"""
Phase 16B.6.1: Railway Deploy Package Hardening.

Narrow, static contract test for .railwayignore itself — this does NOT
emulate Railway's Rust `ignore`-crate matching engine (fnmatch/pathlib
are not guaranteed equivalent for **, directory-only patterns,
negation, precedence, or rooted patterns — see the audit that preceded
this file). It only asserts facts about the literal text of
.railwayignore and basic git-tracking state, both intentionally narrow
and honest about what they do and don't prove (see §9 risk note: full
bundle verification is only possible via an actual `railway up`).

This file reads ONLY .railwayignore — never SYSTEM_CONSTITUTION.md,
never any secret file.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent
RAILWAYIGNORE = REPO_ROOT / ".railwayignore"


def _lines():
    text = RAILWAYIGNORE.read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()]


def _active_lines():
    return [line for line in _lines() if line and not line.startswith("#")]


class TestRailwayignoreExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(RAILWAYIGNORE.is_file())


class TestRailwayignoreContract(unittest.TestCase):
    def setUp(self):
        self.active = _active_lines()

    def test_system_constitution_listed_as_its_own_active_rule(self):
        self.assertIn("SYSTEM_CONSTITUTION.md", self.active)

    def test_git_directory_listed(self):
        self.assertIn(".git", self.active)

    def test_git_contents_listed(self):
        self.assertIn(".git/**", self.active)

    def test_no_wildcard_markdown_rule(self):
        self.assertNotIn("*.md", self.active)
        for line in self.active:
            self.assertFalse(line.endswith("*.md"), f"unexpected markdown wildcard: {line!r}")

    def test_no_wildcard_python_rule(self):
        self.assertNotIn("*.py", self.active)
        for line in self.active:
            self.assertFalse(line.endswith("*.py"), f"unexpected python wildcard: {line!r}")

    def test_no_business_core_wildcard_rule(self):
        for line in self.active:
            self.assertFalse(line.startswith("business_core"), f"unexpected business_core rule: {line!r}")

    def test_requirements_txt_not_listed(self):
        self.assertNotIn("requirements.txt", self.active)

    def test_procfile_not_listed(self):
        self.assertNotIn("Procfile", self.active)

    def test_start_py_not_listed(self):
        self.assertNotIn("start.py", self.active)

    def test_no_repository_root_wildcard_rule(self):
        for line in self.active:
            self.assertNotIn(line, ("*", "**", "/*", "/**", "."))

    def test_no_negation_rules(self):
        """A '!' negation rule could theoretically re-include
        SYSTEM_CONSTITUTION.md after an earlier broader exclusion —
        this file has none, and this guards against one being added
        without deliberate review."""
        for line in self.active:
            self.assertFalse(line.startswith("!"), f"unexpected negation rule: {line!r}")

    def test_exactly_three_active_rules(self):
        """Keeps the file minimal/additive per Phase 16B.6.1 §1 — a
        change to this count should be a deliberate, reviewed edit."""
        self.assertEqual(len(self.active), 3)


class TestSystemConstitutionGitState(unittest.TestCase):
    """Confirms tracking state via git plumbing only — never opens
    SYSTEM_CONSTITUTION.md itself."""

    def test_system_constitution_not_tracked(self):
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "SYSTEM_CONSTITUTION.md"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_system_constitution_present_on_disk(self):
        self.assertTrue((REPO_ROOT / "SYSTEM_CONSTITUTION.md").is_file())

    def test_railwayignore_is_untracked_or_addable(self):
        """.railwayignore itself should be a normal trackable text
        file — not itself gitignored (which would prevent committing
        it)."""
        result = subprocess.run(
            ["git", "check-ignore", "-v", ".railwayignore"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
