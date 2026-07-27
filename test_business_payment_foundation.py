"""
Tests for Phase 39C — Payment/Milestone Domain Foundation:
business_core/business_builder.py's Payment orchestration (ADR-022).
Covers Decimal amount normalization, currency normalization, Commercial
Milestone Template creation/lifecycle, Payment Obligation creation/
relations/idempotency/lifecycle, Payment Transaction creation/
idempotency/confirmation/reversal/failure, derived balance calculation,
and Obligation status synchronization.

No live Sheets/Drive/Telegram access — mocks only. Registered in
conftest.py's hard socket-block set before this file's logic was
written.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb


# ─────────────────────────────────────────────────────────────
# Decimal amount normalization
# ─────────────────────────────────────────────────────────────

class TestNormalizePaymentAmount(unittest.TestCase):
    def test_valid_integer(self):
        r = bb.normalize_payment_amount("150000")
        self.assertTrue(r["ok"])
        self.assertEqual(r["normalized"], "150000.00")

    def test_valid_scale_2(self):
        r = bb.normalize_payment_amount("150000.50")
        self.assertTrue(r["ok"])
        self.assertEqual(r["normalized"], "150000.50")

    def test_zero_rejected(self):
        r = bb.normalize_payment_amount("0")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_AMOUNT_MUST_BE_POSITIVE")

    def test_negative_rejected(self):
        r = bb.normalize_payment_amount("-100")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_AMOUNT_MUST_BE_POSITIVE")

    def test_scale_greater_than_2_rejected(self):
        r = bb.normalize_payment_amount("100.123")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_AMOUNT_SCALE")

    def test_float_rejected(self):
        r = bb.normalize_payment_amount(100.50)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_AMOUNT")

    def test_scientific_notation_rejected(self):
        r = bb.normalize_payment_amount("1e5")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_AMOUNT")

    def test_thousands_comma_rejected(self):
        r = bb.normalize_payment_amount("150,000")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_AMOUNT")

    def test_empty_rejected(self):
        r = bb.normalize_payment_amount("")
        self.assertFalse(r["ok"])

    def test_none_rejected(self):
        r = bb.normalize_payment_amount(None)
        self.assertFalse(r["ok"])

    def test_garbage_rejected(self):
        r = bb.normalize_payment_amount("abc")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_AMOUNT")

    def test_exact_decimal_summation(self):
        a = bb.normalize_payment_amount("0.1")["amount"]
        b = bb.normalize_payment_amount("0.2")["amount"]
        self.assertEqual(a + b, Decimal("0.30"))

    def test_whitespace_trimmed(self):
        r = bb.normalize_payment_amount("  100.00  ")
        self.assertTrue(r["ok"])
        self.assertEqual(r["normalized"], "100.00")


class TestNormalizePaymentCurrency(unittest.TestCase):
    def test_uppercased(self):
        r = bb.normalize_payment_currency("kzt")
        self.assertTrue(r["ok"])
        self.assertEqual(r["currency"], "KZT")

    def test_blank_rejected(self):
        r = bb.normalize_payment_currency("")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_CURRENCY")

    def test_none_rejected(self):
        r = bb.normalize_payment_currency(None)
        self.assertFalse(r["ok"])

    def test_wrong_length_rejected(self):
        r = bb.normalize_payment_currency("KZTX")
        self.assertFalse(r["ok"])

    def test_non_letters_rejected(self):
        r = bb.normalize_payment_currency("KZ1")
        self.assertFalse(r["ok"])

    def test_whitespace_trimmed(self):
        r = bb.normalize_payment_currency("  KZT  ")
        self.assertTrue(r["ok"])
        self.assertEqual(r["currency"], "KZT")


# ─────────────────────────────────────────────────────────────
# Balance calculator
# ─────────────────────────────────────────────────────────────

class TestComputePaymentBalance(unittest.TestCase):
    def test_no_transactions(self):
        r = bb._compute_payment_balance("150000.00", [])
        self.assertTrue(r["ok"])
        self.assertEqual(r["paid_amount"], "0.00")
        self.assertEqual(r["remaining_amount"], "150000.00")

    def test_confirmed_only_counted(self):
        txns = [
            {"Status": "confirmed", "Amount": "50000.00"},
            {"Status": "pending", "Amount": "1000000.00"},
            {"Status": "failed", "Amount": "1000000.00"},
            {"Status": "reversed", "Amount": "1000000.00"},
        ]
        r = bb._compute_payment_balance("150000.00", txns)
        self.assertTrue(r["ok"])
        self.assertEqual(r["paid_amount"], "50000.00")
        self.assertEqual(r["remaining_amount"], "100000.00")

    def test_full_payment(self):
        txns = [{"Status": "confirmed", "Amount": "150000.00"}]
        r = bb._compute_payment_balance("150000.00", txns)
        self.assertEqual(r["remaining_amount"], "0.00")

    def test_multiple_partial_payments(self):
        txns = [
            {"Status": "confirmed", "Amount": "50000.00"},
            {"Status": "confirmed", "Amount": "30000.00"},
        ]
        r = bb._compute_payment_balance("150000.00", txns)
        self.assertEqual(r["paid_amount"], "80000.00")
        self.assertEqual(r["remaining_amount"], "70000.00")

    def test_overpayment_blocked(self):
        txns = [{"Status": "confirmed", "Amount": "200000.00"}]
        r = bb._compute_payment_balance("150000.00", txns)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED")

    def test_unknown_status_blocks(self):
        txns = [{"Status": "bogus", "Amount": "10.00"}]
        r = bb._compute_payment_balance("150000.00", txns)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_TRANSACTION_STATUS")


# ─────────────────────────────────────────────────────────────
# Commercial Milestone Template
# ─────────────────────────────────────────────────────────────

class TestCreateCommercialMilestoneTemplate(unittest.TestCase):
    def test_requires_title(self):
        r = bb.create_commercial_milestone_template("", "fixed")
        self.assertFalse(r["ok"])

    def test_requires_roadmap_template_or_service(self):
        r = bb.create_commercial_milestone_template("T", "fixed", fixed_amount="100", currency="KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_ENTITY_RELATION_MISMATCH")

    def test_fixed_missing_amount(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]):
            r = bb.create_commercial_milestone_template("T", "fixed", roadmap_template_id="RMT-001", currency="KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MILESTONE_FIXED_AMOUNT_REQUIRED")

    def test_percentage_missing_percentage(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]):
            r = bb.create_commercial_milestone_template("T", "percentage", roadmap_template_id="RMT-001", currency="KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MILESTONE_PERCENTAGE_REQUIRED")

    def test_fixed_with_percentage_conflicts(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]):
            r = bb.create_commercial_milestone_template(
                "T", "fixed", roadmap_template_id="RMT-001", currency="KZT",
                fixed_amount="100", percentage="10",
            )
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MILESTONE_CALCULATION_FIELDS_CONFLICT")

    def test_invalid_calculation_type(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]):
            r = bb.create_commercial_milestone_template("T", "bogus", roadmap_template_id="RMT-001", currency="KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_MILESTONE_CALCULATION_TYPE")

    def test_roadmap_template_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[]):
            r = bb.create_commercial_milestone_template(
                "T", "fixed", roadmap_template_id="RMT-999", currency="KZT", fixed_amount="100",
            )
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "ROADMAP_NOT_FOUND")

    def test_creates_new_fixed_template(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]), \
             patch("business_core.payment_manager.find_templates_by_identity", return_value=[]), \
             patch("business_core.payment_manager.create_commercial_milestone_template",
                   return_value={"ok": True, "commercial_milestone_template_id": "PMT-001", "code": "COMMERCIAL_MILESTONE_TEMPLATE_CREATED", "error": None}), \
             patch("business_core.payment_manager.find_commercial_milestone_template_by_id",
                   return_value={"Commercial Milestone Template ID": "PMT-001", "Status": "active"}):
            r = bb.create_commercial_milestone_template(
                "T", "fixed", roadmap_template_id="RMT-001", currency="KZT", fixed_amount="150000",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_MILESTONE_TEMPLATE_CREATED")
        self.assertTrue(r["created"])

    def test_reuses_existing_template_on_identity_match(self):
        existing = {"Commercial Milestone Template ID": "PMT-001", "Status": "active"}
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]), \
             patch("business_core.payment_manager.find_templates_by_identity", return_value=[existing]):
            r = bb.create_commercial_milestone_template(
                "T", "fixed", roadmap_template_id="RMT-001", currency="KZT", fixed_amount="150000",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_MILESTONE_TEMPLATE_REUSED")
        self.assertTrue(r["reused"])

    def test_multiple_identity_matches_block(self):
        matches = [
            {"Commercial Milestone Template ID": "PMT-001"},
            {"Commercial Milestone Template ID": "PMT-002"},
        ]
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]), \
             patch("business_core.payment_manager.find_templates_by_identity", return_value=matches):
            r = bb.create_commercial_milestone_template(
                "T", "fixed", roadmap_template_id="RMT-001", currency="KZT", fixed_amount="150000",
            )
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MULTIPLE_COMMERCIAL_MILESTONE_TEMPLATE_MATCHES")
        self.assertEqual(set(r["conflicting_ids"]), {"PMT-001", "PMT-002"})

    def test_no_percentage_auto_calculation_from_service_catalog(self):
        """A percentage-mode Template must never trigger a Service
        price-range lookup to compute an amount — ADR-022 §12/§15."""
        with patch("business_core.sheets.read_business_sheet", return_value=[{"Template ID": "RMT-001"}]) as mock_read, \
             patch("business_core.service_manager.find_service_by_id") as mock_find_service, \
             patch("business_core.payment_manager.find_templates_by_identity", return_value=[]), \
             patch("business_core.payment_manager.create_commercial_milestone_template",
                   return_value={"ok": True, "commercial_milestone_template_id": "PMT-001", "code": "", "error": None}), \
             patch("business_core.payment_manager.find_commercial_milestone_template_by_id",
                   return_value={"Commercial Milestone Template ID": "PMT-001", "Status": "active"}):
            bb.create_commercial_milestone_template(
                "T", "percentage", roadmap_template_id="RMT-001", currency="KZT", percentage="10",
            )
        mock_find_service.assert_not_called()


class TestTemplateLifecycle(unittest.TestCase):
    def test_active_to_inactive(self):
        template = {"Commercial Milestone Template ID": "PMT-001", "Status": "active"}
        with patch("business_core.payment_manager.find_commercial_milestone_template_by_id", return_value=template), \
             patch("business_core.payment_manager.update_commercial_milestone_template_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.transition_commercial_milestone_template_status("PMT-001", "inactive")
        self.assertTrue(r["ok"])
        self.assertEqual(r["final_status"], "inactive")

    def test_archived_to_active_requires_explicit_restore(self):
        template = {"Commercial Milestone Template ID": "PMT-001", "Status": "archived"}
        with patch("business_core.payment_manager.find_commercial_milestone_template_by_id", return_value=template):
            r = bb.transition_commercial_milestone_template_status("PMT-001", "active")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_MILESTONE_TEMPLATE_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_no_op_unchanged(self):
        template = {"Commercial Milestone Template ID": "PMT-001", "Status": "active"}
        with patch("business_core.payment_manager.find_commercial_milestone_template_by_id", return_value=template):
            r = bb.transition_commercial_milestone_template_status("PMT-001", "active")
        self.assertTrue(r["ok"])
        self.assertFalse(r["changed"])

    def test_invalid_status(self):
        template = {"Commercial Milestone Template ID": "PMT-001", "Status": "active"}
        with patch("business_core.payment_manager.find_commercial_milestone_template_by_id", return_value=template):
            r = bb.transition_commercial_milestone_template_status("PMT-001", "bogus")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS")


# ─────────────────────────────────────────────────────────────
# Payment Obligation
# ─────────────────────────────────────────────────────────────

_ACTIVE_CLIENT = {
    "person_id": "PRS-001", "status": "active", "person_type": "клиент",
    "biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-001",
}


def _patch_relation_happy_path():
    return [
        patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]),
        patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT),
        patch("business_core.person_manager.is_person_archived", return_value=False),
        patch("business_core.person_manager.is_client_person", return_value=True),
        patch("business_core.person_manager.has_person_business_link", return_value=True),
    ]


class TestCreatePaymentObligation(unittest.TestCase):
    def test_requires_business_id(self):
        r = bb.create_payment_obligation("", "PRS-001", "100", "KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "BUSINESS_NOT_FOUND")

    def test_requires_client_id(self):
        r = bb.create_payment_obligation("BIZ-001", "", "100", "KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "CLIENT_NOT_FOUND")

    def test_requires_idempotency_source(self):
        r = bb.create_payment_obligation("BIZ-001", "PRS-001", "100", "KZT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_IDEMPOTENCY_CONFLICT")

    def test_invalid_amount_propagates(self):
        r = bb.create_payment_obligation("BIZ-001", "PRS-001", "-5", "KZT", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_AMOUNT_MUST_BE_POSITIVE")

    def test_client_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=None):
            r = bb.create_payment_obligation("BIZ-001", "PRS-999", "100", "KZT", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "CLIENT_NOT_FOUND")

    def test_creates_new_obligation_zero_matches(self):
        patches = _patch_relation_happy_path()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.payment_manager.find_obligations_by_caller_key", return_value=[]), \
             patch("business_core.payment_manager.create_payment_obligation",
                   return_value={"ok": True, "payment_obligation_id": "POB-001", "code": "", "error": None}), \
             patch("business_core.payment_manager.find_payment_obligation_by_id",
                   return_value={"Payment Obligation ID": "POB-001", "Status": "draft"}):
            r = bb.create_payment_obligation("BIZ-001", "PRS-001", "150000", "KZT", caller_idempotency_key="K1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_CREATED")
        self.assertTrue(r["created"])
        self.assertEqual(r["paid_amount"], "0.00")
        self.assertEqual(r["remaining_amount"], "150000.00")

    def test_reuses_on_one_match(self):
        existing = {
            "Payment Obligation ID": "POB-001", "Status": "draft",
            "Object ID": "", "Service ID": "", "Roadmap ID": "", "Stage ID": "",
            "Commercial Milestone Template ID": "", "Obligation Amount": "150000.00",
            "Currency": "KZT", "Paid Amount": "0.00", "Remaining Amount": "150000.00",
        }
        patches = _patch_relation_happy_path()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.payment_manager.find_obligations_by_caller_key", return_value=[existing]):
            r = bb.create_payment_obligation("BIZ-001", "PRS-001", "150000", "KZT", caller_idempotency_key="K1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_REUSED")
        self.assertTrue(r["reused"])

    def test_multiple_matches_block(self):
        matches = [{"Payment Obligation ID": "POB-001"}, {"Payment Obligation ID": "POB-002"}]
        patches = _patch_relation_happy_path()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.payment_manager.find_obligations_by_caller_key", return_value=matches):
            r = bb.create_payment_obligation("BIZ-001", "PRS-001", "150000", "KZT", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MULTIPLE_PAYMENT_OBLIGATION_MATCHES")
        self.assertEqual(set(r["conflicting_ids"]), {"POB-001", "POB-002"})

    def test_client_business_link_mismatch(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=False):
            r = bb.create_payment_obligation("BIZ-001", "PRS-001", "150000", "KZT", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_ENTITY_RELATION_MISMATCH")

    def test_no_title_or_amount_date_dedup(self):
        """Passing a different title/amount must not affect the caller-key
        match set — the lookup mock only returns rows for the exact key,
        proving the orchestration never re-filters by title/amount itself."""
        patches = _patch_relation_happy_path()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.payment_manager.find_obligations_by_caller_key") as mock_lookup, \
             patch("business_core.payment_manager.create_payment_obligation",
                   return_value={"ok": True, "payment_obligation_id": "POB-002", "code": "", "error": None}), \
             patch("business_core.payment_manager.find_payment_obligation_by_id",
                   return_value={"Payment Obligation ID": "POB-002", "Status": "draft"}):
            mock_lookup.return_value = []
            bb.create_payment_obligation("BIZ-001", "PRS-001", "999999", "KZT", caller_idempotency_key="K2", title="Different Title")
            mock_lookup.assert_called_once_with("BIZ-001", "K2")


class TestPaymentObligationLifecycle(unittest.TestCase):
    def _obligation(self, status, paid_amount="0.00"):
        return {
            "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001",
            "Status": status, "Paid Amount": paid_amount,
        }

    def test_draft_to_issued(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("draft")), \
             patch("business_core.payment_manager.update_payment_obligation_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.transition_payment_obligation_status("POB-001", "issued")
        self.assertTrue(r["ok"])
        self.assertEqual(r["final_status"], "issued")

    def test_manual_transition_to_partially_paid_blocked(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("issued")):
            r = bb.transition_payment_obligation_status("POB-001", "partially_paid")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_OBLIGATION_TRANSITION")

    def test_manual_transition_to_paid_blocked(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("issued")):
            r = bb.transition_payment_obligation_status("POB-001", "paid")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_OBLIGATION_TRANSITION")

    def test_cancel_blocked_when_paid_amount_positive(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("partially_paid", "50000.00")):
            r = bb.transition_payment_obligation_status("POB-001", "cancelled")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_HAS_CONFIRMED_PAYMENTS")

    def test_cancel_allowed_when_paid_amount_zero(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("partially_paid", "0.00")), \
             patch("business_core.payment_manager.update_payment_obligation_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.transition_payment_obligation_status("POB-001", "cancelled")
        self.assertTrue(r["ok"])

    def test_paid_only_allows_archived(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("paid")):
            r = bb.transition_payment_obligation_status("POB-001", "issued")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_OBLIGATION_TRANSITION")

    def test_archived_is_terminal(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("archived")):
            r = bb.transition_payment_obligation_status("POB-001", "draft")
        self.assertFalse(r["ok"])

    def test_no_op_returns_unchanged(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation("draft")):
            r = bb.transition_payment_obligation_status("POB-001", "draft")
        self.assertTrue(r["ok"])
        self.assertFalse(r["changed"])

    def test_not_found(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=None):
            r = bb.transition_payment_obligation_status("POB-999", "issued")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_NOT_FOUND")


# ─────────────────────────────────────────────────────────────
# Payment Transaction
# ─────────────────────────────────────────────────────────────

_OBLIGATION_FOR_TXN = {
    "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-001",
    "Currency": "KZT", "Obligation Amount": "150000.00",
}


class TestCreatePaymentTransaction(unittest.TestCase):
    def test_requires_idempotency_source(self):
        r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "100", "KZT", "2026-01-01")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED")

    def test_obligation_not_found(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=None):
            r = bb.create_payment_transaction("BIZ-001", "POB-999", "PRS-001", "100", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_NOT_FOUND")

    def test_client_mismatch(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-999", "100", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_ENTITY_RELATION_MISMATCH")

    def test_currency_mismatch(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "100", "USD", "2026-01-01", external_transaction_id="E1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_CURRENCY_MISMATCH")

    def test_creates_pending_transaction(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.find_transactions_by_external_id", return_value=[]), \
             patch("business_core.payment_manager.create_payment_transaction",
                   return_value={"ok": True, "payment_transaction_id": "PTXN-001", "code": "", "error": None}), \
             patch("business_core.payment_manager.find_payment_transaction_by_id",
                   return_value={"Payment Transaction ID": "PTXN-001", "Status": "pending"}):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "50000", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["final_status"], "pending")
        self.assertTrue(r["created"])

    def test_evidence_document_wrong_business_blocks(self):
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.document_manager.find_document_by_id", return_value={"business_id": "BIZ-999"}):
            r = bb.create_payment_transaction(
                "BIZ-001", "POB-001", "PRS-001", "50000", "KZT", "2026-01-01",
                external_transaction_id="E1", evidence_document_id="DREG-001",
            )
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_ENTITY_RELATION_MISMATCH")

    def test_multiple_external_id_matches_block(self):
        matches = [{"Payment Transaction ID": "PTXN-001"}, {"Payment Transaction ID": "PTXN-002"}]
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.find_transactions_by_external_id", return_value=matches):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "50000", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MULTIPLE_PAYMENT_TRANSACTION_MATCHES")

    def test_incompatible_idempotency_reuse_blocks(self):
        existing = {"Payment Transaction ID": "PTXN-001", "Payment Obligation ID": "POB-999", "Amount": "1.00", "Currency": "KZT"}
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.find_transactions_by_external_id", return_value=[existing]):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "50000", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT")

    def test_compatible_reuse(self):
        existing = {"Payment Transaction ID": "PTXN-001", "Payment Obligation ID": "POB-001", "Amount": "50000.00", "Currency": "KZT", "Status": "pending"}
        with patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.find_transactions_by_external_id", return_value=[existing]):
            r = bb.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "50000", "KZT", "2026-01-01", external_transaction_id="E1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_REUSED")
        self.assertTrue(r["reused"])


class TestConfirmPaymentTransaction(unittest.TestCase):
    def _txn(self, status="pending", amount="50000.00"):
        return {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001",
            "Payment Obligation ID": "POB-001", "Amount": amount, "Currency": "KZT", "Status": status,
        }

    def test_not_found(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=None):
            r = bb.confirm_payment_transaction("PTXN-999", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_NOT_FOUND")

    def test_already_confirmed_no_op(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("confirmed")):
            r = bb.confirm_payment_transaction("PTXN-001", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED")
        self.assertFalse(r["changed"])

    def test_invalid_source_status(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("failed")):
            r = bb.confirm_payment_transaction("PTXN-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_TRANSACTION_TRANSITION")

    def test_confirmed_by_required(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("pending")):
            r = bb.confirm_payment_transaction("PTXN-001", "")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_CONFIRMATION_METADATA_REQUIRED")

    def test_successful_confirmation(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("pending")), \
             patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[]), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch.object(bb, "_synchronize_payment_obligation_after_transaction_change",
                          return_value={"ok": True, "paid_amount": "50000.00", "remaining_amount": "100000.00", "status": "partially_paid"}):
            with patch("business_core.payment_manager.find_payment_transaction_by_id", side_effect=[self._txn("pending"), self._txn("confirmed")]):
                r = bb.confirm_payment_transaction("PTXN-001", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_CONFIRMED")
        self.assertEqual(r["paid_amount"], "50000.00")
        self.assertEqual(r["remaining_amount"], "100000.00")

    def test_overpayment_blocked(self):
        other_txn = {"Payment Transaction ID": "PTXN-OTHER", "Status": "confirmed", "Amount": "150000.00"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("pending", amount="10.00")), \
             patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=_OBLIGATION_FOR_TXN), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[other_txn]):
            r = bb.confirm_payment_transaction("PTXN-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED")


class TestReversePaymentTransaction(unittest.TestCase):
    def _txn(self, status="confirmed"):
        return {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001",
            "Payment Obligation ID": "POB-001", "Amount": "50000.00", "Currency": "KZT",
            "Payment Date": "2026-01-01", "Status": status,
        }

    def test_reason_required(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("confirmed")):
            r = bb.reverse_payment_transaction("PTXN-001", "", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED")

    def test_invalid_source_status(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("pending")):
            r = bb.reverse_payment_transaction("PTXN-001", "client error", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_TRANSACTION_TRANSITION")

    def test_already_reversed_no_op(self):
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn("reversed")):
            r = bb.reverse_payment_transaction("PTXN-001", "reason", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED")
        self.assertFalse(r["changed"])

    def test_successful_reversal_preserves_financial_fields(self):
        original = self._txn("confirmed")
        reversed_row = dict(original)
        reversed_row["Status"] = "reversed"
        with patch("business_core.payment_manager.find_payment_transaction_by_id", side_effect=[original, reversed_row]), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch.object(bb, "_synchronize_payment_obligation_after_transaction_change",
                          return_value={"ok": True, "paid_amount": "0.00", "remaining_amount": "150000.00", "status": "issued"}):
            r = bb.reverse_payment_transaction("PTXN-001", "client requested refund", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_TRANSACTION_REVERSED")
        self.assertEqual(r["remaining_amount"], "150000.00")

    def test_reversal_does_not_create_negative_transaction(self):
        """The reversal path must call update_payment_transaction_status
        exactly once — never a second create call for an offsetting row."""
        original = self._txn("confirmed")
        reversed_row = dict(original)
        reversed_row["Status"] = "reversed"
        with patch("business_core.payment_manager.find_payment_transaction_by_id", side_effect=[original, reversed_row]), \
             patch("business_core.payment_manager.create_payment_transaction") as mock_create, \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch.object(bb, "_synchronize_payment_obligation_after_transaction_change",
                          return_value={"ok": True, "paid_amount": "0.00", "remaining_amount": "150000.00", "status": "issued"}):
            bb.reverse_payment_transaction("PTXN-001", "reason", "dida")
        mock_create.assert_not_called()


class TestFailPaymentTransaction(unittest.TestCase):
    def test_pending_to_failed(self):
        txn = {"Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001", "Status": "pending"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.fail_payment_transaction("PTXN-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["final_status"], "failed")

    def test_confirmed_cannot_fail(self):
        txn = {"Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001", "Status": "confirmed"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn):
            r = bb.fail_payment_transaction("PTXN-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_PAYMENT_TRANSACTION_TRANSITION")


# ─────────────────────────────────────────────────────────────
# Obligation status synchronization
# ─────────────────────────────────────────────────────────────

class TestSynchronizePaymentObligation(unittest.TestCase):
    def test_zero_paid_stays_issued(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "issued", "Paid At": ""}
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, {**obligation, "Paid Amount": "0.00", "Remaining Amount": "150000.00"}]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[]), \
             patch("business_core.payment_manager.update_payment_obligation_balance",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "issued")

    def test_partial_payment_synchronizes_to_partially_paid(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "issued", "Paid At": ""}
        verify = {**obligation, "Paid Amount": "50000.00", "Remaining Amount": "100000.00", "Status": "partially_paid"}
        txns = [{"Status": "confirmed", "Amount": "50000.00"}]
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, verify]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=txns), \
             patch("business_core.payment_manager.update_payment_obligation_balance",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "partially_paid")

    def test_full_payment_synchronizes_to_paid(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "partially_paid", "Paid At": ""}
        verify = {**obligation, "Paid Amount": "150000.00", "Remaining Amount": "0.00", "Status": "paid"}
        txns = [{"Status": "confirmed", "Amount": "150000.00"}]
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, verify]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=txns), \
             patch("business_core.payment_manager.update_payment_obligation_balance",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "paid")

    def test_reversal_synchronizes_paid_back_to_issued(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "paid", "Paid At": "2026-01-01 00:00:00 UTC"}
        verify = {**obligation, "Paid Amount": "0.00", "Remaining Amount": "150000.00", "Status": "issued"}
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, verify]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[]), \
             patch("business_core.payment_manager.update_payment_obligation_balance") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "issued")
        self.assertTrue(mock_update.call_args.kwargs["clear_paid_at"])

    def test_cancelled_status_protected(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "cancelled", "Paid At": ""}
        verify = {**obligation, "Paid Amount": "0.00", "Remaining Amount": "150000.00", "Status": "cancelled"}
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, verify]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=[]), \
             patch("business_core.payment_manager.update_payment_obligation_balance",
                   return_value={"ok": True, "changed": False, "code": "", "error": None}):
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "cancelled")

    def test_cache_verification_failure_detected(self):
        obligation = {"Payment Obligation ID": "POB-001", "Obligation Amount": "150000.00", "Status": "issued", "Paid At": ""}
        stale_verify = {**obligation, "Paid Amount": "0.00", "Remaining Amount": "150000.00", "Status": "issued"}
        txns = [{"Status": "confirmed", "Amount": "50000.00"}]
        with patch("business_core.payment_manager.find_payment_obligation_by_id", side_effect=[obligation, stale_verify]), \
             patch("business_core.payment_manager.list_payment_transactions", return_value=txns), \
             patch("business_core.payment_manager.update_payment_obligation_balance",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb._synchronize_payment_obligation_after_transaction_change("POB-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED")


if __name__ == "__main__":
    unittest.main()
