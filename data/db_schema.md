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
