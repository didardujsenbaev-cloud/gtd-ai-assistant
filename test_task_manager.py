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


class TestGenerateNextTaskId(unittest.TestCase):
    """Phase 18A.9-A1: task_registry-only allocation — unlike
    generate_next_id(), never falls back to a predictable "-001" ID on
    a read failure."""

    def test_empty_registry_starts_at_001(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_task_id
            self.assertEqual(generate_next_task_id(), "TSK-001")

    def test_increments_from_existing_rows(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_task_id
            self.assertEqual(generate_next_task_id(), "TSK-002")

    def test_read_failure_returns_none_never_a_fallback_id(self):
        sheet = MagicMock()
        sheet.get_all_values.side_effect = RuntimeError("SENTINEL-BOOM")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import generate_next_task_id
            self.assertIsNone(generate_next_task_id())

    def test_get_business_sheet_itself_raising_returns_none(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("SENTINEL-BOOM")):
            from business_core.sheets import generate_next_task_id
            self.assertIsNone(generate_next_task_id())


class TestAppendTaskRegistryRow(unittest.TestCase):
    """Phase 18A.9-A1: task_registry-only append using gspread's real
    append_row() — never computes an explicit next_row client-side."""

    def test_uses_real_append_row_not_explicit_range_update(self):
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import append_task_registry_row
            append_task_registry_row(list(TASK_ROW))
        sheet.append_row.assert_called_once()
        sheet.update.assert_not_called()
        sheet.get_all_values.assert_not_called()

    def test_pads_row_to_header_width(self):
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import append_task_registry_row
            append_task_registry_row(["TSK-050", "BIZ-001"])
        written = sheet.append_row.call_args[0][0]
        self.assertEqual(len(written), len(TASK_HEADERS))

    def test_raises_on_failure_never_swallows(self):
        sheet = MagicMock()
        sheet.append_row.side_effect = RuntimeError("SENTINEL-BOOM")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            from business_core.sheets import append_task_registry_row
            with self.assertRaises(RuntimeError):
                append_task_registry_row(list(TASK_ROW))


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


def _verified(*matches):
    return {"ok": True, "matches": list(matches)}


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
        with patch("business_core.sheets.generate_next_task_id", return_value="TSK-050"), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_task_registry_row") as mock_append, \
             patch.object(tm, "_verify_created_task_row",
                          return_value=_verified({"task_id": "TSK-050", "business_id": "BIZ-001", "status": "new"})):
            result = tm.create_task("BIZ-001", "Title")
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_id"], "TSK-050")
        self.assertEqual(result["code"], "TASK_CREATED")
        mock_append.assert_called_once()
        row = mock_append.call_args[0][0]
        self.assertEqual(row[TASK_HEADERS.index("Task ID")], "TSK-050")
        self.assertEqual(row[TASK_HEADERS.index("Business ID")], "BIZ-001")
        self.assertEqual(row[TASK_HEADERS.index("Status")], "new")

    def test_idempotency_key_normalized_into_row(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.row_values.return_value = TASK_HEADERS
        with patch("business_core.sheets.generate_next_task_id", return_value="TSK-050"), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_task_registry_row") as mock_append, \
             patch.object(tm, "_verify_created_task_row", return_value=_verified({"task_id": "TSK-050"})):
            tm.create_task("BIZ-001", "Title", idempotency_key="  KEY-1  ")
        row = mock_append.call_args[0][0]
        self.assertEqual(row[TASK_HEADERS.index("Idempotency Key")], "KEY-1")


class TestCreateTaskIdAllocationFailure(unittest.TestCase):

    def test_id_allocation_failure_produces_fixed_code_no_append(self):
        tm = _fresh_tm()
        with patch("business_core.sheets.generate_next_task_id", return_value=None), \
             patch("business_core.sheets.append_task_registry_row") as mock_append:
            result = tm.create_task("BIZ-001", "Title")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ID_ALLOCATION_ERROR")
        self.assertIsNone(result["error"])
        self.assertEqual(result["task_id"], "")
        mock_append.assert_not_called()

    def test_header_read_failure_produces_fixed_code_no_append(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.row_values.side_effect = RuntimeError("SENTINEL-BOOM")
        with patch("business_core.sheets.generate_next_task_id", return_value="TSK-050"), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_task_registry_row") as mock_append:
            result = tm.create_task("BIZ-001", "Title")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ID_ALLOCATION_ERROR")
        mock_append.assert_not_called()
        self.assertNotIn("SENTINEL-BOOM", str(result))


class TestCreateTaskAppendAndVerification(unittest.TestCase):

    def _run(self, append_side_effect, verify_result):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.row_values.return_value = TASK_HEADERS
        with patch("business_core.sheets.generate_next_task_id", return_value="TSK-050"), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_task_registry_row",
                   side_effect=append_side_effect) as mock_append, \
             patch.object(tm, "_verify_created_task_row", return_value=verify_result) as mock_verify:
            result = tm.create_task("BIZ-001", "Title")
        return result, mock_append, mock_verify

    def test_append_raises_verify_finds_nothing_is_ambiguous_unknown(self):
        """Phase 18A.9-A1-F1: RAISES×ZERO is UNKNOWN, never confirmed failure."""
        result, mock_append, mock_verify = self._run(
            append_side_effect=RuntimeError("SENTINEL-BOOM"),
            verify_result=_verified(),
        )
        mock_append.assert_called_once()
        mock_verify.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_WRITE_OUTCOME_UNKNOWN")
        self.assertEqual(result["task_id"], "TSK-050")
        self.assertIsNone(result["error"])
        self.assertNotIn("SENTINEL-BOOM", str(result))
        self.assertNotEqual(result["code"], "TASK_STORAGE_ERROR")

    def test_append_raises_but_verify_finds_row_confirmed_success(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=RuntimeError("SENTINEL-BOOM"),
            verify_result=_verified({"task_id": "TSK-050"}),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_CREATED")
        self.assertEqual(result["task_id"], "TSK-050")

    def test_append_succeeds_but_verify_finds_nothing_ambiguous(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=None,
            verify_result=_verified(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_WRITE_OUTCOME_UNKNOWN")
        self.assertIsNone(result["error"])
        self.assertEqual(result["task_id"], "TSK-050")

    def test_append_succeeds_verify_finds_one_confirmed_success(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=None,
            verify_result=_verified({"task_id": "TSK-050"}),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_CREATED")

    def test_append_succeeds_verify_finds_duplicate(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=None,
            verify_result=_verified({"task_id": "TSK-050"}, {"task_id": "TSK-051"}),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_DUPLICATE_DETECTED")
        self.assertEqual(set(result["conflicting_task_ids"]), {"TSK-050", "TSK-051"})

    def test_verification_read_failure_is_ambiguous_not_zero(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=None,
            verify_result={"ok": False, "matches": []},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_WRITE_OUTCOME_UNKNOWN")

    def test_verification_read_failure_after_append_exception_is_still_ambiguous(self):
        result, mock_append, mock_verify = self._run(
            append_side_effect=RuntimeError("SENTINEL-BOOM"),
            verify_result={"ok": False, "matches": []},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_WRITE_OUTCOME_UNKNOWN")
        self.assertNotIn("SENTINEL-BOOM", str(result))

    def test_no_retry_on_any_path(self):
        # Every path above calls append exactly once — create_task()
        # never retries a write itself.
        for append_side_effect, verify_result in [
            (RuntimeError("x"), _verified()),
            (None, _verified()),
            (None, _verified({"task_id": "TSK-050"})),
            (None, _verified({"task_id": "TSK-050"}, {"task_id": "TSK-051"})),
        ]:
            with self.subTest(append_side_effect=append_side_effect, verify_result=verify_result):
                _, mock_append, _ = self._run(append_side_effect, verify_result)
                self.assertEqual(mock_append.call_count, 1)


class TestFindTasksByIdempotencyKeyContract(unittest.TestCase):

    def test_success_returns_typed_ok_contract(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-001", "IDEMP-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "")
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["matches"]), 1)

    def test_no_match_returns_ok_empty(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-001", "NO-SUCH-KEY")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])

    def test_read_exception_never_returns_ok_true_or_empty_list(self):
        # Phase 18A.9-A1: a read failure must be distinguishable from
        # zero matches -- ok must be False, never a bare [].
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.side_effect = RuntimeError("SENTINEL-BOOM")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-001", "IDEMP-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "IDEMPOTENCY_CHECK_UNAVAILABLE")
        self.assertEqual(result["matches"], [])
        self.assertIsInstance(result, dict)
        self.assertNotIsInstance(result, list)
        self.assertNotIn("SENTINEL-BOOM", str(result))

    def test_blank_business_id_short_circuits_ok_empty(self):
        tm = _fresh_tm()
        result = tm.find_tasks_by_idempotency_key("", "IDEMP-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])

    def test_blank_key_short_circuits_ok_empty(self):
        tm = _fresh_tm()
        result = tm.find_tasks_by_idempotency_key("BIZ-001", "")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])

    def test_whitespace_only_key_short_circuits_ok_empty(self):
        tm = _fresh_tm()
        result = tm.find_tasks_by_idempotency_key("BIZ-001", "   ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])

    def test_leading_trailing_whitespace_key_matches_stored_stripped_value(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-001", "  IDEMP-1  ")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["matches"]), 1)

    def test_case_difference_does_not_match(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-001", "idemp-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])

    def test_different_business_same_key_does_not_match(self):
        tm = _fresh_tm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TASK_HEADERS, TASK_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = tm.find_tasks_by_idempotency_key("BIZ-999", "IDEMP-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"], [])


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


# ─────────────────────────────────────────────────────────────
# Phase 18A.9-A1 §12: deterministic two-worker concurrency
# simulations, mocked storage only. This phase implements
# fail-closed storage hardening (never guess an ID, never treat a
# read failure as "zero matches", never silently overwrite a row,
# distinguish an ambiguous write from a confirmed one) -- it does
# NOT implement a process-local lock (deferred per §9: the lock's
# lifecycle could not be bounded cleanly without a new abstraction,
# so this phase prioritizes the fail-closed storage changes) and
# does NOT claim any protection across processes/replicas/rolling
# deploy overlap (§17). These tests document the residual races that
# a future phase's lock/reservation design must still close.
# ─────────────────────────────────────────────────────────────

class TestConcurrencyRaceSimulations(unittest.TestCase):

    def test_same_business_same_key_concurrent_idempotency_reads_still_duplicate(self):
        from business_core.business_builder import create_business_task
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key",
                   return_value={"ok": True, "code": "", "matches": [], "error": None}), \
             patch("business_core.task_manager.create_task") as mock_create:
            mock_create.side_effect = [
                {"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None},
                {"ok": True, "task_id": "TSK-002", "code": "TASK_CREATED", "error": None},
            ]
            result_a = create_business_task("BIZ-001", "Title", idempotency_key="SAME-KEY")
            result_b = create_business_task("BIZ-001", "Title", idempotency_key="SAME-KEY")
        # No process-local lock exists in this phase -- both workers'
        # idempotency reads see "0 matches" (mocked to represent two
        # reads that raced ahead of either write), so both succeed
        # with distinct Task IDs under the same (Business, Key).
        self.assertTrue(result_a["ok"])
        self.assertTrue(result_b["ok"])
        self.assertEqual(result_a["code"], "TASK_CREATED")
        self.assertEqual(result_b["code"], "TASK_CREATED")
        self.assertNotEqual(result_a["task_id"], result_b["task_id"])

    def test_different_business_same_key_no_interaction(self):
        from business_core.business_builder import create_business_task
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key",
                   return_value={"ok": True, "code": "", "matches": [], "error": None}) as mock_lookup, \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}):
            result_a = create_business_task("BIZ-001", "Title", idempotency_key="SAME-KEY")
            result_b = create_business_task("BIZ-002", "Title", idempotency_key="SAME-KEY")
        self.assertTrue(result_a["ok"])
        self.assertTrue(result_b["ok"])
        self.assertEqual(mock_lookup.call_args_list[0].args, ("BIZ-001", "SAME-KEY"))
        self.assertEqual(mock_lookup.call_args_list[1].args, ("BIZ-002", "SAME-KEY"))

    def test_same_business_different_keys_no_interaction(self):
        from business_core.business_builder import create_business_task
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key",
                   return_value={"ok": True, "code": "", "matches": [], "error": None}), \
             patch("business_core.task_manager.create_task") as mock_create:
            mock_create.side_effect = [
                {"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None},
                {"ok": True, "task_id": "TSK-002", "code": "TASK_CREATED", "error": None},
            ]
            result_a = create_business_task("BIZ-001", "Title", idempotency_key="KEY-A")
            result_b = create_business_task("BIZ-001", "Title", idempotency_key="KEY-B")
        self.assertTrue(result_a["ok"])
        self.assertTrue(result_b["ok"])
        self.assertNotEqual(result_a["task_id"], result_b["task_id"])

    def test_same_starting_id_snapshot_produces_colliding_ids(self):
        # Both workers read the exact same pre-write registry state and
        # independently compute the identical next Task ID -- proven
        # directly against the real allocation function, no lock.
        from business_core.sheets import generate_next_task_id
        snapshot_sheet = MagicMock()
        snapshot_sheet.get_all_values.return_value = [TASK_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=snapshot_sheet):
            id_a = generate_next_task_id()
            id_b = generate_next_task_id()
        self.assertEqual(id_a, id_b)
        self.assertEqual(id_a, "TSK-001")

    def test_same_append_row_snapshot_both_appends_land_independently(self):
        # append_task_registry_row() uses the real append API -- it
        # eliminates client-computed-row overwrite (Phase 18A.9-A0
        # audit §6), but it does NOT itself reject a duplicate Task ID
        # value; two concurrent appends with the same generated ID
        # both land as two separate rows.
        from business_core.sheets import append_task_registry_row
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            append_task_registry_row(["TSK-001", "BIZ-001"])
            append_task_registry_row(["TSK-001", "BIZ-001"])
        self.assertEqual(sheet.append_row.call_count, 2)
        sheet.update.assert_not_called()

    def test_cross_process_replica_protection_not_claimed(self):
        # Phase 18A.9-A1 explicitly does not implement or claim any
        # cross-process/cross-replica protection (§9/§17) -- there is
        # no lock object at all in task_manager, so nothing could span
        # two independent process imports of the module.
        import importlib
        import business_core.task_manager as tm1
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        tm2 = importlib.import_module("business_core.task_manager")
        self.assertIsNot(tm1, tm2)
        self.assertFalse(any("LOCK" in name.upper() for name in dir(tm1) if not name.startswith("__")))
        self.assertFalse(any("LOCK" in name.upper() for name in dir(tm2) if not name.startswith("__")))


if __name__ == "__main__":
    unittest.main()
