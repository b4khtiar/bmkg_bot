import os
import logging
from aiogram import Router, types, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from database import (
    set_bot_mode, get_bot_mode, add_to_whitelist, remove_from_whitelist,
    get_all_whitelisted, count_users, is_user_whitelisted,
)
from utils.text import esc
from utils.keyboards import get_admin_panel_keyboard
from utils.constants import _VALID_BOT_MODES

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID") or 0)
logger = logging.getLogger(__name__)

@router.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Akses ditolak.", parse_mode="HTML")

    logger.info(f"Admin panel dibuka oleh {ADMIN_ID}")
    await message.answer(
        await _panel_text(),
        reply_markup=get_admin_panel_keyboard(await get_bot_mode()),
        parse_mode="HTML",
    )


async def _panel_text() -> str:
    """Teks panel yang sama untuk tampilan awal dan setelah pergantian mode.

    Sebelumnya setiap pergantian mode mengganti seluruh panel dengan dua baris
    "Status Diubah ke: X", sehingga jumlah pengguna, daftar mode, dan
    petunjuk hilang tanpa ada jalan kembali kecuali mengetik ulang /admin.
    """
    current_mode = await get_bot_mode()
    user_count = await count_users()
    return (
        "🛠 <b>Panel Admin</b>\n\n"
        f"👥 <b>Total pengguna</b>  {user_count}\n"
        f"🤖 <b>Mode saat ini</b>  {esc(current_mode)}\n\n"
        "Pilih mode di bawah untuk mengubah akses pengguna."
    )

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

    # Refresh the panel in place instead of replacing it with a stub, so the
    # user count and the mode list stay visible.
    try:
        await callback.message.edit_text(
            await _panel_text(),
            reply_markup=get_admin_panel_keyboard(new_mode),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
    await callback.answer(f"✅ Mode diubah ke {new_mode}")

@router.callback_query(F.data == "close_panel")
async def handle_close_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Akses ditolak!", show_alert=True)
    await callback.message.delete()

@router.message(Command("whitelist"))
async def cmd_whitelist(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        # Silent return here used to look like the bot ignored the command;
        # the callback handlers already answer "Akses ditolak".
        return await message.answer("⛔ Akses ditolak.", parse_mode="HTML")

    args = message.text.split()
    if len(args) < 2:
        whitelisted = await get_all_whitelisted()
        if whitelisted:
            rows = "\n".join(
                f"• <code>{user['chat_id']}</code> — {esc(user['username'] or 'Tanpa username')}"
                for user in whitelisted
            )
            text = f"👥 <b>Whitelist</b> ({len(whitelisted)} pengguna)\n\n{rows}"
        else:
            text = "👥 <b>Whitelist</b>\n\nBelum ada pengguna yang ditambahkan."

        text += (
            "\n\n<b>Perintah:</b>\n"
            "<code>/whitelist [chat_id]</code> — tambah pengguna\n"
            "<code>/whitelist force [chat_id]</code> — tambah tanpa verifikasi\n"
            "<code>/whitelist remove [chat_id]</code> — hapus pengguna"
        )
        await message.answer(text, parse_mode="HTML")
        return

    if args[1] == "remove" and len(args) >= 3:
        chat_id_str = args[2]
        if not _validate_chat_id(chat_id_str):
            return await message.answer(
                "❌ Chat ID harus berupa angka valid.", parse_mode="HTML"
            )
        chat_id = int(chat_id_str)
        # Report what actually happened. Reporting success unconditionally
        # makes a typo'd ID look like it worked.
        was_present = await is_user_whitelisted(chat_id)
        await remove_from_whitelist(chat_id)
        if was_present:
            return await message.answer(
                f"✅ User <code>{chat_id}</code> dihapus dari whitelist.", parse_mode="HTML"
            )
        return await message.answer(
            f"ℹ️ User <code>{chat_id}</code> tidak ada di whitelist.", parse_mode="HTML"
        )

    # `force` is advertised in the "unknown user" message below, so it has to
    # actually work. Previously it fell through to the add path and "force" was
    # then validated as a chat_id, producing a confusing error.
    force = args[1] == "force"
    if force and len(args) < 3:
        # Length is checked before the second index is read; bare "force" used
        # to raise an unhandled IndexError.
        return await message.answer(
            "❌ Format salah.\nGunakan: <code>/whitelist force [chat_id]</code>",
            parse_mode="HTML",
        )
    chat_id_str = args[2] if force else args[1]

    if not _validate_chat_id(chat_id_str):
        return await message.answer(
            "❌ Chat ID harus berupa angka valid.\n"
            "Gunakan: <code>/whitelist [chat_id]</code>",
            parse_mode="HTML",
        )

    chat_id = int(chat_id_str)

    from database import get_user_info
    user_exists = await get_user_info(chat_id)
    if not user_exists and not force:
        return await message.answer(
            f"⚠️ Pengguna <code>{chat_id}</code> belum pernah menggunakan bot ini.\n"
            "Tambahkan paksa dengan <code>/whitelist force [chat_id]</code>.",
            parse_mode="HTML",
        )

    await add_to_whitelist(chat_id)
    await message.answer(
        f"✅ User <code>{chat_id}</code> berhasil ditambahkan ke whitelist.",
        parse_mode="HTML",
    )


def _validate_chat_id(chat_id_str: str) -> bool:
    """Validate that the string is a valid Telegram chat_id."""
    if not chat_id_str.lstrip("-").isdigit():
        return False
    try:
        val = int(chat_id_str)
        return -9223372036854775808 <= val <= 9223372036854775807
    except (ValueError, OverflowError):
        return False
