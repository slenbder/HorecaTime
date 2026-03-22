import asyncio
import logging
import os
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.db.fsm_storage import SQLiteStorage

from config import BOT_TOKEN, DB_PATH
from app.logging_config import setup_logging
from app.db.models import init_database


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Бот HorecaTime запускается...")

    # Создаём папку db/, если её нет
    os.makedirs("db", exist_ok=True)

    # Инициализируем базу данных ПЕРЕД импортом хендлеров
    try:
        init_database()
    except Exception as e:
        logger.critical("Не удалось инициализировать базу данных: %s", e)
        raise

    # Импортируем роутеры и middleware ПОСЛЕ инициализации БД
    from app.bot.handlers.auth import auth_router
    from app.bot.handlers.userhours import userhours_router
    from app.bot.handlers.userreports import reports_router
    from app.bot.handlers.admin import admin_router
    from app.bot.handlers.superadmin import superadmin_router
    from app.bot.middlewares.roles import RoleMiddleware
    from app.services.google_sheets import GoogleSheetsClient
    from app.scheduler.monthly_switch import notify_upcoming_switch, switch_month

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=SQLiteStorage(db_path="db/bot.db"))

    # Подключаем middleware
    dp.message.middleware(RoleMiddleware())
    dp.callback_query.middleware(RoleMiddleware())

    # Регистрируем роутеры
    dp.include_router(auth_router)
    dp.include_router(userhours_router)
    dp.include_router(reports_router)
    dp.include_router(admin_router)
    dp.include_router(superadmin_router)

    # Планировщик месячного переключения
    sheets_client = GoogleSheetsClient()
    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Moscow"))

    # Уведомление за 6 часов — каждое 1-е число в 12:00 МСК
    scheduler.add_job(
        notify_upcoming_switch,
        CronTrigger(day=1, hour=12, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        args=[bot, DB_PATH],
    )
    # Переключение — каждое 1-е число в 18:00 МСК
    scheduler.add_job(
        switch_month,
        CronTrigger(day=1, hour=18, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        args=[bot, sheets_client, DB_PATH],
    )
    scheduler.start()
    logger.info("Планировщик APScheduler запущен (переключение месяца 1-го в 18:00 МСК)")

    logger.info("Бот HorecaTime запущен, начинаю поллинг")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Бот HorecaTime остановлен")


if __name__ == "__main__":
    asyncio.run(main())
