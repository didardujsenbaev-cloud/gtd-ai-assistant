"""
Phase 38D — Checklist Caller UX (ADR-021 §9-§20): tests for the
centralized result-code -> Russian message mapping in
business_core/telegram_handlers.py — _checklist_instantiation_message()
(instantiate_checklist codes), _checklist_item_transition_message()
(transition_checklist_item_status codes),
_checklist_instance_transition_message() (transition_checklist_status
codes), _checklist_admin_message() (update_checklist_admin_fields
codes) — plus the five operational commands' async behavior and the
three preserved Template commands' error hygiene.

Pure presentation-layer tests for the message helpers: every mapping
case feeds a pre-built structured result dict (never a live
orchestration call) and asserts on the rendered Russian string only.
Async command tests mock business_builder/checklist_manager at the
call site. No network, no Google Sheets. Registered in conftest.py's
hard socket-block set.
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
# _checklist_instantiation_message
# ────────────────────────────────────────────────────────────

class TestChecklistInstantiationMessageMapping(unittest.TestCase):
    def test_created(self):
        result = {
            "ok": True, "code": "CHECKLIST_INSTANCE_CREATED", "error": None,
            "checklist_instance_id": "CLIN-001", "checklist_template_id": "CHK-001",
            "final_status": "draft", "total_items": 3, "required_items": 2,
        }
        msg = th._checklist_instantiation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("CLIN-001", msg)
        self.assertIn("CHK-001", msg)

    def test_reused_not_presented_as_created(self):
        result = {"ok": True, "code": "CHECKLIST_INSTANCE_REUSED", "error": None, "checklist_instance_id": "CLIN-002", "final_status": "draft"}
        msg = th._checklist_instantiation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("♻️", msg)
        self.assertIn("CLIN-002", msg)

    def test_template_not_found(self):
        result = {"ok": False, "code": "CHECKLIST_TEMPLATE_NOT_FOUND", "error": "x"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_template_inactive(self):
        result = {"ok": False, "code": "CHECKLIST_TEMPLATE_INACTIVE", "error": None}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_template_archived(self):
        result = {"ok": False, "code": "CHECKLIST_TEMPLATE_ARCHIVED", "error": None}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_invalid_template_status(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_TEMPLATE_STATUS", "error": None}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_template_items_empty(self):
        result = {"ok": False, "code": "CHECKLIST_TEMPLATE_ITEMS_EMPTY", "error": None}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_classification_conflict(self):
        result = {"ok": False, "code": "CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT", "error": "A"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_business_not_found(self):
        result = {"ok": False, "code": "BUSINESS_NOT_FOUND", "error": "x"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_service_object_roadmap_stage_not_found(self):
        for code in ("SERVICE_NOT_FOUND", "OBJECT_NOT_FOUND", "ROADMAP_NOT_FOUND", "STAGE_NOT_FOUND"):
            result = {"ok": False, "code": code, "error": None}
            msg = th._checklist_instantiation_message(result)
            self.assertIn("❌", msg)

    def test_relation_mismatch(self):
        result = {"ok": False, "code": "CHECKLIST_ENTITY_RELATION_MISMATCH", "error": "x"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)

    def test_multiple_matches_lists_all_ids_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_CHECKLIST_INSTANCE_MATCHES", "error": "x", "conflicting_ids": ("CLIN-001", "CLIN-002")}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("CLIN-001", msg)
        self.assertIn("CLIN-002", msg)
        self.assertIn("не создан", msg.lower())

    def test_partial_persistence_not_shown_as_success(self):
        result = {"ok": False, "code": "CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE", "error": "x", "checklist_instance_id": "CLIN-003"}
        msg = th._checklist_instantiation_message(result)
        self.assertNotIn("✅", msg)
        self.assertIn("CLIN-003", msg)

    def test_post_write_verification_failed(self):
        result = {"ok": False, "code": "CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED", "error": "x"}
        msg = th._checklist_instantiation_message(result)
        self.assertNotIn("✅", msg)

    def test_persistence_failed(self):
        result = {"ok": False, "code": "CHECKLIST_PERSISTENCE_FAILED", "error": "raw internal detail"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)
        self.assertNotIn("raw internal detail", msg)

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "SOME_FUTURE_CODE", "error": "x"}
        msg = th._checklist_instantiation_message(result)
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# _checklist_item_transition_message
# ────────────────────────────────────────────────────────────

class TestChecklistItemTransitionMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "CHECKLIST_ITEM_STATUS_UPDATED", "error": None, "previous_status": "pending", "final_status": "done"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("✅", msg)
        self.assertIn("pending", msg)
        self.assertIn("done", msg)

    def test_unchanged_not_presented_as_changed(self):
        result = {"ok": True, "code": "CHECKLIST_ITEM_STATUS_UNCHANGED", "error": None, "previous_status": "pending"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertNotIn("✅", msg)
        self.assertIn("изменений нет", msg.lower())

    def test_not_found(self):
        result = {"ok": False, "code": "CHECKLIST_INSTANCE_ITEM_NOT_FOUND", "error": None}
        msg = th._checklist_item_transition_message(result, "CLII-404")
        self.assertIn("❌", msg)
        self.assertIn("CLII-404", msg)

    def test_invalid_status(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_ITEM_STATUS", "error": None}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("❌", msg)
        self.assertIn("pending", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_ITEM_STATUS_TRANSITION", "error": None, "previous_status": "done", "requested_status": "pending"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("❌", msg)

    def test_reason_required(self):
        result = {"ok": False, "code": "CHECKLIST_ITEM_REASON_REQUIRED", "error": "Требуется причина"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("❌", msg)

    def test_completion_metadata_required(self):
        result = {"ok": False, "code": "CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED", "error": None}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("❌", msg)

    def test_terminal_reopen_protected(self):
        result = {"ok": False, "code": "CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION", "error": None, "previous_status": "done"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("🔒", msg)
        self.assertIn("reopen", msg.lower())

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "WEIRD_CODE", "error": "x"}
        msg = th._checklist_item_transition_message(result, "CLII-001")
        self.assertIn("❌", msg)
        self.assertIn("WEIRD_CODE", msg)


# ────────────────────────────────────────────────────────────
# _checklist_instance_transition_message
# ────────────────────────────────────────────────────────────

class TestChecklistInstanceTransitionMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "CHECKLIST_STATUS_UPDATED", "error": None, "previous_status": "draft", "final_status": "in_progress"}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        result = {"ok": True, "code": "CHECKLIST_STATUS_UNCHANGED", "error": None, "previous_status": "draft"}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertNotIn("✅", msg)

    def test_not_found(self):
        result = {"ok": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": None}
        msg = th._checklist_instance_transition_message(result, "CLIN-404")
        self.assertIn("❌", msg)
        self.assertIn("CLIN-404", msg)

    def test_invalid_status(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_STATUS", "error": None}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("❌", msg)

    def test_invalid_transition(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_STATUS_TRANSITION", "error": None, "previous_status": "completed", "requested_status": "draft"}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("❌", msg)

    def test_completion_requirements_not_met_shows_remaining(self):
        result = {"ok": False, "code": "CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET", "error": None, "required_remaining": 2}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("❌", msg)
        self.assertIn("2", msg)

    def test_restore_protected(self):
        result = {"ok": False, "code": "CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION", "error": None, "previous_status": "completed"}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("🔒", msg)
        self.assertIn("restore", msg.lower())

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "FUTURE_CODE", "error": "x"}
        msg = th._checklist_instance_transition_message(result, "CLIN-001")
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# _checklist_admin_message
# ────────────────────────────────────────────────────────────

class TestChecklistAdminMessageMapping(unittest.TestCase):
    def test_updated(self):
        result = {"ok": True, "code": "CHECKLIST_ADMIN_FIELDS_UPDATED", "error": None}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertIn("✅", msg)

    def test_unchanged(self):
        result = {"ok": True, "code": "CHECKLIST_ADMIN_FIELDS_UNCHANGED", "error": None}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertNotIn("✅", msg)

    def test_not_found(self):
        result = {"ok": False, "code": "CHECKLIST_INSTANCE_NOT_FOUND", "error": None}
        msg = th._checklist_admin_message(result, "CLIN-404")
        self.assertIn("❌", msg)

    def test_invalid_admin_field(self):
        result = {"ok": False, "code": "INVALID_CHECKLIST_ADMIN_FIELD", "error": "x"}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertIn("❌", msg)

    def test_immutable_field_conflict(self):
        result = {"ok": False, "code": "CHECKLIST_IMMUTABLE_FIELD_CONFLICT", "error": "x"}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertIn("❌", msg)

    def test_relation_update_blocked(self):
        result = {"ok": False, "code": "CHECKLIST_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION", "error": None}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertIn("❌", msg)
        self.assertIn("/updatechecklist", msg)

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "WEIRD", "error": "x"}
        msg = th._checklist_admin_message(result, "CLIN-001")
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# Status labels
# ────────────────────────────────────────────────────────────

class TestChecklistStatusLabels(unittest.TestCase):
    def test_known_instance_status(self):
        label = th._checklist_status_ru("in_progress")
        self.assertIn("(in_progress)", label)
        self.assertNotEqual(label, "in_progress")

    def test_unknown_instance_status_falls_back(self):
        self.assertIn("mystery", th._checklist_status_ru("mystery"))

    def test_known_item_status(self):
        label = th._checklist_item_status_ru("done")
        self.assertIn("(done)", label)


# ────────────────────────────────────────────────────────────
# /startchecklist
# ────────────────────────────────────────────────────────────

class TestStartChecklistCmd(unittest.TestCase):
    def test_missing_business_id(self):
        update, context = _cmd("/startchecklist checklist_template_id=CHK-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.startchecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("business_id", msg)

    def test_missing_template_id(self):
        update, context = _cmd("/startchecklist business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.startchecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("checklist_template_id", msg)

    def test_calls_instantiate_checklist_only(self):
        update, context = _cmd("/startchecklist business_id=BIZ-001 checklist_template_id=CHK-001 roadmap_id=RM-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.instantiate_checklist", return_value={"ok": True, "code": "CHECKLIST_INSTANCE_CREATED", "error": None, "checklist_instance_id": "CLIN-001", "final_status": "draft"}) as mock_fn:
            asyncio.run(th.startchecklist_cmd(update, context))
        mock_fn.assert_called_once()
        self.assertEqual(mock_fn.call_args[0][0], "BIZ-001")
        self.assertEqual(mock_fn.call_args[0][1], "CHK-001")
        self.assertEqual(mock_fn.call_args[1]["roadmap_id"], "RM-001")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_exception_never_exposes_raw_text(self):
        update, context = _cmd("/startchecklist business_id=BIZ-001 checklist_template_id=CHK-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.instantiate_checklist", side_effect=RuntimeError("secret-detail")):
            asyncio.run(th.startchecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-detail", msg)
        self.assertIn("❌", msg)


# ────────────────────────────────────────────────────────────
# /checklists
# ────────────────────────────────────────────────────────────

class TestChecklistsCmd(unittest.TestCase):
    def test_empty_list(self):
        update, context = _cmd("/checklists business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=[]):
            asyncio.run(th.checklists_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не найдены", msg)

    def test_bounded_list(self):
        instances = [
            {"Checklist Instance ID": f"CLIN-{i:03d}", "Checklist Title Snapshot": "T", "Status": "draft", "Completed Items": "0", "Total Items": "3"}
            for i in range(1, 4)
        ]
        update, context = _cmd("/checklists business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=instances):
            asyncio.run(th.checklists_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("CLIN-001", msg)
        self.assertIn("CLIN-003", msg)

    def test_read_only_no_orchestration_call(self):
        update, context = _cmd("/checklists business_id=BIZ-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=[]), \
             patch("business_core.business_builder.instantiate_checklist") as mock_orch:
            asyncio.run(th.checklists_cmd(update, context))
        mock_orch.assert_not_called()


# ────────────────────────────────────────────────────────────
# /checklist
# ────────────────────────────────────────────────────────────

class TestChecklistDetailCmd(unittest.TestCase):
    def test_missing_id(self):
        update, context = _cmd("/checklist")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.checklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("checklist_instance_id", msg)

    def test_not_found(self):
        update, context = _cmd("/checklist checklist_instance_id=CLIN-404")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=None):
            asyncio.run(th.checklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", msg)

    def test_safe_item_rendering_no_notes_or_reasons(self):
        instance = {
            "Checklist Instance ID": "CLIN-001", "Checklist Template ID": "CHK-001",
            "Checklist Title Snapshot": "Test", "Status": "in_progress", "Business ID": "BIZ-001",
            "Service ID": "", "Object ID": "", "Roadmap ID": "RM-001", "Stage ID": "STAGE-001",
            "Completed Items": "1", "Total Items": "2", "Required Remaining": "1",
        }
        items = [{
            "Checklist Instance Item ID": "CLII-001", "Item Order": "1", "Item Title Snapshot": "Do the thing",
            "Required": "true", "Status": "pending",
            "Notes": "SENSITIVE NOTE", "Blocked Reason": "SENSITIVE REASON", "Skip Reason": "SENSITIVE SKIP",
        }]
        update, context = _cmd("/checklist checklist_instance_id=CLIN-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=instance), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=items):
            asyncio.run(th.checklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("CLII-001", msg)
        self.assertIn("Do the thing", msg)
        self.assertNotIn("SENSITIVE NOTE", msg)
        self.assertNotIn("SENSITIVE REASON", msg)
        self.assertNotIn("SENSITIVE SKIP", msg)

    def test_exact_id_only_no_fuzzy(self):
        body_calls = []
        update, context = _cmd("/checklist checklist_instance_id=CLIN-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=None) as mock_find:
            asyncio.run(th.checklist_cmd(update, context))
        mock_find.assert_called_once_with("CLIN-001")


# ────────────────────────────────────────────────────────────
# /updatecheckitem
# ────────────────────────────────────────────────────────────

class TestUpdateCheckItemCmd(unittest.TestCase):
    def test_missing_item_id_or_status(self):
        update, context = _cmd("/updatecheckitem status=done")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.updatecheckitem_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("checklist_instance_item_id", msg)

    def test_calls_transition_only(self):
        update, context = _cmd("/updatecheckitem checklist_instance_item_id=CLII-001 status=done completed_by=dida")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.transition_checklist_item_status",
                   return_value={"ok": True, "code": "CHECKLIST_ITEM_STATUS_UPDATED", "error": None, "previous_status": "pending", "final_status": "done"}) as mock_fn:
            asyncio.run(th.updatecheckitem_cmd(update, context))
        mock_fn.assert_called_once_with("CLII-001", "done", blocked_reason="", skip_reason="", completed_by="dida")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_exception_never_exposes_raw_text(self):
        update, context = _cmd("/updatecheckitem checklist_instance_item_id=CLII-001 status=done")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.transition_checklist_item_status", side_effect=RuntimeError("secret-detail")):
            asyncio.run(th.updatecheckitem_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-detail", msg)


# ────────────────────────────────────────────────────────────
# /updatechecklist
# ────────────────────────────────────────────────────────────

class TestUpdateChecklistCmd(unittest.TestCase):
    def test_missing_instance_id(self):
        update, context = _cmd("/updatechecklist status=in_progress")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.updatechecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("checklist_instance_id", msg)

    def test_status_and_notes_mutually_exclusive(self):
        update, context = _cmd('/updatechecklist checklist_instance_id=CLIN-001 status=in_progress notes=hi')
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.updatechecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("одновременно", msg.lower())

    def test_neither_status_nor_notes(self):
        update, context = _cmd("/updatechecklist checklist_instance_id=CLIN-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(th.updatechecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("status=", msg)

    def test_status_only_calls_transition_checklist_status(self):
        update, context = _cmd("/updatechecklist checklist_instance_id=CLIN-001 status=in_progress")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.transition_checklist_status",
                   return_value={"ok": True, "code": "CHECKLIST_STATUS_UPDATED", "error": None, "previous_status": "draft", "final_status": "in_progress"}) as mock_fn:
            asyncio.run(th.updatechecklist_cmd(update, context))
        mock_fn.assert_called_once_with("CLIN-001", "in_progress")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_notes_only_calls_update_admin_fields(self):
        update, context = _cmd('/updatechecklist checklist_instance_id=CLIN-001 notes="hello there"')
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.update_checklist_admin_fields",
                   return_value={"ok": True, "code": "CHECKLIST_ADMIN_FIELDS_UPDATED", "error": None}) as mock_fn:
            asyncio.run(th.updatechecklist_cmd(update, context))
        self.assertEqual(mock_fn.call_args[0][0], "CLIN-001")
        self.assertIn("Notes", mock_fn.call_args[0][1])
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)


# ────────────────────────────────────────────────────────────
# Existing Template commands — error hygiene
# ────────────────────────────────────────────────────────────

class TestTemplateCommandsErrorHygiene(unittest.TestCase):
    def test_newchecklist_no_raw_exception(self):
        update, context = _cmd('/newchecklist title="Test"')
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record", side_effect=RuntimeError("secret-detail")):
            asyncio.run(th.newchecklist_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-detail", msg)

    def test_linkknowledge_no_raw_exception(self):
        update, context = _cmd("/linkknowledge template_stage_id=TSTG-001 checklist_ids=CHK-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.knowledge_manager.link_knowledge_to_template_stage", side_effect=RuntimeError("secret-detail")):
            asyncio.run(th.linkknowledge_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-detail", msg)

    def test_stageknowledge_no_raw_exception(self):
        update, context = _cmd("/stageknowledge template_stage_id=TSTG-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.knowledge_manager.find_knowledge_by_template_stage", side_effect=RuntimeError("secret-detail")):
            asyncio.run(th.stageknowledge_cmd(update, context))
        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("secret-detail", msg)


if __name__ == "__main__":
    unittest.main()
