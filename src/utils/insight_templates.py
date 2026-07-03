import random
import logging

logger = logging.getLogger(__name__)

WEATHER_CODE_GROUPS = {
    'thunderstorm': {95, 96, 97},
    'rain': set(range(60, 83)),
    'light_rain': {60, 61, 80, 81},
    'heavy_rain': {63, 64, 65, 67, 82},
    'drizzle': {50, 51, 52, 53, 54, 55, 56, 57},
    'clear': {0, 1, 2, 3},
    'haze': {4, 5, 10, 45},
}

def analyze_weather(weather_list):
    if not weather_list:
        return None

    temps, codes, tps, humidities, winds = [], [], [], [], []
    rain_hours, peak_rain_code = [], 0

    for w in weather_list:
        try:
            temp = float(w.get('t', 0))
            code = int(w.get('weather', 0))
            tp = float(w.get('tp', 0))
            hu = float(w.get('hu', 50))
            ws = float(w.get('ws', 0))

            temps.append(temp)
            codes.append(code)
            tps.append(tp)
            humidities.append(hu)
            winds.append(ws)

            local_dt = w.get('local_datetime', '')
            if local_dt and 60 <= code <= 82:
                hour = int(local_dt.split(' ')[1].split(':')[0])
                if 6 <= hour <= 21:
                    rain_hours.append(hour)
                if code > peak_rain_code:
                    peak_rain_code = code
        except (IndexError, ValueError, TypeError):
            continue

    if not temps:
        return None

    max_temp = max(temps)
    min_temp = min(temps)
    avg_hu = sum(humidities) / len(humidities) if humidities else 50
    max_wind = max(winds) if winds else 0
    total_precip = sum(tps)

    return {
        'max_temp': max_temp,
        'min_temp': min_temp,
        'avg_hu': avg_hu,
        'max_wind': max_wind,
        'total_precip': total_precip,
        'codes': codes,
        'has_thunderstorm': any(c in WEATHER_CODE_GROUPS['thunderstorm'] for c in codes),
        'has_rain': any(c in WEATHER_CODE_GROUPS['rain'] for c in codes),
        'rain_heavy': any(c in WEATHER_CODE_GROUPS['heavy_rain'] for c in codes),
        'rain_light': any(c in WEATHER_CODE_GROUPS['light_rain'] for c in codes),
        'is_clear': all(c in WEATHER_CODE_GROUPS['clear'] for c in codes) and total_precip <= 0.01,
        'is_cloudy': all(c in {0, 1, 2, 3, 4} for c in codes) and total_precip <= 0.1,
        'rain_morning': any(6 <= h < 12 for h in rain_hours),
        'rain_afternoon': any(12 <= h < 17 for h in rain_hours),
        'rain_evening': any(17 <= h <= 21 for h in rain_hours),
        'rain_hours': rain_hours,
    }

PREFIXES = [
    "Saran hari ini:", "Insight untuk Anda:", "Catatan penting:",
    "Info kilat:", "Perhatian:", "Tips:", "Sekadar info:",
    "Pengingat:", "Yang perlu kamu tahu:", "Catatan dari BMKG:",
]

THUNDERSTORM_TEMPLATES = [
    "Hujan petir diprediksi hari ini. Jaga jarak dari pepohonan tinggi dan benda metal. Matikan perangkat elektronik yang tidak perlu saat hujan mulai turun.",
    "Ada potensi hujan disertai petir. Hindari area terbuka dan genangan air. Jika di luar ruangan, cari tempat berteduh yang aman — bukan di bawah pohon atau menara.",
    "Waspada petir! Potensi hujan petir hari ini. Amankan gadget dan peralatan rumah tangga. Jangan parkir di bawah pohon besar.",
    "Kondisi mendukung terjadinya hujan petir. Cabut charger saat hujan, hindari menyentuh pipa air atau keran, dan jangan berteduh di shelter terbuka.",
    "Hari ini berpotensi hujan petir. Siapkan jas hujan (bukan payung metal). Lebih baik tunda aktivitas outdoor yang melibatkan ketinggian.",
    "Potensi hujan petir hari ini. Yang penting: jaga jarak dari objek tinggi, matikan listrik yang tidak perlu, dan siapkan power bank — siapa tahu listrik padam.",
    "Ada tanda-tanda hujan petir nanti. Kalau punya rencana ke luar kota, cek ulang jadwal atau siapkan jalur alternatif.",
    "⚠️ Potensi hujan petir signifikan. Bagi yang tinggal di dataran tinggi atau area terbuka, ekstra waspada. Siapkan senter dan lilin.",
]

RAIN_MORNING_TEMPLATES = [
    "Hujan sudah mulai dari pagi. Siapkan payung sebelum berangkat. Aktivitas luar ruangan lebih baik ditunda ke siang atau sore.",
    "Pagi ini berawan gelap dengan potensi hujan. Perjalanan pagi butuh payung atau jas hujan. Hati-hati di jalan, permukaan bisa licin.",
    "Hujan mengawali hari. Buat yang harus berangkat pagi: bawa payung, jaket tipis, dan sabar di jalan. Waspada genangan air.",
    "Pagi yang basah. Kalau bisa, berangkat lebih awal biar tidak kehujanan di perjalanan. Jangan lupa lap kaca helm/spion.",
    "Hujan pagi hari. Vibes-nya cozy buat sarapan hangat di rumah. Tapi kalau harus keluar, pastikan tas tahan air.",
]

RAIN_AFTERNOON_TEMPLATES = [
    "Hujan diprediksi turun siang/sore. Cocok untuk aktivitas indoor. Kalau harus keluar, payung atau jas hujan wajib dibawa.",
    "Cuaca hari ini: hujan di sore hari. Manfaatkan waktu pagi untuk urusan luar rumah. Sore? Nikmati teh hangat di dalam.",
    "Sore nanti diprediksi hujan. Ide bagus: masak makanan hangat, atau rebahan sambil dengar suara hujan.",
    "Prediksi hujan di akhir hari. Kalau punya rencana outdoor, pindahkan ke pagi hari. Sore nanti stay safe, stay warm.",
    "Hujan sore hari — sempurna buat yang suka suasana adem. Tapi buat pengendara motor, siapkan jas hujan dari sekarang.",
]

RAIN_RUSH_HOUR_TEMPLATES = [
    "Hujan jam pulang kerja! Alternatif: tunggu reda dulu, atau siapkan jas hujan. Cek info kemacetan sebelum berangkat.",
    "Sore ini hujan pas jam sibuk. Kalau bisa, tunda pulang 30-60 menit. Atau langsung aja — yang penting bawa jas hujan dan hati-hati.",
    "Cuaca tidak bersahabat di jam pulang: hujan + kemacetan = sabar ekstra. Siapkan playlist favorit selama perjalanan.",
    "Jam sibuk + hujan = kombinasi bikin bete. Tips: bawa jas hujan, jaga jarak pengereman, dan jangan memacu kendaraan.",
    "Prediksi hujan pada jam 15-18. Waktu paling padat aktivitas. Siapkan payung di tas dari pagi, jangan sampai kaget sore nanti.",
]

RAIN_LIGHT_TEMPLATES = [
    "Hujan ringan hari ini, tidak perlu khawatir berlebihan. Cukup bawa payung kecil di tas. Aktivitas outdoor masih bisa dilakukan.",
    "Hujan gerimis sepanjang hari. Mood-nya cozy! Cocok untuk baca buku atau kerja di kafe. Payung tetap harus ada.",
    "Gerimis tipis tidak mengganggu aktivitas. Tapi tetap bawa payung — kadang gerimis bisa berubah jadi hujan deras tanpa aba-aba.",
    "Hujan rintik-rintik. Suasana adem, cocok untuk tidur siang atau ngopi sambil lihat hujan dari jendela.",
]

RAIN_HEAVY_TEMPLATES = [
    "Hujan deras diprediksi hari ini. Jika tidak ada keperluan mendesak, tunda dulu perjalanan. Jangan paksakan diri di kondisi jalan licin.",
    "Intensitas hujan cukup tinggi. Waspada potensi banjir di daerah rendah. Pastikan drainase rumah lancar dan barang berharga di tempat aman.",
    "Hujan lebat! Kurangi kecepatan berkendara, nyalakan lampu, dan jaga jarak aman. Hindari jalur yang rawan banjir atau longsor.",
    "Curah hujan tinggi hari ini. Untuk yang tinggal di daerah rawan longsor atau banjir, tetap waspada dan pantau info terkini dari BPBD.",
    "Hujan deras disertai angin kencang. Amankan benda-benda ringan di halaman. Jika atap rumah sudah rapuh, waspada kebocoran.",
]

HEAT_TEMPLATES = [
    "Suhu hari ini terik, maksimum {max_temp:.0f}°C. Minum air minimal 8 gelas. Gunakan tabir surya SPF 30+ saat keluar. Hindari aktivitas berat di bawah matahari langsung.",
    "Panas menyengat ({max_temp:.0f}°C). Minum air rutin (jangan tunggu haus), pakai baju tipis berwarna terang, dan istirahat di tempat teduh.",
    "Suhu cukup tinggi ({max_temp:.0f}°C). Kalau harus keluar, gunakan topi atau payung. Bawa botol air kemana-mana. Jangan tinggal di mobil parkir!",
    "Terik hari ini, suhu bisa mencapai {max_temp:.0f}°C. Aktivitas outdoor sebaiknya pagi atau sore saja. Siang hari manfaatkan AC atau kipas.",
    "Suhu {max_temp:.0f}°C — panas banget! Hindari alkohol dan kafein berlebihan, dehidrasi datang lebih cepat di cuaca begini.",
    "Panas terik ({max_temp:.0f}°C). Minum es kelapa muda, mandi air dingin, dan hindari aktivitas fisik berat di jam 11-15.",
    "Cuaca gerah karena suhu tinggi. Pakai bahan katun atau linen yang menyerap keringat. Jangan lupa topi atau kacamata hitam kalau keluar.",
    "{max_temp:.0f}°C — suhu maksimum hari ini. Buat yang punya tanaman, siram di pagi dan sore hari supaya tidak layu.",
]

CLEAR_TEMPLATES = [
    "Hari cerah sempurna! Cocok untuk jemur pakaian, olahraga ringan, bersepeda, atau jalan-jalan santai. Manfaatkan cuaca sebelum berubah.",
    "Cuaca hari ini cerah berawan. Ideal untuk aktivitas luar ruangan. Jangan lupa sunscreen kalau berencana di bawah matahari lama.",
    "Hari yang menyenangkan untuk keluar rumah. Suhu nyaman, tidak ada hujan. Mumpung cuaca bagus, manfaatkan sebaik-baiknya!",
    "Cerah sepanjang hari. Cocok untuk cuci mobil, jemur kopi atau padi, atau sekadar jalan kaki menikmati udara segar.",
    "Cuaca bersahabat hari ini. Tidak terlalu panas, tidak hujan. Waktu yang pas untuk piknik, BBQ, atau main di taman.",
    "Langit cerah, angin sepoi. Kondisi prima untuk fotografi outdoor atau sekadar sarapan di teras. Jangan lupa hydration!",
]

CLOUDY_TEMPLATES = [
    "Cuaca berawan stabil hari ini. Nyaman untuk beraktivitas, tidak perlu khawatir hujan mendadak. Suhu terasa adem.",
    "Hari ini berawan tapi tidak hujan. Suasana tenang. Cocok untuk bekerja di luar (outdoor cafe misalnya) tanpa khawatir kepanasan.",
    "Berawan sepanjang hari, suhu stabil. Tidak ada cuaca ekstrem yang diprediksi. Hari yang predictable — enak untuk planning.",
    "Langit berawan. Kondisi ideal buat yang tidak suka terik maupun hujan. Nikmati keseimbangan alam!",
    "Cuaca agak mendung tapi nyaman. Pas untuk jalan-jalan santai atau belanja ke pasar tanpa takut gerah.",
]

WIND_TEMPLATES = [
    "Angin cukup kencang hari ini ({max_wind:.0f} km/jam). Hati-hati dengan benda ringan yang beterbangan. Parkir kendaraan di tempat aman.",
    "Kecepatan angin meningkat ({max_wind:.0f} km/jam). Jika bersepeda atau berkendara, waspada terhadap hembusan mendadak. Hindari jalur pinggir tebing.",
    "Angin bertiup kencang. Benda-benda ringan di luar bisa terbang. Pastikan jemuran aman dan atap rumah dalam kondisi baik.",
    "Hari ini angin cukup kuat ({max_wind:.0f} km/jam). Cocok untuk main layangan! Tapi hindari pohon besar dan kabel listrik.",
    "Waspada angin kencang. Jika berteduh, pilih bangunan kokoh. Hindari reklame atau papan billboard yang tidak stabil.",
]

HUMIDITY_HIGH_TEMPLATES = [
    "Kelembapan tinggi ({avg_hu:.0f}%). Terasa gerah meski suhu tidak terlalu panas. Pakai bahan katun, minum air cukup, mandi air hangat bisa membantu.",
    "Udara lembap hari ini ({avg_hu:.0f}%). Bisa bikin tidak nyaman. Buka jendela untuk ventilasi atau nyalakan kipas. Baju tipis sangat disarankan.",
    "Lembap ({avg_hu:.0f}%). Cocok untuk tanaman hias, tapi tidak terlalu nyaman untuk manusia. Minum air lebih banyak dari biasanya.",
    "Kelembapan tinggi, kulit terasa lengket. Mandi dua kali sehari, pakai bedak tabur, dan hindari bahan sintetis.",
    "Udara terasa berat karena kelembapan tinggi ({avg_hu:.0f}%). Kalau pakai AC, set suhu 24-25°C agar tidak terlalu dingin tapi tetap nyaman.",
]

HUMIDITY_LOW_TEMPLATES = [
    "Kelembapan rendah ({avg_hu:.0f}%). Kulit dan bibir bisa kering. Gunakan pelembap dan lip balm. Minum air cukup sepanjang hari.",
    "Udara kering hari ini ({avg_hu:.0f}%). Humidifier bisa membantu, atau taruh baskom air di dalam ruangan untuk menambah kelembapan.",
    "Kelembapan rendah, rambut bisa kering dan kusam. Gunakan kondisioner ekstra dan hindari hair dryer terlalu panas.",
    "Hari ini kering ({avg_hu:.0f}%). Cocok untuk jemur pakaian — cepat kering! Tapi kulit butuh pelembap tambahan.",
]

HAZE_TEMPLATES = [
    "Kabut/asap mengurangi jarak pandang. Hati-hati berkendara — nyalakan lampu, jaga jarak aman, dan kurangi kecepatan.",
    "Visibilitas rendah karena kabut. Hindari perjalanan jauh jika tidak penting. Jika harus, gunakan fog lamp dan jangan menyalip.",
    "Kabut menyelimuti area pagi ini. Tunggu kabut reda atau ekstra hati-hati. Jangan ngebut!",
    "Udara berkabut. Aktivitas outdoor sebaiknya ditunda. Manfaatkan waktu untuk sarapan hangat di rumah.",
    "Jarak pandang terbatas karena asap atau kabut. Bagi yang punya gangguan pernapasan, pakai masker dan batasi aktivitas luar.",
]

DEFAULT_TEMPLATES = [
    "Cuaca hari ini cenderung stabil. Tidak ada peringatan cuaca ekstrem. Tetap waspada dan nikmati hari!",
    "Kondisi cuaca normal. Tidak ada yang perlu dikhawatirkan. Tetap bawa payung siaga ya!",
    "Tidak ada cuaca signifikan hari ini. Hari yang baik untuk beraktivitas tanpa gangguan cuaca.",
    "Cuaca biasa saja, tidak ada yang istimewa. Kadang hari yang membosankan itu yang terbaik!",
    "Sejauh ini cuaca bersahabat. Tapi ingat, cuaca Indonesia bisa berubah kapan saja — tetap sedia payung.",
]

KOMBINASI_TEMPLATES = [
    "Kombinasi cuaca panas dan kelembapan tinggi bikin gerah maksimal. Saran: minum air kelapa, pakai baju longgar, dan hindari aktivitas berat.",
    "Hujan di tengah suhu hangat — tipikal cuaca tropis. Pakai baju yang mudah kering dan bawa sandal cadangan.",
    "Cuaca panas + angin kencang = potensi debu beterbangan. Tutup makanan dan minuman, terutama kalau jualan di luar.",
    "Angin kencang saat hujan bisa bikin suhu terasa lebih dingin. Siapkan jaket atau selimut tambahan.",
    "Hujan petir di musim pancaroba adalah hal biasa. Tetaplah tenang, siapkan perlengkapan darurat, dan pantau info resmi BMKG.",
]


def pick_templates_until(pool, meta, max_total_chars=600):
    chosen = []
    total_chars = 0
    shuffled = random.sample(pool, len(pool))
    for tmpl in shuffled:
        formatted = tmpl.format(**meta)
        if total_chars + len(formatted) > max_total_chars:
            continue
        chosen.append(formatted)
        total_chars += len(formatted)
        if random.random() < 0.5:
            break
    if not chosen:
        chosen.append(random.choice(pool).format(**meta))
    return chosen


def generate_smart_insight(weather_list, max_insights=None):
    meta = analyze_weather(weather_list)
    if not meta:
        return "Tidak ada data cuaca tersedia."

    pref = random.choice(PREFIXES)
    lines = []
    is_short = max_insights == 1

    if meta['has_thunderstorm']:
        pool = THUNDERSTORM_TEMPLATES
        emoji = "⚡"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    elif meta['rain_heavy']:
        pool = RAIN_HEAVY_TEMPLATES
        emoji = "⛈️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    elif meta['has_rain']:
        rush = any(15 <= h <= 18 for h in meta['rain_hours'])
        if rush:
            pool = RAIN_RUSH_HOUR_TEMPLATES
        elif meta['rain_morning']:
            pool = RAIN_MORNING_TEMPLATES
        elif meta['rain_afternoon'] or meta['rain_evening']:
            pool = RAIN_AFTERNOON_TEMPLATES
        else:
            pool = RAIN_LIGHT_TEMPLATES
        emoji = "🌧️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    elif meta['max_temp'] >= 34:
        pool = HEAT_TEMPLATES
        emoji = "☀️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    elif meta['is_clear']:
        pool = CLEAR_TEMPLATES
        emoji = "☀️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    elif meta['is_cloudy']:
        pool = CLOUDY_TEMPLATES
        emoji = "☁️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))
    else:
        pool = DEFAULT_TEMPLATES
        emoji = "ℹ️"
        if is_short:
            lines.append(random.choice(pool).format(**meta))
        else:
            lines.extend(pick_templates_until(pool, meta))

    if not is_short:
        has_haze = any(c in WEATHER_CODE_GROUPS['haze'] for c in meta['codes'])
        if has_haze:
            if meta['has_rain'] or meta['has_thunderstorm']:
                lines.extend(pick_templates_until(HAZE_TEMPLATES, meta, max_total_chars=300))
            else:
                lines.append(random.choice(HAZE_TEMPLATES))

        if meta['max_wind'] > 25 and not any('angin' in l.lower() for l in lines):
            lines.append(random.choice(WIND_TEMPLATES).format(**meta))

        if meta['avg_hu'] > 85:
            if not any('lembap' in l.lower() or 'kelembapan' in l.lower() for l in lines):
                if meta['has_rain'] or meta['has_thunderstorm']:
                    lines.append(random.choice(HUMIDITY_HIGH_TEMPLATES).format(**meta))
        elif meta['avg_hu'] < 40:
            if not any('kering' in l.lower() or 'kelembapan' in l.lower() for l in lines):
                lines.append(random.choice(HUMIDITY_LOW_TEMPLATES).format(**meta))

        if len(lines) > 2:
            lines = lines[:2]

    separator = "\n"
    return f"{emoji} <b>{pref}</b> {separator.join(lines)}"


def generate_trend_insight(cuaca_data):
    if len(cuaca_data) < 2:
        return ""

    today_entries = cuaca_data[0]
    tomorrow_entries = cuaca_data[1] if len(cuaca_data) > 1 else []

    if not today_entries or not tomorrow_entries:
        return ""

    today_max = max(float(w.get('t', 0)) for w in today_entries)
    tomorrow_max = max(float(w.get('t', 0)) for w in tomorrow_entries)

    today_min = min(float(w.get('t', 0)) for w in today_entries)
    tomorrow_min = min(float(w.get('t', 0)) for w in tomorrow_entries)

    diff_max = tomorrow_max - today_max
    diff_min = tomorrow_min - today_min

    tomorrow_has_rain = any(60 <= int(w.get('weather', 0)) <= 82 for w in tomorrow_entries)
    today_has_rain = any(60 <= int(w.get('weather', 0)) <= 82 for w in today_entries)

    parts = []
    if abs(diff_max) < 2:
        parts.append(f"Suhu besok relatif stabil (maks {tomorrow_max:.0f}°C, sama seperti hari ini).")
    elif diff_max > 0:
        parts.append(f"Besok lebih hangat {diff_max:.0f}°C (maks {tomorrow_max:.0f}°C). Siapkan diri!")
    else:
        parts.append(f"Besok lebih adem {-diff_max:.0f}°C (maks {tomorrow_max:.0f}°C). Enak buat aktivitas outdoor.")

    if tomorrow_has_rain and not today_has_rain:
        parts.append("Besok potensi hujan — beda dengan hari ini yang cerah.")
    elif not tomorrow_has_rain and today_has_rain:
        parts.append("Kabar baik: besok diprediksi tidak hujan, dibanding hari ini.")

    trend_insight = " ".join(parts)
    return f"📈 <b>TREN BESOK</b>\n{trend_insight}"
