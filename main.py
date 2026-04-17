import asyncio
import logging
import os
import socket
from zoneinfo import ZoneInfo

from aiohttp import TCPConnector
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.db.fsm_storage import SQLiteStorage

from config import BOT_TOKEN, DB_PATH
from app.logging_config import setup_logging
from app.db.models import init_database
from app.utils.error_alerts import (
    extract_context,
    is_critical_exception,
    should_send_alert,
    send_critical_alert,
    send_warning_alert,
    CRITICAL_HANDLERS,
)


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
    from app.scheduler.fsm_cleanup import cleanup_expired_fsm_states
    from app.scheduler.healthcheck import healthcheck

    connector = TCPConnector(family=socket.AF_INET)
    session = AiohttpSession(connector=connector)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=SQLiteStorage(db_path=DB_PATH))

    # Подключаем middleware
    dp.message.middleware(RoleMiddleware())
    dp.callback_query.middleware(RoleMiddleware())

    # Регистрируем роутеры
    dp.include_router(auth_router)
    dp.include_router(userhours_router)
    dp.include_router(reports_router)
    dp.include_router(admin_router)
    dp.include_router(superadmin_router)

    @dp.error()
    async def global_error_handler(event: ErrorEvent) -> None:
        """
        Глобальный обработчик необработанных исключений.
        Логирует ошибку + отправляет алерт девелоперу если критично.
        """
        exception = event.exception
        context = extract_context(event)
        handler_name = context['handler']

        # Логируем в errors.log
        logger.error(
            "Необработанное исключение в %s: %s",
            handler_name,
            exception,
            exc_info=True,
        )

        # Определяем severity
        is_critical = (
            handler_name in CRITICAL_HANDLERS
            or is_critical_exception(exception)
        )

        # Проверяем rate limit
        if not should_send_alert(handler_name, exception):
            logger.info(
                "Алерт для %s:%s пропущен (throttle)",
                handler_name,
                type(exception).__name__,
            )
            return

        # Отправляем алерт
        if is_critical:
            await send_critical_alert(bot, exception, context)
        else:
            await send_warning_alert(bot, exception, context)

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
    scheduler.add_job(
        cleanup_expired_fsm_states,
        trigger="interval",
        minutes=5,
        id="fsm_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Планировщик APScheduler запущен (переключение месяца 1-го в 18:00 МСК)")

    # Healthcheck каждые 30 минут
    scheduler.add_job(
        healthcheck,
        trigger="interval",
        minutes=30,
        args=[bot],
        id="healthcheck",
        replace_existing=True,
    )
    logger.info("Healthcheck job зарегистрирован (каждые 30 минут)")

    logger.info("Бот HorecaTime запущен, начинаю поллинг")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Бот HorecaTime остановлен")


if __name__ == "__main__":
    asyncio.run(main())
