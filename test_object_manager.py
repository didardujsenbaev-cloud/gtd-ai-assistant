"""
Phase 30C: behavioral tests for business_core.object_manager (new
canonical owner of OBJECT_REGISTRY, ADR-014/Phase 30B).

No live Sheets/network calls anywhere in this file — all Google Sheets
access is mocked via business_core.sheets.get_business_sheet.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

HEADERS = [
    "OBJ ID", "Client ID", "Biz ID", "City", "Address",
    "Cadastral Number", "Area m2", "Object Type", "Object Status",
    "Current Service ID", "Roadmap ID", "Drive Folder ID",
    "Google Drive", "Notes", "Created At", "Last Updated",
]


def _fresh_om():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.object_manager as om
    return om


def _obj_row(
    object_id="OBJ-001", client_id="PRS-001", biz_id="BIZ-001",
    city="Алматы", address="ул. Тест 1", cadastral="", area="",
    object_type="", status="new", current_service="", roadmap_id="",
    drive_folder_id="", drive_url="", notes="",
):
    row = [""] * len(HEADERS)
    row[HEADERS.index("OBJ ID")] = object_id
    row[HEADERS.index("Client ID")] = client_id
    row[HEADERS.index("Biz ID")] = biz_id
    row[HEADERS.index("City")] = city
    row[HEADERS.index("Address")] = address
    row[HEADERS.index("Cadastral Number")] = cadastral
    row[HEADERS.index("Area m2")] = area
    row[HEADERS.index("Object Type")] = object_type
    row[HEADERS.index("Object Status")] = status
    row[HEADERS.index("Current Service ID")] = current_service
    row[HEADERS.index("Roadmap ID")] = roadmap_id
    row[HEADERS.index("Drive Folder ID")] = drive_folder_id
    row[HEADERS.index("Google Drive")] = drive_url
    row[HEADERS.index("Notes")] = notes
    return row


def _make_sheet(rows=None):
    ws = MagicMock()
    all_rows = [HEADERS] + (rows or [])
    ws.get_all_values.return_value = all_rows
    ws.row_values.return_value = HEADERS
    return ws


# ────────────────────────────────────────────────────────────
# Normalization
# ────────────────────────────────────────────────────────────

class TestNormalization(unittest.TestCase):
    def test_nfkc_normalization(self):
        om = _fresh_om()
        # full-width "Ａ" normalizes to ASCII "A" under NFKC.
        self.assertEqual(om.normalize_object_address("Ａ"), "a")

    def test_whitespace_collapse(self):
        om = _fresh_om()
        self.assertEqual(
            om.normalize_object_address("ул.   Абая    10"),
            om.normalize_object_address("ул. Абая 10"),
        )

    def test_casefold(self):
        om = _fresh_om()
        self.assertEqual(om.normalize_object_city("АЛМАТЫ"), om.normalize_object_city("алматы"))

    def test_cadastral_separators_normalize(self):
        om = _fresh_om()
        self.assertEqual(
            om.normalize_cadastral_number("12:34-56/78"),
            om.normalize_cadastral_number("12345678"),
        )


# ────────────────────────────────────────────────────────────
# Status
# ────────────────────────────────────────────────────────────

class TestStatusValidation(unittest.TestCase):
    def test_omitted_defaults_to_new(self):
        om = _fresh_om()
        self.assertEqual(om.validate_object_status(None), "new")

    def test_canonical_statuses_accepted(self):
        om = _fresh_om()
        for s in ("new", "active", "on_hold", "completed", "cancelled"):
            self.assertEqual(om.validate_object_status(s), s)

    def test_unknown_rejected(self):
        om = _fresh_om()
        with self.assertRaises(ValueError):
            om.validate_object_status("archived")

    def test_unknown_never_written(self):
        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", status="archived",
            )
        self.assertFalse(result["ok"])
        mock_append.assert_not_called()


# ────────────────────────────────────────────────────────────
# Duplicate policy
# ────────────────────────────────────────────────────────────

class TestDuplicatePolicy(unittest.TestCase):
    def test_tier1_same_biz_cadastral_reuses(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-100", biz_id="BIZ-001", cadastral="12:34:56")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-001", client_id="PRS-999", city="Другой город",
                address="Другой адрес", cadastral_number="12-34-56",
            )
        self.assertEqual([m["object_id"] for m in matches], ["OBJ-100"])

    def test_tier1_different_business_creates_new(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-100", biz_id="BIZ-001", cadastral="12:34:56")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-002", client_id="PRS-001", city="Алматы",
                address="ул. Тест 1", cadastral_number="12:34:56",
            )
        self.assertEqual(matches, [])

    def test_tier1_ignores_client_and_address_differences(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-100", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Старая 1", cadastral="12:34:56")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-001", client_id="PRS-999", city="Астана",
                address="ул. Новая 99", cadastral_number="12:34:56",
            )
        self.assertEqual([m["object_id"] for m in matches], ["OBJ-100"])

    def test_tier2_same_biz_client_city_address_reuses(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-200", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1", cadastral="")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-001", client_id="PRS-001", city="Алматы",
                address="ул. Тест 1",
            )
        self.assertEqual([m["object_id"] for m in matches], ["OBJ-200"])

    def test_tier2_different_client_creates_new(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-200", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1", cadastral="")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-001", client_id="PRS-002", city="Алматы",
                address="ул. Тест 1",
            )
        self.assertEqual(matches, [])

    def test_tier2_different_business_creates_new(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-200", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1", cadastral="")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            matches = om.find_duplicate_objects(
                biz_id="BIZ-002", client_id="PRS-001", city="Алматы",
                address="ул. Тест 1",
            )
        self.assertEqual(matches, [])

    def test_multiple_matches_integrity_error(self):
        om = _fresh_om()
        rows = [
            _obj_row(object_id="OBJ-300", biz_id="BIZ-001", cadastral="12:34:56"),
            _obj_row(object_id="OBJ-301", biz_id="BIZ-001", cadastral="12-34-56"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", cadastral_number="12:34:56",
            )
        self.assertFalse(result["ok"])
        self.assertIn("OBJ-300", result["matching_object_ids"])
        self.assertIn("OBJ-301", result["matching_object_ids"])
        mock_append.assert_not_called()

    def test_no_write_on_reuse(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-400", biz_id="BIZ-001", cadastral="12:34:56")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", cadastral_number="12:34:56",
            )
        self.assertTrue(result["object_reused"])
        mock_append.assert_not_called()

    def test_no_write_on_integrity_error(self):
        om = _fresh_om()
        rows = [
            _obj_row(object_id="OBJ-500", biz_id="BIZ-001", cadastral="1"),
            _obj_row(object_id="OBJ-501", biz_id="BIZ-001", cadastral="1"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)), \
             patch("business_core.sheets.append_business_row") as mock_append:
            om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", cadastral_number="1",
            )
        mock_append.assert_not_called()


# ────────────────────────────────────────────────────────────
# Creation
# ────────────────────────────────────────────────────────────

class TestCreation(unittest.TestCase):
    def test_first_call_creates(self):
        om = _fresh_om()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch.object(om, "generate_object_id", return_value="OBJ-901"):
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы", address="ул. Новая 1",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["object_created"])
        mock_append.assert_called_once()

    def test_repeated_call_reuses(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-902", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы", address="ул. Тест 1",
            )
        self.assertTrue(result["object_reused"])
        mock_append.assert_not_called()

    def test_mismatch_warnings(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-903", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1", object_type="дом")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", object_type="квартира",
            )
        self.assertTrue(result["object_reused"])
        self.assertTrue(any("object_type" in w for w in result["warnings"]))

    def test_existing_row_untouched(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-904", biz_id="BIZ-001", client_id="PRS-001",
                          city="Алматы", address="ул. Тест 1")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)) as mock_get_sheet:
            om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы",
                address="ул. Тест 1", object_type="другое",
            )
        # No update_cell ever called on the sheet mock returned.
        sheet = mock_get_sheet.return_value
        sheet.update_cell.assert_not_called()

    def test_header_mapped_write(self):
        om = _fresh_om()
        captured = {}

        def capture(key, row):
            captured["key"] = key
            captured["row"] = row

        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch.object(om, "generate_object_id", return_value="OBJ-905"):
            om.create_object_record(
                client_id="PRS-001", biz_id="BIZ-001", city="Алматы", address="ул. Новая 1",
                object_type="дом",
            )
        idx = {h: i for i, h in enumerate(HEADERS)}
        self.assertEqual(captured["row"][idx["OBJ ID"]], "OBJ-905")
        self.assertEqual(captured["row"][idx["Object Type"]], "дом")
        self.assertEqual(captured["row"][idx["Object Status"]], "new")

    def test_required_fields_validated(self):
        om = _fresh_om()
        result = om.create_object_record(client_id="", biz_id="BIZ-001", city="Алматы", address="ул. 1")
        self.assertFalse(result["ok"])


# ────────────────────────────────────────────────────────────
# Read APIs
# ────────────────────────────────────────────────────────────

class TestReadApis(unittest.TestCase):
    def test_find_by_id(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.find_object_by_id("OBJ-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["object_id"], "OBJ-001")

    def test_list_by_business(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", biz_id="BIZ-001"), _obj_row(object_id="OBJ-002", biz_id="BIZ-002")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.find_objects_by_biz("BIZ-001")
        self.assertEqual([r["object_id"] for r in result], ["OBJ-001"])

    def test_list_by_client(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", client_id="PRS-001"), _obj_row(object_id="OBJ-002", client_id="PRS-002")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.find_objects_by_client("PRS-001")
        self.assertEqual([r["object_id"] for r in result], ["OBJ-001"])

    def test_status_filter(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", status="new"), _obj_row(object_id="OBJ-002", status="completed")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.list_objects(status="completed")
        self.assertEqual([r["object_id"] for r in result], ["OBJ-002"])

    def test_canonical_row_shape(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet(rows)):
            result = om.find_object_by_id("OBJ-001")
        expected_keys = {
            "row_num", "object_id", "client_id", "biz_id", "city", "address",
            "cadastral_number", "area_m2", "object_type", "status",
            "current_service_id", "roadmap_id", "drive_folder_id", "drive_url",
            "notes", "created_at", "last_updated",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ────────────────────────────────────────────────────────────
# Updates
# ────────────────────────────────────────────────────────────

class TestUpdateObjectFields(unittest.TestCase):
    def test_allowed_fields_update(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_object_fields("OBJ-001", {"address": "новый адрес"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated_fields"], ["address"])
        sheet.update_cell.assert_called()

    def test_disallowed_fields_rejected(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_object_fields("OBJ-001", {"client_id": "PRS-999"})
        self.assertFalse(result["ok"])
        sheet.update_cell.assert_not_called()

    def test_all_or_nothing(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_object_fields("OBJ-001", {"address": "x", "biz_id": "y"})
        self.assertFalse(result["ok"])
        sheet.update_cell.assert_not_called()

    def test_last_updated_changed(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            om.update_object_fields("OBJ-001", {"notes": "новые заметки"})
        last_updated_col = HEADERS.index("Last Updated") + 1
        calls = [c for c in sheet.update_cell.call_args_list if c.args[1] == last_updated_col]
        self.assertEqual(len(calls), 1)

    def test_unrelated_fields_preserved(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", city="Алматы", object_type="дом")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            om.update_object_fields("OBJ-001", {"notes": "x"})
        city_col = HEADERS.index("City") + 1
        for call in sheet.update_cell.call_args_list:
            self.assertNotEqual(call.args[1], city_col)

    def test_drive_reference_only_if_empty(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", drive_folder_id="EXISTING")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_object_drive_info("OBJ-001", folder_id="NEW-ID", only_if_empty=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["updated"])
        sheet.update_cell.assert_not_called()

    def test_roadmap_reference_only_if_empty(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001", roadmap_id="RM-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_object_roadmap_id("OBJ-001", "RM-999", only_if_empty=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["updated"])
        sheet.update_cell.assert_not_called()

    def test_repeated_same_reference_idempotent(self):
        om = _fresh_om()
        rows = [_obj_row(object_id="OBJ-001")]
        sheet = _make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            r1 = om.update_object_drive_info("OBJ-001", folder_id="F1", folder_url="U1")
            self.assertTrue(r1["updated"])
            # second call against the SAME (now-empty-again mock) sheet is
            # a separate mock state, but only_if_empty semantics are
            # verified by test_drive_reference_only_if_empty above; here
            # we assert the call itself is safe/idempotent (no exception).
            r2 = om.update_object_drive_info("OBJ-001", folder_id="F1", folder_url="U1")
            self.assertTrue(r2["ok"])


# ────────────────────────────────────────────────────────────
# Wrappers (business_builder compatibility layer)
# ────────────────────────────────────────────────────────────

class TestBusinessBuilderWrapperDelegation(unittest.TestCase):
    def _fresh_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    def test_wrappers_delegate(self):
        bb = self._fresh_bb()
        with patch("business_core.object_manager.create_object_record",
                   return_value={"ok": True, "object_id": "OBJ-1", "error": None,
                                 "object_created": True, "object_reused": False, "warnings": []}) as mock_create:
            result = bb.create_object_record(client_id="PRS-001", biz_id="BIZ-001", city="Алматы", address="x")
        mock_create.assert_called_once()
        self.assertEqual(result["obj_id"], "OBJ-1")

    def test_wrappers_preserve_signatures(self):
        bb = self._fresh_bb()
        import inspect
        sig = inspect.signature(bb.create_object_record)
        self.assertIn("client_id", sig.parameters)
        self.assertIn("biz_id", sig.parameters)
        self.assertIn("city", sig.parameters)
        self.assertIn("address", sig.parameters)

    def test_wrappers_perform_no_registry_access(self):
        bb = self._fresh_bb()
        import inspect
        src = inspect.getsource(bb.find_object_by_id)
        self.assertNotIn("get_business_sheet", src)


# ────────────────────────────────────────────────────────────
# Network safety
# ────────────────────────────────────────────────────────────

class TestNoLiveNetwork(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.object_manager  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
