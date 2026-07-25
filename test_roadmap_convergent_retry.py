"""
Phase 28G: convergent-retry behavioral tests for
business_core.business_builder.create_roadmap_for_object().

Strictly against a mocked business_core.roadmap_manager /
business_core.roadmap_template_manager / business_core.stage_entity_relations
layer — no live network calls, no production data touched.

Phase 33C (ADR-016) update: create_roadmap_for_object() no longer calls
business_core.roadmap_manager.find_active_roadmap_for_object() for duplicate
detection — it calls the new find_open_roadmaps_for_object(object_id,
service_id) instead, which returns a list of Roadmaps whose status is one of
{"active", "on_hold"} ("open"). Zero -> create; exactly one -> reuse; more
than one -> blocking MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR (never an
arbitrary first pick — this is a deliberate ADR-016 tightening of the old
"silently use first + warning" behavior). All tests below mock
find_open_roadmaps_for_object directly rather than
find_active_roadmap_for_object + list_roadmaps.
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


def _template_rows(n=2):
    return [
        {"stage_id": f"TSTG-{i:03d}", "order": str(i), "stage_name": f"Этап {i}",
         "required_docs": "", "responsible": "", "notes": "",
         "sop_ids": [], "checklist_ids": [], "material_ids": [],
         "document_template_ids": [], "faq_ids": []}
        for i in range(1, n + 1)
    ]


def _stage_result(created_ids, created_orders, existing_ids=(), existing_count=None):
    existing_count = len(existing_ids) if existing_count is None else existing_count
    return {
        "ok": True, "roadmap_id": "RM-100",
        "created_stage_ids": list(created_ids), "created_from_orders": list(created_orders),
        "existing_stage_ids": list(existing_ids),
        "created_count": len(created_ids), "existing_count": existing_count,
        "total_count": len(created_ids) + existing_count,
        "error": None,
    }


class _OkCopy:
    ok = True
    created = ()


class TestFirstRunCreatesRoadmapAndStages(unittest.TestCase):
    def test_first_call_creates_roadmap_and_all_stages(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[]), \
             patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-100", "roadmap": {}, "error": None}) as mock_create, \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(2)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result(["STAGE-001", "STAGE-002"], [1, 2])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_OkCopy()):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-100", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-100", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["roadmap_created"])
        self.assertFalse(result["roadmap_reused"])
        self.assertEqual(result["stages_count"], 2)
        self.assertEqual(result["total_stage_count"], 2)
        mock_create.assert_called_once()


class TestSecondIdenticalRunDoesNotDuplicate(unittest.TestCase):
    def test_second_call_reuses_roadmap_no_new_roadmap_created(self):
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-100", "object_id": "OBJ-100", "service_id": "SVC-100",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(2)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result([], [], existing_ids=["STAGE-001", "STAGE-002"])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-100", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-100", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["roadmap_created"])
        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["roadmap_id"], "RM-100")
        mock_create.assert_not_called()

    def test_second_call_creates_no_duplicate_stages(self):
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-100", "object_id": "OBJ-100", "service_id": "SVC-100",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(2)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result([], [], existing_ids=["STAGE-001", "STAGE-002"])) as mock_ensure:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-100", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-100", template_id="RMT-001",
            )

        self.assertEqual(result["stages_count"], 0)
        self.assertEqual(result["existing_stage_count"], 2)
        mock_ensure.assert_called_once()  # idempotency lives inside ensure_roadmap_stages itself


class TestPartialCoreStateRecovery(unittest.TestCase):
    def test_existing_roadmap_without_stages_gets_stages_created(self):
        """4: existing Roadmap, zero Stages -> retry creates them all."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-101", "object_id": "OBJ-101", "service_id": "SVC-101",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(3)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result(["STAGE-001", "STAGE-002", "STAGE-003"], [1, 2, 3])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_OkCopy()):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-101", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-101", template_id="RMT-001",
            )

        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["stages_count"], 3)
        self.assertEqual(result["existing_stage_count"], 0)

    def test_existing_roadmap_with_partial_stages_fills_missing(self):
        """5: existing Roadmap, some Stages -> only missing ones created."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-102", "object_id": "OBJ-102", "service_id": "SVC-102",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(3)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result(["STAGE-003"], [3], existing_ids=["STAGE-001", "STAGE-002"])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_OkCopy()) as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-102", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-102", template_id="RMT-001",
            )

        self.assertEqual(result["stages_count"], 1)
        self.assertEqual(result["existing_stage_count"], 2)
        self.assertEqual(result["total_stage_count"], 3)
        mock_copy.assert_called_once()  # only for the one newly created stage

    def test_existing_stage_ids_are_preserved(self):
        """6: existing Stage IDs never change/reappear as 'created'."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-103", "object_id": "OBJ-103", "service_id": "SVC-103",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(2)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result([], [], existing_ids=["STAGE-777", "STAGE-778"])):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-103", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-103", template_id="RMT-001",
            )

        self.assertEqual(result["existing_stage_ids"], ["STAGE-777", "STAGE-778"])
        self.assertEqual(result["stage_ids"], [])


class TestExtensionIdempotencyAndPartialFailure(unittest.TestCase):
    def test_extension_failure_returns_visible_partial_result(self):
        """9: Extension failure -> partial_success/partial_failure visible, ok stays True."""
        bb = _fresh_bb()

        def failing_copy(template_stage_id, stage_id):
            raise RuntimeError("simulated relation-copy failure")

        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[]), \
             patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-104", "roadmap": {}, "error": None}), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(1)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result(["STAGE-001"], [1])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   side_effect=failing_copy):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-104", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-104", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["partial_success"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual(len(result["relation_copy_errors"]), 1)

    def test_retry_after_extension_failure_completes_missing_operations(self):
        """10: retry only re-attempts relation-copy for stages still
        missing it — simulated here by a retry where ensure_roadmap_stages
        reports the SAME stage as newly created again is not how this
        works; instead a retry naturally only sees it as 'existing' the
        second time, so no extra copy attempt happens for it — copy is
        only attempted for genuinely NEW stages each call."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-105", "object_id": "OBJ-105", "service_id": "SVC-105",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(1)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result([], [], existing_ids=["STAGE-001"])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-105", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-105", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["partial_failure"])
        mock_copy.assert_not_called()

    def test_already_existing_extension_records_not_duplicated(self):
        """11: copy_template_relations_to_stage is only invoked for
        NEWLY created stages, never for ones already existing —
        preventing duplicate relation-copy attempts on retry."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-106", "object_id": "OBJ-106", "service_id": "SVC-106",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=_template_rows(2)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value=_stage_result(["STAGE-002"], [2], existing_ids=["STAGE-001"])), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_OkCopy()) as mock_copy:
            bb.create_roadmap_for_object(
                obj_id="OBJ-106", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-106", template_id="RMT-001",
            )

        self.assertEqual(mock_copy.call_count, 1)
        self.assertEqual(mock_copy.call_args.args, ("TSTG-002", "STAGE-002"))


class TestTemplateMismatchPolicy(unittest.TestCase):
    def test_existing_template_id_is_not_overwritten_by_different_template(self):
        """12: existing Roadmap's own template_id wins over a differently
        requested one."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-107", "object_id": "OBJ-107", "service_id": "SVC-107",
            "status": "active", "template_id": "RMT-EXISTING-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]) as mock_find_ts:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-107", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-107", template_id="RMT-DIFFERENT-002",
            )

        self.assertEqual(result["template_id"], "RMT-EXISTING-001")
        mock_find_ts.assert_called_once_with("RMT-EXISTING-001")

    def test_template_mismatch_is_visible_in_warnings(self):
        """13: mismatch is reported, not silently dropped."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-108", "object_id": "OBJ-108", "service_id": "SVC-108",
            "status": "active", "template_id": "RMT-EXISTING-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-108", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-108", template_id="RMT-DIFFERENT-002",
            )

        self.assertIsNotNone(result["template_warning"])
        self.assertIn("RMT-DIFFERENT-002", result["template_warning"])
        self.assertIn("RMT-EXISTING-001", result["template_warning"])
        self.assertIn(result["template_warning"], result["warnings"])

    def test_template_mismatch_warning_has_no_unescaped_markdown_underscores(self):
        """Regression (found via Phase 28GH production smoke test):
        this message is displayed verbatim in Telegram with
        parse_mode="Markdown" — an unescaped underscore is silently
        consumed as an italic delimiter (e.g. "requested_template_id"
        rendered as "requestedtemplateid"). The message text must
        contain no raw underscores at all."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-115", "object_id": "OBJ-115", "service_id": "SVC-115",
            "status": "active", "template_id": "RMT-EXISTING-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-115", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-115", template_id="RMT-DIFFERENT-002",
            )

        self.assertNotIn("_", result["template_warning"])

    def test_no_mismatch_warning_when_templates_match(self):
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-109", "object_id": "OBJ-109", "service_id": "SVC-109",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-109", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-109", template_id="RMT-001",
            )

        self.assertIsNone(result["template_warning"])

    def test_existing_roadmap_without_template_uses_requested_one(self):
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-110", "object_id": "OBJ-110", "service_id": "SVC-110",
            "status": "active", "template_id": "",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]) as mock_find_ts:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-110", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-110", template_id="RMT-NEW-001",
            )

        self.assertEqual(result["template_id"], "RMT-NEW-001")
        self.assertIsNone(result["template_warning"])
        mock_find_ts.assert_called_once_with("RMT-NEW-001")


class TestOpenRoadmapUniquenessKey(unittest.TestCase):
    """14/15 (Phase 33C rewrite, ADR-016 §9): find_open_roadmaps_for_object
    is the sole duplicate-detection primitive, called with exactly
    (obj_id, service_id) — no Client ID/Business ID/Template ID involved
    in the key. It matches Roadmaps whose status is "active" OR
    "on_hold" ("open"); a Roadmap that is "completed"/"cancelled" is not
    open and therefore never blocks (nor is reused for) a new one."""

    def test_uniqueness_key_is_object_and_service(self):
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-999", "client_id": "PRS-999"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-999"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-999"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object",
                   return_value=[]) as mock_find_open, \
             patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-111", "roadmap": {}, "error": None}), \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            bb.create_roadmap_for_object(
                obj_id="OBJ-111", biz_id="BIZ-999", client_id="PRS-999",
                service_id="SVC-111", template_id="RMT-999",
            )

        mock_find_open.assert_called_once_with("OBJ-111", "SVC-111")

    def test_completed_or_cancelled_roadmap_does_not_block_new_active_roadmap(self):
        """15: a completed/cancelled Roadmap is not "open" — it is
        excluded by find_open_roadmaps_for_object itself, which is why
        this returns an empty list here, allowing a new active Roadmap
        to be created."""
        bb = _fresh_bb()
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object",
                   return_value=[]) as mock_find_open, \
             patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-112", "roadmap": {}, "error": None}) as mock_create, \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-112", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-112", template_id="",
            )

        mock_find_open.assert_called_once()
        mock_create.assert_called_once()
        self.assertTrue(result["roadmap_created"])

    def test_single_on_hold_roadmap_is_reused_like_active(self):
        """New Phase 33C coverage: "on_hold" is open (ADR-016 §9) —
        exactly one on_hold Roadmap is reused, same as one active
        Roadmap would be, never treated as absent."""
        bb = _fresh_bb()
        existing_roadmap = {
            "roadmap_id": "RM-116", "object_id": "OBJ-116", "service_id": "SVC-116",
            "status": "on_hold", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object",
                   return_value=[existing_roadmap]), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-116", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-116", template_id="RMT-001",
            )

        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["roadmap_id"], "RM-116")
        mock_create.assert_not_called()


class TestDuplicateOpenRoadmapIntegrityVisibility(unittest.TestCase):
    """16 (Phase 33C rewrite, ADR-016 §9): >1 open Roadmap for the same
    (Object ID, Service ID) is now a BLOCKING
    MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR — never an arbitrary first
    pick, and never a silent warning-only path. This replaces the old
    Phase 28G "use first + warning" behavior, which ADR-016 explicitly
    retires as unsafe."""

    def test_two_open_roadmaps_block_with_integrity_error_not_silent_pick(self):
        bb = _fresh_bb()
        first_match = {
            "roadmap_id": "RM-113", "object_id": "OBJ-113", "service_id": "SVC-113",
            "status": "active", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        second_match = {
            "roadmap_id": "RM-114", "object_id": "OBJ-113", "service_id": "SVC-113",
            "status": "on_hold", "template_id": "RMT-001",
            "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        with patch("business_core.object_manager.find_object_by_id",
                   return_value={"object_id": "OBJ-TEST", "status": "new", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-TEST", "status": "active", "biz_id": "BIZ-001"}), \
             patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"person_id": "PRS-DEFAULT", "status": "active",
                                 "person_type": "клиент", "biz_ids": [], "primary_biz_id": ""}), \
             patch("business_core.person_manager.is_person_archived", return_value=False), \
             patch("business_core.person_manager.is_client_person", return_value=True), \
             patch("business_core.person_manager.has_person_business_link", return_value=True), \
             patch("business_core.roadmap_manager.find_open_roadmaps_for_object",
                   return_value=[first_match, second_match]), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                   side_effect=lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-113", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-113", template_id="RMT-001",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR")
        self.assertEqual(result["roadmap_id"], "")
        self.assertEqual(set(result["conflicting_roadmap_ids"]), {"RM-113", "RM-114"})
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
