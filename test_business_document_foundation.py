"""
Tests for Phase 37D — Document Domain Foundation: the Document
orchestration section of business_core/business_builder.py (ADR-020).

Covers _validate_document_relations, register_document,
upload_and_register_document, update_document_admin_fields (wrapper),
and transition_document_status. Low-level document_manager.py behavior
is covered separately in test_document_manager.py — here we only mock
its return values to exercise the orchestration/cross-domain policy
layer in isolation.

No live Sheets/Drive calls — mocks only. Registered in conftest.py's
hard socket-block set (Phase 37D, ADR-020 §27).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb  # noqa: E402


def _biz_rows(biz_id="BIZ-001"):
    return [{"ID": biz_id, "Name": "Test Biz"}]


def _read_business_sheet_side_effect(rows_by_sheet):
    def _side_effect(sheet_name):
        return rows_by_sheet.get(sheet_name, [])
    return _side_effect


class TestValidateDocumentRelations(unittest.TestCase):

    def test_business_missing(self):
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect({})):
            result = bb._validate_document_relations("BIZ-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_minimal_valid_no_optional_relations(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_document_relations("BIZ-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["business_id"], "BIZ-001")
        self.assertEqual(result["resolved"]["client_id"], "")

    def test_invalid_client(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = bb._validate_document_relations("BIZ-001", client_id="PRS-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_invalid_object(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.object_manager.find_object_by_id", return_value=None):
            result = bb._validate_document_relations("BIZ-001", object_id="OBJ-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_invalid_roadmap(self):
        rows = {"biz_registry": _biz_rows(), "roadmaps": []}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_document_relations("BIZ-001", roadmap_id="RM-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_invalid_stage(self):
        rows = {"biz_registry": _biz_rows(), "roadmap_stages": []}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_document_relations("BIZ-001", stage_id="STG-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_invalid_template(self):
        rows = {"biz_registry": _biz_rows(), "document_template_registry": []}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_document_relations("BIZ-001", document_template_id="DTPL-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_contradiction_roadmap_disagrees_with_stage(self):
        rows = {
            "biz_registry": _biz_rows(),
            "roadmap_stages": [{"Stage ID": "STG-001", "Roadmap ID": "RM-001"}],
        }
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_document_relations("BIZ-001", stage_id="STG-001", roadmap_id="RM-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_derivation_cascade_from_stage_only(self):
        rows = {
            "biz_registry": _biz_rows(),
            "roadmap_stages": [{"Stage ID": "STG-001", "Roadmap ID": "RM-001"}],
            "roadmaps": [{"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Object ID": "OBJ-001"}],
        }
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.object_manager.find_object_by_id", return_value={"biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.person_manager.find_person_by_id", return_value={"biz_ids": ["BIZ-001"]}):
            result = bb._validate_document_relations("BIZ-001", stage_id="STG-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["roadmap_id"], "RM-001")
        self.assertEqual(result["resolved"]["object_id"], "OBJ-001")
        self.assertEqual(result["resolved"]["client_id"], "PRS-001")


class TestRegisterDocument(unittest.TestCase):

    def _patch_relations_ok(self):
        return patch.object(
            bb, "_validate_document_relations",
            return_value={"ok": True, "code": "", "error": None, "resolved": {
                "business_id": "BIZ-001", "client_id": "", "object_id": "",
                "roadmap_id": "", "stage_id": "", "document_template_id": "",
            }},
        )

    def test_missing_business_id(self):
        result = bb.register_document("", "Title", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_missing_document_name(self):
        result = bb.register_document("BIZ-001", "", "")
        self.assertFalse(result["ok"])

    def test_relation_validation_failure_propagates(self):
        with patch.object(
            bb, "_validate_document_relations",
            return_value={"ok": False, "code": "DOCUMENT_ENTITY_RELATION_MISMATCH", "error": "bad", "resolved": None},
        ):
            result = bb.register_document("BIZ-001", "Title", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ENTITY_RELATION_MISMATCH")

    def test_valid_minimal_registration(self):
        saved = {
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "business_id": "BIZ-001", "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            "document_template_id": "", "document_name": "Title", "status": "uploaded",
            "drive_file_id": "", "drive_file_url": "", "file_name": "", "mime_type": "",
        }
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[]), \
             patch("business_core.document_manager.create_document", return_value={"ok": True, "document_id": "DREG-001", "code": "DOCUMENT_CREATED", "error": None}), \
             patch("business_core.document_manager.find_document_by_id", return_value=saved):
            result = bb.register_document("BIZ-001", "Title", "")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_REGISTERED")
        self.assertTrue(result["created"])
        self.assertEqual(result["document_id"], "DREG-001")

    def test_persistence_failure_propagates(self):
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[]), \
             patch("business_core.document_manager.create_document", return_value={"ok": False, "document_id": "", "code": "", "error": "boom"}):
            result = bb.register_document("BIZ-001", "Title", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_PERSISTENCE_FAILED")
        self.assertTrue(result["retry_safe"])

    def test_post_write_verification_row_missing(self):
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[]), \
             patch("business_core.document_manager.create_document", return_value={"ok": True, "document_id": "DREG-001", "code": "DOCUMENT_CREATED", "error": None}), \
             patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.register_document("BIZ-001", "Title", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_post_write_verification_field_mismatch(self):
        saved = {
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "business_id": "BIZ-999",  # mismatch
            "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            "document_template_id": "", "document_name": "Title", "status": "uploaded",
            "drive_file_id": "", "drive_file_url": "", "file_name": "", "mime_type": "",
        }
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[]), \
             patch("business_core.document_manager.create_document", return_value={"ok": True, "document_id": "DREG-001", "code": "DOCUMENT_CREATED", "error": None}), \
             patch("business_core.document_manager.find_document_by_id", return_value=saved):
            result = bb.register_document("BIZ-001", "Title", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_POST_WRITE_VERIFICATION_FAILED")

    def test_drive_file_id_zero_matches_creates(self):
        saved = {
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "business_id": "BIZ-001", "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            "document_template_id": "", "document_name": "Title", "status": "uploaded",
            "drive_file_id": "FILE1", "drive_file_url": "", "file_name": "", "mime_type": "",
        }
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[]) as mock_lookup, \
             patch("business_core.document_manager.create_document", return_value={"ok": True, "document_id": "DREG-001", "code": "DOCUMENT_CREATED", "error": None}), \
             patch("business_core.document_manager.find_document_by_id", return_value=saved):
            result = bb.register_document("BIZ-001", "Title", "FILE1")
        mock_lookup.assert_called_once_with("FILE1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])

    def test_drive_file_id_one_compatible_match_reuses(self):
        existing = {
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "business_id": "BIZ-001", "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            "status": "uploaded",
        }
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[existing]), \
             patch("business_core.document_manager.create_document") as mock_create:
            result = bb.register_document("BIZ-001", "Title", "FILE1")
        mock_create.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_REUSED")
        self.assertTrue(result["reused"])
        self.assertEqual(result["document_id"], "DREG-001")

    def test_drive_file_id_one_incompatible_match_blocks(self):
        existing = {
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "business_id": "BIZ-002", "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            "status": "uploaded",
        }
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[existing]), \
             patch("business_core.document_manager.create_document") as mock_create:
            result = bb.register_document("BIZ-001", "Title", "FILE1")
        mock_create.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RELATION_CONFLICT_ON_REUSE")

    def test_drive_file_id_multiple_matches_blocks_with_no_first_pick(self):
        m1 = {"document_id": "DREG-001", "business_id": "BIZ-001"}
        m2 = {"document_id": "DREG-002", "business_id": "BIZ-001"}
        with self._patch_relations_ok(), \
             patch("business_core.document_manager.find_documents_by_drive_file_id", return_value=[m1, m2]), \
             patch("business_core.document_manager.create_document") as mock_create:
            result = bb.register_document("BIZ-001", "Title", "FILE1")
        mock_create.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES")
        self.assertEqual(set(result["conflicting_document_ids"]), {"DREG-001", "DREG-002"})
        self.assertTrue(result["retry_safe"])


class TestUploadAndRegisterDocument(unittest.TestCase):

    def test_success_remaps_to_uploaded_code(self):
        registered = {
            "ok": True, "code": "DOCUMENT_REGISTERED", "error": None,
            "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
            "document_template_id": "", "client_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
        }
        with patch.object(bb, "register_document", return_value=registered):
            result = bb.upload_and_register_document("BIZ-001", "Title", "FILE1", "file.pdf", "application/pdf", "https://x")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_UPLOADED")
        self.assertTrue(result["uploaded"])
        self.assertTrue(result["created"])

    def test_persistence_failure_propagates_for_caller_compensation(self):
        failed = {"ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED", "error": "boom", "document_id": "", "business_id": "BIZ-001"}
        with patch.object(bb, "register_document", return_value=failed):
            result = bb.upload_and_register_document("BIZ-001", "Title", "FILE1", "file.pdf", "application/pdf", "https://x")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_PERSISTENCE_FAILED")
        self.assertFalse(result["compensation_attempted"])

    def test_post_write_verification_failure_propagates(self):
        failed = {"ok": False, "code": "DOCUMENT_POST_WRITE_VERIFICATION_FAILED", "error": "mismatch", "document_id": "DREG-001"}
        with patch.object(bb, "register_document", return_value=failed):
            result = bb.upload_and_register_document("BIZ-001", "Title", "FILE1", "file.pdf", "application/pdf", "https://x")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_POST_WRITE_VERIFICATION_FAILED")
        self.assertTrue(result["uploaded"])


class TestUpdateDocumentAdminFieldsOrchestration(unittest.TestCase):

    def test_not_found(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.update_document_admin_fields("DREG-404", {"Document Name": "X"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_delegates_to_low_level(self):
        doc = {"document_id": "DREG-001", "business_id": "BIZ-001"}
        with patch("business_core.document_manager.find_document_by_id", return_value=doc), \
             patch("business_core.document_manager.update_document_admin_fields", return_value={"ok": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None, "changed": True}):
            result = bb.update_document_admin_fields("DREG-001", {"Document Name": "New"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UPDATED")
        self.assertEqual(result["business_id"], "BIZ-001")


class TestUpdateDocumentAdminFieldsWrapperMalformedResultHardening(unittest.TestCase):
    """Phase 17E-2A5-H1: truth-table proof that the wrapper never
    raises on a malformed document_manager result, never synthesizes
    a new success code, and preserves the manager's own deterministic
    codes exactly."""

    _DOC = {"document_id": "DREG-001", "business_id": "BIZ-001"}

    def _call(self, low_level_return):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._DOC), \
             patch("business_core.document_manager.update_document_admin_fields", return_value=low_level_return):
            return bb.update_document_admin_fields("DREG-001", {"Document Name": "New"})

    def test_1_valid_success_dict(self):
        result = self._call({"ok": True, "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None})
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UPDATED")

    def test_2_valid_unchanged_dict(self):
        result = self._call({"ok": True, "changed": False, "code": "DOCUMENT_ADMIN_FIELDS_UNCHANGED", "error": None})
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UNCHANGED")

    def test_3_exception_dict_ok_false_blank_code(self):
        result = self._call({"ok": False, "changed": False, "updated_fields": (), "code": "", "error": "Infrastructure failure"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "")

    def test_4_document_not_found_code(self):
        result = self._call({"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_5_immutable_failure_code(self):
        result = self._call({"ok": False, "changed": False, "code": "DOCUMENT_IMMUTABLE_FIELD_CONFLICT", "error": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_IMMUTABLE_FIELD_CONFLICT")

    def test_6_known_validation_failure_code(self):
        result = self._call({"ok": False, "changed": False, "code": "INVALID_DOCUMENT_ADMIN_FIELD", "error": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_ADMIN_FIELD")

    def test_7_dict_missing_ok(self):
        result = self._call({"changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ADMIN_FIELDS_UPDATED")

    def test_8_empty_dict(self):
        result = self._call({})
        self.assertFalse(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "")

    def test_9_non_dict_none(self):
        result = self._call(None)
        self.assertFalse(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "")

    def test_10_non_dict_string(self):
        result = self._call("not a dict")
        self.assertFalse(result["ok"])

    def test_10_non_dict_list(self):
        result = self._call(["ok", True])
        self.assertFalse(result["ok"])

    def test_10_non_dict_integer(self):
        result = self._call(42)
        self.assertFalse(result["ok"])

    def test_11_truthy_non_boolean_ok(self):
        result = self._call({"ok": "true", "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None})
        self.assertIs(result["ok"], False)

    def test_12_truthy_non_boolean_changed(self):
        result = self._call({"ok": True, "changed": 1, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None})
        self.assertIs(result["changed"], False)

    def test_malformed_output_never_raises(self):
        for bad in (None, "x", [], 0, {}, {"ok": object()}):
            try:
                self._call(bad)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"wrapper raised on malformed input {bad!r}: {exc!r}")

    def test_no_code_synthesis_on_failure(self):
        result = self._call({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})
        self.assertNotIn(result["code"], ("DOCUMENT_ADMIN_FIELDS_UPDATED", "DOCUMENT_ADMIN_FIELDS_UNCHANGED"))

    def test_retry_safe_remains_true(self):
        result = self._call({"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})
        self.assertTrue(result["retry_safe"])

    def test_output_keys_unchanged(self):
        result = self._call({"ok": True, "changed": True, "code": "DOCUMENT_ADMIN_FIELDS_UPDATED", "error": None})
        self.assertIn("ok", result)
        self.assertIn("code", result)
        self.assertIn("error", result)
        self.assertIn("document_id", result)
        self.assertIn("business_id", result)
        self.assertIn("changed", result)
        self.assertIn("retry_safe", result)


class TestTransitionDocumentStatus(unittest.TestCase):

    def _doc(self, status):
        return {"document_id": "DREG-001", "business_id": "BIZ-001", "status": status}

    def test_not_found(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.transition_document_status("DREG-404", "approved")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_invalid_status(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("uploaded")):
            result = bb.transition_document_status("DREG-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_STATUS")

    def test_terminal_reopen_protected_from_archived(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("archived")):
            result = bb.transition_document_status("DREG-001", "uploaded")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_terminal_reopen_protected_from_superseded(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("superseded")):
            result = bb.transition_document_status("DREG-001", "approved")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_archived_to_archived_allowed_as_noop(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("archived")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": False, "code": "DOCUMENT_STATUS_UNCHANGED", "error": None}):
            result = bb.transition_document_status("DREG-001", "archived")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_STATUS_UNCHANGED")

    def test_invalid_ordinary_transition_approved_to_uploaded(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("approved")):
            result = bb.transition_document_status("DREG-001", "uploaded")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_TRANSITION")

    def test_valid_transition_uploaded_to_under_review(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("uploaded")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None}) as mock_update:
            result = bb.transition_document_status("DREG-001", "under_review")
        mock_update.assert_called_once_with("DREG-001", "under_review")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_STATUS_UPDATED")
        self.assertEqual(result["previous_status"], "uploaded")
        self.assertEqual(result["final_status"], "under_review")

    def test_valid_transition_under_review_to_rejected(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("under_review")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None}):
            result = bb.transition_document_status("DREG-001", "rejected")
        self.assertTrue(result["ok"])

    def test_valid_transition_rejected_to_uploaded(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("rejected")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None}):
            result = bb.transition_document_status("DREG-001", "uploaded")
        self.assertTrue(result["ok"])

    def test_unchanged_same_status_noop(self):
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("uploaded")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": False, "code": "DOCUMENT_STATUS_UNCHANGED", "error": None}):
            result = bb.transition_document_status("DREG-001", "uploaded")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_STATUS_UNCHANGED")
        self.assertFalse(result["changed"])

    def test_no_review_or_drive_mutation_side_effects(self):
        """transition_document_status must call only update_document_status —
        no review-field write, no Drive call, no relation write."""
        with patch("business_core.document_manager.find_document_by_id", return_value=self._doc("uploaded")), \
             patch("business_core.document_manager.update_document_status", return_value={"ok": True, "changed": True, "code": "DOCUMENT_STATUS_UPDATED", "error": None}), \
             patch("business_core.document_manager.update_document_admin_fields") as mock_admin:
            bb.transition_document_status("DREG-001", "under_review")
        mock_admin.assert_not_called()


class TestValidateDocumentUploadRequest(unittest.TestCase):
    """Phase 37F.1 (ADR-020 §12): the canonical pre-Drive-upload
    validation boundary. Delegates to document_upload_validation.py —
    these tests only confirm the orchestration wrapping (result-dict
    shape, code selection), not the validation rules themselves
    (covered in test_document_upload_validation.py)."""

    def test_valid_file_returns_document_upload_validated(self):
        result = bb.validate_document_upload_request("passport.pdf", "application/pdf", 1024)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_UPLOAD_VALIDATED")

    def test_analysis_unsupported_still_ok(self):
        result = bb.validate_document_upload_request("contract.rtf", "application/rtf", 1024)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ANALYSIS_UNSUPPORTED")
        self.assertEqual(result["analysis_status"], "unsupported")

    def test_invalid_filename_rejected(self):
        result = bb.validate_document_upload_request("", "application/pdf", 1024)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_too_large_rejected(self):
        result = bb.validate_document_upload_request("passport.pdf", "application/pdf", 999_999_999_999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_TOO_LARGE")

    def test_dangerous_type_rejected(self):
        result = bb.validate_document_upload_request("setup.exe", "application/x-msdownload", 1024)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_DOCUMENT_STORAGE_TYPE")

    def test_no_drive_or_sheets_call(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=AssertionError("must not be called")), \
             patch("integrations.google_drive_adapter.get_drive_service", side_effect=AssertionError("must not be called")):
            result = bb.validate_document_upload_request("passport.pdf", "application/pdf", 1024)
        self.assertTrue(result["ok"])


class TestDriveUploadFailedResult(unittest.TestCase):
    def test_returns_drive_upload_failed_code(self):
        result = bb.document_drive_upload_failed_result("BIZ-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DRIVE_UPLOAD_FAILED")
        self.assertEqual(result["business_id"], "BIZ-001")

    def test_no_document_id_or_family_id(self):
        result = bb.document_drive_upload_failed_result()
        self.assertEqual(result["document_id"], "")
        self.assertEqual(result["document_family_id"], "")


class TestDocumentFileMetadataInvalidResult(unittest.TestCase):
    def test_compensation_succeeded(self):
        result = bb.document_file_metadata_invalid_result(
            business_id="BIZ-001", drive_file_id="FILE1",
            compensation_attempted=True, compensation_succeeded=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_FILE_METADATA_INVALID")
        self.assertTrue(result["compensation_attempted"])
        self.assertTrue(result["compensation_succeeded"])

    def test_compensation_failed(self):
        result = bb.document_file_metadata_invalid_result(
            business_id="BIZ-001", drive_file_id="FILE1",
            compensation_attempted=True, compensation_succeeded=False,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_FILE_METADATA_INVALID")
        self.assertTrue(result["compensation_attempted"])
        self.assertFalse(result["compensation_succeeded"])
        self.assertEqual(result["drive_file_id"], "FILE1")


class TestFinalizePersistenceFailureCompensation(unittest.TestCase):
    def test_compensation_success_returns_drive_upload_compensated(self):
        original = {"ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED", "error": "write failed", "business_id": "BIZ-001", "drive_file_id": "FILE1"}
        result = bb.finalize_persistence_failure_compensation(original, compensation_succeeded=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DRIVE_UPLOAD_COMPENSATED")
        self.assertTrue(result["compensation_attempted"])
        self.assertTrue(result["compensation_succeeded"])

    def test_compensation_failure_returns_orphaned_file_warning(self):
        original = {"ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED", "error": "write failed", "business_id": "BIZ-001", "drive_file_id": "FILE1"}
        result = bb.finalize_persistence_failure_compensation(original, compensation_succeeded=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING")
        self.assertTrue(result["compensation_attempted"])
        self.assertFalse(result["compensation_succeeded"])
        self.assertEqual(result["drive_file_id"], "FILE1")

    def test_never_claims_success_either_way(self):
        original = {"ok": False, "code": "DOCUMENT_PERSISTENCE_FAILED", "error": "x", "business_id": "BIZ-001", "drive_file_id": "FILE1"}
        for succeeded in (True, False):
            result = bb.finalize_persistence_failure_compensation(original, compensation_succeeded=succeeded)
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
