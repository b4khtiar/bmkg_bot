"""Pemetaan nama lokasi -> kode adm4 untuk argumen perintah cuaca.

``REGION_DATA`` di ``utils/constants.py`` bersifat kode adm4 -> nama, dibangun
untuk pemilih lokasi interaktif via tombol (/lokasi). ``/cuaca <lokasi>`` perlu
arah sebaliknya: pengguna mengetik nama, bot mencari kode adm4. Resolver ini
membuat indeks sebaliknya sekali saat impor — nanti menambah provinsi cukup di
``REGION_DATA`` tanpa mengubah kode di sini sama sekali, dan keyboard pilihan
pun otomatis mengikuti.

Pustaka berisi ~25 ribu desa (Pulau Jawa). Indeks eksak (label lengkap, nama
desa, urutan kata, wilayah) dibuat sekali lewat precompute agar tiap query
berbiaya O(1); pencarian substring baru jalan kalau semua tier eksak gagal.
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


def _build_index():
    """Entri baku dari REGION_DATA + tiga indeks eksak.

    Dit berupa dict kunci -> daftar entri (desa dengan nama yang persis sama
    dalam satu kabupaten memang boleh lebih dari satu)."""
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

    by_full: dict = {}
    by_village: dict = {}
    by_token_set: dict = {}
    by_district: dict = {}

    def push(key, mapping, e):
        mapping.setdefault(key, []).append(e)

    for e in entries:
        if e["village"]:
            # Hanya entri dengan nama desa yang bermakna yang boleh jadi kunci
            # tier label lengkap dan tier nama desa. Desa yang namanya sendiri
            # kata pengisi — ada sungguhan: desa "Kelurahan", Kec. Jambu, Kab.
            # Semarang — membuat labelnya ternormalisasi habis ke nama
            # kabupaten saja, dan kunci semacam itu membajak tier eksak dari
            # desa lain. Entri semacam itu tetap bisa dipilih lewat keyboard
            # /lokasi, dan masih terjangkau tier district/substring.
            push(e["full"], by_full, e)
            push(e["village"], by_village, e)
        if e["district"]:
            push(e["district"], by_district, e)
        if frozenset(e["full"].split()):
            push(frozenset(e["full"].split()), by_token_set, e)

    return entries, by_full, by_village, by_token_set, by_district


_ENTRIES, _BY_FULL, _BY_VILLAGE, _BY_TOKEN_SET, _BY_DISTRICT = _build_index()


def _build_code_index():
    """Kode adm4 -> entri, untuk memvalidasi kode yang datang dari callback."""
    return {e["adm4"]: e for e in _ENTRIES}


_ENTRIES_BY_CODE = _build_code_index()


def resolve_location(query: str) -> dict:
    """Cari lokasi dari ketikan pengguna.

    Ladder dari yang paling spesifik; tangkai terbaik yang menang:
    1. label lengkap persis  ("wates, kab. kulon progo")
    2. nama desa/kota persis ("wates")
    3. label lengkap dengan urutan kata berbeda ("kulon progo wates")
    4. substring label       ("progo")
    5. nama wilayah setelah koma ("kulon progo")

    Tier 1-3 eksak: O(1) dari precomputed index terhadap label yang dinormalisasi.
    Tier 4 baru berjalan kalau semua eksak selesai tanpa peretangan. Satu
    kandidat -> "ok". Lebih dari satu pada tangkai terbaik -> "ambiguous"
    (dibawa apa adanya supaya pemanggil bisa menawarkan tombol). Tidak ada ->
    "none". String kosong atau isinya kata pengisi saja ikut "none".
    """
    q = _normalize(query)
    if not q:
        return {"status": "none", "matches": [], "query": query}

    for lookup in (_BY_FULL.get(q), _BY_VILLAGE.get(q),
                   _BY_TOKEN_SET.get(frozenset(q.split()))):
        if lookup:
            matches = list(lookup)
            break
    else:
        # Substring: scan penuh sekali panggil — nama wilayah seperti
        # "kulon progo" tidak menjadi kunci apa pun.
        matches = [e for e in _ENTRIES if q in e["full"]]
        if not matches:
            matches = list(_BY_DISTRICT.get(q, ()))

    if not matches:
        return {"status": "none", "matches": [], "query": query}

    status = "ok" if len(matches) == 1 else "ambiguous"
    return {"status": status, "matches": matches, "query": query}


def label_for(adm4: str):
    """Label lokasi untuk kode adm4 milik pustaka, atau None bila asing.

    Dipakai untuk memvalidasi callback ``wxloc_<adm4>`` dan ``setloc_<adm4>``:
    kode yang tidak dikenal tidak boleh diteruskan ke API ataupun disimpan,
    atau keyboard basi/di-craft bisa menjadikan bot proxy lokasi di luar
    cakupan yang dijanjikan.
    """
    entry = _ENTRIES_BY_CODE.get(adm4)
    return entry["label"] if entry else None


def coverage_summary() -> str:
    """Nama provinsi yang didukung, untuk pesan 'lokasi tidak tersedia'."""
    return ", ".join(sorted(REGION_DATA))


def example_locations(count: int = 3):
    """Beberapa nama contoh yang valid, untuk pesan yang sama."""
    return [e["label"] for e in _ENTRIES[:count]]
