"""
Phase 33D: caller-facing UX tests for
business_core.telegram_handlers.startroadmap_cmd().

Strictly against a mocked business_core.business_builder.
create_roadmap_for_object() — telegram_handlers.py itself must never
reach any cross-domain validation primitive (Business/Client/Object/
Service/Object Type/Template) directly (ADR-016 §1; enforced
structurally by test_roadmap_architecture_guards.py's
TestTelegramHandlersDoesNotDuplicateCrossDomainValidation). This file
exercises only the translation from create_roadmap_for_object()'s
structured result into the Telegram message and log line — no live
network calls, no production data touched.
"""

from __future__ import annotations

import sys
import unittest
import logging
from unittest.mock import patch, MagicMock, AsyncMock


def _fresh_handlers():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import startroadmap_cmd
    return startroadmap_cmd


def _make_update(text: str, args: list):
    update = MagicMock()
    context = MagicMock()
    context.args = args
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 123
    return update, context


def _last_reply(update) -> str:
    return update.message.reply_text.call_args[0][0]


DEFAULT_OBJ = {"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}


async def _invoke(cmd, rm_result: dict, extra_args: str = "", obj_ref_result=None):
    update, context = _make_update(
        f"/startroadmap obj_id=OBJ-001 service_id=SVC-001{extra_args}",
        ["obj_id=OBJ-001", "service_id=SVC-001"] + (extra_args.split() if extra_args else []),
    )
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
         patch("business_core.business_builder.find_object_by_id", return_value=DEFAULT_OBJ), \
         patch("business_core.business_builder.create_roadmap_for_object", return_value=rm_result), \
         patch("business_core.business_builder.update_object_roadmap_id",
               return_value=obj_ref_result if obj_ref_result is not None else {"ok": True, "updated": True, "error": None}):
        await cmd(update, context)
    return _last_reply(update)


def _ok_result(**overrides) -> dict:
    base = {
        "ok": True, "roadmap_id": "RM-100", "error": None, "error_code": "",
        "roadmap_created": True, "roadmap_reused": False,
        "stages_count": 3, "stages_reused": False, "existing_stage_count": 0,
        "used_template": True, "template_id": "RMT-001", "selected_template_id": "RMT-001",
        "template_warning": None, "warnings": (), "relation_copy_errors": (),
        "conflicting_roadmap_ids": [], "candidate_template_ids": [],
        "type_compatibility_warning": None, "client_type_validation": "deferred",
        "partial_failure": False,
    }
    base.update(overrides)
    return base


def _fail_result(error_code: str, error: str, **overrides) -> dict:
    base = {
        "ok": False, "roadmap_id": "", "error": error, "error_code": error_code,
        "roadmap_created": False, "roadmap_reused": False,
        "stages_count": 0, "warnings": (), "conflicting_roadmap_ids": [],
        "candidate_template_ids": [], "type_compatibility_warning": None,
        "partial_failure": False,
    }
    base.update(overrides)
    return base


class _AsyncTestCase(unittest.TestCase):
    def run_async(self, coro):
        import asyncio
        return asyncio.run(coro)


class TestRoadmapCreatedMessage(_AsyncTestCase):
    def test_roadmap_created_message(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(
            roadmap_created=True, roadmap_reused=False, stages_count=5,
        )))
        self.assertIn("Roadmap создан", reply)
        self.assertIn("RM-100", reply)
        self.assertIn("OBJ-001", reply)
        self.assertIn("SVC-001", reply)
        self.assertIn("RMT-001", reply)
        self.assertIn("Этапов создано: 5", reply)


class TestRoadmapReusedMessage(_AsyncTestCase):
    def test_roadmap_reused_message(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(
            roadmap_created=False, roadmap_reused=True, stages_count=0,
            stages_reused=True, existing_stage_count=2,
        )))
        self.assertIn("существующий Roadmap", reply)
        self.assertIn("Новый Roadmap не создан", reply)
        self.assertIn("RM-100", reply)
        self.assertNotIn("✅ *Roadmap создан*", reply)

    def test_created_and_reused_messages_are_distinct(self):
        cmd = _fresh_handlers()
        created = self.run_async(_invoke(cmd, _ok_result(roadmap_created=True, roadmap_reused=False)))
        reused = self.run_async(_invoke(cmd, _ok_result(roadmap_created=False, roadmap_reused=True)))
        self.assertNotEqual(created, reused)
        self.assertIn("Roadmap создан", created)
        self.assertNotIn("Roadmap создан", reused)


class TestTypeMismatchWarning(_AsyncTestCase):
    def test_mismatch_warning_displayed_but_success_preserved(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(
            type_compatibility_warning={
                "status": "mismatch", "object_type": "жилой дом", "service_object_type": "private_house_izhs",
            },
        )))
        self.assertIn("Roadmap создан", reply)
        self.assertIn("тип объекта и тип услуги отличаются", reply)
        self.assertIn("жилой дом", reply)
        self.assertIn("private_house_izhs", reply)

    def test_unavailable_type_comparison_uses_softer_wording(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(
            type_compatibility_warning={"status": "unavailable", "object_type": "", "service_object_type": ""},
        )))
        self.assertIn("Roadmap создан", reply)
        self.assertIn("Не удалось проверить совместимость", reply)

    def test_no_type_warning_when_none(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(type_compatibility_warning=None)))
        self.assertNotIn("совместимость", reply)


class TestErrorCodeMapping(_AsyncTestCase):
    def test_missing_business(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("BUSINESS_NOT_FOUND", "Business BIZ-001 не найден")))
        self.assertIn("не найден", reply)
        self.assertNotIn("Traceback", reply)

    def test_archived_client(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("CLIENT_ARCHIVED", "Клиент PRS-001 архивирован — Roadmap не создан")))
        self.assertIn("архивирован", reply)

    def test_non_client_role(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("CLIENT_ROLE_REQUIRED", "Клиент PRS-001 не имеет роли клиента")))
        self.assertIn("роли", reply)

    def test_missing_client_business_link(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("CLIENT_NOT_LINKED_TO_BUSINESS", "Клиент PRS-001 не привязан к бизнесу BIZ-001")))
        self.assertIn("не привязан", reply)

    def test_object_business_mismatch(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("OBJECT_BUSINESS_MISMATCH", "Object OBJ-001 принадлежит бизнесу 'BIZ-999', а не 'BIZ-001'")))
        self.assertIn("BIZ-999", reply)

    def test_object_client_mismatch(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("OBJECT_CLIENT_MISMATCH", "Object OBJ-001 привязан к клиенту 'PRS-999', а не 'PRS-001'")))
        self.assertIn("PRS-999", reply)

    def test_inactive_service(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("SERVICE_INACTIVE", "Service SVC-001 имеет статус 'inactive'")))
        self.assertIn("inactive", reply)

    def test_service_business_mismatch(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("SERVICE_BUSINESS_MISMATCH", "Service SVC-001 принадлежит бизнесу 'BIZ-999', а не 'BIZ-001'")))
        self.assertIn("BIZ-999", reply)

    def test_stale_template(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("TEMPLATE_NOT_FOUND", "Шаблон RMT-GONE (default для SVC-001) не найден в ROADMAP_TEMPLATE_REGISTRY")))
        self.assertIn("RMT-GONE", reply)

    def test_template_service_mismatch(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result("TEMPLATE_SERVICE_MISMATCH", "Шаблон RMT-001 принадлежит услуге SVC-999, а не SVC-001")))
        self.assertIn("SVC-999", reply)

    def test_unknown_code_safe_fallback(self):
        cmd = _fresh_handlers()
        with self.assertLogs("business_core.telegram_handlers", level="WARNING") as cm:
            reply = self.run_async(_invoke(cmd, _fail_result("SOME_FUTURE_CODE_NOT_YET_MAPPED", "internal detail that should not leak")))
        self.assertNotIn("internal detail that should not leak", reply)
        self.assertNotIn("Traceback", reply)
        self.assertTrue(any("SOME_FUTURE_CODE_NOT_YET_MAPPED" in msg for msg in cm.output))


class TestMultipleTemplatesUX(_AsyncTestCase):
    def test_candidate_list_shown_never_auto_selected(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result(
            "MULTIPLE_TEMPLATES_REQUIRE_SELECTION",
            "Для услуги SVC-001 найдено 2 шаблонов — требуется явный выбор",
            candidate_template_ids=["RMT-A", "RMT-B"],
        )))
        self.assertIn("RMT-A", reply)
        self.assertIn("RMT-B", reply)
        self.assertIn("template_id=", reply)
        # Never phrased as if one were already chosen.
        self.assertNotIn("Roadmap создан", reply)


class TestMultipleOpenRoadmapsUX(_AsyncTestCase):
    def test_all_conflicting_ids_shown(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result(
            "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR",
            "Найдено 2 открытых Roadmap для (Object ID='OBJ-001', Service ID='SVC-001'): ['RM-A', 'RM-B']",
            conflicting_roadmap_ids=["RM-A", "RM-B"],
        )))
        self.assertIn("RM-A", reply)
        self.assertIn("RM-B", reply)
        self.assertIn("не создан", reply)
        self.assertNotIn("Roadmap создан", reply)


class TestPartialFailureUX(_AsyncTestCase):
    def test_stage_materialization_partial_failure_message(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _ok_result(
            error_code="STAGE_MATERIALIZATION_PARTIAL_FAILURE",
            partial_failure=True,
        )))
        self.assertIn("RM-100", reply)
        self.assertIn("не все этапы", reply)
        self.assertIn("безопасно", reply)

    def test_object_reference_partial_failure_message(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(
            cmd, _ok_result(),
            obj_ref_result={"ok": False, "object_id": "OBJ-001", "updated": False, "error": "Объект OBJ-001 не найден"},
        ))
        self.assertIn("RM-100", reply)
        self.assertIn("не удалось обновить ссылку", reply)
        self.assertIn("безопасно", reply)

    def test_object_reference_harmless_noop_produces_no_warning(self):
        """"ok": True, "updated": False (already set) is not a failure —
        must not be surfaced as a partial-failure warning."""
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(
            cmd, _ok_result(),
            obj_ref_result={"ok": True, "object_id": "OBJ-001", "updated": False, "error": None},
        ))
        self.assertNotIn("не удалось обновить ссылку", reply)


class TestSensitiveValuesNotLogged(_AsyncTestCase):
    def test_no_phone_or_secret_in_result_log_line(self):
        cmd = _fresh_handlers()
        with self.assertLogs("business_core.telegram_handlers", level="INFO") as cm:
            self.run_async(_invoke(cmd, _ok_result()))
        combined = "\n".join(cm.output)
        self.assertNotIn("87087632894", combined)
        self.assertNotIn("BOT_TOKEN", combined)
        self.assertIn("RM-100", combined)


class TestNoArbitraryFirstCandidateInCaller(_AsyncTestCase):
    def test_multiple_templates_message_lists_all_not_just_first(self):
        cmd = _fresh_handlers()
        reply = self.run_async(_invoke(cmd, _fail_result(
            "MULTIPLE_TEMPLATES_REQUIRE_SELECTION", "n/a",
            candidate_template_ids=["RMT-A", "RMT-B", "RMT-C"],
        )))
        for tid in ("RMT-A", "RMT-B", "RMT-C"):
            self.assertIn(tid, reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
