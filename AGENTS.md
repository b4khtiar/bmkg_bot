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
- **Timezone**: defaults to `Asia/Jakarta` (Dockerfile hardcodes `TZ=Asia/Jakarta`; docker-compose overrides via `- TZ=Asia/Jakarta`). `ADMIN_CHAT_ID` is used in `src/main.py` and `handlers/admin.py` — mismatch breaks admin commands.
- **Database**: SQLite at `data/bot_data.db` (gitignored). Connection is a process-wide singleton in `src/database.py` (`_db_connection`); opened with WAL mode + 5s busy timeout. Initialized via `init_db()` on startup.
- **Docker note**: Dockerfile copies `src/` into `/app/src/`, but DB path is relative (`data/bot_data.db`). docker-compose mounts `./data:/app/data:z` to persist. If you run `python src/main.py` locally, DB is created at `data/bot_data.db` in the working directory.

## Architecture

- **Entry point**: `src/main.py` — sets up aiogram bot + dispatcher, APScheduler, signal handlers, and runs `start_polling`.
- **Scheduler jobs** (APScheduler, `AsyncIOScheduler`):
  - `check_quake_job` — every 2 min, fetches latest quake from BMKG, broadcasts to users with `notify_quake=1`, dedupes by `config.last_quake_id`.
  - `daily_weather_job ("Pagi")` — daily 06:30, sends daily weather brief to `notify_weather=1` users.
  - `daily_weather_job ("Sore")` — daily 16:45, sends current weather.
  - `nowcast_alert_job` — every 10 min, fetches nowcast RSS, filters by user's province, dedupes CAP alerts via `config.cap_<id>` keys.
  - `cleanup_old_alerts` — weekly Sunday 00:00, deletes all `cap_*` keys from config table.
- **Concurrency**: `_SEND_SEM` Semaphore(10) limits concurrent Telegram sends. `aiosqlite` shared connection is single-connection async.
- **Bot access modes** (stored in `config` table key `bot_mode`): `OPEN` (default), `WHITELIST`, `MAINTENANCE`. Only `ADMIN_CHAT_ID` bypasses MAINTENANCE/WHITELIST checks. See `_VALID_BOT_MODES` in `src/utils/constants.py`.

## Key modules

| File | Responsibility |
|------|---------------|
| `src/main.py` | Bot setup, scheduler, broadcast jobs, graceful shutdown |
| `src/database.py` | All SQLite access via `aiosqlite`, singleton connection |
| `src/services/bmkg_api.py` | HTTP fetch (httpx, retry, URL allowlist), BMKG JSON/XML parsing |
| `src/handlers/user.py` | User commands: `/start`, `/cuaca`, `/prakiraan`, `/gempa`, `/nowcast`, `/atur_notif`, `/ping` |
| `src/handlers/admin.py` | Admin commands: `/admin` (panel), `/whitelist` |
| `src/utils/constants.py` | `REGION_DATA`, `PROVINCE_MAP`, `WEATHER_CODES`, `WEATHER_EMOJI`, `_VALID_BOT_MODES` |
| `src/utils/keyboards.py` | Inline keyboard builders |
| `src/utils/insight_templates.py` | Smart weather insight text generation |
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
- **No tests framework**: there are no tests in this repo. If you add one, match the existing Python 3.11 style (no `src/` package prefix).

## Gotchas

- `data/bot_data.db` and `.env` are gitignored. Do not commit them.
- `__pycache__/` is also gitignored.
- The bot uses **long polling** (`dp.start_polling`) — no webhook endpoint. For production scaling, refactor to webhook mode in `main.py`.
- `check_and_update_alert()` is used for CAP alert dedup (not just "check") — it writes `cap_<id>` to config table and returns True only if the value changed.
- Weather parsing (`parse_weather_current`, `parse_weather_daily_brief`, `parse_weather_multi_day`) assumes BMKG JSON structure: `data[0].cuaca` is a list of time-group lists. If BMKG changes their API shape, these break.
