"""
Phase 1 — Checklist Relation Foundation Telegram caller UX:
/linkchecklist, /syncchecklists, /checklists (stage_id and
template_stage_id modes) (business_core/telegram_handlers.py).

No live Sheets writes, no live Telegram calls — mocks only.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))


class _BaseCase(unittest.TestCase):
    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k:
                del sys.modules[k]

    def _update(self, args_str: str = ""):
        update = MagicMock()
        context = MagicMock()
        context.args = args_str.split() if args_str else []
        update.message.reply_text = AsyncMock()
        update.effective_chat.id = 123
        update.effective_user = MagicMock(id=555)
        return update, context

    def _all_texts(self, update):
        return [c.args[0] for c in update.message.reply_text.call_args_list]

    def _all_parse_modes(self, update):
        return [c.kwargs.get("parse_mode", "unset") for c in update.message.reply_text.call_args_list]


class TestLinkChecklistCmd(_BaseCase):
    def test_defaults_required_true_blocking_true(self):
        """п.41."""
        self._setup()
        from business_core.telegram_handlers import linkchecklist_cmd
        update, context = self._update('template_stage_id=TSTG-001 checklist_ids=CHK-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_entity_relations.create_checklist_relation_for_template_stage") as mock_link:
                mock_link.return_value = MagicMock(ok=True, errors=(), created=({"Entity ID": "CHK-001"},))
                await linkchecklist_cmd(update, context)
            args, kwargs = mock_link.call_args
            self.assertEqual(kwargs.get("required"), True)
            self.assertEqual(kwargs.get("blocking"), True)
        asyncio.run(run())

    def test_explicit_flags_apply_to_all_ids(self):
        """п.42."""
        self._setup()
        from business_core.telegram_handlers import linkchecklist_cmd
        update, context = self._update(
            'template_stage_id=TSTG-001 checklist_ids=CHK-001,CHK-002 required=false blocking=false'
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_entity_relations.create_checklist_relation_for_template_stage") as mock_link:
                mock_link.return_value = MagicMock(ok=True, errors=(), created=({"Entity ID": "X"},))
                await linkchecklist_cmd(update, context)
            self.assertEqual(mock_link.call_count, 2)
            for call in mock_link.call_args_list:
                self.assertEqual(call.kwargs.get("required"), False)
                self.assertEqual(call.kwargs.get("blocking"), False)
        asyncio.run(run())

    def test_missing_template_stage_id(self):
        self._setup()
        from business_core.telegram_handlers import linkchecklist_cmd
        update, context = self._update('checklist_ids=CHK-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await linkchecklist_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_missing_checklist_ids(self):
        self._setup()
        from business_core.telegram_handlers import linkchecklist_cmd
        update, context = self._update('template_stage_id=TSTG-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await linkchecklist_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


class TestSyncChecklistsCmd(_BaseCase):
    def test_preview_only_no_write(self):
        """п.43."""
        self._setup()
        from business_core.telegram_handlers import syncchecklists_cmd
        update, context = self._update('stage_id=STAGE-013')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_checklists_for_stage",
                       return_value={"ok": True, "code": "CHECKLIST_PROVISION_PREVIEW", "error": None,
                                     "stage_id": "STAGE-013", "template_stage_id": "TSTG-001",
                                     "to_create": ("CHK-001",), "created": (), "already_existing": (),
                                     "skipped_inactive": (), "errors": (), "partial_success": False}) as mock_sync:
                await syncchecklists_cmd(update, context)
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs.get("confirm"), False)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("CHK-001", msg)
            self.assertIn("confirm=yes", msg)
        asyncio.run(run())

    def test_confirm_yes_creates(self):
        """п.44."""
        self._setup()
        from business_core.telegram_handlers import syncchecklists_cmd
        update, context = self._update('stage_id=STAGE-013 confirm=yes')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.provision_checklists_for_stage",
                       return_value={"ok": True, "code": "CHECKLIST_PROVISIONED", "error": None,
                                     "stage_id": "STAGE-013", "template_stage_id": "TSTG-001",
                                     "to_create": ("CHK-001",), "created": ("CHK-001",), "already_existing": (),
                                     "skipped_inactive": (), "errors": (), "partial_success": False}) as mock_sync:
                await syncchecklists_cmd(update, context)
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs.get("confirm"), True)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
            self.assertIn("CHK-001", msg)
        asyncio.run(run())

    def test_missing_stage_id(self):
        self._setup()
        from business_core.telegram_handlers import syncchecklists_cmd
        update, context = self._update('')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await syncchecklists_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


class TestChecklistsCmdStageIdMode(_BaseCase):
    def test_shows_instances(self):
        """п.45."""
        self._setup()
        from business_core.telegram_handlers import checklists_cmd
        update, context = self._update('stage_id=STAGE-013')
        instances = [
            {"Checklist Instance ID": "CLIN-001", "Checklist Template ID": "CHK-001",
             "Checklist Title Snapshot": "Документы", "Status": "draft",
             "Completed Items": "0", "Total Items": "3", "Required Remaining": "2", "Stage ID": "STAGE-013"},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.checklist_manager.list_checklist_instances", return_value=instances):
                await checklists_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("CLIN-001", msg)
            self.assertIn("CHK-001", msg)
            self.assertIn("2", msg)
        asyncio.run(run())


class TestChecklistsCmdTemplateStageIdMode(_BaseCase):
    def test_shows_template_relations(self):
        self._setup()
        from business_core.telegram_handlers import checklists_cmd
        update, context = self._update('template_stage_id=TSTG-001')

        resolution = {
            "ok": True, "error": None, "template_stage_id": "TSTG-001", "source": "relations",
            "checklist_template_ids": ("CHK-001",), "skipped_inactive_templates": (),
            "invalid_legacy_checklist_ids": (),
        }
        relation = {"Entity ID": "CHK-001", "Required": "true", "Blocking": "true", "Status": "active"}
        template = {"Checklist ID": "CHK-001", "Title": "Документы клиента"}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.resolve_checklist_templates_for_template_stage",
                       return_value=resolution), \
                 patch("business_core.knowledge_manager.find_checklist_by_id", return_value=template), \
                 patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                       return_value=(relation,)):
                await checklists_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("CHK-001", msg)
            self.assertIn("Документы клиента", msg)
            self.assertIn("Required: true", msg)
            self.assertIn("Blocking: true", msg)
        asyncio.run(run())

    def test_no_linkage_clear_message(self):
        self._setup()
        from business_core.telegram_handlers import checklists_cmd
        update, context = self._update('template_stage_id=TSTG-999')

        resolution = {
            "ok": True, "error": None, "template_stage_id": "TSTG-999", "source": "",
            "checklist_template_ids": (), "skipped_inactive_templates": (),
            "invalid_legacy_checklist_ids": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.resolve_checklist_templates_for_template_stage",
                       return_value=resolution):
                await checklists_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("TSTG-999", msg)
            self.assertIn("нет привязанных", msg)
        asyncio.run(run())


class TestMarkdownSafety(_BaseCase):
    def test_checklists_stage_id_mode_parse_mode_none(self):
        """п.46."""
        self._setup()
        from business_core.telegram_handlers import checklists_cmd
        update, context = self._update('stage_id=STAGE-013')
        instances = [
            {"Checklist Instance ID": "CLIN-001", "Checklist Template ID": "CHK-001",
             "Checklist Title Snapshot": "Документы_клиента *важно*", "Status": "draft",
             "Completed Items": "0", "Total Items": "3", "Required Remaining": "2", "Stage ID": "STAGE-013"},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.checklist_manager.list_checklist_instances", return_value=instances):
                await checklists_cmd(update, context)
            for mode in self._all_parse_modes(update):
                self.assertIsNone(mode if mode != "unset" else None)
        asyncio.run(run())

    def test_checklists_template_stage_id_mode_parse_mode_none(self):
        self._setup()
        from business_core.telegram_handlers import checklists_cmd
        update, context = self._update('template_stage_id=TSTG-001')
        resolution = {
            "ok": True, "error": None, "template_stage_id": "TSTG-001", "source": "relations",
            "checklist_template_ids": ("CHK-001",), "skipped_inactive_templates": (),
            "invalid_legacy_checklist_ids": (),
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.resolve_checklist_templates_for_template_stage",
                       return_value=resolution), \
                 patch("business_core.knowledge_manager.find_checklist_by_id",
                       return_value={"Checklist ID": "CHK-001", "Title": "Название_*важно*"}), \
                 patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                       return_value=({"Entity ID": "CHK-001", "Required": "true", "Blocking": "true", "Status": "active"},)):
                await checklists_cmd(update, context)
            for mode in self._all_parse_modes(update):
                self.assertIsNone(mode if mode != "unset" else None)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
