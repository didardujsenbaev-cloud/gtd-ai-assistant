"""
Stage Dependencies Foundation (2026-07-28, DECISIONS.md §14a).

Sole transactional owner of TEMPLATE_STAGE_DEPENDENCIES — a Template
Stage -> Template Stage prerequisite graph, deliberately its OWN table,
never an ENTITY_TYPE_DISPATCH entry in stage_entity_relations.py. That
module's own docstring states relation direction is "always stage ->
entity, never a generic source-to-target graph" — a Stage-to-Stage
dependency IS exactly such a graph, and this module exists precisely so
that invariant is never bent to accommodate it.

No live dependency instances exist or are ever created. Dependencies are
resolved dynamically at transition time via the existing Template Stage
<-> live Stage Order-join mechanism (business_core.roadmap_manager.
resolve_template_stage_for_stage() for Stage->Template Stage; this
module's own resolve_live_stage_dependencies() for the reverse
Template-Stage-prerequisite->live-Stage direction, using the SAME
Order-as-technical-join-key principle — Order remains display/identity
only, per DECISIONS.md §14/§14a, never treated as a dependency itself).

Cycle prevention has two distinct, deliberately different-purpose
layers:
  - create_template_stage_dependency() runs a full DFS over the ENTIRE
    active dependency graph of one Roadmap Template ID before writing —
    this is the actual prevention mechanism (self/cross-template/direct/
    indirect cycles are all rejected here, before any row exists).
  - detect_reachable_cycle_from_template_stage() is a SEPARATE, bounded
    (default 200 nodes) read-time defense used only inside the
    Dependency Gate (business_builder._evaluate_stage_dependency_gate())
    against data that became corrupted AFTER creation (e.g. a manually
    edited Sheet row bypassing the write-time check) — it never adds a
    hypothetical edge, only detects a cycle already present in the
    currently-stored graph, reachable from one Template Stage.

Dependencies: only business_core.sheets and business_core.roadmap_manager
(read-only). GTD Core is never imported.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)


DEPENDENCY_TYPES = ("finish_to_start",)
SATISFYING_STAGE_STATUSES = frozenset({"done", "skipped"})

_CREATE_TIME_CYCLE_NODE_LIMIT = 1000  # generous — one-time write-path check
_GATE_TIME_CYCLE_NODE_LIMIT = 200     # bounded corrupted-data defense, read on every gate check

_DEPENDENCY_FIELDS = [
    "Dependency ID", "Roadmap Template ID", "Template Stage ID",
    "Depends On Template Stage ID", "Dependency Type", "Blocking", "Status",
    "Created At", "Updated At", "Notes",
]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _dfs_find_cycle(adjacency: dict, start: str, node_limit: int) -> dict:
    """
    Iterative DFS cycle detection starting at `start`, following
    `adjacency` edges (Template Stage ID -> [Depends On Template Stage
    ID, ...]). The current path (tuple) acts as the recursion stack — a
    neighbor already present in the still-open path is a cycle back to
    itself. Bounded by `node_limit` total node-visits to guarantee
    termination against corrupted/oversized data.

    Returns: {"cycle_found": bool, "cycle_path": tuple, "limit_exceeded": bool}
    """
    visited_total = 0
    stack = [(start, (start,))]
    while stack:
        node, path = stack.pop()
        visited_total += 1
        if visited_total > node_limit:
            return {"cycle_found": False, "cycle_path": (), "limit_exceeded": True}
        for neighbor in adjacency.get(node, ()):
            if neighbor in path:
                return {"cycle_found": True, "cycle_path": path + (neighbor,), "limit_exceeded": False}
            stack.append((neighbor, path + (neighbor,)))
    return {"cycle_found": False, "cycle_path": (), "limit_exceeded": False}


def _build_active_adjacency(roadmap_template_id: str, read_context=None) -> dict:
    from business_core.sheets import read_business_sheet_cached

    rows = read_business_sheet_cached("template_stage_dependencies", read_context=read_context)
    adjacency: dict[str, list[str]] = {}
    for r in rows:
        if r.get("Roadmap Template ID", "") != roadmap_template_id:
            continue
        if (r.get("Status", "") or "") != "active":
            continue
        adjacency.setdefault(r.get("Template Stage ID", ""), []).append(
            r.get("Depends On Template Stage ID", "")
        )
    return adjacency


# ═══════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════

def generate_dependency_id() -> str:
    """TDEP-001, TDEP-002, ..."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("template_stage_dependencies")
    except Exception as exc:
        log.warning(f"generate_dependency_id error: {exc}")
        return "TDEP-001"


# ═══════════════════════════════════════════════════════════════
# Reads
# ═══════════════════════════════════════════════════════════════

def list_dependencies_for_template_stage(
    template_stage_id: str, active_only: bool = True, read_context=None,
) -> tuple[dict, ...]:
    """All TEMPLATE_STAGE_DEPENDENCIES rows where Template Stage ID
    (the dependent side) matches — active-only by default. Read-only.

    `read_context`: optional transaction-local cache — see
    business_core.sheets.read_business_sheet_cached()."""
    if not template_stage_id:
        return ()
    try:
        from business_core.sheets import read_business_sheet_cached, SheetsReadError
        rows = read_business_sheet_cached("template_stage_dependencies", read_context=read_context)
        rows = [r for r in rows if r.get("Template Stage ID", "") == template_stage_id]
        if active_only:
            rows = [r for r in rows if (r.get("Status", "") or "") == "active"]
        return tuple(rows)
    except SheetsReadError:
        # Never mask a 429/5xx/network failure as "no dependencies".
        raise
    except Exception as exc:
        log.error(f"list_dependencies_for_template_stage({template_stage_id}) error: {exc}")
        return ()


def find_dependency_by_id(dependency_id: str) -> Optional[dict]:
    if not dependency_id:
        return None
    try:
        from business_core.sheets import find_row_by_id, SheetsReadError
        found = find_row_by_id("template_stage_dependencies", dependency_id)
        return found[1] if found else None
    except SheetsReadError:
        raise
    except Exception as exc:
        log.error(f"find_dependency_by_id({dependency_id}) error: {exc}")
        return None


def _find_dependency_row(template_stage_id: str, depends_on_template_stage_id: str):
    """Exact-match lookup on (Template Stage ID, Depends On Template
    Stage ID), regardless of Status — needed to distinguish an active
    duplicate from an inactive one at create time. Returns (row_num,
    row_dict) or None."""
    from business_core.sheets import get_business_sheet

    sheet = get_business_sheet("template_stage_dependencies")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return None
    headers = all_values[0]
    for i, row in enumerate(all_values[1:], start=2):
        row_dict = {headers[j]: (row[j] if j < len(row) else "") for j in range(len(headers))}
        if (row_dict.get("Template Stage ID") == template_stage_id
                and row_dict.get("Depends On Template Stage ID") == depends_on_template_stage_id):
            return (i, row_dict)
    return None


# ═══════════════════════════════════════════════════════════════
# Cycle detection
# ═══════════════════════════════════════════════════════════════

def detect_dependency_cycle(
    roadmap_template_id: str, from_template_stage_id: str, to_template_stage_id: str,
) -> dict:
    """
    Create-time check: would adding the edge
    (from_template_stage_id depends_on to_template_stage_id) create a
    cycle in the CURRENT active dependency graph of this one Roadmap
    Template ID? Never mutates stored data — builds the adjacency in
    memory, adds the hypothetical edge, and runs a bounded DFS.

    Returns:
        {"ok": bool, "would_create_cycle": bool, "cycle_path": tuple, "error": str | None}
    """
    if not roadmap_template_id or not from_template_stage_id or not to_template_stage_id:
        return {"ok": False, "would_create_cycle": False, "cycle_path": (),
                "error": "roadmap_template_id/from_template_stage_id/to_template_stage_id обязательны"}
    try:
        adjacency = _build_active_adjacency(roadmap_template_id)
        adjacency.setdefault(from_template_stage_id, []).append(to_template_stage_id)

        result = _dfs_find_cycle(adjacency, from_template_stage_id, node_limit=_CREATE_TIME_CYCLE_NODE_LIMIT)
        if result["limit_exceeded"]:
            return {"ok": False, "would_create_cycle": False, "cycle_path": (),
                    "error": "Превышен лимит обхода графа зависимостей при проверке цикла"}
        return {"ok": True, "would_create_cycle": result["cycle_found"], "cycle_path": result["cycle_path"], "error": None}
    except Exception as exc:
        log.error(f"detect_dependency_cycle error: {exc}")
        return {"ok": False, "would_create_cycle": False, "cycle_path": (), "error": str(exc)}


def detect_reachable_cycle_from_template_stage(
    roadmap_template_id: str, template_stage_id: str, node_limit: int = _GATE_TIME_CYCLE_NODE_LIMIT,
    read_context=None,
) -> dict:
    """
    Read-time corrupted-data defense — used ONLY inside the Dependency
    Gate, never as the primary cycle-prevention mechanism (that's
    detect_dependency_cycle(), called at create time). Checks whether
    the CURRENTLY STORED active graph, exactly as it reads right now,
    already contains a cycle reachable from `template_stage_id` — never
    adds a hypothetical edge. Bounded by `node_limit` (default 200) so a
    corrupted graph (e.g. from a manually edited Sheet row that bypassed
    create-time validation) can never cause an unbounded traversal.

    `read_context`: optional transaction-local cache — see
    business_core.sheets.read_business_sheet_cached(). When the caller
    (the Dependency Gate) already read TEMPLATE_STAGE_DEPENDENCIES once
    in this same transition, this reuses that data instead of a second
    full-table read.

    Returns:
        {"ok": bool, "cycle_found": bool, "cycle_path": tuple, "limit_exceeded": bool, "error": str | None}
    """
    if not roadmap_template_id or not template_stage_id:
        return {"ok": False, "cycle_found": False, "cycle_path": (), "limit_exceeded": False,
                "error": "roadmap_template_id/template_stage_id обязательны"}
    try:
        adjacency = _build_active_adjacency(roadmap_template_id, read_context=read_context)
        result = _dfs_find_cycle(adjacency, template_stage_id, node_limit=node_limit)
        return {
            "ok": True, "cycle_found": result["cycle_found"], "cycle_path": result["cycle_path"],
            "limit_exceeded": result["limit_exceeded"], "error": None,
        }
    except Exception as exc:
        from business_core.sheets import SheetsReadError
        if isinstance(exc, SheetsReadError):
            # Never mask a 429/5xx/network failure as a corrupted-graph
            # DEPENDENCY_CONFIGURATION_ERROR (the Dependency Gate's own
            # meaning for this "not ok") — the Gate must see this as a
            # distinct read failure, not "the data is broken".
            raise
        log.error(f"detect_reachable_cycle_from_template_stage error: {exc}")
        return {"ok": False, "cycle_found": False, "cycle_path": (), "limit_exceeded": False, "error": str(exc)}


def validate_dependency_graph_for_template(roadmap_template_id: str) -> dict:
    """
    Read-only diagnostic/audit tool — NOT called automatically on every
    transition (that would re-run a full-graph DFS on every
    pending->in_progress attempt, unnecessary given create-time
    prevention already guards against cycles in normal operation).
    Checks the ENTIRE active dependency graph of one Roadmap Template ID
    for any cycle, from every node that appears in it.

    Returns:
        {"ok": bool, "has_cycle": bool, "cycle_path": tuple, "errors": tuple}
    """
    if not roadmap_template_id:
        return {"ok": False, "has_cycle": False, "cycle_path": (), "errors": ("roadmap_template_id обязателен",)}
    try:
        adjacency = _build_active_adjacency(roadmap_template_id)
        nodes = set(adjacency.keys())
        for targets in adjacency.values():
            nodes.update(targets)

        for node in nodes:
            result = _dfs_find_cycle(adjacency, node, node_limit=_CREATE_TIME_CYCLE_NODE_LIMIT)
            if result["limit_exceeded"]:
                return {"ok": False, "has_cycle": False, "cycle_path": (),
                        "errors": ("Превышен лимит обхода графа зависимостей",)}
            if result["cycle_found"]:
                return {"ok": True, "has_cycle": True, "cycle_path": result["cycle_path"], "errors": ()}
        return {"ok": True, "has_cycle": False, "cycle_path": (), "errors": ()}
    except Exception as exc:
        log.error(f"validate_dependency_graph_for_template({roadmap_template_id}) error: {exc}")
        return {"ok": False, "has_cycle": False, "cycle_path": (), "errors": (str(exc),)}


# ═══════════════════════════════════════════════════════════════
# Create
# ═══════════════════════════════════════════════════════════════

def _dependency_result(ok: bool, code: str, error: str | None, dependency_id: str = "",
                        created: bool = False, reused: bool = False, reactivated: bool = False) -> dict:
    return {
        "ok": ok, "code": code, "error": error,
        "dependency_id": dependency_id, "created": created, "reused": reused, "reactivated": reactivated,
    }


def _reactivate_dependency(row_num: int, row: dict, dependency_type: str, blocking_str: str, notes: str) -> dict:
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("template_stage_dependencies")
        idx = get_header_index_map(sheet.row_values(1))
        now = _now_str()

        sheet.update_cell(row_num, idx["Status"] + 1, "active")
        sheet.update_cell(row_num, idx["Dependency Type"] + 1, dependency_type)
        sheet.update_cell(row_num, idx["Blocking"] + 1, blocking_str)
        if notes:
            sheet.update_cell(row_num, idx["Notes"] + 1, notes)
        sheet.update_cell(row_num, idx["Updated At"] + 1, now)

        return _dependency_result(
            True, "DEPENDENCY_REACTIVATED", None,
            dependency_id=row.get("Dependency ID", ""), reused=True, reactivated=True,
        )
    except Exception as exc:
        log.error(f"_reactivate_dependency error: {exc}")
        return _dependency_result(False, "DEPENDENCY_WRITE_FAILED", str(exc))


def create_template_stage_dependency(
    template_stage_id: str,
    depends_on_template_stage_id: str,
    dependency_type: str = "finish_to_start",
    blocking: bool = True,
    notes: str = "",
) -> dict:
    """
    Validation order, all before any write:
      1. required template_stage_id / depends_on_template_stage_id
      2. dependency_type is a known value ("finish_to_start" only, MVP)
      3. self-dependency rejected
      4. both Template Stages exist in ROADMAP_TEMPLATE_STAGES
      5. both belong to the SAME Roadmap Template ID (cross-template rejected)
      6. active duplicate -> idempotent reuse (no write)
      7. inactive duplicate -> reactivate (single-row update, no new row)
      8. would-create-cycle check (detect_dependency_cycle) -> rejected
      9. write

    Returns:
        {"ok": bool, "code": str, "error": str | None,
         "dependency_id": str, "created": bool, "reused": bool, "reactivated": bool}
    """
    if not template_stage_id or not depends_on_template_stage_id:
        return _dependency_result(False, "TEMPLATE_STAGE_NOT_FOUND",
                                   "template_stage_id и depends_on_template_stage_id обязательны")

    if dependency_type not in DEPENDENCY_TYPES:
        return _dependency_result(
            False, "INVALID_DEPENDENCY_TYPE",
            f"Недопустимый dependency_type {dependency_type!r}. Допустимые значения: {', '.join(DEPENDENCY_TYPES)}",
        )

    if template_stage_id == depends_on_template_stage_id:
        return _dependency_result(False, "SELF_DEPENDENCY_REJECTED", "Этап не может зависеть сам от себя")

    try:
        from business_core.sheets import find_row_by_id

        found_dependent = find_row_by_id("roadmap_template_stages", template_stage_id)
        found_prereq = find_row_by_id("roadmap_template_stages", depends_on_template_stage_id)
        if found_dependent is None or found_prereq is None:
            missing = template_stage_id if found_dependent is None else depends_on_template_stage_id
            return _dependency_result(False, "TEMPLATE_STAGE_NOT_FOUND", f"Template Stage {missing!r} не найден")

        _, dependent_row = found_dependent
        _, prereq_row = found_prereq
        dependent_template_id = dependent_row.get("Template ID", "")
        prereq_template_id = prereq_row.get("Template ID", "")

        if dependent_template_id != prereq_template_id:
            return _dependency_result(
                False, "CROSS_TEMPLATE_DEPENDENCY_REJECTED",
                f"Template Stage {template_stage_id} принадлежит {dependent_template_id!r}, "
                f"а {depends_on_template_stage_id} — {prereq_template_id!r}",
            )

        roadmap_template_id = dependent_template_id
        blocking_str = "true" if blocking else "false"

        existing = _find_dependency_row(template_stage_id, depends_on_template_stage_id)
        if existing is not None:
            row_num, row = existing
            if (row.get("Status", "") or "") == "active":
                return _dependency_result(
                    True, "DEPENDENCY_ALREADY_EXISTS", None,
                    dependency_id=row.get("Dependency ID", ""), reused=True,
                )
            return _reactivate_dependency(row_num, row, dependency_type, blocking_str, notes)

        cycle_result = detect_dependency_cycle(roadmap_template_id, template_stage_id, depends_on_template_stage_id)
        if not cycle_result["ok"]:
            return _dependency_result(False, "DEPENDENCY_WRITE_FAILED", cycle_result.get("error"))
        if cycle_result["would_create_cycle"]:
            code = "DIRECT_CYCLE_REJECTED" if len(cycle_result["cycle_path"]) <= 3 else "INDIRECT_CYCLE_REJECTED"
            return _dependency_result(
                False, code,
                f"Создание зависимости привело бы к циклу: {' -> '.join(cycle_result['cycle_path'])}",
            )

        from business_core.sheets import append_business_row, row_from_header_map, get_business_sheet

        dependency_id = generate_dependency_id()
        now = _now_str()
        sheet = get_business_sheet("template_stage_dependencies")
        headers = sheet.row_values(1)
        values = {
            "Dependency ID": dependency_id, "Roadmap Template ID": roadmap_template_id,
            "Template Stage ID": template_stage_id, "Depends On Template Stage ID": depends_on_template_stage_id,
            "Dependency Type": dependency_type, "Blocking": blocking_str, "Status": "active",
            "Created At": now, "Updated At": now, "Notes": notes,
        }
        row = row_from_header_map(headers, values)
        append_business_row("template_stage_dependencies", row)
        log.info(f"create_template_stage_dependency: {dependency_id} ({template_stage_id} depends_on {depends_on_template_stage_id})")
        return _dependency_result(True, "DEPENDENCY_CREATED", None, dependency_id=dependency_id, created=True)
    except Exception as exc:
        log.error(f"create_template_stage_dependency error: {exc}")
        return _dependency_result(False, "DEPENDENCY_WRITE_FAILED", str(exc))


# ═══════════════════════════════════════════════════════════════
# Live resolver
# ═══════════════════════════════════════════════════════════════

def resolve_live_stage_dependencies(stage_id: str, read_context=None) -> dict:
    """
    Resolves the active Template-Stage-level dependencies of `stage_id`
    into their live-Stage prerequisites, within the SAME Roadmap.

    Mapping:
      - live Stage -> Template Stage: the existing, unchanged
        business_core.roadmap_manager.resolve_template_stage_for_stage()
        (Order-join, already used by every prior Sync/provisioning
        function in this codebase).
      - prerequisite Template Stage -> live Stage: the REVERSE of that
        same join — the prerequisite Template Stage's own Order is
        looked up (within the SAME Roadmap Template ID, to avoid
        matching a same-numbered stage in an unrelated template), then
        the live Stage in THIS Roadmap with that same Order is located.
        Order is used purely as the existing technical join-key — this
        does not turn Order into a dependency (DECISIONS.md §14/§14a).

      Ambiguity guard: if more than one ROADMAP_TEMPLATE_STAGES row
      matches (Stage ID, Template ID) or more than one live Stage in
      this Roadmap shares the resolved Order, this is reported as a
      configuration error — never silently resolved by picking the
      first row.

    Returns:
        {
            "ok": bool, "code": str, "error": str | None,
            "stage_id": str, "roadmap_id": str, "roadmap_template_id": str, "template_stage_id": str,
            "dependencies": tuple,          # raw active TEMPLATE_STAGE_DEPENDENCIES rows
            "resolved": tuple,              # (see per-item shape in module docstring / gate contract)
            "missing_live_stages": tuple,   # (dependency_id, depends_on_template_stage_id)
            "configuration_errors": tuple,  # (dependency_id, reason)
        }

    `read_context` (Sheets quota mitigation, 2026-07-28): optional,
    duck-typed transaction-local cache threaded down from
    transition_stage_status() — see business_core.sheets.
    read_business_sheet_cached() and business_builder._TransitionReadContext.
    Default None preserves the exact prior behavior (always fresh reads)
    for every existing direct caller (e.g. /dependencies).
    """
    from business_core.roadmap_manager import resolve_template_stage_for_stage, get_stages_for_roadmap
    from business_core.sheets import read_business_sheet_cached

    empty = {
        "stage_id": stage_id, "roadmap_id": "", "roadmap_template_id": "", "template_stage_id": "",
        "dependencies": (), "resolved": (), "missing_live_stages": (), "configuration_errors": (),
    }

    resolved = resolve_template_stage_for_stage(stage_id, read_context=read_context)
    if not resolved["ok"]:
        return {"ok": False, "code": resolved["code"], "error": resolved["error"], **empty}

    roadmap = resolved.get("roadmap") or {}
    roadmap_id = roadmap.get("roadmap_id", "")
    roadmap_template_id = resolved.get("template_id", "")
    template_stage_id = resolved["template_stage_id"]

    dependencies = list_dependencies_for_template_stage(
        template_stage_id, active_only=True, read_context=read_context,
    )

    if not dependencies:
        return {
            "ok": True, "code": "NO_STAGE_DEPENDENCIES", "error": None,
            "stage_id": stage_id, "roadmap_id": roadmap_id, "roadmap_template_id": roadmap_template_id,
            "template_stage_id": template_stage_id,
            "dependencies": (), "resolved": (), "missing_live_stages": (), "configuration_errors": (),
        }

    all_template_stage_rows = read_business_sheet_cached("roadmap_template_stages", read_context=read_context)
    all_live_stage_rows = get_stages_for_roadmap(roadmap_id, read_context=read_context)

    resolved_items = []
    missing_live: list[tuple] = []
    configuration_errors: list[tuple] = []

    for dep in dependencies:
        dependency_id = dep.get("Dependency ID", "")
        prereq_tstg_id = dep.get("Depends On Template Stage ID", "")

        matching_template_rows = [
            r for r in all_template_stage_rows
            if r.get("Stage ID", "") == prereq_tstg_id and r.get("Template ID", "") == roadmap_template_id
        ]
        if not matching_template_rows:
            configuration_errors.append((dependency_id, f"Depends On Template Stage {prereq_tstg_id!r} не найден"))
            continue
        if len(matching_template_rows) > 1:
            configuration_errors.append(
                (dependency_id, f"Найдено {len(matching_template_rows)} строк Template Stage {prereq_tstg_id!r} — неоднозначно")
            )
            continue
        prereq_order = matching_template_rows[0].get("Order", "")

        matching_live_rows = [r for r in all_live_stage_rows if str(r.get("order", "")) == str(prereq_order)]
        if not matching_live_rows:
            missing_live.append((dependency_id, prereq_tstg_id))
            continue
        if len(matching_live_rows) > 1:
            configuration_errors.append((
                dependency_id,
                f"Найдено {len(matching_live_rows)} live Stage с Order={prereq_order!r} в Roadmap {roadmap_id} — неоднозначно",
            ))
            continue

        prereq_stage = matching_live_rows[0]
        prereq_status = prereq_stage.get("status", "")

        resolved_items.append({
            "dependency_id": dependency_id,
            "template_stage_id": template_stage_id,
            "depends_on_template_stage_id": prereq_tstg_id,
            "dependency_type": dep.get("Dependency Type", ""),
            "blocking": (dep.get("Blocking", "") or "").strip().lower() == "true",
            "prerequisite_stage_id": prereq_stage.get("stage_id", ""),
            "prerequisite_stage_name": prereq_stage.get("name", ""),
            "prerequisite_status": prereq_status,
            "satisfied": prereq_status in SATISFYING_STAGE_STATUSES,
        })

    return {
        "ok": True, "code": "DEPENDENCIES_RESOLVED", "error": None,
        "stage_id": stage_id, "roadmap_id": roadmap_id, "roadmap_template_id": roadmap_template_id,
        "template_stage_id": template_stage_id,
        "dependencies": tuple(dependencies), "resolved": tuple(resolved_items),
        "missing_live_stages": tuple(missing_live), "configuration_errors": tuple(configuration_errors),
    }
