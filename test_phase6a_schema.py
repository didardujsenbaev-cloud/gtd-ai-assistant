"""
Phase 6A: Multi-Business Config Schema — mock tests.

Проверяет:
- BIZ_REGISTRY содержит новые колонки (Phase 6A)
- PEOPLE_REGISTRY содержит новые колонки (Phase 6A)
- OBJECT_REGISTRY создаётся с правильными заголовками
- ROADMAPS содержит Object ID / Parent Roadmap ID / Case Type
- get_business_config работает со старыми и новыми данными
- get_business_drive_root_id: per-biz root, fallback на .env
- get_business_model_type: правильные значения
- get_person_biz_ids: новое поле и fallback
- normalize_biz_ids: разные форматы
- GTD-файлы не импортируются
"""

import os
import sys
import ast
import unittest
from unittest.mock import MagicMock, patch

# ─── helpers ────────────────────────────────────────────────────────────────

def _all_imports(filepath: str) -> set[str]:
    """Возвращает множество топ-уровневых модулей, используемых в файле."""
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


GTD_FORBIDDEN = {
    "inbox_processor",
    "project_planner",
    "calendar_sync",
    "telegram_bot",
}


class TestGTDIsolation(unittest.TestCase):
    """GTD-файлы не должны импортироваться в Business Core."""

    def _check_file(self, path: str):
        imports = _all_imports(path)
        bad = imports & GTD_FORBIDDEN
        self.assertFalse(bad, f"{path} импортирует GTD-модули: {bad}")

    def test_sheets_no_gtd(self):
        self._check_file("business_core/sheets.py")

    def test_business_builder_no_gtd(self):
        self._check_file("business_core/business_builder.py")

    def test_telegram_handlers_no_gtd(self):
        self._check_file("business_core/telegram_handlers.py")

    def test_google_drive_adapter_no_gtd(self):
        self._check_file("integrations/google_drive_adapter.py")


# ─── Schema headers ─────────────────────────────────────────────────────────

class TestSheetsHeaders(unittest.TestCase):
    """BUSINESS_HEADERS содержат нужные Phase-6A колонки."""

    def _headers(self, key: str) -> list[str]:
        from business_core.sheets import BUSINESS_HEADERS
        return BUSINESS_HEADERS[key]

    def test_biz_registry_new_columns(self):
        headers = self._headers("biz_registry")
        for col in ["Drive Root ID", "Drive Credentials", "Google Account Email",
                    "Cities JSON", "Default City", "Business Model Type"]:
            self.assertIn(col, headers, f"BIZ_REGISTRY missing: {col}")

    def test_biz_registry_old_columns_intact(self):
        headers = self._headers("biz_registry")
        for col in ["ID", "Название", "Slug", "Статус", "Drive Folder ID"]:
            self.assertIn(col, headers, f"BIZ_REGISTRY broken: {col}")

    def test_people_registry_new_columns(self):
        headers = self._headers("people_registry")
        for col in ["Biz IDs", "Company ID", "Citizenship", "Passport / ID", "Primary Biz ID"]:
            self.assertIn(col, headers, f"PEOPLE_REGISTRY missing: {col}")

    def test_people_registry_old_biznes_intact(self):
        headers = self._headers("people_registry")
        self.assertIn("Бизнесы", headers, "Старое поле 'Бизнесы' удалено — нельзя!")

    def test_people_registry_old_drive_intact(self):
        headers = self._headers("people_registry")
        for col in ["Google Drive", "Drive Folder ID"]:
            self.assertIn(col, headers, f"PEOPLE_REGISTRY broken: {col}")

    def test_object_registry_headers(self):
        headers = self._headers("object_registry")
        expected = [
            "OBJ ID", "Client ID", "Biz ID", "City",
            "Address", "Cadastral Number", "Area m2",
            "Object Type", "Object Status",
            "Current Service ID", "Roadmap ID",
            "Drive Folder ID", "Google Drive",
            "Notes", "Created At", "Last Updated",
        ]
        for col in expected:
            self.assertIn(col, headers, f"OBJECT_REGISTRY missing: {col}")

    def test_roadmaps_new_columns(self):
        headers = self._headers("roadmaps")
        for col in ["Object ID", "Parent Roadmap ID", "Case Type"]:
            self.assertIn(col, headers, f"ROADMAPS missing: {col}")

    def test_roadmaps_old_columns_intact(self):
        headers = self._headers("roadmaps")
        for col in ["Roadmap ID", "Business ID", "Client ID", "Status"]:
            self.assertIn(col, headers, f"ROADMAPS broken: {col}")

    def test_sheet_names_include_object_registry(self):
        from business_core.sheets import BUSINESS_SHEET_NAMES
        self.assertIn("object_registry", BUSINESS_SHEET_NAMES)
        self.assertEqual(BUSINESS_SHEET_NAMES["object_registry"], "OBJECT_REGISTRY")

    def test_id_prefixes_include_obj(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertIn("object_registry", _ID_PREFIXES)
        self.assertEqual(_ID_PREFIXES["object_registry"], "OBJ")


# ─── normalize_biz_ids ──────────────────────────────────────────────────────

class TestNormalizeBizIds(unittest.TestCase):

    def _fn(self):
        from business_core.business_builder import normalize_biz_ids
        return normalize_biz_ids

    def test_single(self):
        self.assertEqual(self._fn()("BIZ-001"), ["BIZ-001"])

    def test_multiple_comma(self):
        self.assertEqual(self._fn()("BIZ-001, BIZ-002"), ["BIZ-001", "BIZ-002"])

    def test_multiple_semicolon(self):
        self.assertEqual(self._fn()("BIZ-001; BIZ-003"), ["BIZ-001", "BIZ-003"])

    def test_empty(self):
        self.assertEqual(self._fn()(""), [])

    def test_whitespace_only(self):
        self.assertEqual(self._fn()("   "), [])

    def test_no_crash_on_none_like_empty(self):
        self.assertEqual(self._fn()(""), [])


# ─── get_business_config ────────────────────────────────────────────────────

class TestGetBusinessConfig(unittest.TestCase):
    """get_business_config — безопасная, работает со старыми и новыми колонками."""

    def _make_mock_sheet(self, headers: list, row: list):
        """Мок Google Sheets worksheet."""
        mock = MagicMock()
        mock.get_all_values.return_value = [headers, row]
        return mock

    @patch("business_core.sheets.get_business_sheet")
    def test_with_new_columns(self, mock_get_sheet):
        headers = [
            "ID", "Название", "Slug", "Статус", "Описание", "Города",
            "Drive Folder ID", "Drive Root ID", "Drive Credentials",
            "Google Account Email", "Cities JSON", "Default City", "Business Model Type",
        ]
        row = [
            "BIZ-001", "Узаконение", "uzak", "active", "Недвижимость", "Алматы,Астана",
            "folder-123", "root-456", "uzak_creds",
            "uzak@gmail.com", '["Алматы","Астана"]', "Алматы", "object_based",
        ]
        mock_get_sheet.return_value = self._make_mock_sheet(headers, row)

        from business_core.business_builder import get_business_config
        cfg = get_business_config("BIZ-001")

        self.assertTrue(cfg["found"])
        self.assertEqual(cfg["id"], "BIZ-001")
        self.assertEqual(cfg["business_model_type"], "object_based")
        self.assertEqual(cfg["drive_root_id"], "root-456")
        self.assertEqual(cfg["google_account_email"], "uzak@gmail.com")
        self.assertIn("Алматы", cfg["cities"])

    @patch("business_core.sheets.get_business_sheet")
    def test_without_new_columns(self, mock_get_sheet):
        """Старые данные без Phase-6A колонок — должен вернуть дефолты."""
        headers = ["ID", "Название", "Статус", "Города"]
        row     = ["BIZ-001", "Узаконение", "active", "Алматы"]
        mock_get_sheet.return_value = self._make_mock_sheet(headers, row)

        from business_core.business_builder import get_business_config
        cfg = get_business_config("BIZ-001")

        self.assertTrue(cfg["found"])
        self.assertEqual(cfg["business_model_type"], "general")  # дефолт
        self.assertEqual(cfg["drive_root_id"], "")
        self.assertIn("Алматы", cfg["cities"])

    @patch("business_core.sheets.get_business_sheet")
    def test_not_found(self, mock_get_sheet):
        headers = ["ID", "Название"]
        row     = ["BIZ-999", "Другой"]
        mock_get_sheet.return_value = self._make_mock_sheet(headers, row)

        from business_core.business_builder import get_business_config
        cfg = get_business_config("BIZ-001")

        self.assertFalse(cfg["found"])
        self.assertEqual(cfg["business_model_type"], "general")

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_no_crash(self, mock_get_sheet):
        mock_get_sheet.side_effect = Exception("Sheets API down")

        from business_core.business_builder import get_business_config
        cfg = get_business_config("BIZ-001")

        self.assertFalse(cfg["found"])
        self.assertIsNotNone(cfg)


# ─── get_business_drive_root_id ─────────────────────────────────────────────

class TestGetBusinessDriveRootId(unittest.TestCase):

    @patch("business_core.business_builder.get_business_config")
    def test_per_biz_root_takes_priority(self, mock_cfg):
        mock_cfg.return_value = {"drive_root_id": "per-biz-root-789", "found": True}
        from business_core.business_builder import get_business_drive_root_id
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "global-root-123"}):
            result = get_business_drive_root_id("BIZ-001")
        self.assertEqual(result, "per-biz-root-789")

    @patch("business_core.business_builder.get_business_config")
    def test_fallback_to_env(self, mock_cfg):
        mock_cfg.return_value = {"drive_root_id": "", "found": True}
        from business_core.business_builder import get_business_drive_root_id
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "global-root-123"}):
            result = get_business_drive_root_id("BIZ-001")
        self.assertEqual(result, "global-root-123")

    @patch("business_core.business_builder.get_business_config")
    def test_empty_if_no_root(self, mock_cfg):
        mock_cfg.return_value = {"drive_root_id": "", "found": False}
        from business_core.business_builder import get_business_drive_root_id
        env = {k: v for k, v in os.environ.items() if k != "GDRIVE_BIZ_ROOT_FOLDER_ID"}
        with patch.dict(os.environ, env, clear=True):
            result = get_business_drive_root_id("BIZ-001")
        self.assertEqual(result, "")


# ─── get_business_model_type ────────────────────────────────────────────────

class TestGetBusinessModelType(unittest.TestCase):

    @patch("business_core.business_builder.get_business_config")
    def test_object_based(self, mock_cfg):
        mock_cfg.return_value = {"business_model_type": "object_based", "found": True}
        from business_core.business_builder import get_business_model_type
        self.assertEqual(get_business_model_type("BIZ-001"), "object_based")

    @patch("business_core.business_builder.get_business_config")
    def test_person_case_based(self, mock_cfg):
        mock_cfg.return_value = {"business_model_type": "person_case_based", "found": True}
        from business_core.business_builder import get_business_model_type
        self.assertEqual(get_business_model_type("BIZ-002"), "person_case_based")

    @patch("business_core.business_builder.get_business_config")
    def test_unknown_type_becomes_general(self, mock_cfg):
        mock_cfg.return_value = {"business_model_type": "some_random_type", "found": True}
        from business_core.business_builder import get_business_model_type
        self.assertEqual(get_business_model_type("BIZ-001"), "general")

    @patch("business_core.business_builder.get_business_config")
    def test_default_is_general(self, mock_cfg):
        mock_cfg.return_value = {"business_model_type": "", "found": False}
        from business_core.business_builder import get_business_model_type
        self.assertEqual(get_business_model_type("BIZ-999"), "general")


# ─── get_person_biz_ids ─────────────────────────────────────────────────────

class TestGetPersonBizIds(unittest.TestCase):

    def _make_mock(self, headers: list, rows: list):
        mock = MagicMock()
        mock.get_all_values.return_value = [headers] + rows
        return mock

    @patch("business_core.sheets.get_business_sheet")
    def test_new_biz_ids_field(self, mock_get):
        headers = ["ID", "ФИО", "Бизнесы", "Biz IDs", "Primary Biz ID"]
        rows    = [["PRS-001", "Иван", "Узаконение", "BIZ-001,BIZ-002", "BIZ-001"]]
        mock_get.return_value = self._make_mock(headers, rows)

        from business_core.business_builder import get_person_biz_ids
        result = get_person_biz_ids("PRS-001")
        self.assertEqual(result, ["BIZ-001", "BIZ-002"])

    @patch("business_core.sheets.get_business_sheet")
    @patch("business_core.business_builder._get_biz_id_by_name")
    def test_fallback_to_old_field(self, mock_biz_id, mock_get):
        headers = ["ID", "ФИО", "Бизнесы"]
        rows    = [["PRS-001", "Иван", "Узаконение"]]
        mock_get.return_value = self._make_mock(headers, rows)
        mock_biz_id.return_value = "BIZ-001"

        from business_core.business_builder import get_person_biz_ids
        result = get_person_biz_ids("PRS-001")
        self.assertIn("BIZ-001", result)

    @patch("business_core.sheets.get_business_sheet")
    def test_person_not_found(self, mock_get):
        headers = ["ID", "ФИО", "Biz IDs"]
        rows    = [["PRS-999", "Другой", "BIZ-003"]]
        mock_get.return_value = self._make_mock(headers, rows)

        from business_core.business_builder import get_person_biz_ids
        result = get_person_biz_ids("PRS-001")
        self.assertEqual(result, [])

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("timeout")

        from business_core.business_builder import get_person_biz_ids
        result = get_person_biz_ids("PRS-001")
        self.assertEqual(result, [])


# ─── Drive Adapter: root_folder_id ──────────────────────────────────────────

class TestDriveAdapterExplicitRoot(unittest.TestCase):
    """create_business_folder_structure принимает explicit root_folder_id."""

    def test_signature_accepts_root_folder_id(self):
        import inspect
        from integrations.google_drive_adapter import create_business_folder_structure
        sig = inspect.signature(create_business_folder_structure)
        self.assertIn("root_folder_id", sig.parameters)

    def test_setup_biz_client_folder_accepts_root_folder_id(self):
        import inspect
        from integrations.google_drive_adapter import setup_biz_client_folder
        sig = inspect.signature(setup_biz_client_folder)
        self.assertIn("root_folder_id", sig.parameters)

    @patch("integrations.google_drive_adapter.get_drive_service")
    @patch("integrations.google_drive_adapter.create_business_structure")
    def test_explicit_root_used_over_env(self, mock_create, mock_service):
        mock_create.return_value = {
            "root_id": "biz-folder-xyz", "root_url": "https://drive.google.com/xyz",
            "subfolders": {},
        }
        from integrations.google_drive_adapter import create_business_folder_structure
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "env-global-root"}):
            result = create_business_folder_structure(
                biz_id="BIZ-TEST",
                biz_name="Test",
                root_folder_id="explicit-root-111",
            )
        # create_business_structure должен быть вызван с parent_folder_id = explicit-root-111
        called_kwargs = mock_create.call_args[1]
        self.assertEqual(called_kwargs.get("parent_folder_id", mock_create.call_args[0][1] if len(mock_create.call_args[0]) > 1 else ""), "explicit-root-111")


# ─── provision_biz_drive: per-biz root ──────────────────────────────────────

class TestProvisionBizDrivePerBizRoot(unittest.TestCase):

    @patch("business_core.business_builder.get_business_drive_root_id")
    @patch("integrations.google_drive_adapter.create_business_folder_structure")
    def test_uses_per_biz_root(self, mock_drive, mock_root_id):
        mock_root_id.return_value = "per-biz-root-999"
        mock_drive.return_value = {
            "business_folder_id": "biz-folder-1",
            "business_folder_url": "https://drive.google.com/biz1",
            "folders": {},
        }
        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-001", "Узаконение")

        self.assertTrue(result["ok"])
        # root_folder_id должен быть передан в create_business_folder_structure
        call_kwargs = mock_drive.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "per-biz-root-999")

    @patch("business_core.business_builder.get_business_drive_root_id")
    def test_no_root_returns_not_ok(self, mock_root_id):
        mock_root_id.return_value = ""
        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-001", "Узаконение")
        self.assertFalse(result["ok"])


# ─── Constants ──────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_business_model_types(self):
        from business_core.business_builder import BUSINESS_MODEL_TYPES
        self.assertIn("object_based", BUSINESS_MODEL_TYPES)
        self.assertIn("person_case_based", BUSINESS_MODEL_TYPES)
        self.assertIn("program_based", BUSINESS_MODEL_TYPES)
        self.assertIn("general", BUSINESS_MODEL_TYPES)

    def test_roadmap_case_types(self):
        from business_core.business_builder import ROADMAP_CASE_TYPES
        self.assertIn("legalization_object", ROADMAP_CASE_TYPES)
        self.assertIn("visa_foreigner", ROADMAP_CASE_TYPES)
        self.assertIn("coaching_program", ROADMAP_CASE_TYPES)
        self.assertIn("general", ROADMAP_CASE_TYPES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
