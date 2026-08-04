"""
Tests for Phase 37D — Document Domain Foundation: business_core/document_manager.py
(ADR-020). Covers Document ID/Family ID generation, low-level Document
creation, admin-field update rules, status persistence, and read-only
Drive-File-ID reuse lookups. No cross-entity eligibility, no Drive
orchestration — that's business_builder.py's job, covered separately
in test_business_document_foundation.py.

No live Sheets writes — mocks only, per ENGINEERING_STANDARDS.md
Testing Standards. Registered in conftest.py's hard socket-block set
(Phase 37D, ADR-020 §27) before this file's logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

DOC_HEADERS = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID", "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
]

DOC_ROW = [
    "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "", "",
    "", "Технический паспорт", "uploaded",
    "FILE1", "https://drive.google.com/file/d/FILE1/view", "passport.pdf", "application/pdf",
    "2026-01-01 00:00:00 UTC", "dida",
    "", "", "",
    "", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC",
]


def _fresh_dm():
    """Return business_core.document_manager. Deliberately does NOT wipe
    sys.modules — document_manager.py holds no cross-call state, and a
    broad sys.modules purge here would invalidate module identity for
    other test files' module-level imports (e.g. business_builder.py in
    test_business_document_foundation.py) sharing this test session."""
    import business_core.document_manager as dm
    return dm


def _make_sheet(headers, row, row_num=2, extra_rows=None):
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    all_values = [headers] + [row] + (extra_rows or [])
    sheet.get_all_values.return_value = all_values
    return sheet


class TestIdGeneration(unittest.TestCase):

    def test_document_and_family_id_empty_registry(self):
        dm = _fresh_dm()
        doc_id, fam_id = dm.compute_next_document_and_family_ids([])
        self.assertEqual(doc_id, "DREG-001")
        self.assertEqual(fam_id, "DFAM-001")

    def test_document_and_family_id_increment_independently(self):
        dm = _fresh_dm()
        all_values = [DOC_HEADERS, DOC_ROW]
        doc_id, fam_id = dm.compute_next_document_and_family_ids(all_values)
        self.assertEqual(doc_id, "DREG-002")
        self.assertEqual(fam_id, "DFAM-002")

    def test_family_id_generator_empty(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(dm.generate_next_family_id(), "DFAM-001")

    def test_family_id_generator_scans_family_column_only(self):
        """A high Document ID number must not affect the Family ID counter."""
        dm = _fresh_dm()
        row = list(DOC_ROW)
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        row[idx["Document ID"]] = "DREG-099"
        row[idx["Document Family ID"]] = "DFAM-005"
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, row]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(dm.generate_next_family_id(), "DFAM-006")

    def test_only_one_implementation_of_each_generator(self):
        """Guard against a duplicate ID-generation implementation
        appearing in document_registry_manager.py (ADR-020 §3/§7)."""
        drm_path = WORKSPACE / "business_core" / "document_registry_manager.py"
        src = drm_path.read_text(encoding="utf-8")
        self.assertNotIn("def compute_next_document_and_family_ids", src)
        self.assertNotIn("def generate_next_family_id", src)


class TestFindDocumentById(unittest.TestCase):

    def test_found(self):
        dm = _fresh_dm()
        row_dict = dict(zip(DOC_HEADERS, DOC_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            doc = dm.find_document_by_id("DREG-001")
        self.assertIsNotNone(doc)
        self.assertEqual(doc["document_id"], "DREG-001")
        self.assertEqual(doc["business_id"], "BIZ-001")
        self.assertEqual(doc["status"], "uploaded")

    def test_not_found(self):
        dm = _fresh_dm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(dm.find_document_by_id("DREG-999"))

    def test_blank_id_returns_none(self):
        dm = _fresh_dm()
        self.assertIsNone(dm.find_document_by_id(""))


class TestCreateDocument(unittest.TestCase):

    def test_missing_business_id_rejected(self):
        dm = _fresh_dm()
        result = dm.create_document("", "Title")
        self.assertFalse(result["ok"])

    def test_missing_document_name_rejected(self):
        dm = _fresh_dm()
        result = dm.create_document("BIZ-001", "")
        self.assertFalse(result["ok"])

    def test_invalid_status_rejected(self):
        dm = _fresh_dm()
        result = dm.create_document("BIZ-001", "Title", status="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_STATUS")

    def test_successful_creation(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS]
        sheet.row_values.return_value = DOC_HEADERS
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = dm.create_document("BIZ-001", "Title", drive_file_id="FILE1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["document_id"], "DREG-001")
        self.assertEqual(result["code"], "DOCUMENT_CREATED")
        mock_append.assert_called_once()
        row = mock_append.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(row[idx["Document ID"]], "DREG-001")
        self.assertEqual(row[idx["Document Family ID"]], "DFAM-001")
        self.assertEqual(row[idx["Version"]], "1")
        self.assertEqual(row[idx["Status"]], "uploaded")


class TestUpdateDocumentAdminFields(unittest.TestCase):

    def test_name_update_succeeds(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_admin_fields("DREG-001", {"Document Name": "New Name"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UPDATED")

    def test_unchanged_value_reports_unchanged(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_admin_fields("DREG-001", {"Document Name": "Технический паспорт"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UNCHANGED")

    def test_document_id_identity_conflict(self):
        dm = _fresh_dm()
        result = dm.update_document_admin_fields("DREG-001", {"Document ID": "DREG-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_IMMUTABLE_FIELD_CONFLICT")

    def test_business_id_identity_conflict(self):
        dm = _fresh_dm()
        result = dm.update_document_admin_fields("DREG-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_IMMUTABLE_FIELD_CONFLICT")

    def test_created_at_identity_conflict(self):
        dm = _fresh_dm()
        result = dm.update_document_admin_fields("DREG-001", {"Created At": "2027-01-01"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_IMMUTABLE_FIELD_CONFLICT")

    def test_document_family_id_version_immutable(self):
        dm = _fresh_dm()
        fam_result = dm.update_document_admin_fields("DREG-001", {"Document Family ID": "DFAM-999"})
        self.assertFalse(fam_result["ok"])
        self.assertEqual(fam_result["code"], "DOCUMENT_FAMILY_FIELD_IMMUTABLE")

        version_result = dm.update_document_admin_fields("DREG-001", {"Version": "2"})
        self.assertFalse(version_result["ok"])
        self.assertEqual(version_result["code"], "DOCUMENT_VERSION_FIELD_IMMUTABLE")

    def test_relation_fields_blocked(self):
        dm = _fresh_dm()
        for field in ("Client ID", "Object ID", "Roadmap ID", "Stage ID", "Document Template ID"):
            result = dm.update_document_admin_fields("DREG-001", {field: "X-001"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION")

    def test_drive_fields_blocked(self):
        dm = _fresh_dm()
        for field in ("Drive File ID", "Drive File URL", "File Name", "Mime Type", "Uploaded At", "Uploaded By"):
            result = dm.update_document_admin_fields("DREG-001", {field: "x"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "INVALID_DOCUMENT_ADMIN_FIELD")

    def test_status_blocked(self):
        dm = _fresh_dm()
        result = dm.update_document_admin_fields("DREG-001", {"Status": "approved"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_ADMIN_FIELD")

    def test_review_fields_blocked(self):
        dm = _fresh_dm()
        for field in ("Reviewed At", "Reviewed By", "Rejection Reason"):
            result = dm.update_document_admin_fields("DREG-001", {field: "x"})
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "INVALID_DOCUMENT_ADMIN_FIELD")

    def test_unknown_field_rejected(self):
        dm = _fresh_dm()
        result = dm.update_document_admin_fields("DREG-001", {"Bogus": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_ADMIN_FIELD")

    def test_not_found(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_admin_fields("DREG-999", {"Document Name": "X"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_mixed_invalid_and_valid_rejected_wholesale(self):
        """A single request mixing an immutable field with an otherwise
        valid field must be rejected entirely — never a partial write."""
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_admin_fields("DREG-001", {"Business ID": "BIZ-999", "Document Name": "New"})
        self.assertFalse(result["ok"])
        sheet.update_cell.assert_not_called()


_SECRET_NOTES_MARKER = "SECRET_NOTES_MARKER"
_SECRET_BIZ_MARKER = "BIZ-SECRET"
_SECRET_OBJECT_MARKER = "OBJECT-SECRET"
_SECRET_ROW_MARKER = "ROW-SECRET"
_SECRET_API_MARKER = "API-PAYLOAD-SECRET"
_ALL_SECRET_MARKERS = (
    _SECRET_NOTES_MARKER, _SECRET_BIZ_MARKER, _SECRET_OBJECT_MARKER,
    _SECRET_ROW_MARKER, _SECRET_API_MARKER,
)


def _boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_SECRET_NOTES_MARKER} and {_SECRET_BIZ_MARKER} "
        f"and {_SECRET_OBJECT_MARKER} and {_SECRET_ROW_MARKER} and {_SECRET_API_MARKER}"
    )


class TestDocumentManagerExceptionSecrecy(unittest.TestCase):
    """Phase 17E-2A5-H1: proves the two hardened exception sites in
    document_manager.py never leak exception text, document_id,
    Business ID, Object ID, Notes, or row/API payload content into
    logs or the returned structured result."""

    def _assert_no_secrets_logged(self, mock_log):
        for call in mock_log.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_find_document_row_exception_fixed_log_literal(self):
        dm = _fresh_dm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_secrets), \
             patch("business_core.document_manager.log.warning") as mock_log_warning:
            result = dm._find_document_row(f"DREG-{_SECRET_ROW_MARKER}")
        self.assertIsNone(result)
        mock_log_warning.assert_called_once_with("_find_document_row infrastructure failure")
        self._assert_no_secrets_logged(mock_log_warning)

    def test_notes_update_cell_exception_fixed_log_and_sanitized_result(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager.log.error") as mock_log_error:
            result = dm.update_document_admin_fields(
                "DREG-001", {"Notes": f"new-{_SECRET_NOTES_MARKER}"},
            )
        mock_log_error.assert_called_once_with("update_document_admin_fields infrastructure failure")
        self._assert_no_secrets_logged(mock_log_error)
        self.assertEqual(result, {
            "ok": False, "changed": False, "updated_fields": (), "code": "", "error": "Infrastructure failure",
        })

    def test_updated_at_update_cell_exception_fixed_log_and_sanitized_result(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))

        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        updated_at_col = idx["Updated At"] + 1

        def update_cell(row, col, value):
            if col == updated_at_col:
                _boom_with_secrets()

        sheet.update_cell.side_effect = update_cell
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager.log.error") as mock_log_error:
            result = dm.update_document_admin_fields("DREG-001", {"Document Name": "New Name"})
        mock_log_error.assert_called_once_with("update_document_admin_fields infrastructure failure")
        self._assert_no_secrets_logged(mock_log_error)
        self.assertEqual(result, {
            "ok": False, "changed": False, "updated_fields": (), "code": "", "error": "Infrastructure failure",
        })

    def test_manager_exception_result_shape_permits_sanitized_internal_value(self):
        """The sanitized 'Infrastructure failure' string is permitted
        INSIDE the manager's own returned result — it is never logged,
        and (per business_builder/mapper hardening in this same phase)
        never rendered to Telegram. This test only proves the manager's
        own contract, not downstream rendering."""
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        sheet.update_cell.side_effect = RuntimeError("boom")
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.document_manager.log.error"):
            result = dm.update_document_admin_fields("DREG-001", {"Notes": "x"})
        self.assertEqual(result["error"], "Infrastructure failure")
        self.assertEqual(set(result.keys()), {"ok", "changed", "updated_fields", "code", "error"})


class TestUpdateDocumentStatus(unittest.TestCase):

    def test_status_change(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_status("DREG-001", "under_review")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_unchanged_status(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS, list(DOC_ROW))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_status("DREG-001", "uploaded")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_invalid_status_rejected(self):
        dm = _fresh_dm()
        result = dm.update_document_status("DREG-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_STATUS")

    def test_not_found(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.update_document_status("DREG-999", "approved")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")


class TestFindDocumentsByDriveFileId(unittest.TestCase):

    def test_no_matches(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, DOC_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = dm.find_documents_by_drive_file_id("NOTFOUND")
        self.assertEqual(results, [])

    def test_one_match(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, DOC_ROW]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = dm.find_documents_by_drive_file_id("FILE1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["document_id"], "DREG-001")

    def test_multiple_matches(self):
        dm = _fresh_dm()
        row2 = list(DOC_ROW)
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        row2[idx["Document ID"]] = "DREG-002"
        row2[idx["Document Family ID"]] = "DFAM-002"
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, DOC_ROW, row2]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = dm.find_documents_by_drive_file_id("FILE1")
        self.assertEqual(len(results), 2)

    def test_archived_excluded_by_default(self):
        dm = _fresh_dm()
        archived_row = list(DOC_ROW)
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        archived_row[idx["Status"]] = "archived"
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, archived_row]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = dm.find_documents_by_drive_file_id("FILE1")
        self.assertEqual(results, [])

    def test_archived_included_when_requested(self):
        dm = _fresh_dm()
        archived_row = list(DOC_ROW)
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        archived_row[idx["Status"]] = "archived"
        sheet = MagicMock()
        sheet.get_all_values.return_value = [DOC_HEADERS, archived_row]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            results = dm.find_documents_by_drive_file_id("FILE1", exclude_archived=False)
        self.assertEqual(len(results), 1)

    def test_blank_id_returns_empty(self):
        dm = _fresh_dm()
        self.assertEqual(dm.find_documents_by_drive_file_id(""), [])


class TestNoHardDelete(unittest.TestCase):

    def test_no_delete_primitive_called_anywhere(self):
        path = WORKSPACE / "business_core" / "document_manager.py"
        src = path.read_text(encoding="utf-8")
        for forbidden in ("delete_rows", "delete_row", ".clear(", "batch_clear"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
