"""
Phase 17E-1 / 17E-2A: Command Enforcement architecture guards.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

Pure inventory/architecture tests — no domain behavior is exercised
here (that belongs to test_business_core_read_enforcement.py and
test_mutation_enforcement.py). These tests prove the STRUCTURE of the
enforcement rollout: the six Phase 17E-1 read commands remain
unchanged, the Phase 17E-2A mutation command (updateinteractionnotes)
and the Phase 17E-2A2 dedicated command (updateleadnotes) were added,
no other command changed — in particular /updatelead and
/updateobligation remain entirely outside this map — no resource
substitution, no bypass parameter, no cache,
GTD/telegram_bot.py/authorization.py untouched.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import unittest
from unittest.mock import patch

from business_core import telegram_handlers as th


def _git_show_head(path: str) -> str:
    result = subprocess.run(["git", "show", f"HEAD:{path}"], capture_output=True, text=True, cwd=".")
    if result.returncode != 0:
        raise AssertionError(f"git show HEAD:{path} failed: {result.stderr}")
    return result.stdout


def _top_level_function_sources(src: str) -> dict:
    """Maps top-level def/async-def name -> its exact source text
    (line-sliced from the module source using each node's own
    lineno/end_lineno). Used to isolate exactly which functions in a
    flat, class-free module differ between two versions."""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = "".join(lines[node.lineno - 1:node.end_lineno])
    return out


def _assert_only_functions_changed(test_case, path: str, allowed_changed_function_names: set) -> None:
    """
    Phase 17E-2A4-H1-R1: proves that of every top-level function
    defined in `path`, only those named in
    `allowed_changed_function_names` may differ between the last
    commit (HEAD) and the current working tree. No function may be
    added or removed. This is stricter than an allowlist on the file
    itself — an edit anywhere else in the file, in any other
    function, fails this check even though the file as a whole is
    "in the allowed list" of files that may change this phase.
    """
    head_src = _git_show_head(path)
    with open(path, encoding="utf-8") as f:
        current_src = f.read()

    head_functions = _top_level_function_sources(head_src)
    current_functions = _top_level_function_sources(current_src)

    test_case.assertEqual(
        set(head_functions.keys()), set(current_functions.keys()),
        f"{path}: a top-level function was added or removed — not permitted by this phase's scope",
    )

    for name in head_functions:
        if name in allowed_changed_function_names:
            continue
        test_case.assertEqual(
            head_functions[name], current_functions[name],
            f"{path}: unapproved function '{name}' changed — only {sorted(allowed_changed_function_names)} may change this phase",
        )


def _assert_only_functions_changed_or_added(
    test_case, path: str, allowed_changed_function_names: set, allowed_added_function_names: set,
) -> None:
    """
    Phase 17E-2A4: like _assert_only_functions_changed, but also
    permits a fixed, named set of brand-new top-level functions to
    exist in the working tree that were absent at HEAD (used when a
    phase both hardens an existing function AND adds new dedicated-
    command functions in the same file). No function may be removed.
    Any function present in both versions and not in
    allowed_changed_function_names must be byte-identical.
    """
    head_src = _git_show_head(path)
    with open(path, encoding="utf-8") as f:
        current_src = f.read()

    head_functions = _top_level_function_sources(head_src)
    current_functions = _top_level_function_sources(current_src)

    removed = set(head_functions.keys()) - set(current_functions.keys())
    test_case.assertEqual(removed, set(), f"{path}: a top-level function was removed — not permitted by this phase's scope")

    added = set(current_functions.keys()) - set(head_functions.keys())
    unexpected_added = added - allowed_added_function_names
    test_case.assertEqual(
        unexpected_added, set(),
        f"{path}: unapproved new top-level function(s) {sorted(unexpected_added)} — only {sorted(allowed_added_function_names)} may be added this phase",
    )

    for name in head_functions:
        if name in allowed_changed_function_names:
            continue
        test_case.assertEqual(
            head_functions[name], current_functions[name],
            f"{path}: unapproved function '{name}' changed — only {sorted(allowed_changed_function_names)} may change this phase",
        )

_ENFORCED_HANDLERS = {
    "doc": "doc_cmd",
    "obligation": "obligation_cmd",
    "payment": "payment_cmd",
    "offer": "offer_cmd",
    "lead": "lead_cmd",
    "interaction": "interaction_cmd",
}

_EXPECTED_MAP = {
    "doc":         {"resource": "DOCUMENT", "action": "READ", "target_shape": "BUSINESS_AND_OBJECT"},
    "obligation":  {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
    "payment":     {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
    "offer":       {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
    "lead":        {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
    "interaction": {"resource": "CLIENT",   "action": "READ", "target_shape": "BUSINESS"},
}

_EXPECTED_MUTATION_ENTRY = {
    "updateinteractionnotes": {
        "resource": "CLIENT", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "updateleadnotes": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "updateobligationnotes": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "updateoffernotes": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "updatedocnotes": {
        "resource": "DOCUMENT", "action": "UPDATE", "target_shape": "BUSINESS_AND_OBJECT",
        "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "failpayment": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "requires_fresh_reread": True,
        "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "confirmpayment": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "requires_fresh_reread": True,
        "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "reversepayment": {
        "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "requires_fresh_reread": True,
        "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
    "unassigntask": {
        "resource": "TASK", "action": "ASSIGN", "target_shape": "BUSINESS",
        "operation_kind": "MUTATION", "requires_fresh_reread": True,
        "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
    },
}

_NON_ENFORCED_SAMPLE_HANDLERS = [
    "objects_cmd", "services_cmd", "service_detail_cmd", "roadmaps_cmd" if hasattr(th, "roadmaps_cmd") else "show_roadmaps",
    "show_clients", "finddocs_cmd", "bc_status", "bc_access", "version_cmd",
    "newbiz_confirm", "init_bc", "stage_cmd",
    "newobject_cmd", "startroadmap_cmd", "updatestage_cmd",
    "archivedoc_cmd", "archiveoffer_cmd", "archivelead_cmd", "archiveinteraction_cmd",
    "assignrole_cmd",
    # Phase 17E-2 candidate mutation commands explicitly deferred —
    # must NOT have gained transport/authorization in this phase.
    # confirmpayment_cmd/reversepayment_cmd were authorized in Phase
    # 17E-2A6-AUTH-B2 and are intentionally excluded from this list.
    "updatedoc_cmd", "updateobligation_cmd", "updateoffer_cmd", "updatelead_cmd",
    "sendoffer_cmd", "acceptoffer_cmd", "convertlead_cmd",
]


class TestEnforcementMap(unittest.TestCase):
    def test_map_keys_exactly_fourteen_commands(self):
        expected_keys = set(_EXPECTED_MAP.keys()) | set(_EXPECTED_MUTATION_ENTRY.keys())
        self.assertEqual(set(th.COMMAND_ENFORCEMENT_MAP.keys()), expected_keys)

    def test_six_read_command_values_exact(self):
        for key, val in _EXPECTED_MAP.items():
            with self.subTest(command=key):
                self.assertEqual(th.COMMAND_ENFORCEMENT_MAP[key], val)

    def test_mutation_entries_exact(self):
        for key, val in _EXPECTED_MUTATION_ENTRY.items():
            with self.subTest(command=key):
                self.assertEqual(th.COMMAND_ENFORCEMENT_MAP[key], val)

    def test_no_sixteenth_command_in_map(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_updatelead_not_in_map(self):
        self.assertNotIn("updatelead", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateobligation_not_in_map(self):
        self.assertNotIn("updateobligation", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateoffer_not_in_map(self):
        self.assertNotIn("updateoffer", th.COMMAND_ENFORCEMENT_MAP)

    def test_updatedoc_not_in_map(self):
        self.assertNotIn("updatedoc", th.COMMAND_ENFORCEMENT_MAP)


class TestHandlersUseTransportPreflightAndAdapter(unittest.TestCase):
    def test_each_handler_calls_transport_preflight(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                src = inspect.getsource(getattr(th, func_name))
                self.assertIn("_validate_bc_transport_or_reply(update)", src)

    def test_each_handler_calls_authorize_or_reply_with_true_resource_action(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                src = inspect.getsource(getattr(th, func_name))
                expected = _EXPECTED_MAP[cmd]
                self.assertIn("_authorize_or_reply(", src)
                self.assertIn(f'resource="{expected["resource"]}"', src)
                self.assertIn(f'action="{expected["action"]}"', src)

    def test_each_handler_uses_resolve_target_in_thread(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                src = inspect.getsource(getattr(th, func_name))
                self.assertIn("_resolve_target_in_thread(", src)

    def test_no_handler_calls_authorization_py_directly(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                src = inspect.getsource(getattr(th, func_name))
                self.assertNotIn("authorize_business_core_access(", src)
                self.assertNotIn("from business_core.authorization import", src)

    def test_no_handler_reads_username_phone_display_name(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                tree = ast.parse(inspect.getsource(getattr(th, func_name)))
                accessed = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                for forbidden in ("username", "first_name", "last_name", "phone"):
                    self.assertNotIn(forbidden, accessed)

    def test_no_handler_duplicates_chat_or_user_extraction_logic(self):
        for cmd, func_name in _ENFORCED_HANDLERS.items():
            with self.subTest(command=cmd):
                src = inspect.getsource(getattr(th, func_name))
                self.assertNotIn("effective_chat", src)
                self.assertNotIn("effective_user", src)

    def test_no_bypass_parameter_exists(self):
        full_source = inspect.getsource(th)
        for forbidden in ("transport_already_validated", "skip_transport_check", "bypass_transport"):
            self.assertNotIn(forbidden, full_source)

        # No function anywhere in the module accepts a parameter whose
        # name suggests a transport-check bypass (docstring prose that
        # merely *describes* the absence of a bypass, e.g. "no bypass
        # flag exists", is legitimate and must not trip this check).
        tree = ast.parse(full_source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arg_names = [a.arg.lower() for a in node.args.args + node.args.kwonlyargs]
                for name in arg_names:
                    self.assertNotIn("bypass", name, f"{node.name} has a suspicious bypass-shaped parameter: {name}")
                    self.assertNotIn("skip_transport", name)
                    self.assertNotIn("already_validated", name)

    def test_authorize_or_reply_calls_full_adapter_not_preflight_only(self):
        src = inspect.getsource(th._authorize_or_reply)
        self.assertIn("authorize_telegram_business_core_request(", src)


class TestNoOtherCommandChanged(unittest.TestCase):
    def test_non_enforced_handlers_do_not_call_enforcement_helpers(self):
        for func_name in _NON_ENFORCED_SAMPLE_HANDLERS:
            if not hasattr(th, func_name):
                continue
            with self.subTest(handler=func_name):
                src = inspect.getsource(getattr(th, func_name))
                self.assertNotIn("_validate_bc_transport_or_reply(", src)
                self.assertNotIn("_authorize_or_reply(", src)
                self.assertNotIn("_resolve_target_in_thread(", src)

    def test_no_targetless_command_uses_business_read_as_substitute(self):
        for func_name in _NON_ENFORCED_SAMPLE_HANDLERS:
            if not hasattr(th, func_name):
                continue
            with self.subTest(handler=func_name):
                src = inspect.getsource(getattr(th, func_name))
                self.assertNotIn('resource="BUSINESS"', src)

    def test_registration_count_unchanged_except_none_added_for_enforcement(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        # exactly one registration line per enforced command, unchanged shape
        for cmd in _ENFORCED_HANDLERS:
            self.assertEqual(content.count(f'CommandHandler("{cmd}",'), 1)


class TestNoCacheNoBypassNoUnrelatedFileChange(unittest.TestCase):
    def test_no_cache_in_new_helpers(self):
        for func in (th._validate_bc_transport_or_reply, th._resolve_target_in_thread, th._authorize_or_reply):
            src = inspect.getsource(func)
            for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
                self.assertNotIn(forbidden, src)

    def test_telegram_bot_py_unchanged(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "telegram_bot.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    # Authorization-domain source invariants are enforced in test_authorization_domain.py.

    def test_identity_manager_unchanged(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/identity_manager.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_sheets_py_unchanged(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/sheets.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_gtd_files_unchanged(self):
        import subprocess
        gtd_files = ["inbox_processor.py", "project_planner.py", "calendar_sync.py"]
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"] + gtd_files,
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A4-H1-R1: narrow, function-level replacement for the
# obsolete whole-file "business_builder.py must have no diff"
# assertion. That blanket guard was correct for every prior
# COMMAND ENFORCEMENT phase (none of which touched business_builder.py
# at all) but is structurally incompatible with a hardening phase
# that explicitly, narrowly modifies exactly one wrapper function.
# The replacement proves the modification is confined to that one
# function — an allowlist on the *file* alone would not catch an
# unrelated edit anywhere else in the same file.
# ─────────────────────────────────────────────────────────────

class TestPhase17E2A4H1OfferHardeningScope(unittest.TestCase):
    def test_business_builder_change_confined_to_offer_wrapper(self):
        # Phase 17E-2A5-H1 additionally approves update_document_admin_fields
        # (malformed-manager-result hardening) in this same file.
        # Phase 17E-2A6-H0 additionally approved confirm_payment_transaction
        # and _synchronize_payment_obligation_after_transaction_change
        # (strict ledger-read fail-closed contract).
        # Phase 17E-2A6-H1 additionally approves reverse_payment_transaction
        # and fail_payment_transaction (malformed-result defensive
        # normalization only). _synchronize_payment_obligation_after_
        # transaction_change is NOT touched this phase (unchanged since
        # H0) — confirmed separately by
        # test_payment_business_builder_lifecycle_functions_unchanged.
        # unassign_task is the only approved business_builder function
        # change; all other module constructs are protected by dedicated
        # architecture guards.
        _assert_only_functions_changed(
            self, "business_core/business_builder.py",
            {
                "update_commercial_offer_admin_fields", "update_document_admin_fields",
                "confirm_payment_transaction", "reverse_payment_transaction", "fail_payment_transaction",
                "unassign_task",
            },
        )

    def test_offer_manager_change_confined_to_two_exception_sites(self):
        _assert_only_functions_changed(
            self, "business_core/offer_manager.py",
            {"_find_offer_row", "update_commercial_offer_admin_fields"},
        )

    def test_telegram_handlers_change_confined_to_offer_mapper(self):
        # Phase 17E-2A5-H1 additionally approves _document_admin_message
        # (legacy mapper safety correction) in this same file.
        # Phase 17E-2A5 additionally approves adding
        # _document_notes_message and updatedocnotes_cmd.
        # Phase 17E-2A6-H0 additionally approved
        # _payment_transaction_confirmation_message (new
        # PAYMENT_LEDGER_READ_FAILED branch).
        # Phase 17E-2A6-H1 additionally approves
        # _payment_transaction_reversal_message,
        # _payment_transaction_failure_message (mapper secrecy
        # hardening), and confirmpayment_cmd/reversepayment_cmd/
        # failpayment_cmd (outer-exception logging secrecy only).
        # _task_assignment_message was the only approved
        # telegram_handlers.py function change for the Task assignment
        # mapper hardening. unassigntask_cmd is now additionally
        # approved for its own authorization wiring; every other Task
        # handler command function and COMMAND_ENFORCEMENT_MAP's
        # top-level construct identity are protected separately by
        # test_task_architecture_guards.py.
        _assert_only_functions_changed_or_added(
            self, "business_core/telegram_handlers.py",
            allowed_changed_function_names={
                "register_business_handlers", "_document_admin_message",
                "_payment_transaction_confirmation_message",
                "_payment_transaction_reversal_message", "_payment_transaction_failure_message",
                "confirmpayment_cmd", "reversepayment_cmd", "failpayment_cmd", "updateinteractionnotes_cmd",
                "_task_assignment_message", "unassigntask_cmd",
            },
            allowed_added_function_names={
                "_offer_notes_message", "updateoffernotes_cmd",
                "_document_notes_message", "updatedocnotes_cmd",
            },
        )

    def test_payment_manager_change_confined_to_strict_ledger_read_contract(self):
        # Phase 17E-2A6-H0: _list_transactions_raw hardened (fixed
        # literal log); new _load_transactions_raw_strict,
        # list_payment_transactions_strict, _filter_transactions
        # added.
        # Phase 17E-2A6-H1 additionally approves _find_transaction_row,
        # update_payment_transaction_status, and
        # update_payment_obligation_balance (exception secrecy only).
        # No other payment_manager.py function may change.
        _assert_only_functions_changed_or_added(
            self, "business_core/payment_manager.py",
            allowed_changed_function_names={
                "_list_transactions_raw", "list_payment_transactions",
                "_find_transaction_row", "update_payment_transaction_status", "update_payment_obligation_balance",
            },
            allowed_added_function_names={
                "_load_transactions_raw_strict", "list_payment_transactions_strict", "_filter_transactions",
            },
        )

    def test_payment_lifecycle_functions_unchanged(self):
        # Explicit byte-identity confirmation for every Payment
        # function this phase must NOT touch.
        head_src = _git_show_head("business_core/payment_manager.py")
        head_functions = _top_level_function_sources(head_src)
        with open("business_core/payment_manager.py", encoding="utf-8") as f:
            current_functions = _top_level_function_sources(f.read())
        for name in (
            "_find_obligation_row",
            "update_payment_transaction_admin_fields", "update_payment_obligation_admin_fields",
            "update_payment_obligation_status", "create_payment_transaction", "create_payment_obligation",
            "create_commercial_milestone_template",
        ):
            self.assertEqual(head_functions[name], current_functions[name], f"{name} must be unchanged in Phase 17E-2A6-H1")

    def test_payment_business_builder_lifecycle_functions_unchanged(self):
        head_src = _git_show_head("business_core/business_builder.py")
        head_functions = _top_level_function_sources(head_src)
        with open("business_core/business_builder.py", encoding="utf-8") as f:
            current_functions = _top_level_function_sources(f.read())
        for name in ("_payment_result", "_compute_payment_balance", "_synchronize_payment_obligation_after_transaction_change"):
            self.assertEqual(head_functions[name], current_functions[name], f"{name} must be unchanged in Phase 17E-2A6-H1")

    def test_payment_mappers_and_handlers_unchanged(self):
        head_src = _git_show_head("business_core/telegram_handlers.py")
        head_functions = _top_level_function_sources(head_src)
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            current_functions = _top_level_function_sources(f.read())
        for name in ("payments_cmd", "obligation_cmd"):
            self.assertEqual(head_functions[name], current_functions[name], f"{name} must be unchanged in Phase 17E-2A6-H1")

    def test_payment_ledger_read_failed_code_added_no_extra_map_entry_beyond_failpayment(self):
        # Phase 17E-2A6-H1 itself added no map entry. Phase
        # 17E-2A6-AUTH-B1 added failpayment; Phase 17E-2A6-AUTH-B2
        # added confirmpayment and reversepayment. unassigntask was
        # added later, in the Task assignment mapper's own
        # authorization phase — no other entry beyond these four.
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)
        self.assertIn("failpayment", th.COMMAND_ENFORCEMENT_MAP)
        self.assertIn("confirmpayment", th.COMMAND_ENFORCEMENT_MAP)
        self.assertIn("reversepayment", th.COMMAND_ENFORCEMENT_MAP)

    def test_confirmpayment_reversepayment_now_authorized(self):
        # Phase 17E-2A6-AUTH-B2: confirmpayment_cmd/reversepayment_cmd
        # gain transport preflight and authorization, matching the
        # failpayment_cmd pattern established in Phase 17E-2A6-AUTH-B1.
        for name in ("confirmpayment_cmd", "reversepayment_cmd"):
            src = inspect.getsource(getattr(th, name))
            self.assertIn("_authorize_or_reply(", src)
            self.assertIn("_validate_bc_transport_or_reply(", src)
            self.assertIn('resource="FINANCE"', src)
            self.assertIn('action="UPDATE"', src)

    def test_failpayment_cmd_now_authorized(self):
        # Phase 17E-2A6-AUTH-B1: failpayment_cmd gains transport
        # preflight and authorization; confirmpayment/reversepayment
        # do not, and are not touched by this phase.
        src = inspect.getsource(th.failpayment_cmd)
        self.assertIn("_authorize_or_reply(", src)
        self.assertIn("_validate_bc_transport_or_reply(", src)
        self.assertIn('resource="FINANCE"', src)
        self.assertIn('action="UPDATE"', src)

    def test_interaction_manager_unchanged(self):
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/interaction_manager.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_lead_manager_unchanged(self):
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/lead_manager.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_document_manager_change_confined_to_two_exception_sites(self):
        # Phase 17E-2A5-H1: _find_document_row and
        # update_document_admin_fields exception-logging hardening only.
        _assert_only_functions_changed(
            self, "business_core/document_manager.py",
            {"_find_document_row", "update_document_admin_fields"},
        )

    def test_updateoffernotes_command_exists_and_registered(self):
        self.assertTrue(hasattr(th, "updateoffernotes_cmd"))
        self.assertIn("updateoffernotes", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateoffer_cmd_unchanged(self):
        # Phase 17E-2A5-H1 additionally approves _document_admin_message
        # (legacy mapper safety correction) in this same file.
        # Phase 17E-2A5 additionally approves adding
        # _document_notes_message and updatedocnotes_cmd.
        # Phase 17E-2A6-H0 additionally approved
        # _payment_transaction_confirmation_message (new
        # PAYMENT_LEDGER_READ_FAILED branch).
        # Phase 17E-2A6-H1 additionally approves
        # _payment_transaction_reversal_message,
        # _payment_transaction_failure_message (mapper secrecy
        # hardening), and confirmpayment_cmd/reversepayment_cmd/
        # failpayment_cmd (outer-exception logging secrecy only).
        # _task_assignment_message was the only approved
        # telegram_handlers.py function change for the Task assignment
        # mapper hardening. unassigntask_cmd is now additionally
        # approved for its own authorization wiring; every other Task
        # handler command function and COMMAND_ENFORCEMENT_MAP's
        # top-level construct identity are protected separately by
        # test_task_architecture_guards.py.
        _assert_only_functions_changed_or_added(
            self, "business_core/telegram_handlers.py",
            allowed_changed_function_names={
                "register_business_handlers", "_document_admin_message",
                "_payment_transaction_confirmation_message",
                "_payment_transaction_reversal_message", "_payment_transaction_failure_message",
                "confirmpayment_cmd", "reversepayment_cmd", "failpayment_cmd", "updateinteractionnotes_cmd",
                "_task_assignment_message", "unassigntask_cmd",
            },
            allowed_added_function_names={
                "_offer_notes_message", "updateoffernotes_cmd",
                "_document_notes_message", "updatedocnotes_cmd",
            },
        )
        # Redundant with the file-level check above but explicit:
        # updateoffer_cmd itself must be byte-identical to HEAD.
        head_src = _git_show_head("business_core/telegram_handlers.py")
        head_functions = _top_level_function_sources(head_src)
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            current_functions = _top_level_function_sources(f.read())
        self.assertEqual(head_functions["updateoffer_cmd"], current_functions["updateoffer_cmd"])

    def test_updatedoc_cmd_and_doc_cmd_unchanged(self):
        # Phase 17E-2A5: /updatedocnotes must not alter legacy
        # /updatedoc or /doc in any way.
        head_src = _git_show_head("business_core/telegram_handlers.py")
        head_functions = _top_level_function_sources(head_src)
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            current_functions = _top_level_function_sources(f.read())
        self.assertEqual(head_functions["updatedoc_cmd"], current_functions["updatedoc_cmd"])
        self.assertEqual(head_functions["doc_cmd"], current_functions["doc_cmd"])

    def test_updatedocnotes_command_exists_and_registered(self):
        self.assertTrue(hasattr(th, "updatedocnotes_cmd"))
        self.assertIn("updatedocnotes", th.COMMAND_ENFORCEMENT_MAP)

    def test_enforcement_map_now_fifteen_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_exactly_nine_dedicated_mutation_handlers_use_mutate_helper(self):
        dedicated = [
            "updateinteractionnotes_cmd", "updateleadnotes_cmd",
            "updateobligationnotes_cmd", "updateoffernotes_cmd", "updatedocnotes_cmd",
            "failpayment_cmd", "confirmpayment_cmd", "reversepayment_cmd",
            "unassigntask_cmd",
        ]
        for name in dedicated:
            self.assertTrue(hasattr(th, name))
            fn_src = inspect.getsource(getattr(th, name))
            self.assertIn("_mutate_target_in_thread(", fn_src)
        # No other _cmd function may reference the mutation helper.
        other_cmd_names = [
            n for n in dir(th)
            if n.endswith("_cmd") and n not in dedicated and callable(getattr(th, n))
        ]
        for name in other_cmd_names:
            with self.subTest(handler=name):
                other_src = inspect.getsource(getattr(th, name))
                self.assertNotIn("_mutate_target_in_thread(", other_src)


class TestOfferWrapperContractScope(unittest.TestCase):
    """Proves the approved update_commercial_offer_admin_fields
    correction preserves its external contract and stays a thin,
    side-effect-free-beyond-the-manager wrapper."""

    def test_signature_unchanged(self):
        from business_core import business_builder as bb
        sig = inspect.signature(bb.update_commercial_offer_admin_fields)
        self.assertEqual(list(sig.parameters.keys()), ["offer_id", "updates"])

    def test_calls_manager_mutator_exactly_once_in_source(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        self.assertEqual(src.count("om_update_admin("), 1)

    def test_no_direct_sheets_access(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        for forbidden in ("get_business_sheet(", "update_cell(", "find_row_by_id("):
            self.assertNotIn(forbidden, src)

    def test_no_authorization_call(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        self.assertNotIn("authorize_business_core_access(", src)
        self.assertNotIn("authorize_telegram_business_core_request(", src)

    def test_no_cache(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)

    def test_no_retry_loop(self):
        # "retry" itself legitimately appears in the preserved
        # retry_safe=True flag — only actual loop constructs are
        # forbidden here (covered separately by test_retry_safe_preserved).
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("while ", src)

    def test_no_other_registry_mutation(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        for forbidden in (
            "payment_manager.update_", "payment_manager.create_",
            "lead_manager.update_", "lead_manager.create_",
            "interaction_manager.update_", "interaction_manager.create_",
            "document_manager.update_", "document_manager.create_",
        ):
            self.assertNotIn(forbidden, src)

    def test_no_logging_of_result_or_error(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        self.assertNotIn("log.", src)

    def test_retry_safe_preserved(self):
        from business_core import business_builder as bb
        src = inspect.getsource(bb.update_commercial_offer_admin_fields)
        self.assertIn("retry_safe=True", src)

    def test_returns_same_dict_keys_as_before(self):
        # _offer_result is a shared result-builder used by many Offer
        # orchestration functions and always includes the full field
        # set (unused fields default to safe empty values) — this
        # proves the wrapper's own required output keys are present,
        # not that the shape is exactly these seven keys.
        from business_core import business_builder as bb
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value={"Business ID": "BIZ-001"}), \
             patch("business_core.offer_manager.update_commercial_offer_admin_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_commercial_offer_admin_fields("OFR-001", {"Notes": "x"})
        for required_key in ("ok", "code", "error", "commercial_offer_id", "business_id", "changed", "retry_safe"):
            self.assertIn(required_key, result)


if __name__ == "__main__":
    unittest.main()
