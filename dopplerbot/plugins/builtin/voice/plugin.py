from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

from .manager import VoiceManager
from .store import TempChannelStore
from .view import ChannelControlView


class VoicePlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "main_voice_channel_id",
            SettingType.CHANNEL,
            default=0,
            label="Hub voice channel ID",
            description="Joining this channel creates a private channel and moves the member into it.",
        ),
        PluginSetting(
            "category_id",
            SettingType.CHANNEL,
            default=0,
            label="Category ID for new rooms",
            description="The category temporary voice channels are created in.",
        ),
        PluginSetting(
            "channel_name_prefix",
            SettingType.STRING,
            default="🏠║",
            label="Channel name prefix",
            description="Prepended to the member's display name, e.g. 🏠║username.",
        ),
    )

    async def setup(self):
        self.store = TempChannelStore(self.ctx.db)
        await self.store.create_schema()

        # Registered through the context so reloading the plugin doesn't leave
        # the old view listening for the buttons.
        self.ctx.add_view(ChannelControlView())
        await self.ctx.add_cog(VoiceManager(self))
