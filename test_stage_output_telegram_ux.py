"""
Tests for Phase A — Stage Output Foundation Telegram caller UX:
/newoutput, /linkoutput, /syncoutputs, /outputs, /output, /updateoutput,
/submitoutput, /acceptoutput, /rejectoutput, /waiveoutput
(business_core/telegram_handlers.py).

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


class TestNewOutputCmd(_BaseCase):
    def test_creates_and_forwards_all_params(self):
        self._setup()
        from business_core.telegram_handlers import newoutput_cmd
        update, context = self._update(
            'biz_id=BIZ-001 service_id=SVC-001 template_id=RMT-001 template_stage_id=TSTG-029 '
            'title="Подписанный договор" description="Договор подписан" output_type=document '
            'verification_method="Проверить подписи" related_document_template_id=DOC-001 '
            'related_checklist_id=CHK-001 required=true blocking=true status=active notes="прим"'
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.create_output_template",
                       return_value={"ok": True, "output_template_id": "SOUT-001", "code": "OUTPUT_TEMPLATE_CREATED", "error": None}) as mock_create:
                await newoutput_cmd(update, context)
            _, kwargs = mock_create.call_args
            self.assertEqual(kwargs["biz_id"], "BIZ-001")
            self.assertEqual(kwargs["title"], "Подписанный договор")
            self.assertEqual(kwargs["output_type"], "document")
            self.assertEqual(kwargs["template_stage_id"], "TSTG-029")
            self.assertEqual(kwargs["verification_method"], "Проверить подписи")
            self.assertEqual(kwargs["related_document_template_id"], "DOC-001")
            self.assertEqual(kwargs["related_checklist_id"], "CHK-001")
            self.assertEqual(kwargs["default_required"], "true")
            self.assertEqual(kwargs["default_blocking"], "true")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SOUT-001", msg)
        asyncio.run(run())

    def test_requires_biz_id_title_output_type(self):
        self._setup()
        from business_core.telegram_handlers import newoutput_cmd
        update, context = self._update('title=X output_type=document')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await newoutput_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


class TestLinkOutputCmd(_BaseCase):
    def test_no_flags_resolves_defaults_per_output(self):
        """п.7: без required=/blocking= — defaults разрешаются отдельно
        для каждого output (разные Default Required/Blocking шаблонов)."""
        self._setup()
        from business_core.telegram_handlers import linkoutput_cmd
        update, context = self._update('template_stage_id=TSTG-029 output_ids=SOUT-001,SOUT-002')

        templates = {
            "SOUT-001": {"Default Required": "true", "Default Blocking": "true"},
            "SOUT-002": {"Default Required": "false", "Default Blocking": "false"},
        }

        def _created(candidate):
            return MagicMock(ok=True, created=candidate, errors=())

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.find_output_template_by_id",
                       side_effect=lambda oid: templates[oid]), \
                 patch("business_core.stage_entity_relations.create_required_output_relation_for_template_stage") as mock_link:
                mock_link.side_effect = lambda tstg, ids, req, blk: MagicMock(
                    ok=True, errors=(), created=tuple({"Entity ID": i} for i in ids),
                )
                await linkoutput_cmd(update, context)

            calls = {tuple(sorted(c.args[1])): c.args[2:] for c in mock_link.call_args_list}
            self.assertEqual(calls[("SOUT-001",)], ("true", "true"))
            self.assertEqual(calls[("SOUT-002",)], ("false", "false"))
        asyncio.run(run())

    def test_explicit_flags_apply_to_all_output_ids(self):
        """п.8: явные required=/blocking= применяются одинаково ко всем
        перечисленным outputs."""
        self._setup()
        from business_core.telegram_handlers import linkoutput_cmd
        update, context = self._update(
            'template_stage_id=TSTG-029 output_ids=SOUT-001,SOUT-002 required=false blocking=false'
        )
        templates = {
            "SOUT-001": {"Default Required": "true", "Default Blocking": "true"},
            "SOUT-002": {"Default Required": "true", "Default Blocking": "true"},
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.find_output_template_by_id",
                       side_effect=lambda oid: templates[oid]), \
                 patch("business_core.stage_entity_relations.create_required_output_relation_for_template_stage") as mock_link:
                mock_link.side_effect = lambda tstg, ids, req, blk: MagicMock(
                    ok=True, errors=(), created=tuple({"Entity ID": i} for i in ids),
                )
                await linkoutput_cmd(update, context)

            # Both outputs must resolve to the SAME (required, blocking) pair
            # and therefore land in exactly one call.
            self.assertEqual(mock_link.call_count, 1)
            args = mock_link.call_args[0]
            self.assertEqual(sorted(args[1]), ["SOUT-001", "SOUT-002"])
            self.assertEqual(args[2], "false")
            self.assertEqual(args[3], "false")
        asyncio.run(run())

    def test_missing_template_stage_id(self):
        self._setup()
        from business_core.telegram_handlers import linkoutput_cmd
        update, context = self._update('output_ids=SOUT-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await linkoutput_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


class TestOutputsCmd(_BaseCase):
    def test_shows_multiple_instances(self):
        self._setup()
        from business_core.telegram_handlers import outputs_cmd
        update, context = self._update('stage_id=STAGE-013')
        instances = [
            {"Output Instance ID": "SOUTI-001", "Title Snapshot": "Первый", "Output Type Snapshot": "document",
             "Required": "true", "Blocking": "true", "Status": "pending", "Evidence Value": ""},
            {"Output Instance ID": "SOUTI-002", "Title Snapshot": "Второй", "Output Type Snapshot": "approval",
             "Required": "false", "Blocking": "false", "Status": "accepted", "Evidence Value": "https://x"},
        ]

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=instances):
                await outputs_cmd(update, context)
            combined = "".join(self._all_texts(update))
            self.assertIn("SOUTI-001", combined)
            self.assertIn("SOUTI-002", combined)
            self.assertIn("Первый", combined)
            self.assertIn("Второй", combined)
        asyncio.run(run())

    def test_no_instances_clear_message(self):
        self._setup()
        from business_core.telegram_handlers import outputs_cmd
        update, context = self._update('stage_id=STAGE-013')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.list_output_instances_for_stage", return_value=[]):
                await outputs_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("STAGE-013", msg)
            self.assertIn("нет Output Instances", msg)
        asyncio.run(run())


class TestOutputCmd(_BaseCase):
    def test_shows_full_content(self):
        self._setup()
        from business_core.telegram_handlers import output_cmd
        update, context = self._update('output_instance_id=SOUTI-001')
        instance = {
            "Output Instance ID": "SOUTI-001", "Output Template ID": "SOUT-001",
            "Title Snapshot": "Подписанный договор", "Description Snapshot": "Полное описание",
            "Output Type Snapshot": "document", "Verification Method Snapshot": "Проверить подписи",
            "Related Document Template ID": "DOC-001", "Related Checklist ID": "",
            "Required": "true", "Blocking": "true", "Roadmap ID": "RM-003", "Stage ID": "STAGE-013",
            "Status": "submitted", "Evidence Type": "drive_url", "Evidence Value": "https://x",
            "Submitted By": "555", "Submitted At": "2026-01-01 00:00:00 UTC",
            "Accepted By": "", "Accepted At": "", "Rejected By": "", "Rejected At": "", "Rejection Reason": "",
            "Waived By": "", "Waived At": "", "Waiver Reason": "", "Notes": "",
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.find_output_instance_by_id", return_value=instance):
                await output_cmd(update, context)
            combined = "".join(self._all_texts(update))
            self.assertIn("SOUTI-001", combined)
            self.assertIn("Подписанный договор", combined)
            self.assertIn("Полное описание", combined)
            self.assertIn("drive_url", combined)
            self.assertIn("https://x", combined)
            self.assertIn("555", combined)
        asyncio.run(run())

    def test_not_found(self):
        self._setup()
        from business_core.telegram_handlers import output_cmd
        update, context = self._update('output_instance_id=SOUTI-999')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.find_output_instance_by_id", return_value=None):
                await output_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_markdown_characters_do_not_corrupt_output(self):
        """п.60: символы Markdown в snapshot-полях не ломают вывод —
        всегда parse_mode=None."""
        self._setup()
        from business_core.telegram_handlers import output_cmd
        update, context = self._update('output_instance_id=SOUTI-001')
        instance = {
            "Output Instance ID": "SOUTI-001", "Output Template ID": "SOUT-001",
            "Title Snapshot": "Договор_с_клиентом *важно*", "Description Snapshot": "",
            "Output Type Snapshot": "document", "Verification Method Snapshot": "",
            "Related Document Template ID": "", "Related Checklist ID": "",
            "Required": "true", "Blocking": "true", "Roadmap ID": "", "Stage ID": "STAGE-013",
            "Status": "pending", "Evidence Type": "", "Evidence Value": "",
            "Submitted By": "", "Submitted At": "", "Accepted By": "", "Accepted At": "",
            "Rejected By": "", "Rejected At": "", "Rejection Reason": "",
            "Waived By": "", "Waived At": "", "Waiver Reason": "", "Notes": "",
        }

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.find_output_instance_by_id", return_value=instance):
                await output_cmd(update, context)
            for mode in self._all_parse_modes(update):
                self.assertIsNone(mode if mode != "unset" else None)
            combined = "".join(self._all_texts(update))
            self.assertIn("Договор_с_клиентом *важно*", combined)
        asyncio.run(run())


class TestUpdateOutputCmd(_BaseCase):
    def test_produced_from_pending(self):
        self._setup()
        from business_core.telegram_handlers import updateoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 status=produced')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.update_output_instance_status",
                       return_value={"ok": True, "code": "", "error": None}) as mock_upd:
                await updateoutput_cmd(update, context)
            mock_upd.assert_called_once_with("SOUTI-001", "produced")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
        asyncio.run(run())

    def test_produced_from_rejected(self):
        self._setup()
        from business_core.telegram_handlers import updateoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 status=produced')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.update_output_instance_status",
                       return_value={"ok": True, "code": "", "error": None}) as mock_upd:
                await updateoutput_cmd(update, context)
            mock_upd.assert_called_once_with("SOUTI-001", "produced")
        asyncio.run(run())

    def test_not_applicable_from_pending(self):
        self._setup()
        from business_core.telegram_handlers import updateoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 status=not_applicable')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.update_output_instance_status",
                       return_value={"ok": True, "code": "", "error": None}) as mock_upd:
                await updateoutput_cmd(update, context)
            mock_upd.assert_called_once_with("SOUTI-001", "not_applicable")
        asyncio.run(run())

    def test_forbids_submitted_accepted_rejected_waived(self):
        self._setup()
        from business_core.telegram_handlers import updateoutput_cmd
        for forbidden in ("submitted", "accepted", "rejected", "waived"):
            update, context = self._update(f'output_instance_id=SOUTI-001 status={forbidden}')

            async def run():
                with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                     patch("business_core.stage_output_manager.update_output_instance_status") as mock_upd:
                    await updateoutput_cmd(update, context)
                mock_upd.assert_not_called()
                msg = update.message.reply_text.call_args[0][0]
                self.assertIn("❌", msg)
            asyncio.run(run())

    def test_invalid_transition_surfaces_error(self):
        self._setup()
        from business_core.telegram_handlers import updateoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 status=produced')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.update_output_instance_status",
                       return_value={"ok": False, "code": "INVALID_STATUS_TRANSITION", "error": "not allowed"}):
                await updateoutput_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())


class TestSubmitOutputCmd(_BaseCase):
    def test_saves_evidence_and_audit(self):
        self._setup()
        from business_core.telegram_handlers import submitoutput_cmd
        update, context = self._update(
            'output_instance_id=SOUTI-001 evidence_type=drive_url evidence_value="https://drive.google.com/x"'
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.submit_output_evidence",
                       return_value={"ok": True, "code": "OUTPUT_SUBMITTED", "error": None}) as mock_submit:
                await submitoutput_cmd(update, context)
            args = mock_submit.call_args[0]
            self.assertEqual(args[0], "SOUTI-001")
            self.assertEqual(args[1], "drive_url")
            self.assertEqual(args[2], "https://drive.google.com/x")
            self.assertEqual(args[3], "555")  # Telegram User ID actor
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
        asyncio.run(run())


class TestAcceptOutputCmd(_BaseCase):
    def test_saves_acceptance_audit(self):
        self._setup()
        from business_core.telegram_handlers import acceptoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.accept_output_instance",
                       return_value={"ok": True, "code": "OUTPUT_ACCEPTED", "error": None}) as mock_accept:
                await acceptoutput_cmd(update, context)
            mock_accept.assert_called_once_with("SOUTI-001", "555")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
        asyncio.run(run())


class TestRejectOutputCmd(_BaseCase):
    def test_requires_reason(self):
        self._setup()
        from business_core.telegram_handlers import rejectoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.reject_output_instance",
                       return_value={"ok": False, "code": "REJECTION_REASON_REQUIRED", "error": "reason обязателен"}) as mock_reject:
                await rejectoutput_cmd(update, context)
            mock_reject.assert_called_once_with("SOUTI-001", "555", "")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_with_reason_succeeds(self):
        self._setup()
        from business_core.telegram_handlers import rejectoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 reason="Договор не подписан"')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.reject_output_instance",
                       return_value={"ok": True, "code": "OUTPUT_REJECTED", "error": None}) as mock_reject:
                await rejectoutput_cmd(update, context)
            mock_reject.assert_called_once_with("SOUTI-001", "555", "Договор не подписан")
        asyncio.run(run())


class TestWaiveOutputCmd(_BaseCase):
    def test_requires_reason(self):
        self._setup()
        from business_core.telegram_handlers import waiveoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.waive_output_instance",
                       return_value={"ok": False, "code": "WAIVER_REASON_REQUIRED", "error": "reason обязателен"}) as mock_waive:
                await waiveoutput_cmd(update, context)
            mock_waive.assert_called_once_with("SOUTI-001", "555", "")
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_with_reason_succeeds(self):
        self._setup()
        from business_core.telegram_handlers import waiveoutput_cmd
        update, context = self._update('output_instance_id=SOUTI-001 reason="Требование снято клиентом"')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_output_manager.waive_output_instance",
                       return_value={"ok": True, "code": "OUTPUT_WAIVED", "error": None}) as mock_waive:
                await waiveoutput_cmd(update, context)
            mock_waive.assert_called_once_with("SOUTI-001", "555", "Требование снято клиентом")
        asyncio.run(run())


class TestSyncOutputsCmd(_BaseCase):
    def test_preview_shows_to_add(self):
        self._setup()
        from business_core.telegram_handlers import syncoutputs_cmd
        update, context = self._update('stage_id=STAGE-013')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.sync_stage_output_requirements",
                       return_value={"ok": True, "code": "STAGE_OUTPUT_SYNC_PREVIEW", "error": None,
                                     "stage_id": "STAGE-013", "template_stage_id": "TSTG-029",
                                     "to_add": ("SOUT-001",), "already_present": (), "created": (),
                                     "skipped_inactive_templates": ()}) as mock_sync:
                await syncoutputs_cmd(update, context)
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs.get("confirm"), False)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SOUT-001", msg)
            self.assertIn("confirm=yes", msg)
        asyncio.run(run())

    def test_confirm_yes_creates(self):
        self._setup()
        from business_core.telegram_handlers import syncoutputs_cmd
        update, context = self._update('stage_id=STAGE-013 confirm=yes')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.sync_stage_output_requirements",
                       return_value={"ok": True, "code": "STAGE_OUTPUT_SYNCED", "error": None,
                                     "stage_id": "STAGE-013", "template_stage_id": "TSTG-029",
                                     "to_add": ("SOUT-001",), "already_present": (), "created": ("SOUT-001",),
                                     "skipped_inactive_templates": ()}) as mock_sync:
                await syncoutputs_cmd(update, context)
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs.get("confirm"), True)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
            self.assertIn("SOUT-001", msg)
        asyncio.run(run())

    def test_shows_skipped_inactive_templates(self):
        self._setup()
        from business_core.telegram_handlers import syncoutputs_cmd
        update, context = self._update('stage_id=STAGE-013')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.business_builder.sync_stage_output_requirements",
                       return_value={"ok": True, "code": "STAGE_OUTPUT_SYNC_PREVIEW", "error": None,
                                     "stage_id": "STAGE-013", "template_stage_id": "TSTG-029",
                                     "to_add": (), "already_present": (), "created": (),
                                     "skipped_inactive_templates": ("SOUT-002",)}):
                await syncoutputs_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SOUT-002", msg)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
