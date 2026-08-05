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
# Phase 17E-2A7-H1: exception-logging secrecy hardening.
# updateinteractionnotes_cmd was the one command found (Phase
# 17E-2A7's read-only audit) still using a dynamic f-string
# exception log (`log.error(f"...{e}")`) on its mutation boundary —
# every other dedicated mutation command already used a fixed
# literal. This class proves the fix: the mutation-exception
# boundary now logs a fixed literal only, with zero dynamic content
# (no interaction_id, no Business ID, no Notes, no actor identity,
# no raw exception text), the mutation is attempted exactly once
# with no retry, and the existing fixed user reply is unchanged.
# ─────────────────────────────────────────────────────────────

_INTERACTIONNOTES_SECRET_MARKERS = (
    "INTERACTION-SECRET", "BUSINESS-SECRET", "NOTES-SECRET", "ACTOR-SECRET", "API-PAYLOAD-SECRET",
)


def _interactionnotes_boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        "synthetic failure containing " + " and ".join(_INTERACTIONNOTES_SECRET_MARKERS)
    )


class TestExceptionSecrecy(MutationTestBase):
    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _, mock_mutator = self._run_handler(
                update, finder_return=_ROW, mutator_side_effect=_interactionnotes_boom_with_secrets,
            )
        mock_log_error.assert_called_once_with("updateinteractionnotes_cmd mutation infrastructure failure")
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                args=["interaction_id=ACT-001", f"notes={_INTERACTIONNOTES_SECRET_MARKERS[2]}"],
                finder_return={**_ROW, "Business ID": _INTERACTIONNOTES_SECRET_MARKERS[1]},
                mutator_side_effect=_interactionnotes_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _INTERACTIONNOTES_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            args=["interaction_id=ACT-001", f"notes={_INTERACTIONNOTES_SECRET_MARKERS[2]}"],
            finder_return={**_ROW, "Business ID": _INTERACTIONNOTES_SECRET_MARKERS[1]},
            mutator_side_effect=_interactionnotes_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _INTERACTIONNOTES_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Interaction.")

    def test_mutation_exception_no_raw_exception_text_in_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_ROW, mutator_side_effect=_interactionnotes_boom_with_secrets)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("synthetic failure", text)

    def test_mutation_attempted_exactly_once_no_retry(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(
            update, finder_return=_ROW, mutator_side_effect=_interactionnotes_boom_with_secrets,
        )
        mock_mutator.assert_called_once()

    def test_handler_source_contains_no_dynamic_exception_logging(self):
        """
        AST-scoped (not whole-file substring) proof that
        updateinteractionnotes_cmd's own log.error() calls never take
        an f-string, str(exc)/repr(exc) argument, or exc_info kwarg —
        matches the equivalent guard already used for the other
        dedicated mutation commands. Function-source-scoped rather
        than a raw substring search, so a comment or docstring
        mentioning these terms cannot trip a false positive.
        """
        tree = ast.parse(inspect.getsource(th.updateinteractionnotes_cmd))
        func_node = tree.body[0]
        self.assertIsInstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef))

        for node in ast.walk(func_node):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "log"):
                continue
            self.assertNotEqual(node.func.attr, "exception", "log.exception(...) must not be used")
            if node.func.attr == "error":
                for arg in node.args:
                    self.assertNotIsInstance(arg, ast.JoinedStr, "log.error() must not take an f-string argument")
                    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                        self.assertNotIn(arg.func.id, ("str", "repr", "format"), f"log.error() must not wrap the exception in {arg.func.id}(...)")
                for kw in node.keywords:
                    self.assertNotEqual(kw.arg, "exc_info", "log.error() must not pass exc_info")


class TestOtherSevenMutationHandlersRemainSafe(unittest.TestCase):
    """
    Phase 17E-2A7-H1 §4/§7: read-only audit proving the other seven
    already-authorized mutation handlers contain no equivalent
    dynamic exception-logging leak, and were not touched by this
    phase's fix.
    """
    _OTHER_SEVEN = (
        "updateleadnotes_cmd", "updateobligationnotes_cmd", "updateoffernotes_cmd", "updatedocnotes_cmd",
        "failpayment_cmd", "confirmpayment_cmd", "reversepayment_cmd",
    )

    def test_no_dynamic_exception_logging_in_other_seven(self):
        import ast as _ast
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            src = f.read()
        tree = _ast.parse(src)
        nodes_by_name = {n.name: n for n in _ast.walk(tree) if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}

        for name in self._OTHER_SEVEN:
            with self.subTest(handler=name):
                func_node = nodes_by_name[name]
                for node in _ast.walk(func_node):
                    if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                            and isinstance(node.func.value, _ast.Name) and node.func.value.id == "log"):
                        continue
                    self.assertNotEqual(node.func.attr, "exception")
                    if node.func.attr == "error":
                        for arg in node.args:
                            self.assertNotIsInstance(arg, _ast.JoinedStr)
                            if isinstance(arg, _ast.Call) and isinstance(arg.func, _ast.Name):
                                self.assertNotIn(arg.func.id, ("str", "repr", "format"))
                        for kw in node.keywords:
                            self.assertNotEqual(kw.arg, "exc_info")


# ─────────────────────────────────────────────────────────────
# Architecture
# ─────────────────────────────────────────────────────────────

_OTHER_ENFORCED_HANDLERS = ["doc_cmd", "obligation_cmd", "payment_cmd", "offer_cmd", "lead_cmd", "interaction_cmd"]
_OTHER_MUTATION_CANDIDATE_HANDLERS = [
    "updatedoc_cmd", "updateobligation_cmd", "updateoffer_cmd", "updatelead_cmd",
    "sendoffer_cmd", "acceptoffer_cmd", "convertlead_cmd",
    # confirmpayment_cmd/reversepayment_cmd were authorized in Phase
    # 17E-2A6-AUTH-B2 and are intentionally excluded from this list —
    # they now legitimately use _mutate_target_in_thread.
]


class TestArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_eleven_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

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
    def test_enforcement_map_has_exactly_eleven_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

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
    def test_enforcement_map_has_exactly_eleven_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

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


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A4: /updateoffernotes — dedicated, single-purpose
# mutation command. Mirrors the Obligation-notes section exactly:
# business_builder.update_commercial_offer_admin_fields leaves
# code="" on both success and infrastructure failure, so the safe
# mapper keys off ok/changed flags rather than a code string.
# ═════════════════════════════════════════════════════════════

_OFFER_ROW = dict(_H1_OFFER_ROW)
_OFFER_ROW_OTHER_BIZ = {**_OFFER_ROW, "Business ID": "BIZ-002"}
_OFFER_ROW_MISSING_OWNERSHIP = {**_OFFER_ROW, "Business ID": ""}
_OFFER_ROW_WHITESPACE_OWNERSHIP = {**_OFFER_ROW, "Business ID": "   "}

_OFFER_FINDER_PATH = "business_core.offer_manager.find_commercial_offer_by_id"
_OFFER_MUTATOR_PATH = "business_core.business_builder.update_commercial_offer_admin_fields"

_OFFER_ID_ARG = "commercial_offer_id=OFR-001"
_OFFER_NOTES_ARG = "notes=hello"
_OFFER_ARGS = [_OFFER_ID_ARG, _OFFER_NOTES_ARG]


class OfferNotesMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_OFFER_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_OFFER_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "", "error": None})
        patches.append(patch(_OFFER_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _OFFER_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.updateoffernotes_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestOfferNotesTransport(OfferNotesMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW)
        mock_mutator.assert_called_once()


class TestOfferNotesArguments(OfferNotesMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context([_OFFER_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_notes_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context([_OFFER_ID_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_target_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(["OFR-001", _OFFER_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_trailing_text_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["extra"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH), patch(_OFFER_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["status=sent"])))
        self.assertEqual(self._sent_text(update), "❌ /updateoffernotes принимает только commercial_offer_id и notes.")

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_title_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["title=New Title"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_scope_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["scope=New Scope"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_quoted_amount_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["quoted_amount=200000"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_amount_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["amount=200000"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_currency_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["currency=USD"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_valid_until_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["valid_until=2027-01-01"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_object_id_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["object_id=OBJ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_service_id_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["service_id=SVC-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_roadmap_id_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["roadmap_id=RDM-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_offer_document_id_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["offer_document_id=DOC-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_OFFER_FINDER_PATH) as mock_finder, patch(_OFFER_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS + ["status=sent"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW)
        mock_mutator.assert_called_once()


class TestOfferNotesFirstLookup(OfferNotesMutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) == 1:
                return _OFFER_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        self.assertIn("OFR-001", recorded[0][1])

    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OFFER_ROW)
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
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestOfferNotesAuthorization(OfferNotesMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OFFER_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_OFFER_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.updateoffernotes_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _OFFER_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OFFER_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


class TestOfferNotesFreshReread(OfferNotesMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(offer_id):
            finder_calls.append(offer_id)
            return _OFFER_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["OFR-001", "OFR-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(offer_id):
            finder_calls.append(offer_id)
            return _OFFER_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else _OFFER_ROW_MISSING_OWNERSHIP

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else _OFFER_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else _OFFER_ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_unchanged_ownership_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_ownership_change(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _OFFER_ROW if calls["n"] == 1 else _OFFER_ROW_OTHER_BIZ

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()


class TestOfferNotesMutation(OfferNotesMutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_commercial_offer_by_id":
                return _OFFER_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(_OFFER_ARGS)))
        self.assertIn("update_commercial_offer_admin_fields", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW)
        mock_mutator.assert_called_once_with("OFR-001", {"Notes": "hello"})

    def test_mutation_exception_no_retry(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_OFFER_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_OFFER_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_OFFER_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_OFFER_ROW, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("updateoffernotes_cmd mutation infrastructure failure")

    def test_notes_content_absent_from_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OFFER_ROW, args=["commercial_offer_id=OFR-001", "notes=SECRET_CONTENT"])
        self.assertNotIn("SECRET_CONTENT", self._sent_text(update))

    def test_success_reply_only_after_mutation_result(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OFFER_ROW, mutator_return={
            "ok": True, "changed": True, "code": "", "error": None,
        })
        self.assertEqual(self._sent_text(update), "✅ Notes для Commercial Offer OFR-001 обновлены.")

    def test_unchanged_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OFFER_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_not_found_after_authorization_mapped_to_changed_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_OFFER_ROW, mutator_return={
            "ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "Commercial Offer 'OFR-001' не найден",
        })
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")


class TestOfferNotesMapper(unittest.TestCase):
    """Direct unit tests of _offer_notes_message — including the
    malformed-result robustness requirement from Phase 17E-2A4."""

    def test_changed_success(self):
        msg = th._offer_notes_message({"ok": True, "changed": True, "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "✅ Notes для Commercial Offer OFR-001 обновлены.")

    def test_unchanged_success(self):
        msg = th._offer_notes_message({"ok": True, "changed": False, "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "ℹ️ Commercial Offer OFR-001 — изменений нет (значения совпадают).")

    def test_not_found_after_authorization(self):
        msg = th._offer_notes_message({"ok": False, "changed": False, "code": "COMMERCIAL_OFFER_NOT_FOUND", "error": "x"}, "OFR-001")
        self.assertEqual(msg, "Запись изменилась. Повтори команду ещё раз.")

    def test_ok_false_empty_code(self):
        msg = th._offer_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_ok_false_unknown_code(self):
        msg = th._offer_notes_message({"ok": False, "changed": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_ok_false_infrastructure_failure_error_never_rendered(self):
        msg = th._offer_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "OFR-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_malformed_empty_dict(self):
        msg = th._offer_notes_message({}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_malformed_ok_only(self):
        msg = th._offer_notes_message({"ok": True}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_malformed_ok_false_only(self):
        msg = th._offer_notes_message({"ok": False}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_malformed_changed_only(self):
        msg = th._offer_notes_message({"changed": True}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_malformed_code_only(self):
        msg = th._offer_notes_message({"code": "UNKNOWN"}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_truthy_string_ok_not_treated_as_true(self):
        msg = th._offer_notes_message({"ok": "true", "changed": True, "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_truthy_int_ok_not_treated_as_true(self):
        msg = th._offer_notes_message({"ok": 1, "changed": True, "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_truthy_int_changed_not_treated_as_true(self):
        msg = th._offer_notes_message({"ok": True, "changed": 1, "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_falsy_string_changed_not_treated_as_false(self):
        msg = th._offer_notes_message({"ok": True, "changed": "false", "code": "", "error": None}, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_none_result_does_not_raise(self):
        msg = th._offer_notes_message(None, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_string_result_does_not_raise(self):
        msg = th._offer_notes_message("not a dict", "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_list_result_does_not_raise(self):
        msg = th._offer_notes_message(["ok", True], "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_integer_result_does_not_raise(self):
        msg = th._offer_notes_message(42, "OFR-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Commercial Offer.")


class TestOfferNotesIdempotency(OfferNotesMutationTestBase):
    def test_repeated_identical_notes_produces_unchanged_message(self):
        update1 = _make_update()
        self._run_handler(update1, finder_return=_OFFER_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update1))

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.updateoffernotes_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


class TestOfferNotesIsolation(unittest.TestCase):
    def test_updateoffer_cmd_unchanged_source(self):
        src = inspect.getsource(th.updateoffer_cmd)
        self.assertNotIn("_mutate_target_in_thread(", src)
        self.assertNotIn("_authorize_or_reply(", src)
        self.assertNotIn("_validate_bc_transport_or_reply(", src)

    def test_updateoffer_not_in_enforcement_map(self):
        self.assertNotIn("updateoffer", th.COMMAND_ENFORCEMENT_MAP)

    def test_updateoffernotes_does_not_call_updateoffer_cmd(self):
        src = inspect.getsource(th.updateoffernotes_cmd)
        self.assertNotIn("updateoffer_cmd(", src)

    def test_updateoffernotes_does_not_call_other_offer_mutators(self):
        tree = ast.parse(inspect.getsource(th.updateoffernotes_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in (
            "send_commercial_offer", "accept_commercial_offer", "reject_commercial_offer",
            "expire_commercial_offer", "cancel_commercial_offer", "archive_commercial_offer",
            "revise_commercial_offer",
        ):
            self.assertNotIn(forbidden, referenced_names)


class TestOfferNotesArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_eleven_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_updateoffernotes_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["updateoffernotes"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_registration_line_registered_once(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("updateoffernotes",'), 1)


class TestOfferNotesExceptionSecrecy(OfferNotesMutationTestBase):
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
                args=["commercial_offer_id=OFR-001", f"notes={_SECRET_NOTES_MARKER}"],
                finder_return={**_OFFER_ROW, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        self._assert_no_secrets_logged(mock_log_error)

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            args=["commercial_offer_id=OFR-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_return={**_OFFER_ROW, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Commercial Offer.")

    def test_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, args=["commercial_offer_id=OFR-001", f"notes={_SECRET_NOTES_MARKER}"],
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
                return _OFFER_ROW
            return _boom_with_secrets()

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)


class TestUpdateOfferNotesEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = dict(_H1_OFFER_ROW)
        sheet = MagicMock()
        sheet.row_values.return_value = list(row.keys())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updateoffernotes_cmd(update, _make_context(
                ["commercial_offer_id=OFR-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Commercial Offer.")


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A5-H1: legacy /updatedoc real-chain regression proof.
# Like the legacy /updateoffer proof above, /updatedoc has no
# transport preflight or authorization gate — this proves the
# manager-hardening + wrapper-correction + mapper-correction chain
# alone (not any enforcement layer) prevents raw exception text /
# manager error text / secret markers from reaching Telegram when a
# Sheets write raises during the legacy command's Notes-mode, and
# that it never produces a false success/no-op message either.
# ═════════════════════════════════════════════════════════════

_H1_DOCUMENT_ROW = {
    "Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "1",
    "Business ID": "BIZ-001", "Client ID": "PRS-001", "Object ID": "OBJ-001", "Roadmap ID": "", "Stage ID": "",
    "Document Template ID": "", "Document Name": "old-name", "Status": "uploaded",
    "Drive File ID": "FILE1", "Drive File URL": "https://drive.google.com/file/d/FILE1/view",
    "File Name": "passport.pdf", "Mime Type": "application/pdf",
    "Uploaded At": "", "Uploaded By": "",
    "Reviewed At": "", "Reviewed By": "", "Rejection Reason": "",
    "Notes": "old", "Created At": "", "Updated At": "",
    "Archived At": "", "Archived By": "", "Archive Reason": "", "Previous Status": "",
}


class TestLegacyUpdateDocNotesModeEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = dict(_H1_DOCUMENT_ROW)
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        headers = list(row.keys())
        sheet.row_values.side_effect = lambda r: headers if r == 1 else list(row.values())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updatedoc_cmd(update, _make_context(
                ["document_id=DREG-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("✅", text)
        self.assertNotIn("изменений нет", text)
        self.assertNotIn("ℹ️", text)
        self.assertEqual(text, "❌ Не удалось обновить Document.")

    def test_successful_notes_update_through_real_chain_unaffected(self):
        update = _make_update()
        row = dict(_H1_DOCUMENT_ROW)
        row["Notes"] = "old"
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        headers = list(row.keys())
        sheet.row_values.side_effect = lambda r: headers if r == 1 else list(row.values())

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updatedoc_cmd(update, _make_context(
                ["document_id=DREG-001", "notes=new"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "✅ Document DREG-001 обновлён.")

    def test_unchanged_notes_update_through_real_chain_unaffected(self):
        update = _make_update()
        row = dict(_H1_DOCUMENT_ROW)
        row["Notes"] = "same"
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        headers = list(row.keys())
        sheet.row_values.side_effect = lambda r: headers if r == 1 else list(row.values())

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            _run(th.updatedoc_cmd(update, _make_context(
                ["document_id=DREG-001", "notes=same"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "ℹ️ Document DREG-001 — изменений нет (значения совпадают).")


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A5: /updatedocnotes — dedicated, single-purpose
# mutation command. Mirrors the Offer/Obligation-notes sections
# exactly, except DOCUMENT is an object-addressable resource:
# authorize_business_core_access() structurally requires both
# business_id AND object_id (TARGET_REQUIRED otherwise), so both
# are resolved from the Document's own stored row and both are
# re-verified unchanged on the mandatory second lookup.
# business_builder.update_document_admin_fields leaves code=""
# on both success and infrastructure failure, so the safe mapper
# keys off ok/changed flags rather than a code string.
# ═════════════════════════════════════════════════════════════

_DOCNOTES_ROW = {
    "document_id": "DREG-001", "business_id": "BIZ-001", "object_id": "OBJ-001",
}
_DOCNOTES_ROW_OTHER_BIZ = {**_DOCNOTES_ROW, "business_id": "BIZ-002"}
_DOCNOTES_ROW_OTHER_OBJECT = {**_DOCNOTES_ROW, "object_id": "OBJ-002"}
_DOCNOTES_ROW_MISSING_BIZ = {**_DOCNOTES_ROW, "business_id": ""}
_DOCNOTES_ROW_MISSING_OBJECT = {**_DOCNOTES_ROW, "object_id": ""}
_DOCNOTES_ROW_WHITESPACE_BIZ = {**_DOCNOTES_ROW, "business_id": "   "}
_DOCNOTES_ROW_WHITESPACE_OBJECT = {**_DOCNOTES_ROW, "object_id": "   "}

_DOCNOTES_FINDER_PATH = "business_core.document_manager.find_document_by_id"
_DOCNOTES_MUTATOR_PATH = "business_core.business_builder.update_document_admin_fields"

_DOCNOTES_ID_ARG = "document_id=DREG-001"
_DOCNOTES_NOTES_ARG = "notes=hello"
_DOCNOTES_ARGS = [_DOCNOTES_ID_ARG, _DOCNOTES_NOTES_ARG]


class DocumentNotesMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_DOCNOTES_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_DOCNOTES_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "", "error": None})
        patches.append(patch(_DOCNOTES_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _DOCNOTES_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.updatedocnotes_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestDocumentNotesTransport(DocumentNotesMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_mutator.assert_called_once()


class TestDocumentNotesArguments(DocumentNotesMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context([_DOCNOTES_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_notes_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context([_DOCNOTES_ID_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_target_rejected(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(["DREG-001", _DOCNOTES_NOTES_ARG])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_positional_trailing_text_rejected(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS + ["extra"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH), patch(_DOCNOTES_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS + ["status=approved"])))
        self.assertEqual(self._sent_text(update), "❌ /updatedocnotes принимает только document_id и notes.")

    def _assert_key_rejected(self, key_value):
        update = _make_update()
        with patch(_DOCNOTES_FINDER_PATH) as mock_finder, patch(_DOCNOTES_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS + [key_value])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_business_id_key_rejected(self):
        self._assert_key_rejected("business_id=BIZ-001")

    def test_object_id_key_rejected(self):
        self._assert_key_rejected("object_id=OBJ-001")

    def test_name_key_rejected(self):
        self._assert_key_rejected("name=New Name")

    def test_title_key_rejected(self):
        self._assert_key_rejected("title=New Title")

    def test_filename_key_rejected(self):
        self._assert_key_rejected("filename=x.pdf")

    def test_document_type_key_rejected(self):
        self._assert_key_rejected("document_type=passport")

    def test_status_key_rejected(self):
        self._assert_key_rejected("status=approved")

    def test_storage_url_key_rejected(self):
        self._assert_key_rejected("storage_url=https://example.com")

    def test_drive_file_id_key_rejected(self):
        self._assert_key_rejected("drive_file_id=FILE1")

    def test_content_id_key_rejected(self):
        self._assert_key_rejected("content_id=CNT-001")

    def test_client_id_key_rejected(self):
        self._assert_key_rejected("client_id=PRS-001")

    def test_service_id_key_rejected(self):
        self._assert_key_rejected("service_id=SVC-001")

    def test_roadmap_id_key_rejected(self):
        self._assert_key_rejected("roadmap_id=RM-001")

    def test_stage_id_key_rejected(self):
        self._assert_key_rejected("stage_id=STAGE-001")

    def test_document_template_id_key_rejected(self):
        self._assert_key_rejected("document_template_id=DOC-012")

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_mutator.assert_called_once()


class TestDocumentNotesFirstLookup(DocumentNotesMutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) == 1:
                return _DOCNOTES_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        self.assertIn("DREG-001", recorded[0][1])

    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_DOCNOTES_ROW)
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
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW_MISSING_BIZ)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW_WHITESPACE_BIZ)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_object_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW_MISSING_OBJECT)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_object_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW_WHITESPACE_OBJECT)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestDocumentNotesAuthorization(DocumentNotesMutationTestBase):
    def test_resource_document_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "DOCUMENT")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_authorization_called_exactly_once(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_authz.assert_called_once()

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_object_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["object_id"], "OBJ-001")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.updatedocnotes_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_caller_cannot_spoof_object_id(self):
        src = inspect.getsource(th.updatedocnotes_cmd)
        self.assertNotIn('args.get("object_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _DOCNOTES_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_DOCNOTES_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


class TestDocumentNotesFreshReread(DocumentNotesMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(document_id):
            finder_calls.append(document_id)
            return _DOCNOTES_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["DREG-001", "DREG-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(document_id):
            finder_calls.append(document_id)
            return _DOCNOTES_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_MISSING_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_object_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_MISSING_OBJECT

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_business_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_object_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_OTHER_OBJECT

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_ownership_changed_message_reveals_no_ids(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_OTHER_OBJECT

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("OBJ-001", text)
        self.assertNotIn("OBJ-002", text)

    def test_both_unchanged_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_ownership_change(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _DOCNOTES_ROW if calls["n"] == 1 else _DOCNOTES_ROW_OTHER_OBJECT

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()


class TestDocumentNotesMutation(DocumentNotesMutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_document_by_id":
                return _DOCNOTES_ROW
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(_DOCNOTES_ARGS)))
        self.assertIn("update_document_admin_fields", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW)
        mock_mutator.assert_called_once_with("DREG-001", {"Notes": "hello"})

    def test_mutation_exception_no_retry(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить Notes для Document.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("updatedocnotes_cmd mutation infrastructure failure")

    def test_notes_content_absent_from_reply(self):
        update = _make_update()
        self._run_handler(update, finder_return=_DOCNOTES_ROW, args=["document_id=DREG-001", "notes=SECRET_CONTENT"])
        self.assertNotIn("SECRET_CONTENT", self._sent_text(update))

    def test_success_reply_only_after_mutation_result(self):
        update = _make_update()
        self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_return={
            "ok": True, "changed": True, "code": "", "error": None,
        })
        self.assertEqual(self._sent_text(update), "✅ Notes для Document DREG-001 обновлены.")

    def test_unchanged_result_handled(self):
        update = _make_update()
        self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_not_found_after_authorization_mapped_to_changed_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_DOCNOTES_ROW, mutator_return={
            "ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": "Document 'DREG-001' не найден",
        })
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")


class TestDocumentNotesMapper(unittest.TestCase):
    """Direct unit tests of _document_notes_message — including the
    malformed-result robustness requirement from Phase 17E-2A5."""

    def test_changed_success(self):
        msg = th._document_notes_message({"ok": True, "changed": True, "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "✅ Notes для Document DREG-001 обновлены.")

    def test_unchanged_success(self):
        msg = th._document_notes_message({"ok": True, "changed": False, "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "ℹ️ Document DREG-001 — изменений нет (значения совпадают).")

    def test_not_found_after_authorization(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": "x"}, "DREG-001")
        self.assertEqual(msg, "Запись изменилась. Повтори команду ещё раз.")

    def test_ok_false_empty_code(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_ok_false_unknown_code(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "SOME_FUTURE_CODE", "error": "raw domain error"}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")
        self.assertNotIn("raw domain error", msg)
        self.assertNotIn("SOME_FUTURE_CODE", msg)

    def test_ok_false_infrastructure_failure_error_never_rendered(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"}, "DREG-001")
        self.assertNotIn("Infrastructure failure", msg)

    def test_ok_false_with_updated_code_never_success(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": "x"}, "DREG-001")
        self.assertNotIn("✅", msg)
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_ok_false_with_unchanged_code_never_unchanged_ux(self):
        msg = th._document_notes_message({"ok": False, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": "x"}, "DREG-001")
        self.assertNotIn("ℹ️", msg)
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_malformed_empty_dict(self):
        msg = th._document_notes_message({}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_malformed_ok_only(self):
        msg = th._document_notes_message({"ok": True}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_malformed_ok_false_only(self):
        msg = th._document_notes_message({"ok": False}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_malformed_changed_only(self):
        msg = th._document_notes_message({"changed": True}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_malformed_code_only(self):
        msg = th._document_notes_message({"code": "UNKNOWN"}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_truthy_string_ok_not_treated_as_true(self):
        msg = th._document_notes_message({"ok": "true", "changed": True, "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_truthy_int_ok_not_treated_as_true(self):
        msg = th._document_notes_message({"ok": 1, "changed": True, "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_truthy_int_changed_not_treated_as_true(self):
        msg = th._document_notes_message({"ok": True, "changed": 1, "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_falsy_string_changed_not_treated_as_false(self):
        msg = th._document_notes_message({"ok": True, "changed": "false", "code": "", "error": None}, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_none_result_does_not_raise(self):
        msg = th._document_notes_message(None, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_string_result_does_not_raise(self):
        msg = th._document_notes_message("not a dict", "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_list_result_does_not_raise(self):
        msg = th._document_notes_message(["ok", True], "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")

    def test_integer_result_does_not_raise(self):
        msg = th._document_notes_message(42, "DREG-001")
        self.assertEqual(msg, "❌ Не удалось обновить Notes для Document.")


class TestDocumentNotesIdempotency(DocumentNotesMutationTestBase):
    def test_repeated_identical_notes_produces_unchanged_message(self):
        update1 = _make_update()
        self._run_handler(update1, finder_return=_DOCNOTES_ROW, mutator_return={
            "ok": True, "changed": False, "code": "", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update1))

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.updatedocnotes_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


class TestDocumentNotesIsolation(unittest.TestCase):
    def test_updatedoc_cmd_unchanged_source(self):
        src = inspect.getsource(th.updatedoc_cmd)
        self.assertNotIn("_mutate_target_in_thread(", src)
        self.assertNotIn("_authorize_or_reply(", src)
        self.assertNotIn("_validate_bc_transport_or_reply(", src)

    def test_updatedoc_not_in_enforcement_map(self):
        self.assertNotIn("updatedoc", th.COMMAND_ENFORCEMENT_MAP)

    def test_updatedocnotes_does_not_call_updatedoc_cmd(self):
        src = inspect.getsource(th.updatedocnotes_cmd)
        self.assertNotIn("updatedoc_cmd(", src)

    def test_updatedocnotes_does_not_call_other_document_mutators(self):
        tree = ast.parse(inspect.getsource(th.updatedocnotes_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in (
            "transition_document_status", "relink_document",
            "archive_document", "upload_and_register_document", "register_document",
        ):
            self.assertNotIn(forbidden, referenced_names)

    def test_updatedocnotes_does_not_reference_object_manager(self):
        src = inspect.getsource(th.updatedocnotes_cmd)
        self.assertNotIn("object_manager", src)
        self.assertNotIn("find_object_by_id", src)


class TestDocumentNotesArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_eleven_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_updatedocnotes_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["updatedocnotes"], {
            "resource": "DOCUMENT", "action": "UPDATE", "target_shape": "BUSINESS_AND_OBJECT",
            "operation_kind": "MUTATION", "allowed_modes": ("NOTES_ONLY",), "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_registration_line_registered_once(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("updatedocnotes",'), 1)


class TestDocumentNotesExceptionSecrecy(DocumentNotesMutationTestBase):
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
                args=["document_id=DREG-001", f"notes={_SECRET_NOTES_MARKER}"],
                finder_return={**_DOCNOTES_ROW, "business_id": _SECRET_BIZ_MARKER},
                mutator_side_effect=_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        self._assert_no_secrets_logged(mock_log_error)

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            args=["document_id=DREG-001", f"notes={_SECRET_NOTES_MARKER}"],
            finder_return={**_DOCNOTES_ROW, "business_id": _SECRET_BIZ_MARKER},
            mutator_side_effect=_boom_with_secrets,
        )
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Document.")

    def test_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, args=["document_id=DREG-001", f"notes={_SECRET_NOTES_MARKER}"],
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
                return _DOCNOTES_ROW
            return _boom_with_secrets()

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)


class TestUpdateDocumentNotesEndToEndExceptionSecrecy(unittest.TestCase):
    def test_notes_write_exception_through_real_chain_no_secrets_in_reply(self):
        update = _make_update()
        row = dict(_H1_DOCUMENT_ROW)
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        headers = list(row.keys())
        sheet.row_values.side_effect = lambda r: headers if r == 1 else list(row.values())
        sheet.update_cell.side_effect = _e2e_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.updatedocnotes_cmd(update, _make_context(
                ["document_id=DREG-001", f"notes={_E2E_SECRET_NOTES_MARKER}"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        for marker in _E2E_ALL_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("DOCUMENT_ADMIN_FIELDS_UNCHANGED", text)
        self.assertNotIn("DOCUMENT_ADMIN_FIELDS_UPDATED", text)
        self.assertEqual(text, "❌ Не удалось обновить Notes для Document.")


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A6-H0: /confirmpayment real-chain regression proof.
# Legacy /confirmpayment has no transport preflight or authorization
# (unchanged, out of scope) — this proves the strict ledger-read
# contract alone prevents the confirmed silent-financial-corruption
# defect: a Sheets read failure during the overpayment precheck must
# fail closed before any Transaction or Obligation write, with zero
# secret-marker leakage.
# ═════════════════════════════════════════════════════════════

_LEDGER_SECRET_MARKER = "LEDGER-SECRET"
_TRANSACTION_SECRET_MARKER = "TRANSACTION-SECRET"
_OBLIGATION_SECRET_MARKER = "OBLIGATION-SECRET"
_BALANCE_SECRET_MARKER = "BALANCE-SECRET"
_H0_API_PAYLOAD_MARKER = "API-PAYLOAD-SECRET"
_ALL_H0_SECRET_MARKERS = (
    _LEDGER_SECRET_MARKER, _TRANSACTION_SECRET_MARKER, _OBLIGATION_SECRET_MARKER,
    _BALANCE_SECRET_MARKER, _H0_API_PAYLOAD_MARKER,
)


def _h0_boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic Sheets outage containing {_LEDGER_SECRET_MARKER} and {_TRANSACTION_SECRET_MARKER} "
        f"and {_OBLIGATION_SECRET_MARKER} and {_BALANCE_SECRET_MARKER} and {_H0_API_PAYLOAD_MARKER}"
    )


class TestConfirmPaymentLedgerReadFailureRealChain(unittest.TestCase):
    def test_ledger_read_exception_through_real_chain_fails_closed(self):
        update = _make_update()
        txn_row = {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001",
            "Client ID": "PRS-001", "Amount": "700.00", "Currency": "KZT", "Payment Date": "2026-01-01",
            "Payment Method": "", "External Transaction ID": "", "Caller Idempotency Key": "",
            "Evidence Document ID": "", "Status": "pending", "Reversal Reason": "",
            "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
            "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
        }
        obligation_row = {
            "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-001",
            "Object ID": "", "Service ID": "", "Roadmap ID": "", "Stage ID": "",
            "Commercial Milestone Template ID": "", "Caller Idempotency Key": "",
            "Title Snapshot": "T", "Description Snapshot": "", "Obligation Amount": "1000.00", "Currency": "KZT",
            "Due Date": "", "Status": "partially_paid", "Paid Amount": f"400.00 {_OBLIGATION_SECRET_MARKER}",
            "Remaining Amount": "600.00",
            "Created At": "", "Created By": "", "Issued At": "", "Paid At": "", "Cancelled At": "",
            "Updated At": "", "Notes": "",
        }

        def find_row_side_effect(registry, record_id):
            if registry == "payment_transactions":
                return (2, dict(txn_row))
            if registry == "payment_obligations":
                return (3, dict(obligation_row))
            return None

        with patch("business_core.sheets.find_row_by_id", side_effect=find_row_side_effect), \
             patch("business_core.sheets.get_business_sheet", side_effect=_h0_boom_with_secrets), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.payment_manager.update_payment_transaction_status") as mock_txn_write, \
             patch("business_core.payment_manager.update_payment_obligation_balance") as mock_obligation_write, \
             patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось проверить историю платежей.")
        for marker in _ALL_H0_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("✅", text)
        mock_txn_write.assert_not_called()
        mock_obligation_write.assert_not_called()
        mock_log_error.assert_not_called()

    def test_successful_confirmation_through_real_chain_unaffected(self):
        update = _make_update()
        txn_row = {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001",
            "Client ID": "PRS-001", "Amount": "100.00", "Currency": "KZT", "Payment Date": "2026-01-01",
            "Payment Method": "", "External Transaction ID": "", "Caller Idempotency Key": "",
            "Evidence Document ID": "", "Status": "pending", "Reversal Reason": "",
            "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
            "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
        }
        obligation_row = {
            "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-001",
            "Object ID": "", "Service ID": "", "Roadmap ID": "", "Stage ID": "",
            "Commercial Milestone Template ID": "", "Caller Idempotency Key": "",
            "Title Snapshot": "T", "Description Snapshot": "", "Obligation Amount": "1000.00", "Currency": "KZT",
            "Due Date": "", "Status": "issued", "Paid Amount": "0.00", "Remaining Amount": "1000.00",
            "Created At": "", "Created By": "", "Issued At": "", "Paid At": "", "Cancelled At": "",
            "Updated At": "", "Notes": "",
        }

        empty_txn_sheet = MagicMock()
        empty_txn_sheet.get_all_values.return_value = [list(txn_row.keys())]

        def get_business_sheet_side_effect(registry):
            if registry == "payment_transactions":
                return empty_txn_sheet
            raise AssertionError(f"unexpected sheet read for {registry}")

        find_calls = {"n": 0}

        def find_row_side_effect(registry, record_id):
            if registry == "payment_transactions":
                find_calls["n"] += 1
                row = dict(txn_row)
                # Phase 17E-2A6-AUTH-B2: the handler now performs its
                # own first+second lookup (calls 1-2, must both see
                # "pending" for the stability check to pass) before
                # ever calling the wrapper, which then performs its
                # own first read (call 3, still "pending") and a
                # post-write verification read (call 4, "confirmed").
                if find_calls["n"] > 3:
                    row["Status"] = "confirmed"
                return (2, row)
            if registry == "payment_obligations":
                return (3, dict(obligation_row))
            return None

        with patch("business_core.sheets.find_row_by_id", side_effect=find_row_side_effect), \
             patch("business_core.sheets.get_business_sheet", side_effect=get_business_sheet_side_effect), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.business_builder._synchronize_payment_obligation_after_transaction_change",
                   return_value={"ok": True, "paid_amount": "100.00", "remaining_amount": "900.00", "status": "partially_paid"}):
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertIn("✅", text)


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A6-H1: Payment lifecycle handler outer-exception
# secrecy + real-chain regressions. Legacy /confirmpayment and
# /reversepayment remain unauthorized (unchanged, out of scope) —
# this proves the manager/wrapper/mapper/handler secrecy chain
# established this phase prevents raw exception text, manager error
# text, and secret markers from ever reaching Telegram or logs,
# across every reachable infrastructure-failure point, without
# claiming atomicity anywhere.
#
# Phase 17E-2A6-AUTH-B1: /failpayment gained transport preflight,
# authorization, and a mandatory second lookup — the two
# failpayment-specific tests below now additionally mock the
# authorization adapter to reach the mutation boundary they test.
# Dedicated transport/argument/lookup/authorization test coverage
# for the new failpayment authorization gate lives in the
# TestFailPayment* classes further below.
# ═════════════════════════════════════════════════════════════

_SECRET_REVERSAL_MARKER = "REVERSAL-SECRET"
_ALL_H1_SECRET_MARKERS = _ALL_H0_SECRET_MARKERS + (_SECRET_BIZ_MARKER, _SECRET_REVERSAL_MARKER)


def _h1_boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_LEDGER_SECRET_MARKER} and {_TRANSACTION_SECRET_MARKER} "
        f"and {_OBLIGATION_SECRET_MARKER} and {_BALANCE_SECRET_MARKER} and {_H0_API_PAYLOAD_MARKER} "
        f"and {_SECRET_BIZ_MARKER} and {_SECRET_REVERSAL_MARKER}"
    )


class TestPaymentLifecycleHandlerOuterExceptionSecrecy(unittest.TestCase):
    """Section 23: force an unexpected exception from the
    business_builder wrapper itself (not a Sheets-layer failure) and
    prove the handler's own outer except-boundary is safe."""

    def test_confirmpayment_cmd_unexpected_wrapper_exception(self):
        update = _make_update()
        txn_row = {"Business ID": "BIZ-001", "Payment Obligation ID": "POB-001", "Status": "pending"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn_row), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.business_builder.confirm_payment_transaction", side_effect=_h1_boom_with_secrets), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось подтвердить Payment.")
        mock_log_error.assert_called_once_with("confirmpayment_cmd infrastructure failure")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
            for call_args in mock_log_error.call_args_list:
                for arg in list(call_args.args) + list(call_args.kwargs.values()):
                    self.assertNotIn(marker, str(arg))
        self.assertNotIn("PTXN-001", text)
        self.assertNotIn("owner", text)

    def test_reversepayment_cmd_unexpected_wrapper_exception(self):
        update = _make_update()
        txn_row = {"Business ID": "BIZ-001", "Payment Obligation ID": "POB-001", "Status": "confirmed"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn_row), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.business_builder.reverse_payment_transaction", side_effect=_h1_boom_with_secrets), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _run(th.reversepayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", f'reversal_reason="secret {_SECRET_REVERSAL_MARKER}"', "reversed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось реверснуть Payment.")
        mock_log_error.assert_called_once_with("reversepayment_cmd infrastructure failure")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
            for call_args in mock_log_error.call_args_list:
                for arg in list(call_args.args) + list(call_args.kwargs.values()):
                    self.assertNotIn(marker, str(arg))
        self.assertNotIn("PTXN-001", text)
        self.assertNotIn("owner", text)

    def test_failpayment_cmd_unexpected_wrapper_exception(self):
        update = _make_update()
        txn_row = {"Business ID": "BIZ-001", "Payment Obligation ID": "", "Status": "pending"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn_row), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.business_builder.fail_payment_transaction", side_effect=_h1_boom_with_secrets), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _run(th.failpayment_cmd(update, _make_context(["payment_transaction_id=PTXN-001"])))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось обновить статус Payment.")
        mock_log_error.assert_called_once_with("failpayment_cmd infrastructure failure")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("PTXN-001", text)

    def test_confirmpayment_cmd_normal_success_path_unaffected(self):
        update = _make_update()
        txn_row = {"Business ID": "BIZ-001", "Payment Obligation ID": "POB-001", "Status": "pending"}
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=txn_row), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.business_builder.confirm_payment_transaction",
                   return_value={"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None, "paid_amount": "1.00", "remaining_amount": "1.00", "currency": "KZT"}), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertIn("✅", text)


class TestPaymentLifecycleRealChainRegressions(unittest.TestCase):
    """Section 24: synthetic real-chain regressions covering every
    reachable infrastructure-failure and malformed-result point in
    the confirm/reverse/fail chains, using synthetic rows only."""

    def _txn_row(self, status="pending", amount="100.00"):
        return {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001",
            "Client ID": "PRS-001", "Amount": amount, "Currency": "KZT", "Payment Date": "2026-01-01",
            "Payment Method": "", "External Transaction ID": "", "Caller Idempotency Key": "",
            "Evidence Document ID": "", "Status": status, "Reversal Reason": "",
            "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
            "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
        }

    def _obligation_row(self, status="issued", paid="0.00", remaining="1000.00"):
        return {
            "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-001",
            "Object ID": "", "Service ID": "", "Roadmap ID": "", "Stage ID": "",
            "Commercial Milestone Template ID": "", "Caller Idempotency Key": "",
            "Title Snapshot": "T", "Description Snapshot": "", "Obligation Amount": "1000.00", "Currency": "KZT",
            "Due Date": "", "Status": status, "Paid Amount": paid, "Remaining Amount": remaining,
            "Created At": "", "Created By": "", "Issued At": "", "Paid At": "", "Cancelled At": "",
            "Updated At": "", "Notes": "",
        }

    def test_1_confirm_transaction_write_exception(self):
        """Case 1: Transaction status write itself raises — must fail
        closed before any Obligation write, with the fixed
        PAYMENT_PERSISTENCE_FAILED message."""
        update = _make_update()
        txn_row = self._txn_row("pending")
        obligation_row = self._obligation_row()

        def find_row_side_effect(registry, record_id):
            if registry == "payment_transactions":
                return (2, dict(txn_row))
            if registry == "payment_obligations":
                return (3, dict(obligation_row))
            return None

        txn_sheet = MagicMock()
        txn_sheet.row_values.return_value = list(txn_row.keys())
        txn_sheet.update_cell.side_effect = _h1_boom_with_secrets

        def get_business_sheet_side_effect(registry):
            if registry == "payment_transactions":
                return txn_sheet
            raise AssertionError(f"unexpected sheet read for {registry}")

        with patch("business_core.sheets.find_row_by_id", side_effect=find_row_side_effect), \
             patch("business_core.sheets.get_business_sheet", side_effect=get_business_sheet_side_effect), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.payment_manager.update_payment_obligation_balance") as mock_obligation_write:
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось подтвердить Payment.")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("✅", text)
        mock_obligation_write.assert_not_called()

    def test_2_confirm_obligation_balance_write_exception(self):
        """Case 2: Transaction write succeeds, but the Obligation
        balance write inside synchronization raises — must preserve
        the manual-review partial-state warning, not a false success.
        The obligation starts at Paid Amount 0.00 with a real ledger
        entry that recomputes to a non-zero balance, so the write is
        actually attempted (not skipped as a no-op)."""
        update = _make_update()
        txn_row = self._txn_row("pending")
        obligation_row = self._obligation_row()
        confirmed_ledger_entry = {**txn_row, "Status": "confirmed"}

        find_calls = {"n": 0}

        def find_row_side_effect(registry, record_id):
            if registry == "payment_transactions":
                find_calls["n"] += 1
                row = dict(txn_row)
                # Phase 17E-2A6-AUTH-B2: handler's own first+second
                # lookup (calls 1-2, must both see "pending") precede
                # the wrapper's own first read (call 3, still
                # "pending") and post-write verification read
                # (call 4, "confirmed").
                if find_calls["n"] > 3:
                    row["Status"] = "confirmed"
                return (2, row)
            if registry == "payment_obligations":
                return (3, dict(obligation_row))
            return None

        obligation_sheet = MagicMock()
        obligation_sheet.row_values.return_value = list(obligation_row.keys())
        obligation_sheet.update_cell.side_effect = _h1_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", side_effect=find_row_side_effect), \
             patch("business_core.sheets.get_business_sheet", return_value=obligation_sheet), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.payment_manager.list_payment_transactions_strict", return_value=[confirmed_ledger_entry]), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "\n".join([
            "⚠️ Payment подтверждён, но синхронизация баланса Obligation не удалась.",
            "Требуется ручная проверка.",
        ]))
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("Infrastructure failure", text)
        self.assertNotIn("✅", text)

    def test_3_reverse_transaction_write_exception(self):
        update = _make_update()
        txn_row = self._txn_row("confirmed")
        txn_sheet = MagicMock()
        txn_sheet.row_values.return_value = list(txn_row.keys())
        txn_sheet.update_cell.side_effect = _h1_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, dict(txn_row))), \
             patch("business_core.sheets.get_business_sheet", return_value=txn_sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.payment_manager.update_payment_obligation_balance") as mock_obligation_write:
            _run(th.reversepayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", f'reversal_reason="secret {_SECRET_REVERSAL_MARKER}"', "reversed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось реверснуть Payment.")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("✅", text)
        mock_obligation_write.assert_not_called()

    def test_4_reverse_obligation_balance_write_exception(self):
        update = _make_update()
        txn_row = self._txn_row("confirmed")
        obligation_row = self._obligation_row(status="partially_paid", paid="100.00", remaining="900.00")

        find_calls = {"n": 0}

        def find_row_side_effect(registry, record_id):
            if registry == "payment_transactions":
                find_calls["n"] += 1
                row = dict(txn_row)
                # Phase 17E-2A6-AUTH-B2: handler's own first+second
                # lookup (calls 1-2, must both see "confirmed" for the
                # stability check to pass) precede the wrapper's own
                # first read (call 3, still "confirmed") and post-write
                # verification read (call 4, "reversed").
                if find_calls["n"] > 3:
                    row["Status"] = "reversed"
                return (2, row)
            if registry == "payment_obligations":
                return (3, dict(obligation_row))
            return None

        txn_sheet = MagicMock()
        txn_sheet.row_values.return_value = list(txn_row.keys())
        obligation_sheet = MagicMock()
        obligation_sheet.row_values.return_value = list(obligation_row.keys())
        obligation_sheet.update_cell.side_effect = _h1_boom_with_secrets

        def get_business_sheet_side_effect(registry):
            if registry == "payment_transactions":
                return txn_sheet
            if registry == "payment_obligations":
                return obligation_sheet
            raise AssertionError(f"unexpected sheet read for {registry}")

        with patch("business_core.sheets.find_row_by_id", side_effect=find_row_side_effect), \
             patch("business_core.sheets.get_business_sheet", side_effect=get_business_sheet_side_effect), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "reversal_reason=refund", "reversed_by=owner"]
            )))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "\n".join([
            "⚠️ Payment реверснут, но синхронизация баланса Obligation не удалась.",
            "Требуется ручная проверка.",
        ]))
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("✅", text)

    def test_5_fail_transaction_write_exception(self):
        update = _make_update()
        txn_row = self._txn_row("pending")
        txn_sheet = MagicMock()
        txn_sheet.row_values.return_value = list(txn_row.keys())
        txn_sheet.update_cell.side_effect = _h1_boom_with_secrets

        with patch("business_core.sheets.find_row_by_id", return_value=(2, dict(txn_row))), \
             patch("business_core.sheets.get_business_sheet", return_value=txn_sheet), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(["payment_transaction_id=PTXN-001"])))

        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось обновить статус Payment.")
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)
        self.assertNotIn("✅", text)

    def test_6_transaction_finder_exception_reaching_handler_boundary(self):
        """Case 6: the first finder itself raises (Sheets outage
        before any row is even found). Phase 17E-2A6-AUTH-B2: the
        handler's own first-lookup try/except now catches this before
        the wrapper is ever reached, replying with the fixed
        temporarily-unavailable message and logging nothing (matching
        the established dedicated-command finder-boundary convention
        from ObligationNotes/failpayment)."""
        update = _make_update()
        with patch("business_core.sheets.find_row_by_id", side_effect=_h1_boom_with_secrets), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.telegram_handlers.log.error") as mock_log_error:
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")
        mock_log_error.assert_not_called()
        for marker in _ALL_H1_SECRET_MARKERS:
            self.assertNotIn(marker, text)

    def test_7_malformed_manager_result_through_real_chain(self):
        """Case 7: update_payment_transaction_status returns a
        malformed (non-dict) result — the wrapper must not crash and
        must fall through to PAYMENT_PERSISTENCE_FAILED."""
        update = _make_update()
        with patch("business_core.payment_manager.find_payment_transaction_by_id", return_value=self._txn_row("pending")), \
             patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation_row()), \
             patch("business_core.payment_manager.list_payment_transactions_strict", return_value=[]), \
             patch("business_core.payment_manager.update_payment_transaction_status", return_value=None), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "❌ Не удалось подтвердить Payment.")

    def test_8_malformed_synchronization_result_through_real_chain(self):
        """Case 8: _synchronize_payment_obligation_after_transaction_change
        returns a malformed (non-dict) result after the Transaction
        write already succeeded — must preserve the manual-review
        partial-state warning, never a false success."""
        update = _make_update()
        # Phase 17E-2A6-AUTH-B2: the handler's own first+second lookup
        # (calls 1-2, must both see "pending") precede the wrapper's
        # own first read (call 3, still "pending") and post-write
        # verification read (call 4, "confirmed").
        with patch("business_core.payment_manager.find_payment_transaction_by_id",
                   side_effect=[self._txn_row("pending"), self._txn_row("pending"), self._txn_row("pending"), self._txn_row("confirmed")]), \
             patch("business_core.payment_manager.find_payment_obligation_by_id", return_value=self._obligation_row()), \
             patch("business_core.payment_manager.list_payment_transactions_strict", return_value=[]), \
             patch("business_core.payment_manager.update_payment_transaction_status",
                   return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.business_builder._synchronize_payment_obligation_after_transaction_change", return_value="not a dict"), \
             patch("business_core.payment_manager.update_payment_obligation_balance") as mock_obligation_write, \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(
                ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
            )))
        call = update.message.reply_text.call_args
        text = call.args[0] if call.args else call.kwargs.get("text", "")
        self.assertEqual(text, "\n".join([
            "⚠️ Payment подтверждён, но синхронизация баланса Obligation не удалась.",
            "Требуется ручная проверка.",
        ]))
        mock_obligation_write.assert_not_called()


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A6-AUTH-B1: /failpayment dedicated authorization gate.
# Single-row foundation of the Payment lifecycle authorization
# pattern — FINANCE/UPDATE, target_shape=BUSINESS, MUTATION,
# requires_fresh_reread=True, SINGLE_ROW_MUTATION, IDEMPOTENT.
# Mirrors the ObligationNotes* test structure above, adapted for:
#   - the {"payment_transaction_id", "_pos0"} allowed-key set
#     (named form and positional fallback, matching the pre-existing
#     /failpayment and /payment argument convention);
#   - a three-field stability comparison (Business ID, Payment
#     Obligation ID, Status) instead of Business ID alone, since
#     confirm/reverse write both fields and a concurrent status
#     change must also be caught;
#   - a single-argument mutator (fail_payment_transaction takes only
#     payment_transaction_id — no second parameter to assert on).
# /confirmpayment and /reversepayment are untouched by this phase —
# their own H0/H1 real-chain regressions above are unaffected.
# ═════════════════════════════════════════════════════════════

_FP_ROW = {
    "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001",
    "Client ID": "PRS-001", "Amount": "100.00", "Currency": "KZT", "Payment Date": "2026-01-01",
    "Payment Method": "", "External Transaction ID": "", "Caller Idempotency Key": "",
    "Evidence Document ID": "", "Status": "pending", "Reversal Reason": "",
    "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
    "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
}
_FP_ROW_BLANK_OBLIGATION = {**_FP_ROW, "Payment Obligation ID": ""}
_FP_ROW_OTHER_BIZ = {**_FP_ROW, "Business ID": "BIZ-002"}
_FP_ROW_OTHER_OBLIGATION = {**_FP_ROW, "Payment Obligation ID": "POB-002"}
_FP_ROW_OTHER_STATUS = {**_FP_ROW, "Status": "failed"}
_FP_ROW_MISSING_OWNERSHIP = {**_FP_ROW, "Business ID": ""}
_FP_ROW_WHITESPACE_OWNERSHIP = {**_FP_ROW, "Business ID": "   "}

_FP_FINDER_PATH = "business_core.payment_manager.find_payment_transaction_by_id"
_FP_MUTATOR_PATH = "business_core.business_builder.fail_payment_transaction"

_FP_ID_ARG = "payment_transaction_id=PTXN-001"
_FP_ARGS = [_FP_ID_ARG]

_FP_SECRET_ROW_MARKER = "TRANSACTION-SECRET"


def _fp_boom_with_secrets(*_a, **_k):
    raise RuntimeError(f"synthetic failure containing {_FP_SECRET_ROW_MARKER} and {_SECRET_BIZ_MARKER}")


class FailPaymentMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_FP_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_FP_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None})
        patches.append(patch(_FP_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _FP_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.failpayment_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestFailPaymentTransport(FailPaymentMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW)
        mock_mutator.assert_called_once()


class TestFailPaymentArguments(FailPaymentMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context([])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_named_form_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, args=["payment_transaction_id=PTXN-001"], finder_return=_FP_ROW)
        mock_mutator.assert_called_once_with("PTXN-001")

    def test_positional_form_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, args=["PTXN-001"], finder_return=_FP_ROW)
        mock_mutator.assert_called_once_with("PTXN-001")

    def test_named_takes_precedence_over_positional(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH, return_value=_FP_ROW) as mock_finder, \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch(_FP_MUTATOR_PATH, return_value={"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(["PTXN-999", "payment_transaction_id=PTXN-001"])))
        mock_finder.assert_called_with("PTXN-001")
        mock_mutator.assert_called_once_with("PTXN-001")

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH), patch(_FP_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["status=confirmed"])))
        self.assertEqual(self._sent_text(update), "❌ /failpayment принимает только payment_transaction_id.")

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_object_id_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["object_id=OBJ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_payment_obligation_id_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["payment_obligation_id=POB-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["status=confirmed"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_amount_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_balance_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["balance=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_actor_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["actor=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_confirmed_by_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["confirmed_by=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_reversed_by_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["reversed_by=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_reversal_reason_key_rejected(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH) as mock_finder, patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS + ["reversal_reason=x"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW)
        mock_mutator.assert_called_once()

    def test_secret_values_never_echoed(self):
        update = _make_update()
        self._run_handler(
            update, args=[f"payment_transaction_id={_FP_SECRET_ROW_MARKER}"],
            finder_return=None,
        )
        self.assertNotIn(_FP_SECRET_ROW_MARKER, self._sent_text(update))


class TestFailPaymentFirstLookup(FailPaymentMutationTestBase):
    def test_finder_runs_via_asyncio_to_thread(self):
        update = _make_update()
        recorded = []

        async def fake_to_thread(func, *args, **kwargs):
            recorded.append((getattr(func, "__name__", None), args))
            if len(recorded) <= 2:
                return _FP_ROW
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        self.assertIn("PTXN-001", recorded[0][1])

    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_FP_ROW)
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
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_FP_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_FP_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_obligation_id_allowed_reaches_authorization(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_FP_ROW_BLANK_OBLIGATION)
        mock_authz.assert_called_once()
        mock_mutator.assert_called_once()


class TestFailPaymentAuthorization(FailPaymentMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_FP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_FP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_object_id_omitted(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_FP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs.get("object_id", ""), "")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.failpayment_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _FP_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_denial_generic_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, authz_result=_deny_result())
        self.assertEqual(self._sent_text(update), "Запись недоступна или не найдена.")

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_authorized_exactly_once(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_FP_ROW)
        self.assertEqual(mock_authz.call_count, 1)

    def test_owner_allow_continues_to_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW, authz_result=_allow_result())
        mock_mutator.assert_called_once()


class TestFailPaymentFreshReread(FailPaymentMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(transaction_id):
            finder_calls.append(transaction_id)
            return _FP_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)
        self.assertEqual(finder_calls, ["PTXN-001", "PTXN-001"])

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(transaction_id):
            finder_calls.append(transaction_id)
            return _FP_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_second_row_missing_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else None

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_missing_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_second_business_id_blank_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_MISSING_OWNERSHIP

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_business_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_obligation_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_OBLIGATION

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_status_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_STATUS

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_mismatch_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertEqual(text, "Запись изменилась. Повтори команду ещё раз.")
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_unchanged_stability_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW)
        mock_mutator.assert_called_once()

    def test_no_automatic_reauthorization_on_mismatch(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_STATUS

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()


class TestFailPaymentMutation(FailPaymentMutationTestBase):
    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_payment_transaction_by_id":
                return _FP_ROW
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        self.assertIn("fail_payment_transaction", seen_funcs)

    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW)
        mock_mutator.assert_called_once_with("PTXN-001")

    def test_no_retry_on_mutation_exception(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_FP_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_no_raw_exception_in_reply(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_FP_ROW, mutator_side_effect=boom)
        text = self._sent_text(update)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("write failed", text)

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_FP_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить статус Payment.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_FP_ROW, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("failpayment_cmd infrastructure failure")

    def test_mapper_reused_unchanged_on_success(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None,
        })
        self.assertEqual(self._sent_text(update), "✅ Payment PTXN-001 помечен failed.")

    def test_mapper_reused_unchanged_on_unchanged(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_FAILED", "error": None,
        })
        self.assertEqual(self._sent_text(update), "ℹ️ Payment PTXN-001 уже помечен failed — изменений нет.")

    def test_residual_toctou_not_found_after_authorization(self):
        # The handler's own second lookup already caught disappearance
        # before ever calling the wrapper — this covers the residual
        # case where business_builder itself reports not-found (e.g.
        # a row deleted between the handler's second lookup and the
        # wrapper's own internal read), routed through the unchanged,
        # already-hardened mapper.
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": "not found",
        })
        self.assertEqual(self._sent_text(update), "❌ Payment PTXN-001 не найден.")

    def test_invalid_transition_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Переход в failed возможен только из статуса pending.")

    def test_persistence_failure_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_PERSISTENCE_FAILED", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить статус Payment.")

    def test_malformed_wrapper_result_does_not_raise(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return="not a dict")
        self.assertEqual(self._sent_text(update), "❌ Не удалось обновить статус Payment.")


class TestFailPaymentIdempotency(FailPaymentMutationTestBase):
    def test_repeated_fail_produces_unchanged_message(self):
        update = _make_update()
        self._run_handler(update, finder_return=_FP_ROW, mutator_return={
            "ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_FAILED", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_no_automatic_retry_in_handler(self):
        src = inspect.getsource(th.failpayment_cmd)
        self.assertNotIn("for _ in range", src)
        self.assertNotIn("while True", src)
        self.assertNotIn("retry", src.lower())


class TestFailPaymentIsolation(unittest.TestCase):
    # confirmpayment_cmd/reversepayment_cmd were authorized in Phase
    # 17E-2A6-AUTH-B2, using the same pattern as failpayment_cmd
    # (Phase 17E-2A6-AUTH-B1) — see TestConfirmReversePaymentIsolation
    # below for the isolation guards specific to that phase.
    def test_failpayment_does_not_call_confirm_or_reverse(self):
        tree = ast.parse(inspect.getsource(th.failpayment_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("confirm_payment_transaction", "reverse_payment_transaction"):
            self.assertNotIn(forbidden, referenced_names)

    def test_failpayment_no_obligation_lookup_or_write(self):
        src = inspect.getsource(th.failpayment_cmd)
        for forbidden in ("find_payment_obligation_by_id", "update_payment_obligation_balance"):
            self.assertNotIn(forbidden, src)

    def test_failpayment_no_direct_sheets_write(self):
        src = inspect.getsource(th.failpayment_cmd)
        for forbidden in ("get_business_sheet(", "update_cell(", "find_row_by_id("):
            self.assertNotIn(forbidden, src)

    def test_failpayment_no_cache(self):
        src = inspect.getsource(th.failpayment_cmd)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)


class TestFailPaymentArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_twelve_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_failpayment_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["failpayment"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_registration_line_registered_once(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("failpayment",'), 1)

    def test_mutation_uses_helper_exactly_once_on_authorized_stable_path(self):
        # Identity-based check on the asyncio.to_thread primitive
        # itself (the same proven-stable pattern used by
        # TestFailPaymentMutation.test_mutation_runs_via_asyncio_to_thread
        # above) rather than patching the local _mutate_target_in_thread
        # coroutine directly — patch()'s AsyncMock autodetection for a
        # locally-defined async def proved order-dependent across the
        # full suite in practice.
        update = _make_update()
        mock_mutator = MagicMock(return_value={"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_FAILED", "error": None})

        async def spy_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch(_FP_FINDER_PATH, return_value=_FP_ROW), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch(_FP_MUTATOR_PATH, new=mock_mutator), \
             patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread) as spy, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mutator_calls = [c for c in spy.call_args_list if c.args and c.args[0] is mock_mutator]
        self.assertEqual(len(mutator_calls), 1)

    def test_unauthorized_path_zero_mutation(self):
        update = _make_update()
        with patch(_FP_FINDER_PATH, return_value=_FP_ROW), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_deny_result())), \
             patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_mutator.assert_not_called()

    def test_unstable_path_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _FP_ROW if calls["n"] == 1 else _FP_ROW_OTHER_STATUS

        with patch(_FP_FINDER_PATH, side_effect=finder), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch(_FP_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.failpayment_cmd(update, _make_context(_FP_ARGS)))
        mock_mutator.assert_not_called()


class TestFailPaymentExceptionSecrecy(FailPaymentMutationTestBase):
    def _assert_no_secrets_logged(self, mock_log_error):
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)
                self.assertNotIn(_FP_SECRET_ROW_MARKER, text)

    def test_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                finder_return={**_FP_ROW, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_fp_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        self._assert_no_secrets_logged(mock_log_error)

    def test_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            finder_return={**_FP_ROW, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_fp_boom_with_secrets,
        )
        text = self._sent_text(update)
        self.assertNotIn(_FP_SECRET_ROW_MARKER, text)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)
        self.assertEqual(text, "❌ Не удалось обновить статус Payment.")

    def test_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(update, finder_side_effect=_fp_boom_with_secrets)
        text = self._sent_text(update)
        self.assertNotIn(_FP_SECRET_ROW_MARKER, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_second_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FP_ROW
            raise RuntimeError(f"boom {_FP_SECRET_ROW_MARKER}")

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertNotIn(_FP_SECRET_ROW_MARKER, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_authorization_denial_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, finder_return={**_FP_ROW, "Business ID": _SECRET_BIZ_MARKER}, authz_result=_deny_result(),
        )
        text = self._sent_text(update)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)


# ═════════════════════════════════════════════════════════════
# Phase 17E-2A6-AUTH-B2: /confirmpayment and /reversepayment
# authorization gate. Multi-row extension of the failpayment
# single-row pattern above — FINANCE/UPDATE, target_shape=BUSINESS,
# MUTATION, requires_fresh_reread=True, MULTI_ROW_MUTATION,
# IDEMPOTENT. Differs from failpayment in two respects:
#   - both first and second lookup require a non-blank Payment
#     Obligation ID (fail closed otherwise) — confirm/reverse
#     synchronize an Obligation, failpayment does not;
#   - the mutator takes two/three positional arguments
#     (transaction_id, confirmed_by) / (transaction_id,
#     reversal_reason, reversed_by) instead of one.
# ═════════════════════════════════════════════════════════════

_CRP_ROW = {
    "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001", "Payment Obligation ID": "POB-001",
    "Client ID": "PRS-001", "Amount": "100.00", "Currency": "KZT", "Payment Date": "2026-01-01",
    "Payment Method": "", "External Transaction ID": "", "Caller Idempotency Key": "",
    "Evidence Document ID": "", "Status": "pending", "Reversal Reason": "",
    "Confirmed At": "", "Confirmed By": "", "Reversed At": "", "Reversed By": "",
    "Created At": "", "Created By": "", "Updated At": "", "Notes": "",
}
_CRP_ROW_CONFIRMED = {**_CRP_ROW, "Status": "confirmed"}
_CRP_ROW_BLANK_OBLIGATION = {**_CRP_ROW, "Payment Obligation ID": ""}
_CRP_ROW_OTHER_BIZ = {**_CRP_ROW, "Business ID": "BIZ-002"}
_CRP_ROW_OTHER_OBLIGATION = {**_CRP_ROW, "Payment Obligation ID": "POB-002"}
_CRP_ROW_OTHER_STATUS = {**_CRP_ROW, "Status": "failed"}
_CRP_ROW_MISSING_OWNERSHIP = {**_CRP_ROW, "Business ID": ""}
_CRP_ROW_WHITESPACE_OWNERSHIP = {**_CRP_ROW, "Business ID": "   "}

_CRP_FINDER_PATH = "business_core.payment_manager.find_payment_transaction_by_id"
_CONFIRM_MUTATOR_PATH = "business_core.business_builder.confirm_payment_transaction"
_REVERSE_MUTATOR_PATH = "business_core.business_builder.reverse_payment_transaction"

_CONFIRM_ARGS = ["payment_transaction_id=PTXN-001", "confirmed_by=owner"]
_REVERSE_ARGS = ["payment_transaction_id=PTXN-001", "reversal_reason=refund", "reversed_by=owner"]

_CRP_SECRET_ROW_MARKER = "TRANSACTION-SECRET"


def _crp_boom_with_secrets(*_a, **_k):
    raise RuntimeError(f"synthetic failure containing {_CRP_SECRET_ROW_MARKER} and {_SECRET_BIZ_MARKER}")


class ConfirmPaymentMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_CRP_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_CRP_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None,
                                       "paid_amount": "100.00", "remaining_amount": "900.00", "currency": "KZT"})
        patches.append(patch(_CONFIRM_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _CONFIRM_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.confirmpayment_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class ReversePaymentMutationTestBase(unittest.TestCase):
    def _run_handler(self, update, args=None, *, finder_side_effect=None, finder_return=None,
                      authz_result=None, mutator_return=None, mutator_side_effect=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(_CRP_FINDER_PATH, side_effect=finder_side_effect))
        else:
            patches.append(patch(_CRP_FINDER_PATH, return_value=finder_return))

        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch(_AUTHZ_PATH, new=mock_authz))

        if mutator_side_effect is not None:
            mock_mutator = MagicMock(side_effect=mutator_side_effect)
        else:
            mock_mutator = MagicMock(return_value=mutator_return if mutator_return is not None else
                                      {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None,
                                       "paid_amount": "0.00", "remaining_amount": "1000.00", "currency": "KZT"})
        patches.append(patch(_REVERSE_MUTATOR_PATH, new=mock_mutator))

        ctx = _make_context(args if args is not None else _REVERSE_ARGS)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(th.reversepayment_cmd(update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz, mock_mutator

    def _sent_text(self, update) -> str:
        call = update.message.reply_text.call_args
        return call.args[0] if call.args else call.kwargs.get("text", "")


class TestConfirmPaymentTransport(ConfirmPaymentMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW)
        mock_mutator.assert_called_once()


class TestReversePaymentTransport(ReversePaymentMutationTestBase):
    def test_group_zero_finder_and_mutation(self):
        update = _make_update(chat_type="group")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_supergroup_zero_finder_and_mutation(self):
        update = _make_update(chat_type="supergroup")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_channel_zero_finder_and_mutation(self):
        update = _make_update(chat_type="channel")
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_malformed_update_zero_finder_and_mutation(self):
        update = SimpleNamespace()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_effective_user_zero_finder_and_mutation(self):
        update = _make_update(user_id=None)
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_user_id_zero_finder_and_mutation(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=None)
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_private_allow_path_reaches_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_mutator.assert_called_once()


class TestConfirmPaymentArguments(ConfirmPaymentMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(["confirmed_by=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_confirmed_by_username_fallback(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=570004109, username="fallback_user")
        mock_authz, mock_mutator = self._run_handler(
            update, args=["payment_transaction_id=PTXN-001"], finder_return=_CRP_ROW,
        )
        mock_mutator.assert_called_once()
        self.assertEqual(mock_mutator.call_args.args[1], "fallback_user")

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH), patch(_CONFIRM_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["status=confirmed"])))
        self.assertEqual(self._sent_text(update), "❌ /confirmpayment принимает только payment_transaction_id и confirmed_by.")

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_object_id_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["object_id=OBJ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["status=confirmed"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_amount_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_reversal_fields_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS + ["reversal_reason=x"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_secret_values_never_echoed(self):
        update = _make_update()
        self._run_handler(
            update, args=[f"payment_transaction_id={_CRP_SECRET_ROW_MARKER}", "confirmed_by=owner"],
            finder_return=None,
        )
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, self._sent_text(update))

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW)
        mock_mutator.assert_called_once()


class TestReversePaymentArguments(ReversePaymentMutationTestBase):
    def test_missing_id_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(["reversal_reason=refund", "reversed_by=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_reversal_reason_zero_finder_and_mutation(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(["payment_transaction_id=PTXN-001", "reversed_by=owner"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_reversed_by_username_fallback(self):
        update = _make_update()
        update.effective_user = SimpleNamespace(id=570004109, username="fallback_user")
        _, mock_mutator = self._run_handler(
            update, args=["payment_transaction_id=PTXN-001", "reversal_reason=refund"], finder_return=_CRP_ROW_CONFIRMED,
        )
        mock_mutator.assert_called_once()
        self.assertEqual(mock_mutator.call_args.args[2], "fallback_user")

    def test_quoted_reason_with_spacing_preserved(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(
            update, args=["payment_transaction_id=PTXN-001", 'reversal_reason="client requested refund"', "reversed_by=owner"],
            finder_return=_CRP_ROW_CONFIRMED,
        )
        mock_mutator.assert_called_once_with("PTXN-001", "client requested refund", "owner")

    def test_unknown_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["foo=bar"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_unknown_key_usage_message(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH), patch(_REVERSE_MUTATOR_PATH), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["status=confirmed"])))
        self.assertEqual(self._sent_text(update), "❌ /reversepayment принимает только payment_transaction_id, reversal_reason и reversed_by.")

    def test_business_id_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["business_id=BIZ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_object_id_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["object_id=OBJ-001"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_status_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["status=confirmed"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_amount_key_rejected(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH) as mock_finder, patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS + ["amount=50"])))
        mock_finder.assert_not_called()
        mock_mutator.assert_not_called()

    def test_secret_values_never_echoed(self):
        update = _make_update()
        self._run_handler(
            update, args=[f"payment_transaction_id={_CRP_SECRET_ROW_MARKER}", "reversal_reason=refund", "reversed_by=owner"],
            finder_return=None,
        )
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, self._sent_text(update))

    def test_valid_key_set_continues(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_mutator.assert_called_once()


class TestConfirmPaymentFirstLookup(ConfirmPaymentMutationTestBase):
    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW)
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

    def test_missing_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_WHITESPACE_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_obligation_id_fails_closed_unlike_failpayment(self):
        # Unlike failpayment, confirm/reverse synchronize an
        # Obligation — a blank Obligation ID must fail closed, not
        # be allowed through.
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_BLANK_OBLIGATION)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestReversePaymentFirstLookup(ReversePaymentMutationTestBase):
    def test_finder_called_before_authorization(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_authz.assert_called_once()

    def test_finder_none_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=None)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_finder_exception_zero_authorization_and_mutation(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("sheets down")

        mock_authz, mock_mutator = self._run_handler(update, finder_side_effect=boom)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_missing_business_id_zero_authorization_and_mutation(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_MISSING_OWNERSHIP)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()

    def test_blank_obligation_id_fails_closed_unlike_failpayment(self):
        update = _make_update()
        mock_authz, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_BLANK_OBLIGATION)
        mock_authz.assert_not_called()
        mock_mutator.assert_not_called()


class TestConfirmPaymentAuthorization(ConfirmPaymentMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_object_id_omitted(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs.get("object_id", ""), "")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.confirmpayment_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _CRP_ROW

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_authorized_exactly_once(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW)
        self.assertEqual(mock_authz.call_count, 1)


class TestReversePaymentAuthorization(ReversePaymentMutationTestBase):
    def test_resource_finance_action_update(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["resource"], "FINANCE")
        self.assertEqual(kwargs["action"], "UPDATE")

    def test_business_id_comes_only_from_stored_row(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs["business_id"], "BIZ-001")

    def test_object_id_omitted(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        _, kwargs = mock_authz.call_args
        self.assertEqual(kwargs.get("object_id", ""), "")

    def test_caller_cannot_spoof_business_id(self):
        src = inspect.getsource(th.reversepayment_cmd)
        self.assertNotIn('args.get("business_id"', src)

    def test_denial_zero_second_lookup_and_mutation(self):
        update = _make_update()
        calls = []

        def finder(*a, **k):
            calls.append(a)
            return _CRP_ROW_CONFIRMED

        mock_authz, mock_mutator = self._run_handler(
            update, finder_side_effect=finder, authz_result=_deny_result(),
        )
        self.assertEqual(len(calls), 1)
        mock_mutator.assert_not_called()

    def test_infrastructure_failure_zero_mutation(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, authz_result=_infra_failure_result())
        mock_mutator.assert_not_called()

    def test_authorized_exactly_once(self):
        update = _make_update()
        mock_authz, _ = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        self.assertEqual(mock_authz.call_count, 1)


class TestConfirmPaymentFreshReread(ConfirmPaymentMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(transaction_id):
            finder_calls.append(transaction_id)
            return _CRP_ROW

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)

    def test_second_lookup_only_after_allow(self):
        update = _make_update()
        finder_calls = []

        def finder(transaction_id):
            finder_calls.append(transaction_id)
            return _CRP_ROW

        self._run_handler(update, finder_side_effect=finder, authz_result=_deny_result())
        self.assertEqual(len(finder_calls), 1)

    def test_business_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_BIZ

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_obligation_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_OBLIGATION

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_status_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_STATUS

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_disappeared_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_mismatch_message_reveals_no_business_id(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_BIZ

        self._run_handler(update, finder_side_effect=finder)
        text = self._sent_text(update)
        self.assertNotIn("BIZ-001", text)
        self.assertNotIn("BIZ-002", text)

    def test_no_automatic_reauthorization_on_mismatch(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_STATUS

        mock_authz, _ = self._run_handler(update, finder_side_effect=finder)
        mock_authz.assert_called_once()

    def test_unchanged_stability_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW)
        mock_mutator.assert_called_once()


class TestReversePaymentFreshReread(ReversePaymentMutationTestBase):
    def test_second_lookup_occurs_exactly_twice_total(self):
        update = _make_update()
        finder_calls = []

        def finder(transaction_id):
            finder_calls.append(transaction_id)
            return _CRP_ROW_CONFIRMED

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(len(finder_calls), 2)

    def test_business_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW_CONFIRMED if calls["n"] == 1 else {**_CRP_ROW_CONFIRMED, "Business ID": "BIZ-002"}

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_obligation_id_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW_CONFIRMED if calls["n"] == 1 else {**_CRP_ROW_CONFIRMED, "Payment Obligation ID": "POB-002"}

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_status_changed_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW_CONFIRMED if calls["n"] == 1 else _CRP_ROW

        _, mock_mutator = self._run_handler(update, finder_side_effect=finder)
        mock_mutator.assert_not_called()

    def test_second_row_disappeared_ownership_changed_message(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW_CONFIRMED if calls["n"] == 1 else None

        self._run_handler(update, finder_side_effect=finder)
        self.assertEqual(self._sent_text(update), "Запись изменилась. Повтори команду ещё раз.")

    def test_unchanged_stability_mutation_permitted(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_mutator.assert_called_once()


class TestConfirmPaymentMutation(ConfirmPaymentMutationTestBase):
    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW)
        mock_mutator.assert_called_once_with("PTXN-001", "owner")

    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_payment_transaction_by_id":
                return _CRP_ROW
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None,
                    "paid_amount": "100.00", "remaining_amount": "900.00", "currency": "KZT"}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        self.assertIn("confirm_payment_transaction", seen_funcs)

    def test_no_retry_on_mutation_exception(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_CRP_ROW, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось подтвердить Payment.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_CRP_ROW, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("confirmpayment_cmd infrastructure failure")

    def test_mapper_reused_success(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return={
            "ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None,
            "paid_amount": "100.00", "remaining_amount": "900.00", "currency": "KZT",
        })
        self.assertIn("✅", self._sent_text(update))

    def test_mapper_reused_unchanged(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return={
            "ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_invalid_transition_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Подтверждение возможно только из статуса pending.")

    def test_persistence_failure_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_PERSISTENCE_FAILED", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Не удалось подтвердить Payment.")

    def test_residual_toctou_not_found_after_authorization(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": "not found",
        })
        self.assertEqual(self._sent_text(update), "❌ Payment PTXN-001 не найден.")

    def test_malformed_wrapper_result_does_not_raise(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW, mutator_return="not a dict")
        self.assertEqual(self._sent_text(update), "❌ Не удалось подтвердить Payment.")


class TestReversePaymentMutation(ReversePaymentMutationTestBase):
    def test_mutation_called_exactly_once(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_mutator.assert_called_once()

    def test_mutation_called_with_exact_args(self):
        update = _make_update()
        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED)
        mock_mutator.assert_called_once_with("PTXN-001", "refund", "owner")

    def test_mutation_runs_via_asyncio_to_thread(self):
        update = _make_update()
        seen_funcs = []

        async def spy_to_thread(func, *args, **kwargs):
            seen_funcs.append(getattr(func, "__name__", None))
            if getattr(func, "__name__", None) == "find_payment_transaction_by_id":
                return _CRP_ROW_CONFIRMED
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None,
                    "paid_amount": "0.00", "remaining_amount": "1000.00", "currency": "KZT"}

        with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        self.assertIn("reverse_payment_transaction", seen_funcs)

    def test_no_retry_on_mutation_exception(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        _, mock_mutator = self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_side_effect=boom)
        mock_mutator.assert_called_once()

    def test_mutation_exception_safe_generic_message(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_side_effect=boom)
        self.assertEqual(self._sent_text(update), "❌ Не удалось реверснуть Payment.")

    def test_mutation_exception_fixed_log_literal(self):
        update = _make_update()

        def boom(*_a, **_k):
            raise RuntimeError("write failed")

        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_side_effect=boom)
        mock_log_error.assert_called_once_with("reversepayment_cmd infrastructure failure")

    def test_mapper_reused_success(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None,
            "paid_amount": "0.00", "remaining_amount": "1000.00", "currency": "KZT",
        })
        self.assertIn("✅", self._sent_text(update))

    def test_mapper_reused_unchanged(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": True, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED", "error": None,
        })
        self.assertIn("изменений нет", self._sent_text(update))

    def test_invalid_transition_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": False, "changed": False, "code": "INVALID_PAYMENT_TRANSACTION_TRANSITION", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Реверс возможен только из статуса confirmed.")

    def test_reversal_reason_required_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Укажи reversal_reason и reversed_by.")

    def test_persistence_failure_mapped(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_PERSISTENCE_FAILED", "error": "x",
        })
        self.assertEqual(self._sent_text(update), "❌ Не удалось реверснуть Payment.")

    def test_residual_toctou_not_found_after_authorization(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return={
            "ok": False, "changed": False, "code": "PAYMENT_TRANSACTION_NOT_FOUND", "error": "not found",
        })
        self.assertEqual(self._sent_text(update), "❌ Payment PTXN-001 не найден.")

    def test_malformed_wrapper_result_does_not_raise(self):
        update = _make_update()
        self._run_handler(update, finder_return=_CRP_ROW_CONFIRMED, mutator_return="not a dict")
        self.assertEqual(self._sent_text(update), "❌ Не удалось реверснуть Payment.")


class TestConfirmReversePaymentIsolation(unittest.TestCase):
    def test_failpayment_cmd_unchanged_source(self):
        # Byte-identity to the deployed B1 baseline is enforced
        # elsewhere via git-diff guards; here we just prove B2 didn't
        # add authorization plumbing shared incorrectly.
        src = inspect.getsource(th.failpayment_cmd)
        self.assertNotIn("confirm_payment_transaction", src)
        self.assertNotIn("reverse_payment_transaction", src)

    def test_confirmpayment_does_not_call_reverse_or_fail(self):
        tree = ast.parse(inspect.getsource(th.confirmpayment_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("reverse_payment_transaction", "fail_payment_transaction"):
            self.assertNotIn(forbidden, referenced_names)

    def test_reversepayment_does_not_call_confirm_or_fail(self):
        tree = ast.parse(inspect.getsource(th.reversepayment_cmd))
        referenced_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("confirm_payment_transaction", "fail_payment_transaction"):
            self.assertNotIn(forbidden, referenced_names)

    def test_confirmpayment_no_direct_sheets_write(self):
        src = inspect.getsource(th.confirmpayment_cmd)
        for forbidden in ("get_business_sheet(", "update_cell(", "find_row_by_id("):
            self.assertNotIn(forbidden, src)

    def test_reversepayment_no_direct_sheets_write(self):
        src = inspect.getsource(th.reversepayment_cmd)
        for forbidden in ("get_business_sheet(", "update_cell(", "find_row_by_id("):
            self.assertNotIn(forbidden, src)

    def test_confirmpayment_no_cache(self):
        src = inspect.getsource(th.confirmpayment_cmd)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)

    def test_reversepayment_no_cache(self):
        src = inspect.getsource(th.reversepayment_cmd)
        for forbidden in ("lru_cache", "cache_clear", "_CACHE", "TTLCache"):
            self.assertNotIn(forbidden, src)

    def test_confirmpayment_no_object_registry_lookup(self):
        src = inspect.getsource(th.confirmpayment_cmd)
        self.assertNotIn("object_registry", src.lower())

    def test_reversepayment_no_object_registry_lookup(self):
        src = inspect.getsource(th.reversepayment_cmd)
        self.assertNotIn("object_registry", src.lower())


class TestConfirmReversePaymentArchitecture(unittest.TestCase):
    def test_enforcement_map_has_exactly_fourteen_entries(self):
        self.assertEqual(len(th.COMMAND_ENFORCEMENT_MAP), 15)

    def test_confirmpayment_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["confirmpayment"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "requires_fresh_reread": True,
            "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_reversepayment_metadata_exact(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["reversepayment"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "requires_fresh_reread": True,
            "mutation_side_effect_class": "MULTI_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_failpayment_metadata_unchanged(self):
        self.assertEqual(th.COMMAND_ENFORCEMENT_MAP["failpayment"], {
            "resource": "FINANCE", "action": "UPDATE", "target_shape": "BUSINESS",
            "operation_kind": "MUTATION", "requires_fresh_reread": True,
            "mutation_side_effect_class": "SINGLE_ROW_MUTATION", "idempotency_class": "IDEMPOTENT",
        })

    def test_registration_lines_registered_once(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count('CommandHandler("confirmpayment",'), 1)
        self.assertEqual(content.count('CommandHandler("reversepayment",'), 1)

    def test_confirmpayment_mutation_exactly_once_on_authorized_stable_path(self):
        update = _make_update()
        real_mutate_marker = []

        async def spy_to_thread(func, *args, **kwargs):
            if getattr(func, "__name__", None) == "confirm_payment_transaction":
                real_mutate_marker.append(1)
            if getattr(func, "__name__", None) == "find_payment_transaction_by_id":
                return _CRP_ROW
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_CONFIRMED", "error": None,
                    "paid_amount": "1.00", "remaining_amount": "1.00", "currency": "KZT"}

        with patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        self.assertEqual(len(real_mutate_marker), 1)

    def test_reversepayment_mutation_exactly_once_on_authorized_stable_path(self):
        update = _make_update()
        real_mutate_marker = []

        async def spy_to_thread(func, *args, **kwargs):
            if getattr(func, "__name__", None) == "reverse_payment_transaction":
                real_mutate_marker.append(1)
            if getattr(func, "__name__", None) == "find_payment_transaction_by_id":
                return _CRP_ROW_CONFIRMED
            return {"ok": True, "changed": True, "code": "PAYMENT_TRANSACTION_REVERSED", "error": None,
                    "paid_amount": "0.00", "remaining_amount": "1.00", "currency": "KZT"}

        with patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=spy_to_thread), \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        self.assertEqual(len(real_mutate_marker), 1)

    def test_confirmpayment_unauthorized_path_zero_mutation(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH, return_value=_CRP_ROW), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_deny_result())), \
             patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_mutator.assert_not_called()

    def test_reversepayment_unauthorized_path_zero_mutation(self):
        update = _make_update()
        with patch(_CRP_FINDER_PATH, return_value=_CRP_ROW_CONFIRMED), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_deny_result())), \
             patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_mutator.assert_not_called()

    def test_confirmpayment_unstable_path_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW if calls["n"] == 1 else _CRP_ROW_OTHER_STATUS

        with patch(_CRP_FINDER_PATH, side_effect=finder), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch(_CONFIRM_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.confirmpayment_cmd(update, _make_context(_CONFIRM_ARGS)))
        mock_mutator.assert_not_called()

    def test_reversepayment_unstable_path_zero_mutation(self):
        update = _make_update()
        calls = {"n": 0}

        def finder(*_a, **_k):
            calls["n"] += 1
            return _CRP_ROW_CONFIRMED if calls["n"] == 1 else _CRP_ROW

        with patch(_CRP_FINDER_PATH, side_effect=finder), \
             patch(_AUTHZ_PATH, new=AsyncMock(return_value=_allow_result())), \
             patch(_REVERSE_MUTATOR_PATH) as mock_mutator, \
             patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            _run(th.reversepayment_cmd(update, _make_context(_REVERSE_ARGS)))
        mock_mutator.assert_not_called()


class TestConfirmReversePaymentExceptionSecrecy(ConfirmPaymentMutationTestBase):
    def test_confirm_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                finder_return={**_CRP_ROW, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_crp_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
                self.assertNotIn(_SECRET_BIZ_MARKER, text)

    def test_confirm_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            finder_return={**_CRP_ROW, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_crp_boom_with_secrets,
        )
        text = self._sent_text(update)
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)

    def test_confirm_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(update, finder_side_effect=_crp_boom_with_secrets)
        text = self._sent_text(update)
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_confirm_authorization_denial_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, finder_return={**_CRP_ROW, "Business ID": _SECRET_BIZ_MARKER}, authz_result=_deny_result(),
        )
        text = self._sent_text(update)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)


class TestReversePaymentExceptionSecrecy(ReversePaymentMutationTestBase):
    def test_reverse_mutation_exception_no_secrets_in_log_call_args(self):
        update = _make_update()
        with patch("business_core.telegram_handlers.log.error") as mock_log_error:
            self._run_handler(
                update,
                finder_return={**_CRP_ROW_CONFIRMED, "Business ID": _SECRET_BIZ_MARKER},
                mutator_side_effect=_crp_boom_with_secrets,
            )
        mock_log_error.assert_called_once()
        for call in mock_log_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
                self.assertNotIn(_SECRET_BIZ_MARKER, text)

    def test_reverse_mutation_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update,
            finder_return={**_CRP_ROW_CONFIRMED, "Business ID": _SECRET_BIZ_MARKER},
            mutator_side_effect=_crp_boom_with_secrets,
        )
        text = self._sent_text(update)
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)

    def test_reverse_first_lookup_exception_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(update, finder_side_effect=_crp_boom_with_secrets)
        text = self._sent_text(update)
        self.assertNotIn(_CRP_SECRET_ROW_MARKER, text)
        self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_reverse_authorization_denial_no_secrets_in_reply(self):
        update = _make_update()
        self._run_handler(
            update, finder_return={**_CRP_ROW_CONFIRMED, "Business ID": _SECRET_BIZ_MARKER}, authz_result=_deny_result(),
        )
        text = self._sent_text(update)
        self.assertNotIn(_SECRET_BIZ_MARKER, text)


if __name__ == "__main__":
    unittest.main()
