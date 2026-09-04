import discord
import re
import logging

from discord import app_commands
from discord.ext import commands
from datetime import timedelta, datetime, timezone

import dopplerbot.database as db

# ---------------------------------------------------------------------

# ---> DURATION PARSER
# Parses strings like "10m/h/d" into a timedelta.
# Discord allows timeout for a maximum of 28 days, so anything above that gets capped.
def parse_duration(duration_str: str) -> timedelta | None:
    match = re.fullmatch(r"(\d+)([smhd])", duration_str.strip().lower())
    if not match:
        return None

    amount, unit = match.groups()
    amount = int(amount)

    units = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount)
    }

    delta = units[unit]
    max_delta = timedelta(days=28)
    return delta if delta <= max_delta else max_delta

# ---------------------------------------------------------------------

# ---> ROLE HIERARCHY CHECK
# A moderator can't act on someone with an equal or higher role, unless they're the server owner.
def can_act_on(moderator: discord.Member, target: discord.Member) -> bool:
    if moderator.id == moderator.guild.owner_id:
        return True
    return moderator.top_role > target.top_role

class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

# ---------------------------------------------------------------------

    # ---> MOD LOG
    # Sends an embed to the moderation log channel, if one is configured and enabled.
    # Silently does nothing if logging is off or channel id is not configured.
    async def send_mod_log(self, action: str, moderator: discord.Member, target: discord.Member | discord.User, reason: str, extra: str | None = None):
        enabled = await db.get_settings("mod_log_enabled", "true")
        if enabled != "true":
            return

        raw_channel_id = await db.get_settings("mod_log_channel_id", "0")
        if raw_channel_id is None:
            raw_channel_id = "0"

        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            channel_id = 0

        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logging.warning(f"Mod log channel {channel_id} not found or bot has no access.")
            return

        # get_channel() returns a wide union of channel types; only text-like channels support .send().
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            logging.warning(f"Mod log channel {channel_id} is not a text-capable channel.")
            return

        embed = discord.Embed(
            title=f"🛡️ {action}",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="User", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=False)
        embed.add_field(name="Reason", value=reason or "No reason was given.", inline=False)
        if extra:
            embed.add_field(name="Details", value=extra, inline=False)

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            logging.warning(f"No permission to send message in mod log channel {channel_id}.")

# ---------------------------------------------------------------------

    # ---> KICK
    @app_commands.command(name="kick", description="Kick a user from the server")
    @app_commands.describe(member="User", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        if not can_act_on(interaction.user, member):
            await interaction.response.send_message(
                "You cannot kick a user with the same or a higher role.", ephemeral=True
            )
            return

        try:
            await member.kick(reason=f"{reason} (moderator: {interaction.user})")
        except discord.Forbidden:
            await interaction.response.send_message("Not enough rights.", ephemeral=True)
            return

        await interaction.response.send_message(f"{member.mention} has been kicked. Reason: {reason}")
        await self.send_mod_log("Kick", interaction.user, member, reason)

# ---------------------------------------------------------------------

    # ---> BAN
    @app_commands.command(name="ban", description="Ban a user on the server")
    @app_commands.describe(member="User", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        if not can_act_on(interaction.user, member):
            await interaction.response.send_message(
                "You cannot ban a user with the same or a higher role.", ephemeral=True
            )
            return

        try:
            await member.ban(reason=f"{reason} (moderator: {interaction.user})", delete_message_seconds=0)
        except discord.Forbidden:
            await interaction.response.send_message("Not enough rights.", ephemeral=True)
            return

        await interaction.response.send_message(f"{member.mention} has been banned. Reason: {reason}")
        await self.send_mod_log("Ban", interaction.user, member, reason)

# ---------------------------------------------------------------------

    # ---> UNBAN
    # Accepts a raw user ID, since a banned member can no longer be resolved via member picker in Discord UI.
    @app_commands.command(name="unban", description="Unban user via ID")
    @app_commands.describe(user_id="User ID", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not user_id.isdigit():
            await interaction.response.send_message("User ID can contain only numbers.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=f"{reason} (moderator: {interaction.user})")
        except discord.NotFound:
            await interaction.response.send_message("No user with that ID was found.", ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.response.send_message("Not enough rights.", ephemeral=True)
            return

        await interaction.response.send_message(f"{user.mention} has been unbanned. Reason: {reason}")
        await self.send_mod_log("Unban", interaction.user, user, reason)

# ---------------------------------------------------------------------

    # ---> MUTE
    @app_commands.command(name="mute", description="Temporarily mute a user")
    @app_commands.describe(member="User", duration="Duration, example: 10m, 1h, 2d (maximum 28d)", reason="Reason")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        if not can_act_on(interaction.user, member):
            await interaction.response.send_message(
                "You cannot mute a user with the same or a higher role.", ephemeral=True
            )
            return

        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                "Invalid duration format. Examples: `10m`, `1h`, `2d` (maximum 28d).", ephemeral=True
            )
            return

        try:
            await member.timeout(delta, reason=f"{reason} (moderator: {interaction.user})")
        except discord.Forbidden:
            await interaction.response.send_message("Not enough rights", ephemeral=True)
            return

        await interaction.response.send_message(f"{member.mention} has been muted for {duration}. Reason: {reason}")
        await self.send_mod_log("Timeout", interaction.user, member, reason, extra=f"Duration: {duration}")

# ---------------------------------------------------------------------

    # ---> UNMUTE
    @app_commands.command(name="unmute", description="Unmute a user")
    @app_commands.describe(member="User", reason="Reason")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        try:
            await member.timeout(None, reason=f"{reason} (moderator: {interaction.user})")
        except discord.Forbidden:
            await interaction.response.send_message("Not enough rights", ephemeral=True)
            return

        await interaction.response.send_message(f"{member.mention} has been unmuted.")
        await self.send_mod_log("Unmute", interaction.user, member, reason)

# ---------------------------------------------------------------------

    # ---> WARN
    # No DB persistence for now - just notifies the user and writes to the mod log.
    @app_commands.command(name="warn", description="Warn a user")
    @app_commands.describe(member="User", reason="Reason")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Reason not specified"):
        assert isinstance(interaction.user, discord.Member)

        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not can_act_on(interaction.user, member):
            await interaction.response.send_message(
                "You cannot warn a user with the same or a higher role.", ephemeral=True
            )
            return

        try:
            await member.send(f"You have been issued a warning on **{interaction.guild.name}**.\nReason: {reason}")
        except discord.Forbidden:
            # User has DMs closed - not a failure, the warn still gets logged.
            pass

        await interaction.response.send_message(f"{member.mention} received a warning. Reason: {reason}")
        await self.send_mod_log("Warn", interaction.user, member, reason)

# ---------------------------------------------------------------------

    # ---> ERROR HANDLING
    # Cog-local error handler so every slash command in this cog gets consistent, readable feedback.
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            message = "Not enough rights for this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            message = "Bot does not have enough rights for this action."
        else:
            logging.error(f"Unhandled moderation command error: {error}")
            message = "An error occurred while executing this command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCommands(bot))
