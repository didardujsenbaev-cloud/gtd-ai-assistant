"""
Business Core — Google Sheets layer.

Работает с отдельной таблицей BUSINESS_SPREADSHEET_ID.
Основной sheets.py (GTD Master) не меняется и не импортируется здесь.
Авторизацию берём из того же GOOGLE_CREDENTIALS_FILE.
"""

from __future__ import annotations

import os
import sys
import logging

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Константы
# ─────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

BUSINESS_SHEET_NAMES: dict[str, str] = {
    "biz_registry":        "BIZ_REGISTRY",
    "service_catalog":     "SERVICE_CATALOG",
    "people_registry":     "PEOPLE_REGISTRY",
    "channel_registry":    "CHANNEL_REGISTRY",
    "integration_registry":"INTEGRATION_REGISTRY",
    "roadmaps":            "ROADMAPS",
    "roadmap_stages":      "ROADMAP_STAGES",
    "materials":           "MATERIALS",
    "relationship_capital":"RELATIONSHIP_CAPITAL",
    "business_branches":   "BUSINESS_BRANCHES",
    "object_registry":     "OBJECT_REGISTRY",   # Phase 6A
    # Phase 8B: Roadmap Template Registry
    "roadmap_template_registry": "ROADMAP_TEMPLATE_REGISTRY",
    "roadmap_template_stages":   "ROADMAP_TEMPLATE_STAGES",
}

BUSINESS_HEADERS: dict[str, list[str]] = {
    "biz_registry": [
        "ID", "Название", "Slug", "Статус", "Описание", "Города",
        "Ответственный", "Приоритет", "Дата старта", "Google Drive",
        "Google Sheet", "GTD Project ID", "SendPulse", "Binotel", "WABA",
        "Instagram", "Telegram", "CRM", "Комментарий", "Последнее обновление",
        "Drive Folder ID",       # Drive ID папки бизнеса (Phase 5)
        # Phase 6A: Multi-Business Config
        "Drive Root ID",         # отдельный корневой ID Drive для этого бизнеса
        "Drive Credentials",     # ключ credentials (default / biz_uzak / biz_visa)
        "Google Account Email",  # email Google-аккаунта бизнеса
        "Cities JSON",           # JSON: ["Алматы","Астана","Шымкент"]
        "Default City",          # город по умолчанию
        "Business Model Type",   # object_based / person_case_based / program_based
    ],
    "service_catalog": [
        "ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
        "Цена мин", "Цена макс", "Срок", "Описание",
        "Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
        "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
        "Документы от клиента", "Документы наши",
        "Чек-лист производства", "Чек-лист закрытия",
        "Риски", "Шаблоны", "Инструкция", "Комментарий",
        # Phase 8A: Service Catalog Upgrade (добавлены в конец)
        "Service Name",          # англ. название (может совпадать с Название)
        "Service Category",      # категория: узаконение / виза / коучинг / ...
        "Object Type",           # тип объекта: частный дом / нежилое / новострой
        "Client Type",           # тип клиента: физ. лицо / юр. лицо
        "What Included",         # что включено в услугу
        "What Not Included",     # что не включено
        "Currency",              # KZT / USD / EUR
        "Required Documents",    # необходимые документы
        "Default Roadmap Template ID",  # ключ из ROADMAP_TEMPLATES
        "Contractors Needed",    # нужны ли подрядчики
        "Materials IDs",         # материалы (MATERIAL-ID через запятую)
        "Created At",            # дата создания
        "Last Updated",          # дата обновления
    ],
    "people_registry": [
        "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
        "Telegram", "Email", "Город", "Компания", "Должность",
        "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
        "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
        "День рождения", "Важные события",
        "Дата первого контакта", "Дата последнего контакта",
        "Канал последнего контакта", "История",
        "Следующее касание", "Тип касания", "Заметка касания",
        "Статус отношений", "Теплота", "Комментарий",
        "Google Drive",      # Drive-ссылка на папку клиента (Phase 5)
        "Drive Folder ID",   # Drive ID (Phase 5)
        # Phase 6A: Multi-Business Config
        "Biz IDs",           # "BIZ-001,BIZ-002" — ID бизнесов (вместо имён)
        "Company ID",        # PRS-ID компании (для Визы: сотрудник → компания)
        "Citizenship",       # гражданство (для Визы)
        "Passport / ID",     # паспорт / ИИН (для Узаконения и Визы)
        "Primary Biz ID",    # основной бизнес клиента
    ],
    "channel_registry": [
        "ID", "Тип", "Бизнес ID", "Город", "Номер/Аккаунт",
        "Назначение", "Аудитория", "Ответственный",
        "Статус", "Интеграция", "Метрики", "Комментарий",
    ],
    "integration_registry": [
        "ID", "Сервис A", "Сервис B", "Тип", "Бизнесы", "Описание",
        "API endpoint", "Где код", "Ключи (.env)", "Статус",
        "Последняя проверка", "Как проверить", "Типичные ошибки",
        "Решение", "Ответственный", "Документация", "Комментарий",
    ],
    "roadmaps": [
        "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
        "Client Name", "GTD Project ID", "Responsible", "Status",
        "Created", "Expected", "Progress %",
        "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
        "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
        "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
        "Stage 10 Status", "Notes", "Last Updated",
        # Phase 6A: Multi-Business
        "Object ID",          # OBJ-ID (для Узаконения: объект недвижимости)
        "Parent Roadmap ID",  # RM-ID (если это под-карта другого roadmap)
        "Case Type",          # legalization_object / visa_foreigner / coaching_program / general
    ],
    "roadmap_stages": [
        "Stage ID", "Roadmap ID", "Order", "Name", "Status",
        "Due Date", "Completed At", "GTD Action ID",
        "Responsible", "Docs Required", "Docs Received", "Notes",
    ],
    "materials": [
        "Material ID", "Source", "Received At", "GTD Reference Row",
        "GTD Project ID", "Business ID", "Service ID", "City",
        "Client ID", "Roadmap ID", "Stage ID",
        "File Type", "Drive URL", "Filename", "File Size KB",
        "Status", "Checked By", "Approved At", "Notes",
    ],
    "relationship_capital": [
        "PRS ID", "ФИО", "Теплота", "Дни без контакта",
        "Тип касания", "Дата касания", "Общие интересы",
        "Чем помог мне", "Чем я помог", "Кого познакомить",
        "Через кого решить", "Контент для него",
    ],
    "business_branches": [
        "BIZ ID", "Раздел", "Ключ", "Значение",
        "Цель", "Период", "Дата обновления",
    ],
    # Phase 6A: реестр объектов (недвижимость для Узаконения)
    "object_registry": [
        "OBJ ID", "Client ID", "Biz ID", "City",
        "Address", "Cadastral Number", "Area m2",
        "Object Type",         # квартира / дом / участок / коммерческая
        "Object Status",       # в работе / готово / архив
        "Current Service ID",  # SVC-ID текущей услуги
        "Roadmap ID",          # RM-ID
        "Drive Folder ID",     # папка объекта в Drive
        "Google Drive",        # ссылка на папку
        "Notes",
        "Created At",
        "Last Updated",
    ],
    # Phase 8B: шаблоны дорожных карт
    "roadmap_template_registry": [
        "Template ID",      # RTMPL-001
        "Biz ID",           # BIZ-001 (None = глобальный)
        "Service ID",       # SVC-001 (None = любая)
        "Template Name",    # человеческое название
        "Case Type",        # ключ из ROADMAP_TEMPLATES (совместимость)
        "Object Type",      # тип объекта (частный дом / нежилое / ...)
        "Description",      # описание шаблона
        "Status",           # active / inactive / draft
        "Stages Count",     # сколько этапов (автозаполнение)
        "Notes",
        "Created At",
        "Last Updated",
    ],
    "roadmap_template_stages": [
        "Stage ID",         # TSTG-001
        "Template ID",      # RTMPL-001
        "Order",            # порядковый номер
        "Stage Name",       # название этапа
        "Description",      # описание
        "Required Docs",    # необходимые документы
        "Responsible",      # ответственный по умолчанию
        "Estimated Days",   # ожидаемое количество дней
        "Notes",
        "Created At",
    ],
}

# ID-префиксы для generate_next_id
_ID_PREFIXES: dict[str, str] = {
    "biz_registry":        "BIZ",
    "service_catalog":     "SVC",
    "people_registry":     "PRS",
    "channel_registry":    "CH",
    "integration_registry":"INT",
    "roadmaps":            "RM",
    "roadmap_stages":      "STAGE",
    "materials":           "MAT",
    "object_registry":     "OBJ",    # Phase 6A
    # Phase 8B
    "roadmap_template_registry": "RTMPL",
    "roadmap_template_stages":   "TSTG",
}


# ─────────────────────────────────────────────────────────────
# Авторизация
# ─────────────────────────────────────────────────────────────

def _get_biz_creds() -> Credentials:
    """Получить Google credentials из GOOGLE_CREDENTIALS_FILE."""
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
    if not creds_file:
        raise EnvironmentError(
            "GOOGLE_CREDENTIALS_FILE не найден в .env\n"
            "Добавьте: GOOGLE_CREDENTIALS_FILE=путь/к/credentials.json"
        )
    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"Файл credentials не найден: {creds_file}\n"
            "Убедитесь что JSON ключ service account лежит в папке проекта."
        )
    return Credentials.from_service_account_file(creds_file, scopes=SCOPES)


def _get_biz_client() -> gspread.Client:
    return gspread.authorize(_get_biz_creds())


def _get_service_account_email() -> str:
    """Прочитать client_email из GOOGLE_CREDENTIALS_FILE. Возвращает '<неизвестен>' при ошибке."""
    try:
        import json
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
        if creds_file and os.path.exists(creds_file):
            with open(creds_file) as f:
                return json.load(f).get("client_email", "<неизвестен>")
    except Exception:
        pass
    return "<неизвестен>"


# ─────────────────────────────────────────────────────────────
# Основные функции доступа
# ─────────────────────────────────────────────────────────────

def get_business_spreadsheet() -> gspread.Spreadsheet:
    """
    Открыть таблицу Business Core по BUSINESS_SPREADSHEET_ID.

    Raises:
        EnvironmentError: если BUSINESS_SPREADSHEET_ID не задан в .env
        gspread.exceptions.APIError: если нет доступа к таблице
    """
    biz_id = os.getenv("BUSINESS_SPREADSHEET_ID", "").strip()
    if not biz_id:
        raise EnvironmentError(
            "BUSINESS_SPREADSHEET_ID не найден в .env\n"
            "Добавьте: BUSINESS_SPREADSHEET_ID=<id таблицы Business Core>\n"
            "ID находится в URL: docs.google.com/spreadsheets/d/<ВОТ_ЭТО>/edit"
        )
    client = _get_biz_client()
    try:
        return client.open_by_key(biz_id)
    except gspread.exceptions.APIError as e:
        raise PermissionError(
            f"Нет доступа к BUSINESS_CORE таблице (ID: {biz_id})\n"
            f"Убедитесь что дали доступ service account: "
            f"{_get_service_account_email()}\n"
            f"Ошибка: {e}"
        ) from e


def get_business_sheet(name: str) -> gspread.Worksheet:
    """
    Получить лист по короткому ключу из BUSINESS_SHEET_NAMES.
    Если листа нет — создаёт его с заголовками.

    Args:
        name: ключ из BUSINESS_SHEET_NAMES (например 'biz_registry')

    Raises:
        KeyError: если ключ не найден в BUSINESS_SHEET_NAMES
    """
    if name not in BUSINESS_SHEET_NAMES:
        valid = ", ".join(BUSINESS_SHEET_NAMES.keys())
        raise KeyError(
            f"Неверный ключ листа: '{name}'\n"
            f"Допустимые ключи: {valid}"
        )

    sheet_name = BUSINESS_SHEET_NAMES[name]
    ss = get_business_spreadsheet()

    try:
        return ss.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        log.info(f"Лист '{sheet_name}' не найден — создаю...")
        headers = BUSINESS_HEADERS.get(name, [])
        cols = max(len(headers), 10)
        sheet = ss.add_worksheet(title=sheet_name, rows=1000, cols=cols)
        if headers:
            sheet.append_row(headers, value_input_option="USER_ENTERED")
            log.info(f"Заголовки добавлены: {sheet_name} ({len(headers)} колонок)")
        return sheet


def ensure_headers(sheet: gspread.Worksheet, headers: list[str]) -> bool:
    """
    Проверить и установить заголовки в первой строке.

    - Если первая строка пустая → записывает заголовки
    - Если заголовки уже совпадают → ничего не делает
    - Если заголовки ОТЛИЧАЮТСЯ → выводит предупреждение, НЕ перезаписывает

    Returns:
        True если заголовки корректны (уже были или только что записаны)
        False если обнаружено несоответствие
    """
    if not headers:
        return True

    existing = sheet.row_values(1)

    if not any(existing):
        sheet.update(values=[headers], range_name="A1")
        log.info(f"Заголовки записаны в '{sheet.title}'")
        return True

    if existing == headers:
        return True

    # Заголовки отличаются — не перезаписывать
    missing = [h for h in headers if h not in existing]
    extra = [h for h in existing if h not in headers]
    log.warning(
        f"⚠️  Заголовки листа '{sheet.title}' отличаются от ожидаемых!\n"
        f"   Ожидается {len(headers)} колонок, найдено {len(existing)}\n"
        + (f"   Отсутствуют: {missing}\n" if missing else "")
        + (f"   Лишние: {extra}\n" if extra else "")
        + "   Автоперезапись отключена. Проверьте вручную."
    )
    return False


# ─────────────────────────────────────────────────────────────
# Инициализация всех листов
# ─────────────────────────────────────────────────────────────

def init_business_core_sheets(verbose: bool = True) -> dict[str, bool]:
    """
    Создать все листы Business Core с заголовками (если их нет).

    Безопасно: не перезаписывает существующие данные.

    Args:
        verbose: выводить ли прогресс в stdout

    Returns:
        dict { ключ_листа: True/False (успешно ли) }
    """
    if verbose:
        print("🏗  Инициализация Business Core Sheets...")

    ss = get_business_spreadsheet()
    existing_titles = {ws.title for ws in ss.worksheets()}
    results: dict[str, bool] = {}

    for key, sheet_name in BUSINESS_SHEET_NAMES.items():
        headers = BUSINESS_HEADERS.get(key, [])
        try:
            if sheet_name not in existing_titles:
                cols = max(len(headers), 10)
                sheet = ss.add_worksheet(title=sheet_name, rows=1000, cols=cols)
                if headers:
                    sheet.update(values=[headers], range_name="A1")
                if verbose:
                    print(f"  ✅ Создан:      {sheet_name} ({len(headers)} колонок)")
            else:
                sheet = ss.worksheet(sheet_name)
                ok = ensure_headers(sheet, headers)
                status = "✅ Существует" if ok else "⚠️  Несоответствие заголовков"
                if verbose:
                    print(f"  {status}: {sheet_name}")
            results[key] = True
        except Exception as e:
            if verbose:
                print(f"  ❌ Ошибка {sheet_name}: {e}")
            results[key] = False
            log.error(f"init_business_core_sheets: {sheet_name}: {e}")

    if verbose:
        ok_count = sum(results.values())
        total = len(results)
        url = f"https://docs.google.com/spreadsheets/d/{os.getenv('BUSINESS_SPREADSHEET_ID')}/edit"
        print(f"\n📊 Итог: {ok_count}/{total} листов готово")
        print(f"🔗 Таблица: {url}")

    return results


# ─────────────────────────────────────────────────────────────
# CRUD операции
# ─────────────────────────────────────────────────────────────

def append_business_row(sheet_key: str, values: list) -> int:
    """
    Безопасно добавить строку в лист Business Core.

    Использует sheet.update() вместо sheet.append_row()
    (тот же подход что в основном sheets.py).

    Args:
        sheet_key: ключ из BUSINESS_SHEET_NAMES
        values: список значений строки

    Returns:
        Номер записанной строки (1-based)
    """
    sheet = get_business_sheet(sheet_key)
    all_rows = sheet.get_all_values()
    next_row = len(all_rows) + 1

    if not values:
        raise ValueError("values не может быть пустым")

    cols = len(values)
    # Строим A1-нотацию: A5:T5
    end_col = _col_letter(cols)
    range_name = f"A{next_row}:{end_col}{next_row}"

    # Дополнить до нужного количества колонок если нужно
    headers = BUSINESS_HEADERS.get(sheet_key, [])
    if headers and len(values) < len(headers):
        values = values + [""] * (len(headers) - len(values))
        cols = len(values)
        end_col = _col_letter(cols)
        range_name = f"A{next_row}:{end_col}{next_row}"

    sheet.update(values=[values], range_name=range_name)
    log.debug(f"append_business_row: {sheet_key} → строка {next_row}")
    return next_row


def read_business_sheet(sheet_key: str) -> list[dict]:
    """
    Прочитать все записи листа как список словарей.

    Args:
        sheet_key: ключ из BUSINESS_SHEET_NAMES

    Returns:
        list[dict] — каждый словарь = одна строка (ключи = заголовки)
    """
    sheet = get_business_sheet(sheet_key)
    return sheet.get_all_records()


def update_business_cell(sheet_key: str, row: int, col: int, value) -> None:
    """
    Обновить одну ячейку (row и col с 1).

    Args:
        sheet_key: ключ листа
        row: номер строки (1-based)
        col: номер колонки (1-based)
        value: новое значение
    """
    sheet = get_business_sheet(sheet_key)
    sheet.update_cell(row, col, value)


def find_row_by_id(sheet_key: str, record_id: str) -> tuple[int, dict] | None:
    """
    Найти строку по ID (первая колонка).

    Returns:
        (row_number, row_dict) или None если не найдено
    """
    sheet = get_business_sheet(sheet_key)
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return None

    headers = all_values[0]
    for i, row in enumerate(all_values[1:], start=2):
        if row and row[0] == record_id:
            row_dict = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
            return (i, row_dict)
    return None


# ─────────────────────────────────────────────────────────────
# ID генератор
# ─────────────────────────────────────────────────────────────

def generate_next_id(sheet_key: str, prefix: str | None = None) -> str:
    """
    Сгенерировать следующий ID для записи.

    Читает все записи листа, находит максимальный числовой суффикс
    и возвращает PREFIX-N+1.

    Args:
        sheet_key: ключ листа (определяет дефолтный префикс)
        prefix: явный префикс (если None — берётся из _ID_PREFIXES)

    Returns:
        Строка вида "BIZ-001", "PRS-042" и т.д.

    Examples:
        generate_next_id("biz_registry")          → "BIZ-001"
        generate_next_id("people_registry")        → "PRS-001"
        generate_next_id("roadmap_stages", "STAGE")→ "STAGE-001"
    """
    import re

    if prefix is None:
        prefix = _ID_PREFIXES.get(sheet_key, sheet_key.upper()[:3])

    try:
        sheet = get_business_sheet(sheet_key)
        all_values = sheet.get_all_values()
    except Exception:
        return f"{prefix}-001"

    # Ищем числа в первой колонке (пропускаем заголовок)
    numbers = []
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    for row in all_values[1:]:
        if row and row[0]:
            m = pattern.match(str(row[0]))
            if m:
                numbers.append(int(m.group(1)))

    next_num = max(numbers, default=0) + 1
    return f"{prefix}-{next_num:03d}"


# ─────────────────────────────────────────────────────────────
# Вспомогательные
# ─────────────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    """Конвертировать номер колонки в букву: 1→A, 26→Z, 27→AA."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_spreadsheet_url() -> str:
    """Вернуть URL таблицы Business Core."""
    biz_id = os.getenv("BUSINESS_SPREADSHEET_ID", "")
    if not biz_id:
        return "BUSINESS_SPREADSHEET_ID не задан"
    return f"https://docs.google.com/spreadsheets/d/{biz_id}/edit"


def is_enabled() -> bool:
    """Проверить, включён ли Business Core (BUSINESS_CORE_ENABLED=true)."""
    return os.getenv("BUSINESS_CORE_ENABLED", "false").lower() == "true"


def check_configuration() -> dict:
    """
    Проверить конфигурацию Business Core.

    Returns:
        {
            "ok": bool,
            "issues": list[str],
            "spreadsheet_id": str,
            "enabled": bool,
            "service_account": str,
        }
    """
    issues = []

    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    biz_id = os.getenv("BUSINESS_SPREADSHEET_ID", "")
    enabled = is_enabled()

    if not creds_file:
        issues.append("GOOGLE_CREDENTIALS_FILE не задан в .env")
    elif not os.path.exists(creds_file):
        issues.append(f"Файл credentials не найден: {creds_file}")

    if not biz_id:
        issues.append("BUSINESS_SPREADSHEET_ID не задан в .env")

    service_account = "неизвестен"
    if creds_file and os.path.exists(creds_file):
        try:
            import json
            with open(creds_file) as f:
                service_account = json.load(f).get("client_email", "неизвестен")
        except Exception:
            pass

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "spreadsheet_id": biz_id,
        "enabled": enabled,
        "service_account": service_account,
        "url": get_spreadsheet_url(),
    }


# ─────────────────────────────────────────────────────────────
# CLI: python3 business_core/sheets.py
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Business Core Sheets — проверка конфигурации\n")
    cfg = check_configuration()

    print(f"Service account:      {cfg['service_account']}")
    print(f"Spreadsheet ID:       {cfg['spreadsheet_id']}")
    print(f"Business Core enabled:{cfg['enabled']}")
    print(f"URL:                  {cfg['url']}")

    if cfg["issues"]:
        print("\n❌ Проблемы:")
        for issue in cfg["issues"]:
            print(f"  • {issue}")
        sys.exit(1)

    print("\n✅ Конфигурация корректна")
    print("\nЗапустить инициализацию? (yes/no): ", end="")
    answer = input().strip().lower()
    if answer == "yes":
        init_business_core_sheets()
    else:
        print("Инициализация отменена.")
