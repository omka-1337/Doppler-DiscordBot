import json
from pathlib import Path
import discord
from discord.ext import commands

class EmbedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.embeds_dir = Path(__file__).resolve().parent.parent.parent / "savedata" / "embeds"
        self.images_dir = self.embeds_dir / "images"

    @commands.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def send_embed(self, ctx: commands.Context, name: str):
        file_path = self.embeds_dir / f"{name}.json"

        if not file_path.exists():
            await ctx.send(f"The `{name}` template was not found")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            layout_data = json.load(f)

        view = discord.ui.LayoutView()
        files = []
        missing_images = []

        # Each card is its own independent Container, so it renders as a
        # separate visual box. Several cards can still be part of one message.
        for card_data in layout_data.get("cards", []):
            container = discord.ui.Container(accent_colour=card_data.get("accent_color"))

            for block in card_data.get("blocks", []):
                block_type = block.get("type")

                if block_type == "text":
                    content = (block.get("content") or "").strip()
                    if content:
                        container.add_item(discord.ui.TextDisplay(content))

                elif block_type == "image":
                    attachment_name = block.get("attachment")
                    url = block.get("url")

                    if attachment_name:
                        image_path = self.images_dir / attachment_name
                        if image_path.exists():
                            image_file = discord.File(image_path, filename=attachment_name)
                            files.append(image_file)
                            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=image_file)))
                        else:
                            missing_images.append(attachment_name)
                    elif url:
                        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=url)))

            if container.children:
                view.add_item(container)

        if not view.children:
            await ctx.send(f"The `{name}` template has no content to send.")
            return

        await ctx.send(view=view, files=files)

        if missing_images:
            await ctx.send(f"⚠️ Missing uploaded image(s) for `{name}`: {', '.join(missing_images)}")

async def setup(bot):
    await bot.add_cog(EmbedCog(bot))
