"""
Phase 16B.2: Structured Document Fields.

Covers: exact-date parsing (§E), safe alias fallback for
document_number/document_date (§A), issued_by safety (§B — never
derived from developer/contractor/owner/representative), boolean
storage contract (§C), direction storage contract (§D), backward
compatibility with pre-16B.2 rows, reanalysis semantics (§7),
architecture invariants (§9 — no DOCUMENT_REGISTRY/Template ID/
relations/Completion Gate/duplicate-algorithm influence), Telegram UX
(§8), and sensitive-field non-exposure (§12).

All tests fully mock business_core.sheets / integrations.google_drive_adapter
/ anthropic — no live network calls of any kind.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import unittest
from unittest.mock import MagicMock, patch


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
    "Document Number", "Document Date", "Issued By",
    "Valid From", "Valid Until", "Has Expiration",
    "Direction", "Requires Action",
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


def _col_letters_to_index(col_letters: str) -> int:
    n = 0
    for ch in col_letters:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1


def _make_sheet(headers, existing_rows=None):
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


def _mock_anthropic_response(text):
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


class _Registries:
    def __init__(self, doc_row=None, templates=None, content_rows=None, registry_rows=None):
        self.doc_row = doc_row if doc_row is not None else _doc_registry_row()
        self.templates = templates or []
        self.content_rows = content_rows or []
        self.registry_rows = registry_rows

    def side_effect(self, sheet_key, *a, **kw):
        if sheet_key == "document_registry":
            return self.registry_rows if self.registry_rows is not None else [self.doc_row]
        if sheet_key == "document_template_registry":
            return self.templates
        if sheet_key == "document_content":
            return self.content_rows
        return []


# ────────────────────────────────────────────────────────────
# §E: exact-date parsing
# ────────────────────────────────────────────────────────────

class TestParseExactDate(unittest.TestCase):
    def test_exact_iso_date(self):
        di = _fresh_di()
        self.assertEqual(di.parse_exact_date("2026-07-22"), ("2026-07-22", None))

    def test_dot_format_date_signed_alias_value(self):
        """п.2: 'date signed' alias value '22.07.2026' -> exact ISO —
        this is the real DREG-004/DREG-005 production value."""
        di = _fresh_di()
        self.assertEqual(di.parse_exact_date("22.07.2026"), ("2026-07-22", None))

    def test_slash_and_dash_formats(self):
        di = _fresh_di()
        self.assertEqual(di.parse_exact_date("22/07/2026"), ("2026-07-22", None))
        self.assertEqual(di.parse_exact_date("22-07-2026"), ("2026-07-22", None))

    def test_invalid_calendar_date(self):
        """п.3."""
        di = _fresh_di()
        iso, warn = di.parse_exact_date("31.02.2026")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_INVALID_DATE)

    def test_partial_month_year_ignored(self):
        """п.4."""
        di = _fresh_di()
        iso, warn = di.parse_exact_date("февраль 2026 г.")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_PARTIAL_DATE_IGNORED)

    def test_year_only_ignored(self):
        di = _fresh_di()
        iso, warn = di.parse_exact_date("2026")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_PARTIAL_DATE_IGNORED)

    def test_season_and_year_ignored(self):
        di = _fresh_di()
        iso, warn = di.parse_exact_date("лето 2026")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_PARTIAL_DATE_IGNORED)

    def test_day_month_without_year_ignored(self):
        di = _fresh_di()
        iso, warn = di.parse_exact_date("22 июля")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_PARTIAL_DATE_IGNORED)

    def test_range_without_unambiguous_date_ignored(self):
        di = _fresh_di()
        iso, warn = di.parse_exact_date("с 01.01.2026 по 31.12.2026")
        self.assertEqual(iso, "")
        self.assertEqual(warn, di.WARNING_PARTIAL_DATE_IGNORED)

    def test_empty_input_no_warning(self):
        di = _fresh_di()
        self.assertEqual(di.parse_exact_date(""), ("", None))

    def test_unrelated_text_no_warning(self):
        di = _fresh_di()
        self.assertEqual(di.parse_exact_date("не указано"), ("", None))


# ────────────────────────────────────────────────────────────
# §A: document_number / document_date normalization
# ────────────────────────────────────────────────────────────

class TestExtractStructuredFields(unittest.TestCase):
    def test_document_number_extraction_canonical(self):
        """п.5."""
        di = _fresh_di()
        result = di.extract_structured_fields({"document_number": "123/45"}, {})
        self.assertEqual(result.document_number, "123/45")

    def test_document_number_safe_alias_fallback(self):
        di = _fresh_di()
        result = di.extract_structured_fields({}, {"document_number": "123/45"})
        self.assertEqual(result.document_number, "123/45")

    def test_document_number_bare_number_alias_not_used(self):
        """A bare 'number' key must NEVER be treated as document_number —
        too ambiguous (apartment/POA/license/cadastral number)."""
        di = _fresh_di()
        result = di.extract_structured_fields({}, {"number": "42"})
        self.assertEqual(result.document_number, "")

    def test_document_number_conflict_stays_empty(self):
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"document_number": "111", "номер документа": "222"},
        )
        self.assertEqual(result.document_number, "")
        self.assertIn(di.WARNING_DOCUMENT_NUMBER_CONFLICT, result.warnings)

    def test_document_date_alias_date_signed(self):
        """п.2."""
        di = _fresh_di()
        result = di.extract_structured_fields({}, {"date_signed": "22.07.2026"})
        self.assertEqual(result.document_date, "2026-07-22")

    def test_document_date_conflict_stays_empty(self):
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"date_signed": "22.07.2026", "document_date": "23.07.2026"},
        )
        self.assertEqual(result.document_date, "")
        self.assertIn(di.WARNING_DOCUMENT_DATE_CONFLICT, result.warnings)

    def test_document_date_same_value_no_conflict(self):
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"date_signed": "22.07.2026", "document_date": "22.07.2026"},
        )
        self.assertEqual(result.document_date, "2026-07-22")

    def test_document_date_partial_alias_not_used(self):
        di = _fresh_di()
        result = di.extract_structured_fields({}, {"date_signed": "февраль 2026"})
        self.assertEqual(result.document_date, "")
        self.assertIn(di.WARNING_PARTIAL_DATE_IGNORED, result.warnings)

    # ── §B: issued_by safety ──

    def test_issued_by_safe_extraction(self):
        """п.6."""
        di = _fresh_di()
        result = di.extract_structured_fields({"issued_by": "Нотариус Ким Д.В."}, {})
        self.assertEqual(result.issued_by, "Нотариус Ким Д.В.")

    def test_developer_not_auto_used_as_issued_by(self):
        """п.7: real production example — DREG-005's 'developer' field
        must never leak into issued_by."""
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"developer": "ТОО «Forum Group KZ»"},
        )
        self.assertEqual(result.issued_by, "")
        self.assertIn(di.WARNING_ISSUER_NOT_EXPLICIT, result.warnings)

    def test_contractor_not_auto_used_as_issued_by(self):
        """п.8: real production example — DREG-004's 'contractor' field."""
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"contractor": "ТОО «Forum Group KZ»"},
        )
        self.assertEqual(result.issued_by, "")
        self.assertIn(di.WARNING_ISSUER_NOT_EXPLICIT, result.warnings)

    def test_owner_and_representative_not_auto_used_as_issued_by(self):
        di = _fresh_di()
        result = di.extract_structured_fields(
            {}, {"owner_name": "Адилов Жандос", "representative_name": "Дуйсенбаев Диар"},
        )
        self.assertEqual(result.issued_by, "")

    def test_issued_by_empty_when_model_uncertain(self):
        di = _fresh_di()
        result = di.extract_structured_fields({"issued_by": ""}, {"developer": "X"})
        self.assertEqual(result.issued_by, "")
        self.assertIn(di.WARNING_ISSUER_NOT_EXPLICIT, result.warnings)

    # ── valid_from / valid_until ──

    def test_valid_from_and_valid_until(self):
        """п.9."""
        di = _fresh_di()
        result = di.extract_structured_fields(
            {"valid_from": "2026-01-01", "valid_until": "2027-01-01"}, {},
        )
        self.assertEqual(result.valid_from, "2026-01-01")
        self.assertEqual(result.valid_until, "2027-01-01")

    def test_valid_until_partial_stays_empty(self):
        di = _fresh_di()
        result = di.extract_structured_fields({"valid_until": "2027"}, {})
        self.assertEqual(result.valid_until, "")

    # ── §C: has_expiration / requires_action ──

    def test_has_expiration_true(self):
        """п.10."""
        di = _fresh_di()
        result = di.extract_structured_fields({"has_expiration": True}, {})
        self.assertIs(result.has_expiration, True)

    def test_has_expiration_false(self):
        """п.11."""
        di = _fresh_di()
        result = di.extract_structured_fields({"has_expiration": False}, {})
        self.assertIs(result.has_expiration, False)

    def test_has_expiration_unknown(self):
        """п.12: missing, null, or garbage type -> None, never guessed."""
        di = _fresh_di()
        self.assertIsNone(di.extract_structured_fields({}, {}).has_expiration)
        self.assertIsNone(di.extract_structured_fields({"has_expiration": None}, {}).has_expiration)
        self.assertIsNone(di.extract_structured_fields({"has_expiration": "yes"}, {}).has_expiration)

    def test_requires_action_true(self):
        """п.17."""
        di = _fresh_di()
        result = di.extract_structured_fields({"requires_action": True}, {})
        self.assertIs(result.requires_action, True)

    def test_requires_action_false(self):
        """п.18."""
        di = _fresh_di()
        result = di.extract_structured_fields({"requires_action": False}, {})
        self.assertIs(result.requires_action, False)

    def test_requires_action_unknown(self):
        """п.19."""
        di = _fresh_di()
        self.assertIsNone(di.extract_structured_fields({}, {}).requires_action)
        self.assertIsNone(di.extract_structured_fields({"requires_action": "да"}, {}).requires_action)

    # ── §D: direction ──

    def test_direction_incoming(self):
        """п.13."""
        di = _fresh_di()
        self.assertEqual(di.extract_structured_fields({"direction": "incoming"}, {}).direction, "incoming")

    def test_direction_outgoing(self):
        """п.14."""
        di = _fresh_di()
        self.assertEqual(di.extract_structured_fields({"direction": "outgoing"}, {}).direction, "outgoing")

    def test_direction_internal(self):
        """п.15."""
        di = _fresh_di()
        self.assertEqual(di.extract_structured_fields({"direction": "internal"}, {}).direction, "internal")

    def test_direction_unknown_fallback(self):
        """п.16: missing, garbage, or unrecognized value -> safe fallback."""
        di = _fresh_di()
        self.assertEqual(di.extract_structured_fields({}, {}).direction, "unknown")
        self.assertEqual(di.extract_structured_fields({"direction": "sideways"}, {}).direction, "unknown")
        self.assertEqual(di.extract_structured_fields({"direction": 123}, {}).direction, "unknown")

    # ── Never raises ──

    def test_never_raises_on_malformed_input(self):
        di = _fresh_di()
        result = di.extract_structured_fields(None, None)
        self.assertEqual(result.document_number, "")
        result2 = di.extract_structured_fields("not a dict", ["not", "a", "dict"])
        self.assertEqual(result2.direction, "unknown")


# ────────────────────────────────────────────────────────────
# §C: boolean cell contract
# ────────────────────────────────────────────────────────────

class TestBoolCellContract(unittest.TestCase):
    def test_bool_to_cell(self):
        di = _fresh_di()
        self.assertEqual(di.bool_to_cell(True), "true")
        self.assertEqual(di.bool_to_cell(False), "false")
        self.assertEqual(di.bool_to_cell(None), "")

    def test_cell_to_bool(self):
        di = _fresh_di()
        self.assertIs(di.cell_to_bool("true"), True)
        self.assertIs(di.cell_to_bool("false"), False)
        self.assertIsNone(di.cell_to_bool(""))

    def test_cell_to_bool_rejects_other_representations(self):
        """Never 'True'/'yes'/'да'/'unknown' as text — anything other
        than the exact literal reads back as None."""
        di = _fresh_di()
        for garbage in ("True", "False", "yes", "no", "да", "нет", "unknown", "1", "0"):
            self.assertIsNone(di.cell_to_bool(garbage), garbage)


# ────────────────────────────────────────────────────────────
# Prompt version / prompt content
# ────────────────────────────────────────────────────────────

class TestPromptV2(unittest.TestCase):
    def test_prompt_version_bumped(self):
        di = _fresh_di()
        self.assertEqual(di.PROMPT_VERSION, "v2")

    def test_prompt_contains_structured_fields_block(self):
        di = _fresh_di()
        prompt = di.build_analysis_prompt()
        self.assertIn("structured_fields", prompt)
        self.assertIn("document_number", prompt)
        self.assertIn("issued_by", prompt)
        self.assertIn("direction", prompt)

    def test_parse_and_validate_backward_compatible_missing_block(self):
        """A v1-shaped response (no structured_fields at all) must still
        parse successfully, with structured_fields defaulting to {}."""
        di = _fresh_di()
        raw = json.dumps({
            "document_type": "contract", "summary": "s", "language": "ru",
            "page_count": 1, "keywords": [], "extracted_fields": {}, "text_preview": "",
        })
        parsed = di.parse_and_validate_ai_result(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["structured_fields"], {})

    def test_parse_and_validate_wrong_type_structured_fields_defaults_empty(self):
        di = _fresh_di()
        raw = json.dumps({
            "document_type": "contract", "summary": "s", "language": "ru",
            "page_count": 1, "keywords": [], "extracted_fields": {}, "text_preview": "",
            "structured_fields": "not a dict",
        })
        parsed = di.parse_and_validate_ai_result(raw)
        self.assertEqual(parsed["structured_fields"], {})


# ────────────────────────────────────────────────────────────
# End-to-end analyze_document() integration + backward compatibility
# ────────────────────────────────────────────────────────────

GOOD_AI_JSON_WITH_STRUCTURED = json.dumps({
    "document_type": "acceptance_act",
    "summary": "Акт приёма-передачи.",
    "language": "ru",
    "page_count": 2,
    "keywords": ["акт"],
    "extracted_fields": {"contractor": "ТОО «Forum Group KZ»"},
    "text_preview": "Акт приёма-передачи №...",
    "structured_fields": {
        "document_number": "18/02-10",
        "document_date": "22.07.2026",
        "issued_by": "",
        "valid_from": "",
        "valid_until": "",
        "has_expiration": False,
        "direction": "internal",
        "requires_action": True,
    },
})


class TestAnalyzeDocumentIntegration(unittest.TestCase):
    def _run(self, content_sheet=None, registries=None, ai_response_text=None):
        di = _fresh_di()
        content_sheet = content_sheet if content_sheet is not None else _make_sheet(CONTENT_HEADERS)
        registries = registries if registries is not None else _Registries()

        download_mock = MagicMock(return_value=b"%PDF-1.4 fake pdf bytes")
        anthropic_client = MagicMock()
        text = ai_response_text if ai_response_text is not None else GOOD_AI_JSON_WITH_STRUCTURED
        anthropic_client.messages.create.return_value = _mock_anthropic_response(text)

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
            stack.enter_context(patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False))
            mock_anthropic_module = MagicMock()
            mock_anthropic_module.Anthropic.return_value = anthropic_client
            stack.enter_context(patch.dict("sys.modules", {"anthropic": mock_anthropic_module}))
            result = di.analyze_document(document_id="DREG-001", drive_file_id="FILE1")

        return di, content_sheet, result

    def test_structured_fields_written_in_main_finalize_call(self):
        di, sheet, result = self._run()
        self.assertEqual(result["action"], "completed")
        # main completion write + separate best-effort duplicate write = 2
        self.assertEqual(len(sheet._batch_calls), 2)
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        row = sheet._data[1]
        self.assertEqual(row[idx["Document Number"]], "18/02-10")
        self.assertEqual(row[idx["Document Date"]], "2026-07-22")
        self.assertEqual(row[idx["Issued By"]], "")
        self.assertEqual(row[idx["Has Expiration"]], "false")
        self.assertEqual(row[idx["Direction"]], "internal")
        self.assertEqual(row[idx["Requires Action"]], "true")
        self.assertEqual(row[idx["Prompt Version"]], "v2")

    def test_missing_structured_fields_block_does_not_fail_analysis(self):
        """п.1 of §13: AI omitted structured_fields entirely (v1-shaped
        response) -> analysis still completes, fields just stay empty."""
        di, sheet, result = self._run(ai_response_text=json.dumps({
            "document_type": "contract", "summary": "s", "language": "ru",
            "page_count": 1, "keywords": [], "extracted_fields": {}, "text_preview": "",
        }))
        self.assertEqual(result["action"], "completed")
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        row = sheet._data[1]
        self.assertEqual(row[idx["Document Number"]], "")
        self.assertEqual(row[idx["Direction"]], "unknown")

    def test_schema_not_migrated_finalizes_as_failed_not_crash(self):
        """п.11 of §13: production Sheet still at the pre-16B.2 (23-col)
        shape. update_business_row raises ValueError for the whole main
        write (per §G, structured fields share that call) -> caught by
        analyze_document's outer except, row finalized as failed, never
        an unhandled crash and never silently 'completed'."""
        old_headers = CONTENT_HEADERS[:23]  # pre-16B.2 shape
        sheet = _make_sheet(old_headers)
        di, sheet, result = self._run(content_sheet=sheet)
        self.assertEqual(result["action"], "failed")
        self.assertFalse(result["ok"])
        idx = {h: i for i, h in enumerate(old_headers)}
        row = sheet._data[1]
        self.assertEqual(row[idx["Content Status"]], "failed")

    def test_old_row_backward_compatible_via_document_query(self):
        """п.20: a pre-16B.2 row (no structured columns at all, dict.get
        default) reads back through document_query with safe defaults —
        never raises, never shows garbage."""
        dq = _fresh_dq()
        old_headers = CONTENT_HEADERS[:23]
        content_row = ["DREG-001", "FILE1", "completed", "contract", "", "0.00",
                        "s", "{}", "", "ru", "1", "[]", "claude-sonnet-4-5", "v1",
                        "hash", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC",
                        "", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC",
                        "NEW_DOCUMENT", "", "2026-01-01 00:00:00 UTC"]
        registries = _Registries(content_rows=[dict(zip(old_headers, content_row))])
        with patch("business_core.sheets.find_row_by_id") as mock_find:
            def _find(sheet_key, doc_id):
                if sheet_key == "document_registry":
                    return (2, _doc_registry_row())
                if sheet_key == "document_content":
                    return (2, dict(zip(old_headers, content_row)))
                return None
            mock_find.side_effect = _find
            result = dq.get_document_analysis("DREG-001")
        self.assertEqual(result.document_number, "")
        self.assertEqual(result.document_date, "")
        self.assertIsNone(result.has_expiration)
        self.assertIsNone(result.requires_action)
        self.assertEqual(result.direction, "unknown")

    def test_reanalysis_updates_ai_derived_fields(self):
        """п.21: force reanalysis with a different AI result fully
        replaces the previous structured fields (no human-confirmation
        state exists in this phase, per §7)."""
        old_row = ["DREG-001", "FILE1", "completed"] + [""] * (len(CONTENT_HEADERS) - 3)
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        old_row[idx["Document Number"]] = "OLD-NUMBER"
        old_row[idx["Direction"]] = "incoming"
        sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[old_row])

        new_response = json.dumps({
            "document_type": "contract", "summary": "s2", "language": "ru",
            "page_count": 1, "keywords": [], "extracted_fields": {}, "text_preview": "",
            "structured_fields": {
                "document_number": "NEW-NUMBER", "direction": "outgoing",
                "document_date": "", "issued_by": "", "valid_from": "", "valid_until": "",
                "has_expiration": None, "requires_action": None,
            },
        })
        di = _fresh_di()
        registries = _Registries()
        registry_row_values = [registries.doc_row.get(h, "") for h in DOC_REGISTRY_HEADERS]
        registry_sheet = _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[registry_row_values])

        anthropic_client = MagicMock()
        anthropic_client.messages.create.return_value = _mock_anthropic_response(new_response)
        download_mock = MagicMock(return_value=b"%PDF-1.4 fake pdf bytes")

        def _get_business_sheet_side_effect(key):
            if key == "document_content":
                return sheet
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
            stack.enter_context(patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=False))
            mock_anthropic_module = MagicMock()
            mock_anthropic_module.Anthropic.return_value = anthropic_client
            stack.enter_context(patch.dict("sys.modules", {"anthropic": mock_anthropic_module}))
            result = di.analyze_document(document_id="DREG-001", drive_file_id="FILE1", force=True)

        self.assertEqual(result["action"], "completed")
        row = sheet._data[1]
        self.assertEqual(row[idx["Document Number"]], "NEW-NUMBER")
        self.assertEqual(row[idx["Direction"]], "outgoing")


# ────────────────────────────────────────────────────────────
# §9: Architecture invariants — no side effects outside DOCUMENT_CONTENT
# ────────────────────────────────────────────────────────────

class TestArchitectureInvariants(unittest.TestCase):
    def test_extract_structured_fields_never_writes(self):
        """п.22-25: pure function — no Sheets import at all, cannot
        write to DOCUMENT_REGISTRY, Template ID, relations, or the
        Completion Gate."""
        import inspect
        di = _fresh_di()
        source = inspect.getsource(di.extract_structured_fields)
        source += inspect.getsource(di._extract_document_number)
        source += inspect.getsource(di._extract_date_field)
        source += inspect.getsource(di._extract_issued_by)
        source += inspect.getsource(di._extract_direction)
        source += inspect.getsource(di._extract_optional_bool)
        self.assertNotIn("update_business_row", source)
        self.assertNotIn("append_business_row", source)
        self.assertNotIn("DOCUMENT_REGISTRY", source)
        self.assertNotIn('"Document Template ID"', source)
        self.assertNotIn('"Status"', source)
        self.assertNotIn("STAGE_ENTITY_RELATIONS", source)
        self.assertNotIn("Completion Gate", source)
        self.assertNotIn("transition_stage_status", source)

    def test_structured_fields_write_scoped_to_document_content_only(self):
        """п.22-24: the ONLY sheet_key ever passed alongside the 8 new
        column names is 'document_content' — verified from
        analyze_document's own source, not just by convention."""
        import inspect
        di = _fresh_di()
        source = inspect.getsource(di.analyze_document)
        # The finalize update_business_row call carrying "Document Number"
        # must target "document_content", never any other sheet_key.
        idx = source.index('"Document Number": structured_fields.document_number')
        preceding = source[:idx]
        last_call_start = preceding.rfind('update_business_row("document_content"')
        # The nearest preceding update_business_row(...) call must itself
        # be the "document_content" one — i.e. no OTHER sheet_key's call
        # opens between this call's start and the structured-fields keys.
        self.assertNotEqual(last_call_start, -1)
        between = source[last_call_start:idx]
        self.assertNotIn('update_business_row("document_registry"', between)
        self.assertEqual(between.count('update_business_row("'), 1)

    def test_duplicate_canonical_algorithm_untouched(self):
        """п.26: find_exact_duplicate's own source is unaffected by
        Phase 16B.2 — still the same cycle-free canonical-selection
        algorithm, no structured-field involvement."""
        import inspect
        di = _fresh_di()
        source = inspect.getsource(di.find_exact_duplicate)
        self.assertNotIn("structured_fields", source)
        self.assertNotIn("StructuredDocumentFields", source)

    def test_analyze_document_does_not_call_document_manager_writes(self):
        """п.22-23: analyze_document() (which now also writes structured
        fields) never imports/calls document_manager's DOCUMENT_REGISTRY
        write helpers or template-id mutation."""
        import inspect
        di = _fresh_di()
        source = inspect.getsource(di.analyze_document)
        self.assertNotIn("document_manager", source)
        self.assertNotIn("transition_stage_status", source)
        self.assertNotIn("STAGE_ENTITY_RELATIONS", source)


# ────────────────────────────────────────────────────────────
# §8/§12: Telegram UX — rendering + sensitive-field non-exposure
# ────────────────────────────────────────────────────────────

class _FakeResult:
    """Minimal stand-in for DocumentAnalysisResult — only the attributes
    _render_document_analysis actually reads."""

    def __init__(self, **kw):
        defaults = dict(
            status="completed", document_id="DREG-001", document_name="Doc",
            file_name="file.pdf", mime_type="application/pdf",
            detected_document_type="acceptance_act", summary="Summary",
            fields={}, fields_valid=True, keywords=(), language="ru",
            page_count="1", suggested_template_id="", template_match_confidence="",
            completed_at="2026-01-01", updated_at="2026-01-01", error="",
            is_quota_error=False, is_transient_read_error=False,
            duplicate_status="", duplicate_of_document_id="",
            duplicate_checked_at="", duplicate_document_name="",
            duplicate_document_status="",
            document_number="", document_date="", issued_by="",
            valid_from="", valid_until="", has_expiration=None,
            direction="unknown", requires_action=None,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)
        # Phase 16B.4: /docanalysis now renders through
        # effective_structured_fields, not the raw fields above —
        # synthesize it (unreviewed/AI-passthrough) from those same raw
        # values so these pre-16B.4 tests keep exercising the same
        # AI-value-display scenarios via the real typed render path.
        from business_core.document_intelligence import bool_to_cell
        from business_core.document_confirmation import build_effective_structured_fields
        content_row = {
            "Document Number": self.document_number, "Document Date": self.document_date,
            "Issued By": self.issued_by, "Valid From": self.valid_from, "Valid Until": self.valid_until,
            "Has Expiration": bool_to_cell(self.has_expiration), "Direction": self.direction,
            "Requires Action": bool_to_cell(self.requires_action),
        }
        self.effective_structured_fields = build_effective_structured_fields(content_row, {})


class TestTelegramStructuredFieldsUX(unittest.TestCase):
    def test_requisites_block_shows_canonical_values(self):
        """п.27."""
        th = _fresh_th()
        result = _FakeResult(
            document_number="18/02-10", document_date="2026-07-22",
            issued_by="Нотариус Ким Д.В.", valid_from="2026-01-01",
            valid_until="2027-01-01", has_expiration=True,
            direction="incoming", requires_action=False,
        )
        text = th._render_document_analysis(result)
        self.assertIn("Реквизиты:", text)
        self.assertIn("Номер документа: 18/02-10", text)
        self.assertIn("Дата документа: 2026-07-22", text)
        self.assertIn("Кем выдан: Нотариус Ким Д.В.", text)
        self.assertIn("Действует с: 2026-01-01", text)
        self.assertIn("Действует до: 2027-01-01", text)
        self.assertIn("Есть срок действия: да", text)
        self.assertIn("Направление: входящий", text)
        self.assertIn("Требует действия: нет", text)

    def test_unknown_direction_and_bool_show_not_determined(self):
        th = _fresh_th()
        result = _FakeResult()
        text = th._render_document_analysis(result)
        self.assertIn("Направление: не определено", text)
        self.assertIn("Есть срок действия: не определено", text)
        self.assertIn("Требует действия: не определено", text)

    def test_empty_fields_shown_with_ai_marker(self):
        """Phase 16B.4: ALL 8 fields are now always shown (unlike the
        pre-16B.4 skip-if-empty behavior) — an empty/unreviewed field
        renders as 'не определено' with the 🤖 AI marker, consistent
        with /reviewdoc."""
        th = _fresh_th()
        result = _FakeResult()
        text = th._render_document_analysis(result)
        self.assertIn("Номер документа: не определено 🤖 AI, не проверено", text)
        self.assertIn("Дата документа: не определено 🤖 AI, не проверено", text)
        self.assertIn("Кем выдан: не определено 🤖 AI, не проверено", text)
        self.assertIn("Действует с: не определено 🤖 AI, не проверено", text)
        self.assertIn("Действует до: не определено 🤖 AI, не проверено", text)

    def test_direction_all_values_render(self):
        th = _fresh_th()
        for canonical, label in (
            ("incoming", "входящий"), ("outgoing", "исходящий"),
            ("internal", "внутренний"), ("unknown", "не определено"),
        ):
            self.assertEqual(th._render_direction(canonical), label)

    def test_sensitive_fields_never_auto_shown_in_requisites(self):
        """п.28: structured fields never contain ИИН/БИН/паспорт/счета/
        телефон/email/доверенность/лицензия by construction — they are
        exactly 8 canonical fields, never a passthrough of arbitrary
        extracted_fields. Verify the raw sensitive values from the real
        production DREG-004 payload do NOT leak into the requisites
        block even when present in `fields` (the separate raw-fields
        renderer is untouched, out of scope, but the requisites block
        itself must never reference `result.fields`)."""
        th = _fresh_th()
        result = _FakeResult(
            document_number="18/02-10",
            fields={
                "owner_iin": "781015300461",
                "contractor_bin": "240340030219",
                "representative_iin": "860714351651",
            },
        )
        text = th._render_document_analysis(result)
        # The requisites block itself only ever prints the 8 canonical
        # attributes — this asserts the source never wires `fields`
        # into that block (a stronger, structural guarantee than just
        # checking today's IIN values aren't in the string).
        import inspect
        source = inspect.getsource(th._render_document_analysis)
        requisites_start = source.index("Реквизиты")
        requisites_section = source[requisites_start:source.index("Дубликат", requisites_start)
                                     if "Дубликат" in source[requisites_start:] else len(source)]
        self.assertNotIn("result.fields", requisites_section)

    def test_document_number_is_always_canonical_never_arbitrary(self):
        """Document Number shown is result.effective_structured_fields
        (canonical structured field, Phase 16B.4) — the requisites
        block never falls back to an arbitrary extracted_fields number."""
        import inspect
        th = _fresh_th()
        source = inspect.getsource(th._render_document_analysis)
        requisites_start = source.index("Реквизиты")
        requisites_section = source[requisites_start:requisites_start + 800]
        self.assertIn("result.effective_structured_fields", requisites_section)


if __name__ == "__main__":
    unittest.main()
