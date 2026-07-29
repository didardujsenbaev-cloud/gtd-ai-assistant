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

Every requirement's SOURCE is stage-scoped (each stage's own
"Document Template IDs" list is where a requirement comes from).
Roadmap- and object-level results are AGGREGATIONS over their
constituent stages' requirements, not independent requirement sources.
Service-level evaluation is intentionally not implemented in this
phase — there is no structured, ID-referenceable service-level
requirement source to aggregate (see the audit report, section K, for
the smallest proposed additive schema if that's wanted later).

Phase 17D: requirement SATISFACTION, however, is ROADMAP-scoped, not
stage-scoped — a document uploaded once for a Roadmap (regardless of
which stage it was registered against) satisfies matching requirements
on every stage of that same Roadmap. Stage ID on a DOCUMENT_REGISTRY
row is preserved purely as provenance (where the document was
requested/uploaded/produced/registered) and is never a precondition
for satisfying a requirement. See _current_valid_documents_for()'s
docstring for the exact matching rule.

Phase 18C-4: requirement SOURCE, for an instantiated stage, is now
dual: if that stage has one or more active, instance-scoped
STAGE_ENTITY_RELATIONS rows (Entity Type "document_template"), those
rows are the sole source (never merged with the legacy column, not
even partially); otherwise the original Phase 17A legacy source
(ROADMAP_STAGES."Document Template IDs") is used, exactly as before.
See business_core.stage_entity_relations.
get_document_requirements_source_for_stage() for the exact precedence
rule and get_requirements_for_stage() below for where it's consulted.
Document matching/satisfaction (Phase 17D, above) is completely
unaffected by which source produced the requirement.

Phase 16C.1B1: bulk read context. Every public entrypoint below now
accepts an optional keyword-only `read_context: RequirementsReadContext
| None = None`. When omitted (every existing caller — Completion Gate,
/missingdocs, /docsrequired — passes nothing), the entrypoint creates
ONE throwaway RequirementsReadContext for the duration of that single
call, so each distinct Sheet (roadmaps, roadmap_stages,
stage_entity_relations, document_template_registry, document_registry)
is read AT MOST ONCE per evaluation, regardless of how many stages/
requirements/documents are involved — collapsing the prior O(Q) (Q =
number of requirements) re-reads of document_registry and
document_template_registry down to O(1) per evaluation. Passing an
explicit context lets an external caller (e.g. a future coverage
report) share one context across multiple calls, or share its cached
DOCUMENT_REGISTRY rows with another module (see
business_core.document_search.load_effective_document_records()'s own
optional `registry_rows=` parameter, added separately).

This changes nothing about the RESULT of any function — every
DocumentRequirement/DocumentRequirementStatus/RequirementsSummary is
byte-for-byte identical to before this phase (proven by the existing
Phase 17A-18C-4 test suite, unmodified) — only the number of
underlying Sheets reads changes.

This module is strictly read-only: it makes no AI calls, no Drive
calls, no Sheets writes, never modifies DOCUMENT_REGISTRY or any
roadmap/stage row, and never enqueues a job. It only reads via
business_core.sheets' existing read_business_sheet_cached() (which
itself wraps read_business_sheet()) — never find_row_by_id() or
get_business_sheet() directly anymore (Phase 16C.1B1); the underlying
auto-create-capable get_business_sheet() primitive is still reachable
transitively (unchanged, latent, pre-existing — see the Phase 16C.1A
audit), just called at most once per sheet per evaluation instead of
once per requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Phase 37D (ADR-020 §16): "uploaded", "under_review", and "approved"
# all satisfy a requirement — a document doesn't stop being "the
# document that was asked for" just because it's awaiting or has
# passed review. "archived" is explicitly no longer a live/current
# document and must not satisfy a requirement. "rejected" never
# satisfies. "superseded" satisfies only historically (handled
# separately, not via this set — see _current_valid_documents_for()).
# No current code path writes anything beyond "uploaded"/"archived"
# yet (document_manager.DOCUMENT_STATUS is the full 6-value vocabulary,
# but the lifecycle transition orchestration that would produce
# "under_review"/"approved" data is Foundation-only for now, per
# ADR-020 §14 — full review UX is deferred) — this set is forward-
# compatible with that data the moment it exists.
SATISFYING_STATUSES = frozenset({"uploaded", "under_review", "approved"})

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
    object_id: str = ""
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
    """
    Immutable aggregate result for a stage, roadmap, or object.

    Phase 18C-4A: `configuration_errors` carries deterministic,
    human-readable (stage_id, relation_id, reason) tuples for any
    active document-instance-relation row that was invalid, dangling,
    or a duplicate — never a raw exception. `has_configuration_errors`
    is the fail-closed signal: whenever it's True, `is_complete` is
    forced False regardless of how complete the *valid* requirements
    happen to be, so a broken relation can never be reported as a
    safely complete stage. Both fields default to their empty/False
    state, so any summary built without configuration errors (which is
    every summary today, since no live stage has instance relations
    yet) is byte-for-byte identical to before this phase.
    """
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
    configuration_errors: tuple = ()
    has_configuration_errors: bool = False


class RequirementsReadContext:
    """
    Phase 16C.1B1: mutable, single-evaluation-lifetime Sheets read
    cache — created fresh by a top-level public entrypoint (or by a
    future external caller, e.g. a coverage report) at the start of one
    evaluation, threaded down into every helper, and discarded when
    that evaluation returns. NOT global, NOT shared across Telegram
    updates, NOT TTL'd — mirrors business_core.business_builder.
    _TransitionReadContext's own contract exactly.

    `sheet_rows` is the SAME generic, duck-typed cache dict that
    business_core.sheets.read_business_sheet_cached() and
    business_core.stage_entity_relations.list_relations() already
    expect (`read_context.sheet_rows[sheet_key] -> list[dict]`) — this
    class IS that duck type, so it can be passed directly as the
    `read_context=` argument to either of those existing functions with
    no adapter needed.

    The `*_by_*` index methods below are lazily built (memoized) on
    first access, from whatever `sheet_rows` already holds (fetching it
    via read_business_sheet_cached() if not yet cached) — a stage with
    zero requirements never triggers a document_registry or
    document_template_registry read at all, since neither index is
    ever touched.

    Index semantics (Phase 16C.1A/B design, unchanged from the
    engine's prior direct find_row_by_id()/read_business_sheet() calls):
    single-ID indexes (roadmap/stage/template lookup) keep the FIRST
    matching row for a given ID — exactly matching find_row_by_id()'s
    own top-to-bottom scan. Grouped indexes (by Roadmap ID/Object ID)
    keep every row, in original sheet order — nothing is deduplicated
    or reordered; the family/version reduction in
    _current_valid_documents_for() still operates on the full,
    unmodified group for its own roadmap.
    """

    def __init__(self):
        self.sheet_rows: dict = {}
        self._roadmaps_by_id: dict | None = None
        self._roadmaps_by_object_id: dict | None = None
        self._roadmap_stages_by_id: dict | None = None
        self._roadmap_stages_by_roadmap_id: dict | None = None
        self._document_template_registry_by_id: dict | None = None
        self._document_registry_by_roadmap_id: dict | None = None

    def _rows(self, sheet_key: str) -> list:
        from business_core.sheets import read_business_sheet_cached
        return read_business_sheet_cached(sheet_key, read_context=self)

    def roadmap_by_id(self, roadmap_id: str) -> dict | None:
        if self._roadmaps_by_id is None:
            index: dict = {}
            for row in self._rows("roadmaps"):
                rid = row.get("Roadmap ID", "")
                if rid and rid not in index:
                    index[rid] = row
            self._roadmaps_by_id = index
        return self._roadmaps_by_id.get(roadmap_id)

    def roadmap_ids_for_object(self, object_id: str) -> tuple:
        if self._roadmaps_by_object_id is None:
            grouped: dict = {}
            for row in self._rows("roadmaps"):
                grouped.setdefault(row.get("Object ID", ""), []).append(row)
            self._roadmaps_by_object_id = grouped
        return tuple(row.get("Roadmap ID", "") for row in self._roadmaps_by_object_id.get(object_id, ()))

    def roadmap_stage_by_id(self, stage_id: str) -> dict | None:
        if self._roadmap_stages_by_id is None:
            index: dict = {}
            for row in self._rows("roadmap_stages"):
                sid = row.get("Stage ID", "")
                if sid and sid not in index:
                    index[sid] = row
            self._roadmap_stages_by_id = index
        return self._roadmap_stages_by_id.get(stage_id)

    def stage_ids_for_roadmap(self, roadmap_id: str) -> tuple:
        if self._roadmap_stages_by_roadmap_id is None:
            grouped: dict = {}
            for row in self._rows("roadmap_stages"):
                grouped.setdefault(row.get("Roadmap ID", ""), []).append(row)
            self._roadmap_stages_by_roadmap_id = grouped
        return tuple(row.get("Stage ID", "") for row in self._roadmap_stages_by_roadmap_id.get(roadmap_id, ()))

    def document_template(self, document_template_id: str) -> dict | None:
        if self._document_template_registry_by_id is None:
            index: dict = {}
            for row in self._rows("document_template_registry"):
                tid = row.get("Document Template ID", "")
                if tid and tid not in index:
                    index[tid] = row
            self._document_template_registry_by_id = index
        return self._document_template_registry_by_id.get(document_template_id)

    def document_registry_rows_for_roadmap(self, roadmap_id: str) -> tuple:
        if self._document_registry_by_roadmap_id is None:
            grouped: dict = {}
            for row in self._rows("document_registry"):
                grouped.setdefault(row.get("Roadmap ID", ""), []).append(row)
            self._document_registry_by_roadmap_id = grouped
        return tuple(self._document_registry_by_roadmap_id.get(roadmap_id, ()))


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


def _resolve_scope_chain(
    stage_id: str = "", roadmap_id: str = "", object_id: str = "",
    *, read_context: RequirementsReadContext,
) -> dict:
    """
    Plain upward traversal (stage -> roadmap -> business/service/object),
    read-only, via the context's memoized indexes (Phase 16C.1B1 — was
    find_row_by_id() directly before this phase; same first-row-wins
    semantics, now sourced from an at-most-once-per-evaluation read).
    Deliberately NOT business_core.document_registry_manager.
    resolve_and_validate_links() — that function validates a
    caller-supplied, possibly-contradictory set of IDs for a WRITE gate;
    here we only ever walk upward from one known-good leaf for
    read-only reporting, so there is nothing to validate for
    contradictions.

    Internal helper: always requires an existing read_context — never
    creates its own (that would defeat the whole point of sharing one
    context across a stage/roadmap/object evaluation).
    """
    if stage_id and not roadmap_id:
        found = read_context.roadmap_stage_by_id(stage_id)
        if found:
            roadmap_id = found.get("Roadmap ID", "")

    business_id = ""
    service_id = ""
    if roadmap_id:
        rm = read_context.roadmap_by_id(roadmap_id)
        if rm:
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


def _current_valid_documents_for(
    roadmap_id: str, document_template_id: str, object_id: str = "",
    *, read_context: RequirementsReadContext,
) -> tuple:
    """
    Phase 17D: read-only match of one (roadmap_id, document_template_id)
    requirement against DOCUMENT_REGISTRY, ROADMAP-scoped rather than
    stage-scoped. A document registered against ANY stage of the same
    roadmap (or with no stage recorded at all) now counts — Stage ID is
    preserved on the DOCUMENT_REGISTRY row purely as provenance (where
    the document was requested/uploaded/produced/registered), never as
    a precondition for requirement satisfaction. This replaces the
    Phase 17A "Stage ID must match exactly" rule (formerly matching
    document_registry_manager.get_documents_for_stage()'s behavior —
    that older, separate function is unrelated to this engine and is
    intentionally left unchanged).

    Roadmap ID is the decisive scope key: a document registered under a
    different roadmap never counts, even if it happens to share the
    same Object ID (two different roadmaps for the same object are
    still two independent cases). Object ID, when the requirement has
    one resolved AND the candidate row also has one recorded, must
    additionally agree — a defense-in-depth consistency check, never a
    fallback that alone can satisfy a Roadmap ID mismatch.

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

    Phase 16C.1B1: DOCUMENT_REGISTRY is read at most once per
    evaluation (via read_context.document_registry_rows_for_roadmap(),
    memoized on the shared context) — the Roadmap ID filter that used
    to run here is now applied once, up front, by that grouping index;
    only the Document Template ID / Object ID filter still runs per
    call, over the much smaller per-roadmap candidate set.
    """
    if not roadmap_id or not document_template_id:
        return ()

    candidates = [
        row for row in read_context.document_registry_rows_for_roadmap(roadmap_id)
        if row.get("Document Template ID", "") == document_template_id
        and (
            not object_id
            or not row.get("Object ID", "")
            or row.get("Object ID", "") == object_id
        )
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


def _lookup_template_catalog(document_template_id: str, *, read_context: RequirementsReadContext) -> tuple[str, str]:
    """
    An unknown/dangling document_template_id (not present in
    document_template_registry) is NEVER silently discarded — the
    caller always gets a safe fallback name (the ID itself, always
    visible) rather than an empty string. Silently dropping it would
    falsely inflate completeness for a stage with a broken/typo'd
    template reference. Shared by both the legacy comma-list path
    (_build_requirement) and the Phase 18C-4 relation-row path
    (_build_requirement_from_relation).

    Phase 16C.1B1: sourced from read_context.document_template()
    (memoized index) instead of a fresh find_row_by_id() call each time
    — DOCUMENT_TEMPLATE_REGISTRY is now read at most once per
    evaluation, regardless of how many requirements reference it.
    """
    document_type = ""
    name = document_template_id
    tmpl = read_context.document_template(document_template_id)
    if tmpl:
        document_type = tmpl.get("Document Type", "")
        name = tmpl.get("Title", "") or document_template_id
    return document_type, name


def _build_requirement(
    stage_id: str, document_template_id: str, chain: dict, *, read_context: RequirementsReadContext,
) -> DocumentRequirement:
    """Legacy path: builds a requirement from one ROADMAP_STAGES.
    "Document Template IDs" comma-list entry — required/blocking/
    minimum_count are always the hardcoded engine defaults, since the
    legacy column has no per-item way to express anything else."""
    document_type, name = _lookup_template_catalog(document_template_id, read_context=read_context)

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
        object_id=chain.get("object_id", ""),
        stage_id=stage_id,
    )


def _build_requirement_from_relation(
    stage_id: str, relation: dict, chain: dict, *, read_context: RequirementsReadContext,
) -> DocumentRequirement:
    """
    Phase 18C-4: builds a requirement from one validated, active,
    instance-scoped STAGE_ENTITY_RELATIONS row — required/blocking/
    minimum_count are read from the relation row itself, not the
    engine's hardcoded defaults. Only ever called with a relation that
    business_core.stage_entity_relations.get_document_requirements_source_for_stage()
    has already validated (validate_relation_record +
    validate_relation_references) and de-duplicated — this function
    does no validation of its own.
    """
    document_template_id = relation.get("Entity ID", "")
    document_type, name = _lookup_template_catalog(document_template_id, read_context=read_context)

    required = (relation.get("Required", "") or "").strip().lower() == "true"
    blocking = (relation.get("Blocking", "") or "").strip().lower() == "true"
    try:
        minimum_count = int(str(relation.get("Minimum Count", "1")).strip())
    except (TypeError, ValueError):
        minimum_count = 1

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
        object_id=chain.get("object_id", ""),
        stage_id=stage_id,
        required=required,
        blocking=blocking,
        minimum_count=minimum_count,
    )


def _evaluate_requirement(requirement: DocumentRequirement, *, read_context: RequirementsReadContext) -> DocumentRequirementStatus:
    """
    Matching by exact Document Template ID string works independently
    of whether that ID exists in document_template_registry — the
    catalog only supplies display metadata (name/document_type), never
    a precondition for matching. An unknown template ID is therefore
    evaluated exactly like any other requirement (missing/partial/
    present), never short-circuited to not_applicable.

    Phase 17D: matching is scoped by the requirement's ROADMAP (plus
    Object ID as a secondary consistency check), not by the stage the
    requirement happens to be configured on — see
    _current_valid_documents_for()'s own docstring for the full
    rationale. requirement.stage_id is still carried on the requirement
    (and still recorded on the DOCUMENT_REGISTRY row it matched, if
    any) purely as provenance.
    """
    matched_ids = _current_valid_documents_for(
        requirement.roadmap_id, requirement.document_template_id, requirement.object_id,
        read_context=read_context,
    )
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


def _resolve_stage_requirements_and_errors(stage_id: str, *, read_context: RequirementsReadContext) -> tuple:
    """
    Read-only. Single point of truth for one stage's (requirements,
    configuration_errors) pair — calls
    business_core.stage_entity_relations.get_document_requirements_source_for_stage()
    exactly ONCE (a real Sheets read the first time any stage needs it;
    memoized on read_context thereafter — Phase 16C.1B1), so callers
    that need both the requirements and the configuration errors
    (evaluate_stage_requirements() and its roadmap/object aggregates)
    never fetch the same relation data twice. get_requirements_for_stage()
    and _configuration_errors_for_stage() below are thin single-purpose
    wrappers over this for callers that only need one side.

    Phase 18C-4 source precedence (see
    get_document_requirements_source_for_stage()'s own docstring for
    the exact rule): if this stage has one or more active,
    instance-scoped STAGE_ENTITY_RELATIONS rows of Entity Type
    "document_template", those rows are the SOLE source — never merged
    with the legacy comma-list, even partially. Only when zero such
    relations exist does this fall back to the original Phase 17A
    source, ROADMAP_STAGES."Document Template IDs" — this is exactly
    what keeps every existing roadmap (e.g. RM-001) producing identical
    requirements to before Phase 18C-4, since none has any instance
    relations yet.

    Phase 18C-4A: configuration_errors is a deterministic, displayable
    tuple of (stage_id, relation_id, reason) — never a raw exception.
    Deliberately excludes source.unsupported_entity_type_relation_ids —
    a non-document_template active relation (e.g. a future sop/checklist
    relation) is normal, expected data, not a document-engine
    configuration failure.

    Internal helper: always requires an existing read_context.
    """
    from business_core.stage_entity_relations import get_document_requirements_source_for_stage

    stage_row = read_context.roadmap_stage_by_id(stage_id)
    if not stage_row:
        return (), ()

    source = get_document_requirements_source_for_stage(stage_id, read_context=read_context)

    configuration_errors = []
    for relation_id, reasons in source.validation_errors:
        for reason in reasons:
            configuration_errors.append((stage_id, relation_id, reason))
    for entity_id, relation_ids in source.duplicate_errors:
        for relation_id in relation_ids:
            configuration_errors.append(
                (stage_id, relation_id, f"Duplicate active relation for Entity ID {entity_id!r}.")
            )
    configuration_errors = tuple(configuration_errors)

    chain = _resolve_scope_chain(
        stage_id=stage_id, roadmap_id=stage_row.get("Roadmap ID", ""), read_context=read_context,
    )

    if source.source == "instance_relations":
        requirements = tuple(
            _build_requirement_from_relation(stage_id, rel, chain, read_context=read_context)
            for rel in source.requirements
        )
        return requirements, configuration_errors

    template_ids = _parse_id_list(stage_row.get("Document Template IDs", ""))
    if not template_ids:
        return (), configuration_errors
    return (
        tuple(_build_requirement(stage_id, tid, chain, read_context=read_context) for tid in template_ids),
        configuration_errors,
    )


def get_requirements_for_stage(stage_id: str, *, read_context: RequirementsReadContext | None = None) -> tuple:
    """Read-only: the DocumentRequirement tuple for one stage. Empty
    tuple if the stage doesn't exist or has no requirements — these
    are treated the same (nothing to evaluate), never an exception.

    Phase 16C.1B1: read_context is optional — when omitted, one
    throwaway RequirementsReadContext is created for the duration of
    this single call (existing callers are unaffected; results are
    byte-for-byte identical, only the underlying read count improves).
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    requirements, _ = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
    return requirements


def _configuration_errors_for_stage(stage_id: str, *, read_context: RequirementsReadContext | None = None) -> tuple:
    """Read-only: just the configuration-errors half of
    _resolve_stage_requirements_and_errors() — kept as its own function
    since it's still a meaningful, independently-testable unit, even
    though evaluate_stage_requirements() below calls the combined
    resolver directly to avoid a redundant second Sheets read."""
    context = read_context if read_context is not None else RequirementsReadContext()
    _, configuration_errors = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
    return configuration_errors


def _stage_ids_for_roadmap(roadmap_id: str, *, read_context: RequirementsReadContext) -> tuple:
    """Internal helper: always requires an existing read_context."""
    return read_context.stage_ids_for_roadmap(roadmap_id)


def _roadmap_ids_for_object(object_id: str, *, read_context: RequirementsReadContext) -> tuple:
    """Internal helper: always requires an existing read_context."""
    return read_context.roadmap_ids_for_object(object_id)


def _summarize(scope_type: str, scope_id: str, statuses: tuple, configuration_errors: tuple = ()) -> RequirementsSummary:
    countable = [s for s in statuses if s.status != STATUS_NOT_APPLICABLE and s.requirement.required]
    total_required = len(countable)
    satisfied_required = sum(1 for s in countable if s.is_satisfied)
    missing_required = sum(1 for s in countable if s.status in (STATUS_MISSING, STATUS_PARTIAL))
    blocking_missing = sum(1 for s in statuses if s.is_blocking)
    optional_missing = sum(1 for s in statuses if s.status == STATUS_OPTIONAL_MISSING)

    completion_percentage = 100.0 if total_required == 0 else round(
        (satisfied_required / total_required) * 100, 2
    )
    has_configuration_errors = bool(configuration_errors)
    # Fail closed: a configuration error means the stage can never be
    # reported as safely complete, regardless of how complete the
    # *valid* requirements happen to be.
    is_complete = missing_required == 0 and blocking_missing == 0 and not has_configuration_errors

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
        configuration_errors=configuration_errors,
        has_configuration_errors=has_configuration_errors,
    )


def evaluate_stage_requirements(stage_id: str, *, read_context: RequirementsReadContext | None = None) -> RequirementsSummary:
    """Read-only. Evaluates every requirement for one stage. Calls the
    combined resolver once (not get_requirements_for_stage() +
    _configuration_errors_for_stage() separately) to avoid a redundant
    second STAGE_ENTITY_RELATIONS read.

    Phase 16C.1B1: read_context optional, see get_requirements_for_stage()'s
    docstring for the exact contract — one throwaway context per call
    when omitted.
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    requirements, configuration_errors = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
    statuses = tuple(_evaluate_requirement(r, read_context=context) for r in requirements)
    return _summarize("stage", stage_id, statuses, configuration_errors=configuration_errors)


def get_requirements_for_roadmap(roadmap_id: str, *, read_context: RequirementsReadContext | None = None) -> tuple:
    """Read-only: every requirement across every stage belonging to
    this roadmap — a roadmap has no independent requirement source of
    its own (see module docstring).

    Phase 16C.1B1: shares ONE read_context across every constituent
    stage (calling the internal _resolve_stage_requirements_and_errors()
    resolver directly, rather than the public get_requirements_for_stage()
    entrypoint, which would otherwise create a separate throwaway
    context per stage and reintroduce the very N+1 this phase removes).
    read_context optional — one throwaway context per call when
    omitted.
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    requirements: list = []
    for stage_id in _stage_ids_for_roadmap(roadmap_id, read_context=context):
        reqs, _ = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
        requirements.extend(reqs)
    return tuple(requirements)


def evaluate_roadmap_requirements(roadmap_id: str, *, read_context: RequirementsReadContext | None = None) -> RequirementsSummary:
    """Read-only aggregate over every stage of this roadmap. A
    configuration error on ANY constituent stage propagates upward —
    the roadmap can never be reported safely complete while a child
    stage has broken relation data, in deterministic stage order.

    Phase 16C.1B1: shares ONE read_context across every stage and the
    final per-requirement evaluation pass — read_context optional, one
    throwaway context per call when omitted.
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    all_requirements: list = []
    all_errors: list = []
    for stage_id in _stage_ids_for_roadmap(roadmap_id, read_context=context):
        reqs, errs = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
        all_requirements.extend(reqs)
        all_errors.extend(errs)
    statuses = tuple(_evaluate_requirement(r, read_context=context) for r in all_requirements)
    return _summarize("roadmap", roadmap_id, statuses, configuration_errors=tuple(all_errors))


def get_requirements_for_object(object_id: str, *, read_context: RequirementsReadContext | None = None) -> tuple:
    """Read-only: every requirement across every roadmap whose Object
    ID matches — an object has no independent requirement source of
    its own either (see module docstring); it is reached only through
    its roadmap(s).

    Phase 16C.1B1: shares ONE read_context across every roadmap/stage —
    read_context optional, one throwaway context per call when omitted.
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    requirements: list = []
    for roadmap_id in _roadmap_ids_for_object(object_id, read_context=context):
        for stage_id in _stage_ids_for_roadmap(roadmap_id, read_context=context):
            reqs, _ = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
            requirements.extend(reqs)
    return tuple(requirements)


def evaluate_object_requirements(object_id: str, *, read_context: RequirementsReadContext | None = None) -> RequirementsSummary:
    """Read-only aggregate over every roadmap tied to this object. A
    configuration error on any descendant stage propagates all the way
    up, in deterministic roadmap-then-stage order.

    Phase 16C.1B1: shares ONE read_context across every roadmap/stage
    and the final per-requirement evaluation pass — read_context
    optional, one throwaway context per call when omitted.
    """
    context = read_context if read_context is not None else RequirementsReadContext()
    all_requirements: list = []
    all_errors: list = []
    for roadmap_id in _roadmap_ids_for_object(object_id, read_context=context):
        for stage_id in _stage_ids_for_roadmap(roadmap_id, read_context=context):
            reqs, errs = _resolve_stage_requirements_and_errors(stage_id, read_context=context)
            all_requirements.extend(reqs)
            all_errors.extend(errs)
    statuses = tuple(_evaluate_requirement(r, read_context=context) for r in all_requirements)
    return _summarize("object", object_id, statuses, configuration_errors=tuple(all_errors))
