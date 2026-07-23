"""
Phase 18E: guarded synthetic-data cleanup utility — tests.

Covers business_core.synthetic_cleanup: plan_cleanup() (dry-run) and
cleanup_synthetic_records() (dry_run=True/False), against a mocked
sheets layer mirroring the real Phase 18D production shape (one real
roadmap RM-001/STAGE-001..008/REL-001..009, one synthetic roadmap
RM-002/STAGE-009..016/REL-010..018, plus the person/object rows).

Strictly against mocks — no live network calls, no relation/sheet rows
are ever written to production in this test file.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch, MagicMock


def _fresh_sc():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.synthetic_cleanup as sc
    return sc


# ────────────────────────────────────────────────────────────
# Fixture data mirroring the real Phase 18D production shape
# ────────────────────────────────────────────────────────────

def _people_rows(extra_marker=True):
    return [
        {"ID": "PRS-001", "ФИО": "Real Client", "Комментарий": ""},
        {"ID": "PRS-002", "ФИО": "TEST PHASE 18D",
         "Комментарий": "SYNTHETIC TEST — Phase 18D controlled smoke test. Safe to delete." if extra_marker else ""},
    ]


def _object_rows(extra_marker=True):
    return [
        {"OBJ ID": "OBJ-001", "Client ID": "PRS-001", "Roadmap ID": "RM-001", "Notes": ""},
        {"OBJ ID": "OBJ-002", "Client ID": "PRS-002", "Roadmap ID": "RM-002",
         "Notes": "SYNTHETIC TEST — Phase 18D controlled smoke test. Safe to delete." if extra_marker else ""},
    ]


def _roadmap_rows(extra_marker=True):
    return [
        {"Roadmap ID": "RM-001", "Object ID": "OBJ-001", "Client ID": "PRS-001",
         "Service ID": "SVC-IZH-001", "Notes": ""},
        {"Roadmap ID": "RM-002", "Object ID": "OBJ-002", "Client ID": "PRS-002",
         "Service ID": "SVC-IZH-001",
         "Notes": "SYNTHETIC TEST — Phase 18D controlled smoke test. Safe to delete." if extra_marker else ""},
    ]


def _stage_rows():
    real = [{"Stage ID": f"STAGE-{i:03d}", "Roadmap ID": "RM-001"} for i in range(1, 9)]
    synthetic = [{"Stage ID": f"STAGE-{i:03d}", "Roadmap ID": "RM-002"} for i in range(9, 17)]
    return real + synthetic


def _relation_rows():
    real = [
        {"Relation ID": f"REL-{i:03d}", "Template Stage ID": f"TSTG-{i:03d}", "Stage ID": ""}
        for i in range(1, 10)
    ]
    # Mirrors the real Phase 18D production mapping exactly: 9 instance
    # relations across only 6 of the 8 synthetic stages (STAGE-010/014
    # have no document relations, matching TSTG-018/022's blank mapping).
    synthetic_stage_map = {
        "REL-010": "STAGE-009", "REL-011": "STAGE-009", "REL-012": "STAGE-009",
        "REL-013": "STAGE-011", "REL-014": "STAGE-011",
        "REL-015": "STAGE-012",
        "REL-016": "STAGE-013",
        "REL-017": "STAGE-015",
        "REL-018": "STAGE-016",
    }
    synthetic = [
        {"Relation ID": rel_id, "Template Stage ID": "", "Stage ID": stage_id}
        for rel_id, stage_id in synthetic_stage_map.items()
    ]
    return real + synthetic


SYNTHETIC_ALLOWLIST = [
    "PRS-002", "OBJ-002", "RM-002",
    "STAGE-009", "STAGE-010", "STAGE-011", "STAGE-012",
    "STAGE-013", "STAGE-014", "STAGE-015", "STAGE-016",
    "REL-010", "REL-011", "REL-012", "REL-013", "REL-014",
    "REL-015", "REL-016", "REL-017", "REL-018",
]


def _patch_sheets(people=None, objects=None, roadmaps=None, stages=None, relations=None,
                  delete_capture=None):
    people = _people_rows() if people is None else people
    objects = _object_rows() if objects is None else objects
    roadmaps = _roadmap_rows() if roadmaps is None else roadmaps
    stages = _stage_rows() if stages is None else stages
    relations = _relation_rows() if relations is None else relations

    tables = {
        "people_registry": (people, "ID"),
        "object_registry": (objects, "OBJ ID"),
        "roadmaps": (roadmaps, "Roadmap ID"),
        "roadmap_stages": (stages, "Stage ID"),
        "stage_entity_relations": (relations, "Relation ID"),
    }

    def _read_business_sheet(sheet_key, *a, **kw):
        rows, _ = tables.get(sheet_key, ([], None))
        return rows

    def _find_row_by_id(sheet_key, record_id, *a, **kw):
        table = tables.get(sheet_key)
        if table is None:
            return None
        rows, key_field = table
        for i, row in enumerate(rows, start=2):
            if row.get(key_field, "") == record_id:
                return (i, row)
        return None

    mock_sheets: dict = {}

    def _get_business_sheet(sheet_key, *a, **kw):
        if sheet_key not in mock_sheets:
            ws = MagicMock()

            def _delete_rows(row_num, _sk=sheet_key):
                rows, key_field = tables[_sk]
                # simulate real Sheets bottom-up-safe deletion: remove the
                # (row_num - 2)-th data row (row 1 = header, row 2 = first data row)
                idx = row_num - 2
                if 0 <= idx < len(rows):
                    del rows[idx]
                if delete_capture is not None:
                    delete_capture.append((sheet_key, row_num))

            ws.delete_rows.side_effect = _delete_rows
            mock_sheets[sheet_key] = ws
        return mock_sheets[sheet_key]

    return [
        patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet),
        patch("business_core.sheets.find_row_by_id", side_effect=_find_row_by_id),
        patch("business_core.sheets.get_business_sheet", side_effect=_get_business_sheet),
    ], tables


import contextlib


class _PatchedCase(unittest.TestCase):
    def _sc(self, **kwargs):
        sc = _fresh_sc()
        patches, tables = _patch_sheets(**kwargs)
        stack = contextlib.ExitStack()
        for p in patches:
            stack.enter_context(p)
        self.addCleanup(stack.close)
        return sc, tables


class TestPlanCleanupDryRun(_PatchedCase):
    def test_dry_run_performs_zero_writes(self):
        sc, tables = self._sc()
        result = sc.cleanup_synthetic_records(SYNTHETIC_ALLOWLIST, dry_run=True)
        self.assertTrue(result.dry_run)
        # nothing removed from the mocked tables
        self.assertEqual(len(tables["roadmaps"][0]), 2)
        self.assertEqual(len(tables["object_registry"][0]), 2)
        self.assertEqual(len(tables["people_registry"][0]), 2)
        self.assertEqual(len(tables["roadmap_stages"][0]), 16)
        self.assertEqual(len(tables["stage_entity_relations"][0]), 18)
        self.assertEqual(result.deleted, ())

    def test_only_allowlisted_ids_included_in_plan(self):
        sc, _ = self._sc()
        result = sc.plan_cleanup(SYNTHETIC_ALLOWLIST)
        planned_ids = {rid for rid, _ in result.planned}
        self.assertTrue(planned_ids.issubset(set(SYNTHETIC_ALLOWLIST)))
        self.assertEqual(len(result.planned), 20)  # 1 person + 1 object + 1 roadmap + 8 stages + 9 relations

    def test_real_record_is_rejected(self):
        sc, _ = self._sc()
        result = sc.plan_cleanup(["RM-001"])
        self.assertEqual(len(result.planned), 0)
        self.assertEqual(result.blocked[0][0], "RM-001")
        self.assertIn("protected", result.blocked[0][1])

    def test_missing_synthetic_marker_blocks_cleanup(self):
        sc, _ = self._sc(roadmaps=_roadmap_rows(extra_marker=False))
        result = sc.plan_cleanup(["RM-002"])
        self.assertEqual(len(result.planned), 0)
        self.assertEqual(result.blocked[0][0], "RM-002")
        self.assertIn("marker", result.blocked[0][1])

    def test_inbound_reference_from_non_allowlisted_record_blocks_deletion(self):
        # A REAL (non-synthetic, non-allowlisted) object references OBJ-002's
        # would-be roadmap RM-002 -- simulate by adding an extra real object
        # row pointing at RM-002.
        objects = _object_rows() + [{"OBJ ID": "OBJ-999", "Client ID": "PRS-999", "Roadmap ID": "RM-002", "Notes": ""}]
        sc, _ = self._sc(objects=objects)
        result = sc.plan_cleanup(["RM-002"])
        self.assertEqual(len(result.planned), 0)
        self.assertEqual(result.blocked[0][0], "RM-002")
        self.assertIn("OBJ-999", result.blocked[0][1])

    def test_service_svc_izh_001_never_included(self):
        sc, _ = self._sc()
        result = sc.plan_cleanup(SYNTHETIC_ALLOWLIST + ["SVC-IZH-001"])
        planned_ids = {rid for rid, _ in result.planned}
        self.assertNotIn("SVC-IZH-001", planned_ids)
        blocked_ids = {rid for rid, _ in result.blocked}
        self.assertIn("SVC-IZH-001", blocked_ids)

    def test_protected_ids_cannot_be_deleted(self):
        sc, _ = self._sc()
        protected_attempt = ["RM-001"] + [f"STAGE-{i:03d}" for i in range(1, 9)] + [f"REL-{i:03d}" for i in range(1, 10)]
        result = sc.plan_cleanup(protected_attempt)
        self.assertEqual(len(result.planned), 0)
        blocked_ids = {rid for rid, _ in result.blocked}
        self.assertEqual(blocked_ids, set(protected_attempt))

    def test_missing_already_deleted_record_handled_idempotently(self):
        people = [{"ID": "PRS-001", "ФИО": "Real", "Комментарий": ""}]  # PRS-002 already gone
        sc, _ = self._sc(people=people)
        result = sc.plan_cleanup(["PRS-002"])
        self.assertEqual(len(result.planned), 0)
        self.assertEqual(result.skipped[0][0], "PRS-002")
        self.assertIn("already absent", result.skipped[0][1])

    def test_deterministic_structured_output(self):
        sc, _ = self._sc()
        r1 = sc.plan_cleanup(SYNTHETIC_ALLOWLIST)
        r2 = sc.plan_cleanup(SYNTHETIC_ALLOWLIST)
        self.assertEqual(r1.planned, r2.planned)
        self.assertEqual(r1.blocked, r2.blocked)
        self.assertEqual(r1.skipped, r2.skipped)


class TestLiveDeletionOrder(_PatchedCase):
    def test_rows_deleted_bottom_up_within_same_sheet(self):
        captured = []
        sc, tables = self._sc(delete_capture=captured)
        sc.cleanup_synthetic_records(SYNTHETIC_ALLOWLIST, dry_run=False)
        stage_deletes = [row for sheet, row in captured if sheet == "roadmap_stages"]
        self.assertEqual(stage_deletes, sorted(stage_deletes, reverse=True))
        relation_deletes = [row for sheet, row in captured if sheet == "stage_entity_relations"]
        self.assertEqual(relation_deletes, sorted(relation_deletes, reverse=True))

    def test_row_indexes_re_resolved_immediately_before_deletion(self):
        """Even if the plan was computed earlier, execution must re-read
        current row numbers fresh -- not reuse stale ones from planning."""
        sc, tables = self._sc()
        plan = sc.plan_cleanup(SYNTHETIC_ALLOWLIST)
        # Mutate the live table AFTER planning, shifting every row up by one,
        # simulating an intervening deletion elsewhere.
        tables["roadmap_stages"][0].insert(0, {"Stage ID": "STAGE-000", "Roadmap ID": "RM-000"})
        result = sc.cleanup_synthetic_records(SYNTHETIC_ALLOWLIST, dry_run=False)
        self.assertTrue(result.ok)
        for sid in ["STAGE-009", "STAGE-010", "STAGE-011", "STAGE-012",
                    "STAGE-013", "STAGE-014", "STAGE-015", "STAGE-016"]:
            self.assertIn(sid, result.deleted)

    def test_shifted_rows_do_not_cause_wrong_record_deletion(self):
        sc, tables = self._sc()
        tables["roadmap_stages"][0].insert(0, {"Stage ID": "STAGE-000", "Roadmap ID": "RM-000"})
        sc.cleanup_synthetic_records(SYNTHETIC_ALLOWLIST, dry_run=False)
        remaining_ids = {r["Stage ID"] for r in tables["roadmap_stages"][0]}
        # the unrelated inserted row and all 8 real RM-001 stages must survive
        self.assertIn("STAGE-000", remaining_ids)
        for i in range(1, 9):
            self.assertIn(f"STAGE-{i:03d}", remaining_ids)
        for i in range(9, 17):
            self.assertNotIn(f"STAGE-{i:03d}", remaining_ids)

    def test_partial_failure_reported_accurately(self):
        sc, tables = self._sc()

        real_get_sheet = sc._sheet_for_id  # not used, just for clarity

        call_count = {"n": 0}
        orig_read = tables["object_registry"]

        def _boom_get_business_sheet(sheet_key, *a, **kw):
            if sheet_key == "object_registry":
                raise RuntimeError("simulated 429 quota exceeded")
            ws = MagicMock()
            def _delete_rows(row_num, _sk=sheet_key):
                rows, key_field = tables[_sk]
                idx = row_num - 2
                if 0 <= idx < len(rows):
                    del rows[idx]
            ws.delete_rows.side_effect = _delete_rows
            return ws

        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_get_business_sheet):
            result = sc.cleanup_synthetic_records(SYNTHETIC_ALLOWLIST, dry_run=False)

        self.assertFalse(result.ok)
        # relations, stages, and the roadmap itself (all processed BEFORE
        # object_registry in the required deletion order) should have
        # succeeded already
        self.assertIn("REL-010", result.deleted)
        self.assertIn("STAGE-009", result.deleted)
        self.assertIn("RM-002", result.deleted)
        self.assertTrue(any("simulated 429" in w for w in result.warnings))
        # object/person (object_registry raises; people_registry never reached)
        self.assertNotIn("OBJ-002", result.deleted)
        self.assertNotIn("PRS-002", result.deleted)


class TestDriveDisabled(unittest.TestCase):
    def test_module_has_no_drive_calls(self):
        import inspect
        sc = _fresh_sc()
        source = inspect.getsource(sc)
        self.assertNotIn("get_drive_service", source)
        self.assertNotIn("trash_file", source)
        self.assertNotIn("delete_file", source)


class TestIsolationFromRuntime(unittest.TestCase):
    def test_not_imported_by_telegram_handlers(self):
        with open("business_core/telegram_handlers.py", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("synthetic_cleanup", source)

    def test_not_imported_by_telegram_bot(self):
        with open("telegram_bot.py", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("synthetic_cleanup", source)


if __name__ == "__main__":
    unittest.main()
