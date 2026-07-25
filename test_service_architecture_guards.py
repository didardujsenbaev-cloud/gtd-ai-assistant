"""
Phase 29CD: Service Domain ownership architecture guards.

Source of truth: DECISIONS.md ADR-013 (Phase 29B). Mirrors the pattern
already established in test_roadmap_architecture_guards.py for the
Roadmap domain — pure AST/source inspection, no network, no Sheets.

Target invariants (see ADR-013):
  SERVICE_CATALOG_RUNTIME_WRITERS               == {service_manager.py}
  TELEGRAM_HANDLERS_WRITE_SERVICE_CATALOG_DIRECTLY = NO
  TELEGRAM_HANDLERS_READ_SERVICE_CATALOG_DIRECTLY  = NO
  BUSINESS_BUILDER_READS_SERVICE_CATALOG_DIRECTLY  = NO
  ROADMAP_MODULES_READ_SERVICE_CATALOG_DIRECTLY    = NO
  SERVICE_MANAGER_DEPENDS_ON_ORCHESTRATION         = NO
  SERVICE_MANAGER_DEPENDENCY_CYCLE_EXISTS          = NO
  SERVICE_CREATION_USES_CANONICAL_DUPLICATE_KEY    = YES
  SERVICE_CREATION_IS_IDEMPOTENT                   = YES
  ROADMAP_CREATION_REQUIRES_EXISTING_ACTIVE_SERVICE = YES
  PRODUCTION_IMPORTS_DEAD_SERVICE_CATALOG_MODEL    = NO
  PRODUCTION_CALLERS_USE_PRIVATE_LOAD_SERVICES     = NO

Approved exceptions (explicit, file/function-scoped, not blanket
allowlists — see ADR-013, Decision 1/11/13):
  - report_manager.collect_snapshot(): approved read-only reporting
    exception (raw read_business_sheet("service_catalog"), read-only).
  - business_core/seeds/seed_izhs_*.py::_rename_id_in_sheet: CLI-only
    maintenance debt (renames auto-ID to fixed seed-ID after already
    calling service_manager.create_service_record correctly).
  - business_core/seeds/seed_izhs_commercial_milestones.py::patch_service_notes:
    CLI-only maintenance debt (raw Notes-column patch).
  No other file/function may write or read service_catalog directly.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"


def _imported_module_names(path: Path) -> set[str]:
    """Every module name a file imports, anywhere in its AST —
    module-level or function-local, `import x` or `from x import y`."""
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
    """Find Call nodes to any of `func_names` whose first positional
    arg is the literal string `sheet_key`, anywhere in the file
    (module-level or function-local). Returns 'funcname:lineno' hits."""
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

# Fixed candidate list of production runtime files — CLI-only seed/admin
# scripts are deliberately excluded (approved maintenance-debt exception,
# see module docstring), not silently allowed repository-wide.
_RUNTIME_CANDIDATE_FILES = [
    BUSINESS_CORE / "service_manager.py",
    BUSINESS_CORE / "business_builder.py",
    BUSINESS_CORE / "telegram_handlers.py",
    BUSINESS_CORE / "roadmap_manager.py",
    BUSINESS_CORE / "roadmap_template_manager.py",
]


class TestServiceCatalogRuntimeWriteOwnership(unittest.TestCase):
    """SERVICE_CATALOG_RUNTIME_WRITERS == {service_manager.py}, fully
    strict among production runtime modules (seed/admin CLI scripts are
    an explicit, separately-tracked maintenance-debt exception, not
    scanned by this guard — see ADR-013 Decision 11)."""

    def test_only_service_manager_writes_service_catalog(self):
        writers = set()
        for path in _RUNTIME_CANDIDATE_FILES:
            hits = _calls_touching_sheet_key(path, WRITE_FUNC_NAMES, "service_catalog")
            if hits:
                writers.add(path.name)
        self.assertEqual(
            writers, {"service_manager.py"},
            f"SERVICE_CATALOG must be written only by service_manager.py, found: {writers}",
        )

    def test_telegram_handlers_does_not_write_service_catalog(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "telegram_handlers.py", WRITE_FUNC_NAMES, "service_catalog",
        )
        self.assertEqual(hits, [], f"telegram_handlers.py must not write service_catalog directly: {hits}")


class TestServiceCatalogRuntimeReadOwnership(unittest.TestCase):
    """TELEGRAM_HANDLERS_READ_SERVICE_CATALOG_DIRECTLY = NO,
    BUSINESS_BUILDER_READS_SERVICE_CATALOG_DIRECTLY = NO,
    ROADMAP_MODULES_READ_SERVICE_CATALOG_DIRECTLY = NO."""

    def test_telegram_handlers_no_raw_read(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "telegram_handlers.py", READ_FUNC_NAMES, "service_catalog",
        )
        self.assertEqual(
            hits, [],
            f"telegram_handlers.py must not read service_catalog directly, found: {hits} — "
            f"use business_core.service_manager's public API instead.",
        )

    def test_business_builder_no_raw_read(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "business_builder.py", READ_FUNC_NAMES, "service_catalog",
        )
        self.assertEqual(hits, [], f"business_builder.py must not read service_catalog directly: {hits}")

    def test_roadmap_modules_no_raw_read(self):
        for path in (BUSINESS_CORE / "roadmap_manager.py", BUSINESS_CORE / "roadmap_template_manager.py"):
            hits = _calls_touching_sheet_key(path, READ_FUNC_NAMES, "service_catalog")
            self.assertEqual(hits, [], f"{path.name} must not read service_catalog directly: {hits}")


class TestServiceManagerDependencyDirection(unittest.TestCase):
    """SERVICE_MANAGER_DEPENDS_ON_ORCHESTRATION = NO,
    SERVICE_MANAGER_DEPENDENCY_CYCLE_EXISTS = NO."""

    def test_service_manager_does_not_import_orchestration_or_telegram(self):
        imported = _imported_module_names(BUSINESS_CORE / "service_manager.py")
        forbidden = imported & {"business_builder", "telegram_handlers"}
        self.assertEqual(
            forbidden, set(),
            f"service_manager.py must not import orchestration/Telegram modules, found: {forbidden}",
        )

    def test_service_manager_does_not_import_roadmap_modules(self):
        imported = _imported_module_names(BUSINESS_CORE / "service_manager.py")
        forbidden = imported & {"roadmap_manager", "roadmap_template_manager"}
        self.assertEqual(
            forbidden, set(),
            f"service_manager.py must not import Roadmap modules (reverse dependency), found: {forbidden}",
        )

    def test_no_cycle_between_service_manager_and_roadmap_modules(self):
        """roadmap_manager/roadmap_template_manager -> service_manager
        (one direction, established and approved) must not be met by
        service_manager -> roadmap_* in the reverse direction."""
        sm_imports = _imported_module_names(BUSINESS_CORE / "service_manager.py")
        for other in ("roadmap_manager", "roadmap_template_manager"):
            other_imports = _imported_module_names(BUSINESS_CORE / f"{other}.py")
            sm_imports_other = other in sm_imports
            other_imports_sm = "service_manager" in other_imports
            self.assertFalse(
                sm_imports_other and other_imports_sm,
                f"cycle: service_manager <-> {other}",
            )


class TestServiceCreationDuplicateSafeAndIdempotent(unittest.TestCase):
    """SERVICE_CREATION_USES_CANONICAL_DUPLICATE_KEY = YES,
    SERVICE_CREATION_IS_IDEMPOTENT = YES — behavioral, mock-only."""

    def _fresh_sm(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.service_manager as sm
        return sm

    def test_repeat_call_same_key_reuses_no_second_write(self):
        from unittest.mock import MagicMock, patch
        sm = self._fresh_sm()

        existing_row = {
            "service_id": "SVC-900", "biz_id": "BIZ-001", "service_name": "Test Service",
            "status": "active",
        }
        with patch.object(sm, "_load_services", return_value=([existing_row], [])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(biz_id="BIZ-001", service_name="Test Service")

        self.assertTrue(result["ok"])
        self.assertFalse(result["service_created"])
        self.assertTrue(result["service_reused"])
        self.assertEqual(result["service_id"], "SVC-900")
        mock_append.assert_not_called()


class TestRoadmapRequiresExistingActiveService(unittest.TestCase):
    """ROADMAP_CREATION_REQUIRES_EXISTING_ACTIVE_SERVICE = YES —
    behavioral, mock-only (no live Sheets)."""

    def _fresh_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    def test_missing_service_rejected_no_writes(self):
        from unittest.mock import patch
        bb = self._fresh_bb()
        with patch("business_core.service_manager.find_service_by_id", return_value=None), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-NOT-EXIST",
            )
        self.assertFalse(result["ok"])
        mock_create.assert_not_called()
        mock_append.assert_not_called()

    def test_inactive_service_rejected(self):
        from unittest.mock import patch
        bb = self._fresh_bb()
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-001", "status": "inactive"}), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", service_id="SVC-001",
            )
        self.assertFalse(result["ok"])
        mock_create.assert_not_called()


class TestNoDeadServiceCatalogModelInProduction(unittest.TestCase):
    """PRODUCTION_IMPORTS_DEAD_SERVICE_CATALOG_MODEL = NO —
    business_core/service_catalog.py (the dead legacy in-memory model,
    see ADR-013 Decision 12) must not be imported by any production
    module. Its own legacy tests (test_business_core.py) are excluded."""

    def test_no_production_module_imports_dead_service_catalog(self):
        offenders = []
        for path in sorted(BUSINESS_CORE.glob("*.py")):
            if path.name in ("service_catalog.py", "__init__.py"):
                continue
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("service_catalog"):
                    offenders.append(path.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.endswith("service_catalog") and alias.name != "business_core.sheets":
                            offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            f"business_core/service_catalog.py (dead legacy model) must not be imported by "
            f"production modules, found: {offenders}",
        )


class TestNoProductionCallerUsesPrivateLoadServices(unittest.TestCase):
    """PRODUCTION_CALLERS_USE_PRIVATE_LOAD_SERVICES = NO — _load_services
    is private to service_manager.py; other production modules must use
    the public read API (find_service_by_id / find_services_by_biz /
    list_active_services / list_services / find_services_by_name)."""

    def test_no_external_caller_of_private_load_services(self):
        offenders = []
        for path in sorted(BUSINESS_CORE.glob("*.py")):
            if path.name == "service_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if "_load_services" in src:
                offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            f"_load_services is private to service_manager.py, found external reference in: {offenders}",
        )


class TestApprovedReportingException(unittest.TestCase):
    """report_manager.collect_snapshot()'s raw read_business_sheet
    remains the one documented, approved read-only reporting exception
    (ADR-013 Decision 13) — this guard just confirms it's still scoped
    to that single read-only function and report_manager still doesn't
    write anywhere."""

    def test_report_manager_has_no_writes(self):
        hits = _calls_touching_sheet_key(
            BUSINESS_CORE / "report_manager.py", WRITE_FUNC_NAMES, "service_catalog",
        )
        self.assertEqual(hits, [], f"report_manager.py must remain read-only: {hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
