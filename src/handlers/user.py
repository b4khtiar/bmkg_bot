from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from database import (
    add_user, get_bot_mode, is_user_whitelisted, update_user_location,
    get_user_info, get_user_prefs, update_user_pref, get_db
)
from utils.keyboards import (
    get_province_keyboard, get_city_keyboard, get_start_keyboard,
    get_notif_prefs_keyboard, get_change_location_keyboard,
)
from services.bmkg_api import (
    fetch_weather_data, parse_weather_current,
    fetch_latest_quake, fetch_nowcast_alerts, summarize_nowcast_rss,
    parse_weather_multi_day, parse_weather_hourly_today
)
from utils.constants import get_province_name
from utils.formatters import format_quake, quake_shakemap_url
from utils.text import esc
import os, time, logging

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
logger = logging.getLogger(__name__)

_bot_start_time = time.time()

# Telegram rejects photo captions over 1024 chars. Going over would raise
# inside answer_photo and land in the fallback path, masking the real cause.
_CAPTION_LIMIT = 1024


async def _reply_weather(message: types.Message, text: str, photo_url):
    """Send weather text with its themed photo when one is available.

    The photo is only attempted when the caption fits Telegram's 1024-char cap;
    otherwise the text goes alone, since a rejected photo means no delivery at
    all. See utils/design.py::compose for the reasoning.
    """
    if not photo_url:
        return await message.answer(text, parse_mode="HTML")

    if len(text) > _CAPTION_LIMIT:
        logger.info(
            f"Foto dilewati: caption {len(text)} karakter melebihi {_CAPTION_LIMIT}",
            extra={"chat_id": message.chat.id}
        )
        return await message.answer(text, parse_mode="HTML")

    try:
        await message.answer_photo(photo=photo_url, caption=text, parse_mode="HTML")
    except TelegramBadRequest:
        # Telegram rejected the request, so nothing was delivered — safe to
        # retry as text. A broad except here used to re-send text after
        # network errors too, which could duplicate the whole message for the
        # user if the photo had in fact been accepted.
        logger.warning(
            "Foto cuaca ditolak Telegram, kirim teks saja",
            exc_info=True, extra={"chat_id": message.chat.id}
        )
        await message.answer(text, parse_mode="HTML")
    except TelegramAPIError:
        # Transport-level failure: the message may or may not have landed.
        # Re-sending risks a duplicate, so let the user retry themselves.
        logger.error(
            "Gagal kirim foto cuaca akibat masalah jaringan",
            exc_info=True, extra={"chat_id": message.chat.id}
        )
        await message.answer(
            "⚠️ Pesan cuaca gagal dikirim. Silakan coba lagi beberapa saat lagi.",
            parse_mode="HTML",
        )


async def _safe_edit_text(callback: types.CallbackQuery, text: str, **kwargs):
    """``edit_text`` yang tidak melempar saat pesan tidak berubah.

    Menekan tombol yang sama dua kali (pilih provinsi yang sama, atau toggle
    notifikasi yang mengembalikan state awal) membuat Telegram menjawab
    "message is not modified". Tanpa penjaga ini, handler melempar exception
    dan pengguna melihat spinner yang tidak pernah selesai.
    """
    try:
        await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    mode = await get_bot_mode()

    if mode == "MAINTENANCE" and chat_id != ADMIN_ID:
        return await message.answer(
            "⚠️ <b>Bot sedang dalam pemeliharaan</b>\nSilakan coba lagi nanti.",
            parse_mode="HTML",
        )

    if mode == "WHITELIST" and chat_id != ADMIN_ID:
        whitelisted = await is_user_whitelisted(chat_id)
        if not whitelisted:
            return await message.answer(
                "🔒 <b>Bot dalam Mode Terbatas</b>\nMaaf, Anda belum terdaftar dalam whitelist.",
                parse_mode="HTML",
            )

    username = esc(message.from_user.username or "User")
    await add_user(chat_id, username)

    # Users who already configured a location get their current location back,
    # so re-running /start actually answers "where am I set to?" instead of
    # replaying the first-run message verbatim.
    existing = await get_user_info(chat_id)
    if existing and existing['adm_name']:
        welcome_text = (
            f"Halo {username}! 👋\n\n"
            "Saya adalah bot notifikasi BMKG.\n\n"
            f"📍 <b>Lokasi saat ini:</b> {esc(existing['adm_name'])}\n\n"
            "Gunakan tombol di bawah untuk mengubahnya."
        )
    else:
        welcome_text = (
            f"Halo {username}! 👋\n\n"
            "Saya adalah bot notifikasi BMKG.\n\n"
            "📍 <b>Langkah berikutnya:</b>\n"
            "Agar notifikasi cuaca yang Anda terima akurat, "
            "silakan tekan tombol di bawah untuk mengatur lokasi."
        )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_start_keyboard())

@router.callback_query(F.data == "setup_location")
async def handle_provinces(callback: types.CallbackQuery):
    await callback.answer()
    await _safe_edit_text(
        callback,
        "📍 <b>Pilih Provinsi</b>\n\nSilakan pilih provinsi tempat Anda berada.",
        parse_mode="HTML",
        reply_markup=get_province_keyboard()
    )


@router.callback_query(F.data.startswith("prov_"))
async def handle_cities(callback: types.CallbackQuery):
    await callback.answer()
    prov_name = callback.data.split("_", 1)[1]
    await _safe_edit_text(
        callback,
        f"📍 <b>Pilih Kota/Kabupaten</b>\nWilayah: {esc(prov_name)}",
        parse_mode="HTML",
        reply_markup=get_city_keyboard(prov_name)
    )


@router.callback_query(F.data.startswith("setloc_"))
async def handle_confirm_location(callback: types.CallbackQuery):
    try:
        _, adm_code, adm_name = callback.data.split("_", 2)
    except ValueError:
        return await callback.answer("Data lokasi tidak valid.", show_alert=True)

    await update_user_location(callback.from_user.id, adm_code, adm_name)
    await callback.answer(f"✅ Lokasi diatur ke {adm_name}")
    # Keeps a button on screen: previously the keyboard was removed here, so
    # the user was stranded with no way to change their mind without retyping
    # /start.
    await _safe_edit_text(
        callback,
        f"✅ <b>Lokasi berhasil diatur</b>\n📍 {esc(adm_name)}\n\n"
        "Anda akan menerima notifikasi cuaca untuk wilayah ini.",
        parse_mode="HTML",
        reply_markup=get_change_location_keyboard()
    )

async def _require_location(message: types.Message):
    """Kembalikan data user bila lokasi sudah diatur, atau balas dan hentikan.

    Ships a button instead of only naming a command: the point of the inline
    keyboard is that the next step is one tap away, and three separate handlers
    were each printing the same bare instruction.
    """
    user_data = await get_user_info(message.chat.id)
    if user_data and user_data['adm_code']:
        return user_data

    await message.answer(
        "📍 Lokasi Anda belum diatur.\n"
        "Saya perlu lokasi untuk menampilkan cuaca yang tepat.",
        parse_mode="HTML",
        reply_markup=get_start_keyboard()
    )
    return None


@router.message(Command("cuaca"))
async def cmd_current_weather(message: types.Message):
    user_data = await _require_location(message)
    if not user_data:
        return

    raw_data = await fetch_weather_data(user_data['adm_code'])
    if not raw_data:
        return await message.answer(
            "⚠️ Gagal mengambil data cuaca. BMKG sedang tidak dapat dihubungi, "
            "silakan coba lagi nanti."
        )

    result = await parse_weather_current(raw_data)
    await _reply_weather(message, result.get("text"), result.get("photo_url"))


@router.message(Command("prakiraan"))
async def cmd_extended_forecast(message: types.Message):
    user_data = await _require_location(message)
    if not user_data:
        return

    raw_data = await fetch_weather_data(user_data['adm_code'])
    if not raw_data:
        return await message.answer(
            "⚠️ Gagal mengambil data prakiraan cuaca. BMKG sedang tidak dapat "
            "dihubungi, silakan coba lagi nanti."
        )

    result = await parse_weather_multi_day(raw_data, days=3)
    await _reply_weather(message, result.get("text"), result.get("photo_url"))

@router.message(Command("per_jam", "cuaca_hari_ini"))
async def cmd_hourly_today(message: types.Message):
    """Cuaca per jam untuk hari ini.

    Renamed from /cuaca_hari_ini, which collided with /cuaca: users could not
    tell which one gave the current reading and which gave the hourly table.
    """
    await _answer_with_legacy_hint(message, "/per_jam")
    user_data = await _require_location(message)
    if not user_data:
        return

    raw_data = await fetch_weather_data(user_data['adm_code'])
    if not raw_data:
        return await message.answer(
            "⚠️ Gagal mengambil data cuaca. BMKG sedang tidak dapat dihubungi, "
            "silakan coba lagi nanti."
        )

    result = await parse_weather_hourly_today(raw_data)
    await _reply_weather(message, result.get("text"), result.get("photo_url"))

@router.message(Command("gempa"))
async def cmd_earthquake(message: types.Message):
    raw_data = await fetch_latest_quake()
    if not raw_data:
        return await message.answer("Gagal mengambil data gempa. Silakan coba lagi nanti.")

    # "📍" is reserved for location throughout the bot, so the user's own
    # province is marked with 🏠 to stop the two colliding.
    jarak_info = ""
    user_data = await get_user_info(message.chat.id)
    if user_data and user_data['adm_code']:
        prov_name = get_province_name(user_data['adm_code'])
        if prov_name:
            if prov_name.lower() in str(raw_data.get('Wilayah', '')).lower():
                jarak_info = "🏠 <b>Wilayah Anda terdampak</b>"
            else:
                jarak_info = f"🏠 <b>Provinsi Anda</b>  {prov_name}"

    # Same formatter the broadcast uses, so a typed command and a push look
    # identical instead of being two unrelated designs.
    msg = format_quake(raw_data, distance_info=jarak_info)
    img_url = quake_shakemap_url(raw_data)

    await _reply_weather(message, msg, img_url)

@router.message(Command("nowcast"))
async def cmd_nowcast(message: types.Message):
    user_data = await _require_location(message)
    if not user_data:
        return

    raw_data = await fetch_nowcast_alerts()
    if not raw_data:
        return await message.answer(
            "⚠️ Gagal mengambil data peringatan dini cuaca. BMKG sedang tidak "
            "dapat dihubungi, silakan coba lagi nanti."
        )

    province_filter = get_province_name(user_data['adm_code'])
    nowcast_summary = summarize_nowcast_rss(raw_data, province_filter=province_filter)
    await message.answer(nowcast_summary, parse_mode="HTML")

_NOTIF_PREF_TEXT = (
    "🔔 <b>Pengaturan Notifikasi</b>\n\n"
    "Pilih notifikasi yang ingin Anda terima:"
)


@router.message(Command("notifikasi", "atur_notif"))
async def cmd_notif_preferences(message: types.Message):
    """Notifikasi.

    ``atur_notif`` kept as an accepted alias so existing muscle memory keeps
    working; Telegram's command menu only advertises the new name. The nudge is
    sent once so the rename is discoverable rather than silent.
    """
    await _answer_with_legacy_hint(message, "/notifikasi")
    prefs = await get_user_prefs(message.chat.id)
    await message.answer(
        _NOTIF_PREF_TEXT,
        parse_mode="HTML",
        reply_markup=get_notif_prefs_keyboard(prefs)
    )


async def _answer_with_legacy_hint(message: types.Message, new_command: str):
    """Beri tahu sekali bila perintah lama masih dipakai.

    Menerima nama lama tanpa penjelasan apa pun membuat pengguna tidak
    pernah tahu nama barunya, dan menu perintah Telegram hanya mengiklankan
    nama baru.
    Jadi tanpa petunjuk ini, sebagian pengguna akan kehilangan akses tanpa
    pernah diberi tahu. Alias diam-diam lebih buruk daripada satu baris
    penjelasan.
    """
    parts = (message.text or "").split()
    if not parts:
        return
    typed = parts[0].lstrip("/").split("@")[0]
    if typed == new_command.lstrip("/"):
        return
    await message.answer(
        f"ℹ️ Perintah ini kini <code>{new_command}</code>.",
        parse_mode="HTML",
    )


@router.message(Command("lokasi"))
async def cmd_location(message: types.Message):
    """Atur atau ubah lokasi tanpa harus lewat /start."""
    await message.answer(
        "📍 <b>Pilih Provinsi</b>\n\nSilakan pilih provinsi tempat Anda berada.",
        parse_mode="HTML",
        reply_markup=get_province_keyboard()
    )


@router.callback_query(F.data.startswith("notif_"))
async def handle_notif_toggle(callback: types.CallbackQuery):
    pref_name = callback.data.split("_", 1)[1]
    valid_prefs = {"notify_quake", "notify_weather", "notify_nowcast"}
    if pref_name not in valid_prefs:
        return await callback.answer("Pengaturan tidak dikenal.")

    current_prefs = await get_user_prefs(callback.from_user.id)
    new_value = not current_prefs.get(pref_name, True)
    await update_user_pref(callback.from_user.id, pref_name, new_value)

    updated_prefs = await get_user_prefs(callback.from_user.id)
    await _safe_edit_text(
        callback,
        _NOTIF_PREF_TEXT,
        parse_mode="HTML",
        reply_markup=get_notif_prefs_keyboard(updated_prefs)
    )
    await callback.answer(f"{'✅' if new_value else '❌'} Notifikasi {'diaktifkan' if new_value else 'dinonaktifkan'}")


@router.message(Command("bantuan", "help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>🤖 Perintah yang tersedia</b>\n\n"
        "🌤️ <code>/cuaca</code> — cuaca saat ini di lokasi Anda\n"
        "⏰ <code>/per_jam</code> — cuaca per jam hari ini\n"
        "📅 <code>/prakiraan</code> — prakiraan 3 hari ke depan\n"
        "🚨 <code>/gempa</code> — gempa bumi terkini\n"
        "🌧️ <code>/nowcast</code> — peringatan dini cuaca\n"
        "📍 <code>/lokasi</code> — atur atau ubah lokasi\n"
        "🔔 <code>/notifikasi</code> — atur notifikasi yang diterima\n"
        "🏓 <code>/ping</code> — cek status bot\n\n"
        "Semua data berasal dari BMKG.",
        parse_mode="HTML",
    )

@router.message(Command("ping"))
async def cmd_ping(message: types.Message):
    uptime_sec = int(time.time() - _bot_start_time)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    # "d" for seconds reads as "days" in every other language this bot is used
    # in. Spell it out.
    uptime_str = f"{hours}j {minutes}m {seconds}dtk"

    user_data = await get_user_info(message.chat.id)
    loc = user_data['adm_name'] if user_data and user_data['adm_name'] else None

    # The old version hardcoded "Semua sistem berjalan normal" and never
    # checked anything, so it was most confidently wrong exactly when
    # something was broken. The only thing /ping can check cheaply is the
    # database it talks to.
    db_ok = False
    try:
        _db = await get_db()
        await _db.execute("SELECT 1")
        db_ok = True
    except Exception as e:
        logger.warning(f"Gagal memeriksa database: {e}")

    status_line = (
        "✅ Semua sistem normal." if db_ok else "⚠️ Database tidak dapat diakses."
    )

    msg = (
        "🏓 <b>PONG! Bot aktif</b>\n\n"
        f"⏱️ <b>Uptime</b>  {uptime_str}\n"
        f"📍 <b>Lokasi</b>  {esc(loc) if loc else 'Belum diatur'}\n\n"
        f"<i>{status_line}</i>"
    )
    await message.answer(msg, parse_mode="HTML")
