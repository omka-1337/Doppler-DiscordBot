import logging

import discord
from discord import app_commands
from discord.ext import commands

from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType, TranslationError

from .locale_mapping import display_name, display_name_from_provider_code, get_base_lang

logger = logging.getLogger(__name__)

# Sane safety cap so we never send an absurd amount of text to a translation API.
MAX_TEXT_LENGTH = 4000


class TranslatorCog(commands.Cog):
    def __init__(self, plugin: "TranslatorPlugin"):
        self.plugin = plugin
        self.bot = plugin.bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Translate",
            callback=self.translate_message,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        # Context menus are registered on the tree, not on the cog, so they have
        # to be taken back off by hand when the plugin is unloaded or reloaded.
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def translate_message(self, interaction: discord.Interaction, message: discord.Message):
        text = message.content
        if not text or not text.strip():
            await interaction.response.send_message(
                "⚠️ У цьому повідомленні немає тексту для перекладу.", ephemeral=True
            )
            return

        # Translation calls hit an external API, so defer immediately to avoid
        # the 3-second interaction timeout.
        await interaction.response.defer(ephemeral=True)

        target_base_lang = get_base_lang(interaction.locale)

        try:
            # The backend is this plugin's setting; the credential behind it,
            # if any, belongs to the bot and never reaches here.
            mode = await self.plugin.settings.get("mode")
            result = await self.plugin.ctx.translate.text(
                text[:MAX_TEXT_LENGTH], target_base_lang, mode
            )
        except TranslationError as e:
            self.plugin.log.error("Translation failed: %s", e)
            await interaction.followup.send(
                "❌ Не вдалося виконати переклад. Спробуйте пізніше.", ephemeral=True
            )
            return

        source_display = display_name_from_provider_code(result.source_lang)
        target_display = display_name(result.target_lang)

        reply = (
            f"{result.text}\n\n"
            f"— {source_display} → {target_display} ({result.provider})"
        )

        await interaction.followup.send(reply, ephemeral=True)


class TranslatorPlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "mode",
            SettingType.SELECT,
            default="google_free",
            label="Translation backend",
            description=(
                "Free needs no setup but is rate limited under load. AI reuses the API key "
                "already configured for the bot under Settings -> Providers, and handles "
                "idiom and context better."
            ),
            choices=(
                ("google_free", "Google Translate — free, no key required"),
                ("ai", "AI translation — uses the bot's AI provider"),
            ),
        ),
    )

    async def setup(self):
        await self.ctx.add_cog(TranslatorCog(self))
