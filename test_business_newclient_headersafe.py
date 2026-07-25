"""
Phase 10.2B.4: Header-safe newclient_confirm() — mock tests.

Проверяет, что создание клиента через /newclient (people_registry)
формирует строку по ФАКТИЧЕСКИМ заголовкам листа, а не по позиции,
и что подтверждённое в Phase 10.2B.3 смещение
("active" -> Теплота, "тёплый" -> Комментарий, Biz IDs -> Company ID,
Primary Biz ID -> за пределы листа) больше не воспроизводится.

Phase 23D-2: newclient_confirm()'s STATUS_NEW branch now writes through
business_core.person_manager.create_person() (core identity fields)
followed by update_person() (Бизнесы/Уровень доверия/Теплота — the
"profile fields" split, see ARCHITECTURE.md / Person Layer). The mock
sheet is now STATEFUL (supports find/row_values/get_all_values/update/
update_cell against the same underlying row list) so assertions can
read the final, post-both-calls state of PEOPLE_REGISTRY — a more
robust check than parsing one specific low-level write call, and the
only way to correctly verify fields that are now set via update_cell()
rather than the initial row construction.

Все тесты полностью мокают business_core.sheets.get_business_sheet —
ни один тест не должен обращаться к live Google Sheets API.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Полный порядок заголовков "как на проде до фикса" (константа BUSINESS_HEADERS)
STANDARD_HEADERS = [
    "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
    "Telegram", "Email", "Город", "Компания", "Должность",
    "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
    "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
    "День рождения", "Важные события",
    "Дата первого контакта", "Дата последнего контакта",
    "Канал последнего контакта", "История",
    "Следующее касание", "Тип касания", "Заметка касания",
    "Статус отношений", "Теплота", "Комментарий",
    "Google Drive", "Drive Folder ID",
    "Biz IDs", "Company ID", "Citizenship", "Passport / ID", "Primary Biz ID",
]

# Та же самая, но с перемешанным порядком (не совпадает по позиции) —
# "ID" остаётся первой колонкой (реалистичный сценарий: в реальном
# Google Sheets колонку A с ID практически никогда не переносят, даже
# когда остальные колонки переставляют; это же допущение уже разделяют
# find(..., in_column=1)-паттерны во всех менеджерах этого кодбейса —
# organization_manager.py, roadmap_manager.py, теперь и person_manager.py).
SHUFFLED_HEADERS = [
    "ID",
    "Primary Biz ID", "Passport / ID", "Citizenship", "Company ID", "Biz IDs",
    "Drive Folder ID", "Google Drive",
    "Комментарий", "Теплота", "Статус отношений",
    "Заметка касания", "Тип касания", "Следующее касание",
    "История", "Канал последнего контакта",
    "Дата последнего контакта", "Дата первого контакта",
    "Важные события", "День рождения",
    "Теги", "Специализация", "Кого знает", "Чем я полезен", "Чем полезен",
    "Источник", "Уровень доверия", "Бизнесы", "Подтип", "Тип",
    "Должность", "Компания", "Город", "Email", "Telegram",
    "WhatsApp", "Телефон 2", "Телефон", "Имя", "ФИО",
]


class _StatefulSheet:
    """A minimal, stateful stand-in for one Sheets tab — supports
    find()/row_values()/get_all_values()/update()/update_cell() against
    a single shared row list, so create_person()'s append and
    update_person()'s per-field writes are both reflected in
    get_all_values()/row_values() afterwards."""

    def __init__(self, headers: list, existing_rows: list | None = None):
        self.headers = list(headers)
        self.rows = [list(r) for r in (existing_rows or [])]

    def get_all_values(self):
        return [self.headers] + self.rows

    def row_values(self, r):
        if r == 1:
            return self.headers
        return self.rows[r - 2]

    def find(self, value, in_column=1):
        for i, row in enumerate(self.rows):
            if row and row[0] == value:
                cell = MagicMock()
                cell.row = i + 2
                return cell
        return None

    def update(self, range_name=None, values=None):
        self.rows.append(list(values[0]))

    def update_cell(self, row_num, col, value):
        row = self.rows[row_num - 2]
        while len(row) < col:
            row.append("")
        row[col - 1] = value


def _make_people_sheet(headers: list, existing_rows: list | None = None):
    """Returns a MagicMock wired to a _StatefulSheet instance, so test
    code can still use MagicMock call-tracking (call_count, call_args)
    while the underlying data is genuinely stateful."""
    state = _StatefulSheet(headers, existing_rows)
    sheet = MagicMock()
    sheet.get_all_values.side_effect = state.get_all_values
    sheet.row_values.side_effect = state.row_values
    sheet.find.side_effect = state.find
    sheet.update.side_effect = state.update
    sheet.update_cell.side_effect = state.update_cell
    sheet._state = state  # exposed for assertions reading final row state
    return sheet


def _make_biz_registry_sheet():
    """Minimal BIZ_REGISTRY mock — just enough for create_person()'s
    read-only find_row_by_id("biz_registry", ...) FK check to succeed
    for BIZ-001/BIZ-002, exactly as they exist in production today."""
    sheet = MagicMock()
    sheet.get_all_values.return_value = [["ID"], ["BIZ-001"], ["BIZ-002"]]
    return sheet


def _make_update_context(full_name="Иван Иванов", phone="+77771234567",
                          businesses="ТестБизнес", person_type="клиент",
                          biz_id_resolved="BIZ-001"):
    update = MagicMock()
    update.message.text = "Подтверждаю"
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    nc = {
        "full_name": full_name,
        "phone": phone,
        "businesses": businesses,
        "person_type": person_type,
        # Phase 13A: резолвинг бизнеса теперь происходит в newclient_biz()
        # (через resolve_business()), ДО показа карточки подтверждения —
        # newclient_confirm() лишь читает уже готовый biz_id_resolved.
        "biz_id_resolved": biz_id_resolved,
    }
    # Phase 11J: newclient_confirm() читает только "nc_confirmed_snapshot"
    # (immutable snapshot, взятый в newclient_biz() до показа карточки
    # подтверждения) — "nc" оставлен тоже для полноты мока состояния.
    context.user_data = {
        "nc": dict(nc),
        "nc_confirmed_snapshot": dict(nc),
    }
    return update, context


def _fresh_import():
    for key in list(sys.modules.keys()):
        if "business_core" in key:
            del sys.modules[key]
    from business_core.telegram_handlers import newclient_confirm
    return newclient_confirm


def _identity_result_from_legacy(existing: dict | None, biz_id_resolved: str = "") -> dict:
    """Phase 31D: newclient_confirm() now calls
    person_manager.resolve_person_identity() directly instead of
    business_builder.find_existing_person() — this converts the old
    find_existing_person()-shaped test fixture into the canonical
    resolve_person_identity() result shape, so existing test call
    sites don't all need to be rewritten to build canonical Person
    dicts by hand.

    newclient_confirm() now re-derives same_biz itself via
    has_person_business_link(person, biz_id_resolved), rather than
    trusting a "same_biz" boolean handed to it directly (that field no
    longer exists on resolve_person_identity()'s Person shape) — so
    when the legacy fixture doesn't specify "biz_ids" explicitly, this
    reconstructs a biz_ids list that reproduces the same same_biz
    outcome the fixture's "same_biz" flag originally encoded.
    """
    if existing is None:
        return {"status": "not_found", "person": None, "matches": [], "matched_by": [], "error": None}
    biz_ids = existing.get("biz_ids")
    if biz_ids is None:
        same_biz_flag = existing.get("same_biz", True)
        biz_ids = [biz_id_resolved] if (same_biz_flag and biz_id_resolved) else []
    person = {
        "person_id": existing["prs_id"],
        "full_name": existing.get("full_name", "Иван Иванов"),
        "biz_ids": biz_ids,
        "primary_biz_id": existing.get("primary_biz_id", ""),
        "google_drive": existing.get("drive_url", ""),
        "drive_folder_id": existing.get("drive_folder_id", ""),
        "phone": existing.get("phone_raw", ""),
        "row_num": existing.get("row_num", 2),
    }
    return {"status": "single_match", "person": person, "matches": [person], "matched_by": ["phone"], "error": None}


def _run_newclient_confirm(sheet, find_existing_return=None, biz_id_resolved="BIZ-001"):
    """
    Запустить newclient_confirm с полностью замоканными зависимостями.
    Возвращает (update, context, sheet) для дальнейших проверок.

    Phase 31D: newclient_confirm() migrated onto person_manager.
    resolve_person_identity()/append_person_biz_id()/
    update_person_drive_info() directly (ADR-015 Decision 2) — the
    mocks below target those, not the retired business_builder call
    sites (find_existing_person()/add_biz_id_to_person()/
    update_person_drive_info() remain as compatibility wrappers for
    other callers, but /newclient no longer uses them).
    """
    biz_sheet = _make_biz_registry_sheet()

    def fake_get_business_sheet(key):
        return sheet if key == "people_registry" else biz_sheet

    async def run():
        newclient_confirm = _fresh_import()
        update, context = _make_update_context(biz_id_resolved=biz_id_resolved)

        with patch("business_core.sheets.get_business_sheet", side_effect=fake_get_business_sheet), \
             patch("business_core.sheets.generate_next_id", return_value="PRS-999"), \
             patch("business_core.person_manager.resolve_person_identity",
                   return_value=_identity_result_from_legacy(find_existing_return, biz_id_resolved)), \
             patch("business_core.person_manager.append_person_biz_id") as mock_add_biz, \
             patch("business_core.person_manager.update_person_drive_info") as mock_upd_drive, \
             patch("business_core.business_builder.provision_client_drive",
                   return_value={"ok": False, "error": "Drive не задан для этого бизнеса"}):
            await newclient_confirm(update, context)

        return update, context, mock_add_biz, mock_upd_drive

    return asyncio.run(run())


class TestNewClientHeaderSafeStandardOrder(unittest.TestCase):
    """1, 3-9: стандартный порядок заголовков — значения в правильных колонках."""

    def setUp(self):
        self.sheet = _make_people_sheet(STANDARD_HEADERS)
        self.update, self.context, self.add_biz, self.upd_drive = \
            _run_newclient_confirm(self.sheet, find_existing_return=None)

    def test_1_client_created(self):
        self.update.message.reply_text.assert_called_once()
        msg = self.update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)
        self.assertIn("PRS-999", msg)

    def _created_row(self) -> dict:
        """The row as it looked immediately after create_person()'s
        append (the ONE sheet.update() call) — core identity fields only."""
        self.assertEqual(self.sheet.update.call_count, 1)
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (values[i] if i < len(values) else "") for h, i in idx.items()}

    def _final_row(self) -> dict:
        """The row's FINAL state after create_person() AND
        update_person() (profile fields) have both run."""
        row = self.sheet._state.rows[0]
        idx = {h: i for i, h in enumerate(STANDARD_HEADERS)}
        return {h: (row[i] if i < len(row) else "") for h, i in idx.items()}

    def test_3_id_in_id_column(self):
        row = self._created_row()
        self.assertEqual(row["ID"], "PRS-999")

    def test_3_name_in_fio_column(self):
        row = self._created_row()
        self.assertEqual(row["ФИО"], "Иван Иванов")

    def test_4_relationship_status_active(self):
        row = self._created_row()
        self.assertEqual(row["Статус отношений"], "active")

    def test_5_warmth_value(self):
        """Теплота is now set via the follow-up update_person() call
        (Phase 23D-2), not the initial create_person() row — check the
        FINAL sheet state, not the create-time row."""
        row = self._final_row()
        self.assertEqual(row["Теплота"], "тёплый")

    def test_6_comment_not_warmth(self):
        row = self._final_row()
        self.assertEqual(row["Комментарий"], "")
        self.assertNotEqual(row["Комментарий"], "тёплый")

    def test_7_biz_ids_value(self):
        row = self._created_row()
        self.assertEqual(row["Biz IDs"], "BIZ-001")

    def test_8_primary_biz_id_value(self):
        row = self._created_row()
        self.assertEqual(row["Primary Biz ID"], "BIZ-001")

    def test_9_unknown_extra_columns_untouched(self):
        row = self._final_row()
        # поля, которым не присвоено значение в newclient_confirm, должны остаться пустыми
        for h in ("Company ID", "Citizenship", "Passport / ID", "Телефон 2",
                  "WhatsApp", "Email", "Город"):
            self.assertEqual(row[h], "", f"{h} должно быть пустым")

    def test_10_headers_read_once_for_create(self):
        # create_person()'s and update_person()'s header reads are counted
        # SEPARATELY by splitting the sheet's chronological call log on
        # the one sheet.update() call (create_person()'s row append) —
        # every row_values(1) call before it belongs to create_person(),
        # every one after it belongs to update_person()/_find_person_row().
        calls = self.sheet.method_calls
        append_index = next(
            i for i, c in enumerate(calls) if c[0] == "update"
        )
        before, after = calls[:append_index], calls[append_index + 1:]

        header_reads_for_create = [c for c in before if c[0] == "row_values" and c.args == (1,)]
        header_reads_for_update = [c for c in after if c[0] == "row_values" and c.args == (1,)]

        # create_person() reads headers exactly once before its append.
        self.assertEqual(len(header_reads_for_create), 1)
        # update_person() reads headers exactly twice after the append:
        # once inside _find_person_row() (to map the existing row back to
        # a dict) and once more inside update_person() itself (to resolve
        # the column index for update_cell()). Phase 31D adds a THIRD
        # read after the append: provision_client_drive_safe()'s own
        # find_person_by_id() call, which re-checks PEOPLE_REGISTRY for
        # an existing Drive reference before deciding whether to create
        # a folder — this is the retry-safety check itself (ADR-015
        # Decision 15), not an artifact of the mock.
        self.assertEqual(len(header_reads_for_update), 3)

    def test_11_append_called_once(self):
        self.assertEqual(self.sheet.update.call_count, 1)

    def test_12_bizness_legacy_column_set_via_update_person(self):
        """Phase 23D-2: 'Бизнесы' (legacy display name) is now written
        by update_person(), not create_person() — verify it lands
        correctly in the final state."""
        row = self._final_row()
        self.assertEqual(row["Бизнесы"], "ТестБизнес")


class TestNewClientHeaderSafeShuffledOrder(unittest.TestCase):
    """2: результат не зависит от перестановки заголовков."""

    def setUp(self):
        self.sheet = _make_people_sheet(SHUFFLED_HEADERS)
        self.update, self.context, *_ = _run_newclient_confirm(
            self.sheet, find_existing_return=None
        )

    def _final_row(self) -> dict:
        row = self.sheet._state.rows[0]
        idx = {h: i for i, h in enumerate(SHUFFLED_HEADERS)}
        return {h: (row[i] if i < len(row) else "") for h, i in idx.items()}

    def test_2_created_with_shuffled_headers(self):
        self.update.message.reply_text.assert_called_once()
        msg = self.update.message.reply_text.call_args[0][0]
        self.assertIn("✅", msg)

    def test_values_correct_despite_shuffle(self):
        row = self._final_row()
        self.assertEqual(row["ID"], "PRS-999")
        self.assertEqual(row["ФИО"], "Иван Иванов")
        self.assertEqual(row["Статус отношений"], "active")
        self.assertEqual(row["Теплота"], "тёплый")
        self.assertEqual(row["Комментарий"], "")
        self.assertEqual(row["Biz IDs"], "BIZ-001")
        self.assertEqual(row["Primary Biz ID"], "BIZ-001")


class TestNewClientNoShiftRegression(unittest.TestCase):
    """Regression: старое ошибочное смещение НЕ воспроизводится."""

    def setUp(self):
        self.sheet = _make_people_sheet(STANDARD_HEADERS)
        self.update, self.context, *_ = _run_newclient_confirm(
            self.sheet, find_existing_return=None
        )

    def test_row_length_matches_headers(self):
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        self.assertLessEqual(len(values), len(STANDARD_HEADERS))

    def test_no_overflow_past_headers(self):
        kwargs = self.sheet.update.call_args.kwargs
        values = kwargs["values"][0]
        self.assertEqual(len(values), len(STANDARD_HEADERS))


class TestNewClientSameBizNoNewRow(unittest.TestCase):
    """12: SAME_BIZ не создаёт новую строку."""

    def test_same_biz_skips_append(self):
        sheet = _make_people_sheet(STANDARD_HEADERS)
        with patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update:
            update, context, add_biz, upd_drive = _run_newclient_confirm(
                sheet,
                find_existing_return={"prs_id": "PRS-001", "same_biz": True, "drive_url": ""},
            )
            mock_create.assert_not_called()
            mock_update.assert_not_called()
        self.assertEqual(sheet.update.call_count, 0)
        add_biz.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("уже существует", msg)


class TestNewClientOtherBizNoNewRow(unittest.TestCase):
    """13: OTHER_BIZ не создаёт новую строку, а обновляет связь."""

    def test_other_biz_updates_not_creates(self):
        sheet = _make_people_sheet(STANDARD_HEADERS)
        with patch("business_core.person_manager.create_person") as mock_create, \
             patch("business_core.person_manager.update_person") as mock_update:
            update, context, add_biz, upd_drive = _run_newclient_confirm(
                sheet,
                find_existing_return={"prs_id": "PRS-002", "same_biz": False, "drive_url": ""},
                biz_id_resolved="BIZ-002",
            )
            mock_create.assert_not_called()
            mock_update.assert_not_called()
        self.assertEqual(sheet.update.call_count, 0)
        add_biz.assert_called_once_with("PRS-002", "BIZ-002")
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("другом бизнесе", msg)


class TestNewClientMissingRequiredHeader(unittest.TestCase):
    """14, 15: отсутствие обязательного заголовка -> append не вызывается, ошибка пользователю."""

    def test_missing_biz_ids_header_blocks_append(self):
        headers_without_biz_ids = [h for h in STANDARD_HEADERS if h != "Biz IDs"]
        sheet = _make_people_sheet(headers_without_biz_ids)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0, "append не должен выполняться")
        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)
        self.assertIn("Biz IDs", msg)

    def test_missing_primary_biz_id_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Primary Biz ID"]
        sheet = _make_people_sheet(headers_without)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0)
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)

    def test_missing_relationship_status_header_blocks_append(self):
        headers_without = [h for h in STANDARD_HEADERS if h != "Статус отношений"]
        sheet = _make_people_sheet(headers_without)

        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        self.assertEqual(sheet.update.call_count, 0)

    def test_missing_header_no_partial_write(self):
        """Убедиться, что при отсутствии заголовка sheet.update вообще не трогается
        (нет частичной/смещённой записи)."""
        headers_without = [h for h in STANDARD_HEADERS if h != "Комментарий"]
        sheet = _make_people_sheet(headers_without)

        _run_newclient_confirm(sheet, find_existing_return=None)

        sheet.update.assert_not_called()


class TestNewClientLiveHeadersSnapshot(unittest.TestCase):
    """Против реальных live-заголовков PEOPLE_REGISTRY (33 колонки, Phase 10.2B.3),
    у которых отсутствуют Biz IDs/Primary Biz ID и т.д. — append должен быть
    заблокирован (ожидаемое поведение: лучше явная ошибка, чем смещение)."""

    LIVE_HEADERS_33 = [
        "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp",
        "Telegram", "Email", "Город", "Компания", "Должность",
        "Тип", "Подтип", "Бизнесы", "Уровень доверия", "Источник",
        "Чем полезен", "Чем я полезен", "Кого знает", "Специализация", "Теги",
        "День рождения", "Важные события",
        "Дата первого контакта", "Дата последнего контакта",
        "Канал последнего контакта", "История",
        "Следующее касание", "Тип касания", "Заметка касания",
        "Статус отношений", "Теплота", "Комментарий",
    ]

    def test_live_snapshot_blocks_append_safely(self):
        sheet = _make_people_sheet(self.LIVE_HEADERS_33)
        update, context, *_ = _run_newclient_confirm(sheet, find_existing_return=None)

        sheet.update.assert_not_called()
        msg = update.message.reply_text.call_args[0][0]
        self.assertIn("❌", msg)


if __name__ == "__main__":
    unittest.main()
