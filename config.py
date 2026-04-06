import os
from pathlib import Path
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

# Поддержка относительных путей для credentials.json
if not GOOGLE_CREDENTIALS_PATH.startswith('/'):
    # Относительный путь — преобразуем в абсолютный от корня проекта
    PROJECT_ROOT = Path(__file__).parent
    GOOGLE_CREDENTIALS_PATH = str(PROJECT_ROOT / GOOGLE_CREDENTIALS_PATH)

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise ValueError("SPREADSHEET_ID не задан в .env")

# База данных
DB_PATH = "db/bot.db"

# Техлист (лист с авторизованными пользователями)
TECH_SHEET_NAME = "Техлист"

# Ссылка на таблицу (отправляется пользователям после апрува)
SHEET_URL = os.getenv("SHEET_URL", "")
