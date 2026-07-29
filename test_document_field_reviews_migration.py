"""
Phase 16B.3: tests for migrate_document_field_reviews.py — controlled,
one-time creation of the DOCUMENT_FIELD_REVIEWS append-only audit-trail
sheet. Never relies on get_business_sheet()'s implicit auto-create
side effect being triggered by anything OTHER than this script itself.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


CANONICAL_HEADERS = [
    "Review ID", "Mutation ID", "Document ID", "Business ID", "Field Name",
    "AI Value", "Confirmed Value", "Decision", "Actor", "Reviewed At",
    "Review Version", "Source Analysis Completed At",
]


def _fresh_migration():
    for key in list(sys.modules.keys()):
        if "business_core" in key or key == "migrate_document_field_reviews":
            del sys.modules[key]
    import migrate_document_field_reviews as m
    return m


class _FakeSheet:
    def __init__(self, headers):
        self._headers = list(headers)

    def row_values(self, row):
        return list(self._headers) if row == 1 else []


class TestAnalyzeSheetState(unittest.TestCase):
    def test_sheet_does_not_exist(self):
        m = _fresh_migration()
        with patch("business_core.sheets.business_sheet_exists", return_value=False), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}):
            state = m.analyze_sheet_state()
        self.assertFalse(state["exists"])
        self.assertIsNone(state["headers"])
        self.assertIsNone(state["headers_match"])

    def test_sheet_exists_with_correct_headers(self):
        m = _fresh_migration()
        sheet = _FakeSheet(CANONICAL_HEADERS)
        with patch("business_core.sheets.business_sheet_exists", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}):
            state = m.analyze_sheet_state()
        self.assertTrue(state["exists"])
        self.assertTrue(state["headers_match"])

    def test_sheet_exists_with_wrong_headers(self):
        m = _fresh_migration()
        sheet = _FakeSheet(["Wrong", "Headers"])
        with patch("business_core.sheets.business_sheet_exists", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}):
            state = m.analyze_sheet_state()
        self.assertTrue(state["exists"])
        self.assertFalse(state["headers_match"])


class TestApplyCreation(unittest.TestCase):
    def test_creates_with_exact_canonical_headers(self):
        """п.12."""
        m = _fresh_migration()
        sheet = _FakeSheet(CANONICAL_HEADERS)  # simulates auto-create having already populated headers
        state = {"exists": False, "headers": None, "canonical_headers": CANONICAL_HEADERS, "headers_match": None}
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = m.apply_creation(state)
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["headers"], CANONICAL_HEADERS)

    def test_idempotent_when_already_present(self):
        """п.13."""
        m = _fresh_migration()
        state = {"exists": True, "headers": CANONICAL_HEADERS, "canonical_headers": CANONICAL_HEADERS,
                  "headers_match": True}
        result = m.apply_creation(state)
        self.assertEqual(result["status"], "ALREADY_PRESENT")

    def test_existing_mismatch_fails_closed_never_overwrites(self):
        m = _fresh_migration()
        state = {"exists": True, "headers": ["Wrong"], "canonical_headers": CANONICAL_HEADERS,
                  "headers_match": False}
        result = m.apply_creation(state)
        self.assertEqual(result["status"], "SCHEMA_MISMATCH")

    def test_creation_failure_does_not_leave_misleading_success(self):
        """п.14: if creation raises, status must be CREATION_FAILED,
        never anything implying success."""
        m = _fresh_migration()
        state = {"exists": False, "headers": None, "canonical_headers": CANONICAL_HEADERS, "headers_match": None}
        with patch("business_core.sheets.get_business_sheet", side_effect=Exception("API down")):
            result = m.apply_creation(state)
        self.assertEqual(result["status"], "CREATION_FAILED")
        self.assertIsNotNone(result["error"])

    def test_creation_headers_mismatch_after_create_also_fails(self):
        """A pathological case: get_business_sheet() 'succeeds' but the
        resulting headers somehow don't match — never silently reported
        as CREATED."""
        m = _fresh_migration()
        sheet = _FakeSheet(["Something", "Else"])
        state = {"exists": False, "headers": None, "canonical_headers": CANONICAL_HEADERS, "headers_match": None}
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = m.apply_creation(state)
        self.assertEqual(result["status"], "CREATION_FAILED")


class TestMainDryRunVsLive(unittest.TestCase):
    def test_dry_run_never_creates(self):
        m = _fresh_migration()
        with patch("business_core.sheets.business_sheet_exists", return_value=False), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_field_reviews.py"]), \
             patch("business_core.sheets.get_business_sheet") as mock_get:
            rc = m.main()
        self.assertEqual(rc, 0)
        mock_get.assert_not_called()

    def test_live_with_confirmation_creates(self):
        m = _fresh_migration()
        sheet = _FakeSheet(CANONICAL_HEADERS)
        with patch("business_core.sheets.business_sheet_exists", return_value=False), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_field_reviews.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)

    def test_live_without_confirmation_does_not_create(self):
        m = _fresh_migration()
        with patch("business_core.sheets.business_sheet_exists", return_value=False), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_field_reviews.py", "--live"]), \
             patch("builtins.input", return_value="no"), \
             patch("business_core.sheets.get_business_sheet") as mock_get:
            rc = m.main()
        self.assertEqual(rc, 0)
        mock_get.assert_not_called()

    def test_mismatch_aborts_before_any_live_flag_check(self):
        m = _fresh_migration()
        sheet = _FakeSheet(["Wrong"])
        with patch("business_core.sheets.business_sheet_exists", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_field_reviews.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 1)

    def test_already_present_idempotent_no_op(self):
        m = _fresh_migration()
        sheet = _FakeSheet(CANONICAL_HEADERS)
        with patch("business_core.sheets.business_sheet_exists", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.BUSINESS_HEADERS", {"document_field_reviews": CANONICAL_HEADERS}), \
             patch("sys.argv", ["migrate_document_field_reviews.py", "--live"]), \
             patch("builtins.input", return_value="YES"):
            rc = m.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
