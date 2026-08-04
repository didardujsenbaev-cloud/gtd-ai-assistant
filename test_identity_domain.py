"""
Phase 17B — Identity & Access Control Foundation: domain-manager tests.

Covers business_core/identity_manager.py (Employee lifecycle, Telegram
Identity binding, Access Role/Scope Assignments) and
business_core/business_builder.bootstrap_owner_from_env(). No live
Google Sheets access — mocks only.
"""

from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import MagicMock, patch

import business_core.identity_manager as im


def _make_sheet(headers, row_num=2):
    sheet = MagicMock()
    sheet.row_values.return_value = headers
    return sheet


def _patch_new_id(new_id):
    return patch("business_core.sheets.generate_next_id", return_value=new_id)


# ────────────────────────────────────────────────────────────
# Validation helpers
# ────────────────────────────────────────────────────────────

class TestValidationHelpers(unittest.TestCase):
    def test_numeric_string_valid(self):
        self.assertTrue(im.is_valid_telegram_user_id("12345"))

    def test_numeric_int_valid(self):
        self.assertTrue(im.is_valid_telegram_user_id(12345))

    def test_float_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id("123.45"))
        self.assertFalse(im.is_valid_telegram_user_id(123.45))

    def test_scientific_notation_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id("1e10"))

    def test_negative_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id("-5"))
        self.assertFalse(im.is_valid_telegram_user_id(-5))

    def test_empty_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id(""))
        self.assertFalse(im.is_valid_telegram_user_id(None))

    def test_bool_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id(True))

    def test_username_string_rejected(self):
        self.assertFalse(im.is_valid_telegram_user_id("didar"))

    def test_canonical_actor_format(self):
        self.assertEqual(im.canonical_telegram_actor("12345"), "telegram:12345")
        self.assertEqual(im.canonical_telegram_actor(12345), "telegram:12345")

    def test_canonical_actor_invalid_raises(self):
        with self.assertRaises(ValueError):
            im.canonical_telegram_actor("bad")

    def test_role_enum(self):
        self.assertEqual(im.ACCESS_ROLES, ("OWNER", "ADMIN", "COORDINATOR", "DOCUMENT_SPECIALIST", "VIEWER"))
        self.assertTrue(im.is_valid_access_role("VIEWER"))
        self.assertFalse(im.is_valid_access_role("SALES"))

    def test_scope_type_enum(self):
        self.assertEqual(im.ACCESS_SCOPE_TYPES, ("ALL_BUSINESSES", "SELECTED_BUSINESSES", "ASSIGNED_OBJECTS_ONLY"))
        self.assertTrue(im.is_valid_scope_type("ALL_BUSINESSES"))
        self.assertFalse(im.is_valid_scope_type("CITY"))


# ────────────────────────────────────────────────────────────
# Employee lifecycle
# ────────────────────────────────────────────────────────────

EMPLOYEE_HEADERS = [
    "Employee ID", "Person ID", "Display Label", "Status",
    "Created At", "Created By", "Activated At", "Activated By",
    "Disabled At", "Disabled By", "Disable Reason", "Notes",
]


def _employee_dict(**overrides):
    d = {
        "employee_id": "EMP-001", "person_id": "", "display_label": "", "status": "pending",
        "created_at": "2026-01-01 00:00:00 UTC", "created_by": "telegram:1",
        "activated_at": "", "activated_by": "", "disabled_at": "", "disabled_by": "",
        "disable_reason": "", "notes": "",
    }
    d.update(overrides)
    return d


class TestEmployeeLifecycle(unittest.TestCase):
    def test_create_pending_employee(self):
        sheet = _make_sheet(EMPLOYEE_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             _patch_new_id("EMP-001"), \
             patch("business_core.sheets.append_business_row"), \
             patch.object(im, "find_employee", return_value=_employee_dict(status="pending", created_by="telegram:1")):
            result = im.create_pending_employee(created_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_CREATED")
        self.assertEqual(result["employee_id"], "EMP-001")

    def test_create_pending_employee_requires_created_by(self):
        result = im.create_pending_employee(created_by="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CREATED_BY_REQUIRED")

    def test_create_post_write_verification_failure(self):
        sheet = _make_sheet(EMPLOYEE_HEADERS)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             _patch_new_id("EMP-001"), \
             patch("business_core.sheets.append_business_row"), \
             patch.object(im, "find_employee", return_value=None):
            result = im.create_pending_employee(created_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_activate_pending_to_active(self):
        with patch.object(im, "find_employee", side_effect=[_employee_dict(status="pending"), _employee_dict(status="active")]), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.sheets.update_business_row"):
            result = im.activate_employee("EMP-001", activated_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "EMPLOYEE_ACTIVE")

    def test_activate_already_active_is_noop(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")):
            result = im.activate_employee("EMP-001", activated_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "EMPLOYEE_ALREADY_ACTIVE")

    def test_disable_requires_reason(self):
        result = im.disable_employee("EMP-001", reason="", disabled_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DISABLE_REASON_REQUIRED")

    def test_disable_whitespace_reason_rejected(self):
        result = im.disable_employee("EMP-001", reason="   ", disabled_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DISABLE_REASON_REQUIRED")

    def test_disable_active_to_disabled(self):
        with patch.object(im, "find_employee", side_effect=[_employee_dict(status="active"), _employee_dict(status="disabled")]), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.sheets.update_business_row"):
            result = im.disable_employee("EMP-001", reason="left company", disabled_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "EMPLOYEE_DISABLED")

    def test_disable_already_disabled_is_noop(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="disabled")):
            result = im.disable_employee("EMP-001", reason="x", disabled_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "EMPLOYEE_ALREADY_DISABLED")

    def test_reactivate_disabled_to_active(self):
        with patch.object(im, "find_employee", side_effect=[_employee_dict(status="disabled"), _employee_dict(status="active")]), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.sheets.update_business_row"):
            result = im.reactivate_employee("EMP-001", activated_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_ACTIVE")

    def test_reactivate_from_pending_is_invalid_transition(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="pending")):
            result = im.reactivate_employee("EMP-001", activated_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_EMPLOYEE_TRANSITION")

    def test_activate_not_found(self):
        with patch.object(im, "find_employee", return_value=None):
            result = im.activate_employee("EMP-999", activated_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_NOT_FOUND")

    def test_disable_post_write_verification_failure(self):
        with patch.object(im, "find_employee", side_effect=[_employee_dict(status="active"), _employee_dict(status="active")]), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {})), \
             patch("business_core.sheets.update_business_row"):
            result = im.disable_employee("EMP-001", reason="x", disabled_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_activate_requires_actor(self):
        result = im.activate_employee("EMP-001", activated_by="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ACTOR_REQUIRED")

    def test_no_last_authorized_or_denied_fields_written(self):
        source = inspect.getsource(im)
        self.assertNotIn("Last Authorized At", source)
        self.assertNotIn("Last Denied At", source)


# ────────────────────────────────────────────────────────────
# Telegram identity
# ────────────────────────────────────────────────────────────

TG_HEADERS = [
    "Telegram Identity ID", "Employee ID", "Telegram User ID", "Telegram Actor",
    "Status", "Linked At", "Linked By", "Revoked At", "Revoked By", "Revoke Reason",
]


def _tg_dict(**overrides):
    d = {
        "telegram_identity_id": "TGID-001", "employee_id": "EMP-001",
        "telegram_user_id": "555", "telegram_actor": "telegram:555",
        "status": "active", "linked_at": "2026-01-01 00:00:00 UTC", "linked_by": "telegram:1",
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }
    d.update(overrides)
    return d


class TestTelegramIdentity(unittest.TestCase):
    def test_link_numeric_validation(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")):
            result = im.link_telegram_identity("EMP-001", "not-numeric", linked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TELEGRAM_USER_ID_INVALID")

    def test_link_employee_not_found(self):
        with patch.object(im, "find_employee", return_value=None):
            result = im.link_telegram_identity("EMP-999", "555", linked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_NOT_FOUND")

    def test_link_success_stores_actor_and_text_id(self):
        sheet = _make_sheet(TG_HEADERS)
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_employee_by_telegram_user_id", return_value=None), \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=None), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             _patch_new_id("TGID-001"), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {
                 "Telegram Identity ID": "TGID-001", "Employee ID": "EMP-001",
                 "Telegram User ID": "555", "Telegram Actor": "telegram:555", "Status": "active",
                 "Linked At": "x", "Linked By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
             })):
            result = im.link_telegram_identity("EMP-001", 555, linked_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TELEGRAM_IDENTITY_LINKED")
        row = mock_append.call_args[0][1]
        idx = TG_HEADERS.index("Telegram User ID")
        self.assertEqual(row[idx], "555")
        self.assertIsInstance(row[idx], str)
        idx_actor = TG_HEADERS.index("Telegram Actor")
        self.assertEqual(row[idx_actor], "telegram:555")

    def test_link_active_telegram_id_uniqueness(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_employee_by_telegram_user_id", return_value=_employee_dict(employee_id="EMP-002")):
            result = im.link_telegram_identity("EMP-001", "555", linked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TELEGRAM_USER_ID_ALREADY_BOUND")

    def test_link_one_active_identity_per_employee(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_employee_by_telegram_user_id", return_value=None), \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tg_dict()):
            result = im.link_telegram_identity("EMP-001", "555", linked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EMPLOYEE_ALREADY_HAS_ACTIVE_IDENTITY")

    def test_caller_cannot_supply_actor(self):
        sig = inspect.signature(im.link_telegram_identity)
        self.assertNotIn("telegram_actor", sig.parameters)
        self.assertNotIn("actor", sig.parameters)

    def test_revoke_requires_reason(self):
        result = im.revoke_telegram_identity("TGID-001", reason="", revoked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REVOKE_REASON_REQUIRED")

    def test_revoke_active_identity(self):
        with patch("business_core.sheets.find_row_by_id", side_effect=[
            (2, {"Telegram Identity ID": "TGID-001", "Employee ID": "EMP-001", "Telegram User ID": "555",
                 "Telegram Actor": "telegram:555", "Status": "active", "Linked At": "x", "Linked By": "y",
                 "Revoked At": "", "Revoked By": "", "Revoke Reason": ""}),
            (2, {"Telegram Identity ID": "TGID-001", "Employee ID": "EMP-001", "Telegram User ID": "555",
                 "Telegram Actor": "telegram:555", "Status": "revoked", "Linked At": "x", "Linked By": "y",
                 "Revoked At": "z", "Revoked By": "telegram:1", "Revoke Reason": "left"}),
        ]), patch("business_core.sheets.update_business_row"):
            result = im.revoke_telegram_identity("TGID-001", reason="left", revoked_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TELEGRAM_IDENTITY_REVOKED")

    def test_revoke_already_revoked_is_noop(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {
            "Telegram Identity ID": "TGID-001", "Employee ID": "EMP-001", "Telegram User ID": "555",
            "Telegram Actor": "telegram:555", "Status": "revoked", "Linked At": "x", "Linked By": "y",
            "Revoked At": "z", "Revoked By": "w", "Revoke Reason": "prior",
        })):
            result = im.revoke_telegram_identity("TGID-001", reason="left", revoked_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "TELEGRAM_IDENTITY_ALREADY_REVOKED")

    def test_revoked_row_retained_not_reactivated(self):
        # There is no "reactivate" function for Telegram Identity at all —
        # a structural guard, not just a behavioral one.
        self.assertFalse(hasattr(im, "reactivate_telegram_identity"))

    def test_replacement_is_new_row(self):
        source = inspect.getsource(im.link_telegram_identity)
        self.assertIn("generate_next_id", source)


# ────────────────────────────────────────────────────────────
# Access Role Assignments
# ────────────────────────────────────────────────────────────

ARA_HEADERS = [
    "Access Role Assignment ID", "Employee ID", "Role", "Status",
    "Effective From", "Effective Until", "Assigned At", "Assigned By",
    "Revoked At", "Revoked By", "Revoke Reason",
]


class TestAccessRoleAssignments(unittest.TestCase):
    def test_invalid_role_rejected(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")):
            result = im.assign_access_role("EMP-001", "SALES", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_ROLE")

    def test_owner_generic_grant_denied(self):
        result = im.assign_access_role("EMP-001", "OWNER", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_ROLE_REQUIRES_AUTHORIZATION_DOMAIN")

    def test_owner_generic_revoke_denied(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {
            "Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "OWNER",
            "Status": "active", "Effective From": "", "Effective Until": "", "Assigned At": "x",
            "Assigned By": "system:owner_bootstrap", "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        })):
            result = im.revoke_access_role("ARA-001", reason="x", revoked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_ROLE_REQUIRES_AUTHORIZATION_DOMAIN")

    def test_assign_valid_role(self):
        sheet = _make_sheet(ARA_HEADERS)
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_active_role_assignments", return_value=[]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             _patch_new_id("ARA-001"), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {
                 "Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "VIEWER",
                 "Status": "active", "Effective From": "", "Effective Until": "", "Assigned At": "x",
                 "Assigned By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
             })):
            result = im.assign_access_role("EMP-001", "VIEWER", assigned_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ACCESS_ROLE_ASSIGNED")

    def test_duplicate_active_role_rejected(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_active_role_assignments", return_value=[{"role": "VIEWER"}]):
            result = im.assign_access_role("EMP-001", "VIEWER", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DUPLICATE_ACTIVE_ROLE_ASSIGNMENT")

    def test_multiple_different_roles_allowed(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch.object(im, "find_active_role_assignments", return_value=[{"role": "VIEWER"}]), \
             patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(ARA_HEADERS)), \
             _patch_new_id("ARA-002"), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, {
                 "Access Role Assignment ID": "ARA-002", "Employee ID": "EMP-001", "Role": "COORDINATOR",
                 "Status": "active", "Effective From": "", "Effective Until": "", "Assigned At": "x",
                 "Assigned By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
             })):
            result = im.assign_access_role("EMP-001", "COORDINATOR", assigned_by="telegram:1")
        self.assertTrue(result["ok"])

    def test_revoked_role_retained_and_regrant_is_new_row(self):
        source = inspect.getsource(im.assign_access_role)
        self.assertIn("generate_next_id", source)
        self.assertFalse(hasattr(im, "reactivate_access_role"))

    def test_role_revoke_requires_reason(self):
        result = im.revoke_access_role("ARA-001", reason="", revoked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REVOKE_REASON_REQUIRED")

    def test_revoke_non_owner_role_succeeds(self):
        with patch("business_core.sheets.find_row_by_id", side_effect=[
            (2, {"Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "VIEWER",
                 "Status": "active", "Effective From": "", "Effective Until": "", "Assigned At": "x",
                 "Assigned By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": ""}),
            (2, {"Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "VIEWER",
                 "Status": "revoked", "Effective From": "", "Effective Until": "", "Assigned At": "x",
                 "Assigned By": "telegram:1", "Revoked At": "z", "Revoked By": "telegram:1", "Revoke Reason": "x"}),
        ]), patch("business_core.sheets.update_business_row"):
            result = im.revoke_access_role("ARA-001", reason="x", revoked_by="telegram:1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ACCESS_ROLE_REVOKED")


# ────────────────────────────────────────────────────────────
# Access Scope Assignments
# ────────────────────────────────────────────────────────────

ASA_HEADERS = [
    "Access Scope Assignment ID", "Employee ID", "Access Role Assignment ID",
    "Scope Type", "Business ID", "Object ID", "Status",
    "Effective From", "Effective Until", "Assigned At", "Assigned By",
    "Revoked At", "Revoked By", "Revoke Reason",
]

ACTIVE_ARA_ROW = {
    "Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "COORDINATOR",
    "Status": "active", "Effective From": "", "Effective Until": "", "Assigned At": "x",
    "Assigned By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
}


class TestAccessScopeAssignments(unittest.TestCase):
    def test_all_businesses_rejects_target(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, ACTIVE_ARA_ROW)):
            result = im.assign_access_scope("EMP-001", "ARA-001", "ALL_BUSINESSES", business_id="BIZ-001", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SCOPE_TARGET_NOT_ALLOWED")

    def test_selected_businesses_requires_business_id(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, ACTIVE_ARA_ROW)):
            result = im.assign_access_scope("EMP-001", "ARA-001", "SELECTED_BUSINESSES", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SCOPE_TARGET_REQUIRED")

    def test_assigned_objects_only_requires_object_id(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, ACTIVE_ARA_ROW)):
            result = im.assign_access_scope("EMP-001", "ARA-001", "ASSIGNED_OBJECTS_ONLY", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SCOPE_TARGET_REQUIRED")

    def test_assigned_objects_only_direct_object_id_no_derivation(self):
        source = inspect.getsource(im.assign_access_scope)
        self.assertNotIn("roadmap_stages", source)
        self.assertNotIn("task_registry", source)
        self.assertNotIn("stage_entity_relations", source)
        self.assertNotIn("Responsible", source)

    def test_selected_businesses_one_row_per_business(self):
        sheet = _make_sheet(ASA_HEADERS)
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, ACTIVE_ARA_ROW)), \
             patch.object(im, "find_active_scope_assignments", return_value=[]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             _patch_new_id("ASA-001"), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.find_row_by_id") as mock_find:
            mock_find.side_effect = [
                (2, ACTIVE_ARA_ROW),
                (2, {"Access Scope Assignment ID": "ASA-001", "Employee ID": "EMP-001",
                     "Access Role Assignment ID": "ARA-001", "Scope Type": "SELECTED_BUSINESSES",
                     "Business ID": "BIZ-001", "Object ID": "", "Status": "active",
                     "Effective From": "", "Effective Until": "", "Assigned At": "x",
                     "Assigned By": "telegram:1", "Revoked At": "", "Revoked By": "", "Revoke Reason": ""}),
            ]
            result = im.assign_access_scope("EMP-001", "ARA-001", "SELECTED_BUSINESSES", business_id="BIZ-001", assigned_by="telegram:1")
        self.assertTrue(result["ok"])
        row = mock_append.call_args[0][1]
        idx_business = ASA_HEADERS.index("Business ID")
        self.assertEqual(row[idx_business], "BIZ-001")

    def test_role_assignment_not_found(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=None):
            result = im.assign_access_scope("EMP-001", "ARA-999", "ALL_BUSINESSES", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ACCESS_ROLE_ASSIGNMENT_NOT_FOUND")

    def test_role_assignment_employee_mismatch(self):
        mismatched = dict(ACTIVE_ARA_ROW, **{"Employee ID": "EMP-999"})
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, mismatched)):
            result = im.assign_access_scope("EMP-001", "ARA-001", "ALL_BUSINESSES", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ACCESS_ROLE_ASSIGNMENT_EMPLOYEE_MISMATCH")

    def test_inactive_role_assignment_rejected(self):
        revoked = dict(ACTIVE_ARA_ROW, **{"Status": "revoked"})
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, revoked)):
            result = im.assign_access_scope("EMP-001", "ARA-001", "ALL_BUSINESSES", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ACCESS_ROLE_ASSIGNMENT_NOT_ACTIVE")

    def test_duplicate_active_scope_rejected(self):
        with patch.object(im, "find_employee", return_value=_employee_dict(status="active")), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, ACTIVE_ARA_ROW)), \
             patch.object(im, "find_active_scope_assignments", return_value=[
                 {"scope_type": "SELECTED_BUSINESSES", "business_id": "BIZ-001", "object_id": ""},
             ]):
            result = im.assign_access_scope("EMP-001", "ARA-001", "SELECTED_BUSINESSES", business_id="BIZ-001", assigned_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DUPLICATE_ACTIVE_SCOPE")

    def test_scope_revoke_and_regrant_is_new_row(self):
        source = inspect.getsource(im.assign_access_scope)
        self.assertIn("generate_next_id", source)
        self.assertFalse(hasattr(im, "reactivate_access_scope"))

    def test_scope_revoke_requires_reason(self):
        result = im.revoke_access_scope("ASA-001", reason="", revoked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REVOKE_REASON_REQUIRED")


# ────────────────────────────────────────────────────────────
# Owner bootstrap
# ────────────────────────────────────────────────────────────

class TestOwnerBootstrap(unittest.TestCase):
    def setUp(self):
        os.environ.pop("BC_OWNER_TELEGRAM_USER_ID", None)

    def tearDown(self):
        os.environ.pop("BC_OWNER_TELEGRAM_USER_ID", None)

    def _bb(self):
        import business_core.business_builder as bb
        return bb

    def test_missing_env(self):
        bb = self._bb()
        result = bb.bootstrap_owner_from_env(dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_ENV_MISSING")

    def test_non_numeric_env(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "abc"
        bb = self._bb()
        result = bb.bootstrap_owner_from_env(dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_ENV_INVALID")

    def test_dry_run_zero_writes(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[]), \
             patch("business_core.identity_manager.find_employee_by_telegram_user_id", return_value=None), \
             patch("business_core.identity_manager.create_pending_employee") as mock_create, \
             patch("business_core.identity_manager.link_telegram_identity") as mock_link, \
             patch("business_core.identity_manager._bootstrap_assign_owner_role") as mock_role, \
             patch("business_core.identity_manager.assign_access_scope") as mock_scope:
            result = bb.bootstrap_owner_from_env(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "OWNER_BOOTSTRAP_PREVIEW")
        self.assertTrue(result["dry_run"])
        mock_create.assert_not_called()
        mock_link.assert_not_called()
        mock_role.assert_not_called()
        mock_scope.assert_not_called()

    def test_clean_live_bootstrap_four_created_ids(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[]), \
             patch("business_core.identity_manager.find_employee_by_telegram_user_id", return_value=None), \
             patch("business_core.identity_manager.create_pending_employee", return_value={"ok": True, "changed": True, "code": "EMPLOYEE_CREATED", "error": None, "employee_id": "EMP-001", "retry_safe": True}), \
             patch("business_core.identity_manager.activate_employee", return_value={"ok": True, "changed": True, "code": "EMPLOYEE_ACTIVE", "error": None, "retry_safe": True}), \
             patch("business_core.identity_manager.find_active_telegram_identity_by_employee") as mock_find_identity, \
             patch("business_core.identity_manager.link_telegram_identity", return_value={"ok": True, "changed": True, "code": "TELEGRAM_IDENTITY_LINKED", "error": None, "telegram_identity_id": "TGID-001", "retry_safe": True}), \
             patch("business_core.identity_manager.find_active_role_assignments") as mock_find_roles, \
             patch("business_core.identity_manager._bootstrap_assign_owner_role", return_value={"ok": True, "changed": True, "code": "ACCESS_ROLE_ASSIGNED", "error": None, "access_role_assignment_id": "ARA-001", "retry_safe": True}), \
             patch("business_core.identity_manager.find_active_scope_assignments") as mock_find_scopes, \
             patch("business_core.identity_manager.assign_access_scope", return_value={"ok": True, "changed": True, "code": "ACCESS_SCOPE_ASSIGNED", "error": None, "access_scope_assignment_id": "ASA-001", "retry_safe": True}), \
             patch("business_core.identity_manager.find_employee", return_value=_employee_dict(status="active")):

            mock_find_identity.side_effect = [None, {"telegram_identity_id": "TGID-001", "telegram_user_id": "999"}]
            mock_find_roles.side_effect = [[], [{"role": "OWNER", "access_role_assignment_id": "ARA-001"}]]
            mock_find_scopes.side_effect = [[], [{"scope_type": "ALL_BUSINESSES", "access_scope_assignment_id": "ASA-001"}]]

            result = bb.bootstrap_owner_from_env(dry_run=False)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["code"], "OWNER_BOOTSTRAP_COMPLETE")
        self.assertTrue(result["changed"])
        self.assertEqual(set(result["created_ids"].keys()), {
            "employee_id", "telegram_identity_id", "access_role_assignment_id", "access_scope_assignment_id",
        })

    def test_idempotent_rerun_same_owner(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        owner_assignment = {"employee_id": "EMP-001", "access_role_assignment_id": "ARA-001", "role": "OWNER"}
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[owner_assignment]), \
             patch("business_core.identity_manager.find_employee", return_value=_employee_dict(employee_id="EMP-001", status="active")), \
             patch("business_core.identity_manager.find_active_telegram_identity_by_employee", return_value=_tg_dict(employee_id="EMP-001", telegram_user_id="999")):
            result = bb.bootstrap_owner_from_env(dry_run=False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "OWNER_BOOTSTRAP_ALREADY_COMPLETE")

    def test_conflicting_owner_different_telegram_id(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        owner_assignment = {"employee_id": "EMP-001", "access_role_assignment_id": "ARA-001", "role": "OWNER"}
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[owner_assignment]), \
             patch("business_core.identity_manager.find_employee", return_value=_employee_dict(employee_id="EMP-001", status="active")), \
             patch("business_core.identity_manager.find_active_telegram_identity_by_employee", return_value=_tg_dict(employee_id="EMP-001", telegram_user_id="111")):
            result = bb.bootstrap_owner_from_env(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_CONFLICT_DIFFERENT_TELEGRAM_ID")

    def test_multiple_active_owners_conflict(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[{"employee_id": "EMP-001"}, {"employee_id": "EMP-002"}]):
            result = bb.bootstrap_owner_from_env(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_ACTIVE_OWNERS_CONFLICT")

    def test_telegram_id_bound_to_non_owner_employee(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[]), \
             patch("business_core.identity_manager.find_employee_by_telegram_user_id", return_value=_employee_dict(employee_id="EMP-002", created_by="telegram:5")), \
             patch("business_core.identity_manager.find_active_telegram_identity_by_employee", return_value=_tg_dict(employee_id="EMP-002", linked_by="telegram:5")):
            result = bb.bootstrap_owner_from_env(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TELEGRAM_ID_BOUND_TO_NON_OWNER_EMPLOYEE")

    def test_write_failure_retry_safe_false(self):
        os.environ["BC_OWNER_TELEGRAM_USER_ID"] = "999"
        bb = self._bb()
        with patch("business_core.identity_manager.find_active_owner_assignments", return_value=[]), \
             patch("business_core.identity_manager.find_employee_by_telegram_user_id", return_value=None), \
             patch("business_core.identity_manager.create_pending_employee", return_value={"ok": False, "changed": False, "code": "EMPLOYEE_WRITE_FAILED", "error": None, "employee_id": "", "retry_safe": False}):
            result = bb.bootstrap_owner_from_env(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertFalse(result["retry_safe"])
        self.assertEqual(result["failed_step"], "create_employee")

    def test_no_automatic_startup_call(self):
        # Structural guard: bootstrap_owner_from_env must never be
        # referenced by any module-level (import-time) code.
        import business_core.business_builder as bb
        source_lines = inspect.getsource(bb).splitlines()
        # Every call site of bootstrap_owner_from_env( must be inside a
        # function body (indented), never at column 0.
        for line in source_lines:
            if "bootstrap_owner_from_env(" in line and not line.startswith(" ") and not line.startswith("def bootstrap_owner_from_env"):
                self.fail(f"unexpected module-level call: {line}")

    def test_never_accepts_telegram_id_as_argument(self):
        import business_core.business_builder as bb
        sig = inspect.signature(bb.bootstrap_owner_from_env)
        self.assertNotIn("telegram_user_id", sig.parameters)
        self.assertEqual(list(sig.parameters), ["dry_run"])


# ────────────────────────────────────────────────────────────
# Architecture guards
# ────────────────────────────────────────────────────────────

class TestArchitectureGuards(unittest.TestCase):
    def test_no_people_registry_reuse(self):
        source = inspect.getsource(im)
        self.assertNotIn('"people_registry"', source)

    def test_no_channel_registry_reuse(self):
        source = inspect.getsource(im)
        self.assertNotIn('"channel_registry"', source)

    def test_no_organizational_role_registry_reuse(self):
        source = inspect.getsource(im)
        self.assertNotIn('"role_registry"', source)
        self.assertNotIn('"person_role_assignments"', source)

    def test_no_username_identity(self):
        source = inspect.getsource(im)
        self.assertNotIn("_telegram_username", source)
        self.assertNotIn(".username", source)

    def test_bcaccess_telegram_adapter_isolation(self):
        """
        Phase 17D superseded the original Phase 17B guard (a live
        `git diff HEAD -- telegram_handlers.py` check requiring zero
        diff), since Phase 17D is explicitly approved to add the
        /bcaccess handler to that file. This is the durable
        replacement architecture guard, covering every invariant the
        original zero-diff check was a (now-obsolete) proxy for:

        - bc_access() and its rendering helpers never reach
          identity_manager.py or business_core.sheets directly —
          every read goes exclusively through
          get_telegram_business_core_access_summary() (scoped to
          bc_access's own source, not the whole module, since
          telegram_handlers.py legitimately imports business_core.sheets
          in many other, unrelated pre-existing handlers);
        - bc_access() calls only get_telegram_business_core_access_summary(update)
          — never get_business_core_access_summary,
          authorize_business_core_access, or
          authorize_telegram_business_core_request directly;
        - no other existing handler in the file calls either Telegram
          authorization adapter;
        - CommandHandler("bcaccess", bc_access) is registered exactly
          once.
        """
        import ast

        from business_core import telegram_handlers as th

        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        bc_access_src = (
            inspect.getsource(th.bc_access)
            + inspect.getsource(th._render_bcaccess_message)
            + inspect.getsource(th._render_bcaccess_scope_line)
        )
        self.assertNotIn("identity_manager", bc_access_src)
        self.assertNotIn("business_core.sheets", bc_access_src)
        self.assertNotIn("get_business_sheet", bc_access_src)
        self.assertNotIn("read_business_sheet", bc_access_src)

        self.assertIn("get_telegram_business_core_access_summary(update)", bc_access_src)
        self.assertNotIn("get_business_core_access_summary(", bc_access_src)
        self.assertNotIn("authorize_business_core_access(", bc_access_src)
        self.assertNotIn("authorize_telegram_business_core_request(", bc_access_src)

        self.assertEqual(source.count('CommandHandler("bcaccess"'), 1)

    def test_telegram_adapter_callers_are_exactly_the_two_authorized_paths(self):
        """
        Phase 17E-1 durable replacement for the Phase-17D-era assumption
        that ONLY bc_access may call a Telegram authorization adapter
        function. That assumption is now correctly superseded: Phase
        17E-1 approved a SECOND caller, _authorize_or_reply(), used by
        the six enforced read commands. This test encodes the new,
        durable invariant instead of a live git-diff or a single-caller
        assumption:

          1. bc_access()          -> get_telegram_business_core_access_summary() only
          2. _authorize_or_reply() -> authorize_telegram_business_core_request() only

        No other function anywhere in telegram_handlers.py may reference
        either adapter function — in particular, none of the six
        enforced handlers may call authorize_telegram_business_core_request
        or get_telegram_business_core_access_summary directly; they may
        only call _validate_bc_transport_or_reply,
        _resolve_target_in_thread, and _authorize_or_reply.
        """
        import ast

        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        summary_adapter = "get_telegram_business_core_access_summary"
        request_adapter = "authorize_telegram_business_core_request"

        summary_callers = []
        request_callers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                func_src = ast.get_source_segment(source, node) or ""
                if f"{summary_adapter}(" in func_src:
                    summary_callers.append(node.name)
                if f"{request_adapter}(" in func_src:
                    request_callers.append(node.name)

        self.assertEqual(summary_callers, ["bc_access"],
                          f"get_telegram_business_core_access_summary must be called only by bc_access; found: {summary_callers}")
        self.assertEqual(request_callers, ["_authorize_or_reply"],
                          f"authorize_telegram_business_core_request must be called only by _authorize_or_reply; found: {request_callers}")

    def test_enforced_handlers_use_only_the_three_helpers(self):
        """The six enforced read commands may call only the three
        Phase 17E-1 handler helpers — never an adapter function
        directly, never identity_manager, never business_core.sheets,
        never a raw authorization.py function."""
        import ast

        from business_core import telegram_handlers as th

        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()

        enforced = ("doc_cmd", "obligation_cmd", "payment_cmd", "offer_cmd", "lead_cmd", "interaction_cmd")
        forbidden_direct_calls = (
            "authorize_telegram_business_core_request(",
            "get_telegram_business_core_access_summary(",
            "authorize_business_core_access(",
            "get_business_core_access_summary(",
        )
        for name in enforced:
            with self.subTest(handler=name):
                func_src = inspect.getsource(getattr(th, name))
                for forbidden in forbidden_direct_calls:
                    self.assertNotIn(forbidden, func_src)
                self.assertIn("_validate_bc_transport_or_reply(update)", func_src)
                self.assertIn("_resolve_target_in_thread(", func_src)
                self.assertIn("_authorize_or_reply(", func_src)

    def test_request_adapter_not_called_by_conversation_or_callback_handlers(self):
        """The request adapter must never be called by a
        ConversationHandler state function or a CallbackQueryHandler
        callback — enforcement in Phase 17E-1 is scoped to exactly the
        six plain CommandHandler read commands."""
        import ast

        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        conversation_state_names = {
            "newbiz_start", "newbiz_name", "newbiz_cities", "newbiz_priority", "newbiz_confirm", "newbiz_cancel",
            "newclient_start", "newclient_name", "newclient_phone", "newclient_type", "newclient_biz", "newclient_confirm", "newclient_cancel",
            "editclient_start", "editclient_field", "editclient_value", "editclient_confirm", "editclient_cancel",
            "editobject_start", "editobject_field", "editobject_value", "editobject_confirm", "editobject_cancel",
            "registerdoc_start", "registerdoc_confirm", "registerdoc_cancel",
            "uploaddoc_start", "uploaddoc_receive_file", "uploaddoc_receive_details", "uploaddoc_confirm", "uploaddoc_cancel",
            "newroadmap_start", "newroadmap_business", "newroadmap_client", "newroadmap_service",
            "newroadmap_city", "newroadmap_days", "newroadmap_confirm", "newroadmap_cancel",
        }
        callback_names = {"bc_ctx_callback"}

        request_adapter = "authorize_telegram_business_core_request("
        summary_adapter = "get_telegram_business_core_access_summary("
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (conversation_state_names | callback_names):
                func_src = ast.get_source_segment(source, node) or ""
                if request_adapter in func_src or summary_adapter in func_src:
                    offenders.append(node.name)
        self.assertEqual(offenders, [], f"unexpected adapter usage in conversation/callback handler(s): {offenders}")

    def test_gtd_files_untouched(self):
        import subprocess
        gtd_files = ["inbox_processor.py", "project_planner.py", "calendar_sync.py"]
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"] + gtd_files,
            capture_output=True, text=True, cwd=".",
        )
        self.assertEqual(result.stdout.strip(), "", "GTD files must have zero diff in Phase 17B")

    def test_schema_27_35_12_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_registry"]), 27)
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)
        self.assertEqual(len(BUSINESS_HEADERS["document_field_reviews"]), 12)

    def test_actor_spoofing_sites_unchanged_this_phase(self):
        # A structural reminder, not a fix: telegram_handlers.py still
        # contains the caller-overridable created_by pattern flagged in
        # Phase 17A — Phase 17B does not touch it, by explicit scope
        # (and has zero diff on this file at all, per the guard above).
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        self.assertIn('args.get("created_by", "")', source)


if __name__ == "__main__":
    unittest.main()
