#!/usr/bin/env python3
"""
fix_telegram_ids.py — исправление telegram_id в месячном листе по данным Техлиста.

Использование:
  python fix_telegram_ids.py                          # dry-run (только показать)
  python fix_telegram_ids.py --apply                  # применить изменения
  python fix_telegram_ids.py --sheet-name "Апрель 2026" --apply
"""
import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

sys.path.insert(0, str(Path(__file__).parent))
from config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, TECH_SHEET_NAME

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_PATH = Path("logs/fix_telegram_ids.log")
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
logger = logging.getLogger("fix_tg_ids")


# ---------------------------------------------------------------------------
# Google Sheets connection
# ---------------------------------------------------------------------------

def _get_client() -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        GOOGLE_CREDENTIALS_PATH, scopes
    )
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_techlist(
    ss: gspread.Spreadsheet,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """
    Читает Техлист и строит два маппинга:
      id_to_name:  tg_id_str → canonical_fio
      name_to_ids: fio_lower → [tg_id_str, ...]   (список для детектирования дублей)
    """
    ws = ss.worksheet(TECH_SHEET_NAME)
    rows = ws.get_all_values()

    id_to_name: dict[str, str] = {}
    name_to_ids: dict[str, list[str]] = {}

    for r in rows[1:]:  # строка 0 — заголовок
        tg_id = r[0].strip() if len(r) > 0 else ""
        fio   = r[2].strip() if len(r) > 2 else ""
        if not tg_id or not tg_id.lstrip("-").isdigit() or not fio:
            continue
        id_to_name[tg_id] = fio
        name_to_ids.setdefault(fio.lower(), []).append(tg_id)

    logger.info("Техлист загружен: %d записей", len(id_to_name))
    return id_to_name, name_to_ids


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(
    ws: gspread.Worksheet,
    id_to_name: dict[str, str],
    name_to_ids: dict[str, list[str]],
) -> tuple[list[dict], int, int]:
    """
    Проходит по всем строкам листа.

    Returns:
        fixes       — список { row, display_name, current_tg_id, current_owner, correct_tg_id }
        ok_count    — строк с корректным соответствием
        error_count — строк, пропущенных из-за ошибки (фантом / дубль ФИО)
    """
    rows = ws.get_all_values()
    fixes: list[dict] = []
    ok_count = 0
    error_count = 0

    logger.info("Анализ листа '%s': %d строк", ws.title, len(rows))

    for i, r in enumerate(rows):
        row_num      = i + 1
        display_name = r[0].strip() if len(r) > 0 else ""
        current_tg   = r[1].strip() if len(r) > 1 else ""

        # Строки без числового TG_ID — заголовки секций, разделители, пустые
        if not current_tg or not current_tg.lstrip("-").isdigit():
            continue
        if not display_name:
            continue

        # Проверка 1: TG_ID вообще есть в Техлисте?
        if current_tg not in id_to_name:
            logger.error(
                "Строка %d: TG_ID %s (%r) не найден в Техлисте — ФАНТОМ",
                row_num, current_tg, display_name,
            )
            error_count += 1
            continue

        # Проверка 2: ФИО совпадает с владельцем TG_ID?
        correct_name = id_to_name[current_tg]
        if display_name.lower() == correct_name.lower():
            ok_count += 1
            continue

        # Несоответствие — ищем правильный TG_ID для этого ФИО
        candidates = name_to_ids.get(display_name.lower(), [])

        if not candidates:
            logger.error(
                "Строка %d: ФИО %r не найдено в Техлисте "
                "(TG_ID %s принадлежит %r) — невозможно исправить автоматически",
                row_num, display_name, current_tg, correct_name,
            )
            error_count += 1
            continue

        if len(candidates) > 1:
            logger.warning(
                "Строка %d: ФИО %r даёт %d совпадений в Техлисте %s — ПРОПУСК",
                row_num, display_name, len(candidates), candidates,
            )
            error_count += 1
            continue

        correct_tg = candidates[0]
        fixes.append({
            "row":           row_num,
            "display_name":  display_name,
            "current_tg_id": current_tg,
            "current_owner": correct_name,
            "correct_tg_id": correct_tg,
        })

    return fixes, ok_count, error_count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_fixes(fixes: list[dict]) -> None:
    if not fixes:
        logger.info("Несоответствий, поддающихся автоисправлению, не найдено.")
        return
    logger.info("Найдено исправимых несоответствий: %d", len(fixes))
    for f in fixes:
        logger.info(
            "Строка %d: %s\n"
            "    Сейчас: %s (принадлежит '%s') ❌\n"
            "    Будет:  %s (принадлежит '%s') ✅",
            f["row"], f["display_name"],
            f["current_tg_id"], f["current_owner"],
            f["correct_tg_id"], f["display_name"],
        )


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_sheet(ss: gspread.Spreadsheet, ws: gspread.Worksheet) -> str:
    today = date.today().strftime("%Y-%m-%d")
    backup_name = f"{ws.title} (backup {today})"

    existing_titles = [s.title for s in ss.worksheets()]
    if backup_name in existing_titles:
        logger.info("Backup '%s' уже существует — пропуск", backup_name)
        return backup_name

    try:
        ss.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=backup_name)
        logger.info("Backup создан: '%s'", backup_name)
    except Exception as e:
        logger.error("Не удалось создать backup: %s", e, exc_info=True)
        raise

    return backup_name


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_fixes(ws: gspread.Worksheet, fixes: list[dict]) -> int:
    """Обновляет колонку B для всех несоответствий одним batch_update."""
    if not fixes:
        return 0

    updates = [
        {"range": f"B{f['row']}", "values": [[f["correct_tg_id"]]]}
        for f in fixes
    ]

    try:
        ws.batch_update(updates, value_input_option="RAW")
        logger.info(
            "batch_update применён: %d/%d ячеек обновлено",
            len(updates), len(fixes),
        )
    except Exception as e:
        logger.error("Ошибка batch_update: %s", e, exc_info=True)
        raise

    return len(updates)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Исправляет telegram_id в месячном листе по данным Техлиста",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python fix_telegram_ids.py\n"
            "  python fix_telegram_ids.py --apply\n"
            "  python fix_telegram_ids.py --sheet-name 'Апрель 2026' --apply\n"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Применить изменения (по умолчанию dry-run)",
    )
    parser.add_argument(
        "--sheet-name",
        default="Май 2026",
        metavar="NAME",
        help="Название листа для проверки (по умолчанию: 'Май 2026')",
    )
    args = parser.parse_args()
    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    logger.info("=" * 60)
    logger.info("fix_telegram_ids.py | режим: %s | лист: %r", mode, args.sheet_name)
    logger.info("=" * 60)

    # Подключение
    try:
        gc = _get_client()
        ss = gc.open_by_key(SPREADSHEET_ID)
        logger.info("Подключение к таблице: OK")
    except Exception as e:
        logger.error("Ошибка подключения к Google Sheets: %s", e)
        sys.exit(1)

    # Техлист
    try:
        id_to_name, name_to_ids = load_techlist(ss)
    except Exception as e:
        logger.error("Ошибка загрузки Техлиста: %s", e)
        sys.exit(1)

    # Целевой лист
    try:
        ws = ss.worksheet(args.sheet_name)
        logger.info(
            "Лист '%s' открыт (%d строк, %d столбцов)",
            ws.title, ws.row_count, ws.col_count,
        )
    except gspread.WorksheetNotFound:
        logger.error("Лист '%s' не найден в таблице", args.sheet_name)
        sys.exit(1)

    # Анализ
    fixes, ok_count, error_count = analyse(ws, id_to_name, name_to_ids)
    print_fixes(fixes)

    updated_count = 0

    if dry_run:
        logger.info(
            "DRY RUN: изменения НЕ применены. "
            "Используйте --apply для реального обновления."
        )
    else:
        if fixes:
            try:
                backup_sheet(ss, ws)
            except Exception:
                logger.error(
                    "Прерывание: backup не создан, изменения не применяются"
                )
                sys.exit(1)
            updated_count = apply_fixes(ws, fixes)
        else:
            logger.info("Нет исправимых несоответствий — изменения не нужны.")

    # Финальный отчёт
    total = ok_count + len(fixes) + error_count
    logger.info("")
    logger.info("====== ОТЧЁТ ======")
    logger.info("Лист:                   %s", args.sheet_name)
    logger.info("Режим:                  %s", mode)
    logger.info("Проверено строк:        %d", total)
    logger.info("✅ OK (совпадают):       %d", ok_count)
    logger.info("⚠️  MISMATCH:            %d", len(fixes))
    logger.info("🔴 ERROR/ПРОПУСК:        %d", error_count)
    if not dry_run:
        logger.info("Изменено строк:         %d", updated_count)
    logger.info("===================")

    if error_count:
        logger.warning(
            "ВНИМАНИЕ: %d строк пропущено (фантомы или ФИО не в Техлисте) "
            "— проверьте вручную",
            error_count,
        )


if __name__ == "__main__":
    main()
