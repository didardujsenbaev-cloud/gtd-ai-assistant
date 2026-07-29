"""
Phase 16B.5: Search and Reports by Effective Document Fields.

Read-only, business-scoped document search over EFFECTIVE structured
fields (business_core.document_confirmation.EffectiveStructuredFields)
— never raw AI values where a human decision (confirm/reject) already
overrides them. Backing architecture:

    1 read_business_sheet("document_registry")
    1 read_business_sheet("document_content")
    in-memory join by Document ID, in-memory filter/sort/paginate

DOCUMENT_FIELD_REVIEWS is NEVER read here — Confirmed Fields JSON /
Structured Review Status / Structured Review Version (the materialized
cache already on DOCUMENT_CONTENT) are the only source consulted, so
the call count is FIXED at exactly 2 reads regardless of how many
documents match or how many are returned.

business_id is a mandatory FILTER/boundary, not an access-control
mechanism — this codebase has no RBAC (single-operator personal bot,
see Phase 16B.3's authorization-contract audit); it is required here
purely to bound the search to one business's documents and to keep the
result set (and Sheets read volume attention) predictable, not because
some other business's data is otherwise protected by permissions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field

ALLOWED_SORT_VALUES = ("date_desc", "date_asc", "created_desc")

# Phase 16B.5 §C: exactly these external command parameters — anything
# else is a hard validation error, never silently ignored.
ALLOWED_SEARCH_PARAMS = frozenset({
    "business_id", "date_from", "date_to", "direction", "requires_action",
    "has_expiration", "review_status", "conflict", "limit", "offset", "sort",
})

_REVIEW_STATUS_VALUES = ("unreviewed", "partially_confirmed", "confirmed", "rejected")

DEFAULT_LIMIT = 10
MAX_LIMIT = 20


@dataclass(frozen=True)
class DocumentSearchCriteria:
    business_id: str
    document_date_from: str = ""
    document_date_to: str = ""
    direction: str | None = None
    requires_action: bool | None = None
    has_expiration: bool | None = None
    review_status: str | None = None
    conflict: bool | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str = "date_desc"


@dataclass(frozen=True)
class DocumentSearchItem:
    """
    Never includes raw extracted_fields, Confirmed Fields JSON, actor,
    Review ID/Mutation ID, Drive URL, or hashes — see
    business_core.telegram_handlers._render_document_search_result()
    for what additionally is deliberately never shown even from THIS
    typed item (file_name, full document_name beyond a bounded/
    sanitized length).

    has_conflict: bool | None — None means the review cache for this
    document is malformed/inconsistent and conflict status could NOT
    be reliably determined (cache_warning is also True in that case) —
    NEVER coerced to False.
    """
    document_id: str
    document_name: str
    file_name: str
    business_id: str
    effective_document_date: str
    document_date_source: str          # "human" | "ai" | "none"
    effective_direction: str
    direction_source: str              # "human" | "ai" | "none"
    effective_requires_action: bool | None
    effective_has_expiration: bool | None
    review_status: str
    review_version: int
    has_conflict: bool | None
    duplicate_status: str
    duplicate_of_document_id: str
    cache_warning: bool = False


@dataclass(frozen=True)
class DocumentSearchResult:
    criteria: DocumentSearchCriteria
    total_matches: int
    returned_count: int
    offset: int
    limit: int
    items: tuple = ()
    warnings: tuple = ()


def _parse_bool_param(name: str, raw: str) -> tuple:
    v = (raw or "").strip().lower()
    if v == "true":
        return True, None
    if v == "false":
        return False, None
    return None, f"{name} должен быть true или false."


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def parse_search_criteria(kv: dict) -> tuple:
    """
    kv: an already-parsed key=value dict (e.g. from
    business_core.telegram_handlers._parse_kv_args()).

    Returns (DocumentSearchCriteria | None, error_message | None) — a
    non-None error always means criteria is None, never a partially
    valid object. Never raises.
    """
    unknown = sorted(k for k in kv if k not in ALLOWED_SEARCH_PARAMS)
    if unknown:
        return None, f"Неизвестный параметр: {', '.join(unknown)}."

    business_id = (kv.get("business_id", "") or "").strip()
    if not business_id:
        return None, "business_id обязателен."
    if _has_control_characters(business_id):
        return None, "business_id содержит недопустимые символы."

    from business_core.document_intelligence import parse_exact_date, DIRECTION_VALUES

    date_from = (kv.get("date_from", "") or "").strip()
    if date_from:
        iso, _warn = parse_exact_date(date_from)
        if not iso:
            return None, f"Невалидная date_from: {date_from!r} (нужен точный формат YYYY-MM-DD)."
        date_from = iso

    date_to = (kv.get("date_to", "") or "").strip()
    if date_to:
        iso, _warn = parse_exact_date(date_to)
        if not iso:
            return None, f"Невалидная date_to: {date_to!r} (нужен точный формат YYYY-MM-DD)."
        date_to = iso

    if date_from and date_to and date_from > date_to:
        return None, "date_from не может быть позже date_to."

    direction = None
    if "direction" in kv:
        v = (kv["direction"] or "").strip().lower()
        if v not in DIRECTION_VALUES:
            return None, f"direction должен быть одним из: {', '.join(DIRECTION_VALUES)}."
        direction = v

    requires_action = None
    if "requires_action" in kv:
        requires_action, err = _parse_bool_param("requires_action", kv["requires_action"])
        if err:
            return None, err

    has_expiration = None
    if "has_expiration" in kv:
        has_expiration, err = _parse_bool_param("has_expiration", kv["has_expiration"])
        if err:
            return None, err

    review_status = None
    if "review_status" in kv:
        v = (kv["review_status"] or "").strip().lower()
        if v not in _REVIEW_STATUS_VALUES:
            return None, f"review_status должен быть одним из: {', '.join(_REVIEW_STATUS_VALUES)}."
        review_status = v

    conflict = None
    if "conflict" in kv:
        conflict, err = _parse_bool_param("conflict", kv["conflict"])
        if err:
            return None, err

    limit = DEFAULT_LIMIT
    if "limit" in kv:
        try:
            limit = int(kv["limit"])
        except (ValueError, TypeError):
            return None, "limit должен быть целым числом."
        if limit <= 0:
            return None, "limit должен быть больше 0."
        if limit > MAX_LIMIT:
            return None, f"limit не может быть больше {MAX_LIMIT}."

    offset = 0
    if "offset" in kv:
        try:
            offset = int(kv["offset"])
        except (ValueError, TypeError):
            return None, "offset должен быть целым числом."
        if offset < 0:
            return None, "offset не может быть отрицательным."

    sort = (kv.get("sort", "") or "date_desc").strip()
    if sort not in ALLOWED_SORT_VALUES:
        return None, f"sort должен быть одним из: {', '.join(ALLOWED_SORT_VALUES)}."

    return DocumentSearchCriteria(
        business_id=business_id, document_date_from=date_from, document_date_to=date_to,
        direction=direction, requires_action=requires_action, has_expiration=has_expiration,
        review_status=review_status, conflict=conflict, limit=limit, offset=offset, sort=sort,
    ), None


def _sanitize_document_name(name: str, max_chars: int = 150) -> str:
    text = (name or "").strip()
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == "\t")
    return text[:max_chars]


def _sort_entries(entries: list, sort: str) -> list:
    """
    entries: list of (DocumentSearchItem, created_at_raw) tuples.

    Multi-pass STABLE sort, least-significant key first (Python's
    sort() is guaranteed stable, so each subsequent pass only breaks
    ties left by the previous one — the LAST pass is the most
    dominant/primary key). Missing/malformed Created At or effective
    date is treated the same way as business_core.document_intelligence
    .find_exact_duplicate()'s canonical-selection algorithm: a
    non-empty string always sorts before an empty one, regardless of
    sort direction — never a real calendar-date validity check, exactly
    matching that existing precedent.
    """
    entries = list(entries)
    entries.sort(key=lambda e: e[0].document_id)  # tertiary: Document ID ASC

    if sort == "created_desc":
        entries.sort(key=lambda e: (e[1] or ""), reverse=True)          # secondary: Created At DESC
        entries.sort(key=lambda e: 0 if (e[1] or "") else 1)             # primary: missing Created At last
        return entries

    # date_desc / date_asc: Created At is ALWAYS the DESC tie-break,
    # regardless of the primary date direction (Phase 16B.5 §F).
    entries.sort(key=lambda e: (e[1] or ""), reverse=True)
    entries.sort(key=lambda e: (e[0].effective_document_date or ""), reverse=(sort == "date_desc"))
    entries.sort(key=lambda e: 0 if e[0].effective_document_date else 1)  # primary: missing date last
    return entries


def search_documents(criteria: DocumentSearchCriteria) -> DocumentSearchResult:
    """
    Read-only. Exactly 2 Sheets reads total (document_registry,
    document_content), regardless of how many rows exist or match —
    never DOCUMENT_FIELD_REVIEWS, never a per-document read.

    Raises SheetsQuotaExceededError/TransientSheetsReadError exactly
    like any other read in this codebase — callers (Telegram handlers)
    catch these the same way /docanalysis and /reviewdoc already do.
    """
    from business_core.sheets import read_business_sheet
    from business_core.document_confirmation import (
        parse_confirmed_fields_json, parse_review_version, build_effective_structured_fields,
    )

    warnings: list = []

    registry_rows = read_business_sheet("document_registry")
    content_rows = read_business_sheet("document_content")

    # Business boundary applied at the registry level, first — a
    # document belonging to another Business ID never even enters the
    # candidate set. Duplicate Document ID within one business: first
    # occurrence wins deterministically, flagged via a warning, never a
    # crash and never two rows shown for one ID.
    registry_by_id: dict = {}
    for row in registry_rows:
        doc_id = row.get("Document ID", "")
        if not doc_id or row.get("Business ID", "") != criteria.business_id:
            continue
        if doc_id in registry_by_id:
            warnings.append(f"DUPLICATE_DOCUMENT_ID_REGISTRY:{doc_id}")
            continue
        registry_by_id[doc_id] = row

    content_by_id: dict = {}
    for row in content_rows:
        doc_id = row.get("Document ID", "")
        if not doc_id:
            continue
        if doc_id in content_by_id:
            warnings.append(f"DUPLICATE_DOCUMENT_ID_CONTENT:{doc_id}")
            continue
        content_by_id[doc_id] = row

    entries: list = []
    for doc_id, reg_row in registry_by_id.items():
        content_row = content_by_id.get(doc_id)
        if content_row is None:
            continue  # never analyzed -> no structured fields to search/filter by

        cache_warning = False

        # parse_confirmed_fields_json() itself never raises — it safely
        # falls back to {} for malformed JSON, which would be
        # indistinguishable from a genuinely empty "{}"/unreviewed
        # document. Detect malformed-but-non-empty JSON explicitly here
        # so it becomes a visible cache_warning, never silently treated
        # as "nothing to review".
        raw_confirmed_json = (content_row.get("Confirmed Fields JSON", "") or "").strip()
        if raw_confirmed_json:
            try:
                _parsed_check = json.loads(raw_confirmed_json)
                if not isinstance(_parsed_check, dict):
                    cache_warning = True
            except (ValueError, TypeError):
                cache_warning = True

        confirmed_fields = parse_confirmed_fields_json(content_row.get("Confirmed Fields JSON", ""))

        review_status = content_row.get("Structured Review Status", "") or "unreviewed"
        if review_status not in _REVIEW_STATUS_VALUES:
            review_status = "unreviewed"
            cache_warning = True

        review_version = parse_review_version(content_row.get("Structured Review Version", ""))

        try:
            effective = build_effective_structured_fields(content_row, confirmed_fields)
        except Exception:
            effective = None
            cache_warning = True

        if effective is None:
            eff_date, eff_date_source = "", "none"
            eff_direction, eff_direction_source = "", "none"
            eff_requires_action = None
            eff_has_expiration = None
            has_conflict = None
        else:
            eff_date = effective.document_date.effective_value or ""
            eff_date_source = effective.document_date.source
            eff_direction = effective.direction.effective_value or ""
            eff_direction_source = effective.direction.source
            eff_requires_action = effective.requires_action.effective_value
            eff_has_expiration = effective.has_expiration.effective_value
            has_conflict = any(f.conflict for f in effective)

        if cache_warning:
            has_conflict = None  # never coerced to False — Phase 16B.5 §A

        # ── Filters (Phase 16B.5 §D) ──
        if criteria.document_date_from or criteria.document_date_to:
            if not eff_date:
                continue
            if criteria.document_date_from and eff_date < criteria.document_date_from:
                continue
            if criteria.document_date_to and eff_date > criteria.document_date_to:
                continue

        if criteria.direction is not None and eff_direction != criteria.direction:
            continue

        if criteria.requires_action is not None and eff_requires_action is not criteria.requires_action:
            continue

        if criteria.has_expiration is not None and eff_has_expiration is not criteria.has_expiration:
            continue

        if criteria.review_status is not None and review_status != criteria.review_status:
            continue

        if criteria.conflict is not None and has_conflict is not criteria.conflict:
            continue

        item = DocumentSearchItem(
            document_id=doc_id,
            document_name=_sanitize_document_name(reg_row.get("Document Name", "")),
            file_name=reg_row.get("File Name", ""),
            business_id=reg_row.get("Business ID", ""),
            effective_document_date=eff_date,
            document_date_source=eff_date_source,
            effective_direction=eff_direction,
            direction_source=eff_direction_source,
            effective_requires_action=eff_requires_action,
            effective_has_expiration=eff_has_expiration,
            review_status=review_status,
            review_version=review_version,
            has_conflict=has_conflict,
            duplicate_status=content_row.get("Duplicate Status", "") or "",
            duplicate_of_document_id=content_row.get("Duplicate Of Document ID", "") or "",
            cache_warning=cache_warning,
        )
        entries.append((item, reg_row.get("Created At", "")))

    entries = _sort_entries(entries, criteria.sort)
    total_matches = len(entries)

    page = entries[criteria.offset:criteria.offset + criteria.limit]
    items = tuple(e[0] for e in page)

    return DocumentSearchResult(
        criteria=criteria,
        total_matches=total_matches,
        returned_count=len(items),
        offset=criteria.offset,
        limit=criteria.limit,
        items=items,
        warnings=tuple(warnings),
    )
