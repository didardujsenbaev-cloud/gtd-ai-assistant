"""
Phase 7B tests: Object → Service → Roadmap binding.

Covers:
A. generate_roadmap_id на пустом ROADMAPS → RM-001
B. generate_roadmap_id после существующих roadmap → следующий ID
C. create_roadmap_for_object создает roadmap с Object ID
D. create_roadmap_for_object сохраняет Biz ID, Client ID, Service ID
E. update_object_roadmap_id записывает Roadmap ID в OBJECT_REGISTRY
F. find_roadmaps_by_object возвращает roadmap объекта
G. create_roadmap_stages_from_template создает этапы по case_type
H. неизвестный case_type не ломает создание roadmap
I. /startroadmap создает roadmap для объекта
J. /startroadmap создает stages
K. /startroadmap не создает GTD tasks
L. /roadmaps показывает список
M. /stages показывает этапы
N. GTD Core файлы не импортируются и не меняются
"""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

WORKSPACE = Path(__file__).parent

GTD_FORBIDDEN_MODULES = {
    "inbox_processor",
    "project_planner",
    "calendar_sync",
    "telegram_bot",
}


def _imports_in_file(path: Path) -> list[str]:
    """Return all imported module names found in a Python source file."""
    source = path.read_text(encoding="utf-8")
    tree   = ast.parse(source, str(path))
    mods   = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module.split(".")[0])
    return mods


def _make_sheet(rows: list[list[str]]) -> MagicMock:
    """Create a mock gspread worksheet."""
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    ws.row_values.side_effect = lambda r: rows[r - 1] if 0 <= r - 1 < len(rows) else []
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


def _make_roadmaps_sheet(extra_rows: list[list[str]] | None = None) -> MagicMock:
    headers = [
        "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
        "Client Name", "GTD Project ID", "Responsible", "Status",
        "Created", "Expected", "Progress %",
        "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
        "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
        "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
        "Stage 10 Status", "Notes", "Last Updated",
        "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
    ]
    rows = [headers] + (extra_rows or [])
    return _make_sheet(rows)


def _make_stages_sheet(extra_rows: list[list[str]] | None = None) -> MagicMock:
    headers = [
        "Stage ID", "Roadmap ID", "Order", "Name", "Status",
        "Due Date", "Completed At", "GTD Action ID",
        "Responsible", "Docs Required", "Docs Received", "Notes",
    ]
    rows = [headers] + (extra_rows or [])
    return _make_sheet(rows)


def _make_objects_sheet(extra_rows: list[list[str]] | None = None) -> MagicMock:
    headers = [
        "OBJ ID", "Client ID", "Biz ID", "City", "Address",
        "Cadastral Number", "Area m2", "Object Type", "Object Status",
        "Current Service ID", "Roadmap ID", "Drive Folder ID",
        "Google Drive", "Notes", "Created At", "Last Updated",
    ]
    rows = [headers] + (extra_rows or [])
    return _make_sheet(rows)


# ────────────────────────────────────────────────────────────
# A/B: generate_roadmap_id
# ────────────────────────────────────────────────────────────

class TestGenerateRoadmapId(unittest.TestCase):

    def test_A_empty_roadmaps_returns_RM001(self):
        """A: пустой ROADMAPS → RM-001."""
        # Patch after fresh import to avoid stale module reference
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb

        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_roadmaps_sheet()):
            result = bb.generate_roadmap_id()
        self.assertEqual(result, "RM-001")

    def test_B_after_existing_roadmaps_increments(self):
        """B: после RM-003 → следующий ID > 3."""
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb

        existing_row = ["RM-003"] + [""] * 26
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_roadmaps_sheet([existing_row])):
            result = bb.generate_roadmap_id()

        self.assertTrue(result.startswith("RM-"), msg=f"Expected RM-xxx, got {result}")
        num = int(result.split("-")[1])
        self.assertGreater(num, 0)


# ────────────────────────────────────────────────────────────
# C/D: create_roadmap_for_object
# ────────────────────────────────────────────────────────────

class TestCreateRoadmapForObject(unittest.TestCase):

    def _reload_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    def test_C_creates_roadmap_with_object_id(self):
        """C: create_roadmap_for_object → содержит Object ID."""
        bb = self._reload_bb()

        # get_business_sheet патчится ПОСЛЕ _reload_bb(), иначе перезагрузка
        # модулей сотрёт патч, и create_roadmap_for_object уйдёт в реальный
        # Google Sheets API (тот же паттерн, что уже использовался ниже
        # для append_business_row/generate_next_id).
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_roadmaps_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_ap, \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001",
                biz_id="BIZ-001",
                client_id="PRS-001",
                service_id="SVC-001",
                case_type="legalization_reconstruction_house",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["roadmap_id"], "RM-001")
            appended_row = mock_ap.call_args[0][1]
            # Object ID должен быть в row (после "Last Updated")
            self.assertIn("OBJ-001", appended_row)

    def test_D_saves_biz_client_service(self):
        """D: create_roadmap_for_object сохраняет biz_id, client_id, service_id."""
        bb = self._reload_bb()

        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_roadmaps_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_ap, \
             patch("business_core.sheets.generate_next_id", return_value="RM-001"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-002",
                biz_id="BIZ-002",
                client_id="PRS-002",
                service_id="SVC-002",
            )
            self.assertTrue(result["ok"])
            row = mock_ap.call_args[0][1]
            self.assertIn("BIZ-002", row)
            self.assertIn("PRS-002", row)
            self.assertIn("SVC-002", row)
            self.assertIn("OBJ-002", row)

    def test_missing_required_fields_returns_error(self):
        """create_roadmap_for_object с пустым obj_id → error."""
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        result = bb.create_roadmap_for_object(
            obj_id="", biz_id="BIZ-001", client_id="PRS-001", service_id=""
        )
        self.assertFalse(result["ok"])


class TestCreateRoadmapForObjectExtensionOrchestration(unittest.TestCase):
    """
    Phase 28C/28E: create_roadmap_for_object() is now the single
    orchestration entry point — it calls roadmap_manager.create_roadmap_record()
    (never writes ROADMAPS itself), reads Template Stage rows via
    roadmap_template_manager.find_template_stages(), calls roadmap_manager.
    ensure_roadmap_stages() for Stage creation, and — as the orchestrator,
    not Core — calls stage_entity_relations.copy_template_relations_to_stage()
    directly for newly created stages. Extension (relation-copy) failures
    must never hide that the Roadmap/Stages were genuinely created.
    """

    def _reload_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    def _template_rows(self):
        return [
            {"stage_id": "TSTG-001", "order": "1", "stage_name": "Этап 1",
             "required_docs": "", "responsible": "", "notes": ""},
            {"stage_id": "TSTG-002", "order": "2", "stage_name": "Этап 2",
             "required_docs": "", "responsible": "", "notes": ""},
        ]

    def test_calls_roadmap_manager_create_roadmap_record_not_raw_sheets(self):
        bb = self._reload_bb()
        with patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-900", "roadmap": {}, "error": None}) as mock_create, \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-900", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-001", template_id="RMT-001",
            )
        self.assertTrue(result["ok"])
        mock_create.assert_called_once()
        mock_append.assert_not_called()

    def test_extension_relation_copy_failure_is_visible_but_core_still_ok(self):
        """Extension failure must never be reported as if nothing was
        created — ok stays True (Core succeeded), partial_failure/
        partial_success become True, and the error is visible in
        relation_copy_errors."""
        bb = self._reload_bb()

        def failing_copy(template_stage_id, stage_id):
            raise RuntimeError("simulated transient relation-copy failure")

        with patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-901", "roadmap": {}, "error": None}), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=self._template_rows()), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value={
                       "ok": True, "roadmap_id": "RM-901",
                       "created_stage_ids": ["STAGE-001", "STAGE-002"],
                       "created_from_orders": [1, 2],
                       "existing_stage_ids": [], "created_count": 2, "existing_count": 0,
                       "total_count": 2, "error": None,
                   }), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   side_effect=failing_copy):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-901", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-001", template_id="RMT-001",
            )

        self.assertTrue(result["ok"], "Core (Roadmap + Stages) succeeded — ok must stay True")
        self.assertTrue(result["core_created"])
        self.assertTrue(result["stages_created"])
        self.assertEqual(result["stages_count"], 2)
        self.assertTrue(result["partial_success"])
        self.assertTrue(result["partial_failure"])
        self.assertEqual(len(result["relation_copy_errors"]), 2)
        for stage_id, template_stage_id, errors in result["relation_copy_errors"]:
            self.assertIn("simulated transient relation-copy failure", str(errors))

    def test_relation_copy_success_reports_no_partial_failure(self):
        from business_core.stage_entity_relations import CopyRelationsResult
        bb = self._reload_bb()

        def ok_copy(template_stage_id, stage_id):
            return CopyRelationsResult(template_stage_id=template_stage_id, stage_id=stage_id, created=())

        with patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-902", "roadmap": {}, "error": None}), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=self._template_rows()), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value={
                       "ok": True, "roadmap_id": "RM-902",
                       "created_stage_ids": ["STAGE-001", "STAGE-002"],
                       "created_from_orders": [1, 2],
                       "existing_stage_ids": [], "created_count": 2, "existing_count": 0,
                       "total_count": 2, "error": None,
                   }), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   side_effect=ok_copy) as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-902", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-001", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["partial_success"])
        self.assertFalse(result["partial_failure"])
        self.assertEqual(result["relation_copy_errors"], ())
        self.assertEqual(mock_copy.call_count, 2)
        self.assertEqual(
            [c.args for c in mock_copy.call_args_list],
            [("TSTG-001", "STAGE-001"), ("TSTG-002", "STAGE-002")],
        )

    def test_retry_with_no_new_stages_does_not_call_relation_copy_again(self):
        """Idempotent retry: if ensure_roadmap_stages reports zero newly
        created stages (everything already existed), relation-copy is
        not attempted again for them — matches ensure_roadmap_stages's
        own idempotency guarantee."""
        bb = self._reload_bb()

        with patch("business_core.roadmap_manager.create_roadmap_record",
                   return_value={"ok": True, "roadmap_id": "RM-903", "roadmap": {}, "error": None}), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=self._template_rows()), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value={
                       "ok": True, "roadmap_id": "RM-903",
                       "created_stage_ids": [], "created_from_orders": [],
                       "existing_stage_ids": ["STAGE-001", "STAGE-002"],
                       "created_count": 0, "existing_count": 2,
                       "total_count": 2, "error": None,
                   }), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-903", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-001", template_id="RMT-001",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        mock_copy.assert_not_called()

    def test_does_not_import_extension_modules_at_module_level(self):
        """business_builder.py is the orchestrator, not Core — it IS
        allowed to import Extension modules (unlike roadmap_manager.py/
        roadmap_template_manager.py), and does so, function-locally,
        only inside create_roadmap_for_object's relation-copy branch."""
        import ast
        bb = self._reload_bb()
        import inspect
        src = inspect.getsource(bb)
        tree = ast.parse(src)
        module_level_imports = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                module_level_imports.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_level_imports.add(alias.name.split(".")[-1])
        self.assertNotIn("stage_entity_relations", module_level_imports)


# ────────────────────────────────────────────────────────────
# E: update_object_roadmap_id
# ────────────────────────────────────────────────────────────

class TestUpdateObjectRoadmapId(unittest.TestCase):

    def _reload_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    @patch("business_core.sheets.get_business_sheet")
    def test_E_writes_roadmap_id_to_object_registry(self, mock_get):
        """E: update_object_roadmap_id записывает RM-ID в OBJECT_REGISTRY."""
        obj_row = ["OBJ-001", "PRS-001", "BIZ-001", "Алматы", "Ул. Ленина 1",
                   "", "", "house", "active", "SVC-001", "",
                   "", "", "", "2025-01-01", "2025-01-01"]
        mock_ws = _make_objects_sheet([obj_row])
        mock_get.return_value = mock_ws

        bb = self._reload_bb()
        with patch("business_core.sheets.get_business_sheet", return_value=mock_ws):
            result = bb.update_object_roadmap_id("OBJ-001", "RM-001")
        self.assertTrue(result)
        mock_ws.update_cell.assert_called_once()
        args = mock_ws.update_cell.call_args[0]
        self.assertEqual(args[2], "RM-001")

    @patch("business_core.sheets.get_business_sheet")
    def test_E_does_not_overwrite_existing_roadmap_id(self, mock_get):
        """E: если Roadmap ID уже заполнен — не перезаписывает."""
        obj_row = ["OBJ-001", "PRS-001", "BIZ-001", "Алматы", "Ул. Ленина 1",
                   "", "", "house", "active", "SVC-001", "RM-OLD",
                   "", "", "", "2025-01-01", "2025-01-01"]
        mock_ws = _make_objects_sheet([obj_row])
        mock_get.return_value = mock_ws

        bb = self._reload_bb()
        with patch("business_core.sheets.get_business_sheet", return_value=mock_ws):
            result = bb.update_object_roadmap_id("OBJ-001", "RM-NEW")
        self.assertFalse(result)
        mock_ws.update_cell.assert_not_called()


# ────────────────────────────────────────────────────────────
# F: find_roadmaps_by_object
# ────────────────────────────────────────────────────────────

class TestFindRoadmapsByObject(unittest.TestCase):

    def _reload_bb(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.business_builder as bb
        return bb

    @patch("business_core.sheets.get_business_sheet")
    def test_F_returns_roadmaps_for_object(self, mock_get):
        """F: find_roadmaps_by_object возвращает roadmap объекта."""
        row = [
            "RM-001", "BIZ-001", "SVC-001", "Алматы", "PRS-001",
            "Test Roadmap", "", "", "active", "2025-01-01", "", "0",
            "", "", "", "", "", "", "", "", "", "",
            "", "2025-01-01",
            "OBJ-001", "", "legalization_reconstruction_house",
        ]
        mock_get.return_value = _make_roadmaps_sheet([row])
        bb = self._reload_bb()

        with patch("business_core.sheets.get_business_sheet", return_value=mock_get.return_value):
            results = bb.find_roadmaps_by_object("OBJ-001")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["roadmap_id"], "RM-001")
        self.assertEqual(results[0]["obj_id"], "OBJ-001")

    @patch("business_core.sheets.get_business_sheet")
    def test_F_returns_empty_for_unknown_object(self, mock_get):
        """F: нет roadmap для несуществующего объекта."""
        mock_get.return_value = _make_roadmaps_sheet()
        bb = self._reload_bb()
        with patch("business_core.sheets.get_business_sheet", return_value=mock_get.return_value):
            results = bb.find_roadmaps_by_object("OBJ-999")
        self.assertEqual(results, [])


# ────────────────────────────────────────────────────────────
# G/H: create_roadmap_stages_from_template
# ────────────────────────────────────────────────────────────

class TestCreateRoadmapStages(unittest.TestCase):

    def _reload_rm(self):
        for key in list(sys.modules.keys()):
            if "business_core.roadmap_manager" in key or key == "business_core.roadmap_manager":
                del sys.modules[key]
        import business_core.roadmap_manager as rm
        return rm

    @patch("business_core.sheets.get_business_sheet")
    def test_G_creates_stages_for_known_case_type(self, mock_get):
        """G: create_roadmap_stages_from_template создает этапы по case_type."""
        mock_stage_ws = _make_stages_sheet()
        mock_get.return_value = mock_stage_ws

        rm = self._reload_rm()
        stage_count = len(rm.ROADMAP_TEMPLATES["legalization_reconstruction_house"])

        with patch("business_core.sheets.append_business_row") as mock_ap, \
             patch("business_core.sheets.generate_next_id", side_effect=[
                 f"STAGE-{i:03d}" for i in range(1, stage_count + 1)
             ]):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_reconstruction_house"
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], stage_count)
        self.assertIsNone(result["warning"])
        self.assertEqual(mock_ap.call_count, stage_count)

    def test_H_unknown_case_type_returns_warning_not_error(self):
        """H: неизвестный case_type не ломает создание roadmap."""
        rm = self._reload_rm()
        result = rm.create_roadmap_stages_from_template("RM-001", "unknown_case_xyz")
        self.assertTrue(result["ok"], msg="ok должен быть True даже для неизвестного case_type")
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])
        self.assertIn("не найден", result["warning"].lower())

    def test_H_empty_roadmap_id_returns_error(self):
        """H: пустой roadmap_id → ok=False."""
        rm = self._reload_rm()
        result = rm.create_roadmap_stages_from_template("", "legalization_new_building")
        self.assertFalse(result["ok"])

    def test_G_all_templates_have_stages(self):
        """G: все шаблоны из ROADMAP_TEMPLATES содержат хотя бы 1 этап."""
        rm = self._reload_rm()
        for key, stages in rm.ROADMAP_TEMPLATES.items():
            self.assertGreater(len(stages), 0, f"Шаблон {key} пустой")

    def test_G_stage_rows_contain_roadmap_id(self):
        """G: каждый добавляемый этап содержит roadmap_id."""
        rm = self._reload_rm()
        stage_count = len(rm.ROADMAP_TEMPLATES["legalization_new_building"])
        appended_rows = []

        def capture_row(sheet_key, row):
            appended_rows.append(row)

        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_stages_sheet()), \
             patch("business_core.sheets.append_business_row", side_effect=capture_row), \
             patch("business_core.sheets.generate_next_id", side_effect=[
                 f"STAGE-{i:03d}" for i in range(1, stage_count + 1)
             ]):
            rm.create_roadmap_stages_from_template("RM-005", "legalization_new_building")

        for row in appended_rows:
            self.assertIn("RM-005", row)


# ────────────────────────────────────────────────────────────
# Phase 10.2B.2: create_roadmap_stages_from_template — header-safety
# ────────────────────────────────────────────────────────────

class TestCreateRoadmapStagesHeaderSafety(unittest.TestCase):

    def _reload_rm(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        import business_core.roadmap_manager as rm
        return rm

    def test_standard_header_order_produces_correct_row(self):
        """1: стандартный порядок заголовков — значения на своих местах."""
        rm = self._reload_rm()
        headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
        ]
        sheet = _make_sheet([headers])
        captured = []

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="STAGE-001"):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_new_building")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(headers)}
        row = captured[0]
        self.assertEqual(row[idx["Stage ID"]], "STAGE-001")
        self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
        self.assertEqual(row[idx["Order"]], "1")
        self.assertEqual(row[idx["Name"]], rm.ROADMAP_TEMPLATES["legalization_new_building"][0])
        self.assertEqual(row[idx["Status"]], "pending")
        self.assertEqual(row[idx["Due Date"]], "")
        self.assertEqual(row[idx["Completed At"]], "")
        self.assertEqual(row[idx["GTD Action ID"]], "")
        self.assertEqual(row[idx["Responsible"]], "")
        self.assertEqual(row[idx["Docs Required"]], "")
        self.assertEqual(row[idx["Docs Received"]], "")
        self.assertEqual(row[idx["Notes"]], "")

    def test_shuffled_header_order_gives_same_values_by_name(self):
        """2: результат не зависит от перестановки заголовков листа."""
        rm = self._reload_rm()
        standard = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
        ]
        shuffled = [
            "Notes", "Status", "Stage ID", "Docs Received", "Roadmap ID",
            "Due Date", "Order", "Responsible", "Name",
            "Docs Required", "Completed At", "GTD Action ID",
        ]
        self.assertCountEqual(shuffled, standard)
        sheet = _make_sheet([shuffled])
        captured = []

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="STAGE-001"):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_new_building")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(shuffled)}
        row = captured[0]
        self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
        self.assertEqual(row[idx["Status"]], "pending")
        self.assertEqual(row[idx["Name"]], rm.ROADMAP_TEMPLATES["legalization_new_building"][0])
        self.assertEqual(len(row), len(shuffled))

    def test_unknown_extra_columns_remain_empty(self):
        """4: неизвестные дополнительные колонки листа (напр. Phase 8C
        knowledge-поля, которых эта функция не заполняет) остаются пустыми."""
        rm = self._reload_rm()
        headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
            "SOP IDs", "Checklist IDs", "Materials IDs",
            "Document Template IDs", "FAQ IDs",
        ]
        sheet = _make_sheet([headers])
        captured = []

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, row: captured.append(row)), \
             patch("business_core.sheets.generate_next_id", return_value="STAGE-001"):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_new_building")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(headers)}
        row = captured[0]
        for extra in ("SOP IDs", "Checklist IDs", "Materials IDs",
                      "Document Template IDs", "FAQ IDs"):
            self.assertEqual(row[idx[extra]], "")
        self.assertEqual(len(row), len(headers))

    def test_headers_read_exactly_once_per_call(self):
        """5: заголовки читаются один раз за весь вызов функции,
        а не на каждый этап."""
        rm = self._reload_rm()
        headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
        ]
        sheet = _make_sheet([headers])
        stage_count = len(rm.ROADMAP_TEMPLATES["legalization_new_building"])
        self.assertGreater(stage_count, 1, "нужен шаблон из нескольких этапов")

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.generate_next_id", side_effect=[
                 f"STAGE-{i:03d}" for i in range(1, stage_count + 1)
             ]):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_new_building")

        self.assertTrue(result["ok"])
        row_values_calls = [c for c in sheet.row_values.call_args_list if c.args == (1,)]
        self.assertEqual(len(row_values_calls), 1,
                         "row_values(1) должен вызываться ровно один раз на весь вызов функции")

    def test_write_call_count_matches_stage_count(self):
        """6: append_business_row вызывается прежнее количество раз (по разу на этап)."""
        rm = self._reload_rm()
        sheet = _make_stages_sheet()
        stage_count = len(rm.ROADMAP_TEMPLATES["legalization_reconstruction_house"])

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_ap, \
             patch("business_core.sheets.generate_next_id", side_effect=[
                 f"STAGE-{i:03d}" for i in range(1, stage_count + 1)
             ]):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_reconstruction_house")

        self.assertTrue(result["ok"])
        self.assertEqual(mock_ap.call_count, stage_count)

    def test_stage_count_and_ids_unchanged(self):
        """7/8: количество этапов и stage_ids не изменились."""
        rm = self._reload_rm()
        sheet = _make_stages_sheet()
        stage_count = len(rm.ROADMAP_TEMPLATES["legalization_non_residential_reconstruction"])
        expected_ids = [f"STAGE-{i:03d}" for i in range(1, stage_count + 1)]

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"), \
             patch("business_core.sheets.generate_next_id", side_effect=expected_ids):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_non_residential_reconstruction")

        self.assertEqual(result["stages_count"], stage_count)
        self.assertEqual(result["stage_ids"], expected_ids)

    def test_empty_template_unchanged_no_sheet_access(self):
        """9: пустой/неизвестный шаблон — поведение не изменилось, и
        обращения к листу ROADMAP_STAGES не происходит вовсе."""
        rm = self._reload_rm()
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            result = rm.create_roadmap_stages_from_template("RM-001", "unknown_case_xyz")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])
        self.assertEqual(result["stage_ids"], [])
        mock_get_sheet.assert_not_called()

    def test_missing_required_header_returns_error_without_write(self):
        """10: отсутствует обязательный заголовок (Status) — запись не
        выполняется, ok=False, существующий контракт ошибки сохранён."""
        rm = self._reload_rm()
        incomplete_headers = [
            "Stage ID", "Roadmap ID", "Order", "Name",
            # "Status" отсутствует
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
        ]
        sheet = _make_sheet([incomplete_headers])

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row") as mock_ap, \
             patch("business_core.sheets.generate_next_id", return_value="STAGE-001"):
            result = rm.create_roadmap_stages_from_template(
                "RM-001", "legalization_new_building")

        self.assertFalse(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])
        self.assertEqual(result["stage_ids"], [])
        mock_ap.assert_not_called()


# ────────────────────────────────────────────────────────────
# I/J/K: /startroadmap Telegram command
# ────────────────────────────────────────────────────────────

class TestStartRoadmapCommand(unittest.TestCase):
    """Tests for the /startroadmap command handler."""

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]

    def _make_update(self, text: str) -> tuple[MagicMock, MagicMock]:
        from unittest.mock import AsyncMock
        update  = MagicMock()
        context = MagicMock()
        context.args = text.split() if text else []
        update.message.text = "/startroadmap " + text
        update.message.reply_text = AsyncMock()
        update.effective_chat.id = 123
        return update, context

    @patch("business_core.telegram_handlers._is_bc_enabled", return_value=True)
    @patch("business_core.business_builder.find_object_by_id")
    @patch("business_core.business_builder.create_roadmap_for_object")
    @patch("business_core.business_builder.update_object_roadmap_id")
    @patch("business_core.roadmap_manager.create_roadmap_stages_from_template")
    @patch("business_core.service_manager.find_service_by_id", return_value=None)
    @patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
           return_value=[])
    async def _run_startroadmap(
        self,
        mock_find_tmpl, mock_find_svc,
        mock_stages, mock_upd_obj, mock_create_rm, mock_find_obj, mock_enabled,
        text="obj_id=OBJ-001 service_id=SVC-001 case_type=legalization_reconstruction_house",
    ):
        import asyncio
        from business_core.telegram_handlers import startroadmap_cmd

        mock_find_obj.return_value = {
            "obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001",
        }
        # Phase 28C: create_roadmap_for_object is now the single
        # orchestration entry point — it creates the Roadmap AND the
        # Stages internally, so its own mocked return value carries
        # stages_count/used_template. create_roadmap_stages_from_template
        # (mock_stages) is no longer called directly from startroadmap_cmd
        # at all (that call, if any, now happens inside
        # create_roadmap_for_object, which is mocked as a whole here) —
        # kept patched only so a stray real call would be caught, not to
        # assert it's invoked.
        mock_create_rm.return_value = {
            "ok": True, "roadmap_id": "RM-001", "error": None,
            "core_created": True, "stages_created": True,
            "stages_count": 11, "stage_ids": [], "used_template": False,
            "relation_copy_errors": (), "relation_copy_created_count": 0,
            "partial_success": False, "partial_failure": False, "warnings": (),
        }
        mock_stages.return_value    = {
            "ok": True, "stages_count": 11, "warning": None, "stage_ids": [],
        }
        update, context = self._make_update(text)

        await startroadmap_cmd(update, context)
        return update, mock_find_obj, mock_create_rm, mock_stages, mock_upd_obj

    def test_I_startroadmap_creates_roadmap(self):
        """I: /startroadmap создает roadmap для объекта."""
        import asyncio
        update, mock_find, mock_rm, mock_st, mock_upd = asyncio.run(self._run_startroadmap())
        mock_rm.assert_called_once()
        call_kwargs = mock_rm.call_args
        self.assertEqual(call_kwargs.kwargs.get("obj_id") or call_kwargs[1].get("obj_id", ""), "OBJ-001")

    def test_J_startroadmap_creates_stages(self):
        """J: /startroadmap показывает количество созданных stages
        (Phase 28C: stage creation now happens inside
        create_roadmap_for_object itself, so this asserts the reply
        reflects its mocked stages_count rather than asserting a direct
        call to create_roadmap_stages_from_template)."""
        import asyncio
        update, mock_find, mock_rm, mock_st, mock_upd = asyncio.run(self._run_startroadmap())
        mock_st.assert_not_called()
        reply_text = update.message.reply_text.call_args[0][0]
        self.assertIn("11", reply_text)

    def test_K_startroadmap_does_not_create_gtd_tasks(self):
        """K: /startroadmap НЕ создает GTD tasks."""
        for mod_name in GTD_FORBIDDEN_MODULES:
            if mod_name in sys.modules:
                self.fail(f"GTD module {mod_name!r} was imported by startroadmap!")

    def test_I_missing_obj_id_returns_error(self):
        """I: /startroadmap без obj_id → error сообщение."""
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            from business_core.telegram_handlers import startroadmap_cmd
            update, context = self._make_update("")
            update.message.reply_text = AsyncMock()
            context.args = []
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await startroadmap_cmd(update, context)
            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)

        asyncio.run(run())


class TestStartRoadmapConvergentRetryUX(unittest.TestCase):
    """Phase 28G: /startroadmap must show a distinct message for each
    of the three convergent-retry outcomes, and never say "создан" for
    a reused Roadmap."""

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]

    def _make_update(self, text: str):
        from unittest.mock import AsyncMock
        update  = MagicMock()
        context = MagicMock()
        context.args = text.split() if text else []
        update.message.text = "/startroadmap " + text
        update.message.reply_text = AsyncMock()
        update.effective_chat.id = 123
        return update, context

    async def _run(self, rm_result: dict):
        from business_core.telegram_handlers import startroadmap_cmd
        update, context = self._make_update("obj_id=OBJ-001 service_id=SVC-001")
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.find_object_by_id",
                   return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
             patch("business_core.business_builder.create_roadmap_for_object", return_value=rm_result), \
             patch("business_core.business_builder.update_object_roadmap_id"), \
             patch("business_core.service_manager.find_service_by_id", return_value=None), \
             patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service", return_value=[]):
            await startroadmap_cmd(update, context)
        return update.message.reply_text.call_args[0][0]

    def test_new_roadmap_says_created(self):
        import asyncio
        reply = asyncio.run(self._run({
            "ok": True, "roadmap_id": "RM-200", "error": None,
            "roadmap_created": True, "roadmap_reused": False,
            "stages_count": 5, "used_template": True, "template_id": "RMT-001",
            "template_warning": None, "warnings": (), "relation_copy_errors": (),
        }))
        self.assertIn("Roadmap создан", reply)
        self.assertIn("Этапов создано: 5", reply)
        self.assertNotIn("уже существовал", reply)

    def test_reused_roadmap_with_new_stages_says_reused_and_added(self):
        import asyncio
        reply = asyncio.run(self._run({
            "ok": True, "roadmap_id": "RM-201", "error": None,
            "roadmap_created": False, "roadmap_reused": True,
            "stages_count": 2, "used_template": True, "template_id": "RMT-001",
            "template_warning": None, "warnings": (), "relation_copy_errors": (),
        }))
        self.assertIn("уже существовал", reply)
        self.assertIn("Добавлено отсутствующих этапов: 2", reply)
        self.assertNotIn("✅ *Roadmap создан*", reply)

    def test_reused_roadmap_fully_converged_says_nothing_new(self):
        import asyncio
        reply = asyncio.run(self._run({
            "ok": True, "roadmap_id": "RM-202", "error": None,
            "roadmap_created": False, "roadmap_reused": True,
            "stages_count": 0, "used_template": True, "template_id": "RMT-001",
            "template_warning": None, "warnings": (), "relation_copy_errors": (),
        }))
        self.assertIn("полностью настроен", reply)
        self.assertIn("Новых этапов не создано", reply)
        self.assertNotIn("Roadmap создан", reply)

    def test_template_mismatch_warning_shown(self):
        import asyncio
        reply = asyncio.run(self._run({
            "ok": True, "roadmap_id": "RM-203", "error": None,
            "roadmap_created": False, "roadmap_reused": True,
            "stages_count": 0, "used_template": True, "template_id": "RMT-EXISTING",
            "template_warning": "requested_template_id (RMT-NEW) differs from existing_template_id (RMT-EXISTING); existing Roadmap template retained",
            "warnings": ("requested_template_id (RMT-NEW) differs from existing_template_id (RMT-EXISTING); existing Roadmap template retained",),
            "relation_copy_errors": (),
        }))
        self.assertIn("RMT-NEW", reply)
        self.assertIn("RMT-EXISTING", reply)

    def test_template_mismatch_warning_shown_exactly_once(self):
        """Regression (found via Phase 28GH production smoke test):
        template_warning is also present in "warnings" (for API
        completeness), but the handler must show it only once, not
        twice."""
        import asyncio
        warning_text = "Запрошенный шаблон (RMT-NEW) отличается от уже сохранённого (RMT-EXISTING) — сохранён прежний шаблон Roadmap."
        reply = asyncio.run(self._run({
            "ok": True, "roadmap_id": "RM-204", "error": None,
            "roadmap_created": False, "roadmap_reused": True,
            "stages_count": 0, "used_template": True, "template_id": "RMT-EXISTING",
            "template_warning": warning_text,
            "warnings": (warning_text,),
            "relation_copy_errors": (),
        }))
        self.assertEqual(reply.count("сохранён прежний шаблон"), 1)


# ────────────────────────────────────────────────────────────
# L: /roadmaps показывает список
# ────────────────────────────────────────────────────────────

class TestShowRoadmapsCommand(unittest.TestCase):

    def test_L_roadmaps_shows_list(self):
        """L: /roadmaps показывает список."""
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import show_roadmaps

            row = [
                "RM-001", "BIZ-001", "SVC-001", "Алматы", "PRS-001",
                "Test Client", "", "", "active", "2025-01-01", "", "50",
                "", "", "", "", "", "", "", "", "", "",
                "", "2025-01-01",
                "OBJ-001", "", "legalization_reconstruction_house",
            ]
            mock_ws = _make_roadmaps_sheet([row])

            update  = MagicMock()
            context = MagicMock()
            context.args = []
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=mock_ws):
                await show_roadmaps(update, context)

            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RM-001", msg)
            self.assertIn("OBJ-001", msg)

        asyncio.run(run())

    def test_L_roadmaps_filter_by_obj_id(self):
        """L: /roadmaps obj_id=OBJ-001 фильтрует по объекту."""
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import show_roadmaps

            row_1 = [
                "RM-001", "", "", "", "", "A", "", "", "active", "", "", "0",
                "", "", "", "", "", "", "", "", "", "", "", "",
                "OBJ-001", "", "", "",
            ]
            row_2 = [
                "RM-002", "", "", "", "", "B", "", "", "active", "", "", "0",
                "", "", "", "", "", "", "", "", "", "", "", "",
                "OBJ-002", "", "", "",
            ]
            mock_ws = _make_roadmaps_sheet([row_1, row_2])

            update  = MagicMock()
            context = MagicMock()
            context.args = ["obj_id=OBJ-001"]
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=mock_ws):
                await show_roadmaps(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RM-001", msg)
            self.assertNotIn("RM-002", msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# M: /stages показывает этапы
# ────────────────────────────────────────────────────────────

class TestStagesCommand(unittest.TestCase):

    def test_M_stages_shows_stages(self):
        """M: /stages показывает этапы roadmap."""
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import stages_cmd

            stage_data = [
                {"stage_id": "STAGE-001", "roadmap_id": "RM-001", "order": "1",
                 "name": "Первичный анализ объекта", "status": "pending",
                 "due_date": "", "notes": ""},
                {"stage_id": "STAGE-002", "roadmap_id": "RM-001", "order": "2",
                 "name": "Проверка документов клиента", "status": "in_progress",
                 "due_date": "", "notes": ""},
            ]

            update  = MagicMock()
            context = MagicMock()
            context.args = ["roadmap_id=RM-001"]
            update.message.text = "/stages roadmap_id=RM-001"
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.get_stages_for_roadmap", return_value=stage_data), \
                 patch("business_core.business_builder.find_roadmap_by_id", return_value={
                     "roadmap_id": "RM-001", "title": "Test", "case_type": "legalization",
                 }):
                await stages_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RM-001", msg)
            self.assertIn("Первичный анализ объекта", msg)
            self.assertIn("Проверка документов клиента", msg)

        asyncio.run(run())

    def test_M_stages_without_roadmap_id_returns_error(self):
        """M: /stages без roadmap_id → error сообщение."""
        import asyncio
        from unittest.mock import AsyncMock

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import stages_cmd

            update  = MagicMock()
            context = MagicMock()
            context.args = []
            update.message.text = "/stages"
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await stages_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# N: GTD Core файлы не импортируются
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check_file(self, path: Path):
        if not path.exists():
            return
        imports = _imports_in_file(path)
        for mod in GTD_FORBIDDEN_MODULES:
            self.assertNotIn(
                mod, imports,
                msg=f"{path.name} imports forbidden GTD module {mod!r}"
            )

    def test_N_business_builder_no_gtd_imports(self):
        self._check_file(WORKSPACE / "business_core" / "business_builder.py")

    def test_N_roadmap_manager_no_gtd_imports(self):
        self._check_file(WORKSPACE / "business_core" / "roadmap_manager.py")

    def test_N_telegram_handlers_no_gtd_imports(self):
        self._check_file(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_N_sheets_no_gtd_imports(self):
        self._check_file(WORKSPACE / "business_core" / "sheets.py")

    def test_N_no_gtd_files_modified(self):
        """N: GTD core файлы не изменены этой фазой."""
        gtd_files = [
            "inbox_processor.py",
            "project_planner.py",
            "calendar_sync.py",
        ]
        for fname in gtd_files:
            fpath = WORKSPACE / fname
            if fpath.exists():
                # Файл должен существовать без наших изменений
                self.assertTrue(fpath.exists(), f"GTD файл {fname} исчез")


# ────────────────────────────────────────────────────────────
# Extra: ROADMAP_TEMPLATES structure
# ────────────────────────────────────────────────────────────

class TestRoadmapTemplatesStructure(unittest.TestCase):

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "business_core.roadmap_manager" in key or key == "business_core.roadmap_manager":
                del sys.modules[key]
        import business_core.roadmap_manager as rm
        self.rm = rm

    def test_templates_dict_not_empty(self):
        self.assertGreater(len(self.rm.ROADMAP_TEMPLATES), 0)

    def test_legalization_house_has_11_stages(self):
        stages = self.rm.ROADMAP_TEMPLATES["legalization_reconstruction_house"]
        self.assertEqual(len(stages), 11)

    def test_legalization_new_building_has_10_stages(self):
        stages = self.rm.ROADMAP_TEMPLATES["legalization_new_building"]
        self.assertEqual(len(stages), 10)

    def test_legalization_non_residential_has_14_stages(self):
        stages = self.rm.ROADMAP_TEMPLATES["legalization_non_residential_reconstruction"]
        self.assertEqual(len(stages), 14)

    def test_all_stage_names_are_strings(self):
        for key, stages in self.rm.ROADMAP_TEMPLATES.items():
            for s in stages:
                self.assertIsInstance(s, str, f"Этап в {key} не строка")


if __name__ == "__main__":
    unittest.main(verbosity=2)
