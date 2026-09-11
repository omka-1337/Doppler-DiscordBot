import httpx

PROVIDER_NAME = "chatgpt"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

DEFAULT_MODEL = "gpt-4o-mini"

# OpenAI's model listing says nothing about what a model is for -- no
# capability field, no type. So the only thing to filter on is the name, which
# is guesswork by nature. These are the families that are definitely not text
# chat; anything new and unexpected is better shown than hidden, so this is a
# deny list rather than an allow list.
_NOT_CHAT = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "audio",
    "realtime", "image", "sora", "transcribe", "search", "babbage", "davinci",
)


async def generate_reply(system_prompt: str, prompt: str, api_key: str, model: str = "") -> str:
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model or DEFAULT_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"] or ""


def _looks_like_chat(model_id: str) -> bool:
    lowered = model_id.lower()
    if any(word in lowered for word in _NOT_CHAT):
        return False
    # The chat families are "gpt-...", "chatgpt-..." and the reasoning line
    # "o1", "o3-mini".
    return lowered.startswith(("gpt-", "chatgpt-")) or (
        len(lowered) > 1 and lowered[0] == "o" and lowered[1].isdigit()
    )


async def list_models(api_key: str) -> list[str]:
    """Chat models this key may use, as far as the names let us tell."""
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            OPENAI_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}
        )
        response.raise_for_status()
        data = response.json()

    return sorted(
        m["id"] for m in data.get("data", []) if m.get("id") and _looks_like_chat(m["id"])
    )
