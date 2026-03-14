# HorecaTime

Telegram-бот учёта рабочего времени для сотрудников ресторана.
Python-порт системы на базе Google Apps Script.

## Стек
- Python 3.11+, aiogram 3.13.1
- Google Sheets (single source of truth) через gspread
- SQLite — FSM + кеш ролей
- APScheduler (запланирован)

## Роли
- user — внесение смен, просмотр часов
- admin_hall / admin_bar / admin_kitchen — управление своим отделом
- superadmin — полный доступ, увольнение, переключение месяца
- developer — всё + алерты об ошибках

## Запуск
1. Скопируй .env.example в .env и заполни переменные
2. pip install -r requirements.txt
3. python main.py

## Переменные окружения
BOT_TOKEN — токен Telegram бота
GOOGLE_CREDENTIALS_PATH — путь к JSON сервисного аккаунта Google
SPREADSHEET_ID — ID Google таблицы
ADMIN_HALL_IDS — ID администраторов зала (через запятую)
ADMIN_BAR_IDS — ID администраторов бара
ADMIN_KITCHEN_IDS — ID администраторов кухни
SUPERADMIN_IDS — ID суперадминов
DEVELOPER_ID — ID разработчика

## Структура
Подробнее в CLAUDE.md
