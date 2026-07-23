"""
Tests for Phase 21C — Organization Manager: Role Function + Person Role
Assignment CRUD.

Covers business_core/organization_manager.py's Role Function and
Assignment functions: create/find/list/update/archive for Functions;
assign/end/list-by-person/list-by-role/history/vacancy/multi-role for
Assignments. Does not modify or re-test Department/Role logic — see
test_business_organization_department_role.py (Phase 21B) for that.

No live Sheets writes — mocks only, per ENGINEERING_STANDARDS.md Testing
Standards.
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

ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]
ROLE_ROW = [
    "ROLE-001", "DEPT-001", "Coordinator", "",
    "internal", "full_time", "planned", "", "", "",
]

FUNCTION_HEADERS = [
    "Function ID", "Role ID", "Function Category", "Function Name",
    "Description", "Frequency", "Criticality", "Can Delegate",
    "Status", "Sort Order",
]
FUNCTION_ROW = [
    "FUNC-001", "ROLE-001", "client_management", "Обработка входящих обращений",
    "", "continuous", "high", "false", "active", "1",
]

ASSIGNMENT_HEADERS = [
    "Assignment ID", "Person ID", "Role ID",
    "Start Date", "End Date", "Assignment Type", "Status", "Notes",
]
ASSIGNMENT_ROW = [
    "PRA-001", "PRS-001", "ROLE-001",
    "2026-01-01", "", "primary", "active", "",
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


def _make_multi_sheet(headers, rows):
    sheet = MagicMock()
    sheet.get_all_values.return_value = [headers] + rows
    return sheet


def _multi_get(mapping: dict):
    """Router for get_business_sheet mocking multiple sheet keys."""
    def fake_get(key):
        return mapping.get(key, MagicMock())
    return fake_get


# ─────────────────────────────────────────────────────────────
# Role Function: create
# ─────────────────────────────────────────────────────────────

class TestCreateRoleFunction(unittest.TestCase):

    def test_create_minimal_success(self):
        om = _fresh_om()
        role_sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW)
        func_sheet = MagicMock()
        func_sheet.get_all_values.return_value = [FUNCTION_HEADERS]

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get({"role_registry": role_sheet, "role_functions": func_sheet})):
            result = om.create_role_function("Первичная квалификация", role_id="ROLE-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["function_id"].startswith("FUNC-"))

    def test_create_missing_name_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("", role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertIn("function_name", result["error"])

    def test_create_missing_role_id_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("Follow-up", role_id="")
        self.assertFalse(result["ok"])
        self.assertIn("role_id", result["error"])

    def test_create_unknown_role_rejected(self):
        om = _fresh_om()
        role_sheet = MagicMock()
        role_sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=role_sheet):
            result = om.create_role_function("Follow-up", role_id="ROLE-999")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_create_invalid_status_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("Follow-up", role_id="ROLE-001", status="bogus")
        self.assertFalse(result["ok"])

    def test_create_invalid_frequency_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("Follow-up", role_id="ROLE-001", frequency="hourly")
        self.assertFalse(result["ok"])
        for freq in om.FUNCTION_FREQUENCY:
            self.assertIn(freq, result["error"])

    def test_create_invalid_criticality_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("Follow-up", role_id="ROLE-001", criticality="extreme")
        self.assertFalse(result["ok"])

    def test_create_invalid_can_delegate_rejected(self):
        om = _fresh_om()
        result = om.create_role_function("Follow-up", role_id="ROLE-001", can_delegate="yes")
        self.assertFalse(result["ok"])

    def test_create_blank_frequency_and_criticality_allowed(self):
        """Deferred fields (Phase 20A revised §6) — blank is valid, not
        required."""
        om = _fresh_om()
        role_sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW)
        func_sheet = MagicMock()
        func_sheet.get_all_values.return_value = [FUNCTION_HEADERS]
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get({"role_registry": role_sheet, "role_functions": func_sheet})):
            result = om.create_role_function("Follow-up", role_id="ROLE-001", frequency="", criticality="")
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Role Function: find / list
# ─────────────────────────────────────────────────────────────

class TestFindListRoleFunction(unittest.TestCase):

    def test_find_by_id_found(self):
        om = _fresh_om()
        sheet = _make_sheet(FUNCTION_HEADERS, FUNCTION_ROW)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            func = om.find_role_function_by_id("FUNC-001")
        self.assertIsNotNone(func)
        self.assertEqual(func["function_name"], "Обработка входящих обращений")
        self.assertEqual(func["row_num"], 2)

    def test_find_by_id_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_role_function_by_id("FUNC-999"))

    def test_list_filtered_by_role_sorted_by_sort_order(self):
        om = _fresh_om()
        rows = [
            ["FUNC-002", "ROLE-001", "communications", "SendPulse", "", "", "", "false", "active", "2"],
            ["FUNC-001", "ROLE-001", "client_management", "Обращения", "", "", "", "false", "active", "1"],
            ["FUNC-003", "ROLE-002", "reporting", "Отчётность", "", "", "", "false", "active", "1"],
        ]
        sheet = _make_multi_sheet(FUNCTION_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            funcs = om.list_role_functions(role_id="ROLE-001")
        self.assertEqual(len(funcs), 2)
        self.assertEqual([f["function_id"] for f in funcs], ["FUNC-001", "FUNC-002"])

    def test_list_filtered_by_status(self):
        om = _fresh_om()
        rows = [
            ["FUNC-001", "ROLE-001", "x", "A", "", "", "", "false", "active", "1"],
            ["FUNC-002", "ROLE-001", "x", "B", "", "", "", "false", "inactive", "2"],
        ]
        sheet = _make_multi_sheet(FUNCTION_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            active = om.list_role_functions(status="active")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["function_id"], "FUNC-001")


# ─────────────────────────────────────────────────────────────
# Role Function: update / archive / reassignment
# ─────────────────────────────────────────────────────────────

class TestUpdateArchiveRoleFunction(unittest.TestCase):

    def test_reassign_function_to_different_role(self):
        """Simulates 'move this function from Coordinator to Inbound
        Manager' — a single field update, per Phase 20A revised §6."""
        om = _fresh_om()
        func_sheet = _make_sheet(FUNCTION_HEADERS, list(FUNCTION_ROW))
        # sheet.find() is stubbed to return a valid cell for ANY ID here —
        # sufficient to prove find_role_by_id("ROLE-002") resolves as
        # "exists" and the reassignment write proceeds.
        role_sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW)

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get({"role_functions": func_sheet, "role_registry": role_sheet})):
            result = om.update_role_function("FUNC-001", {"Role ID": "ROLE-002"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Role ID",))
        row_num, col, value = func_sheet.update_cell.call_args[0]
        self.assertEqual(col, FUNCTION_HEADERS.index("Role ID") + 1)
        self.assertEqual(value, "ROLE-002")

    def test_reassign_unknown_role_rejected(self):
        om = _fresh_om()
        func_sheet = _make_sheet(FUNCTION_HEADERS, list(FUNCTION_ROW))
        role_sheet_not_found = MagicMock()
        role_sheet_not_found.find.return_value = None

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get({"role_functions": func_sheet, "role_registry": role_sheet_not_found})):
            result = om.update_role_function("FUNC-001", {"Role ID": "ROLE-999"})
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_update_sort_order(self):
        om = _fresh_om()
        sheet = _make_sheet(FUNCTION_HEADERS, list(FUNCTION_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_role_function("FUNC-001", {"Sort Order": "5"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Sort Order",))

    def test_update_unknown_field_rejected(self):
        om = _fresh_om()
        result = om.update_role_function("FUNC-001", {"Bogus": "x"})
        self.assertFalse(result["ok"])

    def test_archive_sets_status_inactive(self):
        om = _fresh_om()
        sheet = _make_sheet(FUNCTION_HEADERS, list(FUNCTION_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role_function("FUNC-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(value, "inactive")

    def test_archive_is_idempotent(self):
        om = _fresh_om()
        inactive_row = list(FUNCTION_ROW)
        inactive_row[FUNCTION_HEADERS.index("Status")] = "inactive"
        sheet = _make_sheet(FUNCTION_HEADERS, inactive_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role_function("FUNC-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_archive_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role_function("FUNC-999")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Assignment: create
# ─────────────────────────────────────────────────────────────

class TestAssignPersonToRole(unittest.TestCase):

    def _people_role_assignment_sheets(self, person_exists=True, role_exists=True):
        people_sheet = MagicMock()
        people_sheet.get_all_values.return_value = [["ID"], ["PRS-001"]] if person_exists else [["ID"]]
        role_sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW) if role_exists else MagicMock()
        if not role_exists:
            role_sheet.find.return_value = None
        assignment_sheet = MagicMock()
        assignment_sheet.get_all_values.return_value = [ASSIGNMENT_HEADERS]
        return {
            "people_registry": people_sheet,
            "role_registry": role_sheet,
            "person_role_assignments": assignment_sheet,
        }

    def test_assign_minimal_success(self):
        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get(self._people_role_assignment_sheets())):
            result = om.assign_person_to_role("PRS-001", "ROLE-001", "2026-01-01")
        self.assertTrue(result["ok"])
        self.assertTrue(result["assignment_id"].startswith("PRA-"))

    def test_assign_missing_person_id_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("", "ROLE-001", "2026-01-01")
        self.assertFalse(result["ok"])
        self.assertIn("person_id", result["error"])

    def test_assign_missing_role_id_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("PRS-001", "", "2026-01-01")
        self.assertFalse(result["ok"])
        self.assertIn("role_id", result["error"])

    def test_assign_missing_start_date_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("PRS-001", "ROLE-001", "")
        self.assertFalse(result["ok"])
        self.assertIn("start_date", result["error"])

    def test_assign_invalid_date_format_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("PRS-001", "ROLE-001", "01/01/2026")
        self.assertFalse(result["ok"])
        self.assertIn("YYYY-MM-DD", result["error"])

    def test_assign_invalid_assignment_type_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("PRS-001", "ROLE-001", "2026-01-01", assignment_type="bogus")
        self.assertFalse(result["ok"])

    def test_assign_invalid_status_rejected(self):
        om = _fresh_om()
        result = om.assign_person_to_role("PRS-001", "ROLE-001", "2026-01-01", status="bogus")
        self.assertFalse(result["ok"])

    def test_assign_unknown_person_rejected(self):
        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get(self._people_role_assignment_sheets(person_exists=False))):
            result = om.assign_person_to_role("PRS-999", "ROLE-001", "2026-01-01")
        self.assertFalse(result["ok"])
        self.assertIn("PRS-999", result["error"])

    def test_assign_unknown_role_rejected(self):
        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get(self._people_role_assignment_sheets(role_exists=False))):
            result = om.assign_person_to_role("PRS-001", "ROLE-999", "2026-01-01")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_assign_does_not_write_to_people_registry(self):
        """Only a read-only find_row_by_id check into people_registry —
        never a write (Layer Dependency Rules)."""
        om = _fresh_om()
        sheets = self._people_role_assignment_sheets()
        with patch("business_core.sheets.get_business_sheet", side_effect=_multi_get(sheets)):
            om.assign_person_to_role("PRS-001", "ROLE-001", "2026-01-01")
        sheets["people_registry"].update_cell.assert_not_called()
        sheets["people_registry"].append_row.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Assignment: find / list / history / vacancy / multi-role
# ─────────────────────────────────────────────────────────────

class TestFindListAssignment(unittest.TestCase):

    def test_find_by_id_found(self):
        om = _fresh_om()
        sheet = _make_sheet(ASSIGNMENT_HEADERS, ASSIGNMENT_ROW)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            a = om.find_assignment_by_id("PRA-001")
        self.assertIsNotNone(a)
        self.assertEqual(a["person_id"], "PRS-001")
        self.assertEqual(a["role_id"], "ROLE-001")
        self.assertEqual(a["status"], "active")

    def test_find_by_id_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_assignment_by_id("PRA-999"))

    def test_list_assignments_for_person(self):
        om = _fresh_om()
        rows = [
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "", "primary", "active", ""],
            ["PRA-002", "PRS-002", "ROLE-002", "2026-01-01", "", "primary", "active", ""],
        ]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = om.list_assignments_for_person("PRS-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["assignment_id"], "PRA-001")

    def test_list_assignments_for_role(self):
        om = _fresh_om()
        rows = [
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "", "primary", "active", ""],
            ["PRA-002", "PRS-002", "ROLE-002", "2026-01-01", "", "primary", "active", ""],
        ]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = om.list_assignments_for_role("ROLE-002")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["assignment_id"], "PRA-002")

    def test_empty_person_or_role_id_returns_empty_list(self):
        om = _fresh_om()
        self.assertEqual(om.list_assignments_for_person(""), [])
        self.assertEqual(om.list_assignments_for_role(""), [])


class TestAssignmentHistory(unittest.TestCase):

    def test_history_includes_all_statuses_sorted_by_start_date(self):
        om = _fresh_om()
        rows = [
            ["PRA-002", "PRS-002", "ROLE-001", "2026-03-01", "", "primary", "active", ""],
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "2026-02-28", "primary", "ended", ""],
        ]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            history = om.get_assignment_history("ROLE-001")
        self.assertEqual(len(history), 2)
        self.assertEqual([h["assignment_id"] for h in history], ["PRA-001", "PRA-002"])

    def test_history_never_excludes_ended_assignments(self):
        om = _fresh_om()
        rows = [["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "2026-02-28", "primary", "ended", ""]]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            history = om.get_assignment_history("ROLE-001")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "ended")


class TestVacancyDetection(unittest.TestCase):

    def test_role_with_zero_active_assignments_is_vacant(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [ASSIGNMENT_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertTrue(om.is_role_vacant("ROLE-002"))

    def test_role_with_one_active_assignment_is_not_vacant(self):
        om = _fresh_om()
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, [list(ASSIGNMENT_ROW)])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertFalse(om.is_role_vacant("ROLE-001"))

    def test_role_becomes_vacant_again_after_ending_only_assignment(self):
        om = _fresh_om()
        ended_row = list(ASSIGNMENT_ROW)
        ended_row[ASSIGNMENT_HEADERS.index("Status")] = "ended"
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, [ended_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertTrue(om.is_role_vacant("ROLE-001"))


class TestMultiRole(unittest.TestCase):

    def test_person_with_two_active_assignments_both_readable(self):
        om = _fresh_om()
        rows = [
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "", "primary", "active", ""],
            ["PRA-002", "PRS-001", "ROLE-002", "2026-01-01", "", "backup", "active", ""],
        ]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            active_roles = om.get_active_roles_for_person("PRS-001")
        self.assertEqual(len(active_roles), 2)
        self.assertEqual({a["role_id"] for a in active_roles}, {"ROLE-001", "ROLE-002"})

    def test_ended_assignment_excluded_from_active_roles(self):
        om = _fresh_om()
        rows = [
            ["PRA-001", "PRS-001", "ROLE-001", "2026-01-01", "2026-02-01", "primary", "ended", ""],
            ["PRA-002", "PRS-001", "ROLE-002", "2026-01-01", "", "primary", "active", ""],
        ]
        sheet = _make_multi_sheet(ASSIGNMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            active_roles = om.get_active_roles_for_person("PRS-001")
        self.assertEqual(len(active_roles), 1)
        self.assertEqual(active_roles[0]["role_id"], "ROLE-002")


# ─────────────────────────────────────────────────────────────
# Assignment: end / update / idempotency
# ─────────────────────────────────────────────────────────────

class TestEndAssignment(unittest.TestCase):

    def test_end_sets_end_date_and_status(self):
        om = _fresh_om()
        sheet = _make_sheet(ASSIGNMENT_HEADERS, list(ASSIGNMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.end_assignment("PRA-001", end_date="2026-06-30")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        calls = {c.args[1]: c.args[2] for c in sheet.update_cell.call_args_list}
        self.assertEqual(calls[ASSIGNMENT_HEADERS.index("Status") + 1], "ended")
        self.assertEqual(calls[ASSIGNMENT_HEADERS.index("End Date") + 1], "2026-06-30")

    def test_end_without_explicit_date_uses_today(self):
        om = _fresh_om()
        sheet = _make_sheet(ASSIGNMENT_HEADERS, list(ASSIGNMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.end_assignment("PRA-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_end_invalid_date_format_rejected(self):
        om = _fresh_om()
        sheet = _make_sheet(ASSIGNMENT_HEADERS, list(ASSIGNMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.end_assignment("PRA-001", end_date="not-a-date")
        self.assertFalse(result["ok"])

    def test_end_is_idempotent(self):
        om = _fresh_om()
        ended_row = list(ASSIGNMENT_ROW)
        ended_row[ASSIGNMENT_HEADERS.index("Status")] = "ended"
        ended_row[ASSIGNMENT_HEADERS.index("End Date")] = "2026-06-30"
        sheet = _make_sheet(ASSIGNMENT_HEADERS, ended_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.end_assignment("PRA-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_end_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.end_assignment("PRA-999")
        self.assertFalse(result["ok"])

    def test_end_does_not_touch_role_row(self):
        """Role row is never written by end_assignment — vacancy is a
        pure read-time computation over Assignment rows."""
        om = _fresh_om()
        assignment_sheet = _make_sheet(ASSIGNMENT_HEADERS, list(ASSIGNMENT_ROW))
        role_sheet = MagicMock()

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=_multi_get({"person_role_assignments": assignment_sheet, "role_registry": role_sheet})):
            om.end_assignment("PRA-001")
        role_sheet.update_cell.assert_not_called()


class TestUpdateAssignment(unittest.TestCase):

    def test_update_notes(self):
        om = _fresh_om()
        sheet = _make_sheet(ASSIGNMENT_HEADERS, list(ASSIGNMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_assignment("PRA-001", {"Notes": "переведён из другого офиса"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Notes",))

    def test_update_person_id_not_editable(self):
        """Person ID/Role ID are not in the editable-fields allowlist —
        'transfer' is modeled as end + new assign, never an in-place FK
        rewrite (preserves history)."""
        om = _fresh_om()
        result = om.update_assignment("PRA-001", {"Person ID": "PRS-002"})
        self.assertFalse(result["ok"])
        self.assertIn("Person ID", result["error"])

    def test_update_role_id_not_editable(self):
        om = _fresh_om()
        result = om.update_assignment("PRA-001", {"Role ID": "ROLE-002"})
        self.assertFalse(result["ok"])
        self.assertIn("Role ID", result["error"])

    def test_update_invalid_start_date_format_rejected(self):
        om = _fresh_om()
        result = om.update_assignment("PRA-001", {"Start Date": "bad-date"})
        self.assertFalse(result["ok"])

    def test_update_invalid_assignment_type_rejected(self):
        om = _fresh_om()
        result = om.update_assignment("PRA-001", {"Assignment Type": "bogus"})
        self.assertFalse(result["ok"])

    def test_update_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_assignment("PRA-999", {"Notes": "x"})
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Idempotency (cross-cutting: create + repeated archive/end)
# ─────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_double_archive_role_function_same_result(self):
        om = _fresh_om()
        inactive_row = list(FUNCTION_ROW)
        inactive_row[FUNCTION_HEADERS.index("Status")] = "inactive"
        sheet = _make_sheet(FUNCTION_HEADERS, inactive_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            first = om.archive_role_function("FUNC-001")
            second = om.archive_role_function("FUNC-001")
        self.assertEqual(first, second)

    def test_double_end_assignment_same_result_shape(self):
        om = _fresh_om()
        ended_row = list(ASSIGNMENT_ROW)
        ended_row[ASSIGNMENT_HEADERS.index("Status")] = "ended"
        ended_row[ASSIGNMENT_HEADERS.index("End Date")] = "2026-06-30"
        sheet = _make_sheet(ASSIGNMENT_HEADERS, ended_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            first = om.end_assignment("PRA-001")
            second = om.end_assignment("PRA-001")
        self.assertEqual(first, second)


# ─────────────────────────────────────────────────────────────
# Honest return contract
# ─────────────────────────────────────────────────────────────

class TestHonestReturnContract(unittest.TestCase):

    def test_all_write_functions_return_ok_key(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIn("ok", om.update_role_function("FUNC-999", {"Notes": "x"}))
            self.assertIn("ok", om.archive_role_function("FUNC-999"))
            self.assertIn("ok", om.update_assignment("PRA-999", {"Notes": "x"}))
            self.assertIn("ok", om.end_assignment("PRA-999"))
        self.assertIn("ok", om.create_role_function("", role_id=""))
        self.assertIn("ok", om.assign_person_to_role("", "", ""))

    def test_find_functions_return_none_not_exception_on_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_role_function_by_id("FUNC-999"))
            self.assertIsNone(om.find_assignment_by_id("PRA-999"))

    def test_list_and_history_functions_return_list_never_none(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.side_effect = Exception("sheets down")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.list_role_functions(), [])
            self.assertEqual(om.list_assignments_for_person("PRS-001"), [])
            self.assertEqual(om.list_assignments_for_role("ROLE-001"), [])
            self.assertEqual(om.get_assignment_history("ROLE-001"), [])
            self.assertEqual(om.get_active_roles_for_person("PRS-001"), [])


# ─────────────────────────────────────────────────────────────
# Import guards / API surface guards (Phase 21C closeout)
# ─────────────────────────────────────────────────────────────

class TestFullApiSurfaceContract(unittest.TestCase):
    """Locks in the COMPLETE public function surface of
    organization_manager.py as of Phase 21C (Department/Role from 21B +
    Function/Assignment from 21C)."""

    EXPECTED_PUBLIC_FUNCTIONS = (
        # Phase 21B
        "find_department_by_id", "list_departments", "create_department",
        "update_department", "archive_department",
        "find_role_by_id", "list_roles", "create_role",
        "update_role", "archive_role",
        # Phase 21C
        "find_role_function_by_id", "list_role_functions", "create_role_function",
        "update_role_function", "archive_role_function",
        "find_assignment_by_id", "list_assignments_for_person", "list_assignments_for_role",
        "get_assignment_history", "is_role_vacant", "get_active_roles_for_person",
        "assign_person_to_role", "end_assignment", "update_assignment",
    )

    EXPECTED_ENUMS = (
        "DEPARTMENT_STATUS", "ROLE_STATUS", "ROLE_TYPE", "EMPLOYMENT_MODEL",
        "ROLE_FUNCTION_STATUS", "FUNCTION_FREQUENCY", "CRITICALITY", "VALID_BOOL_STRINGS",
        "ASSIGNMENT_STATUS", "ASSIGNMENT_TYPE",
    )

    def test_exact_public_function_surface(self):
        om = _fresh_om()
        public_callables = {
            name for name in vars(om)
            if not name.startswith("_") and callable(getattr(om, name))
            and getattr(getattr(om, name), "__module__", "") == om.__name__
        }
        self.assertEqual(public_callables, set(self.EXPECTED_PUBLIC_FUNCTIONS))

    def test_all_expected_enums_exist_and_are_tuples(self):
        om = _fresh_om()
        for name in self.EXPECTED_ENUMS:
            self.assertTrue(hasattr(om, name), f"missing enum: {name}")
            self.assertIsInstance(getattr(om, name), tuple)


class TestModuleOnlyDependsOnSheets(unittest.TestCase):
    """Layer Dependency Rules (ENGINEERING_STANDARDS.md §2) — re-verified
    after Phase 21C's additions."""

    def test_only_business_core_sheets_imported_within_business_core(self):
        path = WORKSPACE / "business_core" / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        business_core_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("business_core"):
                    business_core_imports.add(node.module)
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("business_core"):
                        business_core_imports.add(a.name)
        self.assertEqual(business_core_imports, {"business_core.sheets"})

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
