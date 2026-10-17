"""Endpoint kesehatan.

`/metrics` dulu melaporkan `1 if _db_check_fn` — yaitu "1" begitu checker
terdaftar, tidak pernah hasil sebenarnya. Jadi selama database mati, Prometheus
melihat `bmkg_bot_db_healthy 1`. Bug-nya persis di tempat yang seharusnya
menangkap kegagalan.
"""
import asyncio
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

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

    async def bmkg_check():
        if isinstance(bmkg, Exception):
            raise bmkg
        return bmkg

    H._set_checkers(db_check, bmkg_check)


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

    def test_async_checkers_are_actually_awaited(self):
        """Regression: dulu `_check_bmkg_sync()` memanggil checker tanpa
        await. Coroutine yang belum dijalankan bukan falsy, jadi checker
        async yang gagal dilaporkan sehat."""
        _register(False, False)

        async def main():
            return await H.get_health_async()

        h = asyncio.run(main())
        assert h["db"] is False
        assert h["bmkg_reachable"] is False


class TestGetHealthAsync:
    """`get_health()` memakai asyncio.run(), yang melempar di dalam loop."""

    def test_works_inside_a_running_loop(self):
        _register(True, True)

        async def main():
            return await H.get_health_async()

        assert asyncio.run(main())["status"] == "ok"

    def test_sync_variant_inside_a_loop_raises_instead_of_lying(self):
        """Kendalikan varian sinkron: di dalam loop, `asyncio.run()` melempar —
        dan ini memang perilaku yang benar. Dulu error itu ditelan per-checker,
        sehingga varian sinkron justru melaporkan `degraded` yang tampak kredibel
        padahal tidak pernah benar-benar memeriksa apa pun; /ping pun memakai
        varian async dan bug ini tidak terlihat. Sekarang salah pakai berarti
        salah pakai yang terlihat (lebih baik daripada berbohong secara diam).
        """
        _register(True, True)

        async def main():
            H.get_health()

        with pytest.raises(RuntimeError):
            asyncio.run(main())


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


class TestBmkgProbe:
    """Checker BMKG harus mem-probe endpoint yang benar-benar dipakai bot.

    Dulu checker mem-HEAD ``https://api.bmkg.go.id`` tanpa path — root domain
    selalu balik 404, sehingga /ping dan panel admin melaporkan "BMKG tidak
    dapat dihubungi" sementara /cuaca dan /gempa mengalir normal.
    """

    @pytest.fixture(autouse=True)
    def fresh_probe_cache(self):
        import main as M
        M._bmkg_health_cache.update(ok=False, at=float("-inf"))
        yield
        M._bmkg_health_cache.update(ok=False, at=float("-inf"))

    @staticmethod
    def _install_client(monkeypatch, statuses):
        import main as M

        class Resp:
            def __init__(self, code):
                self.status_code = code

        class Client:
            def __init__(self):
                self.calls = []

            async def head(self, url, timeout=None):
                self.calls.append(url)
                return Resp(statuses.pop(0) if statuses else 200)

        client = Client()

        async def fake_get_http_client():
            return client

        monkeypatch.setattr(M, "get_http_client", fake_get_http_client)
        return client

    def test_probes_real_endpoints_not_the_root(self, monkeypatch):
        import main as M
        client = self._install_client(monkeypatch, [])
        assert asyncio.run(M._bmkg_health_check()) is True
        assert len(client.calls) == len(M._BMKG_PROBE_URLS)
        for url in client.calls:
            assert urlparse(url).path not in ("", "/"), (
                f"probe menyentuh root domain: {url}"
            )

    def test_one_dead_endpoint_is_enough_to_fail(self, monkeypatch):
        import main as M
        self._install_client(monkeypatch, [200, 404])
        assert asyncio.run(M._bmkg_health_check()) is False

    def test_timeout_counts_as_unreachable(self, monkeypatch):
        import main as M

        class Client:
            async def head(self, url, timeout=None):
                raise TimeoutError("probe timed out")

        async def fake_get_http_client():
            return Client()

        monkeypatch.setattr(M, "get_http_client", fake_get_http_client)
        assert asyncio.run(M._bmkg_health_check()) is False

    def test_result_is_cached_within_ttl(self, monkeypatch):
        import main as M
        client = self._install_client(monkeypatch, [])
        assert asyncio.run(M._bmkg_health_check()) is True
        assert asyncio.run(M._bmkg_health_check()) is True
        # Kedua panggilan (bleh scrape /healthz tiap detik) hanya mem-probe
        # BMKG sekali dalam jendela TTL — tanpa cache, probe per scrape.
        assert len(client.calls) == len(M._BMKG_PROBE_URLS)
