"""Text generation, performed by the broker.

Nothing here holds an API key, and neither does anything else in this process.
The prompt is sent to the broker, which owns the credentials in a volume this
container cannot see, makes the call, and returns only the text.

That matters because plugin code runs in this process and can read anything
this process can. Keeping the key out of it is the only way to keep it away
from an installed plugin.
"""

import logging
import os

import httpx

BROKER_URL = os.getenv("BROKER_URL", "http://doppler_service_broker:8002")

log = logging.getLogger("ai")


class AIError(Exception):
    """Raised when no provider is usable or the provider call failed."""


async def _broker(method: str, path: str, payload: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{BROKER_URL}{path}", timeout=15.0)
            else:
                response = await client.post(f"{BROKER_URL}{path}", json=payload or {}, timeout=180.0)
    except Exception as e:
        raise AIError(f"Service broker is not reachable: {e}") from e

    data = response.json()
    if response.status_code != 200:
        raise AIError(data.get("message", response.text))
    return data


async def is_configured() -> bool:
    """Whether the selected provider has a key, so a caller can fail politely."""
    try:
        providers = (await _broker("GET", "/providers"))["providers"]
    except AIError:
        return False

    section = providers.get("ai", {})
    provider = section.get("provider", "gemini")
    return bool(section.get("configured", {}).get(f"{provider}_api_key"))


async def complete(system_prompt: str, prompt: str) -> str:
    """Send a prompt to the configured provider and return its reply."""
    data = await _broker("POST", "/ai/complete", {"system_prompt": system_prompt, "prompt": prompt})
    return data.get("text", "")
