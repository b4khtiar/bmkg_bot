import httpx
import logging
from datetime import datetime
import xml.etree.ElementTree as ET
from utils.constants import WEATHER_CODES, WEATHER_EMOJI

def parse_weather_daily_brief(json_response):
    """
    Parser khusus laporan pagi untuk ringkasan seharian.
    """
    try:
        weather_list = json_response.get('data', [])[0].get('cuaca', [])[0]
        lokasi = json_response.get('lokasi', {})
        
        # Ambil 4 titik waktu utama (Pagi, Siang, Sore, Malam)
        # Biasanya index 0, 1, 2, 3 mewakili rentang waktu tersebut di data BMKG
        summary_points = []
        labels = ["Pagi", "Siang", "Sore", "Malam"]
        
        for i, label in enumerate(labels):
            if i < len(weather_list):
                w = weather_list[i]
                icon = WEATHER_EMOJI.get(str(w['weather']), "☁️")
                temp = f"{w['t']}°C"
                summary_points.append(f"{label} {icon} {temp}")

        # Gabungkan
        grid_view = "\n".join(summary_points)
        
        msg = (
            f"<b>📅 DAILY BRIEFING:</b>\n{lokasi.get('desa')}\n\n"
            f"<code>{grid_view}</code>\n\n"
            f"💡 <i>Tip: Cuaca hari ini didominasi {weather_list[0]['weather_desc']}.</i>"
        )
        return msg
    except:
        return "Gagal memproses briefing pagi."

def parse_weather_data(json_response, time_label):
    """
    json_response: Full JSON dari API BMKG (adm4)
    time_label: 'Pagi', 'Siang', 'Sore', 'Malam', atau 'Saat Ini'
    """
    try:
        # Navigasi ke list cuaca: data -> index 0 -> cuaca -> index 0
        weather_list = json_response.get('data', [])[0].get('cuaca', [])[0]
        lokasi = json_response.get('lokasi', {})
        nama_tempat = f"{lokasi.get('desa')}, {lokasi.get('kecamatan')}"

        now = datetime.now()
        selected = None

        # Strategi Pencarian:
        if time_label == "Saat Ini":
            # Cari yang local_datetime-nya paling dekat dengan jam sekarang
            selected = min(weather_list, key=lambda x: abs(
                datetime.strptime(x['local_datetime'], "%Y-%m-%d %H:%M:%S") - now
            ))
        else:
            # Cari berdasarkan jam spesifik (Pagi: 07:00, Sore: 17:00)
            target_hour = 7 if time_label == "Pagi" else 16 # Sore di data ini jam 16
            for w in weather_list:
                dt_obj = datetime.strptime(w['local_datetime'], "%Y-%m-%d %H:%M:%S")
                if dt_obj.hour >= target_hour:
                    selected = w
                    break
        
        if not selected:
            selected = weather_list[0]

        # Ambil data spesifik
        temp = selected.get('t')
        hu = selected.get('hu') # Kelembapan
        ws = selected.get('ws') # Kecepatan Angin
        wd = selected.get('wd') # Arah Angin
        desc = selected.get('weather_desc')
        icon_code = str(selected.get('weather'))

        # Gunakan emoji dari constants jika ada, jika tidak pakai weather_desc dari API
        status_emoji = WEATHER_CODES.get(icon_code, desc)

        msg = (f"<b>🌤️ LAPORAN CUACA {time_label.upper()}</b>\n"
               f"📍 {nama_tempat}\n"
               f"📅 {selected.get('local_datetime')}\n\n"
               f"Kondisi: <b>{status_emoji}</b>\n"
               f"Suhu: {temp}°C\n"
               f"Kelembapan: {hu}%\n"
               f"Angin: {ws} km/jam (Arah {wd})\n\n"
               f"<i>Sumber: BMKG</i>")
        return msg
    except (IndexError, KeyError, TypeError) as e:
        return f"⚠️ Gagal memproses data cuaca wilayah ini. ({e})"

def parse_nowcast_rss(xml_string, user_city_name = "Yogyakarta"):
    """
    Scan RSS untuk mencari berita yang relevan dengan kota user.
    """
    root = ET.fromstring(xml_string)
    items = root.findall(".//item")
    relevant_links = []

    for item in items:
        title = item.find("title").text
        link = item.find("link").text
        
        # Filter awal: Jika nama Kota/Kabupaten user ada di judul
        if user_city_name.lower() in title.lower():
            relevant_links.append(link)
            
    return relevant_links

def parse_cap_detail(xml_string):
    """
    Parse format CAP (Common Alerting Protocol) dari link detail.
    """
    # Note: CAP XML menggunakan namespace
    ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
    root = ET.fromstring(xml_string)
    info = root.find("cap:info", ns)
    
    if info is not None:
        return {
            "id": root.find("cap:identifier", ns).text,
            "headline": info.find("cap:headline", ns).text,
            "description": info.find("cap:description", ns).text,
            "instruction": "Tetap waspada, kurangi aktivitas luar ruangan.",
            "expires": info.find("cap:expires", ns).text,
            "image": info.find("cap:web", ns).text if info.find("cap:web", ns) is not None else None
        }
    return None

def detect_weather_alert(json_response):
    try:
        # Ambil cuaca terdekat (index 0 atau 1)
        weather_list = json_response.get('data', [])[0].get('cuaca', [])[0]
        upcoming = weather_list[0] 
        
        weather_code = int(upcoming.get('weather', 0))
        precip = float(upcoming.get('tp', 0)) # Curah hujan dalam mm

        # Logika: Jika kode hujan lebat (63) atau hujan petir (95+)
        # ATAU curah hujan > 5.0 mm dalam 3 jam
        if weather_code in [63, 95, 97] or precip > 5.0:
            return {
                "status": "SIAGA ⚠️",
                "desc": f"{upcoming.get('weather_desc')} (Presipitasi: {precip}mm)",
                "time": upcoming.get('local_datetime')
            }
        return None
    except:
        return None

async def fetch_weather_data(adm_code):
    url = f"https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={adm_code}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Error fetching BMKG Weather: {e}")
    return None

async def fetch_nowcast_alerts():
    url = "https://www.bmkg.go.id/alerts/nowcast/id"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=15)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"Error RSS: {e}")
    return None

async def fetch_alert_detail(detail_url: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(detail_url, timeout=10)
            if response.status_code == 200:
                return response.text
        except Exception:
            return None

async def fetch_latest_quake():
    """Mengambil data gempa terbaru"""
    url = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()['Infogempa']['gempa']
        except Exception as e:
            logging.error(f"Error fetching Quake Data: {e}")
    return None