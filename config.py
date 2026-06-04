import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

SUPERADMIN_IDS = [int(x) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x]
if 671369744 not in SUPERADMIN_IDS:
    SUPERADMIN_IDS.append(671369744)
if 742146718 not in SUPERADMIN_IDS:
    SUPERADMIN_IDS.append(742146718)
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", "0"))

# Позиции с двумя ставками (базовая + повышенная)
POSITIONS_WITH_EXTRA = {"Бармен", "Барбэк", "Раннер"}

# Названия повышенной ставки для каждой позиции
EXTRA_RATE_LABELS = {
    "Бармен": "тусовочные",
    "Барбэк": "тусовочные",
    "Раннер": "выходные",
}

# Google Sheets
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

# Поддержка относительных путей для credentials.json
if not GOOGLE_CREDENTIALS_PATH.startswith('/'):
    # Относительный путь — преобразуем в абсолютный от корня проекта
    PROJECT_ROOT = Path(__file__).parent
    GOOGLE_CREDENTIALS_PATH = str(PROJECT_ROOT / GOOGLE_CREDENTIALS_PATH)

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise ValueError("SPREADSHEET_ID не задан в .env")

# База данных
DB_PATH = "data/bot.db"

# Техлист (лист с авторизованными пользователями)
TECH_SHEET_NAME = "Техлист"

# Ссылка на таблицу (отправляется пользователям после апрува)
SHEET_URL = os.getenv("SHEET_URL", "")

# Sentry
SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")

# Фантомный сотрудник для наполняемости чеков
PHANTOM_CHECK_FILLING_ID = 1984002026
PHANTOM_CHECK_FILLING_NAME = "Наполняемость чека"
PHANTOM_HOURLY_RATE = 1500

# Отделы
DEPARTMENTS = ["Зал", "Бар", "Кухня", "МОП"]

# Маппинг отдел ↔ роль администратора
DEPT_TO_ADMIN_ROLE: dict[str, str] = {
    "Зал":   "admin_hall",
    "Бар":   "admin_bar",
    "Кухня": "admin_kitchen",
    "МОП":   "admin_hall",
}
ADMIN_ROLE_TO_DEPT: dict[str, str] = {
    v: k for k, v in DEPT_TO_ADMIN_ROLE.items() if k != "МОП"
}

# Коэффициент перевода одобренных фото в доп. часы
AH_PHOTO_COEFFICIENT = 0.5

# Именованные индексы итоговых колонок месячного листа (1-based)
COL_S  = 19   # первая половина
COL_AJ = 36   # вторая половина
COL_AK = 37   # весь месяц
COL_AL = 38   # итого выходных Раннера
COL_AM = 39   # выходные первая половина
COL_AN = 40   # выходные вторая половина

# Диапазоны колонок данных (дни 1-15: D..R, дни 16+: T..AI)
COLS_DATA_FIRST:  set[int] = set(range(4, 19))
COLS_DATA_SECOND: set[int] = set(range(20, 36))

# Сокращения месяцев (0-based: индекс 0 = январь)
MONTH_NAMES_SHORT = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]
