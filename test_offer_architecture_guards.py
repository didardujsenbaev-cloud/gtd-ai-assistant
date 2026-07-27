"""
Phase 40C: Commercial Offer Domain architecture guards (ADR-023).
Mirrors the pattern established in test_payment_architecture_guards.py
— pure AST/source inspection, no network, no Google Sheets.

  commercial_offers writer                              == offer_manager.py only
  OFR/OFS ID generator                                   == offer_manager.py only
  Commercial Offer orchestration policy owner            == business_builder.py only
  offer_manager imports business_builder/telegram        == NO
  No AI/fuzzy matching, no float money                   == YES
  No title-based dedup, no amount/date dedup             == YES
  No arbitrary first-pick                                == YES
  Multiple idempotency matches block                     == YES
  Immutable version rows, branching prevention           == YES
  No mutable Is Current flag                             == YES
  No Roadmap/Stage/Document/Service/Client/Payment mutation == YES
  No Payment Obligation creation, no percentage integration == YES
  No Contract/Invoice/line-item registry                 == YES
  No restore/reopen implementation, protection exists    == YES
  No hard delete                                         == YES
  All result fields always present                       == YES
  All Offer tests hard-socket-blocked                    == YES
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


_OFFER_REGISTRIES = {"commercial_offers"}

_OFFER_ORCHESTRATION_FUNCTIONS = (
    "create_commercial_offer", "revise_commercial_offer",
    "send_commercial_offer", "accept_commercial_offer", "reject_commercial_offer",
    "expire_commercial_offer", "cancel_commercial_offer", "archive_commercial_offer",
    "update_commercial_offer_draft", "update_commercial_offer_admin_fields",
)


class TestOfferRegistryWriteOwnership(unittest.TestCase):

    def test_only_offer_manager_writes_offer_registry(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "offer_manager.py"]
        found = _files_writing_registry(candidates, _OFFER_REGISTRIES)
        self.assertEqual(found, set(), f"Only offer_manager.py may write commercial_offers, found: {found}")

    def test_offer_manager_is_the_writer(self):
        path = BUSINESS_CORE / "offer_manager.py"
        found = _files_writing_registry([path], _OFFER_REGISTRIES)
        self.assertEqual(found, {"offer_manager.py"})

    def test_business_builder_does_not_write_offer_registry(self):
        found = _files_writing_registry([BUSINESS_CORE / "business_builder.py"], _OFFER_REGISTRIES)
        self.assertEqual(found, set())

    def test_no_line_item_contract_invoice_registry_exists(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("commercial_offer_line_items", "contract_registry", "invoice_registry"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)


class TestIdGenerationOwnership(unittest.TestCase):

    def test_offer_manager_generates_ids(self):
        import business_core.offer_manager as om
        for fn in ("generate_next_offer_id", "generate_next_series_id"):
            self.assertTrue(callable(getattr(om, fn, None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "offer_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if any(f"def {fn}" in src for fn in ("generate_next_offer_id", "generate_next_series_id")):
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_no_caller_side_id_generation_in_orchestration(self):
        for fn_name in ("create_commercial_offer", "revise_commercial_offer"):
            body = _bb_function_body(fn_name)
            for forbidden in ('"OFR-"', '"OFS-"', "generate_next_id("):
                self.assertNotIn(forbidden, body)


class TestOfferOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in _OFFER_ORCHESTRATION_FUNCTIONS:
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_offer_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "BUSINESS_NOT_FOUND", "CLIENT_NOT_FOUND", "SERVICE_NOT_FOUND", "ROADMAP_NOT_FOUND", "DOCUMENT_NOT_FOUND",
            "MULTIPLE_COMMERCIAL_OFFER_MATCHES", "COMMERCIAL_OFFER_RELATION_MISMATCH", "COMMERCIAL_OFFER_CONTEXT_REQUIRED",
            "COMMERCIAL_OFFER_NOT_LATEST_VERSION", "INVALID_COMMERCIAL_OFFER_AMOUNT", "INVALID_COMMERCIAL_OFFER_CURRENCY",
        ):
            self.assertNotIn(
                forbidden, src,
                f"offer_manager.py must not reference {forbidden} — cross-entity relation/amount/currency/"
                f"version policy belongs solely to business_builder.py (ADR-023).",
            )

    def test_amount_currency_date_normalization_only_in_business_builder(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def normalize_commercial_offer_amount", src)
        self.assertNotIn("def normalize_commercial_offer_currency", src)
        self.assertNotIn("def normalize_commercial_offer_valid_until", src)
        self.assertNotIn("Decimal(", src)

    def test_revision_and_branching_policy_only_in_business_builder(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def revise_commercial_offer", src)


class TestOfferManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_offer_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "offer_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"offer_manager.py must not import: {found}")

    def test_offer_manager_no_gtd_imports(self):
        path = BUSINESS_CORE / "offer_manager.py"
        found = _imported_module_names(path) & GTD_FORBIDDEN
        self.assertEqual(found, set())

    def test_offer_manager_never_imports_payment_manager(self):
        """Offer amount/currency codes must be entirely Offer-local
        (ADR-023 §10) — offer_manager.py should have no reason to
        touch payment_manager.py at all."""
        path = BUSINESS_CORE / "offer_manager.py"
        found = _imported_module_names(path) & {"payment_manager"}
        self.assertEqual(found, set())


class TestClosedDomainsDoNotImportOfferManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_offer_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py", "document_manager.py",
            "object_manager.py", "service_manager.py", "person_manager.py", "knowledge_manager.py",
            "checklist_manager.py", "payment_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"offer_manager"}
            self.assertEqual(found, set(), f"{filename} must not import offer_manager")


class TestGtdFilesDoNotImportOfferDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_offer_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"offer_manager", "business_builder"}
            self.assertNotIn("offer_manager", found, f"{filename} must not import offer_manager")


class TestNoFuzzyMatchingOrTitleDedup(unittest.TestCase):

    def test_creation_never_looks_up_by_title(self):
        body = _bb_function_body("create_commercial_offer")
        self.assertNotIn("find_offers_by_title", body)
        self.assertNotIn('"Title Snapshot"] ==', body)

    def test_no_fuzzy_matching_anywhere_in_offer_orchestration(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("difflib", "SequenceMatcher"):
                self.assertNotIn(forbidden, body)

    def test_no_amount_date_dedup_in_creation_or_revision(self):
        for fn_name in ("create_commercial_offer", "revise_commercial_offer"):
            body = _bb_function_body(fn_name)
            self.assertNotIn('"Quoted Amount"] ==', body)
            self.assertNotIn('"Valid Until"] ==', body)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_offer_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_commercial_offer")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_revision_multiple_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("revise_commercial_offer")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_latest_version_duplicate_max_blocks_no_first_pick(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("len(at_max) > 1", src)
        self.assertIn("COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR", src)


class TestImmutableVersioningAndBranchingPrevention(unittest.TestCase):

    def test_no_mutable_is_current_field_in_schema(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertNotIn("Is Current", BUSINESS_HEADERS["commercial_offers"])

    def test_revision_creates_new_row_never_updates_source(self):
        body = _bb_function_body("revise_commercial_offer")
        self.assertIn("om_create_offer(", body)
        self.assertNotIn("update_commercial_offer_status(", body)
        self.assertNotIn("update_commercial_offer_draft_fields(", body)

    def test_branching_prevention_check_exists(self):
        body = _bb_function_body("revise_commercial_offer")
        self.assertIn("Previous Commercial Offer ID", body)
        self.assertIn("COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR", body)

    def test_latest_version_is_derived_not_stored(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("def find_latest_commercial_offer_in_series", src)
        self.assertIn("max(", src)


class TestNoClosedDomainMutation(unittest.TestCase):

    def test_no_task_manager_mutation_calls(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("task_manager.create_task(", "create_business_task(", "transition_task_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task ({forbidden!r} found)")

    def test_no_document_manager_mutation_calls(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("document_manager.create_document(", "register_document(", "transition_document_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Document ({forbidden!r} found)")

    def test_no_checklist_manager_mutation_calls(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("instantiate_checklist(", "transition_checklist_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Checklist ({forbidden!r} found)")

    def test_no_payment_mutation_or_obligation_creation(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "create_payment_obligation(", "create_payment_transaction(",
                "confirm_payment_transaction(", "reverse_payment_transaction(",
                "payment_manager.create_payment_obligation(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Payment ({forbidden!r} found)")

    def test_no_stage_roadmap_mutation_calls(self):
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("update_stage_status_in_sheet(", "recalculate_roadmap_progress(", "maybe_complete_roadmap("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Stage/Roadmap ({forbidden!r} found)")

    def test_no_startroadmap_integration(self):
        path = BUSINESS_CORE / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("create_commercial_offer", src)
        self.assertNotIn("offer_manager", src)

    def test_no_percentage_payment_template_integration(self):
        """No Commercial Offer function may reach into Payment's
        percentage-Template calculation path (ADR-023 §27)."""
        for fn_name in _OFFER_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            self.assertNotIn("create_commercial_milestone_template(", body)
            self.assertNotIn("Calculation Type", body)


class TestRestoreReopenProtection(unittest.TestCase):

    def test_no_restore_function_exists(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("def restore_commercial_offer", src)
            self.assertNotIn("def reopen_commercial_offer", src)

    def test_restore_protection_code_referenced(self):
        """ADR-023 requires restore protection to exist — Foundation's
        closed transition matrix itself is the protection (archived/
        rejected/expired/cancelled have no path back to draft/sent/
        accepted), verified structurally via the transition dict."""
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn('"archived":  ("archived",)', src.replace("  ", "  ").replace("\n", "\n") or src)


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        path = BUSINESS_CORE / "offer_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)
        body = "\n".join(_bb_function_body(fn) for fn in _OFFER_ORCHESTRATION_FUNCTIONS)
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, body)


class TestResultContractFieldsAlwaysPresent(unittest.TestCase):

    _REQUIRED_FIELDS = (
        "ok", "code", "error",
        "commercial_offer_id", "offer_series_id", "previous_commercial_offer_id", "version_number",
        "business_id", "client_id", "object_id", "service_id", "roadmap_id", "document_id",
        "amount", "currency", "valid_until",
        "previous_status", "requested_status", "final_status",
        "created", "reused", "changed", "revised",
        "sent", "accepted", "rejected", "expired", "cancelled", "archived",
        "conflicting_ids", "warnings", "retry_safe",
    )

    def test_result_builder_always_includes_all_fields(self):
        import business_core.business_builder as bb
        result = bb._offer_result(ok=True, code="X", error=None)
        for field in self._REQUIRED_FIELDS:
            self.assertIn(field, result, f"missing field {field!r} in _offer_result output")


class TestAllRuntimeCodesAreProducedByCallables(unittest.TestCase):

    def test_key_codes_are_producible(self):
        import business_core.business_builder as bb
        self.assertEqual(bb.create_commercial_offer("", "PRS-001", "T", "S", "100", "KZT", "2026-12-31", caller_idempotency_key="K1")["code"], "BUSINESS_NOT_FOUND")
        self.assertEqual(bb.normalize_commercial_offer_amount("-1")["code"], "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE")
        self.assertEqual(bb.normalize_commercial_offer_currency("")["code"], "INVALID_COMMERCIAL_OFFER_CURRENCY")


class TestOfferTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_40c_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_offer_manager.py",
            "test_business_offer_foundation.py",
            "test_offer_architecture_guards.py",
            "test_offer_mock_completeness.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


# ─────────────────────────────────────────────────────────────
# Phase 40D (ADR-023): Commercial Offer caller (Telegram) architecture
# guards. Mirrors the Phase 39D Payment caller guard pattern exactly.
# ─────────────────────────────────────────────────────────────

_OFFER_COMMANDS = (
    "newoffer_cmd", "offers_cmd", "offer_cmd", "reviseoffer_cmd", "updateoffer_cmd",
    "sendoffer_cmd", "acceptoffer_cmd", "rejectoffer_cmd", "expireoffer_cmd",
    "canceloffer_cmd", "archiveoffer_cmd",
)


def _th_function_body(fn_name: str) -> str:
    return _function_body(BUSINESS_CORE / "telegram_handlers.py", fn_name)


class TestOfferCommandsCallOnlyCanonicalOrchestration(unittest.TestCase):

    def test_no_low_level_offer_manager_write_calls_in_mutating_commands(self):
        forbidden = (
            "offer_manager.create_commercial_offer(", "offer_manager.update_commercial_offer_status(",
            "offer_manager.update_commercial_offer_draft_fields(", "offer_manager.update_commercial_offer_admin_fields(",
        )
        for fn_name in (
            "newoffer_cmd", "reviseoffer_cmd", "updateoffer_cmd", "sendoffer_cmd", "acceptoffer_cmd",
            "rejectoffer_cmd", "expireoffer_cmd", "canceloffer_cmd", "archiveoffer_cmd",
        ):
            body = _th_function_body(fn_name)
            for call in forbidden:
                self.assertNotIn(call, body, f"{fn_name} must not call low-level {call.rstrip('(')} directly")

    def test_mutating_commands_call_business_builder_only(self):
        expectations = {
            "newoffer_cmd": "create_commercial_offer(",
            "reviseoffer_cmd": "revise_commercial_offer(",
            "sendoffer_cmd": "send_commercial_offer(",
            "acceptoffer_cmd": "accept_commercial_offer(",
            "rejectoffer_cmd": "reject_commercial_offer(",
            "expireoffer_cmd": "expire_commercial_offer(",
            "canceloffer_cmd": "cancel_commercial_offer(",
            "archiveoffer_cmd": "archive_commercial_offer(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body, f"{fn_name} must call business_builder.{call.rstrip('(')}")

    def test_read_commands_call_exact_offer_manager_helpers_only(self):
        expectations = {
            "offers_cmd": "list_commercial_offers(",
            "offer_cmd": "find_commercial_offer_by_id(",
        }
        for fn_name, call in expectations.items():
            body = _th_function_body(fn_name)
            self.assertIn(call, body)
            for forbidden in (
                "create_commercial_offer(", "revise_commercial_offer(",
                "send_commercial_offer(", "accept_commercial_offer(", "reject_commercial_offer(",
                "expire_commercial_offer(", "cancel_commercial_offer(", "archive_commercial_offer(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} is read-only and must not call {forbidden.rstrip('(')}")


class TestNoCallerSideOfferPolicy(unittest.TestCase):

    def test_no_caller_side_id_generation(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn('"OFR-"', body)
            self.assertNotIn('"OFS-"', body)
            self.assertNotIn("generate_next_id(", body)
            self.assertNotIn("generate_next_ids(", body)

    def test_no_caller_side_amount_currency_date_normalization(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("Decimal(", body)
            self.assertNotIn("normalize_commercial_offer_amount(", body)
            self.assertNotIn("normalize_commercial_offer_currency(", body)
            self.assertNotIn("normalize_commercial_offer_valid_until(", body)

    def test_no_caller_side_relation_or_idempotency_policy(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_validate_commercial_offer_relations(", body)
            self.assertNotIn("find_commercial_offers_by_idempotency_key(", body)
            self.assertNotIn("read_business_sheet(", body)

    def test_no_caller_side_version_or_branching_policy(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("find_latest_commercial_offer_in_series(", body)
            self.assertNotIn("generate_next_series_id(", body)

    def test_no_caller_side_transition_matrix(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("_COMMERCIAL_OFFER_ORDINARY_TRANSITIONS", body)

    def test_no_payment_or_closed_domain_mutation_calls(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            for forbidden in (
                "create_payment_obligation(", "create_payment_transaction(",
                "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Payment/Task/Document/Checklist/Stage/Roadmap ({forbidden!r} found)")


class TestOfferCommandRegistration(unittest.TestCase):

    def test_all_11_commands_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for name in ("newoffer", "offers", "offer", "reviseoffer", "updateoffer", "sendoffer", "acceptoffer", "rejectoffer", "expireoffer", "canceloffer", "archiveoffer"):
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_still_registered_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)


class TestOfferUxHelpersDefinedOnce(unittest.TestCase):

    def test_helpers_defined_exactly_once(self):
        path = BUSINESS_CORE / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for fn in (
            "_offer_creation_message", "_offer_revision_message", "_offer_update_message",
            "_offer_lifecycle_message", "_offer_status_ru", "_format_offer_amount",
        ):
            self.assertEqual(src.count(f"def {fn}("), 1, f"{fn} must be defined exactly once")

    def test_helpers_are_callable(self):
        import business_core.telegram_handlers as th
        for fn in ("_offer_creation_message", "_offer_revision_message", "_offer_update_message", "_offer_lifecycle_message"):
            self.assertTrue(callable(getattr(th, fn, None)))


class TestNoSensitiveOfferFieldsLoggedGuard(unittest.TestCase):

    _DISALLOWED_LOG_TOKENS = ("Scope Snapshot", "Notes", "Caller Idempotency Key", "Rejection Reason", "Cancellation Reason", "update.message.text")

    def test_offer_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestNoRawExceptionInOfferCommands(unittest.TestCase):

    def test_no_raw_exception_interpolation(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            self.assertNotIn("Ошибка: {e}", body)
            self.assertNotIn("str(e)", body)


class TestOfferParserValidationOrdering(unittest.TestCase):

    def test_newoffer_validates_before_orchestration(self):
        body = _th_function_body("newoffer_cmd")
        validation_idx = body.index("if not business_id or not client_id or not title or not scope")
        orchestration_idx = body.index("create_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_reviseoffer_validates_before_orchestration(self):
        body = _th_function_body("reviseoffer_cmd")
        validation_idx = body.index("if not source_id or not caller_idempotency_key")
        orchestration_idx = body.index("revise_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_sendoffer_validates_before_orchestration(self):
        body = _th_function_body("sendoffer_cmd")
        validation_idx = body.index("if not offer_id or not sent_by")
        orchestration_idx = body.index("send_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_acceptoffer_validates_before_orchestration(self):
        body = _th_function_body("acceptoffer_cmd")
        validation_idx = body.index("if not offer_id or not accepted_by")
        orchestration_idx = body.index("accept_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_rejectoffer_validates_before_orchestration(self):
        body = _th_function_body("rejectoffer_cmd")
        validation_idx = body.index("if not offer_id or not rejected_by or not rejection_reason")
        orchestration_idx = body.index("reject_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_canceloffer_validates_before_orchestration(self):
        body = _th_function_body("canceloffer_cmd")
        validation_idx = body.index("if not offer_id or not cancelled_by or not cancellation_reason")
        orchestration_idx = body.index("cancel_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)

    def test_archiveoffer_validates_before_orchestration(self):
        body = _th_function_body("archiveoffer_cmd")
        validation_idx = body.index("if not offer_id")
        orchestration_idx = body.index("archive_commercial_offer(")
        self.assertLess(validation_idx, orchestration_idx)


class TestOfferParseModeIsNone(unittest.TestCase):

    def test_all_offer_commands_pass_parse_mode_none(self):
        for fn_name in _OFFER_COMMANDS:
            body = _th_function_body(fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")


class TestMilestonesCommandUntouchedByCallerPhase(unittest.TestCase):

    def test_milestones_body_unchanged_shape(self):
        body = _th_function_body("milestones_cmd")
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("offer_manager", body)
        self.assertNotIn("create_commercial_offer", body)


if __name__ == "__main__":
    unittest.main()
