"""Perilaku panel admin dan perintah whitelist."""
import asyncio

import pytest

import handlers.admin as A
from tests.aiogram_stub import Message, TelegramBadRequest


class _DB:
    def __init__(self, users=3, whitelisted=()):
        self.users = users
        self.whitelisted = list(whitelisted)
        self.added = []
        self.removed = []
        self.mode = "OPEN"

    async def count_users(self):
        return self.users

    async def get_bot_mode(self):
        return self.mode

    async def set_bot_mode(self, m):
        self.mode = m

    async def get_all_whitelisted(self):
        return [{"chat_id": c, "username": u} for c, u in self.whitelisted]

    async def is_user_whitelisted(self, chat_id):
        return any(c == chat_id for c, _ in self.whitelisted)

    async def add_to_whitelist(self, chat_id):
        self.added.append(chat_id)

    async def remove_from_whitelist(self, chat_id):
        self.removed.append(chat_id)


@pytest.fixture
def db(monkeypatch):
    d = _DB(whitelisted=[(111, "budi"), (222, None)])
    for name in (
        "count_users", "get_bot_mode", "set_bot_mode", "get_all_whitelisted",
        "is_user_whitelisted", "add_to_whitelist", "remove_from_whitelist",
    ):
        monkeypatch.setattr(A, name, getattr(d, name))
    return d


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(A, "ADMIN_ID", 999)
    return 999


@pytest.fixture
def sent():
    out = []

    class Recorder(Message):
        def __init__(self, text=None):
            super().__init__()
            self.text = text
            self.from_user = type("U", (), {"id": 999})()

        async def answer(self, text=None, **kwargs):
            out.append((text, kwargs))
            return self

    return out, Recorder


class TestPanel:
    def test_panel_shows_user_count_and_mode(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_admin_panel(Recorder("/admin")))
        text = out[0][0]
        assert "3" in text and "OPEN" in text

    def test_mode_change_refreshes_panel_in_place(self, db, admin, monkeypatch, sent):
        """Dulu panel diganti dua baris 'Status Diubah ke', sehingga jumlah
        pengguna, daftar mode, dan petunjuk hilang tanpa jalan kembali."""
        db.users = 42
        out, Recorder = sent

        edited = []

        class Cb:
            def __init__(self):
                self.message = type(
                    "M", (),
                    {"edit_text": self._edit},
                )()
                self.from_user = type("U", (), {"id": 999})()
                self.data = "setmode_MAINTENANCE"
                self.answers = []

            async def _edit(self, text=None, **kwargs):
                edited.append((text, kwargs))
                return None

            async def answer(self, *a, **k):
                self.answers.append(a)
                return None

        cb = Cb()
        asyncio.run(A.handle_set_mode(cb))
        assert edited, "panel tidak di-refresh"
        text = edited[0][0]
        assert "42" in text, "jumlah pengguna hilang saat refresh"
        assert "MAINTENANCE" in text
        assert db.mode == "MAINTENANCE"

    def test_identical_message_edit_does_not_raise(self, db, admin, monkeypatch):
        """`message is not modified` melempar exception dan membuat pengguna
        melihat spinner yang tidak selesai."""

        class Cb:
            def __init__(self):
                self.message = type("M", (), {"edit_text": self._edit})()
                self.from_user = type("U", (), {"id": 999})()
                self.data = "setmode_WHITELIST"

            async def _edit(self, text=None, **kwargs):
                raise TelegramBadRequest("message is not modified")

            async def answer(self, *a, **k):
                return None

        asyncio.run(A.handle_set_mode(Cb()))

    def test_non_admin_cannot_change_mode(self, db, monkeypatch):
        monkeypatch.setattr(A, "ADMIN_ID", 1)
        errors = []

        class Cb:
            def __init__(self):
                self.message = None
                self.from_user = type("U", (), {"id": 2})()
                self.data = "setmode_MAINTENANCE"

            async def answer(self, text=None, **kwargs):
                errors.append((text, kwargs))

        asyncio.run(A.handle_set_mode(Cb()))
        assert "ditolak" in errors[0][0].lower()
        assert db.mode == "OPEN"


class TestWhitelist:
    def test_list_shows_entries_and_syntax(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist")))
        text = out[0][0]
        assert "111" in text and "budi" in text
        assert "force" in text

    def test_empty_list_says_so(self, db, admin, monkeypatch, sent):
        db.whitelisted = []
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist")))
        assert "Belum ada" in out[0][0]

    def test_add_existing_user(self, db, admin, monkeypatch, sent):
        async def exists(_id):
            return {"adm_code": "34.01.09.2001"}

        monkeypatch.setattr("database.get_user_info", exists)
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist 123")))
        assert 123 in db.added

    def test_force_actually_works(self, db, admin, monkeypatch, sent):
        """Pesan lama mengajak memakai `/whitelist force [id]`, tapi "force"
        lalu divalidasi sebagai chat_id dan gagal dengan error membingungkan."""
        async def not_exists(_id):
            return None

        monkeypatch.setattr("database.get_user_info", not_exists)
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist force 555")))
        assert 555 in db.added
        assert "berhasil" in out[0][0].lower()

    def test_unknown_user_is_offered_force(self, db, admin, monkeypatch, sent):
        async def not_exists(_id):
            return None

        monkeypatch.setattr("database.get_user_info", not_exists)
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist 777")))
        assert "force" in out[0][0]
        assert 777 not in db.added

    def test_remove_reports_actual_outcome(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist remove 111")))
        assert "dihapus" in out[0][0].lower()

    def test_removing_absent_user_is_not_reported_as_success(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist remove 999")))
        assert "berhasil" not in out[0][0].lower()
        assert "tidak ada" in out[0][0].lower()

    def test_non_word_chat_id_rejected(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist abc")))
        assert "valid" in out[0][0].lower()
        assert db.added == []

    def test_bare_force_is_rejected_clearly(self, db, admin, sent):
        out, Recorder = sent
        asyncio.run(A.cmd_whitelist(Recorder("/whitelist force")))
        assert "format" in out[0][0].lower()
