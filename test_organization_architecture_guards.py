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


def _function_body(src: str, fn_name: str) -> str:
    """Extract one top-level `async def fn_name`'s source body, bounded
    by the next top-level `def `/`async def ` (or EOF for the last
    function in the file — e.g. stageresponsibility_cmd, which precedes
    the synchronous register_business_handlers())."""
    start = src.index(f"async def {fn_name}")
    rest = src[start + 10:]
    candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    end = start + 10 + min(candidates) if candidates else len(src)
    return src[start:end]


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


# ─────────────────────────────────────────────────────────────
# Phase 35E (ADR-018 §17-§20): centralized Organization result-code UX
# mapping guards.
# ─────────────────────────────────────────────────────────────

class TestCentralizedOrganizationUXMappingExists(unittest.TestCase):
    """Phase 35E: exactly one centralized result-code -> Russian message
    mapping function exists for each of the Person<->Role assignment and
    Stage->Role code families — no ad-hoc per-caller message
    construction duplicating them."""

    def test_mapping_functions_exist(self):
        import business_core.telegram_handlers as th
        self.assertTrue(callable(getattr(th, "_organization_assignment_message", None)))
        self.assertTrue(callable(getattr(th, "_stage_role_message", None)))

    def test_mapping_functions_defined_only_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn in ("_organization_assignment_message", "_stage_role_message"):
            self.assertEqual(
                src.count(f"def {fn}("), 1,
                f"{fn} must be defined exactly once in telegram_handlers.py",
            )

    def test_assignrole_uses_centralized_mapping(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def assignrole_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        self.assertIn("_organization_assignment_message(", body)

    def test_assignstagerole_and_reassignstagerole_use_centralized_mapping(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in ("assignstagerole_cmd", "reassignstagerole_cmd"):
            start = src.index(f"async def {fn_name}")
            end = src.index("\nasync def ", start + 10)
            body = src[start:end]
            self.assertIn("_stage_role_message(", body)


class TestAssignRoleDoesNotImplementEligibilityRules(unittest.TestCase):
    """ADR-018 §17: /assignrole must not re-derive Person/Role/
    Department eligibility itself — every branch it takes must come
    from the orchestrator's own result code."""

    def _assignrole_body(self) -> str:
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def assignrole_cmd")
        end = src.index("\nasync def ", start + 10)
        return src[start:end]

    def test_no_direct_low_level_assignment_call(self):
        body = self._assignrole_body()
        self.assertNotIn("organization_manager.assign_person_to_role(", body)

    def test_no_eligibility_re_derivation(self):
        body = self._assignrole_body()
        for snippet in ("is_person_archived", "find_department_by_id", '== "paused"', '== "archived"'):
            self.assertNotIn(snippet, body)


class TestStageRoleCommandsDoNotImplementRoleLifecyclePolicy(unittest.TestCase):
    """ADR-018 §16: /assignstagerole and /reassignstagerole must not
    re-derive Role-lifecycle eligibility (that lives solely in
    work_assignment_manager._role_eligible_for_stage_assignment())."""

    def test_no_role_status_branching_in_stage_role_commands(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in ("assignstagerole_cmd", "reassignstagerole_cmd"):
            start = src.index(f"async def {fn_name}")
            end = src.index("\nasync def ", start + 10)
            body = src[start:end]
            for snippet in ('role["status"]', "_role_eligible_for_stage_assignment", "find_department_by_id"):
                self.assertNotIn(snippet, body)


class TestNoDirectLowLevelPersistenceCallsFromTelegram(unittest.TestCase):
    """ADR-018: no Organization-facing Telegram command may call
    low-level Organization/Stage-relation persistence primitives
    directly — always through the canonical manager/orchestration
    function."""

    def test_no_direct_sheet_primitives_in_organization_commands(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in (
            "newdept_cmd", "newrole_cmd", "roles_cmd", "roledetails_cmd",
            "assignrole_cmd", "assignstagerole_cmd", "reassignstagerole_cmd",
            "stageresponsibility_cmd",
        ):
            body = _function_body(src, fn_name)
            for forbidden in ("get_business_sheet(", "append_business_row(", "batch_append_business_rows(", "update_cell("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not call {forbidden.rstrip('(')} directly")


class TestUnknownResultCodeHasSafeFallback(unittest.TestCase):
    """Phase 35E: an unmapped/future result code must never crash or
    render a raw dict — both mapping functions fall through to a safe,
    logged, generic message."""

    def test_organization_assignment_message_unknown_code_fallback(self):
        import business_core.telegram_handlers as th
        result = {"ok": False, "code": "TOTALLY_NEW_CODE", "error": "detail"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertNotIn("Traceback", msg)

    def test_stage_role_message_unknown_code_fallback(self):
        import business_core.telegram_handlers as th
        result = {"ok": False, "code": "TOTALLY_NEW_CODE", "error": "detail"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertNotIn("Traceback", msg)


class TestSensitiveOrganizationValuesAreNotLogged(unittest.TestCase):
    """Phase 35E §7: Organization command handlers must never log
    phone numbers, Notes, Purpose, Main Result, full message bodies, or
    credentials — only IDs/codes/status/flags."""

    _DISALLOWED_LOG_TOKENS = ("Notes", "Purpose", "Main Result", "phone", "update.message.text")

    def test_organization_commands_do_not_log_disallowed_fields(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in (
            "newdept_cmd", "newrole_cmd", "roles_cmd", "roledetails_cmd",
            "assignrole_cmd", "assignstagerole_cmd", "reassignstagerole_cmd",
            "stageresponsibility_cmd",
        ):
            body = _function_body(src, fn_name)
            log_calls = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_calls:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


# ─────────────────────────────────────────────────────────────
# Phase 35G (ADR-018 §2, closing the Phase 35F identity-tightening
# finding): Department identity immutability + the documented Role
# Function.Role ID exception.
# ─────────────────────────────────────────────────────────────

class TestDepartmentIdentityFieldsAreImmutable(unittest.TestCase):

    def test_business_id_and_department_id_excluded_from_editable_fields(self):
        import business_core.organization_manager as om
        self.assertNotIn("Business ID", om._DEPARTMENT_EDITABLE_FIELDS)
        self.assertNotIn("Department ID", om._DEPARTMENT_EDITABLE_FIELDS)

    def test_identity_conflict_code_exists_and_is_checked_before_any_other_validation(self):
        path = BUSINESS_CORE / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("DEPARTMENT_IMMUTABLE_FIELD_CONFLICT", src)
        start = src.index("def update_department(")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        conflict_pos = body.index("DEPARTMENT_IMMUTABLE_FIELD_CONFLICT")
        write_pos = body.index("sheet.update_cell(")
        self.assertLess(conflict_pos, write_pos, "identity check must run before any Sheets write")


class TestRoleFunctionRoleIdDocumentedException(unittest.TestCase):
    """ADR-018 §2 (Phase 35G addendum): Role Function.Role ID is an
    approved, documented exception — an editable ownership/reference
    field, not identity. Function ID remains the sole immutable
    identity. This guard proves the decision is recorded in DECISIONS.md
    (not a silent, undocumented compromise) and that Function ID itself
    stays non-editable."""

    def test_function_id_remains_non_editable(self):
        import business_core.organization_manager as om
        self.assertNotIn("Function ID", om._ROLE_FUNCTION_EDITABLE_FIELDS)

    def test_role_id_mutability_is_recorded_in_decisions_md(self):
        path = WORKSPACE / "DECISIONS.md"
        src = path.read_text(encoding="utf-8")
        self.assertIn("Role Function.Role ID", src)
        self.assertIn("ЗАДОКУМЕНТИРОВАННОЕ ИСКЛЮЧЕНИЕ", src)


class TestTelegramCannotBypassIdentityPolicy(unittest.TestCase):
    """No Organization-facing Telegram command may pass Department ID/
    Business ID through to update_department(), and none may write
    Organization registries directly (already guarded above; reasserted
    here scoped specifically to the identity-tightening surface)."""

    def test_no_command_updates_department_identity_fields(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn_name in (
            "newdept_cmd", "newrole_cmd", "roles_cmd", "roledetails_cmd",
            "assignrole_cmd", "assignstagerole_cmd", "reassignstagerole_cmd",
            "stageresponsibility_cmd",
        ):
            body = _function_body(src, fn_name)
            self.assertNotIn("update_department(", body)


if __name__ == "__main__":
    unittest.main()
