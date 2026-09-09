"""Plugin discovery, loading and hot-reloading.

Plugins live in one of two roots:

* ``dopplerbot/plugins/builtin/`` -- shipped with the bot, tracked in git.
* ``plugins/`` at the repo root -- installed at runtime (this is where the
  dashboard's plugin browser will put what it downloads). It is bind-mounted
  into the container and ignored by git, so installed plugins survive an image
  rebuild and never end up in the user's commits.

Every plugin is imported under a single synthetic package, ``doppler_plugins``,
whose search path is those two roots. That buys two things: a plugin's own
files can import each other relatively (``from .helpers import x``), and
unloading is just dropping one module prefix out of ``sys.modules`` -- which is
what makes reloading a plugin without restarting the bot possible.
"""

import importlib
import importlib.machinery
import importlib.util
import inspect
import logging
import sys
import traceback
import types
from dataclasses import dataclass
from pathlib import Path

from dopplerbot.database import get_settings_by_category, set_settings
from dopplerbot.plugins.api import Plugin, PluginContext, ServiceUnavailable
from dopplerbot.plugins.manifest import (
    PLUGIN_PACKAGE,
    PluginManifest,
    PluginManifestError,
    load_manifest,
)

log = logging.getLogger("plugins")

_REPO_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_ROOT = Path(__file__).resolve().parent / "builtin"
INSTALLED_ROOT = _REPO_ROOT / "plugins"

# Builtin first: an installed plugin must not silently shadow a shipped one.
PLUGIN_ROOTS = (BUILTIN_ROOT, INSTALLED_ROOT)

# Settings category holding each plugin's on/off state, keyed by plugin id.
ENABLED_CATEGORY = "Plugins"


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    instance: Plugin
    context: PluginContext


def _install_plugin_package():
    """Register the synthetic ``doppler_plugins`` package over both roots."""
    for root in PLUGIN_ROOTS:
        root.mkdir(parents=True, exist_ok=True)

    search_paths = [str(root) for root in PLUGIN_ROOTS]

    existing = sys.modules.get(PLUGIN_PACKAGE)
    if existing is not None:
        existing.__path__ = search_paths  # type: ignore[attr-defined]
        return

    spec = importlib.machinery.ModuleSpec(PLUGIN_PACKAGE, None, is_package=True)
    spec.submodule_search_locations = search_paths  # type: ignore[assignment]
    package = types.ModuleType(PLUGIN_PACKAGE)
    package.__spec__ = spec
    package.__path__ = search_paths  # type: ignore[attr-defined]
    sys.modules[PLUGIN_PACKAGE] = package


def _find_plugin_class(module: types.ModuleType, plugin_id: str) -> type[Plugin]:
    """A plugin module names its class ``PLUGIN``, or defines exactly one."""
    candidate = getattr(module, "PLUGIN", None)
    if inspect.isclass(candidate) and issubclass(candidate, Plugin):
        return candidate

    found = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and issubclass(obj, Plugin)
        and obj is not Plugin
        and obj.__module__ == module.__name__
    ]
    if len(found) == 1:
        return found[0]
    if not found:
        raise PluginManifestError(
            f"{plugin_id!r}: entrypoint defines no Plugin subclass "
            "(subclass dopplerbot.plugins.api.Plugin, or set PLUGIN = YourClass)."
        )
    raise PluginManifestError(
        f"{plugin_id!r}: entrypoint defines several Plugin subclasses "
        f"({', '.join(c.__name__ for c in found)}); set PLUGIN = YourClass to pick one."
    )


def _purge_modules(module_prefix: str):
    """Drop a plugin's modules so the next import reads the code from disk."""
    doomed = [
        name
        for name in sys.modules
        if name == module_prefix or name.startswith(module_prefix + ".")
    ]
    for name in doomed:
        del sys.modules[name]
    importlib.invalidate_caches()


class PluginRegistry:
    """Owns the lifecycle of every plugin for one bot process."""

    def __init__(self, bot):
        self.bot = bot
        self.manifests: dict[str, PluginManifest] = {}
        self.loaded: dict[str, LoadedPlugin] = {}
        # Discovery/load failures, kept so the dashboard can show what broke
        # instead of the user having to read the log.
        self.errors: dict[str, str] = {}
        _install_plugin_package()

    # ---------------------------------------------------------------- discovery

    def discover(self) -> dict[str, PluginManifest]:
        """Re-scan both roots for valid plugin directories."""
        self.manifests = {}
        self.errors = {}

        for root in PLUGIN_ROOTS:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name.startswith((".", "_")):
                    continue
                try:
                    manifest = load_manifest(entry)
                except PluginManifestError as e:
                    self.errors[entry.name] = str(e)
                    log.warning("Ignoring %s: %s", entry, e)
                    continue

                if manifest.id in self.manifests:
                    self.errors[manifest.id] = (
                        f"Duplicate plugin id, ignoring {entry} "
                        f"(already provided by {self.manifests[manifest.id].path})."
                    )
                    log.warning(self.errors[manifest.id])
                    continue

                self.manifests[manifest.id] = manifest

        log.info("Discovered %d plugin(s): %s", len(self.manifests), ", ".join(self.manifests) or "none")
        return self.manifests

    # ------------------------------------------------------------ enabled state

    async def is_enabled(self, plugin_id: str) -> bool:
        states = await get_settings_by_category(ENABLED_CATEGORY)
        if plugin_id in states:
            return states[plugin_id].strip().lower() == "true"
        manifest = self.manifests.get(plugin_id)
        return manifest.default_enabled if manifest else False

    async def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Persist a plugin's on/off state and apply it immediately."""
        await set_settings(plugin_id, "true" if enabled else "false", ENABLED_CATEGORY)
        if enabled:
            return await self.load(plugin_id)
        # Turning a plugin off should also take its sidecar containers down;
        # a reload should not, or every reload would restart them.
        await self.unload(plugin_id, stop_services=True)
        return True

    # ---------------------------------------------------------------- lifecycle

    async def load(self, plugin_id: str) -> bool:
        """Import and start one plugin. Returns whether it came up."""
        if plugin_id in self.loaded:
            return True

        manifest = self.manifests.get(plugin_id)
        if manifest is None:
            self.errors[plugin_id] = "Plugin not found."
            log.error("Cannot load %r: not discovered.", plugin_id)
            return False

        try:
            # The entrypoint may be a plain file or a package __init__; import
            # the plugin directory as a package either way.
            module = importlib.import_module(manifest.module_name)
            entry_stem = Path(manifest.entrypoint).stem
            if entry_stem != "__init__":
                module = importlib.import_module(f"{manifest.module_name}.{entry_stem}")

            plugin_class = _find_plugin_class(module, plugin_id)
            context = PluginContext(manifest, self.bot, plugin_class.SETTINGS)
            await context.settings.seed_defaults()

            instance = plugin_class(context)
            await instance.setup()

        except Exception as e:
            self.errors[plugin_id] = f"{type(e).__name__}: {e}"
            log.error("Failed to load plugin %r:\n%s", plugin_id, traceback.format_exc())
            _purge_modules(manifest.module_name)
            return False

        self.loaded[plugin_id] = LoadedPlugin(manifest, instance, context)
        self.errors.pop(plugin_id, None)
        log.info("Loaded plugin: %s v%s", manifest.name, manifest.version)
        return True

    async def unload(self, plugin_id: str, stop_services: bool = False) -> bool:
        """Stop one plugin and remove everything it registered.

        `stop_services` also takes down the plugin's sidecar containers. It is
        off for reloads, so swapping a plugin's code doesn't bounce a service
        that takes a while to come back.
        """
        entry = self.loaded.pop(plugin_id, None)
        if entry is None:
            return False

        if stop_services and entry.manifest.services:
            try:
                stopped = await entry.context.services.stop()
                if stopped:
                    log.info("Stopped sidecar service(s) for %r: %s", plugin_id, ", ".join(stopped))
            except ServiceUnavailable as e:
                log.warning("Could not stop %r's services: %s", plugin_id, e)

        try:
            await entry.instance.teardown()
        except Exception:
            log.error("teardown() failed for %r:\n%s", plugin_id, traceback.format_exc())

        # Runs even if teardown() raised, so a buggy plugin can't leave its
        # cogs and views wired into the bot.
        await entry.context._unregister()
        _purge_modules(entry.manifest.module_name)

        log.info("Unloaded plugin: %s", entry.manifest.name)
        return True

    async def reload(self, plugin_id: str) -> bool:
        """Swap in the plugin's code from disk without restarting the bot."""
        await self.unload(plugin_id)
        # Re-read the manifest too: a reload should pick up a bumped version or
        # a changed entrypoint, not just changed Python.
        manifest = self.manifests.get(plugin_id)
        if manifest is not None and manifest.path is not None:
            try:
                self.manifests[plugin_id] = load_manifest(manifest.path)
            except PluginManifestError as e:
                self.errors[plugin_id] = str(e)
                log.error("Cannot reload %r: %s", plugin_id, e)
                return False
        return await self.load(plugin_id)

    async def load_all(self):
        """Discover everything and start whatever is enabled."""
        self.discover()
        for plugin_id in self.manifests:
            if await self.is_enabled(plugin_id):
                await self.load(plugin_id)
            else:
                log.info("Skipped disabled plugin: %s", plugin_id)

    async def unload_all(self):
        for plugin_id in list(self.loaded):
            await self.unload(plugin_id)

    # ------------------------------------------------------------- dashboard IO

    async def describe(self) -> list[dict]:
        """Everything the dashboard needs to render the plugins page."""
        out = []
        for plugin_id, manifest in self.manifests.items():
            entry = self.loaded.get(plugin_id)
            schema = entry.context.settings.schema if entry else []
            out.append({
                **manifest.to_dict(),
                "services": [service.to_dict() for service in manifest.services],
                "installed_from": "builtin" if manifest.path and manifest.path.parent == BUILTIN_ROOT else "installed",
                "enabled": await self.is_enabled(plugin_id),
                "running": entry is not None,
                "error": self.errors.get(plugin_id),
                "settings_schema": [s.to_dict() for s in schema if not s.hidden],
                "values": await entry.context.settings.all() if entry else {},
            })
        return out
