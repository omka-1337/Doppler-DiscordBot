import traceback

import discord
from discord.ext import commands

from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

from .providers import PROVIDERS, gemini


class AIChatCog(commands.Cog):
    def __init__(self, plugin: "AIChatPlugin"):
        self.plugin = plugin
        self.bot = plugin.bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if self.bot.user not in message.mentions:
            return

        clean_content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
        if not clean_content:
            clean_content = "Hi! Did you need something?"

        settings = await self.plugin.settings.all()

        provider_name = settings["provider"]
        provider = PROVIDERS.get(provider_name, gemini)
        api_key = settings.get(f"{provider_name}_api_key", "")

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

                bot_name = settings["bot_name"]
                target_language = settings["language"]

                if settings["force_language"]:
                    language_instruction = (
                        f"CRITICAL LANGUAGE RULE: You MUST reply EXCLUSIVELY in {target_language}. "
                        f"Regardless of the language the user speaks to you, always respond in {target_language}."
                    )
                else:
                    language_instruction = (
                        "CRITICAL LANGUAGE RULE: Automatically detect the language of the user's message "
                        "and respond in the EXACT same language."
                    )

                irony = settings["irony"]
                seriousness = settings["seriousness"]

                # This is a set of guidelines for the AI regarding its personality and general rules.
                system_prompt = (
                    f"Your name: {bot_name}.\n"
                    f"{settings['system_prompt']}\n\n"
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


class AIChatPlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "provider",
            SettingType.SELECT,
            default="gemini",
            label="AI provider",
            description="Which service answers. Each one needs its own API key below.",
            choices=(("gemini", "Google Gemini"), ("deepseek", "DeepSeek"), ("chatgpt", "ChatGPT")),
        ),
        PluginSetting("gemini_api_key", SettingType.SECRET, default="", label="Gemini API key"),
        PluginSetting("deepseek_api_key", SettingType.SECRET, default="", label="DeepSeek API key"),
        PluginSetting("chatgpt_api_key", SettingType.SECRET, default="", label="ChatGPT API key"),
        PluginSetting(
            "bot_name",
            SettingType.STRING,
            default="Kara AI",
            label="Persona name",
            description="The name the AI answers to and refers to itself by.",
        ),
        PluginSetting(
            "system_prompt",
            SettingType.TEXT,
            default="You're a moderator on Discord. Be polite and helpful.",
            label="System prompt",
            description="Basic instructions that define the behavior and nature of the bot.",
        ),
        PluginSetting(
            "force_language",
            SettingType.BOOL,
            default=True,
            label="Force language",
            description="If off, the bot replies in whatever language it was addressed in.",
        ),
        PluginSetting(
            "language",
            SettingType.STRING,
            default="English",
            label="Target language",
            description="Only used when Force language is on.",
        ),
        PluginSetting(
            "irony",
            SettingType.SLIDER,
            default=0.2,
            label="Level of irony",
            min=0.0,
            max=1.0,
            step=0.05,
        ),
        PluginSetting(
            "seriousness",
            SettingType.SLIDER,
            default=0.8,
            label="Severity level",
            min=0.0,
            max=1.0,
            step=0.05,
        ),
    )

    async def setup(self):
        await self.ctx.add_cog(AIChatCog(self))
