"""
Offer Manager — Commercial Offer Domain persistence (Phase 40C, ADR-023).

Sole transactional owner of COMMERCIAL_OFFERS. Mirrors payment_manager.
py's role for the Payment Domain (ADR-022 precedent): targeted sheet
reads via sheets.find_row_by_id()/generate_next_id(), never a
positional-index assumption.

This module is deliberately low-level only: no cross-entity relation
validation, no amount/currency/date business normalization, no
idempotency-decision policy beyond exact-match lookup helpers, no
revision policy, no latest-version-acceptance policy, no branching
policy, no Roadmap/Stage/Document/Service/Client/Payment mutation, no
Telegram UX, no Russian user-facing text. All cross-domain policy
lives solely in business_builder.py's Commercial Offer orchestration
functions — this module is the primitive those functions call after
their own validation passes, exactly like payment_manager.py is to
business_builder.create_payment_obligation().

Every row in commercial_offers is an immutable commercial version
(ADR-023 §2) — this module never rewrites commercial fields of an
existing row; only lifecycle status/metadata and Notes may ever be
updated post-creation.

Offer Series ID (`OFS-NNN`) lives in a column other than column A, so
it cannot use business_core.sheets.generate_next_id()'s column-A-only
scan — generate_next_series_id() below implements the same
exact-match-regex, deterministic-next-number algorithm directly
against the "Offer Series ID" column.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


OFFER_STATUS = ("draft", "sent", "accepted", "rejected", "expired", "cancelled", "archived")

_OFFER_FIELDS = [
    "Commercial Offer ID", "Offer Series ID", "Previous Commercial Offer ID",
    "Version Number", "Business ID", "Client ID", "Object ID", "Service ID",
    "Roadmap ID", "Offer Document ID", "Title Snapshot", "Scope Snapshot",
    "Quoted Amount", "Currency", "Valid Until", "Status",
    "Caller Idempotency Key",
    "Created At", "Created By", "Updated At",
    "Sent At", "Sent By",
    "Accepted At", "Accepted By",
    "Rejected At", "Rejected By", "Rejection Reason",
    "Expired At",
    "Cancelled At", "Cancelled By", "Cancellation Reason",
    "Archived At", "Notes",
]

_ADMIN_EDITABLE_FIELDS = ("Notes",)
_DRAFT_EDITABLE_FIELDS = (
    "Title Snapshot", "Scope Snapshot", "Quoted Amount", "Currency", "Valid Until",
    "Object ID", "Service ID", "Roadmap ID", "Offer Document ID", "Notes",
)
_IDENTITY_FIELDS = (
    "Commercial Offer ID", "Offer Series ID", "Previous Commercial Offer ID",
    "Version Number", "Business ID", "Client ID", "Caller Idempotency Key",
    "Created At", "Created By",
)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

def find_commercial_offer_by_id(offer_id: str) -> Optional[dict]:
    """Exact-ID read. Read-only."""
    if not offer_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("commercial_offers", offer_id)
    if not found:
        return None
    _, v = found
    return {f: v.get(f, "") for f in _OFFER_FIELDS}


def _list_offers_raw() -> list[dict]:
    from business_core.sheets import get_business_sheet, get_header_index_map

    try:
        sheet = get_business_sheet("commercial_offers")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"_list_offers_raw() error: {exc}")
        return []
    if len(all_values) < 2:
        return []

    idx = get_header_index_map(all_values[0])

    def _g(row, h):
        i = idx.get(h)
        return row[i].strip() if (i is not None and i < len(row)) else ""

    return [
        {f: _g(row, f) for f in _OFFER_FIELDS}
        for row in all_values[1:]
        if row and row[0].strip()
    ]


def list_commercial_offers(
    business_id: str = "", client_id: str = "", object_id: str = "",
    service_id: str = "", roadmap_id: str = "", offer_series_id: str = "",
    status: str = "", currency: str = "", document_id: str = "",
) -> list[dict]:
    """Read-only, simple filter. No business policy hidden here."""
    rows = _list_offers_raw()
    filters = {
        "Business ID": business_id, "Client ID": client_id, "Object ID": object_id,
        "Service ID": service_id, "Roadmap ID": roadmap_id,
        "Offer Series ID": offer_series_id, "Status": status, "Currency": currency,
        "Offer Document ID": document_id,
    }
    for field, value in filters.items():
        if value:
            rows = [r for r in rows if r.get(field, "") == value]
    return rows


def find_commercial_offers_by_idempotency_key(business_id: str, caller_idempotency_key: str) -> list[dict]:
    """Exact-match idempotency lookup: Business ID + Caller Idempotency
    Key. Never fuzzy, never first-pick — the caller (business_builder)
    decides zero/one/multiple policy from this full list."""
    if not business_id or not caller_idempotency_key:
        return []
    rows = _list_offers_raw()
    return [
        r for r in rows
        if r["Business ID"] == business_id
        and r["Caller Idempotency Key"] == caller_idempotency_key
    ]


def list_commercial_offers_by_series(offer_series_id: str) -> list[dict]:
    """Read-only, exact Offer Series ID match. Used by latest-version
    derivation — never itself decides "latest", only returns the full set."""
    if not offer_series_id:
        return []
    rows = _list_offers_raw()
    return [r for r in rows if r["Offer Series ID"] == offer_series_id]


def find_latest_commercial_offer_in_series(offer_series_id: str) -> dict:
    """
    Canonical latest-version resolver (ADR-023 §18): latest = maximum
    Version Number within the series. No stored "Is Current" flag.
    Malformed/nonpositive version numbers and duplicate-maximum rows
    are reported as integrity errors — never silently first-picked.

    Returns:
        {"ok": bool, "code": str, "error": str | None, "offer": dict | None}
    """
    rows = list_commercial_offers_by_series(offer_series_id)
    if not rows:
        return {"ok": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": f"Offer Series {offer_series_id} не найден", "offer": None}

    parsed = []
    for r in rows:
        raw = r.get("Version Number", "")
        try:
            version = int(raw)
        except (TypeError, ValueError):
            return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_VERSION", "error": f"Некорректный Version Number '{raw}' в серии {offer_series_id}", "offer": None}
        if version <= 0:
            return {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_VERSION", "error": f"Version Number должен быть положительным, получено '{raw}'", "offer": None}
        parsed.append((version, r))

    max_version = max(v for v, _ in parsed)
    at_max = [r for v, r in parsed if v == max_version]
    if len(at_max) > 1:
        ids = tuple(r["Commercial Offer ID"] for r in at_max)
        return {
            "ok": False, "code": "COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR",
            "error": f"Несколько строк с максимальным Version Number={max_version} в серии {offer_series_id}: {ids}",
            "offer": None,
        }

    return {"ok": True, "code": "", "error": None, "offer": at_max[0]}


# ─────────────────────────────────────────────────────────────
# ID generation
# ─────────────────────────────────────────────────────────────

def generate_next_offer_id() -> str:
    from business_core.sheets import generate_next_id
    return generate_next_id("commercial_offers")


def generate_next_series_id() -> str:
    """
    Offer Series ID lives in a column other than column A, so
    sheets.generate_next_id() (column-A-only scan) cannot be reused
    directly. Same deterministic algorithm, applied to the "Offer
    Series ID" column instead: anchored exact-match regex, max
    existing numeric suffix + 1.
    """
    from business_core.sheets import get_business_sheet, get_header_index_map

    prefix = "OFS"
    try:
        sheet = get_business_sheet("commercial_offers")
        all_values = sheet.get_all_values()
    except Exception as exc:
        log.warning(f"generate_next_series_id() error: {exc}")
        return f"{prefix}-001"

    if len(all_values) < 2:
        return f"{prefix}-001"

    idx = get_header_index_map(all_values[0])
    col = idx.get("Offer Series ID")
    if col is None:
        return f"{prefix}-001"

    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    numbers = []
    for row in all_values[1:]:
        if col < len(row) and row[col]:
            m = pattern.match(str(row[col]))
            if m:
                numbers.append(int(m.group(1)))

    next_num = max(numbers, default=0) + 1
    return f"{prefix}-{next_num:03d}"


# ─────────────────────────────────────────────────────────────
# Low-level creation
# ─────────────────────────────────────────────────────────────

def create_commercial_offer(
    offer_series_id: str, previous_commercial_offer_id: str, version_number: int,
    business_id: str, client_id: str, title_snapshot: str, scope_snapshot: str,
    quoted_amount: str, currency: str, valid_until: str,
    *, object_id: str = "", service_id: str = "", roadmap_id: str = "",
    offer_document_id: str = "", caller_idempotency_key: str = "",
    created_by: str = "", notes: str = "",
) -> dict:
    """
    Low-level write — does not validate Business/Client/relation
    existence, does not normalize amount/currency/date, does not check
    idempotency, does not check series/version integrity. All of that
    is business_builder's job. Calling this directly bypasses that
    policy by design.

    Defaults: Status=draft, lifecycle timestamps/actors/reasons blank.

    Returns:
        {"ok": bool, "commercial_offer_id": str, "code": str, "error": str | None}
    """
    if not business_id:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "business_id обязателен"}
    if not client_id:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "client_id обязателен"}
    if not offer_series_id:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "offer_series_id обязателен"}
    if not title_snapshot:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "title_snapshot обязателен"}
    if not scope_snapshot:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "scope_snapshot обязателен"}
    if not quoted_amount:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "quoted_amount обязателен"}
    if not currency:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "currency обязателен"}
    if not valid_until:
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": "valid_until обязателен"}

    try:
        from business_core.sheets import append_business_row, row_from_header_map

        offer_id = generate_next_offer_id()
        now = _now_utc_str()
        values = {
            "Commercial Offer ID": offer_id, "Offer Series ID": offer_series_id,
            "Previous Commercial Offer ID": previous_commercial_offer_id,
            "Version Number": str(version_number),
            "Business ID": business_id, "Client ID": client_id,
            "Object ID": object_id, "Service ID": service_id, "Roadmap ID": roadmap_id,
            "Offer Document ID": offer_document_id,
            "Title Snapshot": title_snapshot, "Scope Snapshot": scope_snapshot,
            "Quoted Amount": quoted_amount, "Currency": currency, "Valid Until": valid_until,
            "Status": "draft", "Caller Idempotency Key": caller_idempotency_key,
            "Created At": now, "Created By": created_by, "Updated At": now,
            "Sent At": "", "Sent By": "",
            "Accepted At": "", "Accepted By": "",
            "Rejected At": "", "Rejected By": "", "Rejection Reason": "",
            "Expired At": "",
            "Cancelled At": "", "Cancelled By": "", "Cancellation Reason": "",
            "Archived At": "", "Notes": notes,
        }
        row = row_from_header_map(_OFFER_FIELDS, values)
        append_business_row("commercial_offers", row)
        log.info(f"create_commercial_offer: {offer_id} series={offer_series_id} version={version_number}")
        return {"ok": True, "commercial_offer_id": offer_id, "code": "COMMERCIAL_OFFER_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_commercial_offer error: {exc}")
        return {"ok": False, "commercial_offer_id": "", "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Low-level updates
# ─────────────────────────────────────────────────────────────

def _find_offer_row(offer_id: str) -> Optional[tuple[int, dict]]:
    if not offer_id:
        return None
    try:
        from business_core.sheets import find_row_by_id
        return find_row_by_id("commercial_offers", offer_id)
    except Exception as exc:
        log.warning(f"_find_offer_row({offer_id}) error: {exc}")
        return None


def update_commercial_offer_admin_fields(offer_id: str, updates: dict) -> dict:
    """Only Notes is ordinarily mutable, in every status (Notes is not
    a commercial fact — ADR-023 §16)."""
    if not offer_id:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "offer_id не указан"}

    identity_conflict = [k for k in updates if k in _IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "code": "COMMERCIAL_OFFER_IMMUTABLE",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Commercial Offer",
        }
    if "Status" in updates:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_IMMUTABLE", "error": "Status изменяется только через transition API"}

    unknown = [k for k in updates if k not in _ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_IMMUTABLE", "error": f"Недопустимые поля для обновления: {', '.join(unknown)}"}

    found = _find_offer_row(offer_id)
    if not found:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": f"Commercial Offer '{offer_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("commercial_offers")
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
        log.error(f"update_commercial_offer_admin_fields({offer_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_commercial_offer_draft_fields(offer_id: str, updates: dict) -> dict:
    """Draft-only commercial-field update. Does not check the current
    Status itself — business_builder already verified `draft` before
    calling this. Enforces only the field whitelist here."""
    if not offer_id:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "offer_id не указан"}

    unknown = [k for k in updates if k not in _DRAFT_EDITABLE_FIELDS]
    if unknown:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_IMMUTABLE", "error": f"Недопустимые поля для draft-обновления: {', '.join(unknown)}"}

    found = _find_offer_row(offer_id)
    if not found:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": f"Commercial Offer '{offer_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("commercial_offers")
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
        log.error(f"update_commercial_offer_draft_fields({offer_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_commercial_offer_status(
    offer_id: str, status: str, *,
    sent_at: str = "", sent_by: str = "",
    accepted_at: str = "", accepted_by: str = "",
    rejected_at: str = "", rejected_by: str = "", rejection_reason: str = "",
    expired_at: str = "",
    cancelled_at: str = "", cancelled_by: str = "", cancellation_reason: str = "",
    archived_at: str = "",
) -> dict:
    """
    Low-level Status (+ transition metadata) write. Does not check the
    transition matrix, actor/reason-required policy, or latest-version
    policy — business_builder's transition functions already validated
    all of that. Never touches any commercial field (Title Snapshot/
    Scope Snapshot/Quoted Amount/Currency/Valid Until/relations) — this
    function's parameter set makes that structurally impossible, which
    is the immutability guarantee for sent/accepted Offers (ADR-023 §28).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not offer_id:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "offer_id не указан"}
    if status not in OFFER_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_COMMERCIAL_OFFER_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(OFFER_STATUS)}",
        }

    found = _find_offer_row(offer_id)
    if not found:
        return {"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": f"Commercial Offer '{offer_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("commercial_offers")
        idx = get_header_index_map(sheet.row_values(1))

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        for field, value in (
            ("Sent At", sent_at), ("Sent By", sent_by),
            ("Accepted At", accepted_at), ("Accepted By", accepted_by),
            ("Rejected At", rejected_at), ("Rejected By", rejected_by), ("Rejection Reason", rejection_reason),
            ("Expired At", expired_at),
            ("Cancelled At", cancelled_at), ("Cancelled By", cancelled_by), ("Cancellation Reason", cancellation_reason),
            ("Archived At", archived_at),
        ):
            if value and not current.get(field, ""):
                sheet.update_cell(row_num, idx[field] + 1, value)
                changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, _now_utc_str())

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_commercial_offer_status({offer_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}
