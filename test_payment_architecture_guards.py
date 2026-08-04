"""
Phase 39C: Payment/Milestone Domain architecture guards (ADR-022).
Mirrors the pattern established in test_checklist_architecture_guards.py
/ test_document_architecture_guards.py / test_task_architecture_guards.py
— pure AST/source inspection, no network, no Google Sheets.

  commercial_milestone_templates/payment_obligations/payment_transactions
  writer                                                 == payment_manager.py only
  PMT/POB/PTXN ID generator                              == payment_manager.py only
  Payment orchestration policy owner                     == business_builder.py only
  payment_manager imports business_builder/telegram      == NO
  No AI/fuzzy matching, no float money                   == YES
  No title-based dedup, no amount/date dedup             == YES
  No arbitrary first-pick                                == YES
  Multiple idempotency matches block                     == YES
  No Roadmap/Stage/Document/Checklist/Task mutation      == YES
  No /startroadmap integration                           == YES
  No Payment Allocation / invoice / expense / ledger      == YES
  No restore/reopen implementation, protection exists    == YES
  No hard delete                                         == YES
  Confirmed Transaction immutability                     == YES
  COMMERCIAL_MILESTONES_MAP / /milestones untouched       == YES
  All result fields always present                       == YES
  All Payment tests hard-socket-blocked                  == YES
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


_PAYMENT_REGISTRIES = {"commercial_milestone_templates", "payment_obligations", "payment_transactions"}

_PAYMENT_ORCHESTRATION_FUNCTIONS = (
    "create_commercial_milestone_template", "transition_commercial_milestone_template_status",
    "update_commercial_milestone_template_admin_fields",
    "create_payment_obligation", "transition_payment_obligation_status", "update_payment_obligation_admin_fields",
    "create_payment_transaction", "confirm_payment_transaction", "reverse_payment_transaction",
    "fail_payment_transaction", "update_payment_transaction_admin_fields",
)


class TestPaymentRegistryWriteOwnership(unittest.TestCase):

    def test_only_payment_manager_writes_payment_registries(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "payment_manager.py"]
        found = _files_writing_registry(candidates, _PAYMENT_REGISTRIES)
        self.assertEqual(found, set(), f"Only payment_manager.py may write Payment registries, found: {found}")

    def test_payment_manager_is_the_writer(self):
        path = BUSINESS_CORE / "payment_manager.py"
        found = _files_writing_registry([path], _PAYMENT_REGISTRIES)
        self.assertEqual(found, {"payment_manager.py"})

    def test_business_builder_does_not_write_payment_registries(self):
        found = _files_writing_registry([BUSINESS_CORE / "business_builder.py"], _PAYMENT_REGISTRIES)
        self.assertEqual(found, set())

    def test_no_payment_allocation_or_invoice_or_ledger_registry_exists(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("payment_allocations", "invoice_registry", "expense_registry", "revenue_registry", "ledger_registry"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)


class TestIdGenerationOwnership(unittest.TestCase):

    def test_payment_manager_generates_ids(self):
        import business_core.payment_manager as pm
        for fn in ("generate_next_template_id", "generate_next_obligation_id", "generate_next_transaction_id"):
            self.assertTrue(callable(getattr(pm, fn, None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "payment_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if any(f"def {fn}" in src for fn in ("generate_next_template_id", "generate_next_obligation_id", "generate_next_transaction_id")):
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_no_caller_side_id_generation_in_orchestration(self):
        for fn_name in ("create_commercial_milestone_template", "create_payment_obligation", "create_payment_transaction"):
            body = _bb_function_body(fn_name)
            for forbidden in ('"PMT-"', '"POB-"', '"PTXN-"', "generate_next_id("):
                self.assertNotIn(forbidden, body)


class TestPaymentOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_payment_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "payment_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "BUSINESS_NOT_FOUND", "STAGE_NOT_FOUND", "ROADMAP_NOT_FOUND", "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND",
            "CLIENT_NOT_FOUND", "MULTIPLE_PAYMENT_OBLIGATION_MATCHES", "MULTIPLE_PAYMENT_TRANSACTION_MATCHES",
            "PAYMENT_ENTITY_RELATION_MISMATCH", "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED",
            "PAYMENT_CURRENCY_MISMATCH", "INVALID_PAYMENT_AMOUNT",
        ):
            self.assertNotIn(
                forbidden, src,
                f"payment_manager.py must not reference {forbidden} — cross-entity relation/overpayment/"
                f"currency/amount policy belongs solely to business_builder.py (ADR-022).",
            )

    def test_amount_currency_normalization_only_in_business_builder(self):
        path = BUSINESS_CORE / "payment_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def normalize_payment_amount", src)
        self.assertNotIn("def normalize_payment_currency", src)
        self.assertNotIn("Decimal(", src)

    def test_balance_calculation_only_in_business_builder(self):
        path = BUSINESS_CORE / "payment_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def _compute_payment_balance", src)
        self.assertNotIn("def _synchronize_payment_obligation", src)


class TestPaymentManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_payment_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "payment_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"payment_manager.py must not import: {found}")

    def test_payment_manager_no_gtd_imports(self):
        path = BUSINESS_CORE / "payment_manager.py"
        found = _imported_module_names(path) & GTD_FORBIDDEN
        self.assertEqual(found, set())


class TestClosedDomainsDoNotImportPaymentManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_payment_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py", "document_manager.py",
            "object_manager.py", "service_manager.py", "person_manager.py", "knowledge_manager.py",
            "checklist_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"payment_manager"}
            self.assertEqual(found, set(), f"{filename} must not import payment_manager")


class TestGtdFilesDoNotImportPaymentDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_payment_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"payment_manager", "business_builder"}
            self.assertNotIn("payment_manager", found, f"{filename} must not import payment_manager")


class TestNoFuzzyMatchingOrTitleDedup(unittest.TestCase):

    def test_obligation_creation_never_looks_up_by_title(self):
        body = _bb_function_body("create_payment_obligation")
        self.assertNotIn("find_obligations_by_title", body)
        self.assertNotIn('"Title Snapshot"] ==', body)

    def test_no_fuzzy_matching_anywhere_in_payment_orchestration(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("difflib", "SequenceMatcher"):
                self.assertNotIn(forbidden, body)

    def test_no_amount_date_dedup_in_obligation_or_transaction_creation(self):
        for fn_name in ("create_payment_obligation", "create_payment_transaction"):
            body = _bb_function_body(fn_name)
            self.assertNotIn('"Obligation Amount"] ==', body)
            self.assertNotIn('"Payment Date"] ==', body)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_obligation_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_payment_obligation")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_multiple_transaction_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_payment_transaction")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_multiple_template_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_commercial_milestone_template")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))


class TestNoClosedDomainMutation(unittest.TestCase):

    def test_no_task_manager_mutation_calls(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("task_manager.create_task(", "task_manager.update_task_status(", "create_business_task(", "transition_task_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task ({forbidden!r} found)")

    def test_no_document_manager_mutation_calls(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("document_manager.create_document(", "document_manager.update_document_status(", "register_document(", "transition_document_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Document ({forbidden!r} found)")

    def test_no_checklist_manager_mutation_calls(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("instantiate_checklist(", "transition_checklist_status(", "transition_checklist_item_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Checklist ({forbidden!r} found)")

    def test_no_stage_roadmap_mutation_calls(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("update_stage_status_in_sheet(", "update_stage_fields(", "recalculate_roadmap_progress(", "maybe_complete_roadmap("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Stage/Roadmap ({forbidden!r} found)")

    def test_no_startroadmap_integration(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("create_payment_obligation", src)
        self.assertNotIn("payment_manager", src)

    def test_no_automatic_obligation_instantiation_anywhere(self):
        for filename in ("roadmap_manager.py", "stage_entity_relations.py", "checklist_manager.py"):
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("create_payment_obligation", src)


class TestCommercialMilestonesMapUntouched(unittest.TestCase):

    def test_map_constant_unchanged_shape(self):
        from business_core.roadmap_manager import COMMERCIAL_MILESTONES_MAP
        self.assertIsInstance(COMMERCIAL_MILESTONES_MAP, dict)
        self.assertIn("RMT-IZH-ALM-STANDARD-002", COMMERCIAL_MILESTONES_MAP)

    def test_payment_manager_never_imports_roadmap_manager(self):
        """payment_manager.py's docstring documents (for humans) that
        COMMERCIAL_MILESTONES_MAP is untouched — this is the structural
        check that it's actually true: no import of roadmap_manager,
        the module where that constant and /milestones live."""
        path = BUSINESS_CORE / "payment_manager.py"
        found = _imported_module_names(path) & {"roadmap_manager"}
        self.assertEqual(found, set())

    def test_business_builder_payment_orchestration_does_not_reference_map(self):
        for fn_name in _PAYMENT_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            self.assertNotIn("COMMERCIAL_MILESTONES_MAP", body)


class TestRestoreReopenProtection(unittest.TestCase):

    def test_no_restore_function_exists(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("def restore_commercial_milestone_template", src)
            self.assertNotIn("def restore_payment_obligation", src)
            self.assertNotIn("def reopen_payment_transaction", src)

    def test_restore_protection_code_exists(self):
        src = (BUSINESS_CORE / "business_builder.py").read_text(encoding="utf-8")
        self.assertIn("COMMERCIAL_MILESTONE_TEMPLATE_RESTORE_REQUIRES_EXPLICIT_ACTION", src)


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        path = BUSINESS_CORE / "payment_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)
        body = "\n".join(_bb_function_body(fn) for fn in _PAYMENT_ORCHESTRATION_FUNCTIONS)
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, body)


class TestConfirmedTransactionImmutability(unittest.TestCase):

    def test_reversal_checks_financial_fields_unchanged(self):
        body = _bb_function_body("reverse_payment_transaction")
        self.assertIn('get("Amount"', body)
        self.assertIn('get("Currency"', body)
        self.assertIn("PAYMENT_TRANSACTION_IMMUTABLE", body)

    def test_admin_update_blocks_identity_fields(self):
        path = BUSINESS_CORE / "payment_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("_TRANSACTION_IDENTITY_FIELDS", src)
        self.assertIn("PAYMENT_TRANSACTION_IMMUTABLE", src)

    def test_no_negative_offset_transaction_created_on_reversal(self):
        body = _bb_function_body("reverse_payment_transaction")
        self.assertNotIn("create_payment_transaction(", body)
        self.assertNotIn("pm_create_transaction(", body)


class TestResultContractFieldsAlwaysPresent(unittest.TestCase):

    _REQUIRED_FIELDS = (
        "ok", "code", "error",
        "commercial_milestone_template_id", "payment_obligation_id", "payment_transaction_id",
        "business_id", "client_id", "object_id", "service_id", "roadmap_id", "stage_id", "document_id",
        "amount", "currency", "paid_amount", "remaining_amount",
        "previous_status", "requested_status", "final_status",
        "created", "reused", "changed", "confirmed", "reversed", "completed",
        "conflicting_ids", "warnings", "retry_safe",
    )

    def test_result_builder_always_includes_all_fields(self):
        import business_core.business_builder as bb
        result = bb._payment_result(ok=True, code="X", error=None)
        for field in self._REQUIRED_FIELDS:
            self.assertIn(field, result, f"missing field {field!r} in _payment_result output")


class TestAllRuntimeCodesAreProducedByCallables(unittest.TestCase):

    def test_key_codes_are_producible(self):
        import business_core.business_builder as bb
        self.assertEqual(bb.create_payment_obligation("", "PRS-001", "100", "KZT")["code"], "BUSINESS_NOT_FOUND")
        self.assertEqual(bb.normalize_payment_amount("-1")["code"], "PAYMENT_AMOUNT_MUST_BE_POSITIVE")
        self.assertEqual(bb.normalize_payment_currency("")["code"], "INVALID_PAYMENT_CURRENCY")


class TestPaymentTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_39c_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_payment_manager.py",
            "test_business_payment_foundation.py",
            "test_payment_architecture_guards.py",
            "test_payment_mock_completeness.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


# ─────────────────────────────────────────────────────────────
# Phase 39D (ADR-022 §18-§26): Payment caller (Telegram) architecture
# guards. Mirrors the Phase 38D Checklist caller guard pattern exactly.
# ─────────────────────────────────────────────────────────────

_PAYMENT_COMMANDS = (
    "newpaymenttemplate_cmd", "paymenttemplates_cmd", "paymenttemplate_cmd", "updatepaymenttemplate_cmd",
    "newobligation_cmd", "obligations_cmd", "obligation_cmd", "updateobligation_cmd",
    "recordpayment_cmd", "payments_cmd", "payment_cmd",
    "confirmpayment_cmd", "reversepayment_cmd", "failpayment_cmd",
)


def _th_function_body(fn_name: str) -> str:
    return _function_body(BUSINESS_CORE / "telegram_handlers.py", fn_name)


class TestPaymentCommandsCallOnlyCanonicalOrchestration(unittest.TestCase):

    def test_no_low_level_payment_manager_write_calls_in_mutating_commands(self):
        forbidden = (
            "payment_manager.create_commercial_milestone_template(", "payment_manager.create_payment_obligation(",
            "payment_manager.create_payment_transaction(", "payment_manager.update_payment_transaction_status(",
            "payment_manager.update_payment_obligation_status(", "payment_manager.update_payment_obligation_balance(",
        )
        for fn_name in (
            "newpaymenttemplate_cmd", "updatepaymenttemplate_cmd", "newobligation_cmd", "updateobligation_cmd",
            "recordpayment_cmd", "confirmpayment_cmd", "reversepayment_cmd", "failpayment_cmd",
        ):
            body = _th_function_body(fn_name)
            for call in forbidden:
                self.assertNotIn(call, body, f"{fn_name} must not call low-level {call.rstrip('(')} directly")

    def test_mutating_commands_call_business_builder_only(self):
        expectations = {
            "newpaymenttemplate_cmd": "create_commercial_milestone_template(",
            "newobligation_cmd": "create_payment_obligation(",
            "recordpayment_cmd": "create_payment_transaction(",
            "confirmpayment_cmd": "confirm_payment_transaction(",
            "reversepayment_cmd": "reverse_payment_transaction(",
            "failpayment_cmd": "fail_payment_transaction(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body, f"{fn_name} must call business_builder.{call.rstrip('(')}")

    def test_read_commands_call_exact_payment_manager_helpers_only(self):
        # obligation_cmd/payment_cmd are enforced (Phase 17E-1): their
        # finder is now passed BY REFERENCE into _resolve_target_in_thread
        # rather than called directly, so a literal "helper(" substring
        # check no longer applies to them — see the dedicated semantic
        # test below. The remaining, unenforced commands still call
        # their manager helper directly and keep the literal check.
        expectations = {
            "paymenttemplates_cmd": "list_commercial_milestone_templates(",
            "paymenttemplate_cmd": "find_commercial_milestone_template_by_id(",
            "obligations_cmd": "list_payment_obligations(",
            "payments_cmd": "list_payment_transactions(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body)
            for forbidden in (
                "create_commercial_milestone_template(", "create_payment_obligation(", "create_payment_transaction(",
                "confirm_payment_transaction(", "reverse_payment_transaction(", "fail_payment_transaction(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} is read-only and must not call {forbidden.rstrip('(')}")

    def test_obligation_and_payment_resolve_finder_through_thread_offload(self):
        """
        Phase 17E-1 semantic replacement for the pre-17E-1 literal
        "find_payment_obligation_by_id("/"find_payment_transaction_by_id("
        substring checks. Those represented a direct synchronous call,
        now obsolete: the approved architecture passes the finder BY
        REFERENCE into _resolve_target_in_thread(finder, record_id).
        Proves: the correct finder object and record-ID variable are
        forwarded, the handler never calls the finder directly, the
        finder is never called outside that one helper call, and
        authorization only runs after the row is resolved.
        """
        expectations = {
            "obligation_cmd": ("find_payment_obligation_by_id", "obligation_id"),
            "payment_cmd": ("find_payment_transaction_by_id", "transaction_id"),
        }
        src = (BUSINESS_CORE / "telegram_handlers.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        nodes_by_name = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

        for fn_name, (finder_name, id_var) in expectations.items():
            with self.subTest(handler=fn_name):
                node = nodes_by_name[fn_name]
                offload_calls, direct_calls = [], []
                for n in ast.walk(node):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                        if n.func.id == "_resolve_target_in_thread":
                            offload_calls.append(n)
                        elif n.func.id == finder_name:
                            direct_calls.append(n)

                self.assertEqual(len(offload_calls), 1)
                call = offload_calls[0]
                self.assertEqual(len(call.args), 2)
                finder_arg, id_arg = call.args
                self.assertIsInstance(finder_arg, ast.Name)
                self.assertEqual(finder_arg.id, finder_name)
                self.assertIsInstance(id_arg, ast.Name)
                self.assertEqual(id_arg.id, id_var)
                self.assertEqual(direct_calls, [], f"{finder_name} must never be called directly in {fn_name}")

                body = _th_function_body(fn_name)
                offload_pos = body.index("_resolve_target_in_thread(")
                authz_pos = body.index("_authorize_or_reply(")
                self.assertLess(offload_pos, authz_pos)


class TestNoCallerSidePaymentPolicy(unittest.TestCase):

    def test_no_caller_side_id_generation(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn('"PMT-"', body)
            self.assertNotIn('"POB-"', body)
            self.assertNotIn('"PTXN-"', body)
            self.assertNotIn("generate_next_id(", body)
            self.assertNotIn("generate_next_ids(", body)

    def test_no_caller_side_amount_normalization(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("Decimal(", body)
            self.assertNotIn("normalize_payment_amount(", body)
            self.assertNotIn("normalize_payment_currency(", body)

    def test_no_caller_side_balance_or_overpayment_policy(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_compute_payment_balance(", body)
            self.assertNotIn("_synchronize_payment_obligation_after_transaction_change(", body)

    def test_no_caller_side_idempotency_lookup(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            for forbidden in (
                "find_obligations_by_caller_key(", "find_obligations_by_template_fallback_key(",
                "find_transactions_by_external_id(", "find_transactions_by_caller_key(",
                "find_templates_by_identity(",
            ):
                self.assertNotIn(forbidden, body)

    def test_no_caller_side_relation_derivation(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_validate_payment_obligation_relations(", body)
            self.assertNotIn("read_business_sheet(", body)

    def test_no_caller_side_transition_matrix(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_PAYMENT_OBLIGATION_ORDINARY_TRANSITIONS", body)
            self.assertNotIn("_PAYMENT_TRANSACTION_ORDINARY_TRANSITIONS", body)
            self.assertNotIn("_COMMERCIAL_MILESTONE_TEMPLATE_ORDINARY_TRANSITIONS", body)

    def test_no_task_document_stage_roadmap_checklist_mutation_calls(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            for forbidden in (
                "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task/Document/Checklist/Stage/Roadmap ({forbidden!r} found)")


class TestPaymentCommandRegistration(unittest.TestCase):

    def test_all_14_commands_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for name in (
            "newpaymenttemplate", "paymenttemplates", "paymenttemplate", "updatepaymenttemplate",
            "newobligation", "obligations", "obligation", "updateobligation",
            "recordpayment", "payments", "payment", "confirmpayment", "reversepayment", "failpayment",
        ):
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_still_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)

    def test_no_bctasks_collision(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        payment_names = {
            "newpaymenttemplate", "paymenttemplates", "paymenttemplate", "updatepaymenttemplate",
            "newobligation", "obligations", "obligation", "updateobligation",
            "recordpayment", "payments", "payment", "confirmpayment", "reversepayment", "failpayment",
        }
        task_names = {"newbctask", "bctasks", "bctask", "updatetask", "assigntask", "reassigntask", "unassigntask"}
        self.assertEqual(payment_names & task_names, set())


class TestPaymentUxHelpersDefinedOnce(unittest.TestCase):

    def test_helpers_defined_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn in (
            "_payment_template_creation_message", "_payment_template_status_message", "_payment_template_admin_message",
            "_payment_obligation_creation_message", "_payment_obligation_status_message", "_payment_obligation_admin_message",
            "_payment_transaction_creation_message", "_payment_transaction_confirmation_message",
            "_payment_transaction_reversal_message", "_payment_transaction_failure_message",
            "_payment_template_status_ru", "_payment_obligation_status_ru", "_payment_transaction_status_ru",
            "_payment_calculation_type_ru", "_format_payment_amount",
        ):
            self.assertEqual(src.count(f"def {fn}("), 1, f"{fn} must be defined exactly once")

    def test_helpers_are_callable(self):
        import business_core.telegram_handlers as th
        for fn in (
            "_payment_template_creation_message", "_payment_obligation_creation_message",
            "_payment_transaction_creation_message", "_payment_transaction_confirmation_message",
            "_payment_transaction_reversal_message", "_payment_transaction_failure_message",
        ):
            self.assertTrue(callable(getattr(th, fn, None)))


class TestNoSensitivePaymentFieldsLogged(unittest.TestCase):

    _DISALLOWED_LOG_TOKENS = (
        "Notes", "External Transaction ID", "Caller Idempotency Key", "Reversal Reason",
        "Payment Method", "update.message.text",
    )

    def test_payment_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestNoRawExceptionInPaymentCommands(unittest.TestCase):

    def test_no_raw_exception_interpolation(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("Ошибка: {e}", body)
            self.assertNotIn("str(e)", body)


class TestPaymentParserValidationOrdering(unittest.TestCase):
    """Insufficient arguments must return before any orchestration call
    — verified structurally: the orchestration import/call must appear
    strictly after the required-argument early-return in source order."""

    def test_newpaymenttemplate_validates_before_orchestration(self):
        body = _th_function_body("newpaymenttemplate_cmd")
        validation_idx = body.index("if not title or not calculation_type or not currency")
        orchestration_idx = body.index("create_commercial_milestone_template(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_newobligation_validates_before_orchestration(self):
        body = _th_function_body("newobligation_cmd")
        validation_idx = body.index("if not business_id or not client_id or not amount or not currency")
        orchestration_idx = body.index("create_payment_obligation(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_recordpayment_validates_before_orchestration(self):
        body = _th_function_body("recordpayment_cmd")
        validation_idx = body.index("if not business_id or not obligation_id or not client_id")
        orchestration_idx = body.index("create_payment_transaction(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_confirmpayment_validates_before_orchestration(self):
        body = _th_function_body("confirmpayment_cmd")
        validation_idx = body.index("if not transaction_id or not confirmed_by")
        orchestration_idx = body.index("confirm_payment_transaction(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_reversepayment_validates_before_orchestration(self):
        body = _th_function_body("reversepayment_cmd")
        validation_idx = body.index("if not transaction_id or not reversal_reason or not reversed_by")
        orchestration_idx = body.index("reverse_payment_transaction(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_failpayment_validates_before_orchestration(self):
        body = _th_function_body("failpayment_cmd")
        validation_idx = body.index("if not transaction_id")
        orchestration_idx = body.index("fail_payment_transaction(")
        self.assertLess(validation_idx, orchestration_idx)


class TestPaymentParseModeIsNone(unittest.TestCase):

    def test_all_payment_commands_pass_parse_mode_none(self):
        for fn_name in _PAYMENT_COMMANDS:
            body = _th_function_body(fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")


class TestMilestonesCommandUntouchedByCallerPhase(unittest.TestCase):

    def test_milestones_body_unchanged_shape(self):
        body = _th_function_body("milestones_cmd")
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("payment_manager", body)
        self.assertNotIn("create_payment_obligation", body)


if __name__ == "__main__":
    unittest.main()
