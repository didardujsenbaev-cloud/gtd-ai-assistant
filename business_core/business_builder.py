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

    Требует GDRIVE_BIZ_ROOT_FOLDER_ID и GOOGLE_CREDENTIALS_FILE.
    Если переменные не заданы — возвращает {ok: False} без ошибки.
    Если Drive API упал — возвращает {ok: False, error: str}.

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
    gdrive_root = os.getenv("GDRIVE_BIZ_ROOT_FOLDER_ID", "").strip()
    creds_file  = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()

    if not gdrive_root or not creds_file:
        log.debug("provision_biz_drive: GDRIVE_BIZ_ROOT_FOLDER_ID или credentials не заданы — пропуск")
        return {"ok": False, "folder_id": None, "folder_url": None,
                "error": "GDRIVE_BIZ_ROOT_FOLDER_ID не задан в .env"}

    try:
        from integrations.google_drive_adapter import create_business_folder_structure

        result = create_business_folder_structure(
            biz_id=biz_id,
            biz_name=biz_name,
            dry_run=False,
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
