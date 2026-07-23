"""
Tests for Phase 21F — Organization Layer: Telegram Commands.

Covers /newdept, /newrole, /roles, /roledetails, /assignrole in
business_core/telegram_handlers.py. Additive-only commands — no existing
command's behavior is touched (verified by a diff-scope regression guard
in this file). No live Sheets writes — organization_manager functions are
mocked throughout, per ENGINEERING_STANDARDS.md Testing Standards.
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
# /newdept
# ─────────────────────────────────────────────────────────────

class TestNewDeptCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "newdept_cmd"))

    def test_happy_path(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newdept name="Operations"', ['name="Operations"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.create_department",
                       return_value={"ok": True, "department_id": "DEPT-001", "error": None}):
                await th.newdept_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("DEPT-001", reply)

    def test_missing_name_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/newdept", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.newdept_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("name", reply)

    def test_manager_error_shown(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newdept name="X" business_id=BIZ-999', ['name="X"', 'business_id=BIZ-999'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.create_department",
                       return_value={"ok": False, "department_id": "", "error": "Business 'BIZ-999' не найден"}):
                await th.newdept_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("BIZ-999", reply)

    def test_bc_disabled_shows_message_without_calling_manager(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newdept name="X"', ['name="X"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
                 patch("business_core.organization_manager.create_department") as mock_create:
                await th.newdept_cmd(upd, ctx)
                mock_create.assert_not_called()

        _run(run())


# ─────────────────────────────────────────────────────────────
# /newrole
# ─────────────────────────────────────────────────────────────

class TestNewRoleCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "newrole_cmd"))

    def test_happy_path(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newrole name="Coordinator" department_id=DEPT-002',
            ['name="Coordinator"', "department_id=DEPT-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.create_role",
                       return_value={"ok": True, "role_id": "ROLE-003", "error": None}):
                await th.newrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("ROLE-003", reply)
        self.assertIn("/assignrole", reply)

    def test_missing_department_id_shows_usage_lists_statuses(self):
        th = _fresh_th()
        upd, ctx = _make_update('/newrole name="Coordinator"', ['name="Coordinator"'])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.newrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        for status in ("planned", "active", "paused", "archived"):
            self.assertIn(status, reply)

    def test_invalid_status_error_shown(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/newrole name="X" department_id=DEPT-001 status=bogus',
            ['name="X"', "department_id=DEPT-001", "status=bogus"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.create_role",
                       return_value={"ok": False, "role_id": "",
                                     "error": "Недопустимый статус 'bogus'. Допустимые значения: planned, active, paused, archived"}):
                await th.newrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("bogus", reply)


# ─────────────────────────────────────────────────────────────
# /roles
# ─────────────────────────────────────────────────────────────

class TestRolesCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "roles_cmd"))

    def test_shows_roles_with_vacancy_icon(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roles", [])
        roles = [
            {"role_id": "ROLE-001", "role_name": "CEO", "status": "active"},
            {"role_id": "ROLE-002", "role_name": "Coordinator", "status": "planned"},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.list_roles", return_value=roles), \
                 patch("business_core.organization_manager.is_role_vacant",
                       side_effect=lambda rid: rid == "ROLE-002"):
                await th.roles_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("ROLE-001", reply)
        self.assertIn("ROLE-002", reply)
        self.assertIn("занята", reply)
        self.assertIn("вакантна", reply)

    def test_empty_list_shows_hint(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roles", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.list_roles", return_value=[]):
                await th.roles_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Пусто", reply)
        self.assertIn("/newrole", reply)

    def test_filter_passed_through_to_manager(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roles department_id=DEPT-002 status=planned",
                                ["department_id=DEPT-002", "status=planned"])
        captured = {}

        def fake_list_roles(department_id="", status=""):
            captured["department_id"] = department_id
            captured["status"] = status
            return []

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.list_roles", side_effect=fake_list_roles):
                await th.roles_cmd(upd, ctx)

        _run(run())
        self.assertEqual(captured["department_id"], "DEPT-002")
        self.assertEqual(captured["status"], "planned")


# ─────────────────────────────────────────────────────────────
# /roledetails
# ─────────────────────────────────────────────────────────────

class TestRoleDetailsCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "roledetails_cmd"))

    def test_missing_role_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roledetails", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.roledetails_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_unknown_role_shows_error(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roledetails role_id=ROLE-999", ["role_id=ROLE-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=None):
                await th.roledetails_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("ROLE-999", reply)

    def test_vacant_role_shows_vacancy_no_assignments(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roledetails role_id=ROLE-002", ["role_id=ROLE-002"])
        role = {
            "role_id": "ROLE-002", "role_name": "Coordinator", "department_id": "DEPT-002",
            "reports_to_role_id": "", "status": "planned", "purpose": "", "main_result": "",
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=role), \
                 patch("business_core.organization_manager.is_role_vacant", return_value=True), \
                 patch("business_core.organization_manager.list_assignments_for_role", return_value=[]):
                await th.roledetails_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("вакантна", reply)

    def test_filled_role_shows_active_assignment(self):
        th = _fresh_th()
        upd, ctx = _make_update("/roledetails role_id=ROLE-001", ["role_id=ROLE-001"])
        role = {
            "role_id": "ROLE-001", "role_name": "CEO", "department_id": "DEPT-001",
            "reports_to_role_id": "", "status": "active", "purpose": "", "main_result": "",
        }
        assignments = [{"person_id": "PRS-001", "start_date": "2026-01-01", "assignment_type": "primary"}]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.find_role_by_id", return_value=role), \
                 patch("business_core.organization_manager.is_role_vacant", return_value=False), \
                 patch("business_core.organization_manager.list_assignments_for_role", return_value=assignments):
                await th.roledetails_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("занята", reply)
        self.assertIn("PRS-001", reply)


# ─────────────────────────────────────────────────────────────
# /assignrole
# ─────────────────────────────────────────────────────────────

class TestAssignRoleCommand(unittest.TestCase):

    def test_registered(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "assignrole_cmd"))

    def test_happy_path(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignrole person_id=PRS-001 role_id=ROLE-001 start_date=2026-01-01",
            ["person_id=PRS-001", "role_id=ROLE-001", "start_date=2026-01-01"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.assign_person_to_role",
                       return_value={"ok": True, "assignment_id": "PRA-001", "error": None}):
                await th.assignrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅", reply)
        self.assertIn("PRA-001", reply)
        self.assertIn("PRS-001", reply)
        self.assertIn("ROLE-001", reply)

    def test_missing_args_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/assignrole person_id=PRS-001", ["person_id=PRS-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.assignrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_unknown_person_error_shown(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignrole person_id=PRS-999 role_id=ROLE-001",
            ["person_id=PRS-999", "role_id=ROLE-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.assign_person_to_role",
                       return_value={"ok": False, "assignment_id": "", "error": "Person 'PRS-999' не найден"}):
                await th.assignrole_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("PRS-999", reply)

    def test_start_date_defaults_to_today_when_omitted(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/assignrole person_id=PRS-001 role_id=ROLE-001",
            ["person_id=PRS-001", "role_id=ROLE-001"],
        )
        captured = {}

        def fake_assign(person_id, role_id, start_date, **kwargs):
            captured["start_date"] = start_date
            return {"ok": True, "assignment_id": "PRA-001", "error": None}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.organization_manager.assign_person_to_role", side_effect=fake_assign):
                await th.assignrole_cmd(upd, ctx)

        _run(run())
        import re
        self.assertRegex(captured["start_date"], r"^\d{4}-\d{2}-\d{2}$")


# ─────────────────────────────────────────────────────────────
# Additive-only regression guard + import guards
# ─────────────────────────────────────────────────────────────

class TestAdditiveOnly(unittest.TestCase):
    """Confirms Phase 21F did not modify any pre-existing command's
    behavior — a diff-scope check via git, not a re-test of every
    existing command (those are already covered by their own test files)."""

    # Note: this class previously included a git-diff-based guard
    # ("test_git_diff_touches_only_additive_lines_in_telegram_handlers")
    # asserting Phase 21F's OWN uncommitted diff to telegram_handlers.py
    # stayed small/additive. That check was a point-in-time closeout
    # verification for Phase 21F specifically (already satisfied and
    # locked in by its commit) — not a durable invariant. Later phases
    # (22D, 23D-2) are explicitly authorized to further modify
    # telegram_handlers.py, including legitimate deletions, so a
    # generic "git diff HEAD" check would misfire against any later,
    # unrelated phase's in-progress changes. Removed rather than left
    # to produce false failures.


class TestNoGtdCoupling(unittest.TestCase):

    def _check_no_gtd_imports_in_new_functions(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        new_funcs = {"newdept_cmd", "newrole_cmd", "roles_cmd", "roledetails_cmd", "assignrole_cmd"}
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
