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

def _resolved_ok(document_template_ids=()):
    """Build a resolve_template_stage_for_stage()-shaped result. The
    legacy `document_template_ids` on template_stage_row defaults to
    empty — most tests exercise the STAGE_ENTITY_RELATIONS source and
    don't need it populated; legacy-source tests pass it explicitly."""
    return {
        "ok": True, "code": "", "error": None,
        "stage": FAKE_STAGE, "roadmap": FAKE_ROADMAP,
        "template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-030",
        "template_stage_row": {
            "stage_id": "TSTG-030", "template_id": "RMT-IZH-ALM-STANDARD-002", "order": "6",
            "document_template_ids": list(document_template_ids),
        },
    }


_RESOLVED_OK = _resolved_ok()
_RESOLVED_OK_LEGACY_DOC_012 = _resolved_ok(["DOC-012"])

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


class TestSyncStageDocumentRequirementsDualSource(unittest.TestCase):
    """Live-audit fix: /linkknowledge and /stageknowledge both read/write
    the legacy ROADMAP_TEMPLATE_STAGES."Document Template IDs" column,
    never STAGE_ENTITY_RELATIONS — sync_stage_document_requirements()
    must accept knowledge from either source, preferring active
    STAGE_ENTITY_RELATIONS when present."""

    def test_sync_from_stage_entity_relations_source(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result(created=({"Entity Type": "document_template",
                                                        "Entity ID": "DOC-012"},))) as mock_copy, \
             patch("business_core.stage_entity_relations.create_document_template_relations_for_stage") as mock_legacy_write:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)

        mock_copy.assert_called_once_with("TSTG-030", "STAGE-014")
        mock_legacy_write.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "relations")
        self.assertEqual(result["created"], ("DOC-012",))

    def test_sync_from_legacy_document_template_ids_source(self):
        """No STAGE_ENTITY_RELATIONS at all for TSTG-030 (the exact
        live-production scenario) — falls back to the legacy column and
        creates an instance-scoped relation via
        create_document_template_relations_for_stage()."""
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK_LEGACY_DOC_012), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.validate_relation_references", return_value=[]), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy, \
             patch("business_core.stage_entity_relations.create_document_template_relations_for_stage",
                   return_value=_copy_result(created=({"Entity Type": "document_template",
                                                        "Entity ID": "DOC-012"},))) as mock_legacy_write:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)

        mock_copy.assert_not_called()
        mock_legacy_write.assert_called_once_with("STAGE-014", ["DOC-012"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_KNOWLEDGE_SYNCED")
        self.assertEqual(result["source"], "legacy")
        self.assertEqual(result["created"], ("DOC-012",))

    def test_legacy_preview_shows_source_and_to_add(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK_LEGACY_DOC_012), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.validate_relation_references", return_value=[]), \
             patch("business_core.stage_entity_relations.create_document_template_relations_for_stage") as mock_write:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        mock_write.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_KNOWLEDGE_SYNC_PREVIEW")
        self.assertEqual(result["source"], "legacy")
        self.assertEqual(result["to_add"], ("DOC-012",))

    def test_relations_take_priority_over_legacy_when_both_present(self):
        """Both sources have data — STAGE_ENTITY_RELATIONS must win, the
        legacy column must be ignored entirely."""
        resolved_both = _resolved_ok(["DOC-999-LEGACY-ONLY"])
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=resolved_both), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_DOC_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result()) as mock_copy, \
             patch("business_core.stage_entity_relations.create_document_template_relations_for_stage") as mock_legacy_write:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        mock_copy.assert_not_called()  # dry_run — nothing written either way
        mock_legacy_write.assert_not_called()
        self.assertEqual(result["source"], "relations")
        self.assertEqual(result["to_add"], ("DOC-012",))
        self.assertNotIn("DOC-999-LEGACY-ONLY", result["to_add"])

    def test_both_sources_empty_is_no_document_template_relations(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_DOCUMENT_TEMPLATE_RELATIONS")

    def test_invalid_legacy_document_template_id_blocked_before_write(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_resolved_ok(["DOC-999-NONEXISTENT"])), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_entity_relations.validate_relation_references",
                   return_value=["Entity ID 'DOC-999-NONEXISTENT' not found in document_template_registry."]), \
             patch("business_core.stage_entity_relations.create_document_template_relations_for_stage") as mock_write:
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=False)

        mock_write.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "INVALID_LEGACY_DOCUMENT_TEMPLATE_ID")
        self.assertIn("DOC-999-NONEXISTENT", result["error"])

    def test_legacy_idempotent_second_run_no_new_to_add(self):
        """Second sync from the legacy source, after the first already
        created the instance relation — must report nothing left to add
        and must not call the write primitive with a stale duplicate."""
        already_existing = (
            {"Stage ID": "STAGE-014", "Entity Type": "document_template", "Entity ID": "DOC-012",
             "Status": "active"},
        )
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK_LEGACY_DOC_012), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=already_existing), \
             patch("business_core.stage_entity_relations.validate_relation_references", return_value=[]):
            result = bb.sync_stage_document_requirements("STAGE-014", dry_run=True)

        self.assertEqual(result["to_add"], ())
        self.assertEqual(result["already_present"], ("DOC-012",))
        self.assertEqual(result["source"], "legacy")


# ────────────────────────────────────────────────────────────
# business_builder.sync_stage_sop_knowledge()
# ────────────────────────────────────────────────────────────

_TEMPLATE_RELATIONS_SOP_ONLY = (
    {"Relation ID": "REL-200", "Template Stage ID": "TSTG-030", "Stage ID": "",
     "Entity Type": "sop", "Entity ID": "SOP-001", "Status": "active"},
)


def _resolved_ok_sop(sop_ids=()):
    return {
        "ok": True, "code": "", "error": None,
        "stage": FAKE_STAGE, "roadmap": FAKE_ROADMAP,
        "template_id": "RMT-IZH-ALM-STANDARD-002", "template_stage_id": "TSTG-030",
        "template_stage_row": {
            "stage_id": "TSTG-030", "template_id": "RMT-IZH-ALM-STANDARD-002", "order": "6",
            "sop_ids": list(sop_ids),
        },
    }


_RESOLVED_OK_SOP = _resolved_ok_sop()
_RESOLVED_OK_SOP_LEGACY = _resolved_ok_sop(["SOP-001"])


class TestSyncStageSopKnowledge(unittest.TestCase):
    """п.30-33: SOP twin of TestSyncStageDocumentRequirements(DualSource) —
    same dual-source, preview/confirm/idempotency contract, applied to
    business_builder.sync_stage_sop_knowledge()."""

    def test_no_sop_knowledge_on_template_stage(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK_SOP), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()):
            result = bb.sync_stage_sop_knowledge("STAGE-014", dry_run=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "NO_SOP_KNOWLEDGE")

    def test_preview_shows_source_and_to_add_relations(self):
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK_SOP), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_SOP_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.sync_stage_sop_knowledge("STAGE-014", dry_run=True)

        mock_copy.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_SOP_SYNC_PREVIEW")
        self.assertEqual(result["source"], "relations")
        self.assertEqual(result["to_add"], ("SOP-001",))

    def test_confirm_yes_creates_relation_via_copy(self):
        created = ({"Entity Type": "sop", "Entity ID": "SOP-001"},)
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK_SOP), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_SOP_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage",
                   return_value=_copy_result(created=created)) as mock_copy:
            result = bb.sync_stage_sop_knowledge("STAGE-014", dry_run=False)

        mock_copy.assert_called_once_with("TSTG-030", "STAGE-014")
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "STAGE_SOP_SYNCED")
        self.assertEqual(result["created"], ("SOP-001",))

    def test_idempotent_second_run_no_new_to_add(self):
        already_existing = (
            {"Stage ID": "STAGE-014", "Entity Type": "sop", "Entity ID": "SOP-001", "Status": "active"},
        )
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage", return_value=_RESOLVED_OK_SOP), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage",
                   return_value=_TEMPLATE_RELATIONS_SOP_ONLY), \
             patch("business_core.stage_entity_relations.get_relations_for_stage",
                   return_value=already_existing), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy:
            result = bb.sync_stage_sop_knowledge("STAGE-014", dry_run=True)

        mock_copy.assert_not_called()
        self.assertEqual(result["to_add"], ())
        self.assertEqual(result["already_present"], ("SOP-001",))

    def test_legacy_sop_ids_on_template_stage_supported(self):
        """п.33: legacy ROADMAP_TEMPLATE_STAGES."SOP IDs" fallback when no
        STAGE_ENTITY_RELATIONS sop rows exist for the Template Stage."""
        with patch("business_core.roadmap_manager.resolve_template_stage_for_stage",
                   return_value=_RESOLVED_OK_SOP_LEGACY), \
             patch("business_core.stage_entity_relations.get_relations_for_template_stage", return_value=()), \
             patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
             patch("business_core.stage_entity_relations.validate_relation_references", return_value=[]), \
             patch("business_core.stage_entity_relations.copy_template_relations_to_stage") as mock_copy, \
             patch("business_core.stage_entity_relations.create_sop_relations_for_stage",
                   return_value=_copy_result(created=({"Entity Type": "sop", "Entity ID": "SOP-001"},))) as mock_legacy:
            result = bb.sync_stage_sop_knowledge("STAGE-014", dry_run=False)

        mock_copy.assert_not_called()
        mock_legacy.assert_called_once_with("STAGE-014", ["SOP-001"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "legacy")
        self.assertEqual(result["created"], ("SOP-001",))

    def test_never_participates_in_transition_stage_status(self):
        """п.35: sync_stage_sop_knowledge должен нигде не вызываться из
        transition_stage_status() — SOP не участвует в Stage Completion Gate."""
        import inspect

        source = inspect.getsource(bb.transition_stage_status)
        self.assertNotIn("sync_stage_sop_knowledge", source)
        self.assertNotIn("sop_registry", source)


# ────────────────────────────────────────────────────────────
# /syncstageknowledge — async command behavior
# ────────────────────────────────────────────────────────────

_NO_SOP_KNOWLEDGE_DEFAULT = {
    "ok": False, "code": "NO_SOP_KNOWLEDGE",
    "error": "У Template Stage нет sop relations, ни legacy-значений",
    "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
    "to_add": (), "already_present": (), "created": (),
}


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
                                 "to_add": ("DOC-012",), "already_present": (), "created": ()}) as mock_fn, \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=_NO_SOP_KNOWLEDGE_DEFAULT):
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
                                 "to_add": ("DOC-012",), "already_present": (), "created": ("DOC-012",)}) as mock_fn, \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=_NO_SOP_KNOWLEDGE_DEFAULT):
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
                                 "to_add": (), "already_present": (), "created": ()}), \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=_NO_SOP_KNOWLEDGE_DEFAULT):
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
                                 "to_add": (), "already_present": ("DOC-012",), "created": ()}), \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=_NO_SOP_KNOWLEDGE_DEFAULT):
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-012", msg)
        self.assertIn("ничего", msg.lower())

    def test_sop_preview_shows_source_and_to_add(self):
        """п.30: preview показывает источник и список добавления для SOP."""
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014")

        doc_ok_nothing = {
            "ok": False, "code": "NO_DOCUMENT_TEMPLATE_RELATIONS", "error": "нет документов",
            "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
            "to_add": (), "already_present": (), "created": (),
        }
        sop_preview = {
            "ok": True, "code": "STAGE_SOP_SYNC_PREVIEW", "error": None,
            "stage_id": "STAGE-014", "template_stage_id": "TSTG-030", "source": "legacy",
            "to_add": ("SOP-001",), "already_present": (), "created": (),
        }
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements", return_value=doc_ok_nothing), \
             patch("business_core.business_builder.sync_stage_sop_knowledge", return_value=sop_preview):
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("SOP-001", msg)
        self.assertIn("legacy", msg.lower())
        self.assertIn("confirm=yes", msg)

    def test_sop_confirm_yes_creates_relation(self):
        """п.31: confirm=yes создаёт relation для SOP."""
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014 confirm=yes")

        doc_ok_nothing = {
            "ok": False, "code": "NO_DOCUMENT_TEMPLATE_RELATIONS", "error": "нет документов",
            "stage_id": "STAGE-014", "template_stage_id": "TSTG-030",
            "to_add": (), "already_present": (), "created": (),
        }
        sop_synced = {
            "ok": True, "code": "STAGE_SOP_SYNCED", "error": None,
            "stage_id": "STAGE-014", "template_stage_id": "TSTG-030", "source": "legacy",
            "to_add": ("SOP-001",), "already_present": (), "created": ("SOP-001",),
        }
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements", return_value=doc_ok_nothing), \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=sop_synced) as mock_sop:
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        _, kwargs = mock_sop.call_args
        self.assertEqual(kwargs.get("dry_run"), False)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("SOP-001", msg)
        self.assertIn("✅", msg)

    def test_document_sync_unaffected_by_sop_addition(self):
        """п.34: document sync продолжает работать без изменений — ту
        же самую функцию продолжает вызывать команда, с теми же кодами
        и тем же текстом рендеринга, независимо от результата sop sync."""
        update, context = _cmd("/syncstageknowledge stage_id=STAGE-014 confirm=yes")

        doc_synced = {
            "ok": True, "code": "STAGE_KNOWLEDGE_SYNCED", "error": None,
            "stage_id": "STAGE-014", "template_stage_id": "TSTG-030", "source": "legacy",
            "to_add": ("DOC-012",), "already_present": (), "created": ("DOC-012",),
        }
        with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
             patch("business_core.business_builder.sync_stage_document_requirements",
                   return_value=doc_synced) as mock_doc, \
             patch("business_core.business_builder.sync_stage_sop_knowledge",
                   return_value=_NO_SOP_KNOWLEDGE_DEFAULT):
            asyncio.run(th.syncstageknowledge_cmd(update, context))

        mock_doc.assert_called_once_with("STAGE-014", dry_run=False)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-012", msg)


if __name__ == "__main__":
    unittest.main()
