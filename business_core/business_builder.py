"""
Business Builder — конструктор нового бизнес-направления.

Фаза 1: локальные данные (модели, стартовые проекты).
Фаза Drive: provision_biz_drive() / save_drive_info_to_sheets() — безопасная обёртка
            над integrations.google_drive_adapter. Не ломает основной GTD-поток:
            любая ошибка Drive логируется и возвращается как {ok: False}.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from business_core.models import BusinessArea
from business_core.business_registry import create_business_record, validate_business_record

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Стандартная структура папок для каждого бизнеса
# ─────────────────────────────────────────────────────────────

STANDARD_FOLDERS = [
    "01 Стратегия",
    "02 Услуги",
    "03 Процессы",
    "04 Маркетинг",
    "05 Продажи",
    "06 Клиенты",
    "07 Производство",
    "08 Финансы",
    "09 Команда",
    "10 Автоматизация",
    "11 Аналитика",
    "12 Архив",
]

# ─────────────────────────────────────────────────────────────
# Стартовые проекты для любого нового бизнеса
# ─────────────────────────────────────────────────────────────

STARTER_PROJECTS_TEMPLATE = [
    {
        "name": "Описать услуги направления",
        "outcome": "Все услуги задокументированы в Service Catalog с этапами, ценами и чек-листами",
        "area_folder": "02 Услуги",
        "priority": "Высокий",
        "context": "@Computer",
        "first_action": "Составить список всех услуг направления и их текущих цен",
    },
    {
        "name": "Собрать текущих клиентов",
        "outcome": "В People Registry внесены все текущие клиенты направления с контактами",
        "area_folder": "06 Клиенты",
        "priority": "Высокий",
        "context": "@Computer",
        "first_action": "Выгрузить список всех клиентов из мессенджеров и таблиц",
    },
    {
        "name": "Описать процесс продаж",
        "outcome": "Воронка продаж задокументирована: от заявки до закрытой сделки",
        "area_folder": "05 Продажи",
        "priority": "Высокий",
        "context": "@Computer",
        "first_action": "Описать текущие этапы работы с клиентом от первого контакта до оплаты",
    },
    {
        "name": "Описать процесс производства",
        "outcome": "Чек-листы производства для каждой услуги задокументированы",
        "area_folder": "07 Производство",
        "priority": "Средний",
        "context": "@Computer",
        "first_action": "Записать все шаги выполнения основной услуги направления",
    },
    {
        "name": "Настроить автоматизацию направления",
        "outcome": "Ключевые рутинные процессы автоматизированы",
        "area_folder": "10 Автоматизация",
        "priority": "Средний",
        "context": "@Computer",
        "first_action": "Составить список рутинных задач, которые можно автоматизировать",
    },
    {
        "name": "Создать базу знаний направления",
        "outcome": "Ключевые знания и инструкции зафиксированы в общедоступном формате",
        "area_folder": "03 Процессы",
        "priority": "Средний",
        "context": "@Computer",
        "first_action": "Создать структуру папки базы знаний: инструкции, шаблоны, FAQ",
    },
    {
        "name": "Настроить финансовый учёт направления",
        "outcome": "Доходы и расходы по направлению фиксируются и анализируются ежемесячно",
        "area_folder": "08 Финансы",
        "priority": "Средний",
        "context": "@Computer",
        "first_action": "Создать таблицу учёта доходов и расходов для направления",
    },
]


# ─────────────────────────────────────────────────────────────
# Основная функция
# ─────────────────────────────────────────────────────────────

def create_business_area(
    name: str,
    cities: Optional[list[str]] = None,
    owner: str = "",
    priority: str = "medium",
    status: str = "test",
    description: str = "",
    existing_ids: Optional[list[str]] = None,
) -> dict:
    """
    Создаёт полную структуру нового бизнес-направления.

    Фаза 1: только локальные данные, без Google API.
    Возвращает словарь, готовый к записи в Google Sheets на следующем этапе.

    Args:
        name: Название бизнес-направления.
        cities: Список городов. По умолчанию ["Алматы"].
        owner: Ответственный.
        priority: high / medium / low.
        status: active / test / hold / archived.
        description: Описание бизнеса.
        existing_ids: Список уже существующих BIZ-IDs.

    Returns:
        {
            "business": BusinessArea,
            "folder_structure": list[str],
            "starter_projects": list[dict],
            "gtd_projects_to_create": list[dict],
            "summary": str,
        }
    """
    if cities is None:
        cities = ["Алматы"]

    # 1. Создаём объект бизнеса
    business = create_business_record(
        name=name,
        cities=cities,
        owner=owner,
        priority=priority,
        status=status,
        description=description,
        existing_ids=existing_ids or [],
    )

    # 2. Генерируем структуру папок
    folder_structure = _build_folder_structure(name)
    business.folder_structure = folder_structure

    # 3. Генерируем стартовые проекты
    starter_projects = _build_starter_projects(business.id, name)
    business.starter_projects = starter_projects

    # 4. Формируем GTD-проекты (для будущей записи в Google Sheets)
    gtd_projects = _build_gtd_projects(business.id, name, starter_projects)

    # 5. Валидируем
    is_valid, errors = validate_business_record(business)

    return {
        "business": business,
        "business_dict": business.to_dict(),
        "folder_structure": folder_structure,
        "starter_projects": starter_projects,
        "gtd_projects_to_create": gtd_projects,
        "is_valid": is_valid,
        "validation_errors": errors,
        "summary": _build_summary(business, folder_structure, starter_projects),
    }


# ─────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────

def _build_folder_structure(business_name: str) -> list[str]:
    """Генерирует список папок для нового бизнеса."""
    return list(STANDARD_FOLDERS)


def _build_starter_projects(biz_id: str, business_name: str) -> list[dict]:
    """Генерирует стартовые проекты с привязкой к бизнесу."""
    projects = []
    for template in STARTER_PROJECTS_TEMPLATE:
        project = {
            "business_id": biz_id,
            "name": f"{template['name']}",
            "full_name": f"{template['name']} [{business_name}]",
            "outcome": template["outcome"],
            "area_folder": template["area_folder"],
            "priority": template["priority"],
            "context": template["context"],
            "first_action": template["first_action"],
            "status": "active",
            "created_at": datetime.now().isoformat(),
        }
        projects.append(project)
    return projects


def _build_gtd_projects(
    biz_id: str,
    business_name: str,
    starter_projects: list[dict],
) -> list[dict]:
    """
    Формирует список проектов в GTD-формате для последующей записи в Google Sheets.
    Структура соответствует колонкам листа PROJECTS в GTD Master.
    """
    gtd_projects = []

    # Главный проект — запуск направления
    gtd_projects.append({
        "gtd_type": "project",
        "name": f"Запустить бизнес-направление: {business_name}",
        "outcome": f"Направление '{business_name}' полностью настроено и работает",
        "area": "Business",
        "priority": "Высокий",
        "status": "active",
        "business_id": biz_id,
        "first_action": f"Открыть BUSINESS_CORE_PLAN.md и запустить /newbiz {business_name}",
        "context": "@Computer",
    })

    # Проект на каждый стартовый блок
    for proj in starter_projects:
        gtd_projects.append({
            "gtd_type": "project",
            "name": proj["full_name"],
            "outcome": proj["outcome"],
            "area": "Business",
            "priority": proj["priority"],
            "status": "active",
            "business_id": biz_id,
            "first_action": proj["first_action"],
            "context": proj["context"],
        })

    return gtd_projects


def _build_summary(
    business: BusinessArea,
    folder_structure: list[str],
    starter_projects: list[dict],
) -> str:
    """Форматирует итоговое сообщение для Telegram."""
    cities_str = ", ".join(business.cities)
    folders_count = len(folder_structure)
    projects_count = len(starter_projects)
    actions_count = sum(1 for p in starter_projects if p.get("first_action"))

    lines = [
        f"✅ Создано бизнес-направление",
        f"",
        f"🏢 {business.name}",
        f"🆔 {business.id} · Статус: {business.status} · Приоритет: {business.priority}",
        f"📍 Города: {cities_str}",
        f"",
        f"📁 Структура папок ({folders_count}):",
    ]
    for folder in folder_structure:
        lines.append(f"   {folder}")

    lines.append(f"")
    lines.append(f"📋 Стартовые проекты ({projects_count}):")
    for proj in starter_projects:
        lines.append(f"   • {proj['name']}")
        lines.append(f"     → {proj['first_action']}")

    lines.append(f"")
    lines.append(f"⚡ Next Actions: {actions_count}")
    lines.append(f"")
    lines.append(f"📌 Следующий шаг:")
    lines.append(f"   Добавить направление в Google Sheets: /biz_save {business.id}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Google Drive интеграция (безопасная — не ломает GTD)
# ─────────────────────────────────────────────────────────────

def provision_biz_drive(biz_id: str, biz_name: str) -> dict:
    """
    Создать папку бизнеса в Google Drive.

    Phase 6A: сначала пробует per-biz Drive Root ID из BIZ_REGISTRY,
    если не задан — fallback на GDRIVE_BIZ_ROOT_FOLDER_ID из .env.
    Если ни того, ни другого нет — возвращает {ok: False}.

    Идемпотентно: если папка уже есть — возвращает её.

    Args:
        biz_id:   ID бизнеса (например "BIZ-001")
        biz_name: Название бизнеса

    Returns:
        {
            "ok":         bool,
            "folder_id":  str | None,
            "folder_url": str | None,
            "error":      str | None,
        }
    """
    # Phase 6A: get_business_drive_root_id уже применяет приоритеты
    gdrive_root = get_business_drive_root_id(biz_id)
    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if not gdrive_root or not creds_file:
        log.debug("provision_biz_drive: Drive root или credentials не заданы — пропуск")
        return {"ok": False, "folder_id": None, "folder_url": None,
                "error": "GDRIVE_BIZ_ROOT_FOLDER_ID не задан в .env"}

    try:
        from integrations.google_drive_adapter import create_business_folder_structure

        result = create_business_folder_structure(
            biz_id=biz_id,
            biz_name=biz_name,
            dry_run=False,
            root_folder_id=gdrive_root,  # Phase 6A: явно передаём root
        )
        log.info(f"provision_biz_drive: {biz_id} → {result['business_folder_url']}")
        return {
            "ok":         True,
            "folder_id":  result["business_folder_id"],
            "folder_url": result["business_folder_url"],
            "error":      None,
        }
    except Exception as exc:
        log.warning(f"provision_biz_drive error (biz_id={biz_id}): {exc}")
        return {
            "ok":         False,
            "folder_id":  None,
            "folder_url": None,
            "error":      str(exc),
        }


def save_drive_info_to_sheets(
    biz_id:     str,
    folder_id:  str,
    folder_url: str,
) -> bool:
    """
    Сохранить Drive-ссылку и ID папки в BIZ_REGISTRY.

    Находит строку по biz_id, определяет позицию колонок
    "Google Drive" и "Drive Folder ID" по реальным заголовкам листа
    (не хардкодит номера колонок — безопасно при разном порядке).

    Args:
        biz_id:     ID бизнеса (первая колонка)
        folder_id:  Google Drive folder ID
        folder_url: ссылка на папку

    Returns:
        True если успешно, False если ошибка или строка не найдена
    """
    try:
        from business_core.sheets import (
            find_row_by_id, update_business_cell, get_business_sheet,
        )

        row_result = find_row_by_id("biz_registry", biz_id)
        if not row_result:
            log.warning(f"save_drive_info_to_sheets: biz_id '{biz_id}' не найден в листе")
            return False

        row_num, _row_dict = row_result
        actual_headers = get_business_sheet("biz_registry").row_values(1)

        if "Google Drive" in actual_headers:
            col = actual_headers.index("Google Drive") + 1
            update_business_cell("biz_registry", row_num, col, folder_url)
            log.debug(f"save_drive_info_to_sheets: 'Google Drive' col={col} ← {folder_url}")

        if "Drive Folder ID" in actual_headers:
            col = actual_headers.index("Drive Folder ID") + 1
            update_business_cell("biz_registry", row_num, col, folder_id)
            log.debug(f"save_drive_info_to_sheets: 'Drive Folder ID' col={col} ← {folder_id}")

        return True
    except Exception as exc:
        log.warning(f"save_drive_info_to_sheets error: {exc}")
        return False


# ─────────────────────────────────────────────────────────────
# Google Drive интеграция для клиентов
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Multi-Business Config helpers (Phase 6A)
# ─────────────────────────────────────────────────────────────

#: Допустимые типы бизнес-модели
BUSINESS_MODEL_TYPES = (
    "object_based",       # Узаконение — клиент → объект → услуга
    "person_case_based",  # Визы — клиент/компания → сотрудник → тип визы
    "program_based",      # Коучинг — клиент → программа
    "general",            # без специфики
)

#: Допустимые типы кейса в Roadmap
ROADMAP_CASE_TYPES = (
    "legalization_object",
    "visa_foreigner",
    "coaching_program",
    "general",
)


def normalize_biz_ids(value: str) -> list[str]:
    """
    Нормализовать строку Biz IDs в список ID.

    Примеры:
        "BIZ-001"                → ["BIZ-001"]
        "BIZ-001, BIZ-002"       → ["BIZ-001", "BIZ-002"]
        ""                       → []

    Args:
        value: строка из колонки "Biz IDs" в PEOPLE_REGISTRY

    Returns:
        list[str] — список BIZ-ID (без пустых строк)
    """
    if not value or not value.strip():
        return []
    return [x.strip() for x in value.replace(";", ",").split(",") if x.strip()]


def get_business_config(biz_id: str) -> dict:
    """
    Получить конфигурацию бизнеса из BIZ_REGISTRY.

    Безопасная — никогда не бросает исключение.
    Если новые Phase-6A колонки отсутствуют — возвращает дефолты.

    Args:
        biz_id: например "BIZ-001"

    Returns:
        {
            "id":                   str,
            "name":                 str,
            "status":               str,
            "cities":               list[str],   # из Cities JSON или из "Города"
            "default_city":         str,
            "business_model_type":  str,         # object_based / person_case_based / ...
            "drive_folder_id":      str,         # папка бизнеса (не root)
            "drive_root_id":        str,         # per-biz Drive root (Phase 6A)
            "drive_credentials":    str,         # ключ credentials
            "google_account_email": str,
            "sendpulse":            str,
            "waba":                 str,
            "instagram":            str,
            "binotel":              str,
            "found":                bool,        # False если biz_id не найден
        }
    """
    defaults = {
        "id":                   biz_id,
        "name":                 "",
        "status":               "",
        "cities":               [],
        "default_city":         "",
        "business_model_type":  "general",
        "drive_folder_id":      "",
        "drive_root_id":        "",
        "drive_credentials":    "",
        "google_account_email": "",
        "sendpulse":            "",
        "waba":                 "",
        "instagram":            "",
        "binotel":              "",
        "found":                False,
    }

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("biz_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return defaults

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h, fallback=""):
            c = _col(h)
            return (row[c].strip() if c is not None and c < len(row) else "") or fallback

        for row in all_values[1:]:
            if not row or row[0] != biz_id:
                continue

            # Города: сначала Cities JSON, потом старое поле "Города"
            cities_json_raw = _get(row, "Cities JSON")
            if cities_json_raw:
                try:
                    import json
                    cities = json.loads(cities_json_raw)
                except Exception:
                    cities = [c.strip() for c in cities_json_raw.split(",") if c.strip()]
            else:
                raw = _get(row, "Города")
                cities = [c.strip() for c in raw.split(",") if c.strip()]

            return {
                "id":                   row[0],
                "name":                 _get(row, "Название"),
                "status":               _get(row, "Статус"),
                "cities":               cities,
                "default_city":         _get(row, "Default City") or (cities[0] if cities else ""),
                "business_model_type":  _get(row, "Business Model Type", "general"),
                "drive_folder_id":      _get(row, "Drive Folder ID"),
                "drive_root_id":        _get(row, "Drive Root ID"),
                "drive_credentials":    _get(row, "Drive Credentials"),
                "google_account_email": _get(row, "Google Account Email"),
                "sendpulse":            _get(row, "SendPulse"),
                "waba":                 _get(row, "WABA"),
                "instagram":            _get(row, "Instagram"),
                "binotel":              _get(row, "Binotel"),
                "found":                True,
            }
    except Exception as exc:
        log.warning(f"get_business_config({biz_id}) error: {exc}")

    return defaults


def get_business_drive_root_id(biz_id: str) -> str:
    """
    Получить Drive Root ID для конкретного бизнеса.

    Логика приоритетов:
    1. BIZ_REGISTRY.Drive Root ID (per-biz, Phase 6A)
    2. GDRIVE_BIZ_ROOT_FOLDER_ID из .env (глобальный fallback)
    3. "" (Drive недоступен)

    Args:
        biz_id: ID бизнеса

    Returns:
        str — folder ID или "" если не найден
    """
    cfg = get_business_config(biz_id)
    if cfg["drive_root_id"]:
        log.debug(f"get_business_drive_root_id({biz_id}): per-biz root → {cfg['drive_root_id']}")
        return cfg["drive_root_id"]

    env_root = os.getenv("GDRIVE_BIZ_ROOT_FOLDER_ID", "").strip()
    if env_root:
        log.debug(f"get_business_drive_root_id({biz_id}): global .env root → {env_root}")
    return env_root


def get_business_model_type(biz_id: str) -> str:
    """
    Получить тип бизнес-модели.

    Returns:
        "object_based" | "person_case_based" | "program_based" | "general"
    """
    cfg = get_business_config(biz_id)
    model = cfg.get("business_model_type", "general")
    return model if model in BUSINESS_MODEL_TYPES else "general"


def get_person_biz_ids(person_id: str) -> list[str]:
    """
    Получить список BIZ-ID для клиента из PEOPLE_REGISTRY.

    Логика:
    1. Если заполнена колонка "Biz IDs" — используем её (Phase 6A)
    2. Иначе ищем biz_id по имени бизнеса из колонки "Бизнесы" (fallback)

    Args:
        person_id: PRS-ID

    Returns:
        list[str] — список BIZ-ID (может быть пустым)
    """
    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        id_col      = 0
        biz_ids_col = _col("Biz IDs")
        biz_col     = _col("Бизнесы")

        for row in all_values[1:]:
            if not row or row[0] != person_id:
                continue

            # Phase 6A: Biz IDs
            if biz_ids_col is not None and biz_ids_col < len(row) and row[biz_ids_col].strip():
                return normalize_biz_ids(row[biz_ids_col])

            # Fallback: старое поле "Бизнесы" (имя → ищем ID)
            if biz_col is not None and biz_col < len(row) and row[biz_col].strip():
                biz_name = row[biz_col].strip()
                biz_id = _get_biz_id_by_name(biz_name)
                return [biz_id] if biz_id != biz_name else []  # biz_id == name значит не найден

        return []
    except Exception as exc:
        log.warning(f"get_person_biz_ids({person_id}) error: {exc}")
        return []


def _normalize_name(name: str) -> str:
    """Нормализовать имя: trim + lower + убрать двойные пробелы."""
    import re
    return re.sub(r"\s+", " ", name.strip()).lower()


def find_existing_client(full_name: str, biz_name: str = "") -> Optional[dict]:
    """
    Найти существующего клиента в PEOPLE_REGISTRY.

    Поиск по нормализованному full_name (обязательно) +
    biz_name (если задан, проверяем что имя бизнеса совпадает или входит).

    Args:
        full_name: ФИО клиента
        biz_name:  название бизнеса (опционально — дополнительный фильтр)

    Returns:
        {
            "row_num":        int,    # номер строки в листе (1-based)
            "prs_id":         str,    # PRS-XXX
            "full_name":      str,    # ФИО из таблицы
            "drive_url":      str,    # ссылка на Drive-папку (или "")
            "drive_folder_id":str,    # Drive folder ID (или "")
        }
        или None если не найдено
    """
    if not full_name or not full_name.strip():
        return None

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return None

        headers = all_values[0]

        def _col(header):
            return headers.index(header) if header in headers else None

        id_col       = 0
        name_col     = _col("ФИО") or 1
        biz_col      = _col("Бизнесы") or 13
        drive_col    = _col("Google Drive")
        drive_id_col = _col("Drive Folder ID")

        norm_name = _normalize_name(full_name)
        norm_biz  = _normalize_name(biz_name) if biz_name else ""

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue

            row_name = _normalize_name(row[name_col] if name_col < len(row) else "")
            if row_name != norm_name:
                continue

            # Имя совпало — проверяем бизнес (если задан)
            if norm_biz:
                row_biz = _normalize_name(row[biz_col] if biz_col < len(row) else "")
                if row_biz and norm_biz not in row_biz and row_biz not in norm_biz:
                    continue  # другой бизнес — не наш клиент

            def _safe_get(col):
                if col is None:
                    return ""
                return row[col].strip() if col < len(row) else ""

            return {
                "row_num":         i,
                "prs_id":          row[id_col],
                "full_name":       row[name_col] if name_col < len(row) else full_name,
                "drive_url":       _safe_get(drive_col),
                "drive_folder_id": _safe_get(drive_id_col),
            }

    except Exception as exc:
        log.warning(f"find_existing_client error: {exc}")

    return None


def _get_biz_id_by_name(biz_name: str) -> str:
    """
    Найти BIZ-ID по названию бизнеса из BIZ_REGISTRY.
    Если не найдено — вернуть biz_name как fallback.
    """
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("biz_registry")
        for row in rows:
            if row.get("Название", "").strip() == biz_name.strip():
                return row.get("ID", biz_name)
    except Exception as exc:
        log.debug(f"_get_biz_id_by_name: не удалось прочитать BIZ_REGISTRY: {exc}")
    return biz_name


def provision_client_drive(
    prs_id: str,
    full_name: str,
    biz_name: str,
    roadmap_id: Optional[str] = None,
) -> dict:
    """
    Создать папку клиента в Google Drive внутри папки бизнеса.

    Требует GDRIVE_BIZ_ROOT_FOLDER_ID и GOOGLE_CREDENTIALS_FILE.
    Если не заданы — возвращает {ok: False} без ошибки.
    Если Drive API упал — возвращает {ok: False, error: str}.

    Идемпотентно: повторный вызов вернёт существующую папку.

    Args:
        prs_id:     ID клиента в PEOPLE_REGISTRY (например "PRS-001")
        full_name:  ФИО клиента
        biz_name:   Название бизнеса (для поиска biz_id и пути к папке)
        roadmap_id: ID дорожной карты (опционально — добавляется к имени папки)

    Returns:
        {
            "ok":         bool,
            "folder_id":  str | None,
            "folder_url": str | None,
            "biz_id":     str | None,
            "error":      str | None,
        }
    """
    if not biz_name:
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "biz_id": None, "error": "biz_name не задан",
        }

    # Phase 6A: используем per-biz root если есть, иначе глобальный из .env
    biz_id_resolved = _get_biz_id_by_name(biz_name)
    gdrive_root = get_business_drive_root_id(biz_id_resolved)
    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if not gdrive_root or not creds_file:
        log.debug("provision_client_drive: Drive root или credentials не заданы — пропуск")
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "biz_id": None, "error": "GDRIVE_BIZ_ROOT_FOLDER_ID не задан в .env",
        }

    try:
        biz_id = biz_id_resolved

        from integrations.google_drive_adapter import setup_biz_client_folder
        result = setup_biz_client_folder(
            biz_id=biz_id,
            biz_name=biz_name,
            client_name=full_name,
            roadmap_id=roadmap_id,
            dry_run=False,
            root_folder_id=gdrive_root,  # Phase 6A: явно передаём root
        )
        log.info(f"provision_client_drive: {prs_id} / {full_name} → {result['client_folder_url']}")
        return {
            "ok":         True,
            "folder_id":  result["client_folder_id"],
            "folder_url": result["client_folder_url"],
            "biz_id":     biz_id,
            "error":      None,
        }
    except Exception as exc:
        log.warning(f"provision_client_drive error (prs_id={prs_id}): {exc}")
        return {
            "ok":         False,
            "folder_id":  None,
            "folder_url": None,
            "biz_id":     None,
            "error":      str(exc),
        }


def save_client_drive_to_sheets(
    prs_id:     str,
    folder_id:  str,
    folder_url: str,
) -> bool:
    """
    Сохранить Drive-ссылку и ID папки клиента в PEOPLE_REGISTRY.

    Ищет строку по prs_id, определяет позицию колонок
    "Google Drive" и "Drive Folder ID" по реальным заголовкам.

    Args:
        prs_id:     ID клиента (первая колонка PEOPLE_REGISTRY)
        folder_id:  Google Drive folder ID
        folder_url: ссылка на папку клиента

    Returns:
        True если успешно, False если ошибка или строка не найдена
    """
    try:
        from business_core.sheets import (
            find_row_by_id, update_business_cell, get_business_sheet,
        )

        row_result = find_row_by_id("people_registry", prs_id)
        if not row_result:
            log.warning(f"save_client_drive_to_sheets: prs_id '{prs_id}' не найден")
            return False

        row_num, _ = row_result
        actual_headers = get_business_sheet("people_registry").row_values(1)

        if "Google Drive" in actual_headers:
            col = actual_headers.index("Google Drive") + 1
            update_business_cell("people_registry", row_num, col, folder_url)
            log.debug(f"save_client_drive_to_sheets: 'Google Drive' col={col} ← {folder_url}")

        if "Drive Folder ID" in actual_headers:
            col = actual_headers.index("Drive Folder ID") + 1
            update_business_cell("people_registry", row_num, col, folder_id)
            log.debug(f"save_client_drive_to_sheets: 'Drive Folder ID' col={col} ← {folder_id}")

        return True
    except Exception as exc:
        log.warning(f"save_client_drive_to_sheets error: {exc}")
        return False


def get_business_creation_status(result: dict) -> str:
    """Возвращает краткий статус создания бизнеса."""
    biz = result.get("business")
    if not biz:
        return "❌ Ошибка: бизнес не создан"

    errors = result.get("validation_errors", [])
    if errors:
        return f"⚠️ Создан с ошибками:\n" + "\n".join(f"  • {e}" for e in errors)

    projects_count = len(result.get("starter_projects", []))
    folders_count = len(result.get("folder_structure", []))
    return (
        f"✅ [{biz.id}] {biz.name}\n"
        f"   📁 {folders_count} папок · 📋 {projects_count} проектов"
    )
