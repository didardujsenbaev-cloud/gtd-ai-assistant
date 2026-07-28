"""
Dependencies Foundation Telegram caller UX (2026-07-28 UX-fix):
/linkdependency, /dependencies (template + live-stage views), and the
Dependency Gate's 3 transition-failure messages
(business_core/telegram_handlers.py).

Root-cause covered by this file: /linkdependency's DEPENDENCY_CREATED/
DEPENDENCY_ALREADY_EXISTS/DEPENDENCY_REACTIVATED replies rendered
"Тип: finish_to_start" under the default parse_mode="Markdown" — legacy
Telegram Markdown parses an even count of "_" as an italic delimiter
pair, silently consuming both underscores around "to" (no parse error,
so _reply()'s own except-fallback to parse_mode=None never fires),
producing "finishtostart". Fixed by sending those three replies with
parse_mode=None (point fix, mirroring dependencies_cmd()'s own existing
parse_mode=None convention) — no business logic, schema, gate, or
transition-flow change.

No live Sheets writes, no live Telegram calls — mocks only.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


class _BaseCase(unittest.TestCase):
    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]

    def _update(self, args_str: str = ""):
        update = MagicMock()
        context = MagicMock()
        context.args = args_str.split() if args_str else []
        update.message.reply_text = AsyncMock()
        update.effective_chat.id = 123
        update.effective_user = MagicMock(id=555)
        return update, context

    def _msg(self, update):
        return update.message.reply_text.call_args[0][0]

    def _parse_mode(self, update):
        return update.message.reply_text.call_args.kwargs.get("parse_mode", "unset")


# ═══════════════════════════════════════════════════════════════
# A. /linkdependency
# ═══════════════════════════════════════════════════════════════

class TestLinkDependencyCmd(_BaseCase):
    def test_created_shows_literal_finish_to_start(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034 blocking=true")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_CREATED", "error": None,
                                     "dependency_id": "TDEP-001", "created": True, "reused": False, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("TSTG-035", msg)
        self.assertIn("TSTG-034", msg)
        self.assertIn("finish_to_start", msg)
        self.assertIn("Blocking: true", msg)
        self.assertNotIn("finishtostart", msg)
        self.assertEqual(self._parse_mode(update), None)

    def test_created_blocking_false(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034 blocking=false")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_CREATED", "error": None,
                                     "dependency_id": "TDEP-002", "created": True, "reused": False, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("Blocking: false", msg)
        self.assertIn("finish_to_start", msg)
        self.assertNotIn("finishtostart", msg)

    def test_already_exists_informational_message(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_ALREADY_EXISTS", "error": None,
                                     "dependency_id": "TDEP-001", "created": False, "reused": True, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("уже существует", msg)
        self.assertIn("TSTG-035", msg)
        self.assertIn("TSTG-034", msg)
        self.assertIn("finish_to_start", msg)
        self.assertNotIn("finishtostart", msg)
        self.assertEqual(self._parse_mode(update), None)

    def test_reactivated_shows_literal_finish_to_start(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_REACTIVATED", "error": None,
                                     "dependency_id": "TDEP-001", "created": False, "reused": True, "reactivated": True}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("реактивирована", msg)
        self.assertIn("TSTG-035", msg)
        self.assertIn("TSTG-034", msg)
        self.assertIn("finish_to_start", msg)
        self.assertNotIn("finishtostart", msg)
        self.assertEqual(self._parse_mode(update), None)

    def test_missing_args_usage_message(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("❌", msg)
        self.assertIn("linkdependency", msg)

    def test_error_result_shows_error_text(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-035")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": False, "code": "SELF_DEPENDENCY_REJECTED",
                                     "error": "Этап не может зависеть сам от себя",
                                     "dependency_id": "", "created": False, "reused": False, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("❌", msg)
        self.assertIn("зависеть сам от себя", msg)


# ═══════════════════════════════════════════════════════════════
# B/C. /dependencies (template + live-stage views)
# ═══════════════════════════════════════════════════════════════

class TestDependenciesCmdTemplateView(_BaseCase):
    def test_template_view_shows_all_fields(self):
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("template_stage_id=TSTG-035")
        rows = ({
            "Dependency ID": "TDEP-001", "Roadmap Template ID": "RMT-IZH-ALM-STANDARD-002",
            "Template Stage ID": "TSTG-035", "Depends On Template Stage ID": "TSTG-034",
            "Dependency Type": "finish_to_start", "Blocking": "true", "Status": "active",
            "Created At": "2026-07-28", "Updated At": "2026-07-28", "Notes": "",
        },)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.list_dependencies_for_template_stage",
                       return_value=rows):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("TSTG-034", msg)
        self.assertIn("finish_to_start", msg)
        self.assertNotIn("finishtostart", msg)
        self.assertIn("Blocking: true", msg)
        self.assertIn("Status: active", msg)
        self.assertEqual(self._parse_mode(update), None)

    def test_template_view_no_dependencies(self):
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("template_stage_id=TSTG-999")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.list_dependencies_for_template_stage",
                       return_value=()):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("нет активных зависимостей", msg)


class TestDependenciesCmdLiveView(_BaseCase):
    def test_live_view_shows_prerequisite_details(self):
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("stage_id=STAGE-019")
        resolution = {
            "ok": True, "code": "DEPENDENCIES_RESOLVED", "error": None,
            "stage_id": "STAGE-019", "roadmap_id": "RM-003",
            "roadmap_template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-035",
            "dependencies": (), "resolved": ({
                "dependency_id": "TDEP-001", "template_stage_id": "TSTG-035",
                "depends_on_template_stage_id": "TSTG-034", "dependency_type": "finish_to_start",
                "blocking": True, "prerequisite_stage_id": "STAGE-018",
                "prerequisite_stage_name": "Получение АПЗ", "prerequisite_status": "done",
                "satisfied": True,
            },),
            "missing_live_stages": (), "configuration_errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.resolve_live_stage_dependencies",
                       return_value=resolution):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("STAGE-018", msg)
        self.assertIn("Получение АПЗ", msg)
        self.assertIn("done", msg)
        self.assertIn("выполнено", msg)
        self.assertIn("blocking=true", msg)
        self.assertEqual(self._parse_mode(update), None)

    def test_live_view_unsatisfied_shows_not_done(self):
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("stage_id=STAGE-019")
        resolution = {
            "ok": True, "code": "DEPENDENCIES_RESOLVED", "error": None,
            "stage_id": "STAGE-019", "roadmap_id": "RM-003",
            "roadmap_template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-035",
            "dependencies": (), "resolved": ({
                "dependency_id": "TDEP-001", "template_stage_id": "TSTG-035",
                "depends_on_template_stage_id": "TSTG-034", "dependency_type": "finish_to_start",
                "blocking": True, "prerequisite_stage_id": "STAGE-018",
                "prerequisite_stage_name": "Получение АПЗ", "prerequisite_status": "in_progress",
                "satisfied": False,
            },),
            "missing_live_stages": (), "configuration_errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.resolve_live_stage_dependencies",
                       return_value=resolution):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("не выполнено", msg)
        self.assertIn("in_progress", msg)

    def test_live_view_no_dependencies(self):
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("stage_id=STAGE-018")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.resolve_live_stage_dependencies",
                       return_value={"ok": True, "code": "NO_STAGE_DEPENDENCIES", "error": None,
                                     "stage_id": "STAGE-018", "roadmap_id": "RM-003",
                                     "roadmap_template_id": "RMT-X", "template_stage_id": "TSTG-034",
                                     "dependencies": (), "resolved": (),
                                     "missing_live_stages": (), "configuration_errors": ()}):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("нет активных зависимостей", msg)


# ═══════════════════════════════════════════════════════════════
# D. transition_stage_status() Dependency Gate failure messages
# ═══════════════════════════════════════════════════════════════

class TestDependencyGateFailureMessages(_BaseCase):
    def test_stage_dependencies_not_satisfied(self):
        self._setup()
        from business_core.telegram_handlers import _stage_transition_failure_message
        result = {
            "code": "STAGE_DEPENDENCIES_NOT_SATISFIED",
            "unsatisfied_dependencies": ({
                "dependency_id": "TDEP-001", "prerequisite_stage_id": "STAGE-018",
                "prerequisite_stage_name": "Получение АПЗ", "prerequisite_status": "in_progress",
            },),
        }
        msg = _stage_transition_failure_message(result, "STAGE-019", "in_progress")
        self.assertTrue(msg.startswith("⛔ Этап нельзя начать"))
        self.assertIn("STAGE-018", msg)
        self.assertIn("in_progress", msg)
        self.assertIn("/dependencies stage_id=STAGE-019", msg)
        self.assertNotIn("TDEP-001", msg)

    def test_prerequisite_live_stage_not_found_safe_message(self):
        self._setup()
        from business_core.telegram_handlers import _stage_transition_failure_message
        result = {"code": "PREREQUISITE_LIVE_STAGE_NOT_FOUND",
                  "missing_live_dependency_stages": (("TDEP-001", "TSTG-034"),)}
        msg = _stage_transition_failure_message(result, "STAGE-019", "in_progress")
        self.assertIn("администратора", msg)
        self.assertNotIn("Traceback", msg)
        self.assertNotIn("Exception", msg)

    def test_dependency_configuration_error_safe_message(self):
        self._setup()
        from business_core.telegram_handlers import _stage_transition_failure_message
        result = {"code": "DEPENDENCY_CONFIGURATION_ERROR",
                  "dependency_configuration_errors": ((None, "cycle detected"),)}
        msg = _stage_transition_failure_message(result, "STAGE-019", "in_progress")
        self.assertIn("администратора", msg)
        self.assertNotIn("Traceback", msg)
        self.assertNotIn("cycle detected", msg)
        self.assertNotIn("project_number", msg)


# ═══════════════════════════════════════════════════════════════
# E. Markdown safety
# ═══════════════════════════════════════════════════════════════

class TestMarkdownSafety(_BaseCase):
    def test_finish_to_start_no_telegram_parse_error(self):
        """Simulates Telegram's own legacy-Markdown italic-pairing bug by
        asserting the fix's parse_mode=None makes the underscore count
        irrelevant — no reliance on Telegram's parser behavior itself."""
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_CREATED", "error": None,
                                     "dependency_id": "TDEP-001", "created": True, "reused": False, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())
        self.assertEqual(self._parse_mode(update), None)

    def test_ids_with_hyphens_render_fully(self):
        self._setup()
        from business_core.telegram_handlers import linkdependency_cmd
        update, context = self._update("template_stage_id=TSTG-035 depends_on=TSTG-034")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.create_template_stage_dependency",
                       return_value={"ok": True, "code": "DEPENDENCY_CREATED", "error": None,
                                     "dependency_id": "TDEP-001", "created": True, "reused": False, "reactivated": False}):
                await linkdependency_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("TSTG-035", msg)
        self.assertIn("TSTG-034", msg)

    def test_prerequisite_title_with_underscore_not_broken(self):
        """A prerequisite Stage name containing an underscore must still
        render literally in the live-stage /dependencies view (already
        parse_mode=None, unaffected by this UX-fix, verified here as a
        regression guard)."""
        self._setup()
        from business_core.telegram_handlers import dependencies_cmd
        update, context = self._update("stage_id=STAGE-019")
        resolution = {
            "ok": True, "code": "DEPENDENCIES_RESOLVED", "error": None,
            "stage_id": "STAGE-019", "roadmap_id": "RM-003",
            "roadmap_template_id": "RMT-X", "template_stage_id": "TSTG-035",
            "dependencies": (), "resolved": ({
                "dependency_id": "TDEP-001", "template_stage_id": "TSTG-035",
                "depends_on_template_stage_id": "TSTG-034", "dependency_type": "finish_to_start",
                "blocking": True, "prerequisite_stage_id": "STAGE-018",
                "prerequisite_stage_name": "Some_Title_With_Underscores",
                "prerequisite_status": "done", "satisfied": True,
            },),
            "missing_live_stages": (), "configuration_errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_dependency_manager.resolve_live_stage_dependencies",
                       return_value=resolution):
                await dependencies_cmd(update, context)
        asyncio.run(run())

        msg = self._msg(update)
        self.assertIn("Some_Title_With_Underscores", msg)


if __name__ == "__main__":
    unittest.main()
