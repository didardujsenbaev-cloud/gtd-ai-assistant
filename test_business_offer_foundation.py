"""
Tests for Phase 40C — Commercial Offer Domain Foundation:
business_core/business_builder.py's Commercial Offer orchestration
(ADR-023). Covers Decimal amount normalization, currency normalization,
date validation, snapshot validation, relation validation, Offer
creation/idempotency, latest-version derivation usage, revision/
branching, lifecycle transitions (send/accept/reject/expire/cancel/
archive), draft-only updates, and effective-expiration read helper.

No live Sheets/Drive/Telegram access — mocks only. Registered in
conftest.py's hard socket-block set before this file's logic was
written.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb


# ─────────────────────────────────────────────────────────────
# Amount / currency / date / snapshot normalization
# ─────────────────────────────────────────────────────────────

class TestNormalizeCommercialOfferAmount(unittest.TestCase):
    def test_valid_integer(self):
        r = bb.normalize_commercial_offer_amount("150000")
        self.assertTrue(r["ok"])
        self.assertEqual(r["normalized"], "150000.00")

    def test_zero_rejected(self):
        r = bb.normalize_commercial_offer_amount("0")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE")

    def test_negative_rejected(self):
        r = bb.normalize_commercial_offer_amount("-1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE")

    def test_scale_greater_than_2_rejected(self):
        r = bb.normalize_commercial_offer_amount("100.123")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE")

    def test_float_rejected(self):
        r = bb.normalize_commercial_offer_amount(100.5)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_AMOUNT")

    def test_scientific_notation_rejected(self):
        r = bb.normalize_commercial_offer_amount("1e5")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_AMOUNT")

    def test_comma_rejected(self):
        r = bb.normalize_commercial_offer_amount("150,000")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_AMOUNT")

    def test_never_emits_payment_codes(self):
        for raw in ("-1", "0", 100.5, "1e5", "150,000", "100.123"):
            r = bb.normalize_commercial_offer_amount(raw)
            self.assertNotIn("PAYMENT", r["code"])

    def test_exact_decimal_arithmetic(self):
        a = bb.normalize_commercial_offer_amount("0.1")["amount"]
        b = bb.normalize_commercial_offer_amount("0.2")["amount"]
        self.assertEqual(a + b, Decimal("0.30"))


class TestNormalizeCommercialOfferCurrency(unittest.TestCase):
    def test_uppercased(self):
        r = bb.normalize_commercial_offer_currency("kzt")
        self.assertTrue(r["ok"])
        self.assertEqual(r["currency"], "KZT")

    def test_blank_rejected(self):
        r = bb.normalize_commercial_offer_currency("")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_CURRENCY")

    def test_wrong_length_rejected(self):
        r = bb.normalize_commercial_offer_currency("KZTX")
        self.assertFalse(r["ok"])

    def test_never_emits_payment_codes(self):
        r = bb.normalize_commercial_offer_currency("")
        self.assertNotIn("PAYMENT", r["code"])


class TestNormalizeCommercialOfferValidUntil(unittest.TestCase):
    def test_valid_future_date(self):
        r = bb.normalize_commercial_offer_valid_until("2026-12-31", reference_date=date(2026, 1, 1))
        self.assertTrue(r["ok"])
        self.assertEqual(r["valid_until"], "2026-12-31")

    def test_same_day_allowed(self):
        r = bb.normalize_commercial_offer_valid_until("2026-01-01", reference_date=date(2026, 1, 1))
        self.assertTrue(r["ok"])

    def test_past_date_rejected(self):
        r = bb.normalize_commercial_offer_valid_until("2025-01-01", reference_date=date(2026, 1, 1))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST")

    def test_invalid_format_rejected(self):
        r = bb.normalize_commercial_offer_valid_until("31/12/2026", reference_date=date(2026, 1, 1))
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_VALID_UNTIL")

    def test_blank_rejected(self):
        r = bb.normalize_commercial_offer_valid_until("")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_VALID_UNTIL")


class TestValidateSnapshots(unittest.TestCase):
    def test_valid_snapshots(self):
        r = bb._validate_commercial_offer_snapshots("Title", "Scope description")
        self.assertTrue(r["ok"])

    def test_blank_title_rejected(self):
        r = bb._validate_commercial_offer_snapshots("  ", "Scope")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_TITLE_REQUIRED")

    def test_blank_scope_rejected(self):
        r = bb._validate_commercial_offer_snapshots("Title", "  ")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_SCOPE_REQUIRED")

    def test_title_too_long_rejected(self):
        r = bb._validate_commercial_offer_snapshots("T" * 301, "Scope")
        self.assertFalse(r["ok"])

    def test_scope_too_long_rejected(self):
        r = bb._validate_commercial_offer_snapshots("Title", "S" * 10001)
        self.assertFalse(r["ok"])

    def test_trims_whitespace(self):
        r = bb._validate_commercial_offer_snapshots("  Title  ", "  Scope  ")
        self.assertEqual(r["title"], "Title")
        self.assertEqual(r["scope"], "Scope")


# ─────────────────────────────────────────────────────────────
# Relation validation
# ─────────────────────────────────────────────────────────────

_ACTIVE_CLIENT = {
    "person_id": "PRS-001", "status": "active", "person_type": "клиент",
    "biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-001",
}


def _relation_happy_patches():
    return [
        patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]),
        patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT),
        patch("business_core.person_manager.is_person_archived", return_value=False),
        patch("business_core.person_manager.is_client_person", return_value=True),
        patch("business_core.person_manager.has_person_business_link", return_value=True),
    ]


class TestValidateRelations(unittest.TestCase):
    def test_requires_business(self):
        r = bb._validate_commercial_offer_relations("", "PRS-001", service_id="SVC-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "BUSINESS_NOT_FOUND")

    def test_requires_client(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]):
            r = bb._validate_commercial_offer_relations("BIZ-001", "", service_id="SVC-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "CLIENT_NOT_FOUND")

    def test_requires_at_least_one_context(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            r = bb._validate_commercial_offer_relations("BIZ-001", "PRS-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_CONTEXT_REQUIRED")

    def test_service_context_sufficient(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}):
            r = bb._validate_commercial_offer_relations("BIZ-001", "PRS-001", service_id="SVC-001")
        self.assertTrue(r["ok"])

    def test_client_business_mismatch_blocks(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=False):
            r = bb._validate_commercial_offer_relations("BIZ-001", "PRS-001", service_id="SVC-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_RELATION_MISMATCH")

    def test_service_not_found(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value=None):
            r = bb._validate_commercial_offer_relations("BIZ-001", "PRS-001", service_id="SVC-999")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "SERVICE_NOT_FOUND")

    def test_document_wrong_business_blocks(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.document_manager.find_document_by_id", return_value={"business_id": "BIZ-999"}):
            r = bb._validate_commercial_offer_relations("BIZ-001", "PRS-001", service_id="SVC-001", offer_document_id="DREG-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_RELATION_MISMATCH")


# ─────────────────────────────────────────────────────────────
# Creation / idempotency
# ─────────────────────────────────────────────────────────────

class TestCreateCommercialOffer(unittest.TestCase):
    def test_requires_business_id(self):
        r = bb.create_commercial_offer("", "PRS-001", "T", "S", "100", "KZT", "2026-12-31", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "BUSINESS_NOT_FOUND")

    def test_requires_idempotency_key(self):
        r = bb.create_commercial_offer("BIZ-001", "PRS-001", "T", "S", "100", "KZT", "2026-12-31")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED")

    def test_invalid_amount_propagates(self):
        r = bb.create_commercial_offer("BIZ-001", "PRS-001", "T", "S", "-5", "KZT", "2026-12-31", caller_idempotency_key="K1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE")

    def test_creates_new_offer_zero_matches(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key", return_value=[]), \
             patch("business_core.offer_manager.generate_next_series_id", return_value="OFS-001"), \
             patch("business_core.offer_manager.create_commercial_offer",
                   return_value={"ok": True, "commercial_offer_id": "OFR-001", "code": "", "error": None}), \
             patch("business_core.offer_manager.find_commercial_offer_by_id",
                   return_value={"Commercial Offer ID": "OFR-001", "Status": "draft"}):
            r = bb.create_commercial_offer(
                "BIZ-001", "PRS-001", "Title", "Scope", "150000", "KZT", "2026-12-31",
                service_id="SVC-001", caller_idempotency_key="K1",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_CREATED")
        self.assertTrue(r["created"])
        self.assertEqual(r["version_number"], 1)

    def test_reuses_on_one_match(self):
        existing = {
            "Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Version Number": "1",
            "Status": "draft", "Object ID": "", "Service ID": "SVC-001", "Roadmap ID": "",
            "Offer Document ID": "", "Quoted Amount": "150000.00", "Currency": "KZT", "Valid Until": "2026-12-31",
        }
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key", return_value=[existing]):
            r = bb.create_commercial_offer(
                "BIZ-001", "PRS-001", "Title", "Scope", "150000", "KZT", "2026-12-31",
                service_id="SVC-001", caller_idempotency_key="K1",
            )
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_REUSED")
        self.assertTrue(r["reused"])

    def test_multiple_matches_block(self):
        matches = [{"Commercial Offer ID": "OFR-001"}, {"Commercial Offer ID": "OFR-002"}]
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key", return_value=matches):
            r = bb.create_commercial_offer(
                "BIZ-001", "PRS-001", "Title", "Scope", "150000", "KZT", "2026-12-31",
                service_id="SVC-001", caller_idempotency_key="K1",
            )
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "MULTIPLE_COMMERCIAL_OFFER_MATCHES")
        self.assertEqual(set(r["conflicting_ids"]), {"OFR-001", "OFR-002"})

    def test_no_title_or_amount_date_dedup(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key") as mock_lookup, \
             patch("business_core.offer_manager.generate_next_series_id", return_value="OFS-002"), \
             patch("business_core.offer_manager.create_commercial_offer",
                   return_value={"ok": True, "commercial_offer_id": "OFR-002", "code": "", "error": None}), \
             patch("business_core.offer_manager.find_commercial_offer_by_id",
                   return_value={"Commercial Offer ID": "OFR-002", "Status": "draft"}):
            mock_lookup.return_value = []
            bb.create_commercial_offer(
                "BIZ-001", "PRS-001", "Different Title", "Scope", "999999", "KZT", "2026-12-31",
                service_id="SVC-001", caller_idempotency_key="K2",
            )
            mock_lookup.assert_called_once_with("BIZ-001", "K2")


# ─────────────────────────────────────────────────────────────
# Revision / branching
# ─────────────────────────────────────────────────────────────

_SOURCE_OFFER = {
    "Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Version Number": "1",
    "Business ID": "BIZ-001", "Client ID": "PRS-001", "Status": "sent",
    "Title Snapshot": "Title", "Scope Snapshot": "Scope", "Quoted Amount": "150000.00",
    "Currency": "KZT", "Valid Until": "2026-12-31",
    "Object ID": "", "Service ID": "SVC-001", "Roadmap ID": "", "Offer Document ID": "",
}


class TestReviseCommercialOffer(unittest.TestCase):
    def test_source_not_found(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=None):
            r = bb.revise_commercial_offer("OFR-999", "K1", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_NOT_FOUND")

    def test_requires_idempotency_key(self):
        r = bb.revise_commercial_offer("OFR-001", "", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED")

    def test_non_latest_source_blocks(self):
        latest = {**_SOURCE_OFFER, "Commercial Offer ID": "OFR-002", "Version Number": "2"}
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_SOURCE_OFFER), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": latest}):
            r = bb.revise_commercial_offer("OFR-001", "K1", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_NOT_LATEST_VERSION")

    def test_branching_blocked(self):
        existing_child = {**_SOURCE_OFFER, "Commercial Offer ID": "OFR-002", "Previous Commercial Offer ID": "OFR-001", "Version Number": "2"}
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_SOURCE_OFFER), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _SOURCE_OFFER}), \
             patch("business_core.offer_manager.list_commercial_offers_by_series", return_value=[_SOURCE_OFFER, existing_child]):
            r = bb.revise_commercial_offer("OFR-001", "K1", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR")

    def test_successful_revision_increments_version(self):
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_SOURCE_OFFER), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _SOURCE_OFFER}), \
             patch("business_core.offer_manager.list_commercial_offers_by_series", return_value=[_SOURCE_OFFER]), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key", return_value=[]), \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.create_commercial_offer",
                   return_value={"ok": True, "commercial_offer_id": "OFR-002", "code": "", "error": None}), \
             patch("business_core.offer_manager.find_commercial_offer_by_id",
                   side_effect=[_SOURCE_OFFER, {"Commercial Offer ID": "OFR-002", "Status": "draft"}]):
            r = bb.revise_commercial_offer("OFR-001", "K2", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_REVISED")
        self.assertEqual(r["version_number"], 2)
        self.assertEqual(r["previous_commercial_offer_id"], "OFR-001")
        self.assertTrue(r["revised"])

    def test_source_row_not_mutated(self):
        """The revision path must never call any low-level update
        function against the source row — only create a new row."""
        patches = _relation_happy_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_SOURCE_OFFER), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _SOURCE_OFFER}), \
             patch("business_core.offer_manager.list_commercial_offers_by_series", return_value=[_SOURCE_OFFER]), \
             patch("business_core.offer_manager.find_commercial_offers_by_idempotency_key", return_value=[]), \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.offer_manager.update_commercial_offer_status") as mock_update_status, \
             patch("business_core.offer_manager.update_commercial_offer_draft_fields") as mock_update_draft, \
             patch("business_core.offer_manager.create_commercial_offer",
                   return_value={"ok": True, "commercial_offer_id": "OFR-002", "code": "", "error": None}), \
             patch("business_core.offer_manager.find_commercial_offer_by_id",
                   side_effect=[_SOURCE_OFFER, {"Commercial Offer ID": "OFR-002", "Status": "draft"}]):
            bb.revise_commercial_offer("OFR-001", "K2", "dida")
        mock_update_status.assert_not_called()
        mock_update_draft.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Lifecycle transitions
# ─────────────────────────────────────────────────────────────

def _offer(status, **overrides):
    base = {"Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Business ID": "BIZ-001", "Status": status}
    base.update(overrides)
    return base


class TestSendCommercialOffer(unittest.TestCase):
    def test_draft_to_sent(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("draft")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("draft")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.send_commercial_offer("OFR-001", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_SENT")
        self.assertTrue(r["sent"])

    def test_requires_actor(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("draft")):
            r = bb.send_commercial_offer("OFR-001", "")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_ACTOR_REQUIRED")

    def test_not_found(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=None):
            r = bb.send_commercial_offer("OFR-999", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_NOT_FOUND")

    def test_invalid_source_status(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("accepted")):
            r = bb.send_commercial_offer("OFR-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_TRANSITION")


class TestAcceptCommercialOffer(unittest.TestCase):
    def test_sent_to_accepted(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("sent")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.accept_commercial_offer("OFR-001", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_ACCEPTED")
        self.assertTrue(r["accepted"])

    def test_only_latest_may_be_accepted(self):
        newer = _offer("sent", **{"Commercial Offer ID": "OFR-002"})
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": newer}):
            r = bb.accept_commercial_offer("OFR-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_NOT_LATEST_VERSION")

    def test_draft_cannot_be_accepted(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("draft")):
            r = bb.accept_commercial_offer("OFR-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_TRANSITION")

    def test_no_op_when_already_accepted(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("accepted")):
            r = bb.accept_commercial_offer("OFR-001", "dida")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_STATUS_UNCHANGED")
        self.assertFalse(r["changed"])

    def test_never_creates_payment_obligation(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("sent")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.business_builder.create_payment_obligation") as mock_pay:
            bb.accept_commercial_offer("OFR-001", "dida")
        mock_pay.assert_not_called()


class TestRejectCommercialOffer(unittest.TestCase):
    def test_requires_reason(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")):
            r = bb.reject_commercial_offer("OFR-001", "dida", "")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_REJECTION_REASON_REQUIRED")

    def test_sent_to_rejected(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("sent")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.reject_commercial_offer("OFR-001", "dida", "too expensive")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_REJECTED")


class TestExpireCommercialOffer(unittest.TestCase):
    def test_sent_to_expired(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("sent")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.expire_commercial_offer("OFR-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_EXPIRED")

    def test_accepted_cannot_expire(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("accepted")):
            r = bb.expire_commercial_offer("OFR-001")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_TRANSITION")


class TestCancelCommercialOffer(unittest.TestCase):
    def test_draft_to_cancelled(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("draft")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("draft")}), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.cancel_commercial_offer("OFR-001", "dida", "no longer needed")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_CANCELLED")

    def test_accepted_cannot_cancel(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("accepted")):
            r = bb.cancel_commercial_offer("OFR-001", "dida", "reason")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_TRANSITION")

    def test_requires_reason(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("draft")), \
             patch("business_core.offer_manager.find_latest_commercial_offer_in_series",
                   return_value={"ok": True, "code": "", "error": None, "offer": _offer("draft")}):
            r = bb.cancel_commercial_offer("OFR-001", "dida", "")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_CANCELLATION_REASON_REQUIRED")


class TestArchiveCommercialOffer(unittest.TestCase):
    def test_any_terminal_to_archived(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("rejected")), \
             patch("business_core.offer_manager.update_commercial_offer_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.archive_commercial_offer("OFR-001")
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_ARCHIVED")

    def test_archived_is_terminal_no_reopen(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("archived")):
            r = bb.send_commercial_offer("OFR-001", "dida")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_TRANSITION")


# ─────────────────────────────────────────────────────────────
# Draft update / effective expiration
# ─────────────────────────────────────────────────────────────

class TestUpdateCommercialOfferDraft(unittest.TestCase):
    def test_blocked_when_not_draft(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_offer("sent")):
            r = bb.update_commercial_offer_draft("OFR-001", {"Notes": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_IMMUTABLE")

    def test_updates_amount_in_draft(self):
        offer = _offer("draft", **{"Client ID": "PRS-001"})
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=offer), \
             patch("business_core.offer_manager.update_commercial_offer_draft_fields",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}):
            r = bb.update_commercial_offer_draft("OFR-001", {"Quoted Amount": "200000"})
        self.assertTrue(r["ok"])


class TestEffectiveExpiration(unittest.TestCase):
    def test_sent_past_valid_until_is_effectively_expired(self):
        offer = {"Status": "sent", "Valid Until": "2026-01-01"}
        self.assertTrue(bb.is_commercial_offer_effectively_expired(offer, reference_date=date(2026, 2, 1)))

    def test_sent_future_valid_until_not_expired(self):
        offer = {"Status": "sent", "Valid Until": "2026-12-31"}
        self.assertFalse(bb.is_commercial_offer_effectively_expired(offer, reference_date=date(2026, 1, 1)))

    def test_accepted_never_effectively_expired(self):
        offer = {"Status": "accepted", "Valid Until": "2020-01-01"}
        self.assertFalse(bb.is_commercial_offer_effectively_expired(offer, reference_date=date(2026, 1, 1)))

    def test_draft_never_effectively_expired(self):
        offer = {"Status": "draft", "Valid Until": "2020-01-01"}
        self.assertFalse(bb.is_commercial_offer_effectively_expired(offer, reference_date=date(2026, 1, 1)))


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A4-H1: update_commercial_offer_admin_fields wrapper
# result-contract correction — proves a success/no-op code is
# synthesized only when the manager's ok is exactly True, and that
# an existing non-empty manager failure code is always preserved.
# ─────────────────────────────────────────────────────────────

class TestUpdateCommercialOfferAdminFieldsWrapper(unittest.TestCase):
    def _run(self, manager_return):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=_SOURCE_OFFER), \
             patch("business_core.offer_manager.update_commercial_offer_admin_fields", return_value=manager_return):
            return bb.update_commercial_offer_admin_fields("OFR-001", {"Notes": "x"})

    def test_ok_true_changed_true_synthesizes_updated(self):
        r = self._run({"ok": True, "changed": True, "code": "", "error": None})
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_UPDATED")

    def test_ok_true_changed_false_synthesizes_unchanged(self):
        r = self._run({"ok": True, "changed": False, "code": "", "error": None})
        self.assertTrue(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_UPDATE_UNCHANGED")

    def test_ok_false_blank_code_stays_blank(self):
        r = self._run({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "")

    def test_ok_false_not_found_code_preserved(self):
        r = self._run({"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_NOT_FOUND")

    def test_ok_false_immutable_code_preserved(self):
        r = self._run({"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_IMMUTABLE", "error": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "COMMERCIAL_OFFER_IMMUTABLE")

    def test_ok_false_known_validation_code_preserved(self):
        r = self._run({"ok": False, "changed": False, "code": "INVALID_COMMERCIAL_OFFER_AMOUNT", "error": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "INVALID_COMMERCIAL_OFFER_AMOUNT")

    def test_missing_ok_key_no_success_synthesis(self):
        r = self._run({"changed": True, "code": "", "error": None})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "")

    def test_non_dict_manager_result_no_exception(self):
        r = self._run("not a dict")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "")

    def test_truthy_non_boolean_ok_no_success_synthesis(self):
        r = self._run({"ok": "true", "changed": True, "code": "", "error": None})
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "")

    def test_no_wrapper_output_accepts_ok_false_with_unchanged_code(self):
        # Explicit regression guard for the exact defect shape: the
        # wrapper itself must never produce this combination for a
        # blank manager code, regardless of caller.
        r = self._run({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})
        self.assertFalse(r["ok"] and r["code"] == "COMMERCIAL_OFFER_UPDATE_UNCHANGED")
        self.assertNotEqual(r["code"], "COMMERCIAL_OFFER_UPDATE_UNCHANGED")


if __name__ == "__main__":
    unittest.main()
