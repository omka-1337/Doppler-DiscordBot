"""
Translator service: reads the saved provider preference from the settings
table and performs the actual translation call, falling back to Google when
DeepL isn't usable, and falling back further to a free/keyless library when
no Google Cloud key is configured either.

Selection logic:
    1. translator_provider decides the preferred provider ("deepl" / "google").
    2. DeepL is only used if translator_deepl_api_key is actually set;
       otherwise we silently fall back to Google.
    3. For Google: if translator_google_api_key is set, we use the official
       Google Cloud Translate API. Otherwise we fall back to the free,
       keyless `deep-translator` library.
"""

import asyncio
import logging
from dataclasses import dataclass

import database
from utils.translator.LocaleMapping import to_deepl_lang, to_google_lang

logger = logging.getLogger(__name__)


class TranslationError(Exception):
    """Raised when translation could not be performed by any backend."""


@dataclass
class TranslationResult:
    translated_text: str
    source_lang: str      # detected source language, as returned by the provider
    target_lang: str      # base language code we asked to translate into (our format)
    provider_used: str    # "deepl" / "google-cloud" / "google-free"


async def _translate_with_deepl(text: str, target_base_lang: str, api_key: str) -> TranslationResult:
    import deepl

    target_lang = to_deepl_lang(target_base_lang)
    translator = deepl.Translator(api_key)

    # deepl's client is sync, so it's run in a thread to avoid blocking the event loop.
    # translate_text() returns TextResult for a single string, or list[TextResult] for
    # an iterable of strings - narrow it here since we always pass a single string.
    raw_result = await asyncio.to_thread(translator.translate_text, text, target_lang=target_lang)
    result = raw_result[0] if isinstance(raw_result, list) else raw_result

    return TranslationResult(
        translated_text=result.text,
        source_lang=result.detected_source_lang,
        target_lang=target_base_lang,
        provider_used="deepl",
    )


async def _translate_with_google_cloud(text: str, target_base_lang: str, api_key: str) -> TranslationResult:
    from google.cloud import translate_v2 as translate_v2_client

    target_lang = to_google_lang(target_base_lang)
    client = translate_v2_client.Client(client_options={"api_key": api_key})

    result = await asyncio.to_thread(client.translate, text, target_language=target_lang)

    return TranslationResult(
        translated_text=result["translatedText"],
        source_lang=result.get("detectedSourceLanguage", "auto"),
        target_lang=target_base_lang,
        provider_used="google-cloud",
    )


async def _translate_with_google_free(text: str, target_base_lang: str) -> TranslationResult:
    from deep_translator import GoogleTranslator

    target_lang = to_google_lang(target_base_lang)

    def _run() -> str:
        return GoogleTranslator(source="auto", target=target_lang).translate(text)

    translated_text = await asyncio.to_thread(_run)

    return TranslationResult(
        translated_text=translated_text,
        source_lang="auto",
        target_lang=target_base_lang,
        provider_used="google-free",
    )


async def translate(text: str, target_base_lang: str) -> TranslationResult:
    """
    Translates `text` into `target_base_lang` (our internal base language code,
    see locale_mapping.get_base_lang), following the saved provider
    preference and falling back to Google when needed.
    """
    settings = await database.get_settings_by_category("Translator")

    provider = settings.get("translator_provider", "google")
    deepl_api_key = settings.get("translator_deepl_api_key", "") or None
    google_api_key = settings.get("translator_google_api_key", "") or None

    effective_provider = provider
    if effective_provider == "deepl" and not deepl_api_key:
        effective_provider = "google"

    try:
        if effective_provider == "deepl" and deepl_api_key:
            return await _translate_with_deepl(text, target_base_lang, deepl_api_key)

        if google_api_key:
            return await _translate_with_google_cloud(text, target_base_lang, google_api_key)

        return await _translate_with_google_free(text, target_base_lang)

    except Exception as e:
        logger.error(f"Translation failed (provider={effective_provider}): {e}")
        raise TranslationError(str(e)) from e