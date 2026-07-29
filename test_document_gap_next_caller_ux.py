"""
Phase 16C.6: /docgapnext Telegram caller UX.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_gap_next.generate_document_gap_next at the call
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
from business_core.document_gap_next import (
    DocumentGapNextCriteria, DocumentGapNextAction, DocumentGapNextResult,
    ERROR_UNSUPPORTED_BASE_STATUS, ERROR_UNSUPPORTED_QUALITY_FLAG,
)
from business_core.document_gap_detail import (
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


def _action(action_code, *lines):
    return DocumentGapNextAction(action_code=action_code, instruction_lines=lines)


def _result(primary=None, secondary=(), ok=True, error_code="", roadmap_id="RM-003",
            requirement_id="STAGE-011:DOC-008", as_of="2026-07-29",
            requirement_name="Топографическая съемка", stage_id="STAGE-011",
            base_status="missing", blocking=True, required=True, quality_flags=()):
    criteria = DocumentGapNextCriteria(roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of)
    return DocumentGapNextResult(
        criteria=criteria, ok=ok, error_code=error_code,
        requirement_name=requirement_name if ok else "", stage_id=stage_id if ok else "",
        base_status=base_status if ok else "", blocking=blocking if ok else False,
        required=required if ok else False, quality_flags=quality_flags if ok else (),
        primary_action=primary if ok else None, secondary_actions=secondary if ok else (),
        warnings=(), generated_at="2026-07-29 10:00:00 UTC",
    )


class TestDocgapnextValidation(unittest.TestCase):
    def test_missing_roadmap_id_shows_validation_error(self):
        update, context = _cmd("/docgapnext requirement_id=STAGE-011:DOC-008")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("roadmap_id", text)
        self.assertIn("Пример", text)

    def test_missing_requirement_id_shows_validation_error(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement_id", text)

    def test_unknown_parameter_shows_validation_error(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008 stage_id=STAGE-011")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("stage_id", text)

    def test_invalid_as_of_shows_validation_error_no_call(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008 as_of=bad")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next") as mock_gen:
            asyncio.run(th.docgapnext_cmd(update, context))
        mock_gen.assert_not_called()


class TestDocgapnextMissingRender(unittest.TestCase):
    def test_missing_action_rendering(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(primary=_action(
            "OBTAIN_MISSING_DOCUMENT",
            "Получить требуемый документ.",
            "Загрузить его в систему.",
            "Повторно проверить требование через /docgap.",
        ), base_status="missing")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("📌 Следующий шаг по требованию", text)
        self.assertIn("Roadmap: RM-003", text)
        self.assertIn("STAGE-011", text)
        self.assertIn("Топографическая съемка", text)
        self.assertIn("отсутствует", text)
        self.assertIn("Получить требуемый документ.", text)
        self.assertIn("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008", text)
        self.assertIn("блокирует завершение этапа", text)
        self.assertIn("/missingdocs roadmap_id=RM-003", text)


class TestDocgapnextMultipleFlagsRender(unittest.TestCase):
    def test_primary_and_secondary_rendered_separately(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-014:DOC-012")
        result = _result(
            primary=_action(
                "OBTAIN_CURRENT_DOCUMENT",
                "Получить актуальную версию документа или продлить срок действия.",
                "Загрузить актуальный документ.",
            ),
            secondary=(_action("CONFIRM_STRUCTURED_DATA", "Проверить извлечённые structured data.",
                                "Подтвердить или исправить значения."),),
            base_status="present", requirement_name="Нотариальное согласие соседей",
            stage_id="STAGE-014", requirement_id="STAGE-014:DOC-012", quality_flags=("expired", "needs_review"),
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Основное действие:", text)
        self.assertIn("Дополнительно:", text)
        self.assertIn("Получить актуальную версию документа", text)
        self.assertIn("Проверить извлечённые structured data.", text)
        # follow-up command must appear only once, in its own block
        self.assertEqual(text.count("/docgap roadmap_id=RM-003 requirement_id=STAGE-014:DOC-012"), 1)


class TestDocgapnextBlockingOptionalMessaging(unittest.TestCase):
    def test_required_blocking(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), required=True, blocking=True)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("⚠️ Требование блокирует завершение этапа.", text)

    def test_required_non_blocking(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), required=True, blocking=False)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не помечено как блокирующее", text)

    def test_optional_message(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(
            primary=_action("OPTIONAL_DOCUMENT_NOT_PROVIDED", "step"),
            required=False, blocking=False, base_status="optional_missing",
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Требование является опциональным.", text)
        self.assertNotIn("блокирует завершение этапа", text)


class TestDocgapnextErrorHandling(unittest.TestCase):
    def test_roadmap_not_found(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-404 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_ROADMAP_NOT_FOUND, roadmap_id="RM-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("RM-404", text)
        self.assertIn("не найден", text)

    def test_requirement_not_found_never_echoes_input_id(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-999:DOC-999")
        result = _result(ok=False, error_code=ERROR_REQUIREMENT_NOT_FOUND, requirement_id="STAGE-999:DOC-999")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не найдено", text)
        self.assertNotIn("STAGE-999:DOC-999", text)

    def test_ambiguous_requirement_id(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_AMBIGUOUS_REQUIREMENT_ID)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("несколько требований", text)

    def test_configuration_error_safe_message(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_COVERAGE_CONFIGURATION_ERROR)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("ошибка", text)
        self.assertNotIn("Что сделать", text)

    def test_invariant_failure_safe_message(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_COVERAGE_INVARIANT_FAILED)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не пройдена", text)

    def test_unsupported_base_status_safe_message_no_raw_value(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_UNSUPPORTED_BASE_STATUS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("неподдерживаемое состояние", text)
        self.assertNotIn("not_applicable", text)

    def test_unsupported_quality_flag_safe_message(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(ok=False, error_code=ERROR_UNSUPPORTED_QUALITY_FLAG)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("неподдерживаемое состояние", text)

    def test_sheets_quota_exceeded_shows_retry_message(self):
        from business_core.sheets import SheetsQuotaExceededError
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next",
                   side_effect=SheetsQuotaExceededError("quota")):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("перегружен", text)

    def test_unexpected_exception_generic_error(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next",
                   side_effect=RuntimeError("boom")):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Не удалось", text)


class TestDocgapnextPrivacy(unittest.TestCase):
    def test_no_document_id_or_file_name(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("DREG-", text)
        self.assertNotIn(".pdf", text)


class TestDocgapnextCommandRegistration(unittest.TestCase):
    def test_docgapnext_registered(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docgapnext", docgapnext_cmd)', source)

    def test_docgap_docgaps_still_registered(self):
        import inspect
        source = inspect.getsource(th)
        self.assertIn('CommandHandler("docgap", docgap_cmd)', source)
        self.assertIn('CommandHandler("docgaps", docgaps_cmd)', source)


if __name__ == "__main__":
    unittest.main()
