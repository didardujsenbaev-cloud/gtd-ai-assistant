"""
Tests for Phase 42C — Interaction / Communication History Domain
Foundation: business_core/interaction_manager.py (ADR-025). Covers
Interaction ID generation, low-level creation, admin-field update
rules, status persistence, and read-only idempotency lookups. No
cross-entity relation validation, no Interaction Type/Direction/
Occurred At/content normalization, no lifecycle policy — that's
business_builder.py's job, covered separately in
test_business_interaction_foundation.py.

No live Sheets writes — mocks only. Registered in conftest.py's hard
socket-block set before this file's logic was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

INTERACTION_HEADERS = [
    "Interaction ID", "Business ID", "Caller Idempotency Key",
    "Interaction Type", "Direction", "Channel ID", "Occurred At",
    "Summary", "Outcome",
    "Lead ID", "Client ID", "Commercial Offer ID", "Assigned Person ID",
    "External Reference", "Status",
    "Created At", "Created By", "Updated At", "Archived At", "Notes",
]

INTERACTION_ROW = [
    "ACT-001", "BIZ-001", "CALLKEY-1",
    "call", "outbound", "CH-001", "2026-07-20T10:00:00+00:00",
    "Discussed pricing", "Interested",
    "LED-001", "", "", "PRS-002",
    "", "active",
    "2026-01-01 00:00:00 UTC", "dida", "2026-01-01 00:00:00 UTC", "", "",
]


def _fresh_im():
    import importlib
    import business_core.interaction_manager as im
    return importlib.reload(im)


def _make_sheet(headers, rows):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


class TestSchema(unittest.TestCase):
    def test_interaction_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["interaction_log"], INTERACTION_HEADERS)

    def test_id_prefix(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["interaction_log"], "ACT")

    def test_prohibited_registry_keys_absent(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("interactions", "interaction_registry", "lead_interactions"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_audit_event_or_message_delivery_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("audit_log", "audit_event_registry", "message_delivery", "message_delivery_registry"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_relation_columns_to_other_domains(self):
        forbidden_columns = (
            "Object ID", "Service ID", "Roadmap ID", "Payment Obligation ID", "Task ID",
        )
        for col in forbidden_columns:
            self.assertNotIn(col, INTERACTION_HEADERS)

    def test_no_message_body_or_attachment_fields(self):
        forbidden = ("Message Body", "Email Body", "Transcript", "Attachment Content", "Provider Payload")
        for col in forbidden:
            self.assertNotIn(col, INTERACTION_HEADERS)

    def test_field_count(self):
        self.assertEqual(len(INTERACTION_HEADERS), 20)


class TestIdGeneration(unittest.TestCase):
    def test_generate_next_interaction_id_empty_sheet(self):
        im = _fresh_im()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [INTERACTION_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(im.generate_next_interaction_id(), "ACT-001")

    def test_generate_next_interaction_id_increments(self):
        im = _fresh_im()
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(im.generate_next_interaction_id(), "ACT-002")

    def test_malformed_existing_interaction_ids_ignored(self):
        im = _fresh_im()
        bad_row = list(INTERACTION_ROW)
        bad_row[0] = "NOT-A-VALID-ID"
        sheet = _make_sheet(INTERACTION_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(im.generate_next_interaction_id(), "ACT-001")

    def test_no_int_or_tch_generator(self):
        im = _fresh_im()
        names = [n for n in dir(im) if "generate_next" in n]
        self.assertEqual(names, ["generate_next_interaction_id"])
        src = Path(__file__).parent.joinpath("business_core", "interaction_manager.py").read_text(encoding="utf-8")
        self.assertNotIn('"INT-', src)
        self.assertNotIn('"TCH-', src)


class TestReadsAndLookups(unittest.TestCase):
    def test_find_by_id_not_found(self):
        im = _fresh_im()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(im.find_interaction_by_id("ACT-999"))

    def test_find_by_id_found(self):
        im = _fresh_im()
        row_dict = dict(zip(INTERACTION_HEADERS, INTERACTION_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            result = im.find_interaction_by_id("ACT-001")
        self.assertEqual(result["Summary"], "Discussed pricing")

    def test_find_by_idempotency_key(self):
        im = _fresh_im()
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = im.find_interactions_by_idempotency_key("BIZ-001", "CALLKEY-1")
        self.assertEqual(len(matches), 1)

    def test_find_by_idempotency_key_no_match(self):
        im = _fresh_im()
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = im.find_interactions_by_idempotency_key("BIZ-001", "OTHER-KEY")
        self.assertEqual(matches, [])

    def test_idempotency_requires_both_args(self):
        im = _fresh_im()
        self.assertEqual(im.find_interactions_by_idempotency_key("", "K"), [])
        self.assertEqual(im.find_interactions_by_idempotency_key("BIZ-001", ""), [])

    def test_list_interactions_excludes_archived_by_default(self):
        im = _fresh_im()
        archived_row = list(INTERACTION_ROW)
        archived_row[0] = "ACT-002"
        archived_row[14] = "archived"
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW, archived_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = im.list_interactions(business_id="BIZ-001")
        self.assertEqual([r["Interaction ID"] for r in rows], ["ACT-001"])

    def test_list_interactions_includes_archived_when_requested(self):
        im = _fresh_im()
        archived_row = list(INTERACTION_ROW)
        archived_row[0] = "ACT-002"
        archived_row[14] = "archived"
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW, archived_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = im.list_interactions(business_id="BIZ-001", include_archived=True)
        self.assertEqual(len(rows), 2)

    def test_list_interactions_exact_filter_no_substring(self):
        im = _fresh_im()
        sheet = _make_sheet(INTERACTION_HEADERS, [INTERACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = im.list_interactions(business_id="BIZ-0")
        self.assertEqual(rows, [])


class TestLowLevelCreation(unittest.TestCase):
    def test_requires_business_id(self):
        im = _fresh_im()
        result = im.create_interaction("", "call", "2026-07-20T10:00:00+00:00", "Summary")
        self.assertFalse(result["ok"])

    def test_requires_interaction_type(self):
        im = _fresh_im()
        result = im.create_interaction("BIZ-001", "", "2026-07-20T10:00:00+00:00", "Summary")
        self.assertFalse(result["ok"])

    def test_requires_occurred_at(self):
        im = _fresh_im()
        result = im.create_interaction("BIZ-001", "call", "", "Summary")
        self.assertFalse(result["ok"])

    def test_requires_summary(self):
        im = _fresh_im()
        result = im.create_interaction("BIZ-001", "call", "2026-07-20T10:00:00+00:00", "")
        self.assertFalse(result["ok"])

    def test_creates_active_row_defaults(self):
        im = _fresh_im()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [INTERACTION_HEADERS]
        appended = {}

        def _capture_append(sheet_key, values):
            appended["row"] = values
            return 2

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row", side_effect=_capture_append):
            result = im.create_interaction("BIZ-001", "call", "2026-07-20T10:00:00+00:00", "Summary", lead_id="LED-001")
        self.assertTrue(result["ok"])
        status_idx = INTERACTION_HEADERS.index("Status")
        archived_idx = INTERACTION_HEADERS.index("Archived At")
        self.assertEqual(appended["row"][status_idx], "active")
        self.assertEqual(appended["row"][archived_idx], "")


class TestAdminFieldImmutability(unittest.TestCase):
    def test_identity_fields_blocked(self):
        im = _fresh_im()
        result = im.update_interaction_admin_fields("ACT-001", {"Summary": "changed"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INTERACTION_IMMUTABLE")

    def test_status_not_editable_via_admin(self):
        im = _fresh_im()
        result = im.update_interaction_admin_fields("ACT-001", {"Status": "archived"})
        self.assertFalse(result["ok"])

    def test_notes_allowed(self):
        im = _fresh_im()
        row_dict = dict(zip(INTERACTION_HEADERS, INTERACTION_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": "updated"})
        self.assertTrue(result["ok"])


class TestStatusUpdate(unittest.TestCase):
    def test_invalid_status_rejected(self):
        im = _fresh_im()
        result = im.update_interaction_status("ACT-001", "not-a-status")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_INTERACTION_STATUS")

    def test_status_updated(self):
        im = _fresh_im()
        row_dict = dict(zip(INTERACTION_HEADERS, INTERACTION_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = im.update_interaction_status("ACT-001", "archived")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_archived_at_write_once(self):
        im = _fresh_im()
        row = dict(zip(INTERACTION_HEADERS, INTERACTION_ROW))
        row["Archived At"] = "2026-01-05 00:00:00 UTC"
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            im.update_interaction_status("ACT-001", "archived", archived_at="2026-02-01 00:00:00 UTC")
        for call in sheet.update_cell.call_args_list:
            self.assertNotEqual(call.args[1], INTERACTION_HEADERS.index("Archived At") + 1)

    def test_never_touches_interaction_facts(self):
        """Structural immutability guarantee: update_interaction_status()'s
        parameter set makes it impossible to pass a fact-field value."""
        import inspect
        im = _fresh_im()
        sig = inspect.signature(im.update_interaction_status)
        forbidden = (
            "interaction_type", "direction", "channel_id", "occurred_at",
            "summary", "outcome", "lead_id", "client_id", "commercial_offer_id",
            "assigned_person_id", "external_reference",
        )
        for name in forbidden:
            self.assertNotIn(name, sig.parameters)


class TestNoHardDeleteNoRestore(unittest.TestCase):
    def test_no_delete_function_exists(self):
        im = _fresh_im()
        names = [n for n in dir(im) if "delete" in n.lower()]
        self.assertEqual(names, [])

    def test_no_restore_function_exists(self):
        im = _fresh_im()
        names = [n for n in dir(im) if "restore" in n.lower() or "reopen" in n.lower()]
        self.assertEqual(names, [])


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A3-H1: manager-level exception logging secrecy.
# Proves _find_interaction_row and update_interaction_admin_fields
# log only a fixed literal on infrastructure exceptions — no raw
# exception text, no entity ID, no updates dict, no row content —
# and that the returned "error" string is likewise a fixed safe
# value, not str(exc).
# ─────────────────────────────────────────────────────────────

_SECRET_NOTES_MARKER = "SECRET_NOTES_MARKER"
_SECRET_BIZ_MARKER = "BIZ-SECRET"
_SECRET_ROW_MARKER = "ROW-SECRET"
_SECRET_API_MARKER = "API-PAYLOAD-SECRET"
_ALL_SECRET_MARKERS = (_SECRET_NOTES_MARKER, _SECRET_BIZ_MARKER, _SECRET_ROW_MARKER, _SECRET_API_MARKER)


def _boom_with_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_SECRET_NOTES_MARKER} and {_SECRET_BIZ_MARKER} "
        f"and {_SECRET_ROW_MARKER} and {_SECRET_API_MARKER}"
    )


class TestFindInteractionRowExceptionSecrecy(unittest.TestCase):
    def test_no_secrets_in_log_call_args(self):
        im = _fresh_im()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.interaction_manager.log.warning") as mock_warn:
            result = im._find_interaction_row("ACT-001")
        self.assertIsNone(result)
        mock_warn.assert_called_once()
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_log_call_is_fixed_string(self):
        im = _fresh_im()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.interaction_manager.log.warning") as mock_warn:
            im._find_interaction_row("ACT-001")
        mock_warn.assert_called_once_with("_find_interaction_row infrastructure failure")


class TestUpdateInteractionAdminFieldsExceptionSecrecy(unittest.TestCase):
    def _row(self):
        return dict(zip(INTERACTION_HEADERS, INTERACTION_ROW))

    def test_notes_write_exception_no_secrets_in_log(self):
        im = _fresh_im()
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.interaction_manager.log.error") as mock_error:
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_interaction_admin_fields infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_notes_write_exception_error_field_is_fixed_safe_string(self):
        im = _fresh_im()
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertEqual(result["error"], "Infrastructure failure")
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, result["error"])

    def test_updated_at_write_exception_no_secrets_in_log(self):
        im = _fresh_im()
        row = self._row()
        row["Notes"] = "old-value"
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS

        def update_cell_side_effect(row_num, col, value):
            if col == INTERACTION_HEADERS.index("Updated At") + 1:
                _boom_with_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.interaction_manager.log.error") as mock_error:
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": "new-value"})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_interaction_admin_fields infrastructure failure")

    def test_success_result_unaffected(self):
        # Regression guard: the happy path must be byte-for-byte
        # unchanged by this hardening.
        im = _fresh_im()
        row = self._row()
        row["Notes"] = "old"
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": "new"})
        self.assertEqual(result, {"ok": True, "changed": True, "code": "", "error": None})

    def test_unchanged_result_unaffected(self):
        im = _fresh_im()
        row = self._row()
        row["Notes"] = "same"
        sheet = MagicMock()
        sheet.row_values.return_value = INTERACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = im.update_interaction_admin_fields("ACT-001", {"Notes": "same"})
        self.assertEqual(result, {"ok": True, "changed": False, "code": "", "error": None})
        sheet.update_cell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
