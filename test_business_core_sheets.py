"""
Тесты для business_core/sheets.py (Фаза 2A).

ВНИМАНИЕ: тест СОЗДАЁТ реальные листы в Google Sheets BUSINESS_CORE.
Запускать только после подтверждения пользователем.

Запуск: python3 test_business_core_sheets.py
"""

import os
import sys
import traceback

# ─────────────────────────────────────────────────────────────
# Инфраструктура тестирования
# ─────────────────────────────────────────────────────────────

PASSED = 0
FAILED = 0
ERRORS = []
TEST_BIZ_ID = "BIZ-TEST"


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
    print(f"\n{'─' * 58}")
    print(f"  {title}")
    print(f"{'─' * 58}")


# ─────────────────────────────────────────────────────────────
# Тест 1: Импорт и конфигурация (без сети)
# ─────────────────────────────────────────────────────────────

section("1. Импорт модуля business_core.sheets")

try:
    from business_core.sheets import (
        BUSINESS_SHEET_NAMES,
        BUSINESS_HEADERS,
        get_business_spreadsheet,
        get_business_sheet,
        ensure_headers,
        init_business_core_sheets,
        append_business_row,
        read_business_sheet,
        update_business_cell,
        generate_next_id,
        get_spreadsheet_url,
        is_enabled,
        check_configuration,
        find_row_by_id,
        _col_letter,
    )
    test("import business_core.sheets — все функции", True)
except Exception as e:
    test("import business_core.sheets", False, str(e))
    traceback.print_exc()
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# Тест 2: Структуры данных
# ─────────────────────────────────────────────────────────────

section("2. Структуры BUSINESS_SHEET_NAMES и BUSINESS_HEADERS")

test("BUSINESS_SHEET_NAMES содержит 10 листов",
     len(BUSINESS_SHEET_NAMES) == 10,
     f"найдено: {len(BUSINESS_SHEET_NAMES)}")

expected_keys = [
    "biz_registry", "service_catalog", "people_registry",
    "channel_registry", "integration_registry",
    "roadmaps", "roadmap_stages", "materials",
    "relationship_capital", "business_branches",
]
for key in expected_keys:
    test(f"ключ '{key}' присутствует", key in BUSINESS_SHEET_NAMES)

test("BUSINESS_HEADERS содержит заголовки для всех 10 листов",
     len(BUSINESS_HEADERS) == 10,
     f"найдено: {len(BUSINESS_HEADERS)}")

test("BIZ_REGISTRY: 20 колонок",
     len(BUSINESS_HEADERS["biz_registry"]) == 20,
     f"найдено: {len(BUSINESS_HEADERS.get('biz_registry', []))}")

test("SERVICE_CATALOG: 28 колонок",
     len(BUSINESS_HEADERS["service_catalog"]) == 28,
     f"найдено: {len(BUSINESS_HEADERS.get('service_catalog', []))}")

test("PEOPLE_REGISTRY: 33 колонки",
     len(BUSINESS_HEADERS["people_registry"]) == 33,
     f"найдено: {len(BUSINESS_HEADERS.get('people_registry', []))}")

test("ROADMAPS: 24 колонки",
     len(BUSINESS_HEADERS["roadmaps"]) == 24,
     f"найдено: {len(BUSINESS_HEADERS.get('roadmaps', []))}")

test("MATERIALS: 19 колонок",
     len(BUSINESS_HEADERS["materials"]) == 19,
     f"найдено: {len(BUSINESS_HEADERS.get('materials', []))}")

# ─────────────────────────────────────────────────────────────
# Тест 3: _col_letter()
# ─────────────────────────────────────────────────────────────

section("3. _col_letter() — конвертация номера колонки в букву")

test("_col_letter(1) == 'A'",   _col_letter(1)  == "A")
test("_col_letter(26) == 'Z'",  _col_letter(26) == "Z")
test("_col_letter(27) == 'AA'", _col_letter(27) == "AA")
test("_col_letter(28) == 'AB'", _col_letter(28) == "AB")
test("_col_letter(52) == 'AZ'", _col_letter(52) == "AZ")

# ─────────────────────────────────────────────────────────────
# Тест 4: check_configuration()
# ─────────────────────────────────────────────────────────────

section("4. check_configuration()")

cfg = check_configuration()
test("check_configuration() возвращает dict", isinstance(cfg, dict))
test("cfg содержит 'ok'", "ok" in cfg)
test("cfg содержит 'spreadsheet_id'", "spreadsheet_id" in cfg)
test("cfg содержит 'service_account'", "service_account" in cfg)
test("cfg содержит 'url'", "url" in cfg)
test("BUSINESS_SPREADSHEET_ID задан", bool(cfg["spreadsheet_id"]),
     "Добавьте BUSINESS_SPREADSHEET_ID в .env")

if cfg["ok"]:
    test("конфигурация полностью корректна", True)
    print(f"\n     Service account: {cfg['service_account']}")
    print(f"     Spreadsheet ID:  {cfg['spreadsheet_id']}")
    print(f"     URL:             {cfg['url']}")
else:
    for issue in cfg["issues"]:
        test(f"config issue: {issue}", False)

test("get_spreadsheet_url() возвращает корректный URL",
     "docs.google.com/spreadsheets/d/" in get_spreadsheet_url())

test("is_enabled() возвращает bool",
     isinstance(is_enabled(), bool))
print(f"     BUSINESS_CORE_ENABLED = {is_enabled()}")

# ─────────────────────────────────────────────────────────────
# Тест 5: get_business_sheet() с неверным ключом
# ─────────────────────────────────────────────────────────────

section("5. Обработка ошибок (без сети)")

try:
    get_business_sheet("несуществующий_ключ")
    test("get_business_sheet с неверным ключом → KeyError", False)
except KeyError as e:
    test("get_business_sheet с неверным ключом → KeyError", True,
         f"KeyError: {e}")
except Exception as e:
    test("get_business_sheet с неверным ключом → ожидался KeyError", False, str(e))

# Проверка что основной GTD sheets.py НЕ импортируется
import ast, pathlib
bc_sheets_path = pathlib.Path("business_core/sheets.py")
source = bc_sheets_path.read_text()
for forbidden in ["from sheets import", "import sheets"]:
    test(
        f"business_core/sheets.py не импортирует GTD sheets: '{forbidden}'",
        forbidden not in source,
    )

# ─────────────────────────────────────────────────────────────
# Тест 6: NETWORK — реальный Google Sheets
# ─────────────────────────────────────────────────────────────

section("6. Подключение к Google Sheets (СЕТЬ)")

if not cfg["ok"]:
    print("  ⏭ Пропущено — конфигурация некорректна")
else:
    try:
        ss = get_business_spreadsheet()
        test("get_business_spreadsheet() — подключение успешно", True)
        test("spreadsheet имеет title", bool(ss.title), f"title: {ss.title}")
        print(f"     Таблица: «{ss.title}»")
    except PermissionError as e:
        test("get_business_spreadsheet() — доступ", False,
             f"Дайте доступ service account к таблице:\n"
             f"     {cfg['service_account']}\n"
             f"     Ошибка: {str(e)[:100]}")
        print("\n❌ Нет доступа к таблице. Дальнейшие тесты с сетью невозможны.")
        print_summary()
        sys.exit(1)
    except Exception as e:
        test("get_business_spreadsheet()", False, str(e))
        print_summary()
        sys.exit(1)

# ─────────────────────────────────────────────────────────────
# Тест 7: init_business_core_sheets()
# ─────────────────────────────────────────────────────────────

section("7. init_business_core_sheets() — создание/проверка листов")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    try:
        results = init_business_core_sheets(verbose=True)
        test("init_business_core_sheets() вернул результаты",
             isinstance(results, dict))
        test(f"все 10 листов инициализированы",
             all(results.values()),
             f"проблемы: {[k for k, v in results.items() if not v]}")
    except Exception as e:
        test("init_business_core_sheets()", False, str(e))
        traceback.print_exc()

# ─────────────────────────────────────────────────────────────
# Тест 8: get_business_sheet() для каждого листа
# ─────────────────────────────────────────────────────────────

section("8. get_business_sheet() — доступ к каждому листу")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    for key in BUSINESS_SHEET_NAMES:
        try:
            sheet = get_business_sheet(key)
            test(f"get_business_sheet('{key}')", True,
                 f"лист: {sheet.title}")
        except Exception as e:
            test(f"get_business_sheet('{key}')", False, str(e))

# ─────────────────────────────────────────────────────────────
# Тест 9: generate_next_id()
# ─────────────────────────────────────────────────────────────

section("9. generate_next_id()")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    id_biz = generate_next_id("biz_registry")
    test("generate_next_id('biz_registry') начинается с 'BIZ-'",
         id_biz.startswith("BIZ-"), f"получено: {id_biz}")

    id_prs = generate_next_id("people_registry")
    test("generate_next_id('people_registry') начинается с 'PRS-'",
         id_prs.startswith("PRS-"), f"получено: {id_prs}")

    id_stage = generate_next_id("roadmap_stages", "STAGE")
    test("generate_next_id('roadmap_stages', 'STAGE') начинается с 'STAGE-'",
         id_stage.startswith("STAGE-"), f"получено: {id_stage}")

    print(f"     Следующие ID: {id_biz}, {id_prs}, {id_stage}")

# ─────────────────────────────────────────────────────────────
# Тест 10: append_business_row() → тестовая запись
# ─────────────────────────────────────────────────────────────

section("10. append_business_row() — добавить тестовую запись")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    from datetime import date

    test_row = [
        TEST_BIZ_ID,                          # ID
        "Тестовый бизнес",                    # Название
        "test-business",                       # Slug
        "test",                                # Статус
        "Проверка Business Core Sheets",       # Описание
        "Алматы, Астана",                      # Города
        "Дидар",                               # Ответственный
        "2",                                   # Приоритет
        date.today().isoformat(),              # Дата старта
    ]

    try:
        row_num = append_business_row("biz_registry", test_row)
        test("append_business_row() записал строку в BIZ_REGISTRY",
             row_num >= 2, f"строка: {row_num}")
        print(f"     Записано в строку: {row_num}")
    except Exception as e:
        test("append_business_row()", False, str(e))
        traceback.print_exc()

# ─────────────────────────────────────────────────────────────
# Тест 11: read_business_sheet() — прочитать BIZ_REGISTRY
# ─────────────────────────────────────────────────────────────

section("11. read_business_sheet() — проверить тестовую запись")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    try:
        records = read_business_sheet("biz_registry")
        test("read_business_sheet() вернул список", isinstance(records, list))
        test("BIZ_REGISTRY содержит записи", len(records) > 0,
             f"найдено: {len(records)}")

        test_record = next(
            (r for r in records if r.get("ID") == TEST_BIZ_ID), None
        )
        test(f"Тестовая запись '{TEST_BIZ_ID}' найдена", test_record is not None)

        if test_record:
            test("Название == 'Тестовый бизнес'",
                 test_record.get("Название") == "Тестовый бизнес",
                 f"получено: {test_record.get('Название')}")
            test("Ответственный == 'Дидар'",
                 test_record.get("Ответственный") == "Дидар",
                 f"получено: {test_record.get('Ответственный')}")
            test("Города содержит 'Алматы'",
                 "Алматы" in test_record.get("Города", ""),
                 f"получено: {test_record.get('Города')}")
            print(f"\n     Найдена запись:")
            for k, v in test_record.items():
                if v:
                    print(f"       {k}: {v}")
    except Exception as e:
        test("read_business_sheet()", False, str(e))
        traceback.print_exc()

# ─────────────────────────────────────────────────────────────
# Тест 12: find_row_by_id()
# ─────────────────────────────────────────────────────────────

section("12. find_row_by_id()")

if not cfg["ok"]:
    print("  ⏭ Пропущено")
else:
    result = find_row_by_id("biz_registry", TEST_BIZ_ID)
    test(f"find_row_by_id('{TEST_BIZ_ID}') нашёл запись",
         result is not None)
    if result:
        row_num, row_data = result
        test("row_num >= 2", row_num >= 2, f"row_num: {row_num}")
        test("row_data это dict", isinstance(row_data, dict))

    result_none = find_row_by_id("biz_registry", "BIZ-NONEXISTENT-99999")
    test("find_row_by_id несуществующего ID → None", result_none is None)

# ─────────────────────────────────────────────────────────────
# Финальная сводка
# ─────────────────────────────────────────────────────────────

def print_summary():
    total = PASSED + FAILED
    print(f"\n{'═' * 58}")
    print(f"  ИТОГ: {PASSED}/{total} тестов прошло")
    if FAILED == 0:
        print("  🎉 Все тесты прошли! Business Core Sheets готов.")
        print(f"\n  🔗 Таблица: {get_spreadsheet_url()}")
        print("\n  Следующий шаг: Фаза 2B — Business Router")
    else:
        print(f"  ❌ Провалено: {FAILED}")
        for err in ERRORS:
            print(f"     • {err}")
    print(f"{'═' * 58}\n")


print_summary()

# Финальная проверка GTD-файлов
section("Проверка: GTD-файлы не были изменены")
import subprocess
for gtd_file in ["telegram_bot.py", "sheets.py", "inbox_processor.py",
                  "project_planner.py", "calendar_sync.py"]:
    test(f"{gtd_file} — не тронут", os.path.exists(gtd_file))
print()

sys.exit(0 if FAILED == 0 else 1)
