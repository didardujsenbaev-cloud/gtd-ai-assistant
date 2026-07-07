"""
Тесты для business_core/roadmap_manager.py (Фаза 2C).

Работает полностью БЕЗ сети, БЕЗ Google Sheets, БЕЗ Telegram.

Запуск: python3 test_roadmap_manager.py
"""

import sys
import traceback
from datetime import date, timedelta

PASSED = 0
FAILED = 0
ERRORS = []


def pytest_approx(expected, rel=0.05):
    """Простая замена pytest.approx для проверки чисел с допуском."""
    class Approx:
        def __eq__(self, actual):
            return abs(actual - expected) <= abs(expected * rel)
    return Approx()


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

section("1. Импорт business_core.roadmap_manager")

try:
    from business_core.roadmap_manager import (
        Roadmap, RoadmapStage,
        create_roadmap, update_stage_status, advance_stage,
        start_roadmap, complete_roadmap,
        get_stage_template, get_next_gtd_action,
        get_overdue_roadmaps, get_blocked_roadmaps,
        get_active_roadmaps, get_roadmaps_by_client,
        get_roadmaps_by_business, get_roadmap_stats,
        format_roadmap_card, format_roadmap_list, format_roadmap_digest,
        STAGE_STATUSES, ROADMAP_STATUSES, STATUS_ICONS,
        SERVICE_STAGE_TEMPLATES, SERVICE_ID_TO_TEMPLATE,
    )
    test("import roadmap_manager — все функции", True)
except Exception as e:
    test("import roadmap_manager", False, str(e))
    traceback.print_exc()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Тест 2: Константы
# ─────────────────────────────────────────────────────────────

section("2. Константы и структуры")

test("STAGE_STATUSES содержит 5 статусов", len(STAGE_STATUSES) == 5)
for s in ("not_started", "in_progress", "waiting", "blocked", "done"):
    test(f"STAGE_STATUSES включает '{s}'", s in STAGE_STATUSES)

test("ROADMAP_STATUSES содержит 4 статуса", len(ROADMAP_STATUSES) == 4)
test("STATUS_ICONS не пустой", len(STATUS_ICONS) > 0)
test("SERVICE_STAGE_TEMPLATES содержит шаблоны", len(SERVICE_STAGE_TEMPLATES) >= 5)
test("default шаблон существует", "default" in SERVICE_STAGE_TEMPLATES)
test("legalization_house шаблон содержит 10 этапов",
     len(SERVICE_STAGE_TEMPLATES.get("legalization_house", [])) == 10)
test("legalization_garage шаблон содержит 6 этапов",
     len(SERVICE_STAGE_TEMPLATES.get("legalization_garage", [])) == 6)
test("visa_tourist шаблон содержит 6 этапов",
     len(SERVICE_STAGE_TEMPLATES.get("visa_tourist", [])) == 6)
test("coaching_strategy шаблон содержит 6 этапов",
     len(SERVICE_STAGE_TEMPLATES.get("coaching_strategy", [])) == 6)


# ─────────────────────────────────────────────────────────────
# Тест 3: get_stage_template()
# ─────────────────────────────────────────────────────────────

section("3. get_stage_template() — выбор шаблона")

t1 = get_stage_template("SVC-001")  # гараж
test("SVC-001 → legalization_garage (6 этапов)",
     len(t1) == 6, f"получено: {len(t1)}")
test("SVC-001 этап 1 — Диагностика кейса",
     t1[0]["name"] == "Диагностика кейса", f"получено: {t1[0]['name']}")

t2 = get_stage_template("SVC-002")  # частный дом
test("SVC-002 → legalization_house (10 этапов)",
     len(t2) == 10, f"получено: {len(t2)}")
test("SVC-002 содержит этап Техпаспорт",
     any(s["name"] == "Техпаспорт" for s in t2))
test("SVC-002 содержит этап Акт ввода",
     any(s["name"] == "Акт ввода" for s in t2))
test("SVC-002 содержит этап Регистрация",
     any(s["name"] == "Регистрация" for s in t2))

t3 = get_stage_template("SVC-004")  # туристическая виза
test("SVC-004 → visa_tourist", len(t3) == 6, f"получено: {len(t3)}")

t4 = get_stage_template("SVC-006")  # коучинг
test("SVC-006 → coaching_strategy", len(t4) == 6, f"получено: {len(t4)}")

# По названию (без ID)
t5 = get_stage_template("", "Узаконение частного дома")
test("По названию 'Узаконение частного дома' → 10 этапов",
     len(t5) == 10, f"получено: {len(t5)}")

t6 = get_stage_template("", "Стратегическая коучинг сессия")
test("По названию 'коучинг' → coaching_strategy",
     len(t6) == 6, f"получено: {len(t6)}")

t7 = get_stage_template("UNKNOWN-999", "Непонятная услуга")
test("Неизвестная услуга → default шаблон",
     len(t7) == 5, f"получено: {len(t7)}")


# ─────────────────────────────────────────────────────────────
# Тест 4: RoadmapStage dataclass
# ─────────────────────────────────────────────────────────────

section("4. RoadmapStage dataclass")

stage = RoadmapStage(
    stage_id="STAGE-001-01",
    roadmap_id="RM-001",
    order=1,
    name="Диагностика кейса",
    docs_required=["Удостоверение", "Документы на землю"],
)

test("RoadmapStage создаётся", stage is not None)
test("stage_id == STAGE-001-01", stage.stage_id == "STAGE-001-01")
test("status по умолчанию == not_started", stage.status == "not_started")
test("is_done() == False по умолчанию", not stage.is_done())
test("is_active() == False по умолчанию", not stage.is_active())
test("docs_required список", isinstance(stage.docs_required, list))
test("docs_required содержит элементы", len(stage.docs_required) == 2)

stage.status = "in_progress"
test("после in_progress: is_active() == True", stage.is_active())
test("после in_progress: is_done() == False", not stage.is_done())

stage.status = "done"
test("после done: is_done() == True", stage.is_done())

# Просроченность
overdue_stage = RoadmapStage(
    stage_id="STAGE-001-02", roadmap_id="RM-001", order=2,
    name="Сбор документов", status="in_progress",
    due_date=(date.today() - timedelta(days=5)).isoformat(),
)
test("просроченный этап: is_overdue() == True", overdue_stage.is_overdue())

future_stage = RoadmapStage(
    stage_id="STAGE-001-03", roadmap_id="RM-001", order=3,
    name="АПЗ", status="in_progress",
    due_date=(date.today() + timedelta(days=10)).isoformat(),
)
test("будущий этап: is_overdue() == False", not future_stage.is_overdue())

done_overdue = RoadmapStage(
    stage_id="STAGE-001-04", roadmap_id="RM-001", order=4,
    name="Проект", status="done",
    due_date=(date.today() - timedelta(days=2)).isoformat(),
)
test("done этап: is_overdue() == False (уже выполнен)", not done_overdue.is_overdue())

d = stage.to_dict()
test("to_dict() возвращает dict", isinstance(d, dict))
test("to_dict() содержит stage_id", "stage_id" in d)


# ─────────────────────────────────────────────────────────────
# Тест 5: create_roadmap()
# ─────────────────────────────────────────────────────────────

section("5. create_roadmap() — создание дорожной карты")

rm = create_roadmap(
    business_id="BIZ-001",
    service_id="SVC-002",       # Узаконение частного дома
    client_id="PRS-001",
    client_name="Иванов Александр",
    city="Алматы",
    responsible="Дидар",
    service_name="Узаконение частного дома",
    gtd_project_id="",
    expected_days=60,
    roadmap_id="RM-TEST-001",
)

test("create_roadmap возвращает Roadmap", isinstance(rm, Roadmap))
test("roadmap_id == RM-TEST-001", rm.roadmap_id == "RM-TEST-001")
test("business_id == BIZ-001", rm.business_id == "BIZ-001")
test("service_id == SVC-002", rm.service_id == "SVC-002")
test("client_name == Иванов Александр", rm.client_name == "Иванов Александр")
test("city == Алматы", rm.city == "Алматы")
test("статус active по умолчанию", rm.status == "active")
test("created_at заполнен", bool(rm.created_at))
test("expected_at заполнен", bool(rm.expected_at))
test("stages не пустой", len(rm.stages) > 0)
test("stages == 10 (шаблон частного дома)", len(rm.stages) == 10,
     f"получено: {len(rm.stages)}")
test("все этапы not_started по умолчанию",
     all(s.status == "not_started" for s in rm.stages))
test("stage_id формат STAGE-...", rm.stages[0].stage_id.startswith("STAGE-"))
test("порядок этапов 1..10",
     [s.order for s in rm.stages] == list(range(1, 11)))
test("первый этап — Диагностика кейса",
     rm.stages[0].name == "Диагностика кейса")
test("этап 7 — Техпаспорт",
     rm.stages[6].name == "Техпаспорт", f"получено: {rm.stages[6].name}")

d = rm.to_dict()
test("to_dict() возвращает dict", isinstance(d, dict))
test("to_dict() содержит roadmap_id", "roadmap_id" in d)
test("to_dict() содержит progress_pct", "progress_pct" in d)
test("progress_pct == 0.0 (ничего не сделано)", d["progress_pct"] == 0.0)

# Создание дорожной карты для гаража
rm_garage = create_roadmap(
    business_id="BIZ-001",
    service_id="SVC-001",
    client_id="PRS-002",
    client_name="Петрова Алия",
    city="Астана",
    responsible="Дидар",
    roadmap_id="RM-TEST-002",
)
test("гараж → 6 этапов", len(rm_garage.stages) == 6,
     f"получено: {len(rm_garage.stages)}")


# ─────────────────────────────────────────────────────────────
# Тест 6: Методы Roadmap
# ─────────────────────────────────────────────────────────────

section("6. Roadmap методы — progress, current_stage, overdue")

test("get_progress_pct() == 0.0 изначально",
     rm.get_progress_pct() == 0.0)
test("get_current_stage() — первый этап",
     rm.get_current_stage() == rm.stages[0])
test("is_completed() == False",
     not rm.is_completed())
test("get_done_stages() == [] (ничего не сделано)",
     rm.get_done_stages() == [])

# Добавляем просроченный этап для проверки
rm.stages[1].due_date = (date.today() - timedelta(days=3)).isoformat()
rm.stages[1].status = "in_progress"
overdue = rm.get_overdue_stages()
test("get_overdue_stages() находит просроченный этап",
     len(overdue) == 1, f"найдено: {len(overdue)}")
rm.stages[1].due_date = None    # сброс
rm.stages[1].status = "not_started"  # сброс


# ─────────────────────────────────────────────────────────────
# Тест 7: start_roadmap() и update_stage_status()
# ─────────────────────────────────────────────────────────────

section("7. start_roadmap() и update_stage_status()")

rm = start_roadmap(rm)
test("после start_roadmap: первый этап in_progress",
     rm.stages[0].status == "in_progress")
test("после start_roadmap: второй этап not_started",
     rm.stages[1].status == "not_started")

# Обновить статус первого этапа → done
rm, stage_done = update_stage_status(rm, rm.stages[0].stage_id, "done", "Диагностика проведена")
test("update_stage_status → done", rm.stages[0].status == "done")
test("completed_at заполнен", bool(rm.stages[0].completed_at))
test("notes обновлён", rm.stages[0].notes == "Диагностика проведена")
test("roadmap ещё active (не все done)", rm.status == "active")

# Некорректный статус
try:
    update_stage_status(rm, rm.stages[0].stage_id, "invalid_status")
    test("некорректный статус → ValueError", False)
except ValueError:
    test("некорректный статус → ValueError", True)

# Несуществующий stage_id
try:
    update_stage_status(rm, "STAGE-UNKNOWN", "done")
    test("несуществующий stage_id → ValueError", False)
except ValueError:
    test("несуществующий stage_id → ValueError", True)


# ─────────────────────────────────────────────────────────────
# Тест 8: advance_stage()
# ─────────────────────────────────────────────────────────────

section("8. advance_stage() — переход к следующему этапу")

# Делаем первый этап done (уже сделали выше), второй not_started
rm2 = create_roadmap(
    business_id="BIZ-001",
    service_id="SVC-001",   # гараж (6 этапов)
    client_id="PRS-003",
    client_name="Асель Нурланова",
    city="Шымкент",
    responsible="Дидар",
    roadmap_id="RM-TEST-003",
)
rm2 = start_roadmap(rm2)

# Advance: этап 1 → done, этап 2 → in_progress
rm2, done_s, next_s = advance_stage(rm2, "Диагностика завершена")
test("advance: этап 1 done", rm2.stages[0].status == "done")
test("advance: этап 2 in_progress", rm2.stages[1].status == "in_progress")
test("advance: done_s — Диагностика",
     done_s is not None and "Диагностика" in done_s.name,
     f"получено: {done_s.name if done_s else None}")
test("advance: next_s — Сбор документов",
     next_s is not None and "Сбор" in next_s.name,
     f"получено: {next_s.name if next_s else None}")

# Advance снова
rm2, done2, next2 = advance_stage(rm2)
test("advance x2: этап 2 done", rm2.stages[1].status == "done")
test("advance x2: этап 3 in_progress", rm2.stages[2].status == "in_progress")
test("get_progress_pct() ≈ 33.3% (2/6)",
     rm2.get_progress_pct() == pytest_approx(33.3, rel=0.05),
     f"получено: {rm2.get_progress_pct()}")

print(f"     progress: {rm2.get_progress_pct():.1f}%")


# ─────────────────────────────────────────────────────────────
# Тест 9: complete_roadmap()
# ─────────────────────────────────────────────────────────────

section("9. complete_roadmap() — завершение")

rm3 = create_roadmap(
    business_id="BIZ-001",
    service_id="SVC-001",
    client_id="PRS-001",
    client_name="Иванов",
    city="Алматы",
    responsible="Дидар",
    roadmap_id="RM-TEST-004",
)
rm3 = complete_roadmap(rm3)

test("complete_roadmap: статус completed", rm3.status == "completed")
test("complete_roadmap: все этапы done",
     all(s.status == "done" for s in rm3.stages))
test("complete_roadmap: progress == 100%", rm3.get_progress_pct() == 100.0)
test("complete_roadmap: is_completed() == True", rm3.is_completed())


# ─────────────────────────────────────────────────────────────
# Тест 10: Автозакрытие при последнем этапе
# ─────────────────────────────────────────────────────────────

section("10. Автозакрытие дорожной карты")

rm_short = create_roadmap(
    business_id="BIZ-003",
    service_id="SVC-006",   # коучинг (6 этапов)
    client_id="PRS-005",
    client_name="Алибек",
    city="Онлайн",
    responsible="Дидар",
    roadmap_id="RM-TEST-005",
)
rm_short = start_roadmap(rm_short)

# Завершаем все этапы через advance
for _ in range(len(rm_short.stages)):
    rm_short, _, _ = advance_stage(rm_short)

test("автозакрытие: все этапы done",
     all(s.status == "done" for s in rm_short.stages))
test("автозакрытие: статус completed",
     rm_short.status == "completed",
     f"получено: {rm_short.status}")


# ─────────────────────────────────────────────────────────────
# Тест 11: get_next_gtd_action()
# ─────────────────────────────────────────────────────────────

section("11. get_next_gtd_action() — следующее GTD-действие")

rm_action = create_roadmap(
    business_id="BIZ-001",
    service_id="SVC-002",
    client_id="PRS-001",
    client_name="Иванов Александр",
    city="Алматы",
    responsible="Дидар",
    roadmap_id="RM-TEST-006",
)
rm_action = start_roadmap(rm_action)

action1 = get_next_gtd_action(rm_action)
test("get_next_gtd_action возвращает строку", isinstance(action1, str))
test("действие содержит имя клиента", "Иванов" in action1,
     f"получено: {action1}")
test("действие содержит город", "Алматы" in action1,
     f"получено: {action1}")
test("действие для Диагностики осмысленное",
     len(action1) > 10, f"получено: '{action1}'")
print(f"     Диагностика → {action1}")

# Advance до Техпаспорта (7-й этап, index 6)
for _ in range(6):
    rm_action, _, _ = advance_stage(rm_action)

action7 = get_next_gtd_action(rm_action)
test("действие для Техпаспорта осмысленное",
     len(action7) > 10, f"получено: '{action7}'")
print(f"     Техпаспорт → {action7}")

# Завершённая карта
rm_done = complete_roadmap(create_roadmap(
    "BIZ-001", "SVC-001", "PRS-001", "Иванов", "Алматы", "Дидар",
    roadmap_id="RM-TEST-007"
))
action_done = get_next_gtd_action(rm_done)
test("завершённая карта → действие 'закрыть'",
     "закрыт" in action_done.lower() or "завершен" in action_done.lower(),
     f"получено: '{action_done}'")


# ─────────────────────────────────────────────────────────────
# Тест 12: Аналитика
# ─────────────────────────────────────────────────────────────

section("12. Аналитика — фильтры и статистика")

# Создаём набор дорожных карт
roadmaps_list = [
    create_roadmap("BIZ-001", "SVC-001", "PRS-001", "Иванов", "Алматы",   "Дидар", roadmap_id="RM-A1"),
    create_roadmap("BIZ-001", "SVC-002", "PRS-002", "Петрова", "Астана",  "Дидар", roadmap_id="RM-A2"),
    create_roadmap("BIZ-002", "SVC-004", "PRS-005", "Алибек",  "Алматы",  "Дидар", roadmap_id="RM-A3"),
    complete_roadmap(create_roadmap("BIZ-001", "SVC-001", "PRS-003", "Асель", "Алматы", "Дидар", roadmap_id="RM-A4")),
]

active = get_active_roadmaps(roadmaps_list)
test("get_active_roadmaps: 3 активных", len(active) == 3, f"получено: {len(active)}")

biz1 = get_roadmaps_by_business(roadmaps_list, "BIZ-001")
test("get_roadmaps_by_business BIZ-001: 3 записи",
     len(biz1) == 3, f"получено: {len(biz1)}")

biz2 = get_roadmaps_by_business(roadmaps_list, "BIZ-002")
test("get_roadmaps_by_business BIZ-002: 1 запись",
     len(biz2) == 1, f"получено: {len(biz2)}")

client_rm = get_roadmaps_by_client(roadmaps_list, "PRS-001")
test("get_roadmaps_by_client PRS-001: 1 запись",
     len(client_rm) == 1, f"получено: {len(client_rm)}")

stats = get_roadmap_stats(roadmaps_list)
test("stats: total == 4", stats["total"] == 4)
test("stats: active == 3", stats["active"] == 3)
test("stats: completed == 1", stats["completed"] == 1)
test("stats: avg_progress — число", isinstance(stats["avg_progress"], float))
print(f"     stats: {stats}")

# get_overdue_roadmaps: добавляем просроченный этап
roadmaps_list[0] = start_roadmap(roadmaps_list[0])
roadmaps_list[0].stages[0].due_date = (date.today() - timedelta(days=2)).isoformat()

overdue_list = get_overdue_roadmaps(roadmaps_list)
test("get_overdue_roadmaps: 1 карта с просроченным этапом",
     len(overdue_list) == 1, f"найдено: {len(overdue_list)}")

# get_blocked_roadmaps
roadmaps_list[1].stages[0].status = "blocked"
blocked = get_blocked_roadmaps(roadmaps_list)
test("get_blocked_roadmaps: 1 карта с blocked этапом",
     len(blocked) == 1, f"найдено: {len(blocked)}")


# ─────────────────────────────────────────────────────────────
# Тест 13: Форматирование
# ─────────────────────────────────────────────────────────────

section("13. Форматирование — карточки и дайджест")

rm_fmt = create_roadmap(
    "BIZ-001", "SVC-002", "PRS-001", "Иванов Александр", "Алматы",
    "Дидар", service_name="Узаконение частного дома",
    roadmap_id="RM-FMT-001",
)
rm_fmt = start_roadmap(rm_fmt)

card = format_roadmap_card(rm_fmt)
test("format_roadmap_card возвращает строку", isinstance(card, str))
test("карточка содержит roadmap_id", "RM-FMT-001" in card)
test("карточка содержит имя клиента", "Иванов" in card)
test("карточка содержит город", "Алматы" in card)
test("карточка содержит прогресс-бар", "░" in card or "█" in card)
test("карточка содержит следующее действие", "действие" in card.lower())

card_compact = format_roadmap_card(rm_fmt, compact=True)
test("compact карточка короче полной", len(card_compact) < len(card))
test("compact содержит имя", "Иванов" in card_compact)

lst = format_roadmap_list([rm_fmt, rm_garage])
test("format_roadmap_list возвращает строку", isinstance(lst, str))
test("список содержит 'Дорожные карты'", "Дорожные карты" in lst or "карт" in lst.lower())

empty_list = format_roadmap_list([])
test("пустой список → сообщение", len(empty_list) > 5)

digest = format_roadmap_digest(roadmaps_list)
test("format_roadmap_digest возвращает строку", isinstance(digest, str))
test("дайджест содержит статистику", any(c.isdigit() for c in digest))


# ─────────────────────────────────────────────────────────────
# Тест 14: Изоляция
# ─────────────────────────────────────────────────────────────

section("14. Изоляция — GTD-файлы не импортируются")

import pathlib
source = pathlib.Path("business_core/roadmap_manager.py").read_text()
for forbidden in ["telegram_bot", "inbox_processor", "project_planner",
                  "calendar_sync", "from sheets import", "import sheets\n"]:
    test(
        f"roadmap_manager.py не импортирует '{forbidden}'",
        forbidden not in source,
    )

import os
section("15. GTD-файлы не изменены")
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
    print("  🎉 Все тесты прошли! Roadmap Manager готов.")
    print("\n  Следующий шаг: Фаза 2D — Material Manager")
else:
    print(f"  ❌ Провалено: {FAILED}")
    for err in ERRORS:
        print(f"     • {err}")
print(f"{'═' * 60}\n")

sys.exit(0 if FAILED == 0 else 1)
