"""
Тесты для модуля Business Core (Фаза 1).
Запуск: python3 test_business_core.py
"""

import sys
import traceback
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Вспомогательная инфраструктура тестирования
# ─────────────────────────────────────────────────────────────

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
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


# ─────────────────────────────────────────────────────────────
# Тест 1: Импорт всех модулей
# ─────────────────────────────────────────────────────────────


def _run_tests():
    """Вся логика тестов Phase 1 — вызывается только из __main__
    (Phase 11F.2: unittest discovery/import больше не выполняет
    тесты и не завершает процесс через sys.exit())."""
    section("1. Импорт модулей")

    try:
        import business_core
        test("import business_core", True)
    except Exception as e:
        test("import business_core", False, str(e))
        print(f"\n❌ Критическая ошибка при импорте business_core: {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        from business_core.models import (
            BusinessArea, Service, Person, Channel, Integration, RelationshipTouch
        )
        test("import models (все 6 моделей)", True)
    except Exception as e:
        test("import models", False, str(e))

    try:
        from business_core.business_registry import (
            create_business_record, list_default_businesses, validate_business_record
        )
        test("import business_registry", True)
    except Exception as e:
        test("import business_registry", False, str(e))

    try:
        from business_core.service_catalog import (
            create_service_record, validate_service_record
        )
        test("import service_catalog", True)
    except Exception as e:
        test("import service_catalog", False, str(e))

    try:
        from business_core.people_registry import (
            create_person_record, validate_person_record
        )
        test("import people_registry", True)
    except Exception as e:
        test("import people_registry", False, str(e))

    try:
        from business_core.channel_registry import (
            create_channel_record, validate_channel_record
        )
        test("import channel_registry", True)
    except Exception as e:
        test("import channel_registry", False, str(e))

    try:
        from business_core.integration_registry import (
            create_integration_record, validate_integration_record
        )
        test("import integration_registry", True)
    except Exception as e:
        test("import integration_registry", False, str(e))

    try:
        from business_core.relationship_capital import (
            create_touch_record, suggest_next_touch
        )
        test("import relationship_capital", True)
    except Exception as e:
        test("import relationship_capital", False, str(e))

    try:
        from business_core.business_builder import (
            create_business_area, STANDARD_FOLDERS, STARTER_PROJECTS_TEMPLATE
        )
        test("import business_builder", True)
    except Exception as e:
        test("import business_builder", False, str(e))
        sys.exit(1)


    # ─────────────────────────────────────────────────────────────
    # Тест 2: create_business_area("Узаконение")
    # ─────────────────────────────────────────────────────────────

    section("2. create_business_area('Узаконение')")

    result = create_business_area(
        name="Узаконение",
        cities=["Алматы", "Астана"],
        owner="Дидар",
        priority="high",
        status="active",
        description="Узаконивание объектов недвижимости",
    )

    test("функция возвращает dict", isinstance(result, dict))
    test("ключ 'business' присутствует", "business" in result)
    test("ключ 'folder_structure' присутствует", "folder_structure" in result)
    test("ключ 'starter_projects' присутствует", "starter_projects" in result)
    test("ключ 'gtd_projects_to_create' присутствует", "gtd_projects_to_create" in result)
    test("ключ 'summary' присутствует", "summary" in result)
    test("ключ 'is_valid' присутствует", "is_valid" in result)

    biz = result.get("business")
    test("business — объект BusinessArea", isinstance(biz, BusinessArea))

    if biz:
        test("biz.name == 'Узаконение'", biz.name == "Узаконение", f"got: {biz.name}")
        test("biz.id начинается с 'BIZ-'", biz.id.startswith("BIZ-"), f"got: {biz.id}")
        test("biz.owner == 'Дидар'", biz.owner == "Дидар", f"got: {biz.owner}")
        test("biz.priority == 'high'", biz.priority == "high", f"got: {biz.priority}")
        test("biz.status == 'active'", biz.status == "active", f"got: {biz.status}")
        test(
            "biz.cities содержит Алматы",
            "Алматы" in biz.cities,
            f"got: {biz.cities}",
        )
        test(
            "biz.cities содержит Астана",
            "Астана" in biz.cities,
            f"got: {biz.cities}",
        )
        test("biz.slug не пустой", bool(biz.slug), f"got: '{biz.slug}'")
        test("biz.created_at не пустой", bool(biz.created_at))


    # ─────────────────────────────────────────────────────────────
    # Тест 3: 12 стандартных папок
    # ─────────────────────────────────────────────────────────────

    section("3. Структура папок (12 стандартных)")

    folders = result.get("folder_structure", [])
    test("папок ровно 12", len(folders) == 12, f"найдено: {len(folders)}")

    expected_folders = [
        "01 Стратегия",
        "02 Услуги",
        "03 Процессы",
        "04 Маркетинг",
        "05 Продажи",
        "06 Клиенты",
        "07 Производство",
        "08 Финансы",
        "09 Команда",
        "10 Автоматизация",
        "11 Аналитика",
        "12 Архив",
    ]
    for folder in expected_folders:
        test(f"папка '{folder}' существует", folder in folders)


    # ─────────────────────────────────────────────────────────────
    # Тест 4: Стартовые проекты
    # ─────────────────────────────────────────────────────────────

    section("4. Стартовые проекты")

    projects = result.get("starter_projects", [])
    test("стартовых проектов ровно 7", len(projects) == 7, f"найдено: {len(projects)}")

    expected_project_names = [
        "Описать услуги направления",
        "Собрать текущих клиентов",
        "Описать процесс продаж",
        "Описать процесс производства",
        "Настроить автоматизацию направления",
        "Создать базу знаний направления",
        "Настроить финансовый учёт направления",
    ]

    for proj_name in expected_project_names:
        found = any(proj_name in p.get("name", "") for p in projects)
        test(f"проект '{proj_name[:35]}...' найден", found)

    for i, proj in enumerate(projects):
        test(
            f"проект #{i+1} имеет поле 'outcome'",
            bool(proj.get("outcome")),
            f"проект: {proj.get('name', '?')}",
        )
        test(
            f"проект #{i+1} имеет поле 'business_id'",
            bool(proj.get("business_id")),
        )


    # ─────────────────────────────────────────────────────────────
    # Тест 5: Next Actions
    # ─────────────────────────────────────────────────────────────

    section("5. Next Actions в проектах")

    actions_count = sum(1 for p in projects if p.get("first_action"))
    test(
        "все 7 проектов имеют first_action",
        actions_count == 7,
        f"найдено с first_action: {actions_count}",
    )

    for i, proj in enumerate(projects):
        action = proj.get("first_action", "")
        test(
            f"проект #{i+1}: first_action не пустой",
            bool(action),
            f"проект: {proj.get('name', '?')}",
        )

    # GTD-проекты (для будущей записи в Sheets)
    gtd_projects = result.get("gtd_projects_to_create", [])
    test(
        "gtd_projects_to_create содержит 8 записей (1 главный + 7)",
        len(gtd_projects) == 8,
        f"найдено: {len(gtd_projects)}",
    )

    for proj in gtd_projects:
        test(
            f"GTD-проект '{proj.get('name', '?')[:35]}' имеет first_action",
            bool(proj.get("first_action")),
        )


    # ─────────────────────────────────────────────────────────────
    # Тест 6: validate_business_record()
    # ─────────────────────────────────────────────────────────────

    section("6. validate_business_record()")

    from business_core.business_registry import validate_business_record

    # Корректный бизнес
    biz_valid = biz
    is_valid, errors = validate_business_record(biz_valid)
    test("корректный бизнес — is_valid == True", is_valid, f"ошибки: {errors}")
    test("корректный бизнес — errors пустой", errors == [], f"ошибки: {errors}")

    # Некорректный: нет имени
    from business_core.models import BusinessArea as BA
    bad_biz = BA(id="BIZ-999", name="", slug="test", cities=["Алматы"])
    is_valid_bad, errors_bad = validate_business_record(bad_biz)
    test("бизнес без имени — is_valid == False", not is_valid_bad)
    test("бизнес без имени — есть ошибки", len(errors_bad) > 0, f"ошибки: {errors_bad}")

    # Некорректный: неверный статус
    bad_status_biz = BA(id="BIZ-998", name="Тест", slug="test", status="unknown", cities=["Алматы"])
    is_valid_status, errors_status = validate_business_record(bad_status_biz)
    test("бизнес с неверным статусом — is_valid == False", not is_valid_status)

    # Некорректный: неверный формат ID
    bad_id_biz = BA(id="WRONG-001", name="Тест", slug="test", cities=["Алматы"])
    is_valid_id, errors_id = validate_business_record(bad_id_biz)
    test("бизнес с неверным ID — is_valid == False", not is_valid_id)

    # dict-запись тоже работает
    dict_record = {"id": "BIZ-001", "name": "Тест", "status": "active", "priority": "high", "cities": ["Алматы"]}
    is_valid_dict, _ = validate_business_record(dict_record)
    test("validate принимает dict", is_valid_dict)


    # ─────────────────────────────────────────────────────────────
    # Тест 7: Service Catalog
    # ─────────────────────────────────────────────────────────────

    section("7. Service Catalog")

    from business_core.service_catalog import create_service_record, validate_service_record

    svc = create_service_record(
        business_id="BIZ-001",
        name="Узаконивание гаража",
        city="Алматы",
        price_min=180000,
        price_max=250000,
        duration_days="30–45 дней",
        stages=["Выезд и обмеры", "Технический паспорт", "Подача в ЦОН"],
        docs_from_client=["Удостоверение личности", "Правоустанавливающий документ"],
        risks=["Самовольное строительство", "Долги по земле"],
    )

    test("create_service_record возвращает Service", isinstance(svc, Service))
    test("svc.id начинается с 'SVC-'", svc.id.startswith("SVC-"))
    test("svc.business_id == 'BIZ-001'", svc.business_id == "BIZ-001")
    test("svc.price_min == 180000", svc.price_min == 180000)
    test("svc.stages содержит 3 этапа", len(svc.stages) == 3)

    is_valid_svc, svc_errors = validate_service_record(svc)
    test("validate_service_record: корректная запись", is_valid_svc, f"ошибки: {svc_errors}")

    # Некорректная запись
    bad_svc = Service(id="WRONG", business_id="", name="")
    is_valid_bad_svc, bad_svc_errors = validate_service_record(bad_svc)
    test("validate_service_record: некорректная запись → False", not is_valid_bad_svc)
    test("validate_service_record: есть ошибки", len(bad_svc_errors) > 0)


    # ─────────────────────────────────────────────────────────────
    # Тест 8: People Registry
    # ─────────────────────────────────────────────────────────────

    section("8. People Registry")

    from business_core.people_registry import create_person_record, validate_person_record

    person = create_person_record(
        full_name="Асель Нурланова",
        phone="+7 777 123 4567",
        city="Алматы",
        person_type="сотрудник",
        businesses=["BIZ-001"],
        trust_level=5,
    )

    test("create_person_record возвращает Person", isinstance(person, Person))
    test("person.id начинается с 'PRS-'", person.id.startswith("PRS-"))
    test("person.full_name корректное", person.full_name == "Асель Нурланова")
    test("person.short_name == 'Асель'", person.short_name == "Асель")
    test("person.trust_level == 5", person.trust_level == 5)
    test("person.businesses содержит BIZ-001", "BIZ-001" in person.businesses)

    is_valid_person, person_errors = validate_person_record(person)
    test("validate_person_record: корректная запись", is_valid_person, f"ошибки: {person_errors}")

    bad_person = Person(id="WRONG", full_name="", trust_level=10)
    is_valid_bad_p, _ = validate_person_record(bad_person)
    test("validate_person_record: некорректная запись → False", not is_valid_bad_p)


    # ─────────────────────────────────────────────────────────────
    # Тест 9: Channel Registry
    # ─────────────────────────────────────────────────────────────

    section("9. Channel Registry")

    from business_core.channel_registry import create_channel_record, validate_channel_record

    ch = create_channel_record(
        channel_type="WABA",
        business_id="BIZ-001",
        account="+7 700 000 0000",
        purpose="Входящие заявки клиентов",
        owner="Дидар",
    )

    test("create_channel_record возвращает Channel", isinstance(ch, Channel))
    test("ch.id начинается с 'CH-'", ch.id.startswith("CH-"))
    test("ch.channel_type == 'WABA'", ch.channel_type == "WABA")

    is_valid_ch, ch_errors = validate_channel_record(ch)
    test("validate_channel_record: корректная запись", is_valid_ch, f"ошибки: {ch_errors}")

    bad_ch = Channel(id="WRONG", channel_type="НеизвестныйТип", business_id="")
    is_valid_bad_ch, _ = validate_channel_record(bad_ch)
    test("validate_channel_record: некорректная запись → False", not is_valid_bad_ch)


    # ─────────────────────────────────────────────────────────────
    # Тест 10: Integration Registry
    # ─────────────────────────────────────────────────────────────

    section("10. Integration Registry")

    from business_core.integration_registry import (
        create_integration_record, validate_integration_record, list_default_integrations
    )

    intg = create_integration_record(
        service_a="Binotel",
        service_b="SendPulse",
        description="Звонки из Binotel → контакты в SendPulse",
        integration_type="Webhook",
        env_keys=["BINOTEL_API_KEY", "SENDPULSE_API_KEY"],
        status="planned",
    )

    test("create_integration_record возвращает Integration", isinstance(intg, Integration))
    test("intg.id начинается с 'INT-'", intg.id.startswith("INT-"))
    test("intg.service_a == 'Binotel'", intg.service_a == "Binotel")
    test("intg.env_keys содержит 2 ключа", len(intg.env_keys) == 2)

    is_valid_intg, intg_errors = validate_integration_record(intg)
    test("validate_integration_record: корректная запись", is_valid_intg, f"ошибки: {intg_errors}")

    defaults = list_default_integrations()
    test("list_default_integrations возвращает 5 записей", len(defaults) == 5, f"найдено: {len(defaults)}")
    test("первая интеграция: Telegram Bot ↔ Google Sheets", defaults[0].service_b == "Google Sheets")


    # ─────────────────────────────────────────────────────────────
    # Тест 11: Relationship Capital
    # ─────────────────────────────────────────────────────────────

    section("11. Relationship Capital")

    from business_core.relationship_capital import create_touch_record, suggest_next_touch

    touch = create_touch_record(
        person_id="PRS-001",
        touch_type="звонок",
        channel="Phone",
        summary="Обсудили условия договора",
        outcome="Встреча на следующей неделе",
        warmth_before=6,
        warmth_after=8,
    )

    test("create_touch_record возвращает RelationshipTouch", isinstance(touch, RelationshipTouch))
    test("touch.id начинается с 'TCH-'", touch.id.startswith("TCH-"))
    test("touch.person_id == 'PRS-001'", touch.person_id == "PRS-001")
    test("touch.warmth_after == 8", touch.warmth_after == 8)
    test("touch.touch_date не пустой", bool(touch.touch_date))

    # suggest_next_touch
    person_hot = Person(
        id="PRS-001",
        full_name="Сарсен Тест",
        relationship_status="hot",
        warmth=9,
        last_contact_date="2026-01-01",
    )
    suggestion = suggest_next_touch(person_hot)
    test("suggest_next_touch возвращает dict", isinstance(suggestion, dict))
    test("suggestion содержит 'touch_type'", "touch_type" in suggestion)
    test("suggestion содержит 'suggested_date'", "suggested_date" in suggestion)
    test("suggestion содержит 'priority'", "priority" in suggestion)
    test(
        "горячий контакт без касания → priority high",
        suggestion.get("priority") == "high",
        f"got: {suggestion.get('priority')}",
    )

    # День рождения
    from datetime import date
    today = date.today()
    person_bday = Person(
        id="PRS-002",
        full_name="Бирлик Тест",
        birthday=today.strftime("%m-%d"),
        relationship_status="warm",
        warmth=7,
    )
    bday_suggestion = suggest_next_touch(person_bday)
    test(
        "именинник сегодня → touch_type 'поздравление'",
        bday_suggestion.get("touch_type") == "поздравление",
        f"got: {bday_suggestion.get('touch_type')}",
    )
    test(
        "именинник сегодня → priority 'high'",
        bday_suggestion.get("priority") == "high",
    )


    # ─────────────────────────────────────────────────────────────
    # Тест 12: list_default_businesses()
    # ─────────────────────────────────────────────────────────────

    section("12. list_default_businesses()")

    from business_core.business_registry import list_default_businesses

    defaults = list_default_businesses()
    test("возвращает список", isinstance(defaults, list))
    test("содержит 5 бизнесов", len(defaults) == 5, f"найдено: {len(defaults)}")

    biz_ids = [b.id for b in defaults]
    test("BIZ-001 присутствует", "BIZ-001" in biz_ids)
    test("BIZ-005 присутствует", "BIZ-005" in biz_ids)

    active = [b for b in defaults if b.status == "active"]
    test("активных бизнесов 3", len(active) == 3, f"найдено: {len(active)}")

    for biz_item in defaults:
        is_v, errs = validate_business_record(biz_item)
        test(f"validate [{biz_item.id}] {biz_item.name[:20]}", is_v, f"ошибки: {errs}")


    # ─────────────────────────────────────────────────────────────
    # Тест 13: to_dict() для всех моделей
    # ─────────────────────────────────────────────────────────────

    section("13. to_dict() у всех моделей")

    test("BusinessArea.to_dict() возвращает dict", isinstance(biz.to_dict(), dict))
    test("Service.to_dict() возвращает dict", isinstance(svc.to_dict(), dict))
    test("Person.to_dict() возвращает dict", isinstance(person.to_dict(), dict))
    test("Channel.to_dict() возвращает dict", isinstance(ch.to_dict(), dict))
    test("Integration.to_dict() возвращает dict", isinstance(intg.to_dict(), dict))
    test("RelationshipTouch.to_dict() возвращает dict", isinstance(touch.to_dict(), dict))


    # ─────────────────────────────────────────────────────────────
    # Тест 14: GTD файлы не импортируются из business_core
    # ─────────────────────────────────────────────────────────────

    section("14. Изоляция — GTD файлы не импортируются")

    import ast
    import os

    bc_dir = os.path.join(os.path.dirname(__file__), "business_core")
    forbidden_imports = ["telegram_bot", "sheets", "calendar_sync", "inbox_processor", "project_planner"]

    for fname in os.listdir(bc_dir):
        if not fname.endswith(".py") or fname == "__init__.py":
            continue
        fpath = os.path.join(bc_dir, fname)
        with open(fpath) as f:
            source = f.read()
        for forbidden in forbidden_imports:
            found = False
            try:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        if isinstance(node, ast.ImportFrom) and node.module:
                            # Точное совпадение с модулем верхнего уровня:
                            # "from sheets import ..."      → node.module == "sheets"         → запрещено
                            # "from business_core.sheets import ..." → node.module == "business_core.sheets" → разрешено
                            top_module = node.module.split(".")[0]
                            if top_module == forbidden:
                                found = True
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                top_module = alias.name.split(".")[0]
                                if top_module == forbidden:
                                    found = True
            except SyntaxError:
                pass
            test(
                f"{fname} не импортирует '{forbidden}'",
                not found,
                f"файл импортирует запрещённый модуль: {forbidden}",
            )


    # ─────────────────────────────────────────────────────────────
    # Итог
    # ─────────────────────────────────────────────────────────────

    total = PASSED + FAILED
    print(f"\n{'═' * 55}")
    print(f"  ИТОГ: {PASSED}/{total} тестов прошло")
    if FAILED == 0:
        print(f"  🎉 Все тесты прошли успешно!")
    else:
        print(f"  ❌ Провалено: {FAILED}")
        for err in ERRORS:
            print(f"     • {err}")
    print(f"{'═' * 55}\n")

    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    _run_tests()
