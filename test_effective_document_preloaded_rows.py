"""
Phase 16C.1B2: Preloaded Document Registry for Effective Records.

Covers: load_effective_document_records()'s new optional
registry_rows/content_rows parameters — None-vs-empty semantics,
input ownership (never mutated/retained), read-count elimination when
preloaded, and full equivalence with the existing Sheets-read path for
every downstream signal (duplicates, malformed cache, conflict
tri-state, effective values). Also re-confirms /finddocs and
/docreport's existing call budgets are unaffected when neither
argument is passed (the default, unmodified path).

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import business_core.document_search as ds
import business_core.document_report as dr


def _registry_row(document_id, business_id="BIZ-001", name="Doc", created_at="2026-07-20 10:00:00 UTC"):
    return {"Document ID": document_id, "Business ID": business_id, "Document Name": name,
            "File Name": "f.pdf", "Created At": created_at}


def _content_row(document_id, document_date="", direction="", confirmed_fields_json="",
                  review_status="", review_version="", duplicate_status="", duplicate_of=""):
    return {
        "Document ID": document_id, "Document Date": document_date, "Direction": direction,
        "Has Expiration": "", "Requires Action": "",
        "Confirmed Fields JSON": confirmed_fields_json,
        "Structured Review Status": review_status, "Structured Review Version": review_version,
        "Duplicate Status": duplicate_status, "Duplicate Of Document ID": duplicate_of,
    }


def _biz_registry_row(business_id="BIZ-001"):
    return {"ID": business_id, "Название": "Test Biz"}


class _Sheets:
    def __init__(self, registry_rows=(), content_rows=(), biz_registry_rows=None, biz_registry_exists=True):
        self.registry_rows = list(registry_rows)
        self.content_rows = list(content_rows)
        self.biz_registry_rows = biz_registry_rows if biz_registry_rows is not None else [_biz_registry_row()]
        self.biz_registry_exists = biz_registry_exists
        self.read_calls: list = []

    def read_business_sheet(self, key):
        self.read_calls.append(key)
        return {
            "document_registry": self.registry_rows,
            "document_content": self.content_rows,
            "biz_registry": self.biz_registry_rows,
        }[key]

    def business_sheet_exists(self, key):
        assert key == "biz_registry"
        return self.biz_registry_exists


class _patched_sheets:
    def __init__(self, sheets):
        self._sheets = sheets
        self._p1 = None
        self._p2 = None

    def __enter__(self):
        self._p1 = patch("business_core.sheets.read_business_sheet", side_effect=self._sheets.read_business_sheet)
        self._p2 = patch("business_core.sheets.business_sheet_exists", side_effect=self._sheets.business_sheet_exists)
        self._p1.__enter__()
        self._p2.__enter__()
        return self._sheets

    def __exit__(self, *exc):
        self._p2.__exit__(*exc)
        self._p1.__exit__(*exc)
        return False


class TestSignatureAndReadCounts(unittest.TestCase):
    def test_no_optional_args_reads_both_sheets(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")])
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records("BIZ-001")
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)
        self.assertEqual(len(records), 1)

    def test_provided_registry_rows_skips_registry_read(self):
        sheets = _Sheets(content_rows=[_content_row("D1")])
        preloaded = [_registry_row("D1")]
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records("BIZ-001", registry_rows=preloaded)
        self.assertEqual(sheets.read_calls.count("document_registry"), 0)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)
        self.assertEqual(len(records), 1)

    def test_provided_content_rows_skips_content_read(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")])
        preloaded = [_content_row("D1")]
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records("BIZ-001", content_rows=preloaded)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 0)
        self.assertEqual(len(records), 1)

    def test_both_provided_zero_sheets_reads(self):
        sheets = _Sheets()
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records(
                "BIZ-001", registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")],
            )
        self.assertEqual(sheets.read_calls, [])
        self.assertEqual(len(records), 1)

    def test_empty_registry_rows_is_explicit_snapshot_not_fallback(self):
        sheets = _Sheets(registry_rows=[_registry_row("SHOULD-NOT-APPEAR")], content_rows=[])
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records("BIZ-001", registry_rows=[])
        self.assertEqual(sheets.read_calls.count("document_registry"), 0)
        self.assertEqual(records, [])

    def test_empty_content_rows_is_explicit_snapshot_not_fallback(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("SHOULD-NOT-MATTER")])
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records("BIZ-001", content_rows=[])
        self.assertEqual(sheets.read_calls.count("document_content"), 0)
        # registry row D1 has no matching content row -> never-analyzed -> excluded
        self.assertEqual(records, [])

    def test_tuple_input_supported(self):
        sheets = _Sheets()
        with _patched_sheets(sheets):
            records, warnings = ds.load_effective_document_records(
                "BIZ-001",
                registry_rows=(_registry_row("D1"),),
                content_rows=(_content_row("D1"),),
            )
        self.assertEqual(len(records), 1)


class TestInputOwnership(unittest.TestCase):
    def test_provided_rows_not_mutated(self):
        registry_rows = [_registry_row("D1"), _registry_row("D2")]
        content_rows = [_content_row("D1"), _content_row("D2")]
        registry_snapshot = [dict(r) for r in registry_rows]
        content_snapshot = [dict(r) for r in content_rows]
        sheets = _Sheets()
        with _patched_sheets(sheets):
            ds.load_effective_document_records("BIZ-001", registry_rows=registry_rows, content_rows=content_rows)
        self.assertEqual(registry_rows, registry_snapshot)
        self.assertEqual(content_rows, content_snapshot)
        self.assertEqual(len(registry_rows), 2)
        self.assertEqual(len(content_rows), 2)

    def test_provided_rows_not_retained_across_calls(self):
        """A second call with different rows must never see leftover
        state from the first — no global/module-level caching."""
        sheets = _Sheets()
        with _patched_sheets(sheets):
            records1, _ = ds.load_effective_document_records(
                "BIZ-001", registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")],
            )
            records2, _ = ds.load_effective_document_records(
                "BIZ-001", registry_rows=[_registry_row("D2")], content_rows=[_content_row("D2")],
            )
        self.assertEqual([r.document_id for r in records1], ["D1"])
        self.assertEqual([r.document_id for r in records2], ["D2"])


class TestEquivalenceWithLiveRead(unittest.TestCase):
    """For identical row data, the preloaded path and the live-read
    path must produce byte-identical records/warnings."""

    def _both_paths(self, registry_rows, content_rows, business_id="BIZ-001"):
        sheets_live = _Sheets(registry_rows=registry_rows, content_rows=content_rows)
        with _patched_sheets(sheets_live):
            live_records, live_warnings = ds.load_effective_document_records(business_id)

        sheets_preloaded = _Sheets()
        with _patched_sheets(sheets_preloaded):
            preloaded_records, preloaded_warnings = ds.load_effective_document_records(
                business_id, registry_rows=registry_rows, content_rows=content_rows,
            )
        return live_records, live_warnings, preloaded_records, preloaded_warnings

    def test_duplicate_document_id_behavior_identical(self):
        registry_rows = [_registry_row("D1", name="First"), _registry_row("D1", name="Second")]
        content_rows = [_content_row("D1")]
        live, live_w, preloaded, preloaded_w = self._both_paths(registry_rows, content_rows)
        self.assertEqual(live, preloaded)
        self.assertEqual(live_w, preloaded_w)
        self.assertIn("DUPLICATE_DOCUMENT_ID_REGISTRY:D1", preloaded_w)

    def test_malformed_cache_behavior_identical(self):
        registry_rows = [_registry_row("D1")]
        content_rows = [_content_row("D1", confirmed_fields_json="not-json-and-not-empty{")]
        live, live_w, preloaded, preloaded_w = self._both_paths(registry_rows, content_rows)
        self.assertEqual(live, preloaded)
        self.assertTrue(preloaded[0].cache_warning)
        self.assertIsNone(preloaded[0].has_conflict)

    def test_has_conflict_tristate_identical(self):
        registry_rows = [_registry_row("D1")]
        content_rows = [_content_row("D1", review_status="bogus-unknown-status")]
        live, live_w, preloaded, preloaded_w = self._both_paths(registry_rows, content_rows)
        self.assertEqual(live, preloaded)
        self.assertIsNone(preloaded[0].has_conflict)

    def test_effective_values_identical(self):
        registry_rows = [_registry_row("D1")]
        content_rows = [_content_row("D1", document_date="2026-07-01", direction="internal")]
        live, live_w, preloaded, preloaded_w = self._both_paths(registry_rows, content_rows)
        self.assertEqual(live, preloaded)
        self.assertEqual(
            preloaded[0].effective_fields.document_date.effective_value, "2026-07-01",
        )

    def test_business_boundary_identical(self):
        registry_rows = [_registry_row("D1", business_id="BIZ-001"), _registry_row("D2", business_id="BIZ-002")]
        content_rows = [_content_row("D1"), _content_row("D2")]
        live, live_w, preloaded, preloaded_w = self._both_paths(registry_rows, content_rows)
        self.assertEqual(live, preloaded)
        self.assertEqual([r.document_id for r in preloaded], ["D1"])


class TestSearchAndReportRegressionUnaffected(unittest.TestCase):
    """/finddocs and /docreport never pass the new parameters — their
    call budget and output must be exactly as before this phase."""

    def test_search_documents_call_budget_unchanged(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")])
        with _patched_sheets(sheets):
            criteria = ds.DocumentSearchCriteria(business_id="BIZ-001")
            result = ds.search_documents(criteria)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)
        self.assertEqual(result.total_matches, 1)

    def test_search_documents_never_reads_document_field_reviews(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")])
        with _patched_sheets(sheets):
            ds.search_documents(ds.DocumentSearchCriteria(business_id="BIZ-001"))
        self.assertNotIn("document_field_reviews", sheets.read_calls)

    def test_generate_document_report_call_budget_unchanged(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")])
        with _patched_sheets(sheets):
            criteria = dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = dr.generate_document_report(criteria)
        self.assertEqual(sheets.read_calls.count("biz_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.total_documents, 1)

    def test_generate_document_report_never_reads_document_field_reviews(self):
        sheets = _Sheets(registry_rows=[_registry_row("D1")], content_rows=[_content_row("D1")])
        with _patched_sheets(sheets):
            criteria = dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            dr.generate_document_report(criteria)
        self.assertNotIn("document_field_reviews", sheets.read_calls)


class TestZeroWrites(unittest.TestCase):
    def test_zero_writes_in_loader(self):
        import inspect
        source = inspect.getsource(ds.load_effective_document_records)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                          "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
