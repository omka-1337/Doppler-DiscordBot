import logging
import wavelink
import discord
import asyncio

class MusicPlayer(wavelink.Player):

    """
    Inherits from wavelink.Player (rather than wrapping it) — this object is a voice
    client for the worker, extended with a queue and its own logic. Fewer levels
    of indirection: self.play(), self.queue, etc. are accessible directly, without self.player....
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The "Now playing" message is deleted and resent every time the track changes (instead of being edited) so
        # that it always stays at the very bottom of the chat and doesn't get lost among new messages.
        self.now_playing_message: discord.Message | None = None

        # A text channel used to send an embed message can be a TextChannel, VoiceChannel, or StageChannel, since Discord allows
        # text chat directly within voice channels, which is why ctx.channel takes the appropriate type.
        self.text_channel: discord.TextChannel | discord.VoiceChannel | discord.StageChannel | None = None

        self.loop: bool = False

        # The current track field is stored separately from the queue to ensure proper handling of loops (loop=True)
        # when the track has already been removed from the queue, and to allow it to be reset to zero during a
        # manual skip, which prevents the track from being played again.
        self.current_track: wavelink.Playable | None = None

        # Inactivity timer task. This is saved so that it can be
        # cancelled if someone manages to add a new track before it expires.
        self.inactivity_task: asyncio.Task | None = None

# -------------------------------------------------------------------------------

    async def add_to_queue(self, track: wavelink.Playable):
        await self.queue.put_wait(track)
        logging.info(f"Track added to queue: {track.title}")

        # Someone has added something — we’re cancelling the planned release due to inactivity.
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
                pass # A user or moderator could have deleted the post themselves — this is not an error

        text_channel = self.text_channel
        if text_channel is None:
            logging.warning("text_channel is None, cannot send now playing message.")
            return

        embed = discord.Embed(
            title="🎵 Now playing",
            description=f"[{track.title}]({track.uri})" if track.uri else track.title,
            color=0x5865F2
        )

        if track.author:
            embed.add_field(name="Author", value=track.author, inline=True)

        if track.length and not track.is_stream:
            minutes, seconds = divmod(track.length // 1000, 60)
            embed.add_field(name="Duration", value=f"{minutes}:{seconds:02d}", inline=True)
        elif track.is_stream:
            embed.add_field(name="Duration", value="🔴 Live", inline=True)

        if not self.queue.is_empty:
            next_track = self.queue[0]
            embed.add_field(name="Up next", value=next_track.title, inline=False)

        if track.source:
            embed.add_field(name="Source", value=track.source.capitalize(), inline=True)

        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        footer_text = "🔁 Looping" if self.loop else None
        if footer_text:
            embed.set_footer(text=footer_text)

        # A local import within a method breaks the circular import, since the module loads MusicControlView while
        # the method is already executing, when all classes and files have been fully initialized in memory.
        from .view import MusicControlView # <- Control buttons.
        view = MusicControlView(self)

        self.now_playing_message = await text_channel.send(embed=embed, view=view)

# -------------------------------------------------------------------------------

    async def play_next(self):
        # When looping is enabled (loop=True), the same track as current_track is played without changing the queue.
        # To move to the next audio track, the Skip button must reset current_track before forcing the skip, so that "loop" does not start playing it again.
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
        # asyncio.current_task() MUST have parentheses. Without them,
        # the self-cancellation check fails. This caused wait_and_disconect() to
        # silently kill itself via cancel_inactivity_timer() because CancelledError
        # bypasses standard Exception blocks.
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
                # The try/except block inside `asyncio.create_task` is necessary because background tasks do not
                # propagate exceptions to the outer code, and without it, any error will go unnoticed in the logs.
                logging.error(f"Error during inactivity disconnect: {e}", exc_info=True)

        self.inactivity_task = asyncio.create_task(wait_and_disconect())

# -------------------------------------------------------------------------------

    async def cleanup_and_disconnect(self):
        # This method serves as the single exit point for all termination scenarios (timeout, empty channel, manual stop),
        # eliminating the need to duplicate the logic for removing embedded messages.
        await self.cancel_inactivity_timer()

        if self.now_playing_message is not None:
            try:
                await self.now_playing_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                logging.warning(f"Failed to delete now playing message: {e}")
            self.now_playing_message = None

        await self.disconnect()