from google import genai
from google.genai import types

PROVIDER_NAME = "gemini"


async def generate_reply(system_prompt: str, prompt: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return response.text or ""
