import logging
import wavelink
import discord
import asyncio

class MusicPlayer(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.now_playing_message: discord.Message | None = None
        self.text_channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel | None = None
        self.loop: bool = False
        self.current_track: wavelink.Playable | None = None
        self.inactivity_task: asyncio.Task | None = None

# -------------------------------------------------------------------------------

    async def add_to_queue(self, track: wavelink.Playable):
        await self.queue.put_wait(track)
        logging.info(f"Track added to queue: {track.title}")

        await self.cancel_inactivity_timer()

        logging.info(f"self.playing = {self.playing}, self.connected = {self.connected}")

        if not self.playing:
            await self.play_next()
        else:
            logging.info("Already playing, track queued for later.")

# -------------------------------------------------------------------------------

    async def send_now_playing(self, track: wavelink.Playable):
        if self.now_playing_message is not None:
            try:
                await self.now_playing_message.delete()
            except discord.NotFound:
                pass

        text_channel = self.text_channel
        if text_channel is None:
            logging.warning("text_channel is None, cannot send now playing message.")
            return

        embed = discord.Embed(
            title="Now playing",
            description=track.title,
            color=0x5865F2
        )

        from utils.MusicControlView import MusicControlView
        view = MusicControlView(self)

        self.now_playing_message = await text_channel.send(embed=embed, view=view)

# -------------------------------------------------------------------------------

    async def play_next(self):
        if self.loop and self.current_track is not None:
            await self.play(self.current_track)
            logging.info(f"Looping: {self.current_track.title}")
            await self.send_now_playing(self.current_track)
            return
        
        if self.queue.is_empty:
            logging.info("Queue is empty, starting inactivity timer.")
            self.current_track = None
            await self.start_inactivity_timer()
            return

        track = self.queue.get()
        self.current_track = track
        await self.cancel_inactivity_timer()
        await self.play(track)
        logging.info(f"Now playing: {track.title}")
        await self.send_now_playing(track)

# -------------------------------------------------------------------------------

    async def cancel_inactivity_timer(self):
        current = asyncio.current_task()
        if (
            self.inactivity_task is not None
            and self.inactivity_task is not current
            and not self.inactivity_task.done()
        ):
            self.inactivity_task.cancel()
        self.inactivity_task = None

# -------------------------------------------------------------------------------

    async def start_inactivity_timer(self, delay: int = 60):
        await self.cancel_inactivity_timer()

        async def wait_and_disconect():
            await asyncio.sleep(delay)
            logging.info("Inactivity timeout reached, disconecting...")
            try:
                await self.cleanup_and_disconnect()
            except Exception as e:
                logging.error(f"Error during inactivity disconnect: {e}", exc_info=True)

        self.inactivity_task = asyncio.create_task(wait_and_disconect())

# -------------------------------------------------------------------------------

    async def cleanup_and_disconnect(self):
        await self.cancel_inactivity_timer()

        if self.now_playing_message is not None:
            try:
                await self.now_playing_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logging.warning(f"Failed to delete now playing message: {e}")
            self.now_playing_message = None

        await self.disconnect()