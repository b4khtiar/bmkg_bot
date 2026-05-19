import httpx
import logging
import random
import re
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
        # print(grid_view)
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

def generate_smart_insight(weather_list):
    if not weather_list:
        return "Tidak ada data cuaca tersedia."

    temps = []
    codes = []
    tps = []
    rainy_busy_hours = []

    for w in weather_list:
        try:
            temp = float(w.get('t', 0))
            code = int(w.get('weather', 0))
            tp = float(w.get('tp', 0))
            temps.append(temp)
            codes.append(code)
            tps.append(tp)
            
            # Extract hour from "2026-04-10 15:00:00" to check for "busy hours with rain"
            local_datetime = w.get('local_datetime', '')
            if local_datetime:
                hour = int(local_datetime.split(' ')[1].split(':')[0])
                # We consider 12:00 to 19:00 as busy/afternoon hours with rain (codes 60-67)
                if 12 <= hour <= 19 and 60 <= code <= 67:
                    rainy_busy_hours.append(hour)
        except (IndexError, ValueError, TypeError):
            pass

    if not temps:
        return "Tidak ada data cuaca tersedia."

    max_temp = max(temps)
    
    # Prefix agar lebih manusiawi
    prefixes = ["Saran hari ini:", "Insight untuk Anda:", "Info penting:", "Catatan:"]
    pref = random.choice(prefixes)

    # 1. PRIORITY: Thunderstorms (WMO codes 95, 96, 97)
    if any(c in [95, 96, 97] for c in codes):
        return f"⚡ <b>{pref}</b> Ada potensi hujan petir. Pastikan perangkat elektronik terlindungi dan hindari berteduh di bawah pohon."

    # 2. PRIORITY: Rain (Codes in the 60s range)
    if any(60 <= c <= 67 for c in codes):
        # Check if rain is predicted during the afternoon/evening (busy hours)
        is_busy_hour_rain = len(rainy_busy_hours) > 0
        
        if is_busy_hour_rain:
            return f"🌧️ <b>{pref}</b> Siapkan jas hujan! Hujan diprediksi turun pada sore hari saat jam pulang kerja/aktivitas padat."
        return f"🌦️ <b>{pref}</b> Sedia payung sebelum hujan. Cuaca hari ini diprediksi akan turun hujan."

    # 3. PRIORITY: Extreme Heat
    if max_temp >= 34:
        return f"☀️ <b>{pref}</b> Suhu sangat terik (maks {max_temp}°C). Gunakan tabir surya dan pastikan cukup minum air putih."

    # 4. PRIORITY: Sunny / Good for Laundry
    # Logic: Weather code is clear (0-3) AND precipitation (tp) is 0
    if all(c <= 3 for c in codes) and all(tp <= 0.01 for tp in tps):
        return f"🧺 <b>{pref}</b> Hari yang cerah! Sangat ideal untuk menjemur pakaian atau agenda luar ruangan."

    # 5. DEFAULT: Cloudy/Stable
    return f"☁️ <b>{pref}</b> Cuaca cenderung stabil dan berawan. Tetap nyaman untuk beraktivitas!"

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

def parse_nowcast_rss(xml_string, user_city_name=None):
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
        # Jika user_city_name = None, ambil semua link
        if user_city_name is None:
            relevant_links.append(link)
            continue
        # Filter awal: Jika nama Kota/Kabupaten user ada di judul
        if user_city_name.lower() in title.lower() or user_city_name.lower() in description.lower():
            relevant_links.append(link)
            
    return relevant_links

def parse_cap_description(text):
    logging.info(f"Parsing CAP description: {text}")
    
    # Bersihkan whitespace aneh (seperti \xa0 atau double space) agar text seragam
    text = re.sub(r'\s+', ' ', text).strip()

    # 1. Extract Start Time
    # Pola: cari di antara "akan terjadi pada " dan " di sebagian"
    start_time_match = re.search(r"akan terjadi pada (.*?) di sebagian", text)
    start_time = start_time_match.group(1).strip() if start_time_match else "Tidak diketahui"

    # 2. Extract Region and Sub-districts
    # Pola: tangkap setelah "sebagian wilayah " sampai ", khususnya di ", lalu tangkap kecamatannya sampai tanda titik pertama
    region_pattern = r"sebagian wilayah (.*?), khususnya di (.*?)\. Kondisi"
    region_match = re.search(region_pattern, text)
    
    province = ""
    sub_districts_raw = ""
    if region_match:
        province = region_match.group(1).strip()
        sub_districts_raw = region_match.group(2).strip()

    # 3. Extract Potential Impacts
    # Pola: ambil teks di antara "dampak berupa " dan ". Masyarakat"
    impact_pattern = r"berpotensi menimbulkan dampak berupa (.*?)\. Masyarakat"
    impact_match = re.search(impact_pattern, text)
    
    impacts = []
    if impact_match:
        raw_impact = impact_match.group(1)
        # Pisahkan menggunakan regex agar "A, B, dan C" atau "A dan B" terpisah dengan rapi
        impacts = [i.strip() for i in re.split(r',| dan ', raw_impact) if i.strip()]

    # 4. Extract Advice
    # Pola: ambil teks di antara "dihimbau untuk " dan ". Kondisi diperkirakan"
    advice_pattern = r"dihimbau untuk (.*?)\. Kondisi diperkirakan"
    advice_match = re.search(advice_pattern, text)
    
    advice = []
    if advice_match:
        raw_advice = advice_match.group(1)
        # Pisahkan berdasarkan koma atau kata "serta"
        advice = [a.strip() for a in re.split(r',| serta ', raw_advice) if a.strip()]

    # 5. Extract End Time
    # Pola: cari teks setelah "berlangsung hingga " sampai titik terakhir
    end_time_match = re.search(r"berlangsung hingga (.*?)\.?$", text)
    end_time = end_time_match.group(1).strip() if end_time_match else "Tidak diketahui"

    return {
        "start_time": start_time,
        "end_time": end_time,
        "province": province,
        "sub_districts": sub_districts_raw,
        "impacts": impacts,
        "advice": advice,
    }

def parse_cap_detail(xml_string):
    """
    Parse format CAP (Common Alerting Protocol) dari link detail.
    """
    # Note: CAP XML menggunakan namespace
    ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
    root = ET.fromstring(xml_string)
    info = root.find("cap:info", ns)
    
    if info is not None:
        # severity can be: Extreme, Severe, Moderate, Minor, Unknown
        severity = info.find("cap:severity", ns).text
        severity_note = "🔴 Bahaya" if severity == "Extreme" else "🔴 Bahaya" if severity == "Severe" else "🟠 Waspada" if severity == "Moderate" else "🟡 Siaga" if severity == "Minor" else "ℹ️ Info"
        effective_text = info.find("cap:effective", ns).text
        expires_text = info.find("cap:expires", ns).text
        # Convert ISO format to readable hour only
        time_effective = effective_text.split("T")[1].split("+")[0]
        time_expires = expires_text.split("T")[1].split("+")[0]
        description_text = info.find("cap:description", ns).text
        # simplify the description
        desc = parse_cap_description(description_text)
        
        return {
            "id": root.find("cap:identifier", ns).text,
            "event": info.find("cap:event", ns).text,
            "severity": severity_note,
            "effective": time_effective,
            "expires": time_expires,
            "province": desc["province"],
            "sub_districts": desc["sub_districts"],
            "impacts": desc["impacts"],
            "advice": desc["advice"],
            "image": info.find("cap:web", ns).text if info.find("cap:web", ns) is not None else None
        }
    return None

def summarize_nowcast_rss(nowcast_data):
    """
    Summarize nowcast data from RSS feed.
    """
    # ambil data Title dan Link saja, dari masing-masing item array nowcast_data
    root = ET.fromstring(nowcast_data)
    items = root.findall(".//item")
    summary = ""
    for item in items:
        title = item.find("title").text
        link = item.find("link").text
        summary += f"📍 {title}\n"
        summary += f"🔗 <a href='{link}'>Lihat Detail</a>\n\n"
    
    return f"""
    🌧️ <b>Peringatan Dini Cuaca</b>
    {summary}
    """

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