"""
Phase 15A: Document Registry Foundation — mock tests.

Scope: register ONE already-existing Drive file against optional
Client/Object/Roadmap/Stage/Document Template links. No upload-from-
Telegram, no review workflow, no versioning UX, no bulk operations.

Covers:
- ID generation (DREG prefix, no collision with document_template_registry's
  DOC- prefix), Document Family ID generator (DFAM, column-aware).
- resolve_and_validate_links(): required Business ID, invalid references,
  contradictory relationship chains, auto-derivation cascade.
- /registerdoc: immutable snapshot, confirmation, cancel, duplicate
  confirmation, exactly one row created.
- /doc, /docs4stage: read-only.
- Old registries (document_template_registry, roadmap_stages, ...)
  never modified by any of this.

All tests fully mock business_core.sheets / integrations.google_drive_adapter
— no live Google Sheets/Drive API calls.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

DOC_HEADERS = [
    "Document ID", "Document Family ID", "Version",
    "Business ID", "Client ID", "Object ID", "Roadmap ID", "Stage ID",
    "Document Template ID",
    "Document Name", "Status",
    "Drive File ID", "Drive File URL", "File Name", "Mime Type",
    "Uploaded At", "Uploaded By",
    "Reviewed At", "Reviewed By", "Rejection Reason",
    "Notes", "Created At", "Updated At",
]


def _fresh_drm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_registry_manager as drm
    return drm


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _make_doc_sheet(existing_rows=None):
    sheet = MagicMock()
    values = [DOC_HEADERS] + (existing_rows or [])
    sheet.get_all_values.return_value = values
    sheet.row_values.side_effect = lambda r: values[r - 1] if 0 <= r - 1 < len(values) else []
    appended = []
    def _update(values, range_name):
        appended.append(values[0])
    sheet.update.side_effect = _update
    sheet._appended = appended
    return sheet


BIZ_ROWS = [
    {"ID": "BIZ-001", "Название": "Узаконение недвижимости", "Статус": "active"},
    {"ID": "BIZ-002", "Название": "Визы и документы", "Статус": "active"},
]
PERSON_ROWS = [{"ID": "PRS-001", "Biz IDs": "BIZ-001", "Primary Biz ID": "BIZ-001"}]
OBJECT_ROWS = [{"OBJ ID": "OBJ-001", "Client ID": "PRS-001", "Biz ID": "BIZ-001"}]
ROADMAP_ROWS = [{"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Object ID": "OBJ-001"}]
STAGE_ROWS = [{"Stage ID": "STAGE-001", "Roadmap ID": "RM-001",
               "Document Template IDs": "DOC-IZH-KP-001"}]
TEMPLATE_ROWS = [{"Document Template ID": "DOC-IZH-KP-001", "Biz ID": "BIZ-001"}]


def _patch_registries(doc_sheet=None):
    return [
        patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect),
        patch("business_core.sheets.get_business_sheet",
              return_value=doc_sheet if doc_sheet is not None else _make_doc_sheet()),
    ]


def _read_business_sheet_side_effect(sheet_key, *a, **kw):
    return {
        "biz_registry": BIZ_ROWS,
        "people_registry": PERSON_ROWS,
        "object_registry": OBJECT_ROWS,
        "roadmaps": ROADMAP_ROWS,
        "roadmap_stages": STAGE_ROWS,
        "document_template_registry": TEMPLATE_ROWS,
        "document_registry": [],
    }.get(sheet_key, [])


# ────────────────────────────────────────────────────────────
# ID generation / prefix collision
# ────────────────────────────────────────────────────────────

class TestIdGeneration(unittest.TestCase):
    def test_document_id_uses_dreg_prefix_not_doc(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["document_registry"], "DREG")
        self.assertNotEqual(_ID_PREFIXES["document_registry"], _ID_PREFIXES["document_template_registry"])

    def test_document_id_generation_empty_sheet(self):
        from business_core.sheets import generate_next_id
        sheet = _make_doc_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            doc_id = generate_next_id("document_registry")
        self.assertEqual(doc_id, "DREG-001")

    def test_family_id_generation_empty_sheet(self):
        drm = _fresh_drm()
        sheet = _make_doc_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            fam_id = drm.generate_next_family_id()
        self.assertEqual(fam_id, "DFAM-001")

    def test_family_id_continues_from_existing(self):
        drm = _fresh_drm()
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        row = [""] * len(DOC_HEADERS)
        row[idx["Document Family ID"]] = "DFAM-005"
        sheet = _make_doc_sheet(existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            fam_id = drm.generate_next_family_id()
        self.assertEqual(fam_id, "DFAM-006")

    def test_family_id_generator_scans_family_column_not_column_one(self):
        """Document ID (column 1) and Document Family ID are independent
        counters — a high Document ID number must not affect Family ID."""
        drm = _fresh_drm()
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        row = [""] * len(DOC_HEADERS)
        row[idx["Document ID"]] = "DREG-099"
        row[idx["Document Family ID"]] = "DFAM-001"
        sheet = _make_doc_sheet(existing_rows=[row])
        with patch("business_core.sheets.get_business_sheet", return_value=sheet):
            fam_id = drm.generate_next_family_id()
        self.assertEqual(fam_id, "DFAM-002")


# ────────────────────────────────────────────────────────────
# resolve_and_validate_links
# ────────────────────────────────────────────────────────────

class TestResolveAndValidateLinks(unittest.TestCase):
    def test_business_id_required(self):
        drm = _fresh_drm()
        result = drm.resolve_and_validate_links(business_id="")
        self.assertFalse(result["ok"])
        self.assertIn("Business ID", result["error"])

    def test_unknown_business_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(business_id="BIZ-999")
        self.assertFalse(result["ok"])
        self.assertIn("BIZ-999", result["error"])

    def test_unknown_stage_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(business_id="BIZ-001", stage_id="STAGE-999")
        self.assertFalse(result["ok"])
        self.assertIn("STAGE-999", result["error"])

    def test_valid_full_chain_resolves(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]):
            result = drm.resolve_and_validate_links(
                business_id="BIZ-001", client_id="PRS-001", object_id="OBJ-001",
                roadmap_id="RM-001", stage_id="STAGE-001",
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["roadmap_id"], "RM-001")

    def test_auto_derives_roadmap_from_stage_only(self):
        """Только stage_id указан — roadmap_id/object_id/client_id
        должны подтянуться автоматически."""
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]):
            result = drm.resolve_and_validate_links(business_id="BIZ-001", stage_id="STAGE-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["roadmap_id"], "RM-001")
        self.assertEqual(result["resolved"]["object_id"], "OBJ-001")
        self.assertEqual(result["resolved"]["client_id"], "PRS-001")

    def test_contradictory_stage_roadmap_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(
                business_id="BIZ-001", stage_id="STAGE-001", roadmap_id="RM-002",
            )
        self.assertFalse(result["ok"])
        self.assertIn("Противоречие", result["error"])

    def test_contradictory_object_client_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(
                business_id="BIZ-001", object_id="OBJ-001", client_id="PRS-999",
            )
        self.assertFalse(result["ok"])
        self.assertIn("Противоречие", result["error"])

    def test_roadmap_belongs_to_different_business_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(business_id="BIZ-002", roadmap_id="RM-001")
        self.assertFalse(result["ok"])
        self.assertIn("Противоречие", result["error"])

    def test_unknown_document_template_rejected(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_and_validate_links(business_id="BIZ-001", document_template_id="DOC-999")
        self.assertFalse(result["ok"])
        self.assertIn("DOC-999", result["error"])


# ────────────────────────────────────────────────────────────
# /registerdoc — start/confirm flow
# ────────────────────────────────────────────────────────────

def _upd(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _ctx(args=None):
    context = MagicMock()
    context.user_data = {}
    context.args = args or []
    return context


def _cmd(cmdline: str):
    """Build (update, context) from a full command line, mirroring what
    python-telegram-bot actually provides: context.args excludes the
    leading /command token, unlike update.message.text which includes
    it. Building both from the SAME string keeps them consistent."""
    update = _upd(cmdline)
    context = _ctx(args=cmdline.split()[1:])
    return update, context


GOOD_META = {
    "ok": True, "name": "passport.pdf", "mime_type": "application/pdf",
    "trashed": False, "web_view_link": "https://drive.google.com/file/d/abc123/view",
}
GOOD_META_NO_WEBVIEW = {
    "ok": True, "name": "passport.pdf", "mime_type": "application/pdf",
    "trashed": False, "web_view_link": "",
}


class TestRegisterDocStart(unittest.TestCase):
    def test_missing_required_args(self):
        th = _fresh_th()
        update, context = _cmd("/registerdoc business=BIZ-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.registerdoc_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("regdoc_confirmed_snapshot", context.user_data)

    def test_invalid_reference_does_not_reach_confirmation(self):
        th = _fresh_th()
        update, context = _cmd('/registerdoc business=BIZ-999 name="Doc" drive=abc123')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
                return await th.registerdoc_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("regdoc_confirmed_snapshot", context.user_data)

    def test_happy_path_shows_confirmation_snapshot(self):
        th = _fresh_th()
        update, context = _cmd('/registerdoc business=BIZ-001 stage=STAGE-001 name="Техпаспорт" drive=abc123')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]), \
                 patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
                 patch("integrations.google_drive_adapter.get_file_metadata", return_value=GOOD_META):
                return await th.registerdoc_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertNotEqual(result, ConversationHandler.END)
        snap = context.user_data["regdoc_confirmed_snapshot"]
        self.assertEqual(snap["business_id"], "BIZ-001")
        self.assertEqual(snap["roadmap_id"], "RM-001")  # auto-derived from stage
        self.assertEqual(snap["file_name"], "passport.pdf")
        self.assertEqual(snap["web_view_link"], GOOD_META["web_view_link"])
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("Техпаспорт", card)

    def test_confirmation_card_shows_all_six_resolved_links_explicitly(self):
        """Карточка должна показывать финальные НОРМАЛИЗОВАННЫЕ связи
        (все шесть, включая пустые как '—'), а не только то, что ввёл
        пользователь — если указан только stage=, auto-derived
        Roadmap/Object/Client должны быть видны, а Document Template ID
        (не указан) — явно как '—'."""
        th = _fresh_th()
        update, context = _cmd('/registerdoc business=BIZ-001 stage=STAGE-001 name="Техпаспорт" drive=abc123')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]), \
                 patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
                 patch("integrations.google_drive_adapter.get_file_metadata", return_value=GOOD_META):
                await th.registerdoc_start(update, context)

        asyncio.run(run())
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("Business ID: BIZ-001", card)
        self.assertIn("Client ID: PRS-001", card)     # auto-derived
        self.assertIn("Object ID: OBJ-001", card)      # auto-derived
        self.assertIn("Roadmap ID: RM-001", card)      # auto-derived
        self.assertIn("Stage ID: STAGE-001", card)
        self.assertIn("Document Template ID: —", card)  # not given, shown explicitly

    def test_trashed_file_rejected(self):
        th = _fresh_th()
        update, context = _cmd('/registerdoc business=BIZ-001 name="Doc" drive=abc123')
        trashed_meta = {"ok": True, "name": "x.pdf", "mime_type": "application/pdf", "trashed": True}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
                 patch("integrations.google_drive_adapter.get_file_metadata", return_value=trashed_meta):
                return await th.registerdoc_start(update, context)

        from telegram.ext import ConversationHandler
        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("regdoc_confirmed_snapshot", context.user_data)


def _dummy_saved_row(**overrides):
    values = ["DREG-001", "DFAM-001", "1", "BIZ-001", "", "", "", "", "",
              "Техпаспорт", "uploaded", "abc123",
              "https://drive.google.com/file/d/abc123/view", "passport.pdf",
              "application/pdf", "2026-01-01 00:00:00 UTC", "dida",
              "", "", "", "", "2026-01-01 00:00:00 UTC", "2026-01-01 00:00:00 UTC"]
    row = dict(zip(DOC_HEADERS, values))
    row.update(overrides)
    return row


class TestRegisterDocConfirm(unittest.TestCase):
    def _walk_to_confirm(self, extra_args="", meta=None):
        th = _fresh_th()
        update, context = _cmd(f'/registerdoc business=BIZ-001 name="Техпаспорт" drive=abc123 {extra_args}')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
                 patch("integrations.google_drive_adapter.get_file_metadata", return_value=meta or GOOD_META):
                await th.registerdoc_start(update, context)

        asyncio.run(run())
        return th, context

    def test_confirm_creates_exactly_one_row(self):
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()
        update = _upd("✅ Подтвердить")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, _dummy_saved_row())):
                await th.registerdoc_confirm(update, context)

        asyncio.run(run())
        self.assertEqual(len(sheet._appended), 1)
        self.assertNotIn("regdoc_confirmed_snapshot", context.user_data)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("DREG-001", reply)

    def test_ids_generated_from_single_sheet_read(self):
        """DREG и DFAM обе вычисляются из ОДНОГО get_all_values() call
        made explicitly for ID generation — not two separate reads (one
        per prefix). append_business_row() then does its own SEPARATE
        internal get_all_values() to determine the next row number —
        that is an existing, unavoidable characteristic of the shared
        primitive used by every write command in this codebase (editclient,
        Stage Management, ...), not a second ID-generation read. Total
        expected get_business_sheet calls for one confirm: 2 (one for
        ID generation, one inside append_business_row)."""
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()
        update = _upd("✅ Подтвердить")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet) as mock_get_sheet, \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _dummy_saved_row())):
                await th.registerdoc_confirm(update, context)
                self.assertEqual(mock_get_sheet.call_count, 2)
                for call in mock_get_sheet.call_args_list:
                    self.assertEqual(call.args[0], "document_registry")

        asyncio.run(run())
        written_row = sheet._appended[0]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(written_row[idx["Document ID"]], "DREG-001")
        self.assertEqual(written_row[idx["Document Family ID"]], "DFAM-001")
        self.assertEqual(written_row[idx["Version"]], "1")

    def test_drive_file_url_uses_webviewlink_verbatim(self):
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()
        update = _upd("✅ Подтвердить")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _dummy_saved_row())):
                await th.registerdoc_confirm(update, context)

        asyncio.run(run())
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(
            sheet._appended[0][idx["Drive File URL"]],
            "https://drive.google.com/file/d/abc123/view",
        )

    def test_missing_webviewlink_leaves_url_empty_but_still_registers(self):
        th, context = self._walk_to_confirm(meta=GOOD_META_NO_WEBVIEW)
        sheet = _make_doc_sheet()
        update = _upd("✅ Подтвердить")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _dummy_saved_row())):
                await th.registerdoc_confirm(update, context)

        asyncio.run(run())
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(len(sheet._appended), 1)
        self.assertEqual(sheet._appended[0][idx["Drive File URL"]], "")

    def test_uploaded_at_created_at_updated_at_share_one_utc_timestamp(self):
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()
        update = _upd("✅ Подтвердить")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _dummy_saved_row())):
                await th.registerdoc_confirm(update, context)

        asyncio.run(run())
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        row = sheet._appended[0]
        self.assertEqual(row[idx["Uploaded At"]], row[idx["Created At"]])
        self.assertEqual(row[idx["Created At"]], row[idx["Updated At"]])
        self.assertIn("UTC", row[idx["Uploaded At"]])

    def test_cancel_creates_no_row(self):
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()
        update = _upd("❌ Отмена")

        async def run():
            with patch("business_core.sheets.get_business_sheet", return_value=sheet):
                await th.registerdoc_confirm(update, context)

        asyncio.run(run())
        self.assertEqual(len(sheet._appended), 0)
        self.assertNotIn("regdoc_confirmed_snapshot", context.user_data)

    def test_duplicate_confirmation_does_not_create_second_row_or_touch_ids_or_drive(self):
        """Второе нажатие '✅ Подтвердить' после того, как snapshot уже
        очищен первым подтверждением, не должно: создавать вторую строку,
        генерировать новые DREG/DFAM, снова обращаться к Sheets/Drive API."""
        th, context = self._walk_to_confirm()
        sheet = _make_doc_sheet()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet) as mock_get_sheet, \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, _dummy_saved_row())), \
                 patch("integrations.google_drive_adapter.get_drive_service") as mock_drive_service, \
                 patch("integrations.google_drive_adapter.get_file_metadata") as mock_get_meta:
                await th.registerdoc_confirm(_upd("✅ Подтвердить"), context)  # first
                calls_after_first = mock_get_sheet.call_count
                await th.registerdoc_confirm(_upd("✅ Подтвердить"), context)  # second (duplicate)
                # Второй confirm не должен трогать document_registry снова,
                # и уж тем более не должен обращаться к Drive API.
                self.assertEqual(mock_get_sheet.call_count, calls_after_first)
                mock_drive_service.assert_not_called()
                mock_get_meta.assert_not_called()

        asyncio.run(run())
        self.assertEqual(len(sheet._appended), 1)


class TestDocCmd(unittest.TestCase):
    def test_read_by_document_id(self):
        th = _fresh_th()
        row = dict(zip(DOC_HEADERS,
            ["DREG-001", "DFAM-001", "1", "BIZ-001", "", "", "RM-001", "STAGE-001",
             "", "Техпаспорт", "uploaded", "abc123", "url", "passport.pdf",
             "application/pdf", "2026-01-01", "dida", "", "", "", "", "", ""]))
        update, context = _upd("/doc document_id=DREG-001"), _ctx(args=["document_id=DREG-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=(2, row)):
                await th.doc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DREG-001", msg)
        self.assertIn("Техпаспорт", msg)

    def test_not_found(self):
        th = _fresh_th()
        update, context = _upd("/doc document_id=DREG-999"), _ctx(args=["document_id=DREG-999"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.find_row_by_id", return_value=None):
                await th.doc_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не найден", msg)


class TestDocs4StageCmd(unittest.TestCase):
    def test_list_by_stage_id_with_missing_requirement(self):
        th = _fresh_th()
        update, context = _upd("/docs4stage stage_id=STAGE-001"), _ctx(args=["stage_id=STAGE-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
                await th.docs4stage_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("DOC-IZH-KP-001", msg)  # missing requirement listed

    def test_unmatchable_stage_shows_explicit_not_matched(self):
        th = _fresh_th()
        stage_no_template = [{"Stage ID": "STAGE-002", "Roadmap ID": "RM-001", "Document Template IDs": ""}]

        def _side_effect(sheet_key, *a, **kw):
            if sheet_key == "roadmap_stages":
                return stage_no_template
            return _read_business_sheet_side_effect(sheet_key, *a, **kw)

        update, context = _upd("/docs4stage stage_id=STAGE-002"), _ctx(args=["stage_id=STAGE-002"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_side_effect):
                await th.docs4stage_cmd(update, context)

        asyncio.run(run())
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("не сопоставлен", msg)


class TestOldRegistriesUntouched(unittest.TestCase):
    def test_registerdoc_never_writes_to_other_sheets(self):
        th = _fresh_th()
        update, context = _cmd('/registerdoc business=BIZ-001 stage=STAGE-001 name="Техпаспорт" drive=abc123')

        async def start():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]), \
                 patch("integrations.google_drive_adapter.get_drive_service", return_value=MagicMock()), \
                 patch("integrations.google_drive_adapter.get_file_metadata", return_value=GOOD_META):
                await th.registerdoc_start(update, context)

        asyncio.run(start())

        sheet = _make_doc_sheet()

        async def confirm():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.sheets.get_business_sheet", return_value=sheet) as mock_get_sheet, \
                 patch("business_core.sheets.find_row_by_id",
                       return_value=(2, _dummy_saved_row(**{"Roadmap ID": "RM-001", "Stage ID": "STAGE-001"}))):
                await th.registerdoc_confirm(_upd("✅ Подтвердить"), context)
                # get_business_sheet должен вызываться ТОЛЬКО с 'document_registry'
                for call in mock_get_sheet.call_args_list:
                    self.assertEqual(call.args[0], "document_registry")

        asyncio.run(confirm())


class TestNoLiveApi(unittest.TestCase):
    def test_import_does_not_touch_sheets(self):
        for key in list(sys.modules.keys()):
            if "business_core" in key:
                del sys.modules[key]
        with patch("business_core.sheets.get_business_sheet") as mock_get_sheet:
            import business_core.telegram_handlers  # noqa: F401
            import business_core.document_registry_manager  # noqa: F401
        mock_get_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
