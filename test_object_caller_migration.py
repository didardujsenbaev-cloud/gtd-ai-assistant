"""
Phase 30D: caller migration behavioral tests not already covered by
test_business_objects.py / test_business_editobject.py — Drive
retry-safety structured result, /newobject idempotent UX, and
find_roadmaps_by_object's delegation to roadmap_manager.list_roadmaps.

No live Sheets/Drive/network calls anywhere in this file.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _fresh_bb():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.business_builder as bb
    return bb


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


# ────────────────────────────────────────────────────────────
# Drive retry-safety (Part 6 / Part 10 items 27-33)
# ────────────────────────────────────────────────────────────

class TestDriveRetrySafety(unittest.TestCase):
    def test_existing_folder_id_skips_drive_api_call(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "EXISTING-ID", "drive_url": "https://existing"}), \
             patch("integrations.google_drive_adapter.create_object_folder") as mock_create:
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertTrue(result["ok"])
        self.assertTrue(result["drive_reused"])
        self.assertFalse(result["drive_created"])
        self.assertEqual(result["folder_id"], "EXISTING-ID")
        mock_create.assert_not_called()

    def test_empty_folder_id_creates_once(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "", "drive_url": ""}), \
             patch("business_core.business_builder.resolve_drive_root_for_business",
                   return_value={"root_id": "root-1", "ok": True, "error": None}), \
             patch("business_core.business_builder.get_business_config",
                   return_value={"name": "X", "found": True}), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"full_name": "Иван", "drive_folder_id": "cl-folder", "google_drive": "https://cl"}), \
             patch("business_core.object_manager.update_object_drive_info",
                   return_value={"ok": True, "object_id": "OBJ-001", "updated": True, "error": None}) as mock_persist, \
             patch("integrations.google_drive_adapter.create_object_folder",
                   return_value={"ok": True, "folder_id": "NEW-ID", "folder_url": "https://new", "error": None}) as mock_create, \
             patch.dict("os.environ", {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertTrue(result["ok"])
        self.assertTrue(result["drive_created"])
        self.assertFalse(result["drive_reused"])
        mock_create.assert_called_once()
        mock_persist.assert_called_once_with(
            "OBJ-001", folder_id="NEW-ID", folder_url="https://new", only_if_empty=True,
        )

    def test_retry_after_persisted_reference_reuses(self):
        """A second call after the reference was already persisted must
        not call Drive's create_object_folder again."""
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "NEW-ID", "drive_url": "https://new"}), \
             patch("integrations.google_drive_adapter.create_object_folder") as mock_create:
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertTrue(result["drive_reused"])
        mock_create.assert_not_called()

    def test_drive_creation_failure_visible(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "", "drive_url": ""}), \
             patch("business_core.business_builder.resolve_drive_root_for_business",
                   return_value={"root_id": "root-1", "ok": True, "error": None}), \
             patch("business_core.business_builder.get_business_config",
                   return_value={"name": "X", "found": True}), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"full_name": "Иван", "drive_folder_id": "cl-folder", "google_drive": ""}), \
             patch("integrations.google_drive_adapter.create_object_folder",
                   return_value={"ok": False, "folder_id": None, "folder_url": None, "error": "drive is down"}), \
             patch.dict("os.environ", {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertFalse(result["ok"])
        self.assertIn("drive is down", result["error"])
        self.assertFalse(result["drive_created"])

    def test_persistence_failure_visible_as_partial(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "", "drive_url": ""}), \
             patch("business_core.business_builder.resolve_drive_root_for_business",
                   return_value={"root_id": "root-1", "ok": True, "error": None}), \
             patch("business_core.business_builder.get_business_config",
                   return_value={"name": "X", "found": True}), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"full_name": "Иван", "drive_folder_id": "cl-folder", "google_drive": ""}), \
             patch("business_core.object_manager.update_object_drive_info",
                   return_value={"ok": False, "object_id": "OBJ-001", "updated": False, "error": "sheets timeout"}), \
             patch("integrations.google_drive_adapter.create_object_folder",
                   return_value={"ok": True, "folder_id": "NEW-ID", "folder_url": "https://new", "error": None}) as mock_create, \
             patch.dict("os.environ", {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertTrue(result["ok"])  # Drive folder genuinely exists
        self.assertTrue(result["drive_created"])
        self.assertTrue(result["partial_failure"])
        mock_create.assert_called_once()

    def test_structured_result_shape(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"drive_folder_id": "EXISTING-ID", "drive_url": "https://existing"}):
            result = bb.provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        expected_keys = {"ok", "folder_id", "folder_url", "error", "drive_created", "drive_reused", "partial_failure"}
        self.assertEqual(set(result.keys()), expected_keys)


# ────────────────────────────────────────────────────────────
# find_roadmaps_by_object migration (Part 7 / Part 10 items 39-40)
# ────────────────────────────────────────────────────────────

class TestFindRoadmapsByObjectDelegation(unittest.TestCase):
    def test_delegates_to_roadmap_manager_list_roadmaps(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.list_roadmaps") as mock_list:
            mock_list.return_value = [{
                "roadmap_id": "RM-001", "business_id": "BIZ-001", "service_id": "SVC-001",
                "client_id": "PRS-001", "client_name": "Test", "status": "active", "raw_status": "active",
                "created": "2026-01-01", "object_id": "OBJ-001", "case_type": "general", "progress": "0",
            }]
            results = bb.find_roadmaps_by_object("OBJ-001")

        mock_list.assert_called_once_with(object_id="OBJ-001")
        self.assertEqual(len(results), 1)

    def test_preserves_return_shape(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.list_roadmaps") as mock_list:
            mock_list.return_value = [{
                "roadmap_id": "RM-001", "business_id": "BIZ-001", "service_id": "SVC-001",
                "client_id": "PRS-001", "client_name": "Test Roadmap", "status": "active", "raw_status": "active",
                "created": "2026-01-01", "object_id": "OBJ-001", "case_type": "general", "progress": "0",
            }]
            results = bb.find_roadmaps_by_object("OBJ-001")

        self.assertEqual(results[0]["roadmap_id"], "RM-001")
        self.assertEqual(results[0]["biz_id"], "BIZ-001")
        self.assertEqual(results[0]["title"], "Test Roadmap")
        self.assertEqual(results[0]["obj_id"], "OBJ-001")


# ────────────────────────────────────────────────────────────
# /newobject idempotent UX (Part 8 / Part 10 items 34-38)
# ────────────────────────────────────────────────────────────

def _make_update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    return update, context


class TestNewObjectIdempotentUx(unittest.TestCase):
    def _run(self, args_str, create_result, biz_row=("row", {})):
        th = _fresh_th()
        update, context = _make_update()
        context.args = args_str.split()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=biz_row), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={
                       "biz_ids": ["BIZ-001"], "primary_biz_id": "", "full_name": "Клиент",
                       "person_type": "клиент", "status": "active",
                   }), \
             patch("business_core.business_builder.add_biz_id_to_person"), \
             patch("business_core.business_builder.create_object_record", return_value=create_result), \
             patch("business_core.business_builder.provision_object_drive",
                   return_value={"ok": False, "folder_id": None, "folder_url": None, "error": None,
                                 "drive_created": False, "drive_reused": False, "partial_failure": False}):
            asyncio.run(th.newobject_cmd(update, context))

        return update.message.reply_text.call_args[0][0]

    def test_new_object_message(self):
        reply = self._run(
            'biz_id=BIZ-001 client_id=PRS-001 city=Алматы address="ул. Тест 1"',
            {"ok": True, "obj_id": "OBJ-900", "error": None,
             "object_created": True, "object_reused": False, "warnings": []},
        )
        self.assertIn("Объект создан", reply)

    def test_reused_object_message(self):
        reply = self._run(
            'biz_id=BIZ-001 client_id=PRS-001 city=Алматы address="ул. Тест 1"',
            {"ok": True, "obj_id": "OBJ-900", "error": None,
             "object_created": False, "object_reused": True, "warnings": []},
        )
        self.assertIn("уже существовал", reply)

    def test_mismatch_warning_shown(self):
        reply = self._run(
            'biz_id=BIZ-001 client_id=PRS-001 city=Алматы address="ул. Тест 1"',
            {"ok": True, "obj_id": "OBJ-900", "error": None,
             "object_created": False, "object_reused": True,
             "warnings": ["object_type: запрошено 'дом', в существующей записи 'квартира'"]},
        )
        self.assertIn("Отличия", reply)
        self.assertIn("object_type", reply)

    def test_business_missing_blocks_creation(self):
        th = _fresh_th()
        update, context = _make_update()
        context.args = 'biz_id=BIZ-NOPE client_id=PRS-001 city=Алматы address="ул. Тест 1"'.split()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=None), \
             patch("business_core.business_builder.create_object_record") as mock_create, \
             patch("business_core.business_builder.provision_object_drive") as mock_drive:
            asyncio.run(th.newobject_cmd(update, context))

        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", reply)
        mock_create.assert_not_called()
        mock_drive.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
