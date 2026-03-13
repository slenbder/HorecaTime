import logging

from app.services.roles_cache import RolesCacheService
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommandScopeChat,
)

from app.bot.fsm.auth_states import AuthStates
from app.bot.keyboards.common import (
    role_type_keyboard,
    admin_dept_keyboard,
    department_keyboard,
    hall_positions_keyboard,
    bar_positions_keyboard,
    kitchen_positions_keyboard,
    main_menu_keyboard,
)

from app.bot.commands import set_commands_for_role
from app.db.models import get_user, delete_user
from app.services.google_sheets import GoogleSheetsClient
from config import (
    SUPERADMIN_IDS,
    ADMIN_HALL_IDS,
    ADMIN_BAR_IDS,
    ADMIN_KITCHEN_IDS,
    DEVELOPER_ID,
)

auth_router = Router()
logger = logging.getLogger(__name__)

# Используем значения из config напрямую (они уже списки int)
SUPERADMINS = SUPERADMIN_IDS
ADMIN_HALL = ADMIN_HALL_IDS
ADMIN_BAR = ADMIN_BAR_IDS
ADMIN_KITCHEN = ADMIN_KITCHEN_IDS

VALID_POSITIONS: dict[str, list[str]] = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Су-шеф", "Горячий цех", "Холодный цех",
               "Кондитерский цех", "Заготовочный цех", "Коренной цех", "МОП"],
}

POSITION_KEYBOARDS = {
    "Зал":   hall_positions_keyboard,
    "Бар":   bar_positions_keyboard,
    "Кухня": kitchen_positions_keyboard,
}

logger.info(f"Загружены SUPERADMINS: {SUPERADMINS}")
logger.info(f"Загружены ADMIN_HALL: {ADMIN_HALL}")
logger.info(f"Загружены ADMIN_BAR: {ADMIN_BAR}")
logger.info(f"Загружены ADMIN_KITCHEN: {ADMIN_KITCHEN}")

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
                "Привет! Давай настроим твою авторизацию.\n\nКем ты являешься?",
                reply_markup=role_type_keyboard(),
            )
            await state.set_state(AuthStates.waiting_role_type)
            return

    # 1. Проверяем, есть ли пользователь и одобрен ли он
    try:
        logger.info(f"Проверка авторизации пользователя {tg_id}")
        is_approved = sheets_client.is_user_fully_authorized(tg_id)
        logger.info(f"Результат проверки авторизации: {is_approved}")

        if is_approved:
            await message.answer(
                "Ты уже авторизован в системе ✅\n"
                "Скоро здесь появится главное меню (внесение часов, отчёты и т.д.)."
            )
            cached = RolesCacheService.get_user_role(tg_id)
            if cached and cached.get("role") and cached["role"] != "guest":
                await set_commands_for_role(message.bot, tg_id, cached["role"])
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
        "Привет! Давай настроим твою авторизацию.\n\nКем ты являешься?",
        reply_markup=role_type_keyboard(),
    )
    await state.set_state(AuthStates.waiting_role_type)


@auth_router.message(AuthStates.waiting_role_type, F.text == "👤 Сотрудник")
async def process_role_type_user(message: Message, state: FSMContext):
    await state.update_data(registration_type="user")
    logger.info("Пользователь %s выбрал тип регистрации: Сотрудник", message.from_user.id)
    await message.answer("Выбери, к какому отделу ты относишься:", reply_markup=department_keyboard())
    await state.set_state(AuthStates.choosing_department)


@auth_router.message(AuthStates.waiting_role_type, F.text == "🔑 Администратор отдела")
async def process_role_type_admin(message: Message, state: FSMContext):
    await state.update_data(registration_type="admin")
    logger.info("Пользователь %s выбрал тип регистрации: Администратор", message.from_user.id)
    await message.answer("Выбери отдел, которым ты управляешь:", reply_markup=admin_dept_keyboard())
    await state.set_state(AuthStates.waiting_admin_dept)


@auth_router.message(AuthStates.waiting_role_type)
async def process_role_type_invalid(message: Message):
    await message.answer(
        "Пожалуйста, выбери вариант, используя кнопки ниже.",
        reply_markup=role_type_keyboard(),
    )


@auth_router.message(AuthStates.waiting_admin_dept, F.text.in_(["Зал", "Бар", "Кухня"]))
async def process_admin_dept(message: Message, state: FSMContext):
    dept = message.text
    logger.info("Пользователь %s (admin) выбрал отдел: %s", message.from_user.id, dept)
    await state.update_data(department=dept)
    await message.answer("Введи своё Фамилию и Имя:")
    await state.set_state(AuthStates.entering_fio)


@auth_router.message(AuthStates.waiting_admin_dept)
async def process_admin_dept_invalid(message: Message):
    await message.answer(
        "Пожалуйста, выбери отдел, используя кнопки ниже.",
        reply_markup=admin_dept_keyboard(),
    )


@auth_router.message(AuthStates.choosing_department, F.text.in_(["Зал", "Бар", "Кухня"]))
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
    await state.update_data(position=position)

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
    registration_type = data.get("registration_type", "user")

    tg_id = message.from_user.id
    nickname = message.from_user.username or ""
    tg_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()

    logger.info(
        "Пользователь %s ввёл ФИО: %s, отдел: %s, тип: %s",
        tg_id, fio, department, registration_type,
    )

    # --- Ветка: заявка администратора ---
    if registration_type == "admin":
        admin_request_text = (
            f"🔑 Заявка администратора\n\n"
            f"👤 {fio}\n"
            f"🏢 Отдел: {department}\n\n"
            f"ID: {tg_id}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"approve_admin:{tg_id}:{department}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject_admin:{tg_id}",
                ),
            ]
        ])

        logger.info("Отправка заявки администратора суперадминам: %s", SUPERADMINS)
        for sa_id in SUPERADMINS:
            try:
                await message.bot.send_message(chat_id=sa_id, text=admin_request_text, reply_markup=keyboard)
                logger.info("Заявка администратора отправлена суперадмину %s", sa_id)
            except Exception as e:
                logger.exception("Не удалось отправить заявку администратора суперадмину %s: %s", sa_id, e)

        await message.answer(
            "Спасибо! Твоя заявка на роль администратора отправлена.\n"
            "После одобрения ты получишь доступ к панели управления отделом."
        )
        logger.info("Заявка администратора от пользователя %s завершена", tg_id)
        await state.clear()
        return

    # --- Ветка: заявка сотрудника (существующая логика) ---
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
            tg_name=tg_name,
            fio_from_user=fio,
            department=department,
            position=position,
        )

        logger.info(f"Заявка успешно записана в строку {row_index}")
    except Exception as e:
        logger.exception(f"Ошибка при записи заявки в Техлист для пользователя {tg_id}: {e}")
        await message.answer(
            "Не удалось сохранить заявку в таблицу. Попробуй позже или напиши администратору."
        )
        await state.clear()
        return

    # 2. Формируем текст заявки с inline-кнопками
    text = (
        "📝 <b>Новая заявка на доступ к боту:</b>\n\n"
        f"👤 <b>ФИО:</b> {fio}\n"
        f"🏢 <b>Отдел:</b> {department}\n"
        f"💼 <b>Позиция:</b> {position}\n\n"
        f"🆔 Telegram ID: <code>{tg_id}</code>\n"
        f"📱 Ник: @{nickname if nickname else '—'}\n"
        f"📋 Имя (TG): {tg_name or '—'}\n"
        f"📊 Строка в Техлисте: {row_index}\n\n"
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
        recipients.extend(ADMIN_HALL)
    elif department == "Бар":
        recipients.extend(ADMIN_BAR)
    elif department == "Кухня":
        recipients.extend(ADMIN_KITCHEN)

    # Суперадмины получают все заявки
    recipients.extend(SUPERADMINS)

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
                    reply_markup=keyboard
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
        f"Позиция: {position}\n"
        f"ФИО: {fio}\n\n"
        "Заявка на доступ отправлена администратору.\n"
        "После одобрения ты сможешь вносить рабочие часы и смотреть отчёты."
    )
    logger.info(f"Регистрация пользователя {tg_id} завершена успешно")
    await state.clear()


# --- Обработчики inline-кнопок ---

DEPT_TO_ADMIN_ROLE = {
    "Зал": "admin_hall",
    "Бар": "admin_bar",
    "Кухня": "admin_kitchen",
}


@auth_router.callback_query(F.data.startswith("approve_admin:"))
async def process_approve_admin(callback: CallbackQuery):
    """Одобрение заявки администратора суперадмином."""
    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            logger.error("Некорректный формат callback_data approve_admin: %s", callback.data)
            await callback.answer("Некорректный формат данных", show_alert=True)
            return
        user_tg_id = int(parts[1])
        dept = parts[2]

        role = DEPT_TO_ADMIN_ROLE.get(dept)
        if not role:
            logger.error("Неизвестный отдел в approve_admin: %s", dept)
            await callback.answer("Неизвестный отдел", show_alert=True)
            return

        # Сохраняем в SQLite
        RolesCacheService.update_user_role(
            telegram_id=user_tg_id,
            full_name="",  # ФИО неизвестно на этом этапе
            role=role,
            department=dept,
        )
        logger.info(
            "Суперадмин %s одобрил администратора %s, роль=%s, отдел=%s",
            callback.from_user.id, user_tg_id, role, dept,
        )

        # Устанавливаем команды для новой роли
        await set_commands_for_role(callback.bot, user_tg_id, role)

        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                chat_id=user_tg_id,
                text=f"✅ Доступ предоставлен!\n\nТы добавлен как администратор отдела {dept}.",
            )
        except Exception as e:
            logger.error("Не удалось уведомить администратора %s: %s", user_tg_id, e)

        await callback.message.edit_text(
            text=callback.message.text + "\n\n✅ ОДОБРЕНО",
            reply_markup=None,
        )
        await callback.answer("Администратор одобрен!")

    except Exception:
        logger.exception("Ошибка при одобрении заявки администратора")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)


@auth_router.callback_query(F.data.startswith("reject_admin:"))
async def process_reject_admin(callback: CallbackQuery):
    """Отклонение заявки администратора суперадмином."""
    try:
        parts = callback.data.split(":")
        user_tg_id = int(parts[1])

        logger.info(
            "Суперадмин %s отклонил заявку администратора %s",
            callback.from_user.id, user_tg_id,
        )

        try:
            await callback.bot.send_message(chat_id=user_tg_id, text="❌ В доступе отказано.")
        except Exception as e:
            logger.error("Не удалось уведомить пользователя %s: %s", user_tg_id, e)

        await callback.message.edit_text(
            text=callback.message.text + "\n\n❌ ОТКЛОНЕНО",
            reply_markup=None,
        )
        await callback.answer("Заявка отклонена")

    except Exception:
        logger.exception("Ошибка при отклонении заявки администратора")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)


@auth_router.callback_query(F.data.startswith("approve_"))
async def process_approve(callback: CallbackQuery):
    """Обработка нажатия кнопки 'Одобрить'"""
    try:
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
        position = user_info.get("position", "")

        # Одобряем пользователя в таблице
        sheets_client.mark_user_approved(row_index)
        logger.info(
            f"Админ {callback.from_user.id} одобрил пользователя {user_tg_id} (строка {row_index})"
        )

        # Сразу добавляем пользователя в график текущего месяца
        try:
            inserted = sheets_client.ensure_user_in_current_month_hours(user_tg_id)
            logger.info(
                "Синхронизация в график завершена для %s, inserted=%s",
                user_tg_id,
                inserted,
            )
        except Exception as sync_error:
            logger.exception(
                "Пользователь %s помечен как одобренный, но не был добавлен в график: %s",
                user_tg_id,
                sync_error,
            )

            await callback.message.edit_text(
                text=callback.message.text + "\n\n⚠️ ОДОБРЕНО, НО НЕ ДОБАВЛЕН В ГРАФИК",
                reply_markup=None,
            )
            await callback.answer(
                "В Техлисте проставлено ДА, но добавить пользователя в график не удалось. Проверь лист месяца и данные в Техлисте.",
                show_alert=True,
            )
            return

        # Записываем в кеш ролей
        RolesCacheService.update_user_role(
            telegram_id=user_tg_id,
            full_name=fio,
            role="user",
            department=department,
        )
        logger.info(f"Пользователь {user_tg_id} добавлен в кеш ролей: {department}, {position}")

        # Уведомляем пользователя
        try:
            await callback.bot.send_message(
                chat_id=user_tg_id,
                text="✅ Твоя заявка одобрена!\n\nТеперь ты можешь вносить рабочие часы и смотреть отчёты."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_tg_id}: {e}")

        cached = RolesCacheService.get_user_role(user_tg_id)
        if cached and cached.get("role") and cached["role"] != "guest":
            await set_commands_for_role(callback.bot, user_tg_id, cached["role"])

        # Обновляем сообщение админа
        await callback.message.edit_text(
            text=callback.message.text + "\n\n✅ ОДОБРЕНО",
            reply_markup=None
        )

        await callback.answer("Пользователь одобрен!")

    except Exception as e:
        logger.exception(f"Ошибка при одобрении заявки: {e}")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)



@auth_router.callback_query(F.data.startswith("reject_"))
async def process_reject(callback: CallbackQuery):
    """Обработка нажатия кнопки 'Отклонить'"""
    try:
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
            text=callback.message.text + "\n\n❌ <b>ОТКЛОНЕНО</b>",
            reply_markup=None
        )
        await callback.answer("Заявка отклонена")

    except Exception as e:
        logger.exception(f"Ошибка при отклонении заявки: {e}")
        await callback.answer("Ошибка при обработке заявки", show_alert=True)


# --- Обработчик кнопки "Написать разработчику" ---

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

    logger.info("Пользователь %s (%s) отправляет сообщение разработчику", tg_id, full_name)

    dev_text = (
        f"📨 Сообщение от пользователя\n\n"
        f"👤 {full_name} (ID: {tg_id})\n\n"
        f"{text}"
    )

    try:
        await message.bot.send_message(chat_id=DEVELOPER_ID, text=dev_text)
        await message.answer("✅ Сообщение отправлено разработчику")
    except Exception:
        error_logger = logging.getLogger("errors")
        error_logger.exception("Не удалось переслать сообщение разработчику от %s", tg_id)
        await message.answer("❌ Не удалось отправить сообщение, попробуйте позже")

    await state.clear()
