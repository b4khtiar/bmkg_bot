"""Pembentuk pesan: gempa, peringatan dini cuaca, dan cuaca.

Parser di ``services/bmkg_api.py`` mengubah payload BMKG menjadi data
terstruktur; semua keputusan tentang tampilannya ada di sini. Pemisahan ini
penting karena dua hal sebelumnya rusak justru karena tercampur: pesan gempa
dipakai dua handler dengan format berbeda, dan tiga metrik yang sama (suhu,
kelembapan, angin) dirender dengan tiga ejaan berbeda di tiga perintah.

Konvensi yang berlaku di semua formatter:

* satu aksen emoji per pesan, di judul saja;
* ``📍`` khusus lokasi, ``🗺️`` untuk cakupan wilayah, ``🏠`` untuk area user;
* baris data: emoji + label tebal + nilai;
* nilai kosong = ``—`` (lihat ``MISSING``);
* ``📡 Sumber: BMKG`` selalu di kaki pesan, dihasilkan ``compose()``.

Weather formatters mengembalikan ``(head, blocks)`` dan TIDAK memanggil
``compose()`` sendiri, karena pemanggilnya (``_build_weather_result``) masih
harus mengambil foto Unsplash secara async lebih dulu. ``compose()`` tetap satu
-satunya tempat yang memutuskan panjang pesan.

Semua data BMKG diperlakukan sebagai input tidak dipercaya dan wajib melewati
``esc()``.
"""

from utils.design import compose, section
from utils.text import (
    MISSING, bullet_list, clamp, esc, fmt_hum, fmt_temp, fmt_wind,
)


def location_label(json_response: dict) -> str:
    """``desa, kecamatan`` dalam satu format untuk semua pesan cuaca.

    Briefing harian dulu hanya menampilkan ``desa``. Nama yang kosong
    dirender sebagai ``—``, bukan ``None``: string "None" pernah bocor ke
    header karena nilainya dirangkai ke dalam string lebih dulu, sebelum
    di-escape.
    """
    lokasi = json_response.get("lokasi") or {}
    desa = esc(lokasi.get("desa"))
    kecamatan = esc(lokasi.get("kecamatan"))
    if desa == MISSING and kecamatan == MISSING:
        return MISSING
    return f"{desa}, {kecamatan}"


# --------------------------------------------------------------------------
# Gempa
# --------------------------------------------------------------------------

_BEARING_WORDS = frozenset({
    "utara", "selatan", "timur", "barat", "daya", "laut",
    "tenggara", "baratdaya", "timurlaut", "selatantimur", "baratlaut",
})


def _is_bearing_token(token: str) -> bool:
    """Apakah token ini bagian dari arah, bukan nama wilayah.

    Arah BMKG selalu diawali jarak: "120 km", "98 km". Jadi token angka di
    awal juga bagian dari arah — tanpa ini, prefiks terpanjang berhenti di
    "120" dan sisanya salah dianggap nama wilayah.
    """
    lowered = token.lower().replace(",", "")
    if lowered in _BEARING_WORDS or lowered.endswith("km"):
        return True
    # Angka bulat atau desimal, mis. "120" atau "12.5".
    return lowered.replace(".", "", 1).isdigit()


def _split_wilayah(wilayah: str) -> tuple[str, str]:
    """Pisahkan ``Wilayah`` BMKG menjadi (arah, nama wilayah).

    Format BMKG: "Pusat gempa berada di 120 km Barat Daya MALUKUTENGGARABRT".

    Arah bisa terdiri dari beberapa kata ("120 km", "Barat", "Daya"), sedangkan
    nama wilayah tidak mengandung kata arah maupun satuan "km". Jadi arah
    adalah prefiks terpanjang yang seluruh tokennya adalah token arah.

    Versi lama memecah pada spasi pertama, sehingga menampilkan "(120)" dan
    "km Barat Daya MALUKUTENGGARABRT" seolah-olah itu nama wilayah.
    """
    cleaned = str(wilayah or "").replace("Pusat gempa berada di ", "").strip()
    tokens = cleaned.split()
    if not tokens:
        return "", ""

    stop = 0
    for token in tokens:
        if not _is_bearing_token(token):
            break
        stop += 1

    if stop == 0:
        # Tidak ada arah yang bisa dibaca; jatuh ke perilaku lama.
        return tokens[0], " ".join(tokens[1:])
    return " ".join(tokens[:stop]), " ".join(tokens[stop:])


def quake_shakemap_url(data: dict) -> str:
    return f"https://cdn.bmkg.go.id/{data.get('Shakemap')}"


def format_quake(data: dict, distance_info: str = "") -> str:
    """Satu-satunya format pesan gempa, dipakai /gempa dan broadcast."""
    posisi, lokasi = _split_wilayah(data.get("Wilayah"))

    head = (
        "🚨 <b>GEMPA TERKINI</b>\n"
        f"🕒 {esc(data.get('Tanggal'))} · {esc(data.get('Jam'))}"
    )
    blocks = [
        (10, f"📈 <b>Magnitudo</b>  <code>{esc(data.get('Magnitude'))}</code>"),
        (10, f"📏 <b>Kedalaman</b>  {esc(data.get('Kedalaman'))} ({esc(posisi)})"),
        (20, f"🗺️ <b>Lokasi</b>  {esc(lokasi)}"),
        # "Dirasakan" is free-form upstream prose of unbounded length — lowest
        # priority so it is the first thing trimmed when the caption is tight.
        (50, f"🏘️ <b>Dirasakan</b>  {esc(clamp(data.get('Dirasakan'), 400))}"),
        (40, f"⚠️ <i>{esc(data.get('Potensi'))}</i>"),
    ]
    if distance_info:
        blocks.insert(3, (15, distance_info.strip()))

    return compose(head=head, blocks=blocks)["text"]


# --------------------------------------------------------------------------
# Peringatan dini cuaca (CAP)
# --------------------------------------------------------------------------

MAX_SUB_DISTRICTS = 5


def format_nowcast_alert(alert: dict) -> str:
    """Format satu peringatan dini cuaca.

    Prioritas pemangkasan disusun supaya bagian yang paling menentukan
    tindakan pengguna — waktu berlaku dan dampak — bertahan paling lama. Saran
    keselamatan justru yang pertama dibuang, karena pengguna sudah sering
    membaca episode peringatan sebelumnya.
    """
    impacts = [i.strip() for i in (alert.get("impacts") or []) if i and i.strip()]
    advice = [a.strip() for a in (alert.get("advice") or []) if a and a.strip()]

    sub_list = [s.strip() for s in str(alert.get("sub_districts") or "").split(", ") if s.strip()]
    overflow = len(sub_list) - MAX_SUB_DISTRICTS
    sub_text = ", ".join(sub_list[:MAX_SUB_DISTRICTS])
    if overflow > 0:
        # Count, not "…": "…." does not tell the user how much they are missing.
        sub_text += f" +{overflow} wilayah lain"

    head = (
        f"{alert.get('severity', 'ℹ️')} <b>PERINGATAN DINI CUACA</b>\n"
        f"🕒 {esc(alert.get('effective'))} – {esc(alert.get('expires'))}\n"
        f"🗺️ {esc(alert.get('province'))}"
    )
    blocks = [
        (10, f"{section('Peringatan')}\n{esc(alert.get('event'))}"),
        (20, f"{section('Potensi Dampak')}\n{bullet_list(impacts)}"),
        (30, f"{section('Saran Keselamatan')}\n{bullet_list(advice)}"),
        (40, f"{section('Wilayah Terdampak')}\n{esc(sub_text)}"),
    ]

    return compose(head=head, blocks=blocks)["text"]


# --------------------------------------------------------------------------
# Cuaca
#
# Semua fungsi di bawah mengembalikan (head, blocks) — lihat docstring modul.
# --------------------------------------------------------------------------


def weather_current(entry: dict, location: str, status_label: str, accent: str) -> tuple:
    """Cuaca saat ini untuk satu slot terdekat.

    Keduanya berasal dari ``utils/weather_table.py``: ``accent`` adalah
    ``wt.emoji(code)`` dan ``status_label`` adalah ``wt.label(code, fallback)``,
    dengan fallback ke ``weather_desc`` milik BMKG bila kode tidak dipetakan.

    Aksen dan label dipisah karena keduanya memuat emoji kondisi yang sama,
    tapi hanya aksen yang boleh berada di judul.
    """
    head = (
        f"{accent} <b>CUACA SAAT INI</b>\n"
        f"📍 {location}\n"
        f"🕒 {esc(entry.get('local_datetime'))}"
    )
    blocks = [
        (10, f"<b>{esc(status_label)}</b>"),
        (20, f"🌡️ <b>Suhu</b>  {fmt_temp(entry.get('t'))}"),
        (30, f"💧 <b>Kelembapan</b>  {fmt_hum(entry.get('hu'))}"),
        (40, f"💨 <b>Angin</b>  {fmt_wind(entry.get('ws'))} ({esc(entry.get('wd'))})"),
    ]
    return head, blocks


def weather_hourly(entries: list, location: str, current_dt: str, emoji_for) -> tuple:
    """Tabel cuaca per jam untuk hari ini.

    ``emoji_for(code) -> str`` dipakai agar pemetaan kode ke emoji tetap
    milik modul yang memiliki tabelnya.
    """
    rows = []
    for entry in entries:
        local_dt = entry.get("local_datetime", "")
        hour = local_dt.split(" ")[1][:5] if " " in local_dt else MISSING
        # Not 📍 — the header already uses that for the location.
        marker = " ← sekarang" if local_dt == current_dt else ""
        rows.append(
            f"{emoji_for(entry.get('weather'))} <code>{esc(hour)}</code>  "
            f"{esc(entry.get('weather_desc'))}  "
            f"{fmt_temp(entry.get('t'))}  💧 {fmt_hum(entry.get('hu'))}{marker}"
        )

    head = f"⏰ <b>CUACA PER JAM HARI INI</b>\n📍 {location}"
    return head, [(10, "\n".join(rows))]


def weather_multiday(days: list) -> tuple:
    """Prakiraan beberapa hari.

    ``days`` adalah ``[(label, temp_min, temp_max, avg_hu, max_wind,
    has_rain, slots_line)]``. Angka dihitung di sini bukan di pemanggil:
    pemformatan harus tetap satu tempat agar ``27°C`` tidak bocor sebagai
    ``27.0°C`` di salah satu perintah.
    """
    blocks = []
    for index, (label, t_min, t_max, avg_hu, max_wind, has_rain, slots) in enumerate(days):
        summary = (
            f"{'🌧️' if has_rain else '☀️'} "
            f"{fmt_temp(t_min)}–{fmt_temp(t_max)}"
            f"  💧 {fmt_hum(avg_hu)}  💨 {fmt_wind(max_wind)}"
        )
        rows = [section(label), summary]
        if slots:
            rows.append(slots)
        # Later days are trimmed first: day one is what people act on.
        blocks.append((50 - index, "\n".join(rows)))

    head = f"📅 <b>PRAKIRAAN CUACA {len(days)} HARI</b>"
    return head, blocks


def weather_daily_brief(slots: list, location: str, insight: str, trend: str) -> tuple:
    """Ringkasan pagi: kondisi per waktu, insight, dan tren besok.

    ``slots`` adalah ``[(label, entry, emoji)]``. Kelembapan ditampilkan di
    setiap slot, sama seperti ``/cuaca`` —rief sebelumnya meniadakannya,
    sehingga metrik yang sama tampil di satu pesan dan hilang di pesan lain.
    """
    rows = []
    for label, entry, emoji in slots:
        rows.append(
            f"🕒 <b>{label}</b>  {emoji} {esc(entry.get('weather_desc'))}"
            f"  {fmt_temp(entry.get('t'))}  💧 {fmt_hum(entry.get('hu'))}"
        )

    blocks = [(10, "\n".join(rows))]
    if insight:
        blocks.append((30, f"💡 <b>INSIGHT</b>\n{insight}"))
    if trend:
        blocks.append((40, f"📈 <b>TREN BESOK</b>\n{trend}"))

    head = f"📅 <b>PRAKIRAAN CUACA HARI INI</b>\n📍 {location}"
    return head, blocks
