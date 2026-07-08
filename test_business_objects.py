"""
Phase 7A: OBJECT_REGISTRY commands — mock tests.

Покрывает:
A. generate_object_id на пустом OBJECT_REGISTRY → OBJ-001
B. generate_object_id после существующих объектов → следующий ID
C. create_object_record создает строку с обязательными полями
D. create_object_record ставит object_status="new" по умолчанию
E. find_objects_by_client возвращает объекты клиента
F. find_objects_by_client с biz_id фильтрует по бизнесу
G. find_object_by_id находит объект
H. update_object_drive_info дозаполняет поля
I. provision_object_drive использует per-biz Drive Root ID
J. provision_object_drive использует существующую папку клиента
K. provision_object_drive создает папку объекта
L. Drive root не настроен → ok=False без исключения
M. create_object_folder принимает client_folder_id
N. create_object_folder создает подпапки объекта
O. /objects показывает список объектов (через find_objects_by_client)
P. GTD Core файлы не импортируются
"""

import ast
import os
import unittest
from datetime import datetime
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


class TestGTDIsolation(unittest.TestCase):  # P
    def test_business_builder_no_gtd(self):
        bad = _top_imports("business_core/business_builder.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"business_builder импортирует GTD: {bad}")

    def test_google_drive_adapter_no_gtd(self):
        bad = _top_imports("integrations/google_drive_adapter.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"google_drive_adapter импортирует GTD: {bad}")

    def test_telegram_handlers_no_gtd(self):
        bad = _top_imports("business_core/telegram_handlers.py") & GTD_FORBIDDEN
        self.assertFalse(bad, f"telegram_handlers импортирует GTD: {bad}")


# ─── Helpers ────────────────────────────────────────────────────────────────

OBJ_HEADERS = [
    "OBJ ID", "Client ID", "Biz ID", "City", "Address",
    "Cadastral Number", "Area m2", "Object Type", "Object Status",
    "Current Service ID", "Roadmap ID", "Drive Folder ID", "Google Drive",
    "Notes", "Created At", "Last Updated",
]


def _make_obj_row(obj_id, client_id, biz_id, city="Алматы", address="ул. Абая 1",
                  object_type="", object_status="new", roadmap_id="",
                  drive_folder_id="", google_drive=""):
    row = [""] * len(OBJ_HEADERS)
    idx = {h: i for i, h in enumerate(OBJ_HEADERS)}
    row[idx["OBJ ID"]]         = obj_id
    row[idx["Client ID"]]      = client_id
    row[idx["Biz ID"]]         = biz_id
    row[idx["City"]]           = city
    row[idx["Address"]]        = address
    row[idx["Object Type"]]    = object_type
    row[idx["Object Status"]]  = object_status
    row[idx["Roadmap ID"]]     = roadmap_id
    row[idx["Drive Folder ID"]]= drive_folder_id
    row[idx["Google Drive"]]   = google_drive
    return row


def _mock_sheet(headers, rows):
    m = MagicMock()
    m.get_all_values.return_value = [headers] + rows
    m.update_cell = MagicMock()
    return m


# ─── A. generate_object_id — empty sheet ────────────────────────────────────

class TestGenerateObjectId(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_empty_registry_returns_obj001(self, mock_sheet):
        """A. Пустой лист → OBJ-001."""
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, [])
        from business_core.business_builder import generate_object_id
        result = generate_object_id()
        self.assertEqual(result, "OBJ-001")

    @patch("business_core.sheets.get_business_sheet")
    def test_existing_objects_next_id(self, mock_sheet):
        """B. Два объекта OBJ-001, OBJ-002 → следующий OBJ-003."""
        rows = [
            _make_obj_row("OBJ-001", "PRS-001", "BIZ-001"),
            _make_obj_row("OBJ-002", "PRS-001", "BIZ-001"),
        ]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import generate_object_id
        result = generate_object_id()
        self.assertEqual(result, "OBJ-003")

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_obj001(self, mock_sheet):
        """Ошибка Sheets → OBJ-001 без исключения."""
        mock_sheet.side_effect = Exception("timeout")
        from business_core.business_builder import generate_object_id
        result = generate_object_id()
        self.assertEqual(result, "OBJ-001")


# ─── C, D. create_object_record ─────────────────────────────────────────────

class TestCreateObjectRecord(unittest.TestCase):

    @patch("business_core.business_builder.generate_object_id")
    @patch("business_core.sheets.append_business_row")
    def test_creates_row_with_required_fields(self, mock_append, mock_gen_id):  # C
        """C. Запись содержит обязательные поля."""
        mock_gen_id.return_value = "OBJ-001"
        from business_core.business_builder import create_object_record
        result = create_object_record(
            client_id="PRS-001",
            biz_id="BIZ-001",
            city="Алматы",
            address="ул. Абая 10",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["obj_id"], "OBJ-001")
        mock_append.assert_called_once()
        row = mock_append.call_args[0][1]
        self.assertEqual(row[0], "OBJ-001")   # OBJ ID
        self.assertEqual(row[1], "PRS-001")   # Client ID
        self.assertEqual(row[2], "BIZ-001")   # Biz ID
        self.assertEqual(row[3], "Алматы")    # City
        self.assertEqual(row[4], "ул. Абая 10")  # Address

    @patch("business_core.business_builder.generate_object_id")
    @patch("business_core.sheets.append_business_row")
    def test_default_status_is_new(self, mock_append, mock_gen_id):  # D
        """D. object_status по умолчанию "new"."""
        mock_gen_id.return_value = "OBJ-002"
        from business_core.business_builder import create_object_record
        result = create_object_record(
            client_id="PRS-001", biz_id="BIZ-001",
            city="Астана", address="пр. Абылай хана 5",
        )
        row = mock_append.call_args[0][1]
        status_idx = OBJ_HEADERS.index("Object Status")
        self.assertEqual(row[status_idx], "new")

    def test_missing_required_fields_returns_error(self):
        from business_core.business_builder import create_object_record
        result = create_object_record(client_id="", biz_id="BIZ-001", city="А", address="б")
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])


# ─── E, F. find_objects_by_client ───────────────────────────────────────────

class TestFindObjectsByClient(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_returns_objects_for_client(self, mock_sheet):  # E
        rows = [
            _make_obj_row("OBJ-001", "PRS-001", "BIZ-001", city="Алматы"),
            _make_obj_row("OBJ-002", "PRS-002", "BIZ-001", city="Астана"),
        ]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_objects_by_client
        result = find_objects_by_client("PRS-001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["obj_id"], "OBJ-001")

    @patch("business_core.sheets.get_business_sheet")
    def test_filters_by_biz_id(self, mock_sheet):  # F
        rows = [
            _make_obj_row("OBJ-001", "PRS-001", "BIZ-001"),
            _make_obj_row("OBJ-002", "PRS-001", "BIZ-002"),
        ]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_objects_by_client
        result = find_objects_by_client("PRS-001", biz_id="BIZ-001")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["biz_id"], "BIZ-001")

    @patch("business_core.sheets.get_business_sheet")
    def test_empty_registry_returns_empty(self, mock_sheet):
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, [])
        from business_core.business_builder import find_objects_by_client
        self.assertEqual(find_objects_by_client("PRS-001"), [])

    @patch("business_core.sheets.get_business_sheet")
    def test_sheets_error_returns_empty(self, mock_sheet):
        mock_sheet.side_effect = Exception("boom")
        from business_core.business_builder import find_objects_by_client
        self.assertEqual(find_objects_by_client("PRS-001"), [])


# ─── G. find_object_by_id ───────────────────────────────────────────────────

class TestFindObjectById(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_finds_object(self, mock_sheet):  # G
        rows = [_make_obj_row("OBJ-003", "PRS-005", "BIZ-002", city="Шымкент")]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_object_by_id
        result = find_object_by_id("OBJ-003")
        self.assertIsNotNone(result)
        self.assertEqual(result["obj_id"], "OBJ-003")
        self.assertEqual(result["city"], "Шымкент")

    @patch("business_core.sheets.get_business_sheet")
    def test_not_found_returns_none(self, mock_sheet):
        rows = [_make_obj_row("OBJ-001", "PRS-001", "BIZ-001")]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_object_by_id
        self.assertIsNone(find_object_by_id("OBJ-999"))

    @patch("business_core.sheets.get_business_sheet")
    def test_error_returns_none(self, mock_sheet):
        mock_sheet.side_effect = Exception("oops")
        from business_core.business_builder import find_object_by_id
        self.assertIsNone(find_object_by_id("OBJ-001"))


# ─── H. update_object_drive_info ────────────────────────────────────────────

class TestUpdateObjectDriveInfo(unittest.TestCase):

    @patch("business_core.sheets.get_business_sheet")
    def test_fills_empty_drive_fields(self, mock_sheet):  # H
        row = _make_obj_row("OBJ-001", "PRS-001", "BIZ-001")
        mock = _mock_sheet(OBJ_HEADERS, [row])
        mock_sheet.return_value = mock

        from business_core.business_builder import update_object_drive_info
        result = update_object_drive_info("OBJ-001", "folder-abc", "https://drive.google.com/abc")
        self.assertTrue(result)
        self.assertEqual(mock.update_cell.call_count, 2)

    @patch("business_core.sheets.get_business_sheet")
    def test_does_not_overwrite_existing(self, mock_sheet):
        row = _make_obj_row("OBJ-001", "PRS-001", "BIZ-001",
                            drive_folder_id="existing", google_drive="https://exist")
        mock = _mock_sheet(OBJ_HEADERS, [row])
        mock_sheet.return_value = mock

        from business_core.business_builder import update_object_drive_info
        result = update_object_drive_info("OBJ-001", "new-folder", "https://new")
        self.assertFalse(result)
        mock.update_cell.assert_not_called()

    @patch("business_core.sheets.get_business_sheet")
    def test_error_returns_false(self, mock_sheet):
        mock_sheet.side_effect = Exception("timeout")
        from business_core.business_builder import update_object_drive_info
        self.assertFalse(update_object_drive_info("OBJ-001", "x", "https://x"))


# ─── I-L. provision_object_drive ────────────────────────────────────────────

class TestProvisionObjectDrive(unittest.TestCase):

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    def test_no_root_returns_not_ok(self, mock_resolve):  # L
        """Drive root не настроен → ok=False без исключения."""
        mock_resolve.return_value = {
            "root_id": "", "ok": False, "source": "none",
            "error": "Drive root not configured"
        }
        from business_core.business_builder import provision_object_drive
        with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
            result = provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder.get_business_config")
    @patch("business_core.business_builder.provision_client_drive")
    @patch("business_core.business_builder.update_person_drive_info")
    @patch("business_core.business_builder.update_object_drive_info")
    @patch("integrations.google_drive_adapter.create_object_folder")
    def test_uses_per_biz_root(self, mock_create, mock_upd_obj, mock_upd_person,
                                mock_prov_cl, mock_cfg, mock_resolve):  # I
        """provision_object_drive использует per-biz root."""
        mock_resolve.return_value = {
            "root_id": "per-biz-root-111", "ok": True, "source": "biz_registry", "error": None
        }
        mock_cfg.return_value = {"name": "Узаконение", "found": True}
        mock_prov_cl.return_value = {
            "ok": True, "folder_id": "client-folder-x", "folder_url": "https://cl/x",
            "biz_id": "BIZ-001",
        }
        mock_create.return_value = {
            "ok": True, "folder_id": "obj-folder-1", "folder_url": "https://obj/1", "error": None
        }
        mock_upd_obj.return_value = True
        mock_upd_person.return_value = True

        from business_core.business_builder import provision_object_drive

        # Мок PEOPLE_REGISTRY (нет папки клиента)
        with patch("business_core.sheets.get_business_sheet") as mock_gs:
            prs_headers = ["ID", "ФИО", "Drive Folder ID", "Google Drive"]
            prs_row     = ["PRS-001", "Иван Петров", "", ""]
            mock_gs.return_value = _mock_sheet(prs_headers, [prs_row])
            with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
                result = provision_object_drive("BIZ-001", "PRS-001", "OBJ-001", "Алматы", "ул. 1")

        self.assertTrue(result["ok"])
        # create_object_folder должен получить per-biz root
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs.get("root_folder_id"), "per-biz-root-111")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder.get_business_config")
    @patch("business_core.business_builder.update_object_drive_info")
    @patch("integrations.google_drive_adapter.create_object_folder")
    def test_uses_existing_client_folder(self, mock_create, mock_upd, mock_cfg, mock_resolve):  # J, M
        """provision_object_drive использует существующую папку клиента."""
        mock_resolve.return_value = {
            "root_id": "root-1", "ok": True, "source": "env", "error": None
        }
        mock_cfg.return_value = {"name": "Узаконение", "found": True}
        mock_create.return_value = {
            "ok": True, "folder_id": "obj-new", "folder_url": "https://obj/new", "error": None
        }
        mock_upd.return_value = True

        from business_core.business_builder import provision_object_drive

        # Клиент уже имеет Drive Folder ID
        with patch("business_core.sheets.get_business_sheet") as mock_gs:
            prs_headers = ["ID", "ФИО", "Drive Folder ID", "Google Drive"]
            prs_row     = ["PRS-001", "Мария", "existing-client-folder", "https://cl/exist"]
            mock_gs.return_value = _mock_sheet(prs_headers, [prs_row])
            with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
                result = provision_object_drive("BIZ-001", "PRS-001", "OBJ-002", "Астана", "пр. 5")

        self.assertTrue(result["ok"])
        # client_folder_id должен быть передан в create_object_folder
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs.get("client_folder_id"), "existing-client-folder")

    @patch("business_core.business_builder.resolve_drive_root_for_business")
    @patch("business_core.business_builder.get_business_config")
    @patch("business_core.business_builder.update_object_drive_info")
    @patch("integrations.google_drive_adapter.create_object_folder")
    def test_drive_saved_to_object_registry(self, mock_create, mock_upd, mock_cfg, mock_resolve):  # K
        """Drive Folder ID сохраняется в OBJECT_REGISTRY."""
        mock_resolve.return_value = {"root_id": "r", "ok": True, "source": "env", "error": None}
        mock_cfg.return_value = {"name": "X", "found": True}
        mock_create.return_value = {
            "ok": True, "folder_id": "saved-id", "folder_url": "https://saved", "error": None
        }
        mock_upd.return_value = True

        from business_core.business_builder import provision_object_drive

        with patch("business_core.sheets.get_business_sheet") as mock_gs:
            prs_headers = ["ID", "ФИО", "Drive Folder ID", "Google Drive"]
            prs_row     = ["PRS-001", "Кто-то", "", ""]
            mock_gs.return_value = _mock_sheet(prs_headers, [prs_row])
            with patch.dict(os.environ, {"GOOGLE_CREDENTIALS_FILE": "/fake/creds.json"}):
                with patch("business_core.business_builder.provision_client_drive") as mock_pcl:
                    with patch("business_core.business_builder.update_person_drive_info"):
                        mock_pcl.return_value = {"ok": True, "folder_id": "cl-f", "folder_url": "https://cl", "biz_id": "BIZ-001"}
                        result = provision_object_drive("BIZ-001", "PRS-001", "OBJ-003", "Алматы", "ул.")

        mock_upd.assert_called_once_with("OBJ-003", drive_folder_id="saved-id", google_drive_url="https://saved")


# ─── M, N. create_object_folder ─────────────────────────────────────────────

class TestCreateObjectFolder(unittest.TestCase):

    def test_function_exists(self):
        from integrations.google_drive_adapter import create_object_folder
        self.assertTrue(callable(create_object_folder))

    def test_signature_has_client_folder_id(self):  # M
        import inspect
        from integrations.google_drive_adapter import create_object_folder
        sig = inspect.signature(create_object_folder)
        self.assertIn("client_folder_id", sig.parameters)
        self.assertIn("root_folder_id",   sig.parameters)

    @patch("integrations.google_drive_adapter.get_drive_service")
    @patch("integrations.google_drive_adapter.get_or_create_folder")
    def test_creates_subfolders(self, mock_get_or_create, mock_service):  # N
        """Создаёт подпапки объекта внутри папки клиента."""
        mock_get_or_create.return_value = ("mock-folder-id", True)

        from integrations.google_drive_adapter import create_object_folder
        result = create_object_folder(
            biz_id="BIZ-001",
            biz_name="Узаконение",
            client_id="PRS-001",
            client_name="Иван Петров",
            obj_id="OBJ-001",
            city="Алматы",
            address="ул. Абая 10",
            client_folder_id="client-folder-123",  # напрямую, без поиска
        )

        self.assertTrue(result["ok"])
        # Должно создаться 5 подпапок + сама папка объекта
        call_names = [c[0][1] for c in mock_get_or_create.call_args_list]
        expected_subs = [
            "01 Документы от клиента", "02 Документы наши",
            "03 Переписка", "04 Фото и медиа", "05 Архив",
        ]
        for sub in expected_subs:
            self.assertIn(sub, call_names, f"Подпапка '{sub}' не создана")

    @patch("integrations.google_drive_adapter.get_drive_service")
    @patch("integrations.google_drive_adapter.get_or_create_folder")
    def test_uses_client_folder_id_directly(self, mock_get_or_create, mock_service):
        """Если client_folder_id передан — папка клиента не ищется."""
        mock_get_or_create.return_value = ("folder-x", False)

        from integrations.google_drive_adapter import create_object_folder
        result = create_object_folder(
            biz_id="BIZ-001", biz_name="Узаконение",
            client_id="PRS-001", client_name="Иван",
            obj_id="OBJ-001", city="Алматы", address="ул. 1",
            client_folder_id="client-direct-folder",
        )

        self.assertTrue(result["ok"])
        # Первый вызов должен использовать client_folder_id как parent, не искать бизнес/клиента
        first_call_parent = mock_get_or_create.call_args_list[0][0][2]
        self.assertEqual(first_call_parent, "client-direct-folder")

    @patch("integrations.google_drive_adapter.get_drive_service")
    def test_drive_error_returns_not_ok(self, mock_service):
        mock_service.side_effect = Exception("Drive auth error")

        from integrations.google_drive_adapter import create_object_folder
        result = create_object_folder(
            biz_id="BIZ-001", biz_name="X",
            client_id="PRS-001", client_name="Y",
            obj_id="OBJ-001", city="Алматы", address="ул.",
        )
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])


# ─── O. /objects (find_objects_by_client используется) ──────────────────────

class TestObjectsCmd(unittest.TestCase):
    """O. /objects возвращает список объектов."""

    @patch("business_core.sheets.get_business_sheet")
    def test_objects_list_multiple_clients(self, mock_sheet):
        rows = [
            _make_obj_row("OBJ-001", "PRS-001", "BIZ-001", city="Алматы"),
            _make_obj_row("OBJ-002", "PRS-001", "BIZ-001", city="Астана"),
            _make_obj_row("OBJ-003", "PRS-002", "BIZ-001"),
        ]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_objects_by_client
        result = find_objects_by_client("PRS-001")
        self.assertEqual(len(result), 2)
        obj_ids = [o["obj_id"] for o in result]
        self.assertIn("OBJ-001", obj_ids)
        self.assertIn("OBJ-002", obj_ids)
        self.assertNotIn("OBJ-003", obj_ids)

    @patch("business_core.sheets.get_business_sheet")
    def test_objects_empty_for_unknown_client(self, mock_sheet):
        rows = [_make_obj_row("OBJ-001", "PRS-001", "BIZ-001")]
        mock_sheet.return_value = _mock_sheet(OBJ_HEADERS, rows)
        from business_core.business_builder import find_objects_by_client
        result = find_objects_by_client("PRS-999")
        self.assertEqual(result, [])


# ─── _parse_kv_args ─────────────────────────────────────────────────────────

class TestParseKvArgs(unittest.TestCase):

    def _fn(self, text):
        from business_core.telegram_handlers import _parse_kv_args
        return _parse_kv_args(text)

    def test_simple_kv(self):
        result = self._fn('biz_id=BIZ-001 client_id=PRS-001 city=Алматы')
        self.assertEqual(result["biz_id"], "BIZ-001")
        self.assertEqual(result["client_id"], "PRS-001")
        self.assertEqual(result["city"], "Алматы")

    def test_quoted_value(self):
        result = self._fn('address="ул. Абая 10" type="частный дом"')
        self.assertEqual(result["address"], "ул. Абая 10")
        self.assertEqual(result["type"], "частный дом")

    def test_empty_string(self):
        self.assertEqual(self._fn(""), {})

    def test_single_arg(self):
        result = self._fn("biz_id=BIZ-003")
        self.assertEqual(result["biz_id"], "BIZ-003")

    def test_mixed(self):
        result = self._fn('biz_id=BIZ-001 address="ул. Ленина 5" area=120')
        self.assertEqual(result["biz_id"], "BIZ-001")
        self.assertEqual(result["address"], "ул. Ленина 5")
        self.assertEqual(result["area"], "120")


if __name__ == "__main__":
    unittest.main(verbosity=2)
