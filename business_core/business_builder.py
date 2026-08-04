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
import re
from dataclasses import dataclass, field
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


def provision_client_drive_safe(
    person_id: str,
    full_name: str,
    biz_name: str,
    roadmap_id: Optional[str] = None,
) -> dict:
    """
    Phase 31D (ADR-015 Decisions 14/15): retry-safe, multi-business-aware
    Drive orchestration for a Client Person — the single decision point
    for "reuse vs create once". Callers (newclient_confirm) must use
    this instead of manually inspecting drive_url/drive_folder_id
    themselves.

    Unlike provision_client_drive() (a pure Drive-folder-creation
    primitive with no PEOPLE_REGISTRY awareness), this function first
    asks person_manager for an existing Drive reference and never calls
    the Drive API at all if one is already set — a second call for the
    same Person never creates a second folder, because it never even
    asks Drive. The existing single Drive Folder ID/Google Drive slot
    is treated as one general/primary Person folder reference (not
    per-Business) — see ADR-015 Decision 14; callers needing the
    OTHER_BIZ "this is a shared folder, not one for the new business"
    warning must add that themselves based on drive_reused + their own
    branch (NEW/SAME_BIZ/OTHER_BIZ), since that phrasing is /newclient
    UX, not a generic Drive-orchestration concern.

    Returns:
        {
            "ok": bool, "drive_created": bool, "drive_reused": bool,
            "partial_failure": bool, "folder_id": str | None,
            "folder_url": str | None, "warning": str | None, "error": str | None,
        }
    """
    from business_core.person_manager import find_person_by_id, update_person_drive_info as pm_update_drive_info

    person = find_person_by_id(person_id)
    if not person:
        return {
            "ok": False, "drive_created": False, "drive_reused": False,
            "partial_failure": False, "folder_id": None, "folder_url": None,
            "warning": None, "error": f"Person '{person_id}' не найден",
        }

    existing_folder_id = person.get("drive_folder_id", "")
    existing_url = person.get("google_drive", "")

    if existing_folder_id or existing_url:
        return {
            "ok": True, "drive_created": False, "drive_reused": True,
            "partial_failure": False,
            "folder_id": existing_folder_id or None, "folder_url": existing_url or None,
            "warning": None, "error": None,
        }

    result = provision_client_drive(prs_id=person_id, full_name=full_name, biz_name=biz_name, roadmap_id=roadmap_id)
    if not result["ok"]:
        return {
            "ok": False, "drive_created": False, "drive_reused": False,
            "partial_failure": False, "folder_id": None, "folder_url": None,
            "warning": None, "error": result.get("error"),
        }

    persist = pm_update_drive_info(person_id, folder_id=result["folder_id"], folder_url=result["folder_url"])
    if not persist["ok"]:
        return {
            "ok": True, "drive_created": True, "drive_reused": False,
            "partial_failure": True,
            "folder_id": result["folder_id"], "folder_url": result["folder_url"],
            "warning": "Папка Drive создана, но не удалось сохранить ссылку в PEOPLE_REGISTRY.",
            "error": persist.get("error"),
        }

    return {
        "ok": True, "drive_created": True, "drive_reused": False,
        "partial_failure": False,
        "folder_id": result["folder_id"], "folder_url": result["folder_url"],
        "warning": None, "error": None,
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

    Thin compatibility wrapper — delegates to
    object_manager.generate_object_id() (canonical owner). Kept for
    callers that still import ID generation from business_builder;
    new callers should import object_manager directly.

    Returns:
        str — следующий OBJ ID
    """
    from business_core.object_manager import generate_object_id as _generate_object_id
    return _generate_object_id()


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

    Thin compatibility wrapper — delegates all persistence,
    normalization, status validation and duplicate-safe logic to
    object_manager.create_object_record() (canonical owner). Preserves
    this function's original signature and "obj_id"-keyed return shape,
    which telegram_handlers.newobject_cmd relies on (Phase 30D) — kept
    permanently as the shape-translation point for that caller, not a
    transitional stub. Additive fields (object_created/object_reused/
    warnings) are passed through unchanged from object_manager.

    Returns:
        {
            "ok":     bool,
            "obj_id": str,
            "error":  str | None,
            # additive:
            "object_created": bool,
            "object_reused":  bool,
            "warnings":       list[str],
        }
    """
    from business_core.object_manager import create_object_record as _create_object_record

    status_arg = object_status if object_status != "new" else None
    result = _create_object_record(
        client_id=client_id, biz_id=biz_id, city=city, address=address,
        cadastral_number=cadastral_number, area_m2=area_m2,
        object_type=object_type, status=status_arg,
        current_service_id=current_service_id, notes=notes,
        drive_folder_id=drive_folder_id, google_drive_url=google_drive_url,
    )
    return {
        "ok":             result["ok"],
        "obj_id":         result["object_id"] or "",
        "error":          result["error"],
        "object_created": result["object_created"],
        "object_reused":  result["object_reused"],
        "warnings":       result["warnings"],
    }


def _canonical_object_to_legacy_shape(obj: dict) -> dict:
    """Translate object_manager's canonical dict shape into the legacy
    business_builder shape (obj_id/object_status/google_drive key
    names) that existing callers of find_object_by_id/
    find_objects_by_client depend on."""
    legacy = {
        "obj_id":             obj["object_id"],
        "client_id":          obj["client_id"],
        "biz_id":             obj["biz_id"],
        "city":               obj["city"],
        "address":            obj["address"],
        "cadastral_number":   obj["cadastral_number"],
        "area_m2":            obj["area_m2"],
        "object_type":        obj["object_type"],
        "object_status":      obj["status"],
        "current_service_id": obj["current_service_id"],
        "roadmap_id":         obj["roadmap_id"],
        "drive_folder_id":    obj["drive_folder_id"],
        "google_drive":       obj["drive_url"],
        "notes":              obj["notes"],
        "created_at":         obj["created_at"],
    }
    if "row_num" in obj:
        legacy["row_num"] = obj["row_num"]
        legacy["last_updated"] = obj["last_updated"]
    return legacy


def find_objects_by_client(client_id: str, biz_id: Optional[str] = None) -> list[dict]:
    """
    Найти объекты клиента в OBJECT_REGISTRY.

    Phase 30C: thin compatibility wrapper — delegates to
    object_manager.find_objects_by_client(), translated back to this
    function's existing (obj_id-keyed) return shape.

    Returns:
        list[dict] — список объектов (пустой если не найдено)
    """
    from business_core.object_manager import find_objects_by_client as _find_objects_by_client
    rows = _find_objects_by_client(client_id, biz_id=biz_id)
    return [_canonical_object_to_legacy_shape(r) for r in rows]


def find_object_by_id(obj_id: str) -> Optional[dict]:
    """
    Найти объект по OBJ ID.

    Phase 30C: thin compatibility wrapper — delegates to
    object_manager.find_object_by_id(), translated back to this
    function's existing (obj_id-keyed) return shape.

    Returns:
        dict или None
    """
    from business_core.object_manager import find_object_by_id as _find_object_by_id
    obj = _find_object_by_id(obj_id)
    if obj is None:
        return None
    return _canonical_object_to_legacy_shape(obj)


def update_object_drive_info(
    obj_id:          str,
    drive_folder_id: str = "",
    google_drive_url: str = "",
) -> bool:
    """
    Дозаполнить Drive Folder ID и Google Drive в OBJECT_REGISTRY.

    Phase 30C: thin compatibility wrapper — delegates to
    object_manager.update_object_drive_info() (only_if_empty=True,
    preserving current production behavior), translated back to this
    function's existing bool return shape.

    Returns:
        True если обновлено, False если не нашли или уже заполнено
    """
    from business_core.object_manager import update_object_drive_info as _update_object_drive_info
    result = _update_object_drive_info(
        obj_id, folder_id=drive_folder_id, folder_url=google_drive_url, only_if_empty=True,
    )
    return bool(result["ok"] and result["updated"])


def _drive_result(
    ok:              bool,
    folder_id:       Optional[str] = None,
    folder_url:      Optional[str] = None,
    error:           Optional[str] = None,
    drive_created:   bool = False,
    drive_reused:    bool = False,
    partial_failure: bool = False,
) -> dict:
    return {
        "ok": ok, "folder_id": folder_id, "folder_url": folder_url, "error": error,
        "drive_created": drive_created, "drive_reused": drive_reused,
        "partial_failure": partial_failure,
    }


def provision_object_drive(
    biz_id:      str,
    client_id:   str,
    obj_id:      str,
    city:        str,
    address:     str,
    object_type: str = "",
) -> dict:
    """
    Создать (или переиспользовать) Drive-папку объекта недвижимости.

    Phase 30D, ADR-014 Decision 14/Part 6 — retry-safe: если у объекта
    в OBJECT_REGISTRY уже есть непустой Drive Folder ID, Drive API НЕ
    вызывается вовсе — существующая ссылка переиспользуется
    (drive_reused=True). Только если ссылка пуста, создаётся новая
    папка, и попытка сохранить ссылку выполняется РОВНО один раз за
    вызов — повторный вызов этой функции никогда не создаёт вторую
    папку в Drive.

    Логика:
    0. object_manager.find_object_by_id(obj_id) — если Drive Folder ID
       уже установлен, вернуть его без обращения к Drive API.
    1. Получить Drive root через resolve_drive_root_for_business(biz_id).
    2. Если root не настроен → ok=False, нет исключения.
    3. Если у клиента уже есть Drive Folder ID → использовать его.
    4. Иначе — создать/получить папку клиента через provision_client_drive.
    5. Создать папку объекта внутри папки клиента.
    6. Сохранить Drive Folder ID через object_manager.update_object_drive_info()
       (only_if_empty=True — тот же safety net на стороне persistence).

    Returns:
        {
            "ok":              bool,
            "folder_id":       str | None,
            "folder_url":      str | None,
            "error":           str | None,
            "drive_created":   bool,  # True только если папка реально создана этим вызовом
            "drive_reused":    bool,  # True если использована уже существующая ссылка
            "partial_failure": bool,  # True если папка создана, но ссылка не сохранилась
        }
    """
    from business_core.object_manager import find_object_by_id, update_object_drive_info as _om_update_drive_info

    obj = find_object_by_id(obj_id)
    if obj and obj.get("drive_folder_id"):
        return _drive_result(
            True, folder_id=obj["drive_folder_id"], folder_url=obj.get("drive_url") or None,
            drive_reused=True,
        )

    # 1. Drive root
    root_info = resolve_drive_root_for_business(biz_id)
    if not root_info["ok"]:
        return _drive_result(False, error=root_info.get("error", "Drive root not configured"))

    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
    if not creds_file:
        return _drive_result(False, error="GOOGLE_CREDENTIALS_FILE не задан")

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

        if not result["ok"]:
            return _drive_result(False, error=result.get("error"))

        # 6. Сохранить ссылку в OBJECT_REGISTRY — ровно одна попытка,
        # only_if_empty=True на стороне object_manager не даст создать
        # вторую ссылку даже при гонке.
        persisted = _om_update_drive_info(
            obj_id, folder_id=result["folder_id"], folder_url=result["folder_url"], only_if_empty=True,
        )
        log.info(f"provision_object_drive: {obj_id} → {result['folder_url']}")

        if not persisted["ok"]:
            # Папка реально создана в Drive, но ссылка не сохранилась —
            # видимый partial failure, не утверждаем полный успех молча.
            return _drive_result(
                True, folder_id=result["folder_id"], folder_url=result["folder_url"],
                error=persisted.get("error"), drive_created=True, partial_failure=True,
            )

        return _drive_result(
            True, folder_id=result["folder_id"], folder_url=result["folder_url"],
            drive_created=True,
        )

    except Exception as exc:
        log.warning(f"provision_object_drive({obj_id}) error: {exc}")
        return _drive_result(False, error=str(exc))


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


def _empty_roadmap_creation_result(error: str, error_code: str = "") -> dict:
    """
    Phase 33C (ADR-016 Decision 4): `error_code` is the stable,
    machine-readable outcome (e.g. "BUSINESS_NOT_FOUND",
    "CLIENT_ARCHIVED", "OBJECT_SERVICE_TYPE_MISMATCH" — see ADR-016
    §14 for the full contract) — `error` remains the existing
    human-readable (Russian) message field every current caller
    already reads. Both are always present; `error_code` is "" only
    for legacy call sites this phase doesn't assign a specific code to
    (the two pre-existing "required fields missing" checks, unchanged
    from before ADR-016).
    """
    return {
        "ok": False, "roadmap_id": "", "error": error, "error_code": error_code,
        "core_created": False, "stages_created": False,
        "stages_count": 0, "stage_ids": [], "used_template": False,
        "relation_copy_errors": (), "relation_copy_created_count": 0,
        "partial_success": False, "partial_failure": False, "warnings": (),
        "roadmap_created": False, "roadmap_reused": False,
        "template_id": "", "template_warning": None,
        "existing_stage_ids": [], "existing_stage_count": 0, "total_stage_count": 0,
        "relations_result": {"created_count": 0, "errors": ()},
        "knowledge_result": {"merged_inline": False},
        # Phase 33C additive fields (ADR-016 §4):
        "stages_reused": False,
        "conflicting_roadmap_ids": [],
        "candidate_template_ids": [],
        "selected_template_id": "",
        "type_compatibility_warning": None,
        "client_type_validation": "deferred",
    }


def _normalize_type_value(value: str) -> str:
    """
    Phase 33C (ADR-016 §6/§11 in the Phase 33B ADR; exact recipe
    specified in the Phase 33C brief): Unicode NFKC -> trim -> collapse
    internal whitespace -> casefold. Used ONLY for the non-blocking
    Object Type comparison — no substring/fuzzy/semantic matching, no
    alias map (none exists yet; see ADR-016 §6 for why one isn't
    invented here).
    """
    import re
    import unicodedata
    v = unicodedata.normalize("NFKC", value or "")
    v = re.sub(r"\s+", " ", v.strip())
    return v.casefold()


def _resolve_and_validate_roadmap_template(
    template_id: str,
    service: dict,
    service_id: str,
) -> dict:
    """
    Phase 33C (ADR-016 §11/13): single canonical Template resolution +
    validation point, used by create_roadmap_for_object() for BOTH an
    explicitly requested template_id and an auto-selected one — no
    second implementation of this logic exists elsewhere (previously,
    explicit-template validation lived only in telegram_handlers.
    startroadmap_cmd(), duplicating what this function now does
    authoritatively at the orchestration boundary; that Telegram-layer
    validation is removed in this same phase to avoid two
    implementations).

    Order: explicit template_id (if given) -> Service's own stored
    Default Roadmap Template ID (if non-empty) -> templates linked to
    this Service via ROADMAP_TEMPLATE_REGISTRY. An explicit template_id
    is validated even if it happens to equal the Service's default —
    there is exactly one validation code path, not two.

    Returns:
        {
            "template_id":  str,   # resolved+validated ID, or "" if none configured at all
            "error_code":   str | None,
            "error":        str | None,
            "candidate_template_ids": list[str],  # only for MULTIPLE_TEMPLATES_REQUIRE_SELECTION
        }
    """
    from business_core.roadmap_template_manager import (
        find_roadmap_template_by_id, find_roadmap_templates_by_service,
    )

    def _validate_candidate(candidate_id: str, source_label: str) -> dict:
        tmpl = find_roadmap_template_by_id(candidate_id)
        if not tmpl:
            return {
                "template_id": "", "error_code": "TEMPLATE_NOT_FOUND",
                "error": f"Шаблон {candidate_id} ({source_label}) не найден в ROADMAP_TEMPLATE_REGISTRY",
                "candidate_template_ids": [],
            }
        tmpl_svc = (tmpl.get("service_id") or "").strip()
        if tmpl_svc and tmpl_svc != service_id:
            return {
                "template_id": "", "error_code": "TEMPLATE_SERVICE_MISMATCH",
                "error": f"Шаблон {candidate_id} принадлежит услуге {tmpl_svc}, а не {service_id}",
                "candidate_template_ids": [],
            }
        tmpl_status = (tmpl.get("status") or "").strip().lower()
        if tmpl_status and tmpl_status != "active":
            return {
                "template_id": "", "error_code": "TEMPLATE_NOT_FOUND",
                "error": f"Шаблон {candidate_id} ({source_label}) имеет статус '{tmpl_status}' — недоступен",
                "candidate_template_ids": [],
            }
        return {"template_id": candidate_id, "error_code": None, "error": None, "candidate_template_ids": []}

    if template_id:
        return _validate_candidate(template_id, "явно указан")

    default_template_id = (service.get("default_roadmap_template_id") or "").strip()
    if default_template_id:
        return _validate_candidate(default_template_id, f"default для {service_id}")

    linked = find_roadmap_templates_by_service(service_id)
    if not linked:
        return {"template_id": "", "error_code": None, "error": None, "candidate_template_ids": []}
    if len(linked) == 1:
        return _validate_candidate(linked[0].get("template_id", ""), f"единственный связанный с {service_id}")

    candidate_ids = [t.get("template_id", "") for t in linked]
    return {
        "template_id": "", "error_code": "MULTIPLE_TEMPLATES_REQUIRE_SELECTION",
        "error": f"Для услуги {service_id} найдено {len(linked)} шаблонов — требуется явный выбор",
        "candidate_template_ids": candidate_ids,
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
    flow (Phase 28C/28D/28E/28G; cross-domain validation added Phase
    33C per ADR-016).

    Validation order (ADR-016 §5, all before any write):
      A. required identifiers (obj_id, biz_id, client_id, service_id)
      B. Business exists (BUSINESS_NOT_FOUND)
      C. Client exists / not archived / has Client role / linked to
         Business (CLIENT_NOT_FOUND / CLIENT_ARCHIVED /
         CLIENT_ROLE_REQUIRED / CLIENT_NOT_LINKED_TO_BUSINESS)
      D. Object exists / eligible status / Business+Client consistency
         (OBJECT_NOT_FOUND / OBJECT_NOT_ELIGIBLE /
         OBJECT_BUSINESS_MISMATCH / OBJECT_CLIENT_MISMATCH)
      E. Service exists / active / Business consistency
         (SERVICE_NOT_FOUND / SERVICE_INACTIVE / SERVICE_BUSINESS_MISMATCH)
      F. Object Type compatibility — non-blocking WARNING only
         (OBJECT_SERVICE_TYPE_MISMATCH); Client Type compatibility
         remains explicitly DEFERRED (ADR-016 §7) — never validated,
         never blocks
      G. Template resolution + validation (explicit -> Service default
         -> linked templates), before any Roadmap row is written
      H. Open-Roadmap duplicate detection — open = {active, on_hold}
         (ADR-016 §9); >1 open Roadmap for (Object ID, Service ID) is a
         blocking MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR, never an
         arbitrary first pick
      I. create or reuse the Roadmap row
      J. materialize missing Stages idempotently

    None of Business/Client/Object/Service/Template records are ever
    mutated during validation — only read. Business status eligibility
    is explicitly NOT enforced this phase (ADR-016 §2 — BIZ_REGISTRY
    has no canonical status model/owner yet); only Business existence
    is required.

    Convergent-retry semantics (Phase 28G, preserved): calling this
    twice with the same (obj_id, service_id) never creates a second
    Roadmap and never duplicates Stages. ALL validations (A-H) re-run
    on every call, including a pure retry — there is no historical
    exception (ADR-016 §10): if Business/Client/Object/Service state
    changed between calls (e.g. Client archived after the first
    Roadmap), the retry is rejected exactly like a first call would be.

    Template mismatch policy (Phase 28G, preserved): if the existing
    (reused) Roadmap already has a non-empty template_id, it is the
    source of truth — a differently-requested template_id is never
    silently applied; "template_warning" reports the mismatch and
    "template_id"/"selected_template_id" reflect the one actually used.
    If the existing Roadmap's template_id is empty, the newly
    requested/resolved one is used for Stage creation this call, but is
    NOT written back onto the existing ROADMAPS row (no owner API
    exists yet for that narrow field update — deferred, not
    improvised).

    Extension failure (relation-copy) never rolls back an already-
    committed Roadmap/Stages — visible via "partial_success"/
    "partial_failure"/"relation_copy_errors"; "ok" stays True whenever
    Core (Roadmap + Stages) succeeded. A Stage-materialization failure
    itself (ensure_roadmap_stages returning ok=False) is now also
    surfaced structurally via error_code="STAGE_MATERIALIZATION_PARTIAL_FAILURE"
    and partial_failure=True (Phase 33C — previously only a warning
    string, "ok" still stays True and the Roadmap row is retained,
    never rolled back; safe to retry).

    Immutable-field integrity (ADR-016 §12/§13): on reuse, the existing
    Roadmap's Business ID/Client ID are compared against the requested
    context — an existing Roadmap's core is never rewritten, and a
    genuine conflict is a blocking integrity error, not a silent
    overwrite or a silent pick.

    Args:
        obj_id:      OBJ-ID объекта (обязательный)
        biz_id:      BIZ-ID бизнеса (обязательный)
        client_id:   PRS-ID клиента (обязательный)
        service_id:  SVC-ID услуги
        case_type:   тип кейса (legalization_reconstruction_house / ...)
        title:       заголовок roadmap (автогенерируется если пустой,
                     используется только при создании нового Roadmap)
        notes:       примечания (используется только при создании)
        template_id: RMT-... шаблон для создания этапов, явно запрошенный
                     (see Template resolution / mismatch policy above)

    Returns:
        {
            "ok":          bool,
            "roadmap_id":  str,
            "error":       str | None,        # human-readable (Russian)
            "error_code":  str,                # stable machine code, "" on success (ADR-016 §14)
            # Phase 28C/28D/28E:
            "core_created":                bool,
            "stages_created":              bool,
            "stages_count":                int,
            "stage_ids":                   list[str],
            "used_template":               bool,
            "relation_copy_errors":        tuple,
            "relation_copy_created_count": int,
            "partial_success":             bool,
            "partial_failure":             bool,
            "warnings":                    tuple,
            # Phase 28G:
            "roadmap_created":    bool,
            "roadmap_reused":     bool,
            "template_id":        str,
            "template_warning":   str | None,
            "existing_stage_ids": list[str],
            "existing_stage_count": int,
            "total_stage_count":    int,
            "relations_result":  {"created_count": int, "errors": tuple},
            "knowledge_result":  {"merged_inline": bool},
            # Phase 33C (ADR-016 §4), additive:
            "stages_reused":              bool,   # True iff any Stage already existed before this call
            "conflicting_roadmap_ids":    list[str],  # populated only for MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR
            "candidate_template_ids":     list[str],  # populated only for MULTIPLE_TEMPLATES_REQUIRE_SELECTION
            "selected_template_id":       str,    # alias of "template_id", for the new structured contract
            "type_compatibility_warning": dict | None,  # {"status": "mismatch"|"unavailable", "object_type": str, "service_object_type": str}
            "client_type_validation":     str,    # always "deferred" (ADR-016 §7) — never blocks, informational only
        }
    """
    # A. Required identifiers.
    if not obj_id or not biz_id or not client_id:
        return _empty_roadmap_creation_result("Обязательные поля: obj_id, biz_id, client_id")
    if not service_id or not service_id.strip():
        # Closeout Remediation (finding #1) — defense-in-depth: service_id
        # is part of the (Object ID, Service ID) duplicate key. A blank/
        # whitespace-only service_id must never reach Roadmap creation —
        # it previously bypassed the reuse lookup entirely and created a
        # distinct, dedup-invisible Roadmap (the RM-002 incident).
        return _empty_roadmap_creation_result("service_id обязателен")

    # B. Business existence (ADR-016 §2). No owner module exists for
    # Business yet (same "Business Domain ещё не имеет отдельного
    # owner-модуля" gap already noted in the Object/Client/Service ADRs)
    # — find_row_by_id("biz_registry", ...) is the existing canonical
    # primitive used identically elsewhere in this file (newobject_cmd,
    # newservice_cmd) for exactly this check; not a new raw read.
    # Business status eligibility is explicitly NOT enforced this phase
    # (ADR-016 §2) — BIZ_REGISTRY.Статус is not a canonical, owned model.
    from business_core.sheets import find_row_by_id
    if find_row_by_id("biz_registry", biz_id) is None:
        return _empty_roadmap_creation_result(f"Business {biz_id} не найден", error_code="BUSINESS_NOT_FOUND")

    # C. Client validation (ADR-016 §3) — canonical person_manager API only.
    from business_core.person_manager import (
        find_person_by_id, is_person_archived, is_client_person, has_person_business_link,
    )
    person = find_person_by_id(client_id)
    if person is None:
        return _empty_roadmap_creation_result(f"Клиент {client_id} не найден", error_code="CLIENT_NOT_FOUND")
    if is_person_archived(person):
        return _empty_roadmap_creation_result(
            f"Клиент {client_id} архивирован — Roadmap не создан", error_code="CLIENT_ARCHIVED",
        )
    if not is_client_person(person):
        return _empty_roadmap_creation_result(
            f"Клиент {client_id} не имеет роли клиента", error_code="CLIENT_ROLE_REQUIRED",
        )
    if not has_person_business_link(person, biz_id):
        return _empty_roadmap_creation_result(
            f"Клиент {client_id} не привязан к бизнесу {biz_id}", error_code="CLIENT_NOT_LINKED_TO_BUSINESS",
        )

    # D. Object validation (ADR-016 §4; existence/status unchanged from
    # Phase 30D/ADR-014 Decision 7 — Business/Client consistency new
    # this phase).
    from business_core.object_manager import find_object_by_id, OBJECT_STATUSES, ROADMAP_ALLOWED_OBJECT_STATUSES
    obj = find_object_by_id(obj_id)
    if obj is None:
        return _empty_roadmap_creation_result(f"Object {obj_id} не найден", error_code="OBJECT_NOT_FOUND")
    object_status = (obj.get("status") or "").strip().lower()
    if object_status not in OBJECT_STATUSES:
        return _empty_roadmap_creation_result(
            f"Object {obj_id}: неизвестный статус '{object_status}' — Roadmap не создан",
            error_code="OBJECT_NOT_ELIGIBLE",
        )
    if object_status not in ROADMAP_ALLOWED_OBJECT_STATUSES:
        return _empty_roadmap_creation_result(
            f"Object {obj_id} имеет статус '{object_status}' — "
            f"Roadmap можно создать только для Object со статусом {', '.join(ROADMAP_ALLOWED_OBJECT_STATUSES)}",
            error_code="OBJECT_NOT_ELIGIBLE",
        )
    if (obj.get("biz_id") or "") != biz_id:
        return _empty_roadmap_creation_result(
            f"Object {obj_id} принадлежит бизнесу {obj.get('biz_id', '')!r}, а не {biz_id!r}",
            error_code="OBJECT_BUSINESS_MISMATCH",
        )
    if (obj.get("client_id") or "") != client_id:
        return _empty_roadmap_creation_result(
            f"Object {obj_id} привязан к клиенту {obj.get('client_id', '')!r}, а не {client_id!r}",
            error_code="OBJECT_CLIENT_MISMATCH",
        )

    # E. Service validation (ADR-016 §5; existence/status unchanged from
    # Phase 29CD/Decision 7 — Business consistency new this phase).
    from business_core.service_manager import find_service_by_id, SERVICE_STATUSES
    service = find_service_by_id(service_id)
    if service is None:
        return _empty_roadmap_creation_result(f"Service {service_id} не найден", error_code="SERVICE_NOT_FOUND")
    service_status = (service.get("status") or "").strip().lower()
    if service_status not in SERVICE_STATUSES:
        return _empty_roadmap_creation_result(
            f"Service {service_id}: неизвестный статус '{service_status}' — Roadmap не создан",
            error_code="SERVICE_INACTIVE",
        )
    if service_status != "active":
        return _empty_roadmap_creation_result(
            f"Service {service_id} имеет статус '{service_status}' — "
            f"Roadmap можно создать только для Service со статусом active",
            error_code="SERVICE_INACTIVE",
        )
    if (service.get("biz_id") or "") != biz_id:
        return _empty_roadmap_creation_result(
            f"Service {service_id} принадлежит бизнесу {service.get('biz_id', '')!r}, а не {biz_id!r}",
            error_code="SERVICE_BUSINESS_MISMATCH",
        )

    if not title:
        title = f"Roadmap {obj_id}" + (f" / {service_id}" if service_id else "")

    warnings: list[str] = []
    template_warning = None

    # F. Object Type compatibility — WARNING only, never blocking
    # (ADR-016 §6 — the vocabulary mismatch between SERVICE_CATALOG.Object
    # Type (English machine slugs) and OBJECT_REGISTRY.Object Type (free
    # Russian text) makes a hard gate unsafe today). Client Type
    # compatibility remains explicitly deferred (ADR-016 §7).
    object_type_raw = obj.get("object_type", "") or ""
    service_object_type_raw = service.get("object_type", "") or ""
    object_type_norm = _normalize_type_value(object_type_raw)
    service_object_type_norm = _normalize_type_value(service_object_type_raw)
    type_compatibility_warning = None
    if not object_type_norm or not service_object_type_norm:
        type_compatibility_warning = {
            "status": "unavailable", "object_type": object_type_raw, "service_object_type": service_object_type_raw,
        }
        warnings.append(
            "Object Type compatibility: сравнение недоступно "
            f"(Object.Object Type={object_type_raw!r}, Service.Object Type={service_object_type_raw!r})"
        )
    elif object_type_norm != service_object_type_norm:
        type_compatibility_warning = {
            "status": "mismatch", "object_type": object_type_raw, "service_object_type": service_object_type_raw,
        }
        warnings.append(
            f"OBJECT_SERVICE_TYPE_MISMATCH: Object.Object Type={object_type_raw!r} "
            f"не совпадает с Service.Object Type={service_object_type_raw!r} (не блокирует создание)"
        )
    # else: exact normalized match — no warning.

    # G. Template resolution + validation (ADR-016 §8/§11) — happens
    # before any Roadmap row is written, for both explicit and
    # auto-selected Template IDs; single implementation, no duplicate
    # validation left in telegram_handlers.py.
    tmpl_resolution = _resolve_and_validate_roadmap_template(template_id, service, service_id)
    if tmpl_resolution["error_code"]:
        result = _empty_roadmap_creation_result(tmpl_resolution["error"], error_code=tmpl_resolution["error_code"])
        result["candidate_template_ids"] = tmpl_resolution["candidate_template_ids"]
        return result
    resolved_template_id = tmpl_resolution["template_id"]

    from business_core.roadmap_manager import create_roadmap_record, find_open_roadmaps_for_object

    # H. Open-Roadmap duplicate detection (ADR-016 §9). Open = {active,
    # on_hold}. >1 open Roadmap for this key is a blocking integrity
    # error, never an arbitrary first pick.
    open_roadmaps = find_open_roadmaps_for_object(obj_id, service_id)
    if len(open_roadmaps) > 1:
        result = _empty_roadmap_creation_result(
            f"Найдено {len(open_roadmaps)} открытых Roadmap для "
            f"(Object ID={obj_id!r}, Service ID={service_id!r}): "
            f"{[r['roadmap_id'] for r in open_roadmaps]} — новый Roadmap не создан",
            error_code="MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR",
        )
        result["conflicting_roadmap_ids"] = [r["roadmap_id"] for r in open_roadmaps]
        return result

    existing = open_roadmaps[0] if open_roadmaps else None

    # I. Create or reuse the Roadmap row.
    if existing is not None:
        # Immutable-identity consistency (ADR-016 §12/§13): an existing
        # Roadmap's Business ID/Client ID must match the requested
        # context — never silently rewritten, never silently ignored.
        immutable_conflicts = []
        if (existing.get("business_id") or "") != biz_id:
            immutable_conflicts.append("business_id")
        if (existing.get("client_id") or "") != client_id:
            immutable_conflicts.append("client_id")
        if immutable_conflicts:
            return _empty_roadmap_creation_result(
                f"Roadmap {existing['roadmap_id']} уже существует с другими "
                f"неизменяемыми полями ({', '.join(immutable_conflicts)}) — "
                f"новый Roadmap не создан, существующий не изменён",
                error_code="ROADMAP_IMMUTABLE_FIELD_CONFLICT",
            )

        roadmap_id = existing["roadmap_id"]
        roadmap_created = False
        roadmap_reused = True

        existing_template_id = (existing.get("template_id") or "").strip()
        if existing_template_id:
            effective_template_id = existing_template_id
            if resolved_template_id and resolved_template_id != existing_template_id:
                # No underscores in the human-readable text — this
                # message is shown verbatim in Telegram (Markdown
                # parse_mode), where unescaped underscores are consumed
                # as italic delimiters and silently dropped (a real bug
                # found via the Phase 28GH production smoke test).
                template_warning = (
                    f"Запрошенный шаблон ({resolved_template_id}) отличается от уже "
                    f"сохранённого ({existing_template_id}) — сохранён "
                    f"прежний шаблон Roadmap."
                )
                warnings.append(template_warning)
        else:
            # Existing Roadmap has no stored template — use the
            # newly resolved one for Stage creation this call.
            # Deliberately NOT written back onto the existing ROADMAPS
            # row: no owner API exists yet for that one narrow field
            # update, and improvising a raw write here would violate
            # this module's own "no direct Roadmap registry writes"
            # boundary. Deferred — see the Phase 28G report.
            effective_template_id = resolved_template_id

        log.info(f"create_roadmap_for_object: reusing existing Roadmap {roadmap_id} / {obj_id} / {service_id}")

    else:
        rm_result = create_roadmap_record(
            business_id=biz_id, client_id=client_id, object_id=obj_id,
            service_id=service_id, template_id=resolved_template_id,
            client_name=title, case_type=case_type, notes=notes,
        )
        if not rm_result["ok"]:
            log.error(f"create_roadmap_for_object: {rm_result['error']}")
            return _empty_roadmap_creation_result(rm_result["error"])

        roadmap_id = rm_result["roadmap_id"]
        roadmap_created = True
        roadmap_reused = False
        effective_template_id = resolved_template_id
        log.info(f"create_roadmap_for_object: {roadmap_id} / {obj_id} / {case_type}")

    stages_count = 0
    stage_ids: list[str] = []
    existing_stage_ids: list[str] = []
    used_template = False
    relation_copy_errors: list[tuple] = []
    relation_copy_created_count = 0
    total_stage_count = 0
    stage_materialization_failed = False

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
                # Phase 33C: a Stage-materialization failure is now
                # surfaced structurally (error_code + partial_failure),
                # not just a warning string — the Roadmap row itself is
                # retained (never rolled back), and a retry is safe:
                # ensure_roadmap_stages() re-reads existing Orders fresh
                # and only attempts genuinely still-missing ones.
                stage_materialization_failed = True
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

    partial_failure = bool(relation_copy_errors) or stage_materialization_failed
    error_code = "STAGE_MATERIALIZATION_PARTIAL_FAILURE" if stage_materialization_failed else ""

    return {
        "ok": True,
        "roadmap_id": roadmap_id,
        "error": None,
        "error_code": error_code,
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
        # Phase 33C additive fields (ADR-016 §4):
        "stages_reused": bool(existing_stage_ids),
        "conflicting_roadmap_ids": [],
        "candidate_template_ids": [],
        "selected_template_id": effective_template_id,
        "type_compatibility_warning": type_compatibility_warning,
        "client_type_validation": "deferred",
    }


def create_stages_from_template_record(roadmap_id: str, template_id: str) -> dict:
    """
    Создать реальные этапы roadmap из шаблона ROADMAP_TEMPLATE_STAGES.

    Closeout Remediation (finding #2): moved here from
    business_core.roadmap_template_manager, where it used to call
    roadmap_manager.ensure_roadmap_stages() — a Roadmap Template Manager
    -> Roadmap Manager import that, combined with roadmap_manager's own
    (necessary, read-only) import of
    roadmap_template_manager.find_roadmap_templates_by_service() inside
    _resolve_template_id(), formed a circular dependency between the two
    *_manager.py modules. This orchestration (reading template stage rows
    from one manager, then handing them to the other manager's owner API
    for the actual Stage row creation) belongs in this orchestration
    layer, not inside either manager. roadmap_template_manager.py no
    longer defines or calls this function.

    Note: business_builder.create_roadmap_for_object() does this same
    find_template_stages() + ensure_roadmap_stages() sequence inline
    already (it does not call this function) — this standalone version
    is kept for any other/future direct caller with the same signature
    and return shape as before the move.

    Returns:
        {
            "ok":           bool,
            "stages_count": int,
            "warning":      str | None,
            "stage_ids":    list[str],
            "partial_success":             bool,   # always False
            "relation_copy_errors":        tuple,   # always ()
            "relation_copy_created_count": int,     # always 0
        }
    """
    if not roadmap_id or not template_id:
        return {
            "ok": False, "stages_count": 0,
            "warning": "roadmap_id и template_id обязательны", "stage_ids": [],
            "partial_success": False, "relation_copy_errors": (), "relation_copy_created_count": 0,
        }

    from business_core.roadmap_template_manager import find_template_stages
    template_stages = find_template_stages(template_id)
    if not template_stages:
        return {
            "ok": True, "stages_count": 0,
            "warning": f"Шаблон {template_id} не содержит этапов.",
            "stage_ids": [],
            "partial_success": False, "relation_copy_errors": (), "relation_copy_created_count": 0,
        }

    try:
        from business_core.roadmap_manager import ensure_roadmap_stages

        result = ensure_roadmap_stages(roadmap_id, template_stages)
        if not result["ok"]:
            return {
                "ok": False, "stages_count": 0,
                "warning": result.get("error", ""), "stage_ids": [],
                "partial_success": False, "relation_copy_errors": (), "relation_copy_created_count": 0,
            }

        return {
            "ok": True,
            "stages_count": result["created_count"],
            "warning": None,
            "stage_ids": result["created_stage_ids"],
            "partial_success": False,
            "relation_copy_errors": (),
            "relation_copy_created_count": 0,
        }

    except Exception as exc:
        log.error(f"create_stages_from_template_record error: {exc}")
        return {
            "ok": False, "stages_count": 0,
            "warning": str(exc), "stage_ids": [],
            "partial_success": False, "relation_copy_errors": (), "relation_copy_created_count": 0,
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
    """
    Найти все roadmap для объекта по OBJ-ID.

    Phase 30D, Part 7: delegates to roadmap_manager.list_roadmaps(
    object_id=...) — the canonical, header-mapped Roadmap owner API —
    instead of a raw ROADMAPS read duplicated here. Translated back to
    this function's existing (biz_id/title/obj_id-keyed, raw Status)
    return shape for its existing caller/tests.
    """
    if not obj_id:
        return []
    try:
        from business_core.roadmap_manager import list_roadmaps
        rows = list_roadmaps(object_id=obj_id)
        return [
            {
                "roadmap_id": r["roadmap_id"],
                "biz_id":     r["business_id"],
                "service_id": r["service_id"],
                "client_id":  r["client_id"],
                "title":      r["client_name"],
                "status":     r["raw_status"],
                "created":    r["created"],
                "obj_id":     r["object_id"],
                "case_type":  r["case_type"],
                "progress":   r["progress"],
            }
            for r in rows
        ]
    except Exception as exc:
        log.warning(f"find_roadmaps_by_object({obj_id}) error: {exc}")
        return []


def update_object_roadmap_id(obj_id: str, roadmap_id: str) -> dict:
    """
    Записать Roadmap ID в OBJECT_REGISTRY для объекта.

    Phase 30C: thin compatibility wrapper — delegates to
    object_manager.update_object_roadmap_id() (only_if_empty=True,
    preserving current "update only if empty" production behavior —
    see ADR-014 Decision 8).

    Phase 33D: returns the full structured dict (was a collapsed bool)
    — the caller-facing UX work needs to distinguish a genuine write
    failure ("ok": False, e.g. Object not found or a Sheets error) from
    the harmless "already set, not overwritten" no-op ("ok": True,
    "updated": False), which a bare bool cannot represent. This dict is
    truthy exactly like the old bool was for any caller that only did
    `if update_object_roadmap_id(...):` — no behavior change for those.

    Returns:
        {"ok": bool, "object_id": str, "updated": bool, "error": str | None}
    """
    from business_core.object_manager import update_object_roadmap_id as _update_object_roadmap_id
    return _update_object_roadmap_id(obj_id, roadmap_id, only_if_empty=True)


# ─────────────────────────────────────────────────────────────
# Phase 34C (ADR-017): Stage transition orchestration boundary.
#
# roadmap_manager.py remains the sole ROADMAP_STAGES/ROADMAPS
# persistence owner (update_stage_status_in_sheet, update_stage_fields,
# recalculate_roadmap_progress, maybe_complete_roadmap — all unchanged
# low-level primitives). Everything that crosses from "one Stage" to
# "its parent Roadmap's own eligibility" lives here instead — exactly
# the same boundary principle ADR-016 already applied to Roadmap
# creation (create_roadmap_for_object). No second implementation of
# this policy exists anywhere else (see
# test_roadmap_architecture_guards.py's Stage-domain guards).
# ─────────────────────────────────────────────────────────────

# Ordinary (non-reopen) transitions allowed from each canonical status,
# including the identity/self-loop transition (ADR-017 Decision 6).
# done/skipped only ever map to themselves here — any other requested
# target from those two sources is an explicit-reopen attempt, handled
# separately (see transition_stage_status), never silently permitted.
_STAGE_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending":     ("pending", "in_progress", "blocked", "skipped"),
    "in_progress": ("in_progress", "pending", "blocked", "done", "skipped"),
    "blocked":     ("blocked", "pending", "in_progress", "skipped"),
    "done":        ("done",),
    "skipped":     ("skipped",),
}

# Statuses from which an ordinary (non-explicit-reopen) transition
# request must never leave — a "done"/"skipped" Stage can only ever be
# read as needing STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION for any
# different target (ADR-017 Decision 6/12). The explicit-reopen
# mechanism itself is out of scope for Phase 34C (ADR-017 Decision 8).
_STAGE_REOPEN_GATED_STATUSES = frozenset({"done", "skipped"})


def _stage_transition_result(
    *, ok: bool, code: str, error: str | None, stage_id: str, roadmap_id: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    changed: bool = False, partial_success: bool = False, written_fields: tuple = (),
    warnings: tuple = (), downstream_failures: tuple = (),
    progress_before: int | None = None, progress_after: int | None = None,
    roadmap_status_before: str = "", roadmap_status_after: str = "",
    retry_safe: bool = True,
    missing_blocking_doc_ids: tuple = (), configuration_error_details: str = "",
    override_applied: bool = False, override_type: str = "", override_id: str = "",
    missing_checklist_instance_ids: tuple = (), missing_checklist_item_ids: tuple = (),
    missing_checklist_item_titles: tuple = (),
    missing_blocking_output_instance_ids: tuple = (), missing_blocking_output_template_ids: tuple = (),
    missing_blocking_output_titles: tuple = (), missing_blocking_output_statuses: tuple = (),
    provisioning_attempted: bool = False, provisioning: dict | None = None,
    provisioning_warning: str = "",
    dependencies_checked: bool = False, unsatisfied_dependencies: tuple = (),
    missing_live_dependency_stages: tuple = (), dependency_configuration_errors: tuple = (),
) -> dict:
    """
    Shared result-builder for transition_stage_status() and
    update_stage_admin_fields() (ADR-017 Decision 12) — the stable,
    structured contract every caller (Telegram or otherwise) reads
    instead of a bare exception or ad-hoc dict shape.

    Phase 43 (Document Completion Gate) additive fields:
    missing_blocking_doc_ids/configuration_error_details/override_applied/
    override_type/override_id all default to their empty/False state, so
    any result built without the gate (which is every result for every
    transition other than in_progress->done) is unaffected.

    Phase 44 (Checklist Completion Gate) additive fields:
    missing_checklist_instance_ids/missing_checklist_item_ids/
    missing_checklist_item_titles — same empty-default contract.

    Phase B (Required Output Completion Gate) additive fields:
    missing_blocking_output_instance_ids/_template_ids/_titles/_statuses —
    same empty-default contract. A missing instance ("instance_missing")
    is represented as an empty string at the corresponding position in
    missing_blocking_output_instance_ids, never by omitting it from the
    other three tuples — all four always stay the same length and index-
    aligned.

    Auto-provisioning (pending->in_progress) additive fields:
    provisioning_attempted/provisioning/provisioning_warning — same
    empty-default contract; every result built for any transition other
    than a successful pending->in_progress is unaffected
    (provisioning_attempted stays False, provisioning stays {}).
    `provisioning` defaults to None here (never a mutable {} default) and
    is normalized to {} in the returned dict, never left as None, so
    every caller can safely do `result["provisioning"].get(...)` without
    a None-check.

    Dependencies Foundation (2026-07-28, DECISIONS.md §14a) additive
    fields: dependencies_checked/unsatisfied_dependencies/missing_live_
    dependency_stages/dependency_configuration_errors — same empty-
    default contract; every result built for any transition other than
    a pending->in_progress attempt is unaffected
    (dependencies_checked stays False).
    """
    return {
        "ok": ok,
        "code": code,
        "error": error,
        "stage_id": stage_id,
        "roadmap_id": roadmap_id,
        "previous_status": previous_status,
        "requested_status": requested_status,
        "final_status": final_status,
        "changed": changed,
        "partial_success": partial_success,
        "written_fields": tuple(written_fields),
        "warnings": tuple(warnings),
        "downstream_failures": tuple(downstream_failures),
        "progress_before": progress_before,
        "progress_after": progress_after,
        "roadmap_status_before": roadmap_status_before,
        "roadmap_status_after": roadmap_status_after,
        "retry_safe": retry_safe,
        "missing_blocking_doc_ids": tuple(missing_blocking_doc_ids),
        "configuration_error_details": configuration_error_details,
        "override_applied": override_applied,
        "override_type": override_type,
        "override_id": override_id,
        "missing_checklist_instance_ids": tuple(missing_checklist_instance_ids),
        "missing_checklist_item_ids": tuple(missing_checklist_item_ids),
        "missing_checklist_item_titles": tuple(missing_checklist_item_titles),
        "missing_blocking_output_instance_ids": tuple(missing_blocking_output_instance_ids),
        "missing_blocking_output_template_ids": tuple(missing_blocking_output_template_ids),
        "missing_blocking_output_titles": tuple(missing_blocking_output_titles),
        "missing_blocking_output_statuses": tuple(missing_blocking_output_statuses),
        "provisioning_attempted": provisioning_attempted,
        "provisioning": provisioning if provisioning is not None else {},
        "provisioning_warning": provisioning_warning,
        "dependencies_checked": dependencies_checked,
        "unsatisfied_dependencies": tuple(unsatisfied_dependencies),
        "missing_live_dependency_stages": tuple(missing_live_dependency_stages),
        "dependency_configuration_errors": tuple(dependency_configuration_errors),
    }


@dataclass(frozen=True)
class _StageCompletionGateResult:
    """
    Phase 44: shared, minimal contract every individual Stage completion
    gate function returns (_evaluate_document_completion_gate(),
    _evaluate_checklist_completion_gate(), and any future one) — so
    transition_stage_status() can evaluate all of them uniformly, combine
    their results into a single failure message / single override audit
    row, and never grow a gate-specific branch inline for each new gate
    type.

    blocked=False + configuration_error=False + warning="" is the
    "nothing to report" default every gate returns when there's simply
    nothing configured for that Stage (not an error — ADR audit finding).
    """
    blocked: bool = False
    warning: str = ""
    error_code: str = ""
    error: str = ""
    override_type: str = ""
    configuration_error: bool = False
    configuration_error_details: str = ""
    missing_blocking_doc_ids: tuple = ()
    missing_checklist_instance_ids: tuple = ()
    missing_checklist_item_ids: tuple = ()
    missing_checklist_item_titles: tuple = ()
    # Phase B (Required Output Completion Gate) — always the same length,
    # index-aligned; missing_blocking_output_instance_ids holds "" at any
    # position where no instance was ever created ("instance_missing").
    missing_blocking_output_instance_ids: tuple = ()
    missing_blocking_output_template_ids: tuple = ()
    missing_blocking_output_titles: tuple = ()
    missing_blocking_output_statuses: tuple = ()


def _evaluate_document_completion_gate(stage_id: str) -> _StageCompletionGateResult:
    """
    Phase 43: Document Completion Gate, extracted as its own function
    (previously inline in transition_stage_status()) so Phase 44 can
    evaluate it side-by-side with _evaluate_checklist_completion_gate()
    uniformly, without transition_stage_status() growing a second
    gate-specific inline block. Behavior is byte-for-byte unchanged from
    Phase 43: uses document_requirements_query.evaluate_scope("stage", ...).

      - no structured requirements configured, or all satisfied ->
        not blocked, not an error
      - only optional missing -> not blocked, warning returned
      - blocking_missing > 0 -> blocked, override_type=
        "missing_blocking_documents", missing_blocking_doc_ids populated
      - has_configuration_errors -> blocked, configuration_error=True,
        override_type="configuration_error", configuration_error_details
        populated (checked BEFORE blocking_missing, exactly as Phase 43
        did — a broken relation is reported as a configuration error,
        never merged with a plain missing-document message)
    """
    from business_core.document_requirements_query import evaluate_scope

    scope_result = evaluate_scope("stage", stage_id)
    summary = scope_result.summary if scope_result.exists else None

    if summary is not None and summary.has_configuration_errors:
        details = "; ".join(
            f"{err_stage_id or '—'}/{relation_id or '—'}: {reason}"
            for err_stage_id, relation_id, reason in summary.configuration_errors
        )
        return _StageCompletionGateResult(
            blocked=True, error_code="STAGE_DOCUMENT_REQUIREMENTS_CONFIGURATION_ERROR",
            error=f"Настройка требований к документам этапа {stage_id} повреждена: {details}",
            override_type="configuration_error",
            configuration_error=True, configuration_error_details=details,
        )

    if summary is not None and summary.blocking_missing > 0:
        missing_doc_ids = tuple(item.requirement.document_template_id for item in summary.items if item.is_blocking)
        return _StageCompletionGateResult(
            blocked=True, error_code="STAGE_DOCUMENT_GATE_BLOCKED",
            error=(
                f"У этапа {stage_id} есть незакрытые обязательные (blocking) "
                f"требования к документам: {', '.join(missing_doc_ids)}"
            ),
            override_type="missing_blocking_documents",
            missing_blocking_doc_ids=missing_doc_ids,
        )

    if summary is not None and summary.optional_missing > 0:
        return _StageCompletionGateResult(
            warning=(
                f"У этапа {stage_id} не хватает {summary.optional_missing} "
                f"необязательных (optional) документов — завершение разрешено."
            ),
        )

    return _StageCompletionGateResult()


def _evaluate_checklist_completion_gate(stage_id: str) -> _StageCompletionGateResult:
    """
    Phase 44: Checklist Completion Gate. Mirrors
    _evaluate_document_completion_gate()'s exact "nothing configured is
    not an error" / "only optional missing is a warning, not a block"
    shape, applied to CHECKLIST_INSTANCES/CHECKLIST_INSTANCE_ITEMS
    (ADR-021) instead of Document Requirements.

    Reuses the existing canonical progress calculator
    _compute_checklist_progress() unchanged — no new progress-counting
    logic is introduced here, only the gate policy around its result.

    Every "cancelled"/"archived" Checklist Instance for this Stage is
    excluded from consideration entirely (an abandoned/retired checklist
    must never block completion) — every other status (draft/
    in_progress/blocked/completed) has its items recomputed fresh from
    CHECKLIST_INSTANCE_ITEMS, never from the Instance's own cached
    Total/Required/Completed/Required Remaining columns (those are a
    display cache written by business_builder.instantiate_checklist()/
    transition_checklist_item_status(), never treated as the source of
    truth here — same "recompute from item Status, never trust a prior
    cache" principle _compute_checklist_progress()'s own docstring
    states).

    If a Stage has zero live Checklist Instances at all, this is
    identical in meaning to "no structured Document requirements
    configured" — allowed, not an error, so old Roadmaps predating this
    gate (which never ran /startchecklist for any of their Stages) are
    never retroactively blocked.
    """
    from business_core.checklist_manager import list_checklist_instances, list_checklist_instance_items

    all_instances = list_checklist_instances()
    live_instances = [
        inst for inst in all_instances
        if inst.get("Stage ID", "") == stage_id and inst.get("Status", "") not in ("cancelled", "archived")
    ]

    if not live_instances:
        return _StageCompletionGateResult()

    missing_instance_ids: list[str] = []
    missing_item_ids: list[str] = []
    missing_item_titles: list[str] = []
    total_optional_missing = 0

    for inst in live_instances:
        instance_id = inst.get("Checklist Instance ID", "")
        raw_items = list_checklist_instance_items(instance_id=instance_id)
        items_for_progress = [
            {"required": (it.get("Required", "").strip().lower() == "true"), "status": it.get("Status", "")}
            for it in raw_items
        ]
        progress = _compute_checklist_progress(items_for_progress)

        if progress["required_remaining"] > 0:
            missing_instance_ids.append(instance_id)
            for it in raw_items:
                required = it.get("Required", "").strip().lower() == "true"
                status = it.get("Status", "")
                if required and status not in _CHECKLIST_SATISFYING_ITEM_STATUSES:
                    missing_item_ids.append(it.get("Checklist Instance Item ID", ""))
                    missing_item_titles.append(it.get("Item Title Snapshot", ""))
        else:
            total_optional_missing += sum(
                1 for it in raw_items
                if it.get("Required", "").strip().lower() != "true"
                and it.get("Status", "") not in _CHECKLIST_SATISFYING_ITEM_STATUSES
            )

    if missing_instance_ids:
        return _StageCompletionGateResult(
            blocked=True, error_code="STAGE_CHECKLIST_GATE_BLOCKED",
            error=(
                f"У этапа {stage_id} есть незавершённые обязательные пункты чек-листа: "
                f"{', '.join(missing_item_titles)}"
            ),
            override_type="missing_checklist_items",
            missing_checklist_instance_ids=tuple(missing_instance_ids),
            missing_checklist_item_ids=tuple(missing_item_ids),
            missing_checklist_item_titles=tuple(missing_item_titles),
        )

    if total_optional_missing > 0:
        return _StageCompletionGateResult(
            warning=(
                f"У этапа {stage_id} не хватает {total_optional_missing} "
                f"необязательных (optional) пунктов чек-листа — завершение разрешено."
            ),
        )

    return _StageCompletionGateResult()


def _evaluate_output_completion_gate(stage_id: str) -> _StageCompletionGateResult:
    """
    Phase B: Required Output Completion Gate. Mirrors
    _evaluate_document_completion_gate()/_evaluate_checklist_completion_
    gate()'s shape (blocked=False is "nothing to report", never an
    error), but — approved architectural correction over the original
    audit's "instances-only" recommendation — checks BOTH of two sources,
    not just existing instances:

      Source A: active STAGE_ENTITY_RELATIONS rows of Entity Type
      "required_output" on this Stage's Template Stage, filtered to
      Blocking=="true". If the resolution to a Template Stage fails for
      any reason, Source A is simply empty (not an error) — Source B
      below is completely independent of this resolution and still
      fully protects against a Stage closing with an unresolved blocking
      instance.

      Source B: every existing STAGE_OUTPUT_INSTANCES row for this Stage
      with its OWN Blocking=="true", regardless of whether its
      originating relation is still active or was ever active at all.
      An already-created blocking instance's own Blocking field is the
      permanent source of truth — deactivating/deleting its relation or
      its Output Template afterward never retroactively exempts it.

    For each blocking relation (Source A) with no corresponding instance
    yet, this reports a "instance_missing" entry (Instance ID = "",
    Template ID = the relation's Entity ID, Title = the Output
    Template's own Title, Status = the literal string
    "instance_missing") — an active blocking relation can never be
    silently bypassed just because /syncoutputs was never run.

    Every instance (from either source) whose Status is NOT in
    stage_output_manager.TERMINAL_OUTPUT_STATUSES ({"accepted", "waived",
    "not_applicable"}) is blocking — pending/produced/submitted/rejected
    all block equally. Required is never consulted (Blocking alone
    governs, exactly like the Document Gate's own Blocking-only
    semantics).

    Deduplicated by (Output Template ID, Output Instance ID) so the same
    output is never counted twice when it appears via both sources at
    once (the common case: an active relation whose instance already
    exists and is still non-terminal).
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage
    from business_core.stage_entity_relations import get_relations_for_template_stage
    from business_core.stage_output_manager import (
        find_output_template_by_id, list_output_instances_for_stage, TERMINAL_OUTPUT_STATUSES,
    )

    resolved = resolve_template_stage_for_stage(stage_id)
    template_stage_id = resolved.get("template_stage_id", "") if resolved.get("ok") else ""

    blocking_relations = ()
    if template_stage_id:
        relations = get_relations_for_template_stage(template_stage_id, entity_type="required_output")
        blocking_relations = tuple(
            r for r in relations if (r.get("Blocking", "") or "").strip().lower() == "true"
        )

    all_instances = list_output_instances_for_stage(stage_id)
    blocking_instances = [
        i for i in all_instances if (i.get("Blocking", "") or "").strip().lower() == "true"
    ]
    instance_by_template_id: dict[str, dict] = {}
    for inst in blocking_instances:
        otid = inst.get("Output Template ID", "")
        if otid not in instance_by_template_id:
            instance_by_template_id[otid] = inst

    seen_pairs: set = set()
    missing_instance_ids: list[str] = []
    missing_template_ids: list[str] = []
    missing_titles: list[str] = []
    missing_statuses: list[str] = []

    def _add_missing(template_id: str, instance_id: str, title: str, status: str) -> None:
        key = (template_id, instance_id)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        missing_template_ids.append(template_id)
        missing_instance_ids.append(instance_id)
        missing_titles.append(title)
        missing_statuses.append(status)

    # Source A: relation-driven requirements.
    for rel in blocking_relations:
        output_template_id = rel.get("Entity ID", "")
        inst = instance_by_template_id.get(output_template_id)
        if inst is None:
            template = find_output_template_by_id(output_template_id)
            title = template.get("Title", "") if template else ""
            _add_missing(output_template_id, "", title, "instance_missing")
        elif inst.get("Status", "") not in TERMINAL_OUTPUT_STATUSES:
            _add_missing(
                output_template_id, inst.get("Output Instance ID", ""),
                inst.get("Title Snapshot", ""), inst.get("Status", ""),
            )

    # Source B: instance-driven requirements — a blocking instance always
    # blocks on its own terms, even with an inactive/deleted relation.
    for inst in blocking_instances:
        status = inst.get("Status", "")
        if status not in TERMINAL_OUTPUT_STATUSES:
            _add_missing(
                inst.get("Output Template ID", ""), inst.get("Output Instance ID", ""),
                inst.get("Title Snapshot", ""), status,
            )

    if missing_template_ids:
        return _StageCompletionGateResult(
            blocked=True, error_code="STAGE_OUTPUT_GATE_BLOCKED",
            error=(
                f"У этапа {stage_id} есть непринятые обязательные результаты (Required Output): "
                f"{', '.join(t for t in missing_titles if t) or ', '.join(missing_template_ids)}"
            ),
            override_type="missing_blocking_outputs",
            missing_blocking_output_instance_ids=tuple(missing_instance_ids),
            missing_blocking_output_template_ids=tuple(missing_template_ids),
            missing_blocking_output_titles=tuple(missing_titles),
            missing_blocking_output_statuses=tuple(missing_statuses),
        )

    return _StageCompletionGateResult()


@dataclass(frozen=True)
class _StageDependencyGateResult:
    """
    Dependencies Foundation (2026-07-28, DECISIONS.md §14a): shared,
    minimal result contract for _evaluate_stage_dependency_gate() —
    mirrors _StageCompletionGateResult's own shape/spirit (blocked=False
    is the "nothing to report" default), but is a SEPARATE dataclass,
    never merged with it — the Dependency Gate governs Stage START
    (pending->in_progress only) while _StageCompletionGateResult's
    family governs Stage FINISH (in_progress->done only); the two never
    fire on the same transition and are kept structurally distinct.
    """
    blocked: bool = False
    error_code: str = ""
    error: str = ""
    dependencies: tuple = ()
    blocking_dependencies: tuple = ()
    satisfied: tuple = ()
    unsatisfied: tuple = ()
    missing_live_stages: tuple = ()
    configuration_errors: tuple = ()


def _evaluate_stage_dependency_gate(stage_id: str, read_context=None) -> _StageDependencyGateResult:
    """
    Dependencies Foundation: evaluates whether `stage_id` may transition
    pending->in_progress given its Template Stage's active prerequisite
    dependencies (business_core.stage_dependency_manager,
    TEMPLATE_STAGE_DEPENDENCIES — a completely separate table from
    STAGE_ENTITY_RELATIONS, never touched here).

    Uses resolve_live_stage_dependencies() to map each active dependency
    to its live prerequisite Stage (Order-join, the same existing
    mechanism resolve_template_stage_for_stage() itself uses — Order
    remains a technical join-key only, never a dependency signal, per
    DECISIONS.md §14/§14a).

    Satisfying prerequisite statuses: "done" and "skipped" (both are
    legitimate terminal outcomes for a Stage — blocking downstream
    progress on a correctly-skipped prerequisite would contradict the
    reason skip exists at all). Unsatisfying: "pending", "in_progress",
    "blocked". Stage-level "cancelled" does not exist as a status
    (STAGE_STATUS_CANONICAL confirms this) — not applicable.

    Non-blocking dependencies (Blocking="false") are included in
    `dependencies` for visibility but never in `blocking_dependencies`/
    `unsatisfied` — they never block the transition. Inactive
    dependencies are never read at all (list_dependencies_for_template_
    stage() defaults to active-only).

    Read-time corrupted-cycle defense: detect_reachable_cycle_from_
    template_stage() — bounded (200 nodes), scoped to one Roadmap
    Template ID, reachable from THIS Template Stage only. This is
    defense-in-depth against data corrupted after creation (e.g. a
    manually edited Sheet row) — the actual cycle-prevention mechanism
    is create_template_stage_dependency()'s own create-time DFS. This
    function never re-validates the WHOLE template graph on every
    transition (that would be validate_dependency_graph_for_template()'s
    job — a separate, manually-invoked diagnostic tool, never called
    automatically here).

    Returns _StageDependencyGateResult — blocked=False + empty defaults
    is "nothing to report" (no active dependencies, or all satisfied).

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache — see _TransitionReadContext.
    Threaded through resolve_live_stage_dependencies()/
    detect_reachable_cycle_from_template_stage() so ROADMAP_STAGES/
    ROADMAPS/ROADMAP_TEMPLATE_STAGES/TEMPLATE_STAGE_DEPENDENCIES are
    each read at most once per transition. A SheetsReadError raised by
    either call is never caught here — it propagates to
    transition_stage_status(), which maps it to SHEETS_QUOTA_EXCEEDED/
    TRANSIENT_SHEETS_READ_ERROR instead of this function's own
    DEPENDENCY_CONFIGURATION_ERROR (a 429/5xx is not "the dependency
    data is broken"). Default None preserves the exact prior behavior
    for every existing direct caller.
    """
    from business_core.stage_dependency_manager import (
        resolve_live_stage_dependencies, detect_reachable_cycle_from_template_stage,
    )

    resolution = resolve_live_stage_dependencies(stage_id, read_context=read_context)
    if not resolution["ok"]:
        # Same shared resolution-failure codes as every other Gate
        # (STAGE_NOT_FOUND/ROADMAP_NOT_FOUND/ROADMAP_HAS_NO_TEMPLATE/
        # TEMPLATE_STAGE_NOT_FOUND) — surfaced as a configuration error
        # here since the Dependency Gate cannot evaluate anything without
        # a resolved Template Stage.
        return _StageDependencyGateResult(
            blocked=True, error_code="DEPENDENCY_CONFIGURATION_ERROR",
            error=resolution.get("error") or f"Не удалось резолвить зависимости этапа {stage_id}",
            configuration_errors=((None, resolution.get("error") or resolution.get("code", "")),),
        )

    if resolution["code"] == "NO_STAGE_DEPENDENCIES":
        return _StageDependencyGateResult(blocked=False, error_code="NO_STAGE_DEPENDENCIES")

    template_stage_id = resolution["template_stage_id"]
    roadmap_template_id = resolution["roadmap_template_id"]

    # Read-time corrupted-cycle defense (bounded, reachable-only) — never
    # the primary prevention mechanism.
    cycle_check = detect_reachable_cycle_from_template_stage(
        roadmap_template_id, template_stage_id, read_context=read_context,
    )
    if not cycle_check["ok"] or cycle_check.get("limit_exceeded") or cycle_check.get("cycle_found"):
        reason = (
            cycle_check.get("error")
            or ("превышен лимит обхода графа зависимостей" if cycle_check.get("limit_exceeded") else None)
            or (f"обнаружен цикл в графе зависимостей: {' -> '.join(cycle_check.get('cycle_path', ()))}"
                if cycle_check.get("cycle_found") else "неизвестная ошибка проверки цикла")
        )
        return _StageDependencyGateResult(
            blocked=True, error_code="DEPENDENCY_CONFIGURATION_ERROR",
            error=f"Настройка зависимостей этапа {stage_id} повреждена: {reason}",
            configuration_errors=((None, reason),),
        )

    configuration_errors = resolution.get("configuration_errors", ())
    if configuration_errors:
        details = "; ".join(f"{dep_id or '—'}: {reason}" for dep_id, reason in configuration_errors)
        return _StageDependencyGateResult(
            blocked=True, error_code="DEPENDENCY_CONFIGURATION_ERROR",
            error=f"Настройка зависимостей этапа {stage_id} повреждена: {details}",
            configuration_errors=tuple(configuration_errors),
        )

    missing_live_stages = resolution.get("missing_live_stages", ())
    if missing_live_stages:
        details = "; ".join(f"{dep_id}: {tstg_id}" for dep_id, tstg_id in missing_live_stages)
        return _StageDependencyGateResult(
            blocked=True, error_code="PREREQUISITE_LIVE_STAGE_NOT_FOUND",
            error=f"Обязательный предыдущий этап не найден в этом Roadmap: {details}",
            missing_live_stages=tuple(missing_live_stages),
        )

    resolved_items = resolution.get("resolved", ())
    dependencies = tuple(resolved_items)
    blocking_dependencies = tuple(d for d in resolved_items if d["blocking"])
    satisfied = tuple(d for d in blocking_dependencies if d["satisfied"])
    unsatisfied = tuple(d for d in blocking_dependencies if not d["satisfied"])

    if unsatisfied:
        titles = ", ".join(f"{d['prerequisite_stage_id']} — {d['prerequisite_stage_name']}" for d in unsatisfied)
        return _StageDependencyGateResult(
            blocked=True, error_code="STAGE_DEPENDENCIES_NOT_SATISFIED",
            error=f"У этапа {stage_id} есть незавершённые обязательные зависимости: {titles}",
            dependencies=dependencies, blocking_dependencies=blocking_dependencies,
            satisfied=satisfied, unsatisfied=unsatisfied,
        )

    return _StageDependencyGateResult(
        blocked=False, error_code="STAGE_DEPENDENCIES_SATISFIED",
        dependencies=dependencies, blocking_dependencies=blocking_dependencies,
        satisfied=satisfied, unsatisfied=(),
    )


def _roadmap_eligibility_code_for_stage_update(roadmap_status: str) -> str | None:
    """
    ADR-017 Decision 7: returns the blocking code for a Stage
    execution-status update given the parent Roadmap's own (normalized)
    status, or None if updates are allowed. "active" is the only
    status that allows Stage execution-status updates. Any status
    outside the four canonical ROADMAP_STATUSES (active/on_hold/
    completed/cancelled — guaranteed by ADR-016 at Roadmap-creation
    time) falls back to the most conservative code, ROADMAP_CANCELLED,
    since no legitimate fifth value is expected to ever occur in
    practice (defense-in-depth only, not an evidenced production case).
    """
    if roadmap_status == "active":
        return None
    if roadmap_status == "on_hold":
        return "ROADMAP_ON_HOLD"
    if roadmap_status == "completed":
        return "ROADMAP_COMPLETED"
    if roadmap_status == "cancelled":
        return "ROADMAP_CANCELLED"
    return "ROADMAP_CANCELLED"


@dataclass
class _TransitionReadContext:
    """
    Sheets quota mitigation (2026-07-28, RM-003 incident post-mortem):
    a private, mutable, transaction-local read cache — created fresh
    inside transition_stage_status() at the start of one call, threaded
    down (as the optional `read_context` kwarg) into every reader on the
    F.7/K path that would otherwise re-derive the same Stage/Roadmap/
    Template Stage/relations/instances from scratch, and discarded when
    transition_stage_status() returns.

    NOT frozen — fields are filled in progressively as the transition
    proceeds (Stage/Roadmap known after A/B/C, template_stage_resolution
    only once F.7 or auto-provisioning first resolves it, etc). NOT
    global, NOT cached across Telegram updates, NOT TTL'd — it lives and
    dies with exactly one transition_stage_status() call.

    Fields:
      stage/roadmap: the exact dicts find_stage_by_id()/find_roadmap_by_id()
        already returned in this transition's own A/B/C validation —
        reused by resolve_template_stage_for_stage() instead of a second
        lookup.
      template_stage_resolution: the full resolve_template_stage_for_stage()
        result — this function is otherwise called fresh, from scratch,
        up to 5 times in one transition (F.7, auto-provisioning
        top-level, checklist provisioning, output provisioning), each
        costing 7 Sheets read requests; this collapses that to one.
      roadmap_stages: get_stages_for_roadmap()'s result for THIS
        transition's one Roadmap (a transition only ever touches one).
      template_stages: find_template_stages()'s result for THIS
        transition's one Roadmap Template (likewise only one per
        transition).
      sheet_rows: generic full-table cache keyed by BUSINESS_SHEET_NAMES
        key (e.g. "template_stage_dependencies", "stage_entity_relations",
        "checklist_instances", "stage_output_instances",
        "stage_output_templates") — see business_core.sheets.
        read_business_sheet_cached().
      relations_by_entity_type: reserved for a future per-entity-type
        STAGE_ENTITY_RELATIONS cache split; not populated in this phase
        (the generic `sheet_rows["stage_entity_relations"]` cache
        already collapses all STAGE_ENTITY_RELATIONS reads to one full-
        table read per transition, filtered by entity_type in memory —
        see stage_entity_relations.list_relations()).
    """
    stage: dict | None = None
    roadmap: dict | None = None
    template_stage_resolution: dict | None = None
    roadmap_stages: tuple = ()
    template_stages: tuple = ()
    sheet_rows: dict = field(default_factory=dict)
    relations_by_entity_type: dict = field(default_factory=dict)


def transition_stage_status(
    stage_id: str,
    target_status: str,
    notes: Optional[str] = None,
    admin_fields: Optional[dict] = None,
    force: bool = False,
    reason: Optional[str] = None,
    actor: str = "",
) -> dict:
    """
    Phase 34C (ADR-017): the sole canonical Stage-transition
    orchestration boundary. /updatestage, /blockstage, and
    /unblockstage all call this — never roadmap_manager.
    update_stage_status_in_sheet() directly — so Roadmap-eligibility
    and transition-matrix policy is enforced exactly once, in exactly
    one place.

    Validation order (ADR-017 §6, all before any write):
      A. required stage_id
      B. Stage exists (STAGE_NOT_FOUND)
      C. parent Roadmap exists (ROADMAP_NOT_FOUND)
      D. Roadmap eligibility (ROADMAP_ON_HOLD / ROADMAP_COMPLETED /
         ROADMAP_CANCELLED) — "active" is the only status that allows
         a Stage execution-status update
      E. target status normalization/validation against
         roadmap_manager.STAGE_STATUS_CANONICAL (INVALID_STAGE_STATUS)
      F. current->target transition validation
         (STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION for an ordinary attempt
         to leave done/skipped; INVALID_STAGE_TRANSITION for any other
         disallowed pair)
      F.5. Stage Completion Gates (Phase 43 Document / Phase 44
         Checklist) — ONLY when previous_status=="in_progress" and
         target_status=="done"; every other transition (including
         anything to/from "skipped") skips this step entirely and never
         evaluates either gate. Both _evaluate_document_completion_gate()
         and _evaluate_checklist_completion_gate() are ALWAYS evaluated
         together (never short-circuited after the first one blocks) so
         a Stage missing both documents and checklist items gets told
         about both reasons in one response, never just the first one
         found:
           - neither gate blocked -> allowed; any optional-missing
             warning from either gate is appended, never silently
             dropped
           - exactly one gate blocked -> that gate's own code
             (STAGE_DOCUMENT_GATE_BLOCKED /
             STAGE_DOCUMENT_REQUIREMENTS_CONFIGURATION_ERROR /
             STAGE_CHECKLIST_GATE_BLOCKED) unless force=True (+ non-blank
             reason)
           - both gates blocked -> combined STAGE_COMPLETION_GATE_BLOCKED,
             error message concatenates both gates' messages, result
             carries both gates' missing_* fields at once, unless
             force=True (+ non-blank reason)
           - force=True with an empty/blank reason is rejected up front
             (STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED — the
             legacy STAGE_DOCUMENT_GATE_OVERRIDE_REASON_REQUIRED name is
             still recognized by telegram_handlers' renderer for
             backward compatibility, but this function only ever emits
             the new neutral name now), before either gate is evaluated
         On any block, Status/Completed At/Roadmap Progress are all
         untouched — the function returns before step G, exactly like
         every other pre-write validation failure.
      G. persist Stage status (roadmap_manager.update_stage_status_in_sheet),
         plus any admin_fields (Blocking Reason, for /blockstage/
         /unblockstage's coupled write) via roadmap_manager.
         update_stage_fields — gated behind the SAME eligibility check
         above, never a second, independent one
      G.5. Completion gate override audit (Phase 43/44) — a SINGLE row
         is appended to STAGE_COMPLETION_OVERRIDES via roadmap_manager.
         record_stage_completion_override() ONLY when force=True
         actually bypassed at least one real block above (never for a
         force=yes call where neither gate would have blocked anyway —
         that would make the audit trail meaningless). When BOTH gates
         were genuinely bypassed by the same force=yes call, this is
         still exactly ONE audit row, with Override Type set to the
         "+"-joined composite of every gate actually bypassed (e.g.
         "missing_blocking_documents+missing_checklist_items") and every
         gate's own missing_* fields populated in that same row — never
         two separate rows for one completion operation. Written only
         after the Status write in G already succeeded. A failure
         recording this row does NOT roll back the Status write —
         surfaced via partial_success/downstream_failures.
      H. recalculate Roadmap progress, only if Status actually changed
      I. maybe auto-complete Roadmap, only after a successful recalculation
      J. return the structured result (ADR-017 §12)

    Explicit reopen (done/skipped -> anything else) is deliberately NOT
    implemented here — Phase 34C enforces only the block
    (STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION); the reopen mechanism
    itself is out of scope (ADR-017 Decision 8/24).

    A downstream failure (progress recalculation or auto-completion)
    never rolls back the already-confirmed Stage Status write — visible
    via partial_success=True and downstream_failures, exactly the same
    principle ADR-016 already applies to Roadmap-creation's Stage
    materialization.

    Args:
        stage_id:      STAGE-... to transition
        target_status: one of roadmap_manager.STAGE_STATUS_CANONICAL
        notes:         optional Notes column update (passed through to
                       update_stage_status_in_sheet unchanged)
        admin_fields:  optional dict of additional ROADMAP_STAGES admin
                       columns (e.g. {"Blocking Reason": "..."})  to
                       write in the same call, under the same
                       eligibility gate — used by /blockstage (sets
                       Blocking Reason + Status="blocked" together) and
                       /unblockstage (clears Blocking Reason + Status
                       back to "pending" together), so neither can bypass
                       Roadmap eligibility by splitting the two writes
                       across separate calls.
        force:         explicit management override of the Phase 43
                       document completion gate (in_progress->done only;
                       has no effect on any other transition). Requires
                       a non-blank `reason`.
        reason:        required (non-blank) whenever force=True; recorded
                       verbatim in the STAGE_COMPLETION_OVERRIDES audit
                       row when the override actually bypasses a block.
        actor:         who is performing this call (e.g. Telegram
                       username via telegram_handlers._telegram_username())
                       — recorded as "User" in the audit row. Never
                       required unless force actually bypasses a block.

    Returns:
        See _stage_transition_result() for the full field list.
    """
    from business_core.roadmap_manager import (
        STAGE_STATUS_CANONICAL, find_stage_by_id, find_roadmap_by_id,
        record_stage_completion_override,
        update_stage_status_in_sheet, update_stage_fields,
        recalculate_roadmap_progress, maybe_complete_roadmap,
        normalize_roadmap_status,
    )
    from business_core.sheets import SheetsQuotaExceededError, TransientSheetsReadError

    # A. Required identifier.
    if not stage_id:
        return _stage_transition_result(
            ok=False, code="STAGE_NOT_FOUND", error="stage_id обязателен",
            stage_id=stage_id, retry_safe=True,
        )

    # Sheets quota mitigation (2026-07-28, RM-003 incident post-mortem):
    # a 429/5xx/network failure during the Stage/Roadmap lookup below
    # must never be reported as STAGE_NOT_FOUND/ROADMAP_NOT_FOUND (that
    # exact masking turned a transient quota exhaustion into a false
    # "not found" during the incident). Nothing has been written yet at
    # this point, so `final_status` is unknown/empty ("Этап не изменён"
    # holds trivially — there is no confirmed previous state to report).
    try:
        # B. Stage existence.
        stage = find_stage_by_id(stage_id)
        if stage is None:
            return _stage_transition_result(
                ok=False, code="STAGE_NOT_FOUND", error=f"Этап {stage_id} не найден",
                stage_id=stage_id, retry_safe=True,
            )

        roadmap_id = stage.get("roadmap_id", "")
        previous_status = stage.get("status", "")

        # C. Parent Roadmap existence.
        roadmap = find_roadmap_by_id(roadmap_id) if roadmap_id else None
    except SheetsQuotaExceededError as exc:
        return _stage_transition_result(
            ok=False, code="SHEETS_QUOTA_EXCEEDED", error=str(exc),
            stage_id=stage_id, retry_safe=True,
        )
    except TransientSheetsReadError as exc:
        return _stage_transition_result(
            ok=False, code="TRANSIENT_SHEETS_READ_ERROR", error=str(exc),
            stage_id=stage_id, retry_safe=True,
        )

    if roadmap is None:
        return _stage_transition_result(
            ok=False, code="ROADMAP_NOT_FOUND",
            error=f"Roadmap {roadmap_id or '(пусто)'} для этапа {stage_id} не найден",
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status, retry_safe=True,
        )

    read_ctx = _TransitionReadContext(stage=stage, roadmap=roadmap)

    roadmap_status_before = normalize_roadmap_status(roadmap.get("status", ""))

    # D. Roadmap eligibility — "active" is the only status that allows
    # a Stage execution-status update (ADR-017 §7).
    eligibility_code = _roadmap_eligibility_code_for_stage_update(roadmap_status_before)
    if eligibility_code is not None:
        return _stage_transition_result(
            ok=False, code=eligibility_code,
            error=(
                f"Roadmap {roadmap_id} имеет статус '{roadmap_status_before}' — "
                f"изменение статуса этапа не разрешено"
            ),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )

    # E. Target status validation.
    if target_status not in STAGE_STATUS_CANONICAL:
        return _stage_transition_result(
            ok=False, code="INVALID_STAGE_STATUS",
            error=(
                f"Недопустимый статус '{target_status}'. "
                f"Допустимые значения: {', '.join(STAGE_STATUS_CANONICAL)}"
            ),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )

    # F. Current -> target transition validation.
    if previous_status in _STAGE_REOPEN_GATED_STATUSES and target_status != previous_status:
        return _stage_transition_result(
            ok=False, code="STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION",
            error=(
                f"Этап {stage_id} имеет статус '{previous_status}' — обычное "
                f"обновление не может вернуть его в '{target_status}'. "
                f"Требуется отдельное явное действие reopen (не реализовано)."
            ),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )

    allowed_targets = _STAGE_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _stage_transition_result(
            ok=False, code="INVALID_STAGE_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )

    # F.5. Stage Completion Gates (Phase 43 Document / Phase 44
    # Checklist) — only for the specific in_progress -> done edge; every
    # other transition (including any path to/from "skipped") is
    # completely unaffected and never evaluates either gate.
    gate_missing_blocking_doc_ids: tuple = ()
    gate_configuration_error_details = ""
    gate_missing_checklist_instance_ids: tuple = ()
    gate_missing_checklist_item_ids: tuple = ()
    gate_missing_checklist_item_titles: tuple = ()
    gate_missing_blocking_output_instance_ids: tuple = ()
    gate_missing_blocking_output_template_ids: tuple = ()
    gate_missing_blocking_output_titles: tuple = ()
    gate_missing_blocking_output_statuses: tuple = ()
    gate_override_types: list[str] = []
    gate_optional_missing_warnings: list[str] = []

    if previous_status == "in_progress" and target_status == "done":
        if force and not (reason or "").strip():
            return _stage_transition_result(
                ok=False, code="STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED",
                error="force=yes требует непустой reason.",
                stage_id=stage_id, roadmap_id=roadmap_id,
                previous_status=previous_status, requested_status=target_status,
                final_status=previous_status,
                roadmap_status_before=roadmap_status_before,
                roadmap_status_after=roadmap_status_before,
                retry_safe=True,
            )

        # All three gates are always evaluated together — never short-
        # circuited after the first one blocks — so a Stage missing
        # documents, checklist items, and Required Output all at once is
        # reported in full, in one response.
        document_gate = _evaluate_document_completion_gate(stage_id)
        checklist_gate = _evaluate_checklist_completion_gate(stage_id)
        output_gate = _evaluate_output_completion_gate(stage_id)
        blocked_gates = [g for g in (document_gate, checklist_gate, output_gate) if g.blocked]

        if document_gate.warning:
            gate_optional_missing_warnings.append(document_gate.warning)
        if checklist_gate.warning:
            gate_optional_missing_warnings.append(checklist_gate.warning)
        if output_gate.warning:
            gate_optional_missing_warnings.append(output_gate.warning)

        if blocked_gates:
            gate_missing_blocking_doc_ids = document_gate.missing_blocking_doc_ids
            gate_configuration_error_details = document_gate.configuration_error_details
            gate_missing_checklist_instance_ids = checklist_gate.missing_checklist_instance_ids
            gate_missing_checklist_item_ids = checklist_gate.missing_checklist_item_ids
            gate_missing_checklist_item_titles = checklist_gate.missing_checklist_item_titles
            gate_missing_blocking_output_instance_ids = output_gate.missing_blocking_output_instance_ids
            gate_missing_blocking_output_template_ids = output_gate.missing_blocking_output_template_ids
            gate_missing_blocking_output_titles = output_gate.missing_blocking_output_titles
            gate_missing_blocking_output_statuses = output_gate.missing_blocking_output_statuses
            gate_override_types = [g.override_type for g in blocked_gates]

            if not force:
                if len(blocked_gates) > 1:
                    combined_error = " | ".join(g.error for g in blocked_gates)
                    return _stage_transition_result(
                        ok=False, code="STAGE_COMPLETION_GATE_BLOCKED", error=combined_error,
                        stage_id=stage_id, roadmap_id=roadmap_id,
                        previous_status=previous_status, requested_status=target_status,
                        final_status=previous_status,
                        roadmap_status_before=roadmap_status_before,
                        roadmap_status_after=roadmap_status_before,
                        retry_safe=True,
                        missing_blocking_doc_ids=gate_missing_blocking_doc_ids,
                        configuration_error_details=gate_configuration_error_details,
                        missing_checklist_instance_ids=gate_missing_checklist_instance_ids,
                        missing_checklist_item_ids=gate_missing_checklist_item_ids,
                        missing_checklist_item_titles=gate_missing_checklist_item_titles,
                        missing_blocking_output_instance_ids=gate_missing_blocking_output_instance_ids,
                        missing_blocking_output_template_ids=gate_missing_blocking_output_template_ids,
                        missing_blocking_output_titles=gate_missing_blocking_output_titles,
                        missing_blocking_output_statuses=gate_missing_blocking_output_statuses,
                    )
                single = blocked_gates[0]
                return _stage_transition_result(
                    ok=False, code=single.error_code, error=single.error,
                    stage_id=stage_id, roadmap_id=roadmap_id,
                    previous_status=previous_status, requested_status=target_status,
                    final_status=previous_status,
                    roadmap_status_before=roadmap_status_before,
                    roadmap_status_after=roadmap_status_before,
                    retry_safe=True,
                    missing_blocking_doc_ids=gate_missing_blocking_doc_ids,
                    configuration_error_details=gate_configuration_error_details,
                    missing_checklist_instance_ids=gate_missing_checklist_instance_ids,
                    missing_checklist_item_ids=gate_missing_checklist_item_ids,
                    missing_checklist_item_titles=gate_missing_checklist_item_titles,
                    missing_blocking_output_instance_ids=gate_missing_blocking_output_instance_ids,
                    missing_blocking_output_template_ids=gate_missing_blocking_output_template_ids,
                    missing_blocking_output_titles=gate_missing_blocking_output_titles,
                    missing_blocking_output_statuses=gate_missing_blocking_output_statuses,
                )

    gate_override_type = "+".join(gate_override_types)

    # F.7. Dependency Gate (Dependencies Foundation, 2026-07-28,
    # DECISIONS.md §14a) — strictly pending->in_progress only, strictly
    # before G (no Status write below this point may execute if this
    # gate blocks). Functionally disjoint from F.5 (which only fires for
    # in_progress->done) — the two gates never evaluate on the same
    # transition. No force/override exists for this gate in this phase;
    # a blocked dependency gate always returns early here, exactly like
    # every other pre-G validation failure above — Status/Start Date/
    # Progress/Roadmap-completion/K (auto-provisioning) are never
    # reached.
    if previous_status == "pending" and target_status == "in_progress":
        # Sheets quota mitigation (2026-07-28): a 429/5xx/network failure
        # while evaluating the Dependency Gate must never be reported as
        # DEPENDENCY_CONFIGURATION_ERROR (that implies corrupted DATA,
        # not a transient infra failure) — nothing has been written yet
        # at this point, so "Этап не изменён" holds.
        try:
            dep_gate = _evaluate_stage_dependency_gate(stage_id, read_context=read_ctx)
        except SheetsQuotaExceededError as exc:
            return _stage_transition_result(
                ok=False, code="SHEETS_QUOTA_EXCEEDED", error=str(exc),
                stage_id=stage_id, roadmap_id=roadmap_id,
                previous_status=previous_status, requested_status=target_status,
                final_status=previous_status,
                roadmap_status_before=roadmap_status_before,
                roadmap_status_after=roadmap_status_before,
                retry_safe=True,
            )
        except TransientSheetsReadError as exc:
            return _stage_transition_result(
                ok=False, code="TRANSIENT_SHEETS_READ_ERROR", error=str(exc),
                stage_id=stage_id, roadmap_id=roadmap_id,
                previous_status=previous_status, requested_status=target_status,
                final_status=previous_status,
                roadmap_status_before=roadmap_status_before,
                roadmap_status_after=roadmap_status_before,
                retry_safe=True,
            )
        if dep_gate.blocked:
            return _stage_transition_result(
                ok=False, code=dep_gate.error_code, error=dep_gate.error,
                stage_id=stage_id, roadmap_id=roadmap_id,
                previous_status=previous_status, requested_status=target_status,
                final_status=previous_status,
                roadmap_status_before=roadmap_status_before,
                roadmap_status_after=roadmap_status_before,
                retry_safe=True,
                dependencies_checked=True,
                unsatisfied_dependencies=dep_gate.unsatisfied,
                missing_live_dependency_stages=dep_gate.missing_live_stages,
                dependency_configuration_errors=dep_gate.configuration_errors,
            )

    # G. Persist Stage status (+ any coupled admin_fields).
    #
    # Sheets quota mitigation (2026-07-28): update_stage_status_in_sheet()
    # itself re-reads the Stage (find_stage_by_id()) BEFORE its own write
    # attempt — if THAT re-read hits a 429/5xx/network failure, it raises
    # here, before any cell has been touched. This is still a pre-write
    # failure (final_status=previous_status, "Этап не изменён" holds) —
    # never a corrupted-data STAGE_WRITE_PARTIAL_FAILURE.
    try:
        write_result = update_stage_status_in_sheet(stage_id, target_status, notes=notes)
    except SheetsQuotaExceededError as exc:
        return _stage_transition_result(
            ok=False, code="SHEETS_QUOTA_EXCEEDED", error=str(exc),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )
    except TransientSheetsReadError as exc:
        return _stage_transition_result(
            ok=False, code="TRANSIENT_SHEETS_READ_ERROR", error=str(exc),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status,
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )
    if not write_result["ok"]:
        return _stage_transition_result(
            ok=False, code="STAGE_WRITE_PARTIAL_FAILURE",
            error=write_result.get("error"),
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=write_result.get("final_status", previous_status),
            roadmap_status_before=roadmap_status_before,
            roadmap_status_after=roadmap_status_before,
            retry_safe=True,
        )

    final_status = write_result["final_status"]
    changed = write_result["changed"]
    written_fields = list(write_result.get("updated_fields", ()))
    warnings = list(write_result.get("warnings", ()))
    downstream_failures: list[str] = []
    partial_success = bool(write_result.get("partial_success"))

    if admin_fields:
        admin_result = update_stage_fields(stage_id, admin_fields)
        if admin_result["ok"]:
            written_fields.extend(admin_result.get("written_fields", ()))
        else:
            partial_success = True
            downstream_failures.append(f"Не удалось обновить дополнительные поля: {admin_result.get('error')}")

    for w in gate_optional_missing_warnings:
        warnings.append(w)

    # Audit trail (Phase 43/44): only written when at least one gate
    # actually had something to override (gate_override_type is non-empty
    # only when force=True genuinely bypassed a real block above — never
    # for a force=yes call where nothing was blocking, so a repeat "done"
    # call or an unnecessary force=yes never creates a second/duplicate
    # row). When BOTH gates were bypassed by this same call, this is
    # still exactly ONE row — gate_override_type is already the
    # "+"-joined composite of every gate that blocked, and every gate's
    # own missing_* fields are included in this single call. Written only
    # now, AFTER the Status write above already succeeded (changed is
    # guaranteed True here, since previous_status="in_progress" !=
    # target_status="done" by construction) — never before, and never if
    # that write had failed (this code path is unreachable in that case,
    # see the early return a few lines above). A failure recording the
    # audit row does NOT roll back the already-confirmed Status write —
    # surfaced via partial_success/downstream_failures, the same
    # principle already used for progress-recalculation/auto-completion
    # failures below.
    override_applied = False
    override_id = ""
    if gate_override_type:
        override_applied = True
        override_result = record_stage_completion_override(
            stage_id=stage_id, roadmap_id=roadmap_id, user=actor, reason=(reason or "").strip(),
            missing_blocking_doc_ids=gate_missing_blocking_doc_ids,
            previous_status=previous_status, target_status=target_status,
            override_type=gate_override_type,
            configuration_error_details=gate_configuration_error_details,
            missing_checklist_instance_ids=gate_missing_checklist_instance_ids,
            missing_checklist_item_ids=gate_missing_checklist_item_ids,
            missing_checklist_item_titles=gate_missing_checklist_item_titles,
            missing_blocking_output_instance_ids=gate_missing_blocking_output_instance_ids,
            missing_blocking_output_template_ids=gate_missing_blocking_output_template_ids,
            missing_blocking_output_titles=gate_missing_blocking_output_titles,
            missing_blocking_output_statuses=gate_missing_blocking_output_statuses,
        )
        if override_result["ok"]:
            override_id = override_result["override_id"]
        else:
            partial_success = True
            downstream_failures.append(
                f"Override применён, но запись в audit trail не удалась: {override_result.get('error')}"
            )

    progress_before = None
    progress_after = None
    roadmap_status_after = roadmap_status_before

    code = "STAGE_STATUS_UPDATED" if changed else "STAGE_STATUS_UNCHANGED"

    # H. Progress recalculation — only if Status actually changed.
    if changed:
        progress_result = recalculate_roadmap_progress(roadmap_id, read_context=read_ctx)
        if progress_result["ok"]:
            progress_after = progress_result["new_progress"]
            try:
                progress_before = int(progress_result.get("old_progress") or 0)
            except (TypeError, ValueError):
                progress_before = None

            # I. Maybe auto-complete Roadmap — only after a successful
            # recalculation. read_context reuses the exact ROADMAP_STAGES
            # list H just read (via get_stages_for_roadmap()) instead of
            # a second full-table re-read — see _TransitionReadContext.
            completion_result = maybe_complete_roadmap(roadmap_id, progress_pct=progress_after, read_context=read_ctx)
            if completion_result["ok"]:
                roadmap_status_after = normalize_roadmap_status(completion_result.get("new_status", roadmap_status_before))
            else:
                partial_success = True
                downstream_failures.append(f"Не удалось проверить завершение Roadmap: {completion_result.get('error')}")
                code = "ROADMAP_AUTO_COMPLETION_FAILED"
        else:
            partial_success = True
            downstream_failures.append(f"Не удалось пересчитать прогресс: {progress_result.get('error')}")
            code = "PROGRESS_RECALCULATION_FAILED"

    # K. Auto-provisioning (Unified Stage Provisioning auto-trigger):
    # strictly pending->in_progress, and only when the write in G actually
    # changed the Stage's status — never for a repeat in_progress call,
    # never for blocked->in_progress/in_progress->blocked/in_progress->done/
    # force completion/admin-field-only updates (all excluded by this exact
    # condition on previous_status/target_status/changed, captured before
    # any write above). Runs strictly after G (Status persisted), H
    # (Progress recalculated), and I (Roadmap auto-completion checked) —
    # the Stage's core state is fully settled before this best-effort
    # downstream step runs.
    #
    # provision_stage_operational_instances() already never raises on its
    # own (both of ITS child subsystems are individually try/except'ed
    # internally) — this try/except here is defense-in-depth on top of
    # that, not a substitute for it: if anything here still raises
    # unexpectedly, it is caught and folded into downstream_failures/
    # provisioning_warning, exactly like every other downstream step above
    # (progress recalculation, roadmap auto-completion) — it NEVER rolls
    # back the Status write already confirmed in G, and it NEVER changes
    # `code` away from "STAGE_STATUS_UPDATED" (unlike the progress/
    # completion downstream failures above, which do override `code` —
    # deliberately different here: provisioning is auxiliary staff
    # tooling, not Roadmap data-integrity-critical, per the approved
    # design).
    provisioning_attempted = False
    provisioning_result: dict | None = None
    provisioning_warning = ""
    if previous_status == "pending" and target_status == "in_progress" and changed:
        provisioning_attempted = True
        try:
            provisioning_result = provision_stage_operational_instances(
                stage_id=stage_id, confirm=True, trigger="stage_started", actor=actor,
                read_context=read_ctx,
            )
            prov_code = provisioning_result.get("code", "")
            if prov_code == "STAGE_PROVISION_PARTIAL":
                partial_success = True
                downstream_failures.append(
                    f"Provisioning выполнен частично: {provisioning_result.get('totals', {})}"
                )
                provisioning_warning = "Provisioning выполнен частично"
            elif prov_code == "STAGE_PROVISION_FAILED":
                partial_success = True
                downstream_failures.append(
                    f"Provisioning не создал ни одного operational instance: {provisioning_result.get('totals', {})}"
                )
                provisioning_warning = "Этап переведён в работу, но operational instances не созданы"
            # STAGE_PROVISIONED / NOTHING_TO_PROVISION / a resolution-
            # failure code all leave provisioning_warning empty — the
            # first two are success states, and a resolution failure here
            # (extremely unlikely, since resolve_template_stage_for_stage()
            # already succeeded moments ago for this same stage_id inside
            # this very function) is surfaced via downstream_failures only.
            elif not provisioning_result.get("ok"):
                partial_success = True
                downstream_failures.append(
                    f"Provisioning не выполнен: {provisioning_result.get('code')}"
                )
        except Exception as exc:
            log.error(f"transition_stage_status({stage_id}): auto-provisioning exception: {exc}")
            partial_success = True
            downstream_failures.append(f"Provisioning вызвал непредвиденную ошибку: {exc}")
            provisioning_warning = "Provisioning вызвал непредвиденную ошибку"
            provisioning_result = provisioning_result or {}

    return _stage_transition_result(
        ok=True, code=code, error=None,
        stage_id=stage_id, roadmap_id=roadmap_id,
        previous_status=previous_status, requested_status=target_status,
        final_status=final_status, changed=changed,
        partial_success=partial_success, written_fields=tuple(written_fields),
        warnings=tuple(warnings), downstream_failures=tuple(downstream_failures),
        progress_before=progress_before, progress_after=progress_after,
        roadmap_status_before=roadmap_status_before, roadmap_status_after=roadmap_status_after,
        retry_safe=True,
        missing_blocking_doc_ids=gate_missing_blocking_doc_ids,
        configuration_error_details=gate_configuration_error_details,
        override_applied=override_applied, override_type=gate_override_type, override_id=override_id,
        missing_checklist_instance_ids=gate_missing_checklist_instance_ids,
        missing_checklist_item_ids=gate_missing_checklist_item_ids,
        missing_checklist_item_titles=gate_missing_checklist_item_titles,
        missing_blocking_output_instance_ids=gate_missing_blocking_output_instance_ids,
        missing_blocking_output_template_ids=gate_missing_blocking_output_template_ids,
        missing_blocking_output_titles=gate_missing_blocking_output_titles,
        missing_blocking_output_statuses=gate_missing_blocking_output_statuses,
        provisioning_attempted=provisioning_attempted,
        provisioning=provisioning_result,
        provisioning_warning=provisioning_warning,
        dependencies_checked=(previous_status == "pending" and target_status == "in_progress"),
    )


def update_stage_admin_fields(stage_id: str, writes: dict) -> dict:
    """
    Phase 34C (ADR-017 Decision 13/19/20): canonical orchestration
    boundary for Stage ADMINISTRATIVE field edits (Responsible, Notes,
    Due Date, Priority, Blocking Reason) — used by /assignstage,
    /duedate, /priority. Never accepts a "Status" key (that always goes
    through transition_stage_status(); roadmap_manager.
    update_stage_fields() itself now rejects "Status" outright as a
    second line of defense).

    Roadmap eligibility for admin-only edits (ADR-017 §13/19, distinct
    and looser than execution-status eligibility in transition_stage_status):
      active:    allowed
      on_hold:   allowed (administrative fields do not advance execution)
      completed: blocked (ROADMAP_COMPLETED) — a completed Roadmap is a
                 historical snapshot, no edits at all
      cancelled: blocked (ROADMAP_CANCELLED) — same reasoning

    Does not duplicate the transition matrix or reopen policy — this
    function never touches Status.

    Returns:
        Same structured shape as _stage_transition_result(), with
        requested_status/previous_status/final_status left blank
        (not applicable to an admin-only edit).
    """
    from business_core.roadmap_manager import find_stage_by_id, find_roadmap_by_id, update_stage_fields, normalize_roadmap_status

    if not stage_id:
        return _stage_transition_result(
            ok=False, code="STAGE_NOT_FOUND", error="stage_id обязателен", stage_id=stage_id,
        )

    stage = find_stage_by_id(stage_id)
    if stage is None:
        return _stage_transition_result(
            ok=False, code="STAGE_NOT_FOUND", error=f"Этап {stage_id} не найден", stage_id=stage_id,
        )

    roadmap_id = stage.get("roadmap_id", "")
    roadmap = find_roadmap_by_id(roadmap_id) if roadmap_id else None
    if roadmap is None:
        return _stage_transition_result(
            ok=False, code="ROADMAP_NOT_FOUND",
            error=f"Roadmap {roadmap_id or '(пусто)'} для этапа {stage_id} не найден",
            stage_id=stage_id, roadmap_id=roadmap_id,
        )

    roadmap_status = normalize_roadmap_status(roadmap.get("status", ""))

    if roadmap_status == "completed":
        return _stage_transition_result(
            ok=False, code="ROADMAP_COMPLETED",
            error=f"Roadmap {roadmap_id} завершён — изменение полей этапа не разрешено",
            stage_id=stage_id, roadmap_id=roadmap_id,
            roadmap_status_before=roadmap_status, roadmap_status_after=roadmap_status,
        )
    if roadmap_status == "cancelled":
        return _stage_transition_result(
            ok=False, code="ROADMAP_CANCELLED",
            error=f"Roadmap {roadmap_id} отменён — изменение полей этапа не разрешено",
            stage_id=stage_id, roadmap_id=roadmap_id,
            roadmap_status_before=roadmap_status, roadmap_status_after=roadmap_status,
        )
    # active / on_hold: administrative edits allowed.

    write_result = update_stage_fields(stage_id, writes)
    if not write_result["ok"]:
        return _stage_transition_result(
            ok=False, code="STAGE_WRITE_PARTIAL_FAILURE", error=write_result.get("error"),
            stage_id=stage_id, roadmap_id=roadmap_id,
            roadmap_status_before=roadmap_status, roadmap_status_after=roadmap_status,
        )

    return _stage_transition_result(
        ok=True, code="STAGE_STATUS_UNCHANGED", error=None,
        stage_id=stage_id, roadmap_id=roadmap_id,
        written_fields=tuple(write_result.get("written_fields", ())),
        roadmap_status_before=roadmap_status, roadmap_status_after=roadmap_status,
    )


# ─────────────────────────────────────────────────────────────
# Phase 35D (ADR-018): Organization Person↔Role assignment
# orchestration boundary.
#
# organization_manager.py remains the sole persistence owner of
# DEPARTMENT_REGISTRY/ROLE_REGISTRY/ROLE_FUNCTIONS/
# PERSON_ROLE_ASSIGNMENTS (unchanged by this phase). Everything that
# crosses from "one Person" / "one Role" to cross-entity eligibility —
# archived-Person, Role status, parent-Department status, Business
# membership, duplicate-active-Assignment policy — lives here instead,
# exactly the same boundary principle ADR-016/ADR-017 already applied
# to Roadmap creation and Stage transitions. No second implementation
# of this policy exists anywhere else (see
# test_organization_architecture_guards.py).
# ─────────────────────────────────────────────────────────────

def _assignment_result(
    *, ok: bool, code: str, error: str | None, department_id: str = "",
    role_id: str = "", person_id: str = "", assignment_id: str = "",
    assignment_created: bool = False, assignment_reused: bool = False,
    previous_status: str = "", final_status: str = "", warnings: tuple = (),
    conflicting_assignment_ids: tuple = (), retry_safe: bool = True,
) -> dict:
    """
    Shared result-builder for assign_person_to_role_canonical() —
    ADR-018 §21's stable, structured contract.
    """
    return {
        "ok": ok,
        "code": code,
        "error": error,
        "department_id": department_id,
        "role_id": role_id,
        "person_id": person_id,
        "assignment_id": assignment_id,
        "assignment_created": assignment_created,
        "assignment_reused": assignment_reused,
        "previous_status": previous_status,
        "final_status": final_status,
        "warnings": tuple(warnings),
        "conflicting_assignment_ids": tuple(conflicting_assignment_ids),
        "retry_safe": retry_safe,
    }


def assign_person_to_role_canonical(
    person_id: str,
    role_id: str,
    start_date: str,
    assignment_type: str = "primary",
    notes: str = "",
) -> dict:
    """
    Phase 35D (ADR-018): the sole canonical Person↔Role assignment
    orchestration boundary. /assignrole and any other future caller
    must call this — never organization_manager.assign_person_to_role()
    directly — so Person/Role/Department/Business-membership eligibility
    and duplicate-active-Assignment policy is enforced exactly once, in
    exactly one place.

    Validation order (ADR-018 §5, all before any write):
      A. required person_id
      B. Person exists (PERSON_NOT_FOUND)
      C. Person not archived (PERSON_ARCHIVED)
      D. required role_id
      E. Role exists (ROLE_NOT_FOUND)
      F. parent Department exists (DEPARTMENT_NOT_FOUND)
      G. Department not archived (DEPARTMENT_ARCHIVED)
      H. Role eligibility — planned/active allowed, paused/archived
         blocked (ROLE_PAUSED/ROLE_ARCHIVED)
      I. Business-scope membership — only when the Department is
         Business-scoped (PERSON_NOT_LINKED_TO_BUSINESS/
         PERSON_ROLE_BUSINESS_MISMATCH); a global Department (blank
         Business ID) requires no membership at all
      J. active-duplicate Assignment lookup for (Person ID, Role ID)
      K. zero/one/multiple policy — zero creates, exactly one is
         reused idempotently, more than one blocks
         (MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR, never an
         arbitrary first pick)
      L. create or reuse via organization_manager.assign_person_to_role()
         (unchanged low-level persistence)
      M. return the structured result (ADR-018 §21)

    Args:
        person_id:       PRS-... to assign
        role_id:         ROLE-... to assign to
        start_date:      YYYY-MM-DD, required by the low-level API
        assignment_type: primary/backup/temporary
        notes:           optional Notes column value

    Returns:
        See _assignment_result() for the full field list.
    """
    from business_core.organization_manager import (
        find_role_by_id, find_department_by_id, assign_person_to_role,
        list_assignments_for_role,
    )

    # A/B. Required person_id, Person exists.
    if not person_id:
        return _assignment_result(ok=False, code="PERSON_NOT_FOUND", error="person_id обязателен")

    from business_core.person_manager import find_person_by_id, is_person_archived, has_person_business_link
    person = find_person_by_id(person_id)
    if person is None:
        return _assignment_result(
            ok=False, code="PERSON_NOT_FOUND", error=f"Person {person_id} не найден", person_id=person_id,
        )

    # C. Person not archived.
    if is_person_archived(person):
        return _assignment_result(
            ok=False, code="PERSON_ARCHIVED",
            error=f"Person {person_id} архивирован — назначение не разрешено", person_id=person_id,
        )

    # D/E. Required role_id, Role exists.
    if not role_id:
        return _assignment_result(ok=False, code="ROLE_NOT_FOUND", error="role_id обязателен", person_id=person_id)

    role = find_role_by_id(role_id)
    if role is None:
        return _assignment_result(
            ok=False, code="ROLE_NOT_FOUND", error=f"Role {role_id} не найден",
            person_id=person_id, role_id=role_id,
        )

    # F/G. Parent Department exists and is not archived.
    department_id = role.get("department_id", "")
    department = find_department_by_id(department_id) if department_id else None
    if department is None:
        return _assignment_result(
            ok=False, code="DEPARTMENT_NOT_FOUND", error=f"Department {department_id} не найден",
            person_id=person_id, role_id=role_id, department_id=department_id,
        )
    if department.get("status") == "archived":
        return _assignment_result(
            ok=False, code="DEPARTMENT_ARCHIVED", error=f"Department {department_id} архивирован",
            person_id=person_id, role_id=role_id, department_id=department_id,
        )

    # H. Role eligibility for Person assignment — planned/active allowed,
    # paused/archived blocked.
    role_status = role.get("status", "")
    if role_status == "paused":
        return _assignment_result(
            ok=False, code="ROLE_PAUSED", error=f"Role {role_id} приостановлена — назначение не разрешено",
            person_id=person_id, role_id=role_id, department_id=department_id,
        )
    if role_status == "archived":
        return _assignment_result(
            ok=False, code="ROLE_ARCHIVED", error=f"Role {role_id} архивирована — назначение не разрешено",
            person_id=person_id, role_id=role_id, department_id=department_id,
        )
    if role_status not in ("planned", "active"):
        return _assignment_result(
            ok=False, code="INVALID_ROLE_STATUS", error=f"Role {role_id} имеет неизвестный статус '{role_status}'",
            person_id=person_id, role_id=role_id, department_id=department_id,
        )

    # I. Business-scope membership — only when Department is Business-
    # scoped (ADR-018 §11). A global Department (blank Business ID)
    # requires no membership at all.
    business_id = department.get("business_id", "")
    if business_id:
        if not has_person_business_link(person, business_id):
            linked_ids = person.get("biz_ids") or []
            if not linked_ids:
                return _assignment_result(
                    ok=False, code="PERSON_NOT_LINKED_TO_BUSINESS",
                    error=f"Person {person_id} не привязан к бизнесу {business_id}",
                    person_id=person_id, role_id=role_id, department_id=department_id,
                )
            return _assignment_result(
                ok=False, code="PERSON_ROLE_BUSINESS_MISMATCH",
                error=f"Person {person_id} привязан к другому бизнесу, а не к {business_id}",
                person_id=person_id, role_id=role_id, department_id=department_id,
            )

    # J/K. Active-duplicate Assignment lookup for (Person ID, Role ID).
    active_assignments = list_assignments_for_role(role_id, status="active")
    matching = [a for a in active_assignments if a.get("person_id") == person_id]

    if len(matching) > 1:
        conflicting_ids = tuple(a.get("assignment_id", "") for a in matching)
        return _assignment_result(
            ok=False, code="MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR",
            error=(
                f"Найдено {len(matching)} активных Assignment для (Person={person_id}, "
                f"Role={role_id}): {conflicting_ids} — новый Assignment не создан"
            ),
            person_id=person_id, role_id=role_id, department_id=department_id,
            conflicting_assignment_ids=conflicting_ids, retry_safe=True,
        )

    if len(matching) == 1:
        existing = matching[0]
        return _assignment_result(
            ok=True, code="ASSIGNMENT_REUSED", error=None,
            person_id=person_id, role_id=role_id, department_id=department_id,
            assignment_id=existing.get("assignment_id", ""), assignment_reused=True,
            previous_status="active", final_status="active", retry_safe=True,
        )

    # L. Create — zero matching active Assignment.
    write_result = assign_person_to_role(
        person_id, role_id, start_date, assignment_type=assignment_type, notes=notes,
    )
    if not write_result["ok"]:
        return _assignment_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            person_id=person_id, role_id=role_id, department_id=department_id, retry_safe=True,
        )

    return _assignment_result(
        ok=True, code="ASSIGNMENT_CREATED", error=None,
        person_id=person_id, role_id=role_id, department_id=department_id,
        assignment_id=write_result["assignment_id"], assignment_created=True,
        previous_status="", final_status="active", retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Phase 36C (ADR-019): Task Domain Foundation — the sole cross-domain
# Task orchestration boundary. task_manager.py remains the persistence-
# only owner of TASK_REGISTRY/TASK_ASSIGNMENTS (unchanged by this
# phase's design — mirrors organization_manager.py's role exactly).
# Everything that crosses from "one Task" / "one Task Assignment" to
# cross-entity eligibility — Business/Client/Object/Service/Roadmap/
# Stage existence and consistency, Roadmap/Stage lifecycle eligibility,
# Organization Person/Role eligibility, creation idempotency, duplicate
# Assignment policy — lives here instead, the same boundary principle
# ADR-016/ADR-017/ADR-018 already applied to Roadmap creation, Stage
# transitions, and Organization Person↔Role assignment. No second
# implementation of this policy exists anywhere else (see
# test_task_architecture_guards.py).
# ─────────────────────────────────────────────────────────────

_TASK_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new":         ("new", "ready", "cancelled", "skipped"),
    "ready":       ("ready", "in_progress", "waiting", "blocked", "done", "cancelled", "skipped"),
    "in_progress": ("in_progress", "ready", "waiting", "blocked", "done", "cancelled", "skipped"),
    "waiting":     ("waiting", "ready", "in_progress", "blocked", "done", "cancelled", "skipped"),
    "blocked":     ("blocked", "ready", "in_progress", "waiting", "cancelled", "skipped"),
    "done":        ("done",),
    "cancelled":   ("cancelled",),
    "skipped":     ("skipped",),
}

_TASK_REOPEN_GATED_STATUSES = frozenset({"done", "cancelled", "skipped"})


def _task_result(
    *, ok: bool, code: str, error: str | None, task_id: str = "", business_id: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    changed: bool = False, assignment_changed: bool = False,
    task_created: bool = False, task_reused: bool = False,
    assignment_id: str = "", previous_assignment_id: str = "",
    warnings: tuple = (), conflicting_task_ids: tuple = (),
    conflicting_assignment_ids: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Task orchestration function
    (ADR-019 §25) — the stable, structured contract every caller reads
    instead of a bare exception or ad-hoc dict shape."""
    return {
        "ok": ok,
        "code": code,
        "error": error,
        "task_id": task_id,
        "business_id": business_id,
        "previous_status": previous_status,
        "requested_status": requested_status,
        "final_status": final_status,
        "changed": changed,
        "assignment_changed": assignment_changed,
        "task_created": task_created,
        "task_reused": task_reused,
        "assignment_id": assignment_id,
        "previous_assignment_id": previous_assignment_id,
        "warnings": tuple(warnings),
        "conflicting_task_ids": tuple(conflicting_task_ids),
        "conflicting_assignment_ids": tuple(conflicting_assignment_ids),
        "retry_safe": retry_safe,
    }


def _task_roadmap_stage_eligibility_for_creation(roadmap_id: str, stage_id: str) -> tuple[str, str, str]:
    """
    ADR-019 §9: new linked Task creation eligibility. Returns
    (code, error, resolved_roadmap_id) — code is "" when eligible.
    Resolves Stage->Roadmap when only stage_id is supplied (Stage
    canonically derives Roadmap ID, per ADR-019 §7).
    """
    from business_core.roadmap_manager import find_stage_by_id, find_roadmap_by_id, normalize_roadmap_status

    resolved_roadmap_id = roadmap_id

    if stage_id:
        stage = find_stage_by_id(stage_id)
        if stage is None:
            return "STAGE_NOT_FOUND", f"Stage {stage_id} не найден", resolved_roadmap_id

        stage_roadmap_id = stage.get("roadmap_id", "")
        if roadmap_id and stage_roadmap_id != roadmap_id:
            return (
                "TASK_ENTITY_RELATION_MISMATCH",
                f"Stage {stage_id} принадлежит Roadmap {stage_roadmap_id}, а не {roadmap_id}",
                resolved_roadmap_id,
            )
        resolved_roadmap_id = stage_roadmap_id

        if stage.get("status", "") in ("done", "skipped"):
            return "STAGE_TERMINAL", f"Stage {stage_id} имеет терминальный статус '{stage.get('status', '')}'", resolved_roadmap_id

    if not resolved_roadmap_id:
        return "", None, resolved_roadmap_id

    roadmap = find_roadmap_by_id(resolved_roadmap_id)
    if roadmap is None:
        return "ROADMAP_NOT_FOUND", f"Roadmap {resolved_roadmap_id} не найден", resolved_roadmap_id

    roadmap_status = normalize_roadmap_status(roadmap.get("status", ""))
    if roadmap_status == "completed":
        return "ROADMAP_COMPLETED", f"Roadmap {resolved_roadmap_id} завершён — новый связанный Task не может быть создан", resolved_roadmap_id
    if roadmap_status == "cancelled":
        return "ROADMAP_CANCELLED", f"Roadmap {resolved_roadmap_id} отменён — новый связанный Task не может быть создан", resolved_roadmap_id
    # active/on_hold both allow new Task creation (ADR-019 §9/§20) —
    # on_hold only blocks the in_progress *transition*, not creation.
    return "", None, resolved_roadmap_id


def create_business_task(
    business_id: str,
    title: str,
    *,
    description: str = "",
    priority: str = "",
    due_date: str = "",
    source: str = "",
    idempotency_key: str = "",
    client_id: str = "",
    object_id: str = "",
    service_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    created_by: str = "",
    gtd_action_id: str = "",
) -> dict:
    """
    Phase 36C (ADR-019 §7): the sole canonical Business Task creation
    orchestration boundary. Any future caller must use this — never
    task_manager.create_task() directly — so Business/relation
    validation, Roadmap/Stage lifecycle eligibility, and creation
    idempotency is enforced exactly once, in exactly one place.

    Validation order (ADR-019 §7, all before any write):
      A. required business_id
      B. Business exists (BUSINESS_NOT_FOUND)
      C. required title
      D. normalize optional inputs (blank strings, not None)
      E. validate Client reference (PERSON_NOT_FOUND if supplied and missing)
      F. validate Object reference (TASK_NOT_FOUND-style existence via
         object_manager; TASK_ENTITY_RELATION_MISMATCH on Business mismatch)
      G. validate Service reference (same shape as Object)
      H. validate Roadmap reference (ROADMAP_NOT_FOUND)
      I. validate Stage reference (STAGE_NOT_FOUND), derive Roadmap ID
         from Stage when Roadmap ID is omitted
      J. cross-validate Stage<->Roadmap (TASK_ENTITY_RELATION_MISMATCH)
      K. cross-validate Roadmap<->Object/Service where supplied
         (TASK_ENTITY_RELATION_MISMATCH)
      L. lifecycle eligibility (ROADMAP_COMPLETED/ROADMAP_CANCELLED/
         STAGE_TERMINAL)
      M. idempotency lookup (Business ID + Idempotency Key)
      N. zero/one/multiple policy (TASK_CREATED/TASK_REUSED/
         MULTIPLE_TASK_IDEMPOTENCY_MATCHES — never an arbitrary first pick)
      O. Task ID generated only inside task_manager.create_task(), i.e.
         only once every validation above has passed
      P. low-level persistence call
      Q. structured result (ADR-019 §25)

    No write before all validation passes.
    """
    from business_core.task_manager import create_task, find_tasks_by_idempotency_key
    from business_core.sheets import find_row_by_id

    # A. Required business_id.
    if not business_id:
        return _task_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")

    # B. Business existence.
    if find_row_by_id("biz_registry", business_id) is None:
        return _task_result(ok=False, code="BUSINESS_NOT_FOUND", error=f"Business {business_id} не найден", business_id=business_id)

    # C. Required title.
    if not title:
        return _task_result(ok=False, code="", error="title обязателен", business_id=business_id)

    # D. Normalize optional inputs.
    client_id = client_id or ""
    object_id = object_id or ""
    service_id = service_id or ""
    roadmap_id = roadmap_id or ""
    stage_id = stage_id or ""

    # E. Client reference.
    if client_id:
        from business_core.person_manager import find_person_by_id
        person = find_person_by_id(client_id)
        if person is None:
            return _task_result(ok=False, code="PERSON_NOT_FOUND", error=f"Client {client_id} не найден", business_id=business_id)

    # F. Object reference.
    if object_id:
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(object_id)
        if obj is None:
            return _task_result(ok=False, code="TASK_ENTITY_RELATION_MISMATCH", error=f"Object {object_id} не найден", business_id=business_id)
        if obj.get("biz_id", "") and obj.get("biz_id", "") != business_id:
            return _task_result(
                ok=False, code="TASK_ENTITY_RELATION_MISMATCH",
                error=f"Object {object_id} принадлежит другому Business", business_id=business_id,
            )

    # G. Service reference.
    if service_id:
        from business_core.service_manager import find_service_by_id
        service = find_service_by_id(service_id)
        if service is None:
            return _task_result(ok=False, code="TASK_ENTITY_RELATION_MISMATCH", error=f"Service {service_id} не найден", business_id=business_id)
        if service.get("biz_id", "") and service.get("biz_id", "") != business_id:
            return _task_result(
                ok=False, code="TASK_ENTITY_RELATION_MISMATCH",
                error=f"Service {service_id} принадлежит другому Business", business_id=business_id,
            )

    # H/I/J. Roadmap/Stage existence + cross-validation + lifecycle
    # eligibility (L), all in one pass via the shared helper.
    eligibility_code, eligibility_error, resolved_roadmap_id = _task_roadmap_stage_eligibility_for_creation(roadmap_id, stage_id)
    if eligibility_code:
        return _task_result(ok=False, code=eligibility_code, error=eligibility_error, business_id=business_id)
    roadmap_id = resolved_roadmap_id

    # K. Roadmap<->Object/Service consistency where supplied.
    if roadmap_id and (object_id or service_id):
        from business_core.roadmap_manager import find_roadmap_by_id
        roadmap = find_roadmap_by_id(roadmap_id)
        if roadmap is not None:
            if object_id and roadmap.get("object_id", "") and roadmap.get("object_id", "") != object_id:
                return _task_result(
                    ok=False, code="TASK_ENTITY_RELATION_MISMATCH",
                    error=f"Roadmap {roadmap_id} принадлежит другому Object, не {object_id}", business_id=business_id,
                )
            if service_id and roadmap.get("service_id", "") and roadmap.get("service_id", "") != service_id:
                return _task_result(
                    ok=False, code="TASK_ENTITY_RELATION_MISMATCH",
                    error=f"Roadmap {roadmap_id} принадлежит другому Service, не {service_id}", business_id=business_id,
                )

    # M/N. Idempotency lookup.
    if idempotency_key:
        matches = find_tasks_by_idempotency_key(business_id, idempotency_key)
        if len(matches) > 1:
            conflicting_ids = tuple(t.get("task_id", "") for t in matches)
            return _task_result(
                ok=False, code="MULTIPLE_TASK_IDEMPOTENCY_MATCHES",
                error=(
                    f"Найдено {len(matches)} Task для (Business={business_id}, "
                    f"Idempotency Key={idempotency_key}): {conflicting_ids} — новый Task не создан"
                ),
                business_id=business_id, conflicting_task_ids=conflicting_ids, retry_safe=True,
            )
        if len(matches) == 1:
            existing = matches[0]
            return _task_result(
                ok=True, code="TASK_REUSED", error=None,
                task_id=existing.get("task_id", ""), business_id=business_id,
                task_reused=True, final_status=existing.get("status", ""), retry_safe=True,
            )

    # O/P. Create — zero matching Task (or no idempotency key supplied).
    write_result = create_task(
        business_id, title,
        description=description, priority=priority, due_date=due_date,
        source=source, idempotency_key=idempotency_key,
        client_id=client_id, object_id=object_id, service_id=service_id,
        roadmap_id=roadmap_id, stage_id=stage_id,
        created_by=created_by, gtd_action_id=gtd_action_id,
    )
    if not write_result["ok"]:
        return _task_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            business_id=business_id, retry_safe=bool(idempotency_key),
        )

    return _task_result(
        ok=True, code="TASK_CREATED", error=None,
        task_id=write_result["task_id"], business_id=business_id,
        task_created=True, final_status="new", retry_safe=True,
    )


def update_task_admin_fields(task_id: str, updates: dict) -> dict:
    """
    Phase 36C (ADR-019 §12/§24): the sole canonical Task admin-field
    update orchestration boundary. Approved mutable fields: Title,
    Description, Priority, Due Date, Created By, GTD Action ID.
    Immutable identity, relation fields, assignment cache fields, and
    Status are all rejected before any write — enforced by
    task_manager.update_task_admin_fields() itself (this function is a
    thin resolve-then-delegate wrapper, since the low-level function
    already carries the full field-classification policy).
    """
    from business_core.task_manager import find_task_by_id, update_task_admin_fields as _low_level_update

    if not task_id:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error="task_id обязателен")

    task = find_task_by_id(task_id)
    if task is None:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error=f"Task {task_id} не найден", task_id=task_id)

    result = _low_level_update(task_id, updates)
    return _task_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        task_id=task_id, business_id=task.get("business_id", ""),
        changed=result.get("changed", False), retry_safe=True,
    )


def _task_roadmap_eligibility_code_for_transition(roadmap_status: str, target_status: str) -> str | None:
    """
    ADR-019 §14/§20: on_hold blocks only the in_progress *transition*,
    not admin edits or other statuses — mirrors ADR-017 §7's Stage
    on_hold behavior exactly. completed/cancelled block every ordinary
    execution transition.
    """
    if roadmap_status == "completed":
        return "ROADMAP_COMPLETED"
    if roadmap_status == "cancelled":
        return "ROADMAP_CANCELLED"
    if roadmap_status == "on_hold" and target_status == "in_progress":
        return "ROADMAP_ON_HOLD"
    return None


def transition_task_status(task_id: str, target_status: str) -> dict:
    """
    Phase 36C (ADR-019 §13/§15/§20): the sole canonical Task-transition
    orchestration boundary.

    Validation order, all before any write:
      A. required task_id
      B. Task exists (TASK_NOT_FOUND)
      C. target status validation (INVALID_TASK_STATUS)
      D. linked Roadmap eligibility, only if Roadmap ID is present
         (ROADMAP_ON_HOLD only for the in_progress target;
         ROADMAP_COMPLETED/ROADMAP_CANCELLED for any execution
         transition)
      E. terminal-state reopen gate (TASK_REOPEN_REQUIRES_EXPLICIT_ACTION
         for an ordinary attempt to leave done/cancelled/skipped)
      F. ordinary transition-matrix validation (INVALID_TASK_TRANSITION)
      G. persist Status (+ Started At/Completed At/Cancelled At timestamp,
         set-once — ADR-019 §16)
      H. structured result

    No Stage or Roadmap mutation ever happens here (ADR-019 §14/§20).
    """
    from business_core.task_manager import find_task_by_id, update_task_status, TASK_STATUS

    if not task_id:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error="task_id обязателен")

    task = find_task_by_id(task_id)
    if task is None:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error=f"Task {task_id} не найден", task_id=task_id)

    business_id = task.get("business_id", "")
    previous_status = task.get("status", "")

    if target_status not in TASK_STATUS:
        return _task_result(
            ok=False, code="INVALID_TASK_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(TASK_STATUS)}",
            task_id=task_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    roadmap_id = task.get("roadmap_id", "")
    if roadmap_id:
        from business_core.roadmap_manager import find_roadmap_by_id, normalize_roadmap_status
        roadmap = find_roadmap_by_id(roadmap_id)
        if roadmap is not None:
            roadmap_status = normalize_roadmap_status(roadmap.get("status", ""))
            eligibility_code = _task_roadmap_eligibility_code_for_transition(roadmap_status, target_status)
            if eligibility_code:
                return _task_result(
                    ok=False, code=eligibility_code,
                    error=f"Roadmap {roadmap_id} имеет статус '{roadmap_status}' — переход не разрешён",
                    task_id=task_id, business_id=business_id,
                    previous_status=previous_status, requested_status=target_status, final_status=previous_status,
                )

    if previous_status in _TASK_REOPEN_GATED_STATUSES and target_status != previous_status:
        return _task_result(
            ok=False, code="TASK_REOPEN_REQUIRES_EXPLICIT_ACTION",
            error=(
                f"Task {task_id} имеет статус '{previous_status}' — обычное обновление не может "
                f"вернуть его в '{target_status}'. Требуется отдельное явное действие reopen (не реализовано)."
            ),
            task_id=task_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    allowed_targets = _TASK_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _task_result(
            ok=False, code="INVALID_TASK_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            task_id=task_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    timestamp_field = ""
    if target_status == "in_progress" and not task.get("started_at", ""):
        timestamp_field = "Started At"
    elif target_status == "done":
        timestamp_field = "Completed At"
    elif target_status == "cancelled":
        timestamp_field = "Cancelled At"

    write_result = update_task_status(task_id, target_status, timestamp_field=timestamp_field)
    if not write_result["ok"]:
        return _task_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            task_id=task_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _task_result(
        ok=True, code="TASK_STATUS_UPDATED" if changed else "TASK_STATUS_UNCHANGED", error=None,
        task_id=task_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status,
        final_status=target_status, changed=changed,
    )


def _task_role_eligible_for_assignment(role: dict) -> tuple[bool, str, str]:
    """
    ADR-019 §18: Role eligibility for Task assignment. active is fully
    eligible; planned is eligible ONLY as a Role-only future
    responsibility (never as an active executor — enforced separately
    in assign_task() when a Person is also supplied); paused/archived
    are blocked outright. Parent Department must exist and not be
    archived. Returns (eligible, code, error) — code is "" when eligible.
    """
    status = role.get("status", "")
    if status == "paused":
        return False, "ROLE_PAUSED", f"Role {role['role_id']} приостановлена — назначение не разрешено"
    if status == "archived":
        return False, "ROLE_ARCHIVED", f"Role {role['role_id']} архивирована — назначение не разрешено"
    if status not in ("planned", "active"):
        return False, "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION", f"Role {role['role_id']} имеет неизвестный статус '{status}'"

    from business_core.organization_manager import find_department_by_id
    department = find_department_by_id(role.get("department_id", ""))
    if department is None:
        return False, "DEPARTMENT_NOT_FOUND", f"Department {role.get('department_id', '')} не найден"
    if department.get("status") == "archived":
        return False, "DEPARTMENT_ARCHIVED", f"Department {role.get('department_id', '')} архивирован"

    return True, "", ""


def assign_task(
    task_id: str,
    responsible_role_id: str = "",
    assignee_person_id: str = "",
    start_date: str = "",
    assignment_type: str = "primary",
) -> dict:
    """
    Phase 36C (ADR-019 §17-20): the sole canonical Task assignment
    orchestration boundary — Task resolution, Role/Person eligibility
    (reusing Organization Domain guarantees, never a second eligibility
    system), current active Task Assignment invariant, and Task
    assignment-cache update, all in one deterministic pass, no write
    before all validation passes.

    Requires at least one of responsible_role_id/assignee_person_id —
    use unassign_task() to remove an existing assignment.
    """
    from business_core.task_manager import (
        find_task_by_id, list_task_assignments_for_task, create_task_assignment,
        end_task_assignment, update_task_assignment_cache,
    )
    from datetime import datetime

    if not task_id:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error="task_id обязателен")

    task = find_task_by_id(task_id)
    if task is None:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error=f"Task {task_id} не найден", task_id=task_id)

    business_id = task.get("business_id", "")

    if not responsible_role_id and not assignee_person_id:
        return _task_result(
            ok=False, code="", error="Требуется хотя бы одно из responsible_role_id/assignee_person_id",
            task_id=task_id, business_id=business_id,
        )

    role = None
    if responsible_role_id:
        from business_core.organization_manager import find_role_by_id
        role = find_role_by_id(responsible_role_id)
        if role is None:
            return _task_result(ok=False, code="ROLE_NOT_FOUND", error=f"Role {responsible_role_id} не найден", task_id=task_id, business_id=business_id)

        eligible, code, error = _task_role_eligible_for_assignment(role)
        if not eligible:
            return _task_result(ok=False, code=code, error=error, task_id=task_id, business_id=business_id)

    if assignee_person_id:
        from business_core.person_manager import find_person_by_id, is_person_archived, has_person_business_link

        person = find_person_by_id(assignee_person_id)
        if person is None:
            return _task_result(ok=False, code="PERSON_NOT_FOUND", error=f"Person {assignee_person_id} не найден", task_id=task_id, business_id=business_id)
        if is_person_archived(person):
            return _task_result(
                ok=False, code="PERSON_ARCHIVED",
                error=f"Person {assignee_person_id} архивирован — назначение не разрешено",
                task_id=task_id, business_id=business_id,
            )

        # A Person assigned as active executor requires an ACTIVE Role
        # when a Role is also supplied — planned Role is Role-only
        # (ADR-019 §11/§18).
        if role is not None and role.get("status", "") == "planned":
            return _task_result(
                ok=False, code="ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION",
                error=f"Role {responsible_role_id} ещё planned — Person не может быть назначен как активный исполнитель",
                task_id=task_id, business_id=business_id,
            )

        business_scope_id = role.get("department_id", "") if role is not None else ""
        department_business_id = ""
        if role is not None:
            from business_core.organization_manager import find_department_by_id
            department = find_department_by_id(role.get("department_id", ""))
            department_business_id = department.get("business_id", "") if department else ""
        else:
            department_business_id = business_id

        if department_business_id:
            if not has_person_business_link(person, department_business_id):
                linked_ids = person.get("biz_ids") or []
                if not linked_ids:
                    return _task_result(
                        ok=False, code="PERSON_NOT_LINKED_TO_BUSINESS",
                        error=f"Person {assignee_person_id} не привязан к бизнесу {department_business_id}",
                        task_id=task_id, business_id=business_id,
                    )
                return _task_result(
                    ok=False, code="PERSON_TASK_BUSINESS_MISMATCH",
                    error=f"Person {assignee_person_id} привязан к другому бизнесу, а не к {department_business_id}",
                    task_id=task_id, business_id=business_id,
                )

    # Current active Task Assignment invariant (ADR-019 §20).
    active_assignments = list_task_assignments_for_task(task_id, status="active")
    if len(active_assignments) > 1:
        conflicting_ids = tuple(a.get("task_assignment_id", "") for a in active_assignments)
        return _task_result(
            ok=False, code="MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
            error=f"Найдено {len(active_assignments)} активных Task Assignment для {task_id}: {conflicting_ids}",
            task_id=task_id, business_id=business_id,
            conflicting_assignment_ids=conflicting_ids, retry_safe=True,
        )

    current = active_assignments[0] if active_assignments else None

    if current is not None and current.get("responsible_role_id", "") == responsible_role_id and current.get("assignee_person_id", "") == assignee_person_id:
        return _task_result(
            ok=True, code="TASK_ASSIGNMENT_REUSED", error=None,
            task_id=task_id, business_id=business_id,
            assignment_id=current.get("task_assignment_id", ""), retry_safe=True,
        )

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")

    previous_assignment_id = current.get("task_assignment_id", "") if current is not None else ""
    if current is not None:
        end_result = end_task_assignment(previous_assignment_id)
        if not end_result["ok"]:
            return _task_result(
                ok=False, code="", error=end_result.get("error"),
                task_id=task_id, business_id=business_id,
                previous_assignment_id=previous_assignment_id, retry_safe=True,
            )

    write_result = create_task_assignment(task_id, responsible_role_id, assignee_person_id, start_date, assignment_type=assignment_type)
    if not write_result["ok"]:
        return _task_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            task_id=task_id, business_id=business_id,
            previous_assignment_id=previous_assignment_id, retry_safe=True,
        )

    cache_result = update_task_assignment_cache(task_id, responsible_role_id, assignee_person_id)

    return _task_result(
        ok=True, code="TASK_ASSIGNMENT_CREATED" if current is None else "TASK_REASSIGNED", error=None,
        task_id=task_id, business_id=business_id,
        assignment_changed=cache_result.get("changed", False),
        assignment_id=write_result["task_assignment_id"], previous_assignment_id=previous_assignment_id,
        retry_safe=True,
    )


def unassign_task(task_id: str) -> dict:
    """
    Phase 36C (ADR-019 §21): the sole canonical Task-unassignment
    orchestration boundary. Ends the current active Task Assignment (if
    any) and clears the Task's assignment cache. Zero active rows is a
    no-op success — unassigning an already-unassigned Task is
    idempotent, not an error.
    """
    from business_core.task_manager import (
        find_task_by_id, list_task_assignments_for_task, end_task_assignment, update_task_assignment_cache,
    )

    if not task_id:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error="task_id обязателен")

    task = find_task_by_id(task_id)
    if task is None:
        return _task_result(ok=False, code="TASK_NOT_FOUND", error=f"Task {task_id} не найден", task_id=task_id)

    business_id = task.get("business_id", "")

    active_assignments = list_task_assignments_for_task(task_id, status="active")
    if len(active_assignments) > 1:
        conflicting_ids = tuple(a.get("task_assignment_id", "") for a in active_assignments)
        return _task_result(
            ok=False, code="MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
            error=f"Найдено {len(active_assignments)} активных Task Assignment для {task_id}: {conflicting_ids}",
            task_id=task_id, business_id=business_id,
            conflicting_assignment_ids=conflicting_ids, retry_safe=True,
        )

    if not active_assignments:
        return _task_result(ok=True, code="TASK_UNASSIGNED", error=None, task_id=task_id, business_id=business_id, retry_safe=True)

    current = active_assignments[0]
    end_result = end_task_assignment(current.get("task_assignment_id", ""))
    if not end_result["ok"]:
        return _task_result(
            ok=False, code="", error=end_result.get("error"),
            task_id=task_id, business_id=business_id,
            previous_assignment_id=current.get("task_assignment_id", ""), retry_safe=True,
        )

    cache_result = update_task_assignment_cache(task_id, "", "")

    return _task_result(
        ok=True, code="TASK_UNASSIGNED", error=None,
        task_id=task_id, business_id=business_id,
        assignment_changed=cache_result.get("changed", False),
        previous_assignment_id=current.get("task_assignment_id", ""), retry_safe=True,
    )


def task_assignment_cache_is_consistent(task_id: str) -> dict:
    """
    Read-only consistency helper (ADR-019 §22): compares a Task's
    cache fields (Responsible Role ID/Assignee Person ID) against the
    current active Task Assignment row (the sole source of truth).
    Never repairs a mismatch automatically — reporting/detection only.
    """
    from business_core.task_manager import find_task_by_id, list_task_assignments_for_task

    task = find_task_by_id(task_id)
    if task is None:
        return {"ok": False, "consistent": False, "error": f"Task {task_id} не найден"}

    active_assignments = list_task_assignments_for_task(task_id, status="active")
    if len(active_assignments) > 1:
        return {"ok": True, "consistent": False, "error": "multiple active Task Assignments"}

    expected_role = active_assignments[0].get("responsible_role_id", "") if active_assignments else ""
    expected_person = active_assignments[0].get("assignee_person_id", "") if active_assignments else ""

    consistent = (
        task.get("responsible_role_id", "") == expected_role
        and task.get("assignee_person_id", "") == expected_person
    )
    return {"ok": True, "consistent": consistent, "error": None}


# ─────────────────────────────────────────────────────────────
# Phase 37D (ADR-020): Document Domain Foundation — the sole
# cross-domain Document orchestration boundary. document_manager.py
# remains the persistence-only owner of DOCUMENT_REGISTRY (mirrors
# task_manager.py's role exactly — ADR-019 precedent). Everything that
# crosses from "one Document" to cross-entity eligibility — Business/
# Client/Object/Roadmap/Stage/Template existence and consistency, Drive
# upload sequencing and compensation, Drive-File-ID reuse policy,
# lifecycle transitions — lives here instead, the same boundary
# principle ADR-016/017/018/019 already applied elsewhere. No second
# implementation of this policy exists anywhere else (see
# test_document_architecture_guards.py).
# ─────────────────────────────────────────────────────────────

_DOCUMENT_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "uploaded":     ("uploaded", "under_review", "archived", "superseded"),
    "under_review": ("under_review", "approved", "rejected", "uploaded", "archived", "superseded"),
    "approved":     ("approved", "archived", "superseded"),
    "rejected":     ("rejected", "under_review", "uploaded", "archived", "superseded"),
    "superseded":   ("superseded",),
    "archived":     ("archived",),
}

_DOCUMENT_REOPEN_GATED_STATUSES = frozenset({"superseded", "archived"})


def _document_result(
    *, ok: bool, code: str, error: str | None,
    document_id: str = "", document_family_id: str = "", version: str = "",
    business_id: str = "", drive_file_id: str = "", drive_file_url: str = "",
    document_template_id: str = "", client_id: str = "", object_id: str = "",
    roadmap_id: str = "", stage_id: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False, uploaded: bool = False,
    compensation_attempted: bool = False, compensation_succeeded: bool = False,
    analysis_status: str = "", warnings: tuple = (), conflicting_document_ids: tuple = (),
    retry_safe: bool = True,
    # Phase 16C.9C: Document Archive — optional, empty-default so every
    # existing caller's output is byte-identical to before this change.
    document_name: str = "", archived_at: str = "", archived_by: str = "", archive_reason: str = "",
) -> dict:
    """Shared result-builder for every Document orchestration function
    (ADR-020 §21/§8 of business_builder.py's design) — the stable,
    structured contract every caller reads instead of a bare exception
    or ad-hoc dict shape. Never carries a raw exception object."""
    return {
        "ok": ok, "code": code, "error": error,
        "document_id": document_id, "document_family_id": document_family_id, "version": version,
        "business_id": business_id, "drive_file_id": drive_file_id, "drive_file_url": drive_file_url,
        "document_template_id": document_template_id, "client_id": client_id, "object_id": object_id,
        "roadmap_id": roadmap_id, "stage_id": stage_id,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed, "uploaded": uploaded,
        "compensation_attempted": compensation_attempted, "compensation_succeeded": compensation_succeeded,
        "analysis_status": analysis_status, "warnings": tuple(warnings),
        "conflicting_document_ids": tuple(conflicting_document_ids), "retry_safe": retry_safe,
        "document_name": document_name, "archived_at": archived_at,
        "archived_by": archived_by, "archive_reason": archive_reason,
    }


def _validate_document_relations(
    business_id: str, client_id: str = "", object_id: str = "",
    roadmap_id: str = "", stage_id: str = "", document_template_id: str = "",
) -> dict:
    """
    ADR-020 §9: canonical cross-domain Document relation-validation
    path, all before any write. Validation order (all before any
    write):
      A. required business_id
      B. Business exists
      D. normalize optional references
      E-I. validate Client/Object/Roadmap/Stage/Template, most-specific-
           first, deriving broader references from more-specific ones
      J/K. cross-check all supplied/derived references for contradictions
      L. return normalized canonical relation set

    Reuses business_core.document_registry_manager.resolve_and_validate_links()
    — the existing, production-proven cross-entity validator (Phase
    15A) — rather than re-implementing the same chain a second time.
    (Document Name requirement (C) is checked separately by the caller,
    since it isn't a relation.)

    Returns:
        {"ok": bool, "code": str, "error": str | None, "resolved": dict | None}
    """
    from business_core.document_registry_manager import resolve_and_validate_links

    if not business_id:
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен", "resolved": None}

    # B. Business existence is checked inside resolve_and_validate_links()
    # itself (against biz_registry via read_business_sheet) — not
    # duplicated here with a second primitive, which would risk the
    # exact two-implementations-of-one-check drift this ADR exists to
    # close elsewhere.
    result = resolve_and_validate_links(
        business_id=business_id, client_id=client_id, object_id=object_id,
        roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
    )
    if not result["ok"]:
        code = "BUSINESS_NOT_FOUND" if result["error"] == f"Business {business_id} не найден." else "DOCUMENT_ENTITY_RELATION_MISMATCH"
        return {"ok": False, "code": code, "error": result["error"], "resolved": None}

    return {"ok": True, "code": "", "error": None, "resolved": result["resolved"]}


def register_document(
    business_id: str,
    document_name: str,
    drive_file_id: str,
    *,
    file_name: str = "",
    mime_type: str = "",
    drive_file_url: str = "",
    client_id: str = "",
    object_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    document_template_id: str = "",
    uploaded_by: str = "",
    notes: str = "",
) -> dict:
    """
    Phase 37D (ADR-020 §10): the sole canonical register-existing-file
    orchestration boundary — Mode A of the one canonical creation
    model. Callers must supply already-read authoritative Drive
    metadata (file_name/mime_type/drive_file_url) — this function does
    not itself call the Drive adapter, so it stays testable without any
    live Drive dependency; the Telegram caller is responsible for
    reading Drive metadata before calling this.

    Validation order, all before any write:
      A. required business_id / Document Name
      B. relation validation (_validate_document_relations)
      C. Drive File ID reuse lookup (zero/one/multiple policy)
      D. Document ID/Family ID generation only after A-C pass
      E. low-level persistence
      F. post-write verification
      G. structured result
    """
    from business_core.document_manager import find_documents_by_drive_file_id, find_document_by_id, create_document

    if not business_id:
        return _document_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not document_name:
        return _document_result(ok=False, code="", error="document_name обязателен", business_id=business_id)

    relation_result = _validate_document_relations(
        business_id, client_id=client_id, object_id=object_id,
        roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
    )
    if not relation_result["ok"]:
        return _document_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id)
    resolved = relation_result["resolved"]

    # Drive File ID reuse policy (ADR-020 §10).
    if drive_file_id:
        matches = find_documents_by_drive_file_id(drive_file_id)
        if len(matches) > 1:
            conflicting_ids = tuple(m["document_id"] for m in matches)
            return _document_result(
                ok=False, code="MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES",
                error=f"Найдено несколько Document с Drive File ID {drive_file_id}: {conflicting_ids}",
                business_id=business_id, drive_file_id=drive_file_id,
                conflicting_document_ids=conflicting_ids, retry_safe=True,
            )
        if len(matches) == 1:
            existing = matches[0]
            compatible = (
                existing["business_id"] == resolved["business_id"]
                and (not resolved["client_id"] or existing["client_id"] == resolved["client_id"])
                and (not resolved["object_id"] or existing["object_id"] == resolved["object_id"])
                and (not resolved["roadmap_id"] or existing["roadmap_id"] == resolved["roadmap_id"])
                and (not resolved["stage_id"] or existing["stage_id"] == resolved["stage_id"])
            )
            if not compatible:
                return _document_result(
                    ok=False, code="DOCUMENT_RELATION_CONFLICT_ON_REUSE",
                    error=f"Document {existing['document_id']} с этим Drive File ID уже существует с другими связями",
                    business_id=business_id, drive_file_id=drive_file_id, document_id=existing["document_id"],
                )
            return _document_result(
                ok=True, code="DOCUMENT_REUSED", error=None,
                document_id=existing["document_id"], document_family_id=existing["document_family_id"],
                version=existing["version"], business_id=business_id, drive_file_id=drive_file_id,
                reused=True, final_status=existing["status"], retry_safe=True,
            )

    write_result = create_document(
        business_id, document_name,
        client_id=resolved["client_id"], object_id=resolved["object_id"],
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        document_template_id=resolved["document_template_id"],
        drive_file_id=drive_file_id, drive_file_url=drive_file_url,
        file_name=file_name, mime_type=mime_type, uploaded_by=uploaded_by, notes=notes,
    )
    if not write_result["ok"]:
        return _document_result(
            ok=False, code="DOCUMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            business_id=business_id, retry_safe=True,
        )

    document_id = write_result["document_id"]
    saved = find_document_by_id(document_id)
    if saved is None:
        return _document_result(
            ok=False, code="DOCUMENT_POST_WRITE_VERIFICATION_FAILED",
            error="Документ записан, но не удалось перечитать его для подтверждения",
            document_id=document_id, business_id=business_id, retry_safe=False,
        )

    # Post-write verification (ADR-020 §8): never claim success on a
    # field mismatch between what was submitted and what was actually
    # persisted, even if the row itself was found — a missing row or a
    # mismatched row both mean "manual verification required", never a
    # second automatic write/upload.
    expected = {
        "business_id": business_id, "client_id": resolved["client_id"], "object_id": resolved["object_id"],
        "roadmap_id": resolved["roadmap_id"], "stage_id": resolved["stage_id"],
        "document_template_id": resolved["document_template_id"], "document_name": document_name,
        "status": "uploaded", "drive_file_id": drive_file_id, "drive_file_url": drive_file_url,
        "file_name": file_name, "mime_type": mime_type,
    }
    mismatches = {k: {"expected": v, "actual": saved.get(k)} for k, v in expected.items() if saved.get(k) != v}
    if mismatches:
        log.error(f"register_document({document_id}) post-write verification mismatch: {mismatches}")
        return _document_result(
            ok=False, code="DOCUMENT_POST_WRITE_VERIFICATION_FAILED",
            error="Документ записан, но проверка после записи не прошла (расхождение полей)",
            document_id=document_id, business_id=business_id, retry_safe=False,
        )

    return _document_result(
        ok=True, code="DOCUMENT_REGISTERED", error=None,
        document_id=saved["document_id"], document_family_id=saved["document_family_id"], version=saved["version"],
        business_id=business_id, drive_file_id=drive_file_id, drive_file_url=drive_file_url,
        document_template_id=resolved["document_template_id"], client_id=resolved["client_id"],
        object_id=resolved["object_id"], roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        created=True, final_status="uploaded", retry_safe=True,
    )


def upload_and_register_document(
    business_id: str,
    document_name: str,
    drive_file_id: str,
    file_name: str,
    mime_type: str,
    drive_file_url: str,
    *,
    client_id: str = "",
    object_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    document_template_id: str = "",
    uploaded_by: str = "",
    notes: str = "",
) -> dict:
    """
    Phase 37D (ADR-020 §11): the canonical persistence-and-compensation
    half of Mode B (Telegram-file upload). The actual Drive upload and
    Telegram file download stay in telegram_handlers.py (both require
    `await`, which this synchronous function cannot do) — the caller
    must call the Drive adapter itself, obtain authoritative Drive
    metadata, and pass it in here already-uploaded. This function then
    owns the Drive-File-ID reuse check, low-level persistence, post-
    write verification, and (via its return code) tells the caller
    whether Drive-side compensation (trashing the just-uploaded file)
    is needed — the actual trash call stays in telegram_handlers.py
    since it also requires `await`.

    This intentionally reuses register_document()'s exact reuse/
    creation/verification logic — Mode A and Mode B converge on the
    same low-level creation model (ADR-020 §7/§13), the only difference
    being who performed the Drive upload before calling in.
    """
    result = register_document(
        business_id, document_name, drive_file_id,
        file_name=file_name, mime_type=mime_type, drive_file_url=drive_file_url,
        client_id=client_id, object_id=object_id, roadmap_id=roadmap_id, stage_id=stage_id,
        document_template_id=document_template_id, uploaded_by=uploaded_by, notes=notes,
    )
    if result["code"] == "DOCUMENT_REGISTERED":
        return _document_result(
            ok=True, code="DOCUMENT_UPLOADED", error=None,
            document_id=result["document_id"], document_family_id=result["document_family_id"], version=result["version"],
            business_id=business_id, drive_file_id=drive_file_id, drive_file_url=drive_file_url,
            document_template_id=result["document_template_id"], client_id=result["client_id"],
            object_id=result["object_id"], roadmap_id=result["roadmap_id"], stage_id=result["stage_id"],
            created=True, uploaded=True, final_status="uploaded", retry_safe=True,
        )
    if result["code"] == "DOCUMENT_POST_WRITE_VERIFICATION_FAILED":
        return _document_result(
            ok=False, code="DOCUMENT_POST_WRITE_VERIFICATION_FAILED", error=result["error"],
            document_id=result["document_id"], business_id=business_id, drive_file_id=drive_file_id,
            uploaded=True, retry_safe=False,
        )
    if result["code"] == "DOCUMENT_PERSISTENCE_FAILED":
        # Caller (telegram_handlers.py) is responsible for attempting
        # Drive compensation and reporting DRIVE_UPLOAD_COMPENSATED /
        # DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING based
        # on whether that compensation succeeds — this function cannot
        # itself await the Drive trash call.
        return _document_result(
            ok=False, code="DOCUMENT_PERSISTENCE_FAILED", error=result["error"],
            business_id=business_id, drive_file_id=drive_file_id, uploaded=True,
            compensation_attempted=False, retry_safe=True,
        )
    return result


def update_document_admin_fields(document_id: str, updates: dict) -> dict:
    """
    Phase 37D (ADR-020 §14/§20): the sole canonical Document admin-field
    update orchestration boundary. Approved mutable fields: Document
    Name, Notes. Immutable identity, version/family, relation, Drive/
    upload-metadata, Status, and review fields are all rejected before
    any write — enforced by document_manager.update_document_admin_fields()
    itself (this function is a thin resolve-then-delegate wrapper).
    """
    from business_core.document_manager import find_document_by_id, update_document_admin_fields as _low_level_update

    if not document_id:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error="document_id обязателен")

    document = find_document_by_id(document_id)
    if document is None:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error=f"Document {document_id} не найден", document_id=document_id)

    result = _low_level_update(document_id, updates)
    if not isinstance(result, dict):
        result = {}
    return _document_result(
        ok=result.get("ok") is True, code=result.get("code") or "", error=result.get("error"),
        document_id=document_id, business_id=document.get("business_id", ""),
        changed=result.get("changed") is True, retry_safe=True,
    )


def relink_document(
    document_id: str, *,
    roadmap_id: str | None = None, stage_id: str | None = None,
    document_template_id: str | None = None, dry_run: bool = False,
) -> dict:
    """
    The sole canonical Document relation-relink orchestration boundary
    — deliberately narrow: only Roadmap ID, Stage ID and Document
    Template ID may ever be changed through this function (audit
    finding: Object ID relink carries an unresolved physical-Drive-
    folder-move risk; Business ID is Document identity, never
    relinkable; Client ID is left untouched alongside Object ID for
    this same reason. Document Template ID carries no such risk — it
    is a pure classification field with no Drive-path implication —
    which is why it, unlike Object ID/Client ID, is a caller-suppliable
    parameter here rather than a fixed anchor).

    Business ID/Client ID/Object ID are always read from the document's
    own existing row and passed to relation validation as fixed anchors
    — never accepted as parameters here — so a new Roadmap/Stage that
    would imply a different Object or Client is caught as a
    contradiction by resolve_and_validate_links() exactly like any
    other cross-entity mismatch, not silently allowed.

    A value of None for roadmap_id/stage_id/document_template_id means
    "keep the document's current value" — passing "" explicitly would
    mean "clear it"; this is mechanically possible (identical to how
    roadmap_id/stage_id already behave) but is not a dedicated,
    supported, or tested feature of this function in this iteration.

    dry_run=True validates the requested relink fully (existence +
    Stage->Roadmap->Object->Client->Business consistency, plus Document
    Template existence/Business-ownership) and returns what WOULD
    change, without writing anything — used for the /updatedoc preview
    step, so the preview and the actual apply share exactly one
    validation path, never two.

    Validation order, all before any write:
      A. required document_id
      B. Document exists (DOCUMENT_NOT_FOUND)
      C. relation validation via the existing resolve_and_validate_links()
         (reused via _validate_document_relations()) — Business/Client/
         Object anchored from the document's own row, Document Template
         ID taken from the caller (or the document's current value if
         not supplied)
      D. (dry_run only) return preview, no write
      E. low-level persistence (Roadmap ID/Stage ID/Document Template ID)
      F. structured result

    Returns:
        See _document_result() for the full field list. roadmap_id/
        stage_id/document_template_id in the result are always the NEW
        (resolved) values; the caller already has the OLD values from
        find_document_by_id() for rendering a before/after preview.
    """
    from business_core.document_manager import find_document_by_id, update_document_relations

    if not document_id:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error="document_id обязателен")

    document = find_document_by_id(document_id)
    if document is None:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error=f"Document {document_id} не найден", document_id=document_id)

    business_id = document.get("business_id", "")
    client_id = document.get("client_id", "")
    object_id = document.get("object_id", "")
    current_document_template_id = document.get("document_template_id", "")
    current_roadmap_id = document.get("roadmap_id", "")
    current_stage_id = document.get("stage_id", "")

    target_roadmap_id = current_roadmap_id if roadmap_id is None else roadmap_id
    target_stage_id = current_stage_id if stage_id is None else stage_id
    target_document_template_id = (
        current_document_template_id if document_template_id is None else document_template_id
    )

    relation_result = _validate_document_relations(
        business_id, client_id=client_id, object_id=object_id,
        roadmap_id=target_roadmap_id, stage_id=target_stage_id,
        document_template_id=target_document_template_id,
    )
    if not relation_result["ok"]:
        return _document_result(
            ok=False, code=relation_result["code"], error=relation_result["error"],
            document_id=document_id, business_id=business_id,
            roadmap_id=current_roadmap_id, stage_id=current_stage_id,
            document_template_id=current_document_template_id,
        )
    resolved = relation_result["resolved"]

    if dry_run:
        return _document_result(
            ok=True, code="DOCUMENT_RELINK_PREVIEW", error=None,
            document_id=document_id, business_id=business_id,
            roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
            document_template_id=resolved["document_template_id"],
        )

    write_result = update_document_relations(document_id, {
        "Roadmap ID": resolved["roadmap_id"], "Stage ID": resolved["stage_id"],
        "Document Template ID": resolved["document_template_id"],
    })
    if not write_result["ok"]:
        return _document_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            document_id=document_id, business_id=business_id,
            roadmap_id=current_roadmap_id, stage_id=current_stage_id,
            document_template_id=current_document_template_id,
        )

    changed = write_result["changed"]
    return _document_result(
        ok=True, code="DOCUMENT_RELATION_UPDATED" if changed else "DOCUMENT_RELATION_UNCHANGED", error=None,
        document_id=document_id, business_id=business_id,
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        document_template_id=resolved["document_template_id"], changed=changed,
    )


def sync_stage_document_requirements(stage_id: str, dry_run: bool = True) -> dict:
    """
    The sole canonical orchestration boundary for retroactively syncing
    document_template requirements from a Template Stage into an
    already-created Roadmap Stage — /syncstageknowledge's backing
    function. Built for the case where a document_template requirement
    was added to a Template Stage AFTER the real Stage had already been
    instantiated from it, so business_builder.create_roadmap_for_object()'s
    one-time, creation-time copy never saw it.

    Dual-source (live-audit fix, added after a production mismatch):
    /linkknowledge and /stageknowledge both read/write the legacy
    ROADMAP_TEMPLATE_STAGES."Document Template IDs" comma-list column
    (via roadmap_template_manager.update_template_stage_knowledge_ids()/
    knowledge_manager.find_knowledge_by_template_stage()) — they never
    touch STAGE_ENTITY_RELATIONS at all. This function must therefore
    accept knowledge from EITHER source:
      1. If the Template Stage has active STAGE_ENTITY_RELATIONS rows
         (Entity Type "document_template"), those are used — copied via
         the existing copy_template_relations_to_stage() — exactly as
         before this fix, unchanged.
      2. Otherwise, if the Template Stage's legacy "Document Template
         IDs" column (read via resolve_template_stage_for_stage()'s
         template_stage_row) has entries, each ID is validated (existence
         in DOCUMENT_TEMPLATE_REGISTRY, via the existing
         validate_relation_references()) and instance-scoped relations
         are created for them via the new
         create_document_template_relations_for_stage() — the legacy-
         column counterpart to copy_template_relations_to_stage(), same
         idempotent/all-or-nothing contract.
      3. If both sources are empty, NO_DOCUMENT_TEMPLATE_RELATIONS.
    The result always reports which source was used ("relations" or
    "legacy") so the preview never hides this from the caller.

    /linkknowledge's own behavior is deliberately UNCHANGED by this fix
    — it still only writes the legacy column. Migrating it onto
    STAGE_ENTITY_RELATIONS is a separate, not-yet-approved decision.

    Deliberately narrow to Entity Type "document_template" — SOP/
    Checklist/Materials/FAQ IDs are a structurally different storage
    layer (comma-list columns written once on ROADMAP_STAGES at
    creation time) and are out of scope for this function; it never
    reads or writes them. If the resolved Template Stage's
    STAGE_ENTITY_RELATIONS also carry an active relation of any OTHER
    Entity Type (e.g. "role") alongside document_template ones, this
    function refuses rather than silently letting
    copy_template_relations_to_stage() (which is itself deliberately
    generic over Entity Type) copy something wider than requested.

    Never writes ROADMAP_STAGES."Document Template IDs" (the legacy
    comma-list column lives on ROADMAP_TEMPLATE_STAGES, not
    ROADMAP_STAGES, and is never written here either way) and never
    writes Status/Responsible/Due Date/Priority/Progress — this
    function only ever calls stage_entity_relations functions, which
    read/write STAGE_ENTITY_RELATIONS exclusively and never touch
    ROADMAP_STAGES at all.

    dry_run=True (the default, used for /syncstageknowledge's preview
    step) performs every read/resolution/validation step and returns
    what WOULD be added, without writing anything.

    Idempotent: relies entirely on copy_template_relations_to_stage()'s
    / create_document_template_relations_for_stage()'s own existing
    duplicate-detection (find_active_duplicate_relation()) — calling
    this twice never creates a second active relation row for the same
    (Stage ID, Entity Type, Entity ID).

    Validation/resolution order, all before any write:
      A. required stage_id
      B. Stage exists (STAGE_NOT_FOUND)
      C. Stage's Roadmap exists (ROADMAP_NOT_FOUND)
      D. Roadmap has a resolvable Template ID (ROADMAP_HAS_NO_TEMPLATE)
      E. a Template Stage with matching Order exists (TEMPLATE_STAGE_NOT_FOUND)
      F. STAGE_ENTITY_RELATIONS source: active document_template
         relations on the Template Stage, if any (source="relations")
      G. else legacy source: ROADMAP_TEMPLATE_STAGES."Document Template
         IDs" on the Template Stage, if any (source="legacy")
      H. if neither source has anything: NO_DOCUMENT_TEMPLATE_RELATIONS
      I. (relations source only) no active relation of another Entity
         Type on the Template Stage (UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE)
      J. (legacy source only) every legacy ID validated
         (INVALID_LEGACY_DOCUMENT_TEMPLATE_ID)
      K. (dry_run only) return preview, no write
      L. copy_template_relations_to_stage() or
         create_document_template_relations_for_stage(), matching the source
      M. structured result

    Returns:
        {
            "ok": bool, "code": str, "error": str | None,
            "stage_id": str, "template_stage_id": str, "source": str,
            "to_add": tuple[str, ...],          # Document Template IDs not yet linked to this Stage
            "already_present": tuple[str, ...], # Document Template IDs already linked to this Stage
            "created": tuple[str, ...],         # actually created (dry_run=False only; always () on preview)
        }
        source is "" until a source is chosen, else "relations" or "legacy".
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage
    from business_core.stage_entity_relations import (
        get_relations_for_template_stage, get_relations_for_stage,
        copy_template_relations_to_stage, create_document_template_relations_for_stage,
        validate_relation_references,
    )

    empty = {
        "stage_id": stage_id, "template_stage_id": "", "source": "",
        "to_add": (), "already_present": (), "created": (),
    }

    resolved = resolve_template_stage_for_stage(stage_id)
    if not resolved["ok"]:
        return {"ok": False, "code": resolved["code"], "error": resolved["error"], **empty}

    template_stage_id = resolved["template_stage_id"]

    all_template_relations = get_relations_for_template_stage(template_stage_id)
    document_type_relations = [r for r in all_template_relations if r.get("Entity Type", "") == "document_template"]
    other_type_relations = [r for r in all_template_relations if r.get("Entity Type", "") != "document_template"]

    source = ""
    template_entity_ids: list[str] = []

    if document_type_relations:
        source = "relations"
        if other_type_relations:
            non_document_types = sorted({r.get("Entity Type", "") for r in other_type_relations})
            return {
                "ok": False, "code": "UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE",
                "error": (
                    f"Template Stage {template_stage_id} содержит relations типа "
                    f"{', '.join(non_document_types)} — эта команда синхронизирует только document_template."
                ),
                "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
                "to_add": (), "already_present": (), "created": (),
            }
        template_entity_ids = [r.get("Entity ID", "") for r in document_type_relations]
    else:
        legacy_ids = list((resolved.get("template_stage_row") or {}).get("document_template_ids", []))
        if legacy_ids:
            source = "legacy"
            invalid = []
            for doc_id in legacy_ids:
                errs = validate_relation_references({
                    "Template Stage ID": "", "Stage ID": stage_id,
                    "Entity Type": "document_template", "Entity ID": doc_id,
                })
                if errs:
                    invalid.append((doc_id, errs))
            if invalid:
                detail = "; ".join(f"{doc_id}: {', '.join(errs)}" for doc_id, errs in invalid)
                return {
                    "ok": False, "code": "INVALID_LEGACY_DOCUMENT_TEMPLATE_ID",
                    "error": f"Некорректные Document Template ID в legacy-поле Template Stage {template_stage_id}: {detail}",
                    "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
                    "to_add": (), "already_present": (), "created": (),
                }
            template_entity_ids = legacy_ids

    if not template_entity_ids:
        return {
            "ok": False, "code": "NO_DOCUMENT_TEMPLATE_RELATIONS",
            "error": (
                f"У Template Stage {template_stage_id} нет ни активных document_template relations, "
                f"ни значений в legacy-поле \"Document Template IDs\""
            ),
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": "",
            "to_add": (), "already_present": (), "created": (),
        }

    existing_relations = get_relations_for_stage(stage_id, entity_type="document_template")
    existing_entity_ids = {r.get("Entity ID", "") for r in existing_relations}

    to_add = tuple(eid for eid in template_entity_ids if eid not in existing_entity_ids)
    already_present = tuple(eid for eid in template_entity_ids if eid in existing_entity_ids)

    if dry_run:
        return {
            "ok": True, "code": "STAGE_KNOWLEDGE_SYNC_PREVIEW", "error": None,
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_add": to_add, "already_present": already_present, "created": (),
        }

    if source == "relations":
        write_result = copy_template_relations_to_stage(template_stage_id, stage_id)
    else:
        write_result = create_document_template_relations_for_stage(stage_id, template_entity_ids)

    if not write_result.ok:
        return {
            "ok": False, "code": "STAGE_KNOWLEDGE_SYNC_FAILED",
            "error": "; ".join(str(errs) for _, errs in write_result.errors) or "Не удалось синхронизировать",
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_add": to_add, "already_present": already_present, "created": (),
        }

    created_entity_ids = tuple(
        rec.get("Entity ID", "") for rec in write_result.created if rec.get("Entity Type", "") == "document_template"
    )
    return {
        "ok": True, "code": "STAGE_KNOWLEDGE_SYNCED", "error": None,
        "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
        "to_add": to_add, "already_present": already_present, "created": created_entity_ids,
    }


def sync_stage_sop_knowledge(stage_id: str, dry_run: bool = True) -> dict:
    """
    Phase 45 (SOP Foundation UX): the SOP twin of
    sync_stage_document_requirements() — same dual-source (active
    STAGE_ENTITY_RELATIONS "sop" relations on the Template Stage, else
    legacy ROADMAP_TEMPLATE_STAGES."SOP IDs" fallback), same
    preview/confirm contract, same idempotency guarantee, kept as a
    SEPARATE function (not merged into sync_stage_document_requirements())
    so neither function grows into a multi-entity-type monolith — the
    same principle already applied to keeping
    _evaluate_document_completion_gate()/_evaluate_checklist_completion_gate()
    as two small functions instead of one. /syncstageknowledge's handler
    calls both this and sync_stage_document_requirements() and combines
    their previews/results into one response.

    SOP relations carry no Required/Blocking semantics (see
    stage_entity_relations._SOP_RELATION_DEFAULTS) and are never read by
    transition_stage_status() or either Stage Completion Gate — this
    function exists purely to make "what SOP applies to this Stage"
    discoverable via /sop stage_id=..., nothing more.

    Never writes ROADMAP_STAGES (SOP IDs legacy column lives on
    ROADMAP_TEMPLATE_STAGES, not ROADMAP_STAGES, and isn't written here
    either way) and never touches Status/Responsible/Due Date/Priority/
    Progress — only ever calls stage_entity_relations functions.

    dry_run=True (the default, used for /syncstageknowledge's preview
    step) performs every read/resolution/validation step and returns
    what WOULD be added, without writing anything.

    Returns:
        {
            "ok": bool, "code": str, "error": str | None,
            "stage_id": str, "template_stage_id": str, "source": str,
            "to_add": tuple[str, ...],          # SOP IDs not yet linked to this Stage
            "already_present": tuple[str, ...], # SOP IDs already linked to this Stage
            "created": tuple[str, ...],         # actually created (dry_run=False only)
        }
        source is "" until a source is chosen, else "relations" or "legacy".
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage
    from business_core.stage_entity_relations import (
        get_relations_for_template_stage, get_relations_for_stage,
        copy_template_relations_to_stage, create_sop_relations_for_stage,
        validate_relation_references,
    )

    empty = {
        "stage_id": stage_id, "template_stage_id": "", "source": "",
        "to_add": (), "already_present": (), "created": (),
    }

    resolved = resolve_template_stage_for_stage(stage_id)
    if not resolved["ok"]:
        return {"ok": False, "code": resolved["code"], "error": resolved["error"], **empty}

    template_stage_id = resolved["template_stage_id"]

    all_template_relations = get_relations_for_template_stage(template_stage_id)
    sop_type_relations = [r for r in all_template_relations if r.get("Entity Type", "") == "sop"]
    other_type_relations = [r for r in all_template_relations if r.get("Entity Type", "") != "sop"]

    source = ""
    template_entity_ids: list[str] = []

    if sop_type_relations:
        source = "relations"
        if other_type_relations:
            non_sop_types = sorted({r.get("Entity Type", "") for r in other_type_relations})
            return {
                "ok": False, "code": "UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE",
                "error": (
                    f"Template Stage {template_stage_id} содержит relations типа "
                    f"{', '.join(non_sop_types)} — эта операция синхронизирует только sop."
                ),
                "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
                "to_add": (), "already_present": (), "created": (),
            }
        template_entity_ids = [r.get("Entity ID", "") for r in sop_type_relations]
    else:
        legacy_ids = list((resolved.get("template_stage_row") or {}).get("sop_ids", []))
        if legacy_ids:
            source = "legacy"
            invalid = []
            for sop_id in legacy_ids:
                errs = validate_relation_references({
                    "Template Stage ID": "", "Stage ID": stage_id,
                    "Entity Type": "sop", "Entity ID": sop_id,
                })
                if errs:
                    invalid.append((sop_id, errs))
            if invalid:
                detail = "; ".join(f"{sop_id}: {', '.join(errs)}" for sop_id, errs in invalid)
                return {
                    "ok": False, "code": "INVALID_LEGACY_SOP_ID",
                    "error": f"Некорректные SOP ID в legacy-поле Template Stage {template_stage_id}: {detail}",
                    "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
                    "to_add": (), "already_present": (), "created": (),
                }
            template_entity_ids = legacy_ids

    if not template_entity_ids:
        return {
            "ok": False, "code": "NO_SOP_KNOWLEDGE",
            "error": (
                f"У Template Stage {template_stage_id} нет ни активных sop relations, "
                f"ни значений в legacy-поле \"SOP IDs\""
            ),
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": "",
            "to_add": (), "already_present": (), "created": (),
        }

    existing_relations = get_relations_for_stage(stage_id, entity_type="sop")
    existing_entity_ids = {r.get("Entity ID", "") for r in existing_relations}

    to_add = tuple(eid for eid in template_entity_ids if eid not in existing_entity_ids)
    already_present = tuple(eid for eid in template_entity_ids if eid in existing_entity_ids)

    if dry_run:
        return {
            "ok": True, "code": "STAGE_SOP_SYNC_PREVIEW", "error": None,
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_add": to_add, "already_present": already_present, "created": (),
        }

    if source == "relations":
        write_result = copy_template_relations_to_stage(template_stage_id, stage_id)
    else:
        write_result = create_sop_relations_for_stage(stage_id, template_entity_ids)

    if not write_result.ok:
        return {
            "ok": False, "code": "STAGE_SOP_SYNC_FAILED",
            "error": "; ".join(str(errs) for _, errs in write_result.errors) or "Не удалось синхронизировать",
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_add": to_add, "already_present": already_present, "created": (),
        }

    created_entity_ids = tuple(
        rec.get("Entity ID", "") for rec in write_result.created if rec.get("Entity Type", "") == "sop"
    )
    return {
        "ok": True, "code": "STAGE_SOP_SYNCED", "error": None,
        "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
        "to_add": to_add, "already_present": already_present, "created": created_entity_ids,
    }


def sync_stage_output_requirements(stage_id: str, confirm: bool = False, read_context=None) -> dict:
    """
    Phase A (Stage Output Foundation): resolves the Template Stage for
    `stage_id`, reads its active required_output relations, and creates
    the missing Output Instances (STAGE_OUTPUT_INSTANCES) for the live
    Stage — idempotent per (Output Template ID, Stage ID) via
    stage_output_manager.create_output_instance()'s own idempotency
    check.

    Unlike sync_stage_document_requirements()/sync_stage_sop_knowledge(),
    there is no legacy comma-list fallback here — Required Output has no
    legacy column anywhere (explicit Phase A decision, item 21) and never
    will; STAGE_ENTITY_RELATIONS (Entity Type="required_output",
    Template-Stage-scoped only) is the sole source from day one. Also
    unlike those two sibling functions, a required_output relation is
    NEVER copied down into a Stage-scoped relation row — the "instance"
    for Required Output is a full STAGE_OUTPUT_INSTANCES row, not a
    relation copy (see stage_entity_relations.
    create_required_output_relation_for_template_stage()'s docstring for
    why the relation stays template-scoped only).

    An active relation whose Output Template is itself inactive (Status
    != "active") is excluded from creation and reported separately in
    `skipped_inactive_templates` — it is neither an error nor silently
    treated as "to_add".

    Never writes ROADMAP_STAGES, never touches Status/Responsible/Due
    Date/Priority/Progress, never evaluates or affects any Stage
    Completion Gate (Required/Blocking are copied onto the created
    instance for future use only — see stage_output_manager module
    docstring).

    confirm=False (the default, used for /syncoutputs' preview step):
    every read/resolution step runs and the result reports what WOULD be
    created, without writing anything.

    Returns:
        {
            "ok": bool, "code": str, "error": str | None,
            "stage_id": str, "template_stage_id": str,
            "to_add": tuple[str, ...],                     # Output Template IDs without an instance yet
            "already_present": tuple[str, ...],            # Output Template IDs with an instance already
            "created": tuple[str, ...],                    # actually created (confirm=True only)
            "skipped_inactive_templates": tuple[str, ...], # active relation, but Output Template itself inactive
            "errors": tuple,        # (output_template_id, error_code, error_message) per create failure — additive
            "partial_success": bool, # True only when SOME (not all) requested instances were created — additive
        }

    Additive contract note: `errors`/`partial_success` were added after
    this function's original shipping shape — every pre-existing field
    above is unchanged in name and meaning; every pre-existing caller
    that ignores these two new fields continues to work exactly as
    before. `errors` is itemized per Output Template (never an inferred
    count) — a create_output_instance() failure never stops the loop,
    every remaining to_add entry is still attempted, and no already-
    created instance is ever rolled back because a later one failed.

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache — see _TransitionReadContext.
    Threaded through resolve_template_stage_for_stage()/
    get_relations_for_template_stage()/find_output_template_by_id()/
    list_output_instances_for_stage() so ROADMAP_STAGES/ROADMAPS/
    ROADMAP_TEMPLATE_STAGES/STAGE_ENTITY_RELATIONS/STAGE_OUTPUT_TEMPLATES/
    STAGE_OUTPUT_INSTANCES are each read at most once per transition —
    find_output_template_by_id() in particular previously cost one
    find_row_by_id() API call per configured Output Template relation
    (M calls); with a context it reads the whole STAGE_OUTPUT_TEMPLATES
    table once and looks up all M in memory. Default None preserves the
    exact prior behavior (always fresh reads) for every existing direct
    caller (e.g. /syncoutputs).
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage
    from business_core.stage_entity_relations import get_relations_for_template_stage
    from business_core.stage_output_manager import (
        find_output_template_by_id, create_output_instance, list_output_instances_for_stage,
    )

    empty = {
        "stage_id": stage_id, "template_stage_id": "",
        "to_add": (), "already_present": (), "created": (), "skipped_inactive_templates": (),
        "errors": (), "partial_success": False,
    }

    resolved = resolve_template_stage_for_stage(stage_id, read_context=read_context)
    if not resolved["ok"]:
        return {"ok": False, "code": resolved["code"], "error": resolved["error"], **empty}

    template_stage_id = resolved["template_stage_id"]

    # get_relations_for_template_stage() defaults to active-only rows —
    # an inactive relation is never returned here at all, so it never
    # reaches `to_add`/creation and is not separately reported (only an
    # ACTIVE relation pointing at an INACTIVE Output Template is —
    # see skipped_inactive_templates below).
    relations = get_relations_for_template_stage(
        template_stage_id, entity_type="required_output", read_context=read_context,
    )
    if not relations:
        return {
            "ok": False, "code": "NO_REQUIRED_OUTPUT_RELATIONS",
            "error": f"У Template Stage {template_stage_id} нет активных required_output relations",
            "stage_id": stage_id, "template_stage_id": template_stage_id,
            "to_add": (), "already_present": (), "created": (), "skipped_inactive_templates": (),
            "errors": (), "partial_success": False,
        }

    relations_by_output_template_id = {r.get("Entity ID", ""): r for r in relations}

    skipped_inactive_templates = []
    active_template_ids = []
    for output_template_id in relations_by_output_template_id:
        template = find_output_template_by_id(output_template_id, read_context=read_context)
        if template is None or (template.get("Status", "") or "") != "active":
            skipped_inactive_templates.append(output_template_id)
        else:
            active_template_ids.append(output_template_id)

    existing_instances = list_output_instances_for_stage(stage_id, read_context=read_context)
    existing_template_ids = {i.get("Output Template ID", "") for i in existing_instances}

    to_add = tuple(otid for otid in active_template_ids if otid not in existing_template_ids)
    already_present = tuple(otid for otid in active_template_ids if otid in existing_template_ids)

    if not confirm:
        return {
            "ok": True, "code": "STAGE_OUTPUT_SYNC_PREVIEW", "error": None,
            "stage_id": stage_id, "template_stage_id": template_stage_id,
            "to_add": to_add, "already_present": already_present, "created": (),
            "skipped_inactive_templates": tuple(skipped_inactive_templates),
            "errors": (), "partial_success": False,
        }

    roadmap = resolved.get("roadmap") or {}
    created = []
    errors = []
    for output_template_id in to_add:
        relation = relations_by_output_template_id[output_template_id]
        result = create_output_instance(
            output_template_id, stage_id,
            roadmap_id=roadmap.get("roadmap_id", ""),
            business_id=roadmap.get("business_id", ""),
            service_id=roadmap.get("service_id", ""),
            object_id=roadmap.get("object_id", ""),
            required=relation.get("Required"),
            blocking=relation.get("Blocking"),
        )
        if result["ok"]:
            created.append(output_template_id)
        else:
            errors.append((
                output_template_id,
                result.get("code") or "OUTPUT_INSTANCE_CREATE_FAILED",
                result.get("error") or "unknown error",
            ))

    if not errors:
        ok, code = True, "STAGE_OUTPUT_SYNCED"
    elif created:
        ok, code = True, "STAGE_OUTPUT_SYNC_PARTIAL"
    else:
        ok, code = False, "STAGE_OUTPUT_SYNC_FAILED"

    return {
        "ok": ok, "code": code,
        "error": None if not errors else "; ".join(f"{otid}: {msg}" for otid, _, msg in errors),
        "stage_id": stage_id, "template_stage_id": template_stage_id,
        "to_add": to_add, "already_present": already_present, "created": tuple(created),
        "skipped_inactive_templates": tuple(skipped_inactive_templates),
        "errors": tuple(errors), "partial_success": bool(errors) and bool(created),
    }


def resolve_checklist_templates_for_template_stage(template_stage_id: str, read_context=None) -> dict:
    """
    Phase 1 (Checklist Relation Foundation): read-only resolver — same
    dual-source precedence already established for document_template/
    sop/required_output: active "checklist" STAGE_ENTITY_RELATIONS rows
    on the Template Stage, else the legacy ROADMAP_TEMPLATE_STAGES.
    "Checklist IDs" comma-list. Relations, when present, are the SOLE
    source — never merged with legacy, same no-merge rule as every
    sibling resolver in this codebase.

    Never writes anything.

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache — see _TransitionReadContext.
    Threaded to get_relations_for_template_stage() so STAGE_ENTITY_
    RELATIONS is read at most once per transition. Default None
    preserves the exact prior behavior for every existing caller.

    Returns:
        {
            "ok": bool, "error": str | None,
            "template_stage_id": str, "source": str,  # "relations" | "legacy" | ""
            "checklist_template_ids": tuple[str, ...],       # valid, active-template, de-duplicated (order preserved)
            "skipped_inactive_templates": tuple[str, ...],   # found but Checklist Template Status != "active"
            "invalid_legacy_checklist_ids": tuple[str, ...], # legacy source only: ID not found in checklist_registry
            "relations": tuple,  # additive — the raw active "checklist" relations read above (source=="relations"
                                 # only, else ()); lets a caller reuse them instead of a second
                                 # get_relations_for_template_stage() call for the same entity_type.
        }
    """
    from business_core.sheets import find_row_by_id
    from business_core.stage_entity_relations import get_relations_for_template_stage
    from business_core.knowledge_manager import find_checklist_by_id

    empty = {
        "template_stage_id": template_stage_id, "source": "",
        "checklist_template_ids": (), "skipped_inactive_templates": (),
        "invalid_legacy_checklist_ids": (), "relations": (),
    }

    if not template_stage_id:
        return {"ok": False, "error": "template_stage_id обязателен", **empty}

    found = find_row_by_id("roadmap_template_stages", template_stage_id)
    if found is None:
        return {"ok": False, "error": f"Template Stage {template_stage_id!r} не найден", **empty}

    relations = get_relations_for_template_stage(
        template_stage_id, entity_type="checklist", read_context=read_context,
    )

    if relations:
        checklist_ids: list[str] = []
        skipped_inactive: list[str] = []
        for rel in relations:
            checklist_id = rel.get("Entity ID", "")
            template = find_checklist_by_id(checklist_id)
            if template is None or template.get("Status", "") != "active":
                skipped_inactive.append(checklist_id)
            elif checklist_id not in checklist_ids:
                checklist_ids.append(checklist_id)
        return {
            "ok": True, "error": None,
            "template_stage_id": template_stage_id, "source": "relations",
            "checklist_template_ids": tuple(checklist_ids),
            "skipped_inactive_templates": tuple(skipped_inactive),
            "invalid_legacy_checklist_ids": (),
            "relations": tuple(relations),
        }

    _, row = found
    raw_legacy = row.get("Checklist IDs", "") or ""
    seen: dict[str, None] = {}
    for token in raw_legacy.split(","):
        token = token.strip()
        if token and token not in seen:
            seen[token] = None
    legacy_ids = list(seen.keys())

    if not legacy_ids:
        return {
            "ok": True, "error": None,
            "template_stage_id": template_stage_id, "source": "",
            "checklist_template_ids": (), "skipped_inactive_templates": (),
            "invalid_legacy_checklist_ids": (), "relations": (),
        }

    checklist_ids = []
    skipped_inactive = []
    invalid_ids: list[str] = []
    for checklist_id in legacy_ids:
        template = find_checklist_by_id(checklist_id)
        if template is None:
            invalid_ids.append(checklist_id)
        elif template.get("Status", "") != "active":
            skipped_inactive.append(checklist_id)
        else:
            checklist_ids.append(checklist_id)

    return {
        "ok": True, "error": None,
        "template_stage_id": template_stage_id, "source": "legacy",
        "checklist_template_ids": tuple(checklist_ids),
        "skipped_inactive_templates": tuple(skipped_inactive),
        "invalid_legacy_checklist_ids": tuple(invalid_ids),
        "relations": (),
    }


def provision_checklists_for_stage(stage_id: str, confirm: bool = False, read_context=None) -> dict:
    """
    Phase 1 (Checklist Relation Foundation): resolves the Template Stage
    for `stage_id`, determines which Checklist Templates apply via
    resolve_checklist_templates_for_template_stage() (relations first,
    legacy fallback, no merge), and creates the missing Checklist
    Instances for the live Stage via instantiate_checklist() — idempotent
    per instantiate_checklist()'s own 4-field key (business_id/
    checklist_template_id/roadmap_id/stage_id): a repeat call never
    creates a duplicate instance, it is recognized as already_existing.

    Only Blocking=true relations are within automatic-provisioning scope
    (see stage_entity_relations.ENTITY_TYPE_DISPATCH["checklist"]'s
    docstring for why — the Checklist Completion Gate itself has no
    concept of relation-level Blocking and is unconditionally applied to
    every live instance's required items once created, so a
    Blocking=false relation is deliberately never auto-instantiated in
    this phase — it remains visible via /checklists
    template_stage_id=... only). The legacy fallback carries no per-item
    Blocking data at all and is always treated as blocking (mirrors the
    established _DOCUMENT_TEMPLATE_RELATION_DEFAULTS precedent already
    used for legacy-sourced document_template/sop relations).

    Deliberately named neutrally (not "sync_...") and takes no Update/
    context/Telegram dependency — /syncchecklists is a thin wrapper over
    this function, and a future automatic pending->in_progress trigger
    (NOT built in this phase) could call it directly, unchanged. This
    phase does not wire any such trigger — transition_stage_status() is
    untouched.

    Never writes ROADMAP_STAGES, never touches Status/Responsible/Due
    Date/Priority/Progress, never evaluates or affects the Checklist
    Completion Gate (a created instance defaults to Status="draft", the
    exact same default a manual /startchecklist call produces, and is
    treated identically by the unchanged gate).

    confirm=False (default, used for /syncchecklists' preview step):
    every read/resolution step runs and the result reports what WOULD be
    created, without writing anything.

    A per-item create failure never stops the loop — every other
    requested instance is still attempted, matching the
    all-non-blocking-items-attempted principle already used elsewhere in
    this codebase.

    Returns:
        {
            "ok": bool, "code": str, "error": str | None,
            "stage_id": str, "template_stage_id": str, "source": str,
            "to_create": tuple[str, ...],        # Checklist Template IDs to instantiate
            "created": tuple[str, ...],          # actually created (confirm=True only)
            "already_existing": tuple[str, ...], # Checklist Template IDs with a live instance already
            "skipped_inactive": tuple[str, ...], # relation/legacy pointed at an inactive Checklist Template
            "errors": tuple,                     # (checklist_template_id, error string) per create failure
            "partial_success": bool,             # True only if SOME (not all) requested instances were created
        }

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache — see _TransitionReadContext.
    Threaded through resolve_template_stage_for_stage()/
    resolve_checklist_templates_for_template_stage()/
    list_checklist_instances() so ROADMAP_STAGES/ROADMAPS/
    ROADMAP_TEMPLATE_STAGES/STAGE_ENTITY_RELATIONS/CHECKLIST_INSTANCES
    are each read at most once per transition instead of once per
    subsystem call. The Blocking-filter below reuses `resolution
    ["relations"]` (additive field) instead of a second
    get_relations_for_template_stage() call for the same entity_type.
    Default None preserves the exact prior behavior (always fresh
    reads) for every existing direct caller (e.g. /syncchecklists).
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage
    from business_core.checklist_manager import list_checklist_instances

    empty = {
        "stage_id": stage_id, "template_stage_id": "", "source": "",
        "to_create": (), "created": (), "already_existing": (),
        "skipped_inactive": (), "errors": (), "partial_success": False,
    }

    resolved = resolve_template_stage_for_stage(stage_id, read_context=read_context)
    if not resolved["ok"]:
        return {"ok": False, "code": resolved["code"], "error": resolved["error"], **empty}

    template_stage_id = resolved["template_stage_id"]
    roadmap = resolved.get("roadmap") or {}

    resolution = resolve_checklist_templates_for_template_stage(template_stage_id, read_context=read_context)
    if not resolution["ok"]:
        return {"ok": False, "code": "TEMPLATE_STAGE_NOT_FOUND", "error": resolution["error"], **empty}

    source = resolution["source"]
    skipped_inactive = list(resolution["skipped_inactive_templates"])

    if not resolution["checklist_template_ids"]:
        return {
            "ok": False, "code": "NO_CHECKLIST_TEMPLATES",
            "error": f"У Template Stage {template_stage_id} нет активных checklist relations, ни legacy-значений",
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_create": (), "created": (), "already_existing": (),
            "skipped_inactive": tuple(skipped_inactive), "errors": (), "partial_success": False,
        }

    blocking_checklist_ids = list(resolution["checklist_template_ids"])
    if source == "relations":
        relations = resolution.get("relations") or ()
        blocking_by_id = {
            r.get("Entity ID", ""): (r.get("Blocking", "") or "").strip().lower() == "true" for r in relations
        }
        blocking_checklist_ids = [cid for cid in blocking_checklist_ids if blocking_by_id.get(cid, False)]

    business_id = roadmap.get("business_id", "")
    service_id = roadmap.get("service_id", "")
    object_id = roadmap.get("object_id", "")
    roadmap_id = roadmap.get("roadmap_id", "")

    existing_instances = [
        inst for inst in list_checklist_instances(business_id=business_id, read_context=read_context)
        if inst.get("Stage ID", "") == stage_id and inst.get("Status", "") not in ("cancelled", "archived")
    ]
    existing_template_ids = {inst.get("Checklist Template ID", "") for inst in existing_instances}

    to_create = tuple(cid for cid in blocking_checklist_ids if cid not in existing_template_ids)
    already_existing = tuple(cid for cid in blocking_checklist_ids if cid in existing_template_ids)

    if not confirm:
        return {
            "ok": True, "code": "CHECKLIST_PROVISION_PREVIEW", "error": None,
            "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
            "to_create": to_create, "created": (), "already_existing": already_existing,
            "skipped_inactive": tuple(skipped_inactive), "errors": (), "partial_success": False,
        }

    created: list[str] = []
    errors: list[tuple] = []
    for checklist_template_id in to_create:
        result = instantiate_checklist(
            business_id, checklist_template_id,
            service_id=service_id, object_id=object_id, roadmap_id=roadmap_id, stage_id=stage_id,
            read_context=read_context,
        )
        if result["ok"]:
            created.append(checklist_template_id)
        else:
            errors.append((checklist_template_id, result.get("error") or result.get("code") or "unknown"))

    if not errors:
        ok, code = True, "CHECKLIST_PROVISIONED"
    elif created:
        ok, code = True, "CHECKLIST_PROVISION_PARTIAL"
    else:
        ok, code = False, "CHECKLIST_PROVISION_FAILED"

    return {
        "ok": ok, "code": code,
        "error": None if not errors else "; ".join(f"{cid}: {err}" for cid, err in errors),
        "stage_id": stage_id, "template_stage_id": template_stage_id, "source": source,
        "to_create": to_create, "created": tuple(created), "already_existing": already_existing,
        "skipped_inactive": tuple(skipped_inactive), "errors": tuple(errors),
        "partial_success": bool(errors) and bool(created),
    }


_STAGE_PROVISIONING_CONFIRM_DENIED_STATUSES = frozenset({"done", "cancelled"})


def provision_stage_operational_instances(
    stage_id: str,
    confirm: bool = False,
    include_checklists: bool = True,
    include_outputs: bool = True,
    trigger: str = "manual",
    actor: str = "",
    read_context=None,
) -> dict:
    """
    Unified Stage Provisioning: a single call orchestrating both
    provision_checklists_for_stage() and sync_stage_output_requirements()
    for one Stage. Deliberately additive/wrapping only — neither child
    function's own contract, the Checklist/Output Completion Gates, or
    transition_stage_status() are touched by this function or by adding
    it. No Update/context/Telegram dependency: /provisionstage is a thin
    wrapper over this function, and a future automatic pending->
    in_progress trigger (NOT wired in this phase) could call it directly,
    unchanged.

    Resolution happens exactly ONCE here (via
    roadmap_manager.resolve_template_stage_for_stage()) — stage_id,
    roadmap_id, and template_stage_id are derived once and returned at
    the top level, rather than relying on comparing each child's own
    (otherwise redundant) resolution outcome. Each child function still
    performs its own internal resolve() *call* — but as of Sheets quota
    mitigation (2026-07-28), `read_context` (optional, see
    _TransitionReadContext) is threaded through to both children, so
    that repeated resolve() call is answered from cache (zero extra
    Sheets reads) rather than re-deriving Stage/Roadmap/Template Stage
    from scratch a 2nd/3rd/4th/5th time within one transition_stage_
    status() transaction — the RM-003 incident (2026-07-28, Google
    Sheets 429 quota exhaustion) traced a meaningful share of one
    transition's ~48-70 read requests to exactly this repeated
    resolution. `read_context=None` (the default) preserves the exact
    prior behavior for /provisionstage and every other direct caller.

    Status policy: `confirm=True` is refused (with
    STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS) when the Stage's current
    Status is "done" or "cancelled" — `confirm=False` (preview) is always
    allowed regardless of Status, since it never writes anything. No
    `force=` override exists in this phase.

    Both included subsystems are ALWAYS attempted (no short-circuit) —
    each wrapped in its own try/except so an unexpected exception in one
    never prevents the other from running and never propagates out of
    this function (a caller, including a future automatic trigger, must
    never see a raised exception here — only a structured error entry).
    A disabled subsystem (`include_checklists=False`/
    `include_outputs=False`) returns an explicit `SUBSYSTEM_DISABLED`
    code in its own raw result — never `None`, never silently omitted.

    `checklists`/`outputs` in the returned dict are each child's FULL,
    UNMODIFIED return dict — field names are never renamed or dropped.
    `totals` is computed ONLY by summing each child's own explicit
    tuple-length fields (`to_create`/`to_add`, `created`, `already_
    existing`/`already_present`, `skipped_inactive`/
    `skipped_inactive_templates`, `errors`) — no inferred/estimated
    count of any kind, now that sync_stage_output_requirements() itemizes
    its own errors additively.

    `trigger`/`actor` are returned in the structured result for a future
    caller's/log's use — neither is written to any sheet or table in
    this phase (no STAGE_PROVISIONING_LOG exists or is created here).

    Top-level `ok`/`code`/`partial_success` policy:
      A. Stage/Roadmap/Template Stage resolution itself fails -> ok=False,
         code=<the shared resolution code>, partial_success=False.
      B. Both INCLUDED subsystems have nothing configured (or are
         disabled) -> ok=True, code="NOTHING_TO_PROVISION",
         partial_success=False.
      C. totals["errors"] == 0 -> ok=True, code="STAGE_PROVISIONED",
         partial_success=False.
      D. totals["errors"] > 0 and (totals["created"] > 0 or
         totals["already_existing"] > 0) -> ok=True,
         code="STAGE_PROVISION_PARTIAL", partial_success=True.
      E. totals["errors"] > 0 and totals["created"] == 0 and
         totals["already_existing"] == 0 -> ok=False,
         code="STAGE_PROVISION_FAILED", partial_success=False.
    `skipped` never counts as an error for this policy.

    Returns:
        {
            "ok": bool, "code": str,
            "stage_id": str, "roadmap_id": str, "template_stage_id": str,
            "confirm": bool, "trigger": str, "actor": str,
            "checklists": dict,  # raw provision_checklists_for_stage() result (or SUBSYSTEM_DISABLED shape)
            "outputs": dict,     # raw sync_stage_output_requirements() result (or SUBSYSTEM_DISABLED shape)
            "totals": {"to_create": int, "created": int, "already_existing": int, "skipped": int, "errors": int},
            "partial_success": bool,
            "warnings": tuple,  # e.g. an unexpected subsystem exception, caught here
            "errors": tuple,    # populated only for policy A / B (resolution failure / status denial)
        }
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage

    def _empty_result(ok: bool, code: str, roadmap_id: str = "", template_stage_id: str = "",
                       errors: tuple = ()) -> dict:
        return {
            "ok": ok, "code": code,
            "stage_id": stage_id, "roadmap_id": roadmap_id, "template_stage_id": template_stage_id,
            "confirm": confirm, "trigger": trigger, "actor": actor,
            "checklists": {}, "outputs": {},
            "totals": {"to_create": 0, "created": 0, "already_existing": 0, "skipped": 0, "errors": 0},
            "partial_success": False,
            "warnings": (), "errors": errors,
        }

    resolved = resolve_template_stage_for_stage(stage_id, read_context=read_context)
    if not resolved["ok"]:
        return _empty_result(False, resolved["code"], errors=(resolved.get("error") or resolved["code"],))

    roadmap = resolved.get("roadmap") or {}
    roadmap_id = roadmap.get("roadmap_id", "")
    template_stage_id = resolved["template_stage_id"]
    stage = resolved.get("stage") or {}
    stage_status = stage.get("status", "")

    if confirm and stage_status in _STAGE_PROVISIONING_CONFIRM_DENIED_STATUSES:
        return _empty_result(
            False, "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS", roadmap_id, template_stage_id,
            errors=(f"Provisioning с confirm=yes запрещён для Stage со статусом {stage_status!r}.",),
        )

    disabled_checklists_result = {
        "ok": True, "code": "SUBSYSTEM_DISABLED", "error": None,
        "stage_id": stage_id, "template_stage_id": template_stage_id, "source": "",
        "to_create": (), "created": (), "already_existing": (), "skipped_inactive": (),
        "errors": (), "partial_success": False,
    }
    disabled_outputs_result = {
        "ok": True, "code": "SUBSYSTEM_DISABLED", "error": None,
        "stage_id": stage_id, "template_stage_id": template_stage_id,
        "to_add": (), "already_present": (), "created": (), "skipped_inactive_templates": (),
        "errors": (), "partial_success": False,
    }

    warnings: list[str] = []

    if include_checklists:
        try:
            checklists_result = provision_checklists_for_stage(stage_id, confirm=confirm, read_context=read_context)
        except Exception as exc:
            log.error(f"provision_stage_operational_instances({stage_id}): checklist subsystem exception: {exc}")
            warnings.append(f"Checklist subsystem raised an exception: {exc}")
            checklists_result = {
                "ok": False, "code": "CHECKLIST_SUBSYSTEM_EXCEPTION", "error": str(exc),
                "stage_id": stage_id, "template_stage_id": template_stage_id, "source": "",
                "to_create": (), "created": (), "already_existing": (), "skipped_inactive": (),
                "errors": (("", "CHECKLIST_SUBSYSTEM_EXCEPTION", str(exc)),), "partial_success": False,
            }
    else:
        checklists_result = disabled_checklists_result

    if include_outputs:
        try:
            outputs_result = sync_stage_output_requirements(stage_id, confirm=confirm, read_context=read_context)
        except Exception as exc:
            log.error(f"provision_stage_operational_instances({stage_id}): output subsystem exception: {exc}")
            warnings.append(f"Output subsystem raised an exception: {exc}")
            outputs_result = {
                "ok": False, "code": "OUTPUT_SUBSYSTEM_EXCEPTION", "error": str(exc),
                "stage_id": stage_id, "template_stage_id": template_stage_id,
                "to_add": (), "already_present": (), "created": (), "skipped_inactive_templates": (),
                "errors": (("", "OUTPUT_SUBSYSTEM_EXCEPTION", str(exc)),), "partial_success": False,
            }
    else:
        outputs_result = disabled_outputs_result

    totals = {
        "to_create": len(checklists_result.get("to_create", ())) + len(outputs_result.get("to_add", ())),
        "created": len(checklists_result.get("created", ())) + len(outputs_result.get("created", ())),
        "already_existing": (
            len(checklists_result.get("already_existing", ())) + len(outputs_result.get("already_present", ()))
        ),
        "skipped": (
            len(checklists_result.get("skipped_inactive", ())) + len(outputs_result.get("skipped_inactive_templates", ()))
        ),
        "errors": len(checklists_result.get("errors", ())) + len(outputs_result.get("errors", ())),
    }

    checklists_configured = checklists_result.get("code") not in ("SUBSYSTEM_DISABLED", "NO_CHECKLIST_TEMPLATES")
    outputs_configured = outputs_result.get("code") not in ("SUBSYSTEM_DISABLED", "NO_REQUIRED_OUTPUT_RELATIONS")

    if not checklists_configured and not outputs_configured:
        ok, code, partial_success = True, "NOTHING_TO_PROVISION", False
    elif totals["errors"] == 0:
        ok, code, partial_success = True, "STAGE_PROVISIONED", False
    elif totals["created"] > 0 or totals["already_existing"] > 0:
        ok, code, partial_success = True, "STAGE_PROVISION_PARTIAL", True
    else:
        ok, code, partial_success = False, "STAGE_PROVISION_FAILED", False

    return {
        "ok": ok, "code": code,
        "stage_id": stage_id, "roadmap_id": roadmap_id, "template_stage_id": template_stage_id,
        "confirm": confirm, "trigger": trigger, "actor": actor,
        "checklists": checklists_result, "outputs": outputs_result,
        "totals": totals, "partial_success": partial_success,
        "warnings": tuple(warnings), "errors": (),
    }


def transition_document_status(document_id: str, target_status: str) -> dict:
    """
    Phase 37D (ADR-020 §15/§11/§12): the sole canonical Document-
    transition orchestration boundary.

    Validation order, all before any write:
      A. required document_id
      B. Document exists (DOCUMENT_NOT_FOUND)
      C. target status validation (INVALID_DOCUMENT_STATUS)
      D. terminal-state reopen gate (DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION
         for an ordinary attempt to leave superseded/archived)
      E. ordinary transition-matrix validation (INVALID_DOCUMENT_TRANSITION)
      F. persist Status
      G. structured result

    No review-field mutation, no AI mutation, no Drive mutation, no
    relation mutation, no Stage/Roadmap/Task mutation happens here.
    """
    from business_core.document_manager import find_document_by_id, update_document_status, DOCUMENT_STATUS

    if not document_id:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error="document_id обязателен")

    document = find_document_by_id(document_id)
    if document is None:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error=f"Document {document_id} не найден", document_id=document_id)

    business_id = document.get("business_id", "")
    previous_status = document.get("status", "")

    if target_status not in DOCUMENT_STATUS:
        return _document_result(
            ok=False, code="INVALID_DOCUMENT_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(DOCUMENT_STATUS)}",
            document_id=document_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if previous_status in _DOCUMENT_REOPEN_GATED_STATUSES and target_status != previous_status:
        return _document_result(
            ok=False, code="DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION",
            error=(
                f"Document {document_id} имеет статус '{previous_status}' — обычное обновление не может "
                f"вернуть его в '{target_status}'. Требуется отдельное явное действие restore (не реализовано)."
            ),
            document_id=document_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    allowed_targets = _DOCUMENT_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _document_result(
            ok=False, code="INVALID_DOCUMENT_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            document_id=document_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    write_result = update_document_status(document_id, target_status)
    if not write_result["ok"]:
        return _document_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            document_id=document_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _document_result(
        ok=True, code="DOCUMENT_STATUS_UPDATED" if changed else "DOCUMENT_STATUS_UNCHANGED", error=None,
        document_id=document_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status,
        final_status=target_status, changed=changed,
    )


# ─────────────────────────────────────────────────────────────
# Phase 16C.9C: Document Archive Domain Operation.
#
# archive_document() is the sole canonical orchestration boundary for
# archiving a Document — telegram_handlers.py (no command exists yet)
# must call this, never document_manager.archive_document_row()
# directly, never sheets.update_business_row() directly, never
# transition_document_status()/update_document_status() as a
# substitute (those never write the four durable archive-metadata
# fields). Archive means Status = "archived" on exactly the named
# Document ID row — no Drive mutation, no DOCUMENT_CONTENT mutation,
# no DOCUMENT_FIELD_REVIEWS mutation, no family-wide effect, no
# restore (not implemented in this phase).
# ─────────────────────────────────────────────────────────────

_DOCUMENT_ARCHIVE_REASON_MAX_LENGTH = 500
_DOCUMENT_ARCHIVE_ACTOR_RE = re.compile(r"^telegram:[0-9]+$")


def archive_document(
    document_id: str,
    reason: str,
    archived_by: str,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Phase 16C.9C (ADR-020 archive extension): the sole canonical
    Document-archive orchestration boundary.

    Validation order, all before any write:
      A. required document_id (trimmed)
      B. required, length-bounded reason (trimmed)
      C. archived_by must match exactly telegram:{digits}
      D. Document exists (DOCUMENT_NOT_FOUND)
      E. already-archived short-circuit (idempotent no-op, zero
         further reads/writes — also covers legacy rows with
         incomplete archive metadata: never repaired, never
         overwritten)
      F. ordinary transition-matrix validation, reusing
         _DOCUMENT_ORDINARY_TRANSITIONS as-is (INVALID_DOCUMENT_TRANSITION
         for e.g. superseded -> archived)
      G. (dry_run only) return preview, no write, no generated
         timestamp
      H. generate one canonical timestamp, used for both Archived At
         and Updated At
      I. one manager write (archive_document_row)
      J. post-write re-read + six-field verification
      K. structured result

    No Drive/DOCUMENT_CONTENT/DOCUMENT_FIELD_REVIEWS/requirements/
    Telegram calls anywhere in this function.
    """
    from business_core.document_manager import find_document_by_id, archive_document_row

    document_id = (document_id or "").strip()
    if not document_id:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error="document_id обязателен")

    reason = (reason or "").strip()
    if not reason:
        return _document_result(
            ok=False, code="DOCUMENT_ARCHIVE_REASON_REQUIRED",
            error="reason обязателен", document_id=document_id,
        )
    if len(reason) > _DOCUMENT_ARCHIVE_REASON_MAX_LENGTH:
        return _document_result(
            ok=False, code="DOCUMENT_ARCHIVE_REASON_TOO_LONG",
            error=f"reason не может превышать {_DOCUMENT_ARCHIVE_REASON_MAX_LENGTH} символов",
            document_id=document_id,
        )

    if not archived_by or not _DOCUMENT_ARCHIVE_ACTOR_RE.match(archived_by):
        return _document_result(
            ok=False, code="DOCUMENT_ARCHIVE_ACTOR_INVALID",
            error="archived_by должен точно соответствовать формату telegram:{numeric_id}",
            document_id=document_id,
        )

    document = find_document_by_id(document_id)
    if document is None:
        return _document_result(ok=False, code="DOCUMENT_NOT_FOUND", error=f"Document {document_id} не найден", document_id=document_id)

    business_id = document.get("business_id", "")
    document_name = document.get("document_name", "")
    roadmap_id = document.get("roadmap_id", "")
    stage_id = document.get("stage_id", "")
    document_template_id = document.get("document_template_id", "")
    current_status = document.get("status", "")

    if current_status == "archived":
        # Idempotent no-op — also covers a legacy archived row with
        # incomplete/blank archive metadata: never repaired, never
        # overwritten, existing (possibly blank) values returned as-is.
        return _document_result(
            ok=True, code="DOCUMENT_ARCHIVE_ALREADY_ARCHIVED", error=None,
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=document.get("previous_status", ""),
            requested_status="archived", final_status="archived",
            archived_at=document.get("archived_at", ""), archived_by=document.get("archived_by", ""),
            archive_reason=document.get("archive_reason", ""),
            changed=False, retry_safe=True,
        )

    allowed_targets = _DOCUMENT_ORDINARY_TRANSITIONS.get(current_status, (current_status,))
    if "archived" not in allowed_targets:
        return _document_result(
            ok=False, code="INVALID_DOCUMENT_TRANSITION",
            error=f"Переход '{current_status}' → 'archived' не разрешён",
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=current_status, requested_status="archived", final_status=current_status,
        )

    if dry_run:
        return _document_result(
            ok=True, code="DOCUMENT_ARCHIVE_PREVIEW", error=None,
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=current_status, requested_status="archived", final_status="archived",
            archived_at="", archived_by=archived_by, archive_reason=reason,
            changed=False, retry_safe=True,
        )

    from datetime import timezone
    archived_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    write_result = archive_document_row(
        document_id, archived_at=archived_at, archived_by=archived_by,
        archive_reason=reason, previous_status=current_status,
    )
    if not write_result["ok"]:
        return _document_result(
            ok=False, code=write_result.get("code") or "DOCUMENT_ARCHIVE_WRITE_FAILED", error=None,
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=current_status, requested_status="archived", final_status=current_status,
            retry_safe=False,
        )

    reread = find_document_by_id(document_id)
    if reread is None:
        log.error(f"archive_document({document_id}) post-write verification: document missing on re-read")
        return _document_result(
            ok=False, code="DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED", error=None,
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=current_status, requested_status="archived", final_status=current_status,
            retry_safe=False,
        )

    expected = {
        "status": "archived", "archived_at": archived_at, "archived_by": archived_by,
        "archive_reason": reason, "previous_status": current_status, "updated_at": archived_at,
    }
    mismatches = {k: {"expected": v, "actual": reread.get(k)} for k, v in expected.items() if reread.get(k) != v}
    if mismatches:
        log.error(f"archive_document({document_id}) post-write verification mismatch fields: {sorted(mismatches.keys())}")
        return _document_result(
            ok=False, code="DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED", error=None,
            document_id=document_id, business_id=business_id, document_name=document_name,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
            previous_status=current_status, requested_status="archived", final_status=current_status,
            retry_safe=False,
        )

    return _document_result(
        ok=True, code="DOCUMENT_ARCHIVED", error=None,
        document_id=document_id, business_id=business_id, document_name=document_name,
        roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=document_template_id,
        previous_status=current_status, requested_status="archived", final_status="archived",
        archived_at=archived_at, archived_by=archived_by, archive_reason=reason,
        changed=True, retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Phase 37F.1 (ADR-020 §12): Document upload-safety orchestration.
#
# Telegram must never implement validation or compensation-code
# policy itself — it calls these functions and renders whatever code
# comes back. The actual Drive upload/download and the compensation
# trash_file() call remain in telegram_handlers.py (both require
# `await`, which these synchronous functions cannot do), but the
# MEANING of every resulting code is decided here, not there.
# ─────────────────────────────────────────────────────────────

def validate_document_upload_request(file_name: str, mime_type: str, file_size: int | None = None) -> dict:
    """
    Canonical pre-Drive-upload validation boundary. Telegram calls this
    (never business_core.document_upload_validation directly) before
    performing any Drive upload, using metadata it already has from
    Telegram's own file object — so an invalid/oversized/dangerous
    file never reaches Drive at all.

    Returns the standard structured Document result. ok=True with
    code="DOCUMENT_ANALYSIS_UNSUPPORTED" means storage is allowed but
    business_core.document_intelligence cannot analyze this MIME type
    — informational only, never a rejection (ADR-020 §12: AI support
    is never a prerequisite for storage). ok=True with code="" means
    fully supported for both storage and analysis — the caller maps
    that to DOCUMENT_UPLOAD_VALIDATED.
    """
    from business_core.document_upload_validation import validate_upload_request

    result = validate_upload_request(file_name, mime_type, file_size)
    analysis_supported = result.get("analysis_supported", True)
    return _document_result(
        ok=result["ok"],
        code=result["code"] or ("DOCUMENT_UPLOAD_VALIDATED" if result["ok"] else ""),
        error=result.get("error"),
        analysis_status="unsupported" if not analysis_supported else "",
        retry_safe=True,
    )


def document_drive_upload_failed_result(business_id: str = "") -> dict:
    """The Drive upload call itself failed — nothing was ever created
    in Drive, so no compensation is needed or attempted."""
    return _document_result(
        ok=False, code="DRIVE_UPLOAD_FAILED",
        error="Не удалось загрузить файл в Google Drive", business_id=business_id, retry_safe=True,
    )


def document_file_metadata_invalid_result(
    *, business_id: str = "", drive_file_id: str = "",
    compensation_attempted: bool = False, compensation_succeeded: bool = False,
) -> dict:
    """
    Authoritative Drive metadata (name/mime_type/webViewLink) was
    missing or incomplete after upload — no Document row is ever
    persisted in this case. compensation_attempted/succeeded carry the
    outcome of the caller's own (necessarily async) Drive-trash
    attempt; the code itself stays DOCUMENT_FILE_METADATA_INVALID
    regardless of that outcome (ADR-020 §12/§6 permits either — this
    keeps the root cause visible, with compensation as a sub-detail).
    """
    return _document_result(
        ok=False, code="DOCUMENT_FILE_METADATA_INVALID",
        error="Не удалось получить полные метаданные файла из Google Drive после загрузки",
        business_id=business_id, drive_file_id=drive_file_id,
        compensation_attempted=compensation_attempted, compensation_succeeded=compensation_succeeded,
        retry_safe=True,
    )


def finalize_persistence_failure_compensation(result: dict, *, compensation_succeeded: bool) -> dict:
    """
    Given a DOCUMENT_PERSISTENCE_FAILED result and the outcome of the
    caller's own (necessarily async) Drive-trash compensation attempt,
    returns the final canonical code — DRIVE_UPLOAD_COMPENSATED on
    success, DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING on
    failure. Never claims upload success either way; register-
    existing-file mode (register_document() with no Drive upload of
    its own) never calls this — a pre-existing Drive file is never
    trashed by that mode.
    """
    code = "DRIVE_UPLOAD_COMPENSATED" if compensation_succeeded else "DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING"
    return _document_result(
        ok=False, code=code, error=result.get("error"),
        business_id=result.get("business_id", ""), drive_file_id=result.get("drive_file_id", ""),
        compensation_attempted=True, compensation_succeeded=compensation_succeeded, retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Phase 38C (ADR-021): Checklist Domain orchestration.
#
# business_builder.py is the sole cross-domain Checklist orchestration
# owner: relation validation, Template lookup/parsing, instantiation
# idempotency, Instance+Item creation, progress computation, lifecycle
# transitions, structured result assembly. business_core.checklist_
# manager.py (persistence) and business_core.knowledge_manager.py
# (Template reads) are called from here — never the reverse. No
# Telegram caller exists yet (Phase 38D); nothing here is called by
# telegram_handlers.py in this phase.
# ─────────────────────────────────────────────────────────────

_CHECKLIST_INSTANCE_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":       ("draft", "in_progress", "cancelled", "archived"),
    "in_progress": ("in_progress", "blocked", "completed", "cancelled", "archived"),
    "blocked":     ("blocked", "in_progress", "cancelled", "archived"),
    "completed":   ("completed", "archived"),
    "cancelled":   ("cancelled", "archived"),
    "archived":    ("archived",),
}
_CHECKLIST_INSTANCE_REOPEN_GATED_STATUSES = frozenset({"completed", "cancelled", "archived"})

_CHECKLIST_ITEM_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending":         ("pending", "in_progress", "blocked", "done", "skipped", "not_applicable"),
    "in_progress":     ("in_progress", "pending", "blocked", "done", "skipped", "not_applicable"),
    "blocked":         ("blocked", "pending", "in_progress", "done", "skipped", "not_applicable"),
    "done":            ("done",),
    "skipped":         ("skipped",),
    "not_applicable":  ("not_applicable",),
}
_CHECKLIST_ITEM_TERMINAL_STATUSES = frozenset({"done", "skipped", "not_applicable"})
_CHECKLIST_SATISFYING_ITEM_STATUSES = frozenset({"done", "not_applicable"})


def _now_utc_str() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _checklist_result(
    *, ok: bool, code: str, error: str | None,
    checklist_instance_id: str = "", checklist_template_id: str = "", checklist_instance_item_id: str = "",
    business_id: str = "", service_id: str = "", object_id: str = "", roadmap_id: str = "", stage_id: str = "",
    task_id: str = "", document_id: str = "", sop_id: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False, completed: bool = False,
    total_items: int = 0, required_items: int = 0, completed_items: int = 0,
    required_remaining: int = 0, blocked_required: int = 0,
    conflicting_ids: tuple = (), created_item_ids: tuple = (),
    warnings: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Checklist orchestration function
    (ADR-021 §24) — the stable, structured contract every caller reads
    instead of a bare exception or ad-hoc dict shape. Never carries a
    raw exception object or a raw Sheets row."""
    return {
        "ok": ok, "code": code, "error": error,
        "checklist_instance_id": checklist_instance_id, "checklist_template_id": checklist_template_id,
        "checklist_instance_item_id": checklist_instance_item_id,
        "business_id": business_id, "service_id": service_id, "object_id": object_id,
        "roadmap_id": roadmap_id, "stage_id": stage_id,
        "task_id": task_id, "document_id": document_id, "sop_id": sop_id,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed, "completed": completed,
        "total_items": total_items, "required_items": required_items, "completed_items": completed_items,
        "required_remaining": required_remaining, "blocked_required": blocked_required,
        "conflicting_ids": tuple(conflicting_ids), "created_item_ids": tuple(created_item_ids),
        "warnings": tuple(warnings), "retry_safe": retry_safe,
    }


def _split_checklist_text(text: str) -> list[str]:
    """Deterministic separator normalization: newline treated as an
    alternative to semicolon (both used interchangeably in production
    Template text), never AI/fuzzy. Order preserved, whitespace
    trimmed, empty tokens dropped."""
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\n", ";")
    return [t.strip() for t in normalized.split(";") if t.strip()]


def parse_checklist_template_items(items_text: str, required_text: str = "", optional_text: str = "") -> dict:
    """
    Phase 38C (ADR-021 §11/§7): the sole deterministic Template-item
    parser. Duplicate item text remains two distinct items, keyed by
    ordinal — never deduplicated. Required/Optional classification is
    exact-normalized-text-match only; a token that matches neither list
    defaults to required=true (the safest default per ADR-021 — an
    unclassified item never silently becomes optional). A token
    present in BOTH lists is a classification conflict and blocks
    instantiation entirely; no fuzzy interpretation is ever attempted.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "items": list[dict]}

    Each item dict: {"source_item_key", "item_order", "item_title_snapshot",
    "item_description_snapshot", "required"}.
    """
    raw_items = _split_checklist_text(items_text)
    if not raw_items:
        return {"ok": False, "code": "CHECKLIST_TEMPLATE_ITEMS_EMPTY", "error": "Список пунктов Template пуст", "items": []}

    required_set = set(_split_checklist_text(required_text))
    optional_set = set(_split_checklist_text(optional_text))

    conflict = required_set & optional_set
    if conflict:
        return {
            "ok": False, "code": "CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT",
            "error": f"Пункты одновременно в Required Items и Optional Items: {', '.join(sorted(conflict))}",
            "items": [],
        }

    items = []
    for ordinal, text in enumerate(raw_items, start=1):
        required = text not in optional_set
        items.append({
            "source_item_key": ordinal,
            "item_order": ordinal,
            "item_title_snapshot": text,
            "item_description_snapshot": "",
            "required": required,
        })
    return {"ok": True, "code": "", "error": None, "items": items}


def _compute_checklist_progress(items: list[dict]) -> dict:
    """
    Phase 38C (ADR-021 §16): canonical progress calculator. `items` is
    a list of {"required": bool, "status": str}. Item statuses are the
    sole truth; this is always recomputed from them, never from a
    prior cache. skipped never counts as complete for a required item.
    """
    total = len(items)
    required_items = sum(1 for i in items if i["required"])
    completed_items = sum(1 for i in items if i["status"] in _CHECKLIST_SATISFYING_ITEM_STATUSES)
    required_remaining = sum(
        1 for i in items if i["required"] and i["status"] not in _CHECKLIST_SATISFYING_ITEM_STATUSES
    )
    blocked_required = sum(1 for i in items if i["required"] and i["status"] == "blocked")
    return {
        "total_items": total, "required_items": required_items,
        "completed_items": completed_items, "required_remaining": required_remaining,
        "blocked_required": blocked_required,
    }


def _validate_checklist_relations(
    business_id: str, service_id: str = "", object_id: str = "", roadmap_id: str = "", stage_id: str = "",
) -> dict:
    """
    Phase 38C (ADR-021 §9): canonical cross-domain Checklist Instance
    relation-validation path, all before any write. Resolution order
    is most-specific-first (Stage, then Roadmap, deriving Object/
    Service) — mirrors document_registry_manager.
    resolve_and_validate_links() exactly, applied to Checklist's own
    (smaller) relation set. Task/Document/SOP are Item-level and never
    validated here — they remain blank in Foundation (ADR-021 §5/§14).

    Returns:
        {"ok": bool, "code": str, "error": str | None, "resolved": dict | None}
    """
    from business_core.sheets import read_business_sheet

    if not business_id:
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен", "resolved": None}

    biz_rows = read_business_sheet("biz_registry")
    if not any(b.get("ID", "") == business_id for b in biz_rows):
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": f"Business {business_id} не найден", "resolved": None}

    resolved_stage_id = stage_id
    resolved_roadmap_id = roadmap_id
    resolved_object_id = object_id
    resolved_service_id = service_id

    if resolved_stage_id:
        stages = read_business_sheet("roadmap_stages")
        stage = next((s for s in stages if s.get("Stage ID", "") == resolved_stage_id), None)
        if stage is None:
            return {"ok": False, "code": "STAGE_NOT_FOUND", "error": f"Stage {resolved_stage_id} не найден", "resolved": None}
        stage_roadmap_id = stage.get("Roadmap ID", "")
        if resolved_roadmap_id and stage_roadmap_id and resolved_roadmap_id != stage_roadmap_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Stage {resolved_stage_id} принадлежит Roadmap {stage_roadmap_id}, а указан Roadmap {resolved_roadmap_id}",
                "resolved": None,
            }
        resolved_roadmap_id = resolved_roadmap_id or stage_roadmap_id

    if resolved_roadmap_id:
        roadmaps = read_business_sheet("roadmaps")
        rm = next((r for r in roadmaps if r.get("Roadmap ID", "") == resolved_roadmap_id), None)
        if rm is None:
            return {"ok": False, "code": "ROADMAP_NOT_FOUND", "error": f"Roadmap {resolved_roadmap_id} не найден", "resolved": None}
        rm_biz_id = rm.get("Business ID", "")
        if rm_biz_id and rm_biz_id != business_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} принадлежит бизнесу {rm_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }
        rm_object_id = rm.get("Object ID", "")
        if resolved_object_id and rm_object_id and resolved_object_id != rm_object_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Object {rm_object_id}, а указан Object {resolved_object_id}",
                "resolved": None,
            }
        resolved_object_id = resolved_object_id or rm_object_id
        rm_service_id = rm.get("Service ID", "")
        if resolved_service_id and rm_service_id and resolved_service_id != rm_service_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Service {rm_service_id}, а указан Service {resolved_service_id}",
                "resolved": None,
            }
        resolved_service_id = resolved_service_id or rm_service_id

    if resolved_object_id:
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(resolved_object_id)
        if obj is None:
            return {"ok": False, "code": "OBJECT_NOT_FOUND", "error": f"Object {resolved_object_id} не найден", "resolved": None}
        obj_biz_id = obj.get("biz_id", "")
        if obj_biz_id and obj_biz_id != business_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Object {resolved_object_id} принадлежит бизнесу {obj_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    if resolved_service_id:
        from business_core.service_manager import find_service_by_id
        svc = find_service_by_id(resolved_service_id)
        if svc is None:
            return {"ok": False, "code": "SERVICE_NOT_FOUND", "error": f"Service {resolved_service_id} не найден", "resolved": None}
        svc_biz_id = svc.get("biz_id", "")
        if svc_biz_id and svc_biz_id != business_id:
            return {
                "ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH",
                "error": f"Service {resolved_service_id} принадлежит бизнесу {svc_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    return {
        "ok": True, "code": "", "error": None,
        "resolved": {
            "business_id": business_id, "service_id": resolved_service_id, "object_id": resolved_object_id,
            "roadmap_id": resolved_roadmap_id, "stage_id": resolved_stage_id,
        },
    }


def instantiate_checklist(
    business_id: str, checklist_template_id: str,
    *, service_id: str = "", object_id: str = "", roadmap_id: str = "", stage_id: str = "",
    created_by: str = "", notes: str = "", read_context=None,
) -> dict:
    """
    Phase 38C (ADR-021 §10/§11): the sole canonical Checklist
    instantiation orchestration boundary.

    Validation order, all before any write:
      A. required business_id / checklist_template_id
      B. Template lookup + status validation (active only)
      C. Template item parsing (complete, before any ID/relation work)
      D. relation validation
      E. idempotency lookup (zero/one/multiple)
      F. Instance ID/Item IDs generated only after A-E pass
      G. low-level parent + item persistence
      H. post-write verification
      I. structured result

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache — see _TransitionReadContext.
    Threaded to find_instances_by_idempotency_key() (step E) so
    CHECKLIST_INSTANCES is read at most once across every checklist
    provision_checklists_for_stage() creates in the same to_create loop,
    instead of once per checklist. Default None preserves the exact
    prior behavior (always a fresh read) for every existing direct
    caller.
    """
    from business_core.checklist_manager import (
        find_instances_by_idempotency_key, create_checklist_instance, create_checklist_instance_items,
        find_checklist_instance_by_id, list_checklist_instance_items,
    )
    from business_core.knowledge_manager import find_checklist_by_id

    if not business_id:
        return _checklist_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not checklist_template_id:
        return _checklist_result(ok=False, code="CHECKLIST_TEMPLATE_NOT_FOUND", error="checklist_template_id обязателен")

    template = find_checklist_by_id(checklist_template_id)
    if template is None:
        return _checklist_result(
            ok=False, code="CHECKLIST_TEMPLATE_NOT_FOUND", error=f"Checklist Template {checklist_template_id} не найден",
            business_id=business_id, checklist_template_id=checklist_template_id,
        )

    template_status = template.get("Status", "")
    if template_status == "inactive":
        return _checklist_result(
            ok=False, code="CHECKLIST_TEMPLATE_INACTIVE", error=f"Checklist Template {checklist_template_id} неактивен",
            business_id=business_id, checklist_template_id=checklist_template_id,
        )
    if template_status == "archived":
        return _checklist_result(
            ok=False, code="CHECKLIST_TEMPLATE_ARCHIVED", error=f"Checklist Template {checklist_template_id} архивирован",
            business_id=business_id, checklist_template_id=checklist_template_id,
        )
    if template_status != "active":
        return _checklist_result(
            ok=False, code="INVALID_CHECKLIST_TEMPLATE_STATUS",
            error=f"Недопустимый статус Checklist Template: '{template_status}'",
            business_id=business_id, checklist_template_id=checklist_template_id,
        )

    parse_result = parse_checklist_template_items(
        template.get("Items", ""), template.get("Required Items", ""), template.get("Optional Items", ""),
    )
    if not parse_result["ok"]:
        return _checklist_result(
            ok=False, code=parse_result["code"], error=parse_result["error"],
            business_id=business_id, checklist_template_id=checklist_template_id,
        )
    items = parse_result["items"]

    relation_result = _validate_checklist_relations(
        business_id, service_id=service_id, object_id=object_id, roadmap_id=roadmap_id, stage_id=stage_id,
    )
    if not relation_result["ok"]:
        return _checklist_result(
            ok=False, code=relation_result["code"], error=relation_result["error"],
            business_id=business_id, checklist_template_id=checklist_template_id,
        )
    resolved = relation_result["resolved"]

    matches = find_instances_by_idempotency_key(
        business_id, checklist_template_id, resolved["roadmap_id"], resolved["stage_id"],
        read_context=read_context,
    )
    if len(matches) > 1:
        conflicting_ids = tuple(m["Checklist Instance ID"] for m in matches)
        return _checklist_result(
            ok=False, code="MULTIPLE_CHECKLIST_INSTANCE_MATCHES",
            error=f"Найдено несколько Checklist Instance с этим ключом: {conflicting_ids}",
            business_id=business_id, checklist_template_id=checklist_template_id,
            conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _checklist_result(
            ok=True, code="CHECKLIST_INSTANCE_REUSED", error=None,
            checklist_instance_id=existing["Checklist Instance ID"], checklist_template_id=checklist_template_id,
            business_id=business_id, service_id=existing.get("Service ID", ""), object_id=existing.get("Object ID", ""),
            roadmap_id=existing.get("Roadmap ID", ""), stage_id=existing.get("Stage ID", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
            total_items=int(existing.get("Total Items") or 0), required_items=int(existing.get("Required Items") or 0),
            completed_items=int(existing.get("Completed Items") or 0),
            required_remaining=int(existing.get("Required Remaining") or 0),
        )

    initial_progress = _compute_checklist_progress([{"required": i["required"], "status": "pending"} for i in items])

    create_result = create_checklist_instance(
        business_id, checklist_template_id, template.get("Title", ""),
        service_id=resolved["service_id"], object_id=resolved["object_id"],
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        status="draft", total_items=initial_progress["total_items"], required_items=initial_progress["required_items"],
        completed_items=0, required_remaining=initial_progress["required_remaining"],
        created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _checklist_result(
            ok=False, code="CHECKLIST_PERSISTENCE_FAILED", error=create_result.get("error"),
            business_id=business_id, checklist_template_id=checklist_template_id, retry_safe=True,
        )
    instance_id = create_result["checklist_instance_id"]

    items_result = create_checklist_instance_items(instance_id, checklist_template_id, items)
    if not items_result["ok"]:
        return _checklist_result(
            ok=False, code="CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE", error=items_result.get("error"),
            checklist_instance_id=instance_id, business_id=business_id, checklist_template_id=checklist_template_id,
            created_item_ids=tuple(items_result.get("item_ids", ())), retry_safe=False,
        )

    saved_instance = find_checklist_instance_by_id(instance_id)
    saved_items = list_checklist_instance_items(instance_id=instance_id)
    if saved_instance is None or len(saved_items) != len(items):
        return _checklist_result(
            ok=False, code="CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED",
            error="Checklist Instance записан, но проверка после записи не прошла",
            checklist_instance_id=instance_id, business_id=business_id, checklist_template_id=checklist_template_id,
            created_item_ids=tuple(items_result["item_ids"]), retry_safe=False,
        )

    return _checklist_result(
        ok=True, code="CHECKLIST_INSTANCE_CREATED", error=None,
        checklist_instance_id=instance_id, checklist_template_id=checklist_template_id,
        business_id=business_id, service_id=resolved["service_id"], object_id=resolved["object_id"],
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        final_status="draft", created=True,
        total_items=initial_progress["total_items"], required_items=initial_progress["required_items"],
        completed_items=0, required_remaining=initial_progress["required_remaining"],
        created_item_ids=tuple(items_result["item_ids"]), retry_safe=True,
    )


def transition_checklist_item_status(
    checklist_instance_item_id: str, target_status: str,
    *, blocked_reason: str = "", skip_reason: str = "", completed_by: str = "",
) -> dict:
    """
    Phase 38C (ADR-021 §14/§17): the sole canonical Checklist Instance
    Item transition orchestration boundary. Never auto-completes the
    parent Instance — that remains a separate explicit transition
    (ADR-021 §18/§19).
    """
    from business_core.checklist_manager import (
        find_checklist_instance_item_by_id, update_checklist_instance_item_status,
        update_checklist_instance_progress, list_checklist_instance_items, CHECKLIST_ITEM_STATUS,
    )

    if not checklist_instance_item_id:
        return _checklist_result(ok=False, code="CHECKLIST_INSTANCE_ITEM_NOT_FOUND", error="checklist_instance_item_id обязателен")

    item = find_checklist_instance_item_by_id(checklist_instance_item_id)
    if item is None:
        return _checklist_result(
            ok=False, code="CHECKLIST_INSTANCE_ITEM_NOT_FOUND",
            error=f"Checklist Instance Item {checklist_instance_item_id} не найден",
            checklist_instance_item_id=checklist_instance_item_id,
        )

    instance_id = item.get("Checklist Instance ID", "")
    previous_status = item.get("Status", "")

    if target_status not in CHECKLIST_ITEM_STATUS:
        return _checklist_result(
            ok=False, code="INVALID_CHECKLIST_ITEM_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(CHECKLIST_ITEM_STATUS)}",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if previous_status in _CHECKLIST_ITEM_TERMINAL_STATUSES and target_status != previous_status:
        return _checklist_result(
            ok=False, code="CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION",
            error=f"Item {checklist_instance_item_id} имеет терминальный статус '{previous_status}' — обычное обновление не может его изменить. Требуется explicit reopen (не реализовано).",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    allowed_targets = _CHECKLIST_ITEM_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _checklist_result(
            ok=False, code="INVALID_CHECKLIST_ITEM_STATUS_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status == "blocked" and not blocked_reason:
        return _checklist_result(
            ok=False, code="CHECKLIST_ITEM_REASON_REQUIRED", error="Для статуса 'blocked' требуется Blocked Reason",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )
    if target_status in ("skipped", "not_applicable") and not skip_reason:
        return _checklist_result(
            ok=False, code="CHECKLIST_ITEM_REASON_REQUIRED", error=f"Для статуса '{target_status}' требуется Skip Reason",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )
    if target_status == "done" and not completed_by:
        return _checklist_result(
            ok=False, code="CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED", error="Для статуса 'done' требуется Completed By",
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    write_result = update_checklist_instance_item_status(
        checklist_instance_item_id, target_status,
        blocked_reason=blocked_reason if target_status == "blocked" else "",
        skip_reason=skip_reason if target_status in ("skipped", "not_applicable") else "",
        completed_at=(_now_utc_str() if target_status == "done" else ""),
        completed_by=(completed_by if target_status == "done" else ""),
    )
    if not write_result["ok"]:
        return _checklist_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]

    all_items = list_checklist_instance_items(instance_id=instance_id)
    progress = _compute_checklist_progress([
        {"required": (i.get("Required", "") == "true"), "status": i.get("Status", "")} for i in all_items
    ])
    update_checklist_instance_progress(
        instance_id, total_items=progress["total_items"], required_items=progress["required_items"],
        completed_items=progress["completed_items"], required_remaining=progress["required_remaining"],
    )

    return _checklist_result(
        ok=True, code="CHECKLIST_ITEM_STATUS_UPDATED" if changed else "CHECKLIST_ITEM_STATUS_UNCHANGED", error=None,
        checklist_instance_item_id=checklist_instance_item_id, checklist_instance_id=instance_id,
        previous_status=previous_status, requested_status=target_status, final_status=target_status, changed=changed,
        total_items=progress["total_items"], required_items=progress["required_items"],
        completed_items=progress["completed_items"], required_remaining=progress["required_remaining"],
        blocked_required=progress["blocked_required"],
    )


def transition_checklist_status(checklist_instance_id: str, target_status: str) -> dict:
    """
    Phase 38C (ADR-021 §13/§16/§19): the sole canonical Checklist
    Instance transition orchestration boundary. Never mutates Items,
    Stage, or Roadmap.
    """
    from business_core.checklist_manager import (
        find_checklist_instance_by_id, update_checklist_instance_status,
        list_checklist_instance_items, CHECKLIST_INSTANCE_STATUS,
    )

    if not checklist_instance_id:
        return _checklist_result(ok=False, code="CHECKLIST_INSTANCE_NOT_FOUND", error="checklist_instance_id обязателен")

    instance = find_checklist_instance_by_id(checklist_instance_id)
    if instance is None:
        return _checklist_result(
            ok=False, code="CHECKLIST_INSTANCE_NOT_FOUND", error=f"Checklist Instance {checklist_instance_id} не найден",
            checklist_instance_id=checklist_instance_id,
        )

    business_id = instance.get("Business ID", "")
    previous_status = instance.get("Status", "")

    if target_status not in CHECKLIST_INSTANCE_STATUS:
        return _checklist_result(
            ok=False, code="INVALID_CHECKLIST_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(CHECKLIST_INSTANCE_STATUS)}",
            checklist_instance_id=checklist_instance_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    allowed_targets = _CHECKLIST_INSTANCE_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))

    if previous_status in _CHECKLIST_INSTANCE_REOPEN_GATED_STATUSES and target_status not in allowed_targets:
        return _checklist_result(
            ok=False, code="CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION",
            error=(
                f"Checklist Instance {checklist_instance_id} имеет статус '{previous_status}' — обычное обновление "
                f"не может вернуть его в '{target_status}'. Требуется отдельное явное действие restore (не реализовано)."
            ),
            checklist_instance_id=checklist_instance_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status not in allowed_targets:
        return _checklist_result(
            ok=False, code="INVALID_CHECKLIST_STATUS_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            checklist_instance_id=checklist_instance_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    started_at = completed_at = cancelled_at = ""
    required_remaining_at_check = 0
    if target_status == "completed":
        items = list_checklist_instance_items(instance_id=checklist_instance_id)
        progress = _compute_checklist_progress([
            {"required": (i.get("Required", "") == "true"), "status": i.get("Status", "")} for i in items
        ])
        required_remaining_at_check = progress["required_remaining"]
        if not items or progress["required_remaining"] > 0:
            return _checklist_result(
                ok=False, code="CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET",
                error="Не все обязательные пункты Checklist завершены (done/not_applicable)",
                checklist_instance_id=checklist_instance_id, business_id=business_id,
                previous_status=previous_status, requested_status=target_status, final_status=previous_status,
                required_remaining=required_remaining_at_check,
            )
        completed_at = _now_utc_str()
    elif target_status == "in_progress" and previous_status != "in_progress":
        started_at = _now_utc_str()
    elif target_status == "cancelled":
        cancelled_at = _now_utc_str()

    write_result = update_checklist_instance_status(
        checklist_instance_id, target_status,
        started_at=started_at, completed_at=completed_at, cancelled_at=cancelled_at,
    )
    if not write_result["ok"]:
        return _checklist_result(
            ok=False, code=write_result.get("code") or "", error=write_result.get("error"),
            checklist_instance_id=checklist_instance_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _checklist_result(
        ok=True, code="CHECKLIST_STATUS_UPDATED" if changed else "CHECKLIST_STATUS_UNCHANGED", error=None,
        checklist_instance_id=checklist_instance_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status, final_status=target_status,
        changed=changed, completed=(target_status == "completed"),
    )


def update_checklist_admin_fields(checklist_instance_id: str, updates: dict) -> dict:
    """
    Phase 38C (ADR-021 §20/§26): the sole canonical Checklist Instance
    admin-field update orchestration boundary. Only Notes is
    ordinarily mutable — enforced by
    checklist_manager.update_checklist_instance_admin_fields() itself
    (this function is a thin resolve-then-delegate wrapper).
    """
    from business_core.checklist_manager import find_checklist_instance_by_id, update_checklist_instance_admin_fields

    if not checklist_instance_id:
        return _checklist_result(ok=False, code="CHECKLIST_INSTANCE_NOT_FOUND", error="checklist_instance_id обязателен")

    instance = find_checklist_instance_by_id(checklist_instance_id)
    if instance is None:
        return _checklist_result(
            ok=False, code="CHECKLIST_INSTANCE_NOT_FOUND", error=f"Checklist Instance {checklist_instance_id} не найден",
            checklist_instance_id=checklist_instance_id,
        )

    result = update_checklist_instance_admin_fields(checklist_instance_id, updates)
    return _checklist_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        checklist_instance_id=checklist_instance_id, business_id=instance.get("Business ID", ""),
        changed=result.get("changed", False), retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Phase 39C (ADR-022): Payment/Milestone Domain orchestration.
#
# business_builder.py is the sole cross-domain Payment orchestration
# owner: Template validation, amount/currency normalization, relation
# validation, Obligation creation, Transaction creation/confirmation/
# reversal, overpayment prevention, balance calculation, Obligation
# status synchronization, idempotency zero/one/multiple handling,
# structured result assembly. business_core.payment_manager.py
# (persistence) is called from here — never the reverse. No Telegram
# caller exists yet (Phase 39D); nothing here is called by
# telegram_handlers.py in this phase. COMMERCIAL_MILESTONES_MAP
# (roadmap_manager.py) and /milestones remain completely untouched —
# this is a wholly separate, new persistence layer (ADR-022 §24).
# ─────────────────────────────────────────────────────────────

from decimal import Decimal, InvalidOperation

_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

_COMMERCIAL_MILESTONE_TEMPLATE_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "active":   ("active", "inactive", "archived"),
    "inactive": ("inactive", "archived"),
    "archived": ("archived",),
}

_PAYMENT_OBLIGATION_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":          ("draft", "issued", "cancelled", "archived"),
    "issued":         ("issued", "cancelled", "archived"),
    "partially_paid": ("partially_paid", "cancelled", "archived"),
    "paid":           ("paid", "archived"),
    "cancelled":      ("cancelled", "archived"),
    "archived":       ("archived",),
}
_PAYMENT_OBLIGATION_SYNC_ONLY_STATUSES = frozenset({"partially_paid", "paid"})

_PAYMENT_TRANSACTION_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending":   ("pending", "confirmed", "failed"),
    "confirmed": ("confirmed", "reversed"),
    "reversed":  ("reversed",),
    "failed":    ("failed",),
}


def _payment_result(
    *, ok: bool, code: str, error: str | None,
    commercial_milestone_template_id: str = "", payment_obligation_id: str = "", payment_transaction_id: str = "",
    business_id: str = "", client_id: str = "", object_id: str = "", service_id: str = "",
    roadmap_id: str = "", stage_id: str = "", document_id: str = "",
    amount: str = "", currency: str = "", paid_amount: str = "", remaining_amount: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False,
    confirmed: bool = False, reversed: bool = False, completed: bool = False,
    conflicting_ids: tuple = (), warnings: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Payment orchestration function
    (ADR-022 §25/§32) — the stable, structured contract every caller
    reads instead of a bare exception or ad-hoc dict shape. Never
    carries a raw exception object or a raw Sheets row."""
    return {
        "ok": ok, "code": code, "error": error,
        "commercial_milestone_template_id": commercial_milestone_template_id,
        "payment_obligation_id": payment_obligation_id, "payment_transaction_id": payment_transaction_id,
        "business_id": business_id, "client_id": client_id, "object_id": object_id, "service_id": service_id,
        "roadmap_id": roadmap_id, "stage_id": stage_id, "document_id": document_id,
        "amount": amount, "currency": currency, "paid_amount": paid_amount, "remaining_amount": remaining_amount,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed,
        "confirmed": confirmed, "reversed": reversed, "completed": completed,
        "conflicting_ids": tuple(conflicting_ids), "warnings": tuple(warnings), "retry_safe": retry_safe,
    }


def normalize_payment_amount(raw) -> dict:
    """
    Phase 39C (ADR-022 §12/§9): the sole canonical Decimal amount
    normalization helper. Decimal only — float input rejected outright
    (money must never be represented as binary floating point).
    Canonical storage as a decimal string with exactly 2 fractional
    digits. No scientific notation, no thousands separators. An input
    with more than 2 fractional digits BLOCKS rather than being
    silently quantized away — this function never rounds a caller's
    input, it only re-serializes an already-2-decimal value.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "amount": Decimal | None, "normalized": str}
    """
    if isinstance(raw, float):
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Сумма не может быть float — используйте Decimal или строку", "amount": None, "normalized": ""}
    if raw is None or raw == "":
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Сумма обязательна", "amount": None, "normalized": ""}

    text = str(raw).strip()
    if not text:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Сумма обязательна", "amount": None, "normalized": ""}
    if "," in text:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Сумма не может содержать разделители тысяч (',')", "amount": None, "normalized": ""}
    if "e" in text.lower():
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Сумма не может использовать экспоненциальную запись", "amount": None, "normalized": ""}

    try:
        value = Decimal(text)
    except InvalidOperation:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": f"Не удаётся разобрать сумму '{raw}'", "amount": None, "normalized": ""}

    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT_SCALE", "error": "Сумма не может иметь более 2 знаков после запятой", "amount": None, "normalized": ""}

    if value <= 0:
        return {"ok": False, "code": "PAYMENT_AMOUNT_MUST_BE_POSITIVE", "error": "Сумма должна быть больше нуля", "amount": None, "normalized": ""}

    quantized = value.quantize(Decimal("0.01"))
    return {"ok": True, "code": "", "error": None, "amount": quantized, "normalized": str(quantized)}


def normalize_payment_currency(raw) -> dict:
    """
    Phase 39C (ADR-022 §13/§10): the sole canonical currency
    normalization helper. Required, uppercased, exactly 3 ASCII
    letters — no implicit default.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "currency": str}
    """
    if raw is None:
        return {"ok": False, "code": "INVALID_PAYMENT_CURRENCY", "error": "Валюта обязательна", "currency": ""}
    text = str(raw).strip().upper()
    if not text:
        return {"ok": False, "code": "INVALID_PAYMENT_CURRENCY", "error": "Валюта обязательна", "currency": ""}
    if not _CURRENCY_CODE_RE.match(text):
        return {"ok": False, "code": "INVALID_PAYMENT_CURRENCY", "error": f"Недопустимый код валюты '{raw}' — требуется 3 буквы ASCII в верхнем регистре", "currency": ""}
    return {"ok": True, "code": "", "error": None, "currency": text}


def _compute_payment_balance(obligation_amount: str, transactions: list[dict]) -> dict:
    """
    Phase 39C (ADR-022 §14/§21): canonical balance calculator. Paid
    Amount = sum of `confirmed`-status Transaction amounts only.
    pending/failed/reversed are excluded. No float — Decimal
    throughout. No caller-side calculation is ever performed outside
    this function.
    """
    from business_core.payment_manager import TRANSACTION_STATUS

    try:
        obligation_decimal = Decimal(obligation_amount or "0")
    except InvalidOperation:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Obligation Amount повреждён", "paid_amount": "", "remaining_amount": ""}

    paid_decimal = Decimal("0.00")
    for txn in transactions:
        status = txn.get("Status", "")
        if status not in TRANSACTION_STATUS:
            return {"ok": False, "code": "INVALID_PAYMENT_TRANSACTION_STATUS", "error": f"Неизвестный статус Transaction: '{status}'", "paid_amount": "", "remaining_amount": ""}
        if status == "confirmed":
            try:
                paid_decimal += Decimal(txn.get("Amount", "0"))
            except InvalidOperation:
                return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": f"Amount Transaction {txn.get('Payment Transaction ID', '')} повреждён", "paid_amount": "", "remaining_amount": ""}

    remaining_decimal = obligation_decimal - paid_decimal
    if remaining_decimal < 0:
        return {"ok": False, "code": "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED", "error": "Сумма подтверждённых платежей превышает Obligation Amount", "paid_amount": "", "remaining_amount": ""}

    return {
        "ok": True, "code": "", "error": None,
        "paid_amount": str(paid_decimal.quantize(Decimal("0.01"))),
        "remaining_amount": str(remaining_decimal.quantize(Decimal("0.01"))),
    }


def _synchronize_payment_obligation_after_transaction_change(payment_obligation_id: str) -> dict:
    """
    Phase 39C (ADR-022 §14/§22): recomputes Paid/Remaining Amount from
    every Transaction row belonging to this Obligation and synchronizes
    Obligation Status accordingly. Never called manually — only from
    confirm_payment_transaction()/reverse_payment_transaction() after
    their own write succeeds. `cancelled`/`archived` are protected —
    synchronization never overwrites those statuses. Bounded timestamp
    policy (ADR-022 §22): Paid At is cleared whenever the Obligation
    leaves `paid` (no separate payment-history table exists yet to
    otherwise preserve a meaningful "first paid" timestamp across a
    reversal).
    """
    from business_core.payment_manager import (
        find_payment_obligation_by_id, list_payment_transactions_strict, update_payment_obligation_balance,
    )

    obligation = find_payment_obligation_by_id(payment_obligation_id)
    if obligation is None:
        return {"ok": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": f"Payment Obligation {payment_obligation_id} не найден"}

    try:
        transactions = list_payment_transactions_strict(payment_obligation_id=payment_obligation_id)
    except Exception:
        # Phase 17E-2A6-H0: a failed ledger read must never be
        # converted to a computed balance from [] — that would
        # silently overwrite a correct Paid Amount/Status with zeroed
        # values that then pass post-write verification. Return
        # before any balance computation or Obligation write.
        return {"ok": False, "code": "PAYMENT_LEDGER_READ_FAILED", "error": "Infrastructure failure"}

    balance = _compute_payment_balance(obligation.get("Obligation Amount", "0"), transactions)
    if not balance["ok"]:
        return balance

    paid_amount = balance["paid_amount"]
    remaining_amount = balance["remaining_amount"]
    current_status = obligation.get("Status", "")

    try:
        paid_decimal = Decimal(paid_amount)
        obligation_decimal = Decimal(obligation.get("Obligation Amount", "0"))
    except InvalidOperation:
        return {"ok": False, "code": "INVALID_PAYMENT_AMOUNT", "error": "Не удалось разобрать сумму для синхронизации"}

    if current_status in ("cancelled", "archived"):
        new_status = current_status
    elif paid_decimal <= 0:
        new_status = "issued" if current_status in ("issued", "partially_paid", "paid") else current_status
    elif paid_decimal < obligation_decimal:
        new_status = "partially_paid"
    elif paid_decimal == obligation_decimal:
        new_status = "paid"
    else:
        return {"ok": False, "code": "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED", "error": "Paid Amount превышает Obligation Amount"}

    previously_paid_at = obligation.get("Paid At", "")
    clear_paid_at = bool(new_status != "paid" and previously_paid_at)
    paid_at = _now_utc_str() if (new_status == "paid" and not previously_paid_at) else ""

    write_result = update_payment_obligation_balance(
        payment_obligation_id, status=new_status, paid_amount=paid_amount, remaining_amount=remaining_amount,
        paid_at=paid_at, clear_paid_at=clear_paid_at,
    )
    if not write_result["ok"]:
        return {"ok": False, "code": "PAYMENT_PERSISTENCE_FAILED", "error": write_result.get("error")}

    verify = find_payment_obligation_by_id(payment_obligation_id)
    if (
        verify is None
        or verify.get("Paid Amount", "") != paid_amount
        or verify.get("Remaining Amount", "") != remaining_amount
        or verify.get("Status", "") != new_status
    ):
        return {"ok": False, "code": "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED", "error": "Не удалось верифицировать синхронизацию баланса Obligation"}

    return {"ok": True, "code": "", "error": None, "paid_amount": paid_amount, "remaining_amount": remaining_amount, "status": new_status}


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template
# ─────────────────────────────────────────────────────────────

def create_commercial_milestone_template(
    title: str, calculation_type: str,
    *, roadmap_template_id: str = "", service_id: str = "", description: str = "",
    sequence: int = 1, trigger_description: str = "",
    fixed_amount: str = "", percentage: str = "", currency: str = "",
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Phase 39C (ADR-022 §9/§10/§14): the sole canonical Commercial
    Milestone Template creation orchestration boundary. ADR-022 did not
    approve a caller-idempotency field for Templates, so identity is
    the exact normalized tuple (Roadmap Template ID, Service ID,
    Sequence, Title) — never fuzzy, never first-pick.
    """
    from business_core.payment_manager import (
        find_templates_by_identity, create_commercial_milestone_template as pm_create_template,
        find_commercial_milestone_template_by_id, CALCULATION_TYPES,
    )

    if not title:
        return _payment_result(ok=False, code="", error="title обязателен")
    if calculation_type not in CALCULATION_TYPES:
        return _payment_result(
            ok=False, code="INVALID_MILESTONE_CALCULATION_TYPE",
            error=f"Недопустимый Calculation Type '{calculation_type}'. Допустимые значения: {', '.join(CALCULATION_TYPES)}",
        )
    try:
        sequence_int = int(sequence)
    except (TypeError, ValueError):
        return _payment_result(ok=False, code="", error="sequence должен быть положительным целым числом")
    if sequence_int <= 0:
        return _payment_result(ok=False, code="", error="sequence должен быть положительным целым числом")

    if not roadmap_template_id and not service_id:
        return _payment_result(ok=False, code="PAYMENT_ENTITY_RELATION_MISMATCH", error="Требуется хотя бы одно: roadmap_template_id или service_id")

    if roadmap_template_id:
        from business_core.sheets import read_business_sheet
        roadmap_templates = read_business_sheet("roadmap_template_registry")
        if not any(t.get("Template ID", "") == roadmap_template_id for t in roadmap_templates):
            return _payment_result(ok=False, code="ROADMAP_NOT_FOUND", error=f"Roadmap Template {roadmap_template_id} не найден")

    if service_id:
        from business_core.service_manager import find_service_by_id
        svc = find_service_by_id(service_id)
        if svc is None:
            return _payment_result(ok=False, code="SERVICE_NOT_FOUND", error=f"Service {service_id} не найден")

    currency_result = normalize_payment_currency(currency)
    if not currency_result["ok"]:
        return _payment_result(ok=False, code=currency_result["code"], error=currency_result["error"])
    normalized_currency = currency_result["currency"]

    normalized_fixed_amount = ""
    normalized_percentage = ""

    if calculation_type == "fixed":
        if percentage:
            return _payment_result(ok=False, code="MILESTONE_CALCULATION_FIELDS_CONFLICT", error="Percentage должен быть пуст для Calculation Type='fixed'")
        if not fixed_amount:
            return _payment_result(ok=False, code="MILESTONE_FIXED_AMOUNT_REQUIRED", error="Fixed Amount обязателен для Calculation Type='fixed'")
        amount_result = normalize_payment_amount(fixed_amount)
        if not amount_result["ok"]:
            return _payment_result(ok=False, code=amount_result["code"], error=amount_result["error"])
        normalized_fixed_amount = amount_result["normalized"]
    else:
        if fixed_amount:
            return _payment_result(ok=False, code="MILESTONE_CALCULATION_FIELDS_CONFLICT", error="Fixed Amount должен быть пуст для Calculation Type='percentage'")
        if not percentage:
            return _payment_result(ok=False, code="MILESTONE_PERCENTAGE_REQUIRED", error="Percentage обязателен для Calculation Type='percentage'")
        try:
            percentage_decimal = Decimal(str(percentage).strip())
        except InvalidOperation:
            return _payment_result(ok=False, code="MILESTONE_PERCENTAGE_REQUIRED", error=f"Не удаётся разобрать Percentage '{percentage}'")
        if percentage_decimal <= 0 or percentage_decimal > 100:
            return _payment_result(ok=False, code="MILESTONE_PERCENTAGE_REQUIRED", error="Percentage должен быть в диапазоне (0, 100]")
        normalized_percentage = str(percentage_decimal)

    matches = find_templates_by_identity(roadmap_template_id, service_id, str(sequence_int), title)
    if len(matches) > 1:
        conflicting_ids = tuple(m["Commercial Milestone Template ID"] for m in matches)
        return _payment_result(
            ok=False, code="MULTIPLE_COMMERCIAL_MILESTONE_TEMPLATE_MATCHES",
            error=f"Найдено несколько Commercial Milestone Template с этим ключом: {conflicting_ids}",
            conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _payment_result(
            ok=True, code="COMMERCIAL_MILESTONE_TEMPLATE_REUSED", error=None,
            commercial_milestone_template_id=existing["Commercial Milestone Template ID"],
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    create_result = pm_create_template(
        title, calculation_type,
        roadmap_template_id=roadmap_template_id, service_id=service_id, description=description,
        sequence=sequence_int, trigger_description=trigger_description,
        fixed_amount=normalized_fixed_amount, percentage=normalized_percentage, currency=normalized_currency,
        status="active", created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _payment_result(ok=False, code=create_result.get("code") or "PAYMENT_PERSISTENCE_FAILED", error=create_result.get("error"), retry_safe=True)
    template_id = create_result["commercial_milestone_template_id"]

    saved = find_commercial_milestone_template_by_id(template_id)
    if saved is None:
        return _payment_result(
            ok=False, code="COMMERCIAL_MILESTONE_TEMPLATE_POST_WRITE_VERIFICATION_FAILED",
            error="Commercial Milestone Template записан, но проверка после записи не прошла",
            commercial_milestone_template_id=template_id, retry_safe=False,
        )

    return _payment_result(
        ok=True, code="COMMERCIAL_MILESTONE_TEMPLATE_CREATED", error=None,
        commercial_milestone_template_id=template_id, currency=normalized_currency,
        amount=normalized_fixed_amount, final_status="active", created=True, retry_safe=True,
    )


def update_commercial_milestone_template_admin_fields(commercial_milestone_template_id: str, updates: dict) -> dict:
    """Phase 39C (ADR-022 §25): thin resolve-then-delegate wrapper.
    Only Description/Trigger Description/Notes are ordinarily mutable
    — enforced by payment_manager.update_commercial_milestone_template_
    admin_fields() itself."""
    from business_core.payment_manager import find_commercial_milestone_template_by_id, update_commercial_milestone_template_admin_fields as pm_update_admin

    if not commercial_milestone_template_id:
        return _payment_result(ok=False, code="COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", error="commercial_milestone_template_id обязателен")

    template = find_commercial_milestone_template_by_id(commercial_milestone_template_id)
    if template is None:
        return _payment_result(ok=False, code="COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", error=f"Commercial Milestone Template {commercial_milestone_template_id} не найден", commercial_milestone_template_id=commercial_milestone_template_id)

    result = pm_update_admin(commercial_milestone_template_id, updates)
    return _payment_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        commercial_milestone_template_id=commercial_milestone_template_id, changed=result.get("changed", False), retry_safe=True,
    )


def transition_commercial_milestone_template_status(commercial_milestone_template_id: str, target_status: str) -> dict:
    """Phase 39C (ADR-022 §16): the sole canonical Commercial Milestone
    Template transition orchestration boundary. No restore
    implementation — attempting inactive/archived → active blocks with
    an explicit restore-required code rather than a generic invalid-
    transition message."""
    from business_core.payment_manager import find_commercial_milestone_template_by_id, update_commercial_milestone_template_status, TEMPLATE_STATUS

    if not commercial_milestone_template_id:
        return _payment_result(ok=False, code="COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", error="commercial_milestone_template_id обязателен")

    template = find_commercial_milestone_template_by_id(commercial_milestone_template_id)
    if template is None:
        return _payment_result(ok=False, code="COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", error=f"Commercial Milestone Template {commercial_milestone_template_id} не найден", commercial_milestone_template_id=commercial_milestone_template_id)

    previous_status = template.get("Status", "")

    if target_status not in TEMPLATE_STATUS:
        return _payment_result(
            ok=False, code="INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(TEMPLATE_STATUS)}",
            commercial_milestone_template_id=commercial_milestone_template_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status == previous_status:
        return _payment_result(
            ok=True, code="COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UNCHANGED", error=None,
            commercial_milestone_template_id=commercial_milestone_template_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status, changed=False,
        )

    allowed_targets = _COMMERCIAL_MILESTONE_TEMPLATE_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        code = "COMMERCIAL_MILESTONE_TEMPLATE_RESTORE_REQUIRES_EXPLICIT_ACTION" if target_status == "active" else "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS"
        return _payment_result(
            ok=False, code=code,
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            commercial_milestone_template_id=commercial_milestone_template_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    write_result = update_commercial_milestone_template_status(commercial_milestone_template_id, target_status)
    if not write_result["ok"]:
        return _payment_result(
            ok=False, code=write_result.get("code") or "PAYMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            commercial_milestone_template_id=commercial_milestone_template_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _payment_result(
        ok=True, code="COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UPDATED" if changed else "COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UNCHANGED", error=None,
        commercial_milestone_template_id=commercial_milestone_template_id,
        previous_status=previous_status, requested_status=target_status, final_status=target_status, changed=changed,
    )


# ─────────────────────────────────────────────────────────────
# Payment Obligation
# ─────────────────────────────────────────────────────────────

def _validate_payment_obligation_relations(
    business_id: str, client_id: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "", stage_id: str = "",
    commercial_milestone_template_id: str = "",
) -> dict:
    """
    Phase 39C (ADR-022 §18/§13): canonical cross-domain Payment
    Obligation relation-validation path, all before any write.
    Resolution order is most-specific-first (Stage, then Roadmap,
    deriving Object/Service) — mirrors _validate_checklist_relations()/
    document_registry_manager.resolve_and_validate_links() exactly,
    applied to Payment's own relation set plus Client validation.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "resolved": dict | None}
    """
    from business_core.sheets import read_business_sheet

    if not business_id:
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен", "resolved": None}
    biz_rows = read_business_sheet("biz_registry")
    if not any(b.get("ID", "") == business_id for b in biz_rows):
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": f"Business {business_id} не найден", "resolved": None}

    if not client_id:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": "client_id обязателен", "resolved": None}

    from business_core.person_manager import find_person_by_id, is_person_archived, is_client_person, has_person_business_link
    client = find_person_by_id(client_id)
    if client is None:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} не найден", "resolved": None}
    if is_person_archived(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} архивирован", "resolved": None}
    if not is_client_person(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"{client_id} не является Client", "resolved": None}
    if not has_person_business_link(client, business_id):
        return {"ok": False, "code": "PAYMENT_ENTITY_RELATION_MISMATCH", "error": f"Client {client_id} не связан с Business {business_id}", "resolved": None}

    resolved_stage_id = stage_id
    resolved_roadmap_id = roadmap_id
    resolved_object_id = object_id
    resolved_service_id = service_id

    if resolved_stage_id:
        stages = read_business_sheet("roadmap_stages")
        stage = next((s for s in stages if s.get("Stage ID", "") == resolved_stage_id), None)
        if stage is None:
            return {"ok": False, "code": "STAGE_NOT_FOUND", "error": f"Stage {resolved_stage_id} не найден", "resolved": None}
        stage_roadmap_id = stage.get("Roadmap ID", "")
        if resolved_roadmap_id and stage_roadmap_id and resolved_roadmap_id != stage_roadmap_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Stage {resolved_stage_id} принадлежит Roadmap {stage_roadmap_id}, а указан Roadmap {resolved_roadmap_id}",
                "resolved": None,
            }
        resolved_roadmap_id = resolved_roadmap_id or stage_roadmap_id

    if resolved_roadmap_id:
        roadmaps = read_business_sheet("roadmaps")
        rm = next((r for r in roadmaps if r.get("Roadmap ID", "") == resolved_roadmap_id), None)
        if rm is None:
            return {"ok": False, "code": "ROADMAP_NOT_FOUND", "error": f"Roadmap {resolved_roadmap_id} не найден", "resolved": None}
        rm_biz_id = rm.get("Business ID", "")
        if rm_biz_id and rm_biz_id != business_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} принадлежит бизнесу {rm_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }
        rm_object_id = rm.get("Object ID", "")
        if resolved_object_id and rm_object_id and resolved_object_id != rm_object_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Object {rm_object_id}, а указан Object {resolved_object_id}",
                "resolved": None,
            }
        resolved_object_id = resolved_object_id or rm_object_id
        rm_service_id = rm.get("Service ID", "")
        if resolved_service_id and rm_service_id and resolved_service_id != rm_service_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Service {rm_service_id}, а указан Service {resolved_service_id}",
                "resolved": None,
            }
        resolved_service_id = resolved_service_id or rm_service_id

    if resolved_object_id:
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(resolved_object_id)
        if obj is None:
            return {"ok": False, "code": "OBJECT_NOT_FOUND", "error": f"Object {resolved_object_id} не найден", "resolved": None}
        obj_biz_id = obj.get("biz_id", "")
        if obj_biz_id and obj_biz_id != business_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Object {resolved_object_id} принадлежит бизнесу {obj_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    if resolved_service_id:
        from business_core.service_manager import find_service_by_id
        svc = find_service_by_id(resolved_service_id)
        if svc is None:
            return {"ok": False, "code": "SERVICE_NOT_FOUND", "error": f"Service {resolved_service_id} не найден", "resolved": None}
        svc_biz_id = svc.get("biz_id", "")
        if svc_biz_id and svc_biz_id != business_id:
            return {
                "ok": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
                "error": f"Service {resolved_service_id} принадлежит бизнесу {svc_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    resolved_template_id = commercial_milestone_template_id
    if resolved_template_id:
        from business_core.payment_manager import find_commercial_milestone_template_by_id
        tmpl = find_commercial_milestone_template_by_id(resolved_template_id)
        if tmpl is None:
            return {"ok": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": f"Commercial Milestone Template {resolved_template_id} не найден", "resolved": None}

    return {
        "ok": True, "code": "", "error": None,
        "resolved": {
            "business_id": business_id, "client_id": client_id,
            "object_id": resolved_object_id, "service_id": resolved_service_id,
            "roadmap_id": resolved_roadmap_id, "stage_id": resolved_stage_id,
            "commercial_milestone_template_id": resolved_template_id,
        },
    }


def create_payment_obligation(
    business_id: str, client_id: str, obligation_amount, currency: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "", stage_id: str = "",
    commercial_milestone_template_id: str = "", caller_idempotency_key: str = "",
    title: str = "", description: str = "", due_date: str = "",
    created_by: str = "", notes: str = "", obligation_sequence: str = "",
) -> dict:
    """
    Phase 39C (ADR-022 §11/§16/§19): the sole canonical Payment
    Obligation creation orchestration boundary.

    Validation order, all before any write:
      A. required business_id / client_id
      B. amount/currency normalization
      C. idempotency-source precondition (caller key, OR a complete
         Template+Roadmap+Stage+Sequence fallback tuple)
      D. Client + relation validation (+ Template existence if supplied)
      E. idempotency lookup (zero/one/multiple)
      F. Obligation ID generated only after A-E pass
      G. low-level persistence
      H. post-write verification
      I. structured result
    """
    from business_core.payment_manager import (
        find_obligations_by_caller_key, find_obligations_by_template_fallback_key,
        create_payment_obligation as pm_create_obligation, find_payment_obligation_by_id,
    )

    if not business_id:
        return _payment_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not client_id:
        return _payment_result(ok=False, code="CLIENT_NOT_FOUND", error="client_id обязателен", business_id=business_id)

    amount_result = normalize_payment_amount(obligation_amount)
    if not amount_result["ok"]:
        return _payment_result(ok=False, code=amount_result["code"], error=amount_result["error"], business_id=business_id, client_id=client_id)
    normalized_amount = amount_result["normalized"]

    currency_result = normalize_payment_currency(currency)
    if not currency_result["ok"]:
        return _payment_result(ok=False, code=currency_result["code"], error=currency_result["error"], business_id=business_id, client_id=client_id)
    normalized_currency = currency_result["currency"]

    has_template_fallback = bool(commercial_milestone_template_id and roadmap_id and stage_id and obligation_sequence)
    if not caller_idempotency_key and not has_template_fallback:
        return _payment_result(
            ok=False, code="PAYMENT_OBLIGATION_IDEMPOTENCY_CONFLICT",
            error="Требуется caller_idempotency_key либо полный Template+Roadmap+Stage+Sequence fallback",
            business_id=business_id, client_id=client_id,
        )

    relation_result = _validate_payment_obligation_relations(
        business_id, client_id, object_id=object_id, service_id=service_id,
        roadmap_id=roadmap_id, stage_id=stage_id, commercial_milestone_template_id=commercial_milestone_template_id,
    )
    if not relation_result["ok"]:
        return _payment_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id, client_id=client_id)
    resolved = relation_result["resolved"]

    if caller_idempotency_key:
        matches = find_obligations_by_caller_key(business_id, caller_idempotency_key)
    else:
        matches = find_obligations_by_template_fallback_key(
            business_id, resolved["commercial_milestone_template_id"], resolved["roadmap_id"], resolved["stage_id"],
        )

    if len(matches) > 1:
        conflicting_ids = tuple(m["Payment Obligation ID"] for m in matches)
        return _payment_result(
            ok=False, code="MULTIPLE_PAYMENT_OBLIGATION_MATCHES",
            error=f"Найдено несколько Payment Obligation с этим ключом: {conflicting_ids}",
            business_id=business_id, client_id=client_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _payment_result(
            ok=True, code="PAYMENT_OBLIGATION_REUSED", error=None,
            payment_obligation_id=existing["Payment Obligation ID"], business_id=business_id, client_id=client_id,
            object_id=existing.get("Object ID", ""), service_id=existing.get("Service ID", ""),
            roadmap_id=existing.get("Roadmap ID", ""), stage_id=existing.get("Stage ID", ""),
            commercial_milestone_template_id=existing.get("Commercial Milestone Template ID", ""),
            amount=existing.get("Obligation Amount", ""), currency=existing.get("Currency", ""),
            paid_amount=existing.get("Paid Amount", ""), remaining_amount=existing.get("Remaining Amount", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    create_result = pm_create_obligation(
        business_id, client_id, normalized_amount, normalized_currency,
        object_id=resolved["object_id"], service_id=resolved["service_id"],
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        commercial_milestone_template_id=resolved["commercial_milestone_template_id"],
        caller_idempotency_key=caller_idempotency_key,
        title_snapshot=title, description_snapshot=description, due_date=due_date,
        created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_PERSISTENCE_FAILED", error=create_result.get("error"), business_id=business_id, client_id=client_id, retry_safe=True)
    obligation_id = create_result["payment_obligation_id"]

    saved = find_payment_obligation_by_id(obligation_id)
    if saved is None:
        return _payment_result(
            ok=False, code="PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED",
            error="Payment Obligation записан, но проверка после записи не прошла",
            payment_obligation_id=obligation_id, business_id=business_id, client_id=client_id, retry_safe=False,
        )

    return _payment_result(
        ok=True, code="PAYMENT_OBLIGATION_CREATED", error=None,
        payment_obligation_id=obligation_id, business_id=business_id, client_id=client_id,
        object_id=resolved["object_id"], service_id=resolved["service_id"],
        roadmap_id=resolved["roadmap_id"], stage_id=resolved["stage_id"],
        commercial_milestone_template_id=resolved["commercial_milestone_template_id"],
        amount=normalized_amount, currency=normalized_currency,
        paid_amount="0.00", remaining_amount=normalized_amount,
        final_status="draft", created=True, retry_safe=True,
    )


def transition_payment_obligation_status(payment_obligation_id: str, target_status: str) -> dict:
    """
    Phase 39C (ADR-022 §17/§22): the sole canonical Payment Obligation
    manual-transition orchestration boundary. Ordinary manual calls can
    never set partially_paid/paid — those are synchronized only from
    Transaction truth via _synchronize_payment_obligation_after_
    transaction_change(). Cancellation blocks when Paid Amount > 0.
    """
    from business_core.payment_manager import find_payment_obligation_by_id, update_payment_obligation_status, OBLIGATION_STATUS

    if not payment_obligation_id:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error="payment_obligation_id обязателен")

    obligation = find_payment_obligation_by_id(payment_obligation_id)
    if obligation is None:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error=f"Payment Obligation {payment_obligation_id} не найден", payment_obligation_id=payment_obligation_id)

    business_id = obligation.get("Business ID", "")
    previous_status = obligation.get("Status", "")
    paid_amount = obligation.get("Paid Amount", "0.00")

    if target_status not in OBLIGATION_STATUS:
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_OBLIGATION_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(OBLIGATION_STATUS)}",
            payment_obligation_id=payment_obligation_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status in _PAYMENT_OBLIGATION_SYNC_ONLY_STATUSES:
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_OBLIGATION_TRANSITION",
            error=f"Статус '{target_status}' устанавливается только автоматической синхронизацией баланса, не обычным переходом",
            payment_obligation_id=payment_obligation_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status == previous_status:
        return _payment_result(
            ok=True, code="PAYMENT_OBLIGATION_STATUS_UNCHANGED", error=None,
            payment_obligation_id=payment_obligation_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status, changed=False,
        )

    allowed_targets = _PAYMENT_OBLIGATION_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_OBLIGATION_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            payment_obligation_id=payment_obligation_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status == "cancelled":
        try:
            paid_decimal = Decimal(paid_amount or "0")
        except InvalidOperation:
            paid_decimal = Decimal("0")
        if paid_decimal > 0:
            return _payment_result(
                ok=False, code="PAYMENT_OBLIGATION_HAS_CONFIRMED_PAYMENTS",
                error=f"Payment Obligation {payment_obligation_id} имеет подтверждённые платежи (Paid Amount={paid_amount}) — отмена заблокирована",
                payment_obligation_id=payment_obligation_id, business_id=business_id,
                previous_status=previous_status, requested_status=target_status, final_status=previous_status,
                paid_amount=paid_amount,
            )

    issued_at = _now_utc_str() if (target_status == "issued" and previous_status != "issued") else ""
    cancelled_at = _now_utc_str() if target_status == "cancelled" else ""

    write_result = update_payment_obligation_status(payment_obligation_id, target_status, issued_at=issued_at, cancelled_at=cancelled_at)
    if not write_result["ok"]:
        return _payment_result(
            ok=False, code=write_result.get("code") or "PAYMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            payment_obligation_id=payment_obligation_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _payment_result(
        ok=True, code="PAYMENT_OBLIGATION_STATUS_UPDATED" if changed else "PAYMENT_OBLIGATION_STATUS_UNCHANGED", error=None,
        payment_obligation_id=payment_obligation_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status, final_status=target_status, changed=changed,
    )


def update_payment_obligation_admin_fields(payment_obligation_id: str, updates: dict) -> dict:
    """Phase 39C (ADR-022 §25): thin resolve-then-delegate wrapper.
    Only Notes is ordinarily mutable."""
    from business_core.payment_manager import find_payment_obligation_by_id, update_payment_obligation_admin_fields as pm_update_admin

    if not payment_obligation_id:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error="payment_obligation_id обязателен")

    obligation = find_payment_obligation_by_id(payment_obligation_id)
    if obligation is None:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error=f"Payment Obligation {payment_obligation_id} не найден", payment_obligation_id=payment_obligation_id)

    result = pm_update_admin(payment_obligation_id, updates)
    return _payment_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        payment_obligation_id=payment_obligation_id, business_id=obligation.get("Business ID", ""),
        changed=result.get("changed", False), retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Payment Transaction
# ─────────────────────────────────────────────────────────────

def create_payment_transaction(
    business_id: str, payment_obligation_id: str, client_id: str, amount, currency: str, payment_date: str,
    *, payment_method: str = "", external_transaction_id: str = "", caller_idempotency_key: str = "",
    evidence_document_id: str = "", created_by: str = "", notes: str = "",
) -> dict:
    """
    Phase 39C (ADR-022 §15/§20/§21): the sole canonical Payment
    Transaction creation orchestration boundary. Never confirms during
    creation — Status is always `pending` (ADR-022 §15).
    """
    from business_core.payment_manager import (
        find_payment_obligation_by_id, find_transactions_by_external_id, find_transactions_by_caller_key,
        create_payment_transaction as pm_create_transaction, find_payment_transaction_by_id,
    )

    if not business_id:
        return _payment_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not payment_obligation_id:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error="payment_obligation_id обязателен", business_id=business_id)
    if not client_id:
        return _payment_result(ok=False, code="CLIENT_NOT_FOUND", error="client_id обязателен", business_id=business_id)
    if not payment_date:
        return _payment_result(ok=False, code="", error="payment_date обязателен", business_id=business_id)
    if not external_transaction_id and not caller_idempotency_key:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED",
            error="Требуется external_transaction_id или caller_idempotency_key",
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
        )

    amount_result = normalize_payment_amount(amount)
    if not amount_result["ok"]:
        return _payment_result(ok=False, code=amount_result["code"], error=amount_result["error"], business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id)
    normalized_amount = amount_result["normalized"]

    currency_result = normalize_payment_currency(currency)
    if not currency_result["ok"]:
        return _payment_result(ok=False, code=currency_result["code"], error=currency_result["error"], business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id)
    normalized_currency = currency_result["currency"]

    obligation = find_payment_obligation_by_id(payment_obligation_id)
    if obligation is None:
        return _payment_result(ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error=f"Payment Obligation {payment_obligation_id} не найден", business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id)

    if obligation.get("Business ID", "") != business_id:
        return _payment_result(
            ok=False, code="PAYMENT_ENTITY_RELATION_MISMATCH",
            error=f"Payment Obligation {payment_obligation_id} принадлежит другому Business",
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
        )
    if obligation.get("Client ID", "") != client_id:
        return _payment_result(
            ok=False, code="PAYMENT_ENTITY_RELATION_MISMATCH",
            error=f"Client {client_id} не совпадает с плательщиком Obligation ({obligation.get('Client ID', '')})",
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
        )
    if obligation.get("Currency", "") != normalized_currency:
        return _payment_result(
            ok=False, code="PAYMENT_CURRENCY_MISMATCH",
            error=f"Валюта Transaction ({normalized_currency}) не совпадает с валютой Obligation ({obligation.get('Currency', '')})",
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
        )

    if evidence_document_id:
        from business_core.document_manager import find_document_by_id
        doc = find_document_by_id(evidence_document_id)
        if doc is None:
            return _payment_result(ok=False, code="DOCUMENT_NOT_FOUND", error=f"Document {evidence_document_id} не найден", business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id)
        if doc.get("business_id", "") != business_id:
            return _payment_result(
                ok=False, code="PAYMENT_ENTITY_RELATION_MISMATCH",
                error=f"Document {evidence_document_id} принадлежит другому Business",
                business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
            )

    if external_transaction_id:
        matches = find_transactions_by_external_id(business_id, external_transaction_id)
    else:
        matches = find_transactions_by_caller_key(business_id, caller_idempotency_key)

    if len(matches) > 1:
        conflicting_ids = tuple(m["Payment Transaction ID"] for m in matches)
        return _payment_result(
            ok=False, code="MULTIPLE_PAYMENT_TRANSACTION_MATCHES",
            error=f"Найдено несколько Payment Transaction с этим ключом: {conflicting_ids}",
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
            conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        existing_compatible = (
            existing.get("Payment Obligation ID", "") == payment_obligation_id
            and existing.get("Amount", "") == normalized_amount
            and existing.get("Currency", "") == normalized_currency
        )
        if not existing_compatible:
            return _payment_result(
                ok=False, code="PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT",
                error=f"Ключ идемпотентности уже используется другим Payment Transaction ({existing.get('Payment Transaction ID', '')}) с иными параметрами",
                business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id,
                conflicting_ids=(existing.get("Payment Transaction ID", ""),), retry_safe=True,
            )
        return _payment_result(
            ok=True, code="PAYMENT_TRANSACTION_REUSED", error=None,
            payment_transaction_id=existing["Payment Transaction ID"], business_id=business_id,
            payment_obligation_id=payment_obligation_id, client_id=client_id,
            amount=existing.get("Amount", ""), currency=existing.get("Currency", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    create_result = pm_create_transaction(
        business_id, payment_obligation_id, client_id, normalized_amount, normalized_currency, payment_date,
        payment_method=payment_method, external_transaction_id=external_transaction_id,
        caller_idempotency_key=caller_idempotency_key, evidence_document_id=evidence_document_id,
        created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _payment_result(
            ok=False, code=create_result.get("code") or "PAYMENT_TRANSACTION_PERSISTENCE_FAILED", error=create_result.get("error"),
            business_id=business_id, payment_obligation_id=payment_obligation_id, client_id=client_id, retry_safe=True,
        )
    transaction_id = create_result["payment_transaction_id"]

    saved = find_payment_transaction_by_id(transaction_id)
    if saved is None:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED",
            error="Payment Transaction записан, но проверка после записи не прошла",
            payment_transaction_id=transaction_id, business_id=business_id, payment_obligation_id=payment_obligation_id,
            client_id=client_id, retry_safe=False,
        )

    return _payment_result(
        ok=True, code="PAYMENT_TRANSACTION_CREATED", error=None,
        payment_transaction_id=transaction_id, business_id=business_id, payment_obligation_id=payment_obligation_id,
        client_id=client_id, amount=normalized_amount, currency=normalized_currency,
        final_status="pending", created=True, retry_safe=True,
    )


def confirm_payment_transaction(payment_transaction_id: str, confirmed_by: str) -> dict:
    """
    Phase 39C (ADR-022 §17/§18/§22): the sole canonical Payment
    Transaction confirmation orchestration boundary. Recomputes the
    Obligation balance EXCLUDING this Transaction first, then checks
    whether confirming it would overpay — blocks rather than silently
    allowing. On success, synchronizes the Obligation's cached balance/
    status from the full Transaction ledger.
    """
    from business_core.payment_manager import (
        find_payment_transaction_by_id, find_payment_obligation_by_id,
        update_payment_transaction_status,
    )

    if not payment_transaction_id:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error="payment_transaction_id обязателен")

    txn = find_payment_transaction_by_id(payment_transaction_id)
    if txn is None:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error=f"Payment Transaction {payment_transaction_id} не найден", payment_transaction_id=payment_transaction_id)

    business_id = txn.get("Business ID", "")
    obligation_id = txn.get("Payment Obligation ID", "")
    previous_status = txn.get("Status", "")

    if previous_status == "confirmed":
        return _payment_result(
            ok=True, code="PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", error=None,
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status,
            changed=False, confirmed=True,
        )
    if previous_status != "pending":
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_TRANSACTION_TRANSITION",
            error=f"Transaction {payment_transaction_id} имеет статус '{previous_status}' — подтверждение возможно только из 'pending'",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status,
        )
    if not confirmed_by:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_CONFIRMATION_METADATA_REQUIRED", error="confirmed_by обязателен",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status,
        )

    obligation = find_payment_obligation_by_id(obligation_id)
    if obligation is None:
        return _payment_result(
            ok=False, code="PAYMENT_OBLIGATION_NOT_FOUND", error=f"Payment Obligation {obligation_id} не найден",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        )

    from business_core.payment_manager import list_payment_transactions_strict

    try:
        ledger = list_payment_transactions_strict(payment_obligation_id=obligation_id)
    except Exception:
        # Phase 17E-2A6-H0: a failed ledger read must never be
        # silently treated as "no other transactions" — that would
        # artificially inflate the remaining balance and could let a
        # real overpayment through. Fail closed before any write.
        return _payment_result(
            ok=False, code="PAYMENT_LEDGER_READ_FAILED", error="Infrastructure failure",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status,
            changed=False, retry_safe=True,
        )

    other_transactions = [
        t for t in ledger
        if t.get("Payment Transaction ID", "") != payment_transaction_id
    ]
    balance_before = _compute_payment_balance(obligation.get("Obligation Amount", "0"), other_transactions)
    if not balance_before["ok"]:
        return _payment_result(
            ok=False, code=balance_before["code"], error=balance_before["error"],
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        )

    try:
        remaining_before = Decimal(balance_before["remaining_amount"])
        txn_amount = Decimal(txn.get("Amount", "0"))
    except InvalidOperation:
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_AMOUNT", error="Не удалось разобрать сумму Transaction",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        )

    if txn_amount > remaining_before:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED",
            error=f"Подтверждение Transaction на сумму {txn_amount} превысит Remaining Amount ({remaining_before})",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            amount=str(txn_amount), remaining_amount=str(remaining_before),
        )

    now = _now_utc_str()
    write_result = update_payment_transaction_status(payment_transaction_id, "confirmed", confirmed_at=now, confirmed_by=confirmed_by)
    if not write_result["ok"]:
        return _payment_result(
            ok=False, code="PAYMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status,
        )

    verify_txn = find_payment_transaction_by_id(payment_transaction_id)
    if verify_txn is None or verify_txn.get("Status", "") != "confirmed":
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED",
            error="Transaction помечен confirmed, но проверка после записи не прошла",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status=previous_status, retry_safe=False,
        )

    sync_result = _synchronize_payment_obligation_after_transaction_change(obligation_id)
    if not sync_result["ok"]:
        return _payment_result(
            ok=False, code="PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED",
            error=f"Transaction подтверждён, но синхронизация баланса Obligation не удалась: {sync_result.get('error')}",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="confirmed", final_status="confirmed",
            confirmed=True, changed=True, retry_safe=False,
        )

    return _payment_result(
        ok=True, code="PAYMENT_TRANSACTION_CONFIRMED", error=None,
        payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        amount=txn.get("Amount", ""), currency=txn.get("Currency", ""),
        paid_amount=sync_result["paid_amount"], remaining_amount=sync_result["remaining_amount"],
        previous_status=previous_status, requested_status="confirmed", final_status="confirmed",
        changed=True, confirmed=True, retry_safe=True,
    )


def reverse_payment_transaction(payment_transaction_id: str, reversal_reason: str, reversed_by: str) -> dict:
    """
    Phase 39C (ADR-022 §13/§19/§22): the sole canonical Payment
    Transaction reversal orchestration boundary. Status-based reversal
    on the original row — never a second offsetting Transaction row.
    Financial fields (Amount/Currency/Payment Date) are verified
    unchanged after the write, as a structural immutability guarantee.
    """
    from business_core.payment_manager import find_payment_transaction_by_id, update_payment_transaction_status

    if not payment_transaction_id:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error="payment_transaction_id обязателен")

    txn = find_payment_transaction_by_id(payment_transaction_id)
    if txn is None:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error=f"Payment Transaction {payment_transaction_id} не найден", payment_transaction_id=payment_transaction_id)

    business_id = txn.get("Business ID", "")
    obligation_id = txn.get("Payment Obligation ID", "")
    previous_status = txn.get("Status", "")

    if previous_status == "reversed":
        return _payment_result(
            ok=True, code="PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", error=None,
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status,
            changed=False, reversed=True,
        )
    if previous_status != "confirmed":
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_TRANSACTION_TRANSITION",
            error=f"Transaction {payment_transaction_id} имеет статус '{previous_status}' — реверс возможен только из 'confirmed'",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status,
        )
    if not reversal_reason:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED", error="reversal_reason обязателен",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status,
        )
    if not reversed_by:
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED", error="reversed_by обязателен",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status,
        )

    now = _now_utc_str()
    write_result = update_payment_transaction_status(
        payment_transaction_id, "reversed", reversed_at=now, reversed_by=reversed_by, reversal_reason=reversal_reason,
    )
    if not write_result["ok"]:
        return _payment_result(
            ok=False, code="PAYMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status,
        )

    verify_txn = find_payment_transaction_by_id(payment_transaction_id)
    if verify_txn is None or verify_txn.get("Status", "") != "reversed":
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED",
            error="Transaction помечен reversed, но проверка после записи не прошла",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status, retry_safe=False,
        )
    if (
        verify_txn.get("Amount", "") != txn.get("Amount", "")
        or verify_txn.get("Currency", "") != txn.get("Currency", "")
        or verify_txn.get("Payment Date", "") != txn.get("Payment Date", "")
    ):
        return _payment_result(
            ok=False, code="PAYMENT_TRANSACTION_IMMUTABLE",
            error="Финансовые поля Transaction изменились при реверсе — недопустимо",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status=previous_status, retry_safe=False,
        )

    sync_result = _synchronize_payment_obligation_after_transaction_change(obligation_id)
    if not sync_result["ok"]:
        return _payment_result(
            ok=False, code="PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED",
            error=f"Transaction реверснут, но синхронизация баланса Obligation не удалась: {sync_result.get('error')}",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="reversed", final_status="reversed",
            reversed=True, changed=True, retry_safe=False,
        )

    return _payment_result(
        ok=True, code="PAYMENT_TRANSACTION_REVERSED", error=None,
        payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        amount=txn.get("Amount", ""), currency=txn.get("Currency", ""),
        paid_amount=sync_result["paid_amount"], remaining_amount=sync_result["remaining_amount"],
        previous_status=previous_status, requested_status="reversed", final_status="reversed",
        changed=True, reversed=True, retry_safe=True,
    )


def fail_payment_transaction(payment_transaction_id: str) -> dict:
    """Phase 39C (ADR-022 §12/§19): the sole canonical pending→failed
    orchestration boundary. failed never affects Obligation balance —
    no synchronization call is made here."""
    from business_core.payment_manager import find_payment_transaction_by_id, update_payment_transaction_status

    if not payment_transaction_id:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error="payment_transaction_id обязателен")

    txn = find_payment_transaction_by_id(payment_transaction_id)
    if txn is None:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error=f"Payment Transaction {payment_transaction_id} не найден", payment_transaction_id=payment_transaction_id)

    business_id = txn.get("Business ID", "")
    obligation_id = txn.get("Payment Obligation ID", "")
    previous_status = txn.get("Status", "")

    if previous_status == "failed":
        return _payment_result(
            ok=True, code="PAYMENT_TRANSACTION_FAILED", error=None,
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="failed", final_status=previous_status, changed=False,
        )
    if previous_status != "pending":
        return _payment_result(
            ok=False, code="INVALID_PAYMENT_TRANSACTION_TRANSITION",
            error=f"Transaction {payment_transaction_id} имеет статус '{previous_status}' — переход в 'failed' возможен только из 'pending'",
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="failed", final_status=previous_status,
        )

    write_result = update_payment_transaction_status(payment_transaction_id, "failed")
    if not write_result["ok"]:
        return _payment_result(
            ok=False, code="PAYMENT_PERSISTENCE_FAILED", error=write_result.get("error"),
            payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
            previous_status=previous_status, requested_status="failed", final_status=previous_status,
        )

    changed = write_result["changed"]
    return _payment_result(
        ok=True, code="PAYMENT_TRANSACTION_FAILED", error=None,
        payment_transaction_id=payment_transaction_id, business_id=business_id, payment_obligation_id=obligation_id,
        previous_status=previous_status, requested_status="failed", final_status="failed", changed=changed,
    )


def update_payment_transaction_admin_fields(payment_transaction_id: str, updates: dict) -> dict:
    """Phase 39C (ADR-022 §25): thin resolve-then-delegate wrapper.
    Only Notes is ordinarily mutable, and only while pending —
    enforced by payment_manager.update_payment_transaction_admin_
    fields() itself."""
    from business_core.payment_manager import find_payment_transaction_by_id, update_payment_transaction_admin_fields as pm_update_admin

    if not payment_transaction_id:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error="payment_transaction_id обязателен")

    txn = find_payment_transaction_by_id(payment_transaction_id)
    if txn is None:
        return _payment_result(ok=False, code="PAYMENT_TRANSACTION_NOT_FOUND", error=f"Payment Transaction {payment_transaction_id} не найден", payment_transaction_id=payment_transaction_id)

    result = pm_update_admin(payment_transaction_id, updates)
    return _payment_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        payment_transaction_id=payment_transaction_id, business_id=txn.get("Business ID", ""),
        payment_obligation_id=txn.get("Payment Obligation ID", ""), changed=result.get("changed", False), retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Phase 40C (ADR-023): Commercial Offer Domain orchestration.
#
# business_builder.py is the sole cross-domain Commercial Offer
# orchestration owner: amount/currency/date/snapshot normalization,
# relation validation, Offer creation, revision, lifecycle transitions,
# latest-version/branching integrity, idempotency zero/one/multiple
# handling, structured result assembly. business_core.offer_manager.py
# (persistence) is called from here — never the reverse. No Telegram
# caller exists yet (Phase 40D); nothing here is called by
# telegram_handlers.py in this phase. Payment Domain (payment_manager.py,
# business_builder's own Payment orchestration section) is never
# imported or modified by any function below — Commercial Offer amount/
# currency codes are entirely Offer-local, never Payment codes
# (ADR-023 §10).
# ─────────────────────────────────────────────────────────────

from datetime import date as _date

_OFFER_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
_OFFER_TITLE_MAX_LENGTH = 300
_OFFER_SCOPE_MAX_LENGTH = 10000

_COMMERCIAL_OFFER_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":     ("draft", "sent", "cancelled", "archived"),
    "sent":      ("sent", "accepted", "rejected", "expired", "cancelled", "archived"),
    "accepted":  ("accepted", "archived"),
    "rejected":  ("rejected", "archived"),
    "expired":   ("expired", "archived"),
    "cancelled": ("cancelled", "archived"),
    "archived":  ("archived",),
}


def _offer_result(
    *, ok: bool, code: str, error: str | None,
    commercial_offer_id: str = "", offer_series_id: str = "", previous_commercial_offer_id: str = "",
    version_number: int = 0,
    business_id: str = "", client_id: str = "", object_id: str = "", service_id: str = "",
    roadmap_id: str = "", document_id: str = "",
    amount: str = "", currency: str = "", valid_until: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False, revised: bool = False,
    sent: bool = False, accepted: bool = False, rejected: bool = False,
    expired: bool = False, cancelled: bool = False, archived: bool = False,
    conflicting_ids: tuple = (), warnings: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Commercial Offer orchestration
    function (ADR-023 §30) — the stable, structured contract every
    caller reads instead of a bare exception or ad-hoc dict shape.
    Never carries a raw exception object or a raw Sheets row."""
    return {
        "ok": ok, "code": code, "error": error,
        "commercial_offer_id": commercial_offer_id, "offer_series_id": offer_series_id,
        "previous_commercial_offer_id": previous_commercial_offer_id, "version_number": version_number,
        "business_id": business_id, "client_id": client_id, "object_id": object_id, "service_id": service_id,
        "roadmap_id": roadmap_id, "document_id": document_id,
        "amount": amount, "currency": currency, "valid_until": valid_until,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed, "revised": revised,
        "sent": sent, "accepted": accepted, "rejected": rejected,
        "expired": expired, "cancelled": cancelled, "archived": archived,
        "conflicting_ids": tuple(conflicting_ids), "warnings": tuple(warnings), "retry_safe": retry_safe,
    }


def normalize_commercial_offer_amount(raw) -> dict:
    """
    Phase 40C (ADR-023 §10): Offer-local canonical Decimal amount
    normalization — deliberately not calling business_builder.
    normalize_payment_amount() so that Commercial Offer never emits a
    Payment-domain code (ADR-023 §7's explicit requirement). Same
    Decimal discipline as Payment: float rejected, canonical 2-
    fractional-digit string, no scientific notation, no thousands
    separators, no silent rounding.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "amount": Decimal | None, "normalized": str}
    """
    if isinstance(raw, float):
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "Сумма не может быть float — используйте Decimal или строку", "amount": None, "normalized": ""}
    if raw is None or raw == "":
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "Сумма обязательна", "amount": None, "normalized": ""}

    text = str(raw).strip()
    if not text:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "Сумма обязательна", "amount": None, "normalized": ""}
    if "," in text:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "Сумма не может содержать разделители тысяч (',')", "amount": None, "normalized": ""}
    if "e" in text.lower():
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "Сумма не может использовать экспоненциальную запись", "amount": None, "normalized": ""}

    try:
        value = Decimal(text)
    except InvalidOperation:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": f"Не удаётся разобрать сумму '{raw}'", "amount": None, "normalized": ""}

    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE", "error": "Сумма не может иметь более 2 знаков после запятой", "amount": None, "normalized": ""}

    if value <= 0:
        return {"ok": False, "code": "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE", "error": "Сумма должна быть больше нуля", "amount": None, "normalized": ""}

    quantized = value.quantize(Decimal("0.01"))
    return {"ok": True, "code": "", "error": None, "amount": quantized, "normalized": str(quantized)}


def normalize_commercial_offer_currency(raw) -> dict:
    """Phase 40C (ADR-023 §11): Offer-local currency normalization.
    Required, uppercased, exactly 3 ASCII letters — same shape as
    Payment's, deliberately not shared, to keep Offer-specific codes."""
    if raw is None:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_CURRENCY", "error": "Валюта обязательна", "currency": ""}
    text = str(raw).strip().upper()
    if not text:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_CURRENCY", "error": "Валюта обязательна", "currency": ""}
    if not _OFFER_CURRENCY_CODE_RE.match(text):
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_CURRENCY", "error": f"Недопустимый код валюты '{raw}' — требуется 3 буквы ASCII в верхнем регистре", "currency": ""}
    return {"ok": True, "code": "", "error": None, "currency": text}


def normalize_commercial_offer_valid_until(raw, *, reference_date: _date | None = None) -> dict:
    """
    Phase 40C (ADR-023 §9): deterministic ISO date validation for
    Valid Until. `reference_date` may be injected for deterministic
    tests; defaults to today (UTC date) otherwise. Must not be earlier
    than the reference date — same-day is allowed.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "valid_until": str}
    """
    if not raw:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_VALID_UNTIL", "error": "valid_until обязателен", "valid_until": ""}
    text = str(raw).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_VALID_UNTIL", "error": f"Некорректная дата '{raw}' — требуется формат YYYY-MM-DD", "valid_until": ""}

    from datetime import timezone as _timezone
    today = reference_date or datetime.now(_timezone.utc).date()
    if parsed < today:
        return {"ok": False, "code": "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST", "error": f"valid_until ({text}) не может быть раньше сегодняшней даты ({today.isoformat()})", "valid_until": ""}

    return {"ok": True, "code": "", "error": None, "valid_until": text}


def _validate_commercial_offer_snapshots(title_snapshot: str, scope_snapshot: str) -> dict:
    """Phase 40C (ADR-023 §10): Title/Scope Snapshot required, trimmed,
    bounded length. Never logs Scope Snapshot content — callers must
    only ever log length/presence, never the text itself."""
    title = (title_snapshot or "").strip()
    scope = (scope_snapshot or "").strip()

    if not title:
        return {"ok": False, "code": "COMMERCIAL_OFFER_TITLE_REQUIRED", "error": "title_snapshot обязателен", "title": "", "scope": ""}
    if len(title) > _OFFER_TITLE_MAX_LENGTH:
        return {"ok": False, "code": "COMMERCIAL_OFFER_TITLE_REQUIRED", "error": f"title_snapshot превышает {_OFFER_TITLE_MAX_LENGTH} символов", "title": "", "scope": ""}
    if not scope:
        return {"ok": False, "code": "COMMERCIAL_OFFER_SCOPE_REQUIRED", "error": "scope_snapshot обязателен", "title": "", "scope": ""}
    if len(scope) > _OFFER_SCOPE_MAX_LENGTH:
        return {"ok": False, "code": "COMMERCIAL_OFFER_SCOPE_REQUIRED", "error": f"scope_snapshot превышает {_OFFER_SCOPE_MAX_LENGTH} символов", "title": "", "scope": ""}

    return {"ok": True, "code": "", "error": None, "title": title, "scope": scope}


def _validate_commercial_offer_relations(
    business_id: str, client_id: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "", offer_document_id: str = "",
) -> dict:
    """
    Phase 40C (ADR-023 §11): canonical cross-domain Commercial Offer
    relation-validation path, all before any write. At least one of
    Object/Service/Roadmap is required (COMMERCIAL_OFFER_CONTEXT_
    REQUIRED otherwise) — an Offer with only Business+Client has no
    commercial context. Resolution mirrors _validate_payment_
    obligation_relations() exactly, applied to Offer's own relation set.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "resolved": dict | None}
    """
    from business_core.sheets import read_business_sheet

    if not business_id:
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен", "resolved": None}
    biz_rows = read_business_sheet("biz_registry")
    if not any(b.get("ID", "") == business_id for b in biz_rows):
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": f"Business {business_id} не найден", "resolved": None}

    if not client_id:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": "client_id обязателен", "resolved": None}
    from business_core.person_manager import find_person_by_id, is_person_archived, is_client_person, has_person_business_link
    client = find_person_by_id(client_id)
    if client is None:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} не найден", "resolved": None}
    if is_person_archived(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} архивирован", "resolved": None}
    if not is_client_person(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"{client_id} не является Client", "resolved": None}
    if not has_person_business_link(client, business_id):
        return {"ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH", "error": f"Client {client_id} не связан с Business {business_id}", "resolved": None}

    if not (object_id or service_id or roadmap_id):
        return {"ok": False, "code": "COMMERCIAL_OFFER_CONTEXT_REQUIRED", "error": "Требуется хотя бы одно: object_id, service_id или roadmap_id", "resolved": None}

    resolved_object_id = object_id
    resolved_service_id = service_id
    resolved_roadmap_id = roadmap_id

    if resolved_roadmap_id:
        roadmaps = read_business_sheet("roadmaps")
        rm = next((r for r in roadmaps if r.get("Roadmap ID", "") == resolved_roadmap_id), None)
        if rm is None:
            return {"ok": False, "code": "ROADMAP_NOT_FOUND", "error": f"Roadmap {resolved_roadmap_id} не найден", "resolved": None}
        rm_biz_id = rm.get("Business ID", "")
        if rm_biz_id and rm_biz_id != business_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} принадлежит бизнесу {rm_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }
        rm_object_id = rm.get("Object ID", "")
        if resolved_object_id and rm_object_id and resolved_object_id != rm_object_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Object {rm_object_id}, а указан Object {resolved_object_id}",
                "resolved": None,
            }
        resolved_object_id = resolved_object_id or rm_object_id
        rm_service_id = rm.get("Service ID", "")
        if resolved_service_id and rm_service_id and resolved_service_id != rm_service_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Roadmap {resolved_roadmap_id} связан с Service {rm_service_id}, а указан Service {resolved_service_id}",
                "resolved": None,
            }
        resolved_service_id = resolved_service_id or rm_service_id

    if resolved_object_id:
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(resolved_object_id)
        if obj is None:
            return {"ok": False, "code": "OBJECT_NOT_FOUND", "error": f"Object {resolved_object_id} не найден", "resolved": None}
        obj_biz_id = obj.get("biz_id", "")
        if obj_biz_id and obj_biz_id != business_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Object {resolved_object_id} принадлежит бизнесу {obj_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    if resolved_service_id:
        from business_core.service_manager import find_service_by_id
        svc = find_service_by_id(resolved_service_id)
        if svc is None:
            return {"ok": False, "code": "SERVICE_NOT_FOUND", "error": f"Service {resolved_service_id} не найден", "resolved": None}
        svc_biz_id = svc.get("biz_id", "")
        if svc_biz_id and svc_biz_id != business_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Service {resolved_service_id} принадлежит бизнесу {svc_biz_id}, а указан Business {business_id}",
                "resolved": None,
            }

    if offer_document_id:
        from business_core.document_manager import find_document_by_id
        doc = find_document_by_id(offer_document_id)
        if doc is None:
            return {"ok": False, "code": "DOCUMENT_NOT_FOUND", "error": f"Document {offer_document_id} не найден", "resolved": None}
        if doc.get("business_id", "") != business_id:
            return {
                "ok": False, "code": "COMMERCIAL_OFFER_RELATION_MISMATCH",
                "error": f"Document {offer_document_id} принадлежит другому Business",
                "resolved": None,
            }

    return {
        "ok": True, "code": "", "error": None,
        "resolved": {
            "business_id": business_id, "client_id": client_id,
            "object_id": resolved_object_id, "service_id": resolved_service_id,
            "roadmap_id": resolved_roadmap_id, "offer_document_id": offer_document_id,
        },
    }


def create_commercial_offer(
    business_id: str, client_id: str, title_snapshot: str, scope_snapshot: str,
    quoted_amount, currency: str, valid_until: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "",
    offer_document_id: str = "", caller_idempotency_key: str = "",
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Phase 40C (ADR-023 §12/§13): the sole canonical Commercial Offer
    creation orchestration boundary — always creates Version 1 of a
    new Offer Series.

    Validation order, all before any write:
      A. required inputs
      B. amount/currency/date/snapshot normalization
      C. relation validation (Business/Client/context/Document)
      D. idempotency lookup (zero/one/multiple)
      E. Offer Series ID + Commercial Offer ID generated only after A-D pass
      F. low-level persistence
      G. post-write verification
      H. structured result
    """
    from business_core.offer_manager import (
        find_commercial_offers_by_idempotency_key, generate_next_series_id,
        create_commercial_offer as om_create_offer, find_commercial_offer_by_id,
    )

    if not business_id:
        return _offer_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not client_id:
        return _offer_result(ok=False, code="CLIENT_NOT_FOUND", error="client_id обязателен", business_id=business_id)
    if not caller_idempotency_key:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED", error="caller_idempotency_key обязателен", business_id=business_id, client_id=client_id)

    amount_result = normalize_commercial_offer_amount(quoted_amount)
    if not amount_result["ok"]:
        return _offer_result(ok=False, code=amount_result["code"], error=amount_result["error"], business_id=business_id, client_id=client_id)
    normalized_amount = amount_result["normalized"]

    currency_result = normalize_commercial_offer_currency(currency)
    if not currency_result["ok"]:
        return _offer_result(ok=False, code=currency_result["code"], error=currency_result["error"], business_id=business_id, client_id=client_id)
    normalized_currency = currency_result["currency"]

    valid_until_result = normalize_commercial_offer_valid_until(valid_until)
    if not valid_until_result["ok"]:
        return _offer_result(ok=False, code=valid_until_result["code"], error=valid_until_result["error"], business_id=business_id, client_id=client_id)
    normalized_valid_until = valid_until_result["valid_until"]

    snapshot_result = _validate_commercial_offer_snapshots(title_snapshot, scope_snapshot)
    if not snapshot_result["ok"]:
        return _offer_result(ok=False, code=snapshot_result["code"], error=snapshot_result["error"], business_id=business_id, client_id=client_id)
    normalized_title = snapshot_result["title"]
    normalized_scope = snapshot_result["scope"]

    relation_result = _validate_commercial_offer_relations(
        business_id, client_id, object_id=object_id, service_id=service_id,
        roadmap_id=roadmap_id, offer_document_id=offer_document_id,
    )
    if not relation_result["ok"]:
        return _offer_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id, client_id=client_id)
    resolved = relation_result["resolved"]

    matches = find_commercial_offers_by_idempotency_key(business_id, caller_idempotency_key)
    if len(matches) > 1:
        conflicting_ids = tuple(m["Commercial Offer ID"] for m in matches)
        return _offer_result(
            ok=False, code="MULTIPLE_COMMERCIAL_OFFER_MATCHES",
            error=f"Найдено несколько Commercial Offer с этим ключом: {conflicting_ids}",
            business_id=business_id, client_id=client_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _offer_result(
            ok=True, code="COMMERCIAL_OFFER_REUSED", error=None,
            commercial_offer_id=existing["Commercial Offer ID"], offer_series_id=existing.get("Offer Series ID", ""),
            version_number=int(existing.get("Version Number") or 0),
            business_id=business_id, client_id=client_id,
            object_id=existing.get("Object ID", ""), service_id=existing.get("Service ID", ""),
            roadmap_id=existing.get("Roadmap ID", ""), document_id=existing.get("Offer Document ID", ""),
            amount=existing.get("Quoted Amount", ""), currency=existing.get("Currency", ""),
            valid_until=existing.get("Valid Until", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    series_id = generate_next_series_id()

    create_result = om_create_offer(
        series_id, "", 1, business_id, client_id, normalized_title, normalized_scope,
        normalized_amount, normalized_currency, normalized_valid_until,
        object_id=resolved["object_id"], service_id=resolved["service_id"], roadmap_id=resolved["roadmap_id"],
        offer_document_id=resolved["offer_document_id"], caller_idempotency_key=caller_idempotency_key,
        created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_PERSISTENCE_FAILED", error=create_result.get("error"), business_id=business_id, client_id=client_id, retry_safe=True)
    offer_id = create_result["commercial_offer_id"]

    saved = find_commercial_offer_by_id(offer_id)
    if saved is None:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED",
            error="Commercial Offer записан, но проверка после записи не прошла",
            commercial_offer_id=offer_id, offer_series_id=series_id, business_id=business_id, client_id=client_id, retry_safe=False,
        )

    return _offer_result(
        ok=True, code="COMMERCIAL_OFFER_CREATED", error=None,
        commercial_offer_id=offer_id, offer_series_id=series_id, version_number=1,
        business_id=business_id, client_id=client_id,
        object_id=resolved["object_id"], service_id=resolved["service_id"], roadmap_id=resolved["roadmap_id"],
        document_id=resolved["offer_document_id"],
        amount=normalized_amount, currency=normalized_currency, valid_until=normalized_valid_until,
        final_status="draft", created=True, retry_safe=True,
    )


def revise_commercial_offer(
    source_commercial_offer_id: str, caller_idempotency_key: str, created_by: str,
    *, title_snapshot: str = "", scope_snapshot: str = "", quoted_amount=None,
    currency: str = "", valid_until: str = "",
    object_id: str = "", service_id: str = "", roadmap_id: str = "",
    offer_document_id: str = "", notes: str = "",
) -> dict:
    """
    Phase 40C (ADR-023 §16/§17/§19): the sole canonical Commercial
    Offer revision orchestration boundary — creates version N+1 in the
    same Offer Series from an existing (must be latest) version.
    Branching is blocked: exactly one next version per current latest.
    """
    from business_core.offer_manager import (
        find_commercial_offer_by_id, find_latest_commercial_offer_in_series,
        find_commercial_offers_by_idempotency_key, list_commercial_offers_by_series,
        create_commercial_offer as om_create_offer,
    )

    if not source_commercial_offer_id:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error="source_commercial_offer_id обязателен")
    if not caller_idempotency_key:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED", error="caller_idempotency_key обязателен")

    source = find_commercial_offer_by_id(source_commercial_offer_id)
    if source is None:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error=f"Commercial Offer {source_commercial_offer_id} не найден")

    business_id = source.get("Business ID", "")
    series_id = source.get("Offer Series ID", "")

    latest_result = find_latest_commercial_offer_in_series(series_id)
    if not latest_result["ok"]:
        return _offer_result(ok=False, code=latest_result["code"], error=latest_result["error"], business_id=business_id, offer_series_id=series_id)
    latest = latest_result["offer"]
    if latest["Commercial Offer ID"] != source_commercial_offer_id:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_NOT_LATEST_VERSION",
            error=f"Commercial Offer {source_commercial_offer_id} не является последней версией серии {series_id}",
            business_id=business_id, offer_series_id=series_id, commercial_offer_id=source_commercial_offer_id,
        )

    # Branching prevention: no other row may already reference this
    # source as its Previous Commercial Offer ID.
    siblings = [
        r for r in list_commercial_offers_by_series(series_id)
        if r.get("Previous Commercial Offer ID", "") == source_commercial_offer_id
    ]
    if siblings:
        conflicting_ids = tuple(r["Commercial Offer ID"] for r in siblings)
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR",
            error=f"Уже существует ревизия(и) от {source_commercial_offer_id}: {conflicting_ids}",
            business_id=business_id, offer_series_id=series_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )

    matches = find_commercial_offers_by_idempotency_key(business_id, caller_idempotency_key)
    if len(matches) > 1:
        conflicting_ids = tuple(m["Commercial Offer ID"] for m in matches)
        return _offer_result(
            ok=False, code="MULTIPLE_COMMERCIAL_OFFER_MATCHES",
            error=f"Найдено несколько Commercial Offer с этим ключом: {conflicting_ids}",
            business_id=business_id, offer_series_id=series_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _offer_result(
            ok=True, code="COMMERCIAL_OFFER_REUSED", error=None,
            commercial_offer_id=existing["Commercial Offer ID"], offer_series_id=existing.get("Offer Series ID", ""),
            previous_commercial_offer_id=existing.get("Previous Commercial Offer ID", ""),
            version_number=int(existing.get("Version Number") or 0),
            business_id=business_id, final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    final_title = title_snapshot if title_snapshot else source.get("Title Snapshot", "")
    final_scope = scope_snapshot if scope_snapshot else source.get("Scope Snapshot", "")
    final_amount_raw = quoted_amount if quoted_amount is not None else source.get("Quoted Amount", "")
    final_currency_raw = currency if currency else source.get("Currency", "")
    final_valid_until_raw = valid_until if valid_until else source.get("Valid Until", "")
    final_object_id = object_id if object_id else source.get("Object ID", "")
    final_service_id = service_id if service_id else source.get("Service ID", "")
    final_roadmap_id = roadmap_id if roadmap_id else source.get("Roadmap ID", "")
    final_document_id = offer_document_id if offer_document_id else source.get("Offer Document ID", "")

    amount_result = normalize_commercial_offer_amount(final_amount_raw)
    if not amount_result["ok"]:
        return _offer_result(ok=False, code=amount_result["code"], error=amount_result["error"], business_id=business_id, offer_series_id=series_id)
    normalized_amount = amount_result["normalized"]

    currency_result = normalize_commercial_offer_currency(final_currency_raw)
    if not currency_result["ok"]:
        return _offer_result(ok=False, code=currency_result["code"], error=currency_result["error"], business_id=business_id, offer_series_id=series_id)
    normalized_currency = currency_result["currency"]

    valid_until_result = normalize_commercial_offer_valid_until(final_valid_until_raw)
    if not valid_until_result["ok"]:
        return _offer_result(ok=False, code=valid_until_result["code"], error=valid_until_result["error"], business_id=business_id, offer_series_id=series_id)
    normalized_valid_until = valid_until_result["valid_until"]

    snapshot_result = _validate_commercial_offer_snapshots(final_title, final_scope)
    if not snapshot_result["ok"]:
        return _offer_result(ok=False, code=snapshot_result["code"], error=snapshot_result["error"], business_id=business_id, offer_series_id=series_id)

    relation_result = _validate_commercial_offer_relations(
        business_id, source.get("Client ID", ""), object_id=final_object_id, service_id=final_service_id,
        roadmap_id=final_roadmap_id, offer_document_id=final_document_id,
    )
    if not relation_result["ok"]:
        return _offer_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id, offer_series_id=series_id)
    resolved = relation_result["resolved"]

    new_version = int(source.get("Version Number") or 0) + 1

    create_result = om_create_offer(
        series_id, source_commercial_offer_id, new_version, business_id, source.get("Client ID", ""),
        snapshot_result["title"], snapshot_result["scope"], normalized_amount, normalized_currency, normalized_valid_until,
        object_id=resolved["object_id"], service_id=resolved["service_id"], roadmap_id=resolved["roadmap_id"],
        offer_document_id=resolved["offer_document_id"], caller_idempotency_key=caller_idempotency_key,
        created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_PERSISTENCE_FAILED", error=create_result.get("error"), business_id=business_id, offer_series_id=series_id, retry_safe=True)
    new_offer_id = create_result["commercial_offer_id"]

    from business_core.offer_manager import find_commercial_offer_by_id as _find
    saved = _find(new_offer_id)
    if saved is None:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED",
            error="Revision записана, но проверка после записи не прошла",
            commercial_offer_id=new_offer_id, offer_series_id=series_id,
            previous_commercial_offer_id=source_commercial_offer_id, business_id=business_id, retry_safe=False,
        )

    return _offer_result(
        ok=True, code="COMMERCIAL_OFFER_REVISED", error=None,
        commercial_offer_id=new_offer_id, offer_series_id=series_id,
        previous_commercial_offer_id=source_commercial_offer_id, version_number=new_version,
        business_id=business_id, client_id=source.get("Client ID", ""),
        object_id=resolved["object_id"], service_id=resolved["service_id"], roadmap_id=resolved["roadmap_id"],
        document_id=resolved["offer_document_id"],
        amount=normalized_amount, currency=normalized_currency, valid_until=normalized_valid_until,
        final_status="draft", created=True, revised=True, retry_safe=True,
    )


def _offer_latest_version_check(offer: dict) -> dict:
    """Shared latest-version guard used by every lifecycle transition
    that requires it (ADR-023 §20/§21/§22/§24)."""
    from business_core.offer_manager import find_latest_commercial_offer_in_series

    series_id = offer.get("Offer Series ID", "")
    offer_id = offer.get("Commercial Offer ID", "")
    latest_result = find_latest_commercial_offer_in_series(series_id)
    if not latest_result["ok"]:
        return latest_result
    if latest_result["offer"]["Commercial Offer ID"] != offer_id:
        return {"ok": False, "code": "COMMERCIAL_OFFER_NOT_LATEST_VERSION", "error": f"Commercial Offer {offer_id} не является последней версией серии {series_id}", "offer": None}
    return {"ok": True, "code": "", "error": None, "offer": offer}


def _transition_commercial_offer(
    offer_id: str, target_status: str, *, require_latest: bool, actor_field: str = "", actor: str = "",
    reason_field: str = "", reason: str = "", extra_status_kwargs: dict | None = None,
) -> dict:
    """Internal shared transition engine for send/accept/reject/expire/
    cancel/archive — validates the transition matrix, actor/reason
    requirements, and latest-version gating uniformly, then delegates
    the actual write to offer_manager.update_commercial_offer_status()."""
    from business_core.offer_manager import find_commercial_offer_by_id, update_commercial_offer_status

    if not offer_id:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error="offer_id обязателен")

    offer = find_commercial_offer_by_id(offer_id)
    if offer is None:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error=f"Commercial Offer {offer_id} не найден", commercial_offer_id=offer_id)

    business_id = offer.get("Business ID", "")
    previous_status = offer.get("Status", "")

    if target_status == previous_status:
        return _offer_result(
            ok=True, code="COMMERCIAL_OFFER_STATUS_UNCHANGED", error=None,
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status, changed=False,
        )

    allowed_targets = _COMMERCIAL_OFFER_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _offer_result(
            ok=False, code="INVALID_COMMERCIAL_OFFER_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if actor_field and not actor:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_ACTOR_REQUIRED", error=f"{actor_field} обязателен",
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )
    if reason_field == "Rejection Reason" and not reason:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_REJECTION_REASON_REQUIRED", error="rejection_reason обязателен",
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )
    if reason_field == "Cancellation Reason" and not reason:
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_CANCELLATION_REASON_REQUIRED", error="cancellation_reason обязателен",
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if require_latest:
        latest_check = _offer_latest_version_check(offer)
        if not latest_check["ok"]:
            return _offer_result(
                ok=False, code=latest_check["code"], error=latest_check["error"],
                commercial_offer_id=offer_id, business_id=business_id,
                previous_status=previous_status, requested_status=target_status, final_status=previous_status,
            )

    now = _now_utc_str()
    status_kwargs = dict(extra_status_kwargs or {})
    write_result = update_commercial_offer_status(offer_id, target_status, **status_kwargs)
    if not write_result["ok"]:
        return _offer_result(
            ok=False, code=write_result.get("code") or "COMMERCIAL_OFFER_PERSISTENCE_FAILED", error=write_result.get("error"),
            commercial_offer_id=offer_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _offer_result(
        ok=True, code="COMMERCIAL_OFFER_STATUS_UPDATED" if changed else "COMMERCIAL_OFFER_STATUS_UNCHANGED", error=None,
        commercial_offer_id=offer_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status, final_status=target_status, changed=changed,
    )


def send_commercial_offer(offer_id: str, sent_by: str) -> dict:
    """Phase 40C (ADR-023 §20): the sole canonical draft→sent orchestration
    boundary. Only draft may become sent; latest-version required."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "sent", require_latest=True,
        actor_field="sent_by", actor=sent_by,
        extra_status_kwargs={"sent_at": now, "sent_by": sent_by},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "sent":
        result["code"] = "COMMERCIAL_OFFER_SENT"
        result["sent"] = True
    return result


def accept_commercial_offer(offer_id: str, accepted_by: str) -> dict:
    """Phase 40C (ADR-023 §21): the sole canonical sent→accepted
    orchestration boundary. Never creates a Payment Obligation, never
    mutates Roadmap/Stage/Service/Document/Payment — acceptance is
    purely a Commercial Offer lifecycle fact."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "accepted", require_latest=True,
        actor_field="accepted_by", actor=accepted_by,
        extra_status_kwargs={"accepted_at": now, "accepted_by": accepted_by},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "accepted":
        result["code"] = "COMMERCIAL_OFFER_ACCEPTED"
        result["accepted"] = True
    return result


def reject_commercial_offer(offer_id: str, rejected_by: str, rejection_reason: str) -> dict:
    """Phase 40C (ADR-023 §22): the sole canonical sent→rejected
    orchestration boundary. rejection_reason is never logged by this
    function — only passed through to persistence."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "rejected", require_latest=True,
        actor_field="rejected_by", actor=rejected_by,
        reason_field="Rejection Reason", reason=rejection_reason,
        extra_status_kwargs={"rejected_at": now, "rejected_by": rejected_by, "rejection_reason": rejection_reason},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "rejected":
        result["code"] = "COMMERCIAL_OFFER_REJECTED"
        result["rejected"] = True
    return result


def expire_commercial_offer(offer_id: str) -> dict:
    """Phase 40C (ADR-023 §23): the sole canonical sent→expired
    orchestration boundary — explicit transition only, never a
    background/scheduled mutation."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "expired", require_latest=True,
        extra_status_kwargs={"expired_at": now},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "expired":
        result["code"] = "COMMERCIAL_OFFER_EXPIRED"
        result["expired"] = True
    return result


def cancel_commercial_offer(offer_id: str, cancelled_by: str, cancellation_reason: str) -> dict:
    """Phase 40C (ADR-023 §24): the sole canonical draft/sent→cancelled
    orchestration boundary. accepted cannot be cancelled (blocked by
    the transition matrix itself, since 'cancelled' is absent from
    the accepted row's allowed targets). Latest-version is checked
    unconditionally — trivially satisfied for an un-revised draft/sent
    Offer, and correctly blocks cancellation of a version that has
    since been superseded by a revision, whether draft or sent."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "cancelled", require_latest=True,
        actor_field="cancelled_by", actor=cancelled_by,
        reason_field="Cancellation Reason", reason=cancellation_reason,
        extra_status_kwargs={"cancelled_at": now, "cancelled_by": cancelled_by, "cancellation_reason": cancellation_reason},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "cancelled":
        result["code"] = "COMMERCIAL_OFFER_CANCELLED"
        result["cancelled"] = True
    return result


def archive_commercial_offer(offer_id: str) -> dict:
    """Phase 40C (ADR-023 §25): the sole canonical →archived
    orchestration boundary. Terminal; no restore; no cascade."""
    now = _now_utc_str()
    result = _transition_commercial_offer(
        offer_id, "archived", require_latest=False,
        extra_status_kwargs={"archived_at": now},
    )
    if result["ok"] and result["changed"] and result["final_status"] == "archived":
        result["code"] = "COMMERCIAL_OFFER_ARCHIVED"
        result["archived"] = True
    return result


def update_commercial_offer_draft(offer_id: str, updates: dict) -> dict:
    """
    Phase 40C (ADR-023 §16/§26): the sole canonical draft-only
    commercial-field update orchestration boundary. Revalidates every
    supplied override exactly like creation does — amount/currency/
    date/snapshot/relations — before persisting. Only permitted while
    the Offer is still `draft`.
    """
    from business_core.offer_manager import find_commercial_offer_by_id, update_commercial_offer_draft_fields

    if not offer_id:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error="offer_id обязателен")

    offer = find_commercial_offer_by_id(offer_id)
    if offer is None:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error=f"Commercial Offer {offer_id} не найден", commercial_offer_id=offer_id)

    business_id = offer.get("Business ID", "")
    current_status = offer.get("Status", "")
    if current_status != "draft":
        return _offer_result(
            ok=False, code="COMMERCIAL_OFFER_IMMUTABLE",
            error=f"Commercial Offer {offer_id} имеет статус '{current_status}' — коммерческие поля изменяемы только в draft",
            commercial_offer_id=offer_id, business_id=business_id,
        )

    persisted_updates: dict = {}

    if "Title Snapshot" in updates or "Scope Snapshot" in updates:
        title = updates.get("Title Snapshot", offer.get("Title Snapshot", ""))
        scope = updates.get("Scope Snapshot", offer.get("Scope Snapshot", ""))
        snap_result = _validate_commercial_offer_snapshots(title, scope)
        if not snap_result["ok"]:
            return _offer_result(ok=False, code=snap_result["code"], error=snap_result["error"], commercial_offer_id=offer_id, business_id=business_id)
        if "Title Snapshot" in updates:
            persisted_updates["Title Snapshot"] = snap_result["title"]
        if "Scope Snapshot" in updates:
            persisted_updates["Scope Snapshot"] = snap_result["scope"]

    if "Quoted Amount" in updates:
        amount_result = normalize_commercial_offer_amount(updates["Quoted Amount"])
        if not amount_result["ok"]:
            return _offer_result(ok=False, code=amount_result["code"], error=amount_result["error"], commercial_offer_id=offer_id, business_id=business_id)
        persisted_updates["Quoted Amount"] = amount_result["normalized"]

    if "Currency" in updates:
        currency_result = normalize_commercial_offer_currency(updates["Currency"])
        if not currency_result["ok"]:
            return _offer_result(ok=False, code=currency_result["code"], error=currency_result["error"], commercial_offer_id=offer_id, business_id=business_id)
        persisted_updates["Currency"] = currency_result["currency"]

    if "Valid Until" in updates:
        valid_until_result = normalize_commercial_offer_valid_until(updates["Valid Until"])
        if not valid_until_result["ok"]:
            return _offer_result(ok=False, code=valid_until_result["code"], error=valid_until_result["error"], commercial_offer_id=offer_id, business_id=business_id)
        persisted_updates["Valid Until"] = valid_until_result["valid_until"]

    if any(k in updates for k in ("Object ID", "Service ID", "Roadmap ID", "Offer Document ID")):
        relation_result = _validate_commercial_offer_relations(
            business_id, offer.get("Client ID", ""),
            object_id=updates.get("Object ID", offer.get("Object ID", "")),
            service_id=updates.get("Service ID", offer.get("Service ID", "")),
            roadmap_id=updates.get("Roadmap ID", offer.get("Roadmap ID", "")),
            offer_document_id=updates.get("Offer Document ID", offer.get("Offer Document ID", "")),
        )
        if not relation_result["ok"]:
            return _offer_result(ok=False, code=relation_result["code"], error=relation_result["error"], commercial_offer_id=offer_id, business_id=business_id)
        for field in ("Object ID", "Service ID", "Roadmap ID", "Offer Document ID"):
            if field in updates:
                persisted_updates[field] = relation_result["resolved"][
                    {"Object ID": "object_id", "Service ID": "service_id", "Roadmap ID": "roadmap_id", "Offer Document ID": "offer_document_id"}[field]
                ]

    if "Notes" in updates:
        persisted_updates["Notes"] = updates["Notes"]

    result = update_commercial_offer_draft_fields(offer_id, persisted_updates)
    return _offer_result(
        ok=result["ok"], code=result.get("code") or ("COMMERCIAL_OFFER_UPDATED" if result.get("changed") else "COMMERCIAL_OFFER_UPDATE_UNCHANGED"),
        error=result.get("error"), commercial_offer_id=offer_id, business_id=business_id, changed=result.get("changed", False), retry_safe=True,
    )


def update_commercial_offer_admin_fields(offer_id: str, updates: dict) -> dict:
    """Phase 40C (ADR-023 §27): thin resolve-then-delegate wrapper.
    Only Notes is ordinarily mutable, in every status."""
    from business_core.offer_manager import find_commercial_offer_by_id, update_commercial_offer_admin_fields as om_update_admin

    if not offer_id:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error="offer_id обязателен")

    offer = find_commercial_offer_by_id(offer_id)
    if offer is None:
        return _offer_result(ok=False, code="COMMERCIAL_OFFER_NOT_FOUND", error=f"Commercial Offer {offer_id} не найден", commercial_offer_id=offer_id)

    result = om_update_admin(offer_id, updates)
    result_is_dict = isinstance(result, dict)
    ok = result.get("ok") if result_is_dict else False
    manager_code = (result.get("code") if result_is_dict else "") or ""

    # Phase 17E-2A4-H1: a success/no-op code may only ever be
    # synthesized when the manager reported ok is True — otherwise an
    # infrastructure failure (manager code="") would be indistinguishable
    # from a genuine no-op, since both leave code="" on the manager
    # side. An existing non-empty manager failure code (NOT_FOUND,
    # IMMUTABLE, validation codes) is always preserved untouched.
    if ok is True:
        code = manager_code or ("COMMERCIAL_OFFER_UPDATED" if result.get("changed") else "COMMERCIAL_OFFER_UPDATE_UNCHANGED")
    else:
        code = manager_code

    return _offer_result(
        ok=(ok is True), code=code,
        error=(result.get("error") if result_is_dict else None),
        commercial_offer_id=offer_id, business_id=offer.get("Business ID", ""),
        changed=(result.get("changed", False) if result_is_dict else False), retry_safe=True,
    )


def is_commercial_offer_effectively_expired(offer: dict, *, reference_date: _date | None = None) -> bool:
    """
    Phase 40C (ADR-023 §17/§29): stateless read-only helper — only
    `sent` Offers with a past Valid Until are effectively expired.
    Never writes, never mutates Status. accepted/rejected/cancelled/
    archived never qualify, regardless of Valid Until.
    """
    if offer.get("Status", "") != "sent":
        return False
    valid_until_raw = offer.get("Valid Until", "")
    if not valid_until_raw:
        return False
    try:
        valid_until = datetime.strptime(valid_until_raw, "%Y-%m-%d").date()
    except ValueError:
        return False
    from datetime import timezone as _timezone
    today = reference_date or datetime.now(_timezone.utc).date()
    return valid_until < today


# ─────────────────────────────────────────────────────────────
# Lead / Sales Funnel Domain (Phase 41C, ADR-024)
#
# Canonical pre-Client Lead entity, fully separate from Person/Client
# (ADR-024 §1/§3) — no automatic Client creation or mutation anywhere
# in this section. lead_manager.py is the sole persistence owner;
# every function below is this domain's sole orchestration boundary,
# exactly mirroring the Payment/Commercial Offer sections above.
#
# Idempotency (Business ID + Caller Idempotency Key) and duplicate-
# contact detection (exact-match, warning-only) are two structurally
# distinct mechanisms (ADR-024 §9/§10) — never conflated below.
# ─────────────────────────────────────────────────────────────

_LEAD_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
_LEAD_PHONE_LIKE_RE = re.compile(r"^\+?\d{7,15}$")
_LEAD_CONTACT_NAME_MAX_LENGTH = 300
_LEAD_COMPANY_MAX_LENGTH = 300
_LEAD_EMAIL_MAX_LENGTH = 254

_LEAD_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new":          ("new", "contacted", "qualified", "unqualified", "lost", "converted", "archived"),
    "contacted":    ("contacted", "qualified", "unqualified", "lost", "converted", "archived"),
    "qualified":    ("qualified", "contacted", "unqualified", "lost", "converted", "archived"),
    "unqualified":  ("unqualified", "archived"),
    "converted":    ("converted", "archived"),
    "lost":         ("lost", "archived"),
    "archived":     ("archived",),
}
_LEAD_DISPOSITION_REQUIRED_STATUSES = frozenset({"unqualified", "lost"})
_LEAD_ACTIVE_STATUSES = frozenset({"new", "contacted", "qualified"})


def _lead_result(
    *, ok: bool, code: str, error: str | None,
    lead_id: str = "", business_id: str = "", service_id: str = "", channel_id: str = "",
    assigned_person_id: str = "", converted_client_id: str = "",
    expected_value: str = "", currency: str = "",
    next_follow_up_at: str = "", last_contacted_at: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False,
    contacted: bool = False, qualified: bool = False, unqualified: bool = False,
    converted: bool = False, lost: bool = False, archived: bool = False,
    duplicate_contact_ids: tuple = (), conflicting_ids: tuple = (),
    warnings: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Lead orchestration function
    (ADR-024 §26) — the stable, structured contract every caller reads
    instead of a bare exception or ad-hoc dict shape. Never carries
    contact name/phone/WhatsApp/email/company values, qualification/
    disposition/Notes text, a raw exception, a raw Sheets row, or any
    Telegram-specific Russian string."""
    return {
        "ok": ok, "code": code, "error": error,
        "lead_id": lead_id, "business_id": business_id, "service_id": service_id, "channel_id": channel_id,
        "assigned_person_id": assigned_person_id, "converted_client_id": converted_client_id,
        "expected_value": expected_value, "currency": currency,
        "next_follow_up_at": next_follow_up_at, "last_contacted_at": last_contacted_at,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed,
        "contacted": contacted, "qualified": qualified, "unqualified": unqualified,
        "converted": converted, "lost": lost, "archived": archived,
        "duplicate_contact_ids": tuple(duplicate_contact_ids), "conflicting_ids": tuple(conflicting_ids),
        "warnings": tuple(warnings), "retry_safe": retry_safe,
    }


# ─────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────

def _validate_lead_contact_name(raw) -> dict:
    """ADR-024 §7: required, trimmed, bounded length, never used for
    identity. Returns {"ok", "code", "error", "name"}."""
    text = str(raw or "").strip()
    if not text:
        return {"ok": False, "code": "LEAD_CONTACT_NAME_REQUIRED", "error": "contact_name_snapshot обязателен", "name": ""}
    if len(text) > _LEAD_CONTACT_NAME_MAX_LENGTH:
        return {"ok": False, "code": "LEAD_CONTACT_NAME_REQUIRED", "error": f"contact_name_snapshot превышает {_LEAD_CONTACT_NAME_MAX_LENGTH} символов", "name": ""}
    return {"ok": True, "code": "", "error": None, "name": text}


def _normalize_lead_company(raw) -> str:
    """ADR-024 §7: optional, trimmed, bounded — never used for identity,
    never blocks creation."""
    text = str(raw or "").strip()
    return text[:_LEAD_COMPANY_MAX_LENGTH]


def _normalize_lead_phone_like(raw, code: str) -> dict:
    """
    ADR-024 §8: shared Phone/WhatsApp normalization. Optional — blank
    stays blank. Trims whitespace, removes safe formatting characters
    (spaces, parentheses, hyphens), preserves an optional leading `+`.
    Remaining content must be 7-15 digits. Never infers a country code,
    never silently prepends +7, never converts a local number into an
    international one.
    """
    if raw is None:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    text = str(raw).strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}

    cleaned = re.sub(r"[\s()\-]", "", text)
    if not _LEAD_PHONE_LIKE_RE.match(cleaned):
        return {"ok": False, "code": code, "error": f"Недопустимый номер '{raw}'", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": cleaned}


def normalize_lead_phone(raw) -> dict:
    return _normalize_lead_phone_like(raw, "INVALID_LEAD_PHONE")


def normalize_lead_whatsapp(raw) -> dict:
    return _normalize_lead_phone_like(raw, "INVALID_LEAD_WHATSAPP")


def normalize_lead_email(raw) -> dict:
    """
    ADR-024 §9: optional, trimmed, lowercased for canonical exact
    matching, exactly one `@`, non-empty local/domain parts, bounded
    length, no internal whitespace, no deliverability claim.
    """
    if raw is None:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    text = str(raw).strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    if any(ch.isspace() for ch in text):
        return {"ok": False, "code": "INVALID_LEAD_EMAIL", "error": f"Email '{raw}' не может содержать пробелы", "normalized": ""}
    if len(text) > _LEAD_EMAIL_MAX_LENGTH:
        return {"ok": False, "code": "INVALID_LEAD_EMAIL", "error": f"Email превышает {_LEAD_EMAIL_MAX_LENGTH} символов", "normalized": ""}
    if text.count("@") != 1:
        return {"ok": False, "code": "INVALID_LEAD_EMAIL", "error": f"Email '{raw}' должен содержать ровно один '@'", "normalized": ""}
    local, domain = text.split("@")
    if not local or not domain:
        return {"ok": False, "code": "INVALID_LEAD_EMAIL", "error": f"Email '{raw}' некорректен", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": text.lower()}


def _validate_lead_contact_channel(phone: str, whatsapp: str, email: str) -> dict:
    """ADR-024 §10: at least one of the three normalized channels must
    be non-blank. Name alone is not sufficient."""
    if not (phone or whatsapp or email):
        return {"ok": False, "code": "LEAD_CONTACT_CHANNEL_REQUIRED", "error": "требуется хотя бы один контактный канал: Phone, WhatsApp или Email"}
    return {"ok": True, "code": "", "error": None}


def normalize_lead_expected_value(raw) -> dict:
    """
    ADR-024 §14: optional Decimal-only estimate. Never canonical
    commercial truth. Mirrors normalize_payment_amount()'s discipline
    with Lead-local result codes (never leaks a PAYMENT_* code).

    Returns:
        {"ok": bool, "code": str, "error": str | None, "normalized": str}
    """
    if isinstance(raw, float):
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE", "error": "Expected Value не может быть float — используйте Decimal или строку", "normalized": ""}

    text = str(raw).strip()
    if "," in text:
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE", "error": "Expected Value не может содержать разделители тысяч (',')", "normalized": ""}
    if "e" in text.lower():
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE", "error": "Expected Value не может использовать экспоненциальную запись", "normalized": ""}

    try:
        value = Decimal(text)
    except InvalidOperation:
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE", "error": f"Не удаётся разобрать Expected Value '{raw}'", "normalized": ""}

    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE_SCALE", "error": "Expected Value не может иметь более 2 знаков после запятой", "normalized": ""}

    if value <= 0:
        return {"ok": False, "code": "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE", "error": "Expected Value должен быть больше нуля", "normalized": ""}

    quantized = value.quantize(Decimal("0.01"))
    return {"ok": True, "code": "", "error": None, "normalized": str(quantized)}


def normalize_lead_currency(raw) -> dict:
    """ADR-024 §14: required whenever Expected Value is present.
    Uppercased, exactly 3 ASCII letters, no implicit default."""
    text = str(raw or "").strip().upper()
    if not text:
        return {"ok": False, "code": "INVALID_LEAD_CURRENCY", "error": "Currency обязателен", "currency": ""}
    if not _LEAD_CURRENCY_CODE_RE.match(text):
        return {"ok": False, "code": "INVALID_LEAD_CURRENCY", "error": f"Недопустимый код валюты '{raw}' — требуется 3 буквы ASCII в верхнем регистре", "currency": ""}
    return {"ok": True, "code": "", "error": None, "currency": text}


def _validate_lead_expected_value_pair(expected_value_raw, currency_raw) -> dict:
    """ADR-024 §14: Expected Value and Currency are both blank or both
    present — never propagated to Commercial Offer or Payment."""
    ev_blank = expected_value_raw is None or str(expected_value_raw).strip() == ""
    cur_blank = currency_raw is None or str(currency_raw).strip() == ""

    if ev_blank and cur_blank:
        return {"ok": True, "code": "", "error": None, "expected_value": "", "currency": ""}
    if ev_blank != cur_blank:
        return {"ok": False, "code": "INVALID_LEAD_EXPECTED_VALUE", "error": "Expected Value и Currency должны быть указаны вместе либо оба пусты", "expected_value": "", "currency": ""}

    amount_result = normalize_lead_expected_value(expected_value_raw)
    if not amount_result["ok"]:
        return {"ok": False, "code": amount_result["code"], "error": amount_result["error"], "expected_value": "", "currency": ""}

    currency_result = normalize_lead_currency(currency_raw)
    if not currency_result["ok"]:
        return {"ok": False, "code": currency_result["code"], "error": currency_result["error"], "expected_value": "", "currency": ""}

    return {"ok": True, "code": "", "error": None, "expected_value": amount_result["normalized"], "currency": currency_result["currency"]}


def normalize_lead_datetime(raw) -> dict:
    """
    ADR-024 §15: deterministic ISO-8601/RFC3339 validation for Next
    Follow-up At / Last Contacted At. Optional — blank stays blank.
    Requires an explicit timezone offset (a trailing "Z" is accepted as
    UTC shorthand) — timezone-naive values are rejected outright to
    avoid ambiguity. No local-time guessing, no scheduler.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "normalized": str}
    """
    if raw is None:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    text = str(raw).strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}

    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return {"ok": False, "code": "INVALID_LEAD_DATETIME", "error": f"Некорректная дата/время '{raw}' — требуется ISO-8601 с явным часовым поясом", "normalized": ""}

    if parsed.tzinfo is None:
        return {"ok": False, "code": "INVALID_LEAD_DATETIME", "error": f"'{raw}' не содержит явного часового пояса", "normalized": ""}

    return {"ok": True, "code": "", "error": None, "normalized": parsed.isoformat()}


# ─────────────────────────────────────────────────────────────
# Relation validation
# ─────────────────────────────────────────────────────────────

def _validate_lead_relations(
    business_id: str, *, service_id: str = "", channel_id: str = "", assigned_person_id: str = "",
) -> dict:
    """
    ADR-024 §13: Business required; Service/Channel/Assigned Person
    optional but must exist and belong to the same Business when
    supplied. Converted Client ID is validated separately, only at
    conversion time (_validate_lead_conversion_target()) — it is never
    part of ordinary creation/update relation validation.
    """
    from business_core.sheets import read_business_sheet

    if not business_id:
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен"}
    biz_rows = read_business_sheet("biz_registry")
    if not any(b.get("ID", "") == business_id for b in biz_rows):
        return {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": f"Business {business_id} не найден"}

    if service_id:
        from business_core.service_manager import find_service_by_id
        svc = find_service_by_id(service_id)
        if svc is None:
            return {"ok": False, "code": "SERVICE_NOT_FOUND", "error": f"Service {service_id} не найден"}
        svc_biz_id = svc.get("biz_id", "")
        if svc_biz_id and svc_biz_id != business_id:
            return {"ok": False, "code": "LEAD_RELATION_MISMATCH", "error": f"Service {service_id} принадлежит бизнесу {svc_biz_id}, а указан Business {business_id}"}

    if channel_id:
        channels = read_business_sheet("channel_registry")
        channel = next((c for c in channels if c.get("ID", "") == channel_id), None)
        if channel is None:
            return {"ok": False, "code": "CHANNEL_NOT_FOUND", "error": f"Channel {channel_id} не найден"}
        ch_biz_id = channel.get("Бизнес ID", "")
        if ch_biz_id and ch_biz_id != business_id:
            return {"ok": False, "code": "LEAD_RELATION_MISMATCH", "error": f"Channel {channel_id} принадлежит бизнесу {ch_biz_id}, а указан Business {business_id}"}

    if assigned_person_id:
        from business_core.person_manager import find_person_by_id, is_person_archived, has_person_business_link
        person = find_person_by_id(assigned_person_id)
        if person is None:
            return {"ok": False, "code": "PERSON_NOT_FOUND", "error": f"Person {assigned_person_id} не найден"}
        if is_person_archived(person):
            return {"ok": False, "code": "PERSON_NOT_FOUND", "error": f"Person {assigned_person_id} архивирован"}
        if not has_person_business_link(person, business_id):
            return {"ok": False, "code": "LEAD_RELATION_MISMATCH", "error": f"Person {assigned_person_id} не связан с Business {business_id}"}

    return {"ok": True, "code": "", "error": None}


def _validate_lead_conversion_target(business_id: str, converted_client_id: str) -> dict:
    """ADR-024 §19: Converted Client ID must reference an existing,
    non-archived, valid Client belonging to the same Business. Never
    creates, never mutates the Client."""
    from business_core.person_manager import find_person_by_id, is_person_archived, is_client_person, has_person_business_link

    client = find_person_by_id(converted_client_id)
    if client is None:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {converted_client_id} не найден"}
    if is_person_archived(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {converted_client_id} архивирован"}
    if not is_client_person(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"{converted_client_id} не является Client"}
    if not has_person_business_link(client, business_id):
        return {"ok": False, "code": "LEAD_RELATION_MISMATCH", "error": f"Client {converted_client_id} не связан с Business {business_id}"}
    return {"ok": True, "code": "", "error": None}


# ─────────────────────────────────────────────────────────────
# Creation
# ─────────────────────────────────────────────────────────────

def create_lead(
    business_id: str, contact_name_snapshot: str,
    *, created_by: str, caller_idempotency_key: str,
    phone_snapshot: str = "", whatsapp_snapshot: str = "", email_snapshot: str = "",
    company_snapshot: str = "", service_id: str = "", source: str = "", channel_id: str = "",
    qualification_notes: str = "", expected_value="", currency: str = "",
    next_follow_up_at: str = "", last_contacted_at: str = "", assigned_person_id: str = "",
    notes: str = "",
) -> dict:
    """
    Phase 41C (ADR-024 §16): the sole canonical Lead creation
    orchestration boundary.

    Validation order, all before any write:
      A. required business_id / contact_name_snapshot / created_by / caller_idempotency_key
      B. contact-name normalization
      C. Phone/WhatsApp/Email normalization
      D. contact-channel requirement (at least one of Phone/WhatsApp/Email)
      E. Expected Value/Currency pairing + normalization
      F. Next Follow-up At / Last Contacted At normalization
      G. relation validation (Business/Service/Channel/Assigned Person)
      H. idempotency lookup (zero/one/multiple)
      I. duplicate-contact-warning lookup (zero-match path only)
      J. Lead ID generated only after A-I pass
      K. low-level persistence
      L. post-write verification
      M. structured result, including any duplicate_contact_ids warning
    """
    from business_core.lead_manager import (
        find_leads_by_idempotency_key, find_leads_by_exact_contact_channels,
        create_lead as lm_create_lead, find_lead_by_id,
    )

    if not business_id:
        return _lead_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not created_by:
        return _lead_result(ok=False, code="LEAD_PERSISTENCE_FAILED", error="created_by обязателен", business_id=business_id)
    if not caller_idempotency_key:
        return _lead_result(ok=False, code="LEAD_IDEMPOTENCY_REQUIRED", error="caller_idempotency_key обязателен", business_id=business_id)

    name_result = _validate_lead_contact_name(contact_name_snapshot)
    if not name_result["ok"]:
        return _lead_result(ok=False, code=name_result["code"], error=name_result["error"], business_id=business_id)
    normalized_name = name_result["name"]

    phone_result = normalize_lead_phone(phone_snapshot)
    if not phone_result["ok"]:
        return _lead_result(ok=False, code=phone_result["code"], error=phone_result["error"], business_id=business_id)
    normalized_phone = phone_result["normalized"]

    whatsapp_result = normalize_lead_whatsapp(whatsapp_snapshot)
    if not whatsapp_result["ok"]:
        return _lead_result(ok=False, code=whatsapp_result["code"], error=whatsapp_result["error"], business_id=business_id)
    normalized_whatsapp = whatsapp_result["normalized"]

    email_result = normalize_lead_email(email_snapshot)
    if not email_result["ok"]:
        return _lead_result(ok=False, code=email_result["code"], error=email_result["error"], business_id=business_id)
    normalized_email = email_result["normalized"]

    channel_check = _validate_lead_contact_channel(normalized_phone, normalized_whatsapp, normalized_email)
    if not channel_check["ok"]:
        return _lead_result(ok=False, code=channel_check["code"], error=channel_check["error"], business_id=business_id)

    normalized_company = _normalize_lead_company(company_snapshot)

    value_result = _validate_lead_expected_value_pair(expected_value, currency)
    if not value_result["ok"]:
        return _lead_result(ok=False, code=value_result["code"], error=value_result["error"], business_id=business_id)
    normalized_expected_value = value_result["expected_value"]
    normalized_currency = value_result["currency"]

    follow_up_result = normalize_lead_datetime(next_follow_up_at)
    if not follow_up_result["ok"]:
        return _lead_result(ok=False, code=follow_up_result["code"], error=follow_up_result["error"], business_id=business_id)
    normalized_follow_up = follow_up_result["normalized"]

    contacted_result = normalize_lead_datetime(last_contacted_at)
    if not contacted_result["ok"]:
        return _lead_result(ok=False, code=contacted_result["code"], error=contacted_result["error"], business_id=business_id)
    normalized_last_contacted = contacted_result["normalized"]

    relation_result = _validate_lead_relations(
        business_id, service_id=service_id, channel_id=channel_id, assigned_person_id=assigned_person_id,
    )
    if not relation_result["ok"]:
        return _lead_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id)

    matches = find_leads_by_idempotency_key(business_id, caller_idempotency_key)
    if len(matches) > 1:
        conflicting_ids = tuple(m["Lead ID"] for m in matches)
        return _lead_result(
            ok=False, code="MULTIPLE_LEAD_MATCHES",
            error=f"Найдено несколько Lead с этим ключом: {conflicting_ids}",
            business_id=business_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _lead_result(
            ok=True, code="LEAD_REUSED", error=None,
            lead_id=existing["Lead ID"], business_id=business_id,
            service_id=existing.get("Service ID", ""), channel_id=existing.get("Channel ID", ""),
            assigned_person_id=existing.get("Assigned Person ID", ""),
            converted_client_id=existing.get("Converted Client ID", ""),
            expected_value=existing.get("Expected Value", ""), currency=existing.get("Currency", ""),
            next_follow_up_at=existing.get("Next Follow-up At", ""), last_contacted_at=existing.get("Last Contacted At", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    duplicate_matches = find_leads_by_exact_contact_channels(
        business_id, phone=normalized_phone, whatsapp=normalized_whatsapp, email=normalized_email,
    )
    duplicate_contact_ids = tuple(m["Lead ID"] for m in duplicate_matches)
    warnings = ("LEAD_CONTACT_DUPLICATE_WARNING",) if duplicate_contact_ids else ()

    create_result = lm_create_lead(
        business_id, normalized_name,
        caller_idempotency_key=caller_idempotency_key,
        phone_snapshot=normalized_phone, whatsapp_snapshot=normalized_whatsapp, email_snapshot=normalized_email,
        company_snapshot=normalized_company, service_id=service_id, source=source, channel_id=channel_id,
        qualification_notes=qualification_notes, expected_value=normalized_expected_value, currency=normalized_currency,
        next_follow_up_at=normalized_follow_up, last_contacted_at=normalized_last_contacted,
        assigned_person_id=assigned_person_id, created_by=created_by, notes=notes,
    )
    if not create_result["ok"]:
        return _lead_result(ok=False, code="LEAD_PERSISTENCE_FAILED", error=create_result.get("error"), business_id=business_id, retry_safe=True)
    lead_id = create_result["lead_id"]

    saved = find_lead_by_id(lead_id)
    if saved is None:
        return _lead_result(
            ok=False, code="LEAD_POST_WRITE_VERIFICATION_FAILED",
            error="Lead записан, но проверка после записи не прошла",
            lead_id=lead_id, business_id=business_id, retry_safe=False,
        )

    return _lead_result(
        ok=True, code="LEAD_CREATED", error=None,
        lead_id=lead_id, business_id=business_id, service_id=service_id, channel_id=channel_id,
        assigned_person_id=assigned_person_id,
        expected_value=normalized_expected_value, currency=normalized_currency,
        next_follow_up_at=normalized_follow_up, last_contacted_at=normalized_last_contacted,
        final_status="new", created=True, retry_safe=True,
        duplicate_contact_ids=duplicate_contact_ids, warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────

def _transition_lead(
    lead_id: str, target_status: str, *,
    qualification_notes: str = "", disposition_reason: str = "", last_contacted_at: str = "",
) -> dict:
    """Internal shared transition engine for contacted/qualified/
    unqualified/lost/archived (ADR-024 §17-§23/§25). Conversion has its
    own dedicated function (convert_lead()) since it carries additional
    required fields and idempotent-target semantics."""
    from business_core.lead_manager import find_lead_by_id, update_lead_status, LEAD_STATUS

    if not lead_id:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error="lead_id обязателен")
    lead = find_lead_by_id(lead_id)
    if lead is None:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error=f"Lead {lead_id} не найден", lead_id=lead_id)

    business_id = lead.get("Business ID", "")
    previous_status = lead.get("Status", "")

    if target_status not in LEAD_STATUS:
        return _lead_result(
            ok=False, code="INVALID_LEAD_STATUS",
            error=f"Недопустимый статус '{target_status}'. Допустимые значения: {', '.join(LEAD_STATUS)}",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status == previous_status:
        return _lead_result(
            ok=True, code="LEAD_STATUS_UNCHANGED", error=None,
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status=target_status, final_status=previous_status, changed=False,
        )

    allowed_targets = _LEAD_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        code = "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION" if (target_status in _LEAD_ACTIVE_STATUSES and previous_status in ("unqualified", "lost", "archived")) else "INVALID_LEAD_TRANSITION"
        return _lead_result(
            ok=False, code=code, error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    if target_status in _LEAD_DISPOSITION_REQUIRED_STATUSES and not disposition_reason:
        return _lead_result(
            ok=False, code="LEAD_DISPOSITION_REASON_REQUIRED", error="disposition_reason обязателен",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    archived_at = _now_utc_str() if target_status == "archived" else ""
    write_result = update_lead_status(
        lead_id, target_status,
        qualification_notes=qualification_notes, disposition_reason=disposition_reason,
        last_contacted_at=last_contacted_at, archived_at=archived_at,
    )
    if not write_result["ok"]:
        return _lead_result(
            ok=False, code=write_result.get("code") or "LEAD_PERSISTENCE_FAILED", error=write_result.get("error"),
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    success_codes = {
        "contacted": "LEAD_CONTACTED", "qualified": "LEAD_QUALIFIED",
        "unqualified": "LEAD_UNQUALIFIED", "lost": "LEAD_LOST", "archived": "LEAD_ARCHIVED",
    }
    code = success_codes.get(target_status, "LEAD_STATUS_UPDATED") if changed else "LEAD_STATUS_UNCHANGED"
    final_status = target_status if changed else previous_status

    return _lead_result(
        ok=True, code=code, error=None,
        lead_id=lead_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status, final_status=final_status, changed=changed,
        contacted=(changed and target_status == "contacted"), qualified=(changed and target_status == "qualified"),
        unqualified=(changed and target_status == "unqualified"), lost=(changed and target_status == "lost"),
        archived=(changed and target_status == "archived"),
    )


def contact_lead(lead_id: str, *, last_contacted_at: str = "") -> dict:
    """ADR-024 §20: explicit new/qualified → contacted. Last Contacted
    At is set only when an explicit datetime is supplied — never
    auto-set to "now", never triggers Task/Interaction creation."""
    normalized_last_contacted = ""
    if last_contacted_at:
        dt_result = normalize_lead_datetime(last_contacted_at)
        if not dt_result["ok"]:
            from business_core.lead_manager import find_lead_by_id
            lead = find_lead_by_id(lead_id) or {}
            return _lead_result(
                ok=False, code=dt_result["code"], error=dt_result["error"],
                lead_id=lead_id, business_id=lead.get("Business ID", ""),
                previous_status=lead.get("Status", ""), requested_status="contacted", final_status=lead.get("Status", ""),
            )
        normalized_last_contacted = dt_result["normalized"]
    return _transition_lead(lead_id, "contacted", last_contacted_at=normalized_last_contacted)


def qualify_lead(lead_id: str, *, qualification_notes: str = "") -> dict:
    """ADR-024 §21: explicit allowed → qualified. Never creates a
    Commercial Offer, never auto-converts, never mutates Service."""
    return _transition_lead(lead_id, "qualified", qualification_notes=qualification_notes)


def unqualify_lead(lead_id: str, *, disposition_reason: str) -> dict:
    """ADR-024 §22: explicit allowed → unqualified. Disposition Reason
    required, set once, never logged. Terminal except archive."""
    return _transition_lead(lead_id, "unqualified", disposition_reason=disposition_reason)


def lose_lead(lead_id: str, *, disposition_reason: str) -> dict:
    """ADR-024 §23: explicit allowed → lost. Same privacy/immutability
    discipline as unqualify_lead(). Terminal except archive."""
    return _transition_lead(lead_id, "lost", disposition_reason=disposition_reason)


def archive_lead(lead_id: str) -> dict:
    """ADR-024 §25: explicit allowed → archived. Terminal — no restore,
    no hard delete. Exact-ID read still works afterward."""
    return _transition_lead(lead_id, "archived")


def convert_lead(lead_id: str, converted_client_id: str, converted_by: str) -> dict:
    """
    Phase 41C (ADR-024 §19/§24): the sole canonical Lead-to-Client
    conversion orchestration boundary. Converted Client ID must
    reference an existing, valid, same-Business Client — never creates
    or mutates a Client, never mutates Person fields. Naturally
    idempotent by status+target check (ADR-024 Option A): repeated
    conversion to the same Client is a safe no-op; conversion to a
    different Client after conversion already occurred is a conflict.
    """
    from business_core.lead_manager import find_lead_by_id, update_lead_status

    if not lead_id:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error="lead_id обязателен")
    lead = find_lead_by_id(lead_id)
    if lead is None:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error=f"Lead {lead_id} не найден", lead_id=lead_id)

    business_id = lead.get("Business ID", "")
    previous_status = lead.get("Status", "")

    if not converted_client_id:
        return _lead_result(
            ok=False, code="LEAD_CONVERSION_CLIENT_REQUIRED", error="converted_client_id обязателен",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status="converted", final_status=previous_status,
        )
    if not converted_by:
        return _lead_result(
            ok=False, code="LEAD_CONVERSION_ACTOR_REQUIRED", error="converted_by обязателен",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status="converted", final_status=previous_status,
        )

    existing_converted_client_id = lead.get("Converted Client ID", "")
    if previous_status == "converted":
        if existing_converted_client_id == converted_client_id:
            return _lead_result(
                ok=True, code="LEAD_STATUS_UNCHANGED", error=None,
                lead_id=lead_id, business_id=business_id,
                service_id=lead.get("Service ID", ""), channel_id=lead.get("Channel ID", ""),
                assigned_person_id=lead.get("Assigned Person ID", ""), converted_client_id=existing_converted_client_id,
                previous_status=previous_status, requested_status="converted", final_status="converted", changed=False,
            )
        return _lead_result(
            ok=False, code="LEAD_CONVERSION_TARGET_CONFLICT",
            error=f"Lead {lead_id} уже конвертирован в Client {existing_converted_client_id} — конверсия в другой Client запрещена",
            lead_id=lead_id, business_id=business_id, converted_client_id=existing_converted_client_id,
            previous_status=previous_status, requested_status="converted", final_status="converted",
        )

    allowed_targets = _LEAD_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if "converted" not in allowed_targets:
        return _lead_result(
            ok=False, code="INVALID_LEAD_TRANSITION", error=f"Переход '{previous_status}' → 'converted' не разрешён",
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status="converted", final_status=previous_status,
        )

    client_check = _validate_lead_conversion_target(business_id, converted_client_id)
    if not client_check["ok"]:
        return _lead_result(
            ok=False, code=client_check["code"], error=client_check["error"],
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status="converted", final_status=previous_status,
        )

    now = _now_utc_str()
    write_result = update_lead_status(lead_id, "converted", converted_client_id=converted_client_id, converted_at=now, converted_by=converted_by)
    if not write_result["ok"]:
        return _lead_result(
            ok=False, code=write_result.get("code") or "LEAD_PERSISTENCE_FAILED", error=write_result.get("error"),
            lead_id=lead_id, business_id=business_id, previous_status=previous_status, requested_status="converted", final_status=previous_status,
        )

    changed = write_result["changed"]
    return _lead_result(
        ok=True, code="LEAD_CONVERTED" if changed else "LEAD_STATUS_UNCHANGED", error=None,
        lead_id=lead_id, business_id=business_id, converted_client_id=converted_client_id,
        previous_status=previous_status, requested_status="converted", final_status="converted", changed=changed, converted=changed,
    )


# ─────────────────────────────────────────────────────────────
# Active-Lead updates
# ─────────────────────────────────────────────────────────────

def update_lead(lead_id: str, updates: dict) -> dict:
    """
    Phase 41C (ADR-024 §23/§26): active-status commercial/contact-field
    update. Mutable only while Status is new/contacted/qualified.
    Every supplied override is revalidated exactly like creation; the
    contact-channel requirement must remain satisfied after the update;
    duplicate-contact warning is recalculated when any contact channel
    changes. Identity/Business/idempotency/status/conversion/audit
    fields are never accepted here — use the dedicated transition/
    conversion/admin functions instead.
    """
    from business_core.lead_manager import find_lead_by_id, update_lead_active_fields

    if not lead_id:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error="lead_id обязателен")
    lead = find_lead_by_id(lead_id)
    if lead is None:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error=f"Lead {lead_id} не найден", lead_id=lead_id)

    business_id = lead.get("Business ID", "")
    status = lead.get("Status", "")

    if status not in _LEAD_ACTIVE_STATUSES:
        return _lead_result(
            ok=False, code="LEAD_IMMUTABLE", error=f"Lead {lead_id} в статусе '{status}' — коммерческие/контактные поля более не изменяемы",
            lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status,
        )

    resolved_name = lead.get("Contact Name Snapshot", "")
    if "Contact Name Snapshot" in updates:
        name_result = _validate_lead_contact_name(updates["Contact Name Snapshot"])
        if not name_result["ok"]:
            return _lead_result(ok=False, code=name_result["code"], error=name_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        resolved_name = name_result["name"]

    resolved_phone = lead.get("Phone Snapshot", "")
    if "Phone Snapshot" in updates:
        phone_result = normalize_lead_phone(updates["Phone Snapshot"])
        if not phone_result["ok"]:
            return _lead_result(ok=False, code=phone_result["code"], error=phone_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        resolved_phone = phone_result["normalized"]

    resolved_whatsapp = lead.get("WhatsApp Snapshot", "")
    if "WhatsApp Snapshot" in updates:
        whatsapp_result = normalize_lead_whatsapp(updates["WhatsApp Snapshot"])
        if not whatsapp_result["ok"]:
            return _lead_result(ok=False, code=whatsapp_result["code"], error=whatsapp_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        resolved_whatsapp = whatsapp_result["normalized"]

    resolved_email = lead.get("Email Snapshot", "")
    if "Email Snapshot" in updates:
        email_result = normalize_lead_email(updates["Email Snapshot"])
        if not email_result["ok"]:
            return _lead_result(ok=False, code=email_result["code"], error=email_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        resolved_email = email_result["normalized"]

    channel_touched = any(f in updates for f in ("Phone Snapshot", "WhatsApp Snapshot", "Email Snapshot"))
    channel_check = _validate_lead_contact_channel(resolved_phone, resolved_whatsapp, resolved_email)
    if not channel_check["ok"]:
        return _lead_result(ok=False, code=channel_check["code"], error=channel_check["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)

    prepared: dict = {}
    if "Contact Name Snapshot" in updates:
        prepared["Contact Name Snapshot"] = resolved_name
    if "Phone Snapshot" in updates:
        prepared["Phone Snapshot"] = resolved_phone
    if "WhatsApp Snapshot" in updates:
        prepared["WhatsApp Snapshot"] = resolved_whatsapp
    if "Email Snapshot" in updates:
        prepared["Email Snapshot"] = resolved_email
    if "Company Snapshot" in updates:
        prepared["Company Snapshot"] = _normalize_lead_company(updates["Company Snapshot"])

    resolved_expected_value = lead.get("Expected Value", "")
    resolved_currency = lead.get("Currency", "")
    if "Expected Value" in updates or "Currency" in updates:
        value_result = _validate_lead_expected_value_pair(
            updates.get("Expected Value", lead.get("Expected Value", "")),
            updates.get("Currency", lead.get("Currency", "")),
        )
        if not value_result["ok"]:
            return _lead_result(ok=False, code=value_result["code"], error=value_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        resolved_expected_value = value_result["expected_value"]
        resolved_currency = value_result["currency"]
        prepared["Expected Value"] = resolved_expected_value
        prepared["Currency"] = resolved_currency

    if "Next Follow-up At" in updates:
        follow_up_result = normalize_lead_datetime(updates["Next Follow-up At"])
        if not follow_up_result["ok"]:
            return _lead_result(ok=False, code=follow_up_result["code"], error=follow_up_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        prepared["Next Follow-up At"] = follow_up_result["normalized"]

    if "Last Contacted At" in updates:
        contacted_result = normalize_lead_datetime(updates["Last Contacted At"])
        if not contacted_result["ok"]:
            return _lead_result(ok=False, code=contacted_result["code"], error=contacted_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        prepared["Last Contacted At"] = contacted_result["normalized"]

    resolved_service_id = updates.get("Service ID", lead.get("Service ID", ""))
    resolved_channel_id = updates.get("Channel ID", lead.get("Channel ID", ""))
    resolved_assigned_person_id = updates.get("Assigned Person ID", lead.get("Assigned Person ID", ""))
    if any(f in updates for f in ("Service ID", "Channel ID", "Assigned Person ID")):
        relation_result = _validate_lead_relations(
            business_id, service_id=resolved_service_id, channel_id=resolved_channel_id, assigned_person_id=resolved_assigned_person_id,
        )
        if not relation_result["ok"]:
            return _lead_result(ok=False, code=relation_result["code"], error=relation_result["error"], lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status)
        for field in ("Service ID", "Channel ID", "Assigned Person ID"):
            if field in updates:
                prepared[field] = updates[field]

    if "Source" in updates:
        prepared["Source"] = updates["Source"]
    if "Qualification Notes" in updates:
        prepared["Qualification Notes"] = updates["Qualification Notes"]
    if "Notes" in updates:
        prepared["Notes"] = updates["Notes"]

    duplicate_contact_ids: tuple = ()
    warnings: tuple = ()
    if channel_touched:
        from business_core.lead_manager import find_leads_by_exact_contact_channels
        duplicate_matches = find_leads_by_exact_contact_channels(
            business_id, phone=resolved_phone, whatsapp=resolved_whatsapp, email=resolved_email, exclude_lead_id=lead_id,
        )
        duplicate_contact_ids = tuple(m["Lead ID"] for m in duplicate_matches)
        warnings = ("LEAD_CONTACT_DUPLICATE_WARNING",) if duplicate_contact_ids else ()

    write_result = update_lead_active_fields(lead_id, prepared)
    if not write_result["ok"]:
        return _lead_result(
            ok=False, code=write_result.get("code") or "LEAD_IMMUTABLE", error=write_result.get("error"),
            lead_id=lead_id, business_id=business_id, previous_status=status, final_status=status,
        )

    changed = write_result["changed"]
    return _lead_result(
        ok=True, code="LEAD_UPDATED" if changed else "LEAD_UPDATE_UNCHANGED", error=None,
        lead_id=lead_id, business_id=business_id, service_id=resolved_service_id, channel_id=resolved_channel_id,
        assigned_person_id=resolved_assigned_person_id, expected_value=resolved_expected_value, currency=resolved_currency,
        previous_status=status, final_status=status, changed=changed,
        duplicate_contact_ids=duplicate_contact_ids, warnings=warnings,
    )


def update_lead_admin_fields(lead_id: str, updates: dict) -> dict:
    """Phase 41C (ADR-024 §27): thin resolve-then-delegate wrapper.
    Only Notes is ordinarily mutable, in every status including
    terminal ones — Notes is never logged."""
    from business_core.lead_manager import find_lead_by_id, update_lead_admin_fields as lm_update_admin

    if not lead_id:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error="lead_id обязателен")
    lead = find_lead_by_id(lead_id)
    if lead is None:
        return _lead_result(ok=False, code="LEAD_NOT_FOUND", error=f"Lead {lead_id} не найден", lead_id=lead_id)

    write_result = lm_update_admin(lead_id, updates)
    if not write_result["ok"]:
        return _lead_result(
            ok=False, code=write_result.get("code") or "LEAD_IMMUTABLE", error=write_result.get("error"),
            lead_id=lead_id, business_id=lead.get("Business ID", ""), previous_status=lead.get("Status", ""), final_status=lead.get("Status", ""),
        )

    changed = write_result["changed"]
    return _lead_result(
        ok=True, code="LEAD_UPDATED" if changed else "LEAD_UPDATE_UNCHANGED", error=None,
        lead_id=lead_id, business_id=lead.get("Business ID", ""),
        previous_status=lead.get("Status", ""), final_status=lead.get("Status", ""), changed=changed,
    )


# ─────────────────────────────────────────────────────────────
# Follow-up due (stateless read-only helper)
# ─────────────────────────────────────────────────────────────

def is_lead_follow_up_due(lead: dict, *, reference_datetime: datetime | None = None) -> bool:
    """
    Phase 41C (ADR-024 §29): stateless read-only helper — never writes,
    never mutates Status, never creates a Task. archived/converted/
    lost/unqualified Leads never qualify, regardless of Next Follow-up
    At, since no further sales action is expected on them.
    """
    if lead.get("Status", "") not in _LEAD_ACTIVE_STATUSES:
        return False
    raw = lead.get("Next Follow-up At", "")
    if not raw:
        return False
    try:
        candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        follow_up_at = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    if follow_up_at.tzinfo is None:
        return False

    from datetime import timezone as _timezone
    now = reference_datetime or datetime.now(_timezone.utc)
    return follow_up_at <= now


# ─────────────────────────────────────────────────────────────
# Interaction / Communication History Domain (Phase 42C, ADR-025)
#
# Canonical immutable Interaction event, channel-neutral, fully
# separate from RelationshipTouch/relationship_capital (ADR-025 §1/§2)
# and from technical Audit Events (ADR-025 §26) — no reuse, no write,
# no import anywhere in this section. interaction_manager.py is the
# sole persistence owner; every function below is this domain's sole
# orchestration boundary, exactly mirroring the Lead/Payment/Commercial
# Offer sections above.
#
# Exactly one primary subject is required: Lead ID XOR Client ID
# (ADR-025 §8) — never both, never neither, never arbitrarily chosen.
# ─────────────────────────────────────────────────────────────

_INTERACTION_TYPES = ("call", "message", "email", "meeting", "note", "other")
_INTERACTION_DIRECTIONS = ("inbound", "outbound", "internal")
_INTERACTION_DIRECTION_OPTIONAL_TYPES = frozenset({"note"})

_INTERACTION_SUMMARY_MAX_LENGTH = 2000
_INTERACTION_OUTCOME_MAX_LENGTH = 1000
_INTERACTION_NOTES_MAX_LENGTH = 5000
_INTERACTION_EXTERNAL_REFERENCE_MAX_LENGTH = 500
from datetime import timedelta as _timedelta

_INTERACTION_OCCURRED_AT_FUTURE_TOLERANCE = _timedelta(minutes=5)

_INTERACTION_ORDINARY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "active":   ("active", "archived"),
    "archived": ("archived",),
}


def _interaction_result(
    *, ok: bool, code: str, error: str | None,
    interaction_id: str = "", business_id: str = "",
    lead_id: str = "", client_id: str = "", commercial_offer_id: str = "",
    channel_id: str = "", assigned_person_id: str = "",
    interaction_type: str = "", direction: str = "", occurred_at: str = "",
    previous_status: str = "", requested_status: str = "", final_status: str = "",
    created: bool = False, reused: bool = False, changed: bool = False, archived: bool = False,
    conflicting_ids: tuple = (), warnings: tuple = (), retry_safe: bool = True,
) -> dict:
    """Shared result-builder for every Interaction orchestration
    function (ADR-025 §27) — the stable, structured contract every
    caller reads instead of a bare exception or ad-hoc dict shape.
    Never carries Summary/Outcome/Notes/External Reference, a raw
    exception, a raw Sheets row, or any Telegram-specific Russian
    string."""
    return {
        "ok": ok, "code": code, "error": error,
        "interaction_id": interaction_id, "business_id": business_id,
        "lead_id": lead_id, "client_id": client_id, "commercial_offer_id": commercial_offer_id,
        "channel_id": channel_id, "assigned_person_id": assigned_person_id,
        "interaction_type": interaction_type, "direction": direction, "occurred_at": occurred_at,
        "previous_status": previous_status, "requested_status": requested_status, "final_status": final_status,
        "created": created, "reused": reused, "changed": changed, "archived": archived,
        "conflicting_ids": tuple(conflicting_ids), "warnings": tuple(warnings), "retry_safe": retry_safe,
    }


# ─────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────

def normalize_interaction_type(raw) -> dict:
    """ADR-025 §11: closed vocabulary. Required, trimmed, lowercased.
    WhatsApp/Telegram are Channel values, never Interaction Type."""
    text = str(raw or "").strip().lower()
    if not text:
        return {"ok": False, "code": "INTERACTION_TYPE_REQUIRED", "error": "interaction_type обязателен", "normalized": ""}
    if text not in _INTERACTION_TYPES:
        return {
            "ok": False, "code": "INVALID_INTERACTION_TYPE",
            "error": f"Недопустимый interaction_type '{raw}'. Допустимые значения: {', '.join(_INTERACTION_TYPES)}",
            "normalized": "",
        }
    return {"ok": True, "code": "", "error": None, "normalized": text}


def normalize_interaction_direction(raw, interaction_type: str) -> dict:
    """
    ADR-025 §12/§14: Direction required for every Interaction Type
    except `note`, where it is optional. No implicit default is ever
    invented — an empty value for a required type blocks; a blank value
    for `note` stays blank.
    """
    text = str(raw or "").strip().lower()
    if not text:
        if interaction_type in _INTERACTION_DIRECTION_OPTIONAL_TYPES:
            return {"ok": True, "code": "", "error": None, "normalized": ""}
        return {"ok": False, "code": "INTERACTION_DIRECTION_REQUIRED", "error": "direction обязателен для этого interaction_type", "normalized": ""}

    if text not in _INTERACTION_DIRECTIONS:
        return {
            "ok": False, "code": "INVALID_INTERACTION_DIRECTION",
            "error": f"Недопустимый direction '{raw}'. Допустимые значения: {', '.join(_INTERACTION_DIRECTIONS)}",
            "normalized": "",
        }
    return {"ok": True, "code": "", "error": None, "normalized": text}


def normalize_interaction_occurred_at(raw, *, reference_datetime: datetime | None = None) -> dict:
    """
    ADR-025 §13: deterministic ISO-8601/RFC3339 validation for Occurred
    At. Required. Requires an explicit timezone offset (a trailing "Z"
    is accepted as UTC shorthand) — timezone-naive values are rejected
    outright. Historical values are allowed; values later than
    reference time + 5 minutes block (small clock-skew tolerance only).

    Returns:
        {"ok": bool, "code": str, "error": str | None, "normalized": str}
    """
    text = str(raw or "").strip()
    if not text:
        return {"ok": False, "code": "INTERACTION_OCCURRED_AT_REQUIRED", "error": "occurred_at обязателен", "normalized": ""}

    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return {"ok": False, "code": "INVALID_INTERACTION_OCCURRED_AT", "error": f"Некорректная дата/время '{raw}' — требуется ISO-8601 с явным часовым поясом", "normalized": ""}

    if parsed.tzinfo is None:
        return {"ok": False, "code": "INVALID_INTERACTION_OCCURRED_AT", "error": f"'{raw}' не содержит явного часового пояса", "normalized": ""}

    from datetime import timezone as _timezone
    now = reference_datetime or datetime.now(_timezone.utc)
    if parsed > now + _INTERACTION_OCCURRED_AT_FUTURE_TOLERANCE:
        return {"ok": False, "code": "INTERACTION_OCCURRED_AT_IN_FUTURE", "error": f"occurred_at ({text}) не может быть в будущем более чем на 5 минут", "normalized": ""}

    return {"ok": True, "code": "", "error": None, "normalized": parsed.isoformat()}


def _validate_interaction_summary(raw) -> dict:
    """ADR-025 §14: required, trimmed, bounded. Never logged by any
    caller."""
    text = str(raw or "").strip()
    if not text:
        return {"ok": False, "code": "INTERACTION_SUMMARY_REQUIRED", "error": "summary обязателен", "normalized": ""}
    if len(text) > _INTERACTION_SUMMARY_MAX_LENGTH:
        return {"ok": False, "code": "INTERACTION_SUMMARY_TOO_LONG", "error": f"summary превышает {_INTERACTION_SUMMARY_MAX_LENGTH} символов", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": text}


def _validate_interaction_outcome(raw) -> dict:
    """ADR-025 §14: optional, trimmed, bounded."""
    text = str(raw or "").strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    if len(text) > _INTERACTION_OUTCOME_MAX_LENGTH:
        return {"ok": False, "code": "INTERACTION_OUTCOME_TOO_LONG", "error": f"outcome превышает {_INTERACTION_OUTCOME_MAX_LENGTH} символов", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": text}


def _validate_interaction_notes(raw) -> dict:
    """ADR-025 §14: optional, bounded, mutable after creation."""
    text = str(raw or "").strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    if len(text) > _INTERACTION_NOTES_MAX_LENGTH:
        return {"ok": False, "code": "INTERACTION_NOTES_TOO_LONG", "error": f"notes превышает {_INTERACTION_NOTES_MAX_LENGTH} символов", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": text}


def _validate_interaction_external_reference(raw) -> dict:
    """ADR-025 §16/§18: optional, bounded, never identity, never
    logged, no provider-specific parsing."""
    text = str(raw or "").strip()
    if not text:
        return {"ok": True, "code": "", "error": None, "normalized": ""}
    if len(text) > _INTERACTION_EXTERNAL_REFERENCE_MAX_LENGTH:
        return {"ok": False, "code": "INTERACTION_EXTERNAL_REFERENCE_TOO_LONG", "error": f"external_reference превышает {_INTERACTION_EXTERNAL_REFERENCE_MAX_LENGTH} символов", "normalized": ""}
    return {"ok": True, "code": "", "error": None, "normalized": text}


# ─────────────────────────────────────────────────────────────
# Relation validation
# ─────────────────────────────────────────────────────────────

def _validate_interaction_subject(business_id: str, lead_id: str, client_id: str) -> dict:
    """
    ADR-025 §8/§10: exactly one primary subject — Lead ID XOR Client
    ID. Neither present blocks; both present block. Never an arbitrary
    selection. Read-only existence + same-Business validation only —
    never mutates Lead or Client.
    """
    has_lead = bool(lead_id)
    has_client = bool(client_id)

    if not has_lead and not has_client:
        return {"ok": False, "code": "INTERACTION_SUBJECT_REQUIRED", "error": "требуется ровно один субъект: lead_id либо client_id"}
    if has_lead and has_client:
        return {"ok": False, "code": "INTERACTION_SUBJECT_CONFLICT", "error": "нельзя одновременно указать lead_id и client_id"}

    if has_lead:
        from business_core.lead_manager import find_lead_by_id
        lead = find_lead_by_id(lead_id)
        if lead is None:
            return {"ok": False, "code": "LEAD_NOT_FOUND", "error": f"Lead {lead_id} не найден"}
        if lead.get("Business ID", "") != business_id:
            return {"ok": False, "code": "INTERACTION_RELATION_MISMATCH", "error": f"Lead {lead_id} принадлежит другому Business"}
        return {"ok": True, "code": "", "error": None}

    from business_core.person_manager import find_person_by_id, is_person_archived, is_client_person, has_person_business_link
    client = find_person_by_id(client_id)
    if client is None:
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} не найден"}
    if is_person_archived(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"Client {client_id} архивирован"}
    if not is_client_person(client):
        return {"ok": False, "code": "CLIENT_NOT_FOUND", "error": f"{client_id} не является Client"}
    if not has_person_business_link(client, business_id):
        return {"ok": False, "code": "INTERACTION_RELATION_MISMATCH", "error": f"Client {client_id} не связан с Business {business_id}"}
    return {"ok": True, "code": "", "error": None}


def _validate_interaction_relations(
    business_id: str, *, commercial_offer_id: str = "", channel_id: str = "", assigned_person_id: str = "",
) -> dict:
    """ADR-025 §9: optional read-only context references. Exact
    existence + same-Business validation. Never mutates Commercial
    Offer/Channel/Person/Organization."""
    from business_core.sheets import read_business_sheet

    if commercial_offer_id:
        from business_core.offer_manager import find_commercial_offer_by_id
        offer = find_commercial_offer_by_id(commercial_offer_id)
        if offer is None:
            return {"ok": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": f"Commercial Offer {commercial_offer_id} не найден"}
        if offer.get("Business ID", "") != business_id:
            return {"ok": False, "code": "INTERACTION_RELATION_MISMATCH", "error": f"Commercial Offer {commercial_offer_id} принадлежит другому Business"}

    if channel_id:
        channels = read_business_sheet("channel_registry")
        channel = next((c for c in channels if c.get("ID", "") == channel_id), None)
        if channel is None:
            return {"ok": False, "code": "CHANNEL_NOT_FOUND", "error": f"Channel {channel_id} не найден"}
        ch_biz_id = channel.get("Бизнес ID", "")
        if ch_biz_id and ch_biz_id != business_id:
            return {"ok": False, "code": "INTERACTION_RELATION_MISMATCH", "error": f"Channel {channel_id} принадлежит другому Business"}

    if assigned_person_id:
        from business_core.person_manager import find_person_by_id, is_person_archived, has_person_business_link
        person = find_person_by_id(assigned_person_id)
        if person is None:
            return {"ok": False, "code": "PERSON_NOT_FOUND", "error": f"Person {assigned_person_id} не найден"}
        if is_person_archived(person):
            return {"ok": False, "code": "PERSON_NOT_FOUND", "error": f"Person {assigned_person_id} архивирован"}
        if not has_person_business_link(person, business_id):
            return {"ok": False, "code": "INTERACTION_RELATION_MISMATCH", "error": f"Person {assigned_person_id} не связан с Business {business_id}"}

    return {"ok": True, "code": "", "error": None}


# ─────────────────────────────────────────────────────────────
# Creation
# ─────────────────────────────────────────────────────────────

def create_interaction(
    business_id: str, interaction_type: str, occurred_at: str, summary: str,
    *, created_by: str, caller_idempotency_key: str,
    direction: str = "", channel_id: str = "", outcome: str = "",
    lead_id: str = "", client_id: str = "", commercial_offer_id: str = "",
    assigned_person_id: str = "", external_reference: str = "", notes: str = "",
) -> dict:
    """
    Phase 42C (ADR-025 §17): the sole canonical Interaction creation
    orchestration boundary.

    Validation order, all before any write:
      A. required business_id / created_by / caller_idempotency_key
      B. Interaction Type normalization
      C. Direction normalization (type-dependent requirement)
      D. Occurred At normalization
      E. Summary/Outcome/Notes/External Reference validation
      F. Business existence
      G. primary-subject XOR validation (Lead ID XOR Client ID)
      H. optional relation validation (Offer/Channel/Assigned Person)
      I. idempotency lookup (zero/one/multiple)
      J. Interaction ID generated only after A-I pass
      K. low-level persistence
      L. post-write verification
      M. structured result
    """
    from business_core.sheets import read_business_sheet
    from business_core.interaction_manager import (
        find_interactions_by_idempotency_key, create_interaction as im_create_interaction,
        find_interaction_by_id,
    )

    if not business_id:
        return _interaction_result(ok=False, code="BUSINESS_NOT_FOUND", error="business_id обязателен")
    if not created_by:
        return _interaction_result(ok=False, code="INTERACTION_PERSISTENCE_FAILED", error="created_by обязателен", business_id=business_id)
    if not caller_idempotency_key:
        return _interaction_result(ok=False, code="INTERACTION_IDEMPOTENCY_REQUIRED", error="caller_idempotency_key обязателен", business_id=business_id)

    type_result = normalize_interaction_type(interaction_type)
    if not type_result["ok"]:
        return _interaction_result(ok=False, code=type_result["code"], error=type_result["error"], business_id=business_id)
    normalized_type = type_result["normalized"]

    direction_result = normalize_interaction_direction(direction, normalized_type)
    if not direction_result["ok"]:
        return _interaction_result(ok=False, code=direction_result["code"], error=direction_result["error"], business_id=business_id)
    normalized_direction = direction_result["normalized"]

    occurred_result = normalize_interaction_occurred_at(occurred_at)
    if not occurred_result["ok"]:
        return _interaction_result(ok=False, code=occurred_result["code"], error=occurred_result["error"], business_id=business_id)
    normalized_occurred_at = occurred_result["normalized"]

    summary_result = _validate_interaction_summary(summary)
    if not summary_result["ok"]:
        return _interaction_result(ok=False, code=summary_result["code"], error=summary_result["error"], business_id=business_id)
    normalized_summary = summary_result["normalized"]

    outcome_result = _validate_interaction_outcome(outcome)
    if not outcome_result["ok"]:
        return _interaction_result(ok=False, code=outcome_result["code"], error=outcome_result["error"], business_id=business_id)
    normalized_outcome = outcome_result["normalized"]

    notes_result = _validate_interaction_notes(notes)
    if not notes_result["ok"]:
        return _interaction_result(ok=False, code=notes_result["code"], error=notes_result["error"], business_id=business_id)
    normalized_notes = notes_result["normalized"]

    external_ref_result = _validate_interaction_external_reference(external_reference)
    if not external_ref_result["ok"]:
        return _interaction_result(ok=False, code=external_ref_result["code"], error=external_ref_result["error"], business_id=business_id)
    normalized_external_reference = external_ref_result["normalized"]

    biz_rows = read_business_sheet("biz_registry")
    if not any(b.get("ID", "") == business_id for b in biz_rows):
        return _interaction_result(ok=False, code="BUSINESS_NOT_FOUND", error=f"Business {business_id} не найден", business_id=business_id)

    subject_result = _validate_interaction_subject(business_id, lead_id, client_id)
    if not subject_result["ok"]:
        return _interaction_result(ok=False, code=subject_result["code"], error=subject_result["error"], business_id=business_id)

    relation_result = _validate_interaction_relations(
        business_id, commercial_offer_id=commercial_offer_id, channel_id=channel_id, assigned_person_id=assigned_person_id,
    )
    if not relation_result["ok"]:
        return _interaction_result(ok=False, code=relation_result["code"], error=relation_result["error"], business_id=business_id)

    matches = find_interactions_by_idempotency_key(business_id, caller_idempotency_key)
    if len(matches) > 1:
        conflicting_ids = tuple(m["Interaction ID"] for m in matches)
        return _interaction_result(
            ok=False, code="MULTIPLE_INTERACTION_MATCHES",
            error=f"Найдено несколько Interaction с этим ключом: {conflicting_ids}",
            business_id=business_id, conflicting_ids=conflicting_ids, retry_safe=True,
        )
    if len(matches) == 1:
        existing = matches[0]
        return _interaction_result(
            ok=True, code="INTERACTION_REUSED", error=None,
            interaction_id=existing["Interaction ID"], business_id=business_id,
            lead_id=existing.get("Lead ID", ""), client_id=existing.get("Client ID", ""),
            commercial_offer_id=existing.get("Commercial Offer ID", ""), channel_id=existing.get("Channel ID", ""),
            assigned_person_id=existing.get("Assigned Person ID", ""),
            interaction_type=existing.get("Interaction Type", ""), direction=existing.get("Direction", ""),
            occurred_at=existing.get("Occurred At", ""),
            final_status=existing.get("Status", ""), reused=True, retry_safe=True,
        )

    create_result = im_create_interaction(
        business_id, normalized_type, normalized_occurred_at, normalized_summary,
        caller_idempotency_key=caller_idempotency_key, direction=normalized_direction, channel_id=channel_id,
        outcome=normalized_outcome, lead_id=lead_id, client_id=client_id,
        commercial_offer_id=commercial_offer_id, assigned_person_id=assigned_person_id,
        external_reference=normalized_external_reference, created_by=created_by, notes=normalized_notes,
    )
    if not create_result["ok"]:
        return _interaction_result(ok=False, code="INTERACTION_PERSISTENCE_FAILED", error=create_result.get("error"), business_id=business_id, retry_safe=True)
    interaction_id = create_result["interaction_id"]

    saved = find_interaction_by_id(interaction_id)
    if saved is None:
        return _interaction_result(
            ok=False, code="INTERACTION_POST_WRITE_VERIFICATION_FAILED",
            error="Interaction записан, но проверка после записи не прошла",
            interaction_id=interaction_id, business_id=business_id, retry_safe=False,
        )

    return _interaction_result(
        ok=True, code="INTERACTION_CREATED", error=None,
        interaction_id=interaction_id, business_id=business_id,
        lead_id=lead_id, client_id=client_id, commercial_offer_id=commercial_offer_id,
        channel_id=channel_id, assigned_person_id=assigned_person_id,
        interaction_type=normalized_type, direction=normalized_direction, occurred_at=normalized_occurred_at,
        final_status="active", created=True, retry_safe=True,
    )


# ─────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────

def archive_interaction(interaction_id: str) -> dict:
    """
    Phase 42C (ADR-025 §19/§22): the sole canonical active → archived
    orchestration boundary. Terminal — no restore, no hard delete.
    Exact-ID read still works afterward.
    """
    from business_core.interaction_manager import find_interaction_by_id, update_interaction_status, INTERACTION_STATUS

    if not interaction_id:
        return _interaction_result(ok=False, code="INTERACTION_NOT_FOUND", error="interaction_id обязателен")
    interaction = find_interaction_by_id(interaction_id)
    if interaction is None:
        return _interaction_result(ok=False, code="INTERACTION_NOT_FOUND", error=f"Interaction {interaction_id} не найден", interaction_id=interaction_id)

    business_id = interaction.get("Business ID", "")
    previous_status = interaction.get("Status", "")
    target_status = "archived"

    if target_status == previous_status:
        return _interaction_result(
            ok=True, code="INTERACTION_STATUS_UNCHANGED", error=None,
            interaction_id=interaction_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status, changed=False,
        )

    allowed_targets = _INTERACTION_ORDINARY_TRANSITIONS.get(previous_status, (previous_status,))
    if target_status not in allowed_targets:
        return _interaction_result(
            ok=False, code="INVALID_INTERACTION_TRANSITION",
            error=f"Переход '{previous_status}' → '{target_status}' не разрешён",
            interaction_id=interaction_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    now = _now_utc_str()
    write_result = update_interaction_status(interaction_id, target_status, archived_at=now)
    if not write_result["ok"]:
        return _interaction_result(
            ok=False, code=write_result.get("code") or "INTERACTION_PERSISTENCE_FAILED", error=write_result.get("error"),
            interaction_id=interaction_id, business_id=business_id,
            previous_status=previous_status, requested_status=target_status, final_status=previous_status,
        )

    changed = write_result["changed"]
    return _interaction_result(
        ok=True, code="INTERACTION_ARCHIVED" if changed else "INTERACTION_STATUS_UNCHANGED", error=None,
        interaction_id=interaction_id, business_id=business_id,
        previous_status=previous_status, requested_status=target_status,
        final_status=target_status if changed else previous_status, changed=changed, archived=changed,
    )


def update_interaction_notes(interaction_id: str, notes: str) -> dict:
    """
    Phase 42C (ADR-025 §21/§23): thin resolve-then-delegate wrapper.
    Only Notes is ordinarily mutable, in every status (active and
    archived) — every other Interaction fact is immutable and has no
    update path.
    """
    from business_core.interaction_manager import find_interaction_by_id, update_interaction_admin_fields as im_update_admin

    if not interaction_id:
        return _interaction_result(ok=False, code="INTERACTION_NOT_FOUND", error="interaction_id обязателен")
    interaction = find_interaction_by_id(interaction_id)
    if interaction is None:
        return _interaction_result(ok=False, code="INTERACTION_NOT_FOUND", error=f"Interaction {interaction_id} не найден", interaction_id=interaction_id)

    notes_result = _validate_interaction_notes(notes)
    if not notes_result["ok"]:
        return _interaction_result(
            ok=False, code=notes_result["code"], error=notes_result["error"],
            interaction_id=interaction_id, business_id=interaction.get("Business ID", ""),
            previous_status=interaction.get("Status", ""), final_status=interaction.get("Status", ""),
        )

    write_result = im_update_admin(interaction_id, {"Notes": notes_result["normalized"]})
    if not write_result["ok"]:
        return _interaction_result(
            ok=False, code=write_result.get("code") or "INTERACTION_IMMUTABLE", error=write_result.get("error"),
            interaction_id=interaction_id, business_id=interaction.get("Business ID", ""),
            previous_status=interaction.get("Status", ""), final_status=interaction.get("Status", ""),
        )

    changed = write_result["changed"]
    return _interaction_result(
        ok=True, code="INTERACTION_NOTES_UPDATED" if changed else "INTERACTION_NOTES_UNCHANGED", error=None,
        interaction_id=interaction_id, business_id=interaction.get("Business ID", ""),
        previous_status=interaction.get("Status", ""), final_status=interaction.get("Status", ""), changed=changed,
    )


# ─────────────────────────────────────────────────────────────
# Phase 17B: Identity & Access Control Foundation — Owner Bootstrap
# Orchestration.
#
# This is the ONLY approved way to create an OWNER Access Role
# Assignment in Phase 17B (identity_manager.assign_access_role()
# categorically rejects Role == "OWNER" — see its docstring). This
# function must NEVER be called from application startup, Telegram
# handler registration, or any import side effect — it is invoked
# exclusively and explicitly from migrate_identity_registries.py's
# --bootstrap-owner CLI flag, requiring its own separate exact "YES"
# confirmation.
# ─────────────────────────────────────────────────────────────

def bootstrap_owner_from_env(*, dry_run: bool = True) -> dict:
    """
    Reads BC_OWNER_TELEGRAM_USER_ID from the environment — never
    accepted as a function argument, so it can only ever be driven by
    deployment configuration, never by any caller-supplied value.

    Returns a structured result (see Phase 17B design):
        {
            "ok": bool, "code": str, "changed": bool, "retry_safe": bool,
            "dry_run": bool,
            "completed_steps": tuple[str, ...], "failed_step": str,
            "created_ids": dict, "verification_errors": tuple[str, ...],
        }
    """
    from business_core import identity_manager as im

    def _result(*, ok, code, changed=False, retry_safe=True, completed_steps=(), failed_step="",
                created_ids=None, verification_errors=()):
        return {
            "ok": ok, "code": code, "changed": changed, "retry_safe": retry_safe, "dry_run": dry_run,
            "completed_steps": tuple(completed_steps), "failed_step": failed_step,
            "created_ids": created_ids or {}, "verification_errors": tuple(verification_errors),
        }

    raw_env = os.getenv("BC_OWNER_TELEGRAM_USER_ID", "").strip()
    if not raw_env:
        return _result(ok=False, code="OWNER_ENV_MISSING")
    if not im.is_valid_telegram_user_id(raw_env):
        return _result(ok=False, code="OWNER_ENV_INVALID")

    # Existing-owner detection — must be unambiguous before any write.
    active_owners = im.find_active_owner_assignments()
    if len(active_owners) > 1:
        return _result(ok=False, code="MULTIPLE_ACTIVE_OWNERS_CONFLICT", retry_safe=True)

    existing_owner_employee = None
    if len(active_owners) == 1:
        owner_assignment = active_owners[0]
        existing_owner_employee = im.find_employee(owner_assignment.get("employee_id", ""))
        owner_identity = im.find_active_telegram_identity_by_employee(owner_assignment.get("employee_id", ""))
        if owner_identity is not None and owner_identity.get("telegram_user_id") == raw_env:
            # Idempotent: the same, correctly-bound owner already exists.
            return _result(
                ok=True, code="OWNER_BOOTSTRAP_ALREADY_COMPLETE", changed=False,
                created_ids={
                    "employee_id": owner_assignment.get("employee_id", ""),
                    "telegram_identity_id": owner_identity.get("telegram_identity_id", ""),
                    "access_role_assignment_id": owner_assignment.get("access_role_assignment_id", ""),
                },
            )
        return _result(ok=False, code="OWNER_CONFLICT_DIFFERENT_TELEGRAM_ID", retry_safe=True)

    # No active owner exists yet. Check whether raw_env is already
    # bound to some OTHER (non-owner) employee.
    bound_employee = im.find_employee_by_telegram_user_id(raw_env, active_only=True)
    resumable_partial_employee_id = ""
    if bound_employee is not None:
        # Unambiguous-resume check: only safe to continue if BOTH the
        # Employee and its Telegram Identity were themselves created
        # by this exact bootstrap actor — otherwise this is a real,
        # distinct employee and must fail closed.
        identity_row = im.find_active_telegram_identity_by_employee(bound_employee["employee_id"])
        if (
            bound_employee.get("created_by") == im.SYSTEM_BOOTSTRAP_ACTOR
            and identity_row is not None
            and identity_row.get("linked_by") == im.SYSTEM_BOOTSTRAP_ACTOR
        ):
            resumable_partial_employee_id = bound_employee["employee_id"]
        else:
            return _result(ok=False, code="TELEGRAM_ID_BOUND_TO_NON_OWNER_EMPLOYEE", retry_safe=True)

    proposed_steps = ("create_employee", "activate_employee", "link_telegram_identity", "assign_owner_role", "assign_all_businesses_scope")
    if dry_run:
        return _result(ok=True, code="OWNER_BOOTSTRAP_PREVIEW", changed=False, completed_steps=(), failed_step="",
                        created_ids={}, verification_errors=())

    completed: list[str] = []
    created_ids: dict = {}

    # Step 1+2: Employee (create-then-activate, since the manager
    # layer only exposes create-as-pending — see identity_manager.
    # create_pending_employee()'s contract).
    if resumable_partial_employee_id:
        employee_id = resumable_partial_employee_id
        employee = im.find_employee(employee_id)
        completed.append("create_employee")
        if employee and employee.get("status") != "active":
            activate_result = im.activate_employee(employee_id, activated_by=im.SYSTEM_BOOTSTRAP_ACTOR)
            if not activate_result["ok"]:
                return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=False,
                                completed_steps=completed, failed_step="activate_employee", created_ids=created_ids)
        completed.append("activate_employee")
    else:
        create_result = im.create_pending_employee(display_label="Owner", created_by=im.SYSTEM_BOOTSTRAP_ACTOR)
        if not create_result["ok"]:
            return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=create_result.get("retry_safe", False),
                            completed_steps=completed, failed_step="create_employee", created_ids=created_ids)
        employee_id = create_result["employee_id"]
        completed.append("create_employee")
        created_ids["employee_id"] = employee_id

        activate_result = im.activate_employee(employee_id, activated_by=im.SYSTEM_BOOTSTRAP_ACTOR)
        if not activate_result["ok"]:
            return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=False,
                            completed_steps=completed, failed_step="activate_employee", created_ids=created_ids)
        completed.append("activate_employee")

    created_ids.setdefault("employee_id", employee_id)

    # Step 3: Telegram Identity.
    identity_row = im.find_active_telegram_identity_by_employee(employee_id)
    if identity_row is not None:
        created_ids["telegram_identity_id"] = identity_row.get("telegram_identity_id", "")
    else:
        link_result = im.link_telegram_identity(employee_id, raw_env, linked_by=im.SYSTEM_BOOTSTRAP_ACTOR)
        if not link_result["ok"]:
            return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=link_result.get("retry_safe", False),
                            completed_steps=completed, failed_step="link_telegram_identity", created_ids=created_ids)
        created_ids["telegram_identity_id"] = link_result["telegram_identity_id"]
    completed.append("link_telegram_identity")

    # Step 4: OWNER Role Assignment (bootstrap-only write path).
    existing_role_rows = [r for r in im.find_active_role_assignments(employee_id) if r.get("role") == "OWNER"]
    if existing_role_rows:
        access_role_assignment_id = existing_role_rows[0]["access_role_assignment_id"]
    else:
        role_result = im._bootstrap_assign_owner_role(employee_id, assigned_by=im.SYSTEM_BOOTSTRAP_ACTOR)
        if not role_result["ok"]:
            return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=role_result.get("retry_safe", False),
                            completed_steps=completed, failed_step="assign_owner_role", created_ids=created_ids)
        access_role_assignment_id = role_result["access_role_assignment_id"]
    created_ids["access_role_assignment_id"] = access_role_assignment_id
    completed.append("assign_owner_role")

    # Step 5: ALL_BUSINESSES Scope Assignment.
    existing_scope_rows = [
        r for r in im.find_active_scope_assignments(employee_id, access_role_assignment_id)
        if r.get("scope_type") == "ALL_BUSINESSES"
    ]
    if existing_scope_rows:
        access_scope_assignment_id = existing_scope_rows[0]["access_scope_assignment_id"]
    else:
        scope_result = im.assign_access_scope(
            employee_id, access_role_assignment_id, "ALL_BUSINESSES", assigned_by=im.SYSTEM_BOOTSTRAP_ACTOR,
        )
        if not scope_result["ok"]:
            return _result(ok=False, code="OWNER_BOOTSTRAP_WRITE_FAILED", retry_safe=scope_result.get("retry_safe", False),
                            completed_steps=completed, failed_step="assign_all_businesses_scope", created_ids=created_ids)
        access_scope_assignment_id = scope_result["access_scope_assignment_id"]
    created_ids["access_scope_assignment_id"] = access_scope_assignment_id
    completed.append("assign_all_businesses_scope")

    # Final post-write verification: re-resolve the owner end-to-end.
    verification_errors: list[str] = []
    final_employee = im.find_employee(employee_id)
    if final_employee is None or final_employee.get("status") != "active":
        verification_errors.append("employee_not_active")
    final_identity = im.find_active_telegram_identity_by_employee(employee_id)
    if final_identity is None or final_identity.get("telegram_user_id") != raw_env:
        verification_errors.append("telegram_identity_mismatch")
    final_roles = im.find_active_role_assignments(employee_id)
    if not any(r.get("role") == "OWNER" for r in final_roles):
        verification_errors.append("owner_role_missing")
    final_scopes = im.find_active_scope_assignments(employee_id, access_role_assignment_id)
    if not any(s.get("scope_type") == "ALL_BUSINESSES" for s in final_scopes):
        verification_errors.append("all_businesses_scope_missing")

    if verification_errors:
        log.error(f"bootstrap_owner_from_env post-write verification errors: {verification_errors}")
        return _result(ok=False, code="OWNER_BOOTSTRAP_POST_WRITE_VERIFICATION_FAILED", retry_safe=False,
                        completed_steps=completed, failed_step="", created_ids=created_ids,
                        verification_errors=verification_errors)

    log.info(f"bootstrap_owner_from_env: OWNER bootstrap complete for employee={employee_id}")
    return _result(ok=True, code="OWNER_BOOTSTRAP_COMPLETE", changed=True,
                    completed_steps=completed, failed_step="", created_ids=created_ids)


# ─────────────────────────────────────────────────────────────
# Phase 17B-IR3A: dedicated, narrow incident-remediation
# orchestration for exactly one confirmed incident (Phase 17B-IR1 —
# an unmocked test run wrote a placeholder OWNER bootstrap to
# production: EMP-001/TGID-001/ARA-001/ASA-001, Telegram User ID
# "999"). Every target ID is a fixed constant, never a caller-
# supplied argument, never sourced from Telegram or any normal user
# input. Never called from application startup, migration, or
# telegram_handlers.py — invoked exclusively via
# remediate_identity_bootstrap_incident.py's explicit CLI.
# ─────────────────────────────────────────────────────────────

_IR3A_ARA_ID = "ARA-001"
_IR3A_TGID_ID = "TGID-001"
_IR3A_EMPLOYEE_ID = "EMP-001"
_IR3A_ASA_ID = "ASA-001"
_IR3A_TELEGRAM_USER_ID = "999"
_IR3A_TELEGRAM_ACTOR = "telegram:999"
_IR3A_REMEDIATION_ACTOR = "system:incident_remediation"
_IR3A_REMEDIATION_REASON = "incident: unauthorized test bootstrap during Phase 17B validation"


def _check_incident_preconditions() -> dict:
    """Read-only. All 13 preconditions from the Phase 17B-IR3A design,
    checked in order; returns the first failure found (fail-closed —
    no need to enumerate every mismatch, one is sufficient to refuse
    any write)."""
    from business_core import identity_manager as im

    def _fail(name):
        return {"ok": False, "failed_precondition": name, "ara": None, "tgid": None, "emp": None, "asa": None}

    ara = im.find_access_role_assignment(_IR3A_ARA_ID)
    if ara is None:
        return _fail("ARA_NOT_FOUND")
    if ara.get("role") != "OWNER":
        return _fail("ARA_ROLE_MISMATCH")
    ara_already_remediated = (
        ara.get("status") == "revoked"
        and ara.get("revoked_by") == _IR3A_REMEDIATION_ACTOR
        and ara.get("revoke_reason") == _IR3A_REMEDIATION_REASON
    )
    if ara.get("status") not in ("active",) and not ara_already_remediated:
        return _fail("ARA_UNEXPECTED_STATUS")
    if ara.get("employee_id") != _IR3A_EMPLOYEE_ID:
        return _fail("ARA_EMPLOYEE_MISMATCH")
    if ara.get("assigned_by") != im.SYSTEM_BOOTSTRAP_ACTOR:
        return _fail("ARA_ASSIGNED_BY_MISMATCH")

    tgid = im.find_telegram_identity(_IR3A_TGID_ID)
    if tgid is None:
        return _fail("TGID_NOT_FOUND")
    if tgid.get("employee_id") != _IR3A_EMPLOYEE_ID:
        return _fail("TGID_EMPLOYEE_MISMATCH")
    if tgid.get("telegram_user_id") != _IR3A_TELEGRAM_USER_ID:
        return _fail("TGID_USER_ID_MISMATCH")
    if tgid.get("telegram_actor") != _IR3A_TELEGRAM_ACTOR:
        return _fail("TGID_ACTOR_MISMATCH")
    if tgid.get("linked_by") != im.SYSTEM_BOOTSTRAP_ACTOR:
        return _fail("TGID_LINKED_BY_MISMATCH")

    emp = im.find_employee(_IR3A_EMPLOYEE_ID)
    if emp is None:
        return _fail("EMP_NOT_FOUND")
    if emp.get("created_by") != im.SYSTEM_BOOTSTRAP_ACTOR:
        return _fail("EMP_CREATED_BY_MISMATCH")

    asa = im.find_access_scope_assignment(_IR3A_ASA_ID)
    if asa is None:
        return _fail("ASA_NOT_FOUND")
    asa_correctly_revoked = (
        asa.get("status") == "revoked"
        and asa.get("revoked_by") == _IR3A_REMEDIATION_ACTOR
        and asa.get("revoke_reason") == _IR3A_REMEDIATION_REASON
    )
    if not asa_correctly_revoked:
        return _fail("ASA_NOT_CORRECTLY_REVOKED")

    return {"ok": True, "failed_precondition": "", "ara": ara, "tgid": tgid, "emp": emp, "asa": asa}


def remediate_phase17b_identity_incident(*, dry_run: bool = True) -> dict:
    """
    Fixed-target incident remediation for exactly the Phase 17B-IR1
    incident. Order: verify ASA-001 already revoked (never re-revoked
    here) -> revoke ARA-001 (specialized path) -> revoke TGID-001
    (existing revoke_telegram_identity) -> disable EMP-001 (existing
    disable_employee). Stops immediately on any step failure, never
    auto-retries, never rolls back completed steps.
    """
    from business_core import identity_manager as im

    def _result(*, ok, code, changed=False, retry_safe=True, completed_steps=(), pending_steps=(),
                failed_step="", result_by_step=None, verification_errors=()):
        return {
            "ok": ok, "code": code, "changed": changed, "retry_safe": retry_safe, "dry_run": dry_run,
            "completed_steps": tuple(completed_steps), "pending_steps": tuple(pending_steps),
            "failed_step": failed_step, "result_by_step": result_by_step or {},
            "verification_errors": tuple(verification_errors),
        }

    pre = _check_incident_preconditions()
    if not pre["ok"]:
        return _result(ok=False, code="INCIDENT_PRECONDITION_FAILED", retry_safe=True, failed_step=pre["failed_precondition"])

    ara, tgid, emp = pre["ara"], pre["tgid"], pre["emp"]

    completed = ["verify_asa_already_revoked"]
    pending = []
    if ara["status"] == "active":
        pending.append("revoke_ara")
    if tgid["status"] == "active":
        pending.append("revoke_tgid")
    if emp["status"] == "active":
        pending.append("disable_emp")

    if dry_run:
        return _result(ok=True, code="INCIDENT_REMEDIATION_PREVIEW", changed=False,
                        completed_steps=tuple(completed), pending_steps=tuple(pending))

    if not pending:
        return _result(ok=True, code="INCIDENT_REMEDIATION_ALREADY_COMPLETE", changed=False,
                        completed_steps=tuple(completed + ["revoke_ara", "revoke_tgid", "disable_emp"]))

    result_by_step: dict = {}
    actually_completed = ["verify_asa_already_revoked"]

    if "revoke_ara" in pending:
        r = im._remediate_revoke_incident_owner_role(
            _IR3A_ARA_ID, expected_employee_id=_IR3A_EMPLOYEE_ID,
            expected_telegram_user_id=_IR3A_TELEGRAM_USER_ID,
            reason=_IR3A_REMEDIATION_REASON, actor=_IR3A_REMEDIATION_ACTOR,
        )
        result_by_step["revoke_ara"] = r
        if not r["ok"]:
            return _result(ok=False, code="INCIDENT_REMEDIATION_STEP_FAILED", retry_safe=r.get("retry_safe", False),
                            completed_steps=tuple(actually_completed), failed_step="revoke_ara", result_by_step=result_by_step)
    actually_completed.append("revoke_ara")

    if "revoke_tgid" in pending:
        r = im.revoke_telegram_identity(_IR3A_TGID_ID, reason=_IR3A_REMEDIATION_REASON, revoked_by=_IR3A_REMEDIATION_ACTOR)
        result_by_step["revoke_tgid"] = r
        if not r["ok"]:
            return _result(ok=False, code="INCIDENT_REMEDIATION_STEP_FAILED", retry_safe=r.get("retry_safe", False),
                            completed_steps=tuple(actually_completed), failed_step="revoke_tgid", result_by_step=result_by_step)
    actually_completed.append("revoke_tgid")

    if "disable_emp" in pending:
        r = im.disable_employee(_IR3A_EMPLOYEE_ID, reason=_IR3A_REMEDIATION_REASON, disabled_by=_IR3A_REMEDIATION_ACTOR)
        result_by_step["disable_emp"] = r
        if not r["ok"]:
            return _result(ok=False, code="INCIDENT_REMEDIATION_STEP_FAILED", retry_safe=r.get("retry_safe", False),
                            completed_steps=tuple(actually_completed), failed_step="disable_emp", result_by_step=result_by_step)
    actually_completed.append("disable_emp")

    final_ara = im.find_access_role_assignment(_IR3A_ARA_ID)
    final_tgid = im.find_telegram_identity(_IR3A_TGID_ID)
    final_emp = im.find_employee(_IR3A_EMPLOYEE_ID)
    verification_errors = []
    if final_ara is None or final_ara.get("status") != "revoked":
        verification_errors.append("ara_not_revoked")
    if final_tgid is None or final_tgid.get("status") != "revoked":
        verification_errors.append("tgid_not_revoked")
    if final_emp is None or final_emp.get("status") != "disabled":
        verification_errors.append("emp_not_disabled")

    if verification_errors:
        log.error(f"remediate_phase17b_identity_incident post-write verification errors: {verification_errors}")
        return _result(ok=False, code="INCIDENT_REMEDIATION_POST_WRITE_VERIFICATION_FAILED", retry_safe=False,
                        completed_steps=tuple(actually_completed), result_by_step=result_by_step,
                        verification_errors=tuple(verification_errors))

    log.info("remediate_phase17b_identity_incident: remediation complete")
    return _result(ok=True, code="INCIDENT_REMEDIATION_COMPLETE", changed=True,
                    completed_steps=tuple(actually_completed), result_by_step=result_by_step)
