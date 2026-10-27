import asyncio
import os
import time
import signal
import logging
import httpx
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat
from handlers import user, admin
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.bmkg_api import (
    fetch_latest_quake, fetch_weather_data, fetch_nowcast_alerts,
    parse_nowcast_rss, fetch_alert_detail, parse_cap_detail,
    parse_weather_daily_brief, parse_weather_current, close_http_client,
    get_http_client,
)
from database import (
    init_db, get_metadata, update_metadata, mark_alert_seen,
    get_last_nowcast, stamp_last_nowcast,
    cleanup_old_alerts, get_users_with_pref, close_db, get_db,
    enqueue_failed_send, retry_pending_sends, delete_pending_send,
    increment_retry_count,
)
from utils import weather_table
from utils.constants import get_province_name
from utils.design import CAPTION_LIMIT
from utils.formatters import format_quake, format_nowcast_alert
from logging_config import setup_logging
from alerts import (
    send_admin_alert, record_bmkg_failure, record_bmkg_success,
    check_broadcast_failure_rate
)
from health_server import start_health_server, stop_health_server, _set_checkers

TZ = os.getenv("TZ", "Asia/Jakarta")
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", 0))

# Jeda minimum antara dua nowcast dengan (provinsi, jenis peringatan) yang
# sama dalam satu chat. BMKG menerbitkan ulang peringatan serupa sebagai CAP
# BARU (file + identifier segar, coba lihat CYG...002 dan CYG...003 yang
# hidup bareng di RSS) tiap siklus nowcast; tanpa jeda, bot mengirimi
# pengguna peringatan "yang sama" berulang 30-120 menit sekali. Peringatan
# yang MENGESKALASI (severity lebih tinggi dari terakhir dikirim) tetap lewat
# meski jeda belum habis.
try:
    NOWCAST_COOLDOWN_MIN = int(os.getenv("NOWCAST_COOLDOWN_MIN", "60"))
except ValueError:
    NOWCAST_COOLDOWN_MIN = 60

# Validate required env vars at startup
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required. Set it in .env")
if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_CHAT_ID is required and must be a valid Telegram chat ID")

setup_logging(level="INFO", bot_mode="OPEN")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TZ)
_shutdown_event = asyncio.Event()
_shutdown_called = False

_SEND_SEM = asyncio.Semaphore(10)

# Max retries for pending sends before giving up
MAX_SEND_RETRIES = 3


async def _send_photo_sem(bot, chat_id, photo, caption):
    """Send a photo, degrading to text-only if the caption cannot fit.

    Telegram caps photo captions at 1024 chars and *rejects* anything longer
    rather than trimming it. Before this guard, an over-length broadcast failed
    here, got queued in ``pending_sends``, failed ``MAX_SEND_RETRIES`` times and
    was dropped — while the admin summary still reported the send as fine,
    because the failure lived in the Telegram layer, not the broadcast layer.
    """
    async with _SEND_SEM:
        if len(caption) > CAPTION_LIMIT:
            logger.warning(
                f"Caption {len(caption)} karakter melebihi batas {CAPTION_LIMIT}, "
                "kirim sebagai teks",
                extra={"chat_id": chat_id},
            )
            return await _send_text_locked(bot, chat_id, caption)
        try:
            await bot.send_photo(chat_id, photo=photo, caption=caption, parse_mode="HTML")
            return True
        except Exception as e:
            logger.warning(f"Gagal kirim foto ke {chat_id}: {e}", extra={"chat_id": chat_id})
            await enqueue_failed_send(chat_id, caption, photo_url=photo)
            return False


async def _send_text_locked(bot, chat_id, msg):
    """Send text assuming ``_SEND_SEM`` is already held."""
    try:
        await bot.send_message(chat_id, msg, parse_mode="HTML")
        return True
    except Exception as e:
        logger.warning(f"Gagal kirim pesan ke {chat_id}: {e}", extra={"chat_id": chat_id})
        await enqueue_failed_send(chat_id, msg)
        return False


async def _send_msg_sem(bot, chat_id, msg):
    async with _SEND_SEM:
        return await _send_text_locked(bot, chat_id, msg)


async def retry_failed_sends_job(bot):
    """Retry queued failed sends. Deletes after max retries."""
    rows = await retry_pending_sends()
    if not rows:
        return

    sent = 0
    failed_permanently = 0
    tasks = []

    for row in rows:
        send_id = row["id"]
        chat_id = row["chat_id"]
        message = row["message"]
        photo_url = row["photo_url"]

        if photo_url:
            tasks.append(_retry_send(bot, send_id, chat_id, photo_url, message))
        else:
            tasks.append(_retry_send_text(bot, send_id, chat_id, message))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        row = rows[i]
        send_id = row["id"]
        if isinstance(result, Exception):
            logger.warning(f"Retry exception for send #{send_id}: {result}")
        elif result is False:
            if row["retry_count"] >= MAX_SEND_RETRIES:
                await delete_pending_send(send_id)
                failed_permanently += 1
            else:
                await increment_retry_count(send_id)

    logger.info(f"Retry job: {sent} sent, {failed_permanently} dropped after max retries")


async def _retry_send(bot, send_id, chat_id, photo_url, caption):
    """Attempt to resend a photo message. Returns True if sent."""
    try:
        async with _SEND_SEM:
            if len(caption) > CAPTION_LIMIT:
                # Rows queued before the length guard existed would otherwise
                # fail identically three times and be dropped.
                logger.warning(
                    f"Caption {len(caption)} karakter melebihi batas pada retry "
                    f"ke {chat_id}, kirim sebagai teks"
                )
                await bot.send_message(chat_id, caption, parse_mode="HTML")
            else:
                await bot.send_photo(chat_id, photo=photo_url, caption=caption, parse_mode="HTML")
        await delete_pending_send(send_id)
        return True
    except Exception as e:
        logger.warning(f"Retry failed for photo to {chat_id}: {e}", extra={"chat_id": chat_id})
        return False


async def _retry_send_text(bot, send_id, chat_id, message):
    """Attempt to resend a text message. Returns True if sent."""
    try:
        async with _SEND_SEM:
            await bot.send_message(chat_id, message, parse_mode="HTML")
        await delete_pending_send(send_id)
        return True
    except Exception as e:
        logger.warning(f"Retry failed for message to {chat_id}: {e}", extra={"chat_id": chat_id})
        return False


async def check_quake_job(bot):
    data = await fetch_latest_quake()
    if not data:
        failed = record_bmkg_failure("quake")
        if failed:
            await send_admin_alert(
                bot,
                "BMKG gempa API gagal fetch berulang (3x). Bot tidak dapat memantau gempa. "
                "Circuit breaker terbuka untuk endpoint ini.",
                severity="CRITICAL"
            )
        return

    record_bmkg_success("quake")

    last_id = await get_metadata("last_quake_id")
    current_id = data['DateTime']

    if current_id != last_id:
        await update_metadata("last_quake_id", current_id)

        users = await get_users_with_pref("notify_quake")
        msg = format_quake(data)
        img_url = f"https://cdn.bmkg.go.id/{data['Shakemap']}"

        results = await asyncio.gather(*[
            _send_photo_sem(bot, u['chat_id'], img_url, msg) for u in users
        ])
        success = sum(1 for r in results if r)
        failed = len(results) - success

        logger.info(f"Broadcast gempa selesai: {success} berhasil, {failed} gagal")
        if failed > 0 and ADMIN_ID:
            if check_broadcast_failure_rate(success, len(results)):
                await send_admin_alert(
                    bot,
                    f"⚠️ Broadcast gempa failure rate tinggi: {failed}/{len(results)} gagal. "
                    f"Bot mungkin diblokir oleh Telegram atau ada masalah koneksi.",
                    severity="WARNING"
                )
            else:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ <b>Ringkasan Broadcast Gempa</b>\n"
                    f"✅ Terkirim: {success}\n"
                    f"❌ Gagal: {failed}",
                    parse_mode="HTML"
                )


async def daily_weather_job(bot, time_label):
    users = await get_users_with_pref("notify_weather")
    weather_cache = {}

    # Fetch weather per unique adm_code, with per-user graceful degradation
    for user_row in users:
        adm_code = user_row['adm_code']
        if not adm_code:
            continue
        if adm_code in weather_cache:
            continue

        raw_data = await fetch_weather_data(adm_code)
        if raw_data:
            if time_label == "Pagi":
                weather_cache[adm_code] = await parse_weather_daily_brief(raw_data)
            else:
                weather_cache[adm_code] = await parse_weather_current(raw_data)

    tasks = []
    for user_row in users:
        adm_code = user_row['adm_code']
        result = weather_cache.get(adm_code)
        if not result:
            # ponytail: silent skip made broadcasts report "0 gagal" while users got nothing.
            # Fallback message keeps counts honest and users informed.
            if not adm_code:
                # Was pointing at /atur_notif, which only toggles notifications —
                # it cannot set a location, so this was a dead end.
                fallback = "⚙️ Lokasi Anda belum diatur, jadi cuaca tidak bisa dikirim.\nAtur lokasi dengan /lokasi."
            else:
                # Do not suggest /cuaca: it hits the same BMKG endpoint that just
                # failed, so the advice cannot help while the outage lasts.
                fallback = (
                    f"⚠️ Data cuaca ({time_label}) sedang tidak tersedia untuk lokasi Anda.\n"
                    "BMKG sedang tidak dapat dihubungi. Data akan dikirim otomatis "
                    "ketika koneksi pulih."
                )
            tasks.append(_send_msg_sem(bot, user_row['chat_id'], fallback))
            continue
        text = result.get("text")
        photo_url = result.get("photo_url")
        if photo_url:
            tasks.append(_send_photo_sem(bot, user_row['chat_id'], photo_url, text))
        else:
            tasks.append(_send_msg_sem(bot, user_row['chat_id'], text))
    results = await asyncio.gather(*tasks) if tasks else []
    success = sum(1 for r in results if r)
    failed = len(results) - success
    # Only users who set a location count as a BMKG data failure. Users without
    # adm_code get the "set location first" notice above, and counting them
    # would page the admin about a config gap, not an outage.
    data_users = [u for u in users if u['adm_code']]
    no_data = sum(1 for u in data_users if not weather_cache.get(u['adm_code']))

    logger.info(f"Broadcast cuaca ({time_label}) selesai: {success} berhasil, {failed} gagal, {no_data} tanpa data")

    # Threshold-gated like check_quake_job/nowcast_alert_job: one cold-cache
    # miss must not page the admin.
    if no_data > 0:
        if record_bmkg_failure("weather"):
            await send_admin_alert(
                bot,
                f"BMKG cuaca gagal berulang (3x). {no_data}/{len(data_users)} pengguna dengan "
                f"lokasi tidak dapat data. Cache mungkin kadaluarsa atau circuit breaker terbuka.",
                severity="WARNING"
            )
    else:
        record_bmkg_success("weather")

    if failed > 0 and ADMIN_ID:
        if check_broadcast_failure_rate(success, len(results)):
            await send_admin_alert(
                bot,
                f"⚠️ Broadcast cuaca ({time_label}) failure rate tinggi: {failed}/{len(results)} gagal.",
                severity="WARNING"
            )
        else:
            await bot.send_message(
                ADMIN_ID,
                f"🌤️ <b>Ringkasan Broadcast Cuaca ({time_label})</b>\n"
                f"✅ Terkirim: {success}\n"
                f"❌ Gagal: {failed}",
                parse_mode="HTML"
            )


async def nowcast_alert_job(bot):
    rss_data = await fetch_nowcast_alerts()
    if not rss_data:
        failed = record_bmkg_failure("nowcast")
        if failed:
            await send_admin_alert(
                bot,
                "BMKG nowcast RSS fetch gagal berulang (3x). "
                "Peringatan dini cuaca tidak dapat diperbarui.",
                severity="WARNING"
            )
        return

    record_bmkg_success("nowcast")

    try:
        users = await get_users_with_pref("notify_nowcast")
        cooldown = NOWCAST_COOLDOWN_MIN * 60

        # --- Fase kumpul: tiap detail CAP di-fetch + di-parse SEKALI per link
        # unik, DI LUAR loop user. Struktur lama menaruh dedup `cap_<id>` di
        # dalam loop user: user pertama urutan query menulis key global dan
        # seluruh user lain di provinsi yang sama tidak pernah menerima
        # peringatan itu. Parser pun menyimpan `sent` (epoch) supaya run
        # dengan beberapa edisi provinsi yang sama sekaligus bisa memilih
        # yang terbaru.
        user_provinces = []
        for user_row in users:
            province_name = get_province_name(user_row['adm_code'])
            if not province_name:
                continue
            user_provinces.append((user_row, province_name))

        unique_links = []
        for _, province_name in user_provinces:
            for link in parse_nowcast_rss(rss_data, province_name):
                if link not in unique_links:
                    unique_links.append(link)

        alerts_by_link = {}
        for link in unique_links:
            detail_xml = await fetch_alert_detail(link)
            if not detail_xml:
                continue
            alert = parse_cap_detail(detail_xml)
            if alert:
                alerts_by_link[link] = alert

        tasks = []
        for user_row, province_name in user_provinces:
            chat_id = user_row['chat_id']
            matching = [
                a for a in alerts_by_link.values()
                if province_name.lower() in a.get('province', '').lower()
            ]
            # Terbaru dulu, sehingga saat RSS menampung >1 edisi provinsi yang
            # sama, yang terbaru yang lolos; edisi lebih tua ditandai
            # sudah-lihat TANPA dikirim (mereka tidak boleh meledak setelah
            # jeda habis, karena masih tertitip di RSS).
            matching.sort(key=lambda a: a.get('sent', 0), reverse=True)

            for alert in matching:
                alert_id = alert.get('id', '')
                if not alert_id:
                    logger.warning(
                        "CAP tanpa identifier dilewati: %s", alert.get('event'),
                        extra={"chat_id": chat_id},
                    )
                    continue

                # Dedup persis per (chat, identifier) — value-nya epoch, bukan
                # placeholder, supaya pembersih `cap_*` bisa menghitung umur key.
                is_new = await mark_alert_seen(f"cap_{chat_id}_{alert_id}")
                if not is_new:
                    continue

                fp = f"{province_name}|{alert.get('event', '')}"
                rank = alert.get('severity_rank', 0)
                now_ts = int(time.time())

                last = await get_last_nowcast(chat_id, fp)
                if last:
                    last_ts, last_rank = last
                    age = now_ts - last_ts
                    if age < cooldown and rank <= last_rank:
                        logger.info(
                            f"Nowcast ulang ditekan ({age // 60}/{NOWCAST_COOLDOWN_MIN} "
                            f"menit, severity tidak eskalasi): {fp}",
                            extra={"chat_id": chat_id},
                        )
                        continue
                    if age < cooldown:
                        logger.info(
                            f"Nowcast eskalasi tetap dikirim (severity {last_rank}→{rank}): {fp}",
                            extra={"chat_id": chat_id},
                        )

                await stamp_last_nowcast(chat_id, fp, now_ts, rank)

                unique_img = f"{alert['image']}?t={now_ts}" if alert.get('image') else None
                msg = format_nowcast_alert(alert)

                if unique_img:
                    tasks.append(_send_photo_sem(bot, chat_id, unique_img, msg))
                else:
                    tasks.append(_send_msg_sem(bot, chat_id, msg))

        results = await asyncio.gather(*tasks) if tasks else []
        success = sum(1 for r in results if r)
        failed = len(results) - success

        logger.info(f"Broadcast nowcast selesai: {success} berhasil, {failed} gagal")
        if failed > 0 and ADMIN_ID:
            if check_broadcast_failure_rate(success, len(results)):
                await send_admin_alert(
                    bot,
                    f"⚠️ Broadcast nowcast failure rate tinggi: {failed}/{len(results)} gagal.",
                    severity="WARNING"
                )
            else:
                await bot.send_message(
                    ADMIN_ID,
                    f"🚨 <b>Ringkasan Broadcast Nowcast</b>\n"
                    f"✅ Terkirim: {success}\n"
                    f"❌ Gagal: {failed}",
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"nowcast_alert_job error: {e}", exc_info=True)
        if ADMIN_ID:
            await send_admin_alert(
                bot,
                f"⚠️ nowcast_alert_job error: {type(e).__name__}: {e}. Beberapa peringatan mungkin tidak terkirim.",
                severity="WARNING"
            )

async def _db_health_check():
    """Async DB health check — used by health server thread via asyncio.run()."""
    try:
        db = await get_db()
        cursor = await db.execute("SELECT 1 FROM config LIMIT 1")
        await cursor.fetchone()
        await cursor.close()
        return True
    except Exception as e:
        logger.warning(f"DB healthcheck failed: {e}")
        return False


#: Probe kesehatan memakai endpoint yang benar-benar dikonsumsi bot (gempa +
#: cuaca), bukan domain root. Dulu checker mem-HEAD ``https://api.bmkg.go.id``
#: yang selalu balik 404 — /ping pun selalu bilang "BMKG tidak dapat dihubungi"
#: padahal /cuaca dan /gempa mengalir normal.
_BMKG_PROBE_URLS = (
    "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json",
    "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=34.01.09.2001",
)
_BMKG_PROBE_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

#: Hasil probe dip-cache dengan TTL: /healthz bisa di-scrape tiap beberapa
#: detik oleh Prometheus, dan tanpa cache itu berarti dua HTTP request ke BMKG
#: per scrape — cara tercepat dikunci firewall.
_BMKG_HEALTH_TTL_SECONDS = 120.0
_bmkg_health_cache = {"ok": False, "at": float("-inf")}


async def _bmkg_health_check():
    """Cek BMKG yang dipakai /healthz, /metrics, /ping, dan panel admin.

    Async (dipanggil via ``get_health_async`` di dalam event loop bot dan via
    ``asyncio.run`` di thread server HTTP) supaya tidak memblokir loop — dulu
    versi sync-nya membekukan loop hingga 5 detik tiap /ping. Ini juga kontrak
    yang dinyatakan ``health_server._set_checkers``: checker terdaftar harus
    awaitable; checker sync tidak di-await berarti hasilnya adalah coroutine
    yang selalu truthy — kegagalan dilaporkan sehat.
    """
    now = time.monotonic()
    if now - _bmkg_health_cache["at"] < _BMKG_HEALTH_TTL_SECONDS:
        return _bmkg_health_cache["ok"]

    ok = True
    try:
        client = await get_http_client()
        for url in _BMKG_PROBE_URLS:
            resp = await client.head(url, timeout=_BMKG_PROBE_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(
                    f"BMKG healthcheck: {url} balik HTTP {resp.status_code}")
                ok = False
                break
    except Exception as e:
        logger.warning(f"BMKG healthcheck gagal: {e}")
        ok = False

    _bmkg_health_cache.update(ok=ok, at=now)
    return ok


async def shutdown():
    global _shutdown_called
    if _shutdown_called:
        return
    _shutdown_called = True

    logger.info("Memulai shutdown...")
    _shutdown_event.set()

    stop_health_server()

    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler dihentikan.")

    await close_db()
    await close_http_client()
    logger.info("Koneksi database dan HTTP ditutup.")


#: Menu perintah yang dilihat pengguna di Telegram.
#:
#: Hanya nama BARU yang dipublikasikan. Nama lama (`/cuaca_hari_ini`,
#: `/atur_notif`) tetap diterima sebagai alias dengan satu pesan pemberitahuan,
#: jadi muscle memory tidak hilang — tapi menu mengajari kosakata yang benar.
#:
#: Tanpa ini, menu perintah Telegram kosong: tidak ada yang(memberi tahu
#: fitur apa saja yang ada.
USER_COMMANDS = [
    ("cuaca", "Cuaca saat ini, opsional: nama lokasi"),
    ("per_jam", "Cuaca per jam hari ini"),
    ("prakiraan", "Prakiraan 3 hari ke depan"),
    ("gempa", "Gempa bumi terkini"),
    ("nowcast", "Peringatan dini cuaca"),
    ("lokasi", "Atur atau ubah lokasi"),
    ("notifikasi", "Atur notifikasi yang diterima"),
    ("bantuan", "Daftar perintah"),
    ("ping", "Cek status bot"),
]

ADMIN_COMMANDS = [
    ("admin", "Panel kontrol admin"),
    ("whitelist", "Kelola whitelist"),
]


async def _publish_commands(bot):
    """Terbitkan menu perintah ke Telegram.

    Kegagalan di sini tidak boleh menghentikan bot: menu perintah hanya
    petunjuk, bukan fungsi. Bot yang jalan tanpa menu lebih baik daripada bot
    yang mati karena API-nya menolak.
    """
    try:
        await bot.set_my_commands(
            [BotCommand(name, description) for name, description in USER_COMMANDS]
        )
        await bot.set_my_commands(
            [BotCommand(name, description) for name, description in ADMIN_COMMANDS],
            scope=BotCommandScopeChat(chat_id=ADMIN_ID),
        )
    except Exception as e:
        logger.warning(f"Gagal menerbitkan menu perintah: {e}")


async def main():
    await init_db()

    # Register health check functions with the threaded health server
    _set_checkers(_db_health_check, _bmkg_health_check)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(admin.router)
    dp.include_router(user.router)

    weather_table.log_problems(logger)
    await _publish_commands(bot)

    scheduler.add_job(check_quake_job, "interval", minutes=2, args=[bot])
    scheduler.add_job(daily_weather_job, "cron", hour=6, minute=30, args=[bot, "Pagi"])
    scheduler.add_job(daily_weather_job, "cron", hour=16, minute=45, args=[bot, "Sore"])
    scheduler.add_job(nowcast_alert_job, "interval", minutes=10, args=[bot])
    scheduler.add_job(cleanup_old_alerts, "cron", day_of_week='sun', hour=0)
    scheduler.add_job(retry_failed_sends_job, "interval", minutes=5, args=[bot])

    scheduler.start()

    # Start health server (Gatus-compatible) in background thread
    start_health_server()

    logger.info("Bot berjalan dalam mode polling...", extra={"bot_mode": "OPEN"})

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass

    try:
        await dp.start_polling(bot)
    finally:
        await shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
