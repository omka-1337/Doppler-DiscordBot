import traceback

import discord
from discord.ext import commands

from dopplerbot.plugins.api import AIError, Plugin, PluginSetting, SettingType


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

        # The provider and its key belong to the bot, not to this plugin, so all
        # it can do is ask whether anything is configured.
        if not await self.plugin.ctx.ai.is_configured():
            await message.reply("No AI provider is configured for this bot yet.")
            return

        settings = await self.plugin.settings.all()

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

                reply_text = await self.plugin.ctx.ai.complete(system_prompt, prompt_to_send)

                if reply_text:
                    await message.reply(reply_text)
                else:
                    await message.reply("The AI returned an empty response...")

            except AIError as e:
                self.plugin.log.error("AI request failed: %s", e)
                await message.reply("The AI service could not be reached right now.")
            except Exception:
                traceback.print_exc()
                await message.reply("Something went wrong while answering.")


class AIChatPlugin(Plugin):
    # Persona only. Which service answers and what it costs is the bot's
    # business: this plugin hands over a prompt through ctx.ai and gets text
    # back, so it never holds an API key.
    SETTINGS = (
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
        PluginSetting("irony", SettingType.SLIDER, default=0.2, label="Level of irony", min=0.0, max=1.0, step=0.05),
        PluginSetting("seriousness", SettingType.SLIDER, default=0.8, label="Severity level", min=0.0, max=1.0, step=0.05),
    )

    async def setup(self):
        await self.ctx.add_cog(AIChatCog(self))
