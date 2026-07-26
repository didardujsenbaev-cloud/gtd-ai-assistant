"""
Phase 37E — Document Caller UX (ADR-020 §4-§15): tests for the
centralized result-code -> Russian message mapping in
business_core/telegram_handlers.py — _document_creation_message()
(register/upload codes), _document_admin_message()
(update_document_admin_fields codes), _document_transition_message()
(transition_document_status codes), plus /updatedoc's async command
behavior and status/admin mutual-exclusion.

Pure presentation-layer tests: every mapping case feeds a pre-built
structured result dict (never a live orchestration call) and asserts
on the rendered Russian string only. Async command tests mock
business_builder at the call site. No network, no Google Sheets.
Registered in conftest.py's hard socket-block set.
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
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _cmd(cmdline: str):
    update = _upd(cmdline)
    context = MagicMock()
    context.user_data = {}
    context.args = cmdline.split()[1:]
    return update, context


# ────────────────────────────────────────────────────────────
# _document_creation_message — /registerdoc + /uploaddoc shared mapping
# ────────────────────────────────────────────────────────────

class TestDocumentCreationMessageMapping(unittest.TestCase):
    def test_registered_shows_ids_and_status(self):
        result = {
            "ok": True, "code": "DOCUMENT_REGISTERED", "error": None,
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "final_status": "uploaded", "business_id": "BIZ-001",
        }
        msg = th._document_creation_message(result, document_name="Техпаспорт", file_name="passport.pdf")
        self.assertIn("✅", msg)
        self.assertIn("зарегистрирован", msg)
        self.assertNotIn("загружен и зарегистрирован", msg)
        self.assertIn("DREG-001", msg)
        self.assertIn("DFAM-001", msg)
        self.assertIn("Техпаспорт", msg)
        self.assertIn("passport.pdf", msg)

    def test_uploaded_uses_distinct_verb(self):
        result = {
            "ok": True, "code": "DOCUMENT_UPLOADED", "error": None,
            "document_id": "DREG-002", "document_family_id": "DFAM-002", "version": "1",
            "final_status": "uploaded", "uploaded": True,
        }
        msg = th._document_creation_message(result, drive_file_url="https://drive.google.com/x")
        self.assertIn("загружен и зарегистрирован", msg)
        self.assertIn("Drive URL", msg)

    def test_reused_is_not_presented_as_created(self):
        result = {
            "ok": True, "code": "DOCUMENT_REUSED", "error": None,
            "document_id": "DREG-003", "document_family_id": "DFAM-003", "final_status": "uploaded",
        }
        msg = th._document_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)
        self.assertIn("уже", msg.lower())
        self.assertIn("DREG-003", msg)

    def test_business_not_found(self):
        result = {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "business_id обязателен"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertIn("Business", msg)

    def test_entity_relation_mismatch(self):
        result = {"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH", "error": "Stage STG-1 не найден."}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertIn("STG-1", msg)

    def test_multiple_drive_file_matches_lists_all_ids_no_first_pick(self):
        result = {
            "ok": False, "code": "MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES", "error": "conflict",
            "conflicting_document_ids": ("DREG-001", "DREG-002"),
        }
        msg = th._document_creation_message(result)
        self.assertIn("DREG-001", msg)
        self.assertIn("DREG-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_relation_conflict_on_reuse(self):
        result = {"ok": False, "code": "DOCUMENT_RELATION_CONFLICT_ON_REUSE", "error": "x", "document_id": "DREG-005"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertIn("DREG-005", msg)

    def test_persistence_failed_no_raw_error(self):
        result = {"ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED", "error": "gspread.exceptions.APIError: 500 secret-looking-detail"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertNotIn("gspread", msg)
        self.assertNotIn("secret-looking-detail", msg)

    def test_post_write_verification_failed_shows_ids_not_ok_as_success(self):
        result = {
            "ok": False, "code": "DOCUMENT_POST_WRITE_VERIFICATION_FAILED", "error": "mismatch",
            "document_id": "DREG-006", "drive_file_id": "FILE1",
        }
        msg = th._document_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("ручн", msg.lower())
        self.assertIn("DREG-006", msg)
        self.assertIn("FILE1", msg)

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "SOME_FUTURE_CODE", "error": "irrelevant internal detail"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)
        self.assertNotIn("irrelevant internal detail", msg)

    def test_no_raw_result_dict_ever_rendered(self):
        for code in (
            "DOCUMENT_REGISTERED", "DOCUMENT_UPLOADED", "DOCUMENT_REUSED", "BUSINESS_NOT_FOUND",
            "DOCUMENT_ENTITY_RELATION_MISMATCH", "MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES",
            "DOCUMENT_RELATION_CONFLICT_ON_REUSE", "DOCUMENT_PERSISTENCE_FAILED",
            "DOCUMENT_POST_WRITE_VERIFICATION_FAILED", "UNKNOWN",
        ):
            result = {
                "ok": code in ("DOCUMENT_REGISTERED", "DOCUMENT_UPLOADED", "DOCUMENT_REUSED"),
                "code": code, "error": "x", "document_id": "DREG-001", "document_family_id": "DFAM-001",
                "final_status": "uploaded", "conflicting_document_ids": ("DREG-001",),
            }
            msg = th._document_creation_message(result)
            self.assertNotIn("{'ok'", msg)
            self.assertNotIn("{\"ok\"", msg)


class TestDocumentUploadSafetyMessageMapping(unittest.TestCase):
    """Phase 37F.1 — the upload-validation and Drive/compensation
    result codes must all be distinctly mapped, not comment-only
    vocabulary."""

    def test_document_upload_validated(self):
        result = {"ok": True, "code": "DOCUMENT_UPLOAD_VALIDATED", "error": None}
        msg = th._document_creation_message(result)
        self.assertIn("✅", msg)

    def test_analysis_unsupported_distinct_from_storage_unsupported(self):
        analysis_result = {"ok": True, "code": "DOCUMENT_ANALYSIS_UNSUPPORTED", "error": None}
        storage_result = {"ok": False, "code": "UNSUPPORTED_DOCUMENT_STORAGE_TYPE", "error": None}
        analysis_msg = th._document_creation_message(analysis_result)
        storage_msg = th._document_creation_message(storage_result)
        self.assertNotIn("❌", analysis_msg)
        self.assertIn("❌", storage_msg)
        self.assertNotEqual(analysis_msg, storage_msg)

    def test_invalid_filename(self):
        result = {"ok": False, "code": "INVALID_DOCUMENT_FILENAME", "error": "Имя файла не указано"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertIn("имя файла", msg.lower())

    def test_too_large(self):
        result = {"ok": False, "code": "DOCUMENT_TOO_LARGE", "error": "x"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)

    def test_unsupported_storage_type(self):
        result = {"ok": False, "code": "UNSUPPORTED_DOCUMENT_STORAGE_TYPE", "error": "x"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)

    def test_drive_upload_failed(self):
        result = {"ok": False, "code": "DRIVE_UPLOAD_FAILED", "error": "x"}
        msg = th._document_creation_message(result)
        self.assertIn("❌", msg)
        self.assertIn("Drive", msg)

    def test_document_file_metadata_invalid_compensation_succeeded_no_success_claim(self):
        result = {
            "ok": False, "code": "DOCUMENT_FILE_METADATA_INVALID", "error": "x",
            "compensation_attempted": True, "compensation_succeeded": True,
        }
        msg = th._document_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("❌", msg)
        self.assertIn("корзину", msg)

    def test_document_file_metadata_invalid_compensation_failed_shows_orphan_warning(self):
        result = {
            "ok": False, "code": "DOCUMENT_FILE_METADATA_INVALID", "error": "x",
            "compensation_attempted": True, "compensation_succeeded": False, "drive_file_id": "FILE1",
        }
        msg = th._document_creation_message(result)
        self.assertIn("⚠️", msg)
        self.assertIn("ручн", msg.lower())
        self.assertIn("FILE1", msg)

    def test_orphan_warning_never_exposes_raw_drive_url(self):
        result = {
            "ok": False, "code": "DOCUMENT_FILE_METADATA_INVALID", "error": "x",
            "compensation_attempted": True, "compensation_succeeded": False, "drive_file_id": "FILE1",
        }
        msg = th._document_creation_message(result)
        self.assertNotIn("drive.google.com", msg)
        self.assertNotIn("http", msg)

    def test_drive_upload_compensated_not_shown_as_success(self):
        result = {"ok": False, "code": "DRIVE_UPLOAD_COMPENSATED", "error": "x", "drive_file_id": "FILE1"}
        msg = th._document_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("❌", msg)
        self.assertIn("корзину", msg)

    def test_orphaned_file_warning_is_explicit_and_no_url(self):
        result = {
            "ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING",
            "error": "x", "drive_file_id": "FILE1",
        }
        msg = th._document_creation_message(result)
        self.assertIn("⚠️", msg)
        self.assertIn("FILE1", msg)
        self.assertNotIn("drive.google.com", msg)
        self.assertNotIn("http", msg)

    def test_all_upload_safety_codes_produce_distinct_messages(self):
        codes_and_ok = [
            ("DOCUMENT_UPLOAD_VALIDATED", True), ("DOCUMENT_ANALYSIS_UNSUPPORTED", True),
            ("INVALID_DOCUMENT_FILENAME", False), ("DOCUMENT_TOO_LARGE", False),
            ("UNSUPPORTED_DOCUMENT_STORAGE_TYPE", False), ("DRIVE_UPLOAD_FAILED", False),
            ("DOCUMENT_FILE_METADATA_INVALID", False), ("DRIVE_UPLOAD_COMPENSATED", False),
            ("DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING", False),
        ]
        messages = set()
        for code, ok in codes_and_ok:
            result = {"ok": ok, "code": code, "error": "x", "drive_file_id": "FILE1"}
            messages.add(th._document_creation_message(result))
        self.assertEqual(len(messages), len(codes_and_ok), "every upload-safety code must render a distinct message")


# ────────────────────────────────────────────────────────────
# _document_admin_message — /updatedoc admin-field mapping
# ────────────────────────────────────────────────────────────

class TestDocumentAdminMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("✅", msg)
        self.assertIn("DREG-001", msg)

    def test_unchanged_is_not_presented_as_changed(self):
        result = {"ok": True, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": None}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertNotIn("✅", msg)
        self.assertIn("изменений нет", msg.lower())

    def test_not_found(self):
        result = {"ok": False, "code": "DOCUMENT_NOT_FOUND", "error": "x"}
        msg = th._document_admin_message(result, "DREG-404")
        self.assertIn("❌", msg)
        self.assertIn("DREG-404", msg)
        self.assertIn("не найден", msg)

    def test_immutable_field_conflict(self):
        result = {"ok": False, "code": "DOCUMENT_IMMUTABLE_FIELD_CONFLICT", "error": "Business ID"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("неизменяемой идентичностью", msg)

    def test_version_field_immutable(self):
        result = {"ok": False, "code": "DOCUMENT_VERSION_FIELD_IMMUTABLE", "error": "x"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("Version", msg)

    def test_family_field_immutable(self):
        result = {"ok": False, "code": "DOCUMENT_FAMILY_FIELD_IMMUTABLE", "error": "x"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("Family", msg)

    def test_relation_update_requires_explicit_action(self):
        result = {"ok": False, "code": "DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION", "error": "x"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("/updatedoc", msg)

    def test_invalid_admin_field(self):
        result = {"ok": False, "code": "INVALID_DOCUMENT_ADMIN_FIELD", "error": "Status"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)

    def test_unknown_code_safe_fallback(self):
        """Mirrors the established Task/Organization domain fallback
        convention: an unmapped code is shown verbatim (it's an internal
        semantic constant, not a raw exception) alongside a generic
        error message — never a Python traceback or raw dict."""
        result = {"ok": False, "code": "WEIRD_FUTURE_CODE", "error": "internal detail"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("WEIRD_FUTURE_CODE", msg)


# ────────────────────────────────────────────────────────────
# _document_transition_message — /updatedoc status mapping
# ────────────────────────────────────────────────────────────

class TestDocumentTransitionMessageMapping(unittest.TestCase):
    def test_status_updated(self):
        result = {
            "ok": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None,
            "previous_status": "uploaded", "final_status": "under_review",
        }
        msg = th._document_transition_message(result, "DREG-001")
        self.assertIn("✅", msg)
        self.assertIn("uploaded", msg)
        self.assertIn("under_review", msg)

    def test_status_unchanged_is_not_presented_as_changed(self):
        result = {"ok": True, "code": "DOCUMENT_STATUS_UNCHANGED", "error": None, "previous_status": "uploaded"}
        msg = th._document_transition_message(result, "DREG-001")
        self.assertNotIn("✅", msg)
        self.assertIn("изменений нет", msg.lower())

    def test_not_found(self):
        result = {"ok": False, "code": "DOCUMENT_NOT_FOUND", "error": "x"}
        msg = th._document_transition_message(result, "DREG-404")
        self.assertIn("❌", msg)
        self.assertIn("DREG-404", msg)

    def test_invalid_status(self):
        result = {"ok": False, "code": "INVALID_DOCUMENT_STATUS", "error": "x"}
        msg = th._document_transition_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("uploaded", msg)  # canonical vocabulary listed

    def test_invalid_transition(self):
        result = {
            "ok": False, "code": "INVALID_DOCUMENT_TRANSITION", "error": "x",
            "previous_status": "approved", "requested_status": "uploaded",
        }
        msg = th._document_transition_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("approved", msg)
        self.assertIn("uploaded", msg)

    def test_restore_requires_explicit_action_is_clear(self):
        result = {
            "ok": False, "code": "DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION", "error": "x",
            "previous_status": "archived",
        }
        msg = th._document_transition_message(result, "DREG-001")
        self.assertIn("🔒", msg)
        self.assertIn("archived", msg)
        self.assertIn("restore", msg.lower())

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "FUTURE_CODE", "error": "internal"}
        msg = th._document_transition_message(result, "DREG-001")
        self.assertIn("❌", msg)
        self.assertIn("FUTURE_CODE", msg)


# ────────────────────────────────────────────────────────────
# _document_status_ru / _document_analysis_status_ru
# ────────────────────────────────────────────────────────────

class TestDocumentStatusLabels(unittest.TestCase):
    def test_known_status_has_russian_label_and_raw_value(self):
        label = th._document_status_ru("under_review")
        self.assertIn("(under_review)", label)
        self.assertNotEqual(label, "under_review")

    def test_unknown_status_falls_back_to_raw_value(self):
        label = th._document_status_ru("mystery")
        self.assertIn("mystery", label)

    def test_analysis_status_label(self):
        label = th._document_analysis_status_ru("completed")
        self.assertIn("(completed)", label)


# ────────────────────────────────────────────────────────────
# /updatedoc — async command behavior
# ────────────────────────────────────────────────────────────

class TestUpdateDocCmd(unittest.TestCase):
    def test_missing_document_id(self):
        update, context = _cmd("/updatedoc name=X")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("document_id", msg)

    def test_status_and_admin_together_rejected(self):
        update, context = _cmd('/updatedoc document_id=DREG-001 status=under_review name="X"')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())

    def test_neither_status_nor_admin_rejected(self):
        update, context = _cmd("/updatedoc document_id=DREG-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("status=", msg)

    def test_status_only_calls_transition_document_status(self):
        update, context = _cmd("/updatedoc document_id=DREG-001 status=under_review")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.transition_document_status",
                   return_value={"ok": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None,
                                 "previous_status": "uploaded", "final_status": "under_review"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_called_once_with("DREG-001", "under_review")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_admin_only_calls_update_document_admin_fields(self):
        update, context = _cmd('/updatedoc document_id=DREG-001 name="New Name" notes="hi"')

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.update_document_admin_fields",
                   return_value={"ok": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        self.assertEqual(mock_fn.call_args[0][0], "DREG-001")
        updates = mock_fn.call_args[0][1]
        self.assertEqual(updates.get("Document Name"), "New Name")
        self.assertEqual(updates.get("Notes"), "hi")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_no_task_id_argument_supported(self):
        """/updatedoc is Document Domain — task_id= must never be
        accepted as a mutable field (it would silently be dropped as
        an unrecognized key, never forwarded to Task orchestration)."""
        update, context = _cmd("/updatedoc document_id=DREG-001 task_id=TSK-001")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.update_document_admin_fields",
                   return_value={"ok": True, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": None}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        if mock_fn.called:
            updates = mock_fn.call_args[0][1]
            self.assertNotIn("Task ID", updates)
            self.assertNotIn("task_id", updates)

    def test_exception_never_exposes_raw_text(self):
        update, context = _cmd("/updatedoc document_id=DREG-001 status=under_review")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.transition_document_status",
                       side_effect=RuntimeError("secret-internal-detail")):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-internal-detail", msg)
        self.assertIn("❌", msg)


if __name__ == "__main__":
    unittest.main()
