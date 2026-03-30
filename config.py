import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

SUPERADMIN_IDS = [int(x) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x]
ADMIN_HALL_IDS = [int(x) for x in os.getenv("ADMIN_HALL_IDS", "").split(",") if x]
ADMIN_BAR_IDS = [int(x) for x in os.getenv("ADMIN_BAR_IDS", "").split(",") if x]
ADMIN_KITCHEN_IDS = [int(x) for x in os.getenv("ADMIN_KITCHEN_IDS", "").split(",") if x]
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", "0"))

# Google Sheets
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise ValueError("SPREADSHEET_ID не задан в .env")

# База данных
DB_PATH = "db/bot.db"

# Техлист (лист с авторизованными пользователями)
TECH_SHEET_NAME = "Техлист"

# Ссылка на таблицу (отправляется пользователям после апрува)
SHEET_URL = os.getenv("SHEET_URL", "")

# ─── Позиции по отделам ───────────────────────────────────────────────────────

HALL_POSITIONS: list = ["Менеджер", "Официант", "Раннер", "Хостесс"]
BAR_POSITIONS:  list = ["Бармен", "Барбэк"]
KITCHEN_POSITIONS: list = [
    "Руководящий состав", "Горячий цех", "Холодный цех",
    "Кондитерский цех", "Заготовочный цех", "Коренной цех",
]
EXTRA_POSITIONS: list = ["Грузчик", "Закупщик"]   # подкатегория «Доп.» (Кухня)
MOP_POSITIONS:   list = ["Клининг", "Котломой"]

# Функциональные группы (множества)
POSITIONS_WITH_EXTRA: set = {"Бармен", "Барбэк", "Раннер"}
SIMPLE_H_POSITIONS: set = set(
    KITCHEN_POSITIONS + EXTRA_POSITIONS + MOP_POSITIONS + ["Хостесс", "Менеджер"]
)

# Словарь отдел → позиции (фактические хранимые имена, без UI-триггеров)
DEPT_POSITIONS: dict = {
    "Зал":   HALL_POSITIONS,
    "Бар":   BAR_POSITIONS,
    "Кухня": KITCHEN_POSITIONS + EXTRA_POSITIONS,
    "МОП":   MOP_POSITIONS,
}

# Для флоу регистрации: включает «Доп.» как триггер под-клавиатуры
VALID_POSITIONS: dict = {
    "Зал":   HALL_POSITIONS,
    "Бар":   BAR_POSITIONS,
    "Кухня": KITCHEN_POSITIONS + ["Доп."],
    "МОП":   MOP_POSITIONS,
}
VALID_DOP_POSITIONS: list = EXTRA_POSITIONS

# Маппинги для Google Sheets (канонические версии)
POSITION_TO_SECTION: dict = {
    "Руководящий состав":  "Руководящий состав",
    "Горячий цех":         "Горячий цех",
    "Холодный цех":        "Холодный цех",
    "Кондитерский цех":    "Кондитерский цех",
    "Заготовочный цех":    "Заготовочный цех",
    "Коренной цех":        "Коренной цех",
    "Грузчик":             "Дополнительные сотрудники",
    "Закупщик":            "Дополнительные сотрудники",
    "Клининг":             "Клининг",
    "Котломой":            "Котломой",
    "Бармен":              "Бармены",
    "Барбэк":              "Барбэки",
    "Официант":            "Официанты",
    "Раннер":              "Раннеры",
    "Хостесс":             "Хостесс",
    "Менеджер":            "Менеджеры",
}

DEPARTMENT_TO_HEADER: dict = {
    "Кухня": "КУХНЯ",
    "Бар":   "БАР",
    "Зал":   "ЗАЛ",
    "МОП":   "Моп",
}
