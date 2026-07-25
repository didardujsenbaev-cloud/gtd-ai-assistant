"""
Tests for template_id selection in /startroadmap.

Phase 33C (ADR-016 §11/§15): Template resolution (explicit -> Service
default -> linked templates) and validation now happen entirely INSIDE
business_builder.create_roadmap_for_object() — telegram_handlers.
startroadmap_cmd() no longer pre-resolves or pre-validates a template
itself (that used to duplicate the same lookup/validation logic here
and in the orchestration layer; ADR-016 explicitly forbids duplicating
validation in telegram_handlers.py). This file was rewritten to match:
tests that exercise the RESOLUTION algorithm itself now let
create_roadmap_for_object() run for real (with Business/Client/Object/
Service dependencies mocked, matching production shapes), rather than
mocking create_roadmap_for_object() as a whole and asserting on
handler-local pre-resolution that no longer exists.
"""

from __future__ import annotations

import ast
import sys
import asyncio
import unittest
from contextlib import ExitStack
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


def _valid_cross_domain_patches() -> list:
    """The full set of patches needed to let create_roadmap_for_object()
    run for real up through Service validation — Business/Client/Object
    all valid, matching (BIZ-001, PRS-001, OBJ-001).

    Two separate find_object_by_id mocks are both needed: startroadmap_cmd
    itself calls business_builder.find_object_by_id() (to read biz_id/
    client_id before calling create_roadmap_for_object()), while
    create_roadmap_for_object() calls object_manager.find_object_by_id()
    internally for its own Object validation — these are different
    functions with different return shapes. Use with an ExitStack:

        with ExitStack() as stack:
            for p in _valid_cross_domain_patches():
                stack.enter_context(p)
            ...
    """
    return [
        patch("business_core.business_builder.find_object_by_id",
              return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}),
        patch("business_core.sheets.find_row_by_id", return_value=("2", {"ID": "BIZ-001"})),
        patch("business_core.person_manager.find_person_by_id",
              return_value={"person_id": "PRS-001", "status": "active",
                            "person_type": "клиент", "biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-001"}),
        patch("business_core.person_manager.is_person_archived", return_value=False),
        patch("business_core.person_manager.is_client_person", return_value=True),
        patch("business_core.person_manager.has_person_business_link", return_value=True),
        patch("business_core.object_manager.find_object_by_id",
              return_value={"object_id": "OBJ-001", "status": "new",
                            "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": ""}),
    ]


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

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={"ok": True, "roadmap_id": "RM-100", "error": None}), \
                 patch("business_core.business_builder.update_object_roadmap_id"):
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
# 2. /startroadmap с template_id — передан насквозь, показан в ответе
# ────────────────────────────────────────────────────────────

class TestExplicitTemplateId(unittest.TestCase):

    def test_2_explicit_template_id_passed_through(self):
        """2: явный template_id передаётся в create_roadmap_for_object
        как есть — resolution/validation теперь целиком внутри неё."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-STANDARD-002",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-STANDARD-002"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       return_value={
                           "ok": True, "roadmap_id": "RM-101", "error": None,
                           "core_created": True, "stages_created": True,
                           "stages_count": 13, "stage_ids": [], "used_template": True,
                           "relation_copy_errors": (), "relation_copy_created_count": 0,
                           "partial_success": False, "partial_failure": False, "warnings": (),
                           "template_id": "RMT-IZH-ALM-STANDARD-002",
                           "selected_template_id": "RMT-IZH-ALM-STANDARD-002",
                       }) as mock_create_rm, \
                 patch("business_core.business_builder.update_object_roadmap_id"):
                await cmd(upd, ctx)
                self.assertEqual(mock_create_rm.call_args.kwargs["template_id"], "RMT-IZH-ALM-STANDARD-002",
                                 "create_roadmap_for_object должен вызываться с явным template_id")

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RM-101", reply)
        self.assertIn("RMT-IZH-ALM-STANDARD-002", reply)

    def test_2_explicit_template_id_shown_in_reply(self):
        """2: явный template_id показывается в ответе (через
        rm_result['selected_template_id'])."""
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
                       return_value={
                           "ok": True, "roadmap_id": "RM-102", "error": None,
                           "core_created": True, "stages_created": True,
                           "stages_count": 15, "stage_ids": [], "used_template": True,
                           "relation_copy_errors": (), "relation_copy_created_count": 0,
                           "partial_success": False, "partial_failure": False, "warnings": (),
                           "template_id": "RMT-IZH-ALM-STANDARD-001",
                           "selected_template_id": "RMT-IZH-ALM-STANDARD-001",
                       }), \
                 patch("business_core.business_builder.update_object_roadmap_id"):
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RMT-IZH-ALM-STANDARD-001", reply)


# ────────────────────────────────────────────────────────────
# 3. template_id не существует — понятная ошибка (внутри
#    create_roadmap_for_object, реальный вызов)
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
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-001", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_template_by_id", return_value=None,
                ))
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("не найден", reply.lower())
        self.assertIn("RMT-UNKNOWN-999", reply)

    def test_3_no_roadmap_created_on_invalid_template(self):
        """3: при неверном template_id roadmap НЕ создаётся (не доходит
        до roadmap_manager.create_roadmap_record)."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-BAD",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-BAD"],
        )

        async def run():
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-001", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_template_by_id", return_value=None,
                ))
                mock_create_record = stack.enter_context(
                    patch("business_core.roadmap_manager.create_roadmap_record")
                )
                await cmd(upd, ctx)
                mock_create_record.assert_not_called()

        _run(run())


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
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-001", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_template_by_id",
                    return_value={"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                                  "service_id": "SVC-IZH-002",  # другая услуга!
                                  "template_name": "Новое строительство", "status": "active"},
                ))
                await cmd(upd, ctx)

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("SVC-IZH-002", reply)
        self.assertIn("SVC-IZH-001", reply)
        self.assertTrue("принадлежит" in reply or "не относится" in reply or "❌" in reply)

    def test_4_no_roadmap_created_on_mismatch(self):
        """4: при несовпадении service_id roadmap НЕ создаётся."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-NEWBUILD-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-NEWBUILD-001"],
        )

        async def run():
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-001", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_template_by_id",
                    return_value={"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                                  "service_id": "SVC-IZH-002",
                                  "template_name": "Новое строительство", "status": "active"},
                ))
                mock_create_record = stack.enter_context(
                    patch("business_core.roadmap_manager.create_roadmap_record")
                )
                await cmd(upd, ctx)
                mock_create_record.assert_not_called()

        _run(run())


# ────────────────────────────────────────────────────────────
# 5. Несколько templates — требуется явный выбор (ADR-016 §8/§11:
#    больше НЕ выбирается первый молча)
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
        """5: при нескольких шаблонах без template_id — показывается
        подсказка со списком всех кандидатов, roadmap НЕ создаётся
        (ADR-016 §8.C: MULTIPLE_TEMPLATES_REQUIRE_SELECTION)."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001"],
        )

        async def run():
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-001", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                    return_value=self._three_templates(),
                ))
                mock_create_record = stack.enter_context(
                    patch("business_core.roadmap_manager.create_roadmap_record")
                )
                await cmd(upd, ctx)
                mock_create_record.assert_not_called()

        _run(run())
        reply = _last_reply(upd)
        self.assertIn("RMT-IZH-ALM-LEGALIZATION-001", reply)
        self.assertIn("RMT-IZH-ALM-STANDARD-001", reply)
        self.assertIn("RMT-IZH-ALM-STANDARD-002", reply)

    def test_5_single_template_no_hint(self):
        """5: при одном шаблоне — автоматически выбирается и валидируется,
        подсказка со списком не нужна."""
        cmd = _fresh_handlers()
        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-002",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-002"],
        )

        single_template = {"template_id": "RMT-IZH-ALM-NEWBUILD-001",
                            "service_id": "SVC-IZH-002", "template_name": "Новое строительство",
                            "status": "active"}

        async def run():
            with ExitStack() as stack:
                stack.enter_context(patch("business_core.telegram_handlers._is_bc_enabled", return_value=True))
                for p in _valid_cross_domain_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.service_manager.find_service_by_id",
                    return_value={"service_id": "SVC-IZH-002", "status": "active",
                                  "biz_id": "BIZ-001", "object_type": "", "default_roadmap_template_id": ""},
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                    return_value=[single_template],
                ))
                stack.enter_context(patch(
                    "business_core.roadmap_template_manager.find_roadmap_template_by_id",
                    return_value=single_template,
                ))
                stack.enter_context(patch("business_core.roadmap_manager.find_open_roadmaps_for_object", return_value=[]))
                stack.enter_context(patch(
                    "business_core.roadmap_manager.create_roadmap_record",
                    return_value={"ok": True, "roadmap_id": "RM-202", "roadmap": {}, "error": None},
                ))
                stack.enter_context(patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]))
                stack.enter_context(patch("business_core.business_builder.update_object_roadmap_id"))
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
