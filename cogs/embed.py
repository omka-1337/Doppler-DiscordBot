import json
from pathlib import Path
import discord
from discord.ext import commands

class EmbedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.embeds_dir = Path(__file__).resolve().parent.parent / "embeds"

    @commands.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def send_embed(self, ctx: commands.Context, name: str):
        file_path = self.embeds_dir / f"{name}.json"
        
        if not file_path.exists():
            await ctx.send(f"The `{name}` template was not found")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            embed_data = json.load(f)

        embed = discord.Embed.from_dict(embed_data)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(EmbedCog(bot))