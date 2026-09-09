import asyncio
import aiosqlite
import logging
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

    # TABLE / MUSIC BOTs SETTINGS
    # The bot_token and bot_user_id entries are initially created as empty fields and are filled in later via the web dashboard.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS music_bots (
            bot_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_token TEXT,
            bot_user_id INTEGER,
            bot_status INTEGER NOT NULL DEFAULT 1
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
]


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

        default_settings = [
            # MAIN
            ("prefix", "+", "Main"),

            # VOICEMANAGER
            ("category_id", "0", "Voice"),
            ("main_voice_channel_id", "0", "Voice"),
            ("voice_channel_name_prefix", "🏠║", "Voice"),

            # MODULES
            ("voice_manger", "true", "Modules"),
            ("music_bots", "true", "Modules"),

            # MUSIC BOTS
            ("music_bot_id", "", "Music")
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

# ----------------------MUSIC BOTS-------------------------------------

# ADD MUSIC BOT
# Creates an empty, inactive bot record for the item just added to the panel, returning its ID for future updates and configuration.
async def add_music_bot():
    async with _db_lock:
        db = await _connect()
        cursor = await db.execute("INSERT INTO music_bots (bot_token, bot_status) VALUES (?, ?)", ("", 0))
        await db.commit()
        return cursor.lastrowid

# ---------------------------------------------------------------------

# UPDATE MUSIC BOT
# The dynamic SET part of the request updates only the fields that were actually sent,
# ignoring values of `None` so as not to overwrite other data
# (for example, the token when toggling the `status` switch).
async def update_music_bot(
    bot_rowid: int,
    bot_token: str | None = None,
    bot_user_id: int | None = None,
    bot_status: int | None = None,
):
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
        logging.info("No parameters provided for update. Skipping execution.")
        return

    # The bot_rowid is added to the end of params for the WHERE clause, since placeholders are substituted sequentially from left to right.
    params.append(bot_rowid)
    query = f"UPDATE music_bots SET {', '.join(fields)} WHERE bot_rowid = ?"

    try:
        async with _db_lock:
            db = await _connect()
            await db.execute(query, tuple(params))
            await db.commit()

    except Exception as e:
        logging.error(f"Error while update settings: {e}")

# ---------------------------------------------------------------------

# The function returns a record by ID, replacing None in the token with an empty string to make it easier to check for the presence of data.
async def get_music_bot(bot_rowid: int) -> tuple[int, str, int | None, int] | None:
    try:
        async with _db_lock:
            db = await _connect()
            async with db.execute(
                "SELECT bot_rowid, bot_token, bot_user_id, bot_status "
                "FROM music_bots WHERE bot_rowid = ?",
                (bot_rowid,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None

                r_id, token, user_id, status = row
                
                safe_user_id = int(user_id) if user_id is not None else None
                safe_token = str(token) if token is not None else ""
                
                return (int(r_id), safe_token, safe_user_id, int(status))

    except Exception as e:
        logging.error(f"Error while getting bot info: {e}")
        return None

# ---------------------------------------------------------------------

# The function returns all records without filtering, leaving it up to the caller to determine which bots are inactive or empty.
async def get_all_music_bots() -> list[tuple]:
    query = """
        SELECT bot_rowid, bot_token, bot_user_id, bot_status
        FROM music_bots
    """
    results: list[tuple] = []
    try:
        async with _db_lock:
            db = await _connect()
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                results = [tuple(row) for row in rows]

    except Exception as e:
        logging.error(f"Error while fetching music bot: {e}")
  
    return results

# ---------------------------------------------------------------------

# Deletes the bot's data from the db.
async def remove_music_bot(bot_rowid: int):
    try:
        async with _db_lock:
            db = await _connect()
            query = "DELETE FROM music_bots WHERE bot_rowid = ?"
            await db.execute(query, (bot_rowid,))
            await db.commit()
    except Exception as e:
        logging.error(f"Error while removing music bot {e}")