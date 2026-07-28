"""
Sheets API quota / 429 mitigation (2026-07-28, RM-003 incident post-
mortem — see DECISIONS.md history for the full audit chain).

Covers:
  - business_core.sheets.read_with_retry(): 429/5xx/timeout retry policy,
    typed exceptions (SheetsQuotaExceededError/TransientSheetsReadError),
    Retry-After handling.
  - Typed exceptions are never masked as "not found" by the read
    functions on the transition path (find_stage_by_id/find_roadmap_by_id/
    get_stages_for_roadmap/find_template_stages/dependency+checklist+
    output readers).
  - business_core.business_builder._TransitionReadContext: transaction-
    local read reuse (resolve_template_stage_for_stage/get_stages_for_
    roadmap/find_template_stages/STAGE_ENTITY_RELATIONS/TEMPLATE_STAGE_
    DEPENDENCIES/CHECKLIST_INSTANCES/STAGE_OUTPUT_INSTANCES/STAGE_OUTPUT_
    TEMPLATES all read at most once per transaction).
  - transition_stage_status()'s error mapping: SHEETS_QUOTA_EXCEEDED/
    TRANSIENT_SHEETS_READ_ERROR before any write vs after a confirmed
    write.
  - Telegram UX never leaks raw APIError/project_number/traceback.
  - Backward compatibility: every function touched here still works
    exactly as before when read_context is omitted (default None).

Strictly mocked — no live network calls, no production data touched.

PRS-003 incident reference: this file is registered in conftest.py's
hard socket-block list — any accidental real network call here must
raise, not silently succeed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import ANY, MagicMock, patch


def _fresh(module_name):
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    return __import__(module_name, fromlist=["*"])


class _FakeResponse:
    """Minimal requests.Response stand-in for gspread.exceptions.APIError —
    only what APIError.__init__/_extract_error and our own retry-after
    reader touch."""

    def __init__(self, code: int, message: str = "boom", retry_after: str | None = None):
        self._code = code
        self._message = message
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def json(self):
        return {"error": {"code": self._code, "message": self._message}}


def _api_error(code: int, retry_after: str | None = None):
    import gspread.exceptions as gspread_exceptions
    return gspread_exceptions.APIError(_FakeResponse(code, retry_after=retry_after))


# ═══════════════════════════════════════════════════════════════
# read_with_retry() — retry policy + typed exceptions
# ═══════════════════════════════════════════════════════════════

class TestReadWithRetry(unittest.TestCase):
    def test_success_no_retry(self):
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(return_value="ok")
        result = sheets.read_with_retry(fn)
        self.assertEqual(result, "ok")
        fn.assert_called_once()

    def test_429_without_retry_after_no_fast_retry(self):
        """п.5: 429 без Retry-After -> сразу SheetsQuotaExceededError, без retry."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=_api_error(429))
        with self.assertRaises(sheets.SheetsQuotaExceededError):
            sheets.read_with_retry(fn)
        fn.assert_called_once()

    def test_429_with_acceptable_retry_after_one_controlled_retry(self):
        """п.6: 429 с допустимым Retry-After -> максимум одна retry."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=[_api_error(429, retry_after="1"), "ok"])
        with patch("time.sleep") as mock_sleep:
            result = sheets.read_with_retry(fn)
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    def test_429_with_acceptable_retry_after_still_fails_raises(self):
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=[_api_error(429, retry_after="1"), _api_error(429, retry_after="1")])
        with patch("time.sleep"):
            with self.assertRaises(sheets.SheetsQuotaExceededError):
                sheets.read_with_retry(fn)
        # Only ONE controlled retry ever — the second 429 must not retry again.
        self.assertEqual(fn.call_count, 2)

    def test_429_with_excessive_retry_after_no_retry(self):
        """Retry-After too long to keep one Telegram command waiting -> no retry at all."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=_api_error(429, retry_after="30"))
        with patch("time.sleep") as mock_sleep:
            with self.assertRaises(sheets.SheetsQuotaExceededError):
                sheets.read_with_retry(fn)
        fn.assert_called_once()
        mock_sleep.assert_not_called()

    def test_5xx_retry_succeeds(self):
        """п.3."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=[_api_error(503), "ok"])
        with patch("time.sleep"):
            result = sheets.read_with_retry(fn)
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)

    def test_5xx_retries_exhausted(self):
        """п.4: 3 attempts total, then TransientSheetsReadError."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=[_api_error(500), _api_error(502), _api_error(503)])
        with patch("time.sleep"):
            with self.assertRaises(sheets.TransientSheetsReadError):
                sheets.read_with_retry(fn)
        self.assertEqual(fn.call_count, 3)

    def test_timeout_retries_then_raises_transient(self):
        import requests.exceptions as requests_exceptions
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=requests_exceptions.Timeout("timed out"))
        with patch("time.sleep"):
            with self.assertRaises(sheets.TransientSheetsReadError):
                sheets.read_with_retry(fn)
        self.assertEqual(fn.call_count, 3)

    def test_other_exception_not_touched(self):
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=ValueError("unrelated"))
        with self.assertRaises(ValueError):
            sheets.read_with_retry(fn)
        fn.assert_called_once()

    def test_other_api_error_status_not_touched(self):
        """A non-429/5xx APIError (e.g. 403 permission denied) is not
        retried and not converted — it propagates as the raw APIError,
        distinct from both typed exceptions."""
        sheets = _fresh("business_core.sheets")
        fn = MagicMock(side_effect=_api_error(403))
        import gspread.exceptions as gspread_exceptions
        with self.assertRaises(gspread_exceptions.APIError):
            sheets.read_with_retry(fn)
        fn.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Typed exceptions never masked as "not found" (transition-path readers)
# ═══════════════════════════════════════════════════════════════

class TestReadersNeverMaskQuotaErrors(unittest.TestCase):
    def test_find_stage_by_id_429_raises_not_none(self):
        """п.1: 429 при первом Stage lookup -> исключение, не None."""
        rm = _fresh("business_core.roadmap_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.find.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                rm.find_stage_by_id("STAGE-018")

    def test_find_stage_by_id_success_no_match_returns_none(self):
        """п.2: успешный read без совпадения -> STAGE_NOT_FOUND (None), не exception."""
        rm = _fresh("business_core.roadmap_manager")
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.find.return_value = None
            result = rm.find_stage_by_id("STAGE-999")
        self.assertIsNone(result)

    def test_find_roadmap_by_id_429_raises(self):
        rm = _fresh("business_core.roadmap_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.find.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                rm.find_roadmap_by_id("RM-003")

    def test_get_stages_for_roadmap_429_raises(self):
        rm = _fresh("business_core.roadmap_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                rm.get_stages_for_roadmap("RM-003")

    def test_find_template_stages_429_raises(self):
        rtm = _fresh("business_core.roadmap_template_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                rtm.find_template_stages("RMT-IZH-ALM-STANDARD-002")

    def test_list_dependencies_for_template_stage_429_raises(self):
        sdm = _fresh("business_core.stage_dependency_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                sdm.list_dependencies_for_template_stage("TSTG-035")

    def test_list_checklist_instances_429_raises(self):
        cm = _fresh("business_core.checklist_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                cm.list_checklist_instances(business_id="BIZ-001")

    def test_list_output_instances_for_stage_429_raises(self):
        som = _fresh("business_core.stage_output_manager")
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.side_effect = _api_error(429)
            with self.assertRaises(SheetsQuotaExceededError):
                som.list_output_instances_for_stage("STAGE-018")


# ═══════════════════════════════════════════════════════════════
# _TransitionReadContext — transaction-local reuse
# ═══════════════════════════════════════════════════════════════

class TestTransitionReadContextReuse(unittest.TestCase):
    def test_resolve_template_stage_for_stage_reused_from_context(self):
        """п.8: resolve_template_stage_for_stage не перечитывает Stage/
        Roadmap/Template Stage при повторном вызове с тем же context."""
        bb = _fresh("business_core.business_builder")
        rm = _fresh("business_core.roadmap_manager")
        ctx = bb._TransitionReadContext()
        stage = {"stage_id": "STAGE-018", "roadmap_id": "RM-003", "order": "10", "status": "pending"}
        roadmap = {"roadmap_id": "RM-003", "status": "active", "template_id": "RMT-X"}
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage) as mock_find_stage, \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap) as mock_find_roadmap, \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=[{"stage_id": "TSTG-034", "order": "10"}]) as mock_find_tstages:
            first = rm.resolve_template_stage_for_stage("STAGE-018", read_context=ctx)
            second = rm.resolve_template_stage_for_stage("STAGE-018", read_context=ctx)
        self.assertTrue(first["ok"])
        self.assertEqual(first, second)
        mock_find_stage.assert_called_once()
        mock_find_roadmap.assert_called_once()
        mock_find_tstages.assert_called_once()

    def test_resolve_template_stage_for_stage_no_context_always_fresh(self):
        """Backward compatibility: without a context, every call re-reads
        (existing direct-caller behavior, e.g. /provisionstage)."""
        rm = _fresh("business_core.roadmap_manager")
        stage = {"stage_id": "STAGE-018", "roadmap_id": "RM-003", "order": "10", "status": "pending"}
        roadmap = {"roadmap_id": "RM-003", "status": "active", "template_id": "RMT-X"}
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage) as mock_find_stage, \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=roadmap), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=[{"stage_id": "TSTG-034", "order": "10"}]):
            rm.resolve_template_stage_for_stage("STAGE-018")
            rm.resolve_template_stage_for_stage("STAGE-018")
        self.assertEqual(mock_find_stage.call_count, 2)

    def test_get_stages_for_roadmap_reused_from_context(self):
        """п.9: ROADMAP_STAGES dataset не перечитывается без необходимости."""
        bb = _fresh("business_core.business_builder")
        rm = _fresh("business_core.roadmap_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Stage ID", "Roadmap ID", "Order", "Name", "Status", "Due Date", "Notes"],
                ["STAGE-018", "RM-003", "10", "АПЗ", "in_progress", "", ""],
            ]
            first = rm.get_stages_for_roadmap("RM-003", read_context=ctx)
            second = rm.get_stages_for_roadmap("RM-003", read_context=ctx)
        self.assertEqual(first, second)
        mock_sheet.return_value.get_all_values.assert_called_once()

    def test_find_template_stages_reused_from_context(self):
        """п.11: ROADMAP_TEMPLATE_STAGES не перечитывается."""
        bb = _fresh("business_core.business_builder")
        rtm = _fresh("business_core.roadmap_template_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Stage ID", "Template ID", "Order", "Stage Name", "Description", "Required Docs",
                 "Responsible", "Estimated Days", "Notes", "Created At",
                 "SOP IDs", "Checklist IDs", "Materials IDs", "Document Template IDs", "FAQ IDs"],
                ["TSTG-034", "RMT-X", "10", "АПЗ", "", "", "", "", "", "", "", "", "", "", ""],
            ]
            first = rtm.find_template_stages("RMT-X", read_context=ctx)
            second = rtm.find_template_stages("RMT-X", read_context=ctx)
        self.assertEqual(first, second)
        mock_sheet.return_value.get_all_values.assert_called_once()

    def test_template_stage_dependencies_reused_from_context(self):
        """п.12."""
        bb = _fresh("business_core.business_builder")
        sdm = _fresh("business_core.stage_dependency_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Dependency ID", "Roadmap Template ID", "Template Stage ID",
                 "Depends On Template Stage ID", "Dependency Type", "Blocking", "Status",
                 "Created At", "Updated At", "Notes"],
            ]
            first = sdm.list_dependencies_for_template_stage("TSTG-035", read_context=ctx)
            second = sdm._build_active_adjacency("RMT-X", read_context=ctx)
        mock_sheet.return_value.get_all_values.assert_called_once()

    def test_stage_entity_relations_reused_from_context(self):
        """п.13: STAGE_ENTITY_RELATIONS читается максимум один раз,
        разные entity_type фильтруются в памяти."""
        bb = _fresh("business_core.business_builder")
        ser = _fresh("business_core.stage_entity_relations")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Relation ID", "Template Stage ID", "Stage ID", "Entity Type", "Entity ID",
                 "Required", "Blocking", "Minimum Count", "Status", "Created At", "Updated At"],
                ["REL-1", "TSTG-034", "", "checklist", "CHK-001", "true", "true", "1", "active", "", ""],
                ["REL-2", "TSTG-034", "", "required_output", "SOUT-001", "true", "true", "1", "active", "", ""],
            ]
            checklist_rels = ser.get_relations_for_template_stage("TSTG-034", entity_type="checklist", read_context=ctx)
            output_rels = ser.get_relations_for_template_stage("TSTG-034", entity_type="required_output", read_context=ctx)
        mock_sheet.return_value.get_all_values.assert_called_once()
        self.assertEqual(len(checklist_rels), 1)
        self.assertEqual(len(output_rels), 1)

    def test_checklist_instances_reused_from_context(self):
        """п.14: idempotency checks выполняются по dataset в памяти."""
        bb = _fresh("business_core.business_builder")
        cm = _fresh("business_core.checklist_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Checklist Instance ID", "Business ID", "Checklist Template ID",
                 "Checklist Title Snapshot", "Service ID", "Object ID", "Roadmap ID", "Stage ID", "Status",
                 "Total Items", "Required Items", "Completed Items", "Required Remaining",
                 "Created At", "Created By", "Started At", "Completed At", "Cancelled At",
                 "Updated At", "Notes"],
            ]
            cm.list_checklist_instances(business_id="BIZ-001", read_context=ctx)
            cm.find_instances_by_idempotency_key("BIZ-001", "CHK-001", read_context=ctx)
        mock_sheet.return_value.get_all_values.assert_called_once()

    def test_output_instances_and_templates_reused_from_context(self):
        """п.15."""
        bb = _fresh("business_core.business_builder")
        som = _fresh("business_core.stage_output_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Output Instance ID", "Output Template ID", "Stage ID", "Roadmap ID", "Business ID",
                 "Service ID", "Object ID", "Status", "Required", "Blocking", "Title Snapshot",
                 "Description Snapshot", "Output Type", "Verification Method", "Created At", "Updated At", "Notes"],
            ]
            som.list_output_instances_for_stage("STAGE-018", read_context=ctx)
            som.list_output_instances_for_stage("STAGE-018", read_context=ctx)
        mock_sheet.return_value.get_all_values.assert_called_once()

    def test_find_output_template_by_id_reused_from_context(self):
        bb = _fresh("business_core.business_builder")
        som = _fresh("business_core.stage_output_manager")
        ctx = bb._TransitionReadContext()
        with patch("business_core.sheets.get_business_sheet") as mock_sheet:
            mock_sheet.return_value.get_all_values.return_value = [
                ["Output Template ID", "Biz ID", "Service ID", "Template ID", "Template Stage ID",
                 "Status"],
                ["SOUT-001", "BIZ-001", "", "", "TSTG-034", "active"],
                ["SOUT-002", "BIZ-001", "", "", "TSTG-034", "active"],
            ]
            r1 = som.find_output_template_by_id("SOUT-001", read_context=ctx)
            r2 = som.find_output_template_by_id("SOUT-002", read_context=ctx)
        mock_sheet.return_value.get_all_values.assert_called_once()
        self.assertEqual(r1["Output Template ID"], "SOUT-001")
        self.assertEqual(r2["Output Template ID"], "SOUT-002")


# ═══════════════════════════════════════════════════════════════
# transition_stage_status() error mapping (before/after write)
# ═══════════════════════════════════════════════════════════════

from test_stage_transition_foundation import _BaseTransitionTestCase, _stage, _roadmap, _fresh_bb


class TestTransitionErrorMapping(_BaseTransitionTestCase):
    def test_quota_error_before_write_stage_unchanged(self):
        """п.20: ошибка до записи -> Этап не изменён."""
        bb = _fresh_bb()
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.roadmap_manager.find_stage_by_id",
                   side_effect=SheetsQuotaExceededError("quota", retry_after=None)):
            result = bb.transition_stage_status("STAGE-018", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SHEETS_QUOTA_EXCEEDED")
        self.assertTrue(result["retry_safe"])

    def test_transient_error_before_write_stage_unchanged(self):
        bb = _fresh_bb()
        from business_core.sheets import TransientSheetsReadError
        with patch("business_core.roadmap_manager.find_stage_by_id",
                   side_effect=TransientSheetsReadError("5xx exhausted")):
            result = bb.transition_stage_status("STAGE-018", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TRANSIENT_SHEETS_READ_ERROR")
        self.assertTrue(result["retry_safe"])

    def test_quota_error_in_dependency_gate_before_write(self):
        """Bypasses the shared harness (its own internal `with patch(...)`
        for _evaluate_stage_dependency_gate would win over an outer patch
        of the same target) — full manual mock set instead, mirroring
        test_stage_auto_provisioning.py's TestCallOrdering pattern."""
        bb = _fresh_bb()
        from business_core.sheets import SheetsQuotaExceededError
        mock_write = MagicMock()
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=_stage(status="pending")), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=_roadmap()), \
             patch("business_core.business_builder._evaluate_stage_dependency_gate",
                   side_effect=SheetsQuotaExceededError("quota")), \
             patch("business_core.roadmap_manager.update_stage_status_in_sheet", mock_write):
            result = bb.transition_stage_status("STAGE-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SHEETS_QUOTA_EXCEEDED")
        self.assertEqual(result["final_status"], "pending")
        mock_write.assert_not_called()

    def test_quota_error_in_status_write_lookup_before_write(self):
        """update_stage_status_in_sheet()'s OWN internal find_stage_by_id
        re-read hits 429 before its own update_cell — still pre-write."""
        bb = _fresh_bb()
        from business_core.sheets import SheetsQuotaExceededError
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=_stage(status="pending")), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=_roadmap()), \
             patch("business_core.business_builder._evaluate_stage_dependency_gate",
                   return_value=bb._StageDependencyGateResult(blocked=False, error_code="NO_STAGE_DEPENDENCIES")), \
             patch("business_core.roadmap_manager.update_stage_status_in_sheet",
                   side_effect=SheetsQuotaExceededError("quota")):
            result = bb.transition_stage_status("STAGE-001", "in_progress")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "SHEETS_QUOTA_EXCEEDED")
        self.assertEqual(result["final_status"], "pending")

    def test_error_after_write_reports_confirmed_final_status(self):
        """п.21: ошибка после Status write -> final_status подтверждён,
        downstream error отдельно (не 'Этап не изменён')."""
        result = self._call(
            stage=_stage(status="pending"), target_status="in_progress",
            progress_result={"ok": False, "error": "Google Sheets API quota exceeded: boom",
                              "roadmap_id": "RM-001", "old_progress": "", "new_progress": 0,
                              "done_count": 0, "total_count": 0, "changed": False},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["final_status"], "in_progress")
        self.assertTrue(result["partial_success"])
        self.assertEqual(result["code"], "PROGRESS_RECALCULATION_FAILED")
        self._last_mock_write.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Telegram UX — no raw API details leaked
# ═══════════════════════════════════════════════════════════════

class TestTelegramQuotaUX(unittest.TestCase):
    def test_quota_exceeded_message_before_write(self):
        th = _fresh("business_core.telegram_handlers")
        result = {
            "code": "SHEETS_QUOTA_EXCEEDED",
            "error": "APIError: [429]: Quota exceeded for quota metric ... consumer 'project_number:271607812866'.",
            "final_status": "pending", "changed": False,
        }
        msg = th._stage_transition_failure_message(result, "STAGE-018", "in_progress")
        self.assertIn("Google Sheets", msg)
        self.assertIn("не изменён", msg)
        self.assertNotIn("project_number", msg)
        self.assertNotIn("APIError", msg)
        self.assertNotIn("Traceback", msg)

    def test_transient_read_error_message_before_write(self):
        th = _fresh("business_core.telegram_handlers")
        result = {
            "code": "TRANSIENT_SHEETS_READ_ERROR",
            "error": "TransientSheetsReadError: Google Sheets API error after 3 attempts: [503]",
            "final_status": "pending", "changed": False,
        }
        msg = th._stage_transition_failure_message(result, "STAGE-018", "in_progress")
        self.assertIn("не изменён", msg)
        self.assertNotIn("503", msg)
        self.assertNotIn("Traceback", msg)


if __name__ == "__main__":
    unittest.main()
