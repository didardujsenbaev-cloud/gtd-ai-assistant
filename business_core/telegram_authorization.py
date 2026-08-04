"""
Telegram Authorization Adapter — Phase 17D.

The ONLY place in this codebase allowed to translate a Telegram
`Update` into a call against the pure, synchronous Authorization
Domain (business_core.authorization). No Telegram handler may call
authorize_business_core_access()/get_business_core_access_summary()
directly — every call must go through one of the two public async
functions in this module.

Both authorize_business_core_access() and get_business_core_access_summary()
are synchronous and may perform blocking Google Sheets network reads
(through identity_manager -> sheets.py -> gspread). Every call to either
is therefore offloaded via `await asyncio.to_thread(...)` so the asyncio
event loop is never blocked (Phase 17D-A1 correction).

Identity is sourced ONLY from `update.effective_user.id` — never a
username, display name, phone number, or caller-supplied argument.
Chat-type policy (private-chat-only) is enforced here, never inside
authorization.py, which stays transport-neutral.

No cache. No writes. No persistent audit logging (deferred to 17H).
Not wired to any existing Business Core command in this phase.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from business_core.authorization import (
    authorize_business_core_access,
    get_business_core_access_summary,
)

# ─────────────────────────────────────────────────────────────
# Closed transport decision-code enum — shared by both adapters
# ─────────────────────────────────────────────────────────────

TELEGRAM_AUTHZ_CODES = (
    "TELEGRAM_ACCESS_ALLOWED",
    "TELEGRAM_SUMMARY_AVAILABLE",
    "PRIVATE_CHAT_REQUIRED",
    "TELEGRAM_USER_NOT_FOUND",
    "INVALID_TELEGRAM_UPDATE",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_UNAVAILABLE",
    "ACCESS_SUMMARY_UNAVAILABLE",
)

_DENIAL_MESSAGE_KEYS = {
    "TELEGRAM_IDENTITY_NOT_FOUND": "identity_not_recognized",
    "TELEGRAM_IDENTITY_AMBIGUOUS": "identity_not_recognized",
    "EMPLOYEE_NOT_FOUND": "identity_not_recognized",
    "EMPLOYEE_PENDING": "employee_pending",
    "EMPLOYEE_DISABLED": "employee_disabled",
    "NO_ACTIVE_ROLE": "no_active_role",
    "ROLE_NOT_PERMITTED": "role_not_permitted",
    "NO_LINKED_SCOPE": "no_matching_scope",
    "SCOPE_NOT_MATCHED": "no_matching_scope",
    "MALFORMED_ROLE_ASSIGNMENT": "no_active_role",
    "MALFORMED_SCOPE_ASSIGNMENT": "no_matching_scope",
    "ASSIGNMENT_NOT_YET_EFFECTIVE": "no_active_role",
    "ASSIGNMENT_EXPIRED": "no_active_role",
    "INVALID_TELEGRAM_USER_ID": "identity_not_recognized",
    "INVALID_RESOURCE": "temporarily_unavailable",
    "INVALID_ACTION": "temporarily_unavailable",
    "TARGET_REQUIRED": "temporarily_unavailable",
}


# ─────────────────────────────────────────────────────────────
# Shared private transport helpers — used by BOTH public adapters
# ─────────────────────────────────────────────────────────────

def _resolve_chat_context(update) -> dict:
    """Never raises. Returns:
        {"ok": bool, "chat_type": str | None, "is_private_chat": bool, "code": str | None}
    ok=False means the update itself was malformed (INVALID_TELEGRAM_UPDATE);
    ok=True with is_private_chat=False means a real, well-formed non-private
    chat (PRIVATE_CHAT_REQUIRED)."""
    if update is None:
        return {"ok": False, "chat_type": None, "is_private_chat": False, "code": "INVALID_TELEGRAM_UPDATE"}

    try:
        effective_chat = update.effective_chat
    except AttributeError:
        return {"ok": False, "chat_type": None, "is_private_chat": False, "code": "INVALID_TELEGRAM_UPDATE"}

    if effective_chat is None:
        return {"ok": True, "chat_type": None, "is_private_chat": False, "code": "PRIVATE_CHAT_REQUIRED"}

    chat_type = getattr(effective_chat, "type", None)
    if not chat_type:
        return {"ok": True, "chat_type": None, "is_private_chat": False, "code": "PRIVATE_CHAT_REQUIRED"}

    if chat_type != "private":
        return {"ok": True, "chat_type": chat_type, "is_private_chat": False, "code": "PRIVATE_CHAT_REQUIRED"}

    return {"ok": True, "chat_type": chat_type, "is_private_chat": True, "code": None}


def _resolve_telegram_user_id(update) -> dict:
    """Never raises. Returns:
        {"ok": bool, "telegram_user_id": str | int | None, "code": str | None}
    Reads ONLY update.effective_user.id — no username, phone, or
    display name is ever inspected."""
    try:
        effective_user = update.effective_user
    except AttributeError:
        return {"ok": False, "telegram_user_id": None, "code": "INVALID_TELEGRAM_UPDATE"}

    if effective_user is None:
        return {"ok": False, "telegram_user_id": None, "code": "TELEGRAM_USER_NOT_FOUND"}

    user_id = getattr(effective_user, "id", None)
    if user_id is None:
        return {"ok": False, "telegram_user_id": None, "code": "TELEGRAM_USER_NOT_FOUND"}

    return {"ok": True, "telegram_user_id": user_id, "code": None}


def _base_transport_fields(chat_ctx: dict, telegram_user_id=None, telegram_actor=None) -> dict:
    return {
        "telegram_user_id": str(telegram_user_id) if telegram_user_id is not None else None,
        "telegram_actor": telegram_actor,
        "chat_type": chat_ctx.get("chat_type"),
        "is_private_chat": chat_ctx.get("is_private_chat", False),
    }


# ─────────────────────────────────────────────────────────────
# Phase 17E-1: public, synchronous, read-free transport preflight.
#
# Reuses the exact same private helpers the two async adapters above
# already use — never duplicates their branching logic. Answers ONLY
# "is this a well-formed private-chat request with a resolvable
# Telegram User ID" — nothing about Business Core identity or
# authorization. Performs zero Google Sheets reads, zero
# identity-registry reads, zero Authorization Domain calls, zero
# asyncio.to_thread (there is nothing to offload — no I/O happens
# here), zero writes, zero caching. Callers (Telegram command
# handlers) use this to reject group/malformed/userless requests
# BEFORE any exact-ID Sheets lookup runs — see Phase 17E-A2.
# ─────────────────────────────────────────────────────────────

def validate_telegram_business_core_transport(update) -> dict:
    """
    Synchronous. valid=True means only: the Update shape is
    acceptable, effective_chat resolves, the chat type is private,
    effective_user resolves, and effective_user.id exists. It does
    NOT mean the Telegram user has a registered Business Core
    identity, an active Employee, or any authorization — those are
    only ever determined by authorize_telegram_business_core_request's
    own Sheets-backed authorize_business_core_access call.
    """
    chat_ctx = _resolve_chat_context(update)
    if not chat_ctx["ok"]:
        return {
            "ok": False, "valid": False, "code": chat_ctx["code"], "error": None, "retry_safe": False,
            "telegram_user_id": None, "chat_type": None, "is_private_chat": False,
            "user_message_key": None,
        }
    if not chat_ctx["is_private_chat"]:
        return {
            "ok": True, "valid": False, "code": "PRIVATE_CHAT_REQUIRED", "error": None, "retry_safe": True,
            "telegram_user_id": None, "chat_type": chat_ctx["chat_type"], "is_private_chat": False,
            "user_message_key": "private_chat_required",
        }

    user_ctx = _resolve_telegram_user_id(update)
    if not user_ctx["ok"]:
        ok = user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND"
        return {
            "ok": ok, "valid": False, "code": user_ctx["code"], "error": None, "retry_safe": ok,
            "telegram_user_id": None, "chat_type": chat_ctx["chat_type"], "is_private_chat": True,
            "user_message_key": "identity_not_recognized" if ok else None,
        }

    return {
        "ok": True, "valid": True, "code": None, "error": None, "retry_safe": True,
        "telegram_user_id": str(user_ctx["telegram_user_id"]),
        "chat_type": chat_ctx["chat_type"], "is_private_chat": True,
        "user_message_key": None,
    }


# ─────────────────────────────────────────────────────────────
# A. Authorization adapter
# ─────────────────────────────────────────────────────────────

async def authorize_telegram_business_core_request(
    update,
    *,
    resource: str,
    action: str,
    business_id: str = "",
    object_id: str = "",
) -> dict:
    """
    Telegram-facing wrapper around authorize_business_core_access().
    Enforces private-chat-only policy, extracts identity solely from
    update.effective_user.id, offloads the synchronous domain call
    via asyncio.to_thread, and normalizes the result. Fail-closed:
    no exception anywhere in this function can result in allowed=True.
    """
    result = {
        "ok": True, "allowed": False, "code": None, "error": None, "retry_safe": True,
        "telegram_user_id": None, "telegram_actor": None,
        "chat_type": None, "is_private_chat": False,
        "resource": resource, "action": action,
        "business_id": business_id, "object_id": object_id,
        "authorization_result": None, "user_message_key": None,
    }

    try:
        chat_ctx = _resolve_chat_context(update)
        result.update(_base_transport_fields(chat_ctx))
        if not chat_ctx["ok"]:
            result["ok"] = False
            result["code"] = chat_ctx["code"]
            result["retry_safe"] = False
            result["user_message_key"] = None
            return result
        if not chat_ctx["is_private_chat"]:
            result["code"] = "PRIVATE_CHAT_REQUIRED"
            result["retry_safe"] = True
            result["user_message_key"] = "private_chat_required"
            return result

        user_ctx = _resolve_telegram_user_id(update)
        if not user_ctx["ok"]:
            result["ok"] = user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND"
            result["code"] = user_ctx["code"]
            result["retry_safe"] = user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND"
            result["user_message_key"] = "identity_not_recognized" if user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND" else None
            return result

        telegram_user_id = user_ctx["telegram_user_id"]
        result["telegram_user_id"] = str(telegram_user_id)

        authorization_result = await asyncio.to_thread(
            authorize_business_core_access,
            telegram_user_id,
            resource=resource,
            action=action,
            business_id=business_id,
            object_id=object_id,
        )
        result["authorization_result"] = authorization_result
        result["telegram_actor"] = authorization_result.get("telegram_actor")

        if not authorization_result.get("ok"):
            result["ok"] = False
            result["allowed"] = False
            result["code"] = "AUTHORIZATION_UNAVAILABLE"
            result["retry_safe"] = False
            result["user_message_key"] = "temporarily_unavailable"
            return result

        if authorization_result.get("allowed"):
            result["ok"] = True
            result["allowed"] = True
            result["code"] = "TELEGRAM_ACCESS_ALLOWED"
            result["retry_safe"] = True
            result["user_message_key"] = None
            return result

        result["ok"] = True
        result["allowed"] = False
        result["code"] = "AUTHORIZATION_DENIED"
        result["retry_safe"] = authorization_result.get("retry_safe", True)
        result["user_message_key"] = _DENIAL_MESSAGE_KEYS.get(
            authorization_result.get("code"), "no_matching_scope",
        )
        return result

    except Exception as exc:
        result["ok"] = False
        result["allowed"] = False
        result["code"] = "AUTHORIZATION_UNAVAILABLE"
        result["error"] = str(exc)
        result["retry_safe"] = False
        result["user_message_key"] = "temporarily_unavailable"
        return result


# ─────────────────────────────────────────────────────────────
# B. Access-summary adapter
# ─────────────────────────────────────────────────────────────

async def get_telegram_business_core_access_summary(update) -> dict:
    """
    Telegram-facing wrapper around get_business_core_access_summary().
    Same private-chat/identity-extraction/thread-offload discipline as
    authorize_telegram_business_core_request(). `available` means only
    that the summary was computed successfully — it is NOT an
    authorization allow decision. A recognized-but-pending/disabled/
    roleless user can still get available=True with
    access_summary_result["can_use_business_core"]=False.
    """
    result = {
        "ok": True, "available": False, "code": None, "error": None, "retry_safe": True,
        "telegram_user_id": None, "telegram_actor": None,
        "chat_type": None, "is_private_chat": False,
        "access_summary_result": None, "user_message_key": None,
    }

    try:
        chat_ctx = _resolve_chat_context(update)
        result.update(_base_transport_fields(chat_ctx))
        if not chat_ctx["ok"]:
            result["ok"] = False
            result["code"] = chat_ctx["code"]
            result["retry_safe"] = False
            result["user_message_key"] = None
            return result
        if not chat_ctx["is_private_chat"]:
            result["code"] = "PRIVATE_CHAT_REQUIRED"
            result["retry_safe"] = True
            result["user_message_key"] = "private_chat_required"
            return result

        user_ctx = _resolve_telegram_user_id(update)
        if not user_ctx["ok"]:
            result["ok"] = user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND"
            result["code"] = user_ctx["code"]
            result["retry_safe"] = user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND"
            result["user_message_key"] = "identity_not_recognized" if user_ctx["code"] == "TELEGRAM_USER_NOT_FOUND" else None
            return result

        telegram_user_id = user_ctx["telegram_user_id"]
        result["telegram_user_id"] = str(telegram_user_id)

        summary_result = await asyncio.to_thread(
            get_business_core_access_summary,
            telegram_user_id,
        )
        result["access_summary_result"] = summary_result
        result["telegram_actor"] = summary_result.get("telegram_actor")

        if not summary_result.get("ok"):
            result["ok"] = False
            result["available"] = False
            result["code"] = "ACCESS_SUMMARY_UNAVAILABLE"
            result["retry_safe"] = False
            result["user_message_key"] = "temporarily_unavailable"
            return result

        result["ok"] = True
        result["available"] = True
        result["code"] = "TELEGRAM_SUMMARY_AVAILABLE"
        result["retry_safe"] = True
        result["user_message_key"] = None
        return result

    except Exception as exc:
        result["ok"] = False
        result["available"] = False
        result["code"] = "ACCESS_SUMMARY_UNAVAILABLE"
        result["error"] = str(exc)
        result["retry_safe"] = False
        result["user_message_key"] = "temporarily_unavailable"
        return result


# ─────────────────────────────────────────────────────────────
# User-facing message keys (Russian) — handlers decide whether/what
# to send; this module never sends a message itself.
# ─────────────────────────────────────────────────────────────

USER_MESSAGES = {
    "private_chat_required": "Эта команда доступна только в личном чате с ботом.",
    "identity_not_recognized": "Ваш аккаунт не подключён к Business Core. Обратитесь к владельцу.",
    "employee_pending": "Ваш доступ к Business Core ещё не активирован.",
    "employee_disabled": "Ваш доступ к Business Core отключён.",
    "no_active_role": "У вас нет активной роли в Business Core.",
    "no_matching_scope": "У вас нет доступа к этому разделу.",
    "role_not_permitted": "Ваша роль не позволяет выполнить это действие.",
    "temporarily_unavailable": "Временная ошибка проверки доступа. Попробуйте ещё раз позже.",
}
