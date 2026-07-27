"""
Phase 41D — Lead / Sales Funnel Caller UX (ADR-024): tests for the
centralized result-code -> Russian message mapping in business_core/
telegram_handlers.py — the message-mapping helpers (creation, update,
shared lifecycle, conversion) plus contact-masking/Expected-Value/
follow-up rendering, plus the 10 operational commands' async behavior
(parser-validation ordering, canonical-boundary-only calls, no raw
exception/dict exposure, no conversion-implies-Client-creation wording).

Pure presentation-layer tests for the message helpers: every mapping
case feeds a pre-built structured result dict (never a live
orchestration call) and asserts on the rendered Russian string only.
Async command tests mock business_builder/lead_manager at the call
site. No network, no Google Sheets. Registered in conftest.py's hard
socket-block set before this file's logic was written.
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


def _run(coro):
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
        return asyncio.run(coro)


def _sent_text(update) -> str:
    call = update.message.reply_text.call_args
    return call.args[0] if call.args else call.kwargs.get("text", "")


def _sent_parse_mode(update):
    call = update.message.reply_text.call_args
    return call.kwargs.get("parse_mode", "NOT_SET")


def _function_body(path, fn_name: str) -> str:
    src = path.read_text(encoding="utf-8")
    start = src.index(f"async def {fn_name}(") if f"async def {fn_name}(" in src else src.index(f"def {fn_name}(")
    rest = src[start + 10:]
    end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    return src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]


_TH_PATH = WORKSPACE / "business_core" / "telegram_handlers.py"

_LEAD_COMMANDS = (
    "newlead_cmd", "leads_cmd", "lead_cmd", "updatelead_cmd", "contactlead_cmd",
    "qualifylead_cmd", "unqualifylead_cmd", "loselead_cmd", "convertlead_cmd", "archivelead_cmd",
)


# ────────────────────────────────────────────────────────────
# Contact masking / rendering helpers
# ────────────────────────────────────────────────────────────

class TestContactMasking(unittest.TestCase):
    def test_phone_masks_all_but_last_4(self):
        masked = th._mask_lead_phone_like("+77001234567")
        self.assertTrue(masked.endswith("4567"))
        self.assertNotIn("770012", masked)
        self.assertNotEqual(masked, "+77001234567")

    def test_phone_short_fully_masked(self):
        masked = th._mask_lead_phone_like("123")
        self.assertEqual(masked, "***")

    def test_phone_blank_stays_blank(self):
        self.assertEqual(th._mask_lead_phone_like(""), "")

    def test_email_masks_local_part(self):
        masked = th._mask_lead_email("ivan@example.com")
        self.assertTrue(masked.endswith("@example.com"))
        self.assertNotIn("ivan@example.com", masked)
        self.assertNotEqual(masked, "ivan@example.com")

    def test_email_blank_stays_blank(self):
        self.assertEqual(th._mask_lead_email(""), "")

    def test_contact_summary_never_contains_raw_phone(self):
        lead = {"Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": ""}
        summary = th._mask_lead_contact_summary(lead)
        self.assertNotIn("+77001234567", summary)

    def test_contact_summary_never_contains_raw_email(self):
        lead = {"Phone Snapshot": "", "WhatsApp Snapshot": "", "Email Snapshot": "ivan@example.com"}
        summary = th._mask_lead_contact_summary(lead)
        self.assertNotIn("ivan@example.com", summary)

    def test_contact_summary_empty_is_safe(self):
        lead = {"Phone Snapshot": "", "WhatsApp Snapshot": "", "Email Snapshot": ""}
        summary = th._mask_lead_contact_summary(lead)
        self.assertEqual(summary, "—")

    def test_name_masking_bounded(self):
        masked = th._mask_lead_contact_name("Ivan Ivanov")
        self.assertNotIn("Ivanov", masked)
        self.assertIn("Ivan", masked)


class TestExpectedValueRendering(unittest.TestCase):
    def test_shows_value_and_currency(self):
        rendered = th._format_lead_expected_value("500000.00", "KZT")
        self.assertIn("500000.00", rendered)
        self.assertIn("KZT", rendered)

    def test_labeled_as_estimate(self):
        rendered = th._format_lead_expected_value("500000.00", "KZT")
        self.assertIn("оценка", rendered.lower())

    def test_never_called_agreed_price_or_offer_amount(self):
        rendered = th._format_lead_expected_value("500000.00", "KZT")
        for forbidden in ("согласованная сумма", "offer amount", "payable amount", "к оплате"):
            self.assertNotIn(forbidden.lower(), rendered.lower())

    def test_blank_is_safe(self):
        self.assertEqual(th._format_lead_expected_value("", ""), "—")


class TestFollowUpRendering(unittest.TestCase):
    def test_shows_next_follow_up(self):
        lead = {"Next Follow-up At": "2026-08-01T10:00:00+00:00", "Last Contacted At": "", "Status": "new"}
        lines = th._format_lead_follow_up_lines(lead)
        self.assertTrue(any("2026-08-01T10:00:00+00:00" in line for line in lines))

    def test_shows_due_warning(self):
        from datetime import datetime, timezone
        lead = {"Next Follow-up At": "2020-01-01T00:00:00Z", "Last Contacted At": "", "Status": "new"}
        with patch("business_core.business_builder.is_lead_follow_up_due", return_value=True):
            lines = th._format_lead_follow_up_lines(lead)
        self.assertTrue(any("просрочен" in line for line in lines))

    def test_no_warning_when_not_due(self):
        lead = {"Next Follow-up At": "2030-01-01T00:00:00Z", "Last Contacted At": "", "Status": "new"}
        with patch("business_core.business_builder.is_lead_follow_up_due", return_value=False):
            lines = th._format_lead_follow_up_lines(lead)
        self.assertFalse(any("просрочен" in line for line in lines))


class TestDuplicateWarningRendering(unittest.TestCase):
    def test_no_ids_no_warning(self):
        lines = th._lead_duplicate_warning_lines({"duplicate_contact_ids": ()})
        self.assertEqual(lines, [])

    def test_shows_all_ids(self):
        lines = th._lead_duplicate_warning_lines({"duplicate_contact_ids": ("LED-001", "LED-002")})
        joined = "\n".join(lines)
        self.assertIn("LED-001", joined)
        self.assertIn("LED-002", joined)

    def test_never_implies_reuse_or_merge(self):
        lines = th._lead_duplicate_warning_lines({"duplicate_contact_ids": ("LED-001",)})
        joined = "\n".join(lines).lower()
        self.assertIn("не объединена", joined)


# ────────────────────────────────────────────────────────────
# Creation message mapping
# ────────────────────────────────────────────────────────────

class TestLeadCreationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {"ok": True, "code": "LEAD_CREATED", "error": None, "lead_id": "LED-001", "final_status": "new", "service_id": "", "expected_value": "", "currency": "", "duplicate_contact_ids": ()}
        msg = th._lead_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("LED-001", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "LEAD_REUSED", "error": None, "lead_id": "LED-002", "final_status": "new"}
        msg = th._lead_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_created_shows_duplicate_warning(self):
        result = {"ok": True, "code": "LEAD_CREATED", "error": None, "lead_id": "LED-001", "final_status": "new", "service_id": "", "expected_value": "", "currency": "", "duplicate_contact_ids": ("LED-999",)}
        msg = th._lead_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("LED-999", msg)
        self.assertIn("⚠️", msg)

    def test_relation_errors(self):
        for code in ("BUSINESS_NOT_FOUND", "SERVICE_NOT_FOUND", "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND", "LEAD_RELATION_MISMATCH"):
            msg = th._lead_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_contact_validation_errors(self):
        for code in ("LEAD_CONTACT_NAME_REQUIRED", "LEAD_CONTACT_CHANNEL_REQUIRED", "INVALID_LEAD_PHONE", "INVALID_LEAD_WHATSAPP", "INVALID_LEAD_EMAIL"):
            msg = th._lead_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_expected_value_and_currency_errors(self):
        for code in ("INVALID_LEAD_EXPECTED_VALUE", "INVALID_LEAD_EXPECTED_VALUE_SCALE", "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE", "INVALID_LEAD_CURRENCY"):
            msg = th._lead_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_datetime_error(self):
        msg = th._lead_creation_message({"ok": False, "code": "INVALID_LEAD_DATETIME", "error": "x"})
        self.assertIn("❌", msg)

    def test_idempotency_required(self):
        msg = th._lead_creation_message({"ok": False, "code": "LEAD_IDEMPOTENCY_REQUIRED", "error": None})
        self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_LEAD_MATCHES", "error": "x", "conflicting_ids": ("LED-001", "LED-002")}
        msg = th._lead_creation_message(result)
        self.assertIn("LED-001", msg)
        self.assertIn("LED-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_persistence_and_verification_failure_not_success(self):
        for code in ("LEAD_PERSISTENCE_FAILED", "LEAD_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._lead_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._lead_creation_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "internal detail"})
        self.assertIn("❌", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)


class TestLeadUpdateMessageMapping(unittest.TestCase):
    def test_updated(self):
        msg = th._lead_update_message({"ok": True, "code": "LEAD_UPDATED", "error": None, "duplicate_contact_ids": ()}, "LED-001")
        self.assertIn("✅", msg)

    def test_updated_shows_duplicate_warning(self):
        msg = th._lead_update_message({"ok": True, "code": "LEAD_UPDATED", "error": None, "duplicate_contact_ids": ("LED-999",)}, "LED-001")
        self.assertIn("LED-999", msg)

    def test_unchanged(self):
        msg = th._lead_update_message({"ok": True, "code": "LEAD_UPDATE_UNCHANGED", "error": None}, "LED-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._lead_update_message({"ok": False, "code": "LEAD_NOT_FOUND", "error": None}, "LED-999")
        self.assertIn("❌", msg)

    def test_immutable(self):
        msg = th._lead_update_message({"ok": False, "code": "LEAD_IMMUTABLE", "error": "x"}, "LED-001")
        self.assertIn("❌", msg)
        self.assertNotIn("✅", msg)

    def test_contact_channel_required(self):
        msg = th._lead_update_message({"ok": False, "code": "LEAD_CONTACT_CHANNEL_REQUIRED", "error": None}, "LED-001")
        self.assertIn("❌", msg)


class TestLeadLifecycleMessageMapping(unittest.TestCase):
    def test_contacted(self):
        result = {"ok": True, "code": "LEAD_CONTACTED", "error": None, "previous_status": "new", "final_status": "contacted"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка контакта")
        self.assertIn("✅", msg)

    def test_qualified(self):
        result = {"ok": True, "code": "LEAD_QUALIFIED", "error": None, "previous_status": "contacted", "final_status": "qualified"}
        msg = th._lead_lifecycle_message(result, "LED-001", "квалификация")
        self.assertIn("✅", msg)

    def test_unqualified(self):
        result = {"ok": True, "code": "LEAD_UNQUALIFIED", "error": None, "previous_status": "new", "final_status": "unqualified"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка 'не подходит'")
        self.assertIn("✅", msg)

    def test_lost(self):
        result = {"ok": True, "code": "LEAD_LOST", "error": None, "previous_status": "qualified", "final_status": "lost"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка 'потерян'")
        self.assertIn("✅", msg)

    def test_archived(self):
        result = {"ok": True, "code": "LEAD_ARCHIVED", "error": None, "previous_status": "lost", "final_status": "archived"}
        msg = th._lead_lifecycle_message(result, "LED-001", "архивирование")
        self.assertIn("✅", msg)

    def test_no_op_unchanged(self):
        result = {"ok": True, "code": "LEAD_STATUS_UNCHANGED", "error": None, "previous_status": "contacted"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка контакта")
        self.assertIn("ℹ️", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_LEAD_TRANSITION", "error": "x", "previous_status": "archived", "requested_status": "contacted"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка контакта")
        self.assertIn("❌", msg)

    def test_restore_blocked(self):
        result = {"ok": False, "code": "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION", "error": None, "previous_status": "unqualified"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка контакта")
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_disposition_reason_required(self):
        msg = th._lead_lifecycle_message({"ok": False, "code": "LEAD_DISPOSITION_REASON_REQUIRED", "error": None}, "LED-001", "отметка 'не подходит'")
        self.assertIn("❌", msg)

    def test_never_echoes_disposition_reason(self):
        result = {"ok": True, "code": "LEAD_UNQUALIFIED", "error": None, "previous_status": "new", "final_status": "unqualified"}
        msg = th._lead_lifecycle_message(result, "LED-001", "отметка 'не подходит'")
        self.assertNotIn("client secret disposition detail", msg)


class TestLeadConversionMessageMapping(unittest.TestCase):
    def test_converted_safe_meaning(self):
        result = {"ok": True, "code": "LEAD_CONVERTED", "error": None, "previous_status": "qualified", "converted_client_id": "PRS-001"}
        msg = th._lead_conversion_message(result, "LED-001")
        self.assertIn("✅", msg)
        self.assertIn("PRS-001", msg)
        for forbidden in ("client создан", "person создан", "object создан", "offer создан", "payment создан", "deal won", "person created", "client created"):
            self.assertNotIn(forbidden.lower(), msg.lower())

    def test_same_client_repeat_is_noop(self):
        result = {"ok": True, "code": "LEAD_STATUS_UNCHANGED", "error": None, "converted_client_id": "PRS-001"}
        msg = th._lead_conversion_message(result, "LED-001")
        self.assertIn("ℹ️", msg)
        self.assertNotIn("✅", msg)

    def test_different_client_conflict(self):
        result = {"ok": False, "code": "LEAD_CONVERSION_TARGET_CONFLICT", "error": "x", "converted_client_id": "PRS-001"}
        msg = th._lead_conversion_message(result, "LED-001")
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_client_not_found(self):
        msg = th._lead_conversion_message({"ok": False, "code": "CLIENT_NOT_FOUND", "error": "x"}, "LED-001")
        self.assertIn("❌", msg)

    def test_relation_mismatch(self):
        msg = th._lead_conversion_message({"ok": False, "code": "LEAD_RELATION_MISMATCH", "error": "x"}, "LED-001")
        self.assertIn("❌", msg)

    def test_client_required(self):
        msg = th._lead_conversion_message({"ok": False, "code": "LEAD_CONVERSION_CLIENT_REQUIRED", "error": None}, "LED-001")
        self.assertIn("❌", msg)

    def test_actor_required(self):
        msg = th._lead_conversion_message({"ok": False, "code": "LEAD_CONVERSION_ACTOR_REQUIRED", "error": None}, "LED-001")
        self.assertIn("❌", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_LEAD_TRANSITION", "error": "x", "previous_status": "archived"}
        msg = th._lead_conversion_message(result, "LED-001")
        self.assertIn("❌", msg)


class TestStatusLabels(unittest.TestCase):
    def test_all_statuses_labeled(self):
        for status in ("new", "contacted", "qualified", "unqualified", "converted", "lost", "archived"):
            label = th._lead_status_ru(status)
            self.assertIn(status, label)

    def test_unknown_status_safe(self):
        label = th._lead_status_ru("some_future_status")
        self.assertIn("some_future_status", label)


# ────────────────────────────────────────────────────────────
# Async command tests
# ────────────────────────────────────────────────────────────

class TestCommandRegistration(unittest.TestCase):
    def test_all_10_commands_registered_exactly_once(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        names = ("newlead", "leads", "lead", "updatelead", "contactlead", "qualifylead", "unqualifylead", "loselead", "convertlead", "archivelead")
        for name in names:
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_no_namespace_collision(self):
        import re
        src = _TH_PATH.read_text(encoding="utf-8")
        all_registered = re.findall(r'CommandHandler\("([a-zA-Z0-9_]+)"', src)
        counts: dict[str, int] = {}
        for name in all_registered:
            counts[name] = counts.get(name, 0) + 1
        lead_names = {"newlead", "leads", "lead", "updatelead", "contactlead", "qualifylead", "unqualifylead", "loselead", "convertlead", "archivelead"}
        for name in lead_names:
            self.assertEqual(counts.get(name, 0), 1, f"/{name} must appear exactly once")


class TestParserValidationOrdering(unittest.TestCase):
    def test_newlead_missing_fields(self):
        update, context = _cmd("/newlead")
        with patch("business_core.business_builder.create_lead") as mock_create:
            _run(th.newlead_cmd(update, context))
        mock_create.assert_not_called()
        self.assertIn("❌", _sent_text(update))

    def test_newlead_missing_idempotency_key(self):
        update, context = _cmd('/newlead business_id=BIZ-001 contact_name=Ivan phone=+77001234567')
        with patch("business_core.business_builder.create_lead") as mock_create:
            _run(th.newlead_cmd(update, context))
        mock_create.assert_not_called()

    def test_updatelead_missing_id(self):
        update, context = _cmd("/updatelead")
        with patch("business_core.business_builder.update_lead") as mock_u, \
             patch("business_core.business_builder.update_lead_admin_fields") as mock_a:
            _run(th.updatelead_cmd(update, context))
        mock_u.assert_not_called()
        mock_a.assert_not_called()

    def test_updatelead_missing_payload(self):
        update, context = _cmd("/updatelead lead_id=LED-001")
        with patch("business_core.business_builder.update_lead") as mock_u:
            _run(th.updatelead_cmd(update, context))
        mock_u.assert_not_called()

    def test_updatelead_mixed_mode_rejected(self):
        update, context = _cmd("/updatelead lead_id=LED-001 phone=+77009999999 notes=x")
        with patch("business_core.business_builder.update_lead") as mock_u, \
             patch("business_core.business_builder.update_lead_admin_fields") as mock_a:
            _run(th.updatelead_cmd(update, context))
        mock_u.assert_not_called()
        mock_a.assert_not_called()

    def test_contactlead_missing_id(self):
        update, context = _cmd("/contactlead")
        with patch("business_core.business_builder.contact_lead") as mock_contact:
            _run(th.contactlead_cmd(update, context))
        mock_contact.assert_not_called()

    def test_qualifylead_missing_id(self):
        update, context = _cmd("/qualifylead")
        with patch("business_core.business_builder.qualify_lead") as mock_qualify:
            _run(th.qualifylead_cmd(update, context))
        mock_qualify.assert_not_called()

    def test_unqualifylead_missing_id_or_reason(self):
        update, context = _cmd("/unqualifylead")
        with patch("business_core.business_builder.unqualify_lead") as mock_u:
            _run(th.unqualifylead_cmd(update, context))
        mock_u.assert_not_called()

        update2, context2 = _cmd("/unqualifylead lead_id=LED-001")
        with patch("business_core.business_builder.unqualify_lead") as mock_u2:
            _run(th.unqualifylead_cmd(update2, context2))
        mock_u2.assert_not_called()

    def test_loselead_missing_id_or_reason(self):
        update, context = _cmd("/loselead")
        with patch("business_core.business_builder.lose_lead") as mock_l:
            _run(th.loselead_cmd(update, context))
        mock_l.assert_not_called()

        update2, context2 = _cmd("/loselead lead_id=LED-001")
        with patch("business_core.business_builder.lose_lead") as mock_l2:
            _run(th.loselead_cmd(update2, context2))
        mock_l2.assert_not_called()

    def test_convertlead_missing_id_client_or_actor(self):
        update, context = _cmd("/convertlead")
        with patch("business_core.business_builder.convert_lead") as mock_c:
            _run(th.convertlead_cmd(update, context))
        mock_c.assert_not_called()

    def test_archivelead_missing_id(self):
        update, context = _cmd("/archivelead")
        with patch("business_core.business_builder.archive_lead") as mock_a:
            _run(th.archivelead_cmd(update, context))
        mock_a.assert_not_called()


class TestCanonicalBoundaries(unittest.TestCase):
    def test_newlead_calls_business_builder_only(self):
        update, context = _cmd(
            '/newlead business_id=BIZ-001 contact_name=Ivan phone=+77001234567 caller_idempotency_key=K1'
        )
        with patch("business_core.business_builder.create_lead",
                   return_value={"ok": True, "code": "LEAD_CREATED", "error": None, "lead_id": "LED-001", "final_status": "new", "duplicate_contact_ids": ()}) as mock_create:
            _run(th.newlead_cmd(update, context))
        mock_create.assert_called_once()

    def test_updatelead_calls_business_builder_only(self):
        update, context = _cmd("/updatelead lead_id=LED-001 phone=+77009999999")
        with patch("business_core.business_builder.update_lead",
                   return_value={"ok": True, "code": "LEAD_UPDATED", "error": None, "duplicate_contact_ids": ()}) as mock_update:
            _run(th.updatelead_cmd(update, context))
        mock_update.assert_called_once()

    def test_updatelead_notes_only_calls_admin_fields(self):
        update, context = _cmd("/updatelead lead_id=LED-001 notes=hi")
        with patch("business_core.business_builder.update_lead_admin_fields",
                   return_value={"ok": True, "code": "LEAD_UPDATED", "error": None}) as mock_admin:
            _run(th.updatelead_cmd(update, context))
        mock_admin.assert_called_once()

    def test_contactlead_calls_business_builder_only(self):
        update, context = _cmd("/contactlead lead_id=LED-001")
        with patch("business_core.business_builder.contact_lead",
                   return_value={"ok": True, "code": "LEAD_CONTACTED", "error": None}) as mock_contact:
            _run(th.contactlead_cmd(update, context))
        mock_contact.assert_called_once()

    def test_qualifylead_calls_business_builder_only(self):
        update, context = _cmd("/qualifylead lead_id=LED-001")
        with patch("business_core.business_builder.qualify_lead",
                   return_value={"ok": True, "code": "LEAD_QUALIFIED", "error": None}) as mock_qualify:
            _run(th.qualifylead_cmd(update, context))
        mock_qualify.assert_called_once()

    def test_unqualifylead_calls_business_builder_only(self):
        update, context = _cmd("/unqualifylead lead_id=LED-001 disposition_reason=not_fit")
        with patch("business_core.business_builder.unqualify_lead",
                   return_value={"ok": True, "code": "LEAD_UNQUALIFIED", "error": None}) as mock_u:
            _run(th.unqualifylead_cmd(update, context))
        mock_u.assert_called_once()

    def test_loselead_calls_business_builder_only(self):
        update, context = _cmd("/loselead lead_id=LED-001 disposition_reason=chose_competitor")
        with patch("business_core.business_builder.lose_lead",
                   return_value={"ok": True, "code": "LEAD_LOST", "error": None}) as mock_l:
            _run(th.loselead_cmd(update, context))
        mock_l.assert_called_once()

    def test_convertlead_calls_business_builder_only(self):
        update, context = _cmd("/convertlead lead_id=LED-001 converted_client_id=PRS-001")
        with patch("business_core.business_builder.convert_lead",
                   return_value={"ok": True, "code": "LEAD_CONVERTED", "error": None, "converted_client_id": "PRS-001"}) as mock_c:
            _run(th.convertlead_cmd(update, context))
        mock_c.assert_called_once()

    def test_archivelead_calls_business_builder_only(self):
        update, context = _cmd("/archivelead lead_id=LED-001")
        with patch("business_core.business_builder.archive_lead",
                   return_value={"ok": True, "code": "LEAD_ARCHIVED", "error": None}) as mock_a:
            _run(th.archivelead_cmd(update, context))
        mock_a.assert_called_once()

    def test_leads_reads_list_helper_only(self):
        update, context = _cmd("/leads status=new")
        with patch("business_core.lead_manager.list_leads", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_lead") as mock_create:
            _run(th.leads_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_lead_reads_exact_helper_only(self):
        update, context = _cmd("/lead lead_id=LED-001")
        lead = {"Lead ID": "LED-001", "Business ID": "BIZ-001", "Status": "new", "Contact Name Snapshot": "Ivan", "Phone Snapshot": "+77001234567", "WhatsApp Snapshot": "", "Email Snapshot": "", "Created At": "2026-01-01"}
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead) as mock_find, \
             patch("business_core.business_builder.create_lead") as mock_create:
            _run(th.lead_cmd(update, context))
        mock_find.assert_called_once()
        mock_create.assert_not_called()

    def test_no_caller_side_id_generation(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn('"LED-"', body)
            self.assertNotIn("generate_next_id(", body)
            self.assertNotIn("generate_next_lead_id(", body)

    def test_no_person_client_mutation_calls(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            for forbidden in ("create_person(", "update_person(", "update_person_drive_info("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Person/Client ({forbidden!r} found)")

    def test_no_relationship_capital_call(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("relationship_capital", body)

    def test_no_closed_domain_mutation_calls(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            for forbidden in (
                "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "create_commercial_offer(", "create_payment_obligation(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate a closed domain ({forbidden!r} found)")


class TestReadCommandsReturnSafeEmptyState(unittest.TestCase):
    def test_leads_empty(self):
        update, context = _cmd("/leads business_id=BIZ-999")
        with patch("business_core.lead_manager.list_leads", return_value=[]):
            _run(th.leads_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_lead_not_found(self):
        update, context = _cmd("/lead lead_id=LED-999")
        with patch("business_core.lead_manager.find_lead_by_id", return_value=None):
            _run(th.lead_cmd(update, context))
        self.assertIn("❌", _sent_text(update))

    def test_leads_excludes_archived_by_default(self):
        leads = [
            {"Lead ID": "LED-001", "Status": "new", "Phone Snapshot": "", "WhatsApp Snapshot": "", "Email Snapshot": ""},
        ]
        update, context = _cmd("/leads")
        with patch("business_core.lead_manager.list_leads", return_value=leads) as mock_list:
            _run(th.leads_cmd(update, context))
        # list_leads itself excludes archived by default (Foundation-level);
        # caller must not override include_archived=True unless requested.
        self.assertFalse(mock_list.call_args.kwargs.get("include_archived", False))


class TestSensitiveFieldsHiddenInReadCommands(unittest.TestCase):
    def test_lead_detail_hides_raw_contact_and_sensitive_fields(self):
        lead = {
            "Lead ID": "LED-001", "Business ID": "BIZ-001", "Status": "new",
            "Contact Name Snapshot": "Ivan Ivanov", "Phone Snapshot": "+77001234567",
            "WhatsApp Snapshot": "", "Email Snapshot": "ivan@example.com", "Company Snapshot": "Acme",
            "Service ID": "", "Source": "", "Channel ID": "", "Assigned Person ID": "",
            "Expected Value": "", "Currency": "", "Next Follow-up At": "", "Last Contacted At": "",
            "Converted Client ID": "", "Converted At": "",
            "Qualification Notes": "sensitive qual note", "Disposition Reason": "sensitive disposition",
            "Notes": "sensitive internal note", "Caller Idempotency Key": "SECRET-KEY",
            "Created At": "2026-01-01", "Updated At": "",
        }
        update, context = _cmd("/lead lead_id=LED-001")
        with patch("business_core.lead_manager.find_lead_by_id", return_value=lead):
            _run(th.lead_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("+77001234567", text)
        self.assertNotIn("ivan@example.com", text)
        self.assertNotIn("Acme", text)
        self.assertNotIn("sensitive qual note", text)
        self.assertNotIn("sensitive disposition", text)
        self.assertNotIn("sensitive internal note", text)
        self.assertNotIn("SECRET-KEY", text)
        self.assertNotIn("Ivanov", text)

    def test_leads_list_hides_raw_contact_and_notes(self):
        leads = [{
            "Lead ID": "LED-001", "Status": "new", "Phone Snapshot": "+77001234567",
            "WhatsApp Snapshot": "", "Email Snapshot": "ivan@example.com",
            "Contact Name Snapshot": "Ivan Ivanov", "Company Snapshot": "Acme",
            "Notes": "sensitive internal note", "Qualification Notes": "sensitive qual note",
            "Disposition Reason": "sensitive disposition", "Caller Idempotency Key": "SECRET-KEY",
        }]
        update, context = _cmd("/leads")
        with patch("business_core.lead_manager.list_leads", return_value=leads):
            _run(th.leads_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("+77001234567", text)
        self.assertNotIn("ivan@example.com", text)
        self.assertNotIn("Ivan Ivanov", text)
        self.assertNotIn("Acme", text)
        self.assertNotIn("sensitive internal note", text)
        self.assertNotIn("sensitive qual note", text)
        self.assertNotIn("sensitive disposition", text)
        self.assertNotIn("SECRET-KEY", text)


class TestNoRawExceptionOrDictExposure(unittest.TestCase):
    def test_no_raw_exception_interpolation(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("str(e)", body)
            self.assertNotIn("Ошибка: {e}", body)

    def test_unhandled_exception_yields_safe_message(self):
        update, context = _cmd("/archivelead lead_id=LED-001")
        with patch("business_core.business_builder.archive_lead", side_effect=RuntimeError("raw internal secret")):
            _run(th.archivelead_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("raw internal secret", text)
        self.assertIn("❌", text)


class TestNoSensitiveLeadFieldsLogged(unittest.TestCase):
    _DISALLOWED_LOG_TOKENS = (
        "Contact Name Snapshot", "Phone Snapshot", "WhatsApp Snapshot", "Email Snapshot",
        "Company Snapshot", "Qualification Notes", "Disposition Reason", "Notes",
        "Caller Idempotency Key", "update.message.text",
    )

    def test_lead_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestParseModeUnderscoresRenderCorrectly(unittest.TestCase):
    def test_all_lead_commands_use_parse_mode_none(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")

    def test_newlead_usage_underscores_intact(self):
        update, context = _cmd("/newlead")
        _run(th.newlead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("business_id", text)
        self.assertIn("contact_name", text)
        self.assertIn("caller_idempotency_key", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_updatelead_usage_underscores_intact(self):
        update, context = _cmd("/updatelead")
        _run(th.updatelead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("lead_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_unqualifylead_usage_underscores_intact(self):
        update, context = _cmd("/unqualifylead")
        _run(th.unqualifylead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("disposition_reason", text)

    def test_loselead_usage_underscores_intact(self):
        update, context = _cmd("/loselead")
        _run(th.loselead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("disposition_reason", text)

    def test_convertlead_usage_underscores_intact(self):
        update, context = _cmd("/convertlead")
        _run(th.convertlead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("converted_client_id", text)

    def test_lead_detail_underscore_field_intact(self):
        update, context = _cmd("/lead")
        _run(th.lead_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("lead_id", text)


class TestBoundaries(unittest.TestCase):
    def test_no_deal_or_interaction_functions_in_lead_commands(self):
        for fn_name in _LEAD_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("create_deal", body)
            self.assertNotIn("create_interaction", body)


if __name__ == "__main__":
    unittest.main()
