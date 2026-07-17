"""
Tests for Phase 9E.2 — автоматическое завершение Roadmap:
should_complete_roadmap() (чистая функция) и maybe_complete_roadmap()
(Sheets-backed, пишет только Status, только active -> completed).
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


def _fresh(mod_name: str):
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module(mod_name)


def _fresh_rm():
    return _fresh("business_core.roadmap_manager")


def _stage(status: str) -> dict:
    return {"stage_id": "STAGE-X", "roadmap_id": "RM-001", "order": "1",
            "name": "x", "status": status, "due_date": "", "notes": ""}


ROADMAPS_HEADERS = [
    "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
    "Client Name", "GTD Project ID", "Responsible", "Status",
    "Created", "Expected", "Progress %",
    "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
    "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
    "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
    "Stage 10 Status", "Notes", "Last Updated",
    "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
]


def _roadmaps_row(roadmap_id="RM-001", status="active", progress="100"):
    row = [""] * len(ROADMAPS_HEADERS)
    idx = {h: i for i, h in enumerate(ROADMAPS_HEADERS)}
    row[idx["Roadmap ID"]] = roadmap_id
    row[idx["Status"]] = status
    row[idx["Progress %"]] = progress
    return row


def _make_roadmaps_sheet(row, row_num=2, headers=None):
    headers = headers if headers is not None else ROADMAPS_HEADERS
    sheet = MagicMock()
    cell = MagicMock()
    cell.row = row_num
    sheet.find.return_value = cell
    sheet.row_values.side_effect = lambda r: headers if r == 1 else row
    return sheet


# ────────────────────────────────────────────────────────────
# should_complete_roadmap — чистая функция
# ────────────────────────────────────────────────────────────

class TestShouldCompleteRoadmap(unittest.TestCase):

    def test_empty_stages_returns_false(self):
        rm = _fresh_rm()
        self.assertFalse(rm.should_complete_roadmap([], 100))

    def test_all_done_progress_100_returns_true(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("done"), _stage("done")]
        self.assertTrue(rm.should_complete_roadmap(stages, 100))

    def test_done_plus_skipped_progress_100_returns_true(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("skipped"), _stage("done")]
        self.assertTrue(rm.should_complete_roadmap(stages, 100))

    def test_all_skipped_returns_true(self):
        rm = _fresh_rm()
        stages = [_stage("skipped"), _stage("skipped")]
        self.assertTrue(rm.should_complete_roadmap(stages, 100))

    def test_one_pending_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("done"), _stage("pending")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_one_in_progress_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("in_progress")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_one_blocked_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("blocked")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_legacy_not_started_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("not_started")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_legacy_waiting_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("waiting")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_stage_status_completed_returns_false(self):
        """'completed' как статус ЭТАПА (не roadmap) не входит в DONE_SET."""
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("completed")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_empty_status_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_unknown_status_returns_false(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("bogus_xyz")]
        self.assertFalse(rm.should_complete_roadmap(stages, 100))

    def test_progress_99_with_all_done_returns_false(self):
        """Даже если по факту все этапы done, но переданный progress_pct
        не 100 — should_complete_roadmap доверяет явно переданному значению,
        не пересчитывает его сама."""
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("done")]
        self.assertFalse(rm.should_complete_roadmap(stages, 99))

    def test_progress_100_with_all_done_returns_true(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("done")]
        self.assertTrue(rm.should_complete_roadmap(stages, 100))

    def test_does_not_call_sheets(self):
        rm = _fresh_rm()
        with patch("business_core.sheets.get_business_sheet") as mock_get:
            rm.should_complete_roadmap([_stage("done")], 100)
            mock_get.assert_not_called()


# ────────────────────────────────────────────────────────────
# maybe_complete_roadmap — Sheets-backed
# ────────────────────────────────────────────────────────────

class TestMaybeCompleteRoadmap(unittest.TestCase):

    def test_active_all_completed_transitions_to_completed(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))
        stages = [_stage("done"), _stage("skipped")]

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=stages, progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["old_status"], "active")
        self.assertEqual(result["new_status"], "completed")
        sheet.update_cell.assert_called_once_with(2, ROADMAPS_HEADERS.index("Status") + 1, "completed")

    def test_already_completed_is_idempotent_no_write(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="completed"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "completed")
        self.assertEqual(result["new_status"], "completed")
        sheet.update_cell.assert_not_called()

    def test_active_not_all_completed_no_write(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))
        stages = [_stage("done"), _stage("pending")]

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=stages, progress_pct=50)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "active")
        self.assertEqual(result["new_status"], "active")
        sheet.update_cell.assert_not_called()

    def test_roadmap_without_stages_no_write(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active", progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[], progress_pct=0)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        sheet.update_cell.assert_not_called()

    def test_roadmap_not_found_returns_clear_error(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.find.return_value = None

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-UNKNOWN")

        self.assertFalse(result["ok"])
        self.assertIn("RM-UNKNOWN", result["error"])
        sheet.update_cell.assert_not_called()

    def test_empty_roadmap_id_returns_error(self):
        rm = _fresh_rm()
        result = rm.maybe_complete_roadmap("")
        self.assertFalse(result["ok"])

    def test_other_status_draft_not_changed(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="draft"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "draft")
        self.assertEqual(result["new_status"], "draft")
        sheet.update_cell.assert_not_called()

    def test_other_status_cancelled_not_changed(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="cancelled"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "cancelled")
        sheet.update_cell.assert_not_called()

    def test_other_status_paused_not_changed(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="paused"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["old_status"], "paused")
        sheet.update_cell.assert_not_called()

    def test_never_reopens_completed_even_if_stages_regress(self):
        """completed никогда не возвращается в active, даже если stages
        внезапно содержат pending (напр. этап откатили назад)."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="completed"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("pending")], progress_pct=0)

        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["new_status"], "completed")
        sheet.update_cell.assert_not_called()

    def test_writes_only_status_column(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))
        stages = [_stage("done")]

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.maybe_complete_roadmap("RM-001", stages=stages, progress_pct=100)

        self.assertEqual(sheet.update_cell.call_count, 1)
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(col, ROADMAPS_HEADERS.index("Status") + 1)
        self.assertEqual(value, "completed")

    def test_does_not_touch_progress_column(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active", progress="100"))
        stages = [_stage("done")]

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.maybe_complete_roadmap("RM-001", stages=stages, progress_pct=100)

        written_cols = [c.args[1] for c in sheet.update_cell.call_args_list]
        self.assertNotIn(ROADMAPS_HEADERS.index("Progress %") + 1, written_cols)

    def test_does_not_write_to_roadmap_stages_sheet(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))
        calls = []

        def fake_get_business_sheet(key):
            calls.append(key)
            if key == "roadmaps":
                return sheet
            raise AssertionError(f"maybe_complete_roadmap не должен трогать лист '{key}'")

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["roadmaps"])

    def test_only_target_row_written(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"), row_num=17)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        for call in sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 17)

    def test_find_called_with_correct_roadmap_id(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.maybe_complete_roadmap("RM-042", stages=[_stage("done")], progress_pct=100)

        sheet.find.assert_called_once_with("RM-042", in_column=1)

    def test_independent_of_header_order(self):
        rm = _fresh_rm()
        shuffled = ["Progress %", "Roadmap ID", "Status", "Business ID"]
        row = ["100", "RM-001", "active", "BIZ-001"]
        sheet = _make_roadmaps_sheet(row, headers=shuffled)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = rm.maybe_complete_roadmap("RM-001", stages=[_stage("done")], progress_pct=100)

        self.assertTrue(result["changed"])
        sheet.update_cell.assert_called_once_with(2, shuffled.index("Status") + 1, "completed")

    def test_reads_stages_and_progress_itself_when_not_provided(self):
        """Если stages/progress_pct не переданы — функция сама их считает."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(status="active"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap",
                          return_value=[{"status": "done"}, {"status": "skipped"}]):
            result = rm.maybe_complete_roadmap("RM-001")

        self.assertTrue(result["changed"])
        self.assertEqual(result["new_status"], "completed")


# ────────────────────────────────────────────────────────────
# Другие roadmap не затрагиваются
# ────────────────────────────────────────────────────────────

class TestOtherRoadmapsUnaffected(unittest.TestCase):

    def test_completing_one_roadmap_does_not_touch_others(self):
        """sheet.find всегда находит нужную строку по ID — здесь
        подтверждаем единственный update_cell идёт в неё же."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(roadmap_id="RM-005", status="active"), row_num=9)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rm.maybe_complete_roadmap("RM-005", stages=[_stage("done")], progress_pct=100)

        self.assertEqual(sheet.update_cell.call_count, 1)
        self.assertEqual(sheet.update_cell.call_args[0][0], 9)


# ────────────────────────────────────────────────────────────
# GTD Core / .env не затронуты
# ────────────────────────────────────────────────────────────

class TestGTDAndEnvUntouched(unittest.TestCase):

    def _check_no_gtd_imports(self, path: Path):
        if not path.exists():
            return
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN,
                                     f"{path.name} импортирует {a.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN,
                                 f"{path.name} импортирует {node.module!r}")

    def test_roadmap_manager_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "roadmap_manager.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_rm()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
