"""
Tests for seed_izhs_whatsapp_templates.py

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

SEED_MODULE   = "business_core.seeds.seed_izhs_whatsapp_templates"
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}
WA_FORBIDDEN  = {"sendpulse", "waba", "requests"}   # no external API

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


def _all_exist_patches(seed):
    """Patch all existence checks to return True."""
    patches = [
        patch(f"{SEED_MODULE}._sop_exists", return_value=True),
    ]
    for msg in seed.MESSAGES:
        patches.append(
            patch(f"{SEED_MODULE}._msg_exists", return_value=True)
        )
    return patches


# ────────────────────────────────────────────────────────────
# 1. dry-run не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestDryRun(unittest.TestCase):

    def test_1_dry_run_no_writes(self):
        """1: dry-run не вызывает append_business_row."""
        seed   = _fresh()
        writes = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=False), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            result = seed.dry_run()
        self.assertEqual(writes, [])

    def test_1_dry_run_shows_8_creates(self):
        """1: dry-run показывает 8 CREATE (SOP + 7 шаблонов) когда ничего нет."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=False):
            result = seed.dry_run()
        self.assertEqual(len(result["plan"]), 8)

    def test_1_dry_run_all_exist(self):
        """1: dry-run показывает только SKIP если всё есть."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True):
            result = seed.dry_run()
        self.assertEqual(result["plan"], [])

    def test_1_dry_run_partial(self):
        """1: dry-run показывает CREATE только для отсутствующих."""
        seed     = _fresh()
        existing = {"MSG-IZH-WA-001", "MSG-IZH-WA-002"}

        def mock_msg_exists(mid):
            return mid in existing

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  side_effect=mock_msg_exists):
            result = seed.dry_run()
        # 5 шаблонов + 0 SOP = 5 create
        self.assertEqual(len(result["plan"]), 5)


# ────────────────────────────────────────────────────────────
# 2. seed создает SOP-IZH-WHATSAPP-001
# ────────────────────────────────────────────────────────────

class TestCreatesSOP(unittest.TestCase):

    def test_2_creates_sop(self):
        """2: run_seed создает SOP-IZH-WHATSAPP-001."""
        seed  = _fresh()
        sheet = _sheet(["SOP ID", "Title"])
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=False), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   return_value={"ok": True, "sop_id": "SOP-TMP-001", "error": None}), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)
        self.assertIn(f"SOP {seed.SOP_ID}", result["created"])
        self.assertEqual(result["errors"], [])

    def test_2_sop_id_constant(self):
        """2: SOP_ID == SOP-IZH-WHATSAPP-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_ID, "SOP-IZH-WHATSAPP-001")

    def test_2_sop_title_correct(self):
        """2: заголовок SOP корректный."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["title"],
                         "Как общаться с клиентом по ИЖС в WhatsApp")

    def test_2_sop_has_4_steps(self):
        """2: SOP содержит шаги 1-4."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        for i in range(1, 5):
            self.assertIn(f"{i}.", steps, f"Нет шага {i}")

    def test_2_sop_mentions_forbidden(self):
        """2: SOP содержит запрещённые формулировки."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("точно узаконим", steps)
        self.assertIn("100% получится", steps)

    def test_2_sop_mentions_allowed(self):
        """2: SOP содержит разрешённые формулировки."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("по госорганам и АПЗ есть риски", steps)

    def test_2_sop_owner_operator(self):
        """2: owner_role == operator."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["owner_role"], "operator")

    def test_2_sop_references_intake_and_router(self):
        """2: SOP ссылается на INTAKE и ROUTER SOPs."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"]
        self.assertIn("SOP-IZH-INTAKE-001", steps)
        self.assertIn("SOP-IZH-ROUTER-001", steps)

    def test_2_sop_no_sendpulse_in_steps(self):
        """2: SOP не содержит упоминаний SendPulse API."""
        seed  = _fresh()
        steps = seed.SOP_DATA["steps"].lower()
        self.assertNotIn("sendpulse", steps)

    def test_2_sop_skip_if_exists(self):
        """2: run_seed пропускает SOP если он уже есть."""
        seed  = _fresh()
        calls = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True), \
             patch("business_core.knowledge_manager.create_sop_record",
                   side_effect=lambda **kw: calls.append(kw)):
            seed.run_seed(verbose=False)
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 3. seed создает MSG-IZH-WA-001…007
# ────────────────────────────────────────────────────────────

class TestCreatesMessages(unittest.TestCase):

    def _run_all_creates(self, seed):
        sheet    = _sheet(["ID", "Q"])
        faq_ctr  = {"n": 0}

        def mock_faq(**kwargs):
            faq_ctr["n"] += 1
            return {"ok": True, "faq_id": f"FAQ-TMP-{faq_ctr['n']:03d}", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_faq_record",
                   side_effect=mock_faq), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            return seed.run_seed(verbose=False)

    def test_3_creates_7_messages(self):
        """3: run_seed создает 7 шаблонов сообщений."""
        seed   = _fresh()
        result = self._run_all_creates(seed)
        msg_created = [c for c in result["created"] if c.startswith("MSG-")]
        self.assertEqual(len(msg_created), 7)

    def test_3_msg_ids_in_constant(self):
        """3: MSG_IDS содержит 7 айди."""
        seed = _fresh()
        self.assertEqual(len(seed.MSG_IDS), 7)

    def test_3_messages_list_has_7(self):
        """3: MESSAGES содержит 7 записей."""
        seed = _fresh()
        self.assertEqual(len(seed.MESSAGES), 7)

    def test_3_all_msg_ids_correct(self):
        """3: MSG IDs от 001 до 007."""
        seed = _fresh()
        ids  = [m["msg_id"] for m in seed.MESSAGES]
        for i in range(1, 8):
            self.assertIn(f"MSG-IZH-WA-{i:03d}", ids)

    def test_3_first_msg_first_contact(self):
        """3: MSG-IZH-WA-001 — для первого контакта."""
        seed = _fresh()
        msg  = next(m for m in seed.MESSAGES if m["msg_id"] == "MSG-IZH-WA-001")
        self.assertIn("впервые", msg["question"].lower())

    def test_3_msg_007_for_guarantees(self):
        """3: MSG-IZH-WA-007 — для вопросов про гарантию."""
        seed = _fresh()
        msg  = next(m for m in seed.MESSAGES if m["msg_id"] == "MSG-IZH-WA-007")
        self.assertIn("гарантию", msg["question"].lower())

    def test_3_all_msgs_have_answer(self):
        """3: все шаблоны имеют непустой answer."""
        seed = _fresh()
        for msg in seed.MESSAGES:
            self.assertGreater(len(msg["answer"]), 50,
                               f"{msg['msg_id']} имеет слишком короткий answer")

    def test_3_all_msgs_have_waba_draft(self):
        """3: все шаблоны содержат WABA Draft в notes."""
        seed = _fresh()
        for msg in seed.MESSAGES:
            self.assertIn("WABA Draft", msg["notes"],
                          f"{msg['msg_id']} не содержит WABA Draft")

    def test_3_category_whatsapp_template(self):
        """3: шаблоны создаются с category=whatsapp_template."""
        seed      = _fresh()
        sheet     = _sheet(["ID", "Q"])
        faq_calls = []

        def mock_faq(**kwargs):
            faq_calls.append(kwargs)
            return {"ok": True, "faq_id": "FAQ-TMP-001", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_faq_record",
                   side_effect=mock_faq), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        self.assertGreater(len(faq_calls), 0)
        for call in faq_calls:
            self.assertEqual(call.get("category"), "whatsapp_template")

    def test_3_no_duplicate_msg_ids(self):
        """3: нет дублирующихся msg_id."""
        seed = _fresh()
        ids  = [m["msg_id"] for m in seed.MESSAGES]
        self.assertEqual(len(ids), len(set(ids)))


# ────────────────────────────────────────────────────────────
# 4. повторный запуск не создает дубли
# ────────────────────────────────────────────────────────────

class TestIdempotency(unittest.TestCase):

    def test_4_no_writes_second_run(self):
        """4: повторный запуск не вызывает append_business_row."""
        seed    = _fresh()
        appends = []
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appends.append((k, r))):
            result = seed.run_seed(verbose=False)
        self.assertEqual(appends, [])
        self.assertEqual(result["created"], [])

    def test_4_all_8_skipped(self):
        """4: все 8 записей в skipped при повторном запуске."""
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True):
            result = seed.run_seed(verbose=False)
        # 1 SOP + 7 templates = 8
        self.assertEqual(len(result["skipped"]), 8)
        self.assertEqual(result["errors"], [])

    def test_4_quota_sop_assumed_exists(self):
        """4: 429 quota error — _sop_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("APIError: [429]: Quota exceeded")
        with patch("business_core.knowledge_manager.find_sop_by_id",
                   side_effect=quota):
            self.assertTrue(seed._sop_exists())

    def test_4_quota_msg_assumed_exists(self):
        """4: 429 quota error — _msg_exists возвращает True."""
        seed  = _fresh()
        quota = Exception("Quota exceeded")
        with patch("business_core.knowledge_manager.find_faq_by_id",
                   side_effect=quota):
            self.assertTrue(seed._msg_exists("MSG-IZH-WA-001"))

    def test_4_rename_skips_same_id(self):
        """4: _rename_id_in_sheet не вызывает update_cell если IDs равны."""
        seed  = _fresh()
        sheet = MagicMock()
        seed._rename_id_in_sheet(sheet, "SAME-001", "SAME-001")
        sheet.get_all_values.assert_not_called()

    def test_4_partial_run_only_missing(self):
        """4: создаёт только отсутствующие шаблоны."""
        seed     = _fresh()
        existing = {"MSG-IZH-WA-001", "MSG-IZH-WA-002", "MSG-IZH-WA-003"}
        sheet    = _sheet(["ID", "Q"])
        faq_ctr  = {"n": 0}

        def mock_msg_exists(mid):
            return mid in existing

        def mock_faq(**kwargs):
            faq_ctr["n"] += 1
            return {"ok": True, "faq_id": f"FAQ-TMP-{faq_ctr['n']:03d}", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",      return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",      side_effect=mock_msg_exists), \
             patch("business_core.knowledge_manager.create_faq_record",
                   side_effect=mock_faq), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            result = seed.run_seed(verbose=False)

        self.assertEqual(faq_ctr["n"], 4)  # только 4 из 7


# ────────────────────────────────────────────────────────────
# 5. связь с 8 ИЖС-услугами
# ────────────────────────────────────────────────────────────

class TestServiceBinding(unittest.TestCase):

    def test_5_sop_contains_8_services(self):
        """5: SOP.service_id содержит все 8 ИЖС-услуг."""
        seed = _fresh()
        for svc in IZH_SERVICE_IDS_EXPECTED:
            self.assertIn(svc, seed.SOP_DATA["service_id"])

    def test_5_izh_service_ids_8_items(self):
        """5: IZH_SERVICE_IDS содержит 8 айди."""
        seed = _fresh()
        ids  = [s.strip() for s in seed.IZH_SERVICE_IDS.split(";") if s.strip()]
        self.assertEqual(len(ids), 8)

    def test_5_faq_created_with_service_ids(self):
        """5: create_faq_record вызывается с IZH_SERVICE_IDS в service_id."""
        seed      = _fresh()
        sheet     = _sheet(["ID", "Q"])
        faq_calls = []

        def mock_faq(**kwargs):
            faq_calls.append(kwargs)
            return {"ok": True, "faq_id": "FAQ-TMP-001", "error": None}

        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=False), \
             patch("business_core.knowledge_manager.create_faq_record",
                   side_effect=mock_faq), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row"):
            seed.run_seed(verbose=False)

        for call in faq_calls:
            for svc in IZH_SERVICE_IDS_EXPECTED:
                self.assertIn(svc, call.get("service_id", ""))

    def test_5_biz_id_biz_001(self):
        """5: BIZ_ID == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")

    def test_5_sop_biz_id(self):
        """5: SOP_DATA.biz_id == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.SOP_DATA["biz_id"], "BIZ-001")


# ────────────────────────────────────────────────────────────
# 6. SendPulse/WABA API не используется
# ────────────────────────────────────────────────────────────

class TestNoExternalAPI(unittest.TestCase):

    def _seed_source(self) -> str:
        path = WORKSPACE / "business_core" / "seeds" / "seed_izhs_whatsapp_templates.py"
        return path.read_text(encoding="utf-8")

    def test_6_no_sendpulse_import(self):
        """6: seed не импортирует sendpulse как модуль."""
        mods = _imports(WORKSPACE / "business_core" / "seeds" / "seed_izhs_whatsapp_templates.py")
        self.assertNotIn("sendpulse", [m.lower() for m in mods])

    def test_6_no_waba_import(self):
        """6: seed не импортирует waba как модуль."""
        mods = _imports(WORKSPACE / "business_core" / "seeds" / "seed_izhs_whatsapp_templates.py")
        self.assertNotIn("waba", [m.lower() for m in mods])

    def test_6_no_requests_import(self):
        """6: seed не делает HTTP requests к внешним API."""
        mods = _imports(WORKSPACE / "business_core" / "seeds" / "seed_izhs_whatsapp_templates.py")
        self.assertNotIn("requests", mods)
        self.assertNotIn("httpx",    mods)
        self.assertNotIn("aiohttp",  mods)

    def test_6_no_api_calls_in_run_seed(self):
        """6: run_seed не содержит вызовов внешних API."""
        seed = _fresh()
        import inspect
        src  = inspect.getsource(seed.run_seed)
        for forbidden in ["sendpulse", "waba", "requests.post", "requests.get"]:
            self.assertNotIn(forbidden, src.lower())

    def test_6_sop_notes_say_manual(self):
        """6: notes SOP указывают что шаблоны используются вручную."""
        seed = _fresh()
        self.assertIn("вручную", seed.SOP_DATA["notes"])


# ────────────────────────────────────────────────────────────
# 7. GTD Core не импортируется
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check_file(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} импортирует {mod!r}")

    def test_7_seed_file(self):
        """7: seed не импортирует GTD Core."""
        self._check_file(
            WORKSPACE / "business_core" / "seeds" / "seed_izhs_whatsapp_templates.py"
        )

    def test_7_knowledge_manager(self):
        """7: knowledge_manager не импортирует GTD Core."""
        self._check_file(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_7_run_seed_no_gtd_calls(self):
        """7: run_seed не вызывает GTD-функции."""
        seed = _fresh()
        import inspect
        src  = inspect.getsource(seed.run_seed)
        for forbidden in ["create_action", "create_project", "add_to_inbox",
                          "inbox_processor", "telegram_bot"]:
            self.assertNotIn(forbidden, src)


# ────────────────────────────────────────────────────────────
# 8. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_8_env_not_modified(self):
        """8: .env не изменён seed'ом."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        seed = _fresh()
        with patch(f"{SEED_MODULE}._sop_exists",  return_value=True), \
             patch(f"{SEED_MODULE}._msg_exists",  return_value=True):
            seed.dry_run()
        self.assertEqual(mtime_before, os.path.getmtime(env_path))

    def test_8_run_seed_no_env_writes(self):
        """8: run_seed не пишет в .env."""
        seed = _fresh()
        import inspect
        src  = inspect.getsource(seed.run_seed)
        for forbidden in ["dotenv_values", "set_key", "open('.env'", 'open(".env"']:
            self.assertNotIn(forbidden, src)

    def test_8_biz_id_biz_001(self):
        """8: BIZ_ID == BIZ-001."""
        seed = _fresh()
        self.assertEqual(seed.BIZ_ID, "BIZ-001")

    def test_8_msg_texts_no_promises(self):
        """8: ни один шаблон не содержит запрещённых обещаний."""
        seed      = _fresh()
        forbidden = ["точно узаконим", "100% получится", "гарантируем срок"]
        for msg in seed.MESSAGES:
            for phrase in forbidden:
                self.assertNotIn(phrase, msg["answer"].lower(),
                                 f"{msg['msg_id']} содержит '{phrase}'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
