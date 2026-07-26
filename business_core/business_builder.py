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
) -> dict:
    """
    Shared result-builder for transition_stage_status() and
    update_stage_admin_fields() (ADR-017 Decision 12) — the stable,
    structured contract every caller (Telegram or otherwise) reads
    instead of a bare exception or ad-hoc dict shape.
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
    }


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


def transition_stage_status(
    stage_id: str,
    target_status: str,
    notes: Optional[str] = None,
    admin_fields: Optional[dict] = None,
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
      G. persist Stage status (roadmap_manager.update_stage_status_in_sheet),
         plus any admin_fields (Blocking Reason, for /blockstage/
         /unblockstage's coupled write) via roadmap_manager.
         update_stage_fields — gated behind the SAME eligibility check
         above, never a second, independent one
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

    Returns:
        See _stage_transition_result() for the full field list.
    """
    from business_core.roadmap_manager import (
        STAGE_STATUS_CANONICAL, find_stage_by_id, find_roadmap_by_id,
        update_stage_status_in_sheet, update_stage_fields,
        recalculate_roadmap_progress, maybe_complete_roadmap,
        normalize_roadmap_status,
    )

    # A. Required identifier.
    if not stage_id:
        return _stage_transition_result(
            ok=False, code="STAGE_NOT_FOUND", error="stage_id обязателен",
            stage_id=stage_id, retry_safe=True,
        )

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
    if roadmap is None:
        return _stage_transition_result(
            ok=False, code="ROADMAP_NOT_FOUND",
            error=f"Roadmap {roadmap_id or '(пусто)'} для этапа {stage_id} не найден",
            stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=target_status,
            final_status=previous_status, retry_safe=True,
        )

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

    # G. Persist Stage status (+ any coupled admin_fields).
    write_result = update_stage_status_in_sheet(stage_id, target_status, notes=notes)
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

    progress_before = None
    progress_after = None
    roadmap_status_after = roadmap_status_before

    code = "STAGE_STATUS_UPDATED" if changed else "STAGE_STATUS_UNCHANGED"

    # H. Progress recalculation — only if Status actually changed.
    if changed:
        progress_result = recalculate_roadmap_progress(roadmap_id)
        if progress_result["ok"]:
            progress_after = progress_result["new_progress"]
            try:
                progress_before = int(progress_result.get("old_progress") or 0)
            except (TypeError, ValueError):
                progress_before = None

            # I. Maybe auto-complete Roadmap — only after a successful
            # recalculation.
            completion_result = maybe_complete_roadmap(roadmap_id, progress_pct=progress_after)
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
    return _document_result(
        ok=result["ok"], code=result.get("code", ""), error=result.get("error"),
        document_id=document_id, business_id=document.get("business_id", ""),
        changed=result.get("changed", False), retry_safe=True,
    )


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
