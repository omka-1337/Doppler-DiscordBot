import discord
import wavelink
import logging

from typing import cast
from cogs.music.MusicBotsManager import MusicBotsManager
from utils.music.MusicPlayer import MusicPlayer
from discord.ext import commands

class MusicCommands(commands.Cog):

    """
    Main bot commands. The MAIN bot itself never joins a voice channel—
    it acts solely as a "conductor": it finds the right worker via MusicBotsManager
    and performs actions on its behalf (sub_bot.connect(), player.add_to_queue()).
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="play")
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str):
        # The use of cast is necessary because get_cog() returns an Optional[Cog], and the static type
        # checker in discord.py cannot automatically determine the specific class based on its string name.
        manager = cast(MusicBotsManager | None, self.bot.get_cog("MusicBotsManager"))
        if manager is None:
            await ctx.send("Music module not loaded.")
            return

        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("First join a voice channel.")
            return

        voice_channel = ctx.author.voice.channel

        # First, it looks for a worker that is ALREADY in this channel (to add the track to
        # the queue instead of spawning a second bot alongside it), and only then does it look for an available one.
        sub_bot = manager.find_worker_for_channel(voice_channel)
        if sub_bot is None:
            await ctx.send("No available music bots.")
            return

        # The channel for the sub_bot's actions must be retrieved from its own cache using the gateway ID, since the voice_channel
        # object belongs to the main bot's cache, and the sub-bot has a separate gateway connection and its own cache.
        sub_bot_channel = sub_bot.get_channel(voice_channel.id)
        if not isinstance(sub_bot_channel, (discord.VoiceChannel, discord.StageChannel)):
            await ctx.send("Music bot cannot access this voice channel.")
            return

        # The text channel object must also be retrieved from the subbot's own cache by ID, and VoiceChannel
        # and StageChannel are valid types, since chats within voice channels support the .send() method.
        raw_text_channel = sub_bot.get_channel(ctx.channel.id)
        if not isinstance(raw_text_channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            await ctx.send("Music bot cannot access this text channel.")
            return

        # If sub_bot is already connected to the desired channel, the existing voice_client
        # is used to add the track to the current queue, and a new MusicPlayer is created only upon the initial connection.
        player = sub_bot_channel.guild.voice_client
        if player is None:
            player = await sub_bot_channel.connect(cls=MusicPlayer)

        if not isinstance(player, MusicPlayer):
            await ctx.send("Failed to initialize custom music player.")
            return

        # The channel for sending "Now playing" updates every time the command is called,
        # so that new notifications are sent to the exact text chat from which the user called the "play" command.
        player.text_channel = raw_text_channel

        # The direct URL is passed to Lavalink in its original form, since wrapping it in search prefixes
        # ("scsearch:"/"ytsearch:") causes the link to fail recognition and results in the default prefix being forced.
        if query.startswith("http://") or query.startswith("https://"):
            search_query = query
        else:
            search_query = f"scearch:{query}"

        tracks: wavelink.Search = await wavelink.Playable.search(search_query)
        if not tracks:
            await ctx.send(f"Can't find: {query}")
            return

        track = tracks[0]
        await player.add_to_queue(track)

        # A user's message is deleted only after the command has been successfully executed,
        # so that if an error occurs, the original message remains available for context.
        await ctx.message.delete()

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCommands(bot))