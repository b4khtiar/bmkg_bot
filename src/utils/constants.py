# Contoh struktur data (bisa kamu lengkapi sesuai kebutuhan wilayah)
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
    "63": "Hujan Lebat ⛈️",
    "80": "Hujan Lokal 🌦️",
    "95": "Hujan Petir ⛈️",
    "97": "Hujan Petir ⛈️"
}

WEATHER_EMOJI = {
    "0": "☀️", "1": "🌤️", "2": "🌤️", "3": "☁️", "4": "☁️",
    "60": "🌧️", "61": "🌧️", "63": "⛈️", "95": "⛈️", "97": "⛈️"
}

# Daftar Mode Bot
class BotMode:
    OPEN = "OPEN"
    WHITELIST = "WHITELIST"
    MAINTENANCE = "MAINTENANCE"