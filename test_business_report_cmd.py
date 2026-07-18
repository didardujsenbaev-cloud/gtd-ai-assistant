"""
Phase 11B: /report Telegram handler — mock tests.

report_cmd() must contain no business logic of its own — it only calls
business_core.report_manager functions and passes the result to _reply().
These tests verify the pipeline wiring, not the report content itself
(content is covered by test_business_report_manager.py).
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import report_cmd
    return report_cmd


def _make_update_context():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 123
    context = MagicMock()
    context.args = []
    return update, context


class TestReportCmdPipeline(unittest.TestCase):
    """Handler calls collect_snapshot -> build_* -> render_report -> reply,
    in that order, and does not assemble text itself."""

    def test_calls_collect_snapshot_and_render_report(self):
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        fake_snapshot = {"errors": {}}
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.report_manager.collect_snapshot",
                   return_value=fake_snapshot) as mock_snapshot, \
             patch("business_core.report_manager.build_attention",
                   return_value={"a": 1}) as mock_attention, \
             patch("business_core.report_manager.build_statistics",
                   return_value={"b": 2}) as mock_stats, \
             patch("business_core.report_manager.build_quality",
                   return_value={"c": 3}) as mock_quality, \
             patch("business_core.report_manager.build_progress",
                   return_value={"d": 4}) as mock_progress, \
             patch("business_core.report_manager.render_report",
                   return_value="RENDERED TEXT") as mock_render:
            asyncio.run(report_cmd(update, context))

        mock_snapshot.assert_called_once()
        mock_attention.assert_called_once_with(fake_snapshot)
        mock_stats.assert_called_once_with(fake_snapshot)
        mock_quality.assert_called_once_with(fake_snapshot)
        mock_progress.assert_called_once_with(fake_snapshot)
        mock_render.assert_called_once()
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertEqual(msg, "RENDERED TEXT")

    def test_render_report_called_with_all_four_structures(self):
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.report_manager.collect_snapshot",
                   return_value={"errors": {}}), \
             patch("business_core.report_manager.build_attention",
                   return_value={"attn": True}), \
             patch("business_core.report_manager.build_statistics",
                   return_value={"stats": True}), \
             patch("business_core.report_manager.build_quality",
                   return_value={"qual": True}), \
             patch("business_core.report_manager.build_progress",
                   return_value={"prog": True}), \
             patch("business_core.report_manager.render_report",
                   return_value="OK") as mock_render:
            asyncio.run(report_cmd(update, context))

        args, kwargs = mock_render.call_args
        self.assertEqual(args[0], {"attn": True})
        self.assertEqual(args[1], {"stats": True})
        self.assertEqual(args[2], {"qual": True})
        self.assertEqual(args[3], {"prog": True})


class TestReportCmdDisabled(unittest.TestCase):
    def test_bc_disabled_no_snapshot_called(self):
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
             patch("business_core.report_manager.collect_snapshot") as mock_snapshot:
            asyncio.run(report_cmd(update, context))

        mock_snapshot.assert_not_called()
        update.message.reply_text.assert_called_once()


class TestReportCmdErrorHandling(unittest.TestCase):
    def test_exception_does_not_propagate_as_traceback(self):
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.report_manager.collect_snapshot",
                   side_effect=RuntimeError("boom")):
            # Must not raise — handler catches and replies with an error message.
            asyncio.run(report_cmd(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)


class TestReportCmdNoLiveApi(unittest.TestCase):
    def test_no_live_sheets_access(self):
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet, \
             patch("business_core.sheets.read_business_sheet", return_value=[]):
            asyncio.run(report_cmd(update, context))

        mock_get_sheet.assert_not_called()
        update.message.reply_text.assert_called_once()

    def test_end_to_end_with_only_sheets_layer_mocked(self):
        """Full pipeline (no report_manager internals mocked) — only the
        Sheets layer is mocked, proving report_cmd never touches live API
        even when exercising real report_manager logic."""
        report_cmd = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.read_business_sheet", return_value=[]):
            asyncio.run(report_cmd(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("Требует внимания", msg)
        self.assertIn("Статистика", msg)


class TestReportCmdImportSafety(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
