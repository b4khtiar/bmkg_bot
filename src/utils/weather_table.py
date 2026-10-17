"""Satu tabel untuk semua kode cuaca BMKG.

Sebelumnya ada empat peta terpisah untuk kode yang sama, dan semuanya sudah
berbeda satu sama lain:

* ``WEATHER_CODES`` (label + emoji) dan ``WEATHER_EMOJI`` (emoji saja) — dua
  peta untuk satu hal, sehingga harus dijaga sinkron manual;
* ``IMAGE_WEATHER_GROUPS`` (pilihan foto) — kode 66 "Hujan Beku Ringan"
  berada di ``heavy_rain``, jadi gerimis beku difoto dengan gambar
  hujan lebat;
* ``insight_templates.WEATHER_CODE_GROUPS`` (kalimat insight) — satu-satunya
  yang tahu kode 50-57 (gerimis), sehingga kode itu tampil sebagai ``❓``
  tanpa foto di semua perintah lain. Set ``clear``-nya juga memuat kode 3
  ("Berawan"), sehingga hari mendung penuh bisa menghasilkan "Hari cerah
  sempurna! Cocok untuk jemur pakaian".

Tabel di bawah mengganti keempatnya. Semua himpunan turunan dihitung dari
``WEATHER_CONDITIONS``, bukan ditulis ulang, sehingga mustahil ada lagi kode
yang punya label tapi tidak punya foto atau kalimat insight — dan itu
dijaga ``tests/test_weather_table.py``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Condition:
    """Satu kondisi cuaca BMKG beserta seluruh sifat turunan."""

    code: int
    label: str
    emoji: str
    #: Grup foto Unsplash: clear/cloudy/foggy/light_rain/heavy_rain/thunderstorm
    photo_group: str
    #: Nama pool template di insight_templates.
    insight_pool: str
    #: "clear" | "partly" | "cloudy" | "obscured" — untuk menentukan langit.
    sky: str
    #: Apakah kode ini berarti ada air jatuh (hujan, gerimis, es, salju).
    wet: bool = False


# Urutan foto: nilai lebih tinggi = kondisi lebih dramatis, jadi foto yang
# dipilih adalah yang palingعاتhdalam, bukan yang pertama muncul.
PHOTO_GROUP_SEVERITY = {
    "clear": 1,
    "cloudy": 2,
    "foggy": 3,
    "light_rain": 4,
    "heavy_rain": 5,
    "thunderstorm": 6,
}


def _c(code, label, emoji, photo_group, insight_pool, sky, wet=False):
    return Condition(code, label, emoji, photo_group, insight_pool, sky, wet)


# Kode dan label mengikuti dokumentasi BMKG. Emoji diseragamkan berdasarkan
# intensitas, bukan asal: sebelum ini 62 ("Hujan Sedang") memakai 🌧️ sementara
# 81 ("Hujan Sedang") memakai 🌦️ — dua kode dengan label identik tampil berbeda.
WEATHER_CONDITIONS = {
    c.code: c
    for c in [
        _c(0, "Cerah", "☀️", "clear", "clear", "clear"),
        _c(1, "Cerah Berawan", "🌤️", "clear", "clear", "partly"),
        _c(2, "Cerah Berawan", "🌤️", "clear", "clear", "partly"),
        _c(3, "Berawan", "☁️", "cloudy", "cloudy", "cloudy"),
        _c(4, "Berawan Tebal", "☁️", "cloudy", "cloudy", "cloudy"),
        _c(5, "Kabut", "🌫️", "foggy", "haze", "obscured"),
        # 6-16 adalah varian kabut asap. Semuanya ada di kode BMKG dan hanya
        # 5, 10, dan 45 yang pernah dipetakan; sisanya tampil ❓.
        _c(6, "Kabut Ringan", "🌫️", "foggy", "haze", "obscured"),
        _c(7, "Kabut", "🌫️", "foggy", "haze", "obscured"),
        _c(8, "Kabut Ringan", "🌫️", "foggy", "haze", "obscured"),
        _c(9, "Kabut", "🌫️", "foggy", "haze", "obscured"),
        _c(10, "Asap", "💨", "foggy", "haze", "obscured"),
        _c(11, "Asap Ringan", "💨", "foggy", "haze", "obscured"),
        _c(12, "Asap", "💨", "foggy", "haze", "obscured"),
        _c(13, "Kabut dan Asap", "🌫️", "foggy", "haze", "obscured"),
        _c(14, "Kabut Ringan", "🌫️", "foggy", "haze", "obscured"),
        _c(15, "Kabut", "🌫️", "foggy", "haze", "obscured"),
        _c(16, "Kabut", "🌫️", "foggy", "haze", "obscured"),
        # 17-29 adalah varian petir. "Hujan dan Petir" sangat lazim di
        # Indonesia dan sebelumnya tidak terpetakan sama sekali.
        _c(17, "Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy"),
        _c(18, "Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy"),
        _c(19, "Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy"),
        _c(24, "Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy"),
        _c(25, "Hujan dan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(26, "Hujan Ringan dan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(27, "Hujan Sedang dan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(28, "Hujan dan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(29, "Hujan Sedang dan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        # 37 "Angin Kuat" sebelumnya tidak ada di peta mana pun dan tampil ❓.
        _c(37, "Angin Kuat", "💨", "cloudy", "wind", "cloudy"),
        _c(45, "Geras", "🌫️", "foggy", "haze", "obscured"),
        _c(50, "Gerimis Ringan", "🌦️", "light_rain", "drizzle", "cloudy", wet=True),
        _c(51, "Gerimis", "🌦️", "light_rain", "drizzle", "cloudy", wet=True),
        _c(52, "Gerimis Ringan", "🌦️", "light_rain", "drizzle", "cloudy", wet=True),
        _c(53, "Gerimis", "🌦️", "light_rain", "drizzle", "cloudy", wet=True),
        _c(54, "Gerimis Deras", "🌦️", "heavy_rain", "drizzle", "cloudy", wet=True),
        _c(55, "Gerimis Deras", "🌦️", "heavy_rain", "drizzle", "cloudy", wet=True),
        _c(56, "Gerimis Beku", "🌧️", "light_rain", "drizzle", "cloudy", wet=True),
        _c(57, "Gerimis Beku Deras", "🌧️", "heavy_rain", "drizzle", "cloudy", wet=True),
        _c(60, "Hujan Ringan", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(61, "Hujan Sedang", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(62, "Hujan Sedang", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(63, "Hujan Lebat", "⛈️", "heavy_rain", "heavy_rain", "cloudy", wet=True),
        _c(64, "Hujan Deras", "⛈️", "heavy_rain", "heavy_rain", "cloudy", wet=True),
        _c(65, "Hujan Sangat Deras", "⛈️", "heavy_rain", "heavy_rain", "cloudy", wet=True),
        # 66 dipindah dari heavy_rain ke light_rain: labelnya "Hujan Beku
        # Ringan", dan foto hujan lebat untuk gerimis beku jelas salah.
        _c(66, "Hujan Beku Ringan", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(67, "Hujan Beku Deras", "⛈️", "heavy_rain", "heavy_rain", "cloudy", wet=True),
        _c(80, "Hujan Lokal", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(81, "Hujan Sedang", "🌧️", "light_rain", "light_rain", "cloudy", wet=True),
        _c(82, "Hujan Lebat", "⛈️", "heavy_rain", "heavy_rain", "cloudy", wet=True),
        _c(95, "Hujan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(96, "Hujan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
        _c(97, "Hujan Petir", "⛈️", "thunderstorm", "thunderstorm", "cloudy", wet=True),
    ]
}

# Kueri Unsplash per kode. Satu kueri per kode (bukan per grup) supaya dua
# kondisi dalam grup yang sama tidak selalu memunculkan foto yang sama.
WEATHER_QUERY_MAP = {
    "0": "bright sunny blue sky",
    "1": "sunny sky scattered clouds",
    "2": "partly cloudy sunny day",
    "3": "cloudy grey sky",
    "4": "overcast dark clouds",
    "5": "haze city skyline",
    "6": "light fog morning street",
    "7": "foggy road visibility",
    "8": "thin fog morning",
    "9": "dense fog road",
    "10": "smoky haze sky",
    "11": "light smoke haze",
    "12": "smoke filled sky",
    "13": "fog and smoke city",
    "14": "light foggy morning",
    "15": "thick fog morning",
    "16": "fog bank landscape",
    "17": "lightning flash sky",
    "18": "thunder flash night sky",
    "19": "storm lightning strike",
    "24": "lightning thunderstorm sky",
    "25": "rain and thunderstorm",
    "26": "light rain lightning",
    "27": "moderate rain lightning",
    "28": "rain thunderstorm dramatic",
    "29": "heavy rain lightning storm",
    "37": "strong wind trees bending",
    "45": "foggy misty landscape morning",
    "50": "light drizzle rain drops",
    "51": "drizzle outside window",
    "52": "fine drizzle grey day",
    "53": "steady drizzle rain",
    "54": "heavy drizzle wet pavement",
    "55": "downpour drizzle streets",
    "56": "freezing drizzle icy",
    "57": "freezing rain ice storm",
    "60": "light rain drops window",
    "61": "rainy day umbrella street",
    "62": "rain clouds grey sky",
    "63": "heavy rain storm street",
    "64": "tropical rain downpour",
    "65": "flood rain storm",
    "66": "cold rain frost",
    "67": "freezing rain ice",
    "80": "tropical rain shower",
    "81": "rain shower umbrella",
    "82": "rainstorm dark clouds",
    "95": "thunderstorm lightning sky",
    "96": "lightning storm dramatic clouds",
    "97": "severe thunderstorm night",
}

# Kode salju (38, 40-44) sengaja tidak dipetakan: BMKG tidak menghasilkannya
# untuk wilayah Indonesia, dan memetakannya hanya menambah permukaan yang
# harus dirawat tanpa pernah terpakai.


UNKNOWN_EMOJI = "❓"


def condition(code) -> Condition | None:
    """Ambil kondisi untuk kode apa pun; ``None`` bila kode tidak dikenal."""
    try:
        return WEATHER_CONDITIONS.get(int(code))
    except (TypeError, ValueError):
        return None


def label(code, fallback: str | None = None) -> str:
    """``"Hujan Lebat ⛈️"``, atau fallback milik BMKG bila kode tak dikenal."""
    cond = condition(code)
    if cond is None:
        return fallback or UNKNOWN_EMOJI
    return f"{cond.label} {cond.emoji}"


def emoji(code) -> str:
    """Emoji kondisi, atau ``❓`` untuk kode yang tidak dipetakan."""
    cond = condition(code)
    return cond.emoji if cond else UNKNOWN_EMOJI


def photo_group(code) -> str | None:
    cond = condition(code)
    return cond.photo_group if cond else None


def is_wet(code) -> bool:
    """True bila kode berarti ada air jatuh (hujan, gerimis, es).

    Catatan: ini **bukan** predicate yang tepat untuk memilih ikon harian.
    Kode 17-24 ("Petir") adalah petir tanpa hujan, jadi ``wet``-nya False,
    padahal ikon ``☀️`` untuk hari badai petir justru menyesatkan. Untuk ikon
    harian pakai :func:`is_wet_or_stormy`.
    """
    cond = condition(code)
    return bool(cond and cond.wet)


def is_wet_or_stormy(code) -> bool:
    """True bila kondisi membuat hari terasa basah ATAU berbahaya.

    Dipakai untuk ikon ringkasan harian, di mana yang penting bukan
    presipisasi fisika melainkan apakah pengguna perlu payung.
    """
    cond = condition(code)
    return bool(cond and (cond.wet or cond.photo_group == "thunderstorm"))


def photo_severity(code) -> int:
    cond = condition(code)
    return PHOTO_GROUP_SEVERITY.get(cond.photo_group, 0) if cond else 0


def query_for(code) -> str | None:
    return WEATHER_QUERY_MAP.get(str(code))


def _codes_where(predicate) -> frozenset:
    return frozenset(c.code for c in WEATHER_CONDITIONS.values() if predicate(c))


# Himpunan turunan. Diturunkan, bukan ditulis ulang.
THUNDERSTORM_CODES = _codes_where(lambda c: c.insight_pool == "thunderstorm")
HEAVY_RAIN_CODES = _codes_where(lambda c: c.insight_pool == "heavy_rain")
LIGHT_RAIN_CODES = _codes_where(lambda c: c.insight_pool == "light_rain")
DRIZZLE_CODES = _codes_where(lambda c: c.insight_pool == "drizzle")
HAZE_CODES = _codes_where(lambda c: c.insight_pool == "haze")
WIND_CODES = _codes_where(lambda c: c.insight_pool == "wind")
CLEAR_SKY_CODES = _codes_where(lambda c: c.sky == "clear")
PARTLY_SKY_CODES = _codes_where(lambda c: c.sky == "partly")
CLOUDY_SKY_CODES = _codes_where(lambda c: c.sky == "cloudy")

#: Semua kode yang berarti ada air jatuh (hujan, gerimis, es, salju). Dipakai
#: untuk ikon "🌧️" pada ringkasan harian. Sebelumnya didefinisikan sebagai
#: ``set(range(60, 83))`` di satu modul dan sebagai ``IMAGE_WEATHER_GROUPS``
#: di modul lain — dua definisi yang tidak pernah dibandingkan.
WET_CODES = _codes_where(lambda c: c.wet)

#: Kode yang terpetakan di tabel.
def known_codes() -> frozenset:
    return frozenset(WEATHER_CONDITIONS)


def missing_queries() -> list[int]:
    """Kode tanpa kueri foto — akan tampil tanpa gambar."""
    return sorted(c for c in WEATHER_CONDITIONS if str(c) not in WEATHER_QUERY_MAP)


def validation_errors() -> list[str]:
    """Masalah integritas tabel. Dipakai tes dan dicek saat startup."""
    problems = []
    for code in missing_queries():
        problems.append(f"kode {code} tidak punya kueri Unsplash")
    for cond in WEATHER_CONDITIONS.values():
        if cond.photo_group not in PHOTO_GROUP_SEVERITY:
            problems.append(f"kode {cond.code} punya grup foto tak dikenal: {cond.photo_group}")
        if not cond.label:
            problems.append(f"kode {cond.code} tidak punya label")
        if not cond.emoji:
            problems.append(f"kode {cond.code} tidak punya emoji")
    # Kode dengan label identik harus tampil identik, kalau tidak pengguna
    # melihat "Hujan Sedang" dengan dua ikon berbeda.
    by_label = {}
    for cond in WEATHER_CONDITIONS.values():
        by_label.setdefault(cond.label, set()).add(cond.emoji)
    for label_text, emojis in by_label.items():
        if len(emojis) > 1:
            problems.append(f'label "{label_text}" punya lebih dari satu emoji: {sorted(emojis)}')
    return problems


def log_problems(logger) -> None:
    """Laporkan masalah tabel saat startup.

    Drift sebelumnya hanya terlihat sebagai ``❓`` di satu pesan, tanpa jejak
    di mana pun. Ini membuat masalahnya diam-diam, jadi dicek sekali di
    startup — bukan digagalkan, karena bot masih berguna saat BMKG menambah
    kode baru.
    """
    problems = validation_errors()
    if not problems:
        logger.info(
            f"Tabel cuaca OK: {len(WEATHER_CONDITIONS)} kode, "
            f"{len(WEATHER_QUERY_MAP)} kueri foto"
        )
        return
    for problem in problems:
        logger.error(f"Tabel cuaca: {problem}")
    unmapped = len(WEATHER_QUERY_MAP) - len(WEATHER_CONDITIONS)
    if unmapped:
        logger.warning(
            f"{unmapped} kueri foto tidak punya kode di tabel — "
            "kemungkinan ada kode yang dihapus"
        )
