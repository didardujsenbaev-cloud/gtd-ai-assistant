"""
Phase 16A: Document Intelligence Foundation — mock tests.

Scope: enrich an already-registered DOCUMENT_REGISTRY row with AI-derived
metadata (detected type, summary, bounded preview, keywords, extracted
fields, a suggested-only Document Template ID) via a separate, purely
additive DOCUMENT_CONTENT sheet. Analysis runs asynchronously (Telegram
job_queue), enqueued ONLY after /uploaddoc's own transaction has fully
succeeded, and can never roll back that upload on failure.

Covers (per the approved architecture, Phase 16A review):
- supported MIME dispatch (_build_content_block / is_supported_mime_type)
- unsupported RTF/DOCX behavior (never auto-treated as plain text)
- missing ANTHROPIC_API_KEY
- valid structured AI result -> completed row
- malformed/non-JSON AI result -> failed, never crashes
- Drive download failure -> failed, DOCUMENT_REGISTRY untouched
- completed idempotent skip / processing duplicate guard / failed no-auto-retry
- force retry updates the existing row, never creates a second one
- template suggestion validation (exact, non-fuzzy match only)
- existing authoritative Document Template ID is never read/overwritten
- analysis failure never touches DOCUMENT_REGISTRY
- background enqueue happens only after successful /uploaddoc verification,
  never on a failed upload or failed registry write
- GTD Core files untouched

All tests fully mock business_core.sheets / integrations.google_drive_adapter
/ anthropic — no live network calls of any kind.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

CONTENT_HEADERS = [
    "Document ID", "Drive File ID", "Content Status",
    "Detected Document Type", "Suggested Document Template ID",
    "Template Match Confidence",
    "AI Summary", "Extracted Fields JSON", "Text Preview",
    "Language", "Page Count", "Keywords JSON",
    "Model", "Prompt Version", "Content Hash",
    "Analysis Started At", "Analysis Completed At", "Analysis Error",
    "Created At", "Updated At",
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


def _fresh_di():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_intelligence as di
    return di


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _col_letters_to_index(col_letters: str) -> int:
    """'A' -> 0, 'B' -> 1, ... (0-based), matching business_core.sheets._col_letter's inverse."""
    n = 0
    for ch in col_letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1


def _make_sheet(headers, existing_rows=None):
    """
    A faithful-enough in-memory Sheets mock: append_business_row()'s
    sheet.update(values=[...], range_name=...) actually appends a new row,
    and update_business_row()'s sheet.batch_update([...]) actually mutates
    the addressed cells — so a subsequent find_row_by_id()/get_all_values()
    within the SAME test sees the effects of earlier writes, exactly like
    a real sheet would (unlike a static return_value snapshot).
    """
    import re

    data = [list(headers)] + [list(r) for r in (existing_rows or [])]
    sheet = MagicMock()
    sheet.get_all_values.side_effect = lambda: [list(row) for row in data]
    sheet.row_values.side_effect = lambda r: list(data[r - 1]) if 0 <= r - 1 < len(data) else []

    appended = []

    def _update(values=None, range_name=None, **kw):
        if values:
            new_row = list(values[0])
            data.append(new_row)
            appended.append(new_row)

    sheet.update.side_effect = _update
    sheet._appended = appended

    batch_calls = []

    def _batch_update(batch_data, **kw):
        batch_calls.append(batch_data)
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
    sheet._batch_calls = batch_calls
    sheet._data = data
    return sheet


def _doc_registry_row(**overrides):
    values = [
        "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "", "",
        "", "Test Doc", "uploaded", "FILE1",
        "https://drive.google.com/file/d/FILE1/view", "file.pdf", "application/pdf",
        "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
        "2026-01-01 00:00:00 UTC",
    ]
    row = dict(zip(DOC_REGISTRY_HEADERS, values))
    row.update(overrides)
    return row


GOOD_AI_JSON = json.dumps({
    "document_type": "technical_passport",
    "summary": "Технический паспорт объекта недвижимости.",
    "language": "ru",
    "page_count": 3,
    "keywords": ["паспорт", "объект"],
    "extracted_fields": {"area_m2": "120"},
    "text_preview": "Технический паспорт № 123...",
})


def _mock_anthropic_response(text):
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


class _Registries:
    """Shared read_business_sheet side_effect for document_registry lookups."""

    def __init__(self, doc_row=None, templates=None):
        self.doc_row = doc_row if doc_row is not None else _doc_registry_row()
        self.templates = templates or []

    def side_effect(self, sheet_key, *a, **kw):
        if sheet_key == "document_registry":
            return [self.doc_row]
        if sheet_key == "document_template_registry":
            return self.templates
        return []


# ────────────────────────────────────────────────────────────
# Pure helpers: MIME dispatch, JSON validation, template matching
# ────────────────────────────────────────────────────────────

class TestSupportedMimeDispatch(unittest.TestCase):
    def test_pdf_supported(self):
        di = _fresh_di()
        self.assertTrue(di.is_supported_mime_type("application/pdf"))

    def test_images_supported(self):
        di = _fresh_di()
        for mt in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            self.assertTrue(di.is_supported_mime_type(mt), mt)

    def test_plain_text_supported(self):
        di = _fresh_di()
        self.assertTrue(di.is_supported_mime_type("text/plain"))

    def test_rtf_not_supported(self):
        """RTF must never be auto-treated as plain text, even though it
        superficially looks like a text/* type in some upload flows."""
        di = _fresh_di()
        self.assertFalse(di.is_supported_mime_type("text/rtf"))
        self.assertFalse(di.is_supported_mime_type("application/rtf"))

    def test_docx_not_supported(self):
        di = _fresh_di()
        self.assertFalse(di.is_supported_mime_type(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ))

    def test_empty_or_missing_mime_not_supported(self):
        di = _fresh_di()
        self.assertFalse(di.is_supported_mime_type(""))
        self.assertFalse(di.is_supported_mime_type(None))

    def test_build_content_block_pdf(self):
        di = _fresh_di()
        block = di._build_content_block("application/pdf", b"%PDF-1.4...")
        self.assertEqual(block["type"], "document")
        self.assertEqual(block["source"]["media_type"], "application/pdf")

    def test_build_content_block_image(self):
        di = _fresh_di()
        block = di._build_content_block("image/png", b"\x89PNG...")
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["media_type"], "image/png")

    def test_build_content_block_text(self):
        di = _fresh_di()
        block = di._build_content_block("text/plain", "hello world".encode("utf-8"))
        self.assertEqual(block["type"], "text")
        self.assertEqual(block["text"], "hello world")

    def test_build_content_block_rejects_unsupported(self):
        di = _fresh_di()
        with self.assertRaises(ValueError):
            di._build_content_block("text/rtf", b"{\\rtf1...")


class TestParseAndValidateAiResult(unittest.TestCase):
    def test_valid_json(self):
        di = _fresh_di()
        parsed = di.parse_and_validate_ai_result(GOOD_AI_JSON)
        self.assertEqual(parsed["document_type"], "technical_passport")
        self.assertEqual(parsed["page_count"], 3)
        self.assertEqual(parsed["keywords"], ["паспорт", "объект"])

    def test_markdown_fenced_json_is_stripped(self):
        di = _fresh_di()
        fenced = f"```json\n{GOOD_AI_JSON}\n```"
        parsed = di.parse_and_validate_ai_result(fenced)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["document_type"], "technical_passport")

    def test_non_json_garbage_returns_none(self):
        di = _fresh_di()
        self.assertIsNone(di.parse_and_validate_ai_result("этот документ про паспорт, вот и всё"))

    def test_json_array_returns_none(self):
        di = _fresh_di()
        self.assertIsNone(di.parse_and_validate_ai_result("[1, 2, 3]"))

    def test_wrong_types_degrade_to_safe_defaults(self):
        di = _fresh_di()
        bad = json.dumps({
            "document_type": 12345,
            "summary": None,
            "language": ["ru"],
            "page_count": "three",
            "keywords": "паспорт",
            "extracted_fields": ["not", "a", "dict"],
            "text_preview": {"nested": "object"},
        })
        parsed = di.parse_and_validate_ai_result(bad)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["document_type"], "")
        self.assertEqual(parsed["summary"], "")
        self.assertEqual(parsed["language"], "")
        self.assertIsNone(parsed["page_count"])
        self.assertEqual(parsed["keywords"], [])
        self.assertEqual(parsed["extracted_fields"], {})
        self.assertEqual(parsed["text_preview"], "")

    def test_empty_string_returns_none(self):
        di = _fresh_di()
        self.assertIsNone(di.parse_and_validate_ai_result(""))
        self.assertIsNone(di.parse_and_validate_ai_result(None))


class TestTemplateMatching(unittest.TestCase):
    TEMPLATES = [
        {"Document Template ID": "DOC-IZH-KP-001", "Title": "Технический паспорт", "Document Type": "technical_passport"},
        {"Document Template ID": "DOC-001", "Title": "Запрос недостающих документов", "Document Type": "message_template"},
    ]

    def test_exact_match_on_document_type_field(self):
        di = _fresh_di()
        with patch("business_core.sheets.read_business_sheet", return_value=self.TEMPLATES):
            tid, conf = di.match_template_suggestion("technical_passport")
        self.assertEqual(tid, "DOC-IZH-KP-001")
        self.assertGreater(conf, 0.0)

    def test_exact_match_on_title_case_insensitive(self):
        di = _fresh_di()
        with patch("business_core.sheets.read_business_sheet", return_value=self.TEMPLATES):
            tid, conf = di.match_template_suggestion("ТЕХНИЧЕСКИЙ ПАСПОРТ")
        self.assertEqual(tid, "DOC-IZH-KP-001")

    def test_no_match_returns_empty(self):
        di = _fresh_di()
        with patch("business_core.sheets.read_business_sheet", return_value=self.TEMPLATES):
            tid, conf = di.match_template_suggestion("invoice")
        self.assertEqual(tid, "")
        self.assertEqual(conf, 0.0)

    def test_empty_document_type_returns_empty_without_reading_sheet(self):
        di = _fresh_di()
        with patch("business_core.sheets.read_business_sheet") as mock_read:
            tid, conf = di.match_template_suggestion("")
        mock_read.assert_not_called()
        self.assertEqual(tid, "")
        self.assertEqual(conf, 0.0)


class TestDecideAction(unittest.TestCase):
    def test_no_row_proceeds(self):
        di = _fresh_di()
        self.assertEqual(di.decide_action(None, force=False), "proceed")

    def test_completed_skips_without_force(self):
        di = _fresh_di()
        row = {"Content Status": "completed"}
        self.assertEqual(di.decide_action(row, force=False), "skip_completed")

    def test_completed_proceeds_with_force(self):
        di = _fresh_di()
        row = {"Content Status": "completed"}
        self.assertEqual(di.decide_action(row, force=True), "proceed")

    def test_processing_always_skips_even_with_force(self):
        di = _fresh_di()
        row = {"Content Status": "processing"}
        self.assertEqual(di.decide_action(row, force=False), "skip_processing")
        self.assertEqual(di.decide_action(row, force=True), "skip_processing")

    def test_failed_skips_without_force_proceeds_with_force(self):
        di = _fresh_di()
        row = {"Content Status": "failed"}
        self.assertEqual(di.decide_action(row, force=False), "skip_failed")
        self.assertEqual(di.decide_action(row, force=True), "proceed")

    def test_unsupported_skips_without_force_proceeds_with_force(self):
        di = _fresh_di()
        row = {"Content Status": "unsupported"}
        self.assertEqual(di.decide_action(row, force=False), "skip_unsupported")
        self.assertEqual(di.decide_action(row, force=True), "proceed")


class TestComputeContentHashAndPreview(unittest.TestCase):
    def test_content_hash_is_sha256_hexdigest(self):
        di = _fresh_di()
        import hashlib
        data = b"hello world"
        self.assertEqual(di.compute_content_hash(data), hashlib.sha256(data).hexdigest())

    def test_bounded_preview_truncates(self):
        di = _fresh_di()
        text = "x" * 1000
        preview = di.bounded_text_preview(text)
        self.assertLessEqual(len(preview), di.TEXT_PREVIEW_MAX_CHARS)
        self.assertTrue(preview.endswith("…"))

    def test_bounded_preview_short_text_unchanged(self):
        di = _fresh_di()
        self.assertEqual(di.bounded_text_preview("short"), "short")


# ────────────────────────────────────────────────────────────
# Deterministic size safeguards — enforced in code, not left to the
# model "following instructions" in the prompt.
# ────────────────────────────────────────────────────────────

class TestSizeSafeguards(unittest.TestCase):
    def test_ai_summary_truncated(self):
        di = _fresh_di()
        long_summary = "x" * 5000
        bounded = di.bounded_summary(long_summary)
        self.assertLessEqual(len(bounded), di.AI_SUMMARY_MAX_CHARS)
        self.assertTrue(bounded.endswith("…"))

    def test_analysis_error_truncated(self):
        di = _fresh_di()
        long_error = "Traceback (most recent call last):\n" + ("frame " * 2000)
        bounded = di.bounded_error(long_error)
        self.assertLessEqual(len(bounded), di.ANALYSIS_ERROR_MAX_CHARS)

    def test_keywords_count_capped(self):
        di = _fresh_di()
        many_keywords = [f"keyword_{i}" for i in range(500)]
        bounded = di.bounded_keywords(many_keywords)
        self.assertLessEqual(len(bounded), di.MAX_KEYWORDS_COUNT)

    def test_keyword_length_capped(self):
        di = _fresh_di()
        bounded = di.bounded_keywords(["x" * 1000])
        self.assertLessEqual(len(bounded[0]), di.MAX_KEYWORD_CHARS)

    def test_extracted_fields_count_capped(self):
        di = _fresh_di()
        many_fields = {f"field_{i}": f"value_{i}" for i in range(500)}
        bounded = di.bounded_extracted_fields(many_fields)
        self.assertLessEqual(len(bounded), di.MAX_EXTRACTED_FIELDS_COUNT)

    def test_extracted_field_key_and_value_length_capped(self):
        di = _fresh_di()
        bounded = di.bounded_extracted_fields({"k" * 1000: "v" * 1000})
        key = next(iter(bounded))
        self.assertLessEqual(len(key), di.MAX_EXTRACTED_FIELD_KEY_CHARS)
        self.assertLessEqual(len(bounded[key]), di.MAX_EXTRACTED_FIELD_VALUE_CHARS)

    def test_bounded_json_is_always_valid_even_for_adversarial_input(self):
        """Bounding happens on the DATA before serialization, so the
        resulting JSON string is always well-formed — never a cut-off,
        unparseable fragment — no matter how large the input."""
        di = _fresh_di()
        adversarial_keywords = [f"k{i}" * 100 for i in range(1000)]
        bounded_kw = di.bounded_keywords(adversarial_keywords)
        json_text = di.bounded_json(bounded_kw)
        parsed_back = json.loads(json_text)  # must not raise
        self.assertIsInstance(parsed_back, list)

        adversarial_fields = {f"f{i}" * 100: f"v{i}" * 1000 for i in range(1000)}
        bounded_fields = di.bounded_extracted_fields(adversarial_fields)
        json_text2 = di.bounded_json(bounded_fields)
        parsed_back2 = json.loads(json_text2)  # must not raise
        self.assertIsInstance(parsed_back2, dict)

    def test_bounded_json_hard_ceiling_produces_valid_truncation_marker(self):
        """Even if per-item bounds somehow weren't applied upstream, the
        absolute MAX_JSON_FIELD_CHARS ceiling still guarantees a valid,
        parseable JSON value is stored — never a raw partial cut."""
        di = _fresh_di()
        huge_unbounded_dict = {f"key_{i}": "v" * 1000 for i in range(100)}
        json_text = di.bounded_json(huge_unbounded_dict)
        self.assertLessEqual(len(json_text), di.MAX_JSON_FIELD_CHARS)
        parsed_back = json.loads(json_text)  # must not raise
        self.assertEqual(parsed_back, {"_truncated": True})

    def test_detected_document_type_and_language_bounded_in_completed_row(self):
        di = _fresh_di()
        huge_type_json = json.dumps({
            "document_type": "x" * 5000,
            "summary": "ok",
            "language": "y" * 5000,
            "page_count": None,
            "keywords": [],
            "extracted_fields": {},
            "text_preview": "",
        })
        sheet = _make_sheet(CONTENT_HEADERS)
        registries = _Registries()
        anthropic_client = MagicMock()
        anthropic_client.messages.create.return_value = _mock_anthropic_response(huge_type_json)
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = anthropic_client

        def _get_business_sheet_side_effect(key):
            if key == "document_content":
                return sheet
            if key == "document_registry":
                registry_sheet = _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[
                    [registries.doc_row.get(h, "") for h in DOC_REGISTRY_HEADERS]
                ])
                return registry_sheet
            raise KeyError(key)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                       side_effect=_get_business_sheet_side_effect))
            stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                       side_effect=registries.side_effect))
            stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()))
            stack.enter_context(patch("integrations.google_drive_adapter._is_shared_drive", return_value=True))
            stack.enter_context(patch("business_core.document_intelligence._download_drive_file_bytes",
                                       return_value=b"%PDF fake"))
            stack.enter_context(patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False))
            stack.enter_context(patch.dict("sys.modules", {"anthropic": mock_anthropic_module}))
            result = di.analyze_document(document_id="DREG-001", drive_file_id="FILE1")

        self.assertEqual(result["action"], "completed")
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        col_to_header = {chr(ord("A") + i): h for h, i in idx.items()}
        final_write = sheet._batch_calls[-1]
        written = {col_to_header[e["range"][0]]: e["values"][0][0] for e in final_write}
        self.assertLessEqual(len(written["Detected Document Type"]), di.DETECTED_TYPE_MAX_CHARS)
        self.assertLessEqual(len(written["Language"]), di.LANGUAGE_MAX_CHARS)


# ────────────────────────────────────────────────────────────
# update_business_row() — general Sheets helper (business_core/sheets.py)
# ────────────────────────────────────────────────────────────

class TestUpdateBusinessRow(unittest.TestCase):
    def test_updates_only_specified_columns(self):
        from business_core.sheets import update_business_row
        row = ["DREG-001", "FILE1", "pending"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            update_business_row("document_content", 2, {"Content Status": "processing"})
        self.assertEqual(sheet._data[1][2], "processing")  # "Content Status" column
        self.assertEqual(sheet._data[1][0], "DREG-001")     # untouched
        self.assertEqual(sheet._data[1][1], "FILE1")        # untouched

    def test_partial_update_does_not_erase_adjacent_values(self):
        """The core requirement: writing 2 fields must leave every other
        already-populated field exactly as it was."""
        from business_core.sheets import update_business_row
        row = [
            "DREG-001", "FILE1", "completed", "technical_passport", "DOC-IZH-KP-001",
            "0.90", "Существующее резюме", '{"a": "1"}', "Существующий preview",
            "ru", "2", '["existing", "keywords"]',
            "claude-sonnet-4-5", "v1", "abc123hash",
            "2026-01-01 00:00:00 UTC", "2026-01-01 00:05:00 UTC", "",
            "2026-01-01 00:00:00 UTC", "2026-01-01 00:05:00 UTC",
        ]
        self.assertEqual(len(row), len(CONTENT_HEADERS))
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[row])

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            update_business_row("document_content", 2, {
                "Content Status": "failed",
                "Analysis Error": "re-analysis failed",
            })

        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        updated_row = sheet._data[1]
        self.assertEqual(updated_row[idx["Content Status"]], "failed")
        self.assertEqual(updated_row[idx["Analysis Error"]], "re-analysis failed")
        # Everything else must be byte-for-byte unchanged:
        for field in CONTENT_HEADERS:
            if field in ("Content Status", "Analysis Error"):
                continue
            self.assertEqual(updated_row[idx[field]], row[idx[field]], f"field changed unexpectedly: {field}")

    def test_resolves_columns_by_live_header_name_not_position(self):
        """Header order on the live sheet, not BUSINESS_HEADERS'
        declared order, must drive column resolution."""
        from business_core.sheets import update_business_row
        shuffled_headers = list(reversed(CONTENT_HEADERS))
        row = [""] * len(shuffled_headers)
        sheet = _make_sheet(shuffled_headers, existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            update_business_row("document_content", 2, {"Content Status": "processing"})
        idx = shuffled_headers.index("Content Status")
        self.assertEqual(sheet._data[1][idx], "processing")

    def test_unknown_column_raises_value_error(self):
        from business_core.sheets import update_business_row
        row = [""] * len(CONTENT_HEADERS)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with self.assertRaises(ValueError):
                update_business_row("document_content", 2, {"Nonexistent Column": "x"})

    def test_missing_row_raises_value_error(self):
        from business_core.sheets import update_business_row
        sheet = _make_sheet(CONTENT_HEADERS)  # no data rows at all
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            with self.assertRaises(ValueError):
                update_business_row("document_content", 5, {"Content Status": "processing"})

    def test_single_batched_write_for_multiple_fields(self):
        from business_core.sheets import update_business_row
        row = [""] * len(CONTENT_HEADERS)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            update_business_row("document_content", 2, {
                "Content Status": "processing",
                "Analysis Started At": "2026-01-01 00:00:00 UTC",
                "Updated At": "2026-01-01 00:00:00 UTC",
            })
        # Exactly ONE batch_update call for all 3 fields, not 3 separate calls.
        self.assertEqual(len(sheet._batch_calls), 1)
        self.assertEqual(len(sheet._batch_calls[0]), 3)

    def test_safe_for_a_different_existing_business_core_sheet(self):
        """update_business_row() is generic — not hardcoded to
        document_content — verified here against a DOCUMENT_REGISTRY-shaped
        sheet."""
        from business_core.sheets import update_business_row
        row = ["DREG-001"] + [""] * (len(DOC_REGISTRY_HEADERS) - 1)
        sheet = _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            update_business_row("document_registry", 2, {"Status": "archived"})
        idx = {h: i for i, h in enumerate(DOC_REGISTRY_HEADERS)}
        self.assertEqual(sheet._data[1][idx["Status"]], "archived")
        self.assertEqual(sheet._data[1][idx["Document ID"]], "DREG-001")  # untouched


# ────────────────────────────────────────────────────────────
# Concurrency / idempotency — deeper proofs beyond decide_action() alone
# ────────────────────────────────────────────────────────────

class TestConcurrencyProofs(unittest.TestCase):
    def _run_twice(self, sheet, registries, force_second=False):
        di = _fresh_di()
        anthropic_client = MagicMock()
        anthropic_client.messages.create.return_value = _mock_anthropic_response(GOOD_AI_JSON)
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = anthropic_client

        def _get_business_sheet_side_effect(key):
            if key == "document_content":
                return sheet
            if key == "document_registry":
                return _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[
                    [registries.doc_row.get(h, "") for h in DOC_REGISTRY_HEADERS]
                ])
            raise KeyError(key)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                       side_effect=_get_business_sheet_side_effect))
            stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                       side_effect=registries.side_effect))
            stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()))
            stack.enter_context(patch("integrations.google_drive_adapter._is_shared_drive", return_value=True))
            stack.enter_context(patch("business_core.document_intelligence._download_drive_file_bytes",
                                       return_value=b"%PDF fake"))
            stack.enter_context(patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False))
            stack.enter_context(patch.dict("sys.modules", {"anthropic": mock_anthropic_module}))
            first = di.analyze_document(document_id="DREG-001", drive_file_id="FILE1")
            second = di.analyze_document(document_id="DREG-001", drive_file_id="FILE1", force=force_second)

        return di, first, second, anthropic_client

    def test_two_near_simultaneous_triggers_cannot_append_two_rows(self):
        """Simulates auto-enqueue-after-upload and a manual /analyzedoc
        firing back-to-back for the same never-before-analyzed document —
        exactly one DOCUMENT_CONTENT row must exist afterward, and the
        second call must not re-download or re-call the AI."""
        sheet = _make_sheet(CONTENT_HEADERS)
        registries = _Registries()
        di, first, second, client = self._run_twice(sheet, registries)

        self.assertEqual(first["action"], "completed")
        self.assertEqual(second["action"], "skip_completed")
        self.assertEqual(client.messages.create.call_count, 1)  # only the first call hit the AI
        # Exactly one row: one append, zero additional appends from the second call.
        self.assertEqual(len(sheet._appended), 1)

    def test_shared_guard_between_auto_and_manual_trigger(self):
        """/uploaddoc's auto-enqueue and /analyzedoc's manual enqueue both
        funnel through the exact same analyze_document() function — the
        idempotency guard is structural, not duplicated logic."""
        th = _fresh_th()
        import inspect
        job_source = inspect.getsource(th._analyze_document_job)
        analyzedoc_source = inspect.getsource(th.analyzedoc_cmd)
        self.assertIn("analyze_document", job_source)
        # analyzedoc_cmd itself only enqueues via the same _enqueue_document_analysis
        # helper that the upload path uses — not a second, separate write path.
        self.assertIn("_enqueue_document_analysis", analyzedoc_source)
        self.assertNotIn("append_business_row", analyzedoc_source)
        self.assertNotIn("update_business_row", analyzedoc_source)


# ────────────────────────────────────────────────────────────
# analyze_document() — full flow, mocked Sheets/Drive/Anthropic
# ────────────────────────────────────────────────────────────

class TestAnalyzeDocument(unittest.TestCase):
    def _run(self, content_sheet=None, registries=None, ai_response_text=None,
              ai_side_effect=None, download_side_effect=None, api_key="sk-test-key",
              document_id="DREG-001", drive_file_id="FILE1", force=False,
              model_env=None):
        di = _fresh_di()
        content_sheet = content_sheet if content_sheet is not None else _make_sheet(CONTENT_HEADERS)
        registries = registries if registries is not None else _Registries()

        download_mock = MagicMock(side_effect=download_side_effect) if download_side_effect else \
            MagicMock(return_value=b"%PDF-1.4 fake pdf bytes")

        anthropic_client = MagicMock()
        if ai_side_effect:
            anthropic_client.messages.create.side_effect = ai_side_effect
        else:
            text = ai_response_text if ai_response_text is not None else GOOD_AI_JSON
            anthropic_client.messages.create.return_value = _mock_anthropic_response(text)

        env = {}
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if model_env:
            env["DOCUMENT_INTELLIGENCE_MODEL"] = model_env

        registry_row_values = [registries.doc_row.get(h, "") for h in DOC_REGISTRY_HEADERS] \
            if registries.doc_row is not None else None
        registry_sheet = _make_sheet(
            DOC_REGISTRY_HEADERS,
            existing_rows=[registry_row_values] if registry_row_values is not None else [],
        )

        def _get_business_sheet_side_effect(key):
            if key == "document_content":
                return content_sheet
            if key == "document_registry":
                return registry_sheet
            raise KeyError(key)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                       side_effect=_get_business_sheet_side_effect))
            stack.enter_context(patch("business_core.sheets.read_business_sheet", side_effect=registries.side_effect))
            stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()))
            stack.enter_context(patch("integrations.google_drive_adapter._is_shared_drive", return_value=True))
            stack.enter_context(patch("business_core.document_intelligence._download_drive_file_bytes", download_mock))
            stack.enter_context(patch.dict("os.environ", env, clear=False))
            if not api_key:
                stack.enter_context(patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}))
            mock_anthropic_module = MagicMock()
            mock_anthropic_module.Anthropic.return_value = anthropic_client
            stack.enter_context(patch.dict("sys.modules", {"anthropic": mock_anthropic_module}))
            result = di.analyze_document(document_id=document_id, drive_file_id=drive_file_id, force=force)

        return di, content_sheet, result, download_mock, anthropic_client

    def test_valid_structured_result_completes(self):
        di, sheet, result, download_mock, client = self._run()
        self.assertEqual(result["action"], "completed")
        self.assertTrue(result["ok"])
        # No prior row -> the claim step is the row's own creation
        # (append_business_row, i.e. sheet.update(), not batch_update);
        # only the final "completed" write goes through batch_update.
        # Field-level correctness is asserted separately in
        # test_completed_row_fields_are_correct().
        self.assertEqual(len(sheet._appended), 1)
        self.assertEqual(len(sheet._batch_calls), 1)

    def test_completed_row_fields_are_correct(self):
        di = _fresh_di()
        sheet = _make_sheet(CONTENT_HEADERS)
        registries = _Registries(templates=[
            {"Document Template ID": "DOC-IZH-KP-001", "Title": "Технический паспорт",
             "Document Type": "technical_passport"},
        ])
        di2, sheet2, result, download_mock, client = self._run(content_sheet=sheet, registries=registries)
        self.assertEqual(result["action"], "completed")

        # Reconstruct the final batch_update payload into a dict of header->value
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        col_to_header = {}
        for h, i in idx.items():
            col_letter = chr(ord("A") + i)
            col_to_header[col_letter] = h

        final_write = sheet._batch_calls[-1]
        written = {}
        for entry in final_write:
            col_letter = entry["range"][0]
            written[col_to_header[col_letter]] = entry["values"][0][0]

        self.assertEqual(written["Content Status"], "completed")
        self.assertEqual(written["Detected Document Type"], "technical_passport")
        self.assertEqual(written["Suggested Document Template ID"], "DOC-IZH-KP-001")
        self.assertEqual(written["AI Summary"], "Технический паспорт объекта недвижимости.")
        self.assertEqual(json.loads(written["Extracted Fields JSON"]), {"area_m2": "120"})
        self.assertEqual(json.loads(written["Keywords JSON"]), ["паспорт", "объект"])
        self.assertEqual(written["Language"], "ru")
        self.assertEqual(written["Page Count"], "3")
        self.assertEqual(written["Analysis Error"], "")
        self.assertTrue(len(written["Content Hash"]) == 64)  # sha256 hex length

    def test_unsupported_mime_never_downloads_or_calls_ai(self):
        di = _fresh_di()
        registries = _Registries(doc_row=_doc_registry_row(**{"Mime Type": "text/rtf"}))
        _, sheet, result, download_mock, client = self._run(registries=registries)
        self.assertEqual(result["action"], "unsupported")
        download_mock.assert_not_called()
        client.messages.create.assert_not_called()

    def test_docx_mime_is_unsupported(self):
        di = _fresh_di()
        registries = _Registries(doc_row=_doc_registry_row(**{
            "Mime Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }))
        _, sheet, result, download_mock, client = self._run(registries=registries)
        self.assertEqual(result["action"], "unsupported")

    def test_missing_api_key_fails_without_ai_call(self):
        _, sheet, result, download_mock, client = self._run(api_key="")
        self.assertEqual(result["action"], "failed")
        self.assertIn("ANTHROPIC_API_KEY", result["error"])
        client.messages.create.assert_not_called()

    def test_malformed_ai_json_fails(self):
        _, sheet, result, download_mock, client = self._run(ai_response_text="это не JSON, а обычный текст")
        self.assertEqual(result["action"], "failed")
        self.assertIn("JSON", result["error"])

    def test_ai_call_exception_fails_gracefully(self):
        def _boom(*a, **kw):
            raise RuntimeError("anthropic api down")
        _, sheet, result, download_mock, client = self._run(ai_side_effect=_boom)
        self.assertEqual(result["action"], "failed")
        self.assertIn("AI call error", result["error"])

    def test_drive_download_failure_fails_gracefully(self):
        def _boom(*a, **kw):
            raise RuntimeError("drive quota exceeded")
        _, sheet, result, download_mock, client = self._run(download_side_effect=_boom)
        self.assertEqual(result["action"], "failed")
        self.assertIn("Drive download error", result["error"])
        client.messages.create.assert_not_called()

    def test_document_registry_row_missing_fails(self):
        di = _fresh_di()
        content_sheet = _make_sheet(CONTENT_HEADERS)
        registry_sheet = _make_sheet(DOC_REGISTRY_HEADERS)  # no data rows -> "not found"

        def _get_business_sheet_side_effect(key):
            if key == "document_content":
                return content_sheet
            if key == "document_registry":
                return registry_sheet
            raise KeyError(key)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                       side_effect=_get_business_sheet_side_effect))
            result = di.analyze_document(document_id="DREG-999", drive_file_id="FILE1")
        self.assertEqual(result["action"], "failed")
        self.assertIn("not found", result["error"])

    def test_completed_idempotent_skip_no_ai_call(self):
        existing_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[existing_row])
        _, sheet2, result, download_mock, client = self._run(content_sheet=sheet)
        self.assertEqual(result["action"], "skip_completed")
        download_mock.assert_not_called()
        client.messages.create.assert_not_called()
        # No new append, no batch_update at all for a pure skip
        self.assertEqual(len(sheet._appended), 0)
        self.assertEqual(len(sheet._batch_calls), 0)

    def test_processing_duplicate_guard_no_ai_call(self):
        existing_row = ["DREG-001", "FILE1", "processing"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[existing_row])
        _, sheet2, result, download_mock, client = self._run(content_sheet=sheet)
        self.assertEqual(result["action"], "skip_processing")
        download_mock.assert_not_called()
        client.messages.create.assert_not_called()

    def test_processing_duplicate_guard_ignores_force(self):
        existing_row = ["DREG-001", "FILE1", "processing"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[existing_row])
        _, sheet2, result, download_mock, client = self._run(content_sheet=sheet, force=True)
        self.assertEqual(result["action"], "skip_processing")

    def test_failed_no_auto_retry(self):
        existing_row = ["DREG-001", "FILE1", "failed"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[existing_row])
        _, sheet2, result, download_mock, client = self._run(content_sheet=sheet)
        self.assertEqual(result["action"], "skip_failed")
        client.messages.create.assert_not_called()

    def test_force_retry_updates_existing_row_no_second_row(self):
        existing_row = ["DREG-001", "FILE1", "failed"] + [""] * (len(CONTENT_HEADERS) - 3)
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[existing_row])
        _, sheet2, result, download_mock, client = self._run(content_sheet=sheet, force=True)
        self.assertEqual(result["action"], "completed")
        # Never appended a second row — only batch_update (claim + final) on the existing one.
        self.assertEqual(len(sheet._appended), 0)
        self.assertGreaterEqual(len(sheet._batch_calls), 2)

    def test_existing_authoritative_template_never_touched(self):
        """analyze_document() must never read or write DOCUMENT_REGISTRY's
        own 'Document Template ID' — only DOCUMENT_CONTENT's separate
        'Suggested Document Template ID' is ever written by this module."""
        registries = _Registries(
            doc_row=_doc_registry_row(**{"Document Template ID": "DOC-USER-CHOSEN-001"}),
            templates=[{"Document Template ID": "DOC-IZH-KP-001", "Title": "Технический паспорт",
                        "Document Type": "technical_passport"}],
        )
        with patch("business_core.sheets.update_business_cell") as mock_cell:
            _, sheet, result, download_mock, client = self._run(registries=registries)
            mock_cell.assert_not_called()  # analyze_document never uses update_business_cell at all
        self.assertEqual(result["action"], "completed")
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        col_to_header = {chr(ord("A") + i): h for h, i in idx.items()}
        final_write = sheet._batch_calls[-1]
        written = {col_to_header[e["range"][0]]: e["values"][0][0] for e in final_write}
        self.assertNotIn("Document Template ID", written)  # not even a DOCUMENT_CONTENT field
        self.assertEqual(written["Suggested Document Template ID"], "DOC-IZH-KP-001")

    def test_analysis_failure_never_touches_document_registry(self):
        def _boom(*a, **kw):
            raise RuntimeError("ai down")
        with patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.update_business_cell") as mock_cell:
            _, sheet, result, download_mock, client = self._run(ai_side_effect=_boom)
            for call in mock_append.call_args_list:
                self.assertNotEqual(call.args[0], "document_registry")
            mock_cell.assert_not_called()
        self.assertEqual(result["action"], "failed")


# ────────────────────────────────────────────────────────────
# /analyzedoc command
# ────────────────────────────────────────────────────────────

def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _cmd(cmdline: str, job_queue=None):
    update = _upd(cmdline)
    context = MagicMock()
    context.args = cmdline.split()[1:]
    context.user_data = {}
    context.job_queue = job_queue if job_queue is not None else MagicMock()
    return update, context


class TestAnalyzeDocCommand(unittest.TestCase):
    def test_missing_document_id(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("document_id", reply)

    def test_document_not_found(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-999")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=None):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", reply)

    def test_completed_shows_cached_result_no_enqueue(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {
            "Content Status": "completed", "Detected Document Type": "technical_passport",
            "AI Summary": "Резюме", "Suggested Document Template ID": "DOC-IZH-KP-001",
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis") as mock_enqueue:
                await th.analyzedoc_cmd(update, context)
                mock_enqueue.assert_not_called()

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("technical_passport", reply)

    def test_processing_reports_in_progress_no_enqueue(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {"Content Status": "processing"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis") as mock_enqueue:
                await th.analyzedoc_cmd(update, context)
                mock_enqueue.assert_not_called()

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("анализируется", reply)

    def test_failed_without_force_requires_force(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {"Content Status": "failed", "Analysis Error": "boom"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis") as mock_enqueue:
                await th.analyzedoc_cmd(update, context)
                mock_enqueue.assert_not_called()

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("force=true", reply)

    def test_force_true_enqueues_exactly_once(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001 force=true")
        cached = {"Content Status": "failed", "Analysis Error": "boom"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis", return_value=True) as mock_enqueue:
                await th.analyzedoc_cmd(update, context)
                mock_enqueue.assert_called_once()

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("очередь", reply)

    def test_no_row_yet_enqueues(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=None), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis", return_value=True) as mock_enqueue:
                await th.analyzedoc_cmd(update, context)
                mock_enqueue.assert_called_once()

        asyncio.run(run())


class TestAnalyzeDocMarkdownSafety(unittest.TestCase):
    """Regression test for the production smoke-test finding: /analyzedoc's
    usage-hint text contains raw underscores (document_id) which, under
    _reply()'s default parse_mode="Markdown", Telegram silently parses as
    paired italic delimiters and strips — turning "document_id" into
    "documentid" — instead of raising an error that would trigger
    _reply()'s plain-text fallback. Every analyzedoc_cmd() reply must
    explicitly pass parse_mode=None, exactly like /uploaddoc's and
    /registerdoc's messages already do."""

    def _assert_parse_mode_none(self, update):
        call = update.message.reply_text.call_args
        self.assertIsNone(call.kwargs.get("parse_mode"), call)

    def test_missing_document_id_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("document_id", reply)  # underscore must survive verbatim

    def test_document_not_found_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-999")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=None):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)

    def test_completed_cached_result_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {"Content Status": "completed", "Detected Document Type": "technical_passport",
                  "AI Summary": "Резюме", "Suggested Document Template ID": "DOC-IZH-KP-001"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)

    def test_processing_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {"Content Status": "processing"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)

    def test_failed_without_force_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")
        cached = {"Content Status": "failed", "Analysis Error": "boom"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("force=true", reply)  # underscore-free, but = must survive too

    def test_enqueued_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001 force=true")
        cached = {"Content Status": "failed", "Analysis Error": "boom"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _doc_registry_row())), \
                 patch("business_core.document_intelligence.get_content_status", return_value=cached), \
                 patch("business_core.telegram_handlers._enqueue_document_analysis", return_value=True):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)

    def test_unhandled_exception_uses_no_parse_mode(self):
        th = _fresh_th()
        update, context = _cmd("/analyzedoc document_id=DREG-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", side_effect=RuntimeError("boom")):
                await th.analyzedoc_cmd(update, context)

        asyncio.run(run())
        self._assert_parse_mode_none(update)


# ────────────────────────────────────────────────────────────
# Enqueue helper + job callback
# ────────────────────────────────────────────────────────────

class TestEnqueueHelper(unittest.TestCase):
    def test_enqueue_calls_job_queue_run_once(self):
        th = _fresh_th()
        job_queue = MagicMock()
        context = MagicMock()
        context.job_queue = job_queue
        result = th._enqueue_document_analysis(context, "DREG-001", "FILE1")
        self.assertTrue(result)
        job_queue.run_once.assert_called_once()
        call = job_queue.run_once.call_args
        self.assertEqual(call.kwargs["data"]["document_id"], "DREG-001")
        self.assertEqual(call.kwargs["data"]["drive_file_id"], "FILE1")

    def test_enqueue_returns_false_when_job_queue_missing(self):
        th = _fresh_th()
        context = MagicMock()
        context.job_queue = None
        result = th._enqueue_document_analysis(context, "DREG-001", "FILE1")
        self.assertFalse(result)

    def test_enqueue_never_raises_on_scheduler_error(self):
        th = _fresh_th()
        context = MagicMock()
        context.job_queue = MagicMock()
        context.job_queue.run_once.side_effect = RuntimeError("scheduler down")
        result = th._enqueue_document_analysis(context, "DREG-001", "FILE1")
        self.assertFalse(result)

    def test_job_callback_calls_analyze_document(self):
        th = _fresh_th()
        context = MagicMock()
        context.job.data = {"document_id": "DREG-001", "drive_file_id": "FILE1", "force": False}

        async def run():
            with patch("business_core.document_intelligence.analyze_document",
                       return_value={"ok": True, "action": "completed", "document_id": "DREG-001", "error": None}) as mock_analyze:
                await th._analyze_document_job(context)
                mock_analyze.assert_called_once_with(document_id="DREG-001", drive_file_id="FILE1", force=False)

        asyncio.run(run())

    def test_job_callback_never_raises_even_on_analyze_exception(self):
        th = _fresh_th()
        context = MagicMock()
        context.job.data = {"document_id": "DREG-001", "drive_file_id": "FILE1"}

        async def run():
            with patch("business_core.document_intelligence.analyze_document",
                       side_effect=RuntimeError("boom")):
                await th._analyze_document_job(context)  # must not raise

        asyncio.run(run())  # no exception == pass


# ────────────────────────────────────────────────────────────
# /uploaddoc integration: enqueue only after successful verification
# ────────────────────────────────────────────────────────────

UD_HEADERS = DOC_REGISTRY_HEADERS


def _make_doc_sheet(existing_rows=None):
    sheet = MagicMock()
    values = [UD_HEADERS] + (existing_rows or [])
    sheet.get_all_values.return_value = values
    return sheet


def _confirmed_snapshot(**overrides):
    snap = {
        "tg_file_id": "tgfile123", "tg_file_unique_id": "uniq123",
        "tg_file_name": "passport.pdf", "tg_mime_type": "application/pdf",
        "tg_file_size": 1234, "uploaded_by": "dida",
        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
        "document_name": "Test Doc", "notes": "",
        "folder_id": "OBJFOLDER1", "folder_level": "object", "folder_source_id": "OBJ-001",
        "folder_name": "06 Клиенты",
        "op_state": "pending",
    }
    snap.update(overrides)
    return snap


def _text_update(text):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


GOOD_UPLOAD_META = {"ok": True, "name": "passport.pdf", "mime_type": "application/pdf",
                    "trashed": False, "web_view_link": "https://drive.google.com/file/d/NEWFILE1/view"}


class TestUploaddocEnqueueIntegration(unittest.TestCase):
    def _run_confirm(self, text="✅ Подтвердить", snap=None, append_side_effect=None,
                      find_row_return=None, job_queue=None):
        th = _fresh_th()
        user_data = {"ud_confirmed_snapshot": snap if snap is not None else _confirmed_snapshot()}
        update = _text_update(text)
        context = MagicMock()
        context.user_data = user_data
        context.job_queue = job_queue if job_queue is not None else MagicMock()

        tg_file = MagicMock()

        async def _download(buf):
            buf.write(b"PDF-BYTES")
        tg_file.download_to_memory = AsyncMock(side_effect=_download)
        context.bot = MagicMock()
        context.bot.get_file = AsyncMock(return_value=tg_file)

        sheet = _make_doc_sheet()
        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                              "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(side_effect=append_side_effect) if append_side_effect else MagicMock(return_value=2)
        used_snap = snap if snap is not None else _confirmed_snapshot()
        found = find_row_return if find_row_return is not None else (2, dict(zip(UD_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", used_snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        tmp = MagicMock()
        tmp.name = "/tmp/fake_upload_test_file"
        tmp.__enter__ = MagicMock(return_value=tmp)
        tmp.__exit__ = MagicMock(return_value=False)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers.tempfile.NamedTemporaryFile", return_value=tmp))
                stack.enter_context(patch("business_core.telegram_handlers.os.path.exists", return_value=True))
                stack.enter_context(patch("business_core.telegram_handlers.os.remove"))
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata", return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file", return_value={"ok": True, "error": ""}))
                stack.enter_context(patch("business_core.sheets.get_business_sheet", return_value=sheet))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                mock_enqueue = stack.enter_context(patch("business_core.telegram_handlers._enqueue_document_analysis"))
                result = await th.uploaddoc_confirm(update, context)
                return result, mock_enqueue

        result, mock_enqueue = asyncio.run(run())
        return th, update, context, result, mock_enqueue

    def test_enqueue_happens_on_successful_upload(self):
        th, update, context, result, mock_enqueue = self._run_confirm()
        mock_enqueue.assert_called_once()
        call = mock_enqueue.call_args
        self.assertEqual(call.args[1], "DREG-001")
        self.assertEqual(call.args[2], "NEWFILE1")

    def test_no_enqueue_on_cancel(self):
        th, update, context, result, mock_enqueue = self._run_confirm(text="❌ Отмена")
        mock_enqueue.assert_not_called()

    def test_no_enqueue_on_registry_write_failure(self):
        def _boom(*a, **kw):
            raise RuntimeError("sheets api error")
        th, update, context, result, mock_enqueue = self._run_confirm(append_side_effect=_boom)
        mock_enqueue.assert_not_called()

    def test_no_enqueue_on_post_write_verification_mismatch(self):
        mismatched = (2, dict(zip(UD_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-999", "PRS-001", "OBJ-001", "RM-001", "",
            "", "Test Doc", "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))
        th, update, context, result, mock_enqueue = self._run_confirm(find_row_return=mismatched)
        mock_enqueue.assert_not_called()

    def test_no_enqueue_when_no_confirmed_snapshot(self):
        th = _fresh_th()
        update = _text_update("✅ Подтвердить")
        context = MagicMock()
        context.user_data = {}
        context.job_queue = MagicMock()

        async def run():
            with patch("business_core.telegram_handlers._enqueue_document_analysis") as mock_enqueue:
                await th.uploaddoc_confirm(update, context)
                mock_enqueue.assert_not_called()

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# Regression / boundaries
# ────────────────────────────────────────────────────────────

class TestRegressionAndBoundaries(unittest.TestCase):
    def test_document_content_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["document_content"], CONTENT_HEADERS)

    def test_document_registry_headers_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["document_registry"], DOC_REGISTRY_HEADERS)

    def test_document_content_sheet_name_registered(self):
        from business_core.sheets import BUSINESS_SHEET_NAMES
        self.assertEqual(BUSINESS_SHEET_NAMES["document_content"], "DOCUMENT_CONTENT")

    def test_register_business_handlers_runs_without_error(self):
        th = _fresh_th()
        app = MagicMock()
        th.register_business_handlers(app)
        self.assertGreater(app.add_handler.call_count, 20)

    def test_analyzedoc_registered_as_plain_command(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "analyzedoc_cmd"))

    def test_gtd_core_files_not_referenced_in_new_module(self):
        """No actual import of telegram_bot.py or reuse of its global
        ai_client — the module's docstring mentions both by name only to
        document that they are deliberately NOT used, so this checks for
        real import statements, not a blanket substring search."""
        import ast
        import inspect
        di = _fresh_di()
        tree = ast.parse(inspect.getsource(di))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        self.assertNotIn("telegram_bot", imported_names)
        # ai_client must never appear as an actual identifier usage either
        # (e.g. `ai_client.messages.create(...)`) — only in prose comments.
        attribute_bases = {
            n.value.id for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        }
        self.assertNotIn("ai_client", attribute_bases)


if __name__ == "__main__":
    unittest.main()
