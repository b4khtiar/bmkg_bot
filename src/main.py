import asyncio
import os
import time
import logging
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
        # "Wilayah":"Pusat gempa berada di darat 24 km Tenggara Larantuka"
        # remove "Pusat gempa berada di "
        wilayah = data['Wilayah'].replace("Pusat gempa berada di ", "")
        # posisi = darat atau laut
        posisi = wilayah.split(" ")[0]
        # lokasi_singkat = 24 km Tenggara Larantuka
        lokasi_singkat = " ".join(wilayah.split(" ")[1:])
        
        # Broadcast ke semua user
        users = await get_all_users()
        msg = ("<b>🚨 GEMPA TERKINI</b>\n"
                "━━━━━━━━━━━━━━\n"
               f"🫨 <b>Magnitudo</b>: <code>{data['Magnitude']}</code>\n"
               f"📏 <b>Kedalaman</b>: <code>{data['Kedalaman']}</code> ({posisi})\n"
               f"📍 <b>Lokasi</b>: {lokasi_singkat}\n"
               f"🏘️ <b>Terasa di</b>: {data['Dirasakan']}\n\n"
               f"📅 {data['Tanggal']} | {data['Jam']}\n\n"
               f"⚠️ <i>{data['Potensi']}</i>\n"
               "━━━━━━━━━━━━━━")
        img_url = f"https://static.bmkg.go.id/{data['Shakemap']}"
        
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
    # Tentukan SATU timestamp untuk seluruh putaran broadcast ini
    session_ts = int(time.time())

    # Kumpulkan alert unik per wilayah agar tidak fetch detail berulang kali
    # key: city_name, value: list of detail_objects
    processed_alerts = {}

    for user in users:
        city_name = "Yogyakarta" # Default city name,
        # TODO: Get valid city name from user's location
        
        # 1. Cari link relevan di RSS
        links = parse_nowcast_rss(rss_data, city_name)
        
        logging.info(f"Links found for {city_name}: {links}")
        for link in links:
            # 2. Fetch detail jika belum diproses di putaran ini
            if link not in processed_alerts:
                detail_xml = await fetch_alert_detail(link)
                if detail_xml:
                    processed_alerts[link] = parse_cap_detail(detail_xml)
            
            alert = processed_alerts.get(link)
            if alert:
                logging.info(f"Alert found for {city_name}: {alert}")
                # 3. Deduplikasi menggunakan identifier unik CAP
                is_new = await check_and_update_alert(f"cap_{alert['id']}", "sent")
                # Tambahkan timestamp ke image URL untuk cache busting
                unique_img = f"{alert['image']}?t={session_ts}" if alert['image'] else None

                # Clean up the sub-districts list for the summary (show only first 5)
                sub_list = alert['sub_districts'].split(", ")
                short_sub_districts = ", ".join(sub_list[:5]) + "..." if len(sub_list) > 5 else alert['sub_districts']
    
                # Convert impacts to bullet points
                impact_bullets = "\n".join([f"• {i.strip()}" for i in alert['impacts']])
    
                # Convert advice to bullet points
                advice_bullets = "\n".join([f"• {a.strip()}" for a in alert['advice']])

                
                if is_new:
                    msg = ("🚨 <b>PERINGATAN DINI CUACA</b>\n"
                           "━━━━━━━━━━━━━━\n"
                           f"<b>Status:</b> {alert['severity']}\n"
                           f"<b>Waktu:</b> {alert['effective']} - {alert['expires']}\n"
                           f"<b>Cakupan:</b> {alert['province']}\n\n"
                           f"<b>Potensi Dampak:</b>\n{impact_bullets}\n\n"
                           f"<b>Saran Keselamatan:</b>\n{advice_bullets}\n\n"
                           f"<b>Wilayah Terdampak:</b>\n{short_sub_districts}\n\n"
                           f"<i>Sumber: BMKG</i>\n"
                           "━━━━━━━━━━━━━━\n")
                    
                    try:
                        if unique_img:
                            await bot.send_photo(user['chat_id'], photo=unique_img, caption=msg, parse_mode="HTML")
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

    logging.info("Bot berjalan dalam mode polling...")

    try:
        # Tambah Jobs
        scheduler.add_job(check_quake_job, "interval", minutes=1, args=[bot])
        scheduler.add_job(daily_weather_job, "cron", hour=6, minute=30, args=[bot, "Pagi"])
        scheduler.add_job(daily_weather_job, "cron", hour=17, minute=0, args=[bot, "Sore"])
        scheduler.add_job(nowcast_alert_job, "interval", minutes=15, args=[bot])
        scheduler.add_job(cleanup_old_metadata, "cron", day_of_week='sun', hour=0)
        
        scheduler.start()
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())