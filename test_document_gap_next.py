"""
Phase 16C.6: Safe Next Action for Document Gap (/docgapnext).

Covers: criteria validation, generic-fallback action rules per
base_status/quality_flag, deterministic primary/secondary priority
(order-independent, duplicate-safe), fail-closed handling of unknown
base_status/quality_flag, verbatim error-code passthrough from
business_core.document_gap_detail, privacy, and call-budget (exactly
one generate_document_gap_detail() call, 0 additional reads/writes).

All tests mock business_core.document_gap_detail.generate_document_gap_detail
directly — this module itself never reads Sheets/Drive.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import business_core.document_gap_next as dgn
from business_core.document_gap_detail import (
    DocumentGapDetail, DocumentGapDetailResult, DocumentGapDetailCriteria,
    ERROR_REQUIREMENT_NOT_FOUND, ERROR_AMBIGUOUS_REQUIREMENT_ID,
)
from business_core.document_coverage import (
    ERROR_ROADMAP_NOT_FOUND, ERROR_ROADMAP_MISSING_BUSINESS_ID,
    ERROR_UNKNOWN_ENGINE_STATUS, ERROR_COVERAGE_CONFIGURATION_ERROR, ERROR_COVERAGE_INVARIANT_FAILED,
)


def _detail(requirement_name="Топографическая съемка", stage_id="STAGE-011", required=True,
            blocking=True, minimum_count=1, base_status="missing", matched_document_count=0,
            canonical_document_count=0, quality_flags=(), **overrides):
    kwargs = dict(
        requirement_id="STAGE-011:DOC-008", requirement_name=requirement_name, stage_id=stage_id,
        required=required, blocking=blocking, minimum_count=minimum_count, base_status=base_status,
        matched_document_count=matched_document_count, canonical_document_count=canonical_document_count,
        exact_duplicate_matched_count=0, unmatched_document_count=0,
        fully_confirmed_count=0, needs_review_count=0, conflict_document_count=0,
        cache_warning_document_count=0, valid_expiry_count=0, expired_document_count=0,
        unknown_expiry_count=0, invalid_expiry_count=0, quality_flags=quality_flags,
    )
    kwargs.update(overrides)
    return DocumentGapDetail(**kwargs)


def _detail_result(detail=None, ok=True, error_code="", roadmap_id="RM-003",
                    requirement_id="STAGE-011:DOC-008", as_of="2026-07-29", warnings=()):
    criteria = DocumentGapDetailCriteria(roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of)
    return DocumentGapDetailResult(
        criteria=criteria, ok=ok, error_code=error_code,
        detail=detail if detail is not None else (_detail() if ok else None),
        warnings=tuple(warnings), generated_at="2026-07-29 10:00:00 UTC",
    )


def _run(detail_result, roadmap_id="RM-003", requirement_id="STAGE-011:DOC-008", as_of="2026-07-29"):
    with patch("business_core.document_gap_detail.generate_document_gap_detail", return_value=detail_result):
        criteria = dgn.DocumentGapNextCriteria(roadmap_id=roadmap_id, requirement_id=requirement_id, as_of=as_of)
        return dgn.generate_document_gap_next(criteria)


class TestParseGapNextCriteria(unittest.TestCase):
    def test_roadmap_id_required(self):
        c, err = dgn.parse_gap_next_criteria({"requirement_id": "STAGE-011:DOC-008"})
        self.assertIsNone(c)
        self.assertIn("roadmap_id", err)

    def test_requirement_id_required(self):
        c, err = dgn.parse_gap_next_criteria({"roadmap_id": "RM-003"})
        self.assertIsNone(c)
        self.assertIn("requirement_id", err)

    def test_unknown_parameter_rejected(self):
        c, err = dgn.parse_gap_next_criteria({
            "roadmap_id": "RM-003", "requirement_id": "STAGE-011:DOC-008", "stage_id": "STAGE-011",
        })
        self.assertIsNone(c)
        self.assertIn("stage_id", err)

    def test_invalid_as_of_rejected(self):
        c, err = dgn.parse_gap_next_criteria({
            "roadmap_id": "RM-003", "requirement_id": "STAGE-011:DOC-008", "as_of": "bad-date",
        })
        self.assertIsNone(c)

    def test_default_as_of_utc_today(self):
        from datetime import datetime, timezone
        fixed = lambda: datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc)
        c, err = dgn.parse_gap_next_criteria(
            {"roadmap_id": "RM-003", "requirement_id": "STAGE-011:DOC-008"}, now_fn=fixed,
        )
        self.assertEqual(c.as_of, "2026-07-29")


class TestBaseStatusActions(unittest.TestCase):
    def test_missing_action(self):
        result = _run(_detail_result(detail=_detail(base_status="missing")))
        self.assertTrue(result.ok)
        self.assertEqual(result.primary_action.action_code, "OBTAIN_MISSING_DOCUMENT")
        self.assertEqual(result.secondary_actions, ())

    def test_partial_action(self):
        result = _run(_detail_result(detail=_detail(base_status="partial")))
        self.assertEqual(result.primary_action.action_code, "OBTAIN_REMAINING_DOCUMENTS")

    def test_optional_missing_action(self):
        result = _run(_detail_result(detail=_detail(
            base_status="optional_missing", required=False, blocking=False,
        )))
        self.assertEqual(result.primary_action.action_code, "OPTIONAL_DOCUMENT_NOT_PROVIDED")

    def test_present_clean_no_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=())))
        self.assertEqual(result.primary_action.action_code, "NO_ACTION_REQUIRED")
        self.assertEqual(result.secondary_actions, ())


class TestQualityFlagActions(unittest.TestCase):
    def test_duplicate_only_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("duplicate_only",))))
        self.assertEqual(result.primary_action.action_code, "UPLOAD_CANONICAL_DOCUMENT")

    def test_expired_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("expired",))))
        self.assertEqual(result.primary_action.action_code, "OBTAIN_CURRENT_DOCUMENT")

    def test_conflict_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("conflict",))))
        self.assertEqual(result.primary_action.action_code, "RESOLVE_STRUCTURED_DATA_CONFLICT")

    def test_needs_review_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("needs_review",))))
        self.assertEqual(result.primary_action.action_code, "CONFIRM_STRUCTURED_DATA")

    def test_invalid_expiry_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("invalid_expiry",))))
        self.assertEqual(result.primary_action.action_code, "FIX_EXPIRY_DATE")

    def test_cache_warning_action(self):
        result = _run(_detail_result(detail=_detail(base_status="present", quality_flags=("cache_warning",))))
        self.assertEqual(result.primary_action.action_code, "RECHECK_QUALITY_DATA")


class TestPriorityAndDeterminism(unittest.TestCase):
    def test_multiple_flags_priority(self):
        result = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("needs_review", "expired"),
        )))
        self.assertEqual(result.primary_action.action_code, "OBTAIN_CURRENT_DOCUMENT")

    def test_secondary_actions_preserved(self):
        result = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("needs_review", "expired"),
        )))
        secondary_codes = [a.action_code for a in result.secondary_actions]
        self.assertEqual(secondary_codes, ["CONFIRM_STRUCTURED_DATA"])

    def test_flag_input_order_does_not_affect_result(self):
        result_a = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("needs_review", "expired", "conflict"),
        )))
        result_b = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("conflict", "expired", "needs_review"),
        )))
        self.assertEqual(result_a.primary_action.action_code, result_b.primary_action.action_code)
        codes_a = [a.action_code for a in result_a.secondary_actions]
        codes_b = [a.action_code for a in result_b.secondary_actions]
        self.assertEqual(codes_a, codes_b)

    def test_duplicate_flags_do_not_duplicate_actions(self):
        result = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("expired", "expired", "conflict"),
        )))
        all_codes = [result.primary_action.action_code] + [a.action_code for a in result.secondary_actions]
        self.assertEqual(len(all_codes), len(set(all_codes)))
        self.assertEqual(len(all_codes), 2)

    def test_partial_with_quality_flags_preserves_secondary_actions(self):
        result = _run(_detail_result(detail=_detail(base_status="partial", quality_flags=("needs_review",))))
        self.assertEqual(result.primary_action.action_code, "OBTAIN_REMAINING_DOCUMENTS")
        secondary_codes = [a.action_code for a in result.secondary_actions]
        self.assertEqual(secondary_codes, ["CONFIRM_STRUCTURED_DATA"])

    def test_missing_with_unexpected_flag_preserves_secondary_action(self):
        result = _run(_detail_result(detail=_detail(base_status="missing", quality_flags=("cache_warning",))))
        self.assertEqual(result.primary_action.action_code, "OBTAIN_MISSING_DOCUMENT")
        secondary_codes = [a.action_code for a in result.secondary_actions]
        self.assertEqual(secondary_codes, ["RECHECK_QUALITY_DATA"])


class TestBlockingOptionalMessaging(unittest.TestCase):
    def test_required_blocking(self):
        result = _run(_detail_result(detail=_detail(required=True, blocking=True)))
        self.assertTrue(result.required)
        self.assertTrue(result.blocking)

    def test_required_non_blocking(self):
        result = _run(_detail_result(detail=_detail(required=True, blocking=False)))
        self.assertTrue(result.required)
        self.assertFalse(result.blocking)

    def test_optional(self):
        result = _run(_detail_result(detail=_detail(
            required=False, blocking=False, base_status="optional_missing",
        )))
        self.assertFalse(result.required)


class TestErrorPassthrough(unittest.TestCase):
    def test_roadmap_not_found_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_ROADMAP_NOT_FOUND))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_ROADMAP_NOT_FOUND)
        self.assertIsNone(result.primary_action)
        self.assertEqual(result.secondary_actions, ())

    def test_roadmap_missing_business_id_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_ROADMAP_MISSING_BUSINESS_ID))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_ROADMAP_MISSING_BUSINESS_ID)

    def test_requirement_not_found_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_REQUIREMENT_NOT_FOUND))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_REQUIREMENT_NOT_FOUND)

    def test_ambiguous_requirement_id_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_AMBIGUOUS_REQUIREMENT_ID))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_AMBIGUOUS_REQUIREMENT_ID)

    def test_configuration_error_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_COVERAGE_CONFIGURATION_ERROR))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_COVERAGE_CONFIGURATION_ERROR)
        self.assertEqual(result.warnings, ())

    def test_invariant_failure_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_COVERAGE_INVARIANT_FAILED))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_COVERAGE_INVARIANT_FAILED)

    def test_unknown_engine_status_passthrough(self):
        result = _run(_detail_result(ok=False, error_code=ERROR_UNKNOWN_ENGINE_STATUS))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, ERROR_UNKNOWN_ENGINE_STATUS)

    def test_unsupported_base_status_typed_failure(self):
        result = _run(_detail_result(detail=_detail(base_status="not_applicable")))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dgn.ERROR_UNSUPPORTED_BASE_STATUS)
        self.assertIsNone(result.primary_action)

    def test_unsupported_quality_flag_typed_failure(self):
        result = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("some_future_flag",),
        )))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, dgn.ERROR_UNSUPPORTED_QUALITY_FLAG)

    def test_unsupported_value_not_leaked(self):
        result = _run(_detail_result(detail=_detail(base_status="not_applicable")))
        self.assertNotIn("not_applicable", str(result.error_code))
        self.assertEqual(result.base_status, "")


class TestCallBudget(unittest.TestCase):
    def test_exactly_one_detail_call(self):
        with patch(
            "business_core.document_gap_detail.generate_document_gap_detail",
            return_value=_detail_result(),
        ) as mock_detail:
            criteria = dgn.DocumentGapNextCriteria(roadmap_id="RM-003", requirement_id="STAGE-011:DOC-008", as_of="2026-07-29")
            dgn.generate_document_gap_next(criteria)
        mock_detail.assert_called_once()

    def test_no_direct_coverage_or_effective_or_engine_calls(self):
        """Runtime proof (not source-text grepping, which false-positives
        on this module's own explanatory docstrings): patch every
        alternative data source this module must never touch directly,
        and confirm none of them are ever invoked for a normal call."""
        with patch(
            "business_core.document_gap_detail.generate_document_gap_detail",
            return_value=_detail_result(),
        ), \
             patch("business_core.document_coverage.generate_document_coverage") as mock_coverage, \
             patch("business_core.document_search.load_effective_document_records") as mock_effective, \
             patch("business_core.document_requirements.evaluate_roadmap_requirements") as mock_roadmap_eval, \
             patch("business_core.document_requirements.evaluate_stage_requirements") as mock_stage_eval, \
             patch("business_core.sheets.read_business_sheet") as mock_read:
            criteria = dgn.DocumentGapNextCriteria(
                roadmap_id="RM-003", requirement_id="STAGE-011:DOC-008", as_of="2026-07-29",
            )
            dgn.generate_document_gap_next(criteria)
        mock_coverage.assert_not_called()
        mock_effective.assert_not_called()
        mock_roadmap_eval.assert_not_called()
        mock_stage_eval.assert_not_called()
        mock_read.assert_not_called()

    def test_zero_writes(self):
        import inspect
        source = inspect.getsource(dgn)
        for forbidden in ("update_business_row", "append_business_row", "add_worksheet",
                          "update_business_cell", "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)


class TestPrivacy(unittest.TestCase):
    def test_no_document_id_in_result_dataclass(self):
        import dataclasses
        result = _run(_detail_result(detail=_detail(base_status="missing")))
        field_names = {f.name for f in dataclasses.fields(result)}
        self.assertNotIn("document_id", field_names)
        self.assertNotIn("matched_document_ids", field_names)
        self.assertNotIn("file_name", field_names)
        self.assertNotIn("document_name", field_names)

    def test_no_raw_warnings_on_success(self):
        result = _run(_detail_result(detail=_detail(base_status="missing")))
        self.assertEqual(result.warnings, ())


class TestActionTextNoFollowUpDuplicate(unittest.TestCase):
    """Phase 16C.6.1: instruction_lines must never repeat the /docgap
    follow-up command or the generic 'Повторно проверить требование'
    phrase — that belongs solely to the single Telegram follow-up block."""

    def _all_actions(self):
        actions = list(dgn._BASE_STATUS_ACTIONS.values())
        actions.append(dgn._NO_ACTION_REQUIRED)
        actions.extend(dgn._QUALITY_FLAG_ACTIONS.values())
        return actions

    def test_no_action_mentions_docgap(self):
        for action in self._all_actions():
            for line in action.instruction_lines:
                self.assertNotIn("/docgap", line, msg=f"{action.action_code}: {line!r}")

    def test_no_action_repeats_generic_followup_phrase(self):
        for action in self._all_actions():
            for line in action.instruction_lines:
                self.assertNotIn("Повторно проверить требование", line,
                                  msg=f"{action.action_code}: {line!r}")

    def test_base_status_actions_exact_wording(self):
        self.assertEqual(
            dgn._BASE_STATUS_ACTIONS["missing"].instruction_lines,
            (
                "Получить требуемый документ.",
                "Загрузить его в систему.",
                "После загрузки обновить проверку требования.",
            ),
        )
        self.assertEqual(
            dgn._BASE_STATUS_ACTIONS["partial"].instruction_lines,
            (
                "Получить недостающее количество документов.",
                "Загрузить их в систему.",
                "После загрузки обновить проверку требования.",
            ),
        )
        self.assertEqual(
            dgn._BASE_STATUS_ACTIONS["optional_missing"].instruction_lines,
            (
                "Решить, нужен ли опциональный документ для этого объекта.",
                "При необходимости получить и загрузить его.",
                "После загрузки обновить проверку требования.",
            ),
        )
        self.assertEqual(
            dgn._NO_ACTION_REQUIRED.instruction_lines,
            (
                "Дополнительных действий по текущему состоянию не требуется.",
                "При изменении документа обновить проверку требования.",
            ),
        )

    def test_quality_flag_actions_exact_wording(self):
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["duplicate_only"].instruction_lines,
            ("Загрузить отдельный документ, а не точную копию уже существующего файла.",),
        )
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["expired"].instruction_lines,
            (
                "Получить актуальную версию документа или продлить срок действия.",
                "Загрузить актуальный документ.",
            ),
        )
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["conflict"].instruction_lines,
            (
                "Проверить конфликтующие значения.",
                "Подтвердить корректное значение или исправить structured data.",
            ),
        )
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["needs_review"].instruction_lines,
            (
                "Проверить извлечённые structured data.",
                "Подтвердить или исправить значения.",
            ),
        )
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["invalid_expiry"].instruction_lines,
            (
                "Проверить значение срока действия.",
                "Исправить некорректную дату.",
            ),
        )
        self.assertEqual(
            dgn._QUALITY_FLAG_ACTIONS["cache_warning"].instruction_lines,
            (
                "Повторно проверить quality-данные документа.",
                "Убедиться, что structured data обработаны корректно.",
            ),
        )

    def test_secondary_actions_no_docgap_reference(self):
        result = _run(_detail_result(detail=_detail(
            base_status="present", quality_flags=("expired", "needs_review"),
        )))
        for action in result.secondary_actions:
            for line in action.instruction_lines:
                self.assertNotIn("/docgap", line)

    def test_action_codes_unchanged(self):
        self.assertEqual(dgn._BASE_STATUS_ACTIONS["missing"].action_code, "OBTAIN_MISSING_DOCUMENT")
        self.assertEqual(dgn._BASE_STATUS_ACTIONS["partial"].action_code, "OBTAIN_REMAINING_DOCUMENTS")
        self.assertEqual(dgn._BASE_STATUS_ACTIONS["optional_missing"].action_code, "OPTIONAL_DOCUMENT_NOT_PROVIDED")
        self.assertEqual(dgn._NO_ACTION_REQUIRED.action_code, "NO_ACTION_REQUIRED")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["duplicate_only"].action_code, "UPLOAD_CANONICAL_DOCUMENT")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["expired"].action_code, "OBTAIN_CURRENT_DOCUMENT")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["conflict"].action_code, "RESOLVE_STRUCTURED_DATA_CONFLICT")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["needs_review"].action_code, "CONFIRM_STRUCTURED_DATA")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["invalid_expiry"].action_code, "FIX_EXPIRY_DATE")
        self.assertEqual(dgn._QUALITY_FLAG_ACTIONS["cache_warning"].action_code, "RECHECK_QUALITY_DATA")


if __name__ == "__main__":
    unittest.main()
