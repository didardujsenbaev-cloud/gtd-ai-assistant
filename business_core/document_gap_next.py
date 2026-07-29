"""
Phase 16C.6: Safe Next Action for Document Gap (/docgapnext).

Pure action-selection layer over an already-computed
business_core.document_gap_detail.DocumentGapDetailResult — never a
third requirements/effective engine, never a Sheets/Drive read of its
own. This module calls generate_document_gap_detail() exactly ONCE and
derives a deterministic, generic-fallback-only recommendation from its
already-returned base_status/quality_flags/blocking/required fields.

Generic-fallback-only (Phase 16C.6 v1): no document_template_registry
Description/Notes, no stage Notes/Description, no SOP prose, no
Service Catalog free text, no LLM generation, no fuzzy inference — none
of these exist as a deterministic, per-requirement instruction source
today (see the Phase 16C.6 audit), so every action's instruction text
is a fixed, reviewed string keyed only by base_status/quality_flag.
Template-specific guidance is an explicit, separate future phase.

Priority model: base_status decides the PRIMARY action first (missing/
partial/optional_missing dominate — there's nothing else to recommend
until the document exists); only when base_status == "present" do
quality_flags decide the primary action, in the fixed priority
duplicate_only > expired > conflict > needs_review > invalid_expiry >
cache_warning. Every other known flag present becomes a SECONDARY
action in the same priority order — never hidden. Flag de-duplication
and priority-ordering happen before any action is built, so the same
set of flags in a different input order always produces an identical
result (Phase 16C.6 §9).

Privacy: DocumentGapNextResult never carries a Document ID, Document
Family ID, document/file name, Drive ID/URL, hash, extracted text,
structured value, AI summary, actor, review event, relation ID, or raw
warning/configuration-error text — only Requirement ID, requirement
name, roadmap/stage ID, base status, safe action codes/text, and
follow-up commands (rendered at the Telegram layer, not stored here).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

ALLOWED_GAP_NEXT_PARAMS = frozenset({"roadmap_id", "requirement_id", "as_of"})

ERROR_UNSUPPORTED_BASE_STATUS = "UNSUPPORTED_BASE_STATUS"
ERROR_UNSUPPORTED_QUALITY_FLAG = "UNSUPPORTED_QUALITY_FLAG"

_KNOWN_BASE_STATUSES = frozenset({"missing", "partial", "optional_missing", "present"})
_KNOWN_QUALITY_FLAGS = frozenset({
    "duplicate_only", "expired", "conflict", "needs_review", "invalid_expiry", "cache_warning",
})

# Fixed priority order for quality-flag-driven actions when base_status == "present".
_QUALITY_FLAG_PRIORITY = (
    "duplicate_only", "expired", "conflict", "needs_review", "invalid_expiry", "cache_warning",
)


@dataclass(frozen=True)
class DocumentGapNextCriteria:
    roadmap_id: str
    requirement_id: str
    as_of: str = ""


@dataclass(frozen=True)
class DocumentGapNextAction:
    action_code: str
    instruction_lines: tuple = ()


@dataclass(frozen=True)
class DocumentGapNextResult:
    criteria: DocumentGapNextCriteria
    ok: bool
    error_code: str
    requirement_name: str
    stage_id: str
    base_status: str
    blocking: bool
    required: bool
    quality_flags: tuple
    primary_action: object  # DocumentGapNextAction | None
    secondary_actions: tuple
    warnings: tuple
    generated_at: str


_BASE_STATUS_ACTIONS = {
    "missing": DocumentGapNextAction(
        action_code="OBTAIN_MISSING_DOCUMENT",
        instruction_lines=(
            "Получить требуемый документ.",
            "Загрузить его в систему.",
            "Повторно проверить требование через /docgap.",
        ),
    ),
    "partial": DocumentGapNextAction(
        action_code="OBTAIN_REMAINING_DOCUMENTS",
        instruction_lines=(
            "Получить недостающее количество документов.",
            "Загрузить их в систему.",
            "Повторно проверить требование через /docgap.",
        ),
    ),
    "optional_missing": DocumentGapNextAction(
        action_code="OPTIONAL_DOCUMENT_NOT_PROVIDED",
        instruction_lines=(
            "Решить, нужен ли опциональный документ для этого объекта.",
            "При необходимости получить и загрузить его.",
            "Повторно проверить требование через /docgap.",
        ),
    ),
}

_NO_ACTION_REQUIRED = DocumentGapNextAction(
    action_code="NO_ACTION_REQUIRED",
    instruction_lines=(
        "Дополнительных действий по текущему состоянию не требуется.",
        "При изменении документа повторно проверить требование.",
    ),
)

_QUALITY_FLAG_ACTIONS = {
    "duplicate_only": DocumentGapNextAction(
        action_code="UPLOAD_CANONICAL_DOCUMENT",
        instruction_lines=(
            "Загрузить отдельный документ, а не точную копию уже существующего файла.",
            "Повторно проверить требование.",
        ),
    ),
    "expired": DocumentGapNextAction(
        action_code="OBTAIN_CURRENT_DOCUMENT",
        instruction_lines=(
            "Получить актуальную версию документа или продлить срок действия.",
            "Загрузить актуальный документ.",
            "Повторно проверить требование.",
        ),
    ),
    "conflict": DocumentGapNextAction(
        action_code="RESOLVE_STRUCTURED_DATA_CONFLICT",
        instruction_lines=(
            "Проверить конфликтующие значения.",
            "Подтвердить корректное значение или исправить structured data.",
            "Повторно проверить требование.",
        ),
    ),
    "needs_review": DocumentGapNextAction(
        action_code="CONFIRM_STRUCTURED_DATA",
        instruction_lines=(
            "Проверить извлечённые structured data.",
            "Подтвердить или исправить значения.",
            "Повторно проверить требование.",
        ),
    ),
    "invalid_expiry": DocumentGapNextAction(
        action_code="FIX_EXPIRY_DATE",
        instruction_lines=(
            "Проверить значение срока действия.",
            "Исправить некорректную дату.",
            "Повторно проверить требование.",
        ),
    ),
    "cache_warning": DocumentGapNextAction(
        action_code="RECHECK_QUALITY_DATA",
        instruction_lines=(
            "Повторно проверить quality-данные документа.",
            "Убедиться, что structured data обработаны корректно.",
            "Повторно проверить требование.",
        ),
    ),
}


def _has_control_characters(text: str) -> bool:
    return any(ord(ch) < 32 and ch not in ("\t",) for ch in text)


def parse_gap_next_criteria(kv: dict, now_fn=None) -> tuple:
    """
    Returns (DocumentGapNextCriteria | None, error_message | None).
    Never raises. Mirrors business_core.document_gap_detail
    .parse_gap_detail_criteria()'s exact validation style.
    """
    unknown = sorted(k for k in kv if k not in ALLOWED_GAP_NEXT_PARAMS)
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

    return DocumentGapNextCriteria(
        roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of,
    ), None


def _select_actions(base_status: str, quality_flags: tuple) -> tuple:
    """
    Pure. Returns (primary_action, secondary_actions_tuple). Assumes
    base_status and every flag in quality_flags have already been
    validated as known — callers must check that first.

    Determinism (Phase 16C.6 §9): flags are de-duplicated and then
    walked in the FIXED _QUALITY_FLAG_PRIORITY order, never in the
    order they appear in the input tuple — so any permutation of the
    same flag set produces an identical result.
    """
    unique_flags = set(quality_flags)
    ordered_flags = [f for f in _QUALITY_FLAG_PRIORITY if f in unique_flags]

    if base_status in ("missing", "partial", "optional_missing"):
        primary = _BASE_STATUS_ACTIONS[base_status]
        secondary = tuple(_QUALITY_FLAG_ACTIONS[f] for f in ordered_flags)
        return primary, secondary

    # base_status == "present"
    if not ordered_flags:
        return _NO_ACTION_REQUIRED, ()
    primary = _QUALITY_FLAG_ACTIONS[ordered_flags[0]]
    secondary = tuple(_QUALITY_FLAG_ACTIONS[f] for f in ordered_flags[1:])
    return primary, secondary


def generate_document_gap_next(criteria: DocumentGapNextCriteria) -> DocumentGapNextResult:
    """
    Read-only. Calls business_core.document_gap_detail
    .generate_document_gap_detail() exactly once — same call budget as
    /docgap (max 6 distinct-sheet reads, 0 DOCUMENT_FIELD_REVIEWS, 0
    writes). This module itself performs 0 reads and 0 writes.

    Raises SheetsQuotaExceededError/TransientSheetsReadError exactly
    like any other read in this codebase — propagated from
    generate_document_gap_detail(), which propagates them in turn from
    generate_document_coverage() / read_business_sheet().
    """
    from business_core.document_gap_detail import (
        DocumentGapDetailCriteria, generate_document_gap_detail,
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    detail_result = generate_document_gap_detail(
        DocumentGapDetailCriteria(
            roadmap_id=criteria.roadmap_id, requirement_id=criteria.requirement_id, as_of=criteria.as_of,
        ),
    )

    if not detail_result.ok:
        # Verbatim passthrough — never a second version of ROADMAP_NOT_FOUND/
        # ROADMAP_MISSING_BUSINESS_ID/REQUIREMENT_NOT_FOUND/
        # AMBIGUOUS_REQUIREMENT_ID/UNKNOWN_ENGINE_STATUS/
        # COVERAGE_CONFIGURATION_ERROR/COVERAGE_INVARIANT_FAILED, and
        # never any of detail_result's own (already-safe) warnings copied
        # into this result.
        return DocumentGapNextResult(
            criteria=criteria, ok=False, error_code=detail_result.error_code,
            requirement_name="", stage_id="", base_status="", blocking=False, required=False,
            quality_flags=(), primary_action=None, secondary_actions=(), warnings=(),
            generated_at=generated_at,
        )

    detail = detail_result.detail

    if detail.base_status not in _KNOWN_BASE_STATUSES:
        return DocumentGapNextResult(
            criteria=criteria, ok=False, error_code=ERROR_UNSUPPORTED_BASE_STATUS,
            requirement_name="", stage_id="", base_status="", blocking=False, required=False,
            quality_flags=(), primary_action=None, secondary_actions=(), warnings=(),
            generated_at=generated_at,
        )

    for flag in detail.quality_flags:
        if flag not in _KNOWN_QUALITY_FLAGS:
            return DocumentGapNextResult(
                criteria=criteria, ok=False, error_code=ERROR_UNSUPPORTED_QUALITY_FLAG,
                requirement_name="", stage_id="", base_status="", blocking=False, required=False,
                quality_flags=(), primary_action=None, secondary_actions=(), warnings=(),
                generated_at=generated_at,
            )

    primary_action, secondary_actions = _select_actions(detail.base_status, detail.quality_flags)

    return DocumentGapNextResult(
        criteria=criteria, ok=True, error_code="",
        requirement_name=detail.requirement_name, stage_id=detail.stage_id,
        base_status=detail.base_status, blocking=detail.blocking, required=detail.required,
        quality_flags=detail.quality_flags, primary_action=primary_action,
        secondary_actions=secondary_actions, warnings=(), generated_at=generated_at,
    )
