"""
Tests for Phase 21D — Organization Manager: Seed Data.

Covers business_core/organization_manager.py's seed_default_organization(),
which reproduces exactly the example organization from ARCHITECTURE.md /
Phase 20A.5 §9. Not auto-run — callable only, mocked here, no live Sheets
writes (per ENGINEERING_STANDARDS.md Testing Standards).

Vacancy (is_role_vacant) and multi-role (get_active_roles_for_person)
read helpers were already delivered in Phase 21C (they're exercised by
test_business_organization_function_assignment.py) — this file adds one
integration-style check that the seed's own vacant roles are correctly
read as vacant via those existing helpers.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


def _fresh_om():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.organization_manager")


class _InMemoryRegistry:
    """A minimal in-memory stand-in for a single Sheets tab: supports
    find()/row_values()/update_cell()/get_all_values() against a growing
    list of rows, so create_department/create_role/etc. (which internally
    call append_business_row + generate_next_id + get_business_sheet) can
    be exercised end-to-end without any live Google API call."""

    def __init__(self, headers: list[str]):
        self.headers = headers
        self.rows: list[list[str]] = []

    def get_all_values(self):
        return [self.headers] + self.rows

    def row_values(self, r):
        if r == 1:
            return self.headers
        return self.rows[r - 2]

    def find(self, value, in_column=1):
        for i, row in enumerate(self.rows):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = i + 2
                return cell
        return None

    def update_cell(self, row_num, col, value):
        row = self.rows[row_num - 2]
        while len(row) < col:
            row.append("")
        row[col - 1] = value

    def update(self, range_name, values):
        # append_business_row() uses sheet.update(range, [values]) to
        # write a fresh row (see business_core/sheets.py).
        self.rows.append(list(values[0]))


DEPARTMENT_HEADERS = [
    "Department ID", "Business ID", "Department Name",
    "Parent Department ID", "Head Role ID", "Status", "Notes",
]
ROLE_HEADERS = [
    "Role ID", "Department ID", "Role Name", "Reports To Role ID",
    "Role Type", "Employment Model", "Status",
    "Purpose", "Main Result", "Notes",
]
FUNCTION_HEADERS = [
    "Function ID", "Role ID", "Function Category", "Function Name",
    "Description", "Frequency", "Criticality", "Can Delegate",
    "Status", "Sort Order",
]
ASSIGNMENT_HEADERS = [
    "Assignment ID", "Person ID", "Role ID",
    "Start Date", "End Date", "Assignment Type", "Status", "Notes",
]
PEOPLE_HEADERS = ["ID"]


def _make_registry_set():
    return {
        "department_registry":        _InMemoryRegistry(DEPARTMENT_HEADERS),
        "role_registry":              _InMemoryRegistry(ROLE_HEADERS),
        "role_functions":             _InMemoryRegistry(FUNCTION_HEADERS),
        "person_role_assignments":    _InMemoryRegistry(ASSIGNMENT_HEADERS),
        "people_registry":            _InMemoryRegistry(PEOPLE_HEADERS),
    }


def _seed_people(registries, person_id="PRS-001"):
    registries["people_registry"].rows.append([person_id])


class TestSeedDefaultOrganization(unittest.TestCase):

    def _run_seed(self, owner_person_id="PRS-001"):
        om = _fresh_om()
        registries = _make_registry_set()
        _seed_people(registries, owner_person_id)

        def fake_get_business_sheet(key):
            return registries[key]

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = om.seed_default_organization(owner_person_id)
        return om, registries, result

    def test_seed_succeeds(self):
        om, registries, result = self._run_seed()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_seed_missing_owner_rejected(self):
        om = _fresh_om()
        result = om.seed_default_organization("")
        self.assertFalse(result["ok"])
        self.assertIn("owner_person_id", result["errors"][0])

    def test_seed_creates_exactly_two_departments(self):
        om, registries, result = self._run_seed()
        self.assertEqual(len(registries["department_registry"].rows), 2)
        self.assertIn("executive", result["department_ids"])
        self.assertIn("operations", result["department_ids"])

    def test_operations_department_reports_to_executive(self):
        om, registries, result = self._run_seed()
        ops_id = result["department_ids"]["operations"]
        exec_id = result["department_ids"]["executive"]
        ops = om.find_department_by_id(ops_id)
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            ops = om.find_department_by_id(ops_id)
        self.assertEqual(ops["parent_department_id"], exec_id)

    def test_executive_head_role_id_set_to_ceo(self):
        om, registries, result = self._run_seed()
        exec_id = result["department_ids"]["executive"]
        ceo_id = result["role_ids"]["ceo"]
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            execu = om.find_department_by_id(exec_id)
        self.assertEqual(execu["head_role_id"], ceo_id)

    def test_seed_creates_exactly_five_roles(self):
        om, registries, result = self._run_seed()
        self.assertEqual(len(registries["role_registry"].rows), 5)
        for key in ("ceo", "operations_manager", "coordinator", "inbound_manager", "document_controller"):
            self.assertIn(key, result["role_ids"])

    def test_ceo_is_active_others_are_planned(self):
        om, registries, result = self._run_seed()
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            ceo = om.find_role_by_id(result["role_ids"]["ceo"])
            ops_mgr = om.find_role_by_id(result["role_ids"]["operations_manager"])
            coordinator = om.find_role_by_id(result["role_ids"]["coordinator"])
        self.assertEqual(ceo["status"], "active")
        self.assertEqual(ops_mgr["status"], "planned")
        self.assertEqual(coordinator["status"], "planned")

    def test_role_hierarchy_chain(self):
        om, registries, result = self._run_seed()
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            ops_mgr = om.find_role_by_id(result["role_ids"]["operations_manager"])
            coordinator = om.find_role_by_id(result["role_ids"]["coordinator"])
            inbound = om.find_role_by_id(result["role_ids"]["inbound_manager"])
            doc_ctrl = om.find_role_by_id(result["role_ids"]["document_controller"])
        self.assertEqual(ops_mgr["reports_to_role_id"], result["role_ids"]["ceo"])
        self.assertEqual(coordinator["reports_to_role_id"], result["role_ids"]["operations_manager"])
        self.assertEqual(inbound["reports_to_role_id"], result["role_ids"]["operations_manager"])
        self.assertEqual(doc_ctrl["reports_to_role_id"], result["role_ids"]["operations_manager"])

    def test_seed_creates_exactly_twelve_coordinator_functions(self):
        om, registries, result = self._run_seed()
        self.assertEqual(len(result["function_ids"]), 12)
        self.assertEqual(len(registries["role_functions"].rows), 12)
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            funcs = om.list_role_functions(role_id=result["role_ids"]["coordinator"])
        self.assertEqual(len(funcs), 12)
        self.assertEqual([f["sort_order"] for f in funcs], [str(i) for i in range(1, 13)])

    def test_seed_creates_exactly_one_assignment(self):
        om, registries, result = self._run_seed(owner_person_id="PRS-042")
        self.assertEqual(len(registries["person_role_assignments"].rows), 1)
        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            assignment = om.find_assignment_by_id(result["assignment_id"])
        self.assertEqual(assignment["person_id"], "PRS-042")
        self.assertEqual(assignment["role_id"], result["role_ids"]["ceo"])
        self.assertEqual(assignment["status"], "active")

    def test_seed_stops_on_first_failure_and_reports_it(self):
        """Missing owner in PEOPLE_REGISTRY -> assignment step fails ->
        seed reports ok=False with the specific error, but everything
        created before that point (departments/roles/functions) stays
        in place — not transactional, honestly reported."""
        om = _fresh_om()
        registries = _make_registry_set()
        # deliberately do NOT seed the owner into people_registry

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            result = om.seed_default_organization("PRS-999-UNKNOWN")

        self.assertFalse(result["ok"])
        self.assertTrue(any("PRS-999-UNKNOWN" in e for e in result["errors"]))
        self.assertEqual(len(registries["department_registry"].rows), 2)
        self.assertEqual(len(registries["role_registry"].rows), 5)
        self.assertEqual(len(registries["role_functions"].rows), 12)
        self.assertEqual(result["assignment_id"], "")


class TestSeedVacancyIntegration(unittest.TestCase):
    """Confirms the seed's intentionally-vacant roles (Operations Manager,
    Coordinator, Inbound Manager, Document Controller) are correctly read
    as vacant via is_role_vacant() (delivered in Phase 21C), and the CEO
    role is correctly read as filled."""

    def test_vacant_roles_read_as_vacant(self):
        om = _fresh_om()
        registries = _make_registry_set()
        _seed_people(registries)

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            result = om.seed_default_organization("PRS-001")
            for key in ("operations_manager", "coordinator", "inbound_manager", "document_controller"):
                self.assertTrue(
                    om.is_role_vacant(result["role_ids"][key]),
                    f"{key} should be vacant (no Assignment created for it)",
                )

    def test_ceo_role_not_vacant(self):
        om = _fresh_om()
        registries = _make_registry_set()
        _seed_people(registries)

        with patch("business_core.sheets.get_business_sheet",
                   side_effect=lambda key: registries[key]):
            result = om.seed_default_organization("PRS-001")
            self.assertFalse(om.is_role_vacant(result["role_ids"]["ceo"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
