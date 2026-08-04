"""
Phase 17D: Telegram Authorization Adapter tests.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

All domain calls (authorize_business_core_access /
get_business_core_access_summary) are mocked via string-based patch
targets on business_core.telegram_authorization.<func> — patching the
exact module-object attribute business_core/telegram_authorization.py's
`from business_core.authorization import ...` binds at import time.
"""

from __future__ import annotations

import asyncio
import importlib
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from business_core import telegram_authorization as ta


def _ta():
    """Always resolves business_core.telegram_authorization fresh via
    sys.modules — never a module reference cached at test-collection
    time. Required because patch("business_core.telegram_authorization.X")
    also re-resolves via sys.modules at patch-application time; if
    another test file purges business_core.* from sys.modules (an
    established, intentional pattern elsewhere in this repo) between
    collection and execution, a cached `ta` reference and a string-based
    patch() target can silently diverge onto two different module
    objects — the exact PRS-003/Phase-17B-IR1 failure mode. Calling
    through this helper keeps every call site consistent with whatever
    patch() just patched."""
    return importlib.import_module("business_core.telegram_authorization")


def _update(chat_type="private", user_id=111, has_chat=True, has_user=True):
    chat = SimpleNamespace(type=chat_type) if has_chat else None
    user = SimpleNamespace(id=user_id) if has_user else None
    upd = SimpleNamespace()
    if has_chat or has_chat is None:
        upd.effective_chat = chat
    if has_user or has_user is None:
        upd.effective_user = user
    return upd


def _update_no_user_attr():
    upd = SimpleNamespace()
    upd.effective_chat = SimpleNamespace(type="private")
    return upd


class AsyncTestCase(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────
# Shared helper tests
# ─────────────────────────────────────────────────────────────

class TestResolveChatContext(unittest.TestCase):
    def test_none_update(self):
        r = ta._resolve_chat_context(None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")

    def test_missing_effective_chat_attribute(self):
        r = ta._resolve_chat_context(SimpleNamespace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")

    def test_effective_chat_none(self):
        upd = SimpleNamespace(effective_chat=None)
        r = ta._resolve_chat_context(upd)
        self.assertTrue(r["ok"])
        self.assertFalse(r["is_private_chat"])
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_missing_chat_type(self):
        upd = SimpleNamespace(effective_chat=SimpleNamespace(type=""))
        r = ta._resolve_chat_context(upd)
        self.assertTrue(r["ok"])
        self.assertFalse(r["is_private_chat"])
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_private_chat(self):
        r = ta._resolve_chat_context(_update(chat_type="private"))
        self.assertTrue(r["ok"])
        self.assertTrue(r["is_private_chat"])
        self.assertIsNone(r["code"])

    def test_group(self):
        r = ta._resolve_chat_context(_update(chat_type="group"))
        self.assertFalse(r["is_private_chat"])
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_supergroup(self):
        r = ta._resolve_chat_context(_update(chat_type="supergroup"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_channel(self):
        r = ta._resolve_chat_context(_update(chat_type="channel"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_never_raises_on_garbage(self):
        r = ta._resolve_chat_context(object())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")


class TestResolveTelegramUserId(unittest.TestCase):
    def test_missing_effective_user_attribute(self):
        r = ta._resolve_telegram_user_id(SimpleNamespace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")

    def test_effective_user_none(self):
        upd = SimpleNamespace(effective_user=None)
        r = ta._resolve_telegram_user_id(upd)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")

    def test_missing_user_id(self):
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=None))
        r = ta._resolve_telegram_user_id(upd)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")

    def test_valid_numeric_id(self):
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=570004109))
        r = ta._resolve_telegram_user_id(upd)
        self.assertTrue(r["ok"])
        self.assertEqual(r["telegram_user_id"], 570004109)

    def test_username_never_read(self):
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=111, username="spoofed", first_name="Fake"))
        r = ta._resolve_telegram_user_id(upd)
        self.assertEqual(r["telegram_user_id"], 111)
        # structural guard: function body never attribute-accesses
        # .username/.first_name/.last_name/.phone (docstring prose
        # mentioning these words in passing is fine)
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(ta._resolve_telegram_user_id))
        accessed_attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        for forbidden in ("username", "first_name", "last_name", "phone"):
            self.assertNotIn(forbidden, accessed_attrs)

    def test_never_raises_on_garbage(self):
        r = ta._resolve_telegram_user_id(object())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")


# ─────────────────────────────────────────────────────────────
# Authorization adapter
# ─────────────────────────────────────────────────────────────

class TestAuthorizeTelegramRequest(AsyncTestCase):
    def _run(self, update, **kwargs):
        kwargs.setdefault("resource", "BUSINESS")
        kwargs.setdefault("action", "READ")
        return self.run_async(_ta().authorize_telegram_business_core_request(update, **kwargs))

    def test_private_chat_allow(self):
        domain_result = {
            "ok": True, "allowed": True, "code": "ACCESS_ALLOWED", "retry_safe": True,
            "telegram_actor": "telegram:570004109",
        }
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result):
            r = self._run(_update(user_id=570004109))
        self.assertTrue(r["ok"])
        self.assertTrue(r["allowed"])
        self.assertEqual(r["code"], "TELEGRAM_ACCESS_ALLOWED")
        self.assertEqual(r["telegram_actor"], "telegram:570004109")
        self.assertIsNone(r["user_message_key"])

    def test_expected_denial(self):
        domain_result = {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED", "retry_safe": True}
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result):
            r = self._run(_update())
        self.assertTrue(r["ok"])
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "AUTHORIZATION_DENIED")
        self.assertTrue(r["retry_safe"])
        self.assertEqual(r["user_message_key"], "no_matching_scope")
        self.assertEqual(r["authorization_result"], domain_result)

    def test_infrastructure_failure(self):
        domain_result = {"ok": False, "allowed": False, "code": "AUTHORIZATION_READ_FAILED", "retry_safe": False}
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result):
            r = self._run(_update())
        self.assertFalse(r["ok"])
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "AUTHORIZATION_UNAVAILABLE")
        self.assertFalse(r["retry_safe"])
        self.assertEqual(r["user_message_key"], "temporarily_unavailable")

    def test_group_denied_zero_domain_calls(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(_update(chat_type="group"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_supergroup_denied(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(_update(chat_type="supergroup"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_channel_denied(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(_update(chat_type="channel"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_callback_query_private(self):
        cb_update = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=570004109),
        )
        domain_result = {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED", "retry_safe": True, "telegram_actor": "telegram:570004109"}
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result):
            r = self._run(cb_update)
        self.assertTrue(r["allowed"])

    def test_callback_query_group(self):
        cb_update = SimpleNamespace(
            effective_chat=SimpleNamespace(type="group"),
            effective_user=SimpleNamespace(id=570004109),
        )
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(cb_update)
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_update_none(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        mock_domain.assert_not_called()

    def test_missing_effective_chat_attribute(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(SimpleNamespace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        mock_domain.assert_not_called()

    def test_effective_chat_none(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(SimpleNamespace(effective_chat=None))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_missing_chat_type(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(SimpleNamespace(effective_chat=SimpleNamespace(type=None)))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_missing_effective_user_attribute(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(_update_no_user_attr())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        mock_domain.assert_not_called()

    def test_effective_user_none(self):
        upd = _update(has_user=False)
        upd.effective_user = None
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(upd)
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")
        mock_domain.assert_not_called()

    def test_missing_user_id_zero_domain_calls(self):
        upd = SimpleNamespace(effective_chat=SimpleNamespace(type="private"), effective_user=SimpleNamespace(id=None))
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            r = self._run(upd)
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")
        mock_domain.assert_not_called()

    def test_non_numeric_user_id_passed_through_to_domain(self):
        upd = SimpleNamespace(effective_chat=SimpleNamespace(type="private"), effective_user=SimpleNamespace(id="not-a-number"))
        domain_result = {"ok": True, "allowed": False, "code": "INVALID_TELEGRAM_USER_ID", "retry_safe": True}
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result) as mock_domain:
            r = self._run(upd)
        mock_domain.assert_called_once()
        self.assertEqual(mock_domain.call_args[0][0], "not-a-number")
        self.assertEqual(r["code"], "AUTHORIZATION_DENIED")

    def test_actor_derived_from_domain_result_never_caller_supplied(self):
        domain_result = {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED", "retry_safe": True, "telegram_actor": "telegram:570004109"}
        with patch("business_core.telegram_authorization.authorize_business_core_access", return_value=domain_result):
            r = self._run(_update(user_id=570004109))
        self.assertEqual(r["telegram_actor"], "telegram:570004109")
        import inspect
        src = inspect.getsource(_ta().authorize_telegram_business_core_request)
        self.assertNotIn("telegram_actor=", src)

    def test_no_direct_sheets_access(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(ta))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        self.assertNotIn("business_core.sheets", imported_modules)
        self.assertNotIn("gspread", imported_modules)
        self.assertNotIn("business_core.identity_manager", imported_modules)

    def test_no_cache(self):
        import inspect
        src = inspect.getsource(ta)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)


# ─────────────────────────────────────────────────────────────
# Summary adapter
# ─────────────────────────────────────────────────────────────

class TestGetTelegramAccessSummary(AsyncTestCase):
    def _run(self, update):
        return self.run_async(_ta().get_telegram_business_core_access_summary(update))

    def test_private_summary_available(self):
        summary = {"ok": True, "telegram_actor": "telegram:570004109", "identity_status": "resolved", "can_use_business_core": True}
        with patch("business_core.telegram_authorization.get_business_core_access_summary", return_value=summary):
            r = self._run(_update(user_id=570004109))
        self.assertTrue(r["ok"])
        self.assertTrue(r["available"])
        self.assertEqual(r["code"], "TELEGRAM_SUMMARY_AVAILABLE")
        self.assertEqual(r["access_summary_result"], summary)

    def test_summary_infrastructure_failure(self):
        summary = {"ok": False, "error": "boom", "retry_safe": False}
        with patch("business_core.telegram_authorization.get_business_core_access_summary", return_value=summary):
            r = self._run(_update())
        self.assertFalse(r["ok"])
        self.assertFalse(r["available"])
        self.assertEqual(r["code"], "ACCESS_SUMMARY_UNAVAILABLE")
        self.assertFalse(r["retry_safe"])

    def test_group_refusal_zero_domain_calls(self):
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_domain:
            r = self._run(_update(chat_type="group"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_missing_user_zero_domain_calls(self):
        upd = _update(has_user=False)
        upd.effective_user = None
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_domain:
            r = self._run(upd)
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")
        mock_domain.assert_not_called()

    def test_available_true_even_when_cannot_use_business_core(self):
        summary = {"ok": True, "telegram_actor": None, "identity_status": "resolved",
                   "employee_status": "pending", "can_use_business_core": False}
        with patch("business_core.telegram_authorization.get_business_core_access_summary", return_value=summary):
            r = self._run(_update())
        self.assertTrue(r["available"])
        self.assertFalse(r["access_summary_result"]["can_use_business_core"])

    def test_callback_query_private(self):
        cb_update = SimpleNamespace(effective_chat=SimpleNamespace(type="private"), effective_user=SimpleNamespace(id=570004109))
        summary = {"ok": True, "can_use_business_core": True}
        with patch("business_core.telegram_authorization.get_business_core_access_summary", return_value=summary):
            r = self._run(cb_update)
        self.assertTrue(r["available"])

    def test_callback_query_group(self):
        cb_update = SimpleNamespace(effective_chat=SimpleNamespace(type="group"), effective_user=SimpleNamespace(id=570004109))
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_domain:
            r = self._run(cb_update)
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        mock_domain.assert_not_called()

    def test_update_none(self):
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_domain:
            r = self._run(None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        mock_domain.assert_not_called()

    def test_missing_effective_chat_attribute(self):
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_domain:
            r = self._run(SimpleNamespace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        mock_domain.assert_not_called()


# ─────────────────────────────────────────────────────────────
# asyncio.to_thread forwarding + event-loop safety
# ─────────────────────────────────────────────────────────────

class TestThreadOffload(AsyncTestCase):
    def test_to_thread_awaited_for_authorization(self):
        domain_result = {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED", "retry_safe": True, "telegram_actor": "telegram:1"}
        recorded = {}

        async def fake_to_thread(func, *args, **kwargs):
            recorded["func"] = func
            recorded["args"] = args
            recorded["kwargs"] = kwargs
            return domain_result

        with patch("business_core.telegram_authorization.asyncio.to_thread", side_effect=fake_to_thread):
            r = self.run_async(_ta().authorize_telegram_business_core_request(
                _update(user_id=570004109), resource="OBJECT", action="READ", business_id="B", object_id="O",
            ))
        self.assertIs(recorded["func"], _ta().authorize_business_core_access)
        self.assertEqual(recorded["args"], (570004109,))
        self.assertEqual(recorded["kwargs"], {"resource": "OBJECT", "action": "READ", "business_id": "B", "object_id": "O"})
        self.assertTrue(r["allowed"])

    def test_to_thread_awaited_for_summary(self):
        summary = {"ok": True, "can_use_business_core": True}
        recorded = {}

        async def fake_to_thread(func, *args, **kwargs):
            recorded["func"] = func
            recorded["args"] = args
            return summary

        with patch("business_core.telegram_authorization.asyncio.to_thread", side_effect=fake_to_thread):
            r = self.run_async(_ta().get_telegram_business_core_access_summary(_update(user_id=570004109)))
        self.assertIs(recorded["func"], _ta().get_business_core_access_summary)
        self.assertEqual(recorded["args"], (570004109,))
        self.assertTrue(r["available"])

    def test_worker_thread_exception_fails_closed_authorization(self):
        def boom(*_a, **_k):
            raise RuntimeError("sheets down")
        with patch("business_core.telegram_authorization.authorize_business_core_access", side_effect=boom):
            r = self.run_async(_ta().authorize_telegram_business_core_request(_update(), resource="BUSINESS", action="READ"))
        self.assertFalse(r["ok"])
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "AUTHORIZATION_UNAVAILABLE")
        self.assertFalse(r["retry_safe"])

    def test_worker_thread_exception_fails_closed_summary(self):
        def boom(*_a, **_k):
            raise RuntimeError("sheets down")
        with patch("business_core.telegram_authorization.get_business_core_access_summary", side_effect=boom):
            r = self.run_async(_ta().get_telegram_business_core_access_summary(_update()))
        self.assertFalse(r["ok"])
        self.assertFalse(r["available"])
        self.assertEqual(r["code"], "ACCESS_SUMMARY_UNAVAILABLE")
        self.assertFalse(r["retry_safe"])

    def test_event_loop_remains_responsive_during_blocking_domain_call(self):
        def blocking_domain(*_a, **_k):
            time.sleep(0.2)
            return {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED", "retry_safe": True, "telegram_actor": "telegram:1"}

        async def run():
            counter = {"n": 0}

            async def ticker():
                while True:
                    counter["n"] += 1
                    await asyncio.sleep(0.01)

            tick_task = asyncio.create_task(ticker())
            with patch("business_core.telegram_authorization.authorize_business_core_access", side_effect=blocking_domain):
                await _ta().authorize_telegram_business_core_request(_update(), resource="BUSINESS", action="READ")
            tick_task.cancel()
            return counter["n"]

        ticks = self.run_async(run())
        self.assertGreater(ticks, 3, "event loop appears blocked during the offloaded domain call")


# ─────────────────────────────────────────────────────────────
# Phase 17E-1: validate_telegram_business_core_transport (public,
# synchronous, read-free preflight)
# ─────────────────────────────────────────────────────────────

class TestValidateTelegramBusinessCoreTransport(unittest.TestCase):
    def test_valid_private_update(self):
        r = _ta().validate_telegram_business_core_transport(_update(user_id=570004109))
        self.assertTrue(r["ok"])
        self.assertTrue(r["valid"])
        self.assertIsNone(r["code"])
        self.assertEqual(r["telegram_user_id"], "570004109")
        self.assertEqual(r["chat_type"], "private")
        self.assertTrue(r["is_private_chat"])

    def test_group(self):
        r = _ta().validate_telegram_business_core_transport(_update(chat_type="group"))
        self.assertTrue(r["ok"])
        self.assertFalse(r["valid"])
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")
        self.assertTrue(r["retry_safe"])

    def test_supergroup(self):
        r = _ta().validate_telegram_business_core_transport(_update(chat_type="supergroup"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_channel(self):
        r = _ta().validate_telegram_business_core_transport(_update(chat_type="channel"))
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_update_none(self):
        r = _ta().validate_telegram_business_core_transport(None)
        self.assertFalse(r["ok"])
        self.assertFalse(r["valid"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")
        self.assertFalse(r["retry_safe"])

    def test_missing_effective_chat_attribute(self):
        r = _ta().validate_telegram_business_core_transport(SimpleNamespace())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")

    def test_effective_chat_none(self):
        r = _ta().validate_telegram_business_core_transport(SimpleNamespace(effective_chat=None))
        self.assertTrue(r["ok"])
        self.assertFalse(r["valid"])
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_missing_chat_type(self):
        upd = SimpleNamespace(effective_chat=SimpleNamespace(type=None))
        r = _ta().validate_telegram_business_core_transport(upd)
        self.assertEqual(r["code"], "PRIVATE_CHAT_REQUIRED")

    def test_missing_effective_user_attribute(self):
        r = _ta().validate_telegram_business_core_transport(_update_no_user_attr())
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_TELEGRAM_UPDATE")

    def test_effective_user_none(self):
        upd = _update(has_user=False)
        upd.effective_user = None
        r = _ta().validate_telegram_business_core_transport(upd)
        self.assertTrue(r["ok"])
        self.assertFalse(r["valid"])
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")

    def test_missing_user_id(self):
        upd = SimpleNamespace(effective_chat=SimpleNamespace(type="private"), effective_user=SimpleNamespace(id=None))
        r = _ta().validate_telegram_business_core_transport(upd)
        self.assertEqual(r["code"], "TELEGRAM_USER_NOT_FOUND")

    def test_username_first_name_last_name_ignored(self):
        upd = SimpleNamespace(
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=570004109, username="spoofed", first_name="Fake", last_name="Name"),
        )
        r = _ta().validate_telegram_business_core_transport(upd)
        self.assertTrue(r["valid"])
        self.assertEqual(r["telegram_user_id"], "570004109")

    def test_zero_authorization_domain_calls(self):
        with patch("business_core.telegram_authorization.authorize_business_core_access") as mock_domain:
            _ta().validate_telegram_business_core_transport(_update())
        mock_domain.assert_not_called()

    def test_zero_access_summary_calls(self):
        with patch("business_core.telegram_authorization.get_business_core_access_summary") as mock_summary:
            _ta().validate_telegram_business_core_transport(_update())
        mock_summary.assert_not_called()

    def test_zero_asyncio_to_thread_calls(self):
        with patch("business_core.telegram_authorization.asyncio.to_thread") as mock_to_thread:
            _ta().validate_telegram_business_core_transport(_update())
        mock_to_thread.assert_not_called()

    def test_no_sheets_or_identity_manager_reference(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(_ta().validate_telegram_business_core_transport))
        imported = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("read_business_sheet", imported)
        self.assertNotIn("find_row_by_id", imported)

    def test_no_write_reference(self):
        import inspect
        src = inspect.getsource(_ta().validate_telegram_business_core_transport)
        for forbidden in ("append_business_row", "update_business_row", "create_pending_employee"):
            self.assertNotIn(forbidden, src)

    def test_no_cache(self):
        import inspect
        src = inspect.getsource(_ta().validate_telegram_business_core_transport)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)

    def test_reuses_private_helpers_not_duplicated(self):
        import inspect
        src = inspect.getsource(_ta().validate_telegram_business_core_transport)
        self.assertIn("_resolve_chat_context(", src)
        self.assertIn("_resolve_telegram_user_id(", src)


if __name__ == "__main__":
    unittest.main()
