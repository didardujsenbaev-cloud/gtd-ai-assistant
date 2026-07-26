"""
Phase 35D — Organization Foundation (ADR-018): tests for the new
canonical Person↔Role assignment orchestration boundary,
business_core.business_builder.assign_person_to_role_canonical().

Covers Person eligibility, Role eligibility, Department eligibility,
Business-scope membership, duplicate-Assignment policy (zero/one/
multiple), and the structured result contract. No live Sheets writes —
mocks only, per ENGINEERING_STANDARDS.md Testing Standards.

Registered in conftest.py's hard socket-block set (Phase 35C/35D,
ADR-018 §24) — see PRS-003 incident precedent in conftest.py's module
docstring.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from business_core.business_builder import assign_person_to_role_canonical

ACTIVE_PERSON = {
    "person_id": "PRS-001", "status": "active", "person_type": "клиент",
    "biz_ids": [], "primary_biz_id": "",
}
ARCHIVED_PERSON = dict(ACTIVE_PERSON, status="archived")
LINKED_PERSON = dict(ACTIVE_PERSON, biz_ids=["BIZ-001"])
OTHER_LINKED_PERSON = dict(ACTIVE_PERSON, biz_ids=["BIZ-999"])

ACTIVE_ROLE = {
    "row_num": 2, "role_id": "ROLE-001", "department_id": "DEPT-001",
    "role_name": "Coordinator", "reports_to_role_id": "", "role_type": "internal",
    "employment_model": "full_time", "status": "active",
    "purpose": "", "main_result": "", "notes": "",
}
PLANNED_ROLE = dict(ACTIVE_ROLE, status="planned")
PAUSED_ROLE = dict(ACTIVE_ROLE, status="paused")
ARCHIVED_ROLE = dict(ACTIVE_ROLE, status="archived")

GLOBAL_DEPARTMENT = {
    "row_num": 2, "department_id": "DEPT-001", "business_id": "",
    "department_name": "Operations", "parent_department_id": "",
    "head_role_id": "", "status": "active", "notes": "",
}
BUSINESS_DEPARTMENT = dict(GLOBAL_DEPARTMENT, business_id="BIZ-001")
ARCHIVED_DEPARTMENT = dict(GLOBAL_DEPARTMENT, status="archived")

_BASE_PATCH_TARGETS = dict(
    find_person_by_id="business_core.person_manager.find_person_by_id",
    is_person_archived="business_core.person_manager.is_person_archived",
    has_person_business_link="business_core.person_manager.has_person_business_link",
    find_role_by_id="business_core.organization_manager.find_role_by_id",
    find_department_by_id="business_core.organization_manager.find_department_by_id",
    list_assignments_for_role="business_core.organization_manager.list_assignments_for_role",
    assign_person_to_role="business_core.organization_manager.assign_person_to_role",
)


def _run(person=ACTIVE_PERSON, role=ACTIVE_ROLE, department=GLOBAL_DEPARTMENT,
         active_assignments=(), assign_result=None, person_archived=False,
         has_biz_link=True, **kwargs):
    if assign_result is None:
        assign_result = {"ok": True, "assignment_id": "PRA-NEW", "code": "ASSIGNMENT_CREATED", "error": None}
    with patch(_BASE_PATCH_TARGETS["find_person_by_id"], return_value=person), \
         patch(_BASE_PATCH_TARGETS["is_person_archived"], return_value=person_archived), \
         patch(_BASE_PATCH_TARGETS["has_person_business_link"], return_value=has_biz_link), \
         patch(_BASE_PATCH_TARGETS["find_role_by_id"], return_value=role), \
         patch(_BASE_PATCH_TARGETS["find_department_by_id"], return_value=department), \
         patch(_BASE_PATCH_TARGETS["list_assignments_for_role"], return_value=list(active_assignments)), \
         patch(_BASE_PATCH_TARGETS["assign_person_to_role"], return_value=assign_result):
        return assign_person_to_role_canonical(
            kwargs.pop("person_id", "PRS-001"),
            kwargs.pop("role_id", "ROLE-001"),
            kwargs.pop("start_date", "2026-01-01"),
        )


class TestRequiredIds(unittest.TestCase):

    def test_missing_person_id_rejected(self):
        result = _run(person_id="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_missing_role_id_rejected(self):
        result = _run(role_id="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_NOT_FOUND")


class TestPersonEligibility(unittest.TestCase):

    def test_person_not_found_rejected(self):
        result = _run(person=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_archived_person_rejected(self):
        result = _run(person=ARCHIVED_PERSON, person_archived=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_ARCHIVED")


class TestRoleEligibility(unittest.TestCase):

    def test_role_not_found_rejected(self):
        result = _run(role=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_NOT_FOUND")

    def test_planned_role_is_eligible(self):
        result = _run(role=PLANNED_ROLE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_CREATED")

    def test_paused_role_rejected(self):
        result = _run(role=PAUSED_ROLE)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_PAUSED")

    def test_archived_role_rejected(self):
        result = _run(role=ARCHIVED_ROLE)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_ARCHIVED")


class TestDepartmentEligibility(unittest.TestCase):

    def test_department_not_found_rejected(self):
        result = _run(department=None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DEPARTMENT_NOT_FOUND")

    def test_archived_department_rejected(self):
        result = _run(department=ARCHIVED_DEPARTMENT)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DEPARTMENT_ARCHIVED")


class TestBusinessMembership(unittest.TestCase):

    def test_global_department_requires_no_membership(self):
        result = _run(department=GLOBAL_DEPARTMENT, person=ACTIVE_PERSON, has_biz_link=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_CREATED")

    def test_business_department_with_linked_person_succeeds(self):
        result = _run(department=BUSINESS_DEPARTMENT, person=LINKED_PERSON, has_biz_link=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_CREATED")

    def test_business_department_with_unlinked_person_rejected(self):
        result = _run(department=BUSINESS_DEPARTMENT, person=ACTIVE_PERSON, has_biz_link=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_LINKED_TO_BUSINESS")

    def test_business_department_with_person_linked_to_other_business_rejected(self):
        result = _run(department=BUSINESS_DEPARTMENT, person=OTHER_LINKED_PERSON, has_biz_link=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_ROLE_BUSINESS_MISMATCH")


class TestDuplicateAssignmentPolicy(unittest.TestCase):

    def test_zero_active_assignments_creates(self):
        result = _run(active_assignments=())
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_CREATED")
        self.assertTrue(result["assignment_created"])
        self.assertFalse(result["assignment_reused"])

    def test_one_matching_active_assignment_is_reused(self):
        existing = {"assignment_id": "PRA-EXISTING", "person_id": "PRS-001", "role_id": "ROLE-001", "status": "active"}
        result = _run(active_assignments=[existing])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_REUSED")
        self.assertTrue(result["assignment_reused"])
        self.assertFalse(result["assignment_created"])
        self.assertEqual(result["assignment_id"], "PRA-EXISTING")

    def test_multiple_active_assignments_blocks_with_all_conflicting_ids(self):
        dup1 = {"assignment_id": "PRA-A", "person_id": "PRS-001", "role_id": "ROLE-001", "status": "active"}
        dup2 = {"assignment_id": "PRA-B", "person_id": "PRS-001", "role_id": "ROLE-001", "status": "active"}
        result = _run(active_assignments=[dup1, dup2])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR")
        self.assertEqual(set(result["conflicting_assignment_ids"]), {"PRA-A", "PRA-B"})

    def test_active_assignment_for_different_person_does_not_block(self):
        other = {"assignment_id": "PRA-OTHER", "person_id": "PRS-999", "role_id": "ROLE-001", "status": "active"}
        result = _run(active_assignments=[other])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ASSIGNMENT_CREATED")


class TestStructuredResultContract(unittest.TestCase):

    def test_success_result_has_all_expected_fields(self):
        result = _run()
        for field in (
            "ok", "code", "error", "department_id", "role_id", "person_id",
            "assignment_id", "assignment_created", "assignment_reused",
            "previous_status", "final_status", "warnings",
            "conflicting_assignment_ids", "retry_safe",
        ):
            self.assertIn(field, result)

    def test_low_level_write_failure_is_propagated(self):
        result = _run(assign_result={"ok": False, "assignment_id": "", "code": "", "error": "boom"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")


if __name__ == "__main__":
    unittest.main()
