"""
Tests for Phase 38C — Checklist Domain Foundation: the Checklist
orchestration section of business_core/business_builder.py (ADR-021).

Covers parse_checklist_template_items, _compute_checklist_progress,
_validate_checklist_relations, instantiate_checklist,
transition_checklist_item_status, transition_checklist_status, and
update_checklist_admin_fields. Low-level checklist_manager.py behavior
is covered separately in test_checklist_manager.py — here we only mock
its return values to exercise the orchestration/cross-domain policy
layer in isolation.

No live Sheets/Drive calls — mocks only. Registered in conftest.py's
hard socket-block set (Phase 38C, ADR-021).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.business_builder as bb  # noqa: E402


# ────────────────────────────────────────────────────────────
# Template parser
# ────────────────────────────────────────────────────────────

class TestParseChecklistTemplateItems(unittest.TestCase):
    def test_semicolon_split(self):
        result = bb.parse_checklist_template_items("A; B; C")
        self.assertTrue(result["ok"])
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["A", "B", "C"])

    def test_newline_split(self):
        result = bb.parse_checklist_template_items("A\nB\nC")
        self.assertTrue(result["ok"])
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["A", "B", "C"])

    def test_mixed_delimiters(self):
        result = bb.parse_checklist_template_items("A; B\nC")
        self.assertTrue(result["ok"])
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["A", "B", "C"])

    def test_whitespace_trimmed(self):
        result = bb.parse_checklist_template_items("  A  ;   B  ")
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["A", "B"])

    def test_empty_tokens_ignored(self):
        result = bb.parse_checklist_template_items("A;; ;B")
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["A", "B"])

    def test_duplicate_item_text_preserved_by_ordinal(self):
        result = bb.parse_checklist_template_items("A; A; A")
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual([i["source_item_key"] for i in result["items"]], [1, 2, 3])

    def test_order_preserved(self):
        result = bb.parse_checklist_template_items("C; A; B")
        self.assertEqual([i["item_order"] for i in result["items"]], [1, 2, 3])
        self.assertEqual([i["item_title_snapshot"] for i in result["items"]], ["C", "A", "B"])

    def test_exact_optional_match_sets_required_false(self):
        result = bb.parse_checklist_template_items("A; B; C", optional_text="B")
        by_title = {i["item_title_snapshot"]: i["required"] for i in result["items"]}
        self.assertFalse(by_title["B"])
        self.assertTrue(by_title["A"])
        self.assertTrue(by_title["C"])

    def test_exact_required_match_stays_required(self):
        result = bb.parse_checklist_template_items("A; B", required_text="A")
        by_title = {i["item_title_snapshot"]: i["required"] for i in result["items"]}
        self.assertTrue(by_title["A"])

    def test_default_required_true_when_unclassified(self):
        result = bb.parse_checklist_template_items("A; B")
        self.assertTrue(all(i["required"] for i in result["items"]))

    def test_required_optional_conflict_blocks(self):
        result = bb.parse_checklist_template_items("A; B", required_text="A", optional_text="A")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT")

    def test_unmatched_classification_text_not_guessed(self):
        """Required/Optional text that doesn't exactly match any parsed
        Item must simply have no effect — never fuzzy-matched."""
        result = bb.parse_checklist_template_items("A; B", optional_text="Something Else Entirely")
        self.assertTrue(result["ok"])
        self.assertTrue(all(i["required"] for i in result["items"]))

    def test_empty_items_blocks(self):
        result = bb.parse_checklist_template_items("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_ITEMS_EMPTY")

    def test_no_ai_or_fuzzy_import(self):
        path = WORKSPACE / "business_core" / "business_builder.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("def parse_checklist_template_items(")
        end = src.index("\ndef ", start + 10)
        body = src[start:end]
        for forbidden in ("anthropic", "openai", "difflib", "import re"):
            self.assertNotIn(forbidden, body)


class TestComputeChecklistProgress(unittest.TestCase):
    def test_all_pending(self):
        items = [{"required": True, "status": "pending"}, {"required": False, "status": "pending"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["total_items"], 2)
        self.assertEqual(progress["required_items"], 1)
        self.assertEqual(progress["completed_items"], 0)
        self.assertEqual(progress["required_remaining"], 1)

    def test_required_done(self):
        items = [{"required": True, "status": "done"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["completed_items"], 1)
        self.assertEqual(progress["required_remaining"], 0)

    def test_required_not_applicable_satisfies(self):
        items = [{"required": True, "status": "not_applicable"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["required_remaining"], 0)

    def test_required_skipped_does_not_satisfy(self):
        items = [{"required": True, "status": "skipped"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["required_remaining"], 1)
        self.assertEqual(progress["completed_items"], 0)

    def test_required_blocked_counted_in_blocked_required(self):
        items = [{"required": True, "status": "blocked"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["blocked_required"], 1)
        self.assertEqual(progress["required_remaining"], 1)

    def test_optional_pending_does_not_affect_required_remaining(self):
        items = [{"required": False, "status": "pending"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["required_remaining"], 0)

    def test_optional_blocked_does_not_count_as_blocked_required(self):
        items = [{"required": False, "status": "blocked"}]
        progress = bb._compute_checklist_progress(items)
        self.assertEqual(progress["blocked_required"], 0)


# ────────────────────────────────────────────────────────────
# Relation validation
# ────────────────────────────────────────────────────────────

def _biz_rows(biz_id="BIZ-001"):
    return [{"ID": biz_id}]


def _read_business_sheet_side_effect(rows_by_sheet):
    def _side_effect(sheet_name):
        return rows_by_sheet.get(sheet_name, [])
    return _side_effect


class TestValidateChecklistRelations(unittest.TestCase):
    def test_business_missing(self):
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect({})):
            result = bb._validate_checklist_relations("BIZ-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_minimal_valid(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_checklist_relations("BIZ-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["business_id"], "BIZ-001")

    def test_invalid_stage(self):
        rows = {"biz_registry": _biz_rows(), "roadmap_stages": []}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_checklist_relations("BIZ-001", stage_id="STAGE-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_invalid_roadmap(self):
        rows = {"biz_registry": _biz_rows(), "roadmaps": []}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_checklist_relations("BIZ-001", roadmap_id="RM-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_NOT_FOUND")

    def test_invalid_object(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.object_manager.find_object_by_id", return_value=None):
            result = bb._validate_checklist_relations("BIZ-001", object_id="OBJ-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OBJECT_NOT_FOUND")

    def test_invalid_service(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.service_manager.find_service_by_id", return_value=None):
            result = bb._validate_checklist_relations("BIZ-001", service_id="SVC-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SERVICE_NOT_FOUND")

    def test_stage_roadmap_contradiction_blocks(self):
        rows = {
            "biz_registry": _biz_rows(),
            "roadmap_stages": [{"Stage ID": "STAGE-001", "Roadmap ID": "RM-001"}],
        }
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)):
            result = bb._validate_checklist_relations("BIZ-001", stage_id="STAGE-001", roadmap_id="RM-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ENTITY_RELATION_MISMATCH")

    def test_stage_derives_roadmap_object_service(self):
        rows = {
            "biz_registry": _biz_rows(),
            "roadmap_stages": [{"Stage ID": "STAGE-001", "Roadmap ID": "RM-001"}],
            "roadmaps": [{"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Object ID": "OBJ-001", "Service ID": "SVC-001"}],
        }
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.object_manager.find_object_by_id", return_value={"biz_id": "BIZ-001"}), \
             patch("business_core.service_manager.find_service_by_id", return_value={"biz_id": "BIZ-001"}):
            result = bb._validate_checklist_relations("BIZ-001", stage_id="STAGE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["roadmap_id"], "RM-001")
        self.assertEqual(result["resolved"]["object_id"], "OBJ-001")
        self.assertEqual(result["resolved"]["service_id"], "SVC-001")

    def test_cross_business_object_blocks(self):
        rows = {"biz_registry": _biz_rows()}
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect(rows)), \
             patch("business_core.object_manager.find_object_by_id", return_value={"biz_id": "BIZ-999"}):
            result = bb._validate_checklist_relations("BIZ-001", object_id="OBJ-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ENTITY_RELATION_MISMATCH")


# ────────────────────────────────────────────────────────────
# instantiate_checklist
# ────────────────────────────────────────────────────────────

def _template(status="active", items="A; B", required="", optional=""):
    return {"Status": status, "Items": items, "Required Items": required, "Optional Items": optional, "Title": "Test Checklist"}


class TestInstantiateChecklist(unittest.TestCase):
    def _patch_relations_ok(self):
        return patch.object(
            bb, "_validate_checklist_relations",
            return_value={"ok": True, "code": "", "error": None, "resolved": {
                "business_id": "BIZ-001", "service_id": "", "object_id": "", "roadmap_id": "", "stage_id": "",
            }},
        )

    def test_missing_business_id(self):
        result = bb.instantiate_checklist("", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "BUSINESS_NOT_FOUND")

    def test_missing_template_id(self):
        result = bb.instantiate_checklist("BIZ-001", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_NOT_FOUND")

    def test_template_not_found(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=None):
            result = bb.instantiate_checklist("BIZ-001", "CHK-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_NOT_FOUND")

    def test_template_inactive_blocks(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template(status="inactive")):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_INACTIVE")

    def test_template_archived_blocks(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template(status="archived")):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_ARCHIVED")

    def test_template_unknown_status_blocks_safely(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template(status="weird")):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_TEMPLATE_STATUS")

    def test_empty_template_items_blocks(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template(items="")):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_TEMPLATE_ITEMS_EMPTY")

    def test_relation_validation_failure_propagates(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             patch.object(bb, "_validate_checklist_relations", return_value={"ok": False, "code": "STAGE_NOT_FOUND", "error": "x", "resolved": None}):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001", stage_id="STAGE-404")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_zero_matches_creates(self):
        saved_instance = {"Checklist Instance ID": "CLIN-001"}
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[]), \
             patch("business_core.checklist_manager.create_checklist_instance", return_value={"ok": True, "checklist_instance_id": "CLIN-001", "code": "CHECKLIST_INSTANCE_CREATED", "error": None}), \
             patch("business_core.checklist_manager.create_checklist_instance_items", return_value={"ok": True, "item_ids": ["CLII-001", "CLII-002"], "code": "", "error": None}), \
             patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=saved_instance), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[{}, {}]):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_CREATED")
        self.assertTrue(result["created"])
        self.assertEqual(result["checklist_instance_id"], "CLIN-001")
        self.assertEqual(result["total_items"], 2)
        self.assertEqual(result["created_item_ids"], ("CLII-001", "CLII-002"))

    def test_one_match_reuses_no_duplicate_items(self):
        existing = {
            "Checklist Instance ID": "CLIN-001", "Service ID": "", "Object ID": "",
            "Roadmap ID": "", "Stage ID": "", "Status": "draft",
            "Total Items": "2", "Required Items": "2", "Completed Items": "0", "Required Remaining": "2",
        }
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[existing]), \
             patch("business_core.checklist_manager.create_checklist_instance") as mock_create, \
             patch("business_core.checklist_manager.create_checklist_instance_items") as mock_create_items:
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        mock_create.assert_not_called()
        mock_create_items.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_REUSED")
        self.assertTrue(result["reused"])
        self.assertEqual(result["checklist_instance_id"], "CLIN-001")

    def test_multiple_matches_block_no_first_pick(self):
        m1 = {"Checklist Instance ID": "CLIN-001"}
        m2 = {"Checklist Instance ID": "CLIN-002"}
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[m1, m2]), \
             patch("business_core.checklist_manager.create_checklist_instance") as mock_create:
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        mock_create.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "MULTIPLE_CHECKLIST_INSTANCE_MATCHES")
        self.assertEqual(set(result["conflicting_ids"]), {"CLIN-001", "CLIN-002"})

    def test_parent_persistence_failure(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[]), \
             patch("business_core.checklist_manager.create_checklist_instance", return_value={"ok": False, "checklist_instance_id": "", "code": "", "error": "boom"}):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_PERSISTENCE_FAILED")
        self.assertTrue(result["retry_safe"])

    def test_partial_persistence_on_item_failure(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[]), \
             patch("business_core.checklist_manager.create_checklist_instance", return_value={"ok": True, "checklist_instance_id": "CLIN-001", "code": "CHECKLIST_INSTANCE_CREATED", "error": None}), \
             patch("business_core.checklist_manager.create_checklist_instance_items", return_value={"ok": False, "item_ids": [], "code": "", "error": "boom"}):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE")
        self.assertEqual(result["checklist_instance_id"], "CLIN-001")
        self.assertFalse(result["retry_safe"])

    def test_post_write_verification_failure(self):
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             self._patch_relations_ok(), \
             patch("business_core.checklist_manager.find_instances_by_idempotency_key", return_value=[]), \
             patch("business_core.checklist_manager.create_checklist_instance", return_value={"ok": True, "checklist_instance_id": "CLIN-001", "code": "CHECKLIST_INSTANCE_CREATED", "error": None}), \
             patch("business_core.checklist_manager.create_checklist_instance_items", return_value={"ok": True, "item_ids": ["CLII-001", "CLII-002"], "code": "", "error": None}), \
             patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=None):
            result = bb.instantiate_checklist("BIZ-001", "CHK-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED")
        self.assertFalse(result["retry_safe"])

    def test_no_ids_generated_before_relation_validation(self):
        """IDs must not be generated before validation/idempotency —
        verify create_checklist_instance is never called when relation
        validation fails."""
        with patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_template()), \
             patch.object(bb, "_validate_checklist_relations", return_value={"ok": False, "code": "STAGE_NOT_FOUND", "error": "x", "resolved": None}), \
             patch("business_core.checklist_manager.create_checklist_instance") as mock_create:
            bb.instantiate_checklist("BIZ-001", "CHK-001", stage_id="STAGE-404")
        mock_create.assert_not_called()


# ────────────────────────────────────────────────────────────
# transition_checklist_item_status
# ────────────────────────────────────────────────────────────

class TestTransitionChecklistItemStatus(unittest.TestCase):
    def _item(self, status):
        return {"Checklist Instance Item ID": "CLII-001", "Checklist Instance ID": "CLIN-001", "Status": status}

    def test_not_found(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=None):
            result = bb.transition_checklist_item_status("CLII-404", "done", completed_by="dida")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_ITEM_NOT_FOUND")

    def test_invalid_status(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")):
            result = bb.transition_checklist_item_status("CLII-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_ITEM_STATUS")

    def test_terminal_reopen_protected(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("done")):
            result = bb.transition_checklist_item_status("CLII-001", "pending")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION")

    def test_blocked_requires_reason(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")):
            result = bb.transition_checklist_item_status("CLII-001", "blocked")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_REASON_REQUIRED")

    def test_skipped_requires_reason(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")):
            result = bb.transition_checklist_item_status("CLII-001", "skipped")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_REASON_REQUIRED")

    def test_not_applicable_requires_reason(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")):
            result = bb.transition_checklist_item_status("CLII-001", "not_applicable")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_REASON_REQUIRED")

    def test_done_requires_completed_by(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")):
            result = bb.transition_checklist_item_status("CLII-001", "done")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED")

    def test_valid_done_transition_recomputes_progress_never_completes_parent(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")), \
             patch("business_core.checklist_manager.update_checklist_instance_item_status", return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[{"Required": "true", "Status": "done"}]), \
             patch("business_core.checklist_manager.update_checklist_instance_progress") as mock_progress, \
             patch("business_core.checklist_manager.update_checklist_instance_status") as mock_instance_status:
            result = bb.transition_checklist_item_status("CLII-001", "done", completed_by="dida")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_STATUS_UPDATED")
        mock_progress.assert_called_once()
        mock_instance_status.assert_not_called()

    def test_unchanged_status_noop(self):
        with patch("business_core.checklist_manager.find_checklist_instance_item_by_id", return_value=self._item("pending")), \
             patch("business_core.checklist_manager.update_checklist_instance_item_status", return_value={"ok": True, "changed": False, "code": "", "error": None}), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[]), \
             patch("business_core.checklist_manager.update_checklist_instance_progress"):
            result = bb.transition_checklist_item_status("CLII-001", "pending")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ITEM_STATUS_UNCHANGED")


# ────────────────────────────────────────────────────────────
# transition_checklist_status
# ────────────────────────────────────────────────────────────

class TestTransitionChecklistStatus(unittest.TestCase):
    def _instance(self, status):
        return {"Checklist Instance ID": "CLIN-001", "Business ID": "BIZ-001", "Status": status}

    def test_not_found(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=None):
            result = bb.transition_checklist_status("CLIN-404", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_NOT_FOUND")

    def test_invalid_status(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")):
            result = bb.transition_checklist_status("CLIN-001", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_STATUS")

    def test_terminal_restore_protected_from_completed(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("completed")):
            result = bb.transition_checklist_status("CLIN-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_terminal_restore_protected_from_archived(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("archived")):
            result = bb.transition_checklist_status("CLIN-001", "draft")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION")

    def test_completed_to_archived_allowed(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("completed")), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": True, "code": "", "error": None}):
            result = bb.transition_checklist_status("CLIN-001", "archived")
        self.assertTrue(result["ok"])

    def test_invalid_ordinary_transition(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")):
            result = bb.transition_checklist_status("CLIN-001", "completed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_CHECKLIST_STATUS_TRANSITION")

    def test_completion_gate_blocks_when_required_remaining(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("in_progress")), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[{"Required": "true", "Status": "pending"}]):
            result = bb.transition_checklist_status("CLIN-001", "completed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET")

    def test_completion_gate_blocks_when_no_items(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("in_progress")), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[]):
            result = bb.transition_checklist_status("CLIN-001", "completed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET")

    def test_completion_gate_passes_when_all_required_satisfied(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("in_progress")), \
             patch("business_core.checklist_manager.list_checklist_instance_items", return_value=[{"Required": "true", "Status": "done"}]), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_update:
            result = bb.transition_checklist_status("CLIN-001", "completed")
        self.assertTrue(result["ok"])
        self.assertTrue(result["completed"])
        call_kwargs = mock_update.call_args[1]
        self.assertTrue(call_kwargs["completed_at"])

    def test_started_at_set_on_first_in_progress(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_update:
            bb.transition_checklist_status("CLIN-001", "in_progress")
        call_kwargs = mock_update.call_args[1]
        self.assertTrue(call_kwargs["started_at"])

    def test_cancelled_at_set_on_cancel(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": True, "code": "", "error": None}) as mock_update:
            bb.transition_checklist_status("CLIN-001", "cancelled")
        call_kwargs = mock_update.call_args[1]
        self.assertTrue(call_kwargs["cancelled_at"])

    def test_unchanged_status_noop(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": False, "code": "", "error": None}):
            result = bb.transition_checklist_status("CLIN-001", "draft")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_STATUS_UNCHANGED")

    def test_no_item_mutation_side_effect(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=self._instance("draft")), \
             patch("business_core.checklist_manager.update_checklist_instance_status", return_value={"ok": True, "changed": True, "code": "", "error": None}), \
             patch("business_core.checklist_manager.update_checklist_instance_item_status") as mock_item_update:
            bb.transition_checklist_status("CLIN-001", "in_progress")
        mock_item_update.assert_not_called()


# ────────────────────────────────────────────────────────────
# update_checklist_admin_fields
# ────────────────────────────────────────────────────────────

class TestUpdateChecklistAdminFields(unittest.TestCase):
    def test_not_found(self):
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=None):
            result = bb.update_checklist_admin_fields("CLIN-404", {"Notes": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_INSTANCE_NOT_FOUND")

    def test_delegates_to_low_level(self):
        instance = {"Checklist Instance ID": "CLIN-001", "Business ID": "BIZ-001"}
        with patch("business_core.checklist_manager.find_checklist_instance_by_id", return_value=instance), \
             patch("business_core.checklist_manager.update_checklist_instance_admin_fields", return_value={"ok": True, "code": "CHECKLIST_ADMIN_FIELDS_UPDATED", "error": None, "changed": True}):
            result = bb.update_checklist_admin_fields("CLIN-001", {"Notes": "x"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_ADMIN_FIELDS_UPDATED")
        self.assertEqual(result["business_id"], "BIZ-001")


if __name__ == "__main__":
    unittest.main()
