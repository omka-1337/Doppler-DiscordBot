import logging

import discord
from discord import app_commands
from discord.ext import commands

from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

from .locale_mapping import display_name, display_name_from_provider_code, get_base_lang
from .service import TranslationError, translate

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

        settings = await self.plugin.settings.all()
        target_base_lang = get_base_lang(interaction.locale)

        try:
            result = await translate(
                text[:MAX_TEXT_LENGTH],
                target_base_lang,
                provider=settings["provider"],
                deepl_api_key=settings["deepl_api_key"],
                google_api_key=settings["google_api_key"],
            )
        except TranslationError:
            await interaction.followup.send(
                "❌ Не вдалося виконати переклад. Спробуйте пізніше.", ephemeral=True
            )
            return

        source_display = display_name_from_provider_code(result.source_lang)
        target_display = display_name(result.target_lang)

        reply = (
            f"{result.translated_text}\n\n"
            f"— {source_display} → {target_display} ({result.provider_used})"
        )

        await interaction.followup.send(reply, ephemeral=True)


class TranslatorPlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "provider",
            SettingType.SELECT,
            default="google",
            label="Translation provider",
            description="DeepL falls back to Google automatically if no DeepL key is set.",
            choices=(("google", "Google"), ("deepl", "DeepL")),
        ),
        PluginSetting(
            "deepl_api_key",
            SettingType.SECRET,
            default="",
            label="DeepL API key",
            description="Required to use DeepL. Leave empty to always use Google.",
        ),
        PluginSetting(
            "google_api_key",
            SettingType.SECRET,
            default="",
            label="Google Cloud Translate API key",
            description="Optional. Without it, a free keyless Google fallback is used instead.",
        ),
    )

    async def setup(self):
        await self.ctx.add_cog(TranslatorCog(self))
