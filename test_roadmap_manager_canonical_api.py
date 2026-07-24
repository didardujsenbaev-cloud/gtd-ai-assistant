"""
Phase 28B: behavioral tests for the new additive canonical Sheets-facing
Roadmap/Roadmap Stage API added to business_core.roadmap_manager:

  find_roadmap_by_id, list_roadmaps, find_active_roadmap_for_object,
  create_roadmap_record, ensure_roadmap_stages

Strictly against a mocked sheets layer — no live network calls, no
production data touched. No existing caller is exercised here; this
file is additive-only, matching the phase's own scope.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

ROADMAPS_HEADERS = [
    "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
    "Client Name", "GTD Project ID", "Responsible", "Status",
    "Created", "Expected", "Progress %",
    "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
    "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
    "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
    "Stage 10 Status", "Notes", "Last Updated",
    "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
]

STAGES_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
    "Start Date", "Priority", "Blocking Reason",
]


def _fresh_rm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.roadmap_manager as rm
    return rm


def _row_from_headers(headers: list[str], values: dict) -> list[str]:
    row = [""] * len(headers)
    for h, v in values.items():
        if h in headers:
            row[headers.index(h)] = v
    return row


def _make_roadmaps_sheet(rows: list[dict]) -> MagicMock:
    """rows: list of {header: value} dicts, one per data row."""
    sheet = MagicMock()
    all_values = [ROADMAPS_HEADERS] + [_row_from_headers(ROADMAPS_HEADERS, r) for r in rows]
    sheet.get_all_values.return_value = all_values
    sheet.row_values.side_effect = lambda r: all_values[r - 1] if 0 <= r - 1 < len(all_values) else []

    def _find(value, in_column=1):
        for i, row in enumerate(all_values[1:], start=2):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = i
                return cell
        return None

    sheet.find.side_effect = _find
    return sheet


def _make_stages_sheet(rows: list[dict]) -> MagicMock:
    sheet = MagicMock()
    all_values = [STAGES_HEADERS] + [_row_from_headers(STAGES_HEADERS, r) for r in rows]
    sheet.get_all_values.return_value = all_values
    sheet.row_values.side_effect = lambda r: all_values[r - 1] if 0 <= r - 1 < len(all_values) else []
    return sheet


# ─────────────────────────────────────────────────────────────
# find_roadmap_by_id
# ─────────────────────────────────────────────────────────────

class TestFindRoadmapById(unittest.TestCase):
    def test_returns_none_for_blank_id(self):
        rm = _fresh_rm()
        self.assertIsNone(rm.find_roadmap_by_id(""))

    def test_returns_none_when_not_found(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(rm.find_roadmap_by_id("RM-999"))

    def test_finds_existing_roadmap_header_mapped(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([{
            "Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Service ID": "SVC-001",
            "Client ID": "PRS-001", "Client Name": "Test Roadmap", "Status": "active",
            "Created": "2026-01-01", "Object ID": "OBJ-001", "Parent Roadmap ID": "",
            "Case Type": "general", "Template ID": "RMT-001", "Progress %": "50",
            "Notes": "hello",
        }])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            found = rm.find_roadmap_by_id("RM-001")
        self.assertIsNotNone(found)
        self.assertEqual(found["roadmap_id"], "RM-001")
        self.assertEqual(found["business_id"], "BIZ-001")
        self.assertEqual(found["object_id"], "OBJ-001")
        self.assertEqual(found["template_id"], "RMT-001")
        self.assertEqual(found["progress"], "50")
        self.assertEqual(found["notes"], "hello")

    def test_shuffled_headers_give_same_values_by_name(self):
        """Header-mapped, not positional — same assertion style already
        established for create_roadmap_stages_from_template in
        test_business_object_roadmaps.py."""
        rm = _fresh_rm()
        shuffled = list(reversed(ROADMAPS_HEADERS))
        sheet = MagicMock()
        row = _row_from_headers(shuffled, {
            "Roadmap ID": "RM-001", "Object ID": "OBJ-777", "Status": "active",
        })
        all_values = [shuffled, row]
        sheet.get_all_values.return_value = all_values
        sheet.row_values.side_effect = lambda r: all_values[r - 1]
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            found = rm.find_roadmap_by_id("RM-001")
        self.assertEqual(found["object_id"], "OBJ-777")
        self.assertEqual(found["status"], "active")


# ─────────────────────────────────────────────────────────────
# list_roadmaps
# ─────────────────────────────────────────────────────────────

class TestListRoadmaps(unittest.TestCase):
    def _seed(self):
        return [
            {"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Object ID": "OBJ-001",
             "Service ID": "SVC-001", "Client ID": "PRS-001", "Status": "active"},
            {"Roadmap ID": "RM-002", "Business ID": "BIZ-001", "Object ID": "OBJ-002",
             "Service ID": "SVC-002", "Client ID": "PRS-002", "Status": "completed"},
            {"Roadmap ID": "RM-003", "Business ID": "BIZ-002", "Object ID": "OBJ-001",
             "Service ID": "SVC-001", "Client ID": "PRS-003", "Status": "active"},
        ]

    def test_no_filters_returns_all(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(self._seed())
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = rm.list_roadmaps()
        self.assertEqual(len(results), 3)

    def test_filter_by_object_id(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(self._seed())
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = rm.list_roadmaps(object_id="OBJ-001")
        self.assertEqual({r["roadmap_id"] for r in results}, {"RM-001", "RM-003"})

    def test_filter_by_object_and_service_and_status_combined(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(self._seed())
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = rm.list_roadmaps(object_id="OBJ-001", service_id="SVC-001", status="active")
        self.assertEqual({r["roadmap_id"] for r in results}, {"RM-001", "RM-003"})

    def test_filter_by_business_id(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(self._seed())
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = rm.list_roadmaps(business_id="BIZ-002")
        self.assertEqual({r["roadmap_id"] for r in results}, {"RM-003"})

    def test_empty_sheet_returns_empty_list(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(rm.list_roadmaps(), [])


# ─────────────────────────────────────────────────────────────
# find_active_roadmap_for_object
# ─────────────────────────────────────────────────────────────

class TestFindActiveRoadmapForObject(unittest.TestCase):
    def test_returns_none_without_both_ids(self):
        rm = _fresh_rm()
        self.assertIsNone(rm.find_active_roadmap_for_object("", "SVC-001"))
        self.assertIsNone(rm.find_active_roadmap_for_object("OBJ-001", ""))

    def test_finds_active_match(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([
            {"Roadmap ID": "RM-001", "Object ID": "OBJ-001", "Service ID": "SVC-001", "Status": "active"},
        ])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            found = rm.find_active_roadmap_for_object("OBJ-001", "SVC-001")
        self.assertIsNotNone(found)
        self.assertEqual(found["roadmap_id"], "RM-001")

    def test_ignores_non_active_status(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([
            {"Roadmap ID": "RM-001", "Object ID": "OBJ-001", "Service ID": "SVC-001", "Status": "completed"},
        ])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            found = rm.find_active_roadmap_for_object("OBJ-001", "SVC-001")
        self.assertIsNone(found)

    def test_ignores_different_object_or_service(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([
            {"Roadmap ID": "RM-001", "Object ID": "OBJ-999", "Service ID": "SVC-001", "Status": "active"},
        ])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(rm.find_active_roadmap_for_object("OBJ-001", "SVC-001"))


# ─────────────────────────────────────────────────────────────
# create_roadmap_record
# ─────────────────────────────────────────────────────────────

class TestCreateRoadmapRecord(unittest.TestCase):
    def test_requires_business_client_object(self):
        rm = _fresh_rm()
        result = rm.create_roadmap_record(business_id="", client_id="PRS-001", object_id="OBJ-001")
        self.assertFalse(result["ok"])
        self.assertIn("business_id", result["error"])

    def test_rejects_invalid_status(self):
        rm = _fresh_rm()
        result = rm.create_roadmap_record(
            business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001", status="bogus",
        )
        self.assertFalse(result["ok"])
        self.assertIn("Status", result["error"])

    def test_accepts_every_canonical_status(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        captured = []
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"):
            for status in rm.ROADMAP_STATUSES:
                result = rm.create_roadmap_record(
                    business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001", status=status,
                )
                self.assertTrue(result["ok"], f"status {status!r} should be accepted")

    def test_header_mapped_write_standard_order(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        captured = []
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="RM-042"):
            result = rm.create_roadmap_record(
                business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001",
                service_id="SVC-001", template_id="RMT-001",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["roadmap_id"], "RM-042")
        idx = {h: i for i, h in enumerate(ROADMAPS_HEADERS)}
        row = captured[0]
        self.assertEqual(row[idx["Roadmap ID"]], "RM-042")
        self.assertEqual(row[idx["Business ID"]], "BIZ-001")
        self.assertEqual(row[idx["Object ID"]], "OBJ-001")
        self.assertEqual(row[idx["Service ID"]], "SVC-001")
        self.assertEqual(row[idx["Template ID"]], "RMT-001")
        self.assertEqual(row[idx["Status"]], "active")
        self.assertEqual(row[idx["Progress %"]], "0")

    def test_shuffled_header_order_gives_same_values_by_name(self):
        rm = _fresh_rm()
        shuffled = list(reversed(ROADMAPS_HEADERS))
        sheet = MagicMock()
        sheet.row_values.side_effect = lambda r: shuffled if r == 1 else []
        captured = []
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"):
            result = rm.create_roadmap_record(
                business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-777",
            )
        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(shuffled)}
        row = captured[0]
        self.assertEqual(row[idx["Object ID"]], "OBJ-777")
        self.assertEqual(len(row), len(shuffled))

    def test_does_not_create_any_stages(self):
        """Phase 27B: low-level persistence only, never orchestrates
        Stage creation itself."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            rm.create_roadmap_record(business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001")
        mock_batch.assert_not_called()

    def test_returns_created_roadmap_dict(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"):
            result = rm.create_roadmap_record(
                business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001",
            )
        self.assertEqual(result["roadmap"]["roadmap_id"], "RM-001")
        self.assertEqual(result["roadmap"]["object_id"], "OBJ-001")
        self.assertEqual(result["roadmap"]["status"], "active")


# ─────────────────────────────────────────────────────────────
# ensure_roadmap_stages — idempotency
# ─────────────────────────────────────────────────────────────

def _tmpl_row(order: int, name: str = "Stage") -> dict:
    return {
        "stage_id": f"TSTG-{order:03d}", "template_id": "RMT-001",
        "order": str(order), "stage_name": f"{name} {order}",
        "description": "", "required_docs": "", "responsible": "",
        "estimated_days": "", "notes": "",
    }


class TestEnsureRoadmapStages(unittest.TestCase):
    def test_requires_roadmap_id(self):
        rm = _fresh_rm()
        result = rm.ensure_roadmap_stages("", [_tmpl_row(1)])
        self.assertFalse(result["ok"])

    def test_empty_template_rows_is_a_noop(self):
        rm = _fresh_rm()
        sheet = _make_stages_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.ensure_roadmap_stages("RM-001", [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["created_count"], 0)

    def test_first_call_creates_all_stages(self):
        rm = _fresh_rm()
        sheet = _make_stages_sheet([])
        rows = [_tmpl_row(1), _tmpl_row(2), _tmpl_row(3)]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_ids",
                   return_value=["STAGE-001", "STAGE-002", "STAGE-003"]), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = rm.ensure_roadmap_stages("RM-001", rows)

        self.assertTrue(result["ok"])
        self.assertEqual(result["created_count"], 3)
        self.assertEqual(result["existing_count"], 0)
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(result["created_stage_ids"], ["STAGE-001", "STAGE-002", "STAGE-003"])
        mock_batch.assert_called_once()
        written_rows = mock_batch.call_args.args[1]
        self.assertEqual(len(written_rows), 3)

    def test_second_call_creates_no_duplicates(self):
        """Idempotency requirement 2: retry after stages already exist
        creates nothing new."""
        rm = _fresh_rm()
        existing_rows = [
            {"Stage ID": "STAGE-001", "Roadmap ID": "RM-001", "Order": "1", "Name": "Stage 1", "Status": "pending"},
            {"Stage ID": "STAGE-002", "Roadmap ID": "RM-001", "Order": "2", "Name": "Stage 2", "Status": "pending"},
            {"Stage ID": "STAGE-003", "Roadmap ID": "RM-001", "Order": "3", "Name": "Stage 3", "Status": "pending"},
        ]
        sheet = _make_stages_sheet(existing_rows)
        rows = [_tmpl_row(1), _tmpl_row(2), _tmpl_row(3)]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = rm.ensure_roadmap_stages("RM-001", rows)

        self.assertTrue(result["ok"])
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["existing_count"], 3)
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(set(result["existing_stage_ids"]), {"STAGE-001", "STAGE-002", "STAGE-003"})
        mock_batch.assert_not_called()

    def test_partial_existing_creates_only_missing_orders(self):
        """Idempotency requirement 3: only missing Orders are created."""
        rm = _fresh_rm()
        existing_rows = [
            {"Stage ID": "STAGE-001", "Roadmap ID": "RM-001", "Order": "1", "Name": "Stage 1", "Status": "pending"},
        ]
        sheet = _make_stages_sheet(existing_rows)
        rows = [_tmpl_row(1), _tmpl_row(2), _tmpl_row(3)]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-002", "STAGE-003"]), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = rm.ensure_roadmap_stages("RM-001", rows)

        self.assertTrue(result["ok"])
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(result["existing_count"], 1)
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(set(result["created_stage_ids"]), {"STAGE-002", "STAGE-003"})
        self.assertEqual(result["existing_stage_ids"], ["STAGE-001"])
        written_rows = mock_batch.call_args.args[1]
        self.assertEqual(len(written_rows), 2)

    def test_no_duplicate_roadmap_id_order_pair_created(self):
        """Idempotency requirement 4: duplicate (Roadmap ID, Order) never
        appears — two template rows sharing the same Order collapse to
        at most one created stage for that Order."""
        rm = _fresh_rm()
        sheet = _make_stages_sheet([])
        rows = [_tmpl_row(1), _tmpl_row(1)]  # duplicate Order in input
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = rm.ensure_roadmap_stages("RM-001", rows)

        self.assertEqual(result["created_count"], 1)
        written_rows = mock_batch.call_args.args[1]
        self.assertEqual(len(written_rows), 1)

    def test_existing_stage_ids_unchanged(self):
        """Idempotency requirement 5: existing Stage IDs are never
        touched or regenerated."""
        rm = _fresh_rm()
        existing_rows = [
            {"Stage ID": "STAGE-777", "Roadmap ID": "RM-001", "Order": "1", "Name": "Stage 1", "Status": "pending"},
        ]
        sheet = _make_stages_sheet(existing_rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = rm.ensure_roadmap_stages("RM-001", [_tmpl_row(1)])

        self.assertEqual(result["existing_stage_ids"], ["STAGE-777"])
        mock_batch.assert_not_called()

    def test_new_stages_use_pending_not_not_started(self):
        """Idempotency requirement 6: 'pending' is written, never the
        legacy 'not_started' value."""
        rm = _fresh_rm()
        sheet = _make_stages_sheet([])
        captured = {}
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: captured.setdefault("rows", rows)):
            rm.ensure_roadmap_stages("RM-001", [_tmpl_row(1)])

        idx = {h: i for i, h in enumerate(STAGES_HEADERS)}
        row = captured["rows"][0]
        self.assertEqual(row[idx["Status"]], "pending")
        self.assertNotEqual(row[idx["Status"]], "not_started")

    def test_status_is_validated_against_canonical_set(self):
        rm = _fresh_rm()
        self.assertIn("pending", rm.STAGE_STATUS_CANONICAL)

    def test_ordering_taken_from_template_stage_order(self):
        rm = _fresh_rm()
        sheet = _make_stages_sheet([])
        rows = [_tmpl_row(3), _tmpl_row(1), _tmpl_row(2)]  # out of order input
        captured = {}
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_ids",
                   return_value=["STAGE-001", "STAGE-002", "STAGE-003"]), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: captured.setdefault("rows", rows)):
            rm.ensure_roadmap_stages("RM-001", rows)

        idx = {h: i for i, h in enumerate(STAGES_HEADERS)}
        orders = [row[idx["Order"]] for row in captured["rows"]]
        self.assertEqual(orders, ["3", "1", "2"])  # preserves each row's own Order value

    def test_does_not_call_stage_entity_relations_or_knowledge_manager(self):
        """Phase 27B orchestration boundary: this function must never
        import/call Relations or Knowledge itself. Checked via AST
        (imports only), not a docstring substring match — the
        function's own docstring legitimately mentions both module
        names in prose to document that it does NOT call them."""
        import ast
        import inspect
        rm = _fresh_rm()
        src = inspect.getsource(rm.ensure_roadmap_stages)
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[-1])
        self.assertNotIn("stage_entity_relations", imported)
        self.assertNotIn("knowledge_manager", imported)


# ─────────────────────────────────────────────────────────────
# update_stage_fields — Phase 28D canonical replacement for
# telegram_handlers._stage_edit_execute's former direct Sheets access
# ─────────────────────────────────────────────────────────────

class TestUpdateStageFields(unittest.TestCase):
    def test_requires_stage_id(self):
        rm = _fresh_rm()
        result = rm.update_stage_fields("", {"Responsible": "Иван"})
        self.assertFalse(result["ok"])

    def test_stage_not_found(self):
        rm = _fresh_rm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = rm.update_stage_fields("STAGE-999", {"Responsible": "Иван"})
        self.assertFalse(result["ok"])
        self.assertIn("STAGE-999", result["error"])

    def test_writes_only_allowed_columns(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.row_values.return_value = STAGES_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_fields("STAGE-001", {
                "Responsible": "Иван", "Stage ID": "HACKED", "Order": "99",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["written_fields"], ("Responsible",))
        written_cols = [c.args[1] for c in sheet.update_cell.call_args_list]
        idx = {h: i + 1 for i, h in enumerate(STAGES_HEADERS)}
        self.assertEqual(written_cols, [idx["Responsible"]])

    def test_writes_multiple_allowed_columns(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.row_values.return_value = STAGES_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(3, {})), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_fields("STAGE-001", {
                "Blocking Reason": "нет доступа", "Status": "blocked",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["written_fields"]), {"Blocking Reason", "Status"})
        self.assertEqual(sheet.update_cell.call_count, 2)
        for c in sheet.update_cell.call_args_list:
            self.assertEqual(c.args[0], 3)

    def test_rereads_row_before_writing(self):
        """Read-before-Write (ENGINEERING_STANDARDS.md) — staleness guard."""
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.row_values.return_value = STAGES_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {})) as mock_find, \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_fields("STAGE-001", {"Priority": "high"})
        mock_find.assert_called_once_with("roadmap_stages", "STAGE-001")


if __name__ == "__main__":
    unittest.main(verbosity=2)
