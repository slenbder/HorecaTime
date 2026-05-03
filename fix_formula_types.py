#!/usr/bin/env python3
"""
fix_formula_types.py — исправляет тип формул (простая vs сложная) в месячном листе.

Проблема: после monthly_switch некоторые строки получают неправильный тип формулы.
Например, "Горячий цех" (simple) имеет сложную формулу со "/".

Позиции читаются из Техлиста (source of truth), т.к. SQLite не хранит поле position.
Применяет исправления сразу (без dry-run), предварительно создаёт backup.

Использование:
  python fix_formula_types.py
  python fix_formula_types.py --sheet-name "Апрель 2026"
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import gspread

sys.path.insert(0, str(Path(__file__).parent))
from app.services.google_sheets import GoogleSheetsClient, TECH_SHEET_NAME
from app.scheduler.monthly_switch import _SIMPLE_H_POSITIONS, _make_formulas

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = Path("logs/fix_formula_types.log")
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
logger = logging.getLogger("fix_formula_types")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIRST_DATA_ROW = 5
COL_A = 0   # ФИО (0-indexed)
COL_B = 1   # telegram_id
COL_S = 18  # S
COL_AJ = 35 # AJ
COL_AK = 36 # AK

TECH_COL_TG_ID   = 0  # A в Техлисте
TECH_COL_POSITION = 4  # E в Техлисте


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_techlist_positions(client: GoogleSheetsClient) -> dict[int, str]:
    """Читает Техлист и возвращает {telegram_id: position}."""
    try:
        tech_ws = client._spreadsheet.worksheet(TECH_SHEET_NAME)
        rows = tech_ws.get_all_values()
    except Exception as e:
        logger.error("Не удалось прочитать Техлист '%s': %s", TECH_SHEET_NAME, e)
        sys.exit(1)

    result: dict[int, str] = {}
    for row in rows[1:]:
        if not row:
            continue
        tg_raw = row[TECH_COL_TG_ID].strip() if len(row) > TECH_COL_TG_ID else ""
        if not tg_raw or not tg_raw.lstrip("-").isdigit():
            continue
        position = row[TECH_COL_POSITION].strip() if len(row) > TECH_COL_POSITION else ""
        result[int(tg_raw)] = position

    logger.info("Техлист загружен: %d записей", len(result))
    return result


def _pad_row(row: list, min_len: int) -> list:
    return row + [""] * max(0, min_len - len(row))


def _is_complex_formula(formula: str) -> bool:
    """Сложная формула содержит ЛЕВСИМВ (разбор "/" формата H/AH)."""
    return "ЛЕВСИМВ" in formula


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Исправить тип формул (простая/сложная) в месячном листе"
    )
    parser.add_argument("--sheet-name", default="Май 2026", help="Название листа")
    args = parser.parse_args()

    sheet_name = args.sheet_name

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

    techlist = _load_techlist_positions(client)

    try:
        all_values = ws.get_all_values()
    except Exception as e:
        logger.error("Ошибка чтения данных листа: %s", e)
        sys.exit(1)

    last_row = len(all_values)

    try:
        formula_data = ws.get(f"A1:AK{last_row}", value_render_option="FORMULA")
    except Exception as e:
        logger.error("Не удалось прочитать формулы: %s", e)
        sys.exit(1)

    # Анализируем строки
    total = 0
    to_fix: list[tuple[int, str, str, str, str, str]] = []
    # (row_idx, name, position, new_s, new_aj, new_ak)

    for i, row in enumerate(all_values):
        row_idx = i + 1
        if row_idx < FIRST_DATA_ROW:
            continue

        row = _pad_row(row, COL_AK + 1)

        tg_id_str = row[COL_B].strip()
        if not tg_id_str or not tg_id_str.lstrip("-").isdigit():
            continue

        tg_id = int(tg_id_str)
        name = row[COL_A].strip() or f"tg={tg_id_str}"

        if tg_id not in techlist:
            logger.warning(
                "Строка %d (%s): tg_id=%d не найден в Техлисте, пропускаем",
                row_idx, name, tg_id,
            )
            continue

        position = techlist[tg_id]
        if not position:
            logger.warning("Строка %d (%s): position пуста в Техлисте", row_idx, name)
            continue

        total += 1

        frow = _pad_row(formula_data[i] if i < len(formula_data) else [], COL_AK + 1)
        cur_s = frow[COL_S]

        should_be_simple = position in _SIMPLE_H_POSITIONS
        currently_complex = _is_complex_formula(cur_s)

        if should_be_simple == (not currently_complex):
            # Тип формулы уже правильный
            continue

        direction = "сложная → простая" if should_be_simple else "простая → сложная"
        logger.info("Строка %d (%s, %s): %s", row_idx, name, position, direction)

        new_s, new_aj, new_ak = _make_formulas(row_idx, position)
        to_fix.append((row_idx, name, position, new_s, new_aj, new_ak))

    print()
    print("====== ОТЧЁТ ======")
    print(f"Лист: {sheet_name}")
    print(f"Проверено строк: {total}")
    print(f"Неверный тип формулы: {len(to_fix)}")

    if not to_fix:
        logger.info("Все типы формул корректны. Нечего исправлять.")
        sys.exit(0)

    for row_idx, name, position, *_ in to_fix:
        should_be_simple = position in _SIMPLE_H_POSITIONS
        direction = "сложная → простая" if should_be_simple else "простая → сложная"
        print(f"  Строка {row_idx}: {name} ({position}) — {direction}")

    # Backup перед изменениями
    backup_name = f"{sheet_name} (backup formula-types {date.today().isoformat()})"
    logger.info("Создаём backup: '%s'", backup_name)
    try:
        client._spreadsheet.duplicate_sheet(
            source_sheet_id=ws.id,
            new_sheet_name=backup_name,
        )
        logger.info("Backup создан: '%s'", backup_name)
    except Exception as e:
        logger.error("Не удалось создать backup: %s", e)
        sys.exit(1)

    # batch_update
    updates = []
    for row_idx, _name, _pos, new_s, new_aj, new_ak in to_fix:
        updates.append({"range": f"S{row_idx}",  "values": [[new_s]]})
        updates.append({"range": f"AJ{row_idx}", "values": [[new_aj]]})
        updates.append({"range": f"AK{row_idx}", "values": [[new_ak]]})

    logger.info("Применяем %d исправлений (%d ячеек)...", len(to_fix), len(updates))
    try:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    except Exception as e:
        logger.error("Ошибка batch_update: %s", e)
        sys.exit(1)

    print()
    print(f"✅ Исправлено строк: {len(to_fix)}")
    print(f"Резервная копия: '{backup_name}'")


if __name__ == "__main__":
    main()
