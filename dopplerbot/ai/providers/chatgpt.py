import httpx

PROVIDER_NAME = "chatgpt"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


async def generate_reply(system_prompt: str, prompt: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("OpenAI API key is not configured.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"] or ""
