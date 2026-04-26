import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID

SHEET_NAME = "Апрель 2026"

def get_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_PATH, scope)
    return gspread.authorize(creds)

client = get_client()
ws = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# Читаем формулу в S11 (не значение)
formula_s11 = ws.acell("S11", value_render_option="FORMULA").value
value_s11   = ws.acell("S11", value_render_option="FORMATTED_VALUE").value
print(f"S11 формула : {formula_s11}")
print(f"S11 значение: {value_s11}")

# Читаем сырые значения D11:R11
print("\nD11:R11 (сырые значения):")
raw = ws.get("D11:R11", value_render_option="UNFORMATTED_VALUE")
if raw:
    for i, val in enumerate(raw[0]):
        col = chr(ord('D') + i)
        print(f"  {col}11 = {repr(val)}")

# Читаем форматированные (как видит пользователь)
print("\nD11:R11 (форматированные):")
fmt = ws.get("D11:R11", value_render_option="FORMATTED_VALUE")
if fmt:
    for i, val in enumerate(fmt[0]):
        col = chr(ord('D') + i)
        print(f"  {col}11 = {repr(val)}")
