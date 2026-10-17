"""Tes untuk parser cuaca dan ringkasan nowcast (jalur sinkron, tanpa API)."""
import asyncio
import re
from copy import deepcopy

import pytest

from fixtures.bmkg import WEATHER_JSON, nowcast_rss
from utils import weather_table as wt
from services.bmkg_api import (
    parse_weather_current, parse_weather_daily_brief,
    parse_weather_hourly_today, parse_weather_multi_day, summarize_nowcast_rss,
)
from utils.design import CAPTION_LIMIT

TASKS = [
    (parse_weather_current, "current"),
    (parse_weather_daily_brief, "brief"),
    (parse_weather_hourly_today, "hourly"),
    (parse_weather_multi_day, "multiday"),
]


def _with_unsplash_stubbed(monkeypatch):
    """Matikan pemanggilan Unsplash — tes ini tidak soal foto."""
    import services.unsplash_client as uc

    async def fake(_code):
        return None, None

    monkeypatch.setattr(uc, "get_weather_photo", fake)


class TestWeatherParsers:
    @pytest.mark.parametrize("fn,label", TASKS)
    def test_output_always_fits_caption_budget(self, fn, label, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        result = asyncio.run(fn(deepcopy(WEATHER_JSON)))
        assert len(result["text"]) <= CAPTION_LIMIT, f"{label} exceeded budget"

    @pytest.mark.parametrize("fn,label", TASKS)
    def test_upstream_html_is_escaped(self, fn, label, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        payload = deepcopy(WEATHER_JSON)
        payload["lokasi"]["desa"] = "A & B <b>"
        payload["data"][0]["cuaca"][0][0]["weather_desc"] = "Hujan & kabut <i>"
        result = asyncio.run(fn(payload))
        assert "&amp;" in result["text"]
        assert "<i>Hujan" not in result["text"]

    @pytest.mark.parametrize("fn,label", TASKS)
    def test_source_attribution_present(self, fn, label, monkeypatch):
        # The daily brief used to omit it, which made this one message in the
        # bot look like it came from nowhere.
        _with_unsplash_stubbed(monkeypatch)
        result = asyncio.run(fn(deepcopy(WEATHER_JSON)))
        assert "Sumber: BMKG" in result["text"]

    @pytest.mark.parametrize("fn,label", TASKS)
    def test_empty_payload_does_not_crash(self, fn, label, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        assert asyncio.run(fn({}))["text"]

    @pytest.mark.parametrize("fn,label", TASKS)
    def test_missing_location_fields_render_as_dash(self, fn, label, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        payload = deepcopy(WEATHER_JSON)
        payload["lokasi"] = {}
        result = asyncio.run(fn(payload))
        assert "—" in result["text"]


class TestDailyBriefTrend:
    """Plugin tren dipasang sejak lama, tapi tidak pernah tampil: pemanggil
    memberi `generate_trend_insight` daftar `data` (grup lokasi) alih-alih
    grup hari di dalamnya, sehingga 'hari besok' selalu kosong."""

    def _brief(self, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        return asyncio.run(parse_weather_daily_brief(deepcopy(WEATHER_JSON)))["text"]

    def test_trend_renders_in_the_full_pipeline(self, monkeypatch):
        text = self._brief(monkeypatch)
        assert "📈 <b>TREN BESOK</b>" in text

    def test_exactly_one_trend_header(self, monkeypatch):
        text = self._brief(monkeypatch)
        assert text.count("📈") == 1

    def test_trend_content_mentions_tomorrow_max_temp(self, monkeypatch):
        """Isi tren berasal dari data hari kedua — bukan placeholder."""
        text = self._brief(monkeypatch)
        assert re.search(r"TREN BESOK.*", text, re.S)
        assert "Besok" in text.split("📈 <b>TREN BESOK</b>")[1]

    def test_single_day_payload_has_no_trend_block(self, monkeypatch):
        """Satu hari tidak punya 'besok' untuk dibandingkan — blok tidak
        boleh muncul kosong atau placeholder."""
        _with_unsplash_stubbed(monkeypatch)
        payload = deepcopy(WEATHER_JSON)
        payload["data"][0]["cuaca"] = payload["data"][0]["cuaca"][:1]
        result = asyncio.run(parse_weather_daily_brief(payload))
        assert "TREN" not in result["text"]


class TestCacheBanner:
    def test_multiday_shows_cache_banner(self):
        """Bug yang diperbaiki: /prakiraan menyajikan data basi tanpa peringatan
        sementara /cuaca dan ringkasan pagi menandainya."""
        payload = deepcopy(WEATHER_JSON)
        payload["_cached"] = True
        payload["_cached_at"] = "2026-10-16T09:00:00"
        result = asyncio.run(parse_weather_multi_day(payload))
        assert "Data cadangan" in result["text"]

    @pytest.mark.parametrize("fn,label", TASKS)
    def test_fresh_data_has_no_banner(self, fn, label, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        result = asyncio.run(fn(deepcopy(WEATHER_JSON)))
        assert "Data cadangan" not in result["text"]


class TestFormatConsistency:
    def test_temperature_rendering_matches_across_parsers(self, monkeypatch):
        """27°C must not appear as "27.0°C" in one message and "27°C" in another."""
        _with_unsplash_stubbed(monkeypatch)
        pattern = re.compile(r"(\d+(?:\.\d+)?)°C")
        for fn, label in TASKS:
            text = asyncio.run(fn(deepcopy(WEATHER_JSON)))["text"]
            values = pattern.findall(text)
            assert values, f"{label} rendered no temperature"
            for value in values:
                assert "." not in value, f"{label} leaked a decimal: {value}°C"

    def test_humidity_uses_one_form_everywhere(self, monkeypatch):
        """Tiga ejaan pernah hidup bersamaan: '💧78%', '💧 <code>78%</code>',
        dan '💧 78%'. Sekarang semua pakai label + nilai yang sama.

        Briefing harian dulu tidak menampilkan kelembapan sama sekali; sekarang
        ikut menampilkannya, jadi tidak ada lagi pengecualian di tes ini.
        """
        _with_unsplash_stubbed(monkeypatch)
        pattern = re.compile(r"💧\s*(?:<b>[^<]*</b>\s*)?(\d+)%")
        for fn, label in TASKS:
            text = asyncio.run(fn(deepcopy(WEATHER_JSON)))["text"]
            match = pattern.search(text)
            assert match, f"{label} tidak menampilkan kelembapan"
            # The humidity value itself must not be wrapped in <code>. Only the
            # segment up to the first % is checked: <code> is still correct for
            # clock times in the hourly table.
            segment = text[match.start():match.end()]
            assert "<code>" not in segment, f"{label} membungkus nilai dalam <code>"

    def test_every_parser_reports_temperature_humidity_and_wind(self, monkeypatch):
        """Ketiga metrik yang sama harus muncul di keempat pesan cuaca."""
        _with_unsplash_stubbed(monkeypatch)
        for fn, label in TASKS:
            text = asyncio.run(fn(deepcopy(WEATHER_JSON)))["text"]
            assert re.search(r"\d+°C", text), f"{label} tidak menampilkan suhu"
            assert re.search(r"\d+%", text), f"{label} tidak menampilkan kelembapan"

    def test_no_raw_placeholders_survive(self, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        for fn, _label in TASKS:
            text = asyncio.run(fn(deepcopy(WEATHER_JSON)))["text"]
            assert "None" not in text
            assert "'" not in text  # repr leakage from missing fields


class TestMultidayRainIcon:
    """Ikon harian harus mencerminkan kondisi, bukan hanya presipisasi."""

    def _payload(self, code):
        payload = deepcopy(WEATHER_JSON)
        for day in payload["data"]:
            for group in day["cuaca"]:
                for entry in group:
                    entry["weather"] = code
                    entry["weather_desc"] = wt.label(code)
                    entry["tp"] = 10
        return payload

    @pytest.mark.parametrize("code,why", [
        (0, "cerah"),
        (3, "berawan"),
        (60, "hujan ringan"),
        (63, "hujan lebat"),
        (24, "petir tanpa hujan"),
        (17, "petir"),
        (95, "hujan petir"),
    ])
    def test_icon_matches_condition(self, code, why, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        text = asyncio.run(parse_weather_multi_day(self._payload(code)))["text"]
        day_line = [l for l in text.splitlines() if "km/jam" in l][0]
        icon = "🌧️" if wt.is_wet_or_stormy(code) else "☀️"
        assert icon in day_line, f"kode {code} ({why}) dapat ikon yang salah: {day_line}"

    def test_storm_day_never_shows_sun(self, monkeypatch):
        _with_unsplash_stubbed(monkeypatch)
        text = asyncio.run(parse_weather_multi_day(self._payload(24)))["text"]
        summary = [l for l in text.splitlines() if "km/jam" in l]
        assert summary and "🌧️" in summary[0]
        assert not summary[0].lstrip().startswith("☀️")


class TestNowcastDigest:
    def test_titles_escaped(self):
        # The title must contain the province name to survive the filter, and
        # carry HTML metacharacters to exercise the escaping.
        rss = nowcast_rss(["Peringatan Cuaca DI Yogyakarta & Sleman <b>"])
        out = summarize_nowcast_rss(rss, province_filter="DI Yogyakarta")
        assert "&amp;" in out
        assert "<b>" not in out

    def test_output_capped_for_long_rss(self):
        """Without a cap, a location-less user received the entire national
        feed, which passes 4096 chars and fails to deliver at all."""
        rss = nowcast_rss([f"Peringatan-{i} DIY" for i in range(60)])
        out = summarize_nowcast_rss(rss, province_filter="DIY")
        assert len(out) <= 4096

    def test_capped_output_says_how_many_are_hidden(self):
        rss = nowcast_rss([f"Peringatan-{i} DIY" for i in range(30)])
        out = summarize_nowcast_rss(rss, province_filter="DIY")
        assert "peringatan lain" in out

    def test_short_list_shows_total(self):
        rss = nowcast_rss(["Peringatan DIY"])
        out = summarize_nowcast_rss(rss, province_filter="DIY")
        assert "Menampilkan 1 peringatan" in out

    def test_no_match_names_the_province(self):
        rss = nowcast_rss(["Peringatan Bali"])
        out = summarize_nowcast_rss(rss, province_filter="DI Yogyakarta")
        assert "DI Yogyakarta" in out

    def test_malformed_xml_degrades_gracefully(self):
        assert summarize_nowcast_rss("<rss><broken>")

    def test_empty_feed(self):
        assert "Tidak ada peringatan" in summarize_nowcast_rss(
            "<rss><channel></channel></rss>"
        )

    def test_province_filter_applied(self):
        rss = nowcast_rss(["Peringatan DIY", "Peringatan Bali"])
        out = summarize_nowcast_rss(rss, province_filter="Bali")
        assert "Bali" in out and "DIY" not in out
