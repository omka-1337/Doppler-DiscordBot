import json

import discord
from discord import app_commands
from discord.ext import commands

from dopplerbot.plugins.api import Plugin


# Discord's own limit for one action row.
MAX_BUTTONS_PER_ROW = 5


class EmbedCog(commands.Cog):
    def __init__(self, plugin: "EmbedPlugin"):
        self.plugin = plugin
        self.bot = plugin.bot
        # Shared with the dashboard: the panel's Embed Builder writes the
        # templates and uploaded images that this command reads back.
        self.embeds_dir = plugin.ctx.savedata_dir / "embeds"
        self.images_dir = self.embeds_dir / "images"

    def _resolve_media(self, block: dict, files: list, missing: list):
        """An uploaded file or a plain URL, whichever the block carries."""
        attachment_name = block.get("attachment")
        if attachment_name:
            path = self.images_dir / attachment_name
            if not path.exists():
                missing.append(attachment_name)
                return None
            image_file = discord.File(path, filename=attachment_name)
            files.append(image_file)
            return image_file

        url = (block.get("url") or "").strip()
        return url or None

    def _list_template_names(self) -> list[str]:
        if not self.embeds_dir.exists():
            return []
        return sorted(p.stem for p in self.embeds_dir.glob("*.json"))

    def build_view(self, layout_data: dict):
        """Turn a saved template into a LayoutView, the files it needs,
        and the names of any uploads that have gone missing."""
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

                elif block_type == "thumbnail":
                    # A thumbnail is a Section accessory, not a standalone
                    # component: Discord always pairs it with the text it sits
                    # beside, so the block carries both.
                    media = self._resolve_media(block, files, missing_images)
                    content = (block.get("content") or "").strip()
                    if media is not None and content:
                        container.add_item(
                            discord.ui.Section(
                                discord.ui.TextDisplay(content),
                                accessory=discord.ui.Thumbnail(media=media),
                            )
                        )

                elif block_type == "buttons":
                    row = discord.ui.ActionRow()
                    for button in (block.get("buttons") or [])[:MAX_BUTTONS_PER_ROW]:
                        label = (button.get("label") or "").strip()
                        url = (button.get("url") or "").strip()
                        # Link buttons only. Any other style needs something to
                        # answer the click, and a saved template has nobody to
                        # do that once the process that sent it has restarted.
                        if label and url.startswith(("http://", "https://")):
                            row.add_item(discord.ui.Button(label=label, url=url))
                    if row.children:
                        container.add_item(row)

                elif block_type == "image":
                    media = self._resolve_media(block, files, missing_images)
                    if media is not None:
                        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media=media)))

            if container.children:
                view.add_item(container)

        return view, files, missing_images

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

        view, files, missing_images = self.build_view(layout_data)

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

class EmbedPlugin(Plugin):
    # No settings of its own: the templates are authored in the dashboard's
    # Embed Builder tab rather than configured here.
    SETTINGS = ()

    async def setup(self):
        self.cog = EmbedCog(self)
        await self.ctx.add_cog(self.cog)

        # The builder is a page, not a form, so it cannot be generated from a
        # settings schema -- it gets what it needs from this plugin instead.
        try:
            self.ctx.add_endpoint("GET", "/templates", self.list_templates)
            self.ctx.add_endpoint("POST", "/delete", self.delete_template)
        except PermissionError as e:
            # Untrusted plugins may not declare endpoints. The commands still
            # work; only the builder's own page would be unavailable.
            self.log.warning("%s", e)

    async def list_templates(self, request):
        names = self.cog._list_template_names()
        if request.query.get("full") != "1":
            return {"templates": names}

        # The page summarises each template, so it needs the contents too.
        out = []
        for name in names:
            try:
                data = json.loads((self.cog.embeds_dir / f"{name}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            out.append({"name": name, "data": data})
        return {"templates": out}

    async def delete_template(self, request):
        body = await request.json()
        name = str(body.get("name", ""))

        # The name comes from the page, so it is treated as untrusted: only a
        # template that is actually in the list may be removed.
        if name not in self.cog._list_template_names():
            return {"status": "error", "message": "No such template."}

        (self.cog.embeds_dir / f"{name}.json").unlink(missing_ok=True)
        self.log.info("Deleted embed template %r", name)
        return {"status": "ok"}
