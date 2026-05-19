from aiogram import Router, types, F
from aiogram.filters import CommandStart, Command
from database import add_user, get_bot_mode, is_user_whitelisted, update_user_location, get_user_info
from utils.keyboards import get_province_keyboard, get_city_keyboard, get_start_keyboard
from services.bmkg_api import fetch_weather_data, parse_weather_data, fetch_latest_quake, fetch_nowcast_alerts, summarize_nowcast_rss
import os

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    chat_id = message.chat.id
    mode = await get_bot_mode()

    # 1. Cek Mode Maintenance
    if mode == "MAINTENANCE" and chat_id != ADMIN_ID:
        return await message.answer("⚠️ *Bot sedang dalam pemeliharaan.*\nSilakan coba lagi nanti.", parse_mode="Markdown")

    # 2. Cek Mode Whitelist
    if mode == "WHITELIST" and chat_id != ADMIN_ID:
        whitelisted = await is_user_whitelisted(chat_id)
        if not whitelisted:
            return await message.answer("🔒 *Bot dalam Mode Terbatas.*\nMaaf, Anda belum terdaftar dalam whitelist.", parse_mode="Markdown")

    # 3. Registrasi User
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
    await callback.message.edit_text(
        "Pilih Provinsi:",
        reply_markup=get_province_keyboard()
    )

@router.callback_query(F.data.startswith("prov_"))
async def handle_cities(callback: types.CallbackQuery):
    prov_name = callback.data.split("_")[1]
    await callback.message.edit_text(
        f"Pilih Kota/Kabupaten di {prov_name}:",
        reply_markup=get_city_keyboard(prov_name)
    )

@router.callback_query(F.data.startswith("setloc_"))
async def handle_confirm_location(callback: types.CallbackQuery):
    _, adm_code, adm_name = callback.data.split("_")
    await update_user_location(callback.from_user.id, adm_code, adm_name)
    await callback.message.edit_text(
        f"✅ Lokasi diatur ke: *{adm_name}*\nAnda akan menerima notifikasi otomatis.",
        parse_mode="Markdown"
    )

@router.message(Command("cuaca"))
async def cmd_current_weather(message: types.Message):
    # Ambil adm_code user dari DB
    user_data = await get_user_info(message.chat.id)
    if not user_data or not user_data['adm_code']:
        return await message.answer("Silakan atur lokasi dulu dengan /start")

    raw_data = await fetch_weather_data(user_data['adm_code'])
    # periksa apakah data ada
    if not raw_data:
        return await message.answer("Gagal mengambil data cuaca. Silakan coba lagi nanti.")
    
    msg = parse_weather_data(raw_data, "Saat Ini")
    await message.answer(msg, parse_mode="HTML")

@router.message(Command("gempa"))
async def cmd_earthquake(message: types.Message):
    # Ambil data gempa terkini dari API
    raw_data = await fetch_latest_quake()
    
    # periksa apakah data ada
    if not raw_data:
        return await message.answer("Gagal mengambil data gempa. Silakan coba lagi nanti.")
    msg = (f"<b>⚠️ GEMPA BUMI TERKINI</b>\n\n"
           f"🗓️ {raw_data['Tanggal']} - {raw_data['Jam']}\n"
           f"📈 Magnitudo: <code>{raw_data['Magnitude']}</code>\n"
           f"📉 Kedalaman: <code>{raw_data['Kedalaman']}</code>\n"
           f"📍 Wilayah: <code>{raw_data['Wilayah']}</code>\n"
           f"📌 Potensi: <code>{raw_data['Potensi']}</code>")
    img_url = f"https://static.bmkg.go.id/{raw_data['Shakemap']}"

    await message.answer_photo(photo=img_url, caption=msg, parse_mode="HTML")

# command nowcast
@router.message(Command("nowcast"))
async def cmd_nowcast(message: types.Message):
    # Ambil data nowcast terkini dari API
    raw_data = await fetch_nowcast_alerts()
    
    # periksa apakah data ada
    if not raw_data:
        return await message.answer("Gagal mengambil data nowcast. Silakan coba lagi nanti.")
    
    # parse nowcast
    nowcast_summary = summarize_nowcast_rss(raw_data)
    
    # kirim pesan
    await message.answer(nowcast_summary, parse_mode="HTML")