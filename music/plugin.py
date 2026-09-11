from dopplerbot.plugins.api import Plugin, PluginSetting, ServiceUnavailable, SettingType

from .commands import MusicCommands
from .manager import MusicBotsManager
from .panel import MusicPanel
from .store import MusicBotStore


class MusicPlugin(Plugin):
    SETTINGS = (
        PluginSetting(
            "lavalink_uri",
            SettingType.STRING,
            default="http://doppler_plg_music_lavalink:2333",
            label="Lavalink address",
            description=(
                "Set automatically when the broker starts the bundled Lavalink service. "
                "Change it only to point at a Lavalink you run yourself."
            ),
        ),
        PluginSetting(
            "lavalink_password",
            SettingType.SECRET,
            default="",
            label="Lavalink password",
            description="Passed to the Lavalink container and used by the workers to connect.",
        ),
        PluginSetting(
            "youtube_oauth_refresh_token",
            SettingType.SECRET,
            default="",
            label="YouTube OAuth refresh token",
            description="Optional. Lets Lavalink play YouTube sources that need a signed-in client.",
        ),
    )

    async def setup(self):
        # Worker accounts are a table rather than settings, so they live in the
        # plugin's own database. The schema is created here because the plugin
        # owns it -- the core knows nothing about this table.
        self.sidecar_started = False
        self.store = MusicBotStore(self.ctx.db)
        await self.store.create_schema()

        await self._ensure_lavalink()

        await self.ctx.add_cog(MusicBotsManager(self))
        await self.ctx.add_cog(MusicCommands(self))

        # Worker accounts are a table with live processes behind them, which no
        # generated settings form can express -- so this plugin ships a page.
        self.panel = MusicPanel(self)
        self.panel.register(self.ctx)

    async def _ensure_lavalink(self):
        """Ask the broker for the Lavalink sidecar declared in the manifest.

        Returning without it is not fatal: the workers will still try the
        configured address, which is how someone running their own Lavalink
        (or a stack without the broker) keeps working.
        """
        try:
            service = await self.ctx.services.start("lavalink")
        except ServiceUnavailable as e:
            self.log.warning(
                "Lavalink sidecar unavailable (%s); falling back to the configured address.", e
            )
            return

        self.sidecar_started = True
        if service.get("uri"):
            await self.settings.set("lavalink_uri", service["uri"])
