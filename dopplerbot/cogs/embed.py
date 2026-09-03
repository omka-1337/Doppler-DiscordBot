import json
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

class EmbedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.embeds_dir = Path(__file__).resolve().parent.parent.parent / "savedata" / "embeds"
        self.images_dir = self.embeds_dir / "images"

    def _list_template_names(self) -> list[str]:
        if not self.embeds_dir.exists():
            return []
        return sorted(p.stem for p in self.embeds_dir.glob("*.json"))

    @app_commands.command(name="embed", description="Send a saved embed template")
    @app_commands.describe(name="The saved template name")
    @app_commands.checks.has_permissions(administrator=True)
    async def send_embed(self, interaction: discord.Interaction, name: str):
        file_path = self.embeds_dir / f"{name}.json"

        if not file_path.exists():
            await interaction.response.send_message(f"The `{name}` template was not found", ephemeral=True)
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
            await interaction.response.send_message(f"The `{name}` template has no content to send.", ephemeral=True)
            return

        await interaction.response.send_message(view=view, files=files)

        if missing_images:
            await interaction.followup.send(
                f"⚠️ Missing uploaded image(s) for `{name}`: {', '.join(missing_images)}", ephemeral=True
            )

    @send_embed.autocomplete("name")
    async def embed_name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.lower()
        return [
            app_commands.Choice(name=template_name, value=template_name)
            for template_name in self._list_template_names()
            if current_lower in template_name.lower()
        ][:25]

async def setup(bot):
    await bot.add_cog(EmbedCog(bot))
