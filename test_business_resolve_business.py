"""
Phase 13A: business_core.business_builder.resolve_business() — mock tests.

Production incident: entering a business name in free-form text
("узаконение недвижимости", lowercase) left Biz IDs/Primary Biz ID
empty because lookup required an exact-case match. resolve_business()
is the single, shared resolver for this: trim + casefold + collapse
internal whitespace, matched against both the BIZ_REGISTRY "ID" column
and the "Название" column. No fuzzy matching — an unrecognized input
must fail loudly with the active-business list, never guess.

All tests fully mock business_core.sheets.read_business_sheet — no
live Google Sheets API calls.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

BIZ_ROWS = [
    {"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"},
    {"ID": "BIZ-002", "Название": "Визы и документы", "Статус": "active"},
    {"ID": "BIZ-004", "Название": "Инвестиции", "Статус": "hold"},
]


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.business_builder import resolve_business
    return resolve_business


class TestResolveBusinessById(unittest.TestCase):
    def test_exact_id(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("BIZ-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_id_lowercase(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("biz-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_id_with_surrounding_spaces(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("  BIZ-001  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")


class TestResolveBusinessByName(unittest.TestCase):
    def test_exact_name(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("Узаконение недвижимости")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_name_lowercase(self):
        """Production incident case: 'узаконение недвижимости'."""
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("узаконение недвижимости")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_name_uppercase(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("УЗАКОНЕНИЕ НЕДВИЖИМОСТИ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_name_with_surrounding_and_extra_internal_spaces(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("  Узаконение   недвижимости  ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["biz_id"], "BIZ-001")

    def test_returns_display_name(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("BIZ-002")
        self.assertEqual(result["biz_name"], "Визы и документы")


class TestResolveBusinessNotFound(unittest.TestCase):
    def test_unknown_business_returns_not_found_with_active_list(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("Совершенно другой бизнес")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_found")
        ids = {b["id"] for b in result["active_businesses"]}
        self.assertEqual(ids, {"BIZ-001", "BIZ-002"})  # BIZ-004 is "hold", excluded

    def test_empty_string_is_not_found(self):
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_found")

    def test_no_fuzzy_matching_partial_name_fails(self):
        """'Узаконение' alone (partial) must NOT match 'Узаконение
        недвижимости' — no fuzzy matching, to avoid attaching a client
        to the wrong business."""
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=BIZ_ROWS):
            result = resolve_business("Узаконение")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_found")


class TestResolveBusinessAmbiguous(unittest.TestCase):
    def test_ambiguous_when_normalization_collapses_two_names(self):
        rows = BIZ_ROWS + [
            {"ID": "BIZ-005", "Название": "узаконение недвижимости", "Статус": "active"},
        ]
        resolve_business = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = resolve_business("Узаконение недвижимости")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ambiguous")


class TestResolveBusinessNoLiveApi(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.business_builder  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
