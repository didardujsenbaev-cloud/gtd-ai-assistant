"""
Phase 11F: Fix Duplicate Stage IDs in Template Roadmap Creation.

Root cause (Phase 11E): create_stages_from_template_record() called
generate_next_id("roadmap_stages") once per loop iteration, but all rows
were written only once, after the loop, via batch_append_business_rows().
Since generate_next_id() only reflects already-PERSISTED sheet state,
every call within the same un-flushed loop saw the identical (pre-batch)
state and returned the identical ID.

Fix: business_core/sheets.py gains generate_next_ids(sheet_key, count),
which reads the sheet ONCE and returns `count` unique sequential IDs
computed locally — no repeated Sheets reads, no writes.
create_stages_from_template_record() now calls it once, before the loop,
instead of calling generate_next_id() inside the loop.

Covers (per Phase 11F spec):
A. Empty sheet → 8 template stages → STAGE-001..STAGE-008
B. Existing max (STAGE-001, STAGE-004, STAGE-010) → next batch of 3 →
   STAGE-011, STAGE-012, STAGE-013
C. Existing duplicates of STAGE-001 → new batch does not repeat STAGE-001
D. Legacy IDs (STAGE-001-01, STAGE-001-02), no canonical numeric ID →
   next starts at STAGE-001
E. Mixed canonical + legacy (STAGE-009, STAGE-001-01) → next STAGE-010
F. 999 boundary → STAGE-999 → next STAGE-1000
G. Batch uniqueness — all IDs within one batch are unique
H. Single stage template still works
I. No regression: Order/Status/Roadmap ID/template Stage ID+Name
   preserved; batch_append_business_rows called exactly once
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


def _fresh_sheets():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.sheets as s
    return s


def _fresh_template_manager():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.roadmap_template_manager as m
    return m


def _ws(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    ws.row_values.side_effect = lambda r: rows[r - 1] if 0 <= r - 1 < len(rows) else []
    return ws


HEADER_ROW = ["Stage ID", "Roadmap ID", "Order", "Name", "Status",
              "Due Date", "Completed At", "GTD Action ID",
              "Responsible", "Docs Required", "Docs Received", "Notes",
              "SOP IDs", "Checklist IDs", "Materials IDs",
              "Document Template IDs", "FAQ IDs"]


def _sheet_with_stage_ids(ids: list[str]):
    rows = [HEADER_ROW]
    for sid in ids:
        row = [""] * len(HEADER_ROW)
        row[0] = sid
        rows.append(row)
    return _ws(rows)


# ────────────────────────────────────────────────────────────
# generate_next_ids() — unit level
# ────────────────────────────────────────────────────────────

class TestGenerateNextIdsEmptySheet(unittest.TestCase):
    """A. Empty sheet — 8 requested IDs → STAGE-001..STAGE-008."""

    def test_a_empty_sheet_sequential_from_one(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids([])):
            ids = sheets.generate_next_ids("roadmap_stages", 8)
        self.assertEqual(ids, [f"STAGE-{n:03d}" for n in range(1, 9)])


class TestGenerateNextIdsExistingMax(unittest.TestCase):
    """B. Existing STAGE-001, STAGE-004, STAGE-010 → next 3 → 011,012,013."""

    def test_b_continues_from_existing_max(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(
                               ["STAGE-001", "STAGE-004", "STAGE-010"])):
            ids = sheets.generate_next_ids("roadmap_stages", 3)
        self.assertEqual(ids, ["STAGE-011", "STAGE-012", "STAGE-013"])


class TestGenerateNextIdsExistingDuplicates(unittest.TestCase):
    """C. Existing duplicate STAGE-001 rows → new batch does not repeat it."""

    def test_c_duplicates_do_not_cause_reissue(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(
                               ["STAGE-001"] * 8)):
            ids = sheets.generate_next_ids("roadmap_stages", 2)
        self.assertNotIn("STAGE-001", ids)
        self.assertEqual(ids, ["STAGE-002", "STAGE-003"])


class TestGenerateNextIdsLegacyIds(unittest.TestCase):
    """D. Legacy IDs only (STAGE-001-01, STAGE-001-02) → starts at STAGE-001."""

    def test_d_legacy_only_starts_at_one(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(
                               ["STAGE-001-01", "STAGE-001-02"])):
            ids = sheets.generate_next_ids("roadmap_stages", 2)
        self.assertEqual(ids, ["STAGE-001", "STAGE-002"])


class TestGenerateNextIdsMixedCanonicalAndLegacy(unittest.TestCase):
    """E. Mixed STAGE-009 (canonical) + STAGE-001-01 (legacy) → next STAGE-010."""

    def test_e_legacy_ignored_canonical_wins(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(
                               ["STAGE-009", "STAGE-001-01"])):
            ids = sheets.generate_next_ids("roadmap_stages", 1)
        self.assertEqual(ids, ["STAGE-010"])


class TestGenerateNextIdsBoundary(unittest.TestCase):
    """F. STAGE-999 → next is STAGE-1000 (no truncation, no reset)."""

    def test_f_999_to_1000(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(["STAGE-999"])):
            ids = sheets.generate_next_ids("roadmap_stages", 1)
        self.assertEqual(ids, ["STAGE-1000"])

    def test_f_1000_to_1001_still_grows(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(["STAGE-1000"])):
            ids = sheets.generate_next_ids("roadmap_stages", 1)
        self.assertEqual(ids, ["STAGE-1001"])


class TestGenerateNextIdsBatchUniqueness(unittest.TestCase):
    """G. All IDs within one batch are unique, regardless of batch size."""

    def test_g_uniqueness_various_sizes(self):
        sheets = _fresh_sheets()
        for count in (1, 2, 8, 50):
            with patch.object(sheets, "get_business_sheet",
                               return_value=_sheet_with_stage_ids([])):
                ids = sheets.generate_next_ids("roadmap_stages", count)
            self.assertEqual(len(ids), count)
            self.assertEqual(len(set(ids)), count)


class TestGenerateNextIdsSingle(unittest.TestCase):
    """H. count == 1 behaves like a single-stage template creation."""

    def test_h_single_id_matches_generate_next_id(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(["STAGE-003"])):
            single = sheets.generate_next_id("roadmap_stages")
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids(["STAGE-003"])):
            batch = sheets.generate_next_ids("roadmap_stages", 1)
        self.assertEqual(batch, [single])


class TestGenerateNextIdsZeroOrNegativeCount(unittest.TestCase):
    def test_zero_count_returns_empty_list(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids([])):
            ids = sheets.generate_next_ids("roadmap_stages", 0)
        self.assertEqual(ids, [])

    def test_negative_count_returns_empty_list(self):
        sheets = _fresh_sheets()
        with patch.object(sheets, "get_business_sheet",
                           return_value=_sheet_with_stage_ids([])):
            ids = sheets.generate_next_ids("roadmap_stages", -1)
        self.assertEqual(ids, [])


class TestGenerateNextIdsSheetReadOnce(unittest.TestCase):
    """generate_next_ids() must read the sheet exactly once per call,
    regardless of requested count — no repeated Sheets reads inside."""

    def test_single_read_for_large_batch(self):
        sheets = _fresh_sheets()
        sheet = _sheet_with_stage_ids([])
        with patch.object(sheets, "get_business_sheet", return_value=sheet) as mock_get:
            sheets.generate_next_ids("roadmap_stages", 20)
        mock_get.assert_called_once()
        sheet.get_all_values.assert_called_once()


# ────────────────────────────────────────────────────────────
# create_stages_from_template_record() — integration level
# ────────────────────────────────────────────────────────────

TEMPLATE_STAGES_8 = [
    {"stage_id": f"TSTG-{n:03d}", "template_id": "RMT-IZH-ALM-STANDARD-001",
     "order": str(o), "stage_name": f"Этап {n}", "description": "",
     "required_docs": "", "responsible": "", "estimated_days": "", "notes": ""}
    for n, o in zip(range(17, 25), [1, 8, 9, 10, 11, 12, 13, 14])
]


class TestCreateStagesNoDuplicateIds(unittest.TestCase):
    """I. Fixed behavior: 8 template stages → 8 unique Stage IDs, one
    batch_append_business_rows() call, Order/Status/Roadmap ID/template
    Stage ID+Name preserved unchanged."""

    def test_eight_stages_get_eight_unique_ids(self):
        m = _fresh_template_manager()
        batch_calls = []

        def capture(key, rows):
            batch_calls.append((key, rows))

        with patch.object(m, "find_template_stages", return_value=TEMPLATE_STAGES_8), \
             patch("business_core.sheets.get_business_sheet",
                   return_value=_sheet_with_stage_ids([])), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=capture), \
             patch("business_core.knowledge_manager.find_knowledge_by_template_stage",
                   return_value={}):
            result = m.create_stages_from_template_record("RM-001", "RMT-IZH-ALM-STANDARD-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 8)
        self.assertEqual(len(set(result["stage_ids"])), 8,
                          "все 8 Stage ID должны быть уникальны")
        self.assertEqual(result["stage_ids"],
                          [f"STAGE-{n:03d}" for n in range(1, 9)])

        # batch_append_business_rows вызван РОВНО один раз
        self.assertEqual(len(batch_calls), 1)
        _, rows = batch_calls[0]
        self.assertEqual(len(rows), 8)

        idx = {h: i for i, h in enumerate(HEADER_ROW)}
        expected_orders = ["1", "8", "9", "10", "11", "12", "13", "14"]
        for row, expected_order, ts in zip(rows, expected_orders, TEMPLATE_STAGES_8):
            self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
            self.assertEqual(row[idx["Status"]], "pending")
            self.assertEqual(row[idx["Order"]], expected_order)
            self.assertEqual(row[idx["Name"]], ts["stage_name"])

        # Все Stage ID в записанных строках тоже уникальны
        written_ids = [row[idx["Stage ID"]] for row in rows]
        self.assertEqual(len(set(written_ids)), 8)

    def test_single_stage_template_still_works(self):
        """H (integration): a 1-stage template still produces exactly one ID."""
        m = _fresh_template_manager()
        batch_calls = []

        with patch.object(m, "find_template_stages",
                           return_value=[TEMPLATE_STAGES_8[0]]), \
             patch("business_core.sheets.get_business_sheet",
                   return_value=_sheet_with_stage_ids([])), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: batch_calls.append(rows)), \
             patch("business_core.knowledge_manager.find_knowledge_by_template_stage",
                   return_value={}):
            result = m.create_stages_from_template_record("RM-001", "RMT-IZH-ALM-STANDARD-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 1)
        self.assertEqual(result["stage_ids"], ["STAGE-001"])
        self.assertEqual(len(batch_calls), 1)

    def test_continues_from_existing_stages_on_other_roadmaps(self):
        """Batch creation on top of a non-empty sheet continues sequentially,
        does not collide with previously-persisted Stage IDs."""
        m = _fresh_template_manager()
        batch_calls = []

        with patch.object(m, "find_template_stages",
                           return_value=TEMPLATE_STAGES_8[:3]), \
             patch("business_core.sheets.get_business_sheet",
                   return_value=_sheet_with_stage_ids(
                       ["STAGE-001", "STAGE-002", "STAGE-003"])), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: batch_calls.append(rows)), \
             patch("business_core.knowledge_manager.find_knowledge_by_template_stage",
                   return_value={}):
            result = m.create_stages_from_template_record("RM-002", "RMT-IZH-ALM-STANDARD-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stage_ids"], ["STAGE-004", "STAGE-005", "STAGE-006"])


if __name__ == "__main__":
    unittest.main()
