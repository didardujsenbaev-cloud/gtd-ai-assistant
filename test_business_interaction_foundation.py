"""
Tests for Phase 42C — Interaction / Communication History Domain
Foundation: business_core/business_builder.py's Interaction
orchestration section (ADR-025). Covers Interaction Type/Direction
normalization, Occurred At normalization, content validation, primary-
subject XOR validation, optional-relation validation, creation
idempotency, lifecycle (active/archived), and Notes updates.
interaction_manager.py's own low-level behavior is covered separately
in test_interaction_manager.py.

No live Sheets/Drive/Telegram/HTTP/socket access — mocks only.
Registered in conftest.py's hard socket-block set before this file's
logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb


# ─────────────────────────────────────────────────────────────
# Interaction Type
# ─────────────────────────────────────────────────────────────

class TestNormalizeInteractionType(unittest.TestCase):
    def test_required(self):
        result = bb.normalize_interaction_type("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_TYPE_REQUIRED")

    def test_all_allowed_types(self):
        for t in ("call", "message", "email", "meeting", "note", "other"):
            result = bb.normalize_interaction_type(t)
            self.assertTrue(result["ok"])
            self.assertEqual(result["normalized"], t)

    def test_lowercased(self):
        result = bb.normalize_interaction_type("CALL")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "call")

    def test_unknown_rejected(self):
        result = bb.normalize_interaction_type("whatsapp")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_INTERACTION_TYPE")

    def test_telegram_not_accepted_as_type(self):
        result = bb.normalize_interaction_type("telegram")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Direction
# ─────────────────────────────────────────────────────────────

class TestNormalizeInteractionDirection(unittest.TestCase):
    def test_required_for_call(self):
        result = bb.normalize_interaction_direction("", "call")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_DIRECTION_REQUIRED")

    def test_required_for_message_email_meeting_other(self):
        for t in ("message", "email", "meeting", "other"):
            result = bb.normalize_interaction_direction("", t)
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "INTERACTION_DIRECTION_REQUIRED")

    def test_optional_for_note(self):
        result = bb.normalize_interaction_direction("", "note")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_valid_direction_for_note(self):
        result = bb.normalize_interaction_direction("internal", "note")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "internal")

    def test_all_valid_directions(self):
        for d in ("inbound", "outbound", "internal"):
            result = bb.normalize_interaction_direction(d, "call")
            self.assertTrue(result["ok"])

    def test_invalid_direction_rejected(self):
        result = bb.normalize_interaction_direction("sideways", "call")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_INTERACTION_DIRECTION")

    def test_no_implicit_default(self):
        # Blank for a required type never silently becomes a default value.
        result = bb.normalize_interaction_direction(None, "meeting")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Occurred At
# ─────────────────────────────────────────────────────────────

class TestNormalizeInteractionOccurredAt(unittest.TestCase):
    def test_required(self):
        result = bb.normalize_interaction_occurred_at("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_OCCURRED_AT_REQUIRED")

    def test_valid_with_offset(self):
        result = bb.normalize_interaction_occurred_at("2026-07-01T10:00:00+00:00")
        self.assertTrue(result["ok"])

    def test_valid_with_z_suffix(self):
        result = bb.normalize_interaction_occurred_at("2026-07-01T10:00:00Z")
        self.assertTrue(result["ok"])

    def test_timezone_naive_rejected(self):
        result = bb.normalize_interaction_occurred_at("2026-07-01T10:00:00")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_INTERACTION_OCCURRED_AT")

    def test_garbage_rejected(self):
        result = bb.normalize_interaction_occurred_at("not-a-date")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_INTERACTION_OCCURRED_AT")

    def test_historical_allowed(self):
        result = bb.normalize_interaction_occurred_at("2020-01-01T00:00:00Z")
        self.assertTrue(result["ok"])

    def test_future_within_tolerance_allowed(self):
        reference = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = bb.normalize_interaction_occurred_at("2026-01-01T12:03:00Z", reference_datetime=reference)
        self.assertTrue(result["ok"])

    def test_future_beyond_tolerance_blocked(self):
        reference = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = bb.normalize_interaction_occurred_at("2026-01-01T12:10:00Z", reference_datetime=reference)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_OCCURRED_AT_IN_FUTURE")

    def test_deterministic(self):
        r1 = bb.normalize_interaction_occurred_at("2026-07-01T10:00:00Z")
        r2 = bb.normalize_interaction_occurred_at("2026-07-01T10:00:00Z")
        self.assertEqual(r1["normalized"], r2["normalized"])


# ─────────────────────────────────────────────────────────────
# Content
# ─────────────────────────────────────────────────────────────

class TestValidateInteractionSummary(unittest.TestCase):
    def test_required(self):
        result = bb._validate_interaction_summary("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUMMARY_REQUIRED")

    def test_blank_after_trim_blocks(self):
        result = bb._validate_interaction_summary("   ")
        self.assertFalse(result["ok"])

    def test_trims(self):
        result = bb._validate_interaction_summary("  hi  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "hi")

    def test_too_long_rejected(self):
        result = bb._validate_interaction_summary("A" * 2001)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUMMARY_TOO_LONG")

    def test_max_length_ok(self):
        result = bb._validate_interaction_summary("A" * 2000)
        self.assertTrue(result["ok"])


class TestValidateInteractionOutcome(unittest.TestCase):
    def test_optional_blank_ok(self):
        result = bb._validate_interaction_outcome("")
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], "")

    def test_too_long_rejected(self):
        result = bb._validate_interaction_outcome("A" * 1001)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_OUTCOME_TOO_LONG")


class TestValidateInteractionNotes(unittest.TestCase):
    def test_optional_blank_ok(self):
        result = bb._validate_interaction_notes("")
        self.assertTrue(result["ok"])

    def test_too_long_rejected(self):
        result = bb._validate_interaction_notes("A" * 5001)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOTES_TOO_LONG")


class TestValidateInteractionExternalReference(unittest.TestCase):
    def test_optional_blank_ok(self):
        result = bb._validate_interaction_external_reference("")
        self.assertTrue(result["ok"])

    def test_too_long_rejected(self):
        result = bb._validate_interaction_external_reference("A" * 501)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_EXTERNAL_REFERENCE_TOO_LONG")


# ─────────────────────────────────────────────────────────────
# Primary subject XOR
# ─────────────────────────────────────────────────────────────

_ACTIVE_CLIENT = {"ID": "PRS-001", "Тип": "клиент"}


class TestValidateInteractionSubject(unittest.TestCase):
    def test_neither_blocks(self):
        result = bb._validate_interaction_subject("BIZ-001", "", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUBJECT_REQUIRED")

    def test_both_block(self):
        result = bb._validate_interaction_subject("BIZ-001", "LED-001", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUBJECT_CONFLICT")

    def test_lead_only_valid(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}):
            result = bb._validate_interaction_subject("BIZ-001", "LED-001", "")
        self.assertTrue(result["ok"])

    def test_lead_not_found(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            result = bb._validate_interaction_subject("BIZ-001", "LED-999", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_NOT_FOUND")

    def test_lead_business_mismatch(self):
        with patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-999"}):
            result = bb._validate_interaction_subject("BIZ-001", "LED-001", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_RELATION_MISMATCH")

    def test_client_only_valid(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True):
            result = bb._validate_interaction_subject("BIZ-001", "", "PRS-001")
        self.assertTrue(result["ok"])

    def test_client_not_found(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb._validate_interaction_subject("BIZ-001", "", "PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_client_not_a_client(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=False):
            result = bb._validate_interaction_subject("BIZ-001", "", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CLIENT_NOT_FOUND")

    def test_client_business_mismatch(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=False):
            result = bb._validate_interaction_subject("BIZ-001", "", "PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_RELATION_MISMATCH")

    def test_no_mutation_calls(self):
        """Read-only subject validation — no manager function beyond
        find_*/is_*/has_* read helpers is ever called."""
        with patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}) as mock_find:
            bb._validate_interaction_subject("BIZ-001", "LED-001", "")
            mock_find.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Optional relations
# ─────────────────────────────────────────────────────────────

class TestValidateInteractionRelations(unittest.TestCase):
    def test_no_optional_relations_ok(self):
        result = bb._validate_interaction_relations("BIZ-001")
        self.assertTrue(result["ok"])

    def test_offer_not_found(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=None):
            result = bb._validate_interaction_relations("BIZ-001", commercial_offer_id="OFR-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_NOT_FOUND")

    def test_offer_business_mismatch(self):
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value={"Business ID": "BIZ-999"}):
            result = bb._validate_interaction_relations("BIZ-001", commercial_offer_id="OFR-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_RELATION_MISMATCH")

    def test_channel_not_found(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[]):
            result = bb._validate_interaction_relations("BIZ-001", channel_id="CH-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHANNEL_NOT_FOUND")

    def test_channel_business_mismatch(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "CH-001", "Бизнес ID": "BIZ-999"}]):
            result = bb._validate_interaction_relations("BIZ-001", channel_id="CH-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_RELATION_MISMATCH")

    def test_assigned_person_not_found(self):
        with patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb._validate_interaction_relations("BIZ-001", assigned_person_id="PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_assigned_person_ok(self):
        with patch("business_core.person_manager.find_person_by_id", return_value={"ID": "PRS-002"}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.has_person_business_link", return_value=True):
            result = bb._validate_interaction_relations("BIZ-001", assigned_person_id="PRS-002")
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Creation
# ─────────────────────────────────────────────────────────────

class TestCreateInteraction(unittest.TestCase):
    def test_requires_business_id(self):
        result = bb.create_interaction("", "call", "2026-07-20T10:00:00Z", "Summary", created_by="admin", caller_idempotency_key="k")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_requires_created_by(self):
        result = bb.create_interaction("BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary", created_by="", caller_idempotency_key="k")
        self.assertFalse(result["ok"])

    def test_requires_idempotency_key(self):
        result = bb.create_interaction("BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary", created_by="admin", caller_idempotency_key="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_IDEMPOTENCY_REQUIRED")

    def test_invalid_type_blocks_before_business_check(self):
        result = bb.create_interaction("BIZ-001", "", "2026-07-20T10:00:00Z", "Summary", created_by="admin", caller_idempotency_key="k")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_TYPE_REQUIRED")

    def test_successful_creation_with_lead(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}), \
             patch("business_core.interaction_manager.create_interaction", return_value={"ok": True, "interaction_id": "ACT-001", "code": "INTERACTION_CREATED", "error": None}), \
             patch("business_core.interaction_manager.find_interaction_by_id", return_value={"Interaction ID": "ACT-001", "Status": "active"}):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Discussed pricing",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_CREATED")
        self.assertEqual(result["interaction_id"], "ACT-001")
        self.assertTrue(result["created"])
        self.assertEqual(result["final_status"], "active")

    def test_successful_creation_with_client(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[]), \
             patch("business_core.person_manager.find_person_by_id", return_value=_ACTIVE_CLIENT), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.interaction_manager.create_interaction", return_value={"ok": True, "interaction_id": "ACT-002", "code": "INTERACTION_CREATED", "error": None}), \
             patch("business_core.interaction_manager.find_interaction_by_id", return_value={"Interaction ID": "ACT-002", "Status": "active"}):
            result = bb.create_interaction(
                "BIZ-001", "email", "2026-07-20T10:00:00Z", "Sent proposal",
                created_by="admin", caller_idempotency_key="k2", direction="outbound", client_id="PRS-001",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["interaction_id"], "ACT-002")

    def test_subject_conflict_blocks(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k", direction="outbound",
                lead_id="LED-001", client_id="PRS-001",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUBJECT_CONFLICT")

    def test_no_subject_blocks(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k", direction="outbound",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_SUBJECT_REQUIRED")

    def test_idempotency_reuse(self):
        existing = {
            "Interaction ID": "ACT-001", "Lead ID": "LED-001", "Client ID": "", "Commercial Offer ID": "",
            "Channel ID": "", "Assigned Person ID": "", "Interaction Type": "call", "Direction": "outbound",
            "Occurred At": "2026-07-20T10:00:00+00:00", "Status": "active",
        }
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[existing]), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_REUSED")
        self.assertTrue(result["reused"])
        self.assertEqual(result["interaction_id"], "ACT-001")

    def test_multiple_idempotency_matches_block(self):
        matches = [{"Interaction ID": "ACT-001"}, {"Interaction ID": "ACT-002"}]
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=matches), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_INTERACTION_MATCHES")
        self.assertEqual(set(result["conflicting_ids"]), {"ACT-001", "ACT-002"})
        self.assertTrue(result["retry_safe"])

    def test_persistence_failure(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}), \
             patch("business_core.interaction_manager.create_interaction", return_value={"ok": False, "interaction_id": "", "code": "", "error": "boom"}):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_PERSISTENCE_FAILED")
        self.assertTrue(result["retry_safe"])

    def test_post_write_verification_failure(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}), \
             patch("business_core.interaction_manager.create_interaction", return_value={"ok": True, "interaction_id": "ACT-001", "code": "INTERACTION_CREATED", "error": None}), \
             patch("business_core.interaction_manager.find_interaction_by_id", return_value=None):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Summary",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_result_never_contains_summary_outcome_notes(self):
        with patch("business_core.sheets.read_business_sheet", return_value=[{"ID": "BIZ-001"}]), \
             patch("business_core.interaction_manager.find_interactions_by_idempotency_key", return_value=[]), \
             patch("business_core.lead_manager.find_lead_by_id", return_value={"Lead ID": "LED-001", "Business ID": "BIZ-001"}), \
             patch("business_core.interaction_manager.create_interaction", return_value={"ok": True, "interaction_id": "ACT-001", "code": "INTERACTION_CREATED", "error": None}), \
             patch("business_core.interaction_manager.find_interaction_by_id", return_value={"Interaction ID": "ACT-001", "Status": "active"}):
            result = bb.create_interaction(
                "BIZ-001", "call", "2026-07-20T10:00:00Z", "Sensitive summary text",
                created_by="admin", caller_idempotency_key="k1", direction="outbound", lead_id="LED-001",
                outcome="Sensitive outcome", notes="Sensitive notes",
            )
        self.assertNotIn("summary", result)
        self.assertNotIn("outcome", result)
        self.assertNotIn("notes", result)


# ─────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────

def _interaction(status="active", **overrides):
    base = {"Interaction ID": "ACT-001", "Business ID": "BIZ-001", "Status": status}
    base.update(overrides)
    return base


class TestArchiveInteraction(unittest.TestCase):
    def test_not_found(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=None):
            result = bb.archive_interaction("ACT-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOT_FOUND")

    def test_active_to_archived(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("active")), \
             patch("business_core.interaction_manager.update_interaction_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.archive_interaction("ACT-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_ARCHIVED")
        self.assertTrue(result["archived"])

    def test_no_op_when_already_archived(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("archived")):
            result = bb.archive_interaction("ACT-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_STATUS_UNCHANGED")
        self.assertFalse(result["changed"])

    def test_invalid_status_rejected(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("bogus")), \
             patch("business_core.interaction_manager.update_interaction_status", return_value={"ok": False, "changed": False, "code": "INVALID_INTERACTION_STATUS", "error": "x"}):
            result = bb.archive_interaction("ACT-001")
        self.assertFalse(result["ok"])


class TestUpdateInteractionNotes(unittest.TestCase):
    def test_not_found(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=None):
            result = bb.update_interaction_notes("ACT-999", "hi")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOT_FOUND")

    def test_updated_in_active_status(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("active")), \
             patch("business_core.interaction_manager.update_interaction_admin_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_interaction_notes("ACT-001", "note text")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOTES_UPDATED")

    def test_updated_in_archived_status(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("archived")), \
             patch("business_core.interaction_manager.update_interaction_admin_fields", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.update_interaction_notes("ACT-001", "note text")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOTES_UPDATED")

    def test_no_op_preserves_unchanged_code(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("active")), \
             patch("business_core.interaction_manager.update_interaction_admin_fields", return_value={"ok": True, "changed": False, "code": "", "error": None}):
            result = bb.update_interaction_notes("ACT-001", "same")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOTES_UNCHANGED")

    def test_too_long_notes_rejected_before_write(self):
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=_interaction("active")), \
             patch("business_core.interaction_manager.update_interaction_admin_fields") as mock_write:
            result = bb.update_interaction_notes("ACT-001", "A" * 5001)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_NOTES_TOO_LONG")
        mock_write.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Result contract
# ─────────────────────────────────────────────────────────────

class TestResultContract(unittest.TestCase):
    def test_all_fields_present(self):
        result = bb._interaction_result(ok=True, code="X", error=None)
        for field in (
            "ok", "code", "error", "interaction_id", "business_id", "lead_id", "client_id",
            "commercial_offer_id", "channel_id", "assigned_person_id", "interaction_type",
            "direction", "occurred_at", "previous_status", "requested_status", "final_status",
            "created", "reused", "changed", "archived", "conflicting_ids", "warnings", "retry_safe",
        ):
            self.assertIn(field, result)

    def test_no_summary_outcome_notes_external_reference(self):
        result = bb._interaction_result(ok=True, code="X", error=None)
        for forbidden in ("summary", "outcome", "notes", "external_reference"):
            self.assertNotIn(forbidden, result)


# ─────────────────────────────────────────────────────────────
# Boundaries
# ─────────────────────────────────────────────────────────────

class TestBoundaries(unittest.TestCase):
    def test_no_relationship_capital_reference(self):
        import inspect
        for fn_name in ("create_interaction", "archive_interaction", "update_interaction_notes", "_validate_interaction_subject"):
            source = inspect.getsource(getattr(bb, fn_name))
            self.assertNotIn("relationship_capital", source)
            self.assertNotIn("RelationshipTouch", source)

    def test_no_lead_or_person_mutation_in_creation(self):
        import inspect
        source = inspect.getsource(bb.create_interaction)
        self.assertNotIn("update_lead", source)
        self.assertNotIn("convert_lead", source)
        self.assertNotIn("update_person", source)
        self.assertNotIn("create_person", source)

    def test_no_task_reminder_offer_payment_creation(self):
        import inspect
        for fn_name in ("create_interaction", "archive_interaction"):
            source = inspect.getsource(getattr(bb, fn_name))
            for forbidden in ("create_business_task", "create_payment_obligation", "create_commercial_offer", "accept_commercial_offer"):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
