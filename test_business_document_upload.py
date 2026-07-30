"""
Phase 15B: Telegram Document Upload Foundation — mock tests.

Scope: upload exactly ONE Telegram document to an existing Drive folder
and register exactly one DOCUMENT_REGISTRY row (Version=1, Status=uploaded).
No /approvedoc, /rejectdoc, /docversions, OCR, bulk upload, keyword-based
document-type guessing, or new Drive folder architecture.

Covers:
- /uploaddoc UD_FILE step: accepts exactly one Telegram document, rejects
  every other media type and albums, without ending the conversation.
- UD_DETAILS step: required Business, optional links, most-specific-first
  auto-fill (reusing resolve_and_validate_links from Phase 15A), folder
  priority Object -> Client -> Business (Stage folder never attempted),
  stop-before-upload when no folder exists, immutable confirmation
  snapshot.
- UD_CONFIRM step: Telegram download only starts after confirmation,
  correct Drive parent folder, Drive URL taken from webViewLink verbatim,
  unique DREG/DFAM ids, Version=1, Status=uploaded, exactly one header-safe
  row, post-write re-read, duplicate-confirm protection, cancel writes
  nothing, Drive upload failure writes nothing, registry write failure
  triggers Drive cleanup (success and orphan-on-failure paths), temp file
  cleanup on both success and error paths, markdown-unsafe filenames don't
  break the reply.
- Regression: existing /registerdoc, /doc, /docs4stage untouched;
  register_business_handlers() still registers everything without error.

All tests fully mock business_core.sheets, business_core.business_builder,
integrations.google_drive_adapter and the Telegram bot/file API — no live
network calls, no live Google Sheets/Drive API calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from telegram.ext import ConversationHandler

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


def _fresh_th():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.telegram_handlers as th
    return th


def _fresh_drm():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    import business_core.document_registry_manager as drm
    return drm


def _make_doc_sheet(existing_rows=None):
    sheet = MagicMock()
    values = [DOC_HEADERS] + (existing_rows or [])
    sheet.get_all_values.return_value = values
    appended = []

    def _update(values, range_name):
        appended.append(values[0])

    sheet.update.side_effect = _update
    sheet._appended = appended
    return sheet


# ────────────────────────────────────────────────────────────
# Shared fixtures: Object/Client/Business all have a populated
# Drive Folder ID, so folder-priority tests can assert which one wins.
# ────────────────────────────────────────────────────────────

BIZ_ROWS = [
    {"ID": "BIZ-001", "Название": "Test Biz", "Статус": "active", "Drive Folder ID": "BIZFOLDER1"},
    {"ID": "BIZ-002", "Название": "No Folder Biz", "Статус": "active", "Drive Folder ID": ""},
]
PERSON_ROWS = [
    {"ID": "PRS-001", "Biz IDs": "BIZ-001", "Primary Biz ID": "BIZ-001", "Drive Folder ID": "PRSFOLDER1"},
]
OBJECT_ROWS = [
    {"OBJ ID": "OBJ-001", "Client ID": "PRS-001", "Biz ID": "BIZ-001", "Drive Folder ID": "OBJFOLDER1"},
]
ROADMAP_ROWS = [{"Roadmap ID": "RM-001", "Business ID": "BIZ-001", "Object ID": "OBJ-001"}]
STAGE_ROWS = [{"Stage ID": "STAGE-001", "Roadmap ID": "RM-001", "Document Template IDs": "DOC-IZH-KP-001"}]
TEMPLATE_ROWS = [{"Document Template ID": "DOC-IZH-KP-001", "Biz ID": "BIZ-001"}]


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


def _find_object_by_id_side_effect(object_id, *a, **kw):
    """Phase 30D: document_registry_manager now reads OBJECT_REGISTRY via
    business_core.object_manager.find_object_by_id() (canonical dict
    shape) instead of a raw read_business_sheet("object_registry")
    call — this mirrors OBJECT_ROWS in the object_manager return shape."""
    for row in OBJECT_ROWS:
        if row.get("OBJ ID") == object_id:
            return {
                "object_id": row.get("OBJ ID", ""),
                "client_id": row.get("Client ID", ""),
                "biz_id": row.get("Biz ID", ""),
                "drive_folder_id": row.get("Drive Folder ID", ""),
                "drive_url": row.get("Google Drive", ""),
            }
    return None


GOOD_FOLDER_META = {"ok": True, "name": "06 Клиенты", "mime_type": "application/vnd.google-apps.folder",
                    "trashed": False, "web_view_link": "https://drive.google.com/drive/folders/OBJFOLDER1"}
GOOD_UPLOAD_META = {"ok": True, "name": "passport.pdf", "mime_type": "application/pdf",
                    "trashed": False, "web_view_link": "https://drive.google.com/file/d/NEWFILE1/view"}


def _make_tg_file(content=b"PDF-BYTES"):
    tg_file = MagicMock()

    async def _download(buf):
        buf.write(content)

    tg_file.download_to_memory = AsyncMock(side_effect=_download)
    return tg_file


def _doc_update(file_name="passport.pdf", mime_type="application/pdf", file_size=1234,
                 file_id="tgfile123", file_unique_id="uniq123", media_group_id=None):
    update = MagicMock()
    update.message.document = MagicMock(
        file_id=file_id, file_unique_id=file_unique_id,
        file_name=file_name, mime_type=mime_type, file_size=file_size,
    )
    update.message.media_group_id = media_group_id
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _non_doc_update(kind="photo"):
    """A message carrying some other media type — no .document at all."""
    update = MagicMock()
    update.message.document = None
    update.message.media_group_id = None
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _text_update(text):
    update = MagicMock()
    update.message.text = text
    update.message.document = None
    update.message.media_group_id = None
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _ctx(user_data=None):
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    context.args = []
    context.bot = MagicMock()
    context.bot.get_file = AsyncMock(return_value=_make_tg_file())
    return context


def _fake_tmp_patches():
    """Avoid real disk I/O: fake tempfile.NamedTemporaryFile / os.path.exists / os.remove."""
    tmp = MagicMock()
    tmp.name = "/tmp/fake_upload_test_file"
    tmp.__enter__ = MagicMock(return_value=tmp)
    tmp.__exit__ = MagicMock(return_value=False)
    return [
        patch("business_core.telegram_handlers.tempfile.NamedTemporaryFile", return_value=tmp),
        patch("business_core.telegram_handlers.os.path.exists", return_value=True),
        patch("business_core.telegram_handlers.os.remove"),
    ]


def _enter_all(patches):
    mocks = [p.start() for p in patches]
    return mocks


def _exit_all(patches):
    for p in reversed(patches):
        p.stop()


# ────────────────────────────────────────────────────────────
# UD_FILE step
# ────────────────────────────────────────────────────────────

class TestUploadDocFileStep(unittest.TestCase):
    def test_start_asks_for_document(self):
        th = _fresh_th()
        update, context = _text_update("/uploaddoc"), _ctx()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        result = asyncio.run(run())
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)

    def test_disabled_business_core_ends_immediately(self):
        th = _fresh_th()
        update, context = _text_update("/uploaddoc"), _ctx()

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=False):
                return await th.uploaddoc_start(update, context)

        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)

    def test_accepts_one_document(self):
        th = _fresh_th()
        update, context = _doc_update(), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_DETAILS)
        self.assertEqual(context.user_data["ud"]["tg_file_id"], "tgfile123")
        self.assertEqual(context.user_data["ud"]["tg_file_name"], "passport.pdf")
        self.assertEqual(context.user_data["ud"]["tg_mime_type"], "application/pdf")
        self.assertEqual(context.user_data["ud"]["tg_file_size"], 1234)
        self.assertEqual(context.user_data["ud"]["uploaded_by"], "dida")

    def test_rejects_photo_stays_in_ud_file(self):
        th = _fresh_th()
        update, context = _non_doc_update("photo"), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("документ", card.lower())

    def test_rejects_text_without_file(self):
        th = _fresh_th()
        update, context = _non_doc_update(), _ctx()
        update.message.text = "просто текст"

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)

    def test_rejects_media_group_album(self):
        th = _fresh_th()
        update, context = _doc_update(media_group_id="grp-1"), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("альбом", card.lower())

    def test_dangerous_file_rejected_before_reaching_details_step(self):
        """Phase 37F.1: a dangerous storage type must be rejected at the
        file-receive step — never proceeds to ask for business=/name=,
        never reaches Drive."""
        th = _fresh_th()
        update, context = _doc_update(file_name="setup.exe", mime_type="application/x-msdownload"), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", card)

    def test_invalid_filename_rejected_before_reaching_details_step(self):
        th = _fresh_th()
        update, context = _doc_update(file_name="bad\x00name.pdf"), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)

    def test_oversized_file_rejected_before_reaching_details_step(self):
        th = _fresh_th()
        update, context = _doc_update(file_size=999_999_999_999), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud", context.user_data)

    def test_analysis_unsupported_file_still_accepted(self):
        """Storage-allowed-but-analysis-unsupported (e.g. RTF, matching
        the existing production Document) must still proceed to
        UD_DETAILS — AI support is never a prerequisite for storage."""
        th = _fresh_th()
        update, context = _doc_update(file_name="contract.rtf", mime_type="application/rtf"), _ctx()

        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_DETAILS)
        self.assertIn("ud", context.user_data)

    def test_valid_file_never_calls_drive_or_persistence(self):
        th = _fresh_th()
        update, context = _doc_update(), _ctx()
        with patch("business_core.document_manager.create_document") as mock_create, \
             patch("integrations.google_drive_adapter.get_drive_service") as mock_drive:
            asyncio.run(th.uploaddoc_receive_file(update, context))
        mock_create.assert_not_called()
        mock_drive.assert_not_called()


# ────────────────────────────────────────────────────────────
# UD_DETAILS step
# ────────────────────────────────────────────────────────────

def _ud_draft():
    return {
        "tg_file_id": "tgfile123", "tg_file_unique_id": "uniq123",
        "tg_file_name": "passport.pdf", "tg_mime_type": "application/pdf",
        "tg_file_size": 1234, "uploaded_by": "dida",
    }


class TestUploadDocDetailsStep(unittest.TestCase):
    def _run_details(self, text, user_data=None):
        th = _fresh_th()
        ud = user_data if user_data is not None else {"ud": _ud_draft()}
        update, context = _text_update(text), _ctx(user_data=ud)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                           side_effect=_read_business_sheet_side_effect))
                stack.enter_context(patch("business_core.object_manager.find_object_by_id",
                                           side_effect=_find_object_by_id_side_effect))
                stack.enter_context(patch("business_core.person_manager.find_person_by_id",
                                           return_value={"biz_ids": ["BIZ-001"], "drive_folder_id": "PRSFOLDER1"}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_FOLDER_META))
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_no_draft_ends_conversation(self):
        th = _fresh_th()
        update, context = _text_update('business=BIZ-001 name="Doc"'), _ctx(user_data={})
        result = asyncio.run(th.uploaddoc_receive_details(update, context))
        self.assertEqual(result, ConversationHandler.END)

    def test_missing_business_required(self):
        th, update, context, result = self._run_details('name="Doc"')
        self.assertEqual(result, th.UD_DETAILS)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_missing_name_required(self):
        th, update, context, result = self._run_details('business=BIZ-001')
        self.assertEqual(result, th.UD_DETAILS)

    def test_invalid_business_rejected(self):
        th, update, context, result = self._run_details('business=BIZ-999 name="Doc"')
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_stage_roadmap_conflict_rejected(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" stage=STAGE-001 roadmap=RM-999'
        )
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_object_client_conflict_rejected(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" object=OBJ-001 client=PRS-999'
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_business_conflict_rejected(self):
        th, update, context, result = self._run_details(
            'business=BIZ-002 name="Doc" object=OBJ-001'
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_document_template_conflict_rejected(self):
        conflicting_template = [{"Document Template ID": "DOC-OTHER-001", "Biz ID": "BIZ-002"}]

        def side_effect(key, *a, **kw):
            if key == "document_template_registry":
                return conflicting_template
            return _read_business_sheet_side_effect(key, *a, **kw)

        th = _fresh_th()
        update, context = _text_update(
            'business=BIZ-001 name="Doc" template=DOC-OTHER-001'
        ), _ctx(user_data={"ud": _ud_draft()})

        async def run():
            with patch("business_core.sheets.read_business_sheet", side_effect=side_effect), \
                 patch("business_core.object_manager.find_object_by_id",
                       side_effect=_find_object_by_id_side_effect), \
                 patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]):
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)

    def test_no_keyword_matching_unrelated_name_does_not_derive_links(self):
        """Document Name text must never be parsed for entity hints —
        only explicit business=/client=/object=/... kv args are used."""
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="OBJ-001 STAGE-001 mentioned in title"'
        )
        self.assertNotEqual(result, ConversationHandler.END)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["object_id"], "")
        self.assertEqual(snap["stage_id"], "")

    def test_most_specific_first_autofill_from_stage(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" stage=STAGE-001'
        )
        self.assertNotEqual(result, ConversationHandler.END)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["roadmap_id"], "RM-001")
        self.assertEqual(snap["object_id"], "OBJ-001")
        self.assertEqual(snap["client_id"], "PRS-001")

    def test_folder_priority_object_wins_over_client_and_business(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" object=OBJ-001'
        )
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["folder_level"], "object")
        self.assertEqual(snap["folder_id"], "OBJFOLDER1")

    def test_folder_priority_client_wins_over_business_when_no_object(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" client=PRS-001'
        )
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["folder_level"], "client")
        self.assertEqual(snap["folder_id"], "PRSFOLDER1")

    def test_folder_priority_business_used_when_no_object_or_client(self):
        th, update, context, result = self._run_details('business=BIZ-001 name="Doc"')
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["folder_level"], "business")
        self.assertEqual(snap["folder_id"], "BIZFOLDER1")

    def test_stage_folder_never_selected(self):
        """Even with a Stage resolved, folder selection must never use a
        'Stage folder' — ROADMAP_STAGES has no such column in this
        architecture, so it must fall through to Object/Client/Business."""
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Doc" stage=STAGE-001'
        )
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertIn(snap["folder_level"], ("object", "client", "business"))
        self.assertNotEqual(snap["folder_level"], "stage")

    def test_no_folder_available_stops_before_upload(self):
        th, update, context, result = self._run_details('business=BIZ-002 name="Doc"')
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        self.assertNotIn("ud", context.user_data)

    def test_confirmation_card_shows_final_normalized_links(self):
        th, update, context, result = self._run_details(
            'business=BIZ-001 name="Технический паспорт" stage=STAGE-001'
        )
        card = update.message.reply_text.call_args[0][0]
        self.assertIn("Business ID: BIZ-001", card)
        self.assertIn("Client ID: PRS-001", card)
        self.assertIn("Object ID: OBJ-001", card)
        self.assertIn("Roadmap ID: RM-001", card)
        self.assertIn("Stage ID: STAGE-001", card)
        self.assertIn("Document Template ID: —", card)
        self.assertIn("Target Drive Folder", card)

    def test_immutable_snapshot_unaffected_by_later_ud_mutation(self):
        th, update, context, result = self._run_details('business=BIZ-001 name="Doc"')
        snap = context.user_data["ud_confirmed_snapshot"]
        original_business = snap["business_id"]
        # 'ud' draft key is popped after snapshot creation — even if
        # something re-created it with different values, confirm must
        # never read from it again.
        context.user_data["ud"] = {"tg_file_name": "tampered.exe"}
        self.assertEqual(snap["business_id"], original_business)
        self.assertEqual(snap["tg_file_name"], "passport.pdf")


# ────────────────────────────────────────────────────────────
# UD_CONFIRM step
# ────────────────────────────────────────────────────────────

def _confirmed_snapshot(**overrides):
    snap = {
        "tg_file_id": "tgfile123", "tg_file_unique_id": "uniq123",
        "tg_file_name": "passport.pdf", "tg_mime_type": "application/pdf",
        "tg_file_size": 1234, "uploaded_by": "dida",
        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
        "document_name": "Технический паспорт", "notes": "",
        "folder_id": "OBJFOLDER1", "folder_level": "object", "folder_source_id": "OBJ-001",
        "folder_name": "06 Клиенты",
        "op_state": "pending",
    }
    snap.update(overrides)
    return snap


class TestUploadDocConfirmStep(unittest.TestCase):
    def _run_confirm(self, text="✅ Подтвердить", snap=None, doc_sheet=None,
                      append_side_effect=None, upload_side_effect=None,
                      trash_return=None, find_row_return=None, metadata_return=None):
        th = _fresh_th()
        user_data = {"ud_confirmed_snapshot": snap if snap is not None else _confirmed_snapshot()}
        update, context = _text_update(text), _ctx(user_data=user_data)

        sheet = doc_sheet if doc_sheet is not None else _make_doc_sheet()

        upload_mock = MagicMock(side_effect=upload_side_effect) if upload_side_effect else \
            MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused", "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(side_effect=append_side_effect) if append_side_effect else MagicMock(return_value=2)
        trash_mock = MagicMock(return_value=trash_return if trash_return is not None else {"ok": True, "error": ""})
        meta_return = metadata_return if metadata_return is not None else GOOD_UPLOAD_META
        used_snap = snap if snap is not None else _confirmed_snapshot()
        found = find_row_return if find_row_return is not None else (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", used_snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=meta_return))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file", trash_mock))
                stack.enter_context(patch("business_core.sheets.get_business_sheet", return_value=sheet))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                return await th.uploaddoc_confirm(update, context)

        result = asyncio.run(run())
        return th, update, context, result, upload_mock, append_mock, trash_mock

    def test_cancel_writes_nothing(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(text="❌ Отмена")
        self.assertEqual(result, ConversationHandler.END)
        upload_mock.assert_not_called()
        append_mock.assert_not_called()
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_no_snapshot_ends_safely(self):
        th = _fresh_th()
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data={})
        result = asyncio.run(th.uploaddoc_confirm(update, context))
        self.assertEqual(result, ConversationHandler.END)

    def test_download_only_happens_on_confirm(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        context.bot.get_file.assert_called_once_with("tgfile123")

    def test_drive_upload_gets_correct_parent_folder(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        call = upload_mock.call_args
        self.assertEqual(call.args[2], "OBJFOLDER1")

    def test_drive_url_from_webviewlink(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(row[idx["Drive File URL"]], GOOD_UPLOAD_META["web_view_link"])

    def test_unique_dreg_and_dfam_created(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertTrue(row[idx["Document ID"]].startswith("DREG-"))
        self.assertTrue(row[idx["Document Family ID"]].startswith("DFAM-"))

    def test_version_is_1(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(row[idx["Version"]], "1")

    def test_status_is_uploaded(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(row[idx["Status"]], "uploaded")

    def test_review_fields_left_empty(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        idx = {h: i for i, h in enumerate(DOC_HEADERS)}
        self.assertEqual(row[idx["Reviewed At"]], "")
        self.assertEqual(row[idx["Reviewed By"]], "")
        self.assertEqual(row[idx["Rejection Reason"]], "")

    def test_exactly_one_row_created(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        append_mock.assert_called_once()
        upload_mock.assert_called_once()

    def test_header_safe_row_length(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        row = append_mock.call_args[0][1]
        self.assertEqual(len(row), len(DOC_HEADERS))

    def test_post_write_reread_performed(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm()
        self.assertEqual(result, ConversationHandler.END)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("DREG-001", reply)

    def test_duplicate_confirm_processing_does_not_reupload(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            snap=_confirmed_snapshot(op_state="processing")
        )
        upload_mock.assert_not_called()
        append_mock.assert_not_called()
        self.assertEqual(result, th.UD_CONFIRM)

    def test_duplicate_confirm_completed_does_not_reupload(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            snap=_confirmed_snapshot(op_state="completed")
        )
        upload_mock.assert_not_called()
        append_mock.assert_not_called()
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_drive_upload_failure_creates_no_row(self):
        def _boom(*a, **kw):
            raise RuntimeError("drive is down")

        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            upload_side_effect=_boom,
        )
        append_mock.assert_not_called()
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", reply)
        self.assertNotIn("drive is down", reply)

    def test_registry_failure_triggers_drive_cleanup(self):
        def _boom(*a, **kw):
            raise RuntimeError("sheets api error")

        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            append_side_effect=_boom, trash_return={"ok": True, "error": ""},
        )
        trash_mock.assert_called_once()
        self.assertEqual(trash_mock.call_args[0][1], "NEWFILE1")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("перемещён в корзину", reply)
        self.assertNotIn("Orphan", reply)

    def test_registry_failure_cleanup_fails_returns_orphan(self):
        def _boom(*a, **kw):
            raise RuntimeError("sheets api error")

        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            append_side_effect=_boom, trash_return={"ok": False, "error": "trash denied"},
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Orphan Drive File ID: NEWFILE1", reply)
        self.assertIn("ручная очистка", reply)

    def test_temp_file_cleaned_up_on_success(self):
        th = _fresh_th()
        ud = {"ud_confirmed_snapshot": _confirmed_snapshot()}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=ud)
        sheet = _make_doc_sheet()
        found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", "Технический паспорт", "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        async def run():
            with contextlib.ExitStack() as stack:
                tmp = MagicMock()
                tmp.name = "/tmp/fake_upload_test_file"
                tmp.__enter__ = MagicMock(return_value=tmp)
                tmp.__exit__ = MagicMock(return_value=False)
                stack.enter_context(patch("business_core.telegram_handlers.tempfile.NamedTemporaryFile",
                                           return_value=tmp))
                stack.enter_context(patch("business_core.telegram_handlers.os.path.exists", return_value=True))
                mock_remove = stack.enter_context(patch("business_core.telegram_handlers.os.remove"))
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file",
                                           return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                          "filename": "passport.pdf", "dry_run": False}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("business_core.sheets.get_business_sheet", return_value=sheet))
                stack.enter_context(patch("business_core.sheets.append_business_row", return_value=2))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                result = await th.uploaddoc_confirm(update, context)
                return result, mock_remove

        result, mock_remove = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        mock_remove.assert_called_once_with("/tmp/fake_upload_test_file")

    def test_temp_file_cleaned_up_on_error(self):
        def _boom(*a, **kw):
            raise RuntimeError("boom")

        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            upload_side_effect=_boom,
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_markdown_unsafe_filename_does_not_break_reply(self):
        snap = _confirmed_snapshot(document_name="under_score_name_v1")
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(snap=snap)
        self.assertEqual(result, ConversationHandler.END)
        update.message.reply_text.assert_called()
        call_args = update.message.reply_text.call_args
        self.assertNotIn("parse_mode", call_args.kwargs)
        reply = call_args[0][0]
        self.assertIn("under_score_name_v1", reply)
        self.assertIn("✅ Документ загружен и зарегистрирован", reply)

    def test_reentrant_state_after_error_allows_fresh_start(self):
        def _boom(*a, **kw):
            raise RuntimeError("boom")

        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            upload_side_effect=_boom,
        )
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        self.assertNotIn("ud", context.user_data)

    # ── Drive metadata failure / incompleteness (post-review fix) ──

    def test_metadata_read_failure_triggers_cleanup_success_no_row(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            metadata_return={"ok": False, "error": "not found"},
            trash_return={"ok": True, "error": ""},
        )
        append_mock.assert_not_called()
        trash_mock.assert_called_once()
        self.assertEqual(trash_mock.call_args[0][1], "NEWFILE1")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("метадан", reply.lower())
        self.assertIn("перемещён в корзину", reply)
        self.assertNotIn("Orphan", reply)
        self.assertNotIn("✅", reply)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_metadata_read_failure_cleanup_fails_returns_orphan(self):
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            metadata_return={"ok": False, "error": "not found"},
            trash_return={"ok": False, "error": "trash denied"},
        )
        append_mock.assert_not_called()
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("Orphan Drive File ID: NEWFILE1", reply)
        self.assertIn("ручная очистка", reply)
        self.assertNotIn("✅", reply)

    def test_metadata_missing_webviewlink_is_incomplete_no_row(self):
        incomplete = {"ok": True, "name": "passport.pdf", "mime_type": "application/pdf",
                      "trashed": False, "web_view_link": ""}
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            metadata_return=incomplete,
        )
        append_mock.assert_not_called()
        trash_mock.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("✅", reply)

    def test_metadata_missing_name_is_incomplete_no_row(self):
        incomplete = {"ok": True, "name": "", "mime_type": "application/pdf",
                      "trashed": False, "web_view_link": "https://drive.google.com/file/d/NEWFILE1/view"}
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            metadata_return=incomplete,
        )
        append_mock.assert_not_called()

    def test_metadata_failure_never_produces_success_reply(self):
        for meta in (
            {"ok": False, "error": "boom"},
            {"ok": True, "name": "", "mime_type": "", "trashed": False, "web_view_link": ""},
        ):
            th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
                metadata_return=meta,
            )
            reply = update.message.reply_text.call_args[0][0]
            self.assertNotIn("✅ Документ загружен и зарегистрирован", reply)
            self.assertEqual(result, ConversationHandler.END)

    # ── Post-write verification (post-review fix) ──

    def test_post_write_row_missing_returns_manual_verification(self):
        th = _fresh_th()
        ud = {"ud_confirmed_snapshot": _confirmed_snapshot()}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=ud)
        sheet = _make_doc_sheet()

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file",
                                           return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                          "filename": "passport.pdf", "dry_run": False}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("business_core.sheets.get_business_sheet", return_value=sheet))
                append_mock = MagicMock(return_value=2)
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=None))
                return await th.uploaddoc_confirm(update, context), append_mock

        result, append_mock = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        append_mock.assert_called_once()  # the row WAS written; only the re-read failed
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("пост-проверка записи не прошла", reply)
        self.assertIn("ручная проверка", reply.lower())
        self.assertIn("Document ID: DREG-001", reply)
        self.assertIn("Drive File ID: NEWFILE1", reply)
        self.assertNotIn("✅ Документ загружен и зарегистрирован", reply)
        # snapshot cleared -> a duplicate confirm becomes a safe no-op
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_post_write_mismatch_returns_manual_verification(self):
        mismatched_found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-999", "PRS-001", "OBJ-001", "RM-001", "",
            "", "Технический паспорт", "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))
        th, update, context, result, upload_mock, append_mock, trash_mock = self._run_confirm(
            find_row_return=mismatched_found,
        )
        self.assertEqual(result, ConversationHandler.END)
        append_mock.assert_called_once()
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("пост-проверка записи не прошла", reply)
        self.assertIn("ручная проверка", reply.lower())
        self.assertNotIn("✅ Документ загружен и зарегистрирован", reply)
        trash_mock.assert_not_called()  # row may exist — never trash the Drive file here
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_duplicate_confirm_after_verification_failure_is_noop(self):
        th = _fresh_th()
        ud = {"ud_confirmed_snapshot": _confirmed_snapshot()}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=ud)
        sheet = _make_doc_sheet()
        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                               "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(return_value=2)

        async def run_once():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("business_core.sheets.get_business_sheet", return_value=sheet))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=None))
                return await th.uploaddoc_confirm(update, context)

        first_result = asyncio.run(run_once())
        self.assertEqual(first_result, ConversationHandler.END)
        self.assertEqual(upload_mock.call_count, 1)
        self.assertEqual(append_mock.call_count, 1)

        # Second tap: snapshot already popped -> safe no-op, no re-download/upload/write.
        second_result = asyncio.run(th.uploaddoc_confirm(update, context))
        self.assertEqual(second_result, ConversationHandler.END)
        self.assertEqual(upload_mock.call_count, 1)
        self.assertEqual(append_mock.call_count, 1)
        self.assertEqual(context.bot.get_file.call_count, 1)


class TestUploadDocCancel(unittest.TestCase):
    def test_cancel_clears_state(self):
        th = _fresh_th()
        update, context = _text_update("/cancel"), _ctx(
            user_data={"ud": _ud_draft(), "ud_confirmed_snapshot": _confirmed_snapshot()}
        )
        result = asyncio.run(th.uploaddoc_cancel(update, context))
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud", context.user_data)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)


# ────────────────────────────────────────────────────────────
# Folder resolution unit tests (document_registry_manager)
# ────────────────────────────────────────────────────────────

class TestResolveTargetDriveFolder(unittest.TestCase):
    def test_object_priority(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001", client_id="PRS-001", object_id="OBJ-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "object")
        self.assertEqual(result["folder_id"], "OBJFOLDER1")

    def test_client_priority_without_object(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect), \
             patch("business_core.person_manager.find_person_by_id",
                   return_value={"drive_folder_id": "PRSFOLDER1"}):
            result = drm.resolve_target_drive_folder("BIZ-001", client_id="PRS-001")
        self.assertEqual(result["level"], "client")
        self.assertEqual(result["folder_id"], "PRSFOLDER1")

    def test_business_priority_without_object_or_client(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001")
        self.assertEqual(result["level"], "business")
        self.assertEqual(result["folder_id"], "BIZFOLDER1")

    def test_stage_id_argument_never_used_for_folder_selection(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001", stage_id="STAGE-001")
        self.assertEqual(result["level"], "business")

    def test_no_folder_anywhere_fails(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
             patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-002")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


# ────────────────────────────────────────────────────────────
# Phase 16C.8.2B: /uploaddoc prefilled args contract
# ────────────────────────────────────────────────────────────

def _entry_update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock(username="dida", id=123)
    return update


def _entry_ctx(args):
    context = MagicMock()
    context.user_data = {}
    context.args = args
    return context


class TestUploadDocPrefillEntry(unittest.TestCase):
    """uploaddoc_start with optional prefill args (business=/roadmap=/
    stage=/template=) — entry-time parse/validate only, 0 reads/writes."""

    def _run(self, args, user_data=None):
        th = _fresh_th()
        update = _entry_update()
        context = _entry_ctx(args)
        if user_data is not None:
            context.user_data = user_data

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_no_args_keeps_current_behavior(self):
        th, update, context, result = self._run([])
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud_prefill", context.user_data)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("Отправь один документ", text)

    def test_no_args_clears_stale_ud_prefill(self):
        th, update, context, result = self._run([], user_data={"ud_prefill": {"business": "OLD"}})
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_valid_four_key_args_enters_ud_file(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-IZH-KP-001"],
        )
        self.assertEqual(result, th.UD_FILE)

    def test_exact_prefill_stored(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-IZH-KP-001"],
        )
        self.assertEqual(context.user_data["ud_prefill"], {
            "business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-IZH-KP-001",
        })

    def test_order_of_args_does_not_matter(self):
        th, update, context, result = self._run(
            ["template=DOC-IZH-KP-001", "business=BIZ-001", "stage=STAGE-001", "roadmap=RM-001"],
        )
        self.assertEqual(context.user_data["ud_prefill"]["business"], "BIZ-001")
        self.assertEqual(context.user_data["ud_prefill"]["template"], "DOC-IZH-KP-001")

    def test_quoted_values_handled(self):
        th, update, context, result = self._run(
            ['business="BIZ-001"', "roadmap=RM-001", "stage=STAGE-001", "template=DOC-IZH-KP-001"],
        )
        self.assertEqual(context.user_data["ud_prefill"]["business"], "BIZ-001")

    def test_partial_prefill_ends_conversation(self):
        th, update, context, result = self._run(["business=BIZ-001", "roadmap=RM-001"])
        self.assertEqual(result, ConversationHandler.END)

    def test_missing_key_list_deterministic(self):
        th, update, context, result = self._run(["business=BIZ-001", "roadmap=RM-001"])
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("stage", text)
        self.assertIn("template", text)

    def test_unknown_key_ends_conversation(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "foo=bar"],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_client_rejected_at_entry(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "client=PRS-001"],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_object_rejected_at_entry(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "object=OBJ-001"],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_name_rejected_at_entry(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", 'name="Doc"'],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_notes_rejected_at_entry(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", 'notes="x"'],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_duplicate_key_rejected(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "business=BIZ-002", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1"],
        )
        self.assertEqual(result, ConversationHandler.END)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("business", text)

    def test_malformed_token_rejected(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "garbage"],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_empty_value_rejected(self):
        th, update, context, result = self._run(
            ["business=", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1"],
        )
        self.assertEqual(result, ConversationHandler.END)

    def test_failure_leaves_no_upload_state(self):
        th, update, context, result = self._run(["business=BIZ-001", "roadmap=RM-001"])
        self.assertNotIn("ud", context.user_data)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_entry_does_zero_reads(self):
        with patch("business_core.sheets.read_business_sheet") as mock_read:
            th, update, context, result = self._run(
                ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1"],
            )
        mock_read.assert_not_called()

    def test_entry_does_zero_writes(self):
        import inspect
        th = _fresh_th()
        source = inspect.getsource(th.uploaddoc_start)
        for forbidden in ("upload_file", "create_document", "register_document", "append_business_row"):
            self.assertNotIn(forbidden, source)

    def test_raw_input_not_echoed_unknown_key(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "SECRETVALUE=leak"],
        )
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("leak", text)


class TestUploadDocRequirementEntry(unittest.TestCase):
    """Phase 16C.8.3A: optional requirement= prefill arg — opaque,
    UX-navigation-only, never required alone, never parsed."""

    def _run(self, args, user_data=None):
        th = _fresh_th()
        update = _entry_update()
        context = _entry_ctx(args)
        if user_data is not None:
            context.user_data = user_data

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_four_keys_plus_requirement_valid(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001",
            "template=DOC-IZH-KP-001", "requirement=STAGE-001:DOC-IZH-KP-001",
        ])
        self.assertEqual(result, th.UD_FILE)

    def test_exact_opaque_requirement_preserved(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001",
            "template=DOC-IZH-KP-001", "requirement=STAGE-001:DOC-IZH-KP-001",
        ])
        self.assertEqual(context.user_data["ud_prefill"]["requirement"], "STAGE-001:DOC-IZH-KP-001")

    def test_requirement_optional_without_breaking_existing(self):
        th, update, context, result = self._run(
            ["business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-IZH-KP-001"],
        )
        self.assertEqual(result, th.UD_FILE)
        self.assertNotIn("requirement", context.user_data["ud_prefill"])

    def test_requirement_alone_rejected(self):
        th, update, context, result = self._run(["requirement=STAGE-001:DOC-IZH-KP-001"])
        self.assertEqual(result, ConversationHandler.END)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("business", text)
        self.assertIn("roadmap", text)
        self.assertIn("stage", text)
        self.assertIn("template", text)

    def test_requirement_plus_partial_context_rejected(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "requirement=STAGE-001:DOC-IZH-KP-001",
        ])
        self.assertEqual(result, ConversationHandler.END)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("stage", text)
        self.assertIn("template", text)

    def test_duplicate_requirement_rejected(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1",
            "requirement=STAGE-001:DOC-1", "requirement=OTHER-VALUE",
        ])
        self.assertEqual(result, ConversationHandler.END)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement", text)

    def test_empty_requirement_rejected(self):
        # A bare trailing `key=` with nothing after it (no quotes) is
        # tokenized as a malformed bare token by the existing parser —
        # the same pre-existing behavior applies to every other key
        # (business=, roadmap=, etc.), not something new here. The
        # "cannot be empty" check is reached via an explicit empty
        # quoted value instead.
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", 'requirement=""',
        ])
        self.assertEqual(result, ConversationHandler.END)
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement", text)
        self.assertIn("пуст", text)

    def test_unknown_keys_still_rejected(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "foo=bar",
        ])
        self.assertEqual(result, ConversationHandler.END)

    def test_allowed_key_message_includes_requirement(self):
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001", "template=DOC-1", "foo=bar",
        ])
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement", text)

    def test_no_parsing_of_opaque_requirement(self):
        """The value has no colon-delimited stage/template shape at
        all — proving it's stored verbatim, never validated/derived."""
        th, update, context, result = self._run([
            "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001",
            "template=DOC-IZH-KP-001", "requirement=OPAQUE-VALUE-NO-DELIMITER",
        ])
        self.assertEqual(result, th.UD_FILE)
        self.assertEqual(context.user_data["ud_prefill"]["requirement"], "OPAQUE-VALUE-NO-DELIMITER")

    def test_zero_entry_reads(self):
        with patch("business_core.sheets.read_business_sheet") as mock_read:
            th, update, context, result = self._run([
                "business=BIZ-001", "roadmap=RM-001", "stage=STAGE-001",
                "template=DOC-1", "requirement=STAGE-001:DOC-1",
            ])
        mock_read.assert_not_called()

    def test_zero_entry_writes(self):
        import inspect
        th = _fresh_th()
        source = inspect.getsource(th.uploaddoc_start)
        for forbidden in ("upload_file", "create_document", "register_document", "append_business_row"):
            self.assertNotIn(forbidden, source)


class TestUploadDocPrefillFileStep(unittest.TestCase):
    """uploaddoc_receive_file behavior when ud_prefill is active."""

    def test_valid_document_preserves_prefill(self):
        th = _fresh_th()
        prefill = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-1"}
        update, context = _doc_update(), _ctx(user_data={"ud_prefill": dict(prefill)})
        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_DETAILS)
        self.assertEqual(context.user_data["ud_prefill"], prefill)

    def test_prefilled_prompt_asks_only_name_notes(self):
        th = _fresh_th()
        prefill = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-1"}
        update, context = _doc_update(), _ctx(user_data={"ud_prefill": prefill})
        asyncio.run(th.uploaddoc_receive_file(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("name=", text)
        self.assertIn("notes=", text)
        self.assertNotIn("business=BIZ-001 name=", text)

    def test_generic_prompt_unchanged_without_prefill(self):
        th = _fresh_th()
        update, context = _doc_update(), _ctx()
        asyncio.run(th.uploaddoc_receive_file(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("business=BIZ-001", text)
        self.assertIn("client=, object=, roadmap=, stage=, template=, notes=", text)

    def test_wrong_content_type_preserves_prefill(self):
        th = _fresh_th()
        prefill = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-1"}
        update, context = _non_doc_update("photo"), _ctx(user_data={"ud_prefill": dict(prefill)})
        result = asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(result, th.UD_FILE)
        self.assertEqual(context.user_data["ud_prefill"], prefill)

    def test_file_metadata_privacy_unchanged(self):
        th = _fresh_th()
        prefill = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-1"}
        update, context = _doc_update(), _ctx(user_data={"ud_prefill": prefill})
        asyncio.run(th.uploaddoc_receive_file(update, context))
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("tgfile123", text)
        self.assertNotIn("uniq123", text)


class TestUploadDocPrefillDetailsStep(unittest.TestCase):
    """uploaddoc_receive_details merge/precedence behavior when
    ud_prefill is active."""

    PREFILL = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-IZH-KP-001"}

    def _run(self, text, prefill=None, ud=None):
        th = _fresh_th()
        user_data = {"ud": ud if ud is not None else _ud_draft()}
        if prefill is not None:
            user_data["ud_prefill"] = dict(prefill)
        update, context = _text_update(text), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                           side_effect=_read_business_sheet_side_effect))
                stack.enter_context(patch("business_core.object_manager.find_object_by_id",
                                           side_effect=_find_object_by_id_side_effect))
                stack.enter_context(patch("business_core.person_manager.find_person_by_id",
                                           return_value={"biz_ids": ["BIZ-001"], "drive_folder_id": "PRSFOLDER1"}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_FOLDER_META))
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_valid_name_accepted(self):
        th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_CONFIRM)

    def test_valid_notes_accepted(self):
        th, update, context, result = self._run(
            'name="Технический паспорт" notes="важно"', prefill=self.PREFILL,
        )
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["notes"], "важно")

    def test_missing_name_remains_ud_details(self):
        th, update, context, result = self._run("notes=x", prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_empty_name_remains_ud_details(self):
        th, update, context, result = self._run('name=""', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_business_key_rejected(self):
        th, update, context, result = self._run('name="Doc" business=BIZ-002', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_roadmap_key_rejected(self):
        th, update, context, result = self._run('name="Doc" roadmap=RM-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_stage_key_rejected(self):
        th, update, context, result = self._run('name="Doc" stage=STAGE-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_template_key_rejected(self):
        th, update, context, result = self._run('name="Doc" template=DOC-IZH-KP-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_same_association_value_rejected(self):
        """Even the SAME value as the prefill must be rejected — the
        field is immutable, resubmission is never a no-op."""
        th, update, context, result = self._run('name="Doc" business=BIZ-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_conflicting_association_value_rejected(self):
        th, update, context, result = self._run('name="Doc" business=BIZ-999', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_client_rejected_in_details(self):
        th, update, context, result = self._run('name="Doc" client=PRS-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_object_rejected_in_details(self):
        th, update, context, result = self._run('name="Doc" object=OBJ-001', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_unknown_key_rejected_in_details(self):
        th, update, context, result = self._run('name="Doc" foo=bar', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_duplicate_name_rejected(self):
        th, update, context, result = self._run('name="A" name="B"', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_malformed_token_rejected_in_details(self):
        th, update, context, result = self._run('name="Doc" garbage', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)

    def test_recoverable_error_retains_ud(self):
        th, update, context, result = self._run('name=""', prefill=self.PREFILL)
        self.assertIn("ud", context.user_data)

    def test_recoverable_error_retains_ud_prefill(self):
        th, update, context, result = self._run('name=""', prefill=self.PREFILL)
        self.assertIn("ud_prefill", context.user_data)
        self.assertEqual(context.user_data["ud_prefill"], self.PREFILL)

    def test_recoverable_error_creates_no_snapshot(self):
        th, update, context, result = self._run('name=""', prefill=self.PREFILL)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_valid_merge_uses_exact_prefill_values(self):
        th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["business_id"], "BIZ-001")
        self.assertEqual(snap["roadmap_id"], "RM-001")
        self.assertEqual(snap["stage_id"], "STAGE-001")
        self.assertEqual(snap["document_template_id"], "DOC-IZH-KP-001")
        self.assertEqual(snap["document_name"], "Технический паспорт")

    def test_resolve_and_validate_links_called(self):
        th = _fresh_th()
        user_data = {"ud": _ud_draft(), "ud_prefill": dict(self.PREFILL)}
        update, context = _text_update('name="Doc"'), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                           side_effect=_read_business_sheet_side_effect))
                stack.enter_context(patch("business_core.object_manager.find_object_by_id",
                                           side_effect=_find_object_by_id_side_effect))
                stack.enter_context(patch("business_core.person_manager.find_person_by_id",
                                           return_value={"biz_ids": ["BIZ-001"], "drive_folder_id": "PRSFOLDER1"}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_FOLDER_META))
                mock_resolve = stack.enter_context(
                    patch("business_core.document_registry_manager.resolve_and_validate_links",
                          wraps=__import__("business_core.document_registry_manager",
                                            fromlist=["resolve_and_validate_links"]).resolve_and_validate_links),
                )
                await th.uploaddoc_receive_details(update, context)
                mock_resolve.assert_called_once()

        asyncio.run(run())

    def test_resolve_target_drive_folder_called(self):
        th = _fresh_th()
        user_data = {"ud": _ud_draft(), "ud_prefill": dict(self.PREFILL)}
        update, context = _text_update('name="Doc"'), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                           side_effect=_read_business_sheet_side_effect))
                stack.enter_context(patch("business_core.object_manager.find_object_by_id",
                                           side_effect=_find_object_by_id_side_effect))
                stack.enter_context(patch("business_core.person_manager.find_person_by_id",
                                           return_value={"biz_ids": ["BIZ-001"], "drive_folder_id": "PRSFOLDER1"}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_FOLDER_META))
                mock_folder = stack.enter_context(
                    patch("business_core.document_registry_manager.resolve_target_drive_folder",
                          wraps=__import__("business_core.document_registry_manager",
                                            fromlist=["resolve_target_drive_folder"]).resolve_target_drive_folder),
                )
                await th.uploaddoc_receive_details(update, context)
                mock_folder.assert_called_once()

        asyncio.run(run())

    def test_inconsistent_ids_use_existing_failure_semantics(self):
        conflicting_template = [{"Document Template ID": "DOC-OTHER-001", "Biz ID": "BIZ-002"}]

        def side_effect(key, *a, **kw):
            if key == "document_template_registry":
                return conflicting_template
            return _read_business_sheet_side_effect(key, *a, **kw)

        th = _fresh_th()
        prefill = {"business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-OTHER-001"}
        user_data = {"ud": _ud_draft(), "ud_prefill": prefill}
        update, context = _text_update('name="Doc"'), _ctx(user_data=user_data)

        async def run():
            with patch("business_core.sheets.read_business_sheet", side_effect=side_effect), \
                 patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect), \
                 patch("business_core.business_builder.get_person_biz_ids", return_value=["BIZ-001"]):
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_snapshot_exact_fields(self):
        """client_id/object_id are passed in as "" (per §8 — the
        prefill flow never accepts them), but the existing
        resolve_and_validate_links() auto-fill chain still derives
        them from the roadmap's own Object ID exactly as it already
        does for the generic flow — this is unchanged existing
        behavior, not something this subphase controls."""
        th, update, context, result = self._run('name="Технический паспорт" notes="заметка"', prefill=self.PREFILL)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["business_id"], "BIZ-001")
        self.assertEqual(snap["object_id"], "OBJ-001")
        self.assertEqual(snap["client_id"], "PRS-001")
        self.assertEqual(snap["roadmap_id"], "RM-001")
        self.assertEqual(snap["stage_id"], "STAGE-001")
        self.assertEqual(snap["document_template_id"], "DOC-IZH-KP-001")
        self.assertEqual(snap["document_name"], "Технический паспорт")
        self.assertEqual(snap["notes"], "заметка")

    def test_requirement_id_absent(self):
        """Phase 16C.8.3A: the snapshot always carries a requirement_id
        key (matching the existing client_id/object_id convention),
        defaulting to "" when no requirement= prefill arg was given —
        never a missing key, never a synthesized/parsed value."""
        th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap.get("requirement_id", ""), "")

    def test_zero_writes_before_confirm(self):
        with patch("integrations.google_drive_adapter.upload_file") as mock_upload, \
             patch("business_core.business_builder.upload_and_register_document") as mock_register:
            th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        mock_upload.assert_not_called()
        mock_register.assert_not_called()


class TestUploadDocRequirementDetailsStep(unittest.TestCase):
    """Phase 16C.8.3A: requirement_id merge/immutability/snapshot
    behavior when ud_prefill carries an optional requirement= arg."""

    PREFILL = {
        "business": "BIZ-001", "roadmap": "RM-001", "stage": "STAGE-001",
        "template": "DOC-IZH-KP-001", "requirement": "STAGE-001:DOC-IZH-KP-001",
    }

    def _run(self, text, prefill=None, ud=None):
        th = _fresh_th()
        user_data = {"ud": ud if ud is not None else _ud_draft()}
        if prefill is not None:
            user_data["ud_prefill"] = dict(prefill)
        update, context = _text_update(text), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch("business_core.sheets.read_business_sheet",
                                           side_effect=_read_business_sheet_side_effect))
                stack.enter_context(patch("business_core.object_manager.find_object_by_id",
                                           side_effect=_find_object_by_id_side_effect))
                stack.enter_context(patch("business_core.person_manager.find_person_by_id",
                                           return_value={"biz_ids": ["BIZ-001"], "drive_folder_id": "PRSFOLDER1"}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_FOLDER_META))
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_valid_file_preserves_requirement(self):
        th = _fresh_th()
        prefill = dict(self.PREFILL)
        update, context = _doc_update(), _ctx(user_data={"ud_prefill": prefill})
        asyncio.run(th.uploaddoc_receive_file(update, context))
        self.assertEqual(context.user_data["ud_prefill"]["requirement"], "STAGE-001:DOC-IZH-KP-001")

    def test_recoverable_details_error_preserves_requirement(self):
        th, update, context, result = self._run('name=""', prefill=self.PREFILL)
        self.assertEqual(result, th.UD_DETAILS)
        self.assertEqual(context.user_data["ud_prefill"]["requirement"], "STAGE-001:DOC-IZH-KP-001")

    def test_requirement_in_details_rejected(self):
        th, update, context, result = self._run(
            'name="Doc" requirement=STAGE-001:DOC-IZH-KP-001', prefill=self.PREFILL,
        )
        self.assertEqual(result, th.UD_DETAILS)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_same_requirement_in_details_rejected(self):
        """Same value as the prefill — still rejected, immutable field
        resubmission is never treated as a no-op."""
        th, update, context, result = self._run(
            'name="Doc" requirement=STAGE-001:DOC-IZH-KP-001', prefill=self.PREFILL,
        )
        self.assertEqual(result, th.UD_DETAILS)

    def test_conflicting_requirement_in_details_rejected(self):
        th, update, context, result = self._run(
            'name="Doc" requirement=OTHER-STAGE:OTHER-DOC', prefill=self.PREFILL,
        )
        self.assertEqual(result, th.UD_DETAILS)
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)

    def test_requirement_rejection_shows_immutable_context_message(self):
        th, update, context, result = self._run(
            'name="Doc" requirement=OTHER-STAGE:OTHER-DOC', prefill=self.PREFILL,
        )
        text = update.message.reply_text.call_args[0][0]
        self.assertIn("уже задан командой /uploaddoc", text)

    def test_snapshot_exact_requirement_id(self):
        th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["requirement_id"], "STAGE-001:DOC-IZH-KP-001")

    def test_requirement_removed_from_ud_prefill_after_snapshot(self):
        th, update, context, result = self._run('name="Технический паспорт"', prefill=self.PREFILL)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_requirement_value_never_parsed(self):
        """An opaque value with no colon-delimited stage/template
        shape at all — proving it flows through as an opaque string,
        never split or reconstructed."""
        prefill = dict(self.PREFILL)
        prefill["requirement"] = "OPAQUE-NO-DELIMITER-VALUE"
        th, update, context, result = self._run('name="Технический паспорт"', prefill=prefill)
        snap = context.user_data["ud_confirmed_snapshot"]
        self.assertEqual(snap["requirement_id"], "OPAQUE-NO-DELIMITER-VALUE")
        self.assertEqual(snap["stage_id"], "STAGE-001")
        self.assertEqual(snap["document_template_id"], "DOC-IZH-KP-001")


class TestUploadDocRequirementPersistenceBoundary(unittest.TestCase):
    """Phase 16C.8.3A: requirement_id must never reach persistence,
    the registry row, or analysis input."""

    def _run_confirm_with_requirement(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-IZH-KP-001")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(return_value=2)
        found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        register_mock = MagicMock(wraps=None)

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file",
                                           return_value={"ok": True, "error": ""}))
                stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                           return_value=_make_doc_sheet()))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                register_spy = stack.enter_context(patch(
                    "business_core.business_builder.upload_and_register_document",
                    wraps=__import__("business_core.business_builder", fromlist=["upload_and_register_document"])
                    .upload_and_register_document,
                ))
                enqueue_spy = stack.enter_context(patch("business_core.telegram_handlers._enqueue_document_analysis"))
                result = await th.uploaddoc_confirm(update, context)
                return result, register_spy, enqueue_spy, append_mock

        result, register_spy, enqueue_spy, append_mock = asyncio.run(run())
        return th, update, context, result, register_spy, enqueue_spy, append_mock

    def test_upload_and_register_document_receives_no_requirement_id(self):
        th, update, context, result, register_spy, enqueue_spy, append_mock = self._run_confirm_with_requirement()
        register_spy.assert_called_once()
        _, kwargs = register_spy.call_args
        self.assertNotIn("requirement_id", kwargs)

    def test_no_snap_passthrough(self):
        import inspect
        th = _fresh_th()
        source = inspect.getsource(th.uploaddoc_confirm)
        self.assertNotIn("**snap", source)

    def test_registry_row_unchanged_no_requirement_field(self):
        th, update, context, result, register_spy, enqueue_spy, append_mock = self._run_confirm_with_requirement()
        row = append_mock.call_args[0][1]
        self.assertEqual(len(row), len(DOC_HEADERS))
        self.assertNotIn("Requirement ID", DOC_HEADERS)

    def test_analysis_enqueue_args_contain_no_requirement_id(self):
        th, update, context, result, register_spy, enqueue_spy, append_mock = self._run_confirm_with_requirement()
        enqueue_spy.assert_called_once()
        args, kwargs = enqueue_spy.call_args
        self.assertNotIn("STAGE-001:DOC-IZH-KP-001", args)
        self.assertNotIn("requirement_id", kwargs)

    def test_post_write_verification_unchanged(self):
        th, update, context, result, register_spy, enqueue_spy, append_mock = self._run_confirm_with_requirement()
        self.assertEqual(result, ConversationHandler.END)

    def test_zero_new_persistence_writes(self):
        th, update, context, result, register_spy, enqueue_spy, append_mock = self._run_confirm_with_requirement()
        append_mock.assert_called_once()


class TestUploadDocRequirementSuccessUX(unittest.TestCase):
    """Phase 16C.8.3A: success-message navigation — requirement_id and
    roadmap_id present/absent combinations, exactly one reply_text
    call, failure paths show no navigation."""

    def _run_confirm(self, requirement_id="", roadmap_id="RM-001"):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id=requirement_id, roadmap_id=roadmap_id)
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(return_value=2)
        found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", roadmap_id, "",
            "", snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": roadmap_id, "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file",
                                           return_value={"ok": True, "error": ""}))
                stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                           return_value=_make_doc_sheet()))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                stack.enter_context(patch("business_core.telegram_handlers._enqueue_document_analysis"))
                return await th.uploaddoc_confirm(update, context)

        result = asyncio.run(run())
        return th, update, context, result

    def test_requirement_present_shows_exact_docgap(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("/docgap roadmap_id=RM-001 requirement_id=STAGE-001:DOC-IZH-KP-001", reply)

    def test_requirement_present_shows_missingdocs(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("/missingdocs roadmap_id=RM-001", reply)

    def test_requirement_absent_roadmap_present_no_docgap(self):
        th, update, context, result = self._run_confirm(requirement_id="")
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("/docgap", reply)

    def test_requirement_absent_roadmap_present_shows_missingdocs(self):
        th, update, context, result = self._run_confirm(requirement_id="")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("/missingdocs roadmap_id=RM-001", reply)

    def test_roadmap_absent_no_navigation_at_all(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001", roadmap_id="")
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("/docgap", reply)
        self.assertNotIn("/missingdocs", reply)

    def test_docgap_exactly_once(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertEqual(reply.count("/docgap"), 1)

    def test_missingdocs_exactly_once(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertEqual(reply.count("/missingdocs"), 1)

    def test_exact_roadmap_id(self):
        th, update, context, result = self._run_confirm(
            requirement_id="STAGE-001:DOC-IZH-KP-001", roadmap_id="RM-777",
        )
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("roadmap_id=RM-777", reply)

    def test_exact_opaque_requirement_id(self):
        th, update, context, result = self._run_confirm(requirement_id="OPAQUE-NO-DELIMITER")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("requirement_id=OPAQUE-NO-DELIMITER", reply)

    def test_commands_remain_one_line(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        docgap_lines = [l for l in reply.splitlines() if l.strip().startswith("/docgap")]
        missingdocs_lines = [l for l in reply.splitlines() if l.strip().startswith("/missingdocs")]
        self.assertEqual(len(docgap_lines), 1)
        self.assertEqual(len(missingdocs_lines), 1)

    def test_no_partial_command(self):
        th, update, context, result = self._run_confirm(requirement_id="", roadmap_id="")
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("roadmap_id=", reply)
        self.assertNotIn("requirement_id=", reply)

    def test_existing_creation_message_fields_unchanged(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Документ загружен и зарегистрирован", reply)
        self.assertIn("Document ID:", reply)

    def test_exactly_one_reply_text_on_success(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        self.assertEqual(update.message.reply_text.call_count, 1)

    def test_navigation_appended_to_same_reply(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        self.assertEqual(update.message.reply_text.call_count, 1)
        reply = update.message.reply_text.call_args[0][0]
        self.assertIn("✅ Документ загружен и зарегистрирован", reply)
        self.assertIn("/docgap", reply)

    def test_enqueue_called_after_reply(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-IZH-KP-001")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)
        call_order = []
        update.message.reply_text = AsyncMock(side_effect=lambda *a, **kw: call_order.append("reply"))

        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(return_value=2)
        found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file",
                                           return_value={"ok": True, "error": ""}))
                stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                           return_value=_make_doc_sheet()))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))

                def _enqueue_side_effect(*a, **kw):
                    call_order.append("enqueue")

                stack.enter_context(patch("business_core.telegram_handlers._enqueue_document_analysis",
                                           side_effect=_enqueue_side_effect))
                return await th.uploaddoc_confirm(update, context)

        asyncio.run(run())
        self.assertEqual(call_order, ["reply", "enqueue"])

    def test_enqueue_count_unchanged(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-IZH-KP-001")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                "filename": "passport.pdf", "dry_run": False})
        append_mock = MagicMock(return_value=2)
        found = (2, dict(zip(DOC_HEADERS, [
            "DREG-001", "DFAM-001", "1", "BIZ-001", "PRS-001", "OBJ-001", "RM-001", "",
            "", snap["document_name"], "uploaded", "NEWFILE1",
            "https://drive.google.com/file/d/NEWFILE1/view", "passport.pdf", "application/pdf",
            "2026-01-01 00:00:00 UTC", "dida", "", "", "", "", "2026-01-01 00:00:00 UTC",
            "2026-01-01 00:00:00 UTC",
        ])))
        enqueue_mock = MagicMock()

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file",
                                           return_value={"ok": True, "error": ""}))
                stack.enter_context(patch("business_core.sheets.get_business_sheet",
                                           return_value=_make_doc_sheet()))
                stack.enter_context(patch("business_core.sheets.append_business_row", append_mock))
                stack.enter_context(patch("business_core.sheets.find_row_by_id", return_value=found))
                stack.enter_context(patch("business_core.telegram_handlers._enqueue_document_analysis",
                                           enqueue_mock))
                return await th.uploaddoc_confirm(update, context)

        result = asyncio.run(run())
        enqueue_mock.assert_called_once()

    def test_failure_path_contains_no_navigation(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-IZH-KP-001")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file",
                                           side_effect=Exception("drive down")))
                return await th.uploaddoc_confirm(update, context)

        asyncio.run(run())
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("/docgap", reply)
        self.assertNotIn("/missingdocs", reply)

    def test_privacy_no_new_exposure(self):
        th, update, context, result = self._run_confirm(requirement_id="STAGE-001:DOC-IZH-KP-001")
        reply = update.message.reply_text.call_args[0][0]
        self.assertNotIn("tgfile123", reply)
        self.assertNotIn("uniq123", reply)
        self.assertNotIn("OBJFOLDER1", reply)


class TestUploadDocPrefillCleanup(unittest.TestCase):
    """ud_prefill lifecycle across every terminal path."""

    def test_cancel_command_clears_ud_prefill(self):
        th = _fresh_th()
        update, context = _text_update("/cancel"), _ctx(
            user_data={"ud": _ud_draft(), "ud_prefill": {"business": "BIZ-001"}},
        )
        asyncio.run(th.uploaddoc_cancel(update, context))
        self.assertNotIn("ud_prefill", context.user_data)

    def test_confirm_cancel_button_clears_ud_prefill(self):
        th = _fresh_th()
        update = _text_update("❌ Отмена")
        context = _ctx(user_data={
            "ud_confirmed_snapshot": _confirmed_snapshot(), "ud_prefill": {"business": "BIZ-001"},
        })
        asyncio.run(th.uploaddoc_confirm(update, context))
        self.assertNotIn("ud_prefill", context.user_data)

    def test_successful_completion_clears_ud_prefill(self):
        th, update, context, result = TestUploadDocPrefillDetailsStep()._run(
            'name="Технический паспорт"', prefill=TestUploadDocPrefillDetailsStep.PREFILL,
        )
        # By the time UD_CONFIRM is reached, ud_prefill has already
        # been folded into the snapshot and cleared.
        self.assertNotIn("ud_prefill", context.user_data)

    def test_terminal_details_failure_clears_ud_prefill(self):
        th = _fresh_th()
        prefill = {"business": "BIZ-999", "roadmap": "RM-001", "stage": "STAGE-001", "template": "DOC-1"}
        user_data = {"ud": _ud_draft(), "ud_prefill": prefill}
        update, context = _text_update('name="Doc"'), _ctx(user_data=user_data)

        async def run():
            with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect), \
                 patch("business_core.object_manager.find_object_by_id", side_effect=_find_object_by_id_side_effect):
                return await th.uploaddoc_receive_details(update, context)

        result = asyncio.run(run())
        self.assertEqual(result, ConversationHandler.END)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_reentry_clears_prior_prefill(self):
        th = _fresh_th()
        update = _entry_update()
        context = _entry_ctx([])
        context.user_data = {"ud_prefill": {"business": "STALE"}}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        asyncio.run(run())
        self.assertNotIn("ud_prefill", context.user_data)

    def test_cancel_clears_requirement_context(self):
        """Phase 16C.8.3A: /cancel clears ud_prefill even when it
        carries a requirement= value — no new cleanup key, same
        generic pop already covers it."""
        th = _fresh_th()
        update, context = _text_update("/cancel"), _ctx(
            user_data={"ud": _ud_draft(), "ud_prefill": {"business": "BIZ-001", "requirement": "STAGE-001:DOC-1"}},
        )
        asyncio.run(th.uploaddoc_cancel(update, context))
        self.assertNotIn("ud_prefill", context.user_data)

    def test_reentry_clears_stale_requirement(self):
        th = _fresh_th()
        update = _entry_update()
        context = _entry_ctx([])
        context.user_data = {"ud_prefill": {"business": "STALE", "requirement": "STALE:REQ"}}

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        asyncio.run(run())
        self.assertNotIn("ud_prefill", context.user_data)

    def test_persistence_failure_clears_requirement_context(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-1")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file",
                                           side_effect=Exception("drive down")))
                return await th.uploaddoc_confirm(update, context)

        asyncio.run(run())
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        self.assertNotIn("ud_prefill", context.user_data)

    def test_post_write_verification_failure_clears_requirement_context(self):
        th = _fresh_th()
        snap = _confirmed_snapshot(requirement_id="STAGE-001:DOC-1")
        user_data = {"ud_confirmed_snapshot": snap}
        update, context = _text_update("✅ Подтвердить"), _ctx(user_data=user_data)

        upload_mock = MagicMock(return_value={"file_id": "NEWFILE1", "file_url": "unused",
                                                "filename": "passport.pdf", "dry_run": False})

        async def run():
            with contextlib.ExitStack() as stack:
                for p in _fake_tmp_patches():
                    stack.enter_context(p)
                stack.enter_context(patch(
                    "business_core.document_registry_manager.resolve_and_validate_links",
                    return_value={"ok": True, "resolved": {
                        "business_id": "BIZ-001", "client_id": "PRS-001", "object_id": "OBJ-001",
                        "roadmap_id": "RM-001", "stage_id": "", "document_template_id": "",
                    }}))
                stack.enter_context(patch("integrations.google_drive_adapter.get_drive_service",
                                           return_value=MagicMock()))
                stack.enter_context(patch("integrations.google_drive_adapter.upload_file", upload_mock))
                stack.enter_context(patch("integrations.google_drive_adapter.get_file_metadata",
                                           return_value=GOOD_UPLOAD_META))
                stack.enter_context(patch("integrations.google_drive_adapter.trash_file",
                                           return_value={"ok": True, "error": ""}))
                stack.enter_context(patch(
                    "business_core.business_builder.upload_and_register_document",
                    return_value={"ok": False, "code": "DOCUMENT_POST_WRITE_VERIFICATION_FAILED",
                                   "error": "mismatch", "document_id": "DREG-001"},
                ))
                return await th.uploaddoc_confirm(update, context)

        asyncio.run(run())
        self.assertNotIn("ud_confirmed_snapshot", context.user_data)
        self.assertNotIn("ud_prefill", context.user_data)


class TestUploadDocPrefillPrivacy(unittest.TestCase):
    def test_no_file_id_or_folder_id_in_entry_errors(self):
        th = _fresh_th()
        update = _entry_update()
        context = _entry_ctx(["business=BIZ-001", "roadmap=RM-001"])

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                return await th.uploaddoc_start(update, context)

        asyncio.run(run())
        text = update.message.reply_text.call_args[0][0]
        self.assertNotIn("folder", text.lower())
        self.assertNotIn("drive.google.com", text)


# ────────────────────────────────────────────────────────────
# Regression: existing Phase 15A commands and registration untouched
# ────────────────────────────────────────────────────────────

class TestRegressionExistingCommands(unittest.TestCase):
    def test_registerdoc_doc_docs4stage_still_present(self):
        th = _fresh_th()
        self.assertTrue(hasattr(th, "registerdoc_start"))
        self.assertTrue(hasattr(th, "registerdoc_confirm"))
        self.assertTrue(hasattr(th, "doc_cmd"))
        self.assertTrue(hasattr(th, "docs4stage_cmd"))

    def test_register_business_handlers_runs_without_error(self):
        th = _fresh_th()
        app = MagicMock()
        th.register_business_handlers(app)
        self.assertGreater(app.add_handler.call_count, 20)

    def test_document_registry_headers_unchanged(self):
        from business_core.sheets import BUSINESS_HEADERS
        self.assertEqual(BUSINESS_HEADERS["document_registry"], DOC_HEADERS)

    def test_document_registry_prefix_unchanged(self):
        from business_core.sheets import _ID_PREFIXES
        self.assertEqual(_ID_PREFIXES["document_registry"], "DREG")


if __name__ == "__main__":
    unittest.main()
