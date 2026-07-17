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


# ─────────────────────────────────────────────────────────────
# Phase 6B: расширенная дедупликация клиентов
# ─────────────────────────────────────────────────────────────

def normalize_person_name(name: str) -> str:
    """
    Нормализовать ФИО: trim → убрать множественные пробелы → lower.

    Примеры:
        "  Иван  Петров " → "иван петров"
        "ИВАН ПЕТРОВ"     → "иван петров"
    """
    import re
    return re.sub(r"\s+", " ", name.strip()).lower()


def normalize_phone(phone: str) -> str:
    """
    Нормализовать телефонный номер: оставить только цифры.

    Примеры:
        "+7 (777) 123-45-67" → "77771234567"
        "8 777 123 45 67"    → "87771234567"
        ""                   → ""
    """
    import re
    if not phone:
        return ""
    return re.sub(r"\D", "", phone.strip())


def find_existing_person(
    name:   Optional[str] = None,
    phone:  Optional[str] = None,
    biz_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Найти существующего человека в PEOPLE_REGISTRY.

    Стратегия поиска (приоритеты):
    1. Телефон (нормализованный) + biz_id — сильный идентификатор.
    2. ФИО (нормализованное) + biz_id.

    Если biz_id не задан — ищем только по имени/телефону (слабый поиск).
    Если найден — возвращаем все ключевые поля, включая biz_ids.

    Args:
        name:   ФИО клиента (опционально)
        phone:  телефон (опционально)
        biz_id: BIZ-ID для фильтрации (опционально)

    Returns:
        {
            "row_num":         int,   # 1-based
            "prs_id":          str,
            "full_name":       str,
            "biz_ids":         list[str],   # из колонки Biz IDs
            "primary_biz_id":  str,
            "drive_url":       str,
            "drive_folder_id": str,
            "phone_raw":       str,   # телефон как записан в таблице
        }
        или None
    """
    if not name and not phone:
        return None

    norm_name  = normalize_person_name(name)  if name  else ""
    norm_phone = normalize_phone(phone)        if phone else ""

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return None

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h, fallback=""):
            c = _col(h)
            return (row[c].strip() if c is not None and c < len(row) else "") or fallback

        name_col     = _col("ФИО") if _col("ФИО") is not None else 1
        phone_col    = _col("Телефон")
        wa_col       = _col("WhatsApp")
        biz_ids_col  = _col("Biz IDs")
        old_biz_col  = _col("Бизнесы")
        drive_col    = _col("Google Drive")
        drive_id_col = _col("Drive Folder ID")
        prim_col     = _col("Primary Biz ID")

        def _person_biz_ids(row) -> list[str]:
            """Возвращает список BIZ-ID из новой или старой колонки."""
            if biz_ids_col is not None and biz_ids_col < len(row) and row[biz_ids_col].strip():
                return normalize_biz_ids(row[biz_ids_col])
            # fallback: старое поле "Бизнесы" — возвращаем как есть (не BIZ-ID, но для сравнения)
            return []

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue

            row_name  = normalize_person_name(row[name_col] if name_col < len(row) else "")
            row_phone = normalize_phone(row[phone_col] if phone_col is not None and phone_col < len(row) else "")
            row_wa    = normalize_phone(row[wa_col]    if wa_col   is not None and wa_col   < len(row) else "")

            # Совпадение по телефону (сильный идентификатор)
            phone_match = bool(
                norm_phone and (
                    (row_phone and row_phone == norm_phone) or
                    (row_wa    and row_wa    == norm_phone)
                )
            )
            # Совпадение по имени
            name_match = bool(norm_name and row_name == norm_name)

            if not phone_match and not name_match:
                continue

            person_biz_ids = _person_biz_ids(row)

            # Если biz_id задан — проверяем совпадение
            if biz_id:
                # Проверяем и новое поле Biz IDs, и старое "Бизнесы"
                old_biz = _get(row, "Бизнесы")
                biz_match = (
                    biz_id in person_biz_ids or
                    # резолвим через имя если нет BIZ-ID в записи
                    (not person_biz_ids and old_biz)
                )
                # Если не совпал biz — помечаем как "другой бизнес"
                same_biz = biz_id in person_biz_ids
            else:
                biz_match = True
                same_biz = True

            if not biz_match and not phone_match and not name_match:
                continue

            return {
                "row_num":         i,
                "prs_id":          row[0],
                "full_name":       row[name_col] if name_col < len(row) else "",
                "biz_ids":         person_biz_ids,
                "primary_biz_id":  _get(row, "Primary Biz ID"),
                "drive_url":       _get(row, "Google Drive"),
                "drive_folder_id": _get(row, "Drive Folder ID"),
                "phone_raw":       row[phone_col] if phone_col is not None and phone_col < len(row) else "",
                "same_biz":        same_biz,  # True = тот же бизнес, False = другой
            }

    except Exception as exc:
        log.warning(f"find_existing_person error: {exc}")

    return None


def add_biz_id_to_person(person_id: str, biz_id: str) -> bool:
    """
    Добавить biz_id в колонку "Biz IDs" существующего клиента.

    Не дублирует, если biz_id уже есть.
    Primary Biz ID не перезаписывает если уже заполнен.

    Args:
        person_id: PRS-ID
        biz_id:    BIZ-ID для добавления

    Returns:
        True если обновлено, False если уже было или ошибка
    """
    if not person_id or not biz_id:
        return False

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        biz_ids_col = _col("Biz IDs")
        prim_col    = _col("Primary Biz ID")

        for i, row in enumerate(all_values[1:], start=2):
            if not row or row[0] != person_id:
                continue

            # Текущие Biz IDs
            current_ids = normalize_biz_ids(
                row[biz_ids_col] if biz_ids_col is not None and biz_ids_col < len(row) else ""
            )

            if biz_id in current_ids:
                log.debug(f"add_biz_id_to_person: {biz_id} уже есть у {person_id}")
                return False  # Уже есть — ничего не делаем

            # Добавляем biz_id
            current_ids.append(biz_id)
            new_biz_ids_str = ",".join(current_ids)

            # Колонка Biz IDs
            if biz_ids_col is not None:
                col_letter = _col_letter(biz_ids_col + 1)
                sheet.update_cell(i, biz_ids_col + 1, new_biz_ids_str)
                log.info(f"add_biz_id_to_person: {person_id} → Biz IDs = {new_biz_ids_str}")

            # Primary Biz ID — только если пустой
            if prim_col is not None:
                current_prim = row[prim_col].strip() if prim_col < len(row) else ""
                if not current_prim:
                    sheet.update_cell(i, prim_col + 1, biz_id)
                    log.info(f"add_biz_id_to_person: {person_id} → Primary Biz ID = {biz_id}")

            return True

    except Exception as exc:
        log.warning(f"add_biz_id_to_person({person_id}, {biz_id}) error: {exc}")

    return False


def update_person_drive_info(person_id: str, folder_id: str, folder_url: str) -> bool:
    """
    Обновить Drive-информацию существующего клиента (дозаполнение).

    Обновляет только если текущие значения пустые — не перезаписывает.

    Args:
        person_id:  PRS-ID
        folder_id:  Google Drive folder ID
        folder_url: Google Drive URL

    Returns:
        True если обновлено, False если уже было или ошибка
    """
    if not person_id or not folder_id:
        return False

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        drive_col    = _col("Google Drive")
        drive_id_col = _col("Drive Folder ID")

        for i, row in enumerate(all_values[1:], start=2):
            if not row or row[0] != person_id:
                continue

            updated = False

            if drive_col is not None:
                current = row[drive_col].strip() if drive_col < len(row) else ""
                if not current and folder_url:
                    sheet.update_cell(i, drive_col + 1, folder_url)
                    updated = True

            if drive_id_col is not None:
                current = row[drive_id_col].strip() if drive_id_col < len(row) else ""
                if not current and folder_id:
                    sheet.update_cell(i, drive_id_col + 1, folder_id)
                    updated = True

            if updated:
                log.info(f"update_person_drive_info: {person_id} → Drive дозаполнен")
            return updated

    except Exception as exc:
        log.warning(f"update_person_drive_info({person_id}) error: {exc}")

    return False


def _col_letter(col_index: int) -> str:
    """Преобразовать 1-based индекс колонки в букву (A, B, ..., Z, AA, ...)."""
    result = ""
    while col_index > 0:
        col_index, rem = divmod(col_index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _normalize_name(name: str) -> str:
    """Нормализовать имя: trim + lower + убрать двойные пробелы."""
    return normalize_person_name(name)


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

        try:
            from business_core.sheets import get_business_sheet
            sheet = get_business_sheet("people_registry")
            all_vals = sheet.get_all_values()
            if all_vals and len(all_vals) > 1:
                headers = all_vals[0]

                def _col(h):
                    return headers.index(h) if h in headers else None

                name_col     = _col("ФИО") or 1
                drive_col    = _col("Drive Folder ID")
                drive_url_col = _col("Google Drive")

                for row in all_vals[1:]:
                    if not row or row[0] != client_id:
                        continue
                    client_name      = row[name_col].strip() if name_col < len(row) else client_id
                    client_folder_id = (row[drive_col].strip()     if drive_col    is not None and drive_col    < len(row) else "")
                    client_drive_url = (row[drive_url_col].strip() if drive_url_col is not None and drive_url_col < len(row) else "")
                    break
        except Exception:
            pass

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
    Создать roadmap для объекта недвижимости в листе ROADMAPS.

    Args:
        obj_id:      OBJ-ID объекта (обязательный)
        biz_id:      BIZ-ID бизнеса (обязательный)
        client_id:   PRS-ID клиента (обязательный)
        service_id:  SVC-ID услуги
        case_type:   тип кейса (legalization_reconstruction_house / ...)
        title:       заголовок roadmap (автогенерируется если пустой)
        notes:       примечания
        template_id: RMT-... шаблон, фактически использованный для этапов

    Returns:
        {
            "ok":          bool,
            "roadmap_id":  str,
            "error":       str | None,
        }
    """
    if not obj_id or not biz_id or not client_id:
        return {
            "ok": False, "roadmap_id": "",
            "error": "Обязательные поля: obj_id, biz_id, client_id",
        }

    try:
        from business_core.sheets import (
            append_business_row,
            get_business_sheet,
            row_from_header_map,
        )
        now        = datetime.now().strftime("%Y-%m-%d")
        roadmap_id = generate_roadmap_id()

        # Автогенерация заголовка
        if not title:
            title = f"Roadmap {obj_id}" + (f" / {service_id}" if service_id else "")

        # Строка собирается по ФАКТИЧЕСКИМ заголовкам листа, а не по
        # жёстко заданным позициям — так запись никогда не съедет
        # относительно реального расположения колонок (см. баг RM-027,
        # где Object ID оказался записан под колонкой 'Template ID').
        sheet   = get_business_sheet("roadmaps")
        headers = sheet.row_values(1)

        values = {
            "Roadmap ID":        roadmap_id,
            "Business ID":       biz_id,
            "Service ID":        service_id,
            "City":              "",
            "Client ID":         client_id,
            "Client Name":       title,
            "GTD Project ID":    "",
            "Responsible":       "",
            "Status":            "active",
            "Created":           now,
            "Expected":          "",
            "Progress %":        "0",
            "Notes":             notes,
            "Last Updated":      now,
            "Object ID":         obj_id,
            "Parent Roadmap ID": "",
            "Case Type":         case_type,
            "Template ID":       template_id,
        }

        try:
            row = row_from_header_map(headers, values)
        except ValueError as header_exc:
            log.error(f"create_roadmap_for_object: {header_exc}")
            return {"ok": False, "roadmap_id": "", "error": str(header_exc)}

        append_business_row("roadmaps", row)
        log.info(f"create_roadmap_for_object: {roadmap_id} / {obj_id} / {case_type}")
        return {"ok": True, "roadmap_id": roadmap_id, "error": None}

    except Exception as exc:
        log.error(f"create_roadmap_for_object error: {exc}")
        return {"ok": False, "roadmap_id": "", "error": str(exc)}


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
