import os
import socket
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

def get_server_ip():
    try:
        # Create a fake UDP connection to determine the primary network interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class WebCommandCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="web", description="Get a link to the bot's web dashboard")
    async def web_dashboard(self, ctx: commands.Context):
        # 1. Check to see if a direct link/domain is specified in .env
        custom_url = os.getenv("DASHBOARD_URL", "").strip()

        if custom_url:
            dashboard_url = custom_url
        else:
            # 2. If not, use the local IP address and port (8000 by default)
            port = os.getenv("WEB_PORT", "8000")
            ip = get_server_ip()
            dashboard_url = f"http://{ip}:{port}"

        embed = discord.Embed(
            title="🌐 Web Dashboard",
            description=f"Go to the bot's control panel by following this link:\n{dashboard_url}",
            color=discord.Color.purple()
        )

        # A link button directly below the message
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Відкрити Dashboard", url=dashboard_url, emoji="🔗"))

        # Set it to “ephemeral” so that only the person who issued the command can see the link
        await ctx.send(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(WebCommandCog(bot))