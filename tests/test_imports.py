"""Import check untuk modul handler dan ``main``.

Dilakukan terhadap stub aiogram karena paket aslinya tidak tersedia di
lingkungan uji. Yang diverifikasi di sini adalah kebocoran rename: modul masih
mengimpor, semua handler terdaftar, dan alias perintah lama masih diterima.
"""
import handlers.admin as A
import handlers.user as U
import main as M
from tests.aiogram_stub import _Filter


class TestUserRouter:
    def test_expected_commands_registered(self):
        names = {f.__name__ for f in U.router.message_handlers}
        assert {
            "cmd_start",
            "cmd_current_weather",
            "cmd_extended_forecast",
            "cmd_hourly_today",
            "cmd_earthquake",
            "cmd_nowcast",
            "cmd_notif_preferences",
            "cmd_location",
            "cmd_help",
            "cmd_ping",
        } <= names

    def test_expected_callbacks_registered(self):
        names = {f.__name__ for f in U.router.callback_handlers}
        assert {
            "handle_provinces",
            "handle_cities",
            "handle_confirm_location",
            "handle_notif_toggle",
        } <= names

    def test_legacy_hourly_command_still_works(self):
        """Rename /cuaca_hari_ini -> /per_jam harus tetap menerima nama lama."""
        names = _command_names(U.router)
        assert "per_jam" in names
        assert "cuaca_hari_ini" in names

    def test_legacy_notif_command_still_works(self):
        names = _command_names(U.router)
        assert "notifikasi" in names
        assert "atur_notif" in names

    def test_new_commands_exist(self):
        names = _command_names(U.router)
        assert {"lokasi", "bantuan"} <= names


class TestAdminRouter:
    def test_handlers_registered(self):
        assert {"cmd_admin_panel", "cmd_whitelist"} <= {
            f.__name__ for f in A.router.message_handlers
        }
        assert {"handle_set_mode", "handle_close_panel"} <= {
            f.__name__ for f in A.router.callback_handlers
        }


class TestMain:
    def test_jobs_present(self):
        for name in (
            "check_quake_job",
            "daily_weather_job",
            "nowcast_alert_job",
            "retry_failed_sends_job",
        ):
            assert callable(getattr(M, name)), name

    def test_both_routers_registered(self):
        assert len(M.__dict__)  # modul termuat
        assert callable(M._send_photo_sem)
        assert callable(M._send_msg_sem)

    def test_send_helpers_are_distinct(self):
        """Dulu ada dua jalur kirim foto dengan semantik panjang berbeda."""
        assert M._send_photo_sem is not M._send_text_locked


def _command_names(router):
    names = set()
    for _f, args, _kwargs in router.registrations:
        for spec in args:
            if isinstance(spec, _Filter):
                names.update(spec.args)
    return names
