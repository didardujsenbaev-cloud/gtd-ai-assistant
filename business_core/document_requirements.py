"""
Phase 17A: Document Requirements Engine Foundation — read-only.

Audit finding (see the Phase 17A report for the full write-up):
ROADMAP_STAGES."Document Template IDs" (a comma-separated list of
document_template_registry IDs, copied from ROADMAP_TEMPLATE_STAGES.
"Document Template IDs" at /startroadmap time) is the ONLY structured,
ID-referenceable document-requirement source anywhere in this codebase.

SERVICE_CATALOG's "Документы от клиента" / "Документы наши" /
"Required Documents", and ROADMAP_STAGES / ROADMAP_TEMPLATE_STAGES'
"Docs Required" / "Docs Received" / "Required Docs", are all free text
— not safely matchable — and are deliberately NOT used here. This
module does not invent a second, competing source of truth.

Every requirement in the current data model is therefore stage-scoped.
Roadmap- and object-level results are AGGREGATIONS over their
constituent stages' requirements, not independent requirement sources.
Service-level evaluation is intentionally not implemented in this
phase — there is no structured, ID-referenceable service-level
requirement source to aggregate (see the audit report, section K, for
the smallest proposed additive schema if that's wanted later).

This module is strictly read-only: it makes no AI calls, no Drive
calls, no Sheets writes, never modifies DOCUMENT_REGISTRY or any
roadmap/stage row, and never enqueues a job. It only reads via
business_core.sheets' existing read_business_sheet()/find_row_by_id().
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Only "uploaded" documents count toward a requirement today.
# document_registry_manager.DOCUMENT_STATUS_ALLOWED also permits
# "archived", but an archived document is explicitly no longer a live/
# current one and must not satisfy a requirement. under_review/
# approved/rejected/superseded are RESERVED in document_registry_manager
# (never written by any current code path) — accepted here for forward
# compatibility only if that module ever starts writing them; today no
# live data ever has these values.
SATISFYING_STATUSES = frozenset({"uploaded"})

STATUS_PRESENT = "present"
STATUS_MISSING = "missing"
STATUS_PARTIAL = "partial"
STATUS_OPTIONAL_MISSING = "optional_missing"
STATUS_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class DocumentRequirement:
    """
    One document requirement, exploded from a single Document Template
    ID entry in a stage's "Document Template IDs" list.

    Only fields justified by the existing architecture carry real
    per-item variation today: document_template_id, document_type/name
    (from document_template_registry), and the resolved scope chain
    (business_id/service_id/roadmap_id/roadmap_template_id/stage_id/
    stage_template_id). required/blocking/minimum_count/allowed_statuses
    are modeled (per the requested API) but default uniformly, because
    the current schema has no per-template optional/blocking/minimum-
    count flag — see the audit report's proposed future additive schema.
    """
    requirement_id: str
    document_template_id: str
    document_type: str = ""
    name: str = ""
    scope_type: str = "stage"
    scope_id: str = ""
    business_id: str = ""
    service_id: str = ""
    roadmap_template_id: str = ""
    roadmap_id: str = ""
    stage_template_id: str = ""
    stage_id: str = ""
    required: bool = True
    blocking: bool = True
    minimum_count: int = 1
    allowed_statuses: tuple = field(default_factory=lambda: tuple(SATISFYING_STATUSES))
    notes: str = ""


@dataclass(frozen=True)
class DocumentRequirementStatus:
    """Immutable evaluation result for one DocumentRequirement."""
    requirement: DocumentRequirement
    matched_document_ids: tuple = ()
    matched_count: int = 0
    status: str = STATUS_MISSING

    @property
    def is_blocking(self) -> bool:
        """True only while this requirement is both flagged blocking
        AND not yet satisfied — a satisfied or not-applicable
        requirement never blocks."""
        return self.requirement.blocking and self.status in (STATUS_MISSING, STATUS_PARTIAL)

    @property
    def is_satisfied(self) -> bool:
        return self.status == STATUS_PRESENT


@dataclass(frozen=True)
class RequirementsSummary:
    """Immutable aggregate result for a stage, roadmap, or object."""
    scope_type: str
    scope_id: str
    items: tuple = ()
    total_required: int = 0
    satisfied_required: int = 0
    missing_required: int = 0
    blocking_missing: int = 0
    optional_missing: int = 0
    completion_percentage: float = 100.0
    is_complete: bool = True


def _parse_id_list(raw: str) -> list[str]:
    """Comma-separated -> de-duplicated (order-preserving) list of IDs.
    The same Document Template ID appearing twice in the source list is
    one requirement, not two — matches how compute_stage_document_status()
    already treats this same column."""
    seen: dict[str, None] = {}
    for token in (raw or "").split(","):
        token = token.strip()
        if token and token not in seen:
            seen[token] = None
    return list(seen.keys())


def _safe_version(raw: str) -> int:
    """Numeric version for family-supersession comparison. Falls back to
    0 (lowest priority) for anything unparseable rather than raising —
    this is a read-only reporting engine, never a hard failure point."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def _resolve_scope_chain(stage_id: str = "", roadmap_id: str = "", object_id: str = "") -> dict:
    """
    Plain upward traversal (stage -> roadmap -> business/service/object),
    read-only, via the existing find_row_by_id() primitive. Deliberately
    NOT business_core.document_registry_manager.resolve_and_validate_links()
    — that function validates a caller-supplied, possibly-contradictory
    set of IDs for a WRITE gate; here we only ever walk upward from one
    known-good leaf for read-only reporting, so there is nothing to
    validate for contradictions.
    """
    from business_core.sheets import find_row_by_id

    if stage_id and not roadmap_id:
        found = find_row_by_id("roadmap_stages", stage_id)
        if found:
            roadmap_id = found[1].get("Roadmap ID", "")

    business_id = ""
    service_id = ""
    if roadmap_id:
        found = find_row_by_id("roadmaps", roadmap_id)
        if found:
            rm = found[1]
            business_id = rm.get("Business ID", "")
            service_id = rm.get("Service ID", "")
            object_id = object_id or rm.get("Object ID", "")

    return {
        "business_id": business_id,
        "service_id": service_id,
        "roadmap_id": roadmap_id,
        "object_id": object_id,
        "stage_id": stage_id,
    }


def _current_valid_documents_for(stage_id: str, document_template_id: str) -> tuple:
    """
    Read-only match of one (stage_id, document_template_id) requirement
    against DOCUMENT_REGISTRY, following the exact same "Stage ID must
    match exactly" rule already established by
    document_registry_manager.get_documents_for_stage() — a document
    registered under a different stage (or with no stage at all) never
    counts, even if its Document Template ID matches.

    Within one Document Family ID, the CURRENT version is always the
    highest Version number among ALL matching rows in that family —
    determined BEFORE looking at Status. Only if that current row's own
    Status is in SATISFYING_STATUSES does the family count at all. This
    order matters: if the newest version is (e.g.) archived, an OLDER
    "uploaded" version in the same family must NOT win and must NOT
    satisfy the requirement — the family's current version is what's
    evaluated, never the highest-among-only-the-already-satisfying-rows.
    Rows with no Document Family ID are treated as their own singleton
    family (keyed by Document ID) so they are never accidentally merged
    with unrelated rows.

    Returns a tuple of the winning Document IDs (one per qualifying
    family) — this IS matched_count via len(), and duplicates across
    independent families both count normally (that's real evidence, not
    inflation — only same-family older versions are excluded).
    """
    from business_core.sheets import read_business_sheet

    if not stage_id or not document_template_id:
        return ()

    candidates = [
        row for row in read_business_sheet("document_registry")
        if row.get("Stage ID", "") == stage_id
        and row.get("Document Template ID", "") == document_template_id
    ]

    families: dict[str, dict] = {}
    for row in candidates:
        family_key = row.get("Document Family ID", "") or f"__no_family__:{row.get('Document ID', '')}"
        current = families.get(family_key)
        if current is None or _safe_version(row.get("Version", "")) > _safe_version(current.get("Version", "")):
            families[family_key] = row

    return tuple(
        row.get("Document ID", "")
        for row in families.values()
        if (row.get("Status", "") or "").strip() in SATISFYING_STATUSES
    )


def _build_requirement(stage_id: str, document_template_id: str, chain: dict) -> DocumentRequirement:
    """
    An unknown/dangling document_template_id (not present in
    document_template_registry) is NEVER silently discarded — it is
    preserved as a normal requirement with a safe fallback name (the ID
    itself, always visible) rather than an empty string. Silently
    dropping it would falsely inflate completeness for a stage with a
    broken/typo'd template reference.
    """
    from business_core.sheets import find_row_by_id

    document_type = ""
    name = document_template_id
    template_found = find_row_by_id("document_template_registry", document_template_id)
    if template_found:
        tmpl = template_found[1]
        document_type = tmpl.get("Document Type", "")
        name = tmpl.get("Title", "") or document_template_id

    return DocumentRequirement(
        requirement_id=f"{stage_id}:{document_template_id}",
        document_template_id=document_template_id,
        document_type=document_type,
        name=name,
        scope_type="stage",
        scope_id=stage_id,
        business_id=chain.get("business_id", ""),
        service_id=chain.get("service_id", ""),
        roadmap_id=chain.get("roadmap_id", ""),
        stage_id=stage_id,
    )


def _evaluate_requirement(requirement: DocumentRequirement) -> DocumentRequirementStatus:
    """
    Matching by exact Document Template ID string works independently
    of whether that ID exists in document_template_registry — the
    catalog only supplies display metadata (name/document_type), never
    a precondition for matching. An unknown template ID is therefore
    evaluated exactly like any other requirement (missing/partial/
    present), never short-circuited to not_applicable.
    """
    matched_ids = _current_valid_documents_for(requirement.stage_id, requirement.document_template_id)
    matched_count = len(matched_ids)

    if not requirement.required:
        status = STATUS_PRESENT if matched_count > 0 else STATUS_OPTIONAL_MISSING
    elif matched_count >= requirement.minimum_count:
        status = STATUS_PRESENT
    elif matched_count > 0:
        status = STATUS_PARTIAL
    else:
        status = STATUS_MISSING

    return DocumentRequirementStatus(
        requirement=requirement, matched_document_ids=matched_ids,
        matched_count=matched_count, status=status,
    )


def get_requirements_for_stage(stage_id: str) -> tuple:
    """Read-only: the DocumentRequirement tuple for one stage, exploded
    from its "Document Template IDs" list. Empty tuple if the stage
    doesn't exist or has no requirements — these are treated the same
    (nothing to evaluate), never an exception."""
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        return ()
    stage_row = found[1]

    template_ids = _parse_id_list(stage_row.get("Document Template IDs", ""))
    if not template_ids:
        return ()

    chain = _resolve_scope_chain(stage_id=stage_id, roadmap_id=stage_row.get("Roadmap ID", ""))
    return tuple(_build_requirement(stage_id, tid, chain) for tid in template_ids)


def _summarize(scope_type: str, scope_id: str, statuses: tuple) -> RequirementsSummary:
    countable = [s for s in statuses if s.status != STATUS_NOT_APPLICABLE and s.requirement.required]
    total_required = len(countable)
    satisfied_required = sum(1 for s in countable if s.is_satisfied)
    missing_required = sum(1 for s in countable if s.status in (STATUS_MISSING, STATUS_PARTIAL))
    blocking_missing = sum(1 for s in statuses if s.is_blocking)
    optional_missing = sum(1 for s in statuses if s.status == STATUS_OPTIONAL_MISSING)

    completion_percentage = 100.0 if total_required == 0 else round(
        (satisfied_required / total_required) * 100, 2
    )
    is_complete = missing_required == 0 and blocking_missing == 0

    return RequirementsSummary(
        scope_type=scope_type,
        scope_id=scope_id,
        items=statuses,
        total_required=total_required,
        satisfied_required=satisfied_required,
        missing_required=missing_required,
        blocking_missing=blocking_missing,
        optional_missing=optional_missing,
        completion_percentage=completion_percentage,
        is_complete=is_complete,
    )


def evaluate_stage_requirements(stage_id: str) -> RequirementsSummary:
    """Read-only. Evaluates every requirement for one stage."""
    requirements = get_requirements_for_stage(stage_id)
    statuses = tuple(_evaluate_requirement(r) for r in requirements)
    return _summarize("stage", stage_id, statuses)


def get_requirements_for_roadmap(roadmap_id: str) -> tuple:
    """Read-only: concatenation of get_requirements_for_stage() over
    every stage belonging to this roadmap — a roadmap has no
    independent requirement source of its own (see module docstring)."""
    from business_core.sheets import read_business_sheet

    stage_ids = [
        row.get("Stage ID", "") for row in read_business_sheet("roadmap_stages")
        if row.get("Roadmap ID", "") == roadmap_id
    ]
    requirements: list = []
    for stage_id in stage_ids:
        requirements.extend(get_requirements_for_stage(stage_id))
    return tuple(requirements)


def evaluate_roadmap_requirements(roadmap_id: str) -> RequirementsSummary:
    """Read-only aggregate over every stage of this roadmap."""
    requirements = get_requirements_for_roadmap(roadmap_id)
    statuses = tuple(_evaluate_requirement(r) for r in requirements)
    return _summarize("roadmap", roadmap_id, statuses)


def get_requirements_for_object(object_id: str) -> tuple:
    """Read-only: concatenation of get_requirements_for_roadmap() over
    every roadmap whose Object ID matches — an object has no
    independent requirement source of its own either (see module
    docstring); it is reached only through its roadmap(s)."""
    from business_core.sheets import read_business_sheet

    roadmap_ids = [
        row.get("Roadmap ID", "") for row in read_business_sheet("roadmaps")
        if row.get("Object ID", "") == object_id
    ]
    requirements: list = []
    for roadmap_id in roadmap_ids:
        requirements.extend(get_requirements_for_roadmap(roadmap_id))
    return tuple(requirements)


def evaluate_object_requirements(object_id: str) -> RequirementsSummary:
    """Read-only aggregate over every roadmap tied to this object."""
    requirements = get_requirements_for_object(object_id)
    statuses = tuple(_evaluate_requirement(r) for r in requirements)
    return _summarize("object", object_id, statuses)
