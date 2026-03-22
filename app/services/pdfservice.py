import logging

import requests
from google.oauth2.service_account import Credentials

logger = logging.getLogger("app")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class PDFService:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        self._creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self._spreadsheet_id = spreadsheet_id

    async def get_pdf_bytes(self, sheet_id: int, range_a1: str | None = None) -> bytes:
        """
        Экспортирует лист или диапазон в PDF через Google Sheets export URL.
        sheet_id  — числовой ID листа (gid).
        range_a1  — диапазон A1 notation (например "A1:AK60"), None = весь лист.
        Возвращает bytes PDF файла.
        """
        import google.auth.transport.requests

        request = google.auth.transport.requests.Request()
        self._creds.refresh(request)

        url = (
            f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/export"
            f"?exportFormat=pdf&format=pdf"
            f"&gid={sheet_id}"
            f"&portrait=false"
            f"&fitw=true"
            f"&sheetnames=false"
            f"&printtitle=false"
            f"&pagenumbers=false"
            f"&gridlines=true"
            f"&fzr=false"
            f"&size=A4"
            f"&top_margin=0.25&bottom_margin=0.25"
            f"&left_margin=0.25&right_margin=0.25"
        )
        if range_a1:
            url += f"&range={requests.utils.quote(range_a1)}"

        logger.info("PDFService.get_pdf_bytes: gid=%s range=%s", sheet_id, range_a1)

        headers = {"Authorization": f"Bearer {self._creds.token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.content
