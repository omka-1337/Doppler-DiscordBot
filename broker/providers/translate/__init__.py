"""Translation, performed here so the API keys never leave this container.

The caller sends text and a target language and receives the translation. Which
provider answered and what key was used stay on this side.

Selection: DeepL is used only if a DeepL key is set, otherwise Google. For
Google, an API key means the official Cloud Translate API; without one, a free
keyless library is used instead.
"""

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger("broker.translate")


class TranslationError(Exception):
    """Raised when no backend could perform the translation."""


@dataclass
class TranslationResult:
    translated_text: str
    source_lang: str      # detected source language, as the provider reported it
    target_lang: str      # the base language code we were asked for
    provider_used: str    # "deepl" / "google-cloud" / "google-free"


# DeepL wants uppercase codes, with a few spelled-out regional variants.
_BASE_TO_DEEPL = {
    "en": "EN-US",
    "pt-BR": "PT-BR",
    "zh-CN": "ZH",
    "zh-TW": "ZH",
    "no": "NB",
}

# Google codes work for both the official API and the keyless fallback.
_BASE_TO_GOOGLE = {"pt-BR": "pt"}


def to_deepl_lang(base_lang: str) -> str:
    return _BASE_TO_DEEPL.get(base_lang, base_lang.upper())


def to_google_lang(base_lang: str) -> str:
    return _BASE_TO_GOOGLE.get(base_lang, base_lang.lower())


async def _with_deepl(text: str, target_base_lang: str, api_key: str) -> TranslationResult:
    import deepl

    translator = deepl.Translator(api_key)
    # deepl's client is synchronous, so it runs in a thread to keep the loop free.
    raw = await asyncio.to_thread(
        translator.translate_text, text, target_lang=to_deepl_lang(target_base_lang)
    )
    result = raw[0] if isinstance(raw, list) else raw

    return TranslationResult(result.text, result.detected_source_lang, target_base_lang, "deepl")


async def _with_google_cloud(text: str, target_base_lang: str, api_key: str) -> TranslationResult:
    from google.cloud import translate_v2 as translate_client

    client = translate_client.Client(client_options={"api_key": api_key})
    result = await asyncio.to_thread(
        client.translate, text, target_language=to_google_lang(target_base_lang)
    )

    return TranslationResult(
        result["translatedText"],
        result.get("detectedSourceLanguage", "auto"),
        target_base_lang,
        "google-cloud",
    )


async def _with_google_free(text: str, target_base_lang: str) -> TranslationResult:
    from deep_translator import GoogleTranslator

    target = to_google_lang(target_base_lang)
    translated = await asyncio.to_thread(
        lambda: GoogleTranslator(source="auto", target=target).translate(text)
    )

    return TranslationResult(translated, "auto", target_base_lang, "google-free")


async def translate(text: str, target_base_lang: str, config: dict) -> TranslationResult:
    provider = config.get("provider", "google")
    deepl_key = config.get("deepl_api_key") or None
    google_key = config.get("google_api_key") or None

    if provider == "deepl" and not deepl_key:
        provider = "google"

    try:
        if provider == "deepl" and deepl_key:
            return await _with_deepl(text, target_base_lang, deepl_key)
        if google_key:
            return await _with_google_cloud(text, target_base_lang, google_key)
        return await _with_google_free(text, target_base_lang)
    except Exception as e:
        log.error("Translation failed (provider=%s): %s", provider, e)
        raise TranslationError(str(e)) from e
