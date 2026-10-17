"""Broadcast: batas panjang, degradasi foto, dan isi pesan.

Bot ini mengirim peringatan lewat `bot.send_photo` dengan caption. Telegram
menolak caption lebih dari 1024 karakter alih-alih memotongnya, dan penolakan
itu tidak terlihat di laporan broadcast: kegagalannya ada di lapisan Telegram,
sedangkan `check_quake_job` menghitung hasil pemanggilan. Akibatnya admin
melihat "0 gagal" sementara peringatan tidak pernah sampai ke pengguna.
"""
import asyncio

import pytest

import main as M
from utils.design import CAPTION_LIMIT


class _FakeBot:
    """Merekam apa yang benar-benar dikirim."""

    def __init__(self):
        self.photos = []
        self.messages = []
        self.fail_photo = False

    async def send_photo(self, chat_id, photo=None, caption=None, parse_mode=None):
        if self.fail_photo:
            raise RuntimeError("telegram rejected")
        self.photos.append((chat_id, photo, caption, parse_mode))

    async def send_message(self, chat_id, text, parse_mode=None):
        self.messages.append((chat_id, text, parse_mode))


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    """Cegah antrean retry dan penghapusan baris menyentuh SQLite sungguhan."""
    queued = []

    async def fake_enqueue(chat_id, message, photo_url=None):
        queued.append((chat_id, message, photo_url))

    async def fake_delete(_send_id):
        return None

    monkeypatch.setattr(M, "enqueue_failed_send", fake_enqueue)
    monkeypatch.setattr(M, "delete_pending_send", fake_delete)
    return queued


class TestPhotoSend:
    def test_over_length_caption_falls_back_to_text(self):
        bot = _FakeBot()
        long_caption = "x" * (CAPTION_LIMIT + 200)
        ok = asyncio.run(M._send_photo_sem(bot, 1, "p.jpg", long_caption))
        assert ok is True
        assert bot.photos == []
        assert bot.messages[0][1] == long_caption

    def test_caption_at_the_limit_still_ships_as_photo(self):
        bot = _FakeBot()
        exact = "x" * CAPTION_LIMIT
        asyncio.run(M._send_photo_sem(bot, 1, "p.jpg", exact))
        assert bot.photos and bot.photos[0][2] == exact

    def test_html_parse_mode_used(self):
        bot = _FakeBot()
        asyncio.run(M._send_photo_sem(bot, 1, "p.jpg", "<b>halo</b>"))
        assert bot.photos[0][3] == "HTML"

    def test_failure_queues_for_retry(self, no_db):
        bot = _FakeBot()
        bot.fail_photo = True
        ok = asyncio.run(M._send_photo_sem(bot, 42, "p.jpg", "halo"))
        assert ok is False
        assert no_db and no_db[0][0] == 42

    def test_semaphore_is_released_after_over_length_fallback(self):
        """Fallbackholding _SEND_SEM lalu memanggil helper yang ikut mengambil
        sem would deadlock; the refactor extracted a _locked variant to
        avoid re-acquiring."""
        bot = _FakeBot()
        asyncio.run(M._send_photo_sem(bot, 1, "p.jpg", "y" * (CAPTION_LIMIT + 1)))
        assert not M._SEND_SEM.locked()


class TestRetryPath:
    def test_retry_downgrades_over_length_photo_to_text(self, no_db):
        bot = _FakeBot()
        long_caption = "z" * (CAPTION_LIMIT + 50)
        ok = asyncio.run(M._retry_send(bot, 7, 1, "p.jpg", long_caption))
        assert ok is True
        assert bot.photos == []
        assert bot.messages and bot.messages[0][1] == long_caption

    def test_retry_keeps_photo_when_it_fits(self, no_db):
        bot = _FakeBot()
        ok = asyncio.run(M._retry_send(bot, 7, 1, "p.jpg", "pendek"))
        assert ok is True
        assert bot.photos and bot.photos[0][2] == "pendek"
