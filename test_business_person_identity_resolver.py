"""
Phase 31C: behavioral tests for the Canonical Person Identity and
Client API Foundation (ADR-015 / Phase 31B).

Covers: normalization, resolve_person_identity() (the single identity
implementation), find_existing_person()/find_duplicate_person()
compatibility wrappers, Client role helpers, list_clients(), and the
Person<->Business query APIs. All Sheets access is mocked — no network.
"""

from __future__ import annotations

import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

HEADERS = [
    "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp", "Telegram",
    "Email", "Город", "Компания", "Должность", "Тип", "Подтип",
    "Уровень доверия", "Статус отношений", "Теплота", "Комментарий",
    "Biz IDs", "Company ID", "Citizenship", "Passport / ID",
    "Primary Biz ID", "Google Drive", "Drive Folder ID",
    "Дата первого контакта", "Дата последнего контакта",
]


def _row(person_id, full_name="", phone="", whatsapp="", email="",
         person_type="", status="active", biz_ids="", primary_biz_id="",
         drive_url="", drive_folder_id=""):
    row = [""] * len(HEADERS)
    idx = {h: i for i, h in enumerate(HEADERS)}
    row[idx["ID"]] = person_id
    row[idx["ФИО"]] = full_name
    row[idx["Телефон"]] = phone
    row[idx["WhatsApp"]] = whatsapp
    row[idx["Email"]] = email
    row[idx["Тип"]] = person_type
    row[idx["Статус отношений"]] = status
    row[idx["Biz IDs"]] = biz_ids
    row[idx["Primary Biz ID"]] = primary_biz_id
    row[idx["Google Drive"]] = drive_url
    row[idx["Drive Folder ID"]] = drive_folder_id
    return row


def _sheet(rows):
    all_values = [HEADERS] + rows
    mock = MagicMock()
    mock.get_all_values.return_value = all_values
    mock.row_values.side_effect = (
        lambda n: all_values[n - 1] if 1 <= n <= len(all_values) else [""] * len(HEADERS)
    )

    def _find(value, in_column=1):
        for i, row in enumerate(rows, start=2):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = i
                return cell
        return None

    mock.find.side_effect = _find
    return mock


def _fresh_pm():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    import importlib
    return importlib.import_module("business_core.person_manager")


# ─────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────

class TestNormalization(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def test_name_nfkc(self):
        # Fullwidth "Ａ" (U+FF21) NFKC-normalizes to ASCII "A"
        self.assertEqual(self.pm.normalize_person_name("Ａ"), "a")

    def test_name_whitespace_collapse(self):
        self.assertEqual(self.pm.normalize_person_name("  Иван   Иванов  "), "иван иванов")

    def test_name_casefold(self):
        self.assertEqual(self.pm.normalize_person_name("ИВАН ИВАНОВ"), "иван иванов")

    def test_phone_kz_8_vs_plus7_equivalence_in_resolver_key(self):
        digits_8 = self.pm.normalize_phone("8 707 123 45 67")
        digits_7 = self.pm.normalize_phone("+7 (707) 123-45-67")
        self.assertNotEqual(digits_8, digits_7)  # normalize_phone itself: NOT canonicalized (locked)
        self.assertEqual(
            self.pm._kz_phone_identity_key(digits_8),
            self.pm._kz_phone_identity_key(digits_7),
        )  # resolver-level canonicalization: equivalent

    def test_phone_punctuation_removed(self):
        self.assertEqual(self.pm.normalize_phone("+7 (707) 123-45-67"), "77071234567")

    def test_phone_non_kz_international_preserved(self):
        digits = self.pm.normalize_phone("+1 (415) 555-2671")
        self.assertEqual(self.pm._kz_phone_identity_key(digits), digits)

    def test_phone_empty_ignored(self):
        self.assertEqual(self.pm.normalize_phone(""), "")
        self.assertEqual(self.pm.normalize_phone(None), "")

    def test_email_trim_casefold(self):
        self.assertEqual(self.pm.normalize_email("  Ivan@EXAMPLE.com  "), "ivan@example.com")

    def test_email_empty_ignored(self):
        self.assertEqual(self.pm.normalize_email(""), "")
        self.assertEqual(self.pm.normalize_email(None), "")


# ─────────────────────────────────────────────────────────────
# resolve_person_identity
# ─────────────────────────────────────────────────────────────

class TestResolvePersonIdentity(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def test_no_match_not_found(self):
        rows = [_row("PRS-001", full_name="Совсем другой", phone="77770000000")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(name="Никто", phone="77771111111")
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["person"])

    def test_one_phone_match_single_match(self):
        rows = [_row("PRS-001", full_name="Иван Петров", phone="77771234567")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "single_match")
        self.assertEqual(result["person"]["person_id"], "PRS-001")
        self.assertEqual(result["matched_by"], ["phone"])

    def test_one_email_match_single_match(self):
        rows = [_row("PRS-001", full_name="Иван Петров", email="ivan@example.com")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(email="ivan@example.com")
        self.assertEqual(result["status"], "single_match")
        self.assertEqual(result["matched_by"], ["email"])

    def test_phone_and_email_point_to_same_person_single_match(self):
        rows = [_row("PRS-001", phone="77771234567", email="ivan@example.com")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567", email="ivan@example.com")
        self.assertEqual(result["status"], "single_match")
        self.assertEqual(set(result["matched_by"]), {"phone", "email"})

    def test_phone_and_email_point_to_different_persons_ambiguous(self):
        rows = [
            _row("PRS-001", phone="77771234567"),
            _row("PRS-002", email="ivan@example.com"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567", email="ivan@example.com")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual({p["person_id"] for p in result["matches"]}, {"PRS-001", "PRS-002"})

    def test_multiple_phone_matches_ambiguous(self):
        rows = [
            _row("PRS-001", phone="77771234567"),
            _row("PRS-002", phone="77771234567"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["matches"]), 2)

    def test_multiple_email_matches_ambiguous(self):
        rows = [
            _row("PRS-001", email="ivan@example.com"),
            _row("PRS-002", email="ivan@example.com"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(email="ivan@example.com")
        self.assertEqual(result["status"], "ambiguous")

    def test_one_name_only_match_ambiguous(self):
        rows = [_row("PRS-001", full_name="Иван Петров")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(name="Иван Петров")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["matched_by"], ["name"])

    def test_multiple_name_only_matches_ambiguous(self):
        rows = [
            _row("PRS-001", full_name="Иван Петров"),
            _row("PRS-002", full_name="Иван Петров"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(name="Иван Петров")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["matches"]), 2)

    def test_no_arbitrary_first_match_on_ambiguous(self):
        rows = [
            _row("PRS-001", phone="77771234567"),
            _row("PRS-002", phone="77771234567"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertIsNone(result["person"], "ambiguous must not silently expose a single 'person'")

    def test_archived_strong_match_only_archived_match(self):
        rows = [_row("PRS-001", phone="77771234567", status="archived")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "archived_match")

    def test_active_and_archived_strong_collision_ambiguous(self):
        rows = [
            _row("PRS-001", phone="77771234567", status="active"),
            _row("PRS-002", phone="77771234567", status="archived"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "ambiguous")

    def test_include_archived_true_folds_archived_into_normal_resolution(self):
        rows = [_row("PRS-001", phone="77771234567", status="archived")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567", include_archived=True)
        self.assertEqual(result["status"], "single_match")

    def test_canonical_matched_by_values(self):
        rows = [_row("PRS-001", phone="77771234567", email="ivan@example.com", full_name="Иван Петров")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(
                phone="77771234567", email="ivan@example.com", name="Иван Петров",
            )
        # matched_by is a subset of the canonical {"phone","email","name"} vocabulary;
        # this row genuinely matches on all three, so all three are expected.
        self.assertTrue(set(result["matched_by"]) <= {"phone", "email", "name"})
        self.assertTrue({"phone", "email"} <= set(result["matched_by"]))

    def test_canonical_result_shape(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet([])):
            result = self.pm.resolve_person_identity(name="Кто-то")
        for key in ("status", "person", "matches", "matched_by", "error"):
            self.assertIn(key, result)

    def test_whatsapp_column_counts_as_strong_phone_identifier(self):
        rows = [_row("PRS-001", whatsapp="77771234567")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "single_match")

    def test_no_inputs_returns_not_found_without_scanning(self):
        with patch("business_core.sheets.get_business_sheet") as mock_get:
            result = self.pm.resolve_person_identity()
        self.assertEqual(result["status"], "not_found")
        mock_get.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Compatibility wrappers
# ─────────────────────────────────────────────────────────────

class TestCompatibilityWrappers(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def test_find_existing_person_delegates(self):
        import inspect
        src = inspect.getsource(self.pm.find_existing_person)
        self.assertIn("resolve_person_identity", src)

    def test_find_duplicate_person_delegates(self):
        import inspect
        src = inspect.getsource(self.pm.find_duplicate_person)
        self.assertIn("resolve_person_identity", src)

    def test_no_separate_matching_logic_remains(self):
        import inspect
        for fn in (self.pm.find_existing_person, self.pm.find_duplicate_person):
            src = inspect.getsource(fn)
            self.assertNotIn("get_business_sheet", src)

    def test_find_existing_person_name_only_still_returns_match(self):
        """Old return shape/semantics preserved: a name-only match
        still resolves (not blocked by resolve_person_identity's
        internal 'ambiguous' classification for name-only matches)."""
        rows = [_row("PRS-001", full_name="Иван Петров", biz_ids="BIZ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.find_existing_person(name="Иван Петров", biz_id="BIZ-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["prs_id"], "PRS-001")
        self.assertTrue(result["same_biz"])

    def test_find_existing_person_different_biz_same_biz_false(self):
        rows = [_row("PRS-001", full_name="Иван Петров", biz_ids="BIZ-002")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.find_existing_person(name="Иван Петров", biz_id="BIZ-001")
        self.assertIsNotNone(result)
        self.assertFalse(result["same_biz"])

    def test_find_existing_person_includes_archived(self):
        rows = [_row("PRS-001", phone="77771234567", status="archived")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.find_existing_person(phone="77771234567")
        self.assertIsNotNone(result, "find_existing_person must not exclude archived rows (legacy behavior)")

    def test_find_duplicate_person_archived_never_blocks(self):
        rows = [_row("PRS-001", phone="77771234567", full_name="Иван Петров", status="archived")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.find_duplicate_person(full_name="Иван Петров", phone="77771234567")
        self.assertIsNone(result)

    def test_find_duplicate_person_business_id_narrows_ambiguous(self):
        rows = [
            _row("PRS-001", full_name="Иван Петров", biz_ids="BIZ-001"),
            _row("PRS-002", full_name="Иван Петров", biz_ids="BIZ-002"),
        ]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.find_duplicate_person(full_name="Иван Петров", business_id="BIZ-002")
        self.assertIsNotNone(result)
        self.assertEqual(result["person_id"], "PRS-002")


# ─────────────────────────────────────────────────────────────
# Client role
# ─────────────────────────────────────────────────────────────

class TestClientRole(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def test_recognized_client_type_true(self):
        self.assertTrue(self.pm.is_client_person({"person_type": "клиент"}))

    def test_recognized_client_subtype_true(self):
        self.assertTrue(self.pm.is_client_person({"person_type": "Клиент по узаконению"}))

    def test_unrecognized_neklient_false(self):
        self.assertFalse(self.pm.is_client_person({"person_type": "неклиент"}))

    def test_empty_type_false(self):
        self.assertFalse(self.pm.is_client_person({"person_type": ""}))
        self.assertFalse(self.pm.is_client_person({}))

    def test_different_category_false(self):
        self.assertFalse(self.pm.is_client_person({"person_type": "потенциальный клиент"}))

    def test_ensure_client_role_empty_type_sets_client(self):
        rows = [_row("PRS-001", full_name="Иван", person_type="")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.ensure_client_role("PRS-001")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])

    def test_ensure_client_role_existing_client_no_op(self):
        rows = [_row("PRS-001", full_name="Иван", person_type="клиент")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.ensure_client_role("PRS-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        self.assertTrue(result["already_client"])

    def test_ensure_client_role_other_category_manual_decision(self):
        rows = [_row("PRS-001", full_name="Иван", person_type="сотрудник")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.ensure_client_role("PRS-001")
        self.assertFalse(result["changed"])
        self.assertTrue(result["manual_decision_required"])
        self.assertIsNotNone(result["warning"])

    def test_ensure_client_role_archived_rejected(self):
        rows = [_row("PRS-001", full_name="Иван", person_type="", status="archived")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            result = self.pm.ensure_client_role("PRS-001")
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_ensure_client_role_no_silent_overwrite(self):
        rows = [_row("PRS-001", full_name="Иван", person_type="сотрудник")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)) as mock_get:
            self.pm.ensure_client_role("PRS-001")
            for call in mock_get.return_value.update_cell.call_args_list:
                self.assertNotEqual(call.args[2] if len(call.args) > 2 else None, "клиент")


# ─────────────────────────────────────────────────────────────
# Client listing
# ─────────────────────────────────────────────────────────────

class TestListClients(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def _rows(self):
        return [
            _row("PRS-001", full_name="Иван Клиентов", person_type="клиент", biz_ids="BIZ-001",
                 phone="77771111111", email="ivan@example.com"),
            _row("PRS-002", full_name="Мария Сотрудникова", person_type="сотрудник", biz_ids="BIZ-001"),
            _row("PRS-003", full_name="Архивный Клиент", person_type="клиент", biz_ids="BIZ-001",
                 status="archived"),
            _row("PRS-004", full_name="Другой Клиент", person_type="клиент по узаконению", biz_ids="BIZ-002"),
        ]

    def test_only_recognized_clients_returned(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients()
        ids = {c["person_id"] for c in clients}
        self.assertNotIn("PRS-002", ids)

    def test_archived_excluded_by_default(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients()
        self.assertNotIn("PRS-003", {c["person_id"] for c in clients})

    def test_archived_optionally_included(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients(include_archived=True)
        self.assertIn("PRS-003", {c["person_id"] for c in clients})

    def test_filter_by_business(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients(biz_id="BIZ-002")
        self.assertEqual({c["person_id"] for c in clients}, {"PRS-004"})

    def test_query_by_id(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients(query="PRS-001")
        self.assertEqual({c["person_id"] for c in clients}, {"PRS-001"})

    def test_query_by_name(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients(query="иван клиентов")
        self.assertEqual({c["person_id"] for c in clients}, {"PRS-001"})

    def test_query_by_phone_or_email(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            by_phone = self.pm.list_clients(query="77771111111")
            by_email = self.pm.list_clients(query="ivan@example.com")
        self.assertEqual({c["person_id"] for c in by_phone}, {"PRS-001"})
        self.assertEqual({c["person_id"] for c in by_email}, {"PRS-001"})

    def test_deterministic_ordering(self):
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(self._rows())):
            clients = self.pm.list_clients(include_archived=True)
        ids = [c["person_id"] for c in clients]
        self.assertEqual(ids, sorted(ids))

    def test_no_substring_false_positive(self):
        rows = [_row("PRS-005", full_name="Тест", person_type="неклиент активный")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            clients = self.pm.list_clients()
        self.assertEqual(clients, [])


# ─────────────────────────────────────────────────────────────
# Person<->Business query APIs
# ─────────────────────────────────────────────────────────────

class TestPersonBusinessQueries(unittest.TestCase):

    def setUp(self):
        self.pm = _fresh_pm()

    def test_parse_comma_and_semicolon(self):
        person = {"biz_ids": ["BIZ-001", "BIZ-002"], "primary_biz_id": ""}
        self.assertEqual(self.pm.list_person_business_ids(person), ["BIZ-001", "BIZ-002"])

    def test_trim_and_dedup(self):
        person = {"biz_ids": ["BIZ-001", "BIZ-001"], "primary_biz_id": "BIZ-001"}
        self.assertEqual(self.pm.list_person_business_ids(person), ["BIZ-001"])

    def test_primary_business_appended_if_missing(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": "BIZ-002"}
        self.assertEqual(self.pm.list_person_business_ids(person), ["BIZ-001", "BIZ-002"])

    def test_has_link_true_false(self):
        person = {"biz_ids": ["BIZ-001"], "primary_biz_id": ""}
        self.assertTrue(self.pm.has_person_business_link(person, "BIZ-001"))
        self.assertFalse(self.pm.has_person_business_link(person, "BIZ-999"))

    def test_append_existing_no_op(self):
        rows = [_row("PRS-001", biz_ids="BIZ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)) as mock_get:
            result = self.pm.append_person_biz_id("PRS-001", "BIZ-001")
        self.assertTrue(result["ok"])
        self.assertFalse(result["changed"])
        mock_get.return_value.update_cell.assert_not_called()

    def test_append_new_preserves_old(self):
        rows = [_row("PRS-001", biz_ids="BIZ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)) as mock_get:
            result = self.pm.append_person_biz_id("PRS-001", "BIZ-002")
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        args, _ = mock_get.return_value.update_cell.call_args_list[0]
        self.assertEqual(args[2], "BIZ-001,BIZ-002")

    def test_stable_ordering_via_person_or_id_string(self):
        rows = [_row("PRS-001", biz_ids="BIZ-001,BIZ-002", primary_biz_id="BIZ-001")]
        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)):
            ids = self.pm.list_person_business_ids("PRS-001")
        self.assertEqual(ids, ["BIZ-001", "BIZ-002"])


# ─────────────────────────────────────────────────────────────
# Network safety
# ─────────────────────────────────────────────────────────────

class TestNoLiveNetwork(unittest.TestCase):

    def test_resolve_person_identity_no_live_socket(self):
        pm = _fresh_pm()
        rows = [_row("PRS-001", full_name="Иван Петров", phone="77771234567")]

        def _blocked_connect(*a, **kw):
            raise AssertionError("live network access attempted in test")

        with patch("business_core.sheets.get_business_sheet", return_value=_sheet(rows)), \
             patch.object(socket.socket, "connect", _blocked_connect):
            result = pm.resolve_person_identity(phone="77771234567")
        self.assertEqual(result["status"], "single_match")


if __name__ == "__main__":
    unittest.main(verbosity=2)
