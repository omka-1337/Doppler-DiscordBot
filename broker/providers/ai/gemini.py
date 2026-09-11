import httpx
from google import genai
from google.genai import types

PROVIDER_NAME = "gemini"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-3.1-flash-lite"

# Gemini says which methods each model supports, which already excludes
# embeddings and video. It does not say what a model *produces*, so the models
# that generate speech or pictures still come back as generateContent -- those
# go by name.
_NOT_TEXT = ("-tts", "-image", "-audio")


async def generate_reply(system_prompt: str, prompt: str, api_key: str, model: str = "") -> str:
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return response.text or ""


async def list_models(api_key: str) -> list[str]:
    """Models this key may use for text generation."""
    if not api_key:
        raise ValueError("Gemini API key is not configured.")

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(GEMINI_MODELS_URL, params={"key": api_key, "pageSize": 200})
        response.raise_for_status()
        data = response.json()

    out = []
    for model in data.get("models", []):
        name = (model.get("name") or "").removeprefix("models/")
        if not name or "generateContent" not in (model.get("supportedGenerationMethods") or []):
            continue
        if any(word in name for word in _NOT_TEXT):
            continue
        out.append(name)

    # Alphabetical alone puts the oddities first -- research and computer-use
    # previews ahead of the models anyone actually picks. The main family leads.
    return sorted(out, key=lambda n: (not n.startswith("gemini-"), n))
