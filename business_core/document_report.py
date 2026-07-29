"""
Phase 16B.6: Business Document Report by Effective Fields.

Read-only, business-scoped AGGREGATE report over EFFECTIVE structured
fields (business_core.document_confirmation.EffectiveStructuredFields)
— reuses business_core.document_search.load_effective_document_records()
so there is exactly ONE bulk-read/join/effective-state-construction
implementation shared with /finddocs, never a second copy of that
contract.

Sheets calls for generate_document_report():
    1 read_business_sheet("biz_registry")       — business-existence check
    (only if the business exists, additionally:)
    1 read_business_sheet("document_registry")
    1 read_business_sheet("document_content")
    0 reads of document_field_reviews, 0 writes

The biz_registry read is a deliberate, documented exception to the
2-read search/report data budget established in Phase 16B.5 — it exists
solely to distinguish "business not found" from "business exists, zero
documents", a distinction /finddocs itself does not make (business_id
there is a pure filter with no existence check). If the business is not
found, document_registry/document_content are never read at all.

This module returns AGGREGATES ONLY — no Document ID, document/file
name, actor, raw extracted value, JSON payload, or audit event ever
appears in DocumentReportSummary or in the rendered Telegram output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ALLOWED_REPORT_PARAMS = frozenset({"business_id", "as_of", "include_duplicates"})

_DUPLICATE_STATUS_EXACT = "EXACT_DUPLICATE"

ERROR_BUSINESS_NOT_FOUND = "BUSINESS_NOT_FOUND"
ERROR_REPORT_INVARIANT_FAILED = "REPORT_INVARIANT_FAILED"


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass(frozen=True)
class DocumentReportCriteria:
    business_id: str
    as_of: str = ""              # always a resolved strict ISO date after parse_report_criteria()
    include_duplicates: bool = True


@dataclass(frozen=True)
class DocumentReportSummary:
    """All counts refer to the working set AFTER include_duplicates
    filtering has been applied — every section of the report relates to
    the same filtered total (Phase 16B.6 §5)."""
    total_documents: int

    review_unreviewed_count: int
    review_partially_confirmed_count: int
    review_confirmed_count: int
    review_rejected_count: int

    conflict_true_count: int
    conflict_unknown_count: int
    cache_warning_count: int

    requires_action_true_count: int
    requires_action_false_count: int
    requires_action_unknown_count: int

    has_expiration_true_count: int
    has_expiration_false_count: int
    has_expiration_unknown_count: int

    valid_until_present_count: int
    expired_count: int
    expires_7d_count: int
    expires_30d_count: int
    expires_later_count: int
    no_valid_until_count: int
    invalid_valid_until_count: int
    expiration_inconsistency_count: int

    exact_duplicate_count: int
    new_document_count: int
    unknown_duplicate_status_count: int

    skipped_row_count: int = 0


@dataclass(frozen=True)
class DocumentReportResult:
    """
    ok=False means summary is ALWAYS None — a failed report never
    exposes partial/inconsistent totals as if they were a successful
    result. error_code is "" on success, otherwise one of
    ERROR_BUSINESS_NOT_FOUND / ERROR_REPORT_INVARIANT_FAILED.

    warnings never contains a Document ID, name, or any other
    identifying value — only generic aggregate-level markers (e.g.
    malformed-row counts already folded into the summary itself).
    """
    criteria: DocumentReportCriteria
    ok: bool
    error_code: str
    summary: object  # DocumentReportSummary | None
    warnings: tuple
    generated_at: str
    source_counts: dict


def _parse_bool_param(name: str, raw: str) -> tuple:
    v = (raw or "").strip().lower()
    if v == "true":
        return True, None
    if v == "false":
        return False, None
    return None, f"{name} должен быть true или false."


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def parse_report_criteria(kv: dict, now_fn=None) -> tuple:
    """
    kv: an already-parsed key=value dict (e.g. from
    business_core.telegram_handlers._parse_kv_args()).

    now_fn: optional zero-arg callable returning a timezone-aware
    datetime, injected for deterministic tests — never monkeypatch the
    global datetime module. Defaults to datetime.now(timezone.utc).

    Returns (DocumentReportCriteria | None, error_message | None) — a
    non-None error always means criteria is None. Never raises.
    """
    unknown = sorted(k for k in kv if k not in ALLOWED_REPORT_PARAMS)
    if unknown:
        return None, f"Неизвестный параметр: {', '.join(unknown)}."

    business_id = (kv.get("business_id", "") or "").strip()
    if not business_id:
        return None, "business_id обязателен."
    if _has_control_characters(business_id):
        return None, "business_id содержит недопустимые символы."

    from business_core.document_intelligence import parse_exact_date

    as_of = (kv.get("as_of", "") or "").strip()
    if as_of:
        iso, _warn = parse_exact_date(as_of)
        if not iso:
            return None, f"Невалидная as_of: {as_of!r} (нужен точный формат YYYY-MM-DD)."
        as_of = iso
    else:
        now = now_fn() if now_fn is not None else datetime.now(timezone.utc)
        as_of = now.date().isoformat()

    include_duplicates = True
    if "include_duplicates" in kv:
        include_duplicates, err = _parse_bool_param("include_duplicates", kv["include_duplicates"])
        if err:
            return None, err

    return DocumentReportCriteria(
        business_id=business_id, as_of=as_of, include_duplicates=include_duplicates,
    ), None


def _classify_valid_until(raw_effective_value, as_of: str) -> tuple:
    """
    Returns (bucket, is_present, is_invalid) where bucket is one of
    "expired" | "expires_7d" | "expires_30d" | "expires_later" |
    "no_valid_until". is_present is True only for a successfully parsed
    ISO date. is_invalid is True only for a non-empty value that failed
    strict ISO parsing (defensive — the write-side pipeline already
    normalizes valid_until through parse_exact_date, so this should be
    rare/only reachable via out-of-band manual edits).
    """
    from business_core.document_intelligence import parse_exact_date

    value = (raw_effective_value or "").strip() if raw_effective_value else ""
    if not value:
        return "no_valid_until", False, False

    iso, _warn = parse_exact_date(value)
    if not iso:
        return "no_valid_until", False, True

    as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    vu_date = datetime.strptime(iso, "%Y-%m-%d").date()

    if vu_date < as_of_date:
        return "expired", True, False
    if as_of_date <= vu_date <= as_of_date + timedelta(days=7):
        return "expires_7d", True, False
    if as_of_date + timedelta(days=8) <= vu_date <= as_of_date + timedelta(days=30):
        return "expires_30d", True, False
    return "expires_later", True, False


def _invariants_hold(summary: DocumentReportSummary) -> bool:
    """
    Pure, independently-testable invariant check (Phase 16B.6 §6):
        review counts sum == total_documents
        requires_action counts sum == total_documents
        has_expiration counts sum == total_documents
        expiry-bucket counts sum == total_documents
    Never mutates, never raises. A single crafted DocumentReportSummary
    can be fed in directly to exercise the failure branch in tests,
    without needing to force an inconsistency through the full
    aggregation pipeline (which never produces one by construction).
    """
    total = summary.total_documents

    review_sum = (
        summary.review_unreviewed_count + summary.review_partially_confirmed_count
        + summary.review_confirmed_count + summary.review_rejected_count
    )
    ra_sum = (
        summary.requires_action_true_count + summary.requires_action_false_count
        + summary.requires_action_unknown_count
    )
    he_sum = (
        summary.has_expiration_true_count + summary.has_expiration_false_count
        + summary.has_expiration_unknown_count
    )
    expiry_sum = (
        summary.expired_count + summary.expires_7d_count + summary.expires_30d_count
        + summary.expires_later_count + summary.no_valid_until_count
    )

    return review_sum == total and ra_sum == total and he_sum == total and expiry_sum == total


def _business_exists(business_id: str) -> bool:
    """
    Strictly read-only business-existence check — deliberately NOT
    business_core.business_builder.get_business_config(), which calls
    business_core.sheets.get_business_sheet() internally and would
    auto-create BIZ_REGISTRY (with headers, via add_worksheet() +
    append_row()) as a side effect if the sheet were ever missing.

    business_sheet_exists() is checked FIRST and never triggers that
    auto-create path (Phase 16B.3 precedent) — if the sheet itself is
    missing, no business_id could possibly be registered in it, so this
    safely reports "not found" without ever calling read_business_sheet()
    (and therefore without ever risking get_business_sheet()'s
    auto-create branch).
    """
    from business_core.sheets import business_sheet_exists, read_business_sheet

    if not business_sheet_exists("biz_registry"):
        return False

    rows = read_business_sheet("biz_registry")
    return any((row.get("ID", "") or "") == business_id for row in rows)


def generate_document_report(criteria: DocumentReportCriteria) -> DocumentReportResult:
    """
    Read-only. See module docstring for the exact Sheets call budget.

    Raises SheetsQuotaExceededError/TransientSheetsReadError exactly
    like any other read in this codebase — callers (Telegram handlers)
    catch these the same way /docanalysis, /reviewdoc and /finddocs
    already do.
    """
    from business_core.document_search import load_effective_document_records

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if not _business_exists(criteria.business_id):
        return DocumentReportResult(
            criteria=criteria, ok=False, error_code=ERROR_BUSINESS_NOT_FOUND,
            summary=None, warnings=(), generated_at=generated_at,
            source_counts={"registry_rows": 0, "content_rows": 0},
        )

    records, loader_warnings = load_effective_document_records(criteria.business_id)
    warnings = list(loader_warnings)

    if not criteria.include_duplicates:
        records = [r for r in records if r.duplicate_status != _DUPLICATE_STATUS_EXACT]

    total_documents = len(records)

    review_counts = {"unreviewed": 0, "partially_confirmed": 0, "confirmed": 0, "rejected": 0}
    conflict_true = conflict_unknown = 0
    cache_warning_count = 0
    requires_action_true = requires_action_false = requires_action_unknown = 0
    has_expiration_true = has_expiration_false = has_expiration_unknown = 0
    valid_until_present = 0
    expired = expires_7d = expires_30d = expires_later = no_valid_until = 0
    invalid_valid_until = 0
    expiration_inconsistency = 0
    exact_duplicate = new_document = unknown_duplicate_status = 0
    skipped_row_count = 0

    for record in records:
        if record.review_status in review_counts:
            review_counts[record.review_status] += 1
        else:
            # defensive: loader already normalizes unknown statuses to
            # "unreviewed" with cache_warning=True, so this should be
            # unreachable — never drop the row silently either way.
            review_counts["unreviewed"] += 1

        if record.cache_warning:
            cache_warning_count += 1

        if record.has_conflict is True:
            conflict_true += 1
        elif record.has_conflict is None:
            conflict_unknown += 1

        effective = record.effective_fields
        if effective is None:
            requires_action_unknown += 1
            has_expiration_unknown += 1
            bucket = "no_valid_until"
            is_present = False
            is_invalid = False
        else:
            ra = effective.requires_action.effective_value
            if ra is True:
                requires_action_true += 1
            elif ra is False:
                requires_action_false += 1
            else:
                requires_action_unknown += 1

            he = effective.has_expiration.effective_value
            if he is True:
                has_expiration_true += 1
            elif he is False:
                has_expiration_false += 1
            else:
                has_expiration_unknown += 1

            vu_effective_value = effective.valid_until.effective_value
            bucket, is_present, is_invalid = _classify_valid_until(vu_effective_value, criteria.as_of)

            if he is False and bucket != "no_valid_until":
                expiration_inconsistency += 1
            elif he is True and bucket == "no_valid_until":
                expiration_inconsistency += 1

        if is_present:
            valid_until_present += 1
        if is_invalid:
            invalid_valid_until += 1

        if bucket == "expired":
            expired += 1
        elif bucket == "expires_7d":
            expires_7d += 1
        elif bucket == "expires_30d":
            expires_30d += 1
        elif bucket == "expires_later":
            expires_later += 1
        else:
            no_valid_until += 1

        if record.duplicate_status == _DUPLICATE_STATUS_EXACT:
            exact_duplicate += 1
        elif record.duplicate_status == "NEW_DOCUMENT":
            new_document += 1
        else:
            unknown_duplicate_status += 1

    summary = DocumentReportSummary(
        total_documents=total_documents,
        review_unreviewed_count=review_counts["unreviewed"],
        review_partially_confirmed_count=review_counts["partially_confirmed"],
        review_confirmed_count=review_counts["confirmed"],
        review_rejected_count=review_counts["rejected"],
        conflict_true_count=conflict_true,
        conflict_unknown_count=conflict_unknown,
        cache_warning_count=cache_warning_count,
        requires_action_true_count=requires_action_true,
        requires_action_false_count=requires_action_false,
        requires_action_unknown_count=requires_action_unknown,
        has_expiration_true_count=has_expiration_true,
        has_expiration_false_count=has_expiration_false,
        has_expiration_unknown_count=has_expiration_unknown,
        valid_until_present_count=valid_until_present,
        expired_count=expired,
        expires_7d_count=expires_7d,
        expires_30d_count=expires_30d,
        expires_later_count=expires_later,
        no_valid_until_count=no_valid_until,
        invalid_valid_until_count=invalid_valid_until,
        expiration_inconsistency_count=expiration_inconsistency,
        exact_duplicate_count=exact_duplicate,
        new_document_count=new_document,
        unknown_duplicate_status_count=unknown_duplicate_status,
        skipped_row_count=skipped_row_count,
    )

    if not _invariants_hold(summary):
        return DocumentReportResult(
            criteria=criteria, ok=False, error_code=ERROR_REPORT_INVARIANT_FAILED,
            summary=None, warnings=(),
            generated_at=generated_at,
            source_counts={"registry_rows": None, "content_rows": None},
        )

    return DocumentReportResult(
        criteria=criteria, ok=True, error_code="",
        summary=summary, warnings=tuple(warnings),
        generated_at=generated_at,
        source_counts={"records_count": total_documents},
    )
