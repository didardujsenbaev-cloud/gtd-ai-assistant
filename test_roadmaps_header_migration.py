"""
Tests for the header-name-based ROADMAPS read/write path and the
migrate_roadmaps_headers.py migration tool.

Context (RM-027 остаточный баг): create_roadmap_for_object писал строку
ПОЗИЦИОННО по статическому списку BUSINESS_HEADERS, полностью игнорируя
фактические заголовки живого листа. Живой лист ROADMAPS исторически имел
только 24 реальных заголовка (до 'Last Updated'); Object ID / Parent
Roadmap ID / Case Type годами писались в колонки 25-27 без подписей.
Когда прошлый фикс дописал колонку 'Template ID' по фактической длине
заголовков (24 -> колонка 25), она легла ровно на данные Object ID.

Это исправление переводит запись (create_roadmap_for_object) и чтение
(find_roadmap_by_id) на сопоставление по ИМЕНИ заголовка, и добавляет
отдельный, идемпотентный, dry-run-first инструмент миграции заголовков.
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
        if "business_core" in k or k == "migrate_roadmaps_headers":
            del sys.modules[k]
    import importlib
    return importlib.import_module(mod_name)


def _fresh_sheets():
    return _fresh("business_core.sheets")


def _fresh_bb():
    return _fresh("business_core.business_builder")


def _fresh_migrate():
    return _fresh("migrate_roadmaps_headers")


# Полный "правильный" набор заголовков ROADMAPS (после миграции).
FULL_HEADERS = [
    "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
    "Client Name", "GTD Project ID", "Responsible", "Status",
    "Created", "Expected", "Progress %",
    "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
    "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
    "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
    "Stage 10 Status", "Notes", "Last Updated",
    "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
]

# Реальная живая раскладка ROADMAPS ДО миграции (воспроизводит прод):
# 24 подписанных заголовка + колонка 25 ошибочно подписана 'Template ID',
# хотя в ней реально лежат значения Object ID; 26-28 без подписи.
LIVE_HEADERS_BEFORE_MIGRATION = FULL_HEADERS[:24] + ["Template ID", "", "", ""]


def _live_data_rows():
    """
    Данные, похожие на реальный прод: колонка 25 = OBJ-xxx, 26 = '' всегда,
    27 = case_type строки, 28 = template_id только для новых roadmap (RM-027).
    """
    def row(rm_id, obj_id, case_type, template_id=""):
        base = [rm_id, "BIZ-001", "SVC-IZH-001", "", "PRS-001", "title",
                "", "", "active", "2026-01-01", "", "0",
                "", "", "", "", "", "", "", "", "", "",
                "", "2026-01-01"]
        return base + [obj_id, "", case_type, template_id]

    return [
        row("RM-022", "OBJ-007", "general"),
        row("RM-026", "OBJ-007", "general"),
        row("RM-027", "OBJ-001", "general", "RMT-IZH-ALM-STANDARD-002"),
    ]


# ────────────────────────────────────────────────────────────
# A1/A3. Общий helper: header name -> column index -> value
# ────────────────────────────────────────────────────────────

class TestHeaderMappingHelpers(unittest.TestCase):

    def test_get_header_index_map_basic(self):
        sheets_mod = _fresh_sheets()
        idx = sheets_mod.get_header_index_map(["A", "B", "C"])
        self.assertEqual(idx, {"A": 0, "B": 1, "C": 2})

    def test_get_header_index_map_ignores_empty_and_dup_headers(self):
        sheets_mod = _fresh_sheets()
        idx = sheets_mod.get_header_index_map(["A", "", "B", "A"])
        self.assertEqual(idx, {"A": 0, "B": 2})

    def test_row_from_header_map_places_values_by_name(self):
        sheets_mod = _fresh_sheets()
        headers = ["Roadmap ID", "Template ID", "Case Type"]
        row = sheets_mod.row_from_header_map(headers, {
            "Roadmap ID": "RM-100", "Template ID": "RMT-X", "Case Type": "general",
        })
        self.assertEqual(row, ["RM-100", "RMT-X", "general"])

    def test_row_from_header_map_order_independent(self):
        """Порядок заголовков в листе может отличаться от порядка ключей в values."""
        sheets_mod = _fresh_sheets()
        headers = ["Case Type", "Roadmap ID", "Template ID"]
        row = sheets_mod.row_from_header_map(headers, {
            "Roadmap ID": "RM-101", "Template ID": "RMT-Y", "Case Type": "legalization",
        })
        idx = {h: i for i, h in enumerate(headers)}
        self.assertEqual(row[idx["Roadmap ID"]], "RM-101")
        self.assertEqual(row[idx["Template ID"]], "RMT-Y")
        self.assertEqual(row[idx["Case Type"]], "legalization")

    def test_row_from_header_map_raises_on_missing_header(self):
        sheets_mod = _fresh_sheets()
        with self.assertRaises(ValueError) as ctx:
            sheets_mod.row_from_header_map(["Roadmap ID"], {"Template ID": "RMT-X"})
        self.assertIn("Template ID", str(ctx.exception))

    def test_read_row_by_headers_reads_by_name(self):
        sheets_mod = _fresh_sheets()
        headers = ["Roadmap ID", "Template ID"]
        row = ["RM-100", "RMT-X"]
        values = sheets_mod.read_row_by_headers(headers, row, ["Roadmap ID", "Template ID"])
        self.assertEqual(values, {"Roadmap ID": "RM-100", "Template ID": "RMT-X"})

    def test_read_row_by_headers_missing_header_returns_empty(self):
        sheets_mod = _fresh_sheets()
        values = sheets_mod.read_row_by_headers(["Roadmap ID"], ["RM-100"], ["Template ID"])
        self.assertEqual(values, {"Template ID": ""})


# ────────────────────────────────────────────────────────────
# A1. create_roadmap_for_object пишет по фактическим заголовкам
# (базовые кейсы уже покрыты в test_roadmap_template_id_persistence.py;
#  здесь — специфика регрессии RM-027 и устойчивость к перестановке).
# ────────────────────────────────────────────────────────────

class TestCreateRoadmapWritesByActualHeaders(unittest.TestCase):

    def test_object_id_and_template_id_never_collide(self):
        """Регрессия RM-027: Object ID и Template ID должны попадать в
        РАЗНЫЕ колонки, даже если 'Template ID' стоит раньше 'Object ID'
        в списке заголовков листа."""
        bb = _fresh_bb()
        rows = []
        headers = ["Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
                   "Client Name", "GTD Project ID", "Responsible", "Status",
                   "Created", "Expected", "Progress %", "Notes", "Last Updated",
                   "Template ID", "Object ID", "Parent Roadmap ID", "Case Type"]
        sheet = MagicMock()
        sheet.row_values.return_value = headers

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: rows.append((k, r))), \
             patch.object(bb, "generate_roadmap_id", return_value="RM-600"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-IZH-001", template_id="RMT-IZH-ALM-STANDARD-002",
            )

        self.assertTrue(result["ok"])
        row = rows[0][1]
        idx = {h: i for i, h in enumerate(headers)}
        self.assertEqual(row[idx["Template ID"]], "RMT-IZH-ALM-STANDARD-002")
        self.assertEqual(row[idx["Object ID"]], "OBJ-001")
        self.assertNotEqual(row[idx["Template ID"]], row[idx["Object ID"]])


# ────────────────────────────────────────────────────────────
# classify_column_data — распознавание содержимого колонки по данным
# ────────────────────────────────────────────────────────────

class TestClassifyColumnData(unittest.TestCase):

    def test_object_id_pattern(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["OBJ-001", "OBJ-007"]), "Object ID")

    def test_template_id_pattern(self):
        m = _fresh_migrate()
        self.assertEqual(
            m.classify_column_data(["RMT-IZH-ALM-STANDARD-002"]), "Template ID")

    def test_parent_roadmap_id_pattern(self):
        m = _fresh_migrate()
        self.assertEqual(m.classify_column_data(["RM-001", "RM-045"]), "Parent Roadmap ID")

    def test_case_type_pattern(self):
        m = _fresh_migrate()
        self.assertEqual(
            m.classify_column_data(["general", "legalization_reconstruction_house"]),
            "Case Type")

    def test_empty_returns_none(self):
        m = _fresh_migrate()
        self.assertIsNone(m.classify_column_data(["", "  ", ""]))

    def test_mixed_unrecognized_returns_none_not_case_type(self):
        """Раньше любые нераспознанные значения ошибочно считались Case Type
        (из-за чего Business ID чуть не переименовали). Теперь — безопасный None."""
        m = _fresh_migrate()
        self.assertIsNone(m.classify_column_data(["BIZ-001", "BIZ-002"]))
        self.assertIsNone(m.classify_column_data(["active", "PRS-001", "2026-01-01"]))


# ────────────────────────────────────────────────────────────
# analyze_roadmaps_headers — план миграции по факту данных
# ────────────────────────────────────────────────────────────

class TestAnalyzeRoadmapsHeaders(unittest.TestCase):

    def test_reproduces_rm027_bug_state_and_proposes_correct_fix(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        self.assertIn((25, "Template ID", "Object ID"), plan["rename"])
        self.assertIn((26, "Parent Roadmap ID"), plan["label_empty"])
        self.assertIn((27, "Case Type"), plan["label_empty"])
        self.assertIn((28, "Template ID"), plan["label_empty"])
        self.assertEqual(plan["append"], [])

    def test_never_touches_unrelated_named_columns(self):
        """Business ID / Client ID / Status и т.п. никогда не должны
        попадать в rename/label_empty/append — только 4 канонических поля."""
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        touched_names = (
            [old for _, old, _ in plan["rename"]]
            + [new for _, _, new in plan["rename"]]
            + [new for _, new in plan["label_empty"]]
            + plan["append"]
        )
        for untouched in ("Business ID", "Client ID", "Status", "Roadmap ID",
                          "Service ID", "Notes"):
            self.assertNotIn(untouched, touched_names)

    def test_already_migrated_sheet_is_idempotent_no_changes(self):
        """Повторная миграция на уже корректных заголовках не предлагает изменений."""
        m = _fresh_migrate()
        all_values = [FULL_HEADERS] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        self.assertEqual(plan["rename"], [])
        self.assertEqual(plan["label_empty"], [])
        self.assertEqual(plan["append"], [])
        self.assertCountEqual(
            plan["already_correct"],
            ["Object ID", "Parent Roadmap ID", "Case Type", "Template ID"],
        )

    def test_running_plan_twice_on_simulated_after_state_yields_no_further_changes(self):
        """Симулируем 'после' первой миграции и прогоняем анализ снова — дублей нет."""
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        first_plan = m.analyze_roadmaps_headers(all_values)

        migrated_headers = first_plan["after_headers_preview"]
        second_all_values = [migrated_headers] + _live_data_rows()
        second_plan = m.analyze_roadmaps_headers(second_all_values)

        self.assertEqual(second_plan["rename"], [])
        self.assertEqual(second_plan["label_empty"], [])
        self.assertEqual(second_plan["append"], [])

    def test_fresh_sheet_with_no_extra_columns_appends_all_four(self):
        """Совершенно новый лист без данных за пределами Last Updated —
        для всех 4 полей нет колонки-кандидата, поэтому все добавляются в конец."""
        m = _fresh_migrate()
        clean_headers = FULL_HEADERS[:24]
        plan = m.analyze_roadmaps_headers([clean_headers])

        self.assertEqual(
            plan["append"],
            ["Object ID", "Parent Roadmap ID", "Case Type", "Template ID"],
        )
        self.assertEqual(plan["rename"], [])
        self.assertEqual(plan["label_empty"], [])

    def test_no_data_rows_at_all_does_not_crash(self):
        m = _fresh_migrate()
        plan = m.analyze_roadmaps_headers([FULL_HEADERS])
        self.assertCountEqual(
            plan["already_correct"],
            ["Object ID", "Parent Roadmap ID", "Case Type", "Template ID"],
        )

    def test_empty_sheet_does_not_crash(self):
        m = _fresh_migrate()
        plan = m.analyze_roadmaps_headers([])
        self.assertEqual(plan["before_headers"], [])


# ────────────────────────────────────────────────────────────
# apply_migration_plan — только заголовки, никогда данные
# ────────────────────────────────────────────────────────────

class TestApplyMigrationPlan(unittest.TestCase):

    def test_apply_only_writes_row_1_cells(self):
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        sheet = MagicMock()
        actions = m.apply_migration_plan(sheet, plan)

        self.assertTrue(len(actions) > 0)
        for call in sheet.update_cell.call_args_list:
            args = call.args
            self.assertEqual(args[0], 1, "update_cell должен писать только в строку 1 (заголовки)")

        sheet.update.assert_not_called()
        sheet.delete_rows.assert_not_called()
        sheet.clear.assert_not_called()
        sheet.append_row.assert_not_called()

    def test_apply_does_not_shift_object_id_parent_case_type(self):
        """После применения плана колонки 25/26/27 остаются на своих местах —
        меняются только подписи (row 1), не позиции существующих данных."""
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        sheet = MagicMock()
        m.apply_migration_plan(sheet, plan)

        written = {call.args[1]: call.args[2] for call in sheet.update_cell.call_args_list}
        self.assertEqual(written.get(25), "Object ID")
        self.assertEqual(written.get(26), "Parent Roadmap ID")
        self.assertEqual(written.get(27), "Case Type")
        self.assertEqual(written.get(28), "Template ID")

    def test_apply_on_already_correct_plan_does_nothing(self):
        m = _fresh_migrate()
        all_values = [FULL_HEADERS] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        sheet = MagicMock()
        actions = m.apply_migration_plan(sheet, plan)

        self.assertEqual(actions, [])
        sheet.update_cell.assert_not_called()

    def test_repeated_apply_does_not_duplicate_headers(self):
        """Применяем план, затем снова анализируем и применяем — второй раз ничего не пишет."""
        m = _fresh_migrate()
        all_values = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        plan = m.analyze_roadmaps_headers(all_values)

        sheet = MagicMock()
        m.apply_migration_plan(sheet, plan)

        migrated_headers = plan["after_headers_preview"]
        second_plan = m.analyze_roadmaps_headers([migrated_headers] + _live_data_rows())
        second_actions = m.apply_migration_plan(MagicMock(), second_plan)
        self.assertEqual(second_actions, [])


# ────────────────────────────────────────────────────────────
# main() CLI: dry-run по умолчанию, YES обязателен для live
# ────────────────────────────────────────────────────────────

class TestMigrationCliSafety(unittest.TestCase):

    def _sheet_before(self):
        sheet = MagicMock()
        sheet.get_all_values.return_value = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        return sheet

    def test_dry_run_default_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmaps_headers.py"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_explicit_dry_run_flag_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmaps_headers.py", "--dry-run"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_live_without_yes_confirmation_does_not_write(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmaps_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="no"):
            m.main()
        sheet.update_cell.assert_not_called()

    def test_live_with_yes_confirmation_writes(self):
        m = _fresh_migrate()
        sheet = self._sheet_before()
        with patch("sys.argv", ["migrate_roadmaps_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", return_value="YES"):
            m.main()
        sheet.update_cell.assert_called()

    def test_live_on_already_correct_sheet_asks_nothing_and_writes_nothing(self):
        m = _fresh_migrate()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [FULL_HEADERS] + _live_data_rows()
        with patch("sys.argv", ["migrate_roadmaps_headers.py", "--live"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("builtins.input", side_effect=AssertionError("не должен спрашивать YES")):
            m.main()
        sheet.update_cell.assert_not_called()


# ────────────────────────────────────────────────────────────
# Regression: find_roadmap_by_id больше не путает Object ID и Template ID
# ────────────────────────────────────────────────────────────

class TestFindRoadmapByIdRegressionRM027(unittest.TestCase):

    def _fake_sheet(self, headers, row):
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: headers if r == 1 else row
        return sheet

    def test_rm027_template_id_after_migration_is_correct(self):
        """После корректной миграции заголовков RM-027 должен читаться с
        правильным template_id, а не с Object ID."""
        bb = _fresh_bb()
        headers = FULL_HEADERS
        row = _live_data_rows()[2]  # RM-027
        sheet = self._fake_sheet(headers, row)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = bb.find_roadmap_by_id("RM-027")

        self.assertEqual(result["template_id"], "RMT-IZH-ALM-STANDARD-002")
        self.assertNotEqual(result["template_id"], "OBJ-001")
        self.assertEqual(result["obj_id"], "OBJ-001")
        self.assertEqual(result["case_type"], "general")

    def test_rm027_before_migration_reproduces_reported_bug(self):
        """Документирует ИСХОДНОЕ сообщение о баге: до миграции живого листа
        find_roadmap_by_id действительно возвращает OBJ-001 как template_id —
        это подтверждает, что причина в заголовках, а не в логике поиска."""
        bb = _fresh_bb()
        headers = LIVE_HEADERS_BEFORE_MIGRATION
        row = _live_data_rows()[2]  # RM-027
        sheet = self._fake_sheet(headers, row)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = bb.find_roadmap_by_id("RM-027")

        self.assertEqual(result["template_id"], "OBJ-001")


# ────────────────────────────────────────────────────────────
# Обратная совместимость: старые roadmap без Template ID — fallback
# ────────────────────────────────────────────────────────────

class TestOldRoadmapsFallbackAfterHeaderFix(unittest.TestCase):

    def test_roadmap_without_template_id_header_falls_back(self):
        bb = _fresh_bb()
        rm = _fresh("business_core.roadmap_manager")

        headers = FULL_HEADERS[:24]  # ещё нет Object ID/Parent/Case Type/Template ID
        row = ["RM-022", "BIZ-001", "SVC-IZH-001", "", "PRS-001", "title",
               "", "", "active", "2026-01-01", "", "0",
               "", "", "", "", "", "", "", "", "", "", "", "2026-01-01"]
        cell = MagicMock()
        cell.row = 2
        sheet = MagicMock()
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: headers if r == 1 else row

        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            roadmap = bb.find_roadmap_by_id("RM-022")

        self.assertEqual(roadmap["template_id"], "")
        self.assertEqual(roadmap["obj_id"], "", "колонки ещё нет — пусто, не мусор из чужой позиции")

        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-IZH-001",
                                 "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}):
            tid = rm._resolve_template_id(roadmap)
        self.assertEqual(tid, "RMT-IZH-ALM-LEGALIZATION-001")


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

    def test_business_builder_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "business_builder.py")

    def test_sheets_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "business_core" / "sheets.py")

    def test_migrate_script_no_gtd_imports(self):
        self._check_no_gtd_imports(WORKSPACE / "migrate_roadmaps_headers.py")

    def test_env_not_modified_by_import(self):
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        _fresh_bb()
        _fresh_migrate()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)

    def test_migration_script_never_calls_sheet_write_in_dry_run_end_to_end(self):
        """Финальная защита: полный main() в dry-run режиме не должен звать
        ни одного write-метода Worksheet."""
        m = _fresh_migrate()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [LIVE_HEADERS_BEFORE_MIGRATION] + _live_data_rows()
        with patch("sys.argv", ["migrate_roadmaps_headers.py"]), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            m.main()

        for write_method in ("update_cell", "update", "append_row", "delete_rows",
                             "clear", "batch_update", "insert_row"):
            getattr(sheet, write_method).assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
