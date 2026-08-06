"""
Tests for Phase 36D — Task Domain: Telegram Commands.

Covers /newbctask, /bctasks, /bctask, /updatetask, /assigntask,
/reassigntask, /unassigntask in business_core/telegram_handlers.py.
Additive-only commands — GTD's own /tasks is never touched (verified
by a dedicated guard test here and in test_task_architecture_guards.py).
No live Sheets writes — business_builder/task_manager functions are
mocked throughout, per ENGINEERING_STANDARDS.md Testing Standards.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


def _fresh_th():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.telegram_handlers")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_update(text: str, args_list: list[str]):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.update_id = 12345
    update.effective_user = SimpleNamespace(id=999)
    update.effective_chat = SimpleNamespace(type="private")
    context = MagicMock()
    context.args = args_list
    return update, context


# ─────────────────────────────────────────────────────────────
# /newbctask
# ─────────────────────────────────────────────────────────────

class TestNewBcTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "newbctask_cmd"))

    def test_missing_business_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask title="X"', ['title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_missing_title_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/newbctask business_id=BIZ-001", ["business_id=BIZ-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_created(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newbctask business_id=BIZ-001 title="Prepare docs"',
            ["business_id=BIZ-001", 'title="Prepare docs"'],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
                                     "business_id": "BIZ-001", "final_status": "new", "error": None}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("TSK-001", reply)

    def test_reused(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newbctask business_id=BIZ-001 title="X" idempotency_key=K1',
            ["business_id=BIZ-001", 'title="X"', "idempotency_key=K1"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": True, "code": "TASK_REUSED", "task_id": "TSK-050",
                                     "business_id": "BIZ-001", "final_status": "ready", "error": None}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", reply)
        self.assertIn("ℹ️", reply)
        self.assertIn("TSK-050", reply)

    def test_business_not_found(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newbctask business_id=BIZ-999 title="X"',
            ["business_id=BIZ-999", 'title="X"'],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "BUSINESS_NOT_FOUND", "business_id": "BIZ-999", "error": "not found"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("BIZ-999", reply)

    def test_roadmap_completed(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newbctask business_id=BIZ-001 title="X" roadmap_id=RM-001',
            ["business_id=BIZ-001", 'title="X"', "roadmap_id=RM-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "ROADMAP_COMPLETED", "error": "done"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("завершён", reply.lower())

    def test_roadmap_cancelled(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "ROADMAP_CANCELLED", "error": "x"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("отменён", reply.lower())

    def test_stage_terminal(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "STAGE_TERMINAL", "error": "x"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_relation_mismatch(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "TASK_ENTITY_RELATION_MISMATCH", "error": "mismatch detail"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_multiple_idempotency_conflict(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "MULTIPLE_TASK_IDEMPOTENCY_MATCHES",
                                     "conflicting_task_ids": ("TSK-A", "TSK-B"), "error": "x"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("TSK-A", reply)
        self.assertIn("TSK-B", reply)

    def test_unknown_code_fallback(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task",
                       return_value={"ok": False, "code": "SOMETHING_NEW", "error": "detail"}):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("SOMETHING_NEW", reply)

    def test_idempotency_key_defaults_deterministically(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])
        captured = {}

        def fake_create(business_id, title, **kwargs):
            captured["idempotency_key"] = kwargs.get("idempotency_key")
            return {"ok": True, "code": "TASK_CREATED", "task_id": "TSK-001", "business_id": business_id, "final_status": "new", "error": None}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task", side_effect=fake_create):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        self.assertTrue(captured["idempotency_key"])

    def test_manager_exception_does_not_leak_traceback(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task", side_effect=RuntimeError("boom")):
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertNotIn("boom", reply)
        self.assertNotIn("Traceback", reply)


# ─────────────────────────────────────────────────────────────
# /bctasks
# ─────────────────────────────────────────────────────────────

_BCTASKS_UNSET = object()


class BcTasksCommandTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, list_side_effect=None, list_return=_BCTASKS_UNSET,
                      authz_result=None, business_id="BIZ-001", th=None):
        th = th or _fresh_th()
        call_log = []
        effective_return = [] if list_return is _BCTASKS_UNSET else list_return

        if list_side_effect is not None:
            def _list(**kwargs):
                call_log.append(("list_tasks", kwargs))
                if callable(list_side_effect):
                    return list_side_effect(**kwargs)
                raise list_side_effect
            mock_list = MagicMock(side_effect=_list)
        else:
            def _list(**kwargs):
                call_log.append(("list_tasks", kwargs))
                return effective_return
            mock_list = MagicMock(side_effect=_list)

        async def _authz(update, **kwargs):
            call_log.append(("authorize", kwargs.get("resource"), kwargs.get("action"), kwargs.get("business_id")))
            return authz_result if authz_result is not None else _bctask_allow_result()
        mock_authz = AsyncMock(side_effect=_authz)

        ctx_args = args if args is not None else [f"business_id={business_id}"]
        ctx = MagicMock()
        ctx.args = ctx_args

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.list_tasks", new=mock_list), \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=mock_authz):
                await th.bctasks_cmd(update, ctx)

        _run(run())
        return mock_list, mock_authz, call_log

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestBcTasksCommand(BcTasksCommandTestBase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "bctasks_cmd"))

    def test_transport_validation(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        upd.effective_chat = None
        th = _fresh_th()
        mock_list, mock_authz, _ = self._run_handler(upd, th=th)
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_missing_business_id_rejected(self):
        upd, _ = _make_update("/bctasks", [])
        mock_list, mock_authz, _ = self._run_handler(upd, args=[])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()
        self.assertIn("business_id", self._sent_text(upd))

    def test_blank_business_id_rejected(self):
        upd, _ = _make_update("/bctasks business_id=", ["business_id="])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["business_id="])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_positional_token_rejected(self):
        upd, _ = _make_update("/bctasks BIZ-001", ["BIZ-001"])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["BIZ-001"])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_unknown_key_rejected(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001 foo=bar", ["business_id=BIZ-001", "foo=bar"])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", "foo=bar"])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_task_id_key_rejected(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001 task_id=TSK-001", ["business_id=BIZ-001", "task_id=TSK-001"])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", "task_id=TSK-001"])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_limit_offset_page_rejected(self):
        for extra in ("limit=10", "offset=0", "page=1", "resource=TASK", "action=READ", "scope=ALL"):
            with self.subTest(extra=extra):
                upd, _ = _make_update(f"/bctasks business_id=BIZ-001 {extra}", ["business_id=BIZ-001", extra])
                mock_list, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", extra])
                mock_list.assert_not_called()
                mock_authz.assert_not_called()

    def test_role_id_without_business_id_rejected(self):
        upd, _ = _make_update("/bctasks role_id=ROLE-001", ["role_id=ROLE-001"])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["role_id=ROLE-001"])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_person_id_without_business_id_rejected(self):
        upd, _ = _make_update("/bctasks person_id=PRS-001", ["person_id=PRS-001"])
        mock_list, mock_authz, _ = self._run_handler(upd, args=["person_id=PRS-001"])
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_malformed_business_id_from_parser_rejected(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        th = _fresh_th()
        with patch.object(th, "_parse_kv_args", return_value={"business_id": object()}):
            mock_list, mock_authz, _ = self._run_handler(upd, th=th)
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_malformed_optional_filter_rejected(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        th = _fresh_th()
        with patch.object(th, "_parse_kv_args", return_value={"business_id": "BIZ-001", "status": object()}):
            mock_list, mock_authz, _ = self._run_handler(upd, th=th)
        mock_list.assert_not_called()
        mock_authz.assert_not_called()

    def test_authorization_uses_task_read(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        _, _, call_log = self._run_handler(upd)
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[1], "TASK")
        self.assertEqual(authz_call[2], "READ")

    def test_authorization_uses_requested_business_id(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        _, _, call_log = self._run_handler(upd, business_id="BIZ-001")
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[3], "BIZ-001")

    def test_authorization_called_exactly_once(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        _, mock_authz, _ = self._run_handler(upd)
        mock_authz.assert_called_once()

    def test_authorization_before_scan(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        _, _, call_log = self._run_handler(upd)
        order = [c[0] for c in call_log]
        self.assertEqual(order.index("authorize"), 0)
        self.assertLess(order.index("authorize"), order.index("list_tasks"))

    def test_deny_blocks_scan(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, _ = self._run_handler(upd, authz_result=_bctask_deny_result())
        mock_list.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись недоступна или не найдена.")

    def test_authorization_read_failure_blocks_scan(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, _ = self._run_handler(upd, authz_result=_bctask_infra_failure_result())
        mock_list.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_list_tasks_called_exactly_once(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, _ = self._run_handler(upd)
        mock_list.assert_called_once()

    def test_list_tasks_thread_offloaded(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        th = _fresh_th()
        with patch.object(th.asyncio, "to_thread", wraps=th.asyncio.to_thread) as mock_to_thread:
            self._run_handler(upd, th=th)
        mock_to_thread.assert_called_once()

    def test_list_tasks_gets_same_business_id(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, _ = self._run_handler(upd, business_id="BIZ-001")
        self.assertEqual(mock_list.call_args.kwargs["business_id"], "BIZ-001")

    def test_list_tasks_gets_all_normalized_filters(self):
        upd, _ = _make_update(
            "/bctasks business_id=BIZ-001 status=ready roadmap_id=RM-001 stage_id=STAGE-001 role_id=ROLE-001 person_id=PRS-001",
            ["business_id=BIZ-001", "status=ready", "roadmap_id=RM-001", "stage_id=STAGE-001", "role_id=ROLE-001", "person_id=PRS-001"],
        )
        mock_list, _, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", "status=ready", "roadmap_id=RM-001", "stage_id=STAGE-001", "role_id=ROLE-001", "person_id=PRS-001"],
        )
        self.assertEqual(
            {k: v for k, v in mock_list.call_args.kwargs.items() if k != "raise_on_error"},
            dict(business_id="BIZ-001", status="ready", roadmap_id="RM-001",
                 stage_id="STAGE-001", role_id="ROLE-001", person_id="PRS-001"),
        )

    def test_raise_on_error_true_passed_exactly(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, _ = self._run_handler(upd)
        self.assertIs(mock_list.call_args.kwargs["raise_on_error"], True)

    def test_no_default_mode_fallback(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_list, _, call_log = self._run_handler(upd)
        list_calls = [c for c in call_log if c[0] == "list_tasks"]
        self.assertEqual(len(list_calls), 1)
        self.assertIs(list_calls[0][1]["raise_on_error"], True)

    def test_storage_exception_not_treated_as_empty(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        self._run_handler(upd, list_side_effect=RuntimeError("boom"))
        reply = self._sent_text(upd)
        self.assertNotEqual(reply, "📋 Tasks — BIZ-001\n\nПусто.")
        self.assertEqual(reply, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_fixed_literal_storage_error_logging(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        th = _fresh_th()
        with patch.object(th, "log") as mock_log:
            self._run_handler(upd, list_side_effect=RuntimeError("SECRET-DETAIL-MARKER"), th=th)
            mock_log.error.assert_called_once_with("bctasks_cmd storage read failure")
            for call in mock_log.mock_calls:
                self.assertNotIn("SECRET-DETAIL-MARKER", str(call))

    def test_non_list_result_handled_safely(self):
        for value in (None, {}, "bad", object(), 0, 1, (1, 2)):
            with self.subTest(result=repr(type(value))):
                upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
                self._run_handler(upd, list_return=value)
                self.assertEqual(upd.message.reply_text.call_count, 1)
                self.assertEqual(self._sent_text(upd), "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_malformed_rows_skipped(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        rows = [None, "bad", object(), {"task_id": "TSK-001", "business_id": "BIZ-001", "title": "X", "status": "ready", "due_date": ""}]
        self._run_handler(upd, list_return=rows)
        reply = self._sent_text(upd)
        self.assertIn("TSK-001", reply)

    def test_foreign_business_rows_excluded(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        rows = [{"task_id": "TSK-999", "business_id": "BIZ-999", "title": "Other", "status": "ready", "due_date": ""}]
        self._run_handler(upd, list_return=rows)
        reply = self._sent_text(upd)
        self.assertNotIn("TSK-999", reply)
        self.assertIn("Пусто", reply)

    def test_missing_business_id_rows_excluded(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        rows = [{"task_id": "TSK-999", "title": "Other", "status": "ready", "due_date": ""}]
        self._run_handler(upd, list_return=rows)
        self.assertIn("Пусто", self._sent_text(upd))

    def test_poisoned_business_id_rows_excluded(self):
        class Poisoned:
            def __str__(self):
                return "STR-SECRET-MARKER"

            def __repr__(self):
                return "REPR-SECRET-MARKER"

        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        rows = [{"task_id": "TSK-999", "business_id": Poisoned(), "title": "Other", "status": "ready", "due_date": ""}]
        self._run_handler(upd, list_return=rows)
        reply = self._sent_text(upd)
        self.assertNotIn("STR-SECRET-MARKER", reply)
        self.assertNotIn("REPR-SECRET-MARKER", reply)
        self.assertIn("Пусто", reply)

    def test_valid_empty_authorized_business(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        self._run_handler(upd, list_return=[])
        reply = self._sent_text(upd)
        self.assertIn("Пусто", reply)
        self.assertNotIn("newbctask", reply)

    def test_formatter_called_exactly_once_with_filtered_rows(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        th = _fresh_th()
        rows = [
            {"task_id": "TSK-001", "business_id": "BIZ-001", "title": "X", "status": "ready", "due_date": ""},
            {"task_id": "TSK-999", "business_id": "BIZ-999", "title": "Foreign", "status": "ready", "due_date": ""},
        ]
        with patch("business_core.telegram_handlers._task_list_lines", wraps=th._task_list_lines) as mock_formatter:
            self._run_handler(upd, list_return=rows, th=th)
        mock_formatter.assert_called_once()
        passed_rows = mock_formatter.call_args.args[0]
        self.assertEqual(len(passed_rows), 1)
        self.assertEqual(passed_rows[0]["task_id"], "TSK-001")

    def test_result_cap_behavior(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        rows = [
            {"task_id": f"TSK-{i:03d}", "business_id": "BIZ-001", "title": "X", "status": "ready", "due_date": ""}
            for i in range(25)
        ]
        self._run_handler(upd, list_return=rows)
        reply = self._sent_text(upd)
        self.assertIn("… и ещё 5", reply)

    def test_adversarial_long_fields_stay_one_telegram_message(self):
        # Closes the exact blind spot found in review: bctasks_cmd
        # calling _reply exactly once does not by itself prove exactly
        # one Telegram message is sent, since _reply/_safe_send may
        # chunk a long enough joined string into several reply_text
        # calls. This test exercises the real _reply/_safe_send path
        # (only authorization and list_tasks are mocked) against 25
        # same-Business rows with every displayed field at 10,000
        # characters, forcing both the 20-row cap and the more-results
        # line, and proves the per-field output caps keep the total
        # rendered text — and therefore the real reply_text call count
        # — bounded to a single Telegram message.
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        long = "L" * 10000
        rows = [
            {
                "task_id": "T" * 10000, "business_id": "BIZ-001", "title": "X" * 10000,
                "status": long, "due_date": "D" * 10000,
            }
            for _ in range(25)
        ]
        self._run_handler(upd, list_return=rows)
        self.assertEqual(upd.message.reply_text.call_count, 1)
        sent_text = upd.message.reply_text.call_args[0][0]
        self.assertLessEqual(len(sent_text), 4000)
        # Every capped field must appear only in its clipped form —
        # the full 10,000-character value must never reach the reply.
        self.assertNotIn("T" * 41, sent_text)
        self.assertNotIn("X" * 61, sent_text)
        self.assertNotIn(long[:42], sent_text)
        self.assertNotIn("D" * 31, sent_text)
        self.assertIn("… и ещё 5", sent_text)

    def test_reply_exactly_once_allowed_path(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        self._run_handler(upd, list_return=[{"task_id": "TSK-001", "business_id": "BIZ-001", "title": "X", "status": "ready", "due_date": ""}])
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_reply_exactly_once_deny_path(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        self._run_handler(upd, authz_result=_bctask_deny_result())
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_reply_exactly_once_storage_error_path(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        self._run_handler(upd, list_side_effect=RuntimeError("boom"))
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_no_mutation_helper_called(self):
        upd, _ = _make_update("/bctasks business_id=BIZ-001", ["business_id=BIZ-001"])
        with patch("business_core.business_builder.unassign_task") as mock_unassign, \
             patch("business_core.task_manager.end_task_assignment") as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache") as mock_cache:
            self._run_handler(upd)
            mock_unassign.assert_not_called()
            mock_end.assert_not_called()
            mock_cache.assert_not_called()

    def test_no_gtd_read_path(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def bctasks_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        for forbidden in ("read_next_actions", "inbox_processor"):
            self.assertNotIn(forbidden, body)


# ─────────────────────────────────────────────────────────────
# /bctask
# ─────────────────────────────────────────────────────────────

TASK_DICT = {
    "task_id": "TSK-001", "business_id": "BIZ-001", "title": "Prepare docs",
    "description": "secret notes", "status": "ready", "priority": "high",
    "due_date": "2026-08-01", "source": "telegram", "idempotency_key": "K1",
    "client_id": "", "object_id": "", "service_id": "", "roadmap_id": "", "stage_id": "",
    "responsible_role_id": "ROLE-001", "assignee_person_id": "",
    "created_at": "2026-01-01", "updated_at": "2026-01-01",
    "started_at": "", "completed_at": "", "cancelled_at": "",
    "created_by": "999", "gtd_action_id": "",
}


def _bctask_allow_result():
    return {"ok": True, "allowed": True, "code": "TELEGRAM_ACCESS_ALLOWED",
            "authorization_result": {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED"}}


def _bctask_deny_result():
    return {"ok": True, "allowed": False, "code": "AUTHORIZATION_DENIED",
            "authorization_result": {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED"}}


def _bctask_infra_failure_result():
    return {"ok": False, "allowed": False, "code": "AUTHORIZATION_UNAVAILABLE",
            "authorization_result": None}


class BcTaskCommandTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, task_id="TSK-001", th=None):
        th = th or _fresh_th()
        call_log = []

        if finder_side_effect is not None:
            def _finder(tid):
                call_log.append(("finder", tid))
                if callable(finder_side_effect):
                    return finder_side_effect(tid)
                raise finder_side_effect
            mock_finder = MagicMock(side_effect=_finder)
        else:
            def _finder(tid):
                call_log.append(("finder", tid))
                return finder_return
            mock_finder = MagicMock(side_effect=_finder)

        async def _authz(update, **kwargs):
            call_log.append(("authorize", kwargs.get("resource"), kwargs.get("action"), kwargs.get("business_id")))
            return authz_result if authz_result is not None else _bctask_allow_result()
        mock_authz = AsyncMock(side_effect=_authz)

        ctx_args = args if args is not None else [f"task_id={task_id}"]
        ctx = MagicMock()
        ctx.args = ctx_args

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", new=mock_finder), \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=mock_authz), \
                 patch("business_core.task_manager.get_current_task_assignment") as mock_current_assignment, \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent") as mock_consistency:
                await th.bctask_cmd(update, ctx)
                call_log.append(("_no_assignment_helper_called", mock_current_assignment.called))
                call_log.append(("_no_consistency_helper_called", mock_consistency.called))

        _run(run())
        return mock_finder, mock_authz, call_log

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestBcTaskCommand(BcTaskCommandTestBase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "bctask_cmd"))

    def test_missing_task_id_shows_usage(self):
        upd, _ = _make_update("/bctask", [])
        finder, authz, _ = self._run_handler(upd, args=[])
        finder.assert_not_called()
        authz.assert_not_called()
        self.assertIn("❌", self._sent_text(upd))

    def test_not_found(self):
        upd, _ = _make_update("/bctask task_id=TSK-999", ["task_id=TSK-999"])
        finder, authz, _ = self._run_handler(upd, finder_return=None, task_id="TSK-999")
        finder.assert_called_once_with("TSK-999")
        authz.assert_not_called()
        self.assertIn("недоступна", self._sent_text(upd).lower())

    def test_found_unassigned(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        task = dict(TASK_DICT, responsible_role_id="", assignee_person_id="")
        self._run_handler(upd, finder_return=task)
        reply = self._sent_text(upd)
        self.assertIn("TSK-001", reply)
        self.assertIn("—", reply)  # unassigned placeholder somewhere

    def test_reply_contains_no_assignment_or_cache_output(self):
        # Active Assignment ID and cache-consistency state were removed
        # from /bctask output entirely — they were sourced from reads
        # that are not scoped to the authorized Business ID.
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, finder_return=dict(TASK_DICT))
        reply = self._sent_text(upd)
        for marker in ("Active Assignment ID", "Assignment cache", "РАССОГЛАСОВАН", "согласованность назначения"):
            self.assertNotIn(marker, reply)

    def test_no_assignment_or_cache_helper_invoked(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        _, _, call_log = self._run_handler(upd, finder_return=dict(TASK_DICT))
        self.assertIn(("_no_assignment_helper_called", False), call_log)
        self.assertIn(("_no_consistency_helper_called", False), call_log)

    def test_description_not_logged(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        with patch("business_core.telegram_handlers.log") as mock_log:
            self._run_handler(upd, finder_return=dict(TASK_DICT))
            for call in mock_log.method_calls:
                for arg in call.args:
                    self.assertNotIn("secret notes", str(arg))

    # ── Section 15 required tests ──────────────────────────────

    def test_named_task_id_accepted(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, _ = self._run_handler(upd, finder_return=dict(TASK_DICT))
        finder.assert_called_once_with("TSK-001")

    def test_positional_task_id_accepted(self):
        upd, _ = _make_update("/bctask TSK-001", ["TSK-001"])
        finder, authz, _ = self._run_handler(upd, args=["TSK-001"], finder_return=dict(TASK_DICT))
        finder.assert_called_once_with("TSK-001")

    def test_named_task_id_precedence(self):
        upd, _ = _make_update("/bctask TSK-XXX task_id=TSK-001", ["TSK-XXX", "task_id=TSK-001"])
        finder, authz, _ = self._run_handler(upd, args=["TSK-XXX", "task_id=TSK-001"], finder_return=dict(TASK_DICT))
        finder.assert_called_once_with("TSK-001")

    def test_blank_task_id_rejected(self):
        upd, _ = _make_update("/bctask", [])
        finder, authz, _ = self._run_handler(upd, args=[])
        finder.assert_not_called()
        authz.assert_not_called()

    def test_unknown_key_rejected(self):
        upd, _ = _make_update("/bctask task_id=TSK-001 foo=bar", ["task_id=TSK-001", "foo=bar"])
        finder, authz, _ = self._run_handler(upd, args=["task_id=TSK-001", "foo=bar"])
        finder.assert_not_called()
        authz.assert_not_called()

    def test_caller_business_id_rejected(self):
        upd, _ = _make_update("/bctask task_id=TSK-001 business_id=BIZ-999", ["task_id=TSK-001", "business_id=BIZ-999"])
        finder, authz, _ = self._run_handler(upd, args=["task_id=TSK-001", "business_id=BIZ-999"])
        finder.assert_not_called()

    def test_caller_object_role_person_fields_rejected(self):
        for extra in ("object_id=OBJ-999", "role_id=ROLE-999", "responsible_role_id=ROLE-999",
                      "person_id=PRS-999", "assignee_person_id=PRS-999", "assignment_id=TAS-999"):
            with self.subTest(extra=extra):
                upd, _ = _make_update(f"/bctask task_id=TSK-001 {extra}", ["task_id=TSK-001", extra])
                finder, authz, _ = self._run_handler(upd, args=["task_id=TSK-001", extra])
                finder.assert_not_called()

    def test_transport_failure_blocks_lookup(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        upd.effective_chat = None
        th = _fresh_th()
        finder, authz, _ = self._run_handler(upd, finder_return=dict(TASK_DICT), th=th)
        finder.assert_not_called()
        authz.assert_not_called()

    _MALFORMED_FIRST_SHAPES = [None, {}, [], "bad", object(), 0, 1]

    class _Poisoned:
        def __str__(self):
            return "STR-SECRET-MARKER"

        def __repr__(self):
            return "REPR-SECRET-MARKER"

    def test_malformed_lookup_shapes_fail_closed(self):
        markers = ("STR-SECRET-MARKER", "REPR-SECRET-MARKER")
        for value in self._MALFORMED_FIRST_SHAPES + [self._Poisoned()]:
            with self.subTest(first=repr(value)):
                upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
                with patch("business_core.telegram_handlers.log") as mock_log:
                    finder, authz, _ = self._run_handler(upd, finder_return=value)
                authz.assert_not_called()
                self.assertEqual(finder.call_count, 1)
                self.assertEqual(upd.message.reply_text.call_count, 1)
                reply = self._sent_text(upd)
                for marker in markers:
                    self.assertNotIn(marker, reply)
                for call in mock_log.mock_calls:
                    call_text = str(call)
                    for marker in markers:
                        self.assertNotIn(marker, call_text)

    def test_empty_dict_lookup_blocked_via_blank_business_id(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, _ = self._run_handler(upd, finder_return={})
        authz.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись недоступна или не найдена.")

    def test_blank_stored_business_id_blocked(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        task = dict(TASK_DICT, business_id="")
        finder, authz, _ = self._run_handler(upd, finder_return=task)
        authz.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись недоступна или не найдена.")

    class _PoisonedBusinessId:
        def __str__(self):
            return "STR-SECRET-MARKER"

        def __repr__(self):
            return "REPR-SECRET-MARKER"

    class _RaisingBusinessId:
        def __str__(self):
            raise RuntimeError("RAISE-SECRET-MARKER")

        def __repr__(self):
            raise RuntimeError("RAISE-SECRET-MARKER")

    _MALFORMED_BUSINESS_ID_SHAPES = [None, [], {}, object(), 0, 1]

    def test_malformed_business_id_shapes_fail_closed(self):
        markers = ("STR-SECRET-MARKER", "REPR-SECRET-MARKER", "RAISE-SECRET-MARKER")
        shapes = self._MALFORMED_BUSINESS_ID_SHAPES + [self._PoisonedBusinessId(), self._RaisingBusinessId()]
        for value in shapes:
            with self.subTest(business_id=repr(type(value))):
                upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
                task = dict(TASK_DICT, business_id=value)
                with patch("business_core.telegram_handlers.log") as mock_log:
                    finder, authz, _ = self._run_handler(upd, finder_return=task)
                authz.assert_not_called()
                self.assertEqual(upd.message.reply_text.call_count, 1)
                reply = self._sent_text(upd)
                self.assertEqual(reply, "Запись недоступна или не найдена.")
                for marker in markers:
                    self.assertNotIn(marker, reply)
                for call in mock_log.mock_calls:
                    call_text = str(call)
                    for marker in markers:
                        self.assertNotIn(marker, call_text)

    def test_authorization_uses_resource_task_action_read(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, call_log = self._run_handler(upd, finder_return=dict(TASK_DICT))
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[1], "TASK")
        self.assertEqual(authz_call[2], "READ")

    def test_authorization_uses_stored_business_id(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, call_log = self._run_handler(upd, finder_return=dict(TASK_DICT))
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[3], "BIZ-001")

    def test_authorization_called_exactly_once(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, _ = self._run_handler(upd, finder_return=dict(TASK_DICT))
        authz.assert_called_once()

    def test_authorization_deny_blocks_formatter(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, finder_return=dict(TASK_DICT), authz_result=_bctask_deny_result())
        reply = self._sent_text(upd)
        self.assertNotIn("Prepare docs", reply)
        self.assertEqual(reply, "Запись недоступна или не найдена.")

    def test_authorization_read_failure_blocks_formatter(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, finder_return=dict(TASK_DICT), authz_result=_bctask_infra_failure_result())
        reply = self._sent_text(upd)
        self.assertNotIn("Prepare docs", reply)
        self.assertEqual(reply, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_allowed_flow_reply_contains_formatted_detail_once(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, finder_return=dict(TASK_DICT))
        self.assertEqual(upd.message.reply_text.call_count, 1)
        self.assertIn("Prepare docs", self._sent_text(upd))

    def test_formatter_called_exactly_once_with_the_first_task_object(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        task = dict(TASK_DICT)
        th = _fresh_th()
        with patch("business_core.telegram_handlers._task_detail_lines", wraps=th._task_detail_lines) as mock_formatter:
            self._run_handler(upd, finder_return=task, th=th)
        mock_formatter.assert_called_once()
        self.assertIs(mock_formatter.call_args.args[0], task)

    def test_lookup_occurs_through_finder_exactly_once(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, _ = self._run_handler(upd, finder_return=dict(TASK_DICT))
        self.assertEqual(finder.call_count, 1)

    def test_no_reread_no_second_finder_call(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, call_log = self._run_handler(upd, finder_return=dict(TASK_DICT))
        finder_calls = [c for c in call_log if c[0] == "finder"]
        self.assertEqual(len(finder_calls), 1)

    def test_no_mutation_helper_called(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        with patch("business_core.business_builder.unassign_task") as mock_unassign, \
             patch("business_core.task_manager.end_task_assignment") as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache") as mock_cache:
            self._run_handler(upd, finder_return=dict(TASK_DICT))
            mock_unassign.assert_not_called()
            mock_end.assert_not_called()
            mock_cache.assert_not_called()

    def test_exception_during_formatting_uses_fixed_literal_log(self):
        upd, _ = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        th = _fresh_th()
        with patch.object(th, "log") as mock_log, \
             patch("business_core.telegram_handlers._task_detail_lines", side_effect=RuntimeError("boom internal detail")):
            self._run_handler(upd, finder_return=dict(TASK_DICT), th=th)
            mock_log.error.assert_called_once_with("bctask_cmd formatting/reply failure")
        reply = self._sent_text(upd)
        self.assertNotIn("boom internal detail", reply)
        self.assertIn("❌", reply)


# ─────────────────────────────────────────────────────────────
# /updatetask
# ─────────────────────────────────────────────────────────────

class TestUpdateTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "updatetask_cmd"))

    def test_admin_updated(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 priority=high", ["task_id=TSK-001", "priority=high"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.update_task_admin_fields",
                       return_value={"ok": True, "code": "TASK_ADMIN_FIELDS_UPDATED", "changed": True, "error": None}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_admin_unchanged(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 priority=high", ["task_id=TSK-001", "priority=high"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.update_task_admin_fields",
                       return_value={"ok": True, "code": "TASK_ADMIN_FIELDS_UNCHANGED", "changed": False, "error": None}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("ℹ️", reply)

    def test_invalid_field_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_immutable_field_blocked(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 priority=high", ["task_id=TSK-001", "priority=high"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.update_task_admin_fields",
                       return_value={"ok": False, "code": "TASK_IMMUTABLE_FIELD_CONFLICT", "changed": False, "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_relation_field_blocked_message(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 priority=high", ["task_id=TSK-001", "priority=high"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.update_task_admin_fields",
                       return_value={"ok": False, "code": "TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION", "changed": False, "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("связей", reply.lower())

    def test_status_updated(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=ready", ["task_id=TSK-001", "status=ready"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": True, "code": "TASK_STATUS_UPDATED", "previous_status": "new",
                                     "requested_status": "ready", "final_status": "ready", "error": None}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_status_unchanged(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=new", ["task_id=TSK-001", "status=new"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": True, "code": "TASK_STATUS_UNCHANGED", "previous_status": "new",
                                     "requested_status": "new", "final_status": "new", "error": None}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("ℹ️", reply)

    def test_invalid_status(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=bogus", ["task_id=TSK-001", "status=bogus"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": False, "code": "INVALID_TASK_STATUS", "previous_status": "new",
                                     "requested_status": "bogus", "final_status": "new", "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_invalid_transition(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=new", ["task_id=TSK-001", "status=new"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": False, "code": "INVALID_TASK_TRANSITION", "previous_status": "blocked",
                                     "requested_status": "new", "final_status": "blocked", "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_terminal_reopen_blocked(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=ready", ["task_id=TSK-001", "status=ready"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": False, "code": "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION",
                                     "previous_status": "done", "requested_status": "ready", "final_status": "done", "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("🔒", reply)
        self.assertIn("reopen", reply.lower())

    def test_roadmap_on_hold_blocks_in_progress(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatetask task_id=TSK-001 status=in_progress", ["task_id=TSK-001", "status=in_progress"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status",
                       return_value={"ok": False, "code": "ROADMAP_ON_HOLD", "previous_status": "ready",
                                     "requested_status": "in_progress", "final_status": "ready", "error": "x"}):
                await th.updatetask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⏸️", reply)

    def test_mixed_status_and_admin_rejected(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatetask task_id=TSK-001 status=ready priority=high",
            ["task_id=TSK-001", "status=ready", "priority=high"],
        )
        calls = {}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_task_status") as mock_transition, \
                 patch("business_core.business_builder.update_task_admin_fields") as mock_admin:
                await th.updatetask_cmd(upd, ctx)
                calls["transition_called"] = mock_transition.called
                calls["admin_called"] = mock_admin.called

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertFalse(calls["transition_called"])
        self.assertFalse(calls["admin_called"])


# ─────────────────────────────────────────────────────────────
# /assigntask, /reassigntask, /unassigntask
# ─────────────────────────────────────────────────────────────

class TestAssignTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "assigntask_cmd"))

    def test_missing_args_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_created(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001", "error": None}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("TAS-001", reply)

    def test_reused(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_ASSIGNMENT_REUSED", "assignment_id": "TAS-050", "error": None}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", reply)
        self.assertIn("ℹ️", reply)

    def test_role_only(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])
        captured = {}

        def fake_assign(task_id, responsible_role_id="", assignee_person_id="", **kwargs):
            captured["role"] = responsible_role_id
            captured["person"] = assignee_person_id
            return {"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001", "error": None}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task", side_effect=fake_assign):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        self.assertEqual(captured["role"], "ROLE-001")
        self.assertEqual(captured["person"], "")

    def test_person_only(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 person_id=PRS-001", ["task_id=TSK-001", "person_id=PRS-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001", "error": None}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_both_role_and_person(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assigntask task_id=TSK-001 role_id=ROLE-001 person_id=PRS-001",
            ["task_id=TSK-001", "role_id=ROLE-001", "person_id=PRS-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001", "error": None}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_person_missing(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 person_id=PRS-999", ["task_id=TSK-001", "person_id=PRS-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "PERSON_NOT_FOUND", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_person_archived(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 person_id=PRS-001", ["task_id=TSK-001", "person_id=PRS-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "PERSON_ARCHIVED", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("архивирован", reply.lower())

    def test_business_mismatch(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 person_id=PRS-001", ["task_id=TSK-001", "person_id=PRS-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "PERSON_TASK_BUSINESS_MISMATCH", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_role_missing(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-999", ["task_id=TSK-001", "role_id=ROLE-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "ROLE_NOT_FOUND", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_role_paused(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "ROLE_PAUSED", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("приостановлена", reply.lower())

    def test_role_archived(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "ROLE_ARCHIVED", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("архивирован", reply.lower())

    def test_planned_role_with_person_blocked(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assigntask task_id=TSK-001 role_id=ROLE-001 person_id=PRS-001",
            ["task_id=TSK-001", "role_id=ROLE-001", "person_id=PRS-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("planned", reply)

    def test_department_archived(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "DEPARTMENT_ARCHIVED", "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_multiple_active_conflict(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
                                     "conflicting_assignment_ids": ("TAS-A", "TAS-B"), "error": "x"}):
                await th.assigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("TAS-A", reply)
        self.assertIn("TAS-B", reply)


class TestReassignTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "reassigntask_cmd"))

    def test_reassigned(self):
        th = _fresh_th()
        upd, ctx = _make_update("/reassigntask task_id=TSK-001 role_id=ROLE-002", ["task_id=TSK-001", "role_id=ROLE-002"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_REASSIGNED", "assignment_id": "TAS-020",
                                     "previous_assignment_id": "TAS-010", "error": None}):
                await th.reassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("TAS-010", reply)
        self.assertIn("TAS-020", reply)

    def test_reused_no_op(self):
        th = _fresh_th()
        upd, ctx = _make_update("/reassigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": True, "code": "TASK_ASSIGNMENT_REUSED", "assignment_id": "TAS-010", "error": None}):
                await th.reassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", reply)
        self.assertIn("ℹ️", reply)

    def test_multiple_active_conflict(self):
        th = _fresh_th()
        upd, ctx = _make_update("/reassigntask task_id=TSK-001 role_id=ROLE-002", ["task_id=TSK-001", "role_id=ROLE-002"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.assign_task",
                       return_value={"ok": False, "code": "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
                                     "conflicting_assignment_ids": ("TAS-A", "TAS-B"), "error": "x"}):
                await th.reassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)


_UNASSIGNTASK_FINDER_PATH = "business_core.task_manager.find_task_by_id"
_UNASSIGNTASK_MUTATOR_PATH = "business_core.business_builder.unassign_task"
_UNASSIGNTASK_AUTHZ_PATH = "business_core.telegram_authorization.authorize_telegram_business_core_request"

_UNASSIGNTASK_ROW = {
    "task_id": "TSK-001", "business_id": "BIZ-001",
    "responsible_role_id": "ROLE-001", "assignee_person_id": "PRS-001",
    "status": "in_progress", "object_id": "OBJ-001",
}


def _unassigntask_allow_result():
    return {"ok": True, "allowed": True, "code": "TELEGRAM_ACCESS_ALLOWED",
            "authorization_result": {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED"}}


def _unassigntask_deny_result():
    return {"ok": True, "allowed": False, "code": "AUTHORIZATION_DENIED",
            "authorization_result": {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED"}}


def _unassigntask_infra_failure_result():
    return {"ok": False, "allowed": False, "code": "AUTHORIZATION_UNAVAILABLE",
            "authorization_result": None}


def _unassigntask_clean_success():
    return {"ok": True, "code": "TASK_UNASSIGNED", "error": None,
            "changed": True, "assignment_changed": True, "partial_state": False}


def _unassigntask_noop():
    return {"ok": True, "code": "TASK_UNASSIGNED", "error": None,
            "changed": False, "assignment_changed": False, "partial_state": False}


def _unassigntask_partial_failure():
    return {"ok": False, "code": "TASK_UNASSIGNMENT_PARTIAL_FAILURE",
            "error": "TASK_ASSIGNMENT_CACHE_CLEAR_FAILED",
            "changed": True, "assignment_changed": True, "cache_changed": False,
            "partial_state": True, "manual_review_required": True, "retry_safe": False}


_UNSET = object()


class UnassignTaskCommandTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=_UNASSIGNTASK_ROW,
                      finder_second_return=_UNSET, authz_result=None, mutator_return=None, mutator_side_effect=None,
                      task_id="TSK-001", th=None):
        th = th or _fresh_th()
        call_log = []

        if finder_side_effect is not None:
            def _finder(tid):
                call_log.append(("finder", tid))
                return finder_side_effect(tid) if callable(finder_side_effect) else (_ for _ in ()).throw(finder_side_effect)
            mock_finder = MagicMock(side_effect=_finder)
        else:
            second = finder_return if finder_second_return is _UNSET else finder_second_return
            returns = [finder_return, second]

            def _finder(tid):
                call_log.append(("finder", tid))
                return returns.pop(0) if returns else second
            mock_finder = MagicMock(side_effect=_finder)

        async def _authz(update, **kwargs):
            call_log.append(("authorize", kwargs.get("resource"), kwargs.get("action"), kwargs.get("business_id")))
            return authz_result if authz_result is not None else _unassigntask_allow_result()
        mock_authz = AsyncMock(side_effect=_authz)

        if mutator_side_effect is not None:
            def _mutator(tid):
                call_log.append(("mutate", tid))
                raise mutator_side_effect
            mock_mutator = MagicMock(side_effect=_mutator)
        else:
            def _mutator(tid):
                call_log.append(("mutate", tid))
                return mutator_return if mutator_return is not None else _unassigntask_clean_success()
            mock_mutator = MagicMock(side_effect=_mutator)

        ctx_args = args if args is not None else [f"task_id={task_id}"]
        ctx = MagicMock()
        ctx.args = ctx_args

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch(_UNASSIGNTASK_FINDER_PATH, new=mock_finder), \
                 patch(_UNASSIGNTASK_AUTHZ_PATH, new=mock_authz), \
                 patch(_UNASSIGNTASK_MUTATOR_PATH, new=mock_mutator):
                await th.unassigntask_cmd(update, ctx)

        _run(run())
        return mock_finder, mock_authz, mock_mutator, call_log

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestUnassignTaskCommand(UnassignTaskCommandTestBase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "unassigntask_cmd"))

    # ── Section 17: argument/parser tests ──────────────────────

    def test_named_task_id_accepted(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd)
        mutator.assert_called_once_with("TSK-001")

    def test_positional_task_id_accepted(self):
        upd, _ = _make_update("/unassigntask TSK-001", ["TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, args=["TSK-001"])
        mutator.assert_called_once_with("TSK-001")

    def test_blank_task_id_rejected(self):
        upd, _ = _make_update("/unassigntask", [])
        finder, authz, mutator, _ = self._run_handler(upd, args=[])
        finder.assert_not_called()
        authz.assert_not_called()
        mutator.assert_not_called()
        self.assertIn("❌", self._sent_text(upd))

    def test_unknown_named_key_rejected(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001 foo=bar", ["task_id=TSK-001", "foo=bar"])
        finder, authz, mutator, _ = self._run_handler(upd, args=["task_id=TSK-001", "foo=bar"])
        finder.assert_not_called()
        authz.assert_not_called()
        mutator.assert_not_called()
        self.assertIn("❌", self._sent_text(upd))

    def test_caller_supplied_business_id_rejected(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001 business_id=BIZ-999", ["task_id=TSK-001", "business_id=BIZ-999"])
        finder, authz, mutator, _ = self._run_handler(upd, args=["task_id=TSK-001", "business_id=BIZ-999"])
        finder.assert_not_called()
        authz.assert_not_called()
        mutator.assert_not_called()

    def test_caller_supplied_object_id_rejected(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001 object_id=OBJ-999", ["task_id=TSK-001", "object_id=OBJ-999"])
        finder, authz, mutator, _ = self._run_handler(upd, args=["task_id=TSK-001", "object_id=OBJ-999"])
        mutator.assert_not_called()

    def test_caller_supplied_role_person_assignment_fields_rejected(self):
        for extra in ("role_id=ROLE-999", "person_id=PRS-999", "assignment_id=TAS-999"):
            with self.subTest(extra=extra):
                upd, _ = _make_update(f"/unassigntask task_id=TSK-001 {extra}", ["task_id=TSK-001", extra])
                finder, authz, mutator, _ = self._run_handler(upd, args=["task_id=TSK-001", extra])
                mutator.assert_not_called()

    def test_named_task_id_wins_over_positional(self):
        upd, _ = _make_update("/unassigntask TSK-XXX task_id=TSK-001", ["TSK-XXX", "task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, args=["TSK-XXX", "task_id=TSK-001"])
        # A bare positional token becomes _pos0 — itself an allowed
        # key — so both task_id and _pos0 may be present together;
        # named task_id wins per established `.get("task_id") or
        # .get("_pos0", "")` parser convention, matching every other
        # Task command's existing precedent.
        for call in finder.call_args_list:
            self.assertEqual(call.args, ("TSK-001",))
        mutator.assert_called_once_with("TSK-001")

    # ── Section 7-8: first lookup / authorization ──────────────

    def test_task_not_found_no_authorization_no_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-999", ["task_id=TSK-999"])
        finder, authz, mutator, _ = self._run_handler(upd, finder_return=None, task_id="TSK-999")
        finder.assert_called_once_with("TSK-999")
        authz.assert_not_called()
        mutator.assert_not_called()

    def test_first_lookup_exception_no_authorization_no_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, finder_side_effect=RuntimeError("boom"))
        authz.assert_not_called()
        mutator.assert_not_called()

    # ── Malformed first-lookup shape (fail-closed) ─────────────

    class _PoisonedFirst:
        def __str__(self):
            return "STR-SECRET-MARKER"

        def __repr__(self):
            return "REPR-SECRET-MARKER"

    class _PoisonedFirstGetRaises:
        """Not a dict — has a .get() method that raises if ever
        called. isinstance(x, dict) is False for this object, so the
        handler must reject it before .get() is ever invoked."""
        def get(self, *a, **kw):
            raise RuntimeError("GET-RAISE-SECRET-MARKER")

    def test_malformed_first_lookup_shapes_fail_closed(self):
        markers = ("STR-SECRET-MARKER", "REPR-SECRET-MARKER")
        malformed = [None, {}, [], "bad", object(), 0, 1, self._PoisonedFirst()]
        for value in malformed:
            with self.subTest(first=repr(value)):
                upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
                with patch("business_core.telegram_handlers.log") as mock_log:
                    finder, authz, mutator, _ = self._run_handler(upd, finder_return=value)
                authz.assert_not_called()
                mutator.assert_not_called()
                self.assertEqual(finder.call_count, 1)
                self.assertEqual(upd.message.reply_text.call_count, 1)
                reply = self._sent_text(upd)
                self.assertEqual(reply, "Запись недоступна или не найдена.")
                for marker in markers:
                    self.assertNotIn(marker, reply)
                for call in mock_log.mock_calls:
                    call_text = str(call)
                    for marker in markers:
                        self.assertNotIn(marker, call_text)

    def test_malformed_first_lookup_get_raises_is_never_called(self):
        # A non-dict object whose .get() would raise if ever called —
        # proves the isinstance(dict) guard rejects it before .get()
        # is invoked at all, so the poisoned .get() never executes.
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        poisoned = self._PoisonedFirstGetRaises()
        finder, authz, mutator, _ = self._run_handler(upd, finder_return=poisoned)
        authz.assert_not_called()
        mutator.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись недоступна или не найдена.")

    # ── Malformed second-lookup shape (fail-closed) ────────────

    def test_malformed_second_lookup_shapes_fail_closed(self):
        markers = ("STR-SECRET-MARKER", "REPR-SECRET-MARKER")
        malformed = [None, {}, [], "bad", object(), 0, 1, self._PoisonedFirst()]
        for value in malformed:
            with self.subTest(second=repr(value)):
                upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
                with patch("business_core.telegram_handlers.log") as mock_log:
                    finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=value)
                authz.assert_called_once()
                self.assertEqual(finder.call_count, 2)
                mutator.assert_not_called()
                self.assertEqual(upd.message.reply_text.call_count, 1)
                reply = self._sent_text(upd)
                self.assertEqual(reply, "Запись изменилась. Повтори команду ещё раз.")
                for marker in markers:
                    self.assertNotIn(marker, reply)
                for call in mock_log.mock_calls:
                    call_text = str(call)
                    for marker in markers:
                        self.assertNotIn(marker, call_text)

    def test_empty_dict_first_lookup_blocked_via_blank_business_id(self):
        """Documents the exact source path: {} passes isinstance(dict)
        but its Business ID normalizes to blank, so it is blocked by
        the existing required-ownership check — not by falling
        through to the (second-lookup-only) protected-field
        comparison, which {} never reaches on the first lookup."""
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, finder_return={})
        authz.assert_not_called()
        mutator.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись недоступна или не найдена.")

    def test_empty_dict_second_lookup_blocked_via_blank_business_id(self):
        """Same explicit blank-Business-ID path on the second lookup —
        {} normalizes to a blank Business ID and is blocked before the
        3-field protected comparison ever executes."""
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return={})
        authz.assert_called_once()
        mutator.assert_not_called()
        self.assertEqual(self._sent_text(upd), "Запись изменилась. Повтори команду ещё раз.")

    def test_authorization_uses_resource_task_action_assign(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, call_log = self._run_handler(upd)
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[1], "TASK")
        self.assertEqual(authz_call[2], "ASSIGN")

    def test_authorization_uses_stored_business_id_not_caller_supplied(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, call_log = self._run_handler(upd)
        authz_call = [c for c in call_log if c[0] == "authorize"][0]
        self.assertEqual(authz_call[3], "BIZ-001")

    def test_authorization_called_exactly_once(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd)
        authz.assert_called_once()

    def test_authorization_denial_prevents_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, authz_result=_unassigntask_deny_result())
        mutator.assert_not_called()
        self.assertEqual(finder.call_count, 1)

    def test_authorization_infrastructure_failure_prevents_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, authz_result=_unassigntask_infra_failure_result())
        mutator.assert_not_called()

    # ── Section 9: second lookup / protected-field comparison ──

    def test_second_lookup_occurs_after_authorization(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, call_log = self._run_handler(upd)
        order = [c[0] for c in call_log]
        self.assertEqual(order, ["finder", "authorize", "finder", "mutate"])

    def test_second_lookup_missing_blocks_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=None)
        mutator.assert_not_called()

    def test_business_id_change_blocks_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        changed_row = {**_UNASSIGNTASK_ROW, "business_id": "BIZ-002"}
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=changed_row)
        mutator.assert_not_called()

    def test_responsible_role_id_change_blocks_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        changed_row = {**_UNASSIGNTASK_ROW, "responsible_role_id": "ROLE-999"}
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=changed_row)
        mutator.assert_not_called()

    def test_assignee_person_id_change_blocks_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        changed_row = {**_UNASSIGNTASK_ROW, "assignee_person_id": "PRS-999"}
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=changed_row)
        mutator.assert_not_called()

    def test_status_only_change_does_not_block_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        changed_row = {**_UNASSIGNTASK_ROW, "status": "done"}
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=changed_row)
        mutator.assert_called_once_with("TSK-001")

    def test_object_id_only_change_does_not_block_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        changed_row = {**_UNASSIGNTASK_ROW, "object_id": "OBJ-999"}
        finder, authz, mutator, _ = self._run_handler(upd, finder_second_return=changed_row)
        mutator.assert_called_once_with("TSK-001")

    def test_second_lookup_exception_blocks_mutation(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        calls = {"n": 0}

        def _finder_side_effect(tid):
            calls["n"] += 1
            if calls["n"] == 1:
                return _UNASSIGNTASK_ROW
            raise RuntimeError("boom")
        finder, authz, mutator, _ = self._run_handler(upd, finder_side_effect=_finder_side_effect)
        mutator.assert_not_called()

    def test_same_task_across_both_reads_mutation_allowed(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd)
        mutator.assert_called_once_with("TSK-001")

    # ── Section 10: mutation / mapper integration ──────────────

    def test_mutation_called_exactly_once(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd)
        mutator.assert_called_once()

    def test_clean_success_reply(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, mutator_return=_unassigntask_clean_success())
        self.assertIn("✅", self._sent_text(upd))

    def test_already_unassigned_noop_reply(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, mutator_return=_unassigntask_noop())
        self.assertIn("ℹ️", self._sent_text(upd))

    def test_partial_state_failure_reply(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, mutator_return=_unassigntask_partial_failure())
        self.assertIn("⚠️", self._sent_text(upd))

    def test_multiple_active_conflict_reply(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd, mutator_return={
            "ok": False, "code": "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
            "conflicting_assignment_ids": ("TAS-A", "TAS-B"), "error": "x",
        })
        self.assertIn("⚠️", self._sent_text(upd))

    def test_reply_at_most_once(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        self._run_handler(upd)
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_no_retry_on_mutation_exception(self):
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        finder, authz, mutator, _ = self._run_handler(upd, mutator_side_effect=RuntimeError("boom internal detail"))
        mutator.assert_called_once()
        reply = self._sent_text(upd)
        self.assertIn("❌", reply)
        self.assertNotIn("boom internal detail", reply)
        self.assertNotIn("Traceback", reply)

    def test_mutation_exception_fixed_log_literal(self):
        th = _fresh_th()
        upd, _ = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])
        with patch.object(th, "log") as mock_log:
            self._run_handler(upd, mutator_side_effect=RuntimeError("boom internal detail"), th=th)
            mock_log.error.assert_called_once_with("unassigntask_cmd mutation infrastructure failure")

    def test_missing_task_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/unassigntask", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.unassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)


class TestNoRawExceptionExposure(unittest.TestCase):

    def test_all_task_commands_swallow_exceptions_safely(self):
        import contextlib

        th = _fresh_th()
        commands_and_patches = [
            ("newbctask_cmd", ("create_business_task",), '/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"']),
            ("bctasks_cmd", ("task_manager.list_tasks",), "/bctasks", []),
            ("updatetask_cmd", ("transition_task_status",), "/updatetask task_id=TSK-001 status=ready", ["task_id=TSK-001", "status=ready"]),
            ("assigntask_cmd", ("assign_task",), "/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            ("reassigntask_cmd", ("assign_task",), "/reassigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            # unassigntask_cmd and bctask_cmd are now authorized,
            # secure-flow commands (canonical lookup + authorization sit
            # ahead of any mutation/formatting) — their own raw-exception-
            # secrecy coverage lives in TestUnassignTaskCommand and
            # TestBcTaskCommand instead, with the finder/authorization
            # properly mocked.
        ]
        for cmd_name, targets, text, args_list in commands_and_patches:
            upd, ctx = _make_update(text, args_list)
            cmd = getattr(th, cmd_name)

            async def run():
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                    for target in targets:
                        module = "business_core.business_builder" if "." not in target else f"business_core.{target.split('.')[0]}"
                        attr = target.split(".")[-1]
                        stack.enter_context(patch(f"{module}.{attr}", side_effect=RuntimeError("boom internal detail")))
                    await cmd(upd, ctx)

            _run(run())
            reply = upd.message.reply_text.call_args[0][0]
            self.assertIn("❌", reply, f"{cmd_name} did not show an error")
            self.assertNotIn("boom internal detail", reply, f"{cmd_name} leaked exception text")
            self.assertNotIn("Traceback", reply, f"{cmd_name} leaked a traceback")


if __name__ == "__main__":
    unittest.main()
