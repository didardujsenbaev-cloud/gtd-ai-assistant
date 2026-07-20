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
                stack.enter_context(patch("business_core.business_builder.get_person_biz_ids",
                                           return_value=["BIZ-001"]))
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
        self.assertIn("Document registered, but post-write verification failed.", reply)
        self.assertIn("Manual verification is required.", reply)
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
        self.assertIn("Document registered, but post-write verification failed.", reply)
        self.assertIn("Manual verification is required.", reply)
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
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001", client_id="PRS-001", object_id="OBJ-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "object")
        self.assertEqual(result["folder_id"], "OBJFOLDER1")

    def test_client_priority_without_object(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001", client_id="PRS-001")
        self.assertEqual(result["level"], "client")
        self.assertEqual(result["folder_id"], "PRSFOLDER1")

    def test_business_priority_without_object_or_client(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001")
        self.assertEqual(result["level"], "business")
        self.assertEqual(result["folder_id"], "BIZFOLDER1")

    def test_stage_id_argument_never_used_for_folder_selection(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-001", stage_id="STAGE-001")
        self.assertEqual(result["level"], "business")

    def test_no_folder_anywhere_fails(self):
        drm = _fresh_drm()
        with patch("business_core.sheets.read_business_sheet", side_effect=_read_business_sheet_side_effect):
            result = drm.resolve_target_drive_folder("BIZ-002")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


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
