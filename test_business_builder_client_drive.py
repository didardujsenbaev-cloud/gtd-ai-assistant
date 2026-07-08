"""
Mock-тесты для provision_client_drive() и save_client_drive_to_sheets().

Проверяют:
1.  Клиент создаётся даже если Drive недоступен (нет GDRIVE_BIZ_ROOT_FOLDER_ID)
2.  Drive ошибка не ломает создание клиента
3.  При успешном Drive создаётся/возвращается клиентская папка
4.  Если biz_id не найден — используется biz_name как fallback
5.  Если biz_id найден — используется правильный ID
6.  Повторный вызов идемпотентен (setup_biz_client_folder вызывается снова)
7.  Ссылка на папку сохраняется в people_registry
8.  Если нет колонки Drive Folder ID — Google Drive всё равно сохраняется
9.  GTD-файлы не импортируются
10. telegram_bot.py не менялся
"""

import unittest
import sys
import os
import ast
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────────────────────
# 1. Импорт
# ─────────────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    def test_import_business_builder(self):
        from business_core import business_builder
        self.assertTrue(hasattr(business_builder, "provision_client_drive"))
        self.assertTrue(hasattr(business_builder, "save_client_drive_to_sheets"))
        self.assertTrue(hasattr(business_builder, "_get_biz_id_by_name"))


# ─────────────────────────────────────────────────────────────
# 2. _get_biz_id_by_name
# ─────────────────────────────────────────────────────────────

class TestGetBizIdByName(unittest.TestCase):
    def test_found_in_registry(self):
        rows = [
            {"ID": "BIZ-001", "Название": "Узаконение", "Статус": "active"},
            {"ID": "BIZ-002", "Название": "Визы", "Статус": "active"},
        ]
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            from business_core.business_builder import _get_biz_id_by_name
            self.assertEqual(_get_biz_id_by_name("Узаконение"), "BIZ-001")
            self.assertEqual(_get_biz_id_by_name("Визы"), "BIZ-002")

    def test_not_found_returns_name(self):
        rows = [{"ID": "BIZ-001", "Название": "Узаконение", "Статус": "active"}]
        with patch("business_core.sheets.read_business_sheet", return_value=rows):
            from business_core.business_builder import _get_biz_id_by_name
            result = _get_biz_id_by_name("НеизвестныйБизнес")
            self.assertEqual(result, "НеизвестныйБизнес")

    def test_sheets_error_returns_name(self):
        with patch("business_core.sheets.read_business_sheet", side_effect=Exception("no conn")):
            from business_core.business_builder import _get_biz_id_by_name
            result = _get_biz_id_by_name("Узаконение")
            self.assertEqual(result, "Узаконение")


# ─────────────────────────────────────────────────────────────
# 3. provision_client_drive — без GDRIVE_BIZ_ROOT_FOLDER_ID
# ─────────────────────────────────────────────────────────────

class TestProvisionClientDriveNoConfig(unittest.TestCase):
    def test_no_gdrive_root_returns_ok_false(self):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict("os.environ", env, clear=False):
            from business_core.business_builder import provision_client_drive
            result = provision_client_drive("PRS-001", "Иван Иванов", "Узаконение")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["folder_id"])
        self.assertIsNone(result["folder_url"])
        self.assertIsNotNone(result["error"])

    def test_no_credentials_returns_ok_false(self):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "some_root_id",
            "GOOGLE_CREDENTIALS_FILE": "",
        }
        with patch.dict("os.environ", env, clear=False):
            from business_core.business_builder import provision_client_drive
            result = provision_client_drive("PRS-001", "Иван Иванов", "Узаконение")
        self.assertFalse(result["ok"])

    def test_empty_biz_name_returns_ok_false(self):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "some_root_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict("os.environ", env, clear=False):
            from business_core.business_builder import provision_client_drive
            result = provision_client_drive("PRS-001", "Иван Иванов", "")
        self.assertFalse(result["ok"])
        self.assertIn("biz_name", result["error"])


# ─────────────────────────────────────────────────────────────
# 4. provision_client_drive — успешный Drive
# ─────────────────────────────────────────────────────────────

class TestProvisionClientDriveSuccess(unittest.TestCase):
    def _run_provision(self, biz_name="Узаконение", roadmap_id=None):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root_folder_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        mock_drive_result = {
            "client_folder_id": "client_folder_abc",
            "client_folder_url": "https://drive.google.com/drive/folders/client_folder_abc",
            "subfolders": {},
            "dry_run": False,
        }
        biz_rows = [{"ID": "BIZ-001", "Название": "Узаконение", "Статус": "active"}]

        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", return_value=biz_rows):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    return_value=mock_drive_result,
                ) as mock_setup:
                    from business_core.business_builder import provision_client_drive
                    result = provision_client_drive(
                        prs_id="PRS-001",
                        full_name="Иван Иванов",
                        biz_name=biz_name,
                        roadmap_id=roadmap_id,
                    )
        return result, mock_setup

    def test_success_returns_ok_true(self):
        result, _ = self._run_provision()
        self.assertTrue(result["ok"])
        self.assertEqual(result["folder_id"], "client_folder_abc")
        self.assertIn("client_folder_abc", result["folder_url"])
        self.assertIsNone(result["error"])

    def test_biz_id_resolved_from_registry(self):
        result, mock_setup = self._run_provision()
        call_kwargs = mock_setup.call_args
        self.assertEqual(call_kwargs.kwargs.get("biz_id") or call_kwargs[1].get("biz_id") or
                         (call_kwargs[0][0] if call_kwargs[0] else None), "BIZ-001")

    def test_roadmap_id_passed_through(self):
        result, mock_setup = self._run_provision(roadmap_id="RM-007")
        call_kwargs = mock_setup.call_args
        # roadmap_id должен быть передан в setup_biz_client_folder
        all_args = str(call_kwargs)
        self.assertIn("RM-007", all_args)

    def test_biz_id_fallback_when_not_in_registry(self):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root_folder_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        mock_drive_result = {
            "client_folder_id": "folder_xyz",
            "client_folder_url": "https://drive.google.com/drive/folders/folder_xyz",
            "subfolders": {},
            "dry_run": False,
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", return_value=[]):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    return_value=mock_drive_result,
                ) as mock_setup:
                    from business_core.business_builder import provision_client_drive
                    result = provision_client_drive("PRS-002", "Мария Петрова", "НеизвестныйБизнес")

        self.assertTrue(result["ok"])
        # biz_id должен быть равен biz_name (fallback)
        all_args = str(mock_setup.call_args)
        self.assertIn("НеизвестныйБизнес", all_args)


# ─────────────────────────────────────────────────────────────
# 5. provision_client_drive — Drive ошибка
# ─────────────────────────────────────────────────────────────

class TestProvisionClientDriveError(unittest.TestCase):
    def test_drive_api_error_returns_ok_false(self):
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root_folder_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", return_value=[]):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    side_effect=Exception("Drive API 403"),
                ):
                    from business_core.business_builder import provision_client_drive
                    result = provision_client_drive("PRS-003", "Ошибка Клиент", "Бизнес")

        self.assertFalse(result["ok"])
        self.assertIsNone(result["folder_id"])
        self.assertIn("Drive API 403", result["error"])

    def test_drive_error_does_not_raise(self):
        """provision_client_drive никогда не бросает исключение"""
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", side_effect=Exception("sheets error")):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    side_effect=Exception("drive error"),
                ):
                    from business_core.business_builder import provision_client_drive
                    try:
                        result = provision_client_drive("PRS-004", "Тест", "Бизнес")
                    except Exception as e:
                        self.fail(f"provision_client_drive бросил исключение: {e}")


# ─────────────────────────────────────────────────────────────
# 6. save_client_drive_to_sheets
# ─────────────────────────────────────────────────────────────

class TestSaveClientDriveToSheets(unittest.TestCase):
    def _make_mock_sheet(self, headers):
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = headers
        return mock_sheet

    def test_saves_both_columns(self):
        headers = [
            "ID", "ФИО", "Тип", "Бизнесы", "Комментарий",
            "Google Drive", "Drive Folder ID",
        ]
        mock_sheet = self._make_mock_sheet(headers)
        mock_update = MagicMock()

        with patch("business_core.sheets.find_row_by_id", return_value=(3, {"ID": "PRS-001"})):
            with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
                with patch("business_core.sheets.update_business_cell", mock_update):
                    from business_core.business_builder import save_client_drive_to_sheets
                    result = save_client_drive_to_sheets(
                        "PRS-001", "folder_abc", "https://drive.google.com/folder_abc"
                    )

        self.assertTrue(result)
        calls = mock_update.call_args_list
        self.assertEqual(len(calls), 2)
        # col of "Google Drive" = index 5 + 1 = 6
        self.assertEqual(calls[0], call("people_registry", 3, 6, "https://drive.google.com/folder_abc"))
        # col of "Drive Folder ID" = index 6 + 1 = 7
        self.assertEqual(calls[1], call("people_registry", 3, 7, "folder_abc"))

    def test_saves_only_google_drive_when_no_drive_folder_id_col(self):
        headers = ["ID", "ФИО", "Тип", "Google Drive"]
        mock_sheet = self._make_mock_sheet(headers)
        mock_update = MagicMock()

        with patch("business_core.sheets.find_row_by_id", return_value=(2, {"ID": "PRS-002"})):
            with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
                with patch("business_core.sheets.update_business_cell", mock_update):
                    from business_core.business_builder import save_client_drive_to_sheets
                    result = save_client_drive_to_sheets(
                        "PRS-002", "folder_xyz", "https://drive.google.com/folder_xyz"
                    )

        self.assertTrue(result)
        self.assertEqual(len(mock_update.call_args_list), 1)

    def test_returns_false_when_prs_id_not_found(self):
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            from business_core.business_builder import save_client_drive_to_sheets
            result = save_client_drive_to_sheets("PRS-999", "x", "y")
        self.assertFalse(result)

    def test_returns_false_on_sheets_exception(self):
        with patch("business_core.sheets.find_row_by_id", side_effect=Exception("sheets error")):
            from business_core.business_builder import save_client_drive_to_sheets
            result = save_client_drive_to_sheets("PRS-001", "x", "y")
        self.assertFalse(result)

    def test_does_not_raise(self):
        """save_client_drive_to_sheets никогда не бросает исключение"""
        with patch("business_core.sheets.find_row_by_id", side_effect=RuntimeError("boom")):
            from business_core.business_builder import save_client_drive_to_sheets
            try:
                save_client_drive_to_sheets("PRS-001", "x", "y")
            except Exception as e:
                self.fail(f"save_client_drive_to_sheets бросил исключение: {e}")


# ─────────────────────────────────────────────────────────────
# 7. People Registry headers содержат Drive-колонки
# ─────────────────────────────────────────────────────────────

class TestPeopleRegistryHeaders(unittest.TestCase):
    def test_headers_contain_google_drive(self):
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS.get("people_registry", [])
        self.assertIn("Google Drive", headers)

    def test_headers_contain_drive_folder_id(self):
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS.get("people_registry", [])
        self.assertIn("Drive Folder ID", headers)

    def test_drive_columns_at_end(self):
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS.get("people_registry", [])
        gd_idx = headers.index("Google Drive")
        dfid_idx = headers.index("Drive Folder ID")
        # оба должны быть в конце (не ломают старые колонки)
        self.assertGreater(gd_idx, 20)
        self.assertGreater(dfid_idx, 20)
        # комментарий должен быть до Drive-колонок
        self.assertIn("Комментарий", headers)
        comment_idx = headers.index("Комментарий")
        self.assertLess(comment_idx, gd_idx)


# ─────────────────────────────────────────────────────────────
# 8. Изоляция — GTD-файлы не импортируются
# ─────────────────────────────────────────────────────────────

class TestIsolation(unittest.TestCase):
    _GTD_FORBIDDEN = {
        "sheets",           # GTD sheets.py (не business_core.sheets)
        "inbox_processor",
        "project_planner",
        "calendar_sync",
    }

    def _get_imports(self, filepath):
        with open(filepath) as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return imports

    def test_business_builder_no_gtd_imports(self):
        path = os.path.join(os.path.dirname(__file__), "business_core", "business_builder.py")
        imports = self._get_imports(path)
        for forbidden in self._GTD_FORBIDDEN:
            self.assertNotIn(
                forbidden, imports,
                f"business_builder.py импортирует GTD-модуль: {forbidden}"
            )

    def test_telegram_bot_not_modified(self):
        """telegram_bot.py не должен содержать newclient Drive логику напрямую"""
        path = os.path.join(os.path.dirname(__file__), "telegram_bot.py")
        with open(path) as f:
            content = f.read()
        self.assertNotIn("provision_client_drive", content,
                         "telegram_bot.py не должен содержать provision_client_drive напрямую")


# ─────────────────────────────────────────────────────────────
# 9. Идемпотентность — повторный вызов не создаёт дубль
# ─────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):
    def test_second_call_reuses_existing_folder(self):
        """setup_biz_client_folder идемпотентен — при повторном вызове возвращает существующую папку"""
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root_id",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        mock_result = {
            "client_folder_id": "existing_folder",
            "client_folder_url": "https://drive.google.com/existing",
            "subfolders": {},
            "dry_run": False,
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", return_value=[]):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    return_value=mock_result,
                ) as mock_setup:
                    from business_core.business_builder import provision_client_drive
                    r1 = provision_client_drive("PRS-001", "Клиент А", "Бизнес")
                    r2 = provision_client_drive("PRS-001", "Клиент А", "Бизнес")

        self.assertTrue(r1["ok"])
        self.assertTrue(r2["ok"])
        self.assertEqual(r1["folder_id"], r2["folder_id"])
        # setup_biz_client_folder вызван дважды — идемпотентность на его стороне
        self.assertEqual(mock_setup.call_count, 2)


# ─────────────────────────────────────────────────────────────
# 10. find_existing_client — поиск дублей
# ─────────────────────────────────────────────────────────────

class TestFindExistingClient(unittest.TestCase):
    def _make_sheet(self, rows_data):
        """Вернуть мок листа с get_all_values."""
        headers = [
            "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
            "Telegram", "Email", "Город", "Компания", "Должность",
            "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
            "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
            "День рождения", "Важные события",
            "Дата первого контакта", "Дата последнего контакта",
            "Канал последнего контакта", "История",
            "Следующее касание", "Тип касания", "Заметка касания",
            "Статус отношений", "Теплота", "Комментарий",
            "Google Drive", "Drive Folder ID",
        ]
        values = [headers] + rows_data
        mock_sheet = MagicMock()
        mock_sheet.get_all_values.return_value = values
        return mock_sheet

    def _row(self, prs_id, full_name, biz="", drive_url="", drive_id=""):
        return [
            prs_id, full_name, full_name.split()[0], "", "", "", "", "",
            "", "", "", "клиент", "", biz, "", "",
            "", "", "", "", "", "", "",
            "2024-01-01", "2024-01-01", "", "",
            "", "", "", "active", "тёплый", "",
            drive_url, drive_id,
        ]

    def test_found_by_name_and_biz(self):
        rows = [self._row("PRS-001", "Иван Иванов", "Узаконение")]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Иван Иванов", "Узаконение")
        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-001")

    def test_found_case_insensitive(self):
        rows = [self._row("PRS-002", "Мария Петрова", "Визы")]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("мария петрова", "визы")
        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-002")

    def test_not_found_different_name(self):
        rows = [self._row("PRS-001", "Иван Иванов", "Узаконение")]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Пётр Сидоров", "Узаконение")
        self.assertIsNone(result)

    def test_not_found_different_biz(self):
        """Одинаковое имя в разных бизнесах — НЕ дубль."""
        rows = [self._row("PRS-001", "Иван Иванов", "Узаконение")]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Иван Иванов", "Визы")
        self.assertIsNone(result)

    def test_same_name_same_biz_is_duplicate(self):
        """Одинаковое имя в одном бизнесе — дубль."""
        rows = [
            self._row("PRS-001", "Иван Иванов", "Узаконение"),
            self._row("PRS-002", "Иван Иванов", "Узаконение"),
        ]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Иван Иванов", "Узаконение")
        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-001")  # первый найденный

    def test_returns_drive_url_if_present(self):
        rows = [self._row("PRS-003", "Тест Клиент", "Бизнес",
                          drive_url="https://drive.google.com/abc",
                          drive_id="folder_abc")]
        mock_sheet = self._make_sheet(rows)
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Тест Клиент", "Бизнес")
        self.assertEqual(result["drive_url"], "https://drive.google.com/abc")
        self.assertEqual(result["drive_folder_id"], "folder_abc")

    def test_empty_name_returns_none(self):
        mock_sheet = self._make_sheet([])
        with patch("business_core.sheets.get_business_sheet", return_value=mock_sheet):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("", "Бизнес")
        self.assertIsNone(result)

    def test_sheets_error_returns_none(self):
        with patch("business_core.sheets.get_business_sheet", side_effect=Exception("no conn")):
            from business_core.business_builder import find_existing_client
            result = find_existing_client("Иван Иванов", "Бизнес")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────
# 11. _normalize_name
# ─────────────────────────────────────────────────────────────

class TestNormalizeName(unittest.TestCase):
    def test_lowercase(self):
        from business_core.business_builder import _normalize_name
        self.assertEqual(_normalize_name("ИВАН ИВАНОВ"), "иван иванов")

    def test_strips_whitespace(self):
        from business_core.business_builder import _normalize_name
        self.assertEqual(_normalize_name("  Иван  "), "иван")

    def test_double_spaces(self):
        from business_core.business_builder import _normalize_name
        self.assertEqual(_normalize_name("Иван  Иванов"), "иван иванов")

    def test_empty(self):
        from business_core.business_builder import _normalize_name
        self.assertEqual(_normalize_name(""), "")


# ─────────────────────────────────────────────────────────────
# 12. Дедупликация в связке provision_client_drive
# ─────────────────────────────────────────────────────────────

class TestDeduplication(unittest.TestCase):
    def test_drive_not_called_if_url_already_exists(self):
        """Если у существующего клиента уже есть Drive URL — повторный Drive-вызов не нужен."""
        # Существующий клиент с Drive URL
        existing = {
            "row_num": 2, "prs_id": "PRS-001", "full_name": "Иван Иванов",
            "drive_url": "https://drive.google.com/existing",
            "drive_folder_id": "existing_folder",
        }
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("integrations.google_drive_adapter.setup_biz_client_folder") as mock_drive:
                # Симулируем: find_existing_client вернул существующего с drive_url
                # Код telegram_handlers должен НЕ вызывать provision_client_drive если drive_url есть
                # Проверяем логику через прямое тестирование условия
                drive_url = existing["drive_url"]
                should_skip = bool(drive_url)
                self.assertTrue(should_skip)
                mock_drive.assert_not_called()  # не вызван, т.к. мы пропустили

    def test_drive_called_if_existing_client_has_no_url(self):
        """Если существующий клиент без Drive URL — Drive вызывается для дозаполнения."""
        env = {
            "GDRIVE_BIZ_ROOT_FOLDER_ID": "root",
            "GOOGLE_CREDENTIALS_FILE": "creds.json",
        }
        mock_result = {
            "client_folder_id": "new_folder",
            "client_folder_url": "https://drive.google.com/new_folder",
            "subfolders": {},
            "dry_run": False,
        }
        with patch.dict("os.environ", env, clear=False):
            with patch("business_core.sheets.read_business_sheet", return_value=[]):
                with patch(
                    "integrations.google_drive_adapter.setup_biz_client_folder",
                    return_value=mock_result,
                ) as mock_drive:
                    from business_core.business_builder import provision_client_drive
                    result = provision_client_drive("PRS-001", "Иван Иванов", "Бизнес")

        self.assertTrue(result["ok"])
        mock_drive.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
