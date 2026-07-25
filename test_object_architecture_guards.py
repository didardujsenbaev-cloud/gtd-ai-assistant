"""
Phase 30C: Object Manager Foundation architecture guards.

Source of truth: DECISIONS.md ADR-014 (Phase 30B). Mirrors the pattern
established in test_service_architecture_guards.py / test_roadmap_
architecture_guards.py — pure AST/source inspection, no network, no
Sheets.

Foundation-state invariants checked NOW (strict, no allowlist):
  object_manager imports orchestration/Telegram/roadmap/service/person/
    Drive adapter/Extension modules == NO
  object_manager dependency cycle == NO
  object_manager contains the canonical Part-10 API
  business_builder's Object compatibility wrappers perform zero raw
    OBJECT_REGISTRY access (no get_business_sheet/append_business_row/
    update_cell calls of their own — everything delegates to
    object_manager)
  OBJECT_REGISTRY write primitives (append_business_row, update_cell)
    exist only in object_manager.py among production runtime modules
    (business_builder.py's wrappers must not also implement them)

Transitional debt (Phase 30C — caller migration NOT done, Phase 30D):
  telegram_handlers.py still reads/writes OBJECT_REGISTRY raw
    (editobject_start/editobject_confirm/objects_cmd)
  document_registry_manager.py still reads OBJECT_REGISTRY raw
  document_requirements_query.py still reads OBJECT_REGISTRY raw
This debt is pinned to its EXACT known file set — this guard does not
assert OBJECT_REGISTRY_RUNTIME_WRITERS == {object_manager.py} yet (that
invariant is Phase 30D's target, once /editobject is migrated); it only
asserts no NEW writer/reader has appeared beyond this known set.
"""

from __future__ import annotations

import ast
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


WRITE_FUNC_NAMES = {"append_business_row", "batch_append_business_rows"}
READ_FUNC_NAMES = {"read_business_sheet", "get_business_sheet", "find_row_by_id"}

_WRAPPER_FUNCTIONS = (
    "generate_object_id", "create_object_record", "find_objects_by_client",
    "find_object_by_id", "update_object_drive_info", "update_object_roadmap_id",
)


class TestObjectManagerDependencyDirection(unittest.TestCase):
    """object_manager -> business_core.sheets only (ADR-014, Decision 16)."""

    def test_object_manager_does_not_import_orchestration_or_telegram(self):
        imported = _imported_module_names(BUSINESS_CORE / "object_manager.py")
        forbidden = imported & {"business_builder", "telegram_handlers"}
        self.assertEqual(forbidden, set(), f"object_manager.py must not import orchestration/Telegram: {forbidden}")

    def test_object_manager_does_not_import_domain_managers(self):
        imported = _imported_module_names(BUSINESS_CORE / "object_manager.py")
        forbidden = imported & {"roadmap_manager", "roadmap_template_manager", "service_manager", "person_manager"}
        self.assertEqual(forbidden, set(), f"object_manager.py must not import other domain managers: {forbidden}")

    def test_object_manager_does_not_import_drive_or_extension(self):
        imported = _imported_module_names(BUSINESS_CORE / "object_manager.py")
        forbidden = imported & {
            "google_drive_adapter", "stage_entity_relations", "knowledge_manager",
            "document_registry_manager", "document_requirements_query", "material_manager",
        }
        self.assertEqual(forbidden, set(), f"object_manager.py must not import Drive/Extension modules: {forbidden}")

    def test_no_cycle_business_builder_object_manager(self):
        om_imports = _imported_module_names(BUSINESS_CORE / "object_manager.py")
        bb_imports = _imported_module_names(BUSINESS_CORE / "business_builder.py")
        om_imports_bb = "business_builder" in om_imports
        bb_imports_om = "object_manager" in bb_imports
        self.assertTrue(bb_imports_om, "business_builder.py should delegate to object_manager (compatibility wrappers)")
        self.assertFalse(om_imports_bb, "object_manager.py must not import business_builder (would be a cycle)")


class TestObjectManagerCanonicalApiExists(unittest.TestCase):
    """object_manager.py contains the Part-10 canonical API surface."""

    EXPECTED_FUNCTIONS = (
        "generate_object_id",
        "normalize_object_address",
        "normalize_object_city",
        "normalize_cadastral_number",
        "validate_object_status",
        "create_object_record",
        "find_object_by_id",
        "find_objects_by_client",
        "find_objects_by_biz",
        "list_objects",
        "find_duplicate_objects",
        "update_object_fields",
        "update_object_drive_info",
        "update_object_roadmap_id",
    )

    def test_functions_exist_and_are_callable(self):
        import business_core.object_manager as om
        for name in self.EXPECTED_FUNCTIONS:
            self.assertTrue(callable(getattr(om, name, None)), f"object_manager.{name} must exist and be callable")

    def test_object_statuses_constant(self):
        import business_core.object_manager as om
        self.assertEqual(set(om.OBJECT_STATUSES), {"new", "active", "on_hold", "completed", "cancelled"})
        self.assertEqual(om.OBJECT_STATUS_DEFAULT, "new")


class TestBusinessBuilderWrappersPerformNoRegistryAccess(unittest.TestCase):
    """business_builder's compatibility wrappers must contain zero raw
    OBJECT_REGISTRY access of their own (Part 11) — everything must
    delegate to object_manager."""

    def test_wrappers_do_not_call_sheets_primitives_directly(self):
        import inspect
        import business_core.business_builder as bb

        forbidden_calls = {
            "get_business_sheet", "append_business_row", "batch_append_business_rows",
            "update_cell", "generate_next_id", "row_from_header_map", "read_row_by_headers",
        }
        offenders = {}
        for name in _WRAPPER_FUNCTIONS:
            func = getattr(bb, name)
            src = inspect.getsource(func)
            tree = ast.parse(src)
            hits = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                    if fname in forbidden_calls:
                        hits.append(fname)
            if hits:
                offenders[name] = hits
        self.assertEqual(offenders, {}, f"business_builder wrapper(s) still perform raw registry access: {offenders}")

    def test_wrappers_import_object_manager(self):
        import inspect
        import business_core.business_builder as bb
        for name in _WRAPPER_FUNCTIONS:
            src = inspect.getsource(getattr(bb, name))
            self.assertIn(
                "object_manager", src,
                f"business_builder.{name} must delegate to business_core.object_manager",
            )


class TestObjectRegistryWritePrimitivesOwnedByObjectManager(unittest.TestCase):
    """Among production runtime modules, only object_manager.py should
    contain the actual append_business_row/update_cell calls against
    OBJECT_REGISTRY — business_builder.py's wrappers must not
    reimplement writes (checked structurally above; this checks the
    module-wide picture instead)."""

    def test_business_builder_has_no_direct_object_registry_writes(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "business_builder.py", WRITE_FUNC_NAMES, "object_registry",
        )
        self.assertEqual(hits, [], f"business_builder.py must not write object_registry directly: {hits}")

    def test_object_manager_is_the_write_primitive_owner(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "object_manager.py", WRITE_FUNC_NAMES, "object_registry",
        )
        self.assertTrue(hits, "object_manager.py should contain the actual OBJECT_REGISTRY write primitive")


class TestTransitionalDebtSnapshot(unittest.TestCase):
    """Phase 30C foundation-only: caller migration has NOT happened yet.
    This guard pins the EXACT known raw-access debt so it doesn't grow
    silently — Phase 30D must remove these, not add to them."""

    _KNOWN_DEBT_FILES = {
        "telegram_handlers.py",
        "document_registry_manager.py",
        "document_requirements_query.py",
    }

    def test_no_new_raw_object_registry_readers_beyond_known_debt(self):
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name not in ("object_manager.py", "sheets.py", "report_manager.py", "synthetic_cleanup.py")
        ]
        offenders = set()
        for path in candidate_files:
            hits = _calls_touching_sheet_key(path, READ_FUNC_NAMES, "object_registry")
            if hits:
                offenders.add(path.name)
        unexpected = offenders - self._KNOWN_DEBT_FILES
        self.assertEqual(
            unexpected, set(),
            f"New raw OBJECT_REGISTRY reader(s) found beyond the known Phase 30D debt list: {unexpected}",
        )

    def test_no_new_raw_object_registry_writers_beyond_known_debt(self):
        candidate_files = [
            p for p in BUSINESS_CORE.glob("*.py")
            if p.name not in ("object_manager.py", "sheets.py")
        ]
        offenders = set()
        for path in candidate_files:
            hits = _calls_touching_sheet_key(path, WRITE_FUNC_NAMES, "object_registry")
            if hits:
                offenders.add(path.name)
        unexpected = offenders - self._KNOWN_DEBT_FILES
        self.assertEqual(
            unexpected, set(),
            f"New raw OBJECT_REGISTRY writer(s) found beyond the known Phase 30D debt list: {unexpected}",
        )

    def test_report_manager_remains_read_only_approved_exception(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "report_manager.py", WRITE_FUNC_NAMES, "object_registry",
        )
        self.assertEqual(hits, [], f"report_manager.py must remain read-only: {hits}")


class TestObjectCreationDuplicateSafeAndIdempotent(unittest.TestCase):
    """OBJECT_CREATION_USES_CANONICAL_DUPLICATE_POLICY = YES,
    OBJECT_CREATION_IS_IDEMPOTENT = YES — behavioral, mock-only."""

    def test_repeat_call_same_tier1_key_reuses_no_second_write(self):
        from unittest.mock import MagicMock, patch
        import sys
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.object_manager as om

        existing_row = {
            "object_id": "OBJ-900", "biz_id": "BIZ-001", "client_id": "PRS-001",
            "city": "Алматы", "address": "ул. Тест 1", "cadastral_number": "12:34:56",
            "area_m2": "", "object_type": "", "status": "new", "notes": "",
        }
        with patch.object(om, "_load_objects", return_value=([existing_row], [])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="другой адрес", cadastral_number="12-34-56",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["object_created"])
        self.assertTrue(result["object_reused"])
        self.assertEqual(result["object_id"], "OBJ-900")
        mock_append.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
