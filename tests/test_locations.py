"""Resolver /cuaca <lokasi>: ketikan pengguna -> kode adm4.

Cakupan wilayah baru DI Yogyakarta, jadi ketikan di luar pustaka tidak boleh
ditebak melainkan ditolak dengan pesan yang jelas — dan ketikan ambigu harus
dibawa apa adanya supaya pemanggil bisa menawarkan tombol kandidat.
"""
from utils import locations as L


class TestNormalization:
    def test_case_punctuation_and_filler_do_not_matter(self):
        variants = [
            "Wates, Kab. Kulon Progo",
            "wates kulon progo",
            "WATES",
            "  wates,   kab.  kulon   progo  ",
            "Kabupaten Kulon Progo, Desa Wates",
        ]
        statuses = {L.resolve_location(v)["status"] for v in variants}
        assert statuses == {"ok"}, variants

    def test_filler_only_query_is_no_match(self):
        for q in ("", "   ", "kab.", "kota desa"):
            r = L.resolve_location(q)
            assert r["status"] == "none", q


class TestMatchLadder:
    def test_exact_village(self):
        r = L.resolve_location("wonosari")
        assert r["status"] == "ok"
        assert r["matches"][0]["label"] == "Wonosari, Kab. Gunung Kidul"

    def test_province_capital(self):
        """"yogyakarta" harus mengenai Kota Yogyakarta, bukan nama provinsinya."""
        r = L.resolve_location("yogyakarta")
        assert r["status"] == "ok"
        assert r["matches"][0]["label"] == "Kota Yogyakarta"

    def test_district_name_alone_matches(self):
        """'sleman' tidak jadi nama desa, tapi token wilayahnya ada di label."""
        r = L.resolve_location("sleman")
        assert r["status"] == "ok"
        assert "Sleman" in r["matches"][0]["label"]

    def test_ambiguous_district_becomes_a_list(self):
        """"kulon progo" milik dua desa — ditolak politely, bukan dipilih acak."""
        r = L.resolve_location("kulon progo")
        assert r["status"] == "ambiguous"
        labels = [m["label"] for m in r["matches"]]
        assert "Jatimulyo, Kab. Kulon Progo" in labels
        assert "Wates, Kab. Kulon Progo" in labels

    def test_outside_coverage_is_rejected(self):
        assert L.resolve_location("jakarta")["status"] == "none"
        assert L.resolve_location("bandung selatan")["status"] == "none"


class TestEveryLibraryEntryIsResolvable:
    """Entri baru di REGION_DATA harus tetap bisa dicari via nama desanya —

    kalau tidak, keyboard /lokasi menawarkan tempat yang tidak bisa diketik.
    """
    def test_all_entries_reachable_by_village_name(self):
        for province, places in L.REGION_DATA.items():
            for adm4, label in places.items():
                village = label.partition(",")[0]
                r = L.resolve_location(village)
                assert r["status"] in ("ok", "ambiguous"), (adm4, label)
                assert adm4 in [m["adm4"] for m in r["matches"]], (adm4, label)


class TestCallbackSafety:
    def test_known_code_round_trips(self):
        assert L.label_for("34.01.02.2001") == "Wates, Kab. Kulon Progo"

    def test_unknown_code_is_rejected(self):
        """Kode asing dari callback_data yang di-craft tidak boleh lolos."""
        assert L.label_for("31.75.03.1001") is None  # Jakarta Selatan
        assert L.label_for("") is None
        assert L.label_for("DROP TABLE users") is None

    def test_coverage_and_examples_reference_real_labels(self):
        assert "Yogyakarta" in L.coverage_summary()
        examples = L.example_locations()
        assert 0 < len(examples) <= 3
        for label in examples:
            assert L.resolve_location(label)["status"] in ("ok", "ambiguous")
