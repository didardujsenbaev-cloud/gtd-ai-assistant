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

import ast
import sys
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

WORKSPACE = Path(__file__).parent


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

    def test_role_entity_type_valid_reference_has_no_errors(self):
        """Phase 24B: Role existence is checked via
        organization_manager.find_role_by_id(), not a raw role_registry
        Sheet read — a Role that the manager reports as found produces
        no error."""
        ser = self._ser()
        record = _rel_row(**{"Entity Type": "role", "Entity ID": "ROLE-001"})
        with patch(
            "business_core.organization_manager.find_role_by_id",
            return_value={"role_id": "ROLE-001"},
        ) as mock_find_role:
            errors = ser.validate_relation_references(record)
        mock_find_role.assert_called_once_with("ROLE-001")
        self.assertEqual(errors, [])

    def test_role_entity_type_dangling_reference_reported(self):
        """A Role the manager cannot find is still reported as a
        dangling Entity ID — never silently dropped."""
        ser = self._ser()
        record = _rel_row(**{"Entity Type": "role", "Entity ID": "ROLE-999"})
        with patch(
            "business_core.organization_manager.find_role_by_id",
            return_value=None,
        ) as mock_find_role:
            errors = ser.validate_relation_references(record)
        mock_find_role.assert_called_once_with("ROLE-999")
        self.assertTrue(any("ROLE-999" in e and "not found" in e for e in errors))


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

    def test_only_document_template_role_and_sop_supported_today(self):
        """Phase 22B added "role" (Work Execution Foundation), Phase 45
        added "sop" (SOP Foundation UX) — the dispatch table is exactly
        three entries, all additive, none a schema change to
        STAGE_ENTITY_RELATIONS itself. "contractor_person" remains
        explicitly deferred (Phase 22A/22B)."""
        ser = _fresh_ser()
        self.assertEqual(set(ser.ENTITY_TYPE_DISPATCH.keys()), {"document_template", "role", "sop"})

    def test_role_entity_type_dispatch_target(self):
        ser = _fresh_ser()
        entry = ser.ENTITY_TYPE_DISPATCH["role"]
        self.assertEqual(entry["sheet_key"], "role_registry")
        self.assertEqual(entry["id_column"], "Role ID")

    def test_sop_entity_type_dispatch_target(self):
        ser = _fresh_ser()
        entry = ser.ENTITY_TYPE_DISPATCH["sop"]
        self.assertEqual(entry["sheet_key"], "sop_registry")
        self.assertEqual(entry["id_column"], "SOP ID")


# ────────────────────────────────────────────────────────────
# Architecture guard: Role FK validation ownership (Phase 24B)
# ────────────────────────────────────────────────────────────

class TestRoleValidationArchitectureGuard(unittest.TestCase):
    def test_role_branch_does_not_call_find_row_by_id(self):
        """Phase 24B: validate_relation_references() must route Role
        existence checks through organization_manager.find_role_by_id(),
        never through a raw find_row_by_id("role_registry", ...) Sheet
        read. This inspects the AST of the "if entity_type == 'role'"
        branch specifically — every other branch (Template Stage ID,
        Stage ID, and the non-role dispatch fallback) is untouched by
        this guard and keeps using find_row_by_id as before."""
        import ast
        import inspect

        ser = _fresh_ser()
        source = inspect.getsource(ser.validate_relation_references)
        tree = ast.parse(source)
        func_node = tree.body[0]
        self.assertIsInstance(func_node, ast.FunctionDef)

        def is_role_check(node):
            return (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "entity_type"
                and any(isinstance(c, ast.Constant) and c.value == "role" for c in node.test.comparators)
            )

        role_if_nodes = [n for n in ast.walk(func_node) if is_role_check(n)]
        self.assertEqual(len(role_if_nodes), 1, "expected exactly one 'entity_type == role' branch")
        role_branch = role_if_nodes[0].body

        def calls_named(nodes, name):
            for stmt in nodes:
                for call in ast.walk(stmt):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name:
                        return True
            return False

        self.assertTrue(
            calls_named(role_branch, "find_role_by_id"),
            "role branch must call organization_manager.find_role_by_id",
        )
        self.assertFalse(
            calls_named(role_branch, "find_row_by_id"),
            "role branch must not call the raw sheets.find_row_by_id",
        )


# ────────────────────────────────────────────────────────────
# Architecture guard: Relation Layer must not depend on the
# Document Layer (Phase 26B)
# ────────────────────────────────────────────────────────────

class TestNoDocumentLayerDependency(unittest.TestCase):
    """ENGINEERING_STANDARDS.md, Layer Dependency Rules: the Document
    Layer (business_core.document_requirements) may depend on the
    Relation Layer (business_core.stage_entity_relations), never the
    reverse. Phase 26A found a violation (a function-local import of
    document_requirements._parse_id_list inside
    compare_legacy_document_relations()); Phase 26B removed it. This
    guard is module-wide, not just scoped to that one function, since
    the documented rule applies to the whole Relation Layer — any
    future reintroduction anywhere in this module must fail here."""

    def test_module_does_not_import_document_requirements(self):
        path = WORKSPACE / "business_core" / "stage_entity_relations.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))

        forbidden = "document_requirements"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        forbidden, alias.name,
                        f"forbidden import: 'import {alias.name}'",
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(
                    forbidden, node.module,
                    f"forbidden import: 'from {node.module} import ...'",
                )

    def test_no_import_statement_references_parse_id_list(self):
        """Prose mentions of document_requirements.py or its
        _parse_id_list() convention in docstrings/comments are fine
        (that module IS allowed to depend on this one, and this
        module's own docs legitimately explain the local duplicate) —
        what must never reappear is an actual import statement pulling
        _parse_id_list from document_requirements."""
        path = WORKSPACE / "business_core" / "stage_entity_relations.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.assertNotEqual(
                        alias.name, "_parse_id_list",
                        "must not import _parse_id_list from any module",
                    )


# ────────────────────────────────────────────────────────────
# Read-only / no-write guarantees
# ────────────────────────────────────────────────────────────

class TestReadOnlyGuarantees(unittest.TestCase):
    def test_read_and_validation_functions_have_no_write_calls(self):
        """The read/validation/comparison surface (everything except
        the Phase 18C-3 copy_template_relations_to_stage(), which
        legitimately writes new instance relations) must remain
        strictly read-only."""
        import inspect
        ser = _fresh_ser()
        read_only_functions = (
            ser.list_relations, ser.get_relation_by_id,
            ser.get_relations_for_template_stage, ser.get_relations_for_stage,
            ser.validate_relation_record, ser.validate_relation_references,
            ser.find_active_duplicate_relation, ser.compare_legacy_document_relations,
        )
        for fn in read_only_functions:
            source = inspect.getsource(fn)
            for forbidden in ("append_business_row", "update_business_row", "update_business_cell",
                              "batch_append_business_rows", "generate_next_id"):
                self.assertNotIn(forbidden, source, f"{fn.__name__} unexpectedly contains {forbidden!r}")

    def test_module_makes_no_ai_or_drive_calls(self):
        import inspect
        ser = _fresh_ser()
        source = inspect.getsource(ser)
        self.assertNotIn("anthropic", source.lower())
        self.assertNotIn("get_drive_service", source)


# ────────────────────────────────────────────────────────────
# Phase 26B: _parse_legacy_id_list() — local replacement for the
# removed business_core.document_requirements._parse_id_list import.
# Must remain byte-for-byte behaviorally identical to that function.
# ────────────────────────────────────────────────────────────

class TestParseLegacyIdList(unittest.TestCase):
    def test_empty_string_returns_empty_list(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list(""), [])

    def test_none_returns_empty_list(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list(None), [])

    def test_single_id(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list("DOC-002"), ["DOC-002"])

    def test_multiple_ids_preserve_order(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list("DOC-002,DOC-003,DOC-004"), ["DOC-002", "DOC-003", "DOC-004"])

    def test_whitespace_around_tokens_is_stripped(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list(" DOC-002 , DOC-003 "), ["DOC-002", "DOC-003"])

    def test_duplicate_ids_deduplicated_keeping_first_occurrence_order(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list("DOC-002,DOC-003,DOC-002"), ["DOC-002", "DOC-003"])

    def test_empty_tokens_between_commas_are_dropped(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list("DOC-002,,DOC-003,"), ["DOC-002", "DOC-003"])

    def test_only_commas_returns_empty_list(self):
        ser = _fresh_ser()
        self.assertEqual(ser._parse_legacy_id_list(",,,"), [])

    def test_return_type_is_list(self):
        ser = _fresh_ser()
        self.assertIsInstance(ser._parse_legacy_id_list("DOC-002"), list)


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


# ────────────────────────────────────────────────────────────
# Phase 18C-3: copy_template_relations_to_stage()
# ────────────────────────────────────────────────────────────

COPY_TEMPLATE_STAGES = [{"Stage ID": "TSTG-017", "Template ID": "RMT-IZH-ALM-STANDARD-001"}]
COPY_REAL_STAGES = [{"Stage ID": "STAGE-100", "Roadmap ID": "RM-100"}]
COPY_TEMPLATES = [
    {"Document Template ID": "DOC-002", "Title": "Test A", "Status": "active"},
    {"Document Template ID": "DOC-003", "Title": "Test B", "Status": "active"},
]


class _CopyCase(unittest.TestCase):
    def _run(self, template_stage_id="TSTG-017", stage_id="STAGE-100",
              template_stages=None, real_stages=None, templates=None, relations=None,
              destination_exists=True, next_ids=None, batch_side_effect=None,
              timestamp="2026-07-22"):
        ser = _fresh_ser()
        template_stages = COPY_TEMPLATE_STAGES if template_stages is None else template_stages
        real_stages = (COPY_REAL_STAGES if destination_exists else []) if real_stages is None else real_stages
        templates = COPY_TEMPLATES if templates is None else templates
        relations = relations or []

        appended = []

        def _batch_append(sheet_key, rows):
            if batch_side_effect is not None:
                batch_side_effect()
            appended.extend(rows)

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

        mock_sheet = unittest.mock.MagicMock()
        mock_sheet.row_values.return_value = [
            "Relation ID", "Template Stage ID", "Stage ID", "Entity Type", "Entity ID",
            "Required", "Blocking", "Minimum Count", "Status", "Created At", "Updated At",
        ]

        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_ids",
                   return_value=(next_ids if next_ids is not None else ["REL-100", "REL-101", "REL-102"])), \
             patch("business_core.sheets.batch_append_business_rows", side_effect=_batch_append):
            result = ser.copy_template_relations_to_stage(template_stage_id, stage_id, timestamp=timestamp)
        return result, appended


class TestCopyTemplateRelationsToStage(_CopyCase):
    def test_one_relation_creates_one_instance(self):
        result, appended = self._run(relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})])
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.created[0]["Entity ID"], "DOC-002")

    def test_multiple_relations_preserve_source_order(self):
        relations = [
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
            _rel_row(**{"Relation ID": "REL-002", "Entity ID": "DOC-003"}),
        ]
        result, appended = self._run(relations=relations, next_ids=["REL-100", "REL-101"])
        self.assertEqual([c["Entity ID"] for c in result.created], ["DOC-002", "DOC-003"])

    def test_no_source_relations_creates_none(self):
        result, appended = self._run(relations=[])
        self.assertTrue(result.ok)
        self.assertEqual(result.created, ())
        self.assertEqual(appended, [])

    def test_instance_copy_has_blank_template_stage_id(self):
        result, _ = self._run(relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})])
        self.assertEqual(result.created[0]["Template Stage ID"], "")

    def test_instance_copy_has_correct_stage_id(self):
        result, _ = self._run(
            stage_id="STAGE-100", relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})],
        )
        self.assertEqual(result.created[0]["Stage ID"], "STAGE-100")

    def test_required_blocking_minimum_count_copied_exactly(self):
        result, _ = self._run(relations=[_rel_row(**{
            "Relation ID": "REL-001", "Entity ID": "DOC-002",
            "Required": "false", "Blocking": "false", "Minimum Count": "2",
        })])
        created = result.created[0]
        self.assertEqual(created["Required"], "false")
        self.assertEqual(created["Blocking"], "false")
        self.assertEqual(created["Minimum Count"], "2")

    def test_inactive_template_relation_ignored(self):
        result, appended = self._run(relations=[
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002", "Status": "inactive"}),
        ])
        self.assertTrue(result.ok)
        self.assertEqual(result.created, ())
        self.assertEqual(appended, [])

    def test_duplicate_destination_relation_not_recreated(self):
        relations = [
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),  # source (template-scoped)
            _rel_row(**{  # already-copied destination (instance-scoped)
                "Relation ID": "REL-050", "Template Stage ID": "", "Stage ID": "STAGE-100", "Entity ID": "DOC-002",
            }),
        ]
        result, appended = self._run(relations=relations)
        self.assertTrue(result.ok)
        self.assertEqual(result.created, ())
        self.assertEqual(len(result.skipped_duplicates), 1)
        self.assertEqual(result.skipped_duplicates[0], ("REL-001", "REL-050"))
        self.assertEqual(appended, [])

    def test_retry_is_idempotent(self):
        relations = [_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})]
        first, appended1 = self._run(relations=relations, next_ids=["REL-100"])
        self.assertEqual(len(first.created), 1)
        # simulate the retry: the destination relation now already exists
        relations_after = relations + [{
            **_rel_row(**{"Relation ID": "REL-100", "Template Stage ID": "", "Stage ID": "STAGE-100", "Entity ID": "DOC-002"}),
        }]
        second, appended2 = self._run(relations=relations_after)
        self.assertEqual(second.created, ())
        self.assertEqual(len(second.skipped_duplicates), 1)
        self.assertEqual(appended2, [])  # no duplicate write on retry

    def test_same_entity_id_allowed_for_two_different_stage_ids(self):
        relations = [
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
            _rel_row(**{  # existing relation for a DIFFERENT destination stage
                "Relation ID": "REL-050", "Template Stage ID": "", "Stage ID": "STAGE-999", "Entity ID": "DOC-002",
            }),
        ]
        result, appended = self._run(stage_id="STAGE-100", relations=relations)
        self.assertEqual(len(result.created), 1)  # not blocked by the other stage's relation

    def test_invalid_source_relation_visible_not_silently_skipped(self):
        result, appended = self._run(relations=[_rel_row(**{
            "Relation ID": "REL-001", "Entity ID": "DOC-002", "Required": "yes",  # invalid
        })])
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0][0], "REL-001")
        self.assertEqual(appended, [])  # nothing created when a source relation is invalid

    def test_dangling_source_entity_id_visible(self):
        result, appended = self._run(relations=[_rel_row(**{
            "Relation ID": "REL-001", "Entity ID": "DOC-999",
        })])
        self.assertFalse(result.ok)
        self.assertTrue(any("DOC-999" in str(e) for _, errs in result.errors for e in errs))
        self.assertEqual(appended, [])

    def test_dangling_template_stage_id_visible(self):
        result, appended = self._run(
            template_stage_id="TSTG-999",
            relations=[_rel_row(**{"Relation ID": "REL-001", "Template Stage ID": "TSTG-999", "Entity ID": "DOC-002"})],
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("TSTG-999" in str(e) for _, errs in result.errors for e in errs))
        self.assertEqual(appended, [])

    def test_unsupported_entity_type_visible(self):
        """"sop" is now a supported Entity Type (Phase 45) — use
        "checklist" instead as an example of a still-unsupported type."""
        result, appended = self._run(relations=[_rel_row(**{
            "Relation ID": "REL-001", "Entity Type": "checklist", "Entity ID": "CHK-001",
        })])
        self.assertFalse(result.ok)
        self.assertTrue(any("Unsupported Entity Type" in str(e) for _, errs in result.errors for e in errs))
        self.assertEqual(appended, [])

    def test_relation_id_generation_is_deterministic(self):
        result, _ = self._run(
            relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})],
            next_ids=["REL-777"],
        )
        self.assertEqual(result.created[0]["Relation ID"], "REL-777")

    def test_no_writes_before_destination_stage_exists(self):
        result, appended = self._run(destination_exists=False, relations=[
            _rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"}),
        ])
        self.assertFalse(result.ok)
        self.assertEqual(appended, [])
        self.assertTrue(any("does not exist yet" in str(e) for _, errs in result.errors for e in errs))

    def test_partial_failure_produces_explicit_structured_error(self):
        def _boom():
            raise RuntimeError("simulated write failure")

        result, appended = self._run(
            relations=[_rel_row(**{"Relation ID": "REL-001", "Entity ID": "DOC-002"})],
            batch_side_effect=_boom,
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("simulated write failure" in str(e) for _, errs in result.errors for e in errs))

    def test_blank_args_return_precondition_error(self):
        ser = _fresh_ser()
        result = ser.copy_template_relations_to_stage("", "STAGE-100")
        self.assertFalse(result.ok)


# ────────────────────────────────────────────────────────────
# create_document_template_relations_for_stage() — the legacy-column
# fallback counterpart to copy_template_relations_to_stage(), added
# after a live-audit finding that /linkknowledge/roadmap_template_manager.
# update_template_stage_knowledge_ids() only ever writes ROADMAP_TEMPLATE_
# STAGES."Document Template IDs", never a STAGE_ENTITY_RELATIONS row.
# ────────────────────────────────────────────────────────────

class _LegacyCreateCase(unittest.TestCase):
    def _run(self, stage_id="STAGE-100", document_template_ids=("DOC-002",),
              real_stages=None, templates=None, relations=None,
              destination_exists=True, next_ids=None, batch_side_effect=None,
              timestamp="2026-07-22"):
        ser = _fresh_ser()
        real_stages = (COPY_REAL_STAGES if destination_exists else []) if real_stages is None else real_stages
        templates = COPY_TEMPLATES if templates is None else templates
        relations = relations or []

        appended = []

        def _batch_append(sheet_key, rows):
            if batch_side_effect is not None:
                batch_side_effect()
            appended.extend(rows)

        def _read_business_sheet(sheet_key, *a, **kw):
            return {
                "roadmap_stages": real_stages,
                "document_template_registry": templates,
                "stage_entity_relations": relations,
            }.get(sheet_key, [])

        def _find_row_by_id(sheet_key, record_id, *a, **kw):
            table = {
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

        mock_sheet = unittest.mock.MagicMock()
        mock_sheet.row_values.return_value = [
            "Relation ID", "Template Stage ID", "Stage ID", "Entity Type", "Entity ID",
            "Required", "Blocking", "Minimum Count", "Status", "Created At", "Updated At",
        ]

        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.sheets.get_business_sheet", return_value=mock_sheet), \
             patch("business_core.sheets.generate_next_ids",
                   return_value=(next_ids if next_ids is not None else ["REL-200", "REL-201", "REL-202"])), \
             patch("business_core.sheets.batch_append_business_rows", side_effect=_batch_append):
            result = ser.create_document_template_relations_for_stage(
                stage_id, list(document_template_ids), timestamp=timestamp,
            )
        return result, appended


class TestCreateDocumentTemplateRelationsForStage(_LegacyCreateCase):
    def test_one_id_creates_one_instance_relation(self):
        result, appended = self._run(document_template_ids=("DOC-002",))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.created[0]["Entity ID"], "DOC-002")
        self.assertEqual(result.created[0]["Entity Type"], "document_template")
        self.assertEqual(result.created[0]["Stage ID"], "STAGE-100")
        self.assertEqual(result.created[0]["Template Stage ID"], "")
        self.assertEqual(len(appended), 1)

    def test_uses_established_document_template_defaults(self):
        """Required=true, Blocking=true, Minimum Count=1 — the same
        defaults every existing document_template relation row in
        production already has."""
        result, _ = self._run(document_template_ids=("DOC-002",))
        created = result.created[0]
        self.assertEqual(created["Required"], "true")
        self.assertEqual(created["Blocking"], "true")
        self.assertEqual(created["Minimum Count"], "1")
        self.assertEqual(created["Status"], "active")

    def test_multiple_ids_create_multiple_relations(self):
        result, appended = self._run(document_template_ids=("DOC-002", "DOC-003"))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 2)
        self.assertEqual(len(appended), 2)

    def test_dangling_document_template_id_visible_not_written(self):
        result, appended = self._run(document_template_ids=("DOC-999-MISSING",))
        self.assertFalse(result.ok)
        self.assertEqual(appended, [])
        self.assertTrue(any("DOC-999-MISSING" in str(e) for _, errs in result.errors for e in errs))

    def test_duplicate_active_relation_not_recreated(self):
        result, appended = self._run(
            document_template_ids=("DOC-002",),
            relations=[_rel_row(**{"Relation ID": "REL-050", "Template Stage ID": "",
                                    "Stage ID": "STAGE-100", "Entity ID": "DOC-002"})],
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.created, ())
        self.assertEqual(appended, [])
        self.assertEqual(len(result.skipped_duplicates), 1)

    def test_retry_is_idempotent(self):
        existing = [_rel_row(**{"Relation ID": "REL-050", "Template Stage ID": "",
                                 "Stage ID": "STAGE-100", "Entity ID": "DOC-002"})]
        result1, appended1 = self._run(document_template_ids=("DOC-002", "DOC-003"), relations=existing)
        self.assertTrue(result1.ok)
        self.assertEqual(len(result1.created), 1)  # only DOC-003 is new
        self.assertEqual(result1.created[0]["Entity ID"], "DOC-003")

    def test_deduplicates_repeated_ids_in_input(self):
        result, appended = self._run(document_template_ids=("DOC-002", "DOC-002"))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.created), 1)

    def test_no_writes_before_destination_stage_exists(self):
        result, appended = self._run(destination_exists=False, document_template_ids=("DOC-002",))
        self.assertFalse(result.ok)
        self.assertEqual(appended, [])
        self.assertTrue(any("does not exist yet" in str(e) for _, errs in result.errors for e in errs))

    def test_blank_args_return_precondition_error(self):
        ser = _fresh_ser()
        result = ser.create_document_template_relations_for_stage("STAGE-100", [])
        self.assertFalse(result.ok)

        result2 = ser.create_document_template_relations_for_stage("", ["DOC-002"])
        self.assertFalse(result2.ok)

    def test_partial_failure_produces_explicit_structured_error(self):
        def _boom():
            raise RuntimeError("simulated write failure")

        result, appended = self._run(document_template_ids=("DOC-002",), batch_side_effect=_boom)
        self.assertFalse(result.ok)
        self.assertTrue(any("simulated write failure" in str(e) for _, errs in result.errors for e in errs))

    def test_only_appends_to_stage_entity_relations_sheet(self):
        """get_business_sheet/batch_append_business_rows must only ever
        target 'stage_entity_relations' — ROADMAP_STAGES is read once
        (existence precondition) but never written."""
        ser = _fresh_ser()

        write_targets = []

        def _batch_append(sheet_key, rows):
            write_targets.append(sheet_key)

        get_business_sheet_targets = []

        def _get_business_sheet(sheet_key):
            get_business_sheet_targets.append(sheet_key)
            mock_sheet = unittest.mock.MagicMock()
            mock_sheet.row_values.return_value = [
                "Relation ID", "Template Stage ID", "Stage ID", "Entity Type", "Entity ID",
                "Required", "Blocking", "Minimum Count", "Status", "Created At", "Updated At",
            ]
            return mock_sheet

        def _read_business_sheet(sheet_key, *a, **kw):
            return {
                "roadmap_stages": COPY_REAL_STAGES,
                "document_template_registry": COPY_TEMPLATES,
                "stage_entity_relations": [],
            }.get(sheet_key, [])

        def _find_row_by_id(sheet_key, record_id, *a, **kw):
            table = {
                "roadmap_stages": (COPY_REAL_STAGES, "Stage ID"),
                "document_template_registry": (COPY_TEMPLATES, "Document Template ID"),
            }.get(sheet_key)
            if table is None:
                return None
            rows, key_field = table
            for i, row in enumerate(rows, start=2):
                if row.get(key_field, "") == record_id:
                    return (i, row)
            return None

        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet), \
             patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id), \
             patch("business_core.sheets.get_business_sheet", side_effect=_get_business_sheet), \
             patch("business_core.sheets.generate_next_ids", return_value=["REL-300"]), \
             patch("business_core.sheets.batch_append_business_rows", side_effect=_batch_append):
            ser.create_document_template_relations_for_stage("STAGE-100", ["DOC-002"])

        self.assertEqual(write_targets, ["stage_entity_relations"])
        self.assertEqual(get_business_sheet_targets, ["stage_entity_relations"])


if __name__ == "__main__":
    unittest.main()
