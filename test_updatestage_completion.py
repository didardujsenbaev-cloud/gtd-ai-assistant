"""
Tests for Phase 9E.2 — интеграция автозавершения Roadmap в /updatestage.

Phase 34C (ADR-017) update: the recalculate_roadmap_progress() +
maybe_complete_roadmap() orchestration this file used to test at the
/updatestage handler level now lives entirely inside business_builder.
transition_stage_status() (see test_stage_transition_foundation.py for
call-count/argument-level coverage of that function). This file now
covers only the HANDLER's rendering of transition_stage_status()'s
structured result — updatestage_cmd no longer calls
recalculate_roadmap_progress/maybe_complete_roadmap itself.

Контракт (unchanged in spirit, now enforced inside transition_stage_status):
- ответ содержит строку про завершение ТОЛЬКО при реальном переходе
  active -> completed, либо при idempotent-повторе на уже completed;
- если условия не выполнены (progress < 100, или Status не active/completed) —
  ничего дополнительного про Status не выводится.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


def _fresh(mod_name: str):
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module(mod_name)


def _fresh_th():
    return _fresh("business_core.telegram_handlers")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_update(text: str, args_list: list[str]):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args_list
    return update, context


def _transition_result(
    ok=True, code="STAGE_STATUS_UPDATED", error=None,
    stage_id="STAGE-001", roadmap_id="RM-001",
    previous_status="pending", requested_status="done", final_status="done",
    changed=True, partial_success=False, written_fields=("Status",),
    progress_before=None, progress_after=None,
    roadmap_status_before="active", roadmap_status_after="active",
):
    return {
        "ok": ok, "code": code, "error": error,
        "stage_id": stage_id, "roadmap_id": roadmap_id,
        "previous_status": previous_status, "requested_status": requested_status,
        "final_status": final_status, "changed": changed, "partial_success": partial_success,
        "written_fields": written_fields, "warnings": (), "downstream_failures": (),
        "progress_before": progress_before, "progress_after": progress_after,
        "roadmap_status_before": roadmap_status_before, "roadmap_status_after": roadmap_status_after,
        "retry_safe": True,
    }


async def _invoke(th, upd, ctx, result):
    with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
         patch("business_core.business_builder.transition_stage_status", return_value=result):
        await th.updatestage_cmd(upd, ctx)


class TestLastStageCompletesRoadmap(unittest.TestCase):

    def test_last_stage_done_progress_100_roadmap_completed(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            progress_before=67, progress_after=100,
            roadmap_status_before="active", roadmap_status_after="completed",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertEqual(
            reply,
            "✅ Этап обновлён\n"
            "Этап: `STAGE-001`\n"
            "Статус: pending → done\n"
            "Прогресс roadmap `RM-001`: 67% → 100%\n"
            "✅ Roadmap `RM-001` завершён: active → completed",
        )

    def test_last_stage_skipped_completes_roadmap(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-003 status=skipped",
            ["stage_id=STAGE-003", "status=skipped"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            stage_id="STAGE-003", previous_status="pending", requested_status="skipped",
            final_status="skipped", progress_before=67, progress_after=100,
            roadmap_status_before="active", roadmap_status_after="completed",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Roadmap `RM-001` завершён: active → completed", reply)

    def test_progress_below_100_roadmap_stays_active_no_extra_line(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            progress_before=33, progress_after=67,
            roadmap_status_before="active", roadmap_status_after="active",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("завершён", reply)
        self.assertNotIn("Roadmap `RM-001` уже имеет статус", reply)
        self.assertIn("Прогресс roadmap `RM-001`: 33% → 67%", reply)


class TestMaybeCompleteNotCalledOnErrors(unittest.TestCase):

    def test_invalid_status_shows_failure_message(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=bogus",
            ["stage_id=STAGE-001", "status=bogus"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            ok=False, code="INVALID_STAGE_STATUS", error="Недопустимый статус 'bogus'",
            requested_status="bogus", changed=False, roadmap_id="",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)

    def test_stage_not_found_shows_failure_message(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-UNKNOWN status=done",
            ["stage_id=STAGE-UNKNOWN", "status=done"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            ok=False, code="STAGE_NOT_FOUND", error="Этап не найден",
            stage_id="STAGE-UNKNOWN", roadmap_id="", changed=False,
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)


class TestIdempotentAfterCompletion(unittest.TestCase):

    def test_repeat_call_after_completed_is_safe(self):
        """Повторная установка статуса этапа после того, как roadmap уже
        completed — безопасна, показывает 'уже имеет статус completed'."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-003 status=skipped",
            ["stage_id=STAGE-003", "status=skipped"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            stage_id="STAGE-003", previous_status="skipped", requested_status="skipped",
            final_status="skipped", changed=False,
            roadmap_status_before="completed", roadmap_status_after="completed",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("уже имел статус", reply)
        self.assertNotIn("завершён:", reply)

    def test_active_roadmap_below_100_no_completed_message_on_repeat(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        _run(_invoke(th, upd, ctx, _transition_result(
            previous_status="done", requested_status="done", final_status="done", changed=False,
            roadmap_status_before="active", roadmap_status_after="active",
        )))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("завершён", reply)
        self.assertNotIn("уже имеет статус", reply)


class TestPartialFailureFromDownstream(unittest.TestCase):
    """Phase 34C: progress-recalculation/auto-completion failures inside
    transition_stage_status() surface as partial_success=True — the
    handler must render this distinctly, never as a total failure (the
    Stage Status write itself already succeeded)."""

    def test_partial_success_shown_when_progress_recalculation_fails(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        result = _transition_result(code="PROGRESS_RECALCULATION_FAILED", partial_success=True)
        result["downstream_failures"] = ("Не удалось пересчитать прогресс: timeout",)
        _run(_invoke(th, upd, ctx, result))
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("⚠️", reply)
        self.assertIn("частично", reply)
        self.assertIn("Повтор команды безопасен", reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
