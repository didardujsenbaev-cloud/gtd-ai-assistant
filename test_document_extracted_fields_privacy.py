"""
Phase 16B.2.1: Telegram Extracted Fields Privacy Hardening.

Narrow, standalone hotfix — /docanalysis's "Извлечённые поля" block
(raw, free-form extracted_fields) was showing sensitive keys/values
verbatim (ИИН, БИН, доверенность, нотариальная лицензия, ...) in
production. This adds a key-name denylist filter — NEVER touches
Sheets, document_intelligence.py, the AI prompt, duplicate logic,
DOCUMENT_REGISTRY, or the Completion Gate. Structured fields
("Реквизиты") and the duplicate block are untouched.

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
        # Phase 16B.4: /docanalysis renders through effective_structured_fields.
        from business_core.document_intelligence import bool_to_cell
        from business_core.document_confirmation import build_effective_structured_fields
        content_row = {
            "Document Number": self.document_number, "Document Date": self.document_date,
            "Issued By": self.issued_by, "Valid From": self.valid_from, "Valid Until": self.valid_until,
            "Has Expiration": bool_to_cell(self.has_expiration), "Direction": self.direction,
            "Requires Action": bool_to_cell(self.requires_action),
        }
        self.effective_structured_fields = build_effective_structured_fields(content_row, {})


class TestIsSensitiveFieldKey(unittest.TestCase):
    def setUp(self):
        self.th = _fresh_th()

    def test_owner_iin_hidden(self):
        """п.1."""
        self.assertTrue(self.th._is_sensitive_field_key("owner_iin"))

    def test_owner_IIN_mixed_case_hidden(self):
        """п.2/п.15."""
        self.assertTrue(self.th._is_sensitive_field_key("owner IIN"))

    def test_iin_sobstvennika_russian_hidden(self):
        """п.3."""
        self.assertTrue(self.th._is_sensitive_field_key("ИИН собственника"))

    def test_contractor_bin_hidden(self):
        """п.4."""
        self.assertTrue(self.th._is_sensitive_field_key("contractor_bin"))

    def test_bin_organizatsii_russian_hidden(self):
        """п.5."""
        self.assertTrue(self.th._is_sensitive_field_key("БИН проектной организации"))

    def test_passport_hidden(self):
        """п.6."""
        self.assertTrue(self.th._is_sensitive_field_key("passport"))
        self.assertTrue(self.th._is_sensitive_field_key("паспорт"))

    def test_phone_hidden(self):
        """п.7."""
        self.assertTrue(self.th._is_sensitive_field_key("телефон"))
        self.assertTrue(self.th._is_sensitive_field_key("phone"))

    def test_email_hidden(self):
        """п.8."""
        self.assertTrue(self.th._is_sensitive_field_key("email"))
        self.assertTrue(self.th._is_sensitive_field_key("e-mail"))

    def test_iban_hidden(self):
        """п.9."""
        self.assertTrue(self.th._is_sensitive_field_key("IBAN"))

    def test_bank_account_hidden(self):
        """п.10."""
        self.assertTrue(self.th._is_sensitive_field_key("bank_account"))
        self.assertTrue(self.th._is_sensitive_field_key("банковский счет"))
        self.assertTrue(self.th._is_sensitive_field_key("банковский счёт"))
        self.assertTrue(self.th._is_sensitive_field_key("расчетный счет"))
        self.assertTrue(self.th._is_sensitive_field_key("расчётный счёт"))

    def test_power_of_attorney_hidden(self):
        """п.11 — real production key from DREG-004."""
        self.assertTrue(self.th._is_sensitive_field_key("power_of_attorney_number"))
        self.assertTrue(self.th._is_sensitive_field_key("power of attorney"))

    def test_doverennost_nomer_hidden(self):
        """п.12."""
        self.assertTrue(self.th._is_sensitive_field_key("доверенность номер"))

    def test_notary_license_hidden(self):
        """п.13 — real production key from DREG-004."""
        self.assertTrue(self.th._is_sensitive_field_key("notary_license"))

    def test_litsenziya_notariusa_hidden(self):
        """п.14."""
        self.assertTrue(self.th._is_sensitive_field_key("лицензия нотариуса"))

    def test_underscores_and_hyphens_normalized(self):
        """п.16."""
        self.assertTrue(self.th._is_sensitive_field_key("owner-iin"))
        self.assertTrue(self.th._is_sensitive_field_key("owner.iin"))
        self.assertTrue(self.th._is_sensitive_field_key("owner/iin"))

    def test_slitno_concatenated_form_hidden(self):
        """Collapsed/concatenated forms of multi-word tokens are still
        caught (e.g. 'poweroftattorney', 'bankaccount')."""
        self.assertTrue(self.th._is_sensitive_field_key("powerofattorney"))
        self.assertTrue(self.th._is_sensitive_field_key("bankaccount"))

    # ── Safe fields ──

    def test_safe_address_shown(self):
        """п.17."""
        self.assertFalse(self.th._is_sensitive_field_key("address"))

    def test_safe_contractor_developer_owner_name_shown(self):
        """п.18."""
        self.assertFalse(self.th._is_sensitive_field_key("contractor"))
        self.assertFalse(self.th._is_sensitive_field_key("developer"))
        self.assertFalse(self.th._is_sensitive_field_key("owner_name"))

    def test_safe_area_shown(self):
        """п.19."""
        self.assertFalse(self.th._is_sensitive_field_key("total_area_sqm"))
        self.assertFalse(self.th._is_sensitive_field_key("living_area"))

    def test_safe_cost_shown(self):
        """п.20."""
        self.assertFalse(self.th._is_sensitive_field_key("total_cost"))
        self.assertFalse(self.th._is_sensitive_field_key("estimated_cost_tenge"))

    def test_safe_dates_shown(self):
        self.assertFalse(self.th._is_sensitive_field_key("construction_start"))
        self.assertFalse(self.th._is_sensitive_field_key("construction_end"))
        self.assertFalse(self.th._is_sensitive_field_key("document_date"))

    def test_narrow_tokens_never_used_alone(self):
        """Bare 'account'/'number'/'id'/'license'/'bank' must NEVER
        alone trigger hiding — too many false positives."""
        for key in ("account_manager", "order_number", "object_id",
                    "driver_license", "bank"):
            self.assertFalse(self.th._is_sensitive_field_key(key), key)


class TestSplitSafeAndSensitiveFields(unittest.TestCase):
    def setUp(self):
        self.th = _fresh_th()

    def test_real_dreg004_payload_split(self):
        """Real production DREG-004 extracted_fields — verifies the
        exact split against actual data seen in this engagement."""
        fields = {
            "address": "г. Алматы, ...",
            "contractor": "ТОО «Forum Group KZ»",
            "contractor_bin": "240340030219",
            "contractor_director": "Бериккара Арайым Бакытжанкызы",
            "date_signed": "22.07.2026",
            "end_date": "июнь 2026 г.",
            "living_area": "92.0 кв.м.",
            "notary_license": "15015860",
            "object_type": "квартира",
            "owner_iin": "781015300461",
            "owner_name": "Адилов Жандос Жанатович",
            "power_of_attorney_number": "18/02-10",
            "representative_iin": "860714351651",
            "representative_name": "Дуйсенбаев Диара Рымбаевич",
            "start_date": "февраль 2026 г.",
            "total_area": "142.5 кв.м.",
            "total_cost": "15 000 000 тенге",
        }
        safe, hidden = self.th._split_safe_and_sensitive_fields(fields)
        self.assertNotIn("contractor_bin", safe)
        self.assertNotIn("notary_license", safe)
        self.assertNotIn("owner_iin", safe)
        self.assertNotIn("power_of_attorney_number", safe)
        self.assertNotIn("representative_iin", safe)
        self.assertIn("address", safe)
        self.assertIn("contractor", safe)
        self.assertIn("owner_name", safe)
        self.assertIn("total_cost", safe)
        self.assertEqual(hidden, 5)


class TestRenderRequisitesUnaffected(unittest.TestCase):
    """п.24-26: everything except the raw fields block is untouched."""

    def test_docanalysis_otherwise_unchanged(self):
        th = _fresh_th()
        result = _FakeResult(document_number="18/02-10", fields={})
        text = th._render_document_analysis(result)
        self.assertIn("Document ID: DREG-001", text)
        self.assertIn("Реквизиты:", text)
        self.assertIn("Номер документа: 18/02-10", text)

    def test_duplicate_block_unchanged(self):
        th = _fresh_th()
        result = _FakeResult(
            duplicate_status="EXACT_DUPLICATE", duplicate_of_document_id="DREG-004",
            duplicate_document_name="Doc", duplicate_document_status="uploaded",
            fields={"owner_iin": "123"},
        )
        text = th._render_document_analysis(result)
        self.assertIn("Обнаружен точный дубликат", text)
        self.assertIn("DREG-004", text)

    def test_structured_fields_block_unchanged(self):
        th = _fresh_th()
        result = _FakeResult(
            document_date="2026-07-22", direction="internal",
            fields={"owner_iin": "123"},
        )
        text = th._render_document_analysis(result)
        self.assertIn("Дата документа: 2026-07-22", text)
        self.assertIn("Направление: внутренний", text)


class TestRenderExtractedFieldsBlock(unittest.TestCase):
    def test_all_sensitive_fallback_message_and_count(self):
        """п.21: hidden count shown; п.'fallback' when nothing safe left."""
        th = _fresh_th()
        result = _FakeResult(fields={"owner_iin": "781015300461", "contractor_bin": "240340030219"})
        text = th._render_document_analysis(result)
        self.assertIn("🔒 Чувствительные данные скрыты.", text)
        self.assertIn("🔒 Скрыто чувствительных полей: 2", text)
        self.assertNotIn("781015300461", text)
        self.assertNotIn("240340030219", text)
        self.assertNotIn("owner_iin", text)
        self.assertNotIn("owner iin", text)

    def test_mixed_safe_and_sensitive_shows_both(self):
        th = _fresh_th()
        result = _FakeResult(fields={
            "address": "г. Алматы, ул. Абая 1",
            "owner_iin": "781015300461",
        })
        text = th._render_document_analysis(result)
        self.assertIn("address: г. Алматы, ул. Абая 1", text)
        self.assertIn("🔒 Скрыто чувствительных полей: 1", text)
        self.assertNotIn("781015300461", text)
        self.assertNotIn("owner iin", text)

    def test_all_safe_no_hidden_line(self):
        th = _fresh_th()
        result = _FakeResult(fields={"address": "г. Алматы", "total_cost": "1000000"})
        text = th._render_document_analysis(result)
        self.assertIn("address: г. Алматы", text)
        self.assertNotIn("🔒", text)

    def test_no_fields_at_all_no_block(self):
        th = _fresh_th()
        result = _FakeResult(fields={})
        text = th._render_document_analysis(result)
        self.assertNotIn("Извлечённые поля:", text)

    def test_raw_values_unchanged_in_result_object(self):
        """п.22: filtering is render-only — the result object itself
        (as produced by document_query) is never mutated."""
        th = _fresh_th()
        fields = {"owner_iin": "781015300461", "address": "г. Алматы"}
        result = _FakeResult(fields=fields)
        th._render_document_analysis(result)
        self.assertEqual(result.fields, {"owner_iin": "781015300461", "address": "г. Алматы"})

    def test_invalid_fields_json_message_unaffected(self):
        th = _fresh_th()
        result = _FakeResult(fields_valid=False, fields={})
        text = th._render_document_analysis(result)
        self.assertIn("некорректном формате", text)


if __name__ == "__main__":
    unittest.main()
