"""
Tests for migrate_roadmap_stages_headers.py (Phase 9A — safe schema
alignment for ROADMAP_STAGES, a prerequisite for Stage Management).

Context: create_stages_from_template_record() writes 5 knowledge-binding
fields (SOP IDs, Checklist IDs, Materials IDs, Document Template IDs,
FAQ IDs) into columns 13-17 positionally. The live sheet's header row only
has 12 real headers. Unlike the ROADMAPS bug (RM-027), no column here is
mislabeled — the tail columns are simply blank. This migration labels them
only after confirming their actual content against the ID-prefix registry
(_ID_PREFIXES in business_core/sheets.py: SOP-, CHK-, MAT-, DOC-, FAQ-),
and infers unlabeled/dataless columns (Materials IDs, FAQ IDs) strictly by
their fixed position in the single code path that writes them.
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
        if "business_core" in k or k == "migrate_roadmap_stages_headers":
            del sys.modules[k]
    import importlib
    return importlib.import_module(mod_name)


def _fresh_migrate():
    return _fresh("migrate_roadmap_stages_headers")


# Живая раскладка ДО миграции (воспроизводит прод: 12 подписанных
# заголовков + 4 пустых, реальный col_count листа = 17).
LIVE_HEADERS_BEFORE = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "", "", "", "",
]

FULL_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
]


def _live_data_rows():
    """Повторяет наблюдаемое распределение данных на проде:
    233 строки в реальности, здесь — репрезентативная выборка."""

    def row(stage_id, rm_id, order, name, status, sop="", chk="", mat="", doc="", faq=""):
        base = [stage_id, rm_id, str(order), name, status,
                "", "", "", "Дидар", "Паспорт", "", "Notes text"]
        return base + [sop, chk, mat, doc, faq]

    return [
        row("STAGE-001-01", "RM-001", 1, "Диагностика", "pending", "SOP-001", "CHK-001", "", "DOC-001"),
        row("STAGE-001-02", "RM-001", 2, "Сбор документов", "pending"),
        row("STAGE-002-01", "RM-002", 1, "Диагностика", "not_started"),
    ]


# ────────────────────────────────────────────────────────────
# classify_column_data
# ────────────────────────────────────────────────────────────

class TestClassifyColumnData(unittest.TestCase):

    def test_sop_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["SOP-001", "SOP-002"]), "SOP IDs")

    def test_checklist_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["CHK-001"]), "Checklist IDs")

    def test_materials_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["MAT-001", "MAT-002"]), "Materials IDs")

    def test_document_template_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["DOC-001"]), "Document Template IDs")

    def test_faq_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["FAQ-001"]), "FAQ IDs")

    def test_comma_separated_list_all_same_prefix(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["SOP-001,SOP-002", "SOP-003"]), "SOP IDs")

    def test_mixed_prefixes_in_one_value_returns_none(self):
        """Список из разных префиксов в одной ячейке — не наше поле, безопасный отказ."""
        m = _fresh_migrate()
        self.assertIsNone(m.classify_column_data(["SOP-001,CHK-001"]))

    def test_empty_returns_none(self):
        m = _fresh_migrate()
        self.assertIsNone(m.classify_column_data(["", "  "]))

    def test_unrelated_values_return_none_not_guessed(self):
        m = _fresh_migrate()
        self.assertIsNone(m.classify_column_data(["Дидар", "Иван"]))
        self.assertIsNone(m.classify_column_data(["pending", "not_started"]))


# ────────────────────────────────────────────────────────────
# analyze_roadmap_stages_headers
# ────────────────────────────────────────────────────────────

class TestAnalyzeRoadmapStagesHeaders(unittest.TestCase):

    def test_reproduces_live_state_and_proposes_correct_labels(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        self.assertEqual(plan["rename"], [], "на этом листе переименований быть не должно")
        self.assertIn((13, "SOP IDs"), plan["label_empty"])
        self.assertIn((14, "Checklist IDs"), plan["label_empty"])
        self.assertIn((15, "Materials IDs"), plan["label_empty"])
        self.assertIn((16, "Document Template IDs"), plan["label_empty"])
        self.assertIn((17, "FAQ IDs"), plan["label_empty"])
        self.assertEqual(plan["append"], [])

    def test_materials_and_faq_are_positional_not_data_confirmed(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        positional_names = [name for _, name in plan["inferred_by_position"]]
        self.assertIn("Materials IDs", positional_names)
        self.assertIn("FAQ IDs", positional_names)
        # SOP/Checklist/Document Template — подтверждены данными, не позиционно
        self.assertNotIn("SOP IDs", positional_names)
        self.assertNotIn("Checklist IDs", positional_names)
        self.assertNotIn("Document Template IDs", positional_names)

    def test_never_touches_unrelated_named_columns(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        touched = (
            [old for _, old, _ in plan["rename"]]
            + [new for _, _, new in plan["rename"]]
            + [new for _, new in plan["label_empty"]]
            + plan["append"]
        )
        for untouched in ("Stage ID", "Roadmap ID", "Status", "Name",
                          "Responsible", "Docs Required", "Notes"):
            self.assertNotIn(untouched, touched)

    def test_already_migrated_sheet_is_idempotent_no_changes(self):
        m = _fresh_migrate()
        all_values = [FULL_HEADERS] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        self.assertEqual(plan["rename"], [])
        self.assertEqual(plan["label_empty"], [])
        self.assertEqual(plan["append"], [])
        self.assertCountEqual(plan["already_correct"], m.CANONICAL_TAIL)

    def test_running_plan_twice_on_simulated_after_state_yields_no_further_changes(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        first_plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        migrated_headers = first_plan["after_headers_preview"]
        second_plan = m.analyze_roadmap_stages_headers(
            [migrated_headers] + _live_data_rows(), col_count=17)

        self.assertEqual(second_plan["rename"], [])
        self.assertEqual(second_plan["label_empty"], [])
        self.assertEqual(second_plan["append"], [])

    def test_mixed_incomplete_headers_fixed_correctly(self):
        """Смешанный/неполный набор: SOP IDs уже подписан правильно,
        Checklist IDs пуст, Materials/Document Template/FAQ — тоже пусты."""
        m = _fresh_migrate()
        mixed_headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
            "SOP IDs", "", "", "",
        ]
        plan = m.analyze_roadmap_stages_headers(
            [mixed_headers] + _live_data_rows(), col_count=17)

        self.assertIn("SOP IDs", plan["already_correct"])
        self.assertIn((14, "Checklist IDs"), plan["label_empty"])
        self.assertIn((16, "Document Template IDs"), plan["label_empty"])
        self.assertEqual(plan["rename"], [])

    def test_no_col_count_no_data_beyond_range_appends_faq(self):
        """Без информации о реальном col_count (например мок без атрибута)
        FAQ IDs, для которого физически нет ни заголовка, ни данных нигде —
        считается новой колонкой в конце."""
        m = _fresh_migrate()
        headers_without_col17 = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
            "SOP IDs", "Checklist IDs", "Materials IDs", "Document Template IDs",
        ]
        plan = m.analyze_roadmap_stages_headers([headers_without_col17], col_count=None)
        self.assertEqual(plan["append"], ["FAQ IDs"])

    def test_empty_sheet_does_not_crash(self):
        m = _fresh_migrate()
        plan = m.analyze_roadmap_stages_headers([])
        self.assertEqual(plan["before_headers"], [])

    def test_no_data_rows_at_all_all_append(self):
        m = _fresh_migrate()
        plan = m.analyze_roadmap_stages_headers([LIVE_HEADERS_BEFORE[:12]])
        self.assertEqual(plan["append"], list(m.CANONICAL_TAIL))


# ────────────────────────────────────────────────────────────
# strip_trailing_empty / compare_data_rows — регрессия ложного
# срабатывания byte-identical проверки (used-range padding из gspread)
# ────────────────────────────────────────────────────────────

class TestStripTrailingEmptyAndCompareDataRows(unittest.TestCase):

    def test_trailing_empty_added_by_padding_considered_equal(self):
        m = _fresh_migrate()
        self.assertEqual(m.strip_trailing_empty(["A", "B"]), ["A", "B"])
        self.assertEqual(m.strip_trailing_empty(["A", "B", ""]), ["A", "B"])
        self.assertEqual(
            m.strip_trailing_empty(["A", "B"]),
            m.strip_trailing_empty(["A", "B", ""]),
        )

    def test_multiple_trailing_empty_values_do_not_create_differences(self):
        m = _fresh_migrate()
        self.assertEqual(
            m.strip_trailing_empty(["A", "B", "", "", "", ""]),
            ["A", "B"],
        )
        comparison = m.compare_data_rows(
            [["A", "B"]],
            [["A", "B", "", "", ""]],
        )
        self.assertFalse(comparison["raw_equal"])
        self.assertTrue(comparison["normalized_equal"])
        self.assertEqual(comparison["real_diff_count"], 0)

    def test_internal_empty_value_keeps_its_position(self):
        """Пустое значение ВНУТРИ строки (например, незаполненное поле
        посередине) — это реальные данные, не padding, и не должно
        убираться или сдвигать соседние значения."""
        m = _fresh_migrate()
        row = ["STAGE-001-01", "RM-001", "1", "Name", "pending", "", "", "", "Дидар"]
        self.assertEqual(m.strip_trailing_empty(row), row)

        comparison = m.compare_data_rows([row], [list(row)])
        self.assertTrue(comparison["raw_equal"])
        self.assertTrue(comparison["normalized_equal"])
        self.assertEqual(comparison["real_diff_count"], 0)

    def test_real_value_change_is_detected(self):
        m = _fresh_migrate()
        before = [["STAGE-001-01", "RM-001", "1", "Name", "pending"]]
        after  = [["STAGE-001-01", "RM-001", "1", "Name", "done"]]

        comparison = m.compare_data_rows(before, after)
        self.assertFalse(comparison["raw_equal"])
        self.assertFalse(comparison["normalized_equal"])
        self.assertEqual(comparison["real_diff_count"], 1)

    def test_change_in_non_empty_value_count_is_detected(self):
        """Изменение количества НЕпустых значений (не просто хвостовой
        padding) должно быть обнаружено как реальное различие."""
        m = _fresh_migrate()
        before = [["STAGE-001-01", "RM-001", "1", "Name", "pending", "", "", "", "Дидар"]]
        after  = [["STAGE-001-01", "RM-001", "1", "Name", "pending", "", "", "", "Дидар", "SOP-001"]]

        comparison = m.compare_data_rows(before, after)
        self.assertFalse(comparison["raw_equal"])
        self.assertFalse(comparison["normalized_equal"])
        self.assertEqual(comparison["real_diff_count"], 1)

    def test_compare_data_rows_does_not_write_anywhere(self):
        """Чистая функция сравнения — не должна принимать/вызывать sheet."""
        m = _fresh_migrate()
        import inspect
        sig = inspect.signature(m.compare_data_rows)
        self.assertEqual(list(sig.parameters), ["before", "after"])

    def test_row_count_mismatch_counted_as_differences(self):
        m = _fresh_migrate()
        before = [["A"], ["B"]]
        after  = [["A"]]
        comparison = m.compare_data_rows(before, after)
        self.assertFalse(comparison["normalized_equal"])
        self.assertEqual(comparison["real_diff_count"], 1)


# ────────────────────────────────────────────────────────────
# apply_migration_plan — только заголовки, никогда данные
# ────────────────────────────────────────────────────────────

class TestApplyMigrationPlan(unittest.TestCase):

    def test_apply_only_writes_row_1_cells(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        sheet = MagicMock()
        actions = m.apply_migration_plan(sheet, plan)

        self.assertTrue(len(actions) > 0)
        for call in sheet.update_cell.call_args_list:
            self.assertEqual(call.args[0], 1)

        sheet.update.assert_not_called()
        sheet.delete_rows.assert_not_called()
        sheet.clear.assert_not_called()
        sheet.append_row.assert_not_called()

    def test_apply_writes_expected_columns(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        sheet = MagicMock()
        m.apply_migration_plan(sheet, plan)

        written = {call.args[1]: call.args[2] for call in sheet.update_cell.call_args_list}
        self.assertEqual(written.get(13), "SOP IDs")
        self.assertEqual(written.get(14), "Checklist IDs")
        self.assertEqual(written.get(15), "Materials IDs")
        self.assertEqual(written.get(16), "Document Template IDs")
        self.assertEqual(written.get(17), "FAQ IDs")

    def test_apply_on_already_correct_plan_does_nothing(self):
        m = _fresh_migrate()
        plan = m.analyze_roadmap_stages_headers([FULL_HEADERS] + _live_data_rows(), col_count=17)

        sheet = MagicMock()
        actions = m.apply_migration_plan(sheet, plan)

        self.assertEqual(actions, [])
        sheet.update_cell.assert_not_called()

    def test_repeated_apply_does_not_duplicate_headers(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        plan = m.analyze_roadmap_stages_headers(all_values, col_count=17)

        sheet = MagicMock()
        m.apply_migration_plan(sheet, plan)

        migrated_headers = plan["after_headers_preview"]
        second_plan = m.analyze_roadmap_stages_headers(
            [migrated_headers] + _live_data_rows(), col_count=17)
        second_actions = m.apply_migration_plan(MagicMock(), second_plan)
        self.assertEqual(second_actions, [])


# ────────────────────────────────────────────────────────────
# main() CLI: dry-run по умолчанию, YES обязателен для live,
# проверка целостности данных до/после
# ────────────────────────────────────────────────────────────

class TestMigrationCliSafety(unittest.TestCase):

    def _sheet_before(self, col_count=17):
        sheet = MagicMock()
        rows = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        sheet.get_all_values.return_value = rows
        sheet.col_count = col_count
        return sheet

    def test_dry_run_default_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_explicit_dry_run_flag_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--dry-run"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_live_without_yes_confirmation_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="no"):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_live_with_yes_confirmation_writes(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="YES"):
            m.main()
        sheet.update_cell.assert_called()

    def test_live_on_already_correct_sheet_asks_nothing_and_writes_nothing(self):
        m = _fresh_migrate()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [FULL_HEADERS] + _live_data_rows()
        sheet.col_count = 17
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", side_effect=AssertionError("не должен спрашивать YES")):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_live_verifies_data_rows_identical_before_and_after(self):
        """main() должен сверять строки данных до/после live-записи."""
        m = _fresh_migrate()
        data_rows = _live_data_rows()
        sheet = MagicMock()
        # get_all_values вызывается трижды: анализ, снимок до записи, снимок после
        sheet.get_all_values.return_value = [LIVE_HEADERS_BEFORE] + data_rows
        sheet.col_count = 17

        printed = []
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="YES"), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            m.main()

        joined = "\n".join(printed)
        self.assertIn("raw_equal", joined)
        self.assertIn("True", joined)
        self.assertIn("normalized_equal", joined)
        self.assertNotIn("ВНИМАНИЕ", joined)

    def test_live_used_range_padding_is_not_reported_as_data_change(self):
        """Регрессия реального инцидента: после подписи ранее пустого
        заголовка used-range листа расширяется, и gspread дополняет КАЖДУЮ
        строку данных хвостовой '' — это должно распознаваться как
        raw_equal=False, normalized_equal=True, БЕЗ тревоги 'ВНИМАНИЕ'."""
        m = _fresh_migrate()
        sheet = MagicMock()
        before_rows = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        # "после" — те же данные, но each row получила ровно одну лишнюю
        # хвостовую пустую ячейку (рост used-range с 16 до 17 колонок).
        after_data = [list(r) + [""] for r in _live_data_rows()]
        after_rows = [FULL_HEADERS] + after_data
        sheet.get_all_values.side_effect = [before_rows, before_rows[1:], after_rows[1:]]
        sheet.col_count = 17

        printed = []
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="YES"), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            m.main()

        joined = "\n".join(printed)
        self.assertIn("raw_equal (сырое сравнение, чувствительно к padding used-range): False", joined)
        self.assertIn("normalized_equal (без хвостовых пустых значений):               True", joined)
        self.assertIn("Количество строк с реальными различиями:                        0", joined)
        self.assertNotIn("ВНИМАНИЕ", joined)

    def test_live_detects_data_mismatch_if_rows_changed_unexpectedly(self):
        """Если между 'до' и 'после' снимками данные всё же изменились
        по существу (не просто хвостовой padding) — это должно быть явно
        показано (defensive check)."""
        m = _fresh_migrate()
        sheet = MagicMock()
        before_rows = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        after_rows  = [FULL_HEADERS] + [["CHANGED"] + r[1:] for r in _live_data_rows()]
        sheet.get_all_values.side_effect = [before_rows, before_rows[1:], after_rows[1:]]
        sheet.col_count = 17

        printed = []
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="YES"), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            m.main()

        joined = "\n".join(printed)
        self.assertIn("normalized_equal (без хвостовых пустых значений):               False", joined)
        self.assertIn("ВНИМАНИЕ", joined)


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

    def test_migrate_script_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "migrate_roadmap_stages_headers.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_migrate()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)

    def test_migration_script_never_calls_sheet_write_in_dry_run_end_to_end(self):
        m = _fresh_migrate()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [LIVE_HEADERS_BEFORE] + _live_data_rows()
        sheet.col_count = 17
        with patch("sys.argv", ["migrate_roadmap_stages_headers.py"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()

        for write_method in ("update_cell", "update", "append_row", "delete_rows",
                             "clear", "batch_update", "insert_row"):
            getattr(sheet, write_method).assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
