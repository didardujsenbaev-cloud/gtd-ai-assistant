"""
Phase 10.2D: /newservice parser & Biz ID validation hardening — mock tests.

Инцидент: случайное сообщение "/newservice завершён успешно." создало
реальную запись SVC-001 (Бизнес ID='завершён', Название='успешно.') —
positional fallback (_pos0/_pos1) тихо интерпретировал свободный текст
как biz_id/name, без проверки существования бизнеса.

Эти тесты проверяют, что:
- positional fallback полностью удалён;
- свободный текст без key=value отклоняется;
- несуществующий biz_id отклоняется;
- корректный key=value ввод продолжает работать без изменения семантики.

Все тесты полностью мокают Google Sheets API (через find_row_by_id /
get_business_sheet) — ни один тест не должен обращаться к live API.
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
    from business_core.telegram_handlers import newservice_cmd
    return newservice_cmd


def _make_update_context(args_list):
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 123
    context = MagicMock()
    context.args = args_list
    return update, context


def _run(args_list, biz_exists=True, create_result=None):
    """
    Запустить newservice_cmd с полностью замоканными зависимостями.

    biz_exists: что вернёт find_row_by_id для biz_registry (True → найден,
                False → None, т.е. не найден).
    """
    newservice_cmd = _fresh_import()
    update, context = _make_update_context(args_list)

    find_row_return = (2, {"ID": "BIZ-001"}) if biz_exists else None
    if create_result is None:
        create_result = {"ok": True, "service_id": "SVC-999", "error": None}

    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
         patch("business_core.sheets.find_row_by_id", return_value=find_row_return) as mock_find, \
         patch("business_core.service_manager.create_service_record",
               return_value=create_result) as mock_create:
        asyncio.run(newservice_cmd(update, context))

    return update, mock_find, mock_create


class TestNewserviceNoArgs(unittest.TestCase):
    """1. no args → rejected, create_service_record not called."""

    def test_no_args_rejected(self):
        update, mock_find, mock_create = _run([])
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)


class TestNewserviceFreeText(unittest.TestCase):
    """2, 14. Свободный текст (инцидент SVC-001) → rejected."""

    def test_incident_text_rejected(self):
        # Точная реконструкция инцидента: "/newservice завершён успешно."
        update, mock_find, mock_create = _run(["завершён", "успешно."])
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_incident_no_garbage_biz_id_or_name_leak(self):
        """Регрессия: убедиться, что create_service_record не получает
        'завершён'/'успешно.' ни в каком виде — вызов вообще не происходит."""
        update, mock_find, mock_create = _run(["завершён", "успешно."])
        mock_create.assert_not_called()
        # find_row_by_id тоже не должен был вызываться — отклонено раньше,
        # на этапе парсинга, до проверки существования biz_id.
        mock_find.assert_not_called()


class TestNewservicePositionalOnly(unittest.TestCase):
    """3. Positional-only ввод (BIZ-001 Услуга, без '=') → rejected."""

    def test_positional_only_rejected(self):
        update, mock_find, mock_create = _run(["BIZ-001", "Услуга"])
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_positional_mixed_with_kv_rejected(self):
        """Даже если один токен — валидный key=value, наличие ЛЮБОГО
        позиционного токена должно приводить к отказу."""
        update, mock_find, mock_create = _run(["biz_id=BIZ-001", "лишнее_слово"])
        mock_create.assert_not_called()


class TestNewserviceMissingFields(unittest.TestCase):
    """4, 5, 6. missing biz / missing name / blank name → rejected."""

    def test_missing_biz_rejected(self):
        update, mock_find, mock_create = _run(["name=Тест"])
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_missing_name_rejected(self):
        update, mock_find, mock_create = _run(["biz_id=BIZ-001"])
        mock_create.assert_not_called()

    def test_blank_name_rejected(self):
        # name="   " -> после _parse_kv_args это одна кавычка-строка из пробелов
        update, mock_find, mock_create = _run(['biz_id=BIZ-001', 'name="   "'])
        mock_create.assert_not_called()


class TestNewserviceNonexistentBiz(unittest.TestCase):
    """7. Несуществующий biz_id → rejected, create_service_record не вызван."""

    def test_nonexistent_biz_rejected(self):
        update, mock_find, mock_create = _run(
            ["biz_id=BIZ-DOES-NOT-EXIST", "name=Тест"], biz_exists=False
        )
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("BIZ-DOES-NOT-EXIST", msg)
        mock_find.assert_called_once_with("biz_registry", "BIZ-DOES-NOT-EXIST")


class TestNewserviceValidCreation(unittest.TestCase):
    """8, 9, 10. Валидный key=value ввод -> create_service_record вызван
    ровно один раз, optional-поля и алиасы передаются без изменений."""

    def test_valid_creation_calls_create_once(self):
        # Многословное значение передаётся так, как его реально разбивает
        # Telegram (наивный сплит по пробелам с кавычками из исходного
        # текста), а не как один pre-joined Python-элемент списка.
        update, mock_find, mock_create = _run(
            ["biz_id=BIZ-001", 'name="Тестовая', 'услуга"']
        )
        mock_create.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("SVC-999", msg)
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["service_name"], "Тестовая услуга")

    def test_optional_fields_passed_through(self):
        update, mock_find, mock_create = _run([
            "biz_id=BIZ-001", "name=Тест",
            "category=узаконение", "city=Алматы",
            "price_from=1500000", 'duration="3-4', 'месяца"',
        ])
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["service_category"], "узаконение")
        self.assertEqual(kwargs["city"], "Алматы")
        self.assertEqual(kwargs["price_from"], "1500000")
        self.assertEqual(kwargs["estimated_duration"], "3-4 месяца")

    def test_service_name_alias_preserved(self):
        """Алиас 'service_name=' (вместо 'name=') должен продолжать работать."""
        update, mock_find, mock_create = _run(
            ["biz_id=BIZ-001", 'service_name="Тест', 'через', 'алиас"']
        )
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["service_name"], "Тест через алиас")

    def test_biz_id_existence_checked_before_create(self):
        update, mock_find, mock_create = _run(["biz_id=BIZ-001", "name=Тест"])
        mock_find.assert_called_once_with("biz_registry", "BIZ-001")
        mock_create.assert_called_once()


class TestNewserviceUnknownKeys(unittest.TestCase):
    """11. Неизвестные key — текущая реализация их отклоняет (reject)."""

    def test_unknown_key_rejected(self):
        update, mock_find, mock_create = _run(
            ["biz_id=BIZ-001", "name=Тест", "totally_unknown_field=value"]
        )
        mock_create.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("totally_unknown_field", msg)


class TestNewserviceNoLiveApiInTests(unittest.TestCase):
    """12, 13. Ни один сценарий (валидный и невалидный) не должен
    обращаться к live Google API; create_service_record не вызывается
    ни при каком невалидном вводе."""

    def test_no_args_no_live_calls(self):
        # get_business_sheet не должен вообще вызываться на этапе parsing-отказа
        newservice_cmd = _fresh_import()
        update, context = _make_update_context([])
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet, \
             patch("business_core.service_manager.create_service_record") as mock_create:
            asyncio.run(newservice_cmd(update, context))
        mock_get_sheet.assert_not_called()
        mock_create.assert_not_called()

    def test_all_invalid_scenarios_never_call_create(self):
        scenarios = [
            [],
            ["завершён", "успешно."],
            ["BIZ-001", "Услуга"],
            ["name=Тест"],
            ["biz_id=BIZ-001"],
        ]
        for args_list in scenarios:
            with self.subTest(args=args_list):
                _, _, mock_create = _run(args_list)
                mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
