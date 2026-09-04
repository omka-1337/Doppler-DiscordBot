from utils.music.MusicPlayer import MusicPlayer
import asyncio
import logging
import discord
import wavelink
import os

from typing import Dict
from discord.ext import commands
from dopplerbot.database import get_all_music_bots, update_music_bot

LAVALINK_URI = os.getenv("LAVALINK_URI", "http://lavalink_music_server:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD")

class MusicBotsManager(commands.Cog):

    """
    Manages the lifecycle of worker bots (individual discord.Client instances, each with its own
    Discord account/token). It does NOT play music itself—that is the responsibility of MusicPlayer.
    The Manager is only responsible for "which bots are currently active and in which channel."
    """

    def __init__(self, main_bot: commands.Bot):
        self.main_bot = main_bot
        # The dictionary maps IDs from the `music_bots` table to a live instance of
        # discord.Client, serving as the single source of truth for running workers.
        self.running_bots: Dict[int, discord.Client] = {}
        self._init_task: asyncio.Task | None = None

# ---------------------------------------------------------------------

    async def cog_load(self):
        # The asyncio.create_task call is used instead of await to avoid blocking
        # the Cog while the internal process waits for the main bot to be ready.
        self._init_task = asyncio.create_task(self.start_music_bots())

# ---------------------------------------------------------------------

    # The method is called automatically when unload_extension() is executed, ensuring
    # that all sub-bots are disconnected from voice channels when the module is disabled.
    async def cog_unload(self):
        logging.info("Stopping all music music bots...")
        # Copying keys using list(...) creates a snapshot before the loop begins,
        # preventing a RuntimeError caused by changes to the dictionary during iteration.
        tasks = [
            self.stop_music_bot(bot_rowid)
            for bot_rowid in list(self.running_bots.keys())
        ]
        if tasks:
            # return_exceptions=True ensures that all other workers are
            # stopped, even if an error occurs while one of them is being shut down.
            await asyncio.gather(*tasks, return_exceptions=True)

# <==============================> MUSIC BOTS CONTROL IN DASHBOARD <===============================>

    # A bulk launch retrieves only active bots from the database,
    # delegating client creation to the start_single_bot function to reuse the logic.
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

    # This function launches a single worker and can be called both during a bulk
    # launch and directly from the bot's internal API when saving a token in the dashboard.
    async def start_single_bot(self, bot_rowid: int, bot_token: str):
        if bot_rowid in self.running_bots:
            logging.warning(f"Music bot {bot_rowid} is already running.")
            return

        if not bot_token:
            logging.warning(f"Music bot {bot_rowid} has no token specified.")
            return

        # message_content: The intent does not trigger because the worker is controlled
        # directly by the main bot and does not process text commands that would make
        # no sense and would create additional problems for users.
        intents = discord.Intents.default()
        sub_bot = discord.Client(intents=intents)

        @sub_bot.event
        async def on_ready(bot=sub_bot):
            # The bot=sub_bot parameter pins a specific instance in the loop, preventing
            # the use of the last sub_bot object from memory in all on_ready handlers.
            if bot.user:
                logging.info(f"Secondary bot ready: {bot.user}")
                await update_music_bot(bot_rowid, bot_user_id=bot.user.id)

                if LAVALINK_PASSWORD is None:
                    logging.error("Lavalink password is not configured.")
                    return

                # Each worker has its own connection to Lavalink, since the server distinguishes between
                # sessions based on the bot's `user_id` and can handle several of them at the same time.
                node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
                await wavelink.Pool.connect(client=bot, nodes=[node])
                logging.info(f"Music bot {bot_rowid} connected to Lavalink.")

        self.running_bots[bot_rowid] = sub_bot
        asyncio.create_task(self.run_sub_bot(sub_bot, bot_token, bot_rowid))

        @sub_bot.event
        async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
            # The end-of-track event is the only point at which the system transitions to the next track,
            # which eliminates the need to duplicate the logic for both automatic playback and manual skipping.
            player = payload.player
            if isinstance(player, MusicPlayer):
                await player.play_next()

        @sub_bot.event
        async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
            # This event responds to a change in any user's voice status, causing the bot to leave the channel if no one else is left in it.
            voice_client = member.guild.voice_client
            if not isinstance(voice_client, MusicPlayer):
                return

            channel = voice_client.channel
            if channel is None:
                return

            # not m.bot: the bot should not count itself as ‘someone who is listening’.
            members = [m for m in channel.members if not m.bot]
            if not members:
                logging.info("Voice channel is empty, disconecting...")
                await voice_client.cleanup_and_disconnect()


# ------------------------------------------------------------------------------

    # The wrapper around bot_instance.start(token) handles login errors, ensuring that any
    # inactive worker is removed from running_bots to keep the state up to date.
    async def run_sub_bot(
        self, bot_instance: discord.Client, token: str, bot_rowid: int
    ):
        try:
            await bot_instance.start(token)
        except discord.errors.LoginFailure:
            logging.error(f"Invalid token for music bot {bot_rowid}.")
            self.running_bots.pop(bot_rowid, None)
        except Exception as e:
            logging.error(f"Error running music bot {bot_rowid}: {e}", exc_info=True)
            self.running_bots.pop(bot_rowid, None)

# -------------------------------------------------------------------------------

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
                # An entry is removed from running_bots regardless of the result of close(),
                # since keeping a "half-alive" worker in the dictionary is worse than forcibly marking it as stopped.
                self.running_bots.pop(bot_rowid, None)

# <======================> MUSIC BOTS CONTROL WITH COMMANDS <=========================>

    # The bot selection algorithm searches for a bot that is already in the desired channel or one
    # that is available (with no active voice connections), checking its status directly via sub_bot.voice_clients.
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