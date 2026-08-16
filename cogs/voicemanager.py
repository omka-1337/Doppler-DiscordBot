# VOICE CHANNELS MANAGER

import asyncio
import discord
from discord.ext import commands
from database import get_settings_by_category, get_all_temp_channels, add_temp_channel, remove_temp_channel


class VoiceManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_channels = {}
        self.creating_channels = set()

    # AFTER A RESTART SYNCS THE CHANNELS WITH THE DATABASE
    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()

        db_channels = await get_all_temp_channels()
        for owner_id, channel_id in db_channels:
            channel = self.bot.get_channel(channel_id)

            if channel:
                if len(channel.members) == 0:
                    try:
                        await channel.delete()
                        await remove_temp_channel(channel_id)
                    except Exception as e:
                        print(f"Error deleting orphan channel {channel_id}: {e}")
                else:
                    self.user_channels[owner_id] = channel_id
            else:
                await remove_temp_channel(channel_id)

    # CREATE A CHANNEL
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        voice_settings = await get_settings_by_category("Voice")
        try:
            main_channel_id = int(voice_settings.get("main_voice_channel_id", 0))
            category_id = int(voice_settings.get("category_id", 0))
        except ValueError:
            return

        if not main_channel_id or not category_id:
            return

        if after.channel and after.channel.id == main_channel_id:
            if member.id in self.creating_channels:
                return

            self.creating_channels.add(member.id)  # Add a user to the block list

            category = self.bot.get_channel(category_id)
            if not category:
                print("Category not found. Check CATEGORY_ID in settings.")
                self.creating_channels.remove(member.id)
                return

            try:
                new_channel = await member.guild.create_voice_channel(
                    name=f"🏠║{member.display_name}",
                    category=category
                )

                self.user_channels[member.id] = new_channel.id
                await add_temp_channel(member.id, new_channel.id)
                await member.move_to(new_channel)

                embed = discord.Embed(
                    title="Voice channel control panel",
                    description="Use the buttons to navigate.",
                    color=discord.Color.yellow()
                )
                view = ChannelControlView(new_channel)
                await new_channel.send(embed=embed, view=view)
            except Exception as e:
                print(f"Error creating a channel: {e}")
            finally:
                self.creating_channels.remove(member.id)  # Remove a user from the block list

        # Handling a user's exit from a channel
        if before.channel and before.channel.id in self.user_channels.values():
            await asyncio.sleep(3)
            try:
                target_channel = before.channel
                if target_channel and len(target_channel.members) == 0:
                    channel_id = target_channel.id
                    await target_channel.delete()

                    await remove_temp_channel(channel_id)
                    for user_id, ch_id in list(self.user_channels.items()):
                        if ch_id == channel_id:
                            del self.user_channels[user_id]
            except Exception as e:
                print(f"Error while deleting a channel: {e}")


# BUTTONS
class ChannelControlView(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=None)
        self.channel = channel

    # Changing the channel name
    @discord.ui.button(
        label="Change name",
        emoji=discord.PartialEmoji(name='edit', id=1367560478041313422),
        style=discord.ButtonStyle.primary
    )
    async def rename_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RenameChannelModal(self.channel)
        await interaction.response.send_modal(modal)


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
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error when changing the channel name: {e}",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(VoiceManager(bot))