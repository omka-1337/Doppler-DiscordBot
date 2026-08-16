import logging
import wavelink
import discord

class MusicPlayer(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.now_playing_message: discord.Message | None = None
        self.text_channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel | None = None
        self.loop: bool = False
        self.current_track: wavelink.Playable | None = None

    async def add_to_queue(self, track: wavelink.Playable):
        await self.queue.put_wait(track)
        logging.info(f"Track added to queue: {track.title}")

        if not self.playing:
            await self.play_next()

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

    async def play_next(self):
        if self.loop and self.current_track is not None:
            await self.play(self.current_track)
            logging.info(f"Looping: {self.current_track.title}")
            await self.send_now_playing(self.current_track)
            return
        
        if self.queue.is_empty:
            logging.info("Queue is empty, nothing to play.")
            self.current_track = None
            return

        track = self.queue.get()
        self.current_track = track
        await self.play(track)
        logging.info(f"Now playing: {track.title}")
        await self.send_now_playing(track)