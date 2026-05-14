import logging
import logging.handlers
import traceback
from pathlib import Path

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


def setup_logging() -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Консольный вывод
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Общий лог
    app_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "app.log", maxBytes=5_000_000, backupCount=7, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    # Лог ошибок
    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log", maxBytes=5_000_000, backupCount=7, encoding="utf-8"
    )
    errors_handler.setLevel(logging.ERROR)
    errors_handler.setFormatter(formatter)

    # Лог Google API
    google_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "google_api.log", maxBytes=5_000_000, backupCount=7, encoding="utf-8"
    )
    google_handler.setLevel(logging.INFO)
    google_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)  # Добавили консоль
    root_logger.addHandler(app_handler)
    root_logger.addHandler(errors_handler)

    google_api_logger = logging.getLogger("google_api")
    google_api_logger.setLevel(logging.INFO)
    google_api_logger.handlers.clear()
    google_api_logger.addHandler(google_handler)
    google_api_logger.addHandler(console_handler)
    google_api_logger.propagate = False  # Не дублировать в root (app.log)

    _init_sentry()
    _init_telegram_handler()


IGNORED_ERRORS = (
    "TelegramBadRequest",
    "TelegramNetworkError",
    "TelegramConnectionError",
)


class TelegramHandler(logging.Handler):
    def __init__(self, bot_token: str, chat_id: int):
        super().__init__()
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type and exc_type.__name__ in IGNORED_ERRORS:
                return
        try:
            import requests
            msg = record.getMessage()
            tb = ""
            if record.exc_info:
                tb = "\n\n" + "".join(traceback.format_exception(*record.exc_info))
            text = f"🚨 HorecaTime ERROR\n\n{msg}{tb}"
            if len(text) > 4000:
                text = text[:4000] + "...[обрезано]"
            requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=5,
            )
        except Exception:
            pass


def _init_telegram_handler() -> None:
    from config import BOT_TOKEN, DEVELOPER_ID
    if not BOT_TOKEN:
        return
    handler = TelegramHandler(BOT_TOKEN, DEVELOPER_ID)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)


def _init_sentry() -> None:
    from config import SENTRY_DSN
    if not SENTRY_DSN:
        return
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.asyncio import AsyncioIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            LoggingIntegration(
                level=logging.ERROR,
                event_level=logging.ERROR,
            ),
            AsyncioIntegration(),
        ],
        traces_sample_rate=0.0,
        ignore_errors=[
            "TelegramBadRequest",
            "TelegramNetworkError",
            "TelegramConnectionError",
        ],
    )
