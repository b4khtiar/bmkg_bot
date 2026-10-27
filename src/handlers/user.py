import functools

from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from database import (
    add_user, get_bot_mode, is_user_whitelisted, update_user_location,
    get_user_info, get_user_prefs, update_user_pref
)
from utils.keyboards import (
    get_province_keyboard, get_regency_keyboard, get_desa_keyboard,
    get_start_keyboard, get_notif_prefs_keyboard,
    get_change_location_keyboard, regency_map,
    get_weather_location_choices,
)
from utils import locations
from services.bmkg_api import (
    fetch_weather_data, parse_weather_current,
    fetch_latest_quake, fetch_nowcast_alerts, summarize_nowcast_rss,
    parse_weather_multi_day, parse_weather_hourly_today
)
from utils.constants import get_province_name
from utils.formatters import format_quake, quake_shakemap_url
from utils.text import esc
from utils.design import CAPTION_LIMIT as _CAPTION_LIMIT  # diimpor dengan nama lama karena tes merujuk U._CAPTION_LIMIT
import os, time, logging

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
logger = logging.getLogger(__name__)

_bot_start_time = time.time()
# `_CAPTION_LIMIT` di atas adalah CAPTION_LIMIT dari utils/design.py — angka
# 1024 tidak lagi diketik ulang di sini; angka panjang caption hanya boleh
# punya satu definisi.


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


#: Perintah yang tetap berguna saat MAINTENANCE: tidak menyentuh API BMKG, dan
#: membiarkan pengguna mengubah pengaturan sangat mungkin karena "kenapa tidak
#: ada notifikasi".
_ALLOWED_DURING_MAINTENANCE = {"start", "bantuan", "ping", "lokasi", "notifikasi"}


def _command_name(message: types.Message) -> str:
    """Nama perintah yang diketik pengguna, tanpa '/' dan tanpa '@botname'."""
    parts = (message.text or "").split()
    if not parts:
        return ""
    return parts[0].lstrip("/").split("@")[0]


def _command_arg(message: types.Message) -> str:
    """Isi argumen perintah: sisa teks setelah kata pertama.

    "/cuaca  Wates,  Kab. Kulon Progo " dan "/cuaca Wates, Kab. Kulon Progo"
    harus sama; spasi internal dirapatkan bersama, dan "/cuaca" telanjang
    menghasilkan string kosong (jalur lokasi tersimpan).
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return " ".join(parts[1].split())


async def check_access(message: types.Message, command: str = None) -> bool:
    """True bila perintah ini boleh dijalankan; kalau tidak, sudah dibalas.

    ``command`` mengesampingkan deteksi dari teks pesan — dipakai oleh handler
    callback, yang pesan sumbernya bukan perintah dan justru akan di-scrape
    jadi keputusan yang kebetulan benar.

    Dulu hanya ``/start`` yang memeriksa mode, jadi saat bot ``MAINTENANCE``
    pengguna masih bisa ``/cuaca`` dan menerima data — pemeliharaan jadi
    tidak berarti apa-apa.

    Kebijakan yang dipakai:
    * ``MAINTENANCE`` — hanya perintah yang butuh data BMKG yang dihentikan.
      ``/start``, ``/bantuan``, ``/ping``, ``/lokasi``, dan ``/notifikasi``
      tetap jalan supaya pengguna tidak terjebak tanpa jalan keluar.
    * ``WHITELIST`` — semua perintah tertutup kecuali ``/start``, yang
      menampilkan penjelasan. Ini soal akses, bukan soal data.

    Admin selalu lolos.
    """
    chat_id = message.chat.id
    if chat_id == ADMIN_ID:
        return True

    mode = await get_bot_mode()
    if mode == "OPEN":
        return True

    if mode == "MAINTENANCE":
        if (command or _command_name(message)) in _ALLOWED_DURING_MAINTENANCE:
            return True
        await message.answer(
            "\u26a0\ufe0f <b>Bot sedang dalam pemeliharaan</b>\n"
            "Perintah ini tidak tersedia sementara ini. "
            "Silakan coba lagi nanti.",
            parse_mode="HTML",
        )
        return False

    if mode == "WHITELIST" and not await is_user_whitelisted(chat_id):
        await message.answer(
            "\U0001f512 <b>Bot dalam Mode Terbatas</b>\n"
            "Maaf, Anda belum terdaftar dalam whitelist.",
            parse_mode="HTML",
        )
        return False

    return True


def requires_access(handler):
    """Bungkus handler agar selalu melewati ``check_access`` lebih dulu."""

    @functools.wraps(handler)
    async def wrapper(message, *args, **kwargs):
        if not await check_access(message):
            return None
        return await handler(message, *args, **kwargs)

    return wrapper


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
        reply_markup=get_regency_keyboard(prov_name)
    )


@router.callback_query(F.data.startswith("kabpage_"))
async def handle_regency_page(callback: types.CallbackQuery):
    """Halaman daftar kabupaten/kota untuk satu provinsi.

    Bentuk callback: ``kabpage_<province>_<page>``. Satu callback alih-alih
    menyimpan pesan terpisah yang harus diingat setiap saat — state tetap
    berupa teks, jadi tombol tetap benar juga setelah restart bot.
    """
    await callback.answer()
    try:
        prov, page = callback.data.split("_", 1)[1].rsplit("_", 1)
        page = int(page)
    except (ValueError, IndexError):
        return await callback.answer("Halaman tidak valid.", show_alert=True)

    if not regency_map(prov):
        return await callback.answer("Provinsi tidak dikenal.", show_alert=True)

    await _safe_edit_text(
        callback,
        f"📍 <b>Pilih Kota/Kabupaten</b>\nWilayah: {esc(prov)}",
        parse_mode="HTML",
        reply_markup=get_regency_keyboard(prov, page)
    )


@router.callback_query(F.data.startswith("kabback_"))
async def handle_regency_back(callback: types.CallbackQuery):
    await callback.answer()
    code = callback.data.split("_", 1)[1]
    prov = get_province_name(code)
    if not prov:
        return await callback.answer("Wilayah tidak dikenal.", show_alert=True)

    await _safe_edit_text(
        callback,
        f"📍 <b>Pilih Kota/Kabupaten</b>\nWilayah: {esc(prov)}",
        parse_mode="HTML",
        reply_markup=get_regency_keyboard(prov)
    )


@router.callback_query(F.data.startswith("kab_"))
async def handle_desas(callback: types.CallbackQuery):
    """Pilih desa: kabupaten/kota diturunkan dari lima digit pertama."""
    await callback.answer()
    code = callback.data.split("_", 1)[1]
    prov = get_province_name(code)
    if not prov or not regency_map(prov).get(code):
        return await callback.answer("Wilayah tidak dikenal.", show_alert=True)

    reg = regency_map(prov)[code]
    await _safe_edit_text(
        callback,
        f"📍 <b>Pilih Desa/Kelurahan</b>\nWilayah: {esc(prov)} · {esc(reg)}",
        parse_mode="HTML",
        reply_markup=get_desa_keyboard(code)
    )


@router.callback_query(F.data.startswith("desapage_"))
async def handle_desa_page(callback: types.CallbackQuery):
    """Halaman daftar desa: ``desapage_<regency_code>_<page>``."""
    await callback.answer()
    try:
        code, page = callback.data.split("_", 1)[1].rsplit("_", 1)
        page = int(page)
    except (ValueError, IndexError):
        return await callback.answer("Halaman tidak valid.", show_alert=True)

    prov = get_province_name(code)
    reg = regency_map(prov).get(code) if prov else None
    if reg is None:
        return await callback.answer("Wilayah tidak dikenal.", show_alert=True)

    await _safe_edit_text(
        callback,
        f"📍 <b>Pilih Desa/Kelurahan</b>\nWilayah: {esc(prov)} · {esc(reg)}",
        parse_mode="HTML",
        reply_markup=get_desa_keyboard(code, page)
    )


@router.callback_query(F.data.startswith("setloc_"))
async def handle_confirm_location(callback: types.CallbackQuery):
    # Dua bentuk: ``setloc_<kode>`` (keyboard baru, kode-saja supaya selalu
    # muat 64 byte) dan ``setloc_<kode>_<nama>`` (basi sebelum deploy ini).
    # Label canonical selalu diambil kembali dari pustaka, bukan dari nama
    # yang tertanam — satu sumber kebenaran, dan kode yang tidak dikenal
    # ditolak.
    parts = callback.data.split("_", 2)
    adm_code = parts[1] if len(parts) > 1 else ""
    adm_name = locations.label_for(adm_code)
    if adm_name is None:
        return await callback.answer("Lokasi tidak dikenal.", show_alert=True)

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
@requires_access
async def cmd_current_weather(message: types.Message):
    arg = _command_arg(message)
    if arg:
        return await _cuaca_for_query(message, arg)

    user_data = await _require_location(message)
    if not user_data:
        return

    await _send_current_weather(message, user_data['adm_code'])


async def _send_current_weather(message: types.Message, adm_code: str) -> None:
    """Ambil dan kirim cuaca saat ini untuk satu kode adm4.

    Jalur yang sama untuk lokasi tersimpan pengguna maupun lokasi yang
    ditanyakan lewat argumen / tombol kandidat — supaya guard caption, foto,
    dan fallback pemberitahuan tidak berjalan berbeda di antara keduanya.
    """
    raw_data = await fetch_weather_data(adm_code)
    if not raw_data:
        return await message.answer(
            "⚠️ Gagal mengambil data cuaca. BMKG sedang tidak dapat dihubungi, "
            "silakan coba lagi nanti."
        )

    result = await parse_weather_current(raw_data)
    await _reply_weather(message, result.get("text"), result.get("photo_url"))


async def _cuaca_for_query(message: types.Message, query: str) -> None:
    """Cuaca saat ini untuk lokasi yang diketik, tanpa mengubah lokasi tersimpan.

    Cakupan data wilayah baru DI Yogyakarta, jadi ketikan di luar pustaka tidak
    ditebak-nebak melainkan ditolak dengan daftar contoh yang valid — sama
    seperti pemilih lokasi via /lokasi.
    """
    resolved = locations.resolve_location(query)

    if resolved["status"] == "none":
        examples = ", ".join(
            f"<code>{esc(label)}</code>" for label in locations.example_locations()
        )
        await message.answer(
            "🗺️ <b>Lokasi tidak tersedia</b>\n\n"
            f"Cakupan saya belum mencakup \"{esc(query)}\". "
            f"Saat ini baru <b>{esc(locations.coverage_summary())}</b> "
            f"yang didukung, misalnya: {examples}.\n\n"
            "Untuk memilih lokasi dari daftar dan menyimpannya, gunakan /lokasi.",
            parse_mode="HTML",
        )
        return

    if resolved["status"] == "ambiguous":
        names = "\n".join(f"• {esc(m['label'])}" for m in resolved["matches"])
        await message.answer(
            "🏘️ <b>Beberapa lokasi cocok</b>\n\n"
            f"{names}\n\n"
            "Pilih salah satu di bawah, atau ketik nama yang lebih spesifik.",
            parse_mode="HTML",
            reply_markup=get_weather_location_choices(resolved["matches"]),
        )
        return

    await _send_current_weather(message, resolved["matches"][0]["adm4"])


@router.callback_query(F.data.startswith("wxloc_"))
async def handle_weather_location_choice(callback: types.CallbackQuery):
    """Kirim cuaca untuk lokasi yang dipilih dari daftar kandidat.

    Akses dicek dengan perintah eksplisit ``cuaca``: mengandalkan teks pesan
    sumber berarti meng-scrape emoji/HTML dan keputusan mode hanya kebetulan
    benar. Kode adm4 dari callback_data divalidasi ke pustaka — kode asing
    tidak boleh diteruskan ke API.
    """
    if not callback.message:
        return await callback.answer("Pesan tidak tersedia lagi.")

    if not await check_access(callback.message, command="cuaca"):
        return await callback.answer()

    adm4 = callback.data.split("_", 1)[1]
    label = locations.label_for(adm4)
    if label is None:
        return await callback.answer("Lokasi tidak dikenal.", show_alert=True)

    await callback.answer("Mengambil cuaca…")
    await _send_current_weather(callback.message, adm4)

    # Pilihannya sudah terjawab; ganti pesan kandidat dengan konfirmasi
    # satu baris (edit sekaligus menghapus keyboard).
    try:
        await callback.message.edit_text(
            f"✅ Cuaca {esc(label)} ditampilkan di bawah.",
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        logger.warning(
            "Pesan kandidat lokasi gagal dikonfirmasi", exc_info=True,
            extra={"chat_id": callback.message.chat.id}
        )


@router.message(Command("prakiraan"))
@requires_access
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
@requires_access
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
@requires_access
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
@requires_access
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

@router.callback_query(F.data.startswith("provpage_"))
async def handle_province_page(callback: types.CallbackQuery):
    """Pindah halaman daftar provinsi."""
    await callback.answer()
    try:
        page = int(callback.data.split("_", 1)[1])
    except ValueError:
        # Callback basi (dari versi bot sebelumnya) tidak boleh membuat
        # pengguna terjebak di spinner.
        page = 0

    await _safe_edit_text(
        callback,
        "📍 <b>Pilih Provinsi</b>\n\nSilakan pilih provinsi tempat Anda berada.",
        parse_mode="HTML",
        reply_markup=get_province_keyboard(page)
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
        "🌤️ <code>/cuaca [lokasi]</code> — cuaca saat ini; tanpa argumen memakai "
        "lokasi yang tersimpan\n"
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

    # One health source, shared with /healthz and /metrics. The old version
    # hardcoded "Semua sistem berjalan normal" and never checked anything, so
    # it was most confidently wrong exactly when something was broken. It also
    # ran its own DB query, duplicating the health server's.
    from health_server import get_health_async

    try:
        # Async variant is mandatory here: the sync one calls asyncio.run(),
        # which raises inside the bot's own event loop.
        health = await get_health_async()
    except Exception as e:
        # Health checking must never be the reason /ping fails.
        logger.warning(f"Gagal membaca status kesehatan: {e}")
        health = {"status": "unknown", "db": False, "bmkg_reachable": False}

    status_line = (
        "✅ Semua sistem normal."
        if health["status"] == "ok"
        else "⚠️ Ada gangguan: "
        + ", ".join(
            part
            for part, bad in (
                ("database tidak dapat diakses", not health["db"]),
                ("BMKG tidak dapat dihubungi", not health["bmkg_reachable"]),
            )
            if bad
        )
        + "."
    )

    msg = (
        "🏓 <b>PONG! Bot aktif</b>\n\n"
        f"⏱️ <b>Uptime</b>  {uptime_str}\n"
        f"📍 <b>Lokasi</b>  {esc(loc) if loc else 'Belum diatur'}\n\n"
        f"<i>{status_line}</i>"
    )
    await message.answer(msg, parse_mode="HTML")
