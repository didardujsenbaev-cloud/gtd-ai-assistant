"""
Phase 16C.2: /docgaps Telegram caller UX.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_coverage.generate_document_coverage at the call
site — never a live Sheets/network call.
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
from business_core.document_coverage import (
    DocumentCoverageCriteria, DocumentCoverageItem, DocumentCoverageSummary, DocumentCoverageResult,
    ERROR_ROADMAP_NOT_FOUND, ERROR_ROADMAP_MISSING_BUSINESS_ID,
    ERROR_STAGE_NOT_FOUND, ERROR_STAGE_NOT_IN_ROADMAP,
    ERROR_COVERAGE_CONFIGURATION_ERROR, ERROR_COVERAGE_INVARIANT_FAILED,
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


def _item(requirement_name="Технический паспорт", stage_id="STAGE-019", required=True, blocking=True,
          minimum_count=1, base_status="missing", matched_document_count=0, canonical_document_count=0,
          quality_flags=()):
    return DocumentCoverageItem(
        requirement_id="STAGE-019:DOC-001", requirement_name=requirement_name, stage_id=stage_id,
        required=required, blocking=blocking, minimum_count=minimum_count, base_status=base_status,
        matched_document_count=matched_document_count, canonical_document_count=canonical_document_count,
        exact_duplicate_matched_count=0, unmatched_document_count=0,
        quality_flags=quality_flags,
    )


def _summary(total_requirements=1, **overrides):
    kwargs = dict(
        total_requirements=total_requirements, required_count=total_requirements, optional_count=0,
        present_count=0, missing_count=total_requirements, partial_count=0, optional_missing_count=0,
        blocking_missing_count=total_requirements, needs_review_count=0, conflict_count=0,
        expired_count=0, duplicate_only_count=0, cache_warning_count=0, invalid_expiry_count=0,
        unmatched_document_count=0,
    )
    kwargs.update(overrides)
    return DocumentCoverageSummary(**kwargs)


def _result(items=(), summary=None, ok=True, error_code="", roadmap_id="RM-003", stage_id="",
            as_of="2026-07-29", warnings=()):
    criteria = DocumentCoverageCriteria(roadmap_id=roadmap_id, stage_id=stage_id, as_of=as_of)
    return DocumentCoverageResult(
        criteria=criteria, ok=ok, error_code=error_code,
        summary=summary if summary is not None else (_summary() if ok else None),
        items=tuple(items), warnings=tuple(warnings), generated_at="2026-07-29 10:00:00 UTC",
    )


class TestDocgapsValidation(unittest.TestCase):
    def test_missing_roadmap_id_shows_validation_error(self):
        update, context = _cmd("/docgaps stage_id=STAGE-019")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("roadmap_id", text)
        self.assertIn("Пример", text)

    def test_unknown_parameter_shows_validation_error(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003 object_id=OBJ-1")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("object_id", text)

    def test_invalid_as_of_shows_validation_error_no_coverage_call(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003 as_of=bad-date")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage") as mock_gen:
            asyncio.run(th.docgaps_cmd(update, context))
        mock_gen.assert_not_called()
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("as_of", text)


class TestDocgapsSuccessfulReport(unittest.TestCase):
    def test_renders_roadmap_and_summary(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(items=[_item()])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("RM-003", text)
        self.assertIn("(UTC)", text)
        self.assertIn("Итого требований: 1", text)

    def test_missing_item_rendered_under_ne_hvataet(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(items=[_item(base_status="missing")])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Не хватает:", text)
        self.assertIn("Технический паспорт", text)
        self.assertIn("STAGE-019", text)

    def test_partial_item_shows_found_of_minimum(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        item = _item(base_status="partial", matched_document_count=1, canonical_document_count=1, minimum_count=2)
        result = _result(items=[item], summary=_summary(missing_count=0, partial_count=1))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("найдено 1 из 2", text)

    def test_flagged_present_item_shown_under_trebuyut_vnimaniya(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        item = _item(base_status="present", quality_flags=("needs_review", "expired"))
        result = _result(items=[item], summary=_summary(missing_count=0, present_count=1))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Требуют внимания:", text)
        self.assertIn("не подтверждён полностью", text)
        self.assertIn("срок истёк", text)

    def test_clean_present_item_never_individually_rendered(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        item = _item(base_status="present", quality_flags=(), requirement_name="Чистый документ")
        result = _result(items=[item], summary=_summary(missing_count=0, present_count=1))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("Чистый документ", text)

    def test_never_shows_document_id_or_file_name(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(items=[_item()])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("DREG-", text)
        self.assertNotIn(".pdf", text)

    def test_warnings_shown_as_count_only(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(items=[_item()], warnings=("SOME_SAFE_CODE",))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Предупреждения", text)
        self.assertIn("1", text)


class TestDocgapsErrorHandling(unittest.TestCase):
    def test_roadmap_not_found(self):
        update, context = _cmd("/docgaps roadmap_id=RM-404")
        result = _result(ok=False, error_code=ERROR_ROADMAP_NOT_FOUND, roadmap_id="RM-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("RM-404", text)
        self.assertIn("не найден", text)

    def test_roadmap_missing_business_id(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(ok=False, error_code=ERROR_ROADMAP_MISSING_BUSINESS_ID)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Business ID", text)

    def test_stage_not_found(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003 stage_id=STAGE-999")
        result = _result(ok=False, error_code=ERROR_STAGE_NOT_FOUND, stage_id="STAGE-999")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("STAGE-999", text)
        self.assertIn("не найден", text)

    def test_stage_not_in_roadmap(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003 stage_id=STAGE-001")
        result = _result(ok=False, error_code=ERROR_STAGE_NOT_IN_ROADMAP, stage_id="STAGE-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не принадлежит", text)

    def test_invariant_failure_shows_safe_generic_message_no_partial_totals(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(ok=False, error_code=ERROR_COVERAGE_INVARIANT_FAILED)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("итогов не пройдена", text)
        self.assertNotIn("Итого требований", text)

    def test_configuration_error_shows_safe_message_no_raw_data(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        result = _result(
            ok=False, error_code=ERROR_COVERAGE_CONFIGURATION_ERROR,
            warnings=("REQUIREMENTS_CONFIGURATION_ERROR",),
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage", return_value=result):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("ошибка", text)
        self.assertNotIn("Итого требований", text)
        self.assertNotIn("REL-", text)
        self.assertNotIn("REQUIREMENTS_CONFIGURATION_ERROR", text)

    def test_sheets_quota_exceeded_shows_retry_message(self):
        from business_core.sheets import SheetsQuotaExceededError
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage",
                   side_effect=SheetsQuotaExceededError("quota")):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("перегружен", text)

    def test_unexpected_exception_shows_generic_error(self):
        update, context = _cmd("/docgaps roadmap_id=RM-003")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_coverage.generate_document_coverage",
                   side_effect=RuntimeError("boom")):
            asyncio.run(th.docgaps_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Не удалось", text)


class TestDocgapsCommandRegistration(unittest.TestCase):
    def test_docgaps_registered_as_command_handler(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docgaps", docgaps_cmd)', source)


if __name__ == "__main__":
    unittest.main()
