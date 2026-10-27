"""Resolver /cuaca <lokasi>: ketikan pengguna -> kode adm4.

Pustaka memuat 25.271 desa dari enam provinsi Pulau Jawa, jadi nama umum
("Wonosari", 30 desa) nyaris selalu ambigu — itu perilaku yang benar, bukan
kegagalan: pemanggil menawarkan tombol kandidat. Ketikan di luar cakupan
dijawab "none" dengan contoh yang valid, bukan ditebak. Indeks eksak dibuat
precomputed saat impor, jadi sweep seluruh pustaka di sini tetap murah.
"""
from utils import locations as L


class TestNormalization:
    def test_case_punctuation_and_filler_do_not_matter(self):
        # "Pisangan Baru" dipakai tepat 1 desa, jadi semua bentuk ketikan
        # ini diharapkan mengenai entri yang sama dengan status "ok".
        variants = [
            "Pisangan Baru, Kota Jakarta Timur",
            "pisangan baru jakarta timur",
            "PISANGAN BARU",
            "  pisangan   baru,   kota  jakarta   timur  ",
            "Kota Jakarta Timur, Desa Pisangan Baru",
        ]
        statuses = {L.resolve_location(v)["status"] for v in variants}
        assert statuses == {"ok"}, variants

    def test_filler_only_query_is_no_match(self):
        for q in ("", "   ", "kab.", "kota desa"):
            r = L.resolve_location(q)
            assert r["status"] == "none", q


class TestMatchLadder:
    def test_exact_full_label(self):
        r = L.resolve_location("Karangwuni, Kab. Kulon Progo")
        assert r["status"] == "ok"
        assert r["matches"][0]["adm4"] == "34.01.02.2001"

    def test_reordered_full_label(self):
        """'Kulon Progo Karangwuni' — urutan kata bolak-balik tetap ketemu."""
        r = L.resolve_location("kulon progo karangwuni")
        assert r["status"] == "ok"
        assert r["matches"][0]["adm4"] == "34.01.02.2001"

    def test_unique_village_name(self):
        """'sleman' nyaris selalu dianggap nama wilayah, tapi juga nama satu
        desa — village tier lebih dulu daripada district tier."""
        r = L.resolve_location("sleman")
        assert r["status"] == "ok"
        assert r["matches"][0]["label"] == "Sleman, Kab. Indramayu"
        assert r["matches"][0]["adm4"] == "32.12.12.2001"

    def test_java_multiprovince_coverage(self):
        """Lokasi di luar DIY tetap valid — Jakarta TImur via desanya."""
        r = L.resolve_location("pisangan baru")
        assert r["status"] == "ok"
        assert r["matches"][0]["adm4"] == "31.75.01.1001"
        assert r["matches"][0]["label"] == "Pisangan Baru, Kota Jakarta Timur"

    def test_common_village_name_is_ambiguous(self):
        """'wonosari' dipakai 30 desa — boleh ambigu, asal semua kandidat
        kelas satu (nama desa persis), termasuk versi DIY-nya."""
        r = L.resolve_location("wonosari")
        assert r["status"] == "ambiguous"
        adm4s = {m["adm4"] for m in r["matches"]}
        assert "34.03.01.2001" in adm4s, "Wonosari, Kab. Gunung Kidul"
        assert len(r["matches"]) == 30

    def test_ambiguous_district_name(self):
        """'kulon progo' bukan nama desa — substring tier memuat semua desa
        Kulon Progo, ambigu dan jujur soal itu."""
        r = L.resolve_location("kulon progo")
        assert r["status"] == "ambiguous"
        assert all("Kulon Progo" in m["label"] for m in r["matches"])
        assert len(r["matches"]) == 88

    def test_outside_coverage_is_rejected(self):
        assert L.resolve_location("amsterdam")["status"] == "none"
        assert L.resolve_location("pontianak")["status"] == "none"
        assert L.resolve_location("bandung selatan")["status"] == "none"


class TestEveryLibraryEntryIsResolvable:
    """Entri baru di REGION_DATA harus tetap bisa dicari via nama desanya —
    kalau tidak, keyboard /lokasi menawarkan tempat yang tidak bisa diketik."""

    def test_all_entries_reachable_by_village_name(self):
        swept = 0
        for province, places in L.REGION_DATA.items():
            for adm4, label in places.items():
                swept += 1
                village = label.partition(",")[0]
                if not L._normalize(village):
                    # Nama desa yang setelah normalisasi kosong — sungguhan
                    # ada: desa "Kelurahan", Kec. Jambu, Kab. Semarang. Desa
                    # itu tidak bisa dijangkau lewat nama desanya (tidak punya
                    # nama yang bermakna); picker keyboard tetap jalannya.
                    continue
                r = L.resolve_location(village)
                assert r["status"] in ("ok", "ambiguous"), (adm4, label)
                assert adm4 in [m["adm4"] for m in r["matches"]], (adm4, label)
        assert swept > 25000, swept

    def test_all_six_java_provinces_present(self):
        assert set(L.REGION_DATA) == {
            "DI Yogyakarta", "Banten", "DKI Jakarta",
            "Jawa Barat", "Jawa Tengah", "Jawa Timur"}


class TestCallbackSafety:
    def test_known_code_round_trips(self):
        assert L.label_for("34.01.02.2001") == "Karangwuni, Kab. Kulon Progo"
        assert L.label_for("31.75.01.1001") == "Pisangan Baru, Kota Jakarta Timur"

    def test_unknown_code_is_rejected(self):
        """Kode asing dari callback_data yang di-craft tidak boleh lolos."""
        assert L.label_for("99.99.99.9999") is None
        assert L.label_for("") is None
        assert L.label_for("DROP TABLE users") is None

    def test_coverage_and_examples_reference_real_labels(self):
        assert "Yogyakarta" in L.coverage_summary()
        examples = L.example_locations()
        assert 0 < len(examples) <= 3
        for label in examples:
            r = L.resolve_location(label)
            assert r["status"] in ("ok", "ambiguous"), label
