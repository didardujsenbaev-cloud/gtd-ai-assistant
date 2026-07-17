"""
Tests for Phase 9B — минимальный /updatestage: единый канонический
словарь статусов этапа (STAGE_STATUS_CANONICAL), find_stage_by_id(),
update_stage_status_in_sheet() и Telegram-команда /updatestage.

Не покрывает (сознательно вне рамок Phase 9B):
- пересчёт Progress %;
- автоматическое завершение Roadmap;
- историю изменений;
- уведомления;
- массовое обновление;
- миграцию legacy-статусов.
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


def _fresh_rm():
    return _fresh("business_core.roadmap_manager")


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


STAGES_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
]

STAGE_ROW = [
    "STAGE-001-01", "RM-001", "1", "Диагностика кейса", "pending",
    "", "", "", "Дидар",
    "Правоустанавливающий документ на землю", "", "Существующая заметка",
    "", "", "", "", "",
]


def _make_stage_sheet(headers=None, row=None, row_num=2):
    headers = headers if headers is not None else STAGES_HEADERS
    row = row if row is not None else STAGE_ROW
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    return sheet


# ────────────────────────────────────────────────────────────
# find_stage_by_id
# ────────────────────────────────────────────────────────────

class TestFindStageById(unittest.TestCase):

    def test_found_reads_by_header_name(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            stage = rm.find_stage_by_id("STAGE-001-01")

        self.assertIsNotNone(stage)
        self.assertEqual(stage["stage_id"], "STAGE-001-01")
        self.assertEqual(stage["roadmap_id"], "RM-001")
        self.assertEqual(stage["status"], "pending")
        self.assertEqual(stage["notes"], "Существующая заметка")
        self.assertEqual(stage["row_num"], 2)

    def test_independent_of_header_order(self):
        """Порядок заголовков в листе может отличаться — чтение всё равно верное."""
        rm = _fresh_rm()
        shuffled_headers = [
            "Notes", "Stage ID", "Status", "Roadmap ID", "Order", "Name",
            "Due Date", "Completed At", "GTD Action ID", "Responsible",
            "Docs Required", "Docs Received",
        ]
        shuffled_row = [
            "Заметка", "STAGE-002-01", "blocked", "RM-002", "3", "АПЗ",
            "", "", "", "Дидар", "", "",
        ]
        sheet = _make_stage_sheet(headers=shuffled_headers, row=shuffled_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            stage = rm.find_stage_by_id("STAGE-002-01")

        self.assertEqual(stage["status"], "blocked")
        self.assertEqual(stage["roadmap_id"], "RM-002")
        self.assertEqual(stage["notes"], "Заметка")

    def test_not_found_returns_none(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(rm.find_stage_by_id("STAGE-UNKNOWN"))

    def test_empty_stage_id_returns_none_without_sheet_call(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(rm.find_stage_by_id(""))
        sheet.find.assert_not_called()

    def test_reads_legacy_status_without_crashing(self):
        """Этап с legacy-статусом (not_started, из /newroadmap) читается
        как есть, без исключения — валидация статуса тут не происходит."""
        rm = _fresh_rm()
        legacy_row = list(STAGE_ROW)
        legacy_row[STAGES_HEADERS.index("Status")] = "not_started"
        sheet = _make_stage_sheet(row=legacy_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            stage = rm.find_stage_by_id("STAGE-001-01")
        self.assertEqual(stage["status"], "not_started")


# ────────────────────────────────────────────────────────────
# STAGE_STATUS_CANONICAL — словарь и изоляция от STAGE_STATUSES
# ────────────────────────────────────────────────────────────

class TestCanonicalStatusConstant(unittest.TestCase):

    def test_canonical_set_is_exactly_the_five_values(self):
        rm = _fresh_rm()
        self.assertEqual(
            set(rm.STAGE_STATUS_CANONICAL),
            {"pending", "in_progress", "blocked", "done", "skipped"},
        )

    def test_legacy_stage_statuses_constant_untouched(self):
        """STAGE_STATUSES (мёртвая in-memory модель) не менялась."""
        rm = _fresh_rm()
        self.assertEqual(
            rm.STAGE_STATUSES,
            ("not_started", "in_progress", "waiting", "blocked", "done"),
        )

    def test_legacy_values_not_in_canonical_set(self):
        rm = _fresh_rm()
        for legacy in ("not_started", "completed", "waiting"):
            self.assertNotIn(legacy, rm.STAGE_STATUS_CANONICAL)


# ────────────────────────────────────────────────────────────
# update_stage_status_in_sheet — валидация статуса
# ────────────────────────────────────────────────────────────

class TestUpdateStageStatusValidation(unittest.TestCase):

    def test_all_five_canonical_statuses_accepted(self):
        rm = _fresh_rm()
        for status in rm.STAGE_STATUS_CANONICAL:
            sheet = _make_stage_sheet()
            with patch("business_core.sheets.get_business_sheet", return_value=sheet):
                result = rm.update_stage_status_in_sheet("STAGE-001-01", status)
            self.assertTrue(result["ok"], f"статус {status} должен приниматься")

    def test_legacy_not_started_rejected(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "not_started")
        self.assertFalse(result["ok"])
        self.assertIn("not_started", result["error"] + str(result))
        sheet.update_cell.assert_not_called()

    def test_legacy_completed_rejected(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "completed")
        self.assertFalse(result["ok"])
        sheet.update_cell.assert_not_called()

    def test_legacy_waiting_rejected(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "waiting")
        self.assertFalse(result["ok"])
        sheet.update_cell.assert_not_called()

    def test_typo_rejected_with_clear_error_listing_canonical_values(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "donee")
        self.assertFalse(result["ok"])
        for status in rm.STAGE_STATUS_CANONICAL:
            self.assertIn(status, result["error"])
        sheet.update_cell.assert_not_called()

    def test_invalid_status_no_lookup_performed(self):
        """Невалидный статус отклоняется до похода в Sheets вообще."""
        rm = _fresh_rm()
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001-01", "bogus")
        sheet.find.assert_not_called()

    def test_unknown_stage_id_returns_clear_error(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-UNKNOWN", "done")
        self.assertFalse(result["ok"])
        self.assertIn("STAGE-UNKNOWN", result["error"])
        sheet.update_cell.assert_not_called()

    def test_empty_stage_id_returns_error(self):
        rm = _fresh_rm()
        with patch("business_core.sheets.get_business_sheet", return_value=MagicMock()):
            result = rm.update_stage_status_in_sheet("", "done")
        self.assertFalse(result["ok"])


# ────────────────────────────────────────────────────────────
# update_stage_status_in_sheet — запись только нужных колонок
# ────────────────────────────────────────────────────────────

class TestUpdateStageStatusWrite(unittest.TestCase):

    def test_writes_only_status_column_without_notes(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        self.assertTrue(result["ok"])
        self.assertEqual(sheet.update_cell.call_count, 1)
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(row_num, 2)
        self.assertEqual(col, STAGES_HEADERS.index("Status") + 1)
        self.assertEqual(value, "done")

    def test_writes_status_and_notes_when_notes_provided(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet(
                "STAGE-001-01", "blocked", notes="Ожидаем документы клиента")

        self.assertTrue(result["ok"])
        self.assertEqual(sheet.update_cell.call_count, 2)
        calls = {call.args[1]: call.args[2] for call in sheet.update_cell.call_args_list}
        self.assertEqual(calls[STAGES_HEADERS.index("Status") + 1], "blocked")
        self.assertEqual(calls[STAGES_HEADERS.index("Notes") + 1], "Ожидаем документы клиента")

    def test_notes_none_does_not_touch_notes_column(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001-01", "in_progress", notes=None)

        written_cols = [call.args[1] for call in sheet.update_cell.call_args_list]
        self.assertNotIn(STAGES_HEADERS.index("Notes") + 1, written_cols)

    def test_does_not_touch_other_columns(self):
        """Order/Name/Due Date/Responsible/Docs Required/знаниевые поля —
        ни разу не участвуют в update_cell."""
        rm = _fresh_rm()
        sheet = _make_stage_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet(
                "STAGE-001-01", "done", notes="готово")

        written_cols = {call.args[1] for call in sheet.update_cell.call_args_list}
        protected = {
            STAGES_HEADERS.index(h) + 1 for h in (
                "Order", "Name", "Due Date", "Completed At", "GTD Action ID",
                "Responsible", "Docs Required", "Docs Received",
                "SOP IDs", "Checklist IDs", "Materials IDs",
                "Document Template IDs", "FAQ IDs",
            )
        }
        self.assertEqual(written_cols & protected, set())

    def test_does_not_touch_other_rows(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet(row_num=57)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        for call in sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 57)

    def test_regression_guard_roadmaps_sheet_never_touched(self):
        """Обновление этапа не должно вызывать get_business_sheet('roadmaps')
        вовсе — ни Progress %, ни Status Roadmap не пересчитываются."""
        rm = _fresh_rm()
        stage_sheet = _make_stage_sheet()
        calls = []

        def fake_get_business_sheet(key):
            calls.append(key)
            if key == "roadmap_stages":
                return stage_sheet
            raise AssertionError(f"update_stage_status_in_sheet не должен трогать лист '{key}'")

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        self.assertTrue(result["ok"])
        self.assertNotIn("roadmaps", calls)


# ────────────────────────────────────────────────────────────
# Идемпотентность
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_setting_same_status_twice_both_succeed(self):
        rm = _fresh_rm()
        row_already_done = list(STAGE_ROW)
        row_already_done[STAGES_HEADERS.index("Status")] = "done"
        sheet = _make_stage_sheet(row=row_already_done)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            first = rm.update_stage_status_in_sheet("STAGE-001-01", "done")
            second = rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])

    def test_repeated_same_status_reports_changed_false(self):
        rm = _fresh_rm()
        row_already_done = list(STAGE_ROW)
        row_already_done[STAGES_HEADERS.index("Status")] = "done"
        sheet = _make_stage_sheet(row=row_already_done)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "done")
        self.assertEqual(result["new_status"], "done")

    def test_actual_change_reports_changed_true(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet()  # status == "pending"
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001-01", "done")

        self.assertTrue(result["changed"])
        self.assertEqual(result["old_status"], "pending")


# ────────────────────────────────────────────────────────────
# /updatestage — end-to-end Telegram
# ────────────────────────────────────────────────────────────

class TestUpdateStageCommand(unittest.TestCase):

    def test_registered_in_command_handlers(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "updatestage_cmd"))

    def test_happy_path_status_only(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001-01 status=done",
            ["stage_id=STAGE-001-01", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value={"ok": True, "error": None, "stage_id": "STAGE-001-01",
                                     "old_status": "pending", "new_status": "done", "changed": True}):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("STAGE-001-01", reply)
        self.assertIn("pending", reply)
        self.assertIn("done", reply)

    def test_happy_path_with_notes(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/updatestage stage_id=STAGE-001-01 status=blocked notes="Ожидаем документы клиента"',
            ["stage_id=STAGE-001-01", "status=blocked", 'notes="Ожидаем документы клиента"'],
        )
        captured = {}

        def fake_update(stage_id, status, notes=None):
            captured["notes"] = notes
            return {"ok": True, "error": None, "stage_id": stage_id,
                    "old_status": "pending", "new_status": status, "changed": True}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       side_effect=fake_update):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        self.assertEqual(captured["notes"], "Ожидаем документы клиента")
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Notes", reply)

    def test_missing_stage_id_shows_usage(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatestage status=done", ["status=done"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("stage", reply.lower())

    def test_missing_status_shows_usage_lists_canonical_values(self):
        th = _fresh_th()
        upd, ctx = _make_update("/updatestage stage_id=STAGE-001-01", ["stage_id=STAGE-001-01"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        for status in ("pending", "in_progress", "blocked", "done", "skipped"):
            self.assertIn(status, reply)

    def test_unknown_stage_id_shows_error(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-UNKNOWN status=done",
            ["stage_id=STAGE-UNKNOWN", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value={"ok": False, "error": "Этап 'STAGE-UNKNOWN' не найден",
                                     "stage_id": "STAGE-UNKNOWN", "old_status": "", "new_status": "done",
                                     "changed": False}):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("STAGE-UNKNOWN", reply)

    def test_invalid_status_shows_error(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001-01 status=bogus",
            ["stage_id=STAGE-001-01", "status=bogus"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value={"ok": False, "error": "Недопустимый статус 'bogus'. "
                                     "Допустимые значения: pending, in_progress, blocked, done, skipped",
                                     "stage_id": "STAGE-001-01", "old_status": "", "new_status": "bogus",
                                     "changed": False}):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("bogus", reply)

    def test_idempotent_repeat_shows_no_change_message(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001-01 status=done",
            ["stage_id=STAGE-001-01", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value={"ok": True, "error": None, "stage_id": "STAGE-001-01",
                                     "old_status": "done", "new_status": "done", "changed": False}):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("❌", reply)

    def test_bc_disabled_shows_message_without_calling_sheets(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001-01 status=done",
            ["stage_id=STAGE-001-01", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet") as mock_update:
                await th.updatestage_cmd(upd, ctx)
                mock_update.assert_not_called()

        _run(run())


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

    def test_roadmap_manager_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "roadmap_manager.py")

    def test_telegram_handlers_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_rm()
        _fresh_th()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)

    def test_updatestage_docstring_mentions_canonical_statuses(self):
        th = _fresh_th()
        import inspect
        src = inspect.getsource(th.updatestage_cmd)
        for status in ("pending", "in_progress", "blocked", "done", "skipped"):
            self.assertIn(status, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
