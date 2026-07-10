"""
Seed: Алматы / ИЖС / Обычный путь / Реконструкция-Пристройка-Надстройка / с проведением СМР.

Услуга:    SVC-IZH-001 (уже существует — не создаём)
Шаблон:    RMT-IZH-ALM-STANDARD-001
15 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_almaty_standard_reconstruction.py --dry-run
    python3 business_core/seeds/seed_izhs_almaty_standard_reconstruction.py

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

SERVICE_ID   = "SVC-IZH-001"         # уже существует
TEMPLATE_ID  = "RMT-IZH-ALM-STANDARD-001"
CHECKLIST_ID = "CHK-IZH-ALM-STANDARD-RECON-DOCS-001"
SOP_ID       = "SOP-IZH-ALM-STANDARD-RECON-PRIMARY-001"
BIZ_ID       = "BIZ-001"

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= (
        "Алматы / ИЖС / обычный путь / "
        "реконструкция-пристройка-надстройка / с проведением СМР"
    ),
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "almaty_izhs_standard_reconstruction_before_smr",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для обычного пути реконструкции, пристройки или надстройки частного дома "
        "в Алматы. Применяется, когда СМР должны проводиться после получения АПЗ."
    ),
    status=        "active",
    notes=         (
        "Новый дом не входит в этот шаблон. Новое строительство будет отдельной услугой SVC-IZH-002. "
        "Исполнительная съемка для реконструкции ИЖС в этом шаблоне не используется. "
        "Финал — технический паспорт, акт ввода, согласование в архитектуре и регистрация акта в НАО."
    ),
)

# ─── 15 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ объекта и намерения клиента",
        description=   (
            "Проверяем, что клиент хочет сделать: реконструкцию, пристройку или надстройку. "
            "Новый дом не входит в этот шаблон. Проверяем документы, землю, техпаспорт, "
            "площадь изменений и риски."
        ),
        required_docs= (
            "удостоверение клиента; документы на объект; документы на землю; "
            "техпаспорт если есть; фото/видео; адрес объекта"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент фактически строит новый дом; неверная классификация услуги; "
            "объект не подходит под реконструкцию"
        ),
    ),
    dict(
        order=2,
        stage_name=    "Проверка земли, ПДП, красных линий и ограничений",
        description=   (
            "Проверяем целевое назначение земли, ПДП, красные линии, отступы, "
            "ограничения участка, общую долевую собственность и необходимость согласия соседей."
        ),
        required_docs= (
            "документ на землю; кадастровый номер; адрес объекта; сведения ПДП при наличии"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         (
            "Risks: неподходящее целевое назначение; красные линии; "
            "нарушение отступов; общая долевая собственность"
        ),
    ),
    dict(
        order=3,
        stage_name=    "Топографическая съемка",
        description=   (
            "Заказываем топосъемку, получаем фактическую ситуацию по участку, "
            "границам, строениям и ограничениям."
        ),
        required_docs= "адрес объекта; кадастровый номер; доступ к участку",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: нет доступа к участку; ошибки в границах; выявлены ограничения",
    ),
    dict(
        order=4,
        stage_name=    "Согласование топосъемки",
        description=   (
            "Согласовываем топосъемку. Согласованная топосъемка используется дальше "
            "для проектной части и АПЗ."
        ),
        required_docs= "готовая топосъемка",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: замечания по съемке; задержка согласования",
    ),
    dict(
        order=5,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем состав работ, стоимость от 950 000 тг, порядок оплаты, сроки, "
            "ответственность клиента по СМР, документам и согласиям."
        ),
        required_docs= "данные клиента; данные объекта",
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Risks: клиент не понимает, что СМР должны быть после АПЗ; "
            "клиент затягивает оплату"
        ),
    ),
    dict(
        order=6,
        stage_name=    "Согласие соседей / дольщиков, если нужно",
        description=   (
            "Согласие требуется, если реконструкция близко к границе, "
            "затрагивает соседей или есть общая долевая собственность."
        ),
        required_docs= "данные соседей/дольщиков; документы для нотариуса при необходимости",
        responsible=   "client",
        estimated_days="5",
        notes=         (
            "Risks: сосед не согласен; дольщик не согласен; клиент затягивает согласие"
        ),
    ),
    dict(
        order=7,
        stage_name=    "Первичный замер БТИ / специалиста",
        description=   (
            "Делаем фактический замер существующего объекта и планируемых изменений. "
            "Данные используются для технического проекта и будущего техпаспорта."
        ),
        required_docs= "доступ к объекту; документы на объект; адрес",
        responsible=   "contractor",
        estimated_days="3",
        notes=         "Risks: расхождение площадей; выявлены незаявленные постройки; нет доступа",
    ),
    dict(
        order=8,
        stage_name=    "Техническое обследование / сейсмостойкое заключение",
        description=   (
            "Для реконструкции, пристройки и надстройки в Алматы готовим техническое "
            "обследование и сейсмостойкое заключение. Иногда может быть одним документом."
        ),
        required_docs= "замеры; документы на объект; доступ к объекту; фото/видео",
        responsible=   "contractor",
        estimated_days="7",
        notes=         (
            "Risks: конструктивные риски; сейсмические замечания; недостаточно данных"
        ),
    ),
    dict(
        order=9,
        stage_name=    "Технический проект",
        description=   (
            "Готовим технический проект до получения АПЗ. Используем согласованную "
            "топосъемку, замеры, техобследование и сейсмостойкое заключение."
        ),
        required_docs= (
            "согласованная топосъемка; первичный замер; техобследование; "
            "сейсмостойкое заключение; документы клиента"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: замечания к проекту; недостаточно исходных данных; "
            "нужно корректировать проект"
        ),
    ),
    dict(
        order=10,
        stage_name=    "Получение АПЗ",
        description=   (
            "Формируем пакет и подаем на получение АПЗ. "
            "В обычном пути АПЗ обязательно."
        ),
        required_docs= (
            "технический проект; согласованная топосъемка; документы клиента; "
            "документы на землю/объект; согласие если требуется"
        ),
        responsible=   "manager",
        estimated_days="10",
        notes=         "Risks: замечания архитектуры; отказ; задержка рассмотрения",
    ),
    dict(
        order=11,
        stage_name=    "Проведение СМР клиентом / подрядчиком",
        description=   (
            "После получения АПЗ клиент или его подрядчик проводит строительно-монтажные работы. "
            "Если СМР уже начаты, фиксируем это как риск, но ведем по обычному пути."
        ),
        required_docs= "АПЗ; проектные материалы",
        responsible=   "client",
        estimated_days="30",
        notes=         (
            "Risks: клиент начал СМР до АПЗ; работы выполнены не по проекту; "
            "затягивание строительных работ"
        ),
    ),
    dict(
        order=12,
        stage_name=    "Технический паспорт",
        description=   (
            "После завершения СМР изготавливается технический паспорт. "
            "Клиент сам оплачивает госпошлины или услуги БТИ."
        ),
        required_docs= (
            "завершенные СМР; документы клиента; документы на объект; доступ к объекту"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: задержка БТИ; расхождение площадей; клиент не оплатил услуги/госпошлины"
        ),
    ),
    dict(
        order=13,
        stage_name=    "Подготовка акта ввода",
        description=   "Готовим акт ввода и пакет для kompozitной услуги.",
        required_docs= (
            "АПЗ; технический паспорт; документы клиента; "
            "документы на объект; проектные материалы"
        ),
        responsible=   "manager",
        estimated_days="2",
        notes=         "Risks: неполный пакет; ошибки в документах",
    ),
    dict(
        order=14,
        stage_name=    "Согласование акта ввода в архитектуре",
        description=   (
            "Подаем акт ввода на согласование в архитектуру. Обычно при подаче сегодня "
            "результат готов завтра вечером в рабочие дни. "
            "Иногда приходится пересдавать архитектуру."
        ),
        required_docs= "акт ввода; полный пакет; технический паспорт; АПЗ",
        responsible=   "government",
        estimated_days="1",
        notes=         "Risks: замечания архитектуры; пересдача; задержка согласования",
    ),
    dict(
        order=15,
        stage_name=    "Регистрация акта ввода в НАО",
        description=   (
            "После согласования архитектуры акт ввода регистрируется в НАО. "
            "Обычно около 5 рабочих дней."
        ),
        required_docs= (
            "согласованный акт ввода; технический паспорт; "
            "документы клиента; документы на объект"
        ),
        responsible=   "government",
        estimated_days="5",
        notes=         "Risks: замечания НАО; ошибки в документах; задержка регистрации",
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для обычного пути реконструкции ИЖС в Алматы",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Документы на объект; "
        "Документ на земельный участок; Кадастровый номер; "
        "Технический паспорт если есть; Фото/видео объекта; Адрес объекта; "
        "Топосъемка; Согласованная топосъемка; "
        "Согласие соседей/дольщиков если требуется; Первичный замер; "
        "Техническое обследование; Сейсмостойкое заключение; Технический проект; "
        "АПЗ; Технический паспорт после СМР; Акт ввода; "
        "Согласование архитектуры; Регистрация акта в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для обычного пути реконструкции, "
        "получения АПЗ, техпаспорта, акта ввода и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=            "Как определить обычный путь реконструкции ИЖС в Алматы",
    biz_id=           BIZ_ID,
    service_id=       SERVICE_ID,
    template_id=      TEMPLATE_ID,
    purpose=          (
        "До запуска договора понять, подходит ли объект под обычный путь реконструкции, "
        "пристройки или надстройки, и не является ли это новым строительством."
    ),
    steps=            (
        "1. Уточнить, что клиент хочет сделать: реконструкция, пристройка или надстройка. "
        "2. Отделить от нового строительства. Новый дом вести как отдельную услугу. "
        "3. Получить документы на объект и землю. "
        "4. Проверить целевое назначение земли. "
        "5. Проверить техпаспорт и фактическое состояние объекта. "
        "6. Проверить ПДП, красные линии, отступы и ограничения. "
        "7. Проверить наличие общей долевой собственности. "
        "8. Определить, нужно ли согласие соседей или дольщиков. "
        "9. Проверить, не начал ли клиент СМР до АПЗ. "
        "10. Зафиксировать риски и выбрать шаблон RMT-IZH-ALM-STANDARD-001."
    ),
    expected_result=  (
        "Выбран обычный путь реконструкции ИЖС или объект направлен в другой шаблон."
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

    # Проверяем что SVC-IZH-001 существует (не создаём, только информируем)
    if _service_exists():
        skip.append(f"[OK]   Service {SERVICE_ID} существует — используем его")
    else:
        skip.append(f"[WARN] Service {SERVICE_ID} не найден (должен существовать из seed 1)")

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
    Не создаёт новый Service — только использует SVC-IZH-001.

    Returns:
        {"created": list[str], "skipped": list[str], "errors": list[str]}
    """
    created = []
    skipped = []
    errors  = []

    # ── 0. Проверка Service (не создаём) ─────────────────────
    if _service_exists():
        skipped.append(f"Service {SERVICE_ID} (уже существует)")
        if verbose: print(f"  [OK]   Service {SERVICE_ID} найден")
    else:
        skipped.append(f"Service {SERVICE_ID} (не найден — нужен seed 1)")
        if verbose:
            print(f"  [WARN] Service {SERVICE_ID} не найден — запусти сначала seed 1")

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
    print("Seed: Алматы / ИЖС / Обычный путь / Реконструкция-Пристройка")
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
