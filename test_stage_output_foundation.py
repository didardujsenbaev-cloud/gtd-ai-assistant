"""
Tests for Phase A — Stage Output Foundation: STAGE_OUTPUT_TEMPLATES /
STAGE_OUTPUT_INSTANCES schema, business_core/stage_output_manager.py
(Output Template/Instance persistence + lifecycle transitions),
stage_entity_relations.ENTITY_TYPE_DISPATCH["required_output"] +
create_required_output_relation_for_template_stage(), and
business_builder.sync_stage_output_requirements().

Required Output is explicitly NOT wired into any Stage Completion Gate
in this phase — see the architecture guards at the bottom of this file.

No live Sheets writes — mocks only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

OUTPUT_TEMPLATE_HEADERS = [
    "Output Template ID", "Biz ID", "Service ID", "Template ID", "Template Stage ID",
    "Title", "Description", "Output Type", "Verification Method",
    "Related Document Template ID", "Related Checklist ID",
    "Default Required", "Default Blocking", "Status", "Notes",
    "Created At", "Last Updated",
]

OUTPUT_INSTANCE_HEADERS = [
    "Output Instance ID", "Output Template ID", "Business ID", "Service ID", "Object ID",
    "Roadmap ID", "Stage ID",
    "Title Snapshot", "Description Snapshot", "Output Type Snapshot", "Verification Method Snapshot",
    "Related Document Template ID", "Related Checklist ID",
    "Required", "Blocking", "Status",
    "Evidence Type", "Evidence Value",
    "Submitted By", "Submitted At",
    "Accepted By", "Accepted At",
    "Rejected By", "Rejected At", "Rejection Reason",
    "Waived By", "Waived At", "Waiver Reason",
    "Created At", "Last Updated", "Notes",
]

OUTPUT_TEMPLATE_ROW = [
    "SOUT-001", "BIZ-001", "SVC-001", "RMT-001", "TSTG-029",
    "Подписанный договор с клиентом", "Договор подписан обеими сторонами",
    "document", "Проверить наличие подписанного обеими сторонами договора",
    "DOC-001", "",
    "true", "true", "active", "",
    "2026-01-01", "2026-01-01",
]


def _fresh_som():
    for k in list(sys.modules):
        if k.startswith("business_core"):
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.stage_output_manager")


def _make_sheet(headers, rows):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


# ────────────────────────────────────────────────────────────
# 39. Schema guards
# ────────────────────────────────────────────────────────────

class TestSchema(unittest.TestCase):
    def test_output_template_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["stage_output_templates"], OUTPUT_TEMPLATE_HEADERS)

    def test_output_instance_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["stage_output_instances"], OUTPUT_INSTANCE_HEADERS)

    def test_sheet_names_registered(self):
        from business_core.sheets import BUSINESS_SHEET_NAMES
        self.assertEqual(BUSINESS_SHEET_NAMES["stage_output_templates"], "STAGE_OUTPUT_TEMPLATES")
        self.assertEqual(BUSINESS_SHEET_NAMES["stage_output_instances"], "STAGE_OUTPUT_INSTANCES")

    def test_id_prefixes(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["stage_output_templates"], "SOUT")
        self.assertEqual(_ID_PREFIXES["stage_output_instances"], "SOUTI")

    def test_prefixes_unique_across_all_registries(self):
        from business_core.sheets import _ID_PREFIXES
        all_prefixes = list(_ID_PREFIXES.values())
        self.assertEqual(all_prefixes.count("SOUT"), 1)
        self.assertEqual(all_prefixes.count("SOUTI"), 1)


# 40. ID generation

class TestIdGeneration(unittest.TestCase):
    def test_generate_output_template_id_empty_sheet(self):
        som = _fresh_som()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OUTPUT_TEMPLATE_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(som.generate_output_template_id(), "SOUT-001")

    def test_generate_output_template_id_increments(self):
        som = _fresh_som()
        sheet = _make_sheet(OUTPUT_TEMPLATE_HEADERS, [OUTPUT_TEMPLATE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(som.generate_output_template_id(), "SOUT-002")

    def test_generate_output_instance_id_empty_sheet(self):
        som = _fresh_som()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OUTPUT_INSTANCE_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(som.generate_output_instance_id(), "SOUTI-001")


# 41. Template creation / 42. required field validation / 43. output_type enum

class TestCreateOutputTemplate(unittest.TestCase):
    def test_creates_with_generated_id(self):
        som = _fresh_som()
        with patch("business_core.sheets.append_business_row") as mock_append, \
             patch.object(som, "generate_output_template_id", return_value="SOUT-001"):
            result = som.create_output_template(biz_id="BIZ-001", title="Договор", output_type="document")
        self.assertTrue(result["ok"])
        self.assertEqual(result["output_template_id"], "SOUT-001")
        mock_append.assert_called_once()

    def test_requires_biz_id(self):
        som = _fresh_som()
        result = som.create_output_template(biz_id="", title="Договор", output_type="document")
        self.assertFalse(result["ok"])

    def test_requires_title(self):
        som = _fresh_som()
        result = som.create_output_template(biz_id="BIZ-001", title="", output_type="document")
        self.assertFalse(result["ok"])

    def test_requires_output_type(self):
        som = _fresh_som()
        result = som.create_output_template(biz_id="BIZ-001", title="Договор", output_type="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_OUTPUT_TYPE")

    def test_invalid_output_type_rejected(self):
        som = _fresh_som()
        result = som.create_output_template(biz_id="BIZ-001", title="Договор", output_type="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_OUTPUT_TYPE")

    def test_every_valid_output_type_accepted(self):
        som = _fresh_som()
        with patch("business_core.sheets.append_business_row"), \
             patch.object(som, "generate_output_template_id", return_value="SOUT-001"):
            for output_type in som.OUTPUT_TYPES:
                result = som.create_output_template(biz_id="BIZ-001", title="X", output_type=output_type)
                self.assertTrue(result["ok"], output_type)


# 44. Status enum / 45-46. Allowed/disallowed transitions

class TestOutputStatusTransitions(unittest.TestCase):
    def test_pending_to_produced_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("pending", "produced"), [])

    def test_rejected_to_produced_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("rejected", "produced"), [])

    def test_pending_to_not_applicable_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("pending", "not_applicable"), [])

    def test_pending_to_submitted_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("pending", "submitted"), [])

    def test_produced_to_submitted_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("produced", "submitted"), [])

    def test_produced_to_accepted_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("produced", "accepted"), [])

    def test_submitted_to_accepted_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("submitted", "accepted"), [])

    def test_submitted_to_rejected_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("submitted", "rejected"), [])

    def test_rejected_to_submitted_allowed(self):
        som = _fresh_som()
        self.assertEqual(som.validate_output_status_transition("rejected", "submitted"), [])

    def test_waive_allowed_from_pending_produced_submitted_rejected(self):
        som = _fresh_som()
        for current in ("pending", "produced", "submitted", "rejected"):
            self.assertEqual(som.validate_output_status_transition(current, "waived"), [])

    def test_terminal_statuses_have_no_outgoing_transitions(self):
        som = _fresh_som()
        for terminal in som.TERMINAL_OUTPUT_STATUSES:
            for target in som.OUTPUT_STATUSES:
                errors = som.validate_output_status_transition(terminal, target)
                self.assertTrue(errors, f"{terminal} -> {target} should be blocked")

    def test_disallowed_transition_pending_to_accepted_rejected(self):
        som = _fresh_som()
        self.assertTrue(som.validate_output_status_transition("pending", "accepted"))
        self.assertTrue(som.validate_output_status_transition("pending", "rejected"))
        # Sanity check: pending -> waived IS allowed (contrast case).
        self.assertEqual(som.validate_output_status_transition("pending", "waived"), [])

    def test_disallowed_transition_produced_to_rejected(self):
        som = _fresh_som()
        self.assertTrue(som.validate_output_status_transition("produced", "rejected"))

    def test_disallowed_transition_rejected_to_accepted(self):
        som = _fresh_som()
        self.assertTrue(som.validate_output_status_transition("rejected", "accepted"))

    def test_unknown_status_rejected(self):
        som = _fresh_som()
        self.assertTrue(som.validate_output_status_transition("pending", "bogus"))
        self.assertTrue(som.validate_output_status_transition("bogus", "produced"))


# 47. Instance creates snapshots / 48. relation required/blocking propagate /
# 49. fallback to template defaults / idempotency

class TestCreateOutputInstance(unittest.TestCase):
    def _template(self, **overrides):
        row = dict(zip(OUTPUT_TEMPLATE_HEADERS, OUTPUT_TEMPLATE_ROW))
        row.update(overrides)
        return row

    def test_snapshots_title_description_type_verification_method(self):
        som = _fresh_som()
        template = self._template()
        with patch.object(som, "find_output_template_by_id", return_value=template), \
             patch.object(som, "_find_existing_instance", return_value=None), \
             patch.object(som, "generate_output_instance_id", return_value="SOUTI-001"), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.row_from_header_map", side_effect=lambda h, v: [v.get(x, "") for x in h]):
            result = som.create_output_instance("SOUT-001", "STAGE-013")
        self.assertTrue(result["ok"])
        written_values = mock_append.call_args[0][1]
        row_dict = dict(zip(OUTPUT_INSTANCE_HEADERS, written_values))
        self.assertEqual(row_dict["Title Snapshot"], template["Title"])
        self.assertEqual(row_dict["Description Snapshot"], template["Description"])
        self.assertEqual(row_dict["Output Type Snapshot"], template["Output Type"])
        self.assertEqual(row_dict["Verification Method Snapshot"], template["Verification Method"])

    def test_explicit_required_blocking_take_priority_over_template_defaults(self):
        som = _fresh_som()
        template = self._template(**{"Default Required": "true", "Default Blocking": "true"})
        with patch.object(som, "find_output_template_by_id", return_value=template), \
             patch.object(som, "_find_existing_instance", return_value=None), \
             patch.object(som, "generate_output_instance_id", return_value="SOUTI-001"), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.row_from_header_map", side_effect=lambda h, v: [v.get(x, "") for x in h]):
            som.create_output_instance("SOUT-001", "STAGE-013", required="false", blocking="false")
        written_values = mock_append.call_args[0][1]
        row_dict = dict(zip(OUTPUT_INSTANCE_HEADERS, written_values))
        self.assertEqual(row_dict["Required"], "false")
        self.assertEqual(row_dict["Blocking"], "false")

    def test_none_required_blocking_falls_back_to_template_defaults(self):
        som = _fresh_som()
        template = self._template(**{"Default Required": "false", "Default Blocking": "true"})
        with patch.object(som, "find_output_template_by_id", return_value=template), \
             patch.object(som, "_find_existing_instance", return_value=None), \
             patch.object(som, "generate_output_instance_id", return_value="SOUTI-001"), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.sheets.row_from_header_map", side_effect=lambda h, v: [v.get(x, "") for x in h]):
            som.create_output_instance("SOUT-001", "STAGE-013", required=None, blocking=None)
        written_values = mock_append.call_args[0][1]
        row_dict = dict(zip(OUTPUT_INSTANCE_HEADERS, written_values))
        self.assertEqual(row_dict["Required"], "false")
        self.assertEqual(row_dict["Blocking"], "true")

    def test_idempotent_per_output_template_and_stage_pair(self):
        som = _fresh_som()
        existing = {"Output Instance ID": "SOUTI-001", "Output Template ID": "SOUT-001", "Stage ID": "STAGE-013"}
        with patch.object(som, "find_output_template_by_id", return_value=self._template()), \
             patch.object(som, "_find_existing_instance", return_value=existing), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = som.create_output_instance("SOUT-001", "STAGE-013")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "OUTPUT_INSTANCE_ALREADY_EXISTS")
        self.assertEqual(result["output_instance_id"], "SOUTI-001")
        mock_append.assert_not_called()

    def test_missing_template_returns_error(self):
        som = _fresh_som()
        with patch.object(som, "find_output_template_by_id", return_value=None):
            result = som.create_output_instance("SOUT-999", "STAGE-013")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OUTPUT_TEMPLATE_NOT_FOUND")


# 56-59: submit/accept/reject/waive evidence + reason requirements + audit

class TestOutputLifecycleFunctions(unittest.TestCase):
    def test_submit_requires_evidence_type(self):
        som = _fresh_som()
        result = som.submit_output_evidence("SOUTI-001", "", "https://x", "111")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EVIDENCE_TYPE_REQUIRED")

    def test_submit_requires_evidence_value(self):
        som = _fresh_som()
        result = som.submit_output_evidence("SOUTI-001", "drive_url", "  ", "111")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EVIDENCE_VALUE_REQUIRED")

    def test_submit_writes_evidence_and_actor_audit(self):
        som = _fresh_som()
        with patch.object(som, "update_output_instance_status", return_value={"ok": True, "code": "", "error": None}) as mock_upd:
            result = som.submit_output_evidence("SOUTI-001", "drive_url", "https://x", "111")
        self.assertTrue(result["ok"])
        args, kwargs = mock_upd.call_args
        self.assertEqual(args[1], "submitted")
        self.assertEqual(kwargs["Evidence Type"], "drive_url")
        self.assertEqual(kwargs["Evidence Value"], "https://x")
        self.assertEqual(kwargs["Submitted By"], "111")
        self.assertTrue(kwargs["Submitted At"])

    def test_accept_writes_actor_audit(self):
        som = _fresh_som()
        with patch.object(som, "update_output_instance_status", return_value={"ok": True, "code": "", "error": None}) as mock_upd:
            som.accept_output_instance("SOUTI-001", "222")
        args, kwargs = mock_upd.call_args
        self.assertEqual(args[1], "accepted")
        self.assertEqual(kwargs["Accepted By"], "222")
        self.assertTrue(kwargs["Accepted At"])

    def test_reject_requires_reason(self):
        som = _fresh_som()
        result = som.reject_output_instance("SOUTI-001", "333", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "REJECTION_REASON_REQUIRED")

    def test_reject_writes_actor_and_reason_audit(self):
        som = _fresh_som()
        with patch.object(som, "update_output_instance_status", return_value={"ok": True, "code": "", "error": None}) as mock_upd:
            som.reject_output_instance("SOUTI-001", "333", "Договор не подписан")
        args, kwargs = mock_upd.call_args
        self.assertEqual(args[1], "rejected")
        self.assertEqual(kwargs["Rejected By"], "333")
        self.assertEqual(kwargs["Rejection Reason"], "Договор не подписан")
        self.assertTrue(kwargs["Rejected At"])

    def test_waive_requires_reason(self):
        som = _fresh_som()
        result = som.waive_output_instance("SOUTI-001", "444", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "WAIVER_REASON_REQUIRED")

    def test_waive_writes_actor_and_reason_audit(self):
        som = _fresh_som()
        with patch.object(som, "update_output_instance_status", return_value={"ok": True, "code": "", "error": None}) as mock_upd:
            som.waive_output_instance("SOUTI-001", "444", "Требование снято клиентом")
        args, kwargs = mock_upd.call_args
        self.assertEqual(args[1], "waived")
        self.assertEqual(kwargs["Waived By"], "444")
        self.assertEqual(kwargs["Waiver Reason"], "Требование снято клиентом")
        self.assertTrue(kwargs["Waived At"])

    def test_update_output_instance_status_rejects_invalid_transition(self):
        som = _fresh_som()
        current = dict(zip(OUTPUT_INSTANCE_HEADERS,
                            ["SOUTI-001", "SOUT-001", "", "", "", "", "STAGE-013"]
                            + [""] * (len(OUTPUT_INSTANCE_HEADERS) - 7)))
        current["Status"] = "accepted"
        with patch("business_core.sheets.find_row_by_id", return_value=(2, current)):
            result = som.update_output_instance_status("SOUTI-001", "produced")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_STATUS_TRANSITION")

    def test_update_output_instance_status_not_found(self):
        som = _fresh_som()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = som.update_output_instance_status("SOUTI-999", "produced")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "OUTPUT_INSTANCE_NOT_FOUND")


class TestReads(unittest.TestCase):
    def test_find_output_template_by_id_not_found(self):
        som = _fresh_som()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(som.find_output_template_by_id("SOUT-999"))

    def test_find_output_template_by_id_found(self):
        som = _fresh_som()
        row_dict = dict(zip(OUTPUT_TEMPLATE_HEADERS, OUTPUT_TEMPLATE_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            result = som.find_output_template_by_id("SOUT-001")
        self.assertEqual(result["Title"], "Подписанный договор с клиентом")

    def test_list_output_templates_for_template_stage_filters(self):
        som = _fresh_som()
        row_a = dict(zip(OUTPUT_TEMPLATE_HEADERS, OUTPUT_TEMPLATE_ROW))
        row_b = dict(row_a)
        row_b["Output Template ID"] = "SOUT-002"
        row_b["Template Stage ID"] = "TSTG-999"
        with patch("business_core.sheets.read_business_sheet", return_value=[row_a, row_b]):
            result = som.list_output_templates_for_template_stage("TSTG-029")
        self.assertEqual([r["Output Template ID"] for r in result], ["SOUT-001"])

    def test_list_output_instances_for_stage_filters(self):
        som = _fresh_som()
        row_a = {"Output Instance ID": "SOUTI-001", "Stage ID": "STAGE-013"}
        row_b = {"Output Instance ID": "SOUTI-002", "Stage ID": "STAGE-999"}
        with patch("business_core.sheets.read_business_sheet", return_value=[row_a, row_b]):
            result = som.list_output_instances_for_stage("STAGE-013")
        self.assertEqual([r["Output Instance ID"] for r in result], ["SOUTI-001"])


# ────────────────────────────────────────────────────────────
# ENTITY_TYPE_DISPATCH["required_output"] + relation creation
# ────────────────────────────────────────────────────────────

class TestRequiredOutputEntityType(unittest.TestCase):
    def test_dispatch_entry_present(self):
        import business_core.stage_entity_relations as ser
        self.assertIn("required_output", ser.ENTITY_TYPE_DISPATCH)
        self.assertEqual(ser.ENTITY_TYPE_DISPATCH["required_output"]["sheet_key"], "stage_output_templates")
        self.assertEqual(ser.ENTITY_TYPE_DISPATCH["required_output"]["id_column"], "Output Template ID")

    def test_dispatch_now_has_four_entries(self):
        import business_core.stage_entity_relations as ser
        self.assertEqual(
            set(ser.ENTITY_TYPE_DISPATCH.keys()),
            {"document_template", "role", "sop", "required_output"},
        )


class TestCreateRequiredOutputRelationForTemplateStage(unittest.TestCase):
    def test_precondition_requires_both_args(self):
        import business_core.stage_entity_relations as ser
        result = ser.create_required_output_relation_for_template_stage("", [], "true", "true")
        self.assertFalse(result.ok)

    def test_template_stage_must_exist(self):
        import business_core.stage_entity_relations as ser
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = ser.create_required_output_relation_for_template_stage(
                "TSTG-999", ["SOUT-001"], "true", "true",
            )
        self.assertFalse(result.ok)

    def test_never_writes_blank_required_blocking(self):
        """The relation write path must always persist a concrete
        true/false — validate_relation_record() rejects blank."""
        import business_core.stage_entity_relations as ser
        with patch("business_core.sheets.find_row_by_id", side_effect=[(1, {}), None]), \
             patch.object(ser, "validate_relation_references", return_value=[]), \
             patch.object(ser, "find_active_duplicate_relation", return_value=None):
            errors = ser.validate_relation_record({
                "Template Stage ID": "TSTG-029", "Stage ID": "",
                "Entity Type": "required_output", "Entity ID": "SOUT-001",
                "Required": "", "Blocking": "true", "Minimum Count": "1", "Status": "active",
            })
        self.assertTrue(errors)  # blank Required must fail structural validation


# ────────────────────────────────────────────────────────────
# business_builder.sync_stage_output_requirements()
# ────────────────────────────────────────────────────────────

_RESOLVED_OK = {
    "ok": True, "code": "", "error": None,
    "stage": {"stage_id": "STAGE-013"},
    "roadmap": {"roadmap_id": "RM-003", "business_id": "BIZ-001", "service_id": "SVC-001", "object_id": "OBJ-001"},
    "template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-029",
    "template_stage_row": {"stage_id": "TSTG-029"},
}

_RELATION_SOUT_001 = {
    "Relation ID": "REL-100", "Template Stage ID": "TSTG-029", "Stage ID": "",
    "Entity Type": "required_output", "Entity ID": "SOUT-001",
    "Required": "true", "Blocking": "true", "Status": "active",
}

_ACTIVE_TEMPLATE = {"Output Template ID": "SOUT-001", "Status": "active"}
_INACTIVE_TEMPLATE = {"Output Template ID": "SOUT-001", "Status": "inactive"}


class TestSyncStageOutputRequirements(unittest.TestCase):
    def test_resolution_failure_propagates(self):
        import business_core.business_builder as bb
        failed = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "Stage STAGE-999 не найден"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed):
            result = bb.sync_stage_output_requirements("STAGE-999", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_no_required_output_relations(self):
        import business_core.business_builder as bb
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_REQUIRED_OUTPUT_RELATIONS")

    def test_preview_shows_to_add_and_does_not_write(self):
        import business_core.business_builder as bb
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_SOUT_001,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_ACTIVE_TEMPLATE), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.create_output_instance") as mock_create:
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=False)

        mock_create.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_OUTPUT_SYNC_PREVIEW")
        self.assertEqual(result["to_add"], ("SOUT-001",))
        self.assertEqual(result["already_present"], ())

    def test_confirm_creates_missing_instances(self):
        import business_core.business_builder as bb
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_SOUT_001,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_ACTIVE_TEMPLATE), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.create_output_instance",
                   return_value={"ok": True, "output_instance_id": "SOUTI-001", "code": "OUTPUT_INSTANCE_CREATED", "error": None}) as mock_create:
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=True)

        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        self.assertEqual(args[0], "SOUT-001")
        self.assertEqual(args[1], "STAGE-013")
        self.assertEqual(kwargs["roadmap_id"], "RM-003")
        self.assertEqual(kwargs["required"], "true")
        self.assertEqual(kwargs["blocking"], "true")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_OUTPUT_SYNCED")
        self.assertEqual(result["created"], ("SOUT-001",))

    def test_idempotent_second_run_reports_already_present(self):
        import business_core.business_builder as bb
        existing = {"Output Template ID": "SOUT-001", "Output Instance ID": "SOUTI-001"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_SOUT_001,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_ACTIVE_TEMPLATE), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=(existing,)), \
             patch("business_core.stage_output_manager.create_output_instance") as mock_create:
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=True)

        mock_create.assert_not_called()
        self.assertEqual(result["to_add"], ())
        self.assertEqual(result["already_present"], ("SOUT-001",))
        self.assertEqual(result["created"], ())

    def test_inactive_output_template_skipped_and_reported(self):
        import business_core.business_builder as bb
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=(_RELATION_SOUT_001,)), \
             patch("business_core.stage_output_manager.find_output_template_by_id", return_value=_INACTIVE_TEMPLATE), \
             patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=()), \
             patch("business_core.stage_output_manager.create_output_instance") as mock_create:
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=True)

        mock_create.assert_not_called()
        self.assertEqual(result["to_add"], ())
        self.assertEqual(result["created"], ())
        self.assertEqual(result["skipped_inactive_templates"], ("SOUT-001",))

    def test_inactive_relation_never_returned_by_get_relations(self):
        """get_relations_for_template_stage() defaults to active-only —
        an inactive relation must never surface as to_add/created at all."""
        import business_core.business_builder as bb
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.sync_stage_output_requirements("STAGE-013", confirm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_REQUIRED_OUTPUT_RELATIONS")

    def test_never_touches_roadmap_stages_writer(self):
        """Architectural guard: sync_stage_output_requirements() must
        never call any ROADMAP_STAGES writer — it only ever calls
        stage_output_manager/stage_entity_relations read+create functions."""
        import ast
        import inspect
        import business_core.business_builder as bb

        source = inspect.getsource(bb.sync_stage_output_requirements)
        tree = ast.parse(source)
        called_names = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("update_stage_fields", called_names)
        self.assertNotIn("update_stage_status_in_sheet", called_names)


# ────────────────────────────────────────────────────────────
# 61-63: Completion Gate isolation guards + regression marker
# ────────────────────────────────────────────────────────────

class TestCompletionGateWiring(unittest.TestCase):
    """Phase B deliberately changes what Phase A's isolation guards
    asserted — this class replaces TestCompletionGateIsolation, which
    asserted the OPPOSITE (no gate wiring at all). Explicitly rewritten,
    not just extended, per the Phase B instruction."""

    def test_transition_stage_status_now_calls_output_gate(self):
        import inspect
        import business_core.business_builder as bb

        source = inspect.getsource(bb.transition_stage_status)
        self.assertIn("_evaluate_output_completion_gate", source)

    def test_transition_stage_status_still_never_calls_sync(self):
        """sync_stage_output_requirements() remains a separate, manually
        triggered (/syncoutputs) retroactive tool — the gate reads
        existing instances/relations directly, it never invokes sync."""
        import inspect
        import business_core.business_builder as bb

        source = inspect.getsource(bb.transition_stage_status)
        self.assertNotIn("sync_stage_output_requirements", source)

    def test_output_completion_gate_function_exists(self):
        import business_core.business_builder as bb
        self.assertTrue(hasattr(bb, "_evaluate_output_completion_gate"))

    def test_document_and_checklist_gate_functions_unchanged_by_name(self):
        import business_core.business_builder as bb
        self.assertTrue(hasattr(bb, "_evaluate_document_completion_gate"))
        self.assertTrue(hasattr(bb, "_evaluate_checklist_completion_gate"))

    def test_stage_completion_overrides_schema_now_includes_output_fields(self):
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS["stage_completion_overrides"]
        self.assertIn("Missing Blocking Output Instance IDs", headers)
        self.assertIn("Missing Blocking Output Template IDs", headers)
        self.assertIn("Missing Blocking Output Titles", headers)
        self.assertIn("Missing Blocking Output Statuses", headers)

    def test_stage_completion_overrides_first_14_columns_unchanged(self):
        """п.27 support: the pre-Phase-B column order must be preserved
        exactly — new fields only ever append at positions 15-18."""
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS["stage_completion_overrides"]
        self.assertEqual(headers[:14], [
            "Override ID", "Stage ID", "Roadmap ID", "User", "Overridden At",
            "Reason", "Missing Blocking Doc IDs", "Previous Status", "Target Status",
            "Override Type", "Configuration Error Details",
            "Missing Checklist Instance IDs", "Missing Checklist Item IDs",
            "Missing Checklist Item Titles",
        ])
        self.assertEqual(headers[14:18], [
            "Missing Blocking Output Instance IDs", "Missing Blocking Output Template IDs",
            "Missing Blocking Output Titles", "Missing Blocking Output Statuses",
        ])

    def test_stage_output_templates_and_instances_schema_unchanged(self):
        """Phase A schema (Часть 6 isolation requirement) must remain
        byte-for-byte untouched by Phase B."""
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["stage_output_templates"], OUTPUT_TEMPLATE_HEADERS)
        self.assertEqual(BUSINESS_HEADERS["stage_output_instances"], OUTPUT_INSTANCE_HEADERS)

    def test_lifecycle_functions_never_reference_the_gate(self):
        """Phase A lifecycle functions must stay one-directional: the
        gate reads them, they never call back into the gate."""
        import inspect
        import business_core.stage_output_manager as som

        for fn in (
            som.submit_output_evidence, som.accept_output_instance,
            som.reject_output_instance, som.waive_output_instance,
            som.update_output_instance_status, som.create_output_instance,
        ):
            source = inspect.getsource(fn)
            self.assertNotIn("_evaluate_output_completion_gate", source)
            self.assertNotIn("transition_stage_status", source)


if __name__ == "__main__":
    unittest.main()
