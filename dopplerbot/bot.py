import discord
import asyncio
import httpx
import os
import logging
import math
from datetime import datetime, timezone
from dotenv import load_dotenv
from discord.ext import commands
from aiohttp import web
from dopplerbot import __version__
from dopplerbot.database import init_db, get_settings, set_settings, close_db
from dopplerbot.plugins import PluginRegistry
from dopplerbot.plugins import endpoints as plugin_endpoints
from dopplerbot.plugins import trust as plugin_trust
from dopplerbot.plugins.manifest import CURRENT_API_VERSION

load_dotenv()

STARTED_AT = datetime.now(timezone.utc)

# LOGGING
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s]: %(message)s',
    handlers=[
        logging.FileHandler('latest.log', mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
# Privileged; must also be enabled in the Discord Developer Portal. Required for
# on_member_join, which Server Protect uses to post the verify prompt.
intents.members = True

# Resolved at startup rather than at import: the token may not exist yet on a
# fresh install, and the dashboard's first-run setup writes it while this
# container is running.
async def resolve_token() -> str:
    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if token:
        return token

    # This container is deliberately not shown .env, and compose only reads it
    # when the stack comes up -- so first-run setup also stores the token in the
    # database, which is where it is picked up from here. No extra exposure:
    # discord.py holds the token in memory anyway, where plugin code can reach it.
    return (await get_settings("discord_bot_token", "", category="Main") or "").strip()


class DopplerBot(commands.Bot):
    """Slash commands only.

    commands.Bot stays as the base class because plugins register cogs through
    it, but prefix processing is switched off. With no prefix commands left,
    every message would otherwise be parsed as a possible command and each
    mention logged as CommandNotFound — and the AI plugin exists precisely to
    be mentioned.
    """

    async def process_commands(self, message: discord.Message) -> None:
        return


# Required by the constructor and otherwise inert, since the override above
# means it is never consulted.
bot = DopplerBot(
    command_prefix=commands.when_mentioned,
    # discord.py registers a prefix-based !help by default; with prefix
    # processing off it could never run, so it should not be registered.
    help_command=None,
    intents=intents
)

# Everything the bot does comes from plugins; this process only hosts them.
bot.plugins = PluginRegistry(bot)

# ---------------------------------------------------------------------

# ---------------------------------------------------------------------

# MUSIC WORKER BOTS FROM WEB-PANEL
# The worker accounts live in the music plugin's own database, so the dashboard
# cannot read or write them directly -- every change comes through here, which
# updates the row and starts or stops the matching worker in one step.
def _music():
    """The running music plugin and its manager cog, or (None, None)."""
    entry = bot.plugins.loaded.get("music")
    if entry is None:
        return None, None
    return entry.instance, bot.get_cog("MusicBotsManager")


def _music_unavailable():
    return web.json_response(
        {"status": "error", "message": "Music plugin is not running"}, status=503
    )


async def handle_music_list(request):
    plugin, _ = _music()
    if plugin is None:
        return _music_unavailable()
    return web.json_response({"status": "ok", "bots": [list(row) for row in await plugin.store.all()]})


async def handle_music_add(request):
    plugin, _ = _music()
    if plugin is None:
        return _music_unavailable()
    return web.json_response({"status": "ok", "bot_rowid": await plugin.store.add()})


async def handle_music_remove(request):
    plugin, cog = _music()
    if plugin is None:
        return _music_unavailable()

    data = await request.json()
    bot_rowid = data.get("bot_rowid")

    if cog is not None:
        await cog.stop_music_bot(bot_rowid)
    await plugin.store.remove(bot_rowid)
    return web.json_response({"status": "ok"})


async def handle_music_save_token(request):
    plugin, cog = _music()
    if plugin is None:
        return _music_unavailable()

    data = await request.json()
    bot_rowid = data.get("bot_rowid")
    token = data.get("bot_token", "")

    await plugin.store.update(bot_rowid, bot_token=token)

    # Restart the worker so it picks up the new token immediately.
    if cog is not None:
        await cog.stop_music_bot(bot_rowid)
        if token:
            await cog.start_single_bot(bot_rowid, token)
    return web.json_response({"status": "ok"})


async def handle_music_set_active(request):
    plugin, cog = _music()
    if plugin is None:
        return _music_unavailable()

    data = await request.json()
    bot_rowid = data.get("bot_rowid")
    is_active = bool(data.get("is_active"))

    await plugin.store.update(bot_rowid, bot_status=int(is_active))

    if cog is None:
        return web.json_response({"status": "ok"})

    if is_active:
        row = await plugin.store.get(bot_rowid)
        if row is None:
            return web.json_response({"status": "error", "message": "Bot not found"}, status=404)
        if not row[1]:
            return web.json_response(
                {"status": "error", "message": "This bot has no token yet"}, status=400
            )
        await cog.start_single_bot(bot_rowid, row[1])
    else:
        await cog.stop_music_bot(bot_rowid)

    return web.json_response({"status": "ok"})

# Lavalink's address and password are the music plugin's settings now, so the
# dashboard can no longer talk to Lavalink directly -- these proxy for it.
async def handle_music_youtube_status(request):
    plugin, _ = _music()
    if plugin is None:
        return _music_unavailable()

    settings = await plugin.settings.all()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings['lavalink_uri']}/youtube",
                headers={"Authorization": settings["lavalink_password"]},
                timeout=5.0,
            )
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=502)

    if response.status_code != 200:
        return web.json_response({"status": "error", "message": "Lavalink returned an error"}, status=502)

    return web.json_response(
        {"status": "ok", "configured": response.json().get("refreshToken") is not None}
    )


async def handle_music_youtube_token(request):
    plugin, _ = _music()
    if plugin is None:
        return _music_unavailable()

    data = await request.json()
    refresh_token = data.get("refresh_token", "")

    # Stored as a plugin setting so it is also handed to the Lavalink container
    # as environment the next time the sidecar is created.
    await plugin.settings.set("youtube_oauth_refresh_token", refresh_token)

    settings = await plugin.settings.all()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings['lavalink_uri']}/youtube",
                headers={"Authorization": settings["lavalink_password"]},
                json={"refreshToken": refresh_token, "skipInitialization": True},
                timeout=5.0,
            )
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=502)

    if response.status_code != 204:
        return web.json_response({"status": "error", "message": "Lavalink rejected the token"}, status=400)

    return web.json_response({"status": "ok"})

# ---------------------------------------------------------------------

# BOT STATS FOR THE WEB DASHBOARD
async def handle_stats(request):
    uptime_seconds = (datetime.now(timezone.utc) - STARTED_AT).total_seconds()

    return web.json_response({
        "version": __version__,
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": uptime_seconds,
        # Not shown on the dashboard -- the bot locks itself to one guild, so the
        # number says nothing there -- but first-run setup waits on it to know
        # whether the bot has been invited anywhere yet.
        "guild_count": len(bot.guilds),
        "plugins_running": len(bot.plugins.loaded),
        "plugins_total": len(bot.plugins.manifests),
        # Before the gateway connects this is inf, not nan, which the previous
        # isnan() guard let through and round() then refused.
        "latency_ms": round(bot.latency * 1000) if math.isfinite(bot.latency) else None,
        "connected": not bot.is_closed(),
    })

# ---------------------------------------------------------------------

# DASHBOARD LOGIN AUTHORIZATION
# Called by the web dashboard after a Discord OAuth login, to decide whether
# the authenticated account may enter the panel: the home guild's owner, or
# anyone with Administrator permission there.
async def handle_check_admin(request):
    data = await request.json()

    try:
        user_id = int(data.get("user_id"))
    except (TypeError, ValueError):
        return web.json_response({"status": "error", "message": "Invalid user_id"}, status=400)

    if not bot.guilds:
        return web.json_response({"authorized": False})

    guild = bot.guilds[0]
    try:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    except discord.NotFound:
        return web.json_response({"authorized": False})

    authorized = guild.owner_id == user_id or member.guild_permissions.administrator
    return web.json_response({"authorized": authorized})

# ---------------------------------------------------------------------

# PLUGIN MANAGEMENT FROM WEB-PANEL
# The dashboard's plugin page is the only way plugins are turned on, off or
# reloaded; reloading swaps a plugin's code in place, without restarting the bot.
async def handle_list_plugins(request):
    return web.json_response({"plugins": await bot.plugins.describe()})


async def handle_rescan_plugins(request):
    """Pick up plugins added on disk (e.g. just installed from the panel)."""
    bot.plugins.discover()
    return web.json_response({"status": "ok", "plugins": await bot.plugins.describe()})


async def handle_toggle_plugin(request):
    data = await request.json()
    plugin_id = data.get("plugin")
    enabled = bool(data.get("enabled"))

    if plugin_id not in bot.plugins.manifests:
        return web.json_response({"status": "error", "message": "Unknown plugin"}, status=404)

    ok = await bot.plugins.set_enabled(plugin_id, enabled)
    await sync_commands()

    if not ok:
        return web.json_response(
            {"status": "error", "message": bot.plugins.errors.get(plugin_id, "Failed to load")},
            status=500,
        )
    return web.json_response({"status": "ok"})


async def handle_reload_plugin(request):
    data = await request.json()
    plugin_id = data.get("plugin")

    if plugin_id not in bot.plugins.manifests:
        return web.json_response({"status": "error", "message": "Unknown plugin"}, status=404)

    ok = await bot.plugins.reload(plugin_id)
    await sync_commands()

    if not ok:
        return web.json_response(
            {"status": "error", "message": bot.plugins.errors.get(plugin_id, "Reload failed")},
            status=500,
        )
    return web.json_response({"status": "ok"})


async def handle_plugin_settings(request):
    """Save a running plugin's settings, validated against its declared schema."""
    data = await request.json()
    plugin_id = data.get("plugin")
    values = data.get("values") or {}

    entry = bot.plugins.loaded.get(plugin_id)
    if entry is None:
        return web.json_response(
            {"status": "error", "message": "Plugin is not running"}, status=400
        )

    try:
        for key, value in values.items():
            await entry.context.settings.set(key, value)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)

    return web.json_response({"status": "ok"})

# ---------------------------------------------------------------------

# PLUGIN SOURCES AND INSTALLATION
# The broker owns the trust configuration and the plugins directory -- both are
# read-only in this container -- so everything here is a pass-through. The bot
# adds only what the broker cannot know: reloading its own registry afterwards.
BROKER_URL = os.getenv("BROKER_URL", "http://doppler_service_broker:8002")


async def _call_broker(method: str, path: str, payload=None):
    try:
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(f"{BROKER_URL}{path}", timeout=60.0)
            else:
                response = await client.post(f"{BROKER_URL}{path}", json=payload or {}, timeout=300.0)
    except Exception as e:
        return web.json_response(
            {"status": "error", "message": f"Service broker is not reachable: {e}"}, status=503
        )

    return web.json_response(response.json(), status=response.status_code)


async def handle_sources(request):
    return await _call_broker("GET", "/sources")


async def handle_catalog(request):
    return await _call_broker("GET", "/catalog")


async def handle_add_source(request):
    return await _call_broker("POST", "/sources/add", await request.json())


async def handle_trust_source(request):
    return await _call_broker("POST", "/sources/trust", await request.json())


async def handle_remove_source(request):
    return await _call_broker("POST", "/sources/remove", await request.json())


async def handle_install_plugin(request):
    data = await request.json()
    response = await _call_broker("POST", "/plugins/install", data)
    if response.status != 200:
        return response

    plugin_id = data.get("plugin")
    bot.plugins.discover()

    if plugin_id in bot.plugins.loaded:
        # Installing over a running plugin is an upgrade: load() would return
        # early because it is already loaded, leaving the previous version in
        # memory with the new files sitting unused on disk.
        await bot.plugins.reload(plugin_id)
        await sync_commands()
    elif await bot.plugins.is_enabled(plugin_id):
        # Installing something and then having to switch it on separately is a
        # pointless extra step when the plugin says it wants to be on.
        await bot.plugins.load(plugin_id)
        await sync_commands()

    return web.json_response({
        "status": "ok",
        "running": plugin_id in bot.plugins.loaded,
        "error": bot.plugins.errors.get(plugin_id),
    })


async def handle_uninstall_plugin(request):
    data = await request.json()
    plugin_id = data.get("plugin")

    # Unload first: the code has to stop running before its files disappear.
    await bot.plugins.unload(plugin_id, stop_services=True)

    response = await _call_broker("POST", "/plugins/uninstall", data)
    bot.plugins.discover()
    await sync_commands()
    return response

# ---------------------------------------------------------------------

# PLUGIN-SUPPLIED PAGES
# A page is served as plain text and rendered by the dashboard inside a
# sandboxed frame. Trusted sources only, for the same reason endpoints are:
# the page is the plugin's own code running in the operator's browser, and the
# sandbox is a second line of defence rather than the only one.
async def handle_list_plugin_pages(request):
    pages = []
    for plugin_id, entry in bot.plugins.loaded.items():
        page = entry.manifest.page
        if page and plugin_trust.is_trusted(plugin_id):
            pages.append({
                "plugin": plugin_id,
                "title": page.title,
                "icon": page.icon,
                "plugin_name": entry.manifest.name,
            })
    return web.json_response({"status": "ok", "pages": pages})


async def handle_plugin_page(request):
    plugin_id = request.match_info["plugin_id"]
    entry = bot.plugins.loaded.get(plugin_id)

    if entry is None or not entry.manifest.page:
        return web.json_response({"status": "error", "message": "No such page"}, status=404)

    if not plugin_trust.is_trusted(plugin_id):
        return web.json_response(
            {"status": "error", "message": f"{plugin_id!r} came from an untrusted source."}, status=403
        )

    path = (entry.manifest.path / entry.manifest.page.entry).resolve()
    # The manifest parser rejects escaping paths, but a symlink placed inside
    # the plugin folder could still point outside it.
    if not path.is_relative_to(entry.manifest.path.resolve()) or not path.is_file():
        return web.json_response({"status": "error", "message": "Page file is missing"}, status=404)

    return web.Response(text=path.read_text(encoding="utf-8"), content_type="text/plain")

# ---------------------------------------------------------------------

# PLUGIN-DECLARED ENDPOINTS
# Registered in a lookup table rather than the router: aiohttp freezes its
# router once the app is running, and plugins come and go long after that.
async def handle_plugin_endpoint(request):
    plugin_id = request.match_info["plugin_id"]
    path = "/" + request.match_info.get("tail", "")

    handler = plugin_endpoints.lookup(plugin_id, request.method, path)
    if handler is None:
        return web.json_response(
            {"status": "error", "message": f"No {request.method} {path} declared by {plugin_id!r}."},
            status=404,
        )

    try:
        result = await handler(request)
    except Exception as e:
        logging.exception("Plugin endpoint %s %s failed", request.method, path)
        return web.json_response({"status": "error", "message": str(e)}, status=500)

    # Returning a dict is shorthand; anything else is passed through as the
    # plugin's own response.
    if isinstance(result, dict):
        return web.json_response(result)
    return result


async def handle_list_plugin_endpoints(request):
    return web.json_response({"status": "ok", "endpoints": plugin_endpoints.declared()})

# ---------------------------------------------------------------------

# START INTERNAL API
async def start_internal_api():
    app = web.Application()
    app.router.add_get("/internal/music/bots", handle_music_list)
    app.router.add_post("/internal/music/add", handle_music_add)
    app.router.add_post("/internal/music/remove", handle_music_remove)
    app.router.add_post("/internal/music/save-token", handle_music_save_token)
    app.router.add_post("/internal/music/set-active", handle_music_set_active)
    app.router.add_get("/internal/music/youtube", handle_music_youtube_status)
    app.router.add_post("/internal/music/youtube", handle_music_youtube_token)
    app.router.add_get("/internal/stats", handle_stats)
    app.router.add_post("/internal/check-admin", handle_check_admin)
    app.router.add_get("/internal/plugins", handle_list_plugins)
    app.router.add_post("/internal/plugins/rescan", handle_rescan_plugins)
    app.router.add_post("/internal/plugins/toggle", handle_toggle_plugin)
    app.router.add_post("/internal/plugins/reload", handle_reload_plugin)
    app.router.add_post("/internal/plugins/settings", handle_plugin_settings)
    app.router.add_get("/internal/sources", handle_sources)
    app.router.add_post("/internal/sources/add", handle_add_source)
    app.router.add_post("/internal/sources/trust", handle_trust_source)
    app.router.add_post("/internal/sources/remove", handle_remove_source)
    app.router.add_get("/internal/catalog", handle_catalog)
    app.router.add_post("/internal/plugins/install", handle_install_plugin)
    app.router.add_post("/internal/plugins/uninstall", handle_uninstall_plugin)
    app.router.add_get("/internal/plugin-endpoints", handle_list_plugin_endpoints)
    app.router.add_get("/internal/plugin-pages", handle_list_plugin_pages)
    app.router.add_get("/internal/plugin-page/{plugin_id}", handle_plugin_page)
    app.router.add_route("*", "/internal/plugin/{plugin_id}/{tail:.*}", handle_plugin_endpoint)
    # This API is only polled internally (e.g. every few seconds by the dashboard's
    # stats tab) — per-request access logs here are just noise in latest.log.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8001)
    await site.start()
    logging.info("Internal Bot API started on port 8001")

# ---------------------------------------------------------------------

# ---------------------------------------------------------------------

# ---------------------------------------------------------------------

# HOME GUILD LOCK
# This bot is designed for single-guild use (settings, ServerProtect, etc. are
# all global, not per-guild). The first guild it's ever in becomes "home" and
# is persisted; any other guild — whether already joined or invited later — is
# left immediately to avoid two servers silently sharing one bot's config.
async def enforce_home_guild():
    raw_home_id = await get_settings("home_guild_id", "")

    if not raw_home_id:
        if not bot.guilds:
            return
        home_guild = bot.guilds[0]
        await set_settings("home_guild_id", str(home_guild.id), "Main")
        logging.info(f"Home guild locked to: {home_guild.name} ({home_guild.id})")
        home_guild_id = home_guild.id
    else:
        try:
            home_guild_id = int(raw_home_id)
        except ValueError:
            logging.error(f"Invalid home_guild_id setting: {raw_home_id!r}")
            return

    for guild in list(bot.guilds):
        if guild.id != home_guild_id:
            logging.warning(f"Leaving non-home guild: {guild.name} ({guild.id})")
            try:
                await guild.leave()
            except discord.HTTPException as e:
                logging.error(f"Failed to leave guild {guild.id}: {e}")

# ---------------------------------------------------------------------

# THE BOT'S OWN COMMANDS
# Everything else comes from plugins; this is the one command the bot itself
# provides, so an operator can read the running versions from inside Discord
# without opening the dashboard.
@bot.tree.command(name="bot-info", description="Show the bot, plugin API and installed plugin versions.")
@discord.app_commands.default_permissions(manage_guild=True)
async def bot_info(interaction: discord.Interaction):
    running = sorted(bot.plugins.loaded.items())

    embed = discord.Embed(
        title="Doppler",
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Bot version", value=f"`{__version__}`", inline=True)
    embed.add_field(name="Plugin API", value=f"`{CURRENT_API_VERSION}`", inline=True)
    embed.add_field(name="discord.py", value=f"`{discord.__version__}`", inline=True)

    if running:
        # A guild can install more plugins than one field can hold, and Discord
        # rejects the whole message rather than truncating it.
        lines = [
            f"{entry.manifest.icon} **{entry.manifest.name}** `{entry.manifest.version}`"
            for _, entry in running
        ]
        block, shown = "", 0
        for line in lines:
            if len(block) + len(line) + 1 > 1024:
                break
            block += line + "\n"
            shown += 1
        if shown < len(lines):
            block += f"...and {len(lines) - shown} more"
        embed.add_field(name=f"Active plugins ({len(running)})", value=block, inline=False)
    else:
        embed.add_field(name="Active plugins (0)", value="No plugins are running.", inline=False)

    total = len(bot.plugins.manifests)
    if total > len(running):
        embed.set_footer(text=f"{total - len(running)} installed but not running")

    if bot.user and bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------

# SLASH COMMAND SYNC
# Also called after a plugin is enabled or reloaded, so its commands appear or
# disappear without waiting for a restart.
async def sync_commands() -> int:
    if not bot.guilds:
        logging.warning("Bot is not in any guild, slash commands not synced.")
        return 0

    guild = bot.guilds[0]
    # copy_global_to() merges the global commands into whatever the guild copy
    # already holds, so a command whose plugin has been unloaded would stay
    # there and be re-uploaded on every sync. Clearing first makes the guild
    # copy an exact mirror of what is currently loaded.
    bot.tree.clear_commands(guild=guild)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    logging.info(f"Synced {len(synced)} slash command(s) to guild: {guild.name} ({guild.id})")
    return len(synced)

# ---------------------------------------------------------------------

# EVENTS
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")

    await enforce_home_guild()
    await sync_commands()

# ---------------------------------------------------------------------

# Refuse invites to any server other than the locked home guild.
@bot.event
async def on_guild_join(guild: discord.Guild):
    raw_home_id = await get_settings("home_guild_id", "")
    if not raw_home_id:
        return  # not locked yet — on_ready will adopt whichever guild ends up first

    try:
        home_guild_id = int(raw_home_id)
    except ValueError:
        return

    if guild.id != home_guild_id:
        logging.warning(f"Refusing invite: leaving non-home guild {guild.name} ({guild.id})")
        try:
            await guild.leave()
        except discord.HTTPException as e:
            logging.error(f"Failed to leave guild {guild.id}: {e}")

# ---------------------------------------------------------------------

# MAIN START FUNCTION
async def main():
    try:
        logging.info(f"Doppler {__version__} starting up.")
        logging.info("Initializing SQLite database...")
        await init_db()
        logging.info("Database initialized successfully.")

        await start_internal_api()

        token = await resolve_token()
        if not token:
            # Exiting restarts the container, which re-reads the database — so
            # finishing setup in the dashboard brings the bot up on its own.
            logging.error(
                "No bot token configured yet. Finish the first-run setup in the dashboard; "
                "this container will pick it up on its next restart."
            )
            return

        async with bot:
            await bot.plugins.load_all()
            await bot.start(token)

    finally:
        await close_db()
        logging.info(f"DB connection succecfuly closed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot execution stopped safely.")