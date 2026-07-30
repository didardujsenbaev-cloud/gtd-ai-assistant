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
            base_status="missing", blocking=True, required=True, quality_flags=(),
            business_id="BIZ-001", document_template_id="DOC-008"):
    criteria = DocumentGapNextCriteria(roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of)
    return DocumentGapNextResult(
        criteria=criteria, ok=ok, error_code=error_code,
        requirement_name=requirement_name if ok else "", stage_id=stage_id if ok else "",
        base_status=base_status if ok else "", blocking=blocking if ok else False,
        required=required if ok else False, quality_flags=quality_flags if ok else (),
        primary_action=primary if ok else None, secondary_actions=secondary if ok else (),
        warnings=(), generated_at="2026-07-29 10:00:00 UTC",
        business_id=business_id if ok else "", document_template_id=document_template_id if ok else "",
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
            "После загрузки обновить проверку требования.",
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
        self.assertEqual(text.count("/docgap"), 1)
        self.assertIn("Повторно проверить:", text)
        self.assertNotIn("Повторная проверка:", text)
        self.assertNotIn("Повторно проверить требование:", text)


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
        self.assertEqual(text.count("/docgap"), 1)
        self.assertIn("Повторно проверить:", text)
        self.assertNotIn("Повторная проверка:", text)
        self.assertNotIn("Повторно проверить требование:", text)


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

    def test_all_error_responses_never_show_followup_command(self):
        error_codes = [
            ERROR_ROADMAP_NOT_FOUND, ERROR_ROADMAP_MISSING_BUSINESS_ID,
            ERROR_REQUIREMENT_NOT_FOUND, ERROR_AMBIGUOUS_REQUIREMENT_ID,
            ERROR_UNKNOWN_ENGINE_STATUS, ERROR_COVERAGE_CONFIGURATION_ERROR,
            ERROR_COVERAGE_INVARIANT_FAILED, ERROR_UNSUPPORTED_BASE_STATUS,
            ERROR_UNSUPPORTED_QUALITY_FLAG,
        ]
        for code in error_codes:
            update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
            result = _result(ok=False, error_code=code)
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
                asyncio.run(th.docgapnext_cmd(update, context))
            text = update.message.reply_text.call_args[0][0]
            self.assertNotIn("/docgap", text, msg=f"error_code={code}")
            self.assertNotIn("Повторно проверить:", text, msg=f"error_code={code}")

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


class TestDocgapnextUploadNavigation(unittest.TestCase):
    """Phase 16C.8.2C: ready-to-copy /uploaddoc command shown only when
    primary_action.action_code is upload-eligible AND business_id/
    roadmap_id/stage_id/document_template_id are all non-empty."""

    def _run(self, result):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result):
            asyncio.run(th.docgapnext_cmd(update, context))
        return update.message.reply_text.call_args[0][0]

    # ── visibility matrix: shown ──

    def test_missing_shows_exact_command(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    def test_partial_shows_exact_command(self):
        text = self._run(_result(primary=_action("OBTAIN_REMAINING_DOCUMENTS", "step")))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    def test_optional_missing_shows_exact_command(self):
        text = self._run(_result(primary=_action("OPTIONAL_DOCUMENT_NOT_PROVIDED", "step")))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    def test_expired_shows_exact_command(self):
        text = self._run(_result(primary=_action("OBTAIN_CURRENT_DOCUMENT", "step"), base_status="present"))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    def test_duplicate_only_shows_exact_command(self):
        text = self._run(_result(primary=_action("UPLOAD_CANONICAL_DOCUMENT", "step"), base_status="present"))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    # ── visibility matrix: hidden ──

    def test_present_clean_hides_command(self):
        text = self._run(_result(primary=_action("NO_ACTION_REQUIRED", "step"), base_status="present"))
        self.assertNotIn("/uploaddoc", text)
        self.assertNotIn("Загрузить документ:", text)

    def test_needs_review_hides_command(self):
        text = self._run(_result(primary=_action("CONFIRM_STRUCTURED_DATA", "step"), base_status="present"))
        self.assertNotIn("/uploaddoc", text)

    def test_conflict_hides_command(self):
        text = self._run(_result(primary=_action("RESOLVE_STRUCTURED_DATA_CONFLICT", "step"), base_status="present"))
        self.assertNotIn("/uploaddoc", text)

    def test_invalid_expiry_hides_command(self):
        text = self._run(_result(primary=_action("FIX_EXPIRY_DATE", "step"), base_status="present"))
        self.assertNotIn("/uploaddoc", text)

    def test_cache_warning_hides_command(self):
        text = self._run(_result(primary=_action("RECHECK_QUALITY_DATA", "step"), base_status="present"))
        self.assertNotIn("/uploaddoc", text)

    def test_primary_action_none_hides_command(self):
        # ok=False forces primary_action=None via _result()'s own logic.
        text = self._run(_result(ok=False, error_code="REQUIREMENT_NOT_FOUND"))
        self.assertNotIn("/uploaddoc", text)

    # ── fail-closed on missing typed fields ──

    def test_empty_business_id_hides_full_block(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), business_id=""))
        self.assertNotIn("/uploaddoc", text)
        self.assertNotIn("Загрузить документ:", text)

    def test_empty_roadmap_id_hides_full_block(self):
        result = _result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), roadmap_id="")
        # roadmap_id empty would normally fail earlier validation, but
        # exercise the renderer directly to prove the fail-closed guard
        # itself (not just upstream validation) hides the block.
        text = th._render_document_gap_next(result)
        self.assertNotIn("/uploaddoc", text)
        self.assertNotIn("Загрузить документ:", text)

    def test_empty_stage_id_hides_full_block(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), stage_id=""))
        self.assertNotIn("/uploaddoc", text)
        self.assertNotIn("Загрузить документ:", text)

    def test_empty_document_template_id_hides_full_block(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), document_template_id=""))
        self.assertNotIn("/uploaddoc", text)
        self.assertNotIn("Загрузить документ:", text)

    def test_no_partial_command_on_missing_field(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), business_id=""))
        self.assertNotIn("business=", text)
        self.assertNotIn("roadmap=", text)
        self.assertNotIn("template=", text)

    # ── command contract ──

    def test_command_uses_canonical_keys(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertIn("business=BIZ-001", text)
        self.assertIn("roadmap=RM-003", text)
        self.assertIn("stage=STAGE-011", text)
        self.assertIn("template=DOC-008", text)

    def test_no_forbidden_id_suffix_keys(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        uploaddoc_line = next(line for line in text.splitlines() if line.strip().startswith("/uploaddoc"))
        self.assertNotIn("business_id=", uploaddoc_line)
        self.assertNotIn("roadmap_id=", uploaddoc_line)
        self.assertNotIn("stage_id=", uploaddoc_line)
        self.assertNotIn("document_template_id=", uploaddoc_line)

    def test_no_requirement_id_argument(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        uploaddoc_line = next(line for line in text.splitlines() if line.strip().startswith("/uploaddoc"))
        self.assertNotIn("requirement_id=", uploaddoc_line)

    def test_no_client_object_name_notes_args(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        uploaddoc_line = next(line for line in text.splitlines() if line.strip().startswith("/uploaddoc"))
        for forbidden in ("client=", "object=", "name=", "notes="):
            self.assertNotIn(forbidden, uploaddoc_line)

    def test_exact_business_id(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), business_id="BIZ-777"))
        self.assertIn("business=BIZ-777", text)

    def test_exact_roadmap_id(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), roadmap_id="RM-999"))
        self.assertIn("roadmap=RM-999", text)

    def test_exact_stage_id(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), stage_id="STAGE-999"))
        self.assertIn("stage=STAGE-999", text)

    def test_exact_template_id(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"), document_template_id="DOC-999"))
        self.assertIn("template=DOC-999", text)

    def test_command_exactly_once(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertEqual(text.count("/uploaddoc"), 1)

    def test_label_exactly_once(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertEqual(text.count("Загрузить документ:"), 1)

    # ── placement ──

    def test_placement_after_actions_before_docgap(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "Получить документ.")))
        instruction_pos = text.index("Получить документ.")
        upload_label_pos = text.index("Загрузить документ:")
        upload_cmd_pos = text.index("/uploaddoc")
        docgap_label_pos = text.index("Повторно проверить:")
        docgap_cmd_pos = text.index("/docgap roadmap_id=")
        self.assertLess(instruction_pos, upload_label_pos)
        self.assertLess(upload_label_pos, upload_cmd_pos)
        self.assertLess(upload_cmd_pos, docgap_label_pos)
        self.assertLess(docgap_label_pos, docgap_cmd_pos)

    # ── multi-flag combinations (§7) ──

    def test_duplicate_only_plus_expired_shows_command(self):
        text = self._run(_result(
            primary=_action("UPLOAD_CANONICAL_DOCUMENT", "step"),
            secondary=(_action("OBTAIN_CURRENT_DOCUMENT", "step2"),),
            base_status="present", quality_flags=("duplicate_only", "expired"),
        ))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)
        self.assertEqual(text.count("/uploaddoc"), 1)

    def test_expired_plus_needs_review_shows_command(self):
        text = self._run(_result(
            primary=_action("OBTAIN_CURRENT_DOCUMENT", "step"),
            secondary=(_action("CONFIRM_STRUCTURED_DATA", "step2"),),
            base_status="present", quality_flags=("expired", "needs_review"),
        ))
        self.assertIn("/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008", text)

    def test_conflict_plus_needs_review_hides_command(self):
        text = self._run(_result(
            primary=_action("RESOLVE_STRUCTURED_DATA_CONFLICT", "step"),
            secondary=(_action("CONFIRM_STRUCTURED_DATA", "step2"),),
            base_status="present", quality_flags=("conflict", "needs_review"),
        ))
        self.assertNotIn("/uploaddoc", text)

    def test_needs_review_plus_invalid_expiry_hides_command(self):
        text = self._run(_result(
            primary=_action("CONFIRM_STRUCTURED_DATA", "step"),
            secondary=(_action("FIX_EXPIRY_DATE", "step2"),),
            base_status="present", quality_flags=("needs_review", "invalid_expiry"),
        ))
        self.assertNotIn("/uploaddoc", text)

    def test_secondary_upload_eligible_action_does_not_trigger_block_alone(self):
        """Invariant guard (§4): even if a secondary action happens to
        be upload-eligible, the block must not appear unless the
        PRIMARY action itself is upload-eligible."""
        text = self._run(_result(
            primary=_action("CONFIRM_STRUCTURED_DATA", "step"),
            secondary=(_action("OBTAIN_CURRENT_DOCUMENT", "step2"),),
            base_status="present", quality_flags=("needs_review", "expired"),
        ))
        self.assertNotIn("/uploaddoc", text)

    # ── every typed error path hides /uploaddoc (§9) ──

    def test_every_typed_error_hides_uploaddoc(self):
        error_codes = [
            ERROR_ROADMAP_NOT_FOUND, ERROR_ROADMAP_MISSING_BUSINESS_ID,
            ERROR_REQUIREMENT_NOT_FOUND, ERROR_AMBIGUOUS_REQUIREMENT_ID,
            ERROR_UNKNOWN_ENGINE_STATUS, ERROR_COVERAGE_CONFIGURATION_ERROR,
            ERROR_COVERAGE_INVARIANT_FAILED,
        ]
        for code in error_codes:
            text = self._run(_result(ok=False, error_code=code))
            self.assertNotIn("/uploaddoc", text, msg=f"error_code={code}")

    # ── privacy ──

    def test_privacy_no_document_id_or_drive_url(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertNotIn("DREG-", text)
        self.assertNotIn("drive.google.com", text)
        self.assertNotIn(".pdf", text)

    # ── message splitting ──

    def test_long_ids_command_stays_one_line(self):
        text = self._run(_result(
            primary=_action("OBTAIN_MISSING_DOCUMENT", "step"),
            business_id="BIZ-00000000001-VERY-LONG-IDENTIFIER",
            roadmap_id="RM-00000000001-VERY-LONG-IDENTIFIER-VALUE",
            stage_id="STAGE-00000000001-VERY-LONG-IDENTIFIER-VALUE",
            document_template_id="DOC-00000000001-VERY-LONG-IDENTIFIER-VALUE",
        ))
        uploaddoc_lines = [line for line in text.splitlines() if line.strip().startswith("/uploaddoc")]
        self.assertEqual(len(uploaddoc_lines), 1)
        self.assertIn("business=BIZ-00000000001-VERY-LONG-IDENTIFIER", uploaddoc_lines[0])
        self.assertIn("template=DOC-00000000001-VERY-LONG-IDENTIFIER-VALUE", uploaddoc_lines[0])

    # ── existing behavior unchanged ──

    def test_existing_docgap_exact_once_unchanged(self):
        text = self._run(_result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step")))
        self.assertEqual(text.count("/docgap roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008"), 1)

    def test_zero_writes(self):
        import inspect
        source = inspect.getsource(th._render_document_gap_next)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                          "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)

    def test_call_budget_unchanged(self):
        update, context = _cmd("/docgapnext roadmap_id=RM-003 requirement_id=STAGE-011:DOC-008")
        result = _result(primary=_action("OBTAIN_MISSING_DOCUMENT", "step"))
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_gap_next.generate_document_gap_next", return_value=result) as mock_gen:
            asyncio.run(th.docgapnext_cmd(update, context))
            mock_gen.assert_called_once()


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
