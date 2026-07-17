"""
Phase 10.2E: /newroadmap deprecation — mock tests.

newroadmap_start() больше не запускает legacy-диалог создания дорожной
карты (client+service, positional writer, canonical-несовместимый
Status "not_started", Object ID/Case Type/Template ID никогда не
заполняются — см. Phase 10.2E audit). Вместо этого сразу отправляет
redirect на /startroadmap и завершает conversation.

Все тесты полностью мокают Google Sheets API — ни один тест не должен
обращаться к live API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from telegram.ext import ConversationHandler


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import newroadmap_start
    return newroadmap_start


def _make_update_context(existing_user_data: dict | None = None):
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = existing_user_data if existing_user_data is not None else {}
    return update, context


class TestNewroadmapStartDeprecation(unittest.TestCase):
    """1-3. Возвращает END, отправляет redirect-сообщение, упоминает /startroadmap."""

    def setUp(self):
        newroadmap_start = _fresh_import()
        self.update, self.context = _make_update_context()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            self.result = asyncio.run(newroadmap_start(self.update, self.context))

    def test_1_returns_conversation_end(self):
        self.assertEqual(self.result, ConversationHandler.END)

    def test_2_sends_message(self):
        self.update.message.reply_text.assert_called_once()

    def test_3_mentions_startroadmap(self):
        msg = self.update.message.reply_text.call_args[0][0]
        self.assertIn("/startroadmap", msg)
        self.assertIn("больше не используется", msg)


class TestNewroadmapStartNoConversationState(unittest.TestCase):
    """4. context.user_data["nr"] не создаётся."""

    def test_nr_key_not_created(self):
        newroadmap_start = _fresh_import()
        update, context = _make_update_context(existing_user_data={})
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(newroadmap_start(update, context))
        self.assertNotIn("nr", context.user_data)


class TestNewroadmapStartStaleState(unittest.TestCase):
    """5. Существующий context.user_data["nr"] безопасно удаляется,
    остальные ключи user_data не трогаются."""

    def test_stale_nr_removed_other_keys_preserved(self):
        newroadmap_start = _fresh_import()
        existing = {
            "nr": {"business_id": "BIZ-001", "client_name": "Stale Client"},
            "unrelated_key": "unrelated_value",
            "another_flow": {"foo": "bar"},
        }
        update, context = _make_update_context(existing_user_data=existing)
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            asyncio.run(newroadmap_start(update, context))

        self.assertNotIn("nr", context.user_data)
        self.assertEqual(context.user_data.get("unrelated_key"), "unrelated_value")
        self.assertEqual(context.user_data.get("another_flow"), {"foo": "bar"})


class TestNewroadmapStartNoWrites(unittest.TestCase):
    """6-9. Ни один Sheets/write helper не вызывается."""

    def _run_with_mocks(self):
        newroadmap_start = _fresh_import()
        update, context = _make_update_context()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet, \
             patch("business_core.sheets.read_business_sheet") as mock_read_sheet, \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.generate_next_id") as mock_gen_id, \
             patch("business_core.business_builder.create_roadmap_for_object") as mock_create_rm:
            asyncio.run(newroadmap_start(update, context))
        return mock_get_sheet, mock_read_sheet, mock_append, mock_gen_id, mock_create_rm

    def test_6_no_get_business_sheet(self):
        mock_get_sheet, *_ = self._run_with_mocks()
        mock_get_sheet.assert_not_called()

    def test_6b_no_read_business_sheet(self):
        _, mock_read_sheet, *_ = self._run_with_mocks()
        mock_read_sheet.assert_not_called()

    def test_7_no_append_business_row(self):
        _, _, mock_append, _, _ = self._run_with_mocks()
        mock_append.assert_not_called()

    def test_8_no_generate_next_id(self):
        *_, mock_gen_id, _ = self._run_with_mocks()
        mock_gen_id.assert_not_called()

    def test_9_no_create_roadmap_for_object(self):
        *_, mock_create_rm = self._run_with_mocks()
        mock_create_rm.assert_not_called()


class TestNewroadmapStartNoLegacyStateHandlers(unittest.TestCase):
    """10. Ни один legacy state-handler (newroadmap_business/client/
    service/city/days/confirm) не вызывается."""

    def test_no_legacy_handlers_called(self):
        newroadmap_start = _fresh_import()
        update, context = _make_update_context()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.telegram_handlers.newroadmap_business") as mock_business, \
             patch("business_core.telegram_handlers.newroadmap_client") as mock_client, \
             patch("business_core.telegram_handlers.newroadmap_service") as mock_service, \
             patch("business_core.telegram_handlers.newroadmap_city") as mock_city, \
             patch("business_core.telegram_handlers.newroadmap_days") as mock_days, \
             patch("business_core.telegram_handlers.newroadmap_confirm") as mock_confirm:
            asyncio.run(newroadmap_start(update, context))

        mock_business.assert_not_called()
        mock_client.assert_not_called()
        mock_service.assert_not_called()
        mock_city.assert_not_called()
        mock_days.assert_not_called()
        mock_confirm.assert_not_called()


class TestNewroadmapStartNoLiveApiImportTime(unittest.TestCase):
    """11, 12. Нет обращения к live API; нет Sheets-доступа на этапе импорта модуля."""

    def test_no_live_api_calls_during_import(self):
        # Импорт модуля не должен вызывать get_business_sheet вовсе —
        # проверяем, что сам факт импорта не создаёт побочных обращений.
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
        mock_get_sheet.assert_not_called()

    def test_disabled_bc_path_also_no_writes(self):
        """Если Business Core отключён — тоже никаких обращений к Sheets."""
        newroadmap_start = _fresh_import()
        update, context = _make_update_context()
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet, \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = asyncio.run(newroadmap_start(update, context))
        self.assertEqual(result, ConversationHandler.END)
        mock_get_sheet.assert_not_called()
        mock_append.assert_not_called()


if __name__ == "__main__":
    unittest.main()
