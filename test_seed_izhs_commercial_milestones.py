"""
Tests for seed_izhs_commercial_milestones.py

Checks 1–5 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

WORKSPACE  = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE  = "business_core.seeds.seed_izhs_commercial_milestones"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


def _fresh():
    for k in list(sys.modules):
        if "business_core" in k or k == SEED_MODULE:
            del sys.modules[k]
    import importlib
    return importlib.import_module(SEED_MODULE)


def _imports(path: Path) -> list[str]:
    src  = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module.split(".")[0])
    return mods


def _sheet_with_row(headers, row_values):
    """Мок листа с одной строкой данных."""
    ws = MagicMock()
    ws.get_all_values.return_value = [headers, row_values]
    ws.update_cell = MagicMock()
    return ws


# ────────────────────────────────────────────────────────────
# 1. dry-run не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_1_dry_run_no_writes(self):
        """1: dry-run не вызывает update_cell и append_row."""
        seed   = _fresh()
        writes = []
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=False), \
             patch("business_core.sheets.get_business_sheet") as mock_gs:
            ws = MagicMock()
            ws.update_cell = MagicMock(side_effect=lambda *a: writes.append(a))
            mock_gs.return_value = ws
            result = seed.patch_service_notes(dry_run=True)

        self.assertEqual(writes, [], "dry_run не должен вызывать update_cell")
        self.assertEqual(result["action"], "would_update")
        self.assertTrue(result["ok"])

    def test_1_dry_run_plan_shows_update(self):
        """1: dry_run() показывает UPDATE когда нужно."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=False):
            result = seed.dry_run()
        self.assertGreater(len(result["plan"]), 0)
        self.assertTrue(any("UPDATE" in p for p in result["plan"]))

    def test_1_dry_run_skip_when_patched(self):
        """1: dry_run() показывает SKIP если уже есть маркер."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])
        self.assertGreater(len(result["skip"]), 0)

    def test_1_dry_run_warn_if_no_service(self):
        """1: dry_run() предупреждает если сервис не найден."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists", return_value=False):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])
        self.assertTrue(any("WARN" in s or "не найден" in s for s in result["skip"]))


# ────────────────────────────────────────────────────────────
# 2. Notes/Description обновляется
# ────────────────────────────────────────────────────────────

class TestPatchUpdates(unittest.TestCase):

    def _make_sheet(self, notes_val=""):
        headers   = ["ID", "Бизнес ID", "Название", "Комментарий", "Notes"]
        row_vals  = ["SVC-IZH-001", "BIZ-001", "Узаконение", notes_val, notes_val]
        return _sheet_with_row(headers, row_vals)

    def test_2_updates_notes_column(self):
        """2: patch_service_notes обновляет колонку Комментарий."""
        seed  = _fresh()
        sheet = self._make_sheet("")
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=False), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets._invalidate_sheet_cache"):
            result = seed.patch_service_notes(dry_run=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "updated")
        sheet.update_cell.assert_called()

    def test_2_written_value_contains_marker(self):
        """2: записанное значение содержит маркер версии."""
        seed  = _fresh()
        sheet = self._make_sheet("")
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=False), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets._invalidate_sheet_cache"):
            seed.patch_service_notes(dry_run=False)

        # Ищем вызов update_cell с маркером
        marker_found = any(
            seed._MARKER in str(c.args)
            for c in sheet.update_cell.call_args_list
        )
        self.assertTrue(marker_found, "Маркер должен быть в записанном значении")

    def test_2_written_value_contains_price(self):
        """2: записанное значение содержит 950 000 тг."""
        seed  = _fresh()
        sheet = self._make_sheet("")
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=False), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets._invalidate_sheet_cache"):
            seed.patch_service_notes(dry_run=False)

        all_written = " ".join(str(c.args) for c in sheet.update_cell.call_args_list)
        self.assertIn("950", all_written)
        self.assertIn("150", all_written)
        self.assertIn("500", all_written)
        self.assertIn("300", all_written)

    def test_2_written_value_contains_3_stages(self):
        """2: описание содержит 3 этапа."""
        seed = _fresh()
        notes = seed.COMMERCIAL_NOTES
        self.assertIn("Этап 1", notes)
        self.assertIn("Этап 2", notes)
        self.assertIn("Этап 3", notes)

    def test_2_returns_error_if_service_missing(self):
        """2: возвращает ошибку если SVC-IZH-001 не найден."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists", return_value=False):
            result = seed.patch_service_notes(dry_run=False)
        self.assertFalse(result["ok"])
        self.assertIn("не найден", result["error"])


# ────────────────────────────────────────────────────────────
# 3. повторный запуск не дублирует текст
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_3_skip_if_marker_exists(self):
        """3: patch_service_notes возвращает skip если маркер уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=True):
            result = seed.patch_service_notes(dry_run=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "skip")

    def test_3_no_update_cell_on_second_run(self):
        """3: update_cell не вызывается если маркер уже есть."""
        seed  = _fresh()
        # Лист содержит строку с маркером
        notes_with_marker = f"Старые заметки\n\n=== {seed._MARKER} ==="
        headers  = ["ID", "Комментарий"]
        row_vals = ["SVC-IZH-001", notes_with_marker]
        ws = _sheet_with_row(headers, row_vals)

        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=True), \
             patch("business_core.sheets.get_business_sheet", return_value=ws):
            seed.patch_service_notes(dry_run=False)

        ws.update_cell.assert_not_called()

    def test_3_marker_is_unique_string(self):
        """3: маркер уникален и не меняется."""
        seed = _fresh()
        self.assertEqual(seed._MARKER, "КОММЕРЧЕСКАЯ МОДЕЛЬ v1")

    def test_3_already_patched_detects_marker(self):
        """3: _already_patched возвращает True если маркер есть в Notes."""
        seed = _fresh()
        notes_with_marker = f"Старый текст\n\n=== {seed._MARKER} ==="
        headers  = ["ID", "Комментарий", "Notes"]
        row_vals = ["SVC-IZH-001", notes_with_marker, ""]
        ws = _sheet_with_row(headers, row_vals)

        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = seed._already_patched()
        self.assertTrue(result)

    def test_3_already_patched_false_without_marker(self):
        """3: _already_patched возвращает False если маркера нет."""
        seed = _fresh()
        headers  = ["ID", "Комментарий"]
        row_vals = ["SVC-IZH-001", "Обычные заметки без маркера"]
        ws = _sheet_with_row(headers, row_vals)

        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = seed._already_patched()
        self.assertFalse(result)


# ────────────────────────────────────────────────────────────
# 4. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_4_env_file_not_modified(self):
        """4: .env файл не изменён этим seed."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        seed = _fresh()
        # Запуск dry_run не должен трогать .env
        with patch(f"{SEED_MODULE}._service_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._already_patched", return_value=True):
            seed.dry_run()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after, ".env был изменён!")

    def test_4_seed_does_not_import_dotenv_write(self):
        """4: seed не вызывает запись в .env."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.patch_service_notes)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)

    def test_4_commercial_notes_content(self):
        """4: коммерческая модель содержит все ключевые поля."""
        seed = _fresh()
        notes = seed.COMMERCIAL_NOTES
        required = [
            "150 000", "500 000", "300 000", "950 000",
            "Этап 1", "Этап 2", "Этап 3",
            "АПЗ", "НАО", "техпаспорт",
            "Не входит",
        ]
        for r in required:
            self.assertIn(r, notes, f"В COMMERCIAL_NOTES отсутствует: {r!r}")


# ────────────────────────────────────────────────────────────
# 5. GTD Core не трогается
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_5_seed_file(self):
        self._check(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_commercial_milestones.py"
        )

    def test_5_service_manager(self):
        self._check(WORKSPACE / "business_core" / "service_manager.py")

    def test_5_sheets(self):
        self._check(WORKSPACE / "business_core" / "sheets.py")

    def test_5_no_gtd_functions(self):
        """5: patch_service_notes не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.patch_service_notes)
        for forbidden in ["create_action", "create_project", "add_to_inbox",
                          "inbox_processor", "telegram_bot"]:
            self.assertNotIn(forbidden, src)

    def test_5_service_id_constant(self):
        """5: SERVICE_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_ID, "SVC-IZH-001")

    def test_5_target_columns_defined(self):
        """5: целевые колонки определены."""
        seed = _fresh()
        self.assertIn("Комментарий", seed._TARGET_COLUMNS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
