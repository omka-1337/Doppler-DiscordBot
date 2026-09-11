"""What the plugin's dashboard page can ask for.

These used to be special-cased routes inside the bot itself, which meant the
core carried code for one plugin. They belong here: the worker table, the
Lavalink address and the YouTube token are all this plugin's own.
"""

import httpx


class MusicPanel:
    """Endpoint handlers, kept apart from the plugin's Discord side."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.log = plugin.log

    @property
    def store(self):
        return self.plugin.store

    @property
    def manager(self):
        return self.plugin.bot.get_cog("MusicBotsManager")

    def register(self, ctx):
        try:
            ctx.add_endpoint("GET", "/bots", self.list_bots)
            ctx.add_endpoint("POST", "/add", self.add_bot)
            ctx.add_endpoint("POST", "/remove", self.remove_bot)
            ctx.add_endpoint("POST", "/save-token", self.save_token)
            ctx.add_endpoint("POST", "/set-active", self.set_active)
            ctx.add_endpoint("GET", "/youtube", self.youtube_status)
            ctx.add_endpoint("POST", "/youtube", self.youtube_token)
        except PermissionError as e:
            # Untrusted plugins may not declare endpoints. Playback still works;
            # only the page would have nothing to talk to.
            self.log.warning("%s", e)

    # -- worker identity ------------------------------------------------

    async def _identity(self, user_id: int | None, running_client) -> dict:
        """The worker's Discord name and avatar, for the card in the panel.

        A running worker knows itself. A stopped one is looked up by the id
        recorded the last time it connected, using the main bot's token -- the
        worker's own token is never sent anywhere for this.
        """
        user = running_client.user if running_client is not None else None

        if user is None and user_id:
            main = self.plugin.bot
            user = main.get_user(user_id)
            if user is None:
                try:
                    user = await main.fetch_user(user_id)
                except Exception as e:
                    self.log.debug("Could not resolve worker %s: %s", user_id, e)

        if user is None:
            return {"username": None, "global_name": None, "avatar_url": None}

        return {
            "username": user.name,
            "global_name": getattr(user, "global_name", None) or user.name,
            "avatar_url": user.display_avatar.url if user.display_avatar else None,
        }

    # -- endpoints ------------------------------------------------------

    async def list_bots(self, request):
        manager = self.manager
        running = manager.running_bots if manager is not None else {}

        bots = []
        for row_id, token, user_id, status in await self.store.all():
            row_id = int(row_id)
            bots.append({
                "id": row_id,
                "token": token or "",
                "active": bool(status),
                "running": row_id in running,
                **await self._identity(user_id, running.get(row_id)),
            })
        return {"bots": bots}

    async def add_bot(self, request):
        return {"status": "ok", "id": await self.store.add()}

    async def remove_bot(self, request):
        body = await request.json()
        row_id = int(body.get("id") or 0)
        if not row_id:
            return {"status": "error", "message": "No worker given."}

        manager = self.manager
        if manager is not None:
            await manager.stop_music_bot(row_id)
        await self.store.remove(row_id)
        return {"status": "ok"}

    async def save_token(self, request):
        body = await request.json()
        row_id = int(body.get("id") or 0)
        token = str(body.get("token", "")).strip()
        if not row_id:
            return {"status": "error", "message": "No worker given."}

        await self.store.update(row_id, bot_token=token)

        # Restarted here so the new token takes effect without a reload.
        manager = self.manager
        if manager is not None:
            await manager.stop_music_bot(row_id)
            if token:
                await manager.start_single_bot(row_id, token)
        return {"status": "ok"}

    async def set_active(self, request):
        body = await request.json()
        row_id = int(body.get("id") or 0)
        active = bool(body.get("active"))
        if not row_id:
            return {"status": "error", "message": "No worker given."}

        await self.store.update(row_id, bot_status=int(active))

        manager = self.manager
        if manager is None:
            return {"status": "ok"}

        if not active:
            await manager.stop_music_bot(row_id)
            return {"status": "ok"}

        row = await self.store.get(row_id)
        if row is None:
            return {"status": "error", "message": "No such worker."}
        if not row[1]:
            return {"status": "error", "message": "This worker has no token yet."}

        await manager.start_single_bot(row_id, row[1])
        return {"status": "ok"}

    # -- YouTube OAuth, which is Lavalink's, not Discord's ---------------

    async def _lavalink(self):
        settings = await self.plugin.settings.all()
        return settings["lavalink_uri"], settings["lavalink_password"]

    async def youtube_status(self, request):
        uri, password = await self._lavalink()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{uri}/youtube", headers={"Authorization": password}, timeout=5.0
                )
        except Exception as e:
            return {"status": "error", "message": f"Lavalink is not reachable: {e}"}

        if response.status_code != 200:
            return {"status": "error", "message": "Lavalink returned an error."}

        return {"status": "ok", "configured": response.json().get("refreshToken") is not None}

    async def youtube_token(self, request):
        body = await request.json()
        refresh_token = str(body.get("refresh_token", "")).strip()

        # Stored as a setting so the broker also hands it to the Lavalink
        # container as environment next time the sidecar is created.
        await self.plugin.settings.set("youtube_oauth_refresh_token", refresh_token)

        uri, password = await self._lavalink()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{uri}/youtube",
                    headers={"Authorization": password},
                    json={"refreshToken": refresh_token, "skipInitialization": True},
                    timeout=5.0,
                )
        except Exception as e:
            return {"status": "error", "message": f"Lavalink is not reachable: {e}"}

        if response.status_code != 204:
            return {"status": "error", "message": "Lavalink rejected the token."}

        return {"status": "ok"}
