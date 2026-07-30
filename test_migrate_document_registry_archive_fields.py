"""
Phase 16C.9B — Document Archive Schema Foundation.

Tests for migrate_document_registry_archive_fields.py (pure header
analysis + fake-worksheet migration apply) and for runtime backward
compatibility of business_core/document_manager.py against the
expanded 27-header DOCUMENT_REGISTRY schema.

No real Google Sheets access — fakes/mocks only.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import migrate_document_registry_archive_fields as mig

CANONICAL_23 = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID",
    "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
]
CANONICAL_27 = CANONICAL_23 + ["Archived At", "Archived By", "Archive Reason", "Previous Status"]


class FakeWorksheet:
    """Minimal in-memory stand-in for gspread.Worksheet."""

    def __init__(self, rows: list[list[str]], col_count: int, row_count: int = 1000, title: str = "DOCUMENT_REGISTRY"):
        self._rows = [list(r) for r in rows]
        self.col_count = col_count
        self.row_count = row_count
        self.title = title
        self.update_cell_calls: list[tuple[int, int, str]] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.fail_resize = False
        self.fail_update_cell_at: int | None = None  # 1-based call number to fail on

    def row_values(self, row: int) -> list[str]:
        idx = row - 1
        if idx < 0 or idx >= len(self._rows):
            return []
        return list(self._rows[idx])

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self._rows]

    def resize(self, rows: int, cols: int) -> None:
        self.resize_calls.append((rows, cols))
        if self.fail_resize:
            raise RuntimeError("simulated resize failure")
        self.row_count = rows
        self.col_count = cols

    def update_cell(self, row: int, col: int, value: str) -> None:
        self.update_cell_calls.append((row, col, value))
        if self.fail_update_cell_at is not None and len(self.update_cell_calls) == self.fail_update_cell_at:
            raise RuntimeError("simulated update_cell failure")
        idx = row - 1
        while len(self._rows) <= idx:
            self._rows.append([])
        r = self._rows[idx]
        while len(r) < col:
            r.append("")
        r[col - 1] = value


def _sheet_with_headers(headers: list[str], data_rows: list[list[str]] | None = None, col_count: int | None = None) -> FakeWorksheet:
    rows = [headers] + (data_rows or [])
    return FakeWorksheet(rows, col_count=col_count if col_count is not None else max(len(headers), 10))


# ────────────────────────────────────────────────────────────
# 1. Canonical target
# ────────────────────────────────────────────────────────────

class TestCanonicalTarget(unittest.TestCase):
    def test_canonical_is_exactly_27_headers(self):
        self.assertEqual(mig._canonical_headers(), CANONICAL_27)
        self.assertEqual(len(mig._canonical_headers()), 27)


# ────────────────────────────────────────────────────────────
# 2-6. Partial-prefix planning
# ────────────────────────────────────────────────────────────

class TestPartialPrefixPlanning(unittest.TestCase):
    def test_23_header_schema_plans_four_additions(self):
        plan = mig.analyze_document_registry_headers(CANONICAL_23, current_col_count=23)
        self.assertTrue(plan["prefix_ok"])
        self.assertEqual(plan["to_append"], ["Archived At", "Archived By", "Archive Reason", "Previous Status"])
        self.assertTrue(plan["has_changes"])

    def test_24_header_clean_prefix_plans_three(self):
        existing = CANONICAL_23 + ["Archived At"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=24)
        self.assertTrue(plan["prefix_ok"])
        self.assertEqual(plan["to_append"], ["Archived By", "Archive Reason", "Previous Status"])

    def test_25_header_clean_prefix_plans_two(self):
        existing = CANONICAL_23 + ["Archived At", "Archived By"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=25)
        self.assertTrue(plan["prefix_ok"])
        self.assertEqual(plan["to_append"], ["Archive Reason", "Previous Status"])

    def test_26_header_clean_prefix_plans_one(self):
        existing = CANONICAL_23 + ["Archived At", "Archived By", "Archive Reason"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=26)
        self.assertTrue(plan["prefix_ok"])
        self.assertEqual(plan["to_append"], ["Previous Status"])

    def test_27_header_schema_already_present(self):
        plan = mig.analyze_document_registry_headers(CANONICAL_27, current_col_count=27)
        self.assertTrue(plan["prefix_ok"])
        self.assertEqual(plan["to_append"], [])
        self.assertFalse(plan["has_changes"])


# ────────────────────────────────────────────────────────────
# 7-13. Fail-closed cases
# ────────────────────────────────────────────────────────────

class TestFailClosedCases(unittest.TestCase):
    def test_existing_header_rename_fails_closed(self):
        existing = list(CANONICAL_23)
        existing[20] = "Note"  # "Notes" renamed
        plan = mig.analyze_document_registry_headers(existing, current_col_count=23)
        self.assertFalse(plan["prefix_ok"])
        self.assertTrue(any(c[1] == "Note" for c in plan["conflicts"]))

    def test_misspelled_archived_at_fails_closed(self):
        existing = CANONICAL_23 + ["Archved At"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=24)
        self.assertFalse(plan["prefix_ok"])

    def test_new_headers_wrong_order_fails_closed(self):
        existing = CANONICAL_23 + ["Archived By", "Archived At"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=25)
        self.assertFalse(plan["prefix_ok"])

    def test_unknown_extra_header_fails_closed(self):
        existing = CANONICAL_23 + ["Some Unknown Column"]
        plan = mig.analyze_document_registry_headers(existing, current_col_count=24)
        self.assertFalse(plan["prefix_ok"])

    def test_duplicate_existing_header_fails_closed(self):
        existing = list(CANONICAL_23)
        existing[10] = existing[9]  # duplicate "Document Name" into "Status" slot
        plan = mig.analyze_document_registry_headers(existing, current_col_count=23)
        self.assertFalse(plan["prefix_ok"])
        self.assertTrue(plan["duplicate_existing_headers"] or plan["conflicts"])

    def test_duplicate_new_header_detected_via_canonical_check(self):
        # Simulate a corrupted canonical schema (defensive check — the real
        # BUSINESS_HEADERS list has no duplicates, but the analyzer must
        # never rely solely on get_header_index_map's first-occurrence
        # behavior to hide a duplicate).
        with patch.object(mig, "_canonical_headers", return_value=CANONICAL_23 + ["Archived At", "Archived At"]):
            plan = mig.analyze_document_registry_headers(CANONICAL_23, current_col_count=23)
            self.assertFalse(plan["prefix_ok"])
            self.assertIn("Archived At", plan["duplicate_canonical_headers"])

    def test_empty_cell_inside_populated_prefix_fails_closed(self):
        existing = list(CANONICAL_23)
        existing[5] = ""  # blank out "Object ID"
        plan = mig.analyze_document_registry_headers(existing, current_col_count=23)
        self.assertFalse(plan["prefix_ok"])
        self.assertTrue(any(c[0] == 6 for c in plan["conflicts"]))


# ────────────────────────────────────────────────────────────
# 14-16. Dry-run / live confirmation behavior
# ────────────────────────────────────────────────────────────

class TestDryRunLiveConfirmation(unittest.TestCase):
    def test_dry_run_performs_zero_writes(self):
        sheet = _sheet_with_headers(CANONICAL_23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog"]):
                rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.update_cell_calls, [])
        self.assertEqual(sheet.resize_calls, [])

    def test_live_requires_exact_yes(self):
        sheet = _sheet_with_headers(CANONICAL_23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog", "--live"]):
                with patch("builtins.input", return_value="YES"):
                    rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(sheet.update_cell_calls), 4)

    def test_non_yes_confirmation_performs_zero_writes(self):
        sheet = _sheet_with_headers(CANONICAL_23)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog", "--live"]):
                with patch("builtins.input", return_value="yes"):
                    rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.update_cell_calls, [])
        self.assertEqual(sheet.resize_calls, [])


# ────────────────────────────────────────────────────────────
# 17-19. Write mechanism
# ────────────────────────────────────────────────────────────

class TestWriteMechanism(unittest.TestCase):
    def test_grid_resizes_only_when_needed(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(sheet.resize_calls, [])
        self.assertEqual(result["status"], mig.STATUS_ADDED)

    def test_grid_resize_triggered_when_narrow(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=23)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(sheet.resize_calls, [(sheet.row_count, 27)])

    def test_existing_matching_headers_not_rewritten(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        written_cols = [c for (_, c, _) in sheet.update_cell_calls]
        self.assertEqual(written_cols, [24, 25, 26, 27])

    def test_only_missing_trailing_cells_written(self):
        sheet = _sheet_with_headers(CANONICAL_23 + ["Archived At", "Archived By"], col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual([v for (_, _, v) in sheet.update_cell_calls], ["Archive Reason", "Previous Status"])


# ────────────────────────────────────────────────────────────
# 20-22. Data preservation
# ────────────────────────────────────────────────────────────

class TestDataPreservation(unittest.TestCase):
    def test_data_rows_unchanged(self):
        data = [["DREG-001", "DFAM-001", "1"] + [""] * 20]
        sheet = _sheet_with_headers(CANONICAL_23, data_rows=data, col_count=27)
        data_before = sheet.get_all_values()[1:]
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=data_before)
        self.assertTrue(result["data_preserved"])
        self.assertEqual(sheet.get_all_values()[1], data[0])

    def test_existing_values_never_shift(self):
        data = [["DREG-001", "DFAM-001", "1", "BIZ-001"] + [""] * 19]
        sheet = _sheet_with_headers(CANONICAL_23, data_rows=data, col_count=27)
        data_before = sheet.get_all_values()[1:]
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        mig.apply_migration_plan(sheet, plan, data_rows_before=data_before)
        after = sheet.get_all_values()[1]
        self.assertEqual(after[0], "DREG-001")
        self.assertEqual(after[3], "BIZ-001")

    def test_new_trailing_cells_remain_blank(self):
        data = [["DREG-001"] + [""] * 22]
        sheet = _sheet_with_headers(CANONICAL_23, data_rows=data, col_count=27)
        data_before = sheet.get_all_values()[1:]
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=data_before)
        self.assertTrue(result["appended_columns_clean"])


# ────────────────────────────────────────────────────────────
# 23-26. Verification / typed failures
# ────────────────────────────────────────────────────────────

class TestVerificationAndFailures(unittest.TestCase):
    def test_final_exact_header_verification(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(result["status"], mig.STATUS_ADDED)
        self.assertEqual(sheet.row_values(1), CANONICAL_27)

    def test_verification_mismatch_returns_failure(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)

        original_update_cell = sheet.update_cell
        def _corrupting_update_cell(row, col, value):
            original_update_cell(row, col, "WRONG_VALUE" if col == 27 else value)
        sheet.update_cell = _corrupting_update_cell

        result = mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(result["status"], mig.STATUS_VERIFICATION_FAILED)

    def test_header_write_failure_returns_typed_failure(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        sheet.fail_update_cell_at = 2
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(result["status"], mig.STATUS_HEADER_WRITE_FAILED)
        self.assertEqual(result["added_headers"], ["Archived At"])

    def test_resize_failure_returns_typed_failure(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=23)
        sheet.fail_resize = True
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        result = mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(result["status"], mig.STATUS_GRID_RESIZE_FAILED)
        self.assertEqual(sheet.update_cell_calls, [])

    def test_schema_conflict_raises_before_any_write(self):
        existing = list(CANONICAL_23)
        existing[20] = "Note"
        sheet = _sheet_with_headers(existing, col_count=27)
        plan = mig.analyze_document_registry_headers(sheet.row_values(1), current_col_count=sheet.col_count)
        with self.assertRaises(ValueError):
            mig.apply_migration_plan(sheet, plan, data_rows_before=[])
        self.assertEqual(sheet.update_cell_calls, [])
        self.assertEqual(sheet.resize_calls, [])


# ────────────────────────────────────────────────────────────
# 27-29. Idempotency / resume
# ────────────────────────────────────────────────────────────

class TestIdempotencyAndResume(unittest.TestCase):
    def test_first_live_run_succeeds(self):
        sheet = _sheet_with_headers(CANONICAL_23, col_count=27)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog", "--live"]):
                with patch("builtins.input", return_value="YES"):
                    rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_27)

    def test_second_run_is_noop(self):
        sheet = _sheet_with_headers(CANONICAL_27, col_count=27)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog", "--live"]):
                with patch("builtins.input", return_value="YES"):
                    rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.update_cell_calls, [])
        self.assertEqual(sheet.resize_calls, [])

    def test_interrupted_valid_prefix_state_safely_resumes(self):
        # Simulates a prior partial run that got as far as "Archived At"
        # + "Archived By" before crashing.
        sheet = _sheet_with_headers(CANONICAL_23 + ["Archived At", "Archived By"], col_count=27)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with patch("sys.argv", ["prog", "--live"]):
                with patch("builtins.input", return_value="YES"):
                    rc = mig.main()
        self.assertEqual(rc, 0)
        self.assertEqual(sheet.row_values(1), CANONICAL_27)
        self.assertEqual([v for (_, _, v) in sheet.update_cell_calls], ["Archive Reason", "Previous Status"])


# ────────────────────────────────────────────────────────────
# 30. Bootstrap
# ────────────────────────────────────────────────────────────

class TestBootstrap(unittest.TestCase):
    def test_bootstrap_canonical_headers_contain_all_27(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["document_registry"], CANONICAL_27)


# ────────────────────────────────────────────────────────────
# 31-33, 15. Runtime backward compatibility (document_manager.py,
# unmodified this phase, run against the expanded 27-header schema)
# ────────────────────────────────────────────────────────────

class TestRuntimeBackwardCompatibility(unittest.TestCase):
    def test_old_style_data_rows_remain_readable_with_blank_new_fields(self):
        from business_core.document_manager import find_document_by_id
        data = [["DREG-001", "DFAM-001", "1", "BIZ-001"] + [""] * 19]
        sheet = _sheet_with_headers(CANONICAL_27, data_rows=data, col_count=27)
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {
            **{h: "" for h in CANONICAL_27},
            "Document ID": "DREG-001", "Business ID": "BIZ-001",
        })):
            doc = find_document_by_id("DREG-001")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["document_id"], "DREG-001")

    def test_existing_code_can_append_row_against_27_headers(self):
        from business_core.document_manager import create_document
        sheet = _sheet_with_headers(CANONICAL_27, col_count=27)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as append_mock:
            result = create_document(business_id="BIZ-001", document_name="Test Doc")
        self.assertTrue(result["ok"])
        row = append_mock.call_args[0][1]
        self.assertEqual(len(row), 27)
        # New archive fields must be filled with "" by old code, never
        # populated or accidentally shifted.
        self.assertEqual(row[23:27], ["", "", "", ""])

    def test_existing_status_update_touches_only_status_and_updated_at(self):
        from business_core.document_manager import update_document_status
        sheet = _sheet_with_headers(CANONICAL_27, data_rows=[["DREG-001"] + [""] * 26], col_count=27)
        found_row = dict(zip(CANONICAL_27, ["DREG-001"] + [""] * 26))
        found_row["Status"] = "uploaded"
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager._find_document_row", return_value=(2, found_row)):
            update_document_status("DREG-001", "approved")
        written_cols = sorted(c for (_, c, _) in sheet.update_cell_calls)
        idx = {h: i + 1 for i, h in enumerate(CANONICAL_27)}
        self.assertEqual(set(written_cols), {idx["Status"], idx["Updated At"]})
        # Archive columns (24-27) must never be touched by this path.
        self.assertTrue(all(c < idx["Archived At"] for c in written_cols))

    def test_admin_update_touches_only_document_name_or_notes(self):
        from business_core.document_manager import update_document_admin_fields
        sheet = _sheet_with_headers(CANONICAL_27, data_rows=[["DREG-001"] + [""] * 26], col_count=27)
        found_row = dict(zip(CANONICAL_27, ["DREG-001"] + [""] * 26))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager._find_document_row", return_value=(2, found_row)):
            result = update_document_admin_fields("DREG-001", {"Notes": "updated note"})
        self.assertTrue(result["ok"])
        written_cols = [c for (_, c, _) in sheet.update_cell_calls]
        idx = {h: i + 1 for i, h in enumerate(CANONICAL_27)}
        self.assertTrue(set(written_cols).issubset({idx["Notes"], idx["Updated At"]}))

    def test_no_archive_metadata_accidentally_overwritten(self):
        from business_core.document_manager import update_document_admin_fields
        row_values = ["DREG-001"] + [""] * 26
        found_row = dict(zip(CANONICAL_27, row_values))
        found_row["Archived At"] = "2026-01-01 00:00:00 UTC"
        found_row["Archived By"] = "telegram:12345"
        sheet = _sheet_with_headers(CANONICAL_27, data_rows=[row_values], col_count=27)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager._find_document_row", return_value=(2, found_row)):
            update_document_admin_fields("DREG-001", {"Notes": "unrelated edit"})
        idx = {h: i + 1 for i, h in enumerate(CANONICAL_27)}
        archived_cols = {idx["Archived At"], idx["Archived By"], idx["Archive Reason"], idx["Previous Status"]}
        written_cols = {c for (_, c, _) in sheet.update_cell_calls}
        self.assertEqual(written_cols & archived_cols, set())


# ────────────────────────────────────────────────────────────
# 34-35. Sibling schemas unchanged
# ────────────────────────────────────────────────────────────

class TestSiblingSchemasUnchanged(unittest.TestCase):
    def test_document_content_schema_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)

    def test_document_field_reviews_schema_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["document_field_reviews"], [
            "Review ID", "Mutation ID", "Document ID", "Business ID", "Field Name",
            "AI Value", "Confirmed Value", "Decision", "Actor", "Reviewed At",
            "Review Version", "Source Analysis Completed At",
        ])


if __name__ == "__main__":
    unittest.main()
