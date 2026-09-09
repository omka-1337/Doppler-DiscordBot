"""The surface a plugin is written against.

A plugin imports only from here::

    from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

Two ideas drive the design:

* **Namespaced settings.** A plugin reads and writes its own settings through
  ``ctx.settings``, which is bound to that plugin's id as the settings
  category. It cannot reach the core's keys (the bot token, the session secret)
  or another plugin's keys through this object, and it never touches ``.env``
  or the database module itself.
* **Settings declared in code.** ``Plugin.SETTINGS`` is the single source of
  truth: the dashboard generates the plugin's settings form from it, defaults
  are seeded from it on first load, and reads/writes of an undeclared key are
  rejected -- a typo in a key name becomes an error instead of a setting that
  silently never applies.

This is a namespace boundary, not a security sandbox. A plugin is Python
running in the bot's own process, so it *could* reach anything if it set out
to. The API's job is to make sure a well-behaved plugin never has a reason to
go looking. Treat installing a third-party plugin as running third-party code.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import discord

from dopplerbot.database import SAVEDATA_DIR, get_settings, get_settings_by_category, set_settings
from dopplerbot.plugins.manifest import PluginManifest

if TYPE_CHECKING:
    from discord.ext import commands

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SettingType(str, Enum):
    """Field kinds the dashboard knows how to render.

    Values are plain strings so the schema serialises straight to JSON for the
    panel's form generator.
    """

    STRING = "string"      # single-line text
    TEXT = "text"          # multi-line textarea (e.g. a system prompt)
    SECRET = "secret"      # password-style input, masked in the panel
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"          # toggle switch
    SELECT = "select"      # dropdown; requires choices
    SLIDER = "slider"      # numeric range; requires min/max
    CHANNEL = "channel"    # Discord channel id
    ROLE = "role"          # Discord role id


class PluginSettingError(Exception):
    """Raised for an invalid settings schema or an undeclared settings key."""


@dataclass(frozen=True)
class PluginSetting:
    """One field in a plugin's settings form."""

    key: str
    type: SettingType = SettingType.STRING
    default: Any = ""
    label: str = ""
    description: str = ""
    # SELECT only: (stored value, label shown in the panel) pairs.
    choices: Sequence[tuple[str, str]] = field(default_factory=tuple)
    # SLIDER / INT / FLOAT bounds.
    min: float | None = None
    max: float | None = None
    step: float | None = None
    # Persisted like any other setting, but not rendered in the panel. For
    # runtime state a plugin wants to survive a restart (e.g. "lockdown is
    # currently active") rather than something the operator sets.
    hidden: bool = False

    def __post_init__(self):
        if not _KEY_PATTERN.match(self.key):
            raise PluginSettingError(
                f"Invalid setting key {self.key!r}: lowercase letters, digits and "
                "underscores only, starting with a letter."
            )
        if self.type is SettingType.SELECT and not self.choices:
            raise PluginSettingError(f"Setting {self.key!r} is a select but declares no choices.")
        if self.type is SettingType.SLIDER and (self.min is None or self.max is None):
            raise PluginSettingError(f"Setting {self.key!r} is a slider but declares no min/max.")

    def coerce(self, raw: str) -> Any:
        """Turn the stored string into the Python type this setting describes."""
        if self.type is SettingType.BOOL:
            return str(raw).strip().lower() in ("true", "1", "yes", "on")
        if self.type in (SettingType.INT, SettingType.CHANNEL, SettingType.ROLE):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return int(self.default or 0)
        if self.type in (SettingType.FLOAT, SettingType.SLIDER):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float(self.default or 0)
        return "" if raw is None else str(raw)

    @staticmethod
    def serialize(value: Any) -> str:
        """Everything is stored as TEXT; booleans get the same spelling the core uses."""
        if isinstance(value, bool):
            return "true" if value else "false"
        return "" if value is None else str(value)

    def to_dict(self) -> dict:
        """Schema for the dashboard's form generator."""
        return {
            "key": self.key,
            "type": self.type.value,
            "default": self.serialize(self.default),
            "label": self.label or self.key.replace("_", " ").title(),
            "description": self.description,
            "choices": [{"value": v, "label": l} for v, l in self.choices],
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "hidden": self.hidden,
        }


class ScopedSettings:
    """A plugin's view of the settings table, locked to its own namespace.

    Every read and write goes to the ``settings`` row whose category equals the
    plugin id, and only for keys the plugin declared in ``Plugin.SETTINGS``.
    """

    def __init__(self, namespace: str, schema: Sequence[PluginSetting]):
        self._namespace = namespace
        self._schema = {s.key: s for s in schema}

    def _field(self, key: str) -> PluginSetting:
        try:
            return self._schema[key]
        except KeyError:
            raise PluginSettingError(
                f"{self._namespace!r} has no declared setting {key!r}. "
                f"Declared: {', '.join(sorted(self._schema)) or '(none)'}."
            ) from None

    @property
    def schema(self) -> list[PluginSetting]:
        return list(self._schema.values())

    async def seed_defaults(self):
        """Insert declared settings that aren't in the database yet.

        Existing values are never overwritten, so an upgraded plugin that adds
        a new setting picks up its default without disturbing the others.
        """
        existing = await get_settings_by_category(self._namespace)
        for setting in self._schema.values():
            if setting.key not in existing:
                await set_settings(setting.key, PluginSetting.serialize(setting.default), self._namespace)

    async def get(self, key: str) -> Any:
        """Read one setting, already coerced to its declared type."""
        setting = self._field(key)
        raw = await get_settings(key, None, category=self._namespace)
        if raw is None:
            return setting.coerce(PluginSetting.serialize(setting.default))
        return setting.coerce(raw)

    async def set(self, key: str, value: Any):
        setting = self._field(key)
        await set_settings(key, PluginSetting.serialize(value), self._namespace)

    async def all(self) -> dict[str, Any]:
        """Every declared setting, coerced. Missing rows fall back to defaults."""
        raw = await get_settings_by_category(self._namespace)
        return {
            key: setting.coerce(raw.get(key, PluginSetting.serialize(setting.default)))
            for key, setting in self._schema.items()
        }


class PluginContext:
    """Everything a plugin is handed at load time."""

    def __init__(self, manifest: PluginManifest, bot: "commands.Bot", schema: Sequence[PluginSetting]):
        self.manifest = manifest
        self.id = manifest.id
        self.bot = bot
        self.log = logging.getLogger(f"plugin.{manifest.id}")
        self.settings = ScopedSettings(manifest.id, schema)
        # Registrations tracked so unloading a plugin really removes it -- this
        # is what makes reloading a plugin without restarting the bot work.
        self._cogs: list[str] = []
        self._views: list[discord.ui.View] = []

    @property
    def data_dir(self) -> Path:
        """A private directory for this plugin's files, created on first use."""
        path = SAVEDATA_DIR / "plugins" / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def savedata_dir(self) -> Path:
        """The bot's shared data directory.

        Only for data a plugin has to share with the dashboard -- the embed
        plugin reads the templates the panel's builder writes, for instance.
        Anything private to the plugin belongs in ``data_dir``.
        """
        return SAVEDATA_DIR

    async def add_cog(self, cog: "commands.Cog"):
        """Register a cog and remember it, so unload can take it back out."""
        await self.bot.add_cog(cog)
        self._cogs.append(cog.qualified_name)

    def add_view(self, view: discord.ui.View):
        """Register a persistent view (timeout=None with explicit custom_ids)."""
        self.bot.add_view(view)
        self._views.append(view)

    async def _unregister(self):
        """Undo every registration made through this context."""
        for cog_name in reversed(self._cogs):
            try:
                await self.bot.remove_cog(cog_name)
            except Exception:
                self.log.exception("Failed to remove cog %s", cog_name)
        self._cogs.clear()

        for view in self._views:
            try:
                view.stop()
                # discord.py exposes Client.add_view but no public counterpart,
                # so the persistent-view store has to be reached directly. If a
                # future version moves it, unloading still succeeds -- the view
                # is stopped either way, it just stays registered until restart.
                store = getattr(getattr(self.bot, "_connection", None), "_view_store", None)
                if store is None:
                    self.log.warning("Cannot unregister persistent views on this discord.py version.")
                else:
                    store.remove_view(view)
            except Exception:
                self.log.exception("Failed to remove a persistent view")
        self._views.clear()


class Plugin:
    """Base class every plugin subclasses.

    Identity (id, name, version) comes from ``plugin.json`` so that the
    dashboard's plugin browser can describe a plugin without importing it;
    this class carries only behaviour and the settings schema.
    """

    # Settings the dashboard renders a form for, and the only keys
    # ctx.settings will read or write.
    SETTINGS: Sequence[PluginSetting] = ()

    def __init__(self, ctx: PluginContext):
        self.ctx = ctx
        self.log = ctx.log
        self.bot = ctx.bot
        self.settings = ctx.settings

    async def setup(self):
        """Called when the plugin is enabled. Register cogs and views here."""

    async def teardown(self):
        """Called when the plugin is disabled or reloaded.

        Cogs and views added through the context are removed automatically;
        override this to stop background tasks or close connections.
        """
