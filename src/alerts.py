import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

ADMIN_ALERT_COOLDOWN = 300  # 5 min between identical alerts

_thresholds = {
    "bmkg_failures": int(__import__("os").getenv("BMKG_FAILURES_ALERT_THRESHOLD", "3")),
    "broadcast_failure_rate": float(__import__("os").getenv("BROADCAST_FAILURE_RATE", "0.2")),
    "db_timeout_seconds": int(__import__("os").getenv("DB_TIMEOUT_ALERT_SECONDS", "5")),
}

# Track consecutive BMKG failures per endpoint
_bmkg_fail_counts = defaultdict(int)
_last_alert_time = defaultdict(float)


async def send_admin_alert(bot, message: str, severity: str = "WARNING"):
    """Send an alert to the admin chat. Suppressed if sent within cooldown."""
    import os

    admin_id_str = os.getenv("ADMIN_CHAT_ID", "0")
    if not admin_id_str or admin_id_str == "0":
        logger.warning(f"Admin alert (no ADMIN_CHAT_ID): [{severity}] {message}")
        return

    admin_id = int(admin_id_str)
    alert_key = message[:80]  # Group by similar messages
    now = time.time()

    if now - _last_alert_time[alert_key] < ADMIN_ALERT_COOLDOWN:
        logger.info(f"Alert suppressed (cooldown): {message[:60]}")
        return

    _last_alert_time[alert_key] = now

    formatted = (
        f"⚠️ <b>[BOT ALERT] {severity}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{message}\n"
        f"━━━━━━━━━━━━━━\n"
        f"<i>{time.strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )

    try:
        await bot.send_message(admin_id, formatted, parse_mode="HTML")
        logger.info(f"Admin alert sent: {message[:60]}")
    except Exception as e:
        logger.error(f"Failed to send admin alert: {e}")


def record_bmkg_failure(endpoint: str) -> bool:
    """Increment failure counter. Return True if threshold exceeded (and DO NOT reset)."""
    _bmkg_fail_counts[endpoint] += 1
    return _bmkg_fail_counts[endpoint] >= _thresholds["bmkg_failures"]


def record_bmkg_success(endpoint: str):
    """Reset failure counter on success."""
    _bmkg_fail_counts[endpoint] = 0


def check_broadcast_failure_rate(success: int, total: int) -> bool:
    """Return True if failure rate exceeds threshold."""
    if total == 0:
        return False
    failure_rate = (total - success) / total
    return failure_rate > _thresholds["broadcast_failure_rate"]
