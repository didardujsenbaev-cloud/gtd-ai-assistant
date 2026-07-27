"""
Tests for Phase 41C — Lead / Sales Funnel Domain Foundation:
business_core/business_builder.py's Lead orchestration section
(ADR-024). Covers contact normalization, contact-channel requirement,
Expected Value/currency pairing, datetime normalization, relation
validation, creation idempotency, duplicate-contact warning, lifecycle
transitions, conversion, active-Lead updates, and the follow-up-due
helper. lead_manager.py's own low-level behavior is covered separately
in test_lead_manager.py.

No live Sheets/Drive/Telegram/HTTP/socket access — mocks only.
Registered in conftest.py's hard socket-block set before this file's
logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb


# ─────────────────────────────────────────────────────────────
# Contact name
# ─────────────────────────────────────────────────────────────

class TestValidateLeadContactName(unittest.TestCase):
    def test_required(self):
        result = bb._validate_lead_contact_name("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_NAME_REQUIRED")

    def test_blank_after_trim_blocks(self):
        result = bb._validate_lead_contact_name("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_NAME_REQUIRED")

    def test_trims_whitespace(self):
        result = bb._validate_lead_contact_name("  Ivan Ivanov  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "Ivan Ivanov")

    def test_bounded_length(self):
        result = bb._validate_lead_contact_name("A" * 301)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_NAME_REQUIRED")

    def test_max_length_ok(self):
        result = bb._validate_lead_contact_name("A" * 300)
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Phone / WhatsApp
# ─────────────────────────────────────────────────────────────

class TestNormalizeLeadPhone(unittest.TestCase):
    def test_blank_stays_blank(self):
        result = bb.normalize_lead_phone("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_none_stays_blank(self):
        result = bb.normalize_lead_phone(None)
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_removes_formatting_characters(self):
        result = bb.normalize_lead_phone("+7 (700) 123-45-67")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "+77001234567")

    def test_preserves_leading_plus(self):
        result = bb.normalize_lead_phone("+77001234567")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "+77001234567")

    def test_no_plus_ok(self):
        result = bb.normalize_lead_phone("77001234567")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "77001234567")

    def test_no_country_code_inference(self):
        """A bare local number is never rewritten with an inferred
        country code — normalization is purely mechanical."""
        result = bb.normalize_lead_phone("7001234567")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "7001234567")
        self.assertNotIn("+7", result["normalized"][:2])

    def test_too_short_rejected(self):
        result = bb.normalize_lead_phone("12345")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_PHONE")

    def test_too_long_rejected(self):
        result = bb.normalize_lead_phone("1" * 20)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_PHONE")

    def test_letters_rejected(self):
        result = bb.normalize_lead_phone("+7abc1234567")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_PHONE")


class TestNormalizeLeadWhatsapp(unittest.TestCase):
    def test_blank_stays_blank(self):
        result = bb.normalize_lead_whatsapp("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_valid_normalizes(self):
        result = bb.normalize_lead_whatsapp("+7 700 123 45 67")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "+77001234567")

    def test_invalid_rejected_with_whatsapp_specific_code(self):
        result = bb.normalize_lead_whatsapp("bad")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_WHATSAPP")

    def test_phone_and_whatsapp_codes_are_distinct(self):
        phone_result = bb.normalize_lead_phone("bad")
        whatsapp_result = bb.normalize_lead_whatsapp("bad")
        self.assertNotEqual(phone_result["code"], whatsapp_result["code"])


# ─────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────

class TestNormalizeLeadEmail(unittest.TestCase):
    def test_blank_stays_blank(self):
        result = bb.normalize_lead_email("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_lowercased(self):
        result = bb.normalize_lead_email("Ivan@Example.COM")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "ivan@example.com")

    def test_trimmed(self):
        result = bb.normalize_lead_email("  ivan@example.com  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "ivan@example.com")

    def test_no_at_sign_rejected(self):
        result = bb.normalize_lead_email("not-an-email")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EMAIL")

    def test_multiple_at_signs_rejected(self):
        result = bb.normalize_lead_email("a@b@c.com")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EMAIL")

    def test_empty_local_part_rejected(self):
        result = bb.normalize_lead_email("@example.com")
        self.assertFalse(result["ok"])

    def test_empty_domain_rejected(self):
        result = bb.normalize_lead_email("ivan@")
        self.assertFalse(result["ok"])

    def test_internal_whitespace_rejected(self):
        result = bb.normalize_lead_email("ivan ivanov@example.com")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EMAIL")

    def test_too_long_rejected(self):
        result = bb.normalize_lead_email("a" * 250 + "@example.com")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EMAIL")


# ─────────────────────────────────────────────────────────────
# Contact-channel requirement
# ─────────────────────────────────────────────────────────────

class TestContactChannelRequirement(unittest.TestCase):
    def test_none_supplied_blocks(self):
        result = bb._validate_lead_contact_channel("", "", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_CHANNEL_REQUIRED")

    def test_phone_only_ok(self):
        result = bb._validate_lead_contact_channel("+77001234567", "", "")
        self.assertTrue(result["ok"])

    def test_whatsapp_only_ok(self):
        result = bb._validate_lead_contact_channel("", "+77001234567", "")
        self.assertTrue(result["ok"])

    def test_email_only_ok(self):
        result = bb._validate_lead_contact_channel("", "", "ivan@example.com")
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Expected Value / Currency
# ─────────────────────────────────────────────────────────────

class TestNormalizeLeadExpectedValue(unittest.TestCase):
    def test_float_rejected(self):
        result = bb.normalize_lead_expected_value(100.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE")

    def test_comma_rejected(self):
        result = bb.normalize_lead_expected_value("100,000.00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE")

    def test_scientific_notation_rejected(self):
        result = bb.normalize_lead_expected_value("1e5")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE")

    def test_zero_rejected(self):
        result = bb.normalize_lead_expected_value("0.00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE")

    def test_negative_rejected(self):
        result = bb.normalize_lead_expected_value("-100.00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE")

    def test_scale_over_2_rejected(self):
        result = bb.normalize_lead_expected_value("100.123")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE_SCALE")

    def test_valid_quantized(self):
        result = bb.normalize_lead_expected_value("100")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "100.00")

    def test_never_emits_payment_or_offer_codes(self):
        for raw in (100.5, "100,000", "1e5", "0", "-1", "100.123", "bad"):
            result = bb.normalize_lead_expected_value(raw)
            if not result["ok"]:
                self.assertNotIn("PAYMENT", result["code"])
                self.assertNotIn("OFFER", result["code"])


class TestNormalizeLeadCurrency(unittest.TestCase):
    def test_required(self):
        result = bb.normalize_lead_currency("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_CURRENCY")

    def test_uppercased(self):
        result = bb.normalize_lead_currency("kzt")
        self.assertTrue(result["ok"])
        self.assertEqual(result["currency"], "KZT")

    def test_wrong_length_rejected(self):
        result = bb.normalize_lead_currency("KZ")
        self.assertFalse(result["ok"])


class TestExpectedValuePair(unittest.TestCase):
    def test_both_blank_ok(self):
        result = bb._validate_lead_expected_value_pair("", "")
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_value"], "")
        self.assertEqual(result["currency"], "")

    def test_value_without_currency_blocks(self):
        result = bb._validate_lead_expected_value_pair("100.00", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE")

    def test_currency_without_value_blocks(self):
        result = bb._validate_lead_expected_value_pair("", "KZT")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_EXPECTED_VALUE")

    def test_both_present_valid(self):
        result = bb._validate_lead_expected_value_pair("100.00", "KZT")
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_value"], "100.00")
        self.assertEqual(result["currency"], "KZT")


# ─────────────────────────────────────────────────────────────
# Datetime normalization
# ─────────────────────────────────────────────────────────────

class TestNormalizeLeadDatetime(unittest.TestCase):
    def test_blank_stays_blank(self):
        result = bb.normalize_lead_datetime("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_valid_with_offset(self):
        result = bb.normalize_lead_datetime("2026-08-01T10:00:00+00:00")
        self.assertTrue(result["ok"])

    def test_valid_with_z_suffix(self):
        result = bb.normalize_lead_datetime("2026-08-01T10:00:00Z")
        self.assertTrue(result["ok"])

    def test_timezone_naive_rejected(self):
        result = bb.normalize_lead_datetime("2026-08-01T10:00:00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_DATETIME")

    def test_garbage_rejected(self):
        result = bb.normalize_lead_datetime("not-a-date")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_DATETIME")

    def test_deterministic(self):
        r1 = bb.normalize_lead_datetime("2026-08-01T10:00:00Z")
        r2 = bb.normalize_lead_datetime("2026-08-01T10:00:00Z")
        self.assertEqual(r1["normalized"], r2["normalized"])


# ─────────────────────────────────────────────────────────────
# Relation validation
# ─────────────────────────────────────────────────────────────

_ACTIVE_PERSON = {"ID": "PRS-002", "Тип": "сотрудник"}
_ACTIVE_CLIENT = {"ID": "PRS-001", "Тип": "клиент"}


def _relation_happy_patches():
    return [
        patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]),
    ]


class TestValidateLeadRelations(unittest.TestCase):
    def test_business_required(self):
        result = bb._validate_lead_relations("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_business_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[]):
            result = bb._validate_lead_relations("BIZ-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_business_only_ok(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]):
            result = bb._validate_lead_relations("BIZ-001")
        self.assertTrue(result["ok"])

    def test_service_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.service_manager.find_service_by_id", return_value=None):
            result = bb._validate_lead_relations("BIZ-001", service_id="SVC-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SERVICE_NOT_FOUND")

    def test_service_business_mismatch(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-999"}):
            result = bb._validate_lead_relations("BIZ-001", service_id="SVC-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RELATION_MISMATCH")

    def test_channel_not_found(self):
        def _fake_read(key):
            return [{"ID": "BIZ-001"}] if key == "biz_registry" else []
        with patch("business_core.sheets.read_business_sheet", side_effect=_fake_read):
            result = bb._validate_lead_relations("BIZ-001", channel_id="CH-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHANNEL_NOT_FOUND")

    def test_channel_business_mismatch(self):
        def _fake_read(key):
            if key == "biz_registry":
                return [{"ID": "BIZ-001"}]
            if key == "channel_registry":
                return [{"ID": "CH-001", "Бизнес ID": "BIZ-999"}]
            return []
        with patch("business_core.sheets.read_business_sheet", side_effect=_fake_read):
            result = bb._validate_lead_relations("BIZ-001", channel_id="CH-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RELATION_MISMATCH")

    def test_assigned_person_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb._validate_lead_relations("BIZ-001", assigned_person_id="PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_assigned_person_archived(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_PERSON), \
             patch("business_core.person_manager.is_person_archived", return_value=True):
            result = bb._validate_lead_relations("BIZ-001", assigned_person_id="PRS-002")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_assigned_person_not_linked_to_business(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_PERSON), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.has_person_business_link", return_value=False):
            result = bb._validate_lead_relations("BIZ-001", assigned_person_id="PRS-002")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RELATION_MISMATCH")

    def test_assigned_person_ok(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_PERSON), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.has_person_business_link", return_value=True):
            result = bb._validate_lead_relations("BIZ-001", assigned_person_id="PRS-002")
        self.assertTrue(result["ok"])

    def test_never_mutates_related_domains(self):
        """Read-only relation checks — no manager function beyond
        find_*/is_* read helpers is ever called."""
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]) as mock_read:
            bb._validate_lead_relations("BIZ-001")
            mock_read.assert_called()


class TestValidateLeadConversionTarget(unittest.TestCase):
    def test_client_not_found(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb._validate_lead_conversion_target("BIZ-001", "PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_client_archived(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=True):
            result = bb._validate_lead_conversion_target("BIZ-001", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_not_a_client(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=False):
            result = bb._validate_lead_conversion_target("BIZ-001", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_business_mismatch(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=False):
            result = bb._validate_lead_conversion_target("BIZ-001", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RELATION_MISMATCH")

    def test_valid_client(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True):
            result = bb._validate_lead_conversion_target("BIZ-001", "PRS-001")
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Creation
# ─────────────────────────────────────────────────────────────

class TestCreateLead(unittest.TestCase):
    def test_requires_business_id(self):
        result = bb.create_lead("", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_requires_created_by(self):
        result = bb.create_lead("BIZ-001", "Ivan Ivanov", created_by="", caller_idempotency_key="k")
        self.assertFalse(result["ok"])

    def test_requires_idempotency_key(self):
        result = bb.create_lead("BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_IDEMPOTENCY_REQUIRED")

    def test_requires_contact_channel(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]):
            result = bb.create_lead("BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_CHANNEL_REQUIRED")

    def test_successful_creation(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": True, "lead_id": "LED-001", "code": "LEAD_CREATED", "error": None}), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Status": "new"}):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_CREATED")
        self.assertEqual(result["lead_id"], "LED-001")
        self.assertTrue(result["created"])
        self.assertEqual(result["final_status"], "new")

    def test_idempotency_reuse(self):
        existing = {
            "Lead ID": "LED-001", "Service ID": "", "Channel ID": "", "Assigned Person ID": "",
            "Converted Client ID": "", "Expected Value": "", "Currency": "",
            "Next Follow-up At": "", "Last Contacted At": "", "Status": "new",
        }
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[existing]):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_REUSED")
        self.assertTrue(result["reused"])
        self.assertEqual(result["lead_id"], "LED-001")

    def test_multiple_idempotency_matches_block(self):
        matches = [{"Lead ID": "LED-001"}, {"Lead ID": "LED-002"}]
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=matches):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_LEAD_MATCHES")
        self.assertEqual(set(result["conflicting_ids"]), {"LED-001", "LED-002"})
        self.assertTrue(result["retry_safe"])

    def test_duplicate_contact_warning_does_not_block_creation(self):
        dup = {"Lead ID": "LED-999"}
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[dup]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": True, "lead_id": "LED-001", "code": "LEAD_CREATED", "error": None}), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Status": "new"}):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_CREATED")
        self.assertEqual(result["duplicate_contact_ids"], ("LED-999",))
        self.assertIn("LEAD_CONTACT_DUPLICATE_WARNING", result["warnings"])

    def test_no_duplicate_warning_never_auto_merges(self):
        """The result never carries a merged/reused Lead ID from a
        duplicate match — creation always proceeds independently."""
        dup = {"Lead ID": "LED-999"}
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[dup]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": True, "lead_id": "LED-001", "code": "LEAD_CREATED", "error": None}), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Status": "new"}):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertNotEqual(result["lead_id"], "LED-999")

    def test_persistence_failure(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": False, "lead_id": "", "code": "", "error": "boom"}):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_PERSISTENCE_FAILED")
        self.assertTrue(result["retry_safe"])

    def test_post_write_verification_failure(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": True, "lead_id": "LED-001", "code": "LEAD_CREATED", "error": None}), \
             patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_expected_value_never_propagated_to_result_as_offer_or_payment(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.lead_manager.find_leads_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[]), \
             patch("business_core.lead_manager.create_lead", return_value={"ok": True, "lead_id": "LED-001", "code": "LEAD_CREATED", "error": None}), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Status": "new"}):
            result = bb.create_lead(
                "BIZ-001", "Ivan Ivanov", created_by="admin", caller_idempotency_key="k",
                phone_snapshot="+77001234567", expected_value="500.00", currency="KZT",
            )
        self.assertTrue(result["ok"])
        self.assertNotIn("commercial_offer_id", result)
        self.assertNotIn("payment_obligation_id", result)


# ─────────────────────────────────────────────────────────────
# Lifecycle transitions
# ─────────────────────────────────────────────────────────────

def _lead(status="new", **overrides):
    base = {"Lead ID": "LED-001", "Business ID": "BIZ-001", "Status": status, "Converted Client ID": ""}
    base.update(overrides)
    return base


class TestLeadTransitionsGeneral(unittest.TestCase):
    def test_lead_not_found(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            result = bb.contact_lead("LED-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_NOT_FOUND")

    def test_same_status_is_noop(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("contacted")):
            result = bb.contact_lead("LED-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_STATUS_UNCHANGED")
        self.assertFalse(result["changed"])

    def test_invalid_status_rejected(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")):
            result = bb._transition_lead("LED-001", "not-a-status")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_STATUS")

    def test_archived_is_terminal(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("archived")):
            result = bb.contact_lead("LED-001")
        self.assertFalse(result["ok"])
        self.assertIn(result["code"], ("INVALID_LEAD_TRANSITION", "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION"))

    def test_restore_from_unqualified_blocked(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("unqualified")):
            result = bb.contact_lead("LED-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_restore_from_lost_blocked(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("lost")):
            result = bb.qualify_lead("LED-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_lost_to_unqualified_blocked(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("lost")):
            result = bb.unqualify_lead("LED-001", disposition_reason="x")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_TRANSITION")


class TestContactedTransition(unittest.TestCase):
    def test_new_to_contacted(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.contact_lead("LED-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACTED")
        self.assertTrue(result["contacted"])

    def test_qualified_to_contacted_allowed(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.contact_lead("LED-001")
        self.assertTrue(result["ok"])

    def test_explicit_last_contacted_at_validated(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")):
            result = bb.contact_lead("LED-001", last_contacted_at="not-a-date")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_DATETIME")

    def test_no_automatic_last_contacted_at_without_explicit_value(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")), \
             patch("business_core.lead_manager.update_lead_status") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            bb.contact_lead("LED-001")
            self.assertEqual(mock_update.call_args.kwargs["last_contacted_at"], "")


class TestQualifiedTransition(unittest.TestCase):
    def test_new_to_qualified(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.qualify_lead("LED-001", qualification_notes="Good fit")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_QUALIFIED")
        self.assertTrue(result["qualified"])


class TestUnqualifiedTransition(unittest.TestCase):
    def test_requires_disposition_reason(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")):
            result = bb.unqualify_lead("LED-001", disposition_reason="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_DISPOSITION_REASON_REQUIRED")

    def test_succeeds_with_reason(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("contacted")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.unqualify_lead("LED-001", disposition_reason="Не наш профиль")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_UNQUALIFIED")
        self.assertTrue(result["unqualified"])


class TestLostTransition(unittest.TestCase):
    def test_requires_disposition_reason(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")):
            result = bb.lose_lead("LED-001", disposition_reason="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_DISPOSITION_REASON_REQUIRED")

    def test_succeeds_with_reason(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.lose_lead("LED-001", disposition_reason="Выбрал конкурента")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_LOST")
        self.assertTrue(result["lost"])


class TestArchiveTransition(unittest.TestCase):
    def test_from_new(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.archive_lead("LED-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_ARCHIVED")
        self.assertTrue(result["archived"])

    def test_from_unqualified(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("unqualified")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.archive_lead("LED-001")
        self.assertTrue(result["ok"])

    def test_from_converted(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("converted")), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.archive_lead("LED-001")
        self.assertTrue(result["ok"])

    def test_archived_from_archived_is_noop(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("archived")):
            result = bb.archive_lead("LED-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_STATUS_UNCHANGED")


# ─────────────────────────────────────────────────────────────
# Conversion
# ─────────────────────────────────────────────────────────────

class TestConvertLead(unittest.TestCase):
    def test_requires_client_id(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")):
            result = bb.convert_lead("LED-001", "", "admin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONVERSION_CLIENT_REQUIRED")

    def test_requires_actor(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")):
            result = bb.convert_lead("LED-001", "PRS-001", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONVERSION_ACTOR_REQUIRED")

    def test_invalid_transition_from_terminal(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("unqualified")):
            result = bb.convert_lead("LED-001", "PRS-001", "admin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_TRANSITION")

    def test_client_not_found(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")), \
             patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb.convert_lead("LED-001", "PRS-999", "admin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_successful_conversion_direct_from_new(self):
        """ADR-024 §17: direct new → converted is explicitly allowed."""
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("new")), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.convert_lead("LED-001", "PRS-001", "admin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONVERTED")
        self.assertTrue(result["converted"])
        self.assertEqual(result["converted_client_id"], "PRS-001")

    def test_repeat_conversion_to_same_client_is_noop(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("converted", **{"Converted Client ID": "PRS-001"})):
            result = bb.convert_lead("LED-001", "PRS-001", "admin")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_STATUS_UNCHANGED")
        self.assertFalse(result["changed"])

    def test_conversion_to_different_client_after_conversion_blocks(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("converted", **{"Converted Client ID": "PRS-001"})):
            result = bb.convert_lead("LED-001", "PRS-999", "admin")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONVERSION_TARGET_CONFLICT")

    def test_conversion_never_creates_or_mutates_client(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("qualified")), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.lead_manager.update_lead_status", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_update:
            bb.convert_lead("LED-001", "PRS-001", "admin")
            # Only the Lead's own low-level status writer is called —
            # no Client-creating or Client-mutating function.
            mock_update.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Active-Lead updates
# ─────────────────────────────────────────────────────────────

class TestUpdateLead(unittest.TestCase):
    def test_lead_not_found(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            result = bb.update_lead("LED-999", {"Notes": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_NOT_FOUND")

    def test_terminal_status_blocks_active_update(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("converted")):
            result = bb.update_lead("LED-001", {"Company Snapshot": "Acme"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_IMMUTABLE")

    def test_active_status_allows_update(self):
        lead = _lead("new", **{"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""})
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead), \
             patch("business_core.lead_manager.update_lead_active_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_lead("LED-001", {"Company Snapshot": "Acme"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_UPDATED")

    def test_contact_channel_invariant_enforced_on_update(self):
        """Clearing the only contact channel without providing a
        replacement must fail — the invariant must hold after update."""
        lead = _lead("new", **{"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""})
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead):
            result = bb.update_lead("LED-001", {"Phone Snapshot": ""})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_CONTACT_CHANNEL_REQUIRED")

    def test_duplicate_warning_recalculated_on_contact_change(self):
        lead = _lead("new", **{"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""})
        dup = {"Lead ID": "LED-999"}
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead), \
             patch("business_core.lead_manager.find_leads_by_exact_contact_channels", return_value=[dup]), \
             patch("business_core.lead_manager.update_lead_active_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_lead("LED-001", {"Phone Snapshot": "+77009999999"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["duplicate_contact_ids"], ("LED-999",))

    def test_identity_fields_never_accepted(self):
        """update_lead() only ever forwards a known-safe whitelist to
        update_lead_active_fields() — Business ID/Caller Idempotency
        Key/Status are never included even if present in the input
        dict."""
        lead = _lead("new", **{"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""})
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead), \
             patch("business_core.lead_manager.update_lead_active_fields") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            bb.update_lead("LED-001", {"Business ID": "BIZ-999", "Notes": "hi"})
            forwarded = mock_update.call_args.args[1]
            self.assertNotIn("Business ID", forwarded)

    def test_no_op_preserves_timestamp_via_changed_false(self):
        lead = _lead("new", **{"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""})
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead), \
             patch("business_core.lead_manager.update_lead_active_fields", return_value={"ok": True, "changed": False, "code": "", "error": None}):
            result = bb.update_lead("LED-001", {"Notes": "same"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_UPDATE_UNCHANGED")
        self.assertFalse(result["changed"])


class TestUpdateLeadAdminFields(unittest.TestCase):
    def test_notes_mutable_in_terminal_status(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=_lead("archived")), \
             patch("business_core.lead_manager.update_lead_admin_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_lead_admin_fields("LED-001", {"Notes": "note"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "LEAD_UPDATED")

    def test_lead_not_found(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            result = bb.update_lead_admin_fields("LED-999", {"Notes": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_NOT_FOUND")


# ─────────────────────────────────────────────────────────────
# Follow-up due
# ─────────────────────────────────────────────────────────────

class TestFollowUpDue(unittest.TestCase):
    def test_no_follow_up_date_not_due(self):
        lead = _lead("new", **{"Next Follow-up At": ""})
        self.assertFalse(bb.is_lead_follow_up_due(lead))

    def test_past_date_is_due(self):
        from datetime import datetime, timezone
        lead = _lead("new", **{"Next Follow-up At": "2020-01-01T00:00:00Z"})
        reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(bb.is_lead_follow_up_due(lead, reference_datetime=reference))

    def test_future_date_not_due(self):
        from datetime import datetime, timezone
        lead = _lead("new", **{"Next Follow-up At": "2030-01-01T00:00:00Z"})
        reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(bb.is_lead_follow_up_due(lead, reference_datetime=reference))

    def test_archived_never_due(self):
        from datetime import datetime, timezone
        lead = _lead("archived", **{"Next Follow-up At": "2020-01-01T00:00:00Z"})
        reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(bb.is_lead_follow_up_due(lead, reference_datetime=reference))

    def test_converted_never_due(self):
        from datetime import datetime, timezone
        lead = _lead("converted", **{"Next Follow-up At": "2020-01-01T00:00:00Z"})
        reference = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(bb.is_lead_follow_up_due(lead, reference_datetime=reference))

    def test_never_writes(self):
        """Stateless helper — no Sheets/manager write function is ever
        imported or called."""
        lead = _lead("new", **{"Next Follow-up At": "2020-01-01T00:00:00Z"})
        with patch("business_core.lead_manager.update_lead_status") as mock_update:
            bb.is_lead_follow_up_due(lead)
            mock_update.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Boundaries
# ─────────────────────────────────────────────────────────────

class TestBoundaries(unittest.TestCase):
    def test_no_deal_functions(self):
        names = [n for n in dir(bb) if "deal" in n.lower()]
        self.assertEqual(names, [])

    def test_no_lead_interaction_registry_functions(self):
        names = [n for n in dir(bb) if n.lower().startswith("create_lead_interaction") or n.lower().startswith("create_interaction")]
        self.assertEqual(names, [])

    def test_no_relationship_capital_write_in_lead_functions(self):
        import inspect
        for fn_name in ("create_lead", "convert_lead", "update_lead", "_transition_lead"):
            source = inspect.getsource(getattr(bb, fn_name))
            self.assertNotIn("relationship_capital", source)

    def test_conversion_never_calls_create_person(self):
        import inspect
        source = inspect.getsource(bb.convert_lead)
        self.assertNotIn("create_person", source)
        self.assertNotIn("update_person", source)


if __name__ == "__main__":
    unittest.main()
