"""
Seed: Алматы / ИЖС / Временная легализация самовольного строения / Законченные СМР.

Услуга:    SVC-IZH-001
Шаблон:    RMT-IZH-ALM-LEGALIZATION-001
12 этапов, 1 чек-лист, 1 SOP.

Использование:
    python3 business_core/seeds/seed_izhs_almaty_legalization.py --dry-run
    python3 business_core/seeds/seed_izhs_almaty_legalization.py

Идемпотентность:
    Повторный запуск не создаёт дублей — проверяет по фиксированным ID.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

# Гарантируем что корень проекта в sys.path при прямом запуске
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════════

SERVICE_ID  = "SVC-IZH-001"
TEMPLATE_ID = "RMT-IZH-ALM-LEGALIZATION-001"
CHECKLIST_ID= "CHK-IZH-ALM-LEGALIZATION-DOCS-001"
SOP_ID      = "SOP-IZH-ALM-LEGALIZATION-PRIMARY-001"
BIZ_ID      = "BIZ-001"

# ─── Данные услуги ───────────────────────────────────────────

SERVICE_DATA = dict(
    biz_id=              BIZ_ID,
    service_name=        "Узаконение реконструкции / пристройки / надстройки частного дома",
    service_category=    "legalization_reconstruction",
    city=                "Алматы",
    object_type=         "private_house_izhs",
    client_type=         "physical_person",
    description=         (
        "Узаконение самовольной реконструкции, пристройки, надстройки, бани, "
        "хозпостройки или иных изменений на участке ИЖС/ЛПХ/дача в Алматы."
    ),
    what_included=       (
        "топосъемка; согласование топосъемки; первичный замер БТИ/специалиста; "
        "технический проект; сейсмостойкое заключение; подготовка пакета в районный акимат; "
        "сопровождение подачи; технический паспорт; сопровождение комиссии; "
        "получение протокола комиссии; регистрация протокола в НАО; координация процесса"
    ),
    what_not_included=   (
        "нотариальное согласие соседей — клиент сам договаривается; "
        "госпошлины/оплата технического паспорта — клиент оплачивает сам; "
        "срочности нет"
    ),
    price_from=          "950000",
    currency=            "KZT",
    estimated_duration=  "3-4 месяца",
    required_documents=  (
        "удостоверение личности; правоустанавливающий документ; "
        "документ на земельный участок; технический паспорт если есть; "
        "кадастровый номер; фото/видео объекта; адрес объекта"
    ),
    default_roadmap_template_id= TEMPLATE_ID,
    risks=               (
        "целевое назначение земли не подходит; фактическое строение не соответствует земле; "
        "красные линии; ПДП; нарушение отступов; проблемы с соседями; "
        "отсутствие согласия соседей; сейсмические/конструктивные риски; "
        "расхождение площади по документам и факту; объект невозможно легализовать"
    ),
    contractors_needed=  (
        "топограф; специалист БТИ/замерщик; проектировщик; "
        "специалист по сейсмостойкому заключению; технический специалист; координатор"
    ),
    status=              "active",
    notes=               (
        "Для Алматы. Временная легализация самовольных строений по текущей рабочей логике. "
        "ЛПХ/дача учитываются внутри ИЖС через поле Land Purpose."
    ),
)

# ─── Данные шаблона ──────────────────────────────────────────

TEMPLATE_DATA = dict(
    template_name= "Алматы / ИЖС / временная легализация самовольного строения / законченные СМР",
    biz_id=        BIZ_ID,
    service_id=    SERVICE_ID,
    case_type=     "almaty_izhs_temporary_legalization_finished_smr",
    object_type=   "private_house_izhs",
    description=   (
        "Шаблон для легализации самовольной реконструкции, пристройки, надстройки, "
        "бани, хозпостройки или иного построенного объекта на ИЖС/ЛПХ/дача в Алматы. "
        "Применяется для уже выполненных СМР."
    ),
    status=        "active",
    notes=         (
        "Временный сценарий легализации. Финальный документ — протокол комиссии, "
        "который подлежит регистрации в НАО. АПЗ, отдельный проект после АПЗ, "
        "исполнительная съемка и акт ввода в этом сценарии не используются как основные этапы."
    ),
)

# ─── 12 этапов ───────────────────────────────────────────────

STAGES = [
    dict(
        order=1,
        stage_name=    "Первичный анализ объекта",
        description=   (
            "Проверяем фото/видео, документы, землю, фактическое строение, ПДП, "
            "красные линии, отступы, риски соседей и возможность легализации."
        ),
        required_docs= (
            "фото/видео объекта; правоустанавливающий документ; документ на землю; "
            "техпаспорт если есть; кадастровый номер; адрес объекта"
        ),
        responsible=   "manager",
        estimated_days="1",
        notes=         (
            "Expected Result: принято предварительное решение, можно ли запускать объект в легализацию. "
            "Risks: неподходящее целевое назначение; красные линии; нарушение отступов; объект невозможно легализовать"
        ),
    ),
    dict(
        order=2,
        stage_name=    "Топографическая съемка",
        description=   (
            "Заказываем топосъемку, получаем фактическую ситуацию по участку, "
            "границам, строениям, ПДП и красным линиям."
        ),
        required_docs= "адрес объекта; кадастровый номер; доступ к участку",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: нет доступа к участку; ошибки в границах; выявлены ограничения",
    ),
    dict(
        order=3,
        stage_name=    "Согласование топосъемки",
        description=   (
            "Передаем топосъемку на согласование. "
            "Согласованная топосъемка дальше используется в техническом проекте."
        ),
        required_docs= "готовая топосъемка",
        responsible=   "contractor",
        estimated_days="5",
        notes=         "Risks: замечания по съемке; задержка согласования",
    ),
    dict(
        order=4,
        stage_name=    "Договор с клиентом",
        description=   (
            "Фиксируем стоимость, сроки, состав работ, "
            "порядок оплаты и доверенность при необходимости."
        ),
        required_docs= "данные клиента; данные объекта",
        responsible=   "manager",
        estimated_days="1",
        notes=         "Risks: клиент затягивает оплату; клиент не понимает ограничения процедуры",
    ),
    dict(
        order=5,
        stage_name=    "Нотариальное согласие соседей",
        description=   (
            "Для легализации требуется согласие соседей. "
            "Клиент сам договаривается с соседями и организует нотариальное оформление."
        ),
        required_docs= "данные соседей; документы для нотариуса",
        responsible=   "client",
        estimated_days="5",
        notes=         "Risks: сосед не согласен; сосед недоступен; клиент затягивает получение согласия",
    ),
    dict(
        order=6,
        stage_name=    "Первичный замер БТИ / специалиста",
        description=   (
            "Специалист делает первичный фактический замер объекта. "
            "Эти данные используются для технического проекта и дальнейшего технического паспорта."
        ),
        required_docs= "доступ к объекту; адрес; документы клиента",
        responsible=   "contractor",
        estimated_days="3",
        notes=         (
            "Risks: нет доступа к объекту; расхождение площадей; "
            "выявлены незаявленные постройки"
        ),
    ),
    dict(
        order=7,
        stage_name=    "Технический проект + сейсмостойкое заключение",
        description=   (
            "Готовится технический проект. Сейсмостойкое заключение может быть внутри "
            "одного документа. Для этого сценария отдельный проект после АПЗ не делается."
        ),
        required_docs= (
            "согласованная топосъемка; первичный замер; "
            "документы на объект; документы на землю"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         (
            "Risks: конструктивные риски; сейсмические замечания; "
            "недостаточно исходных данных"
        ),
    ),
    dict(
        order=8,
        stage_name=    "Подача в районный акимат",
        description=   (
            "Формируем пакет и подаем в районный акимат по месту объекта."
        ),
        required_docs= (
            "согласованная топосъемка; технический проект; сейсмостойкое заключение; "
            "документы клиента; документы на землю/объект; нотариальное согласие соседей"
        ),
        responsible=   "manager",
        estimated_days="3",
        notes=         "Risks: неполный пакет; замечания акимата; отказ в принятии",
    ),
    dict(
        order=9,
        stage_name=    "Технический паспорт",
        description=   (
            "Изготавливается основной технический паспорт до комиссии. "
            "Клиент сам оплачивает госпошлины или оплату за техпаспорт."
        ),
        required_docs= (
            "первичный замер; документы клиента; документы на объект; доступ к объекту"
        ),
        responsible=   "contractor",
        estimated_days="10",
        notes=         "Risks: задержка БТИ; расхождение площадей; клиент не оплатил услуги/госпошлины",
    ),
    dict(
        order=10,
        stage_name=    "Комиссия",
        description=   (
            "Комиссия рассматривает пакет и объект, принимает решение по легализации."
        ),
        required_docs= (
            "полный пакет; технический паспорт; технический проект; "
            "согласие соседей; документы клиента и объекта"
        ),
        responsible=   "government",
        estimated_days="15",
        notes=         "Risks: замечания комиссии; отказ; необходимость доработки документов",
    ),
    dict(
        order=11,
        stage_name=    "Протокол комиссии",
        description=   (
            "Получаем протокол комиссии. Протокол является финальным документом "
            "по легализации и подлежит регистрации в НАО."
        ),
        required_docs= "решение комиссии",
        responsible=   "manager",
        estimated_days="3",
        notes=         "Risks: задержка выдачи протокола; ошибки в протоколе",
    ),
    dict(
        order=12,
        stage_name=    "Регистрация протокола в НАО",
        description=   (
            "Регистрируем протокол комиссии в НАО, "
            "чтобы изменения были официально отражены."
        ),
        required_docs= (
            "протокол комиссии; технический паспорт; "
            "документы клиента; документы на объект"
        ),
        responsible=   "manager",
        estimated_days="5",
        notes=         "Risks: замечания НАО; ошибки в документах; задержка регистрации",
    ),
]

# ─── Чек-лист ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=       "Чек-лист документов для легализации ИЖС в Алматы",
    biz_id=      BIZ_ID,
    service_id=  SERVICE_ID,
    template_id= TEMPLATE_ID,
    items=       (
        "Удостоверение личности клиента; Правоустанавливающий документ; "
        "Документ на земельный участок; Кадастровый номер; "
        "Технический паспорт если есть; Фото/видео объекта; Адрес объекта; "
        "Топосъемка; Согласованная топосъемка; Нотариальное согласие соседей; "
        "Первичный замер БТИ/специалиста; Технический проект; "
        "Сейсмостойкое заключение; Технический паспорт; "
        "Протокол комиссии; Регистрация протокола в НАО"
    ),
    completion_criteria= (
        "Полный пакет готов для подачи, комиссии и регистрации в НАО."
    ),
    status=      "active",
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=            "Как провести первичный анализ ИЖС для легализации в Алматы",
    biz_id=           BIZ_ID,
    service_id=       SERVICE_ID,
    template_id=      TEMPLATE_ID,
    purpose=          (
        "До запуска договора понять, подходит ли объект под легализацию "
        "и какие есть риски."
    ),
    steps=            (
        "1. Получить от клиента фото/видео объекта. "
        "2. Получить документы на объект и землю. "
        "3. Проверить целевое назначение земли. "
        "4. Сравнить фактическое строение с тем, что указано в документах. "
        "5. Проверить наличие пристроек, надстроек, бани, хозпостроек. "
        "6. Проверить красные линии, ПДП и ограничения. "
        "7. Проверить объект по карте map.gov4c.kz/egkn/. "
        "8. Зафиксировать, что для легализации требуется согласие соседей. "
        "9. Зафиксировать предварительные риски. "
        "10. Принять решение: брать объект в работу / нужна доп. проверка / не брать."
    ),
    expected_result=  (
        "Есть предварительное заключение по возможности легализации объекта."
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
    plan   = []
    skip   = []

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
        plan.append(f"[CREATE] {missing} stages для {TEMPLATE_ID} (уже есть: {existing_stages})")

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

    # ── 1. Service ────────────────────────────────────────────
    if _service_exists():
        skipped.append(f"Service {SERVICE_ID}")
        if verbose: print(f"  [SKIP] Service {SERVICE_ID}")
    else:
        try:
            from business_core.service_manager import create_service_record
            from business_core.sheets import get_business_sheet, BUSINESS_SHEET_NAMES
            sheet  = get_business_sheet("service_catalog")
            values = sheet.get_all_values()
            # Используем фиксированный ID — подставляем его после создания
            result = create_service_record(**SERVICE_DATA)
            if result["ok"]:
                # Переименуем авто-ID в фиксированный SVC-IZH-001
                _rename_id_in_sheet(sheet, result["service_id"], SERVICE_ID)
                created.append(f"Service {SERVICE_ID}")
                if verbose: print(f"  [OK] Service {SERVICE_ID}")
            else:
                errors.append(f"Service: {result['error']}")
                if verbose: print(f"  [ERR] Service: {result['error']}")
        except Exception as e:
            errors.append(f"Service exception: {e}")
            if verbose: print(f"  [ERR] Service exception: {e}")

    # ── 2. Template ───────────────────────────────────────────
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

    # ── 3. Stages ─────────────────────────────────────────────
    existing_count = _stages_count()
    if existing_count >= len(STAGES):
        skipped.append(f"Stages {TEMPLATE_ID} ({existing_count} уже есть)")
        if verbose: print(f"  [SKIP] Stages для {TEMPLATE_ID} ({existing_count})")
    else:
        try:
            from business_core.roadmap_template_manager import add_roadmap_template_stage
            from business_core.sheets import get_business_sheet
            stage_sheet    = get_business_sheet("roadmap_template_stages")
            stages_to_add  = STAGES[existing_count:]
            added_count    = 0
            stage_ids      = []
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
                    stage_ids.append(result["stage_id"])
                else:
                    errors.append(f"Stage {s['order']}: {result['error']}")
            created.append(f"Stages {TEMPLATE_ID} (+{added_count})")
            if verbose: print(f"  [OK] Stages: +{added_count} (итого {existing_count + added_count})")
        except Exception as e:
            errors.append(f"Stages exception: {e}")
            if verbose: print(f"  [ERR] Stages exception: {e}")

    # ── 4. Checklist ──────────────────────────────────────────
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

    # ── 5. SOP ────────────────────────────────────────────────
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
    """
    Заменить авто-ID на фиксированный seed-ID в первой колонке листа.
    Нужно только при первом создании (авто-ID ещё не занят).
    """
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
    print("Seed: Алматы / ИЖС / Легализация самовольного строения")
    print("=" * 60)

    if is_dry_run:
        print("\n[DRY-RUN] — ничего не записывается в Google Sheets\n")
        result = dry_run()
        for line in result["plan"]:
            print(f"  {line}")
        for line in result["skip"]:
            print(f"  {line}")
        print()
        if not result["plan"]:
            print("  Все записи уже существуют. Ничего делать не нужно.")
        return

    # Live mode — запрос подтверждения
    result = dry_run()
    print("\nБудет создано:")
    if result["plan"]:
        for line in result["plan"]:
            print(f"  {line}")
    else:
        print("  Всё уже существует. Ничего делать не нужно.")
        return

    if result["skip"]:
        print("\nБудет пропущено:")
        for line in result["skip"]:
            print(f"  {line}")

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
