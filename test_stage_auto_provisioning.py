"""
Auto-trigger for Unified Stage Provisioning: transition_stage_status()'s
strictly-scoped pending->in_progress hook into
business_core.business_builder.provision_stage_operational_instances().

Covers: exact trigger condition, call ordering (after Status/Progress/
Roadmap-completion are settled), confirm=True/trigger="stage_started"/
actor passthrough, try/except isolation (never rolls back Status),
STAGE_PROVISIONED/NOTHING_TO_PROVISION/PARTIAL/FAILED/exception policy,
that transition `code`/`ok` are never overridden by provisioning,
downstream_failures augmentation (never replacement), and that
Completion Gates / force override / /provisionstage / /syncchecklists /
/syncoutputs are all untouched.

Reuses test_stage_transition_foundation.py's shared
_BaseTransitionTestCase harness (already extended with a default-safe
provisioning mock) — no live Sheets writes, no live Telegram calls.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

from test_stage_transition_foundation import (
    _BaseTransitionTestCase, _stage, _roadmap, _write_result,
    _default_provisioning_nothing,
)


def _provisioned_result(stage_id="STAGE-001", created_checklists=(), created_outputs=(),
                        already_existing=0, skipped=0, errors=0):
    return {
        "ok": True, "code": "STAGE_PROVISIONED",
        "stage_id": stage_id, "roadmap_id": "RM-001", "template_stage_id": "TSTG-001",
        "confirm": True, "trigger": "stage_started", "actor": "",
        "checklists": {"created": created_checklists, "already_existing": (), "to_create": (),
                        "skipped_inactive": (), "errors": (), "source": "relations"},
        "outputs": {"created": created_outputs, "already_present": (), "to_add": (),
                    "skipped_inactive_templates": (), "errors": ()},
        "totals": {
            "to_create": 0, "created": len(created_checklists) + len(created_outputs),
            "already_existing": already_existing, "skipped": skipped, "errors": errors,
        },
        "partial_success": False, "warnings": (), "errors": (),
    }


def _partial_result(stage_id="STAGE-001"):
    return {
        "ok": True, "code": "STAGE_PROVISION_PARTIAL",
        "stage_id": stage_id, "roadmap_id": "RM-001", "template_stage_id": "TSTG-001",
        "confirm": True, "trigger": "stage_started", "actor": "",
        "checklists": {"created": ("CHK-001",), "already_existing": (), "to_create": (),
                        "skipped_inactive": (), "errors": (), "source": "relations"},
        "outputs": {"created": (), "already_present": (), "to_add": (),
                    "skipped_inactive_templates": (), "errors": (("SOUT-001", "CODE", "boom"),)},
        "totals": {"to_create": 0, "created": 1, "already_existing": 0, "skipped": 0, "errors": 1},
        "partial_success": True, "warnings": (), "errors": (),
    }


def _failed_result(stage_id="STAGE-001"):
    return {
        "ok": False, "code": "STAGE_PROVISION_FAILED",
        "stage_id": stage_id, "roadmap_id": "RM-001", "template_stage_id": "TSTG-001",
        "confirm": True, "trigger": "stage_started", "actor": "",
        "checklists": {"created": (), "already_existing": (), "to_create": (),
                        "skipped_inactive": (), "errors": (("CHK-001", "boom"),), "source": "relations"},
        "outputs": {"created": (), "already_present": (), "to_add": (),
                    "skipped_inactive_templates": (), "errors": (("SOUT-001", "CODE", "boom"),)},
        "totals": {"to_create": 0, "created": 0, "already_existing": 0, "skipped": 0, "errors": 2},
        "partial_success": False, "warnings": (), "errors": (),
    }


class TestTriggerCondition(_BaseTransitionTestCase):
    def test_pending_to_in_progress_invokes_provisioning_once(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=_provisioned_result(),
        )
        self.assertTrue(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_called_once()

    def test_confirm_true_passed(self):
        result = self._call(target_status="in_progress", stage=_stage(status="pending"))
        _, kwargs = self._last_mock_provisioning.call_args
        self.assertEqual(kwargs.get("confirm"), True)

    def test_trigger_stage_started_passed(self):
        self._call(target_status="in_progress", stage=_stage(status="pending"))
        _, kwargs = self._last_mock_provisioning.call_args
        self.assertEqual(kwargs.get("trigger"), "stage_started")

    def test_actor_passed_through(self):
        self._call(target_status="in_progress", stage=_stage(status="pending"), actor="570004109")
        _, kwargs = self._last_mock_provisioning.call_args
        self.assertEqual(kwargs.get("actor"), "570004109")

    def test_actor_empty_by_default(self):
        self._call(target_status="in_progress", stage=_stage(status="pending"))
        _, kwargs = self._last_mock_provisioning.call_args
        self.assertEqual(kwargs.get("actor"), "")

    def test_stage_id_passed(self):
        self._call(target_status="in_progress", stage=_stage(status="pending", stage_id="STAGE-042"), stage_id="STAGE-042")
        args, kwargs = self._last_mock_provisioning.call_args
        self.assertEqual(kwargs.get("stage_id"), "STAGE-042")

    def test_blocked_to_in_progress_does_not_trigger(self):
        result = self._call(target_status="in_progress", stage=_stage(status="blocked"))
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_in_progress_to_blocked_does_not_trigger(self):
        result = self._call(target_status="blocked", stage=_stage(status="in_progress"))
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_in_progress_to_done_does_not_trigger(self):
        result = self._call(target_status="done", stage=_stage(status="in_progress"))
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_repeat_in_progress_does_not_trigger(self):
        """previous_status is already "in_progress" — not "pending"."""
        result = self._call(target_status="in_progress", stage=_stage(status="in_progress"))
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_invalid_transition_does_not_trigger(self):
        result = self._call(target_status="in_progress", stage=_stage(status="done"))
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_force_completion_does_not_trigger(self):
        """in_progress->done with force=yes — not pending->in_progress at all."""
        from test_stage_transition_foundation import _blocking_missing_scope_result
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            force=True, reason="override",
        )
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_admin_field_update_does_not_trigger(self):
        """target_status equals current status (e.g. admin-only edit path
        via a same-status call) — changed stays False, no trigger."""
        result = self._call(
            target_status="in_progress", stage=_stage(status="in_progress"),
            write_result=_write_result(previous="in_progress", new="in_progress", changed=False),
        )
        self.assertFalse(result["provisioning_attempted"])
        self._last_mock_provisioning.assert_not_called()

    def test_not_triggered_when_status_write_fails(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            write_result=_write_result(ok=False, error="boom"),
        )
        self.assertFalse(result.get("ok"))
        self._last_mock_provisioning.assert_not_called()


class TestCallOrdering(_BaseTransitionTestCase):
    def test_provisioning_called_after_status_write(self):
        calls = []
        self._last_write_calls = calls

        def _write_side_effect(*a, **k):
            calls.append("write")
            return _write_result(new="in_progress")

        def _provisioning_side_effect(*a, **k):
            calls.append("provisioning")
            return _provisioned_result()

        from test_stage_transition_foundation import _fresh_bb
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=_stage(status="pending")), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=_roadmap()), \
             patch("business_core.roadmap_manager.update_stage_status_in_sheet", side_effect=_write_side_effect), \
             patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                   return_value={"ok": True, "error": None, "roadmap_id": "RM-001",
                                 "old_progress": "33", "new_progress": 67, "done_count": 2, "total_count": 3, "changed": True}), \
             patch("business_core.roadmap_manager.maybe_complete_roadmap",
                   return_value={"ok": True, "error": None, "roadmap_id": "RM-001",
                                 "old_status": "active", "new_status": "active", "changed": False}), \
             patch("business_core.document_requirements_query.evaluate_scope") as mock_scope, \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=[]), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[]), \
             patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value={"ok": False, "code": "STAGE_NOT_FOUND", "error": "", "template_stage_id": "", "roadmap": None}), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None), \
             patch("business_core.roadmap_manager.record_stage_completion_override",
                   return_value={"ok": True, "override_id": "SCO-001", "error": None}), \
             patch("business_core.business_builder._evaluate_stage_dependency_gate",
                   return_value=bb._StageDependencyGateResult(blocked=False, error_code="NO_STAGE_DEPENDENCIES")), \
             patch("business_core.business_builder.provision_stage_operational_instances",
                   side_effect=_provisioning_side_effect):
            from business_core.document_requirements_query import ScopeEvaluationResult
            from business_core.document_requirements import RequirementsSummary
            mock_scope.return_value = ScopeEvaluationResult(
                scope_type="stage", scope_id="STAGE-001", exists=True,
                summary=RequirementsSummary(scope_type="stage", scope_id="STAGE-001"),
            )
            bb.transition_stage_status("STAGE-001", "in_progress")

        self.assertEqual(calls, ["write", "provisioning"])


class TestResultShapeAndPolicy(_BaseTransitionTestCase):
    def test_provisioning_added_to_transition_result(self):
        prov = _provisioned_result()
        result = self._call(target_status="in_progress", stage=_stage(status="pending"), provisioning_result=prov)
        self.assertEqual(result["provisioning"], prov)

    def test_stage_provisioned_no_warning(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=_provisioned_result(created_checklists=("CHK-001",)),
        )
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provisioning_warning"], "")
        self.assertFalse(result["partial_success"])

    def test_nothing_to_provision(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=_default_provisioning_nothing(),
        )
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provisioning_warning"], "")
        self.assertFalse(result["partial_success"])

    def test_partial_success_sets_warning_and_downstream_failure(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=_partial_result(),
        )
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")  # code never overridden
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["provisioning_warning"], "Provisioning выполнен частично")
        self.assertTrue(any("частично" in f for f in result["downstream_failures"]))

    def test_full_failure_sets_warning_and_downstream_failure(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=_failed_result(),
        )
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertTrue(result["ok"])  # transition itself still succeeded
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["provisioning_warning"], "Этап переведён в работу, но operational instances не созданы")

    def test_unexpected_exception_does_not_roll_back_stage(self):
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_side_effect=RuntimeError("boom"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertEqual(result["final_status"], "in_progress")
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["provisioning_warning"], "Provisioning вызвал непредвиденную ошибку")
        self.assertTrue(any("непредвиденную ошибку" in f for f in result["downstream_failures"]))

    def test_stage_not_rolled_back_on_partial_or_failed(self):
        for prov_result in (_partial_result(), _failed_result()):
            result = self._call(
                target_status="in_progress", stage=_stage(status="pending"),
                provisioning_result=prov_result,
            )
            self.assertEqual(result["final_status"], "in_progress")
            self.assertTrue(result["changed"])

    def test_downstream_failures_augmented_not_replaced(self):
        """A pre-existing downstream failure (e.g. progress recalculation)
        must survive alongside the new provisioning failure entry — the
        list is appended to, never overwritten."""
        from test_stage_transition_foundation import _progress_result
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            progress_result=_progress_result(ok=False, error="progress boom"),
            provisioning_result=_partial_result(),
        )
        failures_text = " ".join(result["downstream_failures"])
        self.assertIn("прогресс", failures_text.lower())
        self.assertIn("частично", failures_text.lower())

    def test_manual_provisioning_before_transition_yields_already_existing(self):
        """Simulated: manual /provisionstage ran first, so the auto-
        trigger's own call to provision_stage_operational_instances()
        (mocked here) reports everything as already_existing — matches
        real idempotency guarantees of the underlying function, which
        this test file does not re-verify (covered by
        test_unified_stage_provisioning.py)."""
        already_existing_result = _provisioned_result(already_existing=2)
        result = self._call(
            target_status="in_progress", stage=_stage(status="pending"),
            provisioning_result=already_existing_result,
        )
        self.assertEqual(result["provisioning"]["totals"]["created"], 0)
        self.assertEqual(result["provisioning"]["totals"]["already_existing"], 2)
        self.assertFalse(result["partial_success"])


class TestBackwardCompatibility(_BaseTransitionTestCase):
    def test_existing_fields_unchanged_for_non_provisioning_transition(self):
        result = self._call(target_status="blocked", stage=_stage(status="in_progress"))
        self.assertIn("ok", result)
        self.assertIn("code", result)
        self.assertIn("stage_id", result)
        self.assertIn("roadmap_id", result)
        self.assertIn("partial_success", result)
        self.assertIn("downstream_failures", result)
        self.assertFalse(result["provisioning_attempted"])
        self.assertEqual(result["provisioning"], {})
        self.assertEqual(result["provisioning_warning"], "")

    def test_provisioning_never_none_in_result(self):
        """_stage_transition_result()'s provisioning param defaults to
        None but must always be normalized to {} in the returned dict —
        never left as None."""
        result = self._call(target_status="blocked", stage=_stage(status="in_progress"))
        self.assertIsNotNone(result["provisioning"])
        self.assertEqual(result["provisioning"], {})


class TestGatesAndOverrideUnaffected(unittest.TestCase):
    def test_checklist_gate_source_unchanged(self):
        import inspect
        from test_stage_transition_foundation import _fresh_bb
        bb = _fresh_bb()
        source = inspect.getsource(bb._evaluate_checklist_completion_gate)
        self.assertNotIn("provision_stage_operational_instances", source)

    def test_output_gate_source_unchanged(self):
        import inspect
        from test_stage_transition_foundation import _fresh_bb
        bb = _fresh_bb()
        source = inspect.getsource(bb._evaluate_output_completion_gate)
        self.assertNotIn("provision_stage_operational_instances", source)

    def test_document_gate_source_unchanged(self):
        import inspect
        from test_stage_transition_foundation import _fresh_bb
        bb = _fresh_bb()
        source = inspect.getsource(bb._evaluate_document_completion_gate)
        self.assertNotIn("provision_stage_operational_instances", source)

    def test_provision_stage_operational_instances_unchanged_signature(self):
        """Sheets quota mitigation (2026-07-28) added one new, optional,
        default-None `read_context` param at the end — additive only,
        every pre-existing positional/keyword usage is unaffected."""
        import inspect
        from test_stage_transition_foundation import _fresh_bb
        bb = _fresh_bb()
        sig = inspect.signature(bb.provision_stage_operational_instances)
        self.assertEqual(
            list(sig.parameters.keys()),
            ["stage_id", "confirm", "include_checklists", "include_outputs", "trigger", "actor", "read_context"],
        )
        self.assertIsNone(sig.parameters["read_context"].default)


class TestForceCompletionGatePathUnaffected(_BaseTransitionTestCase):
    def test_force_override_still_works_with_both_gates_blocked(self):
        from test_stage_transition_foundation import _blocking_missing_scope_result, _checklist_instance, _checklist_item
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
            force=True, reason="approved",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["override_applied"])
        self._last_mock_provisioning.assert_not_called()
        self.assertFalse(result["provisioning_attempted"])


class TestTelegramMessages(unittest.TestCase):
    def _result(self, **overrides):
        base = {
            "code": "STAGE_STATUS_UPDATED", "changed": True, "previous_status": "pending",
            "final_status": "in_progress", "roadmap_id": "RM-001", "stage_id": "STAGE-001",
            "downstream_failures": (), "partial_success": False, "retry_safe": True, "warnings": (),
            "override_applied": False, "missing_checklist_item_titles": (), "missing_blocking_output_titles": (),
            "provisioning_attempted": True, "provisioning": {}, "provisioning_warning": "",
        }
        base.update(overrides)
        return base

    def test_success_message_shows_breakdown(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = self._result(provisioning=_provisioned_result(created_checklists=("CHK-001",), created_outputs=("SOUT-001",)))
        lines = _stage_transition_success_lines(result, "STAGE-001", None)
        combined = "\n".join(lines)
        self.assertIn("📦 Operational provisioning:", combined)
        self.assertIn("Checklist created: 1", combined)
        self.assertIn("Outputs created: 1", combined)

    def test_nothing_to_provision_message(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = self._result(provisioning=_default_provisioning_nothing())
        lines = _stage_transition_success_lines(result, "STAGE-001", None)
        combined = "\n".join(lines)
        self.assertIn("Operational provisioning: нечего создавать.", combined)

    def test_partial_message(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = self._result(
            provisioning=_partial_result(), partial_success=True,
            provisioning_warning="Provisioning выполнен частично",
            downstream_failures=("Provisioning выполнен частично: {...}",),
        )
        lines = _stage_transition_success_lines(result, "STAGE-001", None)
        combined = "\n".join(lines)
        self.assertIn("Provisioning выполнен частично", combined)
        self.assertIn("/provisionstage stage_id=STAGE-001 confirm=yes", combined)

    def test_full_failure_message(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = self._result(
            provisioning=_failed_result(), partial_success=True,
            provisioning_warning="Этап переведён в работу, но operational instances не созданы",
        )
        lines = _stage_transition_success_lines(result, "STAGE-001", None)
        combined = "\n".join(lines)
        self.assertIn("Этап переведён в работу, но operational instances не созданы", combined)
        self.assertIn("/provisionstage stage_id=STAGE-001 confirm=yes", combined)

    def test_no_provisioning_block_when_not_attempted(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = self._result(provisioning_attempted=False, provisioning={})
        lines = _stage_transition_success_lines(result, "STAGE-001", None)
        combined = "\n".join(lines)
        self.assertNotIn("Operational provisioning", combined)


class TestExistingCommandsUnchanged(unittest.TestCase):
    def test_syncchecklists_source_unchanged_by_autotrigger(self):
        import inspect
        import business_core.telegram_handlers as th
        source = inspect.getsource(th.syncchecklists_cmd)
        self.assertNotIn("stage_started", source)

    def test_syncoutputs_source_unchanged_by_autotrigger(self):
        import inspect
        import business_core.telegram_handlers as th
        source = inspect.getsource(th.syncoutputs_cmd)
        self.assertNotIn("stage_started", source)

    def test_provisionstage_source_unchanged_by_autotrigger(self):
        import inspect
        import business_core.telegram_handlers as th
        source = inspect.getsource(th.provisionstage_cmd)
        self.assertNotIn("stage_started", source)


if __name__ == "__main__":
    unittest.main()
