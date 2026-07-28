"""
Phase 1 — Checklist Relation Foundation: STAGE_ENTITY_RELATIONS
Entity Type="checklist", business_core.stage_entity_relations.
create_checklist_relation_for_template_stage(), business_core.
business_builder.resolve_checklist_templates_for_template_stage()/
provision_checklists_for_stage().

Does NOT touch: _evaluate_checklist_completion_gate(),
transition_stage_status(), STAGE_COMPLETION_OVERRIDES, checklist
instance/item schemas, /startchecklist, /updatecheckitem,
/updatechecklist.

No live Sheets writes — mocks only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


def _fresh_ser():
    for k in list(sys.modules):
        if k.startswith("business_core"):
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.stage_entity_relations")


def _fresh_bb():
    for k in list(sys.modules):
        if k.startswith("business_core"):
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.business_builder")


# ────────────────────────────────────────────────────────────
# п.25: ENTITY_TYPE_DISPATCH — fifth entry
# ────────────────────────────────────────────────────────────

class TestChecklistEntityType(unittest.TestCase):
    def test_dispatch_entry_present(self):
        ser = _fresh_ser()
        self.assertIn("checklist", ser.ENTITY_TYPE_DISPATCH)
        self.assertEqual(ser.ENTITY_TYPE_DISPATCH["checklist"]["sheet_key"], "checklist_registry")
        self.assertEqual(ser.ENTITY_TYPE_DISPATCH["checklist"]["id_column"], "Checklist ID")

    def test_dispatch_now_has_five_entries(self):
        ser = _fresh_ser()
        self.assertEqual(
            set(ser.ENTITY_TYPE_DISPATCH.keys()),
            {"document_template", "role", "sop", "required_output", "checklist"},
        )


# ────────────────────────────────────────────────────────────
# п.26-30: create_checklist_relation_for_template_stage()
# ────────────────────────────────────────────────────────────

class TestCreateChecklistRelation(unittest.TestCase):
    def test_creates_relation(self):
        ser = _fresh_ser()
        with patch("business_core.sheets.find_row_by_id", side_effect=[(1, {}), None]), \
             patch.object(ser, "validate_relation_references", return_value=[]), \
             patch.object(ser, "find_active_duplicate_relation", return_value=None), \
             patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("business_core.sheets.generate_next_ids", return_value=["REL-100"]), \
             patch("business_core.sheets.row_from_header_map", side_effect=lambda h, v: v), \
             patch("business_core.sheets.batch_append_business_rows") as mock_append:
            mock_sheet.return_value.row_values.return_value = ["Relation ID", "Template Stage ID", "Stage ID", "Entity Type", "Entity ID", "Required", "Blocking", "Minimum Count", "Status", "Created At", "Updated At"]
            result = ser.create_checklist_relation_for_template_stage("TSTG-001", "CHK-001")
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.created[0]["Entity Type"], "checklist")
        self.assertEqual(result.created[0]["Entity ID"], "CHK-001")
        self.assertEqual(result.created[0]["Required"], "true")
        self.assertEqual(result.created[0]["Blocking"], "true")
        mock_append.assert_called_once()

    def test_bool_false_converted_to_string(self):
        ser = _fresh_ser()
        with patch("business_core.sheets.find_row_by_id", side_effect=[(1, {}), None]), \
             patch.object(ser, "validate_relation_references", return_value=[]), \
             patch.object(ser, "find_active_duplicate_relation", return_value=None), \
             patch("business_core.sheets.get_business_sheet") as mock_sheet, \
             patch("business_core.sheets.generate_next_ids", return_value=["REL-101"]), \
             patch("business_core.sheets.row_from_header_map", side_effect=lambda h, v: v), \
             patch("business_core.sheets.batch_append_business_rows"):
            mock_sheet.return_value.row_values.return_value = ["Relation ID"]
            result = ser.create_checklist_relation_for_template_stage(
                "TSTG-001", "CHK-002", required=False, blocking=False,
            )
        self.assertEqual(result.created[0]["Required"], "false")
        self.assertEqual(result.created[0]["Blocking"], "false")

    def test_duplicate_relation_idempotent(self):
        """п.27: повторный вызов не создаёт дубль."""
        ser = _fresh_ser()
        existing = {"Relation ID": "REL-050", "Entity ID": "CHK-001"}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, {})), \
             patch.object(ser, "validate_relation_references", return_value=[]), \
             patch.object(ser, "find_active_duplicate_relation", return_value=existing), \
             patch("business_core.sheets.batch_append_business_rows") as mock_append:
            result = ser.create_checklist_relation_for_template_stage("TSTG-001", "CHK-001")
        self.assertTrue(result.ok)
        self.assertEqual(result.created, ())
        self.assertEqual(result.skipped_duplicates, (("CHK-001", "REL-050"),))
        mock_append.assert_not_called()

    def test_invalid_template_stage_rejected(self):
        """п.28."""
        ser = _fresh_ser()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = ser.create_checklist_relation_for_template_stage("TSTG-999", "CHK-001")
        self.assertFalse(result.ok)

    def test_invalid_checklist_template_rejected(self):
        """п.29: validate_relation_references catches a dangling Entity ID."""
        ser = _fresh_ser()
        with patch("business_core.sheets.find_row_by_id", return_value=(1, {})), \
             patch.object(ser, "validate_relation_references",
                          return_value=["Entity ID 'CHK-999' not found in checklist_registry."]):
            result = ser.create_checklist_relation_for_template_stage("TSTG-001", "CHK-999")
        self.assertFalse(result.ok)
        self.assertIn("CHK-999", str(result.errors))

    def test_precondition_requires_both_args(self):
        ser = _fresh_ser()
        result = ser.create_checklist_relation_for_template_stage("", "")
        self.assertFalse(result.ok)


# ────────────────────────────────────────────────────────────
# п.31-33: resolve_checklist_templates_for_template_stage()
# ────────────────────────────────────────────────────────────

_ACTIVE_TEMPLATE = {"Checklist ID": "CHK-001", "Title": "Документы клиента", "Status": "active"}
_INACTIVE_TEMPLATE = {"Checklist ID": "CHK-002", "Title": "Старый чек-лист", "Status": "inactive"}

_RELATION_CHK_001 = {
    "Relation ID": "REL-100", "Template Stage ID": "TSTG-001", "Stage ID": "",
    "Entity Type": "checklist", "Entity ID": "CHK-001",
    "Required": "true", "Blocking": "true", "Status": "active",
}


class TestResolveChecklistTemplates(unittest.TestCase):
    def test_prefers_relations_over_legacy(self):
        """п.31."""
        bb = _fresh_bb()
        row = {"Checklist IDs": "CHK-999-LEGACY-ONLY"}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, row)), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_ACTIVE_TEMPLATE):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "relations")
        self.assertEqual(result["checklist_template_ids"], ("CHK-001",))
        self.assertNotIn("CHK-999-LEGACY-ONLY", result["checklist_template_ids"])

    def test_falls_back_to_legacy_when_no_relations(self):
        """п.32."""
        bb = _fresh_bb()
        row = {"Checklist IDs": "CHK-001, CHK-002"}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, row)), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.knowledge_manager.find_checklist_by_id",
                   side_effect=lambda cid: {"CHK-001": _ACTIVE_TEMPLATE, "CHK-002": _INACTIVE_TEMPLATE}.get(cid)):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "legacy")
        self.assertEqual(result["checklist_template_ids"], ("CHK-001",))
        self.assertEqual(result["skipped_inactive_templates"], ("CHK-002",))

    def test_legacy_ids_deduplicated_order_preserved(self):
        """п.33."""
        bb = _fresh_bb()
        row = {"Checklist IDs": "CHK-001, CHK-002, CHK-001, CHK-002"}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, row)), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.knowledge_manager.find_checklist_by_id",
                   side_effect=lambda cid: {"CHK-001": _ACTIVE_TEMPLATE, "CHK-002": {**_ACTIVE_TEMPLATE, "Checklist ID": "CHK-002"}}.get(cid)):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertEqual(result["checklist_template_ids"], ("CHK-001", "CHK-002"))

    def test_legacy_invalid_id_reported(self):
        bb = _fresh_bb()
        row = {"Checklist IDs": "CHK-999-GHOST"}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, row)), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.knowledge_manager.find_checklist_by_id", return_value=None):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertEqual(result["invalid_legacy_checklist_ids"], ("CHK-999-GHOST",))
        self.assertEqual(result["checklist_template_ids"], ())

    def test_relations_inactive_template_skipped(self):
        bb = _fresh_bb()
        with patch("business_core.sheets.find_row_by_id", return_value=(1, {})), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.knowledge_manager.find_checklist_by_id", return_value=_INACTIVE_TEMPLATE):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertEqual(result["checklist_template_ids"], ())
        self.assertEqual(result["skipped_inactive_templates"], ("CHK-001",))

    def test_template_stage_not_found(self):
        bb = _fresh_bb()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-999")
        self.assertFalse(result["ok"])

    def test_no_source_at_all(self):
        bb = _fresh_bb()
        row = {"Checklist IDs": ""}
        with patch("business_core.sheets.find_row_by_id", return_value=(1, row)), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.resolve_checklist_templates_for_template_stage("TSTG-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "")
        self.assertEqual(result["checklist_template_ids"], ())


# ────────────────────────────────────────────────────────────
# п.34-40: provision_checklists_for_stage()
# ────────────────────────────────────────────────────────────

_RESOLVED_OK = {
    "ok": True, "code": "", "error": None,
    "template_stage_id": "TSTG-001",
    "roadmap": {"roadmap_id": "RM-003", "business_id": "BIZ-001", "service_id": "SVC-001", "object_id": "OBJ-001"},
}

_RESOLUTION_OK = {
    "ok": True, "error": None, "template_stage_id": "TSTG-001", "source": "relations",
    "checklist_template_ids": ("CHK-001",), "skipped_inactive_templates": (), "invalid_legacy_checklist_ids": (),
    # Additive field (Sheets quota mitigation, 2026-07-28): provision_checklists_for_stage()
    # now reuses this instead of a second get_relations_for_template_stage() call.
    "relations": (_RELATION_CHK_001,),
}


class TestProvisionChecklistsForStage(unittest.TestCase):
    def test_resolution_failure_propagates(self):
        bb = _fresh_bb()
        failed = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "не найден"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed):
            result = bb.provision_checklists_for_stage("STAGE-999", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_no_checklist_templates(self):
        bb = _fresh_bb()
        empty_resolution = {**_RESOLUTION_OK, "checklist_template_ids": (), "source": ""}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=empty_resolution):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_CHECKLIST_TEMPLATES")

    def test_preview_does_not_write(self):
        """п.34."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=_RESOLUTION_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=()), \
             patch.object(bb, "instantiate_checklist") as mock_instantiate:
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        mock_instantiate.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_PROVISION_PREVIEW")
        self.assertEqual(result["to_create"], ("CHK-001",))

    def test_confirm_creates_instance(self):
        """п.35, п.37: IDs передаются корректно."""
        bb = _fresh_bb()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=_RESOLUTION_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=()), \
             patch.object(bb, "instantiate_checklist",
                          return_value={"ok": True, "checklist_instance_id": "CLIN-050"}) as mock_instantiate:
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=True)
        mock_instantiate.assert_called_once_with(
            "BIZ-001", "CHK-001", service_id="SVC-001", object_id="OBJ-001",
            roadmap_id="RM-003", stage_id="STAGE-013", read_context=ANY,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_PROVISIONED")
        self.assertEqual(result["created"], ("CHK-001",))

    def test_repeat_sync_no_duplicate(self):
        """п.36."""
        bb = _fresh_bb()
        existing = [{"Checklist Template ID": "CHK-001", "Stage ID": "STAGE-013", "Status": "draft"}]
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=_RESOLUTION_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=existing), \
             patch.object(bb, "instantiate_checklist") as mock_instantiate:
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=True)
        mock_instantiate.assert_not_called()
        self.assertEqual(result["to_create"], ())
        self.assertEqual(result["already_existing"], ("CHK-001",))

    def test_existing_instance_shown_as_already_existing(self):
        """п.38."""
        bb = _fresh_bb()
        existing = [{"Checklist Template ID": "CHK-001", "Stage ID": "STAGE-013", "Status": "in_progress"}]
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=_RESOLUTION_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_CHK_001,)), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=existing):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        self.assertEqual(result["already_existing"], ("CHK-001",))

    def test_inactive_template_shown_as_skipped(self):
        """п.39."""
        bb = _fresh_bb()
        resolution = {**_RESOLUTION_OK, "checklist_template_ids": (), "skipped_inactive_templates": ("CHK-002",)}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=resolution):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_CHECKLIST_TEMPLATES")
        self.assertEqual(result["skipped_inactive"], ("CHK-002",))

    def test_partial_failure_creates_remaining_valid_instances(self):
        """п.40."""
        bb = _fresh_bb()
        relations = (
            _RELATION_CHK_001,
            {**_RELATION_CHK_001, "Relation ID": "REL-101", "Entity ID": "CHK-002"},
        )
        resolution = {**_RESOLUTION_OK, "checklist_template_ids": ("CHK-001", "CHK-002"), "relations": relations}

        def _instantiate_side_effect(business_id, checklist_template_id, **kwargs):
            if checklist_template_id == "CHK-001":
                return {"ok": False, "error": "boom"}
            return {"ok": True, "checklist_instance_id": "CLIN-051"}

        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=resolution), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=relations), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=()), \
             patch.object(bb, "instantiate_checklist", side_effect=_instantiate_side_effect):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "CHECKLIST_PROVISION_PARTIAL")
        self.assertEqual(result["created"], ("CHK-002",))
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["partial_success"])

    def test_blocking_false_relation_excluded_from_provisioning(self):
        """A Blocking=false relation is filtered out of the automatic-
        provisioning scope entirely — the preview correctly reports
        nothing to create and nothing already existing for it (not a
        hard NO_CHECKLIST_TEMPLATES error, since the Template Stage IS
        configured, just not with anything in blocking scope)."""
        bb = _fresh_bb()
        non_blocking_relation = {**_RELATION_CHK_001, "Blocking": "false"}
        resolution = {**_RESOLUTION_OK, "relations": (non_blocking_relation,)}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=resolution), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=()):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["to_create"], ())
        self.assertEqual(result["already_existing"], ())

    def test_legacy_source_always_treated_as_blocking(self):
        bb = _fresh_bb()
        legacy_resolution = {**_RESOLUTION_OK, "source": "legacy"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch.object(bb, "resolve_checklist_templates_for_template_stage", return_value=legacy_resolution), \
             patch("business_core.checklist_manager.list_checklist_instances", return_value=()):
            result = bb.provision_checklists_for_stage("STAGE-013", confirm=False)
        self.assertEqual(result["to_create"], ("CHK-001",))


# ────────────────────────────────────────────────────────────
# п.47-48: Completion Gate / transition_stage_status() isolation guards
# ────────────────────────────────────────────────────────────

class TestChecklistRelationFoundationIsolation(unittest.TestCase):
    def test_checklist_gate_source_unchanged(self):
        """п.47: Checklist Gate must still only exclude cancelled/archived
        — no Blocking-awareness introduced."""
        import inspect
        import business_core.business_builder as bb

        source = inspect.getsource(bb._evaluate_checklist_completion_gate)
        self.assertIn('inst.get("Status", "") not in ("cancelled", "archived")', source)
        self.assertNotIn("Blocking", source)

    def test_transition_stage_status_never_calls_checklist_provisioning(self):
        """п.48/19: architecture guard — Checklist Relation Foundation is
        never invoked automatically from transition_stage_status()."""
        import inspect
        import business_core.business_builder as bb

        source = inspect.getsource(bb.transition_stage_status)
        self.assertNotIn("provision_checklists_for_stage", source)
        self.assertNotIn("resolve_checklist_templates_for_template_stage", source)

    def test_startchecklist_updatecheckitem_updatechecklist_untouched(self):
        import inspect
        import business_core.telegram_handlers as th

        for fn in (th.startchecklist_cmd, th.updatecheckitem_cmd, th.updatechecklist_cmd):
            source = inspect.getsource(fn)
            self.assertNotIn("provision_checklists_for_stage", source)
            self.assertNotIn("create_checklist_relation_for_template_stage", source)

    def test_stage_completion_overrides_schema_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(len(BUSINESS_HEADERS["stage_completion_overrides"]), 18)


if __name__ == "__main__":
    unittest.main()
