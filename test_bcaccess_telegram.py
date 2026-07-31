"""
Phase 17D: /bcaccess Telegram command tests.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

bc_access() does a call-time `from business_core.telegram_authorization
import get_telegram_business_core_access_summary` (mirroring every
other Business Core handler's lazy-import convention), so all mocks
target "business_core.telegram_authorization.get_telegram_business_core_access_summary"
— the module attribute get_telegram_business_core_access_summary is
re-resolved from, not a stale local reference — safe even under the
sys.modules-purge adversarial-ordering pattern this repo tests for.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from business_core import telegram_handlers as th


def _make_update():
    update = AsyncMock()
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    return update


def _run(coro):
    return asyncio.run(coro)


def _adapter_result(**overrides):
    base = {
        "ok": True, "available": True, "code": "TELEGRAM_SUMMARY_AVAILABLE", "error": None, "retry_safe": True,
        "telegram_user_id": "570004109", "telegram_actor": "telegram:570004109",
        "chat_type": "private", "is_private_chat": True,
        "access_summary_result": None, "user_message_key": None,
    }
    base.update(overrides)
    return base


def _summary(**overrides):
    base = {
        "ok": True, "error": None, "retry_safe": True,
        "telegram_user_id": "570004109", "telegram_actor": "telegram:570004109",
        "identity_status": "resolved", "employee_id": "EMP-002", "employee_status": "active",
        "can_use_business_core": True,
        "roles": ["OWNER"],
        "scopes_by_role_assignment": [
            {"access_role_assignment_id": "ARA-002", "role": "OWNER", "scope_type": "ALL_BUSINESSES", "target_count": 1},
        ],
        "malformed_warnings": [], "evaluated_at": "2026-07-31 00:00:00 UTC",
    }
    base.update(overrides)
    return base


class TestBcAccessResponses(unittest.TestCase):
    def _invoke(self, adapter_result):
        update = _make_update()
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=adapter_result,
        ):
            _run(th.bc_access(update, context=None))
        return update

    def test_owner_style_private_response(self):
        adapter_result = _adapter_result(access_summary_result=_summary())
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Telegram ID: 570004109", text)
        self.assertIn("Статус: Активен", text)
        self.assertIn("Роль: OWNER", text)
        self.assertIn("Все бизнесы", text)
        self.assertIn("Business Core: Доступен", text)

    def test_unrecognized_user(self):
        summary = _summary(identity_status="not_found", employee_id=None, employee_status=None,
                            can_use_business_core=False, roles=[], scopes_by_role_assignment=[])
        adapter_result = _adapter_result(access_summary_result=summary)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не подключён к Business Core", text)

    def test_pending_employee(self):
        summary = _summary(employee_status="pending", can_use_business_core=False,
                            roles=[], scopes_by_role_assignment=[])
        adapter_result = _adapter_result(access_summary_result=summary)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("ещё не активирован", text)

    def test_disabled_employee(self):
        summary = _summary(employee_status="disabled", can_use_business_core=False,
                            roles=[], scopes_by_role_assignment=[])
        adapter_result = _adapter_result(access_summary_result=summary)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("отключён", text)

    def test_active_no_role_or_scope(self):
        summary = _summary(roles=[], scopes_by_role_assignment=[], can_use_business_core=False)
        adapter_result = _adapter_result(access_summary_result=summary)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Нет активного доступа", text)

    def test_summary_unavailable(self):
        adapter_result = _adapter_result(ok=False, available=False, code="ACCESS_SUMMARY_UNAVAILABLE",
                                          access_summary_result=None)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Временная ошибка", text)

    def test_group_refusal(self):
        adapter_result = _adapter_result(ok=True, available=False, code="PRIVATE_CHAT_REQUIRED",
                                          is_private_chat=False, chat_type="group", access_summary_result=None)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("только в личном чате", text)

    def test_multiple_roles_each_own_scope_line(self):
        summary = _summary(
            roles=["OWNER", "COORDINATOR"],
            scopes_by_role_assignment=[
                {"access_role_assignment_id": "ARA-A", "role": "COORDINATOR", "scope_type": "ASSIGNED_OBJECTS_ONLY", "target_count": 3},
                {"access_role_assignment_id": "ARA-B", "role": "OWNER", "scope_type": "ALL_BUSINESSES", "target_count": 1},
            ],
        )
        adapter_result = _adapter_result(access_summary_result=summary)
        update = self._invoke(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Роль: COORDINATOR", text)
        self.assertIn("Назначенные объекты: 3", text)
        self.assertIn("Роль: OWNER", text)
        self.assertIn("Все бизнесы", text)


class TestBcAccessNoLeakage(unittest.TestCase):
    def test_extra_argument_ignored(self):
        update = _make_update()
        context = type("Ctx", (), {"args": ["12345"]})()
        adapter_result = _adapter_result(access_summary_result=_summary())
        mock_adapter = AsyncMock(return_value=adapter_result)
        with patch("business_core.telegram_authorization.get_telegram_business_core_access_summary", new=mock_adapter):
            _run(th.bc_access(update, context=context))
        # adapter is called with the update only — no target ID argument possible
        mock_adapter.assert_called_once_with(update)

    def test_no_context_args_read_in_source(self):
        import inspect
        src = inspect.getsource(th.bc_access)
        self.assertNotIn("context.args", src)

    def test_no_raw_ids_in_response(self):
        summary = _summary()
        adapter_result = _adapter_result(access_summary_result=summary)
        update = _make_update()
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=adapter_result,
        ):
            _run(th.bc_access(update, context=None))
        text = update.message.reply_text.call_args[0][0]
        for forbidden in ("EMP-", "TGID-", "ARA-", "ASA-"):
            self.assertNotIn(forbidden, text)

    def test_response_under_4096_chars(self):
        adapter_result = _adapter_result(access_summary_result=_summary())
        update = self._invoke_via_module(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        self.assertLess(len(text), 4096)

    def _invoke_via_module(self, adapter_result):
        update = _make_update()
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=adapter_result,
        ):
            _run(th.bc_access(update, context=None))
        return update

    def test_stable_russian_text_snapshot(self):
        adapter_result = _adapter_result(access_summary_result=_summary())
        update = self._invoke_via_module(adapter_result)
        text = update.message.reply_text.call_args[0][0]
        expected = (
            "Telegram ID: 570004109\n"
            "Статус: Активен\n"
            "Роль: OWNER\n"
            "Доступ: Все бизнесы\n"
            "\n"
            "Business Core: Доступен"
        )
        self.assertEqual(text, expected)


class TestBcAccessArchitectureGuards(unittest.TestCase):
    def test_registered_exactly_once(self):
        with open("business_core/telegram_handlers.py") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("bcaccess"'), 1)

    def test_imports_only_telegram_summary_adapter(self):
        import inspect
        src = inspect.getsource(th.bc_access)
        self.assertIn("get_telegram_business_core_access_summary", src)
        self.assertNotIn("get_business_core_access_summary(", src.replace("get_telegram_business_core_access_summary", ""))

    def test_never_imports_authorization_module_directly(self):
        import inspect
        src = inspect.getsource(th.bc_access) + inspect.getsource(th._render_bcaccess_message)
        self.assertNotIn("from business_core.authorization import", src)
        self.assertNotIn("business_core.authorization.authorize", src)
        self.assertNotIn("business_core.authorization.get_business_core_access_summary", src)

    def test_never_imports_identity_manager(self):
        import inspect
        src = inspect.getsource(th.bc_access) + inspect.getsource(th._render_bcaccess_message)
        self.assertNotIn("identity_manager", src)

    def test_never_imports_sheets(self):
        import inspect
        src = inspect.getsource(th.bc_access) + inspect.getsource(th._render_bcaccess_message)
        self.assertNotIn("business_core.sheets", src)
        self.assertNotIn("get_business_sheet", src)
        self.assertNotIn("read_business_sheet", src)

    def test_never_calls_get_business_core_access_summary_directly(self):
        update = _make_update()
        adapter_result = _adapter_result(access_summary_result=_summary())
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=adapter_result,
        ) as mock_adapter, patch(
            "business_core.authorization.get_business_core_access_summary",
        ) as mock_domain:
            _run(th.bc_access(update, context=None))
        mock_adapter.assert_called_once()
        mock_domain.assert_not_called()

    def test_no_write_call(self):
        import inspect
        src = inspect.getsource(th.bc_access) + inspect.getsource(th._render_bcaccess_message)
        for forbidden in ("append_business_row", "update_business_row", "create_pending_employee",
                           "assign_access_role", "assign_access_scope", "link_telegram_identity"):
            self.assertNotIn(forbidden, src)

    def test_renders_only_callers_own_summary_no_target_param(self):
        import inspect
        sig = inspect.signature(th.bc_access)
        params = list(sig.parameters)
        self.assertEqual(params, ["update", "context"])

    def test_bcaccess_scope_type_labels_do_not_expose_raw_ids(self):
        self.assertNotIn("access_role_assignment_id", str(th._BC_ACCESS_SCOPE_TYPE_LABELS))


class TestBcAccessOtherUserIsolation(unittest.TestCase):
    def test_two_users_never_see_each_others_data(self):
        summary_a = _summary(telegram_user_id="111", roles=["VIEWER"],
                              scopes_by_role_assignment=[{"access_role_assignment_id": "ARA-X", "role": "VIEWER", "scope_type": "ALL_BUSINESSES", "target_count": 1}])
        summary_b = _summary(telegram_user_id="222", roles=["COORDINATOR"],
                              scopes_by_role_assignment=[{"access_role_assignment_id": "ARA-Y", "role": "COORDINATOR", "scope_type": "ASSIGNED_OBJECTS_ONLY", "target_count": 5}])

        update_a = _make_update()
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=_adapter_result(telegram_user_id="111", access_summary_result=summary_a),
        ):
            _run(th.bc_access(update_a, context=None))
        text_a = update_a.message.reply_text.call_args[0][0]

        update_b = _make_update()
        with patch(
            "business_core.telegram_authorization.get_telegram_business_core_access_summary",
            new_callable=AsyncMock, return_value=_adapter_result(telegram_user_id="222", access_summary_result=summary_b),
        ):
            _run(th.bc_access(update_b, context=None))
        text_b = update_b.message.reply_text.call_args[0][0]

        self.assertIn("111", text_a)
        self.assertNotIn("222", text_a)
        self.assertIn("COORDINATOR", text_b)
        self.assertNotIn("COORDINATOR", text_a)
        self.assertIn("VIEWER", text_a)
        self.assertNotIn("VIEWER", text_b)


if __name__ == "__main__":
    unittest.main()
