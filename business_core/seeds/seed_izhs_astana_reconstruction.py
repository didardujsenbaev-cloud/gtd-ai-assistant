"""
Seed: Астана / ИЖС / реконструкция-пристройка-надстройка / обычный путь.

Услуга:    SVC-IZH-AST-001 (новая — создаём)
Шаблон:    RMT-IZH-AST-RECON-001
12 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_astana_reconstruction.py --dry-run
    python3 business_core/seeds/seed_izhs_astana_reconstruction.py

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

SERVICE_ID   = "SVC-IZH-AST-001"
TEMPLATE_ID  = "RMT-IZH-AST-RECON-001"
CHECKLIST_ID = "CHK-IZH-AST-RECON-DOCS-001"
SOP_ID       = "SOP-IZH-AST-RECON-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    service_name=            "Астана / реконструкция / пристройка / надстройка ИЖС",
    biz_id=                  BIZ_ID,
    service_category=        "private_house_reconstruction",
    city=                    "Астана",
    object_type=             "private_house_izhs",
    client_type=             "physical_person",
    description=             (
        "Сопровождение реконструкции, пристройки или надстройки частного дома в Астане "
        "по обычному пути: первичный анализ, проверка документов, проектная часть, "
        "получение АПЗ, технический паспорт, акт ввода и регистрация в НАО."
    ),
    what_included=           (
        "первичный анализ объекта; проверка документов на дом и землю; "
        "проверка фактических изменений; "
        "проверка необходимости топосъемки/ПДП/ограничений; договор с клиентом; "
        "эскизный или технический проект; получение АПЗ; "
        "сопровождение СМР если они еще не выполнены; технический паспорт; "
        "подготовка акта ввода; согласование акта ввода; регистрация в НАО; "
        "координация процесса"
    ),
    what_not_included=       (
        "строительно-монтажные работы; госпошлины; оплата технического паспорта; "
        "нотариальные согласия если потребуются; штрафы; "
        "повторные подачи после существенных изменений; "
        "дополнительные согласования, не указанные в договоре"
    ),
    price_from=              "700000",
    currency=                "KZT",
    estimated_duration=      "2-4 месяца",
    required_documents=      (
        "удостоверение личности; документы на дом; документ на земельный участок; "
        "технический паспорт если есть; кадастровый номер; адрес объекта; "
        "фото/видео объекта"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=                   (
        "объект фактически является новым строительством; документы неполные; "
        "расхождение фактической площади; СМР уже выполнены до АПЗ; "
        "требуется согласие соседей/дольщиков; ограничения по земле; "
        "замечания архитектуры; отказ/замечания по АПЗ; задержки госорганов"
    ),
    contractors_needed=      (
        "проектировщик; специалист БТИ/техпаспорт; "
        "топограф при необходимости; координатор"
    ),
    status=                  "active",
    notes=                   (
        "Астанинская версия проще Алматы. Сейсмостойкое заключение не требуется. "
        "Техническое обследование используется только при необходимости. "
        "ПДП/регламент/ситуационная схема проверяются только при сложных или спорных случаях. "
        "Топосъемка используется по ситуации. "
        "Водоохранная зона проверяется только если рядом есть водный объект."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= "Астана / ИЖС / реконструкция-пристройка-надстройка / обычный путь",
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "astana_izhs_reconstruction_standard",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для сопровождения реконструкции, пристройки или надстройки "
        "частного дома в Астане по обычному пути."
    ),
    status=        "active",
    notes=         (
        "Универсальный шаблон для Астаны. "
        "Если СМР еще не выполнены — этап СМР проходится после АПЗ. "
        "Если СМР уже выполнены — этап СМР отмечается как выполненный/пропущенный, "
        "но фиксируется риск выполненных работ до АПЗ. "
        "Сейсмостойкость не используется. "
        "Техобследование, топосъемка, ПДП/регламент и водоохранная зона — "
        "только при необходимости."
    ),
)

# ─── 12 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ объекта",
        description=   (
            "Проверяем, что объект относится к реконструкции, пристройке или надстройке "
            "частного дома в Астане, а не к новому строительству или отдельной хозпостройке."
        ),
        required_docs= (
            "удостоверение клиента; документы на дом; документы на землю; "
            "техпаспорт если есть; фото/видео; адрес; кадастровый номер"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: объект фактически является новым строительством; "
            "объект относится к отдельной хозпостройке; неверная классификация услуги"
        ),
    ),
    dict(
        order=2,
        stage_name=    "Проверка документов на дом и землю",
        description=   (
            "Проверяем документы на дом, земельный участок, собственника, адрес, "
            "кадастровый номер и наличие технического паспорта."
        ),
        required_docs= (
            "документы на дом; документ на землю; техпаспорт если есть; "
            "удостоверение клиента"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: документы неполные; ошибки в документах; "
            "собственник не совпадает; техпаспорт отсутствует"
        ),
    ),
    dict(
        order=3,
        stage_name=    "Проверка фактических изменений",
        description=   (
            "Сравниваем фактическое состояние с документами: что изменилось, "
            "какая пристройка/надстройка/реконструкция выполнена или планируется."
        ),
        required_docs= (
            "фото/видео объекта; техпаспорт если есть; документы на дом; "
            "доступ к объекту при необходимости"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: расхождение площади; выявлены незаявленные постройки; "
            "клиент уже выполнил СМР до АПЗ"
        ),
    ),
    dict(
        order=4,
        stage_name=    "Проверка необходимости топосъемки / ПДП / ограничений",
        description=   (
            "Для Астаны топосъемка, ПДП/регламент/ситуационная схема проверяются "
            "не всегда, а только если есть спорный участок, ограничения, "
            "большие изменения, сложное расположение или требования госоргана."
        ),
        required_docs= "документы на землю; кадастровый номер; адрес; фото/видео",
        responsible=   "manager",
        estimated_days="3",
        notes=         (
            "Risks: ограничения участка; красные линии; требование топосъемки; "
            "спорные границы; дополнительные запросы"
        ),
    ),
    dict(
        order=5,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем состав работ, цену, сроки, порядок оплаты, "
            "риски АПЗ, ответственность клиента по документам и СМР."
        ),
        required_docs= "данные клиента; данные объекта",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент не понимает риск отказа/замечаний; "
            "клиент затягивает оплату"
        ),
    ),
    dict(
        order=6,
        stage_name=    "Эскизный / технический проект",
        description=   (
            "Готовим проектную часть для реконструкции, пристройки или надстройки. "
            "В Астане без сейсмостойкого заключения. "
            "Техобследование добавляется только если требуется."
        ),
        required_docs= (
            "документы на дом; документы на землю; техпаспорт если есть; "
            "фото/видео; топосъемка если требуется"
        ),
        responsible=   "contractor",
        estimated_days="7",
        notes=         (
            "Risks: нужны корректировки; "
            "фактическое состояние не совпадает с документами; "
            "требуется дополнительное техобследование"
        ),
    ),
    dict(
        order=7,
        stage_name=    "Получение АПЗ",
        description=   "Формируем пакет и подаем на получение АПЗ.",
        required_docs= (
            "проектная часть; документы клиента; документы на дом и землю; "
            "топосъемка если требуется; дополнительные проверки если требуются"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         (
            "Risks: замечания архитектуры; отказ; задержка рассмотрения; "
            "неполный пакет"
        ),
    ),
    dict(
        order=8,
        stage_name=    "Проведение СМР, если еще не выполнено",
        description=   (
            "Если СМР еще не выполнены, клиент или подрядчик выполняет работы "
            "после получения АПЗ. Если СМР уже выполнены, этап отмечается как "
            "выполненный/пропущенный с фиксацией риска."
        ),
        required_docs= "АПЗ; проектная часть",
        responsible=   "client",
        estimated_days="30",
        notes=         (
            "Risks: работы выполнены не по проектной логике; "
            "клиент изменил решения; СМР были выполнены до АПЗ"
        ),
    ),
    dict(
        order=9,
        stage_name=    "Технический паспорт",
        description=   (
            "После завершения СМР изготавливается технический паспорт "
            "по фактическому состоянию объекта."
        ),
        required_docs= (
            "АПЗ; документы клиента; документы на дом и землю; доступ к объекту"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: задержка БТИ; расхождение площадей; "
            "клиент не оплатил услуги/госпошлины"
        ),
    ),
    dict(
        order=10,
        stage_name=    "Подготовка акта ввода",
        description=   "Готовим акт ввода и пакет документов.",
        required_docs= (
            "АПЗ; технический паспорт; документы клиента; "
            "документы на дом и землю; проектная часть"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         "Risks: неполный пакет; ошибки в документах",
    ),
    dict(
        order=11,
        stage_name=    "Согласование акта ввода",
        description=   "Подаем акт ввода на согласование в уполномоченный орган.",
        required_docs= "акт ввода; полный пакет; технический паспорт; АПЗ",
        responsible=   "manager",
        estimated_days="3",
        notes=         "Risks: замечания; пересдача; задержка согласования",
    ),
    dict(
        order=12,
        stage_name=    "Регистрация в НАО",
        description=   (
            "После согласования акта ввода регистрируем изменения в НАО."
        ),
        required_docs= (
            "согласованный акт ввода; технический паспорт; "
            "документы клиента; документы на объект"
        ),
        responsible=   "manager",
        estimated_days="5",
        notes=         (
            "Risks: замечания НАО; ошибки в документах; задержка регистрации"
        ),
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для реконструкции ИЖС в Астане",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документы на дом; "
        "Документ на земельный участок; Технический паспорт если есть; "
        "Кадастровый номер; Адрес объекта; Фото/видео объекта; "
        "Топосъемка если требуется; "
        "ПДП/регламент/ситуационная схема если требуется; "
        "Согласие соседей/дольщиков если требуется; "
        "Эскизный или технический проект; Техобследование если требуется; "
        "АПЗ; Технический паспорт; Акт ввода; "
        "Согласование акта ввода; Регистрация в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для реконструкции, пристройки или надстройки ИЖС в Астане, "
        "получения АПЗ, техпаспорта, акта ввода и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=           "Как определить реконструкцию ИЖС в Астане",
    biz_id=          BIZ_ID,
    service_id=      SERVICE_ID,
    template_id=     TEMPLATE_ID,
    purpose=         (
        "До запуска договора понять, подходит ли объект под реконструкцию, пристройку "
        "или надстройку ИЖС в Астане, и какие упрощенные или дополнительные этапы нужны."
    ),
    steps=           (
        "1. Уточнить, что клиент хочет сделать: реконструкцию, пристройку или надстройку. "
        "2. Проверить, не является ли объект новым строительством. "
        "3. Проверить, не является ли объект отдельной хозпостройкой. "
        "4. Получить документы на дом и землю. "
        "5. Проверить технический паспорт, если есть. "
        "6. Сравнить фактическое состояние с документами. "
        "7. Определить, выполнены ли СМР уже или только планируются. "
        "8. Определить, нужна ли топосъемка. "
        "9. Определить, нужна ли проверка ПДП/регламента/ситуационной схемы. "
        "10. Определить, нужно ли техническое обследование. "
        "11. Зафиксировать риски и выбрать шаблон RMT-IZH-AST-RECON-001."
    ),
    expected_result= (
        "Выбран шаблон реконструкции ИЖС в Астане "
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
                total = existing_count + added
                print(f"  [OK] Stages: +{added} (итого {total})")
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
    print("Seed: Астана / ИЖС / реконструкция (SVC-IZH-AST-001)")
    print("Template: RMT-IZH-AST-RECON-001 | 12 этапов")
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
