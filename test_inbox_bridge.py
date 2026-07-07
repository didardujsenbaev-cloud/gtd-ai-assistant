"""
Тесты для business_core/inbox_bridge.py (Фаза 5 + 5B).

route_inbox() теперь возвращает (note: str, confirm_data: dict | None):
  confidence >= 0.9  → (note_string, None)    — сноска сразу
  0.5 <= conf < 0.9  → ("", dict)             — нужно подтверждение
  confidence < 0.5   → ("", None)             — молчать
  BC disabled        → ("", None)
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("BUSINESS_CORE_ENABLED", "true")
os.environ.setdefault("BUSINESS_SPREADSHEET_ID", "test_id")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "test_creds.json")

sys.path.insert(0, os.path.dirname(__file__))

from business_core.inbox_bridge import route_inbox, invalidate_cache, _cache


# ─────────────────────────────────────────────────────────────
# Фикстуры
# ─────────────────────────────────────────────────────────────

FAKE_BUSINESSES = [
    {"id": "BIZ-001", "name": "Узаконение", "slug": "legalization",
     "status": "active", "cities": "Алматы,Астана"},
    {"id": "BIZ-002", "name": "Недвижимость", "slug": "real_estate",
     "status": "active", "cities": "Алматы"},
]

FAKE_PEOPLE = [
    {"id": "P-001", "full_name": "Манько Андрей Сергеевич",
     "short_name": "Андрей", "person_type": "client"},
    {"id": "P-002", "full_name": "Ким Александр",
     "short_name": "Александр", "person_type": "client"},
]

FAKE_ROADMAPS = [
    {
        "roadmap_id":  "RM-001",
        "business_id": "BIZ-001",
        "client_id":   "P-001",
        "client_name": "Манько Андрей Сергеевич",
        "service_id":  "SVC-001",
        "city":        "Алматы",
        "status":      "active",
    },
]

ACTION_RESULT = {
    "результат": "Action",
    "действие":  "Позвонить клиенту",
    "область":   "Узаконение",
    "контекст":  "@Phone",
    "приоритет": "Средний",
    "время":     "15",
    "энергия":   "Средняя",
    "срок":      "",
    "пояснение": "Тест",
    "проект":    "",
}

SOMEDAY_RESULT = {
    "результат": "Someday",
    "действие":  "",
    "область":   "Личное",
    "контекст":  "",
    "приоритет": "Низкий",
    "время":     "0",
    "пояснение": "Когда-нибудь",
    "проект":    "",
}


def _patch_cache(businesses=None, people=None, roadmaps=None):
    """Патч кеша без обращения к Google Sheets."""
    _cache["businesses"] = businesses if businesses is not None else FAKE_BUSINESSES
    _cache["people"]     = people if people is not None else FAKE_PEOPLE
    _cache["roadmaps"]   = roadmaps if roadmaps is not None else FAKE_ROADMAPS
    _cache["loaded_at"]  = 9_999_999_999.0


def _make_routing(confidence=0.9, business_name="Узаконение", business_id="BIZ-001",
                  client_name="", client_id="", city="", roadmap_stage_name="",
                  needs_confirmation=False, routing_method="keyword_match"):
    """Создать фейковый результат роутера с нужным confidence."""
    return {
        "business_id":        business_id,
        "business_name":      business_name,
        "service_id":         "",
        "service_name":       "",
        "city":               city,
        "client_id":          client_id,
        "client_name":        client_name,
        "process":            "",
        "roadmap_id":         "",
        "roadmap_stage_id":   "",
        "roadmap_stage_name": roadmap_stage_name,
        "confidence":         confidence,
        "needs_confirmation": needs_confirmation,
        "routing_method":     routing_method,
        "matched_keywords":   [],
    }


# ─────────────────────────────────────────────────────────────
# Тесты возвращаемого типа
# ─────────────────────────────────────────────────────────────

class TestReturnType(unittest.TestCase):
    """route_inbox() всегда возвращает (str, dict|None)."""

    def setUp(self):
        invalidate_cache()

    def test_returns_tuple_when_bc_disabled(self):
        with patch.dict(os.environ, {"BUSINESS_CORE_ENABLED": "false"}):
            result = route_inbox("текст", ACTION_RESULT)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_returns_tuple_for_someday(self):
        _patch_cache()
        note, confirm = route_inbox("когда-нибудь", SOMEDAY_RESULT)
        self.assertIsInstance(note, str)
        self.assertIsNone(confirm)

    def test_returns_tuple_for_action(self):
        _patch_cache()
        result = route_inbox("Узаконение Алматы", ACTION_RESULT)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


# ─────────────────────────────────────────────────────────────
# Тесты по confidence
# ─────────────────────────────────────────────────────────────

class TestConfidenceLevels(unittest.TestCase):

    def setUp(self):
        invalidate_cache()
        _patch_cache()

    # ── confidence >= 0.9 → сноска сразу, confirm=None ──────

    def test_high_confidence_returns_note(self):
        """confidence >= 0.9 → note непустой, confirm=None"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.95, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("Узаконение", ACTION_RESULT)
        self.assertNotEqual(note, "")
        self.assertIsNone(confirm)

    def test_high_confidence_note_format(self):
        """Сноска при confidence=0.95 начинается с ─────"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.95, business_name="Узаконение"),
        ):
            note, _ = route_inbox("Узаконение", ACTION_RESULT)
        self.assertTrue(note.startswith("\n\n─────\n"))

    def test_exact_09_confidence_returns_note(self):
        """confidence == 0.9 → граница: возвращаем сноску сразу"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.9, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("Узаконение", ACTION_RESULT)
        self.assertNotEqual(note, "")
        self.assertIsNone(confirm)

    # ── 0.5 <= confidence < 0.9 → confirm_data, note пустой ─

    def test_medium_confidence_returns_confirm(self):
        """0.5 <= confidence < 0.9 → note пустой, confirm непустой"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.7, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("Узаконение", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNotNone(confirm)

    def test_medium_confidence_confirm_keys(self):
        """confirm_data содержит нужные ключи"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.7, business_name="Узаконение",
                                       city="Алматы"),
        ):
            _, confirm = route_inbox("Узаконение Алматы", ACTION_RESULT)
        self.assertIn("business_name", confirm)
        self.assertIn("city", confirm)
        self.assertIn("confidence", confirm)
        self.assertIn("roadmap_id", confirm)

    def test_medium_confidence_confirm_values(self):
        """confirm_data содержит правильные значения"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.75, business_name="Узаконение",
                                       city="Алматы"),
        ):
            _, confirm = route_inbox("Узаконение Алматы", ACTION_RESULT)
        self.assertEqual(confirm["business_name"], "Узаконение")
        self.assertAlmostEqual(confirm["confidence"], 0.75)

    def test_exact_05_returns_confirm(self):
        """confidence == 0.5 → нижняя граница: confirm (не молчать)"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.5, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("Узаконение", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNotNone(confirm)

    def test_just_below_09_returns_confirm(self):
        """confidence=0.89 → ещё нужно подтверждение"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.89, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("Узаконение", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNotNone(confirm)

    # ── confidence < 0.5 → молчать ──────────────────────────

    def test_low_confidence_returns_empty(self):
        """confidence < 0.5 → note пустой, confirm=None"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.3, business_name="Узаконение"),
        ):
            note, confirm = route_inbox("что-то", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNone(confirm)

    def test_zero_confidence_silent(self):
        """confidence=0.0 → полное молчание"""
        with patch(
            "business_core.business_router.route_business_context",
            return_value=_make_routing(confidence=0.0, business_name=""),
        ):
            note, confirm = route_inbox("что угодно", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNone(confirm)


# ─────────────────────────────────────────────────────────────
# Тесты на отключённый BC и ошибки
# ─────────────────────────────────────────────────────────────

class TestBCDisabledAndErrors(unittest.TestCase):

    def setUp(self):
        invalidate_cache()

    def test_bc_disabled_returns_empty_tuple(self):
        """BUSINESS_CORE_ENABLED=false → ("", None)"""
        with patch.dict(os.environ, {"BUSINESS_CORE_ENABLED": "false"}):
            note, confirm = route_inbox("Узаконение Алматы", ACTION_RESULT)
        self.assertEqual(note, "")
        self.assertIsNone(confirm)

    def test_someday_not_routed(self):
        """Someday → ("", None) без обращения к роутеру"""
        _patch_cache()
        note, confirm = route_inbox("когда-нибудь поехать на море", SOMEDAY_RESULT)
        self.assertEqual(note, "")
        self.assertIsNone(confirm)

    def test_exception_returns_empty_tuple_not_raises(self):
        """RuntimeError внутри роутера → ("", None), GTD не падает"""
        _patch_cache()
        with patch(
            "business_core.business_router.route_business_context",
            side_effect=RuntimeError("simulated crash"),
        ):
            result = route_inbox("Узаконение", ACTION_RESULT)
        self.assertEqual(result, ("", None))

    def test_import_error_returns_empty_tuple(self):
        """ImportError модуля → ("", None)"""
        invalidate_cache()
        _bc_note, _bc_confirm = "", None
        try:
            raise ImportError("module not found (test)")
        except Exception:
            pass
        self.assertEqual(_bc_note, "")
        self.assertIsNone(_bc_confirm)


# ─────────────────────────────────────────────────────────────
# Тесты кеша
# ─────────────────────────────────────────────────────────────

class TestCache(unittest.TestCase):

    def test_cache_not_stale_when_fresh(self):
        import time
        _patch_cache()
        _cache["loaded_at"] = time.time()
        from business_core.inbox_bridge import _is_stale
        self.assertFalse(_is_stale())

    def test_cache_stale_when_old(self):
        _patch_cache()
        _cache["loaded_at"] = 0.0
        from business_core.inbox_bridge import _is_stale
        self.assertTrue(_is_stale())

    def test_invalidate_cache(self):
        _patch_cache()
        invalidate_cache()
        from business_core.inbox_bridge import _is_stale
        self.assertTrue(_is_stale())


# ─────────────────────────────────────────────────────────────
# Тесты _find_active_roadmap
# ─────────────────────────────────────────────────────────────

class TestFindActiveRoadmap(unittest.TestCase):

    def test_finds_by_last_name(self):
        from business_core.inbox_bridge import _find_active_roadmap
        rm = _find_active_roadmap("Манько Андрей", "BIZ-001", FAKE_ROADMAPS)
        self.assertIsNotNone(rm)
        self.assertEqual(rm["roadmap_id"], "RM-001")

    def test_returns_none_for_unknown_client(self):
        from business_core.inbox_bridge import _find_active_roadmap
        rm = _find_active_roadmap("Петров Иван", "BIZ-001", FAKE_ROADMAPS)
        self.assertIsNone(rm)

    def test_returns_none_for_empty_name(self):
        from business_core.inbox_bridge import _find_active_roadmap
        rm = _find_active_roadmap("", "BIZ-001", FAKE_ROADMAPS)
        self.assertIsNone(rm)


# ─────────────────────────────────────────────────────────────
# Тест _build_note
# ─────────────────────────────────────────────────────────────

class TestBuildNote(unittest.TestCase):

    def test_build_note_with_full_routing(self):
        from business_core.inbox_bridge import _build_note
        routing = _make_routing(
            confidence=0.95, business_name="Узаконение",
            city="Алматы", client_name="Манько Андрей", client_id="P-001",
        )
        active_rm = {"roadmap_id": "RM-001"}
        note = _build_note(routing, active_rm)
        self.assertIn("Узаконение", note)
        self.assertIn("Алматы", note)
        self.assertIn("Манько Андрей", note)
        self.assertIn("RM-001", note)
        self.assertTrue(note.startswith("\n\n─────\n"))

    def test_build_note_empty_when_no_fields(self):
        from business_core.inbox_bridge import _build_note
        routing = _make_routing(confidence=0.95, business_name="", city="",
                                client_name="", client_id="")
        note = _build_note(routing, None)
        self.assertEqual(note, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
