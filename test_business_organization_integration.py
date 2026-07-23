"""
Tests for Phase 21E — Organization Layer: Regression & Integration Tests.

This sub-phase adds no new production code. Its purpose (per the Phase 21
Implementation Plan) is a full-chain integration check plus the one
regression guard identified by the Phase 21C Integrity Audit as
documented-but-untested: archiving a Role must never touch
ROLE_FUNCTIONS or PERSON_ROLE_ASSIGNMENTS.

The full Department -> Role -> Function -> Assignment chain is already
exercised end-to-end by test_business_organization_seed.py's in-memory
registry tests (seed_default_organization() IS that integration test) —
this file adds the one gap the audit flagged, not a duplicate.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]
ROLE_ROW = [
    "ROLE-001", "DEPT-001", "Coordinator", "",
    "internal", "full_time", "active", "", "", "",
]


def _fresh_om():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.organization_manager")


def _make_sheet(headers, row, row_num=2):
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    sheet.get_all_values.return_value = [headers, row]
    return sheet


class TestArchiveRoleDoesNotCascade(unittest.TestCase):
    """The gap flagged by the Phase 21C Integrity Audit (§9 Test
    Completeness): archive_role()'s docstring claims it never touches
    Role Function or Assignment rows, but no test previously verified it."""

    def test_archive_role_never_calls_get_business_sheet_for_functions_or_assignments(self):
        om = _fresh_om()
        role_sheet = _make_sheet(ROLE_HEADERS, list(ROLE_ROW))
        touched_sheets = []

        def fake_get_business_sheet(key):
            touched_sheets.append(key)
            if key == "role_registry":
                return role_sheet
            raise AssertionError(f"archive_role() must not touch sheet '{key}'")

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = om.archive_role("ROLE-001")

        self.assertTrue(result["ok"])
        self.assertNotIn("role_functions", touched_sheets)
        self.assertNotIn("person_role_assignments", touched_sheets)
        self.assertEqual(set(touched_sheets), {"role_registry"})

    def test_archive_department_never_touches_role_registry(self):
        """Symmetric guard: archiving a Department must not touch Role
        (or Function/Assignment) rows either."""
        om = _fresh_om()
        DEPARTMENT_HEADERS = [
            "Department ID", "Business ID", "Department Name",
            "Parent Department ID", "Head Role ID", "Status", "Notes",
        ]
        dept_row = ["DEPT-001", "", "Operations", "", "", "active", ""]
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, dept_row)
        touched_sheets = []

        def fake_get_business_sheet(key):
            touched_sheets.append(key)
            if key == "department_registry":
                return dept_sheet
            raise AssertionError(f"archive_department() must not touch sheet '{key}'")

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = om.archive_department("DEPT-001")

        self.assertTrue(result["ok"])
        self.assertEqual(set(touched_sheets), {"department_registry"})


class TestFullChainIntegrationSmoke(unittest.TestCase):
    """A lighter-weight confirmation (beyond seed_default_organization's
    own thorough coverage) that reading a full Department -> Role ->
    Function -> Assignment chain works together without any cross-entity
    surprises, using independent hand-built mocks rather than the seed
    function's in-memory registry helper."""

    def test_read_full_chain_independently_of_seed_helper(self):
        om = _fresh_om()

        DEPARTMENT_HEADERS = [
            "Department ID", "Business ID", "Department Name",
            "Parent Department ID", "Head Role ID", "Status", "Notes",
        ]
        FUNCTION_HEADERS = [
            "Function ID", "Role ID", "Function Category", "Function Name",
            "Description", "Frequency", "Criticality", "Can Delegate",
            "Status", "Sort Order",
        ]
        ASSIGNMENT_HEADERS = [
            "Assignment ID", "Person ID", "Role ID",
            "Start Date", "End Date", "Assignment Type", "Status", "Notes",
        ]

        dept_sheet = MagicMock()
        dept_sheet.get_all_values.return_value = [
            DEPARTMENT_HEADERS,
            ["DEPT-001", "", "Operations", "", "ROLE-001", "active", ""],
        ]
        role_sheet = MagicMock()
        role_sheet.get_all_values.return_value = [
            ROLE_HEADERS,
            ["ROLE-001", "DEPT-001", "Coordinator", "", "internal", "full_time", "active", "", "", ""],
        ]
        func_sheet = MagicMock()
        func_sheet.get_all_values.return_value = [
            FUNCTION_HEADERS,
            ["FUNC-001", "ROLE-001", "reporting", "Отчётность", "", "daily", "medium", "false", "active", "1"],
        ]
        assignment_sheet = MagicMock()
        assignment_sheet.get_all_values.return_value = [
            ASSIGNMENT_HEADERS,
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "", "primary", "active", ""],
        ]

        registries = {
            "department_registry": dept_sheet,
            "role_registry": role_sheet,
            "role_functions": func_sheet,
            "person_role_assignments": assignment_sheet,
        }

        with patch("business_core.sheets.get_business_sheet", side_effect=lambda k: registries[k]):
            departments = om.list_departments()
            roles = om.list_roles(department_id="DEPT-001")
            functions = om.list_role_functions(role_id="ROLE-001")
            assignments = om.list_assignments_for_role("ROLE-001")
            vacant = om.is_role_vacant("ROLE-001")
            active_for_person = om.get_active_roles_for_person("PRS-001")

        self.assertEqual(len(departments), 1)
        self.assertEqual(len(roles), 1)
        self.assertEqual(len(functions), 1)
        self.assertEqual(len(assignments), 1)
        self.assertFalse(vacant)
        self.assertEqual(len(active_for_person), 1)
        self.assertEqual(active_for_person[0]["role_id"], "ROLE-001")


if __name__ == "__main__":
    unittest.main(verbosity=2)
