from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def role_type_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Сотрудник")],
            [KeyboardButton(text="🔑 Администратор отдела")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def admin_dept_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Зал")],
            [KeyboardButton(text="Бар")],
            [KeyboardButton(text="Кухня")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def department_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Зал")],
            [KeyboardButton(text="Бар")],
            [KeyboardButton(text="Кухня")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def hall_positions_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Менеджер")],
            [KeyboardButton(text="Официант")],
            [KeyboardButton(text="Раннер")],
            [KeyboardButton(text="Хостесс")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def bar_positions_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Бармен")],
            [KeyboardButton(text="Барбэк")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kitchen_positions_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Су-шеф")],
            [KeyboardButton(text="Горячий цех")],
            [KeyboardButton(text="Холодный цех")],
            [KeyboardButton(text="Кондитерский цех")],
            [KeyboardButton(text="Заготовочный цех")],
            [KeyboardButton(text="Коренной цех")],
            [KeyboardButton(text="МОП")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_keyboard(role: str) -> InlineKeyboardMarkup:
    buttons = []
    if role != "developer":
        buttons.append([InlineKeyboardButton(text="✉️ Написать разработчику", callback_data="contact_dev")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
