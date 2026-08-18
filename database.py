import asyncio
import aiosqlite
import logging
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "bot.db"

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
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Main'
        )
    """)

    # TABLE / TEMPORARY VOICE CHANNELS
    await db.execute("""
        CREATE TABLE IF NOT EXISTS temp_channels (
            owner_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL
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


# INIT DB
async def init_db():
    async with _db_lock:
        db = await _connect()

        default_settings = [
            # MAIN
            ("prefix", "+", "Main"),
            # AI
            ("ai_chat_enabled", "true", "AI"),
            ("ai_bot_name", "Kara AI", "AI"),
            ("ai_system_prompt", "You're a moderator on Discord. Be polite and helpful.", "AI"),
            ("ai_language", "English", "AI"),
            ("ai_irony", "0.2", "AI"),
            ("ai_seriousness", "0.8", "AI"),
            ("ai_force_language", "false", "AI"),
            # VOICEMANAGER
            ("category_id", "0", "Voice"),
            ("main_voice_channel_id", "0", "Voice"),
            # MODULES
            ("ai_features", "true", "Modules"),
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
                    ON CONFLICT(key) DO NOTHING
                    """,
                    (key, val, cat),
                )
            except Exception as e:
                logging.error(f"Error inserting default settings: {e}")

        await db.commit()


# ---> SETTINGS
# GETTING SETTINGS
async def get_settings(key: str, default: str | None = None) -> str | None:
    async with _db_lock:
        db = await _connect()
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
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
            INSERT INTO settings (key, value, category) 
            VALUES (?, ?, ?) 
            ON CONFLICT(key) DO UPDATE SET 
                value = excluded.value, 
                category = excluded.category
            """,
            (key, value, category),
        )
        await db.commit()


# ---> VOICE MANAGER
# ADD TEMP CHANNEL
async def add_temp_channel(owner_id: int, channel_id: int):
    async with _db_lock:
        db = await _connect()
        await db.execute(
            "INSERT OR REPLACE INTO temp_channels (owner_id, channel_id) VALUES (?, ?)",
            (owner_id, channel_id),
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
async def get_all_temp_channels() -> list[tuple[int, int]]:
    async with _db_lock:
        db = await _connect()
        async with db.execute("SELECT owner_id, channel_id FROM temp_channels") as cursor:
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