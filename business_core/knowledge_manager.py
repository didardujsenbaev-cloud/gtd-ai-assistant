"""
Knowledge Manager — SOP, Checklist, Document Templates, FAQ.

Phase 8C: SOP / Checklist / Materials Binding.

Архитектура:
  Template Stage → SOP / Checklist / DocTemplate / FAQ
  При /startroadmap knowledge IDs копируются в реальные ROADMAP_STAGES.

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

def generate_sop_id() -> str:
    """SOP-001, SOP-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("sop_registry")
    except Exception as exc:
        log.warning(f"generate_sop_id error: {exc}")
        return "SOP-001"


def generate_checklist_id() -> str:
    """CHK-001, CHK-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("checklist_registry")
    except Exception as exc:
        log.warning(f"generate_checklist_id error: {exc}")
        return "CHK-001"


def generate_document_template_id() -> str:
    """DOC-001, DOC-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("document_template_registry")
    except Exception as exc:
        log.warning(f"generate_document_template_id error: {exc}")
        return "DOC-001"


def generate_faq_id() -> str:
    """FAQ-001, FAQ-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("faq_registry")
    except Exception as exc:
        log.warning(f"generate_faq_id error: {exc}")
        return "FAQ-001"


# ═══════════════════════════════════════════════════════════════
# Create records
# ═══════════════════════════════════════════════════════════════

def create_sop_record(
    title:              str,
    biz_id:             str = "",
    service_id:         str = "",
    template_id:        str = "",
    template_stage_id:  str = "",
    purpose:            str = "",
    steps:              str = "",
    expected_result:    str = "",
    owner_role:         str = "",
    drive_file_id:      str = "",
    google_drive:       str = "",
    version:            str = "1.0",
    status:             str = "active",
    notes:              str = "",
) -> dict:
    """
    Создать SOP в SOP_REGISTRY.

    Returns:
        {"ok": bool, "sop_id": str, "error": str | None}
    """
    if not title:
        return {"ok": False, "sop_id": "", "error": "title обязателен"}
    try:
        from business_core.sheets import append_business_row
        now    = datetime.now().strftime("%Y-%m-%d")
        sop_id = generate_sop_id()
        row    = [
            sop_id, biz_id, service_id, template_id, template_stage_id,
            title, purpose, steps, expected_result, owner_role,
            drive_file_id, google_drive, version, status, notes,
            now, now,
        ]
        append_business_row("sop_registry", row)
        log.info(f"create_sop_record: {sop_id} / {title}")
        return {"ok": True, "sop_id": sop_id, "error": None}
    except Exception as exc:
        log.error(f"create_sop_record error: {exc}")
        return {"ok": False, "sop_id": "", "error": str(exc)}


def create_checklist_record(
    title:              str,
    biz_id:             str = "",
    service_id:         str = "",
    template_id:        str = "",
    template_stage_id:  str = "",
    items:              str = "",
    required_items:     str = "",
    optional_items:     str = "",
    completion_criteria: str = "",
    owner_role:         str = "",
    drive_file_id:      str = "",
    google_drive:       str = "",
    version:            str = "1.0",
    status:             str = "active",
    notes:              str = "",
) -> dict:
    """
    Создать Checklist в CHECKLIST_REGISTRY.

    Returns:
        {"ok": bool, "checklist_id": str, "error": str | None}
    """
    if not title:
        return {"ok": False, "checklist_id": "", "error": "title обязателен"}
    try:
        from business_core.sheets import append_business_row
        now          = datetime.now().strftime("%Y-%m-%d")
        checklist_id = generate_checklist_id()
        row          = [
            checklist_id, biz_id, service_id, template_id, template_stage_id,
            title, items, required_items, optional_items,
            completion_criteria, owner_role,
            drive_file_id, google_drive, version, status, notes,
            now, now,
        ]
        append_business_row("checklist_registry", row)
        log.info(f"create_checklist_record: {checklist_id} / {title}")
        return {"ok": True, "checklist_id": checklist_id, "error": None}
    except Exception as exc:
        log.error(f"create_checklist_record error: {exc}")
        return {"ok": False, "checklist_id": "", "error": str(exc)}


def create_document_template_record(
    title:              str,
    biz_id:             str = "",
    service_id:         str = "",
    template_id:        str = "",
    template_stage_id:  str = "",
    document_type:      str = "",
    description:        str = "",
    drive_file_id:      str = "",
    google_drive:       str = "",
    version:            str = "1.0",
    status:             str = "active",
    notes:              str = "",
) -> dict:
    """
    Создать Document Template в DOCUMENT_TEMPLATE_REGISTRY.

    Returns:
        {"ok": bool, "doc_template_id": str, "error": str | None}
    """
    if not title:
        return {"ok": False, "doc_template_id": "", "error": "title обязателен"}
    try:
        from business_core.sheets import append_business_row
        now             = datetime.now().strftime("%Y-%m-%d")
        doc_template_id = generate_document_template_id()
        row             = [
            doc_template_id, biz_id, service_id, template_id, template_stage_id,
            title, document_type, description,
            drive_file_id, google_drive, version, status, notes,
            now, now,
        ]
        append_business_row("document_template_registry", row)
        log.info(f"create_document_template_record: {doc_template_id} / {title}")
        return {"ok": True, "doc_template_id": doc_template_id, "error": None}
    except Exception as exc:
        log.error(f"create_document_template_record error: {exc}")
        return {"ok": False, "doc_template_id": "", "error": str(exc)}


def create_faq_record(
    question:           str,
    answer:             str,
    biz_id:             str = "",
    service_id:         str = "",
    template_id:        str = "",
    template_stage_id:  str = "",
    category:           str = "",
    status:             str = "active",
    notes:              str = "",
) -> dict:
    """
    Создать FAQ в FAQ_REGISTRY.

    Returns:
        {"ok": bool, "faq_id": str, "error": str | None}
    """
    if not question:
        return {"ok": False, "faq_id": "", "error": "question обязателен"}
    try:
        from business_core.sheets import append_business_row
        now    = datetime.now().strftime("%Y-%m-%d")
        faq_id = generate_faq_id()
        row    = [
            faq_id, biz_id, service_id, template_id, template_stage_id,
            question, answer, category, status, notes,
            now, now,
        ]
        append_business_row("faq_registry", row)
        log.info(f"create_faq_record: {faq_id} / {question[:40]}")
        return {"ok": True, "faq_id": faq_id, "error": None}
    except Exception as exc:
        log.error(f"create_faq_record error: {exc}")
        return {"ok": False, "faq_id": "", "error": str(exc)}


# ═══════════════════════════════════════════════════════════════
# Find by ID
# ═══════════════════════════════════════════════════════════════

def _find_by_id(sheet_key: str, id_col: str, record_id: str) -> Optional[dict]:
    """Универсальный поиск по ID в любом knowledge листе."""
    if not record_id:
        return None
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet(sheet_key)
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
            if row[0].strip() == record_id:
                return {h: _g(row, h) for h in headers}
    except Exception as exc:
        log.warning(f"_find_by_id({sheet_key}, {record_id}) error: {exc}")
    return None


def find_sop_by_id(sop_id: str) -> Optional[dict]:
    return _find_by_id("sop_registry", "SOP ID", sop_id)


def find_checklist_by_id(checklist_id: str) -> Optional[dict]:
    return _find_by_id("checklist_registry", "Checklist ID", checklist_id)


def find_document_template_by_id(doc_template_id: str) -> Optional[dict]:
    return _find_by_id("document_template_registry", "Document Template ID", doc_template_id)


def find_faq_by_id(faq_id: str) -> Optional[dict]:
    return _find_by_id("faq_registry", "FAQ ID", faq_id)


# ═══════════════════════════════════════════════════════════════
# Knowledge binding helpers
# ═══════════════════════════════════════════════════════════════

def _merge_ids(existing: str, new_ids: list[str]) -> str:
    """
    Объединить существующие ID с новыми, без дублей.

    "SOP-001,SOP-002" + ["SOP-002","SOP-003"] → "SOP-001,SOP-002,SOP-003"
    """
    parts  = [x.strip() for x in existing.split(",") if x.strip()]
    result = list(parts)
    for nid in new_ids:
        nid = nid.strip()
        if nid and nid not in result:
            result.append(nid)
    return ",".join(result)


def link_knowledge_to_template_stage(
    template_stage_id:      str,
    sop_ids:                list[str] | None = None,
    checklist_ids:          list[str] | None = None,
    material_ids:           list[str] | None = None,
    document_template_ids:  list[str] | None = None,
    faq_ids:                list[str] | None = None,
) -> dict:
    """
    Привязать knowledge к этапу шаблона в ROADMAP_TEMPLATE_STAGES.

    Обновляет колонки SOP IDs, Checklist IDs, Materials IDs,
    Document Template IDs, FAQ IDs без перезаписи уже привязанных.

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
    # Проверяем — есть ли что обновлять
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
                merged   = _merge_ids(existing, new_ids)
                if merged != existing:
                    sheet.update_cell(i, col_idx + 1, merged)

            log.info(f"link_knowledge_to_template_stage: {template_stage_id}")
            return {"ok": True, "updated": True, "error": None}

        return {"ok": False, "updated": False,
                "error": f"Stage {template_stage_id} не найден"}

    except Exception as exc:
        log.error(f"link_knowledge_to_template_stage error: {exc}")
        return {"ok": False, "updated": False, "error": str(exc)}


def find_knowledge_by_template_stage(template_stage_id: str) -> dict:
    """
    Получить все привязанные knowledge по ID этапа шаблона.

    Returns:
        {
            "sop_ids":               list[str],
            "checklist_ids":         list[str],
            "material_ids":          list[str],
            "document_template_ids": list[str],
            "faq_ids":               list[str],
        }
    """
    empty = {
        "sop_ids": [], "checklist_ids": [], "material_ids": [],
        "document_template_ids": [], "faq_ids": [],
    }
    if not template_stage_id:
        return empty

    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_template_stages")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return empty
        headers = all_values[0]

        def _ids(row, col_name):
            if col_name not in headers:
                return []
            idx = headers.index(col_name)
            val = row[idx].strip() if idx < len(row) else ""
            return [x.strip() for x in val.split(",") if x.strip()]

        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if row[0].strip() == template_stage_id:
                return {
                    "sop_ids":               _ids(row, "SOP IDs"),
                    "checklist_ids":         _ids(row, "Checklist IDs"),
                    "material_ids":          _ids(row, "Materials IDs"),
                    "document_template_ids": _ids(row, "Document Template IDs"),
                    "faq_ids":               _ids(row, "FAQ IDs"),
                }

    except Exception as exc:
        log.warning(f"find_knowledge_by_template_stage({template_stage_id}) error: {exc}")
    return empty


def get_knowledge_for_stage(stage_id: str, is_template: bool = False) -> dict:
    """
    Получить knowledge для реального ROADMAP_STAGES этапа.

    Args:
        stage_id:    STAGE-ID или TSTG-ID
        is_template: True если это этап шаблона (ROADMAP_TEMPLATE_STAGES)
    """
    sheet_key = "roadmap_template_stages" if is_template else "roadmap_stages"
    empty = {
        "sop_ids": [], "checklist_ids": [], "material_ids": [],
        "document_template_ids": [], "faq_ids": [],
    }
    if not stage_id:
        return empty

    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet(sheet_key)
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return empty
        headers = all_values[0]

        def _ids(row, col_name):
            if col_name not in headers:
                return []
            idx = headers.index(col_name)
            val = row[idx].strip() if idx < len(row) else ""
            return [x.strip() for x in val.split(",") if x.strip()]

        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if row[0].strip() == stage_id:
                return {
                    "sop_ids":               _ids(row, "SOP IDs"),
                    "checklist_ids":         _ids(row, "Checklist IDs"),
                    "material_ids":          _ids(row, "Materials IDs"),
                    "document_template_ids": _ids(row, "Document Template IDs"),
                    "faq_ids":               _ids(row, "FAQ IDs"),
                }
    except Exception as exc:
        log.warning(f"get_knowledge_for_stage({stage_id}) error: {exc}")
    return empty
