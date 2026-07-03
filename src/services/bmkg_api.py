import httpx
import logging
import random
import re
import asyncio
from datetime import datetime
from urllib.parse import urlparse
import defusedxml.ElementTree as ET
from utils.constants import WEATHER_CODES, WEATHER_EMOJI
from utils.insight_templates import generate_smart_insight, generate_trend_insight

logger = logging.getLogger(__name__)

_http_client = None

async def get_http_client():
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _http_client

async def close_http_client():
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None

_ALLOWED_HOSTS = {"api.bmkg.go.id", "data.bmkg.go.id", "static.bmkg.go.id", "www.bmkg.go.id"}

def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        result = parsed.scheme in ("https",) and hostname in _ALLOWED_HOSTS
        if not result:
            logger.warning(f"URL ditolak: scheme={parsed.scheme} hostname={hostname} path={parsed.path}")
        return result
    except Exception as e:
        logger.warning(f"Gagal parse URL {url}: {e}")
        return False

async def fetch_with_retry(url, retries=2, delay=1.5, text=False, json=False, params=None):
    if not validate_url(url):
        logger.warning(f"URL ditolak (bukan domain BMKG): {url}")
        return None
    client = await get_http_client()
    for attempt in range(retries + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.text if text else response.json() if json else response
            logger.warning(f"HTTP {response.status_code} untuk {url} (percobaan {attempt+1}/{retries+1})")
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            logger.warning(f"Gagal fetch {url}: {e} (percobaan {attempt+1}/{retries+1})")
            if attempt < retries:
                await asyncio.sleep(delay * (attempt + 1))
    return None

def _flatten_today_entries(json_response):
    """Flatten semua entries dari grup cuaca[0] (hari ini)."""
    cuaca_data = json_response.get('data', [])
    if not cuaca_data:
        return []
    today_groups = cuaca_data[0].get('cuaca', [])
    all_entries = []
    for group in today_groups:
        all_entries.extend(group)
    return all_entries

def _find_nearest_entry(entries, target_hour):
    """Cari entry dengan jam terdekat ke target_hour."""
    best = None
    best_diff = 999
    for entry in entries:
        try:
            dt = datetime.strptime(entry['local_datetime'], "%Y-%m-%d %H:%M:%S")
            diff = abs(dt.hour - target_hour)
            if diff < best_diff:
                best_diff = diff
                best = entry
        except (KeyError, ValueError):
            continue
    return best

def parse_weather_daily_brief(json_response):
    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return "Gagal memproses briefing cuaca."

        lokasi = json_response.get('lokasi', {})

        time_slots = [
            ("Pagi", 7),
            ("Siang", 12),
            ("Sore", 15),
            ("Petang", 18),
            ("Malam", 21),
        ]

        summary_points = []
        for label, hour in time_slots:
            entry = _find_nearest_entry(all_entries, hour)
            if entry:
                weather_desc = entry.get('weather_desc', '')
                icon = WEATHER_EMOJI.get(str(entry['weather']), '❓')
                temp = f"{entry['t']}°C"
                summary_points.append(f"🕒 <b>{label}</b>\n{icon} {weather_desc} | {temp}")

        grid_view = "\n\n".join(summary_points)
        tips = generate_smart_insight(all_entries, max_insights=1)

        cuaca_data = json_response.get('data', [])
        trend = generate_trend_insight(cuaca_data) if cuaca_data else None
        trend_section = f"\n\n{trend}" if trend else ""

        msg = (
            f"📅 <b>PRAKIRAAN CUACA HARI INI</b>\n"
            f"📍 <b>{lokasi.get('desa')}</b>\n\n"
            f"{grid_view}\n\n"
            f"💡 <b>INSIGHT</b>\n{tips}"
            f"{trend_section}"
        )
        return msg
    except Exception as e:
        logger.error(f"Gagal memproses briefing cuaca: {e}")
        return "Gagal memproses briefing cuaca."

def parse_weather_current(json_response):
    """Tampilkan cuaca untuk jam terdekat dengan waktu sekarang."""
    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return "Tidak ada data cuaca."

        now = datetime.now()
        selected = min(all_entries, key=lambda x: abs(
            datetime.strptime(x['local_datetime'], "%Y-%m-%d %H:%M:%S") - now
        ))

        lokasi = json_response.get('lokasi', {})
        nama_tempat = f"{lokasi.get('desa')}, {lokasi.get('kecamatan')}"

        temp = selected.get('t')
        hu = selected.get('hu')
        ws = selected.get('ws')
        wd = selected.get('wd')
        desc = selected.get('weather_desc')
        icon_code = str(selected.get('weather'))
        status_emoji = WEATHER_CODES.get(icon_code, desc)
        local_dt = selected.get('local_datetime', '')

        msg = (
            f"<b>🌤️ CUACA SAAT INI</b>\n"
            f"📍 {nama_tempat}\n"
            f"📅 {local_dt}\n\n"
            f"<b>{status_emoji}</b>\n"
            f"🌡️ <code>{temp}°C</code>  💧 <code>{hu}%</code>\n"
            f"💨 <code>{ws} km/jam</code> ({wd})\n\n"
            f"<i>📡 Sumber: BMKG</i>"
        )
        return msg
    except Exception as e:
        logger.error(f"Gagal memproses cuaca saat ini: {e}")
        return "Gagal memproses data cuaca."

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

_RE_START_TIME = re.compile(r"akan terjadi pada (.*?) di sebagian")
_RE_REGION = re.compile(r"sebagian wilayah (.*?), khususnya di (.*?)\. Kondisi")
_RE_IMPACT = re.compile(r"berpotensi menimbulkan dampak berupa (.*?)\. Masyarakat")
_RE_ADVICE = re.compile(r"dihimbau untuk (.*?)\. Kondisi diperkirakan")
_RE_END_TIME = re.compile(r"berlangsung hingga (.*?)\.?$")
_RE_SPLIT = re.compile(r',| dan | serta ')

def parse_cap_description(text):
    logging.info(f"Parsing CAP description: {text}")
    text = re.sub(r'\s+', ' ', text).strip()

    start_time_match = _RE_START_TIME.search(text)
    start_time = start_time_match.group(1).strip() if start_time_match else "Tidak diketahui"

    region_match = _RE_REGION.search(text)
    province = ""
    sub_districts_raw = ""
    if region_match:
        province = region_match.group(1).strip()
        sub_districts_raw = region_match.group(2).strip()

    impact_match = _RE_IMPACT.search(text)
    impacts = []
    if impact_match:
        impacts = [i.strip() for i in _RE_SPLIT.split(impact_match.group(1)) if i.strip()]

    advice_match = _RE_ADVICE.search(text)
    advice = []
    if advice_match:
        advice = [a.strip() for a in _RE_SPLIT.split(advice_match.group(1)) if a.strip()]

    end_time_match = _RE_END_TIME.search(text)
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
    ns = {'cap': 'urn:oasis:names:tc:emergency:cap:1.2'}
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as e:
        logger.error(f"Gagal parse XML CAP: {e}")
        return None

    info = root.find("cap:info", ns)
    if info is None:
        logger.warning("CAP XML tidak memiliki elemen info")
        return None

    try:
        severity_el = info.find("cap:severity", ns)
        severity = severity_el.text if severity_el is not None else "Unknown"
        severity_note = (
            "🔴 Bahaya" if severity in ("Extreme", "Severe") else
            "🟠 Waspada" if severity == "Moderate" else
            "🟡 Siaga" if severity == "Minor" else
            "ℹ️ Info"
        )

        effective_el = info.find("cap:effective", ns)
        expires_el = info.find("cap:expires", ns)
        effective_text = effective_el.text if effective_el is not None else ""
        expires_text = expires_el.text if expires_el is not None else ""
        time_effective = effective_text.split("T")[1].split("+")[0] if effective_text else ""
        time_expires = expires_text.split("T")[1].split("+")[0] if expires_text else ""

        description_el = info.find("cap:description", ns)
        description_text = description_el.text if description_el is not None else ""
        desc = parse_cap_description(description_text)

        identifier_el = root.find("cap:identifier", ns)
        event_el = info.find("cap:event", ns)
        web_el = info.find("cap:web", ns)

        return {
            "id": identifier_el.text if identifier_el is not None else "",
            "event": event_el.text if event_el is not None else "Peringatan Cuaca",
            "severity": severity_note,
            "effective": time_effective,
            "expires": time_expires,
            "province": desc.get("province", ""),
            "sub_districts": desc.get("sub_districts", ""),
            "impacts": desc.get("impacts", []),
            "advice": desc.get("advice", []),
            "image": web_el.text if web_el is not None else None,
        }
    except AttributeError as e:
        logger.error(f"Field CAP XML tidak ditemukan: {e}")
    except Exception as e:
        logger.error(f"Error tidak terduga di parse_cap_detail: {e}")
    return None

def summarize_nowcast_rss(nowcast_data, province_filter=None):
    try:
        root = ET.fromstring(nowcast_data)
    except ET.ParseError as e:
        logger.error(f"Gagal parse RSS nowcast: {e}")
        return "Gagal memproses data peringatan cuaca."

    items = root.findall(".//item")
    if not items:
        return "Tidak ada peringatan cuaca saat ini."

    filtered = []
    for item in items:
        title = item.find("title")
        desc = item.find("description")
        link = item.find("link")
        if title is None or link is None:
            continue
        title_text = title.text or ""
        desc_text = desc.text if desc is not None else ""
        if province_filter and province_filter.lower() not in title_text.lower() and province_filter.lower() not in desc_text.lower():
            continue
        filtered.append((title_text, link.text or ""))

    if not filtered:
        if province_filter:
            return f"Tidak ada peringatan cuaca untuk wilayah {province_filter} saat ini."
        return "Tidak ada peringatan cuaca saat ini."

    lines = []
    for title, link in filtered:
        lines.append(f"📍 {title}")
        lines.append(f"🔗 <a href='{link}'>Lihat Detail</a>")

    count_info = f"\n\n📊 <i>Menampilkan {len(filtered)} peringatan</i>" if len(filtered) > 1 else ""
    return (
        f"🌧️ <b>Peringatan Dini Cuaca</b>\n"
        f"{chr(10).join(lines)}"
        f"{count_info}"
    )

def parse_weather_multi_day(json_response, days=3):
    if not json_response:
        return "Tidak ada data prakiraan cuaca."

    groups = json_response.get('data', [])
    if not groups:
        return "Tidak ada data prakiraan cuaca."

    cuaca_groups = groups[0].get('cuaca', [])
    if not cuaca_groups:
        return "Tidak ada data prakiraan cuaca."

    lokasi = json_response.get('lokasi', {})
    nama_tempat = f"{lokasi.get('desa')}, {lokasi.get('kecamatan')}"

    day_names = ["Hari Ini", "Besok", "Lusa"]
    output = [f"📅 <b>PRAKIRAAN CUACA 3 HARI</b>\n📍 <b>{nama_tempat}</b>\n"]

    today_str = datetime.now().strftime("%Y-%m-%d")

    for day_idx in range(min(days, len(cuaca_groups))):
        entries = cuaca_groups[day_idx]
        if not entries:
            continue

        day_label = day_names[day_idx] if day_idx < len(day_names) else f"Hari ke-{day_idx+1}"
        output.append(f"\n━━━ {day_label} ━━━")

        temp_max = max(float(w.get('t', 0)) for w in entries if w.get('t') is not None)
        temp_min = min(float(w.get('t', 0)) for w in entries if w.get('t') is not None)
        has_rain = any(60 <= int(w.get('weather', 0)) <= 82 for w in entries)
        avg_hu = sum(float(w.get('hu', 50)) for w in entries) / len(entries)
        max_wind = max(float(w.get('ws', 0)) for w in entries)

        rain_icon = "🌧️" if has_rain else "☀️"
        output.append(f"🌡️ <code>{temp_min:.0f}°C</code> – <code>{temp_max:.0f}°C</code> {rain_icon}")
        output.append(f"💧 <code>{avg_hu:.0f}%</code> | 💨 <code>{max_wind:.0f} km/jam</code>")

        time_lines = []
        for w in entries:
            local_dt = w.get('local_datetime', '')
            hour = local_dt.split(' ')[1][:5] if ' ' in local_dt else '—'
            weather_code = str(w.get('weather', ''))
            emoji = WEATHER_EMOJI.get(weather_code, '❓')
            temp = w.get('t', '?')
            hu = w.get('hu', '?')
            time_lines.append(f"• {emoji} <code>{hour}</code>  {temp}°C  💧{hu}%")

        if time_lines:
            output.extend(time_lines)

    output.append("\n━━━━━━━━━━━━━━\n<i>📡 Sumber: BMKG</i>")
    return "\n".join(output)

async def fetch_weather_data(adm_code):
    url = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
    params = {"adm4": adm_code}
    try:
        data = await fetch_with_retry(url, json=True, params=params)
        return data
    except Exception as e:
        logger.error(f"Gagal fetch cuaca untuk {adm_code}: {e}")
    return None

async def fetch_nowcast_alerts():
    url = "https://www.bmkg.go.id/alerts/nowcast/id"
    try:
        data = await fetch_with_retry(url, text=True)
        return data
    except Exception as e:
        logger.error(f"Gagal fetch nowcast RSS: {e}")
    return None

async def fetch_alert_detail(detail_url: str):
    try:
        data = await fetch_with_retry(detail_url, text=True, retries=1)
        return data
    except Exception as e:
        logger.warning(f"Gagal fetch detail alert: {e}")
    return None

async def fetch_latest_quake():
    url = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
    try:
        data = await fetch_with_retry(url, json=True, retries=2)
        if data:
            return data.get('Infogempa', {}).get('gempa')
    except Exception as e:
        logger.error(f"Gagal fetch data gempa: {e}")
    return None