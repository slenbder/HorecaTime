"""
Тесты для функций работы с персональными ставками в app/db/models.py:
  - get_user_rate()
  - set_user_rate()
  - snapshot_user_rates_history()
  - get_user_rate_history()  (используется для проверки снимков)

Все тесты используют изолированную временную БД (tempfile.mkstemp),
которая создаётся заново перед каждым тестом и удаляется после.
"""
import asyncio
import os
import sqlite3
import tempfile

import pytest

from app.db.models import (
    get_user_rate,
    get_user_rate_history,
    set_user_rate,
    snapshot_user_rates_history,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _create_schema(db_path: str) -> None:
    """Создаёт минимальную схему БД, необходимую для тестируемых функций."""
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                full_name   TEXT NOT NULL,
                role        TEXT NOT NULL,
                department  TEXT,
                position    TEXT,
                hourly_rate REAL,
                created_at  TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_rates (
                telegram_id INTEGER PRIMARY KEY,
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                updated_at  TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_rates_history (
                telegram_id INTEGER NOT NULL,
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                month       INTEGER NOT NULL,
                year        INTEGER NOT NULL,
                PRIMARY KEY (telegram_id, month, year)
            )
        ''')
        conn.commit()


def _insert_user_rate(db_path: str, telegram_id: int,
                      base_rate: float, extra_rate: float | None = None) -> None:
    """Вставляет запись в user_rates напрямую (минуя бизнес-логику)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            'INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) '
            'VALUES (?, ?, ?, "2026-01-01T00:00:00")',
            (telegram_id, base_rate, extra_rate),
        )
        conn.commit()


def _count_history(db_path: str, month: int, year: int) -> int:
    """Возвращает количество записей в user_rates_history для периода."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT COUNT(*) FROM user_rates_history WHERE month = ? AND year = ?',
            (month, year),
        ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    """Создаёт временный файл БД со схемой; удаляет после теста."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _create_schema(path)
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# get_user_rate
# ---------------------------------------------------------------------------

class TestGetUserRate:
    def test_existing_user_base_only(self, db_path):
        """Возвращает ставку существующего пользователя (только базовая)."""
        _insert_user_rate(db_path, telegram_id=111, base_rate=250.0)

        result = asyncio.run(get_user_rate(db_path, 111))

        assert result is not None
        assert result["telegram_id"] == 111
        assert result["base_rate"] == 250.0
        assert result["extra_rate"] is None

    def test_existing_user_with_extra_rate(self, db_path):
        """Возвращает обе ставки для позиции с повышенной ставкой."""
        _insert_user_rate(db_path, telegram_id=222, base_rate=350.0, extra_rate=500.0)

        result = asyncio.run(get_user_rate(db_path, 222))

        assert result is not None
        assert result["base_rate"] == 350.0
        assert result["extra_rate"] == 500.0

    def test_nonexistent_user_returns_none(self, db_path):
        """Для несуществующего telegram_id возвращает None."""
        result = asyncio.run(get_user_rate(db_path, 999999))

        assert result is None

    def test_returns_correct_user_when_multiple_exist(self, db_path):
        """Возвращает ставку именно запрошенного пользователя."""
        _insert_user_rate(db_path, telegram_id=301, base_rate=200.0)
        _insert_user_rate(db_path, telegram_id=302, base_rate=400.0, extra_rate=600.0)

        result_301 = asyncio.run(get_user_rate(db_path, 301))
        result_302 = asyncio.run(get_user_rate(db_path, 302))

        assert result_301["base_rate"] == 200.0
        assert result_302["base_rate"] == 400.0
        assert result_302["extra_rate"] == 600.0


# ---------------------------------------------------------------------------
# set_user_rate
# ---------------------------------------------------------------------------

class TestSetUserRate:
    def test_insert_new_rate(self, db_path):
        """Создаёт новую запись для пользователя, которого не было."""
        asyncio.run(set_user_rate(db_path, telegram_id=401, base_rate=280.0))

        result = asyncio.run(get_user_rate(db_path, 401))

        assert result is not None
        assert result["base_rate"] == 280.0
        assert result["extra_rate"] is None

    def test_insert_with_extra_rate(self, db_path):
        """Создаёт запись с повышенной ставкой."""
        asyncio.run(set_user_rate(db_path, telegram_id=402, base_rate=350.0, extra_rate=500.0))

        result = asyncio.run(get_user_rate(db_path, 402))

        assert result["base_rate"] == 350.0
        assert result["extra_rate"] == 500.0

    def test_update_existing_base_rate(self, db_path):
        """Обновляет базовую ставку уже существующего пользователя."""
        _insert_user_rate(db_path, telegram_id=403, base_rate=200.0)

        asyncio.run(set_user_rate(db_path, telegram_id=403, base_rate=250.0))

        result = asyncio.run(get_user_rate(db_path, 403))
        assert result["base_rate"] == 250.0

    def test_update_clears_extra_rate(self, db_path):
        """При обновлении без extra_rate — поле обнуляется."""
        _insert_user_rate(db_path, telegram_id=404, base_rate=350.0, extra_rate=500.0)

        asyncio.run(set_user_rate(db_path, telegram_id=404, base_rate=350.0, extra_rate=None))

        result = asyncio.run(get_user_rate(db_path, 404))
        assert result["extra_rate"] is None

    def test_update_changes_extra_rate(self, db_path):
        """Обновляет повышенную ставку."""
        _insert_user_rate(db_path, telegram_id=405, base_rate=200.0, extra_rate=300.0)

        asyncio.run(set_user_rate(db_path, telegram_id=405, base_rate=200.0, extra_rate=350.0))

        result = asyncio.run(get_user_rate(db_path, 405))
        assert result["extra_rate"] == 350.0

    def test_persists_after_separate_call(self, db_path):
        """Изменения видны при повторном чтении (другой вызов get_user_rate)."""
        asyncio.run(set_user_rate(db_path, telegram_id=406, base_rate=230.0))
        asyncio.run(set_user_rate(db_path, telegram_id=406, base_rate=260.0))

        result = asyncio.run(get_user_rate(db_path, 406))

        assert result["base_rate"] == 260.0

    def test_zero_base_rate_is_stored(self, db_path):
        """Нулевая ставка допустима и сохраняется корректно."""
        asyncio.run(set_user_rate(db_path, telegram_id=407, base_rate=0.0))

        result = asyncio.run(get_user_rate(db_path, 407))

        assert result is not None
        assert result["base_rate"] == 0.0


# ---------------------------------------------------------------------------
# snapshot_user_rates_history
# ---------------------------------------------------------------------------

class TestSnapshotUserRatesHistory:
    def test_snapshot_copies_all_rates(self, db_path):
        """Снимок содержит все текущие записи из user_rates."""
        _insert_user_rate(db_path, telegram_id=501, base_rate=250.0)
        _insert_user_rate(db_path, telegram_id=502, base_rate=350.0, extra_rate=500.0)

        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        assert _count_history(db_path, month=3, year=2026) == 2

    def test_snapshot_values_match_source(self, db_path):
        """Значения снимка совпадают с исходными ставками."""
        _insert_user_rate(db_path, telegram_id=503, base_rate=280.0, extra_rate=400.0)

        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        hist = asyncio.run(get_user_rate_history(db_path, 503, month=3, year=2026))
        assert hist is not None
        assert hist["base_rate"] == 280.0
        assert hist["extra_rate"] == 400.0

    def test_snapshot_not_overwritten_on_repeat_call(self, db_path):
        """Повторный снимок для того же периода не перезаписывает данные (INSERT OR IGNORE)."""
        _insert_user_rate(db_path, telegram_id=504, base_rate=200.0)
        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        # Меняем ставку после первого снимка
        asyncio.run(set_user_rate(db_path, telegram_id=504, base_rate=999.0))
        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        hist = asyncio.run(get_user_rate_history(db_path, 504, month=3, year=2026))
        assert hist["base_rate"] == 200.0  # оригинальное значение сохранено

    def test_snapshot_is_independent_per_period(self, db_path):
        """Снимки разных периодов не влияют друг на друга."""
        _insert_user_rate(db_path, telegram_id=505, base_rate=250.0)
        asyncio.run(snapshot_user_rates_history(db_path, month=2, year=2026))

        asyncio.run(set_user_rate(db_path, telegram_id=505, base_rate=300.0))
        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        hist_feb = asyncio.run(get_user_rate_history(db_path, 505, month=2, year=2026))
        hist_mar = asyncio.run(get_user_rate_history(db_path, 505, month=3, year=2026))

        assert hist_feb["base_rate"] == 250.0
        assert hist_mar["base_rate"] == 300.0

    def test_snapshot_empty_user_rates(self, db_path):
        """Снимок пустой таблицы user_rates не вызывает ошибку и не создаёт записей."""
        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        assert _count_history(db_path, month=3, year=2026) == 0

    def test_snapshot_does_not_affect_current_rates(self, db_path):
        """После снимка текущие ставки в user_rates остаются неизменными."""
        _insert_user_rate(db_path, telegram_id=506, base_rate=350.0)

        asyncio.run(snapshot_user_rates_history(db_path, month=3, year=2026))

        current = asyncio.run(get_user_rate(db_path, 506))
        assert current["base_rate"] == 350.0

    def test_history_returns_none_for_missing_period(self, db_path):
        """get_user_rate_history возвращает None, если снимок для периода не создавался."""
        _insert_user_rate(db_path, telegram_id=507, base_rate=200.0)

        hist = asyncio.run(get_user_rate_history(db_path, 507, month=1, year=2026))

        assert hist is None
