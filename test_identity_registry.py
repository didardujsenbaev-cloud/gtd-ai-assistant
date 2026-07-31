"""
Phase 17B — Identity & Access Control Foundation: schema + migration
script tests.

Covers: exact header lists/sheet names/ID prefixes for the four new
registries, existing schemas unchanged, and migrate_identity_registries.py
(dry-run/live sheet creation, header-mismatch fail-closed, idempotency,
owner-bootstrap gating). No live Google Sheets access — mocks only.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import migrate_identity_registries as mir

EMPLOYEE_HEADERS = [
    "Employee ID", "Person ID", "Display Label", "Status",
    "Created At", "Created By",
    "Activated At", "Activated By",
    "Disabled At", "Disabled By", "Disable Reason",
    "Notes",
]
TELEGRAM_IDENTITY_HEADERS = [
    "Telegram Identity ID", "Employee ID", "Telegram User ID", "Telegram Actor",
    "Status", "Linked At", "Linked By", "Revoked At", "Revoked By", "Revoke Reason",
]
ACCESS_ROLE_HEADERS = [
    "Access Role Assignment ID", "Employee ID", "Role", "Status",
    "Effective From", "Effective Until", "Assigned At", "Assigned By",
    "Revoked At", "Revoked By", "Revoke Reason",
]
ACCESS_SCOPE_HEADERS = [
    "Access Scope Assignment ID", "Employee ID", "Access Role Assignment ID",
    "Scope Type", "Business ID", "Object ID", "Status",
    "Effective From", "Effective Until", "Assigned At", "Assigned By",
    "Revoked At", "Revoked By", "Revoke Reason",
]


class TestSchemaDefinitions(unittest.TestCase):
    def test_employee_registry_headers(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["employee_registry"], EMPLOYEE_HEADERS)

    def test_telegram_identity_registry_headers(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["telegram_identity_registry"], TELEGRAM_IDENTITY_HEADERS)

    def test_access_role_assignments_headers(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["access_role_assignments"], ACCESS_ROLE_HEADERS)

    def test_access_scope_assignments_headers(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["access_scope_assignments"], ACCESS_SCOPE_HEADERS)

    def test_sheet_names(self):
        from business_core.sheets import BUSINESS_SHEET_NAMES
        self.assertEqual(BUSINESS_SHEET_NAMES["employee_registry"], "EMPLOYEE_REGISTRY")
        self.assertEqual(BUSINESS_SHEET_NAMES["telegram_identity_registry"], "TELEGRAM_IDENTITY_REGISTRY")
        self.assertEqual(BUSINESS_SHEET_NAMES["access_role_assignments"], "ACCESS_ROLE_ASSIGNMENTS")
        self.assertEqual(BUSINESS_SHEET_NAMES["access_scope_assignments"], "ACCESS_SCOPE_ASSIGNMENTS")

    def test_id_prefixes(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["employee_registry"], "EMP")
        self.assertEqual(_ID_PREFIXES["telegram_identity_registry"], "TGID")
        self.assertEqual(_ID_PREFIXES["access_role_assignments"], "ARA")
        self.assertEqual(_ID_PREFIXES["access_scope_assignments"], "ASA")

    def test_existing_document_schemas_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_registry"]), 27)
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)
        self.assertEqual(len(BUSINESS_HEADERS["document_field_reviews"]), 12)

    def test_no_existing_headers_changed_spotcheck(self):
        from business_core.sheets import BUSINESS_HEADERS
        # Spot-check a handful of unrelated, pre-existing registries to
        # confirm this phase touched only the four new dict entries.
        self.assertEqual(BUSINESS_HEADERS["people_registry"][0], "ID")
        self.assertEqual(BUSINESS_HEADERS["role_registry"][0], "Role ID")
        self.assertEqual(BUSINESS_HEADERS["channel_registry"][0], "ID")


class TestMigrationCheckRegistry(unittest.TestCase):
    def test_missing_sheet_detected(self):
        import gspread
        ss = MagicMock()
        ss.worksheet.side_effect = gspread.exceptions.WorksheetNotFound()
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss):
            plan = mir.check_registry("employee_registry")
        self.assertFalse(plan["exists"])
        self.assertEqual(plan["canonical_headers"], EMPLOYEE_HEADERS)

    def test_existing_sheet_matching_headers(self):
        sheet = MagicMock()
        sheet.row_values.return_value = EMPLOYEE_HEADERS
        ss = MagicMock()
        ss.worksheet.return_value = sheet
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss):
            plan = mir.check_registry("employee_registry")
        self.assertTrue(plan["exists"])
        self.assertTrue(plan["headers_match"])

    def test_existing_sheet_mismatched_headers(self):
        sheet = MagicMock()
        sheet.row_values.return_value = ["Wrong", "Headers"]
        ss = MagicMock()
        ss.worksheet.return_value = sheet
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss):
            plan = mir.check_registry("employee_registry")
        self.assertTrue(plan["exists"])
        self.assertFalse(plan["headers_match"])


class TestMigrationCreateRegistry(unittest.TestCase):
    def test_already_present_zero_writes(self):
        plan = {"exists": True, "headers_match": True, "existing_headers": EMPLOYEE_HEADERS,
                "canonical_headers": EMPLOYEE_HEADERS}
        with patch("business_core.sheets.get_business_sheet") as mock_get:
            result = mir.create_registry_if_missing("employee_registry", plan)
        self.assertEqual(result["status"], mir.STATUS_ALREADY_PRESENT)
        mock_get.assert_not_called()

    def test_header_mismatch_fails_closed(self):
        plan = {"exists": True, "headers_match": False, "existing_headers": ["Wrong"],
                "canonical_headers": EMPLOYEE_HEADERS}
        with patch("business_core.sheets.get_business_sheet") as mock_get:
            result = mir.create_registry_if_missing("employee_registry", plan)
        self.assertEqual(result["status"], mir.STATUS_HEADER_MISMATCH)
        mock_get.assert_not_called()

    def test_missing_sheet_created(self):
        plan = {"exists": False, "headers_match": False, "existing_headers": [],
                "canonical_headers": EMPLOYEE_HEADERS}
        sheet = MagicMock()
        sheet.row_values.return_value = EMPLOYEE_HEADERS
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = mir.create_registry_if_missing("employee_registry", plan)
        self.assertEqual(result["status"], mir.STATUS_CREATED)

    def test_creation_verification_failure(self):
        plan = {"exists": False, "headers_match": False, "existing_headers": [],
                "canonical_headers": EMPLOYEE_HEADERS}
        sheet = MagicMock()
        sheet.row_values.return_value = ["Something", "Else"]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = mir.create_registry_if_missing("employee_registry", plan)
        self.assertEqual(result["status"], mir.STATUS_VERIFICATION_FAILED)


class TestMigrationCLI(unittest.TestCase):
    def _mock_all_missing(self):
        import gspread
        ss = MagicMock()
        ss.worksheet.side_effect = gspread.exceptions.WorksheetNotFound()
        return ss

    def test_dry_run_default_zero_writes(self):
        ss = self._mock_all_missing()
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.sheets.get_business_sheet") as mock_get, \
             patch("sys.argv", ["prog"]):
            rc = mir.main()
        self.assertEqual(rc, 0)
        mock_get.assert_not_called()

    def test_live_without_yes_is_dry_run(self):
        ss = self._mock_all_missing()
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.sheets.get_business_sheet") as mock_get, \
             patch("sys.argv", ["prog", "--live", "no"]):
            rc = mir.main()
        self.assertEqual(rc, 0)
        mock_get.assert_not_called()

    def test_live_yes_creates_four_sheets(self):
        ss = self._mock_all_missing()
        created_sheet = MagicMock()

        def _get_business_sheet(key):
            headers = {
                "employee_registry": EMPLOYEE_HEADERS,
                "telegram_identity_registry": TELEGRAM_IDENTITY_HEADERS,
                "access_role_assignments": ACCESS_ROLE_HEADERS,
                "access_scope_assignments": ACCESS_SCOPE_HEADERS,
            }[key]
            s = MagicMock()
            s.row_values.return_value = headers
            return s

        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.sheets.get_business_sheet", side_effect=_get_business_sheet) as mock_get, \
             patch("sys.argv", ["prog", "--live", "YES"]):
            rc = mir.main()
        self.assertEqual(rc, 0)
        self.assertEqual(mock_get.call_count, 4)

    def test_bootstrap_owner_requires_live(self):
        with patch("sys.argv", ["prog", "--bootstrap-owner", "YES"]):
            rc = mir.main()
        self.assertEqual(rc, 1)

    def test_bootstrap_owner_not_run_without_flag(self):
        ss = self._mock_all_missing()

        def _get_business_sheet(key):
            headers = {
                "employee_registry": EMPLOYEE_HEADERS,
                "telegram_identity_registry": TELEGRAM_IDENTITY_HEADERS,
                "access_role_assignments": ACCESS_ROLE_HEADERS,
                "access_scope_assignments": ACCESS_SCOPE_HEADERS,
            }[key]
            s = MagicMock()
            s.row_values.return_value = headers
            return s

        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.sheets.get_business_sheet", side_effect=_get_business_sheet), \
             patch("business_core.business_builder.bootstrap_owner_from_env") as mock_bootstrap, \
             patch("sys.argv", ["prog", "--live", "YES"]):
            rc = mir.main()
        self.assertEqual(rc, 0)
        mock_bootstrap.assert_not_called()

    def test_header_mismatch_blocks_bootstrap(self):
        sheet = MagicMock()
        sheet.row_values.return_value = ["Wrong"]
        ss = MagicMock()
        ss.worksheet.return_value = sheet
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.business_builder.bootstrap_owner_from_env") as mock_bootstrap, \
             patch("sys.argv", ["prog", "--live", "YES", "--bootstrap-owner", "YES"]), \
             patch("builtins.input", return_value="YES"):
            rc = mir.main()
        self.assertEqual(rc, 1)
        mock_bootstrap.assert_not_called()

    def test_repeated_run_idempotent(self):
        headers_by_name = {
            "EMPLOYEE_REGISTRY": EMPLOYEE_HEADERS,
            "TELEGRAM_IDENTITY_REGISTRY": TELEGRAM_IDENTITY_HEADERS,
            "ACCESS_ROLE_ASSIGNMENTS": ACCESS_ROLE_HEADERS,
            "ACCESS_SCOPE_ASSIGNMENTS": ACCESS_SCOPE_HEADERS,
        }

        def _worksheet(name):
            s = MagicMock()
            s.row_values.return_value = headers_by_name[name]
            return s

        ss = MagicMock()
        ss.worksheet.side_effect = _worksheet
        with patch("business_core.sheets.get_business_spreadsheet", return_value=ss), \
             patch("business_core.sheets.get_business_sheet") as mock_get, \
             patch("sys.argv", ["prog", "--live", "YES"]):
            rc1 = mir.main()
            rc2 = mir.main()
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        mock_get.assert_not_called()  # all four already present with matching headers


if __name__ == "__main__":
    unittest.main()
