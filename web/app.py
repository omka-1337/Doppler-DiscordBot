import asyncio
import logging
import os
import platform
import secrets
import time
import httpx
import psutil
from datetime import datetime, timezone
from urllib.parse import urlencode

from pathlib import Path
from dotenv import load_dotenv
from utils.env_editor import update_env_file
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import markdown
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from utils.i18n import get_translations

from dopplerbot import __version__ as DOPPLER_VERSION
from dopplerbot.database import get_settings, get_settings_by_category, set_settings
from dopplerbot.plugins.manifest import CURRENT_API_VERSION
from dopplerbot import logs as bot_logs
from discord import __version__ as discord_version

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



# Primes psutil's internal sample so the first /api/stats call already has a
# meaningful (non-blocking) delta to compare against.
psutil.cpu_percent()

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

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
# Reachable without a session only while setup is unfinished — there is no
# token to log in with yet. Once it is done these fall back under the login
# check like everything else, so they cannot be used to overwrite the token.
SETUP_PREFIXES = ("/setup", "/api/setup/")

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


# Until both of these exist the dashboard has nothing to authenticate against,
# so every request is sent to the first-run setup page. Requiring the client
# secret here — not just the token — is what makes login mandatory rather than
# optional: there is no path to a working dashboard that skips it.
def is_setup_complete() -> bool:
    return bool(os.getenv("DISCORD_BOT_TOKEN") and os.getenv("DISCORD_CLIENT_SECRET"))


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

        if not is_setup_complete():
            if path.startswith(SETUP_PREFIXES):
                return await call_next(request)
            if path.startswith("/api/") or path.startswith("/ws/"):
                return JSONResponse({"detail": "Setup required"}, status_code=503)
            return RedirectResponse("/setup")

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

# Identities come from Discord, and every dashboard render used to ask again.
# That is two API calls per page view, so a burst of renders can be rate limited
# -- and the old code answered a failure with a blank name and no avatar, which
# looks exactly like something being broken. Cached, and a failed refresh keeps
# serving the last good answer rather than throwing it away.
_IDENTITY_TTL = 600.0
_identity_cache: dict[str, tuple[float, object]] = {}

_UNKNOWN_BOT = {"username": "Discord Bot", "global_name": "Discord Bot", "avatar_url": None}


def _cached(key: str):
    entry = _identity_cache.get(key)
    if entry is None:
        return None, False
    stored_at, value = entry
    return value, (time.time() - stored_at) < _IDENTITY_TTL


def _remember(key: str, value):
    _identity_cache[key] = (time.time(), value)
    return value


def _avatar_url(user_id, avatar_hash) -> str | None:
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else None


async def _discord_user(path: str) -> dict | None:
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DISCORD_API_BASE}{path}",
                headers={"Authorization": f"Bot {token}"},
                timeout=10.0,
            )
    except Exception as e:
        logging.warning("Discord lookup %s failed: %s", path, e)
        return None

    if response.status_code != 200:
        # 429 is the one that matters here, and it is temporary by definition.
        logging.warning("Discord lookup %s returned %s", path, response.status_code)
        return None
    return response.json()


async def get_user_avatar(user_id: str) -> str | None:
    """The logged-in account's avatar, looked up with the bot token."""
    if not user_id:
        return None

    key = f"user:{user_id}"
    value, fresh = _cached(key)
    if fresh:
        return value

    data = await _discord_user(f"/users/{user_id}")
    if data is None:
        # Stale beats blank: an avatar from ten minutes ago is still right.
        return value

    return _remember(key, _avatar_url(user_id, data.get("avatar")))


async def get_bot_info() -> dict:
    # The token is read at call time, not from the import-time constant: on a
    # fresh install this process starts without one, and the token entered
    # during setup would otherwise stay invisible until a restart.
    if not os.getenv("DISCORD_BOT_TOKEN", ""):
        return dict(_UNKNOWN_BOT)

    value, fresh = _cached("bot")
    if fresh:
        return dict(value)

    data = await _discord_user("/users/@me")
    if data is None:
        return dict(value) if value else dict(_UNKNOWN_BOT)

    return dict(_remember("bot", {
        "username": data.get("username", "Discord Bot"),
        "global_name": data.get("global_name") or data.get("username"),
        "avatar_url": _avatar_url(data.get("id"), data.get("avatar")),
    }))


def forget_identities() -> None:
    """Drop the cache, so a new token is reflected at once."""
    _identity_cache.clear()


# ---------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    bot_info = await get_bot_info()

    settings_main = await get_settings_by_category("Main")
    settings_modules = await get_settings_by_category("Modules")

    t = get_translations("en")

    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "t": t,
            "bot": bot_info,
            "settings_main": settings_main,
            "settings_modules": settings_modules,
            "discord_token": os.getenv("DISCORD_BOT_TOKEN", ""),
            "discord_client_secret": os.getenv("DISCORD_CLIENT_SECRET", ""),
            "logged_in_username": request.session.get("username", ""),
            "logged_in_avatar": await get_user_avatar(request.session.get("user_id", "")),
        }
    )


# ---------------------------------------------------------------------

# FIRST-RUN SETUP
# Both values are verified against Discord before they can be saved, so a typo
# cannot leave the install in a state where the dashboard is unreachable and the
# bot will not start.

async def _verify_bot_token(token: str) -> dict:
    """Ask Discord who this token belongs to. Also yields the client id."""
    if not token.strip():
        return {"valid": False, "message": "Enter a bot token."}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{DISCORD_API_BASE}/oauth2/applications/@me",
                headers={"Authorization": f"Bot {token.strip()}"},
                timeout=10.0,
            )
    except Exception as e:
        return {"valid": False, "message": f"Could not reach Discord: {e}"}

    if response.status_code == 401:
        return {"valid": False, "message": "Discord rejected this token."}
    if response.status_code != 200:
        return {"valid": False, "message": f"Discord returned HTTP {response.status_code}."}

    app_info = response.json()
    bot_user = app_info.get("bot") or {}
    return {
        "valid": True,
        "client_id": app_info.get("id"),
        "application": app_info.get("name", ""),
        "bot_username": bot_user.get("username", ""),
    }


async def _verify_client_secret(client_id: str, secret: str) -> dict:
    """Verify the secret by actually using it.

    A client-credentials grant is the only way to tell a correct secret from a
    plausible-looking one: Discord will not confirm it any other way, and a
    wrong secret would otherwise only surface as a failed login later.
    """
    if not secret.strip():
        return {"valid": False, "message": "Enter the client secret."}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{DISCORD_API_BASE}/oauth2/token",
                data={"grant_type": "client_credentials", "scope": "identify"},
                auth=(client_id, secret.strip()),
                timeout=10.0,
            )
    except Exception as e:
        return {"valid": False, "message": f"Could not reach Discord: {e}"}

    if response.status_code == 200:
        return {"valid": True}
    if response.status_code in (400, 401):
        return {"valid": False, "message": "Discord rejected this client secret."}
    return {"valid": False, "message": f"Discord returned HTTP {response.status_code}."}


class SetupTokenPayload(BaseModel):
    token: str


class SetupSecretPayload(BaseModel):
    token: str
    client_secret: str


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if is_setup_complete():
        return RedirectResponse("/")

    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "version": DOPPLER_VERSION,
            "redirect_uri": f"{str(request.base_url).rstrip('/')}/auth/callback",
            "portal_url": DISCORD_DEVELOPER_PORTAL_URL,
        },
    )


@app.post("/api/setup/validate-token")
async def setup_validate_token(payload: SetupTokenPayload):
    return JSONResponse(await _verify_bot_token(payload.token))


@app.post("/api/setup/validate-secret")
async def setup_validate_secret(payload: SetupSecretPayload):
    token_check = await _verify_bot_token(payload.token)
    if not token_check["valid"]:
        return JSONResponse({"valid": False, "message": "Check the bot token first."})

    return JSONResponse(await _verify_client_secret(token_check["client_id"], payload.client_secret))


# Permissions the bundled plugins actually need — deliberately not Administrator:
# temporary voice channels, moderation, the verified role, and revoking invites
# during a raid lockdown.
INVITE_PERMISSIONS = 1099796925494


@app.get("/api/setup/status")
async def setup_status():
    """Whether the bot is up yet, and whether it has joined a server.

    The setup page waits on this instead of jumping straight to login: the bot
    container needs a moment to start, and login cannot authorise anyone until
    the bot is actually in a guild to check ownership against.
    """
    client_id = await get_discord_client_id()
    invite_url = (
        f"{DISCORD_OAUTH_AUTHORIZE_URL}?client_id={client_id}"
        f"&scope=bot+applications.commands&permissions={INVITE_PERMISSIONS}"
        if client_id else None
    )

    online, guilds = False, 0
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BOT_INTERNAL_API}/internal/stats", timeout=3.0)
        if response.status_code == 200:
            stats = response.json()
            online = bool(stats.get("connected"))
            guilds = stats.get("guild_count", 0)
    except Exception:
        pass  # not up yet; the page keeps waiting

    return JSONResponse({"bot_online": online, "guild_count": guilds, "invite_url": invite_url})


@app.post("/api/setup/save")
async def setup_save(payload: SetupSecretPayload):
    # Re-verified here rather than trusting the browser: the buttons that
    # enabled saving live on the client, and this endpoint is reachable without
    # them.
    token_check = await _verify_bot_token(payload.token)
    if not token_check["valid"]:
        raise HTTPException(status_code=400, detail=token_check.get("message", "Invalid bot token."))

    secret_check = await _verify_client_secret(token_check["client_id"], payload.client_secret)
    if not secret_check["valid"]:
        raise HTTPException(status_code=400, detail=secret_check.get("message", "Invalid client secret."))

    token = payload.token.strip()
    secret = payload.client_secret.strip()

    update_env_file("DISCORD_BOT_TOKEN", token)
    update_env_file("DISCORD_CLIENT_SECRET", secret)
    os.environ["DISCORD_BOT_TOKEN"] = token
    os.environ["DISCORD_CLIENT_SECRET"] = secret
    forget_identities()

    # The bot container is not shown .env, and compose only reads it when the
    # stack comes up — so the token also goes in the database, where the bot
    # looks on its next restart.
    await set_settings("discord_bot_token", token, "Main")

    global _cached_client_id
    _cached_client_id = token_check["client_id"]

    return JSONResponse({
        "status": "ok",
        "bot_username": token_check.get("bot_username", ""),
    })

# ---------------------------------------------------------------------

# PLUGIN API REFERENCE
# Served from the dashboard rather than linked out: it then matches the version
# actually installed, and stays available on a LAN-only deployment.

# What each declared setting type renders as. Built by iterating the enum, so a
# type added to the code and not described here still shows up in the table
# instead of quietly going missing from the docs.
# The reference itself lives in documentation.md at the repo root, so GitHub and
# the dashboard render one text rather than two that drift apart. This route only
# turns it into HTML; the template carries the styling.
DOCS_SOURCE = BASE_DIR / "documentation.md"


@app.get("/docs/plugins", response_class=HTMLResponse)
async def plugin_api_docs(request: Request):
    # toc_depth 2-2 keeps the sidebar to the section headings. Without it every
    # entry nests under the document's single h1, which is not a useful menu.
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-2"}},
    )
    try:
        body = md.convert(DOCS_SOURCE.read_text(encoding="utf-8"))
    except OSError:
        body = "<p>The reference is missing from this install.</p>"
        md.toc = ""

    return templates.TemplateResponse(
        request=request,
        name="plugin_api.html",
        context={
            "version": DOPPLER_VERSION,
            "api_version": CURRENT_API_VERSION,
            "content": body,
            "toc": md.toc,
        },
    )


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

# ------------------------------PLUGINS--------------------------------

# The bot process owns the plugin registry -- it is the one that imports the
# code and holds the running instances -- so the dashboard only proxies to it.
BOT_INTERNAL_API = "http://doppler_discord_bot:8001"
BROKER_API = os.getenv("BROKER_URL", "http://doppler_service_broker:8002")


async def _call_bot(method: str, path: str, payload: dict | None = None) -> dict:
    """Call the bot's internal API, turning transport errors into HTTP 503."""
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{BOT_INTERNAL_API}{path}", timeout=10.0)
            else:
                response = await client.post(f"{BOT_INTERNAL_API}{path}", json=payload or {}, timeout=15.0)
    except httpx.TimeoutException as e:
        # Not the same thing as unreachable, and saying so sends people looking
        # in the wrong place. Starting a plugin that needs a sidecar can outlast
        # this, especially the first time, when the image still has to be pulled.
        raise HTTPException(
            status_code=504,
            detail="The bot did not answer in time. It may still be working on it "
                   "— give it a moment and check the plugin list.",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Bot is not reachable: {e}") from e

    if response.status_code >= 400:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response.json()


async def _call_broker(method: str, path: str, payload: dict | None = None) -> dict:
    """Talk to the broker directly; see BROKER_API above for why."""
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{BROKER_API}{path}", timeout=15.0)
            else:
                response = await client.post(f"{BROKER_API}{path}", json=payload or {}, timeout=60.0)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Broker is not reachable: {e}") from e

    if response.status_code >= 400:
        try:
            detail = response.json().get("message", response.text)
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response.json()


class ProviderPayload(BaseModel):
    section: str
    values: dict


@app.get("/api/providers")
async def get_providers():
    """Provider settings and which keys are set. Never the keys themselves."""
    return JSONResponse(await _call_broker("GET", "/providers"))


@app.get("/api/providers/models")
async def get_provider_models(provider: str = ""):
    """What the selected provider currently offers, asked of the provider."""
    path = f"/ai/models?provider={provider}" if provider else "/ai/models"
    return JSONResponse(await _call_broker("GET", path))


@app.post("/api/providers")
async def set_providers(payload: ProviderPayload):
    return JSONResponse(await _call_broker(
        "POST", "/providers", {"section": payload.section, "values": payload.values}
    ))


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

class SourcePayload(BaseModel):
    name: str
    repo: str = ""
    branch: str = "main"
    label: str = ""


class SourceTrustPayload(BaseModel):
    name: str
    trusted: bool


class InstallPayload(BaseModel):
    source: str
    plugin: str


@app.get("/api/plugins/sources")
async def list_sources():
    return JSONResponse(await _call_bot("GET", "/internal/sources"))


@app.get("/api/plugins/catalog")
async def plugin_catalog():
    """Everything the configured sources offer, with install state and trust."""
    return JSONResponse(await _call_bot("GET", "/internal/catalog"))


@app.post("/api/plugins/sources/add")
async def add_source(payload: SourcePayload):
    return JSONResponse(await _call_bot("POST", "/internal/sources/add", payload.model_dump()))


@app.post("/api/plugins/sources/trust")
async def trust_source(payload: SourceTrustPayload):
    return JSONResponse(await _call_bot("POST", "/internal/sources/trust", payload.model_dump()))


@app.post("/api/plugins/sources/remove")
async def remove_source(payload: SourceTrustPayload):
    return JSONResponse(await _call_bot("POST", "/internal/sources/remove", {"name": payload.name}))


@app.post("/api/plugins/install")
async def install_plugin(payload: InstallPayload):
    return JSONResponse(await _call_bot("POST", "/internal/plugins/install", payload.model_dump()))


@app.post("/api/plugins/uninstall")
async def uninstall_plugin(payload: PluginActionPayload):
    return JSONResponse(await _call_bot("POST", "/internal/plugins/uninstall", {"plugin": payload.plugin}))

@app.get("/api/bot-info")
async def bot_info():
    """The bot's name and avatar, for plugin pages to render alongside a preview."""
    return JSONResponse(await get_bot_info())


@app.get("/api/guild/options")
async def guild_options():
    """Channels, categories and roles of the home guild, for the pickers."""
    return JSONResponse(await _call_bot("GET", "/internal/guild/options"))


@app.get("/api/plugin-pages")
async def list_plugin_pages():
    return JSONResponse(await _call_bot("GET", "/internal/plugin-pages"))


@app.get("/api/plugin-page/{plugin_id}")
async def get_plugin_page(plugin_id: str):
    """The plugin's own HTML, returned as text for the dashboard to sandbox.

    Deliberately not served as text/html at its own URL: that would give it the
    dashboard's origin, which is exactly what the sandbox exists to prevent.
    """
    url = f"{BOT_INTERNAL_API}/internal/plugin-page/{plugin_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Bot is not reachable: {e}") from e

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code,
                            detail=response.json().get("message", "Page unavailable"))

    return JSONResponse({"status": "ok", "html": response.text})


@app.get("/api/plugin-endpoints")
async def list_plugin_endpoints():
    """What the installed plugins expose, so a plugin's own page can find it."""
    return JSONResponse(await _call_bot("GET", "/internal/plugin-endpoints"))


# Singular "plugin" on purpose: /api/plugins/* is the plugin management API, and
# a catch-all there would shadow it.
@app.api_route("/api/plugin/{plugin_id}/{path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def call_plugin_endpoint(plugin_id: str, path: str, request: Request):
    """Forward to a plugin's own endpoint, behind the dashboard's login.

    The body is streamed through untouched so a plugin can accept uploads as
    well as JSON.
    """
    url = f"{BOT_INTERNAL_API}/internal/plugin/{plugin_id}/{path}"
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ("content-type", "accept")
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                request.method, url,
                content=await request.body(),
                params=dict(request.query_params),
                headers=headers,
                timeout=60.0,
            )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Bot is not reachable: {e}") from e

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )

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
# Tails the bot's current log file (shared through the same bind mount) and
# pushes new lines to the browser over a WebSocket.
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
        path = bot_logs.current_log()
        last_size = 0

        if path is not None and path.exists():
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-200:]
            if lines:
                await websocket.send_text("\n".join(line.rstrip("\n") for line in lines))
            last_size = path.stat().st_size

        while True:
            await asyncio.sleep(1)

            # Re-resolved every tick: restarting the bot opens a new file, and
            # the stream has to follow it rather than sit on the finished one.
            newest = bot_logs.current_log()
            if newest is None:
                continue
            if newest != path:
                path, last_size = newest, 0

            if not path.exists():
                continue

            current_size = path.stat().st_size
            if current_size < last_size:
                last_size = 0

            if current_size > last_size:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_size)
                    new_content = f.read()
                last_size = current_size

                new_lines = [line for line in new_content.splitlines() if line.strip()]
                if new_lines:
                    await websocket.send_text("\n".join(new_lines))

    except WebSocketDisconnect:
        pass


# A log on its own rarely explains anything: the same traceback means different
# things depending on which versions and which plugins produced it. This bundles
# the state around the log into one file a person can read before deciding to
# send it anywhere.
def _mask(value) -> str:
    text = str(value)
    if not text:
        return "(empty)"
    return f"(set, {len(text)} chars)"


def _plugin_lines(plugins: list[dict]) -> list[str]:
    out = []
    for plugin in sorted(plugins, key=lambda p: p.get("id", "")):
        state = "running" if plugin.get("running") else ("enabled" if plugin.get("enabled") else "disabled")
        out.append(
            f"  {plugin.get('id', '?'):<16} {plugin.get('version', '?'):<10} "
            f"api {plugin.get('api_version', '?'):<5} {state:<9} from {plugin.get('installed_from', '?')}"
        )
        if plugin.get("error"):
            out.append(f"      error: {plugin['error']}")

        schema = {f["key"]: f for f in plugin.get("settings_schema", [])}
        values = plugin.get("values", {}) or {}
        for key in sorted(values):
            field = schema.get(key)
            if field is None:
                # Hidden settings carry state, not configuration, and their type
                # is not published -- named but never shown.
                out.append(f"      {key} = (hidden)")
            elif field.get("type") == "secret":
                out.append(f"      {key} = {_mask(values[key])}")
            else:
                out.append(f"      {key} = {values[key]!r}")
    return out


async def _diagnostics_report() -> str:
    lines = [
        "Doppler diagnostics report",
        f"generated  {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "Read this before sending it anywhere: it contains your guild's channel",
        "and role ids, and whatever your log happens to mention. Secrets are",
        "replaced with their length, never their value.",
        "",
        "=" * 72,
        "VERSIONS",
        "=" * 72,
        f"  Doppler      {DOPPLER_VERSION}",
        f"  Plugin API   {CURRENT_API_VERSION}",
        f"  Python       {platform.python_version()}",
        f"  discord.py   {discord_version}",
        f"  Host         {platform.system()} {platform.release()}",
        "",
    ]

    # Each section is optional: a report that stops at the first thing the bot
    # cannot answer is exactly the report nobody can use.
    async def section(title: str, getter):
        lines.append("=" * 72)
        lines.append(title)
        lines.append("=" * 72)
        try:
            lines.extend(await getter())
        except Exception as e:
            lines.append(f"  unavailable: {e}")
        lines.append("")

    async def bot_state():
        stats = await _call_bot("GET", "/internal/stats")
        return [
            f"  started at   {stats.get('started_at', '?')}",
            f"  uptime       {stats.get('uptime_seconds', '?')} s",
            f"  latency      {stats.get('latency_ms')} ms",
            f"  guilds       {stats.get('guild_count', '?')}",
            f"  plugins      {stats.get('plugins_running', '?')} running of {stats.get('plugins_total', '?')}",
        ]

    async def plugins():
        return _plugin_lines((await _call_bot("GET", "/internal/plugins")).get("plugins", []))

    async def providers():
        data = (await _call_broker("GET", "/providers")).get("providers", {})
        out = []
        for section_name, fields in data.items():
            out.append(f"  [{section_name}]")
            for key, value in sorted(fields.items()):
                if key == "configured":
                    for provider, is_set in sorted(value.items()):
                        out.append(f"      {provider} = {'set' if is_set else 'not set'}")
                else:
                    out.append(f"      {key} = {value!r}")
        return out or ["  nothing configured"]

    async def services():
        running = (await _call_broker("GET", "/services")).get("services", [])
        out = []
        for service in running:
            out.append(
                f"  {service.get('name', '?'):<34} {service.get('status', '?'):<10} "
                f"{service.get('plugin', '?')}/{service.get('service', '?')}"
            )
            out.append(f"      image {service.get('image', '?')}")
        return out or ["  none running"]

    await section("BOT", bot_state)
    await section("PLUGINS", plugins)
    await section("AI PROVIDER", providers)
    await section("SIDECAR SERVICES", services)

    lines.append("=" * 72)
    path = bot_logs.current_log()
    lines.append(f"LOG  {path.name if path else '(none)'}")
    lines.append("=" * 72)
    if path is not None and path.exists():
        lines.append(path.read_text(encoding="utf-8", errors="replace"))
    else:
        lines.append("  no log file yet")

    return "\n".join(lines)


@app.get("/api/diagnostics")
async def download_diagnostics():
    """One file describing this install, with the current log at the end."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    return Response(
        content=await _diagnostics_report(),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="doppler-report-{stamp}.txt"'},
    )

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
    request.session["username"] = user.get("global_name") or user.get("username", "")

    return RedirectResponse("/")

# ---------------------------------------------------------------------

@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login")