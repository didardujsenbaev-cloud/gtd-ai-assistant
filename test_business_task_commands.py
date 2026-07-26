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
    update.effective_user.id = 999
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

class TestBcTasksCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "bctasks_cmd"))

    def test_empty(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctasks", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.list_tasks", return_value=[]):
                await th.bctasks_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Пусто", reply)

    def test_list_with_one(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctasks", [])
        task = {"task_id": "TSK-001", "title": "Prepare docs", "status": "ready", "due_date": "2026-08-01"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.list_tasks", return_value=[task]):
                await th.bctasks_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("TSK-001", reply)
        self.assertIn("Prepare docs", reply)

    def test_filters_passed_exactly(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/bctasks business_id=BIZ-001 status=ready roadmap_id=RM-001 stage_id=STAGE-001 role_id=ROLE-001 person_id=PRS-001",
            ["business_id=BIZ-001", "status=ready", "roadmap_id=RM-001", "stage_id=STAGE-001", "role_id=ROLE-001", "person_id=PRS-001"],
        )
        calls = {}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.list_tasks", return_value=[]) as mock_list:
                await th.bctasks_cmd(upd, ctx)
                calls["call_args"] = mock_list.call_args

        _run(run())
        self.assertEqual(
            calls["call_args"].kwargs,
            dict(business_id="BIZ-001", status="ready", roadmap_id="RM-001",
                 stage_id="STAGE-001", role_id="ROLE-001", person_id="PRS-001"),
        )

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


class TestBcTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "bctask_cmd"))

    def test_missing_task_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_not_found(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-999", ["task_id=TSK-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=None):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("TSK-999", reply)

    def test_found_unassigned(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        task = dict(TASK_DICT, responsible_role_id="", assignee_person_id="")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=task), \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent",
                       return_value={"ok": True, "consistent": True, "error": None}), \
                 patch("business_core.task_manager.get_current_task_assignment", return_value=None):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("TSK-001", reply)
        self.assertIn("—", reply)  # unassigned placeholder somewhere

    def test_found_with_consistent_assignment(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=dict(TASK_DICT)), \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent",
                       return_value={"ok": True, "consistent": True, "error": None}), \
                 patch("business_core.task_manager.get_current_task_assignment", return_value=current):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("TAS-050", reply)
        self.assertIn("согласован", reply.lower())

    def test_cache_mismatch_displayed(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=dict(TASK_DICT)), \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent",
                       return_value={"ok": True, "consistent": False, "error": None}), \
                 patch("business_core.task_manager.get_current_task_assignment", return_value=None):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("РАССОГЛАСОВАН", reply)

    def test_multiple_active_conflict_no_current_shown(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=dict(TASK_DICT)), \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent",
                       return_value={"ok": True, "consistent": False, "error": "multiple active Task Assignments"}), \
                 patch("business_core.task_manager.get_current_task_assignment", return_value=None):
                await th.bctask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("РАССОГЛАСОВАН", reply)
        self.assertNotIn("Active Assignment ID", reply)

    def test_description_not_logged(self):
        th = _fresh_th()
        upd, ctx = _make_update("/bctask task_id=TSK-001", ["task_id=TSK-001"])
        captured_calls = []

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.task_manager.find_task_by_id", return_value=dict(TASK_DICT)), \
                 patch("business_core.business_builder.task_assignment_cache_is_consistent",
                       return_value={"ok": True, "consistent": True, "error": None}), \
                 patch("business_core.task_manager.get_current_task_assignment", return_value=None), \
                 patch("business_core.telegram_handlers.log") as mock_log:
                await th.bctask_cmd(upd, ctx)
                captured_calls.extend(mock_log.method_calls)

        _run(run())
        for call in captured_calls:
            for arg in call.args:
                self.assertNotIn("secret notes", str(arg))


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


class TestUnassignTaskCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "unassigntask_cmd"))

    def test_unassigned(self):
        th = _fresh_th()
        upd, ctx = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.unassign_task",
                       return_value={"ok": True, "code": "TASK_UNASSIGNED", "error": None}):
                await th.unassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_zero_active_no_op(self):
        th = _fresh_th()
        upd, ctx = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.unassign_task",
                       return_value={"ok": True, "code": "TASK_UNASSIGNED", "error": None}):
                await th.unassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)

    def test_multiple_active_conflict(self):
        th = _fresh_th()
        upd, ctx = _make_update("/unassigntask task_id=TSK-001", ["task_id=TSK-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.unassign_task",
                       return_value={"ok": False, "code": "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
                                     "conflicting_assignment_ids": ("TAS-A", "TAS-B"), "error": "x"}):
                await th.unassigntask_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)

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
            ("bctask_cmd", ("task_manager.find_task_by_id",), "/bctask task_id=TSK-001", ["task_id=TSK-001"]),
            ("updatetask_cmd", ("transition_task_status",), "/updatetask task_id=TSK-001 status=ready", ["task_id=TSK-001", "status=ready"]),
            ("assigntask_cmd", ("assign_task",), "/assigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            ("reassigntask_cmd", ("assign_task",), "/reassigntask task_id=TSK-001 role_id=ROLE-001", ["task_id=TSK-001", "role_id=ROLE-001"]),
            ("unassigntask_cmd", ("unassign_task",), "/unassigntask task_id=TSK-001", ["task_id=TSK-001"]),
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
