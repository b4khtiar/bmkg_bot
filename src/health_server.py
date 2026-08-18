import logging
import threading
import time
import asyncio
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_PORT = int(os.getenv("HEALTH_SERVER_PORT", "8080"))

_started_at = None
_server: HTTPServer = None
_thread: threading.Thread = None

# Use a closure to access the DB check function (avoids circular import)
_db_check_fn = None
_bmkg_check_fn = None


def _set_checkers(db_fn, bmkg_fn):
    """Called from main.py to register async check functions."""
    global _db_check_fn, _bmkg_check_fn
    _db_check_fn = db_fn
    _bmkg_check_fn = bmkg_fn


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        global _started_at
        path = urlparse(self.path).path

        if path == "/healthz":
            self._respond_health()
        elif path == "/metrics":
            self._respond_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def _respond_health(self):
        db_ok = False
        bmkg_ok = False

        if _db_check_fn:
            try:
                db_ok = asyncio.run(_db_check_fn())
            except Exception as e:
                logger.warning(f"DB healthcheck error: {e}")

        if _bmkg_check_fn:
            try:
                bmkg_ok = _bmkg_check_fn()
            except Exception as e:
                logger.warning(f"BMKG healthcheck error: {e}")

        status = "ok" if (db_ok and bmkg_ok) else "degraded"
        uptime = int(time.time() - _started_at) if _started_at else 0

        body = {
            "status": status,
            "db": db_ok,
            "bmkg_reachable": bmkg_ok,
            "uptime_seconds": uptime,
        }
        payload = json.dumps(body).encode("utf-8")

        self.send_response(200 if status == "ok" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _respond_metrics(self):
        uptime = int(time.time() - _started_at) if _started_at else 0

        lines = [
            "# HELP bmkg_bot_uptime_seconds Bot uptime",
            "# TYPE bmkg_bot_uptime_seconds gauge",
            f"bmkg_bot_uptime_seconds {uptime}",
            "# HELP bmkg_bot_db_healthy DB health (1=ok, 0=down)",
            "# TYPE bmkg_bot_db_healthy gauge",
            f"bmkg_bot_db_healthy {1 if _db_check_fn else 0}",
            "# HELP bmkg_bot_bmkg_reachable BMKG API reachable (1=ok, 0=down)",
            "# TYPE bmkg_bot_bmkg_reachable gauge",
            f"bmkg_bot_bmkg_reachable {1 if _bmkg_check_fn else 0}",
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
    port = DEFAULT_PORT
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
    global _server
    if _server:
        _server.shutdown()
        _server.server_close()
        logger.info("Health server stopped.")
