"""Whether a plugin may be granted privileged capabilities.

The broker is the authority — it decides about sidecar containers — but the bot
needs the same answer for capabilities it grants itself, and it can compute it
safely: both files below are mounted read-only into this container, so plugin
code cannot forge them.

The rule matches the broker's exactly: trusted only if this plugin was
installed from a source that is marked trusted *right now*. A directory placed
by hand has no record of where it came from, and "no evidence" is not "yes".
"""

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLED_RECORD = _REPO_ROOT / "config" / "installed.json"
SOURCES_FILE = _REPO_ROOT / "config" / "sources.json"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def source_of(plugin_id: str) -> str | None:
    entry = _read(INSTALLED_RECORD, {}).get(plugin_id)
    return entry.get("source") if isinstance(entry, dict) else None


def is_trusted(plugin_id: str) -> bool:
    name = source_of(plugin_id)
    if not name:
        return False

    for source in _read(SOURCES_FILE, {}).get("sources", []):
        if source.get("name") == name:
            return bool(source.get("trusted"))
    return False
