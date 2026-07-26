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


if __name__ == "__main__":
    unittest.main()
