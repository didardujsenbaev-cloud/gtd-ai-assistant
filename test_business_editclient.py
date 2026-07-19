"""
Phase 13A: /editclient — mock tests.

Same immutable-snapshot architecture as /newclient (Phase 11J):
choose field -> enter new value -> confirmation card (old/was ->
new/станет) -> snapshot -> ONLY on explicit confirm does a single
targeted cell write happen, against a freshly re-read row. ID, Drive
Folder ID and Created At are never touched. Business edits resolve
through business_core.business_builder.resolve_business() and store
the Biz ID, never the raw display text.

All tests fully mock business_core.sheets — no live Google Sheets API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

PEOPLE_HEADERS = [
    "ID", "ФИО", "Имя", "Телефон", "Тип", "Бизнесы",
    "Комментарий", "Google Drive", "Drive Folder ID",
    "Biz IDs", "Primary Biz ID", "Дата первого контакта",
]


def _make_people_sheet(rows: list[list]) -> MagicMock:
    sheet = MagicMock()
    values = [PEOPLE_HEADERS] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    updates = {}
    def _update_cell(row, col, value):
        updates[(row, col)] = value
    sheet.update_cell.side_effect = _update_cell
    sheet._updates = updates
    return sheet


def _existing_row(client_id="PRS-001", fio="Кайрат", phone="87087632894",
                   biz_display="узаконение недвижимости", drive_id="DRIVE-ABC123",
                   biz_ids="", primary_biz=""):
    idx = {h: i for i, h in enumerate(PEOPLE_HEADERS)}
    row = [""] * len(PEOPLE_HEADERS)
    row[idx["ID"]] = client_id
    row[idx["ФИО"]] = fio
    row[idx["Имя"]] = fio.split()[0] if fio.split() else fio
    row[idx["Телефон"]] = phone
    row[idx["Тип"]] = "клиент"
    row[idx["Бизнесы"]] = biz_display
    row[idx["Комментарий"]] = ""
    row[idx["Drive Folder ID"]] = drive_id
    row[idx["Biz IDs"]] = biz_ids
    row[idx["Primary Biz ID"]] = primary_biz
    row[idx["Дата первого контакта"]] = "2026-07-18"
    return row


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import (
        editclient_start, editclient_field, editclient_value, editclient_confirm,
    )
    return dict(start=editclient_start, field=editclient_field,
                value=editclient_value, confirm=editclient_confirm)


def _upd(text: str, args=None):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _ctx(args=None):
    context = MagicMock()
    context.user_data = {}
    context.args = args or []
    return context


class TestEditClientEntityNotFound(unittest.TestCase):
    def test_unknown_client_id_reports_not_found(self):
        handlers = _fresh_import()
        context = _ctx(args=["client_id=PRS-999"])
        sheet = _make_people_sheet([])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet):
                return await handlers["start"](_upd("/editclient client_id=PRS-999"), context)

        result = asyncio.run(run())
        from telegram.ext import ConversationHandler
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ec", context.user_data)


def _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233",
                      existing_row=None, biz_rows=None):
    context = _ctx(args=["client_id=PRS-001"])
    sheet = _make_people_sheet([existing_row or _existing_row()])
    biz_rows = biz_rows or [{"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"}]

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.read_business_sheet", return_value=biz_rows):
            await handlers["start"](_upd("/editclient client_id=PRS-001"), context)
            await handlers["field"](_upd(field_button), context)
            await handlers["value"](_upd(new_value), context)

    asyncio.run(run())
    return context, sheet


class TestEditClientOneFieldChanges(unittest.TestCase):
    def test_phone_change_updates_only_phone_cell(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(PEOPLE_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        phone_col = PEOPLE_HEADERS.index("Телефон") + 1
        self.assertEqual(sheet._updates.get((2, phone_col)), "87001112233")
        # ни ID, ни Drive Folder ID не должны были обновиться
        id_col = PEOPLE_HEADERS.index("ID") + 1
        drive_col = PEOPLE_HEADERS.index("Drive Folder ID") + 1
        self.assertNotIn((2, id_col), sheet._updates)
        self.assertNotIn((2, drive_col), sheet._updates)


class TestEditClientIdAndDriveUnchanged(unittest.TestCase):
    def test_id_and_drive_folder_id_never_written(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Комментарий", new_value="звонил дважды")

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(PEOPLE_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        written_cols = {col for (_row, col) in sheet._updates}
        self.assertNotIn(PEOPLE_HEADERS.index("ID") + 1, written_cols)
        self.assertNotIn(PEOPLE_HEADERS.index("Drive Folder ID") + 1, written_cols)


class TestEditClientSnapshotProtection(unittest.TestCase):
    def test_draft_mutation_after_card_does_not_affect_save(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        # Мутация draft ПОСЛЕ показа карточки подтверждения не должна
        # повлиять на то, что реально сохранится.
        context.user_data["ec"]["new_value"] = "СОВСЕМ ДРУГОЕ ЗНАЧЕНИЕ"

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(PEOPLE_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        phone_col = PEOPLE_HEADERS.index("Телефон") + 1
        self.assertEqual(sheet._updates.get((2, phone_col)), "87001112233")
        self.assertNotIn("СОВСЕМ ДРУГОЕ ЗНАЧЕНИЕ", sheet._updates.values())


class TestEditClientCancel(unittest.TestCase):
    def test_cancel_at_confirm_writes_nothing(self):
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        async def cancel():
            await handlers["confirm"](_upd("❌ Отмена"), context)

        asyncio.run(cancel())
        self.assertEqual(sheet._updates, {})
        self.assertNotIn("ec", context.user_data)
        self.assertNotIn("ec_confirmed_snapshot", context.user_data)


class TestEditClientBusinessSavesId(unittest.TestCase):
    def test_business_edit_saves_biz_id_not_display_name(self):
        """Тот же production-баг, что чинил Phase 13A resolver:
        'узаконение недвижимости' в свободной форме -> BIZ-001."""
        handlers = _fresh_import()
        context, sheet = _walk_to_confirm(
            handlers, field_button="Бизнес", new_value="узаконение недвижимости",
        )

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, dict(zip(PEOPLE_HEADERS, _existing_row())))):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(confirm())
        biz_ids_col = PEOPLE_HEADERS.index("Biz IDs") + 1
        primary_col = PEOPLE_HEADERS.index("Primary Biz ID") + 1
        self.assertEqual(sheet._updates.get((2, biz_ids_col)), "BIZ-001")
        self.assertEqual(sheet._updates.get((2, primary_col)), "BIZ-001")

    def test_unresolvable_business_reprompts_without_writing(self):
        handlers = _fresh_import()
        context = _ctx(args=["client_id=PRS-001"])
        sheet = _make_people_sheet([_existing_row()])
        biz_rows = [{"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"}]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.read_business_sheet", return_value=biz_rows):
                await handlers["start"](_upd("/editclient client_id=PRS-001"), context)
                await handlers["field"](_upd("Бизнес"), context)
                result = await handlers["value"](_upd("Совершенно другой бизнес"), context)
                return result

        from business_core.telegram_handlers import EC_VALUE
        result = asyncio.run(run())
        self.assertEqual(result, EC_VALUE)
        self.assertNotIn("ec_confirmed_snapshot", context.user_data)
        self.assertEqual(sheet._updates, {})


class TestEditClientNoLiveApi(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
