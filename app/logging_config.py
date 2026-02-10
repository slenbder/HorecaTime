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

    logging.getLogger("google_api").setLevel(logging.INFO)
    logging.getLogger("google_api").handlers.clear()
    logging.getLogger("google_api").addHandler(google_handler)
    logging.getLogger("google_api").addHandler(console_handler)  # И сюда
