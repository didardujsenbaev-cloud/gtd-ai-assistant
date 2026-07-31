"""
Phase 16C.9C — Document Archive Domain Operation.

Covers:
  - business_core/document_manager.py: _document_row_to_dict mapping of
    the four Phase 16C.9B archive columns, and the new low-level
    archive_document_row() write.
  - business_core/business_builder.py: the new archive_document()
    domain orchestration (validation, idempotency, dry-run, post-write
    verification, failure codes, retry_safe semantics).
  - Architecture guards (source inspection) proving the Telegram layer
    never bypasses business_builder.archive_document().
  - A coverage-integration test proving SATISFYING_STATUSES already
    excludes "archived" with zero coverage-engine changes.

No live Sheets/Drive access — mocks only.
"""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from unittest.mock import MagicMock, patch

DOC_HEADERS_27 = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID", "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
    "Archived At", "Archived By", "Archive Reason", "Previous Status",
]

DOC_ROW_27 = [
    "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "STAGE-001",
    "DOC-001", "Технический паспорт", "uploaded",
    "FILE1", "https://drive.google.com/file/d/FILE1/view", "passport.pdf", "application/pdf",
    "2026-01-01 00:00:00 UTC", "dida",
    "", "", "",
    "", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC",
    "", "", "", "",
]

# A sparse legacy row shorter than the header row (pre-migration
# shape) — the 4 trailing archive cells are simply absent, not blank
# strings physically present in the row.
DOC_ROW_23_LEGACY = DOC_ROW_27[:23]

VALID_ACTOR = "telegram:12345"


def _fresh_dm():
    import business_core.document_manager as dm
    return dm


def _fresh_bb():
    import business_core.business_builder as bb
    return bb


def _make_sheet(headers, row, row_num=2, extra_rows=None):
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    all_values = [headers] + [row] + (extra_rows or [])
    sheet.get_all_values.return_value = all_values
    return sheet


def _row_dict(**overrides):
    row = dict(zip(DOC_HEADERS_27, DOC_ROW_27))
    row.update(overrides)
    return row


def _doc(**overrides):
    """A business_builder-level document dict, as returned by
    document_manager.find_document_by_id()."""
    d = {
        "document_id": "DREG-001", "document_family_id": "DFAM-001", "version": "1",
        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
        "roadmap_id": "RM-001", "stage_id": "STAGE-001", "document_template_id": "DOC-001",
        "document_name": "Технический паспорт", "status": "uploaded",
        "drive_file_id": "FILE1", "drive_file_url": "https://drive.google.com/file/d/FILE1/view",
        "file_name": "passport.pdf", "mime_type": "application/pdf",
        "uploaded_at": "2026-01-01 00:00:00 UTC", "uploaded_by": "dida",
        "reviewed_at": "", "reviewed_by": "", "rejection_reason": "",
        "notes": "", "created_at": "2026-01-01 00:00:00 UTC", "updated_at": "2026-01-01 00:00:00 UTC",
        "archived_at": "", "archived_by": "", "archive_reason": "", "previous_status": "",
    }
    d.update(overrides)
    return d


# ────────────────────────────────────────────────────────────
# 1-3. Mapping
# ────────────────────────────────────────────────────────────

class TestArchiveColumnMapping(unittest.TestCase):
    def test_27_column_row_maps_all_four_fields(self):
        dm = _fresh_dm()
        row = _row_dict(**{
            "Archived At": "2026-02-01 00:00:00 UTC", "Archived By": VALID_ACTOR,
            "Archive Reason": "Ошибочная загрузка", "Previous Status": "uploaded",
        })
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            doc = dm.find_document_by_id("DREG-001")
        self.assertEqual(doc["archived_at"], "2026-02-01 00:00:00 UTC")
        self.assertEqual(doc["archived_by"], VALID_ACTOR)
        self.assertEqual(doc["archive_reason"], "Ошибочная загрузка")
        self.assertEqual(doc["previous_status"], "uploaded")

    def test_sparse_legacy_row_maps_archive_fields_to_empty(self):
        dm = _fresh_dm()
        row = dict(zip(DOC_HEADERS_27[:23], DOC_ROW_23_LEGACY))
        # find_row_by_id's contract already returns "" for any header
        # not present in the row it read — simulate that exact shape.
        for h in DOC_HEADERS_27[23:]:
            row.setdefault(h, "")
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            doc = dm.find_document_by_id("DREG-001")
        self.assertEqual(doc["archived_at"], "")
        self.assertEqual(doc["archived_by"], "")
        self.assertEqual(doc["archive_reason"], "")
        self.assertEqual(doc["previous_status"], "")

    def test_existing_mappings_unchanged(self):
        dm = _fresh_dm()
        row = _row_dict()
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            doc = dm.find_document_by_id("DREG-001")
        self.assertEqual(doc["document_id"], "DREG-001")
        self.assertEqual(doc["business_id"], "BIZ-001")
        self.assertEqual(doc["status"], "uploaded")
        self.assertEqual(doc["notes"], "")
        self.assertEqual(doc["updated_at"], "2026-01-01 00:00:00 UTC")


# ────────────────────────────────────────────────────────────
# Manager-level: archive_document_row
# ────────────────────────────────────────────────────────────

class TestArchiveDocumentRowManager(unittest.TestCase):
    def test_one_update_business_row_call(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS_27, list(DOC_ROW_27))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.update_business_row") as mock_write:
            result = dm.archive_document_row(
                "DREG-001", archived_at="2026-02-01 00:00:00 UTC", archived_by=VALID_ACTOR,
                archive_reason="test reason", previous_status="uploaded",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVED")
        mock_write.assert_called_once()

    def test_exact_six_field_values(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS_27, list(DOC_ROW_27))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.update_business_row") as mock_write:
            dm.archive_document_row(
                "DREG-001", archived_at="2026-02-01 00:00:00 UTC", archived_by=VALID_ACTOR,
                archive_reason="test reason", previous_status="uploaded",
            )
        args, _ = mock_write.call_args
        sheet_key, row_num, values = args
        self.assertEqual(sheet_key, "document_registry")
        self.assertEqual(values, {
            "Status": "archived",
            "Archived At": "2026-02-01 00:00:00 UTC",
            "Archived By": VALID_ACTOR,
            "Archive Reason": "test reason",
            "Previous Status": "uploaded",
            "Updated At": "2026-02-01 00:00:00 UTC",
        })

    def test_no_update_cell_calls(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS_27, list(DOC_ROW_27))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.update_business_row"):
            dm.archive_document_row(
                "DREG-001", archived_at="x", archived_by=VALID_ACTOR,
                archive_reason="r", previous_status="uploaded",
            )
        sheet.update_cell.assert_not_called()

    def test_missing_row(self):
        dm = _fresh_dm()
        sheet = MagicMock()
        sheet.find.return_value = None
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = dm.archive_document_row(
                "DREG-999", archived_at="x", archived_by=VALID_ACTOR,
                archive_reason="r", previous_status="uploaded",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_write_exception_typed_failure(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS_27, list(DOC_ROW_27))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.update_business_row", side_effect=RuntimeError("boom")):
            result = dm.archive_document_row(
                "DREG-001", archived_at="x", archived_by=VALID_ACTOR,
                archive_reason="r", previous_status="uploaded",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_WRITE_FAILED")

    def test_no_raw_exception_leakage(self):
        dm = _fresh_dm()
        sheet = _make_sheet(DOC_HEADERS_27, list(DOC_ROW_27))
        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.update_business_row", side_effect=RuntimeError("sensitive detail")):
            result = dm.archive_document_row(
                "DREG-001", archived_at="x", archived_by=VALID_ACTOR,
                archive_reason="r", previous_status="uploaded",
            )
        self.assertIsNone(result["error"])
        self.assertNotIn("sensitive detail", str(result))

    def test_empty_document_id(self):
        dm = _fresh_dm()
        result = dm.archive_document_row(
            "", archived_at="x", archived_by=VALID_ACTOR, archive_reason="r", previous_status="uploaded",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")


# ────────────────────────────────────────────────────────────
# Builder-level: archive_document() — validation
# ────────────────────────────────────────────────────────────

class TestArchiveDocumentValidation(unittest.TestCase):
    def test_empty_document_id(self):
        bb = _fresh_bb()
        result = bb.archive_document("", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_whitespace_document_id(self):
        bb = _fresh_bb()
        result = bb.archive_document("   ", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_empty_reason(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_REASON_REQUIRED")

    def test_whitespace_reason(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "   ", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_REASON_REQUIRED")

    def test_reason_length_500_accepted(self):
        bb = _fresh_bb()
        reason = "x" * 500
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", reason, VALID_ACTOR, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_PREVIEW")

    def test_reason_length_501_rejected(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "x" * 501, VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_REASON_TOO_LONG")

    def test_exact_trimmed_reason_persisted(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "  hello world  ", VALID_ACTOR, dry_run=True)
        self.assertEqual(result["archive_reason"], "hello world")

    def test_valid_telegram_actor(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "reason", "telegram:1", dry_run=True)
        self.assertTrue(result["ok"])

    def test_username_actor_rejected(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "reason", "dida")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ACTOR_INVALID")

    def test_numeric_only_actor_rejected(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "reason", "12345")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ACTOR_INVALID")

    def test_empty_actor_rejected(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "reason", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ACTOR_INVALID")

    def test_whitespace_actor_rejected(self):
        bb = _fresh_bb()
        result = bb.archive_document("DREG-001", "reason", "  telegram:123  ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ACTOR_INVALID")

    def test_malformed_actor_variants_rejected(self):
        bb = _fresh_bb()
        for bad in ("telegram:", "telegram:-1", "telegram:+1", "telegram:12a", "Telegram:123", "telegram:123 ", "xtelegram:123"):
            result = bb.archive_document("DREG-001", "reason", bad)
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ACTOR_INVALID", bad)

    def test_document_not_found(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.archive_document("DREG-999", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_validation_failure_zero_reads_zero_writes(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id") as mock_read, \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            result = bb.archive_document("", "reason", VALID_ACTOR)
        mock_read.assert_not_called()
        mock_write.assert_not_called()
        self.assertFalse(result["changed"])
        self.assertTrue(result["retry_safe"])


# ────────────────────────────────────────────────────────────
# Status transitions
# ────────────────────────────────────────────────────────────

class TestArchiveTransitions(unittest.TestCase):
    def _archive(self, status, dry_run=False):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc(status=status)), \
             patch("business_core.document_manager.archive_document_row", return_value={"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}):
            return bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=dry_run)

    def test_uploaded_to_archived(self):
        result = self._archive("uploaded", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["previous_status"], "uploaded")

    def test_under_review_to_archived(self):
        result = self._archive("under_review", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["previous_status"], "under_review")

    def test_approved_to_archived(self):
        result = self._archive("approved", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["previous_status"], "approved")

    def test_rejected_to_archived(self):
        result = self._archive("rejected", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["previous_status"], "rejected")

    def test_superseded_rejected(self):
        result = self._archive("superseded", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_TRANSITION")

    def test_malformed_current_status_rejected(self):
        result = self._archive("bogus_status", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_TRANSITION")

    def test_archived_idempotent_noop(self):
        bb = _fresh_bb()
        archived_doc = _doc(status="archived", archived_at="2026-01-15 00:00:00 UTC",
                             archived_by=VALID_ACTOR, archive_reason="orig", previous_status="uploaded")
        with patch("business_core.document_manager.find_document_by_id", return_value=archived_doc), \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            result = bb.archive_document("DREG-001", "new reason", VALID_ACTOR)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ALREADY_ARCHIVED")
        mock_write.assert_not_called()

    def test_archived_metadata_unchanged_on_retry(self):
        bb = _fresh_bb()
        archived_doc = _doc(status="archived", archived_at="2026-01-15 00:00:00 UTC",
                             archived_by=VALID_ACTOR, archive_reason="orig", previous_status="uploaded")
        with patch("business_core.document_manager.find_document_by_id", return_value=archived_doc), \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            result = bb.archive_document("DREG-001", "attempted new reason", "telegram:999")
        self.assertEqual(result["archived_at"], "2026-01-15 00:00:00 UTC")
        self.assertEqual(result["archived_by"], VALID_ACTOR)
        self.assertEqual(result["archive_reason"], "orig")
        self.assertEqual(result["previous_status"], "uploaded")
        mock_write.assert_not_called()

    def test_legacy_incomplete_archived_metadata_unchanged(self):
        bb = _fresh_bb()
        legacy_doc = _doc(status="archived", archived_at="", archived_by="", archive_reason="", previous_status="")
        with patch("business_core.document_manager.find_document_by_id", return_value=legacy_doc), \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_ALREADY_ARCHIVED")
        self.assertEqual(result["archived_at"], "")
        self.assertEqual(result["archived_by"], "")
        self.assertEqual(result["archive_reason"], "")
        mock_write.assert_not_called()


# ────────────────────────────────────────────────────────────
# Dry-run
# ────────────────────────────────────────────────────────────

class TestArchiveDryRun(unittest.TestCase):
    def test_preview_code(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_PREVIEW")

    def test_preview_timestamp_empty(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        self.assertEqual(result["archived_at"], "")

    def test_preview_echoes_actor_and_reason(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "  my reason  ", VALID_ACTOR, dry_run=True)
        self.assertEqual(result["archived_by"], VALID_ACTOR)
        self.assertEqual(result["archive_reason"], "my reason")

    def test_preview_zero_writes(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        mock_write.assert_not_called()

    def test_preview_one_read(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()) as mock_read:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        mock_read.assert_called_once()

    def test_preview_performs_no_verification_read(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()) as mock_read:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        self.assertEqual(mock_read.call_count, 1)


# ────────────────────────────────────────────────────────────
# Confirmed execution / timestamps / write map
# ────────────────────────────────────────────────────────────

class TestArchiveConfirmedExecution(unittest.TestCase):
    def test_one_canonical_timestamp(self):
        bb = _fresh_bb()
        captured = {}

        def _capture_write(document_id, *, archived_at, archived_by, archive_reason, previous_status):
            captured["archived_at"] = archived_at
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        verified = _doc(status="archived")
        with patch("business_core.document_manager.find_document_by_id", side_effect=[_doc(), verified]), \
             patch("business_core.document_manager.archive_document_row", side_effect=_capture_write):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        # verification will fail since `verified` doesn't carry the
        # generated timestamp, but the point of this test is that
        # exactly one timestamp was generated and used for the write.
        self.assertIn("archived_at", captured)

    def test_updated_at_equals_archived_at(self):
        bb = _fresh_bb()
        write_kwargs = {}

        def _capture_write(document_id, **kwargs):
            write_kwargs.update(kwargs)
            verified = _doc(
                status="archived", archived_at=kwargs["archived_at"], archived_by=kwargs["archived_by"],
                archive_reason=kwargs["archive_reason"], previous_status=kwargs["previous_status"],
                updated_at=kwargs["archived_at"],
            )
            self._verified = verified
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        with patch("business_core.document_manager.find_document_by_id") as mock_read, \
             patch("business_core.document_manager.archive_document_row", side_effect=_capture_write):
            mock_read.side_effect = lambda doc_id: _doc() if mock_read.call_count == 1 else self._verified
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVED")

    def test_post_write_verification_succeeds(self):
        bb = _fresh_bb()

        def _write(document_id, **kwargs):
            self._kwargs = kwargs
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        def _read(doc_id):
            if not hasattr(self, "_kwargs"):
                return _doc()
            k = self._kwargs
            return _doc(status="archived", archived_at=k["archived_at"], archived_by=k["archived_by"],
                        archive_reason=k["archive_reason"], previous_status=k["previous_status"],
                        updated_at=k["archived_at"])

        with patch("business_core.document_manager.find_document_by_id", side_effect=_read), \
             patch("business_core.document_manager.archive_document_row", side_effect=_write):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVED")
        self.assertTrue(result["changed"])
        self.assertTrue(result["retry_safe"])

    def _run_with_mismatch(self, field):
        bb = _fresh_bb()

        def _write(document_id, **kwargs):
            self._kwargs = kwargs
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        def _read(doc_id):
            if not hasattr(self, "_kwargs"):
                return _doc()
            k = self._kwargs
            verified = _doc(status="archived", archived_at=k["archived_at"], archived_by=k["archived_by"],
                             archive_reason=k["archive_reason"], previous_status=k["previous_status"],
                             updated_at=k["archived_at"])
            verified[field] = "WRONG_VALUE"
            return verified

        with patch("business_core.document_manager.find_document_by_id", side_effect=_read), \
             patch("business_core.document_manager.archive_document_row", side_effect=_write):
            return bb.archive_document("DREG-001", "reason", VALID_ACTOR)

    def test_mismatch_status(self):
        result = self._run_with_mismatch("status")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_mismatch_archived_at(self):
        result = self._run_with_mismatch("archived_at")
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_mismatch_archived_by(self):
        result = self._run_with_mismatch("archived_by")
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_mismatch_archive_reason(self):
        result = self._run_with_mismatch("archive_reason")
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_mismatch_previous_status(self):
        result = self._run_with_mismatch("previous_status")
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_mismatch_updated_at(self):
        result = self._run_with_mismatch("updated_at")
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")

    def test_post_write_document_missing(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", side_effect=[_doc(), None]), \
             patch("business_core.document_manager.archive_document_row", return_value={"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_manager_returned_failure(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("business_core.document_manager.archive_document_row", return_value={"ok": False, "changed": False, "code": "DOCUMENT_NOT_FOUND", "error": None}):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")
        self.assertFalse(result["retry_safe"])

    def test_manager_exception_retry_safe_false(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("business_core.document_manager.archive_document_row", return_value={"ok": False, "changed": False, "code": "DOCUMENT_ARCHIVE_WRITE_FAILED", "error": None}):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ARCHIVE_WRITE_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_verification_failure_retry_safe_false(self):
        result = self._run_with_mismatch("status")
        self.assertFalse(result["retry_safe"])

    def test_success_retry_safe_true(self):
        bb = _fresh_bb()

        def _write(document_id, **kwargs):
            self._kwargs = kwargs
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        def _read(doc_id):
            if not hasattr(self, "_kwargs"):
                return _doc()
            k = self._kwargs
            return _doc(status="archived", archived_at=k["archived_at"], archived_by=k["archived_by"],
                        archive_reason=k["archive_reason"], previous_status=k["previous_status"],
                        updated_at=k["archived_at"])

        with patch("business_core.document_manager.find_document_by_id", side_effect=_read), \
             patch("business_core.document_manager.archive_document_row", side_effect=_write):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertTrue(result["retry_safe"])

    def test_exact_result_shape(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        expected_keys = {
            "ok", "code", "error", "document_id", "document_family_id", "version",
            "business_id", "drive_file_id", "drive_file_url", "document_template_id",
            "client_id", "object_id", "roadmap_id", "stage_id",
            "previous_status", "requested_status", "final_status",
            "created", "reused", "changed", "uploaded",
            "compensation_attempted", "compensation_succeeded", "analysis_status",
            "warnings", "conflicting_document_ids", "retry_safe",
            "document_name", "archived_at", "archived_by", "archive_reason",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_drive_fields_absent_or_empty(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        self.assertEqual(result["drive_file_url"], "")
        self.assertEqual(result["drive_file_id"], "")


# ────────────────────────────────────────────────────────────
# Isolation
# ────────────────────────────────────────────────────────────

class TestArchiveIsolation(unittest.TestCase):
    def test_no_drive_calls(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("integrations.google_drive_adapter.trash_file") as mock_drive:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        mock_drive.assert_not_called()

    def test_no_requirements_reads(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("business_core.document_requirements.evaluate_stage_requirements") as mock_req:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        mock_req.assert_not_called()

    def test_no_content_writes(self):
        # A precise architecture guard: no call addressing the
        # document_content sheet or its module — a mere docstring
        # mention of the sheet name (explaining what this function
        # does NOT touch) must not trip this check.
        source = inspect.getsource(_fresh_bb().archive_document)
        self.assertNotIn('"document_content"', source)
        self.assertNotIn("document_intelligence", source)

    def test_no_review_writes(self):
        source = inspect.getsource(_fresh_bb().archive_document)
        self.assertNotIn('"document_field_reviews"', source)
        self.assertNotIn("document_confirmation", source)

    def test_selected_row_only(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()) as mock_read, \
             patch("business_core.document_manager.archive_document_row") as mock_write:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        for call in mock_read.call_args_list:
            self.assertEqual(call.args[0], "DREG-001")

    def test_family_version_unaffected(self):
        source = inspect.getsource(_fresh_bb().archive_document)
        self.assertNotIn("document_family_id", source.lower())
        self.assertNotIn("compute_next_document_and_family_ids", source)

    def test_duplicate_canonical_logic_not_invoked(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=_doc()), \
             patch("business_core.document_intelligence.find_exact_duplicate") as mock_dup:
            bb.archive_document("DREG-001", "reason", VALID_ACTOR, dry_run=True)
        mock_dup.assert_not_called()

    def test_fresh_live_status_used_after_stale_preview(self):
        bb = _fresh_bb()
        # Preview sees "uploaded"; confirmed execution re-reads and finds
        # the live row has since moved to "approved" — archive must use
        # the LIVE status as previous_status, never the stale preview.
        def _write(document_id, **kwargs):
            self._kwargs = kwargs
            return {"ok": True, "changed": True, "code": "DOCUMENT_ARCHIVED", "error": None}

        def _read(doc_id):
            if not hasattr(self, "_kwargs"):
                return _doc(status="approved")  # live status differs from an earlier "uploaded" preview
            k = self._kwargs
            return _doc(status="archived", archived_at=k["archived_at"], archived_by=k["archived_by"],
                        archive_reason=k["archive_reason"], previous_status=k["previous_status"],
                        updated_at=k["archived_at"])

        with patch("business_core.document_manager.find_document_by_id", side_effect=_read), \
             patch("business_core.document_manager.archive_document_row", side_effect=_write):
            result = bb.archive_document("DREG-001", "reason", VALID_ACTOR)
        self.assertEqual(result["previous_status"], "approved")


# ────────────────────────────────────────────────────────────
# Coverage integration
# ────────────────────────────────────────────────────────────

class TestArchiveCoverageIntegration(unittest.TestCase):
    STAGES = [{"Stage ID": "STAGE-001", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-001"}]
    ROADMAPS = [{"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Service ID": "SVC-001", "Object ID": "OBJ-001"}]
    TEMPLATES = [{"Document Template ID": "DOC-001", "Title": "Технический паспорт", "Document Type": "technical_passport"}]

    def _doc_row(self, status):
        return {
            "Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "1",
            "Business ID": "BIZ-001", "Client ID": "PRS-001", "Object ID": "OBJ-001",
            "Roadmap ID": "RM-001", "Stage ID": "STAGE-001", "Document Template ID": "DOC-001",
            "Document Name": "Test", "Status": status,
            "Drive File ID": "FILE1", "Drive File URL": "", "File Name": "f.pdf", "Mime Type": "application/pdf",
            "Uploaded At": "", "Uploaded By": "", "Reviewed At": "", "Reviewed By": "",
            "Rejection Reason": "", "Notes": "", "Created At": "", "Updated At": "",
        }

    def _evaluate(self, documents):
        import business_core.document_requirements as dr

        def _read_business_sheet(sheet_key, *a, **kw):
            return {
                "roadmap_stages": self.STAGES, "roadmaps": self.ROADMAPS,
                "document_template_registry": self.TEMPLATES, "document_registry": documents,
                "document_content": [], "stage_entity_relations": [],
            }.get(sheet_key, [])

        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet):
            return dr.evaluate_stage_requirements("STAGE-001")

    def test_active_document_satisfies(self):
        summary = self._evaluate([self._doc_row("uploaded")])
        self.assertTrue(summary.is_complete)
        self.assertEqual(summary.missing_required, 0)

    def test_archived_document_excluded(self):
        summary = self._evaluate([self._doc_row("archived")])
        self.assertFalse(summary.is_complete)
        self.assertEqual(summary.missing_required, 1)

    def test_last_satisfying_document_archived_becomes_missing(self):
        before = self._evaluate([self._doc_row("uploaded")])
        self.assertTrue(before.is_complete)
        after = self._evaluate([self._doc_row("archived")])
        self.assertFalse(after.is_complete)
        self.assertEqual(after.missing_required, 1)

    def test_completion_gate_reflects_missing_naturally(self):
        # No Completion Gate code is touched by archive_document() —
        # this proves the *coverage read* naturally reflects the new
        # Status on the very next evaluation, with no cache to bust.
        after = self._evaluate([self._doc_row("archived")])
        self.assertEqual(after.blocking_missing, 1)
        self.assertEqual(after.missing_required, 1)
        self.assertFalse(after.is_complete)

    def test_no_coverage_engine_mutation(self):
        source = inspect.getsource(_fresh_bb().archive_document)
        self.assertNotIn("document_requirements", source)
        self.assertNotIn("document_coverage", source)


# ────────────────────────────────────────────────────────────
# Architecture guards (source inspection)
# ────────────────────────────────────────────────────────────

class TestArchitectureGuards(unittest.TestCase):
    def test_manager_owns_low_level_write(self):
        dm = _fresh_dm()
        self.assertTrue(hasattr(dm, "archive_document_row"))
        source = inspect.getsource(dm.archive_document_row)
        self.assertIn("update_business_row", source)

    def test_builder_calls_archive_document_row(self):
        bb = _fresh_bb()
        source = inspect.getsource(bb.archive_document)
        self.assertIn("archive_document_row", source)

    def test_builder_does_not_call_update_business_row_directly(self):
        bb = _fresh_bb()
        source = inspect.getsource(bb.archive_document)
        self.assertNotIn("update_business_row", source)

    def test_archive_does_not_use_update_document_status(self):
        bb = _fresh_bb()
        source = inspect.getsource(bb.archive_document)
        self.assertNotIn("update_document_status", source)

    def test_telegram_handlers_has_no_archive_document_row_call(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("archive_document_row", source)

    def test_telegram_handlers_has_no_low_level_archive_write(self):
        # Phase 16C.9D superseded the original assumption behind this
        # guard ("no archive-domain write path exists in Telegram in
        # this phase at all") — /archivedoc now legitimately exists and
        # calls business_builder.archive_document(). The guard is
        # updated to prove the real boundary: archivedoc_cmd calls the
        # one approved domain function and nothing lower-level, scoped
        # to the function's own source (not a whole-file substring ban
        # that would also reject the legitimate call).
        import business_core.telegram_handlers as th
        source = inspect.getsource(th.archivedoc_cmd)

        self.assertIn("archive_document(", source)

        for forbidden in (
            "archive_document_row(",
            "update_business_row(",
            "update_document_status(",
            "update_cell(",
            "get_business_sheet(",
            "append_business_row(",
            "find_row_by_id(",
        ):
            self.assertNotIn(forbidden, source)

    def test_sheets_py_unchanged_by_this_phase(self):
        # Structural guard: sheets.py must still expose exactly the
        # same update_business_row signature this phase relies on —
        # not a content-diff guard (git handles that), just a contract
        # sanity check that this phase didn't need to touch it.
        import business_core.sheets as sheets
        sig = inspect.signature(sheets.update_business_row)
        self.assertEqual(list(sig.parameters), ["sheet_key", "row", "values"])


# ────────────────────────────────────────────────────────────
# Schema / compatibility
# ────────────────────────────────────────────────────────────

class TestSchemaAndCompatibility(unittest.TestCase):
    def test_schema_27_35_12_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["document_registry"]), 27)
        self.assertEqual(len(BUSINESS_HEADERS["document_content"]), 35)
        self.assertEqual(len(BUSINESS_HEADERS["document_field_reviews"]), 12)

    def test_existing_document_result_callers_unchanged(self):
        bb = _fresh_bb()
        with patch("business_core.document_manager.find_document_by_id", return_value=None):
            result = bb.transition_document_status("DREG-999", "approved")
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")
        self.assertEqual(result["document_name"], "")
        self.assertEqual(result["archived_at"], "")


if __name__ == "__main__":
    unittest.main()
