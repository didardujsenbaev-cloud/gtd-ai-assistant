"""
Phase 17B — Identity & Access Control Foundation: schema + migration
script tests.

Covers: exact header lists/sheet names/ID prefixes for the four new
registries, existing schemas unchanged, and migrate_identity_registries.py
(dry-run/live sheet creation, header-mismatch fail-closed, idempotency,
owner-bootstrap gating). No live Google Sheets access — mocks only.
"""

from __future__ import annotations

import ast
import socket
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import migrate_identity_registries as mir

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"

# Phase 17B-IR1/IR2 incident-response guard: mirrors
# test_interaction_mock_completeness.py's exact pattern — a
# PRS-003-class regression check that a missing hard-socket-block
# registration is structurally detectable, paired with conftest.py's
# hard, mock-independent socket block as the real backstop. This
# registry itself was the incident's root cause (these two files were
# never added), so it is deliberately re-declared and cross-checked
# here, not merely trusted to remain correct in conftest.py.
_IDENTITY_TEST_FILES = frozenset({
    "test_identity_registry.py",
    "test_identity_domain.py",
})

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


# ────────────────────────────────────────────────────────────
# Phase 17B-IR1/IR2: incident-response socket-isolation guards
# ────────────────────────────────────────────────────────────

class TestIdentityTestFilesExist(unittest.TestCase):
    def test_every_registered_identity_test_file_exists_on_disk(self):
        for filename in _IDENTITY_TEST_FILES:
            self.assertTrue((WORKSPACE / filename).exists(), f"{filename} does not exist")


class TestIdentityTestFilesAreHardSocketBlocked(unittest.TestCase):
    def test_all_identity_files_registered_in_conftest(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        missing = [f for f in _IDENTITY_TEST_FILES if f not in conftest_src]
        self.assertEqual(missing, [], f"not registered in conftest.py's hard socket-block set: {missing}")

    def test_identity_domain_frozenset_included_in_hard_block(self):
        """Structural check that the new frozenset is actually unioned
        into _HARD_SOCKET_BLOCK_TEST_FILES, not merely defined and
        forgotten — this exact gap (defined-but-not-unioned, or simply
        never added at all) is what let Phase 17B-IR1 happen."""
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("_IDENTITY_DOMAIN_TEST_FILES", conftest_src)
        union_start = conftest_src.index("_HARD_SOCKET_BLOCK_TEST_FILES = (")
        union_end = conftest_src.index(")", union_start)
        union_body = conftest_src[union_start:union_end]
        self.assertIn("_IDENTITY_DOMAIN_TEST_FILES", union_body)

    def test_conftest_fixture_is_autouse(self):
        """The hard-block fixture must apply automatically to every
        test in a registered file, without any test needing to
        explicitly request it — an opt-in fixture would have failed to
        prevent the exact same incident."""
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        fixture_start = conftest_src.index("def _block_live_sockets_for_hardened_tests")
        preceding = conftest_src[:fixture_start]
        decorator_line = preceding.rstrip().splitlines()[-1]
        self.assertIn("autouse=True", decorator_line)


class TestIdentityDomainNetworkAttemptIsRejected(unittest.TestCase):
    """Proves the block is real and mock-independent: a genuine
    socket.connect() attempt made from within this test's own context
    (which IS one of the two registered files) must be rejected before
    any external call — never silently succeed, never silently no-op."""

    def test_real_socket_connect_attempt_is_blocked(self):
        with self.assertRaises(AssertionError) as ctx:
            socket.socket().connect(("8.8.8.8", 53))
        self.assertIn("live socket connection", str(ctx.exception))

    def test_real_socket_connect_ex_attempt_is_blocked(self):
        with self.assertRaises(AssertionError):
            socket.socket().connect_ex(("8.8.8.8", 53))

    def test_block_active_before_any_test_logic_runs(self):
        # By the time this test method body executes, the autouse
        # fixture has already replaced socket.socket.connect with the
        # module-level _blocked_connect — proven directly by identity,
        # not merely by the two behavioral tests above.
        import conftest
        self.assertIs(socket.socket.connect, conftest._blocked_connect)


class TestIdentityManagerHasNoDirectNetworkAccess(unittest.TestCase):
    """Mirrors test_interaction_mock_completeness.py's static guard —
    identity_manager.py must only ever reach Sheets through
    business_core.sheets.get_business_sheet(), never its own client,
    so mocking that one seam is always sufficient."""

    def test_identity_manager_only_depends_on_sheets(self):
        path = BUSINESS_CORE / "identity_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        forbidden_top_level = {"gspread", "requests", "socket", "telegram"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
        self.assertEqual(found & forbidden_top_level, set())

    def test_identity_manager_never_constructs_its_own_sheets_client(self):
        path = BUSINESS_CORE / "identity_manager.py"
        src = path.read_text(encoding="utf-8")
        forbidden_calls = ("gspread.authorize(", "gspread.service_account(", ".open_by_key(", "Credentials.from_service_account")
        hits = [forbidden for forbidden in forbidden_calls if forbidden in src]
        self.assertEqual(hits, [], f"identity_manager.py bypassing get_business_sheet() with its own client: {hits}")

    def test_identity_manager_reads_writes_sheets_only_through_get_business_sheet(self):
        path = BUSINESS_CORE / "identity_manager.py"
        src = path.read_text(encoding="utf-8")
        if "update_cell(" in src or "append_row(" in src or "get_all_values(" in src:
            self.assertIn("get_business_sheet", src, "identity_manager.py performs a Sheets operation without ever calling get_business_sheet()")


class TestFullSuiteOrderingWithModulePurgeFiles(unittest.TestCase):
    """Phase 17B-IR1's actual failure mode was specific to TestOwnerBootstrap:
    patch.object(im, ...) there patches attributes on the identity_manager
    module object imported at test-COLLECTION time, but
    business_builder.bootstrap_owner_from_env() does its own fresh
    `from business_core import identity_manager as im` INSIDE the
    function body at CALL time — if another test file purges
    business_core.* from sys.modules in between (e.g.
    test_business_document_upload.py's _fresh_th()), that inner import
    resolves to a different, freshly-re-executed module object than
    the one the test's patches modified, and the patches silently miss.

    This does not apply to the tests that call identity_manager
    functions directly (TestEmployeeLifecycle etc.) — those call the
    exact same module reference they patched, with no intervening
    fresh import, so patch.object there is safe. Only the
    TestOwnerBootstrap class (which exercises code with its own
    call-time re-import) needs the module-reload-safe string-based
    patch() form — verified here by scoping the check to that class's
    own source only."""

    def test_no_module_object_patch_object_in_owner_bootstrap_tests(self):
        src = (WORKSPACE / "test_identity_domain.py").read_text(encoding="utf-8")
        class_start = src.index("class TestOwnerBootstrap")
        next_class = src.index("\nclass ", class_start + 1)
        class_body = src[class_start:next_class]
        self.assertNotIn("patch.object(im,", class_body,
                          "TestOwnerBootstrap still uses patch.object(im, ...) — unsafe against "
                          "business_builder's call-time re-import; use patch(\"business_core.identity_manager.X\") instead")
        self.assertNotIn("patch.object(bb,", class_body,
                          "TestOwnerBootstrap still uses patch.object(bb, ...) against a module-level import")


if __name__ == "__main__":
    unittest.main()
