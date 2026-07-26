"""
Phase 36D — Task Caller UX (ADR-019 §4/§14-16): tests for the
centralized result-code -> Russian message mapping in
business_core/telegram_handlers.py — _task_creation_message(),
_task_admin_message(), _task_transition_message(),
_task_assignment_message(), and status-translation helpers.

Pure presentation-layer tests: every case feeds a pre-built structured
result dict (never a live orchestration call) and asserts on the
rendered Russian string only — no network, no Google Sheets.
Registered in conftest.py's hard socket-block set.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.telegram_handlers as th


class TestStatusTranslation(unittest.TestCase):

    def test_all_task_statuses_translated(self):
        for status in ("new", "ready", "in_progress", "waiting", "blocked", "done", "cancelled", "skipped"):
            label = th._task_status_ru(status)
            self.assertIn(status, label)
            self.assertIn(th._TASK_STATUS_RU[status], label)

    def test_assignment_status_translation_exists(self):
        self.assertEqual(th._TASK_ASSIGNMENT_STATUS_RU["active"], "Активно")
        self.assertEqual(th._TASK_ASSIGNMENT_STATUS_RU["ended"], "Завершено")

    def test_no_new_assignment_status_invented(self):
        self.assertEqual(set(th._TASK_ASSIGNMENT_STATUS_RU.keys()), {"active", "ended"})


class TestTaskCreationMessageMapping(unittest.TestCase):

    def test_created(self):
        result = {"ok": True, "code": "TASK_CREATED", "task_id": "TSK-001", "business_id": "BIZ-001", "final_status": "new"}
        msg = th._task_creation_message(result)
        self.assertIn("✅", msg)
        self.assertIn("TSK-001", msg)

    def test_reused_distinct_from_created(self):
        created = th._task_creation_message({"ok": True, "code": "TASK_CREATED", "task_id": "TSK-001", "final_status": "new"})
        reused = th._task_creation_message({"ok": True, "code": "TASK_REUSED", "task_id": "TSK-001", "final_status": "ready"})
        self.assertNotEqual(created, reused)
        self.assertIn("✅", created)
        self.assertNotIn("✅", reused)
        self.assertIn("ℹ️", reused)

    def test_business_not_found(self):
        msg = th._task_creation_message({"ok": False, "code": "BUSINESS_NOT_FOUND", "business_id": "BIZ-999", "error": "x"})
        self.assertIn("❌", msg)
        self.assertIn("BIZ-999", msg)

    def test_relation_mismatch(self):
        msg = th._task_creation_message({"ok": False, "code": "TASK_ENTITY_RELATION_MISMATCH", "error": "detail"})
        self.assertIn("❌", msg)

    def test_roadmap_completed(self):
        msg = th._task_creation_message({"ok": False, "code": "ROADMAP_COMPLETED", "error": "x"})
        self.assertIn("❌", msg)

    def test_roadmap_cancelled(self):
        msg = th._task_creation_message({"ok": False, "code": "ROADMAP_CANCELLED", "error": "x"})
        self.assertIn("❌", msg)

    def test_stage_terminal(self):
        msg = th._task_creation_message({"ok": False, "code": "STAGE_TERMINAL", "error": "x"})
        self.assertIn("❌", msg)

    def test_multiple_idempotency_matches_no_first_pick(self):
        msg = th._task_creation_message({
            "ok": False, "code": "MULTIPLE_TASK_IDEMPOTENCY_MATCHES",
            "conflicting_task_ids": ("TSK-A", "TSK-B", "TSK-C"), "error": "x",
        })
        self.assertIn("⚠️", msg)
        self.assertIn("TSK-A", msg)
        self.assertIn("TSK-B", msg)
        self.assertIn("TSK-C", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._task_creation_message({"ok": False, "code": "TOTALLY_NEW", "error": "detail"})
        self.assertIn("❌", msg)
        self.assertIn("TOTALLY_NEW", msg)


class TestTaskAdminMessageMapping(unittest.TestCase):

    def test_updated(self):
        msg = th._task_admin_message({"ok": True, "code": "TASK_ADMIN_FIELDS_UPDATED"}, "TSK-001")
        self.assertIn("✅", msg)

    def test_unchanged_distinct_from_updated(self):
        updated = th._task_admin_message({"ok": True, "code": "TASK_ADMIN_FIELDS_UPDATED"}, "TSK-001")
        unchanged = th._task_admin_message({"ok": True, "code": "TASK_ADMIN_FIELDS_UNCHANGED"}, "TSK-001")
        self.assertNotEqual(updated, unchanged)
        self.assertIn("ℹ️", unchanged)

    def test_task_not_found(self):
        msg = th._task_admin_message({"ok": False, "code": "TASK_NOT_FOUND"}, "TSK-999")
        self.assertIn("❌", msg)
        self.assertIn("TSK-999", msg)

    def test_immutable_field_conflict(self):
        msg = th._task_admin_message({"ok": False, "code": "TASK_IMMUTABLE_FIELD_CONFLICT", "error": "Business ID"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_relation_update_requires_explicit_action(self):
        msg = th._task_admin_message({"ok": False, "code": "TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("связ", msg.lower())

    def test_invalid_admin_field(self):
        msg = th._task_admin_message({"ok": False, "code": "INVALID_TASK_ADMIN_FIELD", "error": "Status"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._task_admin_message({"ok": False, "code": "NEW_CODE", "error": "x"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("NEW_CODE", msg)


class TestTaskTransitionMessageMapping(unittest.TestCase):

    def test_updated(self):
        msg = th._task_transition_message(
            {"ok": True, "code": "TASK_STATUS_UPDATED", "previous_status": "new", "final_status": "ready"}, "TSK-001")
        self.assertIn("✅", msg)
        self.assertIn("new", msg)
        self.assertIn("ready", msg)

    def test_unchanged_distinct_from_updated(self):
        updated = th._task_transition_message({"ok": True, "code": "TASK_STATUS_UPDATED", "previous_status": "new", "final_status": "ready"}, "TSK-001")
        unchanged = th._task_transition_message({"ok": True, "code": "TASK_STATUS_UNCHANGED", "previous_status": "new"}, "TSK-001")
        self.assertNotEqual(updated, unchanged)
        self.assertIn("ℹ️", unchanged)

    def test_task_not_found(self):
        msg = th._task_transition_message({"ok": False, "code": "TASK_NOT_FOUND"}, "TSK-999")
        self.assertIn("❌", msg)

    def test_invalid_status(self):
        msg = th._task_transition_message({"ok": False, "code": "INVALID_TASK_STATUS", "requested_status": "bogus"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_invalid_transition(self):
        msg = th._task_transition_message(
            {"ok": False, "code": "INVALID_TASK_TRANSITION", "previous_status": "blocked", "requested_status": "new"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_terminal_reopen_message_exists(self):
        msg = th._task_transition_message(
            {"ok": False, "code": "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION", "previous_status": "done"}, "TSK-001")
        self.assertIn("🔒", msg)
        self.assertIn("reopen", msg.lower())
        self.assertIn("done", msg)

    def test_roadmap_on_hold(self):
        msg = th._task_transition_message({"ok": False, "code": "ROADMAP_ON_HOLD"}, "TSK-001")
        self.assertIn("⏸️", msg)

    def test_roadmap_completed(self):
        # Mirrors the Stage-transition precedent (_stage_transition_
        # failure_message's ROADMAP_COMPLETED branch): a completed
        # Roadmap is phrased positively ("✅ уже завершён") even though
        # ok=False — it blocks the transition, not a defect.
        msg = th._task_transition_message({"ok": False, "code": "ROADMAP_COMPLETED"}, "TSK-001")
        self.assertIn("завершён", msg.lower())

    def test_roadmap_cancelled(self):
        msg = th._task_transition_message({"ok": False, "code": "ROADMAP_CANCELLED"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._task_transition_message({"ok": False, "code": "NEW_CODE", "error": "x"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("NEW_CODE", msg)


class TestTaskAssignmentMessageMapping(unittest.TestCase):

    def test_created(self):
        msg = th._task_assignment_message({"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001"}, "TSK-001")
        self.assertIn("✅", msg)
        self.assertIn("TAS-001", msg)

    def test_reused_distinct_from_created(self):
        created = th._task_assignment_message({"ok": True, "code": "TASK_ASSIGNMENT_CREATED", "assignment_id": "TAS-001"}, "TSK-001")
        reused = th._task_assignment_message({"ok": True, "code": "TASK_ASSIGNMENT_REUSED", "assignment_id": "TAS-050"}, "TSK-001")
        self.assertNotEqual(created, reused)
        self.assertNotIn("✅", reused)
        self.assertIn("ℹ️", reused)

    def test_reassigned_distinct_from_reused(self):
        reused = th._task_assignment_message({"ok": True, "code": "TASK_ASSIGNMENT_REUSED", "assignment_id": "TAS-050"}, "TSK-001")
        reassigned = th._task_assignment_message(
            {"ok": True, "code": "TASK_REASSIGNED", "assignment_id": "TAS-020", "previous_assignment_id": "TAS-010"}, "TSK-001")
        self.assertNotEqual(reused, reassigned)
        self.assertIn("✅", reassigned)
        self.assertIn("TAS-010", reassigned)
        self.assertIn("TAS-020", reassigned)

    def test_unassigned(self):
        msg = th._task_assignment_message({"ok": True, "code": "TASK_UNASSIGNED"}, "TSK-001")
        self.assertIn("✅", msg)
        self.assertIn("TSK-001", msg)

    def test_unassign_preserves_history_message_does_not_claim_deletion(self):
        msg = th._task_assignment_message({"ok": True, "code": "TASK_UNASSIGNED"}, "TSK-001")
        for forbidden in ("удал", "стёр", "delete"):
            self.assertNotIn(forbidden, msg.lower())

    def test_task_not_found(self):
        msg = th._task_assignment_message({"ok": False, "code": "TASK_NOT_FOUND"}, "TSK-999")
        self.assertIn("❌", msg)

    def test_role_not_found(self):
        msg = th._task_assignment_message({"ok": False, "code": "ROLE_NOT_FOUND"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_role_paused(self):
        msg = th._task_assignment_message({"ok": False, "code": "ROLE_PAUSED"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("приостановлена", msg.lower())

    def test_role_archived(self):
        msg = th._task_assignment_message({"ok": False, "code": "ROLE_ARCHIVED"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("архивирован", msg.lower())

    def test_role_paused_and_archived_are_distinct(self):
        paused = th._task_assignment_message({"ok": False, "code": "ROLE_PAUSED"}, "TSK-001")
        archived = th._task_assignment_message({"ok": False, "code": "ROLE_ARCHIVED"}, "TSK-001")
        self.assertNotEqual(paused, archived)

    def test_role_not_active_for_task_execution(self):
        msg = th._task_assignment_message({"ok": False, "code": "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_department_not_found(self):
        msg = th._task_assignment_message({"ok": False, "code": "DEPARTMENT_NOT_FOUND"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_department_archived(self):
        msg = th._task_assignment_message({"ok": False, "code": "DEPARTMENT_ARCHIVED"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_person_not_found(self):
        msg = th._task_assignment_message({"ok": False, "code": "PERSON_NOT_FOUND"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_person_archived(self):
        msg = th._task_assignment_message({"ok": False, "code": "PERSON_ARCHIVED"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("архивирован", msg.lower())

    def test_person_not_linked_to_business(self):
        msg = th._task_assignment_message({"ok": False, "code": "PERSON_NOT_LINKED_TO_BUSINESS"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_person_task_business_mismatch(self):
        msg = th._task_assignment_message({"ok": False, "code": "PERSON_TASK_BUSINESS_MISMATCH"}, "TSK-001")
        self.assertIn("❌", msg)

    def test_multiple_active_no_first_pick(self):
        msg = th._task_assignment_message({
            "ok": False, "code": "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR",
            "conflicting_assignment_ids": ("TAS-A", "TAS-B"), "error": "x",
        }, "TSK-001")
        self.assertIn("⚠️", msg)
        self.assertIn("TAS-A", msg)
        self.assertIn("TAS-B", msg)

    def test_unknown_code_safe_fallback(self):
        msg = th._task_assignment_message({"ok": False, "code": "NEW_CODE", "error": "x"}, "TSK-001")
        self.assertIn("❌", msg)
        self.assertIn("NEW_CODE", msg)

    def test_no_raw_dict_ever_rendered(self):
        for code in (
            "TASK_ASSIGNMENT_CREATED", "TASK_ASSIGNMENT_REUSED", "TASK_REASSIGNED", "TASK_UNASSIGNED",
            "TASK_NOT_FOUND", "ROLE_NOT_FOUND", "ROLE_PAUSED", "ROLE_ARCHIVED",
            "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION", "DEPARTMENT_NOT_FOUND", "DEPARTMENT_ARCHIVED",
            "PERSON_NOT_FOUND", "PERSON_ARCHIVED", "PERSON_NOT_LINKED_TO_BUSINESS",
            "PERSON_TASK_BUSINESS_MISMATCH", "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR", "UNKNOWN",
        ):
            result = {
                "ok": code in ("TASK_ASSIGNMENT_CREATED", "TASK_ASSIGNMENT_REUSED", "TASK_REASSIGNED", "TASK_UNASSIGNED"),
                "code": code, "error": "x", "assignment_id": "TAS-1", "previous_assignment_id": "TAS-0",
                "conflicting_assignment_ids": (),
            }
            msg = th._task_assignment_message(result, "TSK-001")
            self.assertIsInstance(msg, str)
            self.assertNotIn("{'ok'", msg)
            self.assertNotIn("Traceback", msg)


if __name__ == "__main__":
    unittest.main()
