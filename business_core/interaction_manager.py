"""
Interaction Manager — Interaction / Communication History Domain
persistence (Phase 42C, ADR-025).

Sole transactional owner of INTERACTION_LOG. Mirrors lead_manager.py's/
payment_manager.py's/offer_manager.py's role for their own domains
(ADR-022/ADR-023/ADR-024 precedent): targeted sheet reads via
sheets.find_row_by_id()/generate_next_id(), never a positional-index
assumption.

This module is deliberately low-level only: no cross-entity relation
validation, no primary-subject XOR policy, no Interaction Type/
Direction/Occurred At/content normalization, no idempotency-decision
policy beyond exact-match lookup helpers, no lifecycle policy, no
Person/Lead/Commercial Offer mutation, no Telegram UX, no Russian
user-facing text. All cross-domain policy lives solely in
business_builder.py's Interaction orchestration functions — this
module is the primitive those functions call after their own
validation passes, exactly like lead_manager.py is to
business_builder.create_lead().

Interaction is fully separate from RelationshipTouch/relationship_
capital (ADR-025 §1/§2): this module never imports relationship_
capital, never writes it, and never reuses TCH identity. It is also
fully separate from Person/Client/Lead/Commercial Offer persistence —
this module never reads or writes people_registry, leads, or
commercial_offers; subject/context references are validated
read-only by business_builder before this module is ever called.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


INTERACTION_STATUS = ("active", "archived")

_INTERACTION_FIELDS = [
    "Interaction ID", "Business ID", "Caller Idempotency Key",
    "Interaction Type", "Direction", "Channel ID", "Occurred At",
    "Summary", "Outcome",
    "Lead ID", "Client ID", "Commercial Offer ID", "Assigned Person ID",
    "External Reference", "Status",
    "Created At", "Created By", "Updated At", "Archived At", "Notes",
]

_ADMIN_EDITABLE_FIELDS = ("Notes",)
_IDENTITY_FIELDS = (
    "Interaction ID", "Business ID", "Caller Idempotency Key",
    "Interaction Type", "Direction", "Channel ID", "Occurred At",
    "Summary", "Outcome",
    "Lead ID", "Client ID", "Commercial Offer ID", "Assigned Person ID",
    "External Reference", "Created At", "Created By",
)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

def find_interaction_by_id(interaction_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only. Returns the row unconditionally,
    including archived Interactions (ADR-025 §22 — exact-ID read always
    works)."""
    if not interaction_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("interaction_log", interaction_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _INTERACTION_FIELDS}


def _list_interactions_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("interaction_log")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_interactions_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _INTERACTION_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_interactions(
    business_id: str = "", lead_id: str = "", client_id: str = "",
    commercial_offer_id: str = "", channel_id: str = "", assigned_person_id: str = "",
    interaction_type: str = "", direction: str = "", status: str = "",
    *, include_archived: bool = False,
) -> list[dict]:
    """Read-only, exact-match filters only. No fuzzy/substring matching,
    no arbitrary first-pick. Archived Interactions excluded by default
    (ADR-025 §20/§22) unless include_archived=True or status="archived"
    is explicitly requested."""
    rows = _list_interactions_raw()
    filters = {
        "Business ID": business_id, "Lead ID": lead_id, "Client ID": client_id,
        "Commercial Offer ID": commercial_offer_id, "Channel ID": channel_id,
        "Assigned Person ID": assigned_person_id, "Interaction Type": interaction_type,
        "Direction": direction, "Status": status,
    }
    for field, value in filters.items():
        if value:
            rows = [r for r in rows if r.get(field, "") == value]
    if not include_archived and status != "archived":
        rows = [r for r in rows if r.get("Status", "") != "archived"]
    return rows


def find_interactions_by_idempotency_key(business_id: str, caller_idempotency_key: str) -> list[dict]:
    """Primary Interaction idempotency lookup (ADR-025 §17): exact
    Business ID + Caller Idempotency Key match. Never fuzzy, never
    first-pick — the caller (business_builder) decides zero/one/
    multiple policy from this full list."""
    if not business_id or not caller_idempotency_key:
        return []
    rows = _list_interactions_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Caller Idempotency Key"] == caller_idempotency_key
    ]


# ─────────────────────────────────────────────────────────────
# ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_interaction_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("interaction_log")


# ─────────────────────────────────────────────────────────────
# Low-level creation
# ─────────────────────────────────────────────────────────────

def create_interaction(
    business_id: str, interaction_type: str, occurred_at: str, summary: str,
    *, caller_idempotency_key: str = "", direction: str = "", channel_id: str = "",
    outcome: str = "", lead_id: str = "", client_id: str = "",
    commercial_offer_id: str = "", assigned_person_id: str = "",
    external_reference: str = "", created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Business/Lead/Client/Offer/
    Channel/Assigned Person existence, does not validate the primary-
    subject XOR rule, does not normalize Interaction Type/Direction/
    Occurred At/content, does not check idempotency. All of that is
    business_builder.create_interaction()'s job. Calling this directly
    bypasses that policy by design.

    Defaults (ADR-025 §17): Status=active, Archived At blank,
    Created/Updated At set.

    Returns:
        {"ok": bool, "interaction_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "interaction_id": "", "code": "", "error": "business_id обязателен"}
    if not interaction_type:
        return {"ok": False, "interaction_id": "", "code": "", "error": "interaction_type обязателен"}
    if not occurred_at:
        return {"ok": False, "interaction_id": "", "code": "", "error": "occurred_at обязателен"}
    if not summary:
        return {"ok": False, "interaction_id": "", "code": "", "error": "summary обязателен"}

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        interaction_id = generate_next_interaction_id()
        now = _now_utc_str()
        values = {
            "Interaction ID": interaction_id, "Business ID": business_id,
            "Caller Idempotency Key": caller_idempotency_key,
            "Interaction Type": interaction_type, "Direction": direction,
            "Channel ID": channel_id, "Occurred At": occurred_at,
            "Summary": summary, "Outcome": outcome,
            "Lead ID": lead_id, "Client ID": client_id,
            "Commercial Offer ID": commercial_offer_id, "Assigned Person ID": assigned_person_id,
            "External Reference": external_reference, "Status": "active",
            "Created At": now, "Created By": created_by, "Updated At": now,
            "Archived At": "", "Notes": notes,
        }
        row = row_from_header_map(_INTERACTION_FIELDS, values)
        append_business_row("interaction_log", row)
        log.info(f"create_interaction: {interaction_id}")
        return {"ok": True, "interaction_id": interaction_id, "code": "INTERACTION_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_interaction error: {exc}")
        return {"ok": False, "interaction_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Low-level updates
# ─────────────────────────────────────────────────────────────

def _find_interaction_row(interaction_id: str) -> Optional[tuple[int, dict]]:
    if not interaction_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("interaction_log", interaction_id)
    except Exception:
        # Phase 17E-2A3-H1: fixed literal only — no exception
        # interpolation, no entity ID, no row content. The underlying
        # exception (e.g. a Sheets API error) could theoretically echo
        # request payload content, so nothing about it is logged.
        log.warning("_find_interaction_row infrastructure failure")
        return None


def update_interaction_admin_fields(interaction_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable, in every status — Notes is not
    an immutable Interaction fact (ADR-025 §21/§23) and is never
    logged."""
    if not interaction_id:
        return {"ok": False, "changed": False, "code": "INTERACTION_NOT_FOUND", "error": "interaction_id не указан"}

    identity_conflict = [k for k in updates if k in _IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "INTERACTION_IMMUTABLE",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемыми фактами Interaction",
        }
    if "Status" in updates:
        return {"ok": False, "changed": False, "code": "INTERACTION_IMMUTABLE", "error": "Status изменяется только через архивирование"}

    unknown = [k for k in updates if k not in _ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {"ok": False, "changed": False, "code": "INTERACTION_IMMUTABLE", "error": f"Недопустимые поля для обновления: {', '.join(unknown)}"}

    found = _find_interaction_row(interaction_id)
    if not found:
        return {"ok": False, "changed": False, "code": "INTERACTION_NOT_FOUND", "error": f"Interaction '{interaction_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("interaction_log")
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

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception:
        # Phase 17E-2A3-H1: fixed literal only — no exception
        # interpolation, no entity ID, no updates dict, no row
        # content. "error" is likewise sanitized to a fixed safe
        # string, since callers (including business_builder.
        # update_interaction_notes' code-synthesis fallback) may
        # place this value where a Telegram mapper renders it.
        log.error("update_interaction_admin_fields infrastructure failure")
        return {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}


def update_interaction_status(interaction_id: str, status: str, *, archived_at: str = "") -> dict:
    """
    Low-level Status (+ archive metadata) write. Does not check the
    transition matrix — business_builder.archive_interaction() already
    validated that. Never touches any Interaction fact (Interaction
    Type/Direction/Channel ID/Occurred At/Summary/Outcome/Lead ID/
    Client ID/Commercial Offer ID/Assigned Person ID/External
    Reference) — this function's parameter set makes that structurally
    impossible, which is the immutability guarantee (ADR-025 §20/§23).

    Archived At is write-once: once set, this function never overwrites
    it again.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not interaction_id:
        return {"ok": False, "changed": False, "code": "INTERACTION_NOT_FOUND", "error": "interaction_id не указан"}
    if status not in INTERACTION_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_INTERACTION_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(INTERACTION_STATUS)}",
        }

    found = _find_interaction_row(interaction_id)
    if not found:
        return {"ok": False, "changed": False, "code": "INTERACTION_NOT_FOUND", "error": f"Interaction '{interaction_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("interaction_log")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        if archived_at and not current.get("Archived At", ""):
            sheet.update_cell(row_num, idx["Archived At"] + 1, archived_at)
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_interaction_status({interaction_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}
