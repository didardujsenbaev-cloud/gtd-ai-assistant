"""
Tests for Phase 23D-2 — /newclient refactored onto
business_core.person_manager.create_person()/update_person().

Phase 31D update: newclient_confirm() now calls person_manager.
resolve_person_identity() directly (ADR-015 Decision 2) instead of the
business_builder.find_existing_person() compatibility wrapper, and
routes Drive orchestration through business_builder.
provision_client_drive_safe() (a single retry-safe decision point,
ADR-015 Decisions 14/15) instead of calling provision_client_drive()
and update_person_drive_info() separately. Every test below is mocked
at these NEW call points — provision_client_drive_safe() is mocked
wholesale so no test ever triggers its internal (real)
person_manager.find_person_by_id() call, which would otherwise hit
live Google Sheets.

Covers exactly the scenarios required by the approved Phase 23D-2 plan:
create_person success, create_person failure, update_person partial
failure, Drive failure after successful creation, unchanged SAME_BIZ/
OTHER_BIZ behavior, no duplicate Person creation (resolve_person_identity
remains the sole dedup decision-maker), exact preservation of
Бизнесы/Уровень доверия/Теплота, "Бизнесы" now accepted by
update_person()'s editable-field whitelist, and profile_fields_warning
safely initialized on every branch.

No live Sheets writes — mocks only, per ENGINEERING_STANDARDS.md
Testing Standards.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_th():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.telegram_handlers")


def _fresh_pm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.person_manager")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _identity_result_from_legacy(existing: dict | None, biz_id_resolved: str = "BIZ-001") -> dict:
    """Phase 31D: newclient_confirm() now calls person_manager.
    resolve_person_identity() directly instead of business_builder.
    find_existing_person() — converts the old find_existing_person()
    fixture shape into the canonical resolve_person_identity() result
    shape. same_biz is re-derived by newclient_confirm() itself via
    has_person_business_link(), so when the fixture doesn't specify
    "biz_ids" explicitly, this reconstructs a biz_ids list that
    reproduces the same same_biz outcome the fixture's "same_biz" flag
    originally encoded."""
    if existing is None:
        return {"status": "not_found", "person": None, "matches": [], "matched_by": [], "error": None}
    biz_ids = existing.get("biz_ids")
    if biz_ids is None:
        same_biz_flag = existing.get("same_biz", True)
        biz_ids = [biz_id_resolved] if (same_biz_flag and biz_id_resolved) else []
    person = {
        "person_id": existing["prs_id"],
        "full_name": existing.get("full_name", "Иван Иванов"),
        "biz_ids": biz_ids,
        "primary_biz_id": existing.get("primary_biz_id", ""),
        "google_drive": existing.get("drive_url", ""),
        "drive_folder_id": existing.get("drive_folder_id", ""),
        "phone": existing.get("phone_raw", ""),
        "row_num": existing.get("row_num", 2),
    }
    return {"status": "single_match", "person": person, "matches": [person], "matched_by": ["phone"], "error": None}


_DRIVE_NOT_CONFIGURED = {
    "ok": False, "drive_created": False, "drive_reused": False, "partial_failure": False,
    "folder_id": None, "folder_url": None, "warning": None, "error": "не задан",
}


def _drive_created(folder_id: str, folder_url: str) -> dict:
    return {
        "ok": True, "drive_created": True, "drive_reused": False, "partial_failure": False,
        "folder_id": folder_id, "folder_url": folder_url, "warning": None, "error": None,
    }


def _drive_reused(folder_id: str, folder_url: str) -> dict:
    return {
        "ok": True, "drive_created": False, "drive_reused": True, "partial_failure": False,
        "folder_id": folder_id, "folder_url": folder_url, "warning": None, "error": None,
    }


def _make_confirm_update(text="✅ Сохранить"):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_confirm_context(full_name="Иван Иванов", phone="+77771234567",
                           businesses="ТестБизнес", person_type="клиент",
                           biz_id_resolved="BIZ-001"):
    context = MagicMock()
    snapshot = {
        "full_name": full_name, "phone": phone, "businesses": businesses,
        "person_type": person_type, "biz_id_resolved": biz_id_resolved,
    }
    context.user_data = {"nc": dict(snapshot), "nc_confirmed_snapshot": dict(snapshot)}
    return context


# ─────────────────────────────────────────────────────────────
# 1. create_person success
# ─────────────────────────────────────────────────────────────

class TestCreatePersonSuccess(unittest.TestCase):

    def test_status_new_success_produces_standard_reply(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        async def run():
            with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
                 patch("business_core.person_manager.create_person",
                       return_value={"ok": True, "person_id": "PRS-100", "error": None}), \
                 patch("business_core.person_manager.update_person",
                       return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}), \
                 patch("business_core.business_builder.provision_client_drive_safe",
                       return_value=_DRIVE_NOT_CONFIGURED):
                await th.newclient_confirm(update, context)

        _run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Клиент добавлен!", msg)
        self.assertIn("PRS-100", msg)
        self.assertNotIn("⚠️", msg)


# ─────────────────────────────────────────────────────────────
# 2. create_person failure
# ─────────────────────────────────────────────────────────────

class TestCreatePersonFailure(unittest.TestCase):

    def test_create_person_failure_preserves_error_ux(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": False, "person_id": "", "error": "Business 'BIZ-001' не найден"}), \
             patch("business_core.person_manager.update_person") as mock_update, \
             patch("business_core.business_builder.provision_client_drive_safe") as mock_drive, \
             patch("business_core.inbox_bridge.invalidate_cache") as mock_cache:
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌ Ошибка сохранения:", msg)
        self.assertIn("Business 'BIZ-001' не найден", msg)
        mock_update.assert_not_called()
        mock_drive.assert_not_called()
        mock_cache.assert_not_called()

    def test_create_person_failure_clears_state(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": False, "person_id": "", "error": "boom"}):
            _run(th.newclient_confirm(update, context))

        self.assertNotIn("nc", context.user_data)
        self.assertNotIn("nc_confirmed_snapshot", context.user_data)


# ─────────────────────────────────────────────────────────────
# 3. update_person partial failure
# ─────────────────────────────────────────────────────────────

class TestUpdatePersonPartialFailure(unittest.TestCase):

    def test_partial_success_message_and_continued_flow(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-101", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": False, "changed": False, "updated_fields": (),
                                 "error": "Sheets API timeout"}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED) as mock_drive, \
             patch("business_core.inbox_bridge.invalidate_cache") as mock_cache:
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        # Success header still present — Person WAS created, never claimed otherwise.
        self.assertIn("✅ Клиент добавлен!", msg)
        self.assertIn("PRS-101", msg)
        # Partial-success warning present, phrased as "some", never "none".
        self.assertIn("⚠️", msg)
        self.assertIn("Некоторые", msg)
        self.assertNotIn("Ошибка сохранения", msg)
        # Drive provisioning and cache invalidation still proceed.
        mock_drive.assert_called_once()
        mock_cache.assert_called_once()

    def test_partial_failure_logs_person_id_operation_error_and_fields(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-102", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": False, "changed": False, "updated_fields": (),
                                 "error": "Sheets API timeout"}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED), \
             patch("business_core.telegram_handlers.log") as mock_log:
            _run(th.newclient_confirm(update, context))

        warning_calls = [c.args[0] for c in mock_log.warning.call_args_list]
        combined = " ".join(warning_calls)
        self.assertIn("PRS-102", combined)
        self.assertIn("update_person", combined)
        self.assertIn("Sheets API timeout", combined)
        self.assertIn("Бизнесы", combined)
        self.assertIn("Уровень доверия", combined)
        self.assertIn("Теплота", combined)

    def test_partial_failure_does_not_claim_no_fields_saved(self):
        """The warning wording must say 'some' fields may not have
        saved, never imply none were saved (update_person() writes
        each field with its own update_cell() call — a failure can be
        genuinely partial at the field level)."""
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-103", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": False, "changed": False, "updated_fields": (),
                                 "error": "boom"}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("не сохранены", msg)  # must not claim NONE were saved
        self.assertIn("могли сохраниться не полностью", msg)


# ─────────────────────────────────────────────────────────────
# 4. Drive failure after successful creation
# ─────────────────────────────────────────────────────────────

class TestDriveFailureAfterSuccessfulCreation(unittest.TestCase):

    def test_drive_exception_does_not_affect_success_reply(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-104", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   side_effect=RuntimeError("drive down")):
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Клиент добавлен!", msg)
        self.assertIn("PRS-104", msg)
        self.assertNotIn("Ошибка сохранения", msg)


# ─────────────────────────────────────────────────────────────
# 5/6. SAME_BIZ / OTHER_BIZ unchanged, 7. no duplicate creation
# ─────────────────────────────────────────────────────────────

class TestExistingBranchesUnchangedNoDuplicateCreation(unittest.TestCase):

    def test_same_biz_never_calls_create_or_update_person(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(
                       {"prs_id": "PRS-001", "same_biz": True, "drive_url": ""})), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "changed": False, "already_client": True,
                                 "manual_decision_required": False, "warning": None, "error": None}), \
             patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update, \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("уже существует", msg)

    def test_other_biz_never_calls_create_or_update_person(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(
                       {"prs_id": "PRS-002", "same_biz": False, "drive_url": ""})), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "changed": False, "already_client": True,
                                 "manual_decision_required": False, "warning": None, "error": None}), \
             patch("business_core.person_manager.append_person_biz_id") as mock_add_biz, \
             patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update, \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_add_biz.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("другом бизнесе", msg)


# ─────────────────────────────────────────────────────────────
# 8. Exact preservation of Бизнесы / Уровень доверия / Теплота
# ─────────────────────────────────────────────────────────────

class TestProfileFieldPreservation(unittest.TestCase):

    def test_update_person_called_with_exact_client_defaults(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context(businesses="Узаконение недвижимости")

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-105", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}) as mock_update, \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        mock_update.assert_called_once_with("PRS-105", {
            "Бизнесы": "Узаконение недвижимости",
            "Уровень доверия": "средний",
            "Теплота": "тёплый",
        })


# ─────────────────────────────────────────────────────────────
# 9. "Бизнесы" accepted by update_person()
# ─────────────────────────────────────────────────────────────

class TestBiznesyEditableField(unittest.TestCase):

    def test_biznesy_in_editable_fields_whitelist(self):
        pm = _fresh_pm()
        self.assertIn("Бизнесы", pm._PERSON_EDITABLE_FIELDS)

    def test_update_person_accepts_biznesy(self):
        pm = _fresh_pm()
        result = pm.update_person("", {"Бизнесы": "X"})
        # Empty person_id is rejected for a DIFFERENT reason (no ID) —
        # the important thing is it's not rejected as an unknown field.
        self.assertNotIn("Недопустимые поля", result["error"] or "")


# ─────────────────────────────────────────────────────────────
# 10. profile_fields_warning safely initialized for every branch
# ─────────────────────────────────────────────────────────────

class TestProfileFieldsWarningInitialization(unittest.TestCase):

    def test_same_biz_branch_does_not_raise_unbound_variable(self):
        """If profile_fields_warning were not initialized before the
        branching, STATUS_SAME_BIZ would raise UnboundLocalError when
        the reply-construction step reads it. Reaching a normal reply
        (not an exception swallowed into '❌ Ошибка сохранения') proves
        it's safely bound."""
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(
                       {"prs_id": "PRS-001", "same_biz": True, "drive_url": ""})), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "changed": False, "already_client": True,
                                 "manual_decision_required": False, "warning": None, "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("UnboundLocalError", msg)
        self.assertIn("уже существует", msg)

    def test_other_biz_branch_does_not_raise_unbound_variable(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(
                       {"prs_id": "PRS-002", "same_biz": False, "drive_url": ""})), \
             patch("business_core.person_manager.append_person_biz_id"), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "changed": False, "already_client": True,
                                 "manual_decision_required": False, "warning": None, "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_DRIVE_NOT_CONFIGURED):
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertNotIn("UnboundLocalError", msg)
        self.assertIn("другом бизнесе", msg)


# ─────────────────────────────────────────────────────────────
# Phase 31D — Drive orchestration routes through the single retry-safe
# provision_client_drive_safe() decision point (ADR-015 Decisions 14/15)
# instead of provision_client_drive() + update_person_drive_info()
# called separately from newclient_confirm() itself.
# ─────────────────────────────────────────────────────────────

class TestStatusNewDriveUsesPersonManager(unittest.TestCase):

    def test_status_new_drive_calls_provision_client_drive_safe_with_correct_args(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-105", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_drive_created("fid-105", "https://drive.google.com/fid-105")) as mock_drive:
            _run(th.newclient_confirm(update, context))

        mock_drive.assert_called_once_with(
            person_id="PRS-105", full_name="Иван Иванов", biz_name="ТестБизнес",
        )

    def test_status_new_drive_success_reply_unchanged(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity", return_value=_identity_result_from_legacy(None)), \
             patch("business_core.person_manager.create_person",
                   return_value={"ok": True, "person_id": "PRS-107", "error": None}), \
             patch("business_core.person_manager.update_person",
                   return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_drive_created("fid-107", "https://drive.google.com/fid-107")):
            _run(th.newclient_confirm(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Клиент добавлен!", msg)
        self.assertIn("PRS-107", msg)
        self.assertIn("📁 Drive: https://drive.google.com/fid-107", msg)

    def test_other_biz_drive_path_reuses_existing_reference(self):
        """Existing-person (OTHER_BIZ) Drive path — reuses via
        provision_client_drive_safe()'s own reuse decision, and shows
        the multi-business "shared folder" warning (ADR-015
        Decision 14) since this is OTHER_BIZ with an existing reference."""
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        with patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(
                       {"prs_id": "PRS-002", "same_biz": False, "drive_url": "https://drive.google.com/fid-existing"})), \
             patch("business_core.person_manager.append_person_biz_id"), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "changed": False, "already_client": True,
                                 "manual_decision_required": False, "warning": None, "error": None}), \
             patch("business_core.business_builder.provision_client_drive_safe",
                   return_value=_drive_reused("fid-existing", "https://drive.google.com/fid-existing")) as mock_drive:
            _run(th.newclient_confirm(update, context))

        mock_drive.assert_called_once_with(
            person_id="PRS-002", full_name="Иван Иванов", biz_name="ТестБизнес",
        )
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("📁 Drive: https://drive.google.com/fid-existing", msg)
        self.assertIn("уже существует общая папка", msg)


class TestNewClientConfirmNoDirectRegistryWrite(unittest.TestCase):
    """Architecture guard: newclient_confirm() must contain no raw
    update_business_cell()/update_cell()/get_business_sheet()-for-write/
    save_client_drive_to_sheets() call — only the Person Manager-backed
    wrappers (create_person, update_person, append_person_biz_id via
    person_manager, provision_client_drive_safe)."""

    def test_no_direct_registry_write_calls_remain(self):
        import ast
        import inspect
        from business_core.telegram_handlers import newclient_confirm

        source = inspect.getsource(newclient_confirm)
        tree = ast.parse(source)

        forbidden_calls = {"update_business_cell", "update_cell", "save_client_drive_to_sheets"}
        found_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in forbidden_calls:
                    found_calls.add(name)

        self.assertEqual(found_calls, set())

    def test_save_client_drive_to_sheets_not_imported(self):
        import inspect
        from business_core.telegram_handlers import newclient_confirm

        source = inspect.getsource(newclient_confirm)
        self.assertNotIn("save_client_drive_to_sheets", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
