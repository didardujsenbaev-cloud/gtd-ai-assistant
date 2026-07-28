"""
Phase 16B.1: Document Intelligence Reliability & Exact Duplicate
Foundation.

Two closed technical gaps:
  A. business_core.document_intelligence readers now use the existing
     Sheets quota mitigation contract (SheetsReadError/
     SheetsQuotaExceededError/TransientSheetsReadError/read_with_retry) —
     a 429/5xx/network failure is never reported as a generic AI/analysis
     failure, and never masks a document as "not found".
  B. Content Hash (already computed, already stored) is now used for
     deterministic EXACT_DUPLICATE / NEW_DOCUMENT detection —
     find_exact_duplicate() — purely informational: never deletes/trashes
     the new file, never replaces the old document, never touches
     Document Family/Version/Template ID/relations/Status, never
     satisfies the Document Completion Gate.

All tests fully mock business_core.sheets / gspread.exceptions.APIError /
anthropic / Google Drive — no live network calls of any kind.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from unittest.mock import MagicMock, patch


def _fresh_di():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_intelligence as di
    return di


def _fresh_dq():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_query as dq
    return dq


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


CONTENT_HEADERS = [
    "Document ID", "Drive File ID", "Content Status",
    "Detected Document Type", "Suggested Document Template ID",
    "Template Match Confidence",
    "AI Summary", "Extracted Fields JSON", "Text Preview",
    "Language", "Page Count", "Keywords JSON",
    "Model", "Prompt Version", "Content Hash",
    "Analysis Started At", "Analysis Completed At", "Analysis Error",
    "Created At", "Updated At",
    "Duplicate Status", "Duplicate Of Document ID", "Duplicate Checked At",
]

DOC_REGISTRY_HEADERS = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID",
    "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
]


def _registry_row(document_id="DREG-001", business_id="BIZ-001", status="uploaded",
                   created_at="2026-01-01", document_name="Test Doc", mime_type="application/pdf"):
    values = {
        "Document ID": document_id, "Document Family ID": "DFAM-001", "Version": "1",
        "Business ID": business_id, "Client ID": "PRS-001", "Object ID": "OBJ-001",
        "Roadmap ID": "", "Stage ID": "", "Document Template ID": "",
        "Document Name": document_name, "Status": status,
        "Drive File ID": "FILE1", "Drive File URL": "https://drive.google.com/file/d/FILE1/view",
        "File Name": "file.pdf", "Mime Type": mime_type,
        "Uploaded At": created_at, "Uploaded By": "dida",
        "Reviewed At": "", "Reviewed By": "", "Rejection Reason": "",
        "Notes": "", "Created At": created_at, "Updated At": created_at,
    }
    return [values[h] for h in DOC_REGISTRY_HEADERS]


def _content_row(document_id, content_hash="", status="completed", **overrides):
    values = {h: "" for h in CONTENT_HEADERS}
    values["Document ID"] = document_id
    values["Content Status"] = status
    values["Content Hash"] = content_hash
    values.update(overrides)
    return [values[h] for h in CONTENT_HEADERS]


def _api_error(code: int):
    import gspread.exceptions as gspread_exceptions

    class _FakeResponse:
        def json(self):
            return {"error": {"code": code, "message": "boom"}}
        headers = {}

    return gspread_exceptions.APIError(_FakeResponse())


# ═══════════════════════════════════════════════════════════════
# A. find_exact_duplicate() — pure unit tests
# ═══════════════════════════════════════════════════════════════

class TestFindExactDuplicate(unittest.TestCase):
    def _patch_sheets(self, content_rows, registry_rows):
        def _read(sheet_key):
            if sheet_key == "document_content":
                return [dict(zip(CONTENT_HEADERS, r)) for r in content_rows]
            if sheet_key == "document_registry":
                return [dict(zip(DOC_REGISTRY_HEADERS, r)) for r in registry_rows]
            raise AssertionError(f"unexpected sheet_key {sheet_key}")
        return patch("business_core.sheets.read_business_sheet", side_effect=_read)

    def test_same_business_same_hash_other_id_is_exact_duplicate(self):
        di = _fresh_di()
        content_rows = [_content_row("DREG-001", content_hash="HASH1")]
        registry_rows = [
            _registry_row("DREG-001", created_at="2026-01-01"),
            _registry_row("DREG-002", created_at="2026-01-05"),  # self, newer
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")
        self.assertEqual(result.duplicate_document_status, "uploaded")

    def test_same_hash_same_document_id_is_new_document(self):
        """Analyzing the very same document (no other candidate at all)."""
        di = _fresh_di()
        with self._patch_sheets([], []):
            result = di.find_exact_duplicate("DREG-001", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "NEW_DOCUMENT")

    def test_same_hash_different_business_is_new_document(self):
        di = _fresh_di()
        content_rows = [_content_row("DREG-001", content_hash="HASH1")]
        registry_rows = [
            _registry_row("DREG-001", business_id="BIZ-999", created_at="2026-01-01"),
            _registry_row("DREG-002", business_id="BIZ-001", created_at="2026-01-05"),  # self
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "NEW_DOCUMENT")

    def test_empty_hash_is_new_document_with_warning(self):
        di = _fresh_di()
        result = di.find_exact_duplicate("DREG-002", "BIZ-001", "")
        self.assertEqual(result.status, "NEW_DOCUMENT")
        self.assertTrue(result.warnings)

    def test_multiple_candidates_deterministic_oldest_canonical(self):
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-001", content_hash="HASH1"),
            _content_row("DREG-002", content_hash="HASH1"),
        ]
        registry_rows = [
            _registry_row("DREG-001", created_at="2026-01-05"),
            _registry_row("DREG-002", created_at="2026-01-01"),  # actually oldest
            _registry_row("DREG-003", created_at="2026-01-10"),  # self, newest
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-003", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-002")

    def test_tie_break_by_minimum_document_id(self):
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-002", content_hash="HASH1"),
            _content_row("DREG-001", content_hash="HASH1"),
        ]
        registry_rows = [
            _registry_row("DREG-002", created_at="2026-01-01"),
            _registry_row("DREG-001", created_at="2026-01-01"),
            _registry_row("DREG-003", created_at="2026-01-10"),  # self
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-003", "BIZ-001", "HASH1")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")

    def test_archived_rejected_superseded_candidates_still_match(self):
        """п.6: physical duplicate detection is independent of the found
        document's business Status — all statuses participate."""
        di = _fresh_di()
        for status in ("rejected", "archived", "superseded", "under_review", "approved"):
            content_rows = [_content_row("DREG-001", content_hash="HASH1")]
            registry_rows = [
                _registry_row("DREG-001", status=status, created_at="2026-01-01"),
                _registry_row("DREG-002", created_at="2026-01-05"),  # self, newer
            ]
            with self._patch_sheets(content_rows, registry_rows):
                result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
            self.assertEqual(result.status, "EXACT_DUPLICATE", status)
            self.assertEqual(result.duplicate_document_status, status)

    def test_older_document_never_points_to_newer_one_on_reanalysis(self):
        """The oldest document in the whole set is always NEW_DOCUMENT,
        even when newer duplicates of it already exist — no cycle risk."""
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-001", content_hash="HASH1"),
            _content_row("DREG-002", content_hash="HASH1"),
        ]
        registry_rows = [
            _registry_row("DREG-001", created_at="2026-01-01"),
            _registry_row("DREG-002", created_at="2026-01-05"),
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-001", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "NEW_DOCUMENT")

    def test_candidate_missing_from_registry_excluded_with_warning(self):
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-001", content_hash="HASH1"),
            _content_row("DREG-GHOST", content_hash="HASH1"),
        ]
        registry_rows = [
            _registry_row("DREG-001", created_at="2026-01-01"),
            _registry_row("DREG-002", created_at="2026-01-05"),  # self, newer
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
        # DREG-GHOST excluded -> only DREG-001 (older) + self (DREG-002) remain
        self.assertEqual(result.status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")

    def test_missing_created_at_never_falsely_claims_oldest(self):
        """A candidate with an empty/malformed Created At must never be
        preferred over one with a real value — an empty string would
        otherwise sort first lexicographically and let corrupted data
        falsely become canonical ahead of a genuinely older document."""
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-001", content_hash="HASH1"),  # real, older-looking date
            _content_row("DREG-002", content_hash="HASH1"),  # self, empty Created At
        ]
        registry_rows = [
            _registry_row("DREG-001", created_at="2026-01-05"),
            _registry_row("DREG-002", created_at=""),  # malformed/missing
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
        # DREG-001 has a real Created At -> it must win canonical status
        # even though "" (DREG-002's malformed value) would sort first
        # lexicographically.
        self.assertEqual(result.status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")

    def test_all_missing_created_at_falls_back_to_document_id(self):
        """When every candidate's Created At is empty, the deterministic
        fallback is purely Document ID order — never dependent on
        Google Sheets row order."""
        di = _fresh_di()
        content_rows = [
            _content_row("DREG-002", content_hash="HASH1"),
            _content_row("DREG-001", content_hash="HASH1"),
        ]
        registry_rows = [
            _registry_row("DREG-002", created_at=""),
            _registry_row("DREG-001", created_at=""),
        ]
        with self._patch_sheets(content_rows, registry_rows):
            result = di.find_exact_duplicate("DREG-002", "BIZ-001", "HASH1")
        self.assertEqual(result.status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")


# ═══════════════════════════════════════════════════════════════
# B. Typed exceptions never masked as "not found" / generic failure
# ═══════════════════════════════════════════════════════════════

class TestReadersNeverMaskQuotaErrors(unittest.TestCase):
    """find_row_by_id() (used by get_content_status()/analyze_document()'s
    own initial lookup) reads via sheet.get_all_values() — NOT sheet.find()
    — see business_core.sheets.find_row_by_id()."""

    def test_get_content_status_429_raises_not_none(self):
        di = _fresh_di()
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                di.get_content_status("DREG-001")

    def test_analyze_document_429_before_claim_returns_quota_action(self):
        """п.13: 429 is not DOCUMENT_NOT_FOUND — nothing claimed at all."""
        di = _fresh_di()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            result = di.analyze_document("DREG-001", "FILE1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "quota_exceeded")
        self.assertNotEqual(result["action"], "failed")  # never conflated with a real analysis failure

    def test_analyze_document_429_without_retry_after_no_fast_retry(self):
        """п.14."""
        di = _fresh_di()
        mock_get_all_values = MagicMock(side_effect=_api_error(429))
        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("time.sleep") as mock_sleep:
            mock_sheet.return_value.get_all_values = mock_get_all_values
            di.analyze_document("DREG-001", "FILE1")
        mock_get_all_values.assert_called_once()
        mock_sleep.assert_not_called()

    def test_analyze_document_5xx_retry_succeeds(self):
        """п.15."""
        di = _fresh_di()
        call_count = {"n": 0}

        def _get_all_values():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _api_error(503)
            return []

        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("time.sleep"):
            mock_sheet.return_value.get_all_values.side_effect = _get_all_values
            mock_sheet.return_value.row_values.return_value = CONTENT_HEADERS
            result = di.analyze_document("DREG-001", "FILE1")
        # After the retried get_all_values() succeeds (empty sheet -> not
        # found), analyze_document proceeds to the claim step normally.
        self.assertIn(result["action"], ("failed", "unsupported", "completed"))

    def test_analyze_document_5xx_retry_exhausted_gives_typed_failure(self):
        """п.16."""
        di = _fresh_di()
        mock_get_all_values = MagicMock(side_effect=[_api_error(500), _api_error(502), _api_error(503)])
        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("time.sleep"):
            mock_sheet.return_value.get_all_values = mock_get_all_values
            result = di.analyze_document("DREG-001", "FILE1")
        self.assertEqual(result["action"], "transient_read_error")
        self.assertEqual(mock_get_all_values.call_count, 3)

    def test_registry_read_429_mid_analysis_not_generic_failed(self):
        """A 429 reading DOCUMENT_REGISTRY (after the claim already
        succeeded) must be tagged distinctly, not collapsed into the
        same generic 'failed' as an AI/Drive error."""
        di = _fresh_di()
        content_sheet = _make_sheet(CONTENT_HEADERS, [])

        def _get_business_sheet(key):
            if key == "document_content":
                return content_sheet
            raise AssertionError(f"unexpected {key}")

        from business_core.sheets import SheetsQuotaExceededError

        def _find_row_by_id(sheet_key, record_id):
            if sheet_key == "document_content":
                return None
            if sheet_key == "document_registry":
                raise SheetsQuotaExceededError("quota")
            raise AssertionError(sheet_key)

        with patch("business_core.sheets.get_business_sheet", side_effect=_get_business_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id):
            result = di.analyze_document("DREG-001", "FILE1")
        self.assertEqual(result["action"], "quota_exceeded")
        self.assertIn(di.QUOTA_ERROR_PREFIX, result["error"])


def _make_sheet(headers, existing_rows=None):
    data = [list(headers)] + [list(r) for r in (existing_rows or [])]
    sheet = MagicMock()
    sheet.get_all_values.side_effect = lambda: [list(row) for row in data]
    sheet.row_values.side_effect = lambda r: list(data[r - 1]) if 0 <= r - 1 < len(data) else []

    def _col_letters_to_index(col_letters: str) -> int:
        n = 0
        for ch in col_letters:
            n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
        return n - 1

    def _update(values=None, range_name=None, **kw):
        if values:
            data.append(list(values[0]))

    sheet.update.side_effect = _update

    def _batch_update(batch_data, **kw):
        for entry in batch_data:
            m = re.match(r"([A-Za-z]+)(\d+)", entry["range"])
            col_idx = _col_letters_to_index(m.group(1))
            row_idx = int(m.group(2)) - 1
            while len(data) <= row_idx:
                data.append([""] * len(headers))
            row = data[row_idx]
            while len(row) <= col_idx:
                row.append("")
            row[col_idx] = entry["values"][0][0]

    sheet.batch_update.side_effect = _batch_update
    sheet._data = data
    return sheet


# ═══════════════════════════════════════════════════════════════
# C. Exact duplicate — no automatic side effects (п.7-11)
# ═══════════════════════════════════════════════════════════════

def _good_ai_json():
    return json.dumps({
        "document_type": "technical_passport", "summary": "Summary.",
        "language": "ru", "page_count": 1, "keywords": [], "extracted_fields": {},
        "text_preview": "preview",
    })


def _mock_anthropic_response(text):
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


class TestExactDuplicateNoSideEffects(unittest.TestCase):
    def _find_row_by_id_from_content_sheet(self, content_sheet, record_id):
        for i, row in enumerate(content_sheet._data[1:], start=2):
            if row and row[0] == record_id:
                return (i, dict(zip(CONTENT_HEADERS, row)))
        return None

    def test_exact_duplicate_does_not_change_document_status(self):
        content_sheet = _make_sheet(CONTENT_HEADERS, [])
        registry_row = _registry_row("DREG-002", created_at="2026-01-05")
        older_registry = _registry_row("DREG-001", created_at="2026-01-01")

        import hashlib
        h = hashlib.sha256(b"%PDF-1.4 fake").hexdigest()
        existing_dup = [_content_row("DREG-001", content_hash=h)]

        di = _fresh_di()

        def _find_row_by_id(sheet_key, record_id):
            if sheet_key == "document_content":
                return self._find_row_by_id_from_content_sheet(content_sheet, record_id)
            if sheet_key == "document_registry":
                if record_id == "DREG-002":
                    return (2, dict(zip(DOC_REGISTRY_HEADERS, registry_row)))
                if record_id == "DREG-001":
                    return (3, dict(zip(DOC_REGISTRY_HEADERS, older_registry)))
            return None

        def _read_business_sheet(key):
            if key == "document_template_registry":
                return []
            if key == "document_content":
                return [dict(zip(CONTENT_HEADERS, r)) for r in existing_dup]
            if key == "document_registry":
                return [dict(zip(DOC_REGISTRY_HEADERS, older_registry)),
                        dict(zip(DOC_REGISTRY_HEADERS, registry_row))]
            return []

        with patch("business_core.sheets.get_business_sheet", return_value=content_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet), \
             patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
             patch("business_core.document_intelligence._download_drive_file_bytes", return_value=b"%PDF-1.4 fake"), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_anthropic_cls.return_value.messages.create.return_value = _mock_anthropic_response(_good_ai_json())
            result = di.analyze_document("DREG-002", "FILE1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "completed")
        # Registry write only ever happens through business_core.document_manager —
        # nothing here calls update_document_status / any DOCUMENT_REGISTRY write.
        final_row = content_sheet._data[-1]
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        self.assertEqual(final_row[idx["Duplicate Status"]], "EXACT_DUPLICATE")
        self.assertEqual(final_row[idx["Duplicate Of Document ID"]], "DREG-001")

    def test_duplicate_check_failure_does_not_fail_analysis(self):
        """п.7 (failure scenario 6/9 combined): duplicate lookup itself
        raising must never turn a successful AI analysis into a failure —
        it's purely informational."""
        content_sheet = _make_sheet(CONTENT_HEADERS, [])
        registry_row = _registry_row("DREG-001")
        di = _fresh_di()

        def _find_row_by_id(sheet_key, record_id):
            if sheet_key == "document_content":
                return self._find_row_by_id_from_content_sheet(content_sheet, record_id)
            if sheet_key == "document_registry":
                return (2, dict(zip(DOC_REGISTRY_HEADERS, registry_row)))
            return None

        def _read_business_sheet(key):
            if key == "document_template_registry":
                return []
            raise RuntimeError("boom")  # duplicate lookup itself fails

        with patch("business_core.sheets.get_business_sheet", return_value=content_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet), \
             patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
             patch("business_core.document_intelligence._download_drive_file_bytes", return_value=b"%PDF-1.4"), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_anthropic_cls.return_value.messages.create.return_value = _mock_anthropic_response(_good_ai_json())
            result = di.analyze_document("DREG-001", "FILE1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "completed")


# ═══════════════════════════════════════════════════════════════
# D. document_query rendering (is_quota_error / duplicate fields)
# ═══════════════════════════════════════════════════════════════

class TestDocumentQueryDuplicateAndQuotaFields(unittest.TestCase):
    def test_completed_result_with_exact_duplicate_fields(self):
        dq = _fresh_dq()
        content = dict(zip(CONTENT_HEADERS, _content_row(
            "DREG-002", status="completed",
            **{"Duplicate Status": "EXACT_DUPLICATE", "Duplicate Of Document ID": "DREG-001",
               "Duplicate Checked At": "2026-07-28"},
        )))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-002")))
        dup_registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001", document_name="Original", status="approved")))

        def _find_row_by_id(sheet_key, record_id):
            if sheet_key == "document_registry":
                if record_id == "DREG-002":
                    return (2, registry)
                if record_id == "DREG-001":
                    return (3, dup_registry)
            return None

        with patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-002")

        self.assertEqual(result.duplicate_status, "EXACT_DUPLICATE")
        self.assertEqual(result.duplicate_of_document_id, "DREG-001")
        self.assertEqual(result.duplicate_document_name, "Original")
        self.assertEqual(result.duplicate_document_status, "approved")

    def test_new_document_has_empty_duplicate_fields(self):
        dq = _fresh_dq()
        content = dict(zip(CONTENT_HEADERS, _content_row("DREG-001", status="completed",
                                                          **{"Duplicate Status": "NEW_DOCUMENT"})))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001")))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, registry)), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-001")
        self.assertEqual(result.duplicate_status, "NEW_DOCUMENT")
        self.assertEqual(result.duplicate_of_document_id, "")

    def test_pre_16b1_row_has_empty_duplicate_status_backward_compatible(self):
        """п.25: an old DOCUMENT_CONTENT row (written before this phase)
        simply has no Duplicate Status value — read as ''. Must not
        crash, must not be misrepresented as NEW_DOCUMENT/EXACT_DUPLICATE."""
        dq = _fresh_dq()
        old_headers = CONTENT_HEADERS[:20]  # pre-16B.1 shape, no duplicate columns
        old_row_values = _content_row("DREG-001", status="completed")[:20]
        content = dict(zip(old_headers, old_row_values))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001")))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, registry)), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-001")
        self.assertEqual(result.duplicate_status, "")
        self.assertEqual(result.status, "completed")

    def test_quota_error_prefix_recognized(self):
        dq = _fresh_dq()
        from business_core.document_intelligence import QUOTA_ERROR_PREFIX
        content = dict(zip(CONTENT_HEADERS, _content_row(
            "DREG-001", status="failed", **{"Analysis Error": f"{QUOTA_ERROR_PREFIX}boom"},
        )))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001")))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, registry)), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-001")
        self.assertTrue(result.is_quota_error)
        self.assertFalse(result.is_transient_read_error)

    def test_transient_error_prefix_recognized(self):
        dq = _fresh_dq()
        from business_core.document_intelligence import TRANSIENT_ERROR_PREFIX
        content = dict(zip(CONTENT_HEADERS, _content_row(
            "DREG-001", status="failed", **{"Analysis Error": f"{TRANSIENT_ERROR_PREFIX}boom"},
        )))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001")))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, registry)), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-001")
        self.assertTrue(result.is_transient_read_error)
        self.assertFalse(result.is_quota_error)

    def test_ordinary_ai_failure_neither_flag_set(self):
        dq = _fresh_dq()
        content = dict(zip(CONTENT_HEADERS, _content_row(
            "DREG-001", status="failed", **{"Analysis Error": "AI call error: boom"},
        )))
        registry = dict(zip(DOC_REGISTRY_HEADERS, _registry_row("DREG-001")))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, registry)), \
             patch("business_core.document_intelligence.get_content_status", return_value=content):
            result = dq.get_document_analysis("DREG-001")
        self.assertFalse(result.is_quota_error)
        self.assertFalse(result.is_transient_read_error)


# ═══════════════════════════════════════════════════════════════
# E. Telegram UX
# ═══════════════════════════════════════════════════════════════

class TestTelegramDuplicateAndQuotaUX(unittest.TestCase):
    def test_exact_duplicate_ux(self):
        th = _fresh_th()
        result = MagicMock()
        result.status = "completed"
        result.document_id = "DREG-002"
        result.document_name = "Test"
        result.file_name = "file.pdf"
        result.detected_document_type = "technical_passport"
        result.summary = "Summary"
        result.language = "ru"
        result.page_count = "1"
        result.suggested_template_id = ""
        result.template_match_confidence = ""
        result.keywords = ()
        result.completed_at = "2026-07-28"
        result.fields_valid = True
        result.fields = {}
        result.duplicate_status = "EXACT_DUPLICATE"
        result.duplicate_of_document_id = "DREG-001"
        result.duplicate_document_name = "Original Doc"
        result.duplicate_document_status = "approved"

        msg = th._render_document_analysis(result)
        self.assertIn("Обнаружен точный дубликат", msg)
        self.assertIn("DREG-001", msg)
        self.assertIn("Original Doc", msg)
        self.assertIn("approved", msg)
        self.assertIn("Автоматическая замена не выполнялась", msg)
        # never leak internals
        self.assertNotIn("SHA-256", msg)
        self.assertNotIn("Content Hash", msg)

    def test_new_document_ux(self):
        th = _fresh_th()
        result = MagicMock()
        result.status = "completed"
        result.document_id = "DREG-001"
        result.document_name = "Test"
        result.file_name = "file.pdf"
        result.detected_document_type = ""
        result.summary = ""
        result.language = ""
        result.page_count = ""
        result.suggested_template_id = ""
        result.template_match_confidence = ""
        result.keywords = ()
        result.completed_at = ""
        result.fields_valid = True
        result.fields = {}
        result.duplicate_status = "NEW_DOCUMENT"
        result.duplicate_of_document_id = ""
        result.duplicate_document_name = ""
        result.duplicate_document_status = ""

        msg = th._render_document_analysis(result)
        self.assertIn("Дубликат: не обнаружен", msg)

    def test_quota_error_ux_safe(self):
        th = _fresh_th()
        result = MagicMock()
        result.status = "failed"
        result.is_quota_error = True
        result.is_transient_read_error = False
        result.document_id = "DREG-001"
        msg = th._render_document_analysis(result)
        self.assertIn("Google Sheets временно перегружен", msg)
        self.assertIn("/analyzedoc", msg)
        self.assertNotIn("APIError", msg)
        self.assertNotIn("project_number", msg)

    def test_transient_error_ux_safe(self):
        th = _fresh_th()
        result = MagicMock()
        result.status = "failed"
        result.is_quota_error = False
        result.is_transient_read_error = True
        result.document_id = "DREG-001"
        msg = th._render_document_analysis(result)
        self.assertIn("Не удалось временно прочитать данные Google Sheets", msg)
        self.assertIn("Документ сохранён", msg)

    def test_ordinary_failed_ux_unchanged(self):
        """п.24: existing /docanalysis failed-rendering stays intact for
        a non-quota AI failure."""
        th = _fresh_th()
        result = MagicMock()
        result.status = "failed"
        result.is_quota_error = False
        result.is_transient_read_error = False
        result.document_id = "DREG-001"
        result.document_name = "Test"
        result.error = "AI call error: boom"
        result.updated_at = "2026-07-28"
        msg = th._render_document_analysis(result)
        self.assertIn("Анализ завершился с ошибкой", msg)
        self.assertIn("force=true", msg)


# ═══════════════════════════════════════════════════════════════
# F. Completion Gate invariant — architecture guards
# ═══════════════════════════════════════════════════════════════

class TestCompletionGateNeverReadsDocumentContent(unittest.TestCase):
    def test_evaluate_document_completion_gate_source_never_mentions_document_content(self):
        import inspect
        import business_core.business_builder as bb
        src = inspect.getsource(bb._evaluate_document_completion_gate)
        self.assertNotIn("document_content", src.lower())
        self.assertNotIn("duplicate", src.lower())

    def test_evaluate_document_completion_gate_never_calls_document_intelligence(self):
        import inspect
        import business_core.business_builder as bb
        src = inspect.getsource(bb._evaluate_document_completion_gate)
        self.assertNotIn("document_intelligence", src)
        self.assertNotIn("document_query", src)

    def test_find_exact_duplicate_never_writes_document_registry(self):
        import inspect
        import business_core.document_intelligence as di
        src = inspect.getsource(di.find_exact_duplicate)
        self.assertNotIn("update_business_row(\"document_registry\"", src)
        self.assertNotIn("append_business_row(\"document_registry\"", src)
        self.assertNotIn("update_document_status", src)

    def test_find_exact_duplicate_never_touches_family_version_template(self):
        """Checks for actual field-write-shaped string literals (quoted
        header names), not prose mentions in the function's own docstring
        explaining what it deliberately does NOT touch."""
        import inspect
        import business_core.document_intelligence as di
        src = inspect.getsource(di.find_exact_duplicate)
        for forbidden in ('"Document Family ID"', '"Version"', '"Document Template ID"'):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
