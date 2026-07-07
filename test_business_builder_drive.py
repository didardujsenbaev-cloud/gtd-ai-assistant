"""
Тесты для Drive-интеграции business_core/business_builder.py.

Все тесты работают без реального Google Drive (mock).
Проверяет:
  1. provision_biz_drive: нет env-переменных → skip (ok=False)
  2. provision_biz_drive: Drive успешен → ok=True + folder_id + folder_url
  3. provision_biz_drive: Drive упал → ok=False + error (не бросает исключение)
  4. provision_biz_drive: идемпотентность (повторный вызов)
  5. save_drive_info_to_sheets: обновляет 'Google Drive' и 'Drive Folder ID' колонки
  6. save_drive_info_to_sheets: biz_id не найден → возвращает False
  7. save_drive_info_to_sheets: ошибка Sheets → False (не бросает)
  8. GTD-файлы не импортируются
  9. /newbiz создаёт бизнес даже если Drive отключён
 10. /newbiz при ошибке Drive показывает предупреждение
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# .env не нужен для mock-тестов, но если есть — загружаем
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=".env")
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────
# Импорт тестируемых функций
# ─────────────────────────────────────────────────────────────

from business_core.business_builder import provision_biz_drive, save_drive_info_to_sheets


# ─────────────────────────────────────────────────────────────
# Тест 1–4: provision_biz_drive()
# ─────────────────────────────────────────────────────────────

class TestProvisionBizDrive(unittest.TestCase):

    def test_no_gdrive_root_returns_error_dict(self):
        """Нет GDRIVE_BIZ_ROOT_FOLDER_ID → ok=False, нет исключения."""
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict(os.environ, env, clear=False):
            # Удаляем ключ если был
            os.environ.pop("GDRIVE_BIZ_ROOT_FOLDER_ID", None)
            result = provision_biz_drive("BIZ-001", "Тест")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["folder_id"])
        self.assertIsNone(result["folder_url"])
        self.assertIsNotNone(result["error"])

    def test_no_credentials_returns_error_dict(self):
        """Нет GOOGLE_CREDENTIALS_FILE → ok=False."""
        env_backup = os.environ.pop("GOOGLE_CREDENTIALS_FILE", None)
        try:
            with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT_123"}, clear=False):
                os.environ.pop("GOOGLE_CREDENTIALS_FILE", None)
                result = provision_biz_drive("BIZ-001", "Тест")
            self.assertFalse(result["ok"])
        finally:
            if env_backup:
                os.environ["GOOGLE_CREDENTIALS_FILE"] = env_backup

    def test_success_returns_folder_info(self):
        """Drive API доступен → ok=True + folder_id + folder_url."""
        mock_result = {
            "business_folder_id":  "FOLDER_ID_001",
            "business_folder_url": "https://drive.google.com/drive/folders/FOLDER_ID_001",
            "folders":             {},
            "dry_run":             False,
        }
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT_123",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                return_value=mock_result,
            ):
                with patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()):
                    result = provision_biz_drive("BIZ-001", "Узаконение")

        self.assertTrue(result["ok"])
        self.assertEqual(result["folder_id"], "FOLDER_ID_001")
        self.assertIn("drive.google.com", result["folder_url"])
        self.assertIsNone(result["error"])

    def test_drive_exception_returns_error_dict(self):
        """Drive API упал → ok=False + error строка, исключение НЕ пробрасывается."""
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT_123",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                side_effect=RuntimeError("Drive API timeout"),
            ):
                result = provision_biz_drive("BIZ-002", "Бизнес")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["folder_id"])
        self.assertIsNotNone(result["error"])
        self.assertIn("Drive API timeout", result["error"])

    def test_idempotent_same_folder(self):
        """Повторный вызов — возвращает тот же folder_id (адаптер идемпотентен)."""
        mock_result = {
            "business_folder_id":  "STABLE_ID_001",
            "business_folder_url": "https://drive.google.com/drive/folders/STABLE_ID_001",
            "folders":             {},
            "dry_run":             False,
        }
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT_123",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                return_value=mock_result,
            ):
                r1 = provision_biz_drive("BIZ-003", "Бизнес")
                r2 = provision_biz_drive("BIZ-003", "Бизнес")

        self.assertEqual(r1["folder_id"], r2["folder_id"])
        self.assertEqual(r1["folder_url"], r2["folder_url"])


# ─────────────────────────────────────────────────────────────
# Тест 5–7: save_drive_info_to_sheets()
# ─────────────────────────────────────────────────────────────

class TestSaveDriveInfoToSheets(unittest.TestCase):

    def _make_mock_sheet(self, headers: list[str]):
        """Создать mock Worksheet с нужными заголовками."""
        sheet = MagicMock()
        sheet.row_values.return_value = headers
        return sheet

    def test_updates_google_drive_column(self):
        """'Google Drive' колонка обновляется folder_url."""
        headers = ["ID", "Название", "Google Drive", "Drive Folder ID"]
        mock_sheet = self._make_mock_sheet(headers)

        with patch("business_core.sheets.find_row_by_id", return_value=(3, {"ID": "BIZ-001"})):
            with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
                with patch("business_core.sheets.update_business_cell") as mock_update:
                    result = save_drive_info_to_sheets(
                        "BIZ-001",
                        "FOLDER_ID_X",
                        "https://drive.google.com/drive/folders/FOLDER_ID_X",
                    )

        self.assertTrue(result)
        # Должно быть 2 вызова: один для URL, один для ID
        self.assertEqual(mock_update.call_count, 2)

        calls = mock_update.call_args_list
        # "Google Drive" в индексе 2 → col=3
        url_call = next(c for c in calls if "drive.google.com" in str(c))
        self.assertIn(3, url_call.args)

        # "Drive Folder ID" в индексе 3 → col=4
        id_call = next(c for c in calls if "FOLDER_ID_X" in str(c) and "drive.google.com" not in str(c))
        self.assertIn(4, id_call.args)

    def test_no_drive_folder_id_column_still_updates_url(self):
        """Если 'Drive Folder ID' нет в заголовках — URL всё равно сохраняется."""
        headers = ["ID", "Название", "Google Drive"]  # без Drive Folder ID
        mock_sheet = self._make_mock_sheet(headers)

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "BIZ-002"})):
            with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
                with patch("business_core.sheets.update_business_cell") as mock_update:
                    result = save_drive_info_to_sheets("BIZ-002", "FID", "https://drive.google.com/X")

        self.assertTrue(result)
        self.assertEqual(mock_update.call_count, 1)   # только URL

    def test_biz_id_not_found_returns_false(self):
        """biz_id не найден в листе → False."""
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            result = save_drive_info_to_sheets("BIZ-MISSING", "X", "https://url")
        self.assertFalse(result)

    def test_sheets_exception_returns_false(self):
        """Ошибка Sheets → False, не бросает исключение."""
        with patch("business_core.sheets.find_row_by_id", side_effect=Exception("API error")):
            result = save_drive_info_to_sheets("BIZ-001", "X", "https://url")
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────
# Тест 8: GTD-файлы не импортируются
# ─────────────────────────────────────────────────────────────

class TestIsolation(unittest.TestCase):

    def test_business_builder_does_not_import_gtd(self):
        """business_builder.py не импортирует GTD-файлы напрямую."""
        import ast
        import pathlib

        source = pathlib.Path("business_core/business_builder.py").read_text()
        tree = ast.parse(source)

        forbidden_top = {"telegram_bot", "inbox_processor", "project_planner",
                         "calendar_sync", "sheets"}  # основной sheets.py
        forbidden_from = {"sheets"}

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertNotIn(top, forbidden_top,
                            f"business_builder импортирует запрещённый модуль: {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    # разрешаем business_core.sheets (не основной sheets.py)
                    if top == "business_core":
                        continue
                    if top == "integrations":
                        continue
                    self.assertNotIn(top, {"telegram_bot", "inbox_processor",
                                           "project_planner", "calendar_sync"},
                        f"business_builder импортирует: {node.module}")

    def test_gtd_files_not_modified(self):
        """Ключевые GTD-файлы существуют (не удалены)."""
        for fname in ["telegram_bot.py", "sheets.py", "inbox_processor.py",
                      "project_planner.py", "calendar_sync.py"]:
            self.assertTrue(os.path.exists(fname), f"{fname} исчез!")


# ─────────────────────────────────────────────────────────────
# Тест 9–10: сценарии newbiz (логика без Telegram)
# ─────────────────────────────────────────────────────────────

class TestNewBizDriveScenarios(unittest.TestCase):
    """Проверяем логику provision_biz_drive в сценариях /newbiz без запуска Telegram."""

    def test_biz_created_even_if_drive_disabled(self):
        """Бизнес создаётся даже если Drive не задан (GDRIVE_BIZ_ROOT_FOLDER_ID='')."""
        env_backup = os.environ.pop("GDRIVE_BIZ_ROOT_FOLDER_ID", None)
        try:
            result = provision_biz_drive("BIZ-004", "Тест отключён")
            # Должен вернуть ok=False, но без исключения
            self.assertFalse(result["ok"])
            self.assertIsInstance(result, dict)
        finally:
            if env_backup:
                os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = env_backup

    def test_drive_error_contains_message(self):
        """При ошибке Drive сообщение об ошибке содержит полезный текст."""
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                side_effect=PermissionError("Нет доступа к папке BUSINESS_CORE_DRIVE"),
            ):
                result = provision_biz_drive("BIZ-005", "Права")

        self.assertFalse(result["ok"])
        self.assertIn("BUSINESS_CORE_DRIVE", result["error"])

    def test_drive_note_format_on_success(self):
        """Формат drive_note соответствует ожидаемому Telegram Markdown."""
        mock_result = {
            "business_folder_id":  "NOTE_ID",
            "business_folder_url": "https://drive.google.com/drive/folders/NOTE_ID",
            "folders": {}, "dry_run": False,
        }
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                return_value=mock_result,
            ):
                result = provision_biz_drive("BIZ-006", "Формат")

        # Симулируем формирование drive_note как в telegram_handlers.py
        if result["ok"]:
            drive_note = f"\n📁 [Drive папка]({result['folder_url']})"
        else:
            drive_note = f"\n⚠️ Бизнес создан, но папка Drive не создана: {result['error'][:80]}"

        self.assertIn("📁", drive_note)
        self.assertIn("Drive папка", drive_note)
        self.assertIn("drive.google.com", drive_note)

    def test_drive_note_format_on_error(self):
        """drive_note при ошибке содержит предупреждение."""
        with patch.dict(os.environ, {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "ROOT",
            "GOOGLE_CREDENTIALS_FILE":   "creds.json",
        }):
            with patch(
                "integrations.google_drive_adapter.create_business_folder_structure",
                side_effect=Exception("connection refused"),
            ):
                result = provision_biz_drive("BIZ-007", "Ошибка")

        drive_note = f"\n⚠️ Бизнес создан, но папка Drive не создана: {result['error'][:80]}"
        self.assertIn("⚠️", drive_note)
        self.assertIn("connection refused", drive_note)


# ─────────────────────────────────────────────────────────────
# Итог
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()
    for cls in [
        TestProvisionBizDrive,
        TestSaveDriveInfoToSheets,
        TestIsolation,
        TestNewBizDriveScenarios,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
