"""
Phase 41C: Lead / Sales Funnel Domain architecture guards (ADR-024).
Mirrors the pattern established in test_payment_architecture_guards.py/
test_offer_architecture_guards.py — pure AST/source inspection, no
network, no Google Sheets.

  leads writer                                          == lead_manager.py only
  LED ID generator                                      == lead_manager.py only
  Lead orchestration policy owner                       == business_builder.py only
  lead_manager imports business_builder/telegram         == NO
  Idempotency distinct from duplicate detection          == YES
  No fuzzy/name-based dedup, no first-pick               == YES
  Multiple idempotency matches block                     == YES
  Duplicate-contact warning returns all IDs, never merges == YES
  No Deal/Interaction/Campaign registry                  == YES
  No Object/Roadmap/Commercial Offer/Payment/Task mutation == YES
  No automatic Client creation, no Person mutation        == YES
  No relationship_capital reuse                          == YES
  Expected Value never propagated to Offer/Payment        == YES
  No restore/reopen implementation                        == YES
  No hard delete                                          == YES
  All result fields always present                        == YES
  All Lead tests hard-socket-blocked                      == YES
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


_LEAD_REGISTRIES = {"leads"}

_LEAD_ORCHESTRATION_FUNCTIONS = (
    "create_lead", "contact_lead", "qualify_lead", "unqualify_lead", "lose_lead",
    "archive_lead", "convert_lead", "update_lead", "update_lead_admin_fields",
)


class TestLeadRegistryWriteOwnership(unittest.TestCase):

    def test_only_lead_manager_writes_lead_registry(self):
        candidates = [p for p in BUSINESS_CORE.glob("*.py") if p.name != "lead_manager.py"]
        found = _files_writing_registry(candidates, _LEAD_REGISTRIES)
        self.assertEqual(found, set(), f"Only lead_manager.py may write leads, found: {found}")

    def test_lead_manager_is_the_writer(self):
        path = BUSINESS_CORE / "lead_manager.py"
        found = _files_writing_registry([path], _LEAD_REGISTRIES)
        self.assertEqual(found, {"lead_manager.py"})

    def test_business_builder_does_not_write_lead_registry(self):
        found = _files_writing_registry([BUSINESS_CORE / "business_builder.py"], _LEAD_REGISTRIES)
        self.assertEqual(found, set())

    def test_no_deal_interaction_campaign_registry_exists(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in (
            "deal_registry", "deals", "interaction_registry", "interactions",
            "lead_interactions", "campaign_registry", "utm_registry",
        ):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)


class TestIdGenerationOwnership(unittest.TestCase):

    def test_lead_manager_generates_ids(self):
        import business_core.lead_manager as lm
        self.assertTrue(callable(getattr(lm, "generate_next_lead_id", None)))

    def test_no_second_id_generator_anywhere_in_business_core(self):
        hits = []
        for path in BUSINESS_CORE.glob("*.py"):
            if path.name == "lead_manager.py":
                continue
            src = path.read_text(encoding="utf-8")
            if "def generate_next_lead_id" in src:
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_no_caller_side_id_generation_in_orchestration(self):
        body = _bb_function_body("create_lead")
        for forbidden in ('"LED-"', "generate_next_id("):
            self.assertNotIn(forbidden, body)


class TestLeadOrchestrationOwnerIsBusinessBuilder(unittest.TestCase):

    def test_all_orchestration_functions_defined_in_business_builder(self):
        import business_core.business_builder as bb
        for fn in _LEAD_ORCHESTRATION_FUNCTIONS:
            self.assertTrue(callable(getattr(bb, fn, None)), f"{fn} must be defined in business_builder.py")

    def test_lead_manager_does_not_implement_cross_entity_policy_codes(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in (
            "BUSINESS_NOT_FOUND", "SERVICE_NOT_FOUND", "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND", "CLIENT_NOT_FOUND",
            "MULTIPLE_LEAD_MATCHES", "LEAD_RELATION_MISMATCH", "LEAD_CONTACT_CHANNEL_REQUIRED",
            "INVALID_LEAD_PHONE", "INVALID_LEAD_WHATSAPP", "INVALID_LEAD_EMAIL",
            "INVALID_LEAD_EXPECTED_VALUE", "INVALID_LEAD_CURRENCY", "INVALID_LEAD_DATETIME",
        ):
            self.assertNotIn(
                forbidden, src,
                f"lead_manager.py must not reference {forbidden} — cross-entity relation/contact/"
                f"value normalization policy belongs solely to business_builder.py (ADR-024).",
            )

    def test_contact_expected_value_datetime_normalization_only_in_business_builder(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden_fn in (
            "def normalize_lead_phone", "def normalize_lead_whatsapp", "def normalize_lead_email",
            "def normalize_lead_expected_value", "def normalize_lead_currency", "def normalize_lead_datetime",
        ):
            self.assertNotIn(forbidden_fn, src)
        self.assertNotIn("Decimal(", src)

    def test_lifecycle_and_conversion_policy_only_in_business_builder(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("def convert_lead", src)
        self.assertNotIn("_LEAD_ORDINARY_TRANSITIONS", src)


class TestLeadManagerDependencyDirection(unittest.TestCase):

    _FORBIDDEN = {"business_builder", "telegram_handlers"}

    def test_lead_manager_no_forbidden_imports(self):
        path = BUSINESS_CORE / "lead_manager.py"
        found = _imported_module_names(path) & self._FORBIDDEN
        self.assertEqual(found, set(), f"lead_manager.py must not import: {found}")

    def test_lead_manager_no_gtd_imports(self):
        path = BUSINESS_CORE / "lead_manager.py"
        found = _imported_module_names(path) & GTD_FORBIDDEN
        self.assertEqual(found, set())

    def test_lead_manager_never_imports_person_manager(self):
        """Lead is fully separate from Person/Client (ADR-024 §1/§3) —
        lead_manager.py itself should never even import person_manager;
        all Client/Person validation lives in business_builder.py."""
        path = BUSINESS_CORE / "lead_manager.py"
        found = _imported_module_names(path) & {"person_manager"}
        self.assertEqual(found, set())

    def test_lead_manager_never_imports_offer_or_payment_manager(self):
        path = BUSINESS_CORE / "lead_manager.py"
        found = _imported_module_names(path) & {"offer_manager", "payment_manager"}
        self.assertEqual(found, set())


class TestClosedDomainsDoNotImportLeadManager(unittest.TestCase):

    def test_no_closed_domain_file_imports_lead_manager(self):
        closed_domain_files = (
            "organization_manager.py", "work_assignment_manager.py", "task_manager.py",
            "roadmap_manager.py", "stage_entity_relations.py", "document_manager.py",
            "object_manager.py", "service_manager.py", "person_manager.py", "knowledge_manager.py",
            "checklist_manager.py", "payment_manager.py", "offer_manager.py",
        )
        for filename in closed_domain_files:
            path = BUSINESS_CORE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"lead_manager"}
            self.assertEqual(found, set(), f"{filename} must not import lead_manager")


class TestGtdFilesDoNotImportLeadDomain(unittest.TestCase):

    def test_gtd_files_do_not_import_lead_modules(self):
        gtd_files = ("inbox_processor.py", "telegram_bot.py", "project_planner.py", "calendar_sync.py")
        for filename in gtd_files:
            path = WORKSPACE / filename
            if not path.exists():
                continue
            found = _imported_module_names(path) & {"lead_manager"}
            self.assertEqual(found, set(), f"{filename} must not import lead_manager")


class TestIdempotencyDistinctFromDuplicateDetection(unittest.TestCase):

    def test_two_distinct_lookup_functions_exist(self):
        import business_core.lead_manager as lm
        self.assertTrue(callable(lm.find_leads_by_idempotency_key))
        self.assertTrue(callable(lm.find_leads_by_exact_contact_channels))
        self.assertIsNot(lm.find_leads_by_idempotency_key, lm.find_leads_by_exact_contact_channels)

    def test_duplicate_warning_never_blocks_creation(self):
        body = _bb_function_body("create_lead")
        # The duplicate-contact lookup result feeds only warnings/
        # duplicate_contact_ids — it must never itself return early.
        dup_idx = body.rindex("find_leads_by_exact_contact_channels")
        after_dup = body[dup_idx:]
        self.assertNotIn("return _lead_result(ok=False", after_dup.split("lm_create_lead(")[0])

    def test_duplicate_warning_returns_all_ids_never_first_pick(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("def find_leads_by_exact_contact_channels", src)
        self.assertNotIn("matches[0]", src)


class TestNoArbitraryFirstSelection(unittest.TestCase):

    def test_multiple_lead_matches_never_pick_index_zero_silently(self):
        body = _bb_function_body("create_lead")
        self.assertIn("len(matches) > 1", body)
        self.assertLess(body.index("len(matches) > 1"), body.index("matches[0]"))

    def test_no_fuzzy_matching_anywhere_in_lead_orchestration(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("difflib", "SequenceMatcher"):
                self.assertNotIn(forbidden, body)

    def test_no_name_based_or_company_based_dedup(self):
        for fn_name in ("create_lead",):
            body = _bb_function_body(fn_name)
            self.assertNotIn('"Contact Name Snapshot"] ==', body)
            self.assertNotIn('"Company Snapshot"] ==', body)


class TestNoClosedDomainMutation(unittest.TestCase):

    def test_no_task_manager_mutation_calls(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("task_manager.create_task(", "create_business_task(", "transition_task_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Task ({forbidden!r} found)")

    def test_no_document_manager_mutation_calls(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("document_manager.create_document(", "register_document(", "transition_document_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Document ({forbidden!r} found)")

    def test_no_checklist_manager_mutation_calls(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("instantiate_checklist(", "transition_checklist_status("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Checklist ({forbidden!r} found)")

    def test_no_payment_mutation_or_obligation_creation(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in (
                "create_payment_obligation(", "create_payment_transaction(",
                "confirm_payment_transaction(", "reverse_payment_transaction(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Payment ({forbidden!r} found)")

    def test_no_commercial_offer_mutation_or_creation(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("create_commercial_offer(", "revise_commercial_offer(", "accept_commercial_offer("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Commercial Offer ({forbidden!r} found)")

    def test_no_roadmap_object_stage_mutation_calls(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("create_roadmap_for_object(", "update_stage_status_in_sheet(", "create_object("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Object/Roadmap/Stage ({forbidden!r} found)")

    def test_no_person_or_client_creation_or_mutation(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            for forbidden in ("create_person(", "update_person(", "update_person_drive_info("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Person/Client ({forbidden!r} found)")

    def test_no_relationship_capital_reuse(self):
        for fn_name in _LEAD_ORCHESTRATION_FUNCTIONS:
            body = _bb_function_body(fn_name)
            self.assertNotIn("relationship_capital", body)
            self.assertNotIn("RelationshipTouch", body)
            self.assertNotIn("create_touch_record", body)


class TestExpectedValueNeverPropagated(unittest.TestCase):

    def test_expected_value_normalization_never_leaks_payment_or_offer_codes(self):
        import business_core.business_builder as bb
        for raw in (100.5, "100,000", "1e5", "0", "-1", "100.123"):
            result = bb.normalize_lead_expected_value(raw)
            self.assertFalse(result["ok"])
            self.assertNotIn("PAYMENT", result["code"])
            self.assertNotIn("OFFER", result["code"])

    def test_creation_never_creates_offer_or_obligation(self):
        body = _bb_function_body("create_lead")
        for forbidden in ("create_commercial_offer(", "create_payment_obligation("):
            self.assertNotIn(forbidden, body)


class TestRestoreReopenProtection(unittest.TestCase):

    def test_no_restore_function_exists(self):
        for path in BUSINESS_CORE.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("def restore_lead", src)
            self.assertNotIn("def reopen_lead", src)

    def test_restore_protection_code_referenced(self):
        """ADR-024 requires restore protection to exist — Foundation's
        closed transition matrix itself is the protection (unqualified/
        lost/archived have no path back to new/contacted/qualified),
        verified structurally via the transition dict and its explicit
        LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION code."""
        path = BUSINESS_CORE / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn('"archived":     ("archived",)', src)
        self.assertIn("LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION", src)


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        path = BUSINESS_CORE / "lead_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)
        body = "\n".join(_bb_function_body(fn) for fn in _LEAD_ORCHESTRATION_FUNCTIONS)
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, body)


class TestResultContractFieldsAlwaysPresent(unittest.TestCase):

    _REQUIRED_FIELDS = (
        "ok", "code", "error",
        "lead_id", "business_id", "service_id", "channel_id",
        "assigned_person_id", "converted_client_id",
        "expected_value", "currency", "next_follow_up_at", "last_contacted_at",
        "previous_status", "requested_status", "final_status",
        "created", "reused", "changed",
        "contacted", "qualified", "unqualified", "converted", "lost", "archived",
        "duplicate_contact_ids", "conflicting_ids", "warnings", "retry_safe",
    )

    def test_result_builder_always_includes_all_fields(self):
        import business_core.business_builder as bb
        result = bb._lead_result(ok=True, code="X", error=None)
        for field in self._REQUIRED_FIELDS:
            self.assertIn(field, result, f"missing field {field!r} in _lead_result output")

    def test_result_never_includes_contact_or_disposition_text(self):
        import business_core.business_builder as bb
        result = bb._lead_result(ok=True, code="X", error=None)
        for forbidden in ("contact_name_snapshot", "phone_snapshot", "whatsapp_snapshot", "email_snapshot",
                          "company_snapshot", "qualification_notes", "disposition_reason", "notes"):
            self.assertNotIn(forbidden, result)


class TestAllRuntimeCodesAreProducedByCallables(unittest.TestCase):

    def test_key_codes_are_producible(self):
        import business_core.business_builder as bb
        self.assertEqual(bb.create_lead("", "Ivan", created_by="admin", caller_idempotency_key="k")["code"], "BUSINESS_NOT_FOUND")
        self.assertEqual(bb.normalize_lead_currency("")["code"], "INVALID_LEAD_CURRENCY")
        self.assertEqual(bb.normalize_lead_expected_value("-1")["code"], "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE")


class TestLeadTestsHaveHardSocketBlock(unittest.TestCase):

    def test_phase_41c_test_files_registered(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        for filename in (
            "test_lead_manager.py",
            "test_business_lead_foundation.py",
            "test_lead_architecture_guards.py",
            "test_lead_mock_completeness.py",
        ):
            self.assertIn(filename, conftest_src, f"{filename} must be registered in conftest.py's hard socket-block set")


class TestNoTelegramCallerYet(unittest.TestCase):
    """Phase 41C is explicitly Foundation-only — no Telegram command
    for Lead may exist yet (that is Phase 41D's scope)."""

    def test_no_lead_commands_registered(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("newlead_cmd", "leads_cmd", "convertlead_cmd", "qualifylead_cmd"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
