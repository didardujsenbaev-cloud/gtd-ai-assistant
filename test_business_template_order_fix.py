"""
Phase 12A: template Order data-fix regression guard.

Phase 11E/11F documented a pre-existing template-data defect (not a code
bug): ROADMAP_TEMPLATE_STAGES for RMT-IZH-ALM-STANDARD-001 had
Order = 1, 8, 9, 10, 11, 12, 13, 14 instead of 1..8, leaving a gap that
propagated into every roadmap created from this template. Phase 12A
fixed the underlying Sheets data (not code) to Order = 1..8.

This is a live-data regression check, not a unit test of business
logic — it reads the real ROADMAP_TEMPLATE_STAGES sheet (read-only) to
confirm the fix landed and nothing else about the template changed.
Skips cleanly if Business Core is unreachable (e.g. CI without
credentials) rather than failing the whole suite.
"""

from __future__ import annotations

import os
import unittest

TEMPLATE_ID = "RMT-IZH-ALM-STANDARD-001"

# Phase 11F.2 safety gate: this file does a real (read-only) live Sheets
# call, so — like test_business_core_sheets.py — it must never touch the
# network during plain `unittest discover`. No writes are ever performed
# here regardless of flags.
ALLOW_LIVE_TESTS = os.environ.get("BUSINESS_CORE_ALLOW_LIVE_TESTS") == "1"


def _try_read_live_stages():
    try:
        from business_core.sheets import read_business_sheet
        return read_business_sheet("roadmap_template_stages")
    except Exception:
        return None


class TestTemplateOrderFixedLive(unittest.TestCase):
    """Read-only live check — skipped unless BUSINESS_CORE_ALLOW_LIVE_TESTS=1,
    and skips cleanly if Sheets is unreachable even then."""

    @classmethod
    def setUpClass(cls):
        if not ALLOW_LIVE_TESTS:
            raise unittest.SkipTest(
                "live Sheets check skipped — set BUSINESS_CORE_ALLOW_LIVE_TESTS=1 to run"
            )
        cls.stages = _try_read_live_stages()
        if cls.stages is None:
            raise unittest.SkipTest("Business Core Sheets unreachable — skipping live check")
        cls.tmpl_stages = [s for s in cls.stages if s.get("Template ID") == TEMPLATE_ID]
        if not cls.tmpl_stages:
            raise unittest.SkipTest(f"{TEMPLATE_ID} not found in live sheet — skipping")

    def test_exactly_eight_stages(self):
        self.assertEqual(len(self.tmpl_stages), 8)

    def test_order_is_sequential_one_to_eight(self):
        orders = sorted(int(s["Order"]) for s in self.tmpl_stages)
        self.assertEqual(orders, list(range(1, 9)))

    def test_stage_ids_unchanged(self):
        ids = {s["Stage ID"] for s in self.tmpl_stages}
        self.assertEqual(ids, {f"TSTG-{n:03d}" for n in range(17, 25)})

    def test_stage_names_unchanged(self):
        by_id = {s["Stage ID"]: s["Stage Name"] for s in self.tmpl_stages}
        self.assertEqual(by_id["TSTG-017"], "Первичный анализ объекта и намерения клиента")
        self.assertEqual(by_id["TSTG-024"], "Согласование акта ввода в архитектуре")


if __name__ == "__main__":
    unittest.main()
