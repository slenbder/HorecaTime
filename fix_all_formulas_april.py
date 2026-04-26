import sys
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID

SHEET_NAME = "Апрель 2026"
START_ROW = 5
BATCH_SIZE = 50

COL_A = 0   # ФИО (индекс 0)
COL_S = 18  # колонка S (индекс 18)


def get_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_PATH, scope)
    return gspread.authorize(creds)


def col_letter(n):
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def main():
    print(f"Подключаемся к Google Sheets: {SHEET_NAME}")
    client = get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        print(f"Лист '{SHEET_NAME}' не найден!", file=sys.stderr)
        sys.exit(1)

    print("Читаем данные листа...")
    all_values = ws.get_all_values()
    total_rows = len(all_values)
    print(f"Всего строк в листе: {total_rows}")

    updates = []
    updated_rows = []

    for row_idx in range(START_ROW - 1, total_rows):
        row = all_values[row_idx]
        r = row_idx + 1  # номер строки в таблице (1-based)

        fio = row[COL_A].strip() if len(row) > COL_A else ""
        if not fio:
            continue

        old_s = row[COL_S].strip() if len(row) > COL_S else ""

        # ПОДСТАВИТЬ заменяет "." на "," — иначе VALUE("13.5") в русской локали
        # читает точку как разделитель даты (13 мая) и возвращает серийный номер даты
        formula_s  = (
            f'=СУММПРОИЗВ(ЕСЛИ(D{r}:R{r}="";0;'
            f'ЕСЛИОШИБКА(ЗНАЧЕН(ПОДСТАВИТЬ(D{r}:R{r};".";","));0)))'
        )
        formula_aj = (
            f'=СУММПРОИЗВ(ЕСЛИ(T{r}:AI{r}="";0;'
            f'ЕСЛИОШИБКА(ЗНАЧЕН(ПОДСТАВИТЬ(T{r}:AI{r};".";","));0)))'
        )
        formula_ak = f'=S{r}+AJ{r}'

        updates.append({"range": f"S{r}", "values": [[formula_s]]})
        updates.append({"range": f"AJ{r}", "values": [[formula_aj]]})
        updates.append({"range": f"AK{r}", "values": [[formula_ak]]})

        updated_rows.append((r, fio, old_s))
        print(f"Строка {r} ({fio}): S было [{old_s}], будет формула")

    if not updates:
        print("Нет строк для обновления.")
        return

    print(f"\nОтправляем {len(updates)} обновлений батчами по {BATCH_SIZE * 3}...")

    # Группируем по BATCH_SIZE строк (3 ячейки на строку)
    for i in range(0, len(updates), BATCH_SIZE * 3):
        batch = updates[i : i + BATCH_SIZE * 3]
        ws.batch_update(batch, value_input_option="USER_ENTERED")
        print(f"  Батч {i // (BATCH_SIZE * 3) + 1}: отправлено {len(batch)} обновлений")
        if i + BATCH_SIZE * 3 < len(updates):
            time.sleep(1.5)  # Rate limit: 60 req/min

    print(f"\n=== Итого обновлено строк: {len(updated_rows)} ===")

    # Проверка S11 и S13 (Каримов и Любенко)
    print("\nПроверяем формулы и значения S11, S13...")
    time.sleep(3)
    for cell in ["S11", "S13"]:
        formula = ws.acell(cell, value_render_option="FORMULA").value
        value   = ws.acell(cell, value_render_option="FORMATTED_VALUE").value
        has_substitute = "ПОДСТАВИТЬ" in (formula or "") or "SUBSTITUTE" in (formula or "")
        print(f"  {cell}: значение={value}, SUBSTITUTE={'ДА' if has_substitute else 'НЕТ'}")


if __name__ == "__main__":
    main()
