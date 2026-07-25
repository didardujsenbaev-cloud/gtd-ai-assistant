"""
Phase 29CD: behavioral tests for Service Domain ownership consolidation
(ADR-013). Covers what test_service_architecture_guards.py doesn't:
duplicate-safe/idempotent create_service_record() edge cases, strict
status validation, /services and /newroadmap caller migration, and the
remaining Roadmap active-Service validation edge cases (draft, unknown
status). No live Sheets/network calls anywhere in this file.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

SVC_HEADERS = [
    "ID", "Бизнес ID", "Название", "Slug", "Статус", "Город",
    "Цена мин", "Цена макс", "Срок", "Описание",
    "Этап 1", "Этап 2", "Этап 3", "Этап 4", "Этап 5",
    "Этап 6", "Этап 7", "Этап 8", "Этап 9", "Этап 10",
    "Документы от клиента", "Документы наши",
    "Чек-лист производства", "Чек-лист закрытия",
    "Риски", "Шаблоны", "Инструкция", "Комментарий",
    "Service Name", "Service Category", "Object Type", "Client Type",
    "What Included", "What Not Included", "Currency",
    "Required Documents", "Default Roadmap Template ID",
    "Contractors Needed", "Materials IDs", "Created At", "Last Updated",
]


def _fresh_sm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.service_manager as sm
    return sm


def _svc_row(svc_id="SVC-001", biz_id="BIZ-001", name="Тест", status="active"):
    row = [""] * len(SVC_HEADERS)
    row[SVC_HEADERS.index("ID")] = svc_id
    row[SVC_HEADERS.index("Бизнес ID")] = biz_id
    row[SVC_HEADERS.index("Название")] = name
    row[SVC_HEADERS.index("Статус")] = status
    row[SVC_HEADERS.index("Service Name")] = name
    return row


def _make_sheet(extra_rows=None):
    ws = MagicMock()
    rows = [SVC_HEADERS] + (extra_rows or [])
    ws.get_all_values.return_value = rows
    ws.row_values.return_value = SVC_HEADERS
    return ws


# ────────────────────────────────────────────────────────────
# Duplicate-safe create_service_record
# ────────────────────────────────────────────────────────────

class TestDuplicateSafeCreate(unittest.TestCase):

    def test_1_first_call_creates(self):
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch.object(sm, "generate_service_id", return_value="SVC-900"):
            result = sm.create_service_record(biz_id="BIZ-001", service_name="Новая услуга")
        self.assertTrue(result["ok"])
        self.assertTrue(result["service_created"])
        self.assertFalse(result["service_reused"])
        mock_append.assert_called_once()

    def test_2_second_call_same_key_reuses(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-500", biz_id="BIZ-001", name="Повтор")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(biz_id="BIZ-001", service_name="Повтор")
        self.assertTrue(result["ok"])
        self.assertFalse(result["service_created"])
        self.assertTrue(result["service_reused"])
        self.assertEqual(result["service_id"], "SVC-500")
        mock_append.assert_not_called()

    def test_3_case_only_name_difference_reuses(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-501", biz_id="BIZ-001", name="Узаконение Дома")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(biz_id="BIZ-001", service_name="узаконение дома")
        self.assertTrue(result["service_reused"])
        mock_append.assert_not_called()

    def test_4_whitespace_only_difference_reuses(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-502", biz_id="BIZ-001", name="Узаконение дома")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(biz_id="BIZ-001", service_name="  Узаконение   дома  ")
        self.assertTrue(result["service_reused"])
        mock_append.assert_not_called()

    def test_5_same_name_other_business_creates_separate_service(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-503", biz_id="BIZ-001", name="Общая услуга")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch.object(sm, "generate_service_id", return_value="SVC-901"):
            result = sm.create_service_record(biz_id="BIZ-002", service_name="Общая услуга")
        self.assertTrue(result["ok"])
        self.assertTrue(result["service_created"])
        self.assertEqual(result["service_id"], "SVC-901")
        mock_append.assert_called_once()

    def test_6_mismatch_fields_return_warnings_no_overwrite(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-504", biz_id="BIZ-001", name="Услуга с ценой")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(
                biz_id="BIZ-001", service_name="Услуга с ценой", city="Астана",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["service_reused"])
        self.assertTrue(any("city" in w for w in result["warnings"]))
        mock_append.assert_not_called()

    def test_7_existing_row_never_overwritten(self):
        sm = _fresh_sm()
        existing = _svc_row(svc_id="SVC-505", biz_id="BIZ-001", name="Неизменная услуга")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([existing])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            sm.create_service_record(biz_id="BIZ-001", service_name="Неизменная услуга", city="Астана")
        mock_append.assert_not_called()
        # No update_cell either — reuse never mutates the existing row.

    def test_8_multiple_existing_matches_integrity_error_no_write(self):
        sm = _fresh_sm()
        dup1 = _svc_row(svc_id="SVC-506", biz_id="BIZ-001", name="Дубль")
        dup2 = _svc_row(svc_id="SVC-507", biz_id="BIZ-001", name="дубль")
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet([dup1, dup2])), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(biz_id="BIZ-001", service_name="Дубль")
        self.assertFalse(result["ok"])
        self.assertIn("integrity", result["error"])
        self.assertIn("SVC-506", result["error"])
        self.assertIn("SVC-507", result["error"])
        mock_append.assert_not_called()


# ────────────────────────────────────────────────────────────
# Status validation
# ────────────────────────────────────────────────────────────

class TestStatusValidation(unittest.TestCase):

    def test_omitted_status_defaults_active(self):
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch.object(sm, "generate_service_id", return_value="SVC-910"):
            result = sm.create_service_record(biz_id="BIZ-001", service_name="Без статуса")
        self.assertTrue(result["ok"])
        row = mock_append.call_args.args[1]
        idx = SVC_HEADERS.index("Статус")
        self.assertEqual(row[idx], "active")

    def test_explicit_active_inactive_draft_accepted(self):
        sm = _fresh_sm()
        for status in ("active", "inactive", "draft"):
            with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
                 patch("business_core.sheets.append_business_row") as mock_append, \
                 patch.object(sm, "generate_service_id", return_value="SVC-911"):
                result = sm.create_service_record(
                    biz_id="BIZ-001", service_name=f"Статус {status}", status=status,
                )
            self.assertTrue(result["ok"], f"status={status} should be accepted")
            row = mock_append.call_args.args[1]
            idx = SVC_HEADERS.index("Статус")
            self.assertEqual(row[idx], status)

    def test_unknown_status_rejected(self):
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = sm.create_service_record(
                biz_id="BIZ-001", service_name="Плохой статус", status="paused",
            )
        self.assertFalse(result["ok"])
        self.assertIn("paused", result["error"])
        mock_append.assert_not_called()

    def test_unknown_status_never_written_as_active(self):
        sm = _fresh_sm()
        with patch("business_core.sheets.get_business_sheet", return_value=_make_sheet()), \
             patch("business_core.sheets.append_business_row") as mock_append:
            sm.create_service_record(biz_id="BIZ-001", service_name="Мусорный статус", status="garbage")
        mock_append.assert_not_called()


# ────────────────────────────────────────────────────────────
# /services migration (Part 5)
# ────────────────────────────────────────────────────────────

def _fresh_th():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.telegram_handlers as th
    return th


class TestServicesCommandUsesPublicApi(unittest.TestCase):

    def test_services_cmd_uses_list_services_not_private_helper(self):
        th = _fresh_th()
        update = MagicMock()
        update.message.text = "/services"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.service_manager.list_services",
                   return_value=[{"service_id": "SVC-001", "service_name": "Тест",
                                   "biz_id": "BIZ-001", "status": "active",
                                   "city": "", "object_type": "", "price_from": "", "duration": ""}]) as mock_list:
            asyncio.run(th.services_cmd(update, context))

        mock_list.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("SVC-001", reply)

    def test_services_cmd_does_not_call_private_load_services(self):
        th = _fresh_th()
        update = MagicMock()
        update.message.text = "/services"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.service_manager._load_services") as mock_private, \
             patch("business_core.service_manager.list_services", return_value=[]):
            asyncio.run(th.services_cmd(update, context))

        mock_private.assert_not_called()


# ────────────────────────────────────────────────────────────
# /newroadmap legacy service lookup migration (Part 6)
# ────────────────────────────────────────────────────────────

class TestNewroadmapServiceLookup(unittest.TestCase):

    def _run_newroadmap_service(self, text, matches):
        th = _fresh_th()
        update = MagicMock()
        update.message.text = text
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"nr": {}}

        with patch("business_core.service_manager.find_services_by_name",
                   return_value=matches) as mock_find:
            asyncio.run(th.newroadmap_service(update, context))
        return context, mock_find

    def test_uses_find_services_by_name(self):
        context, mock_find = self._run_newroadmap_service("Узаконение", [])
        mock_find.assert_called_once()

    def test_no_raw_sheet_read(self):
        th = _fresh_th()
        update = MagicMock()
        update.message.text = "Узаконение"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"nr": {}}

        with patch("business_core.sheets.read_business_sheet") as mock_raw, \
             patch("business_core.service_manager.find_services_by_name", return_value=[]):
            asyncio.run(th.newroadmap_service(update, context))
        for call in mock_raw.call_args_list:
            self.assertNotEqual(call.args[0], "service_catalog")

    def test_zero_matches_leaves_service_id_unset(self):
        context, _ = self._run_newroadmap_service("Несуществующая", [])
        self.assertNotIn("service_id", context.user_data["nr"])

    def test_one_match_selects_it(self):
        context, _ = self._run_newroadmap_service(
            "Узаконение", [{"service_id": "SVC-IZH-001", "service_name": "Узаконение дома"}],
        )
        self.assertEqual(context.user_data["nr"]["service_id"], "SVC-IZH-001")

    def test_multiple_matches_does_not_silently_pick_first(self):
        context, _ = self._run_newroadmap_service(
            "Услуга",
            [
                {"service_id": "SVC-A", "service_name": "Услуга А"},
                {"service_id": "SVC-B", "service_name": "Услуга Б"},
            ],
        )
        self.assertNotIn("service_id", context.user_data["nr"])


# ────────────────────────────────────────────────────────────
# Roadmap active-Service validation — remaining edge cases
# ────────────────────────────────────────────────────────────

def _fresh_bb():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import business_core.business_builder as bb
    return bb


class TestRoadmapServiceStatusValidation(unittest.TestCase):

    def test_draft_service_rejected_no_writes(self):
        bb = _fresh_bb()
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-001", "status": "draft"}), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.sheets.append_business_row") as mock_append:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", service_id="SVC-001",
            )
        self.assertFalse(result["ok"])
        mock_create.assert_not_called()
        mock_append.assert_not_called()

    def test_unknown_status_in_existing_row_rejected(self):
        bb = _fresh_bb()
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-001", "status": "paused"}), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", service_id="SVC-001",
            )
        self.assertFalse(result["ok"])
        mock_create.assert_not_called()

    def test_no_stage_or_extension_writes_on_validation_failure(self):
        bb = _fresh_bb()
        with patch("business_core.service_manager.find_service_by_id", return_value=None), \
             patch("business_core.roadmap_manager.create_roadmap_record") as mock_create, \
             patch("business_core.roadmap_manager.ensure_roadmap_stages") as mock_stages, \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", service_id="SVC-GONE",
            )
        self.assertFalse(result["ok"])
        mock_create.assert_not_called()
        mock_stages.assert_not_called()
        mock_copy.assert_not_called()

    def test_active_service_preserves_convergent_retry(self):
        """Sanity check: with an active Service, the existing convergent-
        retry behavior (reuse existing active Roadmap) is unchanged."""
        bb = _fresh_bb()
        existing_roadmap = {"roadmap_id": "RM-950", "template_id": "", "status": "active"}
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-001", "status": "active"}), \
             patch("business_core.roadmap_manager.find_active_roadmap_for_object",
                   return_value=existing_roadmap), \
             patch("business_core.roadmap_manager.list_roadmaps", return_value=[existing_roadmap]), \
             patch("business_core.roadmap_template_manager.find_template_stages", return_value=[]):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", service_id="SVC-001",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["roadmap_id"], "RM-950")


if __name__ == "__main__":
    unittest.main(verbosity=2)
