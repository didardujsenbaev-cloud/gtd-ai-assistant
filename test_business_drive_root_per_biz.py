"""
Phase 6C: Per-Business Drive Roots — mock tests.

Проверяет:
1. resolve_drive_root_for_business: источник biz_registry > env > none
2. get_business_drive_root_id: per-biz root > env fallback > ""
3. provision_biz_drive: ok=False без исключения если нет root
4. provision_biz_drive: per-biz root передаётся в Drive Adapter
5. provision_client_drive: per-biz root передаётся в Drive Adapter
6. Бизнес-папка создаётся внутри правильного root
7. Клиентская папка создаётся внутри правильного root
8. GTD-файлы не импортируются и не меняются
"""

import ast
import os
import unittest
from unittest.mock import MagicMock, patch, call

# ─── GTD isolation ──────────────────────────────────────────────────────────

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


def _top_imports(filepath: str) -> set:
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


class TestGTDIsolation(unittest.TestCase):
    def test_business_builder_no_gtd(self):
        bad = _top_imports("business_core/business_builder.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"business_builder импортирует GTD: {bad}")

    def test_google_drive_adapter_no_gtd(self):
        bad = _top_imports("integrations/google_drive_adapter.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"google_drive_adapter импортирует GTD: {bad}")


# ─── resolve_drive_root_for_business ────────────────────────────────────────

class TestResolveDriveRoot(unittest.TestCase):

    @patch("business_core.business_builder.get_business_config")
    def test_per_biz_root_from_registry(self, mock_cfg):
        """Если BIZ_REGISTRY.Drive Root ID заполнен — source=biz_registry."""
        mock_cfg.return_value = {"drive_root_id": "biz-root-ABC", "found": True}

        from business_core.business_builder import resolve_drive_root_for_business
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "env-root-XYZ"}):
            result = resolve_drive_root_for_business("BIZ-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["root_id"], "biz-root-ABC")
        self.assertEqual(result["source"], "biz_registry")

    @patch("business_core.business_builder.get_business_config")
    def test_fallback_to_env(self, mock_cfg):
        """Если Drive Root ID пустой — fallback на .env, source=env."""
        mock_cfg.return_value = {"drive_root_id": "", "found": True}

        from business_core.business_builder import resolve_drive_root_for_business
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "env-root-XYZ"}):
            result = resolve_drive_root_for_business("BIZ-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["root_id"], "env-root-XYZ")
        self.assertEqual(result["source"], "env")

    @patch("business_core.business_builder.get_business_config")
    def test_no_root_ok_false(self, mock_cfg):
        """Нет ни biz root, ни env root — ok=False, нет исключения."""
        mock_cfg.return_value = {"drive_root_id": "", "found": False}

        from business_core.business_builder import resolve_drive_root_for_business
        env = {k: v for k, v in os.environ.items() if k != "GDRIVE_BIZ_ROOT_FOLDER_ID"}
        with patch.dict(os.environ, env, clear=True):
            result = resolve_drive_root_for_business("BIZ-001")

        self.assertFalse(result["ok"])
        self.assertEqual(result["root_id"], "")
        self.assertEqual(result["source"], "none")
        self.assertIsNotNone(result["error"])

    @patch("business_core.business_builder.get_business_config")
    def test_registry_error_falls_back_to_env(self, mock_cfg):
        """Ошибка при чтении BIZ_REGISTRY — fallback на .env без исключения."""
        mock_cfg.side_effect = Exception("Sheets timeout")

        from business_core.business_builder import resolve_drive_root_for_business
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "env-root-fallback"}):
            result = resolve_drive_root_for_business("BIZ-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "env")
        self.assertEqual(result["root_id"], "env-root-fallback")

    @patch("business_core.business_builder.get_business_config")
    def test_biz_root_priority_over_env(self, mock_cfg):
        """per-biz root всегда имеет приоритет над env root."""
        mock_cfg.return_value = {"drive_root_id": "per-biz-111", "found": True}

        from business_core.business_builder import resolve_drive_root_for_business
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "env-222"}):
            result = resolve_drive_root_for_business("BIZ-001")

        self.assertEqual(result["root_id"], "per-biz-111")
        self.assertNotEqual(result["root_id"], "env-222")


# ─── get_business_drive_root_id ─────────────────────────────────────────────

class TestGetBusinessDriveRootId(unittest.TestCase):
    """get_business_drive_root_id — тонкая обёртка над resolve_drive_root_for_business."""

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    def test_returns_root_id_string(self, mock_resolve):
        mock_resolve.return_value = {"root_id": "root-123", "ok": True, "source": "biz_registry"}
        from business_core.business_builder import get_business_drive_root_id
        result = get_business_drive_root_id("BIZ-001")
        self.assertEqual(result, "root-123")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    def test_returns_empty_string_if_no_root(self, mock_resolve):
        mock_resolve.return_value = {"root_id": "", "ok": False, "source": "none"}
        from business_core.business_builder import get_business_drive_root_id
        result = get_business_drive_root_id("BIZ-999")
        self.assertEqual(result, "")


# ─── provision_biz_drive: per-biz root ──────────────────────────────────────

class TestProvisionBizDrivePerBizRoot(unittest.TestCase):

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("integrations.google_drive_adapter.create_business_folder_structure")
    def test_uses_per_biz_root(self, mock_create, mock_resolve):
        """provision_biz_drive передаёт per-biz root в Drive Adapter."""
        mock_resolve.return_value = {
            "root_id": "per-biz-root-999", "ok": True, "source": "biz_registry", "error": None
        }
        mock_create.return_value = {
            "business_folder_id": "biz-folder-1",
            "business_folder_url": "https://drive.google.com/biz1",
            "folders": {},
        }

        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-001", "Узаконение")

        self.assertTrue(result["ok"])
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "per-biz-root-999")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("integrations.google_drive_adapter.create_business_folder_structure")
    def test_uses_env_root_as_fallback(self, mock_create, mock_resolve):
        """provision_biz_drive использует env root если нет per-biz."""
        mock_resolve.return_value = {
            "root_id": "env-root-777", "ok": True, "source": "env", "error": None
        }
        mock_create.return_value = {
            "business_folder_id": "biz-folder-2",
            "business_folder_url": "https://drive.google.com/biz2",
            "folders": {},
        }

        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-002", "Визы")

        self.assertTrue(result["ok"])
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "env-root-777")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    def test_no_root_returns_not_ok_no_exception(self, mock_resolve):
        """Нет root → ok=False, нет исключения, GTD не падает."""
        mock_resolve.return_value = {
            "root_id": "", "ok": False, "source": "none",
            "error": "Drive root not configured"
        }

        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-999", "Без Drive")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])
        self.assertNotIn("Exception", str(result["error"]))

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    def test_no_creds_returns_not_ok(self, mock_resolve):
        """Нет credentials → ok=False, понятная ошибка."""
        mock_resolve.return_value = {
            "root_id": "some-root", "ok": True, "source": "env", "error": None
        }

        from business_core.business_builder import provision_biz_drive
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CREDENTIALS_FILE"}
        with patch.dict(os.environ, env, clear=True):
            result = provision_biz_drive("BIZ-001", "Тест")

        self.assertFalse(result["ok"])
        self.assertIn("GOOGLE_CREDENTIALS_FILE", result["error"])

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("integrations.google_drive_adapter.create_business_folder_structure")
    def test_drive_error_returns_not_ok(self, mock_create, mock_resolve):
        """Drive API упал → ok=False, бизнес не сломан."""
        mock_resolve.return_value = {
            "root_id": "root-abc", "ok": True, "source": "biz_registry", "error": None
        }
        mock_create.side_effect = Exception("Drive API 500")

        from business_core.business_builder import provision_biz_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_biz_drive("BIZ-001", "Узаконение")

        self.assertFalse(result["ok"])
        self.assertIn("Drive API 500", result["error"])


# ─── provision_client_drive: per-biz root ───────────────────────────────────

class TestProvisionClientDrivePerBizRoot(unittest.TestCase):

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder._get_biz_id_by_name")
    @patch("integrations.google_drive_adapter.setup_biz_client_folder")
    def test_client_folder_uses_per_biz_root(self, mock_setup, mock_biz_id, mock_resolve):
        """Клиентская папка создаётся внутри per-biz root."""
        mock_biz_id.return_value = "BIZ-001"
        mock_resolve.return_value = {
            "root_id": "per-biz-root-ABC", "ok": True, "source": "biz_registry", "error": None
        }
        mock_setup.return_value = {
            "client_folder_id": "client-123",
            "client_folder_url": "https://drive.google.com/client123",
            "subfolders": {},
        }

        from business_core.business_builder import provision_client_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_client_drive("PRS-001", "Иван Петров", "Узаконение")

        self.assertTrue(result["ok"])
        call_kwargs = mock_setup.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "per-biz-root-ABC")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder._get_biz_id_by_name")
    @patch("integrations.google_drive_adapter.setup_biz_client_folder")
    def test_client_folder_uses_env_fallback(self, mock_setup, mock_biz_id, mock_resolve):
        """Клиентская папка использует env-root если нет per-biz."""
        mock_biz_id.return_value = "BIZ-002"
        mock_resolve.return_value = {
            "root_id": "env-root-XYZ", "ok": True, "source": "env", "error": None
        }
        mock_setup.return_value = {
            "client_folder_id": "client-456",
            "client_folder_url": "https://drive.google.com/client456",
            "subfolders": {},
        }

        from business_core.business_builder import provision_client_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_client_drive("PRS-002", "Мария", "Визы")

        self.assertTrue(result["ok"])
        call_kwargs = mock_setup.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "env-root-XYZ")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder._get_biz_id_by_name")
    def test_client_no_root_ok_false_no_exception(self, mock_biz_id, mock_resolve):
        """Нет root → ok=False без исключения."""
        mock_biz_id.return_value = "BIZ-999"
        mock_resolve.return_value = {
            "root_id": "", "ok": False, "source": "none",
            "error": "Drive root not configured"
        }

        from business_core.business_builder import provision_client_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_client_drive("PRS-001", "Кто-то", "НеизвестныйБиз")

        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])


# ─── Drive Adapter: root_folder_id parameter ────────────────────────────────

class TestDriveAdapterRootFolderIdParam(unittest.TestCase):
    """Проверяем что Drive Adapter принимает root_folder_id."""

    def test_create_business_folder_structure_has_root_param(self):
        import inspect
        from integrations.google_drive_adapter import create_business_folder_structure
        sig = inspect.signature(create_business_folder_structure)
        self.assertIn("root_folder_id", sig.parameters)

    def test_setup_biz_client_folder_has_root_param(self):
        import inspect
        from integrations.google_drive_adapter import setup_biz_client_folder
        sig = inspect.signature(setup_biz_client_folder)
        self.assertIn("root_folder_id", sig.parameters)

    @patch("integrations.google_drive_adapter.get_drive_service")
    @patch("integrations.google_drive_adapter.create_business_structure")
    def test_explicit_root_used_not_ensure(self, mock_create, mock_service):
        """Если root_folder_id передан — ensure_biz_root_folder_id НЕ вызывается."""
        mock_create.return_value = {
            "root_id": "biz-folder-Z",
            "root_url": "https://drive.google.com/Z",
            "subfolders": {},
        }

        from integrations.google_drive_adapter import create_business_folder_structure
        with patch("integrations.google_drive_adapter.ensure_biz_root_folder_id") as mock_ensure:
            result = create_business_folder_structure(
                biz_id="BIZ-TEST",
                biz_name="Test",
                root_folder_id="explicit-root-999",
            )
            mock_ensure.assert_not_called()

        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs.get("parent_folder_id"), "explicit-root-999")

    @patch("integrations.google_drive_adapter.get_drive_service")
    @patch("integrations.google_drive_adapter.create_business_structure")
    @patch("integrations.google_drive_adapter.ensure_biz_root_folder_id")
    def test_no_root_uses_ensure(self, mock_ensure, mock_create, mock_service):
        """Если root_folder_id не передан — ensure_biz_root_folder_id вызывается."""
        mock_ensure.return_value = "auto-discovered-root"
        mock_create.return_value = {
            "root_id": "biz-folder-Y",
            "root_url": "https://drive.google.com/Y",
            "subfolders": {},
        }

        from integrations.google_drive_adapter import create_business_folder_structure
        result = create_business_folder_structure(
            biz_id="BIZ-TEST2",
            biz_name="Test2",
        )

        mock_ensure.assert_called_once()


# ─── Different businesses have different roots ───────────────────────────────

class TestDifferentBizDifferentRoots(unittest.TestCase):
    """Разные бизнесы используют разные Drive roots."""

    @patch("business_core.business_builder.get_business_config")
    def test_biz001_and_biz002_different_roots(self, mock_cfg):
        configs = {
            "BIZ-001": {"drive_root_id": "root-for-uzak",  "found": True},
            "BIZ-002": {"drive_root_id": "root-for-visa",  "found": True},
            "BIZ-003": {"drive_root_id": "",               "found": True},
        }
        mock_cfg.side_effect = lambda biz_id: configs.get(biz_id, {"drive_root_id": "", "found": False})

        from business_core.business_builder import resolve_drive_root_for_business
        with patch.dict(os.environ, {"GDRIVE_BIZ_ROOT_FOLDER_ID": "global-root"}):
            r1 = resolve_drive_root_for_business("BIZ-001")
            r2 = resolve_drive_root_for_business("BIZ-002")
            r3 = resolve_drive_root_for_business("BIZ-003")

        self.assertEqual(r1["root_id"], "root-for-uzak")
        self.assertEqual(r1["source"], "biz_registry")

        self.assertEqual(r2["root_id"], "root-for-visa")
        self.assertEqual(r2["source"], "biz_registry")

        self.assertEqual(r3["root_id"], "global-root")
        self.assertEqual(r3["source"], "env")

        # Разные roots для разных бизнесов
        self.assertNotEqual(r1["root_id"], r2["root_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
