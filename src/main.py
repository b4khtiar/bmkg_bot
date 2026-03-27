import asyncio
import os
from aiogram import Bot, Dispatcher
from handlers import user, admin
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.bmkg_api import fetch_latest_quake, fetch_weather_data, fetch_nowcast_alerts, parse_nowcast_rss, fetch_alert_detail, parse_cap_detail, parse_weather_daily_brief, parse_weather_data
from database import init_db, get_all_users, get_metadata, update_metadata, check_and_update_alert, cleanup_old_metadata
from utils.constants import REGION_DATA

TZ = os.getenv("TZ", "Asia/Jakarta")
scheduler = AsyncIOScheduler(timezone=TZ)


# Ambil Token dari Environment
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))

async def check_quake_job(bot):
    data = await fetch_latest_quake()
    if not data: return

    last_id = await get_metadata("last_quake_id")
    current_id = data['DateTime']

    if current_id != last_id:
        # Simpan ID baru agar tidak berulang
        await update_metadata("last_quake_id", current_id)
        
        # Broadcast ke semua user
        users = await get_all_users()
        msg = (f"<b>⚠️ ALERT GEMPA</b>\n\n"
               f"🗓️ {data['Tanggal']} {data['Jam']}\n"
               f"Magnitudo: {data['Magnitude']}\n"
               f"Kedalaman: {data['Kedalaman']}\n"
               f"Wilayah: {data['Wilayah']}\n"
               f"Potensi: {data['Potensi']}")
        img_url = f"https://static.bmkg.go.id/{raw_data['Shakemap']}"
        
        for user in users:
            try:
                await bot.send_photo(user['chat_id'], img_url, caption=msg, parse_mode="HTML")
            except: continue

async def daily_weather_job(bot, time_label):
    users = await get_all_users()
    weather_cache = {}

    for user in users:
        adm_code = user['adm_code']
        if not adm_code: continue

        if adm_code not in weather_cache:
            raw_data = await fetch_weather_data(adm_code)
            if raw_data:
                # JIKA PAGI -> Gunakan Briefing Mode
                if time_label == "Pagi":
                    weather_cache[adm_code] = parse_weather_daily_brief(raw_data)
                # JIKA SORE -> Gunakan Detail Mode (Parser lama)
                else:
                    weather_cache[adm_code] = parse_weather_data(raw_data, time_label)
        
        msg = weather_cache.get(adm_code)
        if msg:
            try:
                await bot.send_message(user['chat_id'], msg, parse_mode="HTML")
            except: continue

async def nowcast_alert_job(bot):
    rss_data = await fetch_nowcast_alerts()
    if not rss_data: return

    users = await get_all_users()
    
    # Kumpulkan alert unik per wilayah agar tidak fetch detail berulang kali
    # key: city_name, value: list of detail_objects
    processed_alerts = {}

    for user in users:
        code = user['adm_code'] # Contoh: "34.04"
        # Dapatkan nama provinsi dari kode wilayah
        # format { "provinsi": { "kode": "nama" } }
        province = None
        for prov, kode_map in REGION_DATA.items():
            if code in kode_map:
                province = prov
                break
        
        # 1. Cari link relevan di RSS
        links = parse_nowcast_rss(rss_data, province)
        
        for link in links:
            # 2. Fetch detail jika belum diproses di putaran ini
            if link not in processed_alerts:
                detail_xml = await fetch_alert_detail(link)
                if detail_xml:
                    processed_alerts[link] = parse_cap_detail(detail_xml)
            
            alert = processed_alerts.get(link)
            if alert:
                # 3. Deduplikasi menggunakan identifier unik CAP
                is_new = await check_and_update_alert(f"cap_{alert['id']}", "sent")
                
                if is_new:
                    msg = (f"<b>🚨 PERINGATAN DINI (NOWCASTING)</b>\n\n"
                           f"📢 <b>{alert['headline']}</b>\n\n"
                           f"{alert['description']}\n\n"
                           f"⏳ Berlaku hingga: {alert['expires']}\n\n"
                           f"<i>Sumber: BMKG</i>")
                    
                    try:
                        if alert['image']:
                            await bot.send_photo(user['chat_id'], photo=alert['image'], caption=msg, parse_mode="HTML")
                        else:
                            await bot.send_message(user['chat_id'], msg, parse_mode="HTML")
                    except: continue

async def main():
    # 1. Inisialisasi Database
    await init_db()

    # 2. Inisialisasi Bot & Dispatcher
    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    # 3. Registrasi Router (Handler)
    dp.include_router(admin.router) # Admin dulu agar didahulukan
    dp.include_router(user.router)

    print(f"Bot berjalan dalam mode polling...")

    try:
        # Tambah Jobs
        scheduler.add_job(check_quake_job, "interval", minutes=1, args=[bot])
        scheduler.add_job(daily_weather_job, "cron", hour=6, minute=30, args=[bot, "Pagi"])
        scheduler.add_job(daily_weather_job, "cron", hour=17, minute=0, args=[bot, "Sore"])
        # scheduler.add_job(weather_alert_job, "interval", minutes=20, args=[bot])
        scheduler.add_job(nowcast_alert_job, "interval", minutes=15, args=[bot])
        scheduler.add_job(cleanup_old_metadata, "cron", day_of_week='sun', hour=0)
        
        scheduler.start()
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())