import httpx
import logging
import re
import asyncio
import time
from datetime import datetime
from urllib.parse import urlparse
import defusedxml.ElementTree as ET
from utils import weather_table as wt
from utils.insight_templates import generate_smart_insight, generate_trend_insight
from utils.design import compose, severity_note, severity_rank
from utils.formatters import (
    location_label, weather_current, weather_daily_brief, weather_hourly,
    weather_multiday,
)
from utils.text import esc, esc_href, clamp, fmt_temp

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
    """Cari entry dengan jam terdekat ke target_hour.

    Hours are compared hour-only, so callers must pass entries from a single day.
    Ties (BMKG's 3-hourly grid makes them rare) resolve to the first entry seen;
    changing that to a deliberate rule would alter /cuaca and /prakiraan output.
    """
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


def _most_severe_code(entries):
    """Kode dengan keparahan tertinggi dari sekumpulan entry.

    Mengembalikan ``str`` karena diteruskan ke pencarian foto yang dikunci
    string; ``None`` bila tidak ada kode yang dipetakan.
    """
    best_code = None
    best_rank = -1
    for entry in entries or []:
        code = entry.get("weather")
        if code is None:
            continue
        rank = wt.photo_severity(code)
        if rank > best_rank:
            best_rank = rank
            best_code = str(code) if wt.condition(code) else None
    return best_code


async def _build_weather_result(head: str, blocks, weather_code: str, banner: str = "") -> dict:
    """Attach an Unsplash photo to the weather text, if available.

    ``blocks`` is a list of ``(priority, text)``. Priority drives the truncation
    order inside :func:`compose`, so the parts a user actually acts on (the
    current condition, the temperature) are the last thing dropped when the
    message is too long to fit a photo caption.
    """
    from services.unsplash_client import get_weather_photo
    photo_url, photographer = await get_weather_photo(weather_code)
    return compose(
        head=head,
        blocks=blocks,
        banner=banner,
        photo=photo_url,
        photographer=photographer,
    )


_BRIEF_SLOTS = [
    ("Pagi", 7),
    ("Siang", 12),
    ("Sore", 15),
    ("Petang", 18),
    ("Malam", 21),
]


async def parse_weather_daily_brief(json_response):
    is_cached, cached_at = _extract_cache_metadata(json_response)
    cache_banner = _format_cache_banner(cached_at) if (is_cached and cached_at) else ""

    try:
        all_entries = _flatten_today_entries(json_response)
        if not all_entries:
            return {"text": f"{cache_banner}Gagal memproses briefing cuaca.", "photo_url": None, "photographer": None}

        slots = []
        for label, hour in _BRIEF_SLOTS:
            entry = _find_nearest_entry(all_entries, hour)
            if entry:
                slots.append((label, entry, wt.emoji(entry.get("weather"))))

        tips = generate_smart_insight(all_entries, max_insights=1)
        # `data` is a list of location groups; `generate_trend_insight` wants
        # the day groups *inside* one location. Passing `data` itself made
        # `tomorrow_entries` empty every time, so "📈 TREN BESOK" was silently
        # absent from every daily brief ever sent.
        data = json_response.get("data", [])
        cuaca_days = data[0].get("cuaca", []) if data else []
        trend = generate_trend_insight(cuaca_days)
        # Both generators return plain content now; the section headers
        # ("💡 INSIGHT", "📈 TREN BESOK") are owned by the formatter.
        insight = tips

        head, blocks = weather_daily_brief(
            slots, location_label(json_response), insight, trend
        )
        code = _most_severe_code(all_entries)
        return await _build_weather_result(head, blocks, code, banner=cache_banner)
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

        icon_code = str(selected.get('weather'))
        # Fall back to BMKG's own wording, but always escaped — it is upstream
        # text, and an unescaped "&" here kills the whole message.
        status_label = wt.label(icon_code, selected.get('weather_desc'))
        accent = wt.emoji(icon_code)

        head, blocks = weather_current(
            selected, location_label(json_response), status_label, accent
        )
        return await _build_weather_result(head, blocks, icon_code, banner=cache_banner)
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

        # Scope to today using BMKG's own timestamps, not datetime.now(). The
        # server clock is WIB-equivalent only if TZ is set correctly, and it
        # isn't guaranteed (a bare `docker run` gets UTC, which breaks the first
        # hours of the WIB day). min() because data[0] starts at today 00:00 WIB
        # but can spill into tomorrow — the earliest date is today's.
        # Load-bearing filter — do not drop it as redundant.
        today_prefix = min(
            str(e.get('local_datetime', ''))[:10] for e in all_entries
        )
        all_entries = [e for e in all_entries if str(e.get('local_datetime', '')).startswith(today_prefix)]
        if not all_entries:
            return {"text": f"{cache_banner}Tidak ada data cuaca hari ini.", "photo_url": None, "photographer": None}

        entries_sorted = sorted(all_entries, key=lambda x: x.get('local_datetime', ''))
        # Mark the nearest slot rather than the exact clock hour: BMKG entries
        # are 3-hourly, so an exact-hour match leaves the table unanchored late
        # in the day (nothing matches after the last entry). Matches how
        # /cuaca and /prakiraan pick their slots.
        nearest = _find_nearest_entry(
            entries_sorted, datetime.now().hour
        )
        current_dt = nearest.get('local_datetime', '') if nearest else ''

        head, blocks = weather_hourly(
            entries_sorted,
            location_label(json_response),
            current_dt,
            wt.emoji,
        )
        code = _most_severe_code(all_entries)
        return await _build_weather_result(head, blocks, code, banner=cache_banner)
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

def _iso_epoch(iso_text: str) -> int:
    """``"2026-10-27T15:00:00+07:00"`` → epoch detik; gagal → ``0``.

    Dipakai untuk urutan terbaru-dulu antar-peringatan CAP. Pengecualian
    diserap di sini supaya satu field pelik tidak menggugurkan seluruh CAP.
    Timestamp CAP selalu membawa zona, jadi ``timestamp()`` akurat; fallback 0
    hanya menggeser urutan, bukan logika kirim.
    """
    try:
        return int(datetime.fromisoformat(iso_text.strip()).timestamp())
    except (ValueError, TypeError, AttributeError):
        return 0


_RE_REGION = re.compile(r"sebagian wilayah (.*?), khususnya di (.*?)\. Kondisi")
_RE_IMPACT = re.compile(r"berpotensi menimbulkan dampak berupa (.*?)\. Masyarakat")
_RE_ADVICE = re.compile(r"dihimbau untuk (.*?)\. Kondisi diperkirakan")
_RE_SPLIT = re.compile(r',| dan | serta ')

def parse_cap_description(text):
    """Ambil wilayah, dampak, dan himbauan dari teks CAP.

    Waktu mulai/berakhir dulu ikut di-scrape dari kalimat ("akan terjadi
    pada...", "berlangsung hingga...") padahal CAP XML sudah menyediakannya
    di tag ``effective``/``expires`` — dan tidak ada pihak yang membaca
    kedua kunci tersebut, jadi scraping dan regex-nya dihapus saja.
    """
    logging.info(f"Parsing CAP description: {text}")
    text = re.sub(r'\s+', ' ', text).strip()

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

    return {
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
        # Mapping lives in utils/design.py so the same decision is available to
        # every renderer; it used to be invented inline here and nowhere else.
        severity_note_text = severity_note(severity)

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
        sent_el = root.find("cap:sent", ns)
        event_el = info.find("cap:event", ns)
        web_el = info.find("cap:web", ns)

        # <sent> (waktu penerbitan) + peringkat severity: jumlah urutan
        # terbaru-dulu antar item dan putusan eskalasi di nowcast_alert_job.
        sent_text = sent_el.text if sent_el is not None else ""

        return {
            "id": identifier_el.text if identifier_el is not None else "",
            "sent": _iso_epoch(sent_text),
            "severity_rank": severity_rank(severity),
            "event": event_el.text if event_el is not None else "Peringatan Cuaca",
            "severity": severity_note_text,
            "severity_raw": severity,
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

def summarize_nowcast_rss(nowcast_data, province_filter=None, max_items=8):
    """Ringkasan RSS nowcast untuk /nowcast.

    Dibatasi ``max_items`` karena tanpa filter provinsi, RSS ini memuat seluruh
    nasional. Tanpa batas, pesannya lewat dari limit 4096 karakter Telegram,
    command gagal diam-diam, dan pengguna tidak melihat apa pun.
    """
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
            return (
                f"Tidak ada peringatan cuaca untuk wilayah {esc(province_filter)} saat ini."
            )
        return "Tidak ada peringatan cuaca saat ini."

    head = "🌧️ <b>Peringatan Dini Cuaca</b>"
    if not province_filter:
        # No location means no province filter, so this is the whole country.
        # Point them at the fix rather than dumping it.
        return (
            f"{head}\n"
            "Tidak ada peringatan aktif untuk provinsi tertentu.\n\n"
            "Atur lokasi Anda dulu agar peringatan hanya menampilkan wilayah Anda."
        )

    shown = filtered[:max_items]
    rows = []
    for title, link in shown:
        rows.append(f"🗺️ {esc(title)}")
        if link:
            rows.append(f"   <a href='{esc_href(link)}'>Lihat detail</a>")

    hidden = len(filtered) - len(shown)
    if hidden > 0:
        rows.append(f"\n<i>+{hidden} peringatan lain di wilayah ini.</i>")
    else:
        rows.append(f"\n<i>Menampilkan {len(filtered)} peringatan.</i>")

    # Backstop: titles are upstream text of unbounded length. Telegram rejects
    # messages past 4096 chars outright, with no partial delivery.
    return clamp("\n".join(rows), 4096)

async def parse_weather_multi_day(json_response, days=3):
    if not json_response:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    # Pop cache metadata here too. This parser used to skip it, so /prakiraan
    # served stale data with no warning while /cuaca and the morning brief both
    # showed the "Data cadangan" banner — users had no way to tell.
    is_cached, cached_at = _extract_cache_metadata(json_response)
    cache_banner = _format_cache_banner(cached_at) if (is_cached and cached_at) else ""

    groups = json_response.get('data', [])
    if not groups:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    cuaca_groups = groups[0].get('cuaca', [])
    if not cuaca_groups:
        return {"text": "Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    day_names = ["Hari Ini", "Besok", "Lusa"]
    day_blocks = []
    all_entries_for_photo = []

    for day_idx in range(min(days, len(cuaca_groups))):
        entries = cuaca_groups[day_idx]
        if not entries:
            continue
        all_entries_for_photo.extend(entries)

        day_label = day_names[day_idx] if day_idx < len(day_names) else f"Hari ke-{day_idx+1}"

        # BMKG omits hu/ws/weather on some entries; `or` keeps a missing field
        # from raising TypeError and killing the whole 3-day message.
        temp_max = max(float(w.get('t') or 0) for w in entries)
        temp_min = min(float(w.get('t') or 0) for w in entries)
        # Ikon harian memakai is_wet_or_stormy, bukan is_wet: kode 17-24
        # adalah petir tanpa hujan, jadi wet-nya False — tapi "☀️" untuk hari
        # badai petir menyesatkan.
        has_rain = any(wt.is_wet_or_stormy(w.get("weather")) for w in entries)
        avg_hu = sum(float(w.get('hu') or 50) for w in entries) / len(entries)
        max_wind = max(float(w.get('ws') or 0) for w in entries)

        slot_parts = []
        for slot_hour, slot_label in ((8, "08.00"), (17, "17.00")):
            entry = _find_nearest_entry(entries, slot_hour)
            if not entry:
                continue
            emoji = wt.emoji(entry.get('weather'))
            slot_parts.append(
                f"{emoji} <code>{slot_label}</code> {esc(entry.get('weather_desc'))}"
                f" {fmt_temp(entry.get('t'))}"
            )

        day_blocks.append(
            (day_label, temp_min, temp_max, avg_hu, max_wind, has_rain,
             " · ".join(slot_parts))
        )

    if not day_blocks:
        return {"text": f"{cache_banner}Tidak ada data prakiraan cuaca.", "photo_url": None, "photographer": None}

    head, blocks = weather_multiday(day_blocks)
    code = _most_severe_code(all_entries_for_photo)
    return await _build_weather_result(
        head=f"{head}\n📍 {location_label(json_response)}",
        blocks=blocks,
        weather_code=code,
        banner=cache_banner,
    )

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