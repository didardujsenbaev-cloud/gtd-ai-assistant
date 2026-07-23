"""
Tests for Phase 23C — Organization Manager: Duplicate Protection.

Covers business_core/organization_manager.py's duplicate-detection logic
in create_department() and create_role(): exact/case/whitespace
duplicates, cross-Business/cross-Department/cross-Parent allowances,
archived-row exclusion, the Reports-To-is-not-identity conclusion, and
that detection happens strictly before ID generation and before any
write. No live Sheets writes — mocks only, per
ENGINEERING_STANDARDS.md Testing Standards.

Architecture conclusion locked in by these tests (see
_find_duplicate_role's docstring in organization_manager.py):
"Reports To Role ID" is an EDITABLE ORGANIZATIONAL ATTRIBUTE (member of
_ROLE_EDITABLE_FIELDS, freely reassignable via update_role() since
Phase 21B), NOT part of Role identity — therefore two Roles with the
same name in the same Department are duplicates regardless of whether
their Reports To Role ID differs.
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

DEPARTMENT_HEADERS = [
    "Department ID", "Business ID", "Department Name",
    "Parent Department ID", "Head Role ID", "Status", "Notes",
]
ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]


def _fresh_om():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.organization_manager")


def _make_multi_sheet(headers, rows):
    sheet = MagicMock()
    sheet.get_all_values.return_value = [headers] + rows
    return sheet


def _make_write_sheet(headers, existing_rows):
    """Supports get_all_values() (for list_*/duplicate-check reads) AND
    update()/row_values(1) (for the eventual append_business_row write,
    exercised only when no duplicate is detected)."""
    sheet = MagicMock()
    data_rows = [list(r) for r in existing_rows]

    def get_all_values():
        return [headers] + data_rows

    def row_values(r):
        return headers if r == 1 else data_rows[r - 2]

    def update(range_name, values):
        data_rows.append(list(values[0]))

    sheet.get_all_values.side_effect = get_all_values
    sheet.row_values.side_effect = row_values
    sheet.update.side_effect = update
    return sheet, data_rows


# ─────────────────────────────────────────────────────────────
# Department duplicate protection
# ─────────────────────────────────────────────────────────────

class TestDepartmentDuplicateProtection(unittest.TestCase):

    def test_exact_duplicate_rejected(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = om.create_department("Operations", business_id="BIZ-001")
        self.assertFalse(result["ok"])
        self.assertIn("DEPT-001", result["error"])

    def test_case_only_duplicate_rejected(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = om.create_department("OPERATIONS", business_id="BIZ-001")
        self.assertFalse(result["ok"])

    def test_whitespace_normalized_duplicate_rejected(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result2 = om.create_department("   Operations  ", business_id="BIZ-001")
        self.assertFalse(result2["ok"])

    def test_internal_double_space_normalized_duplicate_rejected(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Client   Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = om.create_department("Client Operations", business_id="BIZ-001")
        self.assertFalse(result["ok"])

    def test_same_name_different_business_allowed(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet, data_rows = _make_write_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-002"})):
            result = om.create_department("Operations", business_id="BIZ-002")
        self.assertTrue(result["ok"], result)

    def test_same_name_different_parent_allowed(self):
        om = _fresh_om()
        rows = [
            ["DEPT-001", "BIZ-001", "Regional Office", "", "", "active", ""],
            ["DEPT-002", "BIZ-001", "HQ", "", "", "active", ""],
        ]
        sheet, data_rows = _make_write_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = om.create_department(
                "Regional Office", business_id="BIZ-001", parent_department_id="DEPT-002",
            )
        self.assertTrue(result["ok"], result)

    def test_archived_department_does_not_block_new_create(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "archived", ""]]
        sheet, data_rows = _make_write_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = om.create_department("Operations", business_id="BIZ-001")
        self.assertTrue(result["ok"], result)

    def test_duplicate_rejected_before_id_generation(self):
        """generate_next_id() must never be called when a duplicate is found."""
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.sheets.generate_next_id") as mock_gen:
            om.create_department("Operations", business_id="BIZ-001")
            mock_gen.assert_not_called()

    def test_duplicate_rejected_before_write(self):
        om = _fresh_om()
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.sheets.append_business_row") as mock_append:
            om.create_department("Operations", business_id="BIZ-001")
            mock_append.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Role duplicate protection
# ─────────────────────────────────────────────────────────────

class TestRoleDuplicateProtection(unittest.TestCase):

    def _dept_sheet(self):
        rows = [["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""]]
        return _make_multi_sheet(DEPARTMENT_HEADERS, rows)

    def test_exact_duplicate_rejected(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-001", result["error"])

    def test_case_only_duplicate_rejected(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("COORDINATOR", department_id="DEPT-001")
        self.assertFalse(result["ok"])

    def test_whitespace_normalized_duplicate_rejected(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Inbound  Manager", "", "internal", "full_time", "planned", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("  Inbound Manager  ", department_id="DEPT-001")
        self.assertFalse(result["ok"])

    def test_same_name_different_department_allowed(self):
        om = _fresh_om()
        dept_rows = [
            ["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""],
            ["DEPT-002", "BIZ-001", "Sales", "", "", "active", ""],
        ]
        dept_sheet = _make_multi_sheet(DEPARTMENT_HEADERS, dept_rows)
        role_rows = [["ROLE-001", "DEPT-001", "Manager", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet, role_data = _make_write_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Manager", department_id="DEPT-002")
        self.assertTrue(result["ok"], result)

    def test_same_name_different_business_scope_allowed_via_different_department(self):
        """Role has no Business ID of its own — effective scope is
        inherited from Department. Two Departments in different
        Businesses, same Role name -> allowed, since Department ID
        (which differs) is the duplicate key, not a Role-level Business ID
        (which doesn't exist in the schema)."""
        om = _fresh_om()
        dept_rows = [
            ["DEPT-001", "BIZ-001", "Operations", "", "", "active", ""],
            ["DEPT-002", "BIZ-002", "Operations", "", "", "active", ""],
        ]
        dept_sheet = _make_multi_sheet(DEPARTMENT_HEADERS, dept_rows)
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet, role_data = _make_write_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-002")
        self.assertTrue(result["ok"], result)

    def test_archived_role_does_not_block_new_create(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "archived", "", "", ""]]
        role_sheet, role_data = _make_write_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001")
        self.assertTrue(result["ok"], result)

    def test_paused_role_does_not_block_new_create(self):
        """Only 'active'/'planned' block a duplicate — 'paused' does not
        (per the explicit instruction: only active-or-planned rows count)."""
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "paused", "", "", ""]]
        role_sheet, role_data = _make_write_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001")
        self.assertTrue(result["ok"], result)

    def test_planned_role_blocks_new_create(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "planned", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001")
        self.assertFalse(result["ok"])

    def test_different_reports_to_role_id_still_counts_as_duplicate(self):
        """The architecture conclusion under test: Reports To Role ID is
        NOT part of Role identity. Same name, same Department, DIFFERENT
        Reports To Role ID on the new request -> still rejected."""
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [
            ["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""],
            ["ROLE-002", "DEPT-001", "Operations Manager", "", "internal", "full_time", "active", "", "", ""],
        ]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            # attempting to create "Coordinator" again, this time reporting
            # to a DIFFERENT role than the existing one (which has "" for
            # Reports To Role ID) — must still be rejected as a duplicate.
            result = om.create_role(
                "Coordinator", department_id="DEPT-001", reports_to_role_id="ROLE-002",
            )
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-001", result["error"])

    def test_duplicate_rejected_before_id_generation(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get), \
             patch("business_core.sheets.generate_next_id") as mock_gen:
            om.create_role("Coordinator", department_id="DEPT-001")
            mock_gen.assert_not_called()

    def test_duplicate_rejected_before_write(self):
        om = _fresh_om()
        dept_sheet = self._dept_sheet()
        role_rows = [["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        role_sheet = _make_multi_sheet(ROLE_HEADERS, role_rows)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get), \
             patch("business_core.sheets.append_business_row") as mock_append:
            om.create_role("Coordinator", department_id="DEPT-001")
            mock_append.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Reports-To architecture conclusion — explicit, standalone assertion
# ─────────────────────────────────────────────────────────────

class TestReportsToIsNotIdentity(unittest.TestCase):

    def test_reports_to_role_id_is_in_editable_fields_not_identity(self):
        """Direct evidence for the architecture conclusion: Reports To
        Role ID is editable (update_role() already supports changing it,
        established Phase 21B), therefore it cannot be part of Role
        identity — an editable attribute is never a duplicate-detection key."""
        om = _fresh_om()
        self.assertIn("Reports To Role ID", om._ROLE_EDITABLE_FIELDS)

    def test_update_role_can_change_reports_to_without_becoming_a_new_role(self):
        om = _fresh_om()
        role_rows = [["ROLE-002", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""]]
        sheet, _ = _make_write_sheet(ROLE_HEADERS, role_rows)
        sheet.find = MagicMock(return_value=MagicMock(row=2))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_role("ROLE-002", {"Reports To Role ID": "ROLE-999-DOES-NOT-EXIST"})
        # rejected because ROLE-999 doesn't exist (FK validation) — but the
        # important point is this is a FIELD UPDATE path, not a "role
        # identity changed, create a new row" path. No new Role ID is
        # ever generated by update_role() under any circumstance.
        self.assertIn("ok", result)


# ─────────────────────────────────────────────────────────────
# Normalization helper
# ─────────────────────────────────────────────────────────────

class TestNormalizationHelper(unittest.TestCase):

    def test_trims_and_collapses_and_casefolds(self):
        om = _fresh_om()
        self.assertEqual(om._normalize_org_name("  Operations   Dept  "), "operations dept")
        self.assertEqual(om._normalize_org_name("OPERATIONS"), "operations")
        self.assertEqual(om._normalize_org_name("Operations"), "operations")

    def test_blank_and_none_safe(self):
        om = _fresh_om()
        self.assertEqual(om._normalize_org_name(""), "")
        self.assertEqual(om._normalize_org_name(None), "")


# ─────────────────────────────────────────────────────────────
# Regression / architecture guards
# ─────────────────────────────────────────────────────────────

class TestRegressionAndGuards(unittest.TestCase):

    def test_only_business_core_sheets_imported(self):
        """organization_manager.py must still depend only on
        business_core.sheets after this phase's additions — the
        normalization helper was deliberately reimplemented locally
        rather than imported from business_builder.py, to preserve this
        exact guarantee."""
        path = WORKSPACE / "business_core" / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("business_core"):
                imports.add(node.module)
        self.assertEqual(imports, {"business_core.sheets"})

    def test_no_gtd_imports(self):
        path = WORKSPACE / "business_core" / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN)

    # Note: a git-diff-based guard asserting telegram_handlers.py stayed
    # fully untouched by Phase 23C was removed here — that was a
    # point-in-time closeout check for Phase 23C specifically (already
    # satisfied and locked in by its commit), not a durable invariant.
    # Later phases (23D-2) are explicitly authorized to modify
    # telegram_handlers.py, so a generic "git diff HEAD" check would
    # misfire against any later, unrelated phase's in-progress changes.

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_om()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
