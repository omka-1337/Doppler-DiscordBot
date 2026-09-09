"""Translation, performed by the broker.

Same arrangement as text generation: the DeepL and Google keys live in the
broker's volume, which this container cannot see. Text goes out, a translation
comes back, and the credential never enters the process plugins run in.
"""

import logging
import os
from dataclasses import dataclass

import httpx

BROKER_URL = os.getenv("BROKER_URL", "http://doppler_service_broker:8002")

log = logging.getLogger("translate")


class TranslationError(Exception):
    """Raised when the translation could not be performed."""


@dataclass
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    provider: str


async def translate(text: str, target_lang: str, mode: str = "google_free") -> TranslationResult:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BROKER_URL}/translate",
                json={"text": text, "target_lang": target_lang, "mode": mode},
                timeout=60.0,
            )
    except Exception as e:
        raise TranslationError(f"Service broker is not reachable: {e}") from e

    data = response.json()
    if response.status_code != 200:
        raise TranslationError(data.get("message", response.text))

    return TranslationResult(
        text=data["text"],
        source_lang=data.get("source_lang", "auto"),
        target_lang=data.get("target_lang", target_lang),
        provider=data.get("provider", "unknown"),
    )
