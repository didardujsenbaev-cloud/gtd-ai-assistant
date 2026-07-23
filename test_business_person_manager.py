"""
Tests for Phase 23D-1 — Person Manager Foundation
(business_core/person_manager.py).

Covers create/update/archive/find/list/duplicate-detection,
normalization, status validation, honest contracts, idempotency, and
regression guards (business_builder.py delegators still work,
telegram_handlers.py untouched, no GTD/Organization/Work Execution
coupling). No live Sheets writes — mocks only, per
ENGINEERING_STANDARDS.md Testing Standards.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

PEOPLE_HEADERS = [
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

PERSON_ROW = [
    "PRS-001", "Иван Иванов", "Иван", "77071234567", "", "",
    "", "", "", "", "",
    "сотрудник", "", "", "средний", "",
    "", "", "", "", "",
    "", "",
    "2026-01-01", "2026-01-01",
    "", "",
    "", "", "",
    "active", "", "",
    "", "",
    "BIZ-001", "", "", "", "BIZ-001",
]


def _fresh_pm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.person_manager")


def _make_sheet(headers=None, row=None, row_num=2):
    headers = headers if headers is not None else PEOPLE_HEADERS
    row = row if row is not None else list(PERSON_ROW)
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    sheet.get_all_values.return_value = [headers, row]
    return sheet


def _make_multi_sheet(headers, rows):
    sheet = MagicMock()
    sheet.get_all_values.return_value = [headers] + rows
    return sheet


def _make_write_sheet(headers, existing_rows):
    """Supports get_all_values() (duplicate-check reads) AND
    row_values(1) + update() (the eventual append_business_row write,
    exercised only when no duplicate is detected)."""
    sheet = MagicMock()
    data_rows = [list(r) for r in existing_rows]

    def get_all_values():
        return [headers] + data_rows

    def row_values(r):
        return headers if r == 1 else data_rows[r - 2]

    def update(range_name, values):
        data_rows.append(list(values[0]))

    sheet.get_all_values.side_effect = get_all_values
    sheet.row_values.side_effect = row_values
    sheet.update.side_effect = update
    return sheet, data_rows


# ─────────────────────────────────────────────────────────────
# create_person
# ─────────────────────────────────────────────────────────────

class TestCreatePerson(unittest.TestCase):

    def test_create_minimal_success(self):
        pm = _fresh_pm()
        sheet, _ = _make_write_sheet(PEOPLE_HEADERS, [])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Дидар Оспанов")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["person_id"].startswith("PRS-"))

    def test_create_missing_full_name_rejected(self):
        pm = _fresh_pm()
        result = pm.create_person("")
        self.assertFalse(result["ok"])
        self.assertIn("full_name", result["error"])

    def test_create_invalid_status_rejected(self):
        pm = _fresh_pm()
        result = pm.create_person("Дидар Оспанов", status="bogus")
        self.assertFalse(result["ok"])
        for s in pm.PERSON_STATUS:
            self.assertIn(s, result["error"])

    def test_create_unknown_business_id_rejected(self):
        pm = _fresh_pm()
        biz_sheet = MagicMock()
        biz_sheet.get_all_values.return_value = [["ID"]]
        with patch("business_core.sheets.get_business_sheet", return_value=biz_sheet):
            result = pm.create_person("Дидар Оспанов", business_id="BIZ-999")
        self.assertFalse(result["ok"])
        self.assertIn("BIZ-999", result["error"])

    def test_create_known_business_id_accepted(self):
        pm = _fresh_pm()
        biz_sheet = MagicMock()
        biz_sheet.get_all_values.return_value = [["ID"], ["BIZ-001"]]
        people_sheet, _ = _make_write_sheet(PEOPLE_HEADERS, [])

        def fake_get(key):
            return biz_sheet if key == "biz_registry" else people_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = pm.create_person("Дидар Оспанов", business_id="BIZ-001")
        self.assertTrue(result["ok"], result)

    def test_no_client_defaults_assumed(self):
        """Person Manager must NOT default Теплота/Уровень доверия the
        way /newclient does — it serves internal employees too."""
        pm = _fresh_pm()
        sheet, data_rows = _make_write_sheet(PEOPLE_HEADERS, [])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            pm.create_person("Дидар Оспанов")
        row = data_rows[0]
        self.assertEqual(row[PEOPLE_HEADERS.index("Теплота")], "")
        self.assertEqual(row[PEOPLE_HEADERS.index("Уровень доверия")], "")


# ─────────────────────────────────────────────────────────────
# Duplicate detection
# ─────────────────────────────────────────────────────────────

class TestDuplicateDetection(unittest.TestCase):

    def test_exact_phone_duplicate_rejected(self):
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Другое Имя", phone="+7 (707) 123-45-67")
        self.assertFalse(result["ok"])
        self.assertIn("PRS-001", result["error"])

    def test_exact_name_duplicate_rejected(self):
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("ИВАН   ИВАНОВ")
        self.assertFalse(result["ok"])

    def test_email_duplicate_rejected_when_available(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Email")] = "ivan@example.com"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Другое Имя", email="IVAN@EXAMPLE.COM")
        self.assertFalse(result["ok"])

    def test_different_business_id_still_matches_by_name(self):
        """Business ID narrows, it does not by itself allow bypassing a
        name/phone match — matching find_duplicate_person's OR semantics."""
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Иван Иванов", business_id="BIZ-001")
        self.assertFalse(result["ok"])

    def test_person_type_is_not_part_of_identity(self):
        """Explicit architectural requirement: creating a person with
        the SAME name/phone but a DIFFERENT Person Type must still be
        rejected as a duplicate — Person Type is an attribute, not identity."""
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]  # Тип = "сотрудник"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Иван Иванов", phone="77071234567", person_type="клиент")
        self.assertFalse(result["ok"])

    def test_archived_person_does_not_block_new_create(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Статус отношений")] = "archived"
        sheet, _ = _make_write_sheet(PEOPLE_HEADERS, [row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Иван Иванов", phone="77071234567")
        self.assertTrue(result["ok"], result)

    def test_no_match_allowed(self):
        pm = _fresh_pm()
        sheet, _ = _make_write_sheet(PEOPLE_HEADERS, [list(PERSON_ROW)])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.create_person("Совершенно Другой", phone="70000000000")
        self.assertTrue(result["ok"], result)

    def test_duplicate_rejected_before_id_generation(self):
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.generate_next_id") as mock_gen:
            pm.create_person("Иван Иванов")
            mock_gen.assert_not_called()

    def test_duplicate_rejected_before_write(self):
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_append:
            pm.create_person("Иван Иванов")
            mock_append.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────

class TestNormalization(unittest.TestCase):

    def test_normalize_person_name(self):
        pm = _fresh_pm()
        self.assertEqual(pm.normalize_person_name("  Иван   Иванов "), "иван иванов")
        self.assertEqual(pm.normalize_person_name("ИВАН ИВАНОВ"), "иван иванов")
        self.assertEqual(pm.normalize_person_name(None), "")

    def test_normalize_phone(self):
        pm = _fresh_pm()
        self.assertEqual(pm.normalize_phone("+7 (707) 123-45-67"), "77071234567")
        self.assertEqual(pm.normalize_phone("8 707 123 45 67"), "87071234567")
        self.assertEqual(pm.normalize_phone(""), "")
        self.assertEqual(pm.normalize_phone(None), "")


# ─────────────────────────────────────────────────────────────
# find_person_by_id / find_person
# ─────────────────────────────────────────────────────────────

class TestFindPerson(unittest.TestCase):

    def test_find_person_by_id_found(self):
        pm = _fresh_pm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            person = pm.find_person_by_id("PRS-001")
        self.assertIsNotNone(person)
        self.assertEqual(person["full_name"], "Иван Иванов")
        self.assertEqual(person["status"], "active")
        self.assertEqual(person["biz_ids"], ["BIZ-001"])
        self.assertEqual(person["row_num"], 2)

    def test_find_person_by_id_not_found(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(pm.find_person_by_id("PRS-999"))

    def test_find_person_by_id_blank_no_sheet_call(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(pm.find_person_by_id(""))
        sheet.find.assert_not_called()

    def test_find_person_matches_archived_too(self):
        """Unlike find_duplicate_person, find_person() is a general
        search and does NOT exclude archived rows."""
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Статус отношений")] = "archived"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            person = pm.find_person(name="Иван Иванов")
        self.assertIsNotNone(person)

    def test_find_person_no_criteria_returns_none(self):
        pm = _fresh_pm()
        self.assertIsNone(pm.find_person())


# ─────────────────────────────────────────────────────────────
# list functions
# ─────────────────────────────────────────────────────────────

class TestListPeople(unittest.TestCase):

    def test_list_all(self):
        pm = _fresh_pm()
        rows = [list(PERSON_ROW)]
        row2 = list(PERSON_ROW)
        row2[0] = "PRS-002"
        row2[PEOPLE_HEADERS.index("ФИО")] = "Пётр Петров"
        rows.append(row2)
        sheet = _make_multi_sheet(PEOPLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            people = pm.list_people()
        self.assertEqual(len(people), 2)

    def test_list_filtered_by_business_id(self):
        pm = _fresh_pm()
        row2 = list(PERSON_ROW)
        row2[0] = "PRS-002"
        row2[PEOPLE_HEADERS.index("Biz IDs")] = "BIZ-002"
        row2[PEOPLE_HEADERS.index("Primary Biz ID")] = "BIZ-002"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [list(PERSON_ROW), row2])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            filtered = pm.list_people(business_id="BIZ-002")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["person_id"], "PRS-002")

    def test_list_filtered_by_person_type(self):
        pm = _fresh_pm()
        row2 = list(PERSON_ROW)
        row2[0] = "PRS-002"
        row2[PEOPLE_HEADERS.index("Тип")] = "клиент"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [list(PERSON_ROW), row2])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            filtered = pm.list_people(person_type="клиент")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["person_id"], "PRS-002")

    def test_list_filtered_by_status(self):
        pm = _fresh_pm()
        row2 = list(PERSON_ROW)
        row2[0] = "PRS-002"
        row2[PEOPLE_HEADERS.index("Статус отношений")] = "archived"
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [list(PERSON_ROW), row2])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            active = pm.list_people(status="active")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["person_id"], "PRS-001")

    def test_list_people_by_business_wrapper(self):
        pm = _fresh_pm()
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [list(PERSON_ROW)])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.list_people_by_business("BIZ-001")
        self.assertEqual(len(result), 1)

    def test_list_people_by_type_wrapper(self):
        pm = _fresh_pm()
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [list(PERSON_ROW)])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.list_people_by_type("сотрудник")
        self.assertEqual(len(result), 1)

    def test_list_empty_sheet_returns_empty_list(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [PEOPLE_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.list_people(), [])


# ─────────────────────────────────────────────────────────────
# update_person
# ─────────────────────────────────────────────────────────────

class TestUpdatePerson(unittest.TestCase):

    def test_update_field(self):
        pm = _fresh_pm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person("PRS-001", {"Должность": "Coordinator"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Должность",))

    def test_update_same_value_no_change(self):
        pm = _fresh_pm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person("PRS-001", {"ФИО": "Иван Иванов"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_update_unknown_field_rejected(self):
        pm = _fresh_pm()
        result = pm.update_person("PRS-001", {"ID": "PRS-999"})
        self.assertFalse(result["ok"])
        self.assertIn("ID", result["error"])

    def test_update_first_contact_date_not_editable(self):
        pm = _fresh_pm()
        result = pm.update_person("PRS-001", {"Дата первого контакта": "2026-01-01"})
        self.assertFalse(result["ok"])

    def test_update_invalid_status_rejected(self):
        pm = _fresh_pm()
        result = pm.update_person("PRS-001", {"Статус отношений": "bogus"})
        self.assertFalse(result["ok"])

    def test_update_not_found(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person("PRS-999", {"Должность": "X"})
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# archive_person
# ─────────────────────────────────────────────────────────────

class TestArchivePerson(unittest.TestCase):

    def test_archive_sets_status(self):
        pm = _fresh_pm()
        sheet = _make_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.archive_person("PRS-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(value, "archived")

    def test_archive_is_idempotent(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Статус отношений")] = "archived"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.archive_person("PRS-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_archive_not_found(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.archive_person("PRS-999")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Honest contract
# ─────────────────────────────────────────────────────────────

class TestHonestContract(unittest.TestCase):

    def test_all_write_functions_return_ok_key(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIn("ok", pm.update_person("PRS-999", {"Должность": "x"}))
            self.assertIn("ok", pm.archive_person("PRS-999"))
        self.assertIn("ok", pm.create_person(""))

    def test_find_functions_return_none_not_exception(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(pm.find_person_by_id("PRS-999"))

    def test_list_functions_return_list_never_none(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.side_effect = Exception("sheets down")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.list_people(), [])
            self.assertEqual(pm.list_people_by_business("BIZ-001"), [])
            self.assertEqual(pm.list_people_by_type("клиент"), [])


# ─────────────────────────────────────────────────────────────
# Idempotency (cross-cutting)
# ─────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_double_archive_same_result(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Статус отношений")] = "archived"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            first = pm.archive_person("PRS-001")
            second = pm.archive_person("PRS-001")
        self.assertEqual(first, second)


# ─────────────────────────────────────────────────────────────
# Regression guards: business_builder.py delegators still work
# ─────────────────────────────────────────────────────────────

class TestBusinessBuilderDelegatorsUnchanged(unittest.TestCase):

    def test_business_builder_still_exposes_relocated_functions(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        import importlib
        bb = importlib.import_module("business_core.business_builder")
        for name in ("normalize_person_name", "normalize_phone",
                     "find_existing_person", "get_person_biz_ids"):
            self.assertTrue(hasattr(bb, name), f"business_builder.{name} missing")

    def test_business_builder_normalize_matches_person_manager(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        import importlib
        bb = importlib.import_module("business_core.business_builder")
        pm = importlib.import_module("business_core.person_manager")
        self.assertEqual(bb.normalize_person_name("  Иван  Иванов "), pm.normalize_person_name("  Иван  Иванов "))
        self.assertEqual(bb.normalize_phone("+7 (707) 123-45-67"), pm.normalize_phone("+7 (707) 123-45-67"))

    def test_find_existing_person_same_biz_semantics_preserved(self):
        """The relocated find_existing_person() must preserve the exact
        original 'same_biz' behavior newclient_confirm() depends on."""
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        import importlib
        bb = importlib.import_module("business_core.business_builder")
        row = list(PERSON_ROW)
        sheet = _make_multi_sheet(PEOPLE_HEADERS, [row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = bb.find_existing_person(name="Иван Иванов", biz_id="BIZ-002")
        self.assertIsNotNone(result)
        self.assertFalse(result["same_biz"])  # matched by name, but different biz


# ─────────────────────────────────────────────────────────────
# Import guards / architecture guards
# ─────────────────────────────────────────────────────────────

class TestArchitectureGuards(unittest.TestCase):

    def test_no_gtd_imports(self):
        path = WORKSPACE / "business_core" / "person_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN)

    def test_only_business_core_sheets_imported(self):
        path = WORKSPACE / "business_core" / "person_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("business_core"):
                imports.add(node.module)
        self.assertEqual(imports, {"business_core.sheets"})

    def test_no_organization_manager_or_work_assignment_manager_import(self):
        """AST-based, not a raw substring search — person_manager.py's own
        docstring legitimately MENTIONS organization_manager.py in prose
        (as a comparison reference for manager conventions), which must
        not be confused with an actual import dependency."""
        path = WORKSPACE / "business_core" / "person_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            if isinstance(node, ast.Import):
                for a in node.names:
                    imports.add(a.name)
        forbidden = {"business_core.organization_manager", "business_core.work_assignment_manager",
                     "business_core.telegram_handlers", "business_core.roadmap_manager"}
        self.assertEqual(imports & forbidden, set())

    # Note: the Phase 23D-1 guard asserting telegram_handlers.py stayed
    # fully untouched was removed here — Phase 23D-2 explicitly refactors
    # newclient_confirm() to call person_manager.create_person()/
    # update_person(), so that constraint no longer applies to this
    # module going forward. person_manager.py's own import-boundary
    # guards above (no organization_manager/work_assignment_manager/
    # telegram_handlers/roadmap_manager IMPORTS) remain the load-bearing
    # check — Telegram is allowed to call INTO person_manager.py, never
    # the reverse.

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_pm()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


# ─────────────────────────────────────────────────────────────
# Phase 23D-3B1 — append_person_biz_id() / update_person_drive_info()
# ─────────────────────────────────────────────────────────────

class TestAppendPersonBizId(unittest.TestCase):

    def test_adds_new_biz_id(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Biz IDs")] = "BIZ-001"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.append_person_biz_id("PRS-001", "BIZ-002")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertIn("Biz IDs", result["updated_fields"])
        biz_ids_col = PEOPLE_HEADERS.index("Biz IDs") + 1
        sheet.update_cell.assert_any_call(2, biz_ids_col, "BIZ-001,BIZ-002")

    def test_duplicate_biz_id_no_change(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Biz IDs")] = "BIZ-001,BIZ-002"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.append_person_biz_id("PRS-001", "BIZ-001")

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["updated_fields"], ())
        sheet.update_cell.assert_not_called()

    def test_does_not_overwrite_existing_primary_biz_id(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Biz IDs")] = "BIZ-001"
        row[PEOPLE_HEADERS.index("Primary Biz ID")] = "BIZ-001"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.append_person_biz_id("PRS-001", "BIZ-002")

        self.assertNotIn("Primary Biz ID", result["updated_fields"])
        primary_col = PEOPLE_HEADERS.index("Primary Biz ID") + 1
        for c in sheet.update_cell.call_args_list:
            self.assertFalse(c.args[1] == primary_col and c.args[2] == "BIZ-002")

    def test_sets_primary_biz_id_if_empty(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Biz IDs")] = "BIZ-001"
        row[PEOPLE_HEADERS.index("Primary Biz ID")] = ""
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.append_person_biz_id("PRS-001", "BIZ-002")

        self.assertIn("Primary Biz ID", result["updated_fields"])
        primary_col = PEOPLE_HEADERS.index("Primary Biz ID") + 1
        sheet.update_cell.assert_any_call(2, primary_col, "BIZ-002")

    def test_person_not_found(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [PEOPLE_HEADERS, list(PERSON_ROW)]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.append_person_biz_id("PRS-999", "BIZ-002")

        self.assertFalse(result["ok"])
        self.assertIn("не найден", result["error"])
        sheet.update_cell.assert_not_called()

    def test_empty_person_id_or_biz_id_rejected(self):
        pm = _fresh_pm()
        self.assertFalse(pm.append_person_biz_id("", "BIZ-001")["ok"])
        self.assertFalse(pm.append_person_biz_id("PRS-001", "")["ok"])

    def test_sheets_error_returns_ok_false(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=Exception("timeout")):
            result = pm.append_person_biz_id("PRS-001", "BIZ-002")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")


class TestUpdatePersonDriveInfo(unittest.TestCase):

    def test_fills_empty_drive_fields(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Google Drive")] = ""
        row[PEOPLE_HEADERS.index("Drive Folder ID")] = ""
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person_drive_info("PRS-001", "folder-123", "https://drive.google.com/x")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(sheet.update_cell.call_count, 2)
        self.assertEqual(set(result["updated_fields"]), {"Google Drive", "Drive Folder ID"})

    def test_does_not_overwrite_existing_drive_fields(self):
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Google Drive")] = "https://existing.url"
        row[PEOPLE_HEADERS.index("Drive Folder ID")] = "existing-id"
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person_drive_info("PRS-001", "new-folder", "https://new.url")

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["updated_fields"], ())
        sheet.update_cell.assert_not_called()

    def test_one_field_empty_one_already_set(self):
        """One field already populated is preserved while the other,
        empty one is independently filled."""
        pm = _fresh_pm()
        row = list(PERSON_ROW)
        row[PEOPLE_HEADERS.index("Google Drive")] = "https://existing.url"
        row[PEOPLE_HEADERS.index("Drive Folder ID")] = ""
        sheet = _make_sheet(row=row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person_drive_info("PRS-001", "new-folder-id", "https://new.url")

        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Drive Folder ID",))
        sheet.update_cell.assert_called_once()

    def test_person_not_found(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [PEOPLE_HEADERS, list(PERSON_ROW)]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person_drive_info("PRS-999", "folder-x", "https://x")

        self.assertFalse(result["ok"])
        self.assertIn("не найден", result["error"])

    def test_empty_folder_id_short_circuits_even_with_folder_url(self):
        """Documented technical debt (Phase 23D-3B): a falsy folder_id
        short-circuits the whole call before folder_url is even
        considered — preserved exactly, not fixed in this phase."""
        pm = _fresh_pm()
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_person_drive_info("PRS-001", "", "https://drive.google.com/x")

        self.assertFalse(result["ok"])
        sheet.get_all_values.assert_not_called()

    def test_sheets_error_returns_ok_false(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=Exception("boom")):
            result = pm.update_person_drive_info("PRS-001", "x", "https://x")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")


if __name__ == "__main__":
    unittest.main(verbosity=2)
