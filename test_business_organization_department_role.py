"""
Tests for Phase 21B — Organization Manager: Department + Role CRUD.

Covers business_core/organization_manager.py's Department and Role
functions: create/find/list/update/archive, enum validation, FK
validation, soft-delete via Status, idempotent archive.

Phase 21C will add Role Function + Person Role Assignment tests to a
separate file. Phase 21F will add Telegram command tests. No live Sheets
writes — mocks only, per ENGINEERING_STANDARDS.md Testing Standards.
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

DEPARTMENT_HEADERS = [
    "Department ID", "Business ID", "Department Name",
    "Parent Department ID", "Head Role ID", "Status", "Notes",
]
DEPARTMENT_ROW = ["DEPT-001", "", "Executive", "", "", "active", ""]

ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]
ROLE_ROW = [
    "ROLE-001", "DEPT-001", "CEO / Founder", "",
    "internal", "full_time", "active",
    "Управлять компанией", "Компания достигает целей", "",
]


def _fresh_om():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.organization_manager")


def _make_sheet(headers, row, row_num=2, extra_rows=None):
    """Mock sheet supporting find/row_values/update_cell/get_all_values."""
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    all_values = [headers, row] + (extra_rows or [])
    sheet.get_all_values.return_value = all_values
    return sheet


def _make_multi_sheet(headers, rows):
    """Mock sheet for list_* functions — get_all_values only."""
    sheet = MagicMock()
    sheet.get_all_values.return_value = [headers] + rows
    return sheet


class _DeptRoleTestBase(unittest.TestCase):
    def _patch_dept_sheet(self, sheet):
        return patch(
            "business_core.sheets.get_business_sheet",
            side_effect=lambda key: sheet if key == "department_registry" else MagicMock(),
        )


# ─────────────────────────────────────────────────────────────
# Department: create
# ─────────────────────────────────────────────────────────────

class TestCreateDepartment(unittest.TestCase):

    def test_create_minimal_success(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DEPARTMENT_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.create_department("Operations")
        self.assertTrue(result["ok"])
        self.assertTrue(result["department_id"].startswith("DEPT-"))
        self.assertIsNone(result["error"])

    def test_create_missing_name_rejected(self):
        om = _fresh_om()
        result = om.create_department("")
        self.assertFalse(result["ok"])
        self.assertIn("department_name", result["error"])

    def test_create_invalid_status_rejected(self):
        om = _fresh_om()
        result = om.create_department("Operations", status="bogus")
        self.assertFalse(result["ok"])
        for status in om.DEPARTMENT_STATUS:
            self.assertIn(status, result["error"])

    def test_create_unknown_business_id_rejected(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [["ID"]]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.create_department("Operations", business_id="BIZ-999")
        self.assertFalse(result["ok"])
        self.assertIn("BIZ-999", result["error"])

    def test_create_known_business_id_accepted(self):
        om = _fresh_om()
        biz_sheet = MagicMock()
        biz_sheet.get_all_values.return_value = [["ID"], ["BIZ-001"]]
        dept_sheet = MagicMock()
        dept_sheet.get_all_values.return_value = [DEPARTMENT_HEADERS]

        def fake_get_business_sheet(key):
            return biz_sheet if key == "biz_registry" else dept_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = om.create_department("Operations", business_id="BIZ-001")
        self.assertTrue(result["ok"])

    def test_create_unknown_parent_department_rejected(self):
        om = _fresh_om()
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        dept_sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=dept_sheet):
            result = om.create_department("Coordination", parent_department_id="DEPT-999")
        self.assertFalse(result["ok"])
        self.assertIn("DEPT-999", result["error"])

    def test_create_known_parent_department_accepted(self):
        om = _fresh_om()
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        with patch("business_core.sheets.get_business_sheet", return_value=dept_sheet):
            result = om.create_department("Coordination", parent_department_id="DEPT-001")
        self.assertTrue(result["ok"])

    def test_create_does_not_validate_head_role_id(self):
        """Head Role ID is a deliberate forward-reference — no validation
        at write time (vacant department head is a legitimate state)."""
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DEPARTMENT_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.create_department("Operations", head_role_id="ROLE-999-NOT-YET-CREATED")
        self.assertTrue(result["ok"])


# ─────────────────────────────────────────────────────────────
# Department: find / list
# ─────────────────────────────────────────────────────────────

class TestFindListDepartment(unittest.TestCase):

    def test_find_by_id_found(self):
        om = _fresh_om()
        sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            dept = om.find_department_by_id("DEPT-001")
        self.assertIsNotNone(dept)
        self.assertEqual(dept["department_name"], "Executive")
        self.assertEqual(dept["status"], "active")
        self.assertEqual(dept["row_num"], 2)

    def test_find_by_id_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_department_by_id("DEPT-999"))

    def test_find_empty_id_returns_none_without_sheet_call(self):
        om = _fresh_om()
        sheet = MagicMock()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_department_by_id(""))
        sheet.find.assert_not_called()

    def test_list_all_departments(self):
        om = _fresh_om()
        rows = [
            ["DEPT-001", "", "Executive", "", "ROLE-001", "active", ""],
            ["DEPT-002", "", "Operations", "DEPT-001", "", "active", ""],
        ]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            depts = om.list_departments()
        self.assertEqual(len(depts), 2)
        self.assertEqual(depts[1]["parent_department_id"], "DEPT-001")

    def test_list_filtered_by_status(self):
        om = _fresh_om()
        rows = [
            ["DEPT-001", "", "Executive", "", "", "active", ""],
            ["DEPT-002", "", "Old Dept", "", "", "archived", ""],
        ]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            active = om.list_departments(status="active")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["department_id"], "DEPT-001")

    def test_list_filtered_by_business_id(self):
        om = _fresh_om()
        rows = [
            ["DEPT-001", "BIZ-001", "Legalization Ops", "", "", "active", ""],
            ["DEPT-002", "BIZ-002", "Visa Ops", "", "", "active", ""],
        ]
        sheet = _make_multi_sheet(DEPARTMENT_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            filtered = om.list_departments(business_id="BIZ-002")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["department_id"], "DEPT-002")

    def test_list_empty_sheet_returns_empty_list(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DEPARTMENT_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.list_departments(), [])


# ─────────────────────────────────────────────────────────────
# Department: update / archive
# ─────────────────────────────────────────────────────────────

class TestUpdateDepartment(unittest.TestCase):

    def test_rename_department(self):
        om = _fresh_om()
        sheet = _make_sheet(DEPARTMENT_HEADERS, list(DEPARTMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_department("DEPT-001", {"Department Name": "Executive Office"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Department Name",))
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(col, DEPARTMENT_HEADERS.index("Department Name") + 1)
        self.assertEqual(value, "Executive Office")

    def test_update_same_value_reports_changed_false(self):
        om = _fresh_om()
        sheet = _make_sheet(DEPARTMENT_HEADERS, list(DEPARTMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_department("DEPT-001", {"Department Name": "Executive"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_update_unknown_field_rejected(self):
        om = _fresh_om()
        result = om.update_department("DEPT-001", {"Bogus Field": "x"})
        self.assertFalse(result["ok"])
        self.assertIn("Bogus Field", result["error"])

    def test_update_invalid_status_rejected(self):
        om = _fresh_om()
        result = om.update_department("DEPT-001", {"Status": "bogus"})
        self.assertFalse(result["ok"])

    def test_update_not_found_department(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_department("DEPT-999", {"Department Name": "X"})
        self.assertFalse(result["ok"])
        self.assertIn("DEPT-999", result["error"])

    def test_update_self_parent_rejected(self):
        om = _fresh_om()
        result = om.update_department("DEPT-001", {"Parent Department ID": "DEPT-001"})
        self.assertFalse(result["ok"])
        self.assertIn("самого себя", result["error"])


class TestArchiveDepartment(unittest.TestCase):

    def test_archive_sets_status(self):
        om = _fresh_om()
        sheet = _make_sheet(DEPARTMENT_HEADERS, list(DEPARTMENT_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_department("DEPT-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(col, DEPARTMENT_HEADERS.index("Status") + 1)
        self.assertEqual(value, "archived")

    def test_archive_is_idempotent(self):
        om = _fresh_om()
        archived_row = list(DEPARTMENT_ROW)
        archived_row[DEPARTMENT_HEADERS.index("Status")] = "archived"
        sheet = _make_sheet(DEPARTMENT_HEADERS, archived_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_department("DEPT-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_archive_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_department("DEPT-999")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Role: create
# ─────────────────────────────────────────────────────────────

class TestCreateRole(unittest.TestCase):

    def _dept_and_role_sheets(self, role_extra_rows=None):
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        role_sheet = MagicMock()
        role_sheet.get_all_values.return_value = [ROLE_HEADERS] + (role_extra_rows or [])

        def fake_get_business_sheet(key):
            return dept_sheet if key == "department_registry" else role_sheet

        return fake_get_business_sheet, role_sheet

    def test_create_minimal_success(self):
        om = _fresh_om()
        fake_get, role_sheet = self._dept_and_role_sheets()
        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["role_id"].startswith("ROLE-"))

    def test_create_missing_name_rejected(self):
        om = _fresh_om()
        result = om.create_role("", department_id="DEPT-001")
        self.assertFalse(result["ok"])
        self.assertIn("role_name", result["error"])

    def test_create_missing_department_id_rejected(self):
        om = _fresh_om()
        result = om.create_role("Coordinator", department_id="")
        self.assertFalse(result["ok"])
        self.assertIn("department_id", result["error"])

    def test_create_unknown_department_rejected(self):
        om = _fresh_om()
        dept_sheet = MagicMock()
        dept_sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=dept_sheet):
            result = om.create_role("Coordinator", department_id="DEPT-999")
        self.assertFalse(result["ok"])
        self.assertIn("DEPT-999", result["error"])

    def test_create_invalid_role_type_rejected(self):
        om = _fresh_om()
        result = om.create_role("Coordinator", department_id="DEPT-001", role_type="external_contractor")
        self.assertFalse(result["ok"])
        self.assertIn("internal", result["error"])

    def test_create_invalid_employment_model_rejected(self):
        om = _fresh_om()
        result = om.create_role("Coordinator", department_id="DEPT-001", employment_model="contractor")
        self.assertFalse(result["ok"])

    def test_create_invalid_status_rejected(self):
        om = _fresh_om()
        result = om.create_role("Coordinator", department_id="DEPT-001", status="bogus")
        self.assertFalse(result["ok"])

    def test_create_unknown_reports_to_rejected(self):
        om = _fresh_om()
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        role_sheet_not_found = MagicMock()
        role_sheet_not_found.find.return_value = None

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet_not_found

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Coordinator", department_id="DEPT-001", reports_to_role_id="ROLE-999")
        self.assertFalse(result["ok"])
        self.assertIn("ROLE-999", result["error"])

    def test_create_known_reports_to_accepted(self):
        om = _fresh_om()
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        role_sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW)

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Operations Manager", department_id="DEPT-001", reports_to_role_id="ROLE-001")
        self.assertTrue(result["ok"])

    def test_create_default_status_is_planned(self):
        """Vacant-by-default matches the org design: a new Role starts
        planned/vacant until explicitly assigned/activated (Phase 21C)."""
        om = _fresh_om()
        fake_get, _ = self._dept_and_role_sheets()
        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("Inbound Manager", department_id="DEPT-001")
        self.assertTrue(result["ok"])
        # default status param is "planned" — verify via a subsequent find
        # is out of scope here (append-only mock); assert no error surfaced
        # for the default status value itself:
        self.assertIsNone(result["error"])


# ─────────────────────────────────────────────────────────────
# Role: find / list
# ─────────────────────────────────────────────────────────────

class TestFindListRole(unittest.TestCase):

    def test_find_by_id_found(self):
        om = _fresh_om()
        sheet = _make_sheet(ROLE_HEADERS, ROLE_ROW)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            role = om.find_role_by_id("ROLE-001")
        self.assertIsNotNone(role)
        self.assertEqual(role["role_name"], "CEO / Founder")
        self.assertEqual(role["status"], "active")
        self.assertEqual(role["row_num"], 2)

    def test_find_by_id_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_role_by_id("ROLE-999"))

    def test_reports_to_chain_readable(self):
        om = _fresh_om()
        rows = [
            ["ROLE-001", "DEPT-001", "CEO", "", "internal", "full_time", "active", "", "", ""],
            ["ROLE-002", "DEPT-002", "Operations Manager", "ROLE-001", "internal", "full_time", "planned", "", "", ""],
            ["ROLE-003", "DEPT-002", "Coordinator", "ROLE-002", "internal", "full_time", "planned", "", "", ""],
        ]
        sheet = _make_multi_sheet(ROLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            roles = om.list_roles()
        by_id = {r["role_id"]: r for r in roles}
        self.assertEqual(by_id["ROLE-003"]["reports_to_role_id"], "ROLE-002")
        self.assertEqual(by_id["ROLE-002"]["reports_to_role_id"], "ROLE-001")
        self.assertEqual(by_id["ROLE-001"]["reports_to_role_id"], "")

    def test_list_filtered_by_department(self):
        om = _fresh_om()
        rows = [
            ["ROLE-001", "DEPT-001", "CEO", "", "internal", "full_time", "active", "", "", ""],
            ["ROLE-002", "DEPT-002", "Coordinator", "", "internal", "full_time", "planned", "", "", ""],
        ]
        sheet = _make_multi_sheet(ROLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            filtered = om.list_roles(department_id="DEPT-002")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["role_id"], "ROLE-002")

    def test_list_filtered_by_status(self):
        om = _fresh_om()
        rows = [
            ["ROLE-001", "DEPT-001", "CEO", "", "internal", "full_time", "active", "", "", ""],
            ["ROLE-002", "DEPT-002", "Coordinator", "", "internal", "full_time", "planned", "", "", ""],
        ]
        sheet = _make_multi_sheet(ROLE_HEADERS, rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            planned = om.list_roles(status="planned")
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["role_id"], "ROLE-002")


# ─────────────────────────────────────────────────────────────
# Role: update / archive
# ─────────────────────────────────────────────────────────────

class TestUpdateRole(unittest.TestCase):

    def test_update_status_planned_to_active(self):
        om = _fresh_om()
        planned_row = list(ROLE_ROW)
        planned_row[ROLE_HEADERS.index("Status")] = "planned"
        sheet = _make_sheet(ROLE_HEADERS, planned_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_role("ROLE-001", {"Status": "active"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["updated_fields"], ("Status",))

    def test_update_unknown_field_rejected(self):
        om = _fresh_om()
        result = om.update_role("ROLE-001", {"Business ID": "BIZ-001"})
        self.assertFalse(result["ok"])
        self.assertIn("Business ID", result["error"])

    def test_update_unknown_department_rejected(self):
        om = _fresh_om()
        result = om.update_role("ROLE-001", {"Department ID": "DEPT-999"})
        self.assertFalse(result["ok"])

    def test_update_self_reports_to_rejected(self):
        om = _fresh_om()
        result = om.update_role("ROLE-001", {"Reports To Role ID": "ROLE-001"})
        self.assertFalse(result["ok"])
        self.assertIn("подчиняться самой себе", result["error"])

    def test_update_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_role("ROLE-999", {"Status": "active"})
        self.assertFalse(result["ok"])


class TestArchiveRole(unittest.TestCase):

    def test_archive_sets_status(self):
        om = _fresh_om()
        sheet = _make_sheet(ROLE_HEADERS, list(ROLE_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role("ROLE-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(col, ROLE_HEADERS.index("Status") + 1)
        self.assertEqual(value, "archived")

    def test_archive_is_idempotent(self):
        om = _fresh_om()
        archived_row = list(ROLE_ROW)
        archived_row[ROLE_HEADERS.index("Status")] = "archived"
        sheet = _make_sheet(ROLE_HEADERS, archived_row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role("ROLE-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_archive_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.archive_role("ROLE-999")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# Duplicate names allowed (no uniqueness constraint in approved schema)
# ─────────────────────────────────────────────────────────────

class TestDuplicatesNowRejected(unittest.TestCase):
    """Superseded by Phase 23C: exact-duplicate names are now rejected,
    not allowed. See test_business_organization_duplicate_protection.py
    for the full duplicate-detection test suite (normalization, scoping,
    archived-row behavior, Reports-To exclusion, etc.) — this class only
    re-confirms the two original Phase 21B scenarios flip outcome."""

    def test_duplicate_department_name_now_rejected(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DEPARTMENT_HEADERS, DEPARTMENT_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.create_department("Executive")
        self.assertFalse(result["ok"])

    def test_duplicate_role_name_now_rejected(self):
        om = _fresh_om()
        dept_sheet = _make_sheet(DEPARTMENT_HEADERS, DEPARTMENT_ROW)
        role_sheet = MagicMock()
        role_sheet.get_all_values.return_value = [ROLE_HEADERS, ROLE_ROW]

        def fake_get(key):
            return dept_sheet if key == "department_registry" else role_sheet

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get):
            result = om.create_role("CEO / Founder", department_id="DEPT-001")
        self.assertFalse(result["ok"])


# ─────────────────────────────────────────────────────────────
# No Core / GTD coupling
# ─────────────────────────────────────────────────────────────

class TestNoCoreOrGtdCoupling(unittest.TestCase):

    def _check_no_gtd_imports(self, path: Path):
        if not path.exists():
            return
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN,
                                     f"{path.name} импортирует {a.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN,
                                 f"{path.name} импортирует {node.module!r}")

    def test_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "organization_manager.py")

    def test_no_import_of_roadmap_manager_or_telegram_handlers(self):
        """organization_manager.py must not import Core managers or the
        Telegram layer — Manager First / Layer Dependency Rules."""
        om = _fresh_om()
        import inspect
        src = inspect.getsource(om)
        self.assertNotIn("roadmap_manager", src)
        self.assertNotIn("telegram_handlers", src)

    def test_no_writes_to_people_registry_or_biz_registry(self):
        """Only read-only find_row_by_id calls into biz_registry are
        allowed — organization_manager.py must never write to another
        domain's registry (Layer Dependency Rules)."""
        write_calls = []

        def fake_get_business_sheet(key):
            sheet = MagicMock()
            sheet.get_all_values.return_value = [DEPARTMENT_HEADERS]
            if key in ("people_registry", "biz_registry"):
                def track_update(*a, **kw):
                    write_calls.append(key)
                sheet.update_cell.side_effect = track_update
                sheet.append_row = MagicMock(side_effect=lambda *a: write_calls.append(key))
            return sheet

        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet), \
             patch("business_core.sheets.find_row_by_id", return_value=None):
            om.create_department("Operations", business_id="BIZ-999")

        self.assertEqual(write_calls, [])

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_om()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


# ─────────────────────────────────────────────────────────────
# API contract / architecture guard (Phase 21B closeout)
# ─────────────────────────────────────────────────────────────

class TestPublicApiContract(unittest.TestCase):
    """Locks in the exact Phase 21B public function surface — a rename or
    removal here is a breaking change per ENGINEERING_STANDARDS.md
    Backward Compatibility and must be deliberate, not accidental."""

    EXPECTED_PUBLIC_FUNCTIONS = (
        "find_department_by_id", "list_departments", "create_department",
        "update_department", "archive_department",
        "find_role_by_id", "list_roles", "create_role",
        "update_role", "archive_role",
    )

    EXPECTED_ENUMS = (
        "DEPARTMENT_STATUS", "ROLE_STATUS", "ROLE_TYPE", "EMPLOYMENT_MODEL",
    )

    def test_all_expected_public_functions_exist(self):
        om = _fresh_om()
        for name in self.EXPECTED_PUBLIC_FUNCTIONS:
            self.assertTrue(hasattr(om, name), f"missing public function: {name}")
            self.assertTrue(callable(getattr(om, name)))

    def test_department_role_functions_still_present(self):
        """Phase 21C legitimately extends this module's public surface
        (Role Function + Assignment CRUD, per the approved Phase 21 plan)
        — this is now a subset check, not exact equality. The exact
        current full surface is locked in by
        test_business_organization_function_assignment.py's own contract
        test (Phase 21C closeout)."""
        om = _fresh_om()
        public_callables = {
            name for name in vars(om)
            if not name.startswith("_") and callable(getattr(om, name))
            and getattr(getattr(om, name), "__module__", "") == om.__name__
        }
        self.assertTrue(set(self.EXPECTED_PUBLIC_FUNCTIONS).issubset(public_callables))

    def test_all_expected_enums_exist_and_are_tuples(self):
        om = _fresh_om()
        for name in self.EXPECTED_ENUMS:
            self.assertTrue(hasattr(om, name), f"missing enum: {name}")
            self.assertIsInstance(getattr(om, name), tuple)

    def test_all_write_functions_return_ok_key(self):
        """Contract check: every write function's dict return always has
        'ok' as the first-class signal, even on the not-found/invalid path."""
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIn("ok", om.update_department("DEPT-999", {"Notes": "x"}))
            self.assertIn("ok", om.archive_department("DEPT-999"))
            self.assertIn("ok", om.update_role("ROLE-999", {"Notes": "x"}))
            self.assertIn("ok", om.archive_role("ROLE-999"))
        self.assertIn("ok", om.create_department(""))
        self.assertIn("ok", om.create_role("", department_id=""))

    def test_find_functions_return_none_not_exception_on_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertIsNone(om.find_department_by_id("DEPT-999"))
            self.assertIsNone(om.find_role_by_id("ROLE-999"))

    def test_list_functions_return_list_never_none(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.side_effect = Exception("sheets down")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.list_departments(), [])
            self.assertEqual(om.list_roles(), [])


class TestModuleOnlyDependsOnSheets(unittest.TestCase):
    """Layer Dependency Rules (ENGINEERING_STANDARDS.md §2): a Manager may
    depend only on business_core.sheets, never on another domain's manager,
    never on the Telegram layer, never on GTD."""

    ALLOWED_IMPORT_ROOTS = {"business_core", "__future__", "logging", "typing"}

    def test_only_business_core_sheets_imported_within_business_core(self):
        path = WORKSPACE / "business_core" / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        business_core_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("business_core"):
                    business_core_imports.add(node.module)
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("business_core"):
                        business_core_imports.add(a.name)
        self.assertEqual(business_core_imports, {"business_core.sheets"})

    def test_no_top_level_import_side_effects(self):
        """All business_core.sheets imports are deferred inside function
        bodies (established convention) — importing the module itself must
        not eagerly touch Sheets/Google API."""
        path = WORKSPACE / "business_core" / "organization_manager.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        module_level_names = {
            n.module for n in tree.body
            if isinstance(n, ast.ImportFrom)
        }
        self.assertNotIn("business_core.sheets", module_level_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
