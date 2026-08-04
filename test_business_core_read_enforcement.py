"""
Phase 17E-1: per-command targeted-read enforcement tests for the six
selected commands: /doc, /obligation, /payment, /offer, /lead,
/interaction.

Registered in conftest.py's hard socket-block set BEFORE this test
logic was written, per the PRS-003/Phase-17B-IR1 precedent.

All finder functions are patched at the exact module path each
handler imports them from at call time (a fresh, local `from ... import
...` inside the function body, matching this repo's established lazy-
import convention) — safe under the sys.modules-purge adversarial
pattern this repo tests for. The Telegram authorization adapter is
patched via "business_core.telegram_authorization.authorize_telegram_business_core_request",
the exact name _authorize_or_reply imports locally at call time.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from business_core import telegram_handlers as th


def _run(coro):
    return asyncio.run(coro)


def _make_update(chat_type="private", user_id=570004109, args=None):
    update = MagicMock()
    update.effective_chat = SimpleNamespace(type=chat_type) if chat_type is not None else None
    update.effective_user = SimpleNamespace(id=user_id) if user_id is not None else None
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args):
    return SimpleNamespace(args=args)


def _allow_result(business_id="", object_id=""):
    return {"ok": True, "allowed": True, "code": "TELEGRAM_ACCESS_ALLOWED", "retry_safe": True,
            "authorization_result": {"ok": True, "allowed": True, "code": "ACCESS_ALLOWED"}}


def _deny_result():
    return {"ok": True, "allowed": False, "code": "AUTHORIZATION_DENIED", "retry_safe": True,
            "authorization_result": {"ok": True, "allowed": False, "code": "SCOPE_NOT_MATCHED"}}


def _infra_failure_result():
    return {"ok": False, "allowed": False, "code": "AUTHORIZATION_UNAVAILABLE", "retry_safe": False,
            "authorization_result": None}


# ─────────────────────────────────────────────────────────────
# Per-command configuration — one entry per enforced command
# ─────────────────────────────────────────────────────────────

_COMMANDS = {
    "doc": {
        "handler": th.doc_cmd,
        "finder_path": "business_core.document_manager.find_document_by_id",
        "id_arg": "document_id",
        "id_value": "DREG-001",
        "resource": "DOCUMENT",
        "row": {
            "document_id": "DREG-001", "document_family_id": "DFAM-1", "version": "1",
            "business_id": "BIZ-001", "client_id": "PRS-1", "object_id": "OBJ-001",
            "roadmap_id": "", "stage_id": "", "document_template_id": "",
            "document_name": "Test Doc", "status": "uploaded",
            "drive_file_id": "", "drive_file_url": "", "file_name": "a.pdf", "mime_type": "application/pdf",
            "uploaded_at": "", "uploaded_by": "",
        },
        "row_missing_ownership": {**{k: "" for k in ["business_id", "object_id"]}, "document_id": "DREG-001"},
        "extra_mocks": {},
    },
    "obligation": {
        "handler": th.obligation_cmd,
        "finder_path": "business_core.payment_manager.find_payment_obligation_by_id",
        "id_arg": "payment_obligation_id",
        "id_value": "POB-001",
        "resource": "FINANCE",
        "row": {
            "Payment Obligation ID": "POB-001", "Business ID": "BIZ-001", "Client ID": "PRS-1",
            "Title Snapshot": "T", "Obligation Amount": "100", "Currency": "RUB",
            "Paid Amount": "0", "Remaining Amount": "100", "Status": "pending",
            "Due Date": "", "Roadmap ID": "", "Stage ID": "", "Commercial Milestone Template ID": "",
        },
        "row_missing_ownership": {"Payment Obligation ID": "POB-001", "Business ID": ""},
        "extra_mocks": {"business_core.payment_manager.list_payment_transactions": []},
    },
    "payment": {
        "handler": th.payment_cmd,
        "finder_path": "business_core.payment_manager.find_payment_transaction_by_id",
        "id_arg": "payment_transaction_id",
        "id_value": "PTXN-001",
        "resource": "FINANCE",
        "row": {
            "Payment Transaction ID": "PTXN-001", "Business ID": "BIZ-001",
            "Payment Obligation ID": "POB-001", "Client ID": "PRS-1",
            "Amount": "100", "Currency": "RUB", "Payment Date": "2026-01-01", "Status": "confirmed",
        },
        "row_missing_ownership": {"Payment Transaction ID": "PTXN-001", "Business ID": ""},
        "extra_mocks": {},
    },
    "offer": {
        "handler": th.offer_cmd,
        "finder_path": "business_core.offer_manager.find_commercial_offer_by_id",
        "id_arg": "commercial_offer_id",
        "id_value": "OFR-001",
        "resource": "FINANCE",
        "row": {
            "Commercial Offer ID": "OFR-001", "Offer Series ID": "OFS-1", "Previous Commercial Offer ID": "",
            "Version Number": "1", "Business ID": "BIZ-001", "Client ID": "PRS-1",
            "Scope Snapshot": "scope", "Title Snapshot": "T",
            "Quoted Amount": "100", "Currency": "RUB", "Valid Until": "2099-01-01", "Status": "draft",
        },
        "row_missing_ownership": {"Commercial Offer ID": "OFR-001", "Business ID": ""},
        "extra_mocks": {
            "business_core.offer_manager.list_commercial_offers_by_series": [],
            "business_core.business_builder.is_commercial_offer_effectively_expired": False,
        },
    },
    "lead": {
        "handler": th.lead_cmd,
        "finder_path": "business_core.lead_manager.find_lead_by_id",
        "id_arg": "lead_id",
        "id_value": "LED-001",
        "resource": "FINANCE",
        "row": {
            "Lead ID": "LED-001", "Business ID": "BIZ-001",
            "Contact Name Snapshot": "Ivan I.", "Status": "new",
        },
        "row_missing_ownership": {"Lead ID": "LED-001", "Business ID": ""},
        "extra_mocks": {},
    },
    "interaction": {
        "handler": th.interaction_cmd,
        "finder_path": "business_core.interaction_manager.find_interaction_by_id",
        "id_arg": "interaction_id",
        "id_value": "ACT-001",
        "resource": "CLIENT",
        "row": {
            "Interaction ID": "ACT-001", "Business ID": "BIZ-001",
            "Interaction Type": "call", "Lead ID": "", "Client ID": "PRS-1",
        },
        "row_missing_ownership": {"Interaction ID": "ACT-001", "Business ID": ""},
        "extra_mocks": {},
    },
}


class EnforcementTestBase(unittest.TestCase):
    def _extra_mock_patches(self, cfg):
        return [patch(path, return_value=val) if not callable(val) or isinstance(val, bool)
                else patch(path, return_value=val) for path, val in cfg["extra_mocks"].items()]

    def _run_handler(self, cfg, update, args, finder_side_effect=None, finder_return=None, authz_result=None):
        patches = []
        if finder_side_effect is not None:
            patches.append(patch(cfg["finder_path"], side_effect=finder_side_effect))
        else:
            patches.append(patch(cfg["finder_path"], return_value=finder_return))
        mock_authz = AsyncMock(return_value=authz_result if authz_result is not None else _allow_result())
        patches.append(patch("business_core.telegram_authorization.authorize_telegram_business_core_request", new=mock_authz))
        for path, val in cfg["extra_mocks"].items():
            patches.append(patch(path, return_value=val))

        ctx = _make_context(args)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            for p in patches:
                p.start()
            try:
                _run(cfg["handler"](update, ctx))
            finally:
                for p in reversed(patches):
                    p.stop()
        return mock_authz


class TestTransportFirstOrdering(EnforcementTestBase):
    def test_group_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update(chat_type="group")
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()

    def test_supergroup_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update(chat_type="supergroup")
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()

    def test_channel_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update(chat_type="channel")
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()

    def test_malformed_update_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = SimpleNamespace()  # no effective_chat / effective_user / message
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()

    def test_missing_effective_user_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update(user_id=None)
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()

    def test_missing_user_id_zero_finder_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                update.effective_user = SimpleNamespace(id=None)
                with patch(cfg["finder_path"]) as mock_finder, \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                mock_finder.assert_not_called()


class TestLookupAndThreadOffload(EnforcementTestBase):
    def test_valid_private_request_finder_called_once(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                mock_authz = self._run_handler(
                    cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"],
                )
                mock_authz.assert_called_once()

    def test_finder_runs_via_asyncio_to_thread(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                recorded = {}

                async def fake_to_thread(func, *args, **kwargs):
                    recorded["func_name"] = getattr(func, "__name__", None)
                    recorded["args"] = args
                    return cfg["row"]

                extra_patches = [patch(p, return_value=v) for p, v in cfg["extra_mocks"].items()]
                with patch("business_core.telegram_handlers.asyncio.to_thread", side_effect=fake_to_thread), \
                     patch("business_core.telegram_authorization.authorize_telegram_business_core_request",
                           new=AsyncMock(return_value=_allow_result())), \
                     patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                    for p in extra_patches:
                        p.start()
                    try:
                        _run(cfg["handler"](update, _make_context([f"{cfg['id_arg']}={cfg['id_value']}"])))
                    finally:
                        for p in extra_patches:
                            p.stop()
                self.assertIn(cfg["id_value"], recorded.get("args", ()))

    def test_finder_none_zero_authorization_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                mock_authz = self._run_handler(
                    cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=None,
                )
                mock_authz.assert_not_called()

    def test_finder_exception_zero_authorization_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()

                def boom(*_a, **_k):
                    raise RuntimeError("sheets down")

                mock_authz = self._run_handler(
                    cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_side_effect=boom,
                )
                mock_authz.assert_not_called()

    def test_finder_exception_temporarily_unavailable_message(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()

                def boom(*_a, **_k):
                    raise RuntimeError("sheets down")

                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_side_effect=boom)
                text = update.message.reply_text.call_args[0][0]
                self.assertIn("Временная ошибка", text)
                self.assertNotIn("RuntimeError", text)
                self.assertNotIn("sheets down", text)

    def test_missing_ownership_field_zero_authorization_calls(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                mock_authz = self._run_handler(
                    cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row_missing_ownership"],
                )
                mock_authz.assert_not_called()

    def test_missing_ownership_field_generic_message(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row_missing_ownership"])
                text = update.message.reply_text.call_args[0][0]
                self.assertEqual(text, "Запись недоступна или не найдена.")


class TestAuthorizationCorrectness(EnforcementTestBase):
    def test_correct_resource_action_forwarded(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                mock_authz = self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"])
                _, kwargs = mock_authz.call_args
                self.assertEqual(kwargs["resource"], cfg["resource"])
                self.assertEqual(kwargs["action"], "READ")

    def test_ownership_comes_from_stored_row_not_caller(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                # extra, irrelevant caller-supplied business_id token — must be ignored
                args = [f"{cfg['id_arg']}={cfg['id_value']}", "business_id=SPOOFED-BIZ"]
                mock_authz = self._run_handler(cfg, update, args, finder_return=cfg["row"])
                _, kwargs = mock_authz.call_args
                self.assertEqual(kwargs["business_id"], "BIZ-001")
                self.assertNotEqual(kwargs["business_id"], "SPOOFED-BIZ")

    def test_expected_denial_generic_text(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_deny_result())
                text = update.message.reply_text.call_args[0][0]
                self.assertEqual(text, "Запись недоступна или не найдена.")

    def test_infrastructure_failure_temporarily_unavailable(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_infra_failure_result())
                text = update.message.reply_text.call_args[0][0]
                self.assertEqual(text, "Временная ошибка проверки доступа. Попробуйте ещё раз позже.")

    def test_owner_allow_succeeds(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_allow_result())
                text = update.message.reply_text.call_args[0][0]
                self.assertNotEqual(text, "Запись недоступна или не найдена.")
                self.assertNotIn("Временная ошибка", text)


class TestRenderingAndAntiEnumeration(EnforcementTestBase):
    def test_zero_protected_fields_before_allow_on_denial(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_deny_result())
                # exactly one reply sent, and it is the generic text — no
                # earlier call could have leaked a protected field.
                self.assertEqual(update.message.reply_text.call_count, 1)
                text = update.message.reply_text.call_args[0][0]
                self.assertNotIn("BIZ-001", text)
                self.assertNotIn(cfg["id_value"], text)

    def test_not_found_and_denied_existing_byte_identical(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update_a = _make_update()
                self._run_handler(cfg, update_a, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=None)
                text_not_found = update_a.message.reply_text.call_args[0][0]

                update_b = _make_update()
                self._run_handler(cfg, update_b, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_deny_result())
                text_denied = update_b.message.reply_text.call_args[0][0]

                self.assertEqual(text_not_found, text_denied)

    def test_no_record_id_in_denial_text(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_deny_result())
                text = update.message.reply_text.call_args[0][0]
                self.assertNotIn(cfg["id_value"], text)

    def test_no_business_object_id_in_denial_text(self):
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                update = _make_update()
                self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=_deny_result())
                text = update.message.reply_text.call_args[0][0]
                self.assertNotIn("BIZ-001", text)
                self.assertNotIn("OBJ-001", text)


class TestNoWrites(EnforcementTestBase):
    def test_zero_write_helpers_called_across_all_paths(self):
        write_names = ("append_business_row", "update_business_row", "update_business_cell")
        for cmd, cfg in _COMMANDS.items():
            with self.subTest(command=cmd):
                mocks = {name: patch(f"business_core.sheets.{name}").start() for name in write_names}
                try:
                    for scenario in ("allow", "deny", "not_found"):
                        update = _make_update()
                        if scenario == "not_found":
                            self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=None)
                        else:
                            authz = _allow_result() if scenario == "allow" else _deny_result()
                            self._run_handler(cfg, update, [f"{cfg['id_arg']}={cfg['id_value']}"], finder_return=cfg["row"], authz_result=authz)
                    for name, mock_obj in mocks.items():
                        mock_obj.assert_not_called()
                finally:
                    patch.stopall()


if __name__ == "__main__":
    unittest.main()
