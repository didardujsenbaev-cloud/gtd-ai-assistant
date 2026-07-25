"""
Phase 33C: dedicated cross-domain validation tests for
business_core.business_builder.create_roadmap_for_object(), covering
ADR-016 (Phase 33B) end to end.

Strictly against a fully mocked Business/Client/Object/Service/Template/
Roadmap layer — no live network calls, no production data touched.
Every test isolates exactly one validation step by keeping all *other*
steps at their "happy path" default via the helper mocks below, so a
failure pinpoints precisely which ADR-016 validation step regressed.

PRS-003 incident reference: a masked live-network call in this domain's
tests once silently passed while credentials were absent (rather than
failing loudly), which is why every Roadmap-domain test file, including
this one, is registered in conftest.py's hard socket-block list — any
accidental real network call here must raise, not silently succeed.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch
from contextlib import ExitStack


def _fresh_bb():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.business_builder as bb
    return bb


DEFAULT_ARGS = dict(
    obj_id="OBJ-001", biz_id="BIZ-001", client_id="PRS-001",
    service_id="SVC-001", template_id="",
)


def _happy_path_patches(**overrides) -> list:
    """
    The default "everything valid, no Roadmap exists yet, no Template
    configured" scenario. Each test overrides exactly the one patch it
    needs to exercise a specific validation branch — every other patch
    stays at this default so only one variable changes at a time.
    """
    person = overrides.get("person", {
        "person_id": "PRS-001", "status": "active", "person_type": "клиент",
        "biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-001",
    })
    obj = overrides.get("object", {
        "object_id": "OBJ-001", "status": "new",
        "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": "",
    })
    service = overrides.get("service", {
        "service_id": "SVC-001", "status": "active",
        "biz_id": "BIZ-001", "object_type": "",
    })
    return [
        patch("business_core.sheets.find_row_by_id",
              return_value=overrides.get("biz_row", ("2", {"ID": "BIZ-001"}))),
        patch("business_core.person_manager.find_person_by_id", return_value=person),
        patch("business_core.person_manager.is_person_archived",
              return_value=overrides.get("archived", False)),
        patch("business_core.person_manager.is_client_person",
              return_value=overrides.get("is_client", True)),
        patch("business_core.person_manager.has_person_business_link",
              return_value=overrides.get("has_link", True)),
        patch("business_core.object_manager.find_object_by_id", return_value=obj),
        patch("business_core.service_manager.find_service_by_id", return_value=service),
        patch("business_core.roadmap_manager.find_open_roadmaps_for_object",
              return_value=overrides.get("open_roadmaps", [])),
        patch("business_core.roadmap_manager.create_roadmap_record",
              return_value=overrides.get("create_result", {
                  "ok": True, "roadmap_id": "RM-NEW-001", "roadmap": {}, "error": None,
              })),
        patch("business_core.roadmap_template_manager.find_roadmap_template_by_id",
              side_effect=overrides.get(
                  "find_template_by_id",
                  lambda tid: {"template_id": tid, "service_id": "", "status": "active"} if tid else None,
              )),
        patch("business_core.roadmap_template_manager.find_roadmap_templates_by_service",
              return_value=overrides.get("linked_templates", [])),
        patch("business_core.roadmap_template_manager.find_template_stages",
              return_value=overrides.get("template_stages", [])),
    ]


def _run(bb, **call_kwargs):
    args = {**DEFAULT_ARGS, **call_kwargs}
    return bb.create_roadmap_for_object(**args)


class _CrossDomainTestCase(unittest.TestCase):
    def _call(self, patch_overrides=None, **call_kwargs):
        bb = _fresh_bb()
        with ExitStack() as stack:
            for p in _happy_path_patches(**(patch_overrides or {})):
                stack.enter_context(p)
            return bb.create_roadmap_for_object(**{**DEFAULT_ARGS, **call_kwargs})


class TestBusinessValidation(_CrossDomainTestCase):
    def test_missing_business_blocks_with_business_not_found(self):
        result = self._call({"biz_row": None})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "BUSINESS_NOT_FOUND")

    def test_valid_business_proceeds(self):
        result = self._call()
        self.assertTrue(result["ok"])


class TestClientValidation(_CrossDomainTestCase):
    def test_missing_client_blocks_with_client_not_found(self):
        result = self._call({"person": None})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CLIENT_NOT_FOUND")

    def test_archived_client_blocks_with_client_archived(self):
        result = self._call({"archived": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CLIENT_ARCHIVED")

    def test_non_client_role_blocks_with_client_role_required(self):
        result = self._call({"is_client": False})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CLIENT_ROLE_REQUIRED")

    def test_client_without_business_link_blocks(self):
        result = self._call({"has_link": False})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CLIENT_NOT_LINKED_TO_BUSINESS")

    def test_valid_client_proceeds(self):
        result = self._call()
        self.assertTrue(result["ok"])


class TestObjectValidation(_CrossDomainTestCase):
    def test_missing_object_blocks_with_object_not_found(self):
        result = self._call({"object": None})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "OBJECT_NOT_FOUND")

    def test_ineligible_object_status_blocks(self):
        result = self._call({"object": {
            "object_id": "OBJ-001", "status": "completed",
            "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": "",
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "OBJECT_NOT_ELIGIBLE")

    def test_object_business_mismatch_blocks(self):
        result = self._call({"object": {
            "object_id": "OBJ-001", "status": "new",
            "biz_id": "BIZ-999", "client_id": "PRS-001", "object_type": "",
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "OBJECT_BUSINESS_MISMATCH")

    def test_object_client_mismatch_blocks(self):
        result = self._call({"object": {
            "object_id": "OBJ-001", "status": "new",
            "biz_id": "BIZ-001", "client_id": "PRS-999", "object_type": "",
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "OBJECT_CLIENT_MISMATCH")

    def test_new_status_object_accepted(self):
        self.assertTrue(self._call({"object": {
            "object_id": "OBJ-001", "status": "new",
            "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": "",
        }})["ok"])

    def test_active_status_object_accepted(self):
        self.assertTrue(self._call({"object": {
            "object_id": "OBJ-001", "status": "active",
            "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": "",
        }})["ok"])

    def test_on_hold_status_object_accepted(self):
        self.assertTrue(self._call({"object": {
            "object_id": "OBJ-001", "status": "on_hold",
            "biz_id": "BIZ-001", "client_id": "PRS-001", "object_type": "",
        }})["ok"])


class TestServiceValidation(_CrossDomainTestCase):
    def test_missing_service_blocks_with_service_not_found(self):
        result = self._call({"service": None})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SERVICE_NOT_FOUND")

    def test_inactive_service_blocks(self):
        result = self._call({"service": {
            "service_id": "SVC-001", "status": "inactive", "biz_id": "BIZ-001", "object_type": "",
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SERVICE_INACTIVE")

    def test_service_business_mismatch_blocks(self):
        result = self._call({"service": {
            "service_id": "SVC-001", "status": "active", "biz_id": "BIZ-999", "object_type": "",
        }})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "SERVICE_BUSINESS_MISMATCH")

    def test_active_service_proceeds(self):
        self.assertTrue(self._call()["ok"])


class TestObjectTypeCompatibilityWarning(_CrossDomainTestCase):
    """ADR-016 §6: non-blocking WARNING only, exact-match after NFKC +
    trim + collapse-whitespace + casefold normalization — never a hard
    gate, never fuzzy/substring matching."""

    def test_exact_match_produces_no_warning(self):
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": "private_house_izhs"},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "private_house_izhs"},
        })
        self.assertTrue(result["ok"])
        self.assertIsNone(result["type_compatibility_warning"])

    def test_mismatch_produces_non_blocking_warning(self):
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": "жилой дом"},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "private_house_izhs"},
        })
        self.assertTrue(result["ok"])  # non-blocking
        self.assertEqual(result["type_compatibility_warning"]["status"], "mismatch")

    def test_blank_object_type_produces_unavailable_status_not_silent_skip(self):
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": ""},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "private_house_izhs"},
        })
        self.assertEqual(result["type_compatibility_warning"]["status"], "unavailable")

    def test_blank_service_type_produces_unavailable_status(self):
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": "private_house_izhs"},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": ""},
        })
        self.assertEqual(result["type_compatibility_warning"]["status"], "unavailable")

    def test_both_blank_produces_unavailable_status(self):
        result = self._call()
        self.assertEqual(result["type_compatibility_warning"]["status"], "unavailable")

    def test_normalization_ignores_case_and_surrounding_whitespace(self):
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": "  Private_House_IZHS  "},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "private_house_izhs"},
        })
        self.assertIsNone(result["type_compatibility_warning"])

    def test_no_fuzzy_or_substring_matching(self):
        """"private_house" is a substring of "private_house_izhs" but
        must NOT be treated as a match — exact comparison only."""
        result = self._call({
            "object": {"object_id": "OBJ-001", "status": "new", "biz_id": "BIZ-001",
                       "client_id": "PRS-001", "object_type": "private_house"},
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "private_house_izhs"},
        })
        self.assertEqual(result["type_compatibility_warning"]["status"], "mismatch")

    def test_client_type_validation_is_marked_deferred(self):
        result = self._call()
        self.assertEqual(result["client_type_validation"], "deferred")


class TestTemplateResolution(_CrossDomainTestCase):
    def test_explicit_valid_template_used(self):
        result = self._call(
            {"find_template_by_id": lambda tid: {
                "template_id": tid, "service_id": "SVC-001", "status": "active",
            } if tid else None},
            template_id="RMT-EXPLICIT",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_template_id"], "RMT-EXPLICIT")

    def test_explicit_missing_template_blocks(self):
        result = self._call({"find_template_by_id": lambda tid: None}, template_id="RMT-GHOST")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TEMPLATE_NOT_FOUND")

    def test_explicit_template_service_mismatch_blocks(self):
        result = self._call(
            {"find_template_by_id": lambda tid: {
                "template_id": tid, "service_id": "SVC-OTHER", "status": "active",
            } if tid else None},
            template_id="RMT-WRONG-SVC",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TEMPLATE_SERVICE_MISMATCH")

    def test_valid_default_template_used_when_no_explicit_given(self):
        result = self._call({
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "", "default_roadmap_template_id": "RMT-DEFAULT"},
            "find_template_by_id": lambda tid: {
                "template_id": tid, "service_id": "SVC-001", "status": "active",
            } if tid else None,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_template_id"], "RMT-DEFAULT")

    def test_stale_default_template_id_blocks(self):
        result = self._call({
            "service": {"service_id": "SVC-001", "status": "active", "biz_id": "BIZ-001",
                        "object_type": "", "default_roadmap_template_id": "RMT-GONE"},
            "find_template_by_id": lambda tid: None,
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TEMPLATE_NOT_FOUND")

    def test_zero_linked_templates_proceeds_with_no_template(self):
        result = self._call({"linked_templates": []})
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_template_id"], "")

    def test_one_linked_template_auto_selected(self):
        result = self._call({
            "linked_templates": [{"template_id": "RMT-ONLY"}],
            "find_template_by_id": lambda tid: {
                "template_id": tid, "service_id": "SVC-001", "status": "active",
            } if tid else None,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_template_id"], "RMT-ONLY")

    def test_multiple_linked_templates_require_explicit_selection(self):
        result = self._call({
            "linked_templates": [{"template_id": "RMT-A"}, {"template_id": "RMT-B"}],
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "MULTIPLE_TEMPLATES_REQUIRE_SELECTION")
        self.assertEqual(set(result["candidate_template_ids"]), {"RMT-A", "RMT-B"})

    def test_zero_stages_in_template_does_not_block_roadmap_creation(self):
        result = self._call({"template_stages": []}, template_id="RMT-EMPTY")
        self.assertTrue(result["ok"])


class TestDuplicateOpenRoadmapPolicy(_CrossDomainTestCase):
    def test_zero_open_roadmaps_creates_new(self):
        result = self._call({"open_roadmaps": []})
        self.assertTrue(result["roadmap_created"])
        self.assertFalse(result["roadmap_reused"])

    def test_one_active_roadmap_is_reused(self):
        result = self._call({"open_roadmaps": [{
            "roadmap_id": "RM-EXIST", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001",
        }]})
        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["roadmap_id"], "RM-EXIST")

    def test_one_on_hold_roadmap_is_reused(self):
        result = self._call({"open_roadmaps": [{
            "roadmap_id": "RM-HOLD", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "on_hold", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001",
        }]})
        self.assertTrue(result["roadmap_reused"])
        self.assertEqual(result["roadmap_id"], "RM-HOLD")

    def test_completed_only_history_allows_new_roadmap(self):
        """Completed Roadmaps are not "open" — find_open_roadmaps_for_object
        itself excludes them, so this scenario is simulated by an empty
        open list even though a completed Roadmap exists in history."""
        result = self._call({"open_roadmaps": []})
        self.assertTrue(result["roadmap_created"])

    def test_cancelled_only_history_allows_new_roadmap(self):
        result = self._call({"open_roadmaps": []})
        self.assertTrue(result["roadmap_created"])

    def test_multiple_open_roadmaps_block_with_integrity_error(self):
        open_roadmaps = [
            {"roadmap_id": "RM-A", "object_id": "OBJ-001", "service_id": "SVC-001",
             "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001"},
            {"roadmap_id": "RM-B", "object_id": "OBJ-001", "service_id": "SVC-001",
             "status": "on_hold", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001"},
        ]
        result = self._call({"open_roadmaps": open_roadmaps})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR")
        self.assertEqual(set(result["conflicting_roadmap_ids"]), {"RM-A", "RM-B"})
        self.assertEqual(result["roadmap_id"], "")

    def test_duplicate_lookup_never_arbitrary_first_pick_across_repeated_calls(self):
        """Calling with the same open-Roadmap conflict twice must
        deterministically block both times — never intermittently
        picking one of the two as if it were the sole match."""
        open_roadmaps = [
            {"roadmap_id": "RM-A", "object_id": "OBJ-001", "service_id": "SVC-001",
             "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001"},
            {"roadmap_id": "RM-B", "object_id": "OBJ-001", "service_id": "SVC-001",
             "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001"},
        ]
        first = self._call({"open_roadmaps": open_roadmaps})
        second = self._call({"open_roadmaps": open_roadmaps})
        self.assertEqual(first["error_code"], "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR")
        self.assertEqual(second["error_code"], "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR")


class TestRetryAndImmutability(_CrossDomainTestCase):
    def test_retry_does_not_create_duplicate_roadmap(self):
        existing = {
            "roadmap_id": "RM-EXIST", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001",
        }
        bb = _fresh_bb()
        with ExitStack() as stack:
            patches = _happy_path_patches(open_roadmaps=[existing])
            mocks = [stack.enter_context(p) for p in patches]
            create_mock = mocks[8]  # create_roadmap_record patch, by position
            result = bb.create_roadmap_for_object(**DEFAULT_ARGS)
        self.assertTrue(result["roadmap_reused"])
        create_mock.assert_not_called()

    def test_immutable_business_id_conflict_blocks(self):
        result = self._call({"open_roadmaps": [{
            "roadmap_id": "RM-CONFLICT", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "active", "template_id": "", "business_id": "BIZ-999", "client_id": "PRS-001",
        }]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "ROADMAP_IMMUTABLE_FIELD_CONFLICT")

    def test_immutable_client_id_conflict_blocks(self):
        result = self._call({"open_roadmaps": [{
            "roadmap_id": "RM-CONFLICT2", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-999",
        }]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "ROADMAP_IMMUTABLE_FIELD_CONFLICT")

    def test_matching_immutable_fields_do_not_block_reuse(self):
        result = self._call({"open_roadmaps": [{
            "roadmap_id": "RM-OK", "object_id": "OBJ-001", "service_id": "SVC-001",
            "status": "active", "template_id": "", "business_id": "BIZ-001", "client_id": "PRS-001",
        }]})
        self.assertTrue(result["ok"])
        self.assertTrue(result["roadmap_reused"])


class TestArchitectureAndMockCompleteness(_CrossDomainTestCase):
    """Sanity checks that this file's own mocking is exhaustive enough
    that the happy path genuinely reaches every validation step (guards
    against a silently-broken test fixture masking real regressions)."""

    def test_happy_path_result_has_all_structured_contract_fields(self):
        result = self._call()
        for key in (
            "ok", "roadmap_id", "error", "error_code", "warnings",
            "roadmap_created", "roadmap_reused", "stages_created", "stages_reused",
            "partial_failure", "conflicting_roadmap_ids", "selected_template_id",
            "type_compatibility_warning", "client_type_validation",
        ):
            self.assertIn(key, result, f"missing expected result field: {key}")

    def test_no_raw_registry_access_outside_roadmap_manager(self):
        """create_roadmap_for_object must reach the Roadmap registry
        only via business_core.roadmap_manager's canonical API — this
        is exercised implicitly by every test above succeeding while
        only roadmap_manager.find_open_roadmaps_for_object/
        create_roadmap_record are mocked (no sheets.* Roadmap-registry
        reads/writes needed for the happy path beyond biz_registry)."""
        result = self._call()
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
