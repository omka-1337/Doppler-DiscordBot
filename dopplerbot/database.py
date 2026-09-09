import asyncio
import aiosqlite
import os
from pathlib import Path

SAVEDATA_DIR = Path(__file__).resolve().parent.parent / "savedata"
SAVEDATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = SAVEDATA_DIR / "bot.db"

# A single, shared connection for the entire bot process (opening new connections for every request is expensive and doesn't make sense).
_db: aiosqlite.Connection | None = None

# Locks the database until the query is completed. This ensures sequential access, which prevents "database is locked" errors.
_db_lock = asyncio.Lock()


async def _connect() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        await ensure_tables(_db)
    return _db


async def close_db():
    global _db
    async with _db_lock:
        if _db is not None:
            await _db.close()
            _db = None


# FORCE TABLE CREATION
async def ensure_tables(db):
    # Settings are keyed by (category, key), where category doubles as the
    # plugin's namespace — a plugin declaring a common key like "channel_id"
    # must not collide with another plugin doing the same.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            category TEXT NOT NULL DEFAULT 'Main',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (category, key)
        )
    """)

    await db.commit()


# First-run seeding, not a migration: `make start` writes a generated Lavalink
# password into .env, and this is how it reaches the music plugin's settings.
# Without it music would not work on a fresh install. Each entry is
# (env var, plugin_id, key); an unset variable is skipped, and a value already
# set from the dashboard is never overwritten.
ENV_SEEDS = [
    ("LAVALINK_PASSWORD", "music", "lavalink_password"),
    ("LAVALINK_URI", "music", "lavalink_uri"),
    ("YOUTUBE_OAUTH_REFRESH_TOKEN", "music", "youtube_oauth_refresh_token"),
]


async def seed_settings_from_env(db):
    for env_var, plugin_id, key in ENV_SEEDS:
        value = os.getenv(env_var)
        if not value:
            continue
        # Fill in a value that is missing *or* still blank: a placeholder row
        # created by a default should not shadow a real key sitting in .env.
        await db.execute(
            """
            INSERT INTO settings (category, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value
            WHERE settings.value = ''
            """,
            (plugin_id, key, value),
        )
    await db.commit()


# INIT DB
async def init_db():
    async with _db_lock:
        db = await _connect()
        await seed_settings_from_env(db)


# ---> SETTINGS
# GETTING SETTINGS
# category is optional for backwards compatibility: without it the first match
# for the key is returned regardless of namespace, which is only safe for the
# handful of globally-unique core keys (prefix, home_guild_id, module toggles).
async def get_settings(key: str, default: str | None = None, category: str | None = None) -> str | None:
    if category is None:
        query, params = "SELECT value FROM settings WHERE key = ? LIMIT 1", (key,)
    else:
        query, params = "SELECT value FROM settings WHERE category = ? AND key = ?", (category, key)

    async with _db_lock:
        db = await _connect()
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default


# GETTING CATEGORY SETTINGS
async def get_settings_by_category(category: str = "Main") -> dict[str, str]:
    async with _db_lock:
        db = await _connect()
        async with db.execute(
            "SELECT key, value FROM settings WHERE category = ?",
            (category,),
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}


# SAVES CHANGES TO THE SETTINGS
async def set_settings(key: str, value: str, category: str = "Main"):
    async with _db_lock:
        db = await _connect()
        await db.execute(
            """
            INSERT INTO settings (category, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value
            """,
            (category, key, value),
        )
        await db.commit()
