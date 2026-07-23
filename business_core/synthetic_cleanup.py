"""
Phase 18E: guarded synthetic-data cleanup utility.

Strictly a one-off, explicitly-invoked maintenance tool for removing
synthetic test records created during a controlled smoke test (e.g.
Phase 18D). This module is deliberately isolated:

- it is NEVER imported by telegram_handlers.py, telegram_bot.py, or
  any other runtime/production code path;
- it has no Telegram command wired to it;
- it only acts on an explicit, caller-supplied allowlist of IDs —
  it never discovers records by prefix scan or pattern match.

Safety model (see cleanup_synthetic_records()'s own docstring for the
full algorithm):
  1. A fixed set of real, load-bearing IDs is hard-refused regardless
     of what the caller passes in (PROTECTED_IDS).
  2. Every candidate ID must carry (directly, or via its validated-
     synthetic parent) an explicit human-readable synthetic marker
     ("SYNTHETIC TEST") before it can ever be deleted.
  3. Every candidate ID is checked for inbound references from any
     OTHER record not itself in the caller's allowlist — such a
     reference blocks deletion.
  4. dry_run=True (the default) performs zero writes; it only
     computes and returns the plan.
  5. Live deletion re-resolves each row's current physical row number
     by ID immediately before deleting it (never reuses a row number
     computed during planning), deletes bottom-up within each sheet,
     and verifies absence immediately afterward.
"""

from __future__ import annotations

from dataclasses import dataclass

# Real, load-bearing IDs that this utility must never delete, no
# matter what a caller's allowlist contains. This is a structural
# guarantee, not just caller discipline.
PROTECTED_IDS = frozenset({
    "RM-001", "SVC-IZH-001",
    "STAGE-001", "STAGE-002", "STAGE-003", "STAGE-004",
    "STAGE-005", "STAGE-006", "STAGE-007", "STAGE-008",
    "REL-001", "REL-002", "REL-003", "REL-004", "REL-005",
    "REL-006", "REL-007", "REL-008", "REL-009",
})

# ID prefix -> sheet_key. Longest/most-specific prefixes are checked
# first by the caller (order matters only in that "REL-" and "RM-"
# never collide with each other's prefixes today).
_ID_PREFIX_SHEET = {
    "PRS-": "people_registry",
    "OBJ-": "object_registry",
    "RM-": "roadmaps",
    "STAGE-": "roadmap_stages",
    "REL-": "stage_entity_relations",
}

_ID_COLUMN = {
    "people_registry": "ID",
    "object_registry": "OBJ ID",
    "roadmaps": "Roadmap ID",
    "roadmap_stages": "Stage ID",
    "stage_entity_relations": "Relation ID",
}

# Sheets/columns that carry a direct, human-readable synthetic marker.
_MARKER_COLUMN = {
    "people_registry": "Комментарий",
    "object_registry": "Notes",
    "roadmaps": "Notes",
}
_MARKER_SUBSTRING = "SYNTHETIC TEST"

# Deletion is only correct in this order: leaf relations, then the
# stages they belong to, then the roadmap, then the object, then the
# person — matching business_core/synthetic_cleanup.py's own dependency
# audit (Phase 18E Part A/C).
_SHEET_DELETION_ORDER = (
    "stage_entity_relations", "roadmap_stages", "roadmaps", "object_registry", "people_registry",
)

# For a given sheet, which other (sheet_key, column) pairs might hold
# an inbound reference to one of its own IDs.
_INBOUND_REFERENCE_FIELDS = {
    "people_registry": [("roadmaps", "Client ID"), ("object_registry", "Client ID")],
    "object_registry": [("roadmaps", "Object ID")],
    "roadmaps": [("object_registry", "Roadmap ID"), ("roadmap_stages", "Roadmap ID")],
    "roadmap_stages": [("stage_entity_relations", "Stage ID")],
    "stage_entity_relations": [],
}


def _sheet_for_id(record_id: str) -> str | None:
    for prefix, sheet_key in _ID_PREFIX_SHEET.items():
        if record_id.startswith(prefix):
            return sheet_key
    return None


@dataclass(frozen=True)
class CleanupResult:
    ok: bool = True
    dry_run: bool = True
    planned: tuple = ()             # (id, sheet_key) in deletion order
    deleted: tuple = ()              # ids actually deleted (live mode only)
    skipped: tuple = ()               # (id, reason) — e.g. already absent
    blocked: tuple = ()                # (id, reason) — refused, never touched
    warnings: tuple = ()
    verification_errors: tuple = ()    # (id, detail) — deleted but still found afterward, or exception


def _is_synthetic(record_id: str, allowlist: set, cache: dict) -> tuple[bool, str]:
    """
    Read-only. Determines whether `record_id` is genuinely synthetic:
      - people_registry / object_registry / roadmaps: their own marker
        column must contain "SYNTHETIC TEST";
      - roadmap_stages: its Roadmap ID must be in the allowlist AND
        that roadmap must itself validate as synthetic;
      - stage_entity_relations: its Stage ID must be in the allowlist
        AND that stage must itself validate as synthetic.
    Never trusts the caller's allowlist alone — always re-checks
    against the live row.
    """
    from business_core.sheets import find_row_by_id

    if record_id in cache:
        return cache[record_id]

    sheet_key = _sheet_for_id(record_id)
    if sheet_key is None:
        cache[record_id] = (False, f"Unknown ID prefix: {record_id!r}")
        return cache[record_id]

    found = find_row_by_id(sheet_key, record_id)
    if found is None:
        cache[record_id] = (False, "not found (already absent)")
        return cache[record_id]
    _, row = found

    if sheet_key in _MARKER_COLUMN:
        marker_value = row.get(_MARKER_COLUMN[sheet_key], "") or ""
        ok = _MARKER_SUBSTRING in marker_value
        cache[record_id] = (ok, "" if ok else f"missing synthetic marker in {_MARKER_COLUMN[sheet_key]!r}")
        return cache[record_id]

    if sheet_key == "roadmap_stages":
        parent_id = row.get("Roadmap ID", "")
        if parent_id not in allowlist:
            cache[record_id] = (False, f"parent Roadmap ID {parent_id!r} not in allowlist")
            return cache[record_id]
        parent_ok, parent_reason = _is_synthetic(parent_id, allowlist, cache)
        cache[record_id] = (parent_ok, parent_reason if not parent_ok else "")
        return cache[record_id]

    if sheet_key == "stage_entity_relations":
        parent_id = row.get("Stage ID", "")
        if not parent_id or parent_id not in allowlist:
            cache[record_id] = (False, f"parent Stage ID {parent_id!r} not in allowlist")
            return cache[record_id]
        parent_ok, parent_reason = _is_synthetic(parent_id, allowlist, cache)
        cache[record_id] = (parent_ok, parent_reason if not parent_ok else "")
        return cache[record_id]

    cache[record_id] = (False, "no marker rule defined for this sheet")
    return cache[record_id]


def _inbound_blockers(record_id: str, allowlist: set) -> list[str]:
    """
    Read-only. Returns a list of human-readable descriptions of any
    reference to `record_id` from a row whose OWN ID is not itself in
    the caller's allowlist. An empty list means safe to delete from a
    referential-integrity standpoint.
    """
    from business_core.sheets import read_business_sheet

    sheet_key = _sheet_for_id(record_id)
    if sheet_key is None:
        return [f"unknown ID prefix: {record_id!r}"]

    blockers = []
    for ref_sheet_key, ref_column in _INBOUND_REFERENCE_FIELDS.get(sheet_key, []):
        ref_id_column = _ID_COLUMN[ref_sheet_key]
        for row in read_business_sheet(ref_sheet_key):
            if row.get(ref_column, "") != record_id:
                continue
            referencing_id = row.get(ref_id_column, "")
            if referencing_id and referencing_id not in allowlist:
                blockers.append(
                    f"{ref_sheet_key}.{referencing_id} references this via {ref_column!r}, "
                    f"and {referencing_id!r} is not in the allowlist"
                )
    return blockers


def plan_cleanup(allowlist_ids: list[str]) -> CleanupResult:
    """
    Strictly read-only. Computes the exact deletion plan without
    writing anything — this IS the dry-run report.
    """
    allowlist = set(allowlist_ids)
    marker_cache: dict = {}

    blocked = []
    planned_by_sheet: dict[str, list[str]] = {k: [] for k in _SHEET_DELETION_ORDER}
    skipped = []
    warnings = []

    for record_id in allowlist_ids:
        if record_id in PROTECTED_IDS:
            blocked.append((record_id, "protected ID — this utility refuses to touch it regardless of input"))
            continue

        sheet_key = _sheet_for_id(record_id)
        if sheet_key is None:
            blocked.append((record_id, f"unknown ID prefix — refused"))
            continue

        from business_core.sheets import find_row_by_id
        found = find_row_by_id(sheet_key, record_id)
        if found is None:
            skipped.append((record_id, "already absent — nothing to delete (idempotent)"))
            continue

        is_synth, reason = _is_synthetic(record_id, allowlist, marker_cache)
        if not is_synth:
            blocked.append((record_id, f"synthetic-marker validation failed: {reason}"))
            continue

        blockers = _inbound_blockers(record_id, allowlist)
        if blockers:
            blocked.append((record_id, "blocked by non-allowlisted inbound reference(s): " + "; ".join(blockers)))
            continue

        planned_by_sheet[sheet_key].append(record_id)

    planned = tuple(
        (record_id, sheet_key)
        for sheet_key in _SHEET_DELETION_ORDER
        for record_id in planned_by_sheet[sheet_key]
    )

    return CleanupResult(
        ok=True, dry_run=True,
        planned=planned, deleted=(), skipped=tuple(skipped), blocked=tuple(blocked),
        warnings=tuple(warnings), verification_errors=(),
    )


def cleanup_synthetic_records(allowlist_ids: list[str], dry_run: bool = True) -> CleanupResult:
    """
    Compute the deletion plan (identical logic to plan_cleanup()); if
    dry_run is False, execute it.

    Execution behavior:
      - processes sheets in _SHEET_DELETION_ORDER (children before
        parents);
      - within one sheet, re-resolves EVERY still-pending ID's current
        row number via a single fresh read, then deletes strictly
        highest-row-number-first (bottom-up) so earlier deletions in
        the same batch never shift a not-yet-deleted row's index;
      - after each single-row delete, re-resolves the ID once more to
        confirm it is now absent — any ID still found is recorded in
        verification_errors, not silently ignored;
      - if a write raises (e.g. a transient Sheets API error), stops
        immediately, returns ok=False with everything confirmed
        deleted so far in `deleted` and the interrupting error in
        `warnings` — never retries automatically, never guesses at a
        stale row number afterward.
    """
    plan = plan_cleanup(allowlist_ids)
    if dry_run:
        return plan

    if not plan.planned:
        return CleanupResult(
            ok=True, dry_run=False, planned=plan.planned, deleted=(),
            skipped=plan.skipped, blocked=plan.blocked, warnings=plan.warnings,
            verification_errors=(),
        )

    from business_core.sheets import get_business_sheet, find_row_by_id

    deleted: list[str] = []
    verification_errors: list[tuple] = []
    warnings: list[str] = list(plan.warnings)

    by_sheet: dict[str, list[str]] = {k: [] for k in _SHEET_DELETION_ORDER}
    for record_id, sheet_key in plan.planned:
        by_sheet[sheet_key].append(record_id)

    for sheet_key in _SHEET_DELETION_ORDER:
        pending_ids = by_sheet[sheet_key]
        if not pending_ids:
            continue

        try:
            sheet = get_business_sheet(sheet_key)
            id_column = _ID_COLUMN[sheet_key]

            # Re-resolve every pending ID's CURRENT row number from a
            # single fresh read — never reuse a row number computed
            # during planning above.
            current_rows: dict[str, int] = {}
            for record_id in pending_ids:
                found = find_row_by_id(sheet_key, record_id)
                if found is None:
                    verification_errors.append((record_id, "vanished between planning and execution — skipped"))
                    continue
                row_num, _ = found
                current_rows[record_id] = row_num

            # Bottom-up within this sheet: highest row number first, so
            # deleting one row never shifts the index of another
            # not-yet-deleted row in this same batch.
            for record_id, row_num in sorted(current_rows.items(), key=lambda kv: kv[1], reverse=True):
                sheet.delete_rows(row_num)
                still_present = find_row_by_id(sheet_key, record_id)
                if still_present is not None:
                    verification_errors.append((record_id, "still present immediately after delete_rows()"))
                else:
                    deleted.append(record_id)

        except Exception as exc:
            warnings.append(f"Stopped during {sheet_key} deletion: {exc}")
            return CleanupResult(
                ok=False, dry_run=False,
                planned=plan.planned, deleted=tuple(deleted),
                skipped=plan.skipped, blocked=plan.blocked,
                warnings=tuple(warnings), verification_errors=tuple(verification_errors),
            )

    return CleanupResult(
        ok=not verification_errors, dry_run=False,
        planned=plan.planned, deleted=tuple(deleted),
        skipped=plan.skipped, blocked=plan.blocked,
        warnings=tuple(warnings), verification_errors=tuple(verification_errors),
    )
