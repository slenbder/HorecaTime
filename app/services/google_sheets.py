from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID

logger = logging.getLogger("google_api")

TECHLIST_SHEET_NAME = "Техлист"

# Индексы столбцов в Техлисте (1-based)
COL_TELEGRAM_ID = 1
COL_NICKNAME = 2
COL_TG_NAME = 3
COL_MESSAGE = 4
COL_REGISTERED_AT = 5
COL_LAST_SEEN_AT = 6
COL_MESSAGE_ID = 7
COL_FIO_FROM_USER = 8
COL_STAGE = 9
COL_IN_STAFF_TABLE = 10  # "ДА", если одобрен и есть в таблице сотрудников
COL_DEPARTMENT = 11      # Отдел (Зал/Бар/Кухня)
COL_POSITION = 12        # Позиция (Runner/Официант/и т.д.)



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
            raise FileNotFoundError(f"Service account JSON not found: {creds_path}")

        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            str(creds_path), scopes
        )
        return gspread.authorize(credentials)

    # --- Техлист ---

    def _get_techlist_worksheet(self):
        return self._spreadsheet.worksheet(TECHLIST_SHEET_NAME)

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """
        Поиск пользователя в Техлисте по Telegram ID.
        """
        ws = self._get_techlist_worksheet()
        all_values: List[List[Any]] = ws.get_all_values()

        for row_idx, row in enumerate(all_values, start=1):
            if not row:
                continue

            if str(row[COL_TELEGRAM_ID - 1]).strip() == str(telegram_id):
                return {
                    "row_index": row_idx,
                    "telegram_id": row[COL_TELEGRAM_ID - 1],
                    "nickname": row[COL_NICKNAME - 1]
                    if len(row) >= COL_NICKNAME
                    else "",
                    "tg_name": row[COL_TG_NAME - 1]
                    if len(row) >= COL_TG_NAME
                    else "",
                    "message": row[COL_MESSAGE - 1]
                    if len(row) >= COL_MESSAGE
                    else "",
                    "registered_at": row[COL_REGISTERED_AT - 1]
                    if len(row) >= COL_REGISTERED_AT
                    else "",
                    "last_seen_at": row[COL_LAST_SEEN_AT - 1]
                    if len(row) >= COL_LAST_SEEN_AT
                    else "",
                    "message_id": row[COL_MESSAGE_ID - 1]
                    if len(row) >= COL_MESSAGE_ID
                    else "",
                    "fio_from_user": row[COL_FIO_FROM_USER - 1]
                    if len(row) >= COL_FIO_FROM_USER
                    else "",
                    "stage": row[COL_STAGE - 1]
                    if len(row) >= COL_STAGE
                    else "",
                    "in_staff_table": row[COL_IN_STAFF_TABLE - 1]
                    if len(row) >= COL_IN_STAFF_TABLE
                    else "",
                    "department": row[COL_DEPARTMENT - 1] 
                    if len(row) >= COL_DEPARTMENT 
                    else "",    # НОВОЕ
                    "position": row[COL_POSITION - 1] 
                    if len(row) >= COL_POSITION 
                    else "",          # НОВОЕ
                }

        return None

    def add_or_update_pending_user(
        self,
        telegram_id: int,
        nickname: str,
        tg_name: str,
        fio_from_user: str,
        department: str = "",       # Новое
        position: str = "",         # Новое
    ) -> int:
        """
        Создаёт или обновляет запись пользователя в Техлисте (заявка на доступ).
        Возвращает номер строки.
        """
        ws = self._get_techlist_worksheet()
        existing = self.get_user_by_telegram_id(telegram_id)
        now_unix = int(time.time())

        if existing:
            row_idx = existing["row_index"]
            ws.update_cell(row_idx, COL_NICKNAME, nickname)
            ws.update_cell(row_idx, COL_TG_NAME, tg_name)
            ws.update_cell(row_idx, COL_FIO_FROM_USER, fio_from_user)
            ws.update_cell(row_idx, COL_LAST_SEEN_AT, str(now_unix))
            ws.update_cell(row_idx, COL_DEPARTMENT, department)      # Новое
            ws.update_cell(row_idx, COL_POSITION, position)          # Новое
            logger.info(
                "Обновлена заявка пользователя %s в строке %s",
                telegram_id,
                row_idx,
            )
            return row_idx

        next_row = len(ws.get_all_values()) + 1
        values = [
            str(telegram_id),  # id пользователя
            nickname,          # Ник
            tg_name,           # Имя (TG)
            "",                # Сообщение
            str(now_unix),     # Время регистрации (UNIX)
            str(now_unix),     # Время крайнего обращения
            "",                # Id сообщения
            fio_from_user,     # Имя и Фамилия отправленное пользователем
            "",                # Номер этапа взаимодействия
            "",                # Наличие в таблице сотрудников
            department,        # Отдел (НОВОЕ)
            position,          # Позиция (НОВОЕ)
        ]

        ws.update(f"A{next_row}:L{next_row}", [values])
        logger.info(
            "Создана новая заявка пользователя %s в строке %s",
            telegram_id,
            next_row,
        )
        return next_row

    def is_user_approved(self, telegram_id: int) -> bool:
        """
        Проверяет, помечен ли пользователь как одобренный (наличие 'ДА' в последнем столбце).
        """
        data = self.get_user_by_telegram_id(telegram_id)
        if not data:
            return False
        return str(data.get("in_staff_table", "")).strip().upper() == "ДА"

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
