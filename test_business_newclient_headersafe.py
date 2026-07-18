"""
Phase 10.2B.4: Header-safe newclient_confirm() — mock tests.

Проверяет, что создание клиента через /newclient (people_registry)
формирует строку по ФАКТИЧЕСКИМ заголовкам листа, а не по позиции,
и что подтверждённое в Phase 10.2B.3 смещение
("active" -> Теплота, "тёплый" -> Комментарий, Biz IDs -> Company ID,
Primary Biz ID -> за пределы листа) больше не воспроизводится.

Все тесты полностью мокают business_core.sheets.get_business_sheet —
ни один тест не должен обращаться к live Google Sheets API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Полный порядок заголовков "как на проде до фикса" (константа BUSINESS_HEADERS)
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

# Та же самая, но с перемешанным порядком (не совпадает по позиции)
SHUFFLED_HEADERS = [
    "Primary Biz ID", "Passport / ID", "Citizenship", "Company ID", "Biz IDs",
    "Drive Folder ID", "Google Drive",
    "Комментарий", "Теплота", "Статус отношений",
    "Заметка касания", "Тип касания", "Следующее касание",
    "История", "Канал последнего контакта",
    "Дата последнего контакта", "Дата первого контакта",
    "Важные события", "День рождения",
    "Теги", "Специализация", "Кого знает", "Чем я полезен", "Чем полезен",
    "Источник", "Уровень доверия", "Бизнесы", "Подтип", "Тип",
    "Должность", "Компания", "Город", "Email", "Telegram",
    "WhatsApp", "Телефон 2", "Телефон", "Имя", "ФИО", "ID",
]


def _make_people_sheet(headers: list, existing_rows: list | None = None) -> MagicMock:
    """Мок листа PEOPLE_REGISTRY. Никаких реальных HTTP-вызовов."""
    sheet = MagicMock()
    sheet.row_values.return_value = list(headers)
    rows = existing_rows or []
    sheet.get_all_values.return_value = [list(headers)] + rows
    sheet.update.return_value = None
    return sheet


def _make_update_context(full_name="Иван Иванов", phone="+77771234567",
                          businesses="ТестБизнес", person_type="клиент"):
    update = MagicMock()
    update.message.text = "Подтверждаю"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    nc = {
        "full_name": full_name,
        "phone": phone,
        "businesses": businesses,
        "person_type": person_type,
    }
    # Phase 11J: newclient_confirm() читает только "nc_confirmed_snapshot"
    # (immutable snapshot, взятый в newclient_biz() до показа карточки
    # подтверждения) — "nc" оставлен тоже для полноты мока состояния.
    context.user_data = {
        "nc": dict(nc),
        "nc_confirmed_snapshot": dict(nc),
    }
    return update, context


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import newclient_confirm
    return newclient_confirm


def _run_newclient_confirm(sheet, find_existing_return=None, biz_id_resolved="BIZ-001"):
    """
    Запустить newclient_confirm с полностью замоканными зависимостями.
    Возвращает (update, context, sheet) для дальнейших проверок.
    """
    async def run():
        newclient_confirm = _fresh_import()
        update, context = _make_update_context()

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
             patch("business_core.business_builder.find_existing_person",
                   return_value=find_existing_return), \
             patch("business_core.business_builder.add_biz_id_to_person") as mock_add_biz, \
             patch("business_core.business_builder.update_person_drive_info") as mock_upd_drive, \
             patch("business_core.business_builder.save_client_drive_to_sheets") as mock_save_drive, \
             patch("business_core.business_builder.provision_client_drive",
                   return_value={"ok": False, "error": "Drive не задан для этого бизнеса"}), \
             patch("business_core.business_builder._get_biz_id_by_name",
                   return_value=biz_id_resolved):
            await newclient_confirm(update, context)

        return update, context, mock_add_biz, mock_upd_drive, mock_save_drive

    return asyncio.run(run())


class TestNewClientHeaderSafeStandardOrder(unittest.TestCase):
    """1, 3-9: стандартный порядок заголовков — значения в правильных колонках."""

    def setUp(self):
        self.sheet = _make_people_sheet(STANDARD_HEADERS)
        self.update, self.context, self.add_biz, self.upd_drive, self.save_drive = \
            _run_newclient_confirm(self.sheet, find_existing_return=None)

    def test_1_client_created(self):
        self.update.message.reply_text.assert_called_once()
        msg = self.update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("PRS-999", msg)

    def _written_row(self) -> dict:
        self.assertEqual(self.sheet.update.call_count, 1)
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_3_id_in_id_column(self):
        row = self._written_row()
        self.assertEqual(row["ID"], "PRS-999")

    def test_3_name_in_fio_column(self):
        row = self._written_row()
        self.assertEqual(row["ФИО"], "Иван Иванов")

    def test_4_relationship_status_active(self):
        row = self._written_row()
        self.assertEqual(row["Статус отношений"], "active")

    def test_5_warmth_value(self):
        row = self._written_row()
        self.assertEqual(row["Теплота"], "тёплый")

    def test_6_comment_not_warmth(self):
        row = self._written_row()
        self.assertEqual(row["Комментарий"], "")
        self.assertNotEqual(row["Комментарий"], "тёплый")

    def test_7_biz_ids_value(self):
        row = self._written_row()
        self.assertEqual(row["Biz IDs"], "BIZ-001")

    def test_8_primary_biz_id_value(self):
        row = self._written_row()
        self.assertEqual(row["Primary Biz ID"], "BIZ-001")

    def test_9_unknown_extra_columns_untouched(self):
        row = self._written_row()
        # поля, которым не присвоено значение в newclient_confirm, должны остаться пустыми
        for h in ("Company ID", "Citizenship", "Passport / ID", "Телефон 2",
                  "WhatsApp", "Email", "Город"):
            self.assertEqual(row[h], "", f"{h} должно быть пустым")

    def test_10_headers_read_once(self):
        self.assertEqual(self.sheet.row_values.call_count, 1)

    def test_11_append_called_once(self):
        self.assertEqual(self.sheet.update.call_count, 1)


class TestNewClientHeaderSafeShuffledOrder(unittest.TestCase):
    """2: результат не зависит от перестановки заголовков."""

    def setUp(self):
        self.sheet = _make_people_sheet(SHUFFLED_HEADERS)
        self.update, self.context, *_ = _run_newclient_confirm(
            self.sheet, find_existing_return=None
        )

    def _written_row(self) -> dict:
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(SHUFFLED_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_2_created_with_shuffled_headers(self):
        self.update.message.reply_text.assert_called_once()
        msg = self.update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_values_correct_despite_shuffle(self):
        row = self._written_row()
        self.assertEqual(row["ID"], "PRS-999")
        self.assertEqual(row["ФИО"], "Иван Иванов")
        self.assertEqual(row["Статус отношений"], "active")
        self.assertEqual(row["Теплота"], "тёплый")
        self.assertEqual(row["Комментарий"], "")
        self.assertEqual(row["Biz IDs"], "BIZ-001")
        self.assertEqual(row["Primary Biz ID"], "BIZ-001")


class TestNewClientNoShiftRegression(unittest.TestCase):
    """Regression: старое ошибочное смещение НЕ воспроизводится."""

    def setUp(self):
        self.sheet = _make_people_sheet(STANDARD_HEADERS)
        self.update, self.context, *_ = _run_newclient_confirm(
            self.sheet, find_existing_return=None
        )

    def _written_row(self) -> dict:
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_row_length_matches_headers(self):
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        self.assertLessEqual(len(values), len(STANDARD_HEADERS))

    def test_no_overflow_past_headers(self):
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        self.assertEqual(len(values), len(STANDARD_HEADERS))


class TestNewClientSameBizNoNewRow(unittest.TestCase):
    """12: SAME_BIZ не создаёт новую строку."""

    def test_same_biz_skips_append(self):
        sheet = _make_people_sheet(STANDARD_HEADERS)
        update, context, add_biz, upd_drive, save_drive = _run_newclient_confirm(
            sheet,
            find_existing_return={"prs_id": "PRS-001", "same_biz": True, "drive_url": ""},
        )
        self.assertEqual(sheet.update.call_count, 0)
        add_biz.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("уже существует", msg)


class TestNewClientOtherBizNoNewRow(unittest.TestCase):
    """13: OTHER_BIZ не создаёт новую строку, а обновляет связь."""

    def test_other_biz_updates_not_creates(self):
        sheet = _make_people_sheet(STANDARD_HEADERS)
        update, context, add_biz, upd_drive, save_drive = _run_newclient_confirm(
            sheet,
            find_existing_return={"prs_id": "PRS-002", "same_biz": False, "drive_url": ""},
            biz_id_resolved="BIZ-002",
        )
        self.assertEqual(sheet.update.call_count, 0)
        add_biz.assert_called_once_with("PRS-002", "BIZ-002")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("другом бизнесе", msg)


class TestNewClientMissingRequiredHeader(unittest.TestCase):
    """14, 15: отсутствие обязательного заголовка -> append не вызывается, ошибка пользователю."""

    def test_missing_biz_ids_header_blocks_append(self):
        headers_without_biz_ids = [h for h in STANDARD_HEADERS if h != "Biz IDs"]
        sheet = _make_people_sheet(headers_without_biz_ids)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0, "append не должен выполняться")
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("Biz IDs", msg)

    def test_missing_primary_biz_id_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Primary Biz ID"]
        sheet = _make_people_sheet(headers_without)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_missing_relationship_status_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Статус отношений"]
        sheet = _make_people_sheet(headers_without)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0)

    def test_missing_header_no_partial_write(self):
        """Убедиться, что при отсутствии заголовка sheet.update вообще не трогается
        (нет частичной/смещённой записи)."""
        headers_without = [h for h in STANDARD_HEADERS if h != "Комментарий"]
        sheet = _make_people_sheet(headers_without)

        _run_newclient_confirm(sheet, find_existing_return=None)

        sheet.update.assert_not_called()


class TestNewClientLiveHeadersSnapshot(unittest.TestCase):
    """Против реальных live-заголовков PEOPLE_REGISTRY (33 колонки, Phase 10.2B.3),
    у которых отсутствуют Biz IDs/Primary Biz ID и т.д. — append должен быть
    заблокирован (ожидаемое поведение: лучше явная ошибка, чем смещение)."""

    LIVE_HEADERS_33 = [
        "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
        "Telegram", "Email", "Город", "Компания", "Должность",
        "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
        "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
        "День рождения", "Важные события",
        "Дата первого контакта", "Дата последнего контакта",
        "Канал последнего контакта", "История",
        "Следующее касание", "Тип касания", "Заметка касания",
        "Статус отношений", "Теплота", "Комментарий",
    ]

    def test_live_snapshot_blocks_append_safely(self):
        sheet = _make_people_sheet(self.LIVE_HEADERS_33)
        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        sheet.update.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)


if __name__ == "__main__":
    unittest.main()
