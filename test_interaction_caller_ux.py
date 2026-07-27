"""
Phase 42D — Interaction / Communication History Caller UX (ADR-025):
tests for the centralized result-code -> Russian message mapping in
business_core/telegram_handlers.py — the message-mapping helpers
(creation, archive, notes) plus status/type/direction labels, subject
rendering, and Summary/Outcome bounded rendering, plus the 5
operational commands' async behavior (parser-validation ordering,
canonical-boundary-only calls, no raw exception/dict exposure, no
External Reference exposure).

Pure presentation-layer tests for the message helpers: every mapping
case feeds a pre-built structured result dict (never a live
orchestration call) and asserts on the rendered Russian string only.
Async command tests mock business_builder/interaction_manager at the
call site. No network, no Google Sheets. Registered in conftest.py's
hard socket-block set before this file's logic was written.
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

_INTERACTION_COMMANDS = (
    "newinteraction_cmd", "interactions_cmd", "interaction_cmd",
    "archiveinteraction_cmd", "updateinteractionnotes_cmd",
)


# ────────────────────────────────────────────────────────────
# Labels / rendering helpers
# ────────────────────────────────────────────────────────────

class TestStatusTypeDirectionLabels(unittest.TestCase):
    def test_all_statuses_labeled(self):
        for status in ("active", "archived"):
            label = th._interaction_status_ru(status)
            self.assertIn(status, label)

    def test_unknown_status_safe(self):
        label = th._interaction_status_ru("some_future_status")
        self.assertIn("some_future_status", label)

    def test_all_types_labeled(self):
        for t in ("call", "message", "email", "meeting", "note", "other"):
            label = th._interaction_type_ru(t)
            self.assertIsInstance(label, str)
            self.assertTrue(label)

    def test_whatsapp_telegram_not_rendered_as_type(self):
        label = th._interaction_type_ru("whatsapp")
        # Falls through to raw value, never a canonical mapped label —
        # WhatsApp/Telegram are Channel values, never Interaction Type.
        self.assertEqual(label, "whatsapp")

    def test_all_directions_labeled(self):
        for d in ("inbound", "outbound", "internal"):
            label = th._interaction_direction_ru(d)
            self.assertIsInstance(label, str)
            self.assertTrue(label)

    def test_blank_direction_safe(self):
        label = th._interaction_direction_ru("")
        self.assertIn("не указано", label)


class TestSubjectRendering(unittest.TestCase):
    def test_lead_only(self):
        text = th._interaction_subject_summary({"Lead ID": "LED-001", "Client ID": ""})
        self.assertIn("LED-001", text)
        self.assertIn("Lead", text)

    def test_client_only(self):
        text = th._interaction_subject_summary({"Lead ID": "", "Client ID": "PRS-001"})
        self.assertIn("PRS-001", text)
        self.assertIn("Client", text)

    def test_both_present_integrity_warning(self):
        text = th._interaction_subject_summary({"Lead ID": "LED-001", "Client ID": "PRS-001"})
        self.assertIn("⚠️", text)
        self.assertIn("LED-001", text)
        self.assertIn("PRS-001", text)

    def test_neither_present_integrity_warning(self):
        text = th._interaction_subject_summary({"Lead ID": "", "Client ID": ""})
        self.assertIn("⚠️", text)

    def test_never_exposes_client_personal_data(self):
        text = th._interaction_subject_summary({"Lead ID": "", "Client ID": "PRS-001", "Contact Name": "Ivan Ivanov"})
        self.assertNotIn("Ivan", text)


class TestTruncation(unittest.TestCase):
    def test_short_text_unchanged(self):
        result = th._truncate_interaction_text("hi", 100)
        self.assertEqual(result, "hi")

    def test_long_text_truncated_with_marker(self):
        result = th._truncate_interaction_text("A" * 200, 50)
        self.assertEqual(len(result), 51)
        self.assertTrue(result.endswith("…"))

    def test_blank_stays_blank(self):
        result = th._truncate_interaction_text("", 100)
        self.assertEqual(result, "")


# ────────────────────────────────────────────────────────────
# Creation message mapping
# ────────────────────────────────────────────────────────────

class TestInteractionCreationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {"ok": True, "code": "INTERACTION_CREATED", "error": None, "interaction_id": "ACT-001", "interaction_type": "call", "direction": "outbound", "occurred_at": "2026-07-20T10:00:00+00:00", "lead_id": "LED-001"}
        msg = th._interaction_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("ACT-001", msg)

    def test_reused_not_created(self):
        result = {"ok": True, "code": "INTERACTION_REUSED", "error": None, "interaction_id": "ACT-002"}
        msg = th._interaction_creation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)

    def test_relation_errors(self):
        for code in ("BUSINESS_NOT_FOUND", "LEAD_NOT_FOUND", "CLIENT_NOT_FOUND", "COMMERCIAL_OFFER_NOT_FOUND", "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND", "INTERACTION_RELATION_MISMATCH"):
            msg = th._interaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_subject_errors(self):
        msg1 = th._interaction_creation_message({"ok": False, "code": "INTERACTION_SUBJECT_REQUIRED", "error": None})
        self.assertIn("❌", msg1)
        msg2 = th._interaction_creation_message({"ok": False, "code": "INTERACTION_SUBJECT_CONFLICT", "error": None})
        self.assertIn("❌", msg2)

    def test_type_direction_errors(self):
        for code in ("INTERACTION_TYPE_REQUIRED", "INVALID_INTERACTION_TYPE", "INTERACTION_DIRECTION_REQUIRED", "INVALID_INTERACTION_DIRECTION"):
            msg = th._interaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_occurred_at_errors(self):
        for code in ("INTERACTION_OCCURRED_AT_REQUIRED", "INVALID_INTERACTION_OCCURRED_AT", "INTERACTION_OCCURRED_AT_IN_FUTURE"):
            msg = th._interaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_content_length_errors(self):
        for code in ("INTERACTION_SUMMARY_REQUIRED", "INTERACTION_SUMMARY_TOO_LONG", "INTERACTION_OUTCOME_TOO_LONG", "INTERACTION_NOTES_TOO_LONG", "INTERACTION_EXTERNAL_REFERENCE_TOO_LONG"):
            msg = th._interaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertIn("❌", msg)

    def test_idempotency_required(self):
        msg = th._interaction_creation_message({"ok": False, "code": "INTERACTION_IDEMPOTENCY_REQUIRED", "error": None})
        self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_INTERACTION_MATCHES", "error": "x", "conflicting_ids": ("ACT-001", "ACT-002")}
        msg = th._interaction_creation_message(result)
        self.assertIn("ACT-001", msg)
        self.assertIn("ACT-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_persistence_and_verification_failure_not_success(self):
        for code in ("INTERACTION_PERSISTENCE_FAILED", "INTERACTION_POST_WRITE_VERIFICATION_FAILED"):
            msg = th._interaction_creation_message({"ok": False, "code": code, "error": "x"})
            self.assertNotIn("✅", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._interaction_creation_message({"ok": False, "code": "SOME_FUTURE_CODE", "error": "internal detail"})
        self.assertIn("❌", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_never_shows_external_reference(self):
        result = {"ok": True, "code": "INTERACTION_CREATED", "error": None, "interaction_id": "ACT-001", "interaction_type": "call", "occurred_at": "2026-07-20T10:00:00Z"}
        msg = th._interaction_creation_message(result)
        self.assertNotIn("external_reference", msg.lower())


class TestInteractionArchiveMessageMapping(unittest.TestCase):
    def test_archived(self):
        result = {"ok": True, "code": "INTERACTION_ARCHIVED", "error": None, "previous_status": "active"}
        msg = th._interaction_archive_message(result, "ACT-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        result = {"ok": True, "code": "INTERACTION_STATUS_UNCHANGED", "error": None, "previous_status": "archived"}
        msg = th._interaction_archive_message(result, "ACT-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._interaction_archive_message({"ok": False, "code": "INTERACTION_NOT_FOUND", "error": None}, "ACT-999")
        self.assertIn("❌", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_INTERACTION_TRANSITION", "error": "x", "previous_status": "archived"}
        msg = th._interaction_archive_message(result, "ACT-001")
        self.assertIn("❌", msg)
        self.assertNotIn("✅", msg)


class TestInteractionNotesMessageMapping(unittest.TestCase):
    def test_updated(self):
        msg = th._interaction_notes_message({"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None}, "ACT-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        msg = th._interaction_notes_message({"ok": True, "code": "INTERACTION_NOTES_UNCHANGED", "error": None}, "ACT-001")
        self.assertIn("ℹ️", msg)

    def test_not_found(self):
        msg = th._interaction_notes_message({"ok": False, "code": "INTERACTION_NOT_FOUND", "error": None}, "ACT-999")
        self.assertIn("❌", msg)

    def test_immutable(self):
        msg = th._interaction_notes_message({"ok": False, "code": "INTERACTION_IMMUTABLE", "error": "x"}, "ACT-001")
        self.assertIn("❌", msg)
        self.assertNotIn("✅", msg)

    def test_never_echoes_notes_content(self):
        result = {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None}
        msg = th._interaction_notes_message(result, "ACT-001")
        self.assertNotIn("client secret note text", msg)


# ────────────────────────────────────────────────────────────
# Async command tests
# ────────────────────────────────────────────────────────────

class TestCommandRegistration(unittest.TestCase):
    def test_all_5_commands_registered_exactly_once(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        names = ("newinteraction", "interactions", "interaction", "archiveinteraction", "updateinteractionnotes")
        for name in names:
            self.assertEqual(src.count(f'CommandHandler("{name}"'), 1, f"/{name} must be registered exactly once")

    def test_milestones_and_lead_commands_unchanged(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        self.assertEqual(src.count('CommandHandler("milestones"'), 1)
        self.assertEqual(src.count('CommandHandler("newlead"'), 1)
        self.assertEqual(src.count('CommandHandler("newoffer"'), 1)

    def test_no_namespace_collision(self):
        import re
        src = _TH_PATH.read_text(encoding="utf-8")
        all_registered = re.findall(r'CommandHandler\("([a-zA-Z0-9_]+)"', src)
        counts: dict[str, int] = {}
        for name in all_registered:
            counts[name] = counts.get(name, 0) + 1
        interaction_names = {"newinteraction", "interactions", "interaction", "archiveinteraction", "updateinteractionnotes"}
        for name in interaction_names:
            self.assertEqual(counts.get(name, 0), 1, f"/{name} must appear exactly once")


class TestParserValidationOrdering(unittest.TestCase):
    def test_newinteraction_missing_fields(self):
        update, context = _cmd("/newinteraction")
        with patch("business_core.business_builder.create_interaction") as mock_create:
            _run(th.newinteraction_cmd(update, context))
        mock_create.assert_not_called()
        self.assertIn("❌", _sent_text(update))

    def test_newinteraction_missing_idempotency_key(self):
        update, context = _cmd('/newinteraction business_id=BIZ-001 interaction_type=call occurred_at=2026-01-01T00:00:00Z summary=hi lead_id=LED-001')
        with patch("business_core.business_builder.create_interaction") as mock_create:
            _run(th.newinteraction_cmd(update, context))
        mock_create.assert_not_called()

    def test_archiveinteraction_missing_id(self):
        update, context = _cmd("/archiveinteraction")
        with patch("business_core.business_builder.archive_interaction") as mock_archive:
            _run(th.archiveinteraction_cmd(update, context))
        mock_archive.assert_not_called()

    def test_updateinteractionnotes_missing_id_or_notes(self):
        update, context = _cmd("/updateinteractionnotes")
        with patch("business_core.business_builder.update_interaction_notes") as mock_notes:
            _run(th.updateinteractionnotes_cmd(update, context))
        mock_notes.assert_not_called()

        update2, context2 = _cmd("/updateinteractionnotes interaction_id=ACT-001")
        with patch("business_core.business_builder.update_interaction_notes") as mock_notes2:
            _run(th.updateinteractionnotes_cmd(update2, context2))
        mock_notes2.assert_not_called()


class TestCanonicalBoundaries(unittest.TestCase):
    def test_newinteraction_calls_business_builder_only(self):
        update, context = _cmd(
            '/newinteraction business_id=BIZ-001 interaction_type=call direction=outbound '
            'occurred_at=2026-01-01T00:00:00Z summary=hi lead_id=LED-001 caller_idempotency_key=K1'
        )
        with patch("business_core.business_builder.create_interaction",
                   return_value={"ok": True, "code": "INTERACTION_CREATED", "error": None, "interaction_id": "ACT-001", "interaction_type": "call"}) as mock_create:
            _run(th.newinteraction_cmd(update, context))
        mock_create.assert_called_once()

    def test_archiveinteraction_calls_business_builder_only(self):
        update, context = _cmd("/archiveinteraction interaction_id=ACT-001")
        with patch("business_core.business_builder.archive_interaction",
                   return_value={"ok": True, "code": "INTERACTION_ARCHIVED", "error": None}) as mock_archive:
            _run(th.archiveinteraction_cmd(update, context))
        mock_archive.assert_called_once()

    def test_updateinteractionnotes_calls_business_builder_only(self):
        update, context = _cmd("/updateinteractionnotes interaction_id=ACT-001 notes=hi")
        with patch("business_core.business_builder.update_interaction_notes",
                   return_value={"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None}) as mock_notes:
            _run(th.updateinteractionnotes_cmd(update, context))
        mock_notes.assert_called_once()

    def test_interactions_reads_list_helper_only(self):
        update, context = _cmd("/interactions status=active")
        with patch("business_core.interaction_manager.list_interactions", return_value=[]) as mock_list, \
             patch("business_core.business_builder.create_interaction") as mock_create:
            _run(th.interactions_cmd(update, context))
        mock_list.assert_called_once()
        mock_create.assert_not_called()

    def test_interaction_reads_exact_helper_only(self):
        update, context = _cmd("/interaction interaction_id=ACT-001")
        interaction = {"Interaction ID": "ACT-001", "Business ID": "BIZ-001", "Lead ID": "LED-001", "Client ID": "", "Interaction Type": "call", "Occurred At": "2026-01-01T00:00:00Z", "Summary": "hi", "Status": "active", "Created At": "2026-01-01"}
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=interaction) as mock_find, \
             patch("business_core.business_builder.create_interaction") as mock_create:
            _run(th.interaction_cmd(update, context))
        mock_find.assert_called_once()
        mock_create.assert_not_called()

    def test_no_caller_side_id_generation(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn('"ACT-"', body)
            self.assertNotIn("generate_next_id(", body)
            self.assertNotIn("generate_next_interaction_id(", body)

    def test_no_lead_client_offer_mutation_calls(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            for forbidden in ("update_lead(", "convert_lead(", "update_person(", "create_person(", "accept_commercial_offer(", "create_commercial_offer("):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate Lead/Person/Offer ({forbidden!r} found)")

    def test_no_relationship_capital_call(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("relationship_capital", body)

    def test_no_closed_domain_mutation_calls(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            for forbidden in (
                "create_business_task(", "transition_task_status(",
                "register_document(", "transition_document_status(",
                "instantiate_checklist(", "transition_checklist_status(",
                "create_payment_obligation(",
                "update_stage_status_in_sheet(", "recalculate_roadmap_progress(",
            ):
                self.assertNotIn(forbidden, body, f"{fn_name} must not mutate a closed domain ({forbidden!r} found)")


class TestReadCommandsReturnSafeEmptyState(unittest.TestCase):
    def test_interactions_empty(self):
        update, context = _cmd("/interactions business_id=BIZ-999")
        with patch("business_core.interaction_manager.list_interactions", return_value=[]):
            _run(th.interactions_cmd(update, context))
        self.assertIn("ℹ️", _sent_text(update))

    def test_interaction_not_found(self):
        update, context = _cmd("/interaction interaction_id=ACT-999")
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=None):
            _run(th.interaction_cmd(update, context))
        self.assertIn("❌", _sent_text(update))

    def test_interactions_excludes_archived_by_default(self):
        update, context = _cmd("/interactions")
        with patch("business_core.interaction_manager.list_interactions", return_value=[]) as mock_list:
            _run(th.interactions_cmd(update, context))
        self.assertFalse(mock_list.call_args.kwargs.get("include_archived", False))


class TestSensitiveFieldsHiddenInReadCommands(unittest.TestCase):
    def test_interaction_detail_hides_notes_external_reference_idempotency_key(self):
        interaction = {
            "Interaction ID": "ACT-001", "Business ID": "BIZ-001", "Lead ID": "LED-001", "Client ID": "",
            "Commercial Offer ID": "", "Channel ID": "", "Assigned Person ID": "",
            "Interaction Type": "call", "Direction": "outbound", "Occurred At": "2026-01-01T00:00:00Z",
            "Summary": "hi", "Outcome": "", "Status": "active",
            "Caller Idempotency Key": "SECRET-KEY", "External Reference": "PROVIDER-MSG-ID-123",
            "Notes": "sensitive internal note", "Created At": "2026-01-01", "Updated At": "", "Archived At": "",
        }
        update, context = _cmd("/interaction interaction_id=ACT-001")
        with patch("business_core.interaction_manager.find_interaction_by_id", return_value=interaction):
            _run(th.interaction_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("SECRET-KEY", text)
        self.assertNotIn("PROVIDER-MSG-ID-123", text)
        self.assertNotIn("sensitive internal note", text)

    def test_interactions_list_hides_full_summary_notes_external_reference(self):
        interactions = [{
            "Interaction ID": "ACT-001", "Status": "active", "Interaction Type": "call",
            "Lead ID": "LED-001", "Client ID": "",
            "Summary": "A" * 500, "Notes": "sensitive internal note",
            "External Reference": "PROVIDER-MSG-ID-123", "Caller Idempotency Key": "SECRET-KEY",
        }]
        update, context = _cmd("/interactions")
        with patch("business_core.interaction_manager.list_interactions", return_value=interactions):
            _run(th.interactions_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("A" * 500, text)
        self.assertNotIn("sensitive internal note", text)
        self.assertNotIn("PROVIDER-MSG-ID-123", text)
        self.assertNotIn("SECRET-KEY", text)


class TestNoRawExceptionOrDictExposure(unittest.TestCase):
    def test_no_raw_exception_interpolation(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("str(e)", body)
            self.assertNotIn("Ошибка: {e}", body)

    def test_unhandled_exception_yields_safe_message(self):
        update, context = _cmd("/archiveinteraction interaction_id=ACT-001")
        with patch("business_core.business_builder.archive_interaction", side_effect=RuntimeError("raw internal secret")):
            _run(th.archiveinteraction_cmd(update, context))
        text = _sent_text(update)
        self.assertNotIn("raw internal secret", text)
        self.assertIn("❌", text)


class TestNoSensitiveInteractionFieldsLogged(unittest.TestCase):
    _DISALLOWED_LOG_TOKENS = ("Summary", "Outcome", "Notes", "External Reference", "Caller Idempotency Key", "update.message.text")

    def test_interaction_handlers_do_not_log_disallowed_fields(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            log_lines = [line for line in body.splitlines() if "log.error(" in line or "log.warning(" in line or "log.info(" in line]
            for line in log_lines:
                for token in self._DISALLOWED_LOG_TOKENS:
                    self.assertNotIn(token, line, f"{fn_name} logs disallowed token {token!r}: {line}")


class TestParseModeUnderscoresRenderCorrectly(unittest.TestCase):
    def test_all_interaction_commands_use_parse_mode_none(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            reply_calls = body.count("_reply(update,")
            parse_none_calls = body.count("parse_mode=None")
            self.assertGreaterEqual(parse_none_calls, reply_calls, f"{fn_name}: not every _reply call passes parse_mode=None")

    def test_newinteraction_usage_underscores_intact(self):
        update, context = _cmd("/newinteraction")
        _run(th.newinteraction_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("business_id", text)
        self.assertIn("interaction_type", text)
        self.assertIn("occurred_at", text)
        self.assertIn("caller_idempotency_key", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_updateinteractionnotes_usage_underscores_intact(self):
        update, context = _cmd("/updateinteractionnotes")
        _run(th.updateinteractionnotes_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("interaction_id", text)
        self.assertEqual(_sent_parse_mode(update), None)

    def test_interaction_detail_underscore_field_intact(self):
        update, context = _cmd("/interaction")
        _run(th.interaction_cmd(update, context))
        text = _sent_text(update)
        self.assertIn("interaction_id", text)


class TestMilestonesCommandUnchanged(unittest.TestCase):
    def test_milestones_still_read_only_roadmap_owned(self):
        src = _TH_PATH.read_text(encoding="utf-8")
        start = src.index("async def milestones_cmd(")
        body = src[start:min(start + 3000, len(src))]
        self.assertIn("get_commercial_milestones_for_roadmap", body)
        self.assertNotIn("interaction_manager", body)


class TestBoundaries(unittest.TestCase):
    def test_no_deal_or_audit_log_functions_in_interaction_commands(self):
        for fn_name in _INTERACTION_COMMANDS:
            body = _function_body(_TH_PATH, fn_name)
            self.assertNotIn("create_deal", body)
            self.assertNotIn("create_audit_event", body)
            self.assertNotIn("RelationshipTouch", body)


if __name__ == "__main__":
    unittest.main()
