#!/usr/bin/env python3
"""
fix_date_cells.py — исправление ячеек, где числа (часы смен) были интерпретированы
Google Sheets как даты в колонках D-R и T-AI.

Использование:
  python fix_date_cells.py                               # dry-run (только показать)
  python fix_date_cells.py --apply                       # применить изменения
  python fix_date_cells.py --sheet-name "Апрель 2026" --apply
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

import gspread

sys.path.insert(0, str(Path(__file__).parent))
from app.services.google_sheets import GoogleSheetsClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = Path("logs/fix_date_cells.log")
LOG_PATH.parent.mkdir(exist_ok=True)

_fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=_fmt,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("fix_date_cells")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIRST_DATA_ROW = 5
DATE_MIN = 40000  # нижняя граница диапазона дат (~2009)
DATE_MAX = 60000  # верхняя граница диапазона дат (~2064)
EXCEL_EPOCH = datetime(1899, 12, 30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col_num_to_letter(n: int) -> str:
    """1-indexed column number → буква(ы) колонки (1=A, 26=Z, 27=AA, ...)."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _serial_to_hours(serial: float) -> str:
    """
    Конвертирует числовой формат даты Google Sheets обратно в часы.

    Логика: день месяца из даты = целая часть часов,
    дробная часть серийного числа = дробная часть часов.
    """
    dt = EXCEL_EPOCH + timedelta(days=serial)
    day = dt.day
    fractional = round(serial - int(serial), 6)
    if fractional > 0:
        hours = day + fractional
        return f"{hours:g}"
    return str(day)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Исправить ячейки с датами (часы смен) в колонках D-R и T-AI"
    )
    parser.add_argument("--sheet-name", default="Май 2026", help="Название листа")
    parser.add_argument(
        "--apply", action="store_true",
        help="Применить изменения (по умолчанию: dry-run)"
    )
    args = parser.parse_args()

    sheet_name = args.sheet_name
    dry_run = not args.apply

    if dry_run:
        logger.info("=== DRY-RUN (запустите с --apply чтобы применить) ===")
    else:
        logger.info("=== APPLY mode ===")

    try:
        client = GoogleSheetsClient()
    except Exception as e:
        logger.error("Не удалось инициализировать GoogleSheetsClient: %s", e)
        sys.exit(1)

    try:
        ws = client._spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.error("Лист '%s' не найден в таблице", sheet_name)
        sys.exit(1)
    except Exception as e:
        logger.error("Ошибка открытия листа '%s': %s", sheet_name, e)
        sys.exit(1)

    logger.info("Открыт лист: '%s'", sheet_name)

    # Определяем последнюю строку
    try:
        all_values = ws.get_all_values()
    except Exception as e:
        logger.error("Ошибка чтения данных листа: %s", e)
        sys.exit(1)

    last_row = len(all_values)
    if last_row < FIRST_DATA_ROW:
        logger.info("Нет строк данных (last_row=%d)", last_row)
        sys.exit(0)

    logger.info("Последняя строка: %d", last_row)

    # Шаг 1: Загружаем диапазоны с UNFORMATTED_VALUE (числа, не строки)
    try:
        data_d_r = ws.get(
            f"D{FIRST_DATA_ROW}:R{last_row}",
            value_render_option="UNFORMATTED_VALUE",
        )
    except Exception as e:
        logger.error("Ошибка чтения диапазона D:R: %s", e)
        sys.exit(1)

    try:
        data_t_ai = ws.get(
            f"T{FIRST_DATA_ROW}:AI{last_row}",
            value_render_option="UNFORMATTED_VALUE",
        )
    except Exception as e:
        logger.error("Ошибка чтения диапазона T:AI: %s", e)
        sys.exit(1)

    # Шаг 2: Детектируем ячейки с датами
    total_checked = 0
    fixes: list[tuple[str, float, str]] = []  # (cell_addr, original, corrected)
    warnings_count = 0

    ranges_info = [
        (4, data_d_r),   # D = колонка 4
        (20, data_t_ai), # T = колонка 20
    ]

    for range_start_col, data in ranges_info:
        for row_offset, row in enumerate(data):
            actual_row = FIRST_DATA_ROW + row_offset
            for col_offset, val in enumerate(row):
                actual_col = range_start_col + col_offset
                cell_addr = f"{_col_num_to_letter(actual_col)}{actual_row}"
                total_checked += 1

                # Пропускаем пустые ячейки
                if val == "" or val is None:
                    continue

                # Пропускаем строки (включая формат "H/AH")
                if isinstance(val, str):
                    continue

                # Пропускаем булевы значения
                if isinstance(val, bool):
                    continue

                # Обрабатываем только числа
                if not isinstance(val, (int, float)):
                    continue

                float_val = float(val)

                # Корректные часы (< DATE_MIN) → пропускаем
                if float_val <= DATE_MIN:
                    continue

                # Неожиданно большие значения → предупреждение, пропускаем
                if float_val >= DATE_MAX:
                    logger.warning(
                        "Ячейка %s: значение %.6g >= %d, пропускаем",
                        cell_addr, float_val, DATE_MAX,
                    )
                    warnings_count += 1
                    continue

                # Это серийный номер даты Google Sheets
                try:
                    corrected = _serial_to_hours(float_val)
                except Exception as e:
                    logger.warning(
                        "Ошибка конвертации %s=%s: %s, пропускаем",
                        cell_addr, val, e,
                    )
                    continue

                logger.info("Ячейка %s: %s (дата) → %s (часы)", cell_addr, val, corrected)
                fixes.append((cell_addr, float_val, corrected))

    # Шаг 3: Отчёт
    print()
    print("====== ОТЧЁТ ======")
    print(f"Лист: {sheet_name}")
    print(f"Проверено ячеек: {total_checked}")
    print(f"Исправлено (даты → часы): {len(fixes)}")
    if warnings_count:
        print(f"Предупреждения (пропущено): {warnings_count}")

    if fixes:
        print()
        print("Примеры исправлений:")
        for cell_addr, orig, corrected in fixes[:10]:
            print(f"  {cell_addr}: {orig} → {corrected}")
        if len(fixes) > 10:
            print(f"  ... и ещё {len(fixes) - 10} ячеек")

    if not fixes:
        logger.info("Нет ячеек для исправления.")
        sys.exit(0)

    if dry_run:
        print()
        print("DRY-RUN: изменения не применены. Запустите с --apply для применения.")
        sys.exit(0)

    # Шаг 4: Резервная копия
    backup_name = f"{sheet_name} (backup dates {date.today().isoformat()})"
    logger.info("Создаём резервную копию: '%s'", backup_name)
    try:
        client._spreadsheet.duplicate_sheet(
            source_sheet_id=ws.id,
            new_sheet_name=backup_name,
        )
        logger.info("Резервная копия создана: '%s'", backup_name)
    except Exception as e:
        logger.error("Не удалось создать резервную копию: %s", e)
        sys.exit(1)

    # Шаг 5: Применяем исправления одним batch_update
    updates = [
        {"range": cell_addr, "values": [[corrected]]}
        for cell_addr, _, corrected in fixes
    ]

    logger.info("Применяем %d исправлений...", len(fixes))
    try:
        ws.batch_update(updates, value_input_option="RAW")
        logger.info("Готово. %d ячеек исправлено.", len(fixes))
    except Exception as e:
        logger.error("Ошибка batch_update: %s", e)
        sys.exit(1)

    print()
    print(f"Применено: {len(fixes)} ячеек исправлено.")
    print(f"Резервная копия: '{backup_name}'")


if __name__ == "__main__":
    main()
