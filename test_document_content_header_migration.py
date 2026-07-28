"""
Phase 16B.1 schema-migration audit: tests for
migrate_document_content_headers.py — the one-time, admin-only, DOCUMENT_
CONTENT-only migration script that appends the 3 new exact-duplicate
columns (Duplicate Status / Duplicate Of Document ID / Duplicate Checked
At) to an already-populated production sheet that still has the Phase
16A (20-column) shape AND (as discovered on the first live attempt) a
grid physically sized to exactly 20 columns — requiring an explicit,
verified worksheet.resize() before any header can be written past
column 20.

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
    """
    Minimal gspread.Worksheet stand-in: row_values(1) for headers,
    update_cell(row, col, value) mutating row 1 only, get_all_values()
    for full-sheet reads, col_count/row_count properties, and resize()
    mimicking gspread's own behavior (updates col_count/row_count
    locally, only after the simulated "API call" succeeds).
    """

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
        return [list(self._headers)] + [list(r) for r in self._data_rows]

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
    def test_missing_all_three_headers(self):
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        self.assertEqual(plan["to_append"], ["Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At"])
        self.assertTrue(plan["prefix_ok"])
        self.assertTrue(plan["has_changes"])
        self.assertEqual(plan["after_preview"], CANONICAL_HEADERS)

    def test_missing_one_header(self):
        existing = PHASE_16A_HEADERS + ["Duplicate Status", "Duplicate Of Document ID"]
        m, plan = _plan(existing, current_col_count=22)
        self.assertEqual(plan["to_append"], ["Duplicate Checked At"])
        self.assertTrue(plan["prefix_ok"])
        self.assertTrue(plan["has_changes"])

    def test_all_headers_already_present(self):
        m, plan = _plan(CANONICAL_HEADERS, current_col_count=23)
        self.assertEqual(plan["to_append"], [])
        self.assertFalse(plan["has_changes"])
        self.assertEqual(plan["already_present"], CANONICAL_HEADERS)

    def test_existing_header_order_preserved_in_preview(self):
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        self.assertEqual(plan["after_preview"][:20], PHASE_16A_HEADERS)

    def test_conflict_detected_never_guessed(self):
        """If an existing header disagrees with the canonical schema at
        any position, the migration must refuse, not guess/reorder."""
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"  # was "Content Status"
        m, plan = _plan(tampered, current_col_count=20)
        self.assertFalse(plan["prefix_ok"])
        self.assertIsNone(plan["after_preview"])
        self.assertTrue(plan["conflicts"])

    # ── Grid-size analysis (Phase 16B.1 hardening) ──

    def test_grid_20_requires_resize_to_23(self):
        """п.1: Grid 20, required 23, dry-run."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        self.assertTrue(plan["grid_resize_required"])
        self.assertEqual(plan["current_col_count"], 20)
        self.assertEqual(plan["required_col_count"], 23)

    def test_grid_23_no_resize_required(self):
        """п.3: Grid 23 — resize не требуется, headers добавляются, если отсутствуют."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=23)
        self.assertFalse(plan["grid_resize_required"])
        self.assertTrue(plan["has_changes"])  # headers still missing even though grid is big enough

    def test_grid_larger_than_required_no_resize(self):
        """п.4: Grid >23 — resize не требуется, grid не уменьшается."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=30)
        self.assertFalse(plan["grid_resize_required"])

    def test_missing_one_header_at_grid_23(self):
        """п.11: Missing one of three headers при grid=23."""
        existing = PHASE_16A_HEADERS + ["Duplicate Status", "Duplicate Of Document ID"]
        m, plan = _plan(existing, current_col_count=23)
        self.assertFalse(plan["grid_resize_required"])
        self.assertEqual(plan["to_append"], ["Duplicate Checked At"])


class TestResizeGridIfNeeded(unittest.TestCase):
    def test_no_resize_when_not_required(self):
        m, plan = _plan(CANONICAL_HEADERS, current_col_count=23)
        sheet = _FakeSheet(CANONICAL_HEADERS, col_count=23)
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertFalse(outcome["attempted"])
        self.assertTrue(outcome["succeeded"])
        self.assertEqual(sheet.resize_calls, [])

    def test_resize_called_once_rows_preserved(self):
        """п.2/п.12: resize(rows=current_rows, cols=23) вызывается один
        раз; row_count сохраняется явно."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, row_count=999)
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertTrue(outcome["attempted"])
        self.assertTrue(outcome["succeeded"])
        self.assertEqual(sheet.resize_calls, [(999, 23)])
        self.assertEqual(sheet.col_count, 23)
        self.assertEqual(sheet.row_count, 999)

    def test_resize_failure_reported(self):
        """п.5."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, resize_side_effect=Exception("boom"))
        outcome = m.resize_grid_if_needed(sheet, plan)
        self.assertTrue(outcome["attempted"])
        self.assertFalse(outcome["succeeded"])
        self.assertIn("boom", outcome["error"])
        self.assertEqual(sheet.col_count, 20)  # unchanged


class TestApplyMigrationPlan(unittest.TestCase):
    def test_added_and_already_present_result(self):
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=23)  # grid already big enough
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=23)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertEqual(result["added_headers"], ["Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At"])
        self.assertEqual(result["already_present_headers"], PHASE_16A_HEADERS)

    def test_appends_strictly_to_the_right_never_reorders(self):
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=23)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=23)
        m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)

    def test_grid_20_live_resizes_then_writes_headers(self):
        """п.2: Grid 20, live — resize вызывается один раз, headers
        пишутся ПОСЛЕ resize, итог 23 headers."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, row_count=999)
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "ADDED")
        self.assertTrue(result["grid_resized"])
        self.assertEqual(sheet.resize_calls, [(999, 23)])
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)
        self.assertEqual(result["grid_before"], 20)
        self.assertEqual(result["grid_after"], 23)

    def test_repeated_migration_is_idempotent(self):
        """п.8: Повторный live после успешной миграции — ALREADY_PRESENT,
        resize=0, header writes=0."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, row_count=999)
        result1 = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result1["status"], "ADDED")
        first_headers = sheet.row_values(1)
        first_col_count = sheet.col_count

        plan2 = m.analyze_document_content_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        self.assertFalse(plan2["has_changes"])
        self.assertFalse(plan2["grid_resize_required"])
        result2 = m.apply_migration_plan(sheet, plan2)
        self.assertEqual(result2["status"], "ALREADY_PRESENT")
        self.assertEqual(sheet.resize_calls, [(999, 23)])  # no second resize call
        self.assertEqual(sheet.row_values(1), first_headers)
        self.assertEqual(sheet.col_count, first_col_count)

    def test_existing_row_data_untouched_after_resize_and_append(self):
        """п.9: Existing row data preserved after resize and header append."""
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16A_HEADERS) - 3)
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, data_rows=[data_row], col_count=20, row_count=999)
        before = sheet.get_all_values()[1:]
        result = m.apply_migration_plan(sheet, plan, data_rows_before=before)
        after = sheet.get_all_values()[1:]
        self.assertEqual(before, after)
        self.assertTrue(result["data_preserved"])

    def test_conflict_plan_raises_never_writes(self):
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"
        m, plan = _plan(tampered, current_col_count=20)
        sheet = _FakeSheet(tampered, col_count=20)
        with self.assertRaises(ValueError):
            m.apply_migration_plan(sheet, plan)
        self.assertEqual(sheet.row_values(1), tampered)
        self.assertEqual(sheet.resize_calls, [])

    def test_grid_resize_failure_headers_never_written(self):
        """п.5: Resize failure — header writes не выполняются;
        status=GRID_RESIZE_FAILED."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, resize_side_effect=Exception("quota exceeded"))
        result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "GRID_RESIZE_FAILED")
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)  # unchanged, nothing appended
        self.assertFalse(result["grid_resized"])
        self.assertIn("quota exceeded", result["error"])

    def test_resize_success_header_write_failure(self):
        """п.6: Resize success + header write failure —
        status=HEADER_WRITE_FAILED; rollback resize не выполняется;
        данные строк не меняются."""
        data_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(PHASE_16A_HEADERS) - 3)
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, data_rows=[data_row], col_count=20, row_count=999)

        original_update_cell = sheet.update_cell
        call_count = {"n": 0}

        def _flaky_update_cell(row, col, value):
            call_count["n"] += 1
            if call_count["n"] == 2:  # fail on the 2nd header write
                raise Exception("transient write error")
            original_update_cell(row, col, value)

        sheet.update_cell = _flaky_update_cell
        data_before = sheet.get_all_values()[1:]

        result = m.apply_migration_plan(sheet, plan, data_rows_before=data_before)

        self.assertEqual(result["status"], "HEADER_WRITE_FAILED")
        self.assertTrue(result["grid_resized"])  # resize was NOT rolled back
        self.assertEqual(sheet.col_count, 23)
        self.assertEqual(result["added_headers"], ["Duplicate Status"])  # only the first one succeeded
        self.assertTrue(result["data_preserved"])

    def test_verification_failed_when_post_write_headers_mismatch(self):
        """п.7: Verification col_count/headers всё ещё не совпадают —
        migration останавливается со status=VERIFICATION_FAILED."""
        m, plan = _plan(PHASE_16A_HEADERS, current_col_count=20)
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, row_count=999)

        # Simulate a write that "succeeds" (no exception) but silently
        # doesn't stick — row_values(1) re-read returns something else.
        original_row_values = sheet.row_values

        def _tampered_row_values(row):
            if row == 1:
                return PHASE_16A_HEADERS + ["Duplicate Status", "WRONG", "Duplicate Checked At"]
            return original_row_values(row)

        with patch.object(sheet, "row_values", side_effect=_tampered_row_values):
            result = m.apply_migration_plan(sheet, plan)
        self.assertEqual(result["status"], "VERIFICATION_FAILED")


class TestMainDryRunVsLive(unittest.TestCase):
    def test_dry_run_default_performs_no_write_no_resize(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)
        self.assertEqual(sheet.resize_calls, [])

    def test_explicit_dry_run_flag_performs_no_write(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--dry-run"]):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_without_confirmation_performs_no_write_no_resize(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="no"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_with_confirmation_resizes_and_appends(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, row_count=999)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_HEADERS)
        self.assertEqual(sheet.resize_calls, [(999, 23)])

    def test_conflict_aborts_with_nonzero_exit_no_write(self):
        m = _fresh_migration()
        tampered = list(PHASE_16A_HEADERS)
        tampered[2] = "Something Else"
        sheet = _FakeSheet(tampered, col_count=20)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.row_values(1), tampered)
        self.assertEqual(sheet.resize_calls, [])

    def test_live_grid_resize_failure_nonzero_exit(self):
        m = _fresh_migration()
        sheet = _FakeSheet(PHASE_16A_HEADERS, col_count=20, resize_side_effect=Exception("boom"))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_content": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_content_headers.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)
        self.assertEqual(sheet.row_values(1), PHASE_16A_HEADERS)  # untouched


if __name__ == "__main__":
    unittest.main()
