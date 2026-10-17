import logging
import threading
import time
import asyncio
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def _port() -> int:
    """Port dibaca saat server dijalankan, bukan saat modul diimpor.

    Membacanya di level modul membuat nilainya terkunci sejak import, sehingga
    override lewat environment setelah import tidak berlaku sama sekali.
    """
    return int(os.getenv("HEALTH_SERVER_PORT", "8080"))

_started_at = None
_server: HTTPServer = None
_thread: threading.Thread = None

# Use a closure to access the check functions (avoids circular import).
# Kontrak: kedua checker harus async — lihat _gather().
_db_check_fn = None
_bmkg_check_fn = None


def _set_checkers(db_fn, bmkg_fn):
    """Called from main.py to register async check functions."""
    global _db_check_fn, _bmkg_check_fn
    _db_check_fn = db_fn
    _bmkg_check_fn = bmkg_fn


def _assemble(db_ok: bool, bmkg_ok: bool) -> dict:
    return {
        "status": "ok" if (db_ok and bmkg_ok) else "degraded",
        "db": db_ok,
        "bmkg_reachable": bmkg_ok,
        "uptime_seconds": int(time.time() - _started_at) if _started_at else 0,
    }


async def _gather() -> dict:
    """Jalankan kedua checker awaitable dan rangkai hasilnya.

    Checker HARUS awaitable. Dulu checker BMKG dipanggil sinkron:
    ``bool(_bmkg_check_fn())`` pada fungsi async akan mengembalikan True untuk
    coroutine yang belum dijalankan — kegagalan cek dilaporkan sehat. Satu
    jalur await untuk kedua pemanggil menghapus jebakan itu sekaligus mencegah
    pemanggilan blocking di dalam event loop bot.
    """
    db_ok = False
    if _db_check_fn:
        try:
            db_ok = bool(await _db_check_fn())
        except Exception as e:
            logger.warning(f"DB healthcheck error: {e}")
    bmkg_ok = False
    if _bmkg_check_fn:
        try:
            bmkg_ok = bool(await _bmkg_check_fn())
        except Exception as e:
            logger.warning(f"BMKG healthcheck error: {e}")
    return _assemble(db_ok, bmkg_ok)


def get_health() -> dict:
    """Status kesehatan — untuk pemanggil di luar event loop (server HTTP).

    Server kesehatan berjalan di thread terpisah, jadi `asyncio.run()` aman
    di sini.
    """
    return asyncio.run(_gather())


async def get_health_async() -> dict:
    """Status kesehatan — untuk pemanggil yang sudah di dalam event loop.

    WAJIB dipakai oleh handler aiogram. Versi sinkron memanggil
    `asyncio.run()`, yang melempar "cannot be called from a running event loop"
    tepat di dalam loop bot — artinya `/ping` akan melaporkan "degraded"
    tanpa pernah benar-benar memeriksa apa pun.
    """
    return await _gather()


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            self._respond_health()
        elif path == "/metrics":
            self._respond_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _respond_health(self):
        body = get_health()
        payload = json.dumps(body).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _respond_metrics(self):
        health = get_health()

        lines = [
            "# HELP bmkg_bot_uptime_seconds Bot uptime",
            "# TYPE bmkg_bot_uptime_seconds gauge",
            f"bmkg_bot_uptime_seconds {health['uptime_seconds']}",
            "# HELP bmkg_bot_db_healthy DB health (1=ok, 0=down)",
            "# TYPE bmkg_bot_db_healthy gauge",
            # Previously `1 if _db_check_fn` — i.e. "1" the moment a checker was
            # registered, never the actual result. /metrics reported a healthy
            # database while the database was down.
            f"bmkg_bot_db_healthy {1 if health['db'] else 0}",
            "# HELP bmkg_bot_bmkg_reachable BMKG API reachable (1=ok, 0=down)",
            "# TYPE bmkg_bot_bmkg_reachable gauge",
            f"bmkg_bot_bmkg_reachable {1 if health['bmkg_reachable'] else 0}",
        ]
        payload = "\n".join(lines).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _run_server():
    global _started_at, _server
    _started_at = time.time()
    port = _port()
    _server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info(f"Health server listening on :{port} (threaded)", extra={"bot_mode": "health"})
    _server.serve_forever()


def start_health_server():
    """Start health server in background thread. Must call _set_checkers() first."""
    global _thread
    _thread = threading.Thread(target=_run_server, daemon=True)
    _thread.start()
    return _thread


def stop_health_server():
    if _server:
        _server.shutdown()
        _server.server_close()
        logger.info("Health server stopped.")
