"""
Tests for Phase 41C — Lead / Sales Funnel Domain Foundation: business_core/
lead_manager.py (ADR-024). Covers Lead ID generation, low-level creation,
admin-field/active-field update rules, status persistence, and read-only
idempotency/duplicate-contact lookups. No cross-entity relation
validation, no contact/Expected Value/currency/datetime normalization,
no lifecycle-policy — that's business_builder.py's job, covered
separately in test_business_lead_foundation.py.

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

LEAD_HEADERS = [
    "Lead ID", "Business ID", "Caller Idempotency Key",
    "Contact Name Snapshot", "Phone Snapshot", "WhatsApp Snapshot",
    "Email Snapshot", "Company Snapshot",
    "Service ID", "Source", "Channel ID", "Status",
    "Qualification Notes", "Disposition Reason",
    "Expected Value", "Currency",
    "Next Follow-up At", "Last Contacted At", "Assigned Person ID",
    "Converted Client ID", "Converted At", "Converted By",
    "Created At", "Created By", "Updated At", "Archived At", "Notes",
]

LEAD_ROW = [
    "LED-001", "BIZ-001", "CALLKEY-1",
    "Ivan Ivanov", "+77001234567", "", "ivan@example.com", "",
    "SVC-001", "instagram", "", "new",
    "", "",
    "100000.00", "KZT",
    "", "", "",
    "", "", "",
    "2026-01-01 00:00:00 UTC", "dida", "2026-01-01 00:00:00 UTC", "", "",
]


def _fresh_lm():
    import importlib
    import business_core.lead_manager as lm
    return importlib.reload(lm)


def _make_sheet(headers, rows):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


class TestSchema(unittest.TestCase):
    def test_lead_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["leads"], LEAD_HEADERS)

    def test_id_prefix(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["leads"], "LED")

    def test_no_deal_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("deal_registry", "deals"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_interaction_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("interactions", "interaction_registry", "lead_interactions"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_campaign_utm_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        for forbidden in ("campaign_registry", "utm_registry", "campaigns"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)
            self.assertNotIn(forbidden, BUSINESS_SHEET_NAMES)

    def test_no_relation_columns_to_other_domains(self):
        forbidden_columns = (
            "Object ID", "Roadmap ID", "Commercial Offer ID", "Payment Obligation ID",
            "Payment Transaction ID", "Task ID", "Deal ID", "Interaction ID",
        )
        for col in forbidden_columns:
            self.assertNotIn(col, LEAD_HEADERS)

    def test_no_generic_json_or_csv_relation_fields(self):
        for col in LEAD_HEADERS:
            self.assertNotIn("JSON", col)
        self.assertNotIn("Relations", LEAD_HEADERS)

    def test_no_person_type_status_fields(self):
        for forbidden in ("Тип", "Тип касания", "Статус отношений", "Теплота"):
            self.assertNotIn(forbidden, LEAD_HEADERS)

    def test_disposition_reason_not_loss_reason(self):
        self.assertIn("Disposition Reason", LEAD_HEADERS)
        self.assertNotIn("Loss Reason", LEAD_HEADERS)

    def test_field_count(self):
        self.assertEqual(len(LEAD_HEADERS), 27)


class TestIdGeneration(unittest.TestCase):
    def test_generate_next_lead_id_empty_sheet(self):
        lm = _fresh_lm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [LEAD_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(lm.generate_next_lead_id(), "LED-001")

    def test_generate_next_lead_id_increments(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(lm.generate_next_lead_id(), "LED-002")

    def test_malformed_existing_lead_ids_ignored(self):
        lm = _fresh_lm()
        bad_row = list(LEAD_ROW)
        bad_row[0] = "NOT-A-VALID-ID"
        sheet = _make_sheet(LEAD_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(lm.generate_next_lead_id(), "LED-001")

    def test_no_duplicate_id_generators(self):
        lm = _fresh_lm()
        generators = [n for n in dir(lm) if "generate_next" in n and "lead_id" in n]
        self.assertEqual(generators, ["generate_next_lead_id"])


class TestReadsAndLookups(unittest.TestCase):
    def test_find_by_id_not_found(self):
        lm = _fresh_lm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(lm.find_lead_by_id("LED-999"))

    def test_find_by_id_found(self):
        lm = _fresh_lm()
        row_dict = dict(zip(LEAD_HEADERS, LEAD_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            result = lm.find_lead_by_id("LED-001")
        self.assertEqual(result["Contact Name Snapshot"], "Ivan Ivanov")

    def test_find_by_idempotency_key(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_idempotency_key("BIZ-001", "CALLKEY-1")
        self.assertEqual(len(matches), 1)

    def test_find_by_idempotency_key_no_match(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_idempotency_key("BIZ-001", "OTHER-KEY")
        self.assertEqual(matches, [])

    def test_idempotency_requires_both_args(self):
        lm = _fresh_lm()
        self.assertEqual(lm.find_leads_by_idempotency_key("", "K"), [])
        self.assertEqual(lm.find_leads_by_idempotency_key("BIZ-001", ""), [])

    def test_duplicate_contact_exact_phone(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", phone="+77001234567")
        self.assertEqual(len(matches), 1)

    def test_duplicate_contact_phone_matches_existing_whatsapp(self):
        lm = _fresh_lm()
        row = list(LEAD_ROW)
        row[4] = ""              # Phone Snapshot blank
        row[5] = "+77001234567"  # WhatsApp Snapshot
        sheet = _make_sheet(LEAD_HEADERS, [row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", phone="+77001234567")
        self.assertEqual(len(matches), 1)

    def test_duplicate_contact_exact_email(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", email="ivan@example.com")
        self.assertEqual(len(matches), 1)

    def test_no_cross_business_match(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-999", phone="+77001234567")
        self.assertEqual(matches, [])

    def test_zero_matches_returns_empty(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", phone="+70000000000")
        self.assertEqual(matches, [])

    def test_multiple_matches_all_returned(self):
        lm = _fresh_lm()
        row2 = list(LEAD_ROW)
        row2[0] = "LED-002"
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW, row2])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", phone="+77001234567")
        self.assertEqual(len(matches), 2)

    def test_exclude_lead_id(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = lm.find_leads_by_exact_contact_channels("BIZ-001", phone="+77001234567", exclude_lead_id="LED-001")
        self.assertEqual(matches, [])

    def test_no_fuzzy_no_args_returns_empty(self):
        lm = _fresh_lm()
        self.assertEqual(lm.find_leads_by_exact_contact_channels("BIZ-001"), [])

    def test_list_leads_excludes_archived_by_default(self):
        lm = _fresh_lm()
        archived_row = list(LEAD_ROW)
        archived_row[0] = "LED-002"
        archived_row[11] = "archived"
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW, archived_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = lm.list_leads(business_id="BIZ-001")
        self.assertEqual([r["Lead ID"] for r in rows], ["LED-001"])

    def test_list_leads_includes_archived_when_requested(self):
        lm = _fresh_lm()
        archived_row = list(LEAD_ROW)
        archived_row[0] = "LED-002"
        archived_row[11] = "archived"
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW, archived_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = lm.list_leads(business_id="BIZ-001", include_archived=True)
        self.assertEqual(len(rows), 2)

    def test_list_leads_exact_filter_no_substring(self):
        lm = _fresh_lm()
        sheet = _make_sheet(LEAD_HEADERS, [LEAD_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            rows = lm.list_leads(business_id="BIZ-0")
        self.assertEqual(rows, [])


class TestLowLevelCreation(unittest.TestCase):
    def test_requires_business_id(self):
        lm = _fresh_lm()
        result = lm.create_lead("", "Ivan Ivanov")
        self.assertFalse(result["ok"])

    def test_requires_contact_name(self):
        lm = _fresh_lm()
        result = lm.create_lead("BIZ-001", "")
        self.assertFalse(result["ok"])

    def test_creates_new_row_defaults(self):
        lm = _fresh_lm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [LEAD_HEADERS]
        appended = {}

        def _capture_append(sheet_key, values):
            appended["row"] = values
            return 2

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row", side_effect=_capture_append):
            result = lm.create_lead("BIZ-001", "Ivan Ivanov", phone_snapshot="+77001234567")
        self.assertTrue(result["ok"])
        status_idx = LEAD_HEADERS.index("Status")
        converted_idx = LEAD_HEADERS.index("Converted Client ID")
        archived_idx = LEAD_HEADERS.index("Archived At")
        self.assertEqual(appended["row"][status_idx], "new")
        self.assertEqual(appended["row"][converted_idx], "")
        self.assertEqual(appended["row"][archived_idx], "")


class TestAdminFieldImmutability(unittest.TestCase):
    def test_identity_fields_blocked(self):
        lm = _fresh_lm()
        result = lm.update_lead_admin_fields("LED-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_IMMUTABLE")

    def test_status_not_editable_via_admin(self):
        lm = _fresh_lm()
        result = lm.update_lead_admin_fields("LED-001", {"Status": "qualified"})
        self.assertFalse(result["ok"])

    def test_notes_allowed(self):
        lm = _fresh_lm()
        row_dict = dict(zip(LEAD_HEADERS, LEAD_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_admin_fields("LED-001", {"Notes": "updated"})
        self.assertTrue(result["ok"])


class TestActiveFieldUpdate(unittest.TestCase):
    def test_only_active_editable_fields_allowed(self):
        lm = _fresh_lm()
        result = lm.update_lead_active_fields("LED-001", {"Business ID": "BIZ-999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "LEAD_IMMUTABLE")

    def test_expected_value_editable(self):
        lm = _fresh_lm()
        row_dict = dict(zip(LEAD_HEADERS, LEAD_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_active_fields("LED-001", {"Expected Value": "200000.00"})
        self.assertTrue(result["ok"])


class TestStatusUpdate(unittest.TestCase):
    def test_invalid_status_rejected(self):
        lm = _fresh_lm()
        result = lm.update_lead_status("LED-001", "not-a-status")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEAD_STATUS")

    def test_status_updated(self):
        lm = _fresh_lm()
        row_dict = dict(zip(LEAD_HEADERS, LEAD_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_status("LED-001", "qualified")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_converted_client_id_write_once(self):
        lm = _fresh_lm()
        row = dict(zip(LEAD_HEADERS, LEAD_ROW))
        row["Converted Client ID"] = "PRS-001"
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_status("LED-001", "converted", converted_client_id="PRS-999")
        # Status itself still updates, but Converted Client ID write is skipped
        # since it is already set (write-once semantics).
        sheet.update_cell.assert_any_call(2, LEAD_HEADERS.index("Status") + 1, "converted")
        for call in sheet.update_cell.call_args_list:
            self.assertNotEqual(call.args[1], LEAD_HEADERS.index("Converted Client ID") + 1)

    def test_never_touches_contact_fields(self):
        """Structural immutability guarantee: update_lead_status()'s
        parameter set makes it impossible to pass a contact/commercial
        field value."""
        import inspect
        lm = _fresh_lm()
        sig = inspect.signature(lm.update_lead_status)
        forbidden = (
            "contact_name_snapshot", "phone_snapshot", "whatsapp_snapshot",
            "email_snapshot", "company_snapshot", "service_id", "expected_value", "currency",
        )
        for name in forbidden:
            self.assertNotIn(name, sig.parameters)


class TestNoHardDeleteNoRestore(unittest.TestCase):
    def test_no_delete_function_exists(self):
        lm = _fresh_lm()
        names = [n for n in dir(lm) if "delete" in n.lower()]
        self.assertEqual(names, [])

    def test_no_restore_function_exists(self):
        lm = _fresh_lm()
        names = [n for n in dir(lm) if "restore" in n.lower() or "reopen" in n.lower()]
        self.assertEqual(names, [])


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A3-H1: manager-level exception logging secrecy.
# Proves _find_lead_row and update_lead_admin_fields log only a
# fixed literal on infrastructure exceptions — no raw exception
# text, no entity ID, no updates dict, no row content — and that
# the returned "error" string is likewise a fixed safe value, not
# str(exc).
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


class TestFindLeadRowExceptionSecrecy(unittest.TestCase):
    def test_no_secrets_in_log_call_args(self):
        lm = _fresh_lm()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.lead_manager.log.warning") as mock_warn:
            result = lm._find_lead_row("LED-001")
        self.assertIsNone(result)
        mock_warn.assert_called_once()
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_log_call_is_fixed_string(self):
        lm = _fresh_lm()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.lead_manager.log.warning") as mock_warn:
            lm._find_lead_row("LED-001")
        mock_warn.assert_called_once_with("_find_lead_row infrastructure failure")


class TestUpdateLeadAdminFieldsExceptionSecrecy(unittest.TestCase):
    def _row(self):
        return dict(zip(LEAD_HEADERS, LEAD_ROW))

    def test_notes_write_exception_no_secrets_in_log(self):
        lm = _fresh_lm()
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.lead_manager.log.error") as mock_error:
            result = lm.update_lead_admin_fields("LED-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_lead_admin_fields infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_notes_write_exception_error_field_is_fixed_safe_string(self):
        lm = _fresh_lm()
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_admin_fields("LED-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertEqual(result["error"], "Infrastructure failure")
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, result["error"])

    def test_updated_at_write_exception_no_secrets_in_log(self):
        lm = _fresh_lm()
        row = self._row()
        row["Notes"] = "old-value"
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS

        def update_cell_side_effect(row_num, col, value):
            if col == LEAD_HEADERS.index("Updated At") + 1:
                _boom_with_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.lead_manager.log.error") as mock_error:
            result = lm.update_lead_admin_fields("LED-001", {"Notes": "new-value"})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_lead_admin_fields infrastructure failure")

    def test_success_result_unaffected(self):
        lm = _fresh_lm()
        row = self._row()
        row["Notes"] = "old"
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_admin_fields("LED-001", {"Notes": "new"})
        self.assertEqual(result, {"ok": True, "changed": True, "code": "", "error": None})

    def test_unchanged_result_unaffected(self):
        lm = _fresh_lm()
        row = self._row()
        row["Notes"] = "same"
        sheet = MagicMock()
        sheet.row_values.return_value = LEAD_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = lm.update_lead_admin_fields("LED-001", {"Notes": "same"})
        self.assertEqual(result, {"ok": True, "changed": False, "code": "", "error": None})
        sheet.update_cell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
