"""
Phase 11J: /newclient confirmation-state snapshot — mock tests.

Incident (Phase 11H/11I accelerated E2E): the confirmation card shown to
the user did not match the data actually persisted to PEOPLE_REGISTRY —
the saved record contained a truncated fragment of unrelated example
text instead of the confirmed name, and the business field held a name
fragment instead of a Biz ID. Root cause: newclient_confirm() re-read
the mutable context.user_data["nc"] draft instead of the exact values
shown in the confirmation card, so anything that mutated "nc" between
render and confirm (re-entry, a stray update, ...) silently changed
what got saved.

Fix: newclient_biz() now takes an immutable
context.user_data["nc_confirmed_snapshot"] snapshot right after
rendering the confirmation card; newclient_confirm() reads ONLY that
snapshot, never "nc" directly, and both keys are cleared after every
terminal outcome (success, cancel, or missing-snapshot error).

Separately: _get_biz_id_by_name() only matches by business NAME and
echoes its input back unchanged when nothing matches, so a user typing
an already-valid Biz ID directly (e.g. "BIZ-001") used to leave
Biz IDs/Primary Biz ID empty. newclient_confirm() now also checks the
BIZ_REGISTRY "ID" column directly as a fallback.

All tests fully mock business_core.sheets / business_core.business_builder
— no live Google Sheets/Drive API calls.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

STANDARD_HEADERS = [
    "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
    "Telegram", "Email", "Город", "Компания", "Должность",
    "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
    "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
    "День рождения", "Важные события",
    "Дата первого контакта", "Дата последнего контакта",
    "Канал последнего контакта", "История",
    "Следующее касание", "Тип касания", "Заметка касания",
    "Статус отношений", "Теплота", "Комментарий",
    "Google Drive", "Drive Folder ID",
    "Biz IDs", "Company ID", "Citizenship", "Passport / ID", "Primary Biz ID",
]


def _make_people_sheet(headers=STANDARD_HEADERS, existing_rows=None) -> MagicMock:
    sheet = MagicMock()
    sheet.row_values.return_value = list(headers)
    sheet.get_all_values.return_value = [list(headers)] + (existing_rows or [])
    sheet.update.return_value = None
    return sheet


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import (
        newclient_start, newclient_name, newclient_phone,
        newclient_type, newclient_biz, newclient_confirm, newclient_cancel,
    )
    return dict(
        start=newclient_start, name=newclient_name, phone=newclient_phone,
        type_=newclient_type, biz=newclient_biz, confirm=newclient_confirm,
        cancel=newclient_cancel,
    )


def _ctx():
    context = MagicMock()
    context.user_data = {}
    return context


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


BIZ_ROWS = [{"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"}]


def _walk_to_confirm(handlers, name="Иван Иванов", phone="+77771234567",
                      person_type="клиент", biz_answer="Узаконение недвижимости"):
    """Проходит start->name->phone->type->biz, возвращает (context, update_biz)."""
    context = _ctx()

    async def run():
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            await handlers["start"](_upd("/newclient"), context)
            await handlers["name"](_upd(name), context)
            await handlers["phone"](_upd(phone), context)
            await handlers["type_"](_upd(person_type), context)
            update_biz = _upd(biz_answer)
            await handlers["biz"](update_biz, context)
        return update_biz

    update_biz = asyncio.run(run())
    return context, update_biz


class TestSnapshotMatchesCard(unittest.TestCase):
    """1. Данные в карточке подтверждения == данные в snapshot."""

    def test_snapshot_equals_rendered_card_values(self):
        handlers = _fresh_import()
        context, update_biz = _walk_to_confirm(handlers)

        card_text = update_biz.message.reply_text.call_args[0][0]
        snap = context.user_data["nc_confirmed_snapshot"]

        self.assertIn(snap["full_name"], card_text)
        self.assertIn(snap["phone"], card_text)
        self.assertIn(snap["person_type"], card_text)
        self.assertIn(snap["businesses"], card_text)


class TestSnapshotUsedForSave(unittest.TestCase):
    """2/3. Snapshot == payload сохранения; изменение draft после
    показа карточки не влияет на сохранённые данные."""

    def _confirm_with_mocks(self, context, confirm_text="✅ Сохранить"):
        handlers = _fresh_import()
        sheet = _make_people_sheet()
        captured = {}

        def capture_update(**kwargs):
            captured["row"] = kwargs.get("values", [[]])[0]
        sheet.update.side_effect = capture_update

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](_upd(confirm_text), context)

        asyncio.run(run())
        return sheet, captured

    def test_draft_mutation_after_card_does_not_affect_save(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Иван Иванов",
                                       biz_answer="Узаконение недвижимости")

        # Симулируем то, что гипотетически произошло в инциденте:
        # "nc" (mutable draft) меняется ПОСЛЕ показа карточки подтверждения
        # (например из-за повторного входа/просочившегося обновления).
        context.user_data["nc"]["full_name"] = "СОВЕРШЕННО ДРУГОЕ ИМЯ"
        context.user_data["nc"]["businesses"] = "Другой Бизнес"

        sheet, captured = self._confirm_with_mocks(context)

        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        row = captured["row"]
        self.assertEqual(row[idx["ФИО"]], "Иван Иванов")
        self.assertNotIn("СОВЕРШЕННО ДРУГОЕ ИМЯ", row[idx["ФИО"]])
        self.assertEqual(row[idx["Бизнесы"]], "Узаконение недвижимости")

    def test_snapshot_values_equal_saved_row(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Петров Пётр", phone="+77009998877")
        snap = dict(context.user_data["nc_confirmed_snapshot"])

        sheet, captured = self._confirm_with_mocks(context)

        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        row = captured["row"]
        self.assertEqual(row[idx["ФИО"]], snap["full_name"])
        self.assertEqual(row[idx["Телефон"]], snap["phone"])


class TestConfirmationTextNeverStored(unittest.TestCase):
    """4. Confirmation text («правильно» / "✅ Сохранить") не
    записывается ни в одно поле сохранённой строки."""

    def test_confirm_button_text_not_in_row(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Тест Клиент")
        sheet = _make_people_sheet()
        captured = {}
        sheet.update.side_effect = lambda **kw: captured.update(row=kw["values"][0])

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](_upd("правильно"), context)

        asyncio.run(run())
        self.assertNotIn("правильно", captured["row"])
        self.assertNotIn("✅ Сохранить", captured["row"])


class TestFreshEntryNoStaleState(unittest.TestCase):
    """10. Повторный /newclient не наследует старый nc/snapshot."""

    def test_restart_clears_previous_snapshot(self):
        handlers = _fresh_import()
        context = _ctx()
        context.user_data["nc"] = {"full_name": "Старое Имя"}
        context.user_data["nc_confirmed_snapshot"] = {"full_name": "Старый Snapshot"}

        asyncio.run(handlers["start"](_upd("/newclient"), context))

        self.assertEqual(context.user_data["nc"], {})
        self.assertNotIn("nc_confirmed_snapshot", context.user_data)

    def test_cancel_clears_snapshot(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers)
        asyncio.run(handlers["confirm"](_upd("❌ Отмена"), context))
        self.assertNotIn("nc", context.user_data)
        self.assertNotIn("nc_confirmed_snapshot", context.user_data)


class TestMissingSnapshotIsSafe(unittest.TestCase):
    """Defensive: confirm без snapshot (не прошли через newclient_biz)
    не падает и не создаёт запись — явная ошибка вместо угадывания."""

    def test_confirm_without_snapshot_does_not_write(self):
        handlers = _fresh_import()
        context = _ctx()
        context.user_data["nc"] = {"full_name": "Что-то"}  # snapshot отсутствует

        with patch("business_core.sheets.append_business_row") as mock_append:
            asyncio.run(handlers["confirm"](_upd("✅ Сохранить"), context))
        mock_append.assert_not_called()


class TestBizIdAcceptsDirectId(unittest.TestCase):
    """6. Пользователь вводит готовый Biz ID напрямую (не название) —
    он не должен потеряться и не должен остаться пустым в Biz IDs/
    Primary Biz ID."""

    def test_direct_biz_id_resolved_via_registry_lookup(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, biz_answer="BIZ-001")

        sheet = _make_people_sheet()
        captured = {}
        sheet.update.side_effect = lambda **kw: captured.update(row=kw["values"][0])

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):  # echoed back unchanged: input == output
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(run())
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        row = captured["row"]
        self.assertEqual(row[idx["Biz IDs"]], "BIZ-001")
        self.assertEqual(row[idx["Primary Biz ID"]], "BIZ-001")


class TestFullNameCharacterPreserved(unittest.TestCase):
    """7. Первая буква имени не теряется на всём пути start->...->save."""

    def test_first_letter_preserved(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Тест Иванов")
        self.assertEqual(context.user_data["nc_confirmed_snapshot"]["full_name"], "Тест Иванов")

        sheet = _make_people_sheet()
        captured = {}
        sheet.update.side_effect = lambda **kw: captured.update(row=kw["values"][0])

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(run())
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        self.assertEqual(captured["row"][idx["ФИО"]], "Тест Иванов")


class TestSuccessNotConfusedWithFormattingError(unittest.TestCase):
    """8. Успешное сохранение не считается ошибкой, если рендеринг
    финального сообщения падает (persistence и notification разделены)."""

    def test_notify_failure_after_successful_save_still_reports_success(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Клиент Успех")
        sheet = _make_people_sheet()
        sheet.update.return_value = None

        update = _upd("✅ Сохранить")
        # Первый вызов reply_text (успешный ответ) — выбрасывает исключение,
        # эмулируя сломанный Markdown/форматирование.
        update.message.reply_text = AsyncMock(side_effect=[Exception("boom"), None])

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.sheets.append_business_row") as mock_append, \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](update, context)
                return mock_append

        mock_append = asyncio.run(run())
        # Запись всё равно должна была уйти в Sheets ДО падения нотификации.
        mock_append.assert_called_once()
        # Второй вызов reply_text — сообщение об успехе, не "Ошибка сохранения".
        second_call_msg = update.message.reply_text.call_args_list[1][0][0]
        self.assertIn("✅", second_call_msg)
        self.assertNotIn("Ошибка сохранения", second_call_msg)

    def test_success_reply_uses_no_markdown_parse_mode(self):
        """Успешный ответ рендерится без Markdown-парсинга (parse_mode=None),
        чтобы подчёркивания в Drive URL/именах не ломали Telegram-парсер."""
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Клиент С Именем")
        sheet = _make_people_sheet()

        update = _upd("✅ Сохранить")

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": True, "folder_id": "fid_with_underscore",
                                     "folder_url": "https://drive.google.com/drive/folders/fid_with_underscore"}), \
                 patch("business_core.business_builder.save_client_drive_to_sheets"), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](update, context)

        asyncio.run(run())
        _, kwargs = update.message.reply_text.call_args
        self.assertIsNone(kwargs.get("parse_mode"))


class TestUserDataCleanedAfterSuccess(unittest.TestCase):
    """9. nc / nc_confirmed_snapshot очищаются после успешного сохранения."""

    def test_cleanup_after_success(self):
        handlers = _fresh_import()
        context, _ = _walk_to_confirm(handlers, name="Клиент Клинап")
        sheet = _make_people_sheet()

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
                 patch("business_core.business_builder.find_existing_person", return_value=None), \
                 patch("business_core.business_builder.provision_client_drive",
                       return_value={"ok": False, "error": "не задан"}), \
                 patch("business_core.business_builder._get_biz_id_by_name",
                       return_value="BIZ-001"):
                await handlers["confirm"](_upd("✅ Сохранить"), context)

        asyncio.run(run())
        self.assertNotIn("nc", context.user_data)
        self.assertNotIn("nc_confirmed_snapshot", context.user_data)


class TestNoLiveApiCalls(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
