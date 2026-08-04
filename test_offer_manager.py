"""
Tests for Phase 40C — Commercial Offer Domain Foundation: business_core/
offer_manager.py (ADR-023). Covers Commercial Offer ID/Series ID
generation, low-level creation, admin-field/draft-field update rules,
status persistence, and read-only idempotency/series/version lookups.
No cross-entity eligibility, no Decimal/currency/date normalization —
that's business_builder.py's job, covered separately in
test_business_offer_foundation.py.

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

OFFER_HEADERS = [
    "Commercial Offer ID", "Offer Series ID", "Previous Commercial Offer ID",
    "Version Number", "Business ID", "Client ID", "Object ID", "Service ID",
    "Roadmap ID", "Offer Document ID", "Title Snapshot", "Scope Snapshot",
    "Quoted Amount", "Currency", "Valid Until", "Status",
    "Caller Idempotency Key",
    "Created At", "Created By", "Updated At",
    "Sent At", "Sent By",
    "Accepted At", "Accepted By",
    "Rejected At", "Rejected By", "Rejection Reason",
    "Expired At",
    "Cancelled At", "Cancelled By", "Cancellation Reason",
    "Archived At", "Notes",
]

OFFER_ROW = [
    "OFR-001", "OFS-001", "", "1", "BIZ-001", "PRS-001", "", "SVC-001",
    "", "", "Этап 1", "Описание объёма", "150000.00", "KZT", "2026-12-31", "draft",
    "CALLKEY-1",
    "2026-01-01 00:00:00 UTC", "dida", "2026-01-01 00:00:00 UTC",
    "", "",
    "", "",
    "", "", "",
    "",
    "", "", "",
    "", "",
]


def _fresh_om():
    import importlib
    import business_core.offer_manager as om
    return importlib.reload(om)


def _make_sheet(headers, rows):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


class TestSchema(unittest.TestCase):
    def test_offer_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["commercial_offers"], OFFER_HEADERS)

    def test_id_prefix(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["commercial_offers"], "OFR")

    def test_no_line_item_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        self.assertNotIn("commercial_offer_line_items", BUSINESS_HEADERS)
        self.assertNotIn("commercial_offer_line_items", BUSINESS_SHEET_NAMES)

    def test_no_contract_or_invoice_registry(self):
        from business_core.sheets import BUSINESS_HEADERS
        for forbidden in ("contract_registry", "invoice_registry"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)

    def test_no_payment_status_fields(self):
        from business_core.sheets import BUSINESS_HEADERS
        for forbidden in ("Paid Amount", "Remaining Amount", "Payment Status"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS["commercial_offers"])


class TestIdGeneration(unittest.TestCase):
    def test_generate_next_offer_id_empty_sheet(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OFFER_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_offer_id(), "OFR-001")

    def test_generate_next_offer_id_increments(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_offer_id(), "OFR-002")

    def test_malformed_existing_offer_ids_ignored(self):
        om = _fresh_om()
        bad_row = list(OFFER_ROW)
        bad_row[0] = "NOT-A-VALID-ID"
        sheet = _make_sheet(OFFER_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_offer_id(), "OFR-001")

    def test_generate_next_series_id_empty_sheet(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OFFER_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_series_id(), "OFS-001")

    def test_generate_next_series_id_increments(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_series_id(), "OFS-002")

    def test_series_id_scans_correct_column_not_column_a(self):
        """Offer Series ID lives in column B, not column A — this test
        proves generate_next_series_id() doesn't accidentally scan
        column A (which holds OFR- IDs, a different prefix)."""
        om = _fresh_om()
        row_with_high_ofr = list(OFFER_ROW)
        row_with_high_ofr[0] = "OFR-999"
        row_with_high_ofr[1] = "OFS-003"
        sheet = _make_sheet(OFFER_HEADERS, [row_with_high_ofr])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(om.generate_next_series_id(), "OFS-004")


class TestReadsAndLookups(unittest.TestCase):
    def test_find_by_id_not_found(self):
        om = _fresh_om()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(om.find_commercial_offer_by_id("OFR-999"))

    def test_find_by_id_found(self):
        om = _fresh_om()
        row_dict = dict(zip(OFFER_HEADERS, OFFER_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            result = om.find_commercial_offer_by_id("OFR-001")
        self.assertEqual(result["Title Snapshot"], "Этап 1")

    def test_find_by_idempotency_key(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = om.find_commercial_offers_by_idempotency_key("BIZ-001", "CALLKEY-1")
        self.assertEqual(len(matches), 1)

    def test_find_by_idempotency_key_no_match(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = om.find_commercial_offers_by_idempotency_key("BIZ-001", "OTHER-KEY")
        self.assertEqual(matches, [])

    def test_requires_both_args(self):
        om = _fresh_om()
        self.assertEqual(om.find_commercial_offers_by_idempotency_key("", "K"), [])
        self.assertEqual(om.find_commercial_offers_by_idempotency_key("BIZ-001", ""), [])

    def test_list_by_series(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = om.list_commercial_offers_by_series("OFS-001")
        self.assertEqual(len(rows), 1)


class TestLatestVersionDerivation(unittest.TestCase):
    def test_single_version_is_latest(self):
        om = _fresh_om()
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offer"]["Commercial Offer ID"], "OFR-001")

    def test_max_version_wins(self):
        om = _fresh_om()
        v2_row = list(OFFER_ROW)
        v2_row[0] = "OFR-002"
        v2_row[2] = "OFR-001"
        v2_row[3] = "2"
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW, v2_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offer"]["Commercial Offer ID"], "OFR-002")

    def test_malformed_version_blocks(self):
        om = _fresh_om()
        bad_row = list(OFFER_ROW)
        bad_row[3] = "not-a-number"
        sheet = _make_sheet(OFFER_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_COMMERCIAL_OFFER_VERSION")

    def test_nonpositive_version_blocks(self):
        om = _fresh_om()
        bad_row = list(OFFER_ROW)
        bad_row[3] = "0"
        sheet = _make_sheet(OFFER_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_COMMERCIAL_OFFER_VERSION")

    def test_duplicate_max_version_blocks_no_first_pick(self):
        om = _fresh_om()
        dup_row = list(OFFER_ROW)
        dup_row[0] = "OFR-777"
        sheet = _make_sheet(OFFER_HEADERS, [OFFER_ROW, dup_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR")

    def test_empty_series_not_found(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OFFER_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.find_latest_commercial_offer_in_series("OFS-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_NOT_FOUND")


class TestLowLevelCreation(unittest.TestCase):
    def test_requires_business_id(self):
        om = _fresh_om()
        result = om.create_commercial_offer("OFS-001", "", 1, "", "PRS-001", "T", "S", "100.00", "KZT", "2026-12-31")
        self.assertFalse(result["ok"])

    def test_requires_title_and_scope(self):
        om = _fresh_om()
        result = om.create_commercial_offer("OFS-001", "", 1, "BIZ-001", "PRS-001", "", "S", "100.00", "KZT", "2026-12-31")
        self.assertFalse(result["ok"])

    def test_creates_draft_row(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OFFER_HEADERS]
        appended = {}

        def _capture_append(sheet_key, values):
            appended["row"] = values
            return 2

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row", side_effect=_capture_append):
            result = om.create_commercial_offer(
                "OFS-001", "", 1, "BIZ-001", "PRS-001", "Title", "Scope", "150000.00", "KZT", "2026-12-31",
            )
        self.assertTrue(result["ok"])
        idx = OFFER_HEADERS.index("Status")
        self.assertEqual(appended["row"][idx], "draft")


class TestAdminFieldImmutability(unittest.TestCase):
    def test_identity_fields_blocked(self):
        om = _fresh_om()
        result = om.update_commercial_offer_admin_fields("OFR-001", {"Quoted Amount": "999.00"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_IMMUTABLE")

    def test_status_not_editable_via_admin(self):
        om = _fresh_om()
        result = om.update_commercial_offer_admin_fields("OFR-001", {"Status": "accepted"})
        self.assertFalse(result["ok"])

    def test_notes_allowed(self):
        om = _fresh_om()
        row_dict = dict(zip(OFFER_HEADERS, OFFER_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": "updated"})
        self.assertTrue(result["ok"])


class TestDraftFieldUpdate(unittest.TestCase):
    def test_only_draft_editable_fields_allowed(self):
        om = _fresh_om()
        result = om.update_commercial_offer_draft_fields("OFR-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_IMMUTABLE")

    def test_quoted_amount_editable_in_draft(self):
        om = _fresh_om()
        row_dict = dict(zip(OFFER_HEADERS, OFFER_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_commercial_offer_draft_fields("OFR-001", {"Quoted Amount": "200000.00"})
        self.assertTrue(result["ok"])


class TestNoHardDelete(unittest.TestCase):
    def test_no_delete_function_exists(self):
        om = _fresh_om()
        names = [n for n in dir(om) if "delete" in n.lower()]
        self.assertEqual(names, [])


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A4-H1: manager-level exception logging secrecy.
# Proves _find_offer_row and update_commercial_offer_admin_fields
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


class TestFindOfferRowExceptionSecrecy(unittest.TestCase):
    def test_no_secrets_in_log_call_args(self):
        om = _fresh_om()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.offer_manager.log.warning") as mock_warn:
            result = om._find_offer_row("OFR-001")
        self.assertIsNone(result)
        mock_warn.assert_called_once()
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_log_call_is_fixed_string(self):
        om = _fresh_om()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.offer_manager.log.warning") as mock_warn:
            om._find_offer_row("OFR-001")
        mock_warn.assert_called_once_with("_find_offer_row infrastructure failure")


class TestUpdateCommercialOfferAdminFieldsExceptionSecrecy(unittest.TestCase):
    def _row(self):
        return dict(zip(OFFER_HEADERS, OFFER_ROW))

    def test_notes_write_exception_no_secrets_in_log(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.offer_manager.log.error") as mock_error:
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_commercial_offer_admin_fields infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_notes_write_exception_error_field_is_fixed_safe_string(self):
        om = _fresh_om()
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertEqual(result["error"], "Infrastructure failure")
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, result["error"])

    def test_updated_at_write_exception_no_secrets_in_log(self):
        om = _fresh_om()
        row = self._row()
        row["Notes"] = "old-value"
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS

        def update_cell_side_effect(row_num, col, value):
            if col == OFFER_HEADERS.index("Updated At") + 1:
                _boom_with_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.offer_manager.log.error") as mock_error:
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": "new-value"})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_commercial_offer_admin_fields infrastructure failure")

    def test_success_result_unaffected(self):
        om = _fresh_om()
        row = self._row()
        row["Notes"] = "old"
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": "new"})
        self.assertEqual(result, {"ok": True, "changed": True, "code": "", "error": None})

    def test_unchanged_result_unaffected(self):
        om = _fresh_om()
        row = self._row()
        row["Notes"] = "same"
        sheet = MagicMock()
        sheet.row_values.return_value = OFFER_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = om.update_commercial_offer_admin_fields("OFR-001", {"Notes": "same"})
        self.assertEqual(result, {"ok": True, "changed": False, "code": "", "error": None})
        sheet.update_cell.assert_not_called()

    def test_validation_result_codes_unaffected(self):
        om = _fresh_om()
        result = om.update_commercial_offer_admin_fields("OFR-001", {"Status": "accepted"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "COMMERCIAL_OFFER_IMMUTABLE")


if __name__ == "__main__":
    unittest.main()
