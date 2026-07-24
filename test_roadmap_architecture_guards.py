"""
Phase 28A/28CDEF: Roadmap domain ownership architecture guards.

Source of truth: the Phase 27B architecture decision report. Phase
28AB installed these guards with several documented, phase-tagged debt
allowlists (business_builder.py/telegram_handlers.py writing ROADMAPS
directly, roadmap_template_manager.py writing ROADMAP_STAGES and
importing stage_entity_relations/knowledge_manager, knowledge_manager.py
writing ROADMAP_TEMPLATE_STAGES directly, roadmap_manager.py importing
business_builder). Phase 28CDEF resolved every one of those — this file
now enforces the fully-strict target architecture with no debt
allowlists remaining:

  ROADMAPS writers                 == {roadmap_manager.py}
  ROADMAP_STAGES writers           == {roadmap_manager.py}
  roadmap_manager imports business_builder  == NO
  roadmap_manager imports Extension          == NO
  roadmap_template_manager imports Extension == NO
  knowledge_manager direct Template Stage registry access == NO

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
# that a Core Roadmap module must never import. document_manager/
# materials_manager are included even though grep shows no current file
# named exactly that — the rule is about the module name, not today's
# file inventory, so a future rename/addition is caught too.
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


class TestRoadmapManagerHasZeroExtensionOrOrchestrationImports(unittest.TestCase):
    """roadmap_manager.py is Core (ENGINEERING_STANDARDS.md: Business ->
    Client -> Service -> Roadmap -> Stage). It must never import an
    Extension-layer module, Telegram, or business_builder. Phase 28E
    removed the last remaining known exception (get_commercial_
    milestones_for_roadmap's business_builder.find_roadmap_by_id usage,
    replaced by this module's own Phase 28B find_roadmap_by_id) — this
    guard is now fully strict, no debt allowlist."""

    def test_no_forbidden_extension_imports(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_EXTENSION_MODULES
        self.assertEqual(
            found, set(),
            f"roadmap_manager.py must not import Extension-layer modules, found: {found}",
        )

    def test_no_forbidden_orchestration_imports(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_ORCHESTRATION_MODULES
        self.assertEqual(
            found, set(),
            f"roadmap_manager.py must not import Telegram/orchestration modules, found: {found}",
        )


class TestRoadmapTemplateManagerHasZeroExtensionOrOrchestrationImports(unittest.TestCase):
    """roadmap_template_manager.py is also Core. Phase 28E removed its
    two known Extension imports (stage_entity_relations,
    knowledge_manager) — find_template_stages() now reads knowledge-ID
    columns directly (same-registry read, no Extension dependency) and
    create_stages_from_template_record() delegates Stage creation to
    roadmap_manager.ensure_roadmap_stages() (Core -> Core) instead of
    writing ROADMAP_STAGES itself and copying relations inline. This
    guard is now fully strict, no debt allowlist."""

    def test_no_forbidden_extension_imports(self):
        path = BUSINESS_CORE / "roadmap_template_manager.py"
        found = _imported_module_names(path) & FORBIDDEN_EXTENSION_MODULES
        self.assertEqual(
            found, set(),
            f"roadmap_template_manager.py must not import Extension-layer modules, found: {found}",
        )

    def test_no_forbidden_orchestration_imports(self):
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


class TestRoadmapsRegistryWriteOwnership(unittest.TestCase):
    """ROADMAPS ("roadmaps" sheet_key) — Phase 28C migrated both
    non-owner writers (business_builder.create_roadmap_for_object now
    calls roadmap_manager.create_roadmap_record instead of writing
    directly; telegram_handlers.newroadmap_confirm now calls
    business_builder.create_roadmap_for_object instead of writing
    directly). roadmap_manager.py is now the sole writer — fully
    strict, no debt allowlist."""

    def test_only_roadmap_manager_writes_roadmaps(self):
        found = _files_writing_registry(_CANDIDATE_WRITER_FILES, {"roadmaps"})
        self.assertEqual(
            found, {"roadmap_manager.py"},
            f"ROADMAPS must be written only by roadmap_manager.py, found: {found}",
        )


class TestRoadmapStagesRegistryWriteOwnership(unittest.TestCase):
    """ROADMAP_STAGES ("roadmap_stages" sheet_key) — Phase 28D/28C
    migrated every non-owner writer: roadmap_template_manager.
    create_stages_from_template_record() now delegates to roadmap_manager.
    ensure_roadmap_stages() instead of writing directly; telegram_handlers.
    newroadmap_confirm() no longer writes stages inline. roadmap_manager.py
    is now the sole writer — fully strict, no debt allowlist."""

    def test_only_roadmap_manager_writes_roadmap_stages(self):
        found = _files_writing_registry(_CANDIDATE_WRITER_FILES, {"roadmap_stages"})
        self.assertEqual(
            found, {"roadmap_manager.py"},
            f"ROADMAP_STAGES must be written only by roadmap_manager.py, found: {found}",
        )


def _functions_reading_and_writing(path: Path, read_sheet_key: str) -> set[str]:
    """
    Names of every function in `path` whose body BOTH calls
    get_business_sheet(read_sheet_key) AND calls update_cell(...)
    anywhere within the same function. Function-local, not whole-module,
    since a file may legitimately READ a registry in one function while
    a DIFFERENT function elsewhere writes an unrelated one.
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


class TestRoadmapTemplateStagesWriteOwnership(unittest.TestCase):
    """
    ROADMAP_TEMPLATE_STAGES target owner is roadmap_template_manager.py
    (Phase 27B). Phase 28F removed knowledge_manager.py's direct
    update_cell() write inside link_knowledge_to_template_stage() —
    that function now delegates to roadmap_template_manager.
    update_template_stage_knowledge_ids(), the sole owner API for this
    write. Fully strict: knowledge_manager.py must have zero functions
    matching this get_business_sheet+update_cell shape.
    """

    def test_knowledge_manager_has_no_direct_template_stage_write(self):
        path = BUSINESS_CORE / "knowledge_manager.py"
        found_funcs = _functions_reading_and_writing(path, "roadmap_template_stages")
        self.assertEqual(
            found_funcs, set(),
            f"knowledge_manager.py must not write ROADMAP_TEMPLATE_STAGES directly, "
            f"found writing function(s): {found_funcs}",
        )

    def test_owner_api_exists_on_roadmap_template_manager(self):
        import business_core.roadmap_template_manager as rtm
        self.assertTrue(
            callable(getattr(rtm, "update_template_stage_knowledge_ids", None)),
            "roadmap_template_manager.update_template_stage_knowledge_ids must exist and be callable",
        )

    def test_knowledge_manager_delegates_to_owner_api(self):
        import ast
        import inspect
        import business_core.knowledge_manager as km
        src = inspect.getsource(km.link_knowledge_to_template_stage)
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
        self.assertIn("roadmap_template_manager", imported)


class TestCanonicalRoadmapApiExists(unittest.TestCase):
    """Phase 28B/28D: the canonical API must exist as public, callable
    functions on business_core.roadmap_manager. Presence-only —
    behavioral correctness is covered by test_roadmap_manager_canonical_api.py."""

    EXPECTED_FUNCTIONS = (
        "find_roadmap_by_id",
        "list_roadmaps",
        "find_active_roadmap_for_object",
        "create_roadmap_record",
        "ensure_roadmap_stages",
        "update_stage_fields",
    )

    # Pre-existing canonical Stage-read/write functions this phase must
    # NOT remove, rename, or change the return shape of.
    EXPECTED_UNCHANGED_FUNCTIONS = (
        "get_stages_for_roadmap",
        "find_stage_by_id",
        "update_stage_status_in_sheet",
    )

    def test_functions_exist_and_are_callable(self):
        import business_core.roadmap_manager as rm
        for name in self.EXPECTED_FUNCTIONS:
            self.assertTrue(
                callable(getattr(rm, name, None)),
                f"business_core.roadmap_manager.{name} must exist and be callable",
            )

    def test_preexisting_stage_functions_untouched(self):
        import business_core.roadmap_manager as rm
        for name in self.EXPECTED_UNCHANGED_FUNCTIONS:
            self.assertTrue(
                callable(getattr(rm, name, None)),
                f"business_core.roadmap_manager.{name} must still exist",
            )


class TestTelegramHandlersNoDirectRoadmapRegistryWrites(unittest.TestCase):
    """TELEGRAM_HANDLERS_WRITE_ROADMAP_REGISTRIES_DIRECTLY == NO
    (Phase 28C/28D target invariant). telegram_handlers.py must not
    itself call append_business_row/batch_append_business_rows/
    update_cell against "roadmaps" or "roadmap_stages" — every write
    must be routed through business_core.roadmap_manager or
    business_core.business_builder."""

    def test_no_append_writes_to_roadmap_registries(self):
        found = _files_writing_registry(
            [BUSINESS_CORE / "telegram_handlers.py"], {"roadmaps", "roadmap_stages"},
        )
        self.assertEqual(found, set(), f"telegram_handlers.py must not write Roadmap registries directly: {found}")

    def test_no_update_cell_writes_to_roadmap_stages(self):
        found_funcs = _functions_reading_and_writing(
            BUSINESS_CORE / "telegram_handlers.py", "roadmap_stages",
        )
        self.assertEqual(
            found_funcs, set(),
            f"telegram_handlers.py must not write roadmap_stages via update_cell, found: {found_funcs}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
