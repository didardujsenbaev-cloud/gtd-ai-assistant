"""
Phase 34C: dedicated tests for business_core.business_builder.
transition_stage_status() and update_stage_admin_fields() — the
canonical Stage-transition/admin-field orchestration boundary approved
in ADR-017 (Phase 34B).

Strictly against mocked business_core.roadmap_manager functions — no
live network calls, no production data touched.

PRS-003 incident reference: this file is registered in conftest.py's
hard socket-block list — any accidental real network call here must
raise, not silently succeed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


def _fresh_bb():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.business_builder as bb
    return bb


def _stage(status="pending", stage_id="STAGE-001", roadmap_id="RM-001"):
    return {
        "row_num": 5, "stage_id": stage_id, "roadmap_id": roadmap_id,
        "order": "1", "name": "Диагностика", "status": status, "raw_status": status,
        "due_date": "", "completed_at": "", "responsible": "", "notes": "",
        "start_date": "", "priority": "", "blocking_reason": "",
        "docs_required": "", "docs_received": "", "checklist_ids": "",
    }


def _roadmap(status="active", roadmap_id="RM-001"):
    return {"roadmap_id": roadmap_id, "status": status, "raw_status": status}


def _write_result(ok=True, previous="pending", new="done", changed=True,
                   roadmap_id="RM-001", stage_id="STAGE-001", partial_success=False,
                   updated_fields=("Status",), warnings=(), error=None, final_status=None):
    return {
        "ok": ok, "partial_success": partial_success, "stage_id": stage_id,
        "roadmap_id": roadmap_id, "previous_status": previous, "requested_status": new,
        "final_status": final_status if final_status is not None else (new if ok else previous),
        "changed": changed, "updated_fields": tuple(updated_fields), "warnings": tuple(warnings),
        "errors": (error,) if error else (), "error": error,
        "old_status": previous, "new_status": new,
    }


def _progress_result(ok=True, old="33", new=67, changed=True, roadmap_id="RM-001", error=None):
    return {"ok": ok, "error": error, "roadmap_id": roadmap_id,
            "old_progress": old, "new_progress": new, "done_count": 2, "total_count": 3, "changed": changed}


def _completion_result(ok=True, old="active", new="active", changed=False, roadmap_id="RM-001", error=None):
    return {"ok": ok, "error": error, "roadmap_id": roadmap_id,
            "old_status": old, "new_status": new, "changed": changed}


# ─────────────────────────────────────────────────────────────
# Phase 43 (Document Completion Gate) — evaluate_scope() result builders.
# Built from the REAL dataclasses (document_requirements_query.
# ScopeEvaluationResult / document_requirements.RequirementsSummary/
# DocumentRequirement/DocumentRequirementStatus) rather than ad-hoc dicts,
# so a test failure here would also catch a real contract drift in those
# classes, not just in this test file's assumptions about their shape.
# ─────────────────────────────────────────────────────────────

def _satisfied_scope_result(stage_id="STAGE-001"):
    """No structured requirements configured (or everything already
    satisfied) — the default for every test that doesn't care about the
    gate at all."""
    from business_core.document_requirements_query import ScopeEvaluationResult
    from business_core.document_requirements import RequirementsSummary
    return ScopeEvaluationResult(
        scope_type="stage", scope_id=stage_id, exists=True,
        summary=RequirementsSummary(scope_type="stage", scope_id=stage_id),
    )


def _blocking_missing_scope_result(stage_id="STAGE-001", doc_ids=("DOC-008",)):
    from business_core.document_requirements_query import ScopeEvaluationResult
    from business_core.document_requirements import (
        RequirementsSummary, DocumentRequirement, DocumentRequirementStatus,
    )
    items = tuple(
        DocumentRequirementStatus(
            requirement=DocumentRequirement(
                requirement_id=f"REQ-{i}", document_template_id=doc_id,
                stage_id=stage_id, blocking=True,
            ),
            status="missing",
        )
        for i, doc_id in enumerate(doc_ids, start=1)
    )
    return ScopeEvaluationResult(
        scope_type="stage", scope_id=stage_id, exists=True,
        summary=RequirementsSummary(
            scope_type="stage", scope_id=stage_id, items=items,
            total_required=len(doc_ids), missing_required=len(doc_ids),
            blocking_missing=len(doc_ids), completion_percentage=0.0, is_complete=False,
        ),
    )


def _optional_missing_scope_result(stage_id="STAGE-001", optional_missing=1):
    from business_core.document_requirements_query import ScopeEvaluationResult
    from business_core.document_requirements import RequirementsSummary
    return ScopeEvaluationResult(
        scope_type="stage", scope_id=stage_id, exists=True,
        summary=RequirementsSummary(
            scope_type="stage", scope_id=stage_id, optional_missing=optional_missing,
        ),
    )


def _configuration_error_scope_result(stage_id="STAGE-001", errors=(("STAGE-001", "REL-999", "dangling entity"),)):
    from business_core.document_requirements_query import ScopeEvaluationResult
    from business_core.document_requirements import RequirementsSummary
    return ScopeEvaluationResult(
        scope_type="stage", scope_id=stage_id, exists=True,
        summary=RequirementsSummary(
            scope_type="stage", scope_id=stage_id, configuration_errors=tuple(errors),
            has_configuration_errors=True, is_complete=False,
        ),
    )


def _override_write_result(ok=True, override_id="SCO-001", error=None):
    return {"ok": ok, "override_id": override_id if ok else "", "error": error}


_UNSET = object()


class _BaseTransitionTestCase(unittest.TestCase):
    def _call(self, target_status="in_progress", notes=None, admin_fields=None,
              stage=_UNSET, roadmap=_UNSET, write_result=None, progress_result=None,
              completion_result=None, stage_id="STAGE-001",
              force=False, reason=None, actor="",
              evaluate_scope_result=_UNSET, record_override_result=None,
              checklist_instances=None, checklist_items=None):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.find_stage_by_id",
                   return_value=_stage() if stage is _UNSET else stage), \
             patch("business_core.roadmap_manager.find_roadmap_by_id",
                   return_value=_roadmap() if roadmap is _UNSET else roadmap), \
             patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                   return_value=write_result if write_result is not None else _write_result(new=target_status)) as mock_write, \
             patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                   return_value=progress_result if progress_result is not None else _progress_result()) as mock_progress, \
             patch("business_core.roadmap_manager.maybe_complete_roadmap",
                   return_value=completion_result if completion_result is not None else _completion_result()), \
             patch("business_core.document_requirements_query.evaluate_scope",
                   return_value=(_satisfied_scope_result(stage_id) if evaluate_scope_result is _UNSET
                                 else evaluate_scope_result)) as mock_evaluate_scope, \
             patch("business_core.checklist_manager.list_checklist_instances",
                   return_value=(checklist_instances if checklist_instances is not None else [])) as mock_checklist_instances, \
             patch("business_core.checklist_manager.list_checklist_instance_items",
                   return_value=(checklist_items if checklist_items is not None else [])) as mock_checklist_items, \
             patch("business_core.roadmap_manager.record_stage_completion_override",
                   return_value=(record_override_result if record_override_result is not None
                                 else _override_write_result())) as mock_record_override:
            result = bb.transition_stage_status(
                stage_id, target_status, notes=notes, admin_fields=admin_fields,
                force=force, reason=reason, actor=actor,
            )
            self._last_mock_record_override = mock_record_override
            self._last_mock_evaluate_scope = mock_evaluate_scope
            self._last_mock_write = mock_write
            self._last_mock_progress = mock_progress
            self._last_mock_checklist_instances = mock_checklist_instances
            self._last_mock_checklist_items = mock_checklist_items
            return result


class TestStageResolution(_BaseTransitionTestCase):
    def test_missing_stage_id(self):
        bb = _fresh_bb()
        result = bb.transition_stage_status("", "done")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_stage_not_found(self):
        result = self._call(stage=None, target_status="done")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_stage_with_missing_parent_roadmap(self):
        result = self._call(stage=_stage(roadmap_id="RM-GONE"), roadmap=None, target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_NOT_FOUND")

    def test_valid_stage_proceeds(self):
        result = self._call(stage=_stage(status="pending"), target_status="in_progress")
        self.assertTrue(result["ok"])


class TestRoadmapEligibility(_BaseTransitionTestCase):
    def test_active_allows_status_update(self):
        result = self._call(roadmap=_roadmap(status="active"), target_status="in_progress")
        self.assertTrue(result["ok"])

    def test_on_hold_blocks_status(self):
        result = self._call(roadmap=_roadmap(status="on_hold"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_ON_HOLD")

    def test_completed_blocks_status(self):
        result = self._call(roadmap=_roadmap(status="completed"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_COMPLETED")

    def test_cancelled_blocks_status(self):
        result = self._call(roadmap=_roadmap(status="cancelled"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_CANCELLED")


class TestStatusVocabulary(_BaseTransitionTestCase):
    def test_all_canonical_values_accepted_where_transition_allows(self):
        for status in ("pending", "in_progress", "blocked", "skipped"):
            result = self._call(
                stage=_stage(status="pending"), target_status=status,
                write_result=_write_result(previous="pending", new=status),
            )
            self.assertTrue(result["ok"], f"{status} should be a valid target from pending")

    def test_not_started_alias_rejected_as_write_target(self):
        """not_started is a READ-time alias only (ADR-009) — it must
        never be accepted as a WRITE target, matching
        update_stage_status_in_sheet's own existing behavior."""
        result = self._call(target_status="not_started")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_STAGE_STATUS")

    def test_unknown_target_blocked(self):
        result = self._call(target_status="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_STAGE_STATUS")


class TestTransitionMatrix(_BaseTransitionTestCase):
    def _assert_allowed(self, current, target):
        result = self._call(
            stage=_stage(status=current), target_status=target,
            write_result=_write_result(previous=current, new=target),
        )
        self.assertTrue(result["ok"], f"{current} -> {target} should be allowed")
        self.assertNotEqual(result["code"], "INVALID_STAGE_TRANSITION")
        self.assertNotEqual(result["code"], "STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def _assert_reopen_blocked(self, current, target):
        result = self._call(stage=_stage(status=current), target_status=target)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def _assert_invalid(self, current, target):
        result = self._call(stage=_stage(status=current), target_status=target)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_STAGE_TRANSITION")

    def test_pending_to_in_progress(self):
        self._assert_allowed("pending", "in_progress")

    def test_pending_to_blocked(self):
        self._assert_allowed("pending", "blocked")

    def test_pending_to_skipped(self):
        self._assert_allowed("pending", "skipped")

    def test_pending_to_done_invalid(self):
        self._assert_invalid("pending", "done")

    def test_in_progress_to_pending(self):
        self._assert_allowed("in_progress", "pending")

    def test_in_progress_to_blocked(self):
        self._assert_allowed("in_progress", "blocked")

    def test_in_progress_to_done(self):
        self._assert_allowed("in_progress", "done")

    def test_in_progress_to_skipped(self):
        self._assert_allowed("in_progress", "skipped")

    def test_blocked_to_pending(self):
        self._assert_allowed("blocked", "pending")

    def test_blocked_to_in_progress(self):
        self._assert_allowed("blocked", "in_progress")

    def test_blocked_to_skipped(self):
        self._assert_allowed("blocked", "skipped")

    def test_blocked_to_done_invalid(self):
        self._assert_invalid("blocked", "done")

    def test_done_to_done_unchanged(self):
        result = self._call(
            stage=_stage(status="done"), target_status="done",
            write_result=_write_result(previous="done", new="done", changed=False),
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_done_to_pending_blocked_with_explicit_reopen_code(self):
        self._assert_reopen_blocked("done", "pending")

    def test_done_to_in_progress_blocked(self):
        self._assert_reopen_blocked("done", "in_progress")

    def test_skipped_to_skipped_unchanged(self):
        result = self._call(
            stage=_stage(status="skipped"), target_status="skipped",
            write_result=_write_result(previous="skipped", new="skipped", changed=False),
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])

    def test_skipped_to_pending_blocked(self):
        self._assert_reopen_blocked("skipped", "pending")

    def test_skipped_to_in_progress_blocked(self):
        self._assert_reopen_blocked("skipped", "in_progress")


class TestTimestamps(_BaseTransitionTestCase):
    """These behaviors live inside update_stage_status_in_sheet (unchanged
    by Phase 34C) — verified here at the orchestration boundary to
    confirm transition_stage_status() doesn't disturb them."""

    def test_first_in_progress_sets_start_date(self):
        result = self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            write_result=_write_result(previous="pending", new="in_progress",
                                       updated_fields=("Status", "Start Date")),
        )
        self.assertIn("Start Date", result["written_fields"])

    def test_repeated_in_progress_preserves_start_date(self):
        result = self._call(
            stage=_stage(status="in_progress"), target_status="in_progress",
            write_result=_write_result(previous="in_progress", new="in_progress",
                                       changed=False, updated_fields=("Status",)),
        )
        self.assertNotIn("Start Date", result["written_fields"])

    def test_done_sets_completed_at(self):
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            write_result=_write_result(previous="in_progress", new="done",
                                       updated_fields=("Status", "Completed At")),
        )
        self.assertIn("Completed At", result["written_fields"])

    def test_skipped_does_not_set_completed_at(self):
        result = self._call(
            stage=_stage(status="pending"), target_status="skipped",
            write_result=_write_result(previous="pending", new="skipped",
                                       updated_fields=("Status",)),
        )
        self.assertNotIn("Completed At", result["written_fields"])

    def test_no_timestamp_cleared_on_ordinary_call(self):
        """transition_stage_status() never issues a clearing write for
        Start Date/Completed At — it only ever forwards whatever
        update_stage_status_in_sheet reports as updated_fields."""
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            write_result=_write_result(previous="in_progress", new="done",
                                       updated_fields=("Status", "Completed At")),
        )
        self.assertEqual(set(result["written_fields"]), {"Status", "Completed At"})


class TestProgress(_BaseTransitionTestCase):
    def test_changed_status_recalculates(self):
        result = self._call(
            target_status="in_progress",
            write_result=_write_result(previous="pending", new="in_progress"),
            progress_result=_progress_result(old="0", new=33),
        )
        self.assertEqual(result["progress_after"], 33)

    def test_unchanged_status_does_not_recalculate(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=_stage(status="pending")), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=_roadmap()), \
             patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                   return_value=_write_result(previous="pending", new="pending", changed=False)), \
             patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc, \
             patch("business_core.roadmap_manager.maybe_complete_roadmap") as mock_complete:
            result = bb.transition_stage_status("STAGE-001", "pending")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UNCHANGED")
        mock_recalc.assert_not_called()
        mock_complete.assert_not_called()

    def test_recalculation_failure_is_structured_partial_success(self):
        result = self._call(
            target_status="in_progress",
            write_result=_write_result(previous="pending", new="in_progress"),
            progress_result=_progress_result(ok=False, error="429 quota"),
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["code"], "PROGRESS_RECALCULATION_FAILED")
        self.assertIn("retry_safe", result)
        self.assertTrue(result["retry_safe"])

    def test_retry_safe_always_true(self):
        result = self._call(target_status="in_progress")
        self.assertTrue(result["retry_safe"])


class TestAutoCompletion(_BaseTransitionTestCase):
    def test_last_incomplete_stage_done_completes_active_roadmap(self):
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            write_result=_write_result(previous="in_progress", new="done"),
            progress_result=_progress_result(old="67", new=100),
            completion_result=_completion_result(changed=True, old="active", new="completed"),
        )
        self.assertEqual(result["roadmap_status_after"], "completed")

    def test_on_hold_roadmap_never_auto_completes(self):
        """on_hold blocks the whole transition before reaching completion
        logic at all (ADR-017 §7) — asserted here for completeness."""
        result = self._call(roadmap=_roadmap(status="on_hold"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_ON_HOLD")

    def test_completed_never_auto_completes_again(self):
        result = self._call(roadmap=_roadmap(status="completed"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_COMPLETED")

    def test_cancelled_never_auto_completes(self):
        result = self._call(roadmap=_roadmap(status="cancelled"), target_status="in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_CANCELLED")

    def test_completion_failure_is_structured_partial_success(self):
        result = self._call(
            stage=_stage(status="in_progress"), target_status="done",
            write_result=_write_result(previous="in_progress", new="done"),
            progress_result=_progress_result(old="67", new=100),
            completion_result=_completion_result(ok=False, error="429 quota"),
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["code"], "ROADMAP_AUTO_COMPLETION_FAILED")


class TestAdminFields(unittest.TestCase):
    def _call(self, writes, roadmap_status="active", stage=None):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.find_stage_by_id",
                   return_value=stage if stage is not None else _stage()), \
             patch("business_core.roadmap_manager.find_roadmap_by_id",
                   return_value=_roadmap(status=roadmap_status)), \
             patch("business_core.roadmap_manager.update_stage_fields",
                   return_value={"ok": True, "stage_id": "STAGE-001",
                                 "written_fields": tuple(writes.keys()), "error": None}):
            return bb.update_stage_admin_fields("STAGE-001", writes)

    def test_active_allows(self):
        result = self._call({"Responsible": "Иван"}, roadmap_status="active")
        self.assertTrue(result["ok"])

    def test_on_hold_allows(self):
        result = self._call({"Responsible": "Иван"}, roadmap_status="on_hold")
        self.assertTrue(result["ok"])

    def test_completed_blocks(self):
        result = self._call({"Responsible": "Иван"}, roadmap_status="completed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_COMPLETED")

    def test_cancelled_blocks(self):
        result = self._call({"Responsible": "Иван"}, roadmap_status="cancelled")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_CANCELLED")

    def test_status_cannot_bypass_transition_api_through_update_stage_fields(self):
        """roadmap_manager.update_stage_fields() itself rejects a "Status"
        key outright — this is the second line of defense confirming
        update_stage_admin_fields() cannot be used to sneak a Status
        change past transition_stage_status()."""
        bb = _fresh_bb()
        import business_core.roadmap_manager as rm
        result = rm.update_stage_fields("STAGE-001", {"Status": "done"})
        self.assertFalse(result["ok"])


class TestArchitecture(unittest.TestCase):
    def test_roadmap_manager_remains_sole_stage_writer(self):
        import ast
        from pathlib import Path
        path = Path(__file__).parent / "business_core" / "roadmap_manager.py"
        src = path.read_text(encoding="utf-8")
        self.assertIn("def update_stage_status_in_sheet", src)
        self.assertIn("def update_stage_fields", src)

    def test_telegram_handlers_has_no_transition_matrix(self):
        from pathlib import Path
        path = Path(__file__).parent / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        self.assertNotIn("_STAGE_ORDINARY_TRANSITIONS", src)

    def test_telegram_handlers_does_not_read_roadmap_status_for_stage_policy(self):
        from pathlib import Path
        import re
        path = Path(__file__).parent / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def updatestage_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        self.assertNotIn("find_roadmap_by_id", body)
        self.assertNotIn("ROADMAP_ON_HOLD", body)

    def test_no_direct_progress_or_completion_calls_from_updatestage(self):
        from pathlib import Path
        path = Path(__file__).parent / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def updatestage_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        self.assertNotIn("recalculate_roadmap_progress(", body)
        self.assertNotIn("maybe_complete_roadmap(", body)

    def test_dependency_direction_has_no_cycle(self):
        import ast
        from pathlib import Path
        path = Path(__file__).parent / "business_core" / "roadmap_manager.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        forbidden = {"business_builder", "telegram_handlers"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[-1])
        self.assertEqual(found & forbidden, set())


# ─────────────────────────────────────────────────────────────
# Phase 43: Document Completion Gate
# ─────────────────────────────────────────────────────────────

class TestDocumentCompletionGate(_BaseTransitionTestCase):
    def test_blocking_zero_allows_done(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_satisfied_scope_result(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertEqual(result["final_status"], "done")

    def test_only_optional_missing_allows_done_with_warning(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_optional_missing_scope_result(optional_missing=2),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")
        self.assertTrue(any("optional" in w.lower() or "необязательных" in w.lower() for w in result["warnings"]))

    def test_zero_configured_requirements_allows_done(self):
        """No structured requirements at all is not an error — same
        result shape as 'everything satisfied'."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_satisfied_scope_result(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "done")

    def test_blocking_missing_rejects_without_force(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_DOCUMENT_GATE_BLOCKED")
        self.assertEqual(result["missing_blocking_doc_ids"], ("DOC-008",))
        self.assertEqual(result["final_status"], "in_progress")

    def test_blocking_missing_does_not_write_status_or_progress(self):
        self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(),
        )
        self._last_mock_write.assert_not_called()
        self._last_mock_progress.assert_not_called()

    def test_force_without_reason_rejected(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(), force=True, reason=None,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED")

    def test_force_with_blank_reason_rejected(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(), force=True, reason="   ",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED")

    def test_force_with_reason_and_blocking_missing_completes_and_audits(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008", "DOC-009")),
            force=True, reason="manager approved", actor="dida",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "done")
        self.assertTrue(result["override_applied"])
        self.assertEqual(result["override_type"], "missing_blocking_documents")
        self.assertEqual(result["override_id"], "SCO-001")

        self._last_mock_record_override.assert_called_once_with(
            stage_id="STAGE-001", roadmap_id="RM-001", user="dida", reason="manager approved",
            missing_blocking_doc_ids=("DOC-008", "DOC-009"),
            previous_status="in_progress", target_status="done",
            override_type="missing_blocking_documents", configuration_error_details="",
            missing_checklist_instance_ids=(), missing_checklist_item_ids=(), missing_checklist_item_titles=(),
        )

    def test_force_with_reason_and_blocking_zero_completes_without_audit(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_satisfied_scope_result(),
            force=True, reason="just in case",
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["override_applied"])
        self.assertEqual(result["override_id"], "")
        self._last_mock_record_override.assert_not_called()

    def test_configuration_error_rejects_without_force(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_configuration_error_scope_result(
                errors=(("STAGE-001", "REL-999", "dangling entity"),),
            ),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_DOCUMENT_REQUIREMENTS_CONFIGURATION_ERROR")
        self.assertIn("REL-999", result["configuration_error_details"])
        self.assertNotEqual(result["code"], "STAGE_DOCUMENT_GATE_BLOCKED")

    def test_configuration_error_with_force_completes_and_audits_with_correct_type(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_configuration_error_scope_result(
                errors=(("STAGE-001", "REL-999", "dangling entity"),),
            ),
            force=True, reason="fixing later",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["override_applied"])
        self.assertEqual(result["override_type"], "configuration_error")
        self._last_mock_record_override.assert_called_once()
        _, kwargs = self._last_mock_record_override.call_args
        self.assertEqual(kwargs["override_type"], "configuration_error")
        self.assertIn("REL-999", kwargs["configuration_error_details"])

    def test_skipped_transition_does_not_go_through_gate(self):
        result = self._call(target_status="skipped", stage=_stage(status="in_progress"))
        self._last_mock_evaluate_scope.assert_not_called()
        self.assertTrue(result["ok"])

    def test_blocked_to_skipped_does_not_go_through_gate(self):
        result = self._call(target_status="skipped", stage=_stage(status="blocked"))
        self._last_mock_evaluate_scope.assert_not_called()
        self.assertTrue(result["ok"])

    def test_pending_to_in_progress_does_not_go_through_gate(self):
        result = self._call(target_status="in_progress", stage=_stage(status="pending"))
        self._last_mock_evaluate_scope.assert_not_called()
        self.assertTrue(result["ok"])

    def test_audit_not_created_when_status_write_fails(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(),
            write_result=_write_result(ok=False, error="sheets exploded"),
            force=True, reason="approved",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_WRITE_PARTIAL_FAILURE")
        self._last_mock_record_override.assert_not_called()

    def test_audit_write_failure_after_successful_done_returns_warning_but_status_stays_done(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(),
            force=True, reason="approved",
            record_override_result=_override_write_result(ok=False, error="append failed"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "done")
        self.assertTrue(result["partial_success"])
        self.assertTrue(any("append failed" in f for f in result["downstream_failures"]))

    def test_repeated_done_does_not_create_new_override_audit(self):
        """A second 'done' call after the Stage is already done is a
        no-op self-loop (STAGE_STATUS_UNCHANGED, done->done is allowed
        by _STAGE_ORDINARY_TRANSITIONS as an identity transition) — the
        gate only ever activates for previous_status=="in_progress", so
        it's never reached here and no second override audit row is
        ever created."""
        result = self._call(
            target_status="done", stage=_stage(status="done"),
            write_result=_write_result(previous="done", new="done", changed=False),
        )
        self._last_mock_evaluate_scope.assert_not_called()
        self._last_mock_record_override.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UNCHANGED")
        self.assertFalse(result["changed"])

    def test_gate_only_calls_evaluate_scope_with_stage_id(self):
        self._call(target_status="done", stage=_stage(status="in_progress"), stage_id="STAGE-001")
        self._last_mock_evaluate_scope.assert_called_once_with("stage", "STAGE-001")


# ─────────────────────────────────────────────────────────────
# Phase 44: Checklist Completion Gate — fixture builders
# ─────────────────────────────────────────────────────────────

def _checklist_instance(instance_id="CLIN-001", stage_id="STAGE-001", status="in_progress"):
    return {"Checklist Instance ID": instance_id, "Stage ID": stage_id, "Status": status}


def _checklist_item(item_id="CLII-001", instance_id="CLIN-001", required=True, status="pending", title="Пункт"):
    return {
        "Checklist Instance Item ID": item_id, "Checklist Instance ID": instance_id,
        "Required": "true" if required else "false", "Status": status,
        "Item Title Snapshot": title,
    }


class TestChecklistCompletionGate(_BaseTransitionTestCase):
    def test_no_checklist_instances_allows_done(self):
        result = self._call(target_status="done", stage=_stage(status="in_progress"), checklist_instances=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")

    def test_fully_completed_checklist_allows_done(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="done")],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_STATUS_UPDATED")

    def test_only_optional_missing_allows_done_with_warning(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[
                _checklist_item(item_id="CLII-001", required=True, status="done", title="Req"),
                _checklist_item(item_id="CLII-002", required=False, status="pending", title="Opt"),
            ],
        )
        self.assertTrue(result["ok"])
        self.assertTrue(any("необязательных" in w.lower() for w in result["warnings"]))

    def test_required_item_missing_rejects_without_force(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить документы")],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_CHECKLIST_GATE_BLOCKED")
        self.assertEqual(result["final_status"], "in_progress")

    def test_required_item_missing_does_not_write_status_or_progress(self):
        self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="pending")],
        )
        self._last_mock_write.assert_not_called()
        self._last_mock_progress.assert_not_called()

    def test_multiple_required_items_missing_all_returned(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[
                _checklist_item(item_id="CLII-001", required=True, status="pending", title="Первый"),
                _checklist_item(item_id="CLII-002", required=True, status="blocked", title="Второй"),
            ],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(set(result["missing_checklist_item_ids"]), {"CLII-001", "CLII-002"})
        self.assertEqual(set(result["missing_checklist_item_titles"]), {"Первый", "Второй"})

    def test_cancelled_instance_never_blocks(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance(status="cancelled")],
            checklist_items=[_checklist_item(required=True, status="pending")],
        )
        self.assertTrue(result["ok"])

    def test_force_without_reason_rejected(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="pending")],
            force=True, reason=None,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED")

    def test_force_with_reason_completes_and_audits_missing_checklist_items(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
            force=True, reason="manager approved", actor="dida",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["override_applied"])
        self.assertEqual(result["override_type"], "missing_checklist_items")

        self._last_mock_record_override.assert_called_once_with(
            stage_id="STAGE-001", roadmap_id="RM-001", user="dida", reason="manager approved",
            missing_blocking_doc_ids=(), previous_status="in_progress", target_status="done",
            override_type="missing_checklist_items", configuration_error_details="",
            missing_checklist_instance_ids=("CLIN-001",), missing_checklist_item_ids=("CLII-001",),
            missing_checklist_item_titles=("Проверить",),
        )

    def test_force_with_reason_and_checklist_complete_completes_without_audit(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="done")],
            force=True, reason="just in case",
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["override_applied"])
        self._last_mock_record_override.assert_not_called()

    def test_audit_write_failure_after_successful_done_returns_warning_but_status_stays_done(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="pending")],
            force=True, reason="approved",
            record_override_result=_override_write_result(ok=False, error="append failed"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "done")
        self.assertTrue(result["partial_success"])
        self.assertTrue(any("append failed" in f for f in result["downstream_failures"]))

    def test_checklist_gate_not_evaluated_for_pending_to_in_progress(self):
        result = self._call(target_status="in_progress", stage=_stage(status="pending"))
        self._last_mock_checklist_instances.assert_not_called()
        self.assertTrue(result["ok"])

    def test_checklist_gate_not_evaluated_for_skipped(self):
        result = self._call(target_status="skipped", stage=_stage(status="in_progress"))
        self._last_mock_checklist_instances.assert_not_called()
        self.assertTrue(result["ok"])


class TestCombinedDocumentAndChecklistGate(_BaseTransitionTestCase):
    def test_both_gates_blocked_without_force_returns_combined_code(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_BLOCKED")
        self.assertEqual(result["missing_blocking_doc_ids"], ("DOC-008",))
        self.assertEqual(result["missing_checklist_item_ids"], ("CLII-001",))

    def test_both_gates_blocked_does_not_write(self):
        self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="pending")],
        )
        self._last_mock_write.assert_not_called()

    def test_both_gates_blocked_with_force_creates_single_combined_audit_row(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
            force=True, reason="both approved", actor="dida",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["override_applied"])
        self.assertEqual(result["override_type"], "missing_blocking_documents+missing_checklist_items")
        self._last_mock_record_override.assert_called_once()
        self.assertEqual(self._last_mock_record_override.call_count, 1)
        _, kwargs = self._last_mock_record_override.call_args
        self.assertEqual(kwargs["missing_blocking_doc_ids"], ("DOC-008",))
        self.assertEqual(kwargs["missing_checklist_item_ids"], ("CLII-001",))
        self.assertEqual(kwargs["override_type"], "missing_blocking_documents+missing_checklist_items")

    def test_only_document_blocked_checklist_clean_uses_document_only_code(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_DOCUMENT_GATE_BLOCKED")

    def test_only_checklist_blocked_document_clean_uses_checklist_only_code(self):
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(required=True, status="pending")],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_CHECKLIST_GATE_BLOCKED")


class TestUpdateStageStatusInSheetStillDocumentAgnostic(unittest.TestCase):
    """Phase 43 architectural guard: the gate lives ONLY in
    business_builder.transition_stage_status() — roadmap_manager.
    update_stage_status_in_sheet() must remain completely unaware of
    documents/relations, exactly as test_updatestage_reliability.py's
    TestNoCouplingToDocumentsOrRelationsOrGTD already locks in. Re-
    asserted here as a cross-file guard so a future edit to THIS phase
    can't accidentally weaken that invariant without a second, loud
    failure."""

    def test_update_stage_status_in_sheet_has_no_document_requirements_import(self):
        import business_core.roadmap_manager as rm
        import inspect
        src = inspect.getsource(rm.update_stage_status_in_sheet)
        self.assertNotIn("document_requirements", src)
        self.assertNotIn("evaluate_scope", src)
        self.assertNotIn("stage_entity_relations", src)
        self.assertNotIn("checklist", src.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
