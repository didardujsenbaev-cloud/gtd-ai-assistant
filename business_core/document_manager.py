"""
Document Manager — Operational Document persistence (Phase 37D, ADR-020).

Sole transactional owner of DOCUMENT_REGISTRY. Mirrors task_manager.py's
role for TASK_REGISTRY exactly (ADR-019 precedent) — targeted
sheet.find() + read_row_by_headers(), never a positional-index
assumption (RM-027 precedent).

This module is deliberately low-level only: no Business/Client/Object/
Roadmap/Stage/Document-Template cross-entity validation, no Drive
upload orchestration, no compensation sequencing, no lifecycle
transition policy, no Russian user-facing text. All of that lives
solely in business_builder.py's Document orchestration functions
(register_document/upload_and_register_document/
update_document_admin_fields/transition_document_status) — this module
is the primitive those functions call after their own validation
passes, exactly like organization_manager.assign_person_to_role() is to
business_builder.assign_person_to_role_canonical() (ADR-018 §15).

Two ID generators live here (Document ID and Document Family ID) —
migrated from business_core/document_registry_manager.py (Phase 15A),
which now keeps only pure read-only relation/folder-resolution helpers
(ADR-020 §3/§4). This is the sole implementation of both generators
after Phase 37D.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported. Never writes
document_content (that belongs solely to document_intelligence.py).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Canonical enums (ADR-020 §11)
# ─────────────────────────────────────────────────────────────

DOCUMENT_STATUS = ("uploaded", "under_review", "approved", "rejected", "superseded", "archived")

_DOCUMENT_FIELDS = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID", "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
    # Phase 16C.9C: read_row_by_headers() already returns "" for any
    # wanted header absent from a sparse/legacy row — no special-casing
    # needed for pre-migration rows.
    "Archived At", "Archived By", "Archive Reason", "Previous Status",
]


def _find_document_row(document_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Returns (row_num, row_dict) or None."""
    if not document_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("document_registry")
        cell = sheet.find(document_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        v = read_row_by_headers(headers, row, _DOCUMENT_FIELDS)
        return (cell.row, v)
    except Exception:
        log.warning("_find_document_row infrastructure failure")
        return None


def _document_row_to_dict(row_num: int, v: dict) -> dict:
    return {
        "row_num":              row_num,
        "document_id":          v["Document ID"],
        "document_family_id":   v["Document Family ID"],
        "version":              v["Version"],
        "business_id":          v["Business ID"],
        "client_id":            v["Client ID"],
        "object_id":            v["Object ID"],
        "roadmap_id":           v["Roadmap ID"],
        "stage_id":             v["Stage ID"],
        "document_template_id": v["Document Template ID"],
        "document_name":        v["Document Name"],
        "status":               v["Status"],
        "drive_file_id":        v["Drive File ID"],
        "drive_file_url":       v["Drive File URL"],
        "file_name":            v["File Name"],
        "mime_type":            v["Mime Type"],
        "uploaded_at":          v["Uploaded At"],
        "uploaded_by":          v["Uploaded By"],
        "reviewed_at":          v["Reviewed At"],
        "reviewed_by":          v["Reviewed By"],
        "rejection_reason":     v["Rejection Reason"],
        "notes":                v["Notes"],
        "created_at":           v["Created At"],
        "updated_at":           v["Updated At"],
        "archived_at":          v["Archived At"],
        "archived_by":          v["Archived By"],
        "archive_reason":       v["Archive Reason"],
        "previous_status":      v["Previous Status"],
    }


def find_document_by_id(document_id: str) -> Optional[dict]:
    """
    Find Document by ID. Read-only. Uses sheets.find_row_by_id() — the
    same generic exact-ID primitive every write path (register_document/
    upload_and_register_document) already relies on for its own post-
    write verification, so a document written in the same operation is
    always immediately visible to this lookup.
    """
    if not document_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("document_registry", document_id)
    if not found:
        return None
    row_num, v = found
    return _document_row_to_dict(row_num, {f: v.get(f, "") for f in _DOCUMENT_FIELDS})


def _list_documents_raw() -> list[dict]:
    """Internal: read every DOCUMENT_REGISTRY row, unfiltered."""
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _g(row, h):
            i = idx.get(h)
            return row[i].strip() if (i is not None and i < len(row)) else ""

        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            results.append(_document_row_to_dict(0, {f: _g(row, f) for f in _DOCUMENT_FIELDS}))
        return results
    except Exception as exc:
        log.warning(f"_list_documents_raw() error: {exc}")
        return []


_ARCHIVED_LIKE_STATUSES = ("archived",)


def find_documents_by_drive_file_id(drive_file_id: str, exclude_archived: bool = True) -> list[dict]:
    """
    Read-only. Every Document whose Drive File ID matches, used
    exclusively by business_builder.register_document()'s zero/one/
    multiple reuse policy (ADR-020 §10). Never called by Telegram/other
    callers directly.
    """
    if not drive_file_id:
        return []
    results = [d for d in _list_documents_raw() if d["drive_file_id"] == drive_file_id]
    if exclude_archived:
        results = [d for d in results if d["status"] not in _ARCHIVED_LIKE_STATUSES]
    return results


def compute_next_document_and_family_ids(all_values: list) -> tuple[str, str]:
    """
    Phase 15A safety refinement (migrated from document_registry_manager.py,
    ADR-020 §7): compute BOTH the next Document ID (DREG-xxx) and
    Document Family ID (DFAM-xxx) from a single already-fetched
    `all_values` snapshot of DOCUMENT_REGISTRY — one read, one append,
    no intermediate state where IDs could be observed to disagree with
    what actually gets written.
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
    DOCUMENT_REGISTRY specifically (not column 1, so sheets.
    generate_next_id() cannot be reused directly for this one column).
    Migrated from document_registry_manager.py (ADR-020 §3/§7) — this
    is now the sole implementation.
    """
    from business_core.sheets import get_business_sheet, get_header_index_map

    prefix = "DFAM"
    try:
        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"generate_next_family_id: failed to read DOCUMENT_REGISTRY: {exc}")
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


def create_document(
    business_id: str,
    document_name: str,
    *,
    document_family_id: str = "",
    version: str = "1",
    client_id: str = "",
    object_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    document_template_id: str = "",
    status: str = "uploaded",
    drive_file_id: str = "",
    drive_file_url: str = "",
    file_name: str = "",
    mime_type: str = "",
    uploaded_by: str = "",
    notes: str = "",
) -> dict:
    """
    Create one Operational Document row in DOCUMENT_REGISTRY.
    Low-level write — does not validate Business/Client/Object/Roadmap/
    Stage/Template existence or consistency, does not resolve Drive
    metadata, does not check Drive File ID duplicates. All of that
    policy is exclusively business_builder.register_document()/
    upload_and_register_document() (ADR-020 §9/§10/§11). Calling this
    function directly bypasses that policy by design — it is the
    primitive the orchestrator calls only after its own validation
    passes, and only with a Document ID already generated by
    compute_next_document_and_family_ids() from the same sheet read.

    Returns:
        {"ok": bool, "document_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "document_id": "", "code": "", "error": "business_id обязателен"}
    if not document_name:
        return {"ok": False, "document_id": "", "code": "", "error": "document_name обязателен"}
    if status not in DOCUMENT_STATUS:
        return {
            "ok": False, "document_id": "", "code": "INVALID_DOCUMENT_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(DOCUMENT_STATUS)}",
        }

    try:
        from business_core.sheets import get_business_sheet, append_business_row, row_from_header_map
        from datetime import datetime, timezone

        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
        headers = all_values[0] if all_values else sheet.row_values(1)

        document_id, generated_family_id = compute_next_document_and_family_ids(all_values)
        family_id = document_family_id or generated_family_id

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        values = {
            "Document ID": document_id, "Document Family ID": family_id, "Version": version,
            "Business ID": business_id, "Client ID": client_id, "Object ID": object_id,
            "Roadmap ID": roadmap_id, "Stage ID": stage_id, "Document Template ID": document_template_id,
            "Document Name": document_name, "Status": status,
            "Drive File ID": drive_file_id, "Drive File URL": drive_file_url,
            "File Name": file_name, "Mime Type": mime_type,
            "Uploaded At": now, "Uploaded By": uploaded_by,
            "Reviewed At": "", "Reviewed By": "", "Rejection Reason": "",
            "Notes": notes, "Created At": now, "Updated At": now,
        }
        row = row_from_header_map(headers, values)
        append_business_row("document_registry", row)
        log.info(f"create_document: {document_id} / family={family_id}")
        return {"ok": True, "document_id": document_id, "code": "DOCUMENT_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_document error: {exc}")
        return {"ok": False, "document_id": "", "code": "", "error": str(exc)}


_DOCUMENT_ADMIN_EDITABLE_FIELDS = ("Document Name", "Notes")

# Phase 37D (ADR-020 §6/§20): identity, version/family, Drive/upload
# metadata, relation fields, Status, and review fields are all
# immutable through this generic path — each has its own dedicated
# future/explicit operation instead (relink, new-version, transition,
# review API).
_DOCUMENT_IDENTITY_FIELDS = ("Document ID", "Business ID", "Created At")
_DOCUMENT_VERSION_FIELDS = ("Document Family ID", "Version")
_DOCUMENT_UPLOAD_METADATA_FIELDS = (
    "Uploaded At", "Uploaded By", "Drive File ID", "Drive File URL", "File Name", "Mime Type",
)
_DOCUMENT_RELATION_FIELDS = ("Client ID", "Object ID", "Roadmap ID", "Stage ID", "Document Template ID")
_DOCUMENT_REVIEW_FIELDS = ("Reviewed At", "Reviewed By", "Rejection Reason")


def update_document_admin_fields(document_id: str, updates: dict) -> dict:
    """
    Update one or more admin fields (Document Name/Notes only). Does
    not check cross-entity eligibility — business_builder.
    update_document_admin_fields() already did that before calling
    this function.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "code": str, "error": str | None}
    """
    if not document_id:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": "document_id не указан"}

    identity_conflict = [k for k in updates if k in _DOCUMENT_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "DOCUMENT_IMMUTABLE_FIELD_CONFLICT",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Document",
        }

    version_conflict = [k for k in updates if k in _DOCUMENT_VERSION_FIELDS]
    if version_conflict:
        code = "DOCUMENT_FAMILY_FIELD_IMMUTABLE" if "Document Family ID" in version_conflict else "DOCUMENT_VERSION_FIELD_IMMUTABLE"
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": code,
            "error": f"Поля {', '.join(version_conflict)} неизменяемы после создания",
        }

    relation_conflict = [k for k in updates if k in _DOCUMENT_RELATION_FIELDS]
    if relation_conflict:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION",
            "error": f"Поля {', '.join(relation_conflict)} требуют отдельного явного relink-действия (не реализовано)",
        }

    upload_conflict = [k for k in updates if k in _DOCUMENT_UPLOAD_METADATA_FIELDS]
    review_conflict = [k for k in updates if k in _DOCUMENT_REVIEW_FIELDS]
    if upload_conflict or review_conflict or "Status" in updates:
        blocked = upload_conflict + review_conflict + (["Status"] if "Status" in updates else [])
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "INVALID_DOCUMENT_ADMIN_FIELD",
            "error": f"Поля {', '.join(blocked)} недоступны через admin-обновление",
        }

    unknown = [k for k in updates if k not in _DOCUMENT_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "INVALID_DOCUMENT_ADMIN_FIELD",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_document_row(document_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "DOCUMENT_NOT_FOUND", "error": f"Document '{document_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime, timezone

        sheet = get_business_sheet("document_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        updated_fields = []
        changed = False
        for header, new_value in updates.items():
            if header not in idx:
                continue
            old_value = current.get(header, "")
            if str(old_value) == str(new_value):
                continue
            sheet.update_cell(row_num, idx[header] + 1, new_value)
            updated_fields.append(header)
            changed = True

        if changed and "Updated At" in idx:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            sheet.update_cell(row_num, idx["Updated At"] + 1, now)

        log.info(f"update_document_admin_fields: {document_id} fields={updated_fields}")
        return {
            "ok": True, "changed": changed, "updated_fields": tuple(updated_fields),
            "code": "DOCUMENT_ADMIN_FIELDS_UPDATED" if changed else "DOCUMENT_ADMIN_FIELDS_UNCHANGED",
            "error": None,
        }
    except Exception:
        log.error("update_document_admin_fields infrastructure failure")
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": "Infrastructure failure"}


# ─────────────────────────────────────────────────────────────
# Relation relink (Roadmap ID / Stage ID only)
# ─────────────────────────────────────────────────────────────

# Deliberately narrow: only the three relation fields business_builder.
# relink_document() is approved to change. Client ID/Object ID remain
# unreachable through ANY generic write path — a future explicit action
# for those (if ever approved) must be its own separate function, never
# an expansion of this allowlist, since Object ID relink carries the
# unresolved physical-Drive-folder-move risk flagged during the audit
# for this feature. Document Template ID was added here in a later
# audit pass — unlike Object ID, it is a pure classification field with
# no Drive-path implication, so it carries none of that risk.
_DOCUMENT_RELINK_EDITABLE_FIELDS = ("Roadmap ID", "Stage ID", "Document Template ID")


def update_document_relations(document_id: str, updates: dict) -> dict:
    """
    Update Roadmap ID and/or Stage ID and/or Document Template ID only.
    Does not itself validate that the new values form a consistent
    Stage->Roadmap->Object->Client->Business chain (or that Document
    Template ID exists/belongs to the right Business) —
    business_builder.relink_document() already did that (via the
    existing resolve_and_validate_links()) before calling this
    function. Business ID/Client ID/Object ID/Drive fields/identity/
    version fields are all rejected outright, regardless of value —
    this function's allowlist makes changing them structurally
    impossible, exactly like update_document_admin_fields() already
    does for Status/Drive/review fields.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "code": str, "error": str | None}
    """
    if not document_id:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": "document_id не указан"}

    unknown = [k for k in updates if k not in _DOCUMENT_RELINK_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "DOCUMENT_RELATION_FIELD_NOT_RELINKABLE",
            "error": f"Поля {', '.join(unknown)} нельзя изменить через relink — разрешены только Roadmap ID и Stage ID",
        }

    found = _find_document_row(document_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "DOCUMENT_NOT_FOUND", "error": f"Document '{document_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime, timezone

        sheet = get_business_sheet("document_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        updated_fields = []
        changed = False
        for header, new_value in updates.items():
            if header not in idx:
                continue
            old_value = current.get(header, "")
            if str(old_value) == str(new_value):
                continue
            sheet.update_cell(row_num, idx[header] + 1, new_value)
            updated_fields.append(header)
            changed = True

        if changed and "Updated At" in idx:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            sheet.update_cell(row_num, idx["Updated At"] + 1, now)

        log.info(f"update_document_relations: {document_id} fields={updated_fields}")
        return {
            "ok": True, "changed": changed, "updated_fields": tuple(updated_fields),
            "code": "DOCUMENT_RELATION_UPDATED" if changed else "DOCUMENT_RELATION_UNCHANGED",
            "error": None,
        }
    except Exception as exc:
        log.error(f"update_document_relations({document_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": str(exc)}


def update_document_status(document_id: str, status: str) -> dict:
    """
    Low-level Status write. Does not check the transition matrix or
    Roadmap/Stage eligibility — business_builder.
    transition_document_status() already did that.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not document_id:
        return {"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": "document_id не указан"}
    if status not in DOCUMENT_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_DOCUMENT_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(DOCUMENT_STATUS)}",
        }

    found = _find_document_row(document_id)
    if not found:
        return {"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": f"Document '{document_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime, timezone

        sheet = get_business_sheet("document_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        if changed and "Updated At" in idx:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            sheet.update_cell(row_num, idx["Updated At"] + 1, now)

        log.info(f"update_document_status: {document_id} -> {status}")
        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_document_status({document_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def archive_document_row(
    document_id: str,
    *,
    archived_at: str,
    archived_by: str,
    archive_reason: str,
    previous_status: str,
) -> dict:
    """
    Phase 16C.9C: low-level Archive row write. Does not validate the
    transition matrix, does not decide idempotency, does not read
    Drive/DOCUMENT_CONTENT/DOCUMENT_FIELD_REVIEWS — business_builder.
    archive_document() already did all of that before calling this.

    Writes exactly six fields in one update_business_row() call (one
    batch_update request) — never multiple update_cell calls, never a
    call to update_document_status():
        Status = "archived"
        Archived At = archived_at
        Archived By = archived_by
        Archive Reason = archive_reason
        Previous Status = previous_status
        Updated At = archived_at

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not document_id:
        return {"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": "document_id не указан"}

    found = _find_document_row(document_id)
    if not found:
        return {"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": f"Document '{document_id}' не найден"}
    row_num, _current = found

    try:
        from business_core.sheets import update_business_row

        update_business_row("document_registry", row_num, {
            "Status": "archived",
            "Archived At": archived_at,
            "Archived By": archived_by,
            "Archive Reason": archive_reason,
            "Previous Status": previous_status,
            "Updated At": archived_at,
        })
        log.info(f"archive_document_row: {document_id} -> archived")
        return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}
    except Exception as exc:
        log.error(f"archive_document_row({document_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "DOCUMENT_ARCHIVE_WRITE_FAILED", "error": None}
