"""
Seed: Астана / ИЖС / снос дома или хозпостройки.

Услуга:    SVC-IZH-AST-004 (новая — создаём)
Шаблон:    RMT-IZH-AST-DEMOLITION-001
9 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_astana_demolition.py --dry-run
    python3 business_core/seeds/seed_izhs_astana_demolition.py

Идемпотентность:
    Повторный запуск не создаёт дублей — проверяет по фиксированным ID.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════════

SERVICE_ID   = "SVC-IZH-AST-004"
TEMPLATE_ID  = "RMT-IZH-AST-DEMOLITION-001"
CHECKLIST_ID = "CHK-IZH-AST-DEMOLITION-DOCS-001"
SOP_ID       = "SOP-IZH-AST-DEMOLITION-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    service_name=            "Астана / снос дома / хозпостройки",
    biz_id=                  BIZ_ID,
    service_category=        "demolition",
    city=                    "Астана",
    object_type=             "private_house_izhs",
    client_type=             "physical_person",
    description=             (
        "Сопровождение процедуры сноса жилого дома или хозпостройки "
        "на участке ИЖС в Астане: технический паспорт, техническое обследование, "
        "заключение о сносе, решение архитектуры, акт сноса и регистрация изменений."
    ),
    what_included=           (
        "проверка документов на объект; проверка документов на землю; "
        "проверка технического паспорта; координация технического обследования; "
        "заключение о возможности сноса; получение решения архитектуры на снос; "
        "подготовка акта сноса; регистрация акта сноса / изменений в госорганах; "
        "координация процесса"
    ),
    what_not_included=       (
        "физический демонтаж; вывоз строительного мусора; спецтехника; госпошлины; "
        "оплата технического паспорта; штрафы; "
        "дополнительные согласования, не указанные в договоре"
    ),
    price_from=              "150000",
    currency=                "KZT",
    estimated_duration=      "1-2 месяца",
    required_documents=      (
        "удостоверение личности; документы на объект; документ на земельный участок; "
        "технический паспорт если есть; кадастровый номер; адрес объекта; "
        "фото/видео объекта"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=                   (
        "объект не зарегистрирован; документы неполные; "
        "технический паспорт отсутствует; архитектура может выдать замечания; "
        "фактический снос выполнен до оформления документов; "
        "ошибки при регистрации акта сноса"
    ),
    contractors_needed=      (
        "специалист по техническому обследованию; специалист БТИ/техпаспорт; координатор"
    ),
    status=                  "active",
    notes=                   (
        "Услуга относится только к документальному сопровождению сноса. "
        "Физический демонтаж, вывоз мусора и спецтехника не входят. "
        "Астанинская версия аналогична Алматы, но город указан отдельно "
        "для чистоты Service Catalog."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= "Астана / ИЖС / снос дома или хозпостройки",
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "astana_izhs_demolition",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для сопровождения сноса жилого дома или хозпостройки "
        "на участке ИЖС в Астане."
    ),
    status=        "active",
    notes=         (
        "Финал — акт сноса и регистрация изменений в госорганах / НАО. "
        "Физический снос выполняется клиентом или подрядчиком и не входит в услугу."
    ),
)

# ─── 9 этапов ────────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ объекта на снос",
        description=   (
            "Проверяем, какой объект планируется снести: жилой дом, баня, гараж, "
            "сарай или другая хозпостройка. Определяем, зарегистрирован ли объект "
            "и какие документы есть."
        ),
        required_docs= (
            "удостоверение клиента; документы на объект; документы на землю; "
            "фото/видео объекта; адрес; кадастровый номер"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: объект не зарегистрирован; непонятен статус объекта; "
            "документы неполные"
        ),
    ),
    dict(
        order=2,
        stage_name=    "Проверка документов на объект и землю",
        description=   (
            "Проверяем правоустанавливающие документы на объект и земельный участок, "
            "кадастровый номер и адрес."
        ),
        required_docs= "документы на объект; документ на землю; кадастровый номер; адрес",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: ошибки в документах; неполный пакет; спор по участку или объекту"
        ),
    ),
    dict(
        order=3,
        stage_name=    "Проверка / получение технического паспорта",
        description=   (
            "Проверяем существующий технический паспорт или координируем его "
            "получение/актуализацию, если это нужно для процедуры сноса."
        ),
        required_docs= "документы клиента; документы на объект; доступ к объекту",
        responsible=   "contractor",
        estimated_days="5",
        notes=         (
            "Risks: техпаспорт отсутствует; данные не совпадают с фактом; задержка БТИ"
        ),
    ),
    dict(
        order=4,
        stage_name=    "Техническое обследование объекта",
        description=   "Проводится техническое обследование объекта перед сносом.",
        required_docs= (
            "доступ к объекту; технический паспорт если есть; "
            "документы на объект; фото/видео"
        ),
        responsible=   "contractor",
        estimated_days="5",
        notes=         (
            "Risks: нет доступа к объекту; выявлены несоответствия; "
            "нужны дополнительные данные"
        ),
    ),
    dict(
        order=5,
        stage_name=    "Заключение о возможности сноса",
        description=   (
            "На основании технического обследования готовится заключение "
            "о возможности сноса."
        ),
        required_docs= "техническое обследование; документы на объект",
        responsible=   "contractor",
        estimated_days="3",
        notes=         "Risks: замечания к заключению; нужно доработать обследование",
    ),
    dict(
        order=6,
        stage_name=    "Получение решения архитектуры на снос",
        description=   (
            "Формируем пакет и подаем документы для получения "
            "решения архитектуры на снос."
        ),
        required_docs= (
            "документы клиента; документы на объект; документы на землю; "
            "технический паспорт; заключение о сносе"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         "Risks: замечания архитектуры; отказ; задержка рассмотрения",
    ),
    dict(
        order=7,
        stage_name=    "Фактический снос клиентом / подрядчиком",
        description=   (
            "После получения решения архитектуры клиент или его подрядчик "
            "выполняет фактический снос объекта."
        ),
        required_docs= "решение архитектуры на снос",
        responsible=   "client",
        estimated_days="10",
        notes=         (
            "Risks: клиент снес объект до решения; задержка демонтажа; мусор не вывезен"
        ),
    ),
    dict(
        order=8,
        stage_name=    "Подготовка акта сноса",
        description=   "После фактического сноса готовим акт сноса.",
        required_docs= (
            "решение архитектуры; подтверждение фактического сноса; "
            "документы клиента и объекта"
        ),
        responsible=   "manager",
        estimated_days="3",
        notes=         (
            "Risks: неполный пакет; ошибки в акте; "
            "нужно подтверждение фактического сноса"
        ),
    ),
    dict(
        order=9,
        stage_name=    "Регистрация акта сноса в госорганах / НАО",
        description=   "Регистрируем акт сноса и изменения в госорганах / НАО.",
        required_docs= (
            "акт сноса; документы клиента; документы на объект; документы на землю"
        ),
        responsible=   "manager",
        estimated_days="5",
        notes=         (
            "Risks: замечания НАО/госорганов; ошибки в документах; задержка регистрации"
        ),
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для сноса дома / хозпостройки в Астане",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документы на объект; "
        "Документ на земельный участок; Кадастровый номер; Адрес объекта; "
        "Фото/видео объекта; Технический паспорт если есть; "
        "Техническое обследование; Заключение о сносе; "
        "Решение архитектуры на снос; Акт сноса; "
        "Регистрация акта сноса в госорганах/НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для сноса, получения решения архитектуры, "
        "подготовки акта сноса и регистрации изменений."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=           "Как определить услугу сноса дома / хозпостройки в Астане",
    biz_id=          BIZ_ID,
    service_id=      SERVICE_ID,
    template_id=     TEMPLATE_ID,
    purpose=         (
        "До запуска договора понять, какой объект планируется снести, "
        "зарегистрирован ли он, какие документы есть "
        "и можно ли запускать процедуру сноса."
    ),
    steps=           (
        "1. Уточнить, какой объект клиент хочет снести: дом, баню, гараж, сарай "
        "или другую хозпостройку. "
        "2. Получить документы на объект и землю. "
        "3. Проверить, зарегистрирован ли объект. "
        "4. Проверить наличие технического паспорта. "
        "5. Получить фото/видео объекта. "
        "6. Определить, нужен ли технический паспорт или его актуализация. "
        "7. Организовать техническое обследование. "
        "8. Подготовить заключение о возможности сноса. "
        "9. Подготовить пакет на решение архитектуры. "
        "10. После фактического сноса подготовить акт сноса. "
        "11. Зарегистрировать акт сноса в госорганах/НАО."
    ),
    expected_result= (
        "Выбран шаблон RMT-IZH-AST-DEMOLITION-001 "
        "или выявлены причины, почему объект нельзя вести в работу."
    ),
    owner_role=      "manager",
    status=          "active",
)


# ═══════════════════════════════════════════════════════════════
# Idempotency helpers
# ═══════════════════════════════════════════════════════════════

def _is_quota_error(e: Exception) -> bool:
    return "429" in str(e) or "Quota exceeded" in str(e)


def _service_exists() -> bool:
    try:
        from business_core.service_manager import find_service_by_id
        return find_service_by_id(SERVICE_ID) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_service_exists: quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_service_exists error: {e}")
        return False


def _template_exists() -> bool:
    try:
        from business_core.roadmap_template_manager import find_roadmap_template_by_id
        return find_roadmap_template_by_id(TEMPLATE_ID) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_template_exists: quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_template_exists error: {e}")
        return False


def _stages_count() -> int:
    try:
        from business_core.roadmap_template_manager import find_template_stages
        return len(find_template_stages(TEMPLATE_ID))
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_stages_count: quota — assuming all {len(STAGES)} exist. {e}")
            return len(STAGES)
        log.warning(f"_stages_count error: {e}")
        return 0


def _checklist_exists() -> bool:
    try:
        from business_core.knowledge_manager import find_checklist_by_id
        return find_checklist_by_id(CHECKLIST_ID) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_checklist_exists: quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_checklist_exists error: {e}")
        return False


def _sop_exists() -> bool:
    try:
        from business_core.knowledge_manager import find_sop_by_id
        return find_sop_by_id(SOP_ID) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_sop_exists: quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_sop_exists error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Dry-run preview
# ═══════════════════════════════════════════════════════════════

def dry_run() -> dict:
    plan = []
    skip = []

    if _service_exists():
        skip.append(f"[SKIP] Service {SERVICE_ID} уже существует")
    else:
        plan.append(f"[CREATE] Service {SERVICE_ID}: {SERVICE_DATA['service_name']}")

    if _template_exists():
        skip.append(f"[SKIP] Template {TEMPLATE_ID} уже существует")
    else:
        plan.append(f"[CREATE] Template {TEMPLATE_ID}: {TEMPLATE_DATA['template_name']}")

    existing = _stages_count()
    if existing >= len(STAGES):
        skip.append(f"[SKIP] Stages для {TEMPLATE_ID} уже есть ({existing})")
    else:
        plan.append(
            f"[CREATE] {len(STAGES) - existing} stages для {TEMPLATE_ID} "
            f"(уже есть: {existing})"
        )

    if _checklist_exists():
        skip.append(f"[SKIP] Checklist {CHECKLIST_ID} уже существует")
    else:
        plan.append(f"[CREATE] Checklist {CHECKLIST_ID}: {CHECKLIST_DATA['title']}")

    if _sop_exists():
        skip.append(f"[SKIP] SOP {SOP_ID} уже существует")
    else:
        plan.append(f"[CREATE] SOP {SOP_ID}: {SOP_DATA['title']}")

    return {"plan": plan, "skip": skip}


# ═══════════════════════════════════════════════════════════════
# Live seed
# ═══════════════════════════════════════════════════════════════

def _rename_id_in_sheet(sheet, old_id: str, new_id: str) -> None:
    if old_id == new_id:
        return
    for i, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0].strip() == old_id:
            sheet.update_cell(i, 1, new_id)
            return


def run_seed(verbose: bool = True) -> dict:
    created = []
    skipped = []
    errors  = []

    # ── Service ───────────────────────────────────────────────
    if _service_exists():
        skipped.append(f"Service {SERVICE_ID}")
        if verbose: print(f"  [SKIP] Service {SERVICE_ID}")
    else:
        try:
            from business_core.service_manager import create_service_record
            from business_core.sheets import get_business_sheet
            result = create_service_record(**SERVICE_DATA)
            if result["ok"]:
                sheet = get_business_sheet("service_catalog")
                _rename_id_in_sheet(sheet, result["service_id"], SERVICE_ID)
                created.append(f"Service {SERVICE_ID}")
                if verbose: print(f"  [OK] Service {SERVICE_ID}")
            else:
                errors.append(f"Service: {result['error']}")
                if verbose: print(f"  [ERR] Service: {result['error']}")
        except Exception as e:
            errors.append(f"Service exception: {e}")
            if verbose: print(f"  [ERR] Service exception: {e}")

    # ── Template ──────────────────────────────────────────────
    if _template_exists():
        skipped.append(f"Template {TEMPLATE_ID}")
        if verbose: print(f"  [SKIP] Template {TEMPLATE_ID}")
    else:
        try:
            from business_core.roadmap_template_manager import create_roadmap_template
            from business_core.sheets import get_business_sheet
            result = create_roadmap_template(**TEMPLATE_DATA)
            if result["ok"]:
                sheet = get_business_sheet("roadmap_template_registry")
                _rename_id_in_sheet(sheet, result["template_id"], TEMPLATE_ID)
                created.append(f"Template {TEMPLATE_ID}")
                if verbose: print(f"  [OK] Template {TEMPLATE_ID}")
            else:
                errors.append(f"Template: {result['error']}")
                if verbose: print(f"  [ERR] Template: {result['error']}")
        except Exception as e:
            errors.append(f"Template exception: {e}")
            if verbose: print(f"  [ERR] Template exception: {e}")

    # ── Stages ────────────────────────────────────────────────
    existing_count = _stages_count()
    if existing_count >= len(STAGES):
        skipped.append(f"Stages {TEMPLATE_ID} ({existing_count})")
        if verbose: print(f"  [SKIP] Stages для {TEMPLATE_ID} ({existing_count})")
    else:
        try:
            from business_core.roadmap_template_manager import add_roadmap_template_stage
            stages_to_add = STAGES[existing_count:]
            added = 0
            for s in stages_to_add:
                result = add_roadmap_template_stage(
                    template_id=    TEMPLATE_ID,
                    stage_name=     s["stage_name"],
                    order=          s["order"],
                    description=    s.get("description",    ""),
                    required_docs=  s.get("required_docs",  ""),
                    responsible=    s.get("responsible",    ""),
                    estimated_days= s.get("estimated_days", ""),
                    notes=          s.get("notes",          ""),
                )
                if result["ok"]:
                    added += 1
                else:
                    errors.append(f"Stage {s['order']}: {result['error']}")
            created.append(f"Stages {TEMPLATE_ID} (+{added})")
            if verbose:
                print(f"  [OK] Stages: +{added} (итого {existing_count + added})")
        except Exception as e:
            errors.append(f"Stages exception: {e}")
            if verbose: print(f"  [ERR] Stages exception: {e}")

    # ── Checklist ─────────────────────────────────────────────
    if _checklist_exists():
        skipped.append(f"Checklist {CHECKLIST_ID}")
        if verbose: print(f"  [SKIP] Checklist {CHECKLIST_ID}")
    else:
        try:
            from business_core.knowledge_manager import create_checklist_record
            from business_core.sheets import get_business_sheet
            result = create_checklist_record(**CHECKLIST_DATA)
            if result["ok"]:
                sheet = get_business_sheet("checklist_registry")
                _rename_id_in_sheet(sheet, result["checklist_id"], CHECKLIST_ID)
                created.append(f"Checklist {CHECKLIST_ID}")
                if verbose: print(f"  [OK] Checklist {CHECKLIST_ID}")
            else:
                errors.append(f"Checklist: {result['error']}")
                if verbose: print(f"  [ERR] Checklist: {result['error']}")
        except Exception as e:
            errors.append(f"Checklist exception: {e}")
            if verbose: print(f"  [ERR] Checklist exception: {e}")

    # ── SOP ───────────────────────────────────────────────────
    if _sop_exists():
        skipped.append(f"SOP {SOP_ID}")
        if verbose: print(f"  [SKIP] SOP {SOP_ID}")
    else:
        try:
            from business_core.knowledge_manager import create_sop_record
            from business_core.sheets import get_business_sheet
            result = create_sop_record(**SOP_DATA)
            if result["ok"]:
                sheet = get_business_sheet("sop_registry")
                _rename_id_in_sheet(sheet, result["sop_id"], SOP_ID)
                created.append(f"SOP {SOP_ID}")
                if verbose: print(f"  [OK] SOP {SOP_ID}")
            else:
                errors.append(f"SOP: {result['error']}")
                if verbose: print(f"  [ERR] SOP: {result['error']}")
        except Exception as e:
            errors.append(f"SOP exception: {e}")
            if verbose: print(f"  [ERR] SOP exception: {e}")

    return {"created": created, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seed: Астана / ИЖС / снос (SVC-IZH-AST-004)")
    print("Template: RMT-IZH-AST-DEMOLITION-001 | 9 этапов")
    print("=" * 60)

    if is_dry_run:
        print("\n[DRY-RUN] — ничего не записывается в Google Sheets\n")
        result = dry_run()
        for line in result["skip"]:
            print(f"  {line}")
        for line in result["plan"]:
            print(f"  {line}")
        print()
        if not result["plan"]:
            print("  Все записи уже существуют. Ничего делать не нужно.")
        return

    result = dry_run()
    print("\nСтатус:")
    for line in result["skip"]:
        print(f"  {line}")

    if result["plan"]:
        print("\nБудет создано:")
        for line in result["plan"]:
            print(f"  {line}")
    else:
        print("\n  Всё уже существует. Ничего делать не нужно.")
        return

    print()
    confirm = input("Type YES to continue: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return

    print("\nЗапись в Google Sheets...\n")
    outcome = run_seed(verbose=True)

    print()
    print(f"Создано:  {len(outcome['created'])} — {', '.join(outcome['created'])}")
    print(f"Пропущено:{len(outcome['skipped'])} — {', '.join(outcome['skipped'])}")
    if outcome["errors"]:
        print(f"Ошибки:   {len(outcome['errors'])}")
        for e in outcome["errors"]:
            print(f"  {e}")
    else:
        print("Ошибок:    нет")
    print("=" * 60)


if __name__ == "__main__":
    main()
