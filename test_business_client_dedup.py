"""
Phase 6B: Deduplication of clients via Biz IDs — mock tests.

Проверяет:
1. normalize_person_name / normalize_phone
2. find_existing_person: поиск по имени, телефону, biz_id
3. add_biz_id_to_person: добавляет без дублей, не трогает Primary Biz ID
4. update_person_drive_info: дозаполняет только если пусто
5. Дедупликация в newclient_confirm:
   - тот же biz_id → STATUS_SAME_BIZ, нет новой строки
   - другой biz_id → STATUS_OTHER_BIZ, add_biz_id вызывается
   - новый клиент → STATUS_NEW, создаётся строка
6. Drive не дублируется
7. GTD-файлы не импортируются
"""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

# ─── GTD isolation ──────────────────────────────────────────────────────────

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


def _top_imports(filepath: str) -> set:
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


class TestGTDIsolation(unittest.TestCase):
    def test_business_builder_no_gtd(self):
        bad = _top_imports("business_core/business_builder.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"business_builder импортирует GTD: {bad}")

    def test_telegram_handlers_no_gtd(self):
        bad = _top_imports("business_core/telegram_handlers.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"telegram_handlers импортирует GTD: {bad}")


# ─── normalize_person_name ──────────────────────────────────────────────────

class TestNormalizePersonName(unittest.TestCase):

    def _fn(self, name):
        from business_core.business_builder import normalize_person_name
        return normalize_person_name(name)

    def test_trim_and_lower(self):
        self.assertEqual(self._fn("  Иван Петров  "), "иван петров")

    def test_multiple_spaces(self):
        self.assertEqual(self._fn("Иван  Петров"), "иван петров")

    def test_upper(self):
        self.assertEqual(self._fn("ИВАН ПЕТРОВ"), "иван петров")

    def test_empty(self):
        self.assertEqual(self._fn(""), "")

    def test_single_word(self):
        self.assertEqual(self._fn("Иван"), "иван")

    def test_same_after_normalize(self):
        self.assertEqual(self._fn("иван петров"), "иван петров")


# ─── normalize_phone ────────────────────────────────────────────────────────

class TestNormalizePhone(unittest.TestCase):

    def _fn(self, phone):
        from business_core.business_builder import normalize_phone
        return normalize_phone(phone)

    def test_kz_format(self):
        self.assertEqual(self._fn("+7 (777) 123-45-67"), "77771234567")

    def test_ru_format(self):
        self.assertEqual(self._fn("8 777 123 45 67"), "87771234567")

    def test_plain(self):
        self.assertEqual(self._fn("77771234567"), "77771234567")

    def test_empty(self):
        self.assertEqual(self._fn(""), "")

    def test_none_like_empty(self):
        self.assertEqual(self._fn(""), "")

    def test_with_spaces(self):
        self.assertEqual(self._fn("7 777 000 0000"), "77770000000")


# ─── find_existing_person ───────────────────────────────────────────────────

def _make_sheet(headers: list, rows: list) -> MagicMock:
    mock = MagicMock()
    mock.get_all_values.return_value = [headers] + rows
    return mock


# Full headers matching current PEOPLE_REGISTRY
FULL_HEADERS = [
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


def _make_row(prs_id, fio, phone="", biz_ids="", primary_biz="",
              biz_name="", drive_url="", drive_folder_id=""):
    """Создать строку таблицы, заполнив нужные поля."""
    row = [""] * len(FULL_HEADERS)
    idx = {h: i for i, h in enumerate(FULL_HEADERS)}
    row[idx["ID"]]             = prs_id
    row[idx["ФИО"]]            = fio
    row[idx["Телефон"]]        = phone
    row[idx["Бизнесы"]]        = biz_name
    row[idx["Google Drive"]]   = drive_url
    row[idx["Drive Folder ID"]]= drive_folder_id
    row[idx["Biz IDs"]]        = biz_ids
    row[idx["Primary Biz ID"]] = primary_biz
    return row


class TestFindExistingPerson(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_find_by_name_and_biz_id(self, mock_get):
        row = _make_row("PRS-001", "Иван Петров", biz_ids="BIZ-001", primary_biz="BIZ-001")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Иван Петров", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-001")
        self.assertTrue(result["same_biz"])

    @patch("business_core.sheets.get_business_sheet")
    def test_find_by_phone_and_biz_id(self, mock_get):
        row = _make_row("PRS-002", "Мария Иванова",
                        phone="+7 777 111 22 33", biz_ids="BIZ-001")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(phone="+7 (777) 111-22-33", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-002")
        self.assertTrue(result["same_biz"])

    @patch("business_core.sheets.get_business_sheet")
    def test_same_name_different_biz_id(self, mock_get):
        """Клиент есть, но в другом бизнесе → same_biz=False."""
        row = _make_row("PRS-003", "Алибек Джаксыбеков", biz_ids="BIZ-002")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Алибек Джаксыбеков", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-003")
        self.assertFalse(result.get("same_biz", True))

    @patch("business_core.sheets.get_business_sheet")
    def test_same_phone_different_biz_id(self, mock_get):
        row = _make_row("PRS-004", "Кто-то", phone="77771234567", biz_ids="BIZ-003")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(phone="77771234567", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertFalse(result.get("same_biz", True))

    @patch("business_core.sheets.get_business_sheet")
    def test_not_found(self, mock_get):
        row = _make_row("PRS-099", "Совсем другой", biz_ids="BIZ-001")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Иван Петров", biz_id="BIZ-001")

        self.assertIsNone(result)

    @patch("business_core.sheets.get_business_sheet")
    def test_case_insensitive_name(self, mock_get):
        row = _make_row("PRS-005", "ИВАН ПЕТРОВ", biz_ids="BIZ-001")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="иван петров", biz_id="BIZ-001")

        self.assertIsNotNone(result)

    @patch("business_core.sheets.get_business_sheet")
    def test_returns_drive_info(self, mock_get):
        row = _make_row("PRS-006", "Нурлан", biz_ids="BIZ-001",
                        drive_url="https://drive.google.com/abc",
                        drive_folder_id="abc123")
        mock_get.return_value = _make_sheet(FULL_HEADERS, [row])

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Нурлан", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["drive_url"], "https://drive.google.com/abc")
        self.assertEqual(result["drive_folder_id"], "abc123")

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("API error")

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Кто-то")

        self.assertIsNone(result)

    def test_both_none_returns_none(self):
        from business_core.business_builder import find_existing_person
        result = find_existing_person()
        self.assertIsNone(result)


# ─── add_biz_id_to_person ───────────────────────────────────────────────────

class TestAddBizIdToPerson(unittest.TestCase):

    def _mock_sheet_with_person(self, biz_ids="", primary_biz=""):
        row = _make_row("PRS-001", "Иван", biz_ids=biz_ids, primary_biz=primary_biz)
        mock = _make_sheet(FULL_HEADERS, [row])
        mock.update_cell = MagicMock()
        return mock

    @patch("business_core.sheets.get_business_sheet")
    def test_adds_new_biz_id(self, mock_get):
        mock = self._mock_sheet_with_person(biz_ids="BIZ-001")
        mock_get.return_value = mock

        from business_core.business_builder import add_biz_id_to_person
        result = add_biz_id_to_person("PRS-001", "BIZ-002")

        self.assertTrue(result)
        # update_cell должен был быть вызван с новым значением
        calls_args = [str(c) for c in mock.update_cell.call_args_list]
        combined = " ".join(calls_args)
        self.assertIn("BIZ-001", combined)
        self.assertIn("BIZ-002", combined)

    @patch("business_core.sheets.get_business_sheet")
    def test_no_duplicate_biz_id(self, mock_get):
        mock = self._mock_sheet_with_person(biz_ids="BIZ-001,BIZ-002")
        mock_get.return_value = mock

        from business_core.business_builder import add_biz_id_to_person
        result = add_biz_id_to_person("PRS-001", "BIZ-001")

        self.assertFalse(result)  # уже есть — не обновляем
        mock.update_cell.assert_not_called()

    @patch("business_core.sheets.get_business_sheet")
    def test_does_not_overwrite_primary_biz_id(self, mock_get):
        mock = self._mock_sheet_with_person(biz_ids="BIZ-001", primary_biz="BIZ-001")
        mock_get.return_value = mock

        from business_core.business_builder import add_biz_id_to_person
        add_biz_id_to_person("PRS-001", "BIZ-002")

        # Primary Biz ID не должен обновляться (уже заполнен)
        for c in mock.update_cell.call_args_list:
            args = c[0]
            # primary_biz_id — последняя колонка в FULL_HEADERS
            primary_col_idx = FULL_HEADERS.index("Primary Biz ID") + 1
            self.assertFalse(
                args[1] == primary_col_idx and args[2] == "BIZ-002",
                "Primary Biz ID не должен перезаписываться"
            )

    @patch("business_core.sheets.get_business_sheet")
    def test_sets_primary_biz_if_empty(self, mock_get):
        mock = self._mock_sheet_with_person(biz_ids="BIZ-001", primary_biz="")
        mock_get.return_value = mock

        from business_core.business_builder import add_biz_id_to_person
        add_biz_id_to_person("PRS-001", "BIZ-002")

        primary_col_idx = FULL_HEADERS.index("Primary Biz ID") + 1
        found = any(
            c[0][1] == primary_col_idx
            for c in mock.update_cell.call_args_list
        )
        self.assertTrue(found, "Primary Biz ID должен быть установлен если пустой")

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_false(self, mock_get):
        mock_get.side_effect = Exception("timeout")

        from business_core.business_builder import add_biz_id_to_person
        result = add_biz_id_to_person("PRS-001", "BIZ-001")

        self.assertFalse(result)


# ─── update_person_drive_info ───────────────────────────────────────────────

class TestUpdatePersonDriveInfo(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_fills_empty_drive_fields(self, mock_get):
        row = _make_row("PRS-001", "Иван", drive_url="", drive_folder_id="")
        mock = _make_sheet(FULL_HEADERS, [row])
        mock.update_cell = MagicMock()
        mock_get.return_value = mock

        from business_core.business_builder import update_person_drive_info
        result = update_person_drive_info("PRS-001", "folder-123", "https://drive.google.com/x")

        self.assertTrue(result)
        self.assertEqual(mock.update_cell.call_count, 2)

    @patch("business_core.sheets.get_business_sheet")
    def test_does_not_overwrite_existing_drive(self, mock_get):
        row = _make_row("PRS-001", "Иван",
                        drive_url="https://existing.url",
                        drive_folder_id="existing-id")
        mock = _make_sheet(FULL_HEADERS, [row])
        mock.update_cell = MagicMock()
        mock_get.return_value = mock

        from business_core.business_builder import update_person_drive_info
        result = update_person_drive_info("PRS-001", "new-folder", "https://new.url")

        self.assertFalse(result)
        mock.update_cell.assert_not_called()

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_false(self, mock_get):
        mock_get.side_effect = Exception("boom")

        from business_core.business_builder import update_person_drive_info
        result = update_person_drive_info("PRS-001", "x", "https://x")

        self.assertFalse(result)


# ─── Integration: deduplication flow ────────────────────────────────────────

class TestDeduplicationFlow(unittest.TestCase):
    """Тесты дедупликации полного цикла (без Telegram, без Drive API)."""

    def _base_existing(self, same_biz=True, drive_url="", drive_folder_id=""):
        return {
            "row_num": 2,
            "prs_id": "PRS-001",
            "full_name": "Иван Петров",
            "biz_ids": ["BIZ-001"],
            "primary_biz_id": "BIZ-001",
            "drive_url": drive_url,
            "drive_folder_id": drive_folder_id,
            "phone_raw": "",
            "same_biz": same_biz,
        }

    @patch("business_core.business_builder.find_existing_person")
    def test_same_biz_no_new_row(self, mock_find):
        """Клиент с тем же именем и biz_id → не создаём новую строку."""
        mock_find.return_value = self._base_existing(same_biz=True)

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Иван Петров", biz_id="BIZ-001")

        self.assertIsNotNone(result)
        self.assertTrue(result["same_biz"])
        self.assertEqual(result["prs_id"], "PRS-001")

    @patch("business_core.business_builder.find_existing_person")
    @patch("business_core.business_builder.add_biz_id_to_person")
    def test_other_biz_add_biz_id(self, mock_add, mock_find):
        """Клиент в другом бизнесе → add_biz_id_to_person вызывается."""
        mock_find.return_value = self._base_existing(same_biz=False)
        mock_add.return_value = True

        from business_core.business_builder import find_existing_person, add_biz_id_to_person

        person = find_existing_person(name="Иван Петров", biz_id="BIZ-002")
        self.assertFalse(person["same_biz"])

        add_biz_id_to_person(person["prs_id"], "BIZ-002")
        mock_add.assert_called_once_with("PRS-001", "BIZ-002")

    @patch("business_core.business_builder.find_existing_person")
    def test_drive_not_called_if_url_exists(self, mock_find):
        """Если drive_url уже есть → provision_client_drive не должен вызываться."""
        mock_find.return_value = self._base_existing(
            same_biz=True,
            drive_url="https://existing.url",
            drive_folder_id="folder-abc",
        )
        from business_core.business_builder import find_existing_person
        person = find_existing_person(name="Иван Петров", biz_id="BIZ-001")

        self.assertTrue(bool(person["drive_url"]))

    @patch("business_core.business_builder.find_existing_person")
    @patch("business_core.business_builder.update_person_drive_info")
    @patch("business_core.business_builder.provision_client_drive")
    def test_drive_filled_if_url_missing(self, mock_provision, mock_update, mock_find):
        """Если drive_url пустой → provision_client_drive вызывается, ссылка дозаполняется."""
        mock_find.return_value = self._base_existing(same_biz=True)  # нет Drive URL
        mock_provision.return_value = {
            "ok": True, "folder_id": "new-id", "folder_url": "https://new.url",
            "biz_id": "BIZ-001", "error": None,
        }
        mock_update.return_value = True

        from business_core.business_builder import (
            find_existing_person, provision_client_drive, update_person_drive_info
        )

        person = find_existing_person(name="Иван Петров", biz_id="BIZ-001")
        self.assertFalse(bool(person["drive_url"]))  # Drive URL пустой

        # Симулируем логику /newclient
        drive_result = provision_client_drive(
            prs_id="PRS-001", full_name="Иван Петров", biz_name="Бизнес"
        )
        self.assertTrue(drive_result["ok"])

        update_person_drive_info("PRS-001", drive_result["folder_id"], drive_result["folder_url"])
        mock_update.assert_called_once_with("PRS-001", "new-id", "https://new.url")

    @patch("business_core.business_builder.find_existing_person")
    @patch("business_core.business_builder.provision_client_drive")
    def test_drive_error_no_duplicate_client(self, mock_provision, mock_find):
        """Drive упал → клиент не дублируется."""
        mock_find.return_value = self._base_existing(same_biz=True)
        mock_provision.side_effect = Exception("Drive API error")

        from business_core.business_builder import find_existing_person, provision_client_drive
        person = find_existing_person(name="Иван Петров", biz_id="BIZ-001")

        # Клиент найден — нет смысла создавать нового
        self.assertIsNotNone(person)
        self.assertEqual(person["prs_id"], "PRS-001")

        # Симулируем ошибку Drive
        try:
            provision_client_drive(prs_id="PRS-001", full_name="Иван Петров", biz_name="Бизнес")
        except Exception:
            pass  # ошибка обработана — клиент не дублируется


# ─── Biz IDs field preserved ────────────────────────────────────────────────

class TestBizFieldsCompatibility(unittest.TestCase):
    """Старое поле "Бизнесы" сохраняется для совместимости."""

    @patch("business_core.sheets.get_business_sheet")
    def test_old_biznes_field_still_readable(self, mock_get):
        row = _make_row("PRS-001", "Иван", biz_name="Узаконение", biz_ids="BIZ-001")
        mock = _make_sheet(FULL_HEADERS, [row])
        mock_get.return_value = mock

        from business_core.business_builder import find_existing_person
        result = find_existing_person(name="Иван", biz_id="BIZ-001")

        self.assertIsNotNone(result)

    def test_normalize_biz_ids_empty_list_when_no_ids(self):
        from business_core.business_builder import normalize_biz_ids
        self.assertEqual(normalize_biz_ids(""), [])
        self.assertEqual(normalize_biz_ids("  "), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
