import aiosqlite
import logging

logger = logging.getLogger(__name__)

DB_PATH = "data/bot_data.db"
_db_connection = None

async def get_db():
    global _db_connection
    if _db_connection is None:
        _db_connection = await aiosqlite.connect(DB_PATH)
        _db_connection.row_factory = aiosqlite.Row
        await _db_connection.execute("PRAGMA journal_mode=WAL")
        await _db_connection.execute("PRAGMA busy_timeout=5000")
    return _db_connection

async def close_db():
    global _db_connection
    if _db_connection:
        await _db_connection.close()
        _db_connection = None

async def init_db():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            is_admin BOOLEAN DEFAULT 0,
            is_whitelisted BOOLEAN DEFAULT 0,
            adm_code TEXT,
            adm_name TEXT,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            chat_id INTEGER PRIMARY KEY,
            notify_quake INTEGER DEFAULT 1,
            notify_weather INTEGER DEFAULT 1,
            notify_nowcast INTEGER DEFAULT 1,
            FOREIGN KEY (chat_id) REFERENCES users(chat_id)
        )
    """)

    await db.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bot_mode', 'OPEN')")
    await db.commit()

async def get_bot_mode():
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key = 'bot_mode'")
    row = await cursor.fetchone()
    return row[0] if row else "OPEN"

async def set_bot_mode(mode):
    db = await get_db()
    await db.execute("UPDATE config SET value = ? WHERE key = 'bot_mode'", (mode,))
    await db.commit()

async def add_user(chat_id: int, username: str):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO users (chat_id, username) VALUES (?, ?)", (chat_id, username))
    await db.execute("INSERT OR IGNORE INTO user_prefs (chat_id) VALUES (?)", (chat_id,))
    await db.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP, username = ? WHERE chat_id = ?", (username, chat_id))
    await db.commit()

async def count_users():
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM users")
    res = await cursor.fetchone()
    return res[0]

async def is_user_whitelisted(chat_id):
    db = await get_db()
    cursor = await db.execute("SELECT is_whitelisted FROM users WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    return row[0] == 1 if row else False

async def add_to_whitelist(chat_id):
    db = await get_db()
    await db.execute("UPDATE users SET is_whitelisted = 1 WHERE chat_id = ?", (chat_id,))
    await db.commit()

async def remove_from_whitelist(chat_id):
    db = await get_db()
    await db.execute("UPDATE users SET is_whitelisted = 0 WHERE chat_id = ?", (chat_id,))
    await db.commit()

async def get_all_whitelisted():
    db = await get_db()
    cursor = await db.execute("SELECT chat_id, username FROM users WHERE is_whitelisted = 1")
    return await cursor.fetchall()

async def update_user_location(chat_id, adm_code, adm_name):
    db = await get_db()
    await db.execute(
        "UPDATE users SET adm_code = ?, adm_name = ? WHERE chat_id = ?",
        (adm_code, adm_name, chat_id)
    )
    await db.commit()

async def get_user_info(chat_id):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    return await cursor.fetchone()

async def get_all_users():
    db = await get_db()
    cursor = await db.execute("SELECT chat_id, adm_code, adm_name FROM users")
    return await cursor.fetchall()

async def get_metadata(key):
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None

async def update_metadata(key, value):
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    await db.commit()

async def check_and_update_alert(key_name, new_value):
    db = await get_db()
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key_name,))
    row = await cursor.fetchone()
    old_value = row[0] if row else None
    if old_value != str(new_value):
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key_name, str(new_value)))
        await db.commit()
        return True
    return False

async def cleanup_old_alerts():
    db = await get_db()
    await db.execute("DELETE FROM config WHERE key LIKE 'cap_%'")
    await db.commit()

async def get_user_prefs(chat_id):
    db = await get_db()
    cursor = await db.execute("SELECT * FROM user_prefs WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    if row:
        return dict(row)
    return {"notify_quake": 1, "notify_weather": 1, "notify_nowcast": 1}

async def update_user_pref(chat_id, pref_name: str, value: bool):
    db = await get_db()
    int_val = 1 if value else 0
    await db.execute(
        f"UPDATE user_prefs SET {pref_name} = ? WHERE chat_id = ?",
        (int_val, chat_id)
    )
    await db.commit()

async def get_users_with_pref(pref_name: str):
    valid_prefs = {"notify_quake", "notify_weather", "notify_nowcast"}
    if pref_name not in valid_prefs:
        raise ValueError(f"Unknown pref: {pref_name}")

    db = await get_db()
    cursor = await db.execute(
        f"SELECT u.chat_id, u.adm_code, u.adm_name FROM users u "
        f"JOIN user_prefs p ON u.chat_id = p.chat_id "
        f"WHERE p.{pref_name} = 1"
    )
    return await cursor.fetchall()
