"""
Phase 16C.2: Document Requirements Coverage (/docgaps).

Read-only composition of two already-existing, already-tested engines
— never a third independent implementation of matching/status/effective-
field logic:

  1. business_core.document_requirements (via a shared
     RequirementsReadContext) supplies base_status, matched_document_ids,
     required/blocking/minimum_count — completely unchanged, this module
     never re-implements matching, family/version supersession, or
     requirement-source precedence.
  2. business_core.document_search.load_effective_document_records()
     (given the SAME context's already-cached document_registry rows,
     via its `registry_rows=` parameter — Phase 16C.1B2) supplies
     review_status/has_conflict/cache_warning/duplicate_status/
     effective valid_until — completely unchanged, this module never
     re-implements effective-field parsing or conflict detection.

base_status is a direct, exhaustively-mapped passthrough of the
requirements engine's own DocumentRequirementStatus.status — an
unrecognized engine status value is a typed failure (ERROR_UNKNOWN_
ENGINE_STATUS), never a silent fallback, so this module can never
silently disagree with the Completion Gate about what "missing" means.

quality_flags (needs_review/conflict/expired/duplicate_only/
cache_warning/invalid_expiry) are an ADDITIONAL, orthogonal signal
layered on top of base_status — they never change base_status and
never imply anything about whether a stage transition would be
blocked. Only business_core.document_requirements' own
blocking_missing/is_complete concepts govern that.

Sheets calls: at most 5 distinct-sheet reads from the requirements
engine (roadmaps, roadmap_stages, stage_entity_relations,
document_template_registry, document_registry — see
business_core.document_requirements.RequirementsReadContext), plus at
most 1 more (document_content) from the effective-document loader —
DOCUMENT_REGISTRY is never read twice, DOCUMENT_FIELD_REVIEWS is never
read at all, and the effective loader is skipped entirely when no
requirement in scope has any matched document (nothing to enrich).
Zero writes anywhere in this module.

Privacy: DocumentCoverageItem/DocumentCoverageSummary/warnings never
carry a Document ID, document/file name, actor, raw JSON, Drive URL,
or hash — only requirement names, stage IDs, counts, and flag labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from business_core.document_requirements import (
    STATUS_PRESENT, STATUS_MISSING, STATUS_PARTIAL, STATUS_OPTIONAL_MISSING,
    RequirementsReadContext, evaluate_stage_requirements, evaluate_roadmap_requirements,
)

ALLOWED_COVERAGE_PARAMS = frozenset({"roadmap_id", "stage_id", "include_optional", "as_of"})

_EXACT_DUPLICATE = "EXACT_DUPLICATE"

# Phase 16C.2 §4 (corrected per the STATUS_NOT_APPLICABLE audit):
# exhaustive, explicit mapping from the requirements engine's own
# status constants to this module's base_status vocabulary — never a
# bare string-literal comparison. STATUS_NOT_APPLICABLE is deliberately
# NOT mapped here: a full re-read of business_core.document_requirements
# ._evaluate_requirement() (the sole producer of DocumentRequirementStatus
# .status) confirms it never assigns STATUS_NOT_APPLICABLE — the
# constant exists only as a defensive value _summarize() excludes from
# its own counting, never something the engine actually returns today.
# Treating it as unreachable (Variant A) means any occurrence — today
# impossible, but never assumed impossible forever — falls through to
# the same ERROR_UNKNOWN_ENGINE_STATUS typed failure as a genuinely
# unrecognized status, rather than silently inventing counting/ordering/
# rendering rules for a status this module has never observed and
# cannot test against real engine behavior.
_ENGINE_STATUS_TO_BASE_STATUS = {
    STATUS_PRESENT: "present",
    STATUS_MISSING: "missing",
    STATUS_PARTIAL: "partial",
    STATUS_OPTIONAL_MISSING: "optional_missing",
}

_REVIEW_STATUS_CONFIRMED = "confirmed"
_REVIEW_STATUS_NEEDS_REVIEW_VALUES = frozenset({"unreviewed", "partially_confirmed", "rejected"})
_KNOWN_REVIEW_STATUSES = frozenset({"unreviewed", "partially_confirmed", "confirmed", "rejected"})

ERROR_ROADMAP_NOT_FOUND = "ROADMAP_NOT_FOUND"
ERROR_ROADMAP_MISSING_BUSINESS_ID = "ROADMAP_MISSING_BUSINESS_ID"
ERROR_STAGE_NOT_FOUND = "STAGE_NOT_FOUND"
ERROR_STAGE_NOT_IN_ROADMAP = "STAGE_NOT_IN_ROADMAP"
ERROR_UNKNOWN_ENGINE_STATUS = "UNKNOWN_ENGINE_STATUS"
ERROR_COVERAGE_CONFIGURATION_ERROR = "COVERAGE_CONFIGURATION_ERROR"
ERROR_COVERAGE_INVARIANT_FAILED = "COVERAGE_INVARIANT_FAILED"


@dataclass(frozen=True)
class DocumentCoverageCriteria:
    roadmap_id: str
    stage_id: str = ""
    include_optional: bool = False
    as_of: str = ""


@dataclass(frozen=True)
class DocumentCoverageItem:
    requirement_id: str
    requirement_name: str
    stage_id: str
    required: bool
    blocking: bool
    minimum_count: int
    base_status: str
    matched_document_count: int
    canonical_document_count: int
    exact_duplicate_matched_count: int
    unmatched_document_count: int
    quality_flags: tuple = ()
    warning_count: int = 0
    # Phase 16C.3: additive per-category counters, surfaced from the
    # exact same _quality_for_item() computation that already derives
    # quality_flags — never a second analysis pass. Each canonical
    # document falls into exactly one review bucket (fully_confirmed_
    # count vs needs_review_count) and exactly one expiry bucket
    # (valid/expired/unknown/invalid_expiry_count), so
    # valid_expiry_count + expired_document_count + unknown_expiry_count
    # + invalid_expiry_count == canonical_document_count always holds.
    fully_confirmed_count: int = 0
    needs_review_count: int = 0
    conflict_document_count: int = 0
    cache_warning_document_count: int = 0
    valid_expiry_count: int = 0
    expired_document_count: int = 0
    unknown_expiry_count: int = 0
    invalid_expiry_count: int = 0
    business_id: str = ""
    document_template_id: str = ""


@dataclass(frozen=True)
class DocumentCoverageSummary:
    total_requirements: int
    required_count: int
    optional_count: int
    present_count: int
    missing_count: int
    partial_count: int
    optional_missing_count: int
    blocking_missing_count: int
    needs_review_count: int
    conflict_count: int
    expired_count: int
    duplicate_only_count: int
    cache_warning_count: int
    invalid_expiry_count: int
    unmatched_document_count: int = 0


@dataclass(frozen=True)
class DocumentCoverageResult:
    criteria: DocumentCoverageCriteria
    ok: bool
    error_code: str
    summary: object  # DocumentCoverageSummary | None
    items: tuple
    warnings: tuple
    generated_at: str


def _parse_bool_param(name: str, raw: str) -> tuple:
    v = (raw or "").strip().lower()
    if v == "true":
        return True, None
    if v == "false":
        return False, None
    return None, f"{name} должен быть true или false."


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def parse_coverage_criteria(kv: dict, now_fn=None) -> tuple:
    """
    Returns (DocumentCoverageCriteria | None, error_message | None).
    Never raises. Mirrors business_core.document_report
    .parse_report_criteria()'s exact validation style.
    """
    unknown = sorted(k for k in kv if k not in ALLOWED_COVERAGE_PARAMS)
    if unknown:
        return None, f"Неизвестный параметр: {', '.join(unknown)}."

    roadmap_id = (kv.get("roadmap_id", "") or "").strip()
    if not roadmap_id:
        return None, "roadmap_id обязателен."
    if _has_control_characters(roadmap_id):
        return None, "roadmap_id содержит недопустимые символы."

    stage_id = (kv.get("stage_id", "") or "").strip()
    if stage_id and _has_control_characters(stage_id):
        return None, "stage_id содержит недопустимые символы."

    include_optional = False
    if "include_optional" in kv:
        include_optional, err = _parse_bool_param("include_optional", kv["include_optional"])
        if err:
            return None, err

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

    return DocumentCoverageCriteria(
        roadmap_id=roadmap_id, stage_id=stage_id, include_optional=include_optional, as_of=as_of,
    ), None


def _classify_valid_until(raw_effective_value, as_of: str) -> str:
    """
    Pure. Never reads Sheets, never uses the current wall-clock time —
    `as_of` is always supplied explicitly by the caller. Returns one of
    "valid" | "expired" | "unknown" | "invalid":
      - "unknown": no valid_until value at all — NOT evidence of
        validity (Phase 16C.2 §1 correction: absence is never treated
        as "valid").
      - "invalid": a non-empty value that fails strict ISO parsing —
        never counted as valid or expired, never hides the document.
      - "valid"/"expired": a successfully parsed ISO date, compared
        directly against `as_of` (both YYYY-MM-DD strings, safely
        comparable lexicographically).

    Deliberately a small, local, independently-tested implementation
    rather than importing business_core.document_report's private
    _classify_valid_until() — that function is out of this phase's
    approved scope and returns a different (bucketed) vocabulary this
    module doesn't need.
    """
    from business_core.document_intelligence import parse_exact_date

    value = (raw_effective_value or "").strip() if raw_effective_value else ""
    if not value:
        return "unknown"

    iso, _warn = parse_exact_date(value)
    if not iso:
        return "invalid"

    return "valid" if iso >= as_of else "expired"


def _quality_for_item(matched_document_ids: tuple, effective_by_id: dict, minimum_count: int, base_status: str, as_of: str) -> dict:
    """
    Pure. Returns a dict of computed per-item quality metrics — never
    touches Sheets, never mutates its inputs.
    """
    canonical_count = 0
    exact_duplicate_matched_count = 0
    unmatched_document_count = 0
    needs_review = False
    conflict = False
    cache_warning = False
    valid_count = 0
    expired_count = 0
    unknown_expiry_count = 0
    invalid_expiry_count = 0

    # Phase 16C.3: per-document counters for /docgap's drill-down —
    # each contributes to at most one of fully_confirmed/needs_review,
    # and cache_warning_document_count counts a document ONCE even if
    # multiple of its own signals (cache_warning flag, has_conflict is
    # None, unknown review status) would independently qualify it.
    fully_confirmed_count = 0
    needs_review_count = 0
    conflict_document_count = 0
    cache_warning_document_count = 0

    for doc_id in matched_document_ids:
        rec = effective_by_id.get(doc_id)
        if rec is None:
            # Phase 16C.2 §3: never record the Document ID itself —
            # only an aggregate count. Structurally should be
            # unreachable (same roadmap -> same business_id -> same
            # registry snapshot both engines share), but handled
            # defensively rather than assumed.
            unmatched_document_count += 1
            cache_warning = True
            continue

        doc_cache_warning = rec.cache_warning or rec.has_conflict is None
        if doc_cache_warning:
            cache_warning = True

        if rec.duplicate_status == _EXACT_DUPLICATE:
            exact_duplicate_matched_count += 1
            if doc_cache_warning:
                cache_warning_document_count += 1
            continue  # exact duplicates are never canonical evidence

        canonical_count += 1

        if rec.has_conflict is True:
            conflict = True
            conflict_document_count += 1

        review_status = rec.review_status
        doc_needs_review = False
        if review_status in _REVIEW_STATUS_NEEDS_REVIEW_VALUES:
            needs_review = True
            doc_needs_review = True
        elif review_status not in _KNOWN_REVIEW_STATUSES:
            # Phase 16C.2 §6: an unrecognized status is never silently
            # treated as confirmed — flag both needs_review and a safe
            # cache warning.
            needs_review = True
            doc_needs_review = True
            cache_warning = True
            doc_cache_warning = True
        # else: "confirmed" -> no needs_review contribution from this document

        if doc_needs_review:
            needs_review_count += 1
        else:
            fully_confirmed_count += 1

        if doc_cache_warning:
            cache_warning_document_count += 1

        raw_valid_until = None
        if rec.effective_fields is not None:
            raw_valid_until = rec.effective_fields.valid_until.effective_value
        classification = _classify_valid_until(raw_valid_until, as_of)
        if classification == "valid":
            valid_count += 1
        elif classification == "expired":
            expired_count += 1
        elif classification == "unknown":
            unknown_expiry_count += 1
        else:
            invalid_expiry_count += 1

    flags: list = []
    if valid_count < minimum_count and expired_count > 0:
        flags.append("expired")
    if invalid_expiry_count > 0:
        flags.append("invalid_expiry")
    if needs_review:
        flags.append("needs_review")
    if conflict:
        flags.append("conflict")
    if cache_warning:
        flags.append("cache_warning")
    if (
        base_status in ("present", "partial")
        and canonical_count < minimum_count
        and exact_duplicate_matched_count > 0
    ):
        flags.append("duplicate_only")

    return {
        "canonical_document_count": canonical_count,
        "exact_duplicate_matched_count": exact_duplicate_matched_count,
        "unmatched_document_count": unmatched_document_count,
        "quality_flags": tuple(flags),
        "warning_count": unmatched_document_count,
        "fully_confirmed_count": fully_confirmed_count,
        "needs_review_count": needs_review_count,
        "conflict_document_count": conflict_document_count,
        "cache_warning_document_count": cache_warning_document_count,
        "valid_expiry_count": valid_count,
        "expired_document_count": expired_count,
        "unknown_expiry_count": unknown_expiry_count,
        "invalid_expiry_count": invalid_expiry_count,
    }


_ORDER_BUCKETS = {
    "missing": 1,
    "partial": 2,
    "present_required_flagged": 3,
    "present_required_clean": 4,
    "optional_missing": 5,
    "present_optional_flagged": 6,
    "present_optional_clean": 7,
}


def _bucket_for(item: DocumentCoverageItem) -> int:
    if item.required and item.base_status == "missing":
        return _ORDER_BUCKETS["missing"]
    if item.required and item.base_status == "partial":
        return _ORDER_BUCKETS["partial"]
    if item.base_status == "optional_missing":
        return _ORDER_BUCKETS["optional_missing"]
    if item.required:
        return _ORDER_BUCKETS["present_required_flagged"] if item.quality_flags else _ORDER_BUCKETS["present_required_clean"]
    return _ORDER_BUCKETS["present_optional_flagged"] if item.quality_flags else _ORDER_BUCKETS["present_optional_clean"]


def generate_document_coverage(criteria: DocumentCoverageCriteria) -> DocumentCoverageResult:
    """
    Read-only. See module docstring for the exact Sheets call budget.

    Raises SheetsQuotaExceededError/TransientSheetsReadError exactly
    like any other read in this codebase — callers (Telegram handlers)
    catch these the same way /docreport//finddocs already do.
    """
    from business_core.document_search import load_effective_document_records

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    warnings: list = []

    context = RequirementsReadContext()

    roadmap_row = context.roadmap_by_id(criteria.roadmap_id)
    if roadmap_row is None:
        return DocumentCoverageResult(
            criteria=criteria, ok=False, error_code=ERROR_ROADMAP_NOT_FOUND,
            summary=None, items=(), warnings=(), generated_at=generated_at,
        )

    business_id = roadmap_row.get("Business ID", "")
    if not business_id:
        return DocumentCoverageResult(
            criteria=criteria, ok=False, error_code=ERROR_ROADMAP_MISSING_BUSINESS_ID,
            summary=None, items=(), warnings=(), generated_at=generated_at,
        )

    if criteria.stage_id:
        stage_row = context.roadmap_stage_by_id(criteria.stage_id)
        if stage_row is None:
            return DocumentCoverageResult(
                criteria=criteria, ok=False, error_code=ERROR_STAGE_NOT_FOUND,
                summary=None, items=(), warnings=(), generated_at=generated_at,
            )
        if stage_row.get("Roadmap ID", "") != criteria.roadmap_id:
            return DocumentCoverageResult(
                criteria=criteria, ok=False, error_code=ERROR_STAGE_NOT_IN_ROADMAP,
                summary=None, items=(), warnings=(), generated_at=generated_at,
            )
        engine_summary = evaluate_stage_requirements(criteria.stage_id, read_context=context)
    else:
        engine_summary = evaluate_roadmap_requirements(criteria.roadmap_id, read_context=context)

    if engine_summary.has_configuration_errors:
        # A broken STAGE_ENTITY_RELATIONS row (invalid/dangling/duplicate)
        # means the requirements engine's own totals for this scope are
        # not trustworthy — never render a normal coverage report, and
        # never let a partial/inconsistent total slip through as if it
        # were a clean result. The only detail ever surfaced is a single
        # safe, content-free aggregate code — relation IDs, template
        # IDs, row payloads, and raw error text (all present on
        # engine_summary.configuration_errors) are deliberately never
        # read out of that tuple here.
        return DocumentCoverageResult(
            criteria=criteria, ok=False, error_code=ERROR_COVERAGE_CONFIGURATION_ERROR,
            summary=None, items=(), warnings=("REQUIREMENTS_CONFIGURATION_ERROR",),
            generated_at=generated_at,
        )

    filtered_statuses = [
        s for s in engine_summary.items
        if criteria.include_optional or s.requirement.required
    ]

    mapped: list = []
    for status in filtered_statuses:
        base_status = _ENGINE_STATUS_TO_BASE_STATUS.get(status.status)
        if base_status is None:
            return DocumentCoverageResult(
                criteria=criteria, ok=False, error_code=ERROR_UNKNOWN_ENGINE_STATUS,
                summary=None, items=(), warnings=(), generated_at=generated_at,
            )
        mapped.append((status, base_status))

    needs_effective_layer = any(status.matched_document_ids for status, _ in mapped)

    effective_by_id: dict = {}
    if needs_effective_layer:
        registry_rows = context.sheet_rows.get("document_registry")
        records, loader_warnings = load_effective_document_records(
            business_id, registry_rows=registry_rows,
        )
        warnings.extend(loader_warnings)
        effective_by_id = {r.document_id: r for r in records}

    items: list = []
    for status, base_status in mapped:
        req = status.requirement
        quality = _quality_for_item(
            status.matched_document_ids, effective_by_id, req.minimum_count, base_status, criteria.as_of,
        )
        items.append(DocumentCoverageItem(
            requirement_id=req.requirement_id,
            requirement_name=req.name or req.document_template_id,
            stage_id=req.stage_id,
            required=req.required,
            blocking=req.blocking,
            minimum_count=req.minimum_count,
            base_status=base_status,
            matched_document_count=status.matched_count,
            canonical_document_count=quality["canonical_document_count"],
            exact_duplicate_matched_count=quality["exact_duplicate_matched_count"],
            unmatched_document_count=quality["unmatched_document_count"],
            quality_flags=quality["quality_flags"],
            warning_count=quality["warning_count"],
            fully_confirmed_count=quality["fully_confirmed_count"],
            needs_review_count=quality["needs_review_count"],
            conflict_document_count=quality["conflict_document_count"],
            cache_warning_document_count=quality["cache_warning_document_count"],
            valid_expiry_count=quality["valid_expiry_count"],
            expired_document_count=quality["expired_document_count"],
            unknown_expiry_count=quality["unknown_expiry_count"],
            invalid_expiry_count=quality["invalid_expiry_count"],
            business_id=req.business_id,
            document_template_id=req.document_template_id,
        ))

    total_requirements = len(items)
    required_count = sum(1 for i in items if i.required)
    optional_count = total_requirements - required_count
    present_count = sum(1 for i in items if i.base_status == "present")
    missing_count = sum(1 for i in items if i.base_status == "missing")
    partial_count = sum(1 for i in items if i.base_status == "partial")
    optional_missing_count = sum(1 for i in items if i.base_status == "optional_missing")
    blocking_missing_count = sum(
        1 for i in items if i.blocking and i.base_status in ("missing", "partial")
    )
    needs_review_count = sum(1 for i in items if "needs_review" in i.quality_flags)
    conflict_count = sum(1 for i in items if "conflict" in i.quality_flags)
    expired_count = sum(1 for i in items if "expired" in i.quality_flags)
    duplicate_only_count = sum(1 for i in items if "duplicate_only" in i.quality_flags)
    cache_warning_count = sum(1 for i in items if "cache_warning" in i.quality_flags)
    invalid_expiry_count = sum(1 for i in items if "invalid_expiry" in i.quality_flags)
    unmatched_document_count = sum(i.unmatched_document_count for i in items)

    if (
        present_count + missing_count + partial_count + optional_missing_count != total_requirements
        or required_count + optional_count != total_requirements
    ):
        return DocumentCoverageResult(
            criteria=criteria, ok=False, error_code=ERROR_COVERAGE_INVARIANT_FAILED,
            summary=None, items=(), warnings=(), generated_at=generated_at,
        )

    summary = DocumentCoverageSummary(
        total_requirements=total_requirements,
        required_count=required_count,
        optional_count=optional_count,
        present_count=present_count,
        missing_count=missing_count,
        partial_count=partial_count,
        optional_missing_count=optional_missing_count,
        blocking_missing_count=blocking_missing_count,
        needs_review_count=needs_review_count,
        conflict_count=conflict_count,
        expired_count=expired_count,
        duplicate_only_count=duplicate_only_count,
        cache_warning_count=cache_warning_count,
        invalid_expiry_count=invalid_expiry_count,
        unmatched_document_count=unmatched_document_count,
    )

    # Stable sort by bucket only — Python's sort() is stable, so ties
    # within one bucket keep their original list order, which is
    # already the requirements engine's own deterministic stage-then-
    # requirement order (built directly from evaluate_*_requirements()'s
    # own item order, never re-derived). requirement_id is unique per
    # requirement, so it can never actually break a tie here — it
    # exists in the spec as a documented, never-triggered safety net,
    # not a discriminator this sort needs to apply.
    items.sort(key=_bucket_for)

    return DocumentCoverageResult(
        criteria=criteria, ok=True, error_code="",
        summary=summary, items=tuple(items), warnings=tuple(warnings), generated_at=generated_at,
    )
