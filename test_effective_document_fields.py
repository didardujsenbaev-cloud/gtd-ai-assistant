"""
Phase 16B.4: Effective Structured Fields in Queries and Reports.

Covers: typed EffectiveStructuredField(s) model, effective-value rules
(confirmed/rejected/unreviewed), conflict-only-when-AI-known,
boolean/direction typed semantics, the ONE shared Telegram formatter
used by both /docanalysis and /reviewdoc, backward compatibility with
the legacy effective_fields dict, no-N-reads convenience helpers, and
privacy/architecture invariants.

All tests fully mock business_core.sheets — no live network calls.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch


def _fresh_dc():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_confirmation as dc
    return dc


def _fresh_dq():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_query as dq
    return dq


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _confirmed_entry(value, status="confirmed", by="didar", at="t1", version=1):
    return {"value": value, "status": status, "confirmed_by": by, "confirmed_at": at, "version": version}


# ────────────────────────────────────────────────────────────
# §4/§1: effective value rules per review state
# ────────────────────────────────────────────────────────────

class TestEffectiveValueRules(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()

    def test_unreviewed_ai_date_becomes_effective(self):
        """п.1."""
        content = {"Document Date": "2026-07-22"}
        fields = self.dc.build_effective_structured_fields(content, {})
        self.assertEqual(fields.document_date.effective_value, "2026-07-22")
        self.assertEqual(fields.document_date.source, "ai")
        self.assertEqual(fields.document_date.review_field_status, "unreviewed")

    def test_confirmed_date_overrides_ai(self):
        """п.2."""
        content = {"Document Date": "2026-07-23"}
        confirmed = {"document_date": _confirmed_entry("2026-07-22")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertEqual(fields.document_date.effective_value, "2026-07-22")
        self.assertEqual(fields.document_date.source, "human")

    def test_confirmed_same_date_no_conflict(self):
        """п.3."""
        content = {"Document Date": "2026-07-22"}
        confirmed = {"document_date": _confirmed_entry("2026-07-22")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertFalse(fields.document_date.conflict)

    def test_confirmed_different_date_conflict(self):
        """п.4."""
        content = {"Document Date": "2026-07-23"}
        confirmed = {"document_date": _confirmed_entry("2026-07-22")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertTrue(fields.document_date.conflict)

    def test_rejected_date_has_no_effective_value(self):
        """п.5: rejected != unreviewed — effective_value is None, not AI fallback."""
        content = {"Document Date": "2026-07-23"}
        confirmed = {"document_date": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertIsNone(fields.document_date.effective_value)
        self.assertEqual(fields.document_date.source, "none")
        self.assertEqual(fields.document_date.review_field_status, "rejected")

    def test_clear_date_falls_back_to_ai(self):
        """п.6: absence of a confirmed_fields entry (post-clear) ==
        unreviewed, falls back to AI."""
        content = {"Document Date": "2026-07-23"}
        fields = self.dc.build_effective_structured_fields(content, {})  # cleared -> key absent
        self.assertEqual(fields.document_date.effective_value, "2026-07-23")
        self.assertEqual(fields.document_date.review_field_status, "unreviewed")

    def test_confirmed_direction(self):
        """п.7."""
        content = {"Direction": "outgoing"}
        confirmed = {"direction": _confirmed_entry("internal")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertEqual(fields.direction.effective_value, "internal")
        self.assertEqual(fields.direction.source, "human")

    def test_rejected_direction_unknown_effective(self):
        """п.8."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertIsNone(fields.direction.effective_value)
        self.assertEqual(fields.direction.review_field_status, "rejected")

    def test_confirmed_boolean_true(self):
        """п.9."""
        content = {"Has Expiration": "false"}
        confirmed = {"has_expiration": _confirmed_entry("true")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertIs(fields.has_expiration.effective_value, True)

    def test_confirmed_boolean_false(self):
        """п.10 — must not be conflated with 'empty'."""
        content = {"Requires Action": "true"}
        confirmed = {"requires_action": _confirmed_entry("false")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertIs(fields.requires_action.effective_value, False)

    def test_rejected_boolean_none(self):
        """п.11."""
        content = {"Requires Action": "true"}
        confirmed = {"requires_action": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertIsNone(fields.requires_action.effective_value)

    def test_ai_boolean_fallback(self):
        """п.12."""
        content = {"Has Expiration": "true"}
        fields = self.dc.build_effective_structured_fields(content, {})
        self.assertIs(fields.has_expiration.effective_value, True)

    def test_source_human(self):
        """п.13."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("internal")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertEqual(fields.direction.source, "human")

    def test_source_ai(self):
        """п.14."""
        content = {"Direction": "internal"}
        fields = self.dc.build_effective_structured_fields(content, {})
        self.assertEqual(fields.direction.source, "ai")

    def test_source_none_only_for_rejected(self):
        """п.15."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertEqual(fields.direction.source, "none")

    def test_unreviewed_source_is_ai_even_when_ai_empty(self):
        """H.3: unreviewed + empty AI value is still source=ai (review
        STATE, not AI-presence) — never source=none."""
        content = {"Issued By": ""}
        fields = self.dc.build_effective_structured_fields(content, {})
        self.assertEqual(fields.issued_by.source, "ai")
        self.assertEqual(fields.issued_by.review_field_status, "unreviewed")

    def test_ai_empty_confirmed_non_empty_no_conflict(self):
        """H.5 / §3: AI value empty + human confirmed non-empty -> no conflict."""
        content = {"Issued By": ""}
        confirmed = {"issued_by": _confirmed_entry("Нотариус Ким")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertFalse(fields.issued_by.conflict)


class TestBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()

    def test_old_row_backward_compatible(self):
        """п.16."""
        content = {}  # no structured columns at all
        fields = self.dc.build_effective_structured_fields(content, {})
        self.assertEqual(fields.direction.effective_value, "")
        self.assertIsNone(fields.has_expiration.effective_value)
        self.assertEqual(fields.direction.review_field_status, "unreviewed")

    def test_malformed_json_safe_fallback(self):
        """п.17."""
        parsed = self.dc.parse_confirmed_fields_json("{not valid json")
        self.assertEqual(parsed, {})
        fields = self.dc.build_effective_structured_fields({}, parsed)
        self.assertEqual(fields.direction.review_field_status, "unreviewed")

    def test_legacy_effective_fields_dict_still_present(self):
        """п.7 of the H-list: legacy dict remains accessible."""
        content = {"Direction": "internal"}
        legacy = self.dc.compute_effective_fields(content, {})
        self.assertIn("direction", legacy)
        self.assertEqual(legacy["direction"]["effective_value"], "internal")

    def test_typed_and_legacy_semantically_consistent(self):
        """п.8 of the H-list."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("outgoing")}
        legacy = self.dc.compute_effective_fields(content, confirmed)
        typed = self.dc.build_effective_structured_fields(content, confirmed)
        self.assertEqual(legacy["direction"]["effective_value"], typed.direction.effective_value)
        self.assertEqual(legacy["direction"]["conflict"], typed.direction.conflict)


class TestConvenienceHelpersNoExtraReads(unittest.TestCase):
    def test_get_effective_document_date_with_preloaded_fields_no_read(self):
        """п.9 of H-list / §F: passing `fields=` must never trigger a read."""
        dc = _fresh_dc()
        content = {"Document Date": "2026-07-22"}
        fields = dc.build_effective_structured_fields(content, {})
        with patch("business_core.document_query.get_document_analysis") as mock_get:
            result = dc.get_effective_document_date(fields=fields)
        mock_get.assert_not_called()
        self.assertEqual(result, "2026-07-22")

    def test_get_effective_direction_with_preloaded_fields_no_read(self):
        dc = _fresh_dc()
        content = {"Direction": "outgoing"}
        fields = dc.build_effective_structured_fields(content, {})
        with patch("business_core.document_query.get_document_analysis") as mock_get:
            result = dc.get_effective_direction(fields=fields)
        mock_get.assert_not_called()
        self.assertEqual(result, "outgoing")

    def test_get_effective_requires_action_with_preloaded_fields_no_read(self):
        dc = _fresh_dc()
        content = {"Requires Action": "true"}
        fields = dc.build_effective_structured_fields(content, {})
        with patch("business_core.document_query.get_document_analysis") as mock_get:
            result = dc.get_effective_requires_action(fields=fields)
        mock_get.assert_not_called()
        self.assertIs(result, True)

    def test_multiple_fields_from_one_preloaded_result_single_read(self):
        """Reading 3 different effective fields from ONE already-loaded
        `fields` object triggers ZERO additional get_document_analysis
        calls — never N reads for N fields."""
        dc = _fresh_dc()
        content = {"Document Date": "2026-07-22", "Direction": "internal", "Requires Action": "true"}
        fields = dc.build_effective_structured_fields(content, {})
        with patch("business_core.document_query.get_document_analysis") as mock_get:
            dc.get_effective_document_date(fields=fields)
            dc.get_effective_direction(fields=fields)
            dc.get_effective_requires_action(fields=fields)
        mock_get.assert_not_called()

    def test_get_effective_structured_fields_by_document_id_is_one_read(self):
        dc = _fresh_dc()
        fake_result = MagicMock(status="completed", effective_structured_fields="SENTINEL")
        with patch("business_core.document_query.get_document_analysis", return_value=fake_result) as mock_get:
            result = dc.get_effective_structured_fields("DREG-001")
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(result, "SENTINEL")

    def test_get_effective_structured_fields_none_when_not_completed(self):
        dc = _fresh_dc()
        fake_result = MagicMock(status="processing")
        with patch("business_core.document_query.get_document_analysis", return_value=fake_result):
            result = dc.get_effective_structured_fields("DREG-001")
        self.assertIsNone(result)


# ────────────────────────────────────────────────────────────
# Telegram rendering — shared formatter
# ────────────────────────────────────────────────────────────

class TestSharedFormatterTelegramUX(unittest.TestCase):
    def setUp(self):
        self.dc = _fresh_dc()
        self.th = _fresh_th()

    def test_docanalysis_confirmed_marker(self):
        """п.21."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("internal")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("Направление: внутренний ✅ подтверждено", text)

    def test_docanalysis_ai_marker(self):
        """п.22."""
        content = {"Direction": "internal"}
        fields = self.dc.build_effective_structured_fields(content, {})
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("Направление: внутренний 🤖 AI, не проверено", text)

    def test_docanalysis_rejected_marker(self):
        """п.23."""
        content = {"Requires Action": "true"}
        confirmed = {"requires_action": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        requires_action_line = next(l for l in lines if l.startswith("Требует действия:"))
        self.assertEqual(requires_action_line, "Требует действия: отклонено человеком ❌")
        self.assertNotIn("не определено", requires_action_line)
        self.assertNotIn("unknown", requires_action_line)

    def test_docanalysis_conflict_warning(self):
        """п.24."""
        content = {"Document Date": "2026-07-23"}
        confirmed = {"document_date": _confirmed_entry("2026-07-22")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("2026-07-22 ✅ подтверждено", text)
        self.assertIn("⚠️ AI сейчас предлагает: 2026-07-23", text)

    def test_reviewdoc_uses_same_formatter(self):
        """п.25/п.6 of H-list: both commands call the exact same
        function — verified by source inspection, not just behavior."""
        import inspect
        review_source = inspect.getsource(self.th._render_review_card)
        self.assertIn("_render_effective_structured_fields_block", review_source)

        docanalysis_source = inspect.getsource(self.th._render_document_analysis)
        self.assertIn("_render_effective_structured_fields_block", docanalysis_source)

    def test_confirmed_false_shows_no_not_empty(self):
        """H.1: confirmed False must render as 'нет', never blank."""
        content = {"Requires Action": "true"}
        confirmed = {"requires_action": _confirmed_entry("false")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("Требует действия: нет ✅ подтверждено", text)

    def test_confirmed_unknown_direction_has_confirmed_marker(self):
        """H.2."""
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("unknown")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("Направление: не определено ✅ подтверждено", text)

    def test_unreviewed_unknown_direction_has_ai_marker(self):
        """H.3."""
        content = {"Direction": ""}
        fields = self.dc.build_effective_structured_fields(content, {})
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertIn("Направление: не определено 🤖 AI, не проверено", text)

    def test_rejected_unknown_differs_from_both(self):
        """H.4."""
        content = {"Direction": ""}
        confirmed = {"direction": _confirmed_entry("", status="rejected")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        direction_line = next(l for l in lines if l.startswith("Направление:"))
        self.assertEqual(direction_line, "Направление: отклонено человеком ❌")
        self.assertNotIn("🤖", direction_line)
        self.assertNotIn("✅", direction_line)

    def test_numbered_vs_unnumbered(self):
        content = {"Direction": "internal"}
        fields = self.dc.build_effective_structured_fields(content, {})
        numbered_lines = self.th._render_effective_structured_fields_block(fields, numbered=True)
        unnumbered_lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        self.assertTrue(any(line.startswith("7.") for line in numbered_lines))
        self.assertFalse(any(line.startswith("7.") for line in unnumbered_lines))

    def test_no_confirmed_fields_json_or_review_id_or_mutation_id_shown(self):
        content = {"Direction": "internal"}
        confirmed = {"direction": _confirmed_entry("internal")}
        fields = self.dc.build_effective_structured_fields(content, confirmed)
        lines = self.th._render_effective_structured_fields_block(fields, numbered=False)
        text = "\n".join(lines)
        self.assertNotIn("Review ID", text)
        self.assertNotIn("Mutation ID", text)
        self.assertNotIn("didar", text)  # actor not shown in the requisites block


# ────────────────────────────────────────────────────────────
# Privacy / architecture invariants
# ────────────────────────────────────────────────────────────

class TestArchitectureAndPrivacyInvariants(unittest.TestCase):
    def test_no_document_registry_writes_in_new_functions(self):
        """п.29."""
        import inspect
        dc = _fresh_dc()
        source = inspect.getsource(dc.build_effective_structured_fields)
        source += inspect.getsource(dc.get_effective_structured_fields)
        self.assertNotIn('update_business_row("document_registry"', source)
        self.assertNotIn('append_business_row("document_registry"', source)

    def test_no_sheets_writes_in_build_effective_structured_fields(self):
        """п.32: pure function — no write/append calls anywhere."""
        import inspect
        dc = _fresh_dc()
        source = inspect.getsource(dc.build_effective_structured_fields)
        source += inspect.getsource(dc.compute_effective_fields)
        self.assertNotIn("update_business_row(", source)
        self.assertNotIn("append_business_row(", source)

    def test_no_completion_gate_or_stage_references(self):
        """п.30/п.31."""
        import inspect
        dc = _fresh_dc()
        source = inspect.getsource(dc.build_effective_structured_fields)
        self.assertNotIn("_evaluate_document_completion_gate", source)
        self.assertNotIn("transition_stage_status", source)

    def test_privacy_key_filtering_unchanged(self):
        """п.26: sensitive-key denylist filter (16B.2.1) untouched by
        this phase — spot check still works."""
        th = _fresh_th()
        self.assertTrue(th._is_sensitive_field_key("owner_iin"))
        self.assertFalse(th._is_sensitive_field_key("address"))

    def test_privacy_value_redaction_unchanged(self):
        """п.27: value-redaction filter (16B.2.2) untouched by this phase."""
        th = _fresh_th()
        text, redacted = th._redact_sensitive_value_fragments("ИИН 781015300461")
        self.assertTrue(redacted)
        self.assertNotIn("781015300461", text)

    def test_duplicate_documents_independent_effective_state(self):
        """п.28."""
        dc = _fresh_dc()
        content_a = {"Direction": "internal"}
        confirmed_a = {"direction": _confirmed_entry("outgoing")}
        content_b = {"Direction": "internal"}
        fields_a = dc.build_effective_structured_fields(content_a, confirmed_a)
        fields_b = dc.build_effective_structured_fields(content_b, {})
        self.assertEqual(fields_a.direction.effective_value, "outgoing")
        self.assertEqual(fields_b.direction.effective_value, "internal")


# ────────────────────────────────────────────────────────────
# document_query.get_document_analysis wiring + call budget
# ────────────────────────────────────────────────────────────

class TestDocumentQueryWiring(unittest.TestCase):
    def test_effective_structured_fields_populated_no_extra_reads(self):
        """п.33: exactly the same read count as before this phase — 1
        document_registry + 1 document_content, 0 document_field_reviews."""
        dq = _fresh_dq()
        content_row = {
            "Content Status": "completed", "Direction": "internal",
            "Structured Review Status": "unreviewed",
            "Confirmed Fields JSON": "", "Structured Review Version": "0",
        }
        registry_row = {"Document Name": "Doc", "File Name": "f.pdf", "Mime Type": "application/pdf"}

        read_calls = []

        def fake_find(sheet_key, doc_id):
            read_calls.append(sheet_key)
            if sheet_key == "document_registry":
                return (2, registry_row)
            return None

        with patch("business_core.sheets.find_row_by_id", side_effect=fake_find), \
             patch("business_core.document_intelligence.get_content_status", return_value=content_row):
            result = dq.get_document_analysis("DREG-001")

        self.assertIsNotNone(result.effective_structured_fields)
        self.assertEqual(result.effective_structured_fields.direction.effective_value, "internal")
        self.assertNotIn("document_field_reviews", read_calls)
        self.assertEqual(read_calls.count("document_registry"), 1)


if __name__ == "__main__":
    unittest.main()
