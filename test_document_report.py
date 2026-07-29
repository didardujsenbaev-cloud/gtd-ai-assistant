"""
Phase 16B.6: Business Document Report by Effective Fields.

Covers: DocumentReportCriteria validation, aggregation math over
effective structured fields, expiry-bucket classification and boundary
edges, expiration-inconsistency detection, duplicate-inclusion
semantics, invariant enforcement (typed failure, never partial
totals), business-not-found vs zero-documents distinction, shared
loader reuse with /finddocs, and Sheets call budget.

All tests fully mock business_core.sheets / business_core.business_builder
— no live network calls.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch


def _fresh_dr():
    import business_core.document_report as dr
    return dr


def _registry_row(document_id, business_id="BIZ-001", name="Doc", created_at="2026-07-20 10:00:00 UTC"):
    return {"Document ID": document_id, "Business ID": business_id, "Document Name": name,
            "File Name": "f.pdf", "Created At": created_at}


def _content_row(document_id, valid_until="", has_expiration="", requires_action="",
                  confirmed_fields_json="", review_status="", review_version="",
                  duplicate_status="", duplicate_of=""):
    return {
        "Document ID": document_id, "Document Date": "", "Direction": "",
        "Valid Until": valid_until, "Has Expiration": has_expiration,
        "Requires Action": requires_action,
        "Confirmed Fields JSON": confirmed_fields_json,
        "Structured Review Status": review_status, "Structured Review Version": review_version,
        "Duplicate Status": duplicate_status, "Duplicate Of Document ID": duplicate_of,
    }


def _biz_registry_row(business_id="BIZ-001"):
    return {"ID": business_id, "Название": "Test Biz"}


class _Sheets:
    """
    Fully controls both business_core.sheets.read_business_sheet() and
    business_core.sheets.business_sheet_exists() so a single object
    governs registry/content/biz_registry data AND whether biz_registry
    itself "exists" (Phase 16B.6 correction: /docreport's business-
    existence check must never risk get_business_sheet()'s auto-create
    side effect, so it goes through business_sheet_exists() first).
    """
    def __init__(self, registry_rows, content_rows, biz_registry_rows=None,
                 biz_registry_exists=True):
        self.registry_rows = registry_rows
        self.content_rows = content_rows
        self.biz_registry_rows = biz_registry_rows if biz_registry_rows is not None else [_biz_registry_row()]
        self.biz_registry_exists = biz_registry_exists
        self.read_calls = []

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
    """with _patched_sheets(sheets): ... — patches both Sheets entry
    points this module touches, from one _Sheets fixture object."""
    def __init__(self, sheets):
        self._sheets = sheets
        self._p1 = None
        self._p2 = None

    def __enter__(self):
        self._p1 = patch("business_core.sheets.read_business_sheet",
                          side_effect=self._sheets.read_business_sheet)
        self._p2 = patch("business_core.sheets.business_sheet_exists",
                          side_effect=self._sheets.business_sheet_exists)
        self._p1.__enter__()
        self._p2.__enter__()
        return self._sheets

    def __exit__(self, *exc):
        self._p2.__exit__(*exc)
        self._p1.__exit__(*exc)
        return False


def _found_sheets(content_rows, registry_rows=None, business_id="BIZ-001"):
    """Convenience: a _Sheets fixture where the business is found and
    biz_registry exists — the common case for aggregation-math tests
    that aren't specifically testing business-existence."""
    if registry_rows is None:
        registry_rows = [_registry_row(r["Document ID"], business_id=business_id) for r in content_rows]
    return _Sheets(registry_rows, content_rows, biz_registry_rows=[_biz_registry_row(business_id)])


class TestParseReportCriteria(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_business_id_required(self):
        c, err = self.dr.parse_report_criteria({})
        self.assertIsNone(c)
        self.assertIn("business_id", err)

    def test_unknown_parameter_rejected(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "foo": "bar"})
        self.assertIsNone(c)
        self.assertIn("foo", err)

    def test_object_id_rejected_as_unknown(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "object_id": "OBJ-1"})
        self.assertIsNone(c)

    def test_invalid_as_of_rejected(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "as_of": "July 2026"})
        self.assertIsNone(c)
        self.assertIn("as_of", err)

    def test_as_of_month_year_only_rejected(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "as_of": "2026-07"})
        self.assertIsNone(c)

    def test_invalid_include_duplicates_rejected(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "include_duplicates": "maybe"})
        self.assertIsNone(c)

    def test_default_include_duplicates_true(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001"})
        self.assertTrue(c.include_duplicates)

    def test_include_duplicates_false_accepted(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "include_duplicates": "false"})
        self.assertFalse(c.include_duplicates)

    def test_explicit_as_of_used_verbatim(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001", "as_of": "2026-07-29"})
        self.assertEqual(c.as_of, "2026-07-29")

    def test_default_as_of_is_utc_today_via_injectable_clock(self):
        fixed = lambda: datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc)
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001"}, now_fn=fixed)
        self.assertEqual(c.as_of, "2026-07-29")

    def test_default_as_of_without_injected_clock_is_real_utc_today(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ-001"})
        expected = datetime.now(timezone.utc).date().isoformat()
        self.assertEqual(c.as_of, expected)

    def test_business_id_control_characters_rejected(self):
        c, err = self.dr.parse_report_criteria({"business_id": "BIZ\x00001"})
        self.assertIsNone(c)


class TestBusinessNotFoundVsZeroDocuments(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_business_not_found(self):
        sheets = _Sheets([], [], biz_registry_rows=[])
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-404", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, self.dr.ERROR_BUSINESS_NOT_FOUND)
        self.assertIsNone(result.summary)

    def test_business_not_found_never_reads_document_sheets(self):
        sheets = _Sheets([], [], biz_registry_rows=[])
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-404", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)
        self.assertEqual(sheets.read_calls, ["biz_registry"])

    def test_missing_biz_registry_sheet_treated_as_not_found_no_reads(self):
        sheets = _Sheets([], [], biz_registry_exists=False)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-404", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, self.dr.ERROR_BUSINESS_NOT_FOUND)
        self.assertEqual(sheets.read_calls, [])  # business_sheet_exists() is False -> never reads at all

    def test_business_found_zero_documents_is_successful_zero_report(self):
        sheets = _Sheets([], [])
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.total_documents, 0)
        self.assertEqual(result.summary.review_unreviewed_count, 0)
        self.assertEqual(result.summary.expired_count, 0)
        self.assertEqual(result.summary.no_valid_until_count, 0)


class TestExpiryClassification(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def _report(self, content_rows, as_of="2026-07-29"):
        registry_rows = [_registry_row(r["Document ID"]) for r in content_rows]
        sheets = _Sheets(registry_rows, content_rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of=as_of)
            return self.dr.generate_document_report(criteria)

    def test_expired_before_as_of(self):
        rows = [_content_row("D1", valid_until="2026-07-28", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expired_count, 1)

    def test_expires_exactly_as_of(self):
        rows = [_content_row("D1", valid_until="2026-07-29", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expires_7d_count, 1)

    def test_expires_exactly_as_of_plus_7(self):
        rows = [_content_row("D1", valid_until="2026-08-05", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expires_7d_count, 1)

    def test_expires_exactly_as_of_plus_8(self):
        rows = [_content_row("D1", valid_until="2026-08-06", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expires_30d_count, 1)

    def test_expires_exactly_as_of_plus_30(self):
        rows = [_content_row("D1", valid_until="2026-08-28", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expires_30d_count, 1)

    def test_expires_exactly_as_of_plus_31_is_later(self):
        rows = [_content_row("D1", valid_until="2026-08-29", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expires_later_count, 1)

    def test_no_valid_until_when_empty(self):
        rows = [_content_row("D1", valid_until="", has_expiration="false")]
        result = self._report(rows)
        self.assertEqual(result.summary.no_valid_until_count, 1)
        self.assertEqual(result.summary.valid_until_present_count, 0)

    def test_valid_until_present_counted_independently(self):
        rows = [
            _content_row("D1", valid_until="2026-07-01", has_expiration="true"),
            _content_row("D2", valid_until="2026-12-01", has_expiration="true"),
        ]
        result = self._report(rows)
        self.assertEqual(result.summary.valid_until_present_count, 2)

    def test_expiry_buckets_sum_to_total(self):
        rows = [
            _content_row("D1", valid_until="2026-07-01", has_expiration="true"),
            _content_row("D2", valid_until="2026-07-30", has_expiration="true"),
            _content_row("D3", valid_until="2026-08-10", has_expiration="true"),
            _content_row("D4", valid_until="2026-12-01", has_expiration="true"),
            _content_row("D5", valid_until="", has_expiration="false"),
        ]
        result = self._report(rows)
        s = result.summary
        self.assertEqual(
            s.expired_count + s.expires_7d_count + s.expires_30d_count
            + s.expires_later_count + s.no_valid_until_count,
            s.total_documents,
        )


class TestExpirationInconsistency(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def _report(self, content_rows, as_of="2026-07-29"):
        registry_rows = [_registry_row(r["Document ID"]) for r in content_rows]
        sheets = _Sheets(registry_rows, content_rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of=as_of)
            return self.dr.generate_document_report(criteria)

    def test_has_expiration_false_with_valid_date_is_inconsistent_but_bucketed(self):
        rows = [_content_row("D1", valid_until="2026-08-01", has_expiration="false")]
        result = self._report(rows)
        self.assertEqual(result.summary.expiration_inconsistency_count, 1)
        self.assertEqual(result.summary.no_valid_until_count, 0)  # still classified into a real bucket

    def test_has_expiration_true_with_missing_date_is_inconsistent(self):
        rows = [_content_row("D1", valid_until="", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expiration_inconsistency_count, 1)
        self.assertEqual(result.summary.no_valid_until_count, 1)

    def test_consistent_true_with_date_no_inconsistency(self):
        rows = [_content_row("D1", valid_until="2026-08-01", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.expiration_inconsistency_count, 0)

    def test_consistent_false_without_date_no_inconsistency(self):
        rows = [_content_row("D1", valid_until="", has_expiration="false")]
        result = self._report(rows)
        self.assertEqual(result.summary.expiration_inconsistency_count, 0)

    def test_unknown_has_expiration_never_flagged_inconsistent(self):
        rows = [_content_row("D1", valid_until="2026-08-01", has_expiration="")]
        result = self._report(rows)
        self.assertEqual(result.summary.expiration_inconsistency_count, 0)

    def test_malformed_valid_until_counted_and_warned(self):
        rows = [_content_row("D1", valid_until="not-a-date", has_expiration="true")]
        result = self._report(rows)
        self.assertEqual(result.summary.invalid_valid_until_count, 1)
        self.assertEqual(result.summary.no_valid_until_count, 1)


class TestDuplicateSemantics(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def _rows(self):
        return [
            _content_row("D1", duplicate_status="EXACT_DUPLICATE", duplicate_of="D0"),
            _content_row("D2", duplicate_status="NEW_DOCUMENT"),
            _content_row("D3", duplicate_status=""),
        ]

    def _report(self, include_duplicates=True):
        rows = self._rows()
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(
                business_id="BIZ-001", as_of="2026-07-29", include_duplicates=include_duplicates,
            )
            return self.dr.generate_document_report(criteria)

    def test_include_duplicates_true_counts_all(self):
        result = self._report(include_duplicates=True)
        self.assertEqual(result.summary.total_documents, 3)
        self.assertEqual(result.summary.exact_duplicate_count, 1)
        self.assertEqual(result.summary.new_document_count, 1)
        self.assertEqual(result.summary.unknown_duplicate_status_count, 1)

    def test_include_duplicates_false_excludes_only_exact_duplicates(self):
        result = self._report(include_duplicates=False)
        self.assertEqual(result.summary.total_documents, 2)
        self.assertEqual(result.summary.exact_duplicate_count, 0)
        self.assertEqual(result.summary.new_document_count, 1)
        self.assertEqual(result.summary.unknown_duplicate_status_count, 1)

    def test_duplicate_counts_reconcile_with_filtered_total(self):
        result = self._report(include_duplicates=False)
        s = result.summary
        self.assertEqual(
            s.exact_duplicate_count + s.new_document_count + s.unknown_duplicate_status_count,
            s.total_documents,
        )

    def test_never_deduplicates_by_hash_again(self):
        # Two independent NEW_DOCUMENT rows never get merged/re-deduped.
        rows = [
            _content_row("D1", duplicate_status="NEW_DOCUMENT"),
            _content_row("D2", duplicate_status="NEW_DOCUMENT"),
        ]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertEqual(result.summary.total_documents, 2)
        self.assertEqual(result.summary.new_document_count, 2)


class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_review_counts_sum_to_total(self):
        rows = [
            _content_row("D1", review_status="unreviewed"),
            _content_row("D2", review_status="confirmed"),
            _content_row("D3", review_status="rejected"),
            _content_row("D4", review_status="partially_confirmed"),
        ]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        s = result.summary
        self.assertEqual(
            s.review_unreviewed_count + s.review_partially_confirmed_count
            + s.review_confirmed_count + s.review_rejected_count,
            s.total_documents,
        )

    def test_requires_action_counts_sum_to_total(self):
        rows = [
            _content_row("D1", requires_action="true"),
            _content_row("D2", requires_action="false"),
            _content_row("D3", requires_action=""),
        ]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        s = result.summary
        self.assertEqual(
            s.requires_action_true_count + s.requires_action_false_count
            + s.requires_action_unknown_count,
            s.total_documents,
        )

    def _blank_summary_kwargs(self, total=1):
        return dict(
            total_documents=total,
            review_unreviewed_count=0, review_partially_confirmed_count=0,
            review_confirmed_count=0, review_rejected_count=0,
            conflict_true_count=0, conflict_unknown_count=0, cache_warning_count=0,
            requires_action_true_count=0, requires_action_false_count=0,
            requires_action_unknown_count=0,
            has_expiration_true_count=0, has_expiration_false_count=0,
            has_expiration_unknown_count=0,
            valid_until_present_count=0, expired_count=0, expires_7d_count=0,
            expires_30d_count=0, expires_later_count=0, no_valid_until_count=0,
            invalid_valid_until_count=0, expiration_inconsistency_count=0,
            exact_duplicate_count=0, new_document_count=0, unknown_duplicate_status_count=0,
        )

    def test_invariants_hold_on_consistent_summary(self):
        kwargs = self._blank_summary_kwargs(total=1)
        kwargs["review_unreviewed_count"] = 1
        kwargs["requires_action_unknown_count"] = 1
        kwargs["has_expiration_unknown_count"] = 1
        kwargs["no_valid_until_count"] = 1
        summary = self.dr.DocumentReportSummary(**kwargs)
        self.assertTrue(self.dr._invariants_hold(summary))

    def test_invariants_fail_on_review_count_mismatch(self):
        kwargs = self._blank_summary_kwargs(total=2)  # only 1 review-status document accounted for
        kwargs["review_unreviewed_count"] = 1
        kwargs["requires_action_unknown_count"] = 2
        kwargs["has_expiration_unknown_count"] = 2
        kwargs["no_valid_until_count"] = 2
        summary = self.dr.DocumentReportSummary(**kwargs)
        self.assertFalse(self.dr._invariants_hold(summary))

    def test_invariants_fail_on_expiry_bucket_mismatch(self):
        kwargs = self._blank_summary_kwargs(total=1)
        kwargs["review_unreviewed_count"] = 1
        kwargs["requires_action_unknown_count"] = 1
        kwargs["has_expiration_unknown_count"] = 1
        # no_valid_until_count left at 0 -> expiry buckets sum to 0, not 1
        summary = self.dr.DocumentReportSummary(**kwargs)
        self.assertFalse(self.dr._invariants_hold(summary))

    def test_invariant_failure_returns_typed_error_not_partial_result(self):
        rows = [_content_row("D1", review_status="confirmed")]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets), \
             patch.object(self.dr, "_invariants_hold", return_value=False):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, self.dr.ERROR_REPORT_INVARIANT_FAILED)
        self.assertIsNone(result.summary)

    def test_normal_path_has_no_error_code_and_is_ok(self):
        rows = [_content_row("D1", review_status="confirmed")]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertTrue(result.ok)
        self.assertEqual(result.error_code, "")


class TestCacheWarningAndConflict(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_cache_warning_counted(self):
        rows = [_content_row("D1", confirmed_fields_json="not-json-and-not-empty{")]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertEqual(result.summary.cache_warning_count, 1)
        self.assertEqual(result.summary.conflict_unknown_count, 1)

    def test_malformed_row_never_dropped_from_total(self):
        rows = [_content_row("D1", confirmed_fields_json="not-json-and-not-empty{")]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertEqual(result.summary.total_documents, 1)
        self.assertEqual(result.summary.skipped_row_count, 0)


class TestSheetsCallBudget(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_exactly_two_document_reads_when_business_found(self):
        rows = [_content_row(f"D{i}") for i in range(5)]
        registry_rows = [_registry_row(r["Document ID"]) for r in rows]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)

    def test_read_count_identical_for_1_vs_100_documents(self):
        rows_1 = [_content_row("D1")]
        registry_1 = [_registry_row("D1")]
        sheets_1 = _Sheets(registry_1, rows_1)

        rows_100 = [_content_row(f"D{i}") for i in range(100)]
        registry_100 = [_registry_row(f"D{i}") for i in range(100)]
        sheets_100 = _Sheets(registry_100, rows_100)

        with _patched_sheets(sheets_1):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)

        with _patched_sheets(sheets_100):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)

        self.assertEqual(len(sheets_1.read_calls), len(sheets_100.read_calls))

    def test_never_reads_document_field_reviews(self):
        rows = [_content_row("D1")]
        registry_rows = [_registry_row("D1")]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)
        self.assertNotIn("document_field_reviews", sheets.read_calls)

    def test_zero_writes(self):
        import inspect
        source = inspect.getsource(self.dr.generate_document_report)
        for forbidden in ("update_business_row", "append_business_row", ".update(", ".append_row("):
            self.assertNotIn(forbidden, source)

    def test_business_existence_check_never_calls_get_business_config(self):
        """get_business_config() calls get_business_sheet() internally,
        which auto-creates a missing worksheet (with headers) as a side
        effect — /docreport's business-existence check must never
        actually invoke it (mentioning it in an explanatory docstring
        is fine; a real call site — "get_business_config(criteria" or
        similar — is not)."""
        import inspect
        exists_source = inspect.getsource(self.dr._business_exists)
        report_source = inspect.getsource(self.dr.generate_document_report)
        for src in (exists_source, report_source):
            self.assertNotIn("business_builder import get_business_config", src)
            self.assertNotIn("get_business_config(criteria", src)
            self.assertNotIn("get_business_config(business_id", src)

    def test_business_existence_check_uses_business_sheet_exists_first(self):
        import inspect
        source = inspect.getsource(self.dr._business_exists)
        self.assertIn("business_sheet_exists", source)

    def test_business_not_found_path_never_calls_get_business_sheet(self):
        """End-to-end guard: even business_core.sheets.get_business_sheet()
        itself (the auto-create-capable primitive) must never be invoked
        on the not-found path — business_sheet_exists() short-circuits
        before any row read is attempted."""
        sheets = _Sheets([], [], biz_registry_rows=[])
        with _patched_sheets(sheets), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-404", as_of="2026-07-29")
            self.dr.generate_document_report(criteria)
        mock_get_sheet.assert_not_called()


class TestSharedLoaderReuse(unittest.TestCase):
    def test_document_report_uses_same_loader_as_finddocs(self):
        import inspect
        report_source = inspect.getsource(_fresh_dr().generate_document_report)
        self.assertIn("load_effective_document_records", report_source)

    def test_search_documents_also_uses_shared_loader(self):
        import inspect
        import business_core.document_search as ds
        search_source = inspect.getsource(ds.search_documents)
        self.assertIn("load_effective_document_records", search_source)


class TestBusinessLevelBoundary(unittest.TestCase):
    def setUp(self):
        self.dr = _fresh_dr()

    def test_other_business_documents_excluded(self):
        rows = [_content_row("D1"), _content_row("D2")]
        registry_rows = [
            _registry_row("D1", business_id="BIZ-001"),
            _registry_row("D2", business_id="BIZ-002"),
        ]
        sheets = _Sheets(registry_rows, rows)
        with _patched_sheets(sheets):
            criteria = self.dr.DocumentReportCriteria(business_id="BIZ-001", as_of="2026-07-29")
            result = self.dr.generate_document_report(criteria)
        self.assertEqual(result.summary.total_documents, 1)


if __name__ == "__main__":
    unittest.main()
