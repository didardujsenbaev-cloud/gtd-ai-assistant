"""
Phase 31D: behavioral tests for Client caller migration + cross-domain
validation (ADR-015). Covers what test_business_newclient_*.py and
test_object_caller_migration.py don't already exercise:

  - /newclient AMBIGUOUS / ARCHIVED_MATCH branches (zero writes)
  - /newclient manual_decision_required blocks Business-link/Drive
  - /newobject Client-role / Business-link / archived validation
  - provision_client_drive_safe() retry-safety (Part 9)

All Sheets/Drive access mocked — no live network.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_th():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.telegram_handlers")


def _fresh_bb():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.business_builder")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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


_DRIVE_NOT_CONFIGURED = {
    "ok": False, "drive_created": False, "drive_reused": False, "partial_failure": False,
    "folder_id": None, "folder_url": None, "warning": None, "error": "не задан",
}


# ─────────────────────────────────────────────────────────────
# /newclient — AMBIGUOUS / ARCHIVED_MATCH (Part 2, Part 12 items 6-7)
# ─────────────────────────────────────────────────────────────

class TestNewClientAmbiguousZeroWrites(unittest.TestCase):

    def test_ambiguous_performs_zero_writes(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        matches = [
            {"person_id": "PRS-010", "full_name": "Иван Иванов", "phone": "77771111111",
             "biz_ids": [], "primary_biz_id": "", "google_drive": "", "drive_folder_id": "", "row_num": 2},
            {"person_id": "PRS-011", "full_name": "Иван Иванов", "phone": "77772222222",
             "biz_ids": [], "primary_biz_id": "", "google_drive": "", "drive_folder_id": "", "row_num": 3},
        ]
        identity = {"status": "ambiguous", "person": None, "matches": matches, "matched_by": ["name"], "error": None}

        with patch("business_core.person_manager.resolve_person_identity", return_value=identity), \
             patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update, \
             patch("business_core.person_manager.append_person_biz_id") as mock_append, \
             patch("business_core.business_builder.provision_client_drive_safe") as mock_drive:
            _run(th.newclient_confirm(update, context))

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_append.assert_not_called()
        mock_drive.assert_not_called()

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("несколько похожих", msg)
        self.assertIn("PRS-010", msg)
        # Full phone must never appear — only masked.
        self.assertNotIn("77771111111", msg)

    def test_archived_match_performs_zero_writes(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()

        identity = {"status": "archived_match", "person": None, "matches": [], "matched_by": ["phone"], "error": None}

        with patch("business_core.person_manager.resolve_person_identity", return_value=identity), \
             patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update, \
             patch("business_core.person_manager.append_person_biz_id") as mock_append, \
             patch("business_core.business_builder.provision_client_drive_safe") as mock_drive:
            _run(th.newclient_confirm(update, context))

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        mock_append.assert_not_called()
        mock_drive.assert_not_called()

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("архивный", msg)


class TestNewClientManualRoleDecisionBlocks(unittest.TestCase):

    def test_manual_decision_required_blocks_business_link_and_drive(self):
        th = _fresh_th()
        update = _make_confirm_update()
        context = _make_confirm_context()  # person_type defaults to "клиент"

        person = {
            "person_id": "PRS-020", "full_name": "Иван Иванов", "phone": "77771234567",
            "biz_ids": [], "primary_biz_id": "", "google_drive": "", "drive_folder_id": "", "row_num": 2,
        }
        identity = {"status": "single_match", "person": person, "matches": [person],
                    "matched_by": ["phone"], "error": None}

        with patch("business_core.person_manager.resolve_person_identity", return_value=identity), \
             patch("business_core.person_manager.ensure_client_role",
                   return_value={"ok": True, "person_id": "PRS-020", "changed": False,
                                 "already_client": False, "manual_decision_required": True,
                                 "warning": "Тип='сотрудник' уже задан", "error": None}), \
             patch("business_core.person_manager.append_person_biz_id") as mock_append, \
             patch("business_core.business_builder.provision_client_drive_safe") as mock_drive:
            _run(th.newclient_confirm(update, context))

        mock_append.assert_not_called()
        mock_drive.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("сотрудник", msg)


# ─────────────────────────────────────────────────────────────
# /newobject — Client-role / Business-link / archived validation
# (Part 7, Part 12 items 30-38)
# ─────────────────────────────────────────────────────────────

def _make_newobject_update_context(args="biz_id=BIZ-001 client_id=PRS-001 city=Алматы address=\"ул. Тест 1\""):
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args.split()
    return update, context


class TestNewObjectClientValidationBehavior(unittest.TestCase):

    def _run_newobject(self, person, biz_row=("row", {}), create_result=None, drive_result=None):
        th = _fresh_th()
        update, context = _make_newobject_update_context()

        create_result = create_result or {
            "ok": True, "obj_id": "OBJ-900", "error": None,
            "object_created": True, "object_reused": False, "warnings": [],
        }
        drive_result = drive_result or {
            "ok": False, "folder_id": None, "folder_url": None, "error": None,
            "drive_created": False, "drive_reused": False, "partial_failure": False,
        }

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=biz_row), \
             patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch("business_core.business_builder.create_object_record", return_value=create_result) as mock_create, \
             patch("business_core.business_builder.provision_object_drive", return_value=drive_result) as mock_drive:
            _run(th.newobject_cmd(update, context))

        return update, mock_create, mock_drive

    def test_missing_person_blocked(self):
        update, mock_create, mock_drive = self._run_newobject(person=None)
        mock_create.assert_not_called()
        mock_drive.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", msg)

    def test_archived_person_blocked(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": "", "person_type": "клиент", "status": "archived"}
        update, mock_create, mock_drive = self._run_newobject(person=person)
        mock_create.assert_not_called()
        mock_drive.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("архиве", msg)

    def test_non_client_person_blocked(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": "", "person_type": "партнер", "status": "active"}
        update, mock_create, mock_drive = self._run_newobject(person=person)
        mock_create.assert_not_called()
        mock_drive.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("/newclient", msg)

    def test_missing_business_link_blocked(self):
        person = {"biz_ids": ["BIZ-999"], "primary_biz_id": "", "person_type": "клиент", "status": "active"}
        update, mock_create, mock_drive = self._run_newobject(person=person)
        mock_create.assert_not_called()
        mock_drive.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не привязан", msg)

    def test_no_silent_auto_link_call(self):
        """The Person is not linked to BIZ-001 — confirm the rejection
        path never calls any Business-link mutation API."""
        person = {"biz_ids": [], "primary_biz_id": "", "person_type": "клиент", "status": "active"}
        th = _fresh_th()
        update, context = _make_newobject_update_context()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=("row", {})), \
             patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch("business_core.person_manager.append_person_biz_id") as mock_append, \
             patch("business_core.business_builder.create_object_record") as mock_create:
            _run(th.newobject_cmd(update, context))

        mock_append.assert_not_called()
        mock_create.assert_not_called()

    def test_valid_client_and_business_link_proceeds(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": "", "person_type": "клиент", "status": "active"}
        update, mock_create, mock_drive = self._run_newobject(person=person)
        mock_create.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("Объект создан", msg)

    def test_existing_object_idempotency_preserved(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": "", "person_type": "клиент", "status": "active"}
        reused_result = {
            "ok": True, "obj_id": "OBJ-900", "error": None,
            "object_created": False, "object_reused": True, "warnings": [],
        }
        update, mock_create, mock_drive = self._run_newobject(person=person, create_result=reused_result)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("уже существовал", msg)

    def test_business_missing_still_blocks_before_client_check(self):
        th = _fresh_th()
        update, context = _make_newobject_update_context()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=None), \
             patch("business_core.person_manager.find_person_by_id") as mock_find_person, \
             patch("business_core.business_builder.create_object_record") as mock_create:
            _run(th.newobject_cmd(update, context))
        mock_find_person.assert_not_called()
        mock_create.assert_not_called()


# ─────────────────────────────────────────────────────────────
# provision_client_drive_safe() retry-safety (Part 9, items 39-46)
# ─────────────────────────────────────────────────────────────

class TestProvisionClientDriveSafe(unittest.TestCase):

    def test_existing_reference_reused_no_drive_call(self):
        bb = _fresh_bb()
        person = {"drive_folder_id": "fid-1", "google_drive": "https://drive.google.com/fid-1"}
        with patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch.object(bb, "provision_client_drive") as mock_provision:
            result = bb.provision_client_drive_safe("PRS-001", "Иван Иванов", "БизнесА")

        mock_provision.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertTrue(result["drive_reused"])
        self.assertFalse(result["drive_created"])
        self.assertEqual(result["folder_id"], "fid-1")

    def test_empty_reference_creates_once(self):
        bb = _fresh_bb()
        person = {"drive_folder_id": "", "google_drive": ""}
        with patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch.object(bb, "provision_client_drive",
                          return_value={"ok": True, "folder_id": "fid-new", "folder_url": "https://x/fid-new",
                                        "biz_id": "BIZ-001", "error": None}) as mock_provision, \
             patch("business_core.person_manager.update_person_drive_info",
                   return_value={"ok": True, "changed": True, "updated_fields": (), "error": None}) as mock_persist:
            result = bb.provision_client_drive_safe("PRS-002", "Мария", "БизнесБ")

        mock_provision.assert_called_once()
        mock_persist.assert_called_once_with("PRS-002", folder_id="fid-new", folder_url="https://x/fid-new")
        self.assertTrue(result["ok"])
        self.assertTrue(result["drive_created"])
        self.assertFalse(result["drive_reused"])

    def test_drive_failure_visible(self):
        bb = _fresh_bb()
        person = {"drive_folder_id": "", "google_drive": ""}
        with patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch.object(bb, "provision_client_drive",
                          return_value={"ok": False, "folder_id": None, "folder_url": None,
                                        "biz_id": None, "error": "Drive API 500"}):
            result = bb.provision_client_drive_safe("PRS-003", "Пётр", "БизнесВ")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "Drive API 500")

    def test_persistence_failure_is_partial_not_total(self):
        bb = _fresh_bb()
        person = {"drive_folder_id": "", "google_drive": ""}
        with patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch.object(bb, "provision_client_drive",
                          return_value={"ok": True, "folder_id": "fid-new", "folder_url": "https://x/fid-new",
                                        "biz_id": "BIZ-001", "error": None}), \
             patch("business_core.person_manager.update_person_drive_info",
                   return_value={"ok": False, "changed": False, "updated_fields": (), "error": "Sheets timeout"}):
            result = bb.provision_client_drive_safe("PRS-004", "Олег", "БизнесГ")

        self.assertTrue(result["ok"])  # folder itself WAS created
        self.assertTrue(result["partial_failure"])
        self.assertIsNotNone(result["warning"])

    def test_no_second_folder_created_in_retry_after_persisted(self):
        """Simulates a retry: the first call's persisted reference means
        the second call must reuse, never call provision_client_drive again."""
        bb = _fresh_bb()
        with patch("business_core.person_manager.find_person_by_id",
                   return_value={"drive_folder_id": "fid-1", "google_drive": "https://x/fid-1"}), \
             patch.object(bb, "provision_client_drive") as mock_provision:
            result = bb.provision_client_drive_safe("PRS-005", "Клиент", "Бизнес")

        mock_provision.assert_not_called()
        self.assertTrue(result["drive_reused"])

    def test_person_not_found(self):
        bb = _fresh_bb()
        with patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb.provision_client_drive_safe("PRS-999", "Никто", "Бизнес")
        self.assertFalse(result["ok"])
        self.assertIn("не найден", result["error"])


class TestNoLiveNetwork(unittest.TestCase):
    def test_provision_client_drive_safe_no_live_socket(self):
        bb = _fresh_bb()
        person = {"drive_folder_id": "fid-1", "google_drive": "https://x/fid-1"}

        def _blocked_connect(*a, **kw):
            raise AssertionError("live network access attempted in test")

        with patch("business_core.person_manager.find_person_by_id", return_value=person), \
             patch.object(socket.socket, "connect", _blocked_connect):
            result = bb.provision_client_drive_safe("PRS-001", "Иван", "Бизнес")
        self.assertTrue(result["drive_reused"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
