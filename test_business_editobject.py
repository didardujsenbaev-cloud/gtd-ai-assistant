"""
Phase 13A: /editobject — mock tests.

Same immutable-snapshot architecture as /editclient. Object ID, Client
ID, Drive Folder ID, Created At and Roadmap ID are never touched by
this command — Client ID reassignment was explicitly excluded from
this first version per Phase 13A's own scope decision.

All tests fully mock business_core.sheets — no live Google Sheets API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

OBJECT_HEADERS = [
    "OBJ ID", "Client ID", "Biz ID", "City", "Address", "Object Type",
    "Object Status", "Roadmap ID", "Drive Folder ID", "Google Drive",
    "Notes", "Created At", "Last Updated",
]


def _make_object_sheet(rows: list[list]) -> MagicMock:
    sheet = MagicMock()
    values = [OBJECT_HEADERS] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    updates = {}
    def _update_cell(row, col, value):
        updates[(row, col)] = value
    sheet.update_cell.side_effect = _update_cell
    sheet._updates = updates
    return sheet


def _existing_row(obj_id="OBJ-001", client_id="PRS-001", address="ул. Абая 10",
                   object_type="жилой дом", roadmap_id="RM-001", drive_id="DRIVE-OBJ-1"):
    idx = {h: i for i, h in enumerate(OBJECT_HEADERS)}
    row = [""] * len(OBJECT_HEADERS)
    row[idx["OBJ ID"]] = obj_id
    row[idx["Client ID"]] = client_id
    row[idx["Biz ID"]] = "BIZ-001"
    row[idx["City"]] = "Алматы"
    row[idx["Address"]] = address
    row[idx["Object Type"]] = object_type
    row[idx["Object Status"]] = "new"
    row[idx["Roadmap ID"]] = roadmap_id
    row[idx["Drive Folder ID"]] = drive_id
    row[idx["Notes"]] = ""
    row[idx["Created At"]] = "2026-07-18"
    row[idx["Last Updated"]] = "2026-07-18"
    return row


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import (
        editobject_start, editobject_field, editobject_value, editobject_confirm,
    )
    return dict(start=editobject_start, field=editobject_field,
                value=editobject_value, confirm=editobject_confirm)


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _ctx(args=None):
    context = MagicMock()
    context.user_data = {}
    context.args = args or []
    return context


class TestEditObjectEntityNotFound(unittest.TestCase):
    def test_unknown_object_id_reports_not_found(self):
        handlers = _fresh_import()
        context = _ctx(args=["object_id=OBJ-999"])
        sheet = _make_object_sheet([])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet):
                return await handlers["start"](_upd("/editobject object_id=OBJ-999"), context)

        result = asyncio.run(run())
        from telegram.ext import ConversationHandler
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("eo", context.user_data)


def _walk_to_confirm(handlers, field_button="Адрес", new_value="ул. Пушкина 5",
                      existing_row=None):
    context = _ctx(args=["object_id=OBJ-001"])
    sheet = _make_object_sheet([existing_row or _existing_row()])

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            await handlers["start"](_upd("/editobject object_id=OBJ-001"), context)
            await handlers["field"](_upd(field_button), context)
            await handlers["value"](_upd(new_value), context)

    asyncio.run(run())
    return context, sheet


class TestEditObjectAddressChanges(unittest.TestCase):
    def test_address_change_updates_only_address_cell(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Адрес", new_value="ул. Пушкина 5")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(OBJECT_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        addr_col = OBJECT_HEADERS.index("Address") + 1
        self.assertEqual(sheet._updates.get((2, addr_col)), "ул. Пушкина 5")

    def test_address_change_mentions_drive_folder_name_unchanged(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Адрес", new_value="ул. Пушкина 5")
        update = _upd("✅ Сохранить")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(OBJECT_HEADERS, _existing_row())))):
                await handlers["confirm"](update, context)

        asyncio.run(confirm())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("Drive-папки", msg)
        self.assertIn("прежним", msg)


class TestEditObjectIdAndDriveUnchanged(unittest.TestCase):
    def test_obj_id_client_id_drive_id_roadmap_id_never_written(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Комментарий", new_value="Ключи у соседа")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(OBJECT_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        written_cols = {col for (_row, col) in sheet._updates}
        for protected in ("OBJ ID", "Client ID", "Drive Folder ID", "Roadmap ID", "Created At"):
            self.assertNotIn(OBJECT_HEADERS.index(protected) + 1, written_cols,
                              f"{protected} must never be written by /editobject")


class TestEditObjectRoadmapLinkageUnchanged(unittest.TestCase):
    def test_roadmap_id_cell_untouched_after_edit(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Тип объекта", new_value="частный дом")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(OBJECT_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        roadmap_col = OBJECT_HEADERS.index("Roadmap ID") + 1
        self.assertNotIn((2, roadmap_col), sheet._updates)


class TestEditObjectCancel(unittest.TestCase):
    def test_cancel_at_confirm_writes_nothing(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Адрес", new_value="ул. Пушкина 5")

        async def cancel():
            await handlers["confirm"](_upd("❌ Отмена"), context)

        asyncio.run(cancel())
        self.assertEqual(sheet._updates, {})
        self.assertNotIn("eo", context.user_data)
        self.assertNotIn("eo_confirmed_snapshot", context.user_data)


class TestEditObjectNoLiveApi(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
