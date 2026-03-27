# BMKG Bot

This bot fetches earthquake data from BMKG (Badan Meteorologi, Klimatologi, dan Geofisika) and sends it to a Telegram channel.

## Features

- Fetches earthquake data from BMKG API
- Sends earthquake notifications to Telegram channel
- Supports multiple locations for monitoring
- Admin commands for managing the bot

## Project Structure

```plaintext
bmkg-bot/
├── data/
│   └── bot_data.db        # SQLite Database (Persistent)
├── src/
│   ├── main.py            # Entry point & Polling
│   ├── database.py        # Management DB (Async)
│   ├── handlers/          # Folder untuk memisahkan logika command
│   │   ├── admin.py       # Command khusus Admin
│   │   └── user.py        # Command untuk semua user
│   ├── services/
│   │   └── bmkg_api.py    # Fetcher data BMKG
│   └── utils/
│       └── constants.py   # Enum untuk data statis
│       └── keyboards.py   # Keyboard untuk interaksi user
├── Dockerfile
└── docker-compose.yml
```
