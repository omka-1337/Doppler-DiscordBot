"""Sidecar service broker.

Plugins declare the containers they need in their manifest, and this service is
the only thing in the stack that talks to Docker. It reads those manifests
itself, from a read-only mount of the project, so the bot -- which runs
third-party plugin code inside its own process -- can only ever *name* a
service. It never describes one.

What this buys and what it doesn't: a plugin's sidecar runs as an ordinary
unprivileged container on the bot's private network, with a memory cap, no
ports published to the host, and no host paths mounted except read-only files
from the plugin's own folder. That does not make an untrusted plugin safe --
its Python still runs in the bot's process -- but it stops "this plugin needs a
container" from meaning "this plugin gets root on the host", which is what
handing the Docker socket to the bot would have meant.
"""

import asyncio
import hashlib
import json
import logging
import os
import socket
from pathlib import Path

import docker
from aiohttp import web

from broker import sources
from dopplerbot.plugins.manifest import PluginManifestError, load_manifest

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s]: %(message)s",
)
log = logging.getLogger("broker")

# The project, mounted read-only. HOST_PROJECT_DIR is the same directory as the
# host sees it: bind mounts are resolved by the Docker daemon on the host, so
# paths inside this container are meaningless to it.
PROJECT_DIR = Path("/project")
HOST_PROJECT_DIR = os.getenv("HOST_PROJECT_DIR", "")

# (path inside this container, path relative to the project on the host).
# Installed plugins come through the writable /plugins mount rather than the
# read-only project view, because the broker is the only thing allowed to
# write there.
PLUGIN_ROOTS = [
    (PROJECT_DIR / "dopplerbot" / "plugins" / "builtin", "dopplerbot/plugins/builtin"),
    (sources.INSTALLED_ROOT, "plugins"),
]


def host_path_for(plugin_dir: Path) -> str:
    """Where a plugin directory lives as the Docker daemon sees it."""
    if not HOST_PROJECT_DIR:
        raise RuntimeError("HOST_PROJECT_DIR is not set, so host paths cannot be resolved.")

    for container_root, host_relative in PLUGIN_ROOTS:
        if plugin_dir.is_relative_to(container_root):
            return f"{HOST_PROJECT_DIR}/{host_relative}/{plugin_dir.relative_to(container_root)}"

    raise RuntimeError(f"{plugin_dir} is not inside a known plugin root.")

LABEL_MANAGED = "doppler.managed"
LABEL_PLUGIN = "doppler.plugin"
LABEL_SERVICE = "doppler.service"
# Fingerprint of the spec a container was created from, so an unchanged
# service can be left running instead of bounced on every plugin reload.
LABEL_SPEC = "doppler.spec"

client = docker.from_env()


def container_name(plugin_id: str, service_name: str) -> str:
    return f"doppler_plg_{plugin_id}_{service_name}"


def spec_fingerprint(spec, environment: dict) -> str:
    """Identity of what would be run, including the resolved environment.

    Values are hashed rather than stored, so secrets never end up in a label.
    """
    payload = json.dumps(
        {
            "image": spec.image,
            "env": sorted(environment.items()),
            "files": sorted(spec.files.items()),
            "memory_mb": spec.memory_mb,
            "port": spec.port,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def discover_manifests() -> dict:
    """Re-read every manifest. Done per request so a freshly installed plugin
    is picked up without restarting the broker."""
    manifests = {}
    for root, _host_relative in PLUGIN_ROOTS:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            try:
                manifest = load_manifest(entry)
            except PluginManifestError as e:
                log.warning("Ignoring %s: %s", entry, e)
                continue
            manifests.setdefault(manifest.id, manifest)
    return manifests


def own_network() -> str | None:
    """The compose network this broker is on, which sidecars join too.

    Sidecars are reachable by container name from the bot and from nothing
    else -- they are never published to the host.
    """
    try:
        me = client.containers.get(socket.gethostname())
        networks = list(me.attrs["NetworkSettings"]["Networks"])
        return networks[0] if networks else None
    except Exception:
        log.exception("Could not determine the broker's own network.")
        return None


def build_mounts(manifest, spec) -> dict:
    """Translate the manifest's file list into host-side read-only binds."""
    if not spec.files:
        return {}

    plugin_dir = manifest.path.resolve()
    host_plugin_dir = host_path_for(plugin_dir)
    volumes = {}

    for source_file, target in spec.files.items():
        resolved = (plugin_dir / source_file).resolve()
        # The manifest parser already rejects absolute paths and "..", but a
        # symlink inside the plugin folder could still point outside it.
        if not resolved.is_relative_to(plugin_dir):
            raise RuntimeError(f"{source_file!r} resolves outside the plugin directory.")
        if not resolved.is_file():
            raise RuntimeError(f"{source_file!r} does not exist in the plugin directory.")

        relative = resolved.relative_to(plugin_dir)
        volumes[f"{host_plugin_dir}/{relative}"] = {"bind": target, "mode": "ro"}

    return volumes


def find_managed(plugin_id: str | None = None, service_name: str | None = None) -> list:
    """Containers this broker owns. Never touches anything it did not create."""
    filters = {"label": [f"{LABEL_MANAGED}=true"]}
    if plugin_id:
        filters["label"].append(f"{LABEL_PLUGIN}={plugin_id}")
    if service_name:
        filters["label"].append(f"{LABEL_SERVICE}={service_name}")
    return client.containers.list(all=True, filters=filters)


def _start(plugin_id: str, service_name: str, env_overrides: dict) -> dict:
    manifests = discover_manifests()
    manifest = manifests.get(plugin_id)
    if manifest is None:
        raise LookupError(f"No installed plugin {plugin_id!r}.")

    spec = next((s for s in manifest.services if s.name == service_name), None)
    if spec is None:
        raise LookupError(f"Plugin {plugin_id!r} declares no service {service_name!r}.")

    # Running a container is the one genuinely privileged thing a plugin can
    # ask for, so it is the thing trust gates.
    if not sources.is_trusted(plugin_id):
        raise PermissionError(
            f"Plugin {plugin_id!r} came from an untrusted source "
            f"({sources.source_of(plugin_id)!r}); sidecar containers are not started for it. "
            "Mark the source trusted in the dashboard if you want to allow this."
        )

    # The caller may fill in values, but only for the variables the manifest
    # declared; it cannot introduce environment of its own.
    unexpected = set(env_overrides) - set(spec.env_from_settings)
    if unexpected:
        raise PermissionError(
            f"Service {service_name!r} does not declare {', '.join(sorted(unexpected))}."
        )

    environment = dict(spec.env)
    for env_name in spec.env_from_settings:
        environment[env_name] = str(env_overrides.get(env_name, ""))

    name = container_name(plugin_id, service_name)
    fingerprint = spec_fingerprint(spec, environment)

    # A container already running from exactly this spec is left alone, so
    # reloading a plugin does not bounce a service that takes time to come back.
    for existing in find_managed(plugin_id, service_name):
        if existing.status == "running" and existing.labels.get(LABEL_SPEC) == fingerprint:
            log.info("%s is already running from the current spec; reusing it.", name)
            return {
                "name": name,
                "id": existing.id[:12],
                "image": spec.image,
                "port": spec.port,
                "uri": f"http://{name}:{spec.port}" if spec.port else None,
                "reused": True,
            }
        log.info("Replacing the previous %s container.", name)
        existing.remove(force=True)

    volumes = build_mounts(manifest, spec)

    try:
        client.images.get(spec.image)
    except docker.errors.ImageNotFound:
        log.info("Pulling %s ...", spec.image)
        client.images.pull(spec.image)

    container = client.containers.run(
        spec.image,
        name=name,
        detach=True,
        environment=environment,
        volumes=volumes,
        network=own_network(),
        mem_limit=f"{spec.memory_mb}m",
        # Everything below is fixed by the broker: a manifest cannot ask for
        # privileges, extra capabilities, host networking or a published port.
        privileged=False,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        restart_policy={"Name": "unless-stopped"},
        labels={
            LABEL_MANAGED: "true",
            LABEL_PLUGIN: plugin_id,
            LABEL_SERVICE: service_name,
            LABEL_SPEC: fingerprint,
        },
    )

    log.info("Started %s (%s) for plugin %r.", name, spec.image, plugin_id)
    return {
        "name": name,
        "id": container.id[:12],
        "image": spec.image,
        "port": spec.port,
        "uri": f"http://{name}:{spec.port}" if spec.port else None,
        "reused": False,
    }


def _stop(plugin_id: str, service_name: str | None) -> list[str]:
    stopped = []
    for container in find_managed(plugin_id, service_name):
        container.remove(force=True)
        stopped.append(container.name)
        log.info("Stopped and removed %s.", container.name)
    return stopped


def _list() -> list[dict]:
    out = []
    for container in find_managed():
        out.append({
            "name": container.name,
            "plugin": container.labels.get(LABEL_PLUGIN),
            "service": container.labels.get(LABEL_SERVICE),
            "status": container.status,
            "image": container.image.tags[0] if container.image.tags else container.image.id[:19],
        })
    return out


# ---------------------------------------------------------------------
# HTTP API. The docker SDK is synchronous, so every call runs in a thread.

async def handle_health(request):
    return web.json_response({"status": "ok", "network": own_network()})


async def handle_list(request):
    services = await asyncio.to_thread(_list)
    return web.json_response({"status": "ok", "services": services})


async def handle_start(request):
    data = await request.json()
    plugin_id = data.get("plugin")
    service_name = data.get("service")
    env = data.get("env") or {}

    if not plugin_id or not service_name:
        return web.json_response({"status": "error", "message": "plugin and service are required"}, status=400)

    try:
        result = await asyncio.to_thread(_start, plugin_id, service_name, env)
    except LookupError as e:
        return web.json_response({"status": "error", "message": str(e)}, status=404)
    except PermissionError as e:
        return web.json_response({"status": "error", "message": str(e)}, status=403)
    except Exception as e:
        log.exception("Failed to start %s/%s", plugin_id, service_name)
        return web.json_response({"status": "error", "message": f"{type(e).__name__}: {e}"}, status=500)

    return web.json_response({"status": "ok", "service": result})


async def handle_stop(request):
    data = await request.json()
    plugin_id = data.get("plugin")
    service_name = data.get("service")

    if not plugin_id:
        return web.json_response({"status": "error", "message": "plugin is required"}, status=400)

    try:
        stopped = await asyncio.to_thread(_stop, plugin_id, service_name)
    except Exception as e:
        log.exception("Failed to stop %s/%s", plugin_id, service_name)
        return web.json_response({"status": "error", "message": str(e)}, status=500)

    return web.json_response({"status": "ok", "stopped": stopped})


# ---------------------------------------------------------------------
# Sources, catalog and installation.

async def handle_sources(request):
    installed = sources.load_installed()
    return web.json_response({
        "status": "ok",
        "sources": sources.load_sources(),
        "installed": installed,
    })


async def handle_add_source(request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    repo = (data.get("repo") or "").strip()
    branch = (data.get("branch") or "main").strip()

    if not name or not repo:
        return web.json_response({"status": "error", "message": "name and repo are required"}, status=400)
    if "/" not in repo or repo.count("/") != 1:
        return web.json_response(
            {"status": "error", "message": "repo must look like owner/repository"}, status=400
        )

    existing = sources.load_sources()
    if any(s["name"] == name for s in existing):
        return web.json_response({"status": "error", "message": f"{name!r} already exists"}, status=409)

    existing.append({
        "name": name,
        "label": (data.get("label") or name).strip(),
        "repo": repo,
        "branch": branch,
        # A newly added source is never trusted by default; marking it trusted
        # is a separate, deliberate act.
        "trusted": False,
    })
    sources.save_sources(existing)
    return web.json_response({"status": "ok", "sources": existing})


async def handle_trust_source(request):
    data = await request.json()
    name = data.get("name")
    trusted = bool(data.get("trusted"))

    existing = sources.load_sources()
    for source in existing:
        if source["name"] == name:
            source["trusted"] = trusted
            sources.save_sources(existing)
            log.info("Source %r is now %s.", name, "trusted" if trusted else "untrusted")
            return web.json_response({"status": "ok", "sources": existing})

    return web.json_response({"status": "error", "message": f"No source named {name!r}"}, status=404)


async def handle_remove_source(request):
    data = await request.json()
    name = data.get("name")

    existing = sources.load_sources()
    remaining = [s for s in existing if s["name"] != name]
    if len(remaining) == len(existing):
        return web.json_response({"status": "error", "message": f"No source named {name!r}"}, status=404)

    sources.save_sources(remaining)
    return web.json_response({"status": "ok", "sources": remaining})


async def handle_catalog(request):
    """Everything on offer, across every configured source."""
    installed = sources.load_installed()
    entries = []
    errors = {}

    for source in sources.load_sources():
        try:
            catalog = await sources.fetch_catalog(source)
        except sources.SourceError as e:
            errors[source["name"]] = str(e)
            continue

        for plugin in catalog.get("plugins", []):
            plugin_id = plugin.get("id")
            if not plugin_id:
                continue
            record = installed.get(plugin_id)
            entries.append({
                **plugin,
                "source": source["name"],
                "source_label": source.get("label", source["name"]),
                "trusted": bool(source.get("trusted")),
                "installed": record is not None,
                "installed_version": record["version"] if record else None,
                # Only meaningful when installed from a different source.
                "installed_from": record["source"] if record else None,
            })

    return web.json_response({"status": "ok", "plugins": entries, "errors": errors})


async def handle_install(request):
    data = await request.json()
    source_name = data.get("source")
    plugin_id = data.get("plugin")

    if not source_name or not plugin_id:
        return web.json_response(
            {"status": "error", "message": "source and plugin are required"}, status=400
        )

    try:
        result = await sources.install(source_name, plugin_id)
    except sources.SourceError as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)
    except Exception as e:
        log.exception("Failed to install %s from %s", plugin_id, source_name)
        return web.json_response({"status": "error", "message": f"{type(e).__name__}: {e}"}, status=500)

    return web.json_response({"status": "ok", "plugin": result})


async def handle_uninstall(request):
    data = await request.json()
    plugin_id = data.get("plugin")

    # Its containers go with it; leaving them running would orphan them.
    try:
        await asyncio.to_thread(_stop, plugin_id, None)
    except Exception:
        log.exception("Failed to stop services for %s during uninstall", plugin_id)

    try:
        await asyncio.to_thread(sources.uninstall, plugin_id)
    except sources.SourceError as e:
        return web.json_response({"status": "error", "message": str(e)}, status=404)

    return web.json_response({"status": "ok"})


def make_app():
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/services", handle_list)
    app.router.add_post("/services/start", handle_start)
    app.router.add_post("/services/stop", handle_stop)
    app.router.add_get("/sources", handle_sources)
    app.router.add_post("/sources/add", handle_add_source)
    app.router.add_post("/sources/trust", handle_trust_source)
    app.router.add_post("/sources/remove", handle_remove_source)
    app.router.add_get("/catalog", handle_catalog)
    app.router.add_post("/plugins/install", handle_install)
    app.router.add_post("/plugins/uninstall", handle_uninstall)
    return app


if __name__ == "__main__":
    log.info("Service broker starting on port 8002 (network=%s)", own_network())
    web.run_app(make_app(), host="0.0.0.0", port=8002, access_log=None)
