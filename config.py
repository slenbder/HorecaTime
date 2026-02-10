import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPERADMIN_IDS = [int(x) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x]
ADMIN_HALL_IDS = [int(x) for x in os.getenv("ADMIN_HALL_IDS", "").split(",") if x]
ADMIN_BAR_IDS = [int(x) for x in os.getenv("ADMIN_BAR_IDS", "").split(",") if x]
ADMIN_KITCHEN_IDS = [int(x) for x in os.getenv("ADMIN_KITCHEN_IDS", "").split(",") if x]

# Google Sheets
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# База данных
DB_PATH = "db/bot.db"

# Техлист (лист с авторизованными пользователями)
TECH_SHEET_NAME = "Техлист"
