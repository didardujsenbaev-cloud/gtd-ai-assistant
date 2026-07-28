"""
Dependencies Foundation (2026-07-28, DECISIONS.md §14a): manager-level
tests for business_core.stage_dependency_manager — TEMPLATE_STAGE_
DEPENDENCIES creation, resolution and cycle detection.

Strictly against mocked business_core.sheets / business_core.
roadmap_manager functions — no live network calls, no production data
touched.

PRS-003 incident reference: this file is registered in conftest.py's
hard socket-block list — any accidental real network call here must
raise, not silently succeed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch, MagicMock


def _fresh_sdm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.stage_dependency_manager as sdm
    return sdm


def _template_stage_row(stage_id, template_id="RMT-IZH-ALM-STANDARD-002", order="1"):
    return {"Stage ID": stage_id, "Template ID": template_id, "Order": order}


def _find_row_by_id_side_effect(rows_by_id):
    def _side_effect(sheet_key, row_id):
        if sheet_key != "roadmap_template_stages":
            return None
        row = rows_by_id.get(row_id)
        return (2, row) if row is not None else None
    return _side_effect


class _FakeSheet:
    """Minimal gspread-worksheet stand-in for _find_dependency_row /
    _reactivate_dependency / create's own append path — only the
    methods stage_dependency_manager actually calls."""

    def __init__(self, headers, rows):
        self._headers = headers
        self._rows = rows  # list[list[str]], parallel to headers
        self.updates = []

    def get_all_values(self):
        return [self._headers] + [list(r) for r in self._rows]

    def row_values(self, n):
        assert n == 1
        return list(self._headers)

    def update_cell(self, row_num, col_num, value):
        self.updates.append((row_num, col_num, value))
        idx = row_num - 2
        self._rows[idx][col_num - 1] = value


_DEP_HEADERS = [
    "Dependency ID", "Roadmap Template ID", "Template Stage ID",
    "Depends On Template Stage ID", "Dependency Type", "Blocking", "Status",
    "Created At", "Updated At", "Notes",
]


def _dep_row(dependency_id="TDEP-001", roadmap_template_id="RMT-IZH-ALM-STANDARD-002",
             template_stage_id="TSTG-035", depends_on="TSTG-034",
             dependency_type="finish_to_start", blocking="true", status="active",
             created_at="2026-07-28", updated_at="2026-07-28", notes=""):
    return [dependency_id, roadmap_template_id, template_stage_id, depends_on,
            dependency_type, blocking, status, created_at, updated_at, notes]


def _dep_dict_from_row(row):
    return dict(zip(_DEP_HEADERS, row))


# ═══════════════════════════════════════════════════════════════
# list_dependencies_for_template_stage / find_dependency_by_id
# ═══════════════════════════════════════════════════════════════

class TestReads(unittest.TestCase):
    def test_list_dependencies_empty_template_stage_id(self):
        sdm = _fresh_sdm()
        self.assertEqual(sdm.list_dependencies_for_template_stage(""), ())

    def test_list_dependencies_filters_by_template_stage_and_active(self):
        sdm = _fresh_sdm()
        rows = [
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-001", template_stage_id="TSTG-035", status="active")),
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-002", template_stage_id="TSTG-035", status="inactive")),
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-003", template_stage_id="TSTG-999", status="active")),
        ]
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            active_only = sdm.list_dependencies_for_template_stage("TSTG-035")
            self.assertEqual(len(active_only), 1)
            self.assertEqual(active_only[0]["Dependency ID"], "TDEP-001")

            all_rows = sdm.list_dependencies_for_template_stage("TSTG-035", active_only=False)
            self.assertEqual(len(all_rows), 2)

    def test_find_dependency_by_id_found(self):
        sdm = _fresh_sdm()
        row = _dep_dict_from_row(_dep_row())
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
            found = sdm.find_dependency_by_id("TDEP-001")
            self.assertEqual(found["Dependency ID"], "TDEP-001")

    def test_find_dependency_by_id_missing(self):
        sdm = _fresh_sdm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(sdm.find_dependency_by_id("TDEP-999"))

    def test_find_dependency_by_id_empty_id(self):
        sdm = _fresh_sdm()
        self.assertIsNone(sdm.find_dependency_by_id(""))


# ═══════════════════════════════════════════════════════════════
# Cycle detection
# ═══════════════════════════════════════════════════════════════

class TestCycleDetection(unittest.TestCase):
    def _adjacency_rows(self, edges, roadmap_template_id="RMT-IZH-ALM-STANDARD-002"):
        rows = []
        for i, (dependent, prereq) in enumerate(edges, start=1):
            rows.append(_dep_dict_from_row(_dep_row(
                dependency_id=f"TDEP-{i:03d}", roadmap_template_id=roadmap_template_id,
                template_stage_id=dependent, depends_on=prereq, status="active",
            )))
        return rows

    def test_detect_dependency_cycle_missing_args(self):
        sdm = _fresh_sdm()
        result = sdm.detect_dependency_cycle("", "TSTG-035", "TSTG-034")
        self.assertFalse(result["ok"])

    def test_detect_dependency_cycle_no_cycle(self):
        sdm = _fresh_sdm()
        with patch("business_core.sheets.read_business_sheet", return_value=[]):
            result = sdm.detect_dependency_cycle("RMT-X", "TSTG-035", "TSTG-034")
            self.assertTrue(result["ok"])
            self.assertFalse(result["would_create_cycle"])

    def test_detect_dependency_cycle_direct(self):
        """TSTG-034 already depends on TSTG-035 -> adding TSTG-035 depends_on
        TSTG-034 would create a direct 2-node cycle."""
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("TSTG-034", "TSTG-035")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.detect_dependency_cycle("RMT-IZH-ALM-STANDARD-002", "TSTG-035", "TSTG-034")
            self.assertTrue(result["ok"])
            self.assertTrue(result["would_create_cycle"])
            self.assertIn("TSTG-035", result["cycle_path"])

    def test_detect_dependency_cycle_indirect(self):
        """A depends_on B, B depends_on C -> adding C depends_on A closes
        an indirect 3-edge cycle."""
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("A", "B"), ("B", "C")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.detect_dependency_cycle("RMT-IZH-ALM-STANDARD-002", "C", "A")
            self.assertTrue(result["would_create_cycle"])
            self.assertGreater(len(result["cycle_path"]), 3)

    def test_detect_reachable_cycle_corrupted_direct(self):
        """Data already contains a direct cycle (e.g. manual Sheet edit
        bypassing create-time validation) -> gate-time bounded DFS finds
        it without any hypothetical edge."""
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("TSTG-034", "TSTG-035"), ("TSTG-035", "TSTG-034")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.detect_reachable_cycle_from_template_stage("RMT-IZH-ALM-STANDARD-002", "TSTG-034")
            self.assertTrue(result["ok"])
            self.assertTrue(result["cycle_found"])
            self.assertFalse(result["limit_exceeded"])

    def test_detect_reachable_cycle_corrupted_indirect(self):
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("A", "B"), ("B", "C"), ("C", "A")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.detect_reachable_cycle_from_template_stage("RMT-IZH-ALM-STANDARD-002", "A")
            self.assertTrue(result["cycle_found"])

    def test_detect_reachable_cycle_limit_exceeded(self):
        """A long corrupted chain longer than node_limit must report
        limit_exceeded, never a false cycle_found=False silently, and
        never an unbounded traversal."""
        sdm = _fresh_sdm()
        edges = [(f"N{i}", f"N{i+1}") for i in range(10)]
        rows = self._adjacency_rows(edges)
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.detect_reachable_cycle_from_template_stage(
                "RMT-IZH-ALM-STANDARD-002", "N0", node_limit=3,
            )
            self.assertTrue(result["limit_exceeded"])
            self.assertFalse(result["cycle_found"])

    def test_validate_dependency_graph_for_template_clean(self):
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("TSTG-035", "TSTG-034")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.validate_dependency_graph_for_template("RMT-IZH-ALM-STANDARD-002")
            self.assertTrue(result["ok"])
            self.assertFalse(result["has_cycle"])

    def test_validate_dependency_graph_for_template_cyclic(self):
        sdm = _fresh_sdm()
        rows = self._adjacency_rows([("A", "B"), ("B", "A")])
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            result = sdm.validate_dependency_graph_for_template("RMT-IZH-ALM-STANDARD-002")
            self.assertTrue(result["has_cycle"])


# ═══════════════════════════════════════════════════════════════
# create_template_stage_dependency
# ═══════════════════════════════════════════════════════════════

class TestCreateDependency(unittest.TestCase):
    def _patch_common(self, find_row_by_id_rows=None, existing_dep_row=None,
                       cycle_rows=(), sheet=None):
        find_row_by_id_rows = find_row_by_id_rows or {
            "TSTG-035": _template_stage_row("TSTG-035"),
            "TSTG-034": _template_stage_row("TSTG-034"),
        }
        sheet = sheet or _FakeSheet(_DEP_HEADERS, [existing_dep_row] if existing_dep_row else [])
        patches = [
            patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id_side_effect(find_row_by_id_rows)),
            patch("business_core.sheets.read_business_sheet", return_value=list(cycle_rows)),
            patch("business_core.sheets.get_business_sheet", return_value=sheet),
            patch("business_core.sheets.get_header_index_map", return_value={h: i for i, h in enumerate(_DEP_HEADERS)}),
            patch("business_core.sheets.append_business_row"),
            patch("business_core.sheets.row_from_header_map", side_effect=lambda headers, values: [values.get(h, "") for h in headers]),
            patch("business_core.sheets.generate_next_id", return_value="TDEP-002"),
        ]
        return patches, sheet

    def test_missing_ids_rejected(self):
        sdm = _fresh_sdm()
        result = sdm.create_template_stage_dependency("", "TSTG-034")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TEMPLATE_STAGE_NOT_FOUND")

    def test_unknown_dependency_type_rejected(self):
        sdm = _fresh_sdm()
        result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034", dependency_type="bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_DEPENDENCY_TYPE")

    def test_self_dependency_rejected(self):
        sdm = _fresh_sdm()
        result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-035")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SELF_DEPENDENCY_REJECTED")

    def test_missing_template_stage_rejected(self):
        sdm = _fresh_sdm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TEMPLATE_STAGE_NOT_FOUND")

    def test_cross_template_dependency_rejected(self):
        sdm = _fresh_sdm()
        rows = {
            "TSTG-035": _template_stage_row("TSTG-035", template_id="RMT-A"),
            "TSTG-034": _template_stage_row("TSTG-034", template_id="RMT-B"),
        }
        with patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id_side_effect(rows)):
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "CROSS_TEMPLATE_DEPENDENCY_REJECTED")

    def test_active_duplicate_idempotent_reuse(self):
        sdm = _fresh_sdm()
        existing = _dep_row(dependency_id="TDEP-001", template_stage_id="TSTG-035",
                             depends_on="TSTG-034", status="active")
        patches, sheet = self._patch_common(existing_dep_row=existing)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DEPENDENCY_ALREADY_EXISTS")
        self.assertTrue(result["reused"])
        self.assertFalse(result["created"])
        self.assertEqual(result["dependency_id"], "TDEP-001")
        self.assertEqual(sheet.updates, [])  # no write on active duplicate

    def test_inactive_duplicate_reactivated(self):
        sdm = _fresh_sdm()
        existing = _dep_row(dependency_id="TDEP-001", template_stage_id="TSTG-035",
                             depends_on="TSTG-034", status="inactive")
        patches, sheet = self._patch_common(existing_dep_row=existing)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034", notes="revived")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DEPENDENCY_REACTIVATED")
        self.assertTrue(result["reused"])
        self.assertTrue(result["reactivated"])
        self.assertFalse(result["created"])
        self.assertTrue(len(sheet.updates) > 0)  # Status/type/blocking/notes/updated_at written

    def test_direct_cycle_rejected(self):
        sdm = _fresh_sdm()
        cycle_rows = [_dep_dict_from_row(_dep_row(
            dependency_id="TDEP-777", template_stage_id="TSTG-034",
            depends_on="TSTG-035", status="active",
        ))]
        patches, sheet = self._patch_common(cycle_rows=cycle_rows)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "DIRECT_CYCLE_REJECTED")

    def test_indirect_cycle_rejected(self):
        sdm = _fresh_sdm()
        rows_by_id = {
            "A": _template_stage_row("A"), "B": _template_stage_row("B"), "C": _template_stage_row("C"),
        }
        cycle_rows = [
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-701", template_stage_id="A", depends_on="B", status="active")),
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-702", template_stage_id="B", depends_on="C", status="active")),
        ]
        patches, sheet = self._patch_common(find_row_by_id_rows=rows_by_id, cycle_rows=cycle_rows)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = sdm.create_template_stage_dependency("C", "A")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INDIRECT_CYCLE_REJECTED")

    def test_successful_create(self):
        sdm = _fresh_sdm()
        patches, sheet = self._patch_common()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = sdm.create_template_stage_dependency("TSTG-035", "TSTG-034", blocking=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "DEPENDENCY_CREATED")
        self.assertTrue(result["created"])
        self.assertEqual(result["dependency_id"], "TDEP-002")


# ═══════════════════════════════════════════════════════════════
# resolve_live_stage_dependencies
# ═══════════════════════════════════════════════════════════════

def _resolve_template_stage_ok(stage_id="STAGE-001", roadmap_id="RM-001",
                                roadmap_template_id="RMT-IZH-ALM-STANDARD-002",
                                template_stage_id="TSTG-035"):
    return {
        "ok": True, "code": "", "error": None,
        "stage": {"stage_id": stage_id, "roadmap_id": roadmap_id},
        "roadmap": {"roadmap_id": roadmap_id},
        "template_id": roadmap_template_id, "template_stage_id": template_stage_id,
        "template_stage_row": None,
    }


def _live_stage(stage_id="STAGE-000", order="1", status="pending", name="Prev Stage"):
    return {"stage_id": stage_id, "order": order, "status": status, "name": name, "roadmap_id": "RM-001"}


class TestResolveLiveStageDependencies(unittest.TestCase):
    def test_stage_resolution_failure_propagates(self):
        sdm = _fresh_sdm()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value={"ok": False, "code": "STAGE_NOT_FOUND", "error": "nope", "roadmap": None, "template_id": "", "template_stage_id": ""}):
            result = sdm.resolve_live_stage_dependencies("STAGE-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_no_dependencies(self):
        sdm = _fresh_sdm()
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolve_template_stage_ok()), \
             patch("business_core.sheets.read_business_sheet", return_value=[]):
            result = sdm.resolve_live_stage_dependencies("STAGE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "NO_STAGE_DEPENDENCIES")
        self.assertEqual(result["resolved"], ())

    def _resolve_with(self, dep_rows, template_stage_rows, live_stage_rows):
        sdm = _fresh_sdm()

        def _read_business_sheet(key):
            if key == "template_stage_dependencies":
                return dep_rows
            if key == "roadmap_template_stages":
                return template_stage_rows
            raise AssertionError(f"unexpected sheet key {key}")

        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolve_template_stage_ok()), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap", return_value=live_stage_rows), \
             patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet):
            return sdm.resolve_live_stage_dependencies("STAGE-001")

    def test_done_prerequisite_satisfied(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = [_live_stage(order="1", status="done")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["resolved"]), 1)
        self.assertTrue(result["resolved"][0]["satisfied"])

    def test_skipped_prerequisite_satisfied(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = [_live_stage(order="1", status="skipped")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertTrue(result["resolved"][0]["satisfied"])

    def test_pending_prerequisite_unsatisfied(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = [_live_stage(order="1", status="pending")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertFalse(result["resolved"][0]["satisfied"])

    def test_multiple_dependencies_all_satisfied(self):
        dep_rows = [
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-001", template_stage_id="TSTG-035", depends_on="TSTG-034")),
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-002", template_stage_id="TSTG-035", depends_on="TSTG-033")),
        ]
        template_rows = [_template_stage_row("TSTG-034", order="1"), _template_stage_row("TSTG-033", order="2")]
        live_rows = [_live_stage(stage_id="STAGE-A", order="1", status="done"),
                     _live_stage(stage_id="STAGE-B", order="2", status="skipped")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertEqual(len(result["resolved"]), 2)
        self.assertTrue(all(r["satisfied"] for r in result["resolved"]))

    def test_multiple_dependencies_one_unsatisfied(self):
        dep_rows = [
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-001", template_stage_id="TSTG-035", depends_on="TSTG-034")),
            _dep_dict_from_row(_dep_row(dependency_id="TDEP-002", template_stage_id="TSTG-035", depends_on="TSTG-033")),
        ]
        template_rows = [_template_stage_row("TSTG-034", order="1"), _template_stage_row("TSTG-033", order="2")]
        live_rows = [_live_stage(stage_id="STAGE-A", order="1", status="done"),
                     _live_stage(stage_id="STAGE-B", order="2", status="in_progress")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        satisfied_flags = sorted(r["satisfied"] for r in result["resolved"])
        self.assertEqual(satisfied_flags, [False, True])

    def test_non_blocking_dependency_flag_preserved(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034", blocking="false"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = [_live_stage(order="1", status="pending")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertFalse(result["resolved"][0]["blocking"])

    def test_missing_live_prerequisite_stage(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = []  # no live Stage has Order=1
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertEqual(result["resolved"], ())
        self.assertEqual(len(result["missing_live_stages"]), 1)

    def test_ambiguous_template_stage_mapping_is_configuration_error(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1"), _template_stage_row("TSTG-034", order="2")]
        live_rows = [_live_stage(order="1", status="done")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertEqual(result["resolved"], ())
        self.assertEqual(len(result["configuration_errors"]), 1)

    def test_ambiguous_live_stage_order_mapping_is_configuration_error(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-034"))]
        template_rows = [_template_stage_row("TSTG-034", order="1")]
        live_rows = [_live_stage(stage_id="STAGE-A", order="1", status="done"),
                     _live_stage(stage_id="STAGE-B", order="1", status="pending")]
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertEqual(result["resolved"], ())
        self.assertEqual(len(result["configuration_errors"]), 1)

    def test_prerequisite_not_found_in_template_stages(self):
        dep_rows = [_dep_dict_from_row(_dep_row(template_stage_id="TSTG-035", depends_on="TSTG-GONE"))]
        template_rows = []
        live_rows = []
        result = self._resolve_with(dep_rows, template_rows, live_rows)
        self.assertEqual(len(result["configuration_errors"]), 1)


# ═══════════════════════════════════════════════════════════════
# Architecture guard
# ═══════════════════════════════════════════════════════════════

class TestArchitectureGuards(unittest.TestCase):
    def test_stage_entity_relations_module_unaffected(self):
        """Dependencies Foundation must never import or extend
        stage_entity_relations.py's ENTITY_TYPE_DISPATCH — that module's
        own invariant (relation direction is always stage -> entity,
        never a generic graph) must remain unbent."""
        import business_core.stage_entity_relations as ser
        self.assertNotIn("template_stage", getattr(ser, "ENTITY_TYPE_DISPATCH", {}))
        self.assertNotIn("stage", getattr(ser, "ENTITY_TYPE_DISPATCH", {}))

    def test_dependencies_table_is_not_entity_relation_type(self):
        import business_core.sheets as sheets
        self.assertIn("template_stage_dependencies", sheets.BUSINESS_SHEET_NAMES)
        self.assertNotIn("template_stage_dependencies", getattr(
            __import__("business_core.stage_entity_relations", fromlist=["ENTITY_TYPE_DISPATCH"]),
            "ENTITY_TYPE_DISPATCH", {},
        ))


if __name__ == "__main__":
    unittest.main()
