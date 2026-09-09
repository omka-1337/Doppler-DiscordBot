"""Doppler's plugin system.

Plugins import from :mod:`dopplerbot.plugins.api`; the bot uses
:class:`~dopplerbot.plugins.loader.PluginRegistry` to run them.
"""

from dopplerbot.plugins.api import (
    Plugin,
    PluginContext,
    PluginSetting,
    PluginSettingError,
    ScopedSettings,
    SettingType,
)
from dopplerbot.plugins.loader import BUILTIN_ROOT, INSTALLED_ROOT, PluginRegistry
from dopplerbot.plugins.manifest import (
    CURRENT_API_VERSION,
    MANIFEST_FILENAME,
    PluginManifest,
    PluginManifestError,
)

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginSetting",
    "PluginSettingError",
    "ScopedSettings",
    "SettingType",
    "PluginRegistry",
    "BUILTIN_ROOT",
    "INSTALLED_ROOT",
    "PluginManifest",
    "PluginManifestError",
    "CURRENT_API_VERSION",
    "MANIFEST_FILENAME",
]
