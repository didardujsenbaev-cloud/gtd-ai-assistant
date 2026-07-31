"""
Phase 17C: Authorization Domain tests.

Registered in conftest.py's hard socket-block set (_IDENTITY_DOMAIN_TEST_FILES)
BEFORE this test logic was written, per the PRS-003/Phase-17B-IR1 precedent.

All identity_manager reads are mocked via string-based patch targets on
business_core.authorization.im.<func> — patching the exact module-object
attribute that business_core/authorization.py's `from business_core import
identity_manager as im` binds at import time, not a possibly-stale
sys.modules entry (the same class of bug that caused the Phase 17B-IR1
incident).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from business_core import authorization as az


def _identity(telegram_identity_id="TGID-1", employee_id="EMP-1", telegram_user_id="111", status="active"):
    return {
        "telegram_identity_id": telegram_identity_id, "employee_id": employee_id,
        "telegram_user_id": telegram_user_id, "telegram_actor": f"telegram:{telegram_user_id}",
        "status": status, "linked_at": "2026-01-01 00:00:00 UTC", "linked_by": "system:owner_bootstrap",
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }


def _employee(employee_id="EMP-1", status="active"):
    return {
        "employee_id": employee_id, "person_id": "", "display_label": "Test",
        "status": status, "created_at": "2026-01-01 00:00:00 UTC", "created_by": "system:owner_bootstrap",
        "activated_at": "2026-01-01 00:00:00 UTC", "activated_by": "system:owner_bootstrap",
        "disabled_at": "", "disabled_by": "", "disable_reason": "", "notes": "",
    }


def _ara(access_role_assignment_id="ARA-1", employee_id="EMP-1", role="OWNER", status="active",
          effective_from="", effective_until=""):
    return {
        "access_role_assignment_id": access_role_assignment_id, "employee_id": employee_id,
        "role": role, "status": status, "effective_from": effective_from, "effective_until": effective_until,
        "assigned_at": "2026-01-01 00:00:00 UTC", "assigned_by": "system:owner_bootstrap",
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }


def _asa(access_scope_assignment_id="ASA-1", employee_id="EMP-1", access_role_assignment_id="ARA-1",
          scope_type="ALL_BUSINESSES", business_id="", object_id="", status="active",
          effective_from="", effective_until=""):
    return {
        "access_scope_assignment_id": access_scope_assignment_id, "employee_id": employee_id,
        "access_role_assignment_id": access_role_assignment_id, "scope_type": scope_type,
        "business_id": business_id, "object_id": object_id, "status": status,
        "effective_from": effective_from, "effective_until": effective_until,
        "assigned_at": "2026-01-01 00:00:00 UTC", "assigned_by": "system:owner_bootstrap",
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }


class AuthorizationTestBase(unittest.TestCase):
    def setUp(self):
        self.identities = []
        self.employees = {}
        self.role_assignments = []
        self.scope_assignments = []
        self._reads_called = []

    def _identities_side_effect(self, telegram_user_id):
        self._reads_called.append("find_active_telegram_identities_by_telegram_user_id")
        return [i for i in self.identities if i["telegram_user_id"] == str(telegram_user_id) and i["status"] == "active"]

    def _employee_side_effect(self, employee_id):
        self._reads_called.append("find_employee")
        return self.employees.get(employee_id)

    def _role_assignments_side_effect(self, employee_id, active_only=False):
        self._reads_called.append("find_role_assignments_by_employee")
        rows = [r for r in self.role_assignments if r["employee_id"] == employee_id]
        if active_only:
            rows = [r for r in rows if r["status"] == "active"]
        return rows

    def _scope_assignments_side_effect(self, access_role_assignment_id, active_only=False):
        self._reads_called.append("find_scope_assignments_by_role_assignment")
        rows = [s for s in self.scope_assignments if s["access_role_assignment_id"] == access_role_assignment_id]
        if active_only:
            rows = [s for s in rows if s["status"] == "active"]
        return rows

    def _authorize(self, telegram_user_id="111", **kwargs):
        with patch("business_core.authorization.im.find_active_telegram_identities_by_telegram_user_id",
                   side_effect=self._identities_side_effect), \
             patch("business_core.authorization.im.find_employee", side_effect=self._employee_side_effect), \
             patch("business_core.authorization.im.find_role_assignments_by_employee",
                   side_effect=self._role_assignments_side_effect), \
             patch("business_core.authorization.im.find_scope_assignments_by_role_assignment",
                   side_effect=self._scope_assignments_side_effect):
            return az.authorize_business_core_access(telegram_user_id, **kwargs)

    def _standard_owner(self, now=None):
        """Owner setup identical in shape to production EMP-002/TGID-002/
        ARA-002/ASA-002."""
        self.identities = [_identity(telegram_user_id="570004109")]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]


# ─────────────────────────────────────────────────────────────
# Structural validation
# ─────────────────────────────────────────────────────────────

class TestStructuralValidation(AuthorizationTestBase):
    def test_invalid_telegram_user_id_non_numeric(self):
        r = self._authorize(telegram_user_id="abc", resource="OBJECT", action="READ", business_id="B", object_id="O")
        self.assertEqual(r["code"], "INVALID_TELEGRAM_USER_ID")
        self.assertFalse(r["allowed"])
        self.assertEqual(self._reads_called, [])

    def test_invalid_resource(self):
        r = self._authorize(resource="NOT_A_RESOURCE", action="READ")
        self.assertEqual(r["code"], "INVALID_RESOURCE")
        self.assertEqual(self._reads_called, [])

    def test_invalid_action(self):
        r = self._authorize(resource="BUSINESS", action="NOT_AN_ACTION")
        self.assertEqual(r["code"], "INVALID_ACTION")
        self.assertEqual(self._reads_called, [])

    def test_missing_business_id_for_object(self):
        r = self._authorize(resource="OBJECT", action="READ", object_id="OBJ-1")
        self.assertEqual(r["code"], "TARGET_REQUIRED")
        self.assertEqual(self._reads_called, [])

    def test_missing_object_id_for_document(self):
        r = self._authorize(resource="DOCUMENT", action="READ", business_id="B")
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_missing_business_id_for_client(self):
        r = self._authorize(resource="CLIENT", action="READ")
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_missing_business_id_for_finance(self):
        r = self._authorize(resource="FINANCE", action="READ")
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_access_control_forbidden_target(self):
        r = self._authorize(resource="ACCESS_CONTROL", action="MANAGE_ACCESS", business_id="B")
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_access_control_targetless_structurally_valid(self):
        # structurally fine; will fail later at identity resolution
        r = self._authorize(resource="ACCESS_CONTROL", action="MANAGE_ACCESS")
        self.assertNotEqual(r["code"], "TARGET_REQUIRED")

    def test_business_write_requires_business_id(self):
        r = self._authorize(resource="BUSINESS", action="UPDATE")
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_business_read_targetless_structurally_valid(self):
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertNotEqual(r["code"], "TARGET_REQUIRED")

    def test_invalid_resource_zero_identity_reads(self):
        self._authorize(resource="BAD", action="READ")
        self.assertEqual(self._reads_called, [])

    def test_invalid_action_zero_identity_reads(self):
        self._authorize(resource="OBJECT", action="BAD", business_id="B", object_id="O")
        self.assertEqual(self._reads_called, [])

    def test_missing_target_zero_identity_reads(self):
        self._authorize(resource="OBJECT", action="READ")
        self.assertEqual(self._reads_called, [])


# ─────────────────────────────────────────────────────────────
# Identity resolution
# ─────────────────────────────────────────────────────────────

class TestIdentityResolution(AuthorizationTestBase):
    def test_valid_unique_identity_owner_allowed(self):
        self._standard_owner()
        r = self._authorize(telegram_user_id="570004109", resource="BUSINESS", action="READ")
        self.assertTrue(r["allowed"])
        self.assertEqual(r["code"], "ACCESS_ALLOWED")

    def test_unknown_identity(self):
        r = self._authorize(telegram_user_id="999999", resource="OBJECT", action="READ", business_id="B", object_id="O")
        self.assertEqual(r["code"], "TELEGRAM_IDENTITY_NOT_FOUND")

    def test_duplicate_active_identities(self):
        self.identities = [_identity(telegram_identity_id="TGID-1", telegram_user_id="111"),
                            _identity(telegram_identity_id="TGID-2", telegram_user_id="111")]
        r = self._authorize(telegram_user_id="111", resource="OBJECT", action="READ", business_id="B", object_id="O")
        self.assertEqual(r["code"], "TELEGRAM_IDENTITY_AMBIGUOUS")

    def test_revoked_identity_not_found(self):
        self.identities = [_identity(status="revoked")]
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertEqual(r["code"], "TELEGRAM_IDENTITY_NOT_FOUND")

    def test_missing_employee(self):
        self.identities = [_identity(employee_id="EMP-GHOST")]
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertEqual(r["code"], "EMPLOYEE_NOT_FOUND")

    def test_pending_employee(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee(status="pending")}
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertEqual(r["code"], "EMPLOYEE_PENDING")

    def test_disabled_employee(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee(status="disabled")}
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertEqual(r["code"], "EMPLOYEE_DISABLED")

    def test_active_employee_continues(self):
        self._standard_owner()
        r = self._authorize(telegram_user_id="570004109", resource="BUSINESS", action="READ")
        self.assertEqual(r["employee_id"], "EMP-1")

    def test_telegram_actor_derived_never_caller_supplied(self):
        self._standard_owner()
        r = self._authorize(telegram_user_id="570004109", resource="BUSINESS", action="READ")
        self.assertEqual(r["telegram_actor"], "telegram:570004109")


# ─────────────────────────────────────────────────────────────
# Time / effective-time rules
# ─────────────────────────────────────────────────────────────

class TestEffectiveTime(AuthorizationTestBase):
    def _base(self, effective_from="", effective_until=""):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER", effective_from=effective_from, effective_until=effective_until)]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]

    def test_empty_bounds_allowed(self):
        self._base()
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertTrue(r["allowed"])

    def test_before_effective_from_denied(self):
        self._base(effective_from="2099-01-01 00:00:00 UTC")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "ASSIGNMENT_NOT_YET_EFFECTIVE")

    def test_exactly_effective_from_allowed(self):
        self._base(effective_from="2026-01-01 00:00:00 UTC")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertTrue(r["allowed"])

    def test_between_bounds_allowed(self):
        self._base(effective_from="2020-01-01 00:00:00 UTC", effective_until="2099-01-01 00:00:00 UTC")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertTrue(r["allowed"])

    def test_exactly_effective_until_is_expired(self):
        self._base(effective_until="2026-01-01 00:00:00 UTC")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "ASSIGNMENT_EXPIRED")

    def test_after_effective_until_expired(self):
        self._base(effective_until="2020-01-01 00:00:00 UTC")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertEqual(r["code"], "ASSIGNMENT_EXPIRED")

    def test_malformed_role_timestamp(self):
        self._base(effective_from="not-a-date")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "MALFORMED_ROLE_ASSIGNMENT")

    def test_malformed_scope_timestamp(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES", effective_until="garbage")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "MALFORMED_SCOPE_ASSIGNMENT")


# ─────────────────────────────────────────────────────────────
# Role / scope pairing
# ─────────────────────────────────────────────────────────────

class TestPairing(AuthorizationTestBase):
    def test_scope_linked_to_same_ara_allows(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(access_role_assignment_id="ARA-1", role="VIEWER")]
        self.scope_assignments = [_asa(access_scope_assignment_id="ASA-1", access_role_assignment_id="ARA-1", scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertTrue(r["allowed"])
        self.assertEqual(r["matched_role_assignment_id"], "ARA-1")
        self.assertEqual(r["matched_scope_assignment_id"], "ASA-1")

    def test_worked_example_viewer_ara010_coordinator_ara011(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [
            _ara(access_role_assignment_id="ARA-010", role="VIEWER"),
            _ara(access_role_assignment_id="ARA-011", role="COORDINATOR"),
        ]
        self.scope_assignments = [
            _asa(access_scope_assignment_id="ASA-010", access_role_assignment_id="ARA-010", scope_type="ALL_BUSINESSES"),
            _asa(access_scope_assignment_id="ASA-011", access_role_assignment_id="ARA-011",
                 scope_type="ASSIGNED_OBJECTS_ONLY", object_id="OBJ-007"),
        ]
        # COORDINATOR's broader-looking VIEWER sibling scope must never leak into a COORDINATOR-only permission (UPDATE)
        r = self._authorize(resource="OBJECT", action="UPDATE", business_id="B", object_id="OBJ-999")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

        r2 = self._authorize(resource="OBJECT", action="UPDATE", business_id="B", object_id="OBJ-007")
        self.assertTrue(r2["allowed"])
        self.assertEqual(r2["matched_role"], "COORDINATOR")
        self.assertEqual(r2["matched_role_assignment_id"], "ARA-011")
        self.assertEqual(r2["matched_scope_assignment_id"], "ASA-011")

    def test_scope_employee_id_mismatch_fails_closed(self):
        self.identities = [_identity(employee_id="EMP-1")]
        self.employees = {"EMP-1": _employee(employee_id="EMP-1")}
        self.role_assignments = [_ara(employee_id="EMP-1", role="VIEWER")]
        self.scope_assignments = [_asa(employee_id="EMP-OTHER", scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "MALFORMED_SCOPE_ASSIGNMENT")

    def test_missing_linked_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = []
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "NO_LINKED_SCOPE")

    def test_revoked_scope_treated_as_no_linked_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES", status="revoked")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "NO_LINKED_SCOPE")

    def test_expired_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES", effective_until="2020-01-01 00:00:00 UTC")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertEqual(r["code"], "ASSIGNMENT_EXPIRED")

    def test_expired_role_unreachable_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER", effective_until="2020-01-01 00:00:00 UTC")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertEqual(r["code"], "ASSIGNMENT_EXPIRED")

    def test_role_with_unknown_value(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="SUPERUSER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "MALFORMED_ROLE_ASSIGNMENT")

    def test_scope_with_unknown_type(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="GLOBAL_EVERYTHING")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r["code"], "MALFORMED_SCOPE_ASSIGNMENT")

    def test_duplicate_scopes_either_can_allow(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [
            _asa(access_scope_assignment_id="ASA-1", scope_type="SELECTED_BUSINESSES", business_id="B"),
            _asa(access_scope_assignment_id="ASA-2", scope_type="SELECTED_BUSINESSES", business_id="B"),
        ]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertTrue(r["allowed"])

    def test_multiple_roles_scopes_union_without_cross_pair_leakage(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [
            _ara(access_role_assignment_id="ARA-A", role="VIEWER"),
            _ara(access_role_assignment_id="ARA-B", role="DOCUMENT_SPECIALIST"),
        ]
        self.scope_assignments = [
            _asa(access_scope_assignment_id="ASA-A", access_role_assignment_id="ARA-A", scope_type="ALL_BUSINESSES"),
            _asa(access_scope_assignment_id="ASA-B", access_role_assignment_id="ARA-B", scope_type="SELECTED_BUSINESSES", business_id="B2"),
        ]
        r = self._authorize(resource="DOCUMENT", action="CREATE", business_id="B2", object_id="O1")
        self.assertTrue(r["allowed"])
        self.assertEqual(r["matched_role"], "DOCUMENT_SPECIALIST")
        self.assertEqual(sorted(r["roles"]), ["DOCUMENT_SPECIALIST", "VIEWER"])


# ─────────────────────────────────────────────────────────────
# Resource / action matrix
# ─────────────────────────────────────────────────────────────

class TestMatrix(AuthorizationTestBase):
    def _grant(self, role, resource, business_id="", object_id=""):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role=role)]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]

    def test_every_matrix_cell(self):
        for role, resource_map in az.ROLE_RESOURCE_ACTION_MATRIX.items():
            for resource, allowed_actions in resource_map.items():
                for action in az.AUTHZ_ACTIONS:
                    with self.subTest(role=role, resource=resource, action=action):
                        self._grant(role, resource)
                        business_id = "" if resource == "ACCESS_CONTROL" else "B"
                        object_id = "O" if resource in ("OBJECT", "DOCUMENT", "OPERATIONAL") else ""
                        if resource == "BUSINESS" and action == "READ":
                            business_id = ""
                        r = self._authorize(resource=resource, action=action, business_id=business_id, object_id=object_id)
                        if action in allowed_actions:
                            if resource == "BUSINESS" and action == "READ" and role not in ("OWNER", "ADMIN"):
                                # targetless BUSINESS READ special rule — covered separately
                                continue
                            self.assertTrue(r["allowed"], f"{role}/{resource}/{action} expected allowed")
                        else:
                            self.assertFalse(r["allowed"], f"{role}/{resource}/{action} expected denied")
                            self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_owner_still_requires_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="OTHER")]
        r = self._authorize(resource="BUSINESS", action="UPDATE", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_admin_cannot_manage_access(self):
        self._grant("ADMIN", "ACCESS_CONTROL")
        r = self._authorize(resource="ACCESS_CONTROL", action="MANAGE_ACCESS")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_coordinator_cannot_client(self):
        self._grant("COORDINATOR", "CLIENT")
        r = self._authorize(resource="CLIENT", action="READ", business_id="B")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_coordinator_cannot_finance(self):
        self._grant("COORDINATOR", "FINANCE")
        r = self._authorize(resource="FINANCE", action="READ", business_id="B")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_document_specialist_cannot_finance(self):
        self._grant("DOCUMENT_SPECIALIST", "FINANCE")
        r = self._authorize(resource="FINANCE", action="READ", business_id="B")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_document_specialist_cannot_access_control(self):
        self._grant("DOCUMENT_SPECIALIST", "ACCESS_CONTROL")
        r = self._authorize(resource="ACCESS_CONTROL", action="READ")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_viewer_cannot_write(self):
        self._grant("VIEWER", "DOCUMENT")
        r = self._authorize(resource="DOCUMENT", action="CREATE", business_id="B", object_id="O")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_viewer_cannot_access_control(self):
        self._grant("VIEWER", "ACCESS_CONTROL")
        r = self._authorize(resource="ACCESS_CONTROL", action="READ")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_viewer_finance_read_only_through_matching_scope(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="B1")]
        r_match = self._authorize(resource="FINANCE", action="READ", business_id="B1")
        self.assertTrue(r_match["allowed"])
        r_nomatch = self._authorize(resource="FINANCE", action="READ", business_id="B2")
        self.assertFalse(r_nomatch["allowed"])
        self.assertEqual(r_nomatch["code"], "SCOPE_NOT_MATCHED")


# ─────────────────────────────────────────────────────────────
# Scope compatibility
# ─────────────────────────────────────────────────────────────

class TestScopeCompatibility(AuthorizationTestBase):
    def _setup(self, role, scope_type, business_id="", object_id=""):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role=role)]
        self.scope_assignments = [_asa(scope_type=scope_type, business_id=business_id, object_id=object_id)]

    def test_all_businesses_matching(self):
        self._setup("VIEWER", "ALL_BUSINESSES")
        r = self._authorize(resource="OBJECT", action="READ", business_id="ANY", object_id="ANY")
        self.assertTrue(r["allowed"])

    def test_selected_businesses_matching(self):
        self._setup("VIEWER", "SELECTED_BUSINESSES", business_id="B1")
        r = self._authorize(resource="OBJECT", action="READ", business_id="B1", object_id="O1")
        self.assertTrue(r["allowed"])

    def test_selected_businesses_non_matching(self):
        self._setup("VIEWER", "SELECTED_BUSINESSES", business_id="B1")
        r = self._authorize(resource="OBJECT", action="READ", business_id="B2", object_id="O1")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_matching(self):
        self._setup("VIEWER", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="OBJECT", action="READ", business_id="B", object_id="OBJ-7")
        self.assertTrue(r["allowed"])

    def test_assigned_objects_only_non_matching(self):
        self._setup("VIEWER", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="OBJECT", action="READ", business_id="B", object_id="OBJ-8")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_cannot_client(self):
        self._setup("DOCUMENT_SPECIALIST", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="CLIENT", action="READ", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_cannot_business(self):
        self._setup("OWNER", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_cannot_finance(self):
        self._setup("OWNER", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="FINANCE", action="READ", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_cannot_access_control(self):
        self._setup("OWNER", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="ACCESS_CONTROL", action="READ")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_client_via_assigned_objects_denied_even_with_matching_object_id(self):
        self._setup("DOCUMENT_SPECIALIST", "ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")
        r = self._authorize(resource="CLIENT", action="READ", business_id="B")
        self.assertFalse(r["allowed"])


# ─────────────────────────────────────────────────────────────
# Targetless BUSINESS READ
# ─────────────────────────────────────────────────────────────

class TestTargetlessBusinessRead(AuthorizationTestBase):
    def _setup(self, role, scope_type):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role=role)]
        self.scope_assignments = [_asa(scope_type=scope_type)]

    def test_owner_all_businesses_allowed(self):
        self._setup("OWNER", "ALL_BUSINESSES")
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertTrue(r["allowed"])

    def test_admin_all_businesses_allowed(self):
        self._setup("ADMIN", "ALL_BUSINESSES")
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertTrue(r["allowed"])

    def test_viewer_all_businesses_denied(self):
        self._setup("VIEWER", "ALL_BUSINESSES")
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_owner_selected_businesses_denied(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="B1")]
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_coordinator_denied_by_role_matrix(self):
        self._setup("COORDINATOR", "ALL_BUSINESSES")
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")


# ─────────────────────────────────────────────────────────────
# Determinism / precedence
# ─────────────────────────────────────────────────────────────

class TestDeterminism(AuthorizationTestBase):
    def test_ara_row_order_shuffle_identical_result(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        ara_a = _ara(access_role_assignment_id="ARA-A", role="VIEWER")
        ara_b = _ara(access_role_assignment_id="ARA-B", role="COORDINATOR")
        self.scope_assignments = [
            _asa(access_scope_assignment_id="ASA-A", access_role_assignment_id="ARA-A", scope_type="ALL_BUSINESSES"),
            _asa(access_scope_assignment_id="ASA-B", access_role_assignment_id="ARA-B", scope_type="ASSIGNED_OBJECTS_ONLY", object_id="O1"),
        ]
        self.role_assignments = [ara_a, ara_b]
        r1 = self._authorize(resource="OBJECT", action="UPDATE", business_id="B", object_id="O1")
        self.role_assignments = [ara_b, ara_a]
        r2 = self._authorize(resource="OBJECT", action="UPDATE", business_id="B", object_id="O1")
        self.assertEqual(r1["matched_role_assignment_id"], r2["matched_role_assignment_id"])
        self.assertEqual(r1["matched_scope_assignment_id"], r2["matched_scope_assignment_id"])

    def test_asa_row_order_shuffle_identical_result(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        asa_a = _asa(access_scope_assignment_id="ASA-A", scope_type="SELECTED_BUSINESSES", business_id="OTHER")
        asa_b = _asa(access_scope_assignment_id="ASA-B", scope_type="SELECTED_BUSINESSES", business_id="B")
        self.scope_assignments = [asa_a, asa_b]
        r1 = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.scope_assignments = [asa_b, asa_a]
        r2 = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        self.assertEqual(r1["matched_scope_assignment_id"], r2["matched_scope_assignment_id"])
        self.assertEqual(r1["matched_scope_assignment_id"], "ASA-B")

    def test_returned_pair_belongs_together(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(access_role_assignment_id="ARA-X", role="VIEWER")]
        self.scope_assignments = [_asa(access_scope_assignment_id="ASA-X", access_role_assignment_id="ARA-X", scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B")
        matched_scope = next(s for s in self.scope_assignments if s["access_scope_assignment_id"] == r["matched_scope_assignment_id"])
        self.assertEqual(matched_scope["access_role_assignment_id"], r["matched_role_assignment_id"])

    def test_unrelated_malformed_role_does_not_override_clean_role_not_permitted(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [
            _ara(access_role_assignment_id="ARA-BAD", role="NOT_A_ROLE"),
            _ara(access_role_assignment_id="ARA-CLEAN", role="COORDINATOR"),
        ]
        self.scope_assignments = [_asa(access_role_assignment_id="ARA-CLEAN", scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="CLIENT", action="READ", business_id="B")
        self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")

    def test_expired_matching_pair_does_not_override_active_scope_not_matched(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [
            _ara(access_role_assignment_id="ARA-EXPIRED", role="VIEWER", effective_until="2020-01-01 00:00:00 UTC"),
            _ara(access_role_assignment_id="ARA-ACTIVE", role="VIEWER"),
        ]
        self.scope_assignments = [
            _asa(access_role_assignment_id="ARA-EXPIRED", scope_type="SELECTED_BUSINESSES", business_id="B"),
            _asa(access_role_assignment_id="ARA-ACTIVE", scope_type="SELECTED_BUSINESSES", business_id="OTHER"),
        ]
        r = self._authorize(resource="BUSINESS", action="READ", business_id="B", now="2026-01-01 00:00:00 UTC")
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")


# ─────────────────────────────────────────────────────────────
# Result contract
# ─────────────────────────────────────────────────────────────

class TestResultContract(AuthorizationTestBase):
    _EXPECTED_KEYS = {
        "ok", "allowed", "code", "error", "retry_safe", "telegram_user_id", "telegram_actor",
        "employee_id", "roles", "resource", "action", "matched_role", "matched_role_assignment_id",
        "matched_scope_assignment_id", "scope_type", "business_id", "object_id", "evaluated_at",
        "denial_reason", "verification_errors",
    }

    def test_every_result_key_present(self):
        r = self._authorize(resource="BUSINESS", action="READ")
        self.assertEqual(set(r.keys()), self._EXPECTED_KEYS)

    def test_expected_denial_ok_true_allowed_false(self):
        r = self._authorize(resource="OBJECT", action="READ", business_id="B", object_id="O")
        self.assertTrue(r["ok"])
        self.assertFalse(r["allowed"])
        self.assertTrue(r["retry_safe"])

    def test_infrastructure_failure_ok_false_retry_unsafe(self):
        def _boom(*_a, **_k):
            raise RuntimeError("Sheets down")
        with patch("business_core.authorization.im.find_active_telegram_identities_by_telegram_user_id", side_effect=_boom):
            r = az.authorize_business_core_access("111", resource="BUSINESS", action="READ")
        self.assertFalse(r["ok"])
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "AUTHORIZATION_READ_FAILED")
        self.assertFalse(r["retry_safe"])

    def test_access_allowed_fields_correct(self):
        self._standard_owner()
        r = self._authorize(telegram_user_id="570004109", resource="BUSINESS", action="READ")
        self.assertTrue(r["ok"])
        self.assertTrue(r["allowed"])
        self.assertEqual(r["code"], "ACCESS_ALLOWED")
        self.assertTrue(r["retry_safe"])
        self.assertEqual(r["matched_role"], "OWNER")
        self.assertEqual(r["scope_type"], "ALL_BUSINESSES")

    def test_roles_vs_matched_role_distinction(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [
            _ara(access_role_assignment_id="ARA-V", role="VIEWER"),
            _ara(access_role_assignment_id="ARA-C", role="COORDINATOR"),
        ]
        self.scope_assignments = [
            _asa(access_role_assignment_id="ARA-V", scope_type="ALL_BUSINESSES"),
            _asa(access_role_assignment_id="ARA-C", scope_type="ASSIGNED_OBJECTS_ONLY", object_id="O1"),
        ]
        r = self._authorize(resource="OBJECT", action="UPDATE", business_id="B", object_id="O1")
        self.assertEqual(r["matched_role"], "COORDINATOR")
        self.assertIn("VIEWER", r["roles"])
        self.assertIn("COORDINATOR", r["roles"])

    def test_telegram_user_id_string_even_when_int_input(self):
        self._standard_owner()
        r = self._authorize(telegram_user_id=570004109, resource="BUSINESS", action="READ")
        self.assertEqual(r["telegram_user_id"], "570004109")
        self.assertIsInstance(r["telegram_user_id"], str)


# ─────────────────────────────────────────────────────────────
# Decision codes — every code reachable
# ─────────────────────────────────────────────────────────────

class TestDecisionCodes(AuthorizationTestBase):
    def test_no_unused_code_members_all_reachable(self):
        reached = set()

        # ACCESS_ALLOWED
        self._standard_owner()
        reached.add(self._authorize(telegram_user_id="570004109", resource="BUSINESS", action="READ")["code"])

        self.setUp()
        reached.add(self._authorize(telegram_user_id="abc", resource="OBJECT", action="READ", business_id="B", object_id="O")["code"])
        self.setUp()
        reached.add(self._authorize(resource="BAD", action="READ")["code"])
        self.setUp()
        reached.add(self._authorize(resource="BUSINESS", action="BAD")["code"])
        self.setUp()
        reached.add(self._authorize(resource="OBJECT", action="READ")["code"])
        self.setUp()
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # TELEGRAM_IDENTITY_NOT_FOUND

        self.setUp()
        self.identities = [_identity(telegram_identity_id="TGID-1"), _identity(telegram_identity_id="TGID-2")]
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # AMBIGUOUS

        self.setUp()
        self.identities = [_identity(employee_id="GHOST")]
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # EMPLOYEE_NOT_FOUND

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee(status="pending")}
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # EMPLOYEE_PENDING

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee(status="disabled")}
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # EMPLOYEE_DISABLED

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # NO_ACTIVE_ROLE (no ARA rows)

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        reached.add(self._authorize(resource="DOCUMENT", action="CREATE", business_id="B", object_id="O")["code"])  # ROLE_NOT_PERMITTED

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="BAD_ROLE")]
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # MALFORMED_ROLE_ASSIGNMENT

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # NO_LINKED_SCOPE

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="OTHER")]
        reached.add(self._authorize(resource="BUSINESS", action="READ", business_id="B")["code"])  # SCOPE_NOT_MATCHED

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="BAD_TYPE")]
        reached.add(self._authorize(resource="BUSINESS", action="READ")["code"])  # MALFORMED_SCOPE_ASSIGNMENT

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER", effective_from="2099-01-01 00:00:00 UTC")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        reached.add(self._authorize(resource="BUSINESS", action="READ", now="2026-01-01 00:00:00 UTC")["code"])  # NOT_YET_EFFECTIVE

        self.setUp()
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER", effective_until="2020-01-01 00:00:00 UTC")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        reached.add(self._authorize(resource="BUSINESS", action="READ", now="2026-01-01 00:00:00 UTC")["code"])  # EXPIRED

        def _boom(*_a, **_k):
            raise RuntimeError("boom")
        with patch("business_core.authorization.im.find_active_telegram_identities_by_telegram_user_id", side_effect=_boom):
            reached.add(az.authorize_business_core_access("111", resource="BUSINESS", action="READ")["code"])

        self.assertEqual(reached, set(az.AUTHZ_DECISION_CODES))


# ─────────────────────────────────────────────────────────────
# Architecture guards
# ─────────────────────────────────────────────────────────────

class TestArchitectureGuards(unittest.TestCase):
    def test_no_write_helper_imported(self):
        import inspect
        source = inspect.getsource(az)
        forbidden = [
            "create_pending_employee", "activate_employee", "disable_employee", "reactivate_employee",
            "link_telegram_identity", "revoke_telegram_identity", "assign_access_role", "revoke_access_role",
            "assign_access_scope", "revoke_access_scope", "_bootstrap_assign_owner_role",
            "_remediate_revoke_incident_owner_role", "append_business_row", "update_business_row",
        ]
        for name in forbidden:
            self.assertNotIn(name, source, f"authorization.py must not reference write helper {name}")

    def test_no_telegram_or_business_builder_import(self):
        import inspect
        source = inspect.getsource(az)
        for forbidden in ("import telegram", "telegram_handlers", "business_builder", "gspread"):
            self.assertNotIn(forbidden, source)

    def test_no_direct_sheets_import(self):
        import inspect
        source = inspect.getsource(az)
        self.assertNotIn("business_core.sheets", source)
        self.assertNotIn("get_business_sheet", source)
        self.assertNotIn("read_business_sheet", source)

    def test_only_stdlib_and_identity_manager_imports(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(az))
        allowed_modules = {"datetime", "typing", "business_core", "__future__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertIn(top, allowed_modules, f"unexpected import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    self.assertIn(top, allowed_modules, f"unexpected import from: {node.module}")

    def test_no_cache_state(self):
        import inspect
        source = inspect.getsource(az)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, source)

    def test_hard_socket_blocked_and_union(self):
        import conftest
        self.assertIn("test_authorization_domain.py", conftest._IDENTITY_DOMAIN_TEST_FILES)
        self.assertIn("test_authorization_domain.py", conftest._HARD_SOCKET_BLOCK_TEST_FILES)

    def test_fixture_autouse(self):
        import conftest
        fixturedef = conftest._block_live_sockets_for_hardened_tests
        marker = getattr(fixturedef, "_pytestfixturefunction", None) or getattr(fixturedef, "_fixture_function_marker", None)
        self.assertIsNotNone(marker, "expected a pytest fixture marker on _block_live_sockets_for_hardened_tests")
        self.assertTrue(marker.autouse)

    def test_socket_connect_rejected_before_reaching_sheets(self):
        import socket
        with self.assertRaises(AssertionError):
            socket.socket().connect(("example.com", 443))

    def test_schema_counts_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_registry"]), 27)
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)
        self.assertEqual(len(BUSINESS_HEADERS["document_field_reviews"]), 12)

    def test_telegram_handlers_defines_no_authorization_import(self):
        with open("business_core/telegram_handlers.py") as f:
            content = f.read()
        self.assertNotIn("business_core.authorization", content)
        self.assertNotIn("from business_core import authorization", content)


if __name__ == "__main__":
    unittest.main()
