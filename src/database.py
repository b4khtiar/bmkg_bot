import aiosqlite
import logging
import json
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_PATH = "data/bot_data.db"
WEATHER_CACHE_TTL_MIN = 15
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

    await db.execute("""
        CREATE TABLE IF NOT EXISTS weather_cache (
            adm_code TEXT PRIMARY KEY,
            cached_json TEXT NOT NULL,
            cached_at DATETIME NOT NULL
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS pending_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            photo_url TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS weather_image_cache (
            condition_group TEXT PRIMARY KEY,
            image_url TEXT NOT NULL,
            photographer TEXT NOT NULL,
            cached_at DATETIME NOT NULL
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

async def mark_alert_seen(key_name, ts=None):
    """Tandai satu alert sudah terkirim; ``True`` hanya bila key belum ada.

    Deterministik, beda dari pola sembanding-value lama
    (``check_and_update_alert``): value-nya epoch penerbitan (bukan placeholder
    ``"sent"``) supaya pembersih `cap_*` bisa cek umur key dari SQL — dan
    status "sudah terkirim" tidak terbalik oleh perbedaan timestamp antara
    panggilan kedua dan pertama. Pengecekan-penulisan berjalan sekuensial di
    dalam job tunggal, tidak ada penelepon paralel.
    """
    db = await get_db()
    cursor = await db.execute("SELECT 1 FROM config WHERE key = ?", (key_name,))
    existing = await cursor.fetchone()
    if existing:
        return False
    value = int(ts) if ts is not None else int(time.time())
    await db.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key_name, str(value)))
    await db.commit()
    return True

def _parse_last_stamp(value):
    """Value `'1730023200:2'` → `(1730023200, 2)`; tak terbaca → `None`."""
    try:
        ts_text, _, rank_text = str(value).partition(":")
        rank = int(rank_text) if rank_text else 0
        return int(ts_text), rank
    except (ValueError, TypeError):
        return None


async def get_last_nowcast(chat_id, fingerprint):
    """Terakhir nowcast yang dikirim ke chat untuk satu ``provinsi|event``.

    Kembalikan ``(epoch terkirim, peringkat severity)`` atau ``None``.
    Dipakai ``nowcast_alert_job``: peringatan ulang dalam jeda ditekan,
    kecuali tingkatnya mengeskalasi.
    """
    db = await get_db()
    cursor = await db.execute(
        "SELECT value FROM config WHERE key = ?",
        (f"cap_last_{chat_id}_{fingerprint}",),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _parse_last_stamp(row[0])


async def stamp_last_nowcast(chat_id, fingerprint, ts, rank):
    """Catat epoch + tingkat severity terakhir yang dikirim untuk ``provinsi|event``."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        (f"cap_last_{chat_id}_{fingerprint}", f"{int(ts)}:{int(rank)}"),
    )
    await db.commit()


ALERT_KEY_TTL_DAYS = 7


async def cleanup_old_alerts():
    """Prune key alert `cap_*` lebih tua dari ``ALERT_KEY_TTL_DAYS``.

    Dulu job ini menghapus SEMUA key `cap_*` Minggu 00:00 apa pun umurnya:
    item RSS yang masih hidup setelah wipe langsung di-broadcast ulang ke
    pengguna. Value kini diawali epoch (format `<epoch>:<rank>` atau epoch
    polos), jadi umurnya bisa dicek dari SQL dengan CAST. Value legacy
    `'sent'` ber-CAST-0 otomatis terpangkas, sekalian membersihkan format lama.
    """
    cutoff_ts = int(time.time() - ALERT_KEY_TTL_DAYS * 86400)
    db = await get_db()
    await db.execute(
        "DELETE FROM config WHERE key LIKE 'cap_%' AND CAST(value AS INTEGER) < ?",
        (cutoff_ts,),
    )
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


async def cache_weather(adm_code: str, weather_json: dict):
    """Store fresh BMKG weather JSON in cache."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO weather_cache (adm_code, cached_json, cached_at) VALUES (?, ?, ?)",
        (adm_code, json.dumps(weather_json), datetime.now().isoformat())
    )
    await db.commit()


async def get_cached_weather(adm_code: str):
    """Return cached weather JSON if within TTL, else None."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT cached_json, cached_at FROM weather_cache WHERE adm_code = ?",
        (adm_code,)
    )
    row = await cursor.fetchone()
    if row:
        try:
            cached_at = datetime.fromisoformat(row["cached_at"])
            if datetime.now() - cached_at < timedelta(minutes=WEATHER_CACHE_TTL_MIN):
                return json.loads(row["cached_json"]), cached_at.isoformat()
        except (ValueError, json.JSONDecodeError):
            pass
    return None


async def enqueue_failed_send(chat_id: int, message: str, photo_url: str = None):
    """Queue a message that failed to send for later retry."""
    db = await get_db()
    await db.execute(
        "INSERT INTO pending_sends (chat_id, message, photo_url) VALUES (?, ?, ?)",
        (chat_id, message, photo_url)
    )
    await db.commit()


async def retry_pending_sends():
    """Retry failed sends. Caller must handle sending via bot. Returns (successes, failures, rows)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, chat_id, message, photo_url, retry_count FROM pending_sends "
        "ORDER BY created_at ASC LIMIT 50"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return rows


async def delete_pending_send(send_id: int):
    db = await get_db()
    await db.execute("DELETE FROM pending_sends WHERE id = ?", (send_id,))
    await db.commit()


async def increment_retry_count(send_id: int):
    db = await get_db()
    await db.execute(
        "UPDATE pending_sends SET retry_count = retry_count + 1 WHERE id = ?",
        (send_id,)
    )
    await db.commit()


async def cache_weather_image(condition_group: str, image_url: str, photographer: str, cached_at: str):
    """Store an Unsplash image URL by weather condition group."""
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO weather_image_cache (condition_group, image_url, photographer, cached_at) VALUES (?, ?, ?, ?)",
        (condition_group, image_url, photographer, cached_at)
    )
    await db.commit()


async def get_cached_weather_image(condition_group: str):
    """Return cached image row for a condition group, or None."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT image_url, photographer, cached_at FROM weather_image_cache WHERE condition_group = ?",
        (condition_group,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return row
