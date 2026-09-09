"""Translation, performed here so any API key stays out of the bot's process.

Two modes, chosen by the operator:

* ``google_free`` — a keyless library. Costs nothing and needs no setup, but it
  scrapes a public endpoint and gets rate limited under load.
* ``ai`` — the AI provider already configured for the bot. Better with idiom
  and context, and it reuses the one key rather than asking for another.

There is deliberately no DeepL or Google Cloud option any more: both meant a
second credential to obtain and store for a job the configured model already
does.
"""

import asyncio
import logging
from dataclasses import dataclass

from broker.providers import ai as ai_providers

log = logging.getLogger("broker.translate")

PROVIDER_FREE = "google_free"
PROVIDER_AI = "ai"


class TranslationError(Exception):
    """Raised when the translation could not be performed."""


@dataclass
class TranslationResult:
    translated_text: str
    source_lang: str      # detected source language, as the backend reported it
    target_lang: str      # the base language code we were asked for
    provider_used: str


# Google codes for the keyless backend.
_BASE_TO_GOOGLE = {"pt-BR": "pt"}

# Spelled out for the model: "translate into uk" is far weaker than
# "translate into Ukrainian".
_BASE_TO_NAME = {
    "en": "English", "uk": "Ukrainian", "pl": "Polish", "de": "German",
    "fr": "French", "es": "Spanish", "it": "Italian", "pt-BR": "Brazilian Portuguese",
    "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese", "nl": "Dutch", "sv": "Swedish", "no": "Norwegian",
    "da": "Danish", "fi": "Finnish", "cs": "Czech", "hu": "Hungarian",
    "ro": "Romanian", "bg": "Bulgarian", "el": "Greek", "tr": "Turkish",
    "vi": "Vietnamese", "th": "Thai", "hi": "Hindi", "id": "Indonesian",
    "hr": "Croatian", "lt": "Lithuanian",
}


def to_google_lang(base_lang: str) -> str:
    return _BASE_TO_GOOGLE.get(base_lang, base_lang.lower())


def language_name(base_lang: str) -> str:
    return _BASE_TO_NAME.get(base_lang, base_lang)


# The keyless backend scrapes a web endpoint, and when that endpoint refuses --
# rate limiting, most often -- the library hands back the error page's text as
# though it were the translation. There is no exception to catch, so the result
# has to be inspected.
_ERROR_PAGE_MARKERS = (
    "That’s an error",
    "That's an error",
    "Error 500 (Server Error)",
    "Error 429 (Too Many Requests)",
    "<html",
    "<!DOCTYPE",
)


def _looks_like_an_error_page(text: str) -> bool:
    return any(marker.lower() in text.lower() for marker in _ERROR_PAGE_MARKERS)


async def _with_google_free(text: str, target_base_lang: str) -> TranslationResult:
    from deep_translator import GoogleTranslator

    target = to_google_lang(target_base_lang)
    translated = await asyncio.to_thread(
        lambda: GoogleTranslator(source="auto", target=target).translate(text)
    )

    if not translated or not translated.strip():
        raise TranslationError("The free translation backend returned nothing.")

    if _looks_like_an_error_page(translated):
        raise TranslationError(
            "The free translation backend is refusing requests (rate limited). "
            "Switching translation to the AI provider avoids this."
        )

    return TranslationResult(translated, "auto", target_base_lang, PROVIDER_FREE)


async def _with_ai(text: str, target_base_lang: str, ai_config: dict) -> TranslationResult:
    provider_name = ai_config.get("provider", "gemini")
    api_key = ai_config.get(f"{provider_name}_api_key", "")

    if not api_key:
        raise TranslationError(
            "AI translation is selected but no AI provider is configured. "
            "Set an API key under Settings -> Providers."
        )

    target = language_name(target_base_lang)
    system_prompt = (
        f"You are a translation engine. Translate the user's message into {target}.\n"
        "Reply with the translation and nothing else: no quotes, no notes, no "
        "explanation, and no mention of the source language. Preserve the original "
        "formatting, emoji and any @mentions or #channel references exactly as they "
        "appear. If the message is already in the target language, return it unchanged."
    )

    provider = ai_providers.PROVIDERS.get(provider_name, ai_providers.gemini)
    try:
        translated = await provider.generate_reply(system_prompt, text, api_key)
    except Exception as e:
        log.error("AI translation failed (provider=%s): %s", provider_name, e)
        raise TranslationError(f"{provider_name} could not translate: {e}") from e

    if not translated or not translated.strip():
        raise TranslationError("The AI provider returned an empty translation.")

    return TranslationResult(
        translated.strip(), "auto", target_base_lang, f"{PROVIDER_AI}-{provider_name}"
    )


async def translate(text: str, target_base_lang: str, config: dict, ai_config: dict) -> TranslationResult:
    mode = config.get("provider", PROVIDER_FREE)

    if mode == PROVIDER_AI:
        return await _with_ai(text, target_base_lang, ai_config)

    return await _with_google_free(text, target_base_lang)
