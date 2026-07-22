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

This module is strictly read-only and additive: it does not write any
relation row, does not migrate the existing "Document Template IDs"
comma-list columns, and is not yet consulted by
business_core.document_requirements.py or any Telegram command. It
only reads via business_core.sheets' existing
read_business_sheet()/find_row_by_id().

Entity Type support is deliberately extensible without a schema
change: adding a new type is one new entry in ENTITY_TYPE_DISPATCH,
never a new column.
"""

from __future__ import annotations

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
