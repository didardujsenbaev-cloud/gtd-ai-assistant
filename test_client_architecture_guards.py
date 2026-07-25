"""
Phase 31D: Client Domain (Person Manager) architecture guards — fully
strict.

Source of truth: DECISIONS.md ADR-015 (Phase 31B). Mirrors the pattern
established in test_object_architecture_guards.py / test_service_
architecture_guards.py / test_roadmap_architecture_guards.py — pure
AST/source inspection, no network, no Sheets.

Phase 31C shipped these guards with a transitional debt allowlist
(telegram_handlers.py's /clients, /bc, legacy /newroadmap still reading
PEOPLE_REGISTRY raw; /newclient still using the find_existing_person/
find_duplicate_person compatibility wrappers; /newobject still
auto-linking Person to Business). Phase 31D migrated every one of those
callers onto the canonical person_manager API — this file now enforces
the fully-strict target architecture, with only ONE permanent,
file-scoped exception remaining:

  PEOPLE_REGISTRY_RUNTIME_WRITERS == {person_manager.py}
  TELEGRAM_HANDLERS_WRITE_PEOPLE_REGISTRY_DIRECTLY == NO
  TELEGRAM_HANDLERS_READ_PEOPLE_REGISTRY_DIRECTLY == NO
  BUSINESS_BUILDER_WRITES_PEOPLE_REGISTRY_DIRECTLY == NO
  PERSON_IDENTITY_HAS_SINGLE_IMPLEMENTATION == YES
  NEWCLIENT_USES_CANONICAL_PERSON_IDENTITY_API == YES
  PERSON_IDENTITY_NEVER_RETURNS_ARBITRARY_FIRST_MATCH == YES (at the
    resolve_person_identity level — see behavioral tests in
    test_business_person_identity_resolver.py)
  NAME_ONLY_MATCH_IS_NOT_AUTOMATIC_REUSE == YES
  MULTIPLE_PERSON_MATCHES_ARE_REJECTED == YES
  CLIENT_LISTING_USES_CANONICAL_HELPER == YES
  CLIENT_ROLE_DETECTION_USES_EXACT_NORMALIZED_VALUES == YES
  PERSON_BUSINESS_LINK_MUTATION_IS_ADD_ONLY == YES
  OBJECT_CREATION_REQUIRES_CLIENT_ROLE == YES
  OBJECT_CREATION_REQUIRES_PERSON_LINKED_TO_OBJECT_BUSINESS == YES
  OBJECT_CREATION_AUTO_LINKS_PERSON_TO_BUSINESS == NO
  ARCHIVED_PERSON_CAN_OWN_NEW_OBJECT == NO
  CLIENT_DRIVE_CREATION_IS_RETRY_SAFE == YES
  MULTI_BUSINESS_CLIENT_DRIVE_CREATES_NO_UNTRACKED_FOLDER == YES
  PERSON_MANAGER_DEPENDENCY_CYCLE_EXISTS == NO

Approved exception (permanent, file/function-scoped, NOT a blanket
allowlist):
  - inbox_bridge.py: raw PEOPLE_REGISTRY read. This is a GTD-boundary
    file that may not be modified under any Business Core Client Domain
    phase (CLAUDE.md GTD Core rule) — its removal is permanently out of
    scope, not merely deferred.
No other file/function may write or read PEOPLE_REGISTRY directly.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"


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


def _calls_touching_sheet_key(path: Path, func_names: set[str], sheet_key: str) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if fname not in func_names:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == sheet_key:
            hits.append(f"{fname}:{node.lineno}")
    return hits


def _calls_in_source(src: str, names: set[str]) -> set[str]:
    tree = ast.parse(src)
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if fname in names:
                hits.add(fname)
    return hits


WRITE_FUNC_NAMES = {"append_business_row", "batch_append_business_rows"}
READ_FUNC_NAMES = {"read_business_sheet", "get_business_sheet", "find_row_by_id"}

_APPROVED_EXCEPTION_FILES = {"inbox_bridge.py"}


class TestPersonManagerDependencyDirection(unittest.TestCase):
    """person_manager -> business_core.sheets only (ADR-015 Decision 13)."""

    def test_person_manager_does_not_import_orchestration_or_telegram(self):
        imported = _imported_module_names(BUSINESS_CORE / "person_manager.py")
        forbidden = imported & {"business_builder", "telegram_handlers"}
        self.assertEqual(forbidden, set(), f"person_manager.py must not import orchestration/Telegram: {forbidden}")

    def test_person_manager_does_not_import_domain_managers(self):
        imported = _imported_module_names(BUSINESS_CORE / "person_manager.py")
        forbidden = imported & {"roadmap_manager", "roadmap_template_manager", "service_manager", "object_manager"}
        self.assertEqual(forbidden, set(), f"person_manager.py must not import other domain managers: {forbidden}")

    def test_person_manager_does_not_import_drive_or_extension(self):
        imported = _imported_module_names(BUSINESS_CORE / "person_manager.py")
        forbidden = imported & {
            "google_drive_adapter", "stage_entity_relations", "knowledge_manager",
            "document_registry_manager", "document_requirements_query", "material_manager",
        }
        self.assertEqual(forbidden, set(), f"person_manager.py must not import Drive/Extension modules: {forbidden}")

    def test_no_cycle_business_builder_person_manager(self):
        pm_imports = _imported_module_names(BUSINESS_CORE / "person_manager.py")
        bb_imports = _imported_module_names(BUSINESS_CORE / "business_builder.py")
        pm_imports_bb = "business_builder" in pm_imports
        bb_imports_pm = "person_manager" in bb_imports
        self.assertTrue(bb_imports_pm, "business_builder.py should delegate to person_manager (compatibility wrappers)")
        self.assertFalse(pm_imports_bb, "person_manager.py must not import business_builder (would be a cycle)")


class TestPersonManagerCanonicalApiExists(unittest.TestCase):
    """person_manager.py contains the Phase 31C Part-10 canonical API surface."""

    EXPECTED_FUNCTIONS = (
        "normalize_person_name", "normalize_phone", "normalize_email",
        "resolve_person_identity",
        "find_person_by_id", "list_people", "list_people_by_business",
        "list_people_by_type", "list_clients", "is_client_person", "is_person_archived",
        "create_person", "update_person", "archive_person",
        "ensure_client_role",
        "list_person_business_ids", "has_person_business_link", "append_person_biz_id",
        "update_person_drive_info",
    )

    COMPATIBILITY_FUNCTIONS = ("find_existing_person", "find_duplicate_person", "find_person")

    def test_functions_exist_and_are_callable(self):
        import business_core.person_manager as pm
        for name in self.EXPECTED_FUNCTIONS:
            self.assertTrue(callable(getattr(pm, name, None)), f"person_manager.{name} must exist and be callable")

    def test_compatibility_functions_still_exist(self):
        import business_core.person_manager as pm
        for name in self.COMPATIBILITY_FUNCTIONS:
            self.assertTrue(callable(getattr(pm, name, None)), f"person_manager.{name} must still exist (not deleted)")


class TestIdentityHasSingleImplementation(unittest.TestCase):
    """PERSON_IDENTITY_HAS_SINGLE_IMPLEMENTATION == YES: find_existing_person
    and find_duplicate_person must delegate to resolve_person_identity and
    must not reimplement phone/name/email comparison themselves."""

    def test_find_existing_person_calls_resolve_person_identity(self):
        import business_core.person_manager as pm
        src = inspect.getsource(pm.find_existing_person)
        self.assertIn("resolve_person_identity", src)
        self.assertNotIn("get_business_sheet", src, "find_existing_person must not scan the sheet itself")

    def test_find_duplicate_person_calls_resolve_person_identity(self):
        import business_core.person_manager as pm
        src = inspect.getsource(pm.find_duplicate_person)
        self.assertIn("resolve_person_identity", src)
        self.assertNotIn("get_business_sheet", src, "find_duplicate_person must not scan the sheet itself")


class TestNewClientUsesCanonicalResolver(unittest.TestCase):
    """NEWCLIENT_USES_CANONICAL_PERSON_IDENTITY_API == YES (Phase 31D
    Part 1): /newclient must call resolve_person_identity() directly
    for its branch decision, not the find_existing_person/
    find_duplicate_person compatibility wrappers (those remain for
    other, non-migrated legacy callers only)."""

    def test_newclient_confirm_calls_resolve_person_identity(self):
        from business_core.telegram_handlers import newclient_confirm
        src = inspect.getsource(newclient_confirm)
        self.assertIn("resolve_person_identity", src)

    def test_newclient_confirm_does_not_use_compatibility_wrappers(self):
        """AST-based check (not a plain substring match) — the function
        body's explanatory comments legitimately reference the retired
        wrapper names by name; what matters is that neither is actually
        CALLED or IMPORTED."""
        from business_core.telegram_handlers import newclient_confirm
        src = inspect.getsource(newclient_confirm)
        tree = ast.parse(src)
        forbidden = {"find_existing_person", "find_duplicate_person"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                if fname in forbidden:
                    found.add(fname)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden:
                        found.add(alias.name)
        self.assertEqual(found, set())

    def test_newclient_confirm_does_not_silently_auto_link(self):
        """AMBIGUOUS/ARCHIVED_MATCH branches must perform zero writes —
        structurally, this means create_person/append_person_biz_id
        must not be reachable from resolve_person_identity() without an
        explicit status check in between (checked behaviorally in
        test_business_newclient_person_manager_refactor.py; this is a
        presence check that the status branching exists at all)."""
        from business_core.telegram_handlers import newclient_confirm
        src = inspect.getsource(newclient_confirm)
        self.assertIn('"ambiguous"', src)
        self.assertIn('"archived_match"', src)


class TestPersonBusinessLinkIsAddOnly(unittest.TestCase):
    """PERSON_BUSINESS_LINK_MUTATION_IS_ADD_ONLY == YES,
    GENERIC_UPDATE_CANNOT_MUTATE_PERSON_BUSINESS_LINK == YES."""

    def test_biz_ids_not_in_editable_fields(self):
        import business_core.person_manager as pm
        self.assertNotIn("Biz IDs", pm._PERSON_EDITABLE_FIELDS)

    def test_primary_biz_id_not_in_editable_fields(self):
        import business_core.person_manager as pm
        self.assertNotIn("Primary Biz ID", pm._PERSON_EDITABLE_FIELDS)

    def test_status_not_in_editable_fields(self):
        import business_core.person_manager as pm
        self.assertNotIn("Статус отношений", pm._PERSON_EDITABLE_FIELDS)

    def test_legacy_biznesy_column_still_editable(self):
        """Untouched by Phase 31C/31D — 'Бизнесы' is the legacy
        free-text display column, not the structured link, and
        newclient_confirm() still writes it via update_person() today."""
        import business_core.person_manager as pm
        self.assertIn("Бизнесы", pm._PERSON_EDITABLE_FIELDS)

    def test_update_person_rejects_biz_ids(self):
        import business_core.person_manager as pm
        result = pm.update_person("PRS-001", {"Biz IDs": "BIZ-999"})
        self.assertFalse(result["ok"])

    def test_update_person_rejects_status(self):
        import business_core.person_manager as pm
        result = pm.update_person("PRS-001", {"Статус отношений": "archived"})
        self.assertFalse(result["ok"])


class TestClientRoleDetectionExact(unittest.TestCase):
    """CLIENT_ROLE_DETECTION_USES_EXACT_NORMALIZED_VALUES == YES —
    structural check that is_client_person does not do substring
    matching (behavioral coverage in the identity resolver test file)."""

    def test_is_client_person_source_has_no_substring_check(self):
        import business_core.person_manager as pm
        src = inspect.getsource(pm.is_client_person)
        self.assertNotIn('"клиент" in', src, "is_client_person must not do substring matching")
        self.assertIn("_RECOGNIZED_CLIENT_TYPES", src)

    def test_list_clients_uses_is_client_person(self):
        import business_core.person_manager as pm
        src = inspect.getsource(pm.list_clients)
        self.assertIn("is_client_person", src)


class TestClientListingUsesCanonicalHelper(unittest.TestCase):
    """CLIENT_LISTING_USES_CANONICAL_HELPER == YES (Phase 31D Parts
    4/5/6): /clients, /bc, and the legacy /newroadmap client lookup all
    call person_manager.list_clients()/list_people(), never a raw
    substring "клиент" in Тип filter."""

    @staticmethod
    def _has_substring_role_check(src: str) -> bool:
        """AST-based: True iff the source contains an actual `in`
        comparison whose left operand is the literal "клиент" (a
        substring role check), ignoring comments/docstrings entirely."""
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op, comparator in zip(node.ops, node.comparators):
                    if isinstance(op, ast.In) and isinstance(node.left, ast.Constant) and node.left.value == "клиент":
                        return True
        return False

    def test_show_clients_uses_list_clients(self):
        from business_core.telegram_handlers import show_clients
        src = inspect.getsource(show_clients)
        self.assertIn("list_clients", src)
        self.assertFalse(self._has_substring_role_check(src))

    def test_bc_dashboard_uses_list_clients(self):
        from business_core.telegram_handlers import bc_dashboard
        src = inspect.getsource(bc_dashboard)
        self.assertIn("list_clients", src)
        self.assertFalse(self._has_substring_role_check(src))

    def test_newroadmap_client_uses_list_clients(self):
        from business_core.telegram_handlers import newroadmap_client
        src = inspect.getsource(newroadmap_client)
        self.assertIn("list_clients", src)


class TestNewObjectClientValidation(unittest.TestCase):
    """OBJECT_CREATION_REQUIRES_CLIENT_ROLE == YES,
    OBJECT_CREATION_REQUIRES_PERSON_LINKED_TO_OBJECT_BUSINESS == YES,
    OBJECT_CREATION_AUTO_LINKS_PERSON_TO_BUSINESS == NO,
    ARCHIVED_PERSON_CAN_OWN_NEW_OBJECT == NO (Phase 31D Part 7)."""

    def test_newobject_checks_archived(self):
        from business_core.telegram_handlers import newobject_cmd
        src = inspect.getsource(newobject_cmd)
        self.assertIn("is_person_archived", src)

    def test_newobject_checks_client_role(self):
        from business_core.telegram_handlers import newobject_cmd
        src = inspect.getsource(newobject_cmd)
        self.assertIn("is_client_person", src)

    def test_newobject_checks_business_link(self):
        from business_core.telegram_handlers import newobject_cmd
        src = inspect.getsource(newobject_cmd)
        self.assertIn("has_person_business_link", src)

    def test_newobject_does_not_auto_link(self):
        """AST-based (not plain substring) — the function's explanatory
        comments legitimately name the retired auto-link call for
        documentation; what matters is that it is never actually
        CALLED or IMPORTED."""
        from business_core.telegram_handlers import newobject_cmd
        src = inspect.getsource(newobject_cmd)
        tree = ast.parse(src)
        forbidden = {"add_biz_id_to_person", "append_person_biz_id"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                if fname in forbidden:
                    found.add(fname)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden:
                        found.add(alias.name)
        self.assertEqual(found, set())


class TestClientDriveRetrySafety(unittest.TestCase):
    """CLIENT_DRIVE_CREATION_IS_RETRY_SAFE == YES,
    MULTI_BUSINESS_CLIENT_DRIVE_CREATES_NO_UNTRACKED_FOLDER == YES
    (Phase 31D Parts 8/9)."""

    def test_provision_client_drive_safe_exists(self):
        import business_core.business_builder as bb
        self.assertTrue(callable(getattr(bb, "provision_client_drive_safe", None)))

    def test_provision_client_drive_safe_checks_existing_reference_first(self):
        import business_core.business_builder as bb
        src = inspect.getsource(bb.provision_client_drive_safe)
        self.assertIn("drive_folder_id", src)
        self.assertIn("google_drive", src)

    def test_newclient_confirm_uses_provision_client_drive_safe(self):
        from business_core.telegram_handlers import newclient_confirm
        src = inspect.getsource(newclient_confirm)
        self.assertIn("provision_client_drive_safe", src)


class TestPeopleRegistryOwnershipFullyStrict(unittest.TestCase):
    """Phase 31D: caller migration is complete. No debt allowlist —
    only the one permanent, file-scoped exception (inbox_bridge.py,
    GTD boundary) is excluded from the candidate scan, everything else
    in business_core/ must be clean."""

    def test_people_registry_runtime_writers_is_person_manager_only(self):
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name != "person_manager.py" and p.name not in _APPROVED_EXCEPTION_FILES
        ]
        offenders = set()
        for path in candidate_files:
            hits = _calls_touching_sheet_key(path, WRITE_FUNC_NAMES, "people_registry")
            if hits:
                offenders.add(path.name)
        self.assertEqual(
            offenders, set(),
            f"PEOPLE_REGISTRY must be written only by person_manager.py, found: {offenders}",
        )

    def test_person_manager_is_the_write_primitive_owner(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "person_manager.py", WRITE_FUNC_NAMES, "people_registry",
        )
        self.assertTrue(hits, "person_manager.py should contain the actual PEOPLE_REGISTRY write primitive")

    def test_no_raw_people_registry_readers_anywhere(self):
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name != "person_manager.py" and p.name not in _APPROVED_EXCEPTION_FILES
        ]
        offenders = set()
        for path in candidate_files:
            hits = _calls_touching_sheet_key(path, READ_FUNC_NAMES, "people_registry")
            if hits:
                offenders.add(path.name)
        self.assertEqual(
            offenders, set(),
            f"PEOPLE_REGISTRY must not be read raw outside person_manager.py, found: {offenders}",
        )

    def test_telegram_handlers_no_direct_people_registry_access(self):
        hits = (
            _calls_touching_sheet_key(BUSINESS_CORE / "telegram_handlers.py", WRITE_FUNC_NAMES, "people_registry")
            + _calls_touching_sheet_key(BUSINESS_CORE / "telegram_handlers.py", READ_FUNC_NAMES, "people_registry")
        )
        self.assertEqual(hits, [], f"telegram_handlers.py must not touch PEOPLE_REGISTRY directly: {hits}")

    def test_business_builder_no_direct_people_registry_access(self):
        hits = (
            _calls_touching_sheet_key(BUSINESS_CORE / "business_builder.py", WRITE_FUNC_NAMES, "people_registry")
            + _calls_touching_sheet_key(BUSINESS_CORE / "business_builder.py", READ_FUNC_NAMES, "people_registry")
        )
        self.assertEqual(hits, [], f"business_builder.py must not touch PEOPLE_REGISTRY directly: {hits}")

    def test_inbox_bridge_remains_the_only_scoped_exception(self):
        """Documents the one permanent exception explicitly, rather
        than silently allowing it via a blanket try/except — if
        inbox_bridge.py's raw read is ever removed, this test should be
        updated to drop the exception, not left stale."""
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "inbox_bridge.py", READ_FUNC_NAMES, "people_registry",
        )
        self.assertTrue(hits, "inbox_bridge.py's documented GTD-boundary read is expected to still exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
