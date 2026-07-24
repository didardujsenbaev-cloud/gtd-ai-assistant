"""
Roadmap Template Manager — управление шаблонами дорожных карт.

Phase 8B: Roadmap Template Core.

Архитектура:
  Service → Default Roadmap Template → Template Stages
                                     ↓
                               Real Roadmap → Real Stages

Листы:
  ROADMAP_TEMPLATE_REGISTRY — карточки шаблонов (RTMPL-001)
  ROADMAP_TEMPLATE_STAGES   — этапы шаблонов (TSTG-001)

Зависимости только от business_core.sheets.
GTD Core не импортируется.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════

def generate_roadmap_template_id() -> str:
    """RTMPL-001, RTMPL-002, ... Безопасен на пустом листе."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("roadmap_template_registry")
    except Exception as exc:
        log.warning(f"generate_roadmap_template_id error: {exc}")
        return "RTMPL-001"


def generate_roadmap_template_stage_id() -> str:
    """TSTG-001, TSTG-002, ... Безопасен на пустом листе."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("roadmap_template_stages")
    except Exception as exc:
        log.warning(f"generate_roadmap_template_stage_id error: {exc}")
        return "TSTG-001"


# ═══════════════════════════════════════════════════════════════
# ROADMAP_TEMPLATE_REGISTRY helpers
# ═══════════════════════════════════════════════════════════════

def create_roadmap_template(
    template_name: str,
    biz_id:        str = "",
    service_id:    str = "",
    case_type:     str = "",
    object_type:   str = "",
    description:   str = "",
    status:        str = "active",
    notes:         str = "",
) -> dict:
    """
    Создать шаблон дорожной карты в ROADMAP_TEMPLATE_REGISTRY.

    Args:
        template_name: обязательное человеческое название шаблона
        biz_id:        BIZ-ID бизнеса (пусто = глобальный шаблон)
        service_id:    SVC-ID услуги (пусто = применим ко всем)
        case_type:     ключ совместимости с ROADMAP_TEMPLATES
        object_type:   тип объекта (частный дом / нежилое / ...)
        description:   описание
        status:        active / inactive / draft
        notes:         заметки

    Returns:
        {"ok": bool, "template_id": str, "error": str | None}
    """
    if not template_name:
        return {"ok": False, "template_id": "", "error": "template_name обязателен"}

    try:
        from business_core.sheets import append_business_row, generate_next_id
        now         = datetime.now().strftime("%Y-%m-%d")
        template_id = generate_roadmap_template_id()

        row = [
            template_id,    # Template ID
            biz_id,         # Biz ID
            service_id,     # Service ID
            template_name,  # Template Name
            case_type,      # Case Type
            object_type,    # Object Type
            description,    # Description
            status,         # Status
            "0",            # Stages Count (обновляется при добавлении этапов)
            notes,          # Notes
            now,            # Created At
            now,            # Last Updated
        ]
        append_business_row("roadmap_template_registry", row)
        log.info(f"create_roadmap_template: {template_id} / {template_name}")
        return {"ok": True, "template_id": template_id, "error": None}

    except Exception as exc:
        log.error(f"create_roadmap_template error: {exc}")
        return {"ok": False, "template_id": "", "error": str(exc)}


def find_roadmap_template_by_id(template_id: str) -> Optional[dict]:
    """Найти шаблон по RTMPL-ID."""
    if not template_id:
        return None
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return None
        headers = all_values[0]

        def _g(row, h):
            try:
                return row[headers.index(h)].strip() if h in headers else ""
            except IndexError:
                return ""

        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if row[0].strip() == template_id:
                return {
                    "template_id":   _g(row, "Template ID"),
                    "biz_id":        _g(row, "Biz ID"),
                    "service_id":    _g(row, "Service ID"),
                    "template_name": _g(row, "Template Name"),
                    "case_type":     _g(row, "Case Type"),
                    "object_type":   _g(row, "Object Type"),
                    "description":   _g(row, "Description"),
                    "status":        _g(row, "Status"),
                    "stages_count":  _g(row, "Stages Count"),
                    "notes":         _g(row, "Notes"),
                    "created_at":    _g(row, "Created At"),
                }
    except Exception as exc:
        log.warning(f"find_roadmap_template_by_id({template_id}) error: {exc}")
    return None


def find_roadmap_templates_by_service(service_id: str) -> list[dict]:
    """Найти все шаблоны, связанные с данной услугой."""
    if not service_id:
        return []
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []
        headers = all_values[0]

        def _g(row, h):
            try:
                return row[headers.index(h)].strip() if h in headers else ""
            except IndexError:
                return ""

        svc_col = headers.index("Service ID") if "Service ID" in headers else None
        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if svc_col is not None and svc_col < len(row) and row[svc_col].strip() == service_id:
                results.append({
                    "template_id":   _g(row, "Template ID"),
                    "biz_id":        _g(row, "Biz ID"),
                    "service_id":    _g(row, "Service ID"),
                    "template_name": _g(row, "Template Name"),
                    "case_type":     _g(row, "Case Type"),
                    "object_type":   _g(row, "Object Type"),
                    "status":        _g(row, "Status"),
                    "stages_count":  _g(row, "Stages Count"),
                })
        return results
    except Exception as exc:
        log.warning(f"find_roadmap_templates_by_service({service_id}) error: {exc}")
        return []


def list_roadmap_templates(biz_id: str = "", status: str = "active") -> list[dict]:
    """Список шаблонов, фильтрация по biz_id и статусу."""
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []
        headers = all_values[0]

        def _g(row, h):
            try:
                return row[headers.index(h)].strip() if h in headers else ""
            except IndexError:
                return ""

        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            rec = {
                "template_id":   _g(row, "Template ID"),
                "biz_id":        _g(row, "Biz ID"),
                "service_id":    _g(row, "Service ID"),
                "template_name": _g(row, "Template Name"),
                "case_type":     _g(row, "Case Type"),
                "object_type":   _g(row, "Object Type"),
                "status":        _g(row, "Status"),
                "stages_count":  _g(row, "Stages Count"),
            }
            if status and rec["status"] != status:
                continue
            if biz_id and rec["biz_id"] not in ("", biz_id):
                continue
            results.append(rec)
        return results
    except Exception as exc:
        log.warning(f"list_roadmap_templates error: {exc}")
        return []


def link_service_to_roadmap_template(
    service_id:  str,
    template_id: str,
) -> bool:
    """
    Привязать шаблон к услуге через SERVICE_CATALOG.Default Roadmap Template ID.

    Returns:
        True если обновлено
    """
    if not service_id or not template_id:
        return False
    try:
        from business_core.service_manager import update_service_roadmap_template
        return update_service_roadmap_template(service_id, template_id)
    except Exception as exc:
        log.warning(f"link_service_to_roadmap_template error: {exc}")
        return False


# ═══════════════════════════════════════════════════════════════
# ROADMAP_TEMPLATE_STAGES helpers
# ═══════════════════════════════════════════════════════════════

def add_roadmap_template_stage(
    template_id:    str,
    stage_name:     str,
    order:          int   = 0,
    description:    str   = "",
    required_docs:  str   = "",
    responsible:    str   = "",
    estimated_days: str   = "",
    notes:          str   = "",
) -> dict:
    """
    Добавить этап в шаблон дорожной карты.

    Если order=0 — автоматически назначается следующий по порядку.

    Returns:
        {"ok": bool, "stage_id": str, "order": int, "error": str | None}
    """
    if not template_id or not stage_name:
        return {
            "ok": False, "stage_id": "",
            "order": 0, "error": "template_id и stage_name обязательны",
        }

    try:
        from business_core.sheets import append_business_row, generate_next_id, get_business_sheet

        # Автоопределение порядкового номера
        if order == 0:
            try:
                existing = get_business_sheet("roadmap_template_stages").get_all_values()
                headers  = existing[0] if existing else []
                t_col    = headers.index("Template ID") if "Template ID" in headers else None
                o_col    = headers.index("Order") if "Order" in headers else None
                max_order = 0
                if t_col is not None and o_col is not None:
                    for row in existing[1:]:
                        if row and t_col < len(row) and row[t_col].strip() == template_id:
                            try:
                                max_order = max(max_order, int(row[o_col]))
                            except (ValueError, IndexError):
                                pass
                order = max_order + 1
            except Exception:
                order = 1

        now      = datetime.now().strftime("%Y-%m-%d")
        stage_id = generate_roadmap_template_stage_id()

        row = [
            stage_id,       # Stage ID
            template_id,    # Template ID
            str(order),     # Order
            stage_name,     # Stage Name
            description,    # Description
            required_docs,  # Required Docs
            responsible,    # Responsible
            estimated_days, # Estimated Days
            notes,          # Notes
            now,            # Created At
        ]
        append_business_row("roadmap_template_stages", row)

        # Обновить счётчик этапов в шаблоне
        _increment_template_stages_count(template_id)

        log.info(f"add_roadmap_template_stage: {stage_id} / {template_id} / #{order} {stage_name}")
        return {"ok": True, "stage_id": stage_id, "order": order, "error": None}

    except Exception as exc:
        log.error(f"add_roadmap_template_stage error: {exc}")
        return {"ok": False, "stage_id": "", "order": 0, "error": str(exc)}


def _increment_template_stages_count(template_id: str) -> None:
    """Увеличить Stages Count на 1 в ROADMAP_TEMPLATE_REGISTRY."""
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return
        headers = all_values[0]
        cnt_col = headers.index("Stages Count") if "Stages Count" in headers else None
        if cnt_col is None:
            return
        for i, row in enumerate(all_values[1:], start=2):
            if row and row[0].strip() == template_id:
                current = int(row[cnt_col]) if cnt_col < len(row) and row[cnt_col].isdigit() else 0
                sheet.update_cell(i, cnt_col + 1, str(current + 1))
                return
    except Exception as exc:
        log.warning(f"_increment_template_stages_count({template_id}) error: {exc}")


def find_template_stages(template_id: str) -> list[dict]:
    """
    Получить все этапы шаблона, отсортированные по Order.

    Phase 28E: also returns each stage's own knowledge-ID columns
    (sop_ids/checklist_ids/material_ids/document_template_ids/faq_ids,
    each a list[str]) — read directly from this same ROADMAP_TEMPLATE_STAGES
    row, since this module already owns that registry. This replaces
    the former business_core.knowledge_manager.find_knowledge_by_template_stage()
    call that create_stages_from_template_record() used to make — that
    was a Core -> Extension read dependency for data that physically
    lives in a registry this module already owns; no Extension import
    is needed to read a column of your own sheet.
    """
    if not template_id:
        return []
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_stages")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []
        headers = all_values[0]

        def _g(row, h):
            try:
                return row[headers.index(h)].strip() if h in headers else ""
            except IndexError:
                return ""

        def _ids(row, h):
            val = _g(row, h)
            return [x.strip() for x in val.split(",") if x.strip()]

        t_col   = headers.index("Template ID") if "Template ID" in headers else None
        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if t_col is not None and t_col < len(row) and row[t_col].strip() == template_id:
                results.append({
                    "stage_id":      _g(row, "Stage ID"),
                    "template_id":   _g(row, "Template ID"),
                    "order":         _g(row, "Order"),
                    "stage_name":    _g(row, "Stage Name"),
                    "description":   _g(row, "Description"),
                    "required_docs": _g(row, "Required Docs"),
                    "responsible":   _g(row, "Responsible"),
                    "estimated_days":_g(row, "Estimated Days"),
                    "notes":         _g(row, "Notes"),
                    "sop_ids":               _ids(row, "SOP IDs"),
                    "checklist_ids":         _ids(row, "Checklist IDs"),
                    "material_ids":          _ids(row, "Materials IDs"),
                    "document_template_ids": _ids(row, "Document Template IDs"),
                    "faq_ids":               _ids(row, "FAQ IDs"),
                })
        results.sort(key=lambda x: int(x["order"]) if x["order"].isdigit() else 0)
        return results
    except Exception as exc:
        log.warning(f"find_template_stages({template_id}) error: {exc}")
        return []


# ═══════════════════════════════════════════════════════════════
# Integration: create real roadmap stages from template
# ═══════════════════════════════════════════════════════════════

def create_stages_from_template_record(roadmap_id: str, template_id: str) -> dict:
    """
    Создать реальные этапы roadmap из шаблона ROADMAP_TEMPLATE_STAGES.

    В отличие от create_roadmap_stages_from_template (который использует
    встроенные ROADMAP_TEMPLATES), этот метод читает этапы из Google Sheets.

    Phase 28D/28E: this function no longer writes ROADMAP_STAGES itself
    and no longer imports business_core.knowledge_manager or
    business_core.stage_entity_relations. It now reads the template
    stages (via find_template_stages(), which since Phase 28E also
    carries each stage's own knowledge-ID columns) and delegates the
    actual Stage row creation to business_core.roadmap_manager.
    ensure_roadmap_stages() — the single approved owner of
    ROADMAP_STAGES writes. This is a Core -> Core call (Roadmap Template
    Manager -> Roadmap Manager), not a layering violation.

    Relation-copying (business_core.stage_entity_relations.
    copy_template_relations_to_stage(), previously done inline here) is
    an Extension-layer concern and has moved to the orchestrator,
    business_core.business_builder.create_roadmap_for_object() — this
    function itself never calls it anymore. "partial_success"/
    "relation_copy_errors"/"relation_copy_created_count" are kept in
    the return shape for backward compatibility with any caller still
    reading those keys, but are now always the neutral/empty values
    below, since this function performs no relation-copying of its own.

    Returns:
        {
            "ok":           bool,
            "stages_count": int,
            "warning":      str | None,
            "stage_ids":    list[str],
            "partial_success":             bool,   # always False — see above
            "relation_copy_errors":        tuple,   # always () — see above
            "relation_copy_created_count": int,     # always 0 — see above
        }
    """
    if not roadmap_id or not template_id:
        return {
            "ok": False, "stages_count": 0,
            "warning": "roadmap_id и template_id обязательны", "stage_ids": [],
            "partial_success": False, "relation_copy_errors": (), "relation_copy_created_count": 0,
        }

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


# ═══════════════════════════════════════════════════════════════
# Phase 28F: Template Stage knowledge-ID ownership.
#
# ROADMAP_TEMPLATE_STAGES is owned exclusively by this module. Before
# Phase 28F, business_core.knowledge_manager.link_knowledge_to_template_stage()
# wrote directly to this sheet via update_cell() — an Extension-layer
# module writing a Core registry. This function is the sole owner API
# for that write; knowledge_manager now calls it instead of touching
# the sheet itself.
# ═══════════════════════════════════════════════════════════════

def _merge_id_list(existing: str, new_ids: list[str]) -> str:
    """
    Union existing comma-separated IDs with new_ids, de-duplicated,
    order-preserving. Local, intentional duplicate of business_core.
    knowledge_manager._merge_ids()'s exact logic — kept private and
    self-contained here rather than imported, matching the same
    reasoning as business_core.stage_entity_relations._parse_legacy_id_list()
    (Phase 26B): the write now belongs to this module, so its merge
    logic does too.
    """
    parts = [x.strip() for x in existing.split(",") if x.strip()]
    result = list(parts)
    for nid in new_ids:
        nid = nid.strip()
        if nid and nid not in result:
            result.append(nid)
    return ",".join(result)


def update_template_stage_knowledge_ids(
    template_stage_id: str,
    sop_ids: list[str] | None = None,
    checklist_ids: list[str] | None = None,
    material_ids: list[str] | None = None,
    document_template_ids: list[str] | None = None,
    faq_ids: list[str] | None = None,
) -> dict:
    """
    Merge (union, never overwrite) knowledge IDs into one
    ROADMAP_TEMPLATE_STAGES row's SOP IDs / Checklist IDs /
    Materials IDs / Document Template IDs / FAQ IDs columns.

    Header-mapped: column positions are read from the sheet's actual
    header row, never assumed by position. Only columns for which
    new IDs were actually passed are touched; a column already
    containing all of the given IDs is left unwritten (no-op merge).

    Returns:
        {"ok": bool, "updated": bool, "error": str | None}
    """
    if not template_stage_id:
        return {"ok": False, "updated": False, "error": "template_stage_id обязателен"}

    knowledge_map = {
        "SOP IDs":               sop_ids or [],
        "Checklist IDs":         checklist_ids or [],
        "Materials IDs":         material_ids or [],
        "Document Template IDs": document_template_ids or [],
        "FAQ IDs":               faq_ids or [],
    }
    if all(not v for v in knowledge_map.values()):
        return {"ok": True, "updated": False, "error": None}

    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_stages")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "updated": False, "error": "Лист пуст"}
        headers = all_values[0]

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0].strip():
                continue
            if row[0].strip() != template_stage_id:
                continue

            for col_name, new_ids in knowledge_map.items():
                if not new_ids:
                    continue
                col_idx = headers.index(col_name) if col_name in headers else None
                if col_idx is None:
                    continue
                existing = row[col_idx].strip() if col_idx < len(row) else ""
                merged = _merge_id_list(existing, new_ids)
                if merged != existing:
                    sheet.update_cell(i, col_idx + 1, merged)

            log.info(f"update_template_stage_knowledge_ids: {template_stage_id}")
            return {"ok": True, "updated": True, "error": None}

        return {"ok": False, "updated": False,
                "error": f"Stage {template_stage_id} не найден"}

    except Exception as exc:
        log.error(f"update_template_stage_knowledge_ids({template_stage_id}) error: {exc}")
        return {"ok": False, "updated": False, "error": str(exc)}
