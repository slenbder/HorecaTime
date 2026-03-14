import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

logger = logging.getLogger("app")
error_logger = logging.getLogger("errors")

_USER_COMMANDS = [
    BotCommand(command="shift",        description="Внести смену"),
    BotCommand(command="hours_first",  description="Часы: первая половина месяца"),
    BotCommand(command="hours_second", description="Часы: вторая половина месяца"),
    BotCommand(command="earnings",     description="Мой заработок"),
    BotCommand(command="schedule",     description="График на месяц"),
    BotCommand(command="contact_dev",  description="Написать разработчику"),
]

_ADMIN_EXTRA_COMMANDS = [
    BotCommand(command="rates",        description="Ставки отдела"),
    BotCommand(command="set_rate",     description="Изменить ставку"),
    BotCommand(command="message_dept", description="Сообщение отделу"),
]

_SUPERADMIN_COMMANDS = [
    BotCommand(command="schedule",     description="График на месяц"),
    BotCommand(command="rates_all",    description="Ставки всех отделов"),
    BotCommand(command="set_rate_all", description="Изменить ставку"),
    BotCommand(command="message_all",  description="Сообщение сотрудникам"),
    BotCommand(command="switch_month", description="Переход на новый месяц"),
    BotCommand(command="dismiss",      description="Уволить сотрудника"),
]

_ROLE_COMMANDS: dict[str, list[BotCommand]] = {
    "user":           _USER_COMMANDS,
    "admin_hall":     _USER_COMMANDS + _ADMIN_EXTRA_COMMANDS,
    "admin_bar":      _USER_COMMANDS + _ADMIN_EXTRA_COMMANDS,
    "admin_kitchen":  _USER_COMMANDS + _ADMIN_EXTRA_COMMANDS,
    "superadmin":     _SUPERADMIN_COMMANDS,
    "developer":      _SUPERADMIN_COMMANDS,
}


async def set_commands_for_role(bot: Bot, telegram_id: int, role: str) -> None:
    commands = _ROLE_COMMANDS.get(role)
    if commands is None:
        return

    try:
        await bot.set_my_commands(
            commands=commands,
            scope=BotCommandScopeChat(chat_id=telegram_id),
        )
        logger.info(
            "Commands set for user %s (role=%s): %d commands",
            telegram_id, role, len(commands),
        )
    except Exception:
        error_logger.exception(
            "Failed to set commands for user %s (role=%s)", telegram_id, role
        )
