"""
Phase 16B.3 schema-migration tests for
migrate_document_content_review_fields.py — appends the 4 new
current-state review-cache columns (Structured Review Status,
Confirmed Fields JSON, Structured Review Version, Structured Review
Updated At) to a production-shaped DOCUMENT_CONTENT sheet already at
the Phase 16B.2 shape (31 columns, headers == grid).

Mirrors migrate_document_content_structured_fields.py's own test
structure (grid-resize-safe, dry-run/--live, normalized
data-preservation, appended_columns_clean, idempotency) — no live
Sheets writes.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


PHASE_16B2_HEADERS = [
    "Document ID", "Drive File ID", "Content Status",
    "Detected Document Type", "Suggested Document Template ID",
    "Template Match Confidence",
    "AI Summary", "Extracted Fields JSON", "Text Preview",
    "Language", "Page Count", "Keywords JSON",
    "Model", "Prompt Version", "Content Hash",
    "Analysis Started At", "Analysis Completed At", "Analysis Error",
    "Created At", "Updated At",
    "Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At",
    "Document Number", "Document Date", "Issued By",
    "Valid From", "Valid Until", "Has Expiration",
    "Direction", "Requires Action",
]

CANONICAL_HEADERS = PHASE_16B2_HEADERS + [
    "Structured Review Status", "Confirmed Fields JSON",
    "Structured Review Version", "Structured Review Updated At",
]


def _fresh_migration():
    for key in list(sys.modules.keys()):
        if "business_core" in key or key == "migrate_document_content_review_fields":
            del sys.modules[key]
    import migrate_document_content_review_fields as m
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
        assert row == 1
        if col > self.col_count:
            raise Exception(f"APIError: exceeds grid limits. Max columns: {self.col_count}")
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
    def test_grid_31_requires_resize_to_35(self):
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=31)
        self.assertTrue(plan["grid_resize_required"])
        self.assertEqual(plan["required_col_count"], 35)
        self.assertEqual(plan["to_append"], [
            "Structured Review Status", "Confirmed Fields JSON",
            "Structured Review Version", "Structured Review Updated At",
        ])

    def test_grid_35_no_resize_required(self):
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=35)
        self.assertFalse(plan["grid_resize_required"])

    def test_conflict_detected_never_guessed(self):
        tampered = list(PHASE_16B2_HEADERS)
        tampered[2] = "Something Else"
        m, plan = _plan(tampered, current_col_count=31)
        self.assertFalse(plan["prefix_ok"])


class TestApplyMigrationPlan(unittest.TestCase):
    def test_grid_31_live_resizes_then_writes_headers(self):
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=31)
        sheet = _FakeSheet(PHASE_16B2_HEADERS, col_count=31, row_count=999)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertEqual(sheet.resize_calls, [(999, 35)])
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)

    def test_repeated_live_after_success_is_idempotent(self):
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=31)
        sheet = _FakeSheet(PHASE_16B2_HEADERS, col_count=31, row_count=999)
        m.apply_migration_plan(sheet, plan)
        plan2 = m.analyze_document_content_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        self.assertFalse(plan2["has_changes"])
        result2 = m.apply_migration_plan(sheet, plan2)
        self.assertEqual(result2["status"], "ALREADY_PRESENT")
        self.assertEqual(sheet.resize_calls, [(999, 35)])

    def test_data_preserved_and_appended_columns_clean(self):
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16B2_HEADERS) - 3)
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=31)
        sheet = _FakeSheet(PHASE_16B2_HEADERS, data_rows=[data_row], col_count=31, row_count=999)
        data_before = sheet.get_all_values()[1:]
        result = m.apply_migration_plan(sheet, plan, data_rows_before=data_before)
        self.assertTrue(result["data_preserved"])
        self.assertTrue(result["appended_columns_clean"])
        self.assertEqual(result["preserved_column_count"], 31)

    def test_grid_resize_failure_headers_never_written(self):
        m, plan = _plan(PHASE_16B2_HEADERS, current_col_count=31)
        sheet = _FakeSheet(PHASE_16B2_HEADERS, col_count=31, resize_side_effect=Exception("boom"))
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "GRID_RESIZE_FAILED")
        self.assertEqual(sheet.row_values(1), PHASE_16B2_HEADERS)


class TestMainDryRunVsLive(unittest.TestCase):
    def test_dry_run_default_performs_no_write_no_resize(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B2_HEADERS, col_count=31)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_review_fields.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_with_confirmation_resizes_and_appends(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16B2_HEADERS, col_count=31, row_count=999)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_review_fields.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)
        self.assertEqual(sheet.resize_calls, [(999, 35)])

    def test_conflict_aborts_with_nonzero_exit_no_write(self):
        m = _fresh_migration()
        tampered = list(PHASE_16B2_HEADERS)
        tampered[2] = "Something Else"
        sheet = _FakeSheet(tampered, col_count=31)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_review_fields.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.resize_calls, [])


if __name__ == "__main__":
    unittest.main()
