"""
Tests for Phase 38C — Checklist Domain Foundation: business_core/
checklist_manager.py (ADR-021). Covers Checklist Instance/Instance Item
ID generation, low-level creation, admin-field update rules, status
persistence, and read-only idempotency-tuple lookups. No cross-entity
eligibility, no Template parsing — that's business_builder.py's job,
covered separately in test_business_checklist_foundation.py.

No live Sheets writes — mocks only. Registered in conftest.py's hard
socket-block set before this file's logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

INSTANCE_HEADERS = [
    "Checklist Instance ID", "Business ID", "Checklist Template ID",
    "Checklist Title Snapshot", "Service ID", "Object ID",
    "Roadmap ID", "Stage ID", "Status",
    "Total Items", "Required Items", "Completed Items", "Required Remaining",
    "Created At", "Created By", "Started At", "Completed At", "Cancelled At",
    "Updated At", "Notes",
]

ITEM_HEADERS = [
    "Checklist Instance Item ID", "Checklist Instance ID", "Checklist Template ID",
    "Source Item Key", "Item Order", "Item Title Snapshot", "Item Description Snapshot",
    "Required", "Status", "Blocked Reason", "Skip Reason",
    "Task ID", "Document ID", "SOP ID",
    "Completed At", "Completed By", "Created At", "Updated At", "Notes",
]

INSTANCE_ROW = [
    "CLIN-001", "BIZ-001", "CHK-001", "Тест чек-лист", "", "",
    "RM-001", "STAGE-001", "draft",
    "3", "2", "0", "2",
    "2026-01-01 00:00:00 UTC", "dida", "", "", "",
    "2026-01-01 00:00:00 UTC", "",
]

ITEM_ROW = [
    "CLII-001", "CLIN-001", "CHK-001",
    "1", "1", "Удостоверение личности", "",
    "true", "pending", "", "",
    "", "", "",
    "", "", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC", "",
]


def _fresh_cm():
    import importlib
    import business_core.checklist_manager as cm
    return importlib.reload(cm)


def _make_sheet(headers, rows, row_num=2):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


class TestSchema(unittest.TestCase):
    def test_instance_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["checklist_instances"], INSTANCE_HEADERS)

    def test_item_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["checklist_instance_items"], ITEM_HEADERS)

    def test_id_prefixes(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["checklist_instances"], "CLIN")
        self.assertEqual(_ID_PREFIXES["checklist_instance_items"], "CLII")

    def test_checklist_registry_schema_unchanged(self):
        """Foundation must never touch the existing Template schema."""
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(
            BUSINESS_HEADERS["checklist_registry"],
            [
                "Checklist ID", "Biz ID", "Service ID", "Template ID", "Template Stage ID",
                "Title", "Items", "Required Items", "Optional Items", "Completion Criteria",
                "Owner Role", "Drive File ID", "Google Drive", "Version", "Status", "Notes",
                "Created At", "Last Updated",
            ],
        )


class TestIdGeneration(unittest.TestCase):
    def test_generate_next_instance_id_empty_sheet(self):
        cm = _fresh_cm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [INSTANCE_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(cm.generate_next_instance_id(), "CLIN-001")

    def test_generate_next_instance_id_increments(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(cm.generate_next_instance_id(), "CLIN-002")

    def test_malformed_existing_ids_ignored(self):
        cm = _fresh_cm()
        bad_row = list(INSTANCE_ROW)
        bad_row[0] = "NOT-A-VALID-ID"
        sheet = _make_sheet(INSTANCE_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(cm.generate_next_instance_id(), "CLIN-001")

    def test_generate_next_item_ids_batch(self):
        cm = _fresh_cm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [ITEM_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            ids = cm.generate_next_item_ids(3)
        self.assertEqual(ids, ["CLII-001", "CLII-002", "CLII-003"])

    def test_generate_next_item_ids_zero_count(self):
        cm = _fresh_cm()
        self.assertEqual(cm.generate_next_item_ids(0), [])


class TestFindById(unittest.TestCase):
    def test_find_instance_found(self):
        cm = _fresh_cm()
        row_dict = dict(zip(INSTANCE_HEADERS, INSTANCE_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            instance = cm.find_checklist_instance_by_id("CLIN-001")
        self.assertIsNotNone(instance)
        self.assertEqual(instance["Checklist Instance ID"], "CLIN-001")
        self.assertEqual(instance["Status"], "draft")

    def test_find_instance_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(cm.find_checklist_instance_by_id("CLIN-999"))

    def test_find_instance_blank_id(self):
        cm = _fresh_cm()
        self.assertIsNone(cm.find_checklist_instance_by_id(""))

    def test_find_item_found(self):
        cm = _fresh_cm()
        row_dict = dict(zip(ITEM_HEADERS, ITEM_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            item = cm.find_checklist_instance_item_by_id("CLII-001")
        self.assertIsNotNone(item)
        self.assertEqual(item["Checklist Instance Item ID"], "CLII-001")

    def test_find_item_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(cm.find_checklist_instance_item_by_id("CLII-999"))


class TestListAndFilter(unittest.TestCase):
    def test_list_instances_filters_by_business_and_status(self):
        cm = _fresh_cm()
        other = list(INSTANCE_ROW)
        other[0], other[1], other[8] = "CLIN-002", "BIZ-002", "completed"
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW, other])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = cm.list_checklist_instances(business_id="BIZ-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["Checklist Instance ID"], "CLIN-001")

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = cm.list_checklist_instances(status="completed")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["Checklist Instance ID"], "CLIN-002")

    def test_list_items_filters_by_instance_and_status(self):
        cm = _fresh_cm()
        other = list(ITEM_ROW)
        other[0], other[1], other[8] = "CLII-002", "CLIN-002", "done"
        sheet = _make_sheet(ITEM_HEADERS, [ITEM_ROW, other])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = cm.list_checklist_instance_items(instance_id="CLIN-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["Checklist Instance Item ID"], "CLII-001")


class TestIdempotencyLookup(unittest.TestCase):
    def test_zero_matches(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = cm.find_instances_by_idempotency_key("BIZ-001", "CHK-001")
        self.assertEqual(matches, [])

    def test_one_match(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = cm.find_instances_by_idempotency_key("BIZ-001", "CHK-001", "RM-001", "STAGE-001")
        self.assertEqual(len(matches), 1)

    def test_multiple_matches(self):
        cm = _fresh_cm()
        dup = list(INSTANCE_ROW)
        dup[0] = "CLIN-002"
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW, dup])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = cm.find_instances_by_idempotency_key("BIZ-001", "CHK-001", "RM-001", "STAGE-001")
        self.assertEqual(len(matches), 2)

    def test_no_match_on_different_stage(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = cm.find_instances_by_idempotency_key("BIZ-001", "CHK-001", "RM-001", "STAGE-999")
        self.assertEqual(matches, [])

    def test_missing_business_or_template_returns_empty(self):
        cm = _fresh_cm()
        self.assertEqual(cm.find_instances_by_idempotency_key("", "CHK-001"), [])
        self.assertEqual(cm.find_instances_by_idempotency_key("BIZ-001", ""), [])


class TestCreateChecklistInstance(unittest.TestCase):
    def test_missing_business_id(self):
        cm = _fresh_cm()
        result = cm.create_checklist_instance("", "CHK-001", "Title")
        self.assertFalse(result["ok"])

    def test_missing_template_id(self):
        cm = _fresh_cm()
        result = cm.create_checklist_instance("BIZ-001", "", "Title")
        self.assertFalse(result["ok"])

    def test_invalid_status(self):
        cm = _fresh_cm()
        result = cm.create_checklist_instance("BIZ-001", "CHK-001", "Title", status="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_STATUS")

    def test_successful_creation(self):
        cm = _fresh_cm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [INSTANCE_HEADERS]
        sheet.row_values.return_value = INSTANCE_HEADERS
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = cm.create_checklist_instance("BIZ-001", "CHK-001", "Title", roadmap_id="RM-001", stage_id="STAGE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["checklist_instance_id"], "CLIN-001")
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_CREATED")
        mock_append.assert_called_once()
        row = mock_append.call_args[0][1]
        idx = {h: i for i, h in enumerate(INSTANCE_HEADERS)}
        self.assertEqual(row[idx["Checklist Instance ID"]], "CLIN-001")
        self.assertEqual(row[idx["Status"]], "draft")


class TestCreateChecklistInstanceItems(unittest.TestCase):
    def test_missing_instance_id(self):
        cm = _fresh_cm()
        result = cm.create_checklist_instance_items("", "CHK-001", [{"item_title_snapshot": "A", "required": True}])
        self.assertFalse(result["ok"])

    def test_empty_items(self):
        cm = _fresh_cm()
        result = cm.create_checklist_instance_items("CLIN-001", "CHK-001", [])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_ITEMS_EMPTY")

    def test_batch_creation(self):
        cm = _fresh_cm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [ITEM_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            items = [
                {"source_item_key": 1, "item_order": 1, "item_title_snapshot": "A", "item_description_snapshot": "", "required": True},
                {"source_item_key": 2, "item_order": 2, "item_title_snapshot": "B", "item_description_snapshot": "", "required": False},
            ]
            result = cm.create_checklist_instance_items("CLIN-001", "CHK-001", items)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item_ids"], ["CLII-001", "CLII-002"])
        mock_batch.assert_called_once()
        rows = mock_batch.call_args[0][1]
        self.assertEqual(len(rows), 2)
        idx = {h: i for i, h in enumerate(ITEM_HEADERS)}
        self.assertEqual(rows[0][idx["Required"]], "true")
        self.assertEqual(rows[1][idx["Required"]], "false")
        self.assertEqual(rows[0][idx["Status"]], "pending")


class TestUpdateChecklistInstanceAdminFields(unittest.TestCase):
    def test_notes_update_succeeds(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_admin_fields("CLIN-001", {"Notes": "hello"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "CHECKLIST_ADMIN_FIELDS_UPDATED")

    def test_unchanged_value_is_noop(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_admin_fields("CLIN-001", {"Notes": ""})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "CHECKLIST_ADMIN_FIELDS_UNCHANGED")

    def test_identity_field_conflict(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_admin_fields("CLIN-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_IMMUTABLE_FIELD_CONFLICT")

    def test_status_blocked(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_admin_fields("CLIN-001", {"Status": "completed"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_ADMIN_FIELD")

    def test_unknown_field(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_admin_fields("CLIN-001", {"Bogus": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_ADMIN_FIELD")

    def test_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = cm.update_checklist_instance_admin_fields("CLIN-999", {"Notes": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_NOT_FOUND")


class TestUpdateChecklistInstanceStatus(unittest.TestCase):
    def test_status_change_with_started_at(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_status("CLIN-001", "in_progress", started_at="2026-01-02 00:00:00 UTC")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_unchanged_status(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_status("CLIN-001", "draft")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_invalid_status(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_status("CLIN-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_STATUS")

    def test_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = cm.update_checklist_instance_status("CLIN-999", "completed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_NOT_FOUND")


class TestUpdateChecklistInstanceProgress(unittest.TestCase):
    def test_progress_persisted(self):
        cm = _fresh_cm()
        sheet = _make_sheet(INSTANCE_HEADERS, [INSTANCE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_progress(
                "CLIN-001", total_items=5, required_items=3, completed_items=2, required_remaining=1,
            )
        self.assertTrue(result["ok"])

    def test_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = cm.update_checklist_instance_progress(
                "CLIN-999", total_items=1, required_items=1, completed_items=0, required_remaining=1,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_NOT_FOUND")


class TestUpdateChecklistInstanceItemAdminFields(unittest.TestCase):
    def test_notes_update(self):
        cm = _fresh_cm()
        sheet = _make_sheet(ITEM_HEADERS, [ITEM_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_item_admin_fields("CLII-001", {"Notes": "x"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_identity_conflict(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_item_admin_fields("CLII-001", {"Item Title Snapshot": "X"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_IMMUTABLE_FIELD_CONFLICT")

    def test_status_blocked(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_item_admin_fields("CLII-001", {"Status": "done"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_ADMIN_FIELD")

    def test_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = cm.update_checklist_instance_item_admin_fields("CLII-999", {"Notes": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_ITEM_NOT_FOUND")


class TestUpdateChecklistInstanceItemStatus(unittest.TestCase):
    def test_status_change(self):
        cm = _fresh_cm()
        sheet = _make_sheet(ITEM_HEADERS, [ITEM_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_item_status("CLII-001", "in_progress")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_done_sets_completed_at_and_by(self):
        cm = _fresh_cm()
        sheet = _make_sheet(ITEM_HEADERS, [ITEM_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_item_status(
                "CLII-001", "done", completed_at="2026-01-05 00:00:00 UTC", completed_by="dida",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_unchanged_status(self):
        cm = _fresh_cm()
        sheet = _make_sheet(ITEM_HEADERS, [ITEM_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = cm.update_checklist_instance_item_status("CLII-001", "pending")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_invalid_status(self):
        cm = _fresh_cm()
        result = cm.update_checklist_instance_item_status("CLII-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_ITEM_STATUS")

    def test_not_found(self):
        cm = _fresh_cm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = cm.update_checklist_instance_item_status("CLII-999", "done")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_ITEM_NOT_FOUND")


class TestNoHardDelete(unittest.TestCase):
    def test_no_delete_primitive_called_anywhere(self):
        path = WORKSPACE / "business_core" / "checklist_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
