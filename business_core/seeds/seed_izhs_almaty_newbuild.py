"""
Seed: Алматы / ИЖС / Новое строительство частного дома на голом участке.

Услуга:    SVC-IZH-002 (новая — создаём)
Шаблон:    RMT-IZH-ALM-NEWBUILD-001
18 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_almaty_newbuild.py --dry-run
    python3 business_core/seeds/seed_izhs_almaty_newbuild.py

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

SERVICE_ID   = "SVC-IZH-002"
TEMPLATE_ID  = "RMT-IZH-ALM-NEWBUILD-001"
CHECKLIST_ID = "CHK-IZH-ALM-NEWBUILD-DOCS-001"
SOP_ID       = "SOP-IZH-ALM-NEWBUILD-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    service_name=            "Новое строительство частного дома на голом участке",
    biz_id=                  BIZ_ID,
    service_category=        "new_construction",
    city=                    "Алматы",
    object_type=             "private_house_izhs",
    client_type=             "physical_person",
    description=             (
        "Сопровождение нового строительства частного дома на голом участке в Алматы. "
        "В рамках нового строительства к дому могут входить хозпостройки: баня, гараж, "
        "сарай, летняя кухня и другие вспомогательные строения."
    ),
    what_included=           (
        "проверка документов на землю; проверка целевого назначения; "
        "ПДП/регламент/ситуационная схема; топосъемка; проверка границ; "
        "проверка водоохранной зоны при необходимости; задание на проектирование; "
        "эскизный проект; получение АПЗ; сопровождение после СМР; "
        "исполнительная съемка; согласование исполнительной съемки; "
        "технический паспорт; акт ввода; согласование в архитектуре; "
        "регистрация в НАО; координация процесса"
    ),
    what_not_included=       (
        "технические условия; строительно-монтажные работы; госпошлины; "
        "оплата технического паспорта; нотариальные согласия если потребуются; штрафы; "
        "повторные подачи после существенных изменений; "
        "дополнительные согласования, не указанные в договоре"
    ),
    price_from=              "700000",
    currency=                "KZT",
    estimated_duration=      "3-4 месяца",
    required_documents=      (
        "удостоверение личности; документ на земельный участок; "
        "кадастровый номер; адрес участка; фото/видео участка если есть"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=                   (
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
        "Услуга применяется для голого участка, где строится новый жилой дом. "
        "Если на участке уже есть дом и нужно построить/узаконить отдельную хозпостройку, "
        "это отдельная услуга SVC-IZH-003. ТУ в рамках этой услуги не ведем. "
        "Проектная часть — эскизный проект. "
        "Исполнительная съемка и согласование исполнительной съемки нужны."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= "Алматы / ИЖС / новое строительство / с проведением СМР",
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "almaty_izhs_newbuild_before_smr",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для нового строительства частного дома на голом участке в Алматы. "
        "К новому дому могут относиться хозпостройки: баня, гараж, сарай, "
        "летняя кухня и другие вспомогательные строения."
    ),
    status=        "active",
    notes=         (
        "Новый дом на голом участке. Если дом уже есть и нужна только хозпостройка, "
        "использовать отдельную будущую услугу SVC-IZH-003. "
        "ТУ не ведем. Проект — эскизный проект. Исполнительная съемка нужна."
    ),
)

# ─── 18 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ: голый участок или нет",
        description=   (
            "Проверяем, что объект относится именно к новому строительству на голом участке. "
            "Если дом уже есть и нужна только хозпостройка, это не этот шаблон."
        ),
        required_docs= (
            "удостоверение клиента; документ на земельный участок; "
            "кадастровый номер; адрес участка; фото/видео участка если есть"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: на участке уже есть дом; клиент фактически хочет отдельную хозпостройку; "
            "неверная классификация услуги"
        ),
    ),
    dict(
        order=2,
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
        order=3,
        stage_name=    "Проверка целевого назначения земли",
        description=   (
            "Проверяем, подходит ли целевое назначение земли "
            "для нового строительства частного дома."
        ),
        required_docs= "документ на земельный участок; кадастровый номер",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: целевое назначение не подходит; требуется изменение назначения"
        ),
    ),
    dict(
        order=4,
        stage_name=    "ПДП / регламент / ситуационная схема",
        description=   (
            "Получаем или анализируем сведения по ПДП, регламенту и ситуационной схеме "
            "как единый градостроительный блок для понимания ограничений строительства."
        ),
        required_docs= "адрес участка; кадастровый номер; документы на землю",
        responsible=   "manager",
        estimated_days="5",
        notes=         (
            "Risks: ограничения ПДП/регламента; красные линии; "
            "невозможность строительства в желаемом виде"
        ),
    ),
    dict(
        order=5,
        stage_name=    "Топографическая съемка",
        description=   "Заказываем или анализируем топосъемку участка.",
        required_docs= "адрес участка; кадастровый номер; доступ к участку",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: нет доступа к участку; ошибки в границах; выявлены ограничения",
    ),
    dict(
        order=6,
        stage_name=    "Проверка границ и расположения будущего строительства",
        description=   (
            "По топосъемке проверяем границы участка, возможное расположение дома "
            "и хозпостроек, отступы и ограничения."
        ),
        required_docs= "топосъемка; сведения ПДП/регламента",
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: спорные границы; недостаточные отступы; "
            "желаемое расположение невозможно"
        ),
    ),
    dict(
        order=7,
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
        order=8,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем состав работ, стоимость от 700 000 тг, порядок оплаты, сроки, "
            "ответственность клиента по СМР и документам."
        ),
        required_docs= "данные клиента; данные участка",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент не понимает риски АПЗ/ограничений; клиент затягивает оплату"
        ),
    ),
    dict(
        order=9,
        stage_name=    "Задание на проектирование",
        description=   (
            "Формируем задание на проектирование для нового дома и возможных хозпостроек."
        ),
        required_docs= (
            "документы на землю; топосъемка; сведения ПДП/регламента; пожелания клиента"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: пожелания клиента не соответствуют ограничениям; "
            "нужно корректировать задание"
        ),
    ),
    dict(
        order=10,
        stage_name=    "Эскизный проект",
        description=   (
            "Готовим эскизный проект. В рамках этой услуги рабочий проект/АР/КЖ не ведем."
        ),
        required_docs= (
            "задание на проектирование; топосъемка; сведения ПДП/регламента"
        ),
        responsible=   "contractor",
        estimated_days="7",
        notes=         "Risks: замечания к эскизному проекту; требуется корректировка",
    ),
    dict(
        order=11,
        stage_name=    "Получение АПЗ",
        description=   "Формируем пакет и подаем на получение АПЗ.",
        required_docs= (
            "эскизный проект; документы клиента; документы на землю; "
            "топосъемка; градостроительные сведения"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         "Risks: замечания архитектуры; отказ; задержка рассмотрения",
    ),
    dict(
        order=12,
        stage_name=    "Проведение СМР клиентом / подрядчиком",
        description=   (
            "После получения АПЗ клиент или его подрядчик выполняет "
            "строительно-монтажные работы."
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
        order=13,
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
        order=14,
        stage_name=    "Согласование исполнительной съемки",
        description=   "Согласовываем исполнительную съемку.",
        required_docs= "исполнительная съемка",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: замечания по исполнительной съемке; задержка согласования",
    ),
    dict(
        order=15,
        stage_name=    "Технический паспорт",
        description=   (
            "Изготавливается технический паспорт. "
            "Клиент сам оплачивает госпошлины или услуги БТИ."
        ),
        required_docs= (
            "завершенные СМР; исполнительная съемка если требуется; "
            "документы клиента; документы на участок; доступ к объекту"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: задержка БТИ; расхождение площадей; "
            "клиент не оплатил услуги/госпошлины"
        ),
    ),
    dict(
        order=16,
        stage_name=    "Подготовка акта ввода",
        description=   "Готовим акт ввода и пакет для композитной услуги.",
        required_docs= (
            "АПЗ; технический паспорт; исполнительная съемка; "
            "документы клиента; документы на участок"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         "Risks: неполный пакет; ошибки в документах",
    ),
    dict(
        order=17,
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
        order=18,
        stage_name=    "Регистрация акта ввода в НАО",
        description=   (
            "После согласования архитектуры акт ввода регистрируется в НАО. "
            "Обычно около 5 рабочих дней."
        ),
        required_docs= (
            "согласованный акт ввода; технический паспорт; "
            "документы клиента; документы на участок"
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
    title=       "Чек-лист документов для нового строительства ИЖС в Алматы",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документ на земельный участок; "
        "Кадастровый номер; Адрес участка; ПДП/регламент/ситуационная схема; "
        "Топосъемка; Проверка границ; Проверка водоохранной зоны если требуется; "
        "Задание на проектирование; Эскизный проект; АПЗ; "
        "Исполнительная съемка; Согласование исполнительной съемки; "
        "Технический паспорт; Акт ввода; Согласование архитектуры; "
        "Регистрация акта в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для нового строительства ИЖС, получения АПЗ, "
        "проведения СМР, исполнительной съемки, техпаспорта, "
        "акта ввода и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=            "Как определить новое строительство ИЖС в Алматы",
    biz_id=           BIZ_ID,
    service_id=       SERVICE_ID,
    template_id=      TEMPLATE_ID,
    purpose=          (
        "До запуска договора понять, что объект относится к новому строительству "
        "на голом участке, а не к реконструкции или отдельной хозпостройке "
        "при существующем доме."
    ),
    steps=            (
        "1. Уточнить, голый участок или на участке уже есть дом. "
        "2. Если дом уже есть и нужна только хозпостройка, направить в отдельную "
        "будущую услугу SVC-IZH-003. "
        "3. Получить документы на земельный участок, адрес и кадастровый номер. "
        "4. Проверить целевое назначение земли. "
        "5. Получить/проанализировать ПДП/регламент/ситуационную схему "
        "как единый градостроительный блок. "
        "6. Получить/заказать топосъемку. "
        "7. Проверить границы и возможное расположение будущего дома. "
        "8. Проверить водоохранную зону, если рядом арык/речка/канал. "
        "9. Зафиксировать риски. "
        "10. Выбрать шаблон RMT-IZH-ALM-NEWBUILD-001."
    ),
    expected_result=  (
        "Выбран шаблон нового строительства или объект направлен в другую услугу."
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
    """
    Показать что будет создано, не записывая в Google Sheets.

    Returns:
        dict со списком планируемых действий и пропусков.
    """
    plan = []
    skip = []

    if _service_exists():
        skip.append(f"[SKIP] Service {SERVICE_ID} уже существует")
    else:
        plan.append(
            f"[CREATE] Service {SERVICE_ID}: {SERVICE_DATA['service_name']}"
        )

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
    """
    Записать данные в Google Sheets.

    Идемпотентен: пропускает то, что уже есть.

    Returns:
        {"created": list[str], "skipped": list[str], "errors": list[str]}
    """
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
    print("Seed: Алматы / ИЖС / Новое строительство (SVC-IZH-002)")
    print("Template: RMT-IZH-ALM-NEWBUILD-001 | 18 этапов")
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

    # Live mode
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
