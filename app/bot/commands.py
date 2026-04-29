import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat

logger = logging.getLogger("app")
error_logger = logging.getLogger("errors")

_USER_COMMANDS = [
    BotCommand(command="shift",        description="Внести смену"),
    BotCommand(command="hours_first",  description="Часы и заработок: 1–15"),
    BotCommand(command="hours_second", description="Часы и заработок: 16–конец + итог"),
    BotCommand(command="hours_last",   description="Часы и заработок за прошлый месяц"),
    BotCommand(command="schedule",     description="График на месяц"),
    BotCommand(command="sheet",        description="Ссылка на график"),
    BotCommand(command="contact_dev",  description="Написать разработчику"),
]

_ADMIN_COMMANDS = [
    BotCommand(command="shift",        description="Внести смену"),
    BotCommand(command="set_rate",     description="Изменить ставку"),
    BotCommand(command="message_dept", description="Сообщение сотрудникам отдела"),
    BotCommand(command="rates",        description="Ставки отдела"),
    BotCommand(command="hours_first",  description="Часы и заработок: 1–15"),
    BotCommand(command="hours_second", description="Часы и заработок: 16–конец + итог"),
    BotCommand(command="hours_last",   description="Часы и заработок за прошлый месяц"),
    BotCommand(command="schedule",     description="График на месяц"),
    BotCommand(command="sheet",        description="Ссылка на график"),
    BotCommand(command="contact_dev",  description="Написать разработчику"),
]

_SUPERADMIN_COMMANDS = [
    BotCommand(command="set_rate",     description="Изменить ставку"),
    BotCommand(command="message_dept", description="Сообщение отделу"),
    BotCommand(command="message_all",  description="Сообщение всем сотрудникам"),
    BotCommand(command="promote",      description="Повысить сотрудника до администратора"),
    BotCommand(command="demote",       description="Понизить администратора до сотрудника"),
    BotCommand(command="dismiss",      description="Уволить сотрудника"),
    BotCommand(command="rates_all",    description="Ставки всех отделов"),
    BotCommand(command="schedule",     description="График на месяц"),
    BotCommand(command="switch_month", description="Переход на новый месяц"),
    BotCommand(command="sheet",        description="Ссылка на график"),
    BotCommand(command="contact_dev",  description="Написать разработчику"),
]

_ROLE_COMMANDS: dict[str, list[BotCommand]] = {
    "user":           _USER_COMMANDS,
    "admin_hall":     _ADMIN_COMMANDS,
    "admin_bar":      _ADMIN_COMMANDS,
    "admin_kitchen":  _ADMIN_COMMANDS,
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
