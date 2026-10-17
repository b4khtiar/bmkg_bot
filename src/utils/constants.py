# Struktur data wilayah (bisa kamu lengkapi sesuai kebutuhan)
REGION_DATA = {
    "DI Yogyakarta": {
        "34.01.09.2001": "Jatimulyo, Kab. Kulon Progo",
        "34.01.02.2001": "Wates, Kab. Kulon Progo",
        "34.02.08.2003": "Bantul Kota, Kab. Bantul",
        "34.04.12.2001": "Tridadi, Kab. Sleman",
        "34.03.01.2001": "Wonosari, Kab. Gunung Kidul",
        "34.71.04.1003": "Kota Yogyakarta"
    }
}

# Kode provinsi dari 2 digit pertama adm_code
PROVINCE_MAP = {
    "11": "Aceh",
    "12": "Sumatera Utara",
    "13": "Sumatera Barat",
    "14": "Riau",
    "15": "Jambi",
    "16": "Sumatera Selatan",
    "17": "Bengkulu",
    "18": "Lampung",
    "19": "Kep. Bangka Belitung",
    "21": "Kep. Riau",
    "31": "DKI Jakarta",
    "32": "Jawa Barat",
    "33": "Jawa Tengah",
    "34": "DI Yogyakarta",
    "35": "Jawa Timur",
    "36": "Banten",
    "51": "Bali",
    "52": "Nusa Tenggara Barat",
    "53": "Nusa Tenggara Timur",
    "61": "Kalimantan Barat",
    "62": "Kalimantan Tengah",
    "63": "Kalimantan Selatan",
    "64": "Kalimantan Timur",
    "65": "Kalimantan Utara",
    "71": "Sulawesi Utara",
    "72": "Sulawesi Tengah",
    "73": "Sulawesi Selatan",
    "74": "Sulawesi Tenggara",
    "75": "Gorontalo",
    "76": "Sulawesi Barat",
    "81": "Maluku",
    "82": "Maluku Utara",
    "91": "Papua Barat",
    "94": "Papua",
    "95": "Papua Pegunungan",
    "96": "Papua Selatan",
    "97": "Papua Tengah",
}

def get_province_name(adm_code):
    if not adm_code or len(adm_code) < 2:
        return None
    return PROVINCE_MAP.get(adm_code[:2])


# Tabel kode cuaca (label, emoji, grup foto, pool insight) tidak lagi ada di
# sini — semuanya diturunkan dari satu tabel di `utils/weather_table.py`.
# WEATHER_CODES, WEATHER_EMOJI, dan IMAGE_WEATHER_GROUPS yang sebelumnya hidup
# di file ini sudah dihapus; lihat modul tersebut.

_VALID_BOT_MODES = {"OPEN", "WHITELIST", "MAINTENANCE"}