"""
Phase 14A: Stage Management Core — mock tests.

Scope: basic stage management only — Start Date, Priority, Blocking
Reason (new columns) plus Responsible/Due Date/Completed At/Notes/
Checklist IDs (already existed, read-only here). No document or
checklist management logic (Checklist Status / Docs Status are
explicitly out of scope for this phase).

Covers:
- Start Date / Completed At auto-fill in update_stage_status_in_sheet().
- /stage (read-only view of all fields, including new ones; empty
  Priority displays as 'normal' without ever being written).
- /assignstage, /duedate, /priority, /blockstage, /unblockstage — each
  via the shared immutable-snapshot confirm architecture.
- Backward compatibility with pre-Phase-14A (shorter) rows.

All tests fully mock business_core.sheets — no live Google Sheets API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

STAGE_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
    "Start Date", "Priority", "Blocking Reason",
]


def _row(stage_id="STAGE-001", roadmap_id="RM-001", order="1", name="Диагностика",
         status="pending", due_date="", completed_at="", responsible="",
         docs_required="паспорт", docs_received="", notes="",
         checklist_ids="", start_date="", priority="", blocking_reason=""):
    idx = {h: i for i, h in enumerate(STAGE_HEADERS)}
    row = [""] * len(STAGE_HEADERS)
    row[idx["Stage ID"]] = stage_id
    row[idx["Roadmap ID"]] = roadmap_id
    row[idx["Order"]] = order
    row[idx["Name"]] = name
    row[idx["Status"]] = status
    row[idx["Due Date"]] = due_date
    row[idx["Completed At"]] = completed_at
    row[idx["Responsible"]] = responsible
    row[idx["Docs Required"]] = docs_required
    row[idx["Docs Received"]] = docs_received
    row[idx["Notes"]] = notes
    row[idx["Checklist IDs"]] = checklist_ids
    row[idx["Start Date"]] = start_date
    row[idx["Priority"]] = priority
    row[idx["Blocking Reason"]] = blocking_reason
    return row


def _make_stage_sheet(row=None, row_num=2):
    row = row if row is not None else _row()
    sheet = MagicMock()
    values = [STAGE_HEADERS, row]
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    updates = {}
    def _update_cell(r, c, v):
        updates[(r, c)] = v
    sheet.update_cell.side_effect = _update_cell
    sheet._updates = updates
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    return sheet


def _fresh_rm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.roadmap_manager as rm
    return rm


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _ctx(args=None):
    context = MagicMock()
    context.user_data = {}
    context.args = args or []
    return context


# ────────────────────────────────────────────────────────────
# Schema / backward compatibility
# ────────────────────────────────────────────────────────────

class TestSchemaBackwardCompatibility(unittest.TestCase):
    def test_new_columns_added_exactly_once(self):
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS["roadmap_stages"]
        for col in ("Start Date", "Priority", "Blocking Reason"):
            self.assertEqual(headers.count(col), 1, f"{col} must appear exactly once")
        # Явно НЕ добавлены в Phase 14A
        self.assertNotIn("Checklist Status", headers)
        self.assertNotIn("Docs Status", headers)
        # Существующие поля переиспользуются, не дублируются
        for col in ("Responsible", "Due Date", "Completed At", "Notes", "Checklist IDs"):
            self.assertEqual(headers.count(col), 1)

    def test_old_short_row_reads_without_error(self):
        th = _fresh_th()
        old_row = [
            "STAGE-001", "RM-001", "1", "Диагностика", "pending",
            "", "", "", "Дидар", "паспорт", "", "старая заметка",
            "", "", "", "", "",
        ]  # 17 колонок — ровно как до Phase 14A, без Start Date/Priority/Blocking Reason
        self.assertEqual(len(old_row), 17)
        row_dict = {
            STAGE_HEADERS[j]: (old_row[j] if j < len(old_row) else "")
            for j in range(len(STAGE_HEADERS))
        }
        update, context = _upd("/stage stage_id=STAGE-001"), _ctx(args=["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
                await th.stage_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("Дидар", msg)
        self.assertIn("Start Date: —", msg)
        self.assertIn("Приоритет: normal", msg)  # пусто -> отображается как normal
        self.assertIn("Blocking Reason: —", msg)


# ────────────────────────────────────────────────────────────
# Auto-fill: Start Date / Completed At
# ────────────────────────────────────────────────────────────

class TestAutofill(unittest.TestCase):
    def test_pending_to_in_progress_fills_empty_start_date(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet(_row(status="pending", start_date=""))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "in_progress")

        self.assertTrue(result["ok"])
        start_col = STAGE_HEADERS.index("Start Date") + 1
        self.assertIn((2, start_col), sheet._updates)
        self.assertRegex(sheet._updates[(2, start_col)], r"^\d{4}-\d{2}-\d{2}$")

    def test_repeat_in_progress_does_not_overwrite_start_date(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet(_row(status="blocked", start_date="2026-01-01"))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001", "in_progress")

        start_col = STAGE_HEADERS.index("Start Date") + 1
        self.assertNotIn((2, start_col), sheet._updates)

    def test_pending_to_done_fills_completed_at(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet(_row(status="pending", completed_at=""))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.update_stage_status_in_sheet("STAGE-001", "done")

        self.assertTrue(result["ok"])
        completed_col = STAGE_HEADERS.index("Completed At") + 1
        self.assertIn((2, completed_col), sheet._updates)

    def test_only_target_stage_row_written(self):
        rm = _fresh_rm()
        sheet = _make_stage_sheet(_row(status="pending"), row_num=57)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001", "done")
        for (r, _c) in sheet._updates:
            self.assertEqual(r, 57)

    def test_next_stage_not_touched(self):
        """update_stage_status_in_sheet принимает один stage_id и меняет
        только его строку — 'следующий этап' в принципе не адресуется."""
        rm = _fresh_rm()
        sheet = _make_stage_sheet(_row(stage_id="STAGE-001", status="pending"), row_num=2)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.update_stage_status_in_sheet("STAGE-001", "done")
        # sheet mock содержит только одну строку данных (row_num=2);
        # ни один update_cell не адресует другую строку.
        for (r, _c) in sheet._updates:
            self.assertEqual(r, 2)


# ────────────────────────────────────────────────────────────
# /stage — read-only view
# ────────────────────────────────────────────────────────────

class TestStageCmd(unittest.TestCase):
    def test_shows_all_fields_including_new_ones(self):
        th = _fresh_th()
        sheet = _make_stage_sheet(_row(priority="high", start_date="2026-07-01",
                                        blocking_reason="ждём документы"))
        update, context = _upd("/stage stage_id=STAGE-001"), _ctx(args=["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet):
                await th.stage_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("high", msg)
        self.assertIn("2026-07-01", msg)
        self.assertIn("ждём документы", msg)

    def test_not_found(self):
        th = _fresh_th()
        sheet = _make_stage_sheet()
        sheet.get_all_values.return_value = [STAGE_HEADERS]
        update, context = _upd("/stage stage_id=STAGE-999"), _ctx(args=["stage_id=STAGE-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet):
                await th.stage_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", msg)


# ────────────────────────────────────────────────────────────
# Generic helpers for the shared start/confirm architecture
# ────────────────────────────────────────────────────────────

def _run_start(th, start_fn, args_str, row=None):
    """args_str is the full command line including the leading /command
    token, mirroring what a human types — but context.args (like real
    python-telegram-bot) must NOT include that leading token."""
    sheet = _make_stage_sheet(row or _row())
    args_only = args_str.split()[1:]
    context = _ctx(args=args_only)
    update = _upd(args_str)

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id",
                   return_value=(2, dict(zip(STAGE_HEADERS, row or _row())))):
            result = await start_fn(update, context)
        return result

    result = asyncio.run(run())
    return result, update, context, sheet


def _run_confirm(th, confirm_fn, context, sheet, text="✅ Подтвердить", row=None):
    update = _upd(text)

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.find_row_by_id",
                   return_value=(2, dict(zip(STAGE_HEADERS, row or _row())))):
            await confirm_fn(update, context)

    asyncio.run(run())
    return update


class TestAssignStage(unittest.TestCase):
    def test_happy_path_writes_responsible_only(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.assignstage_start, "/assignstage stage_id=STAGE-001 responsible=Иван")
        _run_confirm(th, th.assignstage_confirm, context, sheet)

        col = STAGE_HEADERS.index("Responsible") + 1
        self.assertEqual(sheet._updates.get((2, col)), "Иван")
        self.assertEqual(len(sheet._updates), 1)
        self.assertNotIn("se_assign", context.user_data)

    def test_unassign_clears_responsible(self):
        th = _fresh_th()
        row = _row(responsible="Иван")
        _, _, context, sheet = _run_start(
            th, th.assignstage_start, '/assignstage stage_id=STAGE-001 responsible=""', row=row)
        _run_confirm(th, th.assignstage_confirm, context, sheet, row=row)

        col = STAGE_HEADERS.index("Responsible") + 1
        self.assertEqual(sheet._updates.get((2, col)), "")

    def test_stage_not_found(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-999", "responsible=Иван"])
        update = _upd("/assignstage stage_id=STAGE-999 responsible=Иван")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=None):
                return await th.assignstage_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("se_assign", context.user_data)

    def test_missing_responsible_arg_entirely_is_usage_error(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-001"])
        update = _upd("/assignstage stage_id=STAGE-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.assignstage_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)

    def test_cancel_writes_nothing(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.assignstage_start, "/assignstage stage_id=STAGE-001 responsible=Иван")
        _run_confirm(th, th.assignstage_confirm, context, sheet, text="❌ Отмена")
        self.assertEqual(sheet._updates, {})
        self.assertNotIn("se_assign", context.user_data)

    def test_snapshot_is_the_source_of_truth_for_save(self):
        """Snapshot читается и используется целиком на confirm — draft
        (context.user_data['nc'] и т.п. аналоги) в принципе не существует
        отдельно от snapshot в этой архитектуре, так что 'мутация после
        показа карточки' невозможна иначе, чем через сам snapshot."""
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.assignstage_start, "/assignstage stage_id=STAGE-001 responsible=Иван")
        self.assertEqual(context.user_data["se_assign"]["writes"]["Responsible"], "Иван")
        _run_confirm(th, th.assignstage_confirm, context, sheet)
        col = STAGE_HEADERS.index("Responsible") + 1
        self.assertEqual(sheet._updates.get((2, col)), "Иван")

    def test_immutable_fields_never_written(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.assignstage_start, "/assignstage stage_id=STAGE-001 responsible=Иван")
        _run_confirm(th, th.assignstage_confirm, context, sheet)
        written_cols = {c for (_r, c) in sheet._updates}
        for protected in ("Stage ID", "Roadmap ID", "Order", "Name"):
            self.assertNotIn(STAGE_HEADERS.index(protected) + 1, written_cols)


class TestDueDate(unittest.TestCase):
    def test_happy_path(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.duedate_start, "/duedate stage_id=STAGE-001 date=2026-08-01")
        _run_confirm(th, th.duedate_confirm, context, sheet)
        col = STAGE_HEADERS.index("Due Date") + 1
        self.assertEqual(sheet._updates.get((2, col)), "2026-08-01")

    def test_clear_due_date(self):
        th = _fresh_th()
        row = _row(due_date="2026-08-01")
        _, _, context, sheet = _run_start(
            th, th.duedate_start, '/duedate stage_id=STAGE-001 date=""', row=row)
        _run_confirm(th, th.duedate_confirm, context, sheet, row=row)
        col = STAGE_HEADERS.index("Due Date") + 1
        self.assertEqual(sheet._updates.get((2, col)), "")

    def test_invalid_date_format_rejected(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-001", "date=01/08/2026"])
        update = _upd("/duedate stage_id=STAGE-001 date=01/08/2026")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.duedate_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("формате", msg)

    def test_missing_date_arg_entirely_is_usage_error(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-001"])
        update = _upd("/duedate stage_id=STAGE-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.duedate_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)


class TestPriority(unittest.TestCase):
    def test_happy_path(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.priority_start, "/priority stage_id=STAGE-001 level=high")
        _run_confirm(th, th.priority_confirm, context, sheet)
        col = STAGE_HEADERS.index("Priority") + 1
        self.assertEqual(sheet._updates.get((2, col)), "high")

    def test_stores_canonical_lowercase(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.priority_start, "/priority stage_id=STAGE-001 level=HIGH")
        _run_confirm(th, th.priority_confirm, context, sheet)
        col = STAGE_HEADERS.index("Priority") + 1
        self.assertEqual(sheet._updates.get((2, col)), "high")

    def test_normal_is_a_valid_explicit_choice(self):
        th = _fresh_th()
        _, _, context, sheet = _run_start(
            th, th.priority_start, "/priority stage_id=STAGE-001 level=normal")
        _run_confirm(th, th.priority_confirm, context, sheet)
        col = STAGE_HEADERS.index("Priority") + 1
        self.assertEqual(sheet._updates.get((2, col)), "normal")

    def test_invalid_level_rejected(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-001", "level=super-urgent"])
        update = _upd("/priority stage_id=STAGE-001 level=super-urgent")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.priority_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)

    def test_empty_priority_not_auto_written_without_user_action(self):
        """Пустой Priority отображается как 'normal' в /stage, но это
        НЕ приводит к автоматической записи 'normal' в Sheets — только
        явный вызов /priority level=... пишет что-либо."""
        th = _fresh_th()
        sheet = _make_stage_sheet(_row(priority=""))
        update, context = _upd("/stage stage_id=STAGE-001"), _ctx(args=["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet):
                await th.stage_cmd(update, context)

        asyncio.run(run())
        self.assertEqual(sheet._updates, {})


class TestBlockUnblockStage(unittest.TestCase):
    def test_blockstage_sets_reason_and_status(self):
        th = _fresh_th()
        row = _row(status="in_progress")
        _, _, context, sheet = _run_start(
            th, th.blockstage_start,
            '/blockstage stage_id=STAGE-001 reason="ждём документы"', row=row)
        _run_confirm(th, th.blockstage_confirm, context, sheet, row=row)

        reason_col = STAGE_HEADERS.index("Blocking Reason") + 1
        status_col = STAGE_HEADERS.index("Status") + 1
        self.assertEqual(sheet._updates.get((2, reason_col)), "ждём документы")
        self.assertEqual(sheet._updates.get((2, status_col)), "blocked")

    def test_blockstage_empty_reason_rejected(self):
        th = _fresh_th()
        context = _ctx(args=["stage_id=STAGE-001", 'reason='])
        update = _upd("/blockstage stage_id=STAGE-001 reason=")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.blockstage_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)

    def test_unblockstage_clears_reason_and_reverts_status_when_blocked(self):
        th = _fresh_th()
        row = _row(status="blocked", blocking_reason="ждём документы")
        _, _, context, sheet = _run_start(
            th, th.unblockstage_start, "/unblockstage stage_id=STAGE-001", row=row)
        _run_confirm(th, th.unblockstage_confirm, context, sheet, row=row)

        reason_col = STAGE_HEADERS.index("Blocking Reason") + 1
        status_col = STAGE_HEADERS.index("Status") + 1
        self.assertEqual(sheet._updates.get((2, reason_col)), "")
        self.assertEqual(sheet._updates.get((2, status_col)), "pending")

    def test_unblockstage_does_not_touch_status_when_not_blocked(self):
        th = _fresh_th()
        row = _row(status="done", blocking_reason="старая причина")
        _, _, context, sheet = _run_start(
            th, th.unblockstage_start, "/unblockstage stage_id=STAGE-001", row=row)
        _run_confirm(th, th.unblockstage_confirm, context, sheet, row=row)

        status_col = STAGE_HEADERS.index("Status") + 1
        self.assertNotIn((2, status_col), sheet._updates)

    def test_unblockstage_shows_actual_old_to_new(self):
        th = _fresh_th()
        row = _row(status="blocked", blocking_reason="ждём документы от клиента")
        _, update_start, context, sheet = _run_start(
            th, th.unblockstage_start, "/unblockstage stage_id=STAGE-001", row=row)
        card = update_start.message.reply_text.call_args[0][0]
        self.assertIn("ждём документы от клиента", card)


class TestCommandsExcludedFromPhase14A(unittest.TestCase):
    """Требование Phase 14A: /checklist и /docs временно исключены."""

    def test_checklist_command_not_defined(self):
        th = _fresh_th()
        self.assertFalse(hasattr(th, "checklist_start"))

    def test_docs_command_not_defined(self):
        th = _fresh_th()
        self.assertFalse(hasattr(th, "docs_start"))


class TestNoLiveApi(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
