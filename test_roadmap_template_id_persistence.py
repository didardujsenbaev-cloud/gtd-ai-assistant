"""
Regression tests for the RM-022 / RM-026 template_id bug.

Bug: explicit template_id chosen in /startroadmap (e.g. RMT-IZH-ALM-STANDARD-002)
was never persisted, so /milestones later re-derived template_id via
_resolve_template_id() heuristics and picked the wrong template
(first template linked to the service, e.g. RMT-IZH-ALM-LEGALIZATION-001).

Covers:
1. create_roadmap_for_object() записывает template_id в строку ROADMAPS.
2. find_roadmap_by_id() читает template_id обратно.
3. _resolve_template_id() приоритет: сохранённый template_id > notes > default > first-linked.
4. End-to-end: /startroadmap с explicit template_id -> /milestones видит тот же template_id.
5. Обратная совместимость: старые roadmap без template_id резолвятся как раньше.
6. ensure_roadmap_template_id_column() идемпотентна и не трогает существующие данные.
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


def _fresh_bb():
    return _fresh("business_core.business_builder")


def _fresh_rm():
    return _fresh("business_core.roadmap_manager")


def _fresh_th():
    return _fresh("business_core.telegram_handlers")


def _fresh_sheets():
    return _fresh("business_core.sheets")


def _make_update(text: str, args_list: list[str]):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args_list
    return update, context


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


FAKE_STAGES = [
    {"stage_id": f"STG-{i:03d}", "roadmap_id": "RM-300",
     "order": str(i), "name": f"Stage {i}", "status": "pending",
     "due_date": "", "notes": ""}
    for i in range(1, 14)
]


# ────────────────────────────────────────────────────────────
# 1. create_roadmap_for_object() записывает template_id
# ────────────────────────────────────────────────────────────

CANONICAL_ROADMAPS_HEADERS = [
    "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
    "Client Name", "GTD Project ID", "Responsible", "Status",
    "Created", "Expected", "Progress %",
    "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
    "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
    "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
    "Stage 10 Status", "Notes", "Last Updated",
    "Object ID", "Parent Roadmap ID", "Case Type", "Template ID",
]


class TestTemplateIdWrite(unittest.TestCase):
    """create_roadmap_for_object должен писать по фактическим именам
    заголовков листа, а не по жёсткой позиции (см. регрессию RM-027)."""

    def _fake_sheet(self, headers: list[str]):
        sheet = MagicMock()
        sheet.row_values.return_value = list(headers)
        return sheet

    def test_1_template_id_written_under_correct_header_name(self):
        bb = _fresh_bb()
        rows = []
        sheet = self._fake_sheet(CANONICAL_ROADMAPS_HEADERS)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: rows.append((k, r))), \
             patch.object(bb, "generate_roadmap_id", return_value="RM-500"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-IZH-001", case_type="legalization",
                template_id="RMT-IZH-ALM-STANDARD-002",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["roadmap_id"], "RM-500")

        self.assertEqual(len(rows), 1)
        sheet_key, row = rows[0]
        self.assertEqual(sheet_key, "roadmaps")
        idx = {h: i for i, h in enumerate(CANONICAL_ROADMAPS_HEADERS)}
        self.assertEqual(row[idx["Template ID"]], "RMT-IZH-ALM-STANDARD-002")
        self.assertEqual(row[idx["Case Type"]], "legalization")
        self.assertEqual(row[idx["Object ID"]], "OBJ-001",
                         "Object ID должен попасть именно под колонку Object ID, "
                         "а не под Template ID (регрессия RM-027)")

    def test_1_header_order_may_differ_write_still_correct(self):
        """Порядок заголовков в живом листе может отличаться от канонического —
        запись всё равно должна попасть в правильные колонки по имени."""
        bb = _fresh_bb()
        rows = []
        shuffled = [
            "Roadmap ID", "Template ID", "Business ID", "Service ID", "City",
            "Client ID", "Client Name", "GTD Project ID", "Responsible",
            "Status", "Created", "Expected", "Progress %",
            "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
            "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
            "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
            "Stage 10 Status", "Notes", "Last Updated",
            "Case Type", "Object ID", "Parent Roadmap ID",
        ]
        sheet = self._fake_sheet(shuffled)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: rows.append((k, r))), \
             patch.object(bb, "generate_roadmap_id", return_value="RM-503"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-009", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-IZH-001", case_type="general",
                template_id="RMT-IZH-ALM-STANDARD-002",
            )

        self.assertTrue(result["ok"])
        row = rows[0][1]
        idx = {h: i for i, h in enumerate(shuffled)}
        self.assertEqual(row[idx["Template ID"]], "RMT-IZH-ALM-STANDARD-002")
        self.assertEqual(row[idx["Object ID"]], "OBJ-009")
        self.assertEqual(row[idx["Case Type"]], "general")
        self.assertEqual(row[idx["Parent Roadmap ID"]], "")

    def test_1_empty_template_id_writes_empty_string(self):
        """Без template_id (старый вызов /startroadmap без явного шаблона) — пустая строка, не падает."""
        bb = _fresh_bb()
        rows = []
        sheet = self._fake_sheet(CANONICAL_ROADMAPS_HEADERS)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: rows.append((k, r))), \
             patch.object(bb, "generate_roadmap_id", return_value="RM-501"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-002", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-IZH-001",
            )

        self.assertTrue(result["ok"])
        idx = {h: i for i, h in enumerate(CANONICAL_ROADMAPS_HEADERS)}
        self.assertEqual(rows[0][1][idx["Template ID"]], "")

    def test_1_missing_header_returns_clear_error_no_write(self):
        """Если в живом листе нет нужной колонки (например Template ID ещё
        не мигрирован) — понятная ошибка, а не запись в чужую позицию."""
        bb = _fresh_bb()
        rows = []
        # Лист без Object ID / Parent Roadmap ID / Case Type / Template ID —
        # ровно та ситуация, что была в проде до миграции.
        old_headers = CANONICAL_ROADMAPS_HEADERS[:24]  # только до "Last Updated"
        sheet = self._fake_sheet(old_headers)

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: rows.append((k, r))), \
             patch.object(bb, "generate_roadmap_id", return_value="RM-504"):
            result = bb.create_roadmap_for_object(
                obj_id="OBJ-010", biz_id="BIZ-001", client_id="PRS-001",
                service_id="SVC-IZH-001", template_id="RMT-X",
            )

        self.assertFalse(result["ok"])
        self.assertIn("Object ID", result["error"])
        self.assertIn("Template ID", result["error"])
        self.assertEqual(rows, [], "при отсутствующих колонках запись не должна происходить вовсе")


# ────────────────────────────────────────────────────────────
# 2. find_roadmap_by_id() читает template_id
# ────────────────────────────────────────────────────────────

class TestTemplateIdRead(unittest.TestCase):

    def _fake_sheet(self, headers: list[str], row: list[str]):
        sheet = MagicMock()
        cell = MagicMock()
        cell.row = 2
        sheet.find.return_value = cell
        sheet.row_values.side_effect = lambda r: headers if r == 1 else row
        return sheet

    def test_2_reads_template_id_when_column_present(self):
        bb = _fresh_bb()
        sheets_mod = _fresh_sheets()
        headers = list(sheets_mod.BUSINESS_HEADERS["roadmaps"])
        self.assertIn("Template ID", headers)

        row = [""] * len(headers)
        row[headers.index("Roadmap ID")] = "RM-022"
        row[headers.index("Service ID")] = "SVC-IZH-001"
        row[headers.index("Case Type")] = "legalization"
        row[headers.index("Template ID")] = "RMT-IZH-ALM-STANDARD-002"

        sheet = self._fake_sheet(headers, row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = bb.find_roadmap_by_id("RM-022")

        self.assertIsNotNone(result)
        self.assertEqual(result["template_id"], "RMT-IZH-ALM-STANDARD-002")

    def test_2_missing_column_returns_empty_string(self):
        """Старый лист без колонки Template ID — не крашится, вернёт ''."""
        bb = _fresh_bb()
        old_headers = [
            "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
            "Client Name", "GTD Project ID", "Responsible", "Status",
            "Created", "Expected", "Progress %",
            "Stage 1 Status", "Stage 2 Status", "Stage 3 Status",
            "Stage 4 Status", "Stage 5 Status", "Stage 6 Status",
            "Stage 7 Status", "Stage 8 Status", "Stage 9 Status",
            "Stage 10 Status", "Notes", "Last Updated",
            "Object ID", "Parent Roadmap ID", "Case Type",
        ]
        row = [""] * len(old_headers)
        row[0] = "RM-026"
        row[old_headers.index("Case Type")] = "legalization"

        sheet = self._fake_sheet(old_headers, row)
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = bb.find_roadmap_by_id("RM-026")

        self.assertIsNotNone(result)
        self.assertEqual(result["template_id"], "")


# ────────────────────────────────────────────────────────────
# 3. _resolve_template_id: приоритет сохранённого значения
# ────────────────────────────────────────────────────────────

class TestResolveTemplateIdPriority(unittest.TestCase):

    def test_3_saved_template_id_wins_over_notes_and_service_default(self):
        rm = _fresh_rm()
        roadmap = {
            "template_id": "RMT-IZH-ALM-STANDARD-002",
            "notes": "template_id=RMT-IZH-ALM-LEGALIZATION-001",
            "service_id": "SVC-IZH-001",
        }
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-IZH-001",
                                 "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}):
            tid = rm._resolve_template_id(roadmap)

        self.assertEqual(tid, "RMT-IZH-ALM-STANDARD-002")

    def test_3_saved_template_id_wins_over_first_linked_template(self):
        rm = _fresh_rm()
        roadmap = {"template_id": "RMT-IZH-ALM-STANDARD-002", "service_id": "SVC-IZH-001", "notes": ""}

        with patch("business_core.service_manager.find_service_by_id", return_value=None), \
             patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                   return_value=[
                       {"template_id": "RMT-IZH-ALM-LEGALIZATION-001", "service_id": "SVC-IZH-001"},
                       {"template_id": "RMT-IZH-ALM-STANDARD-002", "service_id": "SVC-IZH-001"},
                   ]):
            tid = rm._resolve_template_id(roadmap)

        self.assertEqual(tid, "RMT-IZH-ALM-STANDARD-002")

    def test_3_blank_saved_template_id_falls_back(self):
        """Пустая строка в template_id (не отсутствие ключа) тоже не должна ломать fallback."""
        rm = _fresh_rm()
        roadmap = {"template_id": "  ", "service_id": "SVC-IZH-001", "notes": ""}

        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-IZH-001",
                                 "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}):
            tid = rm._resolve_template_id(roadmap)

        self.assertEqual(tid, "RMT-IZH-ALM-LEGALIZATION-001")


# ────────────────────────────────────────────────────────────
# 4. End-to-end: /startroadmap explicit template_id -> /milestones
# ────────────────────────────────────────────────────────────

class TestEndToEndStartroadmapToMilestones(unittest.TestCase):

    def test_4_explicit_template_id_survives_to_milestones(self):
        # ВАЖНО: только один _fresh(...) в этом тесте. _fresh() удаляет из
        # sys.modules все "business_core.*", поэтому второй вызов после
        # `th = _fresh_th()` инвалидирует уже импортированный th-модуль,
        # и патчи `business_core.telegram_handlers.*` перестают действовать
        # на функцию, которую мы реально вызываем.
        th = _fresh_th()
        import business_core.roadmap_manager as rm

        captured = {}

        def fake_create_roadmap(**kwargs):
            captured["template_id"] = kwargs.get("template_id", "")
            return {"ok": True, "roadmap_id": "RM-300", "error": None}

        stages_calls = []

        def mock_stages(roadmap_id, template_id):
            stages_calls.append(template_id)
            return {"ok": True, "stages_count": 13, "warning": None, "stage_ids": []}

        # Реестр шаблонов услуги: LEGALIZATION-001 идёт первым в листе —
        # именно это раньше приводило к неверному резолву в /milestones.
        linked_templates = [
            {"template_id": "RMT-IZH-ALM-LEGALIZATION-001",
             "service_id": "SVC-IZH-001", "template_name": "Легализация"},
            {"template_id": "RMT-IZH-ALM-STANDARD-002",
             "service_id": "SVC-IZH-001", "template_name": "Обычный путь / с законченными СМР"},
        ]

        upd, ctx = _make_update(
            "/startroadmap obj_id=OBJ-001 service_id=SVC-IZH-001 template_id=RMT-IZH-ALM-STANDARD-002",
            ["obj_id=OBJ-001", "service_id=SVC-IZH-001", "template_id=RMT-IZH-ALM-STANDARD-002"],
        )

        async def run_startroadmap():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.find_object_by_id",
                       return_value={"obj_id": "OBJ-001", "biz_id": "BIZ-001", "client_id": "PRS-001"}), \
                 patch("business_core.business_builder.create_roadmap_for_object",
                       side_effect=fake_create_roadmap), \
                 patch("business_core.business_builder.update_object_roadmap_id"), \
                 patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
                       return_value={"template_id": "RMT-IZH-ALM-STANDARD-002",
                                     "service_id": "SVC-IZH-001",
                                     "template_name": "Обычный путь / с законченными СМР"}), \
                 patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
                       return_value=linked_templates), \
                 patch("business_core.service_manager.find_service_by_id",
                       return_value={"service_id": "SVC-IZH-001",
                                     "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}), \
                 patch("business_core.roadmap_template_manager.create_stages_from_template_record",
                       side_effect=mock_stages), \
                 patch("business_core.roadmap_manager.create_roadmap_stages_from_template",
                       return_value={"stages_count": 0}):
                await th.startroadmap_cmd(upd, ctx)

        _run(run_startroadmap())

        self.assertEqual(captured.get("template_id"), "RMT-IZH-ALM-STANDARD-002",
                         "startroadmap_cmd должен передавать явный template_id в create_roadmap_for_object")
        self.assertEqual(stages_calls, ["RMT-IZH-ALM-STANDARD-002"])

        # ── Roadmap теперь "существует" с тем template_id, что реально сохранился ──
        persisted_roadmap = {
            "roadmap_id": "RM-300", "biz_id": "BIZ-001", "service_id": "SVC-IZH-001",
            "client_id": "PRS-001", "title": "Roadmap OBJ-001", "status": "active",
            "created": "2026-07-16", "obj_id": "OBJ-001", "case_type": "general",
            "notes": "", "progress": "0",
            "template_id": captured["template_id"],
        }

        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=persisted_roadmap), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap",
                   return_value=FAKE_STAGES):
            data = rm.get_commercial_milestones_for_roadmap("RM-300")

        self.assertEqual(data["template_id"], "RMT-IZH-ALM-STANDARD-002")
        self.assertNotEqual(data["template_id"], "RMT-IZH-ALM-LEGALIZATION-001",
                            "Regression: /milestones не должен подменять явно выбранный шаблон")


# ────────────────────────────────────────────────────────────
# 5. Обратная совместимость для старых roadmap без template_id
# ────────────────────────────────────────────────────────────

class TestBackwardCompatibilityOldRoadmaps(unittest.TestCase):

    def test_5_old_roadmap_without_template_id_uses_notes_fallback(self):
        rm = _fresh_rm()
        old_roadmap = {
            "roadmap_id": "RM-022",
            "service_id": "SVC-IZH-001",
            "notes": "template_id=RMT-IZH-ALM-STANDARD-002 (создан вручную до фикса)",
            # ключа "template_id" нет вовсе — как из старого листа без колонки
        }
        tid = rm._resolve_template_id(old_roadmap)
        self.assertEqual(tid, "RMT-IZH-ALM-STANDARD-002")

    def test_5_old_roadmap_without_notes_uses_service_default(self):
        rm = _fresh_rm()
        old_roadmap = {"roadmap_id": "RM-026", "service_id": "SVC-IZH-001", "notes": ""}
        with patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-IZH-001",
                                 "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}):
            tid = rm._resolve_template_id(old_roadmap)
        self.assertEqual(tid, "RMT-IZH-ALM-LEGALIZATION-001")

    def test_5_get_commercial_milestones_works_for_roadmap_missing_template_key(self):
        """find_roadmap_by_id может вернуть dict вовсе без ключа template_id —
        get_commercial_milestones_for_roadmap не должен падать."""
        rm = _fresh_rm()
        old_roadmap = {
            "roadmap_id": "RM-022", "service_id": "SVC-IZH-001",
            "notes": "", "case_type": "legalization",
        }
        with patch("business_core.business_builder.find_roadmap_by_id",
                   return_value=old_roadmap), \
             patch("business_core.service_manager.find_service_by_id",
                   return_value={"service_id": "SVC-IZH-001",
                                 "default_roadmap_template_id": "RMT-IZH-ALM-LEGALIZATION-001"}), \
             patch("business_core.roadmap_manager.get_stages_for_roadmap", return_value=[]):
            data = rm.get_commercial_milestones_for_roadmap("RM-022")

        self.assertTrue(data["ok"])
        self.assertEqual(data["template_id"], "RMT-IZH-ALM-LEGALIZATION-001")


# ────────────────────────────────────────────────────────────
# 6. ensure_roadmap_template_id_column() идемпотентность
# ────────────────────────────────────────────────────────────

class TestEnsureRoadmapTemplateIdColumnIdempotent(unittest.TestCase):

    def test_6_adds_column_when_missing(self):
        sheets_mod = _fresh_sheets()
        sheet = MagicMock()
        sheet.row_values.return_value = [
            "Roadmap ID", "Business ID", "Service ID", "City", "Client ID",
            "Case Type",
        ]

        with patch.object(sheets_mod, "get_business_sheet", return_value=sheet):
            ok = sheets_mod.ensure_roadmap_template_id_column()

        self.assertTrue(ok)
        sheet.update_cell.assert_called_once_with(1, 7, "Template ID")

    def test_6_noop_when_column_already_present(self):
        sheets_mod = _fresh_sheets()
        sheet = MagicMock()
        sheet.row_values.return_value = [
            "Roadmap ID", "Business ID", "Case Type", "Template ID",
        ]

        with patch.object(sheets_mod, "get_business_sheet", return_value=sheet):
            ok = sheets_mod.ensure_roadmap_template_id_column()

        self.assertTrue(ok)
        sheet.update_cell.assert_not_called()

    def test_6_repeated_calls_do_not_duplicate_column(self):
        sheets_mod = _fresh_sheets()
        sheet = MagicMock()
        state = {"headers": ["Roadmap ID", "Case Type"]}

        def fake_update_cell(row, col, value):
            state["headers"].append(value)

        sheet.row_values.side_effect = lambda r: list(state["headers"])
        sheet.update_cell.side_effect = fake_update_cell

        with patch.object(sheets_mod, "get_business_sheet", return_value=sheet):
            sheets_mod.ensure_roadmap_template_id_column()
            sheets_mod.ensure_roadmap_template_id_column()
            sheets_mod.ensure_roadmap_template_id_column()

        self.assertEqual(state["headers"].count("Template ID"), 1)
        self.assertEqual(sheet.update_cell.call_count, 1)

    def test_6_does_not_touch_existing_rows_or_other_columns(self):
        """Только row_values(1) для чтения заголовков и точечный update_cell(1, N, ...) —
        никаких сброса/перезаписи диапазонов, никакого чтения/удаления строк данных."""
        sheets_mod = _fresh_sheets()
        sheet = MagicMock()
        sheet.row_values.return_value = ["Roadmap ID", "Case Type"]

        with patch.object(sheets_mod, "get_business_sheet", return_value=sheet):
            sheets_mod.ensure_roadmap_template_id_column()

        sheet.row_values.assert_called_once_with(1)
        sheet.update.assert_not_called()
        sheet.clear.assert_not_called()
        sheet.delete_rows.assert_not_called()
        sheet.get_all_values.assert_not_called()

    def test_6_failure_is_caught_and_returns_false(self):
        """Ошибка Sheets API не должна поднимать исключение наружу."""
        sheets_mod = _fresh_sheets()
        with patch.object(sheets_mod, "get_business_sheet", side_effect=Exception("API down")):
            ok = sheets_mod.ensure_roadmap_template_id_column()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
