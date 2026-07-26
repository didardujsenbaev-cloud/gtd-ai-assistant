"""
Document Registry — pure read-only relation/folder-resolution helpers
(Phase 15A/15B, narrowed by Phase 37D per ADR-020 §3/§4).

Phase 37D moved every persistence-adjacent function (Document ID/
Document Family ID generation, the canonical operational status
vocabulary) into business_core/document_manager.py — the sole
persistence owner of DOCUMENT_REGISTRY after this phase. This module
now contains ONLY read-only cross-entity validation and Drive-folder
resolution helpers; it writes nothing, and architecture guards
(test_document_architecture_guards.py) prove it cannot write
document_registry.

Do not add a write path here — document_manager.py is the sole
persistence owner (ADR-020 §3).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


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
    from business_core.person_manager import find_person_by_id

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
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(resolved_object_id)
        if obj is None:
            return {"ok": False, "error": f"Object {resolved_object_id} не найден."}
        obj_biz_id = obj.get("biz_id", "")
        if obj_biz_id and obj_biz_id != business_id:
            return {
                "ok": False,
                "error": (
                    f"Противоречие: Object {resolved_object_id} принадлежит "
                    f"бизнесу {obj_biz_id}, а указан Business {business_id}."
                ),
            }
        obj_client_id = obj.get("client_id", "")
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
        person = find_person_by_id(resolved_client_id)
        if person is None:
            return {"ok": False, "error": f"Client {resolved_client_id} не найден."}
        person_biz_ids = person["biz_ids"]
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
    from business_core.person_manager import find_person_by_id

    if object_id:
        from business_core.object_manager import find_object_by_id
        obj = find_object_by_id(object_id)
        folder_id = (obj or {}).get("drive_folder_id", "").strip()
        if folder_id:
            return {"ok": True, "folder_id": folder_id, "level": "object", "source_id": object_id}

    if client_id:
        person = find_person_by_id(client_id)
        folder_id = (person or {}).get("drive_folder_id", "") or ""
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

    ADR-020 §16/§17 designates document_requirements_query.
    evaluate_scope() the sole canonical missing-document evaluator and
    calls this function "legacy", to be removed or converted into a
    thin adapter over evaluate_scope() where safe. Phase 37D attempted
    that conversion and found it NOT safely convertible under this
    phase's existing test mocks: document_requirements.py (the engine
    evaluate_scope() delegates to) reads via sheets.find_row_by_id(),
    not sheets.read_business_sheet() — a different primitive than the
    one /docs4stage's existing tests mock — so swapping the
    implementation would require reworking those tests' mocking
    strategy, which is out of this phase's bounded scope (ADR-020 §38:
    "do not rewrite already-sound components"; this one just isn't
    provably safe to touch yet). This function therefore remains its
    own independent, deterministic, exact-ID-matching algorithm for
    now — DEFERRED, not resolved: Phase 37E (full caller migration)
    should retire this function in favor of calling evaluate_scope()
    directly from docs4stage_cmd, with correspondingly reworked test
    mocks for the Requirements engine's actual read primitives.

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
