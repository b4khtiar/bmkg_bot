"""Fixture payload BMKG yang dipangkas, dipakai sebagai kasus terburuk.

Nilai-nilai di sini sengaja dibuat berlebihan: `Dirasakan` panjang sekali,
bullet dampak dan saran banyak, dan tiap field upstream disisipkan karakter
HTML. Fixture "bagus" tidak akan menangkap bug panjang-kapitan maupun
escaping, karena keduanya baru muncul di payloadybayar yang besar.
"""

QUAKE = {
    "Tanggal": "16-10-2026",
    "Jam": "09:42:00 WIB",
    "Magnitude": "5,4",
    "Kedalaman": "30 km",
    "Wilayah": "Pusat gempa berada di 120 km Barat Daya MALUKUTENGGARABRT",
    # Panjang + mengandung & dan < > dari upstream.
    "Dirasakan": (
        "Banda Aceh, Meulaboh, Sigli & Calang "
        "<script>alert(1)</script> " + "merasakan getaran keras. " * 40
    ),
    "Potensi": "Tidak berpotensi tsunami & tidak ada kenaikan air laut",
    "DateTime": "2026-10-16T09:42:00.000 WIB",
    "Shakemap": "shakemap_16oct2026.png",
}

CAP_ALERT = {
    "id": "id-2026-10-16-01",
    "event": "Hujan lebat & petir",
    "severity": "🔴 Bahaya",
    "effective": "14:00",
    "expires": "17:00",
    "province": "DI Yogyakarta & Sleman <b>",
    "sub_districts": ", ".join(f"Kecamatan {i}" for i in range(1, 13)),
    "impacts": [f"banjir lokal di sekitar jalan utama nomor {i}" for i in range(12)],
    "advice": [f"hindari jalan lintasan air nomor {i}" for i in range(12)],
    "image": "https://images.bmkg.go.id/cap/16oct.png",
}

NOWCAST_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Nowcast</title>
    {items}
  </channel>
</rss>
"""


def _xml_escape(value: str) -> str:
    """Escape untuk payload XML.

    Fixture harus XML yang valid, kalau tidak parsermenghasilkan "not
    well-formed" dan yang teruji adalah jalur error, bukan format pesannya.
    Karakter HTML-nya arrives lewat teks CDATA di fixture terpisah.
    """
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _item(title: str, link: str) -> str:
    return (
        "<item>"
        f"<title>{_xml_escape(title)}</title>"
        f"<description>deskripsi</description>"
        f"<link>{_xml_escape(link)}</link>"
        "</item>"
    )


def nowcast_rss(titles=("Peringatan Dini Cuaca DIY",), links=None):
    """RSS nowcast dengan jumlah item yang bisa diatur."""
    links = links or [f"https://www.bmkg.go.id/cap/{i}" for i in range(len(titles))]
    items = "\n".join(_item(t, l) for t, l in zip(titles, links))
    return NOWCAST_RSS.format(items=items)


def cap_alert_xml(
    identifier="2.49.0.1.360.0.2026.10.27.08.34.003",
    sent="2026-10-27T15:00:00+07:00",
    severity="Moderate",
    event="Hujan Lebat dan Petir",
    province="DI Yogyakarta",
    effective="2026-10-27T15:10:00+07:00",
    expires="2026-10-27T17:00:00+07:00",
    image="https://nowcasting.bmkg.go.id/infografis/CYG/2026/10/27/infografis.jpg",
    sub_districts="GIRIMULYO, NANGGULAN",
):
    """CAP XML peringatan dini cuaca, meniru struktur riil BMKG.

    Deskripsi harus cocok dengan regex di ``parse_cap_description``:
    "sebagian wilayah <prov>, khususnya di <desa>. Kondisi", "dampak berupa
    <...>. Masyarakat", "dihimbau untuk <...>. Kondisi".
    """
    description = (
        "Hujan lebat disertai petir akan terjadi pada 27 October 2026, "
        f"15:10 WIB di sebagian wilayah {province}, khususnya di "
        f"{sub_districts}. Kondisi ini berpotensi menimbulkan dampak berupa "
        "jarak pandang berkurang, angin kencang. Masyarakat dihimbau untuk "
        "tetap waspada, mengurangi aktivitas di luar ruangan. Kondisi "
        "diperkirakan dapat berlangsung hingga 27 October 2026, 17:00 WIB."
    )
    return (
        '<?xml version="1.0" ?>\n'
        '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">\n'
        f"  <identifier>{identifier}</identifier>\n"
        f"  <sent>{sent}</sent>\n"
        "  <msgType>Alert</msgType>\n"
        "  <info>\n"
        f"    <severity>{severity}</severity>\n"
        f"    <effective>{effective}</effective>\n"
        f"    <expires>{expires}</expires>\n"
        f"    <event>{event}</event>\n"
        f"    <description>{description}</description>\n"
        f"    <web>{image}</web>\n"
        "  </info>\n"
        "</alert>"
    )


def _slot(local_datetime, t, hu, ws, wd, weather, desc, tp=0):
    """Satu slot prakiraan, mengikuti field yang dipakai parser."""
    return {
        "datetime": local_datetime.replace(" ", "T") + "Z",
        "local_datetime": local_datetime,
        "t": t,
        "tcc": t + 4,
        "tp": tp,
        "weather": weather,
        "weather_desc": desc,
        "wd_deg": 146,
        "wd": wd,
        "ws": ws,
        "hu": hu,
        "time_index": local_datetime[11:13] + "-" + local_datetime[14:16],
    }


# Struktur mengikuti API BMKG yang sedang berjalan: `data` berisi SATU elemen,
# dan `cuaca` di dalamnya adalah daftar grup, satu grup per hari. Fixture yang
# salah di sini akan menguji jalur error, bukan format pesan.
WEATHER_JSON = {
    "lokasi": {
        "adm4": "34.01.09.2001",
        "provinsi": "Daerah Istimewa Yogyakarta",
        "kotkab": "Kulon Progo",
        "kecamatan": "Girimulyo",
        "desa": "Jatimulyo",
        "timezone": "Asia/Jakarta",
    },
    "data": [
        {
            "lokasi": {
                "adm4": "34.01.09.2001",
                "desa": "Jatimulyo",
                "kecamatan": "Girimulyo",
                "kabupaten": "Kulon Progo",
                "provinsi": "Daerah Istimewa Yogyakarta",
            },
            "cuaca": [
                # Hari 1
                [
                    _slot("2026-10-16 06:00:00", 24, 82, 6, "SE", 3, "Berawan"),
                    _slot("2026-10-16 09:00:00", 27, 78, 9, "B", 2, "Cerah Berawan & berangin"),
                    _slot("2026-10-16 12:00:00", 31, 70, 12, "S", 1, "Cerah Berawan"),
                    _slot("2026-10-16 15:00:00", 30, 82, 14, "S", 95, "Hujan Petir", 18),
                    _slot("2026-10-16 18:00:00", 26, 88, 11, "SE", 63, "Hujan Lebat", 22),
                    _slot("2026-10-16 21:00:00", 25, 90, 8, "E", 60, "Hujan Ringan", 4),
                ],
                # Hari 2
                [
                    _slot("2026-10-17 06:00:00", 24, 85, 5, "SE", 3, "Berawan"),
                    _slot("2026-10-17 09:00:00", 26, 80, 7, "B", 3, "Berawan"),
                    _slot("2026-10-17 12:00:00", 28, 76, 8, "B", 1, "Cerah Berawan"),
                    _slot("2026-10-17 15:00:00", 29, 75, 9, "S", 60, "Hujan Ringan", 6),
                    _slot("2026-10-17 18:00:00", 27, 80, 10, "SE", 60, "Hujan Ringan", 5),
                    _slot("2026-10-17 21:00:00", 25, 87, 7, "E", 3, "Berawan"),
                ],
                # Hari 3
                [
                    _slot("2026-10-18 06:00:00", 23, 88, 5, "SE", 3, "Berawan"),
                    _slot("2026-10-18 09:00:00", 25, 83, 6, "B", 2, "Cerah Berawan"),
                    _slot("2026-10-18 12:00:00", 27, 79, 7, "B", 1, "Cerah Berawan"),
                    _slot("2026-10-18 15:00:00", 28, 77, 9, "S", 2, "Cerah Berawan"),
                    _slot("2026-10-18 18:00:00", 26, 84, 8, "SE", 60, "Hujan Ringan", 4),
                    _slot("2026-10-18 21:00:00", 24, 89, 6, "E", 3, "Berawan"),
                ],
            ],
        }
    ],
}
