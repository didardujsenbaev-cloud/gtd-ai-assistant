"""
Тесты для business_core/inbox_bridge.py (Фаза 5).
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Устанавливаем необходимые env-переменные до импорта
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
    _cache["loaded_at"]  = 9_999_999_999.0   # не устаревший


# ─────────────────────────────────────────────────────────────
# Тесты
# ─────────────────────────────────────────────────────────────

class TestRouteInbox(unittest.TestCase):

    def setUp(self):
        invalidate_cache()

    # ── BC disabled ──────────────────────────────────────────

    def test_bc_disabled_returns_empty(self):
        with patch.dict(os.environ, {"BUSINESS_CORE_ENABLED": "false"}):
            result = route_inbox("Узаконение дом Алматы", ACTION_RESULT)
        self.assertEqual(result, "")

    # ── Нерелевантный GTD-тип ─────────────────────────────────

    def test_someday_not_routed(self):
        _patch_cache()
        result = route_inbox("когда-нибудь поехать на море", SOMEDAY_RESULT)
        self.assertEqual(result, "")

    # ── Action с бизнес-контекстом ───────────────────────────

    def test_action_with_business_keyword(self):
        _patch_cache()
        result = route_inbox("Узаконение дом Манько", ACTION_RESULT)
        # Должен содержать название бизнеса
        self.assertIn("Узаконение", result)

    def test_action_with_client_in_text(self):
        _patch_cache()
        result = route_inbox("Манько оплата", ACTION_RESULT)
        # Клиент найден
        self.assertIn("Манько", result)

    def test_roadmap_reference(self):
        _patch_cache()
        result = route_inbox("Манько Узаконение Алматы", ACTION_RESULT)
        # Должна быть ссылка на дорожную карту
        self.assertIn("RM-001", result)

    # ── Нет подходящего бизнеса ──────────────────────────────

    def test_no_match_returns_empty(self):
        _patch_cache()
        with patch(
            "business_core.business_router.route_business_context",
            return_value={
                "business_id": "", "business_name": "", "service_id": "",
                "service_name": "", "city": "", "client_id": "",
                "client_name": "", "process": "", "roadmap_id": "",
                "roadmap_stage_id": "", "roadmap_stage_name": "",
                "confidence": 0.0, "needs_confirmation": True,
                "routing_method": "none", "matched_keywords": [],
            }
        ):
            result = route_inbox("напомни купить хлеб", ACTION_RESULT)
        self.assertEqual(result, "")

    # ── Кеш работает ─────────────────────────────────────────

    def test_cache_not_stale_when_fresh(self):
        _patch_cache()
        import time
        _cache["loaded_at"] = time.time()  # свежий
        from business_core.inbox_bridge import _is_stale
        self.assertFalse(_is_stale())

    def test_cache_stale_when_old(self):
        _patch_cache()
        _cache["loaded_at"] = 0.0  # очень старый
        from business_core.inbox_bridge import _is_stale
        self.assertTrue(_is_stale())

    def test_invalidate_cache(self):
        _patch_cache()
        invalidate_cache()
        from business_core.inbox_bridge import _is_stale
        self.assertTrue(_is_stale())

    # ── Исключение внутри — не бросает ──────────────────────

    def test_exception_returns_empty_not_raises(self):
        _patch_cache()
        with patch(
            "business_core.business_router.route_business_context",
            side_effect=RuntimeError("simulated error")
        ):
            result = route_inbox("что угодно", ACTION_RESULT)
        self.assertEqual(result, "")

    # ── Формат вывода ────────────────────────────────────────

    def test_output_format_separator(self):
        _patch_cache()
        result = route_inbox("Узаконение дом Манько", ACTION_RESULT)
        if result:
            self.assertTrue(result.startswith("\n\n─────\n"))

    def test_city_in_output(self):
        _patch_cache()
        result = route_inbox("Узаконение дом Алматы", ACTION_RESULT)
        if result:
            self.assertIn("Алматы", result)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
