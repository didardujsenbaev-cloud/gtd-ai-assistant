"""
Phase 17B: read-only query layer bridging Telegram handlers to the
Phase 17A document requirements engine (business_core/document_requirements.py).

This module exists so Telegram handlers never read DOCUMENT_REGISTRY
or any other Sheets row directly, and never call the Phase 17A
evaluate_*/get_requirements_for_* functions without first confirming
the requested scope actually exists in its authoritative registry.

Phase 17A's own evaluate_*() functions deliberately treat "scope not
found" and "scope found but has zero configured requirements" the same
way (both return a zero/100%/complete RequirementsSummary) — that is
correct and unchanged at the engine layer. Distinguishing the two for
user-facing messages is a Telegram-presentation concern, so it is
implemented HERE, not in business_core/document_requirements.py.

Strictly read-only: at most one find_row_by_id() existence check plus
whatever read-only work business_core.document_requirements already
does — no writes, no AI calls, no Drive calls, ever.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_TYPES = ("stage", "roadmap", "object")

_EXISTENCE_SHEET_KEY = {
    "stage": "roadmap_stages",
    "roadmap": "roadmaps",
    "object": "object_registry",
}


@dataclass(frozen=True)
class ScopeEvaluationResult:
    """
    exists=False means the scope_id doesn't exist in its authoritative
    registry at all — summary is always None in that case, and callers
    must never render Phase 17A's own zero/100%/complete convention as
    if it were a valid answer for a nonexistent scope.

    exists=True + summary.items == () means the scope is real but has
    no configured structured document requirements yet — a legitimate,
    different situation from "not found".
    """
    scope_type: str
    scope_id: str
    exists: bool
    summary: object = None  # business_core.document_requirements.RequirementsSummary | None


def scope_exists(scope_type: str, scope_id: str) -> bool:
    """Read-only existence check via the existing find_row_by_id() helper
    — the same primitive already used throughout Business Core, never a
    bespoke Sheets read."""
    from business_core.sheets import find_row_by_id

    sheet_key = _EXISTENCE_SHEET_KEY.get(scope_type)
    if sheet_key is None or not scope_id:
        return False
    return find_row_by_id(sheet_key, scope_id) is not None


def evaluate_scope(scope_type: str, scope_id: str) -> ScopeEvaluationResult:
    """
    The single entry point Telegram handlers should use: validates
    existence first (in this query layer, per the Phase 17B design —
    Phase 17A's engine itself is unchanged), then calls the matching
    Phase 17A evaluate_*_requirements() function only if the scope is
    real.
    """
    if scope_type not in SCOPE_TYPES:
        return ScopeEvaluationResult(scope_type=scope_type, scope_id=scope_id, exists=False, summary=None)

    if not scope_exists(scope_type, scope_id):
        return ScopeEvaluationResult(scope_type=scope_type, scope_id=scope_id, exists=False, summary=None)

    from business_core import document_requirements as dr

    evaluators = {
        "stage": dr.evaluate_stage_requirements,
        "roadmap": dr.evaluate_roadmap_requirements,
        "object": dr.evaluate_object_requirements,
    }
    summary = evaluators[scope_type](scope_id)
    return ScopeEvaluationResult(scope_type=scope_type, scope_id=scope_id, exists=True, summary=summary)
