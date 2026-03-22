import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.bot.fsm.auth_states import AuthStates, SetRateStates
from app.db.models import get_all_rates, update_rate
from config import DB_PATH, SUPERADMIN_IDS, DEVELOPER_ID

superadmin_router = Router()
logger = logging.getLogger(__name__)


def _is_allowed(tg_id: int) -> bool:
    return tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID

# Позиции, у которых есть повышенная ставка
_POSITIONS_WITH_EXTRA = {"Бармен", "Барбэк", "Раннер"}

# Порядок позиций для отображения
_POSITIONS_ORDER = [
    "Бармен", "Барбэк",
    "Официант", "Раннер", "Хостесс", "Менеджер",
    "Горячий цех", "Холодный цех", "Кондитерский цех",
    "Заготовочный цех", "Коренной цех", "МОП", "Су-шеф",
]


def _fmt_money(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def _rates_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=pos, callback_data=f"set_rate_pos:{pos}")]
        for pos in _POSITIONS_ORDER
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@superadmin_router.message(Command("message_all"))
async def cmd_message_all(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/message_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/message_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    await state.update_data(broadcast_type="all")
    await state.set_state(AuthStates.waiting_broadcast_text)
    await message.answer("Введите текст сообщения для всех сотрудников:")


@superadmin_router.message(Command("rates_all"))
async def cmd_rates_all(message: Message):
    tg_id = message.from_user.id
    logger.info("/rates_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/rates_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    logger.info("/rates_all: доступ разрешён, загружаю ставки")
    rates = await get_all_rates(DB_PATH)

    # Сортируем в нужном порядке
    rate_map = {r["position"]: r for r in rates}
    lines = ["💰 Ставки сотрудников:\n"]
    for pos in _POSITIONS_ORDER:
        r = rate_map.get(pos)
        if r is None:
            continue
        base_str = f"{_fmt_money(r['base_rate'])} р/ч"
        if r["extra_rate"] is not None:
            extra_label = "тусовочные" if pos in ("Бармен", "Барбэк") else "повышенная"
            line = f"{pos}: {base_str} ({extra_label}: {_fmt_money(r['extra_rate'])} р/ч)"
        else:
            line = f"{pos}: {base_str}"
        lines.append(line)

    await message.answer("\n".join(lines))


@superadmin_router.message(Command("set_rate_all"))
async def cmd_set_rate_all(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/set_rate_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/set_rate_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    logger.info("/set_rate_all: доступ разрешён, запускаю FSM")
    await state.set_state(SetRateStates.waiting_set_rate_position)
    await message.answer(
        "Выберите позицию для изменения ставки:",
        reply_markup=_rates_keyboard(),
    )


@superadmin_router.callback_query(
    SetRateStates.waiting_set_rate_position,
    F.data.startswith("set_rate_pos:"),
)
async def cb_set_rate_position(callback: CallbackQuery, state: FSMContext):
    position = callback.data.split(":", 1)[1]
    await state.update_data(position=position)
    await state.set_state(SetRateStates.waiting_set_rate_base)
    await callback.message.edit_text(
        f"Позиция: <b>{position}</b>\n\nВведите базовую ставку (р/час):"
    )
    await callback.answer()


@superadmin_router.message(SetRateStates.waiting_set_rate_base)
async def msg_set_rate_base(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        base_rate = float(text)
        if base_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    data = await state.get_data()
    position = data["position"]
    await state.update_data(base_rate=base_rate)

    if position in _POSITIONS_WITH_EXTRA:
        await state.set_state(SetRateStates.waiting_set_rate_extra)
        extra_label = "тусовочную" if position in ("Бармен", "Барбэк") else "повышенную"
        await message.answer(f"Введите {extra_label} ставку (р/час):")
    else:
        # Нет extra_rate — сразу сохраняем
        await _save_rate(message, state, position, base_rate, extra_rate=None)


@superadmin_router.message(SetRateStates.waiting_set_rate_extra)
async def msg_set_rate_extra(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        extra_rate = float(text)
        if extra_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    data = await state.get_data()
    position = data["position"]
    base_rate = data["base_rate"]
    await _save_rate(message, state, position, base_rate, extra_rate)


async def _save_rate(message: Message, state: FSMContext,
                     position: str, base_rate: float, extra_rate: float | None):
    await update_rate(DB_PATH, position, base_rate, extra_rate)
    await state.clear()

    extra_str = ""
    if extra_rate is not None:
        extra_label = "тусовочные" if position in ("Бармен", "Барбэк") else "повышенная"
        extra_str = f", {extra_label}: {_fmt_money(extra_rate)} р/ч"

    logger.info(
        "set_rate_all: позиция=%s base=%s extra=%s (от %s)",
        position, base_rate, extra_rate, message.from_user.id,
    )
    await message.answer(
        f"✅ Ставка обновлена: {position} — {_fmt_money(base_rate)} р/ч{extra_str}"
    )
