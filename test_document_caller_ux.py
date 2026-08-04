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
        """Phase 17E-2A5-H1: hardened — an unmapped code no longer
        renders the code or any manager-supplied error text; it falls
        to the single fixed generic message."""
        result = {"ok": False, "code": "WEIRD_FUTURE_CODE", "error": "internal detail"}
        msg = th._document_admin_message(result, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Document.")
        self.assertNotIn("WEIRD_FUTURE_CODE", msg)
        self.assertNotIn("internal detail", msg)


_SECRET_NOTES_MARKER = "SECRET_NOTES_MARKER"
_SECRET_BIZ_MARKER = "BIZ-SECRET"
_SECRET_OBJECT_MARKER = "OBJECT-SECRET"
_SECRET_ROW_MARKER = "ROW-SECRET"
_SECRET_API_MARKER = "API-PAYLOAD-SECRET"
_ALL_SECRET_MARKERS = (
    _SECRET_NOTES_MARKER, _SECRET_BIZ_MARKER, _SECRET_OBJECT_MARKER,
    _SECRET_ROW_MARKER, _SECRET_API_MARKER,
)
_GENERIC_FAILURE_MSG = "❌ Не удалось обновить Document."


class TestDocumentAdminMessageHardening(unittest.TestCase):
    """Phase 17E-2A5-H1: comprehensive hardened-mapper battery —
    proves _document_admin_message type-checks first, requires
    ok is True (strict identity) for success/no-op UX, uses only
    fixed text for every known rejection code, never renders manager
    error text/unknown codes/secret markers, and never raises on
    malformed input."""

    def test_valid_updated_result(self):
        msg = th._document_admin_message(
            {"ok": True, "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}, "DREG-001",
        )
        self.assertEqual(msg, "✅ Document DREG-001 обновлён.")

    def test_valid_unchanged_result(self):
        msg = th._document_admin_message(
            {"ok": True, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": None}, "DREG-001",
        )
        self.assertEqual(msg, "ℹ️ Document DREG-001 — изменений нет (значения совпадают).")

    def test_ok_false_with_updated_code_never_success(self):
        msg = th._document_admin_message(
            {"ok": False, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": "Infrastructure failure"}, "DREG-001",
        )
        self.assertNotIn("✅", msg)
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_ok_false_with_unchanged_code_never_unchanged_ux(self):
        msg = th._document_admin_message(
            {"ok": False, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": "Infrastructure failure"}, "DREG-001",
        )
        self.assertNotIn("ℹ️", msg)
        self.assertNotIn("изменений нет", msg)
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_not_found_fixed_text(self):
        msg = th._document_admin_message({"ok": False, "code": "DOCUMENT_NOT_FOUND", "error": "x"}, "DREG-404")
        self.assertEqual(msg, "❌ Document DREG-404 не найден.")

    def test_immutable_field_fixed_text_no_error_render(self):
        msg = th._document_admin_message(
            {"ok": False, "code": "DOCUMENT_IMMUTABLE_FIELD_CONFLICT", "error": f"leak-{_SECRET_BIZ_MARKER}"}, "DREG-001",
        )
        self.assertEqual(msg, "❌ Указанные поля являются неизменяемой идентичностью Document.")
        self.assertNotIn(_SECRET_BIZ_MARKER, msg)

    def test_family_immutable_fixed_text(self):
        msg = th._document_admin_message({"ok": False, "code": "DOCUMENT_FAMILY_FIELD_IMMUTABLE", "error": "x"}, "DREG-001")
        self.assertEqual(msg, "❌ Document Family ID неизменяем после создания.")

    def test_version_immutable_fixed_text(self):
        msg = th._document_admin_message({"ok": False, "code": "DOCUMENT_VERSION_FIELD_IMMUTABLE", "error": "x"}, "DREG-001")
        self.assertEqual(msg, "❌ Version неизменяем после создания.")

    def test_relation_update_restriction_fixed_text(self):
        msg = th._document_admin_message(
            {"ok": False, "code": "DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION", "error": "x"}, "DREG-001",
        )
        self.assertEqual(
            msg, "❌ Изменение связей (Client/Object/Roadmap/Stage/Template ID) через /updatedoc не поддерживается.",
        )

    def test_invalid_admin_field_fixed_text_no_error_render(self):
        msg = th._document_admin_message(
            {"ok": False, "code": "INVALID_DOCUMENT_ADMIN_FIELD", "error": f"leak-{_SECRET_API_MARKER}"}, "DREG-001",
        )
        self.assertEqual(msg, "❌ Недопустимое поле для /updatedoc.")
        self.assertNotIn(_SECRET_API_MARKER, msg)

    def test_blank_code_fallback(self):
        msg = th._document_admin_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_unknown_code_fallback(self):
        msg = th._document_admin_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "raw detail"}, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)
        self.assertNotIn("SOME_FUTURE_CODE", msg)
        self.assertNotIn("raw detail", msg)

    def test_infrastructure_failure_never_rendered(self):
        msg = th._document_admin_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "DREG-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_arbitrary_secret_marker_error_never_rendered(self):
        for marker in _ALL_SECRET_MARKERS:
            with self.subTest(marker=marker):
                msg = th._document_admin_message({"ok": False, "code": "", "error": f"boom {marker}"}, "DREG-001")
                self.assertNotIn(marker, msg)
                self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_empty_dict(self):
        msg = th._document_admin_message({}, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_partial_dict_ok_only(self):
        msg = th._document_admin_message({"ok": True}, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_partial_dict_code_only(self):
        msg = th._document_admin_message({"code": "DOCUMENT_ADMIN_FIELDS_UPDATED"}, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_none_result_does_not_raise(self):
        msg = th._document_admin_message(None, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_string_result_does_not_raise(self):
        msg = th._document_admin_message("not a dict", "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_list_result_does_not_raise(self):
        msg = th._document_admin_message(["ok", True], "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_integer_result_does_not_raise(self):
        msg = th._document_admin_message(42, "DREG-001")
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_truthy_string_ok_not_treated_as_true(self):
        msg = th._document_admin_message(
            {"ok": "true", "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}, "DREG-001",
        )
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_truthy_int_ok_not_treated_as_true(self):
        msg = th._document_admin_message(
            {"ok": 1, "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}, "DREG-001",
        )
        self.assertEqual(msg, _GENERIC_FAILURE_MSG)

    def test_fallback_log_is_fixed_literal(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_log_warning:
            th._document_admin_message({"ok": False, "code": "UNMAPPED_XYZ", "error": f"leak-{_SECRET_ROW_MARKER}"}, "DREG-001")
        mock_log_warning.assert_called_once_with("_document_admin_message unmapped safe fallback")
        for call in mock_log_warning.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                self.assertNotIn(_SECRET_ROW_MARKER, str(arg))
                self.assertNotIn("UNMAPPED_XYZ", str(arg))

    def test_known_branches_do_not_log(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_log_warning:
            th._document_admin_message({"ok": True, "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None}, "DREG-001")
        mock_log_warning.assert_not_called()


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


# ────────────────────────────────────────────────────────────
# /updatedoc — relink mode (Roadmap ID / Stage ID only)
# ────────────────────────────────────────────────────────────

_RELINK_DOCUMENT = {
    "document_id": "DREG-003", "business_id": "BIZ-001", "client_id": "PRS-004",
    "object_id": "OBJ-002", "document_template_id": "",
    "roadmap_id": "RM-003", "stage_id": "STAGE-010",
}


class TestUpdateDocRelinkForbiddenFields(unittest.TestCase):
    """business_id/client_id/object_id must be an explicit, visible
    rejection — never a silent no-op. document_template_id is
    deliberately NOT in this set — it is a pure classification field
    with no Drive-path implication, so (unlike Object ID) it IS
    relinkable — see TestUpdateDocRelinkDocumentTemplateId below."""

    def _assert_rejected(self, cmdline: str, forbidden_key: str):
        update, context = _cmd(cmdline)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn(forbidden_key, msg)

    def test_business_id_rejected(self):
        self._assert_rejected("/updatedoc document_id=DREG-003 business_id=BIZ-002", "business_id")

    def test_client_id_rejected(self):
        self._assert_rejected("/updatedoc document_id=DREG-003 client_id=PRS-005", "client_id")

    def test_object_id_rejected(self):
        self._assert_rejected("/updatedoc document_id=DREG-003 object_id=OBJ-009", "object_id")

    def test_document_template_id_alone_is_not_rejected(self):
        """document_template_id must NOT trigger the forbidden-field
        rejection — it goes through the relink path instead."""
        update, context = _cmd("/updatedoc document_id=DREG-003 document_template_id=DOC-012")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELINK_PREVIEW", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-010",
                                 "document_template_id": "DOC-012"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("не поддерживается", msg)

    def test_forbidden_field_never_reaches_relink_document(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 object_id=OBJ-009 stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.relink_document") as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_not_called()

    def test_object_id_combined_with_document_template_id_still_rejected(self):
        """object_id remains forbidden even when combined with the now-
        allowed document_template_id — the presence of one forbidden
        key must still block the whole call."""
        update, context = _cmd(
            "/updatedoc document_id=DREG-003 object_id=OBJ-009 document_template_id=DOC-012",
        )

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.relink_document") as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("object_id", msg)


class TestUpdateDocRelinkModeConflict(unittest.TestCase):
    def test_relink_and_status_together_rejected(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 status=under_review stage_id=STAGE-014")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())

    def test_relink_and_admin_together_rejected(self):
        update, context = _cmd('/updatedoc document_id=DREG-003 name="X" roadmap_id=RM-003')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())

    def test_document_template_id_and_status_together_rejected(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 status=under_review document_template_id=DOC-012")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())

    def test_document_template_id_and_admin_together_rejected(self):
        update, context = _cmd('/updatedoc document_id=DREG-003 notes="x" document_template_id=DOC-012')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.updatedoc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())


class TestUpdateDocRelinkPreviewAndApply(unittest.TestCase):
    """The first call (no confirm=yes) must only preview — never write.
    The second call with confirm=yes must re-validate and apply."""

    def test_preview_call_does_not_write_and_shows_before_after(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELINK_PREVIEW", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-014"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        _, kwargs = mock_fn.call_args
        self.assertEqual(kwargs.get("dry_run"), True)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("STAGE-010", msg)
        self.assertIn("STAGE-014", msg)
        self.assertIn("confirm=yes", msg)
        self.assertIn("Drive", msg)

    def test_confirm_yes_calls_relink_document_with_dry_run_false(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 stage_id=STAGE-014 confirm=yes")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELATION_UPDATED", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-014"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        args, kwargs = mock_fn.call_args
        self.assertEqual(args[0], "DREG-003")
        self.assertEqual(kwargs.get("stage_id"), "STAGE-014")
        self.assertEqual(kwargs.get("dry_run"), False)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("Drive", msg)

    def test_document_not_found_before_calling_relink_document(self):
        update, context = _cmd("/updatedoc document_id=DREG-999 stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=None), \
             patch("business_core.business_builder.relink_document") as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("DREG-999", msg)

    def test_incompatible_stage_shows_error_not_preview(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 stage_id=STAGE-099")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                 "error": "Противоречие: Stage STAGE-099 принадлежит Roadmap RM-999, "
                                          "а указан Roadmap RM-003.",
                                 "roadmap_id": "", "stage_id": ""}):
            asyncio.run(th.updatedoc_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("STAGE-099", msg)

    def test_nonexistent_stage_shows_error_not_preview(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 stage_id=STAGE-999")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                 "error": "Stage STAGE-999 не найден.", "roadmap_id": "", "stage_id": ""}):
            asyncio.run(th.updatedoc_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("STAGE-999", msg)

    def test_roadmap_and_stage_changed_together(self):
        update, context = _cmd(
            "/updatedoc document_id=DREG-003 roadmap_id=RM-003 stage_id=STAGE-014 confirm=yes",
        )

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELATION_UPDATED", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-014"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        args, kwargs = mock_fn.call_args
        self.assertEqual(kwargs.get("roadmap_id"), "RM-003")
        self.assertEqual(kwargs.get("stage_id"), "STAGE-014")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)


class TestUpdateDocRelinkDocumentTemplateId(unittest.TestCase):
    """/updatedoc document_id=... document_template_id=DOC-012 — the
    newly-allowed relink field. Same preview/confirm shape as roadmap_id/
    stage_id."""

    def test_preview_shows_old_and_new_document_template_id(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 document_template_id=DOC-012")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELINK_PREVIEW", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-010",
                                 "document_template_id": "DOC-012"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        _, kwargs = mock_fn.call_args
        self.assertEqual(kwargs.get("document_template_id"), "DOC-012")
        self.assertEqual(kwargs.get("dry_run"), True)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("—", msg)  # старое -> новое formatting present
        self.assertIn("DOC-012", msg)
        self.assertIn("confirm=yes", msg)

    def test_confirm_yes_applies_document_template_id(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 document_template_id=DOC-012 confirm=yes")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": True, "code": "DOCUMENT_RELATION_UPDATED", "error": None,
                                 "roadmap_id": "RM-003", "stage_id": "STAGE-010",
                                 "document_template_id": "DOC-012"}) as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        args, kwargs = mock_fn.call_args
        self.assertEqual(args[0], "DREG-003")
        self.assertEqual(kwargs.get("document_template_id"), "DOC-012")
        self.assertEqual(kwargs.get("dry_run"), False)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("DOC-012", msg)

    def test_nonexistent_document_template_id_shows_error(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 document_template_id=DOC-999")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                 "error": "Document Template DOC-999 не найден.",
                                 "roadmap_id": "", "stage_id": "", "document_template_id": ""}):
            asyncio.run(th.updatedoc_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("DOC-999", msg)

    def test_incompatible_document_template_id_cross_business_shows_error(self):
        update, context = _cmd("/updatedoc document_id=DREG-003 document_template_id=DOC-EXT-001")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch("business_core.business_builder.relink_document",
                   return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                 "error": "Противоречие: Document Template DOC-EXT-001 принадлежит "
                                          "бизнесу BIZ-002, а указан Business BIZ-001.",
                                 "roadmap_id": "", "stage_id": "", "document_template_id": ""}):
            asyncio.run(th.updatedoc_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("DOC-EXT-001", msg)

    def test_document_not_found_before_calling_relink_document(self):
        update, context = _cmd("/updatedoc document_id=DREG-999 document_template_id=DOC-012")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.document_manager.find_document_by_id", return_value=None), \
             patch("business_core.business_builder.relink_document") as mock_fn:
            asyncio.run(th.updatedoc_cmd(update, context))

        mock_fn.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("DREG-999", msg)


# ────────────────────────────────────────────────────────────
# business_builder.relink_document() — orchestration unit tests
# ────────────────────────────────────────────────────────────

class TestRelinkDocumentOrchestration(unittest.TestCase):
    def test_dry_run_true_does_not_write(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": True, "code": "", "error": None,
                                        "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-014",
                                                     "document_template_id": ""}}), \
             patch("business_core.document_manager.update_document_relations") as mock_write:
            result = bb.relink_document("DREG-003", stage_id="STAGE-014", dry_run=True)

        mock_write.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELINK_PREVIEW")
        self.assertEqual(result["stage_id"], "STAGE-014")

    def test_dry_run_false_writes_via_update_document_relations(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": True, "code": "", "error": None,
                                        "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-014",
                                                     "document_template_id": ""}}), \
             patch("business_core.document_manager.update_document_relations",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Stage ID",),
                                 "code": "DOCUMENT_RELATION_UPDATED", "error": None}) as mock_write:
            result = bb.relink_document("DREG-003", stage_id="STAGE-014", dry_run=False)

        mock_write.assert_called_once_with(
            "DREG-003", {"Roadmap ID": "RM-003", "Stage ID": "STAGE-014", "Document Template ID": ""},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_UPDATED")

    def test_anchors_are_read_from_document_not_caller(self):
        """business_id/client_id/object_id must always come from the
        document's own row, never be caller-suppliable — relink_document()
        has no parameters for them at all. document_template_id IS a
        parameter (unlike these three) — it carries no Drive-path risk,
        see TestRelinkDocumentTemplateId below."""
        import business_core.business_builder as bb
        import inspect

        sig = inspect.signature(bb.relink_document)
        self.assertNotIn("business_id", sig.parameters)
        self.assertNotIn("client_id", sig.parameters)
        self.assertNotIn("object_id", sig.parameters)
        self.assertIn("document_template_id", sig.parameters)

    def test_incompatible_stage_blocked_before_write(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                        "error": "Противоречие: Stage STAGE-099 принадлежит Roadmap RM-999, "
                                                 "а указан Roadmap RM-003.", "resolved": None}), \
             patch("business_core.document_manager.update_document_relations") as mock_write:
            result = bb.relink_document("DREG-003", stage_id="STAGE-099", dry_run=False)

        mock_write.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_nonexistent_stage_blocked_before_write(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                        "error": "Stage STAGE-999 не найден.", "resolved": None}), \
             patch("business_core.document_manager.update_document_relations") as mock_write:
            result = bb.relink_document("DREG-003", stage_id="STAGE-999", dry_run=False)

        mock_write.assert_not_called()
        self.assertFalse(result["ok"])

    def test_document_not_found(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.relink_document("DREG-999", stage_id="STAGE-014", dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_drive_fields_and_identity_untouched_by_write_call(self):
        """The write path only ever sends Roadmap ID / Stage ID /
        Document Template ID — Drive File ID/URL, Document ID, Family
        ID, Version are never part of the payload passed to
        update_document_relations()."""
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": True, "code": "", "error": None,
                                        "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-014",
                                                     "document_template_id": ""}}), \
             patch("business_core.document_manager.update_document_relations",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Stage ID",),
                                 "code": "DOCUMENT_RELATION_UPDATED", "error": None}) as mock_write:
            bb.relink_document("DREG-003", stage_id="STAGE-014", dry_run=False)

        payload = mock_write.call_args[0][1]
        self.assertEqual(set(payload.keys()), {"Roadmap ID", "Stage ID", "Document Template ID"})


class TestRelinkDocumentTemplateId(unittest.TestCase):
    """relink_document(..., document_template_id=...) — the newly-
    allowed field. document_template_id carries no Object-ID-style
    Drive-path risk, so it is a real caller parameter (unlike
    business_id/client_id/object_id, which stay fixed anchors)."""

    def test_successful_assignment_to_dreg_003(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": True, "code": "", "error": None,
                                        "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-010",
                                                     "document_template_id": "DOC-012"}}), \
             patch("business_core.document_manager.update_document_relations",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Document Template ID",),
                                 "code": "DOCUMENT_RELATION_UPDATED", "error": None}) as mock_write:
            result = bb.relink_document("DREG-003", document_template_id="DOC-012", dry_run=False)

        mock_write.assert_called_once_with(
            "DREG-003",
            {"Roadmap ID": "RM-003", "Stage ID": "STAGE-010", "Document Template ID": "DOC-012"},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_UPDATED")
        self.assertEqual(result["document_template_id"], "DOC-012")

    def test_nonexistent_document_template_id_blocked_before_write(self):
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                        "error": "Document Template DOC-999 не найден.", "resolved": None}), \
             patch("business_core.document_manager.update_document_relations") as mock_write:
            result = bb.relink_document("DREG-003", document_template_id="DOC-999", dry_run=False)

        mock_write.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_incompatible_cross_business_document_template_id_blocked(self):
        """A Document Template ID that exists but belongs to a
        different Business than the document's own anchored
        business_id is a cross-entity mismatch, exactly like an
        incompatible Stage — reuses the same resolve_and_validate_links()
        Business-ownership check, no new validation code."""
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH",
                                        "error": "Противоречие: Document Template DOC-EXT-001 принадлежит "
                                                 "бизнесу BIZ-002, а указан Business BIZ-001.",
                                        "resolved": None}), \
             patch("business_core.document_manager.update_document_relations") as mock_write:
            result = bb.relink_document("DREG-003", document_template_id="DOC-EXT-001", dry_run=False)

        mock_write.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_document_template_id_none_keeps_current_value(self):
        """Not passing document_template_id must reuse the document's
        own current value, not clear it or pass None through to
        validation."""
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id",
                   return_value={**_RELINK_DOCUMENT, "document_template_id": "DOC-005"}), \
             patch.object(bb, "_validate_document_relations") as mock_validate, \
             patch("business_core.document_manager.update_document_relations",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Stage ID",),
                                 "code": "DOCUMENT_RELATION_UPDATED", "error": None}):
            mock_validate.return_value = {
                "ok": True, "code": "", "error": None,
                "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-014", "document_template_id": "DOC-005"},
            }
            bb.relink_document("DREG-003", stage_id="STAGE-014", dry_run=False)

        _, kwargs = mock_validate.call_args
        self.assertEqual(kwargs.get("document_template_id"), "DOC-005")

    def test_drive_and_identity_fields_preserved_across_template_relink(self):
        """Changing only document_template_id must never touch Drive
        File ID/URL, Document ID, Family ID, Version, Business/Client/
        Object ID — those aren't even in the write payload."""
        import business_core.business_builder as bb

        with patch("business_core.document_manager.find_document_by_id", return_value=dict(_RELINK_DOCUMENT)), \
             patch.object(bb, "_validate_document_relations",
                          return_value={"ok": True, "code": "", "error": None,
                                        "resolved": {"roadmap_id": "RM-003", "stage_id": "STAGE-010",
                                                     "document_template_id": "DOC-012"}}), \
             patch("business_core.document_manager.update_document_relations",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Document Template ID",),
                                 "code": "DOCUMENT_RELATION_UPDATED", "error": None}) as mock_write:
            bb.relink_document("DREG-003", document_template_id="DOC-012", dry_run=False)

        payload = mock_write.call_args[0][1]
        self.assertEqual(set(payload.keys()), {"Roadmap ID", "Stage ID", "Document Template ID"})
        self.assertNotIn("Drive File ID", payload)
        self.assertNotIn("Drive File URL", payload)
        self.assertNotIn("Document ID", payload)
        self.assertNotIn("Document Family ID", payload)
        self.assertNotIn("Version", payload)
        self.assertNotIn("Business ID", payload)
        self.assertNotIn("Client ID", payload)
        self.assertNotIn("Object ID", payload)


# ────────────────────────────────────────────────────────────
# document_manager.update_document_relations() — low-level unit tests
# ────────────────────────────────────────────────────────────

class TestUpdateDocumentRelations(unittest.TestCase):
    def test_unknown_field_rejected(self):
        import business_core.document_manager as dm

        result = dm.update_document_relations("DREG-003", {"Object ID": "OBJ-009"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_FIELD_NOT_RELINKABLE")

    def test_business_id_field_rejected(self):
        import business_core.document_manager as dm

        result = dm.update_document_relations("DREG-003", {"Business ID": "BIZ-002"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_FIELD_NOT_RELINKABLE")

    def test_document_not_found(self):
        import business_core.document_manager as dm

        with patch.object(dm, "_find_document_row", return_value=None):
            result = dm.update_document_relations("DREG-999", {"Stage ID": "STAGE-014"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_document_template_id_is_allowed(self):
        import business_core.document_manager as dm

        current = {"Roadmap ID": "RM-003", "Stage ID": "STAGE-010", "Document Template ID": ""}
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = ["Roadmap ID", "Stage ID", "Document Template ID", "Updated At"]

        with patch.object(dm, "_find_document_row", return_value=(5, current)), \
             patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.get_header_index_map",
                   return_value={"Roadmap ID": 0, "Stage ID": 1, "Document Template ID": 2, "Updated At": 3}):
            result = dm.update_document_relations("DREG-003", {"Document Template ID": "DOC-012"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Document Template ID",))
        mock_sheet.update_cell.assert_any_call(5, 3, "DOC-012")

    def test_writes_only_stage_id_when_roadmap_unchanged(self):
        import business_core.document_manager as dm

        current = {"Roadmap ID": "RM-003", "Stage ID": "STAGE-010"}
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = ["Roadmap ID", "Stage ID", "Updated At"]

        with patch.object(dm, "_find_document_row", return_value=(5, current)), \
             patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.get_header_index_map",
                   return_value={"Roadmap ID": 0, "Stage ID": 1, "Updated At": 2}):
            result = dm.update_document_relations(
                "DREG-003", {"Roadmap ID": "RM-003", "Stage ID": "STAGE-014"},
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Stage ID",))
        mock_sheet.update_cell.assert_any_call(5, 2, "STAGE-014")

    def test_unchanged_values_produce_no_write(self):
        import business_core.document_manager as dm

        current = {"Roadmap ID": "RM-003", "Stage ID": "STAGE-010"}
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = ["Roadmap ID", "Stage ID", "Updated At"]

        with patch.object(dm, "_find_document_row", return_value=(5, current)), \
             patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.get_header_index_map",
                   return_value={"Roadmap ID": 0, "Stage ID": 1, "Updated At": 2}):
            result = dm.update_document_relations(
                "DREG-003", {"Roadmap ID": "RM-003", "Stage ID": "STAGE-010"},
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_UNCHANGED")
        mock_sheet.update_cell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
