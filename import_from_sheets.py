#!/usr/bin/env python3
"""
Одноразовый импорт Google Sheets → SQLite (Фаза 1 миграции "SQLite = source of truth").

Наполняет новые таблицы (employees, shifts, check_filling) данными,
которые сейчас существуют только в Google Sheets:
  a) Техлист → employees (включая неодобренные заявки)
  b) Текущий + прошлый месячные листы → shifts
  c) Строка фантома наполняемости чеков → check_filling
  d) Красные строки текущего месяца → status='dismissed' в employees

Запуск:
  python import_from_sheets.py --dry-run              # прогон без записи
  python import_from_sheets.py --db-path data/bot.db  # боевой импорт

Идемпотентен: повторный запуск не дублирует записи; смены с
source != 'import' (данные Фазы 2) не перезаписываются.
"""
import argparse
import calendar
import logging
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models import create_migration_tables
from app.services.google_sheets import (
    GoogleSheetsClient,
    MONTH_NAMES_RU,
    COL_TELEGRAM_ID,
    COL_NICKNAME,
    COL_FIO_FROM_USER,
    COL_DEPARTMENT,
    COL_POSITION,
    COL_REGISTERED_AT,
    COL_IN_STAFF_TABLE,
    COL_CUSTOM_POSITION,
)
from config import PHANTOM_CHECK_FILLING_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("import_from_sheets")

MSK = ZoneInfo("Europe/Moscow")


# ---------------------------------------------------------------------------
# Парсинг (чистые функции, тестируются без Google API)
# ---------------------------------------------------------------------------

def parse_shift_cell(raw: str) -> tuple[float, float] | None:
    """
    Парсит ячейку смены месячного листа.
    "8" → (8.0, 0.0); "8/2" → (8.0, 2.0); "1,5" → (1.5, 0.0);
    пустая → None (нет записи); мусор → ValueError.
    """
    val = str(raw).strip()
    if not val:
        return None
    if "/" in val:
        h_raw, ah_raw = val.split("/", 1)
        return (
            float(h_raw.strip().replace(",", ".")),
            float(ah_raw.strip().replace(",", ".")),
        )
    return float(val.replace(",", ".")), 0.0


def parse_registered_at(raw: str) -> str | None:
    """'DD.MM.YY HH:MM' (формат колонки F Техлиста) → ISO, или None если не парсится."""
    val = str(raw).strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, "%d.%m.%y %H:%M").replace(tzinfo=MSK).isoformat()
    except ValueError:
        return None


def day_to_col(day: int) -> int:
    """День месяца → 1-based колонка листа: дни 1–15 → D–R (4–18), 16–31 → T–AI (20–35)."""
    return 3 + day if day <= 15 else 19 + (day - 15)


def _cell(row: list, col: int) -> str:
    return str(row[col - 1]).strip() if len(row) >= col else ""


def extract_employees(
    techlist_values: list[list],
    roles_by_id: dict[int, str],
    now_iso: str,
) -> tuple[list[dict], list[str]]:
    """Техлист → записи employees. Возвращает (записи, warnings)."""
    rows: list[dict] = []
    warnings: list[str] = []

    for i, row in enumerate(techlist_values[1:], start=2):  # строка 1 — заголовок
        if not row:
            continue
        tg_raw = _cell(row, COL_TELEGRAM_ID)
        if not tg_raw:
            continue
        if not tg_raw.lstrip("-").isdigit():
            warnings.append(f"Техлист, строка {i}: нечисловой TG_ID '{tg_raw}' — пропущена")
            continue
        tg_id = int(tg_raw)

        registered_at = parse_registered_at(_cell(row, COL_REGISTERED_AT))
        if registered_at is None:
            warnings.append(
                f"Техлист, строка {i} (TG_ID {tg_id}): дата регистрации "
                f"'{_cell(row, COL_REGISTERED_AT)}' не распарсилась — записано текущее время"
            )
            registered_at = now_iso

        full_name = _cell(row, COL_FIO_FROM_USER)
        if not full_name:
            warnings.append(f"Техлист, строка {i} (TG_ID {tg_id}): пустое ФИО")

        approved = _cell(row, COL_IN_STAFF_TABLE).upper() == "ДА"
        rows.append({
            "telegram_id": tg_id,
            "nickname": _cell(row, COL_NICKNAME) or None,
            "full_name": full_name,
            "department": _cell(row, COL_DEPARTMENT),
            "position": _cell(row, COL_POSITION),
            "custom_position": _cell(row, COL_CUSTOM_POSITION) or None,
            "role": roles_by_id.get(tg_id, "user"),
            "status": "approved" if approved else "pending",
            "registered_at": registered_at,
        })
    return rows, warnings


def extract_shifts(
    sheet_values: list[list],
    sheet_name: str,
    month: int,
    year: int,
    now_iso: str,
) -> tuple[list[dict], list[str]]:
    """Месячный лист → записи shifts (строка фантома пропускается)."""
    rows: list[dict] = []
    warnings: list[str] = []
    days_in_month = calendar.monthrange(year, month)[1]

    for i, row in enumerate(sheet_values, start=1):
        tg_raw = _cell(row, 2)  # колонка B
        if not tg_raw or not tg_raw.lstrip("-").isdigit():
            continue
        tg_id = int(tg_raw)
        if tg_id == PHANTOM_CHECK_FILLING_ID:
            continue

        for day in range(1, days_in_month + 1):
            raw = _cell(row, day_to_col(day))
            try:
                parsed = parse_shift_cell(raw)
            except ValueError:
                warnings.append(
                    f"'{sheet_name}', строка {i}, день {day} (TG_ID {tg_id}): "
                    f"непарсибельное значение '{raw}' — пропущено"
                )
                continue
            if parsed is None:
                continue
            h, ah = parsed
            rows.append({
                "telegram_id": tg_id,
                "shift_date": f"{year:04d}-{month:02d}-{day:02d}",
                "hours": h,
                "extra_hours": ah,
                "source": "import",
                "created_at": now_iso,
                "updated_at": now_iso,
            })
    return rows, warnings


def extract_check_filling(
    sheet_values: list[list],
    sheet_name: str,
    month: int,
    year: int,
) -> tuple[list[dict], list[str]]:
    """Дневные ячейки строки фантома → записи check_filling."""
    rows: list[dict] = []
    warnings: list[str] = []
    days_in_month = calendar.monthrange(year, month)[1]

    phantom_row = None
    for row in sheet_values:
        if _cell(row, 2) == str(PHANTOM_CHECK_FILLING_ID):
            phantom_row = row
            break
    if phantom_row is None:
        warnings.append(f"'{sheet_name}': строка фантома {PHANTOM_CHECK_FILLING_ID} не найдена")
        return rows, warnings

    for day in range(1, days_in_month + 1):
        raw = _cell(phantom_row, day_to_col(day))
        if not raw:
            continue
        try:
            count = int(float(raw.replace(",", ".")))
        except ValueError:
            warnings.append(
                f"'{sheet_name}', фантом, день {day}: непарсибельное значение '{raw}' — пропущено"
            )
            continue
        rows.append({"fill_date": f"{year:04d}-{month:02d}-{day:02d}", "count": count})
    return rows, warnings


def extract_dismissed_ids(sheet_values: list[list], dismissed_rows: set) -> list[int]:
    """Индексы красных строк (1-based) → TG_ID из колонки B."""
    result = []
    for i in sorted(dismissed_rows):
        if i > len(sheet_values):
            continue
        tg_raw = _cell(sheet_values[i - 1], 2)
        if tg_raw.lstrip("-").isdigit() and int(tg_raw) != PHANTOM_CHECK_FILLING_ID:
            result.append(int(tg_raw))
    return result


# ---------------------------------------------------------------------------
# Запись в SQLite
# ---------------------------------------------------------------------------

def load_roles(conn: sqlite3.Connection) -> dict[int, str]:
    """Роли из существующей таблицы users (кеш ролей одобренных)."""
    try:
        return dict(conn.execute("SELECT telegram_id, role FROM users").fetchall())
    except sqlite3.OperationalError:
        logger.warning("Таблица users не найдена — все роли будут 'user'")
        return {}


def write_employees(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany('''
        INSERT OR REPLACE INTO employees
            (telegram_id, nickname, full_name, department, position,
             custom_position, role, status, registered_at)
        VALUES (:telegram_id, :nickname, :full_name, :department, :position,
                :custom_position, :role, :status, :registered_at)
    ''', rows)
    return len(rows)


def write_shifts(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """
    Вставка смен с защитой данных Фазы 2: существующая запись
    перезаписывается только если её source == 'import'.
    """
    written = 0
    for r in rows:
        cur = conn.execute('''
            INSERT INTO shifts
                (telegram_id, shift_date, hours, extra_hours, source, created_at, updated_at)
            VALUES (:telegram_id, :shift_date, :hours, :extra_hours, :source, :created_at, :updated_at)
            ON CONFLICT(telegram_id, shift_date) DO UPDATE SET
                hours = excluded.hours,
                extra_hours = excluded.extra_hours,
                updated_at = excluded.updated_at
            WHERE shifts.source = 'import'
        ''', r)
        written += cur.rowcount
    return written


def write_check_filling(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany(
        "INSERT OR REPLACE INTO check_filling (fill_date, count) VALUES (:fill_date, :count)",
        rows,
    )
    return len(rows)


def mark_dismissed(conn: sqlite3.Connection, tg_ids: list[int], now_iso: str) -> int:
    marked = 0
    for tg_id in tg_ids:
        cur = conn.execute(
            "UPDATE employees SET status = 'dismissed', dismissed_at = ? WHERE telegram_id = ?",
            (now_iso, tg_id),
        )
        marked += cur.rowcount
    return marked


# ---------------------------------------------------------------------------
# Основной сценарий
# ---------------------------------------------------------------------------

def _month_sheet(client: GoogleSheetsClient, month: int, year: int):
    """Возвращает (имя листа, all_values) или (имя, None) если лист не найден."""
    name = f"{MONTH_NAMES_RU[month]} {year}"
    try:
        ws = client._spreadsheet.worksheet(name)
        return name, ws.get_all_values()
    except Exception as e:
        logger.warning("Лист '%s' недоступен, пропускаю: %s", name, e)
        return name, None


def run_import(db_path: str, dry_run: bool) -> None:
    now = datetime.now(MSK)
    now_iso = now.isoformat()
    warnings: list[str] = []

    client = GoogleSheetsClient()

    # Роли берём из существующей users до любых записей
    conn = sqlite3.connect(db_path)
    try:
        roles_by_id = load_roles(conn)

        # a) Техлист → employees (один get_all_values на лист)
        techlist_values = client._get_techlist_worksheet().get_all_values()
        employees, w = extract_employees(techlist_values, roles_by_id, now_iso)
        warnings += w

        # b) Текущий + прошлый месяц → shifts
        cur_month, cur_year = now.month, now.year
        prev_month, prev_year = (12, cur_year - 1) if cur_month == 1 else (cur_month - 1, cur_year)

        shifts: list[dict] = []
        check_rows: list[dict] = []
        dismissed_ids: list[int] = []

        for month, year, is_current in (
            (prev_month, prev_year, False),
            (cur_month, cur_year, True),
        ):
            sheet_name, values = _month_sheet(client, month, year)
            if values is None:
                warnings.append(f"Лист '{sheet_name}' не найден — смены за него не импортированы")
                continue

            s_rows, w = extract_shifts(values, sheet_name, month, year, now_iso)
            shifts += s_rows
            warnings += w

            if is_current:
                # c) Фантом текущего месяца → check_filling
                check_rows, w = extract_check_filling(values, sheet_name, month, year)
                warnings += w
                # d) Красные строки текущего месяца → dismissed
                dismissed_rows = client.get_dismissed_rows(sheet_name)
                dismissed_ids = extract_dismissed_ids(values, dismissed_rows)

        # --- Сводка ---
        by_status = {"pending": 0, "approved": 0, "dismissed": 0}
        for e in employees:
            by_status[e["status"]] += 1
        # dismissed проставляется UPDATE'ом после вставки; для сводки считаем пересечение
        dismissed_in_employees = {e["telegram_id"] for e in employees} & set(dismissed_ids)

        print("\n===== ИТОГ ИМПОРТА" + (" (DRY-RUN, БЕЗ ЗАПИСИ)" if dry_run else "") + " =====")
        print(f"employees:     {len(employees)} "
              f"(pending={by_status['pending']}, approved={by_status['approved']}, "
              f"будет помечено dismissed={len(dismissed_in_employees)})")
        print(f"shifts:        {len(shifts)}")
        print(f"check_filling: {len(check_rows)}")
        print(f"warnings:      {len(warnings)}")
        for msg in warnings:
            print(f"  ⚠️  {msg}")

        if dry_run:
            return

        create_migration_tables(conn.cursor())
        n_emp = write_employees(conn, employees)
        n_shifts = write_shifts(conn, shifts)
        n_checks = write_check_filling(conn, check_rows)
        n_dismissed = mark_dismissed(conn, dismissed_ids, now_iso)
        conn.commit()
        print(f"\nЗаписано: employees={n_emp}, shifts={n_shifts} "
              f"(существующие с source!='import' не тронуты), "
              f"check_filling={n_checks}, помечено dismissed={n_dismissed}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Одноразовый импорт Google Sheets → SQLite")
    parser.add_argument("--dry-run", action="store_true",
                        help="полный прогон со статистикой, без записи в БД")
    parser.add_argument("--db-path", default="data/bot.db", help="путь к SQLite БД")
    args = parser.parse_args()

    try:
        run_import(args.db_path, args.dry_run)
    except Exception:
        logger.exception("Импорт завершился с ошибкой")
        sys.exit(1)


if __name__ == "__main__":
    main()
