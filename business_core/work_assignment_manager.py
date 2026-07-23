"""
Work Assignment Manager — Phase 22B: Work Execution Foundation.

Connects Roadmap Stages to Organization Layer Roles, and Roles to the
Person currently holding them. Implements exactly the architecture
approved in Phase 22A, with two adjustments approved before this phase:

  1. Only Entity Type "role" is implemented. "contractor_person" (a
     direct PEOPLE_REGISTRY link bypassing Role) remains deferred until
     a real business case exists — see ARCHITECTURE.md / Work Execution
     Layer.
  2. Vacancy is a terminal, reported status ("vacant") — this module
     never walks the Reports To Role ID hierarchy to auto-escalate.
     Escalation stays a reporting concern for a future phase.

Design decision (unchanged from Phase 22A): there is no new registry.
A "Stage Responsibility" is an ordinary STAGE_ENTITY_RELATIONS row with
Entity Type="role", Entity ID=<Role ID> — reusing the exact mechanism
Phase 18C-1 built for this purpose (ENTITY_TYPE_DISPATCH). This module
never modifies ROADMAP_STAGES, ROADMAPS, the Responsible free-text
field, GTD Core, or the Organization Layer's own write paths (Role/
Assignment writes always go through business_core.organization_manager's
existing public functions, never around them).

resolve_stage_responsibility() returns ONLY one of four structured
statuses — "assigned" / "vacant" / "unconfigured" / "configuration_error"
— never a free-text message as the primary signal. Auxiliary "errors"
strings exist only for diagnostic/logging purposes, never for a caller
to branch on instead of `status`.

Zero business logic lives in a future Telegram layer beyond formatting
this structured result — see ENGINEERING_STANDARDS.md, Module Standards.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

RESOLUTION_STATUS = ("assigned", "vacant", "unconfigured", "configuration_error")

_ROLE_ENTITY_TYPE = "role"


def _resolution_result(
    *, status: str, stage_id: str,
    role_id: Optional[str] = None, person_id: Optional[str] = None,
    relation_id: Optional[str] = None, errors: tuple = (),
) -> dict:
    """Shared result-builder — every resolution outcome uses this exact
    shape, so callers never need to special-case one status's dict keys
    versus another's."""
    return {
        "status": status,
        "stage_id": stage_id,
        "role_id": role_id,
        "person_id": person_id,
        "relation_id": relation_id,
        "errors": tuple(errors),
    }


def _pick_person_for_role(assignments: tuple) -> Optional[dict]:
    """
    Automatic Person Resolution (Phase 22A §6): given the active
    Assignments for one Role, deterministically pick exactly one.

    Precedence: "temporary" (most recent Start Date) > "primary" >
    "backup". Ties within a precedence level break on earliest
    Start Date. Never raises on more than one Assignment at the same
    precedence level (a data anomaly Organization Layer's own write
    path does not prevent) — silently deterministic, not flagged, since
    Phase 22B's approved scope does not add a new diagnostic field for
    this beyond what's already asked.
    """
    if not assignments:
        return None

    def _bucket(a):
        t = a.get("assignment_type", "")
        if t == "temporary":
            return 0
        if t == "primary":
            return 1
        return 2  # "backup" or anything else

    ordered = sorted(assignments, key=lambda a: (_bucket(a), a.get("start_date", "") or ""))
    # "temporary" wins on MOST RECENT start date, everything else on
    # EARLIEST — re-sort just the temporary bucket in reverse.
    temporary = [a for a in assignments if a.get("assignment_type", "") == "temporary"]
    if temporary:
        temporary.sort(key=lambda a: a.get("start_date", "") or "", reverse=True)
        return temporary[0]
    return ordered[0]


def get_responsible_role_for_stage(stage_id: str) -> Optional[str]:
    """
    Read-only. The Role ID currently linked to this stage via an active
    "role"-type STAGE_ENTITY_RELATIONS row, or None if no such relation
    exists. Does NOT validate that the Role still exists/is active —
    that judgment belongs to resolve_stage_responsibility(); this is the
    lower-level primitive.
    """
    if not stage_id:
        return None
    try:
        from business_core.stage_entity_relations import get_relations_for_stage

        relations = get_relations_for_stage(stage_id, entity_type=_ROLE_ENTITY_TYPE)
        if not relations:
            return None
        return relations[0].get("Entity ID", "") or None
    except Exception as exc:
        log.warning(f"get_responsible_role_for_stage({stage_id}) error: {exc}")
        return None


def resolve_stage_responsibility(stage_id: str) -> dict:
    """
    The single entry point of the Responsibility Resolution Flow
    (Phase 22A §5). Read-only — never writes anything.

    Returns exactly one of:
      "assigned"            — an active Role relation exists, the Role
                               exists and is not archived, and it has a
                               resolvable active Assignment.
      "vacant"               — same as above, but the Role has zero
                               active Assignments. Terminal — no
                               hierarchy walk-up (Phase 22A adjustment 2).
      "unconfigured"         — no active Role relation exists for this
                               stage at all.
      "configuration_error"  — stage_id missing/not found, or the
                               relation points at a Role that doesn't
                               exist or is archived. `errors` explains
                               why; never silently hidden.
    """
    if not stage_id:
        return _resolution_result(
            status="configuration_error", stage_id=stage_id or "",
            errors=("stage_id обязателен",),
        )

    try:
        from business_core.sheets import find_row_by_id

        if find_row_by_id("roadmap_stages", stage_id) is None:
            return _resolution_result(
                status="configuration_error", stage_id=stage_id,
                errors=(f"Stage '{stage_id}' не найден",),
            )
    except Exception as exc:
        log.error(f"resolve_stage_responsibility({stage_id}) stage lookup error: {exc}")
        return _resolution_result(
            status="configuration_error", stage_id=stage_id,
            errors=(str(exc),),
        )

    try:
        from business_core.stage_entity_relations import get_relations_for_stage

        relations = get_relations_for_stage(stage_id, entity_type=_ROLE_ENTITY_TYPE)
    except Exception as exc:
        log.error(f"resolve_stage_responsibility({stage_id}) relation lookup error: {exc}")
        return _resolution_result(
            status="configuration_error", stage_id=stage_id,
            errors=(str(exc),),
        )

    if not relations:
        return _resolution_result(status="unconfigured", stage_id=stage_id)

    relation = relations[0]
    relation_id = relation.get("Relation ID", "")
    role_id = relation.get("Entity ID", "")

    try:
        from business_core.organization_manager import find_role_by_id, list_assignments_for_role

        role = find_role_by_id(role_id)
    except Exception as exc:
        log.error(f"resolve_stage_responsibility({stage_id}) role lookup error: {exc}")
        return _resolution_result(
            status="configuration_error", stage_id=stage_id, relation_id=relation_id,
            errors=(str(exc),),
        )

    if role is None:
        return _resolution_result(
            status="configuration_error", stage_id=stage_id, relation_id=relation_id,
            errors=(f"Role '{role_id}' не найден (relation {relation_id})",),
        )

    if role["status"] == "archived":
        return _resolution_result(
            status="configuration_error", stage_id=stage_id, role_id=role_id, relation_id=relation_id,
            errors=(f"Role '{role_id}' архивирована",),
        )

    assignments = list_assignments_for_role(role_id, status="active")

    if not assignments:
        return _resolution_result(
            status="vacant", stage_id=stage_id, role_id=role_id, relation_id=relation_id,
        )

    chosen = _pick_person_for_role(assignments)
    return _resolution_result(
        status="assigned", stage_id=stage_id, role_id=role_id, relation_id=relation_id,
        person_id=chosen.get("person_id", ""),
    )


def assign_role_to_stage(stage_id: str, role_id: str) -> dict:
    """
    Create a new "role"-type STAGE_ENTITY_RELATIONS row linking `stage_id`
    to `role_id`. Refuses to create a second active Role relation on a
    stage that already has one — call reassign_stage_role() instead
    (keeps "exactly one active Role relation per stage" enforced at the
    write boundary, not left to resolution-time luck).

    Returns:
        {"ok": bool, "relation_id": str, "error": str | None}
    """
    if not stage_id:
        return {"ok": False, "relation_id": "", "error": "stage_id обязателен"}
    if not role_id:
        return {"ok": False, "relation_id": "", "error": "role_id обязателен"}

    try:
        from business_core.sheets import find_row_by_id

        if find_row_by_id("roadmap_stages", stage_id) is None:
            return {"ok": False, "relation_id": "", "error": f"Stage '{stage_id}' не найден"}
    except Exception as exc:
        log.error(f"assign_role_to_stage stage lookup error: {exc}")
        return {"ok": False, "relation_id": "", "error": str(exc)}

    try:
        from business_core.organization_manager import find_role_by_id

        role = find_role_by_id(role_id)
    except Exception as exc:
        log.error(f"assign_role_to_stage role lookup error: {exc}")
        return {"ok": False, "relation_id": "", "error": str(exc)}

    if role is None:
        return {"ok": False, "relation_id": "", "error": f"Role '{role_id}' не найден"}
    if role["status"] == "archived":
        return {"ok": False, "relation_id": "", "error": f"Role '{role_id}' архивирована"}

    try:
        from business_core.stage_entity_relations import get_relations_for_stage, find_active_duplicate_relation

        existing = get_relations_for_stage(stage_id, entity_type=_ROLE_ENTITY_TYPE)
        if existing:
            return {
                "ok": False, "relation_id": "",
                "error": (
                    f"У stage '{stage_id}' уже есть активная Role-relation "
                    f"({existing[0].get('Relation ID', '')}) — используй reassign_stage_role()"
                ),
            }

        candidate = {
            "Stage ID": stage_id, "Template Stage ID": "",
            "Entity Type": _ROLE_ENTITY_TYPE, "Entity ID": role_id,
        }
        duplicate = find_active_duplicate_relation(candidate)
        if duplicate is not None:
            return {
                "ok": False, "relation_id": "",
                "error": f"Активная relation уже существует: {duplicate.get('Relation ID', '')}",
            }
    except Exception as exc:
        log.error(f"assign_role_to_stage duplicate check error: {exc}")
        return {"ok": False, "relation_id": "", "error": str(exc)}

    try:
        return _create_role_relation(stage_id, role_id)
    except Exception as exc:
        log.error(f"assign_role_to_stage write error: {exc}")
        return {"ok": False, "relation_id": "", "error": str(exc)}


def _create_role_relation(stage_id: str, role_id: str) -> dict:
    """Internal: write one new active role-relation row. No validation —
    callers (assign_role_to_stage/reassign_stage_role) must validate
    first."""
    from business_core.sheets import (
        get_business_sheet, generate_next_ids, batch_append_business_rows, row_from_header_map,
    )
    from datetime import datetime

    ts = datetime.now().strftime("%Y-%m-%d")
    sheet = get_business_sheet("stage_entity_relations")
    headers = sheet.row_values(1)
    relation_id = generate_next_ids("stage_entity_relations", 1)[0]

    values = {
        "Relation ID": relation_id,
        "Template Stage ID": "",
        "Stage ID": stage_id,
        "Entity Type": _ROLE_ENTITY_TYPE,
        "Entity ID": role_id,
        "Required": "true",
        "Blocking": "false",
        "Minimum Count": "1",
        "Status": "active",
        "Created At": ts,
        "Updated At": ts,
    }
    row = row_from_header_map(headers, values)
    batch_append_business_rows("stage_entity_relations", [row])

    log.info(f"assign_role_to_stage: {relation_id} / stage={stage_id} role={role_id}")
    return {"ok": True, "relation_id": relation_id, "error": None}


def reassign_stage_role(stage_id: str, new_role_id: str) -> dict:
    """
    Change which Role is responsible for a stage: deactivates the
    current active Role relation (Status=inactive — never deleted, full
    history preserved, same versioning convention already used
    throughout STAGE_ENTITY_RELATIONS) and creates a new active one for
    `new_role_id`. Idempotent: if the stage's current active Role
    relation already points at `new_role_id`, this is a no-op
    (ok=True, changed=False).

    If no active Role relation exists yet for this stage, behaves like
    a plain assign_role_to_stage() call (creates the first one).

    Returns:
        {"ok": bool, "changed": bool, "old_relation_id": str | None,
         "new_relation_id": str | None, "error": str | None}
    """
    if not stage_id:
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                "error": "stage_id обязателен"}
    if not new_role_id:
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                "error": "new_role_id обязателен"}

    try:
        from business_core.sheets import find_row_by_id

        if find_row_by_id("roadmap_stages", stage_id) is None:
            return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                    "error": f"Stage '{stage_id}' не найден"}
    except Exception as exc:
        log.error(f"reassign_stage_role stage lookup error: {exc}")
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None, "error": str(exc)}

    try:
        from business_core.organization_manager import find_role_by_id

        role = find_role_by_id(new_role_id)
    except Exception as exc:
        log.error(f"reassign_stage_role role lookup error: {exc}")
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None, "error": str(exc)}

    if role is None:
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                "error": f"Role '{new_role_id}' не найден"}
    if role["status"] == "archived":
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                "error": f"Role '{new_role_id}' архивирована"}

    try:
        from business_core.stage_entity_relations import get_relations_for_stage

        existing = get_relations_for_stage(stage_id, entity_type=_ROLE_ENTITY_TYPE)
    except Exception as exc:
        log.error(f"reassign_stage_role existing-relation lookup error: {exc}")
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None, "error": str(exc)}

    if not existing:
        result = _create_role_relation(stage_id, new_role_id)
        return {
            "ok": result["ok"], "changed": result["ok"],
            "old_relation_id": None, "new_relation_id": result["relation_id"] or None,
            "error": result["error"],
        }

    current = existing[0]
    if current.get("Entity ID", "") == new_role_id:
        return {
            "ok": True, "changed": False,
            "old_relation_id": current.get("Relation ID", ""), "new_relation_id": current.get("Relation ID", ""),
            "error": None,
        }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime

        sheet = get_business_sheet("stage_entity_relations")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        cell = sheet.find(current.get("Relation ID", ""), in_column=1)
        if not cell:
            return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None,
                    "error": f"Relation '{current.get('Relation ID', '')}' не найдена в листе"}

        sheet.update_cell(cell.row, idx["Status"] + 1, "inactive")
        if "Updated At" in idx:
            sheet.update_cell(cell.row, idx["Updated At"] + 1, datetime.now().strftime("%Y-%m-%d"))
    except Exception as exc:
        log.error(f"reassign_stage_role deactivation error: {exc}")
        return {"ok": False, "changed": False, "old_relation_id": None, "new_relation_id": None, "error": str(exc)}

    result = _create_role_relation(stage_id, new_role_id)
    if not result["ok"]:
        return {
            "ok": False, "changed": True,  # old relation IS already deactivated
            "old_relation_id": current.get("Relation ID", ""), "new_relation_id": None,
            "error": result["error"],
        }

    log.info(f"reassign_stage_role: stage={stage_id} {current.get('Entity ID', '')} -> {new_role_id}")
    return {
        "ok": True, "changed": True,
        "old_relation_id": current.get("Relation ID", ""), "new_relation_id": result["relation_id"],
        "error": None,
    }
