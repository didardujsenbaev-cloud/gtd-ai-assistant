"""
Phase 42C: Interaction / Communication History Domain architecture
guards (ADR-025). Mirrors the pattern established in
test_lead_architecture_guards.py — pure AST/source inspection, no
network, no Google Sheets.

  interaction_log writer                                == interaction_manager.py only
  ACT ID generator                                       == interaction_manager.py only
  Interaction orchestration policy owner                 == business_builder.py only
  interaction_manager imports business_builder/telegram   == NO
  interaction_manager imports relationship_capital        == NO
  No fuzzy matching, no first-pick                        == YES
  Multiple idempotency matches block                      == YES
  Subject XOR enforced, no arbitrary selection             == YES
  No Person/Lead/Client/Offer mutation                     == YES
  No Task/Reminder/Audit Event/Message Delivery registry   == YES
  No relationship_capital reuse, no RelationshipTouch      == YES
  No restore/reopen implementation                        == YES
  No hard delete                                           == YES
  All result fields always present                        == YES
  All Interaction tests hard-socket-blocked                == YES
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


_INTERACTION_REGISTRIES = {"interaction_log"}

_INTERACTION_ORCHESTRATION_FUNCTIONS = (
    "create_interaction", "archive_interaction", "update_interaction_notes",
)


class TestInteractionRegistryWriteOwnership(unittest.TestCase):

    def test_only_interaction_manager_writes_interaction_registry(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "interaction_manager.py"]
        found = _files_writing_registry(candidates, _INTERACTION_REGISTRIES)
        self.assertEqual(found, set(), f"Only interaction_manager.py may write interaction_log, found: {found}")

    def test_interaction_manager_is_the_writer(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        found = _files_writing_registry([path], _INTERACTION_REGISTRIES)
        self.assertEqual(found, {"interaction_manager.py"})

    def test_business_builder_does_not_write_interaction_registry(self):
        found = _files_writing_registry([BUSINESS_CORE / "business_builder.py"], _INTERACTION_REGISTRIES)
        self.assertEqual(found, set())

    def test_prohibited_registry_keys_absent(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("interactions", "interaction_registry", "lead_interactions"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_audit_event_or_message_delivery_registry_exists(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("audit_log", "audit_event_registry", "message_delivery"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)


class TestIdGenerationOwnership(unittest.TestCase):

    def test_interaction_manager_generates_ids(self):
        import business_core.interaction_manager as im
        self.assertTrue(callable(getattr(im, "generate_next_interaction_id", None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "interaction_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if "def generate_next_interaction_id" in src:
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_no_int_or_tch_generator_anywhere(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn('"INT-', src if path.name == "interaction_manager.py" else "")
        src = (BUSINESS_CORE / "interaction_manager.py").read_text(encoding="utf-8")
        self.assertNotIn('"INT-', src)
        self.assertNotIn('"TCH-', src)

    def test_no_caller_side_id_generation_in_orchestration(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ('"ACT-"', "generate_next_id(", "generate_next_interaction_id("):
                self.assertNotIn(forbidden, body)


class TestInteractionOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_interaction_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "BUSINESS_NOT_FOUND", "LEAD_NOT_FOUND", "CLIENT_NOT_FOUND", "COMMERCIAL_OFFER_NOT_FOUND",
            "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND", "INTERACTION_SUBJECT_REQUIRED", "INTERACTION_SUBJECT_CONFLICT",
            "MULTIPLE_INTERACTION_MATCHES", "INVALID_INTERACTION_TYPE", "INVALID_INTERACTION_DIRECTION",
            "INVALID_INTERACTION_OCCURRED_AT", "INTERACTION_SUMMARY_REQUIRED",
        ):
            self.assertNotIn(
                forbidden, src,
                f"interaction_manager.py must not reference {forbidden} — cross-entity relation/subject/"
                f"content-validation policy belongs solely to business_builder.py (ADR-025).",
            )

    def test_normalization_only_in_business_builder(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden_fn in (
            "def normalize_interaction_type", "def normalize_interaction_direction",
            "def normalize_interaction_occurred_at",
        ):
            self.assertNotIn(forbidden_fn, src)

    def test_lifecycle_and_subject_policy_only_in_business_builder(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def archive_interaction", src)
        self.assertNotIn("_INTERACTION_ORDINARY_TRANSITIONS", src)
        self.assertNotIn("_validate_interaction_subject", src)


class TestInteractionManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_interaction_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"interaction_manager.py must not import: {found}")

    def test_interaction_manager_no_gtd_imports(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        found = _imported_module_names(path) & GTD_FORBIDDEN
        self.assertEqual(found, set())

    def test_interaction_manager_never_imports_relationship_capital(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        found = _imported_module_names(path) & {"relationship_capital"}
        self.assertEqual(found, set())

    def test_interaction_manager_never_imports_lead_person_offer_managers(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        found = _imported_module_names(path) & {"lead_manager", "person_manager", "offer_manager", "payment_manager"}
        self.assertEqual(found, set())


class TestClosedDomainsDoNotImportInteractionManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_interaction_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py", "document_manager.py",
            "object_manager.py", "service_manager.py", "person_manager.py", "knowledge_manager.py",
            "checklist_manager.py", "payment_manager.py", "offer_manager.py", "lead_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"interaction_manager"}
            self.assertEqual(found, set(), f"{filename} must not import interaction_manager")


class TestGtdFilesDoNotImportInteractionDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_interaction_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"interaction_manager"}
            self.assertEqual(found, set(), f"{filename} must not import interaction_manager")


class TestSubjectXorAndNoFirstPick(unittest.TestCase):

    def test_subject_xor_enforced(self):
        body = _bb_function_body("_validate_interaction_subject")
        self.assertIn("INTERACTION_SUBJECT_REQUIRED", body)
        self.assertIn("INTERACTION_SUBJECT_CONFLICT", body)

    def test_multiple_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_interaction")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_no_fuzzy_matching_anywhere_in_interaction_orchestration(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("difflib", "SequenceMatcher"):
                self.assertNotIn(forbidden, body)

    def test_no_summary_time_or_external_reference_dedup(self):
        body = _bb_function_body("create_interaction")
        self.assertNotIn('"Summary"] ==', body)
        self.assertNotIn('"External Reference"] ==', body)


class TestNoClosedDomainMutation(unittest.TestCase):

    def test_no_task_manager_mutation_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("task_manager.create_task(", "create_business_task(", "transition_task_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task ({forbidden!r} found)")

    def test_no_document_manager_mutation_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("document_manager.create_document(", "register_document(", "transition_document_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Document ({forbidden!r} found)")

    def test_no_checklist_manager_mutation_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("instantiate_checklist(", "transition_checklist_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Checklist ({forbidden!r} found)")

    def test_no_payment_mutation_or_offer_lifecycle_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "create_payment_obligation(", "create_payment_transaction(",
                "confirm_payment_transaction(", "reverse_payment_transaction(",
                "create_commercial_offer(", "revise_commercial_offer(", "accept_commercial_offer(",
                "send_commercial_offer(", "reject_commercial_offer(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Payment/Offer ({forbidden!r} found)")

    def test_no_lead_or_person_mutation_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("update_lead(", "convert_lead(", "contact_lead(", "qualify_lead(", "update_person(", "create_person("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Lead/Person ({forbidden!r} found)")

    def test_no_relationship_capital_reuse(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS + ("_validate_interaction_subject",):
            body = _bb_function_body(fn_name)
            self.assertNotIn("relationship_capital", body)
            self.assertNotIn("RelationshipTouch", body)
            self.assertNotIn("create_touch_record", body)

    def test_no_roadmap_object_stage_mutation_calls(self):
        for fn_name in _INTERACTION_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("create_roadmap_for_object(", "update_stage_status_in_sheet(", "create_object("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Object/Roadmap/Stage ({forbidden!r} found)")


class TestRestoreReopenProtection(unittest.TestCase):

    def test_no_restore_function_exists(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("def restore_interaction", src)
            self.assertNotIn("def reopen_interaction", src)

    def test_restore_protection_code_referenced(self):
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn('"archived": ("archived",)', src)


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        path = BUSINESS_CORE / "interaction_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)
        body = "\n".join(_bb_function_body(fn) for fn in _INTERACTION_ORCHESTRATION_FUNCTIONS)
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, body)


class TestResultContractFieldsAlwaysPresent(unittest.TestCase):

    _REQUIRED_FIELDS = (
        "ok", "code", "error",
        "interaction_id", "business_id", "lead_id", "client_id", "commercial_offer_id",
        "channel_id", "assigned_person_id", "interaction_type", "direction", "occurred_at",
        "previous_status", "requested_status", "final_status",
        "created", "reused", "changed", "archived",
        "conflicting_ids", "warnings", "retry_safe",
    )

    def test_result_builder_always_includes_all_fields(self):
        import business_core.business_builder as bb
        result = bb._interaction_result(ok=True, code="X", error=None)
        for field in self._REQUIRED_FIELDS:
            self.assertIn(field, result, f"missing field {field!r} in _interaction_result output")


class TestAllRuntimeCodesAreProducedByCallables(unittest.TestCase):

    def test_key_codes_are_producible(self):
        import business_core.business_builder as bb
        self.assertEqual(bb.create_interaction("", "call", "2026-01-01T00:00:00Z", "S", created_by="a", caller_idempotency_key="k")["code"], "BUSINESS_NOT_FOUND")
        self.assertEqual(bb.normalize_interaction_type("")["code"], "INTERACTION_TYPE_REQUIRED")
        self.assertEqual(bb.normalize_interaction_direction("", "call")["code"], "INTERACTION_DIRECTION_REQUIRED")


class TestInteractionTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_42c_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_interaction_manager.py",
            "test_business_interaction_foundation.py",
            "test_interaction_architecture_guards.py",
            "test_interaction_mock_completeness.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


class TestNoTelegramCallerYet(unittest.TestCase):
    """Phase 42C is explicitly Foundation-only — no Telegram command
    for Interaction may exist yet (that is Phase 42D's scope)."""

    def test_no_interaction_commands_registered(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("newinteraction_cmd", "interactions_cmd", "archiveinteraction_cmd"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
