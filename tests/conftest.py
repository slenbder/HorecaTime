"""
Настройка окружения для тестов.
Устанавливает фиктивные env-переменные до импорта модулей,
которые зависят от config.py (BOT_TOKEN, SPREADSHEET_ID).
"""
import os

os.environ.setdefault("BOT_TOKEN", "test_token_placeholder")
os.environ.setdefault("SPREADSHEET_ID", "test_spreadsheet_placeholder")
