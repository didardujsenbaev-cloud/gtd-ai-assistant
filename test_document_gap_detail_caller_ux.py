"""
Phase 16C.3: /docgap Telegram caller UX.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_gap_detail.generate_document_gap_detail at the
call site — never a live Sheets/network call.
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
from business_core.document_gap_detail import (
    DocumentGapDetailCriteria, DocumentGapDetail, DocumentGapDetailResult,
    ERROR_REQUIREMENT_NOT_FOUND, ERROR_AMBIGUOUS_REQUIREMENT_ID,
)
from business_core.document_coverage import (
    ERROR_ROADMAP_NOT_FOUND, ERROR_ROADMAP_MISSING_BUSINESS_ID,
    ERROR_UNKNOWN_ENGINE_STATUS, ERROR_COVERAGE_CONFIGURATION_ERROR, ERROR_COVERAGE_INVARIANT_FAILED,
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


def _detail(requirement_name="Топографическая съемка", stage_id="STAGE-011", required=True,
            blocking=True, minimum_count=1, base_status="missing", matched_document_count=0,
            canonical_document_count=0, quality_flags=(), **overrides):
    kwargs = dict(
        requirement_id="STAGE-011:DOC-001", requirement_name=requirement_name, stage_id=stage_id,
        required=required, blocking=blocking, minimum_count=minimum_count, base_status=base_status,
        matched_document_count=matched_document_count, canonical_document_count=canonical_document_count,
        exact_duplicate_matched_count=0, unmatched_document_count=0,
        fully_confirmed_count=0, needs_review_count=0, conflict_document_count=0,
        cache_warning_document_count=0, valid_expiry_count=0, expired_document_count=0,
        unknown_expiry_count=0, invalid_expiry_count=0, quality_flags=quality_flags,
    )
    kwargs.update(overrides)
    return DocumentGapDetail(**kwargs)


def _result(detail=None, ok=True, error_code="", roadmap_id="RM-003",
            requirement_id="STAGE-011:DOC-001", as_of="2026-07-29", warnings=()):
    criteria = DocumentGapDetailCriteria(roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of)
    return DocumentGapDetailResult(
        criteria=criteria, ok=ok, error_code=error_code,
        detail=detail if detail is not None else (_detail() if ok else None),
        warnings=tuple(warnings), generated_at="2026-07-29 10:00:00 UTC",
    )


class TestDocgapValidation(unittest.TestCase):
    def test_missing_roadmap_id_shows_validation_error(self):
        update, context = _cmd("/docgap requirement_id=STAGE-011:DOC-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("roadmap_id", text)
        self.assertIn("Пример", text)

    def test_missing_requirement_id_shows_validation_error(self):
        update, context = _cmd("/docgap roadmap_id=RM-003")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement_id", text)

    def test_unknown_parameter_shows_validation_error(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001 stage_id=STAGE-011")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("stage_id", text)

    def test_invalid_as_of_shows_validation_error_no_call(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001 as_of=bad")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail") as mock_gen:
            asyncio.run(th.docgap_cmd(update, context))
        mock_gen.assert_not_called()


class TestDocgapMissingRender(unittest.TestCase):
    def test_missing_detail_rendering(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(base_status="missing", minimum_count=1, matched_document_count=0))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Roadmap: RM-003", text)
        self.assertIn("STAGE-011", text)
        self.assertIn("Топографическая съемка", text)
        self.assertIn("отсутствует", text)
        self.assertIn("Подходящие документы не найдены", text)
        self.assertIn("блокирует завершение этапа", text)
        self.assertIn("/docgaps roadmap_id=RM-003", text)


class TestDocgapPartialRender(unittest.TestCase):
    def test_partial_detail_rendering(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(base_status="partial", minimum_count=2, matched_document_count=1))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("частично", text)
        self.assertIn("Найдено 1 из 2", text)


class TestDocgapPresentRender(unittest.TestCase):
    def test_present_needs_review_rendering(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-014:DOC-002")
        result = _result(detail=_detail(
            requirement_name="Нотариальное согласие соседей", stage_id="STAGE-014",
            base_status="present", minimum_count=1, matched_document_count=1,
            canonical_document_count=1, quality_flags=("needs_review",), needs_review_count=1,
        ))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("найдено", text)
        self.assertIn("Canonical документов: 1", text)
        self.assertIn("Требует проверки: 1", text)
        self.assertIn("Structured data не подтверждены полностью", text)

    def test_duplicate_only_explanation(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(
            base_status="present", minimum_count=1, matched_document_count=1,
            canonical_document_count=0, quality_flags=("duplicate_only",),
        ))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("точными дубликатами", text)

    def test_expired_explanation(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(
            base_status="present", minimum_count=1, matched_document_count=1,
            canonical_document_count=1, quality_flags=("expired",), expired_document_count=1,
        ))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Недостаточно документов с актуальным сроком", text)

    def test_no_empty_explanation_blocks(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(
            base_status="present", minimum_count=1, matched_document_count=1,
            canonical_document_count=1, quality_flags=(),
        ))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        for phrase in ("не подтверждены полностью", "конфликт между AI", "точными дубликатами",
                       "Недостаточно документов с актуальным", "требует дополнительной проверки",
                       "Есть некорректная дата"):
            self.assertNotIn(phrase, text)


class TestDocgapRequiredOptionalMessages(unittest.TestCase):
    def test_required_blocking_message(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(required=True, blocking=True))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("блокирует завершение этапа", text)

    def test_required_non_blocking_message(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(required=True, blocking=False))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не помечено как блокирующее", text)

    def test_optional_requirement_message(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail(required=False, blocking=False, base_status="optional_missing"))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("является опциональным", text)
        self.assertNotIn("блокирует завершение этапа", text)


class TestDocgapErrorHandling(unittest.TestCase):
    def test_requirement_not_found(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-999:DOC-999")
        result = _result(ok=False, error_code=ERROR_REQUIREMENT_NOT_FOUND, requirement_id="STAGE-999:DOC-999")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не найдено", text)
        self.assertNotIn("STAGE-999:DOC-999", text)  # user-supplied requirement_id never echoed

    def test_ambiguous_requirement_id(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(ok=False, error_code=ERROR_AMBIGUOUS_REQUIREMENT_ID)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("несколько требований", text)

    def test_roadmap_not_found(self):
        update, context = _cmd("/docgap roadmap_id=RM-404 requirement_id=STAGE-011:DOC-001")
        result = _result(ok=False, error_code=ERROR_ROADMAP_NOT_FOUND, roadmap_id="RM-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("RM-404", text)
        self.assertIn("не найден", text)

    def test_configuration_error_shows_safe_message(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(ok=False, error_code=ERROR_COVERAGE_CONFIGURATION_ERROR)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("ошибка", text)
        self.assertNotIn("Основной статус", text)

    def test_invariant_failure_shows_safe_message(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(ok=False, error_code=ERROR_COVERAGE_INVARIANT_FAILED)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("итогов не пройдена", text)
        self.assertNotIn("Основной статус", text)

    def test_sheets_quota_exceeded_shows_retry_message(self):
        from business_core.sheets import SheetsQuotaExceededError
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail",
                   side_effect=SheetsQuotaExceededError("quota")):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("перегружен", text)

    def test_unexpected_exception_shows_generic_error(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail",
                   side_effect=RuntimeError("boom")):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Не удалось", text)


class TestDocgapPrivacy(unittest.TestCase):
    def test_no_document_id_or_file_name_in_output(self):
        update, context = _cmd("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-001")
        result = _result(detail=_detail())
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=result):
            asyncio.run(th.docgap_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("DREG-", text)
        self.assertNotIn(".pdf", text)


class TestDocgapCommandRegistration(unittest.TestCase):
    def test_docgap_registered_as_command_handler(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docgap", docgap_cmd)', source)

    def test_docgaps_still_registered(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docgaps", docgaps_cmd)', source)

    def test_finddocs_and_docreport_still_registered(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("finddocs", finddocs_cmd)', source)
        self.assertIn('CommandHandler("docreport", docreport_cmd)', source)


if __name__ == "__main__":
    unittest.main()
