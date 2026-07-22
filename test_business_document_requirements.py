"""
Phase 17A: Document Requirements Engine Foundation — mock tests.

Audit finding: ROADMAP_STAGES."Document Template IDs" is the only
structured, ID-referenceable document-requirement source in this
codebase (see business_core/document_requirements.py's module
docstring and the Phase 17A audit report for the full write-up).
SERVICE_CATALOG's free-text document fields are deliberately not used.

Covers: no requirements, present/missing/partial, blocking, optional,
minimum_count > 1, authoritative-template-only matching (AI suggested
template never counts), wrong stage/object documents never counting,
accepted vs rejected/archived statuses, multi-version families
(supersession, no inflation), independent-family duplicates counting
correctly, roadmap/object aggregation, completion percentage math,
zero-requirement behavior, and read-only guarantees (no AI, no Drive,
no Sheets writes).

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch


def _fresh_dr():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_requirements as dr
    return dr


def _fresh_drq():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_requirements_query as drq
    return drq


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


# ────────────────────────────────────────────────────────────
# Fixture data + patch harness
# ────────────────────────────────────────────────────────────

STAGES = [
    {"Stage ID": "STAGE-001", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-001"},
    {"Stage ID": "STAGE-002", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-002,DOC-003"},
    {"Stage ID": "STAGE-003", "Roadmap ID": "RM-001", "Document Template IDs": ""},
    {"Stage ID": "STAGE-999", "Roadmap ID": "RM-002", "Document Template IDs": "DOC-001"},
]

ROADMAPS = [
    {"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Service ID": "SVC-001", "Object ID": "OBJ-001"},
    {"Roadmap ID": "RM-002", "Business ID": "BIZ-001", "Service ID": "SVC-001", "Object ID": "OBJ-002"},
]

TEMPLATES = [
    {"Document Template ID": "DOC-001", "Title": "Технический паспорт", "Document Type": "technical_passport"},
    {"Document Template ID": "DOC-002", "Title": "Кадастровая справка", "Document Type": "cadastral_extract"},
    {"Document Template ID": "DOC-003", "Title": "Договор", "Document Type": "contract"},
    # DOC-999 intentionally absent -> dangling reference scenario
]


def _doc_row(**overrides):
    row = {
        "Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "1",
        "Business ID": "BIZ-001", "Client ID": "PRS-001", "Object ID": "OBJ-001",
        "Roadmap ID": "RM-001", "Stage ID": "STAGE-001", "Document Template ID": "DOC-001",
        "Document Name": "Test", "Status": "uploaded",
        "Drive File ID": "FILE1", "Drive File URL": "", "File Name": "f.pdf", "Mime Type": "application/pdf",
        "Uploaded At": "", "Uploaded By": "", "Reviewed At": "", "Reviewed By": "",
        "Rejection Reason": "", "Notes": "", "Created At": "", "Updated At": "",
    }
    row.update(overrides)
    return row


def _content_row(**overrides):
    row = {
        "Document ID": "DREG-001", "Drive File ID": "FILE1", "Content Status": "completed",
        "Detected Document Type": "", "Suggested Document Template ID": "", "Template Match Confidence": "",
        "AI Summary": "", "Extracted Fields JSON": "{}", "Text Preview": "", "Language": "",
        "Page Count": "", "Keywords JSON": "[]", "Model": "", "Prompt Version": "", "Content Hash": "",
        "Analysis Started At": "", "Analysis Completed At": "", "Analysis Error": "",
        "Created At": "", "Updated At": "",
    }
    row.update(overrides)
    return row


def _patch_sheets(stages=None, roadmaps=None, templates=None, documents=None, contents=None):
    stages = STAGES if stages is None else stages
    roadmaps = ROADMAPS if roadmaps is None else roadmaps
    templates = TEMPLATES if templates is None else templates
    documents = documents or []
    contents = contents or []

    def _read_business_sheet(sheet_key, *a, **kw):
        return {
            "roadmap_stages": stages,
            "roadmaps": roadmaps,
            "document_template_registry": templates,
            "document_registry": documents,
            "document_content": contents,
        }.get(sheet_key, [])

    def _find_row_by_id(sheet_key, record_id, *a, **kw):
        table = {
            "roadmap_stages": (stages, "Stage ID"),
            "roadmaps": (roadmaps, "Roadmap ID"),
            "document_template_registry": (templates, "Document Template ID"),
            "document_registry": (documents, "Document ID"),
        }.get(sheet_key)
        if table is None:
            return None
        rows, key_field = table
        for i, row in enumerate(rows, start=2):
            if row.get(key_field, "") == record_id:
                return (i, row)
        return None

    return [
        patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet),
        patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id),
    ]


class _PatchedCase(unittest.TestCase):
    def _dr(self, stages=None, roadmaps=None, templates=None, documents=None, contents=None):
        dr = _fresh_dr()
        patches = _patch_sheets(stages=stages, roadmaps=roadmaps, templates=templates,
                                 documents=documents, contents=contents)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        self.addCleanup(stack.close)
        return dr


# ────────────────────────────────────────────────────────────
# Basic requirement discovery
# ────────────────────────────────────────────────────────────

class TestGetRequirementsForStage(_PatchedCase):
    def test_no_requirements_empty_document_template_ids(self):
        dr = self._dr()
        self.assertEqual(dr.get_requirements_for_stage("STAGE-003"), ())

    def test_stage_not_found_returns_empty_not_exception(self):
        dr = self._dr()
        self.assertEqual(dr.get_requirements_for_stage("STAGE-DOES-NOT-EXIST"), ())

    def test_single_requirement_exploded(self):
        dr = self._dr()
        reqs = dr.get_requirements_for_stage("STAGE-001")
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].document_template_id, "DOC-001")
        self.assertEqual(reqs[0].name, "Технический паспорт")
        self.assertEqual(reqs[0].document_type, "technical_passport")

    def test_multiple_requirements_exploded_and_deduped(self):
        dr = self._dr(stages=[
            {"Stage ID": "STAGE-DUP", "Roadmap ID": "RM-001",
             "Document Template IDs": "DOC-002,DOC-003,DOC-002"},
        ])
        reqs = dr.get_requirements_for_stage("STAGE-DUP")
        self.assertEqual([r.document_template_id for r in reqs], ["DOC-002", "DOC-003"])

    def test_scope_chain_resolved_from_registries(self):
        dr = self._dr()
        reqs = dr.get_requirements_for_stage("STAGE-001")
        self.assertEqual(reqs[0].business_id, "BIZ-001")
        self.assertEqual(reqs[0].service_id, "SVC-001")
        self.assertEqual(reqs[0].roadmap_id, "RM-001")
        self.assertEqual(reqs[0].stage_id, "STAGE-001")


class TestScopeResolutionChain(_PatchedCase):
    """stage_id -> roadmap_id -> object_id -> service_id -> business_id,
    resolved from registry relationships only — never trusted from
    caller-supplied assumptions."""

    def test_full_chain_resolves_via_registries(self):
        dr = self._dr()
        chain = dr._resolve_scope_chain(stage_id="STAGE-001")
        self.assertEqual(chain["roadmap_id"], "RM-001")
        self.assertEqual(chain["object_id"], "OBJ-001")
        self.assertEqual(chain["service_id"], "SVC-001")
        self.assertEqual(chain["business_id"], "BIZ-001")

    def test_broken_roadmap_reference_degrades_gracefully_no_crash(self):
        """A stage pointing at a Roadmap ID that doesn't exist must not
        crash and must not match broadly — the chain simply stays empty
        past the break point."""
        dr = self._dr(stages=[
            {"Stage ID": "STAGE-ORPHAN", "Roadmap ID": "RM-DOES-NOT-EXIST", "Document Template IDs": "DOC-001"},
        ])
        chain = dr._resolve_scope_chain(stage_id="STAGE-ORPHAN")
        self.assertEqual(chain["roadmap_id"], "RM-DOES-NOT-EXIST")
        self.assertEqual(chain["business_id"], "")
        self.assertEqual(chain["service_id"], "")
        self.assertEqual(chain["object_id"], "")

        # And the requirement is still produced (not lost), just with an
        # empty scope chain rather than a crash or wrong data.
        reqs = dr.get_requirements_for_stage("STAGE-ORPHAN")
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0].business_id, "")

    def test_nonexistent_stage_is_empty_result_not_error(self):
        """A nonexistent scope must not be confused with a valid scope
        that simply has zero requirements — both currently produce an
        empty/zero result (documented), but this test pins the specific
        nonexistent-stage case explicitly."""
        dr = self._dr()
        summary = dr.evaluate_stage_requirements("STAGE-TOTALLY-UNKNOWN")
        self.assertEqual(summary.items, ())
        self.assertEqual(summary.total_required, 0)
        self.assertTrue(summary.is_complete)
        self.assertEqual(summary.completion_percentage, 100.0)


# ────────────────────────────────────────────────────────────
# Single-requirement evaluation
# ────────────────────────────────────────────────────────────

class TestEvaluateStageRequirements(_PatchedCase):
    def test_one_required_present(self):
        dr = self._dr(documents=[_doc_row()])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.total_required, 1)
        self.assertEqual(summary.satisfied_required, 1)
        self.assertEqual(summary.missing_required, 0)
        self.assertTrue(summary.is_complete)
        self.assertEqual(summary.items[0].status, dr.STATUS_PRESENT)

    def test_one_required_missing(self):
        dr = self._dr(documents=[])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.total_required, 1)
        self.assertEqual(summary.satisfied_required, 0)
        self.assertEqual(summary.missing_required, 1)
        self.assertFalse(summary.is_complete)
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_blocking_missing_counted(self):
        dr = self._dr(documents=[])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.blocking_missing, 1)
        self.assertTrue(summary.items[0].is_blocking)

    def test_unknown_template_id_is_missing_not_silently_discarded(self):
        """An unknown/dangling Document Template ID must NEVER be
        silently dropped from completeness math (that would falsely
        inflate completion) — it must show up as a normal missing
        requirement, with a safe fallback name (the ID itself)."""
        dr = self._dr(stages=[
            {"Stage ID": "STAGE-DANGLING", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-999"},
        ])
        summary = dr.evaluate_stage_requirements("STAGE-DANGLING")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)
        self.assertEqual(summary.items[0].requirement.name, "DOC-999")  # visible fallback
        self.assertEqual(summary.total_required, 1)  # counted, not discarded
        self.assertFalse(summary.is_complete)

    def test_unknown_template_id_can_still_be_satisfied_by_a_matching_document(self):
        """The catalog is display metadata only, never a precondition
        for matching — a document referencing an unknown template ID
        by exact string can still satisfy the requirement."""
        dr = self._dr(
            stages=[{"Stage ID": "STAGE-DANGLING", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-999"}],
            documents=[_doc_row(**{"Stage ID": "STAGE-DANGLING", "Document Template ID": "DOC-999"})],
        )
        summary = dr.evaluate_stage_requirements("STAGE-DANGLING")
        self.assertEqual(summary.items[0].status, dr.STATUS_PRESENT)

    def test_zero_requirement_stage_is_complete_and_100_percent(self):
        dr = self._dr()
        summary = dr.evaluate_stage_requirements("STAGE-003")
        self.assertEqual(summary.total_required, 0)
        self.assertEqual(summary.completion_percentage, 100.0)
        self.assertTrue(summary.is_complete)

    def test_completion_percentage_math(self):
        dr = self._dr(documents=[_doc_row(**{"Stage ID": "STAGE-002", "Document Template ID": "DOC-002"})])
        summary = dr.evaluate_stage_requirements("STAGE-002")
        # DOC-002 present, DOC-003 missing -> 1/2 = 50.0%
        self.assertEqual(summary.total_required, 2)
        self.assertEqual(summary.satisfied_required, 1)
        self.assertEqual(summary.completion_percentage, 50.0)


# ────────────────────────────────────────────────────────────
# Optional / minimum_count — constructed directly, since the current
# data model never produces required=False or minimum_count>1 on its
# own (see module docstring) — these prove the engine's own logic is
# correct and forward-compatible.
# ────────────────────────────────────────────────────────────

class TestOptionalAndMinimumCount(_PatchedCase):
    def test_optional_missing_status(self):
        dr = self._dr(documents=[])
        req = dr.DocumentRequirement(
            requirement_id="STAGE-001:DOC-001", document_template_id="DOC-001",
            stage_id="STAGE-001", required=False,
        )
        result = dr._evaluate_requirement(req)
        self.assertEqual(result.status, dr.STATUS_OPTIONAL_MISSING)
        self.assertFalse(result.is_blocking)  # optional requirements never block

    def test_optional_present_counts_as_present(self):
        dr = self._dr(documents=[_doc_row()])
        req = dr.DocumentRequirement(
            requirement_id="STAGE-001:DOC-001", document_template_id="DOC-001",
            stage_id="STAGE-001", required=False,
        )
        result = dr._evaluate_requirement(req)
        self.assertEqual(result.status, dr.STATUS_PRESENT)

    def test_optional_missing_excluded_from_required_completion_math(self):
        """Optional documents must not reduce required completion %."""
        dr = self._dr(documents=[])
        required_req = dr.DocumentRequirement(
            requirement_id="a", document_template_id="DOC-001", stage_id="STAGE-001", required=True,
        )
        optional_req = dr.DocumentRequirement(
            requirement_id="b", document_template_id="DOC-002", stage_id="STAGE-002", required=False,
        )
        statuses = (dr._evaluate_requirement(required_req), dr._evaluate_requirement(optional_req))
        summary = dr._summarize("stage", "STAGE-001", statuses)
        self.assertEqual(summary.total_required, 1)  # only the required one counts
        self.assertEqual(summary.optional_missing, 1)
        self.assertEqual(summary.completion_percentage, 0.0)  # not dragged by the optional one

    def test_minimum_count_two_partial_with_one_match(self):
        dr = self._dr(documents=[_doc_row()])
        req = dr.DocumentRequirement(
            requirement_id="STAGE-001:DOC-001", document_template_id="DOC-001",
            stage_id="STAGE-001", minimum_count=2,
        )
        result = dr._evaluate_requirement(req)
        self.assertEqual(result.matched_count, 1)
        self.assertEqual(result.status, dr.STATUS_PARTIAL)
        self.assertFalse(result.is_satisfied)

    def test_minimum_count_two_present_with_two_independent_matches(self):
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-002"}),
        ])
        req = dr.DocumentRequirement(
            requirement_id="STAGE-001:DOC-001", document_template_id="DOC-001",
            stage_id="STAGE-001", minimum_count=2,
        )
        result = dr._evaluate_requirement(req)
        self.assertEqual(result.matched_count, 2)
        self.assertEqual(result.status, dr.STATUS_PRESENT)
        self.assertTrue(result.is_satisfied)


# ────────────────────────────────────────────────────────────
# Matching rules: authoritative template only, wrong scope excluded
# ────────────────────────────────────────────────────────────

class TestMatchingRules(_PatchedCase):
    def test_ai_suggested_template_does_not_count(self):
        """The document's own DOCUMENT_REGISTRY 'Document Template ID' is
        empty (never registered against this template); a DOCUMENT_CONTENT
        row merely *suggesting* this template must never satisfy it."""
        dr = self._dr(
            documents=[_doc_row(**{"Document Template ID": ""})],
            contents=[_content_row(**{"Suggested Document Template ID": "DOC-001"})],
        )
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_engine_never_reads_document_content_at_all(self):
        """Structural guarantee: the AI-suggestion field lives only in
        DOCUMENT_CONTENT, which this engine must never even query."""
        import inspect
        dr = _fresh_dr()
        source = inspect.getsource(dr)
        self.assertNotIn("document_content", source)
        self.assertNotIn("Suggested Document Template ID", source)
        self.assertNotIn("document_intelligence", source)
        self.assertNotIn("document_query", source)

    def test_wrong_stage_document_does_not_count(self):
        dr = self._dr(documents=[_doc_row(**{"Stage ID": "STAGE-002"})])  # right template, wrong stage
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_wrong_roadmap_document_does_not_count(self):
        # STAGE-999 belongs to RM-002; a document registered against
        # STAGE-001 (RM-001) must not satisfy STAGE-999's requirement,
        # even though both reference DOC-001.
        dr = self._dr(documents=[_doc_row(**{"Stage ID": "STAGE-001"})])
        summary = dr.evaluate_stage_requirements("STAGE-999")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_document_with_no_stage_id_does_not_count(self):
        dr = self._dr(documents=[_doc_row(**{"Stage ID": ""})])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_uploaded_status_counts(self):
        dr = self._dr(documents=[_doc_row(**{"Status": "uploaded"})])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_PRESENT)

    def test_archived_status_does_not_count(self):
        dr = self._dr(documents=[_doc_row(**{"Status": "archived"})])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_rejected_status_does_not_count(self):
        dr = self._dr(documents=[_doc_row(**{"Status": "rejected"})])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_blank_status_does_not_count(self):
        dr = self._dr(documents=[_doc_row(**{"Status": ""})])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)


# ────────────────────────────────────────────────────────────
# Versioning and duplicates
# ────────────────────────────────────────────────────────────

class TestVersioningAndDuplicates(_PatchedCase):
    def test_multiple_versions_in_one_family_count_once(self):
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "1"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-001", "Version": "2"}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].matched_count, 1)  # not 2 — same family
        self.assertEqual(summary.items[0].status, dr.STATUS_PRESENT)

    def test_superseded_version_excluded_higher_version_wins(self):
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "1"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-001", "Version": "2"}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].matched_document_ids, ("DREG-002",))  # only the newer one

    def test_duplicate_independent_families_both_count(self):
        """Two genuinely independent uploads (different Document Family
        ID) both satisfying the same requirement is real evidence, not
        inflation — both must count."""
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-002"}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].matched_count, 2)

    def test_missing_family_id_treated_as_singleton_not_merged(self):
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": ""}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": ""}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].matched_count, 2)  # two distinct singleton "families"

    def test_newest_version_not_uploaded_older_uploaded_version_does_not_satisfy(self):
        """If the newest version in a family is (e.g.) archived, an
        older 'uploaded' version in the SAME family must not satisfy
        the requirement — the family's current version is what counts,
        and it isn't in a satisfying status."""
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001",
                        "Version": "1", "Status": "uploaded"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-001",
                        "Version": "2", "Status": "archived"}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        self.assertEqual(summary.items[0].matched_count, 0)
        self.assertEqual(summary.items[0].status, dr.STATUS_MISSING)

    def test_malformed_version_does_not_crash_and_is_deprioritized(self):
        dr = self._dr(documents=[
            _doc_row(**{"Document ID": "DREG-001", "Document Family ID": "DFAM-001", "Version": "not-a-number"}),
            _doc_row(**{"Document ID": "DREG-002", "Document Family ID": "DFAM-001", "Version": "2"}),
        ])
        summary = dr.evaluate_stage_requirements("STAGE-001")  # must not raise
        self.assertEqual(summary.items[0].matched_document_ids, ("DREG-002",))

    def test_blank_version_does_not_crash(self):
        dr = self._dr(documents=[_doc_row(**{"Version": ""})])
        summary = dr.evaluate_stage_requirements("STAGE-001")  # must not raise
        self.assertEqual(summary.items[0].status, dr.STATUS_PRESENT)


class TestParseIdList(_PatchedCase):
    def test_trims_whitespace(self):
        dr = self._dr(stages=[
            {"Stage ID": "STAGE-WS", "Roadmap ID": "RM-001", "Document Template IDs": " DOC-001 , DOC-002 "},
        ])
        self.assertEqual(dr._parse_id_list(" DOC-001 , DOC-002 "), ["DOC-001", "DOC-002"])

    def test_removes_empty_entries(self):
        dr = self._dr()
        self.assertEqual(dr._parse_id_list("DOC-001,,DOC-002,"), ["DOC-001", "DOC-002"])

    def test_deduplicates_preserving_order(self):
        dr = self._dr()
        self.assertEqual(dr._parse_id_list("DOC-002,DOC-001,DOC-002"), ["DOC-002", "DOC-001"])

    def test_blank_field_returns_empty_list(self):
        dr = self._dr()
        self.assertEqual(dr._parse_id_list(""), [])
        self.assertEqual(dr._parse_id_list(None), [])


# ────────────────────────────────────────────────────────────
# Aggregation: roadmap / object
# ────────────────────────────────────────────────────────────

class TestRoadmapAndObjectAggregation(_PatchedCase):
    def test_roadmap_aggregate_sums_all_stages(self):
        dr = self._dr(documents=[
            _doc_row(**{"Stage ID": "STAGE-001", "Document Template ID": "DOC-001"}),
            _doc_row(**{"Document ID": "DREG-002", "Stage ID": "STAGE-002", "Document Template ID": "DOC-002"}),
        ])
        summary = dr.evaluate_roadmap_requirements("RM-001")
        # STAGE-001: DOC-001 present; STAGE-002: DOC-002 present, DOC-003 missing; STAGE-003: none
        self.assertEqual(summary.total_required, 3)
        self.assertEqual(summary.satisfied_required, 2)
        self.assertEqual(summary.missing_required, 1)
        self.assertFalse(summary.is_complete)

    def test_roadmap_not_found_or_no_stages_is_empty(self):
        dr = self._dr(stages=[])
        summary = dr.evaluate_roadmap_requirements("RM-001")
        self.assertEqual(summary.total_required, 0)
        self.assertTrue(summary.is_complete)

    def test_object_aggregate_via_roadmap(self):
        dr = self._dr(documents=[
            _doc_row(**{"Stage ID": "STAGE-001", "Document Template ID": "DOC-001"}),
        ])
        summary = dr.evaluate_object_requirements("OBJ-001")
        self.assertEqual(summary.total_required, 3)
        self.assertEqual(summary.satisfied_required, 1)

    def test_object_with_no_roadmap_is_empty(self):
        dr = self._dr()
        summary = dr.evaluate_object_requirements("OBJ-NONEXISTENT")
        self.assertEqual(summary.total_required, 0)
        self.assertTrue(summary.is_complete)


# ────────────────────────────────────────────────────────────
# Read-only guarantees
# ────────────────────────────────────────────────────────────

class TestReadOnlyGuarantees(_PatchedCase):
    def test_no_sheets_writes_across_all_public_functions(self):
        with patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.update_business_row") as mock_update_row, \
             patch("business_core.sheets.update_business_cell") as mock_update_cell:
            dr = self._dr(documents=[_doc_row()])
            dr.get_requirements_for_stage("STAGE-001")
            dr.evaluate_stage_requirements("STAGE-001")
            dr.get_requirements_for_roadmap("RM-001")
            dr.evaluate_roadmap_requirements("RM-001")
            dr.get_requirements_for_object("OBJ-001")
            dr.evaluate_object_requirements("OBJ-001")
            mock_append.assert_not_called()
            mock_update_row.assert_not_called()
            mock_update_cell.assert_not_called()

    def test_no_drive_access(self):
        with patch("integrations.google_drive_adapter.get_drive_service") as mock_service:
            dr = self._dr(documents=[_doc_row()])
            dr.evaluate_stage_requirements("STAGE-001")
            mock_service.assert_not_called()

    def test_no_anthropic_reference_anywhere_in_module(self):
        import inspect
        dr = _fresh_dr()
        source = inspect.getsource(dr)
        self.assertNotIn("anthropic", source.lower())

    def test_module_never_enqueues_a_job(self):
        # Check actual call patterns, not the word "enqueue" alone — the
        # module's own docstring legitimately says "never enqueues a job".
        import inspect
        dr = _fresh_dr()
        source = inspect.getsource(dr)
        self.assertNotIn("job_queue", source)
        self.assertNotIn("_enqueue_document_analysis(", source)
        self.assertNotIn("run_once(", source)

    def test_result_objects_are_immutable(self):
        dr = self._dr(documents=[_doc_row()])
        summary = dr.evaluate_stage_requirements("STAGE-001")
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            summary.is_complete = False
        with self.assertRaises(FrozenInstanceError):
            summary.items[0].status = "tampered"


# ────────────────────────────────────────────────────────────
# Phase 17B: business_core/document_requirements_query.py
# ────────────────────────────────────────────────────────────

class TestDocumentRequirementsQuery(_PatchedCase):
    def test_scope_exists_stage(self):
        drq = _fresh_drq()
        with contextlib.ExitStack() as stack:
            for p in _patch_sheets():
                stack.enter_context(p)
            self.assertTrue(drq.scope_exists("stage", "STAGE-001"))
            self.assertFalse(drq.scope_exists("stage", "STAGE-NOPE"))

    def test_scope_exists_roadmap(self):
        drq = _fresh_drq()
        with contextlib.ExitStack() as stack:
            for p in _patch_sheets():
                stack.enter_context(p)
            self.assertTrue(drq.scope_exists("roadmap", "RM-001"))
            self.assertFalse(drq.scope_exists("roadmap", "RM-NOPE"))

    def test_scope_exists_object(self):
        drq = _fresh_drq()
        objects = [{"OBJ ID": "OBJ-001", "Client ID": "PRS-001", "Biz ID": "BIZ-001"}]

        def _find(sheet_key, record_id, *a, **kw):
            if sheet_key == "object_registry":
                for row in objects:
                    if row.get("OBJ ID") == record_id:
                        return (2, row)
                return None
            return None

        with patch("business_core.sheets.find_row_by_id", side_effect=_find):
            self.assertTrue(drq.scope_exists("object", "OBJ-001"))
            self.assertFalse(drq.scope_exists("object", "OBJ-NOPE"))

    def test_evaluate_scope_not_found(self):
        drq = _fresh_drq()
        with contextlib.ExitStack() as stack:
            for p in _patch_sheets():
                stack.enter_context(p)
            result = drq.evaluate_scope("stage", "STAGE-NOPE")
        self.assertFalse(result.exists)
        self.assertIsNone(result.summary)

    def test_evaluate_scope_found_calls_engine(self):
        drq = _fresh_drq()
        with contextlib.ExitStack() as stack:
            for p in _patch_sheets(documents=[_doc_row()]):
                stack.enter_context(p)
            result = drq.evaluate_scope("stage", "STAGE-001")
        self.assertTrue(result.exists)
        self.assertEqual(result.summary.total_required, 1)
        self.assertEqual(result.summary.satisfied_required, 1)

    def test_evaluate_scope_found_zero_requirements(self):
        drq = _fresh_drq()
        with contextlib.ExitStack() as stack:
            for p in _patch_sheets():
                stack.enter_context(p)
            result = drq.evaluate_scope("stage", "STAGE-003")  # empty Document Template IDs
        self.assertTrue(result.exists)
        self.assertEqual(result.summary.items, ())

    def test_unknown_scope_type_is_treated_as_not_found(self):
        drq = _fresh_drq()
        result = drq.evaluate_scope("service", "SVC-001")
        self.assertFalse(result.exists)


# ────────────────────────────────────────────────────────────
# Phase 17B: Telegram handlers — /missingdocs, /docsrequired
# ────────────────────────────────────────────────────────────

def _req17b(**overrides):
    dr = _fresh_dr()
    defaults = dict(
        requirement_id="STAGE-001:DOC-001", document_template_id="DOC-001",
        document_type="technical_passport", name="Технический паспорт",
        scope_type="stage", scope_id="STAGE-001", business_id="BIZ-001",
        service_id="SVC-001", roadmap_id="RM-001", stage_id="STAGE-001",
        required=True, blocking=True, minimum_count=1,
    )
    defaults.update(overrides)
    return dr.DocumentRequirement(**defaults)


def _status17b(requirement=None, **overrides):
    dr = _fresh_dr()
    requirement = requirement if requirement is not None else _req17b()
    defaults = dict(requirement=requirement, matched_document_ids=(), matched_count=0, status=dr.STATUS_MISSING)
    defaults.update(overrides)
    return dr.DocumentRequirementStatus(**defaults)


def _summary17b(items=(), **overrides):
    dr = _fresh_dr()
    items = tuple(items)
    total_required = sum(1 for i in items if i.requirement.required)
    satisfied = sum(1 for i in items if i.is_satisfied)
    missing = sum(1 for i in items if i.status in ("missing", "partial"))
    blocking = sum(1 for i in items if i.is_blocking)
    optional_missing = sum(1 for i in items if i.status == "optional_missing")
    completion = 100.0 if total_required == 0 else round(satisfied / total_required * 100, 2)
    defaults = dict(
        scope_type="stage", scope_id="STAGE-001", items=items,
        total_required=total_required, satisfied_required=satisfied,
        missing_required=missing, blocking_missing=blocking, optional_missing=optional_missing,
        completion_percentage=completion, is_complete=(missing == 0 and blocking == 0),
    )
    defaults.update(overrides)
    return dr.RequirementsSummary(**defaults)


def _scope_result17b(exists=True, summary=None, scope_type="stage", scope_id="STAGE-001"):
    drq = _fresh_drq()
    return drq.ScopeEvaluationResult(scope_type=scope_type, scope_id=scope_id, exists=exists, summary=summary)


def _upd17b(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _cmd17b(cmdline: str):
    update = _upd17b(cmdline)
    context = MagicMock()
    context.args = cmdline.split()[1:]
    context.user_data = {}
    return update, context


class TestParseScopeArgs(unittest.TestCase):
    def test_single_stage_id_ok(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("stage_id=STAGE-001")
        self.assertEqual((scope_type, scope_id, error), ("stage", "STAGE-001", None))

    def test_single_roadmap_id_ok(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("roadmap_id=RM-001")
        self.assertEqual((scope_type, scope_id, error), ("roadmap", "RM-001", None))

    def test_single_object_id_ok(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("object_id=OBJ-001")
        self.assertEqual((scope_type, scope_id, error), ("object", "OBJ-001", None))

    def test_no_scope_rejected(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("")
        self.assertIsNone(scope_type)
        self.assertIsNotNone(error)

    def test_multiple_scopes_rejected(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("stage_id=STAGE-001 roadmap_id=RM-001")
        self.assertIsNone(scope_type)
        self.assertIn("ОДИН", error)

    def test_unknown_argument_rejected(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("business_id=BIZ-001")
        self.assertIsNone(scope_type)
        self.assertIn("Неизвестный аргумент", error)

    def test_blank_value_rejected(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args('stage_id=""')
        self.assertIsNone(scope_type)
        self.assertIn("Пустое значение", error)

    def test_malformed_positional_token_rejected(self):
        th = _fresh_th()
        scope_type, scope_id, error = th._parse_scope_args("garbage-token")
        self.assertIsNone(scope_type)
        self.assertIsNotNone(error)


class TestMissingDocsCmd(unittest.TestCase):
    def _run(self, cmdline, result):
        th = _fresh_th()
        update, context = _cmd17b(cmdline)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.document_requirements_query.evaluate_scope", return_value=result):
                await th.missingdocs_cmd(update, context)

        asyncio.run(run())
        return update, context

    def test_no_scope_argument(self):
        th = _fresh_th()
        update, context = _cmd17b("/missingdocs")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.missingdocs_cmd(update, context)

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertIsNone(update.message.reply_text.call_args.kwargs.get("parse_mode"))

    def test_nonexistent_stage(self):
        update, context = self._run(
            "/missingdocs stage_id=STAGE-999",
            _scope_result17b(exists=False, scope_type="stage", scope_id="STAGE-999"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Этап STAGE-999 не найден", reply)

    def test_nonexistent_roadmap(self):
        update, context = self._run(
            "/missingdocs roadmap_id=RM-999",
            _scope_result17b(exists=False, scope_type="roadmap", scope_id="RM-999"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Дорожная карта RM-999 не найдена", reply)

    def test_nonexistent_object(self):
        update, context = self._run(
            "/missingdocs object_id=OBJ-999",
            _scope_result17b(exists=False, scope_type="object", scope_id="OBJ-999"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Объект OBJ-999 не найден", reply)

    def test_zero_configured_stage(self):
        update, context = self._run(
            "/missingdocs stage_id=STAGE-003",
            _scope_result17b(summary=_summary17b(items=(), scope_id="STAGE-003"),
                              scope_type="stage", scope_id="STAGE-003"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("ещё не настроены структурированные требования", reply)
        self.assertNotIn("100", reply)  # never shown as "100% complete" in the primary message

    def test_zero_configured_roadmap_message(self):
        update, context = self._run(
            "/missingdocs roadmap_id=RM-003",
            _scope_result17b(summary=_summary17b(items=(), scope_type="roadmap", scope_id="RM-003"),
                              scope_type="roadmap", scope_id="RM-003"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("В этапах этой дорожной карты", reply)

    def test_zero_configured_object_message(self):
        update, context = self._run(
            "/missingdocs object_id=OBJ-003",
            _scope_result17b(summary=_summary17b(items=(), scope_type="object", scope_id="OBJ-003"),
                              scope_type="object", scope_id="OBJ-003"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("В дорожных картах этого объекта", reply)

    def test_all_satisfied(self):
        req = _req17b()
        status = _status17b(req, status="present", matched_document_ids=("DREG-001",), matched_count=1)
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Все обязательные документы собраны.", reply)
        self.assertIn("Required total: 1", reply)
        self.assertIn("Satisfied: 1", reply)

    def test_one_missing_requirement_listed(self):
        req = _req17b()
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("❌ Не хватает обязательных документов", reply)
        self.assertIn("Document Template ID: DOC-001", reply)
        self.assertIn("Name: Технический паспорт", reply)
        self.assertIn("Stage ID: STAGE-001", reply)
        self.assertIn("Matched count / Minimum count: 0/1", reply)
        self.assertIn("Status: отсутствует", reply)
        self.assertIn("Blocking: yes", reply)

    def test_blocking_missing_shown(self):
        req = _req17b(blocking=True)
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Blocking missing: 1", reply)

    def test_partial_minimum_count(self):
        req = _req17b(minimum_count=2)
        status = _status17b(req, status="partial", matched_document_ids=("DREG-001",), matched_count=1)
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Status: частично", reply)
        self.assertIn("Matched count / Minimum count: 1/2", reply)

    def test_unknown_template_id_visible(self):
        req = _req17b(document_template_id="DOC-999", name="DOC-999")  # engine's own fallback: name==id
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("[неизвестный шаблон: DOC-999]", reply)

    def test_parse_mode_none_on_every_branch(self):
        scenarios = [
            _scope_result17b(exists=False),
            _scope_result17b(summary=_summary17b(items=())),
            _scope_result17b(summary=_summary17b(items=(_status17b(status="present", matched_count=1,
                                                                     matched_document_ids=("D1",)),))),
            _scope_result17b(summary=_summary17b(items=(_status17b(status="missing"),))),
        ]
        for result in scenarios:
            update, context = self._run("/missingdocs stage_id=STAGE-001", result)
            call = update.message.reply_text.call_args
            self.assertIsNone(call.kwargs.get("parse_mode"))

    def test_underscores_preserved(self):
        req = _req17b(name="test_document_name", document_template_id="DOC_001")
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,))
        update, context = self._run("/missingdocs stage_id=STAGE-001",
                                     _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("test_document_name", reply)
        self.assertIn("DOC_001", reply)


class TestDocsRequiredCmd(unittest.TestCase):
    def _run(self, cmdline, result):
        th = _fresh_th()
        update, context = _cmd17b(cmdline)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.document_requirements_query.evaluate_scope", return_value=result):
                await th.docsrequired_cmd(update, context)

        asyncio.run(run())
        return update, context

    def test_stage_scope(self):
        req = _req17b()
        status = _status17b(req, status="present", matched_document_ids=("DREG-001",), matched_count=1)
        summary = _summary17b(items=(status,))
        update, context = self._run("/docsrequired stage_id=STAGE-001", _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("📋 Требования к документам", reply)
        self.assertIn("Stage ID: STAGE-001", reply)
        self.assertIn("Complete: yes", reply)

    def test_roadmap_scope(self):
        req = _req17b(scope_type="roadmap")
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,), scope_type="roadmap", scope_id="RM-001")
        update, context = self._run(
            "/docsrequired roadmap_id=RM-001",
            _scope_result17b(summary=summary, scope_type="roadmap", scope_id="RM-001"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Roadmap ID: RM-001", reply)
        self.assertIn("Complete: no", reply)

    def test_object_scope(self):
        req = _req17b()
        status = _status17b(req, status="present", matched_document_ids=("DREG-001",), matched_count=1)
        summary = _summary17b(items=(status,), scope_type="object", scope_id="OBJ-001")
        update, context = self._run(
            "/docsrequired object_id=OBJ-001",
            _scope_result17b(summary=summary, scope_type="object", scope_id="OBJ-001"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Object ID: OBJ-001", reply)

    def test_full_card_shows_matched_document_ids(self):
        req = _req17b()
        status = _status17b(req, status="present", matched_document_ids=("DREG-001", "DREG-002"), matched_count=2)
        summary = _summary17b(items=(status,))
        update, context = self._run("/docsrequired stage_id=STAGE-001", _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Matched Document IDs: DREG-001, DREG-002", reply)

    def test_full_card_shows_every_requirement_not_just_missing(self):
        present_status = _status17b(_req17b(document_template_id="DOC-001"), status="present",
                                      matched_document_ids=("DREG-001",), matched_count=1)
        missing_status = _status17b(_req17b(document_template_id="DOC-002", name="Другой документ"),
                                      status="missing")
        summary = _summary17b(items=(present_status, missing_status))
        update, context = self._run("/docsrequired stage_id=STAGE-001", _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-001", reply)
        self.assertIn("DOC-002", reply)
        self.assertIn("Другой документ", reply)

    def test_required_and_blocking_flags_shown(self):
        req = _req17b(required=True, blocking=True)
        status = _status17b(req, status="missing")
        summary = _summary17b(items=(status,))
        update, context = self._run("/docsrequired stage_id=STAGE-001", _scope_result17b(summary=summary))
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Required: yes", reply)
        self.assertIn("Blocking: yes", reply)

    def test_status_labels_exact_russian(self):
        th = _fresh_th()
        self.assertEqual(th._STATUS_LABELS_RU["present"], "присутствует")
        self.assertEqual(th._STATUS_LABELS_RU["missing"], "отсутствует")
        self.assertEqual(th._STATUS_LABELS_RU["partial"], "частично")
        self.assertEqual(th._STATUS_LABELS_RU["optional_missing"], "необязательный отсутствует")
        self.assertEqual(th._STATUS_LABELS_RU["not_applicable"], "не применяется")

    def test_zero_configured_never_says_100_percent(self):
        update, context = self._run(
            "/docsrequired stage_id=STAGE-003",
            _scope_result17b(summary=_summary17b(items=())),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("ещё не настроены структурированные требования", reply)
        self.assertNotIn("100", reply)

    def test_nonexistent_scope(self):
        update, context = self._run(
            "/docsrequired stage_id=STAGE-999",
            _scope_result17b(exists=False, scope_id="STAGE-999"),
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Этап STAGE-999 не найден", reply)

    def test_long_output_splits_safely(self):
        statuses = tuple(
            _status17b(_req17b(document_template_id=f"DOC-{i:03d}", name=f"Document number {i} with padding text"),
                       status="missing")
            for i in range(200)
        )
        summary = _summary17b(items=statuses)
        update, context = self._run("/docsrequired stage_id=STAGE-001", _scope_result17b(summary=summary))
        self.assertGreater(update.message.reply_text.call_count, 1)
        for call in update.message.reply_text.call_args_list:
            self.assertIsNone(call.kwargs.get("parse_mode"))
        # no line split in half: every "Document Template ID: DOC-xxx" line
        # must appear whole in exactly one message part
        all_text = "\n".join(c.args[0] for c in update.message.reply_text.call_args_list)
        for i in range(200):
            self.assertIn(f"Document Template ID: DOC-{i:03d}", all_text)


class TestSplitMessageByLines(unittest.TestCase):
    """Phase 17B review fix: a single line longer than max_len must never
    pass through unchanged — it must be deterministically chunked."""

    def test_normal_lines_untouched(self):
        th = _fresh_th()
        text = "line one\nline two\nline three"
        parts = th._split_message_by_lines(text, max_len=100)
        self.assertEqual(parts, [text])

    def test_splits_between_lines_when_over_limit(self):
        th = _fresh_th()
        text = "\n".join(f"line {i}" for i in range(50))
        parts = th._split_message_by_lines(text, max_len=50)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 50)
        # every original line must appear whole in exactly one part
        rejoined = "\n".join(parts)
        for i in range(50):
            self.assertIn(f"line {i}", rejoined)

    def test_never_splits_mid_line_for_normal_sized_lines(self):
        th = _fresh_th()
        lines = [f"field_{i}: value_{i}" for i in range(30)]
        text = "\n".join(lines)
        parts = th._split_message_by_lines(text, max_len=60)
        for line in lines:
            found_whole = any(line in part.split("\n") for part in parts)
            self.assertTrue(found_whole, f"line was split or lost: {line!r}")

    def test_oversized_single_line_is_chunked_not_passed_through(self):
        th = _fresh_th()
        huge_line = "DREG-" + ("X" * 9000)  # single field line far exceeding max_len
        parts = th._split_message_by_lines(huge_line, max_len=4000)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 4000)
        self.assertEqual("".join(parts), huge_line)  # no content lost

    def test_oversized_line_mixed_with_normal_lines_preserves_all_content(self):
        th = _fresh_th()
        huge_line = "Matched Document IDs: " + ", ".join(f"DREG-{i:04d}" for i in range(2000))
        text = "\n".join(["normal line before", huge_line, "normal line after"])
        parts = th._split_message_by_lines(text, max_len=4000)
        for part in parts:
            self.assertLessEqual(len(part), 4000)
        rejoined = "".join(parts)
        self.assertIn("normal line before", rejoined)
        self.assertIn("normal line after", rejoined)
        self.assertIn("DREG-0000", rejoined)
        self.assertIn("DREG-1999", rejoined)

    def test_unicode_preserved_across_chunk_boundary(self):
        th = _fresh_th()
        huge_line = "Кадастровый номер: " + ("Технический паспорт объекта " * 300)
        parts = th._split_message_by_lines(huge_line, max_len=500)
        self.assertGreater(len(parts), 1)
        rejoined = "".join(parts)
        self.assertEqual(rejoined, huge_line)
        # every character survives round-trip decoding (no split mid-codepoint)
        for part in parts:
            part.encode("utf-8")  # would not raise regardless, but proves valid str

    def test_underscores_and_ids_preserved_in_oversized_line(self):
        th = _fresh_th()
        huge_line = "Extracted Fields: " + ", ".join(f"field_{i}_value" for i in range(1000))
        parts = th._split_message_by_lines(huge_line, max_len=1000)
        rejoined = "".join(parts)
        self.assertEqual(rejoined, huge_line)
        self.assertIn("field_0_value", rejoined)
        self.assertIn("field_999_value", rejoined)

    def test_no_empty_parts_for_empty_text(self):
        th = _fresh_th()
        self.assertEqual(th._split_message_by_lines("", max_len=100), [""])


class TestPhase17BReadOnlyGuarantees(unittest.TestCase):
    def test_no_sheets_writes(self):
        th = _fresh_th()
        update, context = _cmd17b("/missingdocs stage_id=STAGE-001")
        summary = _summary17b(items=(_status17b(status="missing"),))

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.document_requirements_query.evaluate_scope",
                       return_value=_scope_result17b(summary=summary)), \
                 patch("business_core.sheets.append_business_row") as mock_append, \
                 patch("business_core.sheets.update_business_row") as mock_update_row, \
                 patch("business_core.sheets.update_business_cell") as mock_update_cell:
                await th.missingdocs_cmd(update, context)
                mock_append.assert_not_called()
                mock_update_row.assert_not_called()
                mock_update_cell.assert_not_called()

        asyncio.run(run())

    def test_no_drive_or_anthropic_reference_in_handlers(self):
        th = _fresh_th()
        import inspect
        for fn in (th.missingdocs_cmd, th.docsrequired_cmd):
            source = inspect.getsource(fn)
            self.assertNotIn("get_drive_service", source)
            self.assertNotIn("anthropic", source.lower())
            self.assertNotIn("analyze_document(", source)

    def test_no_requirement_engine_mutation(self):
        """Handlers must never call any business_core.document_requirements
        write-shaped function — there are none (the engine is entirely
        read-only), but this pins that no future accidental import of a
        write primitive creeps in."""
        th = _fresh_th()
        import inspect
        for fn in (th.missingdocs_cmd, th.docsrequired_cmd):
            source = inspect.getsource(fn)
            self.assertNotIn("append_business_row", source)
            self.assertNotIn("update_business_row", source)
            self.assertNotIn("update_business_cell", source)

    def test_handlers_do_not_read_document_registry_directly(self):
        """Handlers must go through document_requirements_query, not
        touch find_row_by_id/read_business_sheet themselves."""
        th = _fresh_th()
        import inspect
        for fn in (th.missingdocs_cmd, th.docsrequired_cmd):
            source = inspect.getsource(fn)
            self.assertNotIn("find_row_by_id", source)
            self.assertNotIn("read_business_sheet", source)

    def test_commands_registered(self):
        th = _fresh_th()
        app = MagicMock()
        th.register_business_handlers(app)
        self.assertGreater(app.add_handler.call_count, 20)
        self.assertTrue(hasattr(th, "missingdocs_cmd"))
        self.assertTrue(hasattr(th, "docsrequired_cmd"))


if __name__ == "__main__":
    unittest.main()
