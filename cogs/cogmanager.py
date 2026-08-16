#COG MANAGER

from database import set_settings
import discord
from discord.ext import commands
from pathlib import Path

class CogManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cogs_dir = Path("cogs")

        # SET COG STATUS
        async def toggle_cog_module(bot, cog_name: str, db_key: str, enable: bool):
            await set_settings(db_key, "true" if enable else "false", category="Modules")

            try:
                if enable:
                    await bot.load_extension(cog_name)
                    print(f"Extension {cog_name} loaded successfully.")
                else:
                    await bot.unload_extension(cog_name)
                    print(f"Extension {cog_name} unloaded successfully.")
            except Exception as e:
                    print(f"Error toggling extension {cog_name}: {e}")

# CM
    @commands.group(name="cm", invoke_without_command=True, help="Module management (subcommands: list, reload)")
    @commands.has_permissions(administrator=True)
    async def cm(self, ctx: commands.Context):
        await ctx.send("Use `+cm list` or `+cm reload <module>`")

# CM_LIST
    @cm.command(name="list", help="List of all modules and their status")
    @commands.has_permissions(administrator=True)
    async def cm_list(self, ctx: commands.Context):
        embed = discord.Embed(title="List of modules", color=0x2b2d31)

        for file in self.cogs_dir.rglob("*.py"):
            if file.name.startswith("__"):
                continue

            rel_path = file.relative_to(self.cogs_dir).with_suffix("")
            module_path = ".".join(rel_path.parts)

            extension_name = f"cogs.{module_path}"

            status = "🟢" if extension_name in self.bot.extensions else "🔴"

            embed.add_field(
                name=f"{status} {module_path}",
                value=f"`cogs/{rel_path.as_posix()}.py`",
                inline=False
            )
        await ctx.send(embed=embed)

# CM_RELOAD
    @cm.command(name="reload", help="Reload the module")
    @commands.has_permissions(administrator=True)
    async def cm_reload(self, ctx: commands.Context, cog_name: str):
        path = self.cogs_dir / f"{cog_name}.py"
        try:
            if not path.is_file():
                raise commands.ExtensionNotFound(f"{cog_name}.py does not exist.")
            await self.bot.reload_extension(f"cogs.{cog_name}")
            embed = discord.Embed(
                description=f"✅ `{cog_name}` reloaded",
                color=0x00ff00
            )
        except commands.ExtensionNotLoaded:
            embed = discord.Embed(
                description=f"⚠️ `{cog_name}` not loaded",
                color=0xffd700
            )
        except commands.ExtensionNotFound:
            embed = discord.Embed(
                description=f"❌ `{cog_name}` not found",
                color=0xff0000
            )
        except Exception as e:
            embed = discord.Embed(
                description=f"❗ Error:\n```py\n{e}```",
                color=0xff0000
            )
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(CogManager(bot))
