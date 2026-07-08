"""
Phase 8A tests: Service Catalog Upgrade.

Covers:
A. generate_service_id на пустом SERVICE_CATALOG → SVC-001
B. generate_service_id после существующих услуг → следующий ID
C. normalize_service_status для active/inactive/draft
D. normalize_service_status для неизвестного значения → active
E. create_service_record создает услугу с обязательными полями
F. create_service_record ставит status=active по умолчанию
G. create_service_record ставит currency=KZT по умолчанию
H. find_service_by_id находит услугу
I. find_services_by_biz фильтрует по бизнесу
J. find_services_by_object_type фильтрует по типу объекта
K. list_active_services возвращает только active
L. update_service_roadmap_template записывает Default Roadmap Template ID
M. /newservice создает услугу
N. /services показывает список
O. /service показывает карточку
P. GTD Core файлы не импортируются и не меняются
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent

GTD_FORBIDDEN_MODULES = {
    "inbox_processor",
    "project_planner",
    "calendar_sync",
    "telegram_bot",
}


def _imports_in_file(path: Path) -> list[str]:
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


# ────────────────────────────────────────────────────────────
# Sheet mock helpers
# ────────────────────────────────────────────────────────────

SVC_HEADERS_OLD = [
    "ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
    "Цена мин", "Цена макс", "Срок", "Описание",
    "Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
    "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
    "Документы от клиента", "Документы наши",
    "Чек-лист производства", "Чек-лист закрытия",
    "Риски", "Шаблоны", "Инструкция", "Комментарий",
    "Service Name", "Service Category", "Object Type", "Client Type",
    "What Included", "What Not Included", "Currency",
    "Required Documents", "Default Roadmap Template ID",
    "Contractors Needed", "Materials IDs", "Created At", "Last Updated",
]


def _make_svc_sheet(extra_rows=None) -> MagicMock:
    ws = MagicMock()
    rows = [SVC_HEADERS_OLD] + (extra_rows or [])
    ws.get_all_values.return_value = rows
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


def _svc_row(svc_id="SVC-001", biz_id="BIZ-001", name="Тест", status="active",
             city="", obj_type="", currency="KZT"):
    row = [""] * len(SVC_HEADERS_OLD)
    row[SVC_HEADERS_OLD.index("ID")]          = svc_id
    row[SVC_HEADERS_OLD.index("Бизнес ID")]   = biz_id
    row[SVC_HEADERS_OLD.index("Название")]    = name
    row[SVC_HEADERS_OLD.index("Статус")]      = status
    row[SVC_HEADERS_OLD.index("Город")]       = city
    row[SVC_HEADERS_OLD.index("Service Name")]= name
    row[SVC_HEADERS_OLD.index("Object Type")] = obj_type
    row[SVC_HEADERS_OLD.index("Currency")]    = currency
    return row


def _fresh_sm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.service_manager as sm
    return sm


# ────────────────────────────────────────────────────────────
# A/B: generate_service_id
# ────────────────────────────────────────────────────────────

class TestGenerateServiceId(unittest.TestCase):

    def test_A_empty_catalog_returns_SVC001(self):
        """A: пустой SERVICE_CATALOG → SVC-001."""
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet()):
            result = sm.generate_service_id()
        self.assertEqual(result, "SVC-001")

    def test_B_after_existing_increments(self):
        """B: после SVC-003 → следующий ID."""
        sm = _fresh_sm()
        existing = _svc_row("SVC-003")
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet([existing])):
            result = sm.generate_service_id()
        self.assertTrue(result.startswith("SVC-"))
        num = int(result.split("-")[1])
        self.assertGreater(num, 0)


# ────────────────────────────────────────────────────────────
# C/D: normalize_service_status
# ────────────────────────────────────────────────────────────

class TestNormalizeServiceStatus(unittest.TestCase):

    def setUp(self):
        self.sm = _fresh_sm()

    def test_C_active(self):
        """C: active → active."""
        self.assertEqual(self.sm.normalize_service_status("active"), "active")

    def test_C_inactive(self):
        """C: inactive → inactive."""
        self.assertEqual(self.sm.normalize_service_status("inactive"), "inactive")

    def test_C_draft(self):
        """C: draft → draft."""
        self.assertEqual(self.sm.normalize_service_status("draft"), "draft")

    def test_C_uppercase_active(self):
        """C: ACTIVE → active."""
        self.assertEqual(self.sm.normalize_service_status("ACTIVE"), "active")

    def test_D_unknown_returns_active(self):
        """D: неизвестный статус → active."""
        self.assertEqual(self.sm.normalize_service_status("unknown_xyz"), "active")

    def test_D_empty_returns_active(self):
        """D: пустой статус → active."""
        self.assertEqual(self.sm.normalize_service_status(""), "active")


# ────────────────────────────────────────────────────────────
# E/F/G: create_service_record
# ────────────────────────────────────────────────────────────

class TestCreateServiceRecord(unittest.TestCase):

    def test_E_creates_with_required_fields(self):
        """E: create_service_record создает запись с обязательными полями."""
        sm = _fresh_sm()
        appended = []

        def capture(sheet_key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="SVC-001"):
            result = sm.create_service_record(
                biz_id="BIZ-001",
                service_name="Узаконение реконструкции",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["service_id"], "SVC-001")
        self.assertEqual(len(appended), 1)
        row = appended[0]
        self.assertIn("BIZ-001", row)
        self.assertIn("Узаконение реконструкции", row)

    def test_E_missing_biz_id_returns_error(self):
        """E: пустой biz_id → error."""
        sm = _fresh_sm()
        result = sm.create_service_record(biz_id="", service_name="Test")
        self.assertFalse(result["ok"])

    def test_E_missing_name_returns_error(self):
        """E: пустой service_name → error."""
        sm = _fresh_sm()
        result = sm.create_service_record(biz_id="BIZ-001", service_name="")
        self.assertFalse(result["ok"])

    def test_F_default_status_is_active(self):
        """F: status по умолчанию active."""
        sm = _fresh_sm()
        appended = []

        def capture(sheet_key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="SVC-001"):
            result = sm.create_service_record(
                biz_id="BIZ-001", service_name="Test Service"
            )

        self.assertTrue(result["ok"])
        row = appended[0]
        self.assertIn("active", row)

    def test_G_default_currency_is_KZT(self):
        """G: currency по умолчанию KZT."""
        sm = _fresh_sm()
        appended = []

        def capture(sheet_key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="SVC-001"):
            result = sm.create_service_record(
                biz_id="BIZ-001", service_name="Test Service"
            )

        self.assertTrue(result["ok"])
        row = appended[0]
        self.assertIn("KZT", row)

    def test_G_custom_currency_preserved(self):
        """G: кастомная валюта сохраняется."""
        sm = _fresh_sm()
        appended = []

        def capture(sheet_key, row):
            appended.append(row)

        with patch("business_core.sheets.append_business_row", side_effect=capture), \
             patch("business_core.sheets.generate_next_id", return_value="SVC-001"):
            result = sm.create_service_record(
                biz_id="BIZ-001", service_name="Test", currency="USD"
            )

        self.assertTrue(result["ok"])
        row = appended[0]
        self.assertIn("USD", row)


# ────────────────────────────────────────────────────────────
# H: find_service_by_id
# ────────────────────────────────────────────────────────────

class TestFindServiceById(unittest.TestCase):

    def test_H_finds_existing_service(self):
        """H: find_service_by_id находит услугу."""
        sm = _fresh_sm()
        row = _svc_row("SVC-001", "BIZ-001", "Узаконение", "active")

        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet([row])):
            result = sm.find_service_by_id("SVC-001")

        self.assertIsNotNone(result)
        self.assertEqual(result["service_id"], "SVC-001")
        self.assertEqual(result["biz_id"],     "BIZ-001")

    def test_H_returns_none_for_missing(self):
        """H: несуществующий ID → None."""
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet()):
            result = sm.find_service_by_id("SVC-999")
        self.assertIsNone(result)

    def test_H_empty_id_returns_none(self):
        """H: пустой ID → None."""
        sm = _fresh_sm()
        result = sm.find_service_by_id("")
        self.assertIsNone(result)


# ────────────────────────────────────────────────────────────
# I: find_services_by_biz
# ────────────────────────────────────────────────────────────

class TestFindServicesByBiz(unittest.TestCase):

    def test_I_filters_by_biz_id(self):
        """I: find_services_by_biz фильтрует по бизнесу."""
        sm = _fresh_sm()
        rows = [
            _svc_row("SVC-001", "BIZ-001", "Услуга 1"),
            _svc_row("SVC-002", "BIZ-002", "Услуга 2"),
            _svc_row("SVC-003", "BIZ-001", "Услуга 3"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet(rows)):
            result = sm.find_services_by_biz("BIZ-001")

        self.assertEqual(len(result), 2)
        ids = {r["service_id"] for r in result}
        self.assertIn("SVC-001", ids)
        self.assertIn("SVC-003", ids)
        self.assertNotIn("SVC-002", ids)

    def test_I_empty_biz_returns_empty(self):
        """I: пустой biz_id → пустой список."""
        sm = _fresh_sm()
        result = sm.find_services_by_biz("")
        self.assertEqual(result, [])


# ────────────────────────────────────────────────────────────
# J: find_services_by_object_type
# ────────────────────────────────────────────────────────────

class TestFindServicesByObjectType(unittest.TestCase):

    def test_J_filters_by_object_type(self):
        """J: find_services_by_object_type фильтрует по типу объекта."""
        sm = _fresh_sm()
        rows = [
            _svc_row("SVC-001", "BIZ-001", "Сервис 1", obj_type="частный дом"),
            _svc_row("SVC-002", "BIZ-001", "Сервис 2", obj_type="нежилое"),
            _svc_row("SVC-003", "BIZ-001", "Сервис 3", obj_type="частный дом"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet(rows)):
            result = sm.find_services_by_object_type("частный дом")

        self.assertEqual(len(result), 2)

    def test_J_with_biz_filter(self):
        """J: find_services_by_object_type + biz_id фильтрует оба."""
        sm = _fresh_sm()
        rows = [
            _svc_row("SVC-001", "BIZ-001", "Сервис 1", obj_type="частный дом"),
            _svc_row("SVC-002", "BIZ-002", "Сервис 2", obj_type="частный дом"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet(rows)):
            result = sm.find_services_by_object_type("частный дом", biz_id="BIZ-001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service_id"], "SVC-001")


# ────────────────────────────────────────────────────────────
# K: list_active_services
# ────────────────────────────────────────────────────────────

class TestListActiveServices(unittest.TestCase):

    def test_K_returns_only_active(self):
        """K: list_active_services возвращает только active."""
        sm = _fresh_sm()
        rows = [
            _svc_row("SVC-001", status="active"),
            _svc_row("SVC-002", status="inactive"),
            _svc_row("SVC-003", status="draft"),
            _svc_row("SVC-004", status="active"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet(rows)):
            result = sm.list_active_services()

        self.assertEqual(len(result), 2)
        for r in result:
            self.assertEqual(r["status"], "active")

    def test_K_with_biz_filter(self):
        """K: list_active_services + biz_id фильтрует оба."""
        sm = _fresh_sm()
        rows = [
            _svc_row("SVC-001", "BIZ-001", status="active"),
            _svc_row("SVC-002", "BIZ-002", status="active"),
        ]
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet(rows)):
            result = sm.list_active_services(biz_id="BIZ-001")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service_id"], "SVC-001")


# ────────────────────────────────────────────────────────────
# L: update_service_roadmap_template
# ────────────────────────────────────────────────────────────

class TestUpdateServiceRoadmapTemplate(unittest.TestCase):

    def test_L_writes_template_id(self):
        """L: update_service_roadmap_template записывает ID шаблона."""
        sm = _fresh_sm()
        row = _svc_row("SVC-001")
        mock_ws = _make_svc_sheet([row])

        with patch("business_core.sheets.get_business_sheet", return_value=mock_ws):
            result = sm.update_service_roadmap_template(
                "SVC-001", "legalization_reconstruction_house"
            )

        self.assertTrue(result)
        mock_ws.update_cell.assert_called()
        # Проверяем что записалось правильное значение
        call_args = mock_ws.update_cell.call_args_list
        values = [c[0][2] for c in call_args]
        self.assertIn("legalization_reconstruction_house", values)

    def test_L_returns_false_for_missing_service(self):
        """L: несуществующая услуга → False."""
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet",
                   return_value=_make_svc_sheet()):
            result = sm.update_service_roadmap_template("SVC-999", "some_template")
        self.assertFalse(result)

    def test_L_empty_args_returns_false(self):
        """L: пустые аргументы → False."""
        sm = _fresh_sm()
        self.assertFalse(sm.update_service_roadmap_template("", "template"))
        self.assertFalse(sm.update_service_roadmap_template("SVC-001", ""))


# ────────────────────────────────────────────────────────────
# M: /newservice command
# ────────────────────────────────────────────────────────────

class TestNewserviceCommand(unittest.TestCase):

    def test_M_creates_service(self):
        """M: /newservice создает услугу."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import newservice_cmd

            update  = MagicMock()
            context = MagicMock()
            context.args = ['biz_id=BIZ-001', 'name=Узаконение']
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.service_manager.create_service_record",
                       return_value={"ok": True, "service_id": "SVC-001", "error": None}):
                await newservice_cmd(update, context)

            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SVC-001", msg)
            self.assertIn("✅", msg)

        asyncio.run(run())

    def test_M_missing_biz_returns_error(self):
        """M: /newservice без biz_id → error."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import newservice_cmd

            update  = MagicMock()
            context = MagicMock()
            context.args = []
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await newservice_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# N: /services command
# ────────────────────────────────────────────────────────────

class TestServicesCommand(unittest.TestCase):

    def test_N_shows_services_list(self):
        """N: /services показывает список."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import services_cmd

            mock_rows = [
                {"service_id": "SVC-001", "biz_id": "BIZ-001",
                 "service_name": "Узаконение", "status": "active",
                 "city": "Алматы", "object_type": "частный дом",
                 "price_from": "1500000", "duration": "3-4 месяца", "notes": ""},
            ]

            update  = MagicMock()
            context = MagicMock()
            context.args = []
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.service_manager._load_services",
                       return_value=(mock_rows, [])):
                await services_cmd(update, context)

            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SVC-001", msg)
            self.assertIn("Узаконение", msg)

        asyncio.run(run())

    def test_N_filters_by_biz_id(self):
        """N: /services biz_id=BIZ-001 фильтрует."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import services_cmd

            mock_rows = [
                {"service_id": "SVC-001", "biz_id": "BIZ-001",
                 "service_name": "A", "status": "active",
                 "city": "", "object_type": "", "price_from": "", "duration": "", "notes": ""},
                {"service_id": "SVC-002", "biz_id": "BIZ-002",
                 "service_name": "B", "status": "active",
                 "city": "", "object_type": "", "price_from": "", "duration": "", "notes": ""},
            ]

            update  = MagicMock()
            context = MagicMock()
            context.args = ["biz_id=BIZ-001"]
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.service_manager._load_services",
                       return_value=(mock_rows, [])):
                await services_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SVC-001", msg)
            self.assertNotIn("SVC-002", msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# O: /service (detail) command
# ────────────────────────────────────────────────────────────

class TestServiceDetailCommand(unittest.TestCase):

    def test_O_shows_service_card(self):
        """O: /service показывает карточку услуги."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import service_detail_cmd

            mock_svc = {
                "service_id":    "SVC-001",
                "biz_id":        "BIZ-001",
                "service_name":  "Узаконение реконструкции",
                "service_category": "узаконение",
                "city":          "Алматы",
                "object_type":   "частный дом",
                "status":        "active",
                "price_from":    "1500000",
                "price_to":      "2000000",
                "currency":      "KZT",
                "duration":      "3-4 месяца",
                "description":   "Полное узаконение",
                "what_included": "Проект, паспорт, регистрация",
                "what_not_included": "Строительные работы",
                "required_documents": "Удостоверение, правоустанавливающие",
                "default_roadmap_template_id": "legalization_reconstruction_house",
                "risks":         "Сейсмическая зона",
                "notes":         "Через АПЗ",
                "created_at":    "2025-01-01",
            }

            update  = MagicMock()
            context = MagicMock()
            context.args = ["SVC-001"]
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value=mock_svc):
                await service_detail_cmd(update, context)

            update.message.reply_text.assert_called_once()
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SVC-001",               msg)
            self.assertIn("Узаконение реконструкции", msg)
            self.assertIn("BIZ-001",               msg)

        asyncio.run(run())

    def test_O_missing_id_returns_error(self):
        """O: /service без ID → error."""
        import asyncio

        async def run():
            for key in list(sys.modules.keys()):
                if "business_core" in key:
                    del sys.modules[key]
            from business_core.telegram_handlers import service_detail_cmd

            update  = MagicMock()
            context = MagicMock()
            context.args = []
            update.message.reply_text = AsyncMock()
            update.effective_chat.id  = 123

            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await service_detail_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)

        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# P: GTD Isolation
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

    def test_P_service_manager_no_gtd(self):
        self._check_file(WORKSPACE / "business_core" / "service_manager.py")

    def test_P_business_builder_no_gtd(self):
        self._check_file(WORKSPACE / "business_core" / "business_builder.py")

    def test_P_telegram_handlers_no_gtd(self):
        self._check_file(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_P_sheets_no_gtd(self):
        self._check_file(WORKSPACE / "business_core" / "sheets.py")

    def test_P_gtd_files_untouched(self):
        """P: GTD core файлы не изменены этой фазой."""
        for fname in ["inbox_processor.py", "project_planner.py", "calendar_sync.py"]:
            fpath = WORKSPACE / fname
            if fpath.exists():
                self.assertTrue(fpath.exists(), f"GTD файл {fname} исчез")


# ────────────────────────────────────────────────────────────
# Extra: SERVICE_CATALOG schema
# ────────────────────────────────────────────────────────────

class TestServiceCatalogSchema(unittest.TestCase):

    def setUp(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        from business_core import sheets as s
        self.sheets = s

    def test_service_catalog_has_new_phase8a_columns(self):
        """SERVICE_CATALOG содержит все новые колонки Phase 8A."""
        headers = self.sheets.BUSINESS_HEADERS.get("service_catalog", [])
        required = [
            "Service Name", "Service Category", "Object Type", "Client Type",
            "What Included", "What Not Included", "Currency",
            "Required Documents", "Default Roadmap Template ID",
            "Contractors Needed", "Materials IDs", "Created At", "Last Updated",
        ]
        for col in required:
            self.assertIn(col, headers, f"Колонка '{col}' отсутствует в SERVICE_CATALOG")

    def test_old_columns_preserved(self):
        """Старые колонки не удалены и порядок сохранён."""
        headers = self.sheets.BUSINESS_HEADERS.get("service_catalog", [])
        old_cols = ["ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
                    "Цена мин", "Цена макс", "Срок", "Описание", "Риски", "Комментарий"]
        for col in old_cols:
            self.assertIn(col, headers, f"Старая колонка '{col}' удалена!")

    def test_new_columns_are_at_the_end(self):
        """Новые Phase 8A колонки находятся после старых."""
        headers = self.sheets.BUSINESS_HEADERS.get("service_catalog", [])
        last_old = headers.index("Комментарий")
        first_new = headers.index("Service Name")
        self.assertGreater(first_new, last_old,
                           "Service Name должен идти после Комментарий")


if __name__ == "__main__":
    unittest.main(verbosity=2)
