"""The translation backends this plugin uses.

Both live here rather than in the bot: neither needs a credential the plugin is
not allowed to hold. ``google_free`` talks to a public endpoint through
deep-translator, and ``ai`` is just a prompt sent through ``ctx.ai``, where the
provider's key stays on the broker's side exactly as it does for any other
plugin asking for a completion.
"""

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger("plugin.translator")

MODE_FREE = "google_free"
MODE_AI = "ai"


class TranslationError(Exception):
    """Raised when the translation could not be performed."""


@dataclass
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    provider: str


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
    try:
        from deep_translator import GoogleTranslator
    except ImportError as e:
        raise TranslationError(
            "The free backend needs the 'deep-translator' package, which is not "
            "installed. Install it or switch this plugin to AI translation."
        ) from e

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

    return TranslationResult(translated, "auto", target_base_lang, MODE_FREE)


async def _with_ai(ctx, text: str, target_base_lang: str) -> TranslationResult:
    if not await ctx.ai.is_configured():
        raise TranslationError(
            "AI translation is selected but no AI provider is configured. "
            "Set an API key under Settings -> AI Provider."
        )

    target = language_name(target_base_lang)
    system_prompt = (
        f"You are a translation engine. Translate the user's message into {target}.\n"
        "Reply with the translation and nothing else: no quotes, no notes, no "
        "explanation, and no mention of the source language. Preserve the original "
        "formatting, emoji and any @mentions or #channel references exactly as they "
        "appear. If the message is already in the target language, return it unchanged."
    )

    try:
        translated = await ctx.ai.complete(system_prompt, text)
    except Exception as e:
        log.error("AI translation failed: %s", e)
        raise TranslationError(f"The AI provider could not translate: {e}") from e

    if not translated or not translated.strip():
        raise TranslationError("The AI provider returned an empty translation.")

    return TranslationResult(translated.strip(), "auto", target_base_lang, MODE_AI)


async def translate(ctx, text: str, target_base_lang: str, mode: str) -> TranslationResult:
    if mode == MODE_AI:
        return await _with_ai(ctx, text, target_base_lang)
    return await _with_google_free(text, target_base_lang)
