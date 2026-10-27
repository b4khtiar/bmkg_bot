# AGENTS.md — BMKG Telegram Bot

## Run the bot

```bash
# Local dev (must run from repo root; src/ uses bare imports)
cp .env.template .env
# Edit .env: set BOT_TOKEN and ADMIN_CHAT_ID
python src/main.py

# Or via Docker/Podman:
podman-compose build && podman-compose up -d
```

## Environment

- **Required env vars** (`.env`): `BOT_TOKEN`, `ADMIN_CHAT_ID`
- **Optional env vars**: `UNSPLASH_ACCESS_KEY` (weather photos — bot runs without it, text-only), `LOG_LEVEL`, `HEALTH_SERVER_PORT`, `BMKG_FAILURES_ALERT_THRESHOLD`, `BROADCAST_FAILURE_RATE`, `DB_TIMEOUT_ALERT_SECONDS`, `NOWCAST_COOLDOWN_MIN` (repeat-alert cooldown, default 60).
- **Timezone**: defaults to `Asia/Jakarta` (Dockerfile sets `ENV TZ=Asia/Jakarta`; docker-compose also passes `- TZ=Asia/Jakarta`). `ADMIN_CHAT_ID` is used in `src/main.py` and `handlers/admin.py` — mismatch breaks admin commands. **Do not compare `datetime.now()` against BMKG `local_datetime`** — the server clock is WIB-equivalent only when `TZ` is set, and `python src/main.py` on a bare host may not be. Derive dates from BMKG's own payload instead (see `parse_weather_hourly_today`).
- **Database**: SQLite at `data/bot_data.db` (gitignored). Connection is a process-wide singleton in `src/database.py` (`_db_connection`); opened with WAL mode + 5s busy timeout. Initialized via `init_db()` on startup.
- **Docker note**: Dockerfile copies `src/` into `/app/src/`, but DB path is relative (`data/bot_data.db`). docker-compose mounts `./data:/app/data:z` to persist. If you run `python src/main.py` locally, DB is created at `data/bot_data.db` in the working directory.

## Architecture

- **Entry point**: `src/main.py` — sets up aiogram bot + dispatcher, APScheduler, signal handlers, and runs `start_polling`.
- **Scheduler jobs** (APScheduler, `AsyncIOScheduler`):
  - `check_quake_job` — every 2 min, fetches latest quake from BMKG, broadcasts to users with `notify_quake=1`, dedupes by `config.last_quake_id`.
  - `daily_weather_job ("Pagi")` — daily 06:30, sends daily weather brief to `notify_weather=1` users.
  - `daily_weather_job ("Sore")` — daily 16:45, sends current weather.
  - `nowcast_alert_job` — every 10 min, fetches nowcast RSS, filters by user's province, dedupes CAP alerts via per-chat `config.cap_<chat>_<id>` keys + a 60-min repeat cooldown per (chat, province+event) with severity-escalation bypass (`NOWCAST_COOLDOWN_MIN`).
  - `cleanup_old_alerts` — weekly Sunday 00:00, prunes `cap_*` keys **older than 7 days** (`ALERT_KEY_TTL_DAYS`); values start with an epoch so age is checked via `CAST(value AS INTEGER)`.
- **Concurrency**: `_SEND_SEM` Semaphore(10) limits concurrent Telegram sends. `aiosqlite` shared connection is single-connection async.
- **Bot access modes** (stored in `config` table key `bot_mode`): `OPEN` (default), `WHITELIST`, `MAINTENANCE`. Only `ADMIN_CHAT_ID` bypasses MAINTENANCE/WHITELIST checks. See `_VALID_BOT_MODES` in `src/utils/constants.py`.

## Key modules

| File | Responsibility |
|------|---------------|
| `src/main.py` | Bot setup, scheduler, broadcast jobs, graceful shutdown, health server startup |
| `src/database.py` | All SQLite access via `aiosqlite`, singleton connection, `weather_cache` & `pending_sends` tables |
| `src/services/bmkg_api.py` | HTTP fetch (httpx, retry, URL allowlist, circuit breaker), BMKG JSON/XML parsing, cache fallback |
| `src/services/unsplash_client.py` | Unsplash photo fetch by weather condition group; caches by group (memory + SQLite, 6h TTL) |
| `src/handlers/user.py` | User commands: `/start`, `/cuaca`, `/prakiraan`, `/per_jam` (alias `/cuaca_hari_ini`), `/gempa`, `/nowcast`, `/lokasi`, `/notifikasi` (alias `/atur_notif`), `/bantuan`, `/ping` |
| `src/handlers/admin.py` | Admin commands: `/admin` (panel), `/whitelist` (validated) |
| `src/utils/constants.py` | Re-exports `REGION_DATA` from `src/utils/regions/`; `PROVINCE_MAP`, `_VALID_BOT_MODES` |
| `src/utils/regions/*.py` | Region data: one module per province (all six Java provinces, ~25k adm4 → `Kab./Kota` labels, Kepmendagri 2022 edition), merged in `__init__.py` (DIY first) |
| `src/utils/locations.py` | `/cuaca <lokasi>` resolver: name → adm4 via match ladder (exact → village → substring → reordered → district; exact tiers precomputed O(1) at import); `label_for()` validates `wxloc_`/`setloc_` callbacks against the library |
| `src/utils/weather_table.py` | Single source of truth for BMKG weather codes (`WEATHER_CONDITIONS`) + derived sets |
| `src/utils/keyboards.py` | Inline keyboard builders (with 64-byte callback_data assertions); `regency_map()` derives kab/kota grouping from `adm4[:5]` |
| `src/utils/insight_templates.py` | Smart weather insight text generation |
| `src/utils/text.py` | HTML escaping, `fmt_temp`/`fmt_hum`/`fmt_wind`, `MISSING` (`—`) |
| `src/utils/design.py` | `compose()` — caption budget, photo-credit rule, truncation order, `severity_note()` |
| `src/utils/formatters.py` | Message formatting for quake, nowcast, and all four weather commands |
| `src/logging_config.py` | Structured JSON logging with bot_mode context |
| `src/alerts.py` | Admin alert throttling, BMKG failure tracking, broadcast failure rate monitoring |
| `src/health_server.py` | Threaded stdlib HTTP `/healthz` + `/metrics` endpoints on port 8080 |
| `data/db_schema.md` | DB schema reference |

## Running from source

```bash
cd /home/yebe/Development/SIDE_PROJECT/bmkg_bot
python src/main.py
```

**Import style**: the codebase uses **bare imports** (e.g., `from database import ...`, `from handlers import ...`, `from utils.constants import ...`) with no package `__init__.py` tricks beyond empty ones in subdirs. This means **`sys.path` must include `src/`**. The code achieves this implicitly by running `python src/main.py` from the repo root — Python adds `src/` to `sys.path[0]`. **Do not add a `src/__init__.py`** or convert to package layout; it will break imports. Do not move `main.py` out of `src/`.

## BMKG API facts

- **Quake data**: `https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json` — returns `Infogempa.gempa` object. Deduped by `DateTime` field stored in `config.last_quake_id`.
- **Weather**: `https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=<code>` — `adm4` is a dot-separated administrative code (e.g., `34.01.09.2001`). The first 2 digits map to a province via `PROVINCE_MAP` in `constants.py`.
- **Nowcast**: `https://www.bmkg.go.id/alerts/nowcast/id` — RSS XML. Each item has a link to a CAP XML detail page. Province filtering uses `get_province_name(adm_code)[:2]` match against CAP `region` field.
- **URL allowlist**: `validate_url()` in `bmkg_api.py` only permits `*.bmkg.go.id` hosts — do not point fetches at other domains without updating `_ALLOWED_HOSTS`.

## Editing guidance

- **Adding a notification type**: add column to `user_prefs` table in `init_db()`, add key to `valid_prefs` set in `database.py:get_users_with_pref()` and `user.py:handle_notif_toggle()`, define scheduler job in `main.py`.
- **Adding a province**: add entry to `PROVINCE_MAP` (2-digit prefix) and optionally to `REGION_DATA` (for location picker).
- **Adding a user command**: import in `src/handlers/user.py`, route via `@router.message(Command(...))`. No registration needed in `main.py` — it already `include_router(user.router)`.
- **Adding an admin command**: same pattern in `src/handlers/admin.py`.
- **Tests**: `python -m pytest` (config in `pytest.ini`, `pythonpath = src tests`). No network calls. `tests/aiogram_stub.py` installs a stub aiogram only when the real package is missing (it pins `aiogram==3.28.2`, which the sandbox index could not serve) — enough to exercise handlers and broadcasts, not a Telegram simulation. Fixtures in `tests/fixtures/bmkg.py` are deliberately oversized.
- **Region dev scripts** (`scripts/`, dev-only, never touched by pytest): `generate_regions.py` rebuilds the province data modules from a public Kepmendagri mirror JSON (`regency.json` + `village.json`); `validate_regions.py` live-checks adm4 codes against BMKG with pacing (≤60 req/min) and multi-window retry — a suspect must fail in *every* window to be reported as a persistent hole (BMKG 404s flap across its twice-daily grid regeneration). Do not filter `REGION_DATA` from a single session.

## Gotchas

- `data/bot_data.db` and `.env` are gitignored. Do not commit them.
- `__pycache__/` is also gitignored.
- The bot uses **long polling** (`dp.start_polling`) — no webhook endpoint. For production scaling, refactor to webhook mode in `main.py`.
- **Health status has one home: `health_server.py`.** Callers *outside* an event loop (the threaded HTTP `/healthz`+`/metrics` server) use `get_health()`; aiogram handlers use `await get_health_async()`. The sync variant runs `asyncio.run()` internally, which raises inside the bot's own event loop — using it in a handler made `/ping` report "degraded" forever without ever checking anything. `/ping` and the admin panel both use the async variant. Both paths share one `_gather()` that **awaits** both checkers: `_set_checkers` checkers MUST be async callables — calling a checker without awaiting makes a bare coroutine, which is truthy, so failures would be reported healthy.
- **BMKG health probe hits real endpoints, not the bare root** (`main.py:_bmkg_health_check`). `HEAD https://api.bmkg.go.id` (no path) always returns 404, which made `/ping` say "BMKG tidak dapat dihubungi" while `/cuaca`/`/gempa` worked fine. The probe now HEADs the quake + weather endpoints the bot actually consumes, via the shared httpx client, with a 120s TTL cache so frequent `/healthz` scrapes don't hammer BMKG.
- **Nowcast dedup is two-layer, per chat** (`main.py:nowcast_alert_job`): (1) `database.mark_alert_seen()` — deterministic existence check, value is the send epoch (never a placeholder that changes between calls — the old `check_and_update_alert` compared values, so an epoch value there would make every re-check look "new"); (2) `cap_last_<chat>_<prov>|<event>` timestamps the last send per fingerprint for the repeat cooldown — BMKG re-issues the same warning as a NEW CAP (new file + identifier, e.g. `CYG...002` → `CYG...003`) every nowcast cycle, so identifier-only dedup sends the "same" alert twice 30-120 min apart. Higher CAP severity within the cooldown still goes through (escalation). The key check must stay OUTSIDE any per-user aliasing: it is keyed `cap_<chat_id>_<id>` precisely so a second user in the same province is not silently starved (the old global `cap_<id>` inside the user loop delivered each alert to only the first user in query order).
- **The location picker is 3-level (province → regency → desa)** because full Java data has ~28k desa — a flat per-province list would paginate into hundreds of pages. Regencies are *derived* from `adm4[:5]` + the `"Kab. X"` label suffix (`keyboards.regency_map`), no extra structure in `REGION_DATA`. Callbacks: `prov_<name>` → `kabpage_<prov>_<page>`/`kab_<code5>` → `desapage_<code5>_<page>`/`kabback_<code5>` → `setloc_<adm4>`. **`setloc_` carries the code only** (label via `locations.label_for()` at confirm time — the old `setloc_<code>_<label>` embedded-name format overflows Telegram's 64-byte budget); legacy-format callbacks from in-flight keyboards are still parsed. Unknown codes in `kab_`/`desapage_`/`setloc_` are rejected via the library, never forwarded or stored.
- **BMKG's weather grid has holes and they flap**: the same adm4 code can 404 in one hour and 200 the next (BMKG regenerates its grid tiles twice daily; the code list itself is Kepmendagri 2022 and matches BMKG's `desa` names). Do not filter `REGION_DATA` on one validation session — validation scripts must retry suspects in separate windows and only then report persistent holes. Weather fetches for holey codes degrade via the existing ⚠️ path + cache fallback.
- **Callback handlers that trigger a gated command must pass `command=` to `check_access`** (e.g. `wxloc_` → `check_access(callback.message, command="cuaca")`). Relying on the source message's text makes `_command_name` scrape emoji/HTML — the right decision only by accident, and MAINTENANCE would classify it as a random unknown command. Also validate any adm4/region code arriving in `callback_data` against the library (`locations.label_for`) — crafted `wxloc_` codes must not turn the bot into an out-of-coverage proxy.
- Weather parsing (`parse_weather_current`, `parse_weather_daily_brief`, `parse_weather_multi_day`) assumes BMKG JSON structure: `data` has **one** element whose `cuaca` is a list of **day groups**, each a list of entries. If BMKG changes their API shape, these break.
- **Every BMKG/CAP/RSS string must pass through `esc()`** (or `esc_href()` for link attributes). Messages use `parse_mode="HTML"`, and one unescaped `&` makes Telegram reject the whole message with `BadRequest: can't parse entities`. On the broadcast path that rejection is invisible in the admin summary: it counts Telegram call results, not deliveries, so alerts silently vanish after 3 retries.
- **Never emit a message longer than 1024 chars as a photo caption.** Build user-facing messages with `compose()` from `utils/design.py` — it enforces the budget, drops the lowest-priority block first, and discloses the trim. Do not hand-roll caption strings; that is what let nowcast alerts get dropped.
- **Insight and trend generators return plain content** (`utils/insight_templates.py`); the section headers (`💡 INSIGHT`, `📈 TREN BESOK`) belong to the formatter (`utils/formatters.py`). They once produced two stacked headers per block because the generator carried its own bold prefix that the consumer then had to regex-strip.
- `📍` is reserved for **location only** (weather headers, `/gempa` origin). Use `🗺️` for region/scope and `🏠` for the user's own area.
- **BMKG weather codes live only in `utils/weather_table.py`.** There is one `WEATHER_CONDITIONS` table keyed by code with `label`, `emoji`, `photo_group`, `insight_pool`, `sky`, and `wet`; every set (`WET_CODES`, `THUNDERSTORM_CODES`, `HAZE_CODES`, …) is derived from it. Never re-add a second code map — the previous four had already drifted apart, and `tests/test_weather_table.py` now fails on any code without a photo query, an unknown group, or two emoji for one label. `weather_table.log_problems()` runs once at startup for the same reason.
- When choosing a predicate about conditions, pick deliberately: `is_wet(code)` is physical precipitation (so "Petir" 17–24 is False), while `is_wet_or_stormy(code)` also covers thunderstorms and is what the daily rain icon must use.

## Operational notes

- **Health check**: `GET http://localhost:8080/healthz` — returns JSON `{"status":"ok/degraded","db":bool,"bmkg_reachable":bool}`. Runs as a threaded stdlib HTTP server alongside the async bot. Port configurable via `HEALTH_SERVER_PORT` env var.
- **Metrics**: `GET http://localhost:8080/metrics` — basic Prometheus-format metrics (uptime, DB/BMKG health).
- **Circuit breakers**: `CircuitBreaker` in `bmkg_api.py` — 3 consecutive failures → 10 min open state per endpoint. Weather uses per-`adm_code` breakers; quake and nowcast use shared breakers.
- **Alert cooldown**: Admin alerts are throttled to 1 every 5 minutes (same first 80 chars) to avoid spamming.
- **BMKG failure tracking**: `alerts.py:record_bmkg_failure()` / `record_bmkg_success()` track consecutive failures per endpoint. Admin alert fires when threshold `BMKG_FAILURES_ALERT_THRESHOLD` (default 3) is reached.
- **Broadcast failure monitoring**: `alerts.py:check_broadcast_failure_rate()` returns True if failure rate exceeds `BROADCAST_FAILURE_RATE` (default 0.2). Triggers immediate alert instead of just a summary log.
- **Failed message retries**: Messages that fail to send are queued in `pending_sends` table. Retried every 5 minutes via `retry_failed_sends_job`. Dropped after `MAX_SEND_RETRIES` (3) failed attempts.
- **Weather cache**: 15-min TTL SQLite cache for weather data. Served with banner "⚠️ Data cadangan..." when BMKG API is unreachable. Circuit breaker prevents further requests until cooldown expires.
- **Unsplash weather images**: Weather messages include themed photos. `UNSPLASH_ACCESS_KEY` required; weather messages fall back to text-only if unset or on fetch failure. Images cached by condition group (clear/cloudy/foggy/light_rain/heavy_rain/thunderstorm) with 6h TTL, both in-memory (`services/unsplash_client.py`) and SQLite (`weather_image_cache` table). ~8 unique groups → well under Unsplash demo tier (50 req/hour). Parsers return `{"text", "photo_url", "photographer"}` — callers check `photo_url` before using `send_photo`.
- **Logging**: Structured JSON logs to stdout. Uses `logging_config.py` with `StructuredFormatter` that includes `bot_mode` context on every record.
- **Env vars**: `BOT_TOKEN` and `ADMIN_CHAT_ID` are strictly required at startup — bot crashes with `RuntimeError` if missing.

## Phase 4 roadmap (tracked — not yet implemented)

- **Webhook migration** — Long polling doesn't scale. Switch to `dp.start_webhook()` with HTTPS for >50 users.
- **Full REGION_DATA** — DONE for Java: all six provinces (31–36) ship full desa-level coverage (~25k adm4 codes, Kepmendagri 2022 edition, see `src/utils/regions/`). Remaining: the other 28 provinces (add one module per province in `src/utils/regions/` and merge it in `__init__` — no other code changes).
- **Full Prometheus metrics** — Add custom Gauges/Counter for broadcast success/failure rates, BMKG latency, circuit breaker state.
