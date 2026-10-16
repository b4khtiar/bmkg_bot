import httpx
import logging
import random
import re
import asyncio
import time
from datetime import datetime
from urllib.parse import urlparse
import defusedxml.ElementTree as ET
from utils.constants import WEATHER_CODES, WEATHER_EMOJI, _RAIN_CODES
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

_ALLOWED_HOSTS = {"api.bmkg.go.id", "cdn.bmkg.go.id", "data.bmkg.go.id", "static.bmkg.go.id", "www.bmkg.go.id"}

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


class CircuitBreaker:
    """In-memory circuit breaker — single-process, per-endpoint."""

    def __init__(self, name: str, failure_threshold: int = 3, cooldown: int = 600):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._fail_count = 0
        self._last_failure = 0
        self._open = False

    def can_execute(self) -> bool:
        if not self._open:
            return True
        if time.time() - self._last_failure >= self.cooldown:
            self._open = False  # Half-open
            return True
        return False

    def record_failure(self):
        self._fail_count += 1
        self._last_failure = time.time()
        if self._fail_count >= self.failure_threshold:
            self._open = True
            logger.warning(f"Circuit breaker OPEN for {self.name}")

    def record_success(self):
        self._fail_count = 0
        self._open = False


# Circuit breakers per endpoint type
_quake_circuit = CircuitBreaker("quake")
_nowcast_circuit = CircuitBreaker("nowcast")
_weather_circuits = {}  # adm_code -> CircuitBreaker


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
            logger.warning(f"Gagal fetch {url}: {type(e).__name__}: {e} (percobaan {attempt+1}/{retries+1})")
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

def _format_cache_banner(cached_at: str) -> str:
    """Format a banner for cached weather data."""
    try:
        cached_dt = datetime.fromisoformat(cached_at)
        age_min = int((datetime.now() - cached_dt).total_seconds() / 60)
        return f"⚠️ <i>Data cadangan dari {age_min} menit lalu (BMKG sinyal lemah).</i>\n\n"
    except Exception:
        return "⚠️ <i>Data cadangan (BMKG sinyal lemah).</i>\n\n"


def _extract_cache_metadata(json_response):
    """Pop cache metadata from response dict. Returns (is_cached, cached_at_str)."""
    if not isinstance(json_response, dict):
        return False, None
    is_cached = json_response.pop("_cached", False)
    cached_at = json_response.pop("_cached_at", None)
    return is_cached, cached_at


# Severity ranks for image selection (higher = more dramatic image).
_SEVERITY_RANK = {
    "thunderstorm": 6,
    "heavy_rain": 5,
    "light_rain": 4,
    "foggy": 3,
    "cloudy": 2,
    "clear": 1,
}


def _most_severe_code(entries):
    """Given a list of BMKG weather entries, return the weather code with the
    highest severity, so the photo matches the most notable condition."""
    from utils.constants import IMAGE_WEATHER_GROUPS
    best_code = None
    best_rank = -1
    for entry in entries or []:
        code = entry.get("weather")
        if code is None:
            continue
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            continue
        for group, codes in IMAGE_WEATHER_GROUPS.items():
            if code_int in codes and _SEVERITY_RANK[group] > best_rank:
                best_rank = _SEVERITY_RANK[group]
                best_code = str(code_int)
                break
    return best_code


async def _build_weather_result(text: str, weather_code: str) -> dict:
    """Attach an Unsplash photo to the weather text, if available."""
    from services.unsplash_client import get_weather_photo
    photo_url, photographer = await get_weather_photo(weather_code)
    if photo_url and photographer:
        text = f"{text}\n\n📸 <i>Foto: {photographer} / Unsplash</i>"
    return {
        "text": text,
        "photo_url": photo_url,
        "photographer": photographer,
    }


async def parse_weather_daily_brief(json_response):
    is_cached, cached_at = _extract_cache_metadata(json_response)
    cache_banner = _format_cache_banner(cached_at) if (is_cached and cached_at) else ""

    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return {"text": f"{cache_banner}Gagal memproses briefing cuaca.", "photo_url": None, "photographer": None}

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
        text = f"{cache_banner}{msg}" if cache_banner else msg
        code = _most_severe_code(all_entries)
        return await _build_weather_result(text, code)
    except Exception as e:
        logger.error(f"Gagal memproses briefing cuaca: {e}")
        return {"text": f"{cache_banner}Gagal memproses briefing cuaca.", "photo_url": None, "photographer": None}


async def parse_weather_current(json_response):
    """Tampilkan cuaca untuk jam terdekat dengan waktu sekarang."""
    is_cached, cached_at = _extract_cache_metadata(json_response)
    cache_banner = _format_cache_banner(cached_at) if (is_cached and cached_at) else ""

    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return {"text": f"{cache_banner}Tidak ada data cuaca.", "photo_url": None, "photographer": None}

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
        text = f"{cache_banner}{msg}" if cache_banner else msg
        return await _build_weather_result(text, icon_code)
    except Exception as e:
        logger.error(f"Gagal memproses cuaca saat ini: {e}")
        return {"text": f"{cache_banner}Gagal memproses data cuaca.", "photo_url": None, "photographer": None}

async def parse_weather_hourly_today(json_response):
    """Tampilkan semua jam prakiraan untuk hari ini (per jam)."""
    is_cached, cached_at = _extract_cache_metadata(json_response)
    cache_banner = _format_cache_banner(cached_at) if (is_cached and cached_at) else ""

    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return {"text": f"{cache_banner}Tidak ada data cuaca.", "photo_url": None, "photographer": None}

        # _flatten_today_entries mencakup semua grup hari (hari ini/besok/lusa);
        # filter hanya tanggal hari ini.
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        all_entries = [e for e in all_entries if str(e.get('local_datetime', '')).startswith(today_prefix)]
        if not all_entries:
            return {"text": f"{cache_banner}Tidak ada data cuaca hari ini.", "photo_url": None, "photographer": None}

        lokasi = json_response.get('lokasi', {})
        nama_tempat = f"{lokasi.get('desa')}, {lokasi.get('kecamatan')}"

        output = [f"⏰ <b>CUACA PER JAM HARI INI</b>\n📍 <b>{nama_tempat}</b>\n"]

        current_prefix = datetime.now().strftime("%Y-%m-%d %H")
        for entry in sorted(all_entries, key=lambda x: x.get('local_datetime', '')):
            local_dt = entry.get('local_datetime', '')
            hour = local_dt.split(' ')[1][:5] if ' ' in local_dt else '—'
            weather_code = str(entry.get('weather', ''))
            emoji = WEATHER_EMOJI.get(weather_code, '❓')
            temp = entry.get('t', '?')
            hu = entry.get('hu', '?')
            marker = " 📍" if local_dt.startswith(current_prefix) else ""
            output.append(f"{emoji} <code>{hour}</code>  {entry.get('weather_desc', '')}  {temp}°C  💧{hu}%{marker}")

        output.append("\n<i>📡 Sumber: BMKG</i>")
        text = f"{cache_banner}" + "\n".join(output)
        code = _most_severe_code(all_entries)
        return await _build_weather_result(text, code)
    except Exception as e:
        logger.error(f"Gagal memproses cuaca per jam: {e}")
        return {"text": f"{cache_banner}Gagal memproses data cuaca.", "photo_url": None, "photographer": None}


def parse_nowcast_rss(xml_string, user_city_name=None):
    """
    Scan RSS untuk mencari berita yang relevan dengan kota user.
    """
    root = ET.fromstring(xml_string)
    items = root.findall(".//item")
    relevant_links = []

    for item in items:
        desc_el = item.find("description")
        title_el = item.find("title")
        link_el = item.find("link")
        description = desc_el.text if desc_el is not None else ""
        title = title_el.text if title_el is not None else ""
        link = link_el.text if link_el is not None else ""
        if not link:
            continue
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

async def parse_weather_multi_day(json_response, days=3):
    if not json_response:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    groups = json_response.get('data', [])
    if not groups:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    cuaca_groups = groups[0].get('cuaca', [])
    if not cuaca_groups:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    lokasi = json_response.get('lokasi', {})
    nama_tempat = f"{lokasi.get('desa')}, {lokasi.get('kecamatan')}"

    day_names = ["Hari Ini", "Besok", "Lusa"]
    output = [f"📅 <b>PRAKIRAAN CUACA 3 HARI</b>\n📍 <b>{nama_tempat}</b>\n"]

    all_entries_for_photo = []

    for day_idx in range(min(days, len(cuaca_groups))):
        entries = cuaca_groups[day_idx]
        if not entries:
            continue
        all_entries_for_photo.extend(entries)

        day_label = day_names[day_idx] if day_idx < len(day_names) else f"Hari ke-{day_idx+1}"
        output.append(f"\n━━━ {day_label} ━━━")

        # BMKG omits hu/ws/weather on some entries; `or` keeps a missing field
        # from raising TypeError and killing the whole 3-day message.
        temp_max = max(float(w.get('t') or 0) for w in entries)
        temp_min = min(float(w.get('t') or 0) for w in entries)
        has_rain = any(int(w.get('weather') or -1) in _RAIN_CODES for w in entries)
        avg_hu = sum(float(w.get('hu') or 50) for w in entries) / len(entries)
        max_wind = max(float(w.get('ws') or 0) for w in entries)

        rain_icon = "🌧️" if has_rain else "☀️"
        output.append(f"{rain_icon} <code>{temp_min:.0f}–{temp_max:.0f}°C</code> 💧<code>{avg_hu:.0f}%</code> 💨<code>{max_wind:.0f} km/jam</code>")

        slot_parts = []
        for slot_hour, slot_label in ((8, "08.00"), (17, "17.00")):
            entry = _find_nearest_entry(entries, slot_hour)
            if not entry:
                continue
            weather_code = str(entry.get('weather', ''))
            emoji = WEATHER_EMOJI.get(weather_code, '❓')
            weather_desc = entry.get('weather_desc', '')
            temp = entry.get('t', '?')
            slot_parts.append(f"{emoji} <code>{slot_label}</code> {weather_desc} {temp}°C")
        if slot_parts:
            output.append(" · ".join(slot_parts))

    output.append("\n━━━━━━━━━━━━━━\n<i>📡 Sumber: BMKG</i>")
    text = "\n".join(output)
    code = _most_severe_code(all_entries_for_photo)
    return await _build_weather_result(text, code)

async def fetch_weather_data(adm_code):
    """Fetch weather data. Uses circuit breaker. Returns cached data with metadata on failure."""
    url = "https://api.bmkg.go.id/publik/prakiraan-cuaca"
    params = {"adm4": adm_code}

    if adm_code not in _weather_circuits:
        _weather_circuits[adm_code] = CircuitBreaker(f"weather_{adm_code}")
    circuit = _weather_circuits[adm_code]

    if not circuit.can_execute():
        logger.warning(f"Circuit OPEN for weather {adm_code}, trying cache")
        cached = await _get_cached_weather(adm_code)
        if cached:
            data, cached_at = cached
            data["_cached"] = True
            data["_cached_at"] = cached_at
            return data
        return None

    try:
        data = await fetch_with_retry(url, json=True, params=params, retries=3, delay=2.0)
        if data:
            circuit.record_success()
            await _cache_weather(adm_code, data)
            return data
        else:
            circuit.record_failure()
            cached = await _get_cached_weather(adm_code)
            if cached:
                data, cached_at = cached
                data["_cached"] = True
                data["_cached_at"] = cached_at
                logger.warning(f"Using weather cache for {adm_code}")
                return data
            return None
    except Exception as e:
        circuit.record_failure()
        logger.error(f"Gagal fetch cuaca untuk {adm_code}: {e}")
        cached = await _get_cached_weather(adm_code)
        if cached:
            data, cached_at = cached
            data["_cached"] = True
            data["_cached_at"] = cached_at
            return data
        return None


async def _cache_weather(adm_code, weather_json):
    """Internal: import here to avoid circular dependency."""
    from database import cache_weather
    await cache_weather(adm_code, weather_json)


async def _get_cached_weather(adm_code):
    """Internal: import here to avoid circular dependency."""
    from database import get_cached_weather
    return await get_cached_weather(adm_code)


async def fetch_nowcast_alerts():
    if not _nowcast_circuit.can_execute():
        return None
    url = "https://www.bmkg.go.id/alerts/nowcast/id"
    try:
        data = await fetch_with_retry(url, text=True)
        if data:
            _nowcast_circuit.record_success()
            return data
        else:
            _nowcast_circuit.record_failure()
            return None
    except Exception as e:
        _nowcast_circuit.record_failure()
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
    if not _quake_circuit.can_execute():
        return None
    url = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
    try:
        data = await fetch_with_retry(url, json=True, retries=2)
        if data:
            _quake_circuit.record_success()
            return data.get('Infogempa', {}).get('gempa')
        else:
            _quake_circuit.record_failure()
            return None
    except Exception as e:
        _quake_circuit.record_failure()
        logger.error(f"Gagal fetch data gempa: {e}")
        return None