"""Chat providers.

Each module exposes ``PROVIDER_NAME`` and
``async generate_reply(system_prompt, prompt, api_key) -> str``, so adding a
provider is a matter of dropping in a module and listing it here.
"""

from . import chatgpt, deepseek, gemini

PROVIDERS = {
    gemini.PROVIDER_NAME: gemini,
    deepseek.PROVIDER_NAME: deepseek,
    chatgpt.PROVIDER_NAME: chatgpt,
}
