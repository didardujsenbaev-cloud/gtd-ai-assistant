"""
Seed: Алматы / ИЖС / отдельно стоящая хозпостройка при существующем доме.

Услуга:    SVC-IZH-003 (новая — создаём)
Шаблон:    RMT-IZH-ALM-OUTBUILDING-001
19 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_almaty_outbuilding.py --dry-run
    python3 business_core/seeds/seed_izhs_almaty_outbuilding.py

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

SERVICE_ID   = "SVC-IZH-003"
TEMPLATE_ID  = "RMT-IZH-ALM-OUTBUILDING-001"
CHECKLIST_ID = "CHK-IZH-ALM-OUTBUILDING-DOCS-001"
SOP_ID       = "SOP-IZH-ALM-OUTBUILDING-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    service_name=            "Строительство / узаконение хозпостройки при существующем доме",
    biz_id=                  BIZ_ID,
    service_category=        "outbuilding_construction",
    city=                    "Алматы",
    object_type=             "private_house_izhs",
    client_type=             "physical_person",
    description=             (
        "Сопровождение строительства или оформления отдельно стоящей хозпостройки "
        "на участке, где уже есть зарегистрированный жилой дом. "
        "К хозпостройкам относятся баня, гараж, сарай, летняя кухня "
        "и другие вспомогательные строения."
    ),
    what_included=           (
        "проверка существующего зарегистрированного дома; проверка документов на землю; "
        "проверка целевого назначения; ПДП/регламент/ситуационная схема при необходимости; "
        "топосъемка; проверка границ; проверка водоохранной зоны при необходимости; "
        "задание на проектирование; эскизный проект хозпостройки; получение АПЗ; "
        "сопровождение после СМР; исполнительная съемка; согласование исполнительной съемки; "
        "технический паспорт; акт ввода; согласование в архитектуре; "
        "регистрация в НАО; координация процесса"
    ),
    what_not_included=       (
        "строительно-монтажные работы; госпошлины; оплата технического паспорта; "
        "нотариальные согласия если потребуются; штрафы; "
        "повторные подачи после существенных изменений; "
        "дополнительные согласования, не указанные в договоре"
    ),
    price_from=              "400000",
    currency=                "KZT",
    estimated_duration=      "3-4 месяца",
    required_documents=      (
        "удостоверение личности; документ на земельный участок; "
        "документы на существующий дом; технический паспорт дома если есть; "
        "кадастровый номер; адрес участка; "
        "фото/видео участка и места будущей хозпостройки"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=                   (
        "хозпостройка фактически пристроена к дому и должна идти как реконструкция; "
        "целевое назначение земли не подходит; ограничения ПДП/регламента; "
        "красные линии; спорные границы; водоохранная зона; "
        "рядом арык/речка/канал; отказ/замечания по АПЗ; "
        "СМР выполнены не по согласованной логике; задержки госорганов"
    ),
    contractors_needed=      (
        "топограф; проектировщик эскизного проекта; "
        "специалист по исполнительной съемке; специалист БТИ/техпаспорт; координатор"
    ),
    status=                  "active",
    notes=                   (
        "Услуга применяется только для отдельно стоящей хозпостройки "
        "при уже зарегистрированном доме. "
        "Если хозпостройка пристроена к дому, использовать SVC-IZH-001 "
        "реконструкция/пристройка/надстройка. "
        "Процедура похожа на новое строительство дома, но дешевле, "
        "потому что основной дом уже зарегистрирован. "
        "АПЗ нужен, но обычно по хозпостройке меньше проблем."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= (
        "Алматы / ИЖС / отдельно стоящая хозпостройка при существующем доме "
        "/ с проведением СМР"
    ),
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "almaty_izhs_outbuilding_before_smr",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для строительства или оформления отдельно стоящей хозпостройки "
        "на участке ИЖС в Алматы, где уже есть зарегистрированный жилой дом."
    ),
    status=        "active",
    notes=         (
        "Если объект пристроен к дому, использовать SVC-IZH-001. "
        "Если участок голый и строится новый дом с хозпостройками, использовать SVC-IZH-002. "
        "Для отдельно стоящей хозпостройки нужен АПЗ, эскизный проект, "
        "исполнительная съемка, техпаспорт, акт ввода и регистрация в НАО."
    ),
)

# ─── 19 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ: пристроено к дому или отдельно",
        description=   (
            "Проверяем, является ли объект отдельно стоящей хозпостройкой. "
            "Если хозпостройка пристроена к дому, кейс относится к "
            "реконструкции/пристройке SVC-IZH-001."
        ),
        required_docs= (
            "удостоверение клиента; документы на участок; документы на дом; "
            "фото/видео места будущей хозпостройки; адрес; кадастровый номер"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: объект фактически пристроен к дому; неверная классификация услуги; "
            "нужен другой шаблон"
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
            "адрес, кадастровый номер."
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
            "Risks: целевое назначение не подходит; требуется изменение назначения"
        ),
    ),
    dict(
        order=5,
        stage_name=    "ПДП / регламент / ситуационная схема при необходимости",
        description=   (
            "Получаем или анализируем сведения по ПДП, регламенту и ситуационной схеме "
            "как единый градостроительный блок, если это требуется "
            "для понимания ограничений."
        ),
        required_docs= "адрес участка; кадастровый номер; документы на землю",
        responsible=   "manager",
        estimated_days="5",
        notes=         (
            "Risks: ограничения ПДП/регламента; красные линии; "
            "невозможность размещения хозпостройки в желаемом виде"
        ),
    ),
    dict(
        order=6,
        stage_name=    "Топографическая съемка",
        description=   "Заказываем или анализируем топосъемку участка.",
        required_docs= "адрес участка; кадастровый номер; доступ к участку",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: нет доступа к участку; ошибки в границах; выявлены ограничения",
    ),
    dict(
        order=7,
        stage_name=    "Проверка границ и расположения будущей хозпостройки",
        description=   (
            "По топосъемке проверяем границы участка, возможное расположение хозпостройки, "
            "отступы и ограничения."
        ),
        required_docs= "топосъемка; сведения ПДП/регламента если есть",
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: спорные границы; недостаточные отступы; "
            "желаемое расположение невозможно"
        ),
    ),
    dict(
        order=8,
        stage_name=    "Проверка водоохранной зоны, если рядом водный объект",
        description=   (
            "Если рядом есть арык, речка, канал или другой водный объект, "
            "проверяем водоохранную зону и необходимость согласия/запроса "
            "в профильную инспекцию."
        ),
        required_docs= (
            "топосъемка; адрес участка; сведения о водном объекте если есть"
        ),
        responsible=   "manager",
        estimated_days="5",
        notes=         (
            "Risks: водоохранная зона; рядом арык/речка/канал; "
            "профильная инспекция может не дать согласие"
        ),
    ),
    dict(
        order=9,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем состав работ, стоимость от 400 000 тг, порядок оплаты, сроки, "
            "ответственность клиента по СМР и документам."
        ),
        required_docs= "данные клиента; данные участка; данные существующего дома",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент не понимает риски АПЗ/ограничений; клиент затягивает оплату"
        ),
    ),
    dict(
        order=10,
        stage_name=    "Задание на проектирование",
        description=   "Формируем задание на проектирование хозпостройки.",
        required_docs= (
            "документы на землю; топосъемка; сведения ПДП/регламента если есть; "
            "пожелания клиента"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: пожелания клиента не соответствуют ограничениям; "
            "нужно корректировать задание"
        ),
    ),
    dict(
        order=11,
        stage_name=    "Эскизный проект хозпостройки",
        description=   "Готовим эскизный проект хозпостройки.",
        required_docs= (
            "задание на проектирование; топосъемка; сведения ПДП/регламента если есть"
        ),
        responsible=   "contractor",
        estimated_days="7",
        notes=         "Risks: замечания к эскизному проекту; требуется корректировка",
    ),
    dict(
        order=12,
        stage_name=    "Получение АПЗ",
        description=   (
            "Формируем пакет и подаем на получение АПЗ. "
            "Для хозпостройки АПЗ нужен, но обычно меньше проблем, "
            "так как основной дом уже зарегистрирован."
        ),
        required_docs= (
            "эскизный проект; документы клиента; документы на землю; "
            "документы на существующий дом; топосъемка; "
            "градостроительные сведения если есть"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         "Risks: замечания архитектуры; отказ; задержка рассмотрения",
    ),
    dict(
        order=13,
        stage_name=    "Проведение СМР клиентом / подрядчиком",
        description=   (
            "После получения АПЗ клиент или его подрядчик выполняет "
            "строительно-монтажные работы по хозпостройке."
        ),
        required_docs= "АПЗ; эскизный проект",
        responsible=   "client",
        estimated_days="30",
        notes=         (
            "Risks: СМР выполнены не по согласованной логике; затягивание работ; "
            "изменения клиента в процессе строительства"
        ),
    ),
    dict(
        order=14,
        stage_name=    "Исполнительная съемка",
        description=   "После завершения СМР выполняется исполнительная съемка.",
        required_docs= (
            "завершенные СМР; доступ к участку; адрес; кадастровый номер"
        ),
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: нет доступа; выявлены расхождения по факту",
    ),
    dict(
        order=15,
        stage_name=    "Согласование исполнительной съемки",
        description=   "Согласовываем исполнительную съемку.",
        required_docs= "исполнительная съемка",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: замечания по исполнительной съемке; задержка согласования",
    ),
    dict(
        order=16,
        stage_name=    "Технический паспорт",
        description=   (
            "Изготавливается технический паспорт. "
            "Клиент сам оплачивает госпошлины или услуги БТИ."
        ),
        required_docs= (
            "завершенные СМР; исполнительная съемка если требуется; "
            "документы клиента; документы на участок; документы на дом; доступ к объекту"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: задержка БТИ; расхождение площадей; "
            "клиент не оплатил услуги/госпошлины"
        ),
    ),
    dict(
        order=17,
        stage_name=    "Подготовка акта ввода",
        description=   "Готовим акт ввода и пакет для композитной услуги.",
        required_docs= (
            "АПЗ; технический паспорт; исполнительная съемка; "
            "документы клиента; документы на участок; документы на дом"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         "Risks: неполный пакет; ошибки в документах",
    ),
    dict(
        order=18,
        stage_name=    "Согласование акта ввода в архитектуре",
        description=   (
            "Подаем акт ввода на согласование в архитектуру. "
            "Обычно при подаче сегодня результат готов завтра вечером в рабочие дни."
        ),
        required_docs= "акт ввода; полный пакет; технический паспорт; АПЗ",
        responsible=   "government",
        estimated_days="1",
        notes=         "Risks: замечания архитектуры; пересдача; задержка согласования",
    ),
    dict(
        order=19,
        stage_name=    "Регистрация акта ввода в НАО",
        description=   (
            "После согласования архитектуры акт ввода регистрируется в НАО. "
            "Обычно около 5 рабочих дней."
        ),
        required_docs= (
            "согласованный акт ввода; технический паспорт; "
            "документы клиента; документы на участок; документы на дом"
        ),
        responsible=   "government",
        estimated_days="5",
        notes=         (
            "Risks: замечания НАО; ошибки в документах; задержка регистрации"
        ),
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для хозпостройки при существующем доме в Алматы",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документ на земельный участок; "
        "Документы на существующий дом; Технический паспорт дома если есть; "
        "Кадастровый номер; Адрес участка; Фото/видео места хозпостройки; "
        "ПДП/регламент/ситуационная схема если требуется; Топосъемка; "
        "Проверка границ; Проверка водоохранной зоны если требуется; "
        "Задание на проектирование; Эскизный проект хозпостройки; АПЗ; "
        "Исполнительная съемка; Согласование исполнительной съемки; "
        "Технический паспорт; Акт ввода; Согласование архитектуры; "
        "Регистрация акта в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для строительства/оформления хозпостройки "
        "при существующем доме, получения АПЗ, проведения СМР, "
        "исполнительной съемки, техпаспорта, акта ввода и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=            "Как определить хозпостройку при существующем доме в Алматы",
    biz_id=           BIZ_ID,
    service_id=       SERVICE_ID,
    template_id=      TEMPLATE_ID,
    purpose=          (
        "До запуска договора понять, что объект относится к отдельно стоящей хозпостройке "
        "при уже зарегистрированном доме, а не к реконструкции или новому строительству дома."
    ),
    steps=            (
        "1. Уточнить, есть ли на участке уже зарегистрированный жилой дом. "
        "2. Уточнить, хозпостройка отдельно стоящая или пристроена к дому. "
        "3. Если пристроена к дому — направить в SVC-IZH-001. "
        "4. Если участок голый и строится новый дом с хозпостройками — направить в SVC-IZH-002. "
        "5. Получить документы на земельный участок, существующий дом, адрес и кадастровый номер. "
        "6. Проверить целевое назначение земли. "
        "7. Получить/заказать топосъемку. "
        "8. Проверить границы и возможное расположение хозпостройки. "
        "9. Проверить водоохранную зону, если рядом арык/речка/канал. "
        "10. Зафиксировать риски. "
        "11. Выбрать шаблон RMT-IZH-ALM-OUTBUILDING-001."
    ),
    expected_result=  (
        "Выбран шаблон хозпостройки или объект направлен в другую услугу."
    ),
    owner_role=       "manager",
    status=           "active",
)


# ═══════════════════════════════════════════════════════════════
# Idempotency helpers
# ═══════════════════════════════════════════════════════════════

def _service_exists() -> bool:
    try:
        from business_core.service_manager import find_service_by_id
        return find_service_by_id(SERVICE_ID) is not None
    except Exception as e:
        log.warning(f"_service_exists check error: {e}")
        return False


def _template_exists() -> bool:
    try:
        from business_core.roadmap_template_manager import find_roadmap_template_by_id
        return find_roadmap_template_by_id(TEMPLATE_ID) is not None
    except Exception as e:
        log.warning(f"_template_exists check error: {e}")
        return False


def _stages_count() -> int:
    try:
        from business_core.roadmap_template_manager import find_template_stages
        return len(find_template_stages(TEMPLATE_ID))
    except Exception as e:
        log.warning(f"_stages_count check error: {e}")
        return 0


def _checklist_exists() -> bool:
    try:
        from business_core.knowledge_manager import find_checklist_by_id
        return find_checklist_by_id(CHECKLIST_ID) is not None
    except Exception as e:
        log.warning(f"_checklist_exists check error: {e}")
        return False


def _sop_exists() -> bool:
    try:
        from business_core.knowledge_manager import find_sop_by_id
        return find_sop_by_id(SOP_ID) is not None
    except Exception as e:
        log.warning(f"_sop_exists check error: {e}")
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

    existing_stages = _stages_count()
    if existing_stages >= len(STAGES):
        skip.append(f"[SKIP] Stages для {TEMPLATE_ID} уже есть ({existing_stages})")
    else:
        missing = len(STAGES) - existing_stages
        plan.append(
            f"[CREATE] {missing} stages для {TEMPLATE_ID} (уже есть: {existing_stages})"
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

def run_seed(verbose: bool = True) -> dict:
    created = []
    skipped = []
    errors  = []

    # ── 0. Service ────────────────────────────────────────────
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

    # ── 1. Template ───────────────────────────────────────────
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

    # ── 2. Stages ─────────────────────────────────────────────
    existing_count = _stages_count()
    if existing_count >= len(STAGES):
        skipped.append(f"Stages {TEMPLATE_ID} ({existing_count} уже есть)")
        if verbose: print(f"  [SKIP] Stages для {TEMPLATE_ID} ({existing_count})")
    else:
        try:
            from business_core.roadmap_template_manager import add_roadmap_template_stage
            stages_to_add = STAGES[existing_count:]
            added_count   = 0
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
                    added_count += 1
                else:
                    errors.append(f"Stage {s['order']}: {result['error']}")
            created.append(f"Stages {TEMPLATE_ID} (+{added_count})")
            if verbose:
                print(f"  [OK] Stages: +{added_count} (итого {existing_count + added_count})")
        except Exception as e:
            errors.append(f"Stages exception: {e}")
            if verbose: print(f"  [ERR] Stages exception: {e}")

    # ── 3. Checklist ──────────────────────────────────────────
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

    # ── 4. SOP ────────────────────────────────────────────────
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


def _rename_id_in_sheet(sheet, old_id: str, new_id: str) -> None:
    """Заменить авто-ID на фиксированный seed-ID в первой колонке листа."""
    if old_id == new_id:
        return
    all_values = sheet.get_all_values()
    for i, row in enumerate(all_values[1:], start=2):
        if row and row[0].strip() == old_id:
            sheet.update_cell(i, 1, new_id)
            return


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seed: Алматы / ИЖС / Хозпостройка при существующем доме (SVC-IZH-003)")
    print("Template: RMT-IZH-ALM-OUTBUILDING-001 | 19 этапов")
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
