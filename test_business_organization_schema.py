"""
Tests for Phase 21A — Organization Layer Schema Foundation.

Covers registration of the four new Organization Layer registries
(DEPARTMENT_REGISTRY, ROLE_REGISTRY, ROLE_FUNCTIONS,
PERSON_ROLE_ASSIGNMENTS) in business_core/sheets.py's three schema
dicts, per the Phase 20A -> 20A.6 approved architecture (revised:
Role has no "Business ID" column, no "Priority" column).

Schema-only phase — no manager code, no Telegram commands, no live
Sheets writes. See ARCHITECTURE.md / Organization Layer and
ENGINEERING_STANDARDS.md / Registry First for the governing rules.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

NEW_SHEET_KEYS = (
    "department_registry",
    "role_registry",
    "role_functions",
    "person_role_assignments",
)

EXPECTED_SHEET_NAMES = {
    "department_registry":    "DEPARTMENT_REGISTRY",
    "role_registry":          "ROLE_REGISTRY",
    "role_functions":         "ROLE_FUNCTIONS",
    "person_role_assignments": "PERSON_ROLE_ASSIGNMENTS",
}

EXPECTED_PREFIXES = {
    "department_registry":     "DEPT",
    "role_registry":           "ROLE",
    "role_functions":          "FUNC",
    "person_role_assignments": "PRA",
}

EXPECTED_HEADERS = {
    "department_registry": [
        "Department ID", "Business ID", "Department Name",
        "Parent Department ID", "Head Role ID", "Status", "Notes",
    ],
    "role_registry": [
        "Role ID", "Department ID", "Role Name", "Reports To Role ID",
        "Role Type", "Employment Model", "Status",
        "Purpose", "Main Result", "Notes",
    ],
    "role_functions": [
        "Function ID", "Role ID", "Function Category", "Function Name",
        "Description", "Frequency", "Criticality", "Can Delegate",
        "Status", "Sort Order",
    ],
    "person_role_assignments": [
        "Assignment ID", "Person ID", "Role ID",
        "Start Date", "End Date", "Assignment Type", "Status", "Notes",
    ],
}


def _fresh_sheets():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.sheets")


class TestSheetRegistry(unittest.TestCase):
    """Registration checks — mirrors TestSheetRegistry pattern from
    test_business_roadmap_templates.py."""

    def test_all_four_sheet_keys_present_in_sheet_names(self):
        s = _fresh_sheets()
        for key in NEW_SHEET_KEYS:
            self.assertIn(key, s.BUSINESS_SHEET_NAMES)

    def test_sheet_names_match_expected_tab_names(self):
        s = _fresh_sheets()
        for key, expected in EXPECTED_SHEET_NAMES.items():
            self.assertEqual(s.BUSINESS_SHEET_NAMES[key], expected)

    def test_all_four_sheet_keys_present_in_headers(self):
        s = _fresh_sheets()
        for key in NEW_SHEET_KEYS:
            self.assertIn(key, s.BUSINESS_HEADERS)

    def test_headers_exact_match(self):
        s = _fresh_sheets()
        for key, expected in EXPECTED_HEADERS.items():
            self.assertEqual(s.BUSINESS_HEADERS[key], expected)

    def test_all_four_sheet_keys_present_in_id_prefixes(self):
        s = _fresh_sheets()
        for key in NEW_SHEET_KEYS:
            self.assertIn(key, s._ID_PREFIXES)

    def test_id_prefixes_match_expected(self):
        s = _fresh_sheets()
        for key, expected in EXPECTED_PREFIXES.items():
            self.assertEqual(s._ID_PREFIXES[key], expected)


class TestNoPrefixCollision(unittest.TestCase):
    """Re-verify DEPT/ROLE/FUNC/PRA are still unused elsewhere, per the
    Phase 20A audit's collision check and Phase 21A's Definition of Done."""

    def test_new_prefixes_are_unique_across_all_registries(self):
        s = _fresh_sheets()
        all_prefixes = list(s._ID_PREFIXES.values())
        for prefix in EXPECTED_PREFIXES.values():
            self.assertEqual(
                all_prefixes.count(prefix), 1,
                f"prefix {prefix!r} must appear exactly once across _ID_PREFIXES",
            )

    def test_new_sheet_tab_names_are_unique(self):
        s = _fresh_sheets()
        all_names = list(s.BUSINESS_SHEET_NAMES.values())
        for name in EXPECTED_SHEET_NAMES.values():
            self.assertEqual(
                all_names.count(name), 1,
                f"tab name {name!r} must appear exactly once across BUSINESS_SHEET_NAMES",
            )


class TestNoBusinessIdOnRole(unittest.TestCase):
    """Locks in the Phase 20A revised decision: Role is global, no
    "Business ID" column, no "Priority" column."""

    def test_role_registry_has_no_business_id_column(self):
        s = _fresh_sheets()
        self.assertNotIn("Business ID", s.BUSINESS_HEADERS["role_registry"])

    def test_role_registry_has_no_priority_column(self):
        s = _fresh_sheets()
        self.assertNotIn("Priority", s.BUSINESS_HEADERS["role_registry"])

    def test_department_registry_business_id_is_optional_field_present(self):
        """Department MAY carry Business ID (unlike Role) — per §5 of the
        revised Phase 20A audit, Executive/Operations plausibly span all
        businesses, seeded blank, but the column itself is reserved."""
        s = _fresh_sheets()
        self.assertIn("Business ID", s.BUSINESS_HEADERS["department_registry"])


class TestNoRoleBusinessScopeOrKpiTable(unittest.TestCase):
    """Confirms deferred entities from Phase 20A are NOT built in 21A."""

    def test_no_role_business_scope_registry(self):
        s = _fresh_sheets()
        self.assertNotIn("role_business_scope", s.BUSINESS_SHEET_NAMES)

    def test_no_role_kpi_registry(self):
        s = _fresh_sheets()
        self.assertNotIn("role_kpi", s.BUSINESS_SHEET_NAMES)


class TestExistingRegistriesUntouched(unittest.TestCase):
    """Regression guard: Phase 21A must not alter any pre-existing sheet
    definition (Additive Evolution, ENGINEERING_STANDARDS.md)."""

    def test_stage_entity_relations_unchanged(self):
        s = _fresh_sheets()
        self.assertEqual(
            s.BUSINESS_HEADERS["stage_entity_relations"],
            [
                "Relation ID", "Template Stage ID", "Stage ID",
                "Entity Type", "Entity ID",
                "Required", "Blocking", "Minimum Count", "Status",
                "Created At", "Updated At",
            ],
        )

    def test_roadmap_stages_unchanged(self):
        s = _fresh_sheets()
        self.assertEqual(
            s.BUSINESS_HEADERS["roadmap_stages"],
            [
                "Stage ID", "Roadmap ID", "Order", "Name", "Status",
                "Due Date", "Completed At", "GTD Action ID",
                "Responsible", "Docs Required", "Docs Received", "Notes",
                "SOP IDs", "Checklist IDs", "Materials IDs",
                "Document Template IDs", "FAQ IDs",
                "Start Date", "Priority", "Blocking Reason",
                # /unblockstage fix: added so /unblockstage can restore
                # the exact pre-block status instead of always "pending"
                # (see test_business_stage_management.py::TestBlockUnblockStage).
                "Status Before Block",
            ],
        )

    def test_people_registry_unchanged_length(self):
        s = _fresh_sheets()
        self.assertEqual(len(s.BUSINESS_HEADERS["people_registry"]), 40)

    def test_total_registry_count_increased_by_exactly_four(self):
        s = _fresh_sheets()
        # 20 pre-existing (per Phase 18C-1 baseline) + 4 new (Phase 21A) = 24.
        # Phase 36C (ADR-019) legitimately added 2 more (task_registry,
        # task_assignments) = 26. Phase 38C (ADR-021) legitimately added
        # 2 more (checklist_instances, checklist_instance_items) = 28.
        # Phase 39C (ADR-022) legitimately added 3 more
        # (commercial_milestone_templates, payment_obligations,
        # payment_transactions) = 31. Phase 40C (ADR-023) legitimately
        # added 1 more (commercial_offers) = 32. Phase 41C (ADR-024)
        # legitimately added 1 more (leads) = 33. Phase 42C (ADR-025)
        # legitimately added 1 more (interaction_log) = 34. Phase 43
        # (Document Completion Gate) legitimately added 1 more
        # (stage_completion_overrides) = 35. Phase A (Stage Output
        # Foundation) legitimately added 2 more (stage_output_templates,
        # stage_output_instances) = 37. Dependencies Foundation
        # (2026-07-28, DECISIONS.md §14a) legitimately added 1 more
        # (template_stage_dependencies) = 38 — this point-in-time
        # closeout check is updated here rather than treated as a
        # durable count invariant (same precedent as the removed
        # git-diff-based TestAdditiveOnly guard in
        # test_business_organization_commands.py).
        self.assertEqual(len(s.BUSINESS_SHEET_NAMES), 38)
        self.assertEqual(len(s.BUSINESS_HEADERS), 38)


class TestGTDAndEnvUntouched(unittest.TestCase):

    def _check_no_gtd_imports(self, path: Path):
        if not path.exists():
            return
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN,
                                     f"{path.name} импортирует {a.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN,
                                 f"{path.name} импортирует {node.module!r}")

    def test_sheets_py_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "sheets.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_sheets()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
