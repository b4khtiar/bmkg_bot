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

WEATHER_CODES = {
    "0": "Cerah ☀️",
    "1": "Cerah Berawan 🌤️",
    "2": "Cerah Berawan 🌤️",
    "3": "Berawan ☁️",
    "4": "Berawan Tebal ☁️",
    "5": "Udara Kabur 🌫️",
    "10": "Asap 💨",
    "45": "Kabut 🌫️",
    "60": "Hujan Ringan 🌧️",
    "61": "Hujan Sedang 🌧️",
    "62": "Hujan Sedang 🌧️",
    "63": "Hujan Lebat ⛈️",
    "64": "Hujan Deras ⛈️",
    "65": "Hujan Sangat Deras ⛈️",
    "66": "Hujan Beku Ringan 🌧️",
    "67": "Hujan Beku Deras ⛈️",
    "80": "Hujan Lokal 🌦️",
    "81": "Hujan Sedang 🌦️",
    "82": "Hujan Lebat 🌦️",
    "95": "Hujan Petir ⛈️",
    "96": "Hujan Petir ⛈️",
    "97": "Hujan Petir ⛈️",
}

WEATHER_EMOJI = {
    "0": "☀️", "1": "🌤️", "2": "🌤️", "3": "☁️", "4": "☁️",
    "5": "🌫️", "10": "💨", "45": "🌫️",
    "60": "🌧️", "61": "🌧️", "62": "🌧️",
    "63": "⛈️", "64": "⛈️", "65": "⛈️",
    "66": "🌧️", "67": "⛈️",
    "80": "🌦️", "81": "🌦️", "82": "🌦️",
    "95": "⛈️", "96": "⛈️", "97": "⛈️",
}

_VALID_BOT_MODES = {"OPEN", "WHITELIST", "MAINTENANCE"}