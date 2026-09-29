# BMKG Bot — Pantau Cuaca & Gempa via Telegram

Bot Telegram untuk memantau data cuaca, gempa bumi, dan peringatan dini cuaca (nowcast) dari **BMKG (Badan Meteorologi, Klimatologi, dan Geofisika)** Indonesia. Bot mengirim notifikasi otomatis ke pengguna berdasarkan preferensi lokasi dan jenis notifikasi.

## Fitur

| Fitur | Keterangan |
|-------|-----------|
| 🔴 **Notifikasi Gempa** | Broadcast otomatis saat gempa terdeteksi BMKG (setiap 2 menit) |
| 🌧️ **Peringatan Dini Cuaca** | Nowcast dari BMKG, filter per provinsi (setiap 10 menit) |
| 📅 **Prakiraan Cuaca Harian** | Notifikasi otomatis jam 06:30 (ringkasan 5 waktu) |
| 🌤️ **Cuaca Sore** | Notifikasi cuaca jam terdekat jam 16:45 |
| 💡 **Insight Cerdas** | Analisis cuaca otomatis: potensi hujan, panas ekstrem, angin kencang, tips aktivitas |
| 📍 **Multi-lokasi** | Set lokasi per pengguna (provinsi → kota/kabupaten) |
| 🔔 **Preferensi Notifikasi** | Pilih jenis notifikasi yang diterima (gempa/cuaca/nowcast) |
| 👥 **Multi-user** | Mendukung banyak pengguna dengan database terpisah |
| 🛡️ **Mode Akses** | OPEN / WHITELIST / MAINTENANCE |

## Command

### User

| Command | Deskripsi |
|---------|-----------|
| `/start` | Registrasi awal & atur lokasi |
| `/cuaca` | Cuaca saat ini (jam terdekat) |
| `/prakiraan` | Prakiraan cuaca 3 hari ke depan (ringkasan + 08.00 & 17.00) |
| `/cuaca_hari_ini` | Cuaca per jam untuk hari ini |
| `/gempa` | Informasi gempa bumi terkini |
| `/nowcast` | Peringatan dini cuaca (filter provinsi) |
| `/atur_notif` | Atur jenis notifikasi yang diterima |
| `/ping` | Cek status bot |

### Admin

| Command | Deskripsi |
|---------|-----------|
| `/admin` | Buka panel kontrol admin (ubah mode bot) |
| `/whitelist` | Lihat/tambah/hapus daftar whitelist |

## Cara Kerja Insight Cuaca

Bot menganalisis data cuaca dari BMKG dan menghasilkan insight otomatis dengan 50+ template variasi:

- **Hujan Petir** — Peringatan keselamatan, tips proteksi elektronik
- **Hujan (berbagai waktu)** — Saran sesuai jam: pagi, siang, jam pulang
- **Panas Ekstrem** — Tips hidrasi, perlindungan kulit
- **Cerah** — Rekomendasi aktivitas outdoor
- **Angin Kencang** — Peringatan benda terbang, keselamatan berkendara
- **Kelembapan Ekstrem** — Tips kenyamanan tubuh
- **Tren Suhu** — Perbandingan suhu hari ini vs besok

## Struktur Proyek

```
bmkg-bot/
├── data/                       # SQLite database (persistent)
├── src/
│   ├── main.py                 # Entry point, scheduler, broadcast jobs
│   ├── database.py             # Manajemen database (async, shared connection)
│   ├── handlers/
│   │   ├── admin.py            # Command admin (panel, whitelist)
│   │   └── user.py             # Command user (cuaca, gempa, nowcast, dll)
│   ├── services/
│   │   └── bmkg_api.py         # Fetcher & parser data BMKG API
│   └── utils/
│       ├── constants.py        # WEATHER_CODES, PROVINCE_MAP, REGION_DATA
│       ├── keyboards.py        # Inline keyboard builder
│       └── insight_templates.py# 50+ template insight cuaca
├── Dockerfile
├── docker-compose.yml
└── .env                        # Token & konfigurasi (tidak di-commit)
```

## Instalasi & Deploy

### Prasyarat

- Python 3.11+
- Telegram Bot Token (dari [@BotFather](https://t.me/BotFather))

### 1. Clone & Setup

```bash
git clone <repo-url> bmkg-bot
cd bmkg-bot
cp .env.template .env
```

Isi `.env`:
```
BOT_TOKEN=your_bot_token_here
ADMIN_CHAT_ID=your_telegram_id
```

### 2. Jalankan dengan Podman/Docker

```bash
podman-compose build
podman-compose up -d
```

### 3. Atau langsung dengan Python

```bash
pip install -r requirements.txt
python src/main.py
```

## Database

Bot menggunakan SQLite (`data/bot_data.db`) dengan 3 tabel:

- **users** — Data pengguna (chat_id, username, lokasi, whitelist)
- **config** — Konfigurasi global (bot_mode, metadata, cache alert)
- **user_prefs** — Preferensi notifikasi per pengguna

## API BMKG yang Digunakan

| Endpoint | Keperluan |
|----------|-----------|
| `api.bmkg.go.id/publik/prakiraan-cuaca?adm4=...` | Data cuaca per kelurahan |
| `data.bmkg.go.id/DataMKG/TEWS/autogempa.json` | Gempa bumi terkini |
| `www.bmkg.go.id/alerts/nowcast/id` | RSS peringatan dini cuaca |
| `static.bmkg.go.id/...` | Shakemap gempa |

## Lisensi

MIT
