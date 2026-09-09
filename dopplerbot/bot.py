import discord
import asyncio
import os
import logging
import math
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv
from discord.ext import commands
from aiohttp import web
from dopplerbot.database import init_db, get_settings, set_settings, get_settings_by_category, close_db, get_music_bot
from dopplerbot.plugins import PluginRegistry

load_dotenv()

STARTED_AT = datetime.now(timezone.utc)

COG_EXTENSIONS = [
    "dopplerbot.cogs.cogmanager",
    "dopplerbot.cogs.web_command",
    "dopplerbot.cogs.voice.VoiceManager",
    "dopplerbot.cogs.music.MusicBotsManager",
    "dopplerbot.cogs.music.MusicCommands",
]

# Must stay in sync with MODULE_TOGGLE_MAP in web/app.py.
MODULE_CONFIG = {
    "dopplerbot.cogs.voice.VoiceManager": ("Voice", "voice_enabled"),
    "dopplerbot.cogs.music.MusicBotsManager": ("Modules", "music_bots"),
}

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

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

async def get_prefix(bot, message):
    prefix = await get_settings("prefix", "+")
    return prefix

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents
)

# Plugins are the way forward; the COG_EXTENSIONS above are the modules that
# have not been migrated to the plugin API yet. Both run side by side so the
# bot keeps working while modules move over one at a time.
bot.plugins = PluginRegistry(bot)

# ---------------------------------------------------------------------

# RELOAD COG FROM WEB-PANEL
async def handle_reload_cog(request):
    data = await request.json()
    cog_name = data.get("cog")
    action = data.get("action")

    try:
        if action == "load":
            if cog_name not in bot.extensions:
                await bot.load_extension(cog_name)
                logging.info(f"Loaded via Webhook: {cog_name}")

        elif action == "unload":
            if cog_name in bot.extensions:
                await bot.unload_extension(cog_name)
                logging.info(f"Unloaded via Webhook: {cog_name}")
        return web.json_response({"status": "ok"})

    except Exception as e:
        logging.error(f"Error toggling {cog_name}: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# ---------------------------------------------------------------------

# TOGGLE MUSIC BOTS FROM WEB-PANEL
async def handle_toggle_music_bot(request):
    data = await request.json()
    bot_rowid = data.get("bot_rowid")
    action = data.get("action")

    logging.info(f"Registered cogs: {list(bot.cogs.keys())}")
    cog = bot.get_cog("MusicBotsManager")

    if cog is None:
        return web.json_response({"status": "error", "message": "Music module not loaded"}, status = 400)

    try:
        if action == "start":
            bot_data = await get_music_bot(bot_rowid)

            if bot_data is None:
                return web.json_response({"status": "error", "message": f"Bot with ID {bot_rowid} not found in database",}, status=404,)
                
            _, bot_token, _, _ = bot_data

            if not bot_token:
                return web.json_response({"status": "error", "message": f"Bot {bot_rowid} has no token specified",}, status=400,)

            # pyrefly: ignore [missing-attribute]
            await cog.start_single_bot(bot_rowid, bot_token)

        elif action == "stop":
            # pyrefly: ignore [missing-attribute]
            await cog.stop_music_bot(bot_rowid)

        return web.json_response({"status": "ok"})
    except Exception as e:
        
        logging.error(f"Error toggiling music bot {bot_rowid}: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

# ---------------------------------------------------------------------

# BOT STATS FOR THE WEB DASHBOARD
async def handle_stats(request):
    uptime_seconds = (datetime.now(timezone.utc) - STARTED_AT).total_seconds()

    return web.json_response({
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": uptime_seconds,
        "guild_count": len(bot.guilds),
        "latency_ms": round(bot.latency * 1000) if not math.isnan(bot.latency) else None,
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

# START INTERNAL API
async def start_internal_api():
    app = web.Application()
    app.router.add_post("/internal/toggle-cog", handle_reload_cog)
    app.router.add_post("/internal/toggle-music-bot", handle_toggle_music_bot)
    app.router.add_get("/internal/stats", handle_stats)
    app.router.add_post("/internal/check-admin", handle_check_admin)
    app.router.add_get("/internal/plugins", handle_list_plugins)
    app.router.add_post("/internal/plugins/rescan", handle_rescan_plugins)
    app.router.add_post("/internal/plugins/toggle", handle_toggle_plugin)
    app.router.add_post("/internal/plugins/reload", handle_reload_plugin)
    app.router.add_post("/internal/plugins/settings", handle_plugin_settings)
    # This API is only polled internally (e.g. every few seconds by the dashboard's
    # stats tab) — per-request access logs here are just noise in latest.log.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8001)
    await site.start()
    logging.info("Internal Bot API started on port 8001")

# ---------------------------------------------------------------------

# COGS LOAD
async def load_cogs(bot):
    logging.info("Start loading the cogs...")

    for cog_name in COG_EXTENSIONS:
        if cog_name in MODULE_CONFIG:
            category, key_name = MODULE_CONFIG[cog_name]
            cat_settings = await get_settings_by_category(category)
            is_enabled = cat_settings.get(key_name, "true").lower() == "true"

            if not is_enabled:
                logging.info(f"Skipped disabled cog: {cog_name}")
                continue

        try:
            await bot.load_extension(cog_name)
            logging.info(f"Loaded: {cog_name}")
        except Exception as e:
            logging.error(f"Error in {cog_name}:\n{traceback.format_exc()}")

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

# SLASH COMMAND SYNC
# Also called after a plugin is enabled or reloaded, so its commands appear or
# disappear without waiting for a restart.
async def sync_commands() -> int:
    if not bot.guilds:
        logging.warning("Bot is not in any guild, slash commands not synced.")
        return 0

    guild = bot.guilds[0]
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

# COMMANDS
@bot.command()
async def ping(ctx):
    user_mention = ctx.author.mention
    await ctx.send(f"{user_mention}")

# ---------------------------------------------------------------------

# MAIN START FUNCTION
async def main():
    try:
        logging.info("Initializing SQLite database...")
        await init_db()
        logging.info("Database initialized successfully.")

        await start_internal_api()

        if not TOKEN:
            logging.error("DISCORD_BOT_TOKEN parameter missing in .env file.")
            return

        async with bot:
            await load_cogs(bot)
            await bot.plugins.load_all()
            await bot.start(TOKEN)

    finally:
        await close_db()
        logging.info(f"DB connection succecfuly closed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot execution stopped safely.")