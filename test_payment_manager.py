"""
Tests for Phase 39C — Payment/Milestone Domain Foundation: business_core/
payment_manager.py (ADR-022). Covers Commercial Milestone Template /
Payment Obligation / Payment Transaction ID generation, low-level
creation, admin-field update rules, status persistence, and read-only
idempotency-tuple lookups. No cross-entity eligibility, no Decimal/
currency normalization, no balance calculation — that's
business_builder.py's job, covered separately in
test_business_payment_foundation.py.

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

TEMPLATE_HEADERS = [
    "Commercial Milestone Template ID", "Roadmap Template ID", "Service ID",
    "Title", "Description", "Sequence", "Trigger Description",
    "Calculation Type", "Fixed Amount", "Percentage", "Currency", "Status",
    "Created At", "Created By", "Updated At", "Notes",
]

OBLIGATION_HEADERS = [
    "Payment Obligation ID", "Business ID", "Client ID", "Object ID", "Service ID",
    "Roadmap ID", "Stage ID", "Commercial Milestone Template ID",
    "Caller Idempotency Key", "Title Snapshot", "Description Snapshot",
    "Obligation Amount", "Currency", "Due Date", "Status",
    "Paid Amount", "Remaining Amount",
    "Created At", "Created By", "Issued At", "Paid At", "Cancelled At",
    "Updated At", "Notes",
]

TRANSACTION_HEADERS = [
    "Payment Transaction ID", "Business ID", "Payment Obligation ID", "Client ID",
    "Amount", "Currency", "Payment Date", "Payment Method",
    "External Transaction ID", "Caller Idempotency Key", "Evidence Document ID",
    "Status", "Reversal Reason",
    "Confirmed At", "Confirmed By", "Reversed At", "Reversed By",
    "Created At", "Created By", "Updated At", "Notes",
]

TEMPLATE_ROW = [
    "PMT-001", "RMT-001", "", "Этап 1", "Описание", "1", "Триггер",
    "fixed", "150000.00", "", "KZT", "active",
    "2026-01-01 00:00:00 UTC", "dida", "2026-01-01 00:00:00 UTC", "",
]

OBLIGATION_ROW = [
    "POB-001", "BIZ-001", "PRS-001", "", "", "RM-001", "STAGE-001", "PMT-001",
    "CALLKEY-1", "Этап 1", "", "150000.00", "KZT", "", "draft",
    "0.00", "150000.00",
    "2026-01-01 00:00:00 UTC", "dida", "", "", "",
    "2026-01-01 00:00:00 UTC", "",
]

TRANSACTION_ROW = [
    "PTXN-001", "BIZ-001", "POB-001", "PRS-001",
    "50000.00", "KZT", "2026-01-05", "bank_transfer",
    "EXT-1", "", "",
    "pending", "",
    "", "", "", "",
    "2026-01-05 00:00:00 UTC", "dida", "2026-01-05 00:00:00 UTC", "",
]


def _fresh_pm():
    import importlib
    import business_core.payment_manager as pm
    return importlib.reload(pm)


def _make_sheet(headers, rows):
    sheet = MagicMock()
    values = [headers] + rows
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    return sheet


class TestSchema(unittest.TestCase):
    def test_template_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["commercial_milestone_templates"], TEMPLATE_HEADERS)

    def test_obligation_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["payment_obligations"], OBLIGATION_HEADERS)

    def test_transaction_headers_exact(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["payment_transactions"], TRANSACTION_HEADERS)

    def test_id_prefixes(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["commercial_milestone_templates"], "PMT")
        self.assertEqual(_ID_PREFIXES["payment_obligations"], "POB")
        self.assertEqual(_ID_PREFIXES["payment_transactions"], "PTXN")

    def test_no_payment_allocation_registry(self):
        from business_core.sheets import BUSINESS_HEADERS, BUSINESS_SHEET_NAMES
        self.assertNotIn("payment_allocations", BUSINESS_HEADERS)
        self.assertNotIn("payment_allocations", BUSINESS_SHEET_NAMES)

    def test_no_invoice_expense_revenue_registry(self):
        from business_core.sheets import BUSINESS_HEADERS
        for forbidden in ("invoice_registry", "expense_registry", "revenue_registry", "ledger_registry"):
            self.assertNotIn(forbidden, BUSINESS_HEADERS)

    def test_commercial_milestones_map_unaffected(self):
        """The Phase-9 hardcoded config must remain completely untouched."""
        from business_core.roadmap_manager import COMMERCIAL_MILESTONES_MAP
        self.assertIn("RMT-IZH-ALM-STANDARD-002", COMMERCIAL_MILESTONES_MAP)
        self.assertEqual(len(COMMERCIAL_MILESTONES_MAP), 1)


class TestIdGeneration(unittest.TestCase):
    def test_generate_next_template_id_empty_sheet(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TEMPLATE_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.generate_next_template_id(), "PMT-001")

    def test_generate_next_template_id_increments(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TEMPLATE_HEADERS, [TEMPLATE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.generate_next_template_id(), "PMT-002")

    def test_generate_next_obligation_id_empty_sheet(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [OBLIGATION_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.generate_next_obligation_id(), "POB-001")

    def test_generate_next_transaction_id_empty_sheet(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TRANSACTION_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.generate_next_transaction_id(), "PTXN-001")

    def test_malformed_existing_template_ids_ignored(self):
        pm = _fresh_pm()
        bad_row = list(TEMPLATE_ROW)
        bad_row[0] = "NOT-A-VALID-ID"
        sheet = _make_sheet(TEMPLATE_HEADERS, [bad_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm.generate_next_template_id(), "PMT-001")


class TestTemplateReadsAndFind(unittest.TestCase):
    def test_find_by_id_not_found(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.find_row_by_id", return_value=None):
            self.assertIsNone(pm.find_commercial_milestone_template_by_id("PMT-999"))

    def test_find_by_id_found(self):
        pm = _fresh_pm()
        row_dict = dict(zip(TEMPLATE_HEADERS, TEMPLATE_ROW))
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row_dict)):
            result = pm.find_commercial_milestone_template_by_id("PMT-001")
        self.assertEqual(result["Title"], "Этап 1")

    def test_find_templates_by_identity_exact_match_only(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TEMPLATE_HEADERS, [TEMPLATE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_templates_by_identity("RMT-001", "", "1", "Этап 1")
        self.assertEqual(len(matches), 1)

    def test_find_templates_by_identity_no_match(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TEMPLATE_HEADERS, [TEMPLATE_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_templates_by_identity("RMT-001", "", "2", "Этап 1")
        self.assertEqual(matches, [])


class TestObligationReadsAndIdempotency(unittest.TestCase):
    def test_find_obligations_by_caller_key(self):
        pm = _fresh_pm()
        sheet = _make_sheet(OBLIGATION_HEADERS, [OBLIGATION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_obligations_by_caller_key("BIZ-001", "CALLKEY-1")
        self.assertEqual(len(matches), 1)

    def test_find_obligations_by_caller_key_no_match(self):
        pm = _fresh_pm()
        sheet = _make_sheet(OBLIGATION_HEADERS, [OBLIGATION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_obligations_by_caller_key("BIZ-001", "OTHER-KEY")
        self.assertEqual(matches, [])

    def test_find_obligations_requires_both_args(self):
        pm = _fresh_pm()
        self.assertEqual(pm.find_obligations_by_caller_key("", "KEY"), [])
        self.assertEqual(pm.find_obligations_by_caller_key("BIZ-001", ""), [])

    def test_find_obligations_by_template_fallback_key(self):
        pm = _fresh_pm()
        sheet = _make_sheet(OBLIGATION_HEADERS, [OBLIGATION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_obligations_by_template_fallback_key("BIZ-001", "PMT-001", "RM-001", "STAGE-001")
        self.assertEqual(len(matches), 1)


class TestTransactionReadsAndIdempotency(unittest.TestCase):
    def test_find_transactions_by_external_id(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_transactions_by_external_id("BIZ-001", "EXT-1")
        self.assertEqual(len(matches), 1)

    def test_find_transactions_by_caller_key_no_match(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            matches = pm.find_transactions_by_caller_key("BIZ-001", "NOPE")
        self.assertEqual(matches, [])


class TestLowLevelCreation(unittest.TestCase):
    def test_create_commercial_milestone_template_requires_title(self):
        pm = _fresh_pm()
        result = pm.create_commercial_milestone_template("", "fixed")
        self.assertFalse(result["ok"])

    def test_create_commercial_milestone_template_invalid_calculation_type(self):
        pm = _fresh_pm()
        result = pm.create_commercial_milestone_template("Title", "bogus")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_MILESTONE_CALCULATION_TYPE")

    def test_create_payment_obligation_requires_business_id(self):
        pm = _fresh_pm()
        result = pm.create_payment_obligation("", "PRS-001", "100.00", "KZT")
        self.assertFalse(result["ok"])

    def test_create_payment_transaction_requires_idempotency_source(self):
        pm = _fresh_pm()
        result = pm.create_payment_transaction("BIZ-001", "POB-001", "PRS-001", "100.00", "KZT", "2026-01-01")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED")

    def test_create_payment_transaction_defaults_to_pending(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TRANSACTION_HEADERS]
        appended = {}

        def _capture_append(sheet_key, values):
            appended["row"] = values
            return 2

        with patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.append_business_row", side_effect=_capture_append):
            result = pm.create_payment_transaction(
                "BIZ-001", "POB-001", "PRS-001", "100.00", "KZT", "2026-01-01",
                external_transaction_id="EXT-9",
            )
        self.assertTrue(result["ok"])
        idx = TRANSACTION_HEADERS.index("Status")
        self.assertEqual(appended["row"][idx], "pending")


class TestAdminFieldImmutability(unittest.TestCase):
    def test_template_identity_fields_blocked(self):
        pm = _fresh_pm()
        result = pm.update_commercial_milestone_template_admin_fields("PMT-001", {"Fixed Amount": "999.00"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_TRANSACTION_IMMUTABLE")

    def test_obligation_identity_fields_blocked(self):
        pm = _fresh_pm()
        result = pm.update_payment_obligation_admin_fields("POB-001", {"Obligation Amount": "999.00"})
        self.assertFalse(result["ok"])

    def test_obligation_status_not_editable_via_admin(self):
        pm = _fresh_pm()
        result = pm.update_payment_obligation_admin_fields("POB-001", {"Status": "paid"})
        self.assertFalse(result["ok"])

    def test_transaction_identity_fields_blocked(self):
        pm = _fresh_pm()
        result = pm.update_payment_transaction_admin_fields("PTXN-001", {"Amount": "999.00"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_TRANSACTION_IMMUTABLE")

    def test_transaction_notes_blocked_once_confirmed(self):
        pm = _fresh_pm()
        confirmed_row = dict(zip(TRANSACTION_HEADERS, TRANSACTION_ROW))
        confirmed_row["Status"] = "confirmed"
        with patch("business_core.sheets.find_row_by_id", return_value=(2, confirmed_row)):
            result = pm.update_payment_transaction_admin_fields("PTXN-001", {"Notes": "updated"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "PAYMENT_TRANSACTION_IMMUTABLE")

    def test_transaction_notes_allowed_while_pending(self):
        pm = _fresh_pm()
        pending_row = dict(zip(TRANSACTION_HEADERS, TRANSACTION_ROW))
        sheet = MagicMock()
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, pending_row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_payment_transaction_admin_fields("PTXN-001", {"Notes": "updated"})
        self.assertTrue(result["ok"])


class TestNoHardDelete(unittest.TestCase):
    def test_no_delete_function_exists(self):
        pm = _fresh_pm()
        names = [n for n in dir(pm) if "delete" in n.lower()]
        self.assertEqual(names, [])


# ─────────────────────────────────────────────────────────────
# Phase 17E-2A3-H1: manager-level exception logging secrecy.
# Proves _find_obligation_row and
# update_payment_obligation_admin_fields log only a fixed literal
# on infrastructure exceptions — no raw exception text, no entity
# ID, no updates dict, no row content — and that the returned
# "error" string is likewise a fixed safe value, not str(exc).
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


class TestFindObligationRowExceptionSecrecy(unittest.TestCase):
    def test_no_secrets_in_log_call_args(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn:
            result = pm._find_obligation_row("POB-001")
        self.assertIsNone(result)
        mock_warn.assert_called_once()
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_log_call_is_fixed_string(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn:
            pm._find_obligation_row("POB-001")
        mock_warn.assert_called_once_with("_find_obligation_row infrastructure failure")


class TestUpdatePaymentObligationAdminFieldsExceptionSecrecy(unittest.TestCase):
    def _row(self):
        return dict(zip(OBLIGATION_HEADERS, OBLIGATION_ROW))

    def test_notes_write_exception_no_secrets_in_log(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_obligation_admin_fields("POB-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_payment_obligation_admin_fields infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_notes_write_exception_error_field_is_fixed_safe_string(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS
        sheet.update_cell.side_effect = _boom_with_secrets
        with patch("business_core.sheets.find_row_by_id", return_value=(2, self._row())), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_payment_obligation_admin_fields("POB-001", {"Notes": _SECRET_NOTES_MARKER})
        self.assertEqual(result["error"], "Infrastructure failure")
        for marker in _ALL_SECRET_MARKERS:
            self.assertNotIn(marker, result["error"])

    def test_updated_at_write_exception_no_secrets_in_log(self):
        pm = _fresh_pm()
        row = self._row()
        row["Notes"] = "old-value"
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS

        def update_cell_side_effect(row_num, col, value):
            if col == OBLIGATION_HEADERS.index("Updated At") + 1:
                _boom_with_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_obligation_admin_fields("POB-001", {"Notes": "new-value"})
        self.assertFalse(result["ok"])
        mock_error.assert_called_once_with("update_payment_obligation_admin_fields infrastructure failure")

    def test_success_result_unaffected(self):
        pm = _fresh_pm()
        row = self._row()
        row["Notes"] = "old"
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_payment_obligation_admin_fields("POB-001", {"Notes": "new"})
        self.assertEqual(result, {"ok": True, "changed": True, "code": "", "error": None})

    def test_unchanged_result_unaffected(self):
        pm = _fresh_pm()
        row = self._row()
        row["Notes"] = "same"
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet):
            result = pm.update_payment_obligation_admin_fields("POB-001", {"Notes": "same"})
        self.assertEqual(result, {"ok": True, "changed": False, "code": "", "error": None})
        sheet.update_cell.assert_not_called()

    def test_validation_result_codes_unaffected(self):
        # Regression guard: non-exception validation-rejection paths
        # are untouched by this hardening.
        pm = _fresh_pm()
        result = pm.update_payment_obligation_admin_fields("POB-001", {"Status": "issued"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_PAYMENT_OBLIGATION_STATUS")


_SECRET_LEDGER_MARKER = "LEDGER-SECRET"
_SECRET_TRANSACTION_MARKER = "TRANSACTION-SECRET"
_SECRET_OBLIGATION_MARKER = "OBLIGATION-SECRET"
_SECRET_BALANCE_MARKER = "BALANCE-SECRET"
_ALL_LEDGER_SECRET_MARKERS = (
    _SECRET_LEDGER_MARKER, _SECRET_TRANSACTION_MARKER, _SECRET_OBLIGATION_MARKER,
    _SECRET_BALANCE_MARKER, _SECRET_API_MARKER,
)


def _boom_with_ledger_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_SECRET_LEDGER_MARKER} and {_SECRET_TRANSACTION_MARKER} "
        f"and {_SECRET_OBLIGATION_MARKER} and {_SECRET_BALANCE_MARKER} and {_SECRET_API_MARKER}"
    )


class TestStrictTransactionLedgerRead(unittest.TestCase):
    """Phase 17E-2A6-H0: proves the strict/legacy split — a successful
    empty ledger and an infrastructure failure are structurally
    distinguishable, and both public functions share exactly one
    parsing implementation (_load_transactions_raw_strict)."""

    def test_successful_empty_ledger_returns_empty_list(self):
        pm = _fresh_pm()
        sheet = MagicMock()
        sheet.get_all_values.return_value = [TRANSACTION_HEADERS]
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            self.assertEqual(pm._load_transactions_raw_strict(), [])
            self.assertEqual(pm.list_payment_transactions_strict(), [])

    def test_successful_non_empty_ledger_matches_legacy_output(self):
        pm = _fresh_pm()
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            strict_rows = pm.list_payment_transactions_strict()
        sheet2 = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet2):
            legacy_rows = pm.list_payment_transactions()
        self.assertEqual(strict_rows, legacy_rows)
        self.assertEqual(len(strict_rows), 1)

    def test_obligation_filter_matches_legacy_semantics(self):
        pm = _fresh_pm()
        other_row = list(TRANSACTION_ROW)
        other_row[TRANSACTION_HEADERS.index("Payment Obligation ID")] = "POB-999"
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            strict = pm.list_payment_transactions_strict(payment_obligation_id="POB-001")
        sheet2 = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet2):
            legacy = pm.list_payment_transactions(payment_obligation_id="POB-001")
        self.assertEqual(strict, legacy)
        self.assertEqual(len(strict), 1)

    def test_status_filter_matches_legacy_semantics(self):
        pm = _fresh_pm()
        other_row = list(TRANSACTION_ROW)
        other_row[TRANSACTION_HEADERS.index("Status")] = "confirmed"
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            strict = pm.list_payment_transactions_strict(status="pending")
        sheet2 = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet2):
            legacy = pm.list_payment_transactions(status="pending")
        self.assertEqual(strict, legacy)
        self.assertEqual(len(strict), 1)

    def test_combined_filters_match_legacy_semantics(self):
        pm = _fresh_pm()
        other_row = list(TRANSACTION_ROW)
        other_row[TRANSACTION_HEADERS.index("Status")] = "confirmed"
        sheet = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            strict = pm.list_payment_transactions_strict(payment_obligation_id="POB-001", status="pending")
        sheet2 = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW, other_row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet2):
            legacy = pm.list_payment_transactions(payment_obligation_id="POB-001", status="pending")
        self.assertEqual(strict, legacy)
        self.assertEqual(len(strict), 1)

    def test_strict_helper_propagates_infrastructure_exception(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_ledger_secrets):
            with self.assertRaises(RuntimeError):
                pm._load_transactions_raw_strict()
            with self.assertRaises(RuntimeError):
                pm.list_payment_transactions_strict()

    def test_exception_becomes_empty_list_only_through_legacy_function(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_ledger_secrets):
            self.assertEqual(pm.list_payment_transactions(), [])
            with self.assertRaises(RuntimeError):
                pm.list_payment_transactions_strict()

    def test_legacy_fallback_log_is_fixed_literal(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_ledger_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn:
            result = pm._list_transactions_raw()
        self.assertEqual(result, [])
        mock_warn.assert_called_once_with("_list_transactions_raw infrastructure failure")

    def test_no_secret_marker_in_logger_arguments(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_ledger_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn:
            pm._list_transactions_raw()
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_LEDGER_SECRET_MARKERS:
                    self.assertNotIn(marker, text)

    def test_strict_loader_does_not_log(self):
        """The strict loader itself must not log-and-rethrow — only
        the legacy swallow path logs, avoiding duplicate logging."""
        pm = _fresh_pm()
        with patch("business_core.sheets.get_business_sheet", side_effect=_boom_with_ledger_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn, \
             patch("business_core.payment_manager.log.error") as mock_error:
            with self.assertRaises(RuntimeError):
                pm._load_transactions_raw_strict()
        mock_warn.assert_not_called()
        mock_error.assert_not_called()

    def test_strict_and_legacy_successful_outputs_identical(self):
        pm = _fresh_pm()
        sheet_a = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet_a):
            a = pm.list_payment_transactions_strict(payment_obligation_id="POB-001")
        sheet_b = _make_sheet(TRANSACTION_HEADERS, [TRANSACTION_ROW])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet_b):
            b = pm.list_payment_transactions(payment_obligation_id="POB-001")
        self.assertEqual(a, b)


_SECRET_REVERSAL_MARKER = "REVERSAL-SECRET"
_ALL_H1_SECRET_MARKERS = _ALL_LEDGER_SECRET_MARKERS + (_SECRET_REVERSAL_MARKER,)


def _boom_with_h1_secrets(*_a, **_k):
    raise RuntimeError(
        f"synthetic failure containing {_SECRET_LEDGER_MARKER} and {_SECRET_TRANSACTION_MARKER} "
        f"and {_SECRET_OBLIGATION_MARKER} and {_SECRET_BALANCE_MARKER} and {_SECRET_API_MARKER} "
        f"and {_SECRET_REVERSAL_MARKER}"
    )


def _txn_row():
    return dict(zip(TRANSACTION_HEADERS, TRANSACTION_ROW))


class TestFindTransactionRowExceptionSecrecy(unittest.TestCase):
    def test_no_secrets_in_log_call_args(self):
        pm = _fresh_pm()
        with patch("business_core.sheets.find_row_by_id", side_effect=_boom_with_h1_secrets), \
             patch("business_core.payment_manager.log.warning") as mock_warn:
            result = pm._find_transaction_row(f"PTXN-{_SECRET_TRANSACTION_MARKER}")
        self.assertIsNone(result)
        mock_warn.assert_called_once_with("_find_transaction_row infrastructure failure")
        for call in mock_warn.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_H1_SECRET_MARKERS:
                    self.assertNotIn(marker, text)


class TestUpdatePaymentTransactionStatusExceptionSecrecy(unittest.TestCase):
    def _sheet_raising_at(self, col_header):
        row = _txn_row()
        sheet = MagicMock()
        sheet.row_values.return_value = TRANSACTION_HEADERS
        target_col = TRANSACTION_HEADERS.index(col_header) + 1

        def update_cell_side_effect(row_num, col, value):
            if col == target_col:
                _boom_with_h1_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        return row, sheet

    def _run_and_assert_sanitized(self, col_header, **kwargs):
        pm = _fresh_pm()
        row, sheet = self._sheet_raising_at(col_header)
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status("PTXN-001", "confirmed", **kwargs)
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_H1_SECRET_MARKERS:
                    self.assertNotIn(marker, text)
        self.assertEqual(result, {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})

    def test_status_write_exception(self):
        self._run_and_assert_sanitized("Status", confirmed_at="2026-01-01", confirmed_by="owner")

    def test_confirmed_at_write_exception(self):
        row = _txn_row()
        row["Status"] = "pending"
        pm = _fresh_pm()
        _, sheet = self._sheet_raising_at("Confirmed At")
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status("PTXN-001", "confirmed", confirmed_at="2026-01-01", confirmed_by="owner")
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        self.assertEqual(result["error"], "Infrastructure failure")

    def test_confirmed_by_write_exception(self):
        row = _txn_row()
        row["Status"] = "confirmed"
        pm = _fresh_pm()
        _, sheet = self._sheet_raising_at("Confirmed By")
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status("PTXN-001", "confirmed", confirmed_at="2026-01-01", confirmed_by="owner")
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        self.assertEqual(result["error"], "Infrastructure failure")

    def test_reversed_at_write_exception(self):
        row = _txn_row()
        row["Status"] = "confirmed"
        pm = _fresh_pm()
        _, sheet = self._sheet_raising_at("Reversed At")
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status(
                "PTXN-001", "reversed", reversed_at="2026-01-02", reversed_by="owner", reversal_reason="x",
            )
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        self.assertEqual(result["error"], "Infrastructure failure")

    def test_reversed_by_write_exception(self):
        row = _txn_row()
        row["Status"] = "confirmed"
        pm = _fresh_pm()
        _, sheet = self._sheet_raising_at("Reversed By")
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status(
                "PTXN-001", "reversed", reversed_at="2026-01-02", reversed_by="owner", reversal_reason="x",
            )
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        self.assertEqual(result["error"], "Infrastructure failure")

    def test_reversal_reason_write_exception_no_reason_leaked(self):
        row = _txn_row()
        row["Status"] = "confirmed"
        pm = _fresh_pm()
        _, sheet = self._sheet_raising_at("Reversal Reason")
        sheet.row_values.return_value = TRANSACTION_HEADERS
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_transaction_status(
                "PTXN-001", "reversed", reversed_at="2026-01-02", reversed_by="owner",
                reversal_reason=f"secret reason {_SECRET_REVERSAL_MARKER}",
            )
        mock_error.assert_called_once_with("update_payment_transaction_status infrastructure failure")
        self.assertEqual(result["error"], "Infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                self.assertNotIn(_SECRET_REVERSAL_MARKER, str(arg))

    def test_updated_at_write_exception(self):
        self._run_and_assert_sanitized("Updated At", confirmed_at="2026-01-01", confirmed_by="owner")


class TestUpdatePaymentObligationBalanceExceptionSecrecy(unittest.TestCase):
    def _obligation_row(self):
        return dict(zip(OBLIGATION_HEADERS, OBLIGATION_ROW))

    def _run_at(self, col_header):
        pm = _fresh_pm()
        row = self._obligation_row()
        sheet = MagicMock()
        sheet.row_values.return_value = OBLIGATION_HEADERS
        target_col = OBLIGATION_HEADERS.index(col_header) + 1

        def update_cell_side_effect(row_num, col, value):
            if col == target_col:
                _boom_with_h1_secrets()

        sheet.update_cell.side_effect = update_cell_side_effect
        with patch("business_core.sheets.find_row_by_id", return_value=(2, row)), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.payment_manager.log.error") as mock_error:
            result = pm.update_payment_obligation_balance(
                "POB-001", status="partially_paid", paid_amount="1.00", remaining_amount="149999.00", paid_at="2026-01-01",
            )
        mock_error.assert_called_once_with("update_payment_obligation_balance infrastructure failure")
        for call in mock_error.call_args_list:
            for arg in list(call.args) + list(call.kwargs.values()):
                text = str(arg)
                for marker in _ALL_H1_SECRET_MARKERS:
                    self.assertNotIn(marker, text)
        self.assertEqual(result, {"ok": False, "changed": False, "code": "", "error": "Infrastructure failure"})

    def test_status_write_exception(self):
        self._run_at("Status")

    def test_paid_amount_write_exception(self):
        self._run_at("Paid Amount")

    def test_remaining_amount_write_exception(self):
        self._run_at("Remaining Amount")

    def test_paid_at_write_exception(self):
        self._run_at("Paid At")

    def test_updated_at_write_exception(self):
        self._run_at("Updated At")


if __name__ == "__main__":
    unittest.main()
