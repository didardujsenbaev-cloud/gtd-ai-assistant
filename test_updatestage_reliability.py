"""
Tests for Phase 19B-1 — reliability hardening of update_stage_status_in_sheet()
and updatestage_cmd() against partial Google Sheets writes, plus the /stages
icon-mapping bug fix.

Covers (per the Phase 19B-1 spec):
- Per-field write isolation (Status / Completed At / Start Date / Notes),
  each independently caught, never wiping an already-confirmed Status.
- Fresh-read verification when the Status write itself raises — never
  guessed, always re-read.
- Separation of stage-update success from downstream progress-recalculation
  / roadmap-completion failures.
- The new structured result contract (ok, partial_success, previous_status,
  requested_status, final_status, updated_fields, warnings, errors) plus
  full backward compatibility with the old contract (error, old_status,
  new_status).
- Updated Telegram response wording for full-success / partial-success /
  failure-before-commit.
- The /stages 'done' icon-mapping fix.
- No coupling to document requirements / relations / GTD.

Deliberately does NOT cover (out of scope for Phase 19B-1):
- schema changes, new statuses, transition restrictions, auto-next-stage
  activation, responsible-person-ID work.
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

STAGES_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
    "Start Date", "Priority", "Blocking Reason",
]

STAGE_ROW = [
    "STAGE-001", "RM-001", "1", "Диагностика кейса", "pending",
    "", "", "", "Дидар",
    "Правоустанавливающий документ на землю", "", "",
    "", "", "", "", "",
    "", "", "",
]


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


def _make_sheet(headers=None, row=None, row_num=2, fail_headers: dict | None = None):
    """
    fail_headers: {header_name: Exception_instance} — update_cell() raises
    that exception when writing to that header's column; all other columns
    write normally (no-op MagicMock).
    """
    headers = headers if headers is not None else STAGES_HEADERS
    row = row if row is not None else list(STAGE_ROW)
    fail_headers = fail_headers or {}

    idx = {h: i for i, h in enumerate(headers)}
    fail_cols = {idx[h]: exc for h, exc in fail_headers.items() if h in idx}

    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row

    def fake_update_cell(r, c, v):
        col0 = c - 1
        if col0 in fail_cols:
            raise fail_cols[col0]
        return None

    sheet.update_cell.side_effect = fake_update_cell
    return sheet


class TestPerFieldWriteIsolation(unittest.TestCase):

    def test_status_write_raises_but_fresh_read_confirms_committed(self):
        """Status update_cell raises, but a fresh find_stage_by_id() shows
        the new status already committed -> honestly confirmed, not guessed."""
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Status": RuntimeError("timeout")})

        committed_row = list(STAGE_ROW)
        committed_row[STAGES_HEADERS.index("Status")] = "done"

        call_count = {"n": 0}
        real_row_values = sheet.row_values.side_effect

        def row_values_side_effect(r):
            if r == 1:
                return STAGES_HEADERS
            call_count["n"] += 1
            # First read (find_stage_by_id inside update_stage_status_in_sheet
            # itself) sees the OLD row; verification re-read sees the NEW one.
            return STAGE_ROW if call_count["n"] == 1 else committed_row

        sheet.row_values.side_effect = row_values_side_effect

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["final_status"], "done")
        self.assertIn("Status", result["updated_fields"])
        self.assertTrue(result["warnings"])

    def test_status_write_raises_and_verification_read_also_fails(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Status": RuntimeError("timeout")})

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.roadmap_manager.find_stage_by_id", side_effect=[
                 {"row_num": 2, "stage_id": "STAGE-001", "roadmap_id": "RM-001",
                  "status": "pending", "notes": ""},
                 RuntimeError("also failing"),
             ]):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertFalse(result["ok"])
        self.assertFalse(result["partial_success"])
        self.assertTrue(result["errors"])
        self.assertTrue(result["warnings"])

    def test_status_write_raises_verification_shows_old_status_total_failure(self):
        """Fresh read proves the write did NOT commit -> ok=False, final_status
        reflects the honestly-observed (unchanged) status, never a guess."""
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Status": RuntimeError("timeout")})

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertFalse(result["ok"])
        self.assertFalse(result["partial_success"])
        self.assertEqual(result["final_status"], "pending")
        self.assertNotIn("Status", result["updated_fields"])
        sheet.find.assert_called()

    def test_completed_at_write_raises_status_still_confirmed(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Completed At": RuntimeError("boom")})

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["final_status"], "done")
        self.assertIn("Status", result["updated_fields"])
        self.assertNotIn("Completed At", result["updated_fields"])
        self.assertTrue(any("Completed At" in w for w in result["warnings"]))

    def test_start_date_write_raises_status_still_confirmed(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Start Date": RuntimeError("boom")})

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "in_progress")

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["final_status"], "in_progress")
        self.assertIn("Status", result["updated_fields"])
        self.assertNotIn("Start Date", result["updated_fields"])
        self.assertTrue(any("Start Date" in w for w in result["warnings"]))

    def test_notes_write_raises_status_still_confirmed(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Notes": RuntimeError("boom")})

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "blocked", notes="ждём")

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertIn("Status", result["updated_fields"])
        self.assertNotIn("Notes", result["updated_fields"])
        self.assertTrue(any("Notes" in w for w in result["warnings"]))

    def test_notes_column_missing_is_warning_not_error(self):
        """Deliberate Phase 19B-1 improvement: Status is already confirmed by
        the time Notes is attempted, so a missing Notes column becomes a
        warning/partial-success, not a total failure."""
        rm = _fresh_rm()
        headers_no_notes = [h for h in STAGES_HEADERS if h != "Notes"]
        row_no_notes = [v for h, v in zip(STAGES_HEADERS, STAGE_ROW) if h != "Notes"]
        sheet = _make_sheet(headers=headers_no_notes, row=row_no_notes)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "blocked", notes="ждём")

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertTrue(any("Notes" in w for w in result["warnings"]))


class TestStructuredResultContract(unittest.TestCase):

    def test_full_success_all_contract_fields_present(self):
        rm = _fresh_rm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        for key in ("ok", "partial_success", "stage_id", "roadmap_id",
                    "previous_status", "requested_status", "final_status",
                    "changed", "updated_fields", "warnings", "errors",
                    "error", "old_status", "new_status"):
            self.assertIn(key, result)

        self.assertFalse(result["partial_success"])
        self.assertEqual(result["previous_status"], "pending")
        self.assertEqual(result["requested_status"], "done")
        self.assertEqual(result["final_status"], "done")
        self.assertEqual(result["updated_fields"], ("Status", "Completed At"))

    def test_updated_fields_contains_only_confirmed_writes(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Completed At": RuntimeError("x")})
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertEqual(result["updated_fields"], ("Status",))

    def test_final_status_from_fresh_state_not_a_guess(self):
        rm = _fresh_rm()
        sheet = _make_sheet(fail_headers={"Status": RuntimeError("timeout")})
        committed_row = list(STAGE_ROW)
        committed_row[STAGES_HEADERS.index("Status")] = "skipped"

        call_count = {"n": 0}

        def row_values_side_effect(r):
            if r == 1:
                return STAGES_HEADERS
            call_count["n"] += 1
            return STAGE_ROW if call_count["n"] == 1 else committed_row

        sheet.row_values.side_effect = row_values_side_effect

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "skipped")

        self.assertEqual(result["final_status"], "skipped")


class TestIdempotencyAndTransitions(unittest.TestCase):

    def test_same_status_retry_no_warnings(self):
        rm = _fresh_rm()
        row_already_done = list(STAGE_ROW)
        row_already_done[STAGES_HEADERS.index("Status")] = "done"
        sheet = _make_sheet(row=row_already_done)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertFalse(result["partial_success"])

    def test_start_date_not_overwritten_if_already_set(self):
        rm = _fresh_rm()
        row = list(STAGE_ROW)
        row[STAGES_HEADERS.index("Start Date")] = "2026-01-01"
        sheet = _make_sheet(row=row)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "in_progress")

        self.assertTrue(result["ok"])
        self.assertNotIn("Start Date", result["updated_fields"])

    def test_completed_at_refilled_every_done_transition(self):
        rm = _fresh_rm()
        row = list(STAGE_ROW)
        row[STAGES_HEADERS.index("Status")] = "done"
        row[STAGES_HEADERS.index("Completed At")] = "2025-01-01"
        sheet = _make_sheet(row=row)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertIn("Completed At", result["updated_fields"])

    def test_any_status_may_transition_to_any_other(self):
        """Approved business rule: no transition restrictions — done can go
        back to pending, skipped, etc."""
        rm = _fresh_rm()
        row = list(STAGE_ROW)
        row[STAGES_HEADERS.index("Status")] = "done"
        sheet = _make_sheet(row=row)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "pending")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["final_status"], "pending")

    def test_multiple_stages_can_be_in_progress_independently(self):
        """No coupling between stages — update_stage_status_in_sheet only
        touches the single targeted row."""
        rm = _fresh_rm()
        sheet = _make_sheet(row_num=9)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001", "in_progress")

        for call in sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 9)


class TestNoCouplingToDocumentsOrRelationsOrGTD(unittest.TestCase):

    def test_no_document_requirements_or_relation_imports_in_function_source(self):
        rm = _fresh_rm()
        import inspect
        src = inspect.getsource(rm.update_stage_status_in_sheet)
        self.assertNotIn("document_requirements", src)
        self.assertNotIn("stage_entity_relations", src)

    def test_missing_documents_do_not_block_done(self):
        rm = _fresh_rm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")
        self.assertTrue(result["ok"])

    def test_no_gtd_module_imports(self):
        rm = _fresh_rm()
        import inspect
        src = inspect.getsource(rm.update_stage_status_in_sheet)
        for forbidden in ("inbox_processor", "telegram_bot", "project_planner", "calendar_sync"):
            self.assertNotIn(forbidden, src)


class TestTelegramResponses(unittest.TestCase):
    """Phase 34C: updatestage_cmd now calls the single canonical
    business_builder.transition_stage_status() — every scenario below
    mocks that one boundary directly instead of the low-level
    roadmap_manager functions it now calls internally (see
    test_stage_transition_foundation.py for coverage of those internals)."""

    def _transition_result(self, **overrides):
        base = {
            "ok": True, "code": "STAGE_STATUS_UPDATED", "error": None,
            "stage_id": "STAGE-001", "roadmap_id": "RM-001",
            "previous_status": "pending", "requested_status": "done", "final_status": "done",
            "changed": True, "partial_success": False, "written_fields": ("Status", "Completed At"),
            "warnings": (), "downstream_failures": (),
            "progress_before": 33, "progress_after": 67,
            "roadmap_status_before": "active", "roadmap_status_after": "active",
            "retry_safe": True,
        }
        base.update(overrides)
        return base

    def test_failure_before_commit_response(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(
                           ok=False, code="STAGE_WRITE_PARTIAL_FAILURE",
                           changed=False, final_status="pending",
                           error="Не удалось записать Status: timeout")):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIn("Не удалось обновить этап", reply)
        self.assertIn("pending", reply)

    def test_partial_success_response_from_stage_warnings(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(
                           partial_success=True,
                           downstream_failures=("Не удалось обновить Completed At: timeout",))):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("Статус сохранён", reply)
        self.assertIn("Completed At", reply)
        self.assertIn("Повтор команды безопасен", reply)

    def test_partial_success_response_from_downstream_progress_failure(self):
        """Stage update itself fully succeeds; progress recalculation fails.
        This must still surface as a partial-success response, never a
        total failure, and must never flip the confirmed Status result."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(
                           code="PROGRESS_RECALCULATION_FAILED", partial_success=True,
                           progress_before=None, progress_after=None,
                           downstream_failures=("Не удалось пересчитать прогресс: 429 quota",))):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("429 quota", reply)

    def test_partial_success_response_from_downstream_completion_failure(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(
                           code="ROADMAP_AUTO_COMPLETION_FAILED", partial_success=True,
                           progress_before=33, progress_after=100,
                           downstream_failures=("Не удалось проверить завершение Roadmap: 429 quota",))):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("завершение Roadmap", reply)

    def test_full_success_response_unchanged_shape(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result()):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅ Статус этапа обновлён", reply)
        self.assertIn("Было: Ожидает (`pending`)", reply)
        self.assertIn("Стало: Выполнен (`done`)", reply)
        self.assertNotIn("⚠️", reply)

    def test_progress_math_unchanged_in_response(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(progress_before=33, progress_after=67)):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Прогресс: 33% → 67%", reply)

    def test_roadmap_completion_response_unchanged(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_stage_status",
                       return_value=self._transition_result(
                           progress_before=67, progress_after=100,
                           roadmap_status_before="active", roadmap_status_after="completed")):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("🎉 Все этапы завершены. Roadmap `RM-001` переведена в статус «Завершена».", reply)


class TestStagesIconFix(unittest.TestCase):

    def test_stages_displays_done_with_checkmark_icon(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stages roadmap_id=RM-001", ["roadmap_id=RM-001"])

        stage_data = [
            {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "order": "1",
             "name": "Этап 1", "status": "done", "due_date": "", "notes": ""},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.get_stages_for_roadmap", return_value=stage_data), \
                 patch("business_core.business_builder.find_roadmap_by_id", return_value={
                     "roadmap_id": "RM-001", "title": "Test", "case_type": "legalization",
                 }):
                await th.stages_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("✅ *1.* Этап 1", reply)

    def test_stages_done_no_longer_falls_back_to_default_icon(self):
        th = _fresh_th()
        upd, ctx = _make_update("/stages roadmap_id=RM-001", ["roadmap_id=RM-001"])

        stage_data = [
            {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "order": "1",
             "name": "Этап 1", "status": "done", "due_date": "", "notes": ""},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.get_stages_for_roadmap", return_value=stage_data), \
                 patch("business_core.business_builder.find_roadmap_by_id", return_value={
                     "roadmap_id": "RM-001", "title": "Test", "case_type": "legalization",
                 }):
                await th.stages_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("⬜ *1.* Этап 1", reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
