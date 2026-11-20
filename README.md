# BMKG Bot — Pantau Cuaca & Gempa via Telegram

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4.svg)](https://core.telegram.org/bots)

Bot Telegram untuk memantau data cuaca, gempa bumi, dan peringatan dini cuaca (nowcast) dari **BMKG (Badan Meteorologi, Klimatologi, dan Geofisika)** Indonesia. Bot mengirim notifikasi otomatis ke pengguna berdasarkan preferensi lokasi dan jenis notifikasi.

> **Disclaimer:** Proyek komunitas, **bukan bot resmi BMKG**. Data cuaca, gempa, dan peringatan dini bersumber dari layanan publik BMKG dan dapat berubah sewaktu-waktu. Selalu rujuk kanal resmi BMKG ([bmkg.go.id](https://www.bmkg.go.id)) untuk keputusan keselamatan.

## Fitur

| Fitur | Keterangan |
|-------|-----------|
| 🔴 **Notifikasi Gempa** | Broadcast otomatis saat gempa terdeteksi BMKG (setiap 2 menit) |
| 🌧️ **Peringatan Dini Cuaca** | Nowcast dari BMKG, filter per provinsi (setiap 10 menit) |
| 📅 **Prakiraan Cuaca Harian** | Notifikasi otomatis jam 06:30 (ringkasan 5 waktu) |
| 🌤️ **Cuaca Sore** | Notifikasi cuaca jam terdekat jam 16:45 |
| 💡 **Insight Cerdas** | Analisis cuaca otomatis: potensi hujan, panas ekstrem, angin kencang, tips aktivitas |
| 📍 **Multi-lokasi** | Set lokasi per pengguna (provinsi → kab/kota → desa/kelurahan) |
| 🔔 **Preferensi Notifikasi** | Pilih jenis notifikasi yang diterima (gempa/cuaca/nowcast) |
| 👥 **Multi-user** | Mendukung banyak pengguna dengan database terpisah |
| 🛡️ **Mode Akses** | OPEN / WHITELIST / MAINTENANCE |

## Command

### User

| Command | Deskripsi |
|---------|-----------|
| `/start` | Registrasi awal & atur lokasi |
| `/cuaca` | Cuaca saat ini — `/cuaca` tanpa argumen memakai lokasi tersimpan; `/cuaca wates` menjawab untuk lokasi yang disebut (cakupan seluruh provinsi Pulau Jawa, 25 ribu+ desa) |
| `/prakiraan` | Prakiraan cuaca 3 hari ke depan (ringkasan + 08.00 & 17.00) |
| `/per_jam` | Cuaca per jam untuk hari ini |
| `/gempa` | Informasi gempa bumi terkini |
| `/nowcast` | Peringatan dini cuaca (filter provinsi) |
| `/lokasi` | Atur atau ubah lokasi — pemilih 3 lapis (provinsi → kab/kota → desa/kelurahan) |
| `/notifikasi` | Atur jenis notifikasi yang diterima |
| `/bantuan` | Daftar perintah |
| `/ping` | Cek status bot |

Nama lama `/cuaca_hari_ini` dan `/atur_notif` **masih diterima** sebagai alias,
dengan satu pesan pemberitahuan nama barunya. Menu perintah Telegram hanya
menampilkan nama baru.

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

## Cakupan Wilayah

Data wilayah (`src/utils/regions/`, satu modul per provinsi) memuat kode administrasi tingkat desa/kelurahan (adm4) untuk **seluruh provinsi Pulau Jawa**, sesuai Kepmendagri (kode wilayah administrasi tingkat IV — daftar yang sama dengan yang diminta API BMKG):

| Provinsi | Desa/Kelurahan |
|---|---|
| DI Yogyakarta | 438 |
| Banten | 1.552 |
| DKI Jakarta | 267 |
| Jawa Barat | 5.957 |
| Jawa Tengah | 8.563 |
| Jawa Timur | 8.494 |
| **Total** | **25.271** |

- Sumber kode: mirror publik Kepmendagri ([vermaysha/database-wilayah-indonesia](https://github.com/vermaysha/database-wilayah-indonesia), konversi dari [cahyadsn/wilayah](https://github.com/cahyadsn/wilayah)). Label mengikuti nama desa versi BMKG sendiri (`lokasi.desa`).
- **Catatan lubang BMKG**: grid BMKG regenerate dua kali sehari, dan kode yang sama bisa 404 di satu jendela waktu lalu normal di jendela berikutnya. Bot tetap melayani kode mana pun di pustaka — kena lubang hanya menurunkan kualitas jawaban via jalur fallback data cadangan yang sudah ada.
- Validasi live (dev-only, tidak dijalankan pytest): `python scripts/validate_regions.py --sample 400 --rate 50 --windows 3` — kode mencurigakan diulang lintas jendela waktu; hanya gagal di semua jendela yang dilaporkan sebagai lubang permanen.

## Struktur Proyek

```
bmkg-bot/
├── data/                       # SQLite database (persistent, gitignored)
├── src/
│   ├── main.py                 # Entry point, scheduler, broadcast jobs
│   ├── database.py             # Manajemen database (async, shared connection)
│   ├── handlers/
│   │   ├── admin.py            # Command admin (panel, whitelist)
│   │   └── user.py             # Command user (cuaca, gempa, nowcast, dll)
│   ├── services/
│   │   ├── bmkg_api.py         # Fetcher & parser data BMKG API
│   │   └── unsplash_client.py  # Foto cuaca (opsional, butuh API key)
│   └── utils/
│       ├── constants.py        # PROVINCE_MAP + re-export REGION_DATA dari utils/regions/
│       ├── weather_table.py    # Tabel kode cuaca BMKG (satu sumber kebenaran)
│       ├── keyboards.py        # Inline keyboard builder
│       ├── text.py             # Escaping & format nilai
│       ├── design.py           # Perakitan pesan & batas panjang
│       ├── formatters.py       # Format pesan gempa & nowcast
│       └── insight_templates.py# 50+ template insight cuaca
├── tests/                      # Tes (pytest, tanpa jaringan)
├── Dockerfile
├── docker-compose.yml
├── .env.template               # Contoh konfigurasi (salin jadi .env)
└── LICENSE                     # Lisensi MIT (kode proyek ini)
```

### Lapisan presentasi

| File | Tanggung jawab |
|------|----------------|
| `utils/text.py` | Escaping HTML, format angka (`fmt_temp`/`fmt_hum`/`fmt_wind`), daftar bullet, `MISSING` (`—`) |
| `utils/design.py` | `compose()` — satu budgetsatu caption, aturan kredit foto, urutan pemangkasan pesan |
| `utils/formatters.py` | Format pesan gempa & peringatan dini cuaca (dipakai bersama oleh command dan broadcast) |

Semua data dari BMKG diperlakukan sebagai input tidak dipercaya dan wajib
melewati `esc()`. `compose()` menjamin pesan tidak pernah
melebihi 1024 karakter caption: bagian yang paling boleh hilang dipangkas lebih
dulu, lalu pengguna diberi tahu, alih-alih pesan ditolak Telegram dan hilang
diam-diam.

## Instalasi & Deploy

### Prasyarat

- Python 3.11+
- Token bot Telegram (dari [@BotFather](https://t.me/BotFather))
- Telegram user ID kamu sebagai admin (chat ke [@userinfobot](https://t.me/userinfobot) untuk melihat ID)

### 1. Clone & Setup

```bash
git clone https://github.com/b4khtiar/bmkg_bot.git bmkg-bot
cd bmkg-bot
cp .env.template .env
```

Isi `.env` (wajib):

```
BOT_TOKEN=123456789:AA... (dari @BotFather)
ADMIN_CHAT_ID=123456789 (ID Telegram kamu)
```

> 🔒 **Keamanan:** `.env` sudah masuk `.gitignore` dan tidak boleh di-commit.
> Jangan pernah membagikan isi `BOT_TOKEN` ke publik — siapa pun yang
> memegangnya bisa mengendalikan bot kamu. Kalau token bocor, revoke lewat
> [@BotFather](https://t.me/BotFather) → `/revoke`.

### 2. Konfigurasi (opsional)

| Variabel | Wajib? | Default | Keterangan |
|----------|--------|---------|------------|
| `BOT_TOKEN` | Ya | — | Token dari @BotFather |
| `ADMIN_CHAT_ID` | Ya | — | ID Telegram admin |
| `UNSPLASH_ACCESS_KEY` | Tidak | — | Tanpa ini bot jalan normal, hanya tanpa foto cuaca |
| `LOG_LEVEL` | Tidak | `INFO` | Level log |
| `HEALTH_SERVER_PORT` | Tidak | `8080` | Port health check |
| `BMKG_FAILURES_ALERT_THRESHOLD` | Tidak | `3` | Batas failure sebelum alert admin |
| `BROADCAST_FAILURE_RATE` | Tidak | `0.2` | Batas failure rate broadcast |
| `DB_TIMEOUT_ALERT_SECONDS` | Tidak | `5` | Batas timeout DB |
| `NOWCAST_COOLDOWN_MIN` | Tidak | `60` | Cooldown pengulangan nowcast (menit) |

### 3. Jalankan dengan Podman/Docker

```bash
podman-compose build
podman-compose up -d
```

### 4. Atau langsung dengan Python

```bash
pip install -r requirements.txt
python src/main.py
```

## Pengembangan

```bash
pip install -r requirements.txt pytest
python -m pytest
```

Tes tidak memanggil jaringan. Fixture payload BMKG yang dipangkas ada di
`tests/fixtures/bmkg.py`, dan sengaja dibuat berlebihan (bullet dampak dan saran
banyak, `Dirasakan` panjang, karakter HTML di tiap field) karena payload
"bersih" tidak akan menangkap bug panjang-kapitan maupun escaping.

`tests/aiogram_stub.py` memasang tiruan aiogram hanya bila paket aslinya tidak
terpasang — cukup untuk menguji perilaku handler dan broadcast, bukan untuk
menyimulasikan Telegram.

## Database

Bot menggunakan SQLite (`data/bot_data.db`, gitignored) dengan tabel:

- **users** — Data pengguna (chat_id, username, lokasi, whitelist)
- **config** — Konfigurasi global (bot_mode, metadata, cache alert)
- **user_prefs** — Preferensi notifikasi per pengguna
- **weather_cache** — Cache cuaca 15 menit (fallback saat BMKG unreachable)
- **pending_sends** — Antrean retry pesan gagal
- **weather_image_cache** — Cache URL foto Unsplash (TTL 6 jam)

Skema lengkap: [`data/db_schema.md`](data/db_schema.md).

## API BMKG yang Digunakan

| Endpoint | Keperluan |
|----------|-----------|
| `api.bmkg.go.id/publik/prakiraan-cuaca?adm4=...` | Data cuaca per kelurahan |
| `data.bmkg.go.id/DataMKG/TEWS/autogempa.json` | Gempa bumi terkini |
| `www.bmkg.go.id/alerts/nowcast/id` | RSS peringatan dini cuaca |
| `static.bmkg.go.id/...` | Shakemap gempa |

## Atribusi Data

- **Data cuaca, gempa & nowcast** © [BMKG](https://www.bmkg.go.id) — layanan publik. Proyek ini tidak berafiliasi dengan BMKG.
- **Foto cuaca** via [Unsplash](https://unsplash.com) — setiap foto yang dikirim bot mencantumkan kredit fotografer di caption. Butuh `UNSPLASH_ACCESS_KEY` sendiri untuk mengaktifkan fitur ini.
- **Kode wilayah** turunan mirror publik Kepmendagri: [vermaysha/database-wilayah-indonesia](https://github.com/vermaysha/database-wilayah-indonesia) (konversi dari [cahyadsn/wilayah](https://github.com/cahyadsn/wilayah)).

## Lisensi

Kode proyek ini berlisensi [MIT](LICENSE) © 2026 Y. Bakhtiar — bebas dipakai,
dimodifikasi, dan didistribusikan ulang (termasuk komersial) selama mencantumkan
copyright di atas.

Lisensi MIT hanya mencakup **kode**. Data BMKG, foto Unsplash, dan data wilayah
tetap milik pemegang hak masing-masing (lihat Atribusi Data di atas).
