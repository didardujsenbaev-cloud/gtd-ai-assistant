"""
Phase 16B.2 schema-migration tests for
migrate_document_content_structured_fields.py — appends the 8 new
canonical structured-document-field columns (Document Number, Document
Date, Issued By, Valid From, Valid Until, Has Expiration, Direction,
Requires Action) to a production-shaped DOCUMENT_CONTENT sheet that is
already at the Phase 16B.1 shape (23 columns, headers == grid).

Mirrors test_document_content_header_migration.py's structure/coverage
(grid-resize-safe, dry-run/--live, normalized data-preservation,
appended_columns_clean, idempotency) — no live Sheets writes.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


PHASE_16B1_HEADERS = [
    "Document ID", "Drive File ID", "Content Status",
    "Detected Document Type", "Suggested Document Template ID",
    "Template Match Confidence",
    "AI Summary", "Extracted Fields JSON", "Text Preview",
    "Language", "Page Count", "Keywords JSON",
    "Model", "Prompt Version", "Content Hash",
    "Analysis Started At", "Analysis Completed At", "Analysis Error",
    "Created At", "Updated At",
    "Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At",
]

CANONICAL_HEADERS = PHASE_16B1_HEADERS + [
    "Document Number", "Document Date", "Issued By",
    "Valid From", "Valid Until", "Has Expiration",
    "Direction", "Requires Action",
]


def _fresh_migration():
    for key in list(sys.modules.keys()):
        if "business_core" in key or key == "migrate_document_content_structured_fields":
            del sys.modules[key]
    import migrate_document_content_structured_fields as m
    return m


class _FakeSheet:
    def __init__(self, headers, data_rows=None, col_count=None, row_count=999,
                 resize_side_effect=None):
        self._headers = list(headers)
        self._data_rows = [list(r) for r in (data_rows or [])]
        self.col_count = col_count if col_count is not None else len(headers)
        self.row_count = row_count
        self._resize_side_effect = resize_side_effect
        self.resize_calls: list[tuple] = []

    def row_values(self, row):
        if row == 1:
            return list(self._headers)
        idx = row - 2
        return list(self._data_rows[idx]) if 0 <= idx < len(self._data_rows) else []

    def update_cell(self, row, col, value):
        assert row == 1, "migration must never write to a data row"
        if col > self.col_count:
            raise Exception(
                f"APIError: [400]: Range exceeds grid limits. Max columns: {self.col_count}"
            )
        while len(self._headers) < col:
            self._headers.append("")
        self._headers[col - 1] = value

    def get_all_values(self):
        def _padded(row):
            row = list(row)
            if len(row) < self.col_count:
                row = row + [""] * (self.col_count - len(row))
            return row

        return [_padded(self._headers)] + [_padded(r) for r in self._data_rows]

    def resize(self, rows=None, cols=None):
        self.resize_calls.append((rows, cols))
        if self._resize_side_effect is not None:
            raise self._resize_side_effect
        if rows is not None:
            self.row_count = rows
        if cols is not None:
            self.col_count = cols


def _plan(existing_headers, current_col_count=None):
    m = _fresh_migration()
    with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
        return m, m.analyze_document_content_headers(existing_headers, current_col_count=current_col_count)


class TestAnalyzeDocumentContentHeaders(unittest.TestCase):
    def test_missing_all_eight_headers(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        self.assertEqual(plan["to_append"], [
            "Document Number", "Document Date", "Issued By",
            "Valid From", "Valid Until", "Has Expiration",
            "Direction", "Requires Action",
        ])
        self.assertTrue(plan["prefix_ok"])
        self.assertTrue(plan["has_changes"])

    def test_grid_23_requires_resize_to_31(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        self.assertTrue(plan["grid_resize_required"])
        self.assertEqual(plan["current_col_count"], 23)
        self.assertEqual(plan["required_col_count"], 31)

    def test_grid_31_no_resize_required(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=31)
        self.assertFalse(plan["grid_resize_required"])
        self.assertTrue(plan["has_changes"])

    def test_grid_larger_than_required_no_resize(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=40)
        self.assertFalse(plan["grid_resize_required"])

    def test_conflict_detected_never_guessed(self):
        tampered = list(PHASE_16B1_HEADERS)
        tampered[2] = "Something Else"
        m, plan = _plan(tampered, current_col_count=23)
        self.assertFalse(plan["prefix_ok"])
        self.assertIsNone(plan["after_preview"])

    def test_missing_one_header_at_grid_31(self):
        existing = PHASE_16B1_HEADERS + [
            "Document Number", "Document Date", "Issued By",
            "Valid From", "Valid Until", "Has Expiration", "Direction",
        ]
        m, plan = _plan(existing, current_col_count=31)
        self.assertFalse(plan["grid_resize_required"])
        self.assertEqual(plan["to_append"], ["Requires Action"])

    def test_all_headers_already_present(self):
        m, plan = _plan(CANONICAL_HEADERS, current_col_count=31)
        self.assertFalse(plan["has_changes"])


class TestResizeGridIfNeeded(unittest.TestCase):
    def test_resize_called_once_rows_preserved(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertTrue(outcome["succeeded"])
        self.assertEqual(sheet.resize_calls, [(999, 31)])
        self.assertEqual(sheet.col_count, 31)
        self.assertEqual(sheet.row_count, 999)

    def test_no_resize_when_not_required(self):
        m, plan = _plan(CANONICAL_HEADERS, current_col_count=31)
        sheet = _FakeSheet(CANONICAL_HEADERS, col_count=31)
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertFalse(outcome["attempted"])
        self.assertEqual(sheet.resize_calls, [])

    def test_resize_failure_reported(self):
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, resize_side_effect=Exception("boom"))
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertFalse(outcome["succeeded"])
        self.assertEqual(sheet.col_count, 23)


class TestApplyMigrationPlan(unittest.TestCase):
    def test_grid_23_live_resizes_then_writes_headers(self):
        """п.2: Grid 23, live — resize вызывается один раз, headers
        пишутся ПОСЛЕ resize, итог 31 header."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertTrue(result["grid_resized"])
        self.assertEqual(sheet.resize_calls, [(999, 31)])
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)
        self.assertEqual(result["grid_before"], 23)
        self.assertEqual(result["grid_after"], 31)

    def test_grid_31_no_resize_writes_if_missing(self):
        """п.3."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=31)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=31)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertEqual(sheet.resize_calls, [])
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)

    def test_grid_larger_no_shrink(self):
        """п.4."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=40)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=40)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.resize_calls, [])
        self.assertEqual(sheet.col_count, 40)

    def test_grid_resize_failure_headers_never_written(self):
        """п.5."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, resize_side_effect=Exception("quota exceeded"))
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "GRID_RESIZE_FAILED")
        self.assertEqual(sheet.row_values(1), PHASE_16B1_HEADERS)
        self.assertFalse(result["grid_resized"])

    def test_resize_success_header_write_failure(self):
        """п.6."""
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16B1_HEADERS) - 3)
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, data_rows=[data_row], col_count=23, row_count=999)

        original_update_cell = sheet.update_cell
        call_count = {"n": 0}

        def _flaky_update_cell(row, col, value):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise Exception("transient write error")
            original_update_cell(row, col, value)

        sheet.update_cell = _flaky_update_cell
        data_before = sheet.get_all_values()[1:]

        result = m.apply_migration_plan(sheet, plan, data_rows_before=data_before)

        self.assertEqual(result["status"], "HEADER_WRITE_FAILED")
        self.assertTrue(result["grid_resized"])  # not rolled back
        self.assertEqual(sheet.col_count, 31)
        self.assertEqual(result["added_headers"], ["Document Number"])
        self.assertTrue(result["data_preserved"])

    def test_verification_failed_when_post_write_headers_mismatch(self):
        """п.7."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)

        original_row_values = sheet.row_values

        def _tampered_row_values(row):
            if row == 1:
                return PHASE_16B1_HEADERS + ["Document Number", "WRONG"] + ["Issued By", "Valid From",
                                                                             "Valid Until", "Has Expiration",
                                                                             "Direction", "Requires Action"]
            return original_row_values(row)

        with patch.object(sheet, "row_values", side_effect=_tampered_row_values):
            result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "VERIFICATION_FAILED")

    def test_repeated_live_after_success_is_idempotent(self):
        """п.8: Повторный live после успешной миграции — ALREADY_PRESENT,
        resize=0, header writes=0."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)
        result1 = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result1["status"], "ADDED")

        plan2 = m.analyze_document_content_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        self.assertFalse(plan2["has_changes"])
        result2 = m.apply_migration_plan(sheet, plan2)
        self.assertEqual(result2["status"], "ALREADY_PRESENT")
        self.assertEqual(sheet.resize_calls, [(999, 31)])  # no second resize call

    def test_existing_row_data_preserved_after_resize_and_append(self):
        """п.9."""
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16B1_HEADERS) - 3)
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, data_rows=[data_row], col_count=23, row_count=999)
        data_before = sheet.get_all_values()[1:]
        result = m.apply_migration_plan(sheet, plan, data_rows_before=data_before)
        self.assertTrue(result["data_preserved"])
        self.assertTrue(result["appended_columns_clean"])
        self.assertEqual(result["preserved_column_count"], 23)

    def test_existing_header_order_preserved(self):
        """п.10."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)
        m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.row_values(1)[:23], PHASE_16B1_HEADERS)

    def test_missing_one_of_eight_headers_at_grid_31(self):
        """п.11."""
        existing = PHASE_16B1_HEADERS + [
            "Document Number", "Document Date", "Issued By", "Valid From",
            "Valid Until", "Has Expiration", "Direction",
        ]
        m, plan = _plan(existing, current_col_count=31)
        sheet = _FakeSheet(existing, col_count=31)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertEqual(result["added_headers"], ["Requires Action"])

    def test_row_count_preserved_during_resize(self):
        """п.12: mock worksheet.row_count сохраняется при resize."""
        m, plan = _plan(PHASE_16B1_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=777)
        m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.resize_calls, [(777, 31)])
        self.assertEqual(sheet.row_count, 777)


class TestMainDryRunVsLive(unittest.TestCase):
    def test_dry_run_default_performs_no_write_no_resize(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_structured_fields.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16B1_HEADERS)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_with_confirmation_resizes_and_appends(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, row_count=999)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_structured_fields.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)
        self.assertEqual(sheet.resize_calls, [(999, 31)])

    def test_live_without_confirmation_performs_no_write(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_structured_fields.py", "--live"]), \
             patch("builtins.input", return_value="no"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.resize_calls, [])

    def test_conflict_aborts_with_nonzero_exit_no_write(self):
        m = _fresh_migration()
        tampered = list(PHASE_16B1_HEADERS)
        tampered[2] = "Something Else"
        sheet = _FakeSheet(tampered, col_count=23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_structured_fields.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_grid_resize_failure_nonzero_exit(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B1_HEADERS, col_count=23, resize_side_effect=Exception("boom"))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_structured_fields.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.row_values(1), PHASE_16B1_HEADERS)


if __name__ == "__main__":
    unittest.main()
