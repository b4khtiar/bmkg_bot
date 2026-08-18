import logging
import logging.config
import json
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """JSON formatter matching the project's existing log style."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "bot_mode"):
            log_entry["bot_mode"] = record.bot_mode
        if hasattr(record, "adm_code"):
            log_entry["adm_code"] = record.adm_code
        if hasattr(record, "chat_id"):
            log_entry["chat_id"] = record.chat_id
        if hasattr(record, "http_status"):
            log_entry["http_status"] = record.http_status
        if hasattr(record, "extra"):
            log_entry.update(record.extra)
        return json.dumps(log_entry, ensure_ascii=False)


class BotModeFilter(logging.Filter):
    """Attach bot_mode to every log record."""

    def __init__(self):
        super().__init__()
        self._bot_mode = "OPEN"

    def set_mode(self, mode):
        self._bot_mode = mode

    def filter(self, record):
        record.bot_mode = self._bot_mode
        return True


_bot_mode_filter = BotModeFilter()


def setup_logging(level="INFO", bot_mode="OPEN"):
    """Configure structured JSON logging. Safe to call multiple times."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    _bot_mode_filter.set_mode(bot_mode)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Clear existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(StructuredFormatter())
    console_handler.addFilter(_bot_mode_filter)
    root.addHandler(console_handler)


def update_bot_mode(mode):
    """Update the bot_mode attached to log records (call after set_bot_mode)."""
    _bot_mode_filter.set_mode(mode)
    logging.getLogger().info("Bot mode updated", extra={"bot_mode": mode})
