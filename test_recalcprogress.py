"""
Tests for Phase 9D — /recalcprogress: минимальная Telegram-команда,
вызывающая уже существующую recalculate_roadmap_progress() (Phase 9C).

Команда сама ничего не считает — только парсит roadmap_id, вызывает
recalculate_roadmap_progress() и форматирует ответ. Логика расчёта
(DONE_SET, round-half-up, roadmap без этапов) уже покрыта
test_roadmap_progress.py; здесь дополнительно проверяется именно то,
что видно только на уровне команды (Telegram args, формат ответа,
регистрация, что /updatestage не тронут).
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


def _fresh(mod_name: str):
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module(mod_name)


def _fresh_th():
    return _fresh("business_core.telegram_handlers")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_update(text: str, args_list: list[str]):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args_list
    return update, context


def _result(roadmap_id="RM-027", old="0", new=33, done=1, total=3, changed=True, ok=True, error=None):
    return {
        "ok": ok, "error": error, "roadmap_id": roadmap_id,
        "old_progress": old, "new_progress": new,
        "done_count": done, "total_count": total, "changed": changed,
    }


# ────────────────────────────────────────────────────────────
# /recalcprogress — end-to-end
# ────────────────────────────────────────────────────────────

class TestRecalcProgressCommand(unittest.TestCase):

    def test_registered_as_handler_function(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "recalcprogress_cmd"))

    def test_registered_exactly_once(self):
        src = (WORKSPACE / "business_core" / "telegram_handlers.py").read_text(encoding="utf-8")
        count = src.count('CommandHandler("recalcprogress"')
        self.assertEqual(count, 1)

    def test_happy_path_changed_true(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-027",
            ["roadmap_id=RM-027"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_result(old="0", new=33, done=1, total=3, changed=True)):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("RM-027", reply)
        self.assertIn("0%", reply)
        self.assertIn("33%", reply)
        self.assertIn("1", reply)
        self.assertIn("3", reply)
        self.assertIn("✅", reply)

    def test_happy_path_changed_false(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-027",
            ["roadmap_id=RM-027"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_result(old="33", new=33, done=1, total=3, changed=False)):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("ℹ️", reply)
        self.assertIn("RM-027", reply)
        self.assertIn("33%", reply)
        self.assertIn("изменений нет", reply)
        self.assertIn("1", reply)
        self.assertIn("3", reply)
        self.assertNotIn("❌", reply)

    def test_missing_roadmap_id_shows_usage_without_calling_backend(self):
        th = _fresh_th()
        upd, ctx = _make_update("/recalcprogress", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc:
                await th.recalcprogress_cmd(upd, ctx)
                mock_recalc.assert_not_called()

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("roadmap", reply.lower())

    def test_roadmap_not_found_shows_clear_error(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-UNKNOWN",
            ["roadmap_id=RM-UNKNOWN"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_result(ok=False, error="Roadmap 'RM-UNKNOWN' не найден")):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("RM-UNKNOWN", reply)

    def test_roadmap_without_stages_shows_zero_percent(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-002",
            ["roadmap_id=RM-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_result(roadmap_id="RM-002", old="0", new=0,
                                            done=0, total=0, changed=False)):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("0%", reply)
        self.assertIn("0 из 0", reply)

    def test_positional_roadmap_id_works(self):
        th = _fresh_th()
        upd, ctx = _make_update("/recalcprogress RM-027", ["RM-027"])

        captured = {}

        def fake_recalc(roadmap_id):
            captured["roadmap_id"] = roadmap_id
            return _result(roadmap_id=roadmap_id)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       side_effect=fake_recalc):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        self.assertEqual(captured["roadmap_id"], "RM-027")

    def test_bc_disabled_does_not_call_backend(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-027",
            ["roadmap_id=RM-027"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc:
                await th.recalcprogress_cmd(upd, ctx)
                mock_recalc.assert_not_called()

        _run(run())

    def test_reply_shows_done_and_total_count(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-027",
            ["roadmap_id=RM-027"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_result(done=7, total=10, new=70, old="0", changed=True)):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("7", reply)
        self.assertIn("10", reply)
        self.assertIn("70%", reply)


# ────────────────────────────────────────────────────────────
# /updatestage не затронут этим изменением
# ────────────────────────────────────────────────────────────

class TestUpdateStageUntouched(unittest.TestCase):

    def test_updatestage_still_registered_once(self):
        src = (WORKSPACE / "business_core" / "telegram_handlers.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("updatestage"'), 1)

    def test_updatestage_does_not_call_recalculate(self):
        src = (WORKSPACE / "business_core" / "telegram_handlers.py").read_text(encoding="utf-8")
        import re
        match = re.search(
            r"async def updatestage_cmd.*?(?=\nasync def |\Z)", src, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertNotIn("recalculate_roadmap_progress", match.group(0))


# ────────────────────────────────────────────────────────────
# Regression guard — интеграция с реальной recalculate_roadmap_progress
# (Sheets-уровневые проверки уже подробно покрыты в test_roadmap_progress.py;
# здесь — сквозной прогон команда -> функция -> mock Sheets)
# ────────────────────────────────────────────────────────────

ROADMAPS_HEADERS = [
    "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
    "Client Name", "GTD Project ID", "Responsible", "Status",
    "Created", "Expected", "Progress %",
    "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
    "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
    "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
    "Stage 10 Status", "Notes", "Last Updated",
    "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
]


class TestEndToEndWithRealRecalculateFunction(unittest.TestCase):
    """Не мокаем recalculate_roadmap_progress — используем настоящую
    функцию из roadmap_manager с мок-листами, чтобы проверить полную
    цепочку: команда -> recalculate_roadmap_progress -> Sheets."""

    def _make_roadmaps_sheet(self, progress="0", status="active", row_num=2):
        row = [""] * len(ROADMAPS_HEADERS)
        idx = {h: i for i, h in enumerate(ROADMAPS_HEADERS)}
        row[idx["Roadmap ID"]] = "RM-027"
        row[idx["Progress %"]] = progress
        row[idx["Status"]] = status
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = row_num
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: ROADMAPS_HEADERS if r == 1 else row
        return sheet

    def _make_stages_sheet(self, statuses):
        headers = ["Stage ID", "Roadmap ID", "Order", "Name", "Status", "Due Date", "Notes"]
        rows = [headers]
        for i, status in enumerate(statuses, start=1):
            rows.append([f"STAGE-027-{i:02d}", "RM-027", str(i), f"Этап {i}", status, "", ""])
        sheet = MagicMock()
        sheet.get_all_values.return_value = rows
        return sheet

    def _run_command(self, statuses, roadmaps_sheet_kwargs=None):
        th = _fresh_th()
        roadmaps_sheet_kwargs = roadmaps_sheet_kwargs or {}
        roadmaps_sheet = self._make_roadmaps_sheet(**roadmaps_sheet_kwargs)
        stages_sheet = self._make_stages_sheet(statuses)

        def fake_get_business_sheet(key):
            if key == "roadmaps":
                return roadmaps_sheet
            if key == "roadmap_stages":
                return stages_sheet
            raise AssertionError(f"неожиданный лист '{key}'")

        upd, ctx = _make_update("/recalcprogress roadmap_id=RM-027", ["roadmap_id=RM-027"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        return upd, roadmaps_sheet, stages_sheet

    def test_skipped_counts_as_completed(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(["done", "skipped", "pending"])
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("67%", reply)
        self.assertIn("2", reply)
        self.assertIn("3", reply)

    def test_legacy_statuses_not_counted_as_completed(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(
            ["not_started", "waiting", "completed", "done"])
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("25%", reply)
        self.assertIn("1", reply)
        self.assertIn("4", reply)

    def test_writes_only_progress_column_end_to_end(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(["done", "done"])
        self.assertEqual(roadmaps_sheet.update_cell.call_count, 1)
        row_num, col, value = roadmaps_sheet.update_cell.call_args[0]
        self.assertEqual(col, ROADMAPS_HEADERS.index("Progress %") + 1)
        self.assertEqual(value, "100")

    def test_does_not_write_to_roadmap_stages(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(["done", "pending"])
        stages_sheet.update_cell.assert_not_called()
        stages_sheet.update.assert_not_called()
        stages_sheet.append_row.assert_not_called()

    def test_does_not_touch_status_column(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(
            ["done"], roadmaps_sheet_kwargs={"status": "active"})
        written_cols = [c.args[1] for c in roadmaps_sheet.update_cell.call_args_list]
        self.assertNotIn(ROADMAPS_HEADERS.index("Status") + 1, written_cols)

    def test_only_target_row_written_other_roadmaps_unaffected(self):
        upd, roadmaps_sheet, stages_sheet = self._run_command(["done"], roadmaps_sheet_kwargs={"row_num": 30})
        for call in roadmaps_sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 30)
        roadmaps_sheet.find.assert_called_once_with("RM-027", in_column=1)


# ────────────────────────────────────────────────────────────
# GTD Core / .env не затронуты
# ────────────────────────────────────────────────────────────

class TestGTDAndEnvUntouched(unittest.TestCase):

    def _check_no_gtd_imports(self, path: Path):
        if not path.exists():
            return
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN,
                                     f"{path.name} импортирует {a.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN,
                                 f"{path.name} импортирует {node.module!r}")

    def test_telegram_handlers_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "telegram_handlers.py")

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
