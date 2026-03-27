from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def department_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Зал")],
            [KeyboardButton(text="Бар")],
            [KeyboardButton(text="Кухня")],
            [KeyboardButton(text="МОП")],
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
            [KeyboardButton(text="Шеф/Су-шеф")],
            [KeyboardButton(text="Горячий цех")],
            [KeyboardButton(text="Холодный цех")],
            [KeyboardButton(text="Кондитерский цех")],
            [KeyboardButton(text="Заготовочный цех")],
            [KeyboardButton(text="Коренной цех")],
            [KeyboardButton(text="Доп.")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kitchen_dop_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Грузчик")],
            [KeyboardButton(text="Закупщик")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def mop_positions_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Клининг")],
            [KeyboardButton(text="Котломой")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_keyboard(role: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[])
