import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from dopplerbot.database import get_settings_by_category, set_settings

# How long to wait before posting another raid alert/auto-lockdown notice,
# so a sustained burst of joins doesn't spam a new message on every single join.
RAID_ALERT_COOLDOWN_SECONDS = 60


class RaidLockdownView(discord.ui.View):
    """
    Persistent view (survives bot restarts via custom_id) attached to the raid
    alert message in "alert" mode. Only a server administrator may use it.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Enable Lockdown", style=discord.ButtonStyle.danger,
                        custom_id="serverprotect_enable_lockdown")
    async def enable_lockdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return

        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only server administrators can do this.", ephemeral=True)
            return

        cog = interaction.client.get_cog("ServerProtect")
        if cog is None:
            await interaction.response.send_message("Server Protect module is not loaded.", ephemeral=True)
            return

        await cog.activate_lockdown(interaction.guild)

        button.disabled = True
        button.label = "🔒 Lockdown Enabled"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Lockdown enabled: active invites revoked, new joins will be rejected until it lifts.",
            ephemeral=True,
        )


class ServerProtect(commands.Cog):
    """
    Two independent defenses:
    - Account age check on every join (DM the reason, then kick if too new;
      grant a role automatically otherwise).
    - Raid detection: a burst of joins within a time window triggers either an
      admin-gated alert or a fully automatic lockdown, depending on raid_mode.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_joins: deque[float] = deque()
        self._last_raid_alert_at: float = 0.0
        bot.add_view(RaidLockdownView())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = await get_settings_by_category("ServerProtect")
        guild = member.guild

        # --- raid burst detection ---
        now = time.monotonic()
        self._recent_joins.append(now)

        window = float(settings.get("raid_join_window_seconds", "10") or "10")
        threshold = int(settings.get("raid_join_threshold", "5") or "5")

        while self._recent_joins and now - self._recent_joins[0] > window:
            self._recent_joins.popleft()

        lockdown_active = await self._is_lockdown_active(settings)

        if not lockdown_active and len(self._recent_joins) >= threshold:
            if now - self._last_raid_alert_at > RAID_ALERT_COOLDOWN_SECONDS:
                self._last_raid_alert_at = now
                await self._handle_raid_detected(guild, settings)
                settings = await get_settings_by_category("ServerProtect")
                lockdown_active = settings.get("raid_lockdown_active", "false") == "true"

        if lockdown_active:
            await self._reject_member(
                member,
                f"**{guild.name}** is currently in raid-lockdown mode. Please try rejoining later.",
            )
            return

        # --- account age check ---
        min_age_days = int(settings.get("min_account_age_days", "7") or "0")
        account_created = discord.utils.snowflake_time(member.id)
        age_days = (datetime.now(timezone.utc) - account_created).days

        if age_days < min_age_days:
            await self._reject_member(
                member,
                f"your account must be at least {min_age_days} day(s) old to join **{guild.name}** "
                f"(your account is {age_days} day(s) old).",
            )
            return

        role_id = int(settings.get("verified_role_id", "0") or "0")
        if role_id:
            role = guild.get_role(role_id)
            if role is None:
                return
            try:
                await member.add_roles(role, reason="Server Protect: passed account age check")
            except discord.Forbidden:
                logging.warning("Server Protect: bot lacks permission to assign the verified role.")

    # ---------------------------------------------------------------------

    # DMs the reason BEFORE kicking — a kicked member may no longer be DM-able,
    # and some users have DMs from server members closed entirely (best-effort).
    async def _reject_member(self, member: discord.Member, reason: str):
        try:
            await member.send(f"You were removed from **{member.guild.name}**: {reason}")
        except discord.Forbidden:
            pass

        try:
            await member.kick(reason=f"Server Protect: {reason}")
        except discord.Forbidden:
            logging.warning("Server Protect: bot lacks permission to kick members.")

    # ---------------------------------------------------------------------

    # Lazily clears an expired lockdown (no background task needed — checked on
    # every join, and self-heals across restarts since the state is persisted).
    async def _is_lockdown_active(self, settings: dict) -> bool:
        if settings.get("raid_lockdown_active", "false") != "true":
            return False

        duration_minutes = int(settings.get("raid_lockdown_duration_minutes", "15") or "15")
        started_raw = settings.get("raid_lockdown_started_at", "")

        expired = True
        if started_raw:
            try:
                started_at = datetime.fromisoformat(started_raw)
                expired = datetime.now(timezone.utc) - started_at > timedelta(minutes=duration_minutes)
            except ValueError:
                expired = True

        if expired:
            await set_settings("raid_lockdown_active", "false", "ServerProtect")
            return False

        return True

    # ---------------------------------------------------------------------

    async def activate_lockdown(self, guild: discord.Guild):
        await set_settings("raid_lockdown_active", "true", "ServerProtect")
        await set_settings("raid_lockdown_started_at", datetime.now(timezone.utc).isoformat(), "ServerProtect")

        try:
            for invite in await guild.invites():
                try:
                    await invite.delete(reason="Server Protect: raid lockdown")
                except discord.Forbidden:
                    pass
        except discord.Forbidden:
            logging.warning("Server Protect: bot lacks Manage Server permission to revoke invites.")

    # ---------------------------------------------------------------------

    async def _handle_raid_detected(self, guild: discord.Guild, settings: dict):
        mode = settings.get("raid_mode", "alert")

        raw_channel_id = settings.get("raid_alert_channel_id", "0")
        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            channel_id = 0

        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            logging.warning("Server Protect: raid detected but no valid alert channel is configured.")
            if mode == "auto":
                await self.activate_lockdown(guild)
            return

        if mode == "auto":
            await self.activate_lockdown(guild)
            try:
                await channel.send(
                    "🚨 **Raid detected** — lockdown enabled automatically. "
                    "Active invites were revoked and new joins will be rejected for a while."
                )
            except discord.Forbidden:
                logging.warning("Server Protect: no permission to post the lockdown notice.")
            return

        try:
            await channel.send(
                "🚨 **Possible raid detected** — a burst of new members just joined. "
                "An administrator can enable lockdown below (revokes invites, rejects new joins for a while).",
                view=RaidLockdownView(),
            )
        except discord.Forbidden:
            logging.warning("Server Protect: no permission to post the raid alert.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerProtect(bot))
