"""
Tests for Phase 9E.1 — автоматический пересчёт Progress % после
успешного /updatestage.

Контракт:
- после успешного update_stage_status_in_sheet (валидный статус,
  существующий этап) команда вызывает recalculate_roadmap_progress(roadmap_id)
  ровно один раз с правильным roadmap_id;
- при невалидном status или несуществующем stage_id recalculate НЕ
  вызывается вовсе;
- Status roadmap не меняется, ROADMAP_STAGES после установки статуса
  этапа больше ничем не меняется, другие roadmap не затрагиваются;
- /recalcprogress продолжает работать независимо (не удалялась, не
  менялась логика).
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


def _fresh_rm():
    return _fresh("business_core.roadmap_manager")


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


def _stage_row(status="pending", notes="Существующая заметка"):
    row = [""] * len(STAGES_HEADERS)
    idx = {h: i for i, h in enumerate(STAGES_HEADERS)}
    row[idx["Stage ID"]] = "STAGE-001"
    row[idx["Roadmap ID"]] = "RM-001"
    row[idx["Order"]] = "1"
    row[idx["Name"]] = "Диагностика"
    row[idx["Status"]] = status
    row[idx["Notes"]] = notes
    return row


def _roadmaps_row(progress="33", status="active"):
    row = [""] * len(ROADMAPS_HEADERS)
    idx = {h: i for i, h in enumerate(ROADMAPS_HEADERS)}
    row[idx["Roadmap ID"]] = "RM-001"
    row[idx["Progress %"]] = progress
    row[idx["Status"]] = status
    return row


def _make_sheet_dispatcher(stage_row, roadmaps_row, stage_row_num=2, roadmaps_row_num=2,
                           stage_statuses=None):
    """
    Собрать fake get_business_sheet, обслуживающий 'roadmap_stages' и
    'roadmaps'. stage_statuses — если передан, ROADMAP_STAGES будет
    содержать несколько этапов (для реалистичного пересчёта Progress %),
    иначе — один STAGE-001 из stage_row.
    """
    stages_sheet = MagicMock()
    stage_cell = MagicMock()
    stage_cell.row = stage_row_num
    stages_sheet.find.return_value = stage_cell
    stages_sheet.row_values.side_effect = (
        lambda r: STAGES_HEADERS if r == 1 else stage_row
    )

    if stage_statuses is None:
        all_stage_rows = [STAGES_HEADERS, stage_row]
    else:
        all_stage_rows = [STAGES_HEADERS] + stage_statuses
    stages_sheet.get_all_values.return_value = all_stage_rows

    roadmaps_sheet = MagicMock()
    rm_cell = MagicMock()
    rm_cell.row = roadmaps_row_num
    roadmaps_sheet.find.return_value = rm_cell
    roadmaps_sheet.row_values.side_effect = (
        lambda r: ROADMAPS_HEADERS if r == 1 else roadmaps_row
    )

    def dispatcher(key):
        if key == "roadmap_stages":
            return stages_sheet
        if key == "roadmaps":
            return roadmaps_sheet
        raise AssertionError(f"неожиданный лист '{key}'")

    return dispatcher, stages_sheet, roadmaps_sheet


# ────────────────────────────────────────────────────────────
# Основной контракт: вызов recalculate только при успехе
# ────────────────────────────────────────────────────────────

def _transition_result(**overrides):
    """Phase 34C: updatestage_cmd now calls the single canonical
    business_builder.transition_stage_status() — progress recalculation
    and Roadmap auto-completion are internal to it (see
    test_stage_transition_foundation.py for call-count/argument-level
    coverage of that internal orchestration). Handler-level tests here
    mock this one boundary directly instead of the low-level
    roadmap_manager functions transition_stage_status() calls internally."""
    base = {
        "ok": True, "code": "STAGE_STATUS_UPDATED", "error": None,
        "stage_id": "STAGE-001", "roadmap_id": "RM-001",
        "previous_status": "pending", "requested_status": "done", "final_status": "done",
        "changed": True, "partial_success": False, "written_fields": ("Status",),
        "warnings": (), "downstream_failures": (),
        "progress_before": None, "progress_after": None,
        "roadmap_status_before": "active", "roadmap_status_after": "active",
        "retry_safe": True,
    }
    base.update(overrides)
    return base


class TestRecalculateCalledOnlyOnSuccess(unittest.TestCase):

    def test_status_changed_calls_recalculate_once_with_correct_roadmap_id(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(progress_before=33, progress_after=67)):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("RM-001", reply)

    def test_invalid_status_does_not_call_recalculate(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=bogus",
            ["stage_id=STAGE-001", "status=bogus"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(
                           ok=False, code="INVALID_STAGE_STATUS",
                           error="Недопустимый статус 'bogus'. "
                                 "Допустимые значения: pending, in_progress, blocked, done, skipped",
                           requested_status="bogus", final_status="pending", changed=False, roadmap_id="",
                       )):
                await th.updatestage_cmd(upd, ctx)

        _run(run())

    def test_stage_not_found_does_not_call_recalculate(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-UNKNOWN status=done",
            ["stage_id=STAGE-UNKNOWN", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(
                           ok=False, code="STAGE_NOT_FOUND", error="Этап STAGE-UNKNOWN не найден",
                           stage_id="STAGE-UNKNOWN", final_status="", changed=False, roadmap_id="",
                       )):
                await th.updatestage_cmd(upd, ctx)

        _run(run())

    def test_idempotent_status_still_calls_recalculate(self):
        """Повторная установка того же статуса всё равно валидна и успешна —
        текущий Progress показывается (changed=False)."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(
                           previous_status="done", requested_status="done", final_status="done",
                           changed=False, written_fields=("Status",),
                       )):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("уже имеет запрошенный статус", reply)


# ────────────────────────────────────────────────────────────
# Формат ответа
# ────────────────────────────────────────────────────────────

class TestReplyFormat(unittest.TestCase):

    def test_progress_changed_true_format(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(progress_before=33, progress_after=67)):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertEqual(
            reply,
            "✅ Статус этапа обновлён\n"
            "Этап: `STAGE-001`\n"
            "Roadmap: `RM-001`\n"
            "Было: Ожидает (`pending`)\n"
            "Стало: Выполнен (`done`)\n"
            "Прогресс: 33% → 67%",
        )

    def test_progress_changed_false_format(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(
                           previous_status="done", requested_status="done", final_status="done",
                           changed=False,
                       )):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertEqual(
            reply,
            "ℹ️ Этап уже имеет запрошенный статус\n"
            "Этап: `STAGE-001`\n"
            "Roadmap: `RM-001`\n"
            "Текущий статус: Выполнен (`done`) (изменений нет, повтор безопасен).",
        )

    def test_notes_plus_status_progress_all_present_notes_not_lost(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            '/updatestage stage_id=STAGE-001 status=blocked notes="Ожидаем документы клиента"',
            ["stage_id=STAGE-001", "status=blocked", 'notes="Ожидаем документы клиента"'],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=_transition_result(
                           requested_status="blocked", final_status="blocked",
                           progress_before=0, progress_after=0,
                       )):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅ Статус этапа обновлён", reply)
        self.assertIn("Этап: `STAGE-001`", reply)
        self.assertIn("Стало: Заблокирован (`blocked`)", reply)
        self.assertIn("Прогресс: 0%", reply)
        self.assertIn("Notes обновлены: Ожидаем документы клиента", reply)

    def test_progress_line_skipped_when_roadmap_id_missing(self):
        """Если roadmap_id пуст (не должно происходить в норме, но защитно) —
        строка Progress не добавляется, ответ не падает."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value={"ok": True, "error": None, "stage_id": "STAGE-001",
                                     "roadmap_id": "", "old_status": "pending",
                                     "new_status": "done", "changed": True}), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc:
                await th.updatestage_cmd(upd, ctx)
                mock_recalc.assert_not_called()

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("STAGE-001", reply)
        self.assertNotIn("Progress", reply)


# ────────────────────────────────────────────────────────────
# Sheets-уровневая интеграция (реальная update_stage_status_in_sheet +
# реальная recalculate_roadmap_progress, mock только Sheets)
# ────────────────────────────────────────────────────────────

class TestEndToEndSheetsIntegration(unittest.TestCase):

    def _run_full_command(self, status="done", stage_row_status="pending",
                          stage_statuses=None, roadmaps_progress="33",
                          roadmaps_status="active", stage_row_num=5, roadmaps_row_num=8,
                          notes=None):
        th = _fresh_th()
        stage_row = _stage_row(status=stage_row_status)
        roadmaps_row = _roadmaps_row(progress=roadmaps_progress, status=roadmaps_status)
        dispatcher, stages_sheet, roadmaps_sheet = _make_sheet_dispatcher(
            stage_row, roadmaps_row, stage_row_num=stage_row_num,
            roadmaps_row_num=roadmaps_row_num, stage_statuses=stage_statuses,
        )

        text = f"/updatestage stage_id=STAGE-001 status={status}"
        args = [f"stage_id=STAGE-001", f"status={status}"]
        if notes is not None:
            text += f' notes="{notes}"'
            args.append(f'notes="{notes}"')
        upd, ctx = _make_update(text, args)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", side_effect=dispatcher):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        return upd, stages_sheet, roadmaps_sheet

    def test_writes_only_progress_percent_of_target_roadmap(self):
        # get_all_values() у мока статичен и не отражает update_cell,
        # выполненный чуть выше по цепочке (update_stage_status_in_sheet) —
        # поэтому STAGE-001 здесь сразу задан как 'done', представляя
        # состояние листа НА МОМЕНТ пересчёта (после записи статуса).
        stage_statuses = [
            ["STAGE-001", "RM-001", "1", "Диагностика", "done", "", "", "", "", "", "", "Заметка",
             "", "", "", "", ""],
            ["STAGE-002", "RM-001", "2", "Сбор документов", "pending", "", "", "", "", "", "", "",
             "", "", "", "", ""],
            ["STAGE-003", "RM-001", "3", "АПЗ", "pending", "", "", "", "", "", "", "",
             "", "", "", "", ""],
        ]
        upd, stages_sheet, roadmaps_sheet = self._run_full_command(
            status="done", stage_row_status="in_progress",
            stage_statuses=stage_statuses, roadmaps_progress="0",
        )

        # roadmaps_sheet.update_cell должен быть вызван один раз — только Progress %
        self.assertEqual(roadmaps_sheet.update_cell.call_count, 1)
        row_num, col, value = roadmaps_sheet.update_cell.call_args[0]
        self.assertEqual(col, ROADMAPS_HEADERS.index("Progress %") + 1)
        self.assertEqual(value, "33")  # 1 из 3 done -> round-half-up 33%

    def test_status_column_of_roadmap_not_touched(self):
        upd, stages_sheet, roadmaps_sheet = self._run_full_command(
            status="done", stage_row_status="in_progress",
        )
        self.assertGreater(roadmaps_sheet.update_cell.call_count, 0)
        written_cols = [c.args[1] for c in roadmaps_sheet.update_cell.call_args_list]
        self.assertNotIn(ROADMAPS_HEADERS.index("Status") + 1, written_cols)

    def test_stage_row_only_status_and_no_extra_writes_after(self):
        """После update_stage_status_in_sheet (пишет Status, и для 'done'
        дополнительно Completed At — Phase 14A) recalculate_roadmap_progress
        не должен ничего ЕЩЁ писать в ROADMAP_STAGES."""
        upd, stages_sheet, roadmaps_sheet = self._run_full_command(
            status="done", stage_row_status="in_progress",
        )
        # update_stage_status_in_sheet пишет Status + Completed At для 'done'
        # (notes не передан) — recalculate_roadmap_progress не добавляет
        # ничего сверху.
        self.assertEqual(stages_sheet.update_cell.call_count, 2)
        calls = {c.args[1]: c.args[2] for c in stages_sheet.update_cell.call_args_list}
        self.assertEqual(calls[STAGES_HEADERS.index("Status") + 1], "done")
        self.assertIn(STAGES_HEADERS.index("Completed At") + 1, calls)

    def test_only_target_roadmap_row_written(self):
        upd, stages_sheet, roadmaps_sheet = self._run_full_command(
            status="done", stage_row_status="in_progress", roadmaps_row_num=42,
        )
        self.assertGreater(roadmaps_sheet.update_cell.call_count, 0)
        for call in roadmaps_sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 42)

    def test_recalcprogress_command_still_works_independently(self):
        """/recalcprogress не менялась и продолжает работать как раньше."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/recalcprogress roadmap_id=RM-001",
            ["roadmap_id=RM-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value={"ok": True, "error": None, "roadmap_id": "RM-001",
                                     "old_progress": "0", "new_progress": 33,
                                     "done_count": 1, "total_count": 3, "changed": True}):
                await th.recalcprogress_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("RM-001", reply)
        self.assertIn("0%", reply)
        self.assertIn("33%", reply)


# ────────────────────────────────────────────────────────────
# roadmap_manager.update_stage_status_in_sheet — новое поле roadmap_id
# ────────────────────────────────────────────────────────────

class TestUpdateStageStatusReturnsRoadmapId(unittest.TestCase):

    def test_success_includes_roadmap_id(self):
        rm = _fresh_rm()
        stage_row = _stage_row(status="pending")
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 5
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: STAGES_HEADERS if r == 1 else stage_row

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertTrue(result["ok"])
        self.assertEqual(result["roadmap_id"], "RM-001")

    def test_invalid_status_roadmap_id_empty(self):
        rm = _fresh_rm()
        result = rm.update_stage_status_in_sheet("STAGE-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["roadmap_id"], "")

    def test_not_found_roadmap_id_empty(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-UNKNOWN", "done")
        self.assertFalse(result["ok"])
        self.assertEqual(result["roadmap_id"], "")

    def test_core_logic_unchanged_still_writes_only_status(self):
        """Добавление roadmap_id в возвращаемое значение не должно менять
        основную логику записи для non-'done' статусов (по-прежнему
        только Status/Notes — 'done' отдельно автозаполняет Completed At,
        см. test_updatestage.py)."""
        rm = _fresh_rm()
        stage_row = _stage_row(status="pending")
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 5
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: STAGES_HEADERS if r == 1 else stage_row

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001", "blocked")

        self.assertEqual(sheet.update_cell.call_count, 1)
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(col, STAGES_HEADERS.index("Status") + 1)


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

    def test_roadmap_manager_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "roadmap_manager.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_th()
        _fresh_rm()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
