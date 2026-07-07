"""
Модуль подключения к GTD Master System (Google Sheets + Google Drive)
"""

import os
import io
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]

GTD_DRIVE_FOLDER = "GTD_DOCUMENTS"

SHEET_NAMES = {
    "inbox":        "INBOX",
    "projects":     "PROJECTS",
    "next_actions": "NEXT ACTIONS",
    "waiting":      "WAITING FOR",
    "someday":      "SOMEDAY",
    "areas":        "AREAS",
    "review":       "WEEKLY REVIEW",
    "reference":    "REFERENCE",
    "horizons":     "HORIZONS",
    "quarterly":    "QUARTERLY REVIEW",
    "archive":      "ARCHIVE",
}


def _get_creds():
    return Credentials.from_service_account_file(
        os.getenv("GOOGLE_CREDENTIALS_FILE"),
        scopes=SCOPES,
    )


def get_client():
    return gspread.authorize(_get_creds())


def get_drive_service():
    return build("drive", "v3", credentials=_get_creds())


def upload_pdf_to_drive(file_bytes: bytes, filename: str) -> str:
    """Загрузить PDF в папку GTD_DOCUMENTS на Google Drive пользователя."""
    service = get_drive_service()
    folder_id = os.getenv("GDRIVE_FOLDER_ID")

    is_shared = os.getenv("GDRIVE_IS_SHARED_DRIVE", "false").lower() == "true"

    file_meta = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/pdf")
    uploaded = service.files().create(
        body=file_meta,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True
    ).execute()

    # Дать публичный доступ на чтение (только для обычного Drive)
    if not is_shared:
        service.permissions().create(
            fileId=uploaded["id"],
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True
        ).execute()

    return uploaded.get("webViewLink", "")


def get_spreadsheet():
    client = get_client()
    return client.open_by_key(os.getenv("SPREADSHEET_ID"))


def get_sheet(name: str):
    """Получить лист по короткому имени: inbox, projects, next_actions..."""
    ss = get_spreadsheet()
    sheet_name = SHEET_NAMES[name]
    try:
        return ss.worksheet(sheet_name)
    except Exception:
        # Лист не существует — создаём с заголовками
        sheet = ss.add_worksheet(title=sheet_name, rows=500, cols=10)
        if name == "horizons":
            sheet.append_row(["ID", "Горизонт", "Описание", "Дата", "Статус", "Область", "Заметки"])
        elif name == "quarterly":
            sheet.append_row([
                "Дата", "Квартал", "H3 цели", "Проекты", "Приоритеты",
                "Инсайты", "AI итог",
            ])
        elif name == "archive":
            sheet.append_row([
                "ID", "Название проекта", "Итог проекта", "Область",
                "Приоритет", "Дата старта", "Дата завершения",
                "Действий выполнено", "Уроки/Заметки",
            ])
        return sheet


def get_biz_spreadsheet():
    """Открыть бизнес-таблицу (узаконение)."""
    client = get_client()
    return client.open_by_key(os.getenv("BIZ_SPREADSHEET_ID"))


def get_biz_sheet(name: str):
    """Получить лист из бизнес-таблицы по точному имени."""
    return get_biz_spreadsheet().worksheet(name)


def read_biz_objects() -> list[dict]:
    """Вернуть список действующих объектов."""
    ws = get_biz_sheet("Действущие обекты")
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[1]  # строка 2 — заголовки
    result = []
    for row in rows[2:]:
        if not any(row):
            continue
        obj = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
        if obj.get("№", "").strip():
            result.append(obj)
    return result


def read_biz_steps(sheet_name: str) -> list[dict]:
    """Вернуть шаги по объекту из его листа."""
    ws = get_biz_sheet(sheet_name)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    # Строка 1 — адрес, строка 2 — заголовки
    address = rows[0][0] if rows else ""
    headers = rows[1] if len(rows) > 1 else []
    result = []
    for row in rows[2:]:
        if not any(row) or not row[0].strip():
            continue
        step = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
        if step.get("№", "").strip():
            result.append(step)
    return address, result


def read_biz_object_names() -> list[str]:
    """Вернуть список имён листов-объектов (UZ-XXXX)."""
    ss = get_biz_spreadsheet()
    return [ws.title for ws in ss.worksheets() if ws.title.startswith("UZ-")]


def read_inbox() -> list[dict]:
    """Вернуть все строки Inbox как список словарей."""
    sheet = get_sheet("inbox")
    return sheet.get_all_records()


def read_projects() -> list[dict]:
    sheet = get_sheet("projects")
    return sheet.get_all_records()


def read_next_actions() -> list[dict]:
    sheet = get_sheet("next_actions")
    return sheet.get_all_records()


def append_row(sheet_name: str, values: list):
    """Добавить строку в конец листа (надёжный способ через update)."""
    sheet = get_sheet(sheet_name)
    all_rows = sheet.get_all_values()
    next_row = len(all_rows) + 1
    cols = len(values)
    col_letter = chr(ord('A') + cols - 1)
    sheet.update(values=[values], range_name=f"A{next_row}:{col_letter}{next_row}")


def update_cell(sheet_name: str, row: int, col: int, value):
    """Обновить одну ячейку (row и col с 1)."""
    sheet = get_sheet(sheet_name)
    sheet.update_cell(row, col, value)
