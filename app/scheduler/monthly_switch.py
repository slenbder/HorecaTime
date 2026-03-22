import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from config import SUPERADMIN_IDS, DEVELOPER_ID, DB_PATH
from app.services.google_sheets import MONTH_NAMES_RU
from app.db.models import get_all_users

logger = logging.getLogger("app")
error_logger = logging.getLogger("errors")

_SIMPLE_H_POSITIONS = {
    "Су-шеф", "Горячий цех", "Холодный цех", "Кондитерский цех",
    "Заготовочный цех", "Коренной цех", "МОП", "Хостесс", "Менеджер",
}


def get_next_sheet_name() -> tuple[str, int, int]:
    """Returns (sheet_name, month, year) for the next month."""
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if now.month == 12:
        return f"{MONTH_NAMES_RU[1]} {now.year + 1}", 1, now.year + 1
    m = now.month + 1
    return f"{MONTH_NAMES_RU[m]} {now.year}", m, now.year


def _get_current_sheet_name() -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    return f"{MONTH_NAMES_RU[now.month]} {now.year}"


def _make_formulas(r: int, position: str) -> tuple[str, str, str]:
    """Returns (formula_s, formula_aj, formula_ak) for the given row number."""
    if position in _SIMPLE_H_POSITIONS:
        formula_s = f'=SUMPRODUCT(IF(D{r}:R{r}="";0;IFERROR(VALUE(D{r}:R{r});0)))'
        formula_aj = f'=SUMPRODUCT(IF(T{r}:AI{r}="";0;IFERROR(VALUE(T{r}:AI{r});0)))'
        formula_ak = f'=S{r}+AJ{r}'
    else:
        formula_s = (
            f'=SUMPRODUCT(IF(D{r}:R{r}="";0;IF(ISNUMBER(FIND("/";D{r}:R{r}));'
            f'IFERROR(VALUE(LEFT(D{r}:R{r};FIND("/";D{r}:R{r})-1));0);'
            f'IFERROR(VALUE(D{r}:R{r});0))))&"/"&'
            f'SUMPRODUCT(IF(ISNUMBER(FIND("/";D{r}:R{r}));'
            f'IFERROR(VALUE(MID(D{r}:R{r};FIND("/";D{r}:R{r})+1;100));0);0))'
        )
        formula_aj = (
            f'=SUMPRODUCT(IF(T{r}:AI{r}="";0;IF(ISNUMBER(FIND("/";T{r}:AI{r}));'
            f'IFERROR(VALUE(LEFT(T{r}:AI{r};FIND("/";T{r}:AI{r})-1));0);'
            f'IFERROR(VALUE(T{r}:AI{r});0))))&"/"&'
            f'SUMPRODUCT(IF(ISNUMBER(FIND("/";T{r}:AI{r}));'
            f'IFERROR(VALUE(MID(T{r}:AI{r};FIND("/";T{r}:AI{r})+1;100));0);0))'
        )
        formula_ak = (
            f'=(VALUE(LEFT(S{r};FIND("/";S{r})-1))+VALUE(LEFT(AJ{r};FIND("/";AJ{r})-1)))'
            f'&"/"&'
            f'(VALUE(MID(S{r};FIND("/";S{r})+1;100))+VALUE(MID(AJ{r};FIND("/";AJ{r})+1;100)))'
        )
    return formula_s, formula_aj, formula_ak


async def switch_month(bot: Bot, sheets_client, db_path: str) -> dict:
    """
    Main monthly switch function. Called by the scheduler on the 1st at 18:00 MSK.

    Algorithm:
    a) Determine current and next sheet names.
    b) Duplicate current sheet as next month.
    c) Update C2 (month name) and T2 (year) in the new sheet.
    d) Get all rows from the new sheet.
    e) For each employee row (B not empty): check dismissed status and techlist.
    f) Clear shift data for active employees, delete dismissed rows (bottom-up).
    g) Log summary.

    Returns:
        {old_sheet, new_sheet, transferred, removed, anomalies}
    """
    current_name = _get_current_sheet_name()
    next_name, next_month, next_year = get_next_sheet_name()

    logger.info("switch_month: начинаю переключение '%s' → '%s'", current_name, next_name)

    transferred = 0
    removed = 0
    anomalies = 0

    try:
        # Step a/b: Duplicate current sheet
        try:
            source_ws = sheets_client._spreadsheet.worksheet(current_name)
        except Exception as e:
            logger.warning("switch_month: реконнект перед копированием: %s", e)
            sheets_client._reconnect()
            source_ws = sheets_client._spreadsheet.worksheet(current_name)

        try:
            new_ws = sheets_client._spreadsheet.duplicate_sheet(
                source_sheet_id=source_ws.id,
                new_sheet_name=next_name,
            )
            logger.info("switch_month: лист '%s' скопирован как '%s'", current_name, next_name)
        except Exception as dup_err:
            # Sheet may already exist (re-run scenario)
            logger.warning("switch_month: duplicate_sheet ошибка: %s — пробуем использовать существующий", dup_err)
            try:
                new_ws = sheets_client._spreadsheet.worksheet(next_name)
                logger.warning("switch_month: используем существующий лист '%s'", next_name)
            except Exception:
                raise dup_err

        # Step c: Update C2 (month name) and T2 (year)
        new_ws.update_cell(2, 3, MONTH_NAMES_RU[next_month])
        new_ws.update_cell(2, 20, next_year)
        logger.info(
            "switch_month: обновлены C2='%s', T2=%d в листе '%s'",
            MONTH_NAMES_RU[next_month], next_year, next_name,
        )

        # Step d: Get all rows from new sheet
        all_values = new_ws.get_all_values()

        # Step e: Get dismissed rows (red background in col A)
        dismissed_rows = sheets_client.get_dismissed_rows(next_name)
        logger.info(
            "switch_month: обнаружено %d красных строк в '%s'",
            len(dismissed_rows), next_name,
        )

        # Identify employee rows (B column = telegram_id, not empty)
        employee_rows: list[tuple[int, int, str]] = []
        for i, row in enumerate(all_values, start=1):
            if len(row) < 2 or not str(row[1]).strip():
                continue
            tg_id_str = str(row[1]).strip()
            if not tg_id_str.lstrip("-").isdigit():
                continue
            tg_id = int(tg_id_str)
            position = str(row[2]).strip() if len(row) >= 3 else ""
            employee_rows.append((i, tg_id, position))

        rows_to_delete: list[int] = []
        rows_to_clear: list[tuple[int, str]] = []

        for row_idx, tg_id, position in employee_rows:
            is_red = row_idx in dismissed_rows
            in_techlist = sheets_client.user_exists_in_techlist(tg_id)

            if is_red and not in_techlist:
                # Normal dismissal
                rows_to_delete.append(row_idx)
                removed += 1
            elif is_red and in_techlist:
                # Anomaly: marked dismissed but still in techlist
                logger.warning(
                    "switch_month: аномалия — telegram_id=%s красный, но есть в Техлисте. Удаляем.",
                    tg_id,
                )
                anomalies += 1
                rows_to_delete.append(row_idx)
                removed += 1
            elif not is_red and not in_techlist:
                # Anomaly: not red but missing from techlist
                logger.warning(
                    "switch_month: аномалия — telegram_id=%s не в Техлисте, но ячейка не красная. Удаляем.",
                    tg_id,
                )
                anomalies += 1
                rows_to_delete.append(row_idx)
                removed += 1
            else:
                # Active employee
                rows_to_clear.append((row_idx, position))
                transferred += 1

        # Step f (part 1): Clear shift data for active employees, re-insert formulas
        # Do this BEFORE deleting rows to preserve correct indices
        for row_idx, position in rows_to_clear:
            try:
                new_ws.batch_clear([
                    f"D{row_idx}:R{row_idx}",
                    f"T{row_idx}:AI{row_idx}",
                ])
                formula_s, formula_aj, formula_ak = _make_formulas(row_idx, position)
                new_ws.batch_update(
                    [
                        {"range": f"S{row_idx}", "values": [[formula_s]]},
                        {"range": f"AJ{row_idx}", "values": [[formula_aj]]},
                        {"range": f"AK{row_idx}", "values": [[formula_ak]]},
                    ],
                    value_input_option="USER_ENTERED",
                )
                logger.info(
                    "switch_month: очищены смены для строки %d (позиция=%s)",
                    row_idx, position,
                )
            except Exception as e:
                logger.error(
                    "switch_month: ошибка очистки строки %d: %s", row_idx, e
                )

        # Step f (part 2): Delete dismissed rows bottom-up
        for row_idx in sorted(rows_to_delete, reverse=True):
            try:
                new_ws.delete_rows(row_idx)
                logger.info("switch_month: удалена строка %d из '%s'", row_idx, next_name)
            except Exception as e:
                logger.error(
                    "switch_month: ошибка удаления строки %d: %s", row_idx, e
                )

        result = {
            "old_sheet": current_name,
            "new_sheet": next_name,
            "transferred": transferred,
            "removed": removed,
            "anomalies": anomalies,
        }

        # Step g: Log summary
        logger.info(
            "switch_month: завершено. Лист='%s', перенесено=%d, удалено=%d, аномалий=%d",
            next_name, transferred, removed, anomalies,
        )
        return result

    except Exception as e:
        error_logger.exception("switch_month: критическая ошибка: %s", e)
        try:
            await bot.send_message(
                DEVELOPER_ID,
                f"🔴 Критическая ошибка переключения месяца!\n\n"
                f"{type(e).__name__}: {e}",
            )
        except Exception:
            error_logger.exception("switch_month: не удалось отправить алерт разработчику")
        raise


async def notify_upcoming_switch(bot: Bot, db_path: str) -> None:
    """
    Sends a reminder 6 hours before the monthly switch (1st of month, 12:00 MSK).
    """
    logger.info("notify_upcoming_switch: рассылка напоминаний о переключении месяца")

    users = await get_all_users(db_path)
    recipients = list({u["telegram_id"] for u in users} | set(SUPERADMIN_IDS))

    text = (
        "⏰ Напоминание\n\n"
        "Сегодня в 18:00 произойдёт автоматическое переключение на новый месяц.\n\n"
        "Убедитесь что все смены за текущий месяц внесены!"
    )

    sent = 0
    for tg_id in recipients:
        try:
            await bot.send_message(tg_id, text)
            sent += 1
        except Exception as e:
            logger.warning(
                "notify_upcoming_switch: не удалось отправить %s: %s", tg_id, e
            )
        await asyncio.sleep(0.05)

    logger.info("notify_upcoming_switch: отправлено %d/%d уведомлений", sent, len(recipients))


async def notify_switch_done(bot: Bot, db_path: str, result: dict) -> None:
    """
    Sends a notification after the monthly switch is complete.
    """
    logger.info("notify_switch_done: рассылка уведомлений о переключении месяца")

    users = await get_all_users(db_path)
    recipients = list({u["telegram_id"] for u in users} | set(SUPERADMIN_IDS))

    text = (
        f"✅ Месяц переключён\n\n"
        f"{result['new_sheet']} — новый рабочий месяц начался.\n"
        f"Удачной работы! 🚀"
    )

    sent = 0
    for tg_id in recipients:
        try:
            await bot.send_message(tg_id, text)
            sent += 1
        except Exception as e:
            logger.warning(
                "notify_switch_done: не удалось отправить %s: %s", tg_id, e
            )
        await asyncio.sleep(0.05)

    logger.info("notify_switch_done: отправлено %d/%d уведомлений", sent, len(recipients))
