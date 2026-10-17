"""Integritas tabel cuaca — penjaga anti-drift.

Empat peta terpisah (label, emoji, grup foto, pool insight) dulu harus
dijaga sinkron secara manual, dan sudah berbeda satu sama lain: kode 50-57
tahu soal gerimis hanya di satu modul, kode 66 mendapat foto hujan lebat
padahal labelnya "Hujan Beku Ringan", dan set "cerah" memuat kode 3 yang
berlabel "Berawan".

Tabel ini membuat kelas kesalahan itu tidak mungkin terjadi tanpa gagal tes.
"""
import pytest

from utils import weather_table as wt
from utils import insight_templates as it


class TestIntegrity:
    def test_no_validation_errors(self):
        assert wt.validation_errors() == []

    def test_every_code_has_a_photo_query(self):
        """Kode tanpa kueri tampil tanpa foto, dan tidak ada yang memberi tahu."""
        assert wt.missing_queries() == []

    def test_every_code_has_a_known_photo_group(self):
        for cond in wt.WEATHER_CONDITIONS.values():
            assert cond.photo_group in wt.PHOTO_GROUP_SEVERITY

    def test_identical_labels_render_identically(self):
        """Kode 62 dan 81 sama-sama "Hujan Sedang" dan sebelumnya tampil
        dengan ikon berbeda (🌧️ vs 🌦️)."""
        by_label = {}
        for cond in wt.WEATHER_CONDITIONS.values():
            by_label.setdefault(cond.label, set()).add(cond.emoji)
        for label, emojis in by_label.items():
            assert len(emojis) == 1, f'"{label}" punya {emojis}'

    def test_no_orphan_queries(self):
        orphans = set(wt.WEATHER_QUERY_MAP) - {str(c) for c in wt.WEATHER_CONDITIONS}
        assert not orphans, f"kueri tanpa kode: {orphans}"

    def test_log_problems_is_silent_when_healthy(self, caplog):
        import logging

        with caplog.at_level(logging.INFO):
            wt.log_problems(logging.getLogger("t"))
        assert "Tabel cuaca OK" in caplog.text


class TestCoverage:
    @pytest.mark.parametrize("codes,why", [
        ((50, 51, 52, 53, 54, 55, 56, 57), "gerimis"),
        ((17, 18, 19, 24, 25, 26, 27, 28, 29), "petir"),
        ((6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16), "kabut dan asap"),
        ((37,), "angin kuat"),
        ((95, 96, 97), "hujan petir"),
    ])
    def test_codes_are_mapped(self, codes, why):
        for code in codes:
            assert wt.condition(code) is not None, f"kode {code} ({why}) tidak dipetakan"

    def test_drizzle_and_thunder_no_longer_unknown(self):
        assert wt.emoji(51) == "🌦️"
        assert wt.emoji(95) == "⛈️"
        assert wt.emoji(37) == "💨"

    def test_snow_codes_deliberately_absent(self):
        """BMKG tidak mengeluarkan kode salju untuk Indonesia."""
        for code in (38, 40, 41, 42, 43, 44):
            assert wt.condition(code) is None


class TestGroupFixes:
    def test_frozen_drizzle_is_light_rain(self):
        """Kode 66 "Hujan Beku Ringan" dulu ada di heavy_rain, jadi gerimis beku
        difoto dengan gambar hujan lebat."""
        assert wt.photo_group(66) == "light_rain"
        assert wt.photo_group(67) == "heavy_rain"

    def test_frozen_drizzle_severity_below_storm(self):
        assert wt.photo_severity(66) < wt.photo_severity(67)

    def test_overcast_is_not_clear_sky(self):
        """Kode 3 dan 4 berlabel Berawan. Sebelumnya keduanya masuk himpunan
        'clear', sehingga hari mendung penuh bisa menghasilkan "Hari cerah
        sempurna! Cocok untuk jemur pakaian"."""
        assert 3 not in wt.CLEAR_SKY_CODES
        assert 4 not in wt.CLEAR_SKY_CODES
        assert wt.condition(3).sky == "cloudy"
        assert wt.condition(0).sky == "clear"

    def test_thunderstorm_counts_as_wet(self):
        """Kode 95-97 pernah hilang dari himpunan 'rain'."""
        for code in (95, 96, 97):
            assert wt.is_wet(code)

    def test_drizzle_counts_as_wet(self):
        for code in (50, 54, 57):
            assert wt.is_wet(code)

    def test_haze_codes_complete(self):
        assert {5, 10, 45} <= wt.HAZE_CODES

    def test_dry_codes_not_wet(self):
        for code in (0, 3, 4, 37):
            assert not wt.is_wet(code)

    def test_lightning_without_rain_is_stormy_but_not_wet(self):
        """Kode 17-24 "Petir" adalah petir tanpa hujan: secara fisika tidak
        presipitasi, tapi ikon ☀️ untuk hari itu akan menyesatkan."""
        for code in (17, 19, 24):
            assert wt.condition(code).wet is False
            assert wt.is_wet(code) is False
            assert wt.is_wet_or_stormy(code) is True

    def test_stormy_covers_every_precipitation_code(self):
        for cond in wt.WEATHER_CONDITIONS.values():
            if cond.wet:
                assert wt.is_wet_or_stormy(cond.code), cond.code


class TestLookups:
    def test_unknown_code_degrades(self):
        assert wt.emoji(999) == "❓"
        assert wt.photo_group(999) is None
        assert wt.query_for(999) is None
        assert wt.is_wet(999) is False

    def test_non_numeric_code_degrades(self):
        assert wt.emoji("abc") == "❓"
        assert wt.condition(None) is None

    def test_label_uses_bmkg_fallback(self):
        assert wt.label(999, "Cerah") == "Cerah"
        assert wt.label(999) == "❓"

    def test_label_includes_emoji(self):
        assert wt.label(63) == "Hujan Lebat ⛈️"

    def test_string_and_int_codes_agree(self):
        assert wt.condition("63") is wt.condition(63)


class TestMostSevereCode:
    def test_picks_most_dramatic_condition(self):
        from services.bmkg_api import _most_severe_code

        entries = [{"weather": 0}, {"weather": 60}, {"weather": 95}]
        assert _most_severe_code(entries) == "95"

    def test_ignores_unknown_codes(self):
        from services.bmkg_api import _most_severe_code

        assert _most_severe_code([{"weather": 999}]) is None

    def test_empty_and_missing_fields(self):
        from services.bmkg_api import _most_severe_code

        assert _most_severe_code([]) is None
        assert _most_severe_code([{}]) is None
        assert _most_severe_code(None) is None


class TestInsightUsesTable:
    def _entries(self, code, hour=15, tp=0):
        return [{"weather": code, "t": 25, "hu": 70, "ws": 5, "tp": tp,
                 "local_datetime": f"2026-10-16 {hour:02d}:00:00"}]

    def test_overcast_day_not_called_clear(self):
        """Bug yang diperbaiki: kode 3 "Berawan" ada di set clear."""
        meta = it.analyze_weather(self._entries(3))
        assert meta is not None
        assert meta["is_clear"] is False
        assert meta["is_cloudy"] is True

    def test_clear_day_still_clear(self):
        assert it.analyze_weather(self._entries(0))["is_clear"] is True

    def test_thunderstorm_flagged_as_rain(self):
        meta = it.analyze_weather(self._entries(95, tp=20))
        assert meta["has_thunderstorm"] and meta["has_rain"]

    def test_drizzle_flagged_separately(self):
        meta = it.analyze_weather(self._entries(53, tp=1))
        assert meta["has_drizzle"] and not meta["rain_heavy"]

    def test_drizzle_gets_its_own_template(self):
        """Gerimis pernah jatuh ke DEFAULT_TEMPLATES dan berbunyi seperti tidak
        ada apa-apa."""
        from utils.insight_templates import _select_pool

        pool = _select_pool(it.analyze_weather(self._entries(53, tp=1)))
        assert pool is it.DRIZZLE_TEMPLATES

    def test_thunderstorm_beats_drizzle(self):
        from utils.insight_templates import _select_pool

        entries = self._entries(53, tp=1) + self._entries(95, tp=20)
        pool = _select_pool(it.analyze_weather(entries))
        assert pool is it.THUNDERSTORM_TEMPLATES

    def test_insight_has_no_bold_prefix_of_its_own(self):
        """Dulu setiap insight membawa "<emoji> <b>Saran hari ini:</b>" sementara
        pemanggil membungkusnya dengan header "💡 INSIGHT" — dua header bertumpuk.
        Isi insight sekarang polos; header murni milik formatter."""
        for code in (0, 3, 53, 63, 95):
            insight = it.generate_smart_insight(self._entries(code, tp=10), max_insights=1)
            assert "<b>" not in insight, f"kode {code}: {insight!r}"

    def test_trend_has_no_header_of_its_own(self):
        """ generate_trend_insight dulu mengembalikan "📈 <b>TREN BESOK</b>\\n..."
        lengkap dengan header — semua generator isi, formatter yang memberi
        judul."""
        from fixtures.bmkg import WEATHER_JSON

        cuaca_data = WEATHER_JSON["data"][0]["cuaca"]
        trend = it.generate_trend_insight(cuaca_data)
        assert trend, "fixture jelas punya dua hari berbeda"
        assert "<b>" not in trend and "TREN" not in trend

    def test_trend_empty_when_fewer_than_two_days(self):
        assert it.generate_trend_insight([]) == ""
        assert it.generate_trend_insight([[{"t": 30, "weather": 1}]]) == ""

    def test_hour_parsing_survives_malformed_timestamp(self):
        """Pola `local_dt.split(' ')[1]` yang disebut AGENTS.md."""
        entries = [{"weather": 60, "t": 25, "hu": 70, "ws": 5, "tp": 5,
                    "local_datetime": "2026-10-16"}]
        meta = it.analyze_weather(entries)
        assert meta is not None
        assert meta["rain_hours"] == []

    def test_hour_parsed_when_present(self):
        meta = it.analyze_weather(self._entries(60, hour=15, tp=5))
        assert 15 in meta["rain_hours"]

    def test_garbage_entry_does_not_kill_analysis(self):
        entries = [{"weather": "abc", "t": "x", "hu": None, "ws": None, "tp": None},
                   {"weather": 0, "t": 25, "hu": 70, "ws": 5, "tp": 0,
                    "local_datetime": "2026-10-16 09:00:00"}]
        meta = it.analyze_weather(entries)
        assert meta is not None and meta["is_clear"]

    def test_all_wet_codes_appear_in_wet_set(self):
        """Tidak boleh ada kode basah yang lolos dari WET_CODES."""
        for cond in wt.WEATHER_CONDITIONS.values():
            if cond.wet:
                assert cond.code in it.WET_CODES
