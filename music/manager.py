import asyncio
import logging
import discord
import wavelink

from typing import Dict
from discord.ext import commands

from .player import MusicPlayer

class MusicBotsManager(commands.Cog):

    """
    Manages the lifecycle of worker bots (individual discord.Client instances, each with its own
    Discord account/token). It does NOT play music itself—that is the responsibility of MusicPlayer.
    The Manager is only responsible for "which bots are currently active and in which channel."
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.main_bot = plugin.bot
        self.store = plugin.store
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
        logging.info("Stopping all music bots...")

        # The startup task waits on the main bot becoming ready, which may never
        # happen; leaving it pending would stack up one task per plugin reload.
        if self._init_task is not None and not self._init_task.done():
            self._init_task.cancel()
        self._init_task = None

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

        # A worker that died without going through stop_music_bot could still
        # have left a node behind, and nothing else in the bot uses wavelink.
        try:
            await wavelink.Pool.close()
        except Exception as e:
            logging.warning("Could not close the Lavalink pool: %s", e)

# <==============================> MUSIC BOTS CONTROL IN DASHBOARD <===============================>

    # A bulk launch retrieves only active bots from the database,
    # delegating client creation to the start_single_bot function to reuse the logic.
    async def start_music_bots(self):
        try:
            await self._start_music_bots()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Runs detached as a task, so without this an error here would only
            # ever surface as asyncio's "exception was never retrieved" warning.
            logging.exception("Failed to start the music workers.")

    async def _start_music_bots(self):
        await self.main_bot.wait_until_ready()

        # Docker returns as soon as the container exists, but Lavalink needs
        # tens of seconds to boot; connecting before that just fails.
        if getattr(self.plugin, "sidecar_started", False):
            await self.plugin.ctx.services.wait_until_ready("lavalink")

        bots_data = await self.store.all()
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
        settings = await self.plugin.settings.all()
        lavalink_uri = settings["lavalink_uri"]
        lavalink_password = settings["lavalink_password"]

        intents = discord.Intents.default()
        sub_bot = discord.Client(intents=intents)

        @sub_bot.event
        async def on_ready(bot=sub_bot):
            # The bot=sub_bot parameter pins a specific instance in the loop, preventing
            # the use of the last sub_bot object from memory in all on_ready handlers.
            if bot.user:
                logging.info(f"Secondary bot ready: {bot.user}")
                await self.store.update(bot_rowid, bot_user_id=bot.user.id)

                if not lavalink_password:
                    logging.error("Lavalink password is not configured in the music plugin's settings.")
                    return

                # Each worker has its own connection to Lavalink, since the server distinguishes between
                # sessions based on the bot's `user_id` and can handle several of them at the same time.
                node = wavelink.Node(uri=lavalink_uri, password=lavalink_password)
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

        # A track that cannot be played raises this first, and only then ends with
        # reason "loadFailed". Listening to the end alone meant the queue moved on
        # with nothing said, and with looping on it retried the same track forever.
        @sub_bot.event
        async def on_wavelink_track_exception(payload: wavelink.TrackExceptionEventPayload):
            player = payload.player
            if isinstance(player, MusicPlayer):
                exception = getattr(payload, "exception", None) or {}
                reason = exception.get("message") if isinstance(exception, dict) else str(exception)
                await player.report_failure(payload.track, reason)

        # Lavalink stopped receiving audio for a track it had started.
        @sub_bot.event
        async def on_wavelink_track_stuck(payload: wavelink.TrackStuckEventPayload):
            player = payload.player
            if isinstance(player, MusicPlayer):
                await player.report_failure(payload.track, "The source stopped responding.")

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

    @staticmethod
    async def _close_nodes_for(client: discord.Client) -> int:
        """Close and eject the Lavalink nodes belonging to one worker."""
        closed = 0
        for node in list(wavelink.Pool.nodes.values()):
            if node.client is not client:
                continue
            try:
                # eject=True drops it from the pool, so restarting the worker
                # builds a fresh node instead of finding a dead one.
                await node.close(eject=True)
                closed += 1
            except Exception as e:
                logging.warning("Could not close Lavalink node %s: %s", node.identifier, e)
        return closed

# -------------------------------------------------------------------------------

    async def stop_music_bot(self, bot_rowid: int) -> bool:
            bot_instance = self.running_bots.get(bot_rowid)

            if bot_instance is None:
                logging.warning(f"Music bot {bot_rowid} is not running.")
                return False

            try:
                # Closing the client is not enough: the worker's Lavalink node
                # lives in wavelink's global pool and keeps its own reconnect
                # loop. Left behind, it retries a host that no longer resolves
                # once the sidecar is gone, forever.
                await self._close_nodes_for(bot_instance)

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