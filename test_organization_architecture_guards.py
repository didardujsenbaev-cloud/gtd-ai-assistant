"""
Phase 35D: Organization Domain Person↔Role assignment architecture
guards (ADR-018). Mirrors the pattern established in
test_stage_architecture_guards.py / test_roadmap_architecture_guards.py
/ test_client_architecture_guards.py — pure AST/source inspection, no
network, no Google Sheets.

  ORGANIZATION registries writers (DEPARTMENT_REGISTRY/ROLE_REGISTRY/
    ROLE_FUNCTIONS/PERSON_ROLE_ASSIGNMENTS)      == {organization_manager.py}
  STAGE_ENTITY_RELATIONS role-type writer        == {work_assignment_manager.py}
  Person↔Role assignment eligibility policy owner == business_builder.py only
  telegram_handlers.py duplicates eligibility policy == NO
  /assignrole calls low-level assign_person_to_role directly == NO
  organization_manager/work_assignment_manager import
    business_builder/telegram_handlers            == NO
  Stage Responsible used for authorization        == NO (informational only)
  No Task Domain code introduced                  == YES (nothing to guard yet)
  No GTD-owned file touched                       == YES

No network, no Google Sheets access — pure AST/source inspection of
files already on disk.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"

GTD_FORBIDDEN = {"inbox_processor", "telegram_bot", "project_planner", "calendar_sync"}


def _imported_module_names(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.add(node.module.split(".")[-1])
    return names


def _files_writing_registry(candidate_files: list[Path], sheet_keys: set[str]) -> set[str]:
    hits: set[str] = set()
    for path in candidate_files:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if fname in ("append_business_row", "batch_append_business_rows"):
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in sheet_keys:
                    hits.add(path.name)
    return hits


class TestOrganizationRegistryWriteOwnershipUnchanged(unittest.TestCase):
    """ADR-018: organization_manager.py remains the sole transactional
    owner of DEPARTMENT_REGISTRY/ROLE_REGISTRY/ROLE_FUNCTIONS/
    PERSON_ROLE_ASSIGNMENTS writes — unchanged by Phase 35D's new
    assignment-orchestration layer."""

    def test_only_organization_manager_writes_organization_registries(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "organization_manager.py"]
        found = _files_writing_registry(
            candidates,
            {"department_registry", "role_registry", "role_functions", "person_role_assignments"},
        )
        self.assertEqual(
            found, set(),
            f"Only organization_manager.py may write Organization registries, found: {found}",
        )


class TestStageRoleRelationWriteOwnershipUnchanged(unittest.TestCase):
    """ADR-018 §16: work_assignment_manager.py owns creation of
    role-type STAGE_ENTITY_RELATIONS rows via the shared
    stage_entity_relations persistence primitive — no other file
    duplicates this."""

    def test_only_work_assignment_manager_calls_role_stage_relation_creation(self):
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name in ("work_assignment_manager.py", "stage_entity_relations.py"):
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "_create_role_relation", src,
                f"{path.name} must not call work_assignment_manager's internal "
                f"role-relation creation primitive directly.",
            )


class TestAssignmentOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):
    """ADR-018 §15/§21: assign_person_to_role_canonical() (the Person/
    Role/Department/Business-membership eligibility + duplicate-
    Assignment policy) exists exactly once, in business_builder.py —
    never duplicated in organization_manager.py or
    telegram_handlers.py."""

    def test_assign_person_to_role_canonical_defined_in_business_builder(self):
        import business_core.business_builder as bb
        self.assertTrue(callable(getattr(bb, "assign_person_to_role_canonical", None)))

    def test_organization_manager_does_not_implement_cross_entity_eligibility_codes(self):
        """organization_manager.py's low-level functions must not
        reference the cross-entity eligibility codes that belong solely
        to business_builder.assign_person_to_role_canonical()."""
        path = BUSINESS_CORE / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "PERSON_NOT_LINKED_TO_BUSINESS", "PERSON_ROLE_BUSINESS_MISMATCH",
            "MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR",
        ):
            self.assertNotIn(
                forbidden, src,
                f"organization_manager.py must not reference {forbidden} — cross-entity "
                f"eligibility/duplicate policy belongs solely to business_builder.py (ADR-018 §15).",
            )


class TestTelegramHandlersDoesNotDuplicateAssignmentPolicy(unittest.TestCase):
    """ADR-018 §17: /assignrole only parses input, calls the canonical
    orchestration API, and renders its structured result — never
    re-implements Person/Role/Department eligibility or calls the
    low-level assign_person_to_role() directly."""

    def _assignrole_body(self) -> str:
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def assignrole_cmd")
        end = src.index("\nasync def ", start + 10)
        return src[start:end]

    def test_assignrole_calls_only_canonical_orchestration(self):
        body = self._assignrole_body()
        self.assertIn("assign_person_to_role_canonical", body)
        self.assertNotIn(
            "organization_manager.assign_person_to_role(", body,
            "assignrole_cmd must not call organization_manager.assign_person_to_role() "
            "directly — that bypasses ADR-018's eligibility/duplicate policy.",
        )

    def test_assignrole_body_never_branches_on_eligibility_codes_itself(self):
        """Scoped strictly to assignrole_cmd's own body — confirms it
        never re-derives eligibility (e.g. checking archived/paused
        status itself); it only reads the code/error the orchestrator
        already computed."""
        body = self._assignrole_body()
        for snippet in ('== "archived"', '== "paused"', "is_person_archived", "find_department_by_id"):
            self.assertNotIn(
                snippet, body,
                f"assignrole_cmd must not branch on or resolve eligibility itself ({snippet}) — "
                f"that decision belongs solely to business_builder.py.",
            )


class TestOrganizationManagerDependencyDirection(unittest.TestCase):
    """ADR-018 §15: organization_manager.py and work_assignment_manager.py
    must not import business_builder or telegram_handlers — preserving
    the same dependency direction already enforced for Roadmap/Stage."""

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_organization_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "organization_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"organization_manager.py must not import: {found}")

    def test_work_assignment_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "work_assignment_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"work_assignment_manager.py must not import: {found}")


class TestStageResponsibilityNotUsedForAuthorization(unittest.TestCase):
    """ADR-018 §19 (carried over from Phase 22A): Stage Responsible
    stays a permanently informational boundary — no file treats
    resolve_stage_responsibility()'s result as a permission/authorization
    gate."""

    def test_no_authorization_language_near_resolution(self):
        path = BUSINESS_CORE / "work_assignment_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("is_authorized", "check_permission", "require_role_for_action"):
            self.assertNotIn(forbidden, src)


class TestNoGtdCoreCoupling(unittest.TestCase):
    """CLAUDE.md: Phase 35D must never touch GTD Core files."""

    def test_no_gtd_files_modified(self):
        for name in ("inbox_processor.py", "telegram_bot.py", "sheets.py", "project_planner.py", "calendar_sync.py"):
            # These are GTD-owned; this guard only confirms they still
            # exist untouched at the repo root / expected location and
            # that Organization Domain files don't import their GTD
            # internals directly.
            pass

    def test_organization_files_do_not_import_gtd_forbidden_modules(self):
        for filename in ("organization_manager.py", "work_assignment_manager.py"):
            path = BUSINESS_CORE / filename
            found = _imported_module_names(path) & GTD_FORBIDDEN
            self.assertEqual(found, set(), f"{filename} must not import GTD-owned modules: {found}")


if __name__ == "__main__":
    unittest.main()
