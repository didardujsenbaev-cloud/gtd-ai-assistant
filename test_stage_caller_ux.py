"""
Phase 34D: caller-facing UX tests for
business_core.telegram_handlers.updatestage_cmd() and the shared
_stage_edit_execute() admin-field confirm step.

Strictly against mocked business_core.business_builder.
transition_stage_status()/update_stage_admin_fields() — telegram_handlers.py
itself must never reach roadmap_manager's low-level Stage functions
directly (ADR-017; enforced structurally by
test_stage_architecture_guards.py). This file exercises only the
translation from the structured result into the Telegram message and
log line — no live network calls, no production data touched.
"""

from __future__ import annotations

import sys
import unittest
import logging
from unittest.mock import patch, MagicMock, AsyncMock


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _make_update(text: str, args: list):
    update = MagicMock()
    context = MagicMock()
    context.args = args
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update, context


def _last_reply(update) -> str:
    return update.message.reply_text.call_args[0][0]


def _transition_result(**overrides) -> dict:
    base = {
        "ok": True, "code": "STAGE_STATUS_UPDATED", "error": None,
        "stage_id": "STAGE-001", "roadmap_id": "RM-001",
        "previous_status": "pending", "requested_status": "in_progress", "final_status": "in_progress",
        "changed": True, "partial_success": False, "written_fields": ("Status",),
        "warnings": (), "downstream_failures": (),
        "progress_before": 0, "progress_after": 13,
        "roadmap_status_before": "active", "roadmap_status_after": "active",
        "retry_safe": True,
    }
    base.update(overrides)
    return base


class _AsyncTestCase(unittest.TestCase):
    def run_async(self, coro):
        import asyncio
        return asyncio.run(coro)


async def _invoke_updatestage(th, result: dict, status="in_progress"):
    update, context = _make_update(
        f"/updatestage stage_id=STAGE-001 status={status}",
        ["stage_id=STAGE-001", f"status={status}"],
    )
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
         patch("business_core.business_builder.transition_stage_status", return_value=result):
        await th.updatestage_cmd(update, context)
    return _last_reply(update)


class TestStatusUpdateUX(_AsyncTestCase):
    def test_pending_to_in_progress_success(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            previous_status="pending", requested_status="in_progress", final_status="in_progress",
        )))
        self.assertIn("STAGE-001", reply)
        self.assertIn("RM-001", reply)
        self.assertIn("Ожидает", reply)
        self.assertIn("В работе", reply)

    def test_in_progress_to_done_success(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            previous_status="in_progress", requested_status="done", final_status="done",
            progress_before=87, progress_after=100,
        ), status="done"))
        self.assertIn("В работе", reply)
        self.assertIn("Выполнен", reply)
        self.assertIn("87", reply)
        self.assertIn("100", reply)

    def test_status_names_translated_for_all_canonical_values(self):
        th = _fresh_th()
        translations = {
            "pending": "Ожидает", "in_progress": "В работе", "blocked": "Заблокирован",
            "done": "Выполнен", "skipped": "Пропущен",
        }
        for status, ru in translations.items():
            reply = self.run_async(_invoke_updatestage(th, _transition_result(
                previous_status="pending", requested_status=status, final_status=status,
            ), status=status))
            self.assertIn(ru, reply, f"{status} should translate to {ru!r}")
            self.assertIn(f"`{status}`", reply, f"machine ID {status!r} must not be hidden")

    def test_roadmap_completion_shown_only_when_confirmed(self):
        th = _fresh_th()
        completed_reply = self.run_async(_invoke_updatestage(th, _transition_result(
            roadmap_status_before="active", roadmap_status_after="completed",
        )))
        self.assertIn("🎉", completed_reply)

        not_completed_reply = self.run_async(_invoke_updatestage(th, _transition_result(
            roadmap_status_before="active", roadmap_status_after="active",
        )))
        self.assertNotIn("🎉", not_completed_reply)


class TestUnchangedUX(_AsyncTestCase):
    def test_pending_to_pending_unchanged(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            code="STAGE_STATUS_UNCHANGED",
            previous_status="pending", requested_status="pending", final_status="pending",
            changed=False,
        ), status="pending"))
        self.assertNotIn("✅ Статус этапа обновлён", reply)
        self.assertIn("уже имеет запрошенный статус", reply)

    def test_done_to_done_unchanged(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            code="STAGE_STATUS_UNCHANGED",
            previous_status="done", requested_status="done", final_status="done",
            changed=False,
        ), status="done"))
        self.assertNotIn("обновлён", reply)
        self.assertIn("уже имеет запрошенный статус", reply)


class TestValidationUX(_AsyncTestCase):
    def test_missing_stage(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="STAGE_NOT_FOUND", error="Этап не найден",
            stage_id="STAGE-999", roadmap_id="", previous_status="", final_status="", changed=False,
        )))
        self.assertIn("не найден", reply)
        self.assertNotIn("Traceback", reply)

    def test_missing_roadmap(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="ROADMAP_NOT_FOUND", error="Roadmap не найден",
            roadmap_id="", previous_status="", final_status="", changed=False,
        )))
        self.assertIn("Roadmap", reply)
        self.assertIn("STAGE-001", reply)

    def test_invalid_status(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="INVALID_STAGE_STATUS", error="Недопустимый статус 'bogus'",
            requested_status="bogus", previous_status="pending", final_status="pending", changed=False,
        ), status="bogus"))
        self.assertIn("Недопустимый статус", reply)
        self.assertIn("pending", reply)
        self.assertIn("skipped", reply)

    def test_invalid_transition(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="INVALID_STAGE_TRANSITION",
            previous_status="pending", requested_status="done", final_status="pending", changed=False,
        ), status="done"))
        self.assertIn("не разрешён", reply)
        self.assertIn("Ожидает", reply)
        self.assertIn("Выполнен", reply)

    def test_done_reopen_blocked(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION",
            previous_status="done", requested_status="pending", final_status="done", changed=False,
        ), status="pending"))
        self.assertIn("🔒", reply)
        self.assertIn("STAGE-001", reply)
        self.assertIn("RM-001", reply)
        self.assertIn("не реализовано", reply)

    def test_skipped_reopen_blocked(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION",
            previous_status="skipped", requested_status="in_progress", final_status="skipped", changed=False,
        ), status="in_progress"))
        self.assertIn("🔒", reply)
        self.assertIn("Пропущен", reply)


class TestRoadmapStatusUX(_AsyncTestCase):
    def test_on_hold(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="ROADMAP_ON_HOLD",
            previous_status="pending", final_status="pending", changed=False,
            roadmap_status_before="on_hold", roadmap_status_after="on_hold",
        )))
        self.assertIn("приостановлен", reply)
        self.assertIn("административные", reply.lower())

    def test_completed(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="ROADMAP_COMPLETED",
            previous_status="pending", final_status="pending", changed=False,
            roadmap_status_before="completed", roadmap_status_after="completed",
        )))
        self.assertIn("завершён", reply)
        self.assertIn("RM-001", reply)

    def test_cancelled(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="ROADMAP_CANCELLED",
            previous_status="pending", final_status="pending", changed=False,
            roadmap_status_before="cancelled", roadmap_status_after="cancelled",
        )))
        self.assertIn("отменён", reply)
        self.assertNotIn("Traceback", reply)


class TestPartialFailureUX(_AsyncTestCase):
    def test_progress_recalculation_failure(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            code="PROGRESS_RECALCULATION_FAILED", partial_success=True,
            downstream_failures=("Не удалось пересчитать прогресс: 429",), retry_safe=True,
        )))
        self.assertIn("⚠️", reply)
        self.assertIn("STAGE-001", reply)
        self.assertIn("RM-001", reply)
        self.assertIn("Повтор команды безопасен", reply)

    def test_roadmap_auto_completion_failure(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            code="ROADMAP_AUTO_COMPLETION_FAILED", partial_success=True,
            downstream_failures=("Не удалось проверить завершение Roadmap: 429",), retry_safe=True,
        )))
        self.assertIn("⚠️", reply)
        self.assertIn("STAGE-001", reply)
        self.assertIn("RM-001", reply)

    def test_stage_write_partial_failure_preserves_ids(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result(
            ok=False, code="STAGE_WRITE_PARTIAL_FAILURE",
            previous_status="pending", final_status="pending", changed=False,
            error="Не удалось записать Status: timeout",
        )))
        self.assertIn("STAGE-001", reply)

    def test_retry_safe_wording_only_when_true(self):
        th = _fresh_th()
        reply_safe = self.run_async(_invoke_updatestage(th, _transition_result(
            partial_success=True, retry_safe=True,
            downstream_failures=("x",),
        )))
        self.assertIn("Повтор команды безопасен", reply_safe)

        reply_unsafe = self.run_async(_invoke_updatestage(th, _transition_result(
            partial_success=True, retry_safe=False,
            downstream_failures=("x",),
        )))
        self.assertNotIn("Повтор команды безопасен", reply_unsafe)


class TestSafety(_AsyncTestCase):
    def test_unknown_code_fallback(self):
        th = _fresh_th()
        with self.assertLogs("business_core.telegram_handlers", level="WARNING") as cm:
            reply = self.run_async(_invoke_updatestage(th, _transition_result(
                ok=False, code="SOME_FUTURE_CODE_NOT_YET_MAPPED", error="internal db detail",
                previous_status="pending", final_status="pending", changed=False,
            )))
        self.assertNotIn("internal db detail", reply)
        self.assertNotIn("Traceback", reply)
        self.assertTrue(any("SOME_FUTURE_CODE_NOT_YET_MAPPED" in msg for msg in cm.output))

    def test_no_raw_dict_or_traceback_in_success_reply(self):
        th = _fresh_th()
        reply = self.run_async(_invoke_updatestage(th, _transition_result()))
        self.assertNotIn("Traceback", reply)
        self.assertNotIn("{'ok'", reply)

    def test_no_sensitive_values_in_log(self):
        th = _fresh_th()
        with self.assertLogs("business_core.telegram_handlers", level="INFO") as cm:
            self.run_async(_invoke_updatestage(th, _transition_result()))
        combined = "\n".join(cm.output)
        self.assertNotIn("BOT_TOKEN", combined)
        self.assertNotIn("87087632894", combined)
        self.assertIn("STAGE-001", combined)


class TestAdminUX(_AsyncTestCase):
    async def _invoke_admin(self, th, result, target_status=None):
        update, context = _make_update("✅ Подтвердить", [])
        context.user_data = {
            "se_test": {
                "stage_id": "STAGE-001", "field_label": "Ответственный",
                "writes": ({"Status": target_status} if target_status else {"Responsible": "Иван"}),
                "old_value_display": "", "new_value_display": "Иван",
            }
        }
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
            if target_status:
                with patch("business_core.business_builder.transition_stage_status", return_value=result):
                    await th._stage_edit_execute(update, context, "se_test")
            else:
                with patch("business_core.business_builder.update_stage_admin_fields", return_value=result):
                    await th._stage_edit_execute(update, context, "se_test")
        return update.message.reply_text.call_args[0][0]

    def test_active_admin_edit_success(self):
        th = _fresh_th()
        result = {"ok": True, "code": "STAGE_STATUS_UNCHANGED", "error": None,
                  "stage_id": "STAGE-001", "roadmap_id": "RM-001",
                  "written_fields": ("Responsible",), "roadmap_status_before": "active",
                  "roadmap_status_after": "active"}
        reply = self.run_async(self._invoke_admin(th, result))
        self.assertIn("✅", reply)
        self.assertIn("Иван", reply)

    def test_on_hold_admin_edit_success(self):
        th = _fresh_th()
        result = {"ok": True, "code": "STAGE_STATUS_UNCHANGED", "error": None,
                  "stage_id": "STAGE-001", "roadmap_id": "RM-001",
                  "written_fields": ("Responsible",), "roadmap_status_before": "on_hold",
                  "roadmap_status_after": "on_hold"}
        reply = self.run_async(self._invoke_admin(th, result))
        self.assertIn("✅", reply)

    def test_completed_admin_edit_blocked(self):
        th = _fresh_th()
        result = {"ok": False, "code": "ROADMAP_COMPLETED", "error": "Roadmap завершён",
                  "stage_id": "STAGE-001", "roadmap_id": "RM-001",
                  "roadmap_status_before": "completed", "roadmap_status_after": "completed"}
        reply = self.run_async(self._invoke_admin(th, result))
        self.assertIn("завершён", reply)

    def test_cancelled_admin_edit_blocked(self):
        th = _fresh_th()
        result = {"ok": False, "code": "ROADMAP_CANCELLED", "error": "Roadmap отменён",
                  "stage_id": "STAGE-001", "roadmap_id": "RM-001",
                  "roadmap_status_before": "cancelled", "roadmap_status_after": "cancelled"}
        reply = self.run_async(self._invoke_admin(th, result))
        self.assertIn("отменён", reply)

    def test_status_route_uses_transition_api_not_admin_api(self):
        """A "Status" key in the snapshot must call transition_stage_status,
        never update_stage_admin_fields — verified by patching only one
        of the two and confirming the call succeeds without error."""
        th = _fresh_th()
        transition_result = {
            "ok": True, "code": "STAGE_STATUS_UPDATED", "error": None,
            "stage_id": "STAGE-001", "roadmap_id": "RM-001",
            "previous_status": "pending", "requested_status": "blocked", "final_status": "blocked",
            "changed": True, "written_fields": ("Status",),
        }
        reply = self.run_async(self._invoke_admin(th, transition_result, target_status="blocked"))
        self.assertIn("✅", reply)

    def test_unsupported_admin_field_handled_safely(self):
        th = _fresh_th()
        result = {"ok": False, "code": "STAGE_WRITE_PARTIAL_FAILURE", "error": "field rejected",
                  "stage_id": "STAGE-001", "roadmap_id": "RM-001"}
        reply = self.run_async(self._invoke_admin(th, result))
        self.assertIn("❌", reply)
        self.assertNotIn("Traceback", reply)


# ─────────────────────────────────────────────────────────────
# Phase 43: Document Completion Gate — /updatestage force/reason/User wiring
# ─────────────────────────────────────────────────────────────

class TestDocumentCompletionGateCallerUX(_AsyncTestCase):
    def _invoke(self, th, result: dict, cmdline: str, effective_user=None):
        update, context = _make_update(cmdline, cmdline.split()[1:])
        if effective_user is not None:
            update.effective_user = effective_user
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.transition_stage_status", return_value=result) as mock_transition:
            self.run_async(th.updatestage_cmd(update, context))
        return _last_reply(update), mock_transition

    def test_force_yes_and_reason_and_actor_passed_through(self):
        th = _fresh_th()
        user = MagicMock(username="dida", id=123)
        result = _transition_result(
            previous_status="in_progress", requested_status="done", final_status="done",
            override_applied=True, override_type="missing_blocking_documents", override_id="SCO-001",
        )
        reply, mock_transition = self._invoke(
            th, result,
            '/updatestage stage_id=STAGE-001 status=done force=yes reason="manager approved"',
            effective_user=user,
        )
        args, kwargs = mock_transition.call_args
        self.assertEqual(args[0], "STAGE-001")
        self.assertEqual(args[1], "done")
        self.assertTrue(kwargs.get("force"))
        self.assertEqual(kwargs.get("reason"), "manager approved")
        self.assertEqual(kwargs.get("actor"), "dida")
        self.assertIn("✅", reply)
        self.assertIn("SCO-001", reply)

    def test_override_type_underscores_preserved_via_code_span(self):
        """Live-production bug: override_type rendered outside a
        backtick code-span under parse_mode="Markdown" had its
        underscores silently eaten by legacy Telegram Markdown
        (missing_blocking_documents -> missingblockingdocuments in the
        actual message, even though the Sheets row itself was correct).
        Fixed by wrapping override_type in backticks, same as
        override_id already was."""
        th = _fresh_th()
        result = _transition_result(
            previous_status="in_progress", requested_status="done", final_status="done",
            override_applied=True, override_type="missing_blocking_documents", override_id="SCO-001",
        )
        reply, _ = self._invoke(
            th, result,
            '/updatestage stage_id=STAGE-001 status=done force=yes reason="approved"',
        )
        self.assertIn("`missing_blocking_documents`", reply)
        self.assertIn("`SCO-001`", reply)
        self.assertNotIn("missingblockingdocuments", reply)

    def test_force_omitted_defaults_to_false(self):
        th = _fresh_th()
        result = _transition_result(previous_status="in_progress", requested_status="done", final_status="done")
        _, mock_transition = self._invoke(th, result, "/updatestage stage_id=STAGE-001 status=done")
        _, kwargs = mock_transition.call_args
        self.assertFalse(kwargs.get("force"))
        self.assertIsNone(kwargs.get("reason"))

    def test_force_no_without_reason_is_not_treated_as_force(self):
        th = _fresh_th()
        result = _transition_result(previous_status="in_progress", requested_status="done", final_status="done")
        _, mock_transition = self._invoke(th, result, "/updatestage stage_id=STAGE-001 status=done force=no")
        _, kwargs = mock_transition.call_args
        self.assertFalse(kwargs.get("force"))

    def test_gate_blocked_message_shows_missing_doc_ids(self):
        th = _fresh_th()
        result = {
            "ok": False, "code": "STAGE_DOCUMENT_GATE_BLOCKED",
            "error": "У этапа STAGE-001 есть незакрытые обязательные требования: DOC-008",
            "stage_id": "STAGE-001", "roadmap_id": "RM-001",
            "previous_status": "in_progress", "requested_status": "done", "final_status": "in_progress",
            "missing_blocking_doc_ids": ("DOC-008",),
        }
        reply, _ = self._invoke(th, result, "/updatestage stage_id=STAGE-001 status=done")
        self.assertIn("DOC-008", reply)
        self.assertIn("force=yes", reply)

    def test_configuration_error_message_distinct_from_gate_blocked(self):
        th = _fresh_th()
        result = {
            "ok": False, "code": "STAGE_DOCUMENT_REQUIREMENTS_CONFIGURATION_ERROR",
            "error": "broken", "stage_id": "STAGE-001", "roadmap_id": "RM-001",
            "previous_status": "in_progress", "requested_status": "done", "final_status": "in_progress",
            "configuration_error_details": "STAGE-001/REL-999: dangling entity",
        }
        reply, _ = self._invoke(th, result, "/updatestage stage_id=STAGE-001 status=done")
        self.assertIn("REL-999", reply)
        self.assertNotIn("DOC-", reply)

    def test_override_reason_required_message(self):
        th = _fresh_th()
        result = {
            "ok": False, "code": "STAGE_DOCUMENT_GATE_OVERRIDE_REASON_REQUIRED",
            "error": "force=yes требует reason", "stage_id": "STAGE-001", "roadmap_id": "RM-001",
            "previous_status": "in_progress", "requested_status": "done", "final_status": "in_progress",
        }
        reply, _ = self._invoke(th, result, "/updatestage stage_id=STAGE-001 status=done force=yes")
        self.assertIn("❌", reply)
        self.assertIn("force=yes", reply)

    def test_no_free_text_confirm_word_used_anywhere_in_command_source(self):
        """Phase 43 audit п.22: the override must never rely on a free-
        text 'подтвердить' — only explicit force=/reason= parameters."""
        from pathlib import Path
        path = Path(__file__).parent / "business_core" / "telegram_handlers.py"
        src = path.read_text(encoding="utf-8")
        start = src.index("async def updatestage_cmd")
        end = src.index("\nasync def ", start + 10)
        body = src[start:end]
        self.assertNotIn("подтвердить", body.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
