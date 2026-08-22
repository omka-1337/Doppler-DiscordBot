import discord
import asyncio
import os
import logging
import traceback
from dotenv import load_dotenv
from discord.ext import commands
from aiohttp import web
from dopplerbot.database import init_db, get_settings, get_settings_by_category, close_db, get_music_bot

load_dotenv()

COG_EXTENSIONS = [
    "dopplerbot.cogs.cogmanager",
    "dopplerbot.cogs.embed",
    "dopplerbot.cogs.web_command",
    "dopplerbot.cogs.Translator",
    "dopplerbot.cogs.VoiceManager",
    "dopplerbot.cogs.music.MusicBotsManager",
    "dopplerbot.cogs.music.MusicCommands",
    "dopplerbot.cogs.ai.GeminiChat",
    "dopplerbot.cogs.moderation.ModerationCommands",
]

# Must stay in sync with MODULE_TOGGLE_MAP in web/app.py.
MODULE_CONFIG = {
    "dopplerbot.cogs.ai.GeminiChat": ("AI", "ai_enabled"),
    "dopplerbot.cogs.VoiceManager": ("Voice", "voice_enabled"),
    "dopplerbot.cogs.music.MusicBotsManager": ("Modules", "music_bots"),
    "dopplerbot.cogs.moderation.ModerationCommands": ("Modules", "moderation"),
    "dopplerbot.cogs.Translator": ("Modules", "translator"),
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

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

async def get_prefix(bot, message):
    prefix = await get_settings("prefix", "+")
    return prefix

bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents
)

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

# START INTERNAL API
async def start_internal_api():
    app = web.Application()
    app.router.add_post("/internal/toggle-cog", handle_reload_cog)
    app.router.add_post("/internal/toggle-music-bot", handle_toggle_music_bot)
    runner = web.AppRunner(app)
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

# EVENTS
@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")

    if bot.guilds:
        guild = bot.guilds[0]
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logging.info(f"Synced {len(synced)} slash command(s) to guild: {guild.name} ({guild.id})")
    else:
        logging.warning("Bot is not in any guild, slash commands not synced.")

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
            await bot.start(TOKEN)

    finally:
        await close_db()
        logging.info(f"DB connection succecfuly closed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot execution stopped safely.")