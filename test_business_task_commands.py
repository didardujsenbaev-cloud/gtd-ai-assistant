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

_NEWBCTASK_UNSET = object()


def _newbctask_allow_result():
    return {"ok": True, "allowed": True, "code": "TELEGRAM_ACCESS_ALLOWED",
            "authorization_result": {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED"}}


def _newbctask_deny_result():
    return {"ok": True, "allowed": False, "code": "AUTHORIZATION_DENIED",
            "authorization_result": {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED"}}


def _newbctask_infra_failure_result():
    return {"ok": False, "allowed": False, "code": "AUTHORIZATION_UNAVAILABLE",
            "authorization_result": None}


class NewBcTaskCommandTestBase(unittest.TestCase):
    """Phase 18A.8-C1: /newbctask is TASK/CREATE, target_shape=BUSINESS.
    Mirrors BcTasksCommandTestBase's low-level-authorization-patch
    pattern (patches authorize_telegram_business_core_request, the
    function _authorize_or_reply itself calls, rather than
    _authorize_or_reply — proving the real authorization wiring, not
    a test-only shortcut)."""

    def _run_handler(self, update, args=None, *, create_side_effect=None, create_return=_NEWBCTASK_UNSET,
                      authz_result=None, th=None):
        th = th or _fresh_th()
        call_log = []

        if create_side_effect is not None:
            def _create(*a, **kw):
                call_log.append(("create_business_task", a, kw))
                if callable(create_side_effect):
                    return create_side_effect(*a, **kw)
                raise create_side_effect
            mock_create = MagicMock(side_effect=_create)
        else:
            effective_return = create_return if create_return is not _NEWBCTASK_UNSET else {
                "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
            }

            def _create(*a, **kw):
                call_log.append(("create_business_task", a, kw))
                return effective_return
            mock_create = MagicMock(side_effect=_create)

        async def _authz(update, **kwargs):
            call_log.append(("authorize", kwargs.get("resource"), kwargs.get("action"), kwargs.get("business_id")))
            return authz_result if authz_result is not None else _newbctask_allow_result()
        mock_authz = AsyncMock(side_effect=_authz)

        ctx_args = args if args is not None else ["business_id=BIZ-001", 'title="Prepare docs"', "idempotency_key=op:test"]
        ctx = MagicMock()
        ctx.args = ctx_args

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task", new=mock_create), \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=mock_authz):
                await th.newbctask_cmd(update, ctx)

        _run(run())
        return mock_create, mock_authz, call_log

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestNewBcTaskCommand(NewBcTaskCommandTestBase):

    # ── registration / enforcement scope ──

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "newbctask_cmd"))

    def test_map_contains_newbctask(self):
        th = _fresh_th()
        self.assertIn("newbctask", th.COMMAND_ENFORCEMENT_MAP)
        self.assertEqual(
            th.COMMAND_ENFORCEMENT_MAP["newbctask"],
            {
                "resource": "TASK", "action": "CREATE", "target_shape": "BUSINESS",
                "operation_kind": "MUTATION", "requires_fresh_reread": False,
            },
        )

    def test_task_map_keys(self):
        th = _fresh_th()
        task_keys = {k for k in th.COMMAND_ENFORCEMENT_MAP if "task" in k}
        self.assertEqual(task_keys, {"unassigntask", "bctask", "bctasks", "newbctask"})

    def test_map_size_18(self):
        th = _fresh_th()
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 18)

    # ── gates ──

    def test_disabled_gate(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        th = _fresh_th()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
                 patch("business_core.business_builder.create_business_task") as m_create, \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request") as m_authz:
                await th.newbctask_cmd(upd, _make_update("x", [])[1])
                m_create.assert_not_called()
                m_authz.assert_not_called()

        _run(run())

    def test_transport_validation(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        upd.effective_chat = None
        mock_create, mock_authz, _ = self._run_handler(upd)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    # ── allowed-key set ──

    def test_exact_allowed_key_set(self):
        # allowed_keys is function-local (Phase 18A.8-C1-F0) — extract
        # it from the handler's own source rather than a module
        # attribute.
        th = _fresh_th()
        import ast, inspect
        src = inspect.getsource(th.newbctask_cmd)
        tree = ast.parse(src)
        func = tree.body[0]
        allowed_keys = None
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "allowed_keys" for t in node.targets
            ):
                allowed_keys = {elt.value for elt in node.value.elts}
                break
        self.assertIsNotNone(allowed_keys, "allowed_keys assignment not found in newbctask_cmd source")
        self.assertEqual(
            allowed_keys,
            {
                "business_id", "title", "description", "priority", "due_date", "source",
                "idempotency_key", "client_id", "object_id", "service_id", "roadmap_id", "stage_id",
            },
        )

    def test_positional_rejected(self):
        upd, _ = _make_update("/newbctask BIZ-001", ["BIZ-001"])
        mock_create, mock_authz, _ = self._run_handler(upd, args=["BIZ-001"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_unknown_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" foo=bar',
            ["business_id=BIZ-001", 'title="X"', "foo=bar", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "foo=bar", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_status_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" status=done',
            ["business_id=BIZ-001", 'title="X"', "status=done", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "status=done", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_created_by_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" created_by=999',
            ["business_id=BIZ-001", 'title="X"', "created_by=999", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "created_by=999", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_task_id_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" task_id=TSK-999',
            ["business_id=BIZ-001", 'title="X"', "task_id=TSK-999", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "task_id=TSK-999", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_gtd_action_id_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" gtd_action_id=ACT-1',
            ["business_id=BIZ-001", 'title="X"', "gtd_action_id=ACT-1", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "gtd_action_id=ACT-1", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_responsible_role_id_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" responsible_role_id=ROLE-1',
            ["business_id=BIZ-001", 'title="X"', "responsible_role_id=ROLE-1", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "responsible_role_id=ROLE-1", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_assignee_person_id_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" assignee_person_id=PRS-1',
            ["business_id=BIZ-001", 'title="X"', "assignee_person_id=PRS-1", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "assignee_person_id=PRS-1", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_scope_key_rejected(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" scope=ALL',
            ["business_id=BIZ-001", 'title="X"', "scope=ALL", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "scope=ALL", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    # ── required fields ──

    def test_missing_business_id_rejected(self):
        upd, _ = _make_update('/newbctask title="X"', ['title="X"'])
        mock_create, mock_authz, _ = self._run_handler(upd, args=['title="X"'])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_missing_title_rejected(self):
        upd, _ = _make_update("/newbctask business_id=BIZ-001", ["business_id=BIZ-001"])
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_blank_business_id_rejected(self):
        upd, _ = _make_update('/newbctask business_id= title="X"', ["business_id=", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=", 'title="X"', "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_blank_title_rejected(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title=', ["business_id=BIZ-001", "title=", "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", "title=", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    # ── input caps ──

    def test_business_id_at_limit_accepted(self):
        value = "B" * 64
        args = [f"business_id={value}", 'title="X"', "idempotency_key=op:test"]
        upd, _ = _make_update(f'/newbctask business_id={value} title="X"', args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_authz.assert_awaited_once()
        mock_create.assert_called_once()

    def test_business_id_over_limit_rejected(self):
        value = "B" * 65
        args = [f"business_id={value}", 'title="X"', "idempotency_key=op:test"]
        upd, _ = _make_update(f'/newbctask business_id={value} title="X"', args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_title_at_limit_accepted(self):
        value = "T" * 300
        upd, _ = _make_update(
            f'/newbctask business_id=BIZ-001 title={value}', ["business_id=BIZ-001", f"title={value}", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", f"title={value}", "idempotency_key=op:test"])
        mock_authz.assert_awaited_once()
        mock_create.assert_called_once()

    def test_title_over_limit_rejected(self):
        value = "T" * 301
        upd, _ = _make_update(
            f'/newbctask business_id=BIZ-001 title={value}', ["business_id=BIZ-001", f"title={value}", "idempotency_key=op:test"],
        )
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", f"title={value}", "idempotency_key=op:test"])
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_description_over_limit_rejected(self):
        value = "D" * 4001
        args = ["business_id=BIZ-001", 'title="X"', f"description={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_priority_over_limit_rejected(self):
        value = "P" * 33
        args = ["business_id=BIZ-001", 'title="X"', f"priority={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_due_date_over_limit_rejected(self):
        value = "2" * 33
        args = ["business_id=BIZ-001", 'title="X"', f"due_date={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_source_over_limit_rejected(self):
        value = "S" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"source={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_idempotency_key_over_limit_rejected(self):
        value = "K" * 129
        args = ["business_id=BIZ-001", 'title="X"', f"idempotency_key={value}"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_client_id_over_limit_rejected(self):
        value = "C" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"client_id={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_object_id_over_limit_rejected(self):
        value = "O" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"object_id={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_service_id_over_limit_rejected(self):
        value = "S" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"service_id={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_roadmap_id_over_limit_rejected(self):
        value = "R" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"roadmap_id={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_stage_id_over_limit_rejected(self):
        value = "T" * 65
        args = ["business_id=BIZ-001", 'title="X"', f"stage_id={value}", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_due_date_bad_format_rejected(self):
        args = ["business_id=BIZ-001", 'title="X"', "due_date=not-a-date", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_due_date_valid_format_accepted(self):
        args = ["business_id=BIZ-001", 'title="X"', "due_date=2026-01-15", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_authz.assert_awaited_once()
        mock_create.assert_called_once()

    # ── authorization wiring ──

    def test_authorization_exact_call(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, call_log = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_authz.assert_awaited_once()
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs.get("resource"), "TASK")
        self.assertEqual(kwargs.get("action"), "CREATE")
        self.assertEqual(kwargs.get("business_id"), "BIZ-001")

    def test_authorization_count_one(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self.assertEqual(mock_authz.call_count, 1)

    def test_authorization_before_create_call(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        _, _, call_log = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        names = [c[0] for c in call_log]
        self.assertEqual(names.index("authorize"), 0)
        self.assertLess(names.index("authorize"), names.index("create_business_task"))

    def test_denied_blocks_create(self):
        th = _fresh_th()
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], authz_result=_newbctask_deny_result(), th=th,
        )
        mock_create.assert_not_called()
        self.assertEqual(self._sent_text(upd), th._BC_ENFORCEMENT_NOT_FOUND_OR_DENIED_MSG)

    def test_authorization_infra_failure_blocks_create(self):
        th = _fresh_th()
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], authz_result=_newbctask_infra_failure_result(), th=th,
        )
        mock_create.assert_not_called()
        self.assertEqual(self._sent_text(upd), th._BC_ENFORCEMENT_TEMPORARILY_UNAVAILABLE_MSG)

    # ── thread offload / call shape ──

    def test_create_business_task_called_once_on_allowed_path(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self.assertEqual(mock_create.call_count, 1)

    def test_exact_kwargs_passed(self):
        upd, _ = _make_update(
            '/newbctask business_id=BIZ-001 title="X" description=D priority=P due_date=2026-01-01 '
            'source=telegram idempotency_key=K1 client_id=PRS-1 object_id=OBJ-1 service_id=SVC-1 '
            'roadmap_id=RM-1 stage_id=ST-1',
            ["business_id=BIZ-001", 'title="X"', "description=D", "priority=P", "due_date=2026-01-01",
             "source=telegram", "idempotency_key=K1", "client_id=PRS-1", "object_id=OBJ-1",
             "service_id=SVC-1", "roadmap_id=RM-1", "stage_id=ST-1"],
        )
        mock_create, _, call_log = self._run_handler(upd, args=[
            "business_id=BIZ-001", 'title="X"', "description=D", "priority=P", "due_date=2026-01-01",
            "source=telegram", "idempotency_key=K1", "client_id=PRS-1", "object_id=OBJ-1",
            "service_id=SVC-1", "roadmap_id=RM-1", "stage_id=ST-1",
        ])
        args, kwargs = mock_create.call_args
        self.assertEqual(args, ("BIZ-001", "X"))
        self.assertEqual(kwargs["description"], "D")
        self.assertEqual(kwargs["priority"], "P")
        self.assertEqual(kwargs["due_date"], "2026-01-01")
        self.assertEqual(kwargs["source"], "telegram")
        self.assertEqual(kwargs["idempotency_key"], "K1")
        self.assertEqual(kwargs["client_id"], "PRS-1")
        self.assertEqual(kwargs["object_id"], "OBJ-1")
        self.assertEqual(kwargs["service_id"], "SVC-1")
        self.assertEqual(kwargs["roadmap_id"], "RM-1")
        self.assertEqual(kwargs["stage_id"], "ST-1")
        self.assertEqual(kwargs["created_by"], "999")
        self.assertNotIn("gtd_action_id", kwargs)
        self.assertNotIn("status", kwargs)
        self.assertNotIn("task_id", kwargs)

    def test_create_business_task_offloaded_to_thread(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        seen_thread = {}

        def fake_create(*a, **kw):
            import threading
            seen_thread["name"] = threading.current_thread().name
            return {"ok": True, "code": "TASK_CREATED", "task_id": "T1", "business_id": "BIZ-001", "final_status": "new", "error": None}

        async def _authz(update, **kwargs):
            return _newbctask_allow_result()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task", side_effect=fake_create), \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=AsyncMock(side_effect=_authz)):
                import threading
                seen_thread["main"] = threading.current_thread().name
                await th.newbctask_cmd(upd, ctx)

        _run(run())
        self.assertNotEqual(seen_thread["name"], seen_thread["main"])

    def test_no_retry_on_denied(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, mock_authz, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], authz_result=_newbctask_deny_result(),
        )
        self.assertEqual(mock_authz.call_count, 1)
        mock_create.assert_not_called()

    # ── source / idempotency-key (Phase 18A.9-A3-A1: key required) ──
    #
    # idempotency_key identifies a business CREATE operation (scoped
    # with Business ID in core). It is NOT Task content identity:
    # same content + different key ⇒ new operation; same key in the
    # same Business ⇒ reuse; same key in another Business ⇒ separate
    # scope under current core semantics.

    def test_default_source(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self.assertEqual(mock_create.call_args[1]["source"], "telegram")

    def test_caller_source(self):
        args = ["business_id=BIZ-001", 'title="X"', "source=manual", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(upd, args=args)
        self.assertEqual(mock_create.call_args[1]["source"], "manual")

    def test_missing_idempotency_key_rejected_no_mutation(self):
        args = ["business_id=BIZ-001", 'title="X"']
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()
        text = self._sent_text(upd)
        self.assertIn("idempotency_key", text)
        self.assertIn("тот же ключ", text)
        self.assertIn("новый ключ", text)
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_blank_idempotency_key_rejected_no_mutation(self):
        args = ["business_id=BIZ-001", 'title="X"', "idempotency_key="]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_whitespace_only_idempotency_key_rejected_no_mutation(self):
        args = ["business_id=BIZ-001", 'title="X"', 'idempotency_key="   "']
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_no_automatic_tg_update_id_business_key(self):
        """Omitted key must NOT mint tg-<update_id> as operation identity."""
        args = ["business_id=BIZ-001", 'title="X"']
        upd, _ = _make_update("/newbctask ...", args)
        upd.update_id = 777
        mock_create, mock_authz, call_log = self._run_handler(upd, args=args)
        mock_create.assert_not_called()
        mock_authz.assert_not_called()
        self.assertNotIn("tg-777", self._sent_text(upd))

    def test_caller_idempotency_key_passed_unchanged(self):
        args = ["business_id=BIZ-001", 'title="X"', "idempotency_key=MY-KEY"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(upd, args=args)
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "MY-KEY")

    def test_idempotency_key_strip_retains_case(self):
        args = ["business_id=BIZ-001", 'title="X"', 'idempotency_key="  Op:AbC  "']
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(upd, args=args)
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "Op:AbC")

    def test_legacy_tg_key_still_accepted_when_explicit(self):
        """Legacy stored tg-* values remain usable if the caller supplies them."""
        args = ["business_id=BIZ-001", 'title="X"', "idempotency_key=tg-12345"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(upd, args=args)
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "tg-12345")

    def test_update_id_irrelevant_when_key_supplied(self):
        """Transport update_id is not a business-operation key after A3-A1."""
        args = ["business_id=BIZ-001", 'title="X"', "idempotency_key=CALLER-KEY"]
        upd, _ = _make_update("/newbctask ...", args)
        upd.update_id = None
        mock_create, _, _ = self._run_handler(upd, args=args)
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "CALLER-KEY")

    def test_same_key_surfaces_reused_with_key(self):
        args = ["business_id=BIZ-001", 'title="Prepare"', "idempotency_key=op:abc"]
        upd1, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(
            upd1, args=args,
            create_return={
                "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
            },
        )
        self.assertEqual(mock_create.call_count, 1)
        text1 = self._sent_text(upd1)
        self.assertIn("TSK-001", text1)
        self.assertIn("op:abc", text1)
        self.assertEqual(upd1.message.reply_text.call_count, 1)

        upd2, _ = _make_update("/newbctask ...", args)
        mock_create2, _, _ = self._run_handler(
            upd2, args=args,
            create_return={
                "ok": True, "code": "TASK_REUSED", "task_id": "TSK-001",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
                "task_reused": True,
            },
        )
        self.assertEqual(mock_create2.call_count, 1)
        text2 = self._sent_text(upd2)
        self.assertIn("переиспользован", text2)
        self.assertIn("op:abc", text2)
        self.assertIn("TSK-001", text2)
        self.assertEqual(upd2.message.reply_text.call_count, 1)

    def test_different_keys_are_separate_operations(self):
        """Same title + different key must not be content-deduped at Telegram layer."""
        args_a = ["business_id=BIZ-001", 'title="Prepare"', "idempotency_key=op:abc"]
        args_b = ["business_id=BIZ-001", 'title="Prepare"', "idempotency_key=op:def"]
        upd_a, _ = _make_update("/newbctask ...", args_a)
        mock_a, _, _ = self._run_handler(
            upd_a, args=args_a,
            create_return={
                "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
            },
        )
        upd_b, _ = _make_update("/newbctask ...", args_b)
        mock_b, _, _ = self._run_handler(
            upd_b, args=args_b,
            create_return={
                "ok": True, "code": "TASK_CREATED", "task_id": "TSK-002",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
            },
        )
        self.assertEqual(mock_a.call_args[1]["idempotency_key"], "op:abc")
        self.assertEqual(mock_b.call_args[1]["idempotency_key"], "op:def")
        self.assertIn("TSK-002", self._sent_text(upd_b))

    def test_adversarial_key_output_bounded_no_injection(self):
        key128 = ("*`_[]<>" * 20)[:128]
        args = ["business_id=BIZ-001", 'title="X"', f"idempotency_key={key128}"]
        upd, _ = _make_update("/newbctask ...", args)
        mock_create, _, _ = self._run_handler(
            upd, args=args,
            create_return={
                "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
                "business_id": "BIZ-001", "final_status": "new", "error": None,
            },
        )
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], key128)
        text = self._sent_text(upd)
        self.assertEqual(upd.message.reply_text.call_count, 1)
        self.assertLess(len(text), 4000)
        # Mapper bounds rendered key to 64 + ellipsis; raw 128 never appears.
        self.assertIn("…", text)
        self.assertNotIn(key128, text)
        kwargs = upd.message.reply_text.call_args.kwargs
        self.assertTrue(kwargs.get("parse_mode") is None or "parse_mode" not in kwargs)

    # ── created_by ──

    def test_created_by_derived_from_effective_user(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        upd.effective_user = SimpleNamespace(id=54321)
        mock_create, _, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self.assertEqual(mock_create.call_args[1]["created_by"], "54321")

    def test_caller_cannot_override_created_by(self):
        args = ["business_id=BIZ-001", 'title="X"', "created_by=SOMEONE-ELSE", "idempotency_key=op:test"]
        upd, _ = _make_update("/newbctask ...", args)
        upd.effective_user = SimpleNamespace(id=111)
        mock_create, mock_authz, _ = self._run_handler(upd, args=args)
        # created_by is an unknown/rejected key — the command is
        # rejected outright before ever reaching create_business_task.
        mock_create.assert_not_called()
        mock_authz.assert_not_called()

    def test_missing_effective_user_at_transport_layer_fails_closed(self):
        # update.effective_user is required (and .id checked) by the
        # existing, unmodified _validate_bc_transport_or_reply layer
        # itself — so this case is already blocked before this
        # handler's own authorization/created_by logic ever runs.
        th = _fresh_th()
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        upd.effective_user = None
        mock_create, mock_authz, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], th=th)
        mock_authz.assert_not_called()
        mock_create.assert_not_called()

    def test_created_by_guard_fires_if_reached_post_authorization(self):
        # Direct, isolated proof of this handler's OWN created_by
        # fail-closed guard (§12), independent of the transport layer
        # that would normally catch a missing effective_user first —
        # bypasses _validate_bc_transport_or_reply to reach the point
        # in newbctask_cmd where this handler resolves created_by
        # itself, proving that code path also fails closed rather than
        # ever calling create_business_task with a bad/blank actor id.
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        upd.effective_user = None

        async def _authz(update, **kwargs):
            return _newbctask_allow_result()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.telegram_handlers._validate_bc_transport_or_reply", new=AsyncMock(return_value=True)), \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=AsyncMock(side_effect=_authz)), \
                 patch("business_core.business_builder.create_business_task") as m_create:
                await th.newbctask_cmd(upd, ctx)
                m_create.assert_not_called()

        _run(run())
        self.assertEqual(self._sent_text(upd), th._BC_ENFORCEMENT_TEMPORARILY_UNAVAILABLE_MSG)

    # ── malformed result / exceptions ──

    def test_malformed_result_none_handled_safely(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return=None)
        self.assertIn("❌", self._sent_text(upd))
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_malformed_result_list_handled_safely(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return=[])
        self.assertIn("❌", self._sent_text(upd))
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_unexpected_exception_uses_uncertain_create_message(self):
        th = _fresh_th()
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_side_effect=RuntimeError("SENTINEL-BOOM"), th=th,
        )
        reply = self._sent_text(upd)
        self.assertEqual(
            reply,
            "❌ Не удалось подтвердить создание Task. Проверьте список Tasks перед повторной попыткой.",
        )
        self.assertNotIn("SENTINEL-BOOM", reply)
        self.assertNotIn("TASK_REUSED", reply)
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_exception_reply_not_a_success_claim(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        mock_create, _, _ = self._run_handler(
            upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_side_effect=RuntimeError("boom"),
        )
        reply = self._sent_text(upd)
        self.assertNotIn("✅", reply)

    # ── result-code mapping via the handler ──

    def test_task_created_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return={
            "ok": True, "code": "TASK_CREATED", "task_id": "TSK-1", "business_id": "BIZ-001",
            "final_status": "new", "error": None,
        })
        reply = self._sent_text(upd)
        self.assertIn("✅", reply)
        self.assertIn("TSK-1", reply)

    def test_task_reused_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return={
            "ok": True, "code": "TASK_REUSED", "task_id": "TSK-2", "final_status": "ready", "error": None,
        })
        reply = self._sent_text(upd)
        self.assertIn("ℹ️", reply)
        self.assertIn("TSK-2", reply)

    def test_task_storage_error_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return={
            "ok": False, "code": "TASK_STORAGE_ERROR", "error": None,
        })
        reply = self._sent_text(upd)
        self.assertIn("❌", reply)

    def test_relation_mismatch_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return={
            "ok": False, "code": "TASK_ENTITY_RELATION_MISMATCH", "error": "x",
        })
        reply = self._sent_text(upd)
        self.assertIn("❌", reply)

    def test_exactly_one_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        self.assertEqual(upd.message.reply_text.call_count, 1)

    # ── adversarial output-bound proof ──

    def test_adversarial_long_result_stays_one_reply(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        huge = "A" * 100000
        self._run_handler(upd, args=["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"], create_return={
            "ok": True, "code": "TASK_CREATED", "task_id": huge, "business_id": huge, "final_status": "new", "error": None,
        })
        self.assertEqual(upd.message.reply_text.call_count, 1)
        reply = upd.message.reply_text.call_args[0][0]
        self.assertLess(len(reply), 4000)
        self.assertNotIn("A" * 1000, reply)

    # ── no GTD / no assignment writes ──

    def test_no_gtd_module_imported(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', ["business_id=BIZ-001", 'title="X"', "idempotency_key=op:test"])
        th = _fresh_th()
        import inspect
        src = inspect.getsource(th.newbctask_cmd)
        for forbidden in ("inbox_processor", "project_planner", "calendar_sync", "create_task_assignment"):
            self.assertNotIn(forbidden, src)

    def test_no_direct_create_business_task_call_on_event_loop(self):
        th = _fresh_th()
        import inspect
        src = inspect.getsource(th.newbctask_cmd)
        self.assertIn("asyncio.to_thread(", src)
        self.assertNotIn("create_business_task(\n", src.split("asyncio.to_thread(")[0])


class _PoisonedIdentity:
    """Stands in for a Telegram identity field whose __str__/__repr__
    raise — proves type(x) is int rejects it without ever invoking
    either dunder (type() never touches instance-level __getattribute__/
    __str__/__repr__)."""
    def __str__(self):
        raise RuntimeError("STR-SENTINEL-MARKER")

    def __repr__(self):
        raise RuntimeError("REPR-SENTINEL-MARKER")


class TestNewBcTaskCommandIdentityHardening(NewBcTaskCommandTestBase):
    """Phase 18A.8-C1-F1 / 18A.9-A3-A1: strict type(x) is int + positivity
    validation for update.effective_user.id (created_by). Transport
    update_id is no longer used as a business-operation key — the
    explicit caller idempotency_key is required instead."""

    _ARGS = ["business_id=BIZ-001", 'title="Prepare docs"', "idempotency_key=op:test"]

    # ── effective_user.id matrix ──

    def _run_with_user_id(self, user_id, effective_user_present=True):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
        upd.effective_user = SimpleNamespace(id=user_id) if effective_user_present else None
        return self._run_handler(upd, args=list(self._ARGS)), upd

    def test_user_id_none_effective_user_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(None, effective_user_present=False)
        mock_create.assert_not_called()

    def test_user_id_missing_attribute_rejected(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
        upd.effective_user = object()  # no .id attribute at all
        mock_create, mock_authz, _ = self._run_handler(upd, args=list(self._ARGS))
        mock_create.assert_not_called()
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_user_id_none_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(None)
        mock_create.assert_not_called()

    def test_user_id_blank_string_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id("")
        mock_create.assert_not_called()

    def test_user_id_numeric_string_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id("123")
        mock_create.assert_not_called()

    def test_user_id_zero_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(0)
        mock_create.assert_not_called()

    def test_user_id_negative_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(-1)
        mock_create.assert_not_called()

    def test_user_id_bool_true_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(True)
        mock_create.assert_not_called()

    def test_user_id_bool_false_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(False)
        mock_create.assert_not_called()

    def test_user_id_float_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(1.0)
        mock_create.assert_not_called()

    def test_user_id_list_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id([])
        mock_create.assert_not_called()

    def test_user_id_dict_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id({})
        mock_create.assert_not_called()

    def test_user_id_tuple_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(())
        mock_create.assert_not_called()

    def test_user_id_plain_object_rejected(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(object())
        mock_create.assert_not_called()

    def test_user_id_poisoned_rejected_by_own_check_no_str_invocation(self):
        # Isolated proof of newbctask_cmd's OWN type(x) is int guard:
        # with the shared, unmodified transport-validation layer
        # bypassed (it is out of this phase's approved scope and has
        # its own pre-existing, separate str(user_id) call — see
        # test_user_id_poisoned_crashes_at_shared_transport_layer
        # below), this handler's own identity check rejects a poisoned
        # object without ever invoking its __str__/__repr__.
        # th resolved BEFORE entering the patch context — patching by
        # dotted module path only rebinds attributes on the currently-
        # imported module object, so a fresh import performed *inside*
        # the patched block would silently bypass every patch above.
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
        upd.effective_user = SimpleNamespace(id=_PoisonedIdentity())

        async def _authz(update, **kwargs):
            return _newbctask_allow_result()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.telegram_handlers._validate_bc_transport_or_reply", new=AsyncMock(return_value=True)), \
                 patch("business_core.business_builder.create_business_task") as m_cbt, \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=AsyncMock(side_effect=_authz)):
                try:
                    await th.newbctask_cmd(upd, ctx)
                except Exception as e:
                    self.fail(f"exception escaped newbctask_cmd's own identity check: {type(e).__name__}: {e}")
                m_cbt.assert_not_called()

        _run(run())
        reply = self._sent_text(upd)
        self.assertNotIn("STR-SENTINEL-MARKER", reply)
        self.assertNotIn("REPR-SENTINEL-MARKER", reply)
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_user_id_poisoned_end_to_end_fails_closed_no_crash(self):
        # Phase 18A.8-C1-F2: the shared transport layer
        # (validate_telegram_business_core_transport, in
        # telegram_authorization.py) is now hardened too — a poisoned
        # effective_user.id no longer crashes the real end-to-end
        # flow. This replaces the prior phase's crash-expectation test
        # now that the shared boundary itself fails closed; the
        # isolated handler-local check above remains as defense-in-
        # depth proving newbctask_cmd's own logic is independently
        # safe regardless of the shared layer.
        th = _fresh_th()
        upd, ctx = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
        upd.effective_user = SimpleNamespace(id=_PoisonedIdentity())

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.create_business_task") as m_cbt, \
                 patch("business_core.telegram_authorization.authorize_telegram_business_core_request") as m_authz:
                try:
                    await th.newbctask_cmd(upd, ctx)
                except Exception as e:
                    self.fail(f"exception escaped newbctask_cmd end-to-end: {type(e).__name__}: {e}")
                m_authz.assert_not_called()
                m_cbt.assert_not_called()

        _run(run())
        reply = self._sent_text(upd)
        self.assertNotIn("STR-SENTINEL-MARKER", reply)
        self.assertNotIn("REPR-SENTINEL-MARKER", reply)
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_user_id_positive_int_accepted(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(777)
        mock_create.assert_called_once()

    def test_user_id_created_by_exact_string(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(777)
        self.assertEqual(mock_create.call_args[1]["created_by"], "777")

    def test_user_id_large_positive_int_accepted(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id(9999999999)
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["created_by"], "9999999999")

    def test_user_id_rejected_authorization_never_called(self):
        # user_id is validated before authorization (§6) — malformed
        # actor state must never spend an authorization call.
        (mock_create, mock_authz, call_log), upd = self._run_with_user_id(-5)
        mock_authz.assert_not_called()
        mock_create.assert_not_called()

    def test_user_id_rejected_exactly_one_reply(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id("bad")
        self.assertEqual(upd.message.reply_text.call_count, 1)

    def test_user_id_rejected_no_raw_value_in_reply(self):
        (mock_create, mock_authz, _), upd = self._run_with_user_id("SENTINEL-USER-VALUE")
        self.assertNotIn("SENTINEL-USER-VALUE", self._sent_text(upd))

    # ── transport update_id is not a business-operation key (A3-A1) ──

    def test_malformed_update_id_ignored_when_explicit_key_present(self):
        """update_id may be absent/malformed; explicit key still creates."""
        for bad_update_id in (None, "555", 0, -1, True, 1.5, [], {}, object()):
            with self.subTest(update_id=repr(bad_update_id)):
                upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
                upd.update_id = bad_update_id
                mock_create, mock_authz, _ = self._run_handler(upd, args=list(self._ARGS))
                mock_create.assert_called_once()
                self.assertEqual(mock_create.call_args[1]["idempotency_key"], "op:test")
                mock_authz.assert_awaited_once()

    def test_missing_update_id_attribute_ignored_when_explicit_key_present(self):
        upd = MagicMock(spec=["message", "effective_user", "effective_chat"])
        upd.message.reply_text = AsyncMock()
        upd.effective_user = SimpleNamespace(id=999)
        upd.effective_chat = SimpleNamespace(type="private")
        mock_create, mock_authz, _ = self._run_handler(upd, args=list(self._ARGS))
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "op:test")

    def test_poisoned_update_id_ignored_when_explicit_key_present(self):
        upd, _ = _make_update('/newbctask business_id=BIZ-001 title="X"', list(self._ARGS))
        upd.update_id = _PoisonedIdentity()
        mock_create, mock_authz, _ = self._run_handler(upd, args=list(self._ARGS))
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args[1]["idempotency_key"], "op:test")
        self.assertNotIn("STR-SENTINEL-MARKER", self._sent_text(upd))


class TestTaskCreationMessageMapping(unittest.TestCase):
    """Result-code-mapping tests for _task_creation_message, moved out
    of TestNewBcTaskCommand — this layer is now the correct place to
    verify create_business_task result rendering, since newbctask_cmd
    itself no longer calls create_business_task."""

    def test_created(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
            "business_id": "BIZ-001", "final_status": "new", "error": None,
            "idempotency_key": "op:abc",
        })
        self.assertIn("✅", msg)
        self.assertIn("TSK-001", msg)
        self.assertIn("Idempotency Key:", msg)
        self.assertIn("op:abc", msg)

    def test_reused(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": True, "code": "TASK_REUSED", "task_id": "TSK-050",
            "business_id": "BIZ-001", "final_status": "ready", "error": None,
            "idempotency_key": "op:abc",
        })
        self.assertNotIn("✅", msg)
        self.assertIn("ℹ️", msg)
        self.assertIn("TSK-050", msg)
        self.assertIn("переиспользован", msg)
        self.assertIn("Idempotency Key:", msg)
        self.assertIn("op:abc", msg)

    def test_created_key_bounded_to_field_max(self):
        th = _fresh_th()
        long_key = "K" * 128
        msg = th._task_creation_message({
            "ok": True, "code": "TASK_CREATED", "task_id": "TSK-001",
            "business_id": "BIZ-001", "final_status": "new", "error": None,
            "idempotency_key": long_key,
        })
        self.assertIn("…", msg)
        self.assertNotIn(long_key, msg)
        self.assertIn("K" * 64 + "…", msg)

    def test_business_not_found(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": False, "code": "BUSINESS_NOT_FOUND", "business_id": "BIZ-999", "error": "not found",
        })
        self.assertIn("❌", msg)
        self.assertIn("BIZ-999", msg)

    def test_roadmap_completed(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "ROADMAP_COMPLETED", "error": "done"})
        self.assertIn("❌", msg)
        self.assertIn("завершён", msg.lower())

    def test_roadmap_cancelled(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "ROADMAP_CANCELLED", "error": "x"})
        self.assertIn("❌", msg)
        self.assertIn("отменён", msg.lower())

    def test_stage_terminal(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "STAGE_TERMINAL", "error": "x"})
        self.assertIn("❌", msg)

    def test_relation_mismatch(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": False, "code": "TASK_ENTITY_RELATION_MISMATCH", "error": "mismatch detail",
        })
        self.assertIn("❌", msg)

    def test_multiple_idempotency_conflict(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": False, "code": "MULTIPLE_TASK_IDEMPOTENCY_MATCHES",
            "conflicting_task_ids": ("TSK-A", "TSK-B"), "error": "x",
        })
        self.assertIn("⚠️", msg)
        self.assertIn("TSK-A", msg)
        self.assertIn("TSK-B", msg)

    def test_storage_error(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "TASK_STORAGE_ERROR", "error": None})
        self.assertIn("❌", msg)
        self.assertNotIn("None", msg)

    def test_unknown_code_fallback_does_not_leak_code_or_error(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "SOMETHING_NEW", "error": "detail"})
        self.assertIn("❌", msg)
        self.assertNotIn("SOMETHING_NEW", msg)
        self.assertNotIn("detail", msg)

    def test_idempotency_check_unavailable(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "IDEMPOTENCY_CHECK_UNAVAILABLE", "error": None})
        self.assertIn("❌", msg)
        self.assertIn("Попробуйте ещё раз позже", msg)
        self.assertNotIn("None", msg)

    def test_task_id_allocation_error(self):
        th = _fresh_th()
        msg = th._task_creation_message({"ok": False, "code": "TASK_ID_ALLOCATION_ERROR", "error": None})
        self.assertIn("❌", msg)
        self.assertIn("Попробуйте ещё раз позже", msg)
        self.assertNotIn("None", msg)

    def test_write_outcome_unknown_does_not_invite_immediate_retry(self):
        # Phase 18A.9-A1 §8: must say "check the list first", must
        # never say "Попробуйте ещё раз позже" for this specific code.
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": False, "code": "TASK_WRITE_OUTCOME_UNKNOWN", "task_id": "TSK-050", "error": None,
        })
        self.assertIn("❌", msg)
        self.assertIn("проверьте список Tasks", msg)
        self.assertNotIn("Попробуйте ещё раз позже", msg)

    def test_duplicate_detected_bounds_conflicting_ids(self):
        th = _fresh_th()
        many_ids = [f"TSK-{i:03d}" for i in range(30)]
        msg = th._task_creation_message({
            "ok": False, "code": "TASK_DUPLICATE_DETECTED",
            "conflicting_task_ids": tuple(many_ids), "error": None,
        })
        self.assertIn("⚠️", msg)
        self.assertIn("TSK-000", msg)
        # Bounded to max_ids=10 -- later IDs must not appear.
        self.assertNotIn("TSK-029", msg)
        self.assertLess(len(msg), 4000)

    def test_duplicate_detected_no_immediate_retry_wording(self):
        th = _fresh_th()
        msg = th._task_creation_message({
            "ok": False, "code": "TASK_DUPLICATE_DETECTED",
            "conflicting_task_ids": ("TSK-A", "TSK-B"), "error": None,
        })
        self.assertNotIn("Попробуйте ещё раз позже", msg)
        self.assertIn("проверьте список Tasks", msg)


class TestTaskDetailLinesIdempotencyKey(unittest.TestCase):
    """Phase 18A.9-A3-A1: /bctask detail surfaces recoverable operation key."""

    def test_nonblank_key_rendered_bounded(self):
        th = _fresh_th()
        task = {
            "task_id": "TSK-001", "business_id": "BIZ-001", "title": "X",
            "status": "new", "idempotency_key": "op:recover-me",
        }
        text = "\n".join(th._task_detail_lines(task))
        self.assertIn("Idempotency Key:", text)
        self.assertIn("op:recover-me", text)

    def test_blank_legacy_key_omitted(self):
        th = _fresh_th()
        task = {
            "task_id": "TSK-001", "business_id": "BIZ-001", "title": "X",
            "status": "new", "idempotency_key": "",
        }
        text = "\n".join(th._task_detail_lines(task))
        self.assertNotIn("Idempotency Key:", text)

    def test_missing_key_field_omitted(self):
        th = _fresh_th()
        task = {
            "task_id": "TSK-001", "business_id": "BIZ-001", "title": "X",
            "status": "new",
        }
        text = "\n".join(th._task_detail_lines(task))
        self.assertNotIn("Idempotency Key:", text)

    def test_long_key_clipped_to_64(self):
        th = _fresh_th()
        long_key = "K" * 128
        task = {
            "task_id": "TSK-001", "business_id": "BIZ-001", "title": "X",
            "status": "new", "idempotency_key": long_key,
        }
        text = "\n".join(th._task_detail_lines(task))
        self.assertIn("K" * 64 + "…", text)
        self.assertNotIn(long_key, text)


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
            ("bctasks_cmd", ("task_manager.list_tasks",), "/bctasks", []),
            ("updatetask_cmd", ("transition_task_status",), "/updatetask task_id=TSK-001 status=ready", ["task_id=TSK-001", "status=ready"]),
            ("assigntask_cmd", ("assign_task",), "/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            ("reassigntask_cmd", ("assign_task",), "/reassigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            # unassigntask_cmd, bctask_cmd and newbctask_cmd are all
            # authorized, secure-flow commands (canonical lookup and/or
            # authorization sit ahead of any mutation/formatting) —
            # their own raw-exception-secrecy coverage lives in
            # TestUnassignTaskCommand, TestBcTaskCommand and
            # TestNewBcTaskCommand instead, with the finder/
            # authorization properly mocked.
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
