"""
Phase 11B: business_core.report_manager — unit tests for pure functions.

collect_snapshot() is the only Sheets-touching function in the module —
it is fully mocked in every test here. All other functions (build_attention,
build_statistics, build_quality, build_progress, render_report) are pure
and tested directly with plain dict/list fixtures, no mocking needed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.report_manager as rm
    return rm


# ─── Fixtures ────────────────────────────────────────────────────────────

def _biz(id_="BIZ-001", status="active"):
    return {"ID": id_, "Название": "Test Biz", "Статус": status}


def _person(id_="PRS-001", type_="клиент"):
    return {"ID": id_, "ФИО": "Test Person", "Тип": type_}


def _object(obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001", roadmap_id=""):
    return {"OBJ ID": obj_id, "Biz ID": biz_id, "Client ID": client_id, "Roadmap ID": roadmap_id}


def _service(id_="SVC-001"):
    return {"ID": id_, "Название": "Test Service", "Бизнес ID": "BIZ-001"}


def _roadmap(rm_id="RM-001", biz_id="BIZ-001", obj_id="OBJ-001", svc_id="SVC-001",
             status="active", template_id="RMT-001", client_name="Test Client"):
    return {
        "Roadmap ID": rm_id, "Business ID": biz_id, "Object ID": obj_id,
        "Service ID": svc_id, "Status": status, "Template ID": template_id,
        "Client Name": client_name,
    }


def _stage(stage_id="STAGE-001-01", roadmap_id="RM-001", status="pending"):
    return {"Stage ID": stage_id, "Roadmap ID": roadmap_id, "Status": status}


def _empty_snapshot():
    return {"biz": [], "people": [], "objects": [], "services": [],
            "roadmaps": [], "stages": [], "errors": {}}


# ─── collect_snapshot() ─────────────────────────────────────────────────

class TestCollectSnapshot(unittest.TestCase):
    """no live API, one read per sheet, per-sheet error isolation."""

    def test_reads_each_sheet_once(self):
        rm = _fresh_import()
        calls = []

        def fake_read(sheet_key):
            calls.append(sheet_key)
            return []

        with patch("business_core.sheets.read_business_sheet", side_effect=fake_read):
            snapshot = rm.collect_snapshot()

        self.assertEqual(
            sorted(calls),
            sorted(["biz_registry", "people_registry", "object_registry",
                     "service_catalog", "roadmaps", "roadmap_stages"]),
        )
        self.assertEqual(len(calls), 6)
        self.assertEqual(snapshot["errors"], {})

    def test_no_live_api_when_mocked(self):
        rm = _fresh_import()
        with patch("business_core.sheets.read_business_sheet", return_value=[]) as mock_read, \
             patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            rm.collect_snapshot()
        self.assertTrue(mock_read.called)
        mock_get_sheet.assert_not_called()

    def test_one_sheet_failure_does_not_break_others(self):
        rm = _fresh_import()

        def fake_read(sheet_key):
            if sheet_key == "roadmaps":
                raise RuntimeError("Sheets API down")
            return [{"ID": "X"}]

        with patch("business_core.sheets.read_business_sheet", side_effect=fake_read):
            snapshot = rm.collect_snapshot()

        self.assertEqual(snapshot["roadmaps"], [])
        self.assertIn("roadmaps", snapshot["errors"])
        self.assertEqual(snapshot["biz"], [{"ID": "X"}])

    def test_import_safety_no_sheets_access_at_import_time(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet, \
             patch("business_core.sheets.read_business_sheet") as mock_read:
            import business_core.report_manager  # noqa: F401
        mock_get_sheet.assert_not_called()
        mock_read.assert_not_called()


# ─── build_attention() ──────────────────────────────────────────────────

class TestBuildAttentionEmpty(unittest.TestCase):
    def test_empty_snapshot_gives_empty_lists(self):
        rm = _fresh_import()
        result = rm.build_attention(_empty_snapshot())
        self.assertEqual(result["orphan_services"], [])
        self.assertEqual(result["roadmaps_without_object"], [])
        self.assertEqual(result["objects_without_roadmap"], [])
        self.assertEqual(result["legacy_stage_statuses"], [])


class TestBuildAttentionOrphanService(unittest.TestCase):
    def test_orphan_service_detected(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", svc_id="SVC-GHOST")]
        snapshot["services"] = [_service(id_="SVC-001")]
        result = rm.build_attention(snapshot)
        self.assertEqual(len(result["orphan_services"]), 1)
        self.assertEqual(result["orphan_services"][0]["roadmap_id"], "RM-001")
        self.assertEqual(result["orphan_services"][0]["service_id"], "SVC-GHOST")

    def test_valid_service_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", svc_id="SVC-001")]
        snapshot["services"] = [_service(id_="SVC-001")]
        result = rm.build_attention(snapshot)
        self.assertEqual(result["orphan_services"], [])

    def test_empty_service_id_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", svc_id="")]
        snapshot["services"] = []
        result = rm.build_attention(snapshot)
        self.assertEqual(result["orphan_services"], [])


class TestBuildAttentionRoadmapWithoutObject(unittest.TestCase):
    def test_object_without_roadmap_detected(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", obj_id="")]
        result = rm.build_attention(snapshot)
        self.assertEqual(len(result["roadmaps_without_object"]), 1)
        self.assertEqual(result["roadmaps_without_object"][0]["roadmap_id"], "RM-001")

    def test_roadmap_with_object_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", obj_id="OBJ-001")]
        result = rm.build_attention(snapshot)
        self.assertEqual(result["roadmaps_without_object"], [])


class TestBuildAttentionObjectWithoutRoadmap(unittest.TestCase):
    def test_object_without_roadmap_id_detected(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["objects"] = [_object(obj_id="OBJ-001", roadmap_id="")]
        result = rm.build_attention(snapshot)
        self.assertEqual(len(result["objects_without_roadmap"]), 1)
        self.assertEqual(result["objects_without_roadmap"][0]["obj_id"], "OBJ-001")

    def test_object_with_roadmap_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["objects"] = [_object(obj_id="OBJ-001", roadmap_id="RM-001")]
        result = rm.build_attention(snapshot)
        self.assertEqual(result["objects_without_roadmap"], [])


class TestBuildAttentionLegacyStatus(unittest.TestCase):
    def test_legacy_status_detected(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["stages"] = [_stage(stage_id="STAGE-1", status="not_started")]
        result = rm.build_attention(snapshot)
        self.assertEqual(len(result["legacy_stage_statuses"]), 1)
        self.assertEqual(result["legacy_stage_statuses"][0]["status"], "not_started")

    def test_canonical_status_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["stages"] = [
            _stage(stage_id=f"STAGE-{s}", status=s)
            for s in ("pending", "in_progress", "blocked", "done", "skipped")
        ]
        result = rm.build_attention(snapshot)
        self.assertEqual(result["legacy_stage_statuses"], [])

    def test_empty_status_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["stages"] = [_stage(stage_id="STAGE-1", status="")]
        result = rm.build_attention(snapshot)
        self.assertEqual(result["legacy_stage_statuses"], [])


class TestBuildAttentionDeterministicOrdering(unittest.TestCase):
    def test_orphan_services_sorted_by_roadmap_id(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [
            _roadmap(rm_id="RM-003", svc_id="SVC-GHOST-3"),
            _roadmap(rm_id="RM-001", svc_id="SVC-GHOST-1"),
            _roadmap(rm_id="RM-002", svc_id="SVC-GHOST-2"),
        ]
        snapshot["services"] = []
        result = rm.build_attention(snapshot)
        ids = [x["roadmap_id"] for x in result["orphan_services"]]
        self.assertEqual(ids, ["RM-001", "RM-002", "RM-003"])

    def test_repeated_calls_give_identical_order(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["stages"] = [
            _stage(stage_id="STAGE-3", status="not_started"),
            _stage(stage_id="STAGE-1", status="waiting"),
            _stage(stage_id="STAGE-2", status="not_started"),
        ]
        r1 = rm.build_attention(snapshot)
        r2 = rm.build_attention(snapshot)
        self.assertEqual(r1["legacy_stage_statuses"], r2["legacy_stage_statuses"])


# ─── build_statistics() ─────────────────────────────────────────────────

class TestBuildStatisticsEmpty(unittest.TestCase):
    def test_empty_snapshot_all_zero(self):
        rm = _fresh_import()
        result = rm.build_statistics(_empty_snapshot())
        self.assertEqual(result["business_count"], 0)
        self.assertEqual(result["active_business_count"], 0)
        self.assertEqual(result["client_count"], 0)
        self.assertEqual(result["object_count"], 0)
        self.assertEqual(result["roadmap_count"], 0)
        self.assertEqual(result["active_roadmap_count"], 0)
        self.assertEqual(result["stage_count"], 0)


class TestBuildStatisticsOneBusiness(unittest.TestCase):
    def test_one_business_counts(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["biz"] = [_biz(id_="BIZ-001", status="active")]
        snapshot["people"] = [_person(id_="PRS-001", type_="клиент")]
        snapshot["objects"] = [_object()]
        snapshot["roadmaps"] = [_roadmap(status="active")]
        snapshot["stages"] = [_stage(), _stage(stage_id="STAGE-2")]
        result = rm.build_statistics(snapshot)
        self.assertEqual(result["business_count"], 1)
        self.assertEqual(result["active_business_count"], 1)
        self.assertEqual(result["client_count"], 1)
        self.assertEqual(result["object_count"], 1)
        self.assertEqual(result["roadmap_count"], 1)
        self.assertEqual(result["active_roadmap_count"], 1)
        self.assertEqual(result["stage_count"], 2)


class TestBuildStatisticsMultipleBusinesses(unittest.TestCase):
    def test_multiple_businesses_mixed_status(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["biz"] = [
            _biz(id_="BIZ-001", status="active"),
            _biz(id_="BIZ-002", status="test"),
            _biz(id_="BIZ-003", status="active"),
        ]
        snapshot["roadmaps"] = [
            _roadmap(rm_id="RM-001", status="active"),
            _roadmap(rm_id="RM-002", status="completed"),
        ]
        result = rm.build_statistics(snapshot)
        self.assertEqual(result["business_count"], 3)
        self.assertEqual(result["active_business_count"], 2)
        self.assertEqual(result["roadmap_count"], 2)
        self.assertEqual(result["active_roadmap_count"], 1)

    def test_non_client_people_excluded(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["people"] = [
            _person(id_="PRS-001", type_="клиент"),
            _person(id_="PRS-002", type_="партнёр"),
        ]
        result = rm.build_statistics(snapshot)
        self.assertEqual(result["client_count"], 1)


# ─── build_quality() ─────────────────────────────────────────────────────

class TestBuildQuality(unittest.TestCase):
    def test_empty_snapshot(self):
        rm = _fresh_import()
        result = rm.build_quality(_empty_snapshot())
        self.assertEqual(result["orphan_ids"], [])
        self.assertEqual(result["legacy_statuses"], [])
        self.assertEqual(result["missing_template"], [])
        self.assertEqual(result["missing_object"], [])

    def test_missing_template_detected(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", template_id="")]
        result = rm.build_quality(snapshot)
        self.assertEqual(len(result["missing_template"]), 1)
        self.assertEqual(result["missing_template"][0]["roadmap_id"], "RM-001")

    def test_template_present_not_flagged(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", template_id="RMT-001")]
        result = rm.build_quality(snapshot)
        self.assertEqual(result["missing_template"], [])

    def test_quality_consistent_with_attention(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001", svc_id="SVC-GHOST", obj_id="")]
        snapshot["services"] = []
        snapshot["stages"] = [_stage(status="not_started")]
        attention = rm.build_attention(snapshot)
        quality = rm.build_quality(snapshot)
        self.assertEqual(quality["orphan_ids"], attention["orphan_services"])
        self.assertEqual(quality["legacy_statuses"], attention["legacy_stage_statuses"])
        self.assertEqual(quality["missing_object"], attention["roadmaps_without_object"])


# ─── build_progress() ────────────────────────────────────────────────────

class TestBuildProgressEmpty(unittest.TestCase):
    def test_empty_snapshot_zero_average(self):
        rm = _fresh_import()
        result = rm.build_progress(_empty_snapshot())
        self.assertEqual(result["average_progress"], 0)
        self.assertEqual(result["roadmap_progress_map"], {})


class TestBuildProgressCalculation(unittest.TestCase):
    def test_recomputes_from_stages_not_stored_percent(self):
        """Stored 'Progress %' (if it existed on the roadmap dict) must be
        ignored — progress is recomputed purely from stage statuses."""
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        roadmap = _roadmap(rm_id="RM-001")
        roadmap["Progress %"] = "0"  # stale stored value
        snapshot["roadmaps"] = [roadmap]
        snapshot["stages"] = [
            _stage(stage_id="S1", roadmap_id="RM-001", status="done"),
            _stage(stage_id="S2", roadmap_id="RM-001", status="pending"),
        ]
        result = rm.build_progress(snapshot)
        # 1 of 2 done -> 50%, NOT the stale stored "0"
        self.assertEqual(result["roadmap_progress_map"]["RM-001"], 50)

    def test_skipped_counts_as_done(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001")]
        snapshot["stages"] = [
            _stage(stage_id="S1", roadmap_id="RM-001", status="skipped"),
            _stage(stage_id="S2", roadmap_id="RM-001", status="done"),
        ]
        result = rm.build_progress(snapshot)
        self.assertEqual(result["roadmap_progress_map"]["RM-001"], 100)

    def test_roadmap_with_no_stages_is_zero(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001")]
        snapshot["stages"] = []
        result = rm.build_progress(snapshot)
        self.assertEqual(result["roadmap_progress_map"]["RM-001"], 0)

    def test_average_progress_across_multiple_roadmaps(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["roadmaps"] = [_roadmap(rm_id="RM-001"), _roadmap(rm_id="RM-002")]
        snapshot["stages"] = [
            _stage(stage_id="S1", roadmap_id="RM-001", status="done"),
            _stage(stage_id="S2", roadmap_id="RM-002", status="pending"),
        ]
        result = rm.build_progress(snapshot)
        # RM-001: 100%, RM-002: 0% -> average 50%
        self.assertEqual(result["average_progress"], 50)


# ─── render_report() ─────────────────────────────────────────────────────

class TestRenderReport(unittest.TestCase):
    def test_renders_all_four_sections(self):
        rm = _fresh_import()
        attention = rm.build_attention(_empty_snapshot())
        statistics = rm.build_statistics(_empty_snapshot())
        quality = rm.build_quality(_empty_snapshot())
        progress = rm.build_progress(_empty_snapshot())

        text = rm.render_report(attention, statistics, quality, progress)

        self.assertIn("Требует внимания", text)
        self.assertIn("Статистика", text)
        self.assertIn("Качество данных", text)
        self.assertIn("Прогресс", text)

    def test_returns_plain_string_not_telegram_object(self):
        rm = _fresh_import()
        text = rm.render_report(
            rm.build_attention(_empty_snapshot()),
            rm.build_statistics(_empty_snapshot()),
            rm.build_quality(_empty_snapshot()),
            rm.build_progress(_empty_snapshot()),
        )
        self.assertIsInstance(text, str)

    def test_shows_snapshot_errors_when_present(self):
        rm = _fresh_import()
        text = rm.render_report(
            rm.build_attention(_empty_snapshot()),
            rm.build_statistics(_empty_snapshot()),
            rm.build_quality(_empty_snapshot()),
            rm.build_progress(_empty_snapshot()),
            snapshot_errors={"roadmaps": "Sheets API down"},
        )
        self.assertIn("roadmaps", text)
        self.assertIn("Sheets API down", text)

    def test_reflects_actual_counts(self):
        rm = _fresh_import()
        snapshot = _empty_snapshot()
        snapshot["biz"] = [_biz(id_="BIZ-001")]
        statistics = rm.build_statistics(snapshot)
        text = rm.render_report(
            rm.build_attention(snapshot), statistics,
            rm.build_quality(snapshot), rm.build_progress(snapshot),
        )
        self.assertIn("1 всего", text)


if __name__ == "__main__":
    unittest.main()
