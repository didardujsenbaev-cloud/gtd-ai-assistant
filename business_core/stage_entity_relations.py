"""
Phase 18C-1: Stage-to-Entity Relation Foundation — read-only.

STAGE_ENTITY_RELATIONS is the future-proof, stage-centric relation
table proposed in the Phase 18B architecture audit: one row = one
relationship between a stage (template or instantiated) and a
reusable Business Core entity (currently only document templates).

Relation direction is always stage -> entity, never a generic
source-to-target graph. Exactly one of "Template Stage ID"/"Stage ID"
is populated per row — this is what distinguishes a template-level
relation from an instantiated-roadmap-level relation (mirroring the
same stage_template_id/stage_id pair already reserved, but unused, on
business_core.document_requirements.DocumentRequirement).

Most of this module is read-only and additive. The one exception is
copy_template_relations_to_stage() (Phase 18C-3), which creates new
INSTANCE-scoped relation rows (never touches template-scoped rows,
never migrates the existing "Document Template IDs" comma-list
columns). Nothing in this module is yet consulted by
business_core.document_requirements.py or any Telegram command for
requirement evaluation.

Entity Type support is deliberately extensible without a schema
change: adding a new type is one new entry in ENTITY_TYPE_DISPATCH,
never a new column.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_BOOL_STRINGS = ("true", "false")
VALID_STATUSES = ("active", "inactive")

# Entity Type -> (target sheet_key, target ID column name). Adding a
# future Entity Type (sop/checklist/faq/...) is one new entry here,
# never a schema change to STAGE_ENTITY_RELATIONS itself.
ENTITY_TYPE_DISPATCH: dict[str, dict[str, str]] = {
    "document_template": {
        "sheet_key": "document_template_registry",
        "id_column": "Document Template ID",
    },
}


def _is_blank(value: str) -> bool:
    return not (value or "").strip()


# ─────────────────────────────────────────────────────────────
# Read-only listing
# ─────────────────────────────────────────────────────────────

def list_relations(include_inactive: bool = False) -> tuple[dict, ...]:
    """
    All STAGE_ENTITY_RELATIONS rows, in deterministic sheet order.
    Inactive rows are excluded by default (include_inactive=True to
    see them). Never filters out a structurally invalid or dangling
    row — that judgment belongs to validate_relation_record()/
    validate_relation_references(), not to this listing function.
    """
    from business_core.sheets import read_business_sheet

    rows = read_business_sheet("stage_entity_relations")
    if include_inactive:
        return tuple(rows)
    return tuple(r for r in rows if (r.get("Status", "") or "").strip() == "active")


def get_relation_by_id(relation_id: str) -> dict | None:
    """One relation row by its own Relation ID, regardless of Status —
    a direct-ID lookup should not silently hide an inactive row."""
    from business_core.sheets import find_row_by_id

    if not relation_id:
        return None
    found = find_row_by_id("stage_entity_relations", relation_id)
    return found[1] if found else None


def get_relations_for_template_stage(
    template_stage_id: str, entity_type: str | None = None, include_inactive: bool = False
) -> tuple[dict, ...]:
    """All relations whose Template Stage ID matches, in sheet order.
    Does not require Stage ID to be blank on the matched row — this is
    a read helper reflecting actual data, not a validity enforcer."""
    if not template_stage_id:
        return ()
    rows = list_relations(include_inactive=include_inactive)
    rows = tuple(r for r in rows if r.get("Template Stage ID", "") == template_stage_id)
    if entity_type is not None:
        rows = tuple(r for r in rows if r.get("Entity Type", "") == entity_type)
    return rows


def get_relations_for_stage(
    stage_id: str, entity_type: str | None = None, include_inactive: bool = False
) -> tuple[dict, ...]:
    """All relations whose (instantiated) Stage ID matches, in sheet
    order."""
    if not stage_id:
        return ()
    rows = list_relations(include_inactive=include_inactive)
    rows = tuple(r for r in rows if r.get("Stage ID", "") == stage_id)
    if entity_type is not None:
        rows = tuple(r for r in rows if r.get("Entity Type", "") == entity_type)
    return rows


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────

def validate_relation_record(record: dict) -> list[str]:
    """
    Structural validation only — never touches another sheet. Returns
    a list of human-readable error strings; empty list means
    structurally valid. Does not check that referenced IDs actually
    exist (see validate_relation_references() for that).
    """
    errors: list[str] = []

    template_stage_id = record.get("Template Stage ID", "") or ""
    stage_id = record.get("Stage ID", "") or ""
    template_populated = not _is_blank(template_stage_id)
    stage_populated = not _is_blank(stage_id)

    if template_populated and stage_populated:
        errors.append("Both Template Stage ID and Stage ID are populated — exactly one is required.")
    elif not template_populated and not stage_populated:
        errors.append("Neither Template Stage ID nor Stage ID is populated — exactly one is required.")

    entity_type = record.get("Entity Type", "") or ""
    if entity_type not in ENTITY_TYPE_DISPATCH:
        errors.append(
            f"Unsupported Entity Type: {entity_type!r}. "
            f"Supported: {', '.join(sorted(ENTITY_TYPE_DISPATCH))}."
        )

    entity_id = record.get("Entity ID", "") or ""
    if _is_blank(entity_id):
        errors.append("Entity ID is blank.")

    required = record.get("Required", "") or ""
    if required not in VALID_BOOL_STRINGS:
        errors.append(f"Required must be 'true' or 'false', got {required!r}.")

    blocking = record.get("Blocking", "") or ""
    if blocking not in VALID_BOOL_STRINGS:
        errors.append(f"Blocking must be 'true' or 'false', got {blocking!r}.")

    minimum_count = record.get("Minimum Count", "") or ""
    try:
        if int(str(minimum_count).strip()) < 1:
            errors.append(f"Minimum Count must be >= 1, got {minimum_count!r}.")
    except (TypeError, ValueError):
        errors.append(f"Minimum Count must be a positive integer string, got {minimum_count!r}.")

    status = record.get("Status", "") or ""
    if status not in VALID_STATUSES:
        errors.append(f"Status must be 'active' or 'inactive', got {status!r}.")

    return errors


def validate_relation_references(record: dict) -> list[str]:
    """
    Referential-integrity validation against other sheets — read-only.
    Never raises on a dangling reference and never hides it: a
    dangling Entity ID is reported as an error string here, exactly as
    it remains visible (never silently dropped) in the read helpers
    above.
    """
    from business_core.sheets import find_row_by_id

    errors: list[str] = []

    template_stage_id = record.get("Template Stage ID", "") or ""
    stage_id = record.get("Stage ID", "") or ""

    if not _is_blank(template_stage_id):
        if find_row_by_id("roadmap_template_stages", template_stage_id) is None:
            errors.append(f"Template Stage ID {template_stage_id!r} not found in ROADMAP_TEMPLATE_STAGES.")

    if not _is_blank(stage_id):
        if find_row_by_id("roadmap_stages", stage_id) is None:
            errors.append(f"Stage ID {stage_id!r} not found in ROADMAP_STAGES.")

    entity_type = record.get("Entity Type", "") or ""
    entity_id = record.get("Entity ID", "") or ""
    dispatch = ENTITY_TYPE_DISPATCH.get(entity_type)
    if dispatch is not None and not _is_blank(entity_id):
        found = find_row_by_id(dispatch["sheet_key"], entity_id)
        if found is None:
            errors.append(
                f"Entity ID {entity_id!r} not found in {dispatch['sheet_key']} "
                f"(column {dispatch['id_column']!r})."
            )

    return errors


def find_active_duplicate_relation(record: dict) -> dict | None:
    """
    Read-only check for an already-existing ACTIVE relation with the
    same logical unique key:
      - template scope: Template Stage ID + Entity Type + Entity ID
      - instance scope: Stage ID + Entity Type + Entity ID
    An inactive row with the same key never counts as a duplicate —
    it does not block creating a new active relation.
    Returns the matching existing row, or None.
    """
    template_stage_id = record.get("Template Stage ID", "") or ""
    stage_id = record.get("Stage ID", "") or ""
    entity_type = record.get("Entity Type", "") or ""
    entity_id = record.get("Entity ID", "") or ""
    candidate_relation_id = record.get("Relation ID", "") or ""

    active = list_relations(include_inactive=False)

    for row in active:
        if candidate_relation_id and row.get("Relation ID", "") == candidate_relation_id:
            continue  # never compare a record against itself
        if row.get("Entity Type", "") != entity_type:
            continue
        if row.get("Entity ID", "") != entity_id:
            continue
        if not _is_blank(template_stage_id):
            if row.get("Template Stage ID", "") == template_stage_id:
                return row
        elif not _is_blank(stage_id):
            if row.get("Stage ID", "") == stage_id:
                return row

    return None


# ─────────────────────────────────────────────────────────────
# Phase 18C-2: dual-read comparison against the legacy
# ROADMAP_TEMPLATE_STAGES."Document Template IDs" comma-list
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageComparisonResult:
    """Per-Template-Stage-ID comparison between the legacy comma-list
    and the new (document_template, active, template-scoped) relation
    rows. `ordered_match` is the single pass/fail signal; every other
    field explains exactly why, when it's False."""
    template_stage_id: str
    legacy_ids: tuple = ()
    new_ids: tuple = ()
    missing: tuple = ()                          # in legacy, absent from new
    extra: tuple = ()                             # in new, absent from legacy
    legacy_duplicate_ids: tuple = ()              # same ID repeated in the raw legacy comma-list
    duplicate_active_relations: tuple = ()        # same Entity ID has >1 active relation row for this stage
    invalid_relation_ids: tuple = ()              # Relation IDs failing validate_relation_record()
    dangling_entity_ids: tuple = ()               # Entity IDs absent from document_template_registry
    unsupported_entity_type_relation_ids: tuple = ()  # non-document_template relations at this stage
    ordered_match: bool = True


@dataclass(frozen=True)
class DocumentRelationAudit:
    """Whole-template dual-read result — covers every
    ROADMAP_TEMPLATE_STAGES row, not only the currently-populated
    pilot stages."""
    per_stage: tuple = ()
    orphan_relations: tuple = ()                  # relations whose Template Stage ID matches no real stage
    invalid_scope_relation_ids: tuple = ()         # relations with BOTH Template Stage ID and Stage ID populated
    total_legacy_configured_stages: int = 0
    total_new_configured_stages: int = 0
    is_globally_consistent: bool = True


def compare_legacy_document_relations() -> DocumentRelationAudit:
    """
    Strictly read-only. Compares, for EVERY row of
    ROADMAP_TEMPLATE_STAGES (not just the pilot subset), the legacy
    "Document Template IDs" comma-list against active, template-scoped
    STAGE_ENTITY_RELATIONS rows of Entity Type "document_template".

    Never raises on a dangling/invalid/orphan relation — every such
    case is surfaced in the returned result, never silently dropped
    or skipped, matching the same "never silently discard" discipline
    already established for the legacy engine (document_requirements.py).
    """
    from business_core.sheets import read_business_sheet
    from business_core.document_requirements import _parse_id_list

    template_stage_rows = read_business_sheet("roadmap_template_stages")
    known_stage_ids = {r.get("Stage ID", "") for r in template_stage_rows if r.get("Stage ID", "")}

    all_relations = list_relations(include_inactive=True)
    doc_template_ids = {
        t.get("Document Template ID", "") for t in read_business_sheet("document_template_registry")
    }

    orphan_relations = tuple(
        r for r in all_relations
        if not _is_blank(r.get("Template Stage ID", ""))
        and r.get("Template Stage ID", "") not in known_stage_ids
    )
    invalid_scope_relation_ids = tuple(
        r.get("Relation ID", "") for r in all_relations
        if not _is_blank(r.get("Template Stage ID", "")) and not _is_blank(r.get("Stage ID", ""))
    )

    per_stage: list[StageComparisonResult] = []
    total_legacy_configured = 0
    total_new_configured = 0

    for row in template_stage_rows:
        tstg_id = row.get("Stage ID", "")
        raw_legacy = row.get("Document Template IDs", "") or ""
        legacy_ids = tuple(_parse_id_list(raw_legacy))
        raw_tokens = [t.strip() for t in raw_legacy.split(",") if t.strip()]
        legacy_duplicate_ids = tuple(sorted({t for t in raw_tokens if raw_tokens.count(t) > 1}))

        stage_relations = tuple(r for r in all_relations if r.get("Template Stage ID", "") == tstg_id)
        doc_relations = tuple(r for r in stage_relations if r.get("Entity Type", "") == "document_template")
        unsupported_relation_ids = tuple(
            r.get("Relation ID", "") for r in stage_relations if r.get("Entity Type", "") != "document_template"
        )

        active_doc_relations = tuple(r for r in doc_relations if (r.get("Status", "") or "") == "active")
        new_ids = tuple(r.get("Entity ID", "") for r in active_doc_relations)

        seen_counts: dict[str, int] = {}
        for eid in new_ids:
            seen_counts[eid] = seen_counts.get(eid, 0) + 1
        duplicate_active_relations = tuple(sorted(e for e, c in seen_counts.items() if c > 1))

        invalid_relation_ids = tuple(
            r.get("Relation ID", "") for r in doc_relations if validate_relation_record(r)
        )
        dangling_entity_ids = tuple(sorted({
            r.get("Entity ID", "") for r in doc_relations
            if r.get("Entity ID", "") not in doc_template_ids
        }))

        new_ids_deduped_ordered = tuple(dict.fromkeys(new_ids))
        missing = tuple(e for e in legacy_ids if e not in new_ids_deduped_ordered)
        extra = tuple(e for e in new_ids_deduped_ordered if e not in legacy_ids)

        ordered_match = (
            not missing and not extra
            and not legacy_duplicate_ids and not duplicate_active_relations
            and not invalid_relation_ids and not dangling_entity_ids
            and legacy_ids == new_ids_deduped_ordered
        )

        if legacy_ids:
            total_legacy_configured += 1
        if new_ids_deduped_ordered:
            total_new_configured += 1

        per_stage.append(StageComparisonResult(
            template_stage_id=tstg_id,
            legacy_ids=legacy_ids,
            new_ids=new_ids_deduped_ordered,
            missing=missing,
            extra=extra,
            legacy_duplicate_ids=legacy_duplicate_ids,
            duplicate_active_relations=duplicate_active_relations,
            invalid_relation_ids=invalid_relation_ids,
            dangling_entity_ids=dangling_entity_ids,
            unsupported_entity_type_relation_ids=unsupported_relation_ids,
            ordered_match=ordered_match,
        ))

    is_globally_consistent = (
        not orphan_relations and not invalid_scope_relation_ids
        and all(s.ordered_match for s in per_stage)
    )

    return DocumentRelationAudit(
        per_stage=tuple(per_stage),
        orphan_relations=orphan_relations,
        invalid_scope_relation_ids=invalid_scope_relation_ids,
        total_legacy_configured_stages=total_legacy_configured,
        total_new_configured_stages=total_new_configured,
        is_globally_consistent=is_globally_consistent,
    )


# ─────────────────────────────────────────────────────────────
# Phase 18C-3: template -> instance relation inheritance
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CopyRelationsResult:
    """
    Result of copy_template_relations_to_stage(). `ok=False` means
    nothing was written this call (either a precondition failed or a
    source relation was structurally/referentially invalid) — creation
    is all-or-nothing per call, never a partial copy of only the valid
    subset, so a retry after fixing the underlying data cannot leave
    stray duplicate-of-half rows behind.

    `skipped_duplicates` (source Relation ID -> already-existing
    destination Relation ID) is NOT an error — it is exactly what makes
    a retry after a partial multi-stage failure idempotent: relations
    already copied for this stage are recognized and left alone,
    the remaining ones are created.
    """
    template_stage_id: str
    stage_id: str
    created: tuple = ()             # tuple of the new relation row dicts, in source order
    skipped_duplicates: tuple = ()  # tuple of (source_relation_id, existing_destination_relation_id)
    errors: tuple = ()              # tuple of (source_relation_id_or_marker, (error strings...))
    ok: bool = True


def copy_template_relations_to_stage(
    template_stage_id: str, stage_id: str, timestamp: str | None = None
) -> CopyRelationsResult:
    """
    Copy every ACTIVE template-scoped relation of `template_stage_id`
    into new instance-scoped (Stage ID = `stage_id`) relation rows.

    Deliberately generic over Entity Type — it copies whatever active
    relations exist on the source template stage (today always
    document_template, since that is the only ENTITY_TYPE_DISPATCH
    entry), never hardcoding a document-only branch. A future Entity
    Type is copied automatically the moment it has a dispatch entry
    and a source relation row — no change needed here.

    Preconditions enforced BEFORE any write:
      - the destination ROADMAP_STAGE must already exist (never create
        a relation before its stage exists);
      - every source relation must pass both validate_relation_record()
        and validate_relation_references() — an invalid/dangling
        source relation aborts the whole call with a clear error,
        rather than being silently skipped or partially copied.

    Idempotent: a relation whose (Stage ID, Entity Type, Entity ID)
    already exists as an ACTIVE destination relation is recognized via
    find_active_duplicate_relation() and skipped, not recreated — a
    retry after a partial multi-stage failure therefore never produces
    duplicate active instance relations.

    Performs no legacy "Document Template IDs" column changes — that
    inheritance path is untouched and unrelated to this function.
    """
    from business_core.sheets import (
        find_row_by_id, generate_next_ids, batch_append_business_rows,
        get_business_sheet, row_from_header_map,
    )
    from datetime import datetime

    if not template_stage_id or not stage_id:
        return CopyRelationsResult(
            template_stage_id=template_stage_id, stage_id=stage_id,
            errors=(("__precondition__", ("template_stage_id and stage_id are both required.",)),),
            ok=False,
        )

    if find_row_by_id("roadmap_stages", stage_id) is None:
        return CopyRelationsResult(
            template_stage_id=template_stage_id, stage_id=stage_id,
            errors=((
                "__precondition__",
                (f"Destination Stage ID {stage_id!r} does not exist yet in ROADMAP_STAGES — "
                 f"refusing to create relations before its row exists.",),
            ),),
            ok=False,
        )

    source_relations = get_relations_for_template_stage(template_stage_id)  # active only, sheet order

    if not source_relations:
        return CopyRelationsResult(template_stage_id=template_stage_id, stage_id=stage_id)

    validation_errors = []
    for rel in source_relations:
        rel_errors = tuple(validate_relation_record(rel)) + tuple(validate_relation_references(rel))
        if rel_errors:
            validation_errors.append((rel.get("Relation ID", ""), rel_errors))

    if validation_errors:
        return CopyRelationsResult(
            template_stage_id=template_stage_id, stage_id=stage_id,
            errors=tuple(validation_errors), ok=False,
        )

    to_create = []
    skipped_duplicates = []
    for rel in source_relations:
        candidate = {
            "Template Stage ID": "", "Stage ID": stage_id,
            "Entity Type": rel.get("Entity Type", ""), "Entity ID": rel.get("Entity ID", ""),
        }
        existing = find_active_duplicate_relation(candidate)
        if existing is not None:
            skipped_duplicates.append((rel.get("Relation ID", ""), existing.get("Relation ID", "")))
        else:
            to_create.append(rel)

    if not to_create:
        return CopyRelationsResult(
            template_stage_id=template_stage_id, stage_id=stage_id,
            skipped_duplicates=tuple(skipped_duplicates),
        )

    ts = timestamp or datetime.now().strftime("%Y-%m-%d")
    sheet = get_business_sheet("stage_entity_relations")
    headers = sheet.row_values(1)
    new_relation_ids = generate_next_ids("stage_entity_relations", len(to_create))

    rows = []
    created_records = []
    for rel, new_id in zip(to_create, new_relation_ids):
        values = {
            "Relation ID": new_id,
            "Template Stage ID": "",
            "Stage ID": stage_id,
            "Entity Type": rel.get("Entity Type", ""),
            "Entity ID": rel.get("Entity ID", ""),
            "Required": rel.get("Required", ""),
            "Blocking": rel.get("Blocking", ""),
            "Minimum Count": rel.get("Minimum Count", ""),
            "Status": "active",
            "Created At": ts,
            "Updated At": ts,
        }
        rows.append(row_from_header_map(headers, values))
        created_records.append(values)

    try:
        batch_append_business_rows("stage_entity_relations", rows)
    except Exception as exc:
        return CopyRelationsResult(
            template_stage_id=template_stage_id, stage_id=stage_id,
            skipped_duplicates=tuple(skipped_duplicates),
            errors=(("__write_failure__", (str(exc),)),),
            ok=False,
        )

    return CopyRelationsResult(
        template_stage_id=template_stage_id, stage_id=stage_id,
        created=tuple(created_records),
        skipped_duplicates=tuple(skipped_duplicates),
    )
