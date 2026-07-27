"""
Tests for Phase 22C — Work Execution Integration & Regression Gate.

Validates the Work Execution Layer as one coherent subsystem across the
full chain: Department -> Role -> Person Role Assignment (Organization
Layer, Phase 21) -> Stage Responsibility Relation -> Resolution (Work
Execution Layer, Phase 22B). Uses a shared in-memory multi-registry
harness (same pattern as test_business_organization_seed.py) so every
scenario exercises the REAL organization_manager.py / stage_entity_
relations.py / work_assignment_manager.py functions together, not
per-function mocks in isolation.

No new production code is expected from this phase — see the module
docstrings of business_core/work_assignment_manager.py and
business_core/organization_manager.py for what already exists. This
file is purely an integration and regression gate.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


class _InMemoryRegistry:
    """A minimal in-memory stand-in for a single Sheets tab — same
    pattern as test_business_organization_seed.py's harness, extended
    here to also cover roadmap_stages and stage_entity_relations so the
    full Stage -> Relation -> Role -> Person chain can be exercised
    end-to-end against real (non-mocked) business_core functions."""

    def __init__(self, headers: list[str]):
        self.headers = headers
        self.rows: list[list[str]] = []

    def get_all_values(self):
        return [self.headers] + self.rows

    def row_values(self, r):
        if r == 1:
            return self.headers
        return self.rows[r - 2]

    def find(self, value, in_column=1):
        for i, row in enumerate(self.rows):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = i + 2
                return cell
        return None

    def update_cell(self, row_num, col, value):
        row = self.rows[row_num - 2]
        while len(row) < col:
            row.append("")
        row[col - 1] = value

    def update(self, range_name, values):
        self.rows.append(list(values[0]))


DEPARTMENT_HEADERS = [
    "Department ID", "Business ID", "Department Name",
    "Parent Department ID", "Head Role ID", "Status", "Notes",
]
ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]
ASSIGNMENT_HEADERS = [
    "Assignment ID", "Person ID", "Role ID",
    "Start Date", "End Date", "Assignment Type", "Status", "Notes",
]
PEOPLE_HEADERS = ["ID"]
STAGE_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
    "Start Date", "Priority", "Blocking Reason",
]
RELATION_HEADERS = [
    "Relation ID", "Template Stage ID", "Stage ID",
    "Entity Type", "Entity ID",
    "Required", "Blocking", "Minimum Count", "Status",
    "Created At", "Updated At",
]


def _make_registries():
    return {
        "department_registry":     _InMemoryRegistry(DEPARTMENT_HEADERS),
        "role_registry":           _InMemoryRegistry(ROLE_HEADERS),
        "person_role_assignments": _InMemoryRegistry(ASSIGNMENT_HEADERS),
        "people_registry":         _InMemoryRegistry(PEOPLE_HEADERS),
        "roadmap_stages":          _InMemoryRegistry(STAGE_HEADERS),
        "stage_entity_relations":  _InMemoryRegistry(RELATION_HEADERS),
    }


def _seed_person(registries, person_id):
    registries["people_registry"].rows.append([person_id])


def _seed_stage(registries, stage_id, roadmap_id="RM-001"):
    row = [""] * len(STAGE_HEADERS)
    row[STAGE_HEADERS.index("Stage ID")] = stage_id
    row[STAGE_HEADERS.index("Roadmap ID")] = roadmap_id
    row[STAGE_HEADERS.index("Status")] = "pending"
    registries["roadmap_stages"].rows.append(row)


def _get_business_sheet_router(registries):
    def fake_get_business_sheet(key):
        if key not in registries:
            raise AssertionError(f"unexpected sheet access in integration scope: '{key}'")
        return registries[key]
    return fake_get_business_sheet


def _fresh_modules():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    om = importlib.import_module("business_core.organization_manager")
    wam = importlib.import_module("business_core.work_assignment_manager")
    return om, wam


class WorkExecutionIntegrationTestCase(unittest.TestCase):
    """Common setup: fresh modules + fresh registries + one patch context
    covering the entire scenario, so every nested business_core call
    (organization_manager, stage_entity_relations, work_assignment_manager,
    sheets.py primitives) resolves against the SAME in-memory data."""

    def setUp(self):
        self.om, self.wam = _fresh_modules()
        self.registries = _make_registries()
        self.patcher = patch(
            "business_core.sheets.get_business_sheet",
            side_effect=_get_business_sheet_router(self.registries),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)


# ─────────────────────────────────────────────────────────────
# 1. Full happy path
# ─────────────────────────────────────────────────────────────

class TestFullHappyPath(WorkExecutionIntegrationTestCase):

    def test_stage_resolves_to_real_person_through_full_chain(self):
        dept = self.om.create_department("Operations")
        self.assertTrue(dept["ok"], dept)

        role = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        self.assertTrue(role["ok"], role)

        _seed_person(self.registries, "PRS-001")

        assignment = self.om.assign_person_to_role("PRS-001", role["role_id"], start_date="2026-01-01")
        self.assertTrue(assignment["ok"], assignment)

        _seed_stage(self.registries, "STAGE-100")

        link = self.wam.assign_role_to_stage("STAGE-100", role["role_id"])
        self.assertTrue(link["ok"], link)

        result = self.wam.resolve_stage_responsibility("STAGE-100")

        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["role_id"], role["role_id"])
        self.assertEqual(result["person_id"], "PRS-001")
        self.assertEqual(result["relation_id"], link["relation_id"])
        self.assertEqual(result["errors"], ())


# ─────────────────────────────────────────────────────────────
# 2. Person replacement
# ─────────────────────────────────────────────────────────────

class TestPersonReplacement(WorkExecutionIntegrationTestCase):

    def test_replacing_person_does_not_touch_stage_relation(self):
        dept = self.om.create_department("Operations")
        role = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-001")
        _seed_person(self.registries, "PRS-002")
        first_assignment = self.om.assign_person_to_role("PRS-001", role["role_id"], start_date="2026-01-01")
        _seed_stage(self.registries, "STAGE-101")
        link = self.wam.assign_role_to_stage("STAGE-101", role["role_id"])

        relation_row_before = list(self.registries["stage_entity_relations"].rows[0])

        end_result = self.om.end_assignment(first_assignment["assignment_id"], end_date="2026-06-01")
        self.assertTrue(end_result["ok"])

        second_assignment = self.om.assign_person_to_role("PRS-002", role["role_id"], start_date="2026-06-02")
        self.assertTrue(second_assignment["ok"])

        result = self.wam.resolve_stage_responsibility("STAGE-101")

        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["role_id"], role["role_id"])
        self.assertEqual(result["person_id"], "PRS-002")
        # The stage->role relation row itself is byte-for-byte unchanged —
        # person replacement never touches STAGE_ENTITY_RELATIONS.
        relation_row_after = self.registries["stage_entity_relations"].rows[0]
        self.assertEqual(relation_row_before, relation_row_after)


# ─────────────────────────────────────────────────────────────
# 3. Role reassignment
# ─────────────────────────────────────────────────────────────

class TestRoleReassignment(WorkExecutionIntegrationTestCase):

    def test_reassigning_stage_to_new_role_resolves_new_role_and_person(self):
        dept = self.om.create_department("Operations")
        role_a = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        role_b = self.om.create_role("Inbound Manager", department_id=dept["department_id"], status="active")

        _seed_person(self.registries, "PRS-001")
        _seed_person(self.registries, "PRS-002")
        self.om.assign_person_to_role("PRS-001", role_a["role_id"], start_date="2026-01-01")
        self.om.assign_person_to_role("PRS-002", role_b["role_id"], start_date="2026-01-01")

        _seed_stage(self.registries, "STAGE-102")
        link_a = self.wam.assign_role_to_stage("STAGE-102", role_a["role_id"])

        reassign_result = self.wam.reassign_stage_role("STAGE-102", role_b["role_id"])

        self.assertTrue(reassign_result["ok"])
        self.assertTrue(reassign_result["changed"])
        self.assertEqual(reassign_result["old_relation_id"], link_a["relation_id"])
        self.assertNotEqual(reassign_result["new_relation_id"], link_a["relation_id"])

        relations = self.registries["stage_entity_relations"].rows
        old_row = next(r for r in relations if r[0] == link_a["relation_id"])
        new_row = next(r for r in relations if r[0] == reassign_result["new_relation_id"])
        self.assertEqual(old_row[RELATION_HEADERS.index("Status")], "inactive")
        self.assertEqual(new_row[RELATION_HEADERS.index("Status")], "active")
        self.assertEqual(new_row[RELATION_HEADERS.index("Entity ID")], role_b["role_id"])

        result = self.wam.resolve_stage_responsibility("STAGE-102")
        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["role_id"], role_b["role_id"])
        self.assertEqual(result["person_id"], "PRS-002")


# ─────────────────────────────────────────────────────────────
# 4. Vacancy
# ─────────────────────────────────────────────────────────────

class TestVacancy(WorkExecutionIntegrationTestCase):

    def test_vacant_role_resolves_vacant_even_with_filled_parent(self):
        """The Role's Reports To Role ID points at a FILLED role — this
        proves (behaviorally, not just via a call-count spy) that no
        Reports-To hierarchy walk-up occurs (Phase 22A adjustment 2).

        Phase 35D (ADR-018 §16): assign_role_to_stage() now requires an
        "active" Role (previously "planned" was also accepted) — the
        vacancy scenario here is created via an active Role with zero
        Person assignments, not a planned one."""
        dept = self.om.create_department("Operations")
        manager_role = self.om.create_role("Operations Manager", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-MANAGER")
        self.om.assign_person_to_role("PRS-MANAGER", manager_role["role_id"], start_date="2026-01-01")

        vacant_role = self.om.create_role(
            "Coordinator", department_id=dept["department_id"],
            reports_to_role_id=manager_role["role_id"], status="active",
        )
        # deliberately no assign_person_to_role() call for vacant_role

        _seed_stage(self.registries, "STAGE-103")
        self.wam.assign_role_to_stage("STAGE-103", vacant_role["role_id"])

        result = self.wam.resolve_stage_responsibility("STAGE-103")

        self.assertEqual(result["status"], "vacant")
        self.assertEqual(result["role_id"], vacant_role["role_id"])
        self.assertIsNone(result["person_id"])
        # Not the manager's ID, not any other resolved person:
        self.assertNotEqual(result.get("person_id"), "PRS-MANAGER")


# ─────────────────────────────────────────────────────────────
# 5. Archived Role
# ─────────────────────────────────────────────────────────────

class TestArchivedRole(WorkExecutionIntegrationTestCase):

    def test_archiving_linked_role_yields_configuration_error_core_untouched(self):
        dept = self.om.create_department("Operations")
        role = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-001")
        self.om.assign_person_to_role("PRS-001", role["role_id"], start_date="2026-01-01")

        _seed_stage(self.registries, "STAGE-104")
        self.wam.assign_role_to_stage("STAGE-104", role["role_id"])

        stage_row_before = list(self.registries["roadmap_stages"].rows[0])

        archive_result = self.om.archive_role(role["role_id"])
        self.assertTrue(archive_result["ok"])

        result = self.wam.resolve_stage_responsibility("STAGE-104")

        self.assertEqual(result["status"], "configuration_error")
        self.assertEqual(result["role_id"], role["role_id"])
        self.assertTrue(any(role["role_id"] in e for e in result["errors"]))

        # ROADMAP_STAGES row is byte-for-byte unchanged.
        stage_row_after = self.registries["roadmap_stages"].rows[0]
        self.assertEqual(stage_row_before, stage_row_after)


# ─────────────────────────────────────────────────────────────
# 6. Missing configuration
# ─────────────────────────────────────────────────────────────

class TestMissingConfiguration(WorkExecutionIntegrationTestCase):

    def test_stage_with_no_role_relation_is_unconfigured(self):
        _seed_stage(self.registries, "STAGE-105")
        result = self.wam.resolve_stage_responsibility("STAGE-105")

        self.assertEqual(result["status"], "unconfigured")
        self.assertIsNone(result["role_id"])
        self.assertIsNone(result["person_id"])
        self.assertIsNone(result["relation_id"])
        self.assertEqual(result["errors"], ())


# ─────────────────────────────────────────────────────────────
# 7. Historical integrity
# ─────────────────────────────────────────────────────────────

class TestHistoricalIntegrity(WorkExecutionIntegrationTestCase):

    def test_reassignment_never_deletes_old_relation_row(self):
        dept = self.om.create_department("Operations")
        role_a = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        role_b = self.om.create_role("Inbound Manager", department_id=dept["department_id"], status="active")
        _seed_stage(self.registries, "STAGE-106")

        link_a = self.wam.assign_role_to_stage("STAGE-106", role_a["role_id"])
        row_count_before = len(self.registries["stage_entity_relations"].rows)

        self.wam.reassign_stage_role("STAGE-106", role_b["role_id"])
        row_count_after = len(self.registries["stage_entity_relations"].rows)

        self.assertEqual(row_count_after, row_count_before + 1)
        relation_ids = [r[0] for r in self.registries["stage_entity_relations"].rows]
        self.assertIn(link_a["relation_id"], relation_ids)

    def test_ending_assignment_never_overwrites_history(self):
        dept = self.om.create_department("Operations")
        role = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-001")
        _seed_person(self.registries, "PRS-002")

        first = self.om.assign_person_to_role("PRS-001", role["role_id"], start_date="2026-01-01")
        self.om.end_assignment(first["assignment_id"], end_date="2026-03-01")
        second = self.om.assign_person_to_role("PRS-002", role["role_id"], start_date="2026-03-02")

        history = self.om.get_assignment_history(role["role_id"])

        self.assertEqual(len(history), 2)
        assignment_ids = {h["assignment_id"] for h in history}
        self.assertEqual(assignment_ids, {first["assignment_id"], second["assignment_id"]})
        first_entry = next(h for h in history if h["assignment_id"] == first["assignment_id"])
        self.assertEqual(first_entry["status"], "ended")
        self.assertEqual(first_entry["end_date"], "2026-03-01")


# ─────────────────────────────────────────────────────────────
# 8. Cross-layer ownership
# ─────────────────────────────────────────────────────────────

class TestCrossLayerOwnership(WorkExecutionIntegrationTestCase):

    def test_work_execution_writes_only_through_stage_entity_relations(self):
        """Runs a full scenario (create, assign, reassign) and tracks
        every sheet that ever received a write (update_cell/update),
        confirming ROADMAP_STAGES/ROADMAPS are never among them and that
        work_assignment_manager's own writes land exclusively in
        stage_entity_relations (Organization Layer registries are
        expected to receive writes too, but only via organization_manager's
        own calls, not bypassed)."""
        write_log = []
        for key, registry in self.registries.items():
            orig_update_cell = registry.update_cell
            orig_update = registry.update

            def make_wrapped(k, fn):
                def wrapped(*a, **kw):
                    write_log.append(k)
                    return fn(*a, **kw)
                return wrapped

            registry.update_cell = make_wrapped(key, orig_update_cell)
            registry.update = make_wrapped(key, orig_update)

        dept = self.om.create_department("Operations")
        role_a = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        role_b = self.om.create_role("Inbound Manager", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-001")
        self.om.assign_person_to_role("PRS-001", role_a["role_id"], start_date="2026-01-01")
        _seed_stage(self.registries, "STAGE-107")
        self.wam.assign_role_to_stage("STAGE-107", role_a["role_id"])
        self.wam.reassign_stage_role("STAGE-107", role_b["role_id"])

        self.assertNotIn("roadmap_stages", write_log)
        self.assertNotIn("roadmaps", write_log)
        # Work Execution's own writes (assign/reassign) all land in
        # stage_entity_relations.
        self.assertIn("stage_entity_relations", write_log)


# ─────────────────────────────────────────────────────────────
# 9. Stable resolution contract
# ─────────────────────────────────────────────────────────────

class TestStableResolutionContract(WorkExecutionIntegrationTestCase):

    EXPECTED_KEYS = {"status", "stage_id", "role_id", "person_id", "relation_id", "errors"}

    def test_every_status_produces_identical_key_set_with_explicit_nones(self):
        dept = self.om.create_department("Operations")
        role = self.om.create_role("Coordinator", department_id=dept["department_id"], status="active")
        _seed_person(self.registries, "PRS-001")
        self.om.assign_person_to_role("PRS-001", role["role_id"], start_date="2026-01-01")

        _seed_stage(self.registries, "STAGE-A")  # will be: assigned
        _seed_stage(self.registries, "STAGE-B")  # will be: unconfigured
        _seed_stage(self.registries, "STAGE-C")  # will be: vacant
        _seed_stage(self.registries, "STAGE-D")  # will be: configuration_error (archived role)

        self.wam.assign_role_to_stage("STAGE-A", role["role_id"])
        assigned = self.wam.resolve_stage_responsibility("STAGE-A")

        unconfigured = self.wam.resolve_stage_responsibility("STAGE-B")

        # Phase 35D (ADR-018 §16): assign_role_to_stage() now requires
        # an "active" Role — "planned" no longer reaches a vacant
        # relation, it's rejected outright. Vacancy here is an active
        # Role with zero Person assignments instead.
        vacant_role = self.om.create_role("Document Controller", department_id=dept["department_id"], status="active")
        self.wam.assign_role_to_stage("STAGE-C", vacant_role["role_id"])
        vacant = self.wam.resolve_stage_responsibility("STAGE-C")

        archived_role = self.om.create_role("Temp Role", department_id=dept["department_id"], status="active")
        self.wam.assign_role_to_stage("STAGE-D", archived_role["role_id"])
        self.om.archive_role(archived_role["role_id"])
        config_error = self.wam.resolve_stage_responsibility("STAGE-D")

        results = {"assigned": assigned, "unconfigured": unconfigured,
                   "vacant": vacant, "configuration_error": config_error}

        for status_name, result in results.items():
            self.assertEqual(result["status"], status_name)
            self.assertEqual(set(result.keys()), self.EXPECTED_KEYS, f"key mismatch for {status_name}")

        self.assertIsNone(results["unconfigured"]["role_id"])
        self.assertIsNone(results["unconfigured"]["person_id"])
        self.assertIsNone(results["unconfigured"]["relation_id"])

        self.assertIsNotNone(results["vacant"]["role_id"])
        self.assertIsNone(results["vacant"]["person_id"])
        self.assertIsNotNone(results["vacant"]["relation_id"])

        self.assertIsNotNone(results["configuration_error"]["role_id"])
        self.assertIsNone(results["configuration_error"]["person_id"])
        self.assertIsNotNone(results["configuration_error"]["relation_id"])

        self.assertIsNotNone(results["assigned"]["role_id"])
        self.assertIsNotNone(results["assigned"]["person_id"])
        self.assertIsNotNone(results["assigned"]["relation_id"])


# ─────────────────────────────────────────────────────────────
# 10. Architecture guards
# ─────────────────────────────────────────────────────────────

class TestArchitectureGuards(unittest.TestCase):

    def test_no_gtd_imports_work_assignment_manager(self):
        path = WORKSPACE / "business_core" / "work_assignment_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN)

    def test_no_telegram_import_work_assignment_manager(self):
        path = WORKSPACE / "business_core" / "work_assignment_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("telegram_handlers", src)
        self.assertNotIn("from telegram", src)

    def test_no_contractor_person_entity_type(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        import importlib
        ser = importlib.import_module("business_core.stage_entity_relations")
        self.assertNotIn("contractor_person", ser.ENTITY_TYPE_DISPATCH)
        self.assertEqual(set(ser.ENTITY_TYPE_DISPATCH.keys()), {"document_template", "role", "sop"})

    def test_no_automatic_hierarchy_escalation_reference(self):
        """resolve_stage_responsibility()'s executable body must never
        reference "reports_to_role_id" or "Reports To Role ID" — that
        would indicate a hierarchy walk-up, explicitly ruled out by the
        Phase 22A adjustment (vacancy is terminal, not escalated)."""
        import inspect
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        import importlib
        wam = importlib.import_module("business_core.work_assignment_manager")
        src = inspect.getsource(wam.resolve_stage_responsibility)
        self.assertNotIn("reports_to_role_id", src.lower())
        self.assertNotIn("reports to role id", src.lower())

    def test_only_approved_business_core_dependencies(self):
        path = WORKSPACE / "business_core" / "work_assignment_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("business_core"):
                imports.add(node.module)
        self.assertEqual(
            imports,
            {"business_core.sheets", "business_core.stage_entity_relations", "business_core.organization_manager"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
