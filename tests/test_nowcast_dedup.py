"""Dedup nowcast: identifier, jeda pengulangan, dan eskalasi severity.

Insiden yang memicu file ini: peringatan yang sama terkirim dua kali
berjarak 30-50 menit. Penyebabnya, BMKG menerbitkan ulang peringatan serupa
sebagai CAP BARU — identifier segar per siklus nowcast (CYG...002 lalu
CYG...003 hidup bareng di RSS) — sementara dedup lama kunci `cap_<id>`
per-alert-id dan menaruh ceknya DI DALAM loop user (user pertama urutan
query menulis key global; user lain di provinsi yang sama tidak pernah
menerima peringatan itu sama sekali).
"""
import asyncio
import time

import pytest

import database as DB
import main as M
from fixtures.bmkg import cap_alert_xml, nowcast_rss

NOW = int(time.time())
PROV = {"34.01.09.2001": "DI Yogyakarta"}
LINKO99A = "https://www.bmkg.go.id/cap/002"
LINKO99B = "https://www.bmkg.go.id/cap/003"
FP = "DI Yogyakarta|Hujan Lebat dan Petir"


class _FakeBot:
    def __init__(self):
        self.photos = []
        self.messages = []

    async def send_photo(self, chat_id, photo=None, caption=None, parse_mode=None):
        self.photos.append((chat_id, caption))

    async def send_message(self, chat_id, text, parse_mode=None):
        self.messages.append((chat_id, text))


class _FakeStore:
    """Config table tiruan: key → value string, perilaku identik dengan SQL."""

    def __init__(self):
        self.keys = {}
        self.stamped = []

    async def mark_alert_seen(self, key_name, ts=None):
        if key_name in self.keys:
            return False
        self.keys[key_name] = str(int(ts) if ts is not None else NOW)
        return True

    async def get_last_nowcast(self, chat_id, fingerprint):
        value = self.keys.get(f"cap_last_{chat_id}_{fingerprint}")
        if value is None:
            return None
        ts_text, _, rank_text = value.partition(":")
        return int(ts_text), int(rank_text)

    async def stamp_last_nowcast(self, chat_id, fingerprint, ts, rank):
        key = f"cap_last_{chat_id}_{fingerprint}"
        self.keys[key] = f"{int(ts)}:{int(rank)}"
        self.stamped.append((chat_id, fingerprint, int(ts), int(rank)))

    def seed(self, chat_id, fingerprint, minutes_ago, rank):
        self.keys[f"cap_last_{chat_id}_{fingerprint}"] = f"{NOW - minutes_ago * 60}:{rank}"

    async def cleanup_old_alerts(self, cutoff_ts):
        self.keys = {
            k: v for k, v in self.keys.items()
            if not (k.startswith("cap_") and int(v.split(":")[0]) < cutoff_ts)
        }


def _alert(identifier, severity="Moderate", link=LINKO99A):
    return {
        "rss": nowcast_rss(
            titles=["Hujan Lebat disertai Petir di DI Yogyakarta"],
            links=[link],
        ),
        "cap_by_link": {
            link: cap_alert_xml(
                identifier=identifier,
                sent=f"2026-10-27T15:00:00+07:00",
                severity=severity,
            )
        },
    }


@pytest.fixture
def wiring(monkeypatch):
    state = _alert("id-1")
    store = _FakeStore()
    bot = _FakeBot()
    users = [{"chat_id": 1, "adm_code": "34.01.09.2001"}]

    async def fake_rss():
        return state["rss"]

    async def fake_users(_pref):
        return users

    async def fake_detail(link):
        return state["cap_by_link"].get(link)

    monkeypatch.setattr(M, "fetch_nowcast_alerts", fake_rss)
    monkeypatch.setattr(M, "get_users_with_pref", fake_users)
    monkeypatch.setattr(M, "fetch_alert_detail", fake_detail)
    monkeypatch.setattr(M, "get_province_name", lambda code: PROV.get(code))
    monkeypatch.setattr(M, "record_bmkg_success", lambda *_: None)
    monkeypatch.setattr(M, "record_bmkg_failure", lambda *_: False)
    monkeypatch.setattr(M, "mark_alert_seen", store.mark_alert_seen)
    monkeypatch.setattr(M, "get_last_nowcast", store.get_last_nowcast)
    monkeypatch.setattr(M, "stamp_last_nowcast", store.stamp_last_nowcast)
    return state, store, bot, users


def _sent_count(bot):
    return len(bot.photos) + len(bot.messages)


class TestIdentifierDedup:
    def test_same_identifier_sent_once(self, wiring):
        state, store, bot, _ = wiring
        asyncio.run(M.nowcast_alert_job(bot))
        first = _sent_count(bot)
        assert first == 1

        # Run kedua masih (atau lagi) menyimpan CAP yang sama persis.
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == first

    def test_two_users_same_province_both_receive(self, wiring):
        """Key dedup tidak boleh per-alert-id global: user kedua tidak
        kehilangan peringatan hanya karena user pertama mendahuluinya."""
        state, store, bot, users = wiring
        users.append({"chat_id": 2, "adm_code": "34.01.09.2001"})
        asyncio.run(M.nowcast_alert_job(bot))
        recipients = {c for c, _ in bot.messages + bot.photos}
        assert recipients == {1, 2}

    def test_alert_without_identifier_never_sent(self, wiring):
        state, store, bot, _ = wiring
        state["cap_by_link"][LINKO99A] = cap_alert_xml(identifier="")
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 0


class TestRepeatCooldown:
    def test_reissue_within_cooldown_suppressed_and_never_fires_later(self, wiring):
        state, store, bot, _ = wiring
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 1

        # BMKG terbit CYG...003: identifier baru, konten serupa.
        state.update(_alert("id-2", link=LINKO99B))
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 1

        # Ditandai sudah-lihat meski ditekan — tidak boleh muncul belakangan
        # setelah jeda habis, ketika itemnya masih tertitip di RSS.
        assert f"cap_1_id-2" in store.keys

    def test_reissue_after_cooldown_sent(self, wiring):
        state, store, bot, _ = wiring
        asyncio.run(M.nowcast_alert_job(bot))
        store.seed(1, FP, minutes_ago=M.NOWCAST_COOLDOWN_MIN + 10, rank=2)

        state.update(_alert("id-2", link=LINKO99B))
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 2

    def test_escalation_bypasses_cooldown(self, wiring):
        state, store, bot, _ = wiring
        asyncio.run(M.nowcast_alert_job(bot))  # Moderate (rank 2)
        assert _sent_count(bot) == 1

        # Peringatan berikutnya lebih parah: Severe (rank 3).
        state.update(_alert("id-2", severity="Severe", link=LINKO99B))
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 2

    def test_severity_rank_stamped(self, wiring):
        state, store, bot, _ = wiring
        state.update(_alert("id-2", severity="Severe", link=LINKO99B))
        asyncio.run(M.nowcast_alert_job(bot))
        assert bot.messages or bot.photos
        assert store.keys[f"cap_last_1_{FP}"].endswith(":3") or store.stamped[-1][3] == 3


class TestSameRunBurst:
    def test_only_newest_sent_when_two_editions_coexist(self, wiring):
        """RSS riil menampung CYG...002 dan CYG...003 bersamaan: satu run
        tidak boleh mengirim dua peringatan provinsi yang sama."""
        state, store, bot, _ = wiring
        state["rss"] = nowcast_rss(
            titles=["Hujan Lebat disertai Petir di DI Yogyakarta"] * 2,
            links=[LINKO99A, LINKO99B],
        )
        state["cap_by_link"] = {
            LINKO99A: cap_alert_xml(
                identifier="id-old", sent="2026-10-27T13:00:00+07:00",
                effective="2026-10-27T13:10:00+07:00", expires="2026-10-27T15:00:00+07:00",
            ),
            LINKO99B: cap_alert_xml(
                identifier="id-new", sent="2026-10-27T15:00:00+07:00",
            ),
        }
        asyncio.run(M.nowcast_alert_job(bot))
        assert _sent_count(bot) == 1
        # Yang terkirim edisi terbaru (15:10, bukan 13:10) di header 🕒.
        caption = (bot.messages or bot.photos)[0][1]
        assert "15:10" in caption and "13:10" not in caption
        # Edisi lama ditandai sudah-lihat: tidak menggantung untuk run lain.
        assert "cap_1_id-old" in store.keys


class TestLegacyCleanup:
    """cleanup_old_alerts memangkas berdasar umur, bukan kalender."""

    def test_marks_and_prunes_by_age(self, monkeypatch, tmp_path):
        monkeypatch.setattr(DB, "DB_PATH", str(tmp_path / "t.db"))
        DB._db_connection = None  # singleton proses — reset untuk file baru

        async def scenario():
            await DB.init_db()
            now = int(time.time())
            assert await DB.mark_alert_seen("cap_1_fresh", ts=now) is True
            assert await DB.mark_alert_seen("cap_1_stale", ts=now - 30 * 86400) is True
            await DB.stamp_last_nowcast(1, "p|e", now, 2)
            await DB.update_metadata("bot_mode", "OPEN")  # bukan key cap_*
            await DB.cleanup_old_alerts()
            db = await DB.get_db()
            cursor = await db.execute("SELECT key FROM config")
            rows = {r[0] for r in await cursor.fetchall()}
            await cursor.close()
            return rows

        rows = asyncio.run(scenario())
        assert "cap_1_fresh" in rows
        assert "cap_last_1_p|e" in rows
        assert "cap_1_stale" not in rows
        assert "bot_mode" in rows

        DB._db_connection = None
