# src/utils/keyboards.py
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import types
from utils.constants import REGION_DATA

def get_province_keyboard():
    builder = InlineKeyboardBuilder()
    for prov in REGION_DATA.keys():
        builder.row(types.InlineKeyboardButton(
            text=prov, 
            callback_data=f"prov_{prov}")
        )
    return builder.as_markup()

def get_city_keyboard(province_name: str):
    builder = InlineKeyboardBuilder()
    cities = REGION_DATA.get(province_name, {})
    
    # Buat tombol 2 kolom agar tidak terlalu panjang ke bawah
    for code, name in cities.items():
        builder.button(
            text=name, 
            callback_data=f"setloc_{code}_{name}"
        )
    builder.adjust(2) # Maksimal 2 kolom
    
    # Tombol kembali di baris paling bawah
    builder.row(types.InlineKeyboardButton(text="⬅️ Kembali", callback_data="setup_location"))
    return builder.as_markup()

def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Set Lokasi Wilayah", callback_data="setup_location")
    return builder.as_markup()

def get_admin_panel_keyboard(current_mode: str):
    builder = InlineKeyboardBuilder()
    
    # Daftar mode yang tersedia
    modes = ["OPEN", "WHITELIST", "MAINTENANCE"]
    
    for m in modes:
        # Beri tanda centang pada mode yang sedang aktif
        label = f"✅ {m}" if m == current_mode else m
        builder.button(text=label, callback_data=f"setmode_{m}")
    
    # Tombol close panel
    builder.button(text="❌ Close Panel", callback_data="close_panel")
    builder.adjust(1) # Susun vertikal agar rapi
    return builder.as_markup()