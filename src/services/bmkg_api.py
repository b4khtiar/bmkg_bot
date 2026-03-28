import httpx
import logging
import random
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
                weather_desc = w.get('weather_desc', '')
                icon = WEATHER_EMOJI.get(str(w['weather']), '❓')
                temp = f"{w['t']}°C"
                summary_points.append(f"🕒 <b>{label}</b>\n{icon} {weather_desc} | {temp}")

        # Gabungkan
        grid_view = "\n\n".join(summary_points)
        
        tips = generate_smart_insight(weather_list)
        msg = (
            f"📅 <b>PRAKIRAAN CUACA HARI INI</b>\n"
            f"📍 <b>{lokasi.get('desa')}</b>\n\n"
            f"{grid_view}\n\n"
            f"💡 <b>INSIGHT</b>\n{tips}"
        )
        return msg
    except:
        return "Gagal memproses briefing cuaca."

def get_smart_insight(weather_list):
    # Filter hanya untuk 4 waktu utama (07:00, 13:00, 16:00, 19:00)
    data = weather_list[:4]
    max_temp = max(int(w['t']) for w in data)
    codes = [int(w['weather']) for w in data]
    
    # Prefix agar lebih manusiawi
    prefixes = ["Saran hari ini:", "Insight untuk Anda:", "Info penting:", "Catatan rutin:"]
    pref = random.choice(prefixes)

    # Logika Prioritas (Urutkan dari yang paling berbahaya/penting)
    if any(c in [95, 97] for c in codes):
        return f"⚡ <b>{pref}</b> Ada potensi hujan petir. Pastikan perangkat elektronik terlindungi dan hindari berteduh di bawah pohon."

    if any(c in [61, 63] for c in codes):
        # Cek jika hujan di siang atau sore (waktu produktif)
        if codes[1] >= 60 or codes[2] >= 60:
            return f"🌧️ <b>{pref}</b> Siapkan jas hujan di kendaraan. Hujan diprediksi turun saat jam sibuk siang/sore nanti."
        return f"🌦️ <b>{pref}</b> Sedia payung sebelum hujan. Cuaca hari ini diprediksi tidak menentu."

    if max_temp >= 34:
        return f"☀️ <b>{pref}</b> Suhu sangat terik (maks {max_temp}°C). Gunakan tabir surya jika beraktivitas luar ruangan dan cukupi hidrasi."

    if all(c <= 3 for c in codes): # Dominasi Cerah/Berawan
        return f"🧺 <b>{pref}</b> Hari yang cerah! Sangat ideal untuk menjemur pakaian atau agenda luar ruangan seharian."

    return f"☁️ <b>{pref}</b> Cuaca cenderung stabil dan berawan. Tetap nyaman beraktivitas!"

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
               f"📉 Kondisi: <b>{status_emoji}</b>\n"
               f"🌡️ Suhu: <code>{temp}°C</code>\n"
               f"💧 Kelembapan: <code>{hu}%</code>\n"
               f"💨 Angin: <code>{ws} km/jam</code> (Arah <code>{wd}</code>)\n\n"
               f"<i> 📡 Sumber: BMKG</i>")
        return msg
    except (IndexError, KeyError, TypeError) as e:
        return f"⚠️ Gagal memproses data cuaca wilayah ini. ({e})"

def parse_nowcast_rss(xml_string, user_city_name):
    """
    Scan RSS untuk mencari berita yang relevan dengan kota user.
    """
    root = ET.fromstring(xml_string)
    items = root.findall(".//item")
    relevant_links = []

    for item in items:
        description = item.find("description").text
        title = item.find("title").text
        link = item.find("link").text
        
        # Filter awal: Jika nama Kota/Kabupaten user ada di judul
        if user_city_name.lower() in title.lower() or user_city_name.lower() in description.lower():
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
        expires_text = info.find("cap:expires", ns).text
        # Convert ISO format to readable
        readable_expires = expires_text.split("T")[0] + " " + expires_text.split("T")[1].split("+")[0]
        return {
            "id": root.find("cap:identifier", ns).text,
            "severity": info.find("cap:severity", ns).text,
            "headline": info.find("cap:headline", ns).text,
            "description": info.find("cap:description", ns).text,
            "expires": readable_expires,
            "image": info.find("cap:web", ns).text if info.find("cap:web", ns) is not None else None
        }
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