"""
Phase 16C.3: Requirement Coverage Drill-Down (/docgap).

Covers: criteria validation, requirement_id lookup (0/1/>1 matches),
verbatim error-code passthrough from business_core.document_coverage,
detail field correctness (direct copy from DocumentCoverageItem, no
second analysis), privacy, and call-budget (exactly one
generate_document_coverage() call, max 6 distinct-sheet reads).

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import business_core.document_gap_detail as dgd
import business_core.document_coverage as dcov


def _stage_row(stage_id, roadmap_id, template_ids):
    return {"Stage ID": stage_id, "Roadmap ID": roadmap_id,
            "Document Template IDs": ",".join(template_ids)}


def _roadmap_row(roadmap_id, business_id="BIZ-001", object_id="OBJ-001"):
    return {"Roadmap ID": roadmap_id, "Business ID": business_id,
            "Service ID": "SVC-001", "Object ID": object_id}


def _template_row(template_id, title=None):
    return {"Document Template ID": template_id, "Title": title or template_id,
            "Document Type": "generic"}


def _doc_row(document_id, roadmap_id, template_id, stage_id="", object_id="OBJ-001",
             family_id=None, version="1", status="uploaded"):
    return {
        "Document ID": document_id, "Document Family ID": family_id or f"FAM-{document_id}",
        "Version": version, "Business ID": "BIZ-001", "Client ID": "PRS-001",
        "Object ID": object_id, "Roadmap ID": roadmap_id, "Stage ID": stage_id,
        "Document Template ID": template_id, "Document Name": "Test", "Status": status,
    }


def _content_row(document_id, valid_until="", review_status="", confirmed_fields_json="",
                  duplicate_status="", duplicate_of=""):
    return {
        "Document ID": document_id, "Document Date": "", "Direction": "",
        "Valid Until": valid_until, "Has Expiration": "", "Requires Action": "",
        "Confirmed Fields JSON": confirmed_fields_json,
        "Structured Review Status": review_status, "Structured Review Version": "1",
        "Duplicate Status": duplicate_status, "Duplicate Of Document ID": duplicate_of,
    }


class _Sheets:
    def __init__(self, stages=(), roadmaps=(), templates=(), documents=(), contents=(), relations=()):
        self.stages = list(stages)
        self.roadmaps = list(roadmaps)
        self.templates = list(templates)
        self.documents = list(documents)
        self.contents = list(contents)
        self.relations = list(relations)
        self.read_calls: list = []

    def read_business_sheet(self, key, *a, **kw):
        self.read_calls.append(key)
        return {
            "roadmap_stages": self.stages, "roadmaps": self.roadmaps,
            "document_template_registry": self.templates, "document_registry": self.documents,
            "document_content": self.contents, "stage_entity_relations": self.relations,
        }.get(key, [])


def _patched(sheets):
    return patch("business_core.sheets.read_business_sheet", side_effect=sheets.read_business_sheet)


def _run(sheets, roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29"):
    with _patched(sheets):
        criteria = dgd.DocumentGapDetailCriteria(
            roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of,
        )
        return dgd.generate_document_gap_detail(criteria)


def _basic_fixture(documents=(), contents=()):
    return _Sheets(
        roadmaps=[_roadmap_row("RM-1")],
        stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
        templates=[_template_row("DOC-1", "Топографическая съемка")],
        documents=list(documents), contents=list(contents),
    )


class TestParseGapDetailCriteria(unittest.TestCase):
    def test_roadmap_id_required(self):
        c, err = dgd.parse_gap_detail_criteria({"requirement_id": "STAGE-1:DOC-1"})
        self.assertIsNone(c)
        self.assertIn("roadmap_id", err)

    def test_requirement_id_required(self):
        c, err = dgd.parse_gap_detail_criteria({"roadmap_id": "RM-1"})
        self.assertIsNone(c)
        self.assertIn("requirement_id", err)

    def test_unknown_parameter_rejected(self):
        c, err = dgd.parse_gap_detail_criteria({
            "roadmap_id": "RM-1", "requirement_id": "STAGE-1:DOC-1", "stage_id": "STAGE-1",
        })
        self.assertIsNone(c)
        self.assertIn("stage_id", err)

    def test_colon_in_requirement_id_accepted(self):
        c, err = dgd.parse_gap_detail_criteria({
            "roadmap_id": "RM-1", "requirement_id": "STAGE-014:DTPL-001",
        })
        self.assertIsNone(err)
        self.assertEqual(c.requirement_id, "STAGE-014:DTPL-001")

    def test_invalid_as_of_rejected(self):
        c, err = dgd.parse_gap_detail_criteria({
            "roadmap_id": "RM-1", "requirement_id": "STAGE-1:DOC-1", "as_of": "bad-date",
        })
        self.assertIsNone(c)

    def test_default_as_of_is_utc_today(self):
        from datetime import datetime, timezone
        fixed = lambda: datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc)
        c, err = dgd.parse_gap_detail_criteria(
            {"roadmap_id": "RM-1", "requirement_id": "STAGE-1:DOC-1"}, now_fn=fixed,
        )
        self.assertEqual(c.as_of, "2026-07-29")


class TestLookupBehavior(unittest.TestCase):
    def test_requirement_not_found(self):
        sheets = _basic_fixture()
        result = _run(sheets, requirement_id="STAGE-1:DOC-999")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dgd.ERROR_REQUIREMENT_NOT_FOUND)
        self.assertIsNone(result.detail)

    def test_ambiguous_requirement_id(self):
        """Structurally unreachable via real data (see module docstring)
        — exercised here via a hand-built DocumentCoverageResult with
        two items sharing one requirement_id, proving the defensive
        check works rather than silently picking the first match."""
        item = dcov.DocumentCoverageItem(
            requirement_id="STAGE-1:DOC-1", requirement_name="Doc", stage_id="STAGE-1",
            required=True, blocking=True, minimum_count=1, base_status="present",
            matched_document_count=1, canonical_document_count=1,
            exact_duplicate_matched_count=0, unmatched_document_count=0,
        )
        fake_result = dcov.DocumentCoverageResult(
            criteria=dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29"),
            ok=True, error_code="", summary=None, items=(item, item), warnings=(),
            generated_at="2026-07-29 10:00:00 UTC",
        )
        with patch("business_core.document_coverage.generate_document_coverage", return_value=fake_result):
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29",
            )
            result = dgd.generate_document_gap_detail(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dgd.ERROR_AMBIGUOUS_REQUIREMENT_ID)
        self.assertIsNone(result.detail)

    def test_one_match_success(self):
        sheets = _basic_fixture(documents=[_doc_row("DREG-1", "RM-1", "DOC-1")])
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.detail.requirement_id, "STAGE-1:DOC-1")
        self.assertEqual(result.detail.requirement_name, "Топографическая съемка")


class TestErrorPassthrough(unittest.TestCase):
    def test_roadmap_not_found_passthrough(self):
        sheets = _Sheets()
        result = _run(sheets, roadmap_id="RM-MISSING")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_ROADMAP_NOT_FOUND)
        self.assertIsNone(result.detail)

    def test_roadmap_missing_business_id_passthrough(self):
        sheets = _Sheets(roadmaps=[{"Roadmap ID": "RM-1", "Business ID": ""}])
        result = _run(sheets)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_ROADMAP_MISSING_BUSINESS_ID)

    def test_unknown_engine_status_passthrough(self):
        """Uses a hand-built failing DocumentCoverageResult (same
        pattern as the other passthrough tests below) rather than
        patch.dict on document_coverage's module-level mapping — the
        latter mutates the dict object held by THIS test file's own
        `dcov` reference, which can silently diverge from the module
        instance document_gap_detail.py's own per-call local import
        resolves to whenever another test file's module-reload helper
        has run earlier in a full-suite collection. Patching the
        function's return value directly is immune to that by
        construction."""
        fake_result = dcov.DocumentCoverageResult(
            criteria=dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29"),
            ok=False, error_code=dcov.ERROR_UNKNOWN_ENGINE_STATUS,
            summary=None, items=(), warnings=(), generated_at="2026-07-29 10:00:00 UTC",
        )
        with patch("business_core.document_coverage.generate_document_coverage", return_value=fake_result):
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29",
            )
            result = dgd.generate_document_gap_detail(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_UNKNOWN_ENGINE_STATUS)

    def test_configuration_error_passthrough(self):
        rel = {
            "Relation ID": "REL-100", "Template Stage ID": "", "Stage ID": "STAGE-1",
            "Entity Type": "document_template", "Entity ID": "DOC-1",
            "Required": "yes", "Blocking": "true", "Minimum Count": "1",
            "Status": "active", "Created At": "2026-07-22", "Updated At": "2026-07-22",
        }
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            relations=[rel],
        )
        result = _run(sheets)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_COVERAGE_CONFIGURATION_ERROR)
        self.assertIsNone(result.detail)
        self.assertEqual(result.warnings, ())

    def test_invariant_failure_passthrough(self):
        fake_result = dcov.DocumentCoverageResult(
            criteria=dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29"),
            ok=False, error_code=dcov.ERROR_COVERAGE_INVARIANT_FAILED,
            summary=None, items=(), warnings=(), generated_at="2026-07-29 10:00:00 UTC",
        )
        with patch("business_core.document_coverage.generate_document_coverage", return_value=fake_result):
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29",
            )
            result = dgd.generate_document_gap_detail(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_COVERAGE_INVARIANT_FAILED)
        self.assertIsNone(result.detail)

    def test_partial_detail_never_shown_on_any_coverage_failure(self):
        sheets = _Sheets(roadmaps=[{"Roadmap ID": "RM-1", "Business ID": ""}])
        result = _run(sheets)
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, None)


class TestDetailFieldCorrectness(unittest.TestCase):
    def test_missing_detail(self):
        sheets = _basic_fixture()
        result = _run(sheets)
        self.assertEqual(result.detail.base_status, "missing")
        self.assertEqual(result.detail.matched_document_count, 0)

    def test_partial_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        # force minimum_count=2 scenario is not producible via legacy source;
        # partial is instead proven via document_coverage's own test suite —
        # here we confirm base_status "present" copies through untouched.
        result = _run(sheets)
        self.assertEqual(result.detail.base_status, "present")

    def test_present_needs_review_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", review_status="unreviewed")],
        )
        result = _run(sheets)
        self.assertIn("needs_review", result.detail.quality_flags)
        self.assertEqual(result.detail.needs_review_count, 1)
        self.assertEqual(result.detail.fully_confirmed_count, 0)

    def test_present_conflict_detail(self):
        content_row = _content_row("DREG-1", review_status="confirmed")
        content_row["Document Date"] = "2026-01-01"
        content_row["Confirmed Fields JSON"] = '{"document_date":{"status":"confirmed","value":"2026-02-01"}}'
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[content_row],
        )
        result = _run(sheets)
        self.assertIn("conflict", result.detail.quality_flags)
        self.assertEqual(result.detail.conflict_document_count, 1)

    def test_duplicate_only_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", duplicate_status="EXACT_DUPLICATE", duplicate_of="DREG-0")],
        )
        result = _run(sheets)
        self.assertIn("duplicate_only", result.detail.quality_flags)
        self.assertEqual(result.detail.exact_duplicate_matched_count, 1)
        self.assertEqual(result.detail.canonical_document_count, 0)

    def test_expired_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", valid_until="2020-01-01")],
        )
        result = _run(sheets)
        self.assertIn("expired", result.detail.quality_flags)
        self.assertEqual(result.detail.expired_document_count, 1)

    def test_invalid_expiry_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", valid_until="not-a-date")],
        )
        result = _run(sheets)
        self.assertIn("invalid_expiry", result.detail.quality_flags)
        self.assertEqual(result.detail.invalid_expiry_count, 1)
        self.assertNotIn("expired", result.detail.quality_flags)

    def test_cache_warning_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", confirmed_fields_json="not-json-and-not-empty{")],
        )
        result = _run(sheets)
        self.assertIn("cache_warning", result.detail.quality_flags)
        self.assertEqual(result.detail.cache_warning_document_count, 1)

    def test_unmatched_count_detail(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[],
        )
        result = _run(sheets)
        self.assertEqual(result.detail.unmatched_document_count, 1)

    def test_fully_confirmed_breakdown(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", review_status="confirmed")],
        )
        result = _run(sheets)
        self.assertEqual(result.detail.fully_confirmed_count, 1)
        self.assertEqual(result.detail.needs_review_count, 0)

    def test_expiry_counts_breakdown(self):
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
        ]
        contents = [
            _content_row("DREG-1", valid_until="2099-01-01"),
            _content_row("DREG-2", valid_until=""),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        self.assertEqual(result.detail.valid_expiry_count, 1)
        self.assertEqual(result.detail.unknown_expiry_count, 1)

    def test_required_blocking_message_data(self):
        sheets = _basic_fixture()
        result = _run(sheets)
        self.assertTrue(result.detail.required)
        self.assertTrue(result.detail.blocking)

    def test_optional_requirement_found_via_internal_include_optional(self):
        """A requirement with required=False must still be found by
        /docgap — internally, generate_document_gap_detail() always
        calls the coverage layer with include_optional=True regardless
        of anything the caller passed (there is no include_optional
        parameter on /docgap at all)."""
        item = dcov.DocumentCoverageItem(
            requirement_id="STAGE-1:DOC-1", requirement_name="Optional Doc", stage_id="STAGE-1",
            required=False, blocking=False, minimum_count=1, base_status="optional_missing",
            matched_document_count=0, canonical_document_count=0,
            exact_duplicate_matched_count=0, unmatched_document_count=0,
        )
        fake_result = dcov.DocumentCoverageResult(
            criteria=dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29", include_optional=True),
            ok=True, error_code="", summary=None, items=(item,), warnings=(),
            generated_at="2026-07-29 10:00:00 UTC",
        )
        with patch("business_core.document_coverage.generate_document_coverage", return_value=fake_result) as mock_gen:
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29",
            )
            result = dgd.generate_document_gap_detail(criteria)
        self.assertTrue(result.ok)
        self.assertFalse(result.detail.required)
        called_criteria = mock_gen.call_args[0][0]
        self.assertTrue(called_criteria.include_optional)


class TestPrivacy(unittest.TestCase):
    def test_no_document_id_in_result_dataclass(self):
        import dataclasses
        sheets = _basic_fixture(documents=[_doc_row("DREG-1", "RM-1", "DOC-1")])
        result = _run(sheets)
        field_names = {f.name for f in dataclasses.fields(result.detail)}
        self.assertNotIn("document_id", field_names)
        self.assertNotIn("document_ids", field_names)
        self.assertNotIn("matched_document_ids", field_names)
        self.assertNotIn("file_name", field_names)
        self.assertNotIn("document_name", field_names)

    def test_no_raw_warnings_on_success(self):
        sheets = _basic_fixture(documents=[_doc_row("DREG-1", "RM-1", "DOC-1")])
        result = _run(sheets)
        self.assertEqual(result.warnings, ())


class TestCallBudget(unittest.TestCase):
    def test_max_six_reads(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        _run(sheets)
        self.assertLessEqual(len(sheets.read_calls), 6)

    def test_no_repeated_document_registry_read(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        _run(sheets)
        self.assertEqual(sheets.read_calls.count("document_registry"), 1)

    def test_zero_document_field_reviews(self):
        sheets = _basic_fixture(documents=[_doc_row("DREG-1", "RM-1", "DOC-1")])
        _run(sheets)
        self.assertNotIn("document_field_reviews", sheets.read_calls)

    def test_zero_writes(self):
        import inspect
        source = inspect.getsource(dgd)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                          "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)

    def test_exactly_one_coverage_call(self):
        sheets = _basic_fixture(documents=[_doc_row("DREG-1", "RM-1", "DOC-1")])
        with _patched(sheets), patch(
            "business_core.document_coverage.generate_document_coverage",
            wraps=dcov.generate_document_coverage,
        ) as spy:
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id="STAGE-1:DOC-1", as_of="2026-07-29",
            )
            dgd.generate_document_gap_detail(criteria)
        self.assertEqual(spy.call_count, 1)


class TestTypedUploadContextPropagation(unittest.TestCase):
    """Phase 16C.8.2A: business_id/document_template_id are copied
    straight from DocumentCoverageItem onto DocumentGapDetail — no
    second read, no requirement_id parsing."""

    def _run_with_item(self, requirement_id, business_id, document_template_id, stage_id="STAGE-011"):
        item = dcov.DocumentCoverageItem(
            requirement_id=requirement_id, requirement_name="Doc", stage_id=stage_id,
            required=True, blocking=True, minimum_count=1, base_status="missing",
            matched_document_count=0, canonical_document_count=0,
            exact_duplicate_matched_count=0, unmatched_document_count=0,
            business_id=business_id, document_template_id=document_template_id,
        )
        fake_result = dcov.DocumentCoverageResult(
            criteria=dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29"),
            ok=True, error_code="", summary=None, items=(item,), warnings=(),
            generated_at="2026-07-29 10:00:00 UTC",
        )
        with patch("business_core.document_coverage.generate_document_coverage", return_value=fake_result):
            criteria = dgd.DocumentGapDetailCriteria(
                roadmap_id="RM-1", requirement_id=requirement_id, as_of="2026-07-29",
            )
            return dgd.generate_document_gap_detail(criteria)

    def test_gap_detail_exact_business_id(self):
        result = self._run_with_item("STAGE-011:DOC-008", "BIZ-001", "DOC-008")
        self.assertEqual(result.detail.business_id, "BIZ-001")

    def test_gap_detail_exact_document_template_id(self):
        result = self._run_with_item("STAGE-011:DOC-008", "BIZ-001", "DOC-008")
        self.assertEqual(result.detail.document_template_id, "DOC-008")

    def test_opaque_requirement_id_not_parsed(self):
        result = self._run_with_item("REQ-ALPHA-001", "BIZ-001", "DOC-008", stage_id="STAGE-011")
        self.assertEqual(result.detail.requirement_id, "REQ-ALPHA-001")
        self.assertEqual(result.detail.stage_id, "STAGE-011")
        self.assertEqual(result.detail.document_template_id, "DOC-008")
        self.assertEqual(result.detail.business_id, "BIZ-001")

    def test_empty_business_id_stays_empty(self):
        result = self._run_with_item("STAGE-011:DOC-008", "", "DOC-008")
        self.assertEqual(result.detail.business_id, "")

    def test_empty_document_template_id_stays_empty(self):
        result = self._run_with_item("STAGE-011:DOC-008", "BIZ-001", "")
        self.assertEqual(result.detail.document_template_id, "")

    def test_failure_result_business_id_and_template_empty(self):
        """On any typed failure, detail is None entirely — nothing to
        assert on business_id/document_template_id since there's no
        detail object at all; this guards that assumption stays true."""
        sheets = _basic_fixture()
        result = _run(sheets, requirement_id="STAGE-1:DOC-999")
        self.assertFalse(result.ok)
        self.assertIsNone(result.detail)


if __name__ == "__main__":
    unittest.main()
