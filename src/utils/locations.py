"""Pemetaan nama lokasi -> kode adm4 untuk argumen perintah cuaca.

``REGION_DATA`` di ``utils/constants.py`` bersifat kode adm4 -> nama, dibangun
untuk pemilih lokasi interaktif via tombol (/lokasi). ``/cuaca <lokasi>`` perlu
arah sebaliknya: pengguna mengetik nama, bot mencari kode adm4. Resolver ini
membuat indeks sebaliknya sekali saat impor — nanti menambah provinsi cukup di
``REGION_DATA`` tanpa mengubah kode di sini sama sekali, dan keyboard pilihan
pun otomatis mengikuti.
"""

import re

from utils.constants import REGION_DATA

#: Kata pengisi yang tidak boleh ikut membedakan dua tempat, supaya
#: "Wates, Kab. Kulon Progo", "wates kulon progo", dan "Wates" mengenai entri
#: yang sama. "di" ikut dibuang agar "DI Yogyakarta" menyusut ke "yogyakarta".
_FILLER = {
    "kab", "kabupaten", "kota", "desa", "kelurahan", "kecamatan",
    "daerah", "istimewa", "di",
}

_NON_TOKEN = re.compile(r"[^a-z0-9\s]")


def _normalize(text: str) -> str:
    """Satu bentuk kunci untuk semua ketikan: huruf kecil, tanpa tanda baca,
    tanpa kata pengisi. Kosong bila tidak ada sisa token yang bermakna."""
    t = _NON_TOKEN.sub(" ", text.casefold())
    tokens = [tok for tok in t.split() if tok not in _FILLER]
    return " ".join(tokens)


def _index():
    """[(entry)] dari REGION_DATA: label mentah + kunci ternormalisasi."""
    entries = []
    for province, places in REGION_DATA.items():
        for adm4, label in places.items():
            village, _, district = label.partition(",")
            entries.append({
                "adm4": adm4,
                "label": label,
                "province": province,
                "full": _normalize(label),
                "village": _normalize(village),
                "district": _normalize(district),
            })
    return tuple(entries)


_INDEX = _index()
_INDEX_BY_CODE = {e["adm4"]: e for e in _INDEX}


def resolve_location(query: str) -> dict:
    """Cari lokasi dari ketikan pengguna.

    Ladder dari yang paling spesifik; tangkai terbaik yang menang:
    1. label lengkap persis  ("wates, kab. kulon progo")
    2. nama desa/kota persis ("wates")
    3. substring label       ("progo")
    4. label lengkap dengan urutan kata berbeda ("kulon progo wates")
    5. nama wilayah setelah koma ("kulon progo")

    Satu kandidat -> "ok". Lebih dari satu pada tangkai terbaik -> "ambiguous"
    (dibawa apa adanya supaya pemanggil bisa menawarkan tombol). Tidak ada ->
    "none". String kosong atau isinya kata pengisi saja ikut "none".
    """
    q = _normalize(query)
    if not q:
        return {"status": "none", "matches": [], "query": query}

    tiers = (
        [e for e in _INDEX if e["full"] == q],
        [e for e in _INDEX if e["village"] == q],
        [e for e in _INDEX if q in e["full"]],
        [e for e in _INDEX if frozenset(q.split()) == frozenset(e["full"].split())],
        [e for e in _INDEX if e["district"] == q],
    )
    matches = next((tier for tier in tiers if tier), [])

    status = "none" if not matches else ("ok" if len(matches) == 1 else "ambiguous")
    return {"status": status, "matches": list(matches), "query": query}


def label_for(adm4: str):
    """Label lokasi untuk kode adm4 milik pustaka, atau None bila asing.

    Dipakai untuk memvalidasi callback ``wxloc_<adm4>``: kode yang tidak
    dikenal tidak boleh diteruskan ke API, atau keyboard basi/di-craft bisa
    menjadikan bot proxy lokasi di luar cakupan yang dijanjikan.
    """
    entry = _INDEX_BY_CODE.get(adm4)
    return entry["label"] if entry else None


def coverage_summary() -> str:
    """Nama provinsi yang didukung, untuk pesan 'lokasi tidak tersedia'."""
    return ", ".join(sorted(REGION_DATA))


def example_locations(count: int = 3):
    """Beberapa nama contoh yang valid, untuk pesan yang sama."""
    return [e["label"] for e in _INDEX[:count]]
