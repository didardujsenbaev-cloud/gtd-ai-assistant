"""
Phase 37D: Document Domain architecture guards (ADR-020). Mirrors the
pattern established in test_task_architecture_guards.py — pure
AST/source inspection, no network, no Google Sheets.

  document_registry writer                                  == {document_manager.py} only
  Document ID / Family ID generator                          == document_manager.py only
  Document orchestration policy owner                        == business_builder.py only
  document_manager imports business_builder/telegram_handlers == NO
  document_intelligence.py writes document_registry          == NO
  knowledge_manager.py writes document_registry               == NO
  Telegram has direct document_registry write / caller-side ID gen == NO
  Closed domains import document_manager                      == NO
  Canonical requirement evaluator                              == document_requirements_query.evaluate_scope()
  compute_stage_document_status() is a genuine thin adapter    == YES (Phase 37D.1)
  No fuzzy matching / filename dedup / arbitrary first-pick    == YES
  Relation fields not admin-editable                            == YES
  Operational vs AI status kept separate, no AI status mutation == YES
  No Stage/Roadmap/Task write path from Document code           == YES
  Raw exception text not introduced into new orchestration       == YES
  All Document tests hard-socket-blocked                         == YES
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


def _function_body(path: Path, fn_name: str, is_async: bool = False) -> str:
    src = path.read_text(encoding="utf-8")
    marker = f"async def {fn_name}(" if is_async else f"def {fn_name}("
    start = src.index(marker)
    rest = src[start + 10:]
    candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    end = start + 10 + min(candidates) if candidates else len(src)
    return src[start:end]


def _bb_function_body(fn_name: str) -> str:
    return _function_body(BUSINESS_CORE / "business_builder.py", fn_name)


class TestDocumentRegistryWriteOwnership(unittest.TestCase):

    def test_only_document_manager_writes_document_registry(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "document_manager.py"]
        found = _files_writing_registry(candidates, {"document_registry"})
        self.assertEqual(found, set(), f"Only document_manager.py may write document_registry, found: {found}")

    def test_document_manager_is_the_writer(self):
        path = BUSINESS_CORE / "document_manager.py"
        found = _files_writing_registry([path], {"document_registry"})
        self.assertEqual(found, {"document_manager.py"})


class TestIdGenerationOwnership(unittest.TestCase):

    def test_document_registry_manager_no_longer_generates_ids(self):
        path = BUSINESS_CORE / "document_registry_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def compute_next_document_and_family_ids", src)
        self.assertNotIn("def generate_next_family_id", src)

    def test_document_manager_generates_ids(self):
        import business_core.document_manager as dm
        self.assertTrue(callable(getattr(dm, "compute_next_document_and_family_ids", None)))
        self.assertTrue(callable(getattr(dm, "generate_next_family_id", None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "document_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if "def compute_next_document_and_family_ids" in src or "def generate_next_family_id" in src:
                hits.append(path.name)
        self.assertEqual(hits, [])


class TestDocumentOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in (
            "register_document", "upload_and_register_document",
            "update_document_admin_fields", "transition_document_status",
        ):
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_document_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "document_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES", "DOCUMENT_ENTITY_RELATION_MISMATCH",
            "DOCUMENT_RELATION_CONFLICT_ON_REUSE", "DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION",
            "INVALID_DOCUMENT_TRANSITION", "BUSINESS_NOT_FOUND",
        ):
            self.assertNotIn(
                forbidden, src,
                f"document_manager.py must not reference {forbidden} — cross-entity relation/"
                f"reuse/lifecycle policy belongs solely to business_builder.py (ADR-020 §7-15).",
            )


class TestDocumentManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_document_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "document_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"document_manager.py must not import: {found}")

    def test_document_manager_no_russian_wording_in_logs(self):
        path = BUSINESS_CORE / "document_manager.py"
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
                                            f"document_manager.py log call contains Russian text: {part.value!r}",
                                        )


class TestDocumentRegistryManagerReducedToPureReads(unittest.TestCase):

    def test_document_registry_manager_has_no_write_primitive_calls(self):
        path = BUSINESS_CORE / "document_registry_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("append_business_row(", "batch_append_business_rows(", "update_cell("):
            self.assertNotIn(forbidden, src, f"document_registry_manager.py must not write; found {forbidden}")

    def test_expected_read_only_functions_still_present(self):
        import business_core.document_registry_manager as drm
        for fn in ("resolve_and_validate_links", "resolve_target_drive_folder", "get_documents_for_stage", "compute_stage_document_status"):
            self.assertTrue(callable(getattr(drm, fn, None)))


class TestAiDoesNotWriteDocumentRegistry(unittest.TestCase):

    def test_document_intelligence_does_not_write_document_registry(self):
        path = BUSINESS_CORE / "document_intelligence.py"
        if not path.exists():
            return
        found = _files_writing_registry([path], {"document_registry"})
        self.assertEqual(found, set())

    def test_knowledge_manager_does_not_write_document_registry(self):
        path = BUSINESS_CORE / "knowledge_manager.py"
        if not path.exists():
            return
        found = _files_writing_registry([path], {"document_registry"})
        self.assertEqual(found, set())


class TestClosedDomainsDoNotImportDocumentManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_document_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py",
            "object_manager.py", "service_manager.py", "person_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"document_manager"}
            self.assertEqual(found, set(), f"{filename} must not import document_manager")


class TestGtdFilesDoNotImportDocumentDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_document_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"document_manager", "business_builder"}
            self.assertNotIn("document_manager", found, f"{filename} must not import document_manager")


class TestTelegramHasNoDirectDocumentRegistryWrite(unittest.TestCase):

    def test_registerdoc_confirm_has_no_inline_write(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "registerdoc_confirm", is_async=True)
        self.assertNotIn('append_business_row("document_registry"', body)
        self.assertNotIn("compute_next_document_and_family_ids(", body)

    def test_uploaddoc_confirm_has_no_inline_write(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "uploaddoc_confirm", is_async=True)
        self.assertNotIn('append_business_row("document_registry"', body)
        self.assertNotIn("compute_next_document_and_family_ids(", body)

    def test_registerdoc_confirm_calls_canonical_orchestration(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "registerdoc_confirm", is_async=True)
        self.assertIn("register_document(", body)

    def test_uploaddoc_confirm_calls_canonical_orchestration(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "uploaddoc_confirm", is_async=True)
        self.assertIn("upload_and_register_document(", body)


class TestCanonicalRequirementEvaluator(unittest.TestCase):

    def test_evaluate_scope_is_canonical(self):
        import business_core.document_requirements_query as drq
        self.assertTrue(callable(getattr(drq, "evaluate_scope", None)))

    def test_compute_stage_document_status_is_a_real_adapter(self):
        """Phase 37D.1 (ADR-020 §16/§17): compute_stage_document_status()
        must genuinely delegate to evaluate_scope() — not merely claim
        to in prose. A real delegation calls it as a plain expression
        (assigned to a name or passed as an argument), not just
        mentioned in a docstring."""
        body = _function_body(BUSINESS_CORE / "document_registry_manager.py", "compute_stage_document_status")
        self.assertTrue(
            any(
                "= evaluate_scope(" in line or "return evaluate_scope(" in line
                for line in body.splitlines()
            ),
            "compute_stage_document_status must actually call evaluate_scope() — an adapter that only talks about delegating isn't one",
        )

    def test_compute_stage_document_status_has_no_independent_matching_policy(self):
        """The adapter must not re-implement template/document matching,
        satisfaction-status filtering, or scan document_registry rows
        itself — all of that lives solely in evaluate_scope()'s engine
        (business_core/document_requirements.py)."""
        body = _function_body(BUSINESS_CORE / "document_registry_manager.py", "compute_stage_document_status")
        for forbidden in (
            "SATISFYING_STATUSES", "documents_by_template", "read_business_sheet(",
            '.split(",")', "Document Template IDs",
        ):
            self.assertNotIn(forbidden, body, f"compute_stage_document_status must not reimplement matching policy ({forbidden!r} found)")

    def test_no_duplicate_satisfying_statuses_constant_in_legacy_manager(self):
        path = BUSINESS_CORE / "document_registry_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("SATISFYING_STATUSES", src)

    def test_get_documents_for_stage_remains_a_simple_read_not_an_evaluator(self):
        """get_documents_for_stage() may only be a plain document-list
        read API — no template comparison, no status filtering, no
        requirement computation."""
        body = _function_body(BUSINESS_CORE / "document_registry_manager.py", "get_documents_for_stage")
        for forbidden in ("Document Template ID", "SATISFYING_STATUSES", "missing", "matched"):
            self.assertNotIn(forbidden, body, f"get_documents_for_stage must stay a simple read API ({forbidden!r} found)")


class TestCallersConvergeOnCanonicalEvaluator(unittest.TestCase):

    def test_docs4stage_uses_compute_stage_document_status_adapter(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "docs4stage_cmd", is_async=True)
        self.assertIn("compute_stage_document_status", body)

    def test_missingdocs_uses_evaluate_scope(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "missingdocs_cmd", is_async=True)
        self.assertIn("evaluate_scope", body)

    def test_docsrequired_uses_evaluate_scope(self):
        body = _function_body(BUSINESS_CORE / "telegram_handlers.py", "docsrequired_cmd", is_async=True)
        self.assertIn("evaluate_scope", body)

    def test_no_telegram_side_requirement_calculation(self):
        """None of the three commands may independently compare
        Document Template IDs against registered documents — all
        computation must come from the canonical evaluator's result."""
        for fn_name, is_async in (("docs4stage_cmd", True), ("missingdocs_cmd", True), ("docsrequired_cmd", True)):
            body = _function_body(BUSINESS_CORE / "telegram_handlers.py", fn_name, is_async=is_async)
            self.assertNotIn("SATISFYING_STATUSES", body)
            self.assertNotIn("documents_by_template", body)


class TestNoFirstPickInRequirementMatching(unittest.TestCase):

    def test_current_valid_documents_returns_all_matches_not_first_pick(self):
        path = BUSINESS_CORE / "document_requirements.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("def _current_valid_documents_for(")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        self.assertNotIn("[0]", body)
        self.assertIn("return tuple(", body)


class TestNoFuzzyMatchingOrTitleDedup(unittest.TestCase):

    def test_register_document_never_looks_up_by_name(self):
        body = _bb_function_body("register_document")
        self.assertNotIn("find_documents_by_name", body)
        self.assertNotIn('"Document Name"] ==', body)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_drive_file_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("register_document")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))


class TestRelationFieldsNotAdminEditable(unittest.TestCase):

    def test_admin_editable_fields_exclude_relations_and_identity(self):
        import business_core.document_manager as dm
        for forbidden in (
            "Document ID", "Business ID", "Created At",
            "Document Family ID", "Version",
            "Client ID", "Object ID", "Roadmap ID", "Stage ID", "Document Template ID",
            "Status", "Drive File ID", "Drive File URL", "File Name", "Mime Type",
            "Uploaded At", "Uploaded By", "Reviewed At", "Reviewed By", "Rejection Reason",
        ):
            self.assertNotIn(forbidden, dm._DOCUMENT_ADMIN_EDITABLE_FIELDS)

    def test_admin_editable_fields_are_exactly_name_and_notes(self):
        import business_core.document_manager as dm
        self.assertEqual(set(dm._DOCUMENT_ADMIN_EDITABLE_FIELDS), {"Document Name", "Notes"})


class TestOperationalAndAiStatusSeparate(unittest.TestCase):

    def test_document_status_constant_has_no_ai_analysis_values(self):
        import business_core.document_manager as dm
        for ai_value in ("pending", "processing", "completed", "unsupported", "failed"):
            self.assertNotIn(ai_value, dm.DOCUMENT_STATUS)

    def test_document_manager_does_not_mutate_analysis_status(self):
        path = BUSINESS_CORE / "document_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn('get_business_sheet("document_content")', src)
        self.assertNotIn('append_business_row("document_content"', src)
        self.assertNotIn("analysis_status", src)


class TestNoStageRoadmapTaskWritePathFromDocumentCode(unittest.TestCase):

    def test_document_orchestration_never_writes_stage_roadmap_or_task(self):
        for fn_name in (
            "register_document", "upload_and_register_document",
            "update_document_admin_fields", "transition_document_status",
        ):
            body = _bb_function_body(fn_name)
            for forbidden in (
                "update_stage_status_in_sheet(", "update_stage_fields(",
                "recalculate_roadmap_progress(", "maybe_complete_roadmap(",
                "create_document.__wrapped__", "task_manager.create_task(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not write Stage/Roadmap/Task state directly")


class TestNoRawExceptionTextInNewOrchestration(unittest.TestCase):

    def test_document_confirm_handlers_do_not_expose_raw_exceptions(self):
        for fn_name in ("registerdoc_confirm", "uploaddoc_confirm"):
            body = _function_body(BUSINESS_CORE / "telegram_handlers.py", fn_name, is_async=True)
            self.assertNotIn("Ошибка сохранения: {e}", body)
            self.assertNotIn("Ошибка: {e}", body)

    def test_document_orchestration_functions_never_interpolate_exception_into_error(self):
        for fn_name in (
            "register_document", "upload_and_register_document",
            "update_document_admin_fields", "transition_document_status",
        ):
            body = _bb_function_body(fn_name)
            self.assertNotIn("str(e)", body)
            self.assertNotIn("{exc}", body)


class TestDocumentTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_37d_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_business_document_registry.py",
            "test_business_document_upload.py",
            "test_business_document_intelligence.py",
            "test_business_document_requirements.py",
            "test_document_manager.py",
            "test_business_document_foundation.py",
            "test_document_architecture_guards.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


if __name__ == "__main__":
    unittest.main()
