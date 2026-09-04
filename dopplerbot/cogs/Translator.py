import logging

import discord
from discord import app_commands
from discord.ext import commands

import dopplerbot.database as database
from utils.translator.LocaleMapping import (
    get_base_lang,
    display_name,
    display_name_from_provider_code,
)
from utils.translator.TranslatorService import translate, TranslationError

logger = logging.getLogger(__name__)

# Sane safety cap so we never send an absurd amount of text to a translation API.
MAX_TEXT_LENGTH = 4000


class Translator(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Translate",
            callback=self.translate_message,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def translate_message(self, interaction: discord.Interaction, message: discord.Message):
        enabled = await database.get_settings("translator", "false")
        if enabled != "true":
            await interaction.response.send_message(
                "🔌 Модуль Translator вимкнено.", ephemeral=True
            )
            return

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
            result = await translate(text[:MAX_TEXT_LENGTH], target_base_lang)
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Translator(bot))
