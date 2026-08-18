import os
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from database import set_bot_mode, get_bot_mode, add_to_whitelist, remove_from_whitelist, get_all_whitelisted, count_users
from utils.keyboards import get_admin_panel_keyboard
from utils.constants import _VALID_BOT_MODES

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID") or 0)
logger = logging.getLogger(__name__)

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    logger.info(f"Admin panel dibuka oleh {ADMIN_ID}")
    current_mode = await get_bot_mode()
    user_count = await count_users()
    text = (
        "<b>🛠 CONTROL PANEL ADMIN</b>\n\n"
        f"👥 Total User: {user_count}\n"
        f"🤖 Mode: {current_mode}\n"
        "Pilih mode di bawah untuk mengubah akses pengguna:"
    )
    await message.answer(text, reply_markup=get_admin_panel_keyboard(current_mode), parse_mode="HTML")

@router.callback_query(F.data.startswith("setmode_"))
async def handle_set_mode(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Akses ditolak!", show_alert=True)

    new_mode = callback.data.split("_")[1]
    if new_mode not in _VALID_BOT_MODES:
        return await callback.answer("Mode tidak valid!", show_alert=True)

    current_mode = await get_bot_mode()

    if new_mode == current_mode:
        return await callback.answer(f"Bot sudah dalam mode {new_mode}")

    await set_bot_mode(new_mode)

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
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2:
        whitelisted = await get_all_whitelisted()
        text = "*Daftar Whitelist:*\n"
        if whitelisted:
            for user in whitelisted:
                username = user['username'] or "Tanpa username"
                text += f"• `{user['chat_id']}` — {username}\n"
        else:
            text += "Belum ada user yang ditambahkan ke whitelist."

        text += "\n\nGunakan:\n`/whitelist [chat_id]` — tambah user\n`/whitelist remove [chat_id]` — hapus user"
        await message.answer(text, parse_mode="Markdown")
        return

    if args[1] == "remove" and len(args) >= 3:
        chat_id_str = args[2]
        if not _validate_chat_id(chat_id_str):
            return await message.answer("❌ Chat ID harus berupa angka valid.", parse_mode="Markdown")
        chat_id = int(chat_id_str)
        await remove_from_whitelist(chat_id)
        await message.answer(f"✅ User *{chat_id}* berhasil dihapus dari whitelist.", parse_mode="Markdown")
        return

    chat_id_str = args[1]
    if not _validate_chat_id(chat_id_str):
        await message.answer("❌ Chat ID harus berupa angka valid.\nGunakan: `/whitelist [chat_id]`", parse_mode="Markdown")
        return

    chat_id = int(chat_id_str)

    # Verify user exists
    from database import get_user_info
    user_exists = await get_user_info(chat_id)
    if not user_exists:
        await message.answer(f"⚠️ Pengguna *{chat_id}* belum pernah menggunakan bot ini. Tambahkan ke whitelist? Gunakan `/whitelist force [chat_id]`.", parse_mode="Markdown")
        return

    await add_to_whitelist(chat_id)
    await message.answer(f"✅ User *{chat_id}* berhasil ditambahkan ke whitelist.", parse_mode="Markdown")


def _validate_chat_id(chat_id_str: str) -> bool:
    """Validate that the string is a valid Telegram chat_id."""
    if not chat_id_str.lstrip("-").isdigit():
        return False
    try:
        val = int(chat_id_str)
        return -9223372036854775808 <= val <= 9223372036854775807
    except (ValueError, OverflowError):
        return False
