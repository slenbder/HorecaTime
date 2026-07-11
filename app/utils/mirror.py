"""Уведомления о рассинхроне Sheets-зеркала (архитектура "SQLite = source of truth").

Общий модуль для auth.py и userhours.py — без циклических импортов.
"""
import logging

from config import DEVELOPER_ID

logger = logging.getLogger(__name__)


async def notify_mirror_failure(bot, text: str) -> None:
    """
    Уведомляет разработчика, что запись в Sheets-зеркало не прошла.
    SQLite (источник правды) уже записан, операция для пользователя успешна.
    """
    try:
        await bot.send_message(DEVELOPER_ID, f"⚠️ Sheets-зеркало не обновлено: {text}")
    except Exception:
        logger.exception("Не удалось уведомить разработчика о рассинхроне зеркала: %s", text)
