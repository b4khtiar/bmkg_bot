"""Prinsip visual dan perakitan pesan.

Modul ini adalah satu-satunya tempat yang memutuskan apakah sebuah pesan
dikirim sebagai foto (dengan caption) atau sebagai teks, dan apakah foto itu
punya kredit. Sebelumnyalogika itu terbelah dua:

* ``handlers/user.py::_reply_weather``-route ``/cuaca`` punya batas caption,
* ``main.py::_send_photo_sem`` yang dipakai seluruh broadcast **tidak punya
  batas sama sekali**.

Akibatnya peringatan dini cuaca yang panjang (``bmkg_api`` assembling status +
waktu + provinsi + event + seluruh bullet dampak + seluruh bullet saran) gagal
dikirim, masuk ``pending_sends``, gagal tiga kali, lalu dibuang. Ringkasan ke
admin tetap melaporkan "0 gagal" karena gagalnya ada di lapisan Telegram, bukan
di lapisan broadcast.

``compose()`` menutup celah itu: satu budget, satu aturan kredit, satu
urutan pemangkasan.
"""

from utils.text import clamp

# Batas keras Telegram untuk caption foto. Melebihi ini tidak akan dipotong
# oleh Telegram, melainkan ditolak.
CAPTION_LIMIT = 1024

RULE = "━━━━━━━━━━━━━━━━━━"
SOURCE_LINE = "📡 <i>Sumber: BMKG</i>"

# Aksen per tingkat keparahan peringatan dini cuaca (CAP severity).
#
# Pemetaan ini sebelumnya ditulis inline di parse_cap_detail, sehingga tidak
# tersedia di tempat lain yang butuh keputusan yang sama. Sekarang satu
# sumber, dan nilai-mentahnya ikut disimpan supaya pemanggil bisa menampilkannya
# apa adanya kalau perlu.
SEVERITY_ACCENT = {
    "Extreme": "🔴",
    "Severe": "🔴",
    "Moderate": "🟠",
    "Minor": "🟡",
}
SEVERITY_LABEL = {
    "Extreme": "BAHAYA",
    "Severe": "BAHAYA",
    "Moderate": "WASPADA",
    "Minor": "SIAGA",
}
SEVERITY_FALLBACK = ("ℹ️", "INFO")

# Urutan tingkat keparahan untuk pembanding: peringatan ulang yang LEBIH
# parah tetap boleh lewat meski jeda pengulangan nowcast belum habis.
# Tidak ada di tabel (atau "Unknown") = 0, paling lemah.
SEVERITY_RANK = {"Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}


def severity_note(raw: str) -> str:
    """``"Moderate"`` → ``"🟠 WASPADA"``."""
    accent = SEVERITY_ACCENT.get(raw, SEVERITY_FALLBACK[0])
    label = SEVERITY_LABEL.get(raw, SEVERITY_FALLBACK[1])
    return f"{accent} {label}"


def severity_rank(raw: str) -> int:
    """``"Severe"`` → ``3``; tidak dikenal (termasuk ``"Unknown"``) → ``0``."""
    return SEVERITY_RANK.get(raw, 0)


def section(label: str) -> str:
    """Judul seksi bergaris, mis. ``━━━ Dampak ━━━``."""
    return f"━━━ {label} ━━━"


def truncate_notice(dropped: list[str]) -> str:
    """Beri tahu pengguna isi yang dipangkas, agar terasa jujur, bukan rusak.

    Pemangkasan diam-diam terbaca sebagai bug; disclose singkat lebih baik.
    """
    if not dropped:
        return ""
    return "<i>Detail sebagian dipangkas agar pesan tidak terpotong Telegram.</i>"


def _with_credit(text: str, photographer: str | None) -> str:
    """Tambahkan kredit foto hanya bila foto benar-benar ikut terkirim."""
    if not photographer:
        return text
    return f"{text}\n📸 <i>Foto: {photographer} / Unsplash</i>"


def _assemble(head: str, blocks: list[tuple[int, str]], banner: str, dropped: list[str]) -> str:
    # RULE memisahkan kepala dari isi, RULE_SAME menutup pesan sebelum footer.
    # Satu keluarga garis untuk semua pesan; sebelumnya ada "━━━", "━━━━", dan
    # pesan tanpa pemisah sama sekali tergantung perintahnya.
    rows = [head, RULE]
    rows += [text for _, text in blocks]
    notice = truncate_notice(dropped)
    if notice:
        rows.append(notice)
    rows.append(SOURCE_LINE)
    if banner:
        rows.insert(0, banner.rstrip("\n"))
    return "\n".join(r for r in rows if r)


def compose(
    *,
    head: str,
    blocks: list[tuple[int, str]] | None = None,
    banner: str = "",
    photo: str | None = None,
    photographer: str | None = None,
    budget: int = CAPTION_LIMIT,
) -> dict:
    """Rakit satu pesan menjadi {text, photo_url, photographer}.

    ``blocks`` adalah daftar ``(priority, text)``. Priority rendah dibuang lebih
    dulu — dipakai untuk memangkas yang paling boleh hilang (catatan tambahan,
    bullet saran keselamatan) sebelum menyentuh bagian yang pengguna butuh
    untuk bertindak: judul, waktu, lokasi, dan dampak.

    ``banner`` (misalnya "⚠️ Data cadangan") hanya disertakan bila pemanggil
    memang punya data cadangan; pemanggil yang sedang degradation tidak akan
    diam-diam menampilkan data basi seolah-olah data segar.
    """
    blocks = [(p, t) for p, t in (blocks or []) if t]
    dropped: list[str] = []

    def attempt(survivors: list[tuple[int, str]], notice: list[str]) -> dict | None:
        """Coba kirim dengan foto dulu, lalu teks biasa. None bila belum muat.

        Kredit foto adalah bagian dari caption, jadi ketika caption ber-kredit
        tidak muat, kredit itu ikut hilang bersama fotonya — bukan tetap
        tertinggal di teks yang dikirim tanpa foto.
        """
        text = _assemble(head, survivors, banner, notice)

        if photo:
            with_credit = _with_credit(text, photographer)
            if len(with_credit) <= budget:
                return {
                    "text": with_credit,
                    "photo_url": photo,
                    "photographer": photographer,
                }

        if len(text) <= budget:
            return {"text": text, "photo_url": None, "photographer": None}

        return None

    def label_of(block: str) -> str:
        first = block.splitlines()[0] if block.strip() else ""
        return first.strip("━ ").strip() or "bagian tambahan"

    # 1. Penuh: foto dulu, teks sebagai cadangan.
    result = attempt(blocks, dropped)
    if result:
        return result

    # 2. Pangkas block dengan priority tertinggi sampai muat. Yang dibuang
    #    dicatat, lalu diberi tahu ringkas di kaki pesan.
    for idx in sorted(range(len(blocks)), key=lambda i: -blocks[i][0]):
        dropped.append(label_of(blocks[idx][1]))
        remaining = [b for i, b in enumerate(blocks) if i != idx]
        result = attempt(remaining, dropped)
        if result:
            return result

    # 3. Terakhir: judul saja. Potong keras agar tetap terkirim — lebih baik
    #    terpotong daripada hilang total.
    text = _assemble(head, [], banner, dropped)
    if len(text) > budget:
        head_room = max(0, budget - len(SOURCE_LINE) - 1)
        text = clamp(head, head_room) + "\n" + SOURCE_LINE

    return {"text": text, "photo_url": None, "photographer": None}
