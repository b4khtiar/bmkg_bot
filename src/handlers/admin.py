import os
from aiogram import Router, types, F
from aiogram.filters import Command
from database import set_bot_mode, get_bot_mode, add_to_whitelist, count_users
from utils.keyboards import get_admin_panel_keyboard

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID") or 0)

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    """Membuka Control Panel Admin"""
    if message.from_user.id != ADMIN_ID:
        return # Abaikan jika bukan admin

    print(f"Admin ID: {ADMIN_ID} membuka panel admin.")
    current_mode = await get_bot_mode()
    user_count = await count_users()
    text = (
        "<b>🛠 CONTROL PANEL ADMIN</b>\n\n"
        f"👥 Total User: {user_count}\n"
        f"🤖 Mode: {current_mode}\n"
        "Silakan pilih mode di bawah untuk mengubah akses pengguna:"
    )
    
    await message.answer(text, reply_markup=get_admin_panel_keyboard(current_mode), parse_mode="HTML")

@router.callback_query(F.data.startswith("setmode_"))
async def handle_set_mode(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Akses ditolak!", show_alert=True)

    new_mode = callback.data.split("_")[1]
    current_mode = await get_bot_mode()

    if new_mode == current_mode:
        return await callback.answer(f"Bot sudah dalam mode {new_mode}")

    # Update di Database
    await set_bot_mode(new_mode)
    
    # Update tampilan pesan admin
    text = (
        "<b>🛠 CONTROL PANEL ADMIN</b>\n\n"
        f"Status Bot Diubah ke: <b>{new_mode}</b>\n"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_panel_keyboard(new_mode),
        parse_mode="HTML"
    )
    
    await callback.answer(f"✅ Mode diubah ke {new_mode}")

@router.callback_query(F.data == "close_panel")
async def handle_close_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Akses ditolak!", show_alert=True)
    
    await callback.message.delete()

@router.message(Command("whitelist"))
async def cmd_whitelist(message: types.Message):
    # Logika proteksi: Pastikan hanya User ID kamu yang bisa akses
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        # TODO: berikan daftar whitelist
        text = "*Daftar whitelist:*\n"
        # TODO: ambil daftar whitelist dari database
        text += "Belum ada user yang ditambahkan ke whitelist."
        # tambahkan text petunjuk
        text += "\n\nGunakan: `/whitelist [chat_id]` untuk menambahkan user ke whitelist."
        await message.answer(text, parse_mode="Markdown")
        return

    chat_id = args[1]
    await add_to_whitelist(chat_id)
    await message.answer(f"✅ User dengan chat_id *{chat_id}* berhasil ditambahkan ke whitelist.", parse_mode="Markdown")

