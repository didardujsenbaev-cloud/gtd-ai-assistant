"""
Lead Manager — Lead / Sales Funnel Domain persistence (Phase 41C, ADR-024).

Sole transactional owner of LEADS. Mirrors payment_manager.py's/
offer_manager.py's role for their own domains (ADR-022/ADR-023
precedent): targeted sheet reads via sheets.find_row_by_id()/
generate_next_id(), never a positional-index assumption.

This module is deliberately low-level only: no cross-entity relation
validation, no contact normalization, no Expected Value/currency/
datetime normalization, no idempotency-decision policy beyond
exact-match lookup helpers, no duplicate-contact-warning policy beyond
exact-match lookup helpers, no lifecycle transition-matrix policy, no
qualification/conversion policy, no Client/Person mutation, no
Telegram UX, no Russian user-facing text. All cross-domain policy
lives solely in business_builder.py's Lead orchestration functions —
this module is the primitive those functions call after their own
validation passes, exactly like payment_manager.py/offer_manager.py
are to business_builder's Payment/Commercial Offer orchestration.

Lead is a fully separate entity from Person/Client (ADR-024 §1/§3):
this module never reads or writes people_registry, never writes
relationship_capital, and never creates or mutates a Client. Converted
Client ID is a reference-only field set exactly once by the conversion
orchestration function; this module enforces write-once immutability
for it structurally (see update_lead_status()'s parameter set).

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


LEAD_STATUS = ("new", "contacted", "qualified", "unqualified", "converted", "lost", "archived")

_LEAD_FIELDS = [
    "Lead ID", "Business ID", "Caller Idempotency Key",
    "Contact Name Snapshot", "Phone Snapshot", "WhatsApp Snapshot",
    "Email Snapshot", "Company Snapshot",
    "Service ID", "Source", "Channel ID", "Status",
    "Qualification Notes", "Disposition Reason",
    "Expected Value", "Currency",
    "Next Follow-up At", "Last Contacted At", "Assigned Person ID",
    "Converted Client ID", "Converted At", "Converted By",
    "Created At", "Created By", "Updated At", "Archived At", "Notes",
]

_ADMIN_EDITABLE_FIELDS = ("Notes",)
_ACTIVE_EDITABLE_FIELDS = (
    "Contact Name Snapshot", "Phone Snapshot", "WhatsApp Snapshot",
    "Email Snapshot", "Company Snapshot",
    "Service ID", "Source", "Channel ID", "Qualification Notes",
    "Expected Value", "Currency", "Next Follow-up At", "Last Contacted At",
    "Assigned Person ID", "Notes",
)
_IDENTITY_FIELDS = (
    "Lead ID", "Business ID", "Caller Idempotency Key",
    "Converted Client ID", "Converted At", "Converted By",
    "Created At", "Created By",
)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

def find_lead_by_id(lead_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only. Returns the row unconditionally,
    including archived/converted Leads (ADR-024 §22/§25 — exact-ID read
    always works)."""
    if not lead_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("leads", lead_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _LEAD_FIELDS}


def _list_leads_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("leads")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_leads_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _LEAD_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_leads(
    business_id: str = "", service_id: str = "", channel_id: str = "",
    assigned_person_id: str = "", converted_client_id: str = "",
    status: str = "", source: str = "", currency: str = "",
    *, include_archived: bool = False,
) -> list[dict]:
    """Read-only, exact-match filters only. No fuzzy/substring matching,
    no arbitrary first-pick. Archived Leads excluded by default (ADR-024
    §22/§29) unless include_archived=True or status="archived" is
    explicitly requested."""
    rows = _list_leads_raw()
    filters = {
        "Business ID": business_id, "Service ID": service_id, "Channel ID": channel_id,
        "Assigned Person ID": assigned_person_id, "Converted Client ID": converted_client_id,
        "Status": status, "Source": source, "Currency": currency,
    }
    for field, value in filters.items():
        if value:
            rows = [r for r in rows if r.get(field, "") == value]
    if not include_archived and status != "archived":
        rows = [r for r in rows if r.get("Status", "") != "archived"]
    return rows


def find_leads_by_idempotency_key(business_id: str, caller_idempotency_key: str) -> list[dict]:
    """Primary Lead idempotency lookup (ADR-024 §10): exact Business ID
    + Caller Idempotency Key match. Never fuzzy, never first-pick — the
    caller (business_builder) decides zero/one/multiple policy from
    this full list."""
    if not business_id or not caller_idempotency_key:
        return []
    rows = _list_leads_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Caller Idempotency Key"] == caller_idempotency_key
    ]


def find_leads_by_exact_contact_channels(
    business_id: str, *, phone: str = "", whatsapp: str = "", email: str = "",
    exclude_lead_id: str = "",
) -> list[dict]:
    """
    Duplicate-contact warning lookup (ADR-024 §9/§11) — a mechanism
    fully distinct from idempotency (ADR-024 §10). Exact normalized-
    value match only, scoped to one Business:

      - phone matches an existing Phone Snapshot OR WhatsApp Snapshot;
      - whatsapp matches an existing Phone Snapshot OR WhatsApp Snapshot;
      - email matches an existing Email Snapshot.

    All already-normalized values are passed in by business_builder —
    this function performs no normalization itself. Never fuzzy, never
    name-based, never cross-Business. Returns every matching row
    (deduplicated by Lead ID) — the caller decides what to do with a
    non-empty result; this function only ever warns by returning
    matches, it never blocks and never merges.
    """
    if not business_id or not any((phone, whatsapp, email)):
        return []
    rows = _list_leads_raw()
    matches: dict[str, dict] = {}
    for r in rows:
        if r["Business ID"] != business_id:
            continue
        if exclude_lead_id and r["Lead ID"] == exclude_lead_id:
            continue
        row_phone = r.get("Phone Snapshot", "")
        row_whatsapp = r.get("WhatsApp Snapshot", "")
        row_email = r.get("Email Snapshot", "")

        hit = False
        if phone and (row_phone == phone or row_whatsapp == phone):
            hit = True
        if whatsapp and (row_phone == whatsapp or row_whatsapp == whatsapp):
            hit = True
        if email and row_email == email:
            hit = True

        if hit:
            matches[r["Lead ID"]] = r

    return list(matches.values())


# ─────────────────────────────────────────────────────────────
# ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_lead_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("leads")


# ─────────────────────────────────────────────────────────────
# Low-level creation
# ─────────────────────────────────────────────────────────────

def create_lead(
    business_id: str, contact_name_snapshot: str,
    *, caller_idempotency_key: str = "",
    phone_snapshot: str = "", whatsapp_snapshot: str = "", email_snapshot: str = "",
    company_snapshot: str = "", service_id: str = "", source: str = "", channel_id: str = "",
    qualification_notes: str = "", expected_value: str = "", currency: str = "",
    next_follow_up_at: str = "", last_contacted_at: str = "", assigned_person_id: str = "",
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Business/Service/Channel/
    Assigned Person existence, does not normalize contact snapshots,
    does not normalize Expected Value/currency/datetimes, does not
    check idempotency, does not check duplicate-contact warnings. All
    of that is business_builder.create_lead()'s job. Calling this
    directly bypasses that policy by design.

    Defaults (ADR-024 §16): Status=new, Disposition Reason blank,
    Converted fields blank, Archived At blank, Created/Updated At set.

    Returns:
        {"ok": bool, "lead_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "lead_id": "", "code": "", "error": "business_id обязателен"}
    if not contact_name_snapshot:
        return {"ok": False, "lead_id": "", "code": "", "error": "contact_name_snapshot обязателен"}

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        lead_id = generate_next_lead_id()
        now = _now_utc_str()
        values = {
            "Lead ID": lead_id, "Business ID": business_id,
            "Caller Idempotency Key": caller_idempotency_key,
            "Contact Name Snapshot": contact_name_snapshot,
            "Phone Snapshot": phone_snapshot, "WhatsApp Snapshot": whatsapp_snapshot,
            "Email Snapshot": email_snapshot, "Company Snapshot": company_snapshot,
            "Service ID": service_id, "Source": source, "Channel ID": channel_id,
            "Status": "new",
            "Qualification Notes": qualification_notes, "Disposition Reason": "",
            "Expected Value": expected_value, "Currency": currency,
            "Next Follow-up At": next_follow_up_at, "Last Contacted At": last_contacted_at,
            "Assigned Person ID": assigned_person_id,
            "Converted Client ID": "", "Converted At": "", "Converted By": "",
            "Created At": now, "Created By": created_by, "Updated At": now,
            "Archived At": "", "Notes": notes,
        }
        row = row_from_header_map(_LEAD_FIELDS, values)
        append_business_row("leads", row)
        log.info(f"create_lead: {lead_id}")
        return {"ok": True, "lead_id": lead_id, "code": "LEAD_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_lead error: {exc}")
        return {"ok": False, "lead_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Low-level updates
# ─────────────────────────────────────────────────────────────

def _find_lead_row(lead_id: str) -> Optional[tuple[int, dict]]:
    if not lead_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("leads", lead_id)
    except Exception:
        # Phase 17E-2A3-H1: fixed literal only — no exception
        # interpolation, no entity ID, no row content.
        log.warning("_find_lead_row infrastructure failure")
        return None


def _write_fields(lead_id: str, row_num: int, current: dict, updates: dict) -> dict:
    from business_core.sheets import get_business_sheet, get_header_index_map

    sheet = get_business_sheet("leads")
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


def update_lead_admin_fields(lead_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable, in every status — Notes is not
    a commercial/contact fact (ADR-024 §23/§27) and is never logged."""
    if not lead_id:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": "lead_id не указан"}

    identity_conflict = [k for k in updates if k in _IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "LEAD_IMMUTABLE",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Lead",
        }
    if "Status" in updates:
        return {"ok": False, "changed": False, "code": "LEAD_IMMUTABLE", "error": "Status изменяется только через transition API"}

    unknown = [k for k in updates if k not in _ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {"ok": False, "changed": False, "code": "LEAD_IMMUTABLE", "error": f"Недопустимые поля для обновления: {', '.join(unknown)}"}

    found = _find_lead_row(lead_id)
    if not found:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": f"Lead '{lead_id}' не найден"}
    row_num, current = found

    try:
        return _write_fields(lead_id, row_num, current, updates)
    except Exception:
        # Phase 17E-2A3-H1: fixed literal only — no exception
        # interpolation, no entity ID, no updates dict, no row
        # content. "error" is likewise sanitized to a fixed safe
        # string, since /updatelead's legacy fallback mapper renders
        # this value to Telegram for unmapped codes.
        log.error("update_lead_admin_fields infrastructure failure")
        return {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}


def update_lead_active_fields(lead_id: str, updates: dict) -> dict:
    """Active-status commercial/contact-field update. Does not check the
    current Status itself — business_builder already verified the Lead
    is new/contacted/qualified before calling this. Enforces only the
    field whitelist here."""
    if not lead_id:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": "lead_id не указан"}

    unknown = [k for k in updates if k not in _ACTIVE_EDITABLE_FIELDS]
    if unknown:
        return {"ok": False, "changed": False, "code": "LEAD_IMMUTABLE", "error": f"Недопустимые поля для обновления: {', '.join(unknown)}"}

    found = _find_lead_row(lead_id)
    if not found:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": f"Lead '{lead_id}' не найден"}
    row_num, current = found

    try:
        return _write_fields(lead_id, row_num, current, updates)
    except Exception as exc:
        log.error(f"update_lead_active_fields({lead_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_lead_status(
    lead_id: str, status: str, *,
    qualification_notes: str = "", disposition_reason: str = "",
    last_contacted_at: str = "",
    converted_client_id: str = "", converted_at: str = "", converted_by: str = "",
    archived_at: str = "",
) -> dict:
    """
    Low-level Status (+ lifecycle metadata) write. Does not check the
    transition matrix, disposition-reason-required policy, or
    conversion-target policy — business_builder's transition functions
    already validated all of that. Never touches any contact/commercial
    field (Contact Name/Phone/WhatsApp/Email/Company Snapshot, Service
    ID, Source, Channel ID, Expected Value, Currency) — this function's
    parameter set makes that structurally impossible, which is the
    converted/terminal-Lead immutability guarantee (ADR-024 §20/§28).

    Converted Client ID / Converted At / Converted By / Archived At are
    write-once: once set, this function never overwrites them again
    (the same idempotent-no-op-vs-conflict decision is business_
    builder's job, made before ever reaching this write). Last
    Contacted At and Qualification Notes are overwritten whenever a
    non-empty value is supplied, since "contacted"/"qualified" may be
    reached more than once per the approved transition matrix.

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not lead_id:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": "lead_id не указан"}
    if status not in LEAD_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_LEAD_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(LEAD_STATUS)}",
        }

    found = _find_lead_row(lead_id)
    if not found:
        return {"ok": False, "changed": False, "code": "LEAD_NOT_FOUND", "error": f"Lead '{lead_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("leads")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        if qualification_notes and current.get("Qualification Notes", "") != qualification_notes:
            sheet.update_cell(row_num, idx["Qualification Notes"] + 1, qualification_notes)
            changed = True

        if last_contacted_at and current.get("Last Contacted At", "") != last_contacted_at:
            sheet.update_cell(row_num, idx["Last Contacted At"] + 1, last_contacted_at)
            changed = True

        for field, value in (
            ("Disposition Reason", disposition_reason),
            ("Converted Client ID", converted_client_id),
            ("Converted At", converted_at),
            ("Converted By", converted_by),
            ("Archived At", archived_at),
        ):
            if value and not current.get(field, ""):
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_lead_status({lead_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}
