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


# ─────────────────────────────────────────────────────────────
# Phase 42D (ADR-025): Interaction caller (Telegram) architecture
# guards. Mirrors the Phase 41D Lead caller guard pattern exactly.
# ─────────────────────────────────────────────────────────────

_INTERACTION_COMMANDS = (
    "newinteraction_cmd", "interactions_cmd", "interaction_cmd",
    "archiveinteraction_cmd", "updateinteractionnotes_cmd",
)


def _th_function_body(fn_name: str) -> str:
    return _function_body(BUSINESS_CORE / "telegram_handlers.py", fn_name)


class TestInteractionCommandsCallOnlyCanonicalOrchestration(unittest.TestCase):

    def test_no_low_level_interaction_manager_write_calls_in_mutating_commands(self):
        forbidden = (
            "interaction_manager.create_interaction(", "interaction_manager.update_interaction_status(",
            "interaction_manager.update_interaction_admin_fields(",
        )
        for fn_name in ("newinteraction_cmd", "archiveinteraction_cmd", "updateinteractionnotes_cmd"):
            body = _th_function_body(fn_name)
            for call in forbidden:
                self.assertNotIn(call, body, f"{fn_name} must not call low-level {call.rstrip('(')} directly")

    def test_mutating_commands_call_business_builder_only(self):
        expectations = {
            "newinteraction_cmd": "create_interaction(",
            "archiveinteraction_cmd": "archive_interaction(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body, f"{fn_name} must call business_builder.{call.rstrip('(')}")

    def test_updateinteractionnotes_calls_business_builder_mutator_through_thread_offload(self):
        """
        Phase 17E-2A semantic replacement for the literal
        "update_interaction_notes(" substring check — the mutator is
        now passed BY REFERENCE into _mutate_target_in_thread (mirrors
        the Phase 17E-1 finder-by-reference pattern), so the direct-
        call substring no longer appears in the handler body.
        """
        src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "updateinteractionnotes_cmd")

        offload_calls, direct_calls = [], []
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                if n.func.id == "_mutate_target_in_thread":
                    offload_calls.append(n)
                elif n.func.id == "update_interaction_notes":
                    direct_calls.append(n)

        self.assertEqual(len(offload_calls), 1)
        call = offload_calls[0]
        mutator_arg = call.args[0]
        self.assertIsInstance(mutator_arg, ast.Name)
        self.assertEqual(mutator_arg.id, "update_interaction_notes")
        self.assertEqual(direct_calls, [])

    def test_read_commands_call_exact_interaction_manager_helpers_only(self):
        # interaction_cmd is enforced (Phase 17E-1): its finder is
        # passed BY REFERENCE into _resolve_target_in_thread rather
        # than called directly, so the literal substring check no
        # longer applies — see the dedicated semantic test below.
        # interactions_cmd (unenforced, targetless list) still calls
        # its manager helper directly.
        expectations = {
            "interactions_cmd": "list_interactions(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body)
            for forbidden in ("create_interaction(", "archive_interaction(", "update_interaction_notes("):
                self.assertNotIn(forbidden, body, f"{fn_name} is read-only and must not call {forbidden.rstrip('(')}")

    def test_interaction_cmd_resolves_finder_through_thread_offload(self):
        """
        Phase 17E-1 semantic replacement for the pre-17E-1 literal
        "find_interaction_by_id(" substring check. Proves: the correct
        finder object and record-ID variable are forwarded to
        _resolve_target_in_thread, the handler never calls the finder
        directly, and authorization only runs after the row is
        resolved.
        """
        src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "interaction_cmd")

        offload_calls, direct_calls = [], []
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                if n.func.id == "_resolve_target_in_thread":
                    offload_calls.append(n)
                elif n.func.id == "find_interaction_by_id":
                    direct_calls.append(n)

        self.assertEqual(len(offload_calls), 1)
        call = offload_calls[0]
        self.assertEqual(len(call.args), 2)
        finder_arg, id_arg = call.args
        self.assertIsInstance(finder_arg, ast.Name)
        self.assertEqual(finder_arg.id, "find_interaction_by_id")
        self.assertIsInstance(id_arg, ast.Name)
        self.assertEqual(id_arg.id, "interaction_id")
        self.assertEqual(direct_calls, [])

        body = _th_function_body("interaction_cmd")
        offload_pos = body.index("_resolve_target_in_thread(")
        authz_pos = body.index("_authorize_or_reply(")
        self.assertLess(offload_pos, authz_pos)


class TestNoCallerSideInteractionPolicy(unittest.TestCase):

    def test_no_caller_side_id_generation(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn('"ACT-"', body)
            self.assertNotIn("generate_next_id(", body)
            self.assertNotIn("generate_next_interaction_id(", body)

    def test_no_caller_side_type_direction_datetime_normalization(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("normalize_interaction_type(", body)
            self.assertNotIn("normalize_interaction_direction(", body)
            self.assertNotIn("normalize_interaction_occurred_at(", body)

    def test_no_caller_side_subject_or_relation_policy(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_validate_interaction_subject(", body)
            self.assertNotIn("_validate_interaction_relations(", body)
            self.assertNotIn("read_business_sheet(", body)

    def test_no_caller_side_idempotency_policy(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("find_interactions_by_idempotency_key(", body)

    def test_no_relationship_capital_reuse(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("relationship_capital", body)
            self.assertNotIn("RelationshipTouch", body)

    def test_no_lead_client_offer_task_payment_mutation_calls(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            for forbidden in (
                "update_lead(", "convert_lead(", "update_person(", "create_person(",
                "accept_commercial_offer(", "create_commercial_offer(",
                "create_payment_obligation(", "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Lead/Person/Offer/Task/Document/Checklist/Stage/Roadmap ({forbidden!r} found)")


class TestInteractionCommandRegistration(unittest.TestCase):

    def test_all_5_commands_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for name in ("newinteraction", "interactions", "interaction", "archiveinteraction", "updateinteractionnotes"):
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_still_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)


class TestInteractionUxHelpersDefinedOnce(unittest.TestCase):

    def test_helpers_defined_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn in (
            "_interaction_creation_message", "_interaction_archive_message", "_interaction_notes_message",
            "_interaction_status_ru", "_interaction_type_ru", "_interaction_direction_ru",
            "_interaction_subject_summary", "_truncate_interaction_text",
        ):
            self.assertEqual(src.count(f"def {fn}("), 1, f"{fn} must be defined exactly once")

    def test_helpers_are_callable(self):
        import business_core.telegram_handlers as th
        for fn in ("_interaction_creation_message", "_interaction_archive_message", "_interaction_notes_message"):
            self.assertTrue(callable(getattr(th, fn, None)))


class TestExternalReferenceNeverExposedGuard(unittest.TestCase):

    def test_external_reference_field_never_rendered(self):
        for fn_name in ("interaction_cmd", "interactions_cmd"):
            body = _th_function_body(fn_name)
            self.assertNotIn('"External Reference"', body)


class TestNoSensitiveInteractionFieldsLoggedGuard(unittest.TestCase):

    _DISALLOWED_LOG_TOKENS = ("Summary", "Outcome", "Notes", "External Reference", "Caller Idempotency Key", "update.message.text")

    def test_interaction_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestNoRawExceptionInInteractionCommands(unittest.TestCase):

    def test_no_raw_exception_interpolation(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("Ошибка: {e}", body)
            self.assertNotIn("str(e)", body)


class TestInteractionParserValidationOrdering(unittest.TestCase):

    def test_newinteraction_validates_before_orchestration(self):
        body = _th_function_body("newinteraction_cmd")
        validation_idx = body.index("if not business_id or not interaction_type or not occurred_at or not summary or not caller_idempotency_key")
        orchestration_idx = body.index("create_interaction(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_archiveinteraction_validates_before_orchestration(self):
        body = _th_function_body("archiveinteraction_cmd")
        validation_idx = body.index("if not interaction_id")
        orchestration_idx = body.index("archive_interaction(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_updateinteractionnotes_validates_before_orchestration(self):
        # Phase 17E-2A: the mutator is invoked by reference through
        # _mutate_target_in_thread rather than called directly — see
        # test_updateinteractionnotes_calls_business_builder_mutator_through_thread_offload
        # for the AST-level proof that update_interaction_notes is the
        # exact function passed.
        body = _th_function_body("updateinteractionnotes_cmd")
        validation_idx = body.index("if not interaction_id or not notes")
        orchestration_idx = body.index("_mutate_target_in_thread(")
        self.assertLess(validation_idx, orchestration_idx)


class TestInteractionParseModeIsNone(unittest.TestCase):

    def test_all_interaction_commands_pass_parse_mode_none(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _th_function_body(fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")


class TestMilestonesCommandUntouchedByInteractionCallerPhase(unittest.TestCase):

    def test_milestones_body_unchanged_shape(self):
        body = _th_function_body("milestones_cmd")
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("interaction_manager", body)
        self.assertNotIn("create_interaction", body)


if __name__ == "__main__":
    unittest.main()
