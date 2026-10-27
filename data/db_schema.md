# Database Schema

## users Table

| Column         | Type     | Description                                |
| -------------- | -------- | ------------------------------------------ |
| chat_id        | INTEGER  | Telegram chat ID (Primary Key)             |
| username       | TEXT     | Telegram username                          |
| is_admin       | BOOLEAN  | Is user admin? (0 = false, 1 = true)       |
| is_whitelisted | BOOLEAN  | Is user whitelisted? (0 = false, 1 = true) |
| adm_code       | TEXT     | BMKG administrative code                   |
| adm_name       | TEXT     | Administrative name                        |
| last_active    | DATETIME | Last active timestamp                      |

## config Table

| Column | Type | Description                     |
| ------ | ---- | ------------------------------- |
| key    | TEXT | Configuration key (Primary Key) |
| value  | TEXT | Configuration value             |

### Nowcast alert keys (prefix `cap_`)

Dedup state for the nowcast broadcast job (`nowcast_alert_job`). All values
start with an epoch second so the weekly cleanup can prune by **age** with
`CAST(value AS INTEGER)` (see `cleanup_old_alerts`).

| Key                          | Value             | Purpose                                                                 |
| ---------------------------- | ----------------- | ----------------------------------------------------------------------- |
| `cap_<chat_id>_<cap_id>`     | `<epoch>`         |Exact dedup per chat: this CAP identifier was already delivered          |
| `cap_last_<chat_id>_<prov>\|<event>` | `<epoch>:<rank>` | Last alert sent per (chat, province+event); `rank` = severity rank (Minor 1 … Extreme 4) for the repeat cooldown (`NOWCAST_COOLDOWN_MIN`, default 60 min) and severity-escalation bypass |

Legacy keys (`cap_<cap_id>` with value `"sent"`) from before the per-chat
rework carry no epoch — `CAST` yields 0, so the first cleanup run removes them.

## user_prefs Table

| Column         | Type    | Description                         |
| -------------- | ------- | ----------------------------------- |
| chat_id        | INTEGER | Telegram chat ID (PK, FK to users)  |
| notify_quake   | INTEGER | 1 = receive quake broadcasts         |
| notify_weather | INTEGER | 1 = receive weather broadcasts       |
| notify_nowcast | INTEGER | 1 = receive nowcast alert broadcasts |

## weather_cache Table

| Column      | Type     | Description                      |
| ----------- | -------- | -------------------------------- |
| adm_code    | TEXT     | BMKG adm4 code (Primary Key)     |
| cached_json | TEXT     | Raw BMKG weather JSON (as string)|
| cached_at   | DATETIME | ISO timestamp of when cached     |

## pending_sends Table

Queues failed Telegram sends for retry.

| Column      | Type     | Description                              |
| ----------- | -------- | ---------------------------------------- |
| id          | INTEGER  | Auto-increment primary key               |
| chat_id     | INTEGER  | Target Telegram chat ID                  |
| message     | TEXT     | Message text (HTML)                      |
| photo_url   | TEXT     | Photo URL (NULL for text-only)           |
| retry_count | INTEGER  | Number of failed retries                 |
| created_at  | DATETIME | When queued                              |

## weather_image_cache Table

Stores Unsplash photo URLs by weather condition group (6-hour TTL).

| Column          | Type     | Description                                  |
| --------------- | -------- | -------------------------------------------- |
| condition_group | TEXT     | Weather group (clear/cloudy/... PK)          |
| image_url       | TEXT     | Unsplash image URL                           |
| photographer    | TEXT     | Photographer name (for credit line)          |
| cached_at       | DATETIME | ISO timestamp of when cached                 |
