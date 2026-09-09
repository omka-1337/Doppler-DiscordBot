from dopplerbot.database import update_music_bot, add_music_bot, remove_music_bot, get_all_music_bots
import asyncio
import json
import os
import secrets
import time
import uuid
import httpx
import psutil
from urllib.parse import urlencode

from pathlib import Path
from dotenv import load_dotenv
from utils.env_editor import update_env_file
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Form, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from utils.i18n import get_translations

from dopplerbot.database import get_settings, get_settings_by_category, set_settings

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent

env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Persisted once on first run so sessions survive restarts, instead of everyone
# getting logged out whenever the container restarts.
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "")
if not SESSION_SECRET_KEY:
    SESSION_SECRET_KEY = secrets.token_hex(32)
    update_env_file("SESSION_SECRET_KEY", SESSION_SECRET_KEY)
    os.environ["SESSION_SECRET_KEY"] = SESSION_SECRET_KEY

app = FastAPI(title="Bot Dashboard")

EMBEDS_DIR = BASE_DIR / "savedata" / "embeds"
EMBEDS_DIR.mkdir(parents=True, exist_ok=True)

EMBED_IMAGES_DIR = EMBEDS_DIR / "images"
EMBED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

EMBED_IMAGE_MAX_BYTES = 8 * 1024 * 1024
EMBED_IMAGE_ALLOWED_EXT = {".png", ".jpg", ".jpeg"}

LAVALINK_URI = os.getenv("LAVALINK_URI", "http://lavalink_music_server:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

LOG_PATH = BASE_DIR / "latest.log"

# Primes psutil's internal sample so the first /api/stats call already has a
# meaningful (non-blocking) delta to compare against.
psutil.cpu_percent()

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
app.mount("/embed-images", StaticFiles(directory=EMBED_IMAGES_DIR), name="embed-images")

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# ---------------------------------------------------------------------

# DASHBOARD LOGIN (Discord OAuth2)
DISCORD_OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_DEVELOPER_PORTAL_URL = "https://discord.com/developers/applications"

# In-memory CSRF state store: state -> expiry timestamp. Short-lived by design;
# losing it on a restart just means an in-flight login needs retrying.
_pending_login_states: dict[str, float] = {}
LOGIN_STATE_TTL_SECONDS = 600

# Paths reachable without being logged in.
PUBLIC_PATHS = {"/auth/login", "/auth/callback"}
PUBLIC_PREFIXES = ("/static/",)

# The OAuth2 "Client ID" is the bot application's own ID, so it's looked up from
# Discord with the bot token already on hand rather than asking anyone to copy it.
# Cached because it never changes for a given bot. The Client Secret has no such
# lookup — Discord never exposes it to a bot-token-authenticated request — which
# is why that one value still has to be entered by hand.
_cached_client_id: str | None = None


async def get_discord_client_id() -> str | None:
    global _cached_client_id
    if _cached_client_id:
        return _cached_client_id

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DISCORD_API_BASE}/oauth2/applications/@me",
                headers={"Authorization": f"Bot {token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            _cached_client_id = response.json().get("id")
    except Exception as e:
        print(f"Failed to auto-detect the Discord Client ID: {e}")
        return None

    return _cached_client_id


# Login turns itself on — no separate switch — the moment everything it needs
# exists: a bot token, a locked home guild (so there's something to check
# ownership/Administrator against), and a Client Secret. Until then the
# dashboard stays open, so a fresh install can never lock itself out of the
# very settings page that configures this.
async def is_login_configured() -> bool:
    if not os.getenv("DISCORD_BOT_TOKEN") or not os.getenv("DISCORD_CLIENT_SECRET"):
        return False
    home_guild_id = await get_settings("home_guild_id", "")
    return bool(home_guild_id)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        if not await is_login_configured():
            return await call_next(request)

        if not request.session.get("authorized"):
            if path.startswith("/api/") or path.startswith("/ws/"):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            return RedirectResponse("/auth/login")

        return await call_next(request)


app.add_middleware(AuthMiddleware)
# Added last so it wraps AuthMiddleware and runs first, making request.session
# available by the time AuthMiddleware checks it.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY, same_site="lax")

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
    settings_voice = await get_settings_by_category("Voice")
    settings_modules = await get_settings_by_category("Modules")

    t = get_translations("en")

    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "t": t,
            "bot": bot_info,
            "settings_main": settings_main,
            "settings_voice": settings_voice,
            "settings_modules": settings_modules,
            "discord_token": os.getenv("DISCORD_BOT_TOKEN", ""),
            "discord_client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
            "logged_in_username": request.session.get("username", ""),
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
        "discord_client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
    }

# ---------------------------------------------------------------------

# TOKEN & API KEYS SAVE
@app.post("/api/settings/system")
async def save_new_key(
    background_tasks: BackgroundTasks,
    DISCORD_BOT_TOKEN: str = Form(...),
    DISCORD_CLIENT_SECRET: str = Form(""),
):
    current_token = os.getenv("DISCORD_BOT_TOKEN", "")
    token_changed = False

    if DISCORD_BOT_TOKEN and not DISCORD_BOT_TOKEN.startswith("****"):
        if DISCORD_BOT_TOKEN != current_token:
            update_env_file("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN)
            token_changed = True

    if DISCORD_CLIENT_SECRET and not DISCORD_CLIENT_SECRET.startswith("****"):
        update_env_file("DISCORD_CLIENT_SECRET", DISCORD_CLIENT_SECRET)
        os.environ["DISCORD_CLIENT_SECRET"] = DISCORD_CLIENT_SECRET

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
    "voice": ("dopplerbot.cogs.voice.VoiceManager", "Voice", "voice_enabled"),
    "music": ("dopplerbot.cogs.music.MusicBotsManager", "Modules", "music_bots"),
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

# ------------------------------PLUGINS--------------------------------

# The bot process owns the plugin registry -- it is the one that imports the
# code and holds the running instances -- so the dashboard only proxies to it.
BOT_INTERNAL_API = "http://doppler_discord_bot:8001"


async def _call_bot(method: str, path: str, payload: dict | None = None) -> dict:
    """Call the bot's internal API, turning transport errors into HTTP 503."""
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{BOT_INTERNAL_API}{path}", timeout=10.0)
            else:
                response = await client.post(f"{BOT_INTERNAL_API}{path}", json=payload or {}, timeout=15.0)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Bot is not reachable: {e}") from e

    if response.status_code >= 400:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response.json()


class PluginTogglePayload(BaseModel):
    plugin: str
    enabled: bool


class PluginActionPayload(BaseModel):
    plugin: str


class PluginSettingsPayload(BaseModel):
    plugin: str
    values: dict


@app.get("/api/plugins")
async def list_plugins():
    return JSONResponse(await _call_bot("GET", "/internal/plugins"))


@app.post("/api/plugins/rescan")
async def rescan_plugins():
    """Re-scan the plugins directory, e.g. after a plugin was added on disk."""
    return JSONResponse(await _call_bot("POST", "/internal/plugins/rescan"))


@app.post("/api/plugins/toggle")
async def toggle_plugin(payload: PluginTogglePayload):
    return JSONResponse(await _call_bot(
        "POST", "/internal/plugins/toggle",
        {"plugin": payload.plugin, "enabled": payload.enabled},
    ))


@app.post("/api/plugins/reload")
async def reload_plugin(payload: PluginActionPayload):
    """Swap a plugin's code in place, without restarting the bot."""
    return JSONResponse(await _call_bot("POST", "/internal/plugins/reload", {"plugin": payload.plugin}))


@app.post("/api/plugins/settings")
async def save_plugin_settings(payload: PluginSettingsPayload):
    return JSONResponse(await _call_bot(
        "POST", "/internal/plugins/settings",
        {"plugin": payload.plugin, "values": payload.values},
    ))

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

# ---------------------------------------------------------------------

# DASHBOARD STATS (host CPU/RAM + the bot process's own uptime/latency)
@app.get("/api/stats")
async def get_stats():
    mem = psutil.virtual_memory()

    stats = {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": mem.percent,
        "memory_used_mb": round(mem.used / (1024 * 1024)),
        "memory_total_mb": round(mem.total / (1024 * 1024)),
        "bot": None,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://doppler_discord_bot:8001/internal/stats", timeout=3.0)
            if response.status_code == 200:
                stats["bot"] = response.json()
    except Exception as e:
        print(f"Failed to fetch bot stats: {e}")

    return JSONResponse(stats)

# ---------------------------------------------------------------------

# LIVE LOG STREAM
# Tails latest.log (shared with the bot container via the same bind mount)
# and pushes new lines to the browser over a WebSocket.
@app.websocket("/ws/logs")
async def stream_logs(websocket: WebSocket):
    # AuthMiddleware doesn't run for WebSocket connections, so the same check
    # (including the same bypass while login isn't configured yet) is repeated
    # here. SessionMiddleware itself does populate the session for WebSockets.
    if await is_login_configured() and not websocket.session.get("authorized"):
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        last_size = 0

        if LOG_PATH.exists():
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-200:]
            if lines:
                await websocket.send_text("\n".join(line.rstrip("\n") for line in lines))
            last_size = LOG_PATH.stat().st_size

        while True:
            await asyncio.sleep(1)

            if not LOG_PATH.exists():
                continue

            current_size = LOG_PATH.stat().st_size

            # The bot's logging.FileHandler is opened in "w" mode, so a bot
            # restart truncates the file — treat a shrink as "start over".
            if current_size < last_size:
                last_size = 0

            if current_size > last_size:
                with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_size)
                    new_content = f.read()
                last_size = current_size

                new_lines = [line for line in new_content.splitlines() if line.strip()]
                if new_lines:
                    await websocket.send_text("\n".join(new_lines))

    except WebSocketDisconnect:
        pass

# ---------------------------------------------------------------------

# DASHBOARD LOGIN: renders the "Login with Discord" page.
# redirect_uri is derived from whatever address the browser is actually using,
# so localhost / a LAN IP / a domain all work — but each one has to be listed
# in the application's OAuth2 redirect list, which is the single most common
# thing to get wrong, so the page spells that address out with a copy button
# and links straight to the right Developer Portal page.
@app.get("/auth/login", response_class=HTMLResponse)
async def auth_login(request: Request):
    redirect_uri = f"{str(request.base_url).rstrip('/')}/auth/callback"
    client_id = await get_discord_client_id()

    portal_url = (
        f"{DISCORD_DEVELOPER_PORTAL_URL}/{client_id}/oauth2"
        if client_id
        else DISCORD_DEVELOPER_PORTAL_URL
    )

    context = {
        "redirect_uri": redirect_uri,
        "portal_url": portal_url,
        "error": request.query_params.get("error_message"),
    }

    if not client_id:
        context["error"] = context["error"] or (
            "Couldn't reach Discord with the bot token, so the login link can't be built yet."
        )
        return templates.TemplateResponse(request=request, name="login.html", context=context)

    state = secrets.token_urlsafe(24)
    _pending_login_states[state] = time.time() + LOGIN_STATE_TTL_SECONDS

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    context["discord_auth_url"] = f"{DISCORD_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    return templates.TemplateResponse(request=request, name="login.html", context=context)

# ---------------------------------------------------------------------

# DASHBOARD LOGIN: OAuth2 callback — exchanges the code, then asks the bot
# container whether this Discord account owns the home guild or has
# Administrator there before granting a session.
@app.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    def deny(message: str):
        return RedirectResponse(f"/auth/login?{urlencode({'error_message': message})}")

    if error:
        return deny("Login was cancelled.")

    expiry = _pending_login_states.pop(state or "", None)
    if not expiry or expiry < time.time():
        return deny("That login link expired or was already used. Please try again.")

    client_id = await get_discord_client_id()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "")
    redirect_uri = f"{str(request.base_url).rstrip('/')}/auth/callback"

    try:
        async with httpx.AsyncClient() as client:
            token_res = await client.post(
                DISCORD_OAUTH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            token_res.raise_for_status()
            access_token = token_res.json()["access_token"]

            user_res = await client.get(
                f"{DISCORD_API_BASE}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            user_res.raise_for_status()
            user = user_res.json()
    except Exception as e:
        print(f"Dashboard login OAuth exchange failed: {e}")
        return deny("Discord rejected the login. Double-check the Client Secret and the redirect URI below.")

    user_id = user["id"]

    try:
        async with httpx.AsyncClient() as client:
            check_res = await client.post(
                "http://doppler_discord_bot:8001/internal/check-admin",
                json={"user_id": user_id},
                timeout=5.0,
            )
            authorized = check_res.status_code == 200 and check_res.json().get("authorized", False)
    except Exception as e:
        print(f"Failed to check admin status with the bot container: {e}")
        return deny("Couldn't reach the bot to verify your permissions. Is it running?")

    if not authorized:
        return deny(f"{user.get('username', 'That account')} isn't the server owner or an administrator.")

    request.session["authorized"] = True
    request.session["user_id"] = user_id
    request.session["username"] = user.get("username", "")

    return RedirectResponse("/")

# ---------------------------------------------------------------------

@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login")