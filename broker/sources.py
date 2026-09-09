"""Plugin sources, trust, and installing from them.

The trust configuration lives in /config, which is writable here and mounted
read-only into the bot. That is the whole point: plugin code runs inside the
bot's process, so if it could edit this file it could mark its own source
trusted, and the flag would mean nothing. For the same reason installs are
done here rather than in the bot -- a plugin that could write to the plugins
directory could overwrite a trusted plugin's code.

Trust has teeth: the broker refuses to start sidecar containers for a plugin
that came from an untrusted source.
"""

import io
import json
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path

import aiohttp

log = logging.getLogger("broker.sources")

CONFIG_DIR = Path("/config")
SOURCES_FILE = CONFIG_DIR / "sources.json"
INSTALLED_FILE = CONFIG_DIR / "installed.json"
INSTALLED_ROOT = Path("/plugins")

# Refuse absurd downloads outright rather than filling the disk.
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class SourceError(Exception):
    """Raised for an unknown source, a bad catalog, or a failed install."""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as e:
        log.error("Could not read %s: %s", path, e)
        return default


def load_sources() -> list[dict]:
    return _read_json(SOURCES_FILE, {"sources": []}).get("sources", [])


def save_sources(sources: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(json.dumps({"sources": sources}, indent=2) + "\n", encoding="utf-8")


def load_installed() -> dict:
    """{plugin_id: {"source": name, "version": str}} for plugins we installed."""
    return _read_json(INSTALLED_FILE, {})


def save_installed(installed: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLED_FILE.write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")


def find_source(name: str) -> dict:
    for source in load_sources():
        if source.get("name") == name:
            return source
    raise SourceError(f"No configured source named {name!r}.")


def is_trusted(plugin_id: str) -> bool:
    """Whether a plugin may be granted privileged capabilities.

    A plugin the broker did not install is one that shipped with the bot, so it
    is as trusted as the bot itself.
    """
    entry = load_installed().get(plugin_id)
    if entry is None:
        return True

    try:
        return bool(find_source(entry["source"]).get("trusted"))
    except SourceError:
        # The source it came from has since been removed: treat as untrusted.
        return False


def source_of(plugin_id: str) -> str | None:
    entry = load_installed().get(plugin_id)
    return entry["source"] if entry else None


# ---------------------------------------------------------------------

def _catalog_url(source: dict) -> str:
    # The refs/heads/ form is required rather than cosmetic: a branch name
    # containing a slash ("doppler/plugins") is otherwise ambiguous with the
    # file path that follows it.
    return (
        f"https://raw.githubusercontent.com/{source['repo']}/"
        f"refs/heads/{source['branch']}/index.json"
    )


def _archive_url(source: dict) -> str:
    return f"https://codeload.github.com/{source['repo']}/tar.gz/refs/heads/{source['branch']}"


async def fetch_catalog(source: dict) -> dict:
    """Read a source's index.json -- the list of plugins it offers."""
    url = _catalog_url(source)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    raise SourceError(f"{url} returned HTTP {response.status}.")
                body = await response.text()
    except aiohttp.ClientError as e:
        raise SourceError(f"Could not reach {url}: {e}") from e

    try:
        catalog = json.loads(body)
    except json.JSONDecodeError as e:
        raise SourceError(f"{url} is not valid JSON: {e}") from e

    if not isinstance(catalog.get("plugins"), list):
        raise SourceError(f"{url} has no 'plugins' list.")
    return catalog


def _safe_members(tar: tarfile.TarFile, wanted_prefix: str):
    """Yield only regular files under wanted_prefix.

    Archives are downloaded from the internet, so anything that could write
    outside the destination -- absolute paths, '..', links, devices -- is
    dropped rather than trusted.
    """
    for member in tar.getmembers():
        if not member.isfile():
            continue
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            log.warning("Skipping suspicious archive entry %r.", name)
            continue
        if not name.startswith(wanted_prefix):
            continue
        yield member


async def install(source_name: str, plugin_id: str) -> dict:
    """Download one plugin from a source and put it in the plugins directory."""
    source = find_source(source_name)
    url = _archive_url(source)

    chunks: list[bytes] = []
    total = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as response:
                if response.status != 200:
                    raise SourceError(f"{url} returned HTTP {response.status}.")
                # Read to EOF in chunks: a single read() returns only what is
                # already buffered, which truncates the archive.
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise SourceError("Archive is larger than the 64 MB limit.")
                    chunks.append(chunk)
    except aiohttp.ClientError as e:
        raise SourceError(f"Could not download {url}: {e}") from e

    payload = b"".join(chunks)

    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        names = tar.getnames()
        if not names:
            raise SourceError("Archive is empty.")

        # GitHub wraps everything in a single top-level directory whose name
        # depends on the repo and branch, so take it from the archive itself.
        top = names[0].split("/")[0]
        prefix = f"{top}/{plugin_id}/"

        members = list(_safe_members(tar, prefix))
        if not members:
            raise SourceError(f"{source_name!r} has no plugin {plugin_id!r} at its branch root.")

        with tempfile.TemporaryDirectory() as staging:
            staging_path = Path(staging)
            for member in members:
                member.name = member.name[len(prefix):]
                tar.extract(member, staging_path)

            if not (staging_path / "plugin.json").is_file():
                raise SourceError(f"{plugin_id!r} has no plugin.json.")

            target = INSTALLED_ROOT / plugin_id
            INSTALLED_ROOT.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(staging_path, target)
            _make_readable(target)

    manifest = json.loads((INSTALLED_ROOT / plugin_id / "plugin.json").read_text(encoding="utf-8"))

    installed = load_installed()
    installed[plugin_id] = {"source": source_name, "version": manifest.get("version", "")}
    save_installed(installed)

    log.info("Installed %r v%s from %r.", plugin_id, manifest.get("version", "?"), source_name)
    return {"id": plugin_id, "version": manifest.get("version", ""), "source": source_name}


def _make_readable(path: Path) -> None:
    """Give the installed tree sane permissions.

    copytree carries over the mode of the staging directory, which tempfile
    creates as 0700. This container runs as root, so without this the files
    end up unreadable to the person who owns the project on the host.
    """
    path.chmod(0o755)
    for item in path.rglob("*"):
        item.chmod(0o755 if item.is_dir() else 0o644)


def uninstall(plugin_id: str) -> None:
    target = INSTALLED_ROOT / plugin_id
    if not target.is_dir():
        raise SourceError(f"{plugin_id!r} is not installed.")

    shutil.rmtree(target)

    installed = load_installed()
    installed.pop(plugin_id, None)
    save_installed(installed)
    log.info("Uninstalled %r.", plugin_id)
