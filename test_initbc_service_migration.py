"""
Phase 29CD, Part 4: /initbc no longer writes SERVICE_CATALOG directly.

Before this phase, telegram_handlers.init_bc() wrote SERVICE_CATALOG
via a raw append_business_row() call with a positional 28-column row,
its own generate_next_id("service_catalog", "SVC") call, and its own
slug algorithm (name.lower().replace(" ", "-")) — all bypassing
business_core.service_manager entirely, with zero test coverage.

This file is the first-ever test coverage for /initbc's Service-writing
behavior: it must now call ONLY service_manager.create_service_record(),
never append_business_row/generate_next_id against "service_catalog",
and must be safe to run repeatedly (idempotent via create_service_record's
own duplicate-key convergence).
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _fresh_handlers():
    for k in list(sys.modules):
        if "business_core" in k:
            del sys.modules[k]
    from business_core.telegram_handlers import init_bc
    return init_bc


def _make_update():
    update = MagicMock()
    update.message.text = "/initbc"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []
    return update, context


class TestInitBcUsesOwnerApi(unittest.TestCase):
    """15/16/17: /initbc calls only service_manager.create_service_record,
    never writes SERVICE_CATALOG directly, never generates its own ID."""

    def test_calls_create_service_record_for_each_default_service(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-900",
                                 "service_created": True, "service_reused": False,
                                 "warnings": [], "error": None}) as mock_create_svc:
            asyncio.run(init_bc(update, context))

        self.assertGreater(mock_create_svc.call_count, 0)

    def test_never_appends_to_service_catalog_directly(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.sheets.append_business_row") as mock_append, \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-900",
                                 "service_created": True, "service_reused": False,
                                 "warnings": [], "error": None}):
            asyncio.run(init_bc(update, context))

        for call in mock_append.call_args_list:
            self.assertNotEqual(call.args[0], "service_catalog",
                                 "init_bc must never call append_business_row('service_catalog', ...) directly")

    def test_never_generates_service_id_directly(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.sheets.generate_next_id") as mock_gen_id, \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-900",
                                 "service_created": True, "service_reused": False,
                                 "warnings": [], "error": None}):
            asyncio.run(init_bc(update, context))

        for call in mock_gen_id.call_args_list:
            self.assertNotEqual(call.args[0], "service_catalog",
                                 "init_bc must never call generate_next_id('service_catalog', ...) directly")

    def test_no_positional_slug_algorithm_in_source(self):
        """The dead giveaway of the old bypass — name.lower().replace(' ', '-')
        — must be gone from init_bc's source."""
        import inspect
        init_bc = _fresh_handlers()
        src = inspect.getsource(init_bc)
        self.assertNotIn('.replace(" ", "-")', src)


class TestInitBcHandlesCreatedAndReused(unittest.TestCase):
    """18: repeated /initbc reuses existing services instead of erroring
    or creating duplicates — verified via the service_created/
    service_reused flags create_service_record returns."""

    def test_first_run_reports_created(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-900",
                                 "service_created": True, "service_reused": False,
                                 "warnings": [], "error": None}):
            asyncio.run(init_bc(update, context))

        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Услуг добавлено", reply)

    def test_second_run_reuses_without_error(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": True, "service_id": "SVC-900",
                                 "service_created": False, "service_reused": True,
                                 "warnings": [], "error": None}) as mock_create_svc:
            asyncio.run(init_bc(update, context))

        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("❌", reply)
        self.assertGreater(mock_create_svc.call_count, 0)


class TestInitBcNoLiveNetworkOnFailurePaths(unittest.TestCase):
    """33: no live Sheets/network calls even when create_service_record
    reports an error for one service — /initbc must not crash or hang."""

    def test_service_error_does_not_crash_init_bc(self):
        update, context = _make_update()
        init_bc = _fresh_handlers()

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_registry.list_default_businesses", return_value=[]), \
             patch("business_core.sheets.read_business_sheet", return_value=[]), \
             patch("business_core.service_manager.create_service_record",
                   return_value={"ok": False, "service_id": "",
                                 "service_created": False, "service_reused": False,
                                 "warnings": [], "error": "integrity: multiple matches"}):
            asyncio.run(init_bc(update, context))

        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Ошибки услуг", reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
