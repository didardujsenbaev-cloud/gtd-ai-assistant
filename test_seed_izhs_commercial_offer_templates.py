"""
Tests for seed_izhs_commercial_offer_templates.py

Checks 1–8 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE   = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

SEED_MODULE   = "business_core.seeds.seed_izhs_commercial_offer_templates"
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


def _mock_doc_create(**kwargs):
    return {"ok": True, "doc_template_id": "DTMPL-TMP-001", "error": None}


# ────────────────────────────────────────────────────────────
# 1. dry-run не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_1_dry_run_no_writes(self):
        """1: dry-run не вызывает append_business_row."""
        seed   = _fresh()
        writes = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=False), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            result = seed.dry_run()
        self.assertEqual(writes, [])

    def test_1_dry_run_shows_5_creates(self):
        """1: dry-run показывает 5 CREATE (4 DOC + 1 SOP) когда ничего нет."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 5)

    def test_1_dry_run_all_exist(self):
        """1: dry-run показывает только SKIP если всё есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])
        self.assertEqual(len(result["skip"]), 5)

    def test_1_dry_run_partial(self):
        """1: dry-run показывает CREATE только для отсутствующих."""
        seed = _fresh()
        existing = {"DOC-IZH-KP-001", "DOC-IZH-KP-002"}

        def mock_doc_exists(did):
            return did in existing

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  side_effect=mock_doc_exists):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 2)


# ────────────────────────────────────────────────────────────
# 2. seed создает DOC-IZH-KP-001…004
# ────────────────────────────────────────────────────────────

class TestCreatesDocTemplates(unittest.TestCase):

    def _run_all_creates(self, seed):
        sheet   = _sheet(["ID", "Title"])
        ctr     = {"n": 0}

        def mock_create(**kwargs):
            ctr["n"] += 1
            return {"ok": True, "doc_template_id": f"DTMPL-TMP-{ctr['n']:03d}", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_document_template_record",
                   side_effect=mock_create), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            return seed.run_seed(verbose=False)

    def test_2_creates_4_doc_templates(self):
        """2: run_seed создает 4 DOC шаблона."""
        seed   = _fresh()
        result = self._run_all_creates(seed)
        docs   = [c for c in result["created"] if c.startswith("DOC-")]
        self.assertEqual(len(docs), 4)

    def test_2_doc_ids_constant(self):
        """2: DOC_IDS содержит 4 айди."""
        seed = _fresh()
        self.assertEqual(len(seed.DOC_IDS), 4)

    def test_2_docs_list_has_4(self):
        """2: DOCS содержит 4 записи."""
        seed = _fresh()
        self.assertEqual(len(seed.DOCS), 4)

    def test_2_all_doc_ids_present(self):
        """2: DOC IDs от KP-001 до KP-004."""
        seed = _fresh()
        ids  = [d["doc_id"] for d in seed.DOCS]
        for i in range(1, 5):
            self.assertIn(f"DOC-IZH-KP-{i:03d}", ids)

    def test_2_kp001_reconstruction(self):
        """2: DOC-IZH-KP-001 — реконструкция."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-001")
        self.assertIn("реконструкц", doc["title"].lower())

    def test_2_kp002_newbuild(self):
        """2: DOC-IZH-KP-002 — новое строительство."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-002")
        self.assertIn("строительство", doc["title"].lower())

    def test_2_kp003_outbuilding(self):
        """2: DOC-IZH-KP-003 — хозпостройка."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-003")
        self.assertIn("хозпостройка", doc["title"].lower())

    def test_2_kp004_demolition(self):
        """2: DOC-IZH-KP-004 — снос."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-004")
        self.assertIn("снос", doc["title"].lower())

    def test_2_all_docs_commercial_offer_type(self):
        """2: все шаблоны имеют document_type=commercial_offer."""
        seed = _fresh()
        for doc in seed.DOCS:
            self.assertEqual(doc["document_type"], "commercial_offer",
                             f"{doc['doc_id']} имеет неверный document_type")

    def test_2_all_docs_have_description(self):
        """2: все шаблоны имеют непустой description."""
        seed = _fresh()
        for doc in seed.DOCS:
            self.assertGreater(len(doc["description"]), 100,
                               f"{doc['doc_id']} имеет слишком короткий description")

    def test_2_doc_created_with_commercial_offer_type(self):
        """2: create_document_template_record вызывается с document_type=commercial_offer."""
        seed  = _fresh()
        sheet = _sheet(["ID", "Title"])
        calls = []

        def mock_create(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "doc_template_id": "DTMPL-TMP-001", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_document_template_record",
                   side_effect=mock_create), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertEqual(len(calls), 4)
        for call in calls:
            self.assertEqual(call.get("document_type"), "commercial_offer")

    def test_2_all_docs_have_template_placeholders(self):
        """2: шаблоны КП содержат переменные {{city}}."""
        seed = _fresh()
        for doc in seed.DOCS:
            if doc["doc_id"] != "DOC-IZH-KP-004":  # KP-004 has fixed price
                self.assertIn("{{city}}", doc["description"],
                              f"{doc['doc_id']} не содержит {{{{city}}}}")

    def test_2_kp004_fixed_price(self):
        """2: DOC-IZH-KP-004 содержит фиксированную цену 150 000 тг."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-004")
        self.assertIn("150 000", doc["description"])

    def test_2_doc_skip_if_exists(self):
        """2: run_seed пропускает DOC если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True), \
             patch("business_core.knowledge_manager.create_document_template_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 3. seed создает SOP-DOC-IZH-KP-001
# ────────────────────────────────────────────────────────────

class TestCreatesSOP(unittest.TestCase):

    def test_3_creates_sop(self):
        """3: run_seed создает SOP-DOC-IZH-KP-001."""
        seed  = _fresh()
        sheet = _sheet(["SOP ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])

    def test_3_sop_id_constant(self):
        """3: SOP_ID == SOP-DOC-IZH-KP-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-DOC-IZH-KP-001")

    def test_3_sop_title_correct(self):
        """3: заголовок SOP корректный."""
        seed = _fresh()
        self.assertIn("коммерческ", seed.SOP_DATA["title"].lower())

    def test_3_sop_references_intake_and_router(self):
        """3: SOP ссылается на INTAKE и ROUTER."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("SOP-IZH-INTAKE-001", steps)
        self.assertIn("SOP-IZH-ROUTER-001", steps)

    def test_3_sop_references_all_4_docs(self):
        """3: SOP ссылается на все 4 DOC шаблона."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        for doc_id in seed.DOC_IDS:
            self.assertIn(doc_id, steps, f"SOP не ссылается на {doc_id}")

    def test_3_sop_owner_manager(self):
        """3: owner_role == manager."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["owner_role"], "manager")

    def test_3_sop_no_100_guarantee(self):
        """3: SOP содержит запрет на гарантии."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("100%", steps)

    def test_3_sop_skip_if_exists(self):
        """3: run_seed пропускает SOP если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
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
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appends.append((k, r))):
            result = seed.run_seed(verbose=False)
        self.assertEqual(appends, [])
        self.assertEqual(result["created"], [])

    def test_4_all_5_skipped(self):
        """4: все 5 записей в skipped при повторном запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=True):
            result = seed.run_seed(verbose=False)
        self.assertEqual(len(result["skipped"]), 5)
        self.assertEqual(result["errors"], [])

    def test_4_quota_sop_assumed_exists(self):
        """4: 429 quota error — _sop_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("APIError: [429]: Quota exceeded")
        with patch("business_core.knowledge_manager.find_sop_by_id",
                   side_effect=quota):
            self.assertTrue(seed._sop_exists())

    def test_4_quota_doc_assumed_exists(self):
        """4: 429 quota error — _doc_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("Quota exceeded")
        with patch("business_core.knowledge_manager.find_document_template_by_id",
                   side_effect=quota):
            self.assertTrue(seed._doc_exists("DOC-IZH-KP-001"))

    def test_4_rename_skips_same_id(self):
        """4: _rename_id_in_sheet не вызывает update_cell если IDs равны."""
        seed  = _fresh()
        sheet = MagicMock()
        seed._rename_id_in_sheet(sheet, "SAME-001", "SAME-001")
        sheet.get_all_values.assert_not_called()

    def test_4_partial_run_only_missing(self):
        """4: создаёт только отсутствующие шаблоны."""
        seed     = _fresh()
        existing = {"DOC-IZH-KP-001", "DOC-IZH-KP-002"}
        sheet    = _sheet(["ID", "Title"])
        ctr      = {"n": 0}

        def mock_doc_exists(did):
            return did in existing

        def mock_create(**kwargs):
            ctr["n"] += 1
            return {"ok": True, "doc_template_id": f"DTMPL-TMP-{ctr['n']:03d}", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  side_effect=mock_doc_exists), \
             patch("business_core.knowledge_manager.create_document_template_record",
                   side_effect=mock_create), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertEqual(ctr["n"], 2)


# ────────────────────────────────────────────────────────────
# 5. связь с ИЖС-услугами
# ────────────────────────────────────────────────────────────

class TestServiceBinding(unittest.TestCase):

    def test_5_kp001_linked_to_izh001_and_ast001(self):
        """5: DOC-IZH-KP-001 привязан к SVC-IZH-001 и SVC-IZH-AST-001."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-001")
        self.assertIn("SVC-IZH-001",     doc["service_ids"])
        self.assertIn("SVC-IZH-AST-001", doc["service_ids"])

    def test_5_kp002_linked_to_izh002_and_ast002(self):
        """5: DOC-IZH-KP-002 привязан к SVC-IZH-002 и SVC-IZH-AST-002."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-002")
        self.assertIn("SVC-IZH-002",     doc["service_ids"])
        self.assertIn("SVC-IZH-AST-002", doc["service_ids"])

    def test_5_kp003_linked_to_izh003_and_ast003(self):
        """5: DOC-IZH-KP-003 привязан к SVC-IZH-003 и SVC-IZH-AST-003."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-003")
        self.assertIn("SVC-IZH-003",     doc["service_ids"])
        self.assertIn("SVC-IZH-AST-003", doc["service_ids"])

    def test_5_kp004_linked_to_izh004_and_ast004(self):
        """5: DOC-IZH-KP-004 привязан к SVC-IZH-004 и SVC-IZH-AST-004."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-004")
        self.assertIn("SVC-IZH-004",     doc["service_ids"])
        self.assertIn("SVC-IZH-AST-004", doc["service_ids"])

    def test_5_sop_linked_to_all_services(self):
        """5: SOP привязан ко всем 8 ИЖС-услугам."""
        seed = _fresh()
        for svc in ["SVC-IZH-001", "SVC-IZH-002", "SVC-IZH-003", "SVC-IZH-004",
                    "SVC-IZH-AST-001", "SVC-IZH-AST-002", "SVC-IZH-AST-003", "SVC-IZH-AST-004"]:
            self.assertIn(svc, seed.SOP_DATA["service_id"])

    def test_5_biz_id_biz_001(self):
        """5: BIZ_ID == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")

    def test_5_create_called_with_service_ids(self):
        """5: create_document_template_record вызывается с service_id."""
        seed  = _fresh()
        sheet = _sheet(["ID", "Title"])
        calls = []

        def mock_create(**kwargs):
            calls.append(kwargs)
            return {"ok": True, "doc_template_id": "DTMPL-TMP-001", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_document_template_record",
                   side_effect=mock_create), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        for call in calls:
            self.assertGreater(len(call.get("service_id", "")), 5)


# ────────────────────────────────────────────────────────────
# 6. GTD Core не импортируется
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
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_commercial_offer_templates.py"
        )

    def test_6_knowledge_manager(self):
        """6: knowledge_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_6_run_seed_no_gtd_calls(self):
        """6: run_seed не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src  = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox"]:
            self.assertNotIn(forbidden, src)


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
        with patch(f"{SEED_MODULE}._sop_exists", return_value=True), \
             patch(f"{SEED_MODULE}._doc_exists", return_value=True):
            seed.dry_run()
        self.assertEqual(mtime_before, os.path.getmtime(env_path))

    def test_7_run_seed_no_env_writes(self):
        """7: run_seed не пишет в .env."""
        seed = _fresh()
        import inspect
        src  = inspect.getsource(seed.run_seed)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)


# ────────────────────────────────────────────────────────────
# 8. внешние API не подключаются
# ────────────────────────────────────────────────────────────

class TestNoExternalAPI(unittest.TestCase):

    def test_8_no_requests_import(self):
        """8: seed не импортирует requests/httpx/aiohttp."""
        mods = _imports(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_commercial_offer_templates.py"
        )
        for forbidden in ["requests", "httpx", "aiohttp", "urllib"]:
            self.assertNotIn(forbidden, mods)

    def test_8_no_sendpulse_in_imports(self):
        """8: seed не импортирует sendpulse."""
        mods = [m.lower() for m in _imports(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_commercial_offer_templates.py"
        )]
        self.assertNotIn("sendpulse", mods)

    def test_8_doc_descriptions_no_promises(self):
        """8: ни один шаблон КП не содержит запрещённых обещаний."""
        seed      = _fresh()
        forbidden = ["точно узаконим", "100% получится", "гарантируем"]
        for doc in seed.DOCS:
            text = doc["description"].lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, text,
                                 f"{doc['doc_id']} содержит '{phrase}'")

    def test_8_kp_texts_have_important_warning(self):
        """8: шаблоны реконструкции содержат предупреждение о рисках."""
        seed = _fresh()
        doc  = next(d for d in seed.DOCS if d["doc_id"] == "DOC-IZH-KP-001")
        self.assertIn("не гарантирует", doc["description"].lower())

    def test_8_no_duplicate_doc_ids(self):
        """8: нет дублирующихся doc_id."""
        seed = _fresh()
        ids  = [d["doc_id"] for d in seed.DOCS]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
