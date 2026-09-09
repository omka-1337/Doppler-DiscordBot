"""The music plugin's worker-account table.

Each row is one Discord bot account used as a playback worker. The data lives
in the plugin's own database (ctx.db), so it travels with the plugin rather
than sitting in the core's table.
"""

import logging

SCHEMA = """
CREATE TABLE IF NOT EXISTS music_bots (
    bot_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_token TEXT,
    bot_user_id INTEGER,
    bot_status INTEGER NOT NULL DEFAULT 1
);
"""


class MusicBotStore:
    def __init__(self, db):
        self.db = db

    async def create_schema(self):
        await self.db.executescript(SCHEMA)

    # Creates an empty, inactive record for a row just added in the panel,
    # returning its id so the token can be filled in afterwards.
    async def add(self) -> int:
        return await self.db.execute(
            "INSERT INTO music_bots (bot_token, bot_status) VALUES (?, ?)", ("", 0)
        )

    # Only the fields actually passed are updated, so flipping the status
    # switch doesn't blank out the token.
    async def update(
        self,
        bot_rowid: int,
        bot_token: str | None = None,
        bot_user_id: int | None = None,
        bot_status: int | None = None,
    ) -> None:
        if not bot_rowid:
            logging.warning("Failed to update: bot_rowid is missing or invalid.")
            return

        fields: list[str] = []
        params: list[str | int] = []

        if bot_token is not None:
            fields.append("bot_token = ?")
            params.append(bot_token)
        if bot_user_id is not None:
            fields.append("bot_user_id = ?")
            params.append(bot_user_id)
        if bot_status is not None:
            fields.append("bot_status = ?")
            params.append(bot_status)

        if not fields:
            return

        params.append(bot_rowid)
        await self.db.execute(
            f"UPDATE music_bots SET {', '.join(fields)} WHERE bot_rowid = ?", tuple(params)
        )

    async def get(self, bot_rowid: int) -> tuple[int, str, int | None, int] | None:
        row = await self.db.fetchone(
            "SELECT bot_rowid, bot_token, bot_user_id, bot_status FROM music_bots WHERE bot_rowid = ?",
            (bot_rowid,),
        )
        if row is None:
            return None

        r_id, token, user_id, status = row
        return (
            int(r_id),
            str(token) if token is not None else "",
            int(user_id) if user_id is not None else None,
            int(status),
        )

    # Returns every record unfiltered; the caller decides which are inactive.
    async def all(self) -> list[tuple]:
        return await self.db.fetchall(
            "SELECT bot_rowid, bot_token, bot_user_id, bot_status FROM music_bots"
        )

    async def remove(self, bot_rowid: int) -> None:
        await self.db.execute("DELETE FROM music_bots WHERE bot_rowid = ?", (bot_rowid,))
