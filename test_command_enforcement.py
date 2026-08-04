"""
Phase 17E-1: Command Enforcement architecture guards.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

Pure inventory/architecture tests — no domain behavior is exercised
here (that belongs to test_business_core_read_enforcement.py). These
tests prove the STRUCTURE of the enforcement rollout: exactly six
commands are gated, no other command changed, no resource
substitution, no bypass parameter, no cache, GTD/telegram_bot.py/
authorization.py untouched.
"""

from __future__ import annotations

import ast
import inspect
import unittest

from business_core import telegram_handlers as th

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

_NON_ENFORCED_SAMPLE_HANDLERS = [
    "objects_cmd", "services_cmd", "service_detail_cmd", "roadmaps_cmd" if hasattr(th, "roadmaps_cmd") else "show_roadmaps",
    "show_clients", "finddocs_cmd", "bc_status", "bc_access", "version_cmd",
    "newbiz_confirm", "init_bc", "stage_cmd",
    "newobject_cmd", "startroadmap_cmd", "updatestage_cmd",
    "archivedoc_cmd", "archiveoffer_cmd", "archivelead_cmd", "archiveinteraction_cmd",
    "assignrole_cmd",
]


class TestEnforcementMap(unittest.TestCase):
    def test_map_keys_exactly_six_commands(self):
        self.assertEqual(set(th.COMMAND_ENFORCEMENT_MAP.keys()), set(_EXPECTED_MAP.keys()))

    def test_map_values_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP, _EXPECTED_MAP)

    def test_no_seventh_command_in_map(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 6)


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

    def test_authorization_py_unchanged(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/authorization.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

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

    def test_business_builder_unchanged(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/business_builder.py"],
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


if __name__ == "__main__":
    unittest.main()
