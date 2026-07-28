"""
Phase 16B.1 schema-migration audit: tests for
migrate_document_content_headers.py — the one-time, admin-only, DOCUMENT_
CONTENT-only migration script that appends the 3 new exact-duplicate
columns (Duplicate Status / Duplicate Of Document ID / Duplicate Checked
At) to an already-populated production sheet that still has the Phase
16A (20-column) shape.

No live Sheets writes, no live Telegram calls — mocks only. This file
never touches production; it verifies the SCRIPT's own logic against an
in-memory fake sheet.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


PHASE_16A_HEADERS = [
    "Document ID", "Drive File ID", "Content Status",
    "Detected Document Type", "Suggested Document Template ID",
    "Template Match Confidence",
    "AI Summary", "Extracted Fields JSON", "Text Preview",
    "Language", "Page Count", "Keywords JSON",
    "Model", "Prompt Version", "Content Hash",
    "Analysis Started At", "Analysis Completed At", "Analysis Error",
    "Created At", "Updated At",
]

CANONICAL_HEADERS = PHASE_16A_HEADERS + [
    "Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At",
]


def _fresh_migration():
    for key in list(sys.modules.keys()):
        if "business_core" in key or key == "migrate_document_content_headers":
            del sys.modules[key]
    import migrate_document_content_headers as m
    return m


class _FakeSheet:
    """Minimal gspread.Worksheet stand-in: row_values(1) for headers,
    update_cell(row, col, value) mutating row 1 only, get_all_values()
    for full-sheet reads (headers + data)."""

    def __init__(self, headers, data_rows=None):
        self._headers = list(headers)
        self._data_rows = [list(r) for r in (data_rows or [])]

    def row_values(self, row):
        if row == 1:
            return list(self._headers)
        idx = row - 2
        return list(self._data_rows[idx]) if 0 <= idx < len(self._data_rows) else []

    def update_cell(self, row, col, value):
        assert row == 1, "migration must never write to a data row"
        while len(self._headers) < col:
            self._headers.append("")
        self._headers[col - 1] = value

    def get_all_values(self):
        return [list(self._headers)] + [list(r) for r in self._data_rows]


class TestAnalyzeDocumentContentHeaders(unittest.TestCase):
    def test_missing_all_three_headers(self):
        m = _fresh_migration()
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(PHASE_16A_HEADERS)
        self.assertEqual(plan["to_append"], ["Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At"])
        self.assertTrue(plan["prefix_ok"])
        self.assertTrue(plan["has_changes"])
        self.assertEqual(plan["after_preview"], CANONICAL_HEADERS)

    def test_missing_one_header(self):
        m = _fresh_migration()
        existing = PHASE_16A_HEADERS + ["Duplicate Status", "Duplicate Of Document ID"]
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(existing)
        self.assertEqual(plan["to_append"], ["Duplicate Checked At"])
        self.assertTrue(plan["prefix_ok"])
        self.assertTrue(plan["has_changes"])

    def test_all_headers_already_present(self):
        m = _fresh_migration()
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(CANONICAL_HEADERS)
        self.assertEqual(plan["to_append"], [])
        self.assertFalse(plan["has_changes"])
        self.assertEqual(plan["already_present"], CANONICAL_HEADERS)

    def test_existing_header_order_preserved_in_preview(self):
        m = _fresh_migration()
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(PHASE_16A_HEADERS)
        self.assertEqual(plan["after_preview"][:20], PHASE_16A_HEADERS)

    def test_conflict_detected_never_guessed(self):
        """If an existing header disagrees with the canonical schema at
        any position, the migration must refuse, not guess/reorder."""
        m = _fresh_migration()
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"  # was "Content Status"
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(tampered)
        self.assertFalse(plan["prefix_ok"])
        self.assertIsNone(plan["after_preview"])
        self.assertTrue(plan["conflicts"])


class TestApplyMigrationPlan(unittest.TestCase):
    def _plan(self, existing_headers):
        m = _fresh_migration()
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            return m, m.analyze_document_content_headers(existing_headers)

    def test_added_and_already_present_result_codes(self):
        m, plan = self._plan(PHASE_16A_HEADERS)
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        results = m.apply_migration_plan(sheet, plan)
        results_by_name = dict(results)
        for h in PHASE_16A_HEADERS:
            self.assertEqual(results_by_name[h], "ALREADY_PRESENT")
        for h in ("Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At"):
            self.assertEqual(results_by_name[h], "ADDED")

    def test_appends_strictly_to_the_right_never_reorders(self):
        m, plan = self._plan(PHASE_16A_HEADERS)
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)

    def test_repeated_migration_is_idempotent(self):
        m, plan = self._plan(PHASE_16A_HEADERS)
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        m.apply_migration_plan(sheet, plan)
        first_headers = sheet.row_values(1)

        # Second run against the now-migrated sheet.
        plan2 = m.analyze_document_content_headers(sheet.row_values(1))
        self.assertFalse(plan2["has_changes"])
        results2 = m.apply_migration_plan(sheet, plan2)
        self.assertTrue(all(outcome == "ALREADY_PRESENT" for _, outcome in results2))
        self.assertEqual(sheet.row_values(1), first_headers)

    def test_existing_row_data_untouched(self):
        m, plan = self._plan(PHASE_16A_HEADERS)
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16A_HEADERS) - 3)
        sheet = _FakeSheet(PHASE_16A_HEADERS, data_rows=[data_row])
        before = sheet.get_all_values()[1:]
        m.apply_migration_plan(sheet, plan)
        after = sheet.get_all_values()[1:]
        self.assertEqual(before, after)

    def test_conflict_plan_raises_never_writes(self):
        m = _fresh_migration()
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"
        with patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}):
            plan = m.analyze_document_content_headers(tampered)
        sheet = _FakeSheet(tampered)
        with self.assertRaises(ValueError):
            m.apply_migration_plan(sheet, plan)
        # Nothing written — headers unchanged.
        self.assertEqual(sheet.row_values(1), tampered)


class TestMainDryRunVsLive(unittest.TestCase):
    def test_dry_run_default_performs_no_write(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)  # unchanged

    def test_explicit_dry_run_flag_performs_no_write(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--dry-run"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)

    def test_live_without_confirmation_performs_no_write(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="no"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)

    def test_live_with_confirmation_appends_and_verifies(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)

    def test_conflict_aborts_with_nonzero_exit_no_write(self):
        m = _fresh_migration()
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"
        sheet = _FakeSheet(tampered)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.row_values(1), tampered)  # unchanged


if __name__ == "__main__":
    unittest.main()
