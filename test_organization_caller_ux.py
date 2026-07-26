"""
Phase 35E — Organization Caller UX (ADR-018 §17-§20): tests for the
centralized result-code -> Russian message mapping in
business_core/telegram_handlers.py —
_organization_assignment_message() (Person<->Role assignment codes) and
_stage_role_message() (Stage->Role codes) — plus /stageresponsibility's
canonical-state display.

Pure presentation-layer tests: every case feeds a pre-built structured
result dict (never a live manager call) and asserts on the rendered
Russian string only — no network, no Google Sheets. Registered in
conftest.py's hard socket-block set.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.telegram_handlers as th


class TestAssignmentMessageMapping(unittest.TestCase):
    """/assignrole — business_builder.assign_person_to_role_canonical()
    result codes."""

    def test_assignment_created(self):
        result = {"ok": True, "code": "ASSIGNMENT_CREATED", "assignment_id": "PRA-100", "error": None}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("✅", msg)
        self.assertIn("PRS-001", msg)
        self.assertIn("ROLE-001", msg)
        self.assertIn("PRA-100", msg)

    def test_assignment_reused_is_distinct_from_created(self):
        result = {"ok": True, "code": "ASSIGNMENT_REUSED", "assignment_id": "PRA-050", "error": None}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertNotIn("✅", msg)
        self.assertIn("ℹ️", msg)
        self.assertIn("уже", msg.lower())
        self.assertIn("PRA-050", msg)
        self.assertIn("не создан", msg.lower())

    def test_person_not_found(self):
        result = {"ok": False, "code": "PERSON_NOT_FOUND", "error": "Person 'PRS-999' не найден"}
        msg = th._organization_assignment_message(result, "PRS-999", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("PRS-999", msg)

    def test_person_archived_shows_person_id_only(self):
        result = {"ok": False, "code": "PERSON_ARCHIVED", "error": "archived"}
        msg = th._organization_assignment_message(result, "PRS-002", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("PRS-002", msg)
        self.assertIn("архивирован", msg.lower())

    def test_role_not_found(self):
        result = {"ok": False, "code": "ROLE_NOT_FOUND", "error": "not found"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-999")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-999", msg)

    def test_role_paused(self):
        result = {"ok": False, "code": "ROLE_PAUSED", "error": "paused"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-002")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-002", msg)
        self.assertIn("приостановлена", msg.lower())

    def test_role_archived(self):
        result = {"ok": False, "code": "ROLE_ARCHIVED", "error": "archived"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-003")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-003", msg)
        self.assertIn("архивирован", msg.lower())

    def test_role_paused_and_role_archived_messages_are_distinct(self):
        paused = th._organization_assignment_message({"ok": False, "code": "ROLE_PAUSED", "error": ""}, "PRS-001", "ROLE-001")
        archived = th._organization_assignment_message({"ok": False, "code": "ROLE_ARCHIVED", "error": ""}, "PRS-001", "ROLE-001")
        self.assertNotEqual(paused, archived)

    def test_department_not_found(self):
        result = {"ok": False, "code": "DEPARTMENT_NOT_FOUND", "error": "not found", "department_id": "DEPT-999"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-001", msg)

    def test_department_archived(self):
        result = {"ok": False, "code": "DEPARTMENT_ARCHIVED", "error": "archived", "department_id": "DEPT-001"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("DEPT-001", msg)
        self.assertIn("архивирован", msg.lower())

    def test_person_not_linked_to_business(self):
        result = {"ok": False, "code": "PERSON_NOT_LINKED_TO_BUSINESS", "error": "not linked"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("PRS-001", msg)
        self.assertIn("не привязан", msg.lower())

    def test_business_mismatch(self):
        result = {"ok": False, "code": "PERSON_ROLE_BUSINESS_MISMATCH", "error": "mismatch"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("PRS-001", msg)
        self.assertIn("другому бизнесу", msg.lower())

    def test_multiple_active_assignments_integrity_error_lists_all_ids_no_first_pick(self):
        result = {
            "ok": False, "code": "MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR",
            "error": "conflict", "conflicting_assignment_ids": ("PRA-A", "PRA-B", "PRA-C"),
        }
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("⚠️", msg)
        self.assertIn("PRA-A", msg)
        self.assertIn("PRA-B", msg)
        self.assertIn("PRA-C", msg)
        self.assertIn("конфликт", msg.lower())

    def test_assignment_ended_immutable(self):
        result = {"ok": False, "code": "ASSIGNMENT_ENDED_IMMUTABLE", "error": "ended"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("завершено", msg.lower())

    def test_invalid_role_status(self):
        result = {"ok": False, "code": "INVALID_ROLE_STATUS", "error": "bad status"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)

    def test_invalid_assignment_status(self):
        result = {"ok": False, "code": "INVALID_ASSIGNMENT_STATUS", "error": "bad status"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "SOMETHING_NEW_NOT_YET_MAPPED", "error": "detail"}
        msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("SOMETHING_NEW_NOT_YET_MAPPED", msg)

    def test_no_raw_dict_ever_rendered(self):
        for code in (
            "ASSIGNMENT_CREATED", "ASSIGNMENT_REUSED", "PERSON_NOT_FOUND", "PERSON_ARCHIVED",
            "ROLE_NOT_FOUND", "ROLE_PAUSED", "ROLE_ARCHIVED", "DEPARTMENT_NOT_FOUND",
            "DEPARTMENT_ARCHIVED", "PERSON_NOT_LINKED_TO_BUSINESS", "PERSON_ROLE_BUSINESS_MISMATCH",
            "MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR", "ASSIGNMENT_ENDED_IMMUTABLE",
            "INVALID_ROLE_STATUS", "INVALID_ASSIGNMENT_STATUS", "UNKNOWN_CODE",
        ):
            result = {
                "ok": code in ("ASSIGNMENT_CREATED", "ASSIGNMENT_REUSED"),
                "code": code, "error": "x", "assignment_id": "PRA-1",
                "conflicting_assignment_ids": (), "department_id": "DEPT-1",
            }
            msg = th._organization_assignment_message(result, "PRS-001", "ROLE-001")
            self.assertIsInstance(msg, str)
            self.assertNotIn("{'ok'", msg)
            self.assertNotIn("Traceback", msg)


class TestStageRoleMessageMapping(unittest.TestCase):
    """/assignstagerole + /reassignstagerole — work_assignment_manager
    Stage->Role result codes."""

    def test_stage_role_assigned(self):
        result = {"ok": True, "code": "STAGE_ROLE_ASSIGNED", "relation_id": "REL-100"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-001")
        self.assertIn("✅", msg)
        self.assertIn("STAGE-001", msg)
        self.assertIn("ROLE-001", msg)
        self.assertIn("REL-100", msg)

    def test_stage_role_reused_is_distinct_from_assigned(self):
        result = {"ok": True, "code": "STAGE_ROLE_REUSED"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-001")
        self.assertNotIn("✅", msg)
        self.assertIn("ℹ️", msg)
        self.assertIn("уже назначен", msg.lower())

    def test_stage_role_reassigned_is_distinct_from_reused(self):
        result = {"ok": True, "code": "STAGE_ROLE_REASSIGNED", "old_relation_id": "REL-010", "new_relation_id": "REL-020"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-002")
        reused_msg = th._stage_role_message({"ok": True, "code": "STAGE_ROLE_REUSED"}, "STAGE-001", "ROLE-002")
        self.assertNotEqual(msg, reused_msg)
        self.assertIn("✅", msg)
        self.assertIn("REL-010", msg)
        self.assertIn("REL-020", msg)

    def test_stage_not_found(self):
        result = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "x"}
        msg = th._stage_role_message(result, "STAGE-999", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("STAGE-999", msg)

    def test_role_not_active_for_stage_assignment(self):
        result = {"ok": False, "code": "ROLE_NOT_ACTIVE_FOR_STAGE_ASSIGNMENT", "error": "x"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-002")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-002", msg)
        self.assertIn("active", msg.lower())

    def test_department_archived(self):
        result = {"ok": False, "code": "DEPARTMENT_ARCHIVED", "error": "x"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-002")
        self.assertIn("❌", msg)
        self.assertIn("ROLE-002", msg)
        self.assertIn("архивирован", msg.lower())

    def test_multiple_active_stage_role_relations_integrity_error_no_first_pick(self):
        result = {"ok": False, "code": "MULTIPLE_ACTIVE_STAGE_ROLE_RELATIONS_INTEGRITY_ERROR", "error": "x"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-002")
        self.assertIn("⚠️", msg)
        self.assertIn("STAGE-001", msg)
        self.assertIn("конфликт", msg.lower())
        self.assertIn("reassignstagerole", msg)

    def test_unknown_code_safe_fallback(self):
        result = {"ok": False, "code": "SOMETHING_NEW", "error": "detail"}
        msg = th._stage_role_message(result, "STAGE-001", "ROLE-001")
        self.assertIn("❌", msg)
        self.assertIn("SOMETHING_NEW", msg)

    def test_no_raw_dict_ever_rendered(self):
        for code in (
            "STAGE_ROLE_ASSIGNED", "STAGE_ROLE_REUSED", "STAGE_ROLE_REASSIGNED",
            "STAGE_NOT_FOUND", "ROLE_NOT_FOUND", "ROLE_NOT_ACTIVE_FOR_STAGE_ASSIGNMENT",
            "DEPARTMENT_NOT_FOUND", "DEPARTMENT_ARCHIVED",
            "MULTIPLE_ACTIVE_STAGE_ROLE_RELATIONS_INTEGRITY_ERROR", "UNKNOWN_CODE",
        ):
            result = {
                "ok": code.startswith("STAGE_ROLE_"), "code": code, "error": "x",
                "relation_id": "REL-1", "old_relation_id": "REL-0", "new_relation_id": "REL-2",
            }
            msg = th._stage_role_message(result, "STAGE-001", "ROLE-001")
            self.assertIsInstance(msg, str)
            self.assertNotIn("{'ok'", msg)
            self.assertNotIn("Traceback", msg)


class TestStageResponsibilityCanonicalStates(unittest.TestCase):
    """/stageresponsibility must safely render every resolve_stage_
    responsibility() outcome, including the Phase 35D/35E paused-Role
    and missing/archived-Department cases folded into
    configuration_error (RESOLUTION_STATUS stays a locked 4-value enum
    — see test_business_work_assignment.py's own enum-exactness test)."""

    def test_paused_role_shown_as_configuration_error_with_diagnostic_text(self):
        from business_core.work_assignment_manager import RESOLUTION_STATUS
        self.assertEqual(set(RESOLUTION_STATUS), {"assigned", "vacant", "unconfigured", "configuration_error"})

    def test_configuration_error_distinguishes_paused_from_archived_role_via_errors_text(self):
        paused_result = {
            "status": "configuration_error", "stage_id": "STAGE-001", "role_id": "ROLE-001",
            "person_id": None, "relation_id": "REL-010",
            "errors": ("Role 'ROLE-001' приостановлена (paused)",),
        }
        archived_result = {
            "status": "configuration_error", "stage_id": "STAGE-001", "role_id": "ROLE-001",
            "person_id": None, "relation_id": "REL-010",
            "errors": ("Role 'ROLE-001' архивирована",),
        }
        self.assertNotEqual(paused_result["errors"], archived_result["errors"])

    def test_configuration_error_distinguishes_missing_from_archived_department(self):
        missing = ("Department 'DEPT-999' не найден",)
        archived = ("Department 'DEPT-001' архивирован",)
        self.assertNotEqual(missing, archived)


if __name__ == "__main__":
    unittest.main()
