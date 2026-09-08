# VOICE CHANNELS MANAGER

import asyncio
import random
import discord
from discord.ext import commands
from dopplerbot.database import (
    get_settings_by_category,
    get_all_temp_channels,
    add_temp_channel,
    set_temp_channel_owner,
    remove_temp_channel,
)
from utils.voice.VoiceControlView import ChannelControlView


class VoiceManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # channel_id -> current owner_id. The owner is the only one allowed to
        # manage the channel via ChannelControlView; ownership transfers to a
        # random remaining member if they leave.
        self.channel_owners: dict[int, int] = {}
        # channel_id -> original creator's id. Never changes for the life of the
        # channel, so ownership can be handed back if they rejoin later.
        self.original_owners: dict[int, int] = {}
        self.creating_channels = set()
        bot.add_view(ChannelControlView())

    # AFTER A RESTART SYNCS THE CHANNELS WITH THE DATABASE
    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()

        db_channels = await get_all_temp_channels()
        for channel_id, owner_id, original_owner_id in db_channels:
            channel = self.bot.get_channel(channel_id)

            if channel:
                if len(channel.members) == 0:
                    try:
                        await channel.delete()
                        await remove_temp_channel(channel_id)
                    except Exception as e:
                        print(f"Error deleting orphan channel {channel_id}: {e}")
                else:
                    self.channel_owners[channel_id] = owner_id
                    self.original_owners[channel_id] = original_owner_id
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
                name_prefix = voice_settings.get("voice_channel_name_prefix", "🏠║")
                new_channel = await member.guild.create_voice_channel(
                    name=f"{name_prefix}{member.display_name}",
                    category=category
                )

                self.channel_owners[new_channel.id] = member.id
                self.original_owners[new_channel.id] = member.id
                await add_temp_channel(new_channel.id, member.id)
                await member.move_to(new_channel)

                embed = discord.Embed(
                    title="Voice channel control panel",
                    description=f"{member.mention} owns this channel and is the only one who can manage it below.",
                    color=discord.Color.yellow()
                )
                view = ChannelControlView()
                await new_channel.send(embed=embed, view=view)
            except Exception as e:
                print(f"Error creating a channel: {e}")
            finally:
                self.creating_channels.remove(member.id)  # Remove a user from the block list

        # The original creator rejoining gets ownership back automatically,
        # even if someone else was holding it while they were away.
        if after.channel and after.channel.id in self.original_owners:
            channel_id = after.channel.id
            if (
                member.id == self.original_owners[channel_id]
                and self.channel_owners.get(channel_id) != member.id
            ):
                self.channel_owners[channel_id] = member.id
                await set_temp_channel_owner(channel_id, member.id)
                try:
                    await after.channel.send(
                        f"👑 {member.mention} is back — ownership of this channel returned to its original creator."
                    )
                except discord.Forbidden:
                    pass

        # Handling a user's exit from a channel.
        # on_voice_state_update also fires for mute/deafen/streaming toggles
        # where the member never actually left (before.channel == after.channel)
        # — without this check, muting would look identical to leaving and
        # wrongly trigger an ownership transfer / empty-channel cleanup.
        if before.channel and before.channel != after.channel and before.channel.id in self.channel_owners:
            channel_id = before.channel.id

            # The owner left but others remain: hand ownership to a random
            # remaining member who doesn't already own a different channel.
            if self.channel_owners.get(channel_id) == member.id:
                remaining = [
                    m for m in before.channel.members
                    if not m.bot and m.id not in self.channel_owners.values()
                ]
                if remaining:
                    new_owner = random.choice(remaining)
                    self.channel_owners[channel_id] = new_owner.id
                    await set_temp_channel_owner(channel_id, new_owner.id)
                    try:
                        await before.channel.send(
                            f"👑 {new_owner.mention} is now the owner of this channel (previous owner left)."
                        )
                    except discord.Forbidden:
                        pass
                else:
                    del self.channel_owners[channel_id]

            await asyncio.sleep(3)
            try:
                target_channel = before.channel
                if target_channel and len(target_channel.members) == 0:
                    await target_channel.delete()
                    await remove_temp_channel(channel_id)
                    self.channel_owners.pop(channel_id, None)
                    self.original_owners.pop(channel_id, None)
            except Exception as e:
                print(f"Error while deleting a channel: {e}")


async def setup(bot):
    await bot.add_cog(VoiceManager(bot))
