import os
import logging
from datetime import datetime, timedelta

from utils.constants import WEATHER_QUERY_MAP, IMAGE_WEATHER_GROUPS

logger = logging.getLogger(__name__)

UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
IMAGE_CACHE_TTL_HOURS = 6

# In-memory cache: {condition_group: (url, photographer, fetched_at)}
_image_cache = {}
_warned_missing_key = False


def _resolve_condition_group(weather_code: str) -> str | None:
    """Map a raw BMKG weather code to a named condition group."""
    if not weather_code:
        return None
    code_str = str(weather_code)
    for group, codes in IMAGE_WEATHER_GROUPS.items():
        try:
            if int(code_str) in codes:
                return group
        except (ValueError, TypeError):
            continue
    return None


def _query_for_code(weather_code: str) -> str | None:
    """Return the Unsplash search query for a given weather code."""
    if not weather_code:
        return None
    return WEATHER_QUERY_MAP.get(str(weather_code))


def _warn_missing_key_once():
    global _warned_missing_key
    if not _warned_missing_key:
        logger.warning("UNSPLASH_ACCESS_KEY not set — weather images disabled.")
        _warned_missing_key = True


async def _fetch_image(query: str) -> tuple[str | None, str | None]:
    """Hit Unsplash API. Returns (image_url, photographer_name) or (None, None)."""
    if not query:
        return None, None

    try:
        from services.bmkg_api import get_http_client
        client = await get_http_client()
        resp = await client.get(
            UNSPLASH_SEARCH_URL,
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            params={
                "query": query,
                "per_page": 1,
                "orientation": "landscape",
                "content_filter": "high",
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.warning(f"Unsplash API HTTP {resp.status_code} for query '{query}'")
            return None, None

        payload = resp.json()
        results = payload.get("results", [])
        if not results:
            logger.info(f"Unsplash returned no results for '{query}'")
            return None, None

        photo = results[0]
        image_url = photo.get("urls", {}).get("regular")
        photographer = (photo.get("user") or {}).get("name", "")
        if not image_url:
            return None, None
        return image_url, photographer
    except Exception as e:
        logger.warning(f"Unsplash fetch failed for '{query}': {e}")
        return None, None


async def get_weather_photo(weather_code: str) -> tuple[str | None, str | None]:
    """Public entry point. Returns (image_url, photographer) or (None, None).

    Caches by condition group (e.g. 'rain', 'clear') to minimize API calls.
    """
    if not weather_code:
        return None, None

    # Without a key, skip all DB/API work.
    if not UNSPLASH_ACCESS_KEY:
        _warn_missing_key_once()
        return None, None

    group = _resolve_condition_group(weather_code)
    if not group:
        return None, None

    # Check memory cache first
    now = datetime.now()
    cached = _image_cache.get(group)
    if cached:
        url, photographer, fetched_at = cached
        if now - fetched_at < timedelta(hours=IMAGE_CACHE_TTL_HOURS):
            return url, photographer

    # Memory miss → try DB
    db_url, db_photographer = await _get_db_cache(group, now)
    if db_url:
        _image_cache[group] = (db_url, db_photographer, now)
        return db_url, db_photographer

    # Fetch from Unsplash
    query = _query_for_code(weather_code)
    if not query:
        return None, None

    url, photographer = await _fetch_image(query)
    if url:
        _image_cache[group] = (url, photographer, now)
        await _store_db_cache(group, url, photographer, now)
        return url, photographer

    return None, None


async def _get_db_cache(group: str, now: datetime):
    """Return cached (url, photographer) from DB if within TTL, else (None, None)."""
    try:
        from database import get_cached_weather_image
        row = await get_cached_weather_image(group)
        if row:
            cached_at = datetime.fromisoformat(row["cached_at"])
            if now - cached_at < timedelta(hours=IMAGE_CACHE_TTL_HOURS):
                return row["image_url"], row["photographer"]
    except Exception as e:
        logger.warning(f"DB cache read failed for image group '{group}': {e}")
    return None, None


async def _store_db_cache(group: str, url: str, photographer: str, cached_at: datetime):
    """Persist cache to SQLite for durability across restarts."""
    try:
        from database import cache_weather_image
        await cache_weather_image(group, url, photographer, cached_at.isoformat())
    except Exception as e:
        logger.warning(f"DB cache write failed for image group '{group}': {e}")
