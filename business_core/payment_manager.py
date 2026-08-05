"""
Payment Manager — Payment/Milestone Domain persistence (Phase 39C, ADR-022).

Sole transactional owner of COMMERCIAL_MILESTONE_TEMPLATES,
PAYMENT_OBLIGATIONS, and PAYMENT_TRANSACTIONS. One manager owns all
three registries (ADR-022 §3 — deliberately not split into a separate
template-manager module, to avoid day-1 fragmentation) — mirrors
checklist_manager.py's role for CHECKLIST_INSTANCES/
CHECKLIST_INSTANCE_ITEMS and document_manager.py's role for
DOCUMENT_REGISTRY: targeted sheet reads via sheets.find_row_by_id()/
generate_next_id()/generate_next_ids(), never a positional-index
assumption.

This module is deliberately low-level only: no cross-entity relation
validation, no amount/currency business normalization, no idempotency-
decision policy beyond exact-match lookup helpers, no overpayment
policy, no balance-derivation arithmetic, no Roadmap/Stage/Document/
Checklist/Task mutation, no Telegram UX, no Russian user-facing text.
All cross-domain policy lives solely in business_builder.py's Payment
orchestration functions — this module is the primitive those functions
call after their own validation passes, exactly like checklist_manager.py
is to business_builder.instantiate_checklist().

COMMERCIAL_MILESTONES_MAP (business_core.roadmap_manager, the Phase-9-era
hardcoded config) is never read or written here and is entirely
untouched by this module (ADR-022 §24) — this is a wholly new,
unrelated persistence layer.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


TEMPLATE_STATUS = ("active", "inactive", "archived")
OBLIGATION_STATUS = ("draft", "issued", "partially_paid", "paid", "cancelled", "archived")
TRANSACTION_STATUS = ("pending", "confirmed", "reversed", "failed")
CALCULATION_TYPES = ("fixed", "percentage")

_TEMPLATE_FIELDS = [
    "Commercial Milestone Template ID", "Roadmap Template ID", "Service ID",
    "Title", "Description", "Sequence", "Trigger Description",
    "Calculation Type", "Fixed Amount", "Percentage", "Currency", "Status",
    "Created At", "Created By", "Updated At", "Notes",
]

_OBLIGATION_FIELDS = [
    "Payment Obligation ID", "Business ID", "Client ID", "Object ID", "Service ID",
    "Roadmap ID", "Stage ID", "Commercial Milestone Template ID",
    "Caller Idempotency Key", "Title Snapshot", "Description Snapshot",
    "Obligation Amount", "Currency", "Due Date", "Status",
    "Paid Amount", "Remaining Amount",
    "Created At", "Created By", "Issued At", "Paid At", "Cancelled At",
    "Updated At", "Notes",
]

_TRANSACTION_FIELDS = [
    "Payment Transaction ID", "Business ID", "Payment Obligation ID", "Client ID",
    "Amount", "Currency", "Payment Date", "Payment Method",
    "External Transaction ID", "Caller Idempotency Key", "Evidence Document ID",
    "Status", "Reversal Reason",
    "Confirmed At", "Confirmed By", "Reversed At", "Reversed By",
    "Created At", "Created By", "Updated At", "Notes",
]

_TEMPLATE_ADMIN_EDITABLE_FIELDS = ("Description", "Trigger Description", "Notes")
_TEMPLATE_IDENTITY_FIELDS = (
    "Commercial Milestone Template ID", "Roadmap Template ID", "Service ID",
    "Title", "Sequence", "Calculation Type", "Fixed Amount", "Percentage",
    "Currency", "Created At", "Created By",
)

_OBLIGATION_ADMIN_EDITABLE_FIELDS = ("Notes",)
_OBLIGATION_IDENTITY_FIELDS = (
    "Payment Obligation ID", "Business ID", "Client ID", "Object ID", "Service ID",
    "Roadmap ID", "Stage ID", "Commercial Milestone Template ID",
    "Caller Idempotency Key", "Title Snapshot", "Description Snapshot",
    "Obligation Amount", "Currency", "Due Date", "Created At", "Created By",
)

_TRANSACTION_ADMIN_EDITABLE_FIELDS = ("Notes",)
_TRANSACTION_IDENTITY_FIELDS = (
    "Payment Transaction ID", "Business ID", "Payment Obligation ID", "Client ID",
    "Amount", "Currency", "Payment Date", "Payment Method",
    "External Transaction ID", "Caller Idempotency Key", "Evidence Document ID",
    "Created At", "Created By",
)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template — reads
# ─────────────────────────────────────────────────────────────

def find_commercial_milestone_template_by_id(template_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not template_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("commercial_milestone_templates", template_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _TEMPLATE_FIELDS}


def _list_templates_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("commercial_milestone_templates")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_templates_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _TEMPLATE_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_commercial_milestone_templates(roadmap_template_id: str = "", service_id: str = "", status: str = "") -> list[dict]:
    """Read-only, simple filter. No business policy hidden here."""
    rows = _list_templates_raw()
    if roadmap_template_id:
        rows = [r for r in rows if r["Roadmap Template ID"] == roadmap_template_id]
    if service_id:
        rows = [r for r in rows if r["Service ID"] == service_id]
    if status:
        rows = [r for r in rows if r["Status"] == status]
    return rows


def find_templates_by_identity(roadmap_template_id: str, service_id: str, sequence: str, title: str) -> list[dict]:
    """
    Exact-match idempotency lookup: Roadmap Template ID + Service ID +
    Sequence + Title (empty optional values normalized to "" and
    compared as given). Never fuzzy, never first-pick — the caller
    (business_builder) decides zero/one/multiple policy from this full
    list. ADR-022 did not approve a caller-idempotency field for
    Templates (§10 in Phase 39C brief), so this exact normalized tuple
    is the sole mechanism.
    """
    rows = _list_templates_raw()
    return [
        r for r in rows
        if r["Roadmap Template ID"] == (roadmap_template_id or "")
        and r["Service ID"] == (service_id or "")
        and r["Sequence"] == str(sequence or "")
        and r["Title"] == (title or "")
    ]


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template — ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_template_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("commercial_milestone_templates")


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template — low-level creation
# ─────────────────────────────────────────────────────────────

def create_commercial_milestone_template(
    title: str, calculation_type: str,
    *, roadmap_template_id: str = "", service_id: str = "", description: str = "",
    sequence: int = 1, trigger_description: str = "",
    fixed_amount: str = "", percentage: str = "", currency: str = "",
    status: str = "active", created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Roadmap Template/Service
    existence, does not check calculation-type field consistency, does
    not check idempotency. All of that is business_builder's job.
    Calling this directly bypasses that policy by design.

    Returns:
        {"ok": bool, "commercial_milestone_template_id": str, "code": str, "error": str | None}
    """
    if not title:
        return {"ok": False, "commercial_milestone_template_id": "", "code": "", "error": "title обязателен"}
    if calculation_type not in CALCULATION_TYPES:
        return {
            "ok": False, "commercial_milestone_template_id": "", "code": "INVALID_MILESTONE_CALCULATION_TYPE",
            "error": f"Недопустимый Calculation Type '{calculation_type}'. Допустимые значения: {', '.join(CALCULATION_TYPES)}",
        }
    if status not in TEMPLATE_STATUS:
        return {
            "ok": False, "commercial_milestone_template_id": "", "code": "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TEMPLATE_STATUS)}",
        }

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        template_id = generate_next_template_id()
        now = _now_utc_str()
        values = {
            "Commercial Milestone Template ID": template_id,
            "Roadmap Template ID": roadmap_template_id, "Service ID": service_id,
            "Title": title, "Description": description, "Sequence": str(sequence),
            "Trigger Description": trigger_description,
            "Calculation Type": calculation_type,
            "Fixed Amount": fixed_amount, "Percentage": percentage, "Currency": currency,
            "Status": status, "Created At": now, "Created By": created_by,
            "Updated At": now, "Notes": notes,
        }
        row = row_from_header_map(_TEMPLATE_FIELDS, values)
        append_business_row("commercial_milestone_templates", row)
        log.info(f"create_commercial_milestone_template: {template_id}")
        return {"ok": True, "commercial_milestone_template_id": template_id, "code": "COMMERCIAL_MILESTONE_TEMPLATE_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_commercial_milestone_template error: {exc}")
        return {"ok": False, "commercial_milestone_template_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template — low-level updates
# ─────────────────────────────────────────────────────────────

def _find_template_row(template_id: str) -> Optional[tuple[int, dict]]:
    if not template_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("commercial_milestone_templates", template_id)
    except Exception as exc:
        log.warning(f"_find_template_row({template_id}) error: {exc}")
        return None


def update_commercial_milestone_template_admin_fields(template_id: str, updates: dict) -> dict:
    """Only Description/Trigger Description/Notes are ordinarily
    mutable — identity/context/calculation fields are immutable after
    creation in Foundation (ADR-022 §25 preference)."""
    if not template_id:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": "template_id не указан"}

    identity_conflict = [k for k in updates if k in _TEMPLATE_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_IMMUTABLE",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Commercial Milestone Template",
        }

    if "Status" in updates:
        return {
            "ok": False, "changed": False, "code": "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS",
            "error": "Status изменяется только через transition API",
        }

    unknown = [k for k in updates if k not in _TEMPLATE_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "code": "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_template_row(template_id)
    if not found:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": f"Commercial Milestone Template '{template_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("commercial_milestone_templates")
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
    except Exception as exc:
        log.error(f"update_commercial_milestone_template_admin_fields({template_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_commercial_milestone_template_status(template_id: str, status: str) -> dict:
    """Low-level Status write. Does not check the transition matrix —
    business_builder already did that.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not template_id:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": "template_id не указан"}
    if status not in TEMPLATE_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TEMPLATE_STATUS)}",
        }

    found = _find_template_row(template_id)
    if not found:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": f"Commercial Milestone Template '{template_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("commercial_milestone_templates")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True
        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_commercial_milestone_template_status({template_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Payment Obligation — reads
# ─────────────────────────────────────────────────────────────

def find_payment_obligation_by_id(obligation_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not obligation_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("payment_obligations", obligation_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _OBLIGATION_FIELDS}


def _list_obligations_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("payment_obligations")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_obligations_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _OBLIGATION_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_payment_obligations(business_id: str = "", status: str = "") -> list[dict]:
    """Read-only, simple filter. No business policy hidden here."""
    rows = _list_obligations_raw()
    if business_id:
        rows = [r for r in rows if r["Business ID"] == business_id]
    if status:
        rows = [r for r in rows if r["Status"] == status]
    return rows


def find_obligations_by_caller_key(business_id: str, caller_idempotency_key: str) -> list[dict]:
    """Primary Obligation idempotency lookup (ADR-022 §16/§19): exact
    Business ID + Caller Idempotency Key match. Never fuzzy, never
    first-pick."""
    if not business_id or not caller_idempotency_key:
        return []
    rows = _list_obligations_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Caller Idempotency Key"] == caller_idempotency_key
    ]


def find_obligations_by_template_fallback_key(
    business_id: str, template_id: str, roadmap_id: str = "", stage_id: str = "",
) -> list[dict]:
    """Fallback Obligation idempotency lookup, used only for explicit
    Template-derived creation without a caller key (ADR-022 §16): exact
    Business ID + Commercial Milestone Template ID + Roadmap ID + Stage
    ID match."""
    if not business_id or not template_id:
        return []
    rows = _list_obligations_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Commercial Milestone Template ID"] == template_id
        and r["Roadmap ID"] == (roadmap_id or "")
        and r["Stage ID"] == (stage_id or "")
    ]


# ─────────────────────────────────────────────────────────────
# Payment Obligation — ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_obligation_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("payment_obligations")


# ─────────────────────────────────────────────────────────────
# Payment Obligation — low-level creation
# ─────────────────────────────────────────────────────────────

def create_payment_obligation(
    business_id: str, client_id: str, obligation_amount: str, currency: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "", stage_id: str = "",
    commercial_milestone_template_id: str = "", caller_idempotency_key: str = "",
    title_snapshot: str = "", description_snapshot: str = "", due_date: str = "",
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Business/Client/relation
    existence, does not normalize amount/currency, does not check
    idempotency. All of that is business_builder.create_payment_
    obligation()'s job. Calling this directly bypasses that policy by
    design.

    Defaults (ADR-022 §11 preferred): Status=draft, Paid Amount="0.00",
    Remaining Amount=obligation_amount, Issued/Paid/Cancelled At blank.

    Returns:
        {"ok": bool, "payment_obligation_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "payment_obligation_id": "", "code": "", "error": "business_id обязателен"}
    if not client_id:
        return {"ok": False, "payment_obligation_id": "", "code": "", "error": "client_id обязателен"}
    if not obligation_amount:
        return {"ok": False, "payment_obligation_id": "", "code": "", "error": "obligation_amount обязателен"}
    if not currency:
        return {"ok": False, "payment_obligation_id": "", "code": "", "error": "currency обязателен"}

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        obligation_id = generate_next_obligation_id()
        now = _now_utc_str()
        values = {
            "Payment Obligation ID": obligation_id, "Business ID": business_id, "Client ID": client_id,
            "Object ID": object_id, "Service ID": service_id, "Roadmap ID": roadmap_id, "Stage ID": stage_id,
            "Commercial Milestone Template ID": commercial_milestone_template_id,
            "Caller Idempotency Key": caller_idempotency_key,
            "Title Snapshot": title_snapshot, "Description Snapshot": description_snapshot,
            "Obligation Amount": obligation_amount, "Currency": currency, "Due Date": due_date,
            "Status": "draft", "Paid Amount": "0.00", "Remaining Amount": obligation_amount,
            "Created At": now, "Created By": created_by,
            "Issued At": "", "Paid At": "", "Cancelled At": "",
            "Updated At": now, "Notes": notes,
        }
        row = row_from_header_map(_OBLIGATION_FIELDS, values)
        append_business_row("payment_obligations", row)
        log.info(f"create_payment_obligation: {obligation_id}")
        return {"ok": True, "payment_obligation_id": obligation_id, "code": "PAYMENT_OBLIGATION_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_payment_obligation error: {exc}")
        return {"ok": False, "payment_obligation_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Payment Obligation — low-level updates
# ─────────────────────────────────────────────────────────────

def _find_obligation_row(obligation_id: str) -> Optional[tuple[int, dict]]:
    if not obligation_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("payment_obligations", obligation_id)
    except Exception:
        # Phase 17E-2A3-H1: fixed literal only — no exception
        # interpolation, no entity ID, no row content.
        log.warning("_find_obligation_row infrastructure failure")
        return None


def update_payment_obligation_admin_fields(obligation_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable."""
    if not obligation_id:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "obligation_id не указан"}

    identity_conflict = [k for k in updates if k in _OBLIGATION_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_RELATION_MISMATCH",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Payment Obligation",
        }

    if "Status" in updates or "Paid Amount" in updates or "Remaining Amount" in updates:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_OBLIGATION_STATUS",
            "error": "Status/Paid Amount/Remaining Amount изменяются только через transition/balance API",
        }

    unknown = [k for k in updates if k not in _OBLIGATION_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_OBLIGATION_STATUS",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_obligation_row(obligation_id)
    if not found:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": f"Payment Obligation '{obligation_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("payment_obligations")
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
        # string, since /updateobligation's legacy fallback mapper
        # renders this value to Telegram for unmapped codes.
        log.error("update_payment_obligation_admin_fields infrastructure failure")
        return {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}


def update_payment_obligation_status(
    obligation_id: str, status: str, *, issued_at: str = "", cancelled_at: str = "",
) -> dict:
    """Low-level manual-lifecycle Status write (draft/issued/cancelled/
    archived only — never partially_paid/paid, those go through
    update_payment_obligation_balance()). Does not check the transition
    matrix — business_builder already did that.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not obligation_id:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "obligation_id не указан"}
    if status not in OBLIGATION_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_OBLIGATION_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(OBLIGATION_STATUS)}",
        }

    found = _find_obligation_row(obligation_id)
    if not found:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": f"Payment Obligation '{obligation_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("payment_obligations")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        for field, value in (("Issued At", issued_at), ("Cancelled At", cancelled_at)):
            if value and not current.get(field, ""):
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_payment_obligation_status({obligation_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_payment_obligation_balance(
    obligation_id: str, *, status: str, paid_amount: str, remaining_amount: str,
    paid_at: str = "", clear_paid_at: bool = False,
) -> dict:
    """
    Persist the verified derived-balance cache (ADR-022 §14/§21/§22).
    Canonical truth remains Obligation Amount + Transaction rows — this
    is a cache write only, always called by business_builder after
    recomputation from the Transaction ledger, never the source of
    truth itself. Always used for the partially_paid/paid/issued
    (post-reversal) status synchronization path — never for draft/
    cancelled/archived.
    """
    if not obligation_id:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "obligation_id не указан"}
    if status not in OBLIGATION_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_OBLIGATION_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(OBLIGATION_STATUS)}",
        }

    found = _find_obligation_row(obligation_id)
    if not found:
        return {"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": f"Payment Obligation '{obligation_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("payment_obligations")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True
        if current.get("Paid Amount", "") != paid_amount:
            sheet.update_cell(row_num, idx["Paid Amount"] + 1, paid_amount)
            changed = True
        if current.get("Remaining Amount", "") != remaining_amount:
            sheet.update_cell(row_num, idx["Remaining Amount"] + 1, remaining_amount)
            changed = True

        if paid_at and not current.get("Paid At", ""):
            sheet.update_cell(row_num, idx["Paid At"] + 1, paid_at)
            changed = True
        elif clear_paid_at and current.get("Paid At", ""):
            sheet.update_cell(row_num, idx["Paid At"] + 1, "")
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception:
        # Phase 17E-2A6-H1: fixed literal only — no exception
        # interpolation, no obligation ID, no status/paid/remaining/
        # paid-at values, no row content.
        log.error("update_payment_obligation_balance infrastructure failure")
        return {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}


# ─────────────────────────────────────────────────────────────
# Payment Transaction — reads
# ─────────────────────────────────────────────────────────────

def find_payment_transaction_by_id(transaction_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not transaction_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("payment_transactions", transaction_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _TRANSACTION_FIELDS}


def _load_transactions_raw_strict() -> list[dict]:
    """
    Canonical Transaction Registry read (Phase 17E-2A6-H0).

    Raises on infrastructure failure — never converts a failed read
    into an empty list. Returns [] only when the read itself
    succeeded and there are genuinely zero data rows. This is the
    sole implementation of the header-resolution/row-conversion
    logic; both _list_transactions_raw (legacy, swallowing) and
    list_payment_transactions_strict (fail-closed, for financial
    mutation callers only) delegate here so the two public shapes
    can never drift apart.
    """
    from business_core.sheets import get_business_sheet, get_header_index_map

    sheet = get_business_sheet("payment_transactions")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _TRANSACTION_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def _list_transactions_raw() -> list[dict]:
    try:
        return _load_transactions_raw_strict()
    except Exception:
        log.warning("_list_transactions_raw infrastructure failure")
        return []


def _filter_transactions(rows: list[dict], payment_obligation_id: str = "", status: str = "") -> list[dict]:
    """Shared filter semantics for both the legacy and strict list
    functions — never touches I/O, so it cannot itself raise on
    infrastructure failure."""
    if payment_obligation_id:
        rows = [r for r in rows if r["Payment Obligation ID"] == payment_obligation_id]
    if status:
        rows = [r for r in rows if r["Status"] == status]
    return rows


def list_payment_transactions(payment_obligation_id: str = "", status: str = "") -> list[dict]:
    """Read-only, simple filter. No business policy hidden here.
    Unchanged public contract: returns [] on infrastructure failure,
    for read/report/idempotency callers."""
    rows = _list_transactions_raw()
    return _filter_transactions(rows, payment_obligation_id, status)


def list_payment_transactions_strict(payment_obligation_id: str = "", status: str = "") -> list[dict]:
    """
    Phase 17E-2A6-H0: fail-closed variant of list_payment_transactions
    — for financial-mutation callers only (confirm_payment_transaction's
    overpayment precheck, _synchronize_payment_obligation_after_
    transaction_change). Raises on infrastructure failure instead of
    silently returning []; a caller MUST NOT treat an exception from
    this function as "no transactions" — a read failure and a
    genuinely empty ledger are structurally distinguishable states.
    Uses the exact same header resolution, row conversion, and filter
    semantics as list_payment_transactions (shared via
    _load_transactions_raw_strict/_filter_transactions), so successful
    output is always identical between the two.
    """
    rows = _load_transactions_raw_strict()
    return _filter_transactions(rows, payment_obligation_id, status)


def find_transactions_by_external_id(business_id: str, external_transaction_id: str) -> list[dict]:
    """Primary Transaction idempotency lookup (ADR-022 §17/§20): exact
    Business ID + External Transaction ID match."""
    if not business_id or not external_transaction_id:
        return []
    rows = _list_transactions_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["External Transaction ID"] == external_transaction_id
    ]


def find_transactions_by_caller_key(business_id: str, caller_idempotency_key: str) -> list[dict]:
    """Fallback Transaction idempotency lookup (ADR-022 §17/§20): exact
    Business ID + Caller Idempotency Key match, used when no External
    Transaction ID is supplied."""
    if not business_id or not caller_idempotency_key:
        return []
    rows = _list_transactions_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Caller Idempotency Key"] == caller_idempotency_key
    ]


# ─────────────────────────────────────────────────────────────
# Payment Transaction — ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_transaction_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("payment_transactions")


# ─────────────────────────────────────────────────────────────
# Payment Transaction — low-level creation
# ─────────────────────────────────────────────────────────────

def create_payment_transaction(
    business_id: str, payment_obligation_id: str, client_id: str, amount: str, currency: str, payment_date: str,
    *, payment_method: str = "", external_transaction_id: str = "", caller_idempotency_key: str = "",
    evidence_document_id: str = "", created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Obligation/Client/Document
    existence, does not normalize amount/currency, does not check
    idempotency, never confirms. All of that is business_builder.
    create_payment_transaction()'s job. Calling this directly bypasses
    that policy by design.

    Default (ADR-022 §15 preferred): Status=pending. Confirmed/Reversed
    metadata blank.

    Returns:
        {"ok": bool, "payment_transaction_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "business_id обязателен"}
    if not payment_obligation_id:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "payment_obligation_id обязателен"}
    if not client_id:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "client_id обязателен"}
    if not amount:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "amount обязателен"}
    if not currency:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "currency обязателен"}
    if not payment_date:
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": "payment_date обязателен"}
    if not external_transaction_id and not caller_idempotency_key:
        return {
            "ok": False, "payment_transaction_id": "", "code": "PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED",
            "error": "Требуется external_transaction_id или caller_idempotency_key",
        }

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        transaction_id = generate_next_transaction_id()
        now = _now_utc_str()
        values = {
            "Payment Transaction ID": transaction_id, "Business ID": business_id,
            "Payment Obligation ID": payment_obligation_id, "Client ID": client_id,
            "Amount": amount, "Currency": currency, "Payment Date": payment_date,
            "Payment Method": payment_method,
            "External Transaction ID": external_transaction_id,
            "Caller Idempotency Key": caller_idempotency_key,
            "Evidence Document ID": evidence_document_id,
            "Status": "pending", "Reversal Reason": "",
            "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
            "Created At": now, "Created By": created_by, "Updated At": now, "Notes": notes,
        }
        row = row_from_header_map(_TRANSACTION_FIELDS, values)
        append_business_row("payment_transactions", row)
        log.info(f"create_payment_transaction: {transaction_id}")
        return {"ok": True, "payment_transaction_id": transaction_id, "code": "PAYMENT_TRANSACTION_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_payment_transaction error: {exc}")
        return {"ok": False, "payment_transaction_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Payment Transaction — low-level updates
# ─────────────────────────────────────────────────────────────

def _find_transaction_row(transaction_id: str) -> Optional[tuple[int, dict]]:
    if not transaction_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("payment_transactions", transaction_id)
    except Exception:
        # Phase 17E-2A6-H1: fixed literal only — no exception
        # interpolation, no entity ID, no row content.
        log.warning("_find_transaction_row infrastructure failure")
        return None


def update_payment_transaction_admin_fields(transaction_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable, and only while the Transaction
    is still pending (ADR-022 §25) — once confirmed, financial and
    descriptive fields alike are frozen except through the explicit
    reversal path."""
    if not transaction_id:
        return {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": "transaction_id не указан"}

    identity_conflict = [k for k in updates if k in _TRANSACTION_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_IMMUTABLE",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Payment Transaction",
        }

    if "Status" in updates:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_STATUS",
            "error": "Status изменяется только через confirm/reverse/fail API",
        }

    unknown = [k for k in updates if k not in _TRANSACTION_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_STATUS",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_transaction_row(transaction_id)
    if not found:
        return {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": f"Payment Transaction '{transaction_id}' не найден"}
    row_num, current = found

    if current.get("Status", "") != "pending":
        return {
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_IMMUTABLE",
            "error": "Notes изменяемы только пока Payment Transaction в статусе pending",
        }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("payment_transactions")
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
    except Exception as exc:
        log.error(f"update_payment_transaction_admin_fields({transaction_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_payment_transaction_status(
    transaction_id: str, status: str, *,
    confirmed_at: str = "", confirmed_by: str = "",
    reversed_at: str = "", reversed_by: str = "", reversal_reason: str = "",
) -> dict:
    """
    Low-level Status (+ confirm/reversal metadata) write. Does not
    check the transition matrix, overpayment policy, or reason-required
    policy — business_builder.confirm_payment_transaction()/
    reverse_payment_transaction()/fail_payment_transaction() already
    validated all of that. Never touches Amount/Currency/Payment Date/
    External Transaction ID/Caller Idempotency Key/Evidence Document
    ID/Created At/Created By — this function's parameter set makes
    that structurally impossible, which is the immutability guarantee
    (ADR-022 §20).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not transaction_id:
        return {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": "transaction_id не указан"}
    if status not in TRANSACTION_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TRANSACTION_STATUS)}",
        }

    found = _find_transaction_row(transaction_id)
    if not found:
        return {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": f"Payment Transaction '{transaction_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("payment_transactions")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        for field, value in (
            ("Confirmed At", confirmed_at), ("Confirmed By", confirmed_by),
            ("Reversed At", reversed_at), ("Reversed By", reversed_by),
            ("Reversal Reason", reversal_reason),
        ):
            if value and current.get(field, "") != value:
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception:
        # Phase 17E-2A6-H1: fixed literal only — no exception
        # interpolation, no transaction ID, no requested status, no
        # confirmation/reversal metadata, no row content.
        log.error("update_payment_transaction_status infrastructure failure")
        return {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}
