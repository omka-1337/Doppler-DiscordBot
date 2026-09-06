import discord

# Discord's own cap on a voice channel's user limit (0 = unlimited).
MAX_USER_LIMIT = 99


def _get_cog(interaction: discord.Interaction):
    return interaction.client.get_cog("VoiceManager")


# Looked up fresh on every click (not captured at message-send time) so this
# keeps working correctly after an ownership transfer or a bot restart.
async def _ensure_owner(interaction: discord.Interaction) -> bool:
    channel = interaction.channel
    cog = _get_cog(interaction)

    if cog is None or channel is None:
        await interaction.response.send_message("Voice module is not loaded.", ephemeral=True)
        return False

    owner_id = cog.channel_owners.get(channel.id)
    if owner_id is None:
        await interaction.response.send_message("This channel has no registered owner.", ephemeral=True)
        return False

    if interaction.user.id != owner_id:
        await interaction.response.send_message("Only the channel owner can do this.", ephemeral=True)
        return False

    return True


# BUTTONS
# Persistent (timeout=None + explicit custom_id on every component), so it
# keeps working across bot restarts without needing to resend the message.
class ChannelControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Rename", emoji="✏️", style=discord.ButtonStyle.primary,
                        custom_id="voicecontrol_rename")
    async def rename_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _ensure_owner(interaction):
            return
        await interaction.response.send_modal(RenameChannelModal(interaction.channel))

    @discord.ui.button(label="User Limit", emoji="👥", style=discord.ButtonStyle.secondary,
                        custom_id="voicecontrol_limit")
    async def set_user_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _ensure_owner(interaction):
            return
        await interaction.response.send_modal(UserLimitModal(interaction.channel))

    @discord.ui.button(label="Bitrate", emoji="🎚️", style=discord.ButtonStyle.secondary,
                        custom_id="voicecontrol_bitrate")
    async def set_bitrate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _ensure_owner(interaction):
            return
        await interaction.response.send_modal(BitrateModal(interaction.channel))

    @discord.ui.button(label="Lock", emoji="🔒", style=discord.ButtonStyle.secondary,
                        custom_id="voicecontrol_lock")
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _ensure_owner(interaction):
            return

        channel = interaction.channel
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        is_locked = overwrite.connect is False

        overwrite.connect = True if is_locked else False
        try:
            await channel.set_permissions(everyone, overwrite=overwrite)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to edit this channel.", ephemeral=True)
            return

        button.label = "Lock" if is_locked else "Unlock"
        button.emoji = "🔒" if is_locked else "🔓"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "🔒 Channel locked — only allowed members can join." if not is_locked else "🔓 Channel unlocked — anyone can join.",
            ephemeral=True,
        )

    @discord.ui.button(label="Allow User", emoji="✅", style=discord.ButtonStyle.secondary,
                        custom_id="voicecontrol_allow")
    async def allow_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _ensure_owner(interaction):
            return
        await interaction.response.send_message(
            "Pick a member to allow into this channel:",
            view=AllowUserView(interaction.channel),
            ephemeral=True,
        )


# A short-lived helper view (not persistent — it's only ever shown as an
# ephemeral follow-up right after clicking "Allow User").
class AllowUserView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(timeout=120)
        self.channel = channel

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Select a member...")
    async def pick_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        try:
            await self.channel.set_permissions(member, view_channel=True, connect=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to edit this channel.", ephemeral=True)
            return

        await interaction.response.edit_message(content=f"✅ {member.mention} can now join this channel.", view=None)


# MODALS
class RenameChannelModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(title="Change the channel name")
        self.channel = channel
        self.new_name = discord.ui.TextInput(
            label="New channel name",
            placeholder="Enter a new name...",
            max_length=100
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=self.new_name.value)
            await interaction.response.send_message(
                f"✅ The channel name has been changed to: **{self.new_name.value}**",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to rename this channel.", ephemeral=True
            )


class UserLimitModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(title="Set user limit")
        self.channel = channel
        self.limit = discord.ui.TextInput(
            label=f"User limit (0-{MAX_USER_LIMIT}, 0 = unlimited)",
            placeholder="e.g. 5",
            max_length=2,
        )
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.limit.value.strip()
        if not raw.isdigit() or not (0 <= int(raw) <= MAX_USER_LIMIT):
            await interaction.response.send_message(
                f"❌ Enter a number between 0 and {MAX_USER_LIMIT}.", ephemeral=True
            )
            return

        try:
            await self.channel.edit(user_limit=int(raw))
            await interaction.response.send_message(
                f"✅ User limit set to {raw if raw != '0' else 'unlimited'}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to edit this channel.", ephemeral=True
            )


class BitrateModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__(title="Set bitrate")
        self.channel = channel
        max_kbps = int(channel.guild.bitrate_limit // 1000)
        self.bitrate = discord.ui.TextInput(
            label=f"Bitrate in kbps (8-{max_kbps})",
            placeholder="e.g. 64",
            max_length=3,
        )
        self.add_item(self.bitrate)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.bitrate.value.strip()
        max_kbps = int(self.channel.guild.bitrate_limit // 1000)

        if not raw.isdigit() or not (8 <= int(raw) <= max_kbps):
            await interaction.response.send_message(
                f"❌ Enter a number between 8 and {max_kbps} kbps.", ephemeral=True
            )
            return

        try:
            await self.channel.edit(bitrate=int(raw) * 1000)
            await interaction.response.send_message(f"✅ Bitrate set to {raw} kbps.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to edit this channel.", ephemeral=True
            )
