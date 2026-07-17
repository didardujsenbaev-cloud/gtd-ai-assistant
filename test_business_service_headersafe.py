"""
Phase 10.2B.6B: Header-safe create_service_record() — mock tests.

Проверяет, что создание услуги через /newservice (SERVICE_CATALOG)
формирует строку по ФАКТИЧЕСКИМ заголовкам листа, а не по позиции.

Все тесты полностью мокают business_core.sheets.get_business_sheet —
ни один тест не должен обращаться к live Google Sheets API.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

STANDARD_HEADERS = [
    "ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
    "Цена мин", "Цена макс", "Срок", "Описание",
    "Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
    "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
    "Документы от клиента", "Документы наши",
    "Чек-лист производства", "Чек-лист закрытия",
    "Риски", "Шаблоны", "Инструкция", "Комментарий",
    "Service Name", "Service Category", "Object Type", "Client Type",
    "What Included", "What Not Included", "Currency",
    "Required Documents", "Default Roadmap Template ID",
    "Contractors Needed", "Materials IDs", "Created At", "Last Updated",
]

SHUFFLED_HEADERS = list(reversed(STANDARD_HEADERS))

# Аномальная pre-Phase-10.2B.6A схема: первые 28 заголовков canonical,
# последние 13 (Phase 8A) — пустые строки (воспроизводит реальное
# live-состояние SERVICE_CATALOG до миграции Phase 10.2B.6A).
LEGACY_ANOMALOUS_HEADERS = STANDARD_HEADERS[:28] + [""] * 13


def _make_service_sheet(headers: list, existing_rows: list | None = None) -> MagicMock:
    sheet = MagicMock()
    sheet.row_values.return_value = list(headers)
    rows = existing_rows or []
    sheet.get_all_values.return_value = [list(headers)] + rows
    sheet.update.return_value = None
    return sheet


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.service_manager import create_service_record
    return create_service_record


DEFAULT_ARGS = dict(
    biz_id="BIZ-001",
    service_name="Тестовая услуга",
    service_category="узаконение",
    city="Алматы",
    object_type="частный дом",
    client_type="physical_person",
    description="описание услуги",
    what_included="все включено",
    what_not_included="ничего не включено",
    price_from="1000000",
    price_to="2000000",
    currency="KZT",
    estimated_duration="3-4 месяца",
    required_documents="паспорт",
    default_roadmap_template_id="RMT-TEST-001",
    risks="риски есть",
    contractors_needed="да",
    materials_ids="MAT-001",
    status="active",
    notes="комментарий",
)


def _run_create(sheet, service_id="SVC-777", **overrides):
    create_service_record = _fresh_import()
    args = {**DEFAULT_ARGS, **overrides}
    with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
         patch("business_core.service_manager.generate_service_id", return_value=service_id):
        result = create_service_record(**args)
    return result, sheet


class TestServiceHeaderSafeStandardOrder(unittest.TestCase):
    """1, 9-13: канонический порядок заголовков."""

    def setUp(self):
        self.sheet = _make_service_sheet(STANDARD_HEADERS)
        self.result, _ = _run_create(self.sheet)

    def _written_row(self) -> dict:
        self.assertEqual(self.sheet.update.call_count, 1)  # 10. append ровно один раз
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_1_created_ok(self):
        self.assertTrue(self.result["ok"])
        self.assertEqual(self.result["service_id"], "SVC-777")

    def test_9_duplicated_fields_get_same_value(self):
        row = self._written_row()
        self.assertEqual(row["Название"], "Тестовая услуга")
        self.assertEqual(row["Service Name"], "Тестовая услуга")
        self.assertEqual(row["Документы от клиента"], "паспорт")
        self.assertEqual(row["Required Documents"], "паспорт")
        self.assertEqual(row["Шаблоны"], "RMT-TEST-001")
        self.assertEqual(row["Default Roadmap Template ID"], "RMT-TEST-001")

    def test_values_in_correct_columns(self):
        row = self._written_row()
        self.assertEqual(row["ID"], "SVC-777")
        self.assertEqual(row["Бизнес ID"], "BIZ-001")
        self.assertEqual(row["Slug"], "тестовая_услуга")
        self.assertEqual(row["Статус"], "active")
        self.assertEqual(row["Город"], "Алматы")
        self.assertEqual(row["Цена мин"], "1000000")
        self.assertEqual(row["Цена макс"], "2000000")
        self.assertEqual(row["Срок"], "3-4 месяца")
        self.assertEqual(row["Описание"], "описание услуги")
        self.assertEqual(row["Риски"], "риски есть")
        self.assertEqual(row["Комментарий"], "комментарий")
        self.assertEqual(row["Service Category"], "узаконение")
        self.assertEqual(row["Object Type"], "частный дом")
        self.assertEqual(row["Client Type"], "physical_person")
        self.assertEqual(row["What Included"], "все включено")
        self.assertEqual(row["What Not Included"], "ничего не включено")
        self.assertEqual(row["Currency"], "KZT")
        self.assertEqual(row["Contractors Needed"], "да")
        self.assertEqual(row["Materials IDs"], "MAT-001")

    def test_8_optional_empty_fields_stay_empty(self):
        row = self._written_row()
        for h in ("Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
                  "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
                  "Документы наши", "Чек-лист производства",
                  "Чек-лист закрытия", "Инструкция"):
            self.assertEqual(row[h], "", f"{h} должно быть пустым")

    def test_11_row_length_matches_headers(self):
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        self.assertEqual(len(values), len(STANDARD_HEADERS))

    def test_13_created_at_equals_last_updated(self):
        row = self._written_row()
        self.assertNotEqual(row["Created At"], "")
        self.assertEqual(row["Created At"], row["Last Updated"])

    def test_10_headers_read_once(self):
        self.assertEqual(self.sheet.row_values.call_count, 1)


class TestServiceHeaderSafeShuffledOrder(unittest.TestCase):
    """2. Shuffled headers — результат не зависит от порядка."""

    def setUp(self):
        self.sheet = _make_service_sheet(SHUFFLED_HEADERS)
        self.result, _ = _run_create(self.sheet)

    def _written_row(self) -> dict:
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(SHUFFLED_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_created_with_shuffled_headers(self):
        self.assertTrue(self.result["ok"])

    def test_values_and_duplicates_correct_despite_shuffle(self):
        row = self._written_row()
        self.assertEqual(row["ID"], "SVC-777")
        self.assertEqual(row["Бизнес ID"], "BIZ-001")
        self.assertEqual(row["Название"], "Тестовая услуга")
        self.assertEqual(row["Service Name"], "Тестовая услуга")
        self.assertEqual(row["Документы от клиента"], "паспорт")
        self.assertEqual(row["Required Documents"], "паспорт")
        self.assertEqual(row["Шаблоны"], "RMT-TEST-001")
        self.assertEqual(row["Default Roadmap Template ID"], "RMT-TEST-001")


class TestServiceHeaderSafeExtraColumnStart(unittest.TestCase):
    """3. Extra header в начале."""

    def setUp(self):
        self.headers = ["Extra Legacy Col"] + STANDARD_HEADERS
        self.sheet = _make_service_sheet(self.headers)
        self.result, _ = _run_create(self.sheet)

    def test_ok_and_extra_col_untouched(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Extra Legacy Col"]], "")
        self.assertEqual(values[idx["ID"]], "SVC-777")


class TestServiceHeaderSafeExtraColumnMiddle(unittest.TestCase):
    """4. Extra header в середине."""

    def setUp(self):
        self.headers = STANDARD_HEADERS[:20] + ["Middle Extra Col"] + STANDARD_HEADERS[20:]
        self.sheet = _make_service_sheet(self.headers)
        self.result, _ = _run_create(self.sheet)

    def test_ok_and_values_still_correct(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Middle Extra Col"]], "")
        self.assertEqual(values[idx["Currency"]], "KZT")
        self.assertEqual(values[idx["Last Updated"]] != "", True)


class TestServiceHeaderSafeExtraColumnEnd(unittest.TestCase):
    """5. Extra header в конце."""

    def setUp(self):
        self.headers = STANDARD_HEADERS + ["Trailing Extra Col"]
        self.sheet = _make_service_sheet(self.headers)
        self.result, _ = _run_create(self.sheet)

    def test_ok_and_trailing_col_empty(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Trailing Extra Col"]], "")
        self.assertEqual(values[idx["Last Updated"]] != "", True)


class TestServiceHeaderSafeMissingRequiredHeader(unittest.TestCase):
    """6. Отсутствующий обязательный заголовок -> ValueError, append не вызван."""

    def test_missing_currency_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Currency"]
        sheet = _make_service_sheet(headers_without)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        self.assertIn("Currency", result["error"])
        sheet.update.assert_not_called()

    def test_missing_service_name_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Service Name"]
        sheet = _make_service_sheet(headers_without)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        sheet.update.assert_not_called()

    def test_missing_header_no_partial_write(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Materials IDs"]
        sheet = _make_service_sheet(headers_without)
        _run_create(sheet)
        sheet.update.assert_not_called()


class TestServiceHeaderSafeDuplicateHeader(unittest.TestCase):
    """7. Duplicate non-empty header -> ValueError, append не вызван."""

    def test_duplicate_header_blocks_append(self):
        headers = STANDARD_HEADERS + ["Currency"]  # "Currency" дублируется
        sheet = _make_service_sheet(headers)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        self.assertIn("Currency", result["error"])
        sheet.update.assert_not_called()


class TestServiceHeaderSafeIdAndDateGeneration(unittest.TestCase):
    """12, 13, 14: ID и дата генерируются ровно один раз."""

    def test_generate_service_id_called_once(self):
        sheet = _make_service_sheet(STANDARD_HEADERS)
        create_service_record = _fresh_import()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.service_manager.generate_service_id",
                   return_value="SVC-555") as mock_gen:
            result = create_service_record(**DEFAULT_ARGS)
        mock_gen.assert_called_once()
        self.assertEqual(result["service_id"], "SVC-555")

    def test_status_normalization_unchanged(self):
        sheet = _make_service_sheet(STANDARD_HEADERS)
        result, sheet = _run_create(sheet, status="unknown_status")
        self.assertTrue(result["ok"])
        kwargs = sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        self.assertEqual(values[idx["Статус"]], "active")  # normalize_service_status fallback


class TestServiceHeaderSafeLegacyAnomalousSchemaRegression(unittest.TestCase):
    """
    Regression: воспроизводит реальную live pre-Phase-10.2B.6A аномалию
    (первые 28 заголовков canonical, последние 13 — пустые строки).
    Функция должна fail-safe остановиться, НЕ пытаться positional fallback,
    и не вызывать append.
    """

    def test_legacy_anomalous_schema_blocks_append_safely(self):
        sheet = _make_service_sheet(LEGACY_ANOMALOUS_HEADERS)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])
        sheet.update.assert_not_called()

    def test_legacy_anomalous_schema_no_positional_data_written(self):
        sheet = _make_service_sheet(LEGACY_ANOMALOUS_HEADERS)
        _run_create(sheet)
        # ни append_business_row (через sheet.update), ни какая-либо иная
        # запись не должны были быть вызваны
        sheet.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
