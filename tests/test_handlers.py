"""Perilaku handler yang tidak butuh Telegram sungguhan.

Dijalankan terhadap stub aiogram (lihat tests/aiogram_stub.py) plus double
untuk `database`. Fokusnya adalah hal yang salahsunggulan rasakan pengguna:
petunjuk yang mengarah ke tempat yang salah, pesan yang terkirim dua kali, dan
panel yang kehilangan konteksnya.
"""
import asyncio

import pytest

import handlers.user as U
from tests.aiogram_stub import Message, TelegramAPIError, TelegramBadRequest


class _DB:
    """Double untuk fungsi database yang dipakai handler."""

    def __init__(self, user=None, prefs=None, mode="OPEN"):
        self.user = user or {"adm_code": None, "adm_name": None}
        self.prefs = prefs or {}
        self.mode = mode
        self.whitelisted = False
        self.location_updated = None

    async def get_user_info(self, _chat_id):
        return self.user

    async def get_user_prefs(self, _chat_id):
        return self.prefs

    async def get_bot_mode(self):
        return self.mode

    async def is_user_whitelisted(self, _chat_id):
        return self.whitelisted

    async def update_user_location(self, _uid, adm_code, adm_name):
        self.location_updated = (adm_code, adm_name)

    async def add_user(self, *a):
        return None


@pytest.fixture
def db(monkeypatch):
    d = _DB()
    for name in (
        "get_user_info", "get_user_prefs", "get_bot_mode",
        "is_user_whitelisted", "update_user_location", "add_user",
    ):
        monkeypatch.setattr(U, name, getattr(d, name))
    return d


@pytest.fixture
def sent(monkeypatch):
    """Kumpulkan pesan yang benar-benar dikirim handler."""
    out = []

    class Recorder(Message):
        def __init__(self, text=None):
            super().__init__()
            self.text = text
            self.replies = []

        async def answer(self, text=None, **kwargs):
            self.replies.append((text, kwargs))
            out.append((text, kwargs))
            return self

    return out, Recorder


class TestWelcome:
    def test_first_run_asks_for_location(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_start(Recorder("/start")))
        text = out[0][0]
        assert "mengatur lokasi" in text.lower()
        assert out[0][1].get("reply_markup")

    def test_returning_user_sees_current_location(self, db, sent):
        """Dulu /start selaluulang pesan sama, sehingga tidak menjawab
        'lokasi saya di mana?'."""
        out, Recorder = sent
        db.user = {"adm_code": "34.01.09.2001", "adm_name": "Jatimulyo"}
        asyncio.run(U.cmd_start(Recorder("/start")))
        assert "Jatimulyo" in out[0][0]
        assert "langkah berikutnya" not in out[0][0].lower()

    def test_maintenance_message_for_non_admin(self, db, sent):
        out, Recorder = sent
        db.mode = "MAINTENANCE"
        asyncio.run(U.cmd_start(Recorder("/start")))
        assert "pemeliharaan" in out[0][0].lower()

    def test_whitelist_gate_for_non_admin(self, db, sent):
        out, Recorder = sent
        db.mode = "WHITELIST"
        db.whitelisted = False
        asyncio.run(U.cmd_start(Recorder("/start")))
        assert "whitelist" in out[0][0].lower()


class TestLocationGate:
    def test_weather_without_location_offers_a_button(self, db, sent):
        """Tiga handler mencetak instruksi yang sama tanpa tombol; ini
        seharusnya jadi satu ketukan."""
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca")))
        assert out[0][1].get("reply_markup"), "tidak ada tombol untuk mengatur lokasi"

    def test_location_message_names_the_problem(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_extended_forecast(Recorder("/prakiraan")))
        assert "belum diatur" in out[0][0]

    def test_hourly_without_location_gated(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_hourly_today(Recorder("/per_jam")))
        assert "belum diatur" in out[0][0]

    def test_nowcast_without_location_gated(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_nowcast(Recorder("/nowcast")))
        assert "belum diatur" in out[0][0]

    def test_no_command_points_at_wrong_command(self, db, sent):
        """Pesan lama mengarahkan ke /atur_notif, yang tidak bisa mengatur
        lokasi sama sekali."""
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca")))
        assert "/atur_notif" not in out[0][0]


class _WeatherStub:
    """Rekam kode adm4 yang diminta, dan jawab payload cuaca palsu."""

    def __init__(self, monkeypatch):
        self.calls = []
        import handlers.user as U

        async def fake_fetch(adm_code):
            self.calls.append(adm_code)
            return {"data": "stub"}

        async def fake_parse(raw):
            return {"text": "🌤️ <b>CUACA SAAT INI</b>", "photo_url": None}

        monkeypatch.setattr(U, "fetch_weather_data", fake_fetch)
        monkeypatch.setattr(U, "parse_weather_current", fake_parse)


class TestCuacaArgument:
    """/cuaca <lokasi> → cuaca untuk lokasi itu tanpa menyimpannya."""

    def test_argument_queries_that_location_by_code(self, db, sent, monkeypatch):
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca Wates")))
        assert stub.calls == ["34.01.02.2001"], "harus memakai kode adm4 pustaka"
        assert any("CUACA SAAT INI" in t for t, _ in out)

    def test_argument_does_not_touch_saved_location(self, db, sent, monkeypatch):
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca wonosari")))
        assert stub.calls, "harus mem-fetch lokasi yang diketik"
        assert db.location_updated is None, "lokasi tersimpan tidak boleh berubah"

    def test_argument_works_without_saved_location(self, db, sent, monkeypatch):
        """/cuaca wonosari tanpa lokasi tersimpan tetap menjawab, bukan
        menampilkan pemilih lokasi."""
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca wonosari")))
        assert stub.calls, "argumen tidak boleh butuh lokasi tersimpan"
        assert not any("belum diatur" in t for t, _ in out)

    def test_botname_suffix_is_stripped_from_command(self, db, sent, monkeypatch):
        """`/cuaca@BotName wates` tetap harus dikenali (bot di grup)."""
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca@CuacaBot wates")))
        assert stub.calls == ["34.01.02.2001"]

    def test_unknown_location_says_no_with_examples(self, db, sent, monkeypatch):
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca jakarta")))
        assert not stub.calls, "lokasi di luar pustaka tidak boleh di-fetch"
        text = out[0][0]
        assert "tidak tersedia" in text.lower()
        assert "Yogyakarta" in text, "cakupan harus disebut jujur"
        assert "/lokasi" in text, "arahkan ke pemilih lokasi"

    def test_unknown_location_echoes_query_escaped(self, db, sent, monkeypatch):
        """Gema ketikan pengguna harus di-esc — `<b>` mentah dalam jawaban
        berarti teks pengguna bisa menyuntik entitas HTML."""
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca <b>bold</b>")))
        text = out[0][0]
        assert "<b>bold</b>" not in text
        assert "&lt;b&gt;bold&lt;/b&gt;" in text

    def test_ambiguous_query_offers_button_candidates(self, db, sent, monkeypatch):
        stub = _WeatherStub(monkeypatch)
        out, Recorder = sent
        asyncio.run(U.cmd_current_weather(Recorder("/cuaca kulon progo")))
        assert not stub.calls, "ambigu tidak boleh dipilih secara diam-diam"
        markup = out[0][1].get("reply_markup")
        assert markup is not None, "harus menawarkan tombol kandidat"
        buttons = [b for row in markup["inline_keyboard"] for b in row]
        datas = [b.callback_data for b in buttons]
        assert set(datas) == {"wxloc_34.01.09.2001", "wxloc_34.01.02.2001"}
        texts = [b.text for b in buttons]
        assert "Jatimulyo, Kab. Kulon Progo" in texts
        assert "Wates, Kab. Kulon Progo" in texts

    def test_callback_sends_weather_and_clears_choices(self, db, sent, monkeypatch):
        from types import SimpleNamespace
        stub = _WeatherStub(monkeypatch)

        class Msg:
            def __init__(self):
                self.chat = SimpleNamespace(id=1)
                self.replies = []
                self.edits = []

            async def answer(self, text=None, **kwargs):
                self.replies.append((text, kwargs))
                return self

            async def edit_text(self, text=None, **kwargs):
                self.edits.append((text, kwargs))
                return self

        class Cb:
            def __init__(self, data, msg):
                self.data = data
                self.message = msg
                self.toasts = []

            async def answer(self, text=None, **kwargs):
                self.toasts.append((text, kwargs))
                return None

        msg = Msg()
        cb = Cb("wxloc_34.01.02.2001", msg)
        asyncio.run(U.handle_weather_location_choice(cb))
        assert stub.calls == ["34.01.02.2001"]
        assert any("✅" in t for t, _ in msg.edits), (
            "daftar kandidat harus diganti konfirmasi (keyboard ikut hilang)")
        assert any(t and "Mengambil" in t for t, _ in cb.toasts), (
            "spinner harus dijawab dengan toast proses")

    def test_callback_rejects_code_outside_library(self, db, sent, monkeypatch):
        """"Keyboard basi atau callback_data yang di-craft tidak boleh
        menjadikan bot proxy lokasi di luar cakupan."""
        from types import SimpleNamespace
        stub = _WeatherStub(monkeypatch)

        class Msg:
            def __init__(self):
                self.chat = SimpleNamespace(id=1)
                self.replies = []
                self.edits = []

            async def answer(self, text=None, **kwargs):
                self.replies.append((text, kwargs))
                return self

            async def edit_text(self, text=None, **kwargs):
                self.edits.append((text, kwargs))
                return self

        class Cb:
            def __init__(self, data, msg):
                self.data = data
                self.message = msg
                self.toasts = []

            async def answer(self, text=None, **kwargs):
                self.toasts.append((text, kwargs))
                return None

        msg = Msg()
        cb = Cb("wxloc_31.75.03.1001", msg)
        asyncio.run(U.handle_weather_location_choice(cb))
        assert not stub.calls, "kode asing tidak boleh diteruskan ke API"
        assert not msg.edits, "tidak ada konfirmasi untuk kode asing"
        assert any(t and "dikenal" in t for t, _ in cb.toasts)

    def test_callback_gated_during_maintenance(self, db, sent, monkeypatch):
        """"Keyboard lama (sebelum pemeliharaan) tidak boleh tetap menyerahkan
        data saat bot MAINTENANCE."""
        from types import SimpleNamespace
        stub = _WeatherStub(monkeypatch)
        db.mode = "MAINTENANCE"

        class Msg:
            def __init__(self):
                self.chat = SimpleNamespace(id=1)
                self.replies = []
                self.edits = []

            async def answer(self, text=None, **kwargs):
                self.replies.append((text, kwargs))
                return self

            async def edit_text(self, text=None, **kwargs):
                self.edits.append((text, kwargs))
                return self

        class Cb:
            def __init__(self, data, msg):
                self.data = data
                self.message = msg
                self.toasts = []

            async def answer(self, text=None, **kwargs):
                self.toasts.append((text, kwargs))
                return None

        msg = Msg()
        asyncio.run(U.handle_weather_location_choice(
            Cb("wxloc_34.01.02.2001", msg)))
        assert not stub.calls, "pemeliharaan harus memblokir jalur tombol juga"
        assert not msg.edits
        assert any(t and "pemeliharaan" in t.lower() for t, _ in msg.replies)


class TestHelpAndLocationCommands:
    def test_help_lists_new_command_names(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_help(Recorder("/bantuan")))
        text = out[0][0]
        for cmd in ("/cuaca", "/per_jam", "/prakiraan", "/lokasi", "/notifikasi"):
            assert cmd in text

    def test_location_command_offers_province_picker(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_location(Recorder("/lokasi")))
        assert out[0][1].get("reply_markup")


class TestLegacyHint:
    def test_new_name_produces_no_hint(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_notif_preferences(Recorder("/notifikasi")))
        assert len(out) == 1
        assert "kini" not in out[0][0]

    def test_old_name_gets_a_hint(self, db, sent):
        out, Recorder = sent
        asyncio.run(U.cmd_notif_preferences(Recorder("/atur_notif")))
        assert any("/notifikasi" in t for t, _ in out)

    def test_old_hourly_name_gets_a_hint(self, db, sent):
        db.user = {"adm_code": None, "adm_name": None}
        out, Recorder = sent
        asyncio.run(U.cmd_hourly_today(Recorder("/cuaca_hari_ini")))
        assert any("/per_jam" in t for t, _ in out)


class TestPhotoFallback:
    """Bug: fallback lebar `except Exception` mengirim ulang teks bahkan ketika
    foto sebenarnya sudah terkirim, sehingga pengguna menerima isi dua kali."""

    def _msg(self, sent):
        out, Recorder = sent

        class PhotoMsg(Recorder):
            def __init__(self, text=None):
                super().__init__(text)
                self.photo_attempts = 0

            async def answer_photo(self, photo=None, caption=None, **kwargs):
                self.photo_attempts += 1
                # Di aiogram asli ini TelegramNetworkError, subclass dari
                # TelegramAPIError — seperti TelegramBadRequest, tapi berbeda
                #cabang penanganan.
                raise TelegramAPIError("network reset")

        return out, PhotoMsg

    def test_transport_error_does_not_resend_content(self, db, sent):
        """Kegagalan jaringan: mungkin pesan sudah sampai. Mengirim ulang
        berisiko duplikat, jadi pengguna diberi tahu untuk mencoba lagi."""
        out, PhotoMsg = self._msg(sent)
        asyncio.run(U._reply_weather(PhotoMsg("/cuaca"), "CUACA PANTAS", "p.jpg"))
        assert out
        assert all("CUACA PANTAS" not in t for t, _ in out)

    def test_bad_request_falls_back_to_text(self, db, sent):
        """Telegram menolak berarti tidak ada yang terkirim — aman kirim teks."""
        out, PhotoMsg = self._msg(sent)
        original = PhotoMsg.answer_photo

        async def reject(self, photo=None, caption=None, **kwargs):
            self.photo_attempts = getattr(self, "photo_attempts", 0) + 1
            raise TelegramBadRequest("can't parse entities")

        PhotoMsg.answer_photo = reject
        try:
            asyncio.run(U._reply_weather(PhotoMsg("/cuaca"), "CUACA PANTAS", "p.jpg"))
        finally:
            PhotoMsg.answer_photo = original

        assert any("CUACA PANTAS" in t for t, _ in out)

    def test_over_length_caption_skips_the_photo(self, db, sent):
        out, PhotoMsg = self._msg(sent)
        msg = PhotoMsg("/cuaca")
        asyncio.run(U._reply_weather(msg, "x" * (U._CAPTION_LIMIT + 10), "p.jpg"))
        assert getattr(msg, "photo_attempts", 0) == 0
        assert out

    def test_no_photo_sends_text_directly(self, db, sent):
        out, Recorder = sent
        asyncio.run(U._reply_weather(Recorder("/cuaca"), "TEKS", None))
        assert out[0][0] == "TEKS"


class TestPing:
    """`/ping` membaca status dari `health_server.get_health()` — sumber yang
    sama dengan `/healthz` dan `/metrics`.

    Versi lama mengklaim "Semua sistem berjalan normal" tanpa memeriksa
    apa pun, jadi paling percaya diri justru saat ada yang rusak.
    """

    @pytest.fixture
    def health(self, monkeypatch):
        """Kendalikan hasil pemeriksaan kesehatan."""
        import health_server

        state = {"db": True, "bmkg": True}

        async def db_check():
            return state["db"]

        async def bmkg_check():
            return state["bmkg"]

        monkeypatch.setattr(health_server, "_db_check_fn", db_check)
        monkeypatch.setattr(health_server, "_bmkg_check_fn", bmkg_check)
        return state

    def test_healthy_system_says_so(self, db, sent, health):
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert "Semua sistem normal" in out[0][0]

    def test_db_failure_is_reported(self, db, sent, health):
        health["db"] = False
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        text = out[0][0]
        assert "Semua sistem normal" not in text
        assert "database tidak dapat diakses" in text

    def test_bmkg_failure_is_reported(self, db, sent, health):
        """Dulu /ping tidak punya jalur ini sama sekali."""
        health["bmkg"] = False
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert "BMKG tidak dapat dihubungi" in out[0][0]

    def test_both_failures_both_listed(self, db, sent, health):
        health["db"] = False
        health["bmkg"] = False
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        text = out[0][0]
        assert "database tidak dapat diakses" in text
        assert "BMKG tidak dapat dihubungi" in text

    def test_ping_is_awaited_inside_the_event_loop(self, db, sent, health):
        """Regression: /ping memakai `get_health()` yang memanggil
        `asyncio.run()`, yang melempar di dalam loop bot. Akibatnya /ping selalu
        melaporkan 'degraded' dan tidak pernah benar-benar memeriksa apa pun."""
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert "Semua sistem normal" in out[0][0], (
            "checker tidak dijalankan — kemungkinan besar asyncio.run() "
            "dipanggil dari dalam event loop"
        )

    def test_health_failure_never_breaks_ping(self, db, sent, monkeypatch):
        """Memeriksa kesehatan tidak boleh menjadi alasan /ping gagal."""
        import health_server

        def boom():
            raise RuntimeError("checker exploded")

        monkeypatch.setattr(health_server, "get_health", boom)
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert out, "/ping tidak membalas sama sekali saat health check error"
        assert "PONG" in out[0][0]

    def test_uptime_uses_unambiguous_seconds_label(self, db, sent, health):
        """"N detik" dipakai 'd', yang terbaca sebagai hari di bahasa lain."""
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert "dtk" in out[0][0]

    def test_missing_location_shown_as_dash_not_none(self, db, sent, health):
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert "None" not in out[0][0]

    def test_uses_the_shared_health_source(self, db, sent, monkeypatch):
        """/ping tidak boleh punya pemeriksaan kesehatan sendiri — itulah yang
        membuatnya menyimpang dari /healthz."""
        import health_server

        calls = []

        async def fake():
            calls.append(1)
            return {"status": "ok", "db": True, "bmkg_reachable": True}

        monkeypatch.setattr(health_server, "get_health_async", fake)
        out, Recorder = sent
        asyncio.run(U.cmd_ping(Recorder("/ping")))
        assert calls, "/ping tidak membaca health_server.get_health_async()"
