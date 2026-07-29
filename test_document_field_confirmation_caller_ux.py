"""
Phase 16B.3: Human Confirmation of Structured Document Fields —
Telegram caller UX for /reviewdoc, /confirmdocfield, /rejectdocfield,
/cleardocfield.

Pure presentation-layer + async-command-dispatch tests: mocks
business_core.document_query.get_document_analysis and
business_core.document_confirmation.confirm_field/reject_field/
clear_field at the call site — never a live Sheets/network call.
Mirrors test_document_caller_ux.py's own _cmd()/_upd() helper pattern.
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


def _fake_result(**kw):
    from business_core.document_query import DocumentAnalysisResult
    defaults = dict(status="completed", document_id="DREG-004", review_status="unreviewed",
                    review_version=0, effective_fields={})
    defaults.update(kw)
    return DocumentAnalysisResult(**defaults)


def _effective(value, source="ai", conflict=False, review_field_status="unreviewed", ai_value=None):
    return {"effective_value": value, "source": source, "conflict": conflict,
            "ai_value": ai_value if ai_value is not None else value,
            "review_field_status": review_field_status}


class TestReviewdocCmd(unittest.TestCase):
    def test_review_unreviewed_document(self):
        """п.1."""
        update, context = _cmd("/reviewdoc document_id=DREG-004")
        result = _fake_result(effective_fields={
            "document_number": _effective(""), "document_date": _effective("2026-07-22"),
            "issued_by": _effective(""), "valid_from": _effective(""), "valid_until": _effective(""),
            "has_expiration": _effective(""), "direction": _effective("internal"),
            "requires_action": _effective(""),
        })
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_query.get_document_analysis", return_value=result):
            asyncio.run(th.reviewdoc_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Проверка реквизитов", text)
        self.assertIn("Дата документа: 2026-07-22", text)
        self.assertIn("🤖 AI, не проверено", text)
        self.assertIn("не проверено", text)  # aggregate status
        self.assertIn("Версия: 0", text)

    def test_confirmed_field_shows_checkmark(self):
        update, context = _cmd("/reviewdoc document_id=DREG-004")
        result = _fake_result(review_status="partially_confirmed", review_version=1, effective_fields={
            "document_number": _effective(""), "document_date": _effective("2026-07-22", source="confirmed",
                                                                             review_field_status="confirmed"),
            "issued_by": _effective(""), "valid_from": _effective(""), "valid_until": _effective(""),
            "has_expiration": _effective(""), "direction": _effective("internal"),
            "requires_action": _effective(""),
        })
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_query.get_document_analysis", return_value=result):
            asyncio.run(th.reviewdoc_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ подтверждено", text)

    def test_rejected_field_shows_cross(self):
        update, context = _cmd("/reviewdoc document_id=DREG-004")
        result = _fake_result(effective_fields={
            "document_number": _effective(""), "document_date": _effective(""),
            "issued_by": _effective(""), "valid_from": _effective(""), "valid_until": _effective(""),
            "has_expiration": _effective(""),
            "direction": _effective("", source="none", review_field_status="rejected"),
            "requires_action": _effective(""),
        })
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_query.get_document_analysis", return_value=result):
            asyncio.run(th.reviewdoc_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("❌ отклонено", text)

    def test_conflict_shown(self):
        """Reanalysis conflict is surfaced without any automatic change."""
        update, context = _cmd("/reviewdoc document_id=DREG-004")
        result = _fake_result(effective_fields={
            "document_number": _effective(""),
            "document_date": _effective("2026-07-22", source="confirmed", conflict=True,
                                         review_field_status="confirmed", ai_value="2026-07-23"),
            "issued_by": _effective(""), "valid_from": _effective(""), "valid_until": _effective(""),
            "has_expiration": _effective(""), "direction": _effective("internal"),
            "requires_action": _effective(""),
        })
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_query.get_document_analysis", return_value=result):
            asyncio.run(th.reviewdoc_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("2026-07-22", text)  # effective (confirmed) value shown
        self.assertIn("новое AI-значение отличается: 2026-07-23", text)

    def test_missing_document_id(self):
        update, context = _cmd("/reviewdoc")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.reviewdoc_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Укажи document_id", text)


class TestConfirmdocfieldCmd(unittest.TestCase):
    def test_confirm_success_shows_new_version(self):
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=document_date value=2026-07-22 expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": True, "code": "OK", "error": None, "review_version": 1,
                 "confirmed_fields": {"document_date": {"value": "2026-07-22"}},
             }) as mock_confirm:
            asyncio.run(th.confirmdocfield_cmd(update, context))
        mock_confirm.assert_called_once_with("DREG-004", "document_date", "2026-07-22", "didar", 0)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Новая версия: 1", text)

    def test_field_not_allowed_lists_whitelist(self):
        """п.7."""
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=owner_iin value=123 expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": False, "code": "FIELD_NOT_ALLOWED", "error": "не разрешено",
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("не разрешено", text)
        self.assertIn("document_date", text)  # whitelist shown

    def test_version_conflict_shows_actual_version(self):
        """п.19."""
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=5"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": False, "code": "VERSION_CONFLICT", "review_version": 2,
                 "error": "stale",
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("2", text)
        self.assertIn("/reviewdoc document_id=DREG-004", text)

    def test_missing_params_shows_usage(self):
        update, context = _cmd("/confirmdocfield document_id=DREG-004")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Использование", text)

    def test_invalid_expected_version_rejected(self):
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=abc"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("целым числом", text)

    def test_audit_append_failed_never_says_success(self):
        """п.40: an AUDIT_APPEND_FAILED result must never render as a
        success message."""
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": False, "code": "AUDIT_APPEND_FAILED", "error": "audit failed",
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", text)
        self.assertIn("НЕ сохранено", text)


class TestConfirmdocfieldCmdNewCodes(unittest.TestCase):
    def test_idempotent_replay_shown_distinctly(self):
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": True, "code": "OK_IDEMPOTENT_REPLAY", "review_version": 1,
                 "confirmed_fields": {"direction": {"value": "internal"}},
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("уже было применено ранее", text)

    def test_cache_sync_failed_shown_as_warning_not_success(self):
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": False, "code": "CACHE_SYNC_FAILED", "error": "cache down",
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", text)
        self.assertIn("аудит", text.lower())

    def test_reviews_sheet_not_ready_shown_safely(self):
        update, context = _cmd(
            "/confirmdocfield document_id=DREG-004 field=direction value=internal expected_version=0"
        )
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.confirm_field", return_value={
                 "ok": False, "code": "REVIEWS_SHEET_NOT_READY", "error": "not migrated",
             }):
            asyncio.run(th.confirmdocfield_cmd(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", text)
        self.assertNotIn("not migrated", text)  # raw internal error text never shown


class TestRejectdocfieldCmd(unittest.TestCase):
    def test_reject_success(self):
        update, context = _cmd("/rejectdocfield document_id=DREG-004 field=direction expected_version=0")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.reject_field", return_value={
                 "ok": True, "code": "OK", "review_version": 1,
                 "confirmed_fields": {"direction": {"value": ""}},
             }) as mock_reject:
            asyncio.run(th.rejectdocfield_cmd(update, context))
        mock_reject.assert_called_once_with("DREG-004", "direction", "didar", 0)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Новая версия: 1", text)


class TestCleardocfieldCmd(unittest.TestCase):
    def test_clear_success(self):
        """п.6."""
        update, context = _cmd("/cleardocfield document_id=DREG-004 field=direction expected_version=1")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_confirmation.clear_field", return_value={
                 "ok": True, "code": "OK", "review_version": 2,
                 "confirmed_fields": {},
             }) as mock_clear:
            asyncio.run(th.cleardocfield_cmd(update, context))
        mock_clear.assert_called_once_with("DREG-004", "direction", "didar", 1)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Новая версия: 2", text)


if __name__ == "__main__":
    unittest.main()
