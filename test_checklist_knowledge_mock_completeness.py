"""
Phase 38A.1 (Checklist Domain test isolation closure): PRS-003-class
regression guard for the Checklist/Knowledge test surface.

Phase 38A's architecture audit found test_business_knowledge_core.py
and 12 of 16 test_seed_izhs_*.py files missing from conftest.py's hard
socket-block set — the exact same precedent-violating gap Phase 35B/
36C/37B found for Organization/Task/Document. This is a static,
source-level guard (mirrors test_client_newclient_mock_completeness.py's
own approach) that makes that specific class of regression structurally
detectable, paired with conftest.py's hard, mock-independent socket
block as the real backstop.

No live Sheets/Drive/network access — pure AST/source inspection.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
SEEDS_DIR = WORKSPACE / "business_core" / "seeds"

_SEED_TEST_FILES = frozenset({
    "test_seed_izhs_almaty_demolition.py",
    "test_seed_izhs_almaty_legalization.py",
    "test_seed_izhs_almaty_newbuild.py",
    "test_seed_izhs_almaty_outbuilding.py",
    "test_seed_izhs_almaty_standard_reconstruction.py",
    "test_seed_izhs_almaty_standard_reconstruction_finished_smr.py",
    "test_seed_izhs_astana_demolition.py",
    "test_seed_izhs_astana_newbuild.py",
    "test_seed_izhs_astana_outbuilding.py",
    "test_seed_izhs_astana_reconstruction.py",
    "test_seed_izhs_commercial_milestones.py",
    "test_seed_izhs_commercial_milestones_sop.py",
    "test_seed_izhs_commercial_offer_templates.py",
    "test_seed_izhs_intake_sop.py",
    "test_seed_izhs_router_sop.py",
    "test_seed_izhs_whatsapp_templates.py",
})

_KNOWLEDGE_TEST_FILES = frozenset({"test_business_knowledge_core.py"})

_ALL_RELEVANT_TEST_FILES = _SEED_TEST_FILES | _KNOWLEDGE_TEST_FILES


def _seed_module_names() -> frozenset:
    return frozenset(
        p.stem for p in SEEDS_DIR.glob("seed_izhs_*.py")
    )


class TestAllSeedTestFilesExist(unittest.TestCase):
    """Sanity check: the registration list below matches the actual
    seed test files/modules on disk — catches a future seed module
    added without its guard-list entry, or a stale entry for a since-
    removed one."""

    def test_every_seed_module_has_a_registered_test_file(self):
        seed_modules = _seed_module_names()
        expected_test_files = {f"test_{name}.py" for name in seed_modules}
        missing = expected_test_files - _SEED_TEST_FILES
        self.assertEqual(missing, set(), f"seed modules with no registered isolation-guard entry: {missing}")

    def test_no_stale_seed_test_file_entries(self):
        seed_modules = _seed_module_names()
        expected_test_files = {f"test_{name}.py" for name in seed_modules}
        stale = _SEED_TEST_FILES - expected_test_files
        self.assertEqual(stale, set(), f"registered seed test files with no corresponding seed module: {stale}")

    def test_every_seed_test_file_exists_on_disk(self):
        for filename in _ALL_RELEVANT_TEST_FILES:
            self.assertTrue((WORKSPACE / filename).exists(), f"{filename} does not exist")


class TestAllRelevantTestFilesAreHardSocketBlocked(unittest.TestCase):
    """The actual PRS-003-class regression check: every file that
    tests a Checklist/Knowledge seed script or business_core/
    knowledge_manager.py must be in conftest.py's hard socket-block
    set — this is the guard Phase 38A found missing."""

    def test_all_relevant_files_registered_in_conftest(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        missing = [f for f in _ALL_RELEVANT_TEST_FILES if f not in conftest_src]
        self.assertEqual(missing, [], f"not registered in conftest.py's hard socket-block set: {missing}")

    def test_checklist_knowledge_frozenset_included_in_hard_block(self):
        """Structural check that the new frozenset is actually unioned
        into _HARD_SOCKET_BLOCK_TEST_FILES, not merely defined and
        forgotten."""
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("_CHECKLIST_KNOWLEDGE_TEST_FILES", conftest_src)
        # The union expression itself must reference the new set.
        union_start = conftest_src.index("_HARD_SOCKET_BLOCK_TEST_FILES = (")
        union_end = conftest_src.index(")", union_start)
        union_body = conftest_src[union_start:union_end]
        self.assertIn("_CHECKLIST_KNOWLEDGE_TEST_FILES", union_body)


class TestNoLowLevelBypassInSeedModules(unittest.TestCase):
    """Every seed script must reach Sheets exclusively through
    business_core.sheets — no direct gspread/requests/socket usage
    that could bypass the mock surface entirely."""

    def test_no_direct_network_library_imports(self):
        hits = []
        for path in SEEDS_DIR.glob("seed_izhs_*.py"):
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                if any(n in ("gspread", "requests", "socket", "urllib3", "httplib2") for n in names):
                    hits.append(path.name)
        self.assertEqual(hits, [], f"seed modules with direct network-library imports: {hits}")

    def test_seed_modules_never_construct_their_own_sheets_client(self):
        """Writes (append_business_row, or update_cell/append_row on a
        Worksheet object) are only safe because every such object is
        obtained via business_core.sheets.get_business_sheet() —
        itself fully mockable. What must never happen is a seed
        module authenticating or opening a spreadsheet on its own
        (gspread.authorize/open_by_key), which would bypass that
        single mockable choke point entirely."""
        forbidden_calls = ("gspread.authorize(", "gspread.service_account(", ".open_by_key(", "Credentials.from_service_account")
        hits = []
        for path in SEEDS_DIR.glob("seed_izhs_*.py"):
            src = path.read_text(encoding="utf-8")
            for forbidden in forbidden_calls:
                if forbidden in src:
                    hits.append((path.name, forbidden))
        self.assertEqual(hits, [], f"seed modules bypassing get_business_sheet() with their own client: {hits}")

    def test_seed_modules_read_sheets_only_through_get_business_sheet(self):
        for path in SEEDS_DIR.glob("seed_izhs_*.py"):
            src = path.read_text(encoding="utf-8")
            if "update_cell(" in src or "append_row(" in src or "get_all_values(" in src:
                self.assertIn(
                    "get_business_sheet", src,
                    f"{path.name} performs a Sheets operation without ever calling get_business_sheet()",
                )


class TestKnowledgeManagerHasNoDirectNetworkAccess(unittest.TestCase):

    def test_knowledge_manager_only_depends_on_sheets(self):
        path = WORKSPACE / "business_core" / "knowledge_manager.py"
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


if __name__ == "__main__":
    unittest.main()
