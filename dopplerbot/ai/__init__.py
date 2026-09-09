"""Text generation, owned by the bot rather than by any plugin.

The provider and its API key are core settings. A plugin never sees them: it
hands over a system prompt and a prompt through ``ctx.ai`` and gets text back,
and which service answered is none of its business.

This is a layer, not a wall. Plugin code runs inside the bot's process, so a
plugin that went looking could still read the key out of the database. What it
does buy is that a *well-behaved* plugin never holds the key at all, so it
cannot leak one by logging its own settings or shipping them somewhere -- and
one configured provider now serves every plugin instead of each keeping a copy.
"""

import logging

from dopplerbot.database import get_settings_by_category

from .providers import PROVIDERS, gemini

SETTINGS_CATEGORY = "AI"

log = logging.getLogger("ai")


class AIError(Exception):
    """Raised when no provider is usable or the provider call failed."""


async def get_config() -> dict:
    settings = await get_settings_by_category(SETTINGS_CATEGORY)
    provider_name = settings.get("provider", "gemini")
    return {
        "provider": provider_name,
        "api_key": settings.get(f"{provider_name}_api_key", ""),
    }


async def is_configured() -> bool:
    return bool((await get_config())["api_key"])


async def complete(system_prompt: str, prompt: str) -> str:
    """Send a prompt to the configured provider and return its reply."""
    config = await get_config()
    provider_name = config["provider"]

    if not config["api_key"]:
        raise AIError(f"No API key is configured for {provider_name}.")

    provider = PROVIDERS.get(provider_name, gemini)

    try:
        return await provider.generate_reply(system_prompt, prompt, config["api_key"])
    except Exception as e:
        log.error("%s request failed: %s", provider_name, e)
        raise AIError(f"{provider_name} request failed: {e}") from e
