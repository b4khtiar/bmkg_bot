from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from database import (
    add_user, get_bot_mode, is_user_whitelisted, update_user_location,
    get_user_info, get_user_prefs, update_user_pref
)
from utils.keyboards import get_province_keyboard, get_city_keyboard, get_start_keyboard, get_notif_prefs_keyboard
from services.bmkg_api import (
    fetch_weather_data, parse_weather_current, parse_weather_daily_brief,
    fetch_latest_quake, fetch_nowcast_alerts, summarize_nowcast_rss,
    parse_weather_multi_day
)
from utils.constants import get_province_name
import os, time, logging

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
logger = logging.getLogger(__name__)

_bot_start_time = time.time()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    mode = await get_bot_mode()

    if mode == "MAINTENANCE" and chat_id != ADMIN_ID:
        return await message.answer("⚠️ *Bot sedang dalam pemeliharaan.*\nSilakan coba lagi nanti.", parse_mode="Markdown")

    if mode == "WHITELIST" and chat_id != ADMIN_ID:
        whitelisted = await is_user_whitelisted(chat_id)
        if not whitelisted:
            return await message.answer("🔒 *Bot dalam Mode Terbatas.*\nMaaf, Anda belum terdaftar dalam whitelist.", parse_mode="Markdown")

    username = message.from_user.username or "User"
    await add_user(chat_id, username)

    welcome_text = (
        f"Halo {username}! 👋\n\n"
        "Saya adalah bot notifikasi BMKG.\n\n"
        "📍 *Langkah Berikutnya:*\n"
        "Agar saya bisa mengirimkan notifikasi cuaca yang akurat, "
        "silakan tekan tombol di bawah untuk *Mengatur Lokasi* Anda."
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_start_keyboard())

@router.callback_query(F.data == "setup_location")
async def handle_provinces(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Pilih Provinsi:",
        reply_markup=get_province_keyboard()
    )

@router.callback_query(F.data.startswith("prov_"))
async def handle_cities(callback: types.CallbackQuery):
    await callback.answer()
    prov_name = callback.data.split("_", 1)[1]
    await callback.message.edit_text(
        f"Pilih Kota/Kabupaten di {prov_name}:",
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
    await callback.message.edit_text(
        f"✅ Lokasi diatur ke: *{adm_name}*\nAnda akan menerima notifikasi otomatis.",
        parse_mode="Markdown"
    )

@router.message(Command("cuaca"))
async def cmd_current_weather(message: types.Message):
    user_data = await get_user_info(message.chat.id)
    if not user_data or not user_data['adm_code']:
        return await message.answer("Silakan atur lokasi dulu dengan /start")

    raw_data = await fetch_weather_data(user_data['adm_code'])
    if not raw_data:
        return await message.answer("Gagal mengambil data cuaca. Silakan coba lagi nanti.")

    msg = parse_weather_current(raw_data)
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("prakiraan"))
async def cmd_extended_forecast(message: types.Message):
    user_data = await get_user_info(message.chat.id)
    if not user_data or not user_data['adm_code']:
        return await message.answer("Silakan atur lokasi dulu dengan /start")

    raw_data = await fetch_weather_data(user_data['adm_code'])
    if not raw_data:
        return await message.answer("Gagal mengambil data prakiraan cuaca. Silakan coba lagi nanti.")

    msg = parse_weather_multi_day(raw_data, days=3)
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("gempa"))
async def cmd_earthquake(message: types.Message):
    raw_data = await fetch_latest_quake()
    if not raw_data:
        return await message.answer("Gagal mengambil data gempa. Silakan coba lagi nanti.")

    wilayah = raw_data['Wilayah'].replace("Pusat gempa berada di ", "")
    posisi = wilayah.split(" ")[0]
    lokasi_singkat = " ".join(wilayah.split(" ")[1:])

    user_data = await get_user_info(message.chat.id)
    jarak_info = ""
    if user_data and user_data['adm_code']:
        try:
            prov_name = get_province_name(user_data['adm_code'])
            if prov_name and prov_name.lower() in raw_data['Wilayah'].lower():
                jarak_info = "\n📍 <b>Lokasi Anda:</b> Dalam wilayah yang sama."
            elif prov_name:
                jarak_info = f"\n📍 <b>Provinsi Anda:</b> {prov_name}"
        except Exception:
            pass

    msg = (
        f"<b>⚠️ GEMPA BUMI TERKINI</b>\n\n"
        f"🗓️ {raw_data['Tanggal']} - {raw_data['Jam']}\n"
        f"📈 Magnitudo: <code>{raw_data['Magnitude']}</code>\n"
        f"📉 Kedalaman: <code>{raw_data['Kedalaman']}</code> ({posisi})\n"
        f"📍 Wilayah: <code>{lokasi_singkat}</code>\n"
        f"🏘️ Dirasakan: {raw_data['Dirasakan']}\n"
        f"📌 Potensi: <code>{raw_data['Potensi']}</code>"
        f"{jarak_info}"
    )
    img_url = f"https://static.bmkg.go.id/{raw_data['Shakemap']}"

    try:
        await message.answer_photo(photo=img_url, caption=msg, parse_mode="HTML")
    except Exception:
        await message.answer(msg, parse_mode="HTML")

@router.message(Command("nowcast"))
async def cmd_nowcast(message: types.Message):
    raw_data = await fetch_nowcast_alerts()
    if not raw_data:
        return await message.answer("Gagal mengambil data nowcast. Silakan coba lagi nanti.")

    user_data = await get_user_info(message.chat.id)
    province_filter = None
    if user_data and user_data['adm_code']:
        province_filter = get_province_name(user_data['adm_code'])

    nowcast_summary = summarize_nowcast_rss(raw_data, province_filter=province_filter)
    await message.answer(nowcast_summary, parse_mode="HTML")

@router.message(Command("atur_notif"))
async def cmd_notif_preferences(message: types.Message):
    prefs = await get_user_prefs(message.chat.id)
    await message.answer(
        "🔔 <b>Pengaturan Notifikasi</b>\n\n"
        "Pilih jenis notifikasi yang ingin kamu terima:",
        parse_mode="HTML",
        reply_markup=get_notif_prefs_keyboard(prefs)
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
    await callback.message.edit_text(
        "🔔 <b>Pengaturan Notifikasi</b>\n\n"
        "Pilih jenis notifikasi yang ingin kamu terima:",
        parse_mode="HTML",
        reply_markup=get_notif_prefs_keyboard(updated_prefs)
    )
    await callback.answer(f"{'✅' if new_value else '❌'} Notifikasi {'diaktifkan' if new_value else 'dinonaktifkan'}")

@router.message(Command("ping"))
async def cmd_ping(message: types.Message):
    uptime_sec = int(time.time() - _bot_start_time)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}j {minutes}m {seconds}d"

    mode = await get_bot_mode()

    user_data = await get_user_info(message.chat.id)
    loc = user_data['adm_name'] if user_data and user_data['adm_name'] else "Belum diatur"

    msg = (
        "🏓 <b>PONG! Bot Aktif ✅</b>\n\n"
        f"⏱️ Uptime: <code>{uptime_str}</code>\n"
        f"🤖 Mode: <code>{mode}</code>\n"
        f"📍 Lokasi: <code>{loc}</code>\n\n"
        f"<i>Status: ✅ Semua sistem berjalan normal</i>"
    )
    await message.answer(msg, parse_mode="HTML")
