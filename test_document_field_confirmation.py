"""
Phase 16B.3: Human Confirmation of Structured Document Fields.

Covers business_core/document_confirmation.py: field whitelist,
per-field value validation, document-level optimistic concurrency
(expected_version), aggregate review-status computation, effective-
value + conflict computation (read-time, never persisted), the
append-only DOCUMENT_FIELD_REVIEWS audit trail, and the architecture
invariants (no DOCUMENT_REGISTRY/Template ID/Status/relations/
Completion Gate/duplicate-algorithm influence).

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

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
    "Structured Review Status", "Confirmed Fields JSON",
    "Structured Review Version", "Structured Review Updated At",
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

REVIEW_HEADERS = [
    "Review ID", "Mutation ID", "Document ID", "Business ID", "Field Name",
    "AI Value", "Confirmed Value", "Decision", "Actor", "Reviewed At",
    "Review Version", "Source Analysis Completed At",
]


def _fresh_dc():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_confirmation as dc
    return dc


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


def _content_row(**overrides):
    values = ["DREG-001", "FILE1", "completed", "acceptance_act", "", "0.00",
              "s", "{}", "", "ru", "1", "[]", "claude-sonnet-4-5", "v2",
              "hash", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC", "",
              "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC",
              "NEW_DOCUMENT", "", "2026-01-01 00:00:00 UTC",
              "", "2026-07-22", "", "", "", "", "internal", "",
              "", "", "", ""]
    row = dict(zip(CONTENT_HEADERS, values))
    row.update(overrides)
    return [row.get(h, "") for h in CONTENT_HEADERS]


def _registry_row(**overrides):
    values = ["DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "", "",
              "", "Test Doc", "uploaded", "FILE1",
              "https://drive.google.com/file/d/FILE1/view", "file.pdf", "application/pdf",
              "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
              "2026-01-01 00:00:00 UTC"]
    row = dict(zip(DOC_REGISTRY_HEADERS, values))
    row.update(overrides)
    return [row.get(h, "") for h in DOC_REGISTRY_HEADERS]


class _Sheets:
    def __init__(self, content_row=None, registry_row=None, review_rows=None, reviews_exists=True):
        self.content = _make_sheet(CONTENT_HEADERS, existing_rows=[content_row or _content_row()])
        self.registry = _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[registry_row or _registry_row()])
        self.reviews = _make_sheet(REVIEW_HEADERS, existing_rows=review_rows or [])
        self.reviews_exists = reviews_exists

    def get_business_sheet(self, key):
        return {"document_content": self.content, "document_registry": self.registry,
                "document_field_reviews": self.reviews}[key]

    def business_sheet_exists(self, key):
        if key == "document_field_reviews":
            return self.reviews_exists
        return True


def _patched(sheets: "_Sheets"):
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("business_core.sheets.get_business_sheet", side_effect=sheets.get_business_sheet))
    stack.enter_context(patch("business_core.sheets.business_sheet_exists", side_effect=sheets.business_sheet_exists))
    return stack


class TestValidateFieldValue(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()

    def test_document_date_valid_iso(self):
        value, error = self.dc._validate_field_value("document_date", "2026-07-22")
        self.assertIsNone(error)
        self.assertEqual(value, "2026-07-22")

    def test_document_date_invalid_rejected(self):
        """п.9."""
        value, error = self.dc._validate_field_value("document_date", "февраль 2026")
        self.assertIsNotNone(error)

    def test_direction_invalid_rejected(self):
        """п.10."""
        value, error = self.dc._validate_field_value("direction", "sideways")
        self.assertIsNotNone(error)

    def test_direction_valid(self):
        value, error = self.dc._validate_field_value("direction", "OUTGOING")
        self.assertIsNone(error)
        self.assertEqual(value, "outgoing")

    def test_has_expiration_invalid_rejected(self):
        """п.11."""
        value, error = self.dc._validate_field_value("has_expiration", "maybe")
        self.assertIsNotNone(error)

    def test_has_expiration_true_false(self):
        v1, e1 = self.dc._validate_field_value("has_expiration", "true")
        v2, e2 = self.dc._validate_field_value("has_expiration", "false")
        self.assertEqual((v1, e1), ("true", None))
        self.assertEqual((v2, e2), ("false", None))

    def test_value_trimmed(self):
        """п.12."""
        value, error = self.dc._validate_field_value("issued_by", "  Нотариус Ким  ")
        self.assertIsNone(error)
        self.assertEqual(value, "Нотариус Ким")

    def test_control_characters_rejected(self):
        """п.13."""
        value, error = self.dc._validate_field_value("issued_by", "Нотариус\x00Ким")
        self.assertIsNotNone(error)

    def test_formula_injection_rejected(self):
        """п.20 (command injection в value) — Sheets formula-trigger prefix."""
        for bad in ("=SUM(A1)", "+1+1", "-cmd", "@import"):
            value, error = self.dc._validate_field_value("document_number", bad)
            self.assertIsNotNone(error, bad)

    def test_empty_value_rejected(self):
        value, error = self.dc._validate_field_value("document_number", "")
        self.assertIsNotNone(error)


class TestAggregateStatus(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()

    def test_unreviewed_when_empty(self):
        self.assertEqual(self.dc.compute_aggregate_status({}), self.dc.STATUS_UNREVIEWED)

    def test_unknown_ai_value_never_auto_reviewed(self):
        """Aggregate status ignores fields entirely absent from
        Confirmed Fields JSON — an unknown AI value is never counted."""
        self.assertEqual(self.dc.compute_aggregate_status({"document_date": None}), self.dc.STATUS_UNREVIEWED)

    def test_partially_confirmed(self):
        confirmed = {"document_date": {"status": "confirmed"}}
        self.assertEqual(self.dc.compute_aggregate_status(confirmed), self.dc.STATUS_PARTIALLY_CONFIRMED)

    def test_confirmed_when_all_eight_reviewed_and_none_rejected(self):
        confirmed = {f: {"status": "confirmed"} for f in self.dc.ALLOWED_STRUCTURED_FIELDS}
        self.assertEqual(self.dc.compute_aggregate_status(confirmed), self.dc.STATUS_CONFIRMED)

    def test_rejected_if_any_field_rejected(self):
        confirmed = {f: {"status": "confirmed"} for f in self.dc.ALLOWED_STRUCTURED_FIELDS}
        confirmed["direction"] = {"status": "rejected"}
        self.assertEqual(self.dc.compute_aggregate_status(confirmed), self.dc.STATUS_REJECTED)


class TestEffectiveFields(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()

    def test_effective_value_uses_confirmed(self):
        """п.25."""
        row = {"Document Date": "2026-07-23"}
        confirmed = {"document_date": {"value": "2026-07-22", "status": "confirmed"}}
        eff = self.dc.compute_effective_fields(row, confirmed)
        self.assertEqual(eff["document_date"]["effective_value"], "2026-07-22")
        self.assertEqual(eff["document_date"]["source"], "confirmed")

    def test_effective_value_falls_back_to_ai(self):
        """п.26."""
        row = {"Direction": "internal"}
        eff = self.dc.compute_effective_fields(row, {})
        self.assertEqual(eff["direction"]["effective_value"], "internal")
        self.assertEqual(eff["direction"]["source"], "ai")

    def test_reanalysis_conflict_detected(self):
        """п.24: confirmed value differs from CURRENT AI value ->
        conflict=true, effective value stays the confirmed one."""
        row = {"Document Date": "2026-07-23"}  # new AI value after reanalysis
        confirmed = {"document_date": {"value": "2026-07-22", "status": "confirmed"}}
        eff = self.dc.compute_effective_fields(row, confirmed)
        self.assertTrue(eff["document_date"]["conflict"])
        self.assertEqual(eff["document_date"]["effective_value"], "2026-07-22")

    def test_reanalysis_preserves_confirmed_value_no_conflict_when_same(self):
        """п.23."""
        row = {"Document Date": "2026-07-22"}
        confirmed = {"document_date": {"value": "2026-07-22", "status": "confirmed"}}
        eff = self.dc.compute_effective_fields(row, confirmed)
        self.assertFalse(eff["document_date"]["conflict"])

    def test_rejected_field_has_no_effective_value(self):
        row = {"Direction": "internal"}
        confirmed = {"direction": {"status": "rejected"}}
        eff = self.dc.compute_effective_fields(row, confirmed)
        self.assertEqual(eff["direction"]["effective_value"], "")
        self.assertEqual(eff["direction"]["source"], "none")


class TestConfirmField(unittest.TestCase):
    def test_confirm_document_date(self):
        """п.2."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "document_date", "2026-07-22", "didar", 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["review_version"], 1)
        self.assertIn("document_date", result["confirmed_fields"])
        self.assertEqual(result["confirmed_fields"]["document_date"]["status"], "confirmed")

    def test_confirm_direction(self):
        """п.3."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed_fields"]["direction"]["value"], "internal")

    def test_confirm_boolean_true(self):
        """п.4."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "has_expiration", "true", "didar", 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed_fields"]["has_expiration"]["value"], "true")

    def test_confirm_boolean_false(self):
        """п.5."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "requires_action", "false", "didar", 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed_fields"]["requires_action"]["value"], "false")

    def test_invalid_field_rejected(self):
        """п.7: arbitrary field name whitelist rejection."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "owner_iin", "781015300461", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "FIELD_NOT_ALLOWED")

    def test_arbitrary_extracted_field_rejected(self):
        """п.8."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "total_cost", "1000000", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "FIELD_NOT_ALLOWED")

    def test_invalid_date_rejected(self):
        """п.9."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "document_date", "февраль 2026", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_VALUE")

    def test_invalid_direction_rejected(self):
        """п.10."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "sideways", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_VALUE")

    def test_document_not_found(self):
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-999", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DOCUMENT_NOT_FOUND")

    def test_stale_version_conflict(self):
        """п.19: stale expected_version -> CONFLICT, no writes."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "VERSION_CONFLICT")
        self.assertEqual(result["review_version"], 0)
        self.assertEqual(len(sheets.content._batch_calls), 0)
        self.assertEqual(len(sheets.reviews._appended), 0)

    def test_optimistic_version_success(self):
        """п.18."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
            self.assertTrue(r1["ok"])
            r2 = dc.confirm_field("DREG-001", "document_date", "2026-07-22", "didar", r1["review_version"])
            self.assertTrue(r2["ok"])
            self.assertEqual(r2["review_version"], 2)

    def test_actor_recorded(self):
        """п.20."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        idx = {h: i for i, h in enumerate(REVIEW_HEADERS)}
        audit_row = sheets.reviews._appended[0]
        self.assertEqual(audit_row[idx["Actor"]], "didar")

    def test_timestamp_utc(self):
        """п.21."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        entry = result["confirmed_fields"]["direction"]
        self.assertTrue(entry["confirmed_at"].endswith("UTC"))

    def test_review_version_increment(self):
        """п.22."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
            r2 = dc.confirm_field("DREG-001", "document_date", "2026-07-22", "didar", 1)
        self.assertEqual(r1["review_version"], 1)
        self.assertEqual(r2["review_version"], 2)

    def test_no_n_writes_per_field(self):
        """п.43: exactly one update_business_row batch + one audit
        append per mutation — no per-field update_cell."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertEqual(len(sheets.content._batch_calls), 1)
        self.assertEqual(len(sheets.reviews._appended), 1)


class TestRejectAndClearField(unittest.TestCase):
    def test_reject_field(self):
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.reject_field("DREG-001", "direction", "didar", 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed_fields"]["direction"]["status"], "rejected")

    def test_reject_invalid_field_rejected(self):
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            result = dc.reject_field("DREG-001", "owner_iin", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "FIELD_NOT_ALLOWED")

    def test_clear_confirmation(self):
        """п.6."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
            r2 = dc.clear_field("DREG-001", "direction", "didar", r1["review_version"])
        self.assertTrue(r2["ok"])
        self.assertNotIn("direction", r2["confirmed_fields"])
        self.assertEqual(r2["review_status"], "unreviewed")

    def test_clear_does_not_remove_ai_value(self):
        """clear only removes the human confirmation, never the
        AI-derived DOCUMENT_CONTENT column itself (that column is never
        touched by this module at all)."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "outgoing", "didar", 0)
            dc.clear_field("DREG-001", "direction", "didar", r1["review_version"])
        idx = {h: i for i, h in enumerate(CONTENT_HEADERS)}
        self.assertEqual(sheets.content._data[1][idx["Direction"]], "internal")  # untouched original AI value


class TestGetReviewState(unittest.TestCase):
    def test_review_unreviewed_document(self):
        """п.1."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            state = dc.get_review_state("DREG-001")
        self.assertTrue(state["found"])
        self.assertEqual(state["review_status"], "unreviewed")
        self.assertEqual(state["review_version"], 0)

    def test_old_row_backward_compatible(self):
        """п.42: a pre-16B.3 row (empty review columns, dict.get
        default) reads back with safe defaults."""
        dc = _fresh_dc()
        old_row = _content_row()
        sheets = _Sheets(content_row=old_row)
        with _patched(sheets):
            state = dc.get_review_state("DREG-001")
        self.assertEqual(state["review_status"], "unreviewed")
        self.assertEqual(state["review_version"], 0)
        self.assertEqual(state["confirmed_fields"], {})


class TestArchitectureInvariants(unittest.TestCase):
    def test_no_document_registry_writes(self):
        """п.28/29/30/31/32/33: source inspection — this module never
        writes DOCUMENT_REGISTRY/Template ID/Status/relations/Stage/
        Completion Gate."""
        import inspect
        dc = _fresh_dc()
        source = inspect.getsource(dc)
        self.assertNotIn('update_business_row("document_registry"', source)
        self.assertNotIn('append_business_row("document_registry"', source)
        self.assertNotIn("stage_entity_relations", source)
        self.assertNotIn("transition_stage_status", source)
        self.assertNotIn("_evaluate_document_completion_gate", source)

    def test_duplicate_algorithm_not_referenced(self):
        """п.27: duplicate canonical-selection algorithm untouched by
        this module."""
        import inspect
        dc = _fresh_dc()
        source = inspect.getsource(dc)
        self.assertNotIn("find_exact_duplicate", source)
        self.assertNotIn("ExactDuplicateResult", source)

    def test_confirmation_not_copied_between_documents(self):
        """п.27: DREG-004/DREG-005 (exact duplicates) have fully
        independent review state — confirming a field on one document
        never touches another Document ID's row."""
        dc = _fresh_dc()
        content_sheet = _make_sheet(CONTENT_HEADERS, existing_rows=[
            _content_row(**{"Document ID": "DREG-004"}),
            _content_row(**{"Document ID": "DREG-005"}),
        ])
        registry_sheet = _make_sheet(DOC_REGISTRY_HEADERS, existing_rows=[
            _registry_row(**{"Document ID": "DREG-004"}),
            _registry_row(**{"Document ID": "DREG-005"}),
        ])
        reviews_sheet = _make_sheet(REVIEW_HEADERS)

        def _get(key):
            return {"document_content": content_sheet, "document_registry": registry_sheet,
                    "document_field_reviews": reviews_sheet}[key]

        with patch("business_core.sheets.get_business_sheet", side_effect=_get):
            dc.confirm_field("DREG-004", "direction", "internal", "didar", 0)
            state_005 = dc.get_review_state("DREG-005")
        self.assertEqual(state_005["review_status"], "unreviewed")
        self.assertEqual(state_005["confirmed_fields"], {})


class TestAuditAtomicity(unittest.TestCase):
    def test_audit_append_failure_leaves_cache_untouched(self):
        """п.1 of the new list: audit append fails -> cache (DOCUMENT_
        CONTENT) is never even attempted — zero batch calls."""
        dc = _fresh_dc()
        sheets = _Sheets()
        sheets.reviews.update.side_effect = Exception("sheets down")

        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "AUDIT_APPEND_FAILED")
        self.assertEqual(len(sheets.content._batch_calls), 0)
        self.assertEqual(len(sheets.reviews._appended), 0)

    def test_audit_succeeds_cache_write_fails_returns_cache_sync_failed(self):
        """п.2: audit append succeeds, cache write fails ->
        CACHE_SYNC_FAILED — audit remains the source of truth."""
        dc = _fresh_dc()
        sheets = _Sheets()
        sheets.content.batch_update.side_effect = Exception("cache write down")

        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CACHE_SYNC_FAILED")
        # The audit row DID get written (source of truth intact).
        self.assertEqual(len(sheets.reviews._appended), 1)

    def test_rebuild_cache_from_audit_after_cache_failure(self):
        """п.3: after a CACHE_SYNC_FAILED, the audit trail alone is
        enough to rebuild the exact same cache state."""
        dc = _fresh_dc()
        sheets = _Sheets()
        sheets.content.batch_update.side_effect = Exception("cache write down")
        with _patched(sheets):
            dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)

        idx = {h: i for i, h in enumerate(REVIEW_HEADERS)}
        review_row = sheets.reviews._appended[0]
        review_dict = {h: review_row[i] for h, i in idx.items()}
        rebuilt = dc.rebuild_confirmed_fields_from_reviews([review_dict])
        self.assertEqual(rebuilt["confirmed_fields"]["direction"]["value"], "internal")
        self.assertEqual(rebuilt["review_version"], 1)

    def test_retry_same_mutation_id_does_not_duplicate_event(self):
        """п.4: a byte-identical retry (same command resent) is
        recognized via Mutation ID and never appends a second audit
        row — even though the version has already moved on."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
            self.assertTrue(r1["ok"])
            self.assertEqual(len(sheets.reviews._appended), 1)

            # Exact same call again (document_id, field, decision, value,
            # expected_version=0 — the ORIGINAL value, even though the
            # real version is now 1).
            r2 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["code"], "OK_IDEMPOTENT_REPLAY")
        self.assertEqual(len(sheets.reviews._appended), 1)  # NOT 2

    def test_duplicate_review_version_detected_by_rebuild(self):
        """п.6: two rows racily claiming the same Review Version for one
        document — rebuild_confirmed_fields_from_reviews() detects and
        flags it (cannot prevent it — no Sheets-side atomic CAS)."""
        dc = _fresh_dc()
        idx = {h: i for i, h in enumerate(REVIEW_HEADERS)}
        row_a = [""] * len(REVIEW_HEADERS)
        row_a[idx["Document ID"]] = "DREG-001"
        row_a[idx["Field Name"]] = "direction"
        row_a[idx["Decision"]] = "confirm"
        row_a[idx["Confirmed Value"]] = "internal"
        row_a[idx["Review Version"]] = "1"
        row_b = list(row_a)
        row_b[idx["Field Name"]] = "document_date"
        row_b[idx["Confirmed Value"]] = "2026-07-22"
        rows = [dict(zip(REVIEW_HEADERS, row_a)), dict(zip(REVIEW_HEADERS, row_b))]
        rebuilt = dc.rebuild_confirmed_fields_from_reviews(rows)
        self.assertEqual(rebuilt["duplicate_versions"], [1])

    def test_audit_event_exists_without_cache_effective_read_via_rebuild(self):
        """п.7: cache never got written (simulating a crash right after
        the audit append) — rebuild from the audit alone reconstructs
        the correct effective state."""
        dc = _fresh_dc()
        idx = {h: i for i, h in enumerate(REVIEW_HEADERS)}
        row = [""] * len(REVIEW_HEADERS)
        row[idx["Document ID"]] = "DREG-001"
        row[idx["Field Name"]] = "direction"
        row[idx["Decision"]] = "confirm"
        row[idx["Confirmed Value"]] = "outgoing"
        row[idx["Review Version"]] = "1"
        rebuilt = dc.rebuild_confirmed_fields_from_reviews([dict(zip(REVIEW_HEADERS, row))])
        self.assertEqual(rebuilt["confirmed_fields"]["direction"]["value"], "outgoing")
        self.assertEqual(rebuilt["review_status"], "partially_confirmed")

    def test_clear_replay_is_idempotent(self):
        """п.9."""
        dc = _fresh_dc()
        sheets = _Sheets()
        with _patched(sheets):
            r1 = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
            r2 = dc.clear_field("DREG-001", "direction", "didar", r1["review_version"])
            self.assertTrue(r2["ok"])
            r3 = dc.clear_field("DREG-001", "direction", "didar", r1["review_version"])
        self.assertTrue(r3["ok"])
        self.assertEqual(r3["code"], "OK_IDEMPOTENT_REPLAY")
        self.assertEqual(len(sheets.reviews._appended), 2)  # confirm + clear, NOT a 3rd

    def test_sheet_absent_rejects_mutation_no_auto_migration(self):
        """п.10: DOCUMENT_FIELD_REVIEWS doesn't exist yet -> mutation
        fails closed, NEVER auto-creates it."""
        dc = _fresh_dc()
        sheets = _Sheets(reviews_exists=False)
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REVIEWS_SHEET_NOT_READY")
        self.assertEqual(len(sheets.reviews._appended), 0)
        self.assertEqual(len(sheets.content._batch_calls), 0)

    def test_incompatible_review_headers_fail_closed(self):
        """п.11: sheet exists but headers don't match canonical ->
        fail closed, never guesses/writes anyway."""
        dc = _fresh_dc()
        sheets = _Sheets(reviews_exists=True)
        sheets.reviews._data[0] = ["Wrong", "Headers"]
        with _patched(sheets):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REVIEWS_SHEET_NOT_READY")

    def test_stale_version_detected_at_recheck_before_write(self):
        """п.15: expected_version is re-checked immediately before the
        write, not only at the very start — a version change occurring
        in between is still caught."""
        dc = _fresh_dc()
        sheets = _Sheets()

        import business_core.sheets as bs
        original_find = bs.find_row_by_id
        call_count = {"n": 0}

        def _find_with_race(sheet_key, doc_id):
            call_count["n"] += 1
            result = original_find(sheet_key, doc_id)
            # Simulate a concurrent mutation landing between the first
            # version check and the pre-write recheck: bump the cached
            # version out from under this call, on the SECOND
            # "document_content" read only.
            if sheet_key == "document_content" and call_count["n"] == 2:
                row_num, row = result
                row = dict(row)
                row["Structured Review Version"] = "7"
                return (row_num, row)
            return result

        with _patched(sheets), patch("business_core.sheets.find_row_by_id", side_effect=_find_with_race):
            result = dc.confirm_field("DREG-001", "direction", "internal", "didar", 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "VERSION_CONFLICT")
        self.assertEqual(result["review_version"], 7)


if __name__ == "__main__":
    unittest.main()
