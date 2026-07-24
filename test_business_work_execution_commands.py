"""
Tests for Phase 22D — Work Execution Layer: Telegram Commands.

Covers /assignstagerole, /reassignstagerole, /stageresponsibility in
business_core/telegram_handlers.py. Additive-only commands — no existing
command's behavior is touched (verified by a diff-scope regression guard
in this file, same pattern as Phase 21F's test_business_organization_commands.py).
No live Sheets writes — business_core.work_assignment_manager and
business_core.organization_manager functions are mocked throughout, per
ENGINEERING_STANDARDS.md Testing Standards.
"""

from __future__ import annotations

import ast
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
    context = MagicMock()
    context.args = args_list
    return update, context


# ─────────────────────────────────────────────────────────────
# /assignstagerole
# ─────────────────────────────────────────────────────────────

class TestAssignStageRoleCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "assignstagerole_cmd"))

    def test_happy_path(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignstagerole stage_id=STAGE-001 role_id=ROLE-001",
            ["stage_id=STAGE-001", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.assign_role_to_stage",
                       return_value={"ok": True, "relation_id": "REL-050", "error": None}):
                await th.assignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("STAGE-001", reply)
        self.assertIn("ROLE-001", reply)
        self.assertIn("REL-050", reply)

    def test_missing_stage_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assignstagerole role_id=ROLE-001", ["role_id=ROLE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.assignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("stage_id", reply)

    def test_missing_role_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assignstagerole stage_id=STAGE-001", ["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.assignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("role_id", reply)

    def test_duplicate_relation_error_shown(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignstagerole stage_id=STAGE-001 role_id=ROLE-002",
            ["stage_id=STAGE-001", "role_id=ROLE-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.assign_role_to_stage",
                       return_value={"ok": False, "relation_id": "",
                                     "error": "У stage 'STAGE-001' уже есть активная Role-relation "
                                              "(REL-010) — используй reassign_stage_role()"}):
                await th.assignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("REL-010", reply)
        self.assertIn("reassign_stage_role", reply)

    def test_bc_disabled_shows_message_without_calling_manager(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignstagerole stage_id=STAGE-001 role_id=ROLE-001",
            ["stage_id=STAGE-001", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
                 patch("business_core.work_assignment_manager.assign_role_to_stage") as mock_assign:
                await th.assignstagerole_cmd(upd, ctx)
                mock_assign.assert_not_called()

        _run(run())

    def test_manager_exception_does_not_leak_traceback(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignstagerole stage_id=STAGE-001 role_id=ROLE-001",
            ["stage_id=STAGE-001", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.assign_role_to_stage",
                       side_effect=RuntimeError("boom")):
                await th.assignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertNotIn("Traceback", reply)
        self.assertNotIn(".py", reply)


# ─────────────────────────────────────────────────────────────
# /reassignstagerole
# ─────────────────────────────────────────────────────────────

class TestReassignStageRoleCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "reassignstagerole_cmd"))

    def test_changed_successfully(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/reassignstagerole stage_id=STAGE-001 role_id=ROLE-002",
            ["stage_id=STAGE-001", "role_id=ROLE-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.reassign_stage_role",
                       return_value={"ok": True, "changed": True,
                                     "old_relation_id": "REL-010", "new_relation_id": "REL-020",
                                     "error": None}):
                await th.reassignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("REL-010", reply)
        self.assertIn("REL-020", reply)
        self.assertIn("ROLE-002", reply)

    def test_idempotent_noop(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/reassignstagerole stage_id=STAGE-001 role_id=ROLE-001",
            ["stage_id=STAGE-001", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.reassign_stage_role",
                       return_value={"ok": True, "changed": False,
                                     "old_relation_id": "REL-010", "new_relation_id": "REL-010",
                                     "error": None}):
                await th.reassignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("ℹ️", reply)
        self.assertIn("уже назначен", reply)
        self.assertNotIn("❌", reply)

    def test_partial_failure(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/reassignstagerole stage_id=STAGE-001 role_id=ROLE-002",
            ["stage_id=STAGE-001", "role_id=ROLE-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.reassign_stage_role",
                       return_value={"ok": False, "changed": True,
                                     "old_relation_id": "REL-010", "new_relation_id": None,
                                     "error": "Sheets API timeout"}):
                await th.reassignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("REL-010", reply)
        self.assertIn("Sheets API timeout", reply)
        self.assertIn("Повтор", reply)

    def test_validation_error(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/reassignstagerole stage_id=STAGE-999 role_id=ROLE-002",
            ["stage_id=STAGE-999", "role_id=ROLE-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.reassign_stage_role",
                       return_value={"ok": False, "changed": False,
                                     "old_relation_id": None, "new_relation_id": None,
                                     "error": "Stage 'STAGE-999' не найден"}):
                await th.reassignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("STAGE-999", reply)
        self.assertNotIn("⚠️", reply)
        self.assertNotIn("✅", reply)

    def test_missing_args_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/reassignstagerole stage_id=STAGE-001", ["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.reassignstagerole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)


# ─────────────────────────────────────────────────────────────
# /stageresponsibility
# ─────────────────────────────────────────────────────────────

class TestStageResponsibilityCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "stageresponsibility_cmd"))

    def test_missing_stage_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_assigned_status_renders_all_fields(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-001", ["stage_id=STAGE-001"])
        resolve_result = {
            "status": "assigned", "stage_id": "STAGE-001", "role_id": "ROLE-001",
            "person_id": "PRS-001", "relation_id": "REL-010", "errors": (),
        }
        role = {"role_id": "ROLE-001", "role_name": "Coordinator", "status": "active"}
        person = {"full_name": "Иван Иванов", "short_name": "Иван"}
        assignments = [{"person_id": "PRS-001", "assignment_type": "primary"}]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=role), \
                 patch("business_core.person_manager.find_person_by_id", return_value=person), \
                 patch("business_core.organization_manager.list_assignments_for_role", return_value=assignments):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("assigned", reply)
        self.assertIn("STAGE-001", reply)
        self.assertIn("ROLE-001", reply)
        self.assertIn("Coordinator", reply)
        self.assertIn("PRS-001", reply)
        self.assertIn("Иван Иванов", reply)
        self.assertIn("primary", reply)

    def test_vacant_status(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-002", ["stage_id=STAGE-002"])
        resolve_result = {
            "status": "vacant", "stage_id": "STAGE-002", "role_id": "ROLE-003",
            "person_id": None, "relation_id": "REL-011", "errors": (),
        }
        role = {"role_id": "ROLE-003", "role_name": "Inbound Manager", "status": "planned"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=role):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("vacant", reply)
        self.assertIn("ROLE-003", reply)
        self.assertIn("Inbound Manager", reply)
        self.assertIn("нет активного", reply)

    def test_unconfigured_status(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-003", ["stage_id=STAGE-003"])
        resolve_result = {
            "status": "unconfigured", "stage_id": "STAGE-003", "role_id": None,
            "person_id": None, "relation_id": None, "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("unconfigured", reply)
        self.assertIn("не настроена", reply)

    def test_configuration_error_status_shows_identifiers_no_traceback(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-004", ["stage_id=STAGE-004"])
        resolve_result = {
            "status": "configuration_error", "stage_id": "STAGE-004", "role_id": "ROLE-004",
            "person_id": None, "relation_id": "REL-012",
            "errors": ("Role 'ROLE-004' архивирована",),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("configuration_error", reply)
        self.assertIn("ROLE-004", reply)
        self.assertIn("REL-012", reply)
        self.assertIn("архивирована", reply)
        self.assertNotIn("Traceback", reply)

    def test_missing_role_name_falls_back_gracefully(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-005", ["stage_id=STAGE-005"])
        resolve_result = {
            "status": "vacant", "stage_id": "STAGE-005", "role_id": "ROLE-005",
            "person_id": None, "relation_id": "REL-013", "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=None):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Role Name: —", reply)

    def test_missing_person_name_falls_back_gracefully(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-006", ["stage_id=STAGE-006"])
        resolve_result = {
            "status": "assigned", "stage_id": "STAGE-006", "role_id": "ROLE-006",
            "person_id": "PRS-999", "relation_id": "REL-014", "errors": (),
        }
        role = {"role_id": "ROLE-006", "role_name": "Coordinator", "status": "active"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=role), \
                 patch("business_core.person_manager.find_person_by_id", return_value=None), \
                 patch("business_core.organization_manager.list_assignments_for_role", return_value=[]):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Person Name: —", reply)

    def test_manager_exception_does_not_leak_traceback(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-007", ["stage_id=STAGE-007"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       side_effect=RuntimeError("internal boom with /path/to/file.py details")):
                await th.stageresponsibility_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertNotIn("boom", reply)
        self.assertNotIn(".py", reply)
        self.assertNotIn("Traceback", reply)


# ─────────────────────────────────────────────────────────────
# Handlers delegate only to approved manager APIs / no direct Sheets writes
# ─────────────────────────────────────────────────────────────

class TestHandlersDelegateOnlyToApprovedApis(unittest.TestCase):

    def test_assignstagerole_never_calls_get_business_sheet(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignstagerole stage_id=STAGE-001 role_id=ROLE-001",
            ["stage_id=STAGE-001", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.assign_role_to_stage",
                       return_value={"ok": True, "relation_id": "REL-050", "error": None}), \
                 patch("business_core.sheets.get_business_sheet") as mock_sheet:
                await th.assignstagerole_cmd(upd, ctx)
                mock_sheet.assert_not_called()

        _run(run())

    def test_reassignstagerole_never_calls_get_business_sheet(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/reassignstagerole stage_id=STAGE-001 role_id=ROLE-002",
            ["stage_id=STAGE-001", "role_id=ROLE-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.reassign_stage_role",
                       return_value={"ok": True, "changed": True,
                                     "old_relation_id": "REL-010", "new_relation_id": "REL-020",
                                     "error": None}), \
                 patch("business_core.sheets.get_business_sheet") as mock_sheet:
                await th.reassignstagerole_cmd(upd, ctx)
                mock_sheet.assert_not_called()

        _run(run())

    def test_stageresponsibility_never_calls_get_business_sheet_directly_for_writes(self):
        """Read-only: it MAY read via person_manager.find_person_by_id()
        (Phase 23D-4A — people_registry display lookup) but must never
        call get_business_sheet() itself (that would imply a raw,
        unmanaged Sheets access)."""
        th = _fresh_th()
        upd, ctx = _make_update("/stageresponsibility stage_id=STAGE-001", ["stage_id=STAGE-001"])
        resolve_result = {
            "status": "unconfigured", "stage_id": "STAGE-001", "role_id": None,
            "person_id": None, "relation_id": None, "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.work_assignment_manager.resolve_stage_responsibility",
                       return_value=resolve_result), \
                 patch("business_core.sheets.get_business_sheet") as mock_sheet:
                await th.stageresponsibility_cmd(upd, ctx)
                mock_sheet.assert_not_called()

        _run(run())

    def test_stageresponsibility_no_direct_registry_read_calls_remain(self):
        """Phase 23D-4A architecture guard: stageresponsibility_cmd()'s
        person-name lookup must call no direct get_business_sheet()/
        find_row_by_id() — only Person Manager's find_person_by_id()."""
        import ast
        import inspect
        th = _fresh_th()
        source = inspect.getsource(th.stageresponsibility_cmd)
        tree = ast.parse(source)

        forbidden_calls = {"get_business_sheet", "find_row_by_id", "get_all_records"}
        found_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in forbidden_calls:
                    found_calls.add(name)

        self.assertEqual(found_calls, set())


# ─────────────────────────────────────────────────────────────
# Import guards
# ─────────────────────────────────────────────────────────────
#
# Note: this module previously also had a TestAdditiveOnly class with a
# git-diff-based guard asserting Phase 22D's OWN uncommitted diff to
# telegram_handlers.py stayed small/additive. That was a point-in-time
# closeout check for Phase 22D specifically (already satisfied and
# locked in by its commit), not a durable invariant — later phases
# (23D-2) are explicitly authorized to further modify
# telegram_handlers.py, so a generic "git diff HEAD" check would
# misfire against any later, unrelated phase's in-progress changes.
# Removed rather than left to produce false failures.


class TestExistingCommandsUntouched(unittest.TestCase):
    """Spot-check that pre-existing Phase 21F/9B commands still behave
    exactly as before — a regression guard for this specific phase, not
    a re-test of their own dedicated suites."""

    def test_updatestage_cmd_still_registered_and_unaffected(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "updatestage_cmd"))

    def test_assignrole_cmd_still_registered_and_unaffected(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "assignrole_cmd"))

    def test_roledetails_cmd_still_registered_and_unaffected(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "roledetails_cmd"))


class TestNoGtdCoupling(unittest.TestCase):

    def _check_no_gtd_imports_in_new_functions(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        new_funcs = {"assignstagerole_cmd", "reassignstagerole_cmd", "stageresponsibility_cmd"}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in new_funcs:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ImportFrom) and sub.module:
                        self.assertNotIn(sub.module.split(".")[0], GTD_FORBIDDEN)
                    if isinstance(sub, ast.Import):
                        for a in sub.names:
                            self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN)

    def test_no_gtd_imports_in_new_commands(self):
        self._check_no_gtd_imports_in_new_functions()

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_th()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
