from web.app import api_get_settings
import discord
import os
import traceback
from discord.ext import commands
from google import genai
from google.genai import types
from dotenv import load_dotenv
from database import get_settings_by_category

load_dotenv()

# RETRIEVES THE KEY FROM THE CONFIG
class AIChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        api_key = os.getenv("GEMINI_API_KEY", "")

        if not api_key:
            print("[AI Error]: GEMINI_API_KEY not found in config.py")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

# PROCESSING AND TRANSMITTING A MESSAGE TO THE AI
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if self.bot.user in message.mentions:
            if not self.client:
                await message.reply("The API key for AI has not been configured.")
                return

            clean_content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
            if not clean_content:
                clean_content = "Hi! Did you need something?"

            async with message.channel.typing():
                try:
                    # A collection of the latest chat messages for context.
                    raw_history = []
                    async for msg in message.channel.history(limit=10, oldest_first=True):
                        if not msg.content:
                            continue
                        raw_history.append(f"{msg.author.display_name}: {msg.content}")

                    chat_context = '\n'.join(raw_history)

                    ai_settings = await get_settings_by_category("AI")

                    bot_name = ai_settings.get("ai_bot_name", "Gemini")
                    force_language = ai_settings.get("ai_force_languge", "false",) == "true"
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

                    # This is the “working memory” for a specific query.
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

                    # Calling Google AI to generate a response.
                    response = await self.client.aio.models.generate_content(
                        model="gemini-3.1-flash-lite",
                        contents=prompt_to_send,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt
                        )
                    )

                    if response.text:
                        await message.reply(response.text)
                    else:
                        await message.reply("The AI returned an empty response...")

                except Exception:
                    traceback.print_exc()
                    await message.reply("API error")

async def setup(bot):
    await bot.add_cog(AIChatCog(bot))
