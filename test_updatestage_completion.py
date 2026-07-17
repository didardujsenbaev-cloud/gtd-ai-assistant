"""
Tests for Phase 9E.2 — интеграция автозавершения Roadmap в /updatestage.

Контракт:
- после успешного recalculate_roadmap_progress вызывается
  maybe_complete_roadmap(roadmap_id, progress_pct=new_progress) —
  без повторного пересчёта Progress %;
- ответ содержит строку про завершение ТОЛЬКО при реальном переходе
  active -> completed, либо при idempotent-повторе на уже completed;
- если условия не выполнены (progress < 100, или Status не active/completed) —
  ничего дополнительного про Status не выводится;
- при невалидном статусе/несуществующем этапе maybe_complete_roadmap не
  вызывается вовсе.
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


def _update_result(changed=True, old="pending", new="done", roadmap_id="RM-001", ok=True, error=None):
    return {"ok": ok, "error": error, "stage_id": "STAGE-001", "roadmap_id": roadmap_id,
            "old_status": old, "new_status": new, "changed": changed}


def _progress_result(old="67", new=100, done=3, total=3, changed=True, roadmap_id="RM-001"):
    return {"ok": True, "error": None, "roadmap_id": roadmap_id,
            "old_progress": old, "new_progress": new,
            "done_count": done, "total_count": total, "changed": changed}


def _completion_result(changed=True, old="active", new="completed", roadmap_id="RM-001", ok=True, error=None):
    return {"ok": ok, "error": error, "roadmap_id": roadmap_id,
            "old_status": old, "new_status": new, "changed": changed}


# ────────────────────────────────────────────────────────────
# Основной сценарий: последний этап завершает roadmap
# ────────────────────────────────────────────────────────────

class TestLastStageCompletesRoadmap(unittest.TestCase):

    def test_last_stage_done_progress_100_roadmap_completed(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        maybe_calls = []

        def fake_maybe_complete(roadmap_id, **kwargs):
            maybe_calls.append((roadmap_id, kwargs))
            return _completion_result(changed=True, old="active", new="completed")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=True)), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(old="67", new=100, done=3, total=3, changed=True)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       side_effect=fake_maybe_complete):
                await th.updatestage_cmd(upd, ctx)

        _run(run())

        self.assertEqual(len(maybe_calls), 1)
        roadmap_id, kwargs = maybe_calls[0]
        self.assertEqual(roadmap_id, "RM-001")
        self.assertEqual(kwargs.get("progress_pct"), 100)

        reply = upd.message.reply_text.call_args[0][0]
        self.assertEqual(
            reply,
            "✅ Этап `STAGE-001`: pending → done\n"
            "Progress Roadmap `RM-001`: 67% → 100%\n"
            "✅ Roadmap `RM-001` завершён: active → completed",
        )

    def test_last_stage_skipped_completes_roadmap(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-003 status=skipped",
            ["stage_id=STAGE-003", "status=skipped"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=True, old="pending", new="skipped")), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(old="67", new=100, changed=True)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       return_value=_completion_result(changed=True)):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("Roadmap `RM-001` завершён: active → completed", reply)

    def test_progress_below_100_roadmap_stays_active_no_extra_line(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        maybe_calls = []

        def fake_maybe_complete(roadmap_id, **kwargs):
            maybe_calls.append(roadmap_id)
            # progress < 100 -> should_complete_roadmap внутри вернёт False
            return _completion_result(changed=False, old="active", new="active")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=True)), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(old="33", new=67, done=2, total=3, changed=True)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       side_effect=fake_maybe_complete):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        # maybe_complete_roadmap всё равно вызывается (дешёвая проверка),
        # но условие не выполняется -> ничего в ответе про Status
        self.assertEqual(maybe_calls, ["RM-001"])
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("завершён", reply)
        self.assertNotIn("Roadmap `RM-001` уже имеет статус", reply)
        self.assertIn("Progress Roadmap `RM-001`: 33% → 67%", reply)


# ────────────────────────────────────────────────────────────
# maybe_complete_roadmap НЕ вызывается при ошибках
# ────────────────────────────────────────────────────────────

class TestMaybeCompleteNotCalledOnErrors(unittest.TestCase):

    def test_invalid_status_does_not_call_maybe_complete(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=bogus",
            ["stage_id=STAGE-001", "status=bogus"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(ok=False, error="Недопустимый статус 'bogus'", roadmap_id="")), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc, \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap") as mock_complete:
                await th.updatestage_cmd(upd, ctx)
                mock_recalc.assert_not_called()
                mock_complete.assert_not_called()

        _run(run())

    def test_stage_not_found_does_not_call_maybe_complete(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-UNKNOWN status=done",
            ["stage_id=STAGE-UNKNOWN", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(ok=False, error="не найден", roadmap_id="")), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress") as mock_recalc, \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap") as mock_complete:
                await th.updatestage_cmd(upd, ctx)
                mock_recalc.assert_not_called()
                mock_complete.assert_not_called()

        _run(run())


# ────────────────────────────────────────────────────────────
# Идемпотентность после завершения
# ────────────────────────────────────────────────────────────

class TestIdempotentAfterCompletion(unittest.TestCase):

    def test_repeat_call_after_completed_is_safe(self):
        """Повторная установка статуса этапа после того, как roadmap уже
        completed — безопасна, показывает 'уже имеет статус completed'."""
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-003 status=skipped",
            ["stage_id=STAGE-003", "status=skipped"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=False, old="skipped", new="skipped")), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(old="100", new=100, changed=False)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       return_value=_completion_result(changed=False, old="completed", new="completed")):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertIn("уже имел статус", reply)  # этап
        self.assertIn("Roadmap `RM-001` уже имеет статус `completed`", reply)
        self.assertNotIn("завершён:", reply)  # не должно быть сообщения о НОВОМ переходе

    def test_active_roadmap_below_100_no_completed_message_on_repeat(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=False, old="done", new="done")), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(old="67", new=67, changed=False)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       return_value=_completion_result(changed=False, old="active", new="active")):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        reply = upd.message.reply_text.call_args[0][0]
        self.assertNotIn("завершён", reply)
        self.assertNotIn("уже имеет статус", reply)


# ────────────────────────────────────────────────────────────
# progress_pct передаётся напрямую (не пересчитывается заново)
# ────────────────────────────────────────────────────────────

class TestNoDuplicateRecalculation(unittest.TestCase):

    def test_maybe_complete_receives_progress_pct_not_none(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        captured = {}

        def fake_maybe_complete(roadmap_id, **kwargs):
            captured.update(kwargs)
            return _completion_result(changed=False, old="active", new="active")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=True)), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       return_value=_progress_result(new=42, changed=True)), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       side_effect=fake_maybe_complete):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        self.assertEqual(captured.get("progress_pct"), 42)

    def test_recalculate_called_exactly_once_even_with_completion(self):
        th = _fresh_th()
        upd, ctx = _make_update(
            "/updatestage stage_id=STAGE-001 status=done",
            ["stage_id=STAGE-001", "status=done"],
        )
        recalc_calls = []

        def fake_recalc(roadmap_id):
            recalc_calls.append(roadmap_id)
            return _progress_result(new=100, changed=True)

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                       return_value=_update_result(changed=True)), \
                 patch("business_core.roadmap_manager.recalculate_roadmap_progress",
                       side_effect=fake_recalc), \
                 patch("business_core.roadmap_manager.maybe_complete_roadmap",
                       return_value=_completion_result(changed=True)):
                await th.updatestage_cmd(upd, ctx)

        _run(run())
        self.assertEqual(recalc_calls, ["RM-001"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
