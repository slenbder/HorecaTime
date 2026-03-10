import logging
import logging.handlers
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
        LOGS_DIR / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    # Лог ошибок
    errors_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "errors.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    errors_handler.setLevel(logging.ERROR)
    errors_handler.setFormatter(formatter)

    # Лог Google API
    google_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "google_api.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
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
