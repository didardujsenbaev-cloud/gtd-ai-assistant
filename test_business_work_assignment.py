"""
Tests for Phase 22B — Work Execution Foundation
(business_core/work_assignment_manager.py).

Covers resolve_stage_responsibility(), get_responsible_role_for_stage(),
assign_role_to_stage(), reassign_stage_role() — normal resolution,
missing relation, archived role, vacant role, reassignment, duplicate
protection, API contract, import guards, and full regression.

No live Sheets writes — mocks only, per ENGINEERING_STANDARDS.md Testing
Standards. Never modifies ROADMAP_STAGES/ROADMAPS/Responsible/
Organization Layer/GTD Core — verified by explicit guard tests below.
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

RELATION_HEADERS = [
    "Relation ID", "Template Stage ID", "Stage ID",
    "Entity Type", "Entity ID",
    "Required", "Blocking", "Minimum Count", "Status",
    "Created At", "Updated At",
]

ACTIVE_ROLE_RELATION = {
    "Relation ID": "REL-010", "Template Stage ID": "", "Stage ID": "STAGE-001",
    "Entity Type": "role", "Entity ID": "ROLE-001",
    "Required": "true", "Blocking": "false", "Minimum Count": "1",
    "Status": "active", "Created At": "2026-01-01", "Updated At": "2026-01-01",
}

ACTIVE_ROLE = {
    "row_num": 2, "role_id": "ROLE-001", "department_id": "DEPT-001",
    "role_name": "Coordinator", "reports_to_role_id": "", "role_type": "internal",
    "employment_model": "full_time", "status": "active",
    "purpose": "", "main_result": "", "notes": "",
}

ARCHIVED_ROLE = dict(ACTIVE_ROLE, status="archived")

ACTIVE_ASSIGNMENT = {
    "assignment_id": "PRA-001", "person_id": "PRS-001", "role_id": "ROLE-001",
    "start_date": "2026-01-01", "end_date": "", "assignment_type": "primary",
    "status": "active", "notes": "",
}


def _fresh_wam():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.work_assignment_manager")


def _make_relation_sheet(rows: list[dict], row_num_start=2):
    """A mock STAGE_ENTITY_RELATIONS sheet supporting find/row_values/
    get_all_values/update_cell/update, for the write-path tests."""
    sheet = MagicMock()
    data_rows = [list(r.values()) for r in rows]

    def get_all_values():
        return [RELATION_HEADERS] + data_rows

    def row_values(r):
        if r == 1:
            return RELATION_HEADERS
        return data_rows[r - 2]

    def find(value, in_column=1):
        for i, row in enumerate(data_rows):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = row_num_start + i
                return cell
        return None

    def update_cell(row_num, col, value):
        idx = row_num - row_num_start
        row = data_rows[idx]
        while len(row) < col:
            row.append("")
        row[col - 1] = value

    def update(range_name, values):
        data_rows.append(list(values[0]))

    sheet.get_all_values.side_effect = get_all_values
    sheet.row_values.side_effect = row_values
    sheet.find.side_effect = find
    sheet.update_cell.side_effect = update_cell
    sheet.update.side_effect = update
    return sheet, data_rows


# ─────────────────────────────────────────────────────────────
# resolve_stage_responsibility: normal resolution
# ─────────────────────────────────────────────────────────────

class TestResolveNormalResolution(unittest.TestCase):

    def test_assigned_when_role_filled(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"Stage ID": "STAGE-001"})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.organization_manager.list_assignments_for_role",
                   return_value=[dict(ACTIVE_ASSIGNMENT)]):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["role_id"], "ROLE-001")
        self.assertEqual(result["person_id"], "PRS-001")
        self.assertEqual(result["relation_id"], "REL-010")
        self.assertEqual(result["errors"], ())

    def test_precedence_temporary_wins_over_primary(self):
        wam = _fresh_wam()
        temp = dict(ACTIVE_ASSIGNMENT, assignment_id="PRA-002", person_id="PRS-002",
                    assignment_type="temporary", start_date="2026-06-01")
        primary = dict(ACTIVE_ASSIGNMENT)

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.organization_manager.list_assignments_for_role",
                   return_value=[primary, temp]):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["person_id"], "PRS-002")

    def test_precedence_primary_wins_over_backup(self):
        wam = _fresh_wam()
        backup = dict(ACTIVE_ASSIGNMENT, assignment_id="PRA-003", person_id="PRS-003",
                      assignment_type="backup")
        primary = dict(ACTIVE_ASSIGNMENT)

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.organization_manager.list_assignments_for_role",
                   return_value=[backup, primary]):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["person_id"], "PRS-001")


# ─────────────────────────────────────────────────────────────
# resolve_stage_responsibility: missing relation
# ─────────────────────────────────────────────────────────────

class TestResolveMissingRelation(unittest.TestCase):

    def test_unconfigured_when_no_role_relation(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()):
            result = wam.resolve_stage_responsibility("STAGE-002")

        self.assertEqual(result["status"], "unconfigured")
        self.assertIsNone(result["role_id"])
        self.assertIsNone(result["person_id"])
        self.assertEqual(result["errors"], ())

    def test_configuration_error_when_stage_not_found(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = wam.resolve_stage_responsibility("STAGE-999")

        self.assertEqual(result["status"], "configuration_error")
        self.assertTrue(any("STAGE-999" in e for e in result["errors"]))

    def test_configuration_error_when_stage_id_blank(self):
        wam = _fresh_wam()
        result = wam.resolve_stage_responsibility("")
        self.assertEqual(result["status"], "configuration_error")


# ─────────────────────────────────────────────────────────────
# resolve_stage_responsibility: archived role
# ─────────────────────────────────────────────────────────────

class TestResolveArchivedRole(unittest.TestCase):

    def test_configuration_error_when_role_archived(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ARCHIVED_ROLE)):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["status"], "configuration_error")
        self.assertEqual(result["role_id"], "ROLE-001")
        self.assertTrue(any("ROLE-001" in e for e in result["errors"]))

    def test_configuration_error_when_relation_points_at_deleted_role(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=None):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["status"], "configuration_error")
        self.assertTrue(any("ROLE-001" in e for e in result["errors"]))


# ─────────────────────────────────────────────────────────────
# resolve_stage_responsibility: vacant role
# ─────────────────────────────────────────────────────────────

class TestResolveVacantRole(unittest.TestCase):

    def test_vacant_when_no_active_assignments(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.organization_manager.list_assignments_for_role", return_value=[]):
            result = wam.resolve_stage_responsibility("STAGE-001")

        self.assertEqual(result["status"], "vacant")
        self.assertEqual(result["role_id"], "ROLE-001")
        self.assertIsNone(result["person_id"])

    def test_vacant_does_not_walk_reports_to_hierarchy(self):
        """Phase 22A adjustment 2: vacancy is terminal — this module must
        never consult Reports To Role ID to auto-escalate."""
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.organization_manager.list_assignments_for_role", return_value=[]) as mock_list:
            wam.resolve_stage_responsibility("STAGE-001")

        # Only ever called once (for the originally-resolved role) — no
        # second call for any "Reports To" role.
        self.assertEqual(mock_list.call_count, 1)


# ─────────────────────────────────────────────────────────────
# get_responsible_role_for_stage
# ─────────────────────────────────────────────────────────────

class TestGetResponsibleRoleForStage(unittest.TestCase):

    def test_returns_role_id_when_relation_exists(self):
        wam = _fresh_wam()
        with patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)):
            self.assertEqual(wam.get_responsible_role_for_stage("STAGE-001"), "ROLE-001")

    def test_returns_none_when_no_relation(self):
        wam = _fresh_wam()
        with patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()):
            self.assertIsNone(wam.get_responsible_role_for_stage("STAGE-002"))

    def test_returns_none_for_blank_stage_id(self):
        wam = _fresh_wam()
        self.assertIsNone(wam.get_responsible_role_for_stage(""))

    def test_does_not_validate_role_existence(self):
        """Lower-level primitive than resolve_stage_responsibility — just
        reports what's linked, even if the Role turns out to be archived
        or missing (that judgment belongs to resolve_stage_responsibility)."""
        wam = _fresh_wam()
        with patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)):
            # No organization_manager patch at all — proves this function
            # never calls into it.
            role_id = wam.get_responsible_role_for_stage("STAGE-001")
        self.assertEqual(role_id, "ROLE-001")


# ─────────────────────────────────────────────────────────────
# assign_role_to_stage
# ─────────────────────────────────────────────────────────────

class TestAssignRoleToStage(unittest.TestCase):

    def test_happy_path(self):
        wam = _fresh_wam()
        relation_sheet, values = _make_relation_sheet([])

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.find_active_duplicate_relation", return_value=None), \
             patch("business_core.sheets.get_business_sheet", return_value=relation_sheet):
            result = wam.assign_role_to_stage("STAGE-001", "ROLE-001")

        self.assertTrue(result["ok"])
        self.assertTrue(result["relation_id"].startswith("REL-"))
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0][3], "role")
        self.assertEqual(values[0][4], "ROLE-001")
        self.assertEqual(values[0][8], "active")

    def test_missing_stage_id_rejected(self):
        wam = _fresh_wam()
        result = wam.assign_role_to_stage("", "ROLE-001")
        self.assertFalse(result["ok"])
        self.assertIn("stage_id", result["error"])

    def test_missing_role_id_rejected(self):
        wam = _fresh_wam()
        result = wam.assign_role_to_stage("STAGE-001", "")
        self.assertFalse(result["ok"])
        self.assertIn("role_id", result["error"])

    def test_unknown_stage_rejected(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = wam.assign_role_to_stage("STAGE-999", "ROLE-001")
        self.assertFalse(result["ok"])
        self.assertIn("STAGE-999", result["error"])

    def test_unknown_role_rejected(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=None):
            result = wam.assign_role_to_stage("STAGE-001", "ROLE-999")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_archived_role_rejected(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ARCHIVED_ROLE)):
            result = wam.assign_role_to_stage("STAGE-001", "ROLE-001")
        self.assertFalse(result["ok"])
        self.assertIn("архивирована", result["error"])


# ─────────────────────────────────────────────────────────────
# duplicate relation protection
# ─────────────────────────────────────────────────────────────

class TestDuplicateProtection(unittest.TestCase):

    def test_rejects_second_active_role_relation_on_same_stage(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)):
            result = wam.assign_role_to_stage("STAGE-001", "ROLE-002")

        self.assertFalse(result["ok"])
        self.assertIn("reassign_stage_role", result["error"])

    def test_rejects_exact_duplicate_via_generic_mechanism(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.find_active_duplicate_relation",
                   return_value=dict(ACTIVE_ROLE_RELATION)):
            result = wam.assign_role_to_stage("STAGE-001", "ROLE-001")

        self.assertFalse(result["ok"])
        self.assertIn("REL-010", result["error"])


# ─────────────────────────────────────────────────────────────
# role reassignment
# ─────────────────────────────────────────────────────────────

class TestReassignStageRole(unittest.TestCase):

    def test_reassign_deactivates_old_and_creates_new(self):
        wam = _fresh_wam()
        relation_sheet, values = _make_relation_sheet([dict(ACTIVE_ROLE_RELATION)])
        new_role = dict(ACTIVE_ROLE, role_id="ROLE-002")

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=new_role), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)), \
             patch("business_core.sheets.get_business_sheet", return_value=relation_sheet):
            result = wam.reassign_stage_role("STAGE-001", "ROLE-002")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["old_relation_id"], "REL-010")
        self.assertNotEqual(result["new_relation_id"], "REL-010")
        # old relation is now inactive, new one active
        self.assertEqual(values[0][8], "inactive")
        self.assertEqual(values[1][3], "role")
        self.assertEqual(values[1][4], "ROLE-002")
        self.assertEqual(values[1][8], "active")

    def test_reassign_to_same_role_is_idempotent_noop(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=(ACTIVE_ROLE_RELATION,)):
            result = wam.reassign_stage_role("STAGE-001", "ROLE-001")

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_relation_id"], "REL-010")
        self.assertEqual(result["new_relation_id"], "REL-010")

    def test_reassign_with_no_existing_relation_creates_fresh(self):
        wam = _fresh_wam()
        relation_sheet, values = _make_relation_sheet([])

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.sheets.get_business_sheet", return_value=relation_sheet):
            result = wam.reassign_stage_role("STAGE-001", "ROLE-001")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertIsNone(result["old_relation_id"])
        self.assertEqual(len(values), 1)

    def test_reassign_unknown_role_rejected(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=None):
            result = wam.reassign_stage_role("STAGE-001", "ROLE-999")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_reassign_archived_role_rejected(self):
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ARCHIVED_ROLE)):
            result = wam.reassign_stage_role("STAGE-001", "ROLE-001")
        self.assertFalse(result["ok"])
        self.assertIn("архивирована", result["error"])


# ─────────────────────────────────────────────────────────────
# API contract
# ─────────────────────────────────────────────────────────────

class TestApiContract(unittest.TestCase):

    EXPECTED_PUBLIC_FUNCTIONS = (
        "resolve_stage_responsibility", "get_responsible_role_for_stage",
        "assign_role_to_stage", "reassign_stage_role",
    )

    def test_exact_public_function_surface(self):
        wam = _fresh_wam()
        public_callables = {
            name for name in vars(wam)
            if not name.startswith("_") and callable(getattr(wam, name))
            and getattr(getattr(wam, name), "__module__", "") == wam.__name__
        }
        self.assertEqual(public_callables, set(self.EXPECTED_PUBLIC_FUNCTIONS))

    def test_resolution_status_enum_has_exactly_four_values(self):
        wam = _fresh_wam()
        self.assertEqual(
            set(wam.RESOLUTION_STATUS),
            {"assigned", "vacant", "unconfigured", "configuration_error"},
        )

    def test_resolve_result_never_includes_free_text_as_status(self):
        """The `status` field must always be one of the four canonical
        values — never a human-readable message."""
        wam = _fresh_wam()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = wam.resolve_stage_responsibility("STAGE-999")
        self.assertIn(result["status"], wam.RESOLUTION_STATUS)

    def test_resolve_result_has_stable_key_shape_across_all_statuses(self):
        wam = _fresh_wam()
        expected_keys = {"status", "stage_id", "role_id", "person_id", "relation_id", "errors"}

        with patch("business_core.sheets.find_row_by_id", return_value=None):
            unconfig_like = wam.resolve_stage_responsibility("")
        self.assertEqual(set(unconfig_like.keys()), expected_keys)

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()):
            unconfigured = wam.resolve_stage_responsibility("STAGE-001")
        self.assertEqual(set(unconfigured.keys()), expected_keys)

    def test_write_functions_return_ok_key(self):
        wam = _fresh_wam()
        self.assertIn("ok", wam.assign_role_to_stage("", ""))
        self.assertIn("ok", wam.reassign_stage_role("", ""))


# ─────────────────────────────────────────────────────────────
# Import guards / Core & Organization Layer protection
# ─────────────────────────────────────────────────────────────

class TestImportGuardsAndCoreProtection(unittest.TestCase):

    def test_no_gtd_imports(self):
        path = WORKSPACE / "business_core" / "work_assignment_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN)

    def test_only_expected_business_core_modules_imported(self):
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

    def test_no_telegram_handlers_or_roadmap_manager_import(self):
        wam = _fresh_wam()
        import inspect
        src = inspect.getsource(wam)
        self.assertNotIn("telegram_handlers", src)
        self.assertNotIn("roadmap_manager", src)

    def test_never_writes_to_roadmap_stages_or_roadmaps(self):
        """The only sheet this module ever writes to is
        stage_entity_relations — confirmed by tracking every
        get_business_sheet() call during a full write-path exercise."""
        wam = _fresh_wam()
        relation_sheet, values = _make_relation_sheet([])
        touched_sheets = []

        def fake_get_business_sheet(key):
            touched_sheets.append(key)
            if key == "stage_entity_relations":
                return relation_sheet
            raise AssertionError(f"work_assignment_manager must not touch sheet '{key}'")

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.organization_manager.find_role_by_id", return_value=dict(ACTIVE_ROLE)), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.find_active_duplicate_relation", return_value=None), \
             patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            wam.assign_role_to_stage("STAGE-001", "ROLE-001")

        self.assertEqual(set(touched_sheets), {"stage_entity_relations"})

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_wam()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
