#!/usr/bin/env python3
"""
set_plain_text_format.py — устанавливает формат "Plain text" для колонок D-AK
в месячном листе Google Sheets.

Решает проблему: ячейки с датовым форматом хранят "8.5" как серийный номер 46150,
из-за чего формулы СУММПРОИЗВ получают 46150 вместо 8.5.

Использование:
  python set_plain_text_format.py
  python set_plain_text_format.py --sheet-name "Апрель 2026"
"""
import argparse
import logging
import sys
from pathlib import Path

import gspread

sys.path.insert(0, str(Path(__file__).parent))
from app.services.google_sheets import GoogleSheetsClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = Path("logs/set_plain_text_format.log")
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
logger = logging.getLogger("set_plain_text_format")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Установить формат Plain text для колонок D-AK в месячном листе"
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

    sheet_id = ws._properties.get("sheetId")
    if sheet_id is None:
        logger.error("Не удалось получить sheetId для листа '%s'", sheet_name)
        sys.exit(1)

    logger.info("Открыт лист: '%s' (sheetId=%s)", sheet_name, sheet_id)
    logger.info("Устанавливаем Plain text формат для D-AK (все строки)...")

    format_request = {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,       # все строки от 0
                        "startColumnIndex": 3,    # D (A=0, B=1, C=2, D=3)
                        "endColumnIndex": 37,     # AK+1 (AK=36, exclusive end=37)
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "TEXT"
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        ]
    }

    try:
        client._spreadsheet.batch_update(format_request)
        logger.info("Формат Plain text применён к колонкам D-AK")
    except Exception as e:
        logger.error("Ошибка применения формата: %s", e, exc_info=True)
        sys.exit(1)

    print()
    print(f"✅ Формат \"Plain text\" установлен для колонок D-AK")
    print(f"Лист: {sheet_name}")
    print(f"Диапазон: D1:AK (все строки)")
    print()
    print("ВАЖНО: Откройте Google Sheets и пересчитайте формулы:")
    print("  1. Ctrl+A (выделить всё)")
    print("  2. Ctrl+H (Find & Replace)")
    print("  3. Find: =СУММПРОИЗВ")
    print("  4. Replace: =СУММПРОИЗВ")
    print("  5. Replace all")


if __name__ == "__main__":
    main()
