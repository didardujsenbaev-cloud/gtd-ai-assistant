"""
Authorization Domain — Phase 17C.

Pure, read-only evaluation of Business Core access from the four
Phase 17B identity registries (Employee Registry, Telegram Identity
Registry, Access Role Assignments, Access Scope Assignments). Mirrors
identity_manager.py's isolation discipline: no writes, no Telegram
imports, no other domain-manager imports, no Google Sheets helpers
called directly — only business_core.identity_manager's public
read-only functions/constants.

This module intentionally does NOT resolve downstream entity
ownership (Document -> Object -> Business, etc.). Callers of
authorize_business_core_access() MUST resolve canonical
business_id/object_id from production entity records themselves
(e.g. by reading the target Document's own stored Object ID) before
calling this function — a caller-supplied Telegram argument must
never be trusted as proof of ownership. This is a deliberate V1
boundary: adding cross-registry reads here would break this module's
"only imports identity_manager" isolation guarantee. See Phase
17C-A1/17C-A2 architecture audits for the full reasoning.

No caching. Access must be re-evaluated on every call so that a
disable/revoke takes effect on the very next authorization check.

Not wired to Telegram in this phase (Phase 17D+).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from business_core import identity_manager as im

# ─────────────────────────────────────────────────────────────
# Closed enums
# ─────────────────────────────────────────────────────────────

AUTHZ_RESOURCES = (
    "BUSINESS",
    "CLIENT",
    "OBJECT",
    "DOCUMENT",
    "OPERATIONAL",
    "FINANCE",
    "ACCESS_CONTROL",
)

AUTHZ_ACTIONS = (
    "READ",
    "CREATE",
    "UPDATE",
    "ARCHIVE",
    "ASSIGN",
    "MANAGE_ACCESS",
)

AUTHZ_DECISION_CODES = (
    "ACCESS_ALLOWED",
    "INVALID_TELEGRAM_USER_ID",
    "INVALID_RESOURCE",
    "INVALID_ACTION",
    "TARGET_REQUIRED",
    "TELEGRAM_IDENTITY_NOT_FOUND",
    "TELEGRAM_IDENTITY_AMBIGUOUS",
    "EMPLOYEE_NOT_FOUND",
    "EMPLOYEE_PENDING",
    "EMPLOYEE_DISABLED",
    "NO_ACTIVE_ROLE",
    "ROLE_NOT_PERMITTED",
    "MALFORMED_ROLE_ASSIGNMENT",
    "NO_LINKED_SCOPE",
    "SCOPE_NOT_MATCHED",
    "MALFORMED_SCOPE_ASSIGNMENT",
    "ASSIGNMENT_NOT_YET_EFFECTIVE",
    "ASSIGNMENT_EXPIRED",
    "AUTHORIZATION_READ_FAILED",
)

# Deterministic denial precedence — most-preferred (most specific /
# most accurate) first. Clean, explainable denials always outrank an
# unrelated malformed-data flag from a different candidate row.
_DENIAL_PRECEDENCE = (
    "SCOPE_NOT_MATCHED",
    "NO_LINKED_SCOPE",
    "ASSIGNMENT_EXPIRED",
    "ASSIGNMENT_NOT_YET_EFFECTIVE",
    "ROLE_NOT_PERMITTED",
    "MALFORMED_SCOPE_ASSIGNMENT",
    "MALFORMED_ROLE_ASSIGNMENT",
    "NO_ACTIVE_ROLE",
)

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

_TARGETLESS_BUSINESS_READ_ROLES = ("OWNER", "ADMIN")


# ─────────────────────────────────────────────────────────────
# Role / resource / action matrix
# ─────────────────────────────────────────────────────────────

_ALL_ACTIONS = frozenset(AUTHZ_ACTIONS)
_WRITE_LIGHT = frozenset({"READ", "CREATE", "UPDATE"})
_READ_ONLY = frozenset({"READ"})
_DOCUMENT_SPECIALIST_DOC_ACTIONS = frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE"})
_NONE = frozenset()

ROLE_RESOURCE_ACTION_MATRIX = {
    "OWNER": {
        "BUSINESS": _ALL_ACTIONS, "CLIENT": _ALL_ACTIONS, "OBJECT": _ALL_ACTIONS,
        "DOCUMENT": _ALL_ACTIONS, "OPERATIONAL": _ALL_ACTIONS, "FINANCE": _ALL_ACTIONS,
        "ACCESS_CONTROL": _ALL_ACTIONS,
    },
    "ADMIN": {
        "BUSINESS": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "CLIENT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "OBJECT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "DOCUMENT": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "OPERATIONAL": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "FINANCE": frozenset({"READ", "CREATE", "UPDATE", "ARCHIVE", "ASSIGN"}),
        "ACCESS_CONTROL": _NONE,
    },
    "COORDINATOR": {
        "BUSINESS": _NONE, "CLIENT": _NONE,
        "OBJECT": frozenset({"READ", "UPDATE"}),
        "DOCUMENT": _WRITE_LIGHT,
        "OPERATIONAL": _WRITE_LIGHT,
        "FINANCE": _NONE, "ACCESS_CONTROL": _NONE,
    },
    "DOCUMENT_SPECIALIST": {
        "BUSINESS": _NONE,
        "CLIENT": _READ_ONLY,
        "OBJECT": _READ_ONLY,
        "DOCUMENT": _DOCUMENT_SPECIALIST_DOC_ACTIONS,
        "OPERATIONAL": _READ_ONLY,
        "FINANCE": _NONE, "ACCESS_CONTROL": _NONE,
    },
    "VIEWER": {
        "BUSINESS": _READ_ONLY, "CLIENT": _READ_ONLY, "OBJECT": _READ_ONLY,
        "DOCUMENT": _READ_ONLY, "OPERATIONAL": _READ_ONLY, "FINANCE": _READ_ONLY,
        "ACCESS_CONTROL": _NONE,
    },
}


# ─────────────────────────────────────────────────────────────
# Scope-type / resource compatibility
# ─────────────────────────────────────────────────────────────

_SCOPE_RESOURCE_COMPATIBILITY = {
    "ALL_BUSINESSES": frozenset(AUTHZ_RESOURCES),
    "SELECTED_BUSINESSES": frozenset({
        "BUSINESS", "CLIENT", "OBJECT", "DOCUMENT", "OPERATIONAL", "FINANCE",
    }),
    "ASSIGNED_OBJECTS_ONLY": frozenset({"OBJECT", "DOCUMENT", "OPERATIONAL"}),
}

_OBJECT_ADDRESSABLE_RESOURCES = frozenset({"OBJECT", "DOCUMENT", "OPERATIONAL"})


# ─────────────────────────────────────────────────────────────
# Structural target validation (Stage A — zero identity/Sheets reads)
# ─────────────────────────────────────────────────────────────

def _validate_structural_target(resource: str, action: str, business_id: str, object_id: str) -> Optional[str]:
    """Returns None when the request's target shape is structurally
    valid for this resource, else the exact denial code."""
    if resource in ("OBJECT", "DOCUMENT", "OPERATIONAL"):
        if not business_id or not object_id:
            return "TARGET_REQUIRED"
    elif resource in ("CLIENT", "FINANCE"):
        if not business_id:
            return "TARGET_REQUIRED"
    elif resource == "ACCESS_CONTROL":
        if business_id or object_id:
            return "TARGET_REQUIRED"
    elif resource == "BUSINESS":
        if action != "READ" and not business_id:
            return "TARGET_REQUIRED"
        # BUSINESS / READ: business_id may be empty — deferred to the
        # pair-dependent targetless-BUSINESS-READ rule (§14).
    return None


# ─────────────────────────────────────────────────────────────
# Effective-time evaluation
# ─────────────────────────────────────────────────────────────

def _parse_canonical_timestamp(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _in_force_status(effective_from: str, effective_until: str, now_dt: datetime) -> str:
    """Returns one of: 'IN_FORCE', 'NOT_YET_EFFECTIVE', 'EXPIRED', 'MALFORMED'.

    Effective From is inclusive, Effective Until is exclusive:
        in_force = (effective_from == "" OR now >= effective_from)
                   AND (effective_until == "" OR now < effective_until)
    """
    from_dt = None
    if effective_from:
        from_dt = _parse_canonical_timestamp(effective_from)
        if from_dt is None:
            return "MALFORMED"

    until_dt = None
    if effective_until:
        until_dt = _parse_canonical_timestamp(effective_until)
        if until_dt is None:
            return "MALFORMED"

    if from_dt is not None and now_dt < from_dt:
        return "NOT_YET_EFFECTIVE"
    if until_dt is not None and now_dt >= until_dt:
        return "EXPIRED"
    return "IN_FORCE"


# ─────────────────────────────────────────────────────────────
# Target matching
# ─────────────────────────────────────────────────────────────

def _scope_matches_target(scope: dict, resource: str, business_id: str, object_id: str) -> bool:
    scope_type = scope.get("scope_type", "")
    if scope_type == "ALL_BUSINESSES":
        return True
    if scope_type == "SELECTED_BUSINESSES":
        return bool(business_id) and scope.get("business_id", "") == business_id
    if scope_type == "ASSIGNED_OBJECTS_ONLY":
        return bool(object_id) and scope.get("object_id", "") == object_id
    return False


def _targetless_business_read(resource: str, action: str, business_id: str, object_id: str) -> bool:
    return resource == "BUSINESS" and action == "READ" and business_id == "" and object_id == ""


# ─────────────────────────────────────────────────────────────
# Result-building helpers
# ─────────────────────────────────────────────────────────────

def _base_result(*, telegram_user_id, resource, action, business_id, object_id, evaluated_at) -> dict:
    return {
        "ok": True,
        "allowed": False,
        "code": None,
        "error": None,
        "retry_safe": True,
        "telegram_user_id": str(telegram_user_id) if telegram_user_id is not None else "",
        "telegram_actor": None,
        "employee_id": None,
        "roles": [],
        "resource": resource,
        "action": action,
        "matched_role": None,
        "matched_role_assignment_id": None,
        "matched_scope_assignment_id": None,
        "scope_type": None,
        "business_id": business_id,
        "object_id": object_id,
        "evaluated_at": evaluated_at,
        "denial_reason": None,
        "verification_errors": [],
    }


def _deny(result: dict, code: str, *, verification_errors: Optional[list] = None) -> dict:
    result["ok"] = True
    result["allowed"] = False
    result["code"] = code
    result["retry_safe"] = True
    result["denial_reason"] = code
    if verification_errors:
        result["verification_errors"] = verification_errors
    return result


def _read_failed(result: dict, error: str) -> dict:
    result["ok"] = False
    result["allowed"] = False
    result["code"] = "AUTHORIZATION_READ_FAILED"
    result["error"] = error
    result["retry_safe"] = False
    result["denial_reason"] = "AUTHORIZATION_READ_FAILED"
    return result


def _pick_precedence(candidates: set) -> str:
    for code in _DENIAL_PRECEDENCE:
        if code in candidates:
            return code
    return "NO_ACTIVE_ROLE"


def _now_utc() -> str:
    """Same canonical format as identity_manager._now_utc() — kept as
    a local, independent definition rather than importing a private
    symbol, since this module only imports identity_manager's public
    surface."""
    return datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)


# ─────────────────────────────────────────────────────────────
# Canonical public entry point
# ─────────────────────────────────────────────────────────────

def authorize_business_core_access(
    telegram_user_id,
    *,
    resource: str,
    action: str,
    business_id: str = "",
    object_id: str = "",
    now: Optional[str] = None,
) -> dict:
    """
    Pure, read-only, transport-neutral Business Core authorization
    check. Fail-closed by construction: every branch that is not an
    explicit ACCESS_ALLOWED returns allowed=False, and no exception
    raised anywhere in this function can result in allowed=True.

    IMPORTANT — canonical ownership boundary: this function does NOT
    read Document/Object/Roadmap/Client registries and cannot verify
    that object_id actually belongs to business_id. Callers MUST
    resolve business_id/object_id from the target entity's own
    production record (e.g. read the Document row's stored Object ID)
    before calling this function. A raw value typed by a Telegram user
    must never be passed here as if it were already-validated
    ownership — that resolution is the caller's responsibility, not
    this domain's (see Phase 17C-A1/17C-A2 audits).

    telegram_actor is always derived internally from telegram_user_id
    — it is never a caller-suppliable parameter, and no username or
    display-name input is ever accepted or used for resolution.
    """
    evaluated_at = now or _now_utc()
    result = _base_result(
        telegram_user_id=telegram_user_id, resource=resource, action=action,
        business_id=business_id, object_id=object_id, evaluated_at=evaluated_at,
    )

    try:
        # ---- Stage A: structural validation, zero identity/Sheets reads ----
        if not im.is_valid_telegram_user_id(telegram_user_id):
            return _deny(result, "INVALID_TELEGRAM_USER_ID")
        if resource not in AUTHZ_RESOURCES:
            return _deny(result, "INVALID_RESOURCE")
        if action not in AUTHZ_ACTIONS:
            return _deny(result, "INVALID_ACTION")
        target_error = _validate_structural_target(resource, action, business_id, object_id)
        if target_error:
            return _deny(result, target_error)

        now_dt = _parse_canonical_timestamp(evaluated_at)
        if now_dt is None:
            return _read_failed(result, "invalid 'now' evaluation timestamp")

        # ---- Identity resolution ----
        telegram_user_id_str = str(telegram_user_id)
        identities = im.find_active_telegram_identities_by_telegram_user_id(telegram_user_id_str)
        if len(identities) == 0:
            return _deny(result, "TELEGRAM_IDENTITY_NOT_FOUND")
        if len(identities) > 1:
            return _deny(result, "TELEGRAM_IDENTITY_AMBIGUOUS")

        identity = identities[0]
        telegram_actor = im.canonical_telegram_actor(telegram_user_id_str)
        result["telegram_actor"] = telegram_actor

        employee = im.find_employee(identity.get("employee_id", ""))
        if employee is None:
            return _deny(result, "EMPLOYEE_NOT_FOUND")
        result["employee_id"] = employee.get("employee_id")

        employee_status = employee.get("status", "")
        if employee_status == "pending":
            return _deny(result, "EMPLOYEE_PENDING")
        if employee_status == "disabled":
            return _deny(result, "EMPLOYEE_DISABLED")
        if employee_status != "active":
            return _deny(result, "EMPLOYEE_NOT_FOUND")

        employee_id = employee.get("employee_id")

        # ---- ARA/ASA exact-pair evaluation ----
        role_assignments = im.find_role_assignments_by_employee(employee_id, active_only=False)
        role_assignments = sorted(role_assignments, key=lambda ra: ra.get("access_role_assignment_id", ""))

        # First pass: compute the full set of currently-effective roles
        # across ALL role assignments, independent of matching order —
        # "roles" in the result contract must reflect every effective
        # role the Employee holds, not only the ones evaluated before
        # an early allow match short-circuits the pairing loop below.
        effective_roles = []
        for ara in role_assignments:
            if ara.get("employee_id") != employee_id or ara.get("status") != "active":
                continue
            role = ara.get("role", "")
            if role not in im.ACCESS_ROLES:
                continue
            if _in_force_status(ara.get("effective_from", ""), ara.get("effective_until", ""), now_dt) == "IN_FORCE":
                effective_roles.append(role)
        result["roles"] = sorted(set(effective_roles))

        candidates = set()

        for ara in role_assignments:
            if ara.get("employee_id") != employee_id:
                continue
            if ara.get("status") != "active":
                continue

            role = ara.get("role", "")
            if role not in im.ACCESS_ROLES:
                candidates.add("MALFORMED_ROLE_ASSIGNMENT")
                continue

            role_time_status = _in_force_status(ara.get("effective_from", ""), ara.get("effective_until", ""), now_dt)
            if role_time_status == "MALFORMED":
                candidates.add("MALFORMED_ROLE_ASSIGNMENT")
                continue
            if role_time_status == "NOT_YET_EFFECTIVE":
                candidates.add("ASSIGNMENT_NOT_YET_EFFECTIVE")
                continue
            if role_time_status == "EXPIRED":
                candidates.add("ASSIGNMENT_EXPIRED")
                continue

            allowed_actions = ROLE_RESOURCE_ACTION_MATRIX.get(role, {}).get(resource, _NONE)
            if action not in allowed_actions:
                candidates.add("ROLE_NOT_PERMITTED")
                continue

            scopes = im.find_scope_assignments_by_role_assignment(
                ara.get("access_role_assignment_id", ""), active_only=False,
            )
            scopes = sorted(scopes, key=lambda sa: sa.get("access_scope_assignment_id", ""))

            ara_scope_reasons = []
            for asa in scopes:
                if asa.get("employee_id") != ara.get("employee_id"):
                    ara_scope_reasons.append("MALFORMED_SCOPE_ASSIGNMENT")
                    continue
                if asa.get("status") != "active":
                    continue

                scope_type = asa.get("scope_type", "")
                if scope_type not in im.ACCESS_SCOPE_TYPES:
                    ara_scope_reasons.append("MALFORMED_SCOPE_ASSIGNMENT")
                    continue

                scope_time_status = _in_force_status(asa.get("effective_from", ""), asa.get("effective_until", ""), now_dt)
                if scope_time_status == "MALFORMED":
                    ara_scope_reasons.append("MALFORMED_SCOPE_ASSIGNMENT")
                    continue
                if scope_time_status == "NOT_YET_EFFECTIVE":
                    ara_scope_reasons.append("ASSIGNMENT_NOT_YET_EFFECTIVE")
                    continue
                if scope_time_status == "EXPIRED":
                    ara_scope_reasons.append("ASSIGNMENT_EXPIRED")
                    continue

                if resource not in _SCOPE_RESOURCE_COMPATIBILITY.get(scope_type, _NONE):
                    ara_scope_reasons.append("SCOPE_NOT_MATCHED")
                    continue

                if _targetless_business_read(resource, action, business_id, object_id):
                    if role not in _TARGETLESS_BUSINESS_READ_ROLES or scope_type != "ALL_BUSINESSES":
                        ara_scope_reasons.append("SCOPE_NOT_MATCHED")
                        continue
                    matched = True
                else:
                    matched = _scope_matches_target(asa, resource, business_id, object_id)
                    if not matched:
                        ara_scope_reasons.append("SCOPE_NOT_MATCHED")
                        continue

                # Exact valid ARA/ASA pair found.
                result["ok"] = True
                result["allowed"] = True
                result["code"] = "ACCESS_ALLOWED"
                result["retry_safe"] = True
                result["matched_role"] = role
                result["matched_role_assignment_id"] = ara.get("access_role_assignment_id")
                result["matched_scope_assignment_id"] = asa.get("access_scope_assignment_id")
                result["scope_type"] = scope_type
                result["denial_reason"] = None
                return result

            if ara_scope_reasons:
                candidates.update(ara_scope_reasons)
            else:
                candidates.add("NO_LINKED_SCOPE")

        return _deny(result, _pick_precedence(candidates))

    except Exception as exc:
        return _read_failed(result, str(exc))


# ─────────────────────────────────────────────────────────────
# Phase 17D: pure, read-only access-summary operation
#
# Describes the caller's own current identity/Employee/role/scope
# state — it makes NO resource/action allow decision and must never
# be used as an authorization shortcut. Reuses the exact same
# identity-resolution and per-ARA/ASA classification rules as
# authorize_business_core_access() so the two functions can never
# disagree about what is "currently effective."
# ─────────────────────────────────────────────────────────────

def get_business_core_access_summary(telegram_user_id, *, now: Optional[str] = None) -> dict:
    """
    Read-only. Describes the calling Telegram user's own identity,
    Employee status, effective roles, and effective scopes (grouped
    under their exact Access Role Assignment — never combined across
    ARAs). No writes, no cache. Incident/revoked rows are excluded
    naturally by the same active-status/effective-time filtering
    authorize_business_core_access() uses.
    """
    evaluated_at = now or _now_utc()
    result = {
        "ok": True,
        "error": None,
        "retry_safe": True,
        "telegram_user_id": str(telegram_user_id) if telegram_user_id is not None else "",
        "telegram_actor": None,
        "identity_status": "not_found",
        "employee_id": None,
        "employee_status": None,
        "can_use_business_core": False,
        "roles": [],
        "scopes_by_role_assignment": [],
        "malformed_warnings": [],
        "evaluated_at": evaluated_at,
    }

    try:
        if not im.is_valid_telegram_user_id(telegram_user_id):
            result["identity_status"] = "not_found"
            return result

        now_dt = _parse_canonical_timestamp(evaluated_at)
        if now_dt is None:
            return _read_failed_summary(result, "invalid 'now' evaluation timestamp")

        telegram_user_id_str = str(telegram_user_id)
        identities = im.find_active_telegram_identities_by_telegram_user_id(telegram_user_id_str)
        if len(identities) == 0:
            result["identity_status"] = "not_found"
            return result
        if len(identities) > 1:
            result["identity_status"] = "ambiguous"
            return result

        identity = identities[0]
        result["identity_status"] = "resolved"
        result["telegram_actor"] = im.canonical_telegram_actor(telegram_user_id_str)

        employee = im.find_employee(identity.get("employee_id", ""))
        if employee is None:
            return result
        employee_id = employee.get("employee_id")
        result["employee_id"] = employee_id
        result["employee_status"] = employee.get("status")

        if employee.get("status") != "active":
            return result

        role_assignments = im.find_role_assignments_by_employee(employee_id, active_only=False)
        role_assignments = sorted(role_assignments, key=lambda ra: ra.get("access_role_assignment_id", ""))

        effective_roles = []
        malformed = set()
        scopes_by_ara = []
        has_any_effective_scope = False

        for ara in role_assignments:
            if ara.get("employee_id") != employee_id or ara.get("status") != "active":
                continue

            role = ara.get("role", "")
            if role not in im.ACCESS_ROLES:
                malformed.add("MALFORMED_ROLE_ASSIGNMENT")
                continue

            role_time_status = _in_force_status(ara.get("effective_from", ""), ara.get("effective_until", ""), now_dt)
            if role_time_status == "MALFORMED":
                malformed.add("MALFORMED_ROLE_ASSIGNMENT")
                continue
            if role_time_status != "IN_FORCE":
                continue

            effective_roles.append(role)

            scopes = im.find_scope_assignments_by_role_assignment(
                ara.get("access_role_assignment_id", ""), active_only=False,
            )
            scopes = sorted(scopes, key=lambda sa: sa.get("access_scope_assignment_id", ""))

            counts_by_type: dict = {}
            for asa in scopes:
                if asa.get("employee_id") != ara.get("employee_id"):
                    malformed.add("MALFORMED_SCOPE_ASSIGNMENT")
                    continue
                if asa.get("status") != "active":
                    continue

                scope_type = asa.get("scope_type", "")
                if scope_type not in im.ACCESS_SCOPE_TYPES:
                    malformed.add("MALFORMED_SCOPE_ASSIGNMENT")
                    continue

                scope_time_status = _in_force_status(asa.get("effective_from", ""), asa.get("effective_until", ""), now_dt)
                if scope_time_status == "MALFORMED":
                    malformed.add("MALFORMED_SCOPE_ASSIGNMENT")
                    continue
                if scope_time_status != "IN_FORCE":
                    continue

                counts_by_type[scope_type] = counts_by_type.get(scope_type, 0) + 1

            for scope_type, target_count in counts_by_type.items():
                scopes_by_ara.append({
                    "access_role_assignment_id": ara.get("access_role_assignment_id"),
                    "role": role,
                    "scope_type": scope_type,
                    "target_count": target_count,
                })
                has_any_effective_scope = True

        result["roles"] = sorted(set(effective_roles))
        result["scopes_by_role_assignment"] = scopes_by_ara
        result["malformed_warnings"] = sorted(malformed)
        result["can_use_business_core"] = bool(effective_roles) and has_any_effective_scope
        return result

    except Exception as exc:
        return _read_failed_summary(result, str(exc))


def _read_failed_summary(result: dict, error: str) -> dict:
    result["ok"] = False
    result["error"] = error
    result["retry_safe"] = False
    return result
