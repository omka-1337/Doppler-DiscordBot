from utils.MusicPalyer import MusicPlayer
import asyncio
import logging
import discord
import wavelink
import os

from typing import Dict
from discord.ext import commands
from database import get_all_music_bots, update_music_bot

LAVALINK_URI = os.getenv("LAVALINK_URI", "http://lavalink_music_server:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

class MusicBotsManager(commands.Cog):
    def __init__(self, main_bot: commands.Bot):
        self.main_bot = main_bot
        self.running_bots: Dict[int, discord.Client] = {}
        self._init_task: asyncio.Task | None = None

# ---------------------------------------------------------------------

    # LOAD COG
    async def cog_load(self):
        self._init_task = asyncio.create_task(self.start_music_bots())

# ---------------------------------------------------------------------

    # UNLOAD COG
    async def cog_unload(self):
        logging.info("Stopping all music music bots...")
        tasks = [
            self.stop_music_bot(bot_rowid)
            for bot_rowid in list(self.running_bots.keys())
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

# <==============================> MUSIC BOTS CONTROL IN DASHBOARD <===============================>

    # START MUSIC BOTS
    async def start_music_bots(self):
        await self.main_bot.wait_until_ready()

        bots_data = await get_all_music_bots()
        if not bots_data:
            logging.info("No music bots found in database.")
            return

        for row in bots_data:
            bot_rowid, bot_token, bot_user_id, bot_status = row

            if bot_status != 1:
                logging.info(f"Skipping inactive music bot {bot_rowid}.")
                continue

            await self.start_single_bot(bot_rowid, bot_token)

# ------------------------------------------------------------------------------

    # START SINGLE BOT
    async def start_single_bot(self, bot_rowid: int, bot_token: str):
        if bot_rowid in self.running_bots:
            logging.warning(f"Music bot {bot_rowid} is already running.")
            return

        if not bot_token:
            logging.warning(f"Music bot {bot_rowid} has no token specified.")
            return

        intents = discord.Intents.default()
        sub_bot = discord.Client(intents=intents)

        @sub_bot.event
        async def on_ready(bot=sub_bot):
            if bot.user:
                logging.info(f"Secondary bot ready: {bot.user}")
                await update_music_bot(bot_rowid, bot_user_id=bot.user.id)

                if LAVALINK_PASSWORD is None:
                    logging.error("Lavalink password is not configured.")
                    return

                node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
                await wavelink.Pool.connect(client=bot, nodes=[node])
                logging.info(f"Music bot {bot_rowid} connected to Lavalink.")

        self.running_bots[bot_rowid] = sub_bot
        asyncio.create_task(self._run_sub_bot(sub_bot, bot_token, bot_rowid))

        @sub_bot.event
        async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
            player = payload.player
            if isinstance(player, MusicPlayer):
                await player.play_next()

        @sub_bot.event
        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
            voice_client = member.guild.voice_client
            if not isinstance(voice_client, MusicPlayer):
                return

            channel = voice_client.channel
            if channel is None:
                return

            members = [m for m in channel.members if not m.bot]
            if not members:
                logging.info("Voice channel is empty, disconecting...")
                await voice_client.cleanup_and_disconnect()


# ------------------------------------------------------------------------------

    # START SUB BOT
    async def _run_sub_bot(
        self, bot_instance: discord.Client, token: str, bot_rowid: int
    ):
        try:
            await bot_instance.start(token)
        except discord.errors.LoginFailure:
            logging.error(f"Invalid token for music bot {bot_rowid}.")
            self.running_bots.pop(bot_rowid, None)
        except Exception as e:
            logging.error(f"Error running music bot {bot_rowid}: {e}")
            self.running_bots.pop(bot_rowid, None)

# -------------------------------------------------------------------------------

    # STOP MUSIC BOT
    async def stop_music_bot(self, bot_rowid: int) -> bool:
            bot_instance = self.running_bots.get(bot_rowid)

            if bot_instance is None:
                logging.warning(f"Music bot {bot_rowid} is not running.")
                return False

            try:
                await bot_instance.close()
                logging.info(f"Music bot {bot_rowid} stopped successfully.")
                return True
            except Exception as e:
                logging.error(f"Error while stopping music bot {bot_rowid}: {e}")
                return False
            finally:
                self.running_bots.pop(bot_rowid, None)

# <======================> MUSIC BOTS CONTROL WITH COMMANDS <=========================>

    def find_worker_for_channel(self, voice_channel) -> discord.Client | None:
        for sub_bot in self.running_bots.values():
            for vc in sub_bot.voice_clients:
                # pyrefly: ignore [missing-attribute, unknown-name]
                if vc.channel.id == voice_channel.id:
                    return sub_bot

        for sub_bot in self.running_bots.values():
            if not sub_bot.voice_clients:
                return sub_bot

        return None



async def setup(bot: commands.Bot):
    await bot.add_cog(MusicBotsManager(bot))

