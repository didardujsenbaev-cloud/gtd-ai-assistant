"""
Checklist Manager — Operational Checklist persistence (Phase 38C, ADR-021).

Sole transactional owner of CHECKLIST_INSTANCES and
CHECKLIST_INSTANCE_ITEMS. Mirrors task_manager.py's role for
TASK_REGISTRY/TASK_ASSIGNMENTS and document_manager.py's role for
DOCUMENT_REGISTRY (ADR-019/ADR-020 precedent) — targeted sheet reads
via sheets.find_row_by_id()/generate_next_id()/generate_next_ids(),
never a positional-index assumption.

This module is deliberately low-level only: no Template parsing, no
cross-entity relation validation, no idempotency-tuple policy beyond
the exact-match lookup helper below, no Task/Document mutation, no
Stage mutation, no Telegram UX, no Russian user-facing text in log
calls. All cross-domain policy lives solely in business_builder.py's
Checklist orchestration functions (instantiate_checklist/
transition_checklist_status/transition_checklist_item_status/
update_checklist_admin_fields) — this module is the primitive those
functions call after their own validation passes, exactly like
document_manager.py is to business_builder.register_document().

CHECKLIST_REGISTRY (the Phase 8C Template layer) is never read or
written here — that remains business_core.knowledge_manager.py's sole
responsibility (ADR-021 §2). This module owns only the two Phase 38C
operational registries.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


CHECKLIST_INSTANCE_STATUS = ("draft", "in_progress", "blocked", "completed", "cancelled", "archived")
CHECKLIST_ITEM_STATUS = ("pending", "in_progress", "blocked", "done", "skipped", "not_applicable")

_INSTANCE_FIELDS = [
    "Checklist Instance ID", "Business ID", "Checklist Template ID",
    "Checklist Title Snapshot", "Service ID", "Object ID",
    "Roadmap ID", "Stage ID", "Status",
    "Total Items", "Required Items", "Completed Items", "Required Remaining",
    "Created At", "Created By", "Started At", "Completed At", "Cancelled At",
    "Updated At", "Notes",
]

_ITEM_FIELDS = [
    "Checklist Instance Item ID", "Checklist Instance ID", "Checklist Template ID",
    "Source Item Key", "Item Order", "Item Title Snapshot", "Item Description Snapshot",
    "Required", "Status", "Blocked Reason", "Skip Reason",
    "Task ID", "Document ID", "SOP ID",
    "Completed At", "Completed By", "Created At", "Updated At", "Notes",
]

_INSTANCE_ADMIN_EDITABLE_FIELDS = ("Notes",)
_INSTANCE_IDENTITY_FIELDS = (
    "Checklist Instance ID", "Business ID", "Checklist Template ID",
    "Checklist Title Snapshot", "Service ID", "Object ID",
    "Roadmap ID", "Stage ID", "Created At",
)

_ITEM_ADMIN_EDITABLE_FIELDS = ("Notes",)
_ITEM_IDENTITY_FIELDS = (
    "Checklist Instance Item ID", "Checklist Instance ID", "Checklist Template ID",
    "Source Item Key", "Item Order", "Item Title Snapshot", "Item Description Snapshot",
    "Required", "Created At",
)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

def find_checklist_instance_by_id(instance_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not instance_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("checklist_instances", instance_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _INSTANCE_FIELDS}


def find_checklist_instance_item_by_id(item_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not item_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("checklist_instance_items", item_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _ITEM_FIELDS}


def _list_instances_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("checklist_instances")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_instances_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _INSTANCE_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def _list_items_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("checklist_instance_items")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_items_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _ITEM_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_checklist_instances(business_id: str = "", status: str = "") -> list[dict]:
    """Read-only, simple filter. No business policy hidden here."""
    rows = _list_instances_raw()
    if business_id:
        rows = [r for r in rows if r["Business ID"] == business_id]
    if status:
        rows = [r for r in rows if r["Status"] == status]
    return rows


def list_checklist_instance_items(instance_id: str = "", status: str = "") -> list[dict]:
    """Read-only, simple filter. No business policy hidden here."""
    rows = _list_items_raw()
    if instance_id:
        rows = [r for r in rows if r["Checklist Instance ID"] == instance_id]
    if status:
        rows = [r for r in rows if r["Status"] == status]
    return rows


def find_instances_by_idempotency_key(
    business_id: str, template_id: str, roadmap_id: str = "", stage_id: str = "",
) -> list[dict]:
    """
    Exact-match idempotency lookup: Business ID + Checklist Template ID
    + Roadmap ID + Stage ID (empty optional values normalized to "" and
    compared as given). Never fuzzy, never first-pick — the caller
    (business_builder.instantiate_checklist) decides zero/one/multiple
    policy from this full list.
    """
    if not business_id or not template_id:
        return []
    rows = _list_instances_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Checklist Template ID"] == template_id
        and r["Roadmap ID"] == (roadmap_id or "")
        and r["Stage ID"] == (stage_id or "")
    ]


# ─────────────────────────────────────────────────────────────
# ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_instance_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("checklist_instances")


def generate_next_item_ids(count: int) -> list[str]:
    from business_core.sheets import generate_next_ids
    return generate_next_ids("checklist_instance_items", count)


# ─────────────────────────────────────────────────────────────
# Low-level creation
# ─────────────────────────────────────────────────────────────

def create_checklist_instance(
    business_id: str, checklist_template_id: str, title_snapshot: str,
    *, service_id: str = "", object_id: str = "", roadmap_id: str = "", stage_id: str = "",
    status: str = "draft", total_items: int = 0, required_items: int = 0,
    completed_items: int = 0, required_remaining: int = 0,
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Business/Template/relation
    existence, does not parse Template items, does not check
    idempotency. All of that is business_builder.instantiate_checklist()'s
    job. Calling this directly bypasses that policy by design.

    Returns:
        {"ok": bool, "checklist_instance_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "checklist_instance_id": "", "code": "", "error": "business_id обязателен"}
    if not checklist_template_id:
        return {"ok": False, "checklist_instance_id": "", "code": "", "error": "checklist_template_id обязателен"}
    if status not in CHECKLIST_INSTANCE_STATUS:
        return {
            "ok": False, "checklist_instance_id": "", "code": "INVALID_CHECKLIST_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(CHECKLIST_INSTANCE_STATUS)}",
        }

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        instance_id = generate_next_instance_id()
        now = _now_utc_str()
        values = {
            "Checklist Instance ID": instance_id, "Business ID": business_id,
            "Checklist Template ID": checklist_template_id,
            "Checklist Title Snapshot": title_snapshot, "Service ID": service_id,
            "Object ID": object_id, "Roadmap ID": roadmap_id, "Stage ID": stage_id,
            "Status": status,
            "Total Items": str(total_items), "Required Items": str(required_items),
            "Completed Items": str(completed_items), "Required Remaining": str(required_remaining),
            "Created At": now, "Created By": created_by,
            "Started At": "", "Completed At": "", "Cancelled At": "",
            "Updated At": now, "Notes": notes,
        }
        row = row_from_header_map(_INSTANCE_FIELDS, values)
        append_business_row("checklist_instances", row)
        log.info(f"create_checklist_instance: {instance_id}")
        return {"ok": True, "checklist_instance_id": instance_id, "code": "CHECKLIST_INSTANCE_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_checklist_instance error: {exc}")
        return {"ok": False, "checklist_instance_id": "", "code": "", "error": str(exc)}


def create_checklist_instance_items(checklist_instance_id: str, checklist_template_id: str, items: list[dict]) -> dict:
    """
    Batch-create Instance Item rows for one Instance — one sheet read
    (via generate_next_ids) + one batch write, so no two items in the
    same call can ever collide on ID.

    Each entry in `items` must supply: source_item_key, item_order,
    item_title_snapshot, item_description_snapshot, required (bool).

    Returns:
        {"ok": bool, "item_ids": list[str], "code": str, "error": str | None}
    """
    if not checklist_instance_id:
        return {"ok": False, "item_ids": [], "code": "", "error": "checklist_instance_id обязателен"}
    if not items:
        return {"ok": False, "item_ids": [], "code": "CHECKLIST_TEMPLATE_ITEMS_EMPTY", "error": "Список пунктов пуст"}

    try:
        from business_core.sheets import batch_append_business_rows, row_from_header_map

        item_ids = generate_next_item_ids(len(items))
        now = _now_utc_str()
        rows = []
        for item_id, item in zip(item_ids, items):
            values = {
                "Checklist Instance Item ID": item_id,
                "Checklist Instance ID": checklist_instance_id,
                "Checklist Template ID": checklist_template_id,
                "Source Item Key": str(item.get("source_item_key", "")),
                "Item Order": str(item.get("item_order", "")),
                "Item Title Snapshot": item.get("item_title_snapshot", ""),
                "Item Description Snapshot": item.get("item_description_snapshot", ""),
                "Required": "true" if item.get("required", True) else "false",
                "Status": "pending",
                "Blocked Reason": "", "Skip Reason": "",
                "Task ID": "", "Document ID": "", "SOP ID": "",
                "Completed At": "", "Completed By": "",
                "Created At": now, "Updated At": now, "Notes": "",
            }
            rows.append(row_from_header_map(_ITEM_FIELDS, values))

        batch_append_business_rows("checklist_instance_items", rows)
        log.info(f"create_checklist_instance_items: instance={checklist_instance_id} count={len(item_ids)}")
        return {"ok": True, "item_ids": item_ids, "code": "", "error": None}
    except Exception as exc:
        log.error(f"create_checklist_instance_items error: {exc}")
        return {"ok": False, "item_ids": [], "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Low-level updates
# ─────────────────────────────────────────────────────────────

def _find_instance_row(instance_id: str) -> Optional[tuple[int, dict]]:
    if not instance_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("checklist_instances", instance_id)
    except Exception as exc:
        log.warning(f"_find_instance_row({instance_id}) error: {exc}")
        return None


def _find_item_row(item_id: str) -> Optional[tuple[int, dict]]:
    if not item_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("checklist_instance_items", item_id)
    except Exception as exc:
        log.warning(f"_find_item_row({item_id}) error: {exc}")
        return None


def update_checklist_instance_admin_fields(instance_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable. Does not check cross-entity
    eligibility — business_builder already did that."""
    if not instance_id:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": "checklist_instance_id не указан"}

    identity_conflict = [k for k in updates if k in _INSTANCE_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "CHECKLIST_IMMUTABLE_FIELD_CONFLICT",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Checklist Instance",
        }

    if "Status" in updates:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_ADMIN_FIELD",
            "error": "Status изменяется только через transition API",
        }

    unknown = [k for k in updates if k not in _INSTANCE_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_ADMIN_FIELD",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_instance_row(instance_id)
    if not found:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": f"Checklist Instance '{instance_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("checklist_instances")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        for header, new_value in updates.items():
            if header not in idx:
                continue
            if str(current.get(header, "")) == str(new_value):
                continue
            sheet.update_cell(row_num, idx[header] + 1, new_value)
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {
            "ok": True, "changed": changed,
            "code": "CHECKLIST_ADMIN_FIELDS_UPDATED" if changed else "CHECKLIST_ADMIN_FIELDS_UNCHANGED",
            "error": None,
        }
    except Exception as exc:
        log.error(f"update_checklist_instance_admin_fields({instance_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_checklist_instance_status(
    instance_id: str, status: str, *,
    started_at: str = "", completed_at: str = "", cancelled_at: str = "",
) -> dict:
    """
    Low-level Status + lifecycle-timestamp write. Does not check the
    transition matrix or completion policy — business_builder.
    transition_checklist_status() already did that. Timestamps are
    written only when explicitly supplied (business_builder decides
    which one applies for a given transition).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not instance_id:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": "checklist_instance_id не указан"}
    if status not in CHECKLIST_INSTANCE_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(CHECKLIST_INSTANCE_STATUS)}",
        }

    found = _find_instance_row(instance_id)
    if not found:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": f"Checklist Instance '{instance_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("checklist_instances")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        for field, value in (
            ("Started At", started_at), ("Completed At", completed_at), ("Cancelled At", cancelled_at),
        ):
            if value and not current.get(field, ""):
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_checklist_instance_status({instance_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_checklist_instance_progress(
    instance_id: str, *, total_items: int, required_items: int,
    completed_items: int, required_remaining: int,
) -> dict:
    """Persist the verified progress cache. Canonical truth remains
    Instance Item statuses — this is a cache write only, always called
    by business_builder after recomputation, never the source of truth
    itself."""
    if not instance_id:
        return {"ok": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": "checklist_instance_id не указан"}

    found = _find_instance_row(instance_id)
    if not found:
        return {"ok": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": f"Checklist Instance '{instance_id}' не найден"}
    row_num, _ = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("checklist_instances")
        idx = get_header_index_map(sheet.row_values(1))

        sheet.update_cell(row_num, idx["Total Items"] + 1, str(total_items))
        sheet.update_cell(row_num, idx["Required Items"] + 1, str(required_items))
        sheet.update_cell(row_num, idx["Completed Items"] + 1, str(completed_items))
        sheet.update_cell(row_num, idx["Required Remaining"] + 1, str(required_remaining))
        sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_checklist_instance_progress({instance_id}) error: {exc}")
        return {"ok": False, "code": "", "error": str(exc)}


def update_checklist_instance_item_admin_fields(item_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable."""
    if not item_id:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_ITEM_NOT_FOUND", "error": "checklist_instance_item_id не указан"}

    identity_conflict = [k for k in updates if k in _ITEM_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "CHECKLIST_ITEM_IMMUTABLE_FIELD_CONFLICT",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Checklist Instance Item",
        }

    if "Status" in updates:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_ADMIN_FIELD",
            "error": "Status изменяется только через transition API",
        }

    unknown = [k for k in updates if k not in _ITEM_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_ADMIN_FIELD",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_item_row(item_id)
    if not found:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_ITEM_NOT_FOUND", "error": f"Checklist Instance Item '{item_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("checklist_instance_items")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        for header, new_value in updates.items():
            if header not in idx:
                continue
            if str(current.get(header, "")) == str(new_value):
                continue
            sheet.update_cell(row_num, idx[header] + 1, new_value)
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {
            "ok": True, "changed": changed,
            "code": "CHECKLIST_ADMIN_FIELDS_UPDATED" if changed else "CHECKLIST_ADMIN_FIELDS_UNCHANGED",
            "error": None,
        }
    except Exception as exc:
        log.error(f"update_checklist_instance_item_admin_fields({item_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_checklist_instance_item_status(
    item_id: str, status: str, *,
    blocked_reason: str = "", skip_reason: str = "",
    completed_at: str = "", completed_by: str = "",
) -> dict:
    """
    Low-level Item Status (+ reason/completion metadata) write. Does
    not check the transition matrix, reason-required policy, or
    completion-metadata-required policy — business_builder.
    transition_checklist_item_status() already validated all of that.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not item_id:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_ITEM_NOT_FOUND", "error": "checklist_instance_item_id не указан"}
    if status not in CHECKLIST_ITEM_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_CHECKLIST_ITEM_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(CHECKLIST_ITEM_STATUS)}",
        }

    found = _find_item_row(item_id)
    if not found:
        return {"ok": False, "changed": False, "code": "CHECKLIST_INSTANCE_ITEM_NOT_FOUND", "error": f"Checklist Instance Item '{item_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("checklist_instance_items")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        for field, value in (
            ("Blocked Reason", blocked_reason), ("Skip Reason", skip_reason),
        ):
            if current.get(field, "") != value:
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if completed_at and not current.get("Completed At", ""):
            sheet.update_cell(row_num, idx["Completed At"] + 1, completed_at)
            changed = True
        if completed_by and not current.get("Completed By", ""):
            sheet.update_cell(row_num, idx["Completed By"] + 1, completed_by)
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_checklist_instance_item_status({item_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}
