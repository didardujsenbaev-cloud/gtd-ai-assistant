"""
Seed: Астана / ИЖС / отдельно стоящая хозпостройка при существующем доме.

Услуга:    SVC-IZH-AST-003 (новая — создаём)
Шаблон:    RMT-IZH-AST-OUTBUILDING-001
13 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_astana_outbuilding.py --dry-run
    python3 business_core/seeds/seed_izhs_astana_outbuilding.py

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

SERVICE_ID   = "SVC-IZH-AST-003"
TEMPLATE_ID  = "RMT-IZH-AST-OUTBUILDING-001"
CHECKLIST_ID = "CHK-IZH-AST-OUTBUILDING-DOCS-001"
SOP_ID       = "SOP-IZH-AST-OUTBUILDING-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    service_name=            "Астана / хозпостройка при существующем доме",
    biz_id=                  BIZ_ID,
    service_category=        "outbuilding_construction",
    city=                    "Астана",
    object_type=             "private_house_izhs",
    client_type=             "physical_person",
    description=             (
        "Сопровождение строительства или оформления отдельно стоящей хозпостройки "
        "на участке ИЖС в Астане, где уже есть зарегистрированный жилой дом. "
        "К хозпостройкам относятся баня, гараж, сарай, летняя кухня "
        "и другие вспомогательные строения."
    ),
    what_included=           (
        "первичный анализ объекта; проверка существующего зарегистрированного дома; "
        "проверка документов на землю; проверка целевого назначения; "
        "проверка необходимости топосъемки/ПДП/ограничений; договор с клиентом; "
        "задание на проектирование; эскизный проект хозпостройки; получение АПЗ; "
        "сопровождение СМР; исполнительная съемка если требуется; "
        "технический паспорт; акт ввода; регистрация в НАО; координация процесса"
    ),
    what_not_included=       (
        "строительно-монтажные работы; госпошлины; оплата технического паспорта; "
        "нотариальные согласия если потребуются; штрафы; "
        "повторные подачи после существенных изменений; "
        "дополнительные согласования, не указанные в договоре"
    ),
    price_from=              "400000",
    currency=                "KZT",
    estimated_duration=      "2-4 месяца",
    required_documents=      (
        "удостоверение личности; документ на земельный участок; "
        "документы на существующий дом; технический паспорт дома если есть; "
        "кадастровый номер; адрес участка; фото/видео места будущей хозпостройки"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=                   (
        "хозпостройка фактически пристроена к дому и должна идти как реконструкция; "
        "дом не зарегистрирован; целевое назначение земли не подходит; "
        "ограничения участка; замечания архитектуры; отказ/замечания по АПЗ; "
        "СМР выполнены не по согласованной логике; задержки госорганов"
    ),
    contractors_needed=      (
        "проектировщик эскизного проекта; специалист БТИ/техпаспорт; "
        "топограф при необходимости; "
        "специалист по исполнительной съемке при необходимости; координатор"
    ),
    status=                  "active",
    notes=                   (
        "Услуга применяется только для отдельно стоящей хозпостройки "
        "при уже зарегистрированном доме. "
        "Если хозпостройка пристроена к дому, использовать SVC-IZH-AST-001. "
        "Если участок голый и строится новый дом с хозпостройками, "
        "использовать SVC-IZH-AST-002. "
        "АПЗ нужен, но обычно по хозпостройке меньше проблем, "
        "так как основной дом уже зарегистрирован. "
        "Астанинская версия проще Алматы: сейсмостойкость не требуется, "
        "топосъемка/ПДП/регламент используются по ситуации."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= "Астана / ИЖС / отдельно стоящая хозпостройка при существующем доме",
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "astana_izhs_outbuilding_before_smr",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для строительства или оформления отдельно стоящей хозпостройки "
        "на участке ИЖС в Астане, где уже есть зарегистрированный жилой дом."
    ),
    status=        "active",
    notes=         (
        "Если объект пристроен к дому, использовать SVC-IZH-AST-001. "
        "Если участок голый и строится новый дом с хозпостройками, "
        "использовать SVC-IZH-AST-002. "
        "Для отдельно стоящей хозпостройки нужен АПЗ, эскизный проект, "
        "техпаспорт, акт ввода и регистрация в НАО. "
        "Исполнительная съемка используется, если требуется."
    ),
)

# ─── 13 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ: пристроено к дому или отдельно",
        description=   (
            "Проверяем, является ли объект отдельно стоящей хозпостройкой. "
            "Если хозпостройка пристроена к дому, кейс относится к "
            "реконструкции/пристройке SVC-IZH-AST-001."
        ),
        required_docs= (
            "удостоверение клиента; документы на участок; документы на дом; "
            "фото/видео места будущей хозпостройки; адрес; кадастровый номер"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: объект фактически пристроен к дому; "
            "неверная классификация услуги; нужен другой шаблон"
        ),
    ),
    dict(
        order=2,
        stage_name=    "Проверка существующего зарегистрированного дома",
        description=   (
            "Проверяем, что на участке уже есть зарегистрированный жилой дом."
        ),
        required_docs= "документы на дом; техпаспорт дома если есть; документы на участок",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: дом не зарегистрирован; документы неполные; "
            "объект надо вести по другому сценарию"
        ),
    ),
    dict(
        order=3,
        stage_name=    "Проверка документов на землю",
        description=   (
            "Проверяем документы на земельный участок, право собственности/пользования, "
            "адрес и кадастровый номер."
        ),
        required_docs= "документ на земельный участок; кадастровый номер; адрес участка",
        responsible=   "manager",
        estimated_days="1",
        notes=         "Risks: неполные документы; ошибки в документах; спор по участку",
    ),
    dict(
        order=4,
        stage_name=    "Проверка целевого назначения земли",
        description=   (
            "Проверяем, подходит ли целевое назначение земли "
            "для хозпостройки при существующем доме."
        ),
        required_docs= "документ на земельный участок; кадастровый номер",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: целевое назначение не подходит; "
            "требуется изменение назначения"
        ),
    ),
    dict(
        order=5,
        stage_name=    "Проверка необходимости топосъемки / ПДП / ограничений",
        description=   (
            "Для Астаны топосъемка, ПДП/регламент/ситуационная схема проверяются "
            "не всегда, а только если есть спорный участок, ограничения, "
            "сложное расположение, водный объект или требование госоргана."
        ),
        required_docs= (
            "документы на землю; кадастровый номер; адрес участка; "
            "фото/видео места будущей хозпостройки"
        ),
        responsible=   "manager",
        estimated_days="3",
        notes=         (
            "Risks: ограничения участка; красные линии; требование топосъемки; "
            "спорные границы; дополнительные запросы"
        ),
    ),
    dict(
        order=6,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем состав работ, стоимость от 400 000 тг, порядок оплаты, "
            "сроки, риски АПЗ и ответственность клиента по СМР."
        ),
        required_docs= "данные клиента; данные участка; данные существующего дома",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент не понимает риски АПЗ/ограничений; "
            "клиент затягивает оплату"
        ),
    ),
    dict(
        order=7,
        stage_name=    "Задание на проектирование",
        description=   "Формируем задание на проектирование хозпостройки.",
        required_docs= (
            "документы на землю; документы на дом; пожелания клиента; "
            "топосъемка если требуется"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: пожелания клиента не соответствуют ограничениям; "
            "нужно корректировать задание"
        ),
    ),
    dict(
        order=8,
        stage_name=    "Эскизный проект хозпостройки",
        description=   "Готовим эскизный проект хозпостройки.",
        required_docs= (
            "задание на проектирование; документы на землю; "
            "топосъемка если требуется; ограничения если выявлены"
        ),
        responsible=   "contractor",
        estimated_days="7",
        notes=         "Risks: замечания к эскизному проекту; требуется корректировка",
    ),
    dict(
        order=9,
        stage_name=    "Получение АПЗ",
        description=   (
            "Формируем пакет и подаем на получение АПЗ. "
            "Для хозпостройки АПЗ нужен, но обычно меньше проблем, "
            "так как основной дом уже зарегистрирован."
        ),
        required_docs= (
            "эскизный проект; документы клиента; документы на землю; "
            "документы на существующий дом; топосъемка если требуется"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         "Risks: замечания архитектуры; отказ; задержка рассмотрения",
    ),
    dict(
        order=10,
        stage_name=    "Проведение СМР клиентом / подрядчиком",
        description=   (
            "После получения АПЗ клиент или его подрядчик выполняет "
            "строительно-монтажные работы по хозпостройке."
        ),
        required_docs= "АПЗ; эскизный проект",
        responsible=   "client",
        estimated_days="30",
        notes=         (
            "Risks: СМР выполнены не по согласованной логике; "
            "затягивание работ; изменения клиента в процессе строительства"
        ),
    ),
    dict(
        order=11,
        stage_name=    "Исполнительная съемка, если требуется",
        description=   (
            "После завершения СМР выполняется исполнительная съемка, "
            "если она требуется по процедуре или госорганом."
        ),
        required_docs= "завершенные СМР; доступ к участку; адрес; кадастровый номер",
        responsible=   "contractor",
        estimated_days="5",
        notes=         (
            "Risks: нет доступа; выявлены расхождения по факту; "
            "требуется согласование исполнительной съемки"
        ),
    ),
    dict(
        order=12,
        stage_name=    "Технический паспорт",
        description=   (
            "После завершения СМР изготавливается технический паспорт "
            "по фактическому состоянию хозпостройки."
        ),
        required_docs= (
            "завершенные СМР; документы клиента; документы на участок; "
            "документы на дом; доступ к объекту; исполнительная съемка если требуется"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: задержка БТИ; расхождение площадей; "
            "клиент не оплатил услуги/госпошлины"
        ),
    ),
    dict(
        order=13,
        stage_name=    "Подготовка акта ввода и регистрация в НАО",
        description=   (
            "Готовим акт ввода, согласовываем его "
            "и регистрируем изменения в НАО."
        ),
        required_docs= (
            "АПЗ; технический паспорт; документы клиента; документы на участок; "
            "документы на дом; эскизный проект; исполнительная съемка если требуется"
        ),
        responsible=   "manager",
        estimated_days="7",
        notes=         (
            "Risks: неполный пакет; ошибки в документах; замечания; "
            "пересдача; задержка регистрации"
        ),
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для хозпостройки при существующем доме в Астане",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документ на земельный участок; "
        "Документы на существующий дом; Технический паспорт дома если есть; "
        "Кадастровый номер; Адрес участка; Фото/видео места хозпостройки; "
        "Топосъемка если требуется; "
        "ПДП/регламент/ситуационная схема если требуется; "
        "Задание на проектирование; Эскизный проект хозпостройки; "
        "АПЗ; Исполнительная съемка если требуется; "
        "Технический паспорт; Акт ввода; Регистрация в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для строительства/оформления хозпостройки "
        "при существующем доме в Астане, получения АПЗ, проведения СМР, "
        "техпаспорта, акта ввода и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=           "Как определить хозпостройку при существующем доме в Астане",
    biz_id=          BIZ_ID,
    service_id=      SERVICE_ID,
    template_id=     TEMPLATE_ID,
    purpose=         (
        "До запуска договора понять, что объект относится к отдельно стоящей "
        "хозпостройке при уже зарегистрированном доме, а не к реконструкции "
        "или новому строительству дома."
    ),
    steps=           (
        "1. Уточнить, есть ли на участке уже зарегистрированный жилой дом. "
        "2. Уточнить, хозпостройка отдельно стоящая или пристроена к дому. "
        "3. Если пристроена к дому — направить в SVC-IZH-AST-001. "
        "4. Если участок голый и строится новый дом с хозпостройками — "
        "направить в SVC-IZH-AST-002. "
        "5. Получить документы на земельный участок, существующий дом, "
        "адрес и кадастровый номер. "
        "6. Проверить целевое назначение земли. "
        "7. Определить, нужна ли топосъемка. "
        "8. Определить, нужна ли проверка ПДП/регламента/ситуационной схемы. "
        "9. Зафиксировать риски. "
        "10. Выбрать шаблон RMT-IZH-AST-OUTBUILDING-001."
    ),
    expected_result= (
        "Выбран шаблон хозпостройки в Астане "
        "или объект направлен в другую услугу."
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
    print("Seed: Астана / ИЖС / хозпостройка (SVC-IZH-AST-003)")
    print("Template: RMT-IZH-AST-OUTBUILDING-001 | 13 этапов")
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
