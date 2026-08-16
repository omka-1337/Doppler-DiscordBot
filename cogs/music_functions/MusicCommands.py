import discord
import wavelink
import logging

from typing import cast
from cogs.music_functions.MusicBotsManager import MusicBotsManager
from utils.MusicPalyer import MusicPlayer
from discord.ext import commands

class MusicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="play")
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, query: str):
        manager = cast(MusicBotsManager | None, self.bot.get_cog("MusicBotsManager"))
        if manager is None:
            await ctx.send("Music module not loaded.")
            return

        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("First join a voice channel.")
            return

        voice_channel = ctx.author.voice.channel

        sub_bot = manager.find_worker_for_channel(voice_channel)
        if sub_bot is None:
            await ctx.send("No available music bots.")
            return

        sub_bot_channel = sub_bot.get_channel(voice_channel.id)
        if not isinstance(sub_bot_channel, (discord.VoiceChannel, discord.StageChannel)):
            await ctx.send("Music bot cannot access this voice channel.")
            return

        raw_text_channel = sub_bot.get_channel(ctx.channel.id)
        logging.info(f"get_channel({ctx.channel.id}) returned: {raw_text_channel!r}, type: {type(raw_text_channel)}")
        if not isinstance(raw_text_channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel)):
            await ctx.send("Music bot cannot access this text channel.")
            return

        player = sub_bot_channel.guild.voice_client
        if player is None:
            player = await sub_bot_channel.connect(cls=MusicPlayer)

        if not isinstance(player, MusicPlayer):
            await ctx.send("Failed to initialize custom music player.")
            return

        player.text_channel = raw_text_channel

        if query.startswith("http://") or query.startswith("https://"):
            search_query = query
        else:
            search_query = f"search:{query}"

        tracks: wavelink.Search = await wavelink.Playable.search(search_query)
        if not tracks:
            await ctx.send(f"Can't find: {query}")
            return

        track = tracks[0]
        await player.add_to_queue(track)

        await ctx.message.delete()
        await ctx.send(f"Added to queue: {track.title}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCommands(bot))