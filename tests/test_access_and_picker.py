"""Gerbang mode bot dan keyboard provinsi.

Dua masalah yang ditutup di sini:

* **Mode tidak menegakkan apa pun.** Hanya ``/start`` yang memeriksa mode, jadi
  saat bot ``MAINTENANCE`` pengguna masih bisa ``/cuaca`` dan menerima data.
  Pemeliharaan jadi tidak berarti apa-apa.
* **Daftar provinsi tidak bisa diskalakan.** Satu tombol per baris menghasilkan
  dinding yang harus di-scroll, sementara keyboard kota sudah dua per baris —
  dan peta wilayah akan cepat punya 34 provinsi.
"""
import asyncio

import pytest

import handlers.user as U
from utils import keyboards as K
from tests.aiogram_stub import Message


class _DB:
    def __init__(self, mode="OPEN", whitelisted=False):
        self.mode = mode
        self.whitelisted = whitelisted
        self.user = {"adm_code": "34.01.09.2001", "adm_name": "Jatimulyo"}

    async def get_bot_mode(self):
        return self.mode

    async def is_user_whitelisted(self, _chat_id):
        return self.whitelisted

    async def get_user_info(self, _chat_id):
        return self.user

    async def get_user_prefs(self, _chat_id):
        return {}

    async def add_user(self, *a):
        return None


@pytest.fixture
def db(monkeypatch):
    d = _DB()
    for name in ("get_bot_mode", "is_user_whitelisted", "get_user_info",
                 "get_user_prefs", "add_user"):
        monkeypatch.setattr(U, name, getattr(d, name))
    return d


@pytest.fixture
def user(monkeypatch):
    """Pengguna biasa (bukan admin)."""
    monkeypatch.setattr(U, "ADMIN_ID", 999)
    return 1


@pytest.fixture
def sent():
    out = []

    class Recorder(Message):
        def __init__(self, text=None):
            super().__init__()
            self.text = text
            self.chat = type("C", (), {"id": 1})()
            self.from_user = type("U", (), {"username": "u", "id": 1})()

        async def answer(self, text=None, **kwargs):
            out.append((text, kwargs))
            return self

    return out, Recorder


#: Perintah yang butuh API BMKG — harus berhenti saat MAINTENANCE.
DATA_COMMANDS = ["cuaca", "prakiraan", "per_jam", "gempa", "nowcast"]
#: Perintah yang tidak butuh API — harus tetap jalan.
UTILITY_COMMANDS = ["start", "bantuan", "ping", "lokasi", "notifikasi"]


class TestMaintenanceGate:
    @pytest.mark.parametrize("cmd", DATA_COMMANDS)
    def test_data_commands_blocked_during_maintenance(self, db, user, sent, cmd):
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        allowed = asyncio.run(U.check_access(Recorder(f"/{cmd}")))
        assert allowed is False
        assert "pemeliharaan" in out[0][0].lower()

    @pytest.mark.parametrize("cmd", UTILITY_COMMANDS)
    def test_utility_commands_survive_maintenance(self, db, user, sent, cmd):
        """Pengguna tidak boleh terjebak tanpa jalan keluar."""
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder(f"/{cmd}"))) is True
        assert out == []

    def test_open_mode_allows_everything(self, db, user, sent):
        out, Recorder = sent
        for cmd in DATA_COMMANDS + UTILITY_COMMANDS:
            assert asyncio.run(U.check_access(Recorder(f"/{cmd}"))) is True
        assert out == []

    def test_command_with_bot_suffix_recognised(self, db, user, sent):
        """/cuaca@MyBot harus dianggap sama dengan /cuaca, bukan lolos sebagai
        perintah tak dikenal."""
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder("/cuaca@MyWeatherBot"))) is False
        assert "pemeliharaan" in out[0][0].lower()

    def test_capitalised_command_recognised(self, db, user, sent):
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder("/Cuaca"))) is False

    def test_admin_bypasses_maintenance(self, db, user, sent):
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        msg = Recorder("/cuaca")
        msg.chat = type("C", (), {"id": 999})()
        assert asyncio.run(U.check_access(msg)) is True
        assert out == []

    def test_empty_text_does_not_crash(self, db, user, sent):
        db.mode = "MAINTENANCE"
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder(None))) is False


class TestWhitelistGate:
    @pytest.mark.parametrize("cmd", DATA_COMMANDS + ["bantuan", "ping", "lokasi"])
    def test_non_whitelisted_blocked(self, db, user, sent, cmd):
        db.mode = "WHITELIST"
        db.whitelisted = False
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder(f"/{cmd}"))) is False
        assert "whitelist" in out[0][0].lower()

    def test_whitelisted_user_passes(self, db, user, sent):
        db.mode = "WHITELIST"
        db.whitelisted = True
        out, Recorder = sent
        assert asyncio.run(U.check_access(Recorder("/cuaca"))) is True

    def test_start_is_never_gated_by_the_decorator(self, db, user, sent):
        """/start punya penjaga sendiri supaya bisa menjelaskan kenapa
        akses ditolak."""
        db.mode = "WHITELIST"
        db.whitelisted = False
        out, Recorder = sent
        # check_access menolak, tapi /start tidak memakai requires_access.
        assert asyncio.run(U.check_access(Recorder("/start"))) is False
        assert not hasattr(U.cmd_start, "__wrapped__")

    def test_admin_bypasses_whitelist(self, db, user, sent):
        db.mode = "WHITELIST"
        db.whitelisted = False
        out, Recorder = sent
        msg = Recorder("/cuaca")
        msg.chat = type("C", (), {"id": 999})()
        assert asyncio.run(U.check_access(msg)) is True
        assert out == []


class TestAccessDecorator:
    def test_handler_not_called_when_blocked(self, db, user, sent):
        db.mode = "MAINTENANCE"
        called = []

        @U.requires_access
        async def handler(message):
            called.append(1)

        out, Recorder = sent
        asyncio.run(handler(Recorder("/cuaca")))
        assert called == []
        assert out, "pengguna tidak diberi tahu kenapa perintahnya diabaikan"

    def test_handler_called_when_allowed(self, db, user, sent):
        called = []

        @U.requires_access
        async def handler(message):
            called.append(1)
            return "hasil"

        out, Recorder = sent
        assert asyncio.run(handler(Recorder("/cuaca"))) == "hasil"
        assert called == [1]

    def test_decorator_preserves_metadata(self):
        @U.requires_access
        async def contoh(message):
            """Docstring asli."""

        assert contoh.__name__ == "contoh"
        assert contoh.__doc__ == "Docstring asli."

    @pytest.mark.parametrize("name", [
        "cmd_current_weather", "cmd_extended_forecast", "cmd_hourly_today",
        "cmd_earthquake", "cmd_nowcast",
    ])
    def test_data_commands_are_wrapped(self, name):
        handler = getattr(U, name)
        assert hasattr(handler, "__wrapped__"), (
            f"{name} tidak memakai @requires_access — mode tidak akan menegakkan apa pun"
        )

    def test_start_is_not_wrapped(self):
        assert not hasattr(U.cmd_start, "__wrapped__")


class TestProvinceKeyboard:
    def _buttons(self, markup):
        rows = markup["inline_keyboard"]
        return [b for row in rows for b in row]

    def test_two_per_row(self, monkeypatch):
        """Kota sudah dua per baris; provinsi harus sama."""
        monkeypatch.setattr(K, "REGION_DATA", {
            f"Provinsi{i}": {} for i in range(6)
        })
        rows = K.get_province_keyboard()["inline_keyboard"]
        data_rows = [r for r in rows if len(r) == 2]
        assert data_rows, "tidak ada baris dengan dua provinsi"

    def test_paginated_when_many_provinces(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {
            f"Provinsi{i}": {} for i in range(25)
        })
        assert K.province_page_count() == 3
        page0 = self._buttons(K.get_province_keyboard(0))
        labels = [b.text for b in page0]
        assert any("Provinsi0" in t for t in labels)
        assert any("Berikutnya" in t for t in labels)
        assert not any("Sebelumnya" in t for t in labels)

    def test_last_page_has_no_forward_button(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {
            f"Provinsi{i}": {} for i in range(25)
        })
        labels = [b.text for b in self._buttons(K.get_province_keyboard(2))]
        assert any("Sebelumnya" in t for t in labels)
        assert not any("Berikutnya" in t for t in labels)

    def test_single_page_has_no_navigation(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {"DIY": {}})
        labels = [b.text for b in self._buttons(K.get_province_keyboard(0))]
        assert not any("Berikutnya" in t or "Sebelumnya" in t for t in labels)

    def test_page_out_of_range_is_clamped(self, monkeypatch):
        """Callback basi tidak boleh membuat pengguna terjebak di halaman
        kosong tanpa jalan keluar."""
        monkeypatch.setattr(K, "REGION_DATA", {"DIY": {}})
        buttons = self._buttons(K.get_province_keyboard(99))
        assert any("prov_DIY" == b.callback_data for b in buttons)

    def test_negative_page_is_clamped(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {"DIY": {}})
        buttons = self._buttons(K.get_province_keyboard(-5))
        assert any(b.callback_data == "prov_DIY" for b in buttons)

    def test_callback_data_within_telegram_limit(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {
            "Provinsi Dengan Nama Sangat Panjang Sekali": {}
        })
        for b in self._buttons(K.get_province_keyboard(0)):
            assert len(b.callback_data.encode("utf-8")) <= 64

    def test_empty_region_data(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {})
        assert self._buttons(K.get_province_keyboard(0)) == []


class TestWeatherLocationChoices:
    """Keyboard kandidat untuk /cuaca <lokasi> ambigu."""

    @staticmethod
    def _buttons(markup):
        return [b for row in markup["inline_keyboard"] for b in row]

    @staticmethod
    def _matches(n):
        return [
            {"adm4": f"34.0{i}.09.200{i}", "label": f"Tempat{i}, Kab. X"}
            for i in range(n)
        ]

    def test_two_per_row_like_other_picklists(self):
        markup = K.get_weather_location_choices(self._matches(6))
        rows = markup["inline_keyboard"]
        assert all(len(r) == 2 for r in rows), rows

    def test_callback_data_encodes_the_adm4(self):
        buttons = self._buttons(K.get_weather_location_choices(self._matches(3)))
        assert all(b.callback_data.startswith("wxloc_") for b in buttons)
        assert all(len(b.callback_data.encode("utf-8")) <= 64 for b in buttons)

    def test_candidates_are_capped(self):
        """Tier resolusi bisa memilih banyak kandidat; keyboard harus dibatasi
        supaya tidak menjadi dinding tombol."""
        buttons = self._buttons(
            K.get_weather_location_choices(self._matches(25)))
        assert len(buttons) == K._MAX_LOCATION_CHOICES

    def test_empty_match_list_gives_empty_keyboard(self):
        markup = K.get_weather_location_choices([])
        assert markup["inline_keyboard"] == []


class TestRegencyKeyboard:
    """Lapis kedua pemilih lokasi: provinsi -> kabupaten/kota -> desa."""

    def _buttons(self, markup):
        return [b for row in markup["inline_keyboard"] for b in row]

    def _data_buttons(self, markup):
        return [b for b in self._buttons(markup)
                if b.callback_data and not b.callback_data.startswith(
                    ("kabpage_", "desapage_", "kabback_", "setup_location"))]

    def test_labels_derived_from_desa_labels(self):
        """'Tridadi, Kab. Sleman' harus tampil sebagai 'Kab. Sleman'."""
        labels = {b.text for b in self._data_buttons(K.get_regency_keyboard(
            "DI Yogyakarta"))}
        assert labels == {
            "Kab. Kulon Progo", "Kab. Bantul", "Kab. Gunungkidul",
            "Kab. Sleman", "Kota Yogyakarta",
        }

    def test_kota_prefix_grouped_by_code(self, monkeypatch):
        """Label "Kota X" mandiri (tanpa nama desa) berdiri sendiri sebagai
        nama kotanya, dan dikelompokkan lewat 5 digit pertama kode —
        bukan lewat teks label."""
        monkeypatch.setattr(K, "REGION_DATA", {"DI Yogyakarta": {
            "34.71.04.1003": "Kota Yogyakarta",
        }})
        buttons = self._data_buttons(K.get_desa_keyboard("34.71"))
        assert [b.text for b in buttons] == ["Kota Yogyakarta"]
        assert buttons[0].callback_data == "setloc_34.71.04.1003"

    def test_dki_cities_get_kota_prefix(self):
        """31.71 dst. adalah kota administrasi — label tetap "Kota X"."""
        assert K.regency_map("DKI Jakarta")["31.71"] == "Kota Jakarta Pusat"
        assert K.regency_map("DI Yogyakarta")["34.71"] == "Kota Yogyakarta"

    def test_paginated_when_many_regencies(self, monkeypatch):
        """Jawa Timur punya 38 kabupaten/kota — harus dipagasi, bukan satu
        dinding 38 baris."""
        region = {
            f"35.{i:02d}.01.2001": f"Desa X, Kab. R{i}" for i in range(1, 39)
        }
        monkeypatch.setattr(K, "REGION_DATA", {"Jawa Timur": region})

        page0 = self._buttons(
            K.get_regency_keyboard("Jawa Timur", 0))
        texts = [b.text for b in page0]
        assert "Kab. R1" in texts and "Kab. R10" in texts
        assert "Kab. R11" not in texts
        assert any("Berikutnya" in b.text for b in page0)

        page3 = self._buttons(
            K.get_regency_keyboard("Jawa Timur", 3))
        assert any("Kab. R38" in b.text for b in page3)
        assert not any("Berikutnya" in b.text for b in page3)

    def test_back_to_provinces(self):
        row = K.get_regency_keyboard("DI Yogyakarta")["inline_keyboard"][-1]
        assert row[0].callback_data == "setup_location"
        assert "Provinsi" in row[0].text

    def test_unknown_province_is_empty_but_not_crash(self):
        markup = K.get_regency_keyboard("Provinsi Imajiner")
        assert markup["inline_keyboard"] == []


class TestDesaKeyboard:
    def _buttons(self, markup):
        return [b for row in markup["inline_keyboard"] for b in row]

    def _data_buttons(self, markup):
        return [b for b in self._buttons(markup)
                if b.callback_data and not b.callback_data.startswith(
                    ("desapage_", "kabback_", "kabpage_", "setup_location"))]

    def test_list_only_that_regency(self, monkeypatch):
        monkeypatch.setattr(K, "REGION_DATA", {"DI Yogyakarta": {
            "34.01.01.2001": "A, Kab. Kulon Progo",
            "34.01.02.2001": "B, Kab. Kulon Progo",
            "34.02.01.2001": "C, Kab. Bantul",
        }})
        buttons = self._data_buttons(K.get_desa_keyboard("34.01"))
        assert [b.text for b in buttons] == [
            "A, Kab. Kulon Progo", "B, Kab. Kulon Progo"]
        assert "C" not in {b.text.split(",")[0] for b in buttons}

    def test_callback_data_is_code_only(self):
        """setloc_<kode> = 22 byte; nama di belakang kode bisa mendekati atau
        melampaui anggaran 64 byte Telegram."""
        for b in self._data_buttons(K.get_desa_keyboard("34.01")):
            assert b.callback_data.startswith("setloc_")
            assert "_" not in b.callback_data[len("setloc_"):], b.callback_data
            assert len(b.callback_data.encode("utf-8")) <= 64

    def test_paginated_when_many_desas(self, monkeypatch):
        """35 = Jawa Timur di PROVINCE_MAP; kabupaten pertama Jawa Barat
        diawali 32.01."""
        region = {
            f"32.01.01.{2000 + i}": f"Desa{i}, Kab. X" for i in range(1, 26)
        }
        monkeypatch.setattr(K, "REGION_DATA", {"Jawa Barat": region})

        page0 = self._data_buttons(K.get_desa_keyboard("32.01", 0))
        texts = [b.text for b in page0]
        assert "Desa1, Kab. X" in texts and "Desa10, Kab. X" in texts
        assert "Desa11, Kab. X" not in texts
        assert any("Berikutnya" in b.text for b in self._buttons(
            K.get_desa_keyboard("32.01", 0)))

        page2 = self._data_buttons(K.get_desa_keyboard("32.01", 2))
        assert [b.text for b in page2] == [
            f"Desa{i}, Kab. X" for i in range(21, 26)]
        assert not any("Berikutnya" in b.text for b in self._buttons(
            K.get_desa_keyboard("32.01", 2)))

    def test_back_to_regency_list(self):
        row = K.get_desa_keyboard("34.01")["inline_keyboard"][-1]
        assert row[0].callback_data == "kabback_34.01"
        assert "Kabupaten" in row[0].text

    def test_unknown_regency_gives_empty_keyboard(self):
        markup = K.get_desa_keyboard("99.99")
        assert markup["inline_keyboard"] == []

    def test_page_out_of_range_shows_first_page(self):
        """Callback basi (halaman 9) tidak boleh membuat pengguna terjebak di
        halaman kosong — di-clamp ke halaman yang berisi data."""
        page9 = self._data_buttons(K.get_regency_keyboard("DI Yogyakarta", 9))
        assert {b.text for b in page9} == {
            "Kab. Kulon Progo", "Kab. Bantul", "Kab. Gunungkidul",
            "Kab. Sleman", "Kota Yogyakarta"}
        assert len(self._data_buttons(K.get_desa_keyboard("34.71", 9))) == 5
