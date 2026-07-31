"""
Phase 16C.9D — /archivedoc Telegram UX.

Stateless CommandHandler tests: mocks business_builder.archive_document
at the call site only — never a live Sheets/Drive/network call, never
runs /archivedoc against production.
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


def _upd(user_id=123, has_user=True):
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    if has_user:
        update.effective_user = MagicMock(username="didar", id=user_id)
    else:
        update.effective_user = None
    return update


def _cmd(cmdline: str, user_id=123, has_user=True):
    update = _upd(user_id=user_id, has_user=has_user)
    context = MagicMock()
    context.args = cmdline.split()[1:] if cmdline else []
    return update, context


def _run(cmdline: str, user_id=123, has_user=True):
    update, context = _cmd(cmdline, user_id=user_id, has_user=has_user)
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
        asyncio.run(th.archivedoc_cmd(update, context))
    return update


def _reply_text(update) -> str:
    return update.message.reply_text.call_args[0][0]


DOC_RESULT_PREVIEW = {
    "ok": True, "code": "DOCUMENT_ARCHIVE_PREVIEW", "error": None,
    "document_id": "DREG-001", "document_name": "Технический паспорт",
    "previous_status": "uploaded", "final_status": "archived",
    "archived_at": "", "archived_by": "telegram:123", "archive_reason": "test reason",
    "changed": False, "retry_safe": True,
}
DOC_RESULT_ARCHIVED = {
    "ok": True, "code": "DOCUMENT_ARCHIVED", "error": None,
    "document_id": "DREG-001", "document_name": "Технический паспорт",
    "previous_status": "uploaded", "final_status": "archived",
    "archived_at": "2026-02-01 00:00:00 UTC", "archived_by": "telegram:123", "archive_reason": "test reason",
    "changed": True, "retry_safe": True,
}


def _patched_bc(result):
    return patch("business_core.business_builder.archive_document", return_value=result)


# ────────────────────────────────────────────────────────────
# Registration / parser
# ────────────────────────────────────────────────────────────

class TestRegistrationAndParser(unittest.TestCase):
    def test_command_registered(self):
        app = MagicMock()
        th.register_business_handlers(app)
        names = [c.args[0].commands for c in app.add_handler.call_args_list if hasattr(c.args[0], "commands")]
        self.assertIn(frozenset({"archivedoc"}), names)

    def test_handler_is_command_handler(self):
        from telegram.ext import CommandHandler
        app = MagicMock()
        th.register_business_handlers(app)
        matched = [c.args[0] for c in app.add_handler.call_args_list
                   if hasattr(c.args[0], "commands") and c.args[0].commands == frozenset({"archivedoc"})]
        self.assertEqual(len(matched), 1)
        self.assertIsInstance(matched[0], CommandHandler)

    def test_no_conversation_handler_state(self):
        from telegram.ext import ConversationHandler
        app = MagicMock()
        th.register_business_handlers(app)
        for c in app.add_handler.call_args_list:
            handler = c.args[0]
            if isinstance(handler, ConversationHandler):
                for ep in handler.entry_points:
                    if hasattr(ep, "commands"):
                        self.assertNotEqual(ep.commands, frozenset({"archivedoc"}))

    def test_canonical_preview_syntax(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="Причина архивирования"')
        self.assertIsNone(error)
        self.assertEqual(parsed, {"document_id": "DREG-001", "reason": "Причина архивирования"})

    def test_canonical_confirm_syntax(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="Причина архивирования" confirm=yes')
        self.assertIsNone(error)
        self.assertEqual(parsed["confirm"], "yes")

    def test_document_alias_rejected(self):
        parsed, error = th._parse_archivedoc_args('document=DREG-001 reason="x"')
        self.assertIsNone(parsed)
        self.assertIn("document", error)

    def test_positional_id_rejected(self):
        parsed, error = th._parse_archivedoc_args('DREG-001 reason="x"')
        self.assertIsNone(parsed)

    def test_missing_document_id(self):
        parsed, error = th._parse_archivedoc_args('reason="x"')
        self.assertIsNone(parsed)
        self.assertIn("document_id", error)

    def test_whitespace_document_id_reaches_domain_safely(self):
        # Telegram's own context.args splitting collapses whitespace
        # runs (same as str.split()) — a quoted whitespace-only value
        # survives as a single space, not necessarily the exact
        # original run length. The parser must not crash or reject it
        # outright; the domain layer (business_builder.archive_document)
        # is solely authoritative for rejecting it as empty/invalid.
        with _patched_bc(DOC_RESULT_PREVIEW) as mock_bc:
            update = _run('/archivedoc document_id="   " reason="x"')
        self.assertTrue(mock_bc.called)
        self.assertEqual(mock_bc.call_args[0][0].strip(), "")

    def test_missing_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001')
        self.assertIsNone(parsed)
        self.assertIn("reason", error)

    def test_empty_quoted_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason=""')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"], "")

    def test_whitespace_only_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="   "')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"].strip(), "")

    def test_quoted_cyrillic_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="ошибочно загруженный документ"')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"], "ошибочно загруженный документ")

    def test_punctuation_in_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="дубликат, версия №2 — удалить"')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"], "дубликат, версия №2 — удалить")

    def test_equals_sign_inside_quoted_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="a=b"')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"], "a=b")

    def test_unquoted_one_word_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason=ошибка')
        self.assertIsNone(error)
        self.assertEqual(parsed["reason"], "ошибка")

    def test_unquoted_multi_word_reason_rejected(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason=ошибка загрузки')
        self.assertIsNone(parsed)

    def test_unmatched_double_quote(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="abc')
        self.assertIsNone(parsed)
        self.assertIn("кавычка", error)

    def test_unmatched_single_quote(self):
        parsed, error = th._parse_archivedoc_args("document_id=DREG-001 reason='abc")
        self.assertIsNone(parsed)
        self.assertIn("кавычка", error)

    def test_dangling_token(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" extra_junk')
        self.assertIsNone(parsed)

    def test_repeated_document_id(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 document_id=DREG-002 reason="x"')
        self.assertIsNone(parsed)
        self.assertIn("document_id", error)

    def test_repeated_reason(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="a" reason="b"')
        self.assertIsNone(parsed)
        self.assertIn("reason", error)

    def test_repeated_confirm(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" confirm=yes confirm=yes')
        self.assertIsNone(parsed)
        self.assertIn("confirm", error)

    def test_unknown_parameter(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" bogus=1')
        self.assertIsNone(parsed)
        self.assertIn("bogus", error)

    def test_archived_by_parameter_rejected(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" archived_by=telegram:1')
        self.assertIsNone(parsed)
        self.assertIn("archived_by", error)

    def test_dry_run_parameter_rejected(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" dry_run=true')
        self.assertIsNone(parsed)
        self.assertIn("dry_run", error)


# ────────────────────────────────────────────────────────────
# Confirmation semantics
# ────────────────────────────────────────────────────────────

class TestConfirmationSemantics(unittest.TestCase):
    def _dry_run_flag(self, cmdline: str) -> bool:
        with _patched_bc(DOC_RESULT_PREVIEW) as mock_bc:
            _run(cmdline)
        return mock_bc.call_args.kwargs["dry_run"]

    def test_exact_confirm_yes_executes_dry_run_false(self):
        self.assertFalse(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=yes'))

    def test_no_confirm_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x"'))

    def test_confirm_YES_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=YES'))

    def test_confirm_Yes_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=Yes'))

    def test_confirm_true_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=true'))

    def test_confirm_1_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=1'))

    def test_confirm_da_calls_dry_run_true(self):
        self.assertTrue(self._dry_run_flag('/archivedoc document_id=DREG-001 reason="x" confirm=да'))

    def test_whitespace_padded_yes_does_not_execute(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" confirm=" yes"')
        # quoted value with leading space parses fine but must not equal "yes"
        self.assertIsNone(error)
        self.assertNotEqual(parsed["confirm"], "yes")

    def test_quoted_exact_yes_matches(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" confirm="yes"')
        self.assertIsNone(error)
        self.assertEqual(parsed["confirm"], "yes")
        with _patched_bc(DOC_RESULT_ARCHIVED) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm="yes"')
        self.assertFalse(mock_bc.call_args.kwargs["dry_run"])


# ────────────────────────────────────────────────────────────
# Actor derivation
# ────────────────────────────────────────────────────────────

class TestActorDerivation(unittest.TestCase):
    def test_actor_uses_effective_user_id(self):
        with _patched_bc(DOC_RESULT_PREVIEW) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x"', user_id=987)
        self.assertEqual(mock_bc.call_args[0][2], "telegram:987")

    def test_actor_format_telegram_prefix(self):
        actor = th._archivedoc_actor(_upd(user_id=42))
        self.assertEqual(actor, "telegram:42")

    def test_username_never_used(self):
        update = _upd(user_id=55)
        update.effective_user.username = "some_username"
        actor = th._archivedoc_actor(update)
        self.assertNotIn("some_username", actor)
        self.assertEqual(actor, "telegram:55")

    def test_missing_effective_user(self):
        update = _run('/archivedoc document_id=DREG-001 reason="x"', has_user=False)
        text = _reply_text(update)
        self.assertIn("Не удалось определить пользователя", text)

    def test_missing_effective_user_id(self):
        update = _upd()
        update.effective_user = MagicMock(username="x", id=None)
        actor = th._archivedoc_actor(update)
        self.assertEqual(actor, "")

    def test_user_supplied_actor_impossible(self):
        parsed, error = th._parse_archivedoc_args('document_id=DREG-001 reason="x" archived_by=telegram:999')
        self.assertIsNone(parsed)


# ────────────────────────────────────────────────────────────
# Rendering
# ────────────────────────────────────────────────────────────

class TestRendering(unittest.TestCase):
    def test_preview_rendering(self):
        text = th._archivedoc_result_message(DOC_RESULT_PREVIEW, "DREG-001")
        self.assertIn("Предпросмотр", text)
        self.assertIn("DREG-001", text)
        self.assertIn("confirm=yes", text)

    def test_success_rendering(self):
        text = th._archivedoc_result_message(DOC_RESULT_ARCHIVED, "DREG-001")
        self.assertIn("архивирован", text)
        self.assertIn("2026-02-01 00:00:00 UTC", text)

    def test_already_archived_with_metadata(self):
        result = {
            "code": "DOCUMENT_ARCHIVE_ALREADY_ARCHIVED", "document_id": "DREG-001",
            "previous_status": "uploaded", "archived_at": "2026-01-15 00:00:00 UTC",
            "archived_by": "telegram:1", "archive_reason": "orig reason",
        }
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertIn("уже архивирован", text)
        self.assertIn("2026-01-15 00:00:00 UTC", text)
        self.assertIn("orig reason", text)
        self.assertIn("пользователь Telegram", text)
        self.assertNotIn("telegram:1", text)

    def test_already_archived_with_legacy_blanks(self):
        result = {
            "code": "DOCUMENT_ARCHIVE_ALREADY_ARCHIVED", "document_id": "DREG-001",
            "previous_status": "", "archived_at": "", "archived_by": "", "archive_reason": "",
        }
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertIn("недоступны", text)

    def test_not_found(self):
        text = th._archivedoc_result_message({"code": "DOCUMENT_NOT_FOUND"}, "DREG-999")
        self.assertIn("не найден", text)

    def test_reason_required(self):
        text = th._archivedoc_result_message({"code": "DOCUMENT_ARCHIVE_REASON_REQUIRED"}, "DREG-001")
        self.assertIn("причину", text)

    def test_reason_too_long(self):
        text = th._archivedoc_result_message({"code": "DOCUMENT_ARCHIVE_REASON_TOO_LONG"}, "DREG-001")
        self.assertIn("500", text)

    def test_invalid_transition(self):
        text = th._archivedoc_result_message({"code": "INVALID_DOCUMENT_TRANSITION"}, "DREG-001")
        self.assertIn("нельзя архивировать", text)

    def test_write_failure_uncertain_warning(self):
        text = th._archivedoc_result_message({"code": "DOCUMENT_ARCHIVE_WRITE_FAILED"}, "DREG-001")
        self.assertIn("Не повторяйте команду автоматически", text)
        self.assertNotIn("документ не изменён", text)

    def test_verification_failure_uncertain_warning(self):
        text = th._archivedoc_result_message({"code": "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED"}, "DREG-001")
        self.assertIn("Не повторяйте команду автоматически", text)

    def test_unknown_result(self):
        text = th._archivedoc_result_message({"code": "SOME_BOGUS_CODE"}, "DREG-001")
        self.assertIn("Непредвиденный результат", text)

    def test_drive_url_not_displayed(self):
        result = dict(DOC_RESULT_ARCHIVED, drive_file_url="https://drive.google.com/file/d/X/view")
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertNotIn("drive.google.com", text)

    def test_drive_file_id_not_displayed(self):
        result = dict(DOC_RESULT_ARCHIVED, drive_file_id="FILE123")
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertNotIn("FILE123", text)

    def test_raw_actor_id_not_displayed(self):
        text = th._archivedoc_result_message(DOC_RESULT_ARCHIVED, "DREG-001")
        self.assertNotIn("telegram:123", text)

    def test_raw_exception_not_displayed(self):
        result = dict(DOC_RESULT_ARCHIVED, code="DOCUMENT_ARCHIVE_WRITE_FAILED", error="SensitiveTraceback")
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertNotIn("SensitiveTraceback", text)

    def test_document_name_special_characters_safe(self):
        result = dict(DOC_RESULT_PREVIEW, document_name="*bold* _italic_ `code`")
        with _patched_bc(result):
            update = _run('/archivedoc document_id=DREG-001 reason="x"')
        update.message.reply_text.assert_called_once()
        kwargs = update.message.reply_text.call_args
        self.assertIsNone(kwargs.kwargs.get("parse_mode"))

    def test_reason_special_characters_safe(self):
        result = dict(DOC_RESULT_PREVIEW, archive_reason="*bold* [link](url) `code`")
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertIn("*bold* [link](url) `code`", text)

    def test_500_char_reason_fully_rendered(self):
        long_reason = "я" * 500
        result = dict(DOC_RESULT_PREVIEW, archive_reason=long_reason)
        text = th._archivedoc_result_message(result, "DREG-001")
        self.assertIn(long_reason, text)


# ────────────────────────────────────────────────────────────
# Domain boundary
# ────────────────────────────────────────────────────────────

class TestDomainBoundary(unittest.TestCase):
    def test_preview_calls_archive_document_exactly_once(self):
        with _patched_bc(DOC_RESULT_PREVIEW) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x"')
        mock_bc.assert_called_once()

    def test_confirm_calls_archive_document_exactly_once(self):
        with _patched_bc(DOC_RESULT_ARCHIVED) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_bc.assert_called_once()

    def test_preview_passes_dry_run_true(self):
        with _patched_bc(DOC_RESULT_PREVIEW) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x"')
        self.assertTrue(mock_bc.call_args.kwargs["dry_run"])

    def test_confirm_passes_dry_run_false(self):
        with _patched_bc(DOC_RESULT_ARCHIVED) as mock_bc:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        self.assertFalse(mock_bc.call_args.kwargs["dry_run"])

    def test_no_archive_document_row_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("business_core.document_manager.archive_document_row") as mock_low:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_low.assert_not_called()

    def test_no_update_document_status_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("business_core.document_manager.update_document_status") as mock_status:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_status.assert_not_called()

    def test_no_update_business_row_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("business_core.sheets.update_business_row") as mock_row:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_row.assert_not_called()

    def test_no_sheets_primitive_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("business_core.sheets.get_business_sheet") as mock_sheet:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_sheet.assert_not_called()

    def test_no_drive_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("integrations.google_drive_adapter.trash_file") as mock_drive:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_drive.assert_not_called()

    def test_no_content_review_requirements_call(self):
        with _patched_bc(DOC_RESULT_ARCHIVED), \
             patch("business_core.document_requirements.evaluate_stage_requirements") as mock_req, \
             patch("business_core.document_confirmation.confirm_document_field", create=True) as mock_conf:
            _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        mock_req.assert_not_called()
        mock_conf.assert_not_called()


# ────────────────────────────────────────────────────────────
# State / cancel
# ────────────────────────────────────────────────────────────

class TestStateAndCancel(unittest.TestCase):
    def test_no_preview_state_stored(self):
        context = MagicMock()
        context.args = 'document_id=DREG-001 reason="x"'.split()
        context.user_data = {}
        update = _upd()
        with _patched_bc(DOC_RESULT_PREVIEW):
            asyncio.run(th.archivedoc_cmd(update, context))
        self.assertEqual(context.user_data, {})

    def test_stale_preview_uses_fresh_confirmed_result(self):
        # Preview call and confirm call are two fully independent
        # invocations of archive_document — the confirm call's own
        # returned previous_status must be rendered, never a value
        # carried over from an earlier preview call.
        stale_confirmed_result = dict(DOC_RESULT_ARCHIVED, previous_status="approved")
        with _patched_bc(DOC_RESULT_PREVIEW):
            preview_update = _run('/archivedoc document_id=DREG-001 reason="x"')
        preview_text = _reply_text(preview_update)
        self.assertIn("uploaded", preview_text)

        with _patched_bc(stale_confirmed_result):
            confirm_update = _run('/archivedoc document_id=DREG-001 reason="x" confirm=yes')
        confirm_text = _reply_text(confirm_update)
        self.assertIn("approved", confirm_text)

    def test_cancel_routing_unchanged(self):
        app = MagicMock()
        th.register_business_handlers(app)
        # /archivedoc must not appear as any ConversationHandler's
        # fallback or entry point.
        from telegram.ext import ConversationHandler
        for c in app.add_handler.call_args_list:
            handler = c.args[0]
            if isinstance(handler, ConversationHandler):
                for fb in handler.fallbacks:
                    if hasattr(fb, "commands"):
                        self.assertNotEqual(fb.commands, frozenset({"archivedoc"}))

    def test_existing_conversation_handler_order_unchanged(self):
        app = MagicMock()
        th.register_business_handlers(app)
        from telegram.ext import ConversationHandler
        conv_commands = []
        for c in app.add_handler.call_args_list:
            handler = c.args[0]
            if isinstance(handler, ConversationHandler):
                for ep in handler.entry_points:
                    if hasattr(ep, "commands"):
                        conv_commands.append(next(iter(ep.commands)))
        self.assertIn("uploaddoc", conv_commands)

    def test_no_cancel_fallback_added(self):
        app = MagicMock()
        th.register_business_handlers(app)
        matched = [c.args[0] for c in app.add_handler.call_args_list
                   if hasattr(c.args[0], "commands") and c.args[0].commands == frozenset({"archivedoc"})]
        self.assertEqual(len(matched), 1)


# ────────────────────────────────────────────────────────────
# Compatibility
# ────────────────────────────────────────────────────────────

class TestCompatibility(unittest.TestCase):
    def test_telegram_handlers_import_cleanly(self):
        # A plain re-import (not importlib.reload) — reload() is unsafe
        # here since other test files in the full suite purge
        # business_core.* from sys.modules mid-run, and reloading this
        # already-imported module object against a partially-purged
        # module graph is a self-inflicted ordering hazard, not a real
        # assertion about production import cleanliness.
        import business_core.telegram_handlers as th_reimport
        self.assertTrue(hasattr(th_reimport, "archivedoc_cmd"))

    def test_schema_remains_27_35_12(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_registry"]), 27)
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)
        self.assertEqual(len(BUSINESS_HEADERS["document_field_reviews"]), 12)


if __name__ == "__main__":
    unittest.main()
