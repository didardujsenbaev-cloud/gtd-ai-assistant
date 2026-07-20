"""
Phase 15A: Document Registry Foundation.

Scope (see DOCUMENT_REGISTRY_ARCHITECTURE.md for the full design):
  - Register ONE already-existing Drive file against optional
    Client/Object/Roadmap/Stage/Document Template links.
  - No upload-from-Telegram, no review workflow, no versioning beyond
    "every /registerdoc call creates a new family at version 1", no
    bulk operations, no automatic Drive file moves.

Status model (Phase 15A only two values are writable):
    uploaded, archived
Reserved for Phase 15B (validated here as "not yet allowed", not
silently accepted): under_review, approved, rejected, superseded.

ID strategy: "DOC" is already used live by document_template_registry
(Document Template ID). Document Registry uses "DREG" for Document ID
(via the existing generate_next_id() — scans column 1, no change
needed there) and "DFAM" for Document Family ID, which needs its own
generator below because generate_next_id() only ever scans column 1
of a sheet, and Document Family ID is not that sheet's first column.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

log = logging.getLogger(__name__)

DOCUMENT_STATUS_ALLOWED = ("uploaded", "archived")
DOCUMENT_STATUS_RESERVED = ("under_review", "approved", "rejected", "superseded")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def compute_next_document_and_family_ids(all_values: list) -> tuple[str, str]:
    """
    Phase 15A safety refinement: compute BOTH the next Document ID
    (DREG-xxx) and Document Family ID (DFAM-xxx) from a single
    already-fetched `all_values` snapshot of DOCUMENT_REGISTRY.

    Used by registerdoc_confirm() so ID generation happens exactly
    once, from one sheet read, inside the same confirm execution that
    writes the row — never as two separate reads (one per prefix) that
    could observe different sheet states.
    """
    doc_pattern = re.compile(r"^DREG-(\d+)$", re.IGNORECASE)
    fam_pattern = re.compile(r"^DFAM-(\d+)$", re.IGNORECASE)

    if not all_values:
        return "DREG-001", "DFAM-001"

    headers = all_values[0]
    doc_col = headers.index("Document ID") if "Document ID" in headers else 0
    fam_col = headers.index("Document Family ID") if "Document Family ID" in headers else None

    doc_numbers, fam_numbers = [], []
    for row in all_values[1:]:
        if doc_col < len(row) and row[doc_col]:
            m = doc_pattern.match(row[doc_col])
            if m:
                doc_numbers.append(int(m.group(1)))
        if fam_col is not None and fam_col < len(row) and row[fam_col]:
            m = fam_pattern.match(row[fam_col])
            if m:
                fam_numbers.append(int(m.group(1)))

    next_doc = max(doc_numbers, default=0) + 1
    next_fam = max(fam_numbers, default=0) + 1
    return f"DREG-{next_doc:03d}", f"DFAM-{next_fam:03d}"


def generate_next_family_id() -> str:
    """
    DFAM-001, DFAM-002, ... — scans the 'Document Family ID' column of
    DOCUMENT_REGISTRY specifically (not column 1, so generate_next_id()
    cannot be reused directly for this one column).
    """
    from business_core.sheets import get_business_sheet, get_header_index_map

    prefix = "DFAM"
    try:
        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"generate_next_family_id: не удалось прочитать DOCUMENT_REGISTRY: {exc}")
        return f"{prefix}-001"

    if len(all_values) < 2:
        return f"{prefix}-001"

    idx = get_header_index_map(all_values[0])
    fam_col = idx.get("Document Family ID")
    if fam_col is None:
        return f"{prefix}-001"

    pattern = re.compile(rf"^{prefix}-(\d+)$", re.IGNORECASE)
    numbers = []
    for row in all_values[1:]:
        if fam_col < len(row) and row[fam_col]:
            m = pattern.match(row[fam_col])
            if m:
                numbers.append(int(m.group(1)))

    next_num = max(numbers, default=0) + 1
    return f"{prefix}-{next_num:03d}"


def resolve_and_validate_links(
    business_id: str,
    client_id: str = "",
    object_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    document_template_id: str = "",
) -> dict:
    """
    Phase 15A referential validation. Every non-empty ID must exist;
    the chain Stage -> Roadmap -> Object -> Client must be internally
    consistent, and every resolved entity must belong to business_id.

    Resolution order is most-specific-first (Stage, then Roadmap, then
    Object, then Client) so that a caller can pass ONLY stage_id and
    have roadmap_id/object_id/client_id auto-filled from it, rather
    than being forced to spell out the whole chain by hand. If a value
    IS explicitly given at a less-specific level and it disagrees with
    what the more-specific level implies, that is a contradiction and
    the whole registration is rejected — no row is ever written on a
    contradiction.

    Returns:
        {"ok": True, "resolved": {"business_id":..., "client_id":...,
         "object_id":..., "roadmap_id":..., "stage_id":...,
         "document_template_id":...}}
        или
        {"ok": False, "error": str}
    """
    from business_core.sheets import read_business_sheet
    from business_core.business_builder import get_person_biz_ids

    if not business_id:
        return {"ok": False, "error": "Business ID обязателен."}

    biz_rows = read_business_sheet("biz_registry")
    biz = next((b for b in biz_rows if b.get("ID", "") == business_id), None)
    if biz is None:
        return {"ok": False, "error": f"Business {business_id} не найден."}

    resolved_stage_id = stage_id
    resolved_roadmap_id = roadmap_id
    resolved_object_id = object_id
    resolved_client_id = client_id

    # ── Stage -> Roadmap ────────────────────────────────────────
    if resolved_stage_id:
        stages = read_business_sheet("roadmap_stages")
        stage = next((s for s in stages if s.get("Stage ID", "") == resolved_stage_id), None)
        if stage is None:
            return {"ok": False, "error": f"Stage {resolved_stage_id} не найден."}
        stage_roadmap_id = stage.get("Roadmap ID", "")
        if resolved_roadmap_id and stage_roadmap_id and resolved_roadmap_id != stage_roadmap_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Stage {resolved_stage_id} принадлежит "
                    f"Roadmap {stage_roadmap_id}, а указан Roadmap {resolved_roadmap_id}."
                ),
            }
        resolved_roadmap_id = resolved_roadmap_id or stage_roadmap_id

    # ── Roadmap -> Object, Roadmap.Business ─────────────────────
    if resolved_roadmap_id:
        roadmaps = read_business_sheet("roadmaps")
        rm = next((r for r in roadmaps if r.get("Roadmap ID", "") == resolved_roadmap_id), None)
        if rm is None:
            return {"ok": False, "error": f"Roadmap {resolved_roadmap_id} не найден."}
        rm_biz_id = rm.get("Business ID", "")
        if rm_biz_id and rm_biz_id != business_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Roadmap {resolved_roadmap_id} принадлежит "
                    f"бизнесу {rm_biz_id}, а указан Business {business_id}."
                ),
            }
        rm_object_id = rm.get("Object ID", "")
        if resolved_object_id and rm_object_id and resolved_object_id != rm_object_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Roadmap {resolved_roadmap_id} связан с "
                    f"Object {rm_object_id}, а указан Object {resolved_object_id}."
                ),
            }
        resolved_object_id = resolved_object_id or rm_object_id

    # ── Object -> Client, Object.Biz ─────────────────────────────
    if resolved_object_id:
        objects = read_business_sheet("object_registry")
        obj = next((o for o in objects if o.get("OBJ ID", "") == resolved_object_id), None)
        if obj is None:
            return {"ok": False, "error": f"Object {resolved_object_id} не найден."}
        obj_biz_id = obj.get("Biz ID", "")
        if obj_biz_id and obj_biz_id != business_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Object {resolved_object_id} принадлежит "
                    f"бизнесу {obj_biz_id}, а указан Business {business_id}."
                ),
            }
        obj_client_id = obj.get("Client ID", "")
        if resolved_client_id and obj_client_id and resolved_client_id != obj_client_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Object {resolved_object_id} принадлежит "
                    f"клиенту {obj_client_id}, а указан Client {resolved_client_id}."
                ),
            }
        resolved_client_id = resolved_client_id or obj_client_id

    # ── Client -> Business ───────────────────────────────────────
    if resolved_client_id:
        people = read_business_sheet("people_registry")
        person = next((p for p in people if p.get("ID", "") == resolved_client_id), None)
        if person is None:
            return {"ok": False, "error": f"Client {resolved_client_id} не найден."}
        person_biz_ids = get_person_biz_ids(resolved_client_id)
        if person_biz_ids and business_id not in person_biz_ids:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Client {resolved_client_id} не связан "
                    f"с Business {business_id} (связан с: {', '.join(person_biz_ids)})."
                ),
            }

    # ── Document Template (independent existence check only) ────
    if document_template_id:
        templates = read_business_sheet("document_template_registry")
        tmpl = next(
            (t for t in templates if t.get("Document Template ID", "") == document_template_id),
            None,
        )
        if tmpl is None:
            return {"ok": False, "error": f"Document Template {document_template_id} не найден."}
        tmpl_biz_id = tmpl.get("Biz ID", "")
        if tmpl_biz_id and tmpl_biz_id != business_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Document Template {document_template_id} "
                    f"принадлежит бизнесу {tmpl_biz_id}, а указан Business {business_id}."
                ),
            }

    return {
        "ok": True,
        "resolved": {
            "business_id": business_id,
            "client_id": resolved_client_id,
            "object_id": resolved_object_id,
            "roadmap_id": resolved_roadmap_id,
            "stage_id": resolved_stage_id,
            "document_template_id": document_template_id,
        },
    }


def resolve_target_drive_folder(
    business_id: str,
    client_id: str = "",
    object_id: str = "",
    stage_id: str = "",
) -> dict:
    """
    Phase 15B: выбрать существующую целевую Drive-папку для загрузки
    документа, most-specific-first: Object -> Client -> Business.

    Stage folder намеренно НЕ поддерживается: ROADMAP_STAGES не имеет
    колонки "Drive Folder ID" в текущей схеме (см. BUSINESS_HEADERS
    ["roadmap_stages"] в business_core/sheets.py) — придумывать или
    создавать Stage-папку запрещено условиями Phase 15B, поэтому
    stage_id здесь принимается только для единообразия сигнатуры и
    никогда не используется для выбора папки.

    Ни одна папка не создаётся — используется только уже существующий
    и непустой "Drive Folder ID" на найденном уровне.

    Returns:
        {"ok": True, "folder_id": str, "level": "object"|"client"|"business",
         "source_id": str}
        или
        {"ok": False, "error": str}
    """
    from business_core.sheets import read_business_sheet

    if object_id:
        objects = read_business_sheet("object_registry")
        obj = next((o for o in objects if o.get("OBJ ID", "") == object_id), None)
        folder_id = (obj or {}).get("Drive Folder ID", "").strip()
        if folder_id:
            return {"ok": True, "folder_id": folder_id, "level": "object", "source_id": object_id}

    if client_id:
        people = read_business_sheet("people_registry")
        person = next((p for p in people if p.get("ID", "") == client_id), None)
        folder_id = (person or {}).get("Drive Folder ID", "").strip()
        if folder_id:
            return {"ok": True, "folder_id": folder_id, "level": "client", "source_id": client_id}

    if business_id:
        bizzes = read_business_sheet("biz_registry")
        biz = next((b for b in bizzes if b.get("ID", "") == business_id), None)
        folder_id = (biz or {}).get("Drive Folder ID", "").strip()
        if folder_id:
            return {"ok": True, "folder_id": folder_id, "level": "business", "source_id": business_id}

    return {
        "ok": False,
        "error": (
            "Не найдена ни одна существующая целевая папка Drive "
            "(пустой 'Drive Folder ID' у Object/Client/Business). "
            "Загрузка остановлена до создания записи."
        ),
    }


def get_documents_for_stage(stage_id: str) -> list[dict]:
    """Read-only: все зарегистрированные документы для этапа."""
    from business_core.sheets import read_business_sheet

    if not stage_id:
        return []
    docs = read_business_sheet("document_registry")
    return [d for d in docs if d.get("Stage ID", "") == stage_id]


def compute_stage_document_status(stage_id: str) -> dict:
    """
    Phase 15A required-vs-uploaded computation for one stage — exact
    ID-based match against Document Template IDs linked to the stage
    (Phase 8C knowledge binding), NOT keyword matching against filenames
    (that heuristic lived in the now-superseded material_manager.py).

    Returns:
        {
            "stage_id": str,
            "template_ids_required": list[str],   # from ROADMAP_STAGES."Document Template IDs"
            "matched": list[str],                  # template IDs with >=1 registered document
            "missing": list[str],                  # template IDs with 0 registered documents
            "unmatched_documents": list[dict],      # registered docs with no/foreign template ID
            "matchable": bool,                      # False if the stage has no Document Template
                                                      # IDs at all — "не сопоставлено", not a guess
        }
    """
    from business_core.sheets import read_business_sheet

    stages = read_business_sheet("roadmap_stages")
    stage = next((s for s in stages if s.get("Stage ID", "") == stage_id), None)
    if stage is None:
        return {
            "stage_id": stage_id, "matchable": False,
            "template_ids_required": [], "matched": [], "missing": [],
            "unmatched_documents": [],
        }

    raw_template_ids = stage.get("Document Template IDs", "")
    template_ids_required = [t.strip() for t in raw_template_ids.split(",") if t.strip()]

    documents = get_documents_for_stage(stage_id)

    if not template_ids_required:
        return {
            "stage_id": stage_id,
            "matchable": False,
            "template_ids_required": [],
            "matched": [],
            "missing": [],
            "unmatched_documents": documents,
        }

    documents_by_template = {}
    unmatched_documents = []
    for d in documents:
        tid = d.get("Document Template ID", "")
        if tid and tid in template_ids_required:
            documents_by_template.setdefault(tid, []).append(d)
        else:
            unmatched_documents.append(d)

    matched = [t for t in template_ids_required if t in documents_by_template]
    missing = [t for t in template_ids_required if t not in documents_by_template]

    return {
        "stage_id": stage_id,
        "matchable": True,
        "template_ids_required": template_ids_required,
        "matched": matched,
        "missing": missing,
        "unmatched_documents": unmatched_documents,
    }
