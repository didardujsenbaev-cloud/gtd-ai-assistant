"""
Phase 39D — Payment Caller UX (ADR-022): tests for the centralized
result-code -> Russian message mapping in business_core/
telegram_handlers.py — the 10 Payment message-mapping helpers — plus
the 14 operational commands' async behavior (parser-validation
ordering, canonical-boundary-only calls, no raw exception/dict
exposure) and `/milestones` preservation.

Pure presentation-layer tests for the message helpers: every mapping
case feeds a pre-built structured result dict (never a live
orchestration call) and asserts on the rendered Russian string only.
Async command tests mock business_builder/payment_manager at the call
site. No network, no Google Sheets. Registered in conftest.py's hard
socket-block set before this file's logic was written.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.telegram_handlers as th


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    # Phase 17E-1: the six enforced read commands (payment_cmd/
    # obligation_cmd among them) now run a transport preflight before
    # anything else, requiring a real private-chat shape — a bare
    # MagicMock() auto-attribute is truthy and not "private", so it
    # must be set explicitly for these fixtures to still exercise the
    # command's real behavior instead of being rejected at preflight.
    update.effective_chat = SimpleNamespace(type="private")
    return update


def _cmd(cmdline: str):
    update = _upd(cmdline)
    context = MagicMock()
    context.user_data = {}
    context.args = cmdline.split()[1:]
    return update, context


def _run(coro):
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
        return asyncio.run(coro)


def _sent_text(update) -> str:
    call = update.message.reply_text.call_args
    return call.args[0] if call.args else call.kwargs.get("text", "")


def _sent_parse_mode(update):
    call = update.message.reply_text.call_args
    return call.kwargs.get("parse_mode", "NOT_SET")


# ────────────────────────────────────────────────────────────
# Template creation message mapping
# ────────────────────────────────────────────────────────────

class TestPaymentTemplateCreationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {"ok": True, "code": "COMMERCIAL_MILESTONE_TEMPLATE_CREATED", "error": None, "commercial_milestone_template_id": "PMT-001", "final_status": "active", "amount": "150000.00", "currency": "KZT"}
        msg = th._payment_template_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("PMT-001", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "COMMERCIAL_MILESTONE_TEMPLATE_REUSED", "error": None, "commercial_milestone_template_id": "PMT-002", "final_status": "active"}
        msg = th._payment_template_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_multiple_matches_lists_all_ids_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_COMMERCIAL_MILESTONE_TEMPLATE_MATCHES", "error": "x", "conflicting_ids": ("PMT-001", "PMT-002")}
        msg = th._payment_template_creation_message(result)
        self.assertIn("PMT-001", msg)
        self.assertIn("PMT-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_calculation_errors(self):
        for code in ("INVALID_MILESTONE_CALCULATION_TYPE", "MILESTONE_FIXED_AMOUNT_REQUIRED", "MILESTONE_PERCENTAGE_REQUIRED", "MILESTONE_CALCULATION_FIELDS_CONFLICT"):
            msg = th._payment_template_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_amount_currency_errors(self):
        for code in ("INVALID_PAYMENT_AMOUNT", "INVALID_PAYMENT_AMOUNT_SCALE", "PAYMENT_AMOUNT_MUST_BE_POSITIVE", "INVALID_PAYMENT_CURRENCY"):
            msg = th._payment_template_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_relation_errors(self):
        for code in ("ROADMAP_NOT_FOUND", "SERVICE_NOT_FOUND", "PAYMENT_ENTITY_RELATION_MISMATCH"):
            msg = th._payment_template_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_persistence_and_verification_failure_not_success(self):
        for code in ("PAYMENT_PERSISTENCE_FAILED", "COMMERCIAL_MILESTONE_TEMPLATE_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._payment_template_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)

    def test_bare_validation_error_no_code(self):
        msg = th._payment_template_creation_message({"ok": False, "code": "", "error": "title обязателен"})
        self.assertIn("❌", msg)
        self.assertIn("title", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._payment_template_creation_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "internal detail"})
        self.assertIn("❌", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)


class TestPaymentTemplateStatusMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UPDATED", "error": None, "previous_status": "active", "final_status": "inactive"}
        msg = th._payment_template_status_message(result, "PMT-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        result = {"ok": True, "code": "COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UNCHANGED", "error": None, "previous_status": "active"}
        msg = th._payment_template_status_message(result, "PMT-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._payment_template_status_message({"ok": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": "x"}, "PMT-999")
        self.assertIn("❌", msg)

    def test_restore_blocked(self):
        result = {"ok": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_RESTORE_REQUIRES_EXPLICIT_ACTION", "error": "x", "previous_status": "archived"}
        msg = th._payment_template_status_message(result, "PMT-001")
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_invalid_status(self):
        msg = th._payment_template_status_message({"ok": False, "code": "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS", "error": "x"}, "PMT-001")
        self.assertIn("❌", msg)


class TestPaymentTemplateAdminMessageMapping(unittest.TestCase):
    def test_updated(self):
        msg = th._payment_template_admin_message({"ok": True, "changed": True, "code": ""}, "PMT-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        msg = th._payment_template_admin_message({"ok": True, "changed": False, "code": ""}, "PMT-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._payment_template_admin_message({"ok": False, "code": "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "error": "x"}, "PMT-999")
        self.assertIn("❌", msg)

    def test_immutable_identity_conflict(self):
        msg = th._payment_template_admin_message({"ok": False, "code": "PAYMENT_TRANSACTION_IMMUTABLE", "error": "x"}, "PMT-001")
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# Obligation message mapping
# ────────────────────────────────────────────────────────────

class TestPaymentObligationCreationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {"ok": True, "code": "PAYMENT_OBLIGATION_CREATED", "error": None, "payment_obligation_id": "POB-001", "amount": "150000.00", "currency": "KZT", "final_status": "draft"}
        msg = th._payment_obligation_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("POB-001", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "PAYMENT_OBLIGATION_REUSED", "error": None, "payment_obligation_id": "POB-002", "amount": "1.00", "currency": "KZT", "paid_amount": "0.00", "final_status": "draft"}
        msg = th._payment_obligation_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_relation_errors(self):
        for code in ("BUSINESS_NOT_FOUND", "CLIENT_NOT_FOUND", "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND", "ROADMAP_NOT_FOUND", "STAGE_NOT_FOUND", "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND", "PAYMENT_OBLIGATION_RELATION_MISMATCH", "PAYMENT_ENTITY_RELATION_MISMATCH"):
            msg = th._payment_obligation_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_idempotency_conflict(self):
        msg = th._payment_obligation_creation_message({"ok": False, "code": "PAYMENT_OBLIGATION_IDEMPOTENCY_CONFLICT", "error": "x"})
        self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids(self):
        result = {"ok": False, "code": "MULTIPLE_PAYMENT_OBLIGATION_MATCHES", "error": "x", "conflicting_ids": ("POB-001", "POB-002")}
        msg = th._payment_obligation_creation_message(result)
        self.assertIn("POB-001", msg)
        self.assertIn("POB-002", msg)

    def test_amount_currency_errors(self):
        for code in ("INVALID_PAYMENT_AMOUNT", "INVALID_PAYMENT_AMOUNT_SCALE", "PAYMENT_AMOUNT_MUST_BE_POSITIVE", "INVALID_PAYMENT_CURRENCY"):
            msg = th._payment_obligation_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_persistence_and_verification_failure_not_success(self):
        for code in ("PAYMENT_OBLIGATION_PERSISTENCE_FAILED", "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._payment_obligation_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)


class TestPaymentObligationStatusMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "PAYMENT_OBLIGATION_STATUS_UPDATED", "error": None, "previous_status": "draft", "final_status": "issued"}
        msg = th._payment_obligation_status_message(result, "POB-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        result = {"ok": True, "code": "PAYMENT_OBLIGATION_STATUS_UNCHANGED", "error": None, "previous_status": "draft"}
        msg = th._payment_obligation_status_message(result, "POB-001")
        self.assertIn("ℹ️", msg)

    def test_manual_partially_paid_paid_rejected(self):
        msg = th._payment_obligation_status_message({"ok": False, "code": "INVALID_PAYMENT_OBLIGATION_TRANSITION", "error": "x", "previous_status": "issued"}, "POB-001")
        self.assertIn("❌", msg)

    def test_cancellation_with_confirmed_payments_blocked(self):
        result = {"ok": False, "code": "PAYMENT_OBLIGATION_HAS_CONFIRMED_PAYMENTS", "error": "x", "paid_amount": "50000.00"}
        msg = th._payment_obligation_status_message(result, "POB-001")
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_not_found(self):
        msg = th._payment_obligation_status_message({"ok": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "x"}, "POB-999")
        self.assertIn("❌", msg)


class TestPaymentObligationAdminMessageMapping(unittest.TestCase):
    def test_updated(self):
        msg = th._payment_obligation_admin_message({"ok": True, "changed": True, "code": ""}, "POB-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        msg = th._payment_obligation_admin_message({"ok": True, "changed": False, "code": ""}, "POB-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._payment_obligation_admin_message({"ok": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "x"}, "POB-999")
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# Transaction message mapping
# ────────────────────────────────────────────────────────────

class TestPaymentTransactionCreationMessageMapping(unittest.TestCase):
    def test_created_shows_pending(self):
        result = {"ok": True, "code": "PAYMENT_TRANSACTION_CREATED", "error": None, "payment_transaction_id": "PTXN-001", "payment_obligation_id": "POB-001", "amount": "50000.00", "currency": "KZT", "final_status": "pending"}
        msg = th._payment_transaction_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("pending", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "PAYMENT_TRANSACTION_REUSED", "error": None, "payment_transaction_id": "PTXN-002", "final_status": "pending"}
        msg = th._payment_transaction_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_idempotency_required_and_conflict(self):
        msg1 = th._payment_transaction_creation_message({"ok": False, "code": "PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED", "error": None})
        self.assertIn("❌", msg1)
        msg2 = th._payment_transaction_creation_message({"ok": False, "code": "PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT", "error": "x", "conflicting_ids": ("PTXN-009",)})
        self.assertIn("PTXN-009", msg2)

    def test_relation_client_currency_errors(self):
        for code in ("BUSINESS_NOT_FOUND", "PAYMENT_OBLIGATION_NOT_FOUND", "CLIENT_NOT_FOUND", "DOCUMENT_NOT_FOUND", "PAYMENT_ENTITY_RELATION_MISMATCH", "PAYMENT_CURRENCY_MISMATCH"):
            msg = th._payment_transaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids(self):
        result = {"ok": False, "code": "MULTIPLE_PAYMENT_TRANSACTION_MATCHES", "error": "x", "conflicting_ids": ("PTXN-001", "PTXN-002")}
        msg = th._payment_transaction_creation_message(result)
        self.assertIn("PTXN-001", msg)
        self.assertIn("PTXN-002", msg)

    def test_persistence_verification_failure_not_success(self):
        for code in ("PAYMENT_TRANSACTION_PERSISTENCE_FAILED", "PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._payment_transaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)


class TestPaymentTransactionConfirmationMessageMapping(unittest.TestCase):
    def test_confirmed_success(self):
        result = {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None, "paid_amount": "50000.00", "remaining_amount": "100000.00", "currency": "KZT"}
        msg = th._payment_transaction_confirmation_message(result, "PTXN-001")
        self.assertIn("✅", msg)

    def test_no_op(self):
        msg = th._payment_transaction_confirmation_message({"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", "error": None}, "PTXN-001")
        self.assertIn("ℹ️", msg)

    def test_overpayment_block(self):
        result = {"ok": False, "code": "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED", "error": "x", "amount": "999999.00", "remaining_amount": "100.00"}
        msg = th._payment_transaction_confirmation_message(result, "PTXN-001")
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_metadata_required(self):
        msg = th._payment_transaction_confirmation_message({"ok": False, "code": "PAYMENT_TRANSACTION_CONFIRMATION_METADATA_REQUIRED", "error": None}, "PTXN-001")
        self.assertIn("❌", msg)

    def test_partial_failure_not_success(self):
        msg = th._payment_transaction_confirmation_message({"ok": False, "code": "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED", "error": "x"}, "PTXN-001")
        self.assertNotIn("✅", msg)

    def test_ledger_read_failed_fixed_message(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": False, "code": "PAYMENT_LEDGER_READ_FAILED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось проверить историю платежей.")

    def test_ledger_read_failed_no_error_or_amounts_rendered(self):
        msg = th._payment_transaction_confirmation_message(
            {
                "ok": False, "code": "PAYMENT_LEDGER_READ_FAILED", "error": "Infrastructure failure LEDGER-SECRET",
                "amount": "999999.00 BALANCE-SECRET", "remaining_amount": "1.00 BALANCE-SECRET",
            },
            "PTXN-001",
        )
        self.assertNotIn("Infrastructure failure", msg)
        self.assertNotIn("LEDGER-SECRET", msg)
        self.assertNotIn("BALANCE-SECRET", msg)
        self.assertNotIn("999999.00", msg)
        self.assertNotIn("✅", msg)
        self.assertNotIn("ℹ️", msg)


class TestPaymentTransactionReversalMessageMapping(unittest.TestCase):
    def test_reversed_success(self):
        result = {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None, "paid_amount": "0.00", "remaining_amount": "150000.00", "currency": "KZT"}
        msg = th._payment_transaction_reversal_message(result, "PTXN-001")
        self.assertIn("✅", msg)

    def test_no_op(self):
        msg = th._payment_transaction_reversal_message({"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", "error": None}, "PTXN-001")
        self.assertIn("ℹ️", msg)

    def test_reason_required(self):
        msg = th._payment_transaction_reversal_message({"ok": False, "code": "PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED", "error": None}, "PTXN-001")
        self.assertIn("❌", msg)

    def test_never_echoes_reversal_reason(self):
        result = {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None, "paid_amount": "0.00", "remaining_amount": "1.00", "currency": "KZT"}
        msg = th._payment_transaction_reversal_message(result, "PTXN-001")
        self.assertNotIn("client requested a secret refund reason", msg)

    def test_immutability_failure(self):
        msg = th._payment_transaction_reversal_message({"ok": False, "code": "PAYMENT_TRANSACTION_IMMUTABLE", "error": "x"}, "PTXN-001")
        self.assertNotIn("✅", msg)


class TestPaymentTransactionFailureMessageMapping(unittest.TestCase):
    def test_failed(self):
        msg = th._payment_transaction_failure_message({"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None, "previous_status": "pending"}, "PTXN-001")
        self.assertIn("✅", msg)

    def test_no_op(self):
        msg = th._payment_transaction_failure_message({"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_FAILED", "error": None, "previous_status": "failed"}, "PTXN-001")
        self.assertIn("ℹ️", msg)

    def test_invalid_transition(self):
        msg = th._payment_transaction_failure_message({"ok": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "x"}, "PTXN-001")
        self.assertIn("❌", msg)


_H1_SECRET_MARKERS = ("LEDGER-SECRET", "TRANSACTION-SECRET", "OBLIGATION-SECRET", "BALANCE-SECRET", "API-PAYLOAD-SECRET", "REVERSAL-SECRET")


class TestPaymentTransactionConfirmationMessageHardening(unittest.TestCase):
    """Phase 17E-2A6-H1: comprehensive hardened-mapper battery,
    mirroring the Document/Offer Notes mapper convention."""

    def test_valid_success(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None, "paid_amount": "1.00", "remaining_amount": "1.00", "currency": "KZT"}, "PTXN-001",
        )
        self.assertIn("✅", msg)

    def test_valid_unchanged(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", "error": None}, "PTXN-001",
        )
        self.assertIn("ℹ️", msg)

    def test_ok_false_with_success_code_never_success(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertNotIn("✅", msg)
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_ok_false_with_unchanged_code_never_unchanged_ux(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertNotIn("ℹ️", msg)
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_missing_ok(self):
        msg = th._payment_transaction_confirmation_message({"changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_missing_changed(self):
        msg = th._payment_transaction_confirmation_message({"ok": True, "code": "PAYMENT_TRANSACTION_CONFIRMED"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_blank_code(self):
        msg = th._payment_transaction_confirmation_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_unknown_code(self):
        msg = th._payment_transaction_confirmation_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_infrastructure_failure_never_rendered(self):
        msg = th._payment_transaction_confirmation_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_arbitrary_secret_marker_error_never_rendered(self):
        for marker in _H1_SECRET_MARKERS:
            with self.subTest(marker=marker):
                msg = th._payment_transaction_confirmation_message({"ok": False, "code": "", "error": f"boom {marker}"}, "PTXN-001")
                self.assertNotIn(marker, msg)

    def test_invalid_transition_error_never_rendered(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "raw LEDGER-SECRET"}, "PTXN-001",
        )
        self.assertNotIn("LEDGER-SECRET", msg)
        self.assertEqual(msg, "❌ Подтверждение возможно только из статуса pending.")

    def test_empty_dict(self):
        self.assertEqual(th._payment_transaction_confirmation_message({}, "PTXN-001"), "❌ Не удалось подтвердить Payment.")

    def test_none_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_confirmation_message(None, "PTXN-001"), "❌ Не удалось подтвердить Payment.")

    def test_string_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_confirmation_message("not a dict", "PTXN-001"), "❌ Не удалось подтвердить Payment.")

    def test_list_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_confirmation_message(["ok", True], "PTXN-001"), "❌ Не удалось подтвердить Payment.")

    def test_integer_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_confirmation_message(42, "PTXN-001"), "❌ Не удалось подтвердить Payment.")

    def test_ok_truthy_string_not_treated_as_true(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": "true", "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_ok_truthy_int_not_treated_as_true(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": 1, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_changed_falsy_string_not_treated_as_false(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": True, "changed": "false", "code": "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_changed_truthy_int_not_treated_as_true(self):
        msg = th._payment_transaction_confirmation_message(
            {"ok": True, "changed": 1, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось подтвердить Payment.")

    def test_fallback_log_is_fixed_literal(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_confirmation_message({"ok": False, "code": "UNMAPPED_XYZ", "error": "leak-LEDGER-SECRET"}, "PTXN-001")
        mock_warn.assert_called_once_with("_payment_transaction_confirmation_message unmapped safe fallback")
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                self.assertNotIn("LEDGER-SECRET", str(arg))
                self.assertNotIn("UNMAPPED_XYZ", str(arg))

    def test_known_branch_does_not_log(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_confirmation_message({"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None}, "PTXN-001")
        mock_warn.assert_not_called()


class TestPaymentTransactionReversalMessageHardening(unittest.TestCase):
    def test_valid_success(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None, "paid_amount": "1.00", "remaining_amount": "1.00", "currency": "KZT"}, "PTXN-001",
        )
        self.assertIn("✅", msg)

    def test_valid_unchanged(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", "error": None}, "PTXN-001",
        )
        self.assertIn("ℹ️", msg)

    def test_ok_false_with_success_code_never_success(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertNotIn("✅", msg)
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_ok_false_with_unchanged_code_never_unchanged_ux(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertNotIn("ℹ️", msg)
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_missing_ok(self):
        msg = th._payment_transaction_reversal_message({"changed": True, "code": "PAYMENT_TRANSACTION_REVERSED"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_missing_changed(self):
        msg = th._payment_transaction_reversal_message({"ok": True, "code": "PAYMENT_TRANSACTION_REVERSED"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_blank_code(self):
        msg = th._payment_transaction_reversal_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_unknown_code(self):
        msg = th._payment_transaction_reversal_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_infrastructure_failure_never_rendered(self):
        msg = th._payment_transaction_reversal_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_arbitrary_secret_marker_error_never_rendered(self):
        for marker in _H1_SECRET_MARKERS:
            with self.subTest(marker=marker):
                msg = th._payment_transaction_reversal_message({"ok": False, "code": "", "error": f"boom {marker}"}, "PTXN-001")
                self.assertNotIn(marker, msg)

    def test_invalid_transition_error_never_rendered(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "raw REVERSAL-SECRET"}, "PTXN-001",
        )
        self.assertNotIn("REVERSAL-SECRET", msg)
        self.assertEqual(msg, "❌ Реверс возможен только из статуса confirmed.")

    def test_empty_dict(self):
        self.assertEqual(th._payment_transaction_reversal_message({}, "PTXN-001"), "❌ Не удалось реверснуть Payment.")

    def test_none_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_reversal_message(None, "PTXN-001"), "❌ Не удалось реверснуть Payment.")

    def test_string_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_reversal_message("not a dict", "PTXN-001"), "❌ Не удалось реверснуть Payment.")

    def test_list_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_reversal_message(["ok", True], "PTXN-001"), "❌ Не удалось реверснуть Payment.")

    def test_integer_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_reversal_message(42, "PTXN-001"), "❌ Не удалось реверснуть Payment.")

    def test_ok_truthy_string_not_treated_as_true(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": "true", "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_ok_truthy_int_not_treated_as_true(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": 1, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_changed_falsy_string_not_treated_as_false(self):
        msg = th._payment_transaction_reversal_message(
            {"ok": True, "changed": "false", "code": "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось реверснуть Payment.")

    def test_fallback_log_is_fixed_literal(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_reversal_message({"ok": False, "code": "UNMAPPED_XYZ", "error": "leak-REVERSAL-SECRET"}, "PTXN-001")
        mock_warn.assert_called_once_with("_payment_transaction_reversal_message unmapped safe fallback")
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                self.assertNotIn("REVERSAL-SECRET", str(arg))
                self.assertNotIn("UNMAPPED_XYZ", str(arg))

    def test_known_branch_does_not_log(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_reversal_message({"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None}, "PTXN-001")
        mock_warn.assert_not_called()


class TestPaymentTransactionFailureMessageHardening(unittest.TestCase):
    def test_valid_success(self):
        msg = th._payment_transaction_failure_message(
            {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001",
        )
        self.assertIn("✅", msg)

    def test_valid_unchanged(self):
        msg = th._payment_transaction_failure_message(
            {"ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001",
        )
        self.assertIn("ℹ️", msg)

    def test_ok_false_with_failed_code_never_success_or_unchanged(self):
        msg = th._payment_transaction_failure_message(
            {"ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_FAILED", "error": "Infrastructure failure"}, "PTXN-001",
        )
        self.assertNotIn("✅", msg)
        self.assertNotIn("ℹ️", msg)
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_ok_true_changed_missing_never_success(self):
        msg = th._payment_transaction_failure_message({"ok": True, "code": "PAYMENT_TRANSACTION_FAILED"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_blank_code(self):
        msg = th._payment_transaction_failure_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_unknown_code(self):
        msg = th._payment_transaction_failure_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "PTXN-001")
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_infrastructure_failure_never_rendered(self):
        msg = th._payment_transaction_failure_message({"ok": False, "code": "", "error": "Infrastructure failure"}, "PTXN-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_arbitrary_secret_marker_error_never_rendered(self):
        for marker in _H1_SECRET_MARKERS:
            with self.subTest(marker=marker):
                msg = th._payment_transaction_failure_message({"ok": False, "code": "", "error": f"boom {marker}"}, "PTXN-001")
                self.assertNotIn(marker, msg)

    def test_invalid_transition_error_never_rendered(self):
        msg = th._payment_transaction_failure_message(
            {"ok": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "raw TRANSACTION-SECRET"}, "PTXN-001",
        )
        self.assertNotIn("TRANSACTION-SECRET", msg)
        self.assertEqual(msg, "❌ Переход в failed возможен только из статуса pending.")

    def test_empty_dict(self):
        self.assertEqual(th._payment_transaction_failure_message({}, "PTXN-001"), "❌ Не удалось обновить статус Payment.")

    def test_none_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_failure_message(None, "PTXN-001"), "❌ Не удалось обновить статус Payment.")

    def test_string_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_failure_message("not a dict", "PTXN-001"), "❌ Не удалось обновить статус Payment.")

    def test_list_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_failure_message(["ok", True], "PTXN-001"), "❌ Не удалось обновить статус Payment.")

    def test_integer_result_does_not_raise(self):
        self.assertEqual(th._payment_transaction_failure_message(42, "PTXN-001"), "❌ Не удалось обновить статус Payment.")

    def test_ok_truthy_string_not_treated_as_true(self):
        msg = th._payment_transaction_failure_message(
            {"ok": "true", "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_ok_truthy_int_not_treated_as_true(self):
        msg = th._payment_transaction_failure_message(
            {"ok": 1, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_changed_falsy_string_not_treated_as_false(self):
        msg = th._payment_transaction_failure_message(
            {"ok": True, "changed": "false", "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001",
        )
        self.assertEqual(msg, "❌ Не удалось обновить статус Payment.")

    def test_fallback_log_is_fixed_literal(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_failure_message({"ok": False, "code": "UNMAPPED_XYZ", "error": "leak-BALANCE-SECRET"}, "PTXN-001")
        mock_warn.assert_called_once_with("_payment_transaction_failure_message unmapped safe fallback")
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                self.assertNotIn("BALANCE-SECRET", str(arg))
                self.assertNotIn("UNMAPPED_XYZ", str(arg))

    def test_known_branch_does_not_log(self):
        with patch("business_core.telegram_handlers.log.warning") as mock_warn:
            th._payment_transaction_failure_message({"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}, "PTXN-001")
        mock_warn.assert_not_called()


# ────────────────────────────────────────────────────────────
# Status labels
# ────────────────────────────────────────────────────────────

class TestStatusLabels(unittest.TestCase):
    def test_template_labels(self):
        for status in ("active", "inactive", "archived"):
            label = th._payment_template_status_ru(status)
            self.assertIn(status, label)

    def test_obligation_labels(self):
        for status in ("draft", "issued", "partially_paid", "paid", "cancelled", "archived"):
            label = th._payment_obligation_status_ru(status)
            self.assertIn(status, label)

    def test_transaction_labels(self):
        for status in ("pending", "confirmed", "reversed", "failed"):
            label = th._payment_transaction_status_ru(status)
            self.assertIn(status, label)

    def test_unknown_status_safe(self):
        label = th._payment_obligation_status_ru("some_future_status")
        self.assertIn("some_future_status", label)


class TestMoneyRendering(unittest.TestCase):
    def test_amount_and_currency_together(self):
        rendered = th._format_payment_amount("150000.00", "KZT")
        self.assertIn("150000.00", rendered)
        self.assertIn("KZT", rendered)

    def test_no_float_conversion(self):
        rendered = th._format_payment_amount("150000.00", "KZT")
        self.assertNotIn("150000.0 ", rendered)


# ────────────────────────────────────────────────────────────
# Async command tests: registration, parser ordering, canonical
# boundaries, privacy, parse-mode.
# ────────────────────────────────────────────────────────────

_PAYMENT_COMMANDS = (
    "newpaymenttemplate_cmd", "paymenttemplates_cmd", "paymenttemplate_cmd", "updatepaymenttemplate_cmd",
    "newobligation_cmd", "obligations_cmd", "obligation_cmd", "updateobligation_cmd",
    "recordpayment_cmd", "payments_cmd", "payment_cmd",
    "confirmpayment_cmd", "reversepayment_cmd", "failpayment_cmd",
)


class TestCommandRegistration(unittest.TestCase):
    def test_all_15_commands_registered_exactly_once(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        names = (
            "newpaymenttemplate", "paymenttemplates", "paymenttemplate", "updatepaymenttemplate",
            "newobligation", "obligations", "obligation", "updateobligation", "updateobligationnotes",
            "recordpayment", "payments", "payment", "confirmpayment", "reversepayment", "failpayment",
        )
        for name in names:
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_registered_exactly_once(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)

    def test_no_namespace_collision(self):
        import re
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        all_registered = re.findall(r'CommandHandler\("([a-zA-Z0-9_]+)"', src)
        counts: dict[str, int] = {}
        for name in all_registered:
            counts[name] = counts.get(name, 0) + 1
        payment_names = {
            "newpaymenttemplate", "paymenttemplates", "paymenttemplate", "updatepaymenttemplate",
            "newobligation", "obligations", "obligation", "updateobligation",
            "recordpayment", "payments", "payment", "confirmpayment", "reversepayment", "failpayment",
        }
        for name in payment_names:
            self.assertEqual(counts.get(name, 0), 1, f"/{name} must appear exactly once across all registrations")

    def test_no_collision_with_task_command(self):
        path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn('CommandHandler("bctasks"', src)
        self.assertNotIn('CommandHandler("tasks"', src)


class TestParserValidationOrdering(unittest.TestCase):
    """Insufficient arguments must return before any orchestration call."""

    def test_newpaymenttemplate_missing_fields(self):
        update, context = _cmd("/newpaymenttemplate")
        with patch("business_core.business_builder.create_commercial_milestone_template") as mock_create:
            _run(th.newpaymenttemplate_cmd(update, context))
        mock_create.assert_not_called()
        self.assertIn("❌", _sent_text(update))

    def test_updatepaymenttemplate_missing_id(self):
        update, context = _cmd("/updatepaymenttemplate")
        with patch("business_core.business_builder.transition_commercial_milestone_template_status") as mock_t, \
             patch("business_core.business_builder.update_commercial_milestone_template_admin_fields") as mock_a:
            _run(th.updatepaymenttemplate_cmd(update, context))
        mock_t.assert_not_called()
        mock_a.assert_not_called()

    def test_updatepaymenttemplate_missing_mode(self):
        update, context = _cmd("/updatepaymenttemplate commercial_milestone_template_id=PMT-001")
        with patch("business_core.business_builder.transition_commercial_milestone_template_status") as mock_t, \
             patch("business_core.business_builder.update_commercial_milestone_template_admin_fields") as mock_a:
            _run(th.updatepaymenttemplate_cmd(update, context))
        mock_t.assert_not_called()
        mock_a.assert_not_called()

    def test_newobligation_missing_fields(self):
        update, context = _cmd("/newobligation")
        with patch("business_core.business_builder.create_payment_obligation") as mock_create:
            _run(th.newobligation_cmd(update, context))
        mock_create.assert_not_called()

    def test_newobligation_missing_idempotency_source(self):
        update, context = _cmd("/newobligation business_id=BIZ-001 client_id=PRS-001 amount=100 currency=KZT")
        with patch("business_core.business_builder.create_payment_obligation") as mock_create:
            _run(th.newobligation_cmd(update, context))
        mock_create.assert_not_called()

    def test_updateobligation_missing_id(self):
        update, context = _cmd("/updateobligation")
        with patch("business_core.business_builder.transition_payment_obligation_status") as mock_t, \
             patch("business_core.business_builder.update_payment_obligation_admin_fields") as mock_a:
            _run(th.updateobligation_cmd(update, context))
        mock_t.assert_not_called()
        mock_a.assert_not_called()

    def test_updateobligation_missing_mode(self):
        update, context = _cmd("/updateobligation payment_obligation_id=POB-001")
        with patch("business_core.business_builder.transition_payment_obligation_status") as mock_t:
            _run(th.updateobligation_cmd(update, context))
        mock_t.assert_not_called()

    def test_recordpayment_missing_fields(self):
        update, context = _cmd("/recordpayment")
        with patch("business_core.business_builder.create_payment_transaction") as mock_create:
            _run(th.recordpayment_cmd(update, context))
        mock_create.assert_not_called()

    def test_recordpayment_missing_idempotency_source(self):
        update, context = _cmd(
            "/recordpayment business_id=BIZ-001 payment_obligation_id=POB-001 client_id=PRS-001 "
            "amount=100 currency=KZT payment_date=2026-01-01"
        )
        with patch("business_core.business_builder.create_payment_transaction") as mock_create:
            _run(th.recordpayment_cmd(update, context))
        mock_create.assert_not_called()

    def test_confirmpayment_missing_id(self):
        update, context = _cmd("/confirmpayment")
        with patch("business_core.business_builder.confirm_payment_transaction") as mock_confirm:
            _run(th.confirmpayment_cmd(update, context))
        mock_confirm.assert_not_called()

    def test_reversepayment_missing_reason(self):
        update, context = _cmd("/reversepayment payment_transaction_id=PTXN-001")
        with patch("business_core.business_builder.reverse_payment_transaction") as mock_reverse:
            _run(th.reversepayment_cmd(update, context))
        mock_reverse.assert_not_called()

    def test_failpayment_missing_id(self):
        update, context = _cmd("/failpayment")
        with patch("business_core.business_builder.fail_payment_transaction") as mock_fail:
            _run(th.failpayment_cmd(update, context))
        mock_fail.assert_not_called()


class TestCanonicalBoundaries(unittest.TestCase):
    def test_newpaymenttemplate_calls_business_builder_only(self):
        update, context = _cmd(
            "/newpaymenttemplate title=T calculation_type=fixed fixed_amount=100 currency=KZT roadmap_template_id=RMT-001"
        )
        with patch("business_core.business_builder.create_commercial_milestone_template",
                   return_value={"ok": True, "code": "COMMERCIAL_MILESTONE_TEMPLATE_CREATED", "error": None, "commercial_milestone_template_id": "PMT-001", "final_status": "active"}) as mock_create:
            _run(th.newpaymenttemplate_cmd(update, context))
        mock_create.assert_called_once()

    def test_newobligation_calls_business_builder_only(self):
        update, context = _cmd(
            "/newobligation business_id=BIZ-001 client_id=PRS-001 amount=100 currency=KZT caller_idempotency_key=K1"
        )
        with patch("business_core.business_builder.create_payment_obligation",
                   return_value={"ok": True, "code": "PAYMENT_OBLIGATION_CREATED", "error": None, "payment_obligation_id": "POB-001", "final_status": "draft"}) as mock_create:
            _run(th.newobligation_cmd(update, context))
        mock_create.assert_called_once()

    def test_recordpayment_calls_business_builder_only(self):
        update, context = _cmd(
            "/recordpayment business_id=BIZ-001 payment_obligation_id=POB-001 client_id=PRS-001 "
            "amount=100 currency=KZT payment_date=2026-01-01 external_transaction_id=E1"
        )
        with patch("business_core.business_builder.create_payment_transaction",
                   return_value={"ok": True, "code": "PAYMENT_TRANSACTION_CREATED", "error": None, "payment_transaction_id": "PTXN-001", "final_status": "pending"}) as mock_create:
            _run(th.recordpayment_cmd(update, context))
        mock_create.assert_called_once()

    def test_confirmpayment_calls_business_builder_only(self):
        update, context = _cmd("/confirmpayment payment_transaction_id=PTXN-001 confirmed_by=dida")
        with patch("business_core.business_builder.confirm_payment_transaction",
                   return_value={"ok": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None}) as mock_confirm:
            _run(th.confirmpayment_cmd(update, context))
        mock_confirm.assert_called_once()

    def test_reversepayment_calls_business_builder_only(self):
        update, context = _cmd("/reversepayment payment_transaction_id=PTXN-001 reversal_reason=R reversed_by=dida")
        with patch("business_core.business_builder.reverse_payment_transaction",
                   return_value={"ok": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None}) as mock_reverse:
            _run(th.reversepayment_cmd(update, context))
        mock_reverse.assert_called_once()

    def test_failpayment_calls_business_builder_only(self):
        update, context = _cmd("/failpayment payment_transaction_id=PTXN-001")
        with patch("business_core.business_builder.fail_payment_transaction",
                   return_value={"ok": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None, "previous_status": "pending"}) as mock_fail:
            _run(th.failpayment_cmd(update, context))
        mock_fail.assert_called_once()

    def test_paymenttemplates_reads_list_helper_only(self):
        update, context = _cmd("/paymenttemplates status=active")
        with patch("business_core.payment_manager.list_commercial_milestone_templates", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_commercial_milestone_template") as mock_create:
            _run(th.paymenttemplates_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_obligations_reads_list_helper_only(self):
        update, context = _cmd("/obligations business_id=BIZ-001")
        with patch("business_core.payment_manager.list_payment_obligations", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_payment_obligation") as mock_create:
            _run(th.obligations_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_payments_reads_list_helper_only(self):
        update, context = _cmd("/payments business_id=BIZ-001")
        with patch("business_core.payment_manager.list_payment_transactions", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_payment_transaction") as mock_create:
            _run(th.payments_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_no_caller_side_id_generation(self):
        for fn_name in _PAYMENT_COMMANDS:
            src = WORKSPACE.joinpath("business_core", "telegram_handlers.py").read_text(encoding="utf-8")
            start = src.index(f"async def {fn_name}(")
            rest = src[start + 10:]
            end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
            body = src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]
            self.assertNotIn('"PMT-"', body)
            self.assertNotIn('"POB-"', body)
            self.assertNotIn('"PTXN-"', body)
            self.assertNotIn("generate_next_id(", body)


class TestReadCommandsReturnSafeEmptyState(unittest.TestCase):
    def test_paymenttemplates_empty(self):
        update, context = _cmd("/paymenttemplates")
        with patch("business_core.payment_manager.list_commercial_milestone_templates", return_value=[]):
            _run(th.paymenttemplates_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_obligations_empty(self):
        update, context = _cmd("/obligations business_id=BIZ-999")
        with patch("business_core.payment_manager.list_payment_obligations", return_value=[]):
            _run(th.obligations_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_payments_empty(self):
        update, context = _cmd("/payments business_id=BIZ-999")
        with patch("business_core.payment_manager.list_payment_transactions", return_value=[]):
            _run(th.payments_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_paymenttemplate_not_found(self):
        update, context = _cmd("/paymenttemplate commercial_milestone_template_id=PMT-999")
        with patch("business_core.payment_manager.find_commercial_milestone_template_by_id", return_value=None):
            _run(th.paymenttemplate_cmd(update, context))
        self.assertIn("❌", _sent_text(update))

    def test_obligation_not_found(self):
        """Phase 17E-1: not-found now renders the shared anti-
        enumeration text (identical to a denied-but-existing record),
        not an entity-specific "не найден" message."""
        update, context = _cmd("/obligation payment_obligation_id=POB-999")
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=None):
            _run(th.obligation_cmd(update, context))
        self.assertEqual(_sent_text(update), "Запись недоступна или не найдена.")

    def test_payment_not_found(self):
        """Phase 17E-1: not-found now renders the shared anti-
        enumeration text (identical to a denied-but-existing record),
        not an entity-specific "не найден" message."""
        update, context = _cmd("/payment payment_transaction_id=PTXN-999")
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=None):
            _run(th.payment_cmd(update, context))
        self.assertEqual(_sent_text(update), "Запись недоступна или не найдена.")


class TestSensitiveFieldsHiddenInReadCommands(unittest.TestCase):
    def test_payment_detail_hides_external_transaction_id_and_notes(self):
        txn = {
            "Payment Transaction ID": "PTXN-001", "Payment Obligation ID": "POB-001", "Client ID": "PRS-001",
            "Amount": "100.00", "Currency": "KZT", "Payment Date": "2026-01-01", "Status": "pending",
            "External Transaction ID": "SECRET-BANK-REF-12345", "Caller Idempotency Key": "SECRET-KEY",
            "Notes": "sensitive internal note", "Payment Method": "card", "Reversal Reason": "",
            "Evidence Document ID": "", "Confirmed At": "", "Reversed At": "",
        }
        update, context = _cmd("/payment payment_transaction_id=PTXN-001")
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn):
            _run(th.payment_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("SECRET-BANK-REF-12345", text)
        self.assertNotIn("SECRET-KEY", text)
        self.assertNotIn("sensitive internal note", text)

    def test_obligation_detail_hides_notes(self):
        obligation = {
            "Payment Obligation ID": "POB-001", "Title Snapshot": "T", "Client ID": "PRS-001",
            "Obligation Amount": "100.00", "Currency": "KZT", "Paid Amount": "0.00", "Remaining Amount": "100.00",
            "Status": "draft", "Due Date": "", "Roadmap ID": "", "Stage ID": "",
            "Commercial Milestone Template ID": "", "Notes": "sensitive internal note",
        }
        update, context = _cmd("/obligation payment_obligation_id=POB-001")
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=obligation), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[]):
            _run(th.obligation_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("sensitive internal note", text)

    def test_payments_list_hides_notes_and_external_id(self):
        txns = [{
            "Payment Transaction ID": "PTXN-001", "Payment Obligation ID": "POB-001",
            "Amount": "100.00", "Currency": "KZT", "Payment Date": "2026-01-01", "Status": "pending",
            "Notes": "sensitive internal note", "External Transaction ID": "SECRET-REF", "Payment Method": "card",
        }]
        update, context = _cmd("/payments")
        with patch("business_core.payment_manager.list_payment_transactions", return_value=txns):
            _run(th.payments_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("sensitive internal note", text)
        self.assertNotIn("SECRET-REF", text)

    def test_obligations_list_hides_notes(self):
        obligations = [{
            "Payment Obligation ID": "POB-001", "Title Snapshot": "T", "Status": "draft",
            "Paid Amount": "0.00", "Obligation Amount": "100.00", "Currency": "KZT", "Client ID": "PRS-001",
            "Notes": "sensitive internal note",
        }]
        update, context = _cmd("/obligations")
        with patch("business_core.payment_manager.list_payment_obligations", return_value=obligations):
            _run(th.obligations_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("sensitive internal note", text)


class TestNoRawExceptionOrDictExposure(unittest.TestCase):
    def test_no_raw_exception_interpolation(self):
        for fn_name in _PAYMENT_COMMANDS:
            src = WORKSPACE.joinpath("business_core", "telegram_handlers.py").read_text(encoding="utf-8")
            start = src.index(f"async def {fn_name}(")
            rest = src[start + 10:]
            end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
            body = src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]
            self.assertNotIn("str(e)", body)
            self.assertNotIn("Ошибка: {e}", body)

    def test_unhandled_exception_yields_safe_message(self):
        update, context = _cmd("/failpayment payment_transaction_id=PTXN-001")
        with patch("business_core.business_builder.fail_payment_transaction", side_effect=RuntimeError("raw internal secret")):
            _run(th.failpayment_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("raw internal secret", text)
        self.assertIn("❌", text)


class TestParseModeUnderscoresRenderCorrectly(unittest.TestCase):
    def test_all_payment_commands_use_parse_mode_none(self):
        for fn_name in _PAYMENT_COMMANDS:
            src = WORKSPACE.joinpath("business_core", "telegram_handlers.py").read_text(encoding="utf-8")
            start = src.index(f"async def {fn_name}(")
            rest = src[start + 10:]
            end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
            body = src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")

    def test_usage_message_underscores_intact(self):
        update, context = _cmd("/newobligation")
        _run(th.newobligation_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("caller_idempotency_key", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_recordpayment_usage_underscores_intact(self):
        update, context = _cmd("/recordpayment")
        _run(th.recordpayment_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("payment_obligation_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_confirmpayment_usage_underscores_intact(self):
        update, context = _cmd("/confirmpayment")
        _run(th.confirmpayment_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("payment_transaction_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_reversepayment_usage_underscores_intact(self):
        update, context = _cmd("/reversepayment")
        _run(th.reversepayment_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("payment_transaction_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_paymenttemplate_detail_underscore_field_intact(self):
        update, context = _cmd("/paymenttemplate")
        _run(th.paymenttemplate_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("commercial_milestone_template_id", text)


class TestMilestonesCommandUnchanged(unittest.TestCase):
    def test_milestones_still_read_only_roadmap_owned(self):
        src = WORKSPACE.joinpath("business_core", "telegram_handlers.py").read_text(encoding="utf-8")
        start = src.index("async def milestones_cmd(")
        end = start + 3000
        body = src[start:min(end, len(src))]
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("payment_manager", body)
        self.assertNotIn("business_builder.create_payment_obligation", body)


class TestBoundaries(unittest.TestCase):
    def test_no_closed_domain_mutation_calls_in_payment_commands(self):
        for fn_name in _PAYMENT_COMMANDS:
            src = WORKSPACE.joinpath("business_core", "telegram_handlers.py").read_text(encoding="utf-8")
            start = src.index(f"async def {fn_name}(")
            rest = src[start + 10:]
            end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
            body = src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]
            for forbidden in (
                "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate a closed domain ({forbidden!r} found)")

    def test_no_startroadmap_integration(self):
        path = WORKSPACE / "business_core" / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("create_payment_obligation", src)


if __name__ == "__main__":
    unittest.main()
