from dopplerbot.database import update_music_bot, add_music_bot, remove_music_bot, get_all_music_bots
import asyncio
import json
import os
import uuid
import httpx

from pathlib import Path
from dotenv import load_dotenv
from utils.env_editor import update_env_file
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from utils.i18n import get_translations

from dopplerbot.database import get_settings_by_category, set_settings

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

app = FastAPI(title="Bot Dashboard")

EMBEDS_DIR = BASE_DIR / "savedata" / "embeds"
EMBEDS_DIR.mkdir(parents=True, exist_ok=True)

EMBED_IMAGES_DIR = EMBEDS_DIR / "images"
EMBED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

EMBED_IMAGE_MAX_BYTES = 8 * 1024 * 1024
EMBED_IMAGE_ALLOWED_EXT = {".png", ".jpg", ".jpeg"}

LAVALINK_URI = os.getenv("LAVALINK_URI", "http://lavalink_music_server:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
app.mount("/embed-images", StaticFiles(directory=EMBED_IMAGES_DIR), name="embed-images")

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# ---------------------------------------------------------------------

async def get_bot_info() -> dict:
    headers = {"Authorization": f"Bot {TOKEN}"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://discord.com/api/v10/users/@me", headers=headers)
            if response.status_code == 200:
                data = response.json()

                avatar_hash = data.get("avatar")
                user_id = data.get("id")
                avatar_url = (
                    f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
                    if avatar_hash
                    else None
                )

                return {
                    "username": data.get("username", "Discord Bot"),
                    "global_name": data.get("global_name") or data.get("username"),
                    "avatar_url": avatar_url,
                }
        except Exception as e:
            print(f"Error retrieving the bot's profile: {e}")

    return {"username": "Discord Bot", "global_name": "Discord Bot", "avatar_url": None}

# ---------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    bot_info = await get_bot_info()

    settings_main = await get_settings_by_category("Main")
    settings_ai = await get_settings_by_category("AI")
    settings_voice = await get_settings_by_category("Voice")
    settings_modules = await get_settings_by_category("Modules")
    settings_moderation = await get_settings_by_category("Moderation")
    settings_translator = await get_settings_by_category("Translator")

    t = get_translations("en")

    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "t": t,
            "bot": bot_info,
            "settings_main": settings_main,
            "settings_ai": settings_ai,
            "settings_voice": settings_voice,
            "settings_modules": settings_modules,
            "settings_moderation": settings_moderation,
            "settings_translator": settings_translator,
            "discord_token": os.getenv("DISCORD_BOT_TOKEN", ""),
            "gemini_key": os.getenv("GEMINI_API_KEY", "")
        }
    )


class EmbedPayload(BaseModel):
    filename: str
    embed: dict

# ---------------------------------------------------------------------

@app.post("/api/save-embed")
async def save_embed(payload: EmbedPayload):
    if not payload.filename.strip():
        raise HTTPException(status_code=400, detail="The file name cannot be empty")

    clean_filename = "".join(c for c in payload.filename if c.isalnum() or c in ("-", "_")).lower()
    file_path = EMBEDS_DIR / f"{clean_filename}.json"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload.embed, f, ensure_ascii=False, indent=2)
        return {"status": "success", "message": f"The template has been saved as {clean_filename}.json"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------

# UPLOAD IMAGE FOR EMBED
# Stored under savedata/embeds/images/ and served locally for the dashboard preview.
# The bot attaches the file directly when sending (see cogs/embed.py), so this works
# even without a public URL for the dashboard.
@app.post("/api/upload-embed-image")
async def upload_embed_image(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in EMBED_IMAGE_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Only PNG/JPG images are allowed")

    contents = await file.read()
    if len(contents) > EMBED_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 8MB")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = EMBED_IMAGES_DIR / safe_name

    with open(dest, "wb") as f:
        f.write(contents)

    return {"status": "ok", "filename": safe_name}

# ---------------------------------------------------------------------

# SYSTEM & API KEYS ENDPOINTS
@app.get("/api/settings/system")
async def get_system_settings():
    load_dotenv(dotenv_path=env_path, override=True)
    return {
        "discord_bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "")
    }

# ---------------------------------------------------------------------

# TOKEN & API KEYS SAVE
@app.post("/api/settings/system")
async def save_new_key(
    background_tasks: BackgroundTasks,
    DISCORD_BOT_TOKEN: str = Form(...),
    GEMINI_API_KEY: str = Form(...)
):
    current_token = os.getenv("DISCORD_BOT_TOKEN", "")
    token_changed = False

    if DISCORD_BOT_TOKEN and not DISCORD_BOT_TOKEN.startswith("****"):
        if DISCORD_BOT_TOKEN != current_token:
            update_env_file("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN)
            token_changed = True

    if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("****"):
        update_env_file("GEMINI_API_KEY", GEMINI_API_KEY)
        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

    if token_changed:
        background_tasks.add_task(schedule_restart)
        return {"status": "restarting"}

    return {"status": "ok"}

# ---------------------------------------------------------------------

# CATEGORY SETTINGS ENDPOINTS
@app.get("/api/settings/{category}")
async def api_get_settings(category: str):
    settings = await get_settings_by_category(category)
    return JSONResponse(settings)

# ---------------------------------------------------------------------

# SAVE SETTINGS
@app.post("/api/save-settings")
async def save_settings(request: Request):
    data = await request.json()
    category = data.get("category", "Main")
    settings = data.get("settings", {})

    for key, value in settings.items():
        await set_settings(key, str(value), category)

    return JSONResponse({"status": "ok", "message": "Settings saved successfully!"})

# ---------------------------------------------------------------------

MODULE_TOGGLE_MAP = {
    "ai": ("dopplerbot.cogs.ai.GeminiChat", "AI", "ai_enabled"),
    "voice": ("dopplerbot.cogs.VoiceManager", "Voice", "voice_enabled"),
    "music": ("dopplerbot.cogs.music.MusicBotsManager", "Modules", "music_bots"),
    "moderation": ("dopplerbot.cogs.moderation.ModerationCommands", "Modules", "moderation"),
    "translator": ("dopplerbot.cogs.Translator", "Modules", "translator"),
}

class ModuleTogglePayload(BaseModel):
    module: str
    enabled: bool

@app.post("/api/toggle-module")
async def toggle_module(payload: ModuleTogglePayload):
    if payload.module not in MODULE_TOGGLE_MAP:
        raise HTTPException(status_code=400, detail="Unkown module")

    cog_path, category, key_name = MODULE_TOGGLE_MAP[payload.module]

    await set_settings(key_name, "true" if payload.enabled else "false", category)

    action = "load" if payload.enabled else "unload"
    notified = False
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://doppler_discord_bot:8001/internal/toggle-cog",
                json={"cog": cog_path, "action": action},
                timeout=5.0
            )
            notified = response.status_code == 200
    except Exception as e:
        print(f"Failed to notify bot container: {e}")

    return JSONResponse({"status": "ok", "module_notified": notified})

# ----------------------------MUSIC BOTS-------------------------------

# MUSIC BOTS ENDPOINTS
class MusicBotPayload(BaseModel):
    bot_rowid: int
    bot_token: str

@app.post("/api/music/save-token")
async def save_music_bot_token(payload: MusicBotPayload):
    await update_music_bot(payload.bot_rowid, bot_token=payload.bot_token)

    await notify_music_bot(payload.bot_rowid, "stop")
    notified = await notify_music_bot(payload.bot_rowid, "start")

    return JSONResponse({"status": "ok", "bot_notified": notified})

@app.post("/api/music/add-bot")
async def add_music_bot_endpoint():
    bot_rowid = await add_music_bot()
    return JSONResponse({"status": "ok", "bot_rowid": bot_rowid})

@app.get ("/api/music/bots")
async def get_music_bots_endpoint():
    bots = await get_all_music_bots()
    return JSONResponse({"status": "ok", "bots": bots})

# ---------------------------------------------------------------------

class MusicBotIdPayload(BaseModel):
    bot_rowid: int

@app.post("/api/music/remove-bot")
async def remove_music_bot_endpoint(payload: MusicBotIdPayload):
    await notify_music_bot(payload.bot_rowid, "stop")
    await remove_music_bot(payload.bot_rowid)
    return JSONResponse({"status": "ok"})

# ---------------------------------------------------------------------

class ToggleBotPayload(BaseModel):
    bot_rowid: int
    is_active: bool

@app.post("/api/music/toggle-active")
async def toggle_bot_active(payload: ToggleBotPayload):
    await update_music_bot(payload.bot_rowid, bot_status=int(payload.is_active))

    action = "start" if payload.is_active else "stop"
    notified = await notify_music_bot(payload.bot_rowid, action)

    return JSONResponse({"status": "ok", "bot_notified": notified})

# ---------------------------------------------------------------------

# MUSIC BOT WHILE ACTIVE STATUS CHANGED
async def notify_music_bot(bot_rowid: int, action: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://doppler_discord_bot:8001/internal/toggle-music-bot",
                json={"bot_rowid": bot_rowid, "action": action},
                timeout=5.0
            )
            return response.status_code == 200
    except Exception as e:
        print(f"Failed to notify bot conatiner about music bot {bot_rowid}: {e}")
        return False

# ---------------------------OAuth-------------------------------------

@app.get("/api/music/youtube-oauth-status")
async def get_youtube_oauth_status():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{LAVALINK_URI}/youtube",
                headers={"Authorization": LAVALINK_PASSWORD or ""},
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                return JSONResponse({"status": "ok", "configured": data.get("refreshToken") is not None})
            return JSONResponse({"status": "error", "message": "Lavalink returned an error"}, status_code=502)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=502)

# ---------------------------------------------------------------------

class YouTubeOAuthPayload(BaseModel):
    refresh_token: str

@app.post("/api/music/youtube-oauth")
async def set_youtube_oauth(payload: YouTubeOAuthPayload):
    update_env_file("YOUTUBE_OAUTH_REFRESH_TOKEN", payload.refresh_token)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{LAVALINK_URI}/youtube",
                headers={"Authorization": LAVALINK_PASSWORD or ""},
                json={"refreshToken": payload.refresh_token, "skipInitialization": True},
                timeout=5.0
            )
            if response.status_code == 204:
                return JSONResponse({"status": "ok"})
            return JSONResponse({"status": "error", "message": "Lavalink rejected the token"}, status_code=400)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=502)

# ---------------------------------------------------------------------

async def schedule_restart():
    await asyncio.sleep(1)
    os._exit(0)