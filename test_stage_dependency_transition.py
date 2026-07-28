"""
Dependencies Foundation (2026-07-28, DECISIONS.md §14a): Dependency Gate
(business_core.business_builder._evaluate_stage_dependency_gate) and its
F.7 wiring into transition_stage_status().

Two layers of tests:
  - TestDependencyGateUnit: _evaluate_stage_dependency_gate() in
    isolation, mocked at the stage_dependency_manager boundary (never
    hitting Sheets).
  - TestDependencyGateTransitionIntegration: the full
    transition_stage_status() call, using the shared
    _BaseTransitionTestCase harness from test_stage_transition_foundation
    (imported, not duplicated), confirming F.7's exact placement relative
    to Status write / Start Date / Progress / Roadmap completion /
    auto-provisioning, and confirming F.5 (Completion Gates) and force
    completion remain completely unaffected.

Strictly mocked — no live network calls, no production data touched.

PRS-003 incident reference: this file is registered in conftest.py's
hard socket-block list — any accidental real network call here must
raise, not silently succeed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from test_stage_transition_foundation import (
    _BaseTransitionTestCase, _stage, _roadmap, _write_result,
)


def _fresh_bb():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.business_builder as bb
    return bb


def _resolution_ok(stage_id="STAGE-001", roadmap_id="RM-001",
                    roadmap_template_id="RMT-IZH-ALM-STANDARD-002",
                    template_stage_id="TSTG-035", dependencies=(), resolved=(),
                    missing_live_stages=(), configuration_errors=(),
                    code="DEPENDENCIES_RESOLVED"):
    return {
        "ok": True, "code": code, "error": None,
        "stage_id": stage_id, "roadmap_id": roadmap_id,
        "roadmap_template_id": roadmap_template_id, "template_stage_id": template_stage_id,
        "dependencies": dependencies, "resolved": resolved,
        "missing_live_stages": missing_live_stages, "configuration_errors": configuration_errors,
    }


def _resolution_failed(code="STAGE_NOT_FOUND", error="Stage не найден"):
    return {
        "ok": False, "code": code, "error": error,
        "stage_id": "STAGE-001", "roadmap_id": "", "roadmap_template_id": "", "template_stage_id": "",
        "dependencies": (), "resolved": (), "missing_live_stages": (), "configuration_errors": (),
    }


def _resolved_item(dependency_id="TDEP-001", template_stage_id="TSTG-035",
                    depends_on_template_stage_id="TSTG-034", dependency_type="finish_to_start",
                    blocking=True, prerequisite_stage_id="STAGE-000",
                    prerequisite_stage_name="Diagnostics", prerequisite_status="pending",
                    satisfied=False):
    return {
        "dependency_id": dependency_id, "template_stage_id": template_stage_id,
        "depends_on_template_stage_id": depends_on_template_stage_id,
        "dependency_type": dependency_type, "blocking": blocking,
        "prerequisite_stage_id": prerequisite_stage_id, "prerequisite_stage_name": prerequisite_stage_name,
        "prerequisite_status": prerequisite_status, "satisfied": satisfied,
    }


def _no_cycle():
    return {"ok": True, "cycle_found": False, "cycle_path": (), "limit_exceeded": False, "error": None}


def _cycle_found(path=("TSTG-034", "TSTG-035", "TSTG-034")):
    return {"ok": True, "cycle_found": True, "cycle_path": path, "limit_exceeded": False, "error": None}


def _cycle_limit_exceeded():
    return {"ok": True, "cycle_found": False, "cycle_path": (), "limit_exceeded": True, "error": None}


class TestDependencyGateUnit(unittest.TestCase):
    def _gate(self, resolution, cycle_check=None):
        bb = _fresh_bb()
        with patch("business_core.stage_dependency_manager.resolve_live_stage_dependencies",
                   return_value=resolution), \
             patch("business_core.stage_dependency_manager.detect_reachable_cycle_from_template_stage",
                   return_value=cycle_check if cycle_check is not None else _no_cycle()):
            return bb._evaluate_stage_dependency_gate("STAGE-001")

    def test_no_dependencies_not_blocked(self):
        result = self._gate(_resolution_ok(code="NO_STAGE_DEPENDENCIES"))
        self.assertFalse(result.blocked)
        self.assertEqual(result.error_code, "NO_STAGE_DEPENDENCIES")

    def test_resolution_failure_is_configuration_error(self):
        result = self._gate(_resolution_failed())
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "DEPENDENCY_CONFIGURATION_ERROR")

    def test_all_blocking_dependencies_satisfied(self):
        resolved = (_resolved_item(satisfied=True),)
        result = self._gate(_resolution_ok(resolved=resolved))
        self.assertFalse(result.blocked)
        self.assertEqual(result.error_code, "STAGE_DEPENDENCIES_SATISFIED")
        self.assertEqual(len(result.satisfied), 1)
        self.assertEqual(result.unsatisfied, ())

    def test_unsatisfied_blocking_dependency_blocks(self):
        resolved = (_resolved_item(satisfied=False),)
        result = self._gate(_resolution_ok(resolved=resolved))
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "STAGE_DEPENDENCIES_NOT_SATISFIED")
        self.assertEqual(len(result.unsatisfied), 1)

    def test_non_blocking_unsatisfied_dependency_does_not_block(self):
        resolved = (_resolved_item(blocking=False, satisfied=False),)
        result = self._gate(_resolution_ok(resolved=resolved))
        self.assertFalse(result.blocked)
        self.assertEqual(result.error_code, "STAGE_DEPENDENCIES_SATISFIED")
        self.assertEqual(result.blocking_dependencies, ())

    def test_missing_live_prerequisite_stage_blocks(self):
        result = self._gate(_resolution_ok(missing_live_stages=(("TDEP-001", "TSTG-034"),)))
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "PREREQUISITE_LIVE_STAGE_NOT_FOUND")

    def test_configuration_error_from_resolver_blocks(self):
        result = self._gate(_resolution_ok(configuration_errors=(("TDEP-001", "ambiguous"),)))
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "DEPENDENCY_CONFIGURATION_ERROR")

    def test_corrupted_direct_cycle_hard_blocks(self):
        resolved = (_resolved_item(satisfied=True),)
        result = self._gate(_resolution_ok(resolved=resolved), cycle_check=_cycle_found())
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "DEPENDENCY_CONFIGURATION_ERROR")

    def test_corrupted_indirect_cycle_hard_blocks(self):
        resolved = (_resolved_item(satisfied=True),)
        result = self._gate(_resolution_ok(resolved=resolved),
                             cycle_check=_cycle_found(path=("A", "B", "C", "A")))
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "DEPENDENCY_CONFIGURATION_ERROR")

    def test_cycle_check_limit_exceeded_hard_blocks(self):
        resolved = (_resolved_item(satisfied=True),)
        result = self._gate(_resolution_ok(resolved=resolved), cycle_check=_cycle_limit_exceeded())
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_code, "DEPENDENCY_CONFIGURATION_ERROR")

    def test_multiple_dependencies_all_satisfied_not_blocked(self):
        resolved = (_resolved_item(dependency_id="TDEP-001", satisfied=True),
                    _resolved_item(dependency_id="TDEP-002", depends_on_template_stage_id="TSTG-033", satisfied=True))
        result = self._gate(_resolution_ok(resolved=resolved))
        self.assertFalse(result.blocked)
        self.assertEqual(len(result.satisfied), 2)

    def test_multiple_dependencies_one_unsatisfied_blocks(self):
        resolved = (_resolved_item(dependency_id="TDEP-001", satisfied=True),
                    _resolved_item(dependency_id="TDEP-002", depends_on_template_stage_id="TSTG-033", satisfied=False))
        result = self._gate(_resolution_ok(resolved=resolved))
        self.assertTrue(result.blocked)
        self.assertEqual(len(result.unsatisfied), 1)


class TestDependencyGateTransitionIntegration(_BaseTransitionTestCase):
    """Uses the shared harness's dependency_gate_result= override to
    drive transition_stage_status() through F.7 without touching
    stage_dependency_manager at all."""

    def _blocked_gate(self):
        bb = _fresh_bb()
        return bb._StageDependencyGateResult(
            blocked=True, error_code="STAGE_DEPENDENCIES_NOT_SATISFIED",
            error="У этапа STAGE-001 есть незавершённые обязательные зависимости: STAGE-000 — Diagnostics [pending]",
            unsatisfied=(_resolved_item(satisfied=False),),
        )

    def test_gate_fires_only_on_pending_to_in_progress(self):
        """A blocked gate result must have NO effect on any transition
        other than pending->in_progress — F.7 is gated by
        previous_status/target_status before _evaluate_stage_dependency_
        gate is even called."""
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertTrue(result["ok"])
        self._last_mock_dependency_gate.assert_not_called()

    def test_blocked_gate_blocks_pending_to_in_progress(self):
        result = self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_DEPENDENCIES_NOT_SATISFIED")
        self.assertEqual(result["final_status"], "pending")
        self.assertTrue(result["dependencies_checked"])
        self.assertEqual(len(result["unsatisfied_dependencies"]), 1)

    def test_blocked_gate_prevents_status_write(self):
        result = self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertFalse(result["ok"])
        self._last_mock_write.assert_not_called()

    def test_blocked_gate_prevents_progress_recalculation(self):
        self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            dependency_gate_result=self._blocked_gate(),
        )
        self._last_mock_progress.assert_not_called()

    def test_blocked_gate_prevents_auto_provisioning(self):
        result = self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            dependency_gate_result=self._blocked_gate(),
        )
        self._last_mock_provisioning.assert_not_called()
        self.assertFalse(result.get("provisioning_attempted", False))

    def test_missing_live_stage_gate_code_propagates(self):
        bb = _fresh_bb()
        gate = bb._StageDependencyGateResult(
            blocked=True, error_code="PREREQUISITE_LIVE_STAGE_NOT_FOUND",
            error="Обязательный предыдущий этап не найден",
            missing_live_stages=(("TDEP-001", "TSTG-034"),),
        )
        result = self._call(stage=_stage(status="pending"), target_status="in_progress",
                             dependency_gate_result=gate)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PREREQUISITE_LIVE_STAGE_NOT_FOUND")
        self.assertEqual(len(result["missing_live_dependency_stages"]), 1)

    def test_configuration_error_gate_code_propagates(self):
        bb = _fresh_bb()
        gate = bb._StageDependencyGateResult(
            blocked=True, error_code="DEPENDENCY_CONFIGURATION_ERROR",
            error="Настройка зависимостей повреждена",
            configuration_errors=((None, "cycle"),),
        )
        result = self._call(stage=_stage(status="pending"), target_status="in_progress",
                             dependency_gate_result=gate)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DEPENDENCY_CONFIGURATION_ERROR")
        self.assertEqual(len(result["dependency_configuration_errors"]), 1)

    def test_allowed_transition_preserves_auto_provisioning(self):
        """A non-blocked dependency gate must not interfere with the
        pre-existing auto-provisioning trigger on pending->in_progress."""
        result = self._call(stage=_stage(status="pending"), target_status="in_progress")
        self.assertTrue(result["ok"])
        self._last_mock_provisioning.assert_called_once()
        self.assertTrue(result["dependencies_checked"])

    def test_blocked_to_in_progress_unaffected_by_gate_scope(self):
        """blocked->in_progress is not previous_status=="pending", so F.7
        never fires regardless of gate mock content."""
        result = self._call(
            stage=_stage(status="blocked"), target_status="in_progress",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertTrue(result["ok"])
        self._last_mock_dependency_gate.assert_not_called()

    def test_in_progress_to_done_completion_gates_unaffected(self):
        """F.5 Completion Gates (in_progress->done) must remain completely
        unaffected by F.7 — the two gate families are functionally
        disjoint and never fire on the same transition."""
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertTrue(result["ok"])
        self._last_mock_dependency_gate.assert_not_called()

    def test_force_completion_unaffected_by_dependency_gate(self):
        """No dependency override/force exists for F.7 in this phase — but
        force is only ever relevant to F.5 (in_progress->done) anyway, so
        confirm it's untouched by dependency-gate wiring."""
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done", force=True, reason="urgent",
            dependency_gate_result=self._blocked_gate(),
        )
        self.assertTrue(result["ok"])
        self._last_mock_dependency_gate.assert_not_called()

    def test_start_date_write_unaffected_when_gate_passes(self):
        result = self._call(stage=_stage(status="pending"), target_status="in_progress")
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "in_progress")
        self._last_mock_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
