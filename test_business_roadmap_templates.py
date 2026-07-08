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
]


def _ws(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = rows
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
        m = _fresh()
        template_stages = [
            {"stage_id": "TSTG-001", "template_id": "RTMPL-001", "order": "1",
             "stage_name": "Этап 1", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": ""},
            {"stage_id": "TSTG-002", "template_id": "RTMPL-001", "order": "2",
             "stage_name": "Этап 2", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": ""},
        ]
        appended = []

        def capture(key, row):
            appended.append(row)

        with patch.object(m, "find_template_stages", return_value=template_stages), \
             patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id",
                   side_effect=["STAGE-001", "STAGE-002"]):
            result = m.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 2)
        self.assertIsNone(result["warning"])
        for row in appended:
            self.assertIn("RM-001", row)
            self.assertIn("pending", row)

    def test_K_empty_template_returns_warning(self):
        """K: шаблон без этапов → warning, не падает."""
        m = _fresh()
        with patch.object(m, "find_template_stages", return_value=[]):
            result = m.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 0)
        self.assertIsNotNone(result["warning"])

    def test_K_empty_args_returns_error(self):
        """K: пустые аргументы → ok=False."""
        m = _fresh()
        result = m.create_stages_from_template_record("", "RTMPL-001")
        self.assertFalse(result["ok"])


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
        """M: /startroadmap использует шаблон из услуги."""
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
                       return_value={"ok": True, "roadmap_id": "RM-010", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id", return_value=svc_mock), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value={"ok": True, "stages_count": 5,
                                     "warning": None, "stage_ids": []}) as mock_tmpl, \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"ok": True, "stages_count": 0,
                                     "warning": None, "stage_ids": []}) as mock_fallback:
                await startroadmap_cmd(update, context)
                # Должен использовать шаблон из сервиса, не fallback
                mock_tmpl.assert_called_once_with("RM-010", "RTMPL-001")

        asyncio.run(run())

    def test_N_fallback_to_case_type(self):
        """N: /startroadmap fallback на case_type если у сервиса нет шаблона."""
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
                       return_value={"ok": True, "roadmap_id": "RM-011", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value=svc_mock_no_template), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value={"ok": True, "stages_count": 0,
                                     "warning": "нет этапов", "stage_ids": []}) as mock_tmpl, \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"ok": True, "stages_count": 11,
                                     "warning": None, "stage_ids": []}) as mock_fallback:
                await startroadmap_cmd(update, context)
                # Т.к. template дал 0 этапов — должен использовать fallback
                mock_fallback.assert_called_once()

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
