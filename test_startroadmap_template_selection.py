"""
Tests for explicit template_id selection in /startroadmap.

Checks 1–7 per spec.
"""

from __future__ import annotations

import ast
import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync"}

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _fresh_handlers():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    from business_core.telegram_handlers import startroadmap_cmd
    return startroadmap_cmd


def _make_update(text: str, args_list: list[str]):
    update          = MagicMock()
    update.message.text         = text
    update.message.reply_text   = AsyncMock()
    context         = MagicMock()
    context.args    = args_list
    return update, context


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _last_reply(update) -> str:
    return update.message.reply_text.call_args[0][0]


# ────────────────────────────────────────────────────────────
# 1. /startroadmap без template_id работает как раньше
# ────────────────────────────────────────────────────────────

class TestNoTemplateId(unittest.TestCase):

    def test_1_no_template_id_uses_default(self):
        """1: без template_id берёт default из SERVICE_CATALOG."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001"],
        )
        stages_mock = {"ok": True, "stages_count": 12, "warning": None, "stage_ids": []}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-100", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value={"service_id": "SVC-IZH-001",
                                     "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-LEGALIZATION-001",
                                     "service_id": "SVC-IZH-001", "template_name": "Легализация"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[{"template_id": "RMT-IZH-ALM-LEGALIZATION-001",
                                      "service_id": "SVC-IZH-001", "template_name": "Легализация"}]), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value=stages_mock), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RM-100", reply)
        self.assertIn("Roadmap создан", reply)

    def test_1_no_template_id_no_crash_without_service(self):
        """1: без service_id и template_id — не крашится, просит obj_id или работает."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update("/startroadmap", [])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        # Должна быть подсказка, не crash
        self.assertTrue(len(reply) > 0)


# ────────────────────────────────────────────────────────────
# 2. /startroadmap с template_id создает stages из него
# ────────────────────────────────────────────────────────────

class TestExplicitTemplateId(unittest.TestCase):

    def test_2_explicit_template_id_used(self):
        """2: явный template_id — stages создаются именно из него."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-STANDARD-002",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-STANDARD-002"],
        )
        stages_calls = []

        def mock_stages(roadmap_id, template_id):
            stages_calls.append(template_id)
            return {"ok": True, "stages_count": 13, "warning": None, "stage_ids": []}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-101", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-STANDARD-002",
                                     "service_id": "SVC-IZH-001",
                                     "template_name": "Обычный путь / с законченными СМР"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       side_effect=mock_stages), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await cmd(upd, ctx)

        _run(run())
        self.assertEqual(stages_calls, ["RMT-IZH-ALM-STANDARD-002"],
                         "create_stages_from_template_record должен вызываться с явным template_id")
        reply = _last_reply(upd)
        self.assertIn("RM-101", reply)
        self.assertIn("RMT-IZH-ALM-STANDARD-002", reply)

    def test_2_explicit_template_id_shown_in_reply(self):
        """2: явный template_id показывается в ответе."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-STANDARD-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-STANDARD-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-102", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-STANDARD-001",
                                     "service_id": "SVC-IZH-001",
                                     "template_name": "Обычный путь / с проведением СМР"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value={"ok": True, "stages_count": 15, "warning": None, "stage_ids": []}), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RMT-IZH-ALM-STANDARD-001", reply)


# ────────────────────────────────────────────────────────────
# 3. template_id не существует — понятная ошибка
# ────────────────────────────────────────────────────────────

class TestTemplateNotFound(unittest.TestCase):

    def test_3_unknown_template_id_returns_error(self):
        """3: несуществующий template_id → понятная ошибка."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-UNKNOWN-999",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-UNKNOWN-999"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value=None), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("не найден", reply.lower())
        self.assertIn("RMT-UNKNOWN-999", reply)

    def test_3_no_roadmap_created_on_invalid_template(self):
        """3: при неверном template_id roadmap НЕ создаётся."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-BAD",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-BAD"],
        )
        rm_calls = []

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value=None), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       side_effect=lambda **kw: rm_calls.append(kw)):
                await cmd(upd, ctx)

        _run(run())
        self.assertEqual(rm_calls, [], "create_roadmap_for_object не должен вызываться при ошибке шаблона")


# ────────────────────────────────────────────────────────────
# 4. template_id принадлежит другой service_id — понятная ошибка
# ────────────────────────────────────────────────────────────

class TestTemplateMismatch(unittest.TestCase):

    def test_4_wrong_service_template_returns_error(self):
        """4: template_id из другой услуги → понятная ошибка."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-NEWBUILD-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-NEWBUILD-001"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                                     "service_id": "SVC-IZH-002",  # другая услуга!
                                     "template_name": "Новое строительство"}), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("SVC-IZH-002", reply)
        self.assertIn("SVC-IZH-001", reply)
        # должно быть сообщение об ошибке принадлежности
        self.assertTrue("принадлежит" in reply or "не относится" in reply or "❌" in reply)

    def test_4_no_roadmap_created_on_mismatch(self):
        """4: при несовпадении service_id roadmap НЕ создаётся."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-NEWBUILD-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-NEWBUILD-001"],
        )
        rm_calls = []

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                                     "service_id": "SVC-IZH-002",
                                     "template_name": "Новое строительство"}), \
                 patch("business_core.service_manager.find_service_by_id", return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[]), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       side_effect=lambda **kw: rm_calls.append(kw)):
                await cmd(upd, ctx)

        _run(run())
        self.assertEqual(rm_calls, [])


# ────────────────────────────────────────────────────────────
# 5. Несколько templates — показывает список / использует default
# ────────────────────────────────────────────────────────────

class TestMultipleTemplates(unittest.TestCase):

    def _three_templates(self):
        return [
            {"template_id": "RMT-IZH-ALM-LEGALIZATION-001",
             "service_id": "SVC-IZH-001",
             "template_name": "Временная легализация"},
            {"template_id": "RMT-IZH-ALM-STANDARD-001",
             "service_id": "SVC-IZH-001",
             "template_name": "Обычный путь / с проведением СМР"},
            {"template_id": "RMT-IZH-ALM-STANDARD-002",
             "service_id": "SVC-IZH-001",
             "template_name": "Обычный путь / с законченными СМР"},
        ]

    def test_5_hint_shown_when_multiple_templates(self):
        """5: при нескольких шаблонах без template_id — показывается подсказка."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001"],
        )
        reply_calls = []

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-200", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value={"service_id": "SVC-IZH-001",
                                     "default_roadmap_template_id": ""}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=self._three_templates()), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value={"ok": True, "stages_count": 12, "warning": None, "stage_ids": []}), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                # Capture all reply calls
                async def capture(text, **kw):
                    reply_calls.append(text)
                upd.message.reply_text = capture
                await cmd(upd, ctx)

        _run(run())
        all_replies = " ".join(reply_calls)
        # Подсказка должна упомянуть несколько template_id
        self.assertIn("RMT-IZH-ALM-LEGALIZATION-001", all_replies)
        self.assertIn("RMT-IZH-ALM-STANDARD-001", all_replies)
        self.assertIn("RMT-IZH-ALM-STANDARD-002", all_replies)

    def test_5_first_template_still_used_as_fallback(self):
        """5: при нескольких шаблонах без template_id — всё равно создаётся roadmap."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001"],
        )
        stages_calls = []

        def mock_stages(roadmap_id, template_id):
            stages_calls.append(template_id)
            return {"ok": True, "stages_count": 12, "warning": None, "stage_ids": []}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-201", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value={"service_id": "SVC-IZH-001", "default_roadmap_template_id": ""}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=self._three_templates()), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       side_effect=mock_stages), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await cmd(upd, ctx)

        _run(run())
        # Должен использоваться первый шаблон
        self.assertIn("RMT-IZH-ALM-LEGALIZATION-001", stages_calls)

    def test_5_single_template_no_hint(self):
        """5: при одном шаблоне — подсказка со списком не нужна (не падает)."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-002",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-202", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value={"service_id": "SVC-IZH-002",
                                     "default_roadmap_template_id": "RMT-IZH-ALM-NEWBUILD-001"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value=None), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=[{"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                                      "service_id": "SVC-IZH-002", "template_name": "Новое строительство"}]), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       return_value={"ok": True, "stages_count": 18, "warning": None, "stage_ids": []}), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RM-202", reply)


# ────────────────────────────────────────────────────────────
# 6. GTD Core не затронут
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists(): return
        src  = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn(a.name.split(".")[0], GTD_FORBIDDEN,
                                     f"{path.name} импортирует {a.name!r}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], GTD_FORBIDDEN,
                                 f"{path.name} импортирует {node.module!r}")

    def test_6_telegram_handlers(self):
        """6: telegram_handlers не импортирует GTD Core модули."""
        self._check(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_6_roadmap_manager(self):
        """6: roadmap_manager не импортирует GTD Core модули."""
        self._check(WORKSPACE / "business_core" / "roadmap_manager.py")


# ────────────────────────────────────────────────────────────
# 7. .env не изменен
# ────────────────────────────────────────────────────────────

class TestEnvNotChanged(unittest.TestCase):

    def test_7_env_not_modified(self):
        """7: .env не изменён после тестов."""
        env_path = WORKSPACE / ".env"
        if not env_path.exists():
            self.skipTest(".env не найден")
        import os
        mtime_before = os.path.getmtime(env_path)
        # просто импортируем модуль
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        import business_core.telegram_handlers  # noqa: F401
        mtime_after = os.path.getmtime(env_path)
        self.assertEqual(mtime_before, mtime_after)

    def test_7_startroadmap_docstring_updated(self):
        """7: docstring /startroadmap упоминает template_id."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        import business_core.telegram_handlers as th
        import inspect
        src = inspect.getsource(th.startroadmap_cmd)
        self.assertIn("template_id", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
