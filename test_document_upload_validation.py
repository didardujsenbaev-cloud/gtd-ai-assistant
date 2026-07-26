"""
Phase 37F.1 — Document Upload Safety (ADR-020 §12): tests for the
pure, stateless business_core/document_upload_validation.py module.

No Sheets, no Drive, no network — every function here operates only
on already-in-memory strings/ints. Registered in conftest.py's hard
socket-block set (belt-and-suspenders; this module makes no I/O calls
at all).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.document_upload_validation as duv


class TestValidateFilename(unittest.TestCase):
    def test_missing_filename_rejected(self):
        result = duv.validate_filename("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_whitespace_only_rejected(self):
        result = duv.validate_filename("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_too_long_rejected(self):
        result = duv.validate_filename("a" * (duv.MAX_DOCUMENT_FILENAME_LENGTH + 1) + ".pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_control_characters_rejected(self):
        result = duv.validate_filename("passport\x07.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_null_byte_rejected(self):
        result = duv.validate_filename("passport\x00.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_forward_slash_rejected(self):
        result = duv.validate_filename("../etc/passport.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_backslash_rejected(self):
        result = duv.validate_filename("..\\windows\\passport.pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_path_traversal_token_rejected(self):
        result = duv.validate_filename("passport..pdf")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_safe_ordinary_filename_accepted(self):
        result = duv.validate_filename("passport.pdf")
        self.assertTrue(result["ok"])

    def test_safe_filename_with_spaces_and_unicode_accepted(self):
        result = duv.validate_filename("Технический паспорт (копия).pdf")
        self.assertTrue(result["ok"])

    def test_at_exactly_max_length_accepted(self):
        name = "a" * (duv.MAX_DOCUMENT_FILENAME_LENGTH - 4) + ".pdf"
        self.assertEqual(len(name), duv.MAX_DOCUMENT_FILENAME_LENGTH)
        result = duv.validate_filename(name)
        self.assertTrue(result["ok"])


class TestValidateSize(unittest.TestCase):
    def test_zero_rejected(self):
        result = duv.validate_size(0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_TOO_LARGE")

    def test_negative_rejected(self):
        result = duv.validate_size(-1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_TOO_LARGE")

    def test_exactly_at_limit_accepted(self):
        result = duv.validate_size(duv.MAX_DOCUMENT_FILE_SIZE_BYTES)
        self.assertTrue(result["ok"])

    def test_above_limit_rejected(self):
        result = duv.validate_size(duv.MAX_DOCUMENT_FILE_SIZE_BYTES + 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_TOO_LARGE")

    def test_missing_size_metadata_is_not_rejected_here(self):
        result = duv.validate_size(None)
        self.assertTrue(result["ok"])


class TestClassifyStorageType(unittest.TestCase):
    def test_safe_pdf(self):
        result = duv.classify_storage_type("passport.pdf", "application/pdf")
        self.assertTrue(result["ok"])
        self.assertTrue(result["analysis_supported"])

    def test_safe_jpeg(self):
        result = duv.classify_storage_type("scan.jpg", "image/jpeg")
        self.assertTrue(result["ok"])
        self.assertTrue(result["analysis_supported"])

    def test_safe_png(self):
        result = duv.classify_storage_type("scan.png", "image/png")
        self.assertTrue(result["ok"])
        self.assertTrue(result["analysis_supported"])

    def test_common_office_format_storage_allowed_but_analysis_unsupported(self):
        result = duv.classify_storage_type(
            "contract.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["analysis_supported"])

    def test_rtf_storage_allowed_but_analysis_unsupported(self):
        """Matches the existing production RTF Document — must remain valid."""
        result = duv.classify_storage_type("old_contract.rtf", "application/rtf")
        self.assertTrue(result["ok"])
        self.assertFalse(result["analysis_supported"])

    def test_dangerous_executable_by_mime_blocked(self):
        result = duv.classify_storage_type("setup.exe", "application/x-msdownload")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_DOCUMENT_STORAGE_TYPE")

    def test_dangerous_executable_by_extension_blocked(self):
        result = duv.classify_storage_type("run.exe", "application/octet-stream")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_DOCUMENT_STORAGE_TYPE")

    def test_dangerous_script_extension_blocked(self):
        result = duv.classify_storage_type("evil.sh", "text/plain")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_DOCUMENT_STORAGE_TYPE")

    def test_unknown_mime_handled_deterministically(self):
        result = duv.classify_storage_type("mystery.xyz", "application/x-mystery-format")
        self.assertTrue(result["ok"])
        self.assertFalse(result["analysis_supported"])

    def test_malformed_mime_metadata_handled_safely(self):
        result = duv.classify_storage_type("file", "")
        self.assertTrue(result["ok"])
        self.assertFalse(result["analysis_supported"])


class TestValidateUploadRequest(unittest.TestCase):
    def test_safe_pdf_fully_validated(self):
        result = duv.validate_upload_request("passport.pdf", "application/pdf", 1024)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "")
        self.assertTrue(result["analysis_supported"])

    def test_storage_allowed_analysis_unsupported_distinct_code(self):
        result = duv.validate_upload_request("contract.rtf", "application/rtf", 1024)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_ANALYSIS_UNSUPPORTED")

    def test_filename_checked_before_size_and_mime(self):
        result = duv.validate_upload_request("", "application/x-msdownload", -1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DOCUMENT_FILENAME")

    def test_size_checked_before_mime(self):
        result = duv.validate_upload_request("setup.txt", "application/x-msdownload", -1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_TOO_LARGE")

    def test_dangerous_type_blocked_even_with_valid_name_and_size(self):
        result = duv.validate_upload_request("setup.exe", "application/x-msdownload", 1024)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_DOCUMENT_STORAGE_TYPE")

    def test_no_network_or_sheets_access(self):
        """This whole module must never touch Sheets/Drive/network —
        verified by ensuring no such call is even attempted (mocked
        with a raising stub; if it were called, the test would fail
        with that stub's exception, not a normal assertion)."""
        with patch("business_core.sheets.get_business_sheet", side_effect=AssertionError("must not be called")), \
             patch("integrations.google_drive_adapter.get_drive_service", side_effect=AssertionError("must not be called")):
            result = duv.validate_upload_request("passport.pdf", "application/pdf", 1024)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
