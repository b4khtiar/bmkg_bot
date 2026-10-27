"""Pustaka wilayah — kode adm4 -> label, dikelompokkan per provinsi.

Modul per provinsi agar berkas data besar tetap bisa direview dan didiff
per provinsi. ``kunci provinsi -> {kode adm4 -> label}`` dari tiap modul
digabung di sini dengan urutan eksplisit (DI Yogyakarta dulu) supaya daftar
contoh lokasi tetap seperti dulu.

``utils/constants.py`` re-export ``REGION_DATA`` dari sini — konsumen tetap
impor dari constants seperti semula.

Sumber kode wilayah: Kepmendagri No. 100.1.1-6117 Tahun 2022 (kode wilayah
administrasi tingkat IV).
"""

from utils.regions.diy import REGION_DATA as _DIY
from utils.regions.banten import REGION_DATA as _BANTEN
from utils.regions.dki import REGION_DATA as _DKI
from utils.regions.jawa_barat import REGION_DATA as _JAWA_BARAT
from utils.regions.jawa_tengah import REGION_DATA as _JAWA_TENGAH
from utils.regions.jawa_timur import REGION_DATA as _JAWA_TIMUR

#: Urutan gabungan — DI Yogyakarta dulu supaya (1) daftar contoh pada pesan
#: "lokasi tidak tersedia" tetap menampilkan contoh DIY seperti sebelum
#: data Jawa masuk, (2) urutan provinsi pada picker stabil dan tidak acak.
#: Sisanya alfabetis.
REGION_DATA = {
    **_DIY,
    **_BANTEN,
    **_DKI,
    **_JAWA_BARAT,
    **_JAWA_TENGAH,
    **_JAWA_TIMUR,
}
