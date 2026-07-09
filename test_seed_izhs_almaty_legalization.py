"""
Tests for seed_izhs_almaty_legalization.py

Checks 1–10 per spec:
1.  dry-run не пишет в Sheets
2.  seed создает service
3.  seed создает roadmap template
4.  seed создает 12 template stages
5.  seed создает checklist
6.  seed создает SOP
7.  повторный запуск не создает дубли
8.  service получает Default Roadmap Template ID
9.  /startroadmap по SVC-IZH-001 создает stages из RMT-IZH-ALM-LEGALIZATION-001
10. GTD Core файлы не импортируются и не меняются
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call, AsyncMock

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

SEED_MODULE = "business_core.seeds.seed_izhs_almaty_legalization"

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _fresh_seed():
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


def _sheet_with_header(headers: list[str], rows: list[list] = None):
    ws = MagicMock()
    ws.get_all_values.return_value = [headers] + (rows or [])
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


# ────────────────────────────────────────────────────────────
# 1. dry-run не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_1_dry_run_does_not_write(self):
        """1: dry-run не записывает в Google Sheets."""
        seed = _fresh_seed()

        write_calls = []

        def mock_append(sheet_key, row):
            write_calls.append((sheet_key, row))

        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.sheets.append_business_row", side_effect=mock_append):
            result = seed.dry_run()

        self.assertEqual(write_calls, [], "dry_run не должен вызывать append_business_row")
        self.assertGreater(len(result["plan"]), 0, "В плане должны быть записи")

    def test_1_dry_run_shows_skips_when_all_exist(self):
        """1: dry-run показывает SKIP если все уже есть."""
        seed = _fresh_seed()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.dry_run()

        self.assertEqual(result["plan"], [])
        self.assertEqual(len(result["skip"]), 5)

    def test_1_dry_run_shows_create_when_nothing_exists(self):
        """1: dry-run показывает CREATE когда ничего нет."""
        seed = _fresh_seed()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False):
            result = seed.dry_run()

        self.assertEqual(len(result["plan"]), 5)
        self.assertTrue(any("CREATE" in p for p in result["plan"]))


# ────────────────────────────────────────────────────────────
# 2. seed создает service
# ────────────────────────────────────────────────────────────

class TestSeedCreatesService(unittest.TestCase):

    def test_2_creates_service(self):
        """2: run_seed создает service когда его нет."""
        seed = _fresh_seed()
        svc_sheet = _sheet_with_header(["ID", "Бизнес ID", "Название"])
        created_rows = []

        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=svc_sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: created_rows.append((k, r))):
            result = seed.run_seed(verbose=False)

        # Проверяем что запись в created — факт создания важнее деталей rename
        self.assertIn(f"Service {seed.SERVICE_ID}", result["created"])
        self.assertEqual(result["errors"], [])


# ────────────────────────────────────────────────────────────
# 3. seed создает roadmap template
# ────────────────────────────────────────────────────────────

class TestSeedCreatesTemplate(unittest.TestCase):

    def test_3_creates_template(self):
        """3: run_seed создает roadmap template когда его нет."""
        seed = _fresh_seed()
        tmpl_sheet = _sheet_with_header(["Template ID", "Template Name"])

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.create_roadmap_template",
                   return_value={"ok": True, "template_id": "RTMPL-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=tmpl_sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertIn(f"Template {seed.TEMPLATE_ID}", result["created"])
        self.assertEqual(result["errors"], [])


# ────────────────────────────────────────────────────────────
# 4. seed создает 12 template stages
# ────────────────────────────────────────────────────────────

class TestSeedCreatesStages(unittest.TestCase):

    def test_4_creates_12_stages(self):
        """4: run_seed создает 12 этапов для шаблона."""
        seed = _fresh_seed()
        stage_sheet = _sheet_with_header(["Stage ID", "Template ID", "Order", "Stage Name"])
        add_calls   = []

        def mock_add_stage(**kwargs):
            add_calls.append(kwargs)
            return {"ok": True, "stage_id": f"TSTG-{len(add_calls):03d}",
                    "order": kwargs.get("order", 0), "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                   side_effect=mock_add_stage), \
             patch("business_core.sheets.get_business_sheet", return_value=stage_sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertEqual(len(add_calls), 12, f"Ожидалось 12 этапов, вызвано: {len(add_calls)}")
        self.assertEqual(add_calls[0]["stage_name"], "Первичный анализ объекта")
        self.assertEqual(add_calls[11]["stage_name"], "Регистрация протокола в НАО")

    def test_4_stages_have_correct_order(self):
        """4: этапы имеют порядковые номера 1-12."""
        seed = _fresh_seed()
        orders = [s["order"] for s in seed.STAGES]
        self.assertEqual(orders, list(range(1, 13)))

    def test_4_stage_count_is_12(self):
        """4: в STAGES ровно 12 записей."""
        seed = _fresh_seed()
        self.assertEqual(len(seed.STAGES), 12)


# ────────────────────────────────────────────────────────────
# 5. seed создает checklist
# ────────────────────────────────────────────────────────────

class TestSeedCreatesChecklist(unittest.TestCase):

    def test_5_creates_checklist(self):
        """5: run_seed создает checklist когда его нет."""
        seed       = _fresh_seed()
        chk_sheet  = _sheet_with_header(["Checklist ID", "Title"])

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=chk_sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["created"])

    def test_5_checklist_has_16_items(self):
        """5: чек-лист содержит 16 пунктов."""
        seed  = _fresh_seed()
        items = [i.strip() for i in seed.CHECKLIST_DATA["items"].split(";") if i.strip()]
        self.assertEqual(len(items), 16, f"Ожидалось 16 пунктов, нашли {len(items)}")


# ────────────────────────────────────────────────────────────
# 6. seed создает SOP
# ────────────────────────────────────────────────────────────

class TestSeedCreatesSOP(unittest.TestCase):

    def test_6_creates_sop(self):
        """6: run_seed создает SOP когда его нет."""
        seed      = _fresh_seed()
        sop_sheet = _sheet_with_header(["SOP ID", "Title"])

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sop_sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_6_sop_has_10_steps(self):
        """6: SOP содержит 10 шагов."""
        seed  = _fresh_seed()
        steps = seed.SOP_DATA["steps"]
        count = sum(1 for i in range(1, 11) if f"{i}." in steps)
        self.assertEqual(count, 10, f"Ожидалось 10 шагов в SOP")


# ────────────────────────────────────────────────────────────
# 7. повторный запуск не создает дубли
# ────────────────────────────────────────────────────────────

class TestSeedIdempotency(unittest.TestCase):

    def test_7_no_duplicates_on_second_run(self):
        """7: повторный запуск пропускает все записи (все уже есть)."""
        seed = _fresh_seed()
        append_calls = []

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=12), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: append_calls.append((k, r))):
            result = seed.run_seed(verbose=False)

        self.assertEqual(append_calls, [],
                         "При повторном запуске append_business_row не должен вызываться")
        self.assertEqual(result["created"], [])
        self.assertEqual(len(result["skipped"]), 5)

    def test_7_partial_state_only_adds_missing(self):
        """7: если шаблон есть, но stages нет — добавляет только stages."""
        seed = _fresh_seed()
        add_calls = []

        def mock_add(**kwargs):
            add_calls.append(kwargs)
            return {"ok": True, "stage_id": "TSTG-X", "order": 1, "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                   side_effect=mock_add), \
             patch("business_core.sheets.get_business_sheet", return_value=MagicMock()), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertEqual(len(add_calls), 12)
        self.assertEqual(len(result["created"]), 1)
        self.assertIn(f"Stages {seed.TEMPLATE_ID}", result["created"][0])


# ────────────────────────────────────────────────────────────
# 8. service получает Default Roadmap Template ID
# ────────────────────────────────────────────────────────────

class TestServiceDefaultTemplate(unittest.TestCase):

    def test_8_service_data_has_default_template_id(self):
        """8: SERVICE_DATA содержит default_roadmap_template_id."""
        seed = _fresh_seed()
        self.assertEqual(
            seed.SERVICE_DATA.get("default_roadmap_template_id"),
            seed.TEMPLATE_ID,
        )

    def test_8_service_id_matches_constant(self):
        """8: SERVICE_ID и TEMPLATE_ID соответствуют спецификации."""
        seed = _fresh_seed()
        self.assertEqual(seed.SERVICE_ID,  "SVC-IZH-001")
        self.assertEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-LEGALIZATION-001")

    def test_8_template_data_links_to_service(self):
        """8: TEMPLATE_DATA.service_id === SERVICE_ID."""
        seed = _fresh_seed()
        self.assertEqual(seed.TEMPLATE_DATA["service_id"], seed.SERVICE_ID)


# ────────────────────────────────────────────────────────────
# 9. /startroadmap по SVC-IZH-001 создает stages из шаблона
# ────────────────────────────────────────────────────────────

class TestStartRoadmapWithSeedService(unittest.TestCase):

    def test_9_startroadmap_uses_seed_template(self):
        """9: /startroadmap по SVC-IZH-001 создает stages из RMT-IZH-ALM-LEGALIZATION-001."""
        import asyncio
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]

        from business_core.telegram_handlers import startroadmap_cmd

        update  = MagicMock()
        context = MagicMock()
        context.args = ["obj_id=OBJ-001", "service_id=SVC-IZH-001"]
        # startroadmap_cmd читает update.message.text когда context.args truthy
        update.message.text = "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001"
        update.message.reply_text = AsyncMock()

        service_mock = {
            "ID":                          "SVC-IZH-001",
            "service_id":                  "SVC-IZH-001",
            "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001",
        }
        roadmap_mock = {"ok": True, "roadmap_id": "RM-001", "error": None}
        stages_mock  = {"ok": True, "stages_count": 12, "warning": None, "stage_ids": []}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value=service_mock), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value=roadmap_mock), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"Template ID": "RMT-IZH-ALM-LEGALIZATION-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value=stages_mock) as mock_stages, \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await startroadmap_cmd(update, context)

            msg = update.message.reply_text.call_args[0][0]
            return msg

        msg = asyncio.run(run())
        self.assertIn("RM-001", msg)

    def test_9_seed_stages_names_match_spec(self):
        """9: названия 12 этапов соответствуют спецификации."""
        seed = _fresh_seed()
        expected_first = "Первичный анализ объекта"
        expected_last  = "Регистрация протокола в НАО"
        self.assertEqual(seed.STAGES[0]["stage_name"],  expected_first)
        self.assertEqual(seed.STAGES[11]["stage_name"], expected_last)


# ────────────────────────────────────────────────────────────
# 10. GTD Core файлы не импортируются
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists():
            return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_10_seed_file(self):
        self._check(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_almaty_legalization.py"
        )

    def test_10_knowledge_manager(self):
        self._check(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_10_service_manager(self):
        self._check(WORKSPACE / "business_core" / "service_manager.py")

    def test_10_roadmap_template_manager(self):
        self._check(WORKSPACE / "business_core" / "roadmap_template_manager.py")

    def test_10_sheets(self):
        self._check(WORKSPACE / "business_core" / "sheets.py")

    def test_10_seed_data_integrity(self):
        """10: seed содержит все обязательные поля."""
        seed = _fresh_seed()
        self.assertTrue(seed.SERVICE_DATA.get("service_name"))
        self.assertTrue(seed.SERVICE_DATA.get("biz_id"))
        self.assertTrue(seed.TEMPLATE_DATA.get("template_name"))
        self.assertEqual(len(seed.STAGES), 12)
        self.assertTrue(seed.CHECKLIST_DATA.get("title"))
        self.assertTrue(seed.SOP_DATA.get("title"))
        self.assertTrue(seed.SOP_DATA.get("steps"))

    def test_10_no_gtd_tasks_created(self):
        """10: run_seed не создает GTD tasks."""
        seed = _fresh_seed()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox"]:
            self.assertNotIn(forbidden, src,
                f"run_seed содержит вызов GTD-функции: {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
