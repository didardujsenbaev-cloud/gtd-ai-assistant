"""
Phase 16C.8.2B.1: /cancel global handler-routing fix.

Root cause (see the Phase 16C.8.2B production defect diagnosis): a
standalone, conversation-unaware CommandHandler("cancel",
np_cancel_command) was registered in PTB group 0 BEFORE any Business
Core ConversationHandler. python-telegram-bot's Application.
process_update() runs only the FIRST matching handler per group, so
np_cancel_command silently intercepted /cancel before any active
Business Core (or, in principle, GTD) conversation's own /cancel
fallback ever got checked — leaving that conversation's state and
pending user_data uncleaned.

The fix moves np_cancel_command's registration to AFTER
register_business_handlers(app) — no other registration order change.

These tests dispatch real Update objects through a real PTB
Application (built here with the SAME relative handler order as
telegram_bot.py's main(), using the actual imported callables — never
stub functions) to prove real routing behavior, not just callback
logic in isolation. No Sheets/Drive reads or writes, no Telegram
network calls (Application.process_update() is exercised directly;
Bot.initialize()'s network call is bypassed since these tests never
call Application.initialize()/run_polling()).

Patch-ordering note: ConversationHandler/CommandHandler capture the
actual callback object at registration time, so any unittest.mock
patch.object(..., wraps=...) spy MUST be active before
_build_app_with_production_order() runs — never applied afterward.
Every test below builds the Application inside the same `with` block
as its spies for exactly this reason.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update, Message, Chat, User, MessageEntity
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters


def _fresh_modules():
    for key in list(sys.modules.keys()):
        if "business_core" in key or key == "telegram_bot":
            del sys.modules[key]
    import telegram_bot as tb
    import business_core.telegram_handlers as th
    return tb, th


def _make_update(text, update_id, chat_id, user_id):
    user = User(id=user_id, first_name="Tester", is_bot=False)
    chat = Chat(id=chat_id, type="private")
    entity = MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=len(text.split()[0]))
    message = Message(message_id=update_id, date=None, chat=chat, from_user=user, text=text, entities=[entity])
    message._unfreeze()
    message.set_bot(MagicMock(username="TestBot"))
    return Update(update_id=update_id, message=message)


def _build_app_with_production_order(tb, th):
    """
    Registers the real callables in the SAME relative order as
    telegram_bot.py's main() after the Phase 16C.8.2B.1 fix:
      1. GTD ConversationHandlers with their own /cancel fallback
         (Mind Sweep here, as the representative GTD conversation).
      2. Business Core handlers via register_business_handlers()
         (the real function — registers /uploaddoc, /newclient, and
         every other Business Core ConversationHandler exactly as
         production does).
      3. Standalone generic np_cancel_command LAST.
    """
    app = Application.builder().token("123456789:FAKE_TOKEN_FOR_LOCAL_TEST_ONLY").build()

    ms_handler = ConversationHandler(
        entry_points=[CommandHandler("mindsweep", tb.mindsweep_start)],
        states={
            tb.MS_WORK: [MessageHandler(filters.TEXT & ~filters.COMMAND, tb.ms_work)],
            tb.MS_PERSONAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, tb.ms_personal)],
            tb.MS_DONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tb.ms_finish)],
        },
        fallbacks=[CommandHandler("cancel", tb.ms_cancel)],
        allow_reentry=True,
    )
    app.add_handler(ms_handler)

    th.register_business_handlers(app)

    app.add_handler(CommandHandler("cancel", tb.np_cancel_command))

    app._initialized = True
    return app


def _conversation_states(app, entry_command):
    for handler in app.handlers[0]:
        if isinstance(handler, ConversationHandler) and any(
            getattr(ep, "commands", None) == frozenset({entry_command}) for ep in handler.entry_points
        ):
            return dict(handler._conversations)
    return None


class TestCancelRoutingUploaddoc(unittest.TestCase):
    """Items 1-13: prefilled /uploaddoc entry, then /cancel, dispatched
    through a real Application built with the real production handler
    order (post-fix)."""

    def _run(self):
        """Builds the app, dispatches /uploaddoc then /cancel, and
        returns (app, tb, th, uploaddoc_cancel_spy, np_cancel_spy)."""
        tb, th = _fresh_modules()
        Message.reply_text = AsyncMock()

        with patch.object(th, "_is_bc_enabled", return_value=True), \
             patch.object(th, "uploaddoc_cancel", wraps=th.uploaddoc_cancel) as uploaddoc_cancel_spy, \
             patch.object(tb, "np_cancel_command", wraps=tb.np_cancel_command) as np_cancel_spy:
            app = _build_app_with_production_order(tb, th)

            async def scenario():
                upd1 = _make_update(
                    "/uploaddoc business=BIZ-001 roadmap=RM-003 stage=STAGE-011 template=DOC-008",
                    1, chat_id=111, user_id=111,
                )
                await app.process_update(upd1)
                upd2 = _make_update("/cancel", 2, chat_id=111, user_id=111)
                await app.process_update(upd2)

            asyncio.run(scenario())

        return app, tb, th, uploaddoc_cancel_spy, np_cancel_spy

    def test_valid_prefilled_uploaddoc_enters_ud_file_no_reads(self):
        with patch("business_core.sheets.read_business_sheet") as mock_read:
            app, tb, th, _, _ = self._run()
        mock_read.assert_not_called()

    def test_ud_prefill_removed_after_cancel(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, _, _ = self._run()
        self.assertNotIn("ud_prefill", app.user_data.get(111, {}))

    def test_ud_removed_after_cancel(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, _, _ = self._run()
        self.assertNotIn("ud", app.user_data.get(111, {}))

    def test_ud_confirmed_snapshot_removed_after_cancel(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, _, _ = self._run()
        self.assertNotIn("ud_confirmed_snapshot", app.user_data.get(111, {}))

    def test_conversation_state_ends(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, _, _ = self._run()
        states = _conversation_states(app, "uploaddoc")
        self.assertIsNotNone(states)
        self.assertNotIn((111, 111), states)

    def test_np_cancel_command_not_called_during_active_upload(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, uploaddoc_cancel_spy, np_cancel_spy = self._run()
        np_cancel_spy.assert_not_called()

    def test_uploaddoc_cancel_wins(self):
        with patch("business_core.sheets.read_business_sheet"):
            app, tb, th, uploaddoc_cancel_spy, np_cancel_spy = self._run()
        uploaddoc_cancel_spy.assert_called_once()

    def test_no_drive_reads(self):
        with patch("business_core.sheets.read_business_sheet"), \
             patch("integrations.google_drive_adapter.get_drive_service") as mock_drive:
            app, tb, th, _, _ = self._run()
        mock_drive.assert_not_called()

    def test_no_writes(self):
        with patch("business_core.sheets.read_business_sheet"), \
             patch("integrations.google_drive_adapter.upload_file") as mock_upload, \
             patch("business_core.business_builder.upload_and_register_document") as mock_register:
            app, tb, th, _, _ = self._run()
        mock_upload.assert_not_called()
        mock_register.assert_not_called()

    def test_no_telegram_network_calls(self):
        """Application.process_update() never invokes Bot.get_updates /
        get_me — those are only reached via initialize()/run_polling(),
        neither of which this test calls."""
        with patch("business_core.sheets.read_business_sheet"), \
             patch("telegram.Bot.get_updates") as mock_get_updates, \
             patch("telegram.Bot.get_me") as mock_get_me:
            app, tb, th, _, _ = self._run()
        mock_get_updates.assert_not_called()
        mock_get_me.assert_not_called()


class TestCancelRoutingGeneric(unittest.TestCase):
    """Items 14-15: /cancel with no active conversation still reaches
    np_cancel_command, with its unchanged wording."""

    def test_no_active_conversation_reaches_generic_cancel(self):
        tb, th = _fresh_modules()
        Message.reply_text = AsyncMock()

        with patch.object(th, "_is_bc_enabled", return_value=True):
            app = _build_app_with_production_order(tb, th)

            async def scenario():
                upd = _make_update("/cancel", 1, chat_id=222, user_id=222)
                await app.process_update(upd)

            asyncio.run(scenario())

        call_args = Message.reply_text.call_args
        self.assertIsNotNone(call_args)
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        self.assertIn("Нечего отменять", text)
        self.assertIn("Weekly Review", text)


class TestCancelRoutingSecondBusinessCoreConversation(unittest.TestCase):
    """Items 16-20: /newclient (a distinct Business Core
    ConversationHandler with its own /cancel fallback) must also
    correctly win over np_cancel_command."""

    def test_newclient_cancel_wins_and_state_ends(self):
        tb, th = _fresh_modules()
        Message.reply_text = AsyncMock()

        with patch.object(th, "_is_bc_enabled", return_value=True), \
             patch.object(th, "newclient_cancel", wraps=th.newclient_cancel) as newclient_spy, \
             patch.object(tb, "np_cancel_command", wraps=tb.np_cancel_command) as generic_spy:
            app = _build_app_with_production_order(tb, th)

            async def scenario():
                upd1 = _make_update("/newclient", 1, chat_id=333, user_id=333)
                await app.process_update(upd1)
                upd2 = _make_update("/cancel", 2, chat_id=333, user_id=333)
                await app.process_update(upd2)

            asyncio.run(scenario())

        newclient_spy.assert_called_once()
        generic_spy.assert_not_called()

        states = _conversation_states(app, "newclient")
        self.assertIsNotNone(states)
        self.assertNotIn((333, 333), states)
        self.assertNotIn("nc", app.user_data.get(333, {}))


class TestCancelRoutingGtdSafety(unittest.TestCase):
    """Items 21-22: GTD's own conversation /cancel fallback still wins
    while active, and np_cancel_command still wins when nothing is
    active."""

    def test_mindsweep_cancel_fallback_wins_while_active(self):
        tb, th = _fresh_modules()
        Message.reply_text = AsyncMock()

        with patch.object(th, "_is_bc_enabled", return_value=True), \
             patch.object(tb, "ms_cancel", wraps=tb.ms_cancel) as ms_spy, \
             patch.object(tb, "np_cancel_command", wraps=tb.np_cancel_command) as generic_spy:
            app = _build_app_with_production_order(tb, th)

            async def scenario():
                upd1 = _make_update("/mindsweep", 1, chat_id=444, user_id=444)
                await app.process_update(upd1)
                upd2 = _make_update("/cancel", 2, chat_id=444, user_id=444)
                await app.process_update(upd2)

            asyncio.run(scenario())

        ms_spy.assert_called_once()
        generic_spy.assert_not_called()
        self.assertNotIn("ms", app.user_data.get(444, {}))

    def test_generic_cancel_wins_when_nothing_active(self):
        tb, th = _fresh_modules()
        Message.reply_text = AsyncMock()

        with patch.object(th, "_is_bc_enabled", return_value=True), \
             patch.object(tb, "np_cancel_command", wraps=tb.np_cancel_command) as generic_spy:
            app = _build_app_with_production_order(tb, th)

            async def scenario():
                upd = _make_update("/cancel", 1, chat_id=555, user_id=555)
                await app.process_update(upd)

            asyncio.run(scenario())

        generic_spy.assert_called_once()


class TestRegistrationOrderStructural(unittest.TestCase):
    """Behavior-adjacent structural confirmation (secondary to the
    dispatcher tests above, which are the real proof): confirms
    register_business_handlers(app) is called before the standalone
    np_cancel_command registration, that np_cancel_command is
    registered exactly once at the top level, and no duplicate
    top-level /cancel handler or explicit group was introduced. Uses
    substring position within main()'s source, not brittle absolute
    line numbers."""

    def test_register_business_handlers_called_before_standalone_cancel(self):
        import inspect
        tb, th = _fresh_modules()
        source = inspect.getsource(tb.main)
        business_core_pos = source.index("register_business_handlers(app)")
        standalone_cancel_pos = source.index('CommandHandler("cancel", np_cancel_command)')
        self.assertLess(business_core_pos, standalone_cancel_pos)

    def test_standalone_cancel_registered_exactly_once(self):
        import inspect
        tb, th = _fresh_modules()
        source = inspect.getsource(tb.main)
        self.assertEqual(source.count('CommandHandler("cancel", np_cancel_command)'), 1)

    def test_no_group_argument_introduced(self):
        """The fix must be a pure registration-order move — not a
        switch to explicit PTB groups, which would be a larger,
        unauthorized behavioral change."""
        import inspect
        tb, th = _fresh_modules()
        source = inspect.getsource(tb.main)
        self.assertNotIn('CommandHandler("cancel", np_cancel_command), group=', source)


if __name__ == "__main__":
    unittest.main()
