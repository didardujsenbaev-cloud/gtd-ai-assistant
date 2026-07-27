"""
/syncstageknowledge — retroactive document_template knowledge sync
from a Template Stage into an already-created Roadmap Stage.

Covers:
- business_core.roadmap_manager.resolve_template_stage_for_stage()
  (read-only Stage -> Roadmap -> Template ID -> Order join)
- business_core.business_builder.sync_stage_document_requirements()
  (orchestration: resolve, scope-check, preview/apply via the existing
  stage_entity_relations.copy_template_relations_to_stage())
- business_core.telegram_handlers.syncstageknowledge_cmd (preview/
  confirm async command)

Strictly against mocked lower-level functions — no live network calls,
no Sheets writes in this test file.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

WORKSPACE = Path(__file__).parent
sys.path.insert(0, str(WORKSPACE))

import business_core.roadmap_manager as rm
import business_core.business_builder as bb
import business_core.telegram_handlers as th


def _fresh_rm():
    """Re-import business_core.roadmap_manager fresh from sys.modules.

    A bare module-level `rm` reference can go stale if an earlier test
    file (elsewhere in the same pytest run) deletes business_core.* from
    sys.modules and re-imports it — patch("business_core.roadmap_manager.X")
    would then patch the NEW module object while a stale `rm` reference
    still calls into the OLD one, silently bypassing the mock and
    hitting live Google Sheets. Matches the _fresh_rm()/_fresh_sheets()
    convention already used elsewhere in this codebase's test suite."""
    import importlib
    return importlib.import_module("business_core.roadmap_manager")


def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _cmd(cmdline: str):
    update = _upd(cmdline)
    context = MagicMock()
    context.user_data = {}
    context.args = cmdline.split()[1:]
    return update, context


FAKE_STAGE = {
    "row_num": 20, "stage_id": "STAGE-014", "roadmap_id": "RM-003", "order": "6",
    "name": "Согласие соседей / дольщиков, если нужно", "status": "pending",
}
FAKE_ROADMAP = {
    "row_num": 5, "roadmap_id": "RM-003", "template_id": "RMT-IZH-ALM-STANDARD-002",
    "notes": "", "service_id": "SVC-IZH-001",
}
FAKE_TEMPLATE_STAGES = [
    {"stage_id": "TSTG-025", "template_id": "RMT-IZH-ALM-STANDARD-002", "order": "1"},
    {"stage_id": "TSTG-030", "template_id": "RMT-IZH-ALM-STANDARD-002", "order": "6"},
    {"stage_id": "TSTG-031", "template_id": "RMT-IZH-ALM-STANDARD-002", "order": "7"},
]


# ────────────────────────────────────────────────────────────
# roadmap_manager.resolve_template_stage_for_stage()
# ────────────────────────────────────────────────────────────

class TestResolveTemplateStageForStage(unittest.TestCase):
    def test_missing_stage_id(self):
        result = _fresh_rm().resolve_template_stage_for_stage("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_stage_not_found(self):
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=None):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-999")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_roadmap_not_found(self):
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=FAKE_STAGE), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=None):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-014")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_NOT_FOUND")

    def test_roadmap_has_no_template(self):
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=FAKE_STAGE), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id", return_value=""):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-014")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ROADMAP_HAS_NO_TEMPLATE")

    def test_template_stage_not_found_wrong_order(self):
        stage_order_99 = {**FAKE_STAGE, "order": "99"}
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage_order_99), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value="RMT-IZH-ALM-STANDARD-002"), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=FAKE_TEMPLATE_STAGES):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-014")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TEMPLATE_STAGE_NOT_FOUND")

    def test_malformed_order_is_template_stage_not_found(self):
        stage_bad_order = {**FAKE_STAGE, "order": "not-a-number"}
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=stage_bad_order), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value="RMT-IZH-ALM-STANDARD-002"):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-014")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TEMPLATE_STAGE_NOT_FOUND")

    def test_success_resolves_template_stage_by_order(self):
        with patch("business_core.roadmap_manager.find_stage_by_id", return_value=FAKE_STAGE), \
             patch("business_core.roadmap_manager.find_roadmap_by_id", return_value=FAKE_ROADMAP), \
             patch("business_core.roadmap_manager._resolve_template_id",
                   return_value="RMT-IZH-ALM-STANDARD-002"), \
             patch("business_core.roadmap_template_manager.find_template_stages",
                   return_value=FAKE_TEMPLATE_STAGES):
            result = _fresh_rm().resolve_template_stage_for_stage("STAGE-014")
        self.assertTrue(result["ok"])
        self.assertEqual(result["template_stage_id"], "TSTG-030")
        self.assertEqual(result["template_id"], "RMT-IZH-ALM-STANDARD-002")


# ────────────────────────────────────────────────────────────
# business_builder.sync_stage_document_requirements()
# ────────────────────────────────────────────────────────────

_RESOLVED_OK = {
    "ok": True, "code": "", "error": None,
    "stage": FAKE_STAGE, "roadmap": FAKE_ROADMAP,
    "template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-030",
}

_TEMPLATE_RELATIONS_DOC_ONLY = (
    {"Relation ID": "REL-100", "Template Stage ID": "TSTG-030", "Stage ID": "",
     "Entity Type": "document_template", "Entity ID": "DOC-012", "Status": "active"},
)


def _copy_result(created=(), errors=(), ok=True):
    result = MagicMock()
    result.created = created
    result.errors = errors
    result.ok = ok
    return result


class TestSyncStageDocumentRequirements(unittest.TestCase):
    def test_resolution_failure_propagates(self):
        failed = {"ok": False, "code": "STAGE_NOT_FOUND", "error": "Stage STAGE-999 не найден"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed):
            result = bb.sync_stage_document_requirements("STAGE-999", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_NOT_FOUND")

    def test_template_stage_not_found_propagates(self):
        failed = {"ok": False, "code": "TEMPLATE_STAGE_NOT_FOUND", "error": "не найден"}
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=failed):
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "TEMPLATE_STAGE_NOT_FOUND")

    def test_no_document_template_relations_on_template_stage(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_DOCUMENT_TEMPLATE_RELATIONS")

    def test_unsupported_relation_type_on_template_stage_blocks(self):
        mixed_relations = _TEMPLATE_RELATIONS_DOC_ONLY + (
            {"Relation ID": "REL-101", "Template Stage ID": "TSTG-030", "Stage ID": "",
             "Entity Type": "role", "Entity ID": "ROLE-001", "Status": "active"},
        )
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=mixed_relations), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE")
        mock_copy.assert_not_called()

    def test_dry_run_preview_shows_to_add_and_does_not_write(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        mock_copy.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_KNOWLEDGE_SYNC_PREVIEW")
        self.assertEqual(result["to_add"], ("DOC-012",))
        self.assertEqual(result["already_present"], ())
        self.assertEqual(result["template_stage_id"], "TSTG-030")

    def test_apply_calls_copy_template_relations_to_stage(self):
        created = ({"Entity Type": "document_template", "Entity ID": "DOC-012"},)
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result(created=created)) as mock_copy:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)

        mock_copy.assert_called_once_with("TSTG-030", "STAGE-014")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_KNOWLEDGE_SYNCED")
        self.assertEqual(result["created"], ("DOC-012",))

    def test_idempotent_second_run_reports_already_present_no_new_to_add(self):
        already_existing = (
            {"Stage ID": "STAGE-014", "Entity Type": "document_template", "Entity ID": "DOC-012",
             "Status": "active"},
        )
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=already_existing), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result(created=())) as mock_copy:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        mock_copy.assert_not_called()
        self.assertEqual(result["to_add"], ())
        self.assertEqual(result["already_present"], ("DOC-012",))

    def test_copy_failure_surfaces_error(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result(ok=False, errors=(("REL-100", ("bad reference",)),))):
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "STAGE_KNOWLEDGE_SYNC_FAILED")

    def test_scope_limited_to_requested_stage_only(self):
        """resolve_template_stage_for_stage() and copy_template_relations_to_stage()
        must be called with exactly the requested stage_id — never a
        roadmap-wide sweep of other stages."""
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK) as mock_resolve, \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result()) as mock_copy:
            bb.sync_stage_document_requirements("STAGE-014", dry_run=False)

        mock_resolve.assert_called_once_with("STAGE-014")
        mock_copy.assert_called_once_with("TSTG-030", "STAGE-014")

    def test_never_touches_operational_stage_fields(self):
        """Architectural guard: this function must never import any
        ROADMAP_STAGES writer (update_stage_fields/update_stage_status_
        in_sheet) — it only ever calls stage_entity_relations functions,
        which read/write STAGE_ENTITY_RELATIONS exclusively."""
        import ast
        import inspect

        source = inspect.getsource(bb.sync_stage_document_requirements)
        tree = ast.parse(source)
        called_names = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("update_stage_fields", called_names)
        self.assertNotIn("update_stage_status_in_sheet", called_names)


# ────────────────────────────────────────────────────────────
# /syncstageknowledge — async command behavior
# ────────────────────────────────────────────────────────────

class TestSyncStageKnowledgeCmd(unittest.TestCase):
    def test_missing_stage_id(self):
        update, context = _cmd("/syncstageknowledge")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await th.syncstageknowledge_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("stage_id", msg)

    def test_preview_call_uses_dry_run_true_and_shows_to_add(self):
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements",
                   return_value={"ok": True, "code": "STAGE_KNOWLEDGE_SYNC_PREVIEW", "error": None,
                                 "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
                                 "to_add": ("DOC-012",), "already_present": (), "created": ()}) as mock_fn:
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        _, kwargs = mock_fn.call_args
        self.assertEqual(kwargs.get("dry_run"), True)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-012", msg)
        self.assertIn("confirm=yes", msg)
        self.assertIn("STAGE-014", msg)
        self.assertIn("TSTG-030", msg)

    def test_confirm_yes_calls_with_dry_run_false(self):
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014 confirm=yes")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements",
                   return_value={"ok": True, "code": "STAGE_KNOWLEDGE_SYNCED", "error": None,
                                 "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
                                 "to_add": ("DOC-012",), "already_present": (), "created": ("DOC-012",)}) as mock_fn:
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        args, kwargs = mock_fn.call_args
        self.assertEqual(args[0], "STAGE-014")
        self.assertEqual(kwargs.get("dry_run"), False)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("DOC-012", msg)

    def test_error_code_rendered_explicitly(self):
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements",
                   return_value={"ok": False, "code": "NO_DOCUMENT_TEMPLATE_RELATIONS",
                                 "error": "У Template Stage TSTG-030 нет активных document_template relations",
                                 "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
                                 "to_add": (), "already_present": (), "created": ()}):
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("TSTG-030", msg)

    def test_second_run_preview_shows_already_present_not_to_add(self):
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014")

        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements",
                   return_value={"ok": True, "code": "STAGE_KNOWLEDGE_SYNC_PREVIEW", "error": None,
                                 "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
                                 "to_add": (), "already_present": ("DOC-012",), "created": ()}):
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-012", msg)
        self.assertIn("ничего", msg.lower())


if __name__ == "__main__":
    unittest.main()
