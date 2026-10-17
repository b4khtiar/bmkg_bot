"""Konfigurasi pytest bersama.

aiogram tidak tersedia di lingkungan uji ini, jadi `tests/aiogram_stub.py`
memasang tiruan saat paket aslinya tidak bisa diimpor. Stub ini hanya
men-campuskan *signature* yang dipakai repo; ini bukan simulasi Telegram.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:  # pragma: no cover - bergantung pada lingkungan
    import aiogram
except ImportError:
    from tests import aiogram_stub

    aiogram_stub.install()
else:
    # Ini hanya probe ketersediaan paket; nama `aiogram` tidak dipakai di
    # conftest ini, sengaja dihapus agar pemeriksa selalu bersih.
    del aiogram