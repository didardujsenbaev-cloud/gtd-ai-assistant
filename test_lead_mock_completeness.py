"""
Phase 41C (Lead / Sales Funnel Domain Foundation, ADR-024): PRS-003-class
regression guard for the Lead test surface — mirrors
test_payment_mock_completeness.py's/test_offer_mock_completeness.py's own
approach. Static, source-level guard that makes a missing hard-socket-
block registration structurally detectable, paired with conftest.py's
hard, mock-independent socket block as the real backstop.

No live Sheets/Drive/network access — pure AST/source inspection.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"

_LEAD_TEST_FILES = frozenset({
    "test_lead_manager.py",
    "test_business_lead_foundation.py",
    "test_lead_architecture_guards.py",
    "test_lead_mock_completeness.py",
    # Phase 41D (ADR-024): Lead caller (Telegram) UX test file.
    "test_lead_caller_ux.py",
})


class TestAllLeadTestFilesExist(unittest.TestCase):

    def test_every_registered_test_file_exists_on_disk(self):
        for filename in _LEAD_TEST_FILES:
            self.assertTrue((WORKSPACE / filename).exists(), f"{filename} does not exist")


class TestAllLeadTestFilesAreHardSocketBlocked(unittest.TestCase):

    def test_all_lead_files_registered_in_conftest(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        missing = [f for f in _LEAD_TEST_FILES if f not in conftest_src]
        self.assertEqual(missing, [], f"not registered in conftest.py's hard socket-block set: {missing}")

    def test_lead_domain_frozenset_included_in_hard_block(self):
        """Structural check that the new frozenset is actually unioned
        into _HARD_SOCKET_BLOCK_TEST_FILES, not merely defined and
        forgotten."""
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("_LEAD_DOMAIN_TEST_FILES", conftest_src)
        union_start = conftest_src.index("_HARD_SOCKET_BLOCK_TEST_FILES = (")
        union_end = conftest_src.index(")", union_start)
        union_body = conftest_src[union_start:union_end]
        self.assertIn("_LEAD_DOMAIN_TEST_FILES", union_body)


class TestLeadManagerHasNoDirectNetworkAccess(unittest.TestCase):

    def test_lead_manager_only_depends_on_sheets(self):
        path = BUSINESS_CORE / "lead_manager.py"
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

    def test_lead_manager_never_constructs_its_own_sheets_client(self):
        """Writes are only safe because every Sheets object is obtained
        via business_core.sheets.get_business_sheet() — itself fully
        mockable. What must never happen is lead_manager.py
        authenticating or opening a spreadsheet on its own."""
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        forbidden_calls = ("gspread.authorize(", "gspread.service_account(", ".open_by_key(", "Credentials.from_service_account")
        hits = [forbidden for forbidden in forbidden_calls if forbidden in src]
        self.assertEqual(hits, [], f"lead_manager.py bypassing get_business_sheet() with its own client: {hits}")

    def test_lead_manager_reads_sheets_only_through_get_business_sheet(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        if "update_cell(" in src or "append_row(" in src or "get_all_values(" in src:
            self.assertIn("get_business_sheet", src, "lead_manager.py performs a Sheets operation without ever calling get_business_sheet()")


if __name__ == "__main__":
    unittest.main()
