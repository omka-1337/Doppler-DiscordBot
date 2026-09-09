from dopplerbot.plugins.api import Plugin, PluginSetting, SettingType

from .commands import MusicCommands
from .manager import MusicBotsManager
from .store import MusicBotStore


class MusicPlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "lavalink_uri",
            SettingType.STRING,
            default="http://lavalink_music_server:2333",
            label="Lavalink address",
            description="Where the Lavalink audio server is reachable.",
        ),
        PluginSetting(
            "lavalink_password",
            SettingType.SECRET,
            default="",
            label="Lavalink password",
            description="Must match the password Lavalink itself is running with.",
        ),
    )

    async def setup(self):
        # Worker accounts are a table rather than settings, so they live in the
        # plugin's own database. The schema is created here because the plugin
        # owns it -- the core knows nothing about this table.
        self.store = MusicBotStore(self.ctx.db)
        await self.store.create_schema()

        await self.ctx.add_cog(MusicBotsManager(self))
        await self.ctx.add_cog(MusicCommands(self))
