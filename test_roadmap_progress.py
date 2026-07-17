"""
Tests for Phase 9C — Progress % пересчёт: calculate_progress() (чистая
функция) и recalculate_roadmap_progress() (Sheets-backed запись).

Согласованные решения:
- DONE_SET = {"done", "skipped"};
- всё остальное (pending, in_progress, blocked, legacy-значения,
  пустые, неизвестные строки) — не завершено;
- округление: round-half-up, 1/8 -> 13 (не 12, как дал бы Python round()
  из-за banker's rounding);
- total == 0 -> 0;
- recalculate_roadmap_progress НЕ меняет Status roadmap, НЕ меняет
  строки ROADMAP_STAGES, не вызывается автоматически из /updatestage.
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
    return {"stage_id": "STAGE-X", "roadmap_id": "RM-X", "order": "1",
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


def _roadmaps_row(roadmap_id="RM-001", progress="0", status="active"):
    row = [""] * len(ROADMAPS_HEADERS)
    idx = {h: i for i, h in enumerate(ROADMAPS_HEADERS)}
    row[idx["Roadmap ID"]] = roadmap_id
    row[idx["Progress %"]] = progress
    row[idx["Status"]] = status
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
# calculate_progress — чистая функция
# ────────────────────────────────────────────────────────────

class TestCalculateProgress(unittest.TestCase):

    def test_no_stages_returns_zero(self):
        rm = _fresh_rm()
        self.assertEqual(rm.calculate_progress([]), 0)

    def test_all_pending_returns_zero(self):
        rm = _fresh_rm()
        stages = [_stage("pending") for _ in range(4)]
        self.assertEqual(rm.calculate_progress(stages), 0)

    def test_all_done_returns_100(self):
        rm = _fresh_rm()
        stages = [_stage("done") for _ in range(5)]
        self.assertEqual(rm.calculate_progress(stages), 100)

    def test_one_of_three_done(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("pending"), _stage("pending")]
        self.assertEqual(rm.calculate_progress(stages), 33)

    def test_two_of_three_done(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("done"), _stage("pending")]
        self.assertEqual(rm.calculate_progress(stages), 67)

    def test_seven_of_ten_done(self):
        rm = _fresh_rm()
        stages = [_stage("done")] * 7 + [_stage("pending")] * 3
        self.assertEqual(rm.calculate_progress(stages), 70)

    def test_one_of_eight_done_round_half_up(self):
        """1/8 = 12.5% -> round-half-up даёт 13, не 12 (banker's rounding Python round() дал бы 12)."""
        rm = _fresh_rm()
        stages = [_stage("done")] + [_stage("pending")] * 7
        self.assertEqual(rm.calculate_progress(stages), 13)

    def test_mixed_done_and_skipped_both_count(self):
        rm = _fresh_rm()
        stages = [_stage("done"), _stage("skipped"), _stage("pending"), _stage("pending")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_all_skipped_returns_100(self):
        rm = _fresh_rm()
        stages = [_stage("skipped") for _ in range(3)]
        self.assertEqual(rm.calculate_progress(stages), 100)

    def test_in_progress_and_blocked_not_counted(self):
        rm = _fresh_rm()
        stages = [_stage("in_progress"), _stage("blocked"), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 33)

    def test_legacy_not_started_not_counted(self):
        rm = _fresh_rm()
        stages = [_stage("not_started"), _stage("not_started"), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 33)

    def test_legacy_waiting_not_counted(self):
        rm = _fresh_rm()
        stages = [_stage("waiting"), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_legacy_completed_string_not_counted(self):
        """'completed' — статус Roadmap, не Stage; как значение Stage.status не признаётся завершённым."""
        rm = _fresh_rm()
        stages = [_stage("completed"), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_empty_status_not_counted(self):
        rm = _fresh_rm()
        stages = [_stage(""), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_unknown_status_not_counted_no_crash(self):
        rm = _fresh_rm()
        stages = [_stage("bogus_xyz"), _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_missing_status_key_treated_as_not_done(self):
        rm = _fresh_rm()
        stages = [{"stage_id": "S1"}, _stage("done")]
        self.assertEqual(rm.calculate_progress(stages), 50)

    def test_does_not_call_sheets(self):
        """Чистая функция — не должна дергать get_business_sheet вовсе."""
        rm = _fresh_rm()
        with patch("business_core.sheets.get_business_sheet") as mock_get:
            rm.calculate_progress([_stage("done"), _stage("pending")])
            mock_get.assert_not_called()


# ────────────────────────────────────────────────────────────
# recalculate_roadmap_progress — Sheets-backed запись
# ────────────────────────────────────────────────────────────

class TestRecalculateRoadmapProgress(unittest.TestCase):

    def test_writes_correct_percentage(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap",
                          return_value=[{"status": "done"}, {"status": "pending"}]):
            result = rm.recalculate_roadmap_progress("RM-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["new_progress"], 50)
        self.assertEqual(result["done_count"], 1)
        self.assertEqual(result["total_count"], 2)
        sheet.update_cell.assert_called_once_with(2, ROADMAPS_HEADERS.index("Progress %") + 1, "50")

    def test_writes_only_progress_column(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap",
                          return_value=[{"status": "done"}, {"status": "done"}]):
            rm.recalculate_roadmap_progress("RM-001")

        self.assertEqual(sheet.update_cell.call_count, 1)
        row_num, col, value = sheet.update_cell.call_args[0]
        self.assertEqual(row_num, 2)
        self.assertEqual(col, ROADMAPS_HEADERS.index("Progress %") + 1)
        self.assertEqual(value, "100")

    def test_does_not_touch_status_column(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0", status="active"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            rm.recalculate_roadmap_progress("RM-001")

        written_cols = [call.args[1] for call in sheet.update_cell.call_args_list]
        self.assertNotIn(ROADMAPS_HEADERS.index("Status") + 1, written_cols)

    def test_does_not_touch_other_columns_at_all(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            rm.recalculate_roadmap_progress("RM-001")

        written_cols = {call.args[1] for call in sheet.update_cell.call_args_list}
        protected = {
            ROADMAPS_HEADERS.index(h) + 1 for h in ROADMAPS_HEADERS if h != "Progress %"
        }
        self.assertEqual(written_cols & protected, set())

    def test_does_not_write_to_roadmap_stages_sheet(self):
        """recalculate_roadmap_progress не должен трогать ROADMAP_STAGES вовсе."""
        rm = _fresh_rm()
        roadmaps_sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))
        calls = []

        def fake_get_business_sheet(key):
            calls.append(key)
            if key == "roadmaps":
                return roadmaps_sheet
            raise AssertionError(f"recalculate_roadmap_progress не должен трогать лист '{key}'")

        stages_sheet = MagicMock()
        stages_sheet.get_all_values.return_value = [
            ["Stage ID", "Roadmap ID", "Order", "Name", "Status", "Due Date", "Notes"],
            ["STAGE-1", "RM-001", "1", "x", "done", "", ""],
        ]

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet):
            # get_stages_for_roadmap само лезет в sheets — используем реальную
            # реализацию, но она пойдёт по ключу 'roadmap_stages', который мы
            # тоже обслуживаем через fake_get_business_sheet
            def get_business_sheet_with_stages(key):
                calls.append(key)
                if key == "roadmaps":
                    return roadmaps_sheet
                if key == "roadmap_stages":
                    return stages_sheet
                raise AssertionError(f"неожиданный лист '{key}'")

            with patch("business_core.sheets.get_business_sheet",
                       side_effect=get_business_sheet_with_stages):
                result = rm.recalculate_roadmap_progress("RM-001")

        self.assertTrue(result["ok"])
        self.assertIn("roadmaps", calls)
        self.assertIn("roadmap_stages", calls)  # чтение этапов — ожидаемо
        # но никакой WRITE-метод на stages_sheet не вызывался
        stages_sheet.update_cell.assert_not_called()
        stages_sheet.update.assert_not_called()
        stages_sheet.append_row.assert_not_called()

    def test_roadmap_without_stages_writes_zero(self):
        """Живой пример: RM-002/RM-006 сейчас без этапов — должен писать 0, не падать."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[]):
            result = rm.recalculate_roadmap_progress("RM-002")

        self.assertTrue(result["ok"])
        self.assertEqual(result["new_progress"], 0)
        sheet.update_cell.assert_called_once_with(2, ROADMAPS_HEADERS.index("Progress %") + 1, "0")

    def test_unknown_roadmap_id_returns_error_no_write(self):
        rm = _fresh_rm()
        sheet = MagicMock()
        sheet.find.return_value = None

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[]):
            result = rm.recalculate_roadmap_progress("RM-UNKNOWN")

        self.assertFalse(result["ok"])
        self.assertIn("RM-UNKNOWN", result["error"])
        sheet.update_cell.assert_not_called()

    def test_empty_roadmap_id_returns_error(self):
        rm = _fresh_rm()
        result = rm.recalculate_roadmap_progress("")
        self.assertFalse(result["ok"])

    def test_independent_of_header_order(self):
        """Порядок заголовков ROADMAPS может отличаться — запись всё равно в правильную колонку."""
        rm = _fresh_rm()
        shuffled = ["Progress %", "Roadmap ID", "Status", "Business ID"]
        row = ["0", "RM-001", "active", "BIZ-001"]
        sheet = _make_roadmaps_sheet(row, headers=shuffled)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            result = rm.recalculate_roadmap_progress("RM-001")

        self.assertTrue(result["ok"])
        sheet.update_cell.assert_called_once_with(2, shuffled.index("Progress %") + 1, "100")

    def test_missing_progress_column_returns_clear_error(self):
        rm = _fresh_rm()
        headers_without_progress = ["Roadmap ID", "Status"]
        row = ["RM-001", "active"]
        sheet = _make_roadmaps_sheet(row, headers=headers_without_progress)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            result = rm.recalculate_roadmap_progress("RM-001")

        self.assertFalse(result["ok"])
        self.assertIn("Progress %", result["error"])
        sheet.update_cell.assert_not_called()


# ────────────────────────────────────────────────────────────
# Идемпотентность
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_repeated_call_same_state_gives_same_percentage(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="50"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap",
                          return_value=[{"status": "done"}, {"status": "pending"}]):
            first = rm.recalculate_roadmap_progress("RM-001")
            second = rm.recalculate_roadmap_progress("RM-001")

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(first["new_progress"], second["new_progress"])

    def test_repeated_call_reports_changed_false_when_value_already_correct(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="50"))  # уже 50

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap",
                          return_value=[{"status": "done"}, {"status": "pending"}]):
            result = rm.recalculate_roadmap_progress("RM-001")

        self.assertFalse(result["changed"])
        self.assertEqual(result["old_progress"], "50")
        self.assertEqual(result["new_progress"], 50)

    def test_reports_changed_true_when_value_differs(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            result = rm.recalculate_roadmap_progress("RM-001")

        self.assertTrue(result["changed"])
        self.assertEqual(result["old_progress"], "0")
        self.assertEqual(result["new_progress"], 100)


# ────────────────────────────────────────────────────────────
# Другие roadmap не затрагиваются
# ────────────────────────────────────────────────────────────

class TestOtherRoadmapsUnaffected(unittest.TestCase):

    def test_only_target_row_written(self):
        """sheet.find всегда возвращает нужную ячейку по roadmap_id — проверяем,
        что update_cell идёт строго в найденный row_num, а не в произвольную строку."""
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"), row_num=17)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            rm.recalculate_roadmap_progress("RM-001")

        for call in sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 17)

    def test_find_called_with_correct_roadmap_id(self):
        rm = _fresh_rm()
        sheet = _make_roadmaps_sheet(_roadmaps_row(progress="0"))

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch.object(rm, "get_stages_for_roadmap", return_value=[{"status": "done"}]):
            rm.recalculate_roadmap_progress("RM-042")

        sheet.find.assert_called_once_with("RM-042", in_column=1)


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

    def test_updatestage_does_not_call_recalculate(self):
        """Phase 9C/9D: recalculate_roadmap_progress НЕ должен вызываться
        автоматически из /updatestage — только вручную через /recalcprogress
        (Phase 9D), которая явно вызывает его сама и тестируется отдельно
        в test_recalcprogress.py."""
        import re
        th_path = WORKSPACE / "business_core" / "telegram_handlers.py"
        src = th_path.read_text(encoding="utf-8")
        match = re.search(r"async def updatestage_cmd.*?(?=\nasync def |\Z)", src, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertNotIn("recalculate_roadmap_progress", match.group(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
