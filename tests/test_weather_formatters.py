"""Weather formatters: satu kontrak untuk keempat pesan cuaca.

Keempat perintah (/cuaca, /per_jam, /prakiraan, briefing 06:30) dulu
membangun string-nya masing-masing. Akibatnya metrik yang sama tampil dengan
tiga ejaan berbeda, dan satu pesan kehilangan metrik yang punknya punya.
"""
import re

import pytest

from utils.design import severity_note
from utils.formatters import (
    location_label, weather_current, weather_daily_brief, weather_hourly,
    weather_multiday,
)


def _render(head, blocks):
    """Rapproksikan hasil akhir supaya assertion bisa pada teks utuh."""
    from utils.design import compose
    return compose(head=head, blocks=blocks)["text"]


class TestSeverityNote:
    @pytest.mark.parametrize("raw,expected", [
        ("Extreme", "🔴 BAHAYA"),
        ("Severe", "🔴 BAHAYA"),
        ("Moderate", "🟠 WASPADA"),
        ("Minor", "🟡 SIAGA"),
        ("Unknown", "ℹ️ INFO"),
        ("", "ℹ️ INFO"),
    ])
    def test_mapping(self, raw, expected):
        assert severity_note(raw) == expected

    def test_labels_are_uppercase(self):
        # "Waspada" and "WASPADA" rendered as visually different weights of
        # emphasis in the same bot.
        for raw in ("Extreme", "Moderate", "Minor"):
            assert severity_note(raw).split()[1].isupper()


class TestLocationLabel:
    def test_desa_and_kecamatan(self):
        assert location_label({"lokasi": {"desa": "Jatimulyo", "kecamatan": "Wates"}}) \
            == "Jatimulyo, Wates"

    def test_missing_is_dash_not_none(self):
        assert location_label({"lokasi": {}}) == "—"
        assert location_label({}) == "—"

    def test_partial_is_kept(self):
        assert location_label({"lokasi": {"desa": "A", "kecamatan": None}}) == "A, —"

    def test_upstream_html_escaped(self):
        label = location_label({"lokasi": {"desa": "A & B <x>", "kecamatan": "C"}})
        assert "&amp;" in label and "<x>" not in label


class TestWeatherCurrent:
    def _blocks(self):
        entry = {"local_datetime": "2026-10-16 15:00:00", "t": 27, "hu": 78,
                 "ws": 9, "wd": "B"}
        head, blocks = weather_current(entry, "Jatimulyo, Wates", "Cerah Berawan 🌤️", "🌤️")
        return _render(head, blocks)

    def test_title_present(self):
        assert "CUACA SAAT INI" in self._blocks()

    def test_accent_is_the_condition(self):
        assert self._blocks().splitlines()[0].startswith("🌤️")

    def test_all_three_metrics(self):
        text = self._blocks()
        assert "27°C" in text and "78%" in text and "9 km/jam" in text

    def test_wind_direction_shown(self):
        assert "(B)" in self._blocks()

    def test_missing_metrics_render_as_dash(self):
        head, blocks = weather_current({}, "—", "Cerah", "☀️")
        text = _render(head, blocks)
        assert text.count("—") >= 3

    def test_source_attribution(self):
        assert "Sumber: BMKG" in self._blocks()


class TestWeatherHourly:
    def _render_table(self, entries, current_dt=""):
        head, blocks = weather_hourly(entries, "Jatimulyo", current_dt, lambda c: "☀️")
        return _render(head, blocks)

    def test_marks_nearest_slot(self):
        entries = [
            {"local_datetime": "2026-10-16 09:00:00", "weather_desc": "Cerah", "t": 24, "hu": 80},
            {"local_datetime": "2026-10-16 12:00:00", "weather_desc": "Cerah", "t": 27, "hu": 70},
        ]
        text = self._render_table(entries, "2026-10-16 12:00:00")
        assert "← sekarang" in text
        assert text.count("← sekarang") == 1

    def test_humidity_shown_per_row(self):
        entries = [{"local_datetime": "2026-10-16 09:00:00", "weather_desc": "Cerah",
                    "t": 24, "hu": 80}]
        assert "💧 80%" in self._render_table(entries)

    def test_location_marker_not_reused_for_the_flag(self):
        """📍 is reserved for location; the 'now' marker used to be 📍 too."""
        entries = [{"local_datetime": "2026-10-16 09:00:00", "weather_desc": "Cerah",
                    "t": 24, "hu": 80}]
        text = self._render_table(entries, "2026-10-16 09:00:00")
        assert "📍" not in text.splitlines()[2]

    def test_malformed_datetime_renders_dash_not_crash(self):
        entries = [{"local_datetime": "", "weather_desc": "Cerah", "t": 24, "hu": 80}]
        assert "—" in self._render_table(entries)


class TestWeatherMultiday:
    def _render_days(self, days):
        head, blocks = weather_multiday(days)
        return _render(head, blocks)

    def test_day_count_in_title(self):
        text = self._render_days([("Hari Ini", 22, 27, 80, 9, False, "")])
        assert "1 HARI" in text

    def test_range_and_metrics(self):
        text = self._render_days([("Hari Ini", 22, 27, 80, 9, False, "")])
        assert "22°C–27°C" in text and "💧 80%" in text and "💨 9 km/jam" in text

    def test_rain_accent_swaps_the_icon(self):
        wet = self._render_days([("Hari Ini", 22, 27, 80, 9, True, "")])
        dry = self._render_days([("Hari Ini", 22, 27, 80, 9, False, "")])
        assert "🌧️" in wet and "☀️" in dry

    def test_later_days_trimmed_first(self):
        days = [
            ("Hari Ini", 22, 27, 80, 9, False, "SLOT HARI INI"),
            ("Besok", 21, 26, 82, 8, False, "SLOT BESOK"),
            ("Lusa", 20, 25, 84, 7, False, "SLOT LUSA"),
        ]
        head, blocks = weather_multiday(days)
        priorities = [p for p, _ in blocks]
        assert priorities == sorted(priorities, reverse=True), (
            "hari berikutnya harus punya prioritas lebih rendah"
        )

    def test_slot_line_included_when_present(self):
        text = self._render_days([("Hari Ini", 22, 27, 80, 9, False, "SLOT")])
        assert "SLOT" in text

    def test_empty_slot_line_omitted(self):
        text = self._render_days([("Hari Ini", 22, 27, 80, 9, False, "")])
        assert text.count("\n\n") == 0

    def test_decimals_never_leak(self):
        text = self._render_days([("Hari Ini", 22.0, 27.6, 80.4, 9.2, False, "")])
        assert "22.6" not in text and "80.4" not in text
        assert re.search(r"\d+°C", text)


class TestWeatherDailyBrief:
    def _render_brief(self, slots, insight="", trend=""):
        head, blocks = weather_daily_brief(slots, "Jatimulyo", insight, trend)
        return _render(head, blocks)

    def _slot(self):
        return ("Pagi", {"weather_desc": "Cerah Berawan & berangin", "t": 24, "hu": 67}, "🌤️")

    def test_humidity_shown(self):
        """Briefing sebelumnya sama sekali tidak menampilkan kelembapan."""
        assert "💧 67%" in self._render_brief([self._slot()])

    def test_one_row_per_slot(self):
        slots = [
            ("Pagi", {"weather_desc": "Cerah", "t": 24, "hu": 67}, "☀️"),
            ("Siang", {"weather_desc": "Cerah", "t": 32, "hu": 49}, "☀️"),
        ]
        text = self._render_brief(slots)
        assert "Pagi" in text and "Siang" in text
        assert "💧 67%" in text and "💧 49%" in text

    def test_description_escaped(self):
        assert "&amp;" in self._render_brief([self._slot()])

    def test_insight_section_optional(self):
        assert "INSIGHT" not in self._render_brief([self._slot()])

    def test_insight_section_present(self):
        assert "INSIGHT" in self._render_brief([self._slot()], insight="Hujan diperkirakan.")

    def test_trend_section_optional(self):
        assert "TREN" not in self._render_brief([self._slot()], insight="x")
        assert "TREN" in self._render_brief(
            [self._slot()], trend="📈 <b>TREN BESOK</b>\nBesok lebih hangat.")
