"""
Unified Stage Provisioning: business_core.business_builder.
provision_stage_operational_instances() — a single call wrapping
provision_checklists_for_stage() (Phase 1) and
sync_stage_output_requirements() (Phase A/B), plus the additive
errors/partial_success contract added to sync_stage_output_requirements()
itself in this same phase.

Does NOT touch: _evaluate_checklist_completion_gate(),
_evaluate_output_completion_gate(), transition_stage_status(), schemas,
stage_entity_relations.py, checklist/output managers, /syncchecklists,
/syncoutputs (beyond additive error display), /provisionroadmap (not
built), auto-trigger (not built).

No live Sheets writes — mocks only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


def _fresh_bb():
    for k in list(sys.modules):
        if k.startswith("business_core"):
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.business_builder")


def _resolved_ok(stage_status="pending", stage_id="STAGE-016", roadmap_id="RM-003", template_stage_id="TSTG-032"):
    return {
        "ok": True, "code": "", "error": None,
        "stage": {"stage_id": stage_id, "roadmap_id": roadmap_id, "status": stage_status},
        "roadmap": {"roadmap_id": roadmap_id, "business_id": "BIZ-001", "service_id": "SVC-001", "object_id": "OBJ-001"},
        "template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": template_stage_id,
        "template_stage_row": {"stage_id": template_stage_id},
    }


_CHECKLISTS_NOTHING = {
    "ok": False, "code": "NO_CHECKLIST_TEMPLATES", "error": "nothing",
    "stage_id": "STAGE-016", "template_stage_id": "TSTG-032", "source": "",
    "to_create": (), "created": (), "already_existing": (),
    "skipped_inactive": (), "errors": (), "partial_success": False,
}

_OUTPUTS_NOTHING = {
    "ok": False, "code": "NO_REQUIRED_OUTPUT_RELATIONS", "error": "nothing",
    "stage_id": "STAGE-016", "template_stage_id": "TSTG-032",
    "to_add": (), "already_present": (), "created": (), "skipped_inactive_templates": (),
    "errors": (), "partial_success": False,
}


def _checklists_preview(to_create=(), already_existing=(), skipped=()):
    return {
        "ok": True, "code": "CHECKLIST_PROVISION_PREVIEW", "error": None,
        "stage_id": "STAGE-016", "template_stage_id": "TSTG-032", "source": "relations",
        "to_create": to_create, "created": (), "already_existing": already_existing,
        "skipped_inactive": skipped, "errors": (), "partial_success": False,
    }


def _checklists_confirmed(created=(), already_existing=(), skipped=(), errors=(), code="CHECKLIST_PROVISIONED", ok=True):
    return {
        "ok": ok, "code": code, "error": None,
        "stage_id": "STAGE-016", "template_stage_id": "TSTG-032", "source": "relations",
        "to_create": created + tuple(e[0] for e in errors), "created": created, "already_existing": already_existing,
        "skipped_inactive": skipped, "errors": errors, "partial_success": bool(errors) and bool(created),
    }


def _outputs_preview(to_add=(), already_present=(), skipped=()):
    return {
        "ok": True, "code": "STAGE_OUTPUT_SYNC_PREVIEW", "error": None,
        "stage_id": "STAGE-016", "template_stage_id": "TSTG-032",
        "to_add": to_add, "already_present": already_present, "created": (),
        "skipped_inactive_templates": skipped, "errors": (), "partial_success": False,
    }


def _outputs_confirmed(created=(), already_present=(), skipped=(), errors=(), code="STAGE_OUTPUT_SYNCED", ok=True):
    return {
        "ok": ok, "code": code, "error": None,
        "stage_id": "STAGE-016", "template_stage_id": "TSTG-032",
        "to_add": created + tuple(e[0] for e in errors), "already_present": already_present, "created": created,
        "skipped_inactive_templates": skipped, "errors": errors, "partial_success": bool(errors) and bool(created),
    }


class TestResolutionAndStatusPolicy(unittest.TestCase):
    def test_resolve_called_exactly_once(self):
        """п.1: единый resolve выполняется один раз (не сравниваются два
        косвенных resolution-исхода от детей)."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolved_ok()) as mock_resolve, \
             patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
             patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
            bb.provision_stage_operational_instances("STAGE-016", confirm=False)
        mock_resolve.assert_called_once_with("STAGE-016")

    def test_resolution_failure_propagates(self):
        bb = _fresh_bb()
        failed = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "не найден"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed):
            result = bb.provision_stage_operational_instances("STAGE-999", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")
        self.assertEqual(result["checklists"], {})
        self.assertEqual(result["outputs"], {})

    def test_done_status_preview_allowed(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolved_ok(stage_status="done")), \
             patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
             patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=False)
        self.assertTrue(result["ok"])
        self.assertNotEqual(result["code"], "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS")

    def test_done_status_confirm_denied(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolved_ok(stage_status="done")):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS")

    def test_cancelled_status_confirm_denied(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolved_ok(stage_status="cancelled")):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS")

    def test_pending_in_progress_blocked_confirm_allowed(self):
        bb = _fresh_bb()
        for status in ("pending", "in_progress", "blocked"):
            with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                       return_value=_resolved_ok(stage_status=status)), \
                 patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
                 patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
                result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
            self.assertNotEqual(result["code"], "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS", status)


class TestSubsystemInvocation(unittest.TestCase):
    def test_preview_calls_both_subsystems(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_preview(to_create=("CHK-001",))) as mock_chk, \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_preview(to_add=("SOUT-001",))) as mock_out:
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=False)
        mock_chk.assert_called_once_with("STAGE-016", confirm=False)
        mock_out.assert_called_once_with("STAGE-016", confirm=False)
        self.assertEqual(result["checklists"]["to_create"], ("CHK-001",))
        self.assertEqual(result["outputs"]["to_add"], ("SOUT-001",))

    def test_confirm_calls_both_subsystems(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-001",))) as mock_chk, \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(created=("SOUT-001",))) as mock_out:
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        mock_chk.assert_called_once_with("STAGE-016", confirm=True)
        mock_out.assert_called_once_with("STAGE-016", confirm=True)
        self.assertEqual(result["totals"]["created"], 2)

    def test_checklist_only_output_disabled(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_preview(to_create=("CHK-001",))) as mock_chk, \
             patch.object(bb, "sync_stage_output_requirements") as mock_out:
            result = bb.provision_stage_operational_instances(
                "STAGE-016", confirm=False, include_outputs=False,
            )
        mock_out.assert_not_called()
        self.assertEqual(result["outputs"]["code"], "SUBSYSTEM_DISABLED")
        self.assertEqual(result["checklists"]["to_create"], ("CHK-001",))

    def test_output_only_checklist_disabled(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage") as mock_chk, \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_preview(to_add=("SOUT-001",))):
            result = bb.provision_stage_operational_instances(
                "STAGE-016", confirm=False, include_checklists=False,
            )
        mock_chk.assert_not_called()
        self.assertEqual(result["checklists"]["code"], "SUBSYSTEM_DISABLED")

    def test_disabled_subsystem_result_is_not_none(self):
        """п.5-6: disabled subsystem returns explicit SUBSYSTEM_DISABLED,
        never None."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()):
            result = bb.provision_stage_operational_instances(
                "STAGE-016", confirm=False, include_checklists=False, include_outputs=False,
            )
        self.assertIsNotNone(result["checklists"])
        self.assertIsNotNone(result["outputs"])
        self.assertEqual(result["checklists"]["code"], "SUBSYSTEM_DISABLED")
        self.assertEqual(result["outputs"]["code"], "SUBSYSTEM_DISABLED")

    def test_checklist_exception_does_not_prevent_output(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage", side_effect=RuntimeError("boom")), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(created=("SOUT-001",))) as mock_out:
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        mock_out.assert_called_once()
        self.assertEqual(result["checklists"]["code"], "CHECKLIST_SUBSYSTEM_EXCEPTION")
        self.assertTrue(result["warnings"])
        self.assertEqual(result["outputs"]["created"], ("SOUT-001",))

    def test_output_exception_does_not_prevent_checklist(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-001",))) as mock_chk, \
             patch.object(bb, "sync_stage_output_requirements", side_effect=RuntimeError("boom")):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        mock_chk.assert_called_once()
        self.assertEqual(result["outputs"]["code"], "OUTPUT_SUBSYSTEM_EXCEPTION")
        self.assertEqual(result["checklists"]["created"], ("CHK-001",))

    def test_no_telegram_dependency(self):
        """п. no Telegram dependency: signature has only primitives."""
        import inspect
        bb = _fresh_bb()
        sig = inspect.signature(bb.provision_stage_operational_instances)
        for name, param in sig.parameters.items():
            self.assertNotIn("update", name.lower())
            self.assertNotIn("context", name.lower())


class TestTotalsAndPolicy(unittest.TestCase):
    def test_both_already_existing(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(already_existing=("CHK-001",))), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(already_present=("SOUT-001",))):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISIONED")
        self.assertEqual(result["totals"]["already_existing"], 2)
        self.assertEqual(result["totals"]["created"], 0)
        self.assertFalse(result["partial_success"])

    def test_nothing_to_provision(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
             patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "NOTHING_TO_PROVISION")
        self.assertFalse(result["partial_success"])

    def test_inactive_skipped_not_counted_as_error(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-001",), skipped=("CHK-002",))), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(created=("SOUT-001",), skipped=("SOUT-002",))):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertEqual(result["code"], "STAGE_PROVISIONED")
        self.assertEqual(result["totals"]["skipped"], 2)
        self.assertEqual(result["totals"]["errors"], 0)
        self.assertFalse(result["partial_success"])

    def test_partial_checklist_error_output_success(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(
                              created=(), errors=(("CHK-001", "boom"),),
                              code="CHECKLIST_PROVISION_FAILED", ok=False)), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(created=("SOUT-001",))):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISION_PARTIAL")
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["totals"]["errors"], 1)
        self.assertEqual(result["totals"]["created"], 1)

    def test_partial_output_error_checklist_success(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-001",))), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(
                              created=(), errors=(("SOUT-001", "WRITE_FAILURE", "boom"),),
                              code="STAGE_OUTPUT_SYNC_FAILED", ok=False)):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISION_PARTIAL")
        self.assertTrue(result["partial_success"])

    def test_full_failure_no_successful_result(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(
                              created=(), errors=(("CHK-001", "boom"),),
                              code="CHECKLIST_PROVISION_FAILED", ok=False)), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(
                              created=(), errors=(("SOUT-001", "WRITE_FAILURE", "boom"),),
                              code="STAGE_OUTPUT_SYNC_FAILED", ok=False)):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_PROVISION_FAILED")
        self.assertFalse(result["partial_success"])

    def test_totals_computed_only_from_explicit_error_fields(self):
        """п.8: никакого inferred подсчёта — totals.errors строго равен
        сумме длин явных errors tuple'ов обеих подсистем."""
        bb = _fresh_bb()
        checklist_errors = (("CHK-001", "boom1"),)
        output_errors = (("SOUT-001", "CODE", "boom2"), ("SOUT-002", "CODE", "boom3"))
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-003",), errors=checklist_errors,
                                                              code="CHECKLIST_PROVISION_PARTIAL")), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(created=("SOUT-003",), errors=output_errors,
                                                           code="STAGE_OUTPUT_SYNC_PARTIAL")):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertEqual(result["totals"]["errors"], len(checklist_errors) + len(output_errors))

    def test_raw_child_dict_not_lost(self):
        bb = _fresh_bb()
        checklists_raw = _checklists_confirmed(created=("CHK-001",))
        outputs_raw = _outputs_confirmed(created=("SOUT-001",))
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage", return_value=checklists_raw), \
             patch.object(bb, "sync_stage_output_requirements", return_value=outputs_raw):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertEqual(result["checklists"], checklists_raw)
        self.assertEqual(result["outputs"], outputs_raw)
        # every original field name is present, untouched
        for field in ("to_create", "created", "already_existing", "skipped_inactive", "errors", "partial_success", "source"):
            self.assertIn(field, result["checklists"])
        for field in ("to_add", "already_present", "created", "skipped_inactive_templates", "errors", "partial_success"):
            self.assertIn(field, result["outputs"])


class TestIdempotencyAndTriggerActor(unittest.TestCase):
    def test_repeated_call_idempotent(self):
        """Second call with the same already-existing state reports
        already_existing, not a new created count — trivially guaranteed
        since children are idempotent; verified at the wrapper level."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(already_existing=("CHK-001",))), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(already_present=("SOUT-001",))):
            first = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
            second = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertEqual(first["totals"]["created"], 0)
        self.assertEqual(second["totals"]["created"], 0)
        self.assertEqual(first["totals"]["already_existing"], 2)
        self.assertEqual(second["totals"]["already_existing"], 2)

    def test_new_relation_after_first_run_only_fills_new(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage",
                          return_value=_checklists_confirmed(created=("CHK-002",), already_existing=("CHK-001",))), \
             patch.object(bb, "sync_stage_output_requirements",
                          return_value=_outputs_confirmed(already_present=("SOUT-001",))):
            result = bb.provision_stage_operational_instances("STAGE-016", confirm=True)
        self.assertEqual(result["checklists"]["created"], ("CHK-002",))
        self.assertEqual(result["checklists"]["already_existing"], ("CHK-001",))

    def test_trigger_and_actor_returned(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
             patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
            result = bb.provision_stage_operational_instances(
                "STAGE-016", confirm=False, trigger="manual_telegram", actor="570004109",
            )
        self.assertEqual(result["trigger"], "manual_telegram")
        self.assertEqual(result["actor"], "570004109")

    def test_default_trigger_and_actor(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_resolved_ok()), \
             patch.object(bb, "provision_checklists_for_stage", return_value=_CHECKLISTS_NOTHING), \
             patch.object(bb, "sync_stage_output_requirements", return_value=_OUTPUTS_NOTHING):
            result = bb.provision_stage_operational_instances("STAGE-016")
        self.assertEqual(result["trigger"], "manual")
        self.assertEqual(result["actor"], "")


class TestGatesAndTransitionUnchanged(unittest.TestCase):
    def test_checklist_gate_unchanged(self):
        import inspect
        bb = _fresh_bb()
        source = inspect.getsource(bb._evaluate_checklist_completion_gate)
        self.assertNotIn("provision_stage_operational_instances", source)

    def test_output_gate_unchanged(self):
        import inspect
        bb = _fresh_bb()
        source = inspect.getsource(bb._evaluate_output_completion_gate)
        self.assertNotIn("provision_stage_operational_instances", source)

    def test_transition_stage_status_does_not_call_unified_provisioning(self):
        import inspect
        bb = _fresh_bb()
        source = inspect.getsource(bb.transition_stage_status)
        self.assertNotIn("provision_stage_operational_instances", source)
        self.assertNotIn("provision_checklists_for_stage", source)
        self.assertNotIn("sync_stage_output_requirements", source)

    def test_no_provisionroadmap_command(self):
        import business_core.telegram_handlers as th
        self.assertFalse(hasattr(th, "provisionroadmap_cmd"))

    def test_provisionstage_command_exists(self):
        import business_core.telegram_handlers as th
        self.assertTrue(hasattr(th, "provisionstage_cmd"))


class TestProvisionStageCmd(unittest.TestCase):
    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]

    def _update(self, args_str: str = ""):
        from unittest.mock import AsyncMock
        update = MagicMock()
        context = MagicMock()
        context.args = args_str.split() if args_str else []
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock(id=570004109)
        return update, context

    def test_preview_shows_both_subsystems(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("stage_id=STAGE-016")

        result = {
            "ok": True, "code": "STAGE_PROVISION_PREVIEW_MARKER", "stage_id": "STAGE-016",
            "roadmap_id": "RM-003", "template_stage_id": "TSTG-032",
            "checklists": _checklists_preview(to_create=("CHK-001",), already_existing=("CHK-000",)),
            "outputs": _outputs_preview(to_add=("SOUT-001",)),
            "totals": {"to_create": 2, "created": 0, "already_existing": 1, "skipped": 0, "errors": 0},
            "partial_success": False, "warnings": (), "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_stage_operational_instances",
                       return_value=result) as mock_call:
                await provisionstage_cmd(update, context)
            _, kwargs = mock_call.call_args
            self.assertEqual(kwargs.get("confirm"), False)
            self.assertEqual(kwargs.get("trigger"), "manual_telegram")
            self.assertEqual(kwargs.get("actor"), "570004109")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("CHK-001", msg)
            self.assertIn("SOUT-001", msg)
            self.assertIn("confirm=yes", msg)
        asyncio.run(run())

    def test_confirm_shows_created_counts(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("stage_id=STAGE-016 confirm=yes")

        result = {
            "ok": True, "code": "STAGE_PROVISIONED", "stage_id": "STAGE-016",
            "roadmap_id": "RM-003", "template_stage_id": "TSTG-032",
            "checklists": _checklists_confirmed(created=("CHK-001",)),
            "outputs": _outputs_confirmed(created=("SOUT-001",)),
            "totals": {"to_create": 0, "created": 2, "already_existing": 0, "skipped": 0, "errors": 0},
            "partial_success": False, "warnings": (), "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_stage_operational_instances",
                       return_value=result) as mock_call:
                await provisionstage_cmd(update, context)
            _, kwargs = mock_call.call_args
            self.assertEqual(kwargs.get("confirm"), True)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
            self.assertIn("Создано Checklist Instances: 1", msg)
            self.assertIn("Создано Output Instances: 1", msg)
        asyncio.run(run())

    def test_partial_shows_warning_and_errors(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("stage_id=STAGE-016 confirm=yes")

        result = {
            "ok": True, "code": "STAGE_PROVISION_PARTIAL", "stage_id": "STAGE-016",
            "roadmap_id": "RM-003", "template_stage_id": "TSTG-032",
            "checklists": _checklists_confirmed(created=("CHK-001",)),
            "outputs": _outputs_confirmed(created=(), errors=(("SOUT-001", "WRITE_FAILURE", "boom"),),
                                           code="STAGE_OUTPUT_SYNC_FAILED", ok=False),
            "totals": {"to_create": 0, "created": 1, "already_existing": 0, "skipped": 0, "errors": 1},
            "partial_success": True, "warnings": (), "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_stage_operational_instances", return_value=result):
                await provisionstage_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("⚠️ Provisioning выполнен частично", msg)
            self.assertIn("SOUT-001", msg)
        asyncio.run(run())

    def test_failed_shows_clear_message(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("stage_id=STAGE-016 confirm=yes")

        result = {
            "ok": False, "code": "STAGE_PROVISION_FAILED", "stage_id": "STAGE-016",
            "roadmap_id": "RM-003", "template_stage_id": "TSTG-032",
            "checklists": _checklists_confirmed(created=(), errors=(("CHK-001", "boom"),),
                                                 code="CHECKLIST_PROVISION_FAILED", ok=False),
            "outputs": _outputs_confirmed(created=(), errors=(("SOUT-001", "WRITE_FAILURE", "boom"),),
                                           code="STAGE_OUTPUT_SYNC_FAILED", ok=False),
            "totals": {"to_create": 0, "created": 0, "already_existing": 0, "skipped": 0, "errors": 2},
            "partial_success": False, "warnings": (), "errors": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_stage_operational_instances", return_value=result):
                await provisionstage_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌ Provisioning не выполнен", msg)
        asyncio.run(run())

    def test_status_denied_message(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("stage_id=STAGE-013 confirm=yes")

        result = {
            "ok": False, "code": "STAGE_PROVISIONING_NOT_ALLOWED_FOR_STATUS",
            "stage_id": "STAGE-013", "roadmap_id": "RM-003", "template_stage_id": "TSTG-029",
            "confirm": True, "trigger": "manual_telegram", "actor": "570004109",
            "checklists": {}, "outputs": {},
            "totals": {"to_create": 0, "created": 0, "already_existing": 0, "skipped": 0, "errors": 0},
            "partial_success": False, "warnings": (),
            "errors": ("Provisioning с confirm=yes запрещён для Stage со статусом 'done'.",),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_stage_operational_instances", return_value=result):
                await provisionstage_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_missing_stage_id(self):
        import asyncio
        self._setup()
        from business_core.telegram_handlers import provisionstage_cmd
        update, context = self._update("")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await provisionstage_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
