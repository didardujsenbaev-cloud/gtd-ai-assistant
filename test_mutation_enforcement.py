"""
Phase 17E-2A: targeted-mutation enforcement tests for exactly one
command: /updateinteractionnotes.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

The finder (business_core.interaction_manager.find_interaction_by_id)
is patched at the exact module path the handler imports it from — a
fresh, local `from ... import ...` inside the function body, matching
this repo's established lazy-import convention. The mutator
(business_core.business_builder.update_interaction_notes) is patched
the same way. The Telegram authorization adapter is patched via
"business_core.telegram_authorization.authorize_telegram_business_core_request",
the exact name _authorize_or_reply imports locally at call time.

Unlike Phase 17E-1's read commands, this handler calls the finder
TWICE (first lookup for ownership/authorization, second immediately
before mutation) — tests here assert on call count and call order,
not just presence.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from business_core import telegram_handlers as th


def _run(coro):
    return asyncio.run(coro)


def _make_update(chat_type="private", user_id=570004109):
    update = MagicMock()
    update.effective_chat = SimpleNamespace(type=chat_type) if chat_type is not None else None
    update.effective_user = SimpleNamespace(id=user_id) if user_id is not None else None
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args):
    return SimpleNamespace(args=args)


def _allow_result():
    return {"ok": True, "allowed": True, "code": "TELEGRAM_ACCESS_ALLOWED", "retry_safe": True,
            "authorization_result": {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED"}}


def _deny_result():
    return {"ok": True, "allowed": False, "code": "AUTHORIZATION_DENIED", "retry_safe": True,
            "authorization_result": {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED"}}


def _infra_failure_result():
    return {"ok": False, "allowed": False, "code": "AUTHORIZATION_UNAVAILABLE", "retry_safe": False,
            "authorization_result": None}


_ROW = {
    "Interaction ID": "ACT-001", "Business ID": "BIZ-001", "Caller Idempotency Key": "",
    "Interaction Type": "call", "Direction": "outbound", "Channel ID": "", "Occurred At": "2026-01-01T00:00:00Z",
    "Summary": "s", "Outcome": "", "Lead ID": "", "Client ID": "PRS-1", "Commercial Offer ID": "",
    "Assigned Person ID": "", "External Reference": "", "Status": "active",
    "Created At": "2026-01-01T00:00:00Z", "Created By": "", "Updated At": "", "Archived At": "", "Notes": "",
}
_ROW_OTHER_BIZ = {**_ROW, "Business ID": "BIZ-002"}
_ROW_MISSING_OWNERSHIP = {**_ROW, "Business ID": ""}
_ROW_WHITESPACE_OWNERSHIP = {**_ROW, "Business ID": "   "}

_FINDER_PATH = "business_core.interaction_manager.find_interaction_by_id"
_MUTATOR_PATH = "business_core.business_builder.update_interaction_notes"
_AUTHZ_PATH = "business_core.telegram_authorization.authorize_telegram_business_core_request"

_ID_ARG = "interaction_id=ACT-001"
_NOTES_ARG = "notes=hello"
_ARGS = [_ID_ARG, _NOTES_ARG]


class MutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None,
                                       "interaction_id": "ACT-001", "business_id": "BIZ-001", "changed": True})
        patches.append(patch(_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.updateinteractionnotes_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


# ─────────────────────────────────────────────────────────────
# Transport
# ─────────────────────────────────────────────────────────────

class TestTransport(MutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────

class TestArguments(MutationTestBase):
    def test_missing_interaction_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context([_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_notes_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context([_ID_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_id_unsupported(self):
        update = _make_update()
        with patch(_FINDER_PATH) as mock_finder, patch(_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(["ACT-001", _NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()


# ─────────────────────────────────────────────────────────────
# First lookup
# ─────────────────────────────────────────────────────────────

class TestFirstLookup(MutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) == 1:
                return _ROW
            return {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        self.assertIn("ACT-001", recorded[0][1])

    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_ROW)
        mock_authz.assert_called_once()

    def test_finder_none_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=None)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_none_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=None)
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_finder_exception_zero_authorization_and_mutation(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        mock_authz, mock_mutator = self._run_handler(update, finder_side_effect=boom)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_exception_temporarily_unavailable_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        self._run_handler(update, finder_side_effect=boom)
        text = self._sent_text(update)
        self.assertIn("Временная ошибка", text)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("sheets down", text)

    def test_missing_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Authorization
# ─────────────────────────────────────────────────────────────

class TestAuthorization(MutationTestBase):
    def test_resource_client_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "CLIENT")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_caller_cannot_spoof_ownership(self):
        # notes/interaction_id are the only caller-suppliable args; no
        # business_id/object_id kwarg is ever accepted by the parser.
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn('args.get("business_id"', src)
        self.assertNotIn('kv.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_infrastructure_failure_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, authz_result=_infra_failure_result())
        self.assertIn("Временная ошибка", self._sent_text(update))

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Fresh re-read
# ─────────────────────────────────────────────────────────────

class TestFreshReread(MutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(interaction_id):
            finder_calls.append(interaction_id)
            return _ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["ACT-001", "ACT-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(interaction_id):
            finder_calls.append(interaction_id)
            return _ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_lookup_runs_via_asyncio_to_thread(self):
        update = _make_update()
        to_thread_calls = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, *args, **kwargs):
            to_thread_calls.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_interaction_by_id":
                return _ROW
            return {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        self.assertEqual(to_thread_calls.count("find_interaction_by_id"), 2)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else _ROW_MISSING_OWNERSHIP

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else _ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else _ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_unchanged_ownership_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_ownership_change(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _ROW if calls["n"] == 1 else _ROW_OTHER_BIZ

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()

    def test_mutator_internal_lookup_does_not_substitute_for_handler_lookup(self):
        # Even when the mutator is mocked to "succeed" without ever
        # being asked to look anything up itself, the handler's own
        # two finder calls are what gate the mutation — this proves
        # the handler doesn't rely on the mutator's internal find.
        update = _make_update()
        finder_calls = []

        def finder(*_a, **_k):
            finder_calls.append(1)
            return _ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)


# ─────────────────────────────────────────────────────────────
# Ordering
# ─────────────────────────────────────────────────────────────

class TestOrdering(MutationTestBase):
    def test_full_sequence_order(self):
        update = _make_update()
        order = []

        def finder(*_a, **_k):
            order.append("lookup")
            return _ROW

        async def authz(*_a, **_k):
            order.append("authorize")
            return _allow_result()

        def mutator(*_a, **_k):
            order.append("mutate")
            return {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True}

        with patch(_FINDER_PATH, side_effect=finder), \
             patch(_AUTHZ_PATH, new=authz), \
             patch(_MUTATOR_PATH, side_effect=mutator), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))

        self.assertEqual(order, ["lookup", "authorize", "lookup", "mutate"])


# ─────────────────────────────────────────────────────────────
# Mutation
# ─────────────────────────────────────────────────────────────

class TestMutation(MutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_interaction_by_id":
                return _ROW
            return {"ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(_ARGS)))
        self.assertIn("update_interaction_notes", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_ROW)
        mock_mutator.assert_called_once_with("ACT-001", "hello")

    def test_mutation_exception_no_retry(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить Notes для Interaction.")

    def test_notes_content_absent_from_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, args=["interaction_id=ACT-001", "notes=SECRET_CONTENT"])
        self.assertNotIn("SECRET_CONTENT", self._sent_text(update))

    def test_success_reply_only_after_mutation_result(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True,
        })
        self.assertEqual(self._sent_text(update), "✅ Notes для Interaction ACT-001 обновлены.")

    def test_updated_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": True, "code": "INTERACTION_NOTES_UPDATED", "error": None, "changed": True,
        })
        self.assertIn("обновлены", self._sent_text(update))

    def test_unchanged_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": True, "code": "INTERACTION_NOTES_UNCHANGED", "error": None, "changed": False,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_not_found_result_handled(self):
        # Phase 17E-2A3-H1-R1: INTERACTION_NOT_FOUND after authorization
        # maps to the shared ownership-changed message, not a generic
        # "not found" text — see _interaction_notes_message's docstring.
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": False, "code": "INTERACTION_NOT_FOUND", "error": "Interaction ACT-001 не найден",
        })
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_too_long_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": False, "code": "INTERACTION_NOTES_TOO_LONG", "error": "notes превышает 2000 символов",
        })
        self.assertEqual(self._sent_text(update), "❌ Notes превышают допустимую длину.")
        self.assertNotIn("2000", self._sent_text(update))

    def test_fallback_result_code_handled_safely(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_return={
            "ok": False, "code": "SOME_FUTURE_CODE", "error": "unexpected",
        })
        text = self._sent_text(update)
        self.assertTrue(text.startswith("❌"))


# ─────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────

class TestIdempotency(MutationTestBase):
    def test_repeated_identical_notes_produces_unchanged_code(self):
        update1 = _make_update()
        self._run_handler(update1, finder_return=_ROW, mutator_return={
            "ok": True, "code": "INTERACTION_NOTES_UNCHANGED", "error": None, "changed": False,
        })
        self.assertIn("изменений нет", self._sent_text(update1))

    def test_no_duplicate_append_behavior_at_handler_level(self):
        # The handler passes notes through unmodified, exactly once per
        # call — no concatenation/append logic exists in the handler.
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn("+=", src)
        self.assertNotIn(".append(", src)

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


# ─────────────────────────────────────────────────────────────
# Architecture
# ─────────────────────────────────────────────────────────────

_OTHER_ENFORCED_HANDLERS = ["doc_cmd", "obligation_cmd", "payment_cmd", "offer_cmd", "lead_cmd", "interaction_cmd"]
_OTHER_MUTATION_CANDIDATE_HANDLERS = [
    "updatedoc_cmd", "updateobligation_cmd", "updateoffer_cmd", "updatelead_cmd",
    "confirmpayment_cmd", "reversepayment_cmd", "sendoffer_cmd", "acceptoffer_cmd", "convertlead_cmd",
]


class TestArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_nine_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 9)

    def test_six_phase_17e1_entries_unchanged(self):
        expected_six = {
            "doc":         {"resource": "DOCUMENT", "action": "READ", "target_shape": "BUSINESS_AND_OBJECT"},
            "obligation":  {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
            "payment":     {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
            "offer":       {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
            "lead":        {"resource": "FINANCE",  "action": "READ", "target_shape": "BUSINESS"},
            "interaction": {"resource": "CLIENT",   "action": "READ", "target_shape": "BUSINESS"},
        }
        for key, val in expected_six.items():
            with self.subTest(command=key):
                self.assertEqual(th.COMMAND_ENFORCEMENT_MAP[key], val)

    def test_updateinteractionnotes_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["updateinteractionnotes"], {
            "resource": "CLIENT", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_only_updateinteractionnotes_uses_mutate_helper(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertIn("_mutate_target_in_thread(", src)
        for name in _OTHER_ENFORCED_HANDLERS + _OTHER_MUTATION_CANDIDATE_HANDLERS:
            if not hasattr(th, name):
                continue
            with self.subTest(handler=name):
                other_src = inspect.getsource(getattr(th, name))
                self.assertNotIn("_mutate_target_in_thread(", other_src)

    def test_no_other_mutation_command_gained_transport_or_authorize(self):
        for name in _OTHER_MUTATION_CANDIDATE_HANDLERS:
            if not hasattr(th, name):
                continue
            with self.subTest(handler=name):
                src = inspect.getsource(getattr(th, name))
                self.assertNotIn("_validate_bc_transport_or_reply(", src)
                self.assertNotIn("_authorize_or_reply(", src)

    def test_transport_preflight_before_first_lookup(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        transport_pos = src.index("_validate_bc_transport_or_reply(")
        first_lookup_pos = src.index("_resolve_target_in_thread(")
        self.assertLess(transport_pos, first_lookup_pos)

    def test_authorization_after_first_lookup(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        first_lookup_pos = src.index("_resolve_target_in_thread(")
        authz_pos = src.index("_authorize_or_reply(")
        self.assertLess(first_lookup_pos, authz_pos)

    def test_second_lookup_after_authorization(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        authz_pos = src.index("_authorize_or_reply(")
        second_lookup_pos = src.rindex("_resolve_target_in_thread(")
        self.assertLess(authz_pos, second_lookup_pos)

    def test_mutation_after_second_lookup_and_comparison(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        second_lookup_pos = src.rindex("_resolve_target_in_thread(")
        comparison_pos = src.index("second_business_id != first_business_id")
        mutation_pos = src.index("_mutate_target_in_thread(")
        self.assertLess(second_lookup_pos, comparison_pos)
        self.assertLess(comparison_pos, mutation_pos)

    def test_no_direct_synchronous_finder_call(self):
        tree_src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn("find_interaction_by_id(interaction_id)", tree_src)

    def test_no_direct_synchronous_mutation_call(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn("update_interaction_notes(interaction_id, notes)", src)

    def test_no_direct_authorization_py_call(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        self.assertNotIn("authorize_business_core_access(", src)
        self.assertNotIn("from business_core.authorization import", src)

    def test_no_bypass_flag(self):
        src = inspect.getsource(th.updateinteractionnotes_cmd)
        for forbidden in ("bypass", "skip_transport", "already_validated"):
            self.assertNotIn(forbidden, src)

    def test_no_cache_in_mutate_helper(self):
        src = inspect.getsource(th._mutate_target_in_thread)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)

    def test_mutate_helper_no_authorization_no_lookup_no_render(self):
        src = inspect.getsource(th._mutate_target_in_thread)
        self.assertNotIn("_authorize_or_reply(", src)
        self.assertNotIn("_resolve_target_in_thread(", src)
        self.assertNotIn("reply_text(", src)
        self.assertNotIn("_reply(", src)

    def test_registration_line_unchanged(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("updateinteractionnotes", updateinteractionnotes_cmd)'), 1)


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A2: /updateleadnotes — dedicated, single-purpose
# mutation command. Reuses the same top-level helpers above
# (_run, _make_update, _allow_result, _deny_result,
# _infra_failure_result) but has its own row fixtures, finder/
# mutator paths, and allowed-key isolation tests, since this
# command additionally enforces an exact parsed-key set that
# /updateinteractionnotes never needed (it only ever accepted
# interaction_id/notes to begin with).
# ═════════════════════════════════════════════════════════════

_LEAD_ROW = {
    "Lead ID": "LED-001", "Business ID": "BIZ-001", "Status": "new",
    "Contact Name Snapshot": "", "Phone Snapshot": "", "WhatsApp Snapshot": "", "Email Snapshot": "",
    "Company Snapshot": "", "Service ID": "", "Source": "", "Channel ID": "",
    "Qualification Notes": "", "Disposition Reason": "", "Expected Value": "", "Currency": "",
    "Next Follow-up At": "", "Last Contacted At": "", "Assigned Person ID": "",
    "Caller Idempotency Key": "", "Created At": "2026-01-01T00:00:00Z", "Created By": "",
    "Updated At": "", "Notes": "",
}
_LEAD_ROW_OTHER_BIZ = {**_LEAD_ROW, "Business ID": "BIZ-002"}
_LEAD_ROW_MISSING_OWNERSHIP = {**_LEAD_ROW, "Business ID": ""}
_LEAD_ROW_WHITESPACE_OWNERSHIP = {**_LEAD_ROW, "Business ID": "   "}

_LEAD_FINDER_PATH = "business_core.lead_manager.find_lead_by_id"
_LEAD_MUTATOR_PATH = "business_core.business_builder.update_lead_admin_fields"

_LEAD_ID_ARG = "lead_id=LED-001"
_LEAD_NOTES_ARG = "notes=hello"
_LEAD_ARGS = [_LEAD_ID_ARG, _LEAD_NOTES_ARG]


class LeadNotesMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_LEAD_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_LEAD_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "code": "LEAD_UPDATED", "error": None,
                                       "lead_id": "LED-001", "business_id": "BIZ-001", "changed": True})
        patches.append(patch(_LEAD_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _LEAD_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.updateleadnotes_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestLeadNotesTransport(LeadNotesMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()


class TestLeadNotesArguments(LeadNotesMutationTestBase):
    def test_missing_lead_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_notes_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_target_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(["LED-001", _LEAD_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "status=new"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_assigned_person_id_key_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "assigned_person_id=PRS-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_expected_value_key_rejected(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH) as mock_finder, patch(_LEAD_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "expected_value=1000"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_LEAD_FINDER_PATH), patch(_LEAD_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context([_LEAD_ID_ARG, _LEAD_NOTES_ARG, "status=new"])))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ /updateleadnotes принимает только lead_id и notes.")

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW)
        mock_mutator.assert_called_once()


class TestLeadNotesFirstLookup(LeadNotesMutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) == 1:
                return _LEAD_ROW
            return {"ok": True, "code": "LEAD_UPDATED", "error": None, "changed": True}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        self.assertIn("LED-001", recorded[0][1])

    def test_finder_none_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=None)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_none_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=None)
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_finder_exception_zero_authorization_and_mutation(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        mock_authz, mock_mutator = self._run_handler(update, finder_side_effect=boom)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_exception_temporarily_unavailable_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        self._run_handler(update, finder_side_effect=boom)
        text = self._sent_text(update)
        self.assertIn("Временная ошибка", text)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("sheets down", text)

    def test_missing_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestLeadNotesAuthorization(LeadNotesMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_LEAD_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_LEAD_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_caller_cannot_spoof_business_id(self):
        # business_id is a forbidden parsed key (rejected in
        # TestLeadNotesArguments); this proves the handler source
        # itself never reads a caller-supplied business_id anywhere.
        src = inspect.getsource(th.updateleadnotes_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _LEAD_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


class TestLeadNotesFreshReread(LeadNotesMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(lead_id):
            finder_calls.append(lead_id)
            return _LEAD_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["LED-001", "LED-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(lead_id):
            finder_calls.append(lead_id)
            return _LEAD_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else _LEAD_ROW_MISSING_OWNERSHIP

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else _LEAD_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else _LEAD_ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_unchanged_ownership_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_ownership_change(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _LEAD_ROW if calls["n"] == 1 else _LEAD_ROW_OTHER_BIZ

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()


class TestLeadNotesMutation(LeadNotesMutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_lead_by_id":
                return _LEAD_ROW
            return {"ok": True, "code": "LEAD_UPDATED", "error": None, "changed": True}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(_LEAD_ARGS)))
        self.assertIn("update_lead_admin_fields", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW)
        mock_mutator.assert_called_once_with("LED-001", {"Notes": "hello"})

    def test_mutation_exception_no_retry(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_LEAD_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_LEAD_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_LEAD_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить Notes для Lead.")

    def test_notes_content_absent_from_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, args=["lead_id=LED-001", "notes=SECRET_CONTENT"])
        self.assertNotIn("SECRET_CONTENT", self._sent_text(update))

    def test_success_reply_only_after_mutation_result(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, mutator_return={
            "ok": True, "code": "LEAD_UPDATED", "error": None, "changed": True,
        })
        self.assertEqual(self._sent_text(update), "✅ Notes для Lead LED-001 обновлены.")

    def test_unchanged_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, mutator_return={
            "ok": True, "code": "LEAD_UPDATE_UNCHANGED", "error": None, "changed": False,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_not_found_after_authorization_mapped_to_changed_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, mutator_return={
            "ok": False, "code": "LEAD_NOT_FOUND", "error": "Lead LED-001 не найден",
        })
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_unknown_result_code_generic_message_no_code_leaked(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, mutator_return={
            "ok": False, "code": "LEAD_IMMUTABLE", "error": "Поле Status является неизменяемым фактом Lead",
        })
        text = self._sent_text(update)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Lead.")
        self.assertNotIn("LEAD_IMMUTABLE", text)
        self.assertNotIn("Status", text)
        self.assertNotIn("неизменяемым", text)

    def test_raw_error_never_rendered(self):
        update = _make_update()
        self._run_handler(update, finder_return=_LEAD_ROW, mutator_return={
            "ok": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error text should never appear",
        })
        text = self._sent_text(update)
        self.assertNotIn("raw domain error text should never appear", text)


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A2-R1: exception-secrecy correction — proves every
# exception path in updateleadnotes_cmd logs nothing sensitive and
# replies with only the fixed safe message. A synthetic exception
# message carries three secret markers; none may appear in the
# Telegram reply, or in any logger call's positional/keyword
# arguments. These markers are deliberately never asserted via a
# failure-message string that would print them to test output —
# assertNotIn's own failure message only echoes the haystack
# (log call args / reply text), not the needle, so no extra care is
# needed beyond not calling print()/repr() on the marker itself
# anywhere in this test.
# ─────────────────────────────────────────────────────────────

_SECRET_NOTES_MARKER = "SECRET_NOTES_MARKER"
_SECRET_BIZ_MARKER = "BIZ-SECRET"
_SECRET_ROW_MARKER = "ROW-SECRET"
_ALL_SECRET_MARKERS = (_SECRET_NOTES_MARKER, _SECRET_BIZ_MARKER, _SECRET_ROW_MARKER)


def _boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_SECRET_NOTES_MARKER} and {_SECRET_BIZ_MARKER} and {_SECRET_ROW_MARKER}"
    )


class TestLeadNotesExceptionSecrecy(LeadNotesMutationTestBase):
    def _assert_no_secrets_logged(self, mock_log_error):
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                args=["lead_id=LED-001", f"notes={_SECRET_NOTES_MARKER}"],
                finder_return={**_LEAD_ROW, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        self._assert_no_secrets_logged(mock_log_error)

    def test_mutation_exception_log_call_is_fixed_string(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_LEAD_ROW, mutator_side_effect=_boom_with_secrets)
        mock_log_error.assert_called_once_with("updateleadnotes_cmd mutation infrastructure failure")

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            args=["lead_id=LED-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_return={**_LEAD_ROW, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Lead.")

    def test_first_lookup_exception_no_log_call_at_all(self):
        # First-lookup exception path logs nothing today — confirmed
        # here so a future regression that adds unsafe logging would
        # be caught, without this phase adding new logging itself.
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error, \
             patch("business_core.telegram_handlers.log.warning") as mock_log_warning:
            self._run_handler(
                update, args=[f"lead_id=LED-001", f"notes={_SECRET_NOTES_MARKER}"],
                finder_side_effect=_boom_with_secrets,
            )
        mock_log_error.assert_not_called()
        mock_log_warning.assert_not_called()

    def test_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, args=["lead_id=LED-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_second_lookup_exception_no_log_call_at_all(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _LEAD_ROW
            return _boom_with_secrets()

        with patch("business_core.telegram_handlers.log.error") as mock_log_error, \
             patch("business_core.telegram_handlers.log.warning") as mock_log_warning:
            self._run_handler(update, finder_side_effect=finder)
        mock_log_error.assert_not_called()
        mock_log_warning.assert_not_called()

    def test_second_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _LEAD_ROW
            return _boom_with_secrets()

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_mutation_exception_log_message_contains_no_exc_info_flag(self):
        # exc_info/traceback attachment is deliberately avoided since a
        # traceback could indirectly surface request payload content —
        # confirmed by inspecting the handler source directly.
        src = inspect.getsource(th.updateleadnotes_cmd)
        self.assertNotIn("log.exception(", src)
        self.assertNotIn("exc_info=True", src)


class TestLeadNotesIdempotency(LeadNotesMutationTestBase):
    def test_repeated_identical_notes_produces_unchanged_code(self):
        update1 = _make_update()
        self._run_handler(update1, finder_return=_LEAD_ROW, mutator_return={
            "ok": True, "code": "LEAD_UPDATE_UNCHANGED", "error": None, "changed": False,
        })
        self.assertIn("изменений нет", self._sent_text(update1))

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.updateleadnotes_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


class TestLeadNotesIsolation(unittest.TestCase):
    def test_updatelead_cmd_unchanged_source_hash(self):
        # updatelead_cmd itself must not reference the new mapper/
        # helper flow at all — it is untouched by this phase.
        src = inspect.getsource(th.updatelead_cmd)
        self.assertNotIn("_mutate_target_in_thread(", src)
        self.assertNotIn("_authorize_or_reply(", src)
        self.assertNotIn("_validate_bc_transport_or_reply(", src)

    def test_updatelead_not_in_enforcement_map(self):
        self.assertNotIn("updatelead", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateleadnotes_does_not_call_updatelead_cmd(self):
        src = inspect.getsource(th.updateleadnotes_cmd)
        self.assertNotIn("updatelead_cmd(", src)

    def test_updateleadnotes_does_not_call_update_lead(self):
        # AST-level check (not substring) so the docstring's own prose
        # describing what is NOT called can't produce a false positive.
        tree = ast.parse(inspect.getsource(th.updateleadnotes_cmd))
        called_names = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        referenced_names = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        }
        self.assertNotIn("update_lead", called_names)
        self.assertNotIn("update_lead", referenced_names)

    def test_updateleadnotes_does_not_call_update_lead_active_fields(self):
        tree = ast.parse(inspect.getsource(th.updateleadnotes_cmd))
        referenced_names = {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        }
        self.assertNotIn("update_lead_active_fields", referenced_names)


class TestLeadNotesArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_nine_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 9)

    def test_updateleadnotes_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["updateleadnotes"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_only_three_dedicated_notes_handlers_use_mutate_helper(self):
        src_interaction = inspect.getsource(th.updateinteractionnotes_cmd)
        src_lead_notes = inspect.getsource(th.updateleadnotes_cmd)
        src_obligation_notes = inspect.getsource(th.updateobligationnotes_cmd)
        self.assertIn("_mutate_target_in_thread(", src_interaction)
        self.assertIn("_mutate_target_in_thread(", src_lead_notes)
        self.assertIn("_mutate_target_in_thread(", src_obligation_notes)
        for name in _OTHER_ENFORCED_HANDLERS + _OTHER_MUTATION_CANDIDATE_HANDLERS:
            if not hasattr(th, name):
                continue
            with self.subTest(handler=name):
                other_src = inspect.getsource(getattr(th, name))
                self.assertNotIn("_mutate_target_in_thread(", other_src)

    def test_registration_line_unchanged(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("updateleadnotes",'), 1)


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A3: /updateobligationnotes — dedicated, single-purpose
# mutation command. Mirrors the Lead-notes section above exactly,
# except the safe mapper keys off ok/changed flags rather than a
# code string (business_builder.update_payment_obligation_admin_fields
# leaves code="" on both success and failure — no synthesized
# UPDATED/UNCHANGED code exists in this chain), and the mapper must
# survive a malformed non-dict result without raising.
# ═════════════════════════════════════════════════════════════

_OBLIGATION_ROW = {
    "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-1",
    "Object ID": "", "Service ID": "", "Roadmap ID": "", "Stage ID": "",
    "Commercial Milestone Template ID": "", "Caller Idempotency Key": "",
    "Title Snapshot": "T", "Description Snapshot": "", "Obligation Amount": "100", "Currency": "RUB",
    "Due Date": "", "Status": "draft", "Paid Amount": "0", "Remaining Amount": "100",
    "Created At": "", "Created By": "", "Issued At": "", "Paid At": "", "Cancelled At": "",
    "Updated At": "", "Notes": "",
}
_OBLIGATION_ROW_OTHER_BIZ = {**_OBLIGATION_ROW, "Business ID": "BIZ-002"}
_OBLIGATION_ROW_MISSING_OWNERSHIP = {**_OBLIGATION_ROW, "Business ID": ""}
_OBLIGATION_ROW_WHITESPACE_OWNERSHIP = {**_OBLIGATION_ROW, "Business ID": "   "}

_OBLIGATION_FINDER_PATH = "business_core.payment_manager.find_payment_obligation_by_id"
_OBLIGATION_MUTATOR_PATH = "business_core.business_builder.update_payment_obligation_admin_fields"

_OBLIGATION_ID_ARG = "payment_obligation_id=POB-001"
_OBLIGATION_NOTES_ARG = "notes=hello"
_OBLIGATION_ARGS = [_OBLIGATION_ID_ARG, _OBLIGATION_NOTES_ARG]


class ObligationNotesMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_OBLIGATION_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_OBLIGATION_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "", "error": None})
        patches.append(patch(_OBLIGATION_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _OBLIGATION_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.updateobligationnotes_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestObligationNotesTransport(ObligationNotesMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_mutator.assert_called_once()


class TestObligationNotesArguments(ObligationNotesMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context([_OBLIGATION_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_notes_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context([_OBLIGATION_ID_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_target_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(["POB-001", _OBLIGATION_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_trailing_text_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["extra"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH), patch(_OBLIGATION_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["status=issued"])))
        self.assertEqual(self._sent_text(update), "❌ /updateobligationnotes принимает только payment_obligation_id и notes.")

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["status=issued"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_paid_amount_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["paid_amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_remaining_amount_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["remaining_amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_amount_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_currency_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["currency=KZT"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_due_date_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["due_date=2026-01-01"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_payment_transaction_id_key_rejected(self):
        update = _make_update()
        with patch(_OBLIGATION_FINDER_PATH) as mock_finder, patch(_OBLIGATION_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS + ["payment_transaction_id=PTXN-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_mutator.assert_called_once()


class TestObligationNotesFirstLookup(ObligationNotesMutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) == 1:
                return _OBLIGATION_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        self.assertIn("POB-001", recorded[0][1])

    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_authz.assert_called_once()

    def test_finder_none_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=None)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_none_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=None)
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_finder_exception_zero_authorization_and_mutation(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        mock_authz, mock_mutator = self._run_handler(update, finder_side_effect=boom)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_exception_temporarily_unavailable_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        self._run_handler(update, finder_side_effect=boom)
        text = self._sent_text(update)
        self.assertIn("Временная ошибка", text)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("sheets down", text)

    def test_missing_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestObligationNotesAuthorization(ObligationNotesMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.updateobligationnotes_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _OBLIGATION_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OBLIGATION_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


class TestObligationNotesFreshReread(ObligationNotesMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(obligation_id):
            finder_calls.append(obligation_id)
            return _OBLIGATION_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["POB-001", "POB-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(obligation_id):
            finder_calls.append(obligation_id)
            return _OBLIGATION_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else _OBLIGATION_ROW_MISSING_OWNERSHIP

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else _OBLIGATION_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else _OBLIGATION_ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_unchanged_ownership_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_ownership_change(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OBLIGATION_ROW if calls["n"] == 1 else _OBLIGATION_ROW_OTHER_BIZ

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()


class TestObligationNotesMutation(ObligationNotesMutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_payment_obligation_by_id":
                return _OBLIGATION_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(_OBLIGATION_ARGS)))
        self.assertIn("update_payment_obligation_admin_fields", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW)
        mock_mutator.assert_called_once_with("POB-001", {"Notes": "hello"})

    def test_mutation_exception_no_retry(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("updateobligationnotes_cmd mutation infrastructure failure")

    def test_notes_content_absent_from_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OBLIGATION_ROW, args=["payment_obligation_id=POB-001", "notes=SECRET_CONTENT"])
        self.assertNotIn("SECRET_CONTENT", self._sent_text(update))

    def test_success_reply_only_after_mutation_result(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_return={
            "ok": True, "changed": True, "code": "", "error": None,
        })
        self.assertEqual(self._sent_text(update), "✅ Notes для Payment Obligation POB-001 обновлены.")

    def test_unchanged_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_not_found_after_authorization_mapped_to_changed_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OBLIGATION_ROW, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "Payment Obligation 'POB-001' не найден",
        })
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")


class TestObligationNotesMapper(unittest.TestCase):
    """Direct unit tests of _obligation_notes_message — including the
    malformed-result robustness requirement from Phase 17E-2A3."""

    def test_changed_success(self):
        msg = th._obligation_notes_message({"ok": True, "changed": True, "code": "", "error": None}, "POB-001")
        self.assertEqual(msg, "✅ Notes для Payment Obligation POB-001 обновлены.")

    def test_unchanged_success(self):
        msg = th._obligation_notes_message({"ok": True, "changed": False, "code": "", "error": None}, "POB-001")
        self.assertEqual(msg, "ℹ️ Payment Obligation POB-001 — изменений нет (значения совпадают).")

    def test_not_found_after_authorization(self):
        msg = th._obligation_notes_message({"ok": False, "changed": False, "code": "PAYMENT_OBLIGATION_NOT_FOUND", "error": "x"}, "POB-001")
        self.assertEqual(msg, "Запись изменилась. Повтори команду ещё раз.")

    def test_ok_false_empty_code(self):
        msg = th._obligation_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_ok_false_unknown_code(self):
        msg = th._obligation_notes_message({"ok": False, "changed": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_ok_false_infrastructure_failure_error_never_rendered(self):
        msg = th._obligation_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "POB-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_malformed_empty_dict(self):
        msg = th._obligation_notes_message({}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_malformed_ok_only(self):
        msg = th._obligation_notes_message({"ok": True}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_malformed_ok_false_only(self):
        msg = th._obligation_notes_message({"ok": False}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_malformed_changed_only(self):
        msg = th._obligation_notes_message({"changed": True}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_malformed_code_only(self):
        msg = th._obligation_notes_message({"code": "UNKNOWN"}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_truthy_string_ok_not_treated_as_true(self):
        msg = th._obligation_notes_message({"ok": "true", "changed": True, "code": "", "error": None}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_truthy_int_changed_not_treated_as_true(self):
        msg = th._obligation_notes_message({"ok": True, "changed": 1, "code": "", "error": None}, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_none_result_does_not_raise(self):
        msg = th._obligation_notes_message(None, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_string_result_does_not_raise(self):
        msg = th._obligation_notes_message("not a dict", "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_list_result_does_not_raise(self):
        msg = th._obligation_notes_message(["ok", True], "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_integer_result_does_not_raise(self):
        msg = th._obligation_notes_message(42, "POB-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Payment Obligation.")


class TestObligationNotesIdempotency(ObligationNotesMutationTestBase):
    def test_repeated_identical_notes_produces_unchanged_message(self):
        update1 = _make_update()
        self._run_handler(update1, finder_return=_OBLIGATION_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update1))

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.updateobligationnotes_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


class TestObligationNotesIsolation(unittest.TestCase):
    def test_updateobligation_cmd_unchanged_source(self):
        src = inspect.getsource(th.updateobligation_cmd)
        self.assertNotIn("_mutate_target_in_thread(", src)
        self.assertNotIn("_authorize_or_reply(", src)
        self.assertNotIn("_validate_bc_transport_or_reply(", src)

    def test_updateobligation_not_in_enforcement_map(self):
        self.assertNotIn("updateobligation", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateobligationnotes_does_not_call_updateobligation_cmd(self):
        src = inspect.getsource(th.updateobligationnotes_cmd)
        self.assertNotIn("updateobligation_cmd(", src)

    def test_updateobligationnotes_does_not_call_status_or_transaction_mutators(self):
        tree = ast.parse(inspect.getsource(th.updateobligationnotes_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in (
            "transition_payment_obligation_status", "confirm_payment_transaction",
            "reverse_payment_transaction", "fail_payment_transaction",
        ):
            self.assertNotIn(forbidden, referenced_names)


class TestObligationNotesArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_nine_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 9)

    def test_updateobligationnotes_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["updateobligationnotes"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_registration_line_registered_once(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("updateobligationnotes",'), 1)


class TestObligationNotesExceptionSecrecy(ObligationNotesMutationTestBase):
    def _assert_no_secrets_logged(self, mock_log_error):
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                args=["payment_obligation_id=POB-001", f"notes={_SECRET_NOTES_MARKER}"],
                finder_return={**_OBLIGATION_ROW, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        self._assert_no_secrets_logged(mock_log_error)

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            args=["payment_obligation_id=POB-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_return={**_OBLIGATION_ROW, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Payment Obligation.")

    def test_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, args=["payment_obligation_id=POB-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_second_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _OBLIGATION_ROW
            return _boom_with_secrets()

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)


class TestUpdateObligationNotesEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = dict(_OBLIGATION_ROW)
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateobligationnotes_cmd(update, _make_context(
                ["payment_obligation_id=POB-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Payment Obligation.")


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A3-H1: end-to-end regression proof for the deployed
# dedicated commands, through the REAL business_builder + manager
# chain (only the Google Sheets primitives are mocked) — proving
# the manager-level logging hardening actually closes the leak at
# the full-command level, not just at the manager-function level in
# isolation. Before this hardening, a Sheets write exception would
# have propagated str(exc) into result["error"], which each
# command's code-synthesis fallback (business_builder's
# `code=write_result.get("code") or "..._IMMUTABLE"`) could route
# into a mapper branch that renders result["error"] to Telegram.
# ═════════════════════════════════════════════════════════════

_E2E_SECRET_NOTES_MARKER = "SECRET_NOTES_MARKER"
_E2E_SECRET_BIZ_MARKER = "BIZ-SECRET"
_E2E_SECRET_ROW_MARKER = "ROW-SECRET"
_E2E_SECRET_API_MARKER = "API-PAYLOAD-SECRET"
_E2E_ALL_SECRET_MARKERS = (
    _E2E_SECRET_NOTES_MARKER, _E2E_SECRET_BIZ_MARKER, _E2E_SECRET_ROW_MARKER, _E2E_SECRET_API_MARKER,
)


def _e2e_boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_E2E_SECRET_NOTES_MARKER} and {_E2E_SECRET_BIZ_MARKER} "
        f"and {_E2E_SECRET_ROW_MARKER} and {_E2E_SECRET_API_MARKER}"
    )


class TestUpdateInteractionNotesEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = {
            "Interaction ID": "ACT-001", "Business ID": "BIZ-001", "Caller Idempotency Key": "",
            "Interaction Type": "call", "Direction": "outbound", "Channel ID": "", "Occurred At": "",
            "Summary": "s", "Outcome": "", "Lead ID": "", "Client ID": "PRS-1", "Commercial Offer ID": "",
            "Assigned Person ID": "", "External Reference": "", "Status": "active",
            "Created At": "", "Created By": "", "Updated At": "", "Archived At": "", "Notes": "",
        }
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateinteractionnotes_cmd(update, _make_context(
                ["interaction_id=ACT-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        # Real chain: business_builder.update_interaction_notes synthesizes
        # code="INTERACTION_IMMUTABLE" on ok=False with a blank manager
        # code. Phase 17E-2A3-H1-R1: _interaction_notes_message no
        # longer has a dedicated INTERACTION_IMMUTABLE branch that
        # renders result["error"] — it falls to the fully generic fixed
        # message, so neither the raw exception NOR the sanitized
        # "Infrastructure failure" placeholder ever reaches Telegram.
        self.assertEqual(text, "❌ Не удалось обновить Notes для Interaction.")


class TestUpdateLeadNotesEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = {
            "Lead ID": "LED-001", "Business ID": "BIZ-001", "Status": "new",
            "Contact Name Snapshot": "", "Phone Snapshot": "", "WhatsApp Snapshot": "", "Email Snapshot": "",
            "Company Snapshot": "", "Service ID": "", "Source": "", "Channel ID": "",
            "Qualification Notes": "", "Disposition Reason": "", "Expected Value": "", "Currency": "",
            "Next Follow-up At": "", "Last Contacted At": "", "Assigned Person ID": "",
            "Caller Idempotency Key": "", "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
        }
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateleadnotes_cmd(update, _make_context(
                ["lead_id=LED-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        # _lead_notes_message (the dedicated mapper) never checks
        # LEAD_IMMUTABLE at all, so even the synthesized code from
        # business_builder falls through to the fully generic message.
        self.assertEqual(text, "❌ Не удалось обновить Notes для Lead.")


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A4-H1: legacy /updateoffer real-chain regression proof.
# Unlike the dedicated commands above, /updateoffer has NO
# transport preflight or authorization gate — this test proves the
# manager-hardening + wrapper-correction + mapper-correction chain
# alone (not any enforcement layer) is what prevents the previously
# live "ℹ️ ...изменений нет..." false-success message and any
# secret-marker leakage when a Sheets write raises during the
# legacy command's Notes-mode.
# ═════════════════════════════════════════════════════════════

_H1_OFFER_ROW = {
    "Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-001", "Previous Commercial Offer ID": "",
    "Version Number": "1", "Business ID": "BIZ-001", "Client ID": "PRS-001", "Object ID": "", "Service ID": "SVC-001",
    "Roadmap ID": "", "Offer Document ID": "", "Title Snapshot": "T", "Scope Snapshot": "S",
    "Quoted Amount": "150000.00", "Currency": "KZT", "Valid Until": "2026-12-31", "Status": "draft",
    "Caller Idempotency Key": "", "Created At": "", "Created By": "", "Updated At": "",
    "Sent At": "", "Sent By": "", "Accepted At": "", "Accepted By": "",
    "Rejected At": "", "Rejected By": "", "Rejection Reason": "", "Expired At": "",
    "Cancelled At": "", "Cancelled By": "", "Cancellation Reason": "", "Archived At": "", "Notes": "",
}


class TestLegacyUpdateOfferNotesModeEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = dict(_H1_OFFER_ROW)
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updateoffer_cmd(update, _make_context(
                ["commercial_offer_id=OFR-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("COMMERCIAL_OFFER_UPDATE_UNCHANGED", text)
        self.assertNotIn("изменений нет", text)
        self.assertNotIn("ℹ️", text)
        self.assertEqual(text, "❌ Не удалось обновить Commercial Offer.")

    def test_successful_notes_update_through_real_chain_unaffected(self):
        update = _make_update()
        row = dict(_H1_OFFER_ROW)
        row["Notes"] = "old"
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updateoffer_cmd(update, _make_context(
                ["commercial_offer_id=OFR-001", "notes=new"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "✅ Commercial Offer OFR-001 обновлён.")

    def test_unchanged_notes_update_through_real_chain_unaffected(self):
        update = _make_update()
        row = dict(_H1_OFFER_ROW)
        row["Notes"] = "same"
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updateoffer_cmd(update, _make_context(
                ["commercial_offer_id=OFR-001", "notes=same"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "ℹ️ Commercial Offer OFR-001 — изменений нет (значения совпадают).")


if __name__ == "__main__":
    unittest.main()
