import httpx

PROVIDER_NAME = "deepseek"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELS_URL = "https://api.deepseek.com/models"

DEFAULT_MODEL = "deepseek-chat"


async def generate_reply(system_prompt: str, prompt: str, api_key: str, model: str = "") -> str:
    if not api_key:
        raise ValueError("DeepSeek API key is not configured.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            DEEPSEEK_API_URL,
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


async def list_models(api_key: str) -> list[str]:
    """Every model this key may use.

    DeepSeek only publishes chat models here, so nothing needs filtering out.
    """
    if not api_key:
        raise ValueError("DeepSeek API key is not configured.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            DEEPSEEK_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}
        )
        response.raise_for_status()
        data = response.json()

    return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
