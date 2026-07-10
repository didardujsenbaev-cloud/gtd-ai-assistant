"""
Tests for seed_izhs_almaty_standard_reconstruction_finished_smr.py

Checks 1–9 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE    = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE   = "business_core.seeds.seed_izhs_almaty_standard_reconstruction_finished_smr"
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
        seed   = _fresh()
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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [], "create_service_record не должен вызываться в seed 3")

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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.create_roadmap_template",
                   return_value={"ok": True, "template_id": "RTMPL-002", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Template {seed.TEMPLATE_ID}", result["created"])
        self.assertEqual(result["errors"], [])

    def test_3_template_id_constant(self):
        """3: TEMPLATE_ID == RMT-IZH-ALM-STANDARD-002."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-STANDARD-002")

    def test_3_template_case_type(self):
        """3: case_type корректный для finished_smr."""
        seed = _fresh()
        self.assertEqual(
            seed.TEMPLATE_DATA["case_type"],
            "almaty_izhs_standard_reconstruction_finished_smr",
        )

    def test_3_template_different_from_seed1_and_seed2(self):
        """3: TEMPLATE_ID отличается от seed 1 и seed 2."""
        seed = _fresh()
        self.assertNotEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-LEGALIZATION-001")
        self.assertNotEqual(seed.TEMPLATE_ID, "RMT-IZH-ALM-STANDARD-001")


# ────────────────────────────────────────────────────────────
# 4. seed создает 13 template stages
# ────────────────────────────────────────────────────────────

class TestCreatesStages(unittest.TestCase):

    def test_4_creates_13_stages(self):
        """4: run_seed создает 13 этапов."""
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

        self.assertEqual(len(add_calls), 13)

    def test_4_stage_count_is_13(self):
        """4: в STAGES ровно 13 записей."""
        seed = _fresh()
        self.assertEqual(len(seed.STAGES), 13)

    def test_4_stages_order_1_to_13(self):
        """4: порядковые номера 1-13."""
        seed   = _fresh()
        orders = [s["order"] for s in seed.STAGES]
        self.assertEqual(orders, list(range(1, 14)))

    def test_4_first_stage_name(self):
        """4: первый этап — первичный анализ фактически выполненных СМР."""
        seed = _fresh()
        self.assertIn("Первичный анализ", seed.STAGES[0]["stage_name"])
        self.assertIn("СМР", seed.STAGES[0]["stage_name"])

    def test_4_last_stage_name(self):
        """4: последний этап — регистрация акта в НАО."""
        seed = _fresh()
        self.assertIn("НАО", seed.STAGES[12]["stage_name"])

    def test_4_stage_9_is_technical_project_for_finished_smr(self):
        """4: этап 9 — технический проект по фактически выполненным СМР."""
        seed = _fresh()
        self.assertIn("фактически", seed.STAGES[8]["stage_name"].lower())

    def test_4_no_smr_after_apz_stage(self):
        """4: нет этапа проведения СМР клиентом (СМР уже выполнены)."""
        seed       = _fresh()
        smr_stage  = any(
            "проведение смр" in s["stage_name"].lower() or
            "после апз" in s.get("description", "").lower() and "смр" in s.get("description", "").lower()
            for s in seed.STAGES
        )
        # В finished_smr шаблоне нет этапа "Проведение СМР клиентом"
        self.assertFalse(smr_stage)

    def test_4_partial_stages_adds_missing(self):
        """4: если 5 этапов уже есть — добавляет только недостающие 8."""
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

        self.assertEqual(len(add_calls), 8)


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-TMP-001", "error": None}), \
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
        self.assertEqual(
            seed.CHECKLIST_ID,
            "CHK-IZH-ALM-STANDARD-RECON-FINISHED-DOCS-001",
        )

    def test_5_checklist_links_to_template_002(self):
        """5: checklist привязан к шаблону RMT-IZH-ALM-STANDARD-002."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["template_id"], "RMT-IZH-ALM-STANDARD-002")


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_6_sop_has_11_steps(self):
        """6: SOP содержит 11 шагов."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        count = sum(1 for i in range(1, 12) if f"{i}." in steps)
        self.assertEqual(count, 11)

    def test_6_sop_id_constant(self):
        """6: SOP_ID корректный."""
        seed = _fresh()
        self.assertEqual(
            seed.SOP_ID,
            "SOP-IZH-ALM-STANDARD-RECON-FINISHED-PRIMARY-001",
        )

    def test_6_sop_mentions_finished_smr_risk(self):
        """6: SOP упоминает риск выполненных СМР до АПЗ."""
        seed = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("СМР уже выполнены до АПЗ", steps)

    def test_6_sop_links_to_template_002(self):
        """6: SOP привязан к шаблону RMT-IZH-ALM-STANDARD-002."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["template_id"], "RMT-IZH-ALM-STANDARD-002")


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
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
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertGreaterEqual(len(result["skipped"]), 4)

    def test_7_rename_id_skips_if_same(self):
        """7: _rename_id_in_sheet не делает вызов update_cell если IDs совпадают."""
        seed  = _fresh()
        sheet = MagicMock()
        seed._rename_id_in_sheet(sheet, "SAME-001", "SAME-001")
        sheet.get_all_values.assert_not_called()


# ────────────────────────────────────────────────────────────
# 8. GTD Core не импортируется и не меняется
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check_file(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_8_seed_file(self):
        """8: seed не импортирует GTD Core модули."""
        self._check_file(
            WORKSPACE / "business_core" / "seeds" /
            "seed_izhs_almaty_standard_reconstruction_finished_smr.py"
        )

    def test_8_knowledge_manager(self):
        """8: knowledge_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_8_service_manager(self):
        """8: service_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "service_manager.py")

    def test_8_no_gtd_functions_in_run_seed(self):
        """8: run_seed не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox",
                          "inbox_processor", "telegram_bot"]:
            self.assertNotIn(forbidden, src)

    def test_8_template_mentions_other_templates(self):
        """8: Notes шаблона ссылаются на другие шаблоны по ID (не путает)."""
        seed = _fresh()
        notes = seed.TEMPLATE_DATA["notes"]
        self.assertIn("RMT-IZH-ALM-LEGALIZATION-001", notes)
        self.assertNotIn("RMT-IZH-ALM-STANDARD-002", notes)


# ────────────────────────────────────────────────────────────
# 9. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_9_env_file_not_modified(self):
        """9: .env файл не изменён этим seed."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=13), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            seed.dry_run()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after, ".env был изменён!")

    def test_9_seed_does_not_write_env(self):
        """9: run_seed не пишет в .env."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)

    def test_9_biz_id_constant(self):
        """9: BIZ_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")


if __name__ == "__main__":
    unittest.main(verbosity=2)
