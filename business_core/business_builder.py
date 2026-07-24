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
from business_core.person_manager import (
    append_person_biz_id as pm_append_person_biz_id,
    update_person_drive_info as pm_update_person_drive_info,
)

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
    # Phase 6C: resolve_drive_root_for_business возвращает source + ok
    root_info  = resolve_drive_root_for_business(biz_id)
    gdrive_root = root_info["root_id"]
    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if not root_info["ok"] or not gdrive_root:
        log.debug(f"provision_biz_drive({biz_id}): Drive root не настроен — пропуск")
        return {"ok": False, "folder_id": None, "folder_url": None,
                "error": root_info.get("error", "Drive root not configured")}

    if not creds_file:
        return {"ok": False, "folder_id": None, "folder_url": None,
                "error": "GOOGLE_CREDENTIALS_FILE не задан в .env"}

    try:
        from integrations.google_drive_adapter import create_business_folder_structure

        result = create_business_folder_structure(
            biz_id=biz_id,
            biz_name=biz_name,
            dry_run=False,
            root_folder_id=gdrive_root,  # per-biz или глобальный root
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
    Получить Drive Root ID для конкретного бизнеса (строковая версия).

    Логика приоритетов:
    1. BIZ_REGISTRY.Drive Root ID (per-biz, Phase 6A)
    2. GDRIVE_BIZ_ROOT_FOLDER_ID из .env (глобальный fallback)
    3. "" (Drive недоступен)

    Args:
        biz_id: ID бизнеса

    Returns:
        str — folder ID или "" если не найден
    """
    return resolve_drive_root_for_business(biz_id)["root_id"]


def resolve_drive_root_for_business(biz_id: str) -> dict:
    """
    Разрешить Drive Root для конкретного бизнеса с указанием источника.

    Приоритеты:
    1. BIZ_REGISTRY.Drive Root ID      → source = "biz_registry"
    2. GDRIVE_BIZ_ROOT_FOLDER_ID .env  → source = "env"
    3. Нет root                        → ok = False

    Никогда не бросает исключение — безопасна для использования в GTD-потоке.

    Args:
        biz_id: ID бизнеса (например "BIZ-001")

    Returns:
        {
            "root_id": str,            # "" если не найден
            "source":  str,            # "biz_registry" | "env" | "none"
            "ok":      bool,           # False если root не найден
            "error":   str | None,
        }
    """
    try:
        cfg = get_business_config(biz_id)
        if cfg["drive_root_id"]:
            log.debug(f"resolve_drive_root({biz_id}): per-biz root → {cfg['drive_root_id']}")
            return {
                "root_id": cfg["drive_root_id"],
                "source":  "biz_registry",
                "ok":      True,
                "error":   None,
            }
    except Exception as exc:
        log.warning(f"resolve_drive_root({biz_id}): BIZ_REGISTRY error: {exc}")

    env_root = os.getenv("GDRIVE_BIZ_ROOT_FOLDER_ID", "").strip()
    if env_root:
        log.debug(f"resolve_drive_root({biz_id}): global .env root → {env_root}")
        return {
            "root_id": env_root,
            "source":  "env",
            "ok":      True,
            "error":   None,
        }

    return {
        "root_id": "",
        "source":  "none",
        "ok":      False,
        "error":   "Drive root не настроен: задайте Drive Root ID в BIZ_REGISTRY или GDRIVE_BIZ_ROOT_FOLDER_ID в .env",
    }


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

    Phase 23D-1: logic relocated to business_core.person_manager — this
    stays as a thin backward-compatible delegator so every existing
    caller of business_builder.get_person_biz_ids() keeps working
    unchanged (business_builder.py itself included).
    """
    from business_core.person_manager import get_person_biz_ids as _impl
    return _impl(person_id)


# ─────────────────────────────────────────────────────────────
# Phase 6B: расширенная дедупликация клиентов
# ─────────────────────────────────────────────────────────────

def normalize_person_name(name: str) -> str:
    """
    Нормализовать ФИО: trim → убрать множественные пробелы → lower.

    Phase 23D-1: logic relocated to business_core.person_manager — this
    stays as a thin backward-compatible delegator.

    Примеры:
        "  Иван  Петров " → "иван петров"
        "ИВАН ПЕТРОВ"     → "иван петров"
    """
    from business_core.person_manager import normalize_person_name as _impl
    return _impl(name)


def normalize_phone(phone: str) -> str:
    """
    Нормализовать телефонный номер: оставить только цифры.

    Phase 23D-1: logic relocated to business_core.person_manager — this
    stays as a thin backward-compatible delegator.

    Примеры:
        "+7 (777) 123-45-67" → "77771234567"
        "8 777 123 45 67"    → "87771234567"
        ""                   → ""
    """
    from business_core.person_manager import normalize_phone as _impl
    return _impl(phone)


def find_existing_person(
    name:   Optional[str] = None,
    phone:  Optional[str] = None,
    biz_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Найти существующего человека в PEOPLE_REGISTRY.

    Phase 23D-1: logic relocated to business_core.person_manager — this
    stays as a thin backward-compatible delegator so newclient_confirm()
    (business_core/telegram_handlers.py) keeps working completely
    unchanged. See person_manager.find_existing_person()'s own
    docstring for the exact search/return-shape contract preserved here.
    """
    from business_core.person_manager import find_existing_person as _impl
    return _impl(name=name, phone=phone, biz_id=biz_id)


def add_biz_id_to_person(person_id: str, biz_id: str) -> bool:
    """
    Добавить biz_id в колонку "Biz IDs" существующего клиента.

    Phase 23D-3B2: logic relocated to
    business_core.person_manager.append_person_biz_id() — this stays as
    a thin backward-compatible delegator so every existing caller
    (newclient_confirm's OTHER_BIZ branch, newobject_cmd) keeps working
    unchanged. True only on an actual, error-free change — duplicate
    Biz ID, missing person, empty input, and any manager-level error
    all translate to False, exactly as before.

    Returns:
        True если обновлено, False если уже было, не найдено или ошибка
    """
    result = pm_append_person_biz_id(person_id, biz_id)
    return bool(result.get("ok") and result.get("changed"))


def update_person_drive_info(person_id: str, folder_id: str, folder_url: str) -> bool:
    """
    Обновить Drive-информацию существующего клиента (дозаполнение).

    Phase 23D-3B2: logic relocated to
    business_core.person_manager.update_person_drive_info() — this
    stays as a thin backward-compatible delegator so every existing
    caller (newclient_confirm's Drive branch, provision_object_drive)
    keeps working unchanged. True only on an actual, error-free change —
    both-fields-already-populated, missing person, empty input, and any
    manager-level error all translate to False, exactly as before.

    Returns:
        True если обновлено, False если уже было, не найдено или ошибка
    """
    result = pm_update_person_drive_info(person_id, folder_id=folder_id, folder_url=folder_url)
    return bool(result.get("ok") and result.get("changed"))


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


def _normalize_biz_key(s: str) -> str:
    """trim + casefold + схлопнуть внутренние пробелы — для сравнения
    названий/ID бизнеса без учёта регистра и лишних пробелов."""
    return " ".join((s or "").strip().casefold().split())


def resolve_business(value: str) -> dict:
    """
    Phase 13A: единый resolver бизнеса — принимает Biz ID ("BIZ-001"),
    точное название, название в другом регистре или с лишними пробелами
    и резолвит его в ОДИН канонический Biz ID.

    Не использует fuzzy-matching намеренно (см. Phase 13A) — только
    trim/casefold/схлопывание пробелов, чтобы не привязать клиента к
    неверному бизнесу по случайному частичному совпадению.

    Returns:
        {"ok": True, "biz_id": "BIZ-001", "biz_name": "Узаконение недвижимости"}
        или
        {"ok": False, "reason": "not_found" | "ambiguous",
         "active_businesses": [{"id": "BIZ-001", "name": "..."}, ...]}
    """
    from business_core.sheets import read_business_sheet

    try:
        rows = read_business_sheet("biz_registry")
    except Exception as exc:
        log.warning(f"resolve_business: не удалось прочитать BIZ_REGISTRY: {exc}")
        rows = []

    active_businesses = [
        {"id": r.get("ID", ""), "name": r.get("Название", "")}
        for r in rows
        if r.get("Статус", "") == "active"
    ]

    key = _normalize_biz_key(value)
    if not key:
        return {"ok": False, "reason": "not_found", "active_businesses": active_businesses}

    id_matches = {
        r.get("ID", "") for r in rows
        if _normalize_biz_key(r.get("ID", "")) == key
    }
    if len(id_matches) == 1:
        biz_id = next(iter(id_matches))
        biz_row = next((r for r in rows if r.get("ID", "") == biz_id), {})
        return {"ok": True, "biz_id": biz_id, "biz_name": biz_row.get("Название", "")}
    if len(id_matches) > 1:
        return {"ok": False, "reason": "ambiguous", "active_businesses": active_businesses}

    name_matches = {
        r.get("ID", "") for r in rows
        if _normalize_biz_key(r.get("Название", "")) == key
    }
    if len(name_matches) == 1:
        biz_id = next(iter(name_matches))
        biz_row = next((r for r in rows if r.get("ID", "") == biz_id), {})
        return {"ok": True, "biz_id": biz_id, "biz_name": biz_row.get("Название", "")}
    if len(name_matches) > 1:
        return {"ok": False, "reason": "ambiguous", "active_businesses": active_businesses}

    return {"ok": False, "reason": "not_found", "active_businesses": active_businesses}


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

    # Phase 6C: per-biz root через resolve_drive_root_for_business
    biz_id_resolved = _get_biz_id_by_name(biz_name)
    root_info   = resolve_drive_root_for_business(biz_id_resolved)
    gdrive_root = root_info["root_id"]
    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if not root_info["ok"] or not gdrive_root:
        log.debug(f"provision_client_drive({biz_id_resolved}): Drive root не настроен — пропуск")
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "biz_id": None,
            "error": root_info.get("error", "Drive root not configured"),
        }

    if not creds_file:
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "biz_id": None, "error": "GOOGLE_CREDENTIALS_FILE не задан в .env",
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
            root_folder_id=gdrive_root,  # per-biz или глобальный root
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


# ═══════════════════════════════════════════════════════════════
# Phase 7A: OBJECT_REGISTRY helpers
# ═══════════════════════════════════════════════════════════════

def generate_object_id() -> str:
    """
    Сгенерировать следующий OBJ ID из OBJECT_REGISTRY.

    Формат: OBJ-001, OBJ-002, ...
    Безопасно работает на пустом листе.

    Returns:
        str — следующий OBJ ID
    """
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("object_registry")
    except Exception as exc:
        log.warning(f"generate_object_id error: {exc}")
        return "OBJ-001"


def create_object_record(
    client_id:          str,
    biz_id:             str,
    city:               str,
    address:            str,
    cadastral_number:   str = "",
    area_m2:            str = "",
    object_type:        str = "",
    object_status:      str = "new",
    current_service_id: str = "",
    notes:              str = "",
    drive_folder_id:    str = "",
    google_drive_url:   str = "",
) -> dict:
    """
    Создать запись объекта недвижимости в OBJECT_REGISTRY.

    Args:
        client_id:          PRS-ID клиента (обязательный)
        biz_id:             BIZ-ID бизнеса (обязательный)
        city:               Город (обязательный)
        address:            Адрес (обязательный)
        cadastral_number:   Кадастровый номер
        area_m2:            Площадь в м²
        object_type:        Тип объекта (квартира / дом / участок / коммерческая)
        object_status:      Статус — по умолчанию "new"
        current_service_id: SVC-ID текущей услуги
        notes:              Примечания
        drive_folder_id:    Google Drive Folder ID (если уже известен)
        google_drive_url:   Google Drive ссылка (если уже известна)

    Returns:
        {
            "ok":     bool,
            "obj_id": str,
            "error":  str | None,
        }
    """
    if not client_id or not biz_id or not city or not address:
        return {
            "ok": False, "obj_id": "",
            "error": "Обязательные поля: client_id, biz_id, city, address",
        }

    try:
        from business_core.sheets import (
            append_business_row,
            get_business_sheet,
            row_from_header_map,
        )
        now    = datetime.now().strftime("%Y-%m-%d")
        obj_id = generate_object_id()

        # Phase 10.2B.5: строка формируется по ФАКТИЧЕСКИМ заголовкам
        # листа OBJECT_REGISTRY, а не по жёсткой позиции — не зависит
        # от порядка колонок и не смещает значения в чужие колонки.
        sheet   = get_business_sheet("object_registry")
        headers = sheet.row_values(1)

        required_headers = [
            "OBJ ID", "Client ID", "Biz ID", "City", "Address",
            "Cadastral Number", "Area m2", "Object Type", "Object Status",
            "Current Service ID", "Roadmap ID", "Drive Folder ID",
            "Google Drive", "Notes", "Created At", "Last Updated",
        ]
        missing_headers = [h for h in required_headers if h not in headers]
        if missing_headers:
            raise ValueError(
                f"OBJECT_REGISTRY: отсутствуют обязательные колонки {missing_headers}. "
                f"Запись объекта остановлена, ничего не записано."
            )

        row = row_from_header_map(headers, {
            "OBJ ID":             obj_id,
            "Client ID":          client_id,
            "Biz ID":             biz_id,
            "City":               city,
            "Address":            address,
            "Cadastral Number":   cadastral_number,
            "Area m2":            area_m2,
            "Object Type":        object_type,
            "Object Status":      object_status,
            "Current Service ID": current_service_id,
            "Roadmap ID":         "",
            "Drive Folder ID":    drive_folder_id,
            "Google Drive":       google_drive_url,
            "Notes":              notes,
            "Created At":         now,
            "Last Updated":       now,
        })
        append_business_row("object_registry", row)
        log.info(f"create_object_record: {obj_id} / {client_id} / {address}")
        return {"ok": True, "obj_id": obj_id, "error": None}

    except Exception as exc:
        log.error(f"create_object_record error: {exc}")
        return {"ok": False, "obj_id": "", "error": str(exc)}


def find_objects_by_client(client_id: str, biz_id: Optional[str] = None) -> list[dict]:
    """
    Найти объекты клиента в OBJECT_REGISTRY.

    Args:
        client_id: PRS-ID клиента
        biz_id:    BIZ-ID для фильтрации (опционально)

    Returns:
        list[dict] — список объектов (пустой если не найдено)
    """
    if not client_id:
        return []

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h):
            c = _col(h)
            return (row[c].strip() if c is not None and c < len(row) else "")

        results = []
        for row in all_values[1:]:
            if not row or not row[0]:
                continue
            if _get(row, "Client ID") != client_id:
                continue
            if biz_id and _get(row, "Biz ID") != biz_id:
                continue
            results.append({
                "obj_id":             _get(row, "OBJ ID"),
                "client_id":          _get(row, "Client ID"),
                "biz_id":             _get(row, "Biz ID"),
                "city":               _get(row, "City"),
                "address":            _get(row, "Address"),
                "cadastral_number":   _get(row, "Cadastral Number"),
                "area_m2":            _get(row, "Area m2"),
                "object_type":        _get(row, "Object Type"),
                "object_status":      _get(row, "Object Status"),
                "current_service_id": _get(row, "Current Service ID"),
                "roadmap_id":         _get(row, "Roadmap ID"),
                "drive_folder_id":    _get(row, "Drive Folder ID"),
                "google_drive":       _get(row, "Google Drive"),
                "notes":              _get(row, "Notes"),
                "created_at":         _get(row, "Created At"),
            })
        return results

    except Exception as exc:
        log.warning(f"find_objects_by_client({client_id}) error: {exc}")
        return []


def find_object_by_id(obj_id: str) -> Optional[dict]:
    """
    Найти объект по OBJ ID.

    Returns:
        dict или None
    """
    if not obj_id:
        return None

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return None

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h):
            c = _col(h)
            return row[c].strip() if c is not None and c < len(row) else ""

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue
            if _get(row, "OBJ ID") == obj_id:
                return {
                    "row_num":            i,
                    "obj_id":             _get(row, "OBJ ID"),
                    "client_id":          _get(row, "Client ID"),
                    "biz_id":             _get(row, "Biz ID"),
                    "city":               _get(row, "City"),
                    "address":            _get(row, "Address"),
                    "cadastral_number":   _get(row, "Cadastral Number"),
                    "area_m2":            _get(row, "Area m2"),
                    "object_type":        _get(row, "Object Type"),
                    "object_status":      _get(row, "Object Status"),
                    "current_service_id": _get(row, "Current Service ID"),
                    "roadmap_id":         _get(row, "Roadmap ID"),
                    "drive_folder_id":    _get(row, "Drive Folder ID"),
                    "google_drive":       _get(row, "Google Drive"),
                    "notes":              _get(row, "Notes"),
                    "created_at":         _get(row, "Created At"),
                    "last_updated":       _get(row, "Last Updated"),
                }

    except Exception as exc:
        log.warning(f"find_object_by_id({obj_id}) error: {exc}")

    return None


def update_object_drive_info(
    obj_id:          str,
    drive_folder_id: str = "",
    google_drive_url: str = "",
) -> bool:
    """
    Дозаполнить Drive Folder ID и Google Drive в OBJECT_REGISTRY.

    Обновляет только если текущее значение пустое.

    Args:
        obj_id:           OBJ ID
        drive_folder_id:  Google Drive folder ID
        google_drive_url: Google Drive URL

    Returns:
        True если обновлено, False если не нашли или уже заполнено
    """
    if not obj_id:
        return False

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        drive_id_col = _col("Drive Folder ID")
        drive_url_col = _col("Google Drive")
        updated = False

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0].strip() != obj_id:
                continue

            if drive_id_col is not None and drive_folder_id:
                cur = row[drive_id_col].strip() if drive_id_col < len(row) else ""
                if not cur:
                    sheet.update_cell(i, drive_id_col + 1, drive_folder_id)
                    updated = True

            if drive_url_col is not None and google_drive_url:
                cur = row[drive_url_col].strip() if drive_url_col < len(row) else ""
                if not cur:
                    sheet.update_cell(i, drive_url_col + 1, google_drive_url)
                    updated = True

            if updated:
                log.info(f"update_object_drive_info: {obj_id} → Drive дозаполнен")
            return updated

    except Exception as exc:
        log.warning(f"update_object_drive_info({obj_id}) error: {exc}")

    return False


def provision_object_drive(
    biz_id:      str,
    client_id:   str,
    obj_id:      str,
    city:        str,
    address:     str,
    object_type: str = "",
) -> dict:
    """
    Создать Drive-папку объекта недвижимости.

    Логика:
    1. Получить Drive root через resolve_drive_root_for_business(biz_id).
    2. Если root не настроен → ok=False, нет исключения.
    3. Если у клиента уже есть Drive Folder ID → использовать его.
    4. Иначе — создать/получить папку клиента через provision_client_drive.
    5. Создать папку объекта внутри папки клиента.
    6. Сохранить Drive Folder ID в OBJECT_REGISTRY.

    Returns:
        {
            "ok":         bool,
            "folder_id":  str | None,
            "folder_url": str | None,
            "error":      str | None,
        }
    """
    # 1. Drive root
    root_info = resolve_drive_root_for_business(biz_id)
    if not root_info["ok"]:
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "error": root_info.get("error", "Drive root not configured"),
        }

    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
    if not creds_file:
        return {
            "ok": False, "folder_id": None, "folder_url": None,
            "error": "GOOGLE_CREDENTIALS_FILE не задан",
        }

    try:
        # 2. Данные клиента (для имени папки и существующего Drive ID)
        client_data = find_existing_person(name=None, phone=None, biz_id=biz_id)

        # Ищем клиента по client_id напрямую
        client_folder_id  = ""
        client_name       = client_id  # fallback
        client_drive_url  = ""

        from business_core.person_manager import find_person_by_id
        person = find_person_by_id(client_id)
        if person:
            client_name      = person["full_name"] or client_id
            client_folder_id = person["drive_folder_id"] or ""
            client_drive_url = person["google_drive"] or ""

        # 3. Папку клиента нужно получить/создать если нет
        if not client_folder_id:
            # Получаем имя бизнеса для provision_client_drive
            biz_cfg  = get_business_config(biz_id)
            biz_name = biz_cfg.get("name", biz_id)
            cl_res   = provision_client_drive(
                prs_id=client_id, full_name=client_name, biz_name=biz_name
            )
            if cl_res["ok"]:
                client_folder_id = cl_res["folder_id"]
                # Дозаполнить в PEOPLE_REGISTRY
                update_person_drive_info(client_id, cl_res["folder_id"], cl_res["folder_url"])

        # 4. Создаём папку объекта
        from integrations.google_drive_adapter import create_object_folder
        biz_cfg  = get_business_config(biz_id)
        biz_name = biz_cfg.get("name", biz_id)

        result = create_object_folder(
            biz_id=biz_id,
            biz_name=biz_name,
            client_id=client_id,
            client_name=client_name,
            obj_id=obj_id,
            city=city,
            address=address,
            object_type=object_type,
            client_folder_id=client_folder_id or None,
            root_folder_id=root_info["root_id"],
        )

        if result["ok"]:
            # 5. Сохранить в OBJECT_REGISTRY
            update_object_drive_info(
                obj_id,
                drive_folder_id=result["folder_id"],
                google_drive_url=result["folder_url"],
            )
            log.info(f"provision_object_drive: {obj_id} → {result['folder_url']}")

        return result

    except Exception as exc:
        log.warning(f"provision_object_drive({obj_id}) error: {exc}")
        return {"ok": False, "folder_id": None, "folder_url": None, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════
# Phase 7B: Object → Service → Roadmap helpers
# ═══════════════════════════════════════════════════════════════

def generate_roadmap_id() -> str:
    """
    Сгенерировать следующий RM ID из ROADMAPS.

    Формат: RM-001, RM-002, ...
    Безопасно работает на пустом листе.
    """
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("roadmaps")
    except Exception as exc:
        log.warning(f"generate_roadmap_id error: {exc}")
        return "RM-001"


def _empty_roadmap_creation_result(error: str) -> dict:
    return {
        "ok": False, "roadmap_id": "", "error": error,
        "core_created": False, "stages_created": False,
        "stages_count": 0, "stage_ids": [], "used_template": False,
        "relation_copy_errors": (), "relation_copy_created_count": 0,
        "partial_success": False, "partial_failure": False, "warnings": (),
        "roadmap_created": False, "roadmap_reused": False,
        "template_id": "", "template_warning": None,
        "existing_stage_ids": [], "existing_stage_count": 0, "total_stage_count": 0,
        "relations_result": {"created_count": 0, "errors": ()},
        "knowledge_result": {"merged_inline": False},
    }


def create_roadmap_for_object(
    obj_id:      str,
    biz_id:      str,
    client_id:   str,
    service_id:  str,
    case_type:   str = "general",
    title:       str = "",
    notes:       str = "",
    template_id: str = "",
) -> dict:
    """
    Ensure/converge a Roadmap (+ Stages + Extension data) for this
    Object+Service — the single orchestration entry point for this
    flow (Phase 28C/28D/28E/28G).

    Convergent-retry semantics (Phase 28G): calling this twice with the
    same (obj_id, service_id) never creates a second Roadmap and never
    duplicates Stages — the second call finds the existing active
    Roadmap (duplicate key: (Object ID, Service ID), via
    roadmap_manager.find_active_roadmap_for_object() — never Client ID/
    Business ID/Template ID/title), reuses it, and only fills in
    whatever Core/Extension state is still missing:

      validate input
      -> find_active_roadmap_for_object(obj_id, service_id)
      -> if none: create_roadmap_record() (roadmap_created=True)
      -> if found: reuse it (roadmap_reused=True) — its OWN stored
         template_id (if any) wins over a newly-requested one (see
         "Template mismatch policy" below)
      -> read Template Stage rows (Core -> Core,
         roadmap_template_manager.find_template_stages())
      -> ensure_roadmap_stages() — idempotent, only creates missing
         Stage Orders (roadmap_manager.py owns ROADMAP_STAGES)
      -> Extension-copy (stage_entity_relations.copy_template_relations_to_stage())
         only for NEWLY created stages this call — stages that already
         existed were already copied on a prior call, and
         copy_template_relations_to_stage() is itself idempotent
         (find_active_duplicate_relation-gated), so retrying it is safe
         even if this orchestration retries the same stage twice
      -> built-in ROADMAP_TEMPLATES (case_type) fallback ONLY if this
         Roadmap has zero Stages in total (never re-triggered just
         because zero stages were created THIS call — that would
         wrongly create a second, differently-IDed stage set on a pure
         idempotent retry where everything already existed)

    Template mismatch policy (Phase 28G): if the existing (reused)
    Roadmap already has a non-empty template_id, it is the source of
    truth — a differently-requested template_id is never silently
    applied; instead "template_warning" reports the mismatch and
    "template_id" in the result reflects the one actually used (the
    existing Roadmap's). If the existing Roadmap's template_id is
    empty, the newly requested/resolved one is used for Stage creation
    this call, but is NOT written back onto the existing ROADMAPS row
    (no owner API exists yet for that narrow field update — deferred,
    not silently improvised; see the Phase 28G report).

    Extension failure (relation-copy) never rolls back an already-
    committed Roadmap/Stages — visible via "partial_success"/
    "partial_failure"/"relation_copy_errors"; "ok" stays True whenever
    Core (Roadmap + Stages) succeeded.

    Data-integrity visibility: if more than one ACTIVE Roadmap already
    exists for this (Object ID, Service ID) — a state this function
    never itself creates, but could already exist in data predating
    this guarantee — the first (sheet-order) one is used, exactly as
    find_active_roadmap_for_object() already behaves, but a warning is
    added making this visible rather than silently picking one.

    Args:
        obj_id:      OBJ-ID объекта (обязательный)
        biz_id:      BIZ-ID бизнеса (обязательный)
        client_id:   PRS-ID клиента (обязательный)
        service_id:  SVC-ID услуги
        case_type:   тип кейса (legalization_reconstruction_house / ...)
        title:       заголовок roadmap (автогенерируется если пустой,
                     используется только при создании нового Roadmap)
        notes:       примечания (используется только при создании)
        template_id: RMT-... шаблон для создания этапов (requested;
                     see Template mismatch policy above for what
                     actually gets used on a reuse)

    Returns:
        {
            "ok":          bool,
            "roadmap_id":  str,
            "error":       str | None,
            # Phase 28C/28D/28E:
            "core_created":                bool,   # Core state (Roadmap, whether new or reused) is present
            "stages_created":              bool,   # at least one NEW Stage created this call
            "stages_count":                int,    # NEW stages created this call
            "stage_ids":                   list[str],  # NEW stage IDs created this call
            "used_template":               bool,
            "relation_copy_errors":        tuple,
            "relation_copy_created_count": int,
            "partial_success":             bool,
            "partial_failure":             bool,
            "warnings":                    tuple,
            # Phase 28G, additive:
            "roadmap_created":    bool,  # True only if a brand-new ROADMAPS row was created this call
            "roadmap_reused":     bool,  # True if an existing active Roadmap was found and reused
            "template_id":        str,   # the template_id actually used for Stage creation this call
            "template_warning":   str | None,
            "existing_stage_ids": list[str],  # Stage IDs that already existed before this call
            "existing_stage_count": int,
            "total_stage_count":    int,  # existing + newly created this call
            "relations_result":  {"created_count": int, "errors": tuple},
            "knowledge_result":  {"merged_inline": bool},  # knowledge-ID copying happens
                                  # inline inside ensure_roadmap_stages() (same-registry
                                  # field merge, not a separate Extension step) — this
                                  # dict documents that, it is not a second write path
        }
    """
    if not obj_id or not biz_id or not client_id:
        return _empty_roadmap_creation_result("Обязательные поля: obj_id, biz_id, client_id")

    if not title:
        title = f"Roadmap {obj_id}" + (f" / {service_id}" if service_id else "")

    from business_core.roadmap_manager import create_roadmap_record, find_active_roadmap_for_object, list_roadmaps

    warnings: list[str] = []
    template_warning = None

    existing = find_active_roadmap_for_object(obj_id, service_id) if service_id else None

    if existing is not None:
        # Data-integrity visibility (Phase 28G): more than one active
        # Roadmap for this key is a pre-existing anomaly this function
        # never itself creates — surface it rather than silently
        # picking one.
        all_active = list_roadmaps(object_id=obj_id, service_id=service_id, status="active")
        if len(all_active) > 1:
            warnings.append(
                f"data integrity: {len(all_active)} active Roadmaps found for "
                f"(Object ID={obj_id!r}, Service ID={service_id!r}) — using {existing['roadmap_id']}"
            )

        roadmap_id = existing["roadmap_id"]
        roadmap_created = False
        roadmap_reused = True

        existing_template_id = (existing.get("template_id") or "").strip()
        if existing_template_id:
            effective_template_id = existing_template_id
            if template_id and template_id != existing_template_id:
                # No underscores in the human-readable text — this
                # message is shown verbatim in Telegram (Markdown
                # parse_mode), where unescaped underscores are consumed
                # as italic delimiters and silently dropped (a real bug
                # found via the Phase 28GH production smoke test).
                template_warning = (
                    f"Запрошенный шаблон ({template_id}) отличается от уже "
                    f"сохранённого ({existing_template_id}) — сохранён "
                    f"прежний шаблон Roadmap."
                )
                warnings.append(template_warning)
        else:
            # Existing Roadmap has no stored template — use the
            # requested/resolved one for Stage creation this call.
            # Deliberately NOT written back onto the existing ROADMAPS
            # row: no owner API exists yet for that one narrow field
            # update, and improvising a raw write here would violate
            # this module's own "no direct Roadmap registry writes"
            # boundary. Deferred — see the Phase 28G report.
            effective_template_id = template_id

        log.info(f"create_roadmap_for_object: reusing existing Roadmap {roadmap_id} / {obj_id} / {service_id}")

    else:
        rm_result = create_roadmap_record(
            business_id=biz_id, client_id=client_id, object_id=obj_id,
            service_id=service_id, template_id=template_id,
            client_name=title, case_type=case_type, notes=notes,
        )
        if not rm_result["ok"]:
            log.error(f"create_roadmap_for_object: {rm_result['error']}")
            return _empty_roadmap_creation_result(rm_result["error"])

        roadmap_id = rm_result["roadmap_id"]
        roadmap_created = True
        roadmap_reused = False
        effective_template_id = template_id
        log.info(f"create_roadmap_for_object: {roadmap_id} / {obj_id} / {case_type}")

    stages_count = 0
    stage_ids: list[str] = []
    existing_stage_ids: list[str] = []
    used_template = False
    relation_copy_errors: list[tuple] = []
    relation_copy_created_count = 0
    total_stage_count = 0

    if effective_template_id:
        try:
            from business_core.roadmap_template_manager import find_template_stages
            template_stage_rows = find_template_stages(effective_template_id)
        except Exception as exc:
            template_stage_rows = []
            warnings.append(str(exc))

        if template_stage_rows:
            from business_core.roadmap_manager import ensure_roadmap_stages
            stage_result = ensure_roadmap_stages(roadmap_id, template_stage_rows)

            if stage_result["ok"]:
                used_template = True
                stage_ids = stage_result["created_stage_ids"]
                existing_stage_ids = stage_result["existing_stage_ids"]
                stages_count = stage_result["created_count"]
                total_stage_count = stage_result["total_count"]

                # Extension orchestration: relation-copy for newly
                # created stages only — existing ones (idempotent
                # retry) were already copied on a prior call, and
                # copy_template_relations_to_stage() is itself
                # idempotent regardless.
                if stage_ids:
                    order_to_template_stage_id = {
                        int(r["order"]): r.get("stage_id", "")
                        for r in template_stage_rows if str(r.get("order", "")).isdigit()
                    }
                    from business_core.stage_entity_relations import copy_template_relations_to_stage
                    for new_stage_id, order in zip(stage_ids, stage_result["created_from_orders"]):
                        source_template_stage_id = order_to_template_stage_id.get(order, "")
                        if not source_template_stage_id:
                            continue
                        try:
                            rel_result = copy_template_relations_to_stage(source_template_stage_id, new_stage_id)
                            relation_copy_created_count += len(rel_result.created)
                            if not rel_result.ok:
                                relation_copy_errors.append(
                                    (new_stage_id, source_template_stage_id, rel_result.errors)
                                )
                        except Exception as exc:
                            relation_copy_errors.append((new_stage_id, source_template_stage_id, (str(exc),)))
            else:
                warnings.append(stage_result.get("error") or "Не удалось создать этапы из шаблона")
        else:
            warnings.append(f"Шаблон {effective_template_id} не содержит этапов.")

    # Fallback: built-in ROADMAP_TEMPLATES keyed by case_type. Phase 28G
    # fix: gated on total_stage_count == 0 (genuinely zero Stages exist
    # for this Roadmap at all), NOT on "zero stages created THIS call"
    # — the latter would wrongly re-trigger on a pure idempotent retry
    # where every Stage already existed, creating a second, incompatible
    # stage set under case_type-derived IDs.
    if total_stage_count == 0:
        try:
            from business_core.roadmap_manager import create_roadmap_stages_from_template
            fb_result = create_roadmap_stages_from_template(roadmap_id, case_type)
            if fb_result.get("stages_count", 0) > 0:
                stage_ids = fb_result.get("stage_ids", [])
                stages_count = fb_result.get("stages_count", 0)
                total_stage_count = stages_count
                used_template = False
            elif fb_result.get("warning"):
                warnings.append(fb_result["warning"])
        except Exception as exc:
            warnings.append(str(exc))

    partial_failure = bool(relation_copy_errors)

    return {
        "ok": True,
        "roadmap_id": roadmap_id,
        "error": None,
        "core_created": True,
        "stages_created": stages_count > 0,
        "stages_count": stages_count,
        "stage_ids": stage_ids,
        "used_template": used_template,
        "relation_copy_errors": tuple(relation_copy_errors),
        "relation_copy_created_count": relation_copy_created_count,
        "partial_success": partial_failure,
        "partial_failure": partial_failure,
        "warnings": tuple(warnings),
        "roadmap_created": roadmap_created,
        "roadmap_reused": roadmap_reused,
        "template_id": effective_template_id,
        "template_warning": template_warning,
        "existing_stage_ids": existing_stage_ids,
        "existing_stage_count": len(existing_stage_ids),
        "total_stage_count": total_stage_count,
        "relations_result": {
            "created_count": relation_copy_created_count,
            "errors": tuple(relation_copy_errors),
        },
        "knowledge_result": {"merged_inline": used_template},
    }


def find_roadmap_by_id(roadmap_id: str) -> Optional[dict]:
    """Найти roadmap по RM-ID без полного чтения листа ROADMAPS."""
    if not roadmap_id:
        return None

    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("roadmaps")

        # Roadmap ID хранится в первом столбце.
        # Ищем только нужную строку вместо get_all_values().
        cell = sheet.find(roadmap_id, in_column=1)

        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)

        wanted = [
            "Roadmap ID", "Business ID", "Service ID", "Client ID", "Client Name",
            "Status", "Created", "Object ID", "Case Type", "Notes", "Progress %",
            "Template ID",
        ]
        v = read_row_by_headers(headers, row, wanted)

        return {
            "row_num":     cell.row,
            "roadmap_id":  v["Roadmap ID"],
            "biz_id":      v["Business ID"],
            "service_id":  v["Service ID"],
            "client_id":   v["Client ID"],
            "title":       v["Client Name"],
            "status":      v["Status"],
            "created":     v["Created"],
            "obj_id":      v["Object ID"],
            "case_type":   v["Case Type"],
            "notes":       v["Notes"],
            "progress":    v["Progress %"],
            "template_id": v["Template ID"],
        }

    except Exception as exc:
        log.warning(f"find_roadmap_by_id({roadmap_id}) error: {exc}")
        return None


def find_roadmaps_by_object(obj_id: str) -> list[dict]:
    """Найти все roadmap для объекта по OBJ-ID."""
    if not obj_id:
        return []
    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("roadmaps")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []
        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h):
            c = _col(h)
            return row[c].strip() if c is not None and c < len(row) else ""

        obj_col = _col("Object ID")
        results = []
        for row in all_values[1:]:
            if not row or not row[0]:
                continue
            if obj_col is not None and obj_col < len(row) and row[obj_col].strip() == obj_id:
                results.append({
                    "roadmap_id": _get(row, "Roadmap ID"),
                    "biz_id":     _get(row, "Business ID"),
                    "service_id": _get(row, "Service ID"),
                    "client_id":  _get(row, "Client ID"),
                    "title":      _get(row, "Client Name"),
                    "status":     _get(row, "Status"),
                    "created":    _get(row, "Created"),
                    "obj_id":     _get(row, "Object ID"),
                    "case_type":  _get(row, "Case Type"),
                    "progress":   _get(row, "Progress %"),
                })
        return results
    except Exception as exc:
        log.warning(f"find_roadmaps_by_object({obj_id}) error: {exc}")
        return []


def update_object_roadmap_id(obj_id: str, roadmap_id: str) -> bool:
    """
    Записать Roadmap ID в OBJECT_REGISTRY для объекта.

    Обновляет только если текущее значение пустое, чтобы
    не затирать уже связанный roadmap.

    Returns:
        True если обновлено
    """
    if not obj_id or not roadmap_id:
        return False
    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False
        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        rm_col = _col("Roadmap ID")
        if rm_col is None:
            return False

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0].strip() != obj_id:
                continue
            current = row[rm_col].strip() if rm_col < len(row) else ""
            if not current:
                sheet.update_cell(i, rm_col + 1, roadmap_id)
                log.info(f"update_object_roadmap_id: {obj_id} → {roadmap_id}")
                return True
            # Уже заполнен — не перезаписываем
            return False

    except Exception as exc:
        log.warning(f"update_object_roadmap_id({obj_id}) error: {exc}")
    return False
