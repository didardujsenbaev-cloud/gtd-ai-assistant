"""
Phase 16B.6: /docreport Telegram caller UX.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_report.generate_document_report at the call
site — never a live Sheets/network call. Mirrors
test_document_search_caller_ux.py's own _cmd()/_upd() helper pattern.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.telegram_handlers as th
from business_core.document_report import (
    DocumentReportCriteria, DocumentReportSummary, DocumentReportResult,
    ERROR_BUSINESS_NOT_FOUND, ERROR_REPORT_INVARIANT_FAILED,
)


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="didar", id=123)
    return update


def _cmd(cmdline: str):
    update = _upd(cmdline)
    context = MagicMock()
    context.user_data = {}
    context.args = cmdline.split()[1:]
    return update, context


def _summary(total_documents=1, **overrides):
    kwargs = dict(
        total_documents=total_documents,
        review_unreviewed_count=total_documents, review_partially_confirmed_count=0,
        review_confirmed_count=0, review_rejected_count=0,
        conflict_true_count=0, conflict_unknown_count=0, cache_warning_count=0,
        requires_action_true_count=0, requires_action_false_count=0,
        requires_action_unknown_count=total_documents,
        has_expiration_true_count=0, has_expiration_false_count=0,
        has_expiration_unknown_count=total_documents,
        valid_until_present_count=0, expired_count=0, expires_7d_count=0,
        expires_30d_count=0, expires_later_count=0, no_valid_until_count=total_documents,
        invalid_valid_until_count=0, expiration_inconsistency_count=0,
        exact_duplicate_count=0, new_document_count=total_documents,
        unknown_duplicate_status_count=0,
    )
    kwargs.update(overrides)
    return DocumentReportSummary(**kwargs)


def _result(summary=None, ok=True, error_code="", as_of="2026-07-29",
            business_id="BIZ-001", warnings=()):
    criteria = DocumentReportCriteria(business_id=business_id, as_of=as_of)
    return DocumentReportResult(
        criteria=criteria, ok=ok, error_code=error_code,
        summary=summary if summary is not None else (_summary() if ok else None),
        warnings=tuple(warnings), generated_at="2026-07-29 10:00:00 UTC",
        source_counts={},
    )


class TestDocreportValidation(unittest.TestCase):
    def test_missing_business_id_shows_validation_error(self):
        update, context = _cmd("/docreport as_of=2026-07-29")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("business_id", text)
        self.assertIn("Пример", text)

    def test_unknown_parameter_shows_validation_error(self):
        update, context = _cmd("/docreport business_id=BIZ-001 object_id=OBJ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("object_id", text)

    def test_invalid_as_of_shows_validation_error_no_report_call(self):
        update, context = _cmd("/docreport business_id=BIZ-001 as_of=not-a-date")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report") as mock_gen:
            asyncio.run(th.docreport_cmd(update, context))
        mock_gen.assert_not_called()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("as_of", text)

    def test_invalid_include_duplicates_shows_validation_error(self):
        update, context = _cmd("/docreport business_id=BIZ-001 include_duplicates=maybe")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("include_duplicates", text)

class TestDocreportSuccessfulReport(unittest.TestCase):
    def test_renders_business_and_as_of(self):
        update, context = _cmd("/docreport business_id=BIZ-001 as_of=2026-07-29")
        result = _result()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("BIZ-001", text)
        self.assertIn("2026-07-29", text)
        self.assertIn("(UTC)", text)

    def test_renders_total_documents(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result(summary=_summary(total_documents=42))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("42", text)

    def test_renders_all_required_sections(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        for section in (
            "Проверка:", "Качество данных:", "Требуют действия:",
            "Срок действия:", "Истечение:", "Дубликаты:",
        ):
            self.assertIn(section, text)

    def test_never_shows_document_id(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("DREG-", text)
        self.assertNotIn("Document ID", text)

    def test_never_shows_document_name_or_file_name(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn(".pdf", text)

    def test_warnings_shown_as_count_only_never_content(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result(warnings=("DUPLICATE_DOCUMENT_ID_REGISTRY:DREG-999",))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Предупреждения", text)
        self.assertIn("1", text)
        self.assertNotIn("DREG-999", text)

    def test_no_warnings_line_when_empty(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result(warnings=())
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Предупреждения", text)

    def test_zero_documents_renders_zero_totals(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result(summary=_summary(
            total_documents=0, review_unreviewed_count=0,
            requires_action_unknown_count=0, has_expiration_unknown_count=0,
            no_valid_until_count=0, new_document_count=0,
        ))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Всего документов: 0", text)


class TestDocreportErrorHandling(unittest.TestCase):
    def test_business_not_found_shows_distinct_message(self):
        update, context = _cmd("/docreport business_id=BIZ-404")
        result = _result(ok=False, error_code=ERROR_BUSINESS_NOT_FOUND, business_id="BIZ-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("BIZ-404", text)
        self.assertIn("не найден", text)

    def test_business_not_found_never_confused_with_zero_documents(self):
        update, context = _cmd("/docreport business_id=BIZ-404")
        result = _result(ok=False, error_code=ERROR_BUSINESS_NOT_FOUND, business_id="BIZ-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Всего документов", text)

    def test_invariant_failure_shows_safe_generic_message(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        result = _result(ok=False, error_code=ERROR_REPORT_INVARIANT_FAILED)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report", return_value=result):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("итогов не пройдена", text)
        self.assertNotIn("Всего документов", text)

    def test_sheets_quota_exceeded_shows_retry_message(self):
        from business_core.sheets import SheetsQuotaExceededError
        update, context = _cmd("/docreport business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report",
                   side_effect=SheetsQuotaExceededError("quota")):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("перегружен", text)

    def test_transient_read_error_shows_retry_message(self):
        from business_core.sheets import TransientSheetsReadError
        update, context = _cmd("/docreport business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report",
                   side_effect=TransientSheetsReadError("transient")):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Попробуйте позже", text)

    def test_unexpected_exception_shows_generic_error(self):
        update, context = _cmd("/docreport business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_report.generate_document_report",
                   side_effect=RuntimeError("boom")):
            asyncio.run(th.docreport_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Не удалось", text)


class TestDocreportCommandRegistration(unittest.TestCase):
    def test_docreport_registered_as_command_handler(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docreport", docreport_cmd)', source)


if __name__ == "__main__":
    unittest.main()
