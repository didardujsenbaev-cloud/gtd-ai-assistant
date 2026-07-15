"""
Tests for /milestones command and get_commercial_milestones_for_roadmap().

Checks 1–9 per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

RM_MOD = "business_core.roadmap_manager"
TH_MOD = "business_core.telegram_handlers"
RM_PATH = WORKSPACE / "business_core" / "roadmap_manager.py"
TH_PATH = WORKSPACE / "business_core" / "telegram_handlers.py"

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync"}

# Pre-computed milestones config to avoid calling _fresh_rm() inside
# test bodies that already hold a fresh th module reference.
_ALM_MILESTONES_CFG = [
    {"id": "CM-1", "title": "Анализ / проверка возможности оформления",
     "price": 150_000, "currency": "KZT", "stage_orders": list(range(1, 5)),
     "result": "Понятен путь оформления, риски и возможность запуска следующего этапа.",
     "important": "Этап 1 не гарантирует получение АПЗ."},
    {"id": "CM-2", "title": "Документы до АПЗ / проектно-разрешительный этап",
     "price": 500_000, "currency": "KZT", "stage_orders": list(range(5, 11)),
     "result": "Пакет подготовлен, подача выполнена, получен результат по АПЗ.",
     "important": "АПЗ зависит от госоргана."},
    {"id": "CM-3", "title": "Технический паспорт / акт ввода / регистрация",
     "price": 300_000, "currency": "KZT", "stage_orders": list(range(11, 14)),
     "result": "Объект оформлен и изменения зарегистрированы.",
     "important": "Финальный этап запускается после оплаты этапа 3."},
]

# ── фиктивные данные ──────────────────────────────────────────

FAKE_ROADMAP = {
    "roadmap_id": "RM-022",
    "biz_id":     "BIZ-001",
    "service_id": "SVC-IZH-001",
    "client_id":  "PRS-001",
    "title":      "Test roadmap",
    "status":     "active",
    "created":    "2026-01-01",
    "obj_id":     "OBJ-007",
    "case_type":  "legalization",
    "notes":      "",
    "progress":   "0",
}

FAKE_STAGES = [
    {"stage_id": f"STG-{i:03d}", "roadmap_id": "RM-022",
     "order": str(i), "name": f"Stage {i}", "status": "pending",
     "due_date": "", "notes": ""}
    for i in range(1, 14)
]

TEMPLATE_ID_ALM = "RMT-IZH-ALM-STANDARD-002"

FAKE_SVC_WITH_TEMPLATE = {
    "service_id":                   "SVC-IZH-001",
    "default_roadmap_template_id":  TEMPLATE_ID_ALM,
}


def _fresh_rm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module(RM_MOD)


def _fresh_th():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module(TH_MOD)


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


def _make_update(text: str):
    """Сделать фиктивный Update для telegram команды."""
    upd = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    return upd


def _make_context(args: list[str]):
    ctx = MagicMock()
    ctx.args = args
    return ctx


# ────────────────────────────────────────────────────────────
# 1. /milestones без roadmap_id показывает usage
# ────────────────────────────────────────────────────────────

class TestMilestonesUsage(unittest.TestCase):

    def _run_no_args(self, handler_mod):
        """Вызвать milestones_cmd без аргументов."""
        import asyncio
        replies = []

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        upd = _make_update("/milestones")
        ctx = _make_context([])
        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply", side_effect=fake_reply):
            asyncio.run(
                handler_mod.milestones_cmd(upd, ctx)
            )
        return replies

    def test_1_no_args_returns_usage(self):
        """1: /milestones без аргументов показывает usage."""
        th = _fresh_th()
        replies = self._run_no_args(th)
        self.assertEqual(len(replies), 1)
        self.assertIn("milestones", replies[0].lower())

    def test_1_no_args_message_contains_example(self):
        """1: usage содержит пример roadmap_id."""
        th = _fresh_th()
        replies = self._run_no_args(th)
        self.assertIn("roadmap_id", replies[0])

    def test_1_no_args_no_sheet_writes(self):
        """1: usage не пишет в Sheets."""
        th    = _fresh_th()
        calls = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            pass

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: calls.append((k, r))):
            asyncio.run(
                th.milestones_cmd(_make_update("/milestones"), _make_context([]))
            )
        self.assertEqual(calls, [])


# ────────────────────────────────────────────────────────────
# 2. /milestones roadmap_id=RM-022 находит roadmap
# ────────────────────────────────────────────────────────────

class TestMilestonesFindsRoadmap(unittest.TestCase):

    def test_2_calls_get_commercial_milestones(self):
        """2: команда вызывает get_commercial_milestones_for_roadmap."""
        th    = _fresh_th()
        calls = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            pass

        def fake_get(rm_id):
            calls.append(rm_id)
            return {
                "ok": True, "error": None,
                "roadmap": FAKE_ROADMAP,
                "template_id": TEMPLATE_ID_ALM,
                "milestones": [],
                "stages": [],
                "total_price": 0,
            }

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   side_effect=fake_get):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertEqual(calls, ["RM-022"])

    def test_2_roadmap_not_found_shows_error(self):
        """2: если roadmap не найден — показывает ошибку."""
        th      = _fresh_th()
        replies = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value={"ok": False, "error": "Roadmap RM-999 не найден",
                                 "roadmap": None, "template_id": "", "milestones": [],
                                 "stages": [], "total_price": 0}):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-999"),
                    _make_context(["roadmap_id=RM-999"]),
                )
            )
        self.assertGreaterEqual(len(replies), 1)
        self.assertIn("❌", replies[-1])

    def test_2_positional_arg_works(self):
        """2: /milestones RM-022 без ключа работает."""
        th    = _fresh_th()
        calls = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            pass

        def fake_get(rm_id):
            calls.append(rm_id)
            return {"ok": False, "error": "not found", "roadmap": None,
                    "template_id": "", "milestones": [], "stages": [], "total_price": 0}

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   side_effect=fake_get):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones RM-022"),
                    _make_context(["RM-022"]),
                )
            )
        self.assertEqual(calls, ["RM-022"])


# ────────────────────────────────────────────────────────────
# 3. Для RMT-IZH-ALM-STANDARD-002 показывает 3 milestones
# ────────────────────────────────────────────────────────────

class TestMilestonesMap(unittest.TestCase):

    def test_3_map_has_alm_standard_002(self):
        """3: COMMERCIAL_MILESTONES_MAP содержит RMT-IZH-ALM-STANDARD-002."""
        rm = _fresh_rm()
        self.assertIn("RMT-IZH-ALM-STANDARD-002", rm.COMMERCIAL_MILESTONES_MAP)

    def test_3_alm_standard_002_has_3_milestones(self):
        """3: RMT-IZH-ALM-STANDARD-002 имеет 3 коммерческих этапа."""
        rm = _fresh_rm()
        ms = rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"]
        self.assertEqual(len(ms), 3)

    def test_3_milestone_1_stages_1_to_4(self):
        """3: CM-1 включает этапы 1–4."""
        rm = _fresh_rm()
        cm1 = rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][0]
        self.assertEqual(cm1["stage_orders"], [1, 2, 3, 4])

    def test_3_milestone_2_stages_5_to_10(self):
        """3: CM-2 включает этапы 5–10."""
        rm = _fresh_rm()
        cm2 = rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][1]
        self.assertEqual(cm2["stage_orders"], [5, 6, 7, 8, 9, 10])

    def test_3_milestone_3_stages_11_to_13(self):
        """3: CM-3 включает этапы 11–13."""
        rm = _fresh_rm()
        cm3 = rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][2]
        self.assertEqual(cm3["stage_orders"], [11, 12, 13])

    def test_3_get_commercial_milestones_returns_3_for_alm_002(self):
        """3: get_commercial_milestones_for_roadmap возвращает 3 milestone."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["milestones"]), 3)

    def test_3_milestones_have_loaded_stages(self):
        """3: каждый milestone имеет loaded_stages и stage_range."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        for ms in data["milestones"]:
            self.assertIn("loaded_stages", ms)
            self.assertIn("stage_range",   ms)
            self.assertGreater(len(ms["stage_range"]), 0)

    def test_3_cm1_has_4_loaded_stages(self):
        """3: CM-1 загружает 4 этапа."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(len(data["milestones"][0]["loaded_stages"]), 4)

    def test_3_cm2_has_6_loaded_stages(self):
        """3: CM-2 загружает 6 этапов."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(len(data["milestones"][1]["loaded_stages"]), 6)

    def test_3_cm3_has_3_loaded_stages(self):
        """3: CM-3 загружает 3 этапа."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(len(data["milestones"][2]["loaded_stages"]), 3)

    def test_3_reply_contains_3_milestone_headers(self):
        """3: ответ Telegram содержит все 3 заголовка milestone."""
        th      = _fresh_th()
        replies = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        ms_data = {
            "ok": True, "error": None,
            "roadmap":     FAKE_ROADMAP,
            "template_id": TEMPLATE_ID_ALM,
            "milestones": [
                {**m, "loaded_stages": [],
                 "stage_range": f"{m['stage_orders'][0]}–{m['stage_orders'][-1]}"}
                for m in _ALM_MILESTONES_CFG
            ],
            "stages":      [],
            "total_price": 950_000,
        }

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value=ms_data):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertGreaterEqual(len(replies), 1)
        text = replies[-1]
        self.assertIn("1)", text)
        self.assertIn("2)", text)
        self.assertIn("3)", text)


# ────────────────────────────────────────────────────────────
# 4. Итоговая сумма = 950 000
# ────────────────────────────────────────────────────────────

class TestTotalPrice(unittest.TestCase):

    def test_4_total_is_950000(self):
        """4: сумма 3 milestone = 950 000 KZT."""
        rm = _fresh_rm()
        total = sum(
            cm["price"]
            for cm in rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"]
        )
        self.assertEqual(total, 950_000)

    def test_4_get_commercial_total_price(self):
        """4: get_commercial_milestones_for_roadmap возвращает total_price=950000."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=[]):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(data["total_price"], 950_000)

    def test_4_cm1_price_150k(self):
        """4: CM-1 стоит 150 000 тг."""
        rm = _fresh_rm()
        self.assertEqual(
            rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][0]["price"],
            150_000,
        )

    def test_4_cm2_price_500k(self):
        """4: CM-2 стоит 500 000 тг."""
        rm = _fresh_rm()
        self.assertEqual(
            rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][1]["price"],
            500_000,
        )

    def test_4_cm3_price_300k(self):
        """4: CM-3 стоит 300 000 тг."""
        rm = _fresh_rm()
        self.assertEqual(
            rm.COMMERCIAL_MILESTONES_MAP["RMT-IZH-ALM-STANDARD-002"][2]["price"],
            300_000,
        )

    def test_4_reply_contains_950000(self):
        """4: ответ Telegram содержит итоговую сумму 950 000."""
        th      = _fresh_th()
        replies = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        ms_data = {
            "ok": True, "error": None,
            "roadmap":     FAKE_ROADMAP,
            "template_id": TEMPLATE_ID_ALM,
            "milestones": [
                {**m, "loaded_stages": [],
                 "stage_range": f"{m['stage_orders'][0]}–{m['stage_orders'][-1]}"}
                for m in _ALM_MILESTONES_CFG
            ],
            "stages":      [],
            "total_price": 950_000,
        }

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value=ms_data):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertIn("950", replies[-1])


# ────────────────────────────────────────────────────────────
# 5. Команда не пишет в Sheets
# ────────────────────────────────────────────────────────────

class TestNoWrites(unittest.TestCase):

    def _run_cmd(self, th, rm_id="RM-022"):
        import asyncio
        writes = []

        async def fake_reply(update, text, parse_mode=None):
            pass

        data = {
            "ok": True, "error": None,
            "roadmap": FAKE_ROADMAP,
            "template_id": TEMPLATE_ID_ALM,
            "milestones": [],
            "stages": [],
            "total_price": 0,
        }

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value=data), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            asyncio.run(
                th.milestones_cmd(
                    _make_update(f"/milestones roadmap_id={rm_id}"),
                    _make_context([f"roadmap_id={rm_id}"]),
                )
            )
        return writes

    def test_5_no_append_calls(self):
        """5: milestones_cmd не вызывает append_business_row."""
        th = _fresh_th()
        writes = self._run_cmd(th)
        self.assertEqual(writes, [])

    def test_5_helper_does_not_write(self):
        """5: get_commercial_milestones_for_roadmap не пишет в Sheets."""
        rm     = _fresh_rm()
        writes = []
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=[]), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: writes.append((k, r))):
            rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(writes, [])


# ────────────────────────────────────────────────────────────
# 6. Команда не создает новые stages
# ────────────────────────────────────────────────────────────

class TestNoNewStages(unittest.TestCase):

    def test_6_no_create_stages_calls(self):
        """6: milestones_cmd не вызывает create_stages_from_template_record."""
        th    = _fresh_th()
        calls = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            pass

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value={"ok": True, "error": None, "roadmap": FAKE_ROADMAP,
                                 "template_id": "", "milestones": [], "stages": [], "total_price": 0}), \
             patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                   side_effect=lambda *a, **kw: calls.append((a, kw))):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertEqual(calls, [])

    def test_6_helper_does_not_write_stages(self):
        """6: get_commercial_milestones_for_roadmap не пишет в roadmap_stages."""
        rm     = _fresh_rm()
        writes = []

        def track(sheet_key, row):
            if "stage" in sheet_key:
                writes.append((sheet_key, row))

        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=TEMPLATE_ID_ALM), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=[]), \
             patch("business_core.sheets.append_business_row", side_effect=track):
            rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(writes, [])


# ────────────────────────────────────────────────────────────
# 7. Если template_id не поддерживается — понятная ошибка
# ────────────────────────────────────────────────────────────

class TestUnsupportedTemplate(unittest.TestCase):

    def test_7_empty_template_returns_no_milestones(self):
        """7: пустой template_id → milestones = []."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value=""), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=[]):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertTrue(data["ok"])
        self.assertEqual(data["milestones"], [])

    def test_7_unknown_template_returns_no_milestones(self):
        """7: неизвестный template_id → milestones = []."""
        rm = _fresh_rm()
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value="RMT-UNKNOWN-999"), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=[]):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")
        self.assertEqual(data["milestones"], [])

    def test_7_no_milestones_shows_info_message(self):
        """7: если milestones = [] команда показывает информативное сообщение."""
        th      = _fresh_th()
        replies = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value={"ok": True, "error": None, "roadmap": FAKE_ROADMAP,
                                 "template_id": "RMT-UNKNOWN-999",
                                 "milestones": [], "stages": [], "total_price": 0}):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertGreaterEqual(len(replies), 1)
        self.assertIn("SOP-IZH-COMMERCIAL-MILESTONES-001", replies[-1])

    def test_7_no_template_id_shows_info_message(self):
        """7: если template_id не определён — понятное сообщение."""
        th      = _fresh_th()
        replies = []
        import asyncio

        async def fake_reply(update, text, parse_mode=None):
            replies.append(text)

        with patch(f"{TH_MOD}._is_bc_enabled", return_value=True), \
             patch(f"{TH_MOD}._reply",          side_effect=fake_reply), \
             patch("business_core.roadmap_manager.get_commercial_milestones_for_roadmap",
                   return_value={"ok": True, "error": None, "roadmap": FAKE_ROADMAP,
                                 "template_id": "",
                                 "milestones": [], "stages": [], "total_price": 0}):
            asyncio.run(
                th.milestones_cmd(
                    _make_update("/milestones roadmap_id=RM-022"),
                    _make_context(["roadmap_id=RM-022"]),
                )
            )
        self.assertIn("не настроены", replies[-1])

    def test_7_resolve_template_from_notes(self):
        """7: _resolve_template_id читает template_id из notes roadmap."""
        rm = _fresh_rm()
        roadmap_with_notes = {
            **FAKE_ROADMAP,
            "notes": "template_id=RMT-IZH-ALM-STANDARD-002 some other text",
        }
        tid = rm._resolve_template_id(roadmap_with_notes)
        self.assertEqual(tid, "RMT-IZH-ALM-STANDARD-002")

    def test_7_resolve_template_from_service(self):
        """7: _resolve_template_id берёт template из default_roadmap_template_id услуги."""
        rm = _fresh_rm()
        with patch("business_core.service_manager.find_service_by_id",
                   return_value=FAKE_SVC_WITH_TEMPLATE):
            tid = rm._resolve_template_id(FAKE_ROADMAP)
        self.assertEqual(tid, TEMPLATE_ID_ALM)


# ────────────────────────────────────────────────────────────
# 8. GTD Core файлы не трогаются
# ────────────────────────────────────────────────────────────

class TestNoGTDImports(unittest.TestCase):

    def test_8_roadmap_manager_no_gtd_imports(self):
        """8: roadmap_manager не импортирует GTD Core файлы."""
        mods = _imports(RM_PATH)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"Запрещённый импорт в roadmap_manager: {mod}")

    def test_8_telegram_handlers_no_gtd_core(self):
        """8: telegram_handlers не импортирует inbox_processor напрямую."""
        mods = _imports(TH_PATH)
        self.assertNotIn("inbox_processor", mods)

    def test_8_milestones_cmd_in_handlers(self):
        """8: milestones_cmd существует в telegram_handlers."""
        th = _fresh_th()
        self.assertTrue(hasattr(th, "milestones_cmd"))

    def test_8_commercial_milestones_map_in_roadmap_manager(self):
        """8: COMMERCIAL_MILESTONES_MAP существует в roadmap_manager."""
        rm = _fresh_rm()
        self.assertTrue(hasattr(rm, "COMMERCIAL_MILESTONES_MAP"))

    def test_8_get_commercial_milestones_in_roadmap_manager(self):
        """8: get_commercial_milestones_for_roadmap существует."""
        rm = _fresh_rm()
        self.assertTrue(hasattr(rm, "get_commercial_milestones_for_roadmap"))

    def test_8_resolve_template_in_roadmap_manager(self):
        """8: _resolve_template_id существует."""
        rm = _fresh_rm()
        self.assertTrue(hasattr(rm, "_resolve_template_id"))


# ────────────────────────────────────────────────────────────
# 9. .env не меняется
# ────────────────────────────────────────────────────────────

class TestEnvUnchanged(unittest.TestCase):

    def test_9_roadmap_manager_no_env_write(self):
        """9: roadmap_manager.py не содержит open(.env, w)."""
        src = RM_PATH.read_text(encoding="utf-8")
        self.assertNotIn('open(".env", "w")', src)
        self.assertNotIn("open('.env', 'w')", src)

    def test_9_telegram_handlers_no_env_write(self):
        """9: telegram_handlers.py не содержит open(.env, w)."""
        src = TH_PATH.read_text(encoding="utf-8")
        self.assertNotIn('open(".env", "w")', src)

    def test_9_roadmap_manager_compiles(self):
        """9: roadmap_manager.py компилируется без ошибок."""
        import py_compile
        py_compile.compile(str(RM_PATH), doraise=True)

    def test_9_telegram_handlers_compiles(self):
        """9: telegram_handlers.py компилируется без ошибок."""
        import py_compile
        py_compile.compile(str(TH_PATH), doraise=True)

    def test_9_milestones_registered_in_handlers(self):
        """9: /milestones зарегистрирован в register_business_handlers."""
        src = TH_PATH.read_text(encoding="utf-8")
        self.assertIn('"milestones"', src)
        self.assertIn("milestones_cmd", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
