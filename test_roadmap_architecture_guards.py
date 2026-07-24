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
    columns directly (same-registry read, no Extension dependency).
    Closeout Remediation (finding #2) additionally removed this module's
    only remaining business_core.roadmap_manager import
    (create_stages_from_template_record(), which used to delegate Stage
    creation to roadmap_manager.ensure_roadmap_stages() from here) —
    that orchestration now lives in business_builder.
    create_stages_from_template_record() instead, breaking the
    roadmap_manager <-> roadmap_template_manager import cycle (see
    TestNoRoadmapManagerCircularDependency below). This guard is now
    fully strict, no debt allowlist."""

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
    migrated every non-owner writer: roadmap_template_manager no longer
    contains any Stage-creation function at all (Closeout Remediation
    finding #2 moved create_stages_from_template_record() to
    business_builder, which itself only ever delegates to roadmap_manager.
    ensure_roadmap_stages() instead of writing directly); telegram_handlers.
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


class TestConvergentRetryUsesActiveRoadmapLookup(unittest.TestCase):
    """Phase 28G: create_roadmap_for_object must consult
    roadmap_manager.find_active_roadmap_for_object() before ever
    creating a new ROADMAPS row — no duplicate-active-Roadmap bypass."""

    def test_create_roadmap_for_object_calls_find_active_roadmap(self):
        import inspect
        import business_core.business_builder as bb
        src = inspect.getsource(bb.create_roadmap_for_object)
        self.assertIn("find_active_roadmap_for_object", src)


def _files_containing_literal_status_write(candidate_files: list[Path], forbidden_value: str) -> set[str]:
    """
    Scans each file's AST for `forbidden_value` appearing as an actual
    WRITE usage — the two shapes used throughout this codebase:
      - a dict VALUE inside a dict literal (e.g. {"Status": "not_started"}),
        the row_from_header_map(headers, values) pattern;
      - a literal string argument to update_cell(...).

    Deliberately does NOT flag `forbidden_value` appearing as a dict
    KEY (e.g. STAGE_STATUS_READ_ALIASES = {"not_started": "pending"},
    STATUS_ICONS = {"not_started": "..."}) — those are legitimate
    read-alias/display-icon mappings, not writes. Also does not flag
    plain attribute/comparison/default-value usage (e.g. the dead
    in-memory RoadmapStage.status default, or `if x.status ==
    "not_started"`) — neither is a Sheets write.
    """
    hits: set[str] = set()
    for path in candidate_files:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for v in node.values:
                    if isinstance(v, ast.Constant) and v.value == forbidden_value:
                        hits.add(path.name)
            elif isinstance(node, ast.Call):
                fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                if fname == "update_cell":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value == forbidden_value:
                            hits.add(path.name)
    return hits


class TestLegacyStatusNeverWritten(unittest.TestCase):
    """
    Phase 28H: "not_started" (the one evidenced legacy Stage status —
    see roadmap_manager.STAGE_STATUS_READ_ALIASES's own docstring for
    why no other legacy value is aliased) must never be WRITTEN by any
    Roadmap-domain module again. This guard distinguishes write usage
    (dict-literal values feeding row_from_header_map, or update_cell
    literal arguments) from legitimate read-handling (alias-mapping
    dict KEYS, icon-lookup dict KEYS, dead in-memory model defaults/
    comparisons) — it does not blanket-forbid the string repository-wide.
    """

    _CANDIDATE_FILES = [
        BUSINESS_CORE / "roadmap_manager.py",
        BUSINESS_CORE / "roadmap_template_manager.py",
        BUSINESS_CORE / "business_builder.py",
        BUSINESS_CORE / "telegram_handlers.py",
    ]

    def test_not_started_is_never_a_write_value(self):
        found = _files_containing_literal_status_write(self._CANDIDATE_FILES, "not_started")
        self.assertEqual(
            found, set(),
            f"'not_started' found as an actual write value (dict value feeding a "
            f"Sheets write, or a literal update_cell argument) in: {found} — "
            f"only canonical STAGE_STATUS_CANONICAL values may ever be written.",
        )

    def test_canonical_constants_are_the_single_source_of_truth(self):
        """Guards elsewhere in this file, and any future guard, must
        read these same constants — not redeclare their own copies."""
        import business_core.roadmap_manager as rm
        self.assertEqual(
            set(rm.STAGE_STATUS_CANONICAL),
            {"pending", "in_progress", "blocked", "done", "skipped"},
        )
        self.assertEqual(
            set(rm.ROADMAP_STATUSES),
            {"active", "completed", "on_hold", "cancelled"},
        )


class TestNoRoadmapManagerCircularDependency(unittest.TestCase):
    """
    Closeout Remediation (finding #2): CORE_ROADMAP_DEPENDENCY_CYCLE_EXISTS
    must be NO. Before this remediation, roadmap_manager.py imported
    roadmap_template_manager.find_roadmap_templates_by_service() (inside
    _resolve_template_id) AND roadmap_template_manager.py imported
    roadmap_manager.ensure_roadmap_stages() (inside
    create_stages_from_template_record) — a genuine circular *_manager.py
    <-> *_manager.py dependency, both directions function-local/lazy so
    neither raised ImportError, but forbidden by ENGINEERING_STANDARDS.md.
    create_stages_from_template_record() moved to business_builder,
    removing the roadmap_template_manager -> roadmap_manager edge
    entirely. roadmap_manager -> roadmap_template_manager (the
    _resolve_template_id lookup) is the one remaining, single-direction
    edge — not a cycle. This check is AST-based (module-level or
    function-local imports, anywhere in the file) so it cannot be
    defeated by moving an import inside a function.
    """

    def test_roadmap_template_manager_does_not_import_roadmap_manager(self):
        path = BUSINESS_CORE / "roadmap_template_manager.py"
        found = _imported_module_names(path) & {"roadmap_manager"}
        self.assertEqual(
            found, set(),
            "roadmap_template_manager.py must not import business_core.roadmap_manager "
            "anywhere (module-level or function-local) — this is the edge that used to "
            "close the roadmap_manager <-> roadmap_template_manager import cycle.",
        )

    def test_no_cycle_between_the_two_roadmap_managers(self):
        rm_path  = BUSINESS_CORE / "roadmap_manager.py"
        rtm_path = BUSINESS_CORE / "roadmap_template_manager.py"
        rm_imports_rtm = "roadmap_template_manager" in _imported_module_names(rm_path)
        rtm_imports_rm = "roadmap_manager" in _imported_module_names(rtm_path)
        self.assertFalse(
            rm_imports_rtm and rtm_imports_rm,
            "roadmap_manager.py and roadmap_template_manager.py must not import each "
            f"other simultaneously (cycle): roadmap_manager imports roadmap_template_manager "
            f"= {rm_imports_rtm}, roadmap_template_manager imports roadmap_manager = {rtm_imports_rm}",
        )

    def test_template_stage_retrieval_still_works(self):
        import business_core.roadmap_template_manager as rtm
        self.assertTrue(callable(getattr(rtm, "find_template_stages", None)))

    def test_business_builder_owns_create_stages_from_template_record(self):
        import business_core.business_builder as bb
        import business_core.roadmap_template_manager as rtm
        self.assertTrue(
            callable(getattr(bb, "create_stages_from_template_record", None)),
            "business_core.business_builder.create_stages_from_template_record must exist "
            "— the orchestration moved here from roadmap_template_manager.",
        )
        self.assertIsNone(
            getattr(rtm, "create_stages_from_template_record", None),
            "business_core.roadmap_template_manager.create_stages_from_template_record "
            "must no longer exist — it was the function that imported roadmap_manager.",
        )

    def test_create_roadmap_for_object_still_creates_stages_via_ensure_roadmap_stages(self):
        import inspect
        import business_core.business_builder as bb
        src = inspect.getsource(bb.create_roadmap_for_object)
        self.assertIn("ensure_roadmap_stages", src)
        self.assertIn("find_template_stages", src)


class TestTelegramHandlersNeverReadRoadmapStagesDirectly(unittest.TestCase):
    """
    Closeout Remediation (finding #3): TELEGRAM_HANDLERS_READ_ROADMAP_STAGES_DIRECTLY
    must be NO. The six Stage-field commands (/stage, /assignstage, /duedate,
    /priority, /blockstage, /unblockstage) used to call
    business_core.sheets.find_row_by_id("roadmap_stages", ...) directly,
    bypassing the existing owner API roadmap_manager.find_stage_by_id().
    This is a source-level, not just a per-handler, guarantee: no raw
    Sheets read of the roadmap_stages registry anywhere in
    telegram_handlers.py — AST-based, catches find_row_by_id,
    get_worksheet, and get_business_sheet calls against the
    "roadmap_stages" sheet_key, module-level or function-local.
    """

    def test_no_raw_roadmap_stages_reads_in_telegram_handlers(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        raw_read_funcs = {"find_row_by_id", "get_worksheet", "get_business_sheet"}
        hits: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if fname not in raw_read_funcs:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == "roadmap_stages":
                    hits.append(f"{fname}(...) at line {node.lineno}")
        self.assertEqual(
            hits, [],
            f"telegram_handlers.py must not read roadmap_stages directly, found: {hits} "
            f"— use business_core.roadmap_manager.find_stage_by_id() instead.",
        )

    def test_find_stage_by_id_is_used_by_telegram_handlers(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn(
            "find_stage_by_id", src,
            "telegram_handlers.py should call roadmap_manager.find_stage_by_id() "
            "for its Stage-field commands.",
        )

    def test_owner_api_find_stage_by_id_exists(self):
        import business_core.roadmap_manager as rm
        self.assertTrue(callable(getattr(rm, "find_stage_by_id", None)))


class TestEmptyServiceIdCannotReachRoadmapCreation(unittest.TestCase):
    """
    Closeout Remediation (finding #1): EMPTY_SERVICE_ID_CAN_REACH_ROADMAP_CREATION
    must be NO, and INVALID_SERVICE_ID_CAUSES_NO_ROADMAP_WRITE must be YES.
    service_id is part of the (Object ID, Service ID) duplicate key
    find_active_roadmap_for_object() uses to prevent a second active
    Roadmap for the same Object (see the RM-002 production incident) — a
    blank service_id must never bypass that lookup. Both the Telegram
    handler and business_builder.create_roadmap_for_object() (defense in
    depth) must reject it before any write.
    """

    def test_builder_rejects_empty_service_id_without_any_write(self):
        from unittest.mock import patch
        import business_core.business_builder as bb

        with patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.batch_append_business_rows") as mock_batch:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
                service_id="", case_type="general",
            )

        self.assertFalse(result["ok"])
        self.assertIn("service_id", result["error"])
        mock_create.assert_not_called()
        mock_append.assert_not_called()
        mock_batch.assert_not_called()

    def test_builder_rejects_whitespace_only_service_id(self):
        import business_core.business_builder as bb
        result = bb.create_roadmap_for_object(
            obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
            service_id="   ", case_type="general",
        )
        self.assertFalse(result["ok"])

    def test_builder_dedup_lookup_no_longer_conditional_on_service_id(self):
        """The find_active_roadmap_for_object(...) call must not be
        wrapped in a conditional (ternary) expression gated on
        service_id — after validation, service_id is always truthy, so
        the old `find_active_roadmap_for_object(...) if service_id else
        None` bypass pattern must be gone, and the call site must be a
        plain, unconditional assignment."""
        import ast
        import inspect
        import business_core.business_builder as bb
        src = inspect.getsource(bb.create_roadmap_for_object)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.IfExp):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        fname = sub.func.id if isinstance(sub.func, ast.Name) else getattr(sub.func, "attr", None)
                        self.assertNotEqual(
                            fname, "find_active_roadmap_for_object",
                            "find_active_roadmap_for_object() must not be called inside a "
                            "conditional expression gated on service_id.",
                        )

    def test_handler_validates_service_id_before_builder_call(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def startroadmap_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        self.assertIn("service_id", body)
        self.assertIn("create_roadmap_for_object", body)
        # The service_id-emptiness check must appear before the
        # create_roadmap_for_object import/call in source order.
        service_check_pos = body.find("service_id.strip()")
        call_pos = body.find("create_roadmap_for_object")
        self.assertNotEqual(service_check_pos, -1, "no service_id validation found in startroadmap_cmd")
        self.assertLess(service_check_pos, call_pos,
                        "service_id must be validated before create_roadmap_for_object is called")


if __name__ == "__main__":
    unittest.main(verbosity=2)
