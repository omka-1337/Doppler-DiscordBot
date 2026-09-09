"""The temporary-channel table.

One row per live temp channel, so a restart can reconcile what still exists on
Discord instead of orphaning channels. `owner_id` moves when ownership is
handed over; `original_owner_id` never changes, which is how ownership can go
back to the creator when they rejoin.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS temp_channels (
    channel_id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    original_owner_id INTEGER NOT NULL
);
"""


class TempChannelStore:
    def __init__(self, db):
        self.db = db

    async def create_schema(self):
        await self.db.executescript(SCHEMA)

    async def add(self, channel_id: int, owner_id: int):
        await self.db.execute(
            """
            INSERT INTO temp_channels (channel_id, owner_id, original_owner_id)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET owner_id = excluded.owner_id
            """,
            (channel_id, owner_id, owner_id),
        )

    # Only the current owner changes; original_owner_id is deliberately left be.
    async def set_owner(self, channel_id: int, new_owner_id: int):
        await self.db.execute(
            "UPDATE temp_channels SET owner_id = ? WHERE channel_id = ?", (new_owner_id, channel_id)
        )

    async def remove(self, channel_id: int):
        await self.db.execute("DELETE FROM temp_channels WHERE channel_id = ?", (channel_id,))

    async def all(self) -> list[tuple[int, int, int]]:
        return await self.db.fetchall(
            "SELECT channel_id, owner_id, original_owner_id FROM temp_channels"
        )
