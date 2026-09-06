import traceback

import discord
from discord.ext import commands

from dopplerbot.database import get_settings_by_category
from utils.ai import GeminiChat, DeepSeekChat, ChatGPTChat

PROVIDERS = {
    GeminiChat.PROVIDER_NAME: GeminiChat,
    DeepSeekChat.PROVIDER_NAME: DeepSeekChat,
    ChatGPTChat.PROVIDER_NAME: ChatGPTChat,
}


class AIChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if self.bot.user not in message.mentions:
            return

        clean_content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
        if not clean_content:
            clean_content = "Hi! Did you need something?"

        ai_settings = await get_settings_by_category("AI")

        provider_name = ai_settings.get("ai_provider", "gemini")
        provider = PROVIDERS.get(provider_name, GeminiChat)
        api_key = ai_settings.get(f"ai_{provider_name}_api_key", "")

        if not api_key:
            await message.reply(f"The API key for {provider_name} has not been configured.")
            return

        async with message.channel.typing():
            try:
                # A collection of the latest chat messages for context.
                raw_history = []
                async for msg in message.channel.history(limit=10, oldest_first=True):
                    if not msg.content:
                        continue
                    raw_history.append(f"{msg.author.display_name}: {msg.content}")

                chat_context = '\n'.join(raw_history)

                bot_name = ai_settings.get("ai_bot_name", "Kara AI")
                force_language = ai_settings.get("ai_force_language", "false") == "true"
                target_language = ai_settings.get("ai_language", "English")
                system_prompt = ai_settings.get(
                    "ai_system_prompt",
                    "You are a discord server moderator."
                )

                if force_language:
                    language_instruction = (
                        f"CRITICAL LANGUAGE RULE: You MUST reply EXCLUSIVELY in {target_language}. "
                        f"Regardless of the language the user speaks to you, always respond in {target_language}."
                    )
                else:
                    language_instruction = (
                        "CRITICAL LANGUAGE RULE: Automatically detect the language of the user's message "
                        "and respond in the EXACT same language."
                    )

                try:
                    irony = float(ai_settings.get("ai_irony", "0.0"))
                    seriousness = float(ai_settings.get("ai_seriousness", "1.0"))
                except ValueError:
                    irony, seriousness = 0.0, 1.0

                # This is a set of guidelines for the AI regarding its personality and general rules.
                system_prompt = (
                    f"Your name: {bot_name}.\n"
                    f"{system_prompt}\n\n"
                    f"RULES OF CONDUCT:\n"
                    f"- Level of irony/sarcasm: {int(irony * 100)}%.\n"
                    f"- Severity Level: {int(seriousness * 100)}%.\n"
                    f"{language_instruction}"
                )

                # This is the "working memory" for a specific query.
                prompt_to_send = (
                    f"Chat context (recent messages are for reference only):\n"
                    f"--- BEGINNING OF CONTEXT ---\n"
                    f"{chat_context}\n"
                    f"--- END OF CONTEXT ---\n\n"
                    f"ATTENTION! User '{message.author.display_name}' just wrote this message:\n"
                    f"\"{clean_content}\"\n\n"
                    f"TASK: Respond SPECIFICALLY to this last message. Use the context only if necessary.\n"
                    f"{language_instruction}"
                )

                reply_text = await provider.generate_reply(system_prompt, prompt_to_send, api_key)

                if reply_text:
                    await message.reply(reply_text)
                else:
                    await message.reply("The AI returned an empty response...")

            except Exception:
                traceback.print_exc()
                await message.reply("API error")


async def setup(bot):
    await bot.add_cog(AIChatCog(bot))
