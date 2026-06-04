import sqlite3
import pytest

from app.db.models import snapshot_user_rates_history


def _insert_user_rate(conn: sqlite3.Connection, telegram_id: int,
                      base_rate: float, extra_rate: float | None = None) -> None:
    conn.execute(
        'INSERT OR REPLACE INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) VALUES (?, ?, ?, ?)',
        (telegram_id, base_rate, extra_rate, "2026-01-01T00:00:00"),
    )


def _count_history(db_path: str, month: int, year: int) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT COUNT(*) FROM user_rates_history WHERE month = ? AND year = ?',
            (month, year),
        ).fetchone()
    return row[0]


def _fetch_history(db_path: str, month: int, year: int) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT telegram_id, base_rate, extra_rate FROM user_rates_history '
            'WHERE month = ? AND year = ? ORDER BY telegram_id',
            (month, year),
        ).fetchall()
    return [{"telegram_id": r[0], "base_rate": r[1], "extra_rate": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_basic(db_path, insert_user):
    """Базовый снимок: записи из user_rates копируются в user_rates_history."""
    with sqlite3.connect(db_path) as conn:
        insert_user(conn, 1001)
        insert_user(conn, 1002)
        insert_user(conn, 1003)
        _insert_user_rate(conn, 1001, 250.0)
        _insert_user_rate(conn, 1002, 350.0, 500.0)
        _insert_user_rate(conn, 1003, 200.0, 300.0)
        conn.commit()

    await snapshot_user_rates_history(db_path, month=3, year=2026)

    rows = _fetch_history(db_path, month=3, year=2026)
    assert len(rows) == 3

    by_id = {r["telegram_id"]: r for r in rows}
    assert by_id[1001]["base_rate"] == 250.0
    assert by_id[1001]["extra_rate"] is None
    assert by_id[1002]["base_rate"] == 350.0
    assert by_id[1002]["extra_rate"] == 500.0
    assert by_id[1003]["base_rate"] == 200.0
    assert by_id[1003]["extra_rate"] == 300.0


@pytest.mark.asyncio
async def test_snapshot_idempotency(db_path, insert_user):
    """Повторный вызов с теми же месяц/год НЕ дублирует строки (INSERT OR IGNORE)."""
    with sqlite3.connect(db_path) as conn:
        insert_user(conn, 2001)
        insert_user(conn, 2002)
        _insert_user_rate(conn, 2001, 250.0)
        _insert_user_rate(conn, 2002, 350.0, 500.0)
        conn.commit()

    await snapshot_user_rates_history(db_path, month=3, year=2026)
    await snapshot_user_rates_history(db_path, month=3, year=2026)

    count = _count_history(db_path, month=3, year=2026)
    assert count == 2  # не 4


@pytest.mark.asyncio
async def test_snapshot_different_months(db_path, insert_user):
    """Снимки за разные месяцы хранятся независимо."""
    with sqlite3.connect(db_path) as conn:
        insert_user(conn, 3001)
        _insert_user_rate(conn, 3001, 280.0)
        conn.commit()

    await snapshot_user_rates_history(db_path, month=3, year=2026)
    await snapshot_user_rates_history(db_path, month=4, year=2026)

    assert _count_history(db_path, month=3, year=2026) == 1
    assert _count_history(db_path, month=4, year=2026) == 1

    march = _fetch_history(db_path, month=3, year=2026)
    april = _fetch_history(db_path, month=4, year=2026)
    assert march[0]["base_rate"] == 280.0
    assert april[0]["base_rate"] == 280.0


@pytest.mark.asyncio
async def test_snapshot_empty_user_rates(db_path):
    """Если user_rates пуста — функция завершается без ошибок, history тоже пустая."""
    await snapshot_user_rates_history(db_path, month=3, year=2026)

    count = _count_history(db_path, month=3, year=2026)
    assert count == 0
