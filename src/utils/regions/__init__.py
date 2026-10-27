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

#: Urutan gabungan — provinsi terdahulu dulu supaya (1) daftar contoh pada
#: pesan "lokasi tidak tersedia" tetap menampilkan DIY, (2) peta provinsi
#: pada picker stabil dan tidak acak.
REGION_DATA = {
    **_DIY,
}
