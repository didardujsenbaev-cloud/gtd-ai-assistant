"""
Phase 38C: Checklist Domain architecture guards (ADR-021). Mirrors the
pattern established in test_document_architecture_guards.py /
test_task_architecture_guards.py — pure AST/source inspection, no
network, no Google Sheets.

  checklist_instances/checklist_instance_items writer  == {checklist_manager.py} only
  Checklist Instance/Item ID generator                  == checklist_manager.py only
  Checklist orchestration policy owner                  == business_builder.py only
  checklist_manager imports business_builder/telegram    == NO
  Template parsing lives outside checklist_manager       == YES (business_builder only)
  No AI/fuzzy parsing                                    == YES
  No title-based dedup                                   == YES
  No arbitrary first-pick                                == YES
  Multiple idempotency matches block                     == YES
  No Task generation/sync                                == YES
  No Document mutation                                   == YES
  No Stage/Roadmap mutation                               == YES
  No /startroadmap integration                            == YES
  No restore/reopen implementation, protection exists     == YES
  No hard delete                                          == YES
  checklist_registry (Template layer) untouched           == YES
  All Checklist tests hard-socket-blocked                 == YES
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


def _function_body(path: Path, fn_name: str) -> str:
    src = path.read_text(encoding="utf-8")
    start = src.index(f"def {fn_name}(")
    rest = src[start + 10:]
    candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    end = start + 10 + min(candidates) if candidates else len(src)
    return src[start:end]


def _bb_function_body(fn_name: str) -> str:
    return _function_body(BUSINESS_CORE / "business_builder.py", fn_name)


class TestChecklistRegistryWriteOwnership(unittest.TestCase):

    def test_only_checklist_manager_writes_operational_registries(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "checklist_manager.py"]
        found = _files_writing_registry(candidates, {"checklist_instances", "checklist_instance_items"})
        self.assertEqual(found, set(), f"Only checklist_manager.py may write operational Checklist registries, found: {found}")

    def test_checklist_manager_is_the_writer(self):
        path = BUSINESS_CORE / "checklist_manager.py"
        found = _files_writing_registry([path], {"checklist_instances", "checklist_instance_items"})
        self.assertEqual(found, {"checklist_manager.py"})

    def test_checklist_registry_template_layer_untouched(self):
        """checklist_registry (the Phase 8C Template layer) must never
        be written by any new Phase 38C file."""
        new_files = [
            BUSINESS_CORE / "checklist_manager.py",
        ]
        found = _files_writing_registry(new_files, {"checklist_registry"})
        self.assertEqual(found, set())

    def test_business_builder_does_not_write_checklist_registries(self):
        found = _files_writing_registry([BUSINESS_CORE / "business_builder.py"], {
            "checklist_instances", "checklist_instance_items", "checklist_registry",
        })
        self.assertEqual(found, set())


class TestIdGenerationOwnership(unittest.TestCase):

    def test_checklist_manager_generates_ids(self):
        import business_core.checklist_manager as cm
        self.assertTrue(callable(getattr(cm, "generate_next_instance_id", None)))
        self.assertTrue(callable(getattr(cm, "generate_next_item_ids", None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "checklist_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if "def generate_next_instance_id" in src or "def generate_next_item_ids" in src:
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_no_caller_side_id_generation_in_orchestration(self):
        for fn_name in ("instantiate_checklist",):
            body = _bb_function_body(fn_name)
            self.assertNotIn('"CLIN-"', body)
            self.assertNotIn('"CLII-"', body)
            self.assertNotIn("generate_next_id(", body)


class TestChecklistOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in (
            "instantiate_checklist", "transition_checklist_status",
            "transition_checklist_item_status", "update_checklist_admin_fields",
        ):
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_checklist_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "checklist_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "BUSINESS_NOT_FOUND", "STAGE_NOT_FOUND", "ROADMAP_NOT_FOUND", "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND",
            "MULTIPLE_CHECKLIST_INSTANCE_MATCHES", "CHECKLIST_ENTITY_RELATION_MISMATCH",
            "CHECKLIST_TEMPLATE_NOT_FOUND", "CHECKLIST_TEMPLATE_INACTIVE", "CHECKLIST_TEMPLATE_ARCHIVED",
            "CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION", "CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION",
            "CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET",
        ):
            self.assertNotIn(
                forbidden, src,
                f"checklist_manager.py must not reference {forbidden} — cross-entity relation/lifecycle/"
                f"idempotency policy belongs solely to business_builder.py (ADR-021).",
            )

    def test_template_parsing_only_in_business_builder(self):
        path = BUSINESS_CORE / "checklist_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def parse_checklist_template_items", src)
        self.assertNotIn("Optional Items", src)
        self.assertNotIn("_split_checklist_text", src)
        self.assertNotIn('"checklist_registry"', src)


class TestChecklistManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_checklist_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "checklist_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"checklist_manager.py must not import: {found}")

    def test_checklist_manager_no_russian_wording_in_logs(self):
        path = BUSINESS_CORE / "checklist_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = getattr(node.func, "attr", None)
                if fname in ("info", "warning", "error") and getattr(node.func, "value", None) is not None:
                    value_name = getattr(node.func.value, "id", "")
                    if value_name == "log":
                        for arg in node.args:
                            if isinstance(arg, ast.JoinedStr):
                                for part in arg.values:
                                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                                        self.assertFalse(
                                            any(ch in "бвгдежзийклмнопрстуфхцчшщъыьэюя" for ch in part.value.lower()),
                                            f"checklist_manager.py log call contains Russian text: {part.value!r}",
                                        )


class TestClosedDomainsDoNotImportChecklistManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_checklist_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py", "document_manager.py",
            "object_manager.py", "service_manager.py", "person_manager.py", "knowledge_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"checklist_manager"}
            self.assertEqual(found, set(), f"{filename} must not import checklist_manager")


class TestGtdFilesDoNotImportChecklistDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_checklist_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"checklist_manager", "business_builder"}
            self.assertNotIn("checklist_manager", found, f"{filename} must not import checklist_manager")


class TestNoTelegramWritesOrRegistrationYet(unittest.TestCase):

    def test_no_checklist_command_registered_yet(self):
        """Phase 38C is Foundation-only — no new Telegram command may
        exist until Phase 38D."""
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("startchecklist", "updatecheckitem", "updatechecklist"):
            self.assertNotIn(f'CommandHandler("{forbidden}"', src)

    def test_telegram_handlers_does_not_import_checklist_manager(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        found = _imported_module_names(path) & {"checklist_manager"}
        self.assertEqual(found, set())


class TestNoFuzzyMatchingOrTitleDedup(unittest.TestCase):

    def test_instantiate_checklist_never_looks_up_by_title(self):
        body = _bb_function_body("instantiate_checklist")
        self.assertNotIn("find_instances_by_title", body)
        self.assertNotIn('"Checklist Title Snapshot"] ==', body)

    def test_parser_never_fuzzy_matches(self):
        body = _bb_function_body("parse_checklist_template_items")
        for forbidden in ("difflib", "SequenceMatcher", ".lower() in", "startswith(", "in text"):
            self.assertNotIn(forbidden, body)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_instance_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("instantiate_checklist")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))


class TestNoTaskDocumentStageRoadmapMutation(unittest.TestCase):

    _CHECKLIST_ORCHESTRATION_FUNCTIONS = (
        "instantiate_checklist", "transition_checklist_status",
        "transition_checklist_item_status", "update_checklist_admin_fields",
    )

    def test_no_task_manager_mutation_calls(self):
        for fn_name in self._CHECKLIST_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "task_manager.create_task(", "task_manager.update_task_status(",
                "create_business_task(", "transition_task_status(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task ({forbidden!r} found)")

    def test_no_document_manager_mutation_calls(self):
        for fn_name in self._CHECKLIST_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "document_manager.create_document(", "document_manager.update_document_status(",
                "register_document(", "transition_document_status(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Document ({forbidden!r} found)")

    def test_no_stage_roadmap_mutation_calls(self):
        for fn_name in self._CHECKLIST_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "update_stage_status_in_sheet(", "update_stage_fields(",
                "recalculate_roadmap_progress(", "maybe_complete_roadmap(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Stage/Roadmap ({forbidden!r} found)")

    def test_no_startroadmap_integration(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("instantiate_checklist", src)
        self.assertNotIn("checklist_manager", src)


class TestRestoreReopenProtection(unittest.TestCase):

    def test_no_restore_function_exists(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("def restore_checklist", src)
            self.assertNotIn("def reopen_checklist", src)

    def test_restore_protection_codes_exist(self):
        import business_core.business_builder as bb
        src = (BUSINESS_CORE / "business_builder.py").read_text(encoding="utf-8")
        self.assertIn("CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION", src)
        self.assertIn("CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION", src)


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        for filename in ("checklist_manager.py",):
            path = BUSINESS_CORE / filename
            src = path.read_text(encoding="utf-8")
            for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
                self.assertNotIn(forbidden, src)
        body = "\n".join(
            _bb_function_body(fn) for fn in (
                "instantiate_checklist", "transition_checklist_status",
                "transition_checklist_item_status", "update_checklist_admin_fields",
            )
        )
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, body)


class TestResultContractFieldsAlwaysPresent(unittest.TestCase):

    _REQUIRED_FIELDS = (
        "ok", "code", "error", "checklist_instance_id", "checklist_template_id",
        "checklist_instance_item_id", "business_id", "service_id", "object_id",
        "roadmap_id", "stage_id", "task_id", "document_id", "sop_id",
        "previous_status", "requested_status", "final_status",
        "created", "reused", "changed", "completed",
        "total_items", "required_items", "completed_items", "required_remaining", "blocked_required",
        "conflicting_ids", "created_item_ids", "warnings", "retry_safe",
    )

    def test_result_builder_always_includes_all_fields(self):
        import business_core.business_builder as bb
        result = bb._checklist_result(ok=True, code="X", error=None)
        for field in self._REQUIRED_FIELDS:
            self.assertIn(field, result, f"missing field {field!r} in _checklist_result output")


class TestAllRuntimeCodesAreProducedByCallables(unittest.TestCase):

    def test_key_codes_are_producible(self):
        import business_core.business_builder as bb
        self.assertEqual(bb.instantiate_checklist("", "CHK-001")["code"], "BUSINESS_NOT_FOUND")
        self.assertEqual(
            bb.parse_checklist_template_items("")["code"], "CHECKLIST_TEMPLATE_ITEMS_EMPTY",
        )


class TestChecklistTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_38c_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_checklist_manager.py",
            "test_business_checklist_foundation.py",
            "test_checklist_architecture_guards.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


if __name__ == "__main__":
    unittest.main()
