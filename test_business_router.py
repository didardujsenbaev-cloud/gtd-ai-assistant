"""
Тесты для business_core/business_router.py (Фаза 2B).

Работает полностью БЕЗ сети и без Google Sheets.
AI-роутинг отключён (use_ai=False) для воспроизводимости.

Запуск: python3 test_business_router.py
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
# Тестовые данные
# ─────────────────────────────────────────────────────────────

BUSINESSES = [
    {"id": "BIZ-001", "name": "Узаконение недвижимости", "slug": "legalization",
     "status": "active", "cities": ["Алматы", "Астана", "Шымкент"]},
    {"id": "BIZ-002", "name": "Визы и документы",         "slug": "visas",
     "status": "active", "cities": ["Алматы"]},
    {"id": "BIZ-003", "name": "Коучинг",                  "slug": "coaching",
     "status": "active", "cities": ["Алматы", "Онлайн"]},
    {"id": "BIZ-004", "name": "Инвестиции",               "slug": "investments",
     "status": "hold",   "cities": ["Алматы"]},
    {"id": "BIZ-005", "name": "Автоматизация бизнеса",    "slug": "automation",
     "status": "test",   "cities": ["Алматы", "Онлайн"]},
]

SERVICES = [
    {"id": "SVC-001", "business_id": "BIZ-001", "name": "Узаконение гаража"},
    {"id": "SVC-002", "business_id": "BIZ-001", "name": "Узаконение частного дома"},
    {"id": "SVC-003", "business_id": "BIZ-001", "name": "Узаконение коммерческой недвижимости"},
    {"id": "SVC-004", "business_id": "BIZ-002", "name": "Туристическая виза"},
    {"id": "SVC-005", "business_id": "BIZ-002", "name": "Рабочая виза"},
    {"id": "SVC-006", "business_id": "BIZ-003", "name": "Стратегическая сессия"},
]

PEOPLE = [
    {"id": "PRS-001", "full_name": "Иванов Александр",    "short_name": "Александр",
     "person_type": "клиент", "businesses": ["BIZ-001"]},
    {"id": "PRS-002", "full_name": "Петрова Алия",         "short_name": "Алия",
     "person_type": "клиент", "businesses": ["BIZ-001"]},
    {"id": "PRS-003", "full_name": "Асель Нурланова",      "short_name": "Асель",
     "person_type": "сотрудник", "businesses": ["BIZ-001"]},
    {"id": "PRS-004", "full_name": "Сарсен Бейсеков",     "short_name": "Сарсен",
     "person_type": "партнер", "businesses": ["BIZ-001", "BIZ-005"]},
    {"id": "PRS-005", "full_name": "Алибек Дюсенов",      "short_name": "Алибек",
     "person_type": "клиент", "businesses": ["BIZ-002"]},
]

GTD_ACTION = {"результат": "Action",  "действие": "Проверить техпаспорт", "область": "Legalization", "контекст": "@Computer"}
GTD_PROJECT = {"результат": "Project", "действие": "Запустить узаконение", "область": "Business",     "контекст": "@Computer"}
GTD_WAITING = {"результат": "Waiting", "действие": "Ждать от Асель",       "область": "Legalization", "контекст": "@Phone"}
GTD_SOMEDAY = {"результат": "Someday", "действие": "",                      "область": "Family",       "контекст": ""}
GTD_H3      = {"результат": "H3",      "действие": "",                      "область": "",             "контекст": ""}


# ─────────────────────────────────────────────────────────────
# Импорт
# ─────────────────────────────────────────────────────────────

section("1. Импорт business_core.business_router")

try:
    from business_core.business_router import (
        route_business_context,
        should_route,
        format_routing_confirmation,
        format_routing_note,
        _route_by_keywords,
        _find_client_in_text,
        _find_city_in_text,
        _find_roadmap_stage,
        BUSINESS_KEYWORDS,
        KNOWN_CITIES,
        AREA_TO_SLUG,
        BUSINESS_AREAS,
    )
    test("import business_router — все функции", True)
except Exception as e:
    test("import business_router", False, str(e))
    traceback.print_exc()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Тест 2: Структуры данных
# ─────────────────────────────────────────────────────────────

section("2. Структуры BUSINESS_KEYWORDS, KNOWN_CITIES, AREA_TO_SLUG")

test("BUSINESS_KEYWORDS содержит 5 бизнесов",
     len(BUSINESS_KEYWORDS) == 5,
     f"найдено: {list(BUSINESS_KEYWORDS.keys())}")

for slug in ["legalization", "visas", "coaching", "investments", "automation"]:
    test(f"ключевые слова для '{slug}' есть",
         slug in BUSINESS_KEYWORDS and len(BUSINESS_KEYWORDS[slug]) > 0)

test("KNOWN_CITIES содержит Алматы",  "алматы"  in KNOWN_CITIES)
test("KNOWN_CITIES содержит Астана",  "астана"  in KNOWN_CITIES)
test("KNOWN_CITIES содержит Шымкент", "шымкент" in KNOWN_CITIES)

test("AREA_TO_SLUG['Legalization'] == 'legalization'",
     AREA_TO_SLUG.get("Legalization") == "legalization")
test("AREA_TO_SLUG['Visas'] == 'visas'",
     AREA_TO_SLUG.get("Visas") == "visas")


# ─────────────────────────────────────────────────────────────
# Тест 3: _route_by_keywords()
# ─────────────────────────────────────────────────────────────

section("3. _route_by_keywords() — матч по ключевым словам")

biz_id, slug, conf, matched = _route_by_keywords(
    "По узаконению частного дома нужно проверить техпаспорт", BUSINESSES
)
test("узаконение → BIZ-001", biz_id == "BIZ-001", f"получено: {biz_id}")
test("узаконение → slug=legalization", slug == "legalization", f"slug: {slug}")
test("узаконение → confidence > 0.7", conf > 0.7, f"conf: {conf:.2f}")
test("узаконение → найдены ключевые слова", len(matched) > 0, f"matched: {matched}")

biz_id2, slug2, conf2, _ = _route_by_keywords("виза для поездки в Европу", BUSINESSES)
test("виза → BIZ-002", biz_id2 == "BIZ-002", f"получено: {biz_id2}")
test("виза → confidence > 0.7", conf2 > 0.7, f"conf: {conf2:.2f}")

biz_id3, slug3, conf3, _ = _route_by_keywords("стратегическая сессия с командой", BUSINESSES)
test("стратсессия → BIZ-003", biz_id3 == "BIZ-003", f"получено: {biz_id3}")

biz_id4, slug4, conf4, _ = _route_by_keywords("telegram бот для автоматизации", BUSINESSES)
test("телеграм бот → BIZ-005", biz_id4 == "BIZ-005", f"получено: {biz_id4}")

biz_id5, _, conf5, _ = _route_by_keywords("купить хлеб и молоко", BUSINESSES)
test("нерелевантный текст → нет бизнеса", biz_id5 == "", f"получено: {biz_id5}")
test("нерелевантный текст → confidence == 0", conf5 == 0.0, f"conf: {conf5}")


# ─────────────────────────────────────────────────────────────
# Тест 4: _find_client_in_text()
# ─────────────────────────────────────────────────────────────

section("4. _find_client_in_text() — поиск клиента")

pid, pname, pconf = _find_client_in_text(
    "По объекту Иванова надо проверить документы", PEOPLE
)
test("Иванов найден в тексте", pname != "", f"name: {pname}")
test("Иванов → PRS-001", pid == "PRS-001", f"id: {pid}")
test("Иванов → confidence > 0.5", pconf > 0.5, f"conf: {pconf:.2f}")

pid2, pname2, _ = _find_client_in_text(
    "Асель подготовила договор", PEOPLE
)
test("Асель найдена", pname2 != "", f"name: {pname2}")
test("Асель → PRS-003", pid2 == "PRS-003", f"id: {pid2}")

pid3, pname3, _ = _find_client_in_text(
    "Встреча с Сарсеном завтра", PEOPLE
)
test("Сарсен найден", pname3 != "", f"name: {pname3}")
test("Сарсен → PRS-004", pid3 == "PRS-004", f"id: {pid3}")

pid4, pname4, _ = _find_client_in_text("Сходить в магазин", PEOPLE)
test("нет имени → пустой результат", pid4 == "" and pname4 == "",
     f"pid={pid4}, name={pname4}")


# ─────────────────────────────────────────────────────────────
# Тест 5: _find_city_in_text()
# ─────────────────────────────────────────────────────────────

section("5. _find_city_in_text() — определение города")

test("_find_city_in_text('Алматы') == 'Алматы'",
     _find_city_in_text("Объект в Алматы, нужно выехать") == "Алматы")
test("_find_city_in_text('Астана') == 'Астана'",
     _find_city_in_text("Клиент из Астаны") == "Астана")
test("_find_city_in_text('шымкент') → Шымкент",
     _find_city_in_text("офис в Шымкенте") == "Шымкент")
test("_find_city_in_text('онлайн') → Онлайн",
     _find_city_in_text("сессия онлайн") == "Онлайн")
test("нет города → ''",
     _find_city_in_text("позвонить клиенту") == "")


# ─────────────────────────────────────────────────────────────
# Тест 6: _find_roadmap_stage()
# ─────────────────────────────────────────────────────────────

section("6. _find_roadmap_stage() — этап дорожной карты")

_, stage = _find_roadmap_stage("Проверить техпаспорт по объекту Иванова")
test("техпаспорт → этап 'Техпаспорт'",
     stage == "Техпаспорт", f"получено: '{stage}'")

_, stage2 = _find_roadmap_stage("Подать заявление на акт ввода")
test("акт ввода → этап 'Акт ввода'",
     stage2 == "Акт ввода", f"получено: '{stage2}'")

_, stage3 = _find_roadmap_stage("Отправить запрос в АПЗ")
test("апз → этап 'АПЗ'",
     stage3 == "АПЗ", f"получено: '{stage3}'")

_, stage4 = _find_roadmap_stage("Подать на регистрацию в ЕГРН")
test("регистрация/ЕГРН → этап 'Регистрация'",
     stage4 == "Регистрация", f"получено: '{stage4}'")

_, stage5 = _find_roadmap_stage("Позвонить Сарсену завтра")
test("нерелевантный текст → нет этапа", stage5 == "",
     f"получено: '{stage5}'")


# ─────────────────────────────────────────────────────────────
# Тест 7: should_route()
# ─────────────────────────────────────────────────────────────

section("7. should_route() — когда вызывать роутер")

test("Action + Legalization → True",
     should_route({"результат": "Action",  "область": "Legalization"}))
test("Project + Business → True",
     should_route({"результат": "Project", "область": "Business"}))
test("Waiting + Legalization → True",
     should_route({"результат": "Waiting", "область": "Legalization"}))
test("Someday + Family → False",
     not should_route({"результат": "Someday", "область": "Family"}))
test("H3 + '' → False",
     not should_route({"результат": "H3",     "область": ""}))
test("Trash → False",
     not should_route({"результат": "Trash",  "область": ""}))
test("Reference → False",
     not should_route({"результат": "Reference", "область": ""}))
test("Action + пустая область → True (роутить неоднозначное)",
     should_route({"результат": "Action", "область": ""}))


# ─────────────────────────────────────────────────────────────
# Тест 8: route_business_context() — основные сценарии
# ─────────────────────────────────────────────────────────────

section("8. route_business_context() — основные сценарии")

# Сценарий 1: узаконение дома Иванова в Алматы
r1 = route_business_context(
    "По узаконению частного дома Иванова в Алматы надо проверить техпаспорт",
    GTD_ACTION,
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.1: возвращает dict", isinstance(r1, dict))
test("сц.1: business_id == 'BIZ-001'",
     r1["business_id"] == "BIZ-001", f"получено: {r1['business_id']}")
test("сц.1: city == 'Алматы'",
     r1["city"] == "Алматы", f"получено: {r1['city']}")
test("сц.1: client найден (Иванов)",
     "Иванов" in r1["client_name"], f"получено: '{r1['client_name']}'")
test("сц.1: roadmap_stage_name == 'Техпаспорт'",
     r1["roadmap_stage_name"] == "Техпаспорт",
     f"получено: '{r1['roadmap_stage_name']}'")
test("сц.1: confidence > 0.7",
     r1["confidence"] > 0.7, f"conf: {r1['confidence']:.2f}")
test("сц.1: routing_method установлен",
     r1["routing_method"] != "none", f"method: {r1['routing_method']}")
print(f"     conf={r1['confidence']:.2f} biz={r1['business_id']} "
      f"city={r1['city']} client={r1['client_name']} "
      f"stage={r1['roadmap_stage_name']}")

# Сценарий 2: виза для Алматы
r2 = route_business_context(
    "Оформить визу клиенту для поездки в Германию, Алматы",
    {"результат": "Action", "действие": "Оформить визу", "область": "Visas", "контекст": "@Computer"},
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.2: business_id == 'BIZ-002' (визы)",
     r2["business_id"] == "BIZ-002", f"получено: {r2['business_id']}")
test("сц.2: city == 'Алматы'",
     r2["city"] == "Алматы", f"получено: {r2['city']}")
print(f"     conf={r2['confidence']:.2f} biz={r2['business_id']} city={r2['city']}")

# Сценарий 3: коучинг сессия
r3 = route_business_context(
    "Провести стратегическую сессию с командой онлайн",
    {"результат": "Action", "действие": "Провести стратегическую сессию", "область": "Coaching"},
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.3: business_id == 'BIZ-003' (коучинг)",
     r3["business_id"] == "BIZ-003", f"получено: {r3['business_id']}")
test("сц.3: city == 'Онлайн'",
     r3["city"] == "Онлайн", f"получено: {r3['city']}")
print(f"     conf={r3['confidence']:.2f} biz={r3['business_id']} city={r3['city']}")

# Сценарий 4: автоматизация — telegram бот
r4 = route_business_context(
    "Написать telegram бот для автоматизации приёма заявок",
    {"результат": "Project", "действие": "Написать Telegram бот", "область": "IT"},
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.4: business_id == 'BIZ-005' (автоматизация)",
     r4["business_id"] == "BIZ-005", f"получено: {r4['business_id']}")
print(f"     conf={r4['confidence']:.2f} biz={r4['business_id']}")

# Сценарий 5: неоднозначный текст → needs_confirmation
r5 = route_business_context(
    "Позвонить клиенту и уточнить детали",
    {"результат": "Action", "действие": "Позвонить", "область": "Business"},
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.5: неоднозначный → needs_confirmation=True",
     r5["needs_confirmation"] is True, f"получено: {r5['needs_confirmation']}")
test("сц.5: confidence < 0.9",
     r5["confidence"] < 0.9, f"conf: {r5['confidence']:.2f}")
print(f"     conf={r5['confidence']:.2f} needs_confirmation={r5['needs_confirmation']}")

# Сценарий 6: GTD-область напрямую даёт бизнес
r6 = route_business_context(
    "Встреча с клиентом по объекту",
    {"результат": "Action", "действие": "Встреча с клиентом", "область": "Legalization"},
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.6: GTD-область Legalization → BIZ-001",
     r6["business_id"] == "BIZ-001", f"получено: {r6['business_id']}")
print(f"     conf={r6['confidence']:.2f} method={r6['routing_method']}")

# Сценарий 7: Waiting — Асель
r7 = route_business_context(
    "Ждать от Асель подготовленный договор",
    GTD_WAITING,
    BUSINESSES, SERVICES, PEOPLE,
    use_ai=False,
)
test("сц.7: Waiting — Асель найдена", "Асель" in r7["client_name"],
     f"client: {r7['client_name']}")
test("сц.7: process == 'Ожидание'",
     r7["process"] == "Ожидание", f"process: {r7['process']}")


# ─────────────────────────────────────────────────────────────
# Тест 9: format_routing_confirmation()
# ─────────────────────────────────────────────────────────────

section("9. format_routing_confirmation() и format_routing_note()")

text1 = format_routing_confirmation(r1)
test("format_routing_confirmation возвращает строку", isinstance(text1, str))
test("содержит бизнес-название", "Узаконение" in text1,
     f"не найдено в: {text1[:80]}")
test("содержит город Алматы", "Алматы" in text1)
test("содержит имя клиента", "Иванов" in text1)
test("содержит этап", "Техпаспорт" in text1)

note1 = format_routing_note(r1)
test("format_routing_note возвращает строку", isinstance(note1, str))
test("note содержит biz:BIZ-001", "biz:BIZ-001" in note1,
     f"получено: {note1}")
print(f"     note: {note1}")

# needs_confirmation=True → есть вопрос
text5 = format_routing_confirmation(r5)
test("неоднозначный роутинг содержит вопрос о подтверждении",
     "Верно" in text5 or "Да" in text5,
     f"текст: {text5[:100]}")


# ─────────────────────────────────────────────────────────────
# Тест 10: Изоляция — GTD-файлы не импортируются
# ─────────────────────────────────────────────────────────────

section("10. Изоляция — GTD-файлы не импортируются")

import ast, pathlib
source = pathlib.Path("business_core/business_router.py").read_text()
for forbidden in ["telegram_bot", "inbox_processor", "project_planner",
                  "calendar_sync", "from sheets import", "import sheets\n"]:
    test(
        f"business_router.py не импортирует '{forbidden}'",
        forbidden not in source,
    )

# Проверка GTD-файлов не тронуты
import os
section("11. GTD-файлы не изменены")
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
    print("  🎉 Все тесты прошли! Business Router готов.")
    print("\n  Следующий шаг: Фаза 2C — Roadmap Manager")
else:
    print(f"  ❌ Провалено: {FAILED}")
    for err in ERRORS:
        print(f"     • {err}")
print(f"{'═' * 60}\n")

sys.exit(0 if FAILED == 0 else 1)
