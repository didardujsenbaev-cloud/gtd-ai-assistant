"""
Tests for seed_izhs_almaty_standard_reconstruction.py

Checks 1–9 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE  = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE  = "business_core.seeds.seed_izhs_almaty_standard_reconstruction"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _fresh():
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


def _sheet(header=None):
    ws = MagicMock()
    ws.get_all_values.return_value = [header or ["ID", "Name"]]
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


# ────────────────────────────────────────────────────────────
# 1. dry-run не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_1_dry_run_does_not_write(self):
        """1: dry-run не записывает в Google Sheets."""
        seed = _fresh()
        writes = []
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            result = seed.dry_run()
        self.assertEqual(writes, [])
        self.assertGreater(len(result["plan"]), 0)

    def test_1_dry_run_all_exist(self):
        """1: dry-run показывает SKIP если всё уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])

    def test_1_dry_run_shows_create_when_nothing(self):
        """1: dry-run показывает CREATE когда ничего нет."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 4)  # template + stages + checklist + SOP
        self.assertTrue(any("CREATE" in p for p in result["plan"]))


# ────────────────────────────────────────────────────────────
# 2. seed не создает новый Service, использует SVC-IZH-001
# ────────────────────────────────────────────────────────────

class TestServiceNotCreated(unittest.TestCase):

    def test_2_no_new_service_created(self):
        """2: seed не вызывает create_service_record."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [], "create_service_record не должен вызываться в seed 2")

    def test_2_service_id_is_svc_izh_001(self):
        """2: SERVICE_ID == SVC-IZH-001."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_ID, "SVC-IZH-001")

    def test_2_template_links_to_existing_service(self):
        """2: TEMPLATE_DATA.service_id == SVC-IZH-001."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_DATA["service_id"], "SVC-IZH-001")

    def test_2_service_not_in_created_list(self):
        """2: 'Service' не появляется в created при запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.run_seed(verbose=False)
        service_in_created = any("Service" in s for s in result["created"])
        self.assertFalse(service_in_created)


# ────────────────────────────────────────────────────────────
# 3. seed создает roadmap template
# ────────────────────────────────────────────────────────────

class TestCreatesTemplate(unittest.TestCase):

    def test_3_creates_template(self):
        """3: run_seed создает template когда его нет."""
        seed  = _fresh()
        sheet = _sheet(["Template ID", "Template Name"])
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.create_roadmap_template",
                   return_value={"ok": True, "template_id": "RTMPL-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Template {seed.TEMPLATE_ID}", result["created"])
        self.assertEqual(result["errors"], [])

    def test_3_template_id_constant(self):
        """3: TEMPLATE_ID == RMT-IZH-ALM-STANDARD-001."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-STANDARD-001")

    def test_3_template_case_type(self):
        """3: case_type корректный."""
        seed = _fresh()
        self.assertEqual(
            seed.TEMPLATE_DATA["case_type"],
            "almaty_izhs_standard_reconstruction_before_smr",
        )


# ────────────────────────────────────────────────────────────
# 4. seed создает 15 template stages
# ────────────────────────────────────────────────────────────

class TestCreatesStages(unittest.TestCase):

    def test_4_creates_15_stages(self):
        """4: run_seed создает 15 этапов."""
        seed      = _fresh()
        add_calls = []

        def mock_add(**kwargs):
            add_calls.append(kwargs)
            return {"ok": True, "stage_id": f"TSTG-{len(add_calls):03d}",
                    "order": kwargs.get("order", 0), "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                   side_effect=mock_add), \
             patch("business_core.sheets.get_business_sheet", return_value=MagicMock()), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertEqual(len(add_calls), 15)

    def test_4_stage_count_is_15(self):
        """4: в STAGES ровно 15 записей."""
        seed = _fresh()
        self.assertEqual(len(seed.STAGES), 15)

    def test_4_stages_order_1_to_15(self):
        """4: порядковые номера 1-15."""
        seed = _fresh()
        orders = [s["order"] for s in seed.STAGES]
        self.assertEqual(orders, list(range(1, 16)))

    def test_4_first_stage_name(self):
        """4: первый этап — первичный анализ."""
        seed = _fresh()
        self.assertIn("Первичный анализ", seed.STAGES[0]["stage_name"])

    def test_4_last_stage_name(self):
        """4: последний этап — регистрация акта в НАО."""
        seed = _fresh()
        self.assertIn("НАО", seed.STAGES[14]["stage_name"])

    def test_4_partial_stages_adds_missing(self):
        """4: если 5 этапов уже есть — добавляет только недостающие 10."""
        seed      = _fresh()
        add_calls = []

        def mock_add(**kwargs):
            add_calls.append(kwargs)
            return {"ok": True, "stage_id": "TSTG-X", "order": 1, "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=5), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                   side_effect=mock_add), \
             patch("business_core.sheets.get_business_sheet", return_value=MagicMock()), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertEqual(len(add_calls), 10)


# ────────────────────────────────────────────────────────────
# 5. seed создает checklist
# ────────────────────────────────────────────────────────────

class TestCreatesChecklist(unittest.TestCase):

    def test_5_creates_checklist(self):
        """5: run_seed создает checklist."""
        seed  = _fresh()
        sheet = _sheet(["Checklist ID", "Title"])
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["created"])

    def test_5_checklist_has_19_items(self):
        """5: чек-лист содержит 19 пунктов."""
        seed  = _fresh()
        items = [i.strip() for i in seed.CHECKLIST_DATA["items"].split(";") if i.strip()]
        self.assertEqual(len(items), 19, f"Ожидалось 19 пунктов, нашли {len(items)}")

    def test_5_checklist_id_constant(self):
        """5: CHECKLIST_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_ID, "CHK-IZH-ALM-STANDARD-RECON-DOCS-001")


# ────────────────────────────────────────────────────────────
# 6. seed создает SOP
# ────────────────────────────────────────────────────────────

class TestCreatesSOP(unittest.TestCase):

    def test_6_creates_sop(self):
        """6: run_seed создает SOP."""
        seed  = _fresh()
        sheet = _sheet(["SOP ID", "Title"])
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_6_sop_has_10_steps(self):
        """6: SOP содержит 10 шагов."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        count = sum(1 for i in range(1, 11) if f"{i}." in steps)
        self.assertEqual(count, 10)

    def test_6_sop_id_constant(self):
        """6: SOP_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-IZH-ALM-STANDARD-RECON-PRIMARY-001")


# ────────────────────────────────────────────────────────────
# 7. повторный запуск не создает дубли
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_7_no_writes_on_second_run(self):
        """7: повторный запуск не вызывает append_business_row."""
        seed    = _fresh()
        appends = []
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appends.append((k, r))):
            result = seed.run_seed(verbose=False)
        self.assertEqual(appends, [])
        self.assertEqual(result["created"], [])

    def test_7_all_skipped_when_everything_exists(self):
        """7: все записи в skipped."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=15), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.run_seed(verbose=False)
        # service(1) + template + stages + checklist + sop = 5 skipped
        self.assertGreaterEqual(len(result["skipped"]), 4)


# ────────────────────────────────────────────────────────────
# 8. /startroadmap с явным template_id=RMT-IZH-ALM-STANDARD-001
# ────────────────────────────────────────────────────────────

class TestStartRoadmapWithStandardTemplate(unittest.TestCase):

    def test_8_startroadmap_with_explicit_template_id(self):
        """8: /startroadmap с template_id=RMT-IZH-ALM-STANDARD-001 создает stages."""
        import asyncio
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        from business_core.telegram_handlers import startroadmap_cmd

        update  = MagicMock()
        context = MagicMock()
        context.args = [
            "obj_id=OBJ-001",
            "service_id=SVC-IZH-001",
            "template_id=RMT-IZH-ALM-STANDARD-001",
        ]
        update.message.text = (
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 "
            "template_id=RMT-IZH-ALM-STANDARD-001"
        )
        update.message.reply_text = AsyncMock()

        stages_mock = {"ok": True, "stages_count": 15, "warning": None, "stage_ids": []}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001",
                                     "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-010", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"Template ID": "RMT-IZH-ALM-STANDARD-001"}), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value=stages_mock), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await startroadmap_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            return msg

        msg = asyncio.run(run())
        self.assertIn("RM-010", msg)
        self.assertIn("RMT-IZH-ALM-STANDARD-001", msg)

    def test_8_template_id_different_from_seed1(self):
        """8: TEMPLATE_ID отличается от seed 1."""
        seed = _fresh()
        self.assertNotEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-LEGALIZATION-001")
        self.assertEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-STANDARD-001")


# ────────────────────────────────────────────────────────────
# 9. GTD Core isolation
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_9_seed_file(self):
        self._check(
            WORKSPACE / "business_core" / "seeds" /
            "seed_izhs_almaty_standard_reconstruction.py"
        )

    def test_9_knowledge_manager(self):
        self._check(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_9_service_manager(self):
        self._check(WORKSPACE / "business_core" / "service_manager.py")

    def test_9_roadmap_template_manager(self):
        self._check(WORKSPACE / "business_core" / "roadmap_template_manager.py")

    def test_9_data_integrity(self):
        """9: seed содержит все обязательные поля."""
        seed = _fresh()
        self.assertTrue(seed.TEMPLATE_DATA.get("template_name"))
        self.assertTrue(seed.TEMPLATE_DATA.get("biz_id"))
        self.assertTrue(seed.TEMPLATE_DATA.get("service_id"))
        self.assertEqual(len(seed.STAGES), 15)
        self.assertTrue(seed.CHECKLIST_DATA.get("title"))
        self.assertTrue(seed.SOP_DATA.get("title"))
        self.assertTrue(seed.SOP_DATA.get("steps"))

    def test_9_no_gtd_tasks_in_run_seed(self):
        """9: run_seed не создает GTD tasks."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox"]:
            self.assertNotIn(forbidden, src)

    def test_9_seeds_have_different_ids(self):
        """9: seed 2 использует другие IDs чем seed 1."""
        import importlib
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        s1 = importlib.import_module(
            "business_core.seeds.seed_izhs_almaty_legalization")
        s2 = importlib.import_module(
            "business_core.seeds.seed_izhs_almaty_standard_reconstruction")

        self.assertNotEqual(s1.TEMPLATE_ID,  s2.TEMPLATE_ID)
        self.assertNotEqual(s1.CHECKLIST_ID, s2.CHECKLIST_ID)
        self.assertNotEqual(s1.SOP_ID,       s2.SOP_ID)
        self.assertEqual(s1.SERVICE_ID,      s2.SERVICE_ID)   # оба используют SVC-IZH-001


if __name__ == "__main__":
    unittest.main(verbosity=2)
