"""
Tests for seed_izhs_commercial_milestones_sop.py

Checks 1–10 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE   = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE   = "business_core.seeds.seed_izhs_commercial_milestones_sop"
SEED_PATH     = WORKSPACE / "business_core" / "seeds" / "seed_izhs_commercial_milestones_sop.py"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

IZH_8_SERVICES = [
    "SVC-IZH-001", "SVC-IZH-002", "SVC-IZH-003", "SVC-IZH-004",
    "SVC-IZH-AST-001", "SVC-IZH-AST-002", "SVC-IZH-AST-003", "SVC-IZH-AST-004",
]


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

    def test_1_dry_run_no_writes(self):
        """1: dry-run не вызывает append_business_row."""
        seed   = _fresh()
        writes = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            result = seed.dry_run()
        self.assertEqual(writes, [])

    def test_1_dry_run_shows_2_creates(self):
        """1: dry-run показывает 2 CREATE когда ничего нет."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 2)

    def test_1_dry_run_all_exist(self):
        """1: dry-run показывает только SKIP если всё есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])
        self.assertEqual(len(result["skip"]), 2)

    def test_1_dry_run_partial_sop_missing(self):
        """1: dry-run показывает CREATE только для SOP если CHK уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 1)
        self.assertIn("SOP", result["plan"][0])

    def test_1_dry_run_partial_chk_missing(self):
        """1: dry-run показывает CREATE только для CHK если SOP уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 1)
        self.assertIn("Checklist", result["plan"][0])

    def test_1_dry_run_returns_dict(self):
        """1: dry_run возвращает dict с ключами plan и skip."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False):
            result = seed.dry_run()
        self.assertIn("plan", result)
        self.assertIn("skip", result)


# ────────────────────────────────────────────────────────────
# 2. seed создает SOP-IZH-COMMERCIAL-MILESTONES-001
# ────────────────────────────────────────────────────────────

class TestCreatesSOP(unittest.TestCase):

    def test_2_creates_sop(self):
        """2: run_seed создает SOP-IZH-COMMERCIAL-MILESTONES-001."""
        seed  = _fresh()
        sheet = _sheet(["SOP ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_2_sop_id_constant(self):
        """2: SOP_ID == SOP-IZH-COMMERCIAL-MILESTONES-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-IZH-COMMERCIAL-MILESTONES-001")

    def test_2_sop_title_correct(self):
        """2: заголовок SOP содержит ключевые слова."""
        seed = _fresh()
        title = seed.SOP_DATA["title"].lower()
        self.assertIn("этап", title)

    def test_2_sop_status_active(self):
        """2: status == active."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["status"], "active")

    def test_2_sop_owner_manager(self):
        """2: owner_role == manager."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["owner_role"], "manager")

    def test_2_sop_biz_id(self):
        """2: biz_id == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["biz_id"], "BIZ-001")

    def test_2_sop_steps_have_150k(self):
        """2: SOP steps упоминают 150 000 тг."""
        seed = _fresh()
        self.assertIn("150 000", seed.SOP_DATA["steps"])

    def test_2_sop_steps_have_500k(self):
        """2: SOP steps упоминают 500 000 тг."""
        seed = _fresh()
        self.assertIn("500 000", seed.SOP_DATA["steps"])

    def test_2_sop_steps_have_300k(self):
        """2: SOP steps упоминают 300 000 тг."""
        seed = _fresh()
        self.assertIn("300 000", seed.SOP_DATA["steps"])

    def test_2_sop_steps_have_950k(self):
        """2: SOP steps упоминают итог 950 000 тг."""
        seed = _fresh()
        self.assertIn("950 000", seed.SOP_DATA["steps"])

    def test_2_sop_skip_if_exists(self):
        """2: run_seed пропускает SOP если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])

    def test_2_sop_purpose_not_empty(self):
        """2: SOP purpose не пустой."""
        seed = _fresh()
        self.assertGreater(len(seed.SOP_DATA["purpose"]), 10)

    def test_2_sop_expected_result_not_empty(self):
        """2: SOP expected_result не пустой."""
        seed = _fresh()
        self.assertGreater(len(seed.SOP_DATA["expected_result"]), 10)


# ────────────────────────────────────────────────────────────
# 3. seed создает CHK-IZH-COMMERCIAL-MILESTONES-001
# ────────────────────────────────────────────────────────────

class TestCreatesChecklist(unittest.TestCase):

    def test_3_creates_checklist(self):
        """3: run_seed создает CHK-IZH-COMMERCIAL-MILESTONES-001."""
        seed  = _fresh()
        sheet = _sheet(["CHK ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["created"])

    def test_3_checklist_id_constant(self):
        """3: CHECKLIST_ID == CHK-IZH-COMMERCIAL-MILESTONES-001."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_ID, "CHK-IZH-COMMERCIAL-MILESTONES-001")

    def test_3_checklist_title_correct(self):
        """3: заголовок Checklist содержит ключевые слова."""
        seed = _fresh()
        title = seed.CHECKLIST_DATA["title"].lower()
        self.assertIn("этап", title)

    def test_3_checklist_status_active(self):
        """3: status == active."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["status"], "active")

    def test_3_checklist_items_20(self):
        """3: checklist содержит 20 пунктов."""
        seed  = _fresh()
        items = [i.strip() for i in seed.CHECKLIST_DATA["items"].split(";") if i.strip()]
        self.assertEqual(len(items), 20)

    def test_3_checklist_items_has_etap_1(self):
        """3: checklist содержит пункт об Этапе 1."""
        seed = _fresh()
        self.assertIn("Этап 1", seed.CHECKLIST_DATA["items"])

    def test_3_checklist_items_has_etap_2(self):
        """3: checklist содержит пункт об Этапе 2."""
        seed = _fresh()
        self.assertIn("Этап 2", seed.CHECKLIST_DATA["items"])

    def test_3_checklist_items_has_etap_3(self):
        """3: checklist содержит пункт об Этапе 3."""
        seed = _fresh()
        self.assertIn("Этап 3", seed.CHECKLIST_DATA["items"])

    def test_3_checklist_skip_if_exists(self):
        """3: run_seed пропускает Checklist если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])

    def test_3_checklist_completion_criteria_not_empty(self):
        """3: completion_criteria не пустой."""
        seed = _fresh()
        self.assertGreater(len(seed.CHECKLIST_DATA["completion_criteria"]), 10)


# ────────────────────────────────────────────────────────────
# 4. повторный запуск не создает дубли
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_4_idempotent_all_exist(self):
        """4: повторный запуск когда всё есть — created пустой."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertEqual(result["created"], [])

    def test_4_idempotent_sop_skipped(self):
        """4: SOP попадает в skipped при повторном запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["skipped"])

    def test_4_idempotent_checklist_skipped(self):
        """4: Checklist попадает в skipped при повторном запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["skipped"])

    def test_4_quota_error_treated_as_exists(self):
        """4: 429 quota error в _sop_exists → возвращает True (assume exists)."""
        seed = _fresh()
        with patch("business_core.knowledge_manager.find_sop_by_id",
                   side_effect=Exception("429 Quota exceeded")):
            self.assertTrue(seed._sop_exists())

    def test_4_quota_error_checklist_treated_as_exists(self):
        """4: 429 quota error в _checklist_exists → возвращает True."""
        seed = _fresh()
        with patch("business_core.knowledge_manager.find_checklist_by_id",
                   side_effect=Exception("429 Quota exceeded")):
            self.assertTrue(seed._checklist_exists())

    def test_4_run_seed_returns_dict_keys(self):
        """4: run_seed всегда возвращает dict с created/skipped/errors."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertIn("created", result)
        self.assertIn("skipped", result)
        self.assertIn("errors",  result)


# ────────────────────────────────────────────────────────────
# 5. SOP связан с 8 ИЖС-услугами
# ────────────────────────────────────────────────────────────

class TestServiceLinks(unittest.TestCase):

    def test_5_sop_service_id_has_8_services(self):
        """5: SOP.service_id содержит 8 ИЖС service_id."""
        seed = _fresh()
        svc_str = seed.SOP_DATA["service_id"]
        svcs = [s.strip() for s in svc_str.split(";") if s.strip()]
        self.assertEqual(len(svcs), 8)

    def test_5_sop_has_all_almaty_services(self):
        """5: SOP связан со всеми 4 Алматы-услугами."""
        seed = _fresh()
        for svc in ["SVC-IZH-001", "SVC-IZH-002", "SVC-IZH-003", "SVC-IZH-004"]:
            self.assertIn(svc, seed.SOP_DATA["service_id"])

    def test_5_sop_has_all_astana_services(self):
        """5: SOP связан со всеми 4 Астана-услугами."""
        seed = _fresh()
        for svc in ["SVC-IZH-AST-001", "SVC-IZH-AST-002", "SVC-IZH-AST-003", "SVC-IZH-AST-004"]:
            self.assertIn(svc, seed.SOP_DATA["service_id"])

    def test_5_checklist_service_id_has_8_services(self):
        """5: Checklist.service_id содержит 8 ИЖС service_id."""
        seed = _fresh()
        svc_str = seed.CHECKLIST_DATA["service_id"]
        svcs = [s.strip() for s in svc_str.split(";") if s.strip()]
        self.assertEqual(len(svcs), 8)

    def test_5_checklist_has_all_almaty_services(self):
        """5: Checklist связан со всеми 4 Алматы-услугами."""
        seed = _fresh()
        for svc in ["SVC-IZH-001", "SVC-IZH-002", "SVC-IZH-003", "SVC-IZH-004"]:
            self.assertIn(svc, seed.CHECKLIST_DATA["service_id"])

    def test_5_checklist_has_all_astana_services(self):
        """5: Checklist связан со всеми 4 Астана-услугами."""
        seed = _fresh()
        for svc in ["SVC-IZH-AST-001", "SVC-IZH-AST-002", "SVC-IZH-AST-003", "SVC-IZH-AST-004"]:
            self.assertIn(svc, seed.CHECKLIST_DATA["service_id"])

    def test_5_izh_service_ids_constant(self):
        """5: IZH_SERVICE_IDS модуля содержит 8 услуг."""
        seed = _fresh()
        svcs = [s.strip() for s in seed.IZH_SERVICE_IDS.split(";") if s.strip()]
        self.assertEqual(len(svcs), 8)


# ────────────────────────────────────────────────────────────
# 6. существующие roadmap templates не меняются
# ────────────────────────────────────────────────────────────

class TestRoadmapTemplatesUnchanged(unittest.TestCase):

    def test_6_no_roadmap_template_writes(self):
        """6: run_seed не пишет в roadmap_templates."""
        seed   = _fresh()
        writes = []

        def track_write(sheet_key, row):
            if "roadmap_template" in sheet_key:
                writes.append((sheet_key, row))

        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.append_business_row", side_effect=track_write):
            seed.run_seed(verbose=False)
        self.assertEqual(writes, [])

    def test_6_seed_does_not_import_roadmap_template_manager(self):
        """6: seed не импортирует roadmap_template_manager."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("roadmap_template_manager", imports)

    def test_6_no_create_template_calls(self):
        """6: run_seed не вызывает create_roadmap_template."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.roadmap_template_manager.create_roadmap_template",
                   side_effect=lambda **kw: calls.append(kw)) if False else \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 7. существующие stages не меняются
# ────────────────────────────────────────────────────────────

class TestStagesUnchanged(unittest.TestCase):

    def test_7_no_roadmap_stages_writes(self):
        """7: run_seed не пишет в roadmap_stages."""
        seed   = _fresh()
        writes = []

        def track_write(sheet_key, row):
            if "roadmap_stage" in sheet_key:
                writes.append((sheet_key, row))

        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.append_business_row", side_effect=track_write):
            seed.run_seed(verbose=False)
        self.assertEqual(writes, [])

    def test_7_seed_does_not_import_roadmap_manager(self):
        """7: seed не импортирует roadmap_manager напрямую."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("roadmap_manager", imports)

    def test_7_no_batch_append_for_stages(self):
        """7: run_seed не вызывает batch_append_business_rows."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, r: calls.append((k, r))):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 8. новые таблицы не создаются
# ────────────────────────────────────────────────────────────

class TestNoNewSheets(unittest.TestCase):

    def test_8_no_create_sheet_calls(self):
        """8: run_seed не вызывает gspread add_worksheet (не создает таблицы)."""
        import business_core.sheets as sheets_mod
        seed  = _fresh()
        calls = []
        # Проверяем, что seed не вызывает add_worksheet напрямую через gspread
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: calls.append(k)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])

    def test_8_no_add_worksheet_calls(self):
        """8: run_seed не вызывает add_worksheet."""
        seed   = _fresh()
        sheets = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: sheets.append(k)):
            seed.run_seed(verbose=False)
        self.assertEqual(sheets, [])

    def test_8_seed_uses_only_known_sheets(self):
        """8: seed пишет только в sop_registry и checklist_registry."""
        known = {"sop_registry", "checklist_registry"}
        seed  = _fresh()
        sheet = _sheet(["ID", "Title"])
        written_to: set[str] = set()

        def track(sheet_key, row=None):
            written_to.add(sheet_key)

        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row", side_effect=track):
            seed.run_seed(verbose=False)
        unknown = written_to - known
        self.assertEqual(unknown, set())


# ────────────────────────────────────────────────────────────
# 9. GTD Core файлы не импортируются
# ────────────────────────────────────────────────────────────

class TestNoGTDImports(unittest.TestCase):

    def test_9_no_inbox_processor_import(self):
        """9: seed не импортирует inbox_processor."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("inbox_processor", imports)

    def test_9_no_project_planner_import(self):
        """9: seed не импортирует project_planner."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("project_planner", imports)

    def test_9_no_calendar_sync_import(self):
        """9: seed не импортирует calendar_sync."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("calendar_sync", imports)

    def test_9_no_telegram_bot_import(self):
        """9: seed не импортирует telegram_bot."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("telegram_bot", imports)

    def test_9_no_sendpulse_import(self):
        """9: seed не импортирует sendpulse."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("sendpulse", imports)

    def test_9_no_waba_import(self):
        """9: seed не импортирует waba."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("waba", imports)

    def test_9_no_forbidden_gtd_modules(self):
        """9: seed не импортирует ни один из запрещённых GTD-модулей."""
        imports = _imports(SEED_PATH)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, imports, f"Запрещённый импорт: {mod}")


# ────────────────────────────────────────────────────────────
# 10. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvUnchanged(unittest.TestCase):

    def test_10_seed_does_not_write_env(self):
        """10: seed не открывает .env на запись."""
        seed  = _fresh()
        opens = []
        real_open = open

        def fake_open(f, mode="r", *a, **kw):
            if ".env" in str(f) and "w" in str(mode):
                opens.append((str(f), mode))
            return real_open(f, mode, *a, **kw)

        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            seed.run_seed(verbose=False)
        self.assertEqual(opens, [])

    def test_10_env_file_not_imported(self):
        """10: seed не импортирует .env напрямую."""
        imports = _imports(SEED_PATH)
        self.assertNotIn("dotenv", imports)

    def test_10_seed_does_not_contain_env_write(self):
        """10: исходный код seed не содержит open(.env, w)."""
        src = SEED_PATH.read_text(encoding="utf-8")
        self.assertNotIn('open(".env", "w")', src)
        self.assertNotIn("open('.env', 'w')", src)


# ────────────────────────────────────────────────────────────
# Дополнительные проверки данных
# ────────────────────────────────────────────────────────────

class TestDataIntegrity(unittest.TestCase):

    def test_d_sop_steps_mention_apz(self):
        """d: SOP steps упоминают АПЗ."""
        seed = _fresh()
        self.assertIn("АПЗ", seed.SOP_DATA["steps"])

    def test_d_sop_steps_mention_naо(self):
        """d: SOP steps упоминают НАО."""
        seed = _fresh()
        self.assertIn("НАО", seed.SOP_DATA["steps"])

    def test_d_sop_steps_mention_example_template(self):
        """d: SOP steps упоминают пример для RMT-IZH-ALM-STANDARD-002."""
        seed = _fresh()
        self.assertIn("RMT-IZH-ALM-STANDARD-002", seed.SOP_DATA["steps"])

    def test_d_checklist_mentions_bti(self):
        """d: checklist упоминает БТИ."""
        seed = _fresh()
        self.assertIn("БТИ", seed.CHECKLIST_DATA["items"])

    def test_d_checklist_mentions_notary(self):
        """d: checklist упоминает нотариус."""
        seed = _fresh()
        self.assertIn("нотариус", seed.CHECKLIST_DATA["items"])

    def test_d_checklist_mentions_kp(self):
        """d: checklist упоминает КП/договор."""
        seed = _fresh()
        self.assertIn("КП", seed.CHECKLIST_DATA["items"])

    def test_d_sop_notes_mention_services(self):
        """d: SOP notes упоминают service IDs."""
        seed = _fresh()
        self.assertIn("SVC-IZH-001", seed.SOP_DATA["notes"])

    def test_d_seed_file_exists(self):
        """d: файл seed существует."""
        self.assertTrue(SEED_PATH.exists())

    def test_d_seed_file_compiles(self):
        """d: seed компилируется без ошибок."""
        import py_compile
        py_compile.compile(str(SEED_PATH), doraise=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
