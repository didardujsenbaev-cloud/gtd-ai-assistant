"""
Tests for Phase 36C — Task Domain Foundation: business_core/business_builder.py's
Task orchestration functions (ADR-019) — create_business_task(),
update_task_admin_fields(), transition_task_status(), assign_task(),
unassign_task(), task_assignment_cache_is_consistent().

Covers Business/relation validation, Roadmap/Stage lifecycle eligibility,
creation idempotency, admin-field policy, transition matrix, Organization
Role/Person eligibility reuse, and the Task Assignment current-row
invariant. No live Sheets writes — mocks only. Registered in conftest.py's
hard socket-block set (Phase 36C, ADR-019 §27) before this file's logic
was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

from business_core.business_builder import (
    create_business_task, update_task_admin_fields, transition_task_status,
    assign_task, unassign_task, task_assignment_cache_is_consistent,
)
from business_core.task_manager import list_tasks, _TASK_FIELDS

ACTIVE_TASK = {
    "task_id": "TSK-001", "business_id": "BIZ-001", "title": "Prepare docs",
    "description": "", "status": "new", "priority": "", "due_date": "",
    "source": "manual", "idempotency_key": "", "client_id": "", "object_id": "",
    "service_id": "", "roadmap_id": "", "stage_id": "",
    "responsible_role_id": "", "assignee_person_id": "",
    "created_at": "2026-01-01", "updated_at": "2026-01-01",
    "started_at": "", "completed_at": "", "cancelled_at": "",
    "created_by": "", "gtd_action_id": "",
}

ACTIVE_ROLE = {
    "row_num": 2, "role_id": "ROLE-001", "department_id": "DEPT-001",
    "role_name": "Coordinator", "reports_to_role_id": "", "role_type": "internal",
    "employment_model": "full_time", "status": "active",
    "purpose": "", "main_result": "", "notes": "",
}
PLANNED_ROLE = dict(ACTIVE_ROLE, status="planned")
PAUSED_ROLE = dict(ACTIVE_ROLE, status="paused")
ARCHIVED_ROLE = dict(ACTIVE_ROLE, status="archived")

ACTIVE_DEPARTMENT = {
    "row_num": 2, "department_id": "DEPT-001", "business_id": "BIZ-001",
    "department_name": "Operations", "parent_department_id": "",
    "head_role_id": "", "status": "active", "notes": "",
}
ARCHIVED_DEPARTMENT = dict(ACTIVE_DEPARTMENT, status="archived")

ACTIVE_PERSON = {
    "person_id": "PRS-001", "status": "active", "person_type": "internal",
    "biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-001",
}
ARCHIVED_PERSON = dict(ACTIVE_PERSON, status="archived")
UNLINKED_PERSON = dict(ACTIVE_PERSON, biz_ids=[])
OTHER_LINKED_PERSON = dict(ACTIVE_PERSON, biz_ids=["BIZ-999"])


# ─────────────────────────────────────────────────────────────
# create_business_task
# ─────────────────────────────────────────────────────────────

class TestCreateBusinessTaskBasics(unittest.TestCase):

    def test_missing_business_id_rejected(self):
        result = create_business_task("", "Title")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_business_not_found(self):
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = create_business_task("BIZ-999", "Title")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_missing_title_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})):
            result = create_business_task("BIZ-001", "")
        self.assertFalse(result["ok"])

    def test_business_and_title_only_succeeds(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[]), \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}):
            result = create_business_task("BIZ-001", "Title")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_CREATED")
        self.assertTrue(result["task_created"])
        self.assertEqual(result["final_status"], "new")


class TestCreateBusinessTaskRelationValidation(unittest.TestCase):

    def _base_patches(self):
        return [
            patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})),
            patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[]),
            patch("business_core.task_manager.create_task",
                  return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}),
        ]

    def test_invalid_client_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id", return_value=None):
            result = create_business_task("BIZ-001", "Title", client_id="PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_invalid_object_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.object_manager.find_object_by_id", return_value=None):
            result = create_business_task("BIZ-001", "Title", object_id="OBJ-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")

    def test_object_business_mismatch_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.object_manager.find_object_by_id", return_value={"object_id": "OBJ-001", "biz_id": "BIZ-999"}):
            result = create_business_task("BIZ-001", "Title", object_id="OBJ-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")

    def test_invalid_service_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.service_manager.find_service_by_id", return_value=None):
            result = create_business_task("BIZ-001", "Title", service_id="SVC-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")

    def test_service_business_mismatch_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.service_manager.find_service_by_id", return_value={"service_id": "SVC-001", "biz_id": "BIZ-999"}):
            result = create_business_task("BIZ-001", "Title", service_id="SVC-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")

    def test_invalid_roadmap_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=None):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_NOT_FOUND")

    def test_invalid_stage_rejected(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_stage_by_id", return_value=None):
            result = create_business_task("BIZ-001", "Title", stage_id="STAGE-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_stage_derives_roadmap_when_roadmap_omitted(self):
        stage = {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "status": "pending"}
        roadmap = {"roadmap_id": "RM-001", "status": "active", "object_id": "", "service_id": ""}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[]), \
             patch("business_core.task_manager.create_task") as mock_create:
            mock_create.return_value = {"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}
            result = create_business_task("BIZ-001", "Title", stage_id="STAGE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(mock_create.call_args[1]["roadmap_id"], "RM-001")

    def test_stage_roadmap_mismatch_rejected(self):
        stage = {"stage_id": "STAGE-001", "roadmap_id": "RM-002", "status": "pending"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-001", stage_id="STAGE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")

    def test_terminal_stage_rejected(self):
        stage = {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "status": "done"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage):
            result = create_business_task("BIZ-001", "Title", stage_id="STAGE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_TERMINAL")

    def test_skipped_stage_rejected(self):
        stage = {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "status": "skipped"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage):
            result = create_business_task("BIZ-001", "Title", stage_id="STAGE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_TERMINAL")

    def test_completed_roadmap_rejected(self):
        roadmap = {"roadmap_id": "RM-001", "status": "completed", "object_id": "", "service_id": ""}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_COMPLETED")

    def test_cancelled_roadmap_rejected(self):
        roadmap = {"roadmap_id": "RM-001", "status": "cancelled", "object_id": "", "service_id": ""}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_CANCELLED")

    def test_on_hold_roadmap_creation_allowed(self):
        roadmap = {"roadmap_id": "RM-001", "status": "on_hold", "object_id": "", "service_id": ""}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[]), \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-001")
        self.assertTrue(result["ok"])

    def test_roadmap_object_mismatch_rejected(self):
        roadmap = {"roadmap_id": "RM-001", "status": "active", "object_id": "OBJ-999", "service_id": ""}
        obj = {"object_id": "OBJ-001", "biz_id": "BIZ-001"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.object_manager.find_object_by_id", return_value=obj), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = create_business_task("BIZ-001", "Title", roadmap_id="RM-001", object_id="OBJ-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_ENTITY_RELATION_MISMATCH")


class TestCreateBusinessTaskIdempotency(unittest.TestCase):

    def test_zero_match_creates(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[]), \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}):
            result = create_business_task("BIZ-001", "Title", idempotency_key="KEY-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_CREATED")
        self.assertTrue(result["task_created"])

    def test_one_match_reuses(self):
        existing = {"task_id": "TSK-050", "status": "ready"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[existing]):
            result = create_business_task("BIZ-001", "Title", idempotency_key="KEY-1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_REUSED")
        self.assertTrue(result["task_reused"])
        self.assertEqual(result["task_id"], "TSK-050")

    def test_multiple_matches_block_with_all_ids(self):
        dup1 = {"task_id": "TSK-A", "status": "new"}
        dup2 = {"task_id": "TSK-B", "status": "new"}
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key", return_value=[dup1, dup2]):
            result = create_business_task("BIZ-001", "Title", idempotency_key="KEY-1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_TASK_IDEMPOTENCY_MATCHES")
        self.assertEqual(set(result["conflicting_task_ids"]), {"TSK-A", "TSK-B"})

    def test_blank_idempotency_key_creates_without_lookup(self):
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key") as mock_lookup, \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}):
            result = create_business_task("BIZ-001", "Title")
        self.assertTrue(result["ok"])
        mock_lookup.assert_not_called()

    def test_no_title_based_dedup(self):
        """Two calls with the same title but no idempotency key must
        never be treated as duplicates — title-based dedup is
        forbidden (ADR-019 §10/§23)."""
        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-001"})), \
             patch("business_core.task_manager.find_tasks_by_idempotency_key") as mock_lookup, \
             patch("business_core.task_manager.create_task",
                   return_value={"ok": True, "task_id": "TSK-001", "code": "TASK_CREATED", "error": None}) as mock_create:
            create_business_task("BIZ-001", "Same Title")
            create_business_task("BIZ-001", "Same Title")
        mock_lookup.assert_not_called()
        self.assertEqual(mock_create.call_count, 2)


class TestTaskIdGeneratedOnlyAfterValidation(unittest.TestCase):

    def test_no_task_creation_call_when_validation_fails(self):
        with patch("business_core.sheets.find_row_by_id", return_value=None), \
             patch("business_core.task_manager.create_task") as mock_create:
            create_business_task("BIZ-999", "Title")
        mock_create.assert_not_called()


# ─────────────────────────────────────────────────────────────
# update_task_admin_fields (orchestration wrapper)
# ─────────────────────────────────────────────────────────────

class TestUpdateTaskAdminFieldsOrchestration(unittest.TestCase):

    def test_task_not_found(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=None):
            result = update_task_admin_fields("TSK-999", {"Title": "X"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")

    def test_delegates_to_low_level_and_wraps_result(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.update_task_admin_fields",
                   return_value={"ok": True, "changed": True, "updated_fields": ("Title",), "code": "TASK_ADMIN_FIELDS_UPDATED", "error": None}):
            result = update_task_admin_fields("TSK-001", {"Title": "New"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_ADMIN_FIELDS_UPDATED")
        self.assertEqual(result["business_id"], "BIZ-001")


# ─────────────────────────────────────────────────────────────
# transition_task_status
# ─────────────────────────────────────────────────────────────

class TestTransitionTaskStatus(unittest.TestCase):

    def test_task_not_found(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=None):
            result = transition_task_status("TSK-999", "ready")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")

    def test_invalid_status_rejected(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)):
            result = transition_task_status("TSK-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_STATUS")

    def test_new_to_ready_allowed(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.update_task_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = transition_task_status("TSK-001", "ready")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_STATUS_UPDATED")
        self.assertEqual(result["final_status"], "ready")

    def test_unchanged_status_no_op(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.update_task_status", return_value={"ok": True, "changed": False, "code": "", "error": None}):
            result = transition_task_status("TSK-001", "new")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_STATUS_UNCHANGED")

    def test_invalid_transition_blocked(self):
        task = dict(ACTIVE_TASK, status="blocked")
        with patch("business_core.task_manager.find_task_by_id", return_value=task):
            result = transition_task_status("TSK-001", "new")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_TASK_TRANSITION")

    def test_reopen_from_done_blocked(self):
        task = dict(ACTIVE_TASK, status="done")
        with patch("business_core.task_manager.find_task_by_id", return_value=task):
            result = transition_task_status("TSK-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def test_reopen_from_cancelled_blocked(self):
        task = dict(ACTIVE_TASK, status="cancelled")
        with patch("business_core.task_manager.find_task_by_id", return_value=task):
            result = transition_task_status("TSK-001", "ready")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def test_reopen_from_skipped_blocked(self):
        task = dict(ACTIVE_TASK, status="skipped")
        with patch("business_core.task_manager.find_task_by_id", return_value=task):
            result = transition_task_status("TSK-001", "ready")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def test_done_stays_done_ordinarily(self):
        task = dict(ACTIVE_TASK, status="done")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.update_task_status", return_value={"ok": True, "changed": False, "code": "", "error": None}):
            result = transition_task_status("TSK-001", "done")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_STATUS_UNCHANGED")

    def test_matrix_every_ready_target(self):
        task = dict(ACTIVE_TASK, status="ready")
        for target in ("in_progress", "waiting", "blocked", "done", "cancelled", "skipped"):
            with patch("business_core.task_manager.find_task_by_id", return_value=task), \
                 patch("business_core.task_manager.update_task_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
                result = transition_task_status("TSK-001", target)
            self.assertTrue(result["ok"], f"ready -> {target} should be allowed")

    def test_started_at_timestamp_passed_when_blank(self):
        task = dict(ACTIVE_TASK, status="ready", started_at="")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.update_task_status") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            transition_task_status("TSK-001", "in_progress")
        self.assertEqual(mock_update.call_args[1]["timestamp_field"], "Started At")

    def test_started_at_not_repassed_when_already_set(self):
        task = dict(ACTIVE_TASK, status="ready", started_at="2026-01-01")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.update_task_status") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            transition_task_status("TSK-001", "in_progress")
        self.assertEqual(mock_update.call_args[1]["timestamp_field"], "")

    def test_completed_at_timestamp_on_done(self):
        task = dict(ACTIVE_TASK, status="ready")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.update_task_status") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            transition_task_status("TSK-001", "done")
        self.assertEqual(mock_update.call_args[1]["timestamp_field"], "Completed At")

    def test_cancelled_at_timestamp_on_cancelled(self):
        task = dict(ACTIVE_TASK, status="ready")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.update_task_status") as mock_update:
            mock_update.return_value = {"ok": True, "changed": True, "code": "", "error": None}
            transition_task_status("TSK-001", "cancelled")
        self.assertEqual(mock_update.call_args[1]["timestamp_field"], "Cancelled At")

    def test_roadmap_on_hold_blocks_in_progress_only(self):
        task = dict(ACTIVE_TASK, status="ready", roadmap_id="RM-001")
        roadmap = {"roadmap_id": "RM-001", "status": "on_hold"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = transition_task_status("TSK-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_ON_HOLD")

    def test_roadmap_on_hold_allows_waiting(self):
        task = dict(ACTIVE_TASK, status="ready", roadmap_id="RM-001")
        roadmap = {"roadmap_id": "RM-001", "status": "on_hold"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s), \
             patch("business_core.task_manager.update_task_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = transition_task_status("TSK-001", "waiting")
        self.assertTrue(result["ok"])

    def test_completed_roadmap_blocks_execution_transition(self):
        task = dict(ACTIVE_TASK, status="ready", roadmap_id="RM-001")
        roadmap = {"roadmap_id": "RM-001", "status": "completed"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = transition_task_status("TSK-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_COMPLETED")

    def test_cancelled_roadmap_blocks_execution_transition(self):
        task = dict(ACTIVE_TASK, status="ready", roadmap_id="RM-001")
        roadmap = {"roadmap_id": "RM-001", "status": "cancelled"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_manager.normalize_roadmap_status", side_effect=lambda s: s):
            result = transition_task_status("TSK-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_CANCELLED")

    def test_no_roadmap_manager_write_call(self):
        path = WORKSPACE / "business_core" / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("def transition_task_status(")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        for forbidden in ("update_stage_status_in_sheet(", "update_stage_fields(", "maybe_complete_roadmap("):
            self.assertNotIn(forbidden, body)


# ─────────────────────────────────────────────────────────────
# assign_task
# ─────────────────────────────────────────────────────────────

def _assign_patches(**overrides):
    defaults = dict(
        find_task_by_id=dict(ACTIVE_TASK),
        find_role_by_id=dict(ACTIVE_ROLE),
        find_department_by_id=dict(ACTIVE_DEPARTMENT),
        find_person_by_id=dict(ACTIVE_PERSON),
        is_person_archived=False,
        has_person_business_link=True,
        list_task_assignments_for_task=[],
        create_task_assignment={"ok": True, "task_assignment_id": "TAS-NEW", "code": "TASK_ASSIGNMENT_CREATED", "error": None},
        end_task_assignment={"ok": True, "changed": True, "code": "", "error": None},
        update_task_assignment_cache={"ok": True, "changed": True, "code": "", "error": None},
    )
    defaults.update(overrides)
    return [
        patch("business_core.task_manager.find_task_by_id", return_value=defaults["find_task_by_id"]),
        patch("business_core.organization_manager.find_role_by_id", return_value=defaults["find_role_by_id"]),
        patch("business_core.organization_manager.find_department_by_id", return_value=defaults["find_department_by_id"]),
        patch("business_core.person_manager.find_person_by_id", return_value=defaults["find_person_by_id"]),
        patch("business_core.person_manager.is_person_archived", return_value=defaults["is_person_archived"]),
        patch("business_core.person_manager.has_person_business_link", return_value=defaults["has_person_business_link"]),
        patch("business_core.task_manager.list_task_assignments_for_task", return_value=defaults["list_task_assignments_for_task"]),
        patch("business_core.task_manager.create_task_assignment", return_value=defaults["create_task_assignment"]),
        patch("business_core.task_manager.end_task_assignment", return_value=defaults["end_task_assignment"]),
        patch("business_core.task_manager.update_task_assignment_cache", return_value=defaults["update_task_assignment_cache"]),
    ]


class TestAssignTaskRoleOnly(unittest.TestCase):

    def test_role_only_active_allowed(self):
        patches = _assign_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001", start_date="2026-01-01")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_ASSIGNMENT_CREATED")

    def test_role_not_found(self):
        patches = _assign_patches(find_role_by_id=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_NOT_FOUND")

    def test_planned_role_only_allowed(self):
        patches = _assign_patches(find_role_by_id=dict(PLANNED_ROLE))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertTrue(result["ok"])

    def test_paused_role_blocked(self):
        patches = _assign_patches(find_role_by_id=dict(PAUSED_ROLE))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_PAUSED")

    def test_archived_role_blocked(self):
        patches = _assign_patches(find_role_by_id=dict(ARCHIVED_ROLE))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_ARCHIVED")

    def test_department_not_found(self):
        patches = _assign_patches(find_department_by_id=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DEPARTMENT_NOT_FOUND")

    def test_department_archived(self):
        patches = _assign_patches(find_department_by_id=dict(ARCHIVED_DEPARTMENT))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DEPARTMENT_ARCHIVED")


class TestAssignTaskPersonOnly(unittest.TestCase):

    def test_person_only_eligible_allowed(self):
        patches = _assign_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", assignee_person_id="PRS-001")
        self.assertTrue(result["ok"])

    def test_missing_person_blocked(self):
        patches = _assign_patches(find_person_by_id=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", assignee_person_id="PRS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_FOUND")

    def test_archived_person_blocked(self):
        patches = _assign_patches(find_person_by_id=dict(ARCHIVED_PERSON), is_person_archived=True)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", assignee_person_id="PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_ARCHIVED")

    def test_person_not_linked_to_business(self):
        patches = _assign_patches(find_person_by_id=dict(UNLINKED_PERSON), has_person_business_link=False)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001", assignee_person_id="PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_NOT_LINKED_TO_BUSINESS")

    def test_person_business_mismatch(self):
        patches = _assign_patches(find_person_by_id=dict(OTHER_LINKED_PERSON), has_person_business_link=False)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001", assignee_person_id="PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PERSON_TASK_BUSINESS_MISMATCH")

    def test_planned_role_with_person_execution_blocked(self):
        patches = _assign_patches(find_role_by_id=dict(PLANNED_ROLE))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001", assignee_person_id="PRS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION")


class TestAssignTaskCurrentRowInvariant(unittest.TestCase):

    def test_no_role_or_person_rejected(self):
        patches = _assign_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001")
        self.assertFalse(result["ok"])

    def test_task_not_found(self):
        patches = _assign_patches(find_task_by_id=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-999", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")

    def test_zero_active_creates(self):
        patches = _assign_patches(list_task_assignments_for_task=[])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_ASSIGNMENT_CREATED")

    def test_same_request_reuses(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        patches = _assign_patches(list_task_assignments_for_task=[current])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_ASSIGNMENT_REUSED")
        self.assertEqual(result["assignment_id"], "TAS-050")

    def test_different_request_reassigns_and_ends_prior(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-002", "assignee_person_id": "", "status": "active"}
        patches = _assign_patches(list_task_assignments_for_task=[current])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8] as mock_end, patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_REASSIGNED")
        self.assertEqual(result["previous_assignment_id"], "TAS-050")
        mock_end.assert_called_once_with("TAS-050")

    def test_multiple_active_block_with_all_ids(self):
        dup1 = {"task_assignment_id": "TAS-A", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        dup2 = {"task_assignment_id": "TAS-B", "responsible_role_id": "ROLE-002", "assignee_person_id": "", "status": "active"}
        patches = _assign_patches(list_task_assignments_for_task=[dup1, dup2])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            result = assign_task("TSK-001", responsible_role_id="ROLE-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR")
        self.assertEqual(set(result["conflicting_assignment_ids"]), {"TAS-A", "TAS-B"})


# ─────────────────────────────────────────────────────────────
# unassign_task
# ─────────────────────────────────────────────────────────────

class TestUnassignTask(unittest.TestCase):

    def test_blank_task_id(self):
        result = unassign_task("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")
        self.assertTrue(result["retry_safe"])

    def test_task_not_found(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=None):
            result = unassign_task("TSK-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_NOT_FOUND")
        self.assertTrue(result["retry_safe"])

    def test_zero_active_is_noop_success(self):
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[]):
            result = unassign_task("TSK-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_UNASSIGNED")
        self.assertFalse(result["changed"])
        self.assertFalse(result["assignment_changed"])
        self.assertFalse(result["cache_changed"])
        self.assertFalse(result["partial_state"])
        self.assertFalse(result["manual_review_required"])
        self.assertTrue(result["retry_safe"])

    def test_one_active_ends_and_clears_cache(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_cache:
            result = unassign_task("TSK-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_UNASSIGNED")
        mock_end.assert_called_once_with("TAS-050")
        mock_cache.assert_called_once_with("TSK-001", "", "")
        self.assertTrue(result["changed"])
        self.assertTrue(result["assignment_changed"])
        self.assertTrue(result["cache_changed"])
        self.assertFalse(result["partial_state"])
        self.assertFalse(result["manual_review_required"])
        self.assertTrue(result["retry_safe"])

    def test_multiple_active_block(self):
        dup1 = {"task_assignment_id": "TAS-A", "status": "active"}
        dup2 = {"task_assignment_id": "TAS-B", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[dup1, dup2]):
            result = unassign_task("TSK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR")

    def test_assignment_end_failure_cache_never_called_and_no_partial_state(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": False, "changed": False, "code": "", "error": "ASSIGNMENT-SECRET-end-failure"}) as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache") as mock_cache:
            result = unassign_task("TSK-001")
        mock_end.assert_called_once_with("TAS-050")
        mock_cache.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertFalse(result["changed"])
        self.assertFalse(result["partial_state"])
        self.assertFalse(result["manual_review_required"])

    def test_cache_clear_failure_after_assignment_end_is_partial_state_not_success(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache", return_value={"ok": False, "changed": False, "code": "", "error": "CACHE-SECRET-write-failure"}) as mock_cache:
            result = unassign_task("TSK-001")
        mock_end.assert_called_once_with("TAS-050")
        mock_cache.assert_called_once_with("TSK-001", "", "")
        self.assertFalse(result["ok"])
        self.assertNotEqual(result["code"], "TASK_UNASSIGNED")
        self.assertEqual(result["code"], "TASK_UNASSIGNMENT_PARTIAL_FAILURE")
        self.assertTrue(result["changed"])
        self.assertTrue(result["assignment_changed"])
        self.assertFalse(result["cache_changed"])
        self.assertTrue(result["partial_state"])
        self.assertTrue(result["manual_review_required"])
        self.assertFalse(result["retry_safe"])
        self.assertEqual(result["previous_assignment_id"], "TAS-050")

    def test_cache_clear_exception_converted_by_low_level_helper_is_also_partial_state(self):
        """update_task_assignment_cache already converts an internal
        exception into ok=False/error=str(exc) before returning — this
        proves unassign_task treats that exact shape identically to an
        explicit ok=False, with no special-casing of exception origin."""
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.task_manager.update_task_assignment_cache", return_value={"ok": False, "changed": False, "code": "", "error": "API-PAYLOAD-SECRET: boom"}):
            result = unassign_task("TSK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TASK_UNASSIGNMENT_PARTIAL_FAILURE")
        self.assertTrue(result["partial_state"])

    def test_sequential_retry_after_partial_state_remains_noop_and_does_not_repair_cache(self):
        """Documents residual behavior (not a fix): once the active Task
        Assignment has ended, a repeated unassign_task call sees zero
        active assignments and takes the no-op branch — it never re-runs
        update_task_assignment_cache and therefore never repairs a Task
        row left with stale cache fields after a partial failure."""
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[]), \
             patch("business_core.task_manager.update_task_assignment_cache") as mock_cache:
            result = unassign_task("TSK-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "TASK_UNASSIGNED")
        self.assertFalse(result["partial_state"])
        mock_cache.assert_not_called()

    def test_no_retry_loop_single_call_each(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": False, "changed": False, "code": "", "error": "boom"}) as mock_end, \
             patch("business_core.task_manager.update_task_assignment_cache") as mock_cache:
            unassign_task("TSK-001")
        self.assertEqual(mock_end.call_count, 1)
        self.assertEqual(mock_cache.call_count, 0)

    def test_cache_clear_never_called_before_assignment_end(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        call_order = []

        def _record_end(*args, **kwargs):
            call_order.append("end")
            return {"ok": True, "changed": True, "code": "", "error": None}

        def _record_cache(*args, **kwargs):
            call_order.append("cache")
            return {"ok": True, "changed": True, "code": "", "error": None}

        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", side_effect=_record_end), \
             patch("business_core.task_manager.update_task_assignment_cache", side_effect=_record_cache):
            unassign_task("TSK-001")
        self.assertEqual(call_order, ["end", "cache"])

    def test_partial_failure_fields_contain_no_raw_exception_markers(self):
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        markers = ("TASK-SECRET", "ASSIGNMENT-SECRET", "CACHE-SECRET", "API-PAYLOAD-SECRET")
        with patch("business_core.task_manager.find_task_by_id", return_value=dict(ACTIVE_TASK)), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]), \
             patch("business_core.task_manager.end_task_assignment", return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.task_manager.update_task_assignment_cache", return_value={"ok": False, "changed": False, "code": "", "error": "CACHE-SECRET TASK-SECRET ASSIGNMENT-SECRET API-PAYLOAD-SECRET"}):
            result = unassign_task("TSK-001")
        for marker in markers:
            self.assertNotIn(marker, result["code"] or "")
            self.assertNotIn(marker, result["error"] or "")


# ─────────────────────────────────────────────────────────────
# task_assignment_cache_is_consistent
# ─────────────────────────────────────────────────────────────

class TestAssignmentCacheConsistency(unittest.TestCase):

    def test_consistent_when_matching(self):
        task = dict(ACTIVE_TASK, responsible_role_id="ROLE-001", assignee_person_id="")
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]):
            result = task_assignment_cache_is_consistent("TSK-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["consistent"])

    def test_inconsistent_when_mismatched(self):
        task = dict(ACTIVE_TASK, responsible_role_id="ROLE-999", assignee_person_id="")
        current = {"task_assignment_id": "TAS-050", "responsible_role_id": "ROLE-001", "assignee_person_id": "", "status": "active"}
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[current]):
            result = task_assignment_cache_is_consistent("TSK-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["consistent"])

    def test_consistent_when_unassigned_and_cache_blank(self):
        task = dict(ACTIVE_TASK, responsible_role_id="", assignee_person_id="")
        with patch("business_core.task_manager.find_task_by_id", return_value=task), \
             patch("business_core.task_manager.list_task_assignments_for_task", return_value=[]):
            result = task_assignment_cache_is_consistent("TSK-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["consistent"])


# ─────────────────────────────────────────────────────────────
# list_tasks — strict error-contract mode (raise_on_error)
# ─────────────────────────────────────────────────────────────

def _task_row_values(task_id="TSK-001", business_id="BIZ-001", title="Prepare docs",
                      status="ready", roadmap_id="", stage_id="",
                      responsible_role_id="", assignee_person_id="", due_date=""):
    values = {
        "Task ID": task_id, "Business ID": business_id, "Title": title,
        "Description": "", "Status": status, "Priority": "", "Due Date": due_date,
        "Source": "manual", "Idempotency Key": "", "Client ID": "", "Object ID": "",
        "Service ID": "", "Roadmap ID": roadmap_id, "Stage ID": stage_id,
        "Responsible Role ID": responsible_role_id, "Assignee Person ID": assignee_person_id,
        "Created At": "2026-01-01", "Updated At": "2026-01-01",
        "Started At": "", "Completed At": "", "Cancelled At": "",
        "Created By": "", "GTD Action ID": "",
    }
    return [values[f] for f in _TASK_FIELDS]


def _mock_sheet(rows):
    sheet = unittest.mock.MagicMock()
    sheet.get_all_values.return_value = [list(_TASK_FIELDS)] + rows
    return sheet


def _fresh_tm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.task_manager")


class TestListTasksStrictErrorMode(unittest.TestCase):

    def test_default_call_backward_compatible(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([])):
            result = list_tasks()
        self.assertEqual(result, [])

    def test_zero_result_default_mode(self):
        row = _task_row_values(business_id="BIZ-001")
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row])):
            result = list_tasks(business_id="BIZ-999")
        self.assertEqual(result, [])

    def test_zero_result_raise_on_error_true(self):
        row = _task_row_values(business_id="BIZ-001")
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row])):
            result = list_tasks(business_id="BIZ-999", raise_on_error=True)
        self.assertEqual(result, [])

    def test_matching_rows_identical_in_both_modes(self):
        row = _task_row_values(task_id="TSK-001", business_id="BIZ-001", title="Prepare docs")
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row])):
            default_result = list_tasks(business_id="BIZ-001")
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row])):
            strict_result = list_tasks(business_id="BIZ-001", raise_on_error=True)
        self.assertEqual(default_result, strict_result)
        self.assertEqual(len(default_result), 1)
        self.assertEqual(default_result[0]["task_id"], "TSK-001")

    def test_every_filter_behaves_identically_in_both_modes(self):
        matching = _task_row_values(
            task_id="TSK-001", business_id="BIZ-001", status="ready",
            roadmap_id="RM-001", stage_id="STAGE-001",
            responsible_role_id="ROLE-001", assignee_person_id="PRS-001",
        )
        other_business = _task_row_values(task_id="TSK-002", business_id="BIZ-002")
        rows = [matching, other_business]
        filters = dict(
            business_id="BIZ-001", status="ready", roadmap_id="RM-001",
            stage_id="STAGE-001", role_id="ROLE-001", person_id="PRS-001",
        )
        for key in filters:
            with self.subTest(filter=key):
                kwargs = {key: filters[key]}
                with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet(rows)):
                    default_result = list_tasks(**kwargs)
                with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet(rows)):
                    strict_result = list_tasks(**kwargs, raise_on_error=True)
                self.assertEqual(default_result, strict_result)

    def test_storage_exception_default_mode_returns_empty(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER")):
            result = list_tasks()
        self.assertEqual(result, [])

    def test_storage_exception_raise_on_error_true_propagates(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER")):
            with self.assertRaises(RuntimeError) as ctx:
                list_tasks(raise_on_error=True)
        self.assertIn("STRICT-MODE-SECRET-MARKER", str(ctx.exception))

    def test_strict_mode_does_not_return_partial_result(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER")):
            with self.assertRaises(RuntimeError):
                result = list_tasks(raise_on_error=True)
                # If control reached here, a partial value would exist —
                # the assertRaises context proves it never did.
                del result

    def test_strict_mode_performs_no_retry(self):
        mock_getter = unittest.mock.MagicMock(side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER"))
        with patch("business_core.sheets.get_business_sheet", mock_getter):
            with self.assertRaises(RuntimeError):
                list_tasks(raise_on_error=True)
        self.assertEqual(mock_getter.call_count, 1)

    def test_strict_mode_does_not_log_before_propagating(self):
        tm = _fresh_tm()
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER")), \
             patch.object(tm, "log") as mock_log:
            with self.assertRaises(RuntimeError):
                tm.list_tasks(raise_on_error=True)
            mock_log.warning.assert_not_called()
            mock_log.error.assert_not_called()
            for call in mock_log.mock_calls:
                self.assertNotIn("STRICT-MODE-SECRET-MARKER", str(call))

    def test_default_mode_preserves_currently_approved_logging(self):
        tm = _fresh_tm()
        with patch("business_core.sheets.get_business_sheet", side_effect=RuntimeError("STRICT-MODE-SECRET-MARKER")), \
             patch.object(tm, "log") as mock_log:
            result = tm.list_tasks()
        self.assertEqual(result, [])
        mock_log.warning.assert_called_once()
        self.assertIn("STRICT-MODE-SECRET-MARKER", str(mock_log.warning.call_args))

    def test_returned_row_order_unchanged(self):
        row1 = _task_row_values(task_id="TSK-001", business_id="BIZ-001")
        row2 = _task_row_values(task_id="TSK-002", business_id="BIZ-001")
        row3 = _task_row_values(task_id="TSK-003", business_id="BIZ-001")
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row1, row2, row3])):
            result = list_tasks(business_id="BIZ-001")
        self.assertEqual([t["task_id"] for t in result], ["TSK-001", "TSK-002", "TSK-003"])

    def test_six_positional_parameters_still_work(self):
        row = _task_row_values(
            task_id="TSK-001", business_id="BIZ-001", status="ready",
            roadmap_id="RM-001", stage_id="STAGE-001",
            responsible_role_id="ROLE-001", assignee_person_id="PRS-001",
        )
        with patch("business_core.sheets.get_business_sheet", return_value=_mock_sheet([row])):
            result = list_tasks("BIZ-001", "ready", "RM-001", "STAGE-001", "ROLE-001", "PRS-001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["task_id"], "TSK-001")

    def test_raise_on_error_is_keyword_only(self):
        with self.assertRaises(TypeError):
            list_tasks("BIZ-001", "", "", "", "", "", True)

    def test_bctasks_caller_uses_raise_on_error_true(self):
        # bctasks_cmd is the one authorized caller of list_tasks that
        # must opt into strict mode — a storage failure must never be
        # silently indistinguishable from a genuinely empty, authorized
        # Business (business_core/telegram_handlers.py::bctasks_cmd's
        # own architecture guards prove the exact call shape; this is
        # a coarse source-text confirmation that the opt-in exists).
        import inspect
        from business_core import telegram_handlers as th
        src = inspect.getsource(th.bctasks_cmd)
        self.assertIn("raise_on_error=True", src)
        self.assertNotIn("raise_on_error=False", src)


if __name__ == "__main__":
    unittest.main()
