"""
Phase 16B.2.2: Sensitive Extracted Field Value Redaction.

Root cause of the residual leak found in production: 16B.2.1's filter
only inspected KEY names — a safe key (e.g. "representative") whose
VALUE embedded a sensitive fragment ("Дуйсенбаев Диара Рымбаевич, ИИН
860714351651") passed through untouched. This adds label+value
redaction inside otherwise-safe field values. Bare digit runs are
NEVER redacted without a recognized label (would false-positive on
phone numbers, document numbers, cadastral numbers). Only email/IBAN
are matched by shape alone (both are inherently unambiguous formats).

No live network calls — pure rendering-function tests.
"""

from __future__ import annotations

import sys
import unittest


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


class _FakeResult:
    def __init__(self, **kw):
        defaults = dict(
            status="completed", document_id="DREG-001", document_name="Doc",
            file_name="file.pdf", mime_type="application/pdf",
            detected_document_type="acceptance_act", summary="Summary",
            fields={}, fields_valid=True, keywords=(), language="ru",
            page_count="1", suggested_template_id="", template_match_confidence="",
            completed_at="2026-01-01", updated_at="2026-01-01", error="",
            is_quota_error=False, is_transient_read_error=False,
            duplicate_status="", duplicate_of_document_id="",
            duplicate_checked_at="", duplicate_document_name="",
            duplicate_document_status="",
            document_number="", document_date="", issued_by="",
            valid_from="", valid_until="", has_expiration=None,
            direction="unknown", requires_action=None,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestRedactSensitiveValueFragments(unittest.TestCase):
    def setUp(self):
        self.th = _fresh_th()

    def test_iin_with_space_redacted(self):
        """п.1."""
        text, redacted = self.th._redact_sensitive_value_fragments("ИИН 781015300461")
        self.assertTrue(redacted)
        self.assertNotIn("781015300461", text)
        self.assertIn("ИИН", text)

    def test_iin_with_colon_redacted(self):
        """п.2."""
        text, redacted = self.th._redact_sensitive_value_fragments("ИИН: 781015300461")
        self.assertTrue(redacted)
        self.assertNotIn("781015300461", text)
        self.assertIn("ИИН:", text)

    def test_latin_IIN_redacted(self):
        """п.3."""
        text, redacted = self.th._redact_sensitive_value_fragments("IIN 781015300461")
        self.assertTrue(redacted)
        self.assertNotIn("781015300461", text)

    def test_mixed_case_iin_redacted(self):
        """п.4."""
        text, redacted = self.th._redact_sensitive_value_fragments("Iin 781015300461")
        self.assertTrue(redacted)
        text2, redacted2 = self.th._redact_sensitive_value_fragments("иин 781015300461")
        self.assertTrue(redacted2)

    def test_bin_redacted(self):
        """п.5."""
        text, redacted = self.th._redact_sensitive_value_fragments("БИН 240340030219")
        self.assertTrue(redacted)
        self.assertNotIn("240340030219", text)
        text2, redacted2 = self.th._redact_sensitive_value_fragments("BIN 240340030219")
        self.assertTrue(redacted2)

    def test_spaced_digits_redacted(self):
        """п.6."""
        text, redacted = self.th._redact_sensitive_value_fragments("ИИН 78 10 15 30 04 61")
        self.assertTrue(redacted)
        self.assertNotIn("78 10 15", text)

    def test_hyphenated_digits_redacted(self):
        """п.7."""
        text, redacted = self.th._redact_sensitive_value_fragments("ИИН 781015-300461")
        self.assertTrue(redacted)
        self.assertNotIn("781015-300461", text)

    def test_representative_name_preserved(self):
        """п.8 — real production example (DREG-004)."""
        text, redacted = self.th._redact_sensitive_value_fragments(
            "Дуйсенбаев Диара Рымбаевич, ИИН 860714351651"
        )
        self.assertTrue(redacted)
        self.assertIn("Дуйсенбаев Диара Рымбаевич", text)
        self.assertNotIn("860714351651", text)
        self.assertEqual(text, "Дуйсенбаев Диара Рымбаевич, ИИН [скрыто]")

    def test_poverennyy_name_preserved(self):
        """п.9 — real production example (DREG-005)."""
        text, redacted = self.th._redact_sensitive_value_fragments(
            "Дуйсенбаев Диадар Рымбаевич, ИИН: 860714351561"
        )
        self.assertTrue(redacted)
        self.assertIn("Дуйсенбаев Диадар Рымбаевич", text)
        self.assertNotIn("860714351561", text)
        self.assertEqual(text, "Дуйсенбаев Диадар Рымбаевич, ИИН: [скрыто]")

    def test_email_redacted(self):
        """п.10."""
        text, redacted = self.th._redact_sensitive_value_fragments("didar@example.com")
        self.assertTrue(redacted)
        self.assertNotIn("@", text)

    def test_email_embedded_in_longer_value_redacted_inline(self):
        text, redacted = self.th._redact_sensitive_value_fragments(
            "Контакт: didar@example.com, объект в центре"
        )
        self.assertTrue(redacted)
        self.assertIn("объект в центре", text)
        self.assertNotIn("@", text)

    def test_phone_redacted(self):
        """п.11."""
        text, redacted = self.th._redact_sensitive_value_fragments("телефон +7 700 227 8805")
        self.assertTrue(redacted)
        self.assertNotIn("8805", text)
        self.assertIn("телефон", text)

    def test_bare_phone_without_label_not_redacted(self):
        """A bare phone number with no 'телефон'/'phone' label must NOT
        be redacted — too ambiguous without context."""
        text, redacted = self.th._redact_sensitive_value_fragments("+7 700 227 8805")
        self.assertFalse(redacted)

    def test_iban_redacted(self):
        """п.12."""
        text, redacted = self.th._redact_sensitive_value_fragments("KZ86125KZT5004100100")
        self.assertTrue(redacted)
        self.assertNotIn("KZ86125KZT5004100100", text)

    def test_labeled_iban_redacted(self):
        text, redacted = self.th._redact_sensitive_value_fragments("IBAN: KZ86 125K ZT50 0410 0100")
        self.assertTrue(redacted)
        self.assertIn("IBAN:", text)

    def test_passport_number_redacted(self):
        """п.13."""
        text, redacted = self.th._redact_sensitive_value_fragments("паспорт N12345678")
        self.assertTrue(redacted)
        self.assertNotIn("N12345678", text)
        self.assertIn("паспорт", text)

    def test_power_of_attorney_number_redacted(self):
        """п.14."""
        text, redacted = self.th._redact_sensitive_value_fragments("доверенность №18/02-10")
        self.assertTrue(redacted)
        self.assertNotIn("18/02-10", text)
        self.assertIn("доверенность", text)

    def test_notary_license_number_redacted(self):
        """п.15."""
        text, redacted = self.th._redact_sensitive_value_fragments("лицензия нотариуса 15015860")
        self.assertTrue(redacted)
        self.assertNotIn("15015860", text)

    def test_safe_date_unchanged(self):
        """п.16."""
        text, redacted = self.th._redact_sensitive_value_fragments("2026-07-22")
        self.assertFalse(redacted)
        self.assertEqual(text, "2026-07-22")

    def test_safe_area_unchanged(self):
        """п.17."""
        text, redacted = self.th._redact_sensitive_value_fragments("142.5 кв.м.")
        self.assertFalse(redacted)

    def test_safe_cost_unchanged(self):
        """п.18."""
        text, redacted = self.th._redact_sensitive_value_fragments("15 000 000 тенге")
        self.assertFalse(redacted)

    def test_arbitrary_12_digits_without_label_unchanged(self):
        """п.19."""
        text, redacted = self.th._redact_sensitive_value_fragments("123456789012")
        self.assertFalse(redacted)
        self.assertEqual(text, "123456789012")

    def test_multiple_sensitive_fragments_redacted(self):
        """п.20: both ИИН and IBAN in the same value are redacted."""
        text, redacted = self.th._redact_sensitive_value_fragments(
            "ИИН 781015300461, IBAN KZ86125KZT5004100100"
        )
        self.assertTrue(redacted)
        self.assertNotIn("781015300461", text)
        self.assertNotIn("KZ86125KZT5004100100", text)


class TestSplitSafeAndSensitiveFieldsValueLevel(unittest.TestCase):
    def setUp(self):
        self.th = _fresh_th()

    def test_field_counted_once_despite_multiple_fragments(self):
        """п.21: a single value with 2 sensitive fragments still counts
        as ONE hidden field, not two."""
        fields = {"contacts": "ИИН 781015300461, телефон +7 700 227 8805"}
        safe, hidden = self.th._split_safe_and_sensitive_fields(fields)
        self.assertEqual(hidden, 1)
        self.assertIn("contacts", safe)

    def test_hidden_count_includes_redacted_values(self):
        """п.22."""
        fields = {
            "owner_iin": "781015300461",  # key-level hidden
            "representative": "Дуйсенбаев Диара Рымбаевич, ИИН 860714351651",  # value-level redacted
            "address": "г. Алматы",  # fully safe
        }
        safe, hidden = self.th._split_safe_and_sensitive_fields(fields)
        self.assertEqual(hidden, 2)
        self.assertNotIn("owner_iin", safe)
        self.assertIn("representative", safe)
        self.assertIn("address", safe)
        self.assertNotIn("860714351651", safe["representative"])

    def test_source_fields_not_mutated(self):
        """п.23."""
        fields = {"representative": "Дуйсенбаев Диара Рымбаевич, ИИН 860714351651"}
        original_value = fields["representative"]
        self.th._split_safe_and_sensitive_fields(fields)
        self.assertEqual(fields["representative"], original_value)

    def test_dreg004_like_fixture_expected_count(self):
        """Production-like DREG-004 fixture (per this session's reported
        pilot data): 2 fully-hidden keys + 1 redacted value = N=3."""
        fields = {
            "address": "г. Алматы, ...",
            "owner_iin": "781015300461",
            "contractor_bin": "240340030219",
            "representative": "Дуйсенбаев Диара Рымбаевич, ИИН 860714351651",
            "total_cost": "15 000 000 тенге",
        }
        safe, hidden = self.th._split_safe_and_sensitive_fields(fields)
        self.assertEqual(hidden, 3)
        self.assertIn("representative", safe)
        self.assertNotIn("860714351651", safe["representative"])

    def test_dreg005_like_fixture_expected_count(self):
        """Production-like DREG-005 fixture: 3 fully-hidden keys + 1
        redacted value = N=4."""
        fields = {
            "address": "г. Алматы, ...",
            "owner_iin": "781015300461",
            "developer_bin": "240340030219",
            "notary_license": "15015860",
            "поверенный": "Дуйсенбаев Диадар Рымбаевич, ИИН: 860714351561",
            "total_cost": "15 000 000 тенге",
        }
        safe, hidden = self.th._split_safe_and_sensitive_fields(fields)
        self.assertEqual(hidden, 4)
        self.assertIn("поверенный", safe)
        self.assertNotIn("860714351561", safe["поверенный"])


class TestRenderDocumentAnalysisValueRedaction(unittest.TestCase):
    def test_representative_value_redacted_in_render(self):
        th = _fresh_th()
        result = _FakeResult(fields={
            "representative": "Дуйсенбаев Диара Рымбаевич, ИИН 860714351651",
        })
        text = th._render_document_analysis(result)
        self.assertIn("Дуйсенбаев Диара Рымбаевич", text)
        self.assertNotIn("860714351651", text)
        self.assertIn("🔒 Скрыто чувствительных полей: 1", text)

    def test_duplicate_block_unchanged(self):
        """п.24."""
        th = _fresh_th()
        result = _FakeResult(
            duplicate_status="EXACT_DUPLICATE", duplicate_of_document_id="DREG-004",
            duplicate_document_name="Doc", duplicate_document_status="uploaded",
            fields={"representative": "Иванов Иван, ИИН 123456789012"},
        )
        text = th._render_document_analysis(result)
        self.assertIn("Обнаружен точный дубликат", text)
        self.assertIn("DREG-004", text)

    def test_structured_fields_block_unchanged(self):
        """п.25."""
        th = _fresh_th()
        result = _FakeResult(
            document_date="2026-07-22", direction="internal",
            fields={"representative": "Иванов Иван, ИИН 123456789012"},
        )
        text = th._render_document_analysis(result)
        self.assertIn("Дата: 2026-07-22", text)
        self.assertIn("Направление: внутренний", text)


if __name__ == "__main__":
    unittest.main()
