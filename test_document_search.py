"""
Phase 16B.5: Search and Reports by Effective Document Fields.

Covers: DocumentSearchCriteria validation, effective-field matching
rules (date/direction/booleans/review_status/conflict tri-state),
bulk-read architecture (exactly 2 Sheets reads regardless of row
count, 0 DOCUMENT_FIELD_REVIEWS reads, 0 writes), deterministic
sorting/pagination, business boundary, and malformed-cache safety.

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


def _fresh_ds():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_search as ds
    return ds


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


class _Sheets:
    def __init__(self, registry_rows, content_rows):
        self.registry_rows = registry_rows
        self.content_rows = content_rows
        self.read_calls = []

    def read_business_sheet(self, key):
        self.read_calls.append(key)
        return {"document_registry": self.registry_rows, "document_content": self.content_rows}[key]


def _patched(sheets):
    return patch("business_core.sheets.read_business_sheet", side_effect=sheets.read_business_sheet)


class TestParseSearchCriteria(unittest.TestCase):
    def setUp(self):
        self.ds = _fresh_ds()

    def test_business_id_required(self):
        c, err = self.ds.parse_search_criteria({})
        self.assertIsNone(c)
        self.assertIn("business_id", err)

    def test_unknown_parameter_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "foo": "bar"})
        self.assertIsNone(c)
        self.assertIn("foo", err)

    def test_object_id_rejected_as_unknown(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "object_id": "OBJ-001"})
        self.assertIsNone(c)
        self.assertIn("object_id", err)

    def test_roadmap_id_rejected_as_unknown(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "roadmap_id": "RM-001"})
        self.assertIsNone(c)

    def test_stage_id_rejected_as_unknown(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "stage_id": "STAGE-001"})
        self.assertIsNone(c)

    def test_invalid_date_from(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "date_from": "февраль 2026"})
        self.assertIsNone(c)

    def test_invalid_date_to(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "date_to": "not-a-date"})
        self.assertIsNone(c)

    def test_date_from_after_date_to_rejected(self):
        c, err = self.ds.parse_search_criteria({
            "business_id": "BIZ-001", "date_from": "2026-08-01", "date_to": "2026-07-01",
        })
        self.assertIsNone(c)

    def test_invalid_direction(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "direction": "sideways"})
        self.assertIsNone(c)

    def test_invalid_boolean_requires_action(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "requires_action": "maybe"})
        self.assertIsNone(c)

    def test_invalid_review_status(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "review_status": "bogus"})
        self.assertIsNone(c)

    def test_invalid_conflict(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "conflict": "maybe"})
        self.assertIsNone(c)

    def test_limit_above_max_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "21"})
        self.assertIsNone(c)
        self.assertIn("20", err)

    def test_limit_zero_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "0"})
        self.assertIsNone(c)

    def test_limit_negative_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "-1"})
        self.assertIsNone(c)

    def test_default_limit(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001"})
        self.assertEqual(c.limit, 10)

    def test_max_limit_accepted(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "20"})
        self.assertEqual(c.limit, 20)

    def test_offset_negative_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "offset": "-1"})
        self.assertIsNone(c)

    def test_invalid_sort_rejected(self):
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "sort": "name_asc"})
        self.assertIsNone(c)

    def test_date_from_alias(self):
        """§C: date_from -> document_date_from."""
        c, err = self.ds.parse_search_criteria({"business_id": "BIZ-001", "date_from": "2026-07-01"})
        self.assertEqual(c.document_date_from, "2026-07-01")


class TestEffectiveMatching(unittest.TestCase):
    def setUp(self):
        self.ds = _fresh_ds()

    def _run(self, registry_rows, content_rows, kv):
        criteria, err = self.ds.parse_search_criteria(kv)
        self.assertIsNone(err)
        sheets = _Sheets(registry_rows, content_rows)
        with _patched(sheets):
            return self.ds.search_documents(criteria), sheets

    def test_business_boundary(self):
        """п.1."""
        registry = [_registry_row("DREG-001", business_id="BIZ-001"), _registry_row("DREG-002", business_id="BIZ-002")]
        content = [_content_row("DREG-001", document_date="2026-07-22"), _content_row("DREG-002", document_date="2026-07-22")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001"})
        ids = [i.document_id for i in result.items]
        self.assertEqual(ids, ["DREG-001"])

    def test_date_exact_match(self):
        """п.2."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-22")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_from": "2026-07-22", "date_to": "2026-07-22"})
        self.assertEqual(result.total_matches, 1)

    def test_date_from_inclusive(self):
        """п.3."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-01")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_from": "2026-07-01"})
        self.assertEqual(result.total_matches, 1)

    def test_date_to_inclusive(self):
        """п.4."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-31")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_to": "2026-07-31"})
        self.assertEqual(result.total_matches, 1)

    def test_confirmed_date_overrides_ai(self):
        """п.5."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-23",
                                 confirmed_fields_json='{"document_date": {"value": "2026-07-22", "status": "confirmed"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_from": "2026-07-22", "date_to": "2026-07-22"})
        self.assertEqual(result.total_matches, 1)
        self.assertEqual(result.items[0].effective_document_date, "2026-07-22")

    def test_rejected_date_excluded(self):
        """п.6."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-22",
                                 confirmed_fields_json='{"document_date": {"value": "", "status": "rejected"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_from": "2026-07-01", "date_to": "2026-07-31"})
        self.assertEqual(result.total_matches, 0)

    def test_clear_unreviewed_date_uses_ai(self):
        """п.7."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-22", confirmed_fields_json="{}")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "date_from": "2026-07-22", "date_to": "2026-07-22"})
        self.assertEqual(result.total_matches, 1)
        self.assertEqual(result.items[0].document_date_source, "ai")

    def test_direction_confirmed_match(self):
        """п.8."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", direction="outgoing",
                                 confirmed_fields_json='{"direction": {"value": "internal", "status": "confirmed"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "direction": "internal"})
        self.assertEqual(result.total_matches, 1)

    def test_direction_rejected_excluded_even_from_unknown(self):
        """п.9."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", direction="",
                                 confirmed_fields_json='{"direction": {"value": "", "status": "rejected"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "direction": "unknown"})
        self.assertEqual(result.total_matches, 0)

    def test_direction_confirmed_unknown_matches(self):
        """п.10."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", direction="internal",
                                 confirmed_fields_json='{"direction": {"value": "unknown", "status": "confirmed"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "direction": "unknown"})
        self.assertEqual(result.total_matches, 1)

    def test_requires_action_true(self):
        """п.11."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        content[0]["Requires Action"] = "true"
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "requires_action": "true"})
        self.assertEqual(result.total_matches, 1)

    def test_requires_action_false(self):
        """п.12."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        content[0]["Requires Action"] = "false"
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "requires_action": "false"})
        self.assertEqual(result.total_matches, 1)

    def test_requires_action_none_excluded_from_true_and_false(self):
        """п.13."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]  # Requires Action = ""
        result_true, _ = self._run(registry, content, {"business_id": "BIZ-001", "requires_action": "true"})
        self.assertEqual(result_true.total_matches, 0)
        result_false, _ = self._run(registry, content, {"business_id": "BIZ-001", "requires_action": "false"})
        self.assertEqual(result_false.total_matches, 0)

    def test_has_expiration_true(self):
        """п.14."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        content[0]["Has Expiration"] = "true"
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "has_expiration": "true"})
        self.assertEqual(result.total_matches, 1)

    def test_has_expiration_false(self):
        """п.15."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        content[0]["Has Expiration"] = "false"
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "has_expiration": "false"})
        self.assertEqual(result.total_matches, 1)

    def test_review_status_filter(self):
        """п.16."""
        registry = [_registry_row("DREG-001"), _registry_row("DREG-002")]
        content = [_content_row("DREG-001", review_status="confirmed"), _content_row("DREG-002", review_status="unreviewed")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "review_status": "confirmed"})
        self.assertEqual([i.document_id for i in result.items], ["DREG-001"])

    def test_conflict_true(self):
        """п.17."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-23",
                                 confirmed_fields_json='{"document_date": {"value": "2026-07-22", "status": "confirmed"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "conflict": "true"})
        self.assertEqual(result.total_matches, 1)

    def test_conflict_false(self):
        """п.18."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", document_date="2026-07-22",
                                 confirmed_fields_json='{"document_date": {"value": "2026-07-22", "status": "confirmed"}}')]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001", "conflict": "false"})
        self.assertEqual(result.total_matches, 1)

    def test_malformed_cache_warning(self):
        """п.19."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", confirmed_fields_json="{not valid json")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001"})
        self.assertEqual(result.total_matches, 1)  # still included without conflict filter

    def test_no_results(self):
        """п.20."""
        registry = [_registry_row("DREG-001", business_id="BIZ-002")]
        content = [_content_row("DREG-001")]
        result, _ = self._run(registry, content, {"business_id": "BIZ-001"})
        self.assertEqual(result.total_matches, 0)
        self.assertEqual(result.items, ())


class TestConflictTriState(unittest.TestCase):
    def setUp(self):
        self.ds = _fresh_ds()

    def _run(self, registry_rows, content_rows, kv):
        criteria, err = self.ds.parse_search_criteria(kv)
        sheets = _Sheets(registry_rows, content_rows)
        with _patched(sheets):
            return self.ds.search_documents(criteria)

    def test_malformed_cache_conflict_true_excluded(self):
        """M.1: malformed cache + conflict=true filter -> excluded
        (has_conflict is None, never coerced to True)."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", confirmed_fields_json="{not valid")]
        result = self._run(registry, content, {"business_id": "BIZ-001", "conflict": "true"})
        self.assertEqual(result.total_matches, 0)

    def test_malformed_cache_conflict_false_excluded(self):
        """M.2: malformed cache + conflict=false filter -> ALSO
        excluded (None is neither True nor False)."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", confirmed_fields_json="{not valid")]
        result = self._run(registry, content, {"business_id": "BIZ-001", "conflict": "false"})
        self.assertEqual(result.total_matches, 0)

    def test_malformed_cache_no_conflict_filter_included_with_warning(self):
        """M.3."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001", confirmed_fields_json="{not valid")]
        result = self._run(registry, content, {"business_id": "BIZ-001"})
        self.assertEqual(result.total_matches, 1)
        self.assertTrue(result.items[0].cache_warning)
        self.assertIsNone(result.items[0].has_conflict)


class TestDuplicateDocumentId(unittest.TestCase):
    def test_duplicate_document_id_deterministic(self):
        """M.4: duplicate Document ID -> first occurrence wins, one
        row shown, warning recorded, no crash."""
        ds = _fresh_ds()
        registry = [_registry_row("DREG-001", name="First"), _registry_row("DREG-001", name="Second")]
        content = [_content_row("DREG-001")]
        criteria, _ = ds.parse_search_criteria({"business_id": "BIZ-001"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = ds.search_documents(criteria)
        self.assertEqual(result.total_matches, 1)
        self.assertEqual(result.items[0].document_name, "First")
        self.assertTrue(any("DUPLICATE_DOCUMENT_ID" in w for w in result.warnings))


class TestSortingAndPagination(unittest.TestCase):
    def setUp(self):
        self.ds = _fresh_ds()

    def test_default_limit(self):
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001"})
        self.assertEqual(criteria.limit, 10)

    def test_max_limit(self):
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "20"})
        self.assertEqual(criteria.limit, 20)

    def test_offset_slices_correctly(self):
        registry = [_registry_row(f"DREG-{i:03d}") for i in range(5)]
        content = [_content_row(f"DREG-{i:03d}", document_date="2026-07-01") for i in range(5)]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "2", "offset": "2"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = self.ds.search_documents(criteria)
        self.assertEqual(result.total_matches, 5)
        self.assertEqual(result.returned_count, 2)
        self.assertEqual(result.offset, 2)

    def test_deterministic_sorting_date_desc(self):
        """п.24: same input always yields same order."""
        registry = [_registry_row("DREG-002"), _registry_row("DREG-001"), _registry_row("DREG-003")]
        content = [
            _content_row("DREG-002", document_date="2026-07-15"),
            _content_row("DREG-001", document_date="2026-07-22"),
            _content_row("DREG-003", document_date="2026-07-15"),
        ]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001", "sort": "date_desc"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = self.ds.search_documents(criteria)
        ids = [i.document_id for i in result.items]
        self.assertEqual(ids, ["DREG-001", "DREG-002", "DREG-003"])  # tie broken by Document ID ASC

    def test_missing_date_last_date_desc(self):
        """п.25."""
        registry = [_registry_row("DREG-001"), _registry_row("DREG-002")]
        content = [_content_row("DREG-001", document_date=""), _content_row("DREG-002", document_date="2026-07-15")]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001", "sort": "date_desc"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = self.ds.search_documents(criteria)
        self.assertEqual([i.document_id for i in result.items], ["DREG-002", "DREG-001"])

    def test_missing_date_last_date_asc(self):
        """M.7."""
        ds = self.ds
        registry = [_registry_row("DREG-001"), _registry_row("DREG-002")]
        content = [_content_row("DREG-001", document_date=""), _content_row("DREG-002", document_date="2026-07-15")]
        criteria, _ = ds.parse_search_criteria({"business_id": "BIZ-001", "sort": "date_asc"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = ds.search_documents(criteria)
        self.assertEqual([i.document_id for i in result.items], ["DREG-002", "DREG-001"])

    def test_created_desc_malformed_created_at_last(self):
        """M.9."""
        ds = self.ds
        registry = [
            {"Document ID": "DREG-001", "Business ID": "BIZ-001", "Document Name": "A", "File Name": "f.pdf", "Created At": ""},
            {"Document ID": "DREG-002", "Business ID": "BIZ-001", "Document Name": "B", "File Name": "f.pdf", "Created At": "2026-07-20 10:00:00 UTC"},
        ]
        content = [_content_row("DREG-001"), _content_row("DREG-002")]
        criteria, _ = ds.parse_search_criteria({"business_id": "BIZ-001", "sort": "created_desc"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = ds.search_documents(criteria)
        self.assertEqual([i.document_id for i in result.items], ["DREG-002", "DREG-001"])


class TestCallBudget(unittest.TestCase):
    def setUp(self):
        self.ds = _fresh_ds()

    def test_one_document_one_registry_bulk_read(self):
        """п.27/K: exactly 1 read_business_sheet('document_registry')
        call regardless of row count."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            self.ds.search_documents(criteria)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)

    def test_hundred_documents_still_one_registry_bulk_read(self):
        """п.31."""
        registry = [_registry_row(f"DREG-{i:03d}") for i in range(100)]
        content = [_content_row(f"DREG-{i:03d}") for i in range(100)]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001", "limit": "20"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            result = self.ds.search_documents(criteria)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)
        self.assertEqual(sheets.read_calls.count("document_content"), 1)
        self.assertEqual(result.total_matches, 100)
        self.assertEqual(result.returned_count, 20)

    def test_zero_reads_document_field_reviews(self):
        """п.29."""
        registry = [_registry_row("DREG-001")]
        content = [_content_row("DREG-001")]
        criteria, _ = self.ds.parse_search_criteria({"business_id": "BIZ-001"})
        sheets = _Sheets(registry, content)
        with _patched(sheets):
            self.ds.search_documents(criteria)
        self.assertNotIn("document_field_reviews", sheets.read_calls)

    def test_zero_writes(self):
        """п.30: search_documents never imports/calls any write helper."""
        import inspect
        source = inspect.getsource(self.ds.search_documents)
        self.assertNotIn("update_business_row", source)
        self.assertNotIn("append_business_row", source)


if __name__ == "__main__":
    unittest.main()
