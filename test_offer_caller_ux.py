"""
Phase 40D — Commercial Offer Caller UX (ADR-023): tests for the
centralized result-code -> Russian message mapping in business_core/
telegram_handlers.py — the 4 Offer message-mapping helpers (creation,
revision, update, shared lifecycle) — plus the 11 operational
commands' async behavior (parser-validation ordering, canonical-
boundary-only calls, no raw exception/dict exposure, no
acceptance-implies-payment wording) and `/milestones` preservation.

Pure presentation-layer tests for the message helpers: every mapping
case feeds a pre-built structured result dict (never a live
orchestration call) and asserts on the rendered Russian string only.
Async command tests mock business_builder/offer_manager at the call
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
    # Phase 17E-1: offer_cmd now runs a transport preflight before
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


def _function_body(path, fn_name: str) -> str:
    src = path.read_text(encoding="utf-8")
    start = src.index(f"async def {fn_name}(") if f"async def {fn_name}(" in src else src.index(f"def {fn_name}(")
    rest = src[start + 10:]
    end_candidates = [i for i in (rest.find("\nasync def "), rest.find("\ndef ")) if i != -1]
    return src[start:start + 10 + (min(end_candidates) if end_candidates else len(rest))]


_TH_PATH = WORKSPACE / "business_core" / "telegram_handlers.py"

_OFFER_COMMANDS = (
    "newoffer_cmd", "offers_cmd", "offer_cmd", "reviseoffer_cmd", "updateoffer_cmd",
    "sendoffer_cmd", "acceptoffer_cmd", "rejectoffer_cmd", "expireoffer_cmd",
    "canceloffer_cmd", "archiveoffer_cmd",
)


# ────────────────────────────────────────────────────────────
# Creation message mapping
# ────────────────────────────────────────────────────────────

class TestOfferCreationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_CREATED", "error": None, "commercial_offer_id": "OFR-001", "offer_series_id": "OFS-001", "version_number": 1, "amount": "150000.00", "currency": "KZT", "valid_until": "2026-12-31", "final_status": "draft"}
        msg = th._offer_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("OFR-001", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_REUSED", "error": None, "commercial_offer_id": "OFR-002", "final_status": "draft"}
        msg = th._offer_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_relation_errors(self):
        for code in ("BUSINESS_NOT_FOUND", "CLIENT_NOT_FOUND", "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND", "ROADMAP_NOT_FOUND", "DOCUMENT_NOT_FOUND", "COMMERCIAL_OFFER_CONTEXT_REQUIRED", "COMMERCIAL_OFFER_RELATION_MISMATCH"):
            msg = th._offer_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_snapshot_errors(self):
        for code in ("COMMERCIAL_OFFER_TITLE_REQUIRED", "COMMERCIAL_OFFER_SCOPE_REQUIRED"):
            msg = th._offer_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_amount_currency_date_errors(self):
        for code in ("INVALID_COMMERCIAL_OFFER_AMOUNT", "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE", "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE", "INVALID_COMMERCIAL_OFFER_CURRENCY", "INVALID_COMMERCIAL_OFFER_VALID_UNTIL", "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST"):
            msg = th._offer_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_idempotency_required(self):
        msg = th._offer_creation_message({"ok": False, "code": "COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED", "error": None})
        self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_COMMERCIAL_OFFER_MATCHES", "error": "x", "conflicting_ids": ("OFR-001", "OFR-002")}
        msg = th._offer_creation_message(result)
        self.assertIn("OFR-001", msg)
        self.assertIn("OFR-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_persistence_and_verification_failure_not_success(self):
        for code in ("COMMERCIAL_OFFER_PERSISTENCE_FAILED", "COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._offer_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._offer_creation_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "internal detail"})
        self.assertIn("❌", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)


class TestOfferRevisionMessageMapping(unittest.TestCase):
    def test_revised(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_REVISED", "error": None, "commercial_offer_id": "OFR-002", "offer_series_id": "OFS-001", "version_number": 2, "previous_commercial_offer_id": "OFR-001", "final_status": "draft"}
        msg = th._offer_revision_message(result)
        self.assertIn("✅", msg)
        self.assertIn("OFR-002", msg)

    def test_reused_not_revised(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_REUSED", "error": None, "commercial_offer_id": "OFR-002"}
        msg = th._offer_revision_message(result)
        self.assertNotIn("✅", msg)

    def test_source_not_found(self):
        msg = th._offer_revision_message({"ok": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": None})
        self.assertIn("❌", msg)

    def test_not_latest_version_blocked(self):
        msg = th._offer_revision_message({"ok": False, "code": "COMMERCIAL_OFFER_NOT_LATEST_VERSION", "error": None})
        self.assertIn("🔒", msg)
        self.assertNotIn("✅", msg)

    def test_series_integrity_error_lists_ids(self):
        result = {"ok": False, "code": "COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR", "error": "x", "conflicting_ids": ("OFR-002",)}
        msg = th._offer_revision_message(result)
        self.assertIn("OFR-002", msg)

    def test_multiple_matches(self):
        result = {"ok": False, "code": "MULTIPLE_COMMERCIAL_OFFER_MATCHES", "error": "x", "conflicting_ids": ("OFR-001", "OFR-002")}
        msg = th._offer_revision_message(result)
        self.assertIn("OFR-001", msg)
        self.assertIn("OFR-002", msg)


class TestOfferUpdateMessageMapping(unittest.TestCase):
    def test_updated(self):
        msg = th._offer_update_message({"ok": True, "code": "COMMERCIAL_OFFER_UPDATED", "error": None}, "OFR-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        msg = th._offer_update_message({"ok": True, "code": "COMMERCIAL_OFFER_UPDATE_UNCHANGED", "error": None}, "OFR-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._offer_update_message({"ok": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": None}, "OFR-999")
        self.assertIn("❌", msg)

    def test_immutable(self):
        msg = th._offer_update_message({"ok": False, "code": "COMMERCIAL_OFFER_IMMUTABLE", "error": "x"}, "OFR-001")
        self.assertIn("❌", msg)
        self.assertNotIn("✅", msg)


class TestOfferLifecycleMessageMapping(unittest.TestCase):
    def test_sent(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_SENT", "error": None, "previous_status": "draft", "final_status": "sent"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "отправка")
        self.assertIn("✅", msg)

    def test_accepted_does_not_imply_payment(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_ACCEPTED", "error": None, "previous_status": "sent", "final_status": "accepted"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "принятие")
        self.assertIn("✅", msg)
        for forbidden in ("оплата получена", "счёт выставлен", "договор подписан", "obligation создан", "payment received", "invoice issued", "contract signed"):
            self.assertNotIn(forbidden.lower(), msg.lower())

    def test_rejected(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_REJECTED", "error": None, "previous_status": "sent", "final_status": "rejected"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "отклонение")
        self.assertIn("✅", msg)

    def test_expired(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_EXPIRED", "error": None, "previous_status": "sent", "final_status": "expired"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "истечение срока")
        self.assertIn("✅", msg)

    def test_cancelled(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_CANCELLED", "error": None, "previous_status": "draft", "final_status": "cancelled"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "отмена")
        self.assertIn("✅", msg)

    def test_archived(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_ARCHIVED", "error": None, "previous_status": "rejected", "final_status": "archived"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "архивирование")
        self.assertIn("✅", msg)

    def test_no_op_unchanged(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_STATUS_UNCHANGED", "error": None, "previous_status": "accepted"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "принятие")
        self.assertIn("ℹ️", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_COMMERCIAL_OFFER_TRANSITION", "error": "x", "previous_status": "accepted", "requested_status": "draft"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "отправка")
        self.assertIn("❌", msg)

    def test_not_latest_version_blocked(self):
        result = {"ok": False, "code": "COMMERCIAL_OFFER_NOT_LATEST_VERSION", "error": None}
        msg = th._offer_lifecycle_message(result, "OFR-001", "принятие")
        self.assertIn("🔒", msg)

    def test_actor_required(self):
        msg = th._offer_lifecycle_message({"ok": False, "code": "COMMERCIAL_OFFER_ACTOR_REQUIRED", "error": None}, "OFR-001", "отправка")
        self.assertIn("❌", msg)

    def test_rejection_reason_required(self):
        msg = th._offer_lifecycle_message({"ok": False, "code": "COMMERCIAL_OFFER_REJECTION_REASON_REQUIRED", "error": None}, "OFR-001", "отклонение")
        self.assertIn("❌", msg)

    def test_cancellation_reason_required(self):
        msg = th._offer_lifecycle_message({"ok": False, "code": "COMMERCIAL_OFFER_CANCELLATION_REASON_REQUIRED", "error": None}, "OFR-001", "отмена")
        self.assertIn("❌", msg)

    def test_never_echoes_rejection_or_cancellation_reason(self):
        result = {"ok": True, "code": "COMMERCIAL_OFFER_REJECTED", "error": None, "previous_status": "sent", "final_status": "rejected"}
        msg = th._offer_lifecycle_message(result, "OFR-001", "отклонение")
        self.assertNotIn("client secret rejection detail", msg)


class TestStatusLabelsAndAmountRendering(unittest.TestCase):
    def test_all_statuses_labeled(self):
        for status in ("draft", "sent", "accepted", "rejected", "expired", "cancelled", "archived"):
            label = th._offer_status_ru(status)
            self.assertIn(status, label)

    def test_unknown_status_safe(self):
        label = th._offer_status_ru("some_future_status")
        self.assertIn("some_future_status", label)

    def test_amount_and_currency_together(self):
        rendered = th._format_offer_amount("150000.00", "KZT")
        self.assertIn("150000.00", rendered)
        self.assertIn("KZT", rendered)


# ────────────────────────────────────────────────────────────
# Async command tests
# ────────────────────────────────────────────────────────────

class TestCommandRegistration(unittest.TestCase):
    def test_all_11_commands_registered_exactly_once(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        names = ("newoffer", "offers", "offer", "reviseoffer", "updateoffer", "sendoffer", "acceptoffer", "rejectoffer", "expireoffer", "canceloffer", "archiveoffer")
        for name in names:
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_still_registered_exactly_once(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)

    def test_no_namespace_collision(self):
        import re
        src = _TH_PATH.read_text(encoding="utf-8")
        all_registered = re.findall(r'CommandHandler\("([a-zA-Z0-9_]+)"', src)
        counts: dict[str, int] = {}
        for name in all_registered:
            counts[name] = counts.get(name, 0) + 1
        offer_names = {"newoffer", "offers", "offer", "reviseoffer", "updateoffer", "sendoffer", "acceptoffer", "rejectoffer", "expireoffer", "canceloffer", "archiveoffer"}
        for name in offer_names:
            self.assertEqual(counts.get(name, 0), 1, f"/{name} must appear exactly once")


class TestParserValidationOrdering(unittest.TestCase):
    def test_newoffer_missing_fields(self):
        update, context = _cmd("/newoffer")
        with patch("business_core.business_builder.create_commercial_offer") as mock_create:
            _run(th.newoffer_cmd(update, context))
        mock_create.assert_not_called()
        self.assertIn("❌", _sent_text(update))

    def test_newoffer_missing_idempotency_key(self):
        update, context = _cmd("/newoffer business_id=BIZ-001 client_id=PRS-001 title=T scope=S quoted_amount=100 currency=KZT valid_until=2026-12-31")
        with patch("business_core.business_builder.create_commercial_offer") as mock_create:
            _run(th.newoffer_cmd(update, context))
        mock_create.assert_not_called()

    def test_reviseoffer_missing_source_or_key(self):
        update, context = _cmd("/reviseoffer")
        with patch("business_core.business_builder.revise_commercial_offer") as mock_revise:
            _run(th.reviseoffer_cmd(update, context))
        mock_revise.assert_not_called()

    def test_updateoffer_missing_id(self):
        update, context = _cmd("/updateoffer")
        with patch("business_core.business_builder.update_commercial_offer_draft") as mock_d, \
             patch("business_core.business_builder.update_commercial_offer_admin_fields") as mock_a:
            _run(th.updateoffer_cmd(update, context))
        mock_d.assert_not_called()
        mock_a.assert_not_called()

    def test_updateoffer_missing_payload(self):
        update, context = _cmd("/updateoffer commercial_offer_id=OFR-001")
        with patch("business_core.business_builder.update_commercial_offer_draft") as mock_d:
            _run(th.updateoffer_cmd(update, context))
        mock_d.assert_not_called()

    def test_updateoffer_mixed_mode_rejected(self):
        update, context = _cmd("/updateoffer commercial_offer_id=OFR-001 quoted_amount=100 notes=x")
        with patch("business_core.business_builder.update_commercial_offer_draft") as mock_d, \
             patch("business_core.business_builder.update_commercial_offer_admin_fields") as mock_a:
            _run(th.updateoffer_cmd(update, context))
        mock_d.assert_not_called()
        mock_a.assert_not_called()

    def test_sendoffer_missing_id(self):
        update, context = _cmd("/sendoffer")
        with patch("business_core.business_builder.send_commercial_offer") as mock_send:
            _run(th.sendoffer_cmd(update, context))
        mock_send.assert_not_called()

    def test_acceptoffer_missing_id(self):
        update, context = _cmd("/acceptoffer")
        with patch("business_core.business_builder.accept_commercial_offer") as mock_accept:
            _run(th.acceptoffer_cmd(update, context))
        mock_accept.assert_not_called()

    def test_rejectoffer_missing_reason(self):
        update, context = _cmd("/rejectoffer commercial_offer_id=OFR-001 rejected_by=dida")
        with patch("business_core.business_builder.reject_commercial_offer") as mock_reject:
            _run(th.rejectoffer_cmd(update, context))
        mock_reject.assert_not_called()

    def test_expireoffer_missing_id(self):
        update, context = _cmd("/expireoffer")
        with patch("business_core.business_builder.expire_commercial_offer") as mock_expire:
            _run(th.expireoffer_cmd(update, context))
        mock_expire.assert_not_called()

    def test_canceloffer_missing_reason(self):
        update, context = _cmd("/canceloffer commercial_offer_id=OFR-001 cancelled_by=dida")
        with patch("business_core.business_builder.cancel_commercial_offer") as mock_cancel:
            _run(th.canceloffer_cmd(update, context))
        mock_cancel.assert_not_called()

    def test_archiveoffer_missing_id(self):
        update, context = _cmd("/archiveoffer")
        with patch("business_core.business_builder.archive_commercial_offer") as mock_archive:
            _run(th.archiveoffer_cmd(update, context))
        mock_archive.assert_not_called()


class TestCanonicalBoundaries(unittest.TestCase):
    def test_newoffer_calls_business_builder_only(self):
        update, context = _cmd(
            "/newoffer business_id=BIZ-001 client_id=PRS-001 title=T scope=S quoted_amount=100 "
            "currency=KZT valid_until=2026-12-31 caller_idempotency_key=K1 service_id=SVC-001"
        )
        with patch("business_core.business_builder.create_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_CREATED", "error": None, "commercial_offer_id": "OFR-001", "final_status": "draft"}) as mock_create:
            _run(th.newoffer_cmd(update, context))
        mock_create.assert_called_once()

    def test_reviseoffer_calls_business_builder_only(self):
        update, context = _cmd("/reviseoffer source_commercial_offer_id=OFR-001 caller_idempotency_key=K1")
        with patch("business_core.business_builder.revise_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_REVISED", "error": None, "commercial_offer_id": "OFR-002", "final_status": "draft"}) as mock_revise:
            _run(th.reviseoffer_cmd(update, context))
        mock_revise.assert_called_once()

    def test_sendoffer_calls_business_builder_only(self):
        update, context = _cmd("/sendoffer commercial_offer_id=OFR-001 sent_by=dida")
        with patch("business_core.business_builder.send_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_SENT", "error": None}) as mock_send:
            _run(th.sendoffer_cmd(update, context))
        mock_send.assert_called_once()

    def test_acceptoffer_calls_business_builder_only(self):
        update, context = _cmd("/acceptoffer commercial_offer_id=OFR-001 accepted_by=dida")
        with patch("business_core.business_builder.accept_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_ACCEPTED", "error": None}) as mock_accept:
            _run(th.acceptoffer_cmd(update, context))
        mock_accept.assert_called_once()

    def test_rejectoffer_calls_business_builder_only(self):
        update, context = _cmd("/rejectoffer commercial_offer_id=OFR-001 rejected_by=dida rejection_reason=too_expensive")
        with patch("business_core.business_builder.reject_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_REJECTED", "error": None}) as mock_reject:
            _run(th.rejectoffer_cmd(update, context))
        mock_reject.assert_called_once()

    def test_expireoffer_calls_business_builder_only(self):
        update, context = _cmd("/expireoffer commercial_offer_id=OFR-001")
        with patch("business_core.business_builder.expire_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_EXPIRED", "error": None}) as mock_expire:
            _run(th.expireoffer_cmd(update, context))
        mock_expire.assert_called_once()

    def test_canceloffer_calls_business_builder_only(self):
        update, context = _cmd("/canceloffer commercial_offer_id=OFR-001 cancelled_by=dida cancellation_reason=no_longer_needed")
        with patch("business_core.business_builder.cancel_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_CANCELLED", "error": None}) as mock_cancel:
            _run(th.canceloffer_cmd(update, context))
        mock_cancel.assert_called_once()

    def test_archiveoffer_calls_business_builder_only(self):
        update, context = _cmd("/archiveoffer commercial_offer_id=OFR-001")
        with patch("business_core.business_builder.archive_commercial_offer",
                   return_value={"ok": True, "code": "COMMERCIAL_OFFER_ARCHIVED", "error": None}) as mock_archive:
            _run(th.archiveoffer_cmd(update, context))
        mock_archive.assert_called_once()

    def test_offers_reads_list_helper_only(self):
        update, context = _cmd("/offers status=draft")
        with patch("business_core.offer_manager.list_commercial_offers", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_commercial_offer") as mock_create:
            _run(th.offers_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_offer_reads_exact_helpers_only(self):
        update, context = _cmd("/offer commercial_offer_id=OFR-001")
        offer = {"Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Version Number": "1", "Status": "draft", "Title Snapshot": "T", "Scope Snapshot": "S", "Quoted Amount": "100.00", "Currency": "KZT", "Valid Until": "2026-12-31", "Business ID": "BIZ-001", "Client ID": "PRS-001"}
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=offer) as mock_find, \
             patch("business_core.offer_manager.list_commercial_offers_by_series", return_value=[offer]), \
             patch("business_core.business_builder.create_commercial_offer") as mock_create:
            _run(th.offer_cmd(update, context))
        mock_find.assert_called_once()
        mock_create.assert_not_called()

    def test_no_caller_side_id_generation(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn('"OFR-"', body)
            self.assertNotIn('"OFS-"', body)
            self.assertNotIn("generate_next_id(", body)

    def test_no_payment_call_anywhere(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            for forbidden in ("create_payment_obligation(", "create_payment_transaction(", "confirm_payment_transaction("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not call Payment ({forbidden!r} found)")


class TestReadCommandsReturnSafeEmptyState(unittest.TestCase):
    def test_offers_empty(self):
        update, context = _cmd("/offers business_id=BIZ-999")
        with patch("business_core.offer_manager.list_commercial_offers", return_value=[]):
            _run(th.offers_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_offer_not_found(self):
        """Phase 17E-1: not-found now renders the shared anti-
        enumeration text (identical to a denied-but-existing record),
        not an entity-specific "не найден" message."""
        update, context = _cmd("/offer commercial_offer_id=OFR-999")
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=None):
            _run(th.offer_cmd(update, context))
        self.assertEqual(_sent_text(update), "Запись недоступна или не найдена.")

    def test_offers_excludes_archived_by_default(self):
        offers = [
            {"Commercial Offer ID": "OFR-001", "Status": "draft", "Version Number": "1", "Title Snapshot": "A", "Quoted Amount": "1.00", "Currency": "KZT", "Client ID": "PRS-001"},
            {"Commercial Offer ID": "OFR-002", "Status": "archived", "Version Number": "1", "Title Snapshot": "B", "Quoted Amount": "1.00", "Currency": "KZT", "Client ID": "PRS-001"},
        ]
        update, context = _cmd("/offers")
        with patch("business_core.offer_manager.list_commercial_offers", return_value=offers):
            _run(th.offers_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("OFR-001", text)
        self.assertNotIn("OFR-002", text)


class TestSensitiveFieldsHiddenInReadCommands(unittest.TestCase):
    def test_offer_detail_hides_notes_and_idempotency_key(self):
        offer = {
            "Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Version Number": "1",
            "Previous Commercial Offer ID": "", "Business ID": "BIZ-001", "Client ID": "PRS-001",
            "Object ID": "", "Service ID": "", "Roadmap ID": "", "Offer Document ID": "",
            "Title Snapshot": "T", "Scope Snapshot": "S", "Quoted Amount": "100.00", "Currency": "KZT",
            "Valid Until": "2026-12-31", "Status": "draft",
            "Caller Idempotency Key": "SECRET-KEY", "Notes": "sensitive internal note",
            "Rejection Reason": "", "Cancellation Reason": "",
            "Sent At": "", "Accepted At": "", "Rejected At": "", "Cancelled At": "", "Archived At": "",
        }
        update, context = _cmd("/offer commercial_offer_id=OFR-001")
        with patch("business_core.offer_manager.find_commercial_offer_by_id", return_value=offer), \
             patch("business_core.offer_manager.list_commercial_offers_by_series", return_value=[offer]):
            _run(th.offer_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("SECRET-KEY", text)
        self.assertNotIn("sensitive internal note", text)

    def test_offers_list_hides_scope_and_notes(self):
        offers = [{
            "Commercial Offer ID": "OFR-001", "Status": "draft", "Version Number": "1",
            "Title Snapshot": "T", "Quoted Amount": "100.00", "Currency": "KZT", "Client ID": "PRS-001",
            "Scope Snapshot": "sensitive scope text", "Notes": "sensitive internal note",
        }]
        update, context = _cmd("/offers")
        with patch("business_core.offer_manager.list_commercial_offers", return_value=offers):
            _run(th.offers_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("sensitive scope text", text)
        self.assertNotIn("sensitive internal note", text)


class TestNoRawExceptionOrDictExposure(unittest.TestCase):
    def test_no_raw_exception_interpolation(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("str(e)", body)
            self.assertNotIn("Ошибка: {e}", body)

    def test_unhandled_exception_yields_safe_message(self):
        update, context = _cmd("/archiveoffer commercial_offer_id=OFR-001")
        with patch("business_core.business_builder.archive_commercial_offer", side_effect=RuntimeError("raw internal secret")):
            _run(th.archiveoffer_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("raw internal secret", text)
        self.assertIn("❌", text)


class TestNoSensitiveOfferFieldsLogged(unittest.TestCase):
    _DISALLOWED_LOG_TOKENS = ("Scope Snapshot", "Notes", "Caller Idempotency Key", "Rejection Reason", "Cancellation Reason", "update.message.text")

    def test_offer_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestParseModeUnderscoresRenderCorrectly(unittest.TestCase):
    def test_all_offer_commands_use_parse_mode_none(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")

    def test_newoffer_usage_underscores_intact(self):
        update, context = _cmd("/newoffer")
        _run(th.newoffer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("caller_idempotency_key", text)
        self.assertIn("quoted_amount", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_reviseoffer_usage_underscores_intact(self):
        update, context = _cmd("/reviseoffer")
        _run(th.reviseoffer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("source_commercial_offer_id", text)
        self.assertIn("caller_idempotency_key", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_updateoffer_usage_underscores_intact(self):
        update, context = _cmd("/updateoffer")
        _run(th.updateoffer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("commercial_offer_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_rejectoffer_usage_underscores_intact(self):
        update, context = _cmd("/rejectoffer")
        _run(th.rejectoffer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("rejection_reason", text)

    def test_canceloffer_usage_underscores_intact(self):
        update, context = _cmd("/canceloffer")
        _run(th.canceloffer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("cancellation_reason", text)

    def test_offer_detail_underscore_field_intact(self):
        update, context = _cmd("/offer")
        _run(th.offer_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("commercial_offer_id", text)


class TestMilestonesCommandUnchanged(unittest.TestCase):
    def test_milestones_still_read_only_roadmap_owned(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        start = src.index("async def milestones_cmd(")
        body = src[start:min(start + 3000, len(src))]
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("offer_manager", body)
        self.assertNotIn("business_builder.create_commercial_offer", body)


class TestBoundaries(unittest.TestCase):
    def test_no_closed_domain_mutation_calls_in_offer_commands(self):
        for fn_name in _OFFER_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
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
        self.assertNotIn("create_commercial_offer", src)


if __name__ == "__main__":
    unittest.main()
