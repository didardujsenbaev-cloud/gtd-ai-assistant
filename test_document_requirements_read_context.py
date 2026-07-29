"""
Phase 16C.1B1: Requirements Engine Bulk Read Context.

Covers: RequirementsReadContext equivalence (internal auto-created vs.
externally supplied vs. partially preloaded context all produce
byte-identical results to the pre-refactor engine), and Sheets
call-count guarantees (each distinct sheet read at most once per
top-level evaluation, regardless of stage/requirement/roadmap count).

All tests fully mock business_core.sheets — no live network calls.
Does not delete modules from sys.modules (avoids the documented
test-isolation artifact from prior phases) and does not touch .env.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import business_core.document_requirements as dr


def _stage_row(stage_id, roadmap_id, template_ids):
    return {"Stage ID": stage_id, "Roadmap ID": roadmap_id, "Document Template IDs": ",".join(template_ids)}


def _roadmap_row(roadmap_id, object_id="OBJ-001"):
    return {"Roadmap ID": roadmap_id, "Business ID": "BIZ-001", "Service ID": "SVC-001", "Object ID": object_id}


def _template_row(template_id):
    return {"Document Template ID": template_id, "Title": template_id, "Document Type": "generic"}


def _doc_row(document_id, roadmap_id, template_id, stage_id="", family_id=None, version="1", status="uploaded"):
    return {
        "Document ID": document_id, "Document Family ID": family_id or f"FAM-{document_id}",
        "Version": version, "Business ID": "BIZ-001", "Client ID": "PRS-001",
        "Object ID": "OBJ-001", "Roadmap ID": roadmap_id, "Stage ID": stage_id,
        "Document Template ID": template_id, "Document Name": "Test", "Status": status,
    }


class _SpySheets:
    """Backs both business_core.sheets.read_business_sheet() and
    find_row_by_id() from one shared row-set — records every call so
    tests can assert exact per-sheet read counts."""

    def __init__(self, stages=(), roadmaps=(), templates=(), documents=(), relations=()):
        self.stages = list(stages)
        self.roadmaps = list(roadmaps)
        self.templates = list(templates)
        self.documents = list(documents)
        self.relations = list(relations)
        self.read_calls: list = []
        self.find_calls: list = []

    def _table(self, sheet_key):
        return {
            "roadmap_stages": self.stages,
            "roadmaps": self.roadmaps,
            "document_template_registry": self.templates,
            "document_registry": self.documents,
            "stage_entity_relations": self.relations,
        }.get(sheet_key, [])

    def read_business_sheet(self, sheet_key, *a, **kw):
        self.read_calls.append(sheet_key)
        return self._table(sheet_key)

    def find_row_by_id(self, sheet_key, record_id, *a, **kw):
        self.find_calls.append(sheet_key)
        key_field = {
            "roadmap_stages": "Stage ID", "roadmaps": "Roadmap ID",
            "document_template_registry": "Document Template ID", "document_registry": "Document ID",
        }.get(sheet_key)
        if key_field is None:
            return None
        for i, row in enumerate(self._table(sheet_key), start=2):
            if row.get(key_field, "") == record_id:
                return (i, row)
        return None


def _patched(spy):
    return (
        patch("business_core.sheets.read_business_sheet", side_effect=spy.read_business_sheet),
        patch("business_core.sheets.find_row_by_id", side_effect=spy.find_row_by_id),
    )


class _Patched(unittest.TestCase):
    def _run(self, spy, fn, *args, **kwargs):
        p1, p2 = _patched(spy)
        with p1, p2:
            return fn(*args, **kwargs)


def _linear_fixture(num_templates: int):
    """One stage, one roadmap, `num_templates` requirements, all
    unmatched (no documents) — for Q-scaling read-count tests."""
    template_ids = [f"DOC-{i}" for i in range(num_templates)]
    stages = [_stage_row("STAGE-1", "RM-1", template_ids)]
    roadmaps = [_roadmap_row("RM-1")]
    templates = [_template_row(t) for t in template_ids]
    return _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=[])


def _roadmap_fixture(num_stages: int, reqs_per_stage: int):
    """One roadmap with `num_stages` stages, each with `reqs_per_stage`
    unique requirements — for S/Q-scaling read-count tests."""
    stages = []
    templates = []
    template_counter = 0
    for s in range(num_stages):
        stage_template_ids = []
        for _ in range(reqs_per_stage):
            tid = f"DOC-{template_counter}"
            template_counter += 1
            stage_template_ids.append(tid)
            templates.append(_template_row(tid))
        stages.append(_stage_row(f"STAGE-{s}", "RM-1", stage_template_ids))
    roadmaps = [_roadmap_row("RM-1")]
    return _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=[])


def _object_fixture(num_roadmaps: int, stages_per_roadmap: int, reqs_per_stage: int):
    stages = []
    roadmaps = []
    templates = []
    template_counter = 0
    for r in range(num_roadmaps):
        rid = f"RM-{r}"
        roadmaps.append(_roadmap_row(rid, object_id="OBJ-1"))
        for s in range(stages_per_roadmap):
            stage_template_ids = []
            for _ in range(reqs_per_stage):
                tid = f"DOC-{template_counter}"
                template_counter += 1
                stage_template_ids.append(tid)
                templates.append(_template_row(tid))
            stages.append(_stage_row(f"STAGE-{r}-{s}", rid, stage_template_ids))
    return _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=[])


# ────────────────────────────────────────────────────────────
# Equivalence: internal auto-created vs. externally supplied vs.
# partially preloaded context all produce identical results.
# ────────────────────────────────────────────────────────────

class TestContextEquivalence(_Patched):
    def test_stage_evaluation_identical_with_and_without_explicit_context(self):
        spy = _linear_fixture(3)
        result_none = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")

        spy2 = _linear_fixture(3)
        explicit_ctx = dr.RequirementsReadContext()
        result_explicit = self._run(spy2, dr.evaluate_stage_requirements, "STAGE-1", read_context=explicit_ctx)

        self.assertEqual(result_none.total_required, result_explicit.total_required)
        self.assertEqual(
            [i.requirement.document_template_id for i in result_none.items],
            [i.requirement.document_template_id for i in result_explicit.items],
        )
        self.assertEqual(result_none.blocking_missing, result_explicit.blocking_missing)
        self.assertEqual(result_none.is_complete, result_explicit.is_complete)

    def test_partially_preloaded_context_still_produces_correct_result(self):
        """A context that already has roadmap_stages cached (e.g. from
        an unrelated earlier lookup) must still resolve the rest lazily
        and produce an identical result."""
        spy = _linear_fixture(2)
        p1, p2 = _patched(spy)
        with p1, p2:
            preloaded_ctx = dr.RequirementsReadContext()
            # Force one sheet to already be resolved before evaluation starts.
            preloaded_ctx.roadmap_stage_by_id("STAGE-1")
            result = dr.evaluate_stage_requirements("STAGE-1", read_context=preloaded_ctx)
        self.assertEqual(result.total_required, 2)
        self.assertEqual(result.missing_required, 2)

    def test_roadmap_evaluation_shared_context_matches_per_stage_aggregation(self):
        spy = _roadmap_fixture(num_stages=3, reqs_per_stage=2)
        result = self._run(spy, dr.evaluate_roadmap_requirements, "RM-1")
        self.assertEqual(result.total_required, 6)
        self.assertEqual(len(result.items), 6)

    def test_object_evaluation_shared_context_matches_aggregation(self):
        spy = _object_fixture(num_roadmaps=2, stages_per_roadmap=2, reqs_per_stage=1)
        result = self._run(spy, dr.evaluate_object_requirements, "OBJ-1")
        self.assertEqual(result.total_required, 4)

    def test_matched_document_satisfies_requirement_through_context(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-0"])]
        roadmaps = [_roadmap_row("RM-1")]
        templates = [_template_row("DOC-0")]
        documents = [_doc_row("DREG-1", "RM-1", "DOC-0")]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=documents)
        result = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(result.items[0].status, dr.STATUS_PRESENT)
        self.assertEqual(result.items[0].matched_document_ids, ("DREG-1",))


# ────────────────────────────────────────────────────────────
# Call-count guarantees
# ────────────────────────────────────────────────────────────

class TestCallCountStageScope(_Patched):
    def test_stage_not_found_reads_only_roadmap_stages(self):
        spy = _SpySheets()
        self._run(spy, dr.evaluate_stage_requirements, "STAGE-MISSING")
        self.assertEqual(spy.read_calls.count("roadmap_stages"), 1)
        self.assertEqual(spy.read_calls.count("document_registry"), 0)
        self.assertEqual(spy.read_calls.count("document_template_registry"), 0)

    def test_zero_requirements_never_touches_document_registry_or_templates(self):
        stages = [_stage_row("STAGE-1", "RM-1", [])]
        roadmaps = [_roadmap_row("RM-1")]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps)
        self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(spy.read_calls.count("document_registry"), 0)
        self.assertEqual(spy.read_calls.count("document_template_registry"), 0)

    def test_q1_vs_q100_identical_read_count(self):
        spy_q1 = _linear_fixture(1)
        self._run(spy_q1, dr.evaluate_stage_requirements, "STAGE-1")

        spy_q100 = _linear_fixture(100)
        self._run(spy_q100, dr.evaluate_stage_requirements, "STAGE-1")

        self.assertEqual(len(spy_q1.read_calls), len(spy_q100.read_calls))

    def test_each_distinct_sheet_read_at_most_once_for_stage_scope(self):
        spy = _linear_fixture(20)
        self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        for sheet_key in ("roadmaps", "roadmap_stages", "stage_entity_relations",
                          "document_template_registry", "document_registry"):
            self.assertLessEqual(spy.read_calls.count(sheet_key), 1, f"{sheet_key} read more than once")

    def test_no_find_row_by_id_calls_from_stage_evaluation(self):
        """Phase 16C.1B1: document_requirements.py no longer calls
        find_row_by_id() directly for any sheet — only
        read_business_sheet_cached()."""
        spy = _linear_fixture(5)
        self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(spy.find_calls, [])


class TestCallCountRoadmapScope(_Patched):
    def test_s1q1_vs_s20q100_identical_read_count(self):
        spy_small = _roadmap_fixture(num_stages=1, reqs_per_stage=1)
        self._run(spy_small, dr.evaluate_roadmap_requirements, "RM-1")

        spy_large = _roadmap_fixture(num_stages=20, reqs_per_stage=5)  # 100 requirements total
        self._run(spy_large, dr.evaluate_roadmap_requirements, "RM-1")

        self.assertEqual(len(spy_small.read_calls), len(spy_large.read_calls))

    def test_each_distinct_sheet_read_at_most_once_for_roadmap_scope(self):
        spy = _roadmap_fixture(num_stages=10, reqs_per_stage=5)
        self._run(spy, dr.evaluate_roadmap_requirements, "RM-1")
        for sheet_key in ("roadmaps", "roadmap_stages", "stage_entity_relations",
                          "document_template_registry", "document_registry"):
            self.assertLessEqual(spy.read_calls.count(sheet_key), 1, f"{sheet_key} read more than once")

    def test_get_requirements_for_roadmap_also_shares_one_context(self):
        spy = _roadmap_fixture(num_stages=10, reqs_per_stage=2)
        self._run(spy, dr.get_requirements_for_roadmap, "RM-1")
        for sheet_key in ("roadmaps", "roadmap_stages", "document_template_registry"):
            self.assertLessEqual(spy.read_calls.count(sheet_key), 1, f"{sheet_key} read more than once")


class TestCallCountObjectScope(_Patched):
    def test_r1_vs_r10_identical_read_count(self):
        spy_small = _object_fixture(num_roadmaps=1, stages_per_roadmap=2, reqs_per_stage=2)
        self._run(spy_small, dr.evaluate_object_requirements, "OBJ-1")

        spy_large = _object_fixture(num_roadmaps=10, stages_per_roadmap=2, reqs_per_stage=2)
        self._run(spy_large, dr.evaluate_object_requirements, "OBJ-1")

        self.assertEqual(len(spy_small.read_calls), len(spy_large.read_calls))

    def test_each_distinct_sheet_read_at_most_once_for_object_scope(self):
        spy = _object_fixture(num_roadmaps=5, stages_per_roadmap=3, reqs_per_stage=3)
        self._run(spy, dr.evaluate_object_requirements, "OBJ-1")
        for sheet_key in ("roadmaps", "roadmap_stages", "stage_entity_relations",
                          "document_template_registry", "document_registry"):
            self.assertLessEqual(spy.read_calls.count(sheet_key), 1, f"{sheet_key} read more than once")


class TestNoWritesAndNoFieldReviews(_Patched):
    def test_zero_writes_in_context_and_engine(self):
        import inspect
        source = inspect.getsource(dr)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                           "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)

    def test_document_field_reviews_never_read(self):
        spy = _roadmap_fixture(num_stages=5, reqs_per_stage=5)
        self._run(spy, dr.evaluate_roadmap_requirements, "RM-1")
        self.assertNotIn("document_field_reviews", spy.read_calls)

    def test_object_registry_never_read_by_engine_itself(self):
        """object_registry existence checks live in
        document_requirements_query.scope_exists(), never inside this
        engine's own evaluation path (stage/roadmap/object scope)."""
        spy = _object_fixture(num_roadmaps=2, stages_per_roadmap=2, reqs_per_stage=1)
        self._run(spy, dr.evaluate_object_requirements, "OBJ-1")
        self.assertNotIn("object_registry", spy.read_calls)


class TestSemanticsFixturesUnderContext(_Patched):
    """Spot-checks of the Phase 16C.1B1 §7 preserved-semantics list,
    exercised explicitly through the new context-based call paths (the
    full matrix is already covered by test_business_document_requirements.py,
    unmodified — these are focused additions, not a duplicate suite)."""

    def test_minimum_count_partial_with_shared_context(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-0"])]
        roadmaps = [_roadmap_row("RM-1")]
        templates = [_template_row("DOC-0")]
        documents = [_doc_row("DREG-1", "RM-1", "DOC-0")]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=documents)

        p1, p2 = _patched(spy)
        with p1, p2:
            ctx = dr.RequirementsReadContext()
            req = dr.DocumentRequirement(
                requirement_id="STAGE-1:DOC-0", document_template_id="DOC-0",
                stage_id="STAGE-1", roadmap_id="RM-1", minimum_count=2,
            )
            result = dr._evaluate_requirement(req, read_context=ctx)
        self.assertEqual(result.matched_count, 1)
        self.assertEqual(result.status, dr.STATUS_PARTIAL)

    def test_family_version_supersession_with_shared_context(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-0"])]
        roadmaps = [_roadmap_row("RM-1")]
        templates = [_template_row("DOC-0")]
        documents = [
            _doc_row("DREG-1", "RM-1", "DOC-0", family_id="FAM-1", version="1", status="archived"),
            _doc_row("DREG-2", "RM-1", "DOC-0", family_id="FAM-1", version="2", status="archived"),
        ]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=documents)
        result = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        # Newest version (2) is archived -> family does not count, even
        # though an older version exists — matches _current_valid_
        # documents_for()'s documented "current version, not just any
        # satisfying row" rule.
        self.assertEqual(result.items[0].status, dr.STATUS_MISSING)

    def test_object_id_consistency_check_with_shared_context(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-0"])]
        roadmaps = [_roadmap_row("RM-1", object_id="OBJ-1")]
        templates = [_template_row("DOC-0")]
        documents = [_doc_row("DREG-1", "RM-1", "DOC-0")]
        documents[0]["Object ID"] = "OBJ-OTHER"
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=documents)
        result = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(result.items[0].status, dr.STATUS_MISSING)

    def test_wrong_roadmap_excluded_with_shared_context(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-0"])]
        roadmaps = [_roadmap_row("RM-1"), _roadmap_row("RM-2")]
        templates = [_template_row("DOC-0")]
        documents = [_doc_row("DREG-1", "RM-2", "DOC-0")]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=templates, documents=documents)
        result = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(result.items[0].status, dr.STATUS_MISSING)

    def test_missing_catalog_row_falls_back_to_id_name(self):
        stages = [_stage_row("STAGE-1", "RM-1", ["DOC-DANGLING"])]
        roadmaps = [_roadmap_row("RM-1")]
        spy = _SpySheets(stages=stages, roadmaps=roadmaps, templates=[], documents=[])
        result = self._run(spy, dr.evaluate_stage_requirements, "STAGE-1")
        self.assertEqual(result.items[0].requirement.name, "DOC-DANGLING")
        self.assertEqual(result.items[0].status, dr.STATUS_MISSING)


if __name__ == "__main__":
    unittest.main()
