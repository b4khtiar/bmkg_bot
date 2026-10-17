"""Endpoint kesehatan.

`/metrics` dulu melaporkan `1 if _db_check_fn` — yaitu "1" begitu checker
terdaftar, tidak pernah hasil sebenarnya. Jadi selama database mati, Prometheus
melihat `bmkg_bot_db_healthy 1`. Bug-nya persis di tempat yang seharusnya
menangkap kegagalan.
"""
import asyncio
import os
import time
import urllib.request

import pytest

import health_server as H


@pytest.fixture(autouse=True)
def clean_checkers():
    H._set_checkers(None, None)
    yield
    H._set_checkers(None, None)


def _register(db, bmkg):
    async def db_check():
        if isinstance(db, Exception):
            raise db
        return db

    H._set_checkers(db_check, lambda: (_ for _ in ()).throw(bmkg)
                    if isinstance(bmkg, Exception) else bmkg)


class TestGetHealth:
    def test_healthy(self):
        _register(True, True)
        assert H.get_health() == {
            "status": "ok", "db": True, "bmkg_reachable": True,
            "uptime_seconds": H.get_health()["uptime_seconds"],
        }

    def test_reports_real_failures(self):
        _register(False, False)
        h = H.get_health()
        assert h["status"] == "degraded"
        assert h["db"] is False
        assert h["bmkg_reachable"] is False

    def test_raising_checkers_become_false(self):
        _register(RuntimeError("db gone"), RuntimeError("no network"))
        h = H.get_health()
        assert h["db"] is False and h["bmkg_reachable"] is False

    def test_one_failure_does_not_hide_the_other(self):
        _register(True, False)
        h = H.get_health()
        assert h["db"] is True
        assert h["bmkg_reachable"] is False

    def test_missing_checkers_are_not_ok(self):
        """Tidak mendaftarkan checker bukan berarti sehat."""
        assert H.get_health()["status"] == "degraded"


class TestGetHealthAsync:
    """`get_health()` memakai asyncio.run(), yang melempar di dalam loop."""

    def test_works_inside_a_running_loop(self):
        _register(True, True)

        async def main():
            return await H.get_health_async()

        assert asyncio.run(main())["status"] == "ok"

    def test_sync_variant_inside_a_loop_silently_lies(self):
        """Dokumentasikan alasan varian async ada.

        `get_health()` menelan error checker dengan sengaja (checker yang rusak
        tidak boleh menggagalkan endpoint), jadi di dalam loop ia tidak crash —
        ia justru melaporkan `degraded` padahal semua sehat. Justru itu bug-nya:
        tidak pernah benar-benar memeriksa apa pun, tapi tetap bersuara.
        """
        _register(True, True)

        async def main():
            return H.get_health()

        assert asyncio.run(main())["status"] == "degraded"


@pytest.fixture
def server():
    port = 18081
    os.environ["HEALTH_SERVER_PORT"] = str(port)
    H.start_health_server()
    time.sleep(0.4)
    yield f"http://127.0.0.1:{port}"
    H.stop_health_server()


class TestEndpoints:
    def test_healthz_reports_failure(self, server):
        _register(False, True)
        import json
        body = json.loads(urllib.request.urlopen(f"{server}/healthz").read())
        assert body["db"] is False
        assert body["status"] == "degraded"

    def test_metrics_reports_real_db_state(self, server):
        """Regression: `1 if _db_check_fn` melaporkan sehat apa pun hasilnya."""
        _register(False, True)
        body = urllib.request.urlopen(f"{server}/metrics").read().decode()
        assert "bmkg_bot_db_healthy 0" in body
        assert "bmkg_bot_bmkg_reachable 1" in body

    def test_metrics_reports_healthy_when_healthy(self, server):
        _register(True, True)
        body = urllib.request.urlopen(f"{server}/metrics").read().decode()
        assert "bmkg_bot_db_healthy 1" in body
        assert "bmkg_bot_bmkg_reachable 1" in body

    def test_metrics_and_healthz_agree(self, server):
        """Tiga tampilan status harus berasal dari satu sumber."""
        import json
        _register(False, False)
        health = json.loads(urllib.request.urlopen(f"{server}/healthz").read())
        metrics = urllib.request.urlopen(f"{server}/metrics").read().decode()
        expected_db = 1 if health["db"] else 0
        expected_bmkg = 1 if health["bmkg_reachable"] else 0
        assert f"bmkg_bot_db_healthy {expected_db}" in metrics
        assert f"bmkg_bot_bmkg_reachable {expected_bmkg}" in metrics

    def test_unknown_path_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{server}/nope")
        assert exc.value.code == 404
