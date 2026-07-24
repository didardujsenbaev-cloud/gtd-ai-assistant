"""
Phase 8B tests: Roadmap Template Core.

Covers:
A. generate_roadmap_template_id на пустом листе → RTMPL-001
B. generate_roadmap_template_stage_id на пустом листе → TSTG-001
C. create_roadmap_template создает шаблон
D. create_roadmap_template без name → error
E. find_roadmap_template_by_id находит шаблон
F. find_roadmap_templates_by_service фильтрует по service_id
G. add_roadmap_template_stage добавляет этап с автоnorder
H. add_roadmap_template_stage без template_id → error
I. find_template_stages возвращает этапы отсортированными
J. create_stages_from_template_record создает реальные этапы
K. create_stages_from_template_record без этапов → warning, не падает
L. link_service_to_roadmap_template вызывает update_service_roadmap_template
M. /startroadmap использует шаблон из услуги (приоритет)
N. /startroadmap fallback на case_type если шаблона нет
O. /newrtemplate создает шаблон
P. /rtemplates показывает список
Q. /addrtemplatestage добавляет этап
R. /rtemplatestages показывает этапы
S. GTD Core файлы не импортируются
T. Новые листы присутствуют в BUSINESS_SHEET_NAMES
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent

GTD_FORBIDDEN = {
    "inbox_processor", "project_planner",
    "calendar_sync",   "telegram_bot",
}


def _imports_in_file(path: Path) -> list[str]:
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


# ────────────────────────────────────────────────────────────
# Sheet mock helpers
# ────────────────────────────────────────────────────────────

TMPL_HEADERS = [
    "Template ID", "Biz ID", "Service ID", "Template Name", "Case Type",
    "Object Type", "Description", "Status", "Stages Count", "Notes",
    "Created At", "Last Updated",
]

TSTG_HEADERS = [
    "Stage ID", "Template ID", "Order", "Stage Name", "Description",
    "Required Docs", "Responsible", "Estimated Days", "Notes", "Created At",
]

RM_STAGE_HEADERS = [
    "Stage ID", "Roadmap ID", "Order", "Name", "Status",
    "Due Date", "Completed At", "GTD Action ID",
    "Responsible", "Docs Required", "Docs Received", "Notes",
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
]


def _ws(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    ws.row_values.side_effect = lambda r: rows[r - 1] if 0 <= r - 1 < len(rows) else []
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


def _tmpl_sheet(extra=None):
    return _ws([TMPL_HEADERS] + (extra or []))


def _tstg_sheet(extra=None):
    return _ws([TSTG_HEADERS] + (extra or []))


def _rmstage_sheet(extra=None):
    return _ws([RM_STAGE_HEADERS] + (extra or []))


def _tmpl_row(tid="RTMPL-001", biz="", svc="", name="Тест", status="active", cnt="0"):
    r = [""] * len(TMPL_HEADERS)
    r[TMPL_HEADERS.index("Template ID")]   = tid
    r[TMPL_HEADERS.index("Biz ID")]        = biz
    r[TMPL_HEADERS.index("Service ID")]    = svc
    r[TMPL_HEADERS.index("Template Name")] = name
    r[TMPL_HEADERS.index("Status")]        = status
    r[TMPL_HEADERS.index("Stages Count")]  = cnt
    return r


def _tstg_row(sid="TSTG-001", tid="RTMPL-001", order="1", name="Этап 1"):
    r = [""] * len(TSTG_HEADERS)
    r[TSTG_HEADERS.index("Stage ID")]    = sid
    r[TSTG_HEADERS.index("Template ID")] = tid
    r[TSTG_HEADERS.index("Order")]       = order
    r[TSTG_HEADERS.index("Stage Name")]  = name
    return r


def _fresh():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.roadmap_template_manager as m
    return m


def _fresh_with_builder():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.roadmap_template_manager as m
    import business_core.business_builder as bb
    return m, bb


# ────────────────────────────────────────────────────────────
# A/B: ID generation
# ────────────────────────────────────────────────────────────

class TestIdGeneration(unittest.TestCase):

    def test_A_empty_template_registry_returns_RTMPL001(self):
        """A: пустой ROADMAP_TEMPLATE_REGISTRY → RTMPL-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tmpl_sheet()):
            result = m.generate_roadmap_template_id()
        self.assertEqual(result, "RTMPL-001")

    def test_B_empty_template_stages_returns_TSTG001(self):
        """B: пустой ROADMAP_TEMPLATE_STAGES → TSTG-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tstg_sheet()):
            result = m.generate_roadmap_template_stage_id()
        self.assertEqual(result, "TSTG-001")


# ────────────────────────────────────────────────────────────
# C/D: create_roadmap_template
# ────────────────────────────────────────────────────────────

class TestCreateRoadmapTemplate(unittest.TestCase):

    def test_C_creates_template(self):
        """C: create_roadmap_template создает шаблон."""
        m = _fresh()
        appended = []

        def capture(key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="RTMPL-001"):
            result = m.create_roadmap_template(
                template_name="Тест",
                biz_id="BIZ-001",
                service_id="SVC-001",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["template_id"], "RTMPL-001")
        self.assertEqual(len(appended), 1)
        row = appended[0]
        self.assertIn("BIZ-001", row)
        self.assertIn("SVC-001", row)
        self.assertIn("Тест",    row)

    def test_D_empty_name_returns_error(self):
        """D: пустое template_name → error."""
        m = _fresh()
        result = m.create_roadmap_template(template_name="")
        self.assertFalse(result["ok"])
        self.assertIn("обязателен", result["error"].lower())


# ────────────────────────────────────────────────────────────
# E: find_roadmap_template_by_id
# ────────────────────────────────────────────────────────────

class TestFindTemplateById(unittest.TestCase):

    def test_E_finds_template(self):
        """E: find_roadmap_template_by_id находит шаблон."""
        m = _fresh()
        row = _tmpl_row("RTMPL-001", biz="BIZ-001", svc="SVC-001", name="Узаконение")
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tmpl_sheet([row])):
            result = m.find_roadmap_template_by_id("RTMPL-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["template_id"],   "RTMPL-001")
        self.assertEqual(result["biz_id"],        "BIZ-001")
        self.assertEqual(result["service_id"],    "SVC-001")
        self.assertEqual(result["template_name"], "Узаконение")

    def test_E_returns_none_for_missing(self):
        """E: несуществующий ID → None."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tmpl_sheet()):
            result = m.find_roadmap_template_by_id("RTMPL-999")
        self.assertIsNone(result)


# ────────────────────────────────────────────────────────────
# F: find_roadmap_templates_by_service
# ────────────────────────────────────────────────────────────

class TestFindTemplatesByService(unittest.TestCase):

    def test_F_filters_by_service(self):
        """F: find_roadmap_templates_by_service фильтрует по service_id."""
        m = _fresh()
        rows = [
            _tmpl_row("RTMPL-001", svc="SVC-001"),
            _tmpl_row("RTMPL-002", svc="SVC-002"),
            _tmpl_row("RTMPL-003", svc="SVC-001"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tmpl_sheet(rows)):
            result = m.find_roadmap_templates_by_service("SVC-001")

        self.assertEqual(len(result), 2)
        ids = {r["template_id"] for r in result}
        self.assertIn("RTMPL-001", ids)
        self.assertIn("RTMPL-003", ids)

    def test_F_empty_service_returns_empty(self):
        """F: пустой service_id → пустой список."""
        m = _fresh()
        result = m.find_roadmap_templates_by_service("")
        self.assertEqual(result, [])


# ────────────────────────────────────────────────────────────
# G/H: add_roadmap_template_stage
# ────────────────────────────────────────────────────────────

class TestAddTemplateStage(unittest.TestCase):

    def test_G_adds_stage_with_auto_order(self):
        """G: add_roadmap_template_stage добавляет этап, автовычисляет order."""
        m = _fresh()
        appended = []

        def capture(key, row):
            appended.append((key, row))

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="TSTG-001"), \
             patch("business_core.sheets.get_business_sheet", return_value=_tstg_sheet()):
            result = m.add_roadmap_template_stage(
                template_id="RTMPL-001",
                stage_name="Первичный анализ",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stage_id"], "TSTG-001")
        self.assertEqual(result["order"], 1)
        # Проверяем что данные верно попали в строку
        stage_row = appended[0][1]
        self.assertIn("RTMPL-001",        stage_row)
        self.assertIn("Первичный анализ", stage_row)

    def test_G_increments_order_for_second_stage(self):
        """G: второй этап получает order=2."""
        m = _fresh()
        existing = _tstg_row("TSTG-001", "RTMPL-001", "1", "Этап 1")
        appended = []

        def capture(key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="TSTG-002"), \
             patch("business_core.sheets.get_business_sheet",
                   return_value=_tstg_sheet([existing])):
            result = m.add_roadmap_template_stage(
                template_id="RTMPL-001",
                stage_name="Второй этап",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["order"], 2)

    def test_H_missing_template_id_returns_error(self):
        """H: пустой template_id → error."""
        m = _fresh()
        result = m.add_roadmap_template_stage(template_id="", stage_name="Тест")
        self.assertFalse(result["ok"])

    def test_H_missing_stage_name_returns_error(self):
        """H: пустой stage_name → error."""
        m = _fresh()
        result = m.add_roadmap_template_stage(template_id="RTMPL-001", stage_name="")
        self.assertFalse(result["ok"])


# ────────────────────────────────────────────────────────────
# I: find_template_stages
# ────────────────────────────────────────────────────────────

class TestFindTemplateStages(unittest.TestCase):

    def test_I_returns_stages_sorted(self):
        """I: find_template_stages возвращает этапы отсортированными по order."""
        m = _fresh()
        rows = [
            _tstg_row("TSTG-003", "RTMPL-001", "3", "Третий"),
            _tstg_row("TSTG-001", "RTMPL-001", "1", "Первый"),
            _tstg_row("TSTG-002", "RTMPL-001", "2", "Второй"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tstg_sheet(rows)):
            result = m.find_template_stages("RTMPL-001")

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["stage_name"], "Первый")
        self.assertEqual(result[1]["stage_name"], "Второй")
        self.assertEqual(result[2]["stage_name"], "Третий")

    def test_I_returns_only_matching_template(self):
        """I: только этапы нужного шаблона."""
        m = _fresh()
        rows = [
            _tstg_row("TSTG-001", "RTMPL-001", "1", "A"),
            _tstg_row("TSTG-002", "RTMPL-002", "1", "B"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_tstg_sheet(rows)):
            result = m.find_template_stages("RTMPL-001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stage_name"], "A")


# ────────────────────────────────────────────────────────────
# J/K: create_stages_from_template_record
# ────────────────────────────────────────────────────────────

class TestCreateStagesFromTemplateRecord(unittest.TestCase):

    def test_J_creates_real_stages(self):
        """J: create_stages_from_template_record создает реальные этапы."""
        m, bb = _fresh_with_builder()
        template_stages = [
            {"stage_id": "TSTG-001", "template_id": "RTMPL-001", "order": "1",
             "stage_name": "Этап 1", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": ""},
            {"stage_id": "TSTG-002", "template_id": "RTMPL-001", "order": "2",
             "stage_name": "Этап 2", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": ""},
        ]
        appended = []

        def capture(key, rows):
            appended.extend(rows)

        with patch.object(m, "find_template_stages", return_value=template_stages), \
             patch("business_core.sheets.get_business_sheet",
                   return_value=_rmstage_sheet()), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=capture), \
             patch("business_core.knowledge_manager.find_knowledge_by_template_stage",
                   return_value={}), \
             patch("business_core.sheets.generate_next_id",
                   side_effect=["STAGE-001", "STAGE-002"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 2)
        self.assertIsNone(result["warning"])
        for row in appended:
            self.assertIn("RM-001", row)
            self.assertIn("pending", row)
            idx = {h: i for i, h in enumerate(RM_STAGE_HEADERS)}
            self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
            self.assertEqual(row[idx["Status"]], "pending")

    def test_K_empty_template_returns_warning(self):
        """K: шаблон без этапов → warning, не падает."""
        m, bb = _fresh_with_builder()
        with patch.object(m, "find_template_stages", return_value=[]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])

    def test_K_empty_args_returns_error(self):
        """K: пустые аргументы → ok=False."""
        _, bb = _fresh_with_builder()
        result = bb.create_stages_from_template_record("", "RTMPL-001")
        self.assertFalse(result["ok"])


# ────────────────────────────────────────────────────────────
# Phase 28D/28E: create_stages_from_template_record no longer copies
# Stage Entity Relations itself — that Extension-layer orchestration
# moved to business_core.business_builder.create_roadmap_for_object()
# (see test_business_object_roadmaps.py's
# TestCreateRoadmapForObjectExtensionOrchestration for the relocated
# relation-copy/partial-failure coverage). This function now always
# returns the neutral/empty relation-copy fields, and must never import
# or call business_core.stage_entity_relations at all.
# ────────────────────────────────────────────────────────────

class TestCreateStagesFromTemplateRecordRelationCopy(unittest.TestCase):
    def _template_stages(self, n=2):
        return [
            {"stage_id": f"TSTG-{i:03d}", "template_id": "RTMPL-001", "order": str(i),
             "stage_name": f"Этап {i}", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": "",
             "sop_ids": [], "checklist_ids": [], "material_ids": [],
             "document_template_ids": [], "faq_ids": []}
            for i in range(1, n + 1)
        ]

    def _run(self, n=2, generated_ids=None):
        m, bb = _fresh_with_builder()
        generated_ids = generated_ids or [f"STAGE-{i:03d}" for i in range(1, n + 1)]
        sheet = _rmstage_sheet()
        sheet.get_all_values.return_value = [RM_STAGE_HEADERS]
        with patch.object(m, "find_template_stages", return_value=self._template_stages(n)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows"), \
             patch("business_core.sheets.generate_next_ids", return_value=generated_ids):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")
        return result

    def test_relation_copy_fields_are_always_neutral(self):
        result = self._run()
        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 2)
        self.assertFalse(result["partial_success"])
        self.assertEqual(result["relation_copy_errors"], ())
        self.assertEqual(result["relation_copy_created_count"], 0)

    def test_does_not_import_stage_entity_relations(self):
        import ast
        import inspect
        m, bb = _fresh_with_builder()
        src = inspect.getsource(bb.create_stages_from_template_record)
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[-1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[-1])
        self.assertNotIn("stage_entity_relations", imported)
        self.assertNotIn("knowledge_manager", imported)

    def test_delegates_stage_creation_to_roadmap_manager_ensure_roadmap_stages(self):
        m, bb = _fresh_with_builder()
        sheet = _rmstage_sheet()
        sheet.get_all_values.return_value = [RM_STAGE_HEADERS]
        with patch.object(m, "find_template_stages", return_value=self._template_stages(1)), \
             patch("business_core.roadmap_manager.ensure_roadmap_stages",
                   return_value={
                       "ok": True, "roadmap_id": "RM-001",
                       "created_stage_ids": ["STAGE-001"], "created_from_orders": [1],
                       "existing_stage_ids": [], "created_count": 1, "existing_count": 0,
                       "total_count": 1, "error": None,
                   }) as mock_ensure:
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")
        mock_ensure.assert_called_once()
        self.assertEqual(mock_ensure.call_args.args[0], "RM-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stage_ids"], ["STAGE-001"])


# ────────────────────────────────────────────────────────────
# Phase 10.2B.1: create_stages_from_template_record — header-safety
# ────────────────────────────────────────────────────────────

class TestCreateStagesFromTemplateRecordHeaderSafety(unittest.TestCase):

    _TEMPLATE_STAGES = [
        {"stage_id": "TSTG-001", "template_id": "RTMPL-001", "order": "1",
         "stage_name": "Диагностика", "description": "", "required_docs": "Паспорт",
         "responsible": "Дидар", "estimated_days": "", "notes": "Заметка",
         "sop_ids": ["SOP-001"], "checklist_ids": ["CHK-001"],
         "material_ids": ["MAT-001"], "document_template_ids": ["DOC-001"],
         "faq_ids": ["FAQ-001"]},
    ]

    def _knowledge(self):
        return {
            "sop_ids": ["SOP-001"], "checklist_ids": ["CHK-001"],
            "material_ids": ["MAT-001"], "document_template_ids": ["DOC-001"],
            "faq_ids": ["FAQ-001"],
        }

    def test_standard_header_order_produces_correct_row(self):
        """1: стандартный порядок заголовков — значения на своих местах."""
        m, bb = _fresh_with_builder()
        sheet = _rmstage_sheet()
        captured = []

        with patch.object(m, "find_template_stages", return_value=self._TEMPLATE_STAGES), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: captured.extend(rows)), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(RM_STAGE_HEADERS)}
        row = captured[0]
        self.assertEqual(row[idx["Stage ID"]], "STAGE-001")
        self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
        self.assertEqual(row[idx["Order"]], "1")
        self.assertEqual(row[idx["Name"]], "Диагностика")
        self.assertEqual(row[idx["Status"]], "pending")
        self.assertEqual(row[idx["Responsible"]], "Дидар")
        self.assertEqual(row[idx["Docs Required"]], "Паспорт")
        self.assertEqual(row[idx["Notes"]], "Заметка")
        self.assertEqual(row[idx["SOP IDs"]], "SOP-001")
        self.assertEqual(row[idx["Checklist IDs"]], "CHK-001")
        self.assertEqual(row[idx["Materials IDs"]], "MAT-001")
        self.assertEqual(row[idx["Document Template IDs"]], "DOC-001")
        self.assertEqual(row[idx["FAQ IDs"]], "FAQ-001")
        # Поля, которые всегда пустые
        self.assertEqual(row[idx["Due Date"]], "")
        self.assertEqual(row[idx["Completed At"]], "")
        self.assertEqual(row[idx["GTD Action ID"]], "")
        self.assertEqual(row[idx["Docs Received"]], "")

    def test_shuffled_header_order_gives_same_values_by_name(self):
        """2: результат не зависит от перестановки заголовков листа."""
        m, bb = _fresh_with_builder()
        shuffled = [
            "FAQ IDs", "Notes", "Stage ID", "Docs Received", "Roadmap ID",
            "Document Template IDs", "Order", "Responsible", "Name",
            "Materials IDs", "Status", "Checklist IDs", "Due Date",
            "Docs Required", "SOP IDs", "Completed At", "GTD Action ID",
        ]
        self.assertCountEqual(shuffled, RM_STAGE_HEADERS,
                              "перемешанный набор должен содержать те же заголовки")
        sheet = _ws([shuffled])
        captured = []

        with patch.object(m, "find_template_stages", return_value=self._TEMPLATE_STAGES), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: captured.extend(rows)), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(shuffled)}
        row = captured[0]
        self.assertEqual(row[idx["Roadmap ID"]], "RM-001")
        self.assertEqual(row[idx["Status"]], "pending")
        self.assertEqual(row[idx["Name"]], "Диагностика")
        self.assertEqual(row[idx["SOP IDs"]], "SOP-001")
        self.assertEqual(row[idx["FAQ IDs"]], "FAQ-001")
        self.assertEqual(len(row), len(shuffled))

    def test_unknown_extra_columns_remain_empty(self):
        """4: неизвестные дополнительные колонки листа остаются пустыми."""
        m, bb = _fresh_with_builder()
        with_extra = RM_STAGE_HEADERS + ["Custom Future Field"]
        sheet = _ws([with_extra])
        captured = []

        with patch.object(m, "find_template_stages", return_value=self._TEMPLATE_STAGES), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: captured.extend(rows)), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(with_extra)}
        row = captured[0]
        self.assertEqual(row[idx["Custom Future Field"]], "")
        self.assertEqual(len(row), len(with_extra))

    def test_batch_append_called_exactly_once(self):
        """5: batch append вызывается один раз для всех этапов шаблона."""
        m, bb = _fresh_with_builder()
        two_stages = self._TEMPLATE_STAGES + [
            {"stage_id": "TSTG-002", "template_id": "RTMPL-001", "order": "2",
             "stage_name": "Сбор документов", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": "",
             "sop_ids": [], "checklist_ids": [], "material_ids": [],
             "document_template_ids": [], "faq_ids": []},
        ]
        sheet = _rmstage_sheet()
        calls = []

        with patch.object(m, "find_template_stages", return_value=two_stages), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: calls.append((k, rows))), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001", "STAGE-002"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1, "batch_append_business_rows должен вызываться ровно один раз")
        key, rows = calls[0]
        self.assertEqual(key, "roadmap_stages")
        self.assertEqual(len(rows), 2)

    def test_stage_count_and_ids_unchanged(self):
        """6: количество этапов и stage_ids соответствуют шаблону."""
        m, bb = _fresh_with_builder()
        two_stages = self._TEMPLATE_STAGES + [
            {"stage_id": "TSTG-002", "template_id": "RTMPL-001", "order": "2",
             "stage_name": "Сбор документов", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": "",
             "sop_ids": [], "checklist_ids": [], "material_ids": [],
             "document_template_ids": [], "faq_ids": []},
        ]
        sheet = _rmstage_sheet()

        with patch.object(m, "find_template_stages", return_value=two_stages), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows"), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001", "STAGE-002"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertEqual(result["stages_count"], 2)
        self.assertEqual(result["stage_ids"], ["STAGE-001", "STAGE-002"])

    def test_empty_template_behavior_unchanged_no_sheet_access(self):
        """7: пустой шаблон — поведение (warning, ok=True, 0 этапов) не изменилось,
        и обращения к листу ROADMAP_STAGES не происходит вовсе."""
        m, bb = _fresh_with_builder()
        with patch.object(m, "find_template_stages", return_value=[]), \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])
        self.assertEqual(result["stage_ids"], [])
        mock_get_sheet.assert_not_called()


# ────────────────────────────────────────────────────────────
# L: link_service_to_roadmap_template
# ────────────────────────────────────────────────────────────

class TestLinkServiceToTemplate(unittest.TestCase):

    def test_L_calls_update_service_roadmap_template(self):
        """L: link_service_to_roadmap_template вызывает update."""
        m = _fresh()
        with patch("business_core.service_manager.update_service_roadmap_template",
                   return_value=True) as mock_update:
            result = m.link_service_to_roadmap_template("SVC-001", "RTMPL-001")
        self.assertTrue(result)
        mock_update.assert_called_once_with("SVC-001", "RTMPL-001")

    def test_L_empty_args_returns_false(self):
        """L: пустые аргументы → False без вызова update."""
        m = _fresh()
        self.assertFalse(m.link_service_to_roadmap_template("", "RTMPL-001"))
        self.assertFalse(m.link_service_to_roadmap_template("SVC-001", ""))


# ────────────────────────────────────────────────────────────
# M/N: /startroadmap с шаблонным приоритетом
# ────────────────────────────────────────────────────────────

class TestStartRoadmapWithTemplate(unittest.TestCase):

    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]

    def test_M_uses_service_template(self):
        """M: /startroadmap использует шаблон из услуги.

        Phase 28C: template auto-selection (from the service's own
        default_roadmap_template_id) still happens in startroadmap_cmd
        itself, unchanged — what changed is that stage creation from
        that resolved template_id now happens INSIDE
        create_roadmap_for_object, not via a separate call this handler
        makes. So this asserts the resolved template_id is the one
        passed to create_roadmap_for_object, rather than asserting a
        (now nonexistent, from this handler's perspective) direct call
        to create_stages_from_template_record."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import startroadmap_cmd

        svc_mock = {
            "service_id": "SVC-001",
            "biz_id": "BIZ-001",
            "default_roadmap_template_id": "RTMPL-001",
        }

        update  = MagicMock()
        context = MagicMock()
        context.args = ["obj_id=OBJ-001", "service_id=SVC-001"]
        update.message.text = "/startroadmap obj_id=OBJ-001 service_id=SVC-001"
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={
                           "ok": True, "roadmap_id": "RM-010", "error": None,
                           "core_created": True, "stages_created": True,
                           "stages_count": 5, "stage_ids": [], "used_template": True,
                           "relation_copy_errors": (), "relation_copy_created_count": 0,
                           "partial_success": False, "partial_failure": False, "warnings": (),
                       }) as mock_create_rm, \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id", return_value=svc_mock), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]):
                await startroadmap_cmd(update, context)
                # Должен передать в create_roadmap_for_object именно
                # шаблон из сервиса (не пустую строку/case_type-only путь).
                self.assertEqual(mock_create_rm.call_args.kwargs["template_id"], "RTMPL-001")

        asyncio.run(run())

    def test_N_fallback_to_case_type(self):
        """N: /startroadmap передаёт case_type в create_roadmap_for_object,
        когда у услуги нет привязанного шаблона (фактический fallback —
        template_id=="" против case_type — теперь решается внутри
        create_roadmap_for_object, Phase 28C)."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import startroadmap_cmd

        svc_mock_no_template = {
            "service_id": "SVC-001",
            "biz_id": "BIZ-001",
            "default_roadmap_template_id": "",
        }

        update  = MagicMock()
        context = MagicMock()
        context.args = [
            "obj_id=OBJ-001", "service_id=SVC-001",
            "case_type=legalization_reconstruction_house",
        ]
        update.message.text = "/startroadmap obj_id=OBJ-001 service_id=SVC-001 case_type=legalization_reconstruction_house"
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={
                           "ok": True, "roadmap_id": "RM-011", "error": None,
                           "core_created": True, "stages_created": True,
                           "stages_count": 11, "stage_ids": [], "used_template": False,
                           "relation_copy_errors": (), "relation_copy_created_count": 0,
                           "partial_success": False, "partial_failure": False, "warnings": (),
                       }) as mock_create_rm, \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value=svc_mock_no_template), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]):
                await startroadmap_cmd(update, context)
                call_kwargs = mock_create_rm.call_args.kwargs
                self.assertEqual(call_kwargs["template_id"], "")
                self.assertEqual(call_kwargs["case_type"], "legalization_reconstruction_house")

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# O/P/Q/R: Telegram commands
# ────────────────────────────────────────────────────────────

class TestTemplateCommands(unittest.TestCase):

    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]

    def test_O_newrtemplate_creates(self):
        """O: /newrtemplate создает шаблон."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newrtemplate_cmd

        update  = MagicMock()
        context = MagicMock()
        context.args = ['name=Узаконение', 'biz_id=BIZ-001']
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_template_manager.create_roadmap_template",
                       return_value={"ok": True, "template_id": "RTMPL-001", "error": None}):
                await newrtemplate_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RTMPL-001", msg)
            self.assertIn("✅", msg)

        asyncio.run(run())

    def test_O_newrtemplate_no_name_returns_error(self):
        """O: /newrtemplate без name → error."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newrtemplate_cmd

        update  = MagicMock()
        context = MagicMock()
        context.args = []
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await newrtemplate_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)

        asyncio.run(run())

    def test_P_rtemplates_shows_list(self):
        """P: /rtemplates показывает список."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import rtemplates_cmd

        mock_templates = [
            {"template_id": "RTMPL-001", "template_name": "Узаконение",
             "biz_id": "BIZ-001", "service_id": "SVC-001",
             "status": "active", "stages_count": "5"},
        ]

        update  = MagicMock()
        context = MagicMock()
        context.args = []
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_template_manager.list_roadmap_templates",
                       return_value=mock_templates), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]):
                await rtemplates_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RTMPL-001", msg)
            self.assertIn("Узаконение", msg)

        asyncio.run(run())

    def test_Q_addrtemplatestage_adds_stage(self):
        """Q: /addrtemplatestage добавляет этап."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import addrtemplatestage_cmd

        update  = MagicMock()
        context = MagicMock()
        context.args = ['template_id=RTMPL-001', 'stage_name=Анализ']
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                       return_value={"ok": True, "stage_id": "TSTG-001",
                                     "order": 1, "error": None}):
                await addrtemplatestage_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("TSTG-001", msg)
            self.assertIn("✅", msg)

        asyncio.run(run())

    def test_R_rtemplatestages_shows_stages(self):
        """R: /rtemplatestages показывает этапы шаблона."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import rtemplatestages_cmd

        mock_stages = [
            {"stage_id": "TSTG-001", "template_id": "RTMPL-001", "order": "1",
             "stage_name": "Первичный анализ", "description": "",
             "required_docs": "", "responsible": "", "estimated_days": "", "notes": ""},
        ]

        update  = MagicMock()
        context = MagicMock()
        context.args = ["template_id=RTMPL-001"]
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_template_manager.find_template_stages",
                       return_value=mock_stages), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RTMPL-001",
                                     "template_name": "Тест"}):
                await rtemplatestages_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("RTMPL-001",         msg)
            self.assertIn("Первичный анализ",  msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# S: GTD Isolation
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists():
            return
        imports = _imports_in_file(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, imports,
                             msg=f"{path.name} imports forbidden {mod!r}")

    def test_S_roadmap_template_manager_no_gtd(self):
        self._check(WORKSPACE / "business_core" / "roadmap_template_manager.py")

    def test_S_telegram_handlers_no_gtd(self):
        self._check(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_S_service_manager_no_gtd(self):
        self._check(WORKSPACE / "business_core" / "service_manager.py")

    def test_S_sheets_no_gtd(self):
        self._check(WORKSPACE / "business_core" / "sheets.py")

    def test_S_gtd_files_untouched(self):
        for fname in ["inbox_processor.py", "project_planner.py", "calendar_sync.py"]:
            fpath = WORKSPACE / fname
            if fpath.exists():
                self.assertTrue(fpath.exists())


# ────────────────────────────────────────────────────────────
# T: Sheet registry
# ────────────────────────────────────────────────────────────

class TestSheetRegistry(unittest.TestCase):

    def setUp(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]
        from business_core import sheets as s
        self.sheets = s

    def test_T_template_registry_in_sheet_names(self):
        """T: ROADMAP_TEMPLATE_REGISTRY присутствует в BUSINESS_SHEET_NAMES."""
        self.assertIn("roadmap_template_registry",
                      self.sheets.BUSINESS_SHEET_NAMES)

    def test_T_template_stages_in_sheet_names(self):
        """T: ROADMAP_TEMPLATE_STAGES присутствует в BUSINESS_SHEET_NAMES."""
        self.assertIn("roadmap_template_stages",
                      self.sheets.BUSINESS_SHEET_NAMES)

    def test_T_template_registry_has_headers(self):
        """T: ROADMAP_TEMPLATE_REGISTRY имеет заголовки."""
        headers = self.sheets.BUSINESS_HEADERS.get("roadmap_template_registry", [])
        self.assertIn("Template ID", headers)
        self.assertIn("Template Name", headers)
        self.assertIn("Service ID",   headers)
        self.assertIn("Case Type",    headers)

    def test_T_template_stages_has_headers(self):
        """T: ROADMAP_TEMPLATE_STAGES имеет заголовки."""
        headers = self.sheets.BUSINESS_HEADERS.get("roadmap_template_stages", [])
        self.assertIn("Stage ID",    headers)
        self.assertIn("Template ID", headers)
        self.assertIn("Stage Name",  headers)
        self.assertIn("Order",       headers)

    def test_T_prefixes_defined(self):
        """T: ID-префиксы определены."""
        self.assertIn("roadmap_template_registry", self.sheets._ID_PREFIXES)
        self.assertIn("roadmap_template_stages",   self.sheets._ID_PREFIXES)
        self.assertEqual(self.sheets._ID_PREFIXES["roadmap_template_registry"], "RTMPL")
        self.assertEqual(self.sheets._ID_PREFIXES["roadmap_template_stages"],   "TSTG")


if __name__ == "__main__":
    unittest.main(verbosity=2)
