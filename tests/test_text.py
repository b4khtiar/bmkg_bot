from utils.text import (
    MISSING, bullet_list, clamp, esc, esc_href, esc_inline,
    fmt_hum, fmt_num, fmt_temp, fmt_wind, join_rows,
)


class TestEsc:
    def test_escapes_html_metacharacters(self):
        assert esc("a & b") == "a &amp; b"
        assert esc("<b>") == "&lt;b&gt;"
        assert esc(">") == "&gt;"

    def test_none_and_blank_become_missing_dash(self):
        # Two checks collapsed into one so callers do not have to test both.
        assert esc(None) == MISSING
        assert esc("") == MISSING
        assert esc("   ") == MISSING

    def test_preserves_emoji_and_accents(self):
        assert esc("Cerah Berawan 🌤️ & >= x") == "Cerah Berawan 🌤️ &amp; &gt;= x"

    def test_does_not_escape_quotes_for_body_text(self):
        assert "'" in esc("Elly's")

    def test_inline_escapes_quotes(self):
        assert esc_inline('say "hi"') == "say &quot;hi&quot;"

    def test_href_escapes_quotes_to_prevent_attribute_breakout(self):
        # A bare quote here would close the href attribute and let upstream
        # text inject its own attribute onto the <a> tag.
        out = esc_href('http://x/?a=1&b="2"')
        assert '"' not in out
        assert "&amp;" in out and "&quot;" in out

    def test_href_empty_is_empty_string(self):
        assert esc_href("") == ""
        assert esc_href(None) == ""


class TestFormatting:
    def test_temp_no_space_before_degree(self):
        assert fmt_temp(27) == "27°C"
        assert fmt_temp(27.4) == "27°C"

    def test_humidity_and_wind(self):
        assert fmt_hum(63) == "63%"
        assert fmt_wind(12) == "12 km/jam"

    def test_missing_values_render_as_dash(self):
        # Renders as a deliberate visual choice rather than a hole.
        assert fmt_temp(None) == MISSING
        assert fmt_hum("") == MISSING
        assert fmt_wind("abc") == MISSING

    def test_rounding_is_consistent_across_commands(self):
        # 27.0 and 27 must not leak into two different messages as "27.0" and "27".
        assert fmt_num(27.0) == fmt_num(27)

    def test_negative_and_zero(self):
        assert fmt_temp(0) == "0°C"
        assert fmt_temp(-4) == "-4°C"


class TestBulletList:
    def test_empty_returns_missing_not_empty_block(self):
        # A heading followed by zero bullets reads as a bug.
        assert bullet_list([]) == MISSING
        assert bullet_list(None) == MISSING
        assert bullet_list(["", "  "]) == MISSING

    def test_renders_marker(self):
        assert bullet_list(["a", "b"]) == "• a\n• b"

    def test_limit_keeps_first_n(self):
        assert bullet_list(["a", "b", "c"], limit=2) == "• a\n• b"


class TestMisc:
    def test_join_rows_drops_empty(self):
        assert join_rows(["a", "", None, "b"]) == "a\nb"

    def test_clamp_truncates_with_ellipsis(self):
        assert clamp("abcdefghij", 5) == "abcd…"

    def test_clamp_leaves_short_text(self):
        assert clamp("abc", 10) == "abc"

    def test_clamp_none(self):
        assert clamp(None, 5) == MISSING
