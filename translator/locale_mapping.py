"""
Maps a discord.Locale (the language of the Discord client that invoked the
command) to a single internal "base" language code, and from there to the
code format each translation provider expects (DeepL / Google).
"""

import discord

# discord locale value (interaction.locale.value) -> our internal base language code
_LOCALE_VALUE_TO_BASE: dict[str, str] = {
    "en-US": "en",
    "en-GB": "en",
    "bg": "bg",
    "zh-CN": "zh-CN",
    "zh-TW": "zh-TW",
    "hr": "hr",
    "cs": "cs",
    "id": "id",
    "da": "da",
    "nl": "nl",
    "fi": "fi",
    "fr": "fr",
    "de": "de",
    "el": "el",
    "hi": "hi",
    "hu": "hu",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "es-419": "es",
    "lt": "lt",
    "no": "no",
    "pl": "pl",
    "pt-BR": "pt-BR",
    "ro": "ro",
    "ru": "ru",
    "es-ES": "es",
    "sv-SE": "sv",
    "th": "th",
    "tr": "tr",
    "uk": "uk",
    "vi": "vi",
}

DEFAULT_BASE_LANG = "en"


def get_base_lang(locale: discord.Locale) -> str:
    """
    discord interaction.locale -> internal base language code
    (e.g. "uk", "pl", "en", "pt-BR", "zh-CN").
    Falls back to English for any locale we don't recognise.
    """
    return _LOCALE_VALUE_TO_BASE.get(str(locale), DEFAULT_BASE_LANG)


# human-readable name + flag, used in the ephemeral reply footer
_BASE_LANG_DISPLAY: dict[str, str] = {
    "en": "🇬🇧 English",
    "uk": "🇺🇦 Ukrainian",
    "pl": "🇵🇱 Polish",
    "de": "🇩🇪 German",
    "fr": "🇫🇷 French",
    "es": "🇪🇸 Spanish",
    "it": "🇮🇹 Italian",
    "pt-BR": "🇧🇷 Portuguese",
    "ru": "🇷🇺 Russian",
    "ja": "🇯🇵 Japanese",
    "ko": "🇰🇷 Korean",
    "zh-CN": "🇨🇳 Chinese",
    "zh-TW": "🇹🇼 Chinese (Taiwan)",
    "nl": "🇳🇱 Dutch",
    "sv": "🇸🇪 Swedish",
    "no": "🇳🇴 Norwegian",
    "da": "🇩🇰 Danish",
    "fi": "🇫🇮 Finnish",
    "cs": "🇨🇿 Czech",
    "hu": "🇭🇺 Hungarian",
    "ro": "🇷🇴 Romanian",
    "bg": "🇧🇬 Bulgarian",
    "el": "🇬🇷 Greek",
    "tr": "🇹🇷 Turkish",
    "vi": "🇻🇳 Vietnamese",
    "th": "🇹🇭 Thai",
    "hi": "🇮🇳 Hindi",
    "id": "🇮🇩 Indonesian",
    "hr": "🇭🇷 Croatian",
    "lt": "🇱🇹 Lithuanian",
}


def display_name(base_lang: str) -> str:
    """Human-readable name (with flag) for a base language code, e.g. for the target language."""
    return _BASE_LANG_DISPLAY.get(base_lang, base_lang.upper())


def display_name_from_provider_code(code: str) -> str:
    """
    Same as display_name(), but normalizes a provider-returned source language
    code first (DeepL returns e.g. "UK"/"PL" uppercase, Google returns
    lowercase, deep-translator may just say "auto").
    """
    return _BASE_LANG_DISPLAY.get(code.lower(), code.upper())
