"""
Phase 13A: /editclient — mock tests.

Same immutable-snapshot architecture as /newclient (Phase 11J):
choose field -> enter new value -> confirmation card (old/was ->
new/станет) -> snapshot -> ONLY on explicit confirm does a write
happen. ID, Drive Folder ID and Created At are never touched.
Business edits resolve through business_core.business_builder.resolve_business()
and store the Biz ID, never the raw display text.

Phase 23D-3A: editclient_confirm() no longer writes PEOPLE_REGISTRY
directly — it now calls business_core.person_manager.find_person_by_id()
(structural staleness/existence guard) and
business_core.person_manager.update_person() (the actual write), then
unconditionally calls business_core.inbox_bridge.invalidate_cache()
whenever a write was attempted (never inferred from parsing
result["error"] — see the Phase 23D-3A implementation plan).

All tests fully mock business_core.person_manager / business_core.inbox_bridge —
no live Google Sheets API, no real cache access.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import (
        editclient_start, editclient_field, editclient_value, editclient_confirm,
    )
    return dict(start=editclient_start, field=editclient_field,
                value=editclient_value, confirm=editclient_confirm)


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


def _existing_person(client_id="PRS-001", fio="Кайрат", phone="87087632894",
                      biz_display="узаконение недвижимости", drive_id="DRIVE-ABC123",
                      biz_ids="", primary_biz=""):
    """The dict shape find_row_by_id()/find_person_by_id() return for a
    row — used both as editclient_start()'s pre-fetch result and as
    person_manager.find_person_by_id()'s existence-check return value."""
    return {
        "ID": client_id,
        "ФИО": fio,
        "Имя": fio.split()[0] if fio.split() else fio,
        "Телефон": phone,
        "Тип": "клиент",
        "Бизнесы": biz_display,
        "Комментарий": "",
        "Drive Folder ID": drive_id,
        "Biz IDs": biz_ids,
        "Primary Biz ID": primary_biz,
    }


class TestEditClientEntityNotFound(unittest.TestCase):
    def test_unknown_client_id_reports_not_found(self):
        handlers = _fresh_import()
        context = _ctx(args=["client_id=PRS-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=None):
                return await handlers["start"](_upd("/editclient client_id=PRS-999"), context)

        result = asyncio.run(run())
        from telegram.ext import ConversationHandler
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ec", context.user_data)


def _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233",
                      existing_row=None, biz_rows=None):
    context = _ctx(args=["client_id=PRS-001"])
    row = existing_row or _existing_person()
    biz_rows = biz_rows or [{"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"}]

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.read_business_sheet", return_value=biz_rows):
            await handlers["start"](_upd("/editclient client_id=PRS-001"), context)
            await handlers["field"](_upd(field_button), context)
            await handlers["value"](_upd(new_value), context)

    asyncio.run(run())
    return context


def _confirm_with_mocks(handlers, context, *, person_found=True,
                         update_result=None, text="✅ Сохранить"):
    """Run editclient_confirm() with person_manager.find_person_by_id()
    and update_person() mocked, plus inbox_bridge.invalidate_cache()
    tracked. Returns (mock_find, mock_update, mock_invalidate)."""
    update_result = update_result if update_result is not None else {
        "ok": True, "changed": True, "updated_fields": (), "error": None,
    }

    async def run():
        with patch("business_core.person_manager.find_person_by_id",
                    return_value=(_existing_person() if person_found else None)) as mock_find, \
             patch("business_core.person_manager.update_person",
                   return_value=update_result) as mock_update, \
             patch("business_core.inbox_bridge.invalidate_cache") as mock_invalidate:
            await handlers["confirm"](_upd(text), context)
            return mock_find, mock_update, mock_invalidate

    return asyncio.run(run())


class TestEditClientFieldMapping(unittest.TestCase):
    """Phase 23D-3A: each of the 4 editable fields must map to the
    exact update_person() field dict — full_name -> ФИО+Имя, phone ->
    Телефон only, business -> Бизнесы+Biz IDs+Primary Biz ID, notes ->
    Комментарий only. ID and Drive Folder ID must never appear."""

    def test_full_name_maps_to_fio_and_imya(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Имя (ФИО)", new_value="Асхат Нурланов")
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once_with("PRS-001", {"ФИО": "Асхат Нурланов", "Имя": "Асхат"})

    def test_phone_maps_only_to_telefon(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once_with("PRS-001", {"Телефон": "87001112233"})

    def test_business_maps_to_bizness_biz_ids_primary(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Бизнес", new_value="узаконение недвижимости")
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once_with("PRS-001", {
            "Бизнесы": "Узаконение недвижимости",
            "Biz IDs": "BIZ-001",
            "Primary Biz ID": "BIZ-001",
        })

    def test_notes_maps_only_to_kommentariy(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Комментарий", new_value="звонил дважды")
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once_with("PRS-001", {"Комментарий": "звонил дважды"})

    def test_update_person_called_exactly_once(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once()

    def test_id_and_drive_folder_id_never_in_updates(self):
        for field_button, new_value in (
            ("Имя (ФИО)", "Новое Имя"), ("Телефон", "87001112233"),
            ("Бизнес", "узаконение недвижимости"), ("Комментарий", "заметка"),
        ):
            handlers = _fresh_import()
            context = _walk_to_confirm(handlers, field_button=field_button, new_value=new_value)
            mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

            updates_arg = mock_update.call_args.args[1]
            self.assertNotIn("ID", updates_arg)
            self.assertNotIn("Drive Folder ID", updates_arg)


class TestEditClientSnapshotProtection(unittest.TestCase):
    def test_confirmed_snapshot_used_not_mutated_draft(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        # Мутация draft ПОСЛЕ показа карточки подтверждения не должна
        # повлиять на то, что реально сохранится.
        context.user_data["ec"]["new_value"] = "СОВСЕМ ДРУГОЕ ЗНАЧЕНИЕ"

        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        mock_update.assert_called_once_with("PRS-001", {"Телефон": "87001112233"})


class TestEditClientCancel(unittest.TestCase):
    def test_cancel_calls_neither_find_person_by_id_nor_update_person(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(
            handlers, context, text="❌ Отмена",
        )

        mock_find.assert_not_called()
        mock_update.assert_not_called()
        mock_invalidate.assert_not_called()
        self.assertNotIn("ec", context.user_data)
        self.assertNotIn("ec_confirmed_snapshot", context.user_data)


class TestEditClientNotFound(unittest.TestCase):
    def test_not_found_calls_neither_update_person_nor_invalidate_cache(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        async def run():
            update = _upd("✅ Сохранить")
            with patch("business_core.person_manager.find_person_by_id", return_value=None) as mock_find, \
                 patch("business_core.person_manager.update_person") as mock_update, \
                 patch("business_core.inbox_bridge.invalidate_cache") as mock_invalidate:
                await handlers["confirm"](update, context)
                return update, mock_find, mock_update, mock_invalidate

        update, mock_find, mock_update, mock_invalidate = asyncio.run(run())

        mock_find.assert_called_once_with("PRS-001")
        mock_update.assert_not_called()
        mock_invalidate.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertEqual(msg, "❌ Клиент PRS-001 больше не найден — изменение не выполнено.")


class TestEditClientCacheInvalidation(unittest.TestCase):
    def test_success_calls_invalidate_cache_exactly_once(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(
            handlers, context,
            update_result={"ok": True, "changed": True, "updated_fields": ("Телефон",), "error": None},
        )

        mock_invalidate.assert_called_once()

    def test_update_person_failure_still_calls_invalidate_cache_exactly_once(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(
            handlers, context,
            update_result={"ok": False, "changed": False, "updated_fields": (), "error": "boom"},
        )

        mock_invalidate.assert_called_once()


class TestEditClientGenericFailureMessage(unittest.TestCase):
    def test_generic_failure_message_is_exact(self):
        handlers = _fresh_import()
        context = _walk_to_confirm(handlers, field_button="Телефон", new_value="87001112233")

        async def run():
            update = _upd("✅ Сохранить")
            with patch("business_core.person_manager.find_person_by_id",
                        return_value=_existing_person()), \
                 patch("business_core.person_manager.update_person",
                       return_value={"ok": False, "changed": False, "updated_fields": (), "error": "boom"}), \
                 patch("business_core.inbox_bridge.invalidate_cache"):
                await handlers["confirm"](update, context)
                return update

        update = asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertEqual(msg, "❌ Ошибка сохранения: boom")


class TestEditClientBusinessSavesId(unittest.TestCase):
    def test_business_edit_saves_biz_id_not_display_name(self):
        """Тот же production-баг, что чинил Phase 13A resolver:
        'узаконение недвижимости' в свободной форме -> BIZ-001."""
        handlers = _fresh_import()
        context = _walk_to_confirm(
            handlers, field_button="Бизнес", new_value="узаконение недвижимости",
        )
        mock_find, mock_update, mock_invalidate = _confirm_with_mocks(handlers, context)

        updates_arg = mock_update.call_args.args[1]
        self.assertEqual(updates_arg["Biz IDs"], "BIZ-001")
        self.assertEqual(updates_arg["Primary Biz ID"], "BIZ-001")

    def test_unresolvable_business_reprompts_without_writing(self):
        handlers = _fresh_import()
        context = _ctx(args=["client_id=PRS-001"])
        row = _existing_person()
        biz_rows = [{"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"}]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
                 patch("business_core.sheets.read_business_sheet", return_value=biz_rows):
                await handlers["start"](_upd("/editclient client_id=PRS-001"), context)
                await handlers["field"](_upd("Бизнес"), context)
                result = await handlers["value"](_upd("Совершенно другой бизнес"), context)
                return result

        from business_core.telegram_handlers import EC_VALUE
        result = asyncio.run(run())
        self.assertEqual(result, EC_VALUE)
        self.assertNotIn("ec_confirmed_snapshot", context.user_data)


class TestEditClientNoDirectRegistryAccess(unittest.TestCase):
    """Phase 23D-3A architecture guard: editclient_confirm() must call
    no direct get_business_sheet()/update_cell()/row_values()/
    header.index()/append_business_row() — only Person Manager's
    find_person_by_id()/update_person()."""

    def test_no_direct_registry_write_calls_remain(self):
        import ast
        import inspect
        from business_core.telegram_handlers import editclient_confirm

        source = inspect.getsource(editclient_confirm)
        tree = ast.parse(source)

        forbidden_calls = {
            "get_business_sheet", "update_cell", "row_values", "append_business_row",
        }
        found_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name in forbidden_calls:
                    found_calls.add(name)
            if isinstance(node, ast.ImportFrom) and node.module == "business_core.sheets":
                for alias in node.names:
                    self.assertNotIn(
                        alias.name, {"get_business_sheet", "find_row_by_id", "append_business_row"},
                        f"editclient_confirm must not import {alias.name} from business_core.sheets",
                    )

        self.assertEqual(found_calls, set())

    def test_no_header_index_pattern(self):
        import inspect
        from business_core.telegram_handlers import editclient_confirm

        source = inspect.getsource(editclient_confirm)
        self.assertNotIn("headers.index(", source)
        self.assertNotIn(".row_values(1)", source)


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
