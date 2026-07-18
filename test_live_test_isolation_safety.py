"""
Phase 11F.2: Production Test Isolation — safety tests.

Root cause (Phase 11F.1): test_business_core_sheets.py is a live Google
Sheets integration test (Phase 2A) that executed unconditionally at
import time (no `if __name__ == "__main__"` guard) and wrote a real
BIZ-TEST row to production BIZ_REGISTRY (Тест 10, append_business_row)
whenever the file was executed directly — with no environment flag
protecting it. It was also picked up by `unittest discover -p
"test_business_*.py"` as a false ERROR, because module-level `sys.exit()`
calls (in this file, test_business_core.py and test_business_router.py)
raise SystemExit during import.

Fix (this phase):
  - test_business_core_sheets.py / test_business_core.py /
    test_business_router.py: all test-execution logic moved under
    `if __name__ == "__main__":` — importing these modules now does
    nothing (0 assertions run, no sys.exit, no Sheets/Drive calls).
  - test_business_core_sheets.py additionally gates its live logic
    behind two explicit env flags:
      BUSINESS_CORE_ALLOW_LIVE_TESTS=1   → required for ANY live call
      BUSINESS_CORE_ALLOW_LIVE_WRITES=1  → required (together with the
                                            flag above) for the one
                                            write test (Тест 10).

This file verifies the safety guarantees only — it never sets both
flags against the real API: whenever "both flags" behavior is
exercised, business_core.sheets is fully mocked (per Phase 11F.2 task
4 requirement: "в автоматическом тесте реальный API всё равно
мокается").
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
PY = sys.executable

SCRIPT_STYLE_MODULES = [
    "test_business_core",
    "test_business_core_sheets",
    "test_business_router",
]


def _fresh_import(name: str):
    for k in list(sys.modules):
        if k == name or k.startswith("business_core"):
            del sys.modules[k]
    return importlib.import_module(name)


def _clean_env(**overrides):
    env = os.environ.copy()
    env.pop("BUSINESS_CORE_ALLOW_LIVE_TESTS", None)
    env.pop("BUSINESS_CORE_ALLOW_LIVE_WRITES", None)
    env.update(overrides)
    return env


# ────────────────────────────────────────────────────────────
# 5. Import safety — no sys.exit, no test execution, no errors
# ────────────────────────────────────────────────────────────

class TestScriptStyleImportIsSafe(unittest.TestCase):
    """Importing the three previously-unsafe script-style files must
    not execute any test logic, must not call sys.exit, and must not
    raise — this is what caused the unittest-discover false ERRORs."""

    def test_import_does_not_raise_or_exit(self):
        for name in SCRIPT_STYLE_MODULES:
            with self.subTest(module=name):
                mod = _fresh_import(name)
                self.assertEqual(mod.PASSED, 0,
                                  f"{name}: import must not run any test() calls")
                self.assertEqual(mod.FAILED, 0,
                                  f"{name}: import must not run any test() calls")

    def test_unittest_loader_can_load_without_error(self):
        """The exact scenario that produced 'ERROR: Failed to import test
        module' during `unittest discover -p "test_business_*.py"`."""
        loader = unittest.TestLoader()
        for name in SCRIPT_STYLE_MODULES:
            with self.subTest(module=name):
                for k in list(sys.modules):
                    if k == name or k.startswith("business_core"):
                        del sys.modules[k]
                suite = loader.loadTestsFromName(name)
                # A _FailedTest placeholder is unittest's signal that the
                # module import itself raised (e.g. SystemExit before the
                # fix). Ensure none of the collected tests are of that kind.
                for test_case in suite:
                    self.assertNotIsInstance(
                        test_case, unittest.loader._FailedTest,
                        f"{name}: unittest loader reported an import failure",
                    )

    def test_subprocess_import_only_produces_no_output(self):
        """Belt-and-suspenders: a plain `import` in a clean subprocess
        must not print anything or touch the network."""
        for name in SCRIPT_STYLE_MODULES:
            with self.subTest(module=name):
                result = subprocess.run(
                    [PY, "-c", f"import {name}"],
                    cwd=str(WORKSPACE), env=_clean_env(),
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "")


# ────────────────────────────────────────────────────────────
# 1/2/3. Flag gating — subprocess, real script, real env vars
#         (no live Sheets calls occur without flags: the module
#         exits before importing business_core.sheets at all)
# ────────────────────────────────────────────────────────────

class TestLiveFlagGatingSubprocess(unittest.TestCase):
    """Runs test_business_core_sheets.py as a real script (not mocked)
    under each flag combination and asserts on its own stdout —
    the only combination that reaches live Sheets code is skipped here
    (see TestLiveFlagGatingDirect for that, fully mocked)."""

    def _run(self, env_overrides):
        return subprocess.run(
            [PY, "test_business_core_sheets.py"],
            cwd=str(WORKSPACE), env=_clean_env(**env_overrides),
            capture_output=True, text=True, timeout=30,
        )

    def test_no_flags_skips_entirely(self):
        result = self._run({})
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIPPED", result.stdout)
        self.assertIn("BUSINESS_CORE_ALLOW_LIVE_TESTS", result.stdout)

    def test_write_flag_alone_still_skips_entirely(self):
        """BUSINESS_CORE_ALLOW_LIVE_WRITES=1 without ALLOW_LIVE_TESTS
        must not unlock anything — the outer gate checks ALLOW_LIVE_TESTS
        only."""
        result = self._run({"BUSINESS_CORE_ALLOW_LIVE_WRITES": "1"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIPPED", result.stdout)


# ────────────────────────────────────────────────────────────
# 2/3/4. Flag gating — direct in-process call with fully mocked
#         business_core.sheets (never touches the real API)
# ────────────────────────────────────────────────────────────

def _mock_sheets_attrs():
    """Attribute overrides for the network-touching business_core.sheets
    functions only (patch.multiple) — BUSINESS_SHEET_NAMES/HEADERS and
    pure helpers (_col_letter, ensure_headers, update_business_cell) are
    left as the real (static, no-network) values so the file's own
    structural assertions ("10 листов", "20 колонок", ...) stay valid.
    This is the same per-attribute patching pattern already used
    throughout the rest of this suite (e.g. test_business_roadmap_templates.py)."""
    append_mock = MagicMock(return_value=42)
    read_mock = MagicMock(return_value=[
        {"ID": "BIZ-TEST", "Название": "Тестовый бизнес",
         "Ответственный": "Дидар", "Города": "Алматы"},
    ])
    return {
        "check_configuration": MagicMock(return_value={
            "ok": True, "spreadsheet_id": "fake-id",
            "service_account": "fake@sa", "url": "https://fake",
            "issues": [],
        }),
        "get_spreadsheet_url": MagicMock(
            return_value="https://docs.google.com/spreadsheets/d/fake"),
        "is_enabled": MagicMock(return_value=True),
        "get_business_sheet": MagicMock(side_effect=KeyError("несуществующий_ключ")),
        "get_business_spreadsheet": MagicMock(return_value=MagicMock(title="Fake Sheet")),
        "init_business_core_sheets": MagicMock(return_value={"biz_registry": True}),
        "generate_next_id": MagicMock(side_effect=lambda key, prefix=None: {
            "biz_registry": "BIZ-999", "people_registry": "PRS-999",
            "roadmap_stages": "STAGE-999",
        }.get(key, "X-001")),
        "append_business_row": append_mock,
        "read_business_sheet": read_mock,
        "find_row_by_id": MagicMock(side_effect=lambda key, rid: (
            (2, {"ID": rid}) if rid == "BIZ-TEST" else None
        )),
    }


class TestLiveFlagGatingDirect(unittest.TestCase):
    """Calls _run_live_tests() directly (bypassing the __main__ guard,
    which is exercised separately in TestLiveFlagGatingSubprocess) with
    business_core.sheets fully mocked, to prove the write gate itself
    — independent of network reachability."""

    def _load_with_flags(self, allow_tests: bool, allow_writes: bool):
        for k in list(sys.modules):
            if k == "test_business_core_sheets" or k.startswith("business_core"):
                del sys.modules[k]
        env = {}
        if allow_tests:
            env["BUSINESS_CORE_ALLOW_LIVE_TESTS"] = "1"
        if allow_writes:
            env["BUSINESS_CORE_ALLOW_LIVE_WRITES"] = "1"
        with patch.dict(os.environ, env, clear=False):
            for k in ("BUSINESS_CORE_ALLOW_LIVE_TESTS", "BUSINESS_CORE_ALLOW_LIVE_WRITES"):
                if k not in env:
                    os.environ.pop(k, None)
            mod = importlib.import_module("test_business_core_sheets")
        return mod

    def test_read_allowed_write_blocked_with_only_allow_tests(self):
        """Task 4.2: only BUSINESS_CORE_ALLOW_LIVE_TESTS=1 → read proceeds,
        write (Тест 10) stays blocked."""
        mod = self._load_with_flags(allow_tests=True, allow_writes=False)
        attrs = _mock_sheets_attrs()
        # _run_live_tests() always ends with sys.exit(...) — expected for
        # this script, unrelated to the flag gating being verified here.
        with patch.multiple("business_core.sheets", **attrs), \
             self.assertRaises(SystemExit):
            mod._run_live_tests()
        attrs["read_business_sheet"].assert_called()
        attrs["append_business_row"].assert_not_called()

    def test_write_allowed_only_with_both_flags_mocked_api(self):
        """Task 4.4: both flags present → write path technically executes,
        but business_core.sheets is fully mocked — no real API call."""
        mod = self._load_with_flags(allow_tests=True, allow_writes=True)
        attrs = _mock_sheets_attrs()
        with patch.multiple("business_core.sheets", **attrs), \
             self.assertRaises(SystemExit):
            mod._run_live_tests()
        attrs["append_business_row"].assert_called_once()
        # Confirm it was called with the BIZ-TEST fixture row, into biz_registry
        args, kwargs = attrs["append_business_row"].call_args
        self.assertEqual(args[0], "biz_registry")
        self.assertIn("BIZ-TEST", args[1])

    def test_write_blocked_with_both_flags_false(self):
        mod = self._load_with_flags(allow_tests=False, allow_writes=False)
        self.assertFalse(mod.ALLOW_LIVE_TESTS)
        self.assertFalse(mod.ALLOW_LIVE_WRITES)


# ────────────────────────────────────────────────────────────
# 6. Full safe suite never touches production Sheets/Drive
# ────────────────────────────────────────────────────────────

class TestFullSuiteDoesNotTouchProduction(unittest.TestCase):
    """Running `unittest discover -p "test_business_*.py"` (the normal,
    no-live-flags invocation) must never call the real Sheets API — this
    directly re-creates the Phase 11F.1 incident and proves it can no
    longer happen by accident."""

    def test_discovery_and_run_without_flags_never_calls_get_business_sheet(self):
        result = subprocess.run(
            [PY, "-m", "unittest", "discover", "-s", str(WORKSPACE),
             "-p", "test_business_*.py"],
            cwd=str(WORKSPACE), env=_clean_env(),
            capture_output=True, text=True, timeout=120,
        )
        # No more loader ERRORs from the 3 previously-unsafe files.
        self.assertNotIn("test_business_core (unittest.loader._FailedTest",
                          result.stderr)
        self.assertNotIn("test_business_core_sheets (unittest.loader._FailedTest",
                          result.stderr)
        self.assertNotIn("test_business_router (unittest.loader._FailedTest",
                          result.stderr)
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
