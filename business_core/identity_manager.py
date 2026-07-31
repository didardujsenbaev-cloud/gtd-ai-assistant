"""
Identity Manager — Access Control persistence (Phase 17B).

Sole transactional owner of EMPLOYEE_REGISTRY, TELEGRAM_IDENTITY_REGISTRY,
ACCESS_ROLE_ASSIGNMENTS, ACCESS_SCOPE_ASSIGNMENTS. Mirrors document_manager.py's
role for DOCUMENT_REGISTRY exactly (ADR-020 precedent): low-level only, no
cross-entity validation beyond what these four registries can answer on
their own, no Telegram-layer concerns, no Russian user-facing text.

Phase 17B is schema-foundation + domain-manager only — there is NO
authorization domain yet (Phase 17C) and NO Telegram wiring yet
(Phase 17D/17E/17F). Nothing in this module is called from
business_core/telegram_handlers.py in this phase.

Deliberately NOT reusing people_registry/channel_registry/role_registry/
person_role_assignments — those are organizational/CRM entities with a
different purpose and lifecycle (see Phase 17A/17B audits).

Lifecycle discipline across all four registries: identity-bearing/grant-
bearing facts are never edited in place — a replacement or re-grant
always creates a NEW row; a revoked/disabled row is never reactivated
by editing the same row (Employee is the one exception: its own
pending -> active -> disabled -> active lifecycle is a single row,
per Phase 17B's explicit design). No hard deletion anywhere.

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Canonical enums
# ─────────────────────────────────────────────────────────────

EMPLOYEE_STATUSES = ("pending", "active", "disabled")
TELEGRAM_IDENTITY_STATUSES = ("active", "revoked")
ACCESS_ASSIGNMENT_STATUSES = ("active", "revoked")

ACCESS_ROLES = ("OWNER", "ADMIN", "COORDINATOR", "DOCUMENT_SPECIALIST", "VIEWER")
ACCESS_SCOPE_TYPES = ("ALL_BUSINESSES", "SELECTED_BUSINESSES", "ASSIGNED_OBJECTS_ONLY")

SYSTEM_BOOTSTRAP_ACTOR = "system:owner_bootstrap"

_TELEGRAM_USER_ID_RE = re.compile(r"^[0-9]+$")
_TELEGRAM_ACTOR_RE = re.compile(r"^telegram:[0-9]+$")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────
# Validation helpers — strict, never silently coerce
# ─────────────────────────────────────────────────────────────

def is_valid_telegram_user_id(value) -> bool:
    """
    Digits-only string. No float/scientific-notation acceptance, no
    username/display-name fallback of any kind. Accepts int input by
    converting to str first (a caller passing a raw int from
    update.effective_user.id is expected), but never accepts a value
    containing '.', 'e', '+', '-', or any non-digit character.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if not isinstance(value, str):
        return False
    return bool(_TELEGRAM_USER_ID_RE.match(value))


def canonical_telegram_actor(telegram_user_id) -> str:
    """telegram:{numeric_user_id} — raises ValueError on invalid input,
    never silently produces a malformed actor string."""
    if not is_valid_telegram_user_id(telegram_user_id):
        raise ValueError(f"invalid telegram_user_id: {telegram_user_id!r}")
    return f"telegram:{telegram_user_id}"


def is_valid_access_role(role: str) -> bool:
    return role in ACCESS_ROLES


def is_valid_scope_type(scope_type: str) -> bool:
    return scope_type in ACCESS_SCOPE_TYPES


# ─────────────────────────────────────────────────────────────
# Row -> dict mappers
# ─────────────────────────────────────────────────────────────

def _employee_row_to_dict(v: dict) -> dict:
    return {
        "employee_id":    v.get("Employee ID", ""),
        "person_id":      v.get("Person ID", ""),
        "display_label":  v.get("Display Label", ""),
        "status":         v.get("Status", ""),
        "created_at":     v.get("Created At", ""),
        "created_by":     v.get("Created By", ""),
        "activated_at":   v.get("Activated At", ""),
        "activated_by":   v.get("Activated By", ""),
        "disabled_at":    v.get("Disabled At", ""),
        "disabled_by":    v.get("Disabled By", ""),
        "disable_reason": v.get("Disable Reason", ""),
        "notes":          v.get("Notes", ""),
    }


def _telegram_identity_row_to_dict(v: dict) -> dict:
    return {
        "telegram_identity_id": v.get("Telegram Identity ID", ""),
        "employee_id":          v.get("Employee ID", ""),
        "telegram_user_id":     v.get("Telegram User ID", ""),
        "telegram_actor":       v.get("Telegram Actor", ""),
        "status":                v.get("Status", ""),
        "linked_at":             v.get("Linked At", ""),
        "linked_by":             v.get("Linked By", ""),
        "revoked_at":            v.get("Revoked At", ""),
        "revoked_by":            v.get("Revoked By", ""),
        "revoke_reason":         v.get("Revoke Reason", ""),
    }


def _access_role_assignment_row_to_dict(v: dict) -> dict:
    return {
        "access_role_assignment_id": v.get("Access Role Assignment ID", ""),
        "employee_id":               v.get("Employee ID", ""),
        "role":                      v.get("Role", ""),
        "status":                    v.get("Status", ""),
        "effective_from":            v.get("Effective From", ""),
        "effective_until":           v.get("Effective Until", ""),
        "assigned_at":               v.get("Assigned At", ""),
        "assigned_by":               v.get("Assigned By", ""),
        "revoked_at":                v.get("Revoked At", ""),
        "revoked_by":                v.get("Revoked By", ""),
        "revoke_reason":             v.get("Revoke Reason", ""),
    }


def _access_scope_assignment_row_to_dict(v: dict) -> dict:
    return {
        "access_scope_assignment_id": v.get("Access Scope Assignment ID", ""),
        "employee_id":                v.get("Employee ID", ""),
        "access_role_assignment_id":  v.get("Access Role Assignment ID", ""),
        "scope_type":                 v.get("Scope Type", ""),
        "business_id":                v.get("Business ID", ""),
        "object_id":                  v.get("Object ID", ""),
        "status":                     v.get("Status", ""),
        "effective_from":             v.get("Effective From", ""),
        "effective_until":            v.get("Effective Until", ""),
        "assigned_at":                v.get("Assigned At", ""),
        "assigned_by":                v.get("Assigned By", ""),
        "revoked_at":                 v.get("Revoked At", ""),
        "revoked_by":                 v.get("Revoked By", ""),
        "revoke_reason":              v.get("Revoke Reason", ""),
    }


# ─────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────

def find_employee(employee_id: str) -> Optional[dict]:
    """Read-only. Returns a dict or None."""
    if not employee_id:
        return None
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("employee_registry", employee_id)
    if not found:
        return None
    _row_num, v = found
    return _employee_row_to_dict(v)


def find_employee_by_telegram_user_id(telegram_user_id, active_only: bool = True) -> Optional[dict]:
    """
    Read-only. Resolves a numeric Telegram User ID to its Employee row
    via the Telegram Identity Registry — never scans Employee Registry
    directly (Employee Registry has no Telegram column at all, by
    design; identity binding is a fully separate registry).
    """
    if not is_valid_telegram_user_id(telegram_user_id):
        return None
    from business_core.sheets import read_business_sheet

    telegram_user_id = str(telegram_user_id)
    rows = read_business_sheet("telegram_identity_registry")
    for row in rows:
        if row.get("Telegram User ID", "") != telegram_user_id:
            continue
        if active_only and row.get("Status", "") != "active":
            continue
        employee_id = row.get("Employee ID", "")
        return find_employee(employee_id)
    return None


def find_active_telegram_identity_by_employee(employee_id: str) -> Optional[dict]:
    """Read-only. At most one active row is expected per Employee (V1
    invariant enforced at write time by link_telegram_identity())."""
    if not employee_id:
        return None
    from business_core.sheets import read_business_sheet

    rows = read_business_sheet("telegram_identity_registry")
    for row in rows:
        if row.get("Employee ID", "") == employee_id and row.get("Status", "") == "active":
            return _telegram_identity_row_to_dict(row)
    return None


def find_active_role_assignments(employee_id: str) -> list[dict]:
    """Read-only. All active Access Role Assignment rows for one Employee."""
    if not employee_id:
        return []
    from business_core.sheets import read_business_sheet

    rows = read_business_sheet("access_role_assignments")
    return [
        _access_role_assignment_row_to_dict(row)
        for row in rows
        if row.get("Employee ID", "") == employee_id and row.get("Status", "") == "active"
    ]


def find_active_scope_assignments(employee_id: str, access_role_assignment_id: str = "") -> list[dict]:
    """Read-only. All active Access Scope Assignment rows for one
    Employee, optionally narrowed to one specific Access Role
    Assignment ID."""
    if not employee_id:
        return []
    from business_core.sheets import read_business_sheet

    rows = read_business_sheet("access_scope_assignments")
    result = []
    for row in rows:
        if row.get("Employee ID", "") != employee_id:
            continue
        if row.get("Status", "") != "active":
            continue
        if access_role_assignment_id and row.get("Access Role Assignment ID", "") != access_role_assignment_id:
            continue
        result.append(_access_scope_assignment_row_to_dict(row))
    return result


def find_active_owner_assignments() -> list[dict]:
    """Read-only. Every active Access Role Assignment row with
    Role == 'OWNER', across all employees. Used exclusively by the
    owner-bootstrap orchestration (business_builder.
    bootstrap_owner_from_env()) to detect an existing owner before
    ever writing a second one."""
    from business_core.sheets import read_business_sheet

    rows = read_business_sheet("access_role_assignments")
    return [
        _access_role_assignment_row_to_dict(row)
        for row in rows
        if row.get("Role", "") == "OWNER" and row.get("Status", "") == "active"
    ]


# ─────────────────────────────────────────────────────────────
# Employee lifecycle
# ─────────────────────────────────────────────────────────────

def create_pending_employee(*, person_id: str = "", display_label: str = "", created_by: str, notes: str = "") -> dict:
    """
    Create one Employee row with Status='pending'. Low-level write —
    no cross-entity validation of person_id against People Registry
    (that belongs to a future orchestration layer, if ever needed).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None,
         "employee_id": str, "retry_safe": bool}
    """
    if not created_by:
        return {"ok": False, "changed": False, "code": "CREATED_BY_REQUIRED", "error": None, "employee_id": "", "retry_safe": True}

    try:
        from business_core.sheets import generate_next_id, append_business_row, row_from_header_map, get_business_sheet

        sheet = get_business_sheet("employee_registry")
        headers = sheet.row_values(1)
        employee_id = generate_next_id("employee_registry")
        now = _now_utc()

        values = {
            "Employee ID": employee_id, "Person ID": person_id, "Display Label": display_label,
            "Status": "pending", "Created At": now, "Created By": created_by,
            "Activated At": "", "Activated By": "",
            "Disabled At": "", "Disabled By": "", "Disable Reason": "",
            "Notes": notes,
        }
        row = row_from_header_map(headers, values)
        append_business_row("employee_registry", row)

        saved = find_employee(employee_id)
        if saved is None or saved.get("status") != "pending" or saved.get("created_by") != created_by:
            log.error(f"create_pending_employee({employee_id}) post-write verification failed")
            return {"ok": False, "changed": False, "code": "EMPLOYEE_POST_WRITE_VERIFICATION_FAILED", "error": None, "employee_id": employee_id, "retry_safe": False}

        log.info(f"create_pending_employee: {employee_id}")
        return {"ok": True, "changed": True, "code": "EMPLOYEE_CREATED", "error": None, "employee_id": employee_id, "retry_safe": True}
    except Exception as exc:
        log.error(f"create_pending_employee error: {exc}")
        return {"ok": False, "changed": False, "code": "EMPLOYEE_WRITE_FAILED", "error": None, "employee_id": "", "retry_safe": False}


def _employee_status_transition(employee_id: str, *, target_status: str, actor_field: str, actor_value: str,
                                 extra_fields: dict, allowed_from: tuple, noop_from: tuple) -> dict:
    """Shared engine for activate/disable/reactivate — one
    update_business_row() call, one post-write verification read."""
    if not employee_id:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "retry_safe": True}
    if not actor_value:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "retry_safe": True}

    employee = find_employee(employee_id)
    if employee is None:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "retry_safe": True}

    current_status = employee.get("status", "")
    if current_status in noop_from:
        return {"ok": True, "changed": False, "code": f"EMPLOYEE_ALREADY_{target_status.upper()}", "error": None, "retry_safe": True}
    if current_status not in allowed_from:
        return {"ok": False, "changed": False, "code": "INVALID_EMPLOYEE_TRANSITION", "error": None, "retry_safe": True}

    try:
        from business_core.sheets import update_business_row, find_row_by_id

        found = find_row_by_id("employee_registry", employee_id)
        if not found:
            return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "retry_safe": True}
        row_num, _v = found

        values = {"Status": target_status, actor_field: actor_value}
        values.update(extra_fields)
        update_business_row("employee_registry", row_num, values)

        reread = find_employee(employee_id)
        if reread is None or reread.get("status") != target_status:
            log.error(f"_employee_status_transition({employee_id}) post-write verification failed")
            return {"ok": False, "changed": False, "code": "EMPLOYEE_POST_WRITE_VERIFICATION_FAILED", "error": None, "retry_safe": False}

        return {"ok": True, "changed": True, "code": f"EMPLOYEE_{target_status.upper()}", "error": None, "retry_safe": True}
    except Exception as exc:
        log.error(f"_employee_status_transition({employee_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "EMPLOYEE_WRITE_FAILED", "error": None, "retry_safe": False}


def activate_employee(employee_id: str, *, activated_by: str) -> dict:
    """pending -> active. active -> active is a safe no-op."""
    return _employee_status_transition(
        employee_id, target_status="active", actor_field="Activated By", actor_value=activated_by,
        extra_fields={"Activated At": _now_utc()},
        allowed_from=("pending",), noop_from=("active",),
    )


def disable_employee(employee_id: str, *, reason: str, disabled_by: str) -> dict:
    """active/pending -> disabled. disabled -> disabled is a safe no-op.
    reason is required."""
    if not reason or not reason.strip():
        return {"ok": False, "changed": False, "code": "DISABLE_REASON_REQUIRED", "error": None, "retry_safe": True}
    return _employee_status_transition(
        employee_id, target_status="disabled", actor_field="Disabled By", actor_value=disabled_by,
        extra_fields={"Disabled At": _now_utc(), "Disable Reason": reason.strip()},
        allowed_from=("pending", "active"), noop_from=("disabled",),
    )


def reactivate_employee(employee_id: str, *, activated_by: str) -> dict:
    """disabled -> active only. active -> active is a safe no-op."""
    return _employee_status_transition(
        employee_id, target_status="active", actor_field="Activated By", actor_value=activated_by,
        extra_fields={"Activated At": _now_utc()},
        allowed_from=("disabled",), noop_from=("active",),
    )


# ─────────────────────────────────────────────────────────────
# Telegram identity
# ─────────────────────────────────────────────────────────────

def link_telegram_identity(employee_id: str, telegram_user_id, *, linked_by: str) -> dict:
    """
    Requirements enforced here: Employee must exist; Telegram User ID
    must be digits-only; active Telegram User ID must be globally
    unique; at most one active Telegram Identity per Employee (V1).
    Telegram Actor is derived internally — never a caller-suppliable
    parameter.

    Returns:
        {"ok", "changed", "code", "error", "telegram_identity_id", "retry_safe"}
    """
    if not employee_id:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "telegram_identity_id": "", "retry_safe": True}
    if not linked_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "telegram_identity_id": "", "retry_safe": True}
    if not is_valid_telegram_user_id(telegram_user_id):
        return {"ok": False, "changed": False, "code": "TELEGRAM_USER_ID_INVALID", "error": None, "telegram_identity_id": "", "retry_safe": True}

    if find_employee(employee_id) is None:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "telegram_identity_id": "", "retry_safe": True}

    telegram_user_id = str(telegram_user_id)

    if find_employee_by_telegram_user_id(telegram_user_id, active_only=True) is not None:
        return {"ok": False, "changed": False, "code": "TELEGRAM_USER_ID_ALREADY_BOUND", "error": None, "telegram_identity_id": "", "retry_safe": True}
    if find_active_telegram_identity_by_employee(employee_id) is not None:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_ALREADY_HAS_ACTIVE_IDENTITY", "error": None, "telegram_identity_id": "", "retry_safe": True}

    try:
        from business_core.sheets import generate_next_id, append_business_row, row_from_header_map, get_business_sheet

        sheet = get_business_sheet("telegram_identity_registry")
        headers = sheet.row_values(1)
        telegram_identity_id = generate_next_id("telegram_identity_registry")
        now = _now_utc()
        actor = canonical_telegram_actor(telegram_user_id)

        values = {
            "Telegram Identity ID": telegram_identity_id, "Employee ID": employee_id,
            "Telegram User ID": telegram_user_id, "Telegram Actor": actor,
            "Status": "active", "Linked At": now, "Linked By": linked_by,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        row = row_from_header_map(headers, values)
        append_business_row("telegram_identity_registry", row)

        from business_core.sheets import find_row_by_id
        reread = find_row_by_id("telegram_identity_registry", telegram_identity_id)
        if reread is None:
            log.error(f"link_telegram_identity({telegram_identity_id}) post-write verification: row missing")
            return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_POST_WRITE_VERIFICATION_FAILED", "error": None, "telegram_identity_id": telegram_identity_id, "retry_safe": False}
        _row_num, saved_v = reread
        saved = _telegram_identity_row_to_dict(saved_v)
        if saved.get("telegram_user_id") != telegram_user_id or saved.get("telegram_actor") != actor or saved.get("status") != "active":
            log.error(f"link_telegram_identity({telegram_identity_id}) post-write verification: field mismatch")
            return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_POST_WRITE_VERIFICATION_FAILED", "error": None, "telegram_identity_id": telegram_identity_id, "retry_safe": False}

        log.info(f"link_telegram_identity: {telegram_identity_id} employee={employee_id}")
        return {"ok": True, "changed": True, "code": "TELEGRAM_IDENTITY_LINKED", "error": None, "telegram_identity_id": telegram_identity_id, "retry_safe": True}
    except Exception as exc:
        log.error(f"link_telegram_identity error: {exc}")
        return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_WRITE_FAILED", "error": None, "telegram_identity_id": "", "retry_safe": False}


def revoke_telegram_identity(telegram_identity_id: str, *, reason: str, revoked_by: str) -> dict:
    """active -> revoked only. A revoked row is never reactivated —
    replacement always means link_telegram_identity() creating a new
    row. reason is required."""
    if not telegram_identity_id:
        return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_NOT_FOUND", "error": None, "retry_safe": True}
    if not reason or not reason.strip():
        return {"ok": False, "changed": False, "code": "REVOKE_REASON_REQUIRED", "error": None, "retry_safe": True}
    if not revoked_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "retry_safe": True}

    try:
        from business_core.sheets import find_row_by_id, update_business_row

        found = find_row_by_id("telegram_identity_registry", telegram_identity_id)
        if not found:
            return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_NOT_FOUND", "error": None, "retry_safe": True}
        row_num, v = found
        current = _telegram_identity_row_to_dict(v)
        if current.get("status") == "revoked":
            return {"ok": True, "changed": False, "code": "TELEGRAM_IDENTITY_ALREADY_REVOKED", "error": None, "retry_safe": True}

        now = _now_utc()
        update_business_row("telegram_identity_registry", row_num, {
            "Status": "revoked", "Revoked At": now, "Revoked By": revoked_by, "Revoke Reason": reason.strip(),
        })

        reread = find_row_by_id("telegram_identity_registry", telegram_identity_id)
        if reread is None or _telegram_identity_row_to_dict(reread[1]).get("status") != "revoked":
            log.error(f"revoke_telegram_identity({telegram_identity_id}) post-write verification failed")
            return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_POST_WRITE_VERIFICATION_FAILED", "error": None, "retry_safe": False}

        return {"ok": True, "changed": True, "code": "TELEGRAM_IDENTITY_REVOKED", "error": None, "retry_safe": True}
    except Exception as exc:
        log.error(f"revoke_telegram_identity({telegram_identity_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "TELEGRAM_IDENTITY_WRITE_FAILED", "error": None, "retry_safe": False}


# ─────────────────────────────────────────────────────────────
# Access role assignments
# ─────────────────────────────────────────────────────────────

def assign_access_role(employee_id: str, role: str, *, assigned_by: str, effective_from: str = "", effective_until: str = "") -> dict:
    """
    Phase 17B has no authorization domain yet — this function CANNOT
    prove the caller is entitled to grant OWNER (that requires
    resolving the caller's own active roles, which belongs to Phase
    17C). OWNER is therefore categorically rejected here; the only
    permitted way to create an OWNER assignment in this phase is the
    dedicated, explicit owner-bootstrap orchestration
    (business_builder.bootstrap_owner_from_env()), which never calls
    this function.
    """
    if not employee_id:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "access_role_assignment_id": "", "retry_safe": True}
    if not assigned_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "access_role_assignment_id": "", "retry_safe": True}
    if not is_valid_access_role(role):
        return {"ok": False, "changed": False, "code": "INVALID_ROLE", "error": None, "access_role_assignment_id": "", "retry_safe": True}
    if role == "OWNER":
        return {"ok": False, "changed": False, "code": "OWNER_ROLE_REQUIRES_AUTHORIZATION_DOMAIN", "error": None, "access_role_assignment_id": "", "retry_safe": True}

    if find_employee(employee_id) is None:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "access_role_assignment_id": "", "retry_safe": True}

    for existing in find_active_role_assignments(employee_id):
        if existing.get("role") == role:
            return {"ok": False, "changed": False, "code": "DUPLICATE_ACTIVE_ROLE_ASSIGNMENT", "error": None, "access_role_assignment_id": "", "retry_safe": True}

    try:
        from business_core.sheets import generate_next_id, append_business_row, row_from_header_map, get_business_sheet, find_row_by_id

        sheet = get_business_sheet("access_role_assignments")
        headers = sheet.row_values(1)
        access_role_assignment_id = generate_next_id("access_role_assignments")
        now = _now_utc()

        values = {
            "Access Role Assignment ID": access_role_assignment_id, "Employee ID": employee_id,
            "Role": role, "Status": "active",
            "Effective From": effective_from, "Effective Until": effective_until,
            "Assigned At": now, "Assigned By": assigned_by,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        row = row_from_header_map(headers, values)
        append_business_row("access_role_assignments", row)

        reread = find_row_by_id("access_role_assignments", access_role_assignment_id)
        if reread is None:
            log.error(f"assign_access_role({access_role_assignment_id}) post-write verification: row missing")
            return {"ok": False, "changed": False, "code": "ACCESS_ROLE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": False}
        saved = _access_role_assignment_row_to_dict(reread[1])
        if saved.get("role") != role or saved.get("status") != "active" or saved.get("employee_id") != employee_id:
            log.error(f"assign_access_role({access_role_assignment_id}) post-write verification: field mismatch")
            return {"ok": False, "changed": False, "code": "ACCESS_ROLE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": False}

        log.info(f"assign_access_role: {access_role_assignment_id} employee={employee_id} role={role}")
        return {"ok": True, "changed": True, "code": "ACCESS_ROLE_ASSIGNED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": True}
    except Exception as exc:
        log.error(f"assign_access_role error: {exc}")
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_WRITE_FAILED", "error": None, "access_role_assignment_id": "", "retry_safe": False}


def revoke_access_role(access_role_assignment_id: str, *, reason: str, revoked_by: str) -> dict:
    """
    Same OWNER-protection reasoning as assign_access_role(): this
    function cannot prove the caller is an OWNER, so revoking an
    OWNER assignment is categorically rejected here. Real OWNER
    revoke arrives with the authorization domain (Phase 17C/17G).
    """
    if not access_role_assignment_id:
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_ASSIGNMENT_NOT_FOUND", "error": None, "retry_safe": True}
    if not reason or not reason.strip():
        return {"ok": False, "changed": False, "code": "REVOKE_REASON_REQUIRED", "error": None, "retry_safe": True}
    if not revoked_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "retry_safe": True}

    from business_core.sheets import find_row_by_id, update_business_row

    found = find_row_by_id("access_role_assignments", access_role_assignment_id)
    if not found:
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_ASSIGNMENT_NOT_FOUND", "error": None, "retry_safe": True}
    row_num, v = found
    current = _access_role_assignment_row_to_dict(v)

    if current.get("role") == "OWNER":
        return {"ok": False, "changed": False, "code": "OWNER_ROLE_REQUIRES_AUTHORIZATION_DOMAIN", "error": None, "retry_safe": True}
    if current.get("status") == "revoked":
        return {"ok": True, "changed": False, "code": "ACCESS_ROLE_ALREADY_REVOKED", "error": None, "retry_safe": True}

    try:
        now = _now_utc()
        update_business_row("access_role_assignments", row_num, {
            "Status": "revoked", "Revoked At": now, "Revoked By": revoked_by, "Revoke Reason": reason.strip(),
        })
        reread = find_row_by_id("access_role_assignments", access_role_assignment_id)
        if reread is None or _access_role_assignment_row_to_dict(reread[1]).get("status") != "revoked":
            log.error(f"revoke_access_role({access_role_assignment_id}) post-write verification failed")
            return {"ok": False, "changed": False, "code": "ACCESS_ROLE_POST_WRITE_VERIFICATION_FAILED", "error": None, "retry_safe": False}
        return {"ok": True, "changed": True, "code": "ACCESS_ROLE_REVOKED", "error": None, "retry_safe": True}
    except Exception as exc:
        log.error(f"revoke_access_role({access_role_assignment_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_WRITE_FAILED", "error": None, "retry_safe": False}


# ─────────────────────────────────────────────────────────────
# Access scope assignments
# ─────────────────────────────────────────────────────────────

def _scope_target_key(scope_type: str, business_id: str, object_id: str) -> tuple:
    return (scope_type, business_id, object_id)


def assign_access_scope(
    employee_id: str, access_role_assignment_id: str, scope_type: str, *,
    business_id: str = "", object_id: str = "", assigned_by: str,
    effective_from: str = "", effective_until: str = "",
) -> dict:
    """
    ALL_BUSINESSES: Business ID and Object ID must both be empty.
    SELECTED_BUSINESSES: Business ID required, Object ID must be
        empty — one row per business (never a comma-list).
    ASSIGNED_OBJECTS_ONLY: Object ID required, directly supplied by
        the caller — never derived from Stage/Task/Role data (no
        reliable canonical source exists in this repository, per the
        Phase 17A/17B audits).
    """
    if not employee_id:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    if not assigned_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    if not is_valid_scope_type(scope_type):
        return {"ok": False, "changed": False, "code": "INVALID_SCOPE_TYPE", "error": None, "access_scope_assignment_id": "", "retry_safe": True}

    if scope_type == "ALL_BUSINESSES":
        if business_id or object_id:
            return {"ok": False, "changed": False, "code": "SCOPE_TARGET_NOT_ALLOWED", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    elif scope_type == "SELECTED_BUSINESSES":
        if not business_id or object_id:
            return {"ok": False, "changed": False, "code": "SCOPE_TARGET_REQUIRED", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    elif scope_type == "ASSIGNED_OBJECTS_ONLY":
        if not object_id:
            return {"ok": False, "changed": False, "code": "SCOPE_TARGET_REQUIRED", "error": None, "access_scope_assignment_id": "", "retry_safe": True}

    if find_employee(employee_id) is None:
        return {"ok": False, "changed": False, "code": "EMPLOYEE_NOT_FOUND", "error": None, "access_scope_assignment_id": "", "retry_safe": True}

    from business_core.sheets import find_row_by_id
    role_found = find_row_by_id("access_role_assignments", access_role_assignment_id)
    if not role_found:
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_ASSIGNMENT_NOT_FOUND", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    role_row = _access_role_assignment_row_to_dict(role_found[1])
    if role_row.get("employee_id") != employee_id:
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_ASSIGNMENT_EMPLOYEE_MISMATCH", "error": None, "access_scope_assignment_id": "", "retry_safe": True}
    if role_row.get("status") != "active":
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_ASSIGNMENT_NOT_ACTIVE", "error": None, "access_scope_assignment_id": "", "retry_safe": True}

    target_key = _scope_target_key(scope_type, business_id, object_id)
    for existing in find_active_scope_assignments(employee_id, access_role_assignment_id):
        existing_key = _scope_target_key(existing.get("scope_type", ""), existing.get("business_id", ""), existing.get("object_id", ""))
        if existing_key == target_key:
            return {"ok": False, "changed": False, "code": "DUPLICATE_ACTIVE_SCOPE", "error": None, "access_scope_assignment_id": "", "retry_safe": True}

    try:
        from business_core.sheets import generate_next_id, append_business_row, row_from_header_map, get_business_sheet

        sheet = get_business_sheet("access_scope_assignments")
        headers = sheet.row_values(1)
        access_scope_assignment_id = generate_next_id("access_scope_assignments")
        now = _now_utc()

        values = {
            "Access Scope Assignment ID": access_scope_assignment_id, "Employee ID": employee_id,
            "Access Role Assignment ID": access_role_assignment_id, "Scope Type": scope_type,
            "Business ID": business_id, "Object ID": object_id,
            "Status": "active", "Effective From": effective_from, "Effective Until": effective_until,
            "Assigned At": now, "Assigned By": assigned_by,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        row = row_from_header_map(headers, values)
        append_business_row("access_scope_assignments", row)

        reread = find_row_by_id("access_scope_assignments", access_scope_assignment_id)
        if reread is None:
            log.error(f"assign_access_scope({access_scope_assignment_id}) post-write verification: row missing")
            return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_scope_assignment_id": access_scope_assignment_id, "retry_safe": False}
        saved = _access_scope_assignment_row_to_dict(reread[1])
        if saved.get("scope_type") != scope_type or saved.get("status") != "active" or saved.get("employee_id") != employee_id:
            log.error(f"assign_access_scope({access_scope_assignment_id}) post-write verification: field mismatch")
            return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_scope_assignment_id": access_scope_assignment_id, "retry_safe": False}

        log.info(f"assign_access_scope: {access_scope_assignment_id} employee={employee_id} scope_type={scope_type}")
        return {"ok": True, "changed": True, "code": "ACCESS_SCOPE_ASSIGNED", "error": None, "access_scope_assignment_id": access_scope_assignment_id, "retry_safe": True}
    except Exception as exc:
        log.error(f"assign_access_scope error: {exc}")
        return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_WRITE_FAILED", "error": None, "access_scope_assignment_id": "", "retry_safe": False}


def revoke_access_scope(access_scope_assignment_id: str, *, reason: str, revoked_by: str) -> dict:
    """active -> revoked only. A revoked row is never reactivated —
    a re-grant always creates a new row via assign_access_scope()."""
    if not access_scope_assignment_id:
        return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_ASSIGNMENT_NOT_FOUND", "error": None, "retry_safe": True}
    if not reason or not reason.strip():
        return {"ok": False, "changed": False, "code": "REVOKE_REASON_REQUIRED", "error": None, "retry_safe": True}
    if not revoked_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "retry_safe": True}

    from business_core.sheets import find_row_by_id, update_business_row

    found = find_row_by_id("access_scope_assignments", access_scope_assignment_id)
    if not found:
        return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_ASSIGNMENT_NOT_FOUND", "error": None, "retry_safe": True}
    row_num, v = found
    current = _access_scope_assignment_row_to_dict(v)
    if current.get("status") == "revoked":
        return {"ok": True, "changed": False, "code": "ACCESS_SCOPE_ALREADY_REVOKED", "error": None, "retry_safe": True}

    try:
        now = _now_utc()
        update_business_row("access_scope_assignments", row_num, {
            "Status": "revoked", "Revoked At": now, "Revoked By": revoked_by, "Revoke Reason": reason.strip(),
        })
        reread = find_row_by_id("access_scope_assignments", access_scope_assignment_id)
        if reread is None or _access_scope_assignment_row_to_dict(reread[1]).get("status") != "revoked":
            log.error(f"revoke_access_scope({access_scope_assignment_id}) post-write verification failed")
            return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_POST_WRITE_VERIFICATION_FAILED", "error": None, "retry_safe": False}
        return {"ok": True, "changed": True, "code": "ACCESS_SCOPE_REVOKED", "error": None, "retry_safe": True}
    except Exception as exc:
        log.error(f"revoke_access_scope({access_scope_assignment_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "ACCESS_SCOPE_WRITE_FAILED", "error": None, "retry_safe": False}


# ─────────────────────────────────────────────────────────────
# Bootstrap-only OWNER role write (Phase 17B)
#
# Reserved EXCLUSIVELY for business_builder.bootstrap_owner_from_env().
# assign_access_role() above categorically rejects Role == "OWNER"
# because this module cannot prove a caller is authorized to grant
# ownership (no authorization domain exists yet — Phase 17C). This
# private function exists only so the explicit, env-driven,
# never-automatic bootstrap orchestration has a way to write the one
# OWNER row it is specifically designed to create. No other caller
# anywhere in this codebase may use it (architecture-guard tested).
# ─────────────────────────────────────────────────────────────

def _bootstrap_assign_owner_role(employee_id: str, *, assigned_by: str) -> dict:
    if not employee_id or not assigned_by:
        return {"ok": False, "changed": False, "code": "ACTOR_REQUIRED", "error": None, "access_role_assignment_id": "", "retry_safe": True}

    try:
        from business_core.sheets import generate_next_id, append_business_row, row_from_header_map, get_business_sheet, find_row_by_id

        sheet = get_business_sheet("access_role_assignments")
        headers = sheet.row_values(1)
        access_role_assignment_id = generate_next_id("access_role_assignments")
        now = _now_utc()

        values = {
            "Access Role Assignment ID": access_role_assignment_id, "Employee ID": employee_id,
            "Role": "OWNER", "Status": "active",
            "Effective From": "", "Effective Until": "",
            "Assigned At": now, "Assigned By": assigned_by,
            "Revoked At": "", "Revoked By": "", "Revoke Reason": "",
        }
        row = row_from_header_map(headers, values)
        append_business_row("access_role_assignments", row)

        reread = find_row_by_id("access_role_assignments", access_role_assignment_id)
        if reread is None:
            return {"ok": False, "changed": False, "code": "ACCESS_ROLE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": False}
        saved = _access_role_assignment_row_to_dict(reread[1])
        if saved.get("role") != "OWNER" or saved.get("status") != "active" or saved.get("employee_id") != employee_id:
            return {"ok": False, "changed": False, "code": "ACCESS_ROLE_POST_WRITE_VERIFICATION_FAILED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": False}

        log.info(f"_bootstrap_assign_owner_role: {access_role_assignment_id} employee={employee_id}")
        return {"ok": True, "changed": True, "code": "ACCESS_ROLE_ASSIGNED", "error": None, "access_role_assignment_id": access_role_assignment_id, "retry_safe": True}
    except Exception as exc:
        log.error(f"_bootstrap_assign_owner_role error: {exc}")
        return {"ok": False, "changed": False, "code": "ACCESS_ROLE_WRITE_FAILED", "error": None, "access_role_assignment_id": "", "retry_safe": False}
