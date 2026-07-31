"""
Phase 17B-IR3A — dedicated OWNER incident-remediation path.

Covers business_core.identity_manager._remediate_revoke_incident_owner_role,
business_core.business_builder.remediate_phase17b_identity_incident, and
remediate_identity_bootstrap_incident.py. No live Google Sheets access —
mocks only. This file is registered in conftest.py's hard socket-block
set (see _IDENTITY_DOMAIN_TEST_FILES) before any test logic here.
"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

import business_core.identity_manager as im
import business_core.business_builder as bb
import remediate_identity_bootstrap_incident as cli

WORKSPACE = Path(__file__).parent

BOOTSTRAP_ACTOR = im.SYSTEM_BOOTSTRAP_ACTOR
REMEDIATION_ACTOR = "system:incident_remediation"
REMEDIATION_REASON = "incident: unauthorized test bootstrap during Phase 17B validation"


def _ara(**overrides):
    d = {
        "access_role_assignment_id": "ARA-001", "employee_id": "EMP-001", "role": "OWNER",
        "status": "active", "effective_from": "", "effective_until": "",
        "assigned_at": "2026-07-31 04:56:29 UTC", "assigned_by": BOOTSTRAP_ACTOR,
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }
    d.update(overrides)
    return d


def _tgid(**overrides):
    d = {
        "telegram_identity_id": "TGID-001", "employee_id": "EMP-001",
        "telegram_user_id": "999", "telegram_actor": "telegram:999",
        "status": "active", "linked_at": "2026-07-31 04:56:27 UTC", "linked_by": BOOTSTRAP_ACTOR,
        "revoked_at": "", "revoked_by": "", "revoke_reason": "",
    }
    d.update(overrides)
    return d


def _emp(**overrides):
    d = {
        "employee_id": "EMP-001", "person_id": "", "display_label": "Owner", "status": "active",
        "created_at": "2026-07-31 04:56:22 UTC", "created_by": BOOTSTRAP_ACTOR,
        "activated_at": "2026-07-31 04:56:23 UTC", "activated_by": BOOTSTRAP_ACTOR,
        "disabled_at": "", "disabled_by": "", "disable_reason": "", "notes": "",
    }
    d.update(overrides)
    return d


def _asa(**overrides):
    d = {
        "access_scope_assignment_id": "ASA-001", "employee_id": "EMP-001",
        "access_role_assignment_id": "ARA-001", "scope_type": "ALL_BUSINESSES",
        "business_id": "", "object_id": "", "status": "revoked",
        "effective_from": "", "effective_until": "", "assigned_at": "2026-07-31 04:56:33 UTC",
        "assigned_by": BOOTSTRAP_ACTOR, "revoked_at": "2026-07-31 07:53:02 UTC",
        "revoked_by": REMEDIATION_ACTOR, "revoke_reason": REMEDIATION_REASON,
    }
    d.update(overrides)
    return d


_UNSET = object()


def _patch_all(ara=_UNSET, tgid=_UNSET, emp=_UNSET, asa=_UNSET):
    return (
        patch("business_core.identity_manager.find_access_role_assignment", return_value=_ara() if ara is _UNSET else ara),
        patch("business_core.identity_manager.find_telegram_identity", return_value=_tgid() if tgid is _UNSET else tgid),
        patch("business_core.identity_manager.find_employee", return_value=_emp() if emp is _UNSET else emp),
        patch("business_core.identity_manager.find_access_scope_assignment", return_value=_asa() if asa is _UNSET else asa),
    )


# ────────────────────────────────────────────────────────────
# Test isolation guards
# ────────────────────────────────────────────────────────────

class TestIsolationGuards(unittest.TestCase):
    def test_file_registered_in_hard_socket_block(self):
        conftest_src = (WORKSPACE / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("test_identity_incident_remediation.py", conftest_src)
        union_start = conftest_src.index("_HARD_SOCKET_BLOCK_TEST_FILES = (")
        union_end = conftest_src.index(")", union_start)
        union_body = conftest_src[union_start:union_end]
        self.assertIn("_IDENTITY_DOMAIN_TEST_FILES", union_body)

    def test_operation_never_referenced_from_startup(self):
        for filename in ("telegram_bot.py",):
            path = WORKSPACE / filename
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("remediate_phase17b_identity_incident", src)
            self.assertNotIn("remediate_identity_bootstrap_incident", src)

    def test_operation_never_referenced_from_telegram_handlers(self):
        src = (WORKSPACE / "business_core" / "telegram_handlers.py").read_text(encoding="utf-8")
        self.assertNotIn("remediate_phase17b_identity_incident", src)
        self.assertNotIn("_remediate_revoke_incident_owner_role", src)

    def test_generic_owner_revoke_still_blocked(self):
        row = {
            "Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "OWNER",
            "Status": "active", "Effective From": "", "Effective Until": "",
            "Assigned At": "x", "Assigned By": BOOTSTRAP_ACTOR,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            result = im.revoke_access_role("ARA-001", reason="x", revoked_by="telegram:1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OWNER_ROLE_REQUIRES_AUTHORIZATION_DOMAIN")

    def test_no_generic_force_or_bypass_parameter(self):
        sig = inspect.signature(im._remediate_revoke_incident_owner_role)
        self.assertNotIn("force", sig.parameters)
        self.assertNotIn("bypass", sig.parameters)
        sig2 = inspect.signature(bb.remediate_phase17b_identity_incident)
        self.assertNotIn("force", sig2.parameters)
        self.assertNotIn("bypass", sig2.parameters)
        self.assertEqual(list(sig2.parameters), ["dry_run"])

    def test_no_module_object_patch_object_for_orchestration_tests(self):
        """Mirrors test_identity_registry.py's identical guard: any test
        that exercises code through business_builder's call-time
        `from business_core import identity_manager as im` re-import
        (TestPreconditions/TestDryRun/TestLiveExecution/TestIdempotency)
        must use string-based patch() targets, never patch.object(im, ...)
        — the latter silently misses if another test file purges
        business_core.* from sys.modules in between (the exact Phase
        17B-IR1 failure mode)."""
        src = (WORKSPACE / "test_identity_incident_remediation.py").read_text(encoding="utf-8")
        for classname in ("TestPreconditions", "TestDryRun", "TestLiveExecution", "TestIdempotency"):
            class_start = src.index(f"class {classname}")
            next_class = src.index("\nclass ", class_start + 1) if "\nclass " in src[class_start + 1:] else len(src)
            class_body = src[class_start:next_class]
            self.assertNotIn("patch.object(im,", class_body, f"{classname} uses patch.object(im, ...) — unsafe")
            self.assertNotIn("patch.object(bb,", class_body, f"{classname} uses patch.object(bb, ...) — unsafe")

    def test_cli_never_calls_sheets_directly(self):
        src = (WORKSPACE / "remediate_identity_bootstrap_incident.py").read_text(encoding="utf-8")
        self.assertNotIn("business_core.sheets", src)
        self.assertNotIn("get_business_sheet", src)
        self.assertNotIn("update_business_row", src)


# ────────────────────────────────────────────────────────────
# Manager-level: _remediate_revoke_incident_owner_role
# ────────────────────────────────────────────────────────────

class TestSpecializedManagerRevoke(unittest.TestCase):
    def test_not_found(self):
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_TARGET_NOT_FOUND")

    def test_role_mismatch(self):
        row = dict(zip(
            ["Access Role Assignment ID", "Employee ID", "Role", "Status", "Effective From", "Effective Until",
             "Assigned At", "Assigned By", "Revoked At", "Revoked By", "Revoke Reason"],
            ["ARA-001", "EMP-001", "VIEWER", "active", "", "", "x", BOOTSTRAP_ACTOR, "", "", ""],
        ))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertEqual(result["code"], "INCIDENT_ROLE_MISMATCH")

    def _ara_row(self, **overrides):
        d = {
            "Access Role Assignment ID": "ARA-001", "Employee ID": "EMP-001", "Role": "OWNER",
            "Status": "active", "Effective From": "", "Effective Until": "",
            "Assigned At": "x", "Assigned By": BOOTSTRAP_ACTOR,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        d.update(overrides)
        return d

    def test_employee_mismatch(self):
        row = self._ara_row(**{"Employee ID": "EMP-999"})
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertEqual(result["code"], "INCIDENT_EMPLOYEE_MISMATCH")

    def test_assigned_by_mismatch(self):
        row = self._ara_row(**{"Assigned By": "telegram:5"})
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertEqual(result["code"], "INCIDENT_ACTOR_MISMATCH")

    def test_telegram_identity_mismatch(self):
        row = self._ara_row()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid(telegram_user_id="111")):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertEqual(result["code"], "INCIDENT_TELEGRAM_IDENTITY_MISMATCH")

    def test_success(self):
        row = self._ara_row()
        revoked_row = self._ara_row(**{
            "Status": "revoked", "Revoked At": "2026-08-01 00:00:00 UTC",
            "Revoked By": REMEDIATION_ACTOR, "Revoke Reason": REMEDIATION_REASON,
        })
        with patch("business_core.sheets.find_row_by_id", side_effect=[(2, row), (2, revoked_row)]), \
             patch("business_core.sheets.update_business_row") as mock_update, \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid()), \
             patch.object(im, "_now_utc", return_value="2026-08-01 00:00:00 UTC"):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_OWNER_ROLE_REVOKED")
        values = mock_update.call_args[0][2]
        self.assertEqual(values, {
            "Status": "revoked", "Revoked At": "2026-08-01 00:00:00 UTC",
            "Revoked By": REMEDIATION_ACTOR, "Revoke Reason": REMEDIATION_REASON,
        })

    def test_only_four_fields_written(self):
        row = self._ara_row()
        revoked_row = self._ara_row(**{
            "Status": "revoked", "Revoked At": "x", "Revoked By": REMEDIATION_ACTOR, "Revoke Reason": REMEDIATION_REASON,
        })
        with patch("business_core.sheets.find_row_by_id", side_effect=[(2, row), (2, revoked_row)]), \
             patch("business_core.sheets.update_business_row") as mock_update, \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid()):
            im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        values = mock_update.call_args[0][2]
        self.assertEqual(set(values.keys()), {"Status", "Revoked At", "Revoked By", "Revoke Reason"})

    def test_idempotent_already_revoked_by_this_incident(self):
        row = self._ara_row(**{
            "Status": "revoked", "Revoked At": "x", "Revoked By": REMEDIATION_ACTOR, "Revoke Reason": REMEDIATION_REASON,
        })
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.update_business_row") as mock_update, \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid()):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "INCIDENT_OWNER_ROLE_ALREADY_REVOKED")
        mock_update.assert_not_called()

    def test_conflicting_prior_revocation(self):
        row = self._ara_row(**{"Status": "revoked", "Revoked At": "x", "Revoked By": "telegram:5", "Revoke Reason": "other"})
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid()):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_CONFLICTING_PRIOR_REVOCATION")

    def test_post_write_verification_failure(self):
        row = self._ara_row()
        wrong_after = self._ara_row(**{"Status": "active"})  # write silently failed to take effect
        with patch("business_core.sheets.find_row_by_id", side_effect=[(2, row), (2, wrong_after)]), \
             patch("business_core.sheets.update_business_row"), \
             patch.object(im, "find_active_telegram_identity_by_employee", return_value=_tgid()):
            result = im._remediate_revoke_incident_owner_role(
                "ARA-001", expected_employee_id="EMP-001", expected_telegram_user_id="999",
                reason=REMEDIATION_REASON, actor=REMEDIATION_ACTOR,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])


# ────────────────────────────────────────────────────────────
# Orchestration: preconditions
# ────────────────────────────────────────────────────────────

class TestPreconditions(unittest.TestCase):
    def test_wrong_ara_id_not_found(self):
        patches = _patch_all(ara=None)
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_PRECONDITION_FAILED")
        self.assertEqual(result["failed_step"], "ARA_NOT_FOUND")

    def test_wrong_role(self):
        patches = _patch_all(ara=_ara(role="VIEWER"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ARA_ROLE_MISMATCH")

    def test_wrong_employee_id(self):
        patches = _patch_all(ara=_ara(employee_id="EMP-999"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ARA_EMPLOYEE_MISMATCH")

    def test_wrong_assigned_by(self):
        patches = _patch_all(ara=_ara(assigned_by="telegram:5"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ARA_ASSIGNED_BY_MISMATCH")

    def test_wrong_telegram_user_id(self):
        patches = _patch_all(tgid=_tgid(telegram_user_id="111"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "TGID_USER_ID_MISMATCH")

    def test_wrong_telegram_actor(self):
        patches = _patch_all(tgid=_tgid(telegram_actor="telegram:111"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "TGID_ACTOR_MISMATCH")

    def test_wrong_bootstrap_actor_on_tgid(self):
        patches = _patch_all(tgid=_tgid(linked_by="telegram:5"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "TGID_LINKED_BY_MISMATCH")

    def test_missing_employee(self):
        patches = _patch_all(emp=None)
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "EMP_NOT_FOUND")

    def test_wrong_employee_created_by(self):
        patches = _patch_all(emp=_emp(created_by="telegram:5"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "EMP_CREATED_BY_MISMATCH")

    def test_asa_not_revoked(self):
        patches = _patch_all(asa=_asa(status="active"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ASA_NOT_CORRECTLY_REVOKED")

    def test_asa_revoked_with_wrong_actor(self):
        patches = _patch_all(asa=_asa(revoked_by="telegram:5"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ASA_NOT_CORRECTLY_REVOKED")

    def test_asa_revoked_with_wrong_reason(self):
        patches = _patch_all(asa=_asa(revoke_reason="other reason"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ASA_NOT_CORRECTLY_REVOKED")

    def test_conflicting_prior_ara_revocation(self):
        patches = _patch_all(ara=_ara(status="revoked", revoked_by="telegram:5", revoke_reason="other"))
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertEqual(result["failed_step"], "ARA_UNEXPECTED_STATUS")

    def test_precondition_failure_zero_writes(self):
        patches = _patch_all(ara=None)
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role") as mock_ara, \
             patch("business_core.identity_manager.revoke_telegram_identity") as mock_tgid, \
             patch("business_core.identity_manager.disable_employee") as mock_emp:
            bb.remediate_phase17b_identity_incident(dry_run=False)
        mock_ara.assert_not_called()
        mock_tgid.assert_not_called()
        mock_emp.assert_not_called()


# ────────────────────────────────────────────────────────────
# Orchestration: dry-run
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):
    def test_current_partial_state_preview(self):
        patches = _patch_all()  # ARA/TGID/EMP active, ASA already revoked
        with patches[0], patches[1], patches[2], patches[3]:
            result = bb.remediate_phase17b_identity_incident(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_REMEDIATION_PREVIEW")
        self.assertFalse(result["changed"])
        self.assertEqual(result["completed_steps"], ("verify_asa_already_revoked",))
        self.assertEqual(result["pending_steps"], ("revoke_ara", "revoke_tgid", "disable_emp"))

    def test_dry_run_zero_writes(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role") as mock_ara, \
             patch("business_core.identity_manager.revoke_telegram_identity") as mock_tgid, \
             patch("business_core.identity_manager.disable_employee") as mock_emp:
            bb.remediate_phase17b_identity_incident(dry_run=True)
        mock_ara.assert_not_called()
        mock_tgid.assert_not_called()
        mock_emp.assert_not_called()


# ────────────────────────────────────────────────────────────
# Orchestration: live execution
# ────────────────────────────────────────────────────────────

class TestLiveExecution(unittest.TestCase):
    def test_exact_order_and_success(self):
        call_order = []

        def _ara_ok(*a, **kw):
            call_order.append("ara")
            return {"ok": True, "changed": True, "code": "INCIDENT_OWNER_ROLE_REVOKED", "error": None, "retry_safe": True}

        def _tgid_ok(*a, **kw):
            call_order.append("tgid")
            return {"ok": True, "changed": True, "code": "TELEGRAM_IDENTITY_REVOKED", "error": None, "retry_safe": True}

        def _emp_ok(*a, **kw):
            call_order.append("emp")
            return {"ok": True, "changed": True, "code": "EMPLOYEE_DISABLED", "error": None, "retry_safe": True}

        with patch("business_core.identity_manager.find_access_role_assignment", side_effect=[_ara(), _ara(status="revoked")]), \
             patch("business_core.identity_manager.find_telegram_identity", side_effect=[_tgid(), _tgid(status="revoked")]), \
             patch("business_core.identity_manager.find_employee", side_effect=[_emp(), _emp(status="disabled")]), \
             patch("business_core.identity_manager.find_access_scope_assignment", return_value=_asa()), \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role", side_effect=_ara_ok), \
             patch("business_core.identity_manager.revoke_telegram_identity", side_effect=_tgid_ok), \
             patch("business_core.identity_manager.disable_employee", side_effect=_emp_ok):
            result = bb.remediate_phase17b_identity_incident(dry_run=False)

        self.assertEqual(call_order, ["ara", "tgid", "emp"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "INCIDENT_REMEDIATION_COMPLETE")

    def test_stop_on_ara_failure(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role",
                   return_value={"ok": False, "changed": False, "code": "INCIDENT_WRITE_FAILED", "error": None, "retry_safe": False}), \
             patch("business_core.identity_manager.revoke_telegram_identity") as mock_tgid, \
             patch("business_core.identity_manager.disable_employee") as mock_emp:
            result = bb.remediate_phase17b_identity_incident(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "revoke_ara")
        self.assertFalse(result["retry_safe"])
        mock_tgid.assert_not_called()
        mock_emp.assert_not_called()

    def test_stop_on_tgid_failure(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role",
                   return_value={"ok": True, "changed": True, "code": "INCIDENT_OWNER_ROLE_REVOKED", "error": None, "retry_safe": True}), \
             patch("business_core.identity_manager.revoke_telegram_identity",
                   return_value={"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_WRITE_FAILED", "error": None, "retry_safe": False}), \
             patch("business_core.identity_manager.disable_employee") as mock_emp:
            result = bb.remediate_phase17b_identity_incident(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "revoke_tgid")
        mock_emp.assert_not_called()

    def test_stop_on_emp_failure(self):
        patches = _patch_all()
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role",
                   return_value={"ok": True, "changed": True, "code": "INCIDENT_OWNER_ROLE_REVOKED", "error": None, "retry_safe": True}), \
             patch("business_core.identity_manager.revoke_telegram_identity",
                   return_value={"ok": True, "changed": True, "code": "TELEGRAM_IDENTITY_REVOKED", "error": None, "retry_safe": True}), \
             patch("business_core.identity_manager.disable_employee",
                   return_value={"ok": False, "changed": False, "code": "EMPLOYEE_WRITE_FAILED", "error": None, "retry_safe": False}):
            result = bb.remediate_phase17b_identity_incident(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "disable_emp")

    def test_no_rollback_on_failure(self):
        source = inspect.getsource(bb.remediate_phase17b_identity_incident)
        self.assertNotIn("assign_access_role(", source)
        self.assertNotIn("activate_employee(", source)

    def test_no_row_creation_or_deletion(self):
        source = inspect.getsource(bb.remediate_phase17b_identity_incident)
        self.assertNotIn("append_business_row", source)
        self.assertNotIn("create_pending_employee", source)

    def test_asa_never_revoked_again(self):
        source = inspect.getsource(bb.remediate_phase17b_identity_incident)
        self.assertNotIn("revoke_access_scope(", source)


# ────────────────────────────────────────────────────────────
# Idempotency
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):
    def test_fully_remediated_state_is_safe_noop(self):
        patches = _patch_all(
            ara=_ara(status="revoked", revoked_by=REMEDIATION_ACTOR, revoke_reason=REMEDIATION_REASON),
            tgid=_tgid(status="revoked", revoked_by=REMEDIATION_ACTOR, revoke_reason=REMEDIATION_REASON),
            emp=_emp(status="disabled", disabled_by=REMEDIATION_ACTOR, disable_reason=REMEDIATION_REASON),
        )
        with patches[0], patches[1], patches[2], patches[3], \
             patch("business_core.identity_manager._remediate_revoke_incident_owner_role") as mock_ara, \
             patch("business_core.identity_manager.revoke_telegram_identity") as mock_tgid, \
             patch("business_core.identity_manager.disable_employee") as mock_emp:
            result = bb.remediate_phase17b_identity_incident(dry_run=False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "INCIDENT_REMEDIATION_ALREADY_COMPLETE")
        mock_ara.assert_not_called()
        mock_tgid.assert_not_called()
        mock_emp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
