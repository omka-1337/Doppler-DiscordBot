"""Per-plugin SQLite storage.

Settings cover key/value configuration; anything with real structure -- a list
of worker accounts, a warning history -- needs a table. Each plugin gets its
own database file under ``savedata/plugins/<id>/data.db`` rather than sharing
the core's, so a plugin cannot read or corrupt another's data, removing a
plugin removes its data with it, and a plugin owns its own schema without
needing a migration in the core.

The plugin creates its tables in ``setup()``; nothing here inspects or
manages the schema.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

import aiosqlite


class PluginDatabase:
    """One SQLite file, owned by one plugin.

    A single shared connection guarded by a lock, mirroring how the core
    database behaves: opening a connection per query is expensive, and
    serialising access avoids "database is locked" under concurrent commands.
    """

    def __init__(self, plugin_id: str, path: Path):
        self.plugin_id = plugin_id
        self.path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._log = logging.getLogger(f"plugin.{plugin_id}")

    async def _connect(self) -> aiosqlite.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(self.path)
        return self._db

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a write and commit it. Returns lastrowid, useful after INSERT."""
        async with self._lock:
            db = await self._connect()
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor.lastrowid or 0

    async def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> None:
        async with self._lock:
            db = await self._connect()
            await db.executemany(sql, params)
            await db.commit()

    async def executescript(self, script: str) -> None:
        """Run several statements at once -- for creating a plugin's schema."""
        async with self._lock:
            db = await self._connect()
            await db.executescript(script)
            await db.commit()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> tuple | None:
        async with self._lock:
            db = await self._connect()
            async with db.execute(sql, params) as cursor:
                return await cursor.fetchone()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        async with self._lock:
            db = await self._connect()
            async with db.execute(sql, params) as cursor:
                return list(await cursor.fetchall())

    async def close(self) -> None:
        """Close the connection.

        Called when the plugin unloads. aiosqlite runs its connection on a
        thread, so a connection left open would keep that thread alive across
        every reload.
        """
        async with self._lock:
            if self._db is not None:
                try:
                    await self._db.close()
                except Exception:
                    self._log.exception("Failed to close the plugin database")
                self._db = None
