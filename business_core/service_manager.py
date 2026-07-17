"""
Service Manager — управление SERVICE_CATALOG.

Phase 8A: Service Catalog Upgrade.

Архитектурный принцип:
  Business Core → Service Catalog → Roadmap Templates
  GTD Core не затрагивается.

Зависимости только от business_core.sheets.
Не импортирует GTD Core модули.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# Допустимые статусы услуги
SERVICE_STATUSES = {"active", "inactive", "draft"}

# Маппинг старых колонок → новые алиасы для совместимости
_COL_ALIASES: dict[str, list[str]] = {
    "service_id":    ["ID"],
    "biz_id":        ["Бизнес ID"],
    "service_name":  ["Service Name", "Название"],
    "slug":          ["Slug"],
    "status":        ["Статус"],
    "city":          ["Город"],
    "price_from":    ["Цена мин"],
    "price_to":      ["Цена макс"],
    "duration":      ["Срок"],
    "description":   ["Описание"],
    "risks":         ["Риски"],
    "notes":         ["Комментарий"],
    # Phase 8A new columns
    "service_category":           ["Service Category"],
    "object_type":                ["Object Type"],
    "client_type":                ["Client Type"],
    "what_included":              ["What Included"],
    "what_not_included":          ["What Not Included"],
    "currency":                   ["Currency"],
    "required_documents":         ["Required Documents"],
    "default_roadmap_template_id": ["Default Roadmap Template ID"],
    "contractors_needed":         ["Contractors Needed"],
    "materials_ids":              ["Materials IDs"],
    "created_at":                 ["Created At"],
    "last_updated":               ["Last Updated"],
}


def _col_idx(headers: list[str], key: str) -> Optional[int]:
    """Найти индекс колонки по key через _COL_ALIASES."""
    candidates = _COL_ALIASES.get(key, [key])
    for c in candidates:
        if c in headers:
            return headers.index(c)
    return None


def _get(row: list[str], headers: list[str], key: str) -> str:
    idx = _col_idx(headers, key)
    if idx is not None and idx < len(row):
        return row[idx].strip()
    return ""


def _row_to_dict(row: list[str], headers: list[str]) -> dict:
    """Преобразовать строку в dict с нормализованными ключами."""
    result: dict = {}
    for key in _COL_ALIASES:
        result[key] = _get(row, headers, key)
    return result


# ═══════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════

def generate_service_id() -> str:
    """
    Сгенерировать следующий SVC-ID из SERVICE_CATALOG.

    Формат: SVC-001, SVC-002, ...
    Безопасно работает на пустом листе.
    """
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("service_catalog")
    except Exception as exc:
        log.warning(f"generate_service_id error: {exc}")
        return "SVC-001"


# ═══════════════════════════════════════════════════════════════
# Normalization
# ═══════════════════════════════════════════════════════════════

def normalize_service_status(status: str) -> str:
    """
    Нормализовать статус услуги.

    Допустимые: active, inactive, draft.
    Неизвестные значения → active.
    """
    if not status:
        return "active"
    s = status.strip().lower()
    return s if s in SERVICE_STATUSES else "active"


# ═══════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════

def create_service_record(
    biz_id:                     str,
    service_name:               str,
    service_category:           str = "",
    city:                       str = "",
    object_type:                str = "",
    client_type:                str = "",
    description:                str = "",
    what_included:              str = "",
    what_not_included:          str = "",
    price_from:                 str = "",
    price_to:                   str = "",
    currency:                   str = "KZT",
    estimated_duration:         str = "",
    required_documents:         str = "",
    default_roadmap_template_id: str = "",
    risks:                      str = "",
    contractors_needed:         str = "",
    materials_ids:              str = "",
    status:                     str = "active",
    notes:                      str = "",
) -> dict:
    """
    Создать новую запись в SERVICE_CATALOG.

    Args:
        biz_id:        BIZ-ID бизнеса (обязательный)
        service_name:  название услуги (обязательное)

    Returns:
        {
            "ok":         bool,
            "service_id": str,
            "error":      str | None,
        }
    """
    if not biz_id or not service_name:
        return {
            "ok": False, "service_id": "",
            "error": "Обязательные поля: biz_id, service_name",
        }

    try:
        from business_core.sheets import (
            append_business_row,
            get_business_sheet,
            row_from_header_map,
        )
        now        = datetime.now().strftime("%Y-%m-%d")
        service_id = generate_service_id()
        status     = normalize_service_status(status)
        if not currency:
            currency = "KZT"
        slug = _make_slug(service_name)

        # Phase 10.2B.6B: строка формируется по ФАКТИЧЕСКИМ заголовкам
        # листа SERVICE_CATALOG, а не по жёсткой позиции — не зависит
        # от порядка колонок (см. Phase 10.2B.6A: миграция подписала
        # 13 ранее пустых заголовков Phase 8A на их канонических местах).
        sheet   = get_business_sheet("service_catalog")
        headers = sheet.row_values(1)

        from collections import Counter
        duplicate_headers = sorted(
            h for h, c in Counter(headers).items() if h and c > 1
        )
        if duplicate_headers:
            raise ValueError(
                f"SERVICE_CATALOG: обнаружены дублирующиеся заголовки "
                f"{duplicate_headers}. Запись услуги остановлена, ничего не записано."
            )

        required_headers = [
            "ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
            "Цена мин", "Цена макс", "Срок", "Описание",
            "Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
            "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
            "Документы от клиента", "Документы наши",
            "Чек-лист производства", "Чек-лист закрытия",
            "Риски", "Шаблоны", "Инструкция", "Комментарий",
            "Service Name", "Service Category", "Object Type", "Client Type",
            "What Included", "What Not Included", "Currency",
            "Required Documents", "Default Roadmap Template ID",
            "Contractors Needed", "Materials IDs", "Created At", "Last Updated",
        ]
        missing_headers = [h for h in required_headers if h not in headers]
        if missing_headers:
            raise ValueError(
                f"SERVICE_CATALOG: отсутствуют обязательные колонки {missing_headers}. "
                f"Запись услуги остановлена, ничего не записано."
            )

        row = row_from_header_map(headers, {
            "ID":             service_id,
            "Бизнес ID":      biz_id,
            "Название":       service_name,
            "Slug":           slug,
            "Статус":         status,
            "Город":          city,
            "Цена мин":       price_from,
            "Цена макс":      price_to,
            "Срок":           estimated_duration,
            "Описание":       description,
            "Этап 1": "", "Этап 2": "", "Этап 3": "", "Этап 4": "", "Этап 5": "",
            "Этап 6": "", "Этап 7": "", "Этап 8": "", "Этап 9": "", "Этап 10": "",
            "Документы от клиента":          required_documents,
            "Документы наши":                "",
            "Чек-лист производства":         "",
            "Чек-лист закрытия":             "",
            "Риски":                         risks,
            "Шаблоны":                       default_roadmap_template_id,
            "Инструкция":                    "",
            "Комментарий":                   notes,
            # Phase 8A новые колонки
            "Service Name":                  service_name,
            "Service Category":              service_category,
            "Object Type":                   object_type,
            "Client Type":                   client_type,
            "What Included":                 what_included,
            "What Not Included":             what_not_included,
            "Currency":                      currency,
            "Required Documents":            required_documents,
            "Default Roadmap Template ID":   default_roadmap_template_id,
            "Contractors Needed":            contractors_needed,
            "Materials IDs":                 materials_ids,
            "Created At":                    now,
            "Last Updated":                  now,
        })
        append_business_row("service_catalog", row)
        log.info(f"create_service_record: {service_id} / {biz_id} / {service_name}")
        return {"ok": True, "service_id": service_id, "error": None}

    except Exception as exc:
        log.error(f"create_service_record error: {exc}")
        return {"ok": False, "service_id": "", "error": str(exc)}


def _make_slug(name: str) -> str:
    """Простой slug из названия: нижний регистр, пробелы → '_'."""
    import re
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "_", s)
    return s[:60]


# ═══════════════════════════════════════════════════════════════
# Read helpers
# ═══════════════════════════════════════════════════════════════

def _load_services() -> tuple[list[dict], list[str]]:
    """Загрузить все строки SERVICE_CATALOG. Возвращает (rows_dicts, headers)."""
    from business_core.sheets import get_business_sheet
    sheet      = get_business_sheet("service_catalog")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return [], (all_values[0] if all_values else [])
    headers = all_values[0]
    rows    = [
        _row_to_dict(row, headers)
        for row in all_values[1:]
        if row and row[0].strip()
    ]
    return rows, headers


def find_service_by_id(service_id: str) -> Optional[dict]:
    """Найти услугу по SVC-ID."""
    if not service_id:
        return None
    try:
        rows, _ = _load_services()
        for r in rows:
            if r.get("service_id") == service_id:
                return r
    except Exception as exc:
        log.warning(f"find_service_by_id({service_id}) error: {exc}")
    return None


def find_services_by_biz(biz_id: str) -> list[dict]:
    """Найти все услуги бизнеса по BIZ-ID."""
    if not biz_id:
        return []
    try:
        rows, _ = _load_services()
        return [r for r in rows if r.get("biz_id") == biz_id]
    except Exception as exc:
        log.warning(f"find_services_by_biz({biz_id}) error: {exc}")
        return []


def find_services_by_object_type(
    object_type: str,
    biz_id:      str = "",
) -> list[dict]:
    """Найти услуги по типу объекта."""
    if not object_type:
        return []
    try:
        rows, _ = _load_services()
        results = [r for r in rows if r.get("object_type", "").lower() == object_type.lower()]
        if biz_id:
            results = [r for r in results if r.get("biz_id") == biz_id]
        return results
    except Exception as exc:
        log.warning(f"find_services_by_object_type({object_type}) error: {exc}")
        return []


def list_active_services(biz_id: str = "") -> list[dict]:
    """Список активных услуг, опционально фильтруя по бизнесу."""
    try:
        rows, _ = _load_services()
        results = [
            r for r in rows
            if normalize_service_status(r.get("status", "")) == "active"
        ]
        if biz_id:
            results = [r for r in results if r.get("biz_id") == biz_id]
        return results
    except Exception as exc:
        log.warning(f"list_active_services error: {exc}")
        return []


# ═══════════════════════════════════════════════════════════════
# Update helpers
# ═══════════════════════════════════════════════════════════════

def update_service_roadmap_template(
    service_id:          str,
    roadmap_template_id: str,
) -> bool:
    """
    Записать Default Roadmap Template ID в SERVICE_CATALOG.

    Returns:
        True если обновлено
    """
    if not service_id or not roadmap_template_id:
        return False
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("service_catalog")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False
        headers = all_values[0]

        # Обновляем обе колонки: старую "Шаблоны" и новую "Default Roadmap Template ID"
        old_col = headers.index("Шаблоны") if "Шаблоны" in headers else None
        new_col = (headers.index("Default Roadmap Template ID")
                   if "Default Roadmap Template ID" in headers else None)

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0].strip():
                continue
            if row[0].strip() != service_id:
                continue
            if old_col is not None:
                sheet.update_cell(i, old_col + 1, roadmap_template_id)
            if new_col is not None and new_col != old_col:
                sheet.update_cell(i, new_col + 1, roadmap_template_id)
            log.info(f"update_service_roadmap_template: {service_id} → {roadmap_template_id}")
            return True

    except Exception as exc:
        log.warning(f"update_service_roadmap_template({service_id}) error: {exc}")
    return False
