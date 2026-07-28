"""
Phase B — Required Output Completion Gate.

Covers:
- business_core.business_builder._evaluate_output_completion_gate()
  (unit-level, mocked resolve/relations/instances/template lookups)
- business_core.business_builder.transition_stage_status()'s wiring of
  the Output Gate as a third gate alongside Document/Checklist (via
  test_stage_transition_foundation.py's shared _BaseTransitionTestCase
  harness)
- business_core.roadmap_manager.record_stage_completion_override()'s
  four new additive Output audit fields
- business_core.telegram_handlers._stage_transition_failure_message()/
  _stage_transition_success_lines() Output-section rendering

No live Sheets writes — mocks only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

from test_stage_transition_foundation import (
    _BaseTransitionTestCase, _stage, _override_write_result,
)


def _fresh_bb():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.business_builder as bb
    return bb


_RESOLVED_OK = {
    "ok": True, "code": "", "error": None,
    "template_stage_id": "TSTG-029",
    "roadmap": {"roadmap_id": "RM-003", "business_id": "BIZ-001", "service_id": "SVC-001", "object_id": "OBJ-001"},
}


def _relation(entity_id="SOUT-001", blocking="true", status="active"):
    return {
        "Relation ID": "REL-100", "Template Stage ID": "TSTG-029", "Stage ID": "",
        "Entity Type": "required_output", "Entity ID": entity_id,
        "Blocking": blocking, "Required": "true", "Status": status,
    }


def _instance(output_template_id="SOUT-001", instance_id="SOUTI-001",
              blocking="true", status="pending", title="Подписанный договор"):
    return {
        "Output Instance ID": instance_id, "Output Template ID": output_template_id,
        "Stage ID": "STAGE-013", "Blocking": blocking, "Required": "true",
        "Status": status, "Title Snapshot": title,
    }


def _template(output_template_id="SOUT-001", title="Подписанный договор"):
    return {"Output Template ID": output_template_id, "Title": title, "Status": "active"}


# ────────────────────────────────────────────────────────────
# Unit tests: _evaluate_output_completion_gate() directly
# ────────────────────────────────────────────────────────────

class TestOutputGateBlockingStatuses(unittest.TestCase):
    """п.1-9: which instance statuses/flags block."""

    def _gate_for_instance(self, **instance_overrides):
        bb = _fresh_bb()
        inst = _instance(**instance_overrides)
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(inst,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            return bb._evaluate_output_completion_gate("STAGE-013")

    def test_pending_blocks(self):
        self.assertTrue(self._gate_for_instance(status="pending").blocked)

    def test_produced_blocks(self):
        self.assertTrue(self._gate_for_instance(status="produced").blocked)

    def test_submitted_blocks(self):
        self.assertTrue(self._gate_for_instance(status="submitted").blocked)

    def test_rejected_blocks(self):
        self.assertTrue(self._gate_for_instance(status="rejected").blocked)

    def test_accepted_does_not_block(self):
        self.assertFalse(self._gate_for_instance(status="accepted").blocked)

    def test_waived_does_not_block(self):
        self.assertFalse(self._gate_for_instance(status="waived").blocked)

    def test_not_applicable_does_not_block(self):
        self.assertFalse(self._gate_for_instance(status="not_applicable").blocked)

    def test_blocking_false_does_not_block(self):
        self.assertFalse(self._gate_for_instance(status="pending", blocking="false").blocked)

    def test_required_false_blocking_true_still_blocks(self):
        bb = _fresh_bb()
        inst = _instance(status="pending")
        inst["Required"] = "false"
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(inst,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertTrue(result.blocked)


class TestOutputGateRelationSources(unittest.TestCase):
    """п.10-13: relation-without-instance / inactive-relation / instance
    outliving its relation."""

    def test_active_blocking_relation_without_instance_blocks_as_instance_missing(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_relation(),)), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_template()):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertTrue(result.blocked)
        self.assertEqual(result.missing_blocking_output_instance_ids, ("",))
        self.assertEqual(result.missing_blocking_output_template_ids, ("SOUT-001",))
        self.assertEqual(result.missing_blocking_output_titles, ("Подписанный договор",))
        self.assertEqual(result.missing_blocking_output_statuses, ("instance_missing",))

    def test_active_non_blocking_relation_without_instance_does_not_block(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_relation(blocking="false"),)), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_template()):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertFalse(result.blocked)

    def test_inactive_relation_without_instance_does_not_block(self):
        """get_relations_for_template_stage() defaults to active-only —
        an inactive relation is simply never returned, so it can never
        surface here at all."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertFalse(result.blocked)

    def test_existing_blocking_instance_blocks_despite_inactive_template_and_no_relation(self):
        """п.13: the instance's OWN Blocking field is the source of
        truth — deactivating/deleting the Template or its relation
        afterward never exempts an already-created blocking instance."""
        bb = _fresh_bb()
        inst = _instance(status="submitted")
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(inst,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertTrue(result.blocked)
        self.assertEqual(result.missing_blocking_output_instance_ids, ("SOUTI-001",))

    def test_resolution_failure_does_not_suppress_existing_blocking_instance(self):
        """Source B (instances) is independent of Template Stage
        resolution succeeding — a resolution failure never becomes a
        gate bypass for an already-existing blocking instance."""
        bb = _fresh_bb()
        failed_resolve = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "", "template_stage_id": ""}
        inst = _instance(status="pending")
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed_resolve), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage") as mock_relations, \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(inst,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        mock_relations.assert_not_called()
        self.assertTrue(result.blocked)


class TestOutputGateDeduplication(unittest.TestCase):
    def test_relation_and_instance_for_same_output_not_duplicated(self):
        """п.14: an active blocking relation whose instance already
        exists (the common case) must appear exactly once, not twice."""
        bb = _fresh_bb()
        inst = _instance(status="submitted")
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_relation(),)), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(inst,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_template()):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertEqual(len(result.missing_blocking_output_instance_ids), 1)
        self.assertEqual(result.missing_blocking_output_instance_ids, ("SOUTI-001",))

    def test_no_relations_no_instances_not_blocked(self):
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=None):
            result = bb._evaluate_output_completion_gate("STAGE-013")
        self.assertFalse(result.blocked)
        self.assertEqual(result.missing_blocking_output_instance_ids, ())


# ────────────────────────────────────────────────────────────
# transition_stage_status() wiring — via the shared harness
# ────────────────────────────────────────────────────────────

class TestOutputGateTransitionWiring(_BaseTransitionTestCase):
    def test_output_only_blocking_response(self):
        """п.15: output-only blocking response, no Document/Checklist noise."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_OUTPUT_GATE_BLOCKED")
        self.assertEqual(result["missing_blocking_output_template_ids"], ("SOUT-001",))
        self.assertEqual(result["missing_blocking_doc_ids"], ())
        self.assertEqual(result["missing_checklist_instance_ids"], ())

    def test_document_and_output_combined(self):
        """п.16."""
        from test_stage_transition_foundation import _blocking_missing_scope_result
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_BLOCKED")
        self.assertEqual(result["missing_blocking_doc_ids"], ("DOC-008",))
        self.assertEqual(result["missing_blocking_output_template_ids"], ("SOUT-001",))

    def test_checklist_and_output_combined(self):
        """п.17."""
        from test_stage_transition_foundation import _checklist_instance, _checklist_item
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_BLOCKED")
        self.assertEqual(result["missing_checklist_item_ids"], ("CLII-001",))
        self.assertEqual(result["missing_blocking_output_template_ids"], ("SOUT-001",))

    def test_document_checklist_and_output_combined(self):
        """п.18."""
        from test_stage_transition_foundation import (
            _blocking_missing_scope_result, _checklist_instance, _checklist_item,
        )
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            evaluate_scope_result=_blocking_missing_scope_result(doc_ids=("DOC-008",)),
            checklist_instances=[_checklist_instance()],
            checklist_items=[_checklist_item(item_id="CLII-001", required=True, status="pending", title="Проверить")],
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
            force=True, reason="полный форс всех трёх гейтов", actor="dida",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["override_applied"])
        # п.20: канонический порядок join.
        self.assertEqual(
            result["override_type"],
            "missing_blocking_documents+missing_checklist_items+missing_blocking_outputs",
        )
        # п.19: одна audit-строка.
        self._last_mock_record_override.assert_called_once()
        # п.21: все 4 output-поля переданы.
        _, kwargs = self._last_mock_record_override.call_args
        self.assertEqual(kwargs["missing_blocking_output_template_ids"], ("SOUT-001",))
        self.assertEqual(kwargs["missing_blocking_output_instance_ids"], ("",))
        self.assertEqual(kwargs["missing_blocking_output_titles"], ("Подписанный договор",))
        self.assertEqual(kwargs["missing_blocking_output_statuses"], ("instance_missing",))

    def test_instance_missing_records_template_id_title_status(self):
        """п.22."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(title="Подписанный договор с клиентом"),
            force=True, reason="test",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing_blocking_output_instance_ids"], ("",))
        self.assertEqual(result["missing_blocking_output_template_ids"], ("SOUT-001",))
        self.assertEqual(result["missing_blocking_output_titles"], ("Подписанный договор с клиентом",))
        self.assertEqual(result["missing_blocking_output_statuses"], ("instance_missing",))

    def test_force_without_reason_rejected(self):
        """п.23."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
            force=True, reason="",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED")

    def test_force_with_reason_completes(self):
        """п.24."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
            force=True, reason="одобрено",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["override_type"], "missing_blocking_outputs")
        self.assertTrue(result["override_applied"])

    def test_failed_transition_does_not_change_stage(self):
        """п.25."""
        result = self._call(
            target_status="done", stage=_stage(status="in_progress"),
            resolve_template_stage_result=_RESOLVED_OK,
            output_relations=(_relation(),),
            output_template_lookup=lambda otid: _template(),
        )
        self.assertFalse(result["ok"])
        self._last_mock_write.assert_not_called()
        self._last_mock_record_override.assert_not_called()

    def test_accepted_waived_not_applicable_no_longer_block(self):
        for status in ("accepted", "waived", "not_applicable"):
            inst = _instance(status=status)
            result = self._call(
                target_status="done", stage=_stage(status="in_progress"),
                output_instances=(inst,),
            )
            self.assertTrue(result["ok"], f"status={status} should not block")


# ────────────────────────────────────────────────────────────
# record_stage_completion_override() — new fields + backward compat
# ────────────────────────────────────────────────────────────

class TestRecordOverrideOutputFields(unittest.TestCase):
    def test_writes_all_four_output_fields(self):
        import business_core.roadmap_manager as rm
        from business_core.sheets import BUSINESS_HEADERS

        headers = BUSINESS_HEADERS["stage_completion_overrides"]
        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("business_core.sheets.generate_next_id", return_value="SCO-100"), \
             patch("business_core.sheets.append_business_row") as mock_append:
            mock_sheet.return_value.row_values.return_value = headers
            result = rm.record_stage_completion_override(
                stage_id="STAGE-014", roadmap_id="RM-003", user="dida", reason="test",
                override_type="missing_blocking_outputs",
                missing_blocking_output_instance_ids=("",),
                missing_blocking_output_template_ids=("SOUT-002",),
                missing_blocking_output_titles=("Тест",),
                missing_blocking_output_statuses=("instance_missing",),
            )
        self.assertTrue(result["ok"])
        row = mock_append.call_args[0][1]
        row_dict = dict(zip(headers, row))
        self.assertEqual(row_dict["Missing Blocking Output Instance IDs"], "")
        self.assertEqual(row_dict["Missing Blocking Output Template IDs"], "SOUT-002")
        self.assertEqual(row_dict["Missing Blocking Output Titles"], "Тест")
        self.assertEqual(row_dict["Missing Blocking Output Statuses"], "instance_missing")

    def test_omitting_new_fields_writes_empty_strings(self):
        """п.27 support: a caller that never passes the new kwargs (as
        every pre-Phase-B call site did) writes "" for all four —
        exactly what makes old rows read back unchanged."""
        import business_core.roadmap_manager as rm
        from business_core.sheets import BUSINESS_HEADERS

        headers = BUSINESS_HEADERS["stage_completion_overrides"]
        with patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("business_core.sheets.generate_next_id", return_value="SCO-101"), \
             patch("business_core.sheets.append_business_row") as mock_append:
            mock_sheet.return_value.row_values.return_value = headers
            rm.record_stage_completion_override(
                stage_id="STAGE-001", roadmap_id="RM-001", user="dida", reason="test",
                missing_blocking_doc_ids=("DOC-001",), override_type="missing_blocking_documents",
            )
        row = mock_append.call_args[0][1]
        row_dict = dict(zip(headers, row))
        self.assertEqual(row_dict["Missing Blocking Output Instance IDs"], "")
        self.assertEqual(row_dict["Missing Blocking Output Template IDs"], "")
        self.assertEqual(row_dict["Missing Blocking Output Titles"], "")
        self.assertEqual(row_dict["Missing Blocking Output Statuses"], "")

    def test_old_row_reads_back_with_empty_new_fields(self):
        """п.27: a pre-Phase-B row (14 columns of real data, no Output
        columns at all) must read back with "" for the 4 new columns —
        simulated via a raw row shorter than the current header list."""
        from business_core.sheets import BUSINESS_HEADERS, get_header_index_map

        headers = BUSINESS_HEADERS["stage_completion_overrides"]
        old_row_values = [
            "SCO-001", "STAGE-012", "RM-003", "dida", "2026-01-01 00:00:00",
            "старый override", "", "in_progress", "done",
            "missing_blocking_documents", "", "", "", "",
        ]
        idx = get_header_index_map(headers)
        row_dict = {h: (old_row_values[i] if i < len(old_row_values) else "") for h, i in idx.items()}
        self.assertEqual(row_dict["Missing Blocking Output Instance IDs"], "")
        self.assertEqual(row_dict["Missing Blocking Output Template IDs"], "")
        self.assertEqual(row_dict["Missing Blocking Output Titles"], "")
        self.assertEqual(row_dict["Missing Blocking Output Statuses"], "")
        self.assertEqual(row_dict["Override Type"], "missing_blocking_documents")


# ────────────────────────────────────────────────────────────
# Telegram message rendering
# ────────────────────────────────────────────────────────────

class TestOutputGateTelegramMessages(unittest.TestCase):
    def test_output_only_blocking_message(self):
        from business_core.telegram_handlers import _stage_transition_failure_message
        result = {
            "code": "STAGE_OUTPUT_GATE_BLOCKED", "roadmap_id": "RM-003",
            "missing_blocking_output_instance_ids": ("SOUTI-002", ""),
            "missing_blocking_output_template_ids": ("SOUT-002", "SOUT-003"),
            "missing_blocking_output_titles": ("Название", "Другое название"),
            "missing_blocking_output_statuses": ("submitted", "instance_missing"),
        }
        msg = _stage_transition_failure_message(result, "STAGE-013", "done")
        self.assertIn("── Required Outputs ──", msg)
        self.assertIn("SOUTI-002 / SOUT-002 — Название — submitted", msg)
        self.assertIn("[instance отсутствует] / SOUT-003 — Другое название — instance_missing", msg)
        self.assertNotIn("Checklist", msg)
        self.assertNotIn("Document Template", msg)

    def test_combined_message_has_separate_output_section(self):
        from business_core.telegram_handlers import _stage_transition_failure_message
        result = {
            "code": "STAGE_COMPLETION_GATE_BLOCKED", "roadmap_id": "RM-003",
            "missing_blocking_doc_ids": ("DOC-008",),
            "missing_checklist_instance_ids": ("CLIN-001",),
            "missing_checklist_item_ids": ("CLII-001",),
            "missing_checklist_item_titles": ("Проверить",),
            "missing_blocking_output_instance_ids": ("SOUTI-002",),
            "missing_blocking_output_template_ids": ("SOUT-002",),
            "missing_blocking_output_titles": ("Договор",),
            "missing_blocking_output_statuses": ("rejected",),
        }
        msg = _stage_transition_failure_message(result, "STAGE-013", "done")
        self.assertIn("DOC-008", msg)
        self.assertIn("Проверить", msg)
        self.assertIn("── Required Outputs ──", msg)
        self.assertIn("SOUTI-002 / SOUT-002 — Договор — rejected", msg)

    def test_override_applied_success_line_shows_output_titles(self):
        from business_core.telegram_handlers import _stage_transition_success_lines
        result = {
            "code": "STAGE_STATUS_UPDATED", "changed": True, "previous_status": "in_progress",
            "final_status": "done", "roadmap_id": "RM-003", "downstream_failures": (),
            "partial_success": False, "retry_safe": True, "warnings": (),
            "override_applied": True, "override_id": "SCO-100", "override_type": "missing_blocking_outputs",
            "missing_blocking_output_titles": ("Подписанный договор",),
            "missing_checklist_item_titles": (),
        }
        lines = _stage_transition_success_lines(result, "STAGE-013", None)
        combined = "\n".join(lines)
        self.assertIn("Обойдённые Required Output: Подписанный договор", combined)


if __name__ == "__main__":
    unittest.main()
