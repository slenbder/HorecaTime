"""/hours_first, /hours_second, /hours_last считают часы из SQLite (shifts), без Sheets."""
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.bot.handlers.userreports import (
    _load_hours_summary,
    cmd_hours_first,
    cmd_hours_last,
    cmd_hours_second,
)
from app.db.models import create_migration_tables, upsert_shift

TG_ID = 12345
_MSK = ZoneInfo("Europe/Moscow")
_MODULE = "app.bot.handlers.userreports"

# Октябрь 2026: 1 — чт, 2 — пт, 3 — сб, 4 — вс, 5 — пн. Сентябрь 2026: 30 дней, 30.09 — ср.
NOW_OCT = datetime(2026, 10, 10, 12, 0, tzinfo=_MSK)

WAITER = {"telegram_id": TG_ID, "role": "user", "position": "Официант"}
RUNNER = {"telegram_id": TG_ID, "role": "user", "position": "Раннер"}
WAITER_RATE = {"base_rate": 250.0, "extra_rate": None}
RUNNER_RATE = {"base_rate": 200.0, "extra_rate": 250.0}


class SheetsSpy:
    """Журнал обращений к sheets_client: любой атрибут записывается в touched."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        return MagicMock()


@pytest.fixture()
def hours_db(tmp_path):
    path = str(tmp_path / "hours.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


def _message():
    message = MagicMock()
    message.from_user.id = TG_ID
    message.answer = AsyncMock()
    return message


def _answer_text(message):
    message.answer.assert_called_once()
    return message.answer.call_args.args[0]


async def _run(handler, hours_db, *, user, rate, now=NOW_OCT, history=None, spy=None):
    """Запускает хендлер на реальной временной БД; ставки и пользователь подменены."""
    message = _message()
    with (
        patch(f"{_MODULE}.DB_PATH", hours_db),
        patch(f"{_MODULE}.get_user", return_value=user),
        patch(f"{_MODULE}.get_user_rate", new=AsyncMock(return_value=rate)),
        patch(f"{_MODULE}.get_user_rate_history", new=AsyncMock(return_value=history)),
        patch(f"{_MODULE}.sheets_client", spy if spy is not None else SheetsSpy()),
        patch(f"{_MODULE}.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = now
        await handler(message)
    return message


# --- (а) Sheets не вызывается ---

@pytest.mark.parametrize("handler", [cmd_hours_first, cmd_hours_second, cmd_hours_last])
@pytest.mark.asyncio
async def test_handlers_do_not_touch_sheets(handler, hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-09-10", 8.0, 0.0, "user")
    await upsert_shift(hours_db, TG_ID, "2026-10-01", 8.0, 0.0, "user")
    spy = SheetsSpy()

    message = await _run(handler, hours_db, user=WAITER, rate=WAITER_RATE,
                         history=WAITER_RATE, spy=spy)

    assert spy.touched == []
    assert message.answer.await_count == 1  # ответ пользователю реально отправлен


# --- (б) 30-дневный месяц: половины и итог не путаются ---

@pytest.mark.asyncio
async def test_september_six_keys(hours_db):
    for date, h, ah in [
        ("2026-09-01", 8.0, 0.0),
        ("2026-09-15", 6.0, 1.0),    # последний день первой половины
        ("2026-09-16", 9.0, 0.0),    # первый день второй
        ("2026-09-30", 7.5, 2.0),    # последний день 30-дневного месяца
        ("2026-10-01", 100.0, 100.0),  # соседний месяц не попадает
    ]:
        await upsert_shift(hours_db, TG_ID, date, h, ah, "user")

    with patch(f"{_MODULE}.DB_PATH", hours_db):
        data = await _load_hours_summary(TG_ID, 2026, 9)

    assert data["h_first"] == 14.0 and data["ah_first"] == 1.0
    assert data["h_second"] == 16.5 and data["ah_second"] == 2.0
    assert data["h_total"] == 30.5 and data["ah_total"] == 3.0
    assert data["h_total"] != data["h_second"]


@pytest.mark.asyncio
async def test_hours_last_text_for_september_second_half_and_total(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-09-05", 10.0, 0.0, "user")
    await upsert_shift(hours_db, TG_ID, "2026-09-30", 8.0, 0.0, "user")

    with patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)):
        message = await _run(cmd_hours_last, hours_db, user=WAITER, rate=WAITER_RATE,
                             history=WAITER_RATE)

    text = _answer_text(message)
    assert "Отработано: 8 ч" in text          # вторая половина
    assert "Всего за месяц: 18 ч" in text     # итог
    assert "Заработок за месяц: 4500" in text  # 18 * 250


# --- (в) Раннер: выходные из shifts попадают в расчёт ---

@pytest.mark.asyncio
async def test_runner_weekend_hours_from_shifts(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-10-01", 8.0, 0.0, "user")   # чт
    await upsert_shift(hours_db, TG_ID, "2026-10-02", 10.0, 0.0, "user")  # пт, выходной

    message = await _run(cmd_hours_first, hours_db, user=RUNNER, rate=RUNNER_RATE)

    text = _answer_text(message)
    assert "8 ч × 200 р = 1600 р (обычные дни)" in text
    assert "10 ч × 250 р = 2500 р (выходные дни)" in text
    assert "Итого: 4100" in text


# --- (г) /hours_last без смен ---

@pytest.mark.asyncio
async def test_hours_last_without_shifts_says_unavailable(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-10-02", 8.0, 0.0, "user")  # смены есть, но не в сентябре

    message = await _run(cmd_hours_last, hours_db, user=WAITER, rate=WAITER_RATE,
                         history=WAITER_RATE)

    message.answer.assert_called_once_with("📊 Данные за прошлый месяц недоступны.")


# --- (д) /hours_first и /hours_second без смен: нули ---

@pytest.mark.asyncio
async def test_hours_first_without_shifts_zeros(hours_db):
    with patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)):
        message = await _run(cmd_hours_first, hours_db, user=WAITER, rate=WAITER_RATE)

    text = _answer_text(message)
    assert "Отработано: 0 ч" in text
    assert "Заработок: 0 р" in text
    assert "не найдены" not in text


@pytest.mark.asyncio
async def test_hours_second_without_shifts_zeros(hours_db):
    with patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)):
        message = await _run(cmd_hours_second, hours_db, user=WAITER, rate=WAITER_RATE)

    text = _answer_text(message)
    assert "Отработано: 0 ч" in text
    assert "Всего за месяц: 0 ч" in text
    assert "Заработок за месяц: 0 р" in text
    assert "не найдены" not in text


# --- (е) /hours_last берёт ставку из user_rates_history ---

@pytest.mark.asyncio
async def test_hours_last_uses_rate_from_history(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-09-20", 10.0, 0.0, "user")
    history = {"base_rate": 250.0, "extra_rate": None}
    current = {"base_rate": 999.0, "extra_rate": None}

    with patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)):
        message = await _run(cmd_hours_last, hours_db, user=WAITER, rate=current,
                             history=history)

    text = _answer_text(message)
    assert "Заработок за месяц: 2500" in text   # по снимку 250, не по текущей 999
    assert "9990" not in text


@pytest.mark.asyncio
async def test_hours_last_falls_back_to_current_rate_without_history(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-09-20", 10.0, 0.0, "user")
    current = {"base_rate": 300.0, "extra_rate": None}

    with patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)):
        message = await _run(cmd_hours_last, hours_db, user=WAITER, rate=current,
                             history=None)

    assert "Заработок за месяц: 3000" in _answer_text(message)


@pytest.mark.asyncio
async def test_hours_last_history_called_with_prev_month(hours_db):
    await upsert_shift(hours_db, TG_ID, "2026-09-20", 10.0, 0.0, "user")
    message = _message()
    history_mock = AsyncMock(return_value={"base_rate": 250.0, "extra_rate": None})
    with (
        patch(f"{_MODULE}.DB_PATH", hours_db),
        patch(f"{_MODULE}.get_user", return_value=WAITER),
        patch(f"{_MODULE}.get_user_rate", new=AsyncMock(return_value=None)),
        patch(f"{_MODULE}.get_user_rate_history", new=history_mock),
        patch(f"{_MODULE}.get_check_filling_summary", new=AsyncMock(return_value=0)),
        patch(f"{_MODULE}.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = NOW_OCT
        await cmd_hours_last(message)

    history_mock.assert_called_once_with(hours_db, TG_ID, 9, 2026)
    assert "Заработок за месяц: 2500" in _answer_text(message)
