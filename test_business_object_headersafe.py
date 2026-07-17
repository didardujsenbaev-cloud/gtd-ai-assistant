"""
Phase 10.2B.5: Header-safe create_object_record() — mock tests.

Проверяет, что создание объекта через /newobject (OBJECT_REGISTRY)
формирует строку по ФАКТИЧЕСКИМ заголовкам листа, а не по позиции.

Все тесты полностью мокают business_core.sheets.get_business_sheet —
ни один тест не должен обращаться к live Google Sheets API.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

STANDARD_HEADERS = [
    "OBJ ID", "Client ID", "Biz ID", "City", "Address",
    "Cadastral Number", "Area m2", "Object Type", "Object Status",
    "Current Service ID", "Roadmap ID", "Drive Folder ID", "Google Drive",
    "Notes", "Created At", "Last Updated",
]

SHUFFLED_HEADERS = [
    "Last Updated", "Created At", "Notes", "Google Drive", "Drive Folder ID",
    "Roadmap ID", "Current Service ID", "Object Status", "Object Type",
    "Area m2", "Cadastral Number", "Address", "City", "Biz ID",
    "Client ID", "OBJ ID",
]


def _make_object_sheet(headers: list, existing_rows: list | None = None) -> MagicMock:
    sheet = MagicMock()
    sheet.row_values.return_value = list(headers)
    rows = existing_rows or []
    sheet.get_all_values.return_value = [list(headers)] + rows
    sheet.update.return_value = None
    return sheet


def _fresh_import():
    import sys
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.business_builder import create_object_record
    return create_object_record


DEFAULT_ARGS = dict(
    client_id="PRS-777",
    biz_id="BIZ-001",
    city="Алматы",
    address="ул. Тестовая 1",
    cadastral_number="12:34:56",
    area_m2="120",
    object_type="частный дом",
    object_status="new",
    current_service_id="SVC-001",
    notes="test notes",
)


def _run_create(sheet, obj_id="OBJ-777", **overrides):
    create_object_record = _fresh_import()
    args = {**DEFAULT_ARGS, **overrides}
    with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
         patch("business_core.business_builder.generate_object_id", return_value=obj_id):
        result = create_object_record(**args)
    return result, sheet


class TestObjectHeaderSafeStandardOrder(unittest.TestCase):
    """1, 9-11: канонический порядок заголовков."""

    def setUp(self):
        self.sheet = _make_object_sheet(STANDARD_HEADERS)
        self.result, _ = _run_create(self.sheet)

    def _written_row(self) -> dict:
        self.assertEqual(self.sheet.update.call_count, 1)  # 10. append ровно один раз
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_1_created_ok(self):
        self.assertTrue(self.result["ok"])
        self.assertEqual(self.result["obj_id"], "OBJ-777")

    def test_9_values_in_correct_columns(self):
        row = self._written_row()
        self.assertEqual(row["OBJ ID"], "OBJ-777")
        self.assertEqual(row["Client ID"], "PRS-777")
        self.assertEqual(row["Biz ID"], "BIZ-001")
        self.assertEqual(row["City"], "Алматы")
        self.assertEqual(row["Address"], "ул. Тестовая 1")
        self.assertEqual(row["Cadastral Number"], "12:34:56")
        self.assertEqual(row["Area m2"], "120")
        self.assertEqual(row["Object Type"], "частный дом")
        self.assertEqual(row["Object Status"], "new")
        self.assertEqual(row["Current Service ID"], "SVC-001")
        self.assertEqual(row["Roadmap ID"], "")
        self.assertEqual(row["Notes"], "test notes")

    def test_10_headers_read_once(self):
        self.assertEqual(self.sheet.row_values.call_count, 1)

    def test_11_append_called_once(self):
        self.assertEqual(self.sheet.update.call_count, 1)


class TestObjectHeaderSafeShuffledOrder(unittest.TestCase):
    """2. Переставленные заголовки — результат не зависит от порядка."""

    def setUp(self):
        self.sheet = _make_object_sheet(SHUFFLED_HEADERS)
        self.result, _ = _run_create(self.sheet)

    def _written_row(self) -> dict:
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(SHUFFLED_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def test_created_with_shuffled_headers(self):
        self.assertTrue(self.result["ok"])

    def test_values_correct_despite_shuffle(self):
        row = self._written_row()
        self.assertEqual(row["OBJ ID"], "OBJ-777")
        self.assertEqual(row["Client ID"], "PRS-777")
        self.assertEqual(row["Biz ID"], "BIZ-001")
        self.assertEqual(row["City"], "Алматы")
        self.assertEqual(row["Address"], "ул. Тестовая 1")
        self.assertEqual(row["Object Status"], "new")


class TestObjectHeaderSafeExtraColumnStart(unittest.TestCase):
    """3. Дополнительная колонка в НАЧАЛЕ."""

    def setUp(self):
        headers = ["Extra Legacy Col"] + STANDARD_HEADERS
        self.sheet = _make_object_sheet(headers)
        self.result, _ = _run_create(self.sheet)
        self.headers = headers

    def test_ok_and_extra_col_untouched(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Extra Legacy Col"]], "")
        self.assertEqual(values[idx["OBJ ID"]], "OBJ-777")
        self.assertEqual(values[idx["City"]], "Алматы")


class TestObjectHeaderSafeExtraColumnMiddle(unittest.TestCase):
    """4. Дополнительная колонка в СЕРЕДИНЕ."""

    def setUp(self):
        headers = STANDARD_HEADERS[:5] + ["Middle Extra Col"] + STANDARD_HEADERS[5:]
        self.sheet = _make_object_sheet(headers)
        self.result, _ = _run_create(self.sheet)
        self.headers = headers

    def test_ok_and_values_still_correct(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Middle Extra Col"]], "")
        self.assertEqual(values[idx["Cadastral Number"]], "12:34:56")
        self.assertEqual(values[idx["Area m2"]], "120")
        self.assertEqual(values[idx["Last Updated"]] != "", True)


class TestObjectHeaderSafeExtraColumnEnd(unittest.TestCase):
    """5. Дополнительная колонка в КОНЦЕ."""

    def setUp(self):
        headers = STANDARD_HEADERS + ["Trailing Extra Col"]
        self.sheet = _make_object_sheet(headers)
        self.result, _ = _run_create(self.sheet)
        self.headers = headers

    def test_ok_and_trailing_col_empty(self):
        self.assertTrue(self.result["ok"])
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(self.headers)}
        self.assertEqual(values[idx["Trailing Extra Col"]], "")
        self.assertEqual(values[idx["Last Updated"]] != "", True)


class TestObjectHeaderSafeMissingRequiredHeader(unittest.TestCase):
    """6. Отсутствующий обязательный заголовок -> append не вызывается, ok=False."""

    def test_missing_address_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Address"]
        sheet = _make_object_sheet(headers_without)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        self.assertIn("Address", result["error"])
        sheet.update.assert_not_called()

    def test_missing_biz_id_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Biz ID"]
        sheet = _make_object_sheet(headers_without)
        result, _ = _run_create(sheet)

        self.assertFalse(result["ok"])
        sheet.update.assert_not_called()

    def test_missing_header_no_partial_write(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Notes"]
        sheet = _make_object_sheet(headers_without)
        _run_create(sheet)
        sheet.update.assert_not_called()


class TestObjectHeaderSafeDuplicateHeader(unittest.TestCase):
    """7. Duplicate header — row_from_header_map должен использовать первое
    вхождение и не падать (get_header_index_map: побеждает первое вхождение)."""

    def test_duplicate_header_does_not_crash(self):
        headers = STANDARD_HEADERS + ["City"]  # City дублируется в конце
        sheet = _make_object_sheet(headers)
        result, _ = _run_create(sheet)

        self.assertTrue(result["ok"])
        kwargs = sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        # первое вхождение "City" (индекс 3) получает значение,
        # дубликат в конце остаётся пустым
        idx_first_city = STANDARD_HEADERS.index("City")
        self.assertEqual(values[idx_first_city], "Алматы")
        self.assertEqual(values[len(headers) - 1], "")


class TestObjectHeaderSafeEmptyOptionalFields(unittest.TestCase):
    """8. Пустые optional-поля остаются пустыми."""

    def test_optional_fields_empty(self):
        sheet = _make_object_sheet(STANDARD_HEADERS)
        result, _ = _run_create(
            sheet,
            cadastral_number="", area_m2="", object_type="",
            current_service_id="", notes="",
        )
        self.assertTrue(result["ok"])
        kwargs = sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        for h in ("Cadastral Number", "Area m2", "Object Type",
                  "Current Service ID", "Notes", "Drive Folder ID", "Google Drive"):
            self.assertEqual(values[idx[h]], "", f"{h} должно быть пустым")


class TestObjectHeaderSafeIdAndDriveUnchanged(unittest.TestCase):
    """11. Существующая логика ID и Drive не меняется — generate_object_id
    и передаваемые drive_folder_id/google_drive_url используются как раньше."""

    def test_generate_object_id_called_and_used(self):
        sheet = _make_object_sheet(STANDARD_HEADERS)
        create_object_record = _fresh_import()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.business_builder.generate_object_id",
                   return_value="OBJ-555") as mock_gen:
            result = create_object_record(**DEFAULT_ARGS)
        mock_gen.assert_called_once()
        self.assertEqual(result["obj_id"], "OBJ-555")

    def test_drive_fields_passed_through(self):
        sheet = _make_object_sheet(STANDARD_HEADERS)
        result, _ = _run_create(
            sheet,
            drive_folder_id="FOLDER-XYZ",
            google_drive_url="https://drive.google.com/drive/folders/FOLDER-XYZ",
        )
        self.assertTrue(result["ok"])
        kwargs = sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        self.assertEqual(values[idx["Drive Folder ID"]], "FOLDER-XYZ")
        self.assertEqual(values[idx["Google Drive"]],
                          "https://drive.google.com/drive/folders/FOLDER-XYZ")


if __name__ == "__main__":
    unittest.main()
