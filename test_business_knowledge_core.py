"""
Phase 8C tests: SOP / Checklist / Materials Binding.

Covers A–T per spec.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

WORKSPACE = Path(__file__).parent
GTD_FORBIDDEN = {"inbox_processor", "project_planner", "calendar_sync", "telegram_bot"}

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _imports(path: Path) -> list[str]:
    src  = path.read_text(encoding="utf-8")
    tree = ast.parse(src, str(path))
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: mods.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module.split(".")[0])
    return mods


def _ws(rows):
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    ws.update_cell = MagicMock()
    ws.append_row  = MagicMock()
    return ws


SOP_H = ["SOP ID","Biz ID","Service ID","Template ID","Template Stage ID",
         "Title","Purpose","Steps","Expected Result","Owner Role",
         "Drive File ID","Google Drive","Version","Status","Notes",
         "Created At","Last Updated"]

CHK_H = ["Checklist ID","Biz ID","Service ID","Template ID","Template Stage ID",
         "Title","Items","Required Items","Optional Items",
         "Completion Criteria","Owner Role","Drive File ID","Google Drive",
         "Version","Status","Notes","Created At","Last Updated"]

DOC_H = ["Document Template ID","Biz ID","Service ID","Template ID","Template Stage ID",
         "Title","Document Type","Description","Drive File ID","Google Drive",
         "Version","Status","Notes","Created At","Last Updated"]

FAQ_H = ["FAQ ID","Biz ID","Service ID","Template ID","Template Stage ID",
         "Question","Answer","Category","Status","Notes","Created At","Last Updated"]

TSTG_H = ["Stage ID","Template ID","Order","Stage Name","Description",
           "Required Docs","Responsible","Estimated Days","Notes","Created At",
           "SOP IDs","Checklist IDs","Materials IDs","Document Template IDs","FAQ IDs"]


def _sop_sheet(extra=None):   return _ws([SOP_H]  + (extra or []))
def _chk_sheet(extra=None):   return _ws([CHK_H]  + (extra or []))
def _doc_sheet(extra=None):   return _ws([DOC_H]  + (extra or []))
def _faq_sheet(extra=None):   return _ws([FAQ_H]  + (extra or []))
def _tstg_sheet(extra=None):  return _ws([TSTG_H] + (extra or []))


def _tstg_row(sid="TSTG-001", sop="", chk="", mat="", doc="", faq=""):
    r = [""] * len(TSTG_H)
    r[0] = sid
    for col, val in [("SOP IDs", sop), ("Checklist IDs", chk),
                     ("Materials IDs", mat), ("Document Template IDs", doc),
                     ("FAQ IDs", faq)]:
        r[TSTG_H.index(col)] = val
    return r


def _fresh():
    for k in list(sys.modules):
        if "business_core" in k: del sys.modules[k]
    import business_core.knowledge_manager as m
    return m


# ────────────────────────────────────────────────────────────
# A–D: ID generation
# ────────────────────────────────────────────────────────────

class TestIdGeneration(unittest.TestCase):

    def test_A_sop_id_empty(self):
        """A: пустой SOP_REGISTRY → SOP-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet", return_value=_sop_sheet()):
            self.assertEqual(m.generate_sop_id(), "SOP-001")

    def test_B_checklist_id_empty(self):
        """B: пустой CHECKLIST_REGISTRY → CHK-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet", return_value=_chk_sheet()):
            self.assertEqual(m.generate_checklist_id(), "CHK-001")

    def test_C_doc_template_id_empty(self):
        """C: пустой DOCUMENT_TEMPLATE_REGISTRY → DOC-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet", return_value=_doc_sheet()):
            self.assertEqual(m.generate_document_template_id(), "DOC-001")

    def test_D_faq_id_empty(self):
        """D: пустой FAQ_REGISTRY → FAQ-001."""
        m = _fresh()
        with patch("business_core.sheets.get_business_sheet", return_value=_faq_sheet()):
            self.assertEqual(m.generate_faq_id(), "FAQ-001")


# ────────────────────────────────────────────────────────────
# E–H: create_* records
# ────────────────────────────────────────────────────────────

class TestCreateRecords(unittest.TestCase):

    def test_E_create_sop(self):
        """E: create_sop_record создает SOP."""
        m = _fresh()
        appended = []
        with patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appended.append(r)), \
             patch("business_core.sheets.generate_next_id", return_value="SOP-001"):
            result = m.create_sop_record(title="Проверка документов",
                                         steps="1. Шаг; 2. Шаг")
        self.assertTrue(result["ok"])
        self.assertEqual(result["sop_id"], "SOP-001")
        self.assertIn("Проверка документов", appended[0])

    def test_E_create_sop_no_title(self):
        """E: пустой title → error."""
        m = _fresh()
        self.assertFalse(m.create_sop_record(title="")["ok"])

    def test_F_create_checklist(self):
        """F: create_checklist_record создает чек-лист."""
        m = _fresh()
        appended = []
        with patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appended.append(r)), \
             patch("business_core.sheets.generate_next_id", return_value="CHK-001"):
            result = m.create_checklist_record(title="Чек-лист",
                                               items="Удостоверение; Техпаспорт")
        self.assertTrue(result["ok"])
        self.assertEqual(result["checklist_id"], "CHK-001")

    def test_G_create_document_template(self):
        """G: create_document_template_record создает шаблон."""
        m = _fresh()
        appended = []
        with patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appended.append(r)), \
             patch("business_core.sheets.generate_next_id", return_value="DOC-001"):
            result = m.create_document_template_record(
                title="Запрос документов", document_type="message_template")
        self.assertTrue(result["ok"])
        self.assertEqual(result["doc_template_id"], "DOC-001")

    def test_H_create_faq(self):
        """H: create_faq_record создает FAQ."""
        m = _fresh()
        appended = []
        with patch("business_core.sheets.append_business_row",
                   side_effect=lambda k, r: appended.append(r)), \
             patch("business_core.sheets.generate_next_id", return_value="FAQ-001"):
            result = m.create_faq_record(question="Можно без техпаспорта?",
                                         answer="Нет.")
        self.assertTrue(result["ok"])
        self.assertEqual(result["faq_id"], "FAQ-001")

    def test_H_create_faq_no_question(self):
        """H: пустой question → error."""
        m = _fresh()
        self.assertFalse(m.create_faq_record(question="", answer="Ответ")["ok"])


# ────────────────────────────────────────────────────────────
# I–K: link_knowledge_to_template_stage
# ────────────────────────────────────────────────────────────

class TestLinkKnowledge(unittest.TestCase):

    def test_I_writes_sop_ids(self):
        """I: link_knowledge записывает SOP IDs."""
        m = _fresh()
        row = _tstg_row("TSTG-001")
        ws  = _tstg_sheet([row])
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = m.link_knowledge_to_template_stage(
                "TSTG-001", sop_ids=["SOP-001"])
        self.assertTrue(result["ok"])
        ws.update_cell.assert_called()
        vals = [c[0][2] for c in ws.update_cell.call_args_list]
        self.assertIn("SOP-001", vals)

    def test_J_writes_checklist_ids(self):
        """J: link_knowledge записывает Checklist IDs."""
        m = _fresh()
        row = _tstg_row("TSTG-001")
        ws  = _tstg_sheet([row])
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = m.link_knowledge_to_template_stage(
                "TSTG-001", checklist_ids=["CHK-001"])
        self.assertTrue(result["ok"])
        vals = [c[0][2] for c in ws.update_cell.call_args_list]
        self.assertIn("CHK-001", vals)

    def test_K_no_duplicates(self):
        """K: link_knowledge не создает дубли ID."""
        m = _fresh()
        row = _tstg_row("TSTG-001", sop="SOP-001")
        ws  = _tstg_sheet([row])
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            m.link_knowledge_to_template_stage("TSTG-001", sop_ids=["SOP-001"])
        # SOP-001 уже есть → update_cell не должен вызываться
        ws.update_cell.assert_not_called()

    def test_K_adds_new_without_duplicate(self):
        """K: добавляет новый ID без дублирования существующего."""
        m = _fresh()
        row = _tstg_row("TSTG-001", sop="SOP-001")
        ws  = _tstg_sheet([row])
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            m.link_knowledge_to_template_stage("TSTG-001", sop_ids=["SOP-001", "SOP-002"])
        ws.update_cell.assert_called_once()
        written = ws.update_cell.call_args[0][2]
        self.assertIn("SOP-001", written)
        self.assertIn("SOP-002", written)
        self.assertEqual(written.count("SOP-001"), 1)

    def test_K_empty_template_stage_id_returns_error(self):
        """K: пустой template_stage_id → error."""
        m = _fresh()
        result = m.link_knowledge_to_template_stage("", sop_ids=["SOP-001"])
        self.assertFalse(result["ok"])


# ────────────────────────────────────────────────────────────
# L: find_knowledge_by_template_stage
# ────────────────────────────────────────────────────────────

class TestFindKnowledge(unittest.TestCase):

    def test_L_returns_linked_ids(self):
        """L: find_knowledge_by_template_stage возвращает привязанные материалы."""
        m = _fresh()
        row = _tstg_row("TSTG-001", sop="SOP-001,SOP-002",
                        chk="CHK-001", faq="FAQ-001")
        ws  = _tstg_sheet([row])
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = m.find_knowledge_by_template_stage("TSTG-001")
        self.assertEqual(result["sop_ids"],      ["SOP-001", "SOP-002"])
        self.assertEqual(result["checklist_ids"],["CHK-001"])
        self.assertEqual(result["faq_ids"],      ["FAQ-001"])

    def test_L_empty_stage_returns_empty(self):
        """L: пустой stage → пустой dict."""
        m = _fresh()
        result = m.find_knowledge_by_template_stage("")
        self.assertEqual(result["sop_ids"], [])

    def test_L_unknown_stage_returns_empty(self):
        """L: неизвестный stage → пустой dict."""
        m = _fresh()
        ws = _tstg_sheet()
        with patch("business_core.sheets.get_business_sheet", return_value=ws):
            result = m.find_knowledge_by_template_stage("TSTG-999")
        self.assertEqual(result["sop_ids"], [])


# ────────────────────────────────────────────────────────────
# M–R: Telegram commands
# ────────────────────────────────────────────────────────────

class TestKnowledgeCommands(unittest.TestCase):

    def _setup(self):
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]

    def _update(self, args_str=""):
        update  = MagicMock()
        context = MagicMock()
        context.args = args_str.split() if args_str else []
        update.message.reply_text = AsyncMock()
        update.effective_chat.id  = 123
        return update, context

    def test_M_newsop_creates(self):
        """M: /newsop создает SOP."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newsop_cmd
        update, context = self._update('title=Проверка')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_sop_record",
                       return_value={"ok": True, "sop_id": "SOP-001", "error": None}):
                await newsop_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("SOP-001", msg)
        asyncio.run(run())

    def test_M_newsop_no_title(self):
        """M: /newsop без title → error."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newsop_cmd
        update, context = self._update()
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await newsop_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_newsop_expected_result_forwarded(self):
        """п.22: expected_result= передаётся в create_sop_record."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newsop_cmd
        update, context = self._update('title=Проверка expected_result="Документы проверены"')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_sop_record",
                       return_value={"ok": True, "sop_id": "SOP-001", "error": None}) as mock_create:
                await newsop_cmd(update, context)
            _, kwargs = mock_create.call_args
            self.assertEqual(kwargs.get("expected_result"), "Документы проверены")
        asyncio.run(run())

    def test_newsop_result_short_form_backward_compatible(self):
        """п.23: result= продолжает работать как алиас."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newsop_cmd
        update, context = self._update('title=Проверка result="Старый синтаксис"')

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_sop_record",
                       return_value={"ok": True, "sop_id": "SOP-001", "error": None}) as mock_create:
                await newsop_cmd(update, context)
            _, kwargs = mock_create.call_args
            self.assertEqual(kwargs.get("expected_result"), "Старый синтаксис")
        asyncio.run(run())

    def test_newsop_expected_result_takes_priority_over_result(self):
        """п.24: expected_result= побеждает result=, если переданы оба."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newsop_cmd
        update, context = self._update(
            'title=Проверка expected_result="Новый" result="Старый"'
        )

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_sop_record",
                       return_value={"ok": True, "sop_id": "SOP-001", "error": None}) as mock_create:
                await newsop_cmd(update, context)
            _, kwargs = mock_create.call_args
            self.assertEqual(kwargs.get("expected_result"), "Новый")
        asyncio.run(run())

    def test_sop_sop_id_shows_full_steps_no_truncation(self):
        """п.25: /sop sop_id=... показывает Steps полностью, без обрезки [:100]."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import sop_cmd
        long_steps = "1. Шаг один. " * 20  # заведомо длиннее 100 символов
        fake_sop = {
            "SOP ID": "SOP-001", "Title": "Проверка документов",
            "Purpose": "Убедиться в комплектности", "Steps": long_steps,
            "Expected Result": "Документы проверены", "Owner Role": "Юрист",
            "Version": "1.0", "Status": "active", "Notes": "",
            "Google Drive": "", "Drive File ID": "",
        }
        update, context = self._update("sop_id=SOP-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.find_sop_by_id", return_value=fake_sop):
                await sop_cmd(update, context)
            sent_texts = [c.args[0] for c in update.message.reply_text.call_args_list]
            self.assertTrue(any(long_steps in t for t in sent_texts))
        asyncio.run(run())

    def test_sop_long_message_splits_without_losing_text(self):
        """п.26: длинный SOP разбивается на несколько сообщений без потери текста."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import sop_cmd
        very_long_steps = "Шаг номер {}. ".format("X") * 2000
        fake_sop = {
            "SOP ID": "SOP-001", "Title": "Длинный SOP",
            "Purpose": "", "Steps": very_long_steps,
            "Expected Result": "", "Owner Role": "", "Version": "1.0",
            "Status": "active", "Notes": "", "Google Drive": "", "Drive File ID": "",
        }
        update, context = self._update("sop_id=SOP-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.find_sop_by_id", return_value=fake_sop):
                await sop_cmd(update, context)
            sent_texts = [c.args[0] for c in update.message.reply_text.call_args_list]
            self.assertGreater(len(sent_texts), 1)
            self.assertIn(very_long_steps, "".join(sent_texts))
        asyncio.run(run())

    def test_sop_markdown_characters_do_not_corrupt_output(self):
        """п.27: символы Markdown в Title/Steps не ломают вывод — parse_mode=None."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import sop_cmd
        fake_sop = {
            "SOP ID": "SOP-001", "Title": "Проверка_документов *важно*",
            "Purpose": "", "Steps": "1. Шаг_один; 2. Шаг_два *срочно*",
            "Expected Result": "", "Owner Role": "", "Version": "1.0",
            "Status": "active", "Notes": "", "Google Drive": "", "Drive File ID": "",
        }
        update, context = self._update("sop_id=SOP-001")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.find_sop_by_id", return_value=fake_sop):
                await sop_cmd(update, context)
            for call in update.message.reply_text.call_args_list:
                self.assertIsNone(call.kwargs.get("parse_mode"))
            sent_texts = [c.args[0] for c in update.message.reply_text.call_args_list]
            self.assertTrue(any("Проверка_документов *важно*" in t for t in sent_texts))
        asyncio.run(run())

    def test_sop_stage_id_shows_all_linked_sops(self):
        """п.28: /sop stage_id=... показывает все привязанные SOP по порядку."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import sop_cmd
        relations = (
            {"Relation ID": "REL-1", "Stage ID": "STAGE-013", "Entity Type": "sop",
             "Entity ID": "SOP-001", "Status": "active"},
            {"Relation ID": "REL-2", "Stage ID": "STAGE-013", "Entity Type": "sop",
             "Entity ID": "SOP-002", "Status": "active"},
        )
        sop_1 = {"SOP ID": "SOP-001", "Title": "Первый SOP", "Purpose": "", "Steps": "шаги 1",
                 "Expected Result": "", "Owner Role": "", "Version": "1.0", "Status": "active",
                 "Notes": "", "Google Drive": "", "Drive File ID": ""}
        sop_2 = {"SOP ID": "SOP-002", "Title": "Второй SOP", "Purpose": "", "Steps": "шаги 2",
                 "Expected Result": "", "Owner Role": "", "Version": "1.0", "Status": "active",
                 "Notes": "", "Google Drive": "", "Drive File ID": ""}
        update, context = self._update("stage_id=STAGE-013")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=relations), \
                 patch("business_core.knowledge_manager.find_sop_by_id",
                       side_effect=lambda sid: {"SOP-001": sop_1, "SOP-002": sop_2}[sid]):
                await sop_cmd(update, context)
            sent_texts = [c.args[0] for c in update.message.reply_text.call_args_list]
            combined = "".join(sent_texts)
            self.assertIn("Первый SOP", combined)
            self.assertIn("Второй SOP", combined)
            self.assertLess(combined.index("Первый SOP"), combined.index("Второй SOP"))
        asyncio.run(run())

    def test_sop_stage_without_sop_returns_clear_message(self):
        """п.29: этап без привязанных SOP возвращает понятное сообщение, а не ошибку/пусто."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import sop_cmd
        update, context = self._update("stage_id=STAGE-013")

        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.stage_entity_relations.get_relations_for_stage", return_value=()), \
                 patch("business_core.knowledge_manager.get_knowledge_for_stage",
                       return_value={"sop_ids": []}):
                await sop_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("STAGE-013", msg)
            self.assertIn("нет привязанных SOP", msg)
        asyncio.run(run())

    def test_N_newchecklist_creates(self):
        """N: /newchecklist создает чек-лист."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update('title=Чеклист')
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}):
                await newchecklist_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("CHK-001", msg)
        asyncio.run(run())

    def test_N_newchecklist_required_items_optional_items_forwarded(self):
        """N (fix): required_items=/optional_items= (the documented,
        schema-matching long form) must reach create_checklist_record()
        with their exact non-empty values — this is the live-production
        bug (CHK-003) this fix addresses."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update(
            'title=Тест items="A; B; C" required_items="A; B" optional_items="C"'
        )
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}) as mock_create:
                await newchecklist_cmd(update, context)
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["required_items"], "A; B")
            self.assertEqual(kwargs["optional_items"], "C")
        asyncio.run(run())

    def test_N_newchecklist_short_form_backward_compatible(self):
        """N (fix): the short required=/optional= aliases must keep
        working exactly as before, for backward compatibility."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update(
            'title=Тест items="A; B; C" required="A; B" optional="C"'
        )
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}) as mock_create:
                await newchecklist_cmd(update, context)
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["required_items"], "A; B")
            self.assertEqual(kwargs["optional_items"], "C")
        asyncio.run(run())

    def test_N_newchecklist_required_items_takes_priority_over_required(self):
        """N (fix): when BOTH the long and short form are passed at
        once, the long (documented) form wins."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update(
            'title=Тест items="A; B" required_items="NEW" required="OLD"'
        )
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}) as mock_create:
                await newchecklist_cmd(update, context)
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["required_items"], "NEW")
        asyncio.run(run())

    def test_N_newchecklist_optional_items_takes_priority_over_optional(self):
        """N (fix): same priority rule, for optional_items= vs optional=."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update(
            'title=Тест items="A; B" optional_items="NEW" optional="OLD"'
        )
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}) as mock_create:
                await newchecklist_cmd(update, context)
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["optional_items"], "NEW")
        asyncio.run(run())

    def test_N_newchecklist_items_only_unchanged_safe_default(self):
        """N (fix): items= without any required/optional classification
        must behave exactly as before — both forwarded as empty strings,
        letting parse_checklist_template_items()'s existing
        "unclassified defaults to required" policy apply unchanged."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newchecklist_cmd
        update, context = self._update('title=Тест items="A; B; C"')
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_checklist_record",
                       return_value={"ok": True, "checklist_id": "CHK-001", "error": None}) as mock_create:
                await newchecklist_cmd(update, context)
            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["required_items"], "")
            self.assertEqual(kwargs["optional_items"], "")
        asyncio.run(run())

    def test_N_newchecklist_docstring_documents_required_items_optional_items(self):
        """N (fix): the documented/primary syntax shown to a reader of
        the command's own docstring must use required_items=/optional_items=
        (matching checklist_registry's own column names), not just the
        short required=/optional= aliases."""
        from business_core.telegram_handlers import newchecklist_cmd
        doc = newchecklist_cmd.__doc__ or ""
        self.assertIn("required_items=", doc)
        self.assertIn("optional_items=", doc)

    def test_O_newdoctemplate_creates(self):
        """O: /newdoctemplate создает шаблон документа."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newdoctemplate_cmd
        update, context = self._update('title=Запрос')
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_document_template_record",
                       return_value={"ok": True, "doc_template_id": "DOC-001", "error": None}):
                await newdoctemplate_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("DOC-001", msg)
        asyncio.run(run())

    def test_P_newfaq_creates(self):
        """P: /newfaq создает FAQ."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import newfaq_cmd
        update, context = self._update('question=Вопрос answer=Ответ')
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.create_faq_record",
                       return_value={"ok": True, "faq_id": "FAQ-001", "error": None}):
                await newfaq_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("FAQ-001", msg)
        asyncio.run(run())

    def test_Q_linkknowledge_links(self):
        """Q: /linkknowledge связывает knowledge с этапом."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import linkknowledge_cmd
        update, context = self._update('template_stage_id=TSTG-001 sop_ids=SOP-001')
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.link_knowledge_to_template_stage",
                       return_value={"ok": True, "updated": True, "error": None}):
                await linkknowledge_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("✅", msg)
        asyncio.run(run())

    def test_Q_linkknowledge_no_stage_id(self):
        """Q: /linkknowledge без stage_id → error."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import linkknowledge_cmd
        update, context = self._update()
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True):
                await linkknowledge_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("❌", msg)
        asyncio.run(run())

    def test_R_stageknowledge_shows(self):
        """R: /stageknowledge показывает knowledge по этапу."""
        import asyncio
        self._setup()
        from business_core.telegram_handlers import stageknowledge_cmd
        update, context = self._update('template_stage_id=TSTG-001')
        knowledge = {
            "sop_ids": ["SOP-001"], "checklist_ids": [],
            "material_ids": [], "document_template_ids": [], "faq_ids": [],
        }
        sop_data = {"SOP ID": "SOP-001", "Title": "Проверка документов",
                    "Steps": "1. Шаг", "Purpose": ""}
        async def run():
            with patch("business_core.telegram_handlers._is_bc_enabled", return_value=True), \
                 patch("business_core.knowledge_manager.find_knowledge_by_template_stage",
                       return_value=knowledge), \
                 patch("business_core.knowledge_manager.get_knowledge_for_stage",
                       return_value=knowledge), \
                 patch("business_core.knowledge_manager.find_sop_by_id",
                       return_value=sop_data), \
                 patch("business_core.knowledge_manager.find_checklist_by_id",
                       return_value=None), \
                 patch("business_core.knowledge_manager.find_document_template_by_id",
                       return_value=None), \
                 patch("business_core.knowledge_manager.find_faq_by_id",
                       return_value=None):
                await stageknowledge_cmd(update, context)
            msg = update.message.reply_text.call_args[0][0]
            self.assertIn("TSTG-001", msg)
            self.assertIn("Проверка документов", msg)
        asyncio.run(run())


# ────────────────────────────────────────────────────────────
# S: /startroadmap copies knowledge IDs
# ────────────────────────────────────────────────────────────

class TestStartRoadmapCopiesKnowledge(unittest.TestCase):
    """
    Phase 28E/28F: find_template_stages() itself now reads each template
    stage's own knowledge-ID columns directly (no more Core -> Extension
    knowledge_manager.find_knowledge_by_template_stage() call from
    roadmap_template_manager) — so create_stages_from_template_record()
    (via roadmap_manager.ensure_roadmap_stages()) merges whatever
    sop_ids/checklist_ids/etc. keys are already present on the
    template_stage_rows it's given, rather than fetching them
    separately. These tests now mock find_template_stages() to return
    rows WITH those keys already populated, matching find_template_stages()'s
    actual post-Phase-28E return shape.

    Closeout Remediation (finding #2): create_stages_from_template_record()
    itself moved to business_core.business_builder (to break a
    roadmap_manager <-> roadmap_template_manager circular import) — these
    tests still patch find_template_stages on the roadmap_template_manager
    module object (rtm), since business_builder's lazy import resolves it
    from there at call time, but now call business_builder's function.
    """

    def test_S_knowledge_ids_copied_to_real_stages(self):
        """S: create_stages_from_template_record копирует knowledge IDs."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        import business_core.roadmap_template_manager as rtm
        import business_core.business_builder as bb

        template_stages = [
            {"stage_id": "TSTG-001", "template_id": "RTMPL-001", "order": "1",
             "stage_name": "Анализ", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": "",
             "sop_ids": ["SOP-001"], "checklist_ids": ["CHK-001"],
             "material_ids": [], "document_template_ids": ["DOC-001"], "faq_ids": []},
        ]
        appended = []
        rm_stage_headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
            "SOP IDs", "Checklist IDs", "Materials IDs",
            "Document Template IDs", "FAQ IDs",
        ]
        sheet = MagicMock()
        sheet.row_values.return_value = rm_stage_headers
        sheet.get_all_values.return_value = [rm_stage_headers]

        with patch.object(rtm, "find_template_stages", return_value=template_stages), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows",
                   side_effect=lambda k, rows: appended.extend(rows)), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-001"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 1)
        row = appended[0]
        self.assertIn("SOP-001",  row)
        self.assertIn("CHK-001",  row)
        self.assertIn("DOC-001",  row)

    def test_S_no_knowledge_does_not_crash(self):
        """S: если knowledge нет — не падать."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        import business_core.roadmap_template_manager as rtm
        import business_core.business_builder as bb

        template_stages = [
            {"stage_id": "TSTG-002", "template_id": "RTMPL-001", "order": "1",
             "stage_name": "Этап без knowledge", "description": "", "required_docs": "",
             "responsible": "", "estimated_days": "", "notes": "",
             "sop_ids": [], "checklist_ids": [], "material_ids": [],
             "document_template_ids": [], "faq_ids": []},
        ]
        rm_stage_headers = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "GTD Action ID",
            "Responsible", "Docs Required", "Docs Received", "Notes",
            "SOP IDs", "Checklist IDs", "Materials IDs",
            "Document Template IDs", "FAQ IDs",
        ]
        sheet = MagicMock()
        sheet.row_values.return_value = rm_stage_headers
        sheet.get_all_values.return_value = [rm_stage_headers]

        with patch.object(rtm, "find_template_stages", return_value=template_stages), \
             patch("business_core.sheets.get_business_sheet", return_value=sheet), \
             patch("business_core.sheets.batch_append_business_rows"), \
             patch("business_core.sheets.generate_next_ids", return_value=["STAGE-002"]):
            result = bb.create_stages_from_template_record("RM-001", "RTMPL-001")

        self.assertTrue(result["ok"])
        self.assertEqual(result["stages_count"], 1)


# ────────────────────────────────────────────────────────────
# T: GTD Isolation
# ────────────────────────────────────────────────────────────

class TestGTDIsolation(unittest.TestCase):

    def _check(self, path: Path):
        if not path.exists(): return
        mods = _imports(path)
        for mod in GTD_FORBIDDEN:
            self.assertNotIn(mod, mods, f"{path.name} imports {mod!r}")

    def test_T_knowledge_manager(self):
        self._check(WORKSPACE / "business_core" / "knowledge_manager.py")

    def test_T_telegram_handlers(self):
        self._check(WORKSPACE / "business_core" / "telegram_handlers.py")

    def test_T_roadmap_template_manager(self):
        self._check(WORKSPACE / "business_core" / "roadmap_template_manager.py")

    def test_T_sheets(self):
        self._check(WORKSPACE / "business_core" / "sheets.py")

    def test_T_gtd_files_exist(self):
        for f in ["inbox_processor.py", "project_planner.py", "calendar_sync.py"]:
            p = WORKSPACE / f
            if p.exists():
                self.assertTrue(p.exists())

    def test_T_new_sheets_in_registry(self):
        """T: 4 новых листа зарегистрированы в BUSINESS_SHEET_NAMES."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        from business_core.sheets import BUSINESS_SHEET_NAMES, _ID_PREFIXES
        for key, prefix in [
            ("sop_registry",               "SOP"),
            ("checklist_registry",         "CHK"),
            ("document_template_registry", "DOC"),
            ("faq_registry",               "FAQ"),
        ]:
            self.assertIn(key, BUSINESS_SHEET_NAMES, f"{key} отсутствует")
            self.assertIn(key, _ID_PREFIXES,         f"{key} нет в _ID_PREFIXES")
            self.assertEqual(_ID_PREFIXES[key], prefix)

    def test_T_roadmap_stages_has_knowledge_columns(self):
        """T: ROADMAP_STAGES содержит новые knowledge колонки."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS["roadmap_stages"]
        for col in ["SOP IDs", "Checklist IDs", "Materials IDs",
                    "Document Template IDs", "FAQ IDs"]:
            self.assertIn(col, headers, f"ROADMAP_STAGES missing {col!r}")

    def test_T_template_stages_has_knowledge_columns(self):
        """T: ROADMAP_TEMPLATE_STAGES содержит knowledge колонки."""
        for k in list(sys.modules):
            if "business_core" in k: del sys.modules[k]
        from business_core.sheets import BUSINESS_HEADERS
        headers = BUSINESS_HEADERS["roadmap_template_stages"]
        for col in ["SOP IDs", "Checklist IDs", "Materials IDs",
                    "Document Template IDs", "FAQ IDs"]:
            self.assertIn(col, headers, f"ROADMAP_TEMPLATE_STAGES missing {col!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
