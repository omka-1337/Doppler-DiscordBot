"""Plugin manifests.

Every plugin ships a ``plugin.json`` next to its code. The manifest is
deliberately plain data: the dashboard's plugin browser has to be able to list
and describe a plugin -- name, version, author, description -- *before* the
plugin's Python is ever imported, both for locally installed plugins and for
ones offered in a remote catalog on GitHub.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Version of the plugin API this bot implements. A plugin declares the API
# version it was written against; see is_api_compatible() for the rule.
CURRENT_API_VERSION = "1.0"

MANIFEST_FILENAME = "plugin.json"

# A plugin id doubles as its settings namespace, its import name and its
# directory name, so it is restricted to a conservative slug.
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,31}$")

_REQUIRED_FIELDS = ("id", "name", "version", "api_version")


class PluginManifestError(Exception):
    """Raised when a plugin.json is missing, malformed or incompatible."""


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    api_version: str
    description: str = ""
    author: str = ""
    icon: str = "🧩"
    entrypoint: str = "plugin.py"
    homepage: str = ""
    # pip requirements the plugin needs. Declared for the dashboard to show;
    # nothing is installed automatically -- pulling arbitrary packages on a
    # user's behalf is the operator's decision, not the plugin's.
    requirements: list[str] = field(default_factory=list)
    # Whether the plugin starts enabled the first time it is discovered.
    default_enabled: bool = True
    # Filesystem location. Empty for manifests fetched from a remote catalog.
    path: Path | None = None

    @property
    def module_name(self) -> str:
        return f"{PLUGIN_PACKAGE}.{self.id}"

    def to_dict(self) -> dict:
        """Serialisable form, for the dashboard and for catalog indexes."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "description": self.description,
            "author": self.author,
            "icon": self.icon,
            "entrypoint": self.entrypoint,
            "homepage": self.homepage,
            "requirements": list(self.requirements),
            "default_enabled": self.default_enabled,
        }


# Synthetic package every plugin is imported under, so that a plugin can use
# relative imports between its own files and so that unloading is a matter of
# dropping one module prefix from sys.modules.
PLUGIN_PACKAGE = "doppler_plugins"


def is_api_compatible(api_version: str) -> bool:
    """Semver-ish: same major, and a minor no newer than what we implement."""
    try:
        want_major, want_minor = (int(p) for p in api_version.split(".")[:2])
        have_major, have_minor = (int(p) for p in CURRENT_API_VERSION.split(".")[:2])
    except (ValueError, TypeError):
        return False
    return want_major == have_major and want_minor <= have_minor


def parse_manifest(data: dict, path: Path | None = None) -> PluginManifest:
    """Validate a decoded plugin.json. Raises PluginManifestError."""
    if not isinstance(data, dict):
        raise PluginManifestError("Manifest must be a JSON object.")

    missing = [f for f in _REQUIRED_FIELDS if not data.get(f)]
    if missing:
        raise PluginManifestError(f"Manifest is missing required field(s): {', '.join(missing)}.")

    plugin_id = data["id"]
    if not isinstance(plugin_id, str) or not _ID_PATTERN.match(plugin_id):
        raise PluginManifestError(
            f"Invalid plugin id {plugin_id!r}: use 3-32 chars, lowercase letters, "
            "digits and underscores, starting with a letter."
        )

    # The id is the import name, so it must match the folder it lives in --
    # otherwise two plugins could claim the same namespace from different dirs.
    if path is not None and path.name != plugin_id:
        raise PluginManifestError(
            f"Plugin id {plugin_id!r} does not match its directory name {path.name!r}."
        )

    api_version = str(data["api_version"])
    if not is_api_compatible(api_version):
        raise PluginManifestError(
            f"Plugin {plugin_id!r} targets plugin API {api_version}, "
            f"but this bot implements {CURRENT_API_VERSION}."
        )

    requirements = data.get("requirements", [])
    if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
        raise PluginManifestError(f"{plugin_id!r}: 'requirements' must be a list of strings.")

    return PluginManifest(
        id=plugin_id,
        name=str(data["name"]),
        version=str(data["version"]),
        api_version=api_version,
        description=str(data.get("description", "")),
        author=str(data.get("author", "")),
        icon=str(data.get("icon", "🧩")),
        entrypoint=str(data.get("entrypoint", "plugin.py")),
        homepage=str(data.get("homepage", "")),
        requirements=requirements,
        default_enabled=bool(data.get("default_enabled", True)),
        path=path,
    )


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Read and validate the plugin.json inside a plugin directory."""
    manifest_path = plugin_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PluginManifestError(f"No {MANIFEST_FILENAME} in {plugin_dir}.")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PluginManifestError(f"Could not read {manifest_path}: {e}") from e

    manifest = parse_manifest(data, path=plugin_dir)

    if not (plugin_dir / manifest.entrypoint).is_file():
        raise PluginManifestError(
            f"{manifest.id!r}: entrypoint {manifest.entrypoint!r} does not exist in {plugin_dir}."
        )

    return manifest
