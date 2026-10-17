from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import types
from utils.constants import REGION_DATA


#: Tombol provinsi per halaman. Dipaginasi karena peta wilayah sudah-version
#: 34 provinsi: satu tombol per baris menghasilkan dinding 34 baris yang harus
#: di-scroll, sementara keyboard kota sudah dua per baris.
PROVINCES_PER_PAGE = 10


def get_province_keyboard(page: int = 0):
    """Daftar provinsi, dua per baris, dipaginasi.

    ``page`` di-clamp ke rentang yang benar, jadi callback_data yang rusak
    atau basi tidak bisa membuat pengguna terjebak di halaman kosong.
    """
    provinces = list(REGION_DATA.keys())
    if not provinces:
        return _markup([])

    total_pages = max(1, -(-len(provinces) // PROVINCES_PER_PAGE))
    page = min(max(page, 0), total_pages - 1)
    visible = provinces[page * PROVINCES_PER_PAGE:(page + 1) * PROVINCES_PER_PAGE]

    builder = InlineKeyboardBuilder()
    for prov in visible:
        builder.button(text=prov, callback_data=f"prov_{prov}")
    # Two per row, same as the city keyboard it hands off to.
    builder.adjust(2)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton(
                text="⬅️ Sebelumnya", callback_data=f"provpage_{page - 1}"))
        if page < total_pages - 1:
            nav.append(types.InlineKeyboardButton(
                text="Berikutnya ➡️", callback_data=f"provpage_{page + 1}"))
        if nav:
            builder.row(*nav)

    return builder.as_markup()


def province_page_count() -> int:
    provinces = len(REGION_DATA)
    return max(1, -(-provinces // PROVINCES_PER_PAGE))


def _markup(buttons):
    builder = InlineKeyboardBuilder()
    for b in buttons:
        builder.row(b)
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


#: Batas kandidat yang ditawarkan untuk /cuaca <lokasi> ambigu — daftar yang
#: terlalu panjang jadi dinding tombol yang harus di-scroll.
_MAX_LOCATION_CHOICES = 10


def get_weather_location_choices(matches):
    """Tombol kandidat lokasi untuk /cuaca dengan ketikan ambigu.

    callback_data memuat kode adm4 langsung (wxloc_<adm4>) — tanpa status
    sesi, jadi tombol tetap benar walau bot di-restart dulu. Batasi jumlahnya:
    resolusi tier bisa memilih lebih kandidat daripada yang layak ditampilkan.
    """
    builder = InlineKeyboardBuilder()
    for m in matches[:_MAX_LOCATION_CHOICES]:
        callback_data = f"wxloc_{m['adm4']}"
        assert len(callback_data.encode("utf-8")) <= 64, \
            f"callback_data too long for {m['adm4']}: {len(callback_data)} bytes"
        builder.button(text=m["label"], callback_data=callback_data)
    builder.adjust(2)
    return builder.as_markup()


def get_start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Set Lokasi Wilayah", callback_data="setup_location")
    return builder.as_markup()


def get_change_location_keyboard():
    """Tombol pada layar konfirmasi lokasi.

    Layar ini sebelumnya menghapus seluruh keyboard, jadi pengguna yang salah
    pilih tidak punya jalan keluar kecuali mengetik ulang /start.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Ubah Lokasi", callback_data="setup_location")
    return builder.as_markup()


def get_admin_panel_keyboard(current_mode: str):
    builder = InlineKeyboardBuilder()
    modes = ["OPEN", "WHITELIST", "MAINTENANCE"]
    for m in modes:
        # One convention across the bot: ✅ marks the active value, unadorned
        # text marks the alternatives. The prefs keyboard used to use coloured
        # dots instead, including a brown circle that read as a glitch.
        label = f"✅ {m}" if m == current_mode else m
        builder.button(text=label, callback_data=f"setmode_{m}")
    builder.button(text="❌ Tutup Panel", callback_data="close_panel")
    builder.adjust(1)
    return builder.as_markup()


# label, schedule shown to the user. Without the schedule there is no way to
# know when a notification will arrive, so people toggle it off and then
# wonder why they stopped hearing from the bot.
_NOTIF_LABELS = {
    "notify_quake": ("🌋 Gempa", None),
    "notify_weather": ("🌤️ Cuaca", "06.30 & 16.45"),
    "notify_nowcast": ("🌧️ Nowcast", "tiap 10 menit"),
}


def get_notif_prefs_keyboard(prefs: dict):
    builder = InlineKeyboardBuilder()

    for pref_key, (base_label, schedule) in _NOTIF_LABELS.items():
        is_on = prefs.get(pref_key, True)
        text = f"✅ {base_label}" if is_on else f"⬜ {base_label}"
        if schedule:
            text += f" · {schedule}"
        builder.button(text=text, callback_data=f"notif_{pref_key}")

    builder.adjust(1)
    return builder.as_markup()
