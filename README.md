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
| `/cuaca` | Cuaca saat ini — `/cuaca` tanpa argumen memakai lokasi tersimpan; `/cuaca wates` menjawab untuk lokasi yang disebut (cakupan DI Yogyakarta) |
| `/prakiraan` | Prakiraan cuaca 3 hari ke depan (ringkasan + 08.00 & 17.00) |
| `/per_jam` | Cuaca per jam untuk hari ini |
| `/gempa` | Informasi gempa bumi terkini |
| `/nowcast` | Peringatan dini cuaca (filter provinsi) |
| `/lokasi` | Atur atau ubah lokasi |
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
│       ├── constants.py        # PROVINCE_MAP, REGION_DATA, mode bot
│       ├── weather_table.py    # Tabel kode cuaca BMKG (satu sumber kebenaran)
│       ├── keyboards.py        # Inline keyboard builder
│       ├── text.py             # Escaping & format nilai
│       ├── design.py           # Perakitan pesan & batas panjang
│       ├── formatters.py       # Format pesan gempa & nowcast
│       └── insight_templates.py# 50+ template insight cuaca
├── tests/                      # Tes (pytest, tanpa jaringan)
├── Dockerfile
├── docker-compose.yml
└── .env                        # Token & konfigurasi (tidak di-commit)
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
