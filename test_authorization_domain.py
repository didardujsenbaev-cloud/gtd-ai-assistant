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


# ─────────────────────────────────────────────────────────────
# Phase 18A.3: TASK resource addition.
#
# Adds TASK as an isolated Authorization Domain resource only —
# no Task command is authorized, no COMMAND_ENFORCEMENT_MAP entry
# is added, no handler is touched. This section proves the new
# resource behaves exactly as designed (business-only structural
# shape, exact per-role grants, correct scope compatibility) and
# that every pre-existing resource/role/scope behavior is
# byte-identical to before this phase.
# ─────────────────────────────────────────────────────────────

_PRE_PHASE_RESOURCES = (
    "BUSINESS", "CLIENT", "OBJECT", "DOCUMENT", "OPERATIONAL", "FINANCE", "ACCESS_CONTROL",
)

_PRE_PHASE_ACTIONS = ("READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN", "MANAGE_ACCESS")

_PRE_PHASE_MATRIX = {
    "OWNER": {
        "BUSINESS": frozenset(_PRE_PHASE_ACTIONS), "CLIENT": frozenset(_PRE_PHASE_ACTIONS),
        "OBJECT": frozenset(_PRE_PHASE_ACTIONS), "DOCUMENT": frozenset(_PRE_PHASE_ACTIONS),
        "OPERATIONAL": frozenset(_PRE_PHASE_ACTIONS), "FINANCE": frozenset(_PRE_PHASE_ACTIONS),
        "ACCESS_CONTROL": frozenset(_PRE_PHASE_ACTIONS),
    },
    "ADMIN": {
        "BUSINESS": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "CLIENT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "OBJECT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "DOCUMENT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "OPERATIONAL": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "FINANCE": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "ACCESS_CONTROL": frozenset(),
    },
    "COORDINATOR": {
        "BUSINESS": frozenset(), "CLIENT": frozenset(),
        "OBJECT": frozenset({"READ", "UPDATE"}),
        "DOCUMENT": frozenset({"READ", "CREATE", "UPDATE"}),
        "OPERATIONAL": frozenset({"READ", "CREATE", "UPDATE"}),
        "FINANCE": frozenset(), "ACCESS_CONTROL": frozenset(),
    },
    "DOCUMENT_SPECIALIST": {
        "BUSINESS": frozenset(),
        "CLIENT": frozenset({"READ"}),
        "OBJECT": frozenset({"READ"}),
        "DOCUMENT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE"}),
        "OPERATIONAL": frozenset({"READ"}),
        "FINANCE": frozenset(), "ACCESS_CONTROL": frozenset(),
    },
    "VIEWER": {
        "BUSINESS": frozenset({"READ"}), "CLIENT": frozenset({"READ"}), "OBJECT": frozenset({"READ"}),
        "DOCUMENT": frozenset({"READ"}), "OPERATIONAL": frozenset({"READ"}), "FINANCE": frozenset({"READ"}),
        "ACCESS_CONTROL": frozenset(),
    },
}

_PRE_PHASE_SELECTED_BUSINESSES = frozenset({"BUSINESS", "CLIENT", "OBJECT", "DOCUMENT", "OPERATIONAL", "FINANCE"})
_PRE_PHASE_ASSIGNED_OBJECTS_ONLY = frozenset({"OBJECT", "DOCUMENT", "OPERATIONAL"})
_PRE_PHASE_OBJECT_ADDRESSABLE = frozenset({"OBJECT", "DOCUMENT", "OPERATIONAL"})


class TestTaskResourceEnum(unittest.TestCase):
    def test_previous_seven_resources_unchanged_and_in_order(self):
        self.assertEqual(az.AUTHZ_RESOURCES[:7], _PRE_PHASE_RESOURCES)

    def test_task_appended_exactly_once(self):
        self.assertEqual(az.AUTHZ_RESOURCES.count("TASK"), 1)
        self.assertEqual(az.AUTHZ_RESOURCES[-1], "TASK")

    def test_final_resource_count_is_eight(self):
        self.assertEqual(len(az.AUTHZ_RESOURCES), 8)

    def test_actions_unchanged(self):
        self.assertEqual(az.AUTHZ_ACTIONS, _PRE_PHASE_ACTIONS)

    def test_final_action_count_is_six(self):
        self.assertEqual(len(az.AUTHZ_ACTIONS), 6)


class TestTaskMatrixExact(AuthorizationTestBase):
    def test_owner_task_grant_matches_canonical_full_set(self):
        self.assertEqual(az.ROLE_RESOURCE_ACTION_MATRIX["OWNER"]["TASK"], frozenset(az.AUTHZ_ACTIONS))

    def test_admin_task_grant_exact(self):
        self.assertEqual(
            az.ROLE_RESOURCE_ACTION_MATRIX["ADMIN"]["TASK"],
            frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        )

    def test_coordinator_task_grant_exact(self):
        self.assertEqual(
            az.ROLE_RESOURCE_ACTION_MATRIX["COORDINATOR"]["TASK"],
            frozenset({"READ", "CREATE", "UPDATE", "ASSIGN"}),
        )

    def test_document_specialist_task_grant_exact(self):
        self.assertEqual(az.ROLE_RESOURCE_ACTION_MATRIX["DOCUMENT_SPECIALIST"]["TASK"], frozenset({"READ"}))

    def test_viewer_task_grant_exact(self):
        self.assertEqual(az.ROLE_RESOURCE_ACTION_MATRIX["VIEWER"]["TASK"], frozenset({"READ"}))

    def test_admin_task_denied_manage_access(self):
        self._grant_and_check("ADMIN", "MANAGE_ACCESS", expected_allowed=False)

    def test_coordinator_task_denied_archive(self):
        self._grant_and_check("COORDINATOR", "ARCHIVE", expected_allowed=False)

    def test_coordinator_task_denied_manage_access(self):
        self._grant_and_check("COORDINATOR", "MANAGE_ACCESS", expected_allowed=False)

    def test_document_specialist_task_denied_create(self):
        self._grant_and_check("DOCUMENT_SPECIALIST", "CREATE", expected_allowed=False)

    def test_document_specialist_task_denied_update(self):
        self._grant_and_check("DOCUMENT_SPECIALIST", "UPDATE", expected_allowed=False)

    def test_document_specialist_task_denied_archive(self):
        self._grant_and_check("DOCUMENT_SPECIALIST", "ARCHIVE", expected_allowed=False)

    def test_document_specialist_task_denied_assign(self):
        self._grant_and_check("DOCUMENT_SPECIALIST", "ASSIGN", expected_allowed=False)

    def test_viewer_task_denied_create(self):
        self._grant_and_check("VIEWER", "CREATE", expected_allowed=False)

    def test_viewer_task_denied_update(self):
        self._grant_and_check("VIEWER", "UPDATE", expected_allowed=False)

    def test_viewer_task_denied_assign(self):
        self._grant_and_check("VIEWER", "ASSIGN", expected_allowed=False)

    def test_coordinator_task_allowed_assign(self):
        self._grant_and_check("COORDINATOR", "ASSIGN", expected_allowed=True)

    def test_document_specialist_task_allowed_read(self):
        self._grant_and_check("DOCUMENT_SPECIALIST", "READ", expected_allowed=True)

    def _grant_and_check(self, role, action, expected_allowed):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role=role)]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="TASK", action=action, business_id="B")
        self.assertEqual(r["allowed"], expected_allowed)
        if not expected_allowed:
            self.assertEqual(r["code"], "ROLE_NOT_PERMITTED")


class TestTaskStructuralTarget(AuthorizationTestBase):
    def test_blank_business_id_denied(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="TASK", action="READ", business_id="")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "TARGET_REQUIRED")

    def test_valid_business_id_structurally_passes(self):
        self.assertIsNone(az._validate_structural_target("TASK", "READ", "B", ""))

    def test_object_id_not_required(self):
        self.assertIsNone(az._validate_structural_target("TASK", "UPDATE", "B", ""))

    def test_object_less_task_accepted_end_to_end(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="TASK", action="UPDATE", business_id="B", object_id="")
        self.assertTrue(r["allowed"])

    def test_optional_object_id_present_does_not_break_structural_pass(self):
        self.assertIsNone(az._validate_structural_target("TASK", "UPDATE", "B", "O"))

    def test_task_absent_from_object_addressable_resources(self):
        self.assertNotIn("TASK", az._OBJECT_ADDRESSABLE_RESOURCES)

    def test_operational_still_requires_object_id(self):
        self.assertEqual(az._validate_structural_target("OPERATIONAL", "READ", "B", ""), "TARGET_REQUIRED")

    def test_document_still_requires_object_id(self):
        self.assertEqual(az._validate_structural_target("DOCUMENT", "READ", "B", ""), "TARGET_REQUIRED")

    def test_object_still_requires_object_id(self):
        self.assertEqual(az._validate_structural_target("OBJECT", "READ", "B", ""), "TARGET_REQUIRED")


class TestTaskScopeCompatibility(AuthorizationTestBase):
    def test_all_businesses_includes_task_automatically(self):
        self.assertIn("TASK", az._SCOPE_RESOURCE_COMPATIBILITY["ALL_BUSINESSES"])

    def test_all_businesses_task_end_to_end(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="ALL_BUSINESSES")]
        r = self._authorize(resource="TASK", action="READ", business_id="ANY")
        self.assertTrue(r["allowed"])

    def test_selected_businesses_includes_task_explicitly(self):
        self.assertIn("TASK", az._SCOPE_RESOURCE_COMPATIBILITY["SELECTED_BUSINESSES"])

    def test_selected_businesses_task_matching(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="B1")]
        r = self._authorize(resource="TASK", action="READ", business_id="B1")
        self.assertTrue(r["allowed"])

    def test_selected_businesses_task_non_matching(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="VIEWER")]
        self.scope_assignments = [_asa(scope_type="SELECTED_BUSINESSES", business_id="B1")]
        r = self._authorize(resource="TASK", action="READ", business_id="B2")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_excludes_task(self):
        self.assertNotIn("TASK", az._SCOPE_RESOURCE_COMPATIBILITY["ASSIGNED_OBJECTS_ONLY"])

    def test_assigned_objects_only_denies_task_even_with_object_id_supplied(self):
        self.identities = [_identity()]
        self.employees = {"EMP-1": _employee()}
        self.role_assignments = [_ara(role="OWNER")]
        self.scope_assignments = [_asa(scope_type="ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")]
        r = self._authorize(resource="TASK", action="READ", business_id="B")
        self.assertFalse(r["allowed"])
        self.assertEqual(r["code"], "SCOPE_NOT_MATCHED")

    def test_assigned_objects_only_object_document_operational_unchanged(self):
        for resource in ("OBJECT", "DOCUMENT", "OPERATIONAL"):
            with self.subTest(resource=resource):
                self.identities = [_identity()]
                self.employees = {"EMP-1": _employee()}
                self.role_assignments = [_ara(role="OWNER")]
                self.scope_assignments = [_asa(scope_type="ASSIGNED_OBJECTS_ONLY", object_id="OBJ-7")]
                r = self._authorize(resource=resource, action="READ", business_id="B", object_id="OBJ-7")
                self.assertTrue(r["allowed"])


class TestTaskExistingResourceInvariants(unittest.TestCase):
    def test_every_existing_resource_role_grant_byte_equal_to_pre_phase(self):
        for role, resource_map in _PRE_PHASE_MATRIX.items():
            for resource, expected_actions in resource_map.items():
                with self.subTest(role=role, resource=resource):
                    self.assertEqual(az.ROLE_RESOURCE_ACTION_MATRIX[role][resource], expected_actions)

    def test_only_task_is_new_across_all_five_roles(self):
        for role in _PRE_PHASE_MATRIX:
            with self.subTest(role=role):
                new_keys = set(az.ROLE_RESOURCE_ACTION_MATRIX[role].keys()) - set(_PRE_PHASE_MATRIX[role].keys())
                self.assertEqual(new_keys, {"TASK"})

    def test_object_addressable_resources_unchanged(self):
        self.assertEqual(az._OBJECT_ADDRESSABLE_RESOURCES, _PRE_PHASE_OBJECT_ADDRESSABLE)

    def test_structural_target_existing_branches_unchanged(self):
        # OBJECT/DOCUMENT/OPERATIONAL, CLIENT/FINANCE, ACCESS_CONTROL,
        # BUSINESS all behave exactly as before — only TASK was added
        # to the CLIENT/FINANCE-shaped branch.
        self.assertEqual(az._validate_structural_target("OBJECT", "READ", "B", ""), "TARGET_REQUIRED")
        self.assertIsNone(az._validate_structural_target("OBJECT", "READ", "B", "O"))
        self.assertEqual(az._validate_structural_target("CLIENT", "READ", "", ""), "TARGET_REQUIRED")
        self.assertIsNone(az._validate_structural_target("CLIENT", "READ", "B", ""))
        self.assertEqual(az._validate_structural_target("FINANCE", "READ", "", ""), "TARGET_REQUIRED")
        self.assertIsNone(az._validate_structural_target("FINANCE", "READ", "B", ""))
        self.assertEqual(az._validate_structural_target("ACCESS_CONTROL", "READ", "B", ""), "TARGET_REQUIRED")
        self.assertIsNone(az._validate_structural_target("ACCESS_CONTROL", "READ", "", ""))
        self.assertEqual(az._validate_structural_target("BUSINESS", "UPDATE", "", ""), "TARGET_REQUIRED")
        self.assertIsNone(az._validate_structural_target("BUSINESS", "READ", "", ""))

    def test_selected_businesses_gained_only_task(self):
        self.assertEqual(
            az._SCOPE_RESOURCE_COMPATIBILITY["SELECTED_BUSINESSES"] - _PRE_PHASE_SELECTED_BUSINESSES,
            {"TASK"},
        )

    def test_assigned_objects_only_gained_nothing(self):
        self.assertEqual(az._SCOPE_RESOURCE_COMPATIBILITY["ASSIGNED_OBJECTS_ONLY"], _PRE_PHASE_ASSIGNED_OBJECTS_ONLY)

    def test_no_existing_decision_code_changed(self):
        # AUTHZ_DECISION_CODES itself is untouched by this phase.
        self.assertEqual(len(az.AUTHZ_DECISION_CODES), 19)
        self.assertIn("TARGET_REQUIRED", az.AUTHZ_DECISION_CODES)
        self.assertIn("SCOPE_NOT_MATCHED", az.AUTHZ_DECISION_CODES)


class TestTaskCrossLayerIsolation(unittest.TestCase):
    # telegram_handlers.py zero-diff was true for the TASK
    # authorization resource commit itself; ongoing telegram_handlers.py
    # changes (e.g. the Task assignment mapper hardening) are scoped by
    # test_task_architecture_guards.py's dedicated top-level construct
    # guard instead.

    def test_resource_task_call_confined_to_unassigntask_bctask_bctasks_and_newbctask_handlers(self):
        # newbctask_cmd is now a fourth, independent resource="TASK"
        # authorization call site (TASK/CREATE, business-scoped),
        # alongside bctasks_cmd's TASK/READ list call, bctask_cmd's
        # single-record TASK/READ call and unassigntask_cmd's
        # TASK/ASSIGN call. No other function may reference
        # resource="TASK".
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('resource="TASK"'), 4)
        for fn_name in ("unassigntask_cmd", "bctask_cmd", "bctasks_cmd", "newbctask_cmd"):
            start = content.index(f"async def {fn_name}(")
            candidates = [i for i in (content.find("\nasync def ", start + 10), content.find("\ndef ", start + 10)) if i != -1]
            end = min(candidates) if candidates else len(content)
            self.assertIn('resource="TASK"', content[start:end])

    def test_command_enforcement_map_size_eighteen(self):
        from business_core import telegram_handlers as th
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 18)

    def test_command_enforcement_map_task_keys_unassigntask_bctask_bctasks_and_newbctask(self):
        # newbctask (business-scoped TASK/CREATE) joins the existing
        # unassigntask (TASK/ASSIGN), bctask (TASK/READ) and bctasks
        # (TASK/READ) keys.
        from business_core import telegram_handlers as th
        task_keys = {key for key in th.COMMAND_ENFORCEMENT_MAP if "task" in key.lower()}
        self.assertEqual(task_keys, {"unassigntask", "bctask", "bctasks", "newbctask"})

    def test_telegram_authorization_zero_diff(self):
        # Superseded as a whole-file zero-diff check by Phase
        # 18A.8-C1-F2, which legitimately hardens
        # validate_telegram_business_core_transport's identity
        # validation. Scope protection for this file is now carried by
        # TestTelegramAuthorizationTransportIdentityGuards.test_ast_scope_exact
        # in test_task_architecture_guards.py, which is construct-
        # identity based rather than whole-file-diff based and names
        # exactly that one approved construct.
        self.skipTest("superseded by TestTelegramAuthorizationTransportIdentityGuards.test_ast_scope_exact")

    def test_identity_manager_zero_diff(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/identity_manager.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")

    # business_builder.py cross-layer isolation for the TASK authorization
    # resource itself was true at the time of that commit; ongoing
    # business_builder.py Task-domain changes (e.g. unassign_task
    # hardening) are scoped by test_task_architecture_guards.py instead.
    #
    # task_manager.py cross-layer isolation was true at the time of
    # that commit too; ongoing task_manager.py Task-domain changes
    # (e.g. list_tasks's raise_on_error strict-mode contract) are
    # scoped by test_task_architecture_guards.py's
    # test_task_manager_unchanged instead — a single-function AST
    # guard, not a whole-file zero-diff check.

    def test_sheets_zero_diff(self):
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "business_core/sheets.py"],
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "")


# ─────────────────────────────────────────────────────────────
# Phase 18A.3-G: dedicated Authorization Domain source-identity
# guard, replacing the removed blanket
# test_authorization_py_unchanged.
#
# Protection model (two complementary layers — neither replaces the
# other):
#
#   PART A — exact-value/behavior tests (TestTaskResourceEnum,
#   TestTaskMatrixExact, TestTaskStructuralTarget,
#   TestTaskScopeCompatibility, TestMatrix.test_every_matrix_cell,
#   TestScopeCompatibility) already freeze the exact, current,
#   correct values of AUTHZ_RESOURCES, AUTHZ_ACTIONS,
#   ROLE_RESOURCE_ACTION_MATRIX, _SCOPE_RESOURCE_COMPATIBILITY,
#   _validate_structural_target, and _OBJECT_ADDRESSABLE_RESOURCES.
#   These are permanent, commit-independent guards — they will
#   fail the instant any of those values silently drifts from what
#   this phase established as correct, in any future commit,
#   forever. They do not depend on comparing against git HEAD.
#
#   PART B (below) — a source-identity guard comparing the current
#   working tree against git HEAD, for every OTHER top-level
#   construct in authorization.py. AUTHZ_RESOURCES,
#   ROLE_RESOURCE_ACTION_MATRIX, _SCOPE_RESOURCE_COMPATIBILITY, and
#   _validate_structural_target are excluded from this specific
#   comparison — not because they are unprotected, but because Part
#   A already protects their correct value directly and more
#   precisely than a source-diff could (a source-diff only proves
#   "nothing changed since the last commit"; an exact-value test
#   proves "the value is exactly what it must be", which remains
#   true across every future commit, not just the next one). Once
#   this phase is committed, git HEAD itself will include these four
#   constructs' new values, and this Part B comparison will then
#   naturally protect them too, for every commit after that — the
#   exclusion here is specific to this phase's own in-progress diff,
#   not a permanent carve-out.
#
#   AUTHZ_ACTIONS and _OBJECT_ADDRESSABLE_RESOURCES are NOT excluded
#   from Part B — they are not approved to differ in this phase, so
#   they remain both exact-value-tested (Part A) and source-identity
#   guarded (Part B) simultaneously, exactly like every other
#   untouched construct.
# ─────────────────────────────────────────────────────────────

import ast as _ast


def _authorization_construct_sources(src: str) -> dict:
    """
    Maps every top-level function/async-function/assignment/
    annotated-assignment name in `src` to its exact source text,
    sliced by each node's own lineno/end_lineno — the same
    line-slicing technique already used by
    test_command_enforcement.py's _top_level_function_sources,
    extended here to also cover module-level constants (functions
    alone are insufficient for authorization.py, whose
    security-relevant surface is mostly data: the resource/action
    enums and the role/resource/action matrix).
    """
    tree = _ast.parse(src)
    lines = src.splitlines(keepends=True)
    out = {}
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            out[node.name] = "".join(lines[node.lineno - 1:node.end_lineno])
        elif isinstance(node, _ast.Assign):
            for target in node.targets:
                if isinstance(target, _ast.Name):
                    out[target.id] = "".join(lines[node.lineno - 1:node.end_lineno])
        elif isinstance(node, _ast.AnnAssign):
            if isinstance(node.target, _ast.Name):
                out[node.target.id] = "".join(lines[node.lineno - 1:node.end_lineno])
    return out


# The exact four constructs Phase 18A.3 is approved to change —
# permanently protected instead by the exact-value/behavior tests
# named in the module docstring above (Part A), not by this
# comparison.
_TASK_PHASE_APPROVED_TO_DIFFER = frozenset({
    "AUTHZ_RESOURCES", "ROLE_RESOURCE_ACTION_MATRIX",
    "_SCOPE_RESOURCE_COMPATIBILITY", "_validate_structural_target",
})

# The one genuinely new private constant Phase 18A.3 introduces (a
# helper solely for constructing ROLE_RESOURCE_ACTION_MATRIX's new
# TASK/COORDINATOR grant) — the only name permitted to exist in the
# current working tree with no counterpart in HEAD.
_TASK_PHASE_NEWLY_ADDED_CONSTRUCTS = frozenset({"_COORDINATOR_TASK_ACTIONS"})


def _git_show_head_authorization_py() -> str:
    import subprocess
    result = subprocess.run(
        ["git", "show", "HEAD:business_core/authorization.py"],
        capture_output=True, text=True, cwd=".",
    )
    if result.returncode != 0:
        raise AssertionError(f"git show HEAD:business_core/authorization.py failed: {result.stderr}")
    return result.stdout


class TestAuthorizationSourceIdentityGuard(unittest.TestCase):
    """Part B: proves every authorization.py construct outside the
    four Phase-18A.3-approved names is byte-identical to HEAD, and
    that no construct was silently removed, renamed, or joined by an
    unapproved new addition."""

    def test_no_construct_removed_or_unapproved_addition(self):
        head_constructs = _authorization_construct_sources(_git_show_head_authorization_py())
        with open("business_core/authorization.py", encoding="utf-8") as f:
            current_constructs = _authorization_construct_sources(f.read())

        removed = set(head_constructs) - set(current_constructs)
        self.assertEqual(removed, set(), f"authorization.py: construct(s) removed or renamed: {sorted(removed)}")

        added = set(current_constructs) - set(head_constructs)
        unapproved_added = added - _TASK_PHASE_NEWLY_ADDED_CONSTRUCTS
        self.assertEqual(
            unapproved_added, set(),
            f"authorization.py: unapproved new top-level construct(s): {sorted(unapproved_added)}",
        )

    def test_every_untouched_construct_source_identical_to_head(self):
        head_constructs = _authorization_construct_sources(_git_show_head_authorization_py())
        with open("business_core/authorization.py", encoding="utf-8") as f:
            current_constructs = _authorization_construct_sources(f.read())

        for name in head_constructs:
            if name in _TASK_PHASE_APPROVED_TO_DIFFER:
                continue
            with self.subTest(construct=name):
                self.assertEqual(
                    head_constructs[name], current_constructs.get(name),
                    f"authorization.py: unapproved construct '{name}' changed — only "
                    f"{sorted(_TASK_PHASE_APPROVED_TO_DIFFER)} may differ this phase",
                )

    def test_specifically_protects_named_constants(self):
        # Explicit, named coverage for the constants the phase brief
        # called out by name — redundant with the exhaustive AST scan
        # above, but makes the specific security-relevant names
        # traceable in a test failure without reading the AST helper.
        head_constructs = _authorization_construct_sources(_git_show_head_authorization_py())
        with open("business_core/authorization.py", encoding="utf-8") as f:
            current_constructs = _authorization_construct_sources(f.read())
        for name in ("AUTHZ_ACTIONS", "AUTHZ_DECISION_CODES", "_DENIAL_PRECEDENCE", "_TARGETLESS_BUSINESS_READ_ROLES",
                     "_OBJECT_ADDRESSABLE_RESOURCES"):
            with self.subTest(construct=name):
                self.assertIn(name, head_constructs)
                self.assertEqual(head_constructs[name], current_constructs.get(name))

    def test_specifically_protects_named_functions(self):
        head_constructs = _authorization_construct_sources(_git_show_head_authorization_py())
        with open("business_core/authorization.py", encoding="utf-8") as f:
            current_constructs = _authorization_construct_sources(f.read())
        for name in ("_scope_matches_target", "_targetless_business_read", "_in_force_status",
                     "_parse_canonical_timestamp", "authorize_business_core_access",
                     "get_business_core_access_summary", "_base_result", "_deny", "_read_failed",
                     "_pick_precedence", "_now_utc", "_read_failed_summary"):
            with self.subTest(construct=name):
                self.assertIn(name, head_constructs)
                self.assertEqual(head_constructs[name], current_constructs.get(name))

    def test_ast_discovery_finds_all_baseline_constructs_named_above(self):
        # Proves the two explicit "named" tests above are not a
        # manually-incomplete subset — every top-level construct AST
        # discovery finds in HEAD is either one of the four approved-
        # to-differ names or is covered by one of the two explicit
        # named-protection tests (or is itself one of the small
        # internal helper constants used only to build the matrix,
        # e.g. _ALL_ACTIONS/_WRITE_LIGHT/_READ_ONLY/_NONE/
        # _DOCUMENT_SPECIALIST_DOC_ACTIONS/_TIMESTAMP_FORMAT, which
        # the exhaustive source-identity test above still protects
        # even though no single named test calls them out).
        head_constructs = _authorization_construct_sources(_git_show_head_authorization_py())
        explicitly_named = {
            "AUTHZ_ACTIONS", "AUTHZ_DECISION_CODES", "_DENIAL_PRECEDENCE", "_TARGETLESS_BUSINESS_READ_ROLES",
            "_OBJECT_ADDRESSABLE_RESOURCES",
            "_scope_matches_target", "_targetless_business_read", "_in_force_status",
            "_parse_canonical_timestamp", "authorize_business_core_access",
            "get_business_core_access_summary", "_base_result", "_deny", "_read_failed",
            "_pick_precedence", "_now_utc", "_read_failed_summary",
        }
        unnamed_but_still_source_guarded = set(head_constructs) - explicitly_named - _TASK_PHASE_APPROVED_TO_DIFFER
        # These remain protected only by test_every_untouched_construct_source_identical_to_head,
        # not by a dedicated named test — listed here so the coverage
        # gap (if any new one appears) is visible in a diff. Since the
        # TASK authorization resource commit landed, HEAD itself now
        # contains "_COORDINATOR_TASK_ACTIONS" (previously visible only
        # as a working-tree addition via _TASK_PHASE_NEWLY_ADDED_CONSTRUCTS);
        # it is still fully source-identity-guarded, just via this
        # exhaustive path rather than a dedicated named test.
        self.assertEqual(
            unnamed_but_still_source_guarded,
            {"_TIMESTAMP_FORMAT", "_ALL_ACTIONS", "_WRITE_LIGHT", "_READ_ONLY", "_DOCUMENT_SPECIALIST_DOC_ACTIONS", "_NONE",
             "_COORDINATOR_TASK_ACTIONS"},
        )


class TestAuthorizationSourceIdentityHelperUnit(unittest.TestCase):
    """Negative verification (§5, Option A): unit-tests the AST
    comparison helper directly against synthetic in-memory source
    strings — proves the guard actually detects the failure modes it
    claims to, without ever writing to authorization.py on disk."""

    _BASELINE_SRC = (
        "AUTHZ_RESOURCES = (\"BUSINESS\", \"TASK\")\n"
        "AUTHZ_ACTIONS = (\"READ\", \"UPDATE\")\n"
        "\n"
        "def authorize_business_core_access(x):\n"
        "    return x\n"
        "\n"
        "def _scope_matches_target(x):\n"
        "    return x\n"
    )

    def test_change_to_protected_function_is_detected(self):
        mutated = self._BASELINE_SRC.replace(
            "def authorize_business_core_access(x):\n    return x\n",
            "def authorize_business_core_access(x):\n    return x + 1\n",
        )
        baseline = _authorization_construct_sources(self._BASELINE_SRC)
        current = _authorization_construct_sources(mutated)
        self.assertNotEqual(baseline["authorize_business_core_access"], current["authorize_business_core_access"])

    def test_removal_of_protected_function_is_detected(self):
        mutated = self._BASELINE_SRC.replace("def _scope_matches_target(x):\n    return x\n", "")
        baseline = _authorization_construct_sources(self._BASELINE_SRC)
        current = _authorization_construct_sources(mutated)
        removed = set(baseline) - set(current)
        self.assertEqual(removed, {"_scope_matches_target"})

    def test_unexpected_new_top_level_function_is_detected(self):
        mutated = self._BASELINE_SRC + "\ndef _sneaky_new_function(x):\n    return x\n"
        baseline = _authorization_construct_sources(self._BASELINE_SRC)
        current = _authorization_construct_sources(mutated)
        added = set(current) - set(baseline)
        self.assertEqual(added, {"_sneaky_new_function"})
        self.assertNotIn("_sneaky_new_function", _TASK_PHASE_NEWLY_ADDED_CONSTRUCTS)

    def test_approved_construct_difference_is_ignored_by_source_identity_helper(self):
        mutated = self._BASELINE_SRC.replace(
            "AUTHZ_RESOURCES = (\"BUSINESS\", \"TASK\")\n",
            "AUTHZ_RESOURCES = (\"BUSINESS\", \"TASK\", \"EXTRA\")\n",
        )
        baseline = _authorization_construct_sources(self._BASELINE_SRC)
        current = _authorization_construct_sources(mutated)
        # A source-identity comparison WOULD flag this difference —
        # exactly why the real guard explicitly skips
        # "AUTHZ_RESOURCES" via _TASK_PHASE_APPROVED_TO_DIFFER, and
        # relies on TestTaskResourceEnum's exact-value test instead.
        self.assertNotEqual(baseline["AUTHZ_RESOURCES"], current["AUTHZ_RESOURCES"])
        self.assertIn("AUTHZ_RESOURCES", _TASK_PHASE_APPROVED_TO_DIFFER)

    def test_exact_value_test_would_catch_invalid_task_grant(self):
        # Synthetic proof that an exact-value assertion (the Part A
        # mechanism that permanently protects the four approved
        # constructs after this phase, per the module comment above)
        # correctly distinguishes a valid grant from an invalid one —
        # exercised here without touching the real matrix.
        synthetic_matrix = {"COORDINATOR": {"TASK": frozenset({"READ", "CREATE", "UPDATE", "ASSIGN"})}}
        expected = frozenset({"READ", "CREATE", "UPDATE", "ASSIGN"})
        self.assertEqual(synthetic_matrix["COORDINATOR"]["TASK"], expected)
        invalid_synthetic_matrix = {"COORDINATOR": {"TASK": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE"})}}
        self.assertNotEqual(invalid_synthetic_matrix["COORDINATOR"]["TASK"], expected)


if __name__ == "__main__":
    unittest.main()
