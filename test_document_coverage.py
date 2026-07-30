"""
Phase 16C.2: Document Requirements Coverage (/docgaps).

Covers: criteria validation, base_status = exhaustive passthrough of
the requirements engine's own status, quality-flag algorithms
(needs_review/conflict/expired/duplicate_only/cache_warning/
invalid_expiry) per the corrected Phase 16C.2 contract (absent
Valid Until is neither valid nor expired), privacy-safe unmatched-
document handling, deterministic ordering, invariant enforcement,
shared-context call budget (max 6 distinct-sheet reads, 0
DOCUMENT_FIELD_REVIEWS, 0 writes), and business-boundary correctness.

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

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


def _run(sheets, roadmap_id="RM-1", stage_id="", include_optional=False, as_of="2026-07-29"):
    with _patched(sheets):
        criteria = dcov.DocumentCoverageCriteria(
            roadmap_id=roadmap_id, stage_id=stage_id, include_optional=include_optional, as_of=as_of,
        )
        return dcov.generate_document_coverage(criteria)


class TestParseCoverageCriteria(unittest.TestCase):
    def test_roadmap_id_required(self):
        c, err = dcov.parse_coverage_criteria({})
        self.assertIsNone(c)
        self.assertIn("roadmap_id", err)

    def test_unknown_parameter_rejected(self):
        c, err = dcov.parse_coverage_criteria({"roadmap_id": "RM-1", "object_id": "OBJ-1"})
        self.assertIsNone(c)
        self.assertIn("object_id", err)

    def test_default_include_optional_false(self):
        c, err = dcov.parse_coverage_criteria({"roadmap_id": "RM-1"})
        self.assertFalse(c.include_optional)

    def test_invalid_as_of_rejected(self):
        c, err = dcov.parse_coverage_criteria({"roadmap_id": "RM-1", "as_of": "not-a-date"})
        self.assertIsNone(c)

    def test_invalid_include_optional_rejected(self):
        c, err = dcov.parse_coverage_criteria({"roadmap_id": "RM-1", "include_optional": "maybe"})
        self.assertIsNone(c)

    def test_stage_id_optional(self):
        c, err = dcov.parse_coverage_criteria({"roadmap_id": "RM-1"})
        self.assertEqual(c.stage_id, "")


class TestScopeValidation(unittest.TestCase):
    def test_roadmap_not_found(self):
        sheets = _Sheets()
        result = _run(sheets, roadmap_id="RM-MISSING")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_ROADMAP_NOT_FOUND)
        self.assertIsNone(result.summary)

    def test_roadmap_missing_business_id(self):
        sheets = _Sheets(roadmaps=[{"Roadmap ID": "RM-1", "Business ID": ""}])
        result = _run(sheets)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_ROADMAP_MISSING_BUSINESS_ID)

    def test_stage_not_found(self):
        sheets = _Sheets(roadmaps=[_roadmap_row("RM-1")])
        result = _run(sheets, stage_id="STAGE-MISSING")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_STAGE_NOT_FOUND)

    def test_stage_outside_roadmap(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1"), _roadmap_row("RM-2")],
            stages=[_stage_row("STAGE-1", "RM-2", [])],
        )
        result = _run(sheets, roadmap_id="RM-1", stage_id="STAGE-1")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_STAGE_NOT_IN_ROADMAP)


class TestBaseStatusPassthrough(unittest.TestCase):
    def test_present_status_matches_engine(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1", "Техпаспорт")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
        )
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.items[0].base_status, "present")
        self.assertEqual(result.items[0].requirement_name, "Техпаспорт")

    def test_missing_status_matches_engine(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].base_status, "missing")

    def test_unknown_engine_status_returns_typed_failure(self):
        with patch.dict(dcov._ENGINE_STATUS_TO_BASE_STATUS, {}, clear=True):
            sheets = _Sheets(
                roadmaps=[_roadmap_row("RM-1")],
                stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
                templates=[_template_row("DOC-1")],
            )
            result = _run(sheets)
            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, dcov.ERROR_UNKNOWN_ENGINE_STATUS)
            self.assertIsNone(result.summary)

    def test_not_applicable_is_not_mapped_and_returns_typed_failure(self):
        """Phase 16C.2 correction: STATUS_NOT_APPLICABLE is confirmed
        unreachable via _evaluate_requirement() (full re-read of
        business_core.document_requirements), so it is deliberately
        excluded from the mapping — simulating its appearance must
        produce the same typed failure as any other unmapped status,
        never a silently invented counting/ordering/rendering rule.

        Uses patch.object(dcov, ...) — never the string-path
        patch("business_core.document_coverage....") form. The string
        form re-resolves its target via sys.modules at patch time,
        which can be a DIFFERENT module object than this test file's
        own `dcov` reference whenever another test file's module-reload
        helper (_fresh_dr()) has already swapped
        business_core.document_coverage out of sys.modules earlier in a
        full-suite run. patch.object(dcov, ...) patches the exact
        object this test already holds, so it can never target the
        wrong module instance.
        """
        from business_core.document_requirements import (
            STATUS_NOT_APPLICABLE, DocumentRequirementStatus, DocumentRequirement, RequirementsSummary,
        )
        self.assertNotIn(STATUS_NOT_APPLICABLE, dcov._ENGINE_STATUS_TO_BASE_STATUS)

        requirement = DocumentRequirement(
            requirement_id="STAGE-1:DOC-1", document_template_id="DOC-1",
            name="Doc", stage_id="STAGE-1", roadmap_id="RM-1",
        )
        fake_status = DocumentRequirementStatus(
            requirement=requirement, matched_document_ids=(), matched_count=0,
            status=STATUS_NOT_APPLICABLE,
        )
        fake_summary = RequirementsSummary(
            scope_type="roadmap", scope_id="RM-1", items=(fake_status,),
            total_required=0, has_configuration_errors=False,
        )

        sheets = _Sheets(roadmaps=[_roadmap_row("RM-1")])
        with _patched(sheets), patch.object(
            dcov, "evaluate_roadmap_requirements", return_value=fake_summary,
        ):
            criteria = dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29")
            result = dcov.generate_document_coverage(criteria)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_UNKNOWN_ENGINE_STATUS)
        self.assertIsNone(result.summary)


class TestConfigurationErrors(unittest.TestCase):
    def _instance_rel(self, **overrides):
        row = {
            "Relation ID": "REL-100", "Template Stage ID": "", "Stage ID": "STAGE-1",
            "Entity Type": "document_template", "Entity ID": "DOC-1",
            "Required": "true", "Blocking": "true", "Minimum Count": "1",
            "Status": "active", "Created At": "2026-07-22", "Updated At": "2026-07-22",
        }
        row.update(overrides)
        return row

    def test_configuration_error_returns_typed_failure(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            relations=[self._instance_rel(Required="yes")],  # invalid value -> validation error
        )
        result = _run(sheets)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dcov.ERROR_COVERAGE_CONFIGURATION_ERROR)

    def test_configuration_error_summary_is_none_no_partial_totals(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            relations=[self._instance_rel(Required="yes")],
        )
        result = _run(sheets)
        self.assertIsNone(result.summary)
        self.assertEqual(result.items, ())

    def test_configuration_error_warnings_contain_only_safe_code(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            relations=[self._instance_rel(Required="yes")],
        )
        result = _run(sheets)
        self.assertEqual(result.warnings, ("REQUIREMENTS_CONFIGURATION_ERROR",))
        for w in result.warnings:
            self.assertNotIn("REL-", w)
            self.assertNotIn("DOC-", w)
            self.assertNotIn("STAGE-", w)

    def test_clean_requirements_still_produce_normal_summary(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
        )
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.error_code, "")
        self.assertIsNotNone(result.summary)


class TestIncludeOptional(unittest.TestCase):
    def test_include_optional_flag_does_not_crash_with_no_optional_requirements(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
        )
        result = _run(sheets, include_optional=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.optional_count, 0)


class TestNeedsReview(unittest.TestCase):
    def _fixture(self, review_status):
        return _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", review_status=review_status)],
        )

    def test_unreviewed_triggers_needs_review(self):
        result = _run(self._fixture("unreviewed"))
        self.assertIn("needs_review", result.items[0].quality_flags)

    def test_partially_confirmed_triggers_needs_review(self):
        result = _run(self._fixture("partially_confirmed"))
        self.assertIn("needs_review", result.items[0].quality_flags)

    def test_confirmed_does_not_trigger_needs_review(self):
        result = _run(self._fixture("confirmed"))
        self.assertNotIn("needs_review", result.items[0].quality_flags)

    def test_rejected_structured_review_triggers_needs_review(self):
        result = _run(self._fixture("rejected"))
        self.assertIn("needs_review", result.items[0].quality_flags)
        self.assertEqual(result.items[0].base_status, "present")  # base_status unaffected

    def test_unknown_review_status_triggers_needs_review_and_cache_warning(self):
        result = _run(self._fixture("some-future-status"))
        self.assertIn("needs_review", result.items[0].quality_flags)
        self.assertIn("cache_warning", result.items[0].quality_flags)


class TestConflictAndCacheWarning(unittest.TestCase):
    def test_conflict_true(self):
        content_row = _content_row("DREG-1", review_status="confirmed")
        content_row["Document Date"] = "2026-01-01"  # AI-derived value
        content_row["Confirmed Fields JSON"] = (
            '{"document_date":{"status":"confirmed","value":"2026-02-01"}}'
        )
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[content_row],
        )
        result = _run(sheets)
        self.assertIn("conflict", result.items[0].quality_flags)

    def test_malformed_cache_produces_cache_warning_not_conflict_true(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", confirmed_fields_json="not-json-and-not-empty{")],
        )
        result = _run(sheets)
        self.assertIn("cache_warning", result.items[0].quality_flags)
        self.assertNotIn("conflict", result.items[0].quality_flags)


class TestExpiryClassification(unittest.TestCase):
    def _fixture(self, valid_until, minimum_count_docs=1):
        docs = [_doc_row("DREG-1", "RM-1", "DOC-1")]
        contents = [_content_row("DREG-1", valid_until=valid_until)]
        return _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )

    def test_absent_valid_until_is_not_valid_and_not_expired(self):
        result = _run(self._fixture(""))
        self.assertNotIn("expired", result.items[0].quality_flags)

    def test_expired_date_with_minimum_count_1_no_other_valid_no_flag(self):
        """minimum_count=1, single document expired: valid_count(0) < 1
        AND expired_count(1)>0 -> expired flag SHOULD fire here (only
        one document exists and it's expired)."""
        result = _run(self._fixture("2020-01-01"))
        self.assertIn("expired", result.items[0].quality_flags)

    def test_invalid_valid_until_flagged_never_expired(self):
        result = _run(self._fixture("not-a-real-date"))
        self.assertIn("invalid_expiry", result.items[0].quality_flags)
        self.assertNotIn("expired", result.items[0].quality_flags)

    def test_valid_future_date_no_expired_flag(self):
        result = _run(self._fixture("2099-01-01"))
        self.assertNotIn("expired", result.items[0].quality_flags)
        self.assertNotIn("invalid_expiry", result.items[0].quality_flags)

    def test_one_expired_one_valid_with_minimum_count_1_no_flag(self):
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
        ]
        contents = [
            _content_row("DREG-1", valid_until="2020-01-01"),
            _content_row("DREG-2", valid_until="2099-01-01"),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        self.assertNotIn("expired", result.items[0].quality_flags)  # minimum_count=1, 1 valid is enough

    def test_unknown_expiry_cannot_satisfy_valid_count(self):
        """A document with no Valid Until must not count toward
        valid_count, so if minimum_count=1 and the only expired
        document plus an unknown-expiry document exist, expired must
        still fire (unknown never substitutes for valid)."""
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
        ]
        contents = [
            _content_row("DREG-1", valid_until="2020-01-01"),
            _content_row("DREG-2", valid_until=""),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        self.assertIn("expired", result.items[0].quality_flags)


class TestDuplicateOnly(unittest.TestCase):
    def test_exact_duplicate_not_canonical(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", duplicate_status="EXACT_DUPLICATE", duplicate_of="DREG-0")],
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].canonical_document_count, 0)
        self.assertEqual(result.items[0].exact_duplicate_matched_count, 1)

    def test_duplicate_only_flag_when_canonical_insufficient(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", duplicate_status="EXACT_DUPLICATE", duplicate_of="DREG-0")],
        )
        result = _run(sheets)
        # base_status is "present" (registry engine sees 1 matched, satisfies minimum_count=1)
        # but canonical_document_count(0) < minimum_count(1) with exact_duplicate present -> duplicate_only
        self.assertEqual(result.items[0].base_status, "present")
        self.assertIn("duplicate_only", result.items[0].quality_flags)

    def test_canonical_plus_duplicate_no_duplicate_only_flag(self):
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
        ]
        contents = [
            _content_row("DREG-1", duplicate_status="EXACT_DUPLICATE", duplicate_of="DREG-0"),
            _content_row("DREG-2", duplicate_status="NEW_DOCUMENT"),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].canonical_document_count, 1)
        self.assertNotIn("duplicate_only", result.items[0].quality_flags)

    def test_legacy_empty_duplicate_status_is_canonical(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1", duplicate_status="")],
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].canonical_document_count, 1)


class TestUnmatchedDocumentPrivacy(unittest.TestCase):
    def test_unmatched_id_does_not_trigger_duplicate_only(self):
        """A matched Document ID with no corresponding content row (or
        outside the effective loader's business scope) must be counted
        as unmatched, never silently treated as an exact duplicate."""
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[],  # DREG-1 never analyzed -> effective loader excludes it entirely
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].unmatched_document_count, 1)
        self.assertNotIn("duplicate_only", result.items[0].quality_flags)
        self.assertIn("cache_warning", result.items[0].quality_flags)

    def test_warnings_never_contain_document_id(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[
                _doc_row("DREG-DUP-1", "RM-1", "DOC-1", family_id="FAM-A"),
            ],
            contents=[_content_row("DREG-DUP-1")],
        )
        result = _run(sheets)
        for w in result.warnings:
            self.assertNotIn("DREG", w)

    def test_result_never_exposes_document_id_field(self):
        import dataclasses
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        result = _run(sheets)
        item_fields = {f.name for f in dataclasses.fields(result.items[0])}
        self.assertNotIn("document_id", item_fields)
        self.assertNotIn("document_ids", item_fields)
        self.assertNotIn("matched_document_ids", item_fields)


class TestInvariantsAndZeroRequirements(unittest.TestCase):
    def test_no_requirements_success(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", [])],
        )
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.total_requirements, 0)

    def test_no_requirements_skips_effective_loader_zero_content_reads(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", [])],
        )
        result = _run(sheets)
        self.assertEqual(sheets.read_calls.count("document_content"), 0)

    def test_all_missing_requirements_skip_document_content_read(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].base_status, "missing")
        self.assertEqual(sheets.read_calls.count("document_content"), 0)

    def test_no_documents_present_still_ok(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[],
        )
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.missing_count, 1)


class TestOrdering(unittest.TestCase):
    def test_deterministic_ordering_missing_before_present(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1", "DOC-2"])],
            templates=[_template_row("DOC-1"), _template_row("DOC-2")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-2")],
        )
        result = _run(sheets)
        statuses = [i.base_status for i in result.items]
        self.assertEqual(statuses, ["missing", "present"])


class TestCallBudget(unittest.TestCase):
    def test_max_six_reads_with_requirements_and_documents(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        _run(sheets)
        self.assertLessEqual(len(sheets.read_calls), 6)
        for key in ("roadmaps", "roadmap_stages", "stage_entity_relations",
                    "document_template_registry", "document_registry", "document_content"):
            self.assertLessEqual(sheets.read_calls.count(key), 1)

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

    def test_q1_vs_q100_same_max_reads(self):
        def make(n):
            tids = [f"DOC-{i}" for i in range(n)]
            return _Sheets(
                roadmaps=[_roadmap_row("RM-1")],
                stages=[_stage_row("STAGE-1", "RM-1", tids)],
                templates=[_template_row(t) for t in tids],
            )
        sheets_1 = make(1)
        _run(sheets_1)
        sheets_100 = make(100)
        _run(sheets_100)
        self.assertEqual(len(sheets_1.read_calls), len(sheets_100.read_calls))

    def test_no_document_field_reviews_read(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row("DREG-1")],
        )
        _run(sheets)
        self.assertNotIn("document_field_reviews", sheets.read_calls)

    def test_zero_writes(self):
        import inspect
        source = inspect.getsource(dcov)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                          "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)


class TestPhase16C3AdditiveCounters(unittest.TestCase):
    """Phase 16C.3: new numeric fields on DocumentCoverageItem, sourced
    from the exact same _quality_for_item() computation — never a
    second analysis pass. Confirms additive backward compatibility and
    the expiry-bucket invariant."""

    def test_fully_confirmed_and_needs_review_counts(self):
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
        ]
        contents = [
            _content_row("DREG-1", review_status="confirmed"),
            _content_row("DREG-2", review_status="unreviewed"),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        item = result.items[0]
        self.assertEqual(item.fully_confirmed_count, 1)
        self.assertEqual(item.needs_review_count, 1)
        self.assertEqual(item.fully_confirmed_count + item.needs_review_count, item.canonical_document_count)

    def test_conflict_document_count(self):
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
        self.assertEqual(result.items[0].conflict_document_count, 1)

    def test_cache_warning_document_count_no_double_count(self):
        """A document that is BOTH cache_warning=True AND has an
        unknown review status must count once, not twice, in
        cache_warning_document_count."""
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
            contents=[_content_row(
                "DREG-1", review_status="some-future-status",
                confirmed_fields_json="not-json-and-not-empty{",
            )],
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].cache_warning_document_count, 1)

    def test_expiry_buckets_sum_to_canonical_count(self):
        docs = [
            _doc_row("DREG-1", "RM-1", "DOC-1", family_id="FAM-A"),
            _doc_row("DREG-2", "RM-1", "DOC-1", family_id="FAM-B"),
            _doc_row("DREG-3", "RM-1", "DOC-1", family_id="FAM-C"),
            _doc_row("DREG-4", "RM-1", "DOC-1", family_id="FAM-D"),
        ]
        contents = [
            _content_row("DREG-1", valid_until="2099-01-01"),
            _content_row("DREG-2", valid_until="2020-01-01"),
            _content_row("DREG-3", valid_until=""),
            _content_row("DREG-4", valid_until="not-a-date"),
        ]
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=docs, contents=contents,
        )
        result = _run(sheets)
        item = result.items[0]
        self.assertEqual(item.valid_expiry_count, 1)
        self.assertEqual(item.expired_document_count, 1)
        self.assertEqual(item.unknown_expiry_count, 1)
        self.assertEqual(item.invalid_expiry_count, 1)
        self.assertEqual(
            item.valid_expiry_count + item.expired_document_count
            + item.unknown_expiry_count + item.invalid_expiry_count,
            item.canonical_document_count,
        )

    def test_additive_fields_do_not_change_existing_summary(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-1", "DOC-1")],
        )
        result = _run(sheets)
        self.assertTrue(result.ok)
        self.assertEqual(result.summary.present_count, 1)
        # New fields default safely to 0 for a document with no content row.
        self.assertEqual(result.items[0].fully_confirmed_count, 0)
        self.assertEqual(result.items[0].needs_review_count, 0)


class TestBusinessBoundary(unittest.TestCase):
    def test_documents_outside_roadmap_never_counted(self):
        sheets = _Sheets(
            roadmaps=[_roadmap_row("RM-1"), _roadmap_row("RM-2")],
            stages=[_stage_row("STAGE-1", "RM-1", ["DOC-1"])],
            templates=[_template_row("DOC-1")],
            documents=[_doc_row("DREG-1", "RM-2", "DOC-1")],  # wrong roadmap
        )
        result = _run(sheets)
        self.assertEqual(result.items[0].base_status, "missing")


class TestTypedUploadContextPropagation(unittest.TestCase):
    """Phase 16C.8.2A: business_id/document_template_id are threaded
    from the already-loaded DocumentRequirement straight onto
    DocumentCoverageItem — never derived by parsing requirement_id."""

    def _fake_engine_summary(self, requirement_id, stage_id, document_template_id, business_id):
        from business_core.document_requirements import (
            DocumentRequirement, DocumentRequirementStatus, RequirementsSummary, STATUS_MISSING,
        )
        req = DocumentRequirement(
            requirement_id=requirement_id, document_template_id=document_template_id,
            stage_id=stage_id, business_id=business_id,
        )
        status = DocumentRequirementStatus(requirement=req, matched_document_ids=(), matched_count=0,
                                            status=STATUS_MISSING)
        return RequirementsSummary(scope_type="roadmap", scope_id="RM-1", items=(status,))

    def _run_with_fake_engine(self, requirement_id, stage_id, document_template_id, business_id):
        summary = self._fake_engine_summary(requirement_id, stage_id, document_template_id, business_id)
        # Roadmap-level Business ID is always non-empty here — that's a
        # separate concern (ERROR_ROADMAP_MISSING_BUSINESS_ID) from the
        # per-requirement business_id field under test.
        #
        # patch.object(dcov, ...) — never the string-path
        # patch("business_core.document_coverage....") form, per this
        # file's own documented hazard (see
        # test_not_applicable_is_not_mapped_and_returns_typed_failure):
        # the string form re-resolves its target via sys.modules at
        # patch time, which can be a DIFFERENT module object than this
        # test file's own `dcov` reference whenever another test
        # file's module-reload helper (_fresh_th()/_fresh_dr()/
        # _fresh_drq() in test_business_document_requirements.py) has
        # already swapped business_core.document_coverage out of
        # sys.modules earlier in a full-suite run. patch.object(dcov,
        # ...) patches the exact object this test already holds, so it
        # can never target the wrong module instance. The
        # business_core.sheets.read_business_sheet string-path patch
        # below is unaffected by this hazard: RequirementsReadContext
        # .roadmap_by_id() does a fresh `from business_core.sheets
        # import read_business_sheet_cached` at call time, so it
        # always resolves against whatever is currently in
        # sys.modules — the same thing this patch targets.
        with patch.object(dcov, "evaluate_roadmap_requirements", return_value=summary), \
             patch("business_core.sheets.read_business_sheet",
                   side_effect=lambda key, *a, **kw: {"roadmaps": [_roadmap_row("RM-1", business_id="BIZ-ROADMAP")]}.get(key, [])):
            criteria = dcov.DocumentCoverageCriteria(roadmap_id="RM-1", as_of="2026-07-29")
            result = dcov.generate_document_coverage(criteria)
        self.assertTrue(result.ok, result.error_code)
        self.assertEqual(len(result.items), 1)
        return result

    def test_coverage_item_exact_business_id(self):
        result = self._run_with_fake_engine("STAGE-1:DOC-1", "STAGE-1", "DOC-1", "BIZ-001")
        self.assertEqual(result.items[0].business_id, "BIZ-001")

    def test_coverage_item_exact_document_template_id(self):
        result = self._run_with_fake_engine("STAGE-1:DOC-1", "STAGE-1", "DOC-1", "BIZ-001")
        self.assertEqual(result.items[0].document_template_id, "DOC-1")

    def test_opaque_requirement_id_not_parsed(self):
        """requirement_id deliberately does NOT follow the
        stage_id:template_id convention — document_template_id/
        business_id must still come through exactly, proving no
        string-splitting of requirement_id occurs anywhere."""
        result = self._run_with_fake_engine(
            requirement_id="REQ-ALPHA-001", stage_id="STAGE-011",
            document_template_id="DOC-008", business_id="BIZ-001",
        )
        item = result.items[0]
        self.assertEqual(item.requirement_id, "REQ-ALPHA-001")
        self.assertEqual(item.stage_id, "STAGE-011")
        self.assertEqual(item.document_template_id, "DOC-008")
        self.assertEqual(item.business_id, "BIZ-001")

    def test_empty_business_id_stays_empty(self):
        result = self._run_with_fake_engine("STAGE-1:DOC-1", "STAGE-1", "DOC-1", business_id="")
        self.assertEqual(result.items[0].business_id, "")

    def test_empty_document_template_id_stays_empty(self):
        result = self._run_with_fake_engine("STAGE-1:DOC-1", "STAGE-1", "", business_id="BIZ-001")
        self.assertEqual(result.items[0].document_template_id, "")

    def test_existing_fixture_omitting_new_fields_still_works(self):
        """A DocumentCoverageItem built the old way (no business_id/
        document_template_id kwargs) must still construct successfully
        with safe empty defaults — backward compatibility guard."""
        item = dcov.DocumentCoverageItem(
            requirement_id="STAGE-1:DOC-1", requirement_name="Doc", stage_id="STAGE-1",
            required=True, blocking=True, minimum_count=1, base_status="present",
            matched_document_count=1, canonical_document_count=1,
            exact_duplicate_matched_count=0, unmatched_document_count=0,
        )
        self.assertEqual(item.business_id, "")
        self.assertEqual(item.document_template_id, "")


if __name__ == "__main__":
    unittest.main()
