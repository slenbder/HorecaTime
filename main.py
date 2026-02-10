import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from app.logging_config import setup_logging
from app.db.models import init_database


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Бот HorecaTime запускается...")

    # Создаём папку db/, если её нет
    os.makedirs("db", exist_ok=True)
    
    # Инициализируем базу данных ПЕРЕД импортом хендлеров
    init_database()

    # Импортируем роутеры и middleware ПОСЛЕ инициализации БД
    from app.bot.handlers.auth import auth_router
    from app.bot.middlewares.roles import RoleMiddleware

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Подключаем middleware
    dp.message.middleware(RoleMiddleware())
    dp.callback_query.middleware(RoleMiddleware())

    # Регистрируем роутеры
    dp.include_router(auth_router)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
