#!/usr/bin/env python3
"""
fix_kitchen_formulas_now.py — вставляет простые формулы S/AJ/AK в строки 6-29 (КУХНЯ).

Использование:
  python fix_kitchen_formulas_now.py
  python fix_kitchen_formulas_now.py --sheet-name "Апрель 2026"
"""
import argparse
import logging
import sys
from pathlib import Path

import gspread

sys.path.insert(0, str(Path(__file__).parent))
from app.services.google_sheets import GoogleSheetsClient
from app.scheduler.monthly_switch import _make_formulas

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KITCHEN_START = 6
KITCHEN_END   = 33  # включая Коренной цех (строки 32-33)
# Любая кухонная позиция — все они дают простую формулу без "/"
_KITCHEN_POSITION = "Горячий цех"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Вставить простые формулы S/AJ/AK для строк Кухни"
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
        logger.error("Лист '%s' не найден", sheet_name)
        sys.exit(1)
    except Exception as e:
        logger.error("Ошибка открытия листа '%s': %s", sheet_name, e)
        sys.exit(1)

    logger.info("Исправляем формулы Кухни: строки %d-%d", KITCHEN_START, KITCHEN_END)

    updates = []
    for row in range(KITCHEN_START, KITCHEN_END + 1):
        formula_s, formula_aj, formula_ak = _make_formulas(row, _KITCHEN_POSITION)
        updates.append({"range": f"S{row}",  "values": [[formula_s]]})
        updates.append({"range": f"AJ{row}", "values": [[formula_aj]]})
        updates.append({"range": f"AK{row}", "values": [[formula_ak]]})

    try:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    except Exception as e:
        logger.error("Ошибка batch_update: %s", e)
        sys.exit(1)

    for row in range(KITCHEN_START, KITCHEN_END + 1):
        logger.info("✅ Строка %d", row)

    logger.info("✅ Исправлено %d строк Кухни", KITCHEN_END - KITCHEN_START + 1)


if __name__ == "__main__":
    main()
