"""
Tests for Phase 36C — Task Domain Foundation: business_core/task_manager.py
and the task_registry/task_assignments schema additions to
business_core/sheets.py (ADR-019).

Covers schema registration, Task ID/Task Assignment ID generation, and
every low-level persistence function: create_task, update_task_admin_fields,
update_task_status, update_task_assignment_cache, create_task_assignment,
end_task_assignment, and the read helpers. No cross-entity eligibility,
no Organization/Roadmap/Stage validation — that's business_builder.py's
job, covered separately in test_business_task_foundation.py.

No live Sheets writes — mocks only, per ENGINEERING_STANDARDS.md Testing
Standards. Registered in conftest.py's hard socket-block set (Phase 36C,
ADR-019 §27) before this file's logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

TASK_HEADERS = [
    "Task ID", "Business ID", "Title", "Description", "Status",
    "Priority", "Due Date", "Source", "Idempotency Key",
    "Client ID", "Object ID", "Service ID", "Roadmap ID", "Stage ID",
    "Responsible Role ID", "Assignee Person ID",
    "Created At", "Updated At", "Started At", "Completed At", "Cancelled At",
    "Created By", "GTD Action ID",
]

TASK_ROW = [
    "TSK-001", "BIZ-001", "Prepare docs", "desc", "new",
    "", "", "manual", "IDEMP-1",
    "", "", "", "", "",
    "", "",
    "2026-01-01", "2026-01-01", "", "", "",
    "", "",
]

TASK_ASSIGNMENT_HEADERS = [
    "Task Assignment ID", "Task ID", "Responsible Role ID",
    "Assignee Person ID", "Status", "Start Date", "End Date",
    "Assignment Type", "Created At", "Updated At",
]

TASK_ASSIGNMENT_ROW = [
    "TAS-001", "TSK-001", "ROLE-001", "",
    "active", "2026-01-01", "", "primary", "2026-01-01", "2026-01-01",
]


def _fresh_tm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.task_manager")


def _make_sheet(headers, row, row_num=2, extra_rows=None):
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    all_values = [headers] + [row] + (extra_rows or [])
    sheet.get_all_values.return_value = all_values
    return sheet


class TestSchemaRegistration(unittest.TestCase):

    def test_task_registry_registered(self):
        import business_core.sheets as sheets
        self.assertIn("task_registry", sheets.BUSINESS_SHEET_NAMES)
        self.assertEqual(sheets.BUSINESS_SHEET_NAMES["task_registry"], "TASK_REGISTRY")

    def test_task_assignments_registered(self):
        import business_core.sheets as sheets
        self.assertIn("task_assignments", sheets.BUSINESS_SHEET_NAMES)
        self.assertEqual(sheets.BUSINESS_SHEET_NAMES["task_assignments"], "TASK_ASSIGNMENTS")

    def test_task_registry_headers_exact(self):
        import business_core.sheets as sheets
        self.assertEqual(sheets.BUSINESS_HEADERS["task_registry"], TASK_HEADERS)

    def test_task_assignments_headers_exact(self):
        import business_core.sheets as sheets
        self.assertEqual(sheets.BUSINESS_HEADERS["task_assignments"], TASK_ASSIGNMENT_HEADERS)

    def test_no_duplicate_headers_in_task_registry(self):
        import business_core.sheets as sheets
        headers = sheets.BUSINESS_HEADERS["task_registry"]
        self.assertEqual(len(headers), len(set(headers)))

    def test_no_duplicate_headers_in_task_assignments(self):
        import business_core.sheets as sheets
        headers = sheets.BUSINESS_HEADERS["task_assignments"]
        self.assertEqual(len(headers), len(set(headers)))

    def test_task_id_prefix(self):
        import business_core.sheets as sheets
        self.assertEqual(sheets._ID_PREFIXES["task_registry"], "TSK")

    def test_task_assignment_id_prefix(self):
        import business_core.sheets as sheets
        self.assertEqual(sheets._ID_PREFIXES["task_assignments"], "TAS")

    def test_gtd_schema_unmodified(self):
        """This phase must never touch GTD-owned schema definitions."""
        import business_core.sheets as sheets
        for key in ("roadmap_stages", "roadmaps"):
            self.assertIn("GTD Action ID" if key == "roadmap_stages" else "GTD Project ID", sheets.BUSINESS_HEADERS[key])


class TestIdGeneration(unittest.TestCase):

    def test_task_id_generation_empty_registry_starts_at_001(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_id
            self.assertEqual(generate_next_id("task_registry"), "TSK-001")

    def test_task_assignment_id_generation_empty_registry_starts_at_001(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_ASSIGNMENT_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_id
            self.assertEqual(generate_next_id("task_assignments"), "TAS-001")

    def test_task_id_generation_increments(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_id
            self.assertEqual(generate_next_id("task_registry"), "TSK-002")


class TestFindTaskById(unittest.TestCase):

    def test_found(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            task = tm.find_task_by_id("TSK-001")
        self.assertIsNotNone(task)
        self.assertEqual(task["task_id"], "TSK-001")
        self.assertEqual(task["business_id"], "BIZ-001")
        self.assertEqual(task["status"], "new")

    def test_not_found(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(tm.find_task_by_id("TSK-999"))

    def test_blank_id_returns_none(self):
        tm = _fresh_tm()
        self.assertIsNone(tm.find_task_by_id(""))


class TestCreateTask(unittest.TestCase):

    def test_missing_business_id_rejected(self):
        tm = _fresh_tm()
        result = tm.create_task("", "Title")
        self.assertFalse(result["ok"])

    def test_missing_title_rejected(self):
        tm = _fresh_tm()
        result = tm.create_task("BIZ-001", "")
        self.assertFalse(result["ok"])

    def test_invalid_status_rejected(self):
        tm = _fresh_tm()
        result = tm.create_task("BIZ-001", "Title", status="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_STATUS")

    def test_successful_creation(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.row_values.return_value = TASK_HEADERS
        with patch("business_core.sheets.generate_next_id", return_value="TSK-050"), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = tm.create_task("BIZ-001", "Title")
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_id"], "TSK-050")
        self.assertEqual(result["code"], "TASK_CREATED")
        mock_append.assert_called_once()
        row = mock_append.call_args[0][1]
        self.assertEqual(row[TASK_HEADERS.index("Task ID")], "TSK-050")
        self.assertEqual(row[TASK_HEADERS.index("Business ID")], "BIZ-001")
        self.assertEqual(row[TASK_HEADERS.index("Status")], "new")


class TestUpdateTaskAdminFields(unittest.TestCase):

    def test_title_update_succeeds(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_admin_fields("TSK-001", {"Title": "New Title"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "TASK_ADMIN_FIELDS_UPDATED")

    def test_unchanged_value_reports_unchanged(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_admin_fields("TSK-001", {"Title": "Prepare docs"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "TASK_ADMIN_FIELDS_UNCHANGED")

    def test_task_id_identity_conflict(self):
        tm = _fresh_tm()
        result = tm.update_task_admin_fields("TSK-001", {"Task ID": "TSK-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_IMMUTABLE_FIELD_CONFLICT")

    def test_business_id_identity_conflict(self):
        tm = _fresh_tm()
        result = tm.update_task_admin_fields("TSK-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_IMMUTABLE_FIELD_CONFLICT")

    def test_created_at_identity_conflict(self):
        tm = _fresh_tm()
        result = tm.update_task_admin_fields("TSK-001", {"Created At": "2026-02-02"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_IMMUTABLE_FIELD_CONFLICT")

    def test_relation_field_blocked(self):
        tm = _fresh_tm()
        for field in ("Client ID", "Object ID", "Service ID", "Roadmap ID", "Stage ID"):
            result = tm.update_task_admin_fields("TSK-001", {field: "X-001"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION")

    def test_assignment_cache_field_blocked(self):
        tm = _fresh_tm()
        for field in ("Responsible Role ID", "Assignee Person ID"):
            result = tm.update_task_admin_fields("TSK-001", {field: "X-001"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "INVALID_TASK_ADMIN_FIELD")

    def test_status_field_blocked(self):
        tm = _fresh_tm()
        result = tm.update_task_admin_fields("TSK-001", {"Status": "done"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_ADMIN_FIELD")

    def test_unknown_field_rejected(self):
        tm = _fresh_tm()
        result = tm.update_task_admin_fields("TSK-001", {"Bogus": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_ADMIN_FIELD")

    def test_not_found(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_admin_fields("TSK-999", {"Title": "X"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")


class TestUpdateTaskStatus(unittest.TestCase):

    def test_status_change(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_status("TSK-001", "ready")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_unchanged_status(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_status("TSK-001", "new")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_invalid_status_rejected(self):
        tm = _fresh_tm()
        result = tm.update_task_status("TSK-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_STATUS")

    def test_timestamp_field_written_once(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            tm.update_task_status("TSK-001", "in_progress", timestamp_field="Started At")
        calls = [c.args for c in sheet.update_cell.call_args_list]
        started_col = TASK_HEADERS.index("Started At") + 1
        self.assertTrue(any(c[1] == started_col for c in calls))

    def test_timestamp_field_not_overwritten_if_already_set(self):
        tm = _fresh_tm()
        row = list(TASK_ROW)
        row[TASK_HEADERS.index("Started At")] = "2026-01-05"
        sheet = _make_sheet(TASK_HEADERS, row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            tm.update_task_status("TSK-001", "in_progress", timestamp_field="Started At")
        calls = [c.args for c in sheet.update_cell.call_args_list]
        started_col = TASK_HEADERS.index("Started At") + 1
        self.assertFalse(any(c[1] == started_col for c in calls))


class TestUpdateTaskAssignmentCache(unittest.TestCase):

    def test_cache_updated(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_assignment_cache("TSK-001", "ROLE-001", "PRS-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_cache_unchanged_when_same(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_HEADERS, list(TASK_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.update_task_assignment_cache("TSK-001", "", "")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])


class TestTaskAssignmentPersistence(unittest.TestCase):

    def test_create_task_assignment_success(self):
        tm = _fresh_tm()
        with patch("business_core.sheets.generate_next_id", return_value="TAS-100"), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = tm.create_task_assignment("TSK-001", "ROLE-001", "", "2026-01-01")
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_assignment_id"], "TAS-100")
        self.assertEqual(result["code"], "TASK_ASSIGNMENT_CREATED")
        mock_append.assert_called_once()

    def test_create_task_assignment_missing_task_id(self):
        tm = _fresh_tm()
        result = tm.create_task_assignment("", "ROLE-001", "", "2026-01-01")
        self.assertFalse(result["ok"])

    def test_create_task_assignment_invalid_status(self):
        tm = _fresh_tm()
        result = tm.create_task_assignment("TSK-001", "ROLE-001", "", "2026-01-01", status="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_ASSIGNMENT_STATUS")

    def test_list_task_assignments_for_task(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_ASSIGNMENT_HEADERS, TASK_ASSIGNMENT_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = tm.list_task_assignments_for_task("TSK-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_assignment_id"], "TAS-001")

    def test_find_task_assignment_by_id(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_ASSIGNMENT_HEADERS, TASK_ASSIGNMENT_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_task_assignment_by_id("TAS-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["responsible_role_id"], "ROLE-001")

    def test_end_task_assignment_idempotent(self):
        tm = _fresh_tm()
        ended_row = list(TASK_ASSIGNMENT_ROW)
        ended_row[TASK_ASSIGNMENT_HEADERS.index("Status")] = "ended"
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_ASSIGNMENT_HEADERS, ended_row]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.end_task_assignment("TAS-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_end_task_assignment_writes_status_and_end_date(self):
        tm = _fresh_tm()
        sheet = _make_sheet(TASK_ASSIGNMENT_HEADERS, list(TASK_ASSIGNMENT_ROW))
        # find_task_assignment_by_id scans via get_all_values, then
        # end_task_assignment writes via sheet.find()+update_cell().
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.end_task_assignment("TAS-001", end_date="2026-02-01")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_no_hard_delete_call_exists(self):
        """Architecture-level guard: task_manager.py must never call a
        row-deletion primitive for Task Assignments."""
        path = WORKSPACE / "business_core" / "task_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
