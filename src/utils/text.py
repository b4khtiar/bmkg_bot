"""Pembantu teks untuk pesan Telegram.

Semua data dari BMKG (JSON, XML CAP, RSS) diperlakukan sebagai input yang tidak
terpercaya: isinya disisipkan ke pesan dengan ``parse_mode="HTML"``, sehingga
satu karakter ``&`` atau ``<`` saja sudah cukup membuat Telegram menolak pesan
dengan ``BadRequest: can't parse entities``. Di jalur broadcast, pesan itu lalu
antre di ``pending_sends``, gagal ``MAX_SEND_RETRIES`` kali, dan akhirnya
dibuang — pengguna tidak pernah menerima peringatan tersebut.

Karena itu, semua titik sisip wajib melewati ``esc()`` / ``esc_href()``.
"""

import html

# Nilai pengganti saat data kosong. Dipakai di mana-mana, bukan "N/A" dan
# bukan string kosong — supaya "tidak ada data" selalu tampil sebagai keputusan
# visual yang disengaja, bukan sebagai lubang di layout.
MISSING = "—"


def esc(value) -> str:
    """Escape teks untuk disisipkan ke konten pesan HTML.

    ``None`` menjadi ``MISSING``, bukan string kosong, supaya pemanggil tidak
    perlu memeriksa dua hal sekaligus.
    """
    if value is None:
        return MISSING
    text = str(value).strip()
    if not text:
        return MISSING
    return html.escape(text, quote=False)


def esc_inline(value) -> str:
    """Escape teks yang juga boleh berisi karakter kutip.

    Dipakai untuk nilai yang menempel pada atribut seperti ``title="..."``.
    """
    if value is None:
        return MISSING
    text = str(value).strip()
    if not text:
        return MISSING
    return html.escape(text, quote=True)


def esc_href(url) -> str:
    """Escape URL untuk atribut ``href``.

    Kutip menjadi ``&quot;`` sehingga URL tidak bisa menutupi atribut dan
    menyuntikkan event handler baru.
    """
    if not url:
        return ""
    return html.escape(str(url).strip(), quote=True)


def fmt_num(value, decimals: int = 0, suffix: str = "") -> str:
    """Format angka dengan jumlah desimal tetap, atau ``MISSING`` bila absen.

    Dipakai agar ``27.0`` dan ``27`` tidak bocor ke dalam pesan sebagai
    ``27.0°C`` di satu baris dan ``27°C`` di baris lain.
    """
    if value is None or value == "":
        return MISSING
    try:
        number = float(value)
    except (TypeError, ValueError):
        return MISSING
    return f"{number:.{decimals}f}{suffix}"


def fmt_temp(value) -> str:
    """Suhu dalam derajat Celsius, mis. ``27°C``."""
    return fmt_num(value, 0, "°C")


def fmt_hum(value) -> str:
    """Kelembapan relatif, mis. ``63%``."""
    return fmt_num(value, 0, "%")


def fmt_wind(value) -> str:
    """Kecepatan angin, mis. ``12 km/jam``."""
    return fmt_num(value, 0, " km/jam")


def bullet_list(items, marker: str = "•", limit: int | None = None) -> str:
    """Renders a bullet list, or ``MISSING`` when there is nothing to list.

    Kembalikan ``MISSING`` alih-alih heading kosong: blok seperti
    "Potensi Dampak:" dengan nol bullet terlihat seperti bug, bukan seperti
    "tidak ada".
    """
    cleaned = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not cleaned:
        return MISSING
    if limit is not None and len(cleaned) > limit:
        return "\n".join(f"{marker} {i}" for i in cleaned[:limit])
    return "\n".join(f"{marker} {i}" for i in cleaned)


def join_rows(rows) -> str:
    """Gabungkan baris, buang yang kosong supaya tidak ada spasi ganda."""
    return "\n".join(r for r in rows if r)


def clamp(text: str, limit: int, ellipsis: str = "…") -> str:
    """Potong teks panjang di batas karakter, dengan ellipsis.

    Dipakai untuk nilai bebas dari BMKG (mis. ``Dirasakan``) yang panjangnya
    tidak dibatasi oleh payload.
    """
    if text is None:
        return MISSING
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(ellipsis))].rstrip() + ellipsis
