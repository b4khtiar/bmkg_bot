"""Kasus terburuk: payload What'sApp-sized dari BMKG."""
from copy import deepcopy

from fixtures.bmkg import CAP_ALERT, QUAKE
from utils.design import CAPTION_LIMIT
from utils.formatters import format_nowcast_alert, format_quake, quake_shakemap_url


class TestQuakeFormatter:
    def test_fits_caption_budget_with_absurd_input(self):
        msg = format_quake(deepcopy(QUAKE))
        assert len(msg) <= CAPTION_LIMIT

    def test_upstream_html_is_escaped(self):
        msg = format_quake(deepcopy(QUAKE))
        assert "&amp;" in msg
        assert "<script>" not in msg

    def test_potensi_keeps_ampersand_legible(self):
        msg = format_quake(deepcopy(QUAKE))
        assert "tsunami &amp; tidak ada" in msg

    def test_magnitude_and_depth_present(self):
        msg = format_quake(deepcopy(QUAKE))
        assert "5,4" in msg and "30 km" in msg

    def test_direction_and_place_split(self):
        msg = format_quake(deepcopy(QUAKE))
        # "120 km Barat Daya" is the bearing, not the place name.
        assert "(120 km Barat Daya)" in msg
        assert "MALUKUTENGGARABRT" in msg

    def test_distance_info_included_when_given(self):
        msg = format_quake(deepcopy(QUAKE), distance_info="🏠 <b>Provinsi Anda</b>  DIY")
        assert "Provinsi Anda" in msg

    def test_distance_info_omitted_when_absent(self):
        assert "Provinsi Anda" not in format_quake(deepcopy(QUAKE))

    def test_long_dirasakan_is_trimmed_not_dropped_whole(self):
        msg = format_quake(deepcopy(QUAKE))
        assert "Dirasakan" in msg

    def test_missing_fields_do_not_crash(self):
        assert format_quake({})

    def test_shakemap_url(self):
        assert quake_shakemap_url(QUAKE).endswith(QUAKE["Shakemap"])
        assert quake_shakemap_url(QUAKE).startswith("https://cdn.bmkg.go.id/")


class TestNowcastFormatter:
    def test_fits_caption_budget_with_twenty_four_bullets(self):
        alert = deepcopy(CAP_ALERT)
        assert len(alert["impacts"]) == 12
        msg = format_nowcast_alert(alert)
        assert len(msg) <= CAPTION_LIMIT

    def test_headline_and_time_survive_trimming(self):
        msg = format_nowcast_alert(deepcopy(CAP_ALERT))
        assert "PERINGATAN DINI CUACA" in msg
        assert "14:00" in msg and "17:00" in msg

    def test_safety_advice_trimmed_before_impact(self):
        msg = format_nowcast_alert(deepcopy(CAP_ALERT))
        assert "Dampak" in msg

    def test_province_escaped(self):
        msg = format_nowcast_alert(deepcopy(CAP_ALERT))
        assert "&amp;" in msg
        # The upstream "<b>" in the province name must not survive as a tag.
        # Our own <b> around the title is expected, so check the header line
        # that carries the province specifically.
        province_line = [l for l in msg.splitlines() if l.startswith("🗺️")][0]
        assert province_line == "🗺️ DI Yogyakarta &amp; Sleman &lt;b&gt;"

    def test_sub_district_overflow_counted_not_ellipsised(self):
        alert = deepcopy(CAP_ALERT)
        alert["impacts"] = ["satu"]
        alert["advice"] = ["satu"]
        msg = format_nowcast_alert(alert)
        assert "+7 wilayah lain" in msg

    def test_no_ellipsis_run_when_under_five_sub_districts(self):
        alert = deepcopy(CAP_ALERT)
        alert["impacts"] = ["satu"]
        alert["advice"] = ["satu"]
        alert["sub_districts"] = "A, B, C"
        assert "+" not in format_nowcast_alert(alert).split("Wilayah Terdampak")[1]

    def test_missing_lists_render_as_dash_not_empty_heading(self):
        alert = deepcopy(CAP_ALERT)
        alert["impacts"] = []
        alert["advice"] = []
        msg = format_nowcast_alert(alert)
        assert "Dampak ━━━\n—" in msg

    def test_severity_accent_from_parser_is_used_as_title(self):
        msg = format_nowcast_alert(deepcopy(CAP_ALERT))
        assert msg.startswith("🔴 Bahaya")

    def test_missing_fields_do_not_crash(self):
        assert format_nowcast_alert({})
