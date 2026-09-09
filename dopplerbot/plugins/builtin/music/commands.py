import discord
import wavelink
import logging

from typing import cast
from typing import Literal
from .manager import MusicBotsManager
from .player import MusicPlayer
from discord.ext import commands
from discord import app_commands

class MusicCommands(commands.Cog):
    """
    Main bot commands. The MAIN bot itself never joins a voice channel—
    it acts solely as a "conductor": it finds the right worker via MusicBotsManager
    and performs actions on its behalf (sub_bot.connect(), player.add_to_queue()).
    """

    def __init__(self, plugin):
        self.plugin = plugin
        self.bot = plugin.bot

    @app_commands.command(name="play", description="Play a track or add it to the queue")
    @app_commands.describe(
        query="Song name, SoundCloud link, or other supported URL",
        source="Which source to search (ignored if query is a direct URL)"
    )
    @app_commands.choices(source=[
        app_commands.Choice(name="YouTube", value="yt"),
        app_commands.Choice(name="SoundCloud", value="sc"),
    ])

    async def play(self, interaction: discord.Interaction, query: str, source: app_commands.Choice[str] | None = None):
        # The use of cast is necessary because get_cog() returns an Optional[Cog], and the static type
        # checker in discord.py cannot automatically determine the specific class based on its string name.
        manager = cast(MusicBotsManager | None, self.bot.get_cog("MusicBotsManager"))
        if manager is None:
            await interaction.response.send_message("Music module not loaded.")
            return

        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("First join a voice channel.")
            return

        voice_channel = interaction.user.voice.channel

        # First, it looks for a worker that is ALREADY in this channel (to add the track to
        # the queue instead of spawning a second bot alongside it), and only then does it look for an available one.
        sub_bot = manager.find_worker_for_channel(voice_channel)
        if sub_bot is None:
            await interaction.response.send_message("No available music bots.")
            return

        # The channel for the sub_bot's actions must be retrieved from its own cache using the gateway ID, since the voice_channel
        # object belongs to the main bot's cache, and the sub-bot has a separate gateway connection and its own cache.
        sub_bot_channel = sub_bot.get_channel(voice_channel.id)
        if not isinstance(sub_bot_channel, (discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message("Music bot cannot access this voice channel.")
            return

        # Searching for a track may take some time—defer() displays “bot is thinking,”
        # otherwise Discord considers the interaction “timeout” after 3 seconds.
        await interaction.response.defer()

        if interaction.channel_id is None:
            await interaction.response.send_message("Cannot determine the current channel.", ephemeral=True)
            return
        
        # The text channel object must also be retrieved from the subbot's own cache by ID, and VoiceChannel
        # and StageChannel are valid types, since chats within voice channels support the .send() method.
        raw_text_channel = sub_bot.get_channel(interaction.channel_id)

        if not isinstance(raw_text_channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message("Music bot cannot access this text channel.", ephemeral=True)
            return

        # If sub_bot is already connected to the desired channel, the existing voice_client
        # is used to add the track to the current queue, and a new MusicPlayer is created only upon the initial connection.
        player = sub_bot_channel.guild.voice_client
        if player is None:
            player = await sub_bot_channel.connect(cls=MusicPlayer)

        if not isinstance(player, MusicPlayer):
            await interaction.followup.send("Failed to initialize custom music player.")
            return

        # The channel for sending "Now playing" updates every time the command is called,
        # so that new notifications are sent to the exact text chat from which the user called the "play" command.
        player.text_channel = raw_text_channel

        # Link filtering. There's no point in passing a direct link as the track title. We also use prefixes embedded in the wavelink.
        if query.startswith("http://") or query.startswith("https://"):
            search_query = query
            search_source = None
        else:
            search_query = query
            source_value = source.value if source is not None else "sc"
            search_source = wavelink.TrackSource.SoundCloud if source_value == "sc" else wavelink.TrackSource.YouTube

        if search_source is not None:
            tracks: wavelink.Search = await wavelink.Playable.search(search_query, source=search_source)
        else:
            tracks: wavelink.Search = await wavelink.Playable.search(search_query)

        if not tracks:
            await interaction.followup.send(f"Can't find: {query}")
            return

        if isinstance(tracks, wavelink.Playlist):
            added_count = await player.queue.put_wait(tracks)
            await interaction.followup.send(f"Added playlist **{tracks.name}** to queue ({added_count} tracks).", ephemeral=True)

            if not player.playing:
                await player.play_next()
            return

        track = tracks[0]
        await player.add_to_queue(track)

        await interaction.followup.send(f"Added to queue: {track.title}", ephemeral=True)
