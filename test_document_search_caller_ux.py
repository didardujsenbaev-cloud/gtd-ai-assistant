"""
Phase 16B.5: /finddocs Telegram caller UX.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_search.search_documents at the call site —
never a live Sheets/network call. Mirrors test_document_caller_ux.py's
own _cmd()/_upd() helper pattern.
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
from business_core.document_search import DocumentSearchCriteria, DocumentSearchItem, DocumentSearchResult


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


def _item(document_id="DREG-004", document_name="Техпаспорт", file_name="secret_scan_2026.pdf",
          effective_document_date="2026-07-22", document_date_source="human",
          effective_direction="internal", direction_source="human",
          effective_requires_action=None, review_status="partially_confirmed",
          has_conflict=False, cache_warning=False):
    return DocumentSearchItem(
        document_id=document_id, document_name=document_name, file_name=file_name,
        business_id="BIZ-001", effective_document_date=effective_document_date,
        document_date_source=document_date_source, effective_direction=effective_direction,
        direction_source=direction_source, effective_requires_action=effective_requires_action,
        effective_has_expiration=None, review_status=review_status, review_version=2,
        has_conflict=has_conflict, duplicate_status="", duplicate_of_document_id="",
        cache_warning=cache_warning,
    )


def _result(items=(), total_matches=None, offset=0, limit=10, warnings=()):
    total = total_matches if total_matches is not None else len(items)
    criteria = DocumentSearchCriteria(business_id="BIZ-001")
    return DocumentSearchResult(
        criteria=criteria, total_matches=total, returned_count=len(items),
        offset=offset, limit=limit, items=tuple(items), warnings=tuple(warnings),
    )


class TestFinddocsCmd(unittest.TestCase):
    def test_missing_business_id_shows_validation_error(self):
        update, context = _cmd("/finddocs date_from=2026-07-01")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("business_id", text)
        self.assertIn("Пример", text)

    def test_unknown_parameter_shows_validation_error(self):
        update, context = _cmd("/finddocs business_id=BIZ-001 object_id=OBJ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("object_id", text)

    def test_limit_above_max_shows_validation_error_no_search_call(self):
        update, context = _cmd("/finddocs business_id=BIZ-001 limit=21")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents") as mock_search:
            asyncio.run(th.finddocs_cmd(update, context))
        mock_search.assert_not_called()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("20", text)

    def test_successful_search_renders_items(self):
        update, context = _cmd("/finddocs business_id=BIZ-001 date_from=2026-07-01")
        result = _result(items=[_item()])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Найдено документов: 1", text)
        self.assertIn("DREG-004", text)
        self.assertIn("Техпаспорт", text)
        self.assertIn("Дата: 2026-07-22 ✅", text)
        self.assertIn("Направление: внутренний ✅", text)

    def test_file_name_never_shown(self):
        """J: file_name may contain PII — never rendered."""
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item(file_name="Иванов_паспорт_скан.pdf")])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Иванов_паспорт_скан.pdf", text)
        self.assertNotIn(".pdf", text)

    def test_ai_source_marker(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item(document_date_source="ai", direction_source="ai")])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("🤖", text)

    def test_conflict_warning_shown(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item(has_conflict=True)])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Есть конфликт AI и подтверждённых данных", text)

    def test_cache_warning_shown_instead_of_conflict(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item(cache_warning=True, has_conflict=None)])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Состояние подтверждений требует проверки", text)
        self.assertNotIn("Есть конфликт", text)

    def test_no_results_message(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Документы не найдены", text)

    def test_pagination_hint_shown_when_more_results(self):
        result = _result(items=[_item()], total_matches=15, offset=0, limit=1)
        update, context = _cmd("/finddocs business_id=BIZ-001 limit=1")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Следующая страница", text)
        self.assertIn("offset=1", text)

    def test_no_pagination_hint_when_all_shown(self):
        result = _result(items=[_item()], total_matches=1)
        update, context = _cmd("/finddocs business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Следующая страница", text)

    def test_docanalysis_hint_shown(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item()])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("/docanalysis document_id=", text)

    def test_business_id_not_repeated_per_line(self):
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item(), _item(document_id="DREG-005")])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("BIZ-001", text)

    def test_sensitive_fields_absent(self):
        """No extracted_fields, Confirmed Fields JSON, Review ID,
        Mutation ID, actor, hash ever appear."""
        update, context = _cmd("/finddocs business_id=BIZ-001")
        result = _result(items=[_item()])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_search.search_documents", return_value=result):
            asyncio.run(th.finddocs_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        for forbidden in ("Confirmed Fields JSON", "Review ID", "Mutation ID", "didar", "extracted_fields"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
