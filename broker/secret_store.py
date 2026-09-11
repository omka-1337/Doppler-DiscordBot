"""Provider credentials, held where plugin code cannot reach them.

The store lives in /secrets, a volume mounted into this container only. The bot
container -- where plugins run -- has no view of it, and the broker never
returns a value: callers get the *result* of a call made with the credential,
never the credential.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("broker.secrets")

SECRETS_DIR = Path("/secrets")
SECRETS_FILE = SECRETS_DIR / "secrets.json"

# Which fields of each section are credentials. Everything else (a provider
# choice, say) is ordinary configuration and safe to read back.
SECRET_FIELDS = {
    "ai": ("gemini_api_key", "deepseek_api_key", "chatgpt_api_key"),
}

# Only the AI provider is here. Anything that needs no credential has no reason
# to pass through this container at all, and belongs to the plugin that wants it.
DEFAULTS = {
    # An empty model means "whatever the provider module defaults to", so an
    # install that never picks one keeps working.
    "ai": {
        "provider": "gemini",
        "gemini_api_key": "", "deepseek_api_key": "", "chatgpt_api_key": "",
        "gemini_model": "", "deepseek_model": "", "chatgpt_model": "",
    },
}


def _load() -> dict:
    try:
        stored = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        stored = {}
    except (OSError, json.JSONDecodeError) as e:
        log.error("Could not read %s: %s", SECRETS_FILE, e)
        stored = {}

    merged = {section: dict(fields) for section, fields in DEFAULTS.items()}
    for section, fields in stored.items():
        if section in merged and isinstance(fields, dict):
            merged[section].update({k: v for k, v in fields.items() if k in merged[section]})

    return merged


def _save(data: dict) -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    SECRETS_FILE.chmod(0o600)


def get(section: str) -> dict:
    """Full section including credentials. For broker-internal use only."""
    return _load().get(section, {})


def describe() -> dict:
    """What the dashboard may see: settings, plus whether each key is set.

    Deliberately never the values themselves -- a dashboard that could read
    them back would be one more place for them to leak.
    """
    data = _load()
    out = {}
    for section, fields in data.items():
        secrets = SECRET_FIELDS.get(section, ())
        out[section] = {k: v for k, v in fields.items() if k not in secrets}
        out[section]["configured"] = {k: bool(fields.get(k)) for k in secrets}
    return out


def update(section: str, values: dict) -> None:
    """Apply a partial update. A blank credential leaves the stored one alone,
    so saving the form without retyping a key does not wipe it."""
    data = _load()
    if section not in data:
        raise KeyError(section)

    secrets = SECRET_FIELDS.get(section, ())
    for key, value in values.items():
        if key not in data[section]:
            continue
        if key in secrets and not str(value).strip():
            continue
        data[section][key] = str(value)

    _save(data)
    log.info("Updated %r credentials.", section)


def import_once(section: str, values: dict) -> bool:
    """Seed a section from an older location, without overwriting anything set."""
    data = _load()
    changed = False
    for key, value in values.items():
        if key in data.get(section, {}) and value and not data[section][key]:
            data[section][key] = str(value)
            changed = True
    if changed:
        _save(data)
    return changed


# First-run seeding: a fresh install can put a provider key straight in .env and
# the broker picks it up here, so it never passes through the bot at all. Not a
# migration -- this is how a new install gets configured without the dashboard.
ENV_SEEDS = [
    ("GEMINI_API_KEY", "ai", "gemini_api_key"),
    ("DEEPSEEK_API_KEY", "ai", "deepseek_api_key"),
    ("OPENAI_API_KEY", "ai", "chatgpt_api_key"),
]


def import_from_env() -> None:
    for env_var, section, key in ENV_SEEDS:
        value = os.getenv(env_var)
        if value and import_once(section, {key: value}):
            log.info("Seeded %s/%s from %s.", section, key, env_var)
