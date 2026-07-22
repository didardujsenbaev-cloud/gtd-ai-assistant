"""
Phase 18C-1: Stage-to-Entity Relation Foundation — tests.

Covers business_core.stage_entity_relations: read helpers
(list_relations/get_relation_by_id/get_relations_for_template_stage/
get_relations_for_stage), structural validation
(validate_relation_record), referential validation
(validate_relation_references), and active-duplicate detection
(find_active_duplicate_relation).

Strictly against the mocked sheets layer — no live network calls, no
relation rows are ever written to production in this phase.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


def _fresh_ser():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.stage_entity_relations as ser
    return ser


TEMPLATE_STAGES = [
    {"Stage ID": "TSTG-017", "Template ID": "RMT-IZH-ALM-STANDARD-001"},
    {"Stage ID": "TSTG-019", "Template ID": "RMT-IZH-ALM-STANDARD-001"},
]

REAL_STAGES = [
    {"Stage ID": "STAGE-001", "Roadmap ID": "RM-001"},
    {"Stage ID": "STAGE-002", "Roadmap ID": "RM-001"},
]

DOC_TEMPLATES = [
    {"Document Template ID": "DOC-002", "Title": "Удостоверение личности клиента"},
    {"Document Template ID": "DOC-003", "Title": "Документ на земельный участок"},
]


def _rel_row(**overrides):
    row = {
        "Relation ID": "REL-001",
        "Template Stage ID": "TSTG-017",
        "Stage ID": "",
        "Entity Type": "document_template",
        "Entity ID": "DOC-002",
        "Required": "true",
        "Blocking": "true",
        "Minimum Count": "1",
        "Status": "active",
        "Created At": "2026-07-22",
        "Updated At": "2026-07-22",
    }
    row.update(overrides)
    return row


def _patch_sheets(template_stages=None, real_stages=None, templates=None, relations=None):
    template_stages = TEMPLATE_STAGES if template_stages is None else template_stages
    real_stages = REAL_STAGES if real_stages is None else real_stages
    templates = DOC_TEMPLATES if templates is None else templates
    relations = relations or []

    def _read_business_sheet(sheet_key, *a, **kw):
        return {
            "roadmap_template_stages": template_stages,
            "roadmap_stages": real_stages,
            "document_template_registry": templates,
            "stage_entity_relations": relations,
        }.get(sheet_key, [])

    def _find_row_by_id(sheet_key, record_id, *a, **kw):
        table = {
            "roadmap_template_stages": (template_stages, "Stage ID"),
            "roadmap_stages": (real_stages, "Stage ID"),
            "document_template_registry": (templates, "Document Template ID"),
            "stage_entity_relations": (relations, "Relation ID"),
        }.get(sheet_key)
        if table is None:
            return None
        rows, key_field = table
        for i, row in enumerate(rows, start=2):
            if row.get(key_field, "") == record_id:
                return (i, row)
        return None

    return [
        patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet),
        patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id),
    ]


import contextlib


class _PatchedCase(unittest.TestCase):
    def _ser(self, **kwargs):
        ser = _fresh_ser()
        patches = _patch_sheets(**kwargs)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        self.addCleanup(stack.close)
        return ser


# ────────────────────────────────────────────────────────────
# Read helpers
# ────────────────────────────────────────────────────────────

class TestListRelations(_PatchedCase):
    def test_empty_registry_returns_empty_tuple(self):
        ser = self._ser(relations=[])
        self.assertEqual(ser.list_relations(), ())

    def test_template_stage_relation_read(self):
        ser = self._ser(relations=[_rel_row()])
        rows = ser.get_relations_for_template_stage("TSTG-017")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Entity ID"], "DOC-002")

    def test_instantiated_stage_relation_read(self):
        ser = self._ser(relations=[_rel_row(**{
            "Relation ID": "REL-002", "Template Stage ID": "", "Stage ID": "STAGE-001",
        })])
        rows = ser.get_relations_for_stage("STAGE-001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Stage ID"], "STAGE-001")

    def test_entity_type_filtering(self):
        ser = self._ser(relations=[
            _rel_row(**{"Relation ID": "REL-001", "Entity Type": "document_template", "Entity ID": "DOC-002"}),
            _rel_row(**{"Relation ID": "REL-002", "Entity Type": "sop", "Entity ID": "SOP-001"}),
        ])
        rows = ser.get_relations_for_template_stage("TSTG-017", entity_type="document_template")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Relation ID"], "REL-001")

    def test_inactive_rows_excluded_by_default(self):
        ser = self._ser(relations=[
            _rel_row(**{"Relation ID": "REL-001", "Status": "active"}),
            _rel_row(**{"Relation ID": "REL-002", "Status": "inactive"}),
        ])
        active_only = ser.list_relations()
        self.assertEqual(len(active_only), 1)
        self.assertEqual(active_only[0]["Relation ID"], "REL-001")

    def test_inactive_rows_included_when_requested(self):
        ser = self._ser(relations=[
            _rel_row(**{"Relation ID": "REL-001", "Status": "active"}),
            _rel_row(**{"Relation ID": "REL-002", "Status": "inactive"}),
        ])
        all_rows = ser.list_relations(include_inactive=True)
        self.assertEqual(len(all_rows), 2)

    def test_deterministic_ordering_matches_sheet_order(self):
        rows_in = [
            _rel_row(**{"Relation ID": "REL-003", "Entity ID": "DOC-003"}),
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
            _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-002"}),
        ]
        ser = self._ser(relations=rows_in)
        result = ser.list_relations()
        self.assertEqual([r["Relation ID"] for r in result], ["REL-003", "REL-001", "REL-002"])

    def test_get_relation_by_id_found(self):
        ser = self._ser(relations=[_rel_row()])
        row = ser.get_relation_by_id("REL-001")
        self.assertIsNotNone(row)
        self.assertEqual(row["Entity ID"], "DOC-002")

    def test_get_relation_by_id_returns_inactive_row_too(self):
        """A direct-ID lookup must not silently hide an inactive row."""
        ser = self._ser(relations=[_rel_row(**{"Status": "inactive"})])
        row = ser.get_relation_by_id("REL-001")
        self.assertIsNotNone(row)

    def test_get_relation_by_id_not_found(self):
        ser = self._ser(relations=[])
        self.assertIsNone(ser.get_relation_by_id("REL-999"))

    def test_get_relations_for_stage_never_omits_dangling_entity_id(self):
        """A relation pointing at an Entity ID absent from the target
        registry must still be returned by the read helper — never
        silently dropped."""
        ser = self._ser(relations=[_rel_row(**{
            "Relation ID": "REL-001", "Template Stage ID": "", "Stage ID": "STAGE-001",
            "Entity ID": "DOC-999",
        })])
        rows = ser.get_relations_for_stage("STAGE-001")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Entity ID"], "DOC-999")


# ────────────────────────────────────────────────────────────
# Structural validation: validate_relation_record
# ────────────────────────────────────────────────────────────

class TestValidateRelationRecord(unittest.TestCase):
    def test_valid_template_scope_record_has_no_errors(self):
        ser = _fresh_ser()
        self.assertEqual(ser.validate_relation_record(_rel_row()), [])

    def test_valid_instance_scope_record_has_no_errors(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Template Stage ID": "", "Stage ID": "STAGE-001"})
        self.assertEqual(ser.validate_relation_record(record), [])

    def test_both_stage_ids_populated_is_invalid(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Template Stage ID": "TSTG-017", "Stage ID": "STAGE-001"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Both" in e for e in errors))

    def test_both_stage_ids_blank_is_invalid(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Template Stage ID": "", "Stage ID": ""})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Neither" in e for e in errors))

    def test_unsupported_entity_type_is_invalid(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Entity Type": "training"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Unsupported Entity Type" in e for e in errors))

    def test_blank_entity_id_is_invalid(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Entity ID": ""})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Entity ID is blank" in e for e in errors))

    def test_invalid_required_value(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Required": "yes"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Required must be" in e for e in errors))

    def test_invalid_blocking_value(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Blocking": "1"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Blocking must be" in e for e in errors))

    def test_invalid_minimum_count_zero(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Minimum Count": "0"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Minimum Count must be >= 1" in e for e in errors))

    def test_invalid_minimum_count_non_numeric(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Minimum Count": "two"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("positive integer" in e for e in errors))

    def test_invalid_status_value(self):
        ser = _fresh_ser()
        record = _rel_row(**{"Status": "draft"})
        errors = ser.validate_relation_record(record)
        self.assertTrue(any("Status must be" in e for e in errors))

    def test_multiple_errors_all_reported(self):
        ser = _fresh_ser()
        record = _rel_row(**{
            "Template Stage ID": "", "Stage ID": "",
            "Entity Type": "training", "Entity ID": "",
            "Required": "y", "Blocking": "n",
            "Minimum Count": "0", "Status": "draft",
        })
        errors = ser.validate_relation_record(record)
        self.assertGreaterEqual(len(errors), 7)


# ────────────────────────────────────────────────────────────
# Referential validation: validate_relation_references
# ────────────────────────────────────────────────────────────

class TestValidateRelationReferences(_PatchedCase):
    def test_valid_references_have_no_errors(self):
        ser = self._ser()
        self.assertEqual(ser.validate_relation_references(_rel_row()), [])

    def test_dangling_template_stage_id(self):
        ser = self._ser()
        record = _rel_row(**{"Template Stage ID": "TSTG-999"})
        errors = ser.validate_relation_references(record)
        self.assertTrue(any("Template Stage ID" in e and "not found" in e for e in errors))

    def test_dangling_stage_id(self):
        ser = self._ser()
        record = _rel_row(**{"Template Stage ID": "", "Stage ID": "STAGE-999"})
        errors = ser.validate_relation_references(record)
        self.assertTrue(any("Stage ID" in e and "not found" in e for e in errors))

    def test_dangling_entity_id_reported_never_silently_dropped(self):
        ser = self._ser()
        record = _rel_row(**{"Entity ID": "DOC-999"})
        errors = ser.validate_relation_references(record)
        self.assertTrue(any("DOC-999" in e and "not found" in e for e in errors))

    def test_unsupported_entity_type_does_not_crash_reference_check(self):
        """An unsupported Entity Type has no dispatch entry — reference
        checking must degrade gracefully (structural validation already
        flags the type itself), never raise."""
        ser = self._ser()
        record = _rel_row(**{"Entity Type": "training", "Entity ID": "TRN-001"})
        errors = ser.validate_relation_references(record)
        self.assertEqual(errors, [])  # no crash; nothing to check without a dispatch entry


# ────────────────────────────────────────────────────────────
# Active-duplicate detection: find_active_duplicate_relation
# ────────────────────────────────────────────────────────────

class TestFindActiveDuplicateRelation(_PatchedCase):
    def test_duplicate_active_template_relation_detected(self):
        existing = _rel_row(**{"Relation ID": "REL-001"})
        ser = self._ser(relations=[existing])
        candidate = _rel_row(**{"Relation ID": "REL-002"})  # same scope/type/entity, different ID
        dup = ser.find_active_duplicate_relation(candidate)
        self.assertIsNotNone(dup)
        self.assertEqual(dup["Relation ID"], "REL-001")

    def test_duplicate_active_instance_relation_detected(self):
        existing = _rel_row(**{
            "Relation ID": "REL-001", "Template Stage ID": "", "Stage ID": "STAGE-001",
        })
        ser = self._ser(relations=[existing])
        candidate = _rel_row(**{
            "Relation ID": "REL-002", "Template Stage ID": "", "Stage ID": "STAGE-001",
        })
        dup = ser.find_active_duplicate_relation(candidate)
        self.assertIsNotNone(dup)

    def test_same_entity_id_allowed_on_different_stages(self):
        existing = _rel_row(**{"Relation ID": "REL-001", "Template Stage ID": "TSTG-017"})
        ser = self._ser(relations=[existing])
        candidate = _rel_row(**{"Relation ID": "REL-002", "Template Stage ID": "TSTG-019"})
        dup = ser.find_active_duplicate_relation(candidate)
        self.assertIsNone(dup)

    def test_inactive_existing_row_does_not_block_new_active_relation(self):
        existing = _rel_row(**{"Relation ID": "REL-001", "Status": "inactive"})
        ser = self._ser(relations=[existing])
        candidate = _rel_row(**{"Relation ID": "REL-002"})
        dup = ser.find_active_duplicate_relation(candidate)
        self.assertIsNone(dup)

    def test_record_never_compared_against_itself(self):
        existing = _rel_row(**{"Relation ID": "REL-001"})
        ser = self._ser(relations=[existing])
        dup = ser.find_active_duplicate_relation(existing)
        self.assertIsNone(dup)

    def test_different_entity_type_same_id_not_a_duplicate(self):
        existing = _rel_row(**{"Relation ID": "REL-001", "Entity Type": "document_template"})
        ser = self._ser(relations=[existing])
        candidate = _rel_row(**{"Relation ID": "REL-002", "Entity Type": "sop"})
        dup = ser.find_active_duplicate_relation(candidate)
        self.assertIsNone(dup)


# ────────────────────────────────────────────────────────────
# Entity Type dispatcher
# ────────────────────────────────────────────────────────────

class TestEntityTypeDispatcher(unittest.TestCase):
    def test_document_template_dispatch_entry(self):
        ser = _fresh_ser()
        entry = ser.ENTITY_TYPE_DISPATCH["document_template"]
        self.assertEqual(entry["sheet_key"], "document_template_registry")
        self.assertEqual(entry["id_column"], "Document Template ID")

    def test_only_document_template_supported_today(self):
        ser = _fresh_ser()
        self.assertEqual(set(ser.ENTITY_TYPE_DISPATCH.keys()), {"document_template"})


# ────────────────────────────────────────────────────────────
# Read-only / no-write guarantees
# ────────────────────────────────────────────────────────────

class TestReadOnlyGuarantees(unittest.TestCase):
    def test_module_has_no_write_calls(self):
        import inspect
        ser = _fresh_ser()
        source = inspect.getsource(ser)
        for forbidden in ("append_business_row", "update_business_row", "update_business_cell",
                          "batch_append_business_rows", "generate_next_id"):
            self.assertNotIn(forbidden, source)

    def test_module_makes_no_ai_or_drive_calls(self):
        import inspect
        ser = _fresh_ser()
        source = inspect.getsource(ser)
        self.assertNotIn("anthropic", source.lower())
        self.assertNotIn("get_drive_service", source)


# ────────────────────────────────────────────────────────────
# Phase 18C-2: dual-read comparison — compare_legacy_document_relations()
# ────────────────────────────────────────────────────────────

def _tstg_row(**overrides):
    row = {
        "Stage ID": "TSTG-017", "Template ID": "RMT-IZH-ALM-STANDARD-001",
        "Order": "1", "Stage Name": "Test Stage",
        "Document Template IDs": "",
    }
    row.update(overrides)
    return row


def _dt_row(**overrides):
    row = {"Document Template ID": "DOC-002", "Title": "Test Template", "Status": "active"}
    row.update(overrides)
    return row


def _patch_compare(template_stages=None, templates=None, relations=None):
    template_stages = template_stages if template_stages is not None else [_tstg_row()]
    templates = templates if templates is not None else [_dt_row()]
    relations = relations or []

    def _read_business_sheet(sheet_key, *a, **kw):
        return {
            "roadmap_template_stages": template_stages,
            "document_template_registry": templates,
            "stage_entity_relations": relations,
        }.get(sheet_key, [])

    def _find_row_by_id(sheet_key, record_id, *a, **kw):
        table = {
            "roadmap_template_stages": (template_stages, "Stage ID"),
            "document_template_registry": (templates, "Document Template ID"),
            "stage_entity_relations": (relations, "Relation ID"),
        }.get(sheet_key)
        if table is None:
            return None
        rows, key_field = table
        for i, row in enumerate(rows, start=2):
            if row.get(key_field, "") == record_id:
                return (i, row)
        return None

    return [
        patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet),
        patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id),
    ]


class _CompareCase(unittest.TestCase):
    def _compare(self, template_stages=None, templates=None, relations=None):
        ser = _fresh_ser()
        patches = _patch_compare(template_stages=template_stages, templates=templates, relations=relations)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        self.addCleanup(stack.close)
        return ser.compare_legacy_document_relations()


class TestCompareLegacyDocumentRelations(_CompareCase):
    def test_exact_legacy_new_match(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002,DOC-003"})],
            templates=[_dt_row(**{"Document Template ID": "DOC-002"}), _dt_row(**{"Document Template ID": "DOC-003"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-003"}),
            ],
        )
        self.assertTrue(audit.is_globally_consistent)
        stage = audit.per_stage[0]
        self.assertTrue(stage.ordered_match)
        self.assertEqual(stage.missing, ())
        self.assertEqual(stage.extra, ())

    def test_missing_new_relation(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002,DOC-003"})],
            templates=[_dt_row(**{"Document Template ID": "DOC-002"}), _dt_row(**{"Document Template ID": "DOC-003"})],
            relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})],
        )
        stage = audit.per_stage[0]
        self.assertFalse(stage.ordered_match)
        self.assertEqual(stage.missing, ("DOC-003",))
        self.assertFalse(audit.is_globally_consistent)

    def test_extra_new_relation(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002"})],
            templates=[_dt_row(**{"Document Template ID": "DOC-002"}), _dt_row(**{"Document Template ID": "DOC-003"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-003"}),
            ],
        )
        stage = audit.per_stage[0]
        self.assertFalse(stage.ordered_match)
        self.assertEqual(stage.extra, ("DOC-003",))

    def test_different_order_is_a_mismatch(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002,DOC-003"})],
            templates=[_dt_row(**{"Document Template ID": "DOC-002"}), _dt_row(**{"Document Template ID": "DOC-003"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-003"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-002"}),
            ],
        )
        stage = audit.per_stage[0]
        self.assertEqual(stage.missing, ())
        self.assertEqual(stage.extra, ())
        self.assertFalse(stage.ordered_match)  # same set, different order -> still a mismatch

    def test_duplicate_active_relation(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-002"}),
            ],
        )
        stage = audit.per_stage[0]
        self.assertEqual(stage.duplicate_active_relations, ("DOC-002",))
        self.assertFalse(stage.ordered_match)

    def test_inactive_relation_ignored(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002", "Status": "active"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-002", "Status": "inactive"}),
            ],
        )
        stage = audit.per_stage[0]
        # only one ACTIVE relation counts -> no duplicate, exact match
        self.assertEqual(stage.duplicate_active_relations, ())
        self.assertTrue(stage.ordered_match)

    def test_blank_legacy_and_blank_relation_set(self):
        audit = self._compare(template_stages=[_tstg_row(**{"Document Template IDs": ""})], relations=[])
        stage = audit.per_stage[0]
        self.assertEqual(stage.legacy_ids, ())
        self.assertEqual(stage.new_ids, ())
        self.assertTrue(stage.ordered_match)
        self.assertTrue(audit.is_globally_consistent)

    def test_legacy_duplicate_id(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002,DOC-002"})],
            relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})],
        )
        stage = audit.per_stage[0]
        self.assertEqual(stage.legacy_duplicate_ids, ("DOC-002",))
        self.assertFalse(stage.ordered_match)

    def test_dangling_new_entity_id(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002"})],
            templates=[_dt_row(**{"Document Template ID": "DOC-002"})],
            relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-999"})],
        )
        stage = audit.per_stage[0]
        self.assertEqual(stage.dangling_entity_ids, ("DOC-999",))
        self.assertFalse(stage.ordered_match)
        self.assertEqual(stage.missing, ("DOC-002",))  # legacy DOC-002 never satisfied by the dangling relation

    def test_dangling_template_stage_id_is_an_orphan_relation(self):
        audit = self._compare(
            template_stages=[_tstg_row()],
            relations=[_rel_row(**{"Relation ID": "REL-001", "Template Stage ID": "TSTG-999"})],
        )
        self.assertEqual(len(audit.orphan_relations), 1)
        self.assertEqual(audit.orphan_relations[0]["Relation ID"], "REL-001")
        self.assertFalse(audit.is_globally_consistent)

    def test_invalid_scope_with_stage_id_populated(self):
        audit = self._compare(
            template_stages=[_tstg_row()],
            relations=[_rel_row(**{
                "Relation ID": "REL-001", "Template Stage ID": "TSTG-017", "Stage ID": "STAGE-001",
            })],
        )
        self.assertEqual(audit.invalid_scope_relation_ids, ("REL-001",))
        self.assertFalse(audit.is_globally_consistent)

    def test_unsupported_entity_type_excluded_from_comparison_but_reported(self):
        audit = self._compare(
            template_stages=[_tstg_row(**{"Document Template IDs": "DOC-002"})],
            relations=[
                _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
                _rel_row(**{"Relation ID": "REL-002", "Entity Type": "sop", "Entity ID": "SOP-001"}),
            ],
        )
        stage = audit.per_stage[0]
        self.assertTrue(stage.ordered_match)  # the sop relation doesn't affect document comparison
        self.assertEqual(stage.unsupported_entity_type_relation_ids, ("REL-002",))

    def test_deterministic_comparison_output(self):
        template_stages = [
            _tstg_row(**{"Stage ID": "TSTG-017", "Document Template IDs": "DOC-002"}),
            _tstg_row(**{"Stage ID": "TSTG-019", "Document Template IDs": "DOC-003"}),
        ]
        templates = [_dt_row(**{"Document Template ID": "DOC-002"}), _dt_row(**{"Document Template ID": "DOC-003"})]
        relations = [
            _rel_row(**{"Relation ID": "REL-001", "Template Stage ID": "TSTG-017", "Entity ID": "DOC-002"}),
            _rel_row(**{"Relation ID": "REL-002", "Template Stage ID": "TSTG-019", "Entity ID": "DOC-003"}),
        ]
        audit1 = self._compare(template_stages=template_stages, templates=templates, relations=relations)
        audit2 = self._compare(template_stages=template_stages, templates=templates, relations=relations)
        self.assertEqual(
            [s.template_stage_id for s in audit1.per_stage],
            [s.template_stage_id for s in audit2.per_stage],
        )
        self.assertEqual([s.template_stage_id for s in audit1.per_stage], ["TSTG-017", "TSTG-019"])

    def test_covers_every_template_stage_not_only_populated_ones(self):
        template_stages = [
            _tstg_row(**{"Stage ID": "TSTG-017", "Document Template IDs": "DOC-002"}),
            _tstg_row(**{"Stage ID": "TSTG-018", "Document Template IDs": ""}),
        ]
        audit = self._compare(
            template_stages=template_stages,
            relations=[_rel_row(**{"Relation ID": "REL-001", "Template Stage ID": "TSTG-017", "Entity ID": "DOC-002"})],
        )
        self.assertEqual(len(audit.per_stage), 2)
        stage_ids = {s.template_stage_id for s in audit.per_stage}
        self.assertEqual(stage_ids, {"TSTG-017", "TSTG-018"})


class TestCompareLegacyDocumentRelationsNoWrites(unittest.TestCase):
    def test_comparison_helper_performs_no_writes(self):
        import inspect
        ser = _fresh_ser()
        source = inspect.getsource(ser.compare_legacy_document_relations)
        for forbidden in ("append_business_row", "update_business_row", "update_business_cell",
                          "batch_append_business_rows"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
