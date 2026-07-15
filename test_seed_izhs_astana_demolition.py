"""
Tests for seed_izhs_astana_demolition.py

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

SEED_MODULE   = "business_core.seeds.seed_izhs_astana_demolition"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}


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
        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
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
        """1: dry-run показывает только SKIP если всё уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])

    def test_1_dry_run_shows_5_creates(self):
        """1: dry-run показывает 5 CREATE когда ничего нет."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=0), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 5)


# ────────────────────────────────────────────────────────────
# 2. seed создает service SVC-IZH-AST-004
# ────────────────────────────────────────────────────────────

class TestCreatesService(unittest.TestCase):

    def test_2_creates_service(self):
        """2: run_seed создает SVC-IZH-AST-004."""
        seed  = _fresh()
        sheet = _sheet(["ID", "Name"])
        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Service {seed.SERVICE_ID}", result["created"])
        self.assertEqual(result["errors"], [])

    def test_2_service_id_constant(self):
        """2: SERVICE_ID == SVC-IZH-AST-004."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_ID, "SVC-IZH-AST-004")

    def test_2_service_city_astana(self):
        """2: город — Астана."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["city"], "Астана")

    def test_2_service_category_demolition(self):
        """2: категория — demolition."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["service_category"], "demolition")

    def test_2_service_price_150k(self):
        """2: базовая стоимость от 150 000 тг."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["price_from"], "150000")

    def test_2_service_name_contains_astana(self):
        """2: название услуги содержит 'Астана'."""
        seed = _fresh()
        self.assertIn("Астана", seed.SERVICE_DATA["service_name"])

    def test_2_notes_doc_only(self):
        """2: notes указывают что услуга только документальная."""
        seed = _fresh()
        self.assertIn("документальному", seed.SERVICE_DATA["notes"])

    def test_2_skip_if_service_exists(self):
        """2: run_seed не создает дубль если service уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 3. seed создает roadmap template RMT-IZH-AST-DEMOLITION-001
# ────────────────────────────────────────────────────────────

class TestCreatesTemplate(unittest.TestCase):

    def test_3_creates_template(self):
        """3: run_seed создает template когда его нет."""
        seed  = _fresh()
        sheet = _sheet(["Template ID", "Template Name"])
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.create_roadmap_template",
                   return_value={"ok": True, "template_id": "RTMPL-TMP", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Template {seed.TEMPLATE_ID}", result["created"])

    def test_3_template_id_constant(self):
        """3: TEMPLATE_ID == RMT-IZH-AST-DEMOLITION-001."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_ID, "RMT-IZH-AST-DEMOLITION-001")

    def test_3_template_case_type(self):
        """3: case_type == astana_izhs_demolition."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_DATA["case_type"], "astana_izhs_demolition")

    def test_3_template_name_contains_astana(self):
        """3: название шаблона содержит Астана."""
        seed = _fresh()
        self.assertIn("Астана", seed.TEMPLATE_DATA["template_name"])

    def test_3_template_links_to_service(self):
        """3: template привязан к SVC-IZH-AST-004."""
        seed = _fresh()
        self.assertEqual(seed.TEMPLATE_DATA["service_id"], "SVC-IZH-AST-004")

    def test_3_service_has_default_template(self):
        """3: SERVICE_DATA.default_roadmap_template_id == RMT-IZH-AST-DEMOLITION-001."""
        seed = _fresh()
        self.assertEqual(
            seed.SERVICE_DATA["default_roadmap_template_id"],
            "RMT-IZH-AST-DEMOLITION-001",
        )


# ────────────────────────────────────────────────────────────
# 4. seed создает 9 template stages
# ────────────────────────────────────────────────────────────

class TestCreatesStages(unittest.TestCase):

    def test_4_creates_9_stages(self):
        """4: run_seed создает 9 этапов."""
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

        self.assertEqual(len(add_calls), 9)

    def test_4_stage_count_is_9(self):
        """4: в STAGES ровно 9 записей."""
        seed = _fresh()
        self.assertEqual(len(seed.STAGES), 9)

    def test_4_stages_order_1_to_9(self):
        """4: порядковые номера 1-9."""
        seed   = _fresh()
        orders = [s["order"] for s in seed.STAGES]
        self.assertEqual(orders, list(range(1, 10)))

    def test_4_first_stage_primary_analysis(self):
        """4: первый этап — первичный анализ."""
        seed = _fresh()
        self.assertIn("Первичный анализ", seed.STAGES[0]["stage_name"])

    def test_4_last_stage_nao(self):
        """4: последний этап — регистрация в НАО."""
        seed = _fresh()
        self.assertIn("НАО", seed.STAGES[-1]["stage_name"])

    def test_4_has_demolition_client_stage(self):
        """4: есть этап фактического сноса клиентом."""
        seed  = _fresh()
        names = [s["stage_name"] for s in seed.STAGES]
        self.assertTrue(any("снос" in n.lower() and "клиент" in n.lower() for n in names))

    def test_4_partial_adds_missing(self):
        """4: если 4 этапа уже есть — добавляет только 5."""
        seed      = _fresh()
        add_calls = []

        def mock_add(**kwargs):
            add_calls.append(kwargs)
            return {"ok": True, "stage_id": "TSTG-X", "order": 1, "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=4), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.roadmap_template_manager.add_roadmap_template_stage",
                   side_effect=mock_add), \
             patch("business_core.sheets.get_business_sheet", return_value=MagicMock()), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertEqual(len(add_calls), 5)


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["created"])

    def test_5_checklist_id_constant(self):
        """5: CHECKLIST_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_ID, "CHK-IZH-AST-DEMOLITION-DOCS-001")

    def test_5_checklist_has_12_items(self):
        """5: чек-лист содержит 12 пунктов."""
        seed  = _fresh()
        items = [i.strip() for i in seed.CHECKLIST_DATA["items"].split(";") if i.strip()]
        self.assertEqual(len(items), 12, f"Ожидалось 12 пунктов, нашли {len(items)}: {items}")

    def test_5_checklist_links_to_template(self):
        """5: checklist привязан к RMT-IZH-AST-DEMOLITION-001."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["template_id"], "RMT-IZH-AST-DEMOLITION-001")

    def test_5_checklist_links_to_service(self):
        """5: checklist привязан к SVC-IZH-AST-004."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["service_id"], "SVC-IZH-AST-004")

    def test_5_checklist_title_contains_astana(self):
        """5: название чек-листа содержит Астан."""
        seed = _fresh()
        self.assertIn("Астан", seed.CHECKLIST_DATA["title"])


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_6_sop_id_constant(self):
        """6: SOP_ID корректный."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-IZH-AST-DEMOLITION-PRIMARY-001")

    def test_6_sop_has_11_steps(self):
        """6: SOP содержит 11 шагов."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        count = sum(1 for i in range(1, 12) if f"{i}." in steps)
        self.assertEqual(count, 11)

    def test_6_sop_mentions_template(self):
        """6: SOP ссылается на RMT-IZH-AST-DEMOLITION-001."""
        seed = _fresh()
        self.assertIn("RMT-IZH-AST-DEMOLITION-001", seed.SOP_DATA["expected_result"])

    def test_6_sop_links_to_service(self):
        """6: SOP привязан к SVC-IZH-AST-004."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["service_id"], "SVC-IZH-AST-004")

    def test_6_sop_title_contains_astana(self):
        """6: SOP заголовок содержит Астан."""
        seed = _fresh()
        self.assertIn("Астан", seed.SOP_DATA["title"])


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
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
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
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertGreaterEqual(len(result["skipped"]), 5)

    def test_7_quota_error_treated_as_exists(self):
        """7: 429 quota error трактуется как 'уже существует'."""
        seed = _fresh()
        quota_exc = Exception("APIError: [429]: Quota exceeded")
        with patch("business_core.service_manager.find_service_by_id",
                   side_effect=quota_exc):
            exists = seed._service_exists()
        self.assertTrue(exists)

    def test_7_rename_id_skips_if_same(self):
        """7: _rename_id_in_sheet не вызывает update_cell если IDs совпадают."""
        seed  = _fresh()
        sheet = MagicMock()
        seed._rename_id_in_sheet(sheet, "SAME-001", "SAME-001")
        sheet.get_all_values.assert_not_called()


# ────────────────────────────────────────────────────────────
# 8. service получает Default Roadmap Template ID
# ────────────────────────────────────────────────────────────

class TestDefaultTemplate(unittest.TestCase):

    def test_8_service_data_has_default_template(self):
        """8: SERVICE_DATA.default_roadmap_template_id корректный."""
        seed = _fresh()
        self.assertEqual(
            seed.SERVICE_DATA.get("default_roadmap_template_id"),
            "RMT-IZH-AST-DEMOLITION-001",
        )

    def test_8_create_service_called_with_template_id(self):
        """8: create_service_record вызывается с default_roadmap_template_id."""
        seed  = _fresh()
        calls = []
        sheet = _sheet(["ID"])

        def mock_create(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "service_id": "SVC-TMP-001", "error": None}

        with patch(f"{SEED_MODULE}._service_exists",   return_value=False), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch("business_core.service_manager.create_service_record",
                   side_effect=mock_create), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].get("default_roadmap_template_id"),
            "RMT-IZH-AST-DEMOLITION-001",
        )

    def test_8_biz_ids_match(self):
        """8: biz_id в шаблоне и услуге совпадает."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["biz_id"], seed.TEMPLATE_DATA["biz_id"])

    def test_8_astana_not_almaty(self):
        """8: услуга относится к Астане, не к Алматы."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["city"], "Астана")
        self.assertNotEqual(seed.SERVICE_DATA["city"], "Алматы")

    def test_8_ast004_unique(self):
        """8: SERVICE_ID == SVC-IZH-AST-004."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_ID, "SVC-IZH-AST-004")


# ────────────────────────────────────────────────────────────
# 9. GTD Core не импортируется и не меняется
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check_file(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_9_seed_file(self):
        """9: seed не импортирует GTD Core модули."""
        self._check_file(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_astana_demolition.py"
        )

    def test_9_service_manager(self):
        """9: service_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "service_manager.py")

    def test_9_knowledge_manager(self):
        """9: knowledge_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_9_no_gtd_in_run_seed(self):
        """9: run_seed не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox",
                          "inbox_processor", "telegram_bot"]:
            self.assertNotIn(forbidden, src)

    def test_9_notes_doc_only(self):
        """9: Notes указывают что услуга только документальная."""
        seed = _fresh()
        self.assertIn("документальному", seed.SERVICE_DATA["notes"])


# ────────────────────────────────────────────────────────────
# 10. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_10_env_file_not_modified(self):
        """10: .env файл не изменён этим seed."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        seed = _fresh()
        with patch(f"{SEED_MODULE}._service_exists",   return_value=True), \
             patch(f"{SEED_MODULE}._template_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._stages_count",     return_value=9), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch(f"{SEED_MODULE}._sop_exists",       return_value=True):
            seed.dry_run()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after, ".env был изменён!")

    def test_10_seed_does_not_write_env(self):
        """10: run_seed не пишет в .env."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)

    def test_10_biz_id_biz_001(self):
        """10: BIZ_ID == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")

    def test_10_currency_kzt(self):
        """10: валюта KZT."""
        seed = _fresh()
        self.assertEqual(seed.SERVICE_DATA["currency"], "KZT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
