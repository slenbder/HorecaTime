import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

import gspread
from gspread.exceptions import WorksheetNotFound
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, TECH_SHEET_NAME

logger = logging.getLogger("google_api")

# Индексы столбцов в Техлисте (1-based)
COL_TELEGRAM_ID    = 1  # A
COL_NICKNAME       = 2  # B
COL_FIO_FROM_USER  = 3  # C
COL_DEPARTMENT     = 4  # D
COL_POSITION       = 5  # E
COL_REGISTERED_AT  = 6  # F
COL_IN_STAFF_TABLE = 7  # G — «ДА» если утверждён в графике

MONTH_NAMES_RU = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

POSITION_TO_SECTION = {
    "Су-шеф": "Руководящий состав",
    "Горячий цех": "Горячий цех",
    "Холодный цех": "Холодный цех",
    "Кондитерский цех": "Кондитерский цех",
    "Заготовочный цех": "Заготовочный цех",
    "Коренной цех": "Коренной цех",
    "МОП": "МОП",
    "Бармен": "Бармены",
    "Барбэк": "Барбэки",
    "Официант": "Официанты",
    "Раннер": "Раннеры",
    "Хостесс": "Хостесс",
    "Менеджер": "Менеджеры",
}

DEPARTMENT_TO_HEADER = {
    "Кухня": "КУХНЯ",
    "Бар": "БАР",
    "Зал": "ЗАЛ",
}

class GoogleSheetsClient:
    def __init__(self) -> None:
        self._client = self._create_client()
        self._spreadsheet = self._client.open_by_key(SPREADSHEET_ID)

    @staticmethod
    def _create_client() -> gspread.Client:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_path = Path(GOOGLE_CREDENTIALS_PATH)
        if not creds_path.exists():
            logger.error("Файл service account не найден: %s", creds_path)
            raise FileNotFoundError(f"Service account JSON not found: {creds_path}")

        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            str(creds_path), scopes
        )
        logger.info("Google Sheets клиент создан, credentials: %s", creds_path)
        return gspread.authorize(credentials)

    # --- Техлист ---

    def _get_techlist_worksheet(self):
        try:
            return self._spreadsheet.worksheet(TECH_SHEET_NAME)
        except Exception as e:
            logger.warning("Ошибка получения листа '%s', пробуем переподключиться: %s", TECH_SHEET_NAME, e)
            self._reconnect()
            return self._spreadsheet.worksheet(TECH_SHEET_NAME)
    
    def _reconnect(self) -> None:
        """Пересоздаёт клиент и подключение к таблице."""
        logger.warning("Переподключение к Google Sheets...")
        self._client = self._create_client()
        self._spreadsheet = self._client.open_by_key(SPREADSHEET_ID)
        logger.info("Переподключение к Google Sheets выполнено успешно")

    def _auto_resize_columns(self, worksheet) -> None:
        """Автоподбор ширины всех столбцов листа через Sheets API."""
        try:
            body = {
                "requests": [{
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": worksheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": worksheet.col_count,
                        }
                    }
                }]
            }
            self._spreadsheet.batch_update(body)
            logger.info("_auto_resize_columns: выполнено для листа '%s'", worksheet.title)
        except Exception as e:
            logger.warning("_auto_resize_columns: не удалось изменить ширину столбцов для '%s': %s", worksheet.title, e)

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """
        Поиск пользователя в Техлисте по Telegram ID.
        """
        logger.debug("Поиск пользователя %s в Техлисте", telegram_id)
        ws = self._get_techlist_worksheet()
        all_values: List[List[Any]] = ws.get_all_values()

        for row_idx, row in enumerate(all_values[1:], start=2):
            if not row:
                continue

            if str(row[COL_TELEGRAM_ID - 1]).strip() == str(telegram_id):
                return {
                    "row_index": row_idx,
                    "telegram_id": row[COL_TELEGRAM_ID - 1],
                    "nickname": row[COL_NICKNAME - 1] if len(row) >= COL_NICKNAME else "",
                    "fio_from_user": row[COL_FIO_FROM_USER - 1] if len(row) >= COL_FIO_FROM_USER else "",
                    "department": row[COL_DEPARTMENT - 1] if len(row) >= COL_DEPARTMENT else "",
                    "position": row[COL_POSITION - 1] if len(row) >= COL_POSITION else "",
                    "registered_at": row[COL_REGISTERED_AT - 1] if len(row) >= COL_REGISTERED_AT else "",
                    "in_staff_table": row[COL_IN_STAFF_TABLE - 1] if len(row) >= COL_IN_STAFF_TABLE else "",
                }

        return None

    def add_or_update_pending_user(
        self,
        telegram_id: int,
        nickname: str,
        fio_from_user: str,
        department: str = "",
        position: str = "",
    ) -> int:
        """
        Создаёт или обновляет запись пользователя в Техлисте (заявка на доступ).
        Возвращает номер строки.
        """
        ws = self._get_techlist_worksheet()
        existing = self.get_user_by_telegram_id(telegram_id)
        nick = nickname if nickname.startswith("@") else f"@{nickname}"
        now_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%y %H:%M")

        if existing:
            row_idx = existing["row_index"]
            ws.batch_update([
                {"range": f"B{row_idx}", "values": [[nick]]},
                {"range": f"C{row_idx}", "values": [[fio_from_user]]},
                {"range": f"D{row_idx}", "values": [[department]]},
                {"range": f"E{row_idx}", "values": [[position]]},
                {"range": f"F{row_idx}", "values": [[now_str]]},
            ])
            logger.info(
                "Обновлена заявка пользователя %s в строке %s",
                telegram_id,
                row_idx,
            )
            return row_idx

        next_row = len(ws.get_all_values()) + 1
        values = [
            str(telegram_id),  # A: Telegram ID
            nick,              # B: @Ник
            fio_from_user,     # C: ФИО от пользователя
            department,        # D: Отдел
            position,          # E: Позиция
            now_str,           # F: Дата регистрации
        ]

        ws.update(f"A{next_row}:F{next_row}", [values])
        logger.info(
            "Создана новая заявка пользователя %s в строке %s",
            telegram_id,
            next_row,
        )
        self._auto_resize_columns(ws)
        return next_row

    def is_user_approved(self, telegram_id: int) -> bool:
        """
        Проверяет, помечен ли пользователь как одобренный (наличие 'ДА' в последнем столбце).
        """
        data = self.get_user_by_telegram_id(telegram_id)
        if not data:
            return False
        return str(data.get("in_staff_table", "")).strip().upper() == "ДА"
    
    def is_user_fully_authorized(self, telegram_id: int) -> bool:
        logger.debug("Проверка полной авторизации пользователя %s", telegram_id)

        if not self.is_user_approved(telegram_id):
            logger.debug("Пользователь %s не одобрен в Техлисте", telegram_id)
            return False

        try:
            month_ws = self._get_current_month_worksheet()
        except Exception as e:
            logger.warning(
                "Не удалось получить текущий лист месяца при проверке полной авторизации %s: %s",
                telegram_id,
                e,
            )
            return False

        all_rows = month_ws.get_all_values()
        if not all_rows:
            logger.warning("Лист месяца '%s' пуст", month_ws.title)
            return False

        all_data = self._normalize_first_three_cols(all_rows)

        for row in all_data[1:]:
            existing_tg_id = row[1]
            if existing_tg_id == str(telegram_id):
                logger.debug("Пользователь %s найден в листе месяца '%s'", telegram_id, month_ws.title)
                return True

        logger.debug("Пользователь %s не найден в листе месяца '%s'", telegram_id, month_ws.title)
        return False


    def mark_user_approved(self, row_index: int) -> None:
        """
        Помечает пользователя как одобренного (ставит 'ДА' в столбец 'Наличие в таблице сотрудников').
        """
        ws = self._get_techlist_worksheet()
        ws.update_cell(row_index, COL_IN_STAFF_TABLE, "ДА")
        logger.info("Пользователь в строке %s помечен как одобренный", row_index)

    def get_user_from_techlist(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """
        Alias для get_user_by_telegram_id (для читаемости кода).
        """
        return self.get_user_by_telegram_id(telegram_id)

    def user_exists_in_techlist(self, telegram_id: int) -> bool:
        """
        Проверяет, есть ли пользователь в Техлисте (колонка A).
        Возвращает True если telegram_id найден, False иначе.
        """
        logger.info("Проверка наличия %s в Техлисте (колонка A)", telegram_id)
        ws = self._get_techlist_worksheet()
        all_values = ws.get_all_values()
        for row in all_values[1:]:
            if row and str(row[COL_TELEGRAM_ID - 1]).strip() == str(telegram_id):
                logger.info("Пользователь %s найден в Техлисте", telegram_id)
                return True
        logger.info("Пользователь %s НЕ найден в Техлисте", telegram_id)
        return False

    def _get_month_sheet_name(self) -> str:
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        return f"{MONTH_NAMES_RU[now.month]} {now.year}"

    def _get_current_month_worksheet(self):
        sheet_name = self._get_month_sheet_name()
        try:
            return self._spreadsheet.worksheet(sheet_name)
        except WorksheetNotFound as exc:
            raise ValueError(f"Лист текущего месяца '{sheet_name}' не найден") from exc
        except Exception as e:
            logger.warning(f"Ошибка получения листа месяца, пробуем переподключиться: {e}")
            self._reconnect()
            try:
                return self._spreadsheet.worksheet(sheet_name)
            except WorksheetNotFound as exc:
                raise ValueError(f"Лист текущего месяца '{sheet_name}' не найден") from exc

    @staticmethod
    def _normalize_first_three_cols(rows: List[List[Any]]) -> List[List[str]]:
        normalized: List[List[str]] = []
        for row in rows:
            padded = (row + ["", "", ""])[:3]
            normalized.append([str(padded[0]).strip(), str(padded[1]).strip(), str(padded[2]).strip()])
        return normalized

    @staticmethod
    def _find_insert_row_for_section(all_data: List[List[str]], section_header: str) -> int:
        section_header_row = -1

        for i, row in enumerate(all_data, start=1):
            a, b, c = row
            if a == "" and b == "" and c == section_header:
                section_header_row = i
                break

        if section_header_row == -1:
            return -1

        insert_after_row = section_header_row

        for r in range(section_header_row, len(all_data)):
            a = all_data[r][0]
            b = all_data[r][1]

            if a == "" and b == "":
                break

            insert_after_row = r + 1

        return insert_after_row

    @staticmethod
    def _find_end_of_department_block(all_data: List[List[str]], department_header: str) -> int:
        if not department_header:
            return -1

        dept_header_row = -1
        for i, row in enumerate(all_data, start=1):
            a, b, c = row
            if a == "" and b == "" and c == department_header:
                dept_header_row = i
                break

        if dept_header_row == -1:
            return -1

        all_dept_headers = set(DEPARTMENT_TO_HEADER.values())
        last_employee_row = dept_header_row

        for r in range(dept_header_row, len(all_data)):
            a, b, c = all_data[r]

            if a == "" and b == "" and c in all_dept_headers and c != department_header:
                break

            if a != "" or b != "":
                last_employee_row = r + 1

        return last_employee_row

    def ensure_user_in_current_month_hours(self, telegram_id: int) -> bool:
        logger.info("Добавление пользователя %s в график текущего месяца", telegram_id)
        user_info = self.get_user_by_telegram_id(telegram_id)
        if not user_info:
            logger.error("Пользователь %s не найден в Техлисте при добавлении в график", telegram_id)
            raise ValueError(f"Пользователь {telegram_id} не найден в Техлисте")

        month_ws = self._get_current_month_worksheet()

        full_name = str(user_info.get("fio_from_user", "")).strip()
        department = str(user_info.get("department", "")).strip()
        position = str(user_info.get("position", "")).strip()

        all_rows = month_ws.get_all_values()
        if not all_rows:
            raise ValueError(f"Лист '{month_ws.title}' пуст")

        all_data = self._normalize_first_three_cols(all_rows)

        for row in all_data[1:]:
            existing_tg_id = row[1]
            if existing_tg_id == str(telegram_id):
                logger.info(
                    "Пользователь %s уже есть в листе '%s', повторная вставка не требуется",
                    telegram_id,
                    month_ws.title,
                )
                return False

        last_row_month = len(all_data)
        target_section = POSITION_TO_SECTION.get(position)
        department_header = DEPARTMENT_TO_HEADER.get(department)

        if not target_section:
            logger.warning(
                "Позиция '%s' не найдена в POSITION_TO_SECTION для пользователя %s, "
                "вставка по концу блока отдела",
                position,
                telegram_id,
            )

        insert_after_row = -1

        if target_section:
            insert_after_row = self._find_insert_row_for_section(all_data, target_section)

        if not target_section or insert_after_row == -1:
            insert_after_row = self._find_end_of_department_block(all_data, department_header)

        if insert_after_row == -1:
            logger.warning(
                "Не найден блок отдела '%s' для пользователя %s, вставка в конец листа",
                department_header,
                telegram_id,
            )
            insert_after_row = last_row_month

        new_row = insert_after_row + 1

        month_ws.insert_row(
            [full_name, str(telegram_id), position],
            index=new_row,
            value_input_option="USER_ENTERED",
        )

        logger.info(
            "Пользователь %s добавлен в лист '%s' в строку %s (department=%s, position=%s)",
            telegram_id,
            month_ws.title,
            new_row,
            department,
            position,
        )

        # Вставить итоговые формулы H/AH в S, AJ, AK новой строки
        try:
            r = new_row
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
            month_ws.batch_update([
                {"range": f"S{r}", "values": [[formula_s]]},
                {"range": f"AJ{r}", "values": [[formula_aj]]},
                {"range": f"AK{r}", "values": [[formula_ak]]},
            ], value_input_option="USER_ENTERED")
            logger.info("Формулы S/AJ/AK вставлены в строку %s листа '%s'", r, month_ws.title)
        except Exception as e:
            logger.warning(
                "Не удалось вставить формулы в строку %s листа '%s': %s",
                new_row, month_ws.title, e,
            )

        self._auto_resize_columns(month_ws)
        return True

    # --- Запись смены ---

    def write_shift(
        self,
        telegram_id: int,
        day: int,
        month: int,
        year: int,
        h: float,
        ah: float,
    ) -> None:
        """
        Записывает смену в месячный лист.
        Ищет строку пользователя по telegram_id (колонка B),
        находит столбец дня в строке 3, пишет значение ячейки.
        Формат: "{h}/{ah}" если ah > 0, иначе str(h).
        """
        sheet_name = f"{MONTH_NAMES_RU[month]} {year}"
        logger.info(
            "write_shift: telegram_id=%s, %02d.%02d.%d, h=%s, ah=%s, лист='%s'",
            telegram_id, day, month, year, h, ah, sheet_name,
        )

        try:
            ws = self._spreadsheet.worksheet(sheet_name)
        except WorksheetNotFound:
            raise ValueError(f"Лист '{sheet_name}' не найден")
        except Exception as e:
            logger.warning("write_shift: ошибка доступа к листу, реконнект: %s", e)
            self._reconnect()
            try:
                ws = self._spreadsheet.worksheet(sheet_name)
            except WorksheetNotFound:
                raise ValueError(f"Лист '{sheet_name}' не найден")

        all_values = ws.get_all_values()

        # Найти строку пользователя по telegram_id в колонке B (индекс 1)
        user_row = None
        for i, row in enumerate(all_values, start=1):
            if len(row) > 1 and str(row[1]).strip() == str(telegram_id):
                user_row = i
                break

        if user_row is None:
            raise ValueError(
                f"Пользователь {telegram_id} не найден в листе '{sheet_name}'"
            )

        # Найти столбец дня в строке 3 (индекс 2).
        # Данные хранятся в диапазонах D–R (4–18) и T–AI (20–35); колонка S (19) пропускается.
        _VALID_DATA_COLS = set(range(4, 19)) | set(range(20, 36))
        date_row = all_values[2] if len(all_values) > 2 else []
        day_col = None
        for j, cell in enumerate(date_row, start=1):
            if j not in _VALID_DATA_COLS:
                continue
            try:
                if int(str(cell).strip()) == day:
                    day_col = j
                    break
            except (ValueError, TypeError):
                continue

        if day_col is None:
            raise ValueError(
                f"День {day} не найден в строке дат листа '{sheet_name}'"
            )

        # Форматируем значение
        def _fmt(v: float) -> str:
            return str(int(v)) if v == int(v) else str(v)

        cell_value = f"{_fmt(h)}/{_fmt(ah)}" if ah > 0 else _fmt(h)

        ws.update_cell(user_row, day_col, cell_value)
        logger.info(
            "write_shift: записано '%s' → строка=%d, столбец=%d (лист='%s')",
            cell_value, user_row, day_col, sheet_name,
        )

    # --- Отчёты ---

    def get_summary_hours(self, telegram_id: int, sheet_name: str) -> Optional[Dict[str, float]]:
        """
        Читает итоговые ячейки S, AJ, AK для пользователя из указанного листа.
        Возвращает словарь h_first/ah_first/h_second/ah_second/h_total/ah_total
        или None если пользователь не найден.
        """
        logger.info("get_summary_hours: telegram_id=%s, sheet='%s'", telegram_id, sheet_name)
        try:
            ws = self._spreadsheet.worksheet(sheet_name)
        except WorksheetNotFound:
            logger.info("get_summary_hours: лист '%s' не найден", sheet_name)
            return None
        except Exception as e:
            logger.warning("get_summary_hours: ошибка доступа к листу '%s': %s", sheet_name, e)
            return None

        all_values = ws.get_all_values()

        user_row_idx = None
        for i, row in enumerate(all_values, start=1):
            if len(row) > 1 and str(row[1]).strip() == str(telegram_id):
                user_row_idx = i
                break

        if user_row_idx is None:
            logger.info("get_summary_hours: пользователь %s не найден в листе '%s'", telegram_id, sheet_name)
            return None

        row = all_values[user_row_idx - 1]

        def _parse_cell(col_idx: int):
            val = row[col_idx - 1].strip() if len(row) >= col_idx else ""
            if not val:
                return 0.0, 0.0
            if "/" in val:
                parts = val.split("/", 1)
                try:
                    h = float(parts[0])
                except ValueError:
                    h = 0.0
                try:
                    ah = float(parts[1])
                except ValueError:
                    ah = 0.0
                return h, ah
            try:
                return float(val), 0.0
            except ValueError:
                return 0.0, 0.0

        h_first, ah_first = _parse_cell(19)   # S
        h_second, ah_second = _parse_cell(36)  # AJ
        h_total, ah_total = _parse_cell(37)    # AK

        logger.info(
            "get_summary_hours: %s → h_first=%s ah_first=%s h_second=%s ah_second=%s h_total=%s ah_total=%s",
            telegram_id, h_first, ah_first, h_second, ah_second, h_total, ah_total,
        )
        return {
            "h_first": h_first,
            "ah_first": ah_first,
            "h_second": h_second,
            "ah_second": ah_second,
            "h_total": h_total,
            "ah_total": ah_total,
        }

    # --- Увольнение ---

    def get_employees_by_dept(self, dept: str) -> List[Dict[str, Any]]:
        """
        Возвращает список одобренных сотрудников по отделу (фильтр по колонке D Техлиста).
        Каждый элемент: {"telegram_id": int, "full_name": str, "position": str}
        """
        logger.info("get_employees_by_dept: dept=%s", dept)
        ws = self._get_techlist_worksheet()
        all_values = ws.get_all_values()
        result = []
        for row in all_values[1:]:
            if len(row) < COL_DEPARTMENT:
                continue
            row_dept = str(row[COL_DEPARTMENT - 1]).strip()
            if row_dept != dept:
                continue
            approved = (
                len(row) >= COL_IN_STAFF_TABLE
                and str(row[COL_IN_STAFF_TABLE - 1]).strip().upper() == "ДА"
            )
            if not approved:
                continue
            tg_id_raw = str(row[COL_TELEGRAM_ID - 1]).strip()
            if not tg_id_raw.lstrip("-").isdigit():
                continue
            full_name = row[COL_FIO_FROM_USER - 1].strip() if len(row) >= COL_FIO_FROM_USER else ""
            position = row[COL_POSITION - 1].strip() if len(row) >= COL_POSITION else ""
            result.append({
                "telegram_id": int(tg_id_raw),
                "full_name": full_name,
                "position": position,
            })
        logger.info("get_employees_by_dept: найдено %d сотрудников в отделе '%s'", len(result), dept)
        return result

    def dismiss_employee(self, telegram_id: int) -> None:
        """
        Увольняет сотрудника:
        1. Красит ячейку A в текущем месячном листе (#FFCCCC) по telegram_id в колонке B.
        2. Удаляет строку из Техлиста.
        """
        logger.info("dismiss_employee: начало увольнения telegram_id=%s", telegram_id)

        # Покрасить ячейку A в месячном листе
        try:
            month_ws = self._get_current_month_worksheet()
            all_values = month_ws.get_all_values()
            month_row = None
            for i, row in enumerate(all_values, start=1):
                if len(row) > 1 and str(row[1]).strip() == str(telegram_id):
                    month_row = i
                    break
            if month_row is not None:
                month_ws.format(
                    f"A{month_row}",
                    {"backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}},
                )
                logger.info(
                    "dismiss_employee: ячейка A%d в листе '%s' покрашена #FFCCCC (telegram_id=%s)",
                    month_row, month_ws.title, telegram_id,
                )
            else:
                logger.debug(
                    "dismiss_employee: пользователь %s не найден в месячном листе '%s', "
                    "окраска пропущена",
                    telegram_id, month_ws.title,
                )
        except Exception as e:
            logger.error(
                "dismiss_employee: ошибка при окраске ячейки в месячном листе для %s: %s",
                telegram_id, e,
            )

        # Удалить строку из Техлиста
        try:
            ws = self._get_techlist_worksheet()
            all_values = ws.get_all_values()
            tech_row = None
            for i, row in enumerate(all_values, start=1):
                if row and str(row[COL_TELEGRAM_ID - 1]).strip() == str(telegram_id):
                    tech_row = i
                    break
            if tech_row is not None:
                ws.delete_rows(tech_row)
                logger.info(
                    "dismiss_employee: строка %d удалена из Техлиста (telegram_id=%s)",
                    tech_row, telegram_id,
                )
            else:
                logger.debug(
                    "dismiss_employee: пользователь %s не найден в Техлисте, удаление пропущено",
                    telegram_id,
                )
        except Exception as e:
            logger.error(
                "dismiss_employee: ошибка при удалении из Техлиста для %s: %s",
                telegram_id, e,
            )
