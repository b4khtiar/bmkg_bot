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

    for code, name in cities.items():
        callback_data = f"setloc_{code}_{name}"
        assert len(callback_data.encode("utf-8")) <= 64, \
            f"callback_data too long for {name}: {len(callback_data)} bytes"
        builder.button(
            text=name,
            callback_data=callback_data
        )
    builder.adjust(2)

    builder.row(types.InlineKeyboardButton(text="⬅️ Kembali", callback_data="setup_location"))
    return builder.as_markup()

def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Set Lokasi Wilayah", callback_data="setup_location")
    return builder.as_markup()

def get_admin_panel_keyboard(current_mode: str):
    builder = InlineKeyboardBuilder()
    modes = ["OPEN", "WHITELIST", "MAINTENANCE"]
    for m in modes:
        label = f"✅ {m}" if m == current_mode else m
        builder.button(text=label, callback_data=f"setmode_{m}")
    builder.button(text="❌ Close Panel", callback_data="close_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_notif_prefs_keyboard(prefs: dict):
    builder = InlineKeyboardBuilder()

    labels = {
        "notify_quake": ("🔴 Gempa", "🟤 Gempa"),
        "notify_weather": ("🔵 Cuaca", "⚪ Cuaca"),
        "notify_nowcast": ("🟠 Nowcast", "⚪ Nowcast"),
    }

    for pref_key, (on_label, off_label) in labels.items():
        is_on = prefs.get(pref_key, True)
        display = f"{on_label} ✅" if is_on else f"{off_label} ❌"
        builder.button(text=display, callback_data=f"notif_{pref_key}")

    builder.adjust(1)
    return builder.as_markup()
