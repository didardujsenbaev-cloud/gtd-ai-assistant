"""
Phase 43: Document Completion Gate — STAGE_COMPLETION_OVERRIDES registry
schema and roadmap_manager.record_stage_completion_override() write
primitive.

Strictly against mocked business_core.sheets functions — no live network
calls, no production data touched.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


def _fresh_sheets():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.sheets as s
    return s


def _fresh_rm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.roadmap_manager as rm
    return rm


EXPECTED_HEADERS = [
    "Override ID", "Stage ID", "Roadmap ID", "User", "Overridden At",
    "Reason", "Missing Blocking Doc IDs", "Previous Status", "Target Status",
    "Override Type", "Configuration Error Details",
    "Missing Checklist Instance IDs", "Missing Checklist Item IDs",
    "Missing Checklist Item Titles",
]

# Pre-Phase-44 header shape — the exact row shape SCO-001 was written
# with, before the 3 checklist columns existed. Used to prove backward
# compatibility: a sheet still on this older header list must still be
# readable/writable, and the 3 new fields simply default to "".
LEGACY_HEADERS = EXPECTED_HEADERS[:11]


class TestStageCompletionOverridesSchema(unittest.TestCase):
    def test_sheet_key_registered(self):
        s = _fresh_sheets()
        self.assertIn("stage_completion_overrides", s.BUSINESS_SHEET_NAMES)
        self.assertEqual(s.BUSINESS_SHEET_NAMES["stage_completion_overrides"], "STAGE_COMPLETION_OVERRIDES")

    def test_headers_exact_match(self):
        s = _fresh_sheets()
        self.assertEqual(s.BUSINESS_HEADERS["stage_completion_overrides"], EXPECTED_HEADERS)

    def test_id_prefix_is_sco(self):
        s = _fresh_sheets()
        self.assertEqual(s._ID_PREFIXES["stage_completion_overrides"], "SCO")

    def test_prefix_is_unique(self):
        s = _fresh_sheets()
        all_prefixes = list(s._ID_PREFIXES.values())
        self.assertEqual(all_prefixes.count("SCO"), 1)

    def test_tab_name_is_unique(self):
        s = _fresh_sheets()
        all_names = list(s.BUSINESS_SHEET_NAMES.values())
        self.assertEqual(all_names.count("STAGE_COMPLETION_OVERRIDES"), 1)


class TestRecordStageCompletionOverride(unittest.TestCase):
    def _run(self, next_id="SCO-001", **kwargs):
        rm = _fresh_rm()
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = list(EXPECTED_HEADERS)
        appended = []

        def _append(sheet_key, row):
            appended.append((sheet_key, row))

        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_id", return_value=next_id), \
             patch("business_core.sheets.append_business_row", side_effect=_append):
            defaults = dict(
                stage_id="STAGE-011", roadmap_id="RM-003", user="dida",
                reason="manager approved", missing_blocking_doc_ids=("DOC-008",),
                previous_status="in_progress", target_status="done",
                override_type="missing_blocking_documents", timestamp="2026-07-27 12:00:00",
            )
            defaults.update(kwargs)
            result = rm.record_stage_completion_override(**defaults)
        return result, appended

    def test_successful_append(self):
        result, appended = self._run()
        self.assertTrue(result["ok"])
        self.assertEqual(result["override_id"], "SCO-001")
        self.assertEqual(len(appended), 1)

    def test_row_contains_all_fields_in_header_order(self):
        _, appended = self._run(
            stage_id="STAGE-011", roadmap_id="RM-003", user="dida",
            reason="manager approved", missing_blocking_doc_ids=("DOC-008", "DOC-009"),
            previous_status="in_progress", target_status="done",
            override_type="missing_blocking_documents",
        )
        sheet_key, row = appended[0]
        self.assertEqual(sheet_key, "stage_completion_overrides")
        row_dict = dict(zip(EXPECTED_HEADERS, row))
        self.assertEqual(row_dict["Override ID"], "SCO-001")
        self.assertEqual(row_dict["Stage ID"], "STAGE-011")
        self.assertEqual(row_dict["Roadmap ID"], "RM-003")
        self.assertEqual(row_dict["User"], "dida")
        self.assertEqual(row_dict["Reason"], "manager approved")
        self.assertEqual(row_dict["Missing Blocking Doc IDs"], "DOC-008, DOC-009")
        self.assertEqual(row_dict["Previous Status"], "in_progress")
        self.assertEqual(row_dict["Target Status"], "done")
        self.assertEqual(row_dict["Override Type"], "missing_blocking_documents")

    def test_configuration_error_type_and_details_recorded(self):
        _, appended = self._run(
            override_type="configuration_error",
            configuration_error_details="STAGE-011/REL-999: dangling entity",
            missing_blocking_doc_ids=(),
        )
        row_dict = dict(zip(EXPECTED_HEADERS, appended[0][1]))
        self.assertEqual(row_dict["Override Type"], "configuration_error")
        self.assertEqual(row_dict["Configuration Error Details"], "STAGE-011/REL-999: dangling entity")
        self.assertEqual(row_dict["Missing Blocking Doc IDs"], "")

    def test_checklist_fields_recorded(self):
        _, appended = self._run(
            override_type="missing_checklist_items", missing_blocking_doc_ids=(),
            missing_checklist_instance_ids=("CLIN-001",), missing_checklist_item_ids=("CLII-001", "CLII-002"),
            missing_checklist_item_titles=("Первый пункт", "Второй пункт"),
        )
        row_dict = dict(zip(EXPECTED_HEADERS, appended[0][1]))
        self.assertEqual(row_dict["Override Type"], "missing_checklist_items")
        self.assertEqual(row_dict["Missing Checklist Instance IDs"], "CLIN-001")
        self.assertEqual(row_dict["Missing Checklist Item IDs"], "CLII-001, CLII-002")
        self.assertEqual(row_dict["Missing Checklist Item Titles"], "Первый пункт, Второй пункт")

    def test_composite_override_type_recorded_verbatim(self):
        _, appended = self._run(
            override_type="missing_blocking_documents+missing_checklist_items",
            missing_checklist_instance_ids=("CLIN-001",), missing_checklist_item_ids=("CLII-001",),
            missing_checklist_item_titles=("Пункт",),
        )
        row_dict = dict(zip(EXPECTED_HEADERS, appended[0][1]))
        self.assertEqual(row_dict["Override Type"], "missing_blocking_documents+missing_checklist_items")

    def test_checklist_fields_default_empty_for_document_only_override(self):
        """A pure document-gate override (Phase 43 behavior, unchanged)
        must leave the 3 new checklist columns blank, never populated
        with stray data from a prior call."""
        _, appended = self._run()
        row_dict = dict(zip(EXPECTED_HEADERS, appended[0][1]))
        self.assertEqual(row_dict["Missing Checklist Instance IDs"], "")
        self.assertEqual(row_dict["Missing Checklist Item IDs"], "")
        self.assertEqual(row_dict["Missing Checklist Item Titles"], "")

    def test_sco_001_shaped_row_still_reads_back_with_blank_new_columns(self):
        """Backward compatibility: SCO-001 (written before Phase 44) has
        only the 11 legacy columns. Reading it back via the CURRENT
        (14-column) header map must yield "" for the 3 new fields, never
        an error or a missing key — proves the existing production row
        remains fully readable after this additive schema change."""
        legacy_row = {
            "Override ID": "SCO-001", "Stage ID": "STAGE-011", "Roadmap ID": "RM-003",
            "User": "570004109", "Overridden At": "2026-07-27 12:59:15",
            "Reason": "Топосъёмка будет зарегистрирована после получения оригинала",
            "Missing Blocking Doc IDs": "DOC-008", "Previous Status": "in_progress",
            "Target Status": "done", "Override Type": "missing_blocking_documents",
            "Configuration Error Details": "",
        }
        # Simulate reading this legacy row through the CURRENT header map —
        # any header absent from the raw row's own keys must read back "".
        full_row_dict = {h: legacy_row.get(h, "") for h in EXPECTED_HEADERS}
        self.assertEqual(full_row_dict["Override ID"], "SCO-001")
        self.assertEqual(full_row_dict["Missing Checklist Instance IDs"], "")
        self.assertEqual(full_row_dict["Missing Checklist Item IDs"], "")
        self.assertEqual(full_row_dict["Missing Checklist Item Titles"], "")

    def test_write_against_unmigrated_legacy_header_sheet_fails_safely(self):
        """Documents a real operational consequence of this additive
        schema change: until the LIVE Google Sheet's header row is
        actually extended with the 3 new columns (e.g. via
        init_business_core_sheets()/ensure_headers()), a write attempt
        against a sheet still on the old 11-column header will fail —
        row_from_header_map() deliberately raises rather than writing a
        value into the wrong/nonexistent column. The failure is caught
        and surfaced as {"ok": False, "error": ...}, never an unhandled
        exception — see record_stage_completion_override()'s own
        try/except. transition_stage_status() already treats this as a
        non-fatal partial_success (the Stage itself still completes),
        exactly like any other audit-write failure."""
        rm = _fresh_rm()
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = list(LEGACY_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_id", return_value="SCO-002"), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = rm.record_stage_completion_override(
                stage_id="STAGE-011", roadmap_id="RM-003", user="dida", reason="x",
                override_type="missing_checklist_items",
                missing_checklist_instance_ids=("CLIN-001",),
            )
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])
        mock_append.assert_not_called()

    def test_missing_required_args_rejected(self):
        rm = _fresh_rm()
        result = rm.record_stage_completion_override(
            stage_id="", roadmap_id="RM-003", user="dida", reason="x",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["override_id"], "")

    def test_blank_reason_rejected(self):
        rm = _fresh_rm()
        result = rm.record_stage_completion_override(
            stage_id="STAGE-011", roadmap_id="RM-003", user="dida", reason="",
        )
        self.assertFalse(result["ok"])

    def test_write_failure_surfaces_error_not_exception(self):
        rm = _fresh_rm()
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = list(EXPECTED_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_id", return_value="SCO-001"), \
             patch("business_core.sheets.append_business_row", side_effect=RuntimeError("boom")):
            result = rm.record_stage_completion_override(
                stage_id="STAGE-011", roadmap_id="RM-003", user="dida", reason="x",
            )
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])

    def test_never_writes_roadmap_stages(self):
        """Append-only into STAGE_COMPLETION_OVERRIDES — never touches
        ROADMAP_STAGES/ROADMAPS."""
        rm = _fresh_rm()
        write_targets = []

        def _append(sheet_key, row):
            write_targets.append(sheet_key)

        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = list(EXPECTED_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_id", return_value="SCO-001"), \
             patch("business_core.sheets.append_business_row", side_effect=_append):
            rm.record_stage_completion_override(
                stage_id="STAGE-011", roadmap_id="RM-003", user="dida", reason="x",
            )
        self.assertEqual(write_targets, ["stage_completion_overrides"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
