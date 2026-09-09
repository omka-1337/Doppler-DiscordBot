import asyncio
import aiosqlite
import logging
import os
import re
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

    # Migrate the pre-plugin schema (key alone as PRIMARY KEY). Unlike the
    # ephemeral temp_channels table this holds real configuration, so the rows
    # are copied across rather than recreated.
    pk_columns = [row[1] async for row in await db.execute("PRAGMA table_info(settings)") if row[5]]
    if pk_columns == ["key"]:
        await db.execute("""
            CREATE TABLE settings_migrated (
                category TEXT NOT NULL DEFAULT 'Main',
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (category, key)
            )
        """)
        await db.execute(
            "INSERT INTO settings_migrated (category, key, value) SELECT category, key, value FROM settings"
        )
        await db.execute("DROP TABLE settings")
        await db.execute("ALTER TABLE settings_migrated RENAME TO settings")
        logging.info("Migrated the settings table to a (category, key) primary key.")

    # TABLE / TEMPORARY VOICE CHANNELS
    # channel_id is the primary key (one row per channel): owner_id is the
    # current owner (changes on transfer) and original_owner_id never changes,
    # so ownership can be handed back if the creator rejoins later.
    existing_columns = {row[1] async for row in await db.execute("PRAGMA table_info(temp_channels)")}
    if existing_columns and "original_owner_id" not in existing_columns:
        # Pre-migration schema (owner_id as PK, no original owner tracking).
        # Temp channels are ephemeral session state — the real Discord channels
        # are untouched, they just go "unmanaged" until recreated.
        await db.execute("DROP TABLE temp_channels")

    await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_channels (
            channel_id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            original_owner_id INTEGER NOT NULL
        )
    """)

    await db.commit()


# LEGACY SETTINGS MIGRATION
# As each built-in module moves to the plugin API its settings move with it,
# from the core's own category into the plugin's namespace (the plugin id).
# Each entry is (old_category, old_key, new_category, new_key); a row is only
# moved if the plugin hasn't already got a value there, so this is safe to run
# on every startup and does nothing once the move has happened.
LEGACY_SETTINGS_MOVES = [
    # Translator
    ("Translator", "translator_provider", "translator", "provider"),
    ("Translator", "translator_deepl_api_key", "translator", "deepl_api_key"),
    ("Translator", "translator_google_api_key", "translator", "google_api_key"),
    ("Modules", "translator", "Plugins", "translator"),

    # AI chat
    ("AI", "ai_provider", "ai", "provider"),
    ("AI", "ai_gemini_api_key", "ai", "gemini_api_key"),
    ("AI", "ai_deepseek_api_key", "ai", "deepseek_api_key"),
    ("AI", "ai_chatgpt_api_key", "ai", "chatgpt_api_key"),
    ("AI", "ai_bot_name", "ai", "bot_name"),
    ("AI", "ai_system_prompt", "ai", "system_prompt"),
    ("AI", "ai_force_language", "ai", "force_language"),
    ("AI", "ai_language", "ai", "language"),
    ("AI", "ai_irony", "ai", "irony"),
    ("AI", "ai_seriousness", "ai", "seriousness"),
    ("AI", "ai_enabled", "Plugins", "ai"),
    # Never read by any code path -- carried over so it stops lingering in the table.
    ("Modules", "ai_features", "Plugins", "ai"),

    # Moderation
    ("Moderation", "mod_log_enabled", "moderation", "log_enabled"),
    ("Moderation", "mod_log_channel_id", "moderation", "log_channel_id"),
    ("Modules", "moderation", "Plugins", "moderation"),

    # Server Protect (keys keep their names; only the namespace changes)
    ("ServerProtect", "min_account_age_days", "serverprotect", "min_account_age_days"),
    ("ServerProtect", "verified_role_id", "serverprotect", "verified_role_id"),
    ("ServerProtect", "raid_mode", "serverprotect", "raid_mode"),
    ("ServerProtect", "raid_join_threshold", "serverprotect", "raid_join_threshold"),
    ("ServerProtect", "raid_join_window_seconds", "serverprotect", "raid_join_window_seconds"),
    ("ServerProtect", "raid_alert_channel_id", "serverprotect", "raid_alert_channel_id"),
    ("ServerProtect", "raid_lockdown_duration_minutes", "serverprotect", "raid_lockdown_duration_minutes"),
    ("ServerProtect", "raid_lockdown_active", "serverprotect", "raid_lockdown_active"),
    ("ServerProtect", "raid_lockdown_started_at", "serverprotect", "raid_lockdown_started_at"),
    ("Modules", "server_protect", "Plugins", "serverprotect"),

    # Music
    ("Modules", "music_bots", "Plugins", "music"),
]


# As with settings, a module moving to the plugin API takes its tables with it,
# from the core database into savedata/plugins/<id>/data.db. Each entry is
# (table, plugin_id). The table is copied with its schema intact and then
# dropped here, so this runs once and finds nothing on later startups.
LEGACY_TABLE_MOVES = [
    ("music_bots", "music"),
]


# Secrets a migrated module used to read straight out of the environment. They
# are copied into the plugin's namespace once, so the plugin never touches
# os.getenv and the value becomes editable from the dashboard like any other
# setting. Each entry is (env var, plugin_id, key); an unset variable or an
# existing value is left alone.
LEGACY_ENV_SEEDS = [
    ("LAVALINK_PASSWORD", "music", "lavalink_password"),
    ("LAVALINK_URI", "music", "lavalink_uri"),
]


async def seed_settings_from_env(db):
    for env_var, plugin_id, key in LEGACY_ENV_SEEDS:
        value = os.getenv(env_var)
        if not value:
            continue
        await db.execute(
            """
            INSERT INTO settings (category, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(category, key) DO NOTHING
            """,
            (plugin_id, key, value),
        )
    await db.commit()


async def migrate_legacy_tables(db):
    for table, plugin_id in LEGACY_TABLE_MOVES:
        async with db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or not row[0]:
            continue

        # Recreate the table verbatim in the plugin's database so the primary
        # key and AUTOINCREMENT survive -- "CREATE TABLE ... AS SELECT" loses them.
        create_sql, count = re.subn(
            rf"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?{table}[\"'`\]]?",
            f'CREATE TABLE IF NOT EXISTS plugin_db."{table}"',
            row[0],
            count=1,
            flags=re.IGNORECASE,
        )
        if count != 1:
            logging.error(f"Could not rewrite the schema for {table!r}; leaving it in place.")
            continue

        target_dir = SAVEDATA_DIR / "plugins" / plugin_id
        target_dir.mkdir(parents=True, exist_ok=True)

        await db.execute("ATTACH DATABASE ? AS plugin_db", (str(target_dir / "data.db"),))
        try:
            await db.execute(create_sql)
            await db.execute(f'INSERT INTO plugin_db."{table}" SELECT * FROM main."{table}"')
            await db.execute(f'DROP TABLE main."{table}"')
            await db.commit()
            logging.info(f"Moved the {table!r} table into the {plugin_id!r} plugin's database.")
        finally:
            await db.execute("DETACH DATABASE plugin_db")


async def migrate_legacy_settings(db):
    moved = 0
    for old_cat, old_key, new_cat, new_key in LEGACY_SETTINGS_MOVES:
        async with db.execute(
            "SELECT value FROM settings WHERE category = ? AND key = ?", (old_cat, old_key)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            continue

        await db.execute(
            """
            INSERT INTO settings (category, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(category, key) DO NOTHING
            """,
            (new_cat, new_key, row[0]),
        )
        await db.execute("DELETE FROM settings WHERE category = ? AND key = ?", (old_cat, old_key))
        moved += 1

    if moved:
        await db.commit()
        logging.info(f"Moved {moved} legacy setting(s) into their plugin namespaces.")


# INIT DB
async def init_db():
    async with _db_lock:
        db = await _connect()
        await migrate_legacy_settings(db)
        await migrate_legacy_tables(db)
        await seed_settings_from_env(db)

        default_settings = [
            # MAIN
            ("prefix", "+", "Main"),

            # VOICEMANAGER
            ("category_id", "0", "Voice"),
            ("main_voice_channel_id", "0", "Voice"),
            ("voice_channel_name_prefix", "🏠║", "Voice"),

            # MODULES
            ("voice_manger", "true", "Modules"),

        ]

        # Calling ON CONFLICT DO NOTHING during startup applies only the initial default settings without overwriting changes already made by the user.
        for key, val, cat in default_settings:
            try:
                await db.execute(
                    """
                    INSERT INTO settings (key, value, category)
                    VALUES (?, ?, ?)
                    ON CONFLICT(category, key) DO NOTHING
                    """,
                    (key, val, cat),
                )
            except Exception as e:
                logging.error(f"Error inserting default settings: {e}")

        await db.commit()


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


# ---> VOICE MANAGER
# ADD TEMP CHANNEL
# Only used for a brand-new channel, so the current and original owner are
# the same person at this point.
async def add_temp_channel(channel_id: int, owner_id: int):
    async with _db_lock:
        db = await _connect()
        await db.execute(
            "INSERT OR REPLACE INTO temp_channels (channel_id, owner_id, original_owner_id) VALUES (?, ?, ?)",
            (channel_id, owner_id, owner_id),
        )
        await db.commit()


# TRANSFER (OR RESTORE) OWNERSHIP OF AN EXISTING CHANNEL
# Deliberately leaves original_owner_id untouched, so it can still be used later
# to hand ownership back if the original creator rejoins.
async def set_temp_channel_owner(channel_id: int, new_owner_id: int):
    async with _db_lock:
        db = await _connect()
        await db.execute(
            "UPDATE temp_channels SET owner_id = ? WHERE channel_id = ?",
            (new_owner_id, channel_id),
        )
        await db.commit()


# REMOVE TEMP CHANNEL
async def remove_temp_channel(channel_id: int):
    async with _db_lock:
        db = await _connect()
        await db.execute(
            "DELETE FROM temp_channels WHERE channel_id = ?",
            (channel_id,),
        )
        await db.commit()


# GET ALL TEMP CHANNELS
async def get_all_temp_channels() -> list[tuple[int, int, int]]:
    async with _db_lock:
        db = await _connect()
        async with db.execute(
            "SELECT channel_id, owner_id, original_owner_id FROM temp_channels"
        ) as cursor:
            rows = await cursor.fetchall()
            return [tuple(row) for row in rows]
