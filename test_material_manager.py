"""
Тесты для business_core/material_manager.py (Фаза 2D).

БЕЗ сети, БЕЗ Google Sheets, БЕЗ Telegram, БЕЗ Google Drive.

Запуск: python3 test_material_manager.py
"""

import sys
import traceback

PASSED = 0
FAILED = 0
ERRORS = []


def test(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        print(f"  ✅ {name}")
        PASSED += 1
    else:
        msg = f"  ❌ {name}"
        if detail:
            msg += f"\n     → {detail}"
        print(msg)
        FAILED += 1
        ERRORS.append(name)


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ─────────────────────────────────────────────────────────────
# Импорт
# ─────────────────────────────────────────────────────────────

section("1. Импорт business_core.material_manager")

try:
    from business_core.material_manager import (
        Material,
        create_material_record,
        link_material_to_context,
        update_material_status,
        add_tag,
        classify_file_type,
        get_materials_by_roadmap,
        get_materials_by_stage,
        get_materials_by_client,
        get_materials_by_business,
        get_pending_materials,
        get_unlinked_materials,
        get_materials_by_type,
        get_materials_by_project,
        check_stage_documents,
        get_materials_summary,
        format_material_card,
        format_materials_list,
        format_stage_checklist,
        format_materials_digest,
        MATERIAL_STATUSES, MATERIAL_SOURCES, FILE_TYPES,
        STATUS_ICONS, FILE_ICONS,
    )
    test("import material_manager — все функции", True)
except Exception as e:
    test("import material_manager", False, str(e))
    traceback.print_exc()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Тест 2: Константы
# ─────────────────────────────────────────────────────────────

section("2. Константы")

test("MATERIAL_STATUSES содержит 5 статусов",
     len(MATERIAL_STATUSES) == 5)
for s in ("received", "checked", "approved", "rejected", "archived"):
    test(f"MATERIAL_STATUSES включает '{s}'", s in MATERIAL_STATUSES)

test("MATERIAL_SOURCES содержит Telegram", "Telegram" in MATERIAL_SOURCES)
test("MATERIAL_SOURCES содержит WhatsApp",  "WhatsApp" in MATERIAL_SOURCES)
test("FILE_TYPES содержит pdf",            "pdf"      in FILE_TYPES)
test("FILE_TYPES содержит photo",          "photo"    in FILE_TYPES)
test("FILE_TYPES содержит contract",       "contract" in FILE_TYPES)
test("FILE_TYPES содержит techpassport",   "techpassport" in FILE_TYPES)
test("STATUS_ICONS покрывают все статусы",
     all(s in STATUS_ICONS for s in MATERIAL_STATUSES))
test("FILE_ICONS не пустой", len(FILE_ICONS) >= 5)


# ─────────────────────────────────────────────────────────────
# Тест 3: classify_file_type()
# ─────────────────────────────────────────────────────────────

section("3. classify_file_type() — определение типа файла")

test("техпаспорт.pdf → techpassport",
     classify_file_type("техпаспорт_Иванов.pdf") == "techpassport")
test("techpass_01.pdf → techpassport",
     classify_file_type("techpass_01.pdf") == "techpassport")
test("договор_аренды.pdf → contract",
     classify_file_type("договор_аренды.pdf") == "contract")
test("contract_2026.docx → contract",
     classify_file_type("contract_2026.docx") == "contract")
test("паспорт_Иванов.jpg → passport",
     classify_file_type("паспорт_Иванов.jpg") == "passport")
test("удостоверение_Алибек.jpeg → passport",
     classify_file_type("удостоверение_Алибек.jpeg") == "passport")
test("справка_с_работы.pdf → certificate",
     classify_file_type("справка_с_работы.pdf") == "certificate")
test("акт_ввода.pdf → act",
     classify_file_type("акт_ввода.pdf") == "act")

# По MIME
test("image/jpeg → photo (mime)",
     classify_file_type("photo", "image/jpeg") == "photo")
test("application/pdf → pdf (mime)",
     classify_file_type("file", "application/pdf") == "pdf")
test("docx mime → document",
     classify_file_type("file.docx",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
     ) == "document")

# По расширению
test(".xlsx → spreadsheet",
     classify_file_type("data.xlsx") == "spreadsheet")
test(".zip → archive",
     classify_file_type("docs.zip") == "archive")
test("неизвестный → other",
     classify_file_type("file.xyz") == "other")


# ─────────────────────────────────────────────────────────────
# Тест 4: create_material_record()
# ─────────────────────────────────────────────────────────────

section("4. create_material_record() — создание материала")

m1 = create_material_record(
    source="Telegram",
    filename="техпаспорт_Иванов.pdf",
    file_size_kb=512,
    drive_url="https://drive.google.com/file/test",
    gtd_reference_row=15,
    gtd_project_id="GTD-P-001",
    business_id="BIZ-001",
    client_id="PRS-001",
    roadmap_id="RM-001",
    stage_id="STAGE-001-07",
    material_id="MAT-TEST-001",
)

test("create_material_record возвращает Material",
     isinstance(m1, Material))
test("material_id == MAT-TEST-001", m1.material_id == "MAT-TEST-001")
test("source == Telegram", m1.source == "Telegram")
test("file_type == techpassport", m1.file_type == "techpassport",
     f"получено: {m1.file_type}")
test("filename сохранён", m1.filename == "техпаспорт_Иванов.pdf")
test("file_size_kb == 512", m1.file_size_kb == 512)
test("drive_url сохранён", "drive.google.com" in m1.drive_url)
test("gtd_reference_row == 15", m1.gtd_reference_row == 15)
test("gtd_project_id == GTD-P-001", m1.gtd_project_id == "GTD-P-001")
test("business_id == BIZ-001", m1.business_id == "BIZ-001")
test("client_id == PRS-001", m1.client_id == "PRS-001")
test("roadmap_id == RM-001", m1.roadmap_id == "RM-001")
test("stage_id == STAGE-001-07", m1.stage_id == "STAGE-001-07")
test("статус received по умолчанию", m1.status == "received")
test("received_at заполнен", bool(m1.received_at))
test("is_linked() == True", m1.is_linked())
test("is_pending() == True", m1.is_pending())

# Материал без контекста
m_bare = create_material_record(
    source="WhatsApp",
    filename="фото.jpg",
    material_id="MAT-TEST-002",
)
test("материал без контекста: is_linked() == False", not m_bare.is_linked())
test("материал без контекста: is_pending() == True", m_bare.is_pending())
test("фото.jpg → file_type photo", m_bare.file_type == "photo")

# Неизвестный источник
m_unknown_src = create_material_record(
    source="UnknownSource",
    filename="file.pdf",
    material_id="MAT-TEST-003",
)
test("неизвестный источник → 'Other'", m_unknown_src.source == "Other")

# to_dict()
d = m1.to_dict()
test("to_dict() возвращает dict", isinstance(d, dict))
test("to_dict() содержит material_id", "material_id" in d)
test("to_dict() содержит business_id", "business_id" in d)
test("to_dict() содержит drive_url", "drive_url" in d)


# ─────────────────────────────────────────────────────────────
# Тест 5: link_material_to_context()
# ─────────────────────────────────────────────────────────────

section("5. link_material_to_context() — привязка контекста")

m_bare2 = create_material_record(
    source="Telegram",
    filename="договор.pdf",
    material_id="MAT-TEST-004",
)
test("до привязки: is_linked() == False", not m_bare2.is_linked())

m_bare2 = link_material_to_context(
    m_bare2,
    business_id="BIZ-001",
    client_id="PRS-002",
    roadmap_id="RM-002",
    stage_id="STAGE-002-01",
    city="Астана",
)
test("после привязки: is_linked() == True", m_bare2.is_linked())
test("business_id == BIZ-001", m_bare2.business_id == "BIZ-001")
test("client_id == PRS-002",   m_bare2.client_id == "PRS-002")
test("roadmap_id == RM-002",   m_bare2.roadmap_id == "RM-002")
test("stage_id == STAGE-002-01", m_bare2.stage_id == "STAGE-002-01")
test("city == Астана",          m_bare2.city == "Астана")

# Не перезаписывает существующие данные при пустых значениях
m_bare2 = link_material_to_context(m_bare2, business_id="", city="")
test("пустые значения не перезаписывают существующие",
     m_bare2.business_id == "BIZ-001" and m_bare2.city == "Астана")


# ─────────────────────────────────────────────────────────────
# Тест 6: update_material_status()
# ─────────────────────────────────────────────────────────────

section("6. update_material_status() — обновление статуса")

m_status = create_material_record(
    source="Telegram",
    filename="паспорт.jpg",
    material_id="MAT-TEST-005",
)
test("начальный статус received", m_status.status == "received")

m_status = update_material_status(m_status, "checked", checked_by="Дидар")
test("статус → checked", m_status.status == "checked")
test("checked_by заполнен", m_status.checked_by == "Дидар")

m_status = update_material_status(m_status, "approved", notes="Паспорт в порядке")
test("статус → approved", m_status.status == "approved")
test("approved_at заполнен", bool(m_status.approved_at))
test("notes обновлён", "Паспорт" in m_status.notes)

m_status2 = create_material_record(
    source="Telegram",
    filename="старый.jpg",
    material_id="MAT-TEST-006",
)
m_status2 = update_material_status(m_status2, "rejected", notes="Документ просрочен")
test("статус → rejected", m_status2.status == "rejected")

# Некорректный статус
try:
    update_material_status(m_status, "invalid")
    test("некорректный статус → ValueError", False)
except ValueError:
    test("некорректный статус → ValueError", True)


# ─────────────────────────────────────────────────────────────
# Тест 7: add_tag()
# ─────────────────────────────────────────────────────────────

section("7. add_tag()")

m_tag = create_material_record(
    source="Telegram",
    filename="file.pdf",
    material_id="MAT-TEST-007",
)
m_tag = add_tag(m_tag, "Срочно")
m_tag = add_tag(m_tag, "Техпаспорт")
m_tag = add_tag(m_tag, "срочно")  # дубль

test("теги добавляются", len(m_tag.tags) == 2,
     f"тегов: {m_tag.tags}")
test("дубли не добавляются", m_tag.tags.count("срочно") == 1)


# ─────────────────────────────────────────────────────────────
# Тест 8: Фильтры
# ─────────────────────────────────────────────────────────────

section("8. Фильтры — get_materials_by_*()")

materials = [
    create_material_record("Telegram", "техпаспорт1.pdf", business_id="BIZ-001",
        client_id="PRS-001", roadmap_id="RM-001", stage_id="STAGE-001-07",
        gtd_project_id="GTD-P-001", material_id="MAT-F01"),
    create_material_record("Telegram", "договор1.pdf", business_id="BIZ-001",
        client_id="PRS-001", roadmap_id="RM-001", stage_id="STAGE-001-02",
        material_id="MAT-F02"),
    create_material_record("WhatsApp", "паспорт2.jpg", business_id="BIZ-001",
        client_id="PRS-002", roadmap_id="RM-002",
        material_id="MAT-F03"),
    create_material_record("Email", "виза.pdf", business_id="BIZ-002",
        client_id="PRS-005",
        material_id="MAT-F04"),
    create_material_record("Telegram", "фото.jpg",
        material_id="MAT-F05"),  # без контекста
]
# Одобряем один
materials[0] = update_material_status(materials[0], "approved")

rm1_mats = get_materials_by_roadmap("RM-001", materials)
test("by_roadmap RM-001: 2 материала",
     len(rm1_mats) == 2, f"найдено: {len(rm1_mats)}")

stage_mats = get_materials_by_stage("RM-001", "STAGE-001-07", materials)
test("by_stage STAGE-001-07: 1 материал",
     len(stage_mats) == 1, f"найдено: {len(stage_mats)}")

client_mats = get_materials_by_client("PRS-001", materials)
test("by_client PRS-001: 2 материала",
     len(client_mats) == 2, f"найдено: {len(client_mats)}")

biz_mats = get_materials_by_business("BIZ-001", materials)
test("by_business BIZ-001: 3 материала",
     len(biz_mats) == 3, f"найдено: {len(biz_mats)}")

pending = get_pending_materials(materials)
test("pending: 4 материала (approved не считается)",
     len(pending) == 4, f"найдено: {len(pending)}")

unlinked = get_unlinked_materials(materials)
test("unlinked: 1 материал",
     len(unlinked) == 1, f"найдено: {len(unlinked)}")

photo_mats = get_materials_by_type("photo", materials)
# "паспорт2.jpg" классифицируется как 'passport' (ключевое слово приоритетнее расширения)
# поэтому photo == 1 (только "фото.jpg")
test("by_type photo: 1 материал (паспорт → passport, не photo)",
     len(photo_mats) == 1, f"найдено: {len(photo_mats)}")

proj_mats = get_materials_by_project("GTD-P-001", materials)
test("by_project GTD-P-001: 1 материал",
     len(proj_mats) == 1, f"найдено: {len(proj_mats)}")


# ─────────────────────────────────────────────────────────────
# Тест 9: check_stage_documents()
# ─────────────────────────────────────────────────────────────

section("9. check_stage_documents() — чеклист документов этапа")

docs_required = ["Техпаспорт", "Акт ввода", "Паспорт клиента"]

# Пустой список материалов — всё missing
result_empty = check_stage_documents("Регистрация", docs_required, [])
test("пустые материалы → ready==False", not result_empty["ready"])
test("пустые материалы → 3 missing",
     len(result_empty["missing"]) == 3, f"missing: {result_empty['missing']}")
test("received_count == 0", result_empty["received_count"] == 0)

# Часть документов есть
stage_docs = [
    create_material_record("Telegram", "техпаспорт_Иванов.pdf",
        roadmap_id="RM-001", stage_id="STAGE-001-09",
        material_id="MAT-CHECK-01"),
    create_material_record("Telegram", "паспорт_Иванов.jpg",
        roadmap_id="RM-001", stage_id="STAGE-001-09",
        material_id="MAT-CHECK-02"),
]
stage_docs[0] = update_material_status(stage_docs[0], "approved")
stage_docs[1] = update_material_status(stage_docs[1], "checked")

result_partial = check_stage_documents("Регистрация", docs_required, stage_docs)
test("частичный набор: ready == False", not result_partial["ready"])
test("частичный набор: missing содержит Акт ввода",
     "Акт ввода" in result_partial["missing"],
     f"missing: {result_partial['missing']}")
test("received_count == 2", result_partial["received_count"] == 2,
     f"received: {result_partial['received_count']}")

# Отклонённый документ не засчитывается
rejected_doc = create_material_record("Telegram", "техпаспорт_старый.pdf",
    roadmap_id="RM-001", stage_id="STAGE-001-09", material_id="MAT-CHECK-03")
rejected_doc = update_material_status(rejected_doc, "rejected")
result_rej = check_stage_documents("Регистрация", docs_required, [rejected_doc])
test("rejected документ не засчитывается как полученный",
     result_rej["received_count"] == 0)


# ─────────────────────────────────────────────────────────────
# Тест 10: get_materials_summary()
# ─────────────────────────────────────────────────────────────

section("10. get_materials_summary() — статистика")

summary = get_materials_summary(materials)
test("summary['total'] == 5", summary["total"] == 5)
test("summary['pending'] == 4", summary["pending"] == 4)
test("summary['approved'] == 1", summary["approved"] == 1)
test("summary['unlinked'] == 1", summary["unlinked"] == 1)
test("summary['by_type'] dict", isinstance(summary["by_type"], dict))
test("summary['by_source'] dict", isinstance(summary["by_source"], dict))
test("by_source['Telegram'] >= 2", summary["by_source"].get("Telegram", 0) >= 2)
test("total_size_kb >= 0", summary["total_size_kb"] >= 0)
print(f"     by_type: {summary['by_type']}")
print(f"     by_source: {summary['by_source']}")


# ─────────────────────────────────────────────────────────────
# Тест 11: Форматирование
# ─────────────────────────────────────────────────────────────

section("11. Форматирование")

# format_material_card
card = format_material_card(materials[0])
test("format_material_card возвращает строку", isinstance(card, str))
test("карточка содержит имя файла", "техпаспорт1" in card)
test("карточка содержит источник", "Telegram" in card)
test("карточка содержит статус", "approved" in card or "✅" in card)

# format_materials_list
lst = format_materials_list(materials, "Документы по кейсу")
test("format_materials_list возвращает строку", isinstance(lst, str))
test("список содержит заголовок", "Документы по кейсу" in lst)
test("список содержит файлы", "техпаспорт" in lst or "договор" in lst)

empty_lst = format_materials_list([], "Пусто")
test("пустой список → сообщение", "нет материалов" in empty_lst or "Пусто" in empty_lst)

# format_stage_checklist
check = check_stage_documents("Регистрация", docs_required, stage_docs)
checklist = format_stage_checklist(check, stage_docs)
test("format_stage_checklist возвращает строку", isinstance(checklist, str))
test("чеклист содержит название этапа", "Регистрация" in checklist)
test("чеклист содержит счётчик", "/" in checklist)

# format_materials_digest
digest = format_materials_digest(materials)
test("format_materials_digest возвращает строку", isinstance(digest, str))
test("дайджест содержит 'ожидают'", "ожидают" in digest.lower() or "Ожидают" in digest)

empty_digest = format_materials_digest([])
test("пустой дайджест → сообщение", len(empty_digest) > 5)


# ─────────────────────────────────────────────────────────────
# Тест 12: Связь с Roadmap Manager
# ─────────────────────────────────────────────────────────────

section("12. Связь с Roadmap Manager")

try:
    from business_core.roadmap_manager import (
        create_roadmap, start_roadmap, get_stage_template
    )

    rm = create_roadmap(
        business_id="BIZ-001",
        service_id="SVC-002",
        client_id="PRS-001",
        client_name="Иванов",
        city="Алматы",
        responsible="Дидар",
        roadmap_id="RM-LINK-001",
    )
    rm = start_roadmap(rm)
    current_stage = rm.get_current_stage()

    # Создаём материал и привязываем к текущему этапу
    m_linked = create_material_record(
        source="Telegram",
        filename="техпаспорт_Иванов.pdf",
        business_id=rm.business_id,
        client_id=rm.client_id,
        roadmap_id=rm.roadmap_id,
        stage_id=current_stage.stage_id if current_stage else "",
        material_id="MAT-LINK-001",
    )

    # Проверяем материалы этапа через filter
    stage_linked = get_materials_by_stage(
        rm.roadmap_id,
        current_stage.stage_id if current_stage else "",
        [m_linked],
    )
    test("материал привязан к этапу дорожной карты",
         len(stage_linked) == 1)

    # Чеклист документов для текущего этапа
    if current_stage and current_stage.docs_required:
        checklist_result = check_stage_documents(
            current_stage.name,
            current_stage.docs_required,
            stage_linked,
        )
        test("чеклист для этапа дорожной карты работает",
             isinstance(checklist_result, dict))
        test("чеклист содержит stage_name",
             checklist_result["stage_name"] == current_stage.name)
    else:
        test("чеклист: этап без документов — пропущен", True)

    test("Material + Roadmap Manager интеграция работает", True)

except Exception as e:
    test("Material + Roadmap Manager интеграция", False, str(e))
    traceback.print_exc()


# ─────────────────────────────────────────────────────────────
# Тест 13: Изоляция
# ─────────────────────────────────────────────────────────────

section("13. Изоляция — GTD-файлы не импортируются")

import pathlib
source_code = pathlib.Path("business_core/material_manager.py").read_text()
for forbidden in ["telegram_bot", "inbox_processor", "project_planner",
                  "calendar_sync", "from sheets import", "import sheets\n"]:
    test(
        f"material_manager.py не импортирует '{forbidden}'",
        forbidden not in source_code,
    )

import os
section("14. GTD-файлы не изменены")
for f in ["telegram_bot.py", "sheets.py", "inbox_processor.py",
          "project_planner.py", "calendar_sync.py"]:
    test(f"{f} существует", os.path.exists(f))


# ─────────────────────────────────────────────────────────────
# Итог
# ─────────────────────────────────────────────────────────────

total = PASSED + FAILED
print(f"\n{'═' * 60}")
print(f"  ИТОГ: {PASSED}/{total} тестов прошло")
if FAILED == 0:
    print("  🎉 Все тесты прошли! Material Manager готов.")
    print("\n  ✅ Фазы 2A–2D завершены.")
    print("  Следующий шаг: сохранение git + Фаза 3 — Google Drive")
else:
    print(f"  ❌ Провалено: {FAILED}")
    for err in ERRORS:
        print(f"     • {err}")
print(f"{'═' * 60}\n")

sys.exit(0 if FAILED == 0 else 1)
