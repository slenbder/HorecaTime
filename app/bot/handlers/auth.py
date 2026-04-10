import html
import logging
import re

from app.services.roles_cache import RolesCacheService
from aiogram import Router, F
import aiosqlite

from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommandScopeChat, ReplyKeyboardRemove, LinkPreviewOptions,
)

from app.bot.fsm.auth_states import AuthStates
from app.bot.keyboards.common import (
    department_keyboard,
    hall_positions_keyboard,
    bar_positions_keyboard,
    kitchen_positions_keyboard,
    kitchen_dop_keyboard,
    mop_positions_keyboard,
    main_menu_keyboard,
)

from app.bot.commands import set_commands_for_role
from app.db.models import get_user, delete_user, get_users_by_role, get_rate, set_user_rate
from app.services.google_sheets import GoogleSheetsClient
from app.utils.text_utils import make_mention, mask_email
from config import (
    SUPERADMIN_IDS,
    ADMIN_HALL_IDS,
    ADMIN_BAR_IDS,
    ADMIN_KITCHEN_IDS,
    DEVELOPER_ID,
    DB_PATH,
    SHEET_URL,
)

auth_router = Router()
logger = logging.getLogger(__name__)


VALID_POSITIONS: dict[str, list[str]] = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Руководящий состав", "Горячий цех", "Холодный цех",
               "Кондитерский цех", "Заготовочный цех", "Коренной цех", "Доп."],
    "МОП":   ["Клининг", "Котломой"],
}

VALID_DOP_POSITIONS = ["Грузчик", "Закупщик"]

def _is_valid_gmail(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9._%+-]+@gmail\.com$'
    return bool(re.match(pattern, email.strip().lower()))


# Временное хранилище данных заявки между регистрацией и апрувом (callback_key → данные)
_pending_admins: dict[str, dict] = {}

POSITION_TO_SECTION: dict[str, str] = {
    "Руководящий состав": "Руководящий состав",
    "Горячий цех": "Горячий цех",
    "Холодный цех": "Холодный цех",
    "Кондитерский цех": "Кондитерский цех",
    "Заготовочный цех": "Заготовочный цех",
    "Коренной цех": "Коренной цех",
    "Грузчик": "Дополнительные сотрудники",
    "Закупщик": "Дополнительные сотрудники",
    "Клининг": "Клининг",
    "Котломой": "Котломой",
    "Бармен": "Бармены",
    "Барбэк": "Барбэки",
    "Менеджер": "Менеджеры",
    "Официант": "Официанты",
    "Раннер": "Раннеры",
    "Хостесс": "Хостесс",
    "Администратор зала": "Зал",
    "Администратор бара": "Бар",
    "Администратор кухни": "Кухня",
}

POSITION_KEYBOARDS = {
    "Зал":   hall_positions_keyboard,
    "Бар":   bar_positions_keyboard,
    "Кухня": kitchen_positions_keyboard,
    "МОП":   mop_positions_keyboard,
}

logger.debug("Загружены SUPERADMIN_IDS: %s", SUPERADMIN_IDS)
logger.debug("Загружены ADMIN_HALL_IDS: %s", ADMIN_HALL_IDS)
logger.debug("Загружены ADMIN_BAR_IDS: %s", ADMIN_BAR_IDS)
logger.debug("Загружены ADMIN_KITCHEN_IDS: %s", ADMIN_KITCHEN_IDS)

# Инициализируем клиента Google Sheets
try:
    sheets_client = GoogleSheetsClient()
    logger.info("GoogleSheetsClient успешно инициализирован")
except Exception as e:
    logger.exception(f"Ошибка при инициализации GoogleSheetsClient: {e}")
    sheets_client = None


async def _clear_commands(bot, tg_id: int) -> None:
    """Сбрасывает список команд для пользователя (пустой список)."""
    try:
        await bot.set_my_commands(commands=[], scope=BotCommandScopeChat(chat_id=tg_id))
    except Exception:
        logging.getLogger("errors").exception(
            "Не удалось сбросить команды для пользователя %s", tg_id
        )


@auth_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info(f"Получена команда /start от пользователя {tg_id}")

    # Superadmin / Developer: прямо в главное меню, без проверки таблицы
    if tg_id == DEVELOPER_ID:
        privileged_role = "developer"
    elif tg_id in SUPERADMIN_IDS:
        privileged_role = "superadmin"
    else:
        privileged_role = None

    if privileged_role:
        await state.clear()
        await set_commands_for_role(message.bot, tg_id, privileged_role)
        await message.answer("👋 Добро пожаловать!", reply_markup=main_menu_keyboard(privileged_role))
        logger.info("cmd_start: %s вошёл как %s", tg_id, privileged_role)
        return

    if sheets_client is None:
        await message.answer("Ошибка подключения к таблице. Обратись к администратору.")
        logger.error("sheets_client не инициализирован")
        return

    # 0. Resync: если пользователь есть в SQLite, но удалён из Техлиста — сбрасываем
    cached_user = get_user(tg_id)
    if cached_user:
        try:
            exists_in_techlist = sheets_client.user_exists_in_techlist(tg_id)
        except Exception:
            logger.exception(
                "Ошибка при проверке наличия %s в Техлисте при /start, продолжаем без сброса",
                tg_id,
            )
            exists_in_techlist = True  # fail-safe: не сбрасываем при ошибке

        if not exists_in_techlist:
            logger.info("User %s not found in Техлист, resetting", tg_id)
            delete_user(tg_id)
            await state.clear()
            await _clear_commands(message.bot, tg_id)
            await message.answer(
                "Привет! Давай настроим твою авторизацию.\n\nВыбери свой отдел:",
                reply_markup=department_keyboard(),
            )
            await state.set_state(AuthStates.choosing_department)
            return

    # 1. Проверяем, есть ли пользователь и одобрен ли он
    try:
        logger.info(f"Проверка авторизации пользователя {tg_id}")
        is_approved = sheets_client.is_user_fully_authorized(tg_id)
        logger.info(f"Результат проверки авторизации: {is_approved}")

        if is_approved:
            cached = RolesCacheService.get_user_role(tg_id)
            role = cached["role"] if cached and cached.get("role") and cached["role"] != "guest" else "user"
            await set_commands_for_role(message.bot, tg_id, role)
            await message.answer(
                "Ты уже авторизован в системе ✅\n"
                "Используй меню команд для внесения смен и просмотра отчётов."
            )
            await state.clear()
            return
    except Exception as e:
        logger.exception(f"Ошибка при проверке авторизации пользователя {tg_id}: {e}")
        await message.answer(
            "Произошла ошибка при проверке авторизации. Попробуй ещё раз позже."
        )
        return

    # 2. Если не одобрен — запускаем сценарий регистрации
    logger.info(f"Запуск сценария регистрации для пользователя {tg_id}")
    await _clear_commands(message.bot, tg_id)
    await message.answer(
        "Привет! Давай настроим твою авторизацию.\n\nВыбери свой отдел:",
        reply_markup=department_keyboard(),
    )
    await state.set_state(AuthStates.choosing_department)


@auth_router.message(AuthStates.choosing_department, F.text.in_(["Зал", "Бар", "Кухня", "МОП"]))
async def process_department(message: Message, state: FSMContext):
    department = message.text
    logger.info(f"Пользователь {message.from_user.id} выбрал отдел: {department}")
    await state.update_data(department=department)

    if department == "Зал":
        await message.answer(
            "Выбери свою позицию:",
            reply_markup=hall_positions_keyboard(),
        )
    elif department == "Бар":
        await message.answer(
            "Выбери свою позицию:",
            reply_markup=bar_positions_keyboard(),
        )
    elif department == "МОП":
        await message.answer(
            "Выбери свою позицию:",
            reply_markup=mop_positions_keyboard(),
        )
    else:  # Кухня
        await message.answer(
            "Выбери свою позицию:",
            reply_markup=kitchen_positions_keyboard(),
        )

    await state.set_state(AuthStates.choosing_position)


@auth_router.message(AuthStates.choosing_department)
async def process_department_invalid(message: Message):
    logger.warning(f"Пользователь {message.from_user.id} ввёл некорректный отдел: {message.text}")
    await message.answer(
        "Пожалуйста, выбери отдел, используя кнопки ниже.",
        reply_markup=department_keyboard(),
    )


@auth_router.message(AuthStates.choosing_position)
async def process_position(message: Message, state: FSMContext):
    position = message.text
    data = await state.get_data()
    department = data.get("department", "")

    # ↓ ДОБАВЛЕНО: валидация позиции
    allowed = VALID_POSITIONS.get(department, [])
    if position not in allowed:
        logger.warning(
            f"Пользователь {message.from_user.id} ввёл недопустимую позицию: "
            f"'{position}' для отдела '{department}'"
        )
        kb_func = POSITION_KEYBOARDS.get(department, department_keyboard)
        await message.answer(
            "Пожалуйста, выбери позицию из предложенных кнопок:",
            reply_markup=kb_func(),
        )
        return
    # ↑ конец валидации

    logger.info(f"Пользователь {message.from_user.id} выбрал позицию: {position}")

    if position == "Руководящий состав":
        await state.update_data(position="Руководящий состав")
        await message.answer(
            "Введите вашу должность (например: Шеф, Су-шеф ЗЦ, Шеф КЦ):",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(AuthStates.waiting_kitchen_title)
        return

    if position == "Доп.":
        await message.answer(
            "Выбери конкретную должность:",
            reply_markup=kitchen_dop_keyboard(),
        )
        await state.set_state(AuthStates.waiting_dop_position)
        return

    if department == "Кухня":
        await state.update_data(position=position, custom_position="Повар")
    else:
        await state.update_data(position=position)

    await message.answer("Отправь, пожалуйста, своё имя и фамилию (как в таблице):")
    await state.set_state(AuthStates.entering_fio)


@auth_router.message(AuthStates.waiting_kitchen_title)
async def process_custom_position_input(message: Message, state: FSMContext):
    custom_position = (message.text or "").strip()
    if len(custom_position) < 2 or len(custom_position) > 50:
        logger.warning(
            "Пользователь %s ввёл некорректную должность (длина %d): '%s'",
            message.from_user.id, len(custom_position), custom_position[:50],
        )
        await message.answer("Название должности должно быть от 2 до 50 символов. Введите заново:")
        return
    logger.info(
        "Пользователь %s ввёл должность для Руководящий состав: '%s'",
        message.from_user.id, custom_position,
    )
    await state.update_data(custom_position=custom_position)
    await message.answer("Отправь, пожалуйста, своё имя и фамилию (как в таблице):")
    await state.set_state(AuthStates.entering_fio)


@auth_router.message(AuthStates.waiting_dop_position)
async def process_dop_position(message: Message, state: FSMContext):
    position = (message.text or "").strip()
    if position not in VALID_DOP_POSITIONS:
        logger.warning(
            "Пользователь %s выбрал недопустимую доп. позицию: '%s'",
            message.from_user.id, position,
        )
        await message.answer(
            "Пожалуйста, выбери позицию из предложенных кнопок:",
            reply_markup=kitchen_dop_keyboard(),
        )
        return
    logger.info("Пользователь %s выбрал доп. позицию: %s", message.from_user.id, position)
    await state.update_data(position=position, custom_position="Повар")
    await message.answer("Отправь, пожалуйста, своё имя и фамилию (как в таблице):")
    await state.set_state(AuthStates.entering_fio)


@auth_router.message(AuthStates.entering_fio)
async def process_fio(message: Message, state: FSMContext):
    fio = message.text.strip()

    if not fio or len(fio) < 2 or len(fio) > 100:
        logger.warning(
            "Пользователь %s ввёл некорректное ФИО (длина %s): '%s'",
            message.from_user.id, len(fio), fio[:50]
        )
        await message.answer("Пожалуйста, введи имя и фамилию корректно (от 2 до 100 символов).")
        return

    data = await state.get_data()
    department = data.get("department")
    position = data.get("position")
    custom_position = data.get("custom_position")

    tg_id = message.from_user.id
    nickname = message.from_user.username or ""
    tg_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()

    logger.info(
        "Пользователь %s ввёл ФИО: %s, отдел: %s",
        tg_id, fio, department,
    )

    if sheets_client is None:
        await message.answer("Ошибка подключения к таблице. Обратись к администратору.")
        logger.error("sheets_client не инициализирован при записи заявки")
        await state.clear()
        return

    # 1. Записываем/обновляем заявку в Техлисте
    try:
        logger.info(f"Запись заявки в Техлист для пользователя {tg_id}")
        row_index = sheets_client.add_or_update_pending_user(
            telegram_id=tg_id,
            nickname=nickname,
            fio_from_user=fio,
            department=department,
            position=position,
            custom_position=custom_position if custom_position else "",
        )

        logger.info(f"Заявка успешно записана в строку {row_index}")
    except Exception as e:
        logger.exception(f"Ошибка при записи заявки в Техлист для пользователя {tg_id}: {e}")
        await message.answer(
            "Не удалось сохранить заявку в таблицу. Попробуй позже или напиши администратору."
        )
        await state.clear()
        return

    # Вычисляем отображаемые позицию и должность
    DOP_POSITIONS = ["Грузчик", "Закупщик"]
    if position in DOP_POSITIONS:
        position_display = "Дополнительные сотрудники"
        display_title = position
    elif position == "Руководящий состав" and custom_position:
        position_display = "Руководящий состав"
        display_title = custom_position
    elif department == "Кухня":
        position_display = position
        display_title = "Повар"
    elif department == "МОП":
        position_display = position
        display_title = position
    else:
        position_display = position
        display_title = position

    mention = f'<a href="https://t.me/{nickname}">@{nickname}</a>' if nickname else "не указан"

    # 2. Формируем текст заявки с inline-кнопками
    text = (
        "📝 <b>Новая заявка на доступ к боту:</b>\n\n"
        f"👤 <b>ФИО:</b> {html.escape(fio)}\n"
        f"🏢 <b>Отдел:</b> {department}\n"
        f"💼 <b>Позиция:</b> {position_display}\n"
        f"🔧 <b>Должность:</b> {html.escape(display_title)}\n"
        f"🆔 Telegram ID: <code>{tg_id}</code>\n"
        f"📱 Ник: {mention}\n"
        f"📋 Строка в Техлисте: {row_index}\n\n"
        "❓ <b>Добавить пользователя в график?</b>"
    )

    # Inline-кнопки для одобрения/отклонения (передаём только ID и строку)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_{tg_id}_{row_index}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_{tg_id}_{row_index}"
            ),
        ]
    ])


    # 3. Определяем, кому отправлять уведомление
    recipients = []

    # Админы подразделений
    if department == "Зал":
        recipients.extend(ADMIN_HALL_IDS)
    elif department == "Бар":
        recipients.extend(ADMIN_BAR_IDS)
    elif department == "Кухня":
        recipients.extend(ADMIN_KITCHEN_IDS)
    elif department == "МОП":
        recipients.extend(ADMIN_HALL_IDS)

    # Суперадмины получают все заявки
    recipients.extend(SUPERADMIN_IDS)

    # Убираем дубли
    recipients = list(set(recipients))

    # 4. Отправляем уведомления
    if recipients:
        logger.info(f"Отправка заявки админам: {recipients}")
        for admin_id in recipients:
            try:
                await message.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
                logger.info(f"Заявка отправлена админу {admin_id}")
            except Exception as e:
                logger.exception(f"Не удалось отправить заявку админу {admin_id}: {e}")
    else:
        logger.warning("Нет ID админов для отправки заявки")

    # 5. Отвечаем пользователю
    await message.answer(
        "Спасибо! Твои данные сохранены:\n\n"
        f"Отдел: {department}\n"
        f"Позиция: {position_display}\n"
        f"Должность: {display_title}\n"
        f"ФИО: {fio}\n\n"
        "Заявка на доступ отправлена администратору.\n"
        "После одобрения ты сможешь вносить рабочие часы и смотреть отчёты."
    )
    logger.info(f"Регистрация пользователя {tg_id} завершена успешно")
    if custom_position:
        callback_key = f"{tg_id}_{row_index}"
        _pending_admins[callback_key] = {
            'tg_id': tg_id,
            'row_index': row_index,
            'full_name': fio,
            'custom_position': custom_position,
            'position': position,
        }
    await state.clear()


# --- Обработчики inline-кнопок ---


@auth_router.callback_query(F.data.startswith("approve_ah:"))
async def approve_ah_callback(callback: CallbackQuery) -> None:
    """Одобрение доп. часов официанта (AH) администратором зала.

    Формат callback_data: approve_ah:{telegram_id}:{date_str}:{h}:{N}:{value}
    Пример:               approve_ah:6073294261:03.03.26:10.0:3:2
    """
    # Защита от двойного нажатия: если уже одобрено — игнорируем
    if "✅ Одобрено" in (callback.message.text or ""):
        await callback.answer("Уже обработано другим администратором.")
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 6:
        logger.error(
            "approve_ah_callback: неверное число частей (%d) в callback_data: %s",
            len(parts), callback.data,
        )
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    try:
        telegram_id = int(parts[1])
        date_str = parts[2]       # DD.MM.YY
        h = float(parts[3])
        N = int(parts[4])         # всего фото
        value = int(parts[5])     # одобрено фото
    except (ValueError, IndexError):
        logger.error(
            "approve_ah_callback: не удалось распарсить части callback_data: %s", callback.data,
        )
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    ah = value * 0.5

    # Парсим дату из "DD.MM.YY"
    try:
        day_s, month_s, year_s = date_str.split(".")
        day, month, year = int(day_s), int(month_s), 2000 + int(year_s)
    except (ValueError, AttributeError):
        logger.error(
            "approve_ah_callback: не удалось распарсить дату '%s' из callback_data: %s",
            date_str, callback.data,
        )
        await callback.answer("❌ Некорректный формат даты.", show_alert=True)
        return

    if sheets_client is None:
        await callback.answer("❌ Ошибка подключения к таблице.", show_alert=True)
        return

    try:
        sheets_client.write_shift(telegram_id, day, month, year, h, ah)
    except Exception:
        logging.getLogger("errors").exception(
            "approve_ah_callback: ошибка записи для user=%s date=%s", telegram_id, date_str,
        )
        await callback.answer("❌ Ошибка записи.", show_alert=True)
        return

    logger.info(
        "approve_ah_callback: user=%s date=%s H=%.1f AH=%.1f (%d фото из %d), admin=%s",
        telegram_id, date_str, h, ah, value, N, callback.from_user.id,
    )

    def _fmt(val: float) -> str:
        return str(int(val)) if val == int(val) else f"{val:.1f}"

    ah_str = _fmt(ah)
    h_str = _fmt(h)
    original_text = callback.message.text or ""
    new_text = original_text + f"\n✅ Одобрено {value} фото из {N} → Доп. часы = {ah_str} ч"
    try:
        await callback.message.edit_text(new_text, parse_mode="HTML", reply_markup=None, link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:
        logging.getLogger("errors").error(
            "approve_ah_callback: не удалось отредактировать сообщение: %s", e,
        )

    await callback.answer()

    if value == 0:
        waiter_text = (
            f"📋 Смена {date_str} обработана\n"
            f"Часы смены = {h_str} ч | Доп. часов не засчитано"
        )
    else:
        waiter_text = (
            f"📋 Смена {date_str} обработана\n"
            f"Часы смены = {h_str} ч | Доп. часы = {ah_str} ч ({value} фото из {N})"
        )
    try:
        await callback.bot.send_message(chat_id=telegram_id, text=waiter_text)
    except Exception as e:
        logging.getLogger("errors").error(
            "approve_ah: смена записана но уведомление официанту %s не отправлено: %s",
            telegram_id, e,
        )


@auth_router.callback_query(F.data.startswith("approve_"))
async def process_approve(callback: CallbackQuery, state: FSMContext):
    """Обработка нажатия кнопки 'Одобрить'"""
    try:
        original_text = callback.message.text or ""
        if "✅" in original_text or "❌" in original_text:
            await callback.answer("Уже обработано другим администратором.")
            return

        # Парсим callback_data: approve_TELEGRAM_ID_ROW_INDEX
        parts = callback.data.split("_")
        if len(parts) < 3:
            logger.error("Некорректный формат callback_data при одобрении: %s", callback.data)
            await callback.answer("Некорректный формат данных", show_alert=True)
            return
        try:
            user_tg_id = int(parts[1])
            row_index = int(parts[2])
        except ValueError:
            logger.error("Не удалось распарсить ID из callback_data: %s", callback.data)
            await callback.answer("Некорректные данные в запросе", show_alert=True)
            return

        if sheets_client is None:
            await callback.answer("Ошибка подключения к таблице", show_alert=True)
            return

        # Получаем данные пользователя из Техлиста
        user_info = sheets_client.get_user_from_techlist(user_tg_id)
        if not user_info:
            await callback.answer("Пользователь не найден в Техлисте", show_alert=True)
            return

        fio = user_info.get("fio_from_user", "Неизвестно")
        department = user_info.get("department", "")

        # Читаем данные из Техлиста
        position = user_info.get("position", "")         # колонка E — всегда базовая
        custom_position = user_info.get("custom_position", "")  # колонка H

        _nickname = (user_info.get("nickname") or "").lstrip("@") or None
        mention = make_mention(_nickname, fio)

        # Одобряем пользователя в таблице
        sheets_client.mark_user_approved(row_index)
        logger.info(
            f"Админ {callback.from_user.id} одобрил пользователя {user_tg_id} (строка {row_index})"
        )

        # Добавление в месячный лист
        try:
            sheets_client.ensure_user_in_current_month_hours(
                user_tg_id,
                custom_position=custom_position if custom_position else None
            )
        except Exception:
            logger.exception(f"approve: ошибка добавления в график для {user_tg_id}")
            await callback.message.edit_text(
                f"❌ Ошибка при добавлении {fio} в график."
            )
            return

        logger.info(f"Синхронизация в график завершена для {user_tg_id}")

        # Копирование ставки
        default_rate = await get_rate(DB_PATH, position)
        if default_rate:
            await set_user_rate(
                DB_PATH, user_tg_id,
                base_rate=default_rate["base_rate"],
                extra_rate=default_rate.get("extra_rate")
            )
            logger.info(f"Установлена ставка для {fio}: {default_rate['base_rate']}/{default_rate.get('extra_rate')} р/ч")

        # Обновление кеша
        RolesCacheService.update_user_role(
            telegram_id=user_tg_id,
            full_name=fio,
            role="user",
            department=department,
            position=position,
        )
        logger.info(f"Пользователь {user_tg_id} добавлен в кеш ролей: {department}, {position}")

        # Команды меню
        await set_commands_for_role(callback.bot, user_tg_id, "user")

        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                chat_id=user_tg_id,
                text="✅ Твоя заявка одобрена!\n\nТеперь можешь вносить смены через /shift."
            )
        except Exception:
            pass

        # Обновляем сообщение админа
        await callback.message.edit_text(
            text=original_text + f"\n\n✅ {mention} одобрен. Роль: user"
            f"\n✅ Одобрено администратором {html.escape(callback.from_user.full_name)}",
            parse_mode="HTML",
            reply_markup=None,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        await callback.answer("Пользователь одобрен!")

    except Exception as e:
        logger.exception(f"Ошибка при одобрении заявки: {e}")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)



@auth_router.callback_query(F.data.startswith("reject_"))
async def process_reject(callback: CallbackQuery):
    """Обработка нажатия кнопки 'Отклонить'"""
    try:
        original_text = callback.message.text or ""
        if "✅" in original_text or "❌" in original_text:
            await callback.answer("Уже обработано другим администратором.")
            return

        # Парсим callback_data: reject_TELEGRAM_ID_ROW_INDEX
        parts = callback.data.split("_")
        if len(parts) < 3:
            logger.error("Некорректный формат callback_data при отклонении: %s", callback.data)
            await callback.answer("Некорректный формат данных", show_alert=True)
            return
        try:
            user_tg_id = int(parts[1])
        except ValueError:
            logger.error("Не удалось распарсить ID из callback_data: %s", callback.data)
            await callback.answer("Некорректные данные в запросе", show_alert=True)
            return

        logger.info(f"Админ {callback.from_user.id} отклонил пользователя {user_tg_id}")

        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                chat_id=user_tg_id,
                text="❌ Твоя заявка отклонена.\n\nОбратись к администратору для уточнения причины."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_tg_id}: {e}")

        # Обновляем сообщение админа
        await callback.message.edit_text(
            text=original_text + f"\n\n❌ Отклонено администратором {html.escape(callback.from_user.full_name)}",
            parse_mode="HTML",
            reply_markup=None,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
        await callback.answer("Заявка отклонена")

    except Exception as e:
        logger.exception(f"Ошибка при отклонении заявки: {e}")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)


# --- Обработчики "Написать разработчику" (команда + callback) ---

@auth_router.message(Command("contact_dev"))
async def cmd_contact_dev(message: Message, state: FSMContext):
    await message.answer("✉️ Напишите ваше сообщение разработчику:")
    await state.set_state(AuthStates.waiting_dev_message)


@auth_router.callback_query(F.data == "contact_dev")
async def contact_dev_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("✉️ Напишите ваше сообщение разработчику:")
    await state.set_state(AuthStates.waiting_dev_message)


@auth_router.message(AuthStates.waiting_dev_message)
async def contact_dev_send(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    text = message.text or ""

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    username = message.from_user.username
    escaped_full_name = html.escape(full_name)
    if username:
        user_mention = f'<a href="https://t.me/{username}">@{username}</a>'
    else:
        user_mention = escaped_full_name

    logger.info("Пользователь %s (%s) отправляет сообщение разработчику", tg_id, full_name)

    dev_text = (
        f"📨 Сообщение от пользователя\n\n"
        f"👤 {user_mention} — {escaped_full_name}\n\n"
        f"{html.escape(text)}"
    )

    try:
        await message.bot.send_message(chat_id=DEVELOPER_ID, text=dev_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
        await message.answer("✅ Сообщение отправлено разработчику")
    except Exception:
        error_logger = logging.getLogger("errors")
        error_logger.exception("Не удалось переслать сообщение разработчику от %s", tg_id)
        await message.answer("❌ Не удалось отправить сообщение, попробуйте позже")

    await state.clear()


# --- Ввод email после повышения (/promote → waiting_promote_email) ---

@auth_router.message(AuthStates.waiting_promote_email)
async def process_promote_email(message: Message, state: FSMContext):
    email = (message.text or "").strip()
    tg_id = message.from_user.id

    if not _is_valid_gmail(email):
        await message.answer(
            "❌ Принимается только Gmail адрес.\n\n"
            "Пример: yourname@gmail.com\n\n"
            "Введите корректный Gmail:"
        )
        return

    data = await state.get_data()
    dept = data.get("promote_dept", "")
    full_name = data.get("promote_full_name", str(tg_id))

    username = message.from_user.username
    mention = make_mention(username, full_name)

    logger.info("process_promote_email: пользователь %s ввёл email %s, отдел %s", tg_id, mask_email(email), dept)

    notify_text = (
        f"📧 Новый администратор {mention} ввёл email для доступа к таблице:\n"
        f"{html.escape(email)}\n\n"
        f"Добавьте его как редактора в Google Sheets."
    )
    for sa_id in SUPERADMIN_IDS:
        try:
            await message.bot.send_message(chat_id=sa_id, text=notify_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
        except Exception:
            logger.exception("process_promote_email: не удалось уведомить суперадмина %s", sa_id)

    await message.answer(
        "✅ Email отправлен администратору.\n"
        "После получения доступа к таблице вы сможете приступить к обязанностям."
    )
    await state.clear()


# --- Увольнение сотрудника (/dismiss) ---

def _dismiss_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Сотрудник", callback_data="dismiss_type:user")],
        [InlineKeyboardButton(text="🔑 Администратор отдела", callback_data="dismiss_type:admin")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")],
    ])


def _dismiss_dept_keyboard(dismiss_type: str = "user") -> InlineKeyboardMarkup:
    # У МОП нет своего администратора — кнопка показывается только для сотрудников
    depts = ["Зал", "Бар", "Кухня"]
    if dismiss_type == "user":
        depts.append("МОП")
    buttons = [[InlineKeyboardButton(text=d, callback_data=f"dismiss_dept:{d}")] for d in depts]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@auth_router.message(Command("dismiss"))
async def cmd_dismiss(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    if tg_id != DEVELOPER_ID and tg_id not in SUPERADMIN_IDS:
        await message.answer("Команда недоступна.")
        return
    await state.set_state(AuthStates.waiting_dismiss_dept_type)
    await message.answer(
        "Выберите, кого нужно уволить:",
        reply_markup=_dismiss_type_keyboard(),
    )
    logger.info("cmd_dismiss: суперадмин %s открыл меню увольнения", tg_id)


@auth_router.callback_query(AuthStates.waiting_dismiss_dept_type, F.data.startswith("dismiss_type:"))
async def dismiss_type_selected(callback: CallbackQuery, state: FSMContext):
    dismiss_type = callback.data.split(":")[1]  # "user" or "admin"
    await state.update_data(dismiss_type=dismiss_type)
    await state.set_state(AuthStates.waiting_dismiss_dept)
    type_label = "Сотрудник" if dismiss_type == "user" else "Администратор"
    await callback.message.edit_text(
        f"Тип: {type_label}\nВыберите подразделение:",
        reply_markup=_dismiss_dept_keyboard(dismiss_type),
    )
    await callback.answer()


@auth_router.callback_query(AuthStates.waiting_dismiss_dept, F.data.startswith("dismiss_dept:"))
async def dismiss_dept_selected(callback: CallbackQuery, state: FSMContext):
    dept = callback.data.split(":")[1]
    data = await state.get_data()
    dismiss_type = data.get("dismiss_type", "user")

    if dismiss_type == "admin":
        dept_to_role = {"Зал": "admin_hall", "Бар": "admin_bar", "Кухня": "admin_kitchen"}
        admin_role = dept_to_role.get(dept, "")
        filtered = get_users_by_role(DB_PATH, admin_role) if admin_role else []
        logger.info("dismiss_dept_selected: получено %d администраторов из SQLite для отдела %s", len(filtered), dept)
    else:
        if sheets_client is None:
            await callback.answer("Ошибка подключения к таблице", show_alert=True)
            await state.clear()
            return
        try:
            employees = sheets_client.get_employees_by_dept(dept)
        except Exception:
            logger.exception("dismiss_dept_selected: ошибка при получении сотрудников отдела %s", dept)
            await callback.answer("Ошибка при получении списка сотрудников", show_alert=True)
            await state.clear()
            return
        filtered = []
        for emp in employees:
            user_data = get_user(emp["telegram_id"])
            if user_data and user_data.get("role") == "user":
                filtered.append(emp)

    if not filtered:
        type_label = "сотрудников" if dismiss_type == "user" else "администраторов"
        await callback.message.edit_text(
            f"В отделе «{dept}» нет {type_label}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")]
            ]),
        )
        await callback.answer()
        return

    buttons = [
        [InlineKeyboardButton(
            text=emp["full_name"] or str(emp["telegram_id"]),
            callback_data=f"dismiss_select:{emp['telegram_id']}",
        )]
        for emp in filtered
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")])

    await state.update_data(dismiss_dept=dept)
    await state.set_state(AuthStates.waiting_dismiss_confirm)
    await callback.message.edit_text(
        f"Выберите сотрудника для увольнения ({dept}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


_ADMIN_ROLES = {"admin_hall", "admin_bar", "admin_kitchen"}


@auth_router.callback_query(AuthStates.waiting_dismiss_confirm, F.data.startswith("dismiss_select:"))
async def dismiss_select(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[1])

    user_data = get_user(target_id)
    full_name = user_data["full_name"] if user_data else str(target_id)
    role = user_data.get("role", "user") if user_data else "user"

    if sheets_client is not None:
        tech_info = sheets_client.get_user_from_techlist(target_id)
    else:
        tech_info = None
    position = (tech_info["position"] if tech_info else "") or (user_data.get("position") if user_data else "") or (user_data.get("role") if user_data else "") or "—"
    dept = (tech_info["department"] if tech_info else "") or (user_data.get("department") if user_data else "") or "—"

    await state.update_data(
        dismiss_target_id=target_id,
        dismiss_target_name=full_name,
        dismiss_target_position=position,
        dismiss_target_dept=dept,
    )

    if role in _ADMIN_ROLES:
        logger.info(
            "dismiss_select: %s (id=%s) является администратором (%s), показываем развилку",
            full_name, target_id, role,
        )
        await callback.message.edit_text(
            f"⚠️ {full_name} является администратором отдела {dept}.\n\n"
            f"Что вы хотите сделать?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📉 Только понизить до сотрудника",
                    callback_data=f"dismiss_demote_only:{target_id}",
                )],
                [InlineKeyboardButton(
                    text="🔥 Уволить из системы",
                    callback_data=f"dismiss_confirm:{target_id}",
                )],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")],
            ]),
        )
    else:
        position_display = POSITION_TO_SECTION.get(position, position)
        await callback.message.edit_text(
            f"⚠️ Уволить {full_name} ({position_display}, {dept})?\n\nЭто действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, уволить", callback_data=f"dismiss_confirm:{target_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="dismiss_cancel")],
            ]),
        )
    await callback.answer()


@auth_router.callback_query(AuthStates.waiting_dismiss_confirm, F.data.startswith("dismiss_demote_only:"))
async def dismiss_demote_only_handler(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[1])

    fsm_data = await state.get_data()
    full_name = fsm_data.get("dismiss_target_name", str(target_id))
    dept = fsm_data.get("dismiss_target_dept", "")

    user_data = get_user(target_id)
    position = user_data.get("position") if user_data else None

    RolesCacheService.update_user_role(
        telegram_id=target_id,
        full_name=full_name,
        role="user",
        department=dept,
        position=position,
    )
    logger.info(
        "dismiss_demote_only: %s (id=%s) понижен до user суперадмином %s",
        full_name, target_id, callback.from_user.id,
    )

    await set_commands_for_role(callback.bot, target_id, "user")

    try:
        await callback.bot.send_message(
            chat_id=target_id,
            text=(
                "📉 Ваши права администратора были отозваны.\n"
                "Вы возвращаетесь к стандартным функциям сотрудника."
            ),
        )
    except Exception:
        logger.exception("dismiss_demote_only: не удалось уведомить сотрудника %s", target_id)

    await callback.message.edit_text(
        f"✅ {full_name} понижен до сотрудника. Увольнения не произошло.",
        reply_markup=None,
    )
    await callback.answer()
    await state.clear()


@auth_router.callback_query(AuthStates.waiting_dismiss_confirm, F.data.startswith("dismiss_confirm:"))
async def dismiss_confirm_handler(callback: CallbackQuery, state: FSMContext):
    admin_id = callback.from_user.id
    target_id = int(callback.data.split(":")[1])

    fsm_data = await state.get_data()
    full_name = fsm_data.get("dismiss_target_name", str(target_id))

    error_logger = logging.getLogger("errors")

    # Guard: если сотрудник является администратором — сначала понизить
    current_data = get_user(target_id)
    if current_data and current_data.get("role") in _ADMIN_ROLES:
        dept_guard = current_data.get("department") or ""
        position_guard = current_data.get("position")
        RolesCacheService.update_user_role(
            telegram_id=target_id,
            full_name=full_name,
            role="user",
            department=dept_guard,
            position=position_guard,
        )
        try:
            await set_commands_for_role(callback.bot, target_id, "user")
        except Exception:
            error_logger.exception(
                "dismiss_confirm: не удалось сбросить команды после понижения для %s", target_id
            )
        logger.info(
            "dismiss_confirm: %s (id=%s) сначала понижен до user перед увольнением (guard)",
            full_name, target_id,
        )

    # a) Уведомить сотрудника
    try:
        await callback.bot.send_message(
            chat_id=target_id,
            text="❌ Ваш доступ к боту был отозван.\nПо всем вопросам обращайтесь к администратору.",
        )
    except Exception:
        error_logger.exception("dismiss: не удалось уведомить сотрудника %s", target_id)

    # b) Сбросить команды Telegram
    try:
        await callback.bot.set_my_commands(commands=[], scope=BotCommandScopeChat(chat_id=target_id))
    except Exception:
        error_logger.exception("dismiss: не удалось сбросить команды для %s", target_id)

    # c) Сбросить FSM сотрудника
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM fsm_storage WHERE user_id = ?", (target_id,))
            await db.commit()
    except Exception:
        error_logger.exception("dismiss: не удалось очистить FSM для %s", target_id)

    # d+e) Удалить из SQLite (users = roles cache)
    try:
        delete_user(target_id)
    except Exception:
        error_logger.exception("dismiss: не удалось удалить пользователя %s из SQLite", target_id)

    # f+g) Покрасить ячейку в месячном листе и удалить из Техлиста
    if sheets_client is not None:
        try:
            sheets_client.dismiss_employee(target_id)
        except Exception:
            error_logger.exception("dismiss: ошибка при вызове dismiss_employee для %s", target_id)
    else:
        error_logger.error(
            "dismiss: sheets_client не инициализирован, шаги f/g пропущены для %s", target_id
        )

    # h) Ответить суперадмину
    await state.clear()
    await callback.message.edit_text(f"✅ {full_name} уволен. Доступ отозван.", reply_markup=None)
    await callback.answer()

    # i) Логировать
    logger.info("Сотрудник %s (%s) уволен суперадмином %s", target_id, full_name, admin_id)


@auth_router.callback_query(F.data == "dismiss_cancel")
async def dismiss_cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=None)
    await callback.answer()
