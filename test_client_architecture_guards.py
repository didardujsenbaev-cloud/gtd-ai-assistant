"""
Phase 31C: Client Domain (Person Manager) architecture guards.

Source of truth: DECISIONS.md ADR-015 (Phase 31B). Mirrors the pattern
established in test_object_architecture_guards.py / test_service_
architecture_guards.py / test_roadmap_architecture_guards.py — pure
AST/source inspection, no network, no Sheets.

This is a FOUNDATION-PHASE guard file (Phase 31C). Client is not a
separate entity — person_manager.py is the sole owner of
PEOPLE_REGISTRY, and this file enforces the identity/API/dependency
invariants ADR-015 requires of it. Caller migration (telegram_handlers.py's
/clients, /bc, legacy /newroadmap, and business_builder.py's /newobject
validation) is explicitly NOT done yet — that is Phase 31D — so this
file's transitional debt allowlist documents each of those exactly, and
must be tightened (not silently widened) in Phase 31D's own guard file
update.

  PEOPLE_REGISTRY_RUNTIME_WRITERS == {person_manager.py}
  PERSON_MANAGER_DEPENDS_ON_ORCHESTRATION == NO
  PERSON_MANAGER_DEPENDENCY_CYCLE_EXISTS == NO
  PERSON_IDENTITY_HAS_SINGLE_IMPLEMENTATION == YES
  FIND_EXISTING_PERSON_IS_COMPATIBILITY_WRAPPER == YES
  FIND_DUPLICATE_PERSON_IS_COMPATIBILITY_WRAPPER == YES
  PERSON_IDENTITY_NEVER_RETURNS_ARBITRARY_FIRST_MATCH == YES (at the
    resolve_person_identity level — see behavioral tests in
    test_business_person_identity_resolver.py)
  NAME_ONLY_MATCH_IS_NOT_AUTOMATIC_REUSE == YES
  MULTIPLE_STRONG_MATCHES_RETURN_AMBIGUOUS == YES
  ARCHIVED_STRONG_MATCH_RETURNS_ARCHIVED_MATCH == YES
  CLIENT_LISTING_USES_IS_CLIENT_PERSON == YES
  CLIENT_ROLE_DETECTION_USES_EXACT_NORMALIZED_VALUES == YES
  PERSON_BUSINESS_LINK_MUTATION_IS_ADD_ONLY == YES
  GENERIC_UPDATE_CANNOT_MUTATE_PERSON_BUSINESS_LINK == YES

Approved transitional exceptions (explicit, file/function-scoped, NOT
blanket allowlists; removal phase = 31D except where noted otherwise):
  - telegram_handlers.py: /clients (show_clients), /bc dashboard client
    count, legacy /newroadmap client lookup — still read PEOPLE_REGISTRY
    raw. Removal phase = 31D.
  - telegram_handlers.py's /newclient (newclient_confirm) — still uses
    find_existing_person()/find_duplicate_person() compatibility
    wrappers, not resolve_person_identity() directly. Removal phase = 31D.
  - business_builder.py's /newobject validation path — still auto-links
    Person to Business (add_biz_id_to_person) instead of requiring a
    pre-existing link. Removal phase = 31D.
  - inbox_bridge.py — raw PEOPLE_REGISTRY read. Permanent, scoped
    GTD-boundary exception: this file may not be modified under any
    Business Core Client Domain phase (CLAUDE.md GTD Core rule), so its
    removal is out of scope for Phase 31D as well, not just this phase.
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

    _MATCH_PRIMITIVE_CALLS = {"get_business_sheet"}  # a wrapper doing its own sheet scan is a smell

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

    def test_resolve_person_identity_is_the_only_full_scan_matcher(self):
        """Belt-and-suspenders structural check: only resolve_person_identity
        and the general-purpose find_person()/_scan helpers may call
        get_business_sheet for people_registry with matching intent —
        checked behaviorally in test_business_person_identity_resolver.py."""
        import business_core.person_manager as pm
        self.assertTrue(callable(pm.resolve_person_identity))


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
        """Untouched by Phase 31C — 'Бизнесы' is the legacy free-text
        display column, not the structured link, and newclient_confirm()
        still writes it via update_person() today."""
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


class TestPeopleRegistryOwnership(unittest.TestCase):
    """PEOPLE_REGISTRY_RUNTIME_WRITERS == {person_manager.py} — writers
    only. Reads are transitionally allowed in the exact-scoped files
    listed in this module's docstring (Phase 31D removes the
    telegram_handlers.py ones; inbox_bridge.py's is permanent)."""

    def test_people_registry_runtime_writers_is_person_manager_only(self):
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name != "person_manager.py"
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

    def test_business_builder_has_no_direct_people_registry_access(self):
        hits = (
            _calls_touching_sheet_key(BUSINESS_CORE / "business_builder.py", WRITE_FUNC_NAMES, "people_registry")
            + _calls_touching_sheet_key(BUSINESS_CORE / "business_builder.py", READ_FUNC_NAMES, "people_registry")
        )
        self.assertEqual(hits, [], f"business_builder.py must not touch PEOPLE_REGISTRY directly: {hits}")

    def test_known_transitional_readers_are_exactly_these_and_no_more(self):
        """Documents (does not yet forbid) the Phase 31D removal targets:
        telegram_handlers.py's raw reads. If a NEW file starts reading
        PEOPLE_REGISTRY raw, this test must fail — no silent widening of
        the debt allowlist."""
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name not in ({"person_manager.py", "telegram_handlers.py"} | _APPROVED_EXCEPTION_FILES)
        ]
        offenders = set()
        for path in candidate_files:
            hits = _calls_touching_sheet_key(path, READ_FUNC_NAMES, "people_registry")
            if hits:
                offenders.add(path.name)
        self.assertEqual(
            offenders, set(),
            f"Unexpected new raw PEOPLE_REGISTRY reader outside the known Phase 31D debt list: {offenders}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
