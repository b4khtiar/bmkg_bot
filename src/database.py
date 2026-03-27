import aiosqlite

DB_PATH = "data/bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Tabel Users: Menyimpan preferensi notifikasi & lokasi
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                is_admin BOOLEAN DEFAULT 0,
                is_whitelisted BOOLEAN DEFAULT 0,
                adm_code TEXT,      -- Kode wilayah BMKG untuk cuaca
                adm_name TEXT,      -- Nama wilayah (User-friendly)
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabel Config: Menyimpan state global bot
        await db.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Inisialisasi default mode jika belum ada
        await db.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bot_mode', 'MAINTENANCE')")
        await db.commit()

# BOT MODE FUNCTIONS
async def get_bot_mode():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM config WHERE key = 'bot_mode'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "MAINTENANCE"

async def set_bot_mode(mode):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE config SET value = ? WHERE key = 'bot_mode'", (mode,))
        await db.commit()

# USER FUNCTIONS
async def add_user(chat_id: int, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (chat_id, username) VALUES (?, ?)", (chat_id, username))
        await db.commit()

async def count_users():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            res = await cursor.fetchone()
            return res[0]

async def is_user_whitelisted(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_whitelisted FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] == 1 if row else False

async def add_to_whitelist(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_whitelisted = 1 WHERE chat_id = ?", (chat_id,))
        await db.commit()

async def update_user_location(chat_id, adm_code, adm_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET adm_code = ?, adm_name = ? WHERE chat_id = ?",
            (adm_code, adm_name, chat_id)
        )
        await db.commit()

async def get_user_info(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            return await cursor.fetchone()

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT chat_id, adm_code FROM users") as cursor:
            return await cursor.fetchall()

async def get_metadata(key):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def update_metadata(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# WEATHER ALERT FUNCTIONS
async def check_and_update_alert(key_name, new_value):
    """
    Mengembalikan True jika value baru berbeda dengan yang lama (perlu kirim notif),
    sekaligus mengupdate database jika berbeda.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM config WHERE key = ?", (key_name,)) as cursor:
            row = await cursor.fetchone()
            old_value = row[0] if row else None
            
            if old_value != str(new_value):
                await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", 
                                 (key_name, str(new_value)))
                await db.commit()
                return True # Ada perubahan
            return False # Data sama, abaikan

async def cleanup_old_metadata():
    async with aiosqlite.connect(DB_PATH) as db:
        # Hapus alert yang sudah lewat dari 24 jam (asumsi sederhana)
        await db.execute("DELETE FROM config WHERE key LIKE 'alert_%'")
        await db.commit()