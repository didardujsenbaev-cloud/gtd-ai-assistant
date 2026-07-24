"""
Phase 28A: Roadmap domain ownership architecture guards.

Source of truth: the Phase 27B architecture decision report. This file
does not declare the CURRENT architecture correct — several known
violations (documented in Phase 27A/27B) still exist and are pinned
here as explicit, narrowly-scoped, phase-tagged debt so they cannot
silently grow. Each debt entry names the exact phase that is expected
to remove it. When that phase lands, the corresponding allowlist entry
must be deleted (not widened) and the guard becomes strict.

No network, no Google Sheets access — pure AST/source inspection of
files already on disk.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
BUSINESS_CORE = WORKSPACE / "business_core"

# Extension-layer modules (ENGINEERING_STANDARDS.md: Organization,
# Relation, Document, Knowledge, Automation, AI, Reporting, Integration)
# that a Core Roadmap module must never import, now or after any future
# phase. document_manager/materials_manager are included even though
# grep shows no current file named exactly that — the rule is about the
# module name, not today's file inventory, so a future rename/addition
# is caught too.
FORBIDDEN_EXTENSION_MODULES = {
    "stage_entity_relations",
    "knowledge_manager",
    "document_manager",
    "document_registry_manager",
    "materials_manager",
}

# A Core manager must never import the Telegram layer or the
# orchestration layer (business_builder.py) — those depend on Core,
# never the other way around.
FORBIDDEN_ORCHESTRATION_MODULES = {
    "telegram_handlers",
    "business_builder",
}


def _imported_module_names(path: Path) -> set[str]:
    """
    Every module name this file imports, anywhere in its AST —
    module-level or function-local, `import x` or `from x import y`.
    Returns just the top-level segment before any dot, matching how
    business_core submodules are actually named (e.g.
    "business_core.stage_entity_relations" -> "stage_entity_relations"
    is captured via the ImportFrom branch's module.split(".")[-1] check
    below, since these are always dotted as business_core.<name>).
    """
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


class TestRoadmapManagerHasZeroExtensionImports(unittest.TestCase):
    """roadmap_manager.py is Core (ENGINEERING_STANDARDS.md: Business ->
    Client -> Service -> Roadmap -> Stage). It must never import an
    Extension-layer module. Phase 27A confirmed it clean here, and
    Phase 28B's new additive API must not introduce any — this guard
    has no debt allowlist because none is known to exist."""

    def test_no_forbidden_extension_imports(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_EXTENSION_MODULES
        self.assertEqual(
            found, set(),
            f"roadmap_manager.py must not import Extension-layer modules, found: {found}",
        )

    def test_no_telegram_import(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & {"telegram_handlers"}
        self.assertEqual(
            found, set(),
            f"roadmap_manager.py must not import the Telegram layer, found: {found}",
        )


class TestRoadmapManagerOrchestrationDebtIsPinned(unittest.TestCase):
    """
    Phase 28A discovered (not previously flagged this precisely in
    Phase 27A) that roadmap_manager.py's pre-existing
    get_commercial_milestones_for_roadmap() imports
    business_builder.find_roadmap_by_id() internally, to resolve a
    Roadmap row before feeding it to _resolve_template_id(). This
    predates Phase 28AB entirely and is a real, live, production-called
    dependency (via /milestones) — not something safe to silently swap
    for the new Phase 28B find_roadmap_by_id() in this phase, since the
    two functions return different dict key names (business_builder's
    "obj_id"/"biz_id"/"title" vs. this module's "object_id"/
    "business_id"/"client_name"), and telegram_handlers.milestones_cmd
    reads rm.get('obj_id')/rm.get('service_id') directly — swapping
    without also updating that read site would silently break /milestones
    display. Fixing this safely is Phase 28C's job (once business_builder
    itself is being migrated anyway).

    This guard does not approve the dependency — it only prevents any
    OTHER orchestration import from being added to roadmap_manager.py
    beyond this one, already-known, already-scoped case.
    """

    # temporary architectural debt — remove in Phase 28C
    KNOWN_DEBT = {
        "business_builder": "Phase 28C — get_commercial_milestones_for_roadmap's "
                             "business_builder.find_roadmap_by_id usage; requires "
                             "coordinated update of telegram_handlers.milestones_cmd's "
                             "obj_id/service_id reads alongside the swap",
    }

    def test_orchestration_imports_match_known_debt_exactly(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_ORCHESTRATION_MODULES
        expected = set(self.KNOWN_DEBT.keys())

        new_violations = found - expected
        self.assertEqual(
            new_violations, set(),
            f"roadmap_manager.py imports NEW, previously-undocumented "
            f"orchestration modules beyond the known Phase 28C debt: {new_violations}",
        )

        resolved_early = expected - found
        self.assertEqual(
            resolved_early, set(),
            f"Known debt entries {resolved_early} are no longer imported — "
            f"update KNOWN_DEBT (see this class's docstring) to remove them.",
        )


class TestRoadmapTemplateManagerExtensionDebtIsPinned(unittest.TestCase):
    """
    roadmap_template_manager.py is also Core, but Phase 27A found it
    currently imports two Extension-layer modules directly — a
    confirmed, documented violation of the Core -> Extension
    prohibition (ENGINEERING_STANDARDS.md §2). Phase 28E is the phase
    committed to removing both.

    This guard does NOT approve of the debt — it only prevents it from
    growing. If the found set ever contains anything beyond exactly
    these two entries, this test fails. If Phase 28E removes them
    early, this test will fail too (found set becomes smaller than
    expected) — at that point delete KNOWN_DEBT entries here and this
    class stops applying (or convert it into a strict "must be empty"
    guard, merging into the class above).
    """

    # temporary architectural debt — remove in Phase 28E
    KNOWN_DEBT = {
        "stage_entity_relations": "Phase 28E — Extension orchestration extraction",
        "knowledge_manager":      "Phase 28E — Extension orchestration extraction",
    }

    def test_extension_imports_match_known_debt_exactly(self):
        path = BUSINESS_CORE / "roadmap_template_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_EXTENSION_MODULES
        expected = set(self.KNOWN_DEBT.keys())

        new_violations = found - expected
        self.assertEqual(
            new_violations, set(),
            f"roadmap_template_manager.py imports NEW, previously-undocumented "
            f"Extension modules beyond the known Phase 28E debt: {new_violations}",
        )

        resolved_early = expected - found
        self.assertEqual(
            resolved_early, set(),
            f"Known debt entries {resolved_early} are no longer imported — "
            f"great, but this test file must be updated to remove them from "
            f"KNOWN_DEBT (see this class's docstring) before this can be "
            f"reported as passing.",
        )

    def test_no_forbidden_orchestration_imports(self):
        """No known debt here — roadmap_template_manager.py must never
        import Telegram or business_builder, now or later."""
        path = BUSINESS_CORE / "roadmap_template_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_ORCHESTRATION_MODULES
        self.assertEqual(
            found, set(),
            f"roadmap_template_manager.py must not import Telegram/orchestration modules, found: {found}",
        )


def _files_writing_registry(candidate_files: list[Path], sheet_keys: set[str]) -> set[str]:
    """
    For each candidate file, AST-scan every Call node for
    append_business_row(sheet_key, ...) / batch_append_business_rows(sheet_key, ...)
    where sheet_key is a literal string in `sheet_keys`. Returns the set
    of candidate file basenames that contain at least one such call,
    anywhere in the file (module-level or function-local).
    """
    write_func_names = {"append_business_row", "batch_append_business_rows"}
    writers: set[str] = set()

    for path in candidate_files:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in write_func_names:
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if first.value in sheet_keys:
                    writers.add(path.name)
                    break

    return writers


# Fixed candidate list — the only files this guard ever considers.
# Deliberately NOT repository-wide: a new writer appearing in a file
# outside this list would not be caught, but every file Phase 27A
# actually found touching these two registries is included, so any
# change to the KNOWN writer set (new file, or an existing file
# starting to write) is caught.
_CANDIDATE_WRITER_FILES = [
    BUSINESS_CORE / "business_builder.py",
    BUSINESS_CORE / "telegram_handlers.py",
    BUSINESS_CORE / "roadmap_manager.py",
    BUSINESS_CORE / "roadmap_template_manager.py",
    BUSINESS_CORE / "knowledge_manager.py",
    BUSINESS_CORE / "stage_entity_relations.py",
    BUSINESS_CORE / "work_assignment_manager.py",
]


class TestRoadmapsRegistryWriteAllowlist(unittest.TestCase):
    """
    ROADMAPS ("roadmaps" sheet_key) target owner is roadmap_manager.py
    (Phase 27B). Today it has two known non-owner writers — this guard
    pins that exact set so a THIRD, undocumented writer cannot appear
    silently before Phase 28C migrates the known ones away.
    """

    # temporary architectural debt — remove in Phase 28C
    EXPECTED_WRITERS = {
        "business_builder.py":    "Phase 28C — orchestration writer, to migrate to roadmap_manager.create_roadmap_record",
        "telegram_handlers.py":   "Phase 28C — legacy /newroadmap raw write, to migrate to the canonical path",
        "roadmap_manager.py":     "approved owner — Phase 28B added create_roadmap_record (this phase)",
    }

    def test_writers_match_known_allowlist_exactly(self):
        found = _files_writing_registry(_CANDIDATE_WRITER_FILES, {"roadmaps"})
        expected = set(self.EXPECTED_WRITERS.keys())

        unexpected = found - expected
        self.assertEqual(
            unexpected, set(),
            f"NEW, undocumented writer(s) of ROADMAPS found: {unexpected}. "
            f"Every write to 'roadmaps' must go through roadmap_manager.py "
            f"(Phase 27B) — if this is intentional, it must be reflected in "
            f"a phase decision, not silently added.",
        )

        missing = expected - found
        self.assertEqual(
            missing, set(),
            f"Expected writer(s) {missing} no longer write ROADMAPS — update "
            f"EXPECTED_WRITERS (great progress, but keep this guard honest).",
        )


class TestRoadmapStagesRegistryWriteAllowlist(unittest.TestCase):
    """
    ROADMAP_STAGES ("roadmap_stages" sheet_key) target owner is
    roadmap_manager.py (Phase 27B). Today it has three known non-owner-
    consolidated writers (roadmap_manager.py itself already writes it
    via the legacy create_roadmap_stages_from_template AND the new
    Phase 28B ensure_roadmap_stages — both are the approved owner, so
    that's fine) plus two other files with debt tagged for later
    phases.
    """

    # temporary architectural debt — remove in Phase 28C/28D
    EXPECTED_WRITERS = {
        "roadmap_manager.py":          "approved owner — legacy create_roadmap_stages_from_template + Phase 28B ensure_roadmap_stages",
        "roadmap_template_manager.py": "Phase 28D — Stage write consolidation into roadmap_manager",
        "telegram_handlers.py":        "Phase 28C/28D — legacy /newroadmap inline stage creation",
    }

    def test_writers_match_known_allowlist_exactly(self):
        found = _files_writing_registry(_CANDIDATE_WRITER_FILES, {"roadmap_stages"})
        expected = set(self.EXPECTED_WRITERS.keys())

        unexpected = found - expected
        self.assertEqual(
            unexpected, set(),
            f"NEW, undocumented writer(s) of ROADMAP_STAGES found: {unexpected}. "
            f"Every write to 'roadmap_stages' must go through roadmap_manager.py "
            f"(Phase 27B).",
        )

        missing = expected - found
        self.assertEqual(
            missing, set(),
            f"Expected writer(s) {missing} no longer write ROADMAP_STAGES — "
            f"update EXPECTED_WRITERS.",
        )


def _functions_reading_and_writing(path: Path, read_sheet_key: str) -> set[str]:
    """
    Names of every function in `path` whose body BOTH calls
    get_business_sheet(read_sheet_key) AND calls update_cell(...)
    anywhere within the same function — the exact shape of
    knowledge_manager.link_knowledge_to_template_stage()'s direct write
    to ROADMAP_TEMPLATE_STAGES (Phase 27A finding). Function-local, not
    whole-module, since a file may legitimately READ a registry in one
    function while a DIFFERENT function elsewhere writes an unrelated
    one.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    hits: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        calls_get_sheet = False
        calls_update_cell = False
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                fname = inner.func.id if isinstance(inner.func, ast.Name) else getattr(inner.func, "attr", None)
                if fname == "get_business_sheet" and inner.args:
                    first = inner.args[0]
                    if isinstance(first, ast.Constant) and first.value == read_sheet_key:
                        calls_get_sheet = True
                if fname == "update_cell":
                    calls_update_cell = True

        if calls_get_sheet and calls_update_cell:
            hits.add(node.name)

    return hits


class TestRoadmapTemplateStagesDirectWriteDebtIsPinned(unittest.TestCase):
    """
    ROADMAP_TEMPLATE_STAGES target owner is roadmap_template_manager.py
    (Phase 27B). Phase 27A found knowledge_manager.py writes it directly
    via update_cell() inside link_knowledge_to_template_stage() — an
    Extension-layer module writing a Core registry. Phase 28F is the
    phase committed to removing this.

    Narrowly scoped to the two files actually implicated, using a
    function-level (not whole-module) correlation of
    get_business_sheet("roadmap_template_stages") + update_cell() in
    the same function body, matching the exact shape of the known
    violation without a fragile whole-repo scan.
    """

    # temporary architectural debt — remove in Phase 28F
    EXPECTED_WRITE_FUNCTIONS = {
        "knowledge_manager.py": {"link_knowledge_to_template_stage"},
        "roadmap_template_manager.py": set(),  # approved owner; currently uses append_business_row, not update_cell, for its own writes
    }

    def test_only_known_functions_write_template_stages_via_update_cell(self):
        for filename, expected_funcs in self.EXPECTED_WRITE_FUNCTIONS.items():
            path = BUSINESS_CORE / filename
            found_funcs = _functions_reading_and_writing(path, "roadmap_template_stages")

            unexpected = found_funcs - expected_funcs
            self.assertEqual(
                unexpected, set(),
                f"{filename} has NEW, undocumented function(s) writing "
                f"ROADMAP_TEMPLATE_STAGES via update_cell: {unexpected}",
            )


class TestCanonicalRoadmapApiExists(unittest.TestCase):
    """Phase 28B: the new additive canonical API must exist as public,
    callable functions on business_core.roadmap_manager. Presence-only
    — behavioral correctness is covered by test_roadmap_manager_canonical_api.py."""

    EXPECTED_NEW_FUNCTIONS = (
        "find_roadmap_by_id",
        "list_roadmaps",
        "find_active_roadmap_for_object",
        "create_roadmap_record",
        "ensure_roadmap_stages",
    )

    # Pre-existing canonical Stage-read functions this phase must NOT
    # remove, rename, or change the return shape of.
    EXPECTED_UNCHANGED_FUNCTIONS = (
        "get_stages_for_roadmap",
        "find_stage_by_id",
    )

    def test_new_functions_exist_and_are_callable(self):
        import business_core.roadmap_manager as rm
        for name in self.EXPECTED_NEW_FUNCTIONS:
            self.assertTrue(
                callable(getattr(rm, name, None)),
                f"business_core.roadmap_manager.{name} must exist and be callable",
            )

    def test_preexisting_stage_read_functions_untouched(self):
        import business_core.roadmap_manager as rm
        for name in self.EXPECTED_UNCHANGED_FUNCTIONS:
            self.assertTrue(
                callable(getattr(rm, name, None)),
                f"business_core.roadmap_manager.{name} must still exist",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
