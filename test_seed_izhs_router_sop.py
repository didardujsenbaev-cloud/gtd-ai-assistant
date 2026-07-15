"""
Tests for seed_izhs_router_sop.py

Checks 1–7 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE   = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE   = "business_core.seeds.seed_izhs_router_sop"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

IZH_SERVICE_IDS_EXPECTED = [
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

    def test_1_dry_run_partial(self):
        """1: dry-run показывает 1 CREATE если SOP уже есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 1)
        self.assertIn("Checklist", result["plan"][0])


# ────────────────────────────────────────────────────────────
# 2. seed создает SOP-IZH-ROUTER-001
# ────────────────────────────────────────────────────────────

class TestCreatesSOP(unittest.TestCase):

    def test_2_creates_sop(self):
        """2: run_seed создает SOP-IZH-ROUTER-001."""
        seed  = _fresh()
        sheet = _sheet(["SOP ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=False), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])
        self.assertEqual(result["errors"], [])

    def test_2_sop_id_constant(self):
        """2: SOP_ID == SOP-IZH-ROUTER-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-IZH-ROUTER-001")

    def test_2_sop_title_correct(self):
        """2: заголовок SOP корректный."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["title"], "Как определить услугу ИЖС")

    def test_2_sop_has_9_steps(self):
        """2: SOP содержит шаги 1-9."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        for i in range(1, 10):
            self.assertIn(f"{i}.", steps, f"Нет шага {i}")

    def test_2_sop_mentions_all_cities(self):
        """2: SOP упоминает Алматы и Астана."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("Алматы", steps)
        self.assertIn("Астана", steps)

    def test_2_sop_mentions_demolition(self):
        """2: SOP содержит логику для сноса."""
        seed = _fresh()
        self.assertIn("снос", seed.SOP_DATA["steps"].lower())

    def test_2_sop_mentions_newbuild(self):
        """2: SOP содержит логику для нового строительства."""
        seed = _fresh()
        self.assertIn("новое строительство", seed.SOP_DATA["steps"].lower())

    def test_2_sop_mentions_outbuilding(self):
        """2: SOP содержит логику для хозпостройки."""
        seed = _fresh()
        self.assertIn("хозпостройк", seed.SOP_DATA["steps"].lower())

    def test_2_sop_mentions_reconstruction(self):
        """2: SOP содержит логику для реконструкции."""
        seed = _fresh()
        self.assertIn("реконструкц", seed.SOP_DATA["steps"].lower())

    def test_2_sop_owner_role_manager(self):
        """2: owner_role == manager."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["owner_role"], "manager")

    def test_2_sop_status_active(self):
        """2: статус active."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["status"], "active")

    def test_2_sop_skip_if_exists(self):
        """2: run_seed не создает SOP если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])

    def test_2_sop_examples_present(self):
        """2: SOP содержит примеры с конкретными service_id."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("SVC-IZH-001", steps)
        self.assertIn("SVC-IZH-002", steps)
        self.assertIn("SVC-IZH-004", steps)
        self.assertIn("SVC-IZH-AST-001", steps)


# ────────────────────────────────────────────────────────────
# 3. seed создает CHK-IZH-ROUTER-001
# ────────────────────────────────────────────────────────────

class TestCreatesChecklist(unittest.TestCase):

    def test_3_creates_checklist(self):
        """3: run_seed создает CHK-IZH-ROUTER-001."""
        seed  = _fresh()
        sheet = _sheet(["Checklist ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=False), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   return_value={"ok": True, "checklist_id": "CHK-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"Checklist {seed.CHECKLIST_ID}", result["created"])

    def test_3_checklist_id_constant(self):
        """3: CHECKLIST_ID == CHK-IZH-ROUTER-001."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_ID, "CHK-IZH-ROUTER-001")

    def test_3_checklist_title_correct(self):
        """3: заголовок чек-листа корректный."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["title"], "Чек-лист классификации клиента ИЖС")

    def test_3_checklist_has_13_items(self):
        """3: чек-лист содержит 13 пунктов."""
        seed  = _fresh()
        items = [i.strip() for i in seed.CHECKLIST_DATA["items"].split(";") if i.strip()]
        self.assertEqual(len(items), 13, f"Ожидалось 13 пунктов, нашли {len(items)}: {items}")

    def test_3_checklist_status_active(self):
        """3: статус active."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["status"], "active")

    def test_3_checklist_skip_if_exists(self):
        """3: run_seed не создает дубль checklist."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.knowledge_manager.create_checklist_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 4. повторный запуск не создает дубли
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_4_no_writes_second_run(self):
        """4: повторный запуск не вызывает append_business_row."""
        seed    = _fresh()
        appends = []
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appends.append((k, r))):
            result = seed.run_seed(verbose=False)
        self.assertEqual(appends, [])
        self.assertEqual(result["created"], [])

    def test_4_all_skipped_when_exists(self):
        """4: оба объекта в skipped при повторном запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(result["errors"],  [])

    def test_4_quota_error_assumed_exists(self):
        """4: 429 quota error — _sop_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("APIError: [429]: Quota exceeded")
        with patch("business_core.knowledge_manager.find_sop_by_id",
                   side_effect=quota):
            exists = seed._sop_exists()
        self.assertTrue(exists)

    def test_4_quota_error_checklist_assumed_exists(self):
        """4: 429 quota error — _checklist_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("Quota exceeded for 429")
        with patch("business_core.knowledge_manager.find_checklist_by_id",
                   side_effect=quota):
            exists = seed._checklist_exists()
        self.assertTrue(exists)

    def test_4_rename_skips_if_same(self):
        """4: _rename_id_in_sheet не вызывает update_cell если IDs равны."""
        seed  = _fresh()
        sheet = MagicMock()
        seed._rename_id_in_sheet(sheet, "SAME-001", "SAME-001")
        sheet.get_all_values.assert_not_called()


# ────────────────────────────────────────────────────────────
# 5. SOP/Checklist связаны с 8 ИЖС-услугами
# ────────────────────────────────────────────────────────────

class TestServiceBinding(unittest.TestCase):

    def test_5_sop_service_id_contains_8_services(self):
        """5: SOP.service_id содержит все 8 ИЖС-услуг."""
        seed = _fresh()
        for svc in IZH_SERVICE_IDS_EXPECTED:
            self.assertIn(svc, seed.SOP_DATA["service_id"],
                          f"SOP.service_id не содержит {svc}")

    def test_5_checklist_service_id_contains_8_services(self):
        """5: Checklist.service_id содержит все 8 ИЖС-услуг."""
        seed = _fresh()
        for svc in IZH_SERVICE_IDS_EXPECTED:
            self.assertIn(svc, seed.CHECKLIST_DATA["service_id"],
                          f"Checklist.service_id не содержит {svc}")

    def test_5_izh_service_ids_constant(self):
        """5: IZH_SERVICE_IDS содержит 8 айди."""
        seed = _fresh()
        ids  = [s.strip() for s in seed.IZH_SERVICE_IDS.split(";") if s.strip()]
        self.assertEqual(len(ids), 8)

    def test_5_almaty_services_present(self):
        """5: Алматы-услуги присутствуют в IZH_SERVICE_IDS."""
        seed = _fresh()
        for svc in ["SVC-IZH-001", "SVC-IZH-002", "SVC-IZH-003", "SVC-IZH-004"]:
            self.assertIn(svc, seed.IZH_SERVICE_IDS)

    def test_5_astana_services_present(self):
        """5: Астана-услуги присутствуют в IZH_SERVICE_IDS."""
        seed = _fresh()
        for svc in ["SVC-IZH-AST-001", "SVC-IZH-AST-002",
                    "SVC-IZH-AST-003", "SVC-IZH-AST-004"]:
            self.assertIn(svc, seed.IZH_SERVICE_IDS)

    def test_5_biz_id_biz_001(self):
        """5: BIZ_ID == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")

    def test_5_sop_data_biz_id(self):
        """5: SOP_DATA.biz_id == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["biz_id"], "BIZ-001")

    def test_5_checklist_data_biz_id(self):
        """5: CHECKLIST_DATA.biz_id == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.CHECKLIST_DATA["biz_id"], "BIZ-001")


# ────────────────────────────────────────────────────────────
# 6. GTD Core не импортируется и не меняется
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check_file(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_6_seed_file(self):
        """6: seed не импортирует GTD Core."""
        self._check_file(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_router_sop.py"
        )

    def test_6_knowledge_manager(self):
        """6: knowledge_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_6_run_seed_no_gtd_calls(self):
        """6: run_seed не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox",
                          "inbox_processor", "telegram_bot"]:
            self.assertNotIn(forbidden, src)

    def test_6_no_gtd_in_module_level(self):
        """6: верхний уровень seed не содержит GTD imports."""
        seed_file = WORKSPACE / "business_core" / "seeds" / "seed_izhs_router_sop.py"
        text = seed_file.read_text(encoding="utf-8")
        for forbidden in GTD_FORBIDDEN:
            self.assertNotIn(f"import {forbidden}", text,
                             f"seed содержит 'import {forbidden}'")


# ────────────────────────────────────────────────────────────
# 7. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_7_env_not_modified(self):
        """7: .env не изменён seed'ом."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",       return_value=True), \
             patch(f"{SEED_MODULE}._checklist_exists", return_value=True):
            seed.dry_run()
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)

    def test_7_run_seed_no_env_writes(self):
        """7: run_seed не пишет в .env."""
        seed = _fresh()
        import inspect
        src = inspect.getsource(seed.run_seed)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)

    def test_7_currency_not_in_sop(self):
        """7: SOP не содержит валютных данных (не финансовый документ)."""
        seed = _fresh()
        self.assertNotIn("KZT", seed.SOP_DATA["steps"])

    def test_7_sop_purpose_is_set(self):
        """7: SOP.purpose не пустой."""
        seed = _fresh()
        self.assertGreater(len(seed.SOP_DATA["purpose"]), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
