"""
Phase 16C.3: Requirement Coverage Drill-Down (/docgap).

Pure selector/formatter over an already-computed
business_core.document_coverage.DocumentCoverageResult — never a third
requirements/effective engine. This module never reads Sheets/Drive
itself: it calls generate_document_coverage() exactly ONCE (with
include_optional=True, so an optional requirement is never missed
before the lookup even starts) and then does a pure in-memory
requirement_id lookup over the already-returned items.

Requirement ID contract (business_core.document_requirements):
requirement_id = f"{stage_id}:{document_template_id}", produced by
both _build_requirement() and _build_requirement_from_relation(). This
is structurally unique within one roadmap's coverage result — each
stage de-duplicates its own Document Template IDs (legacy comma-list)
or Entity IDs (instance relations, duplicates excluded as a
configuration error) before building requirements, and distinct stages
never share a Stage ID. Ambiguity is therefore not reachable via any
data this engine can currently produce — but AMBIGUOUS_REQUIREMENT_ID
is still checked defensively (never assumed impossible forever) rather
than silently picking the first match.

Privacy: DocumentGapDetail never carries a Document ID, Document
Family ID, document/file name, Drive ID/URL, hash, extracted text, AI
summary, raw structured field payload, actor, review event, relation
ID, or raw configuration-error/warning text — only the requirement
name, stage ID, and aggregate counts already present on
DocumentCoverageItem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

ALLOWED_GAP_DETAIL_PARAMS = frozenset({"roadmap_id", "requirement_id", "as_of"})

ERROR_REQUIREMENT_NOT_FOUND = "REQUIREMENT_NOT_FOUND"
ERROR_AMBIGUOUS_REQUIREMENT_ID = "AMBIGUOUS_REQUIREMENT_ID"


@dataclass(frozen=True)
class DocumentGapDetailCriteria:
    roadmap_id: str
    requirement_id: str
    as_of: str = ""


@dataclass(frozen=True)
class DocumentGapDetail:
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
    fully_confirmed_count: int
    needs_review_count: int
    conflict_document_count: int
    cache_warning_document_count: int
    valid_expiry_count: int
    expired_document_count: int
    unknown_expiry_count: int
    invalid_expiry_count: int
    quality_flags: tuple = ()


@dataclass(frozen=True)
class DocumentGapDetailResult:
    criteria: DocumentGapDetailCriteria
    ok: bool
    error_code: str
    detail: object  # DocumentGapDetail | None
    warnings: tuple
    generated_at: str


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def parse_gap_detail_criteria(kv: dict, now_fn=None) -> tuple:
    """
    Returns (DocumentGapDetailCriteria | None, error_message | None).
    Never raises. Mirrors business_core.document_coverage
    .parse_coverage_criteria()'s exact validation style.

    requirement_id is validated only for emptiness/control characters —
    no new regex is introduced, since its shape (stage_id:template_id,
    containing a colon) is entirely produced by the requirements
    engine, never independently re-validated here.
    """
    unknown = sorted(k for k in kv if k not in ALLOWED_GAP_DETAIL_PARAMS)
    if unknown:
        return None, f"Неизвестный параметр: {', '.join(unknown)}."

    roadmap_id = (kv.get("roadmap_id", "") or "").strip()
    if not roadmap_id:
        return None, "roadmap_id обязателен."
    if _has_control_characters(roadmap_id):
        return None, "roadmap_id содержит недопустимые символы."

    requirement_id = (kv.get("requirement_id", "") or "").strip()
    if not requirement_id:
        return None, "requirement_id обязателен."
    if _has_control_characters(requirement_id):
        return None, "requirement_id содержит недопустимые символы."

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

    return DocumentGapDetailCriteria(
        roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of,
    ), None


def generate_document_gap_detail(criteria: DocumentGapDetailCriteria) -> DocumentGapDetailResult:
    """
    Read-only. Calls business_core.document_coverage
    .generate_document_coverage() exactly once — same call budget as
    /docgaps (max 6 distinct-sheet reads, 0 DOCUMENT_FIELD_REVIEWS, 0
    writes). No second requirements/effective evaluation, no direct
    Sheets access here.

    Raises SheetsQuotaExceededError/TransientSheetsReadError exactly
    like any other read in this codebase — propagated from
    generate_document_coverage(), which propagates them from
    read_business_sheet() in turn.
    """
    from business_core.document_coverage import (
        DocumentCoverageCriteria, generate_document_coverage,
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    coverage_criteria = DocumentCoverageCriteria(
        roadmap_id=criteria.roadmap_id, include_optional=True, as_of=criteria.as_of,
    )
    coverage_result = generate_document_coverage(coverage_criteria)

    if not coverage_result.ok:
        # Verbatim passthrough of the coverage layer's own error code —
        # never a second version of ROADMAP_NOT_FOUND/
        # ROADMAP_MISSING_BUSINESS_ID/UNKNOWN_ENGINE_STATUS/
        # COVERAGE_CONFIGURATION_ERROR/COVERAGE_INVARIANT_FAILED, and
        # never any of coverage_result's own (already-safe, code-only)
        # warnings copied into this result.
        return DocumentGapDetailResult(
            criteria=criteria, ok=False, error_code=coverage_result.error_code,
            detail=None, warnings=(), generated_at=generated_at,
        )

    matches = [i for i in coverage_result.items if i.requirement_id == criteria.requirement_id]

    if not matches:
        return DocumentGapDetailResult(
            criteria=criteria, ok=False, error_code=ERROR_REQUIREMENT_NOT_FOUND,
            detail=None, warnings=(), generated_at=generated_at,
        )
    if len(matches) > 1:
        return DocumentGapDetailResult(
            criteria=criteria, ok=False, error_code=ERROR_AMBIGUOUS_REQUIREMENT_ID,
            detail=None, warnings=(), generated_at=generated_at,
        )

    item = matches[0]
    detail = DocumentGapDetail(
        requirement_id=item.requirement_id,
        requirement_name=item.requirement_name,
        stage_id=item.stage_id,
        required=item.required,
        blocking=item.blocking,
        minimum_count=item.minimum_count,
        base_status=item.base_status,
        matched_document_count=item.matched_document_count,
        canonical_document_count=item.canonical_document_count,
        exact_duplicate_matched_count=item.exact_duplicate_matched_count,
        unmatched_document_count=item.unmatched_document_count,
        fully_confirmed_count=item.fully_confirmed_count,
        needs_review_count=item.needs_review_count,
        conflict_document_count=item.conflict_document_count,
        cache_warning_document_count=item.cache_warning_document_count,
        valid_expiry_count=item.valid_expiry_count,
        expired_document_count=item.expired_document_count,
        unknown_expiry_count=item.unknown_expiry_count,
        invalid_expiry_count=item.invalid_expiry_count,
        quality_flags=item.quality_flags,
    )

    return DocumentGapDetailResult(
        criteria=criteria, ok=True, error_code="",
        detail=detail, warnings=(), generated_at=generated_at,
    )
