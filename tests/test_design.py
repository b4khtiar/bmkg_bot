from utils.design import CAPTION_LIMIT, SOURCE_LINE, compose, section


def _over(n: int) -> str:
    return "x" * n


class TestBudget:
    def test_never_exceeds_caption_limit(self):
        # The bug this guards: an over-length broadcast was rejected by Telegram,
        # retried, and silently dropped. compose must always return something
        # deliverable.
        result = compose(
            head="🚨 JUDUL",
            blocks=[(10, _over(4000)), (80, _over(4000)), (60, _over(4000))],
            banner="⚠️ cadangan",
            photo="http://x/y.jpg",
            photographer="Some One",
        )
        assert len(result["text"]) <= CAPTION_LIMIT

    def test_photo_credit_only_when_photo_ships(self):
        """Kredit tanpa foto adalah kebohongan yang terlihat oleh pengguna."""
        with_photo = compose(
            head="H", blocks=[(10, "small")],
            photo="p.jpg", photographer="Photog",
        )
        assert with_photo["photo_url"] == "p.jpg"
        assert "Photog" in with_photo["text"]

        # Once the body is trimmed to the headline, the photo fits again and
        # its credit legitimately returns with it.
        too_long = compose(
            head="H", blocks=[(10, _over(5000))],
            photo="p.jpg", photographer="Photog",
        )
        if too_long["photo_url"]:
            assert "Photog" in too_long["text"]
        else:
            assert "Photog" not in too_long["text"]

    def test_credit_disappears_with_a_photo_that_does_not_ship(self):
        result = compose(
            head="H", blocks=[(10, _over(980))],
            photo="p.jpg", photographer="Photog",
        )
        # 980 chars of body + head + source fits as text, but not once the
        # ~50-char credit is appended — so the photo must be dropped, and the
        # credit with it.
        assert result["photo_url"] is None
        assert "Photog" not in result["text"]

    def test_photo_dropped_when_caption_cannot_fit_it(self):
        result = compose(
            head="H", blocks=[(10, _over(960))],
            photo="p.jpg", photographer="Photog",
        )
        # Fits as plain text, not as a captioned photo once the credit is added.
        assert len(result["text"]) <= CAPTION_LIMIT
        assert result["photo_url"] is None
        assert result["photographer"] is None

    def test_photo_without_photographer_still_ships(self):
        # A photo with no credit available is still worth sending.
        result = compose(head="H", blocks=[(10, "small")], photo="p.jpg")
        assert result["photo_url"] == "p.jpg"
        assert "Unsplash" not in result["text"]


class TestTruncationOrder:
    def test_low_priority_dropped_first(self):
        """Safety advice is the first thing trimmed; the headline survives."""
        result = compose(
            head="🚨 PERINGATAN",
            blocks=[
                (10, "KEJADIAN penting untuk bertindak"),
                (80, "SARAN KEAMANAN " + _over(3000)),
            ],
            photo="p.jpg", photographer="P",
        )
        assert "KEJADIAN" in result["text"]
        assert "SARAN" not in result["text"]

    def test_high_priority_kept_when_it_fits_alone(self):
        result = compose(
            head="H",
            blocks=[(10, "PENTING"), (90, "opsional " + _over(5000))],
        )
        assert "PENTING" in result["text"]
        assert len(result["text"]) <= CAPTION_LIMIT

    def test_all_blocks_dropped_still_delivers_the_headline(self):
        result = compose(
            head="🚨 PERINGATAN DINI",
            blocks=[(50, _over(9000))],
            photo="p.jpg", photographer="P",
        )
        assert "PERINGATAN DINI" in result["text"]
        assert len(result["text"]) <= CAPTION_LIMIT

    def test_truncation_is_disclosed_not_silent(self):
        # Silent trimming reads as a bug; a short disclosure reads as honest.
        result = compose(
            head="H", blocks=[(10, "a"), (80, _over(5000))],
        )
        assert "dipangkas" in result["text"]


class TestStructure:
    def test_no_disclosure_when_nothing_dropped(self):
        result = compose(head="H", blocks=[(10, "a")])
        assert "dipangkas" not in result["text"]

    def test_source_line_always_present(self):
        for blocks in ([], [(10, "a")], [(10, _over(9000))]):
            result = compose(head="H", blocks=blocks)
            assert SOURCE_LINE in result["text"]

    def test_banner_comes_first(self):
        result = compose(head="H", blocks=[(10, "a")], banner="⚠️ cadangan")
        assert result["text"].startswith("⚠️ cadangan")

    def test_banner_omitted_when_absent(self):
        assert not compose(head="H", blocks=[(10, "a")])["text"].startswith("⚠️")

    def test_empty_blocks_are_dropped_not_rendered_blanks(self):
        result = compose(head="H", blocks=[(10, ""), (20, None), (30, "isi")])
        assert "\n\n\n" not in result["text"]

    def test_banner_counts_against_budget(self):
        result = compose(
            head="H", blocks=[(10, _over(1010))],
            banner="⚠️ " + _over(50),
        )
        assert len(result["text"]) <= CAPTION_LIMIT

    def test_custom_budget_respected(self):
        result = compose(head="H", blocks=[(10, _over(200))], budget=100)
        assert len(result["text"]) <= 100

    def test_section_label_is_delimited(self):
        assert section("Dampak") == "━━━ Dampak ━━━"
