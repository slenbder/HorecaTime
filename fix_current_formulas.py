"""
Массово обновляет формулы S/AJ/AK в указанном месячном листе.

По умолчанию работает в dry-run режиме — только показывает, что изменится.
Для реального применения: python fix_current_formulas.py --apply

Использует _make_formulas() из monthly_switch, чтобы формулы были идентичны
тем, что вставляются при switch_month().

Позиция сотрудника берётся из Техлиста (базовая, например "Холодный цех"),
а не из колонки C месячного листа (где хранится custom_position — "Повар").
"""
import argparse
import logging
import sys
from datetime import date

import gspread

from app.services.google_sheets import GoogleSheetsClient, POSITION_TO_SECTION, TECH_SHEET_NAME
from app.scheduler.monthly_switch import _make_formulas

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FIRST_DATA_ROW = 5  # строки 1-4 — заголовки
COL_A = 0   # ФИО (0-indexed)
COL_B = 1   # telegram_id
COL_S = 18  # колонка S
COL_AJ = 35 # колонка AJ
COL_AK = 36 # колонка AK

# Техлист: колонки (1-indexed → 0-indexed)
TECH_COL_TG_ID   = 0  # колонка A
TECH_COL_POSITION = 4  # колонка E


def _load_techlist_positions(client: GoogleSheetsClient) -> dict[int, str]:
    """Читает Техлист один раз и возвращает словарь {telegram_id: position}."""
    try:
        tech_ws = client._spreadsheet.worksheet(TECH_SHEET_NAME)
        rows = tech_ws.get_all_values()
    except Exception as e:
        logger.error("Не удалось прочитать Техлист '%s': %s", TECH_SHEET_NAME, e)
        sys.exit(1)

    result: dict[int, str] = {}
    for row in rows[1:]:  # пропускаем заголовок
        if not row:
            continue
        tg_raw = row[TECH_COL_TG_ID].strip() if len(row) > TECH_COL_TG_ID else ""
        if not tg_raw or not tg_raw.lstrip("-").isdigit():
            continue
        position = row[TECH_COL_POSITION].strip() if len(row) > TECH_COL_POSITION else ""
        result[int(tg_raw)] = position

    logger.info("Техлист загружен: %d записей", len(result))
    return result


def _read_formulas(ws, last_row: int) -> list[list[str]]:
    """Читает все ячейки листа, возвращая формулы вместо вычисленных значений."""
    try:
        return ws.get(f"A1:AK{last_row}", value_render_option="FORMULA")
    except Exception as e:
        logger.warning("Не удалось получить формулы (FORMULA render): %s. Сравнение отключено.", e)
        return []


def _pad_row(row: list, min_len: int) -> list:
    """Дополняет строку пустыми строками до min_len элементов."""
    return row + [""] * max(0, min_len - len(row))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Обновить формулы S/AJ/AK в месячном листе Google Sheets"
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

    techlist = _load_techlist_positions(client)

    try:
        all_values = ws.get_all_values()
    except Exception as e:
        logger.error("Ошибка чтения данных листа: %s", e)
        sys.exit(1)

    last_row = len(all_values)
    formula_data = _read_formulas(ws, last_row)

    # Анализируем строки
    total = 0
    to_update: list[tuple[int, str, str, str, str, str, str, str, str]] = []
    # (row_idx, name, position, cur_s, cur_aj, cur_ak, new_s, new_aj, new_ak)

    for i, row in enumerate(all_values):
        row_idx = i + 1  # 1-indexed

        if row_idx < FIRST_DATA_ROW:
            continue

        row = _pad_row(row, COL_AK + 1)

        tg_id_str = row[COL_B].strip()
        if not tg_id_str or not tg_id_str.lstrip("-").isdigit():
            continue

        tg_id = int(tg_id_str)
        name = row[COL_A].strip() or f"tg={tg_id_str}"

        # Получаем базовую position из Техлиста
        if tg_id not in techlist:
            logger.warning("Строка %d (%s): tg_id=%d не найден в Техлисте, пропускаем", row_idx, name, tg_id)
            continue

        position = techlist[tg_id]

        if not position:
            logger.error("Строка %d (%s): у tg_id=%d отсутствует position в Техлисте", row_idx, name, tg_id)
            continue

        if position not in POSITION_TO_SECTION:
            logger.error(
                "Строка %d (%s): position '%s' из Техлиста не в POSITION_TO_SECTION — ошибка конфигурации",
                row_idx, name, position,
            )
            continue

        logger.debug("Строка %d (%s): позиция из Техлиста '%s'", row_idx, name, position)

        total += 1

        new_s, new_aj, new_ak = _make_formulas(row_idx, position)

        frow = _pad_row(formula_data[i] if i < len(formula_data) else [], COL_AK + 1)
        cur_s = frow[COL_S]
        cur_aj = frow[COL_AJ]
        cur_ak = frow[COL_AK]

        if cur_s != new_s or cur_aj != new_aj or cur_ak != new_ak:
            to_update.append((row_idx, name, position, cur_s, cur_aj, cur_ak, new_s, new_aj, new_ak))

    # Показываем diff
    if to_update:
        print()
        for row_idx, name, position, cur_s, cur_aj, cur_ak, new_s, new_aj, new_ak in to_update:
            print(f"Строка {row_idx}: {name} (позиция из Техлиста: '{position}')")
            if cur_s != new_s:
                print(f"  S:  {cur_s or '(пусто)'}")
                print(f"  →   {new_s}")
            if cur_aj != new_aj:
                print(f"  AJ: {cur_aj or '(пусто)'}")
                print(f"  →   {new_aj}")
            if cur_ak != new_ak:
                print(f"  AK: {cur_ak or '(пусто)'}")
                print(f"  →   {new_ak}")
            print()

    s_count = sum(1 for r in to_update if r[3] != r[6])
    aj_count = sum(1 for r in to_update if r[4] != r[7])
    ak_count = sum(1 for r in to_update if r[5] != r[8])

    print("====== ОТЧЁТ ======")
    print(f"Лист:             {sheet_name}")
    print(f"Проверено строк:  {total}")
    print(f"Требует правки:   {len(to_update)}")
    print(f"  - S:  {s_count}")
    print(f"  - AJ: {aj_count}")
    print(f"  - AK: {ak_count}")

    if dry_run:
        print("\n[DRY-RUN] Для применения: python fix_current_formulas.py --apply")
        return

    if not to_update:
        print("\nНечего обновлять.")
        return

    # Backup
    backup_name = f"{sheet_name} (backup formulas {date.today()})"
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

    # Собираем batch_update
    updates = []
    for row_idx, name, position, cur_s, cur_aj, cur_ak, new_s, new_aj, new_ak in to_update:
        if cur_s != new_s:
            updates.append({"range": f"S{row_idx}", "values": [[new_s]]})
        if cur_aj != new_aj:
            updates.append({"range": f"AJ{row_idx}", "values": [[new_aj]]})
        if cur_ak != new_ak:
            updates.append({"range": f"AK{row_idx}", "values": [[new_ak]]})

    try:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logger.info("batch_update выполнен: %d ячеек обновлено", len(updates))
    except Exception as e:
        logger.error("Ошибка batch_update: %s", e)
        sys.exit(1)

    print(f"\n✅ Обновлено ячеек: {len(updates)}")
    print(f"  - S:  {s_count}")
    print(f"  - AJ: {aj_count}")
    print(f"  - AK: {ak_count}")


if __name__ == "__main__":
    main()
