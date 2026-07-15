"""
Seed: Коммерческие предложения (КП) по ИЖС.

DOC-IZH-KP-001 — реконструкция / пристройка / надстройка
DOC-IZH-KP-002 — новое строительство
DOC-IZH-KP-003 — хозпостройка при существующем доме
DOC-IZH-KP-004 — снос дома / хозпостройки
SOP-DOC-IZH-KP-001 — как использовать КП по ИЖС

DOC-шаблоны хранятся как document_template records (document_type=commercial_offer)
без изменения архитектуры.

Использование:
    python3 business_core/seeds/seed_izhs_commercial_offer_templates.py --dry-run
    python3 business_core/seeds/seed_izhs_commercial_offer_templates.py
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

SOP_ID  = "SOP-DOC-IZH-KP-001"
BIZ_ID  = "BIZ-001"

DOC_IDS = [
    "DOC-IZH-KP-001",
    "DOC-IZH-KP-002",
    "DOC-IZH-KP-003",
    "DOC-IZH-KP-004",
]

IZH_ALL_SERVICE_IDS = (
    "SVC-IZH-001; SVC-IZH-002; SVC-IZH-003; SVC-IZH-004; "
    "SVC-IZH-AST-001; SVC-IZH-AST-002; SVC-IZH-AST-003; SVC-IZH-AST-004"
)

# ─── SOP — как использовать КП ───────────────────────────────

SOP_DATA = dict(
    title=    "Как использовать коммерческие предложения по ИЖС",
    biz_id=   BIZ_ID,
    service_id=       IZH_ALL_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    purpose=  (
        "Помочь менеджеру выбрать правильный шаблон коммерческого предложения по ИЖС "
        "и адаптировать его под город, объект, стоимость, сроки и риски."
    ),
    steps=(
        "1. Сначала принять клиента по SOP-IZH-INTAKE-001. "
        "2. Затем классифицировать клиента по SOP-IZH-ROUTER-001. "
        "3. Определить service_id и template_id. "
        "4. Выбрать подходящее КП: "
        "DOC-IZH-KP-001 — реконструкция / пристройка / надстройка; "
        "DOC-IZH-KP-002 — новое строительство; "
        "DOC-IZH-KP-003 — хозпостройка; "
        "DOC-IZH-KP-004 — снос. "
        "5. Заполнить переменные: город; объект; цена от; срок; "
        "что входит; что не входит; риски; следующий шаг. "
        "6. Не обещать 100% результат. "
        "7. Не гарантировать АПЗ и решения госорганов. "
        "8. Если объект сложный — сначала предложить диагностику/первичную проверку."
    ),
    expected_result=(
        "Менеджер может быстро подготовить коммерческое предложение по ИЖС "
        "без ручного написания с нуля."
    ),
    owner_role= "manager",
    status=     "active",
    notes=(
        "Используется вместе с SOP-IZH-INTAKE-001 и SOP-IZH-ROUTER-001. "
        "КП хранятся как doc_template records: " + ", ".join(DOC_IDS) + "."
    ),
)

# ─── 4 Doc Templates — КП ─────────────────────────────────────

_KP_COMMON_FOOTER = (
    "\nВажно:\n"
    "АПЗ, согласования и регистрация зависят от документов, фактического состояния "
    "объекта и решений госорганов. Компания не гарантирует положительное решение "
    "госорганов, но сопровождает процесс и заранее предупреждает о рисках."
)

DOCS = [
    dict(
        doc_id=       "DOC-IZH-KP-001",
        service_ids=  "SVC-IZH-001; SVC-IZH-AST-001",
        title=        "Коммерческое предложение — реконструкция / пристройка / надстройка ИЖС",
        document_type="commercial_offer",
        description=  (
            "Коммерческое предложение\n\n"
            "Услуга:\n"
            "Сопровождение оформления реконструкции, пристройки или надстройки частного дома.\n\n"
            "Объект: Частный дом / ИЖС\n"
            "Город: {{city}}\n"
            "Стоимость: от {{price_from}} тенге\n"
            "Срок: ориентировочно {{estimated_duration}}\n\n"
            "В работу входит:\n"
            "1. Первичный анализ объекта и документов\n"
            "2. Проверка документов на дом и земельный участок\n"
            "3. Анализ фактических изменений\n"
            "4. Подготовка проектной части\n"
            "5. Получение АПЗ\n"
            "6. Сопровождение СМР, если работы ещё не выполнены\n"
            "7. Изготовление технического паспорта\n"
            "8. Подготовка акта ввода\n"
            "9. Согласование акта ввода\n"
            "10. Регистрация изменений в НАО\n\n"
            "Для Алматы дополнительно может потребоваться:\n"
            "- топосъёмка\n"
            "- согласование топосъёмки\n"
            "- техническое обследование\n"
            "- сейсмостойкое заключение\n"
            "- согласие соседей/дольщиков\n"
            "- проверка ПДП/регламента/ситуационной схемы\n"
            "- проверка водоохранной зоны\n\n"
            "Для Астаны процедура обычно проще:\n"
            "- сейсмостойкость не требуется\n"
            "- топосъёмка и ПДП/регламент проверяются по ситуации\n"
            "- техническое обследование только при необходимости\n\n"
            "Не входит, если отдельно не указано в договоре:\n"
            "- строительно-монтажные работы\n"
            "- госпошлины\n"
            "- оплата технического паспорта\n"
            "- нотариальные согласия\n"
            "- штрафы\n"
            "- повторные подачи после существенных изменений\n"
            "- дополнительные согласования\n"
            + _KP_COMMON_FOOTER +
            "\n\nДля начала работы нужно:\n"
            "1. Фото/видео объекта\n"
            "2. Документы на дом\n"
            "3. Документы на землю\n"
            "4. Технический паспорт, если есть\n"
            "5. Адрес и кадастровый номер\n"
            "6. Удостоверение личности собственника\n\n"
            "Следующий шаг:\n"
            "После получения документов и фото/видео мы проводим первичную проверку "
            "и подтверждаем точный путь оформления."
        ),
        status=  "active",
        notes=   "Алматы: SVC-IZH-001. Астана: SVC-IZH-AST-001. Переменные: {{city}}, {{price_from}}, {{estimated_duration}}.",
    ),
    dict(
        doc_id=       "DOC-IZH-KP-002",
        service_ids=  "SVC-IZH-002; SVC-IZH-AST-002",
        title=        "Коммерческое предложение — новое строительство частного дома",
        document_type="commercial_offer",
        description=  (
            "Коммерческое предложение\n\n"
            "Услуга:\n"
            "Сопровождение нового строительства частного дома на голом участке.\n\n"
            "Объект: Новый жилой дом на участке ИЖС. К дому могут относиться хозпостройки: "
            "баня, гараж, сарай, летняя кухня и другие вспомогательные строения.\n"
            "Город: {{city}}\n"
            "Стоимость: от {{price_from}} тенге\n"
            "Срок: ориентировочно {{estimated_duration}}\n\n"
            "В работу входит:\n"
            "1. Первичный анализ участка\n"
            "2. Проверка документов на земельный участок\n"
            "3. Проверка целевого назначения земли\n"
            "4. Проверка ограничений участка\n"
            "5. Задание на проектирование\n"
            "6. Эскизный проект\n"
            "7. Получение АПЗ\n"
            "8. Сопровождение после проведения СМР\n"
            "9. Исполнительная съёмка, если требуется\n"
            "10. Технический паспорт\n"
            "11. Подготовка акта ввода\n"
            "12. Согласование акта ввода\n"
            "13. Регистрация в НАО\n\n"
            "Для Алматы:\n"
            "- ПДП/регламент/ситуационная схема обычно проверяются на первом этапе\n"
            "- топосъёмка чаще требуется\n"
            "- исполнительная съёмка и её согласование нужны\n"
            "- водоохранная зона проверяется при наличии арыка/реки/канала рядом\n\n"
            "Для Астаны:\n"
            "- процедура обычно проще\n"
            "- ПДП/регламент и топосъёмка используются по ситуации\n"
            "- сейсмостойкость не требуется\n\n"
            "Не входит, если отдельно не указано:\n"
            "- строительно-монтажные работы\n"
            "- технические условия\n"
            "- рабочий проект/АР/КЖ\n"
            "- госпошлины\n"
            "- оплата технического паспорта\n"
            "- штрафы\n"
            "- дополнительные согласования\n\n"
            "Важно:\n"
            "Услуга применяется для голого участка. Если на участке уже есть дом и нужно оформить "
            "отдельную хозпостройку, используется отдельная услуга. "
            "Если меняется существующий дом, это реконструкция/пристройка/надстройка.\n\n"
            "Для начала работы нужно:\n"
            "1. Документ на земельный участок\n"
            "2. Адрес участка\n"
            "3. Кадастровый номер\n"
            "4. Фото/видео участка\n"
            "5. Удостоверение личности собственника\n"
            "6. Пожелания по дому и хозпостройкам\n\n"
            "Следующий шаг:\n"
            "После первичной проверки участка и документов определяем путь, риски и точный состав работ."
        ),
        status=  "active",
        notes=   "Алматы: SVC-IZH-002. Астана: SVC-IZH-AST-002. Переменные: {{city}}, {{price_from}}, {{estimated_duration}}.",
    ),
    dict(
        doc_id=       "DOC-IZH-KP-003",
        service_ids=  "SVC-IZH-003; SVC-IZH-AST-003",
        title=        "Коммерческое предложение — хозпостройка при существующем доме",
        document_type="commercial_offer",
        description=  (
            "Коммерческое предложение\n\n"
            "Услуга:\n"
            "Сопровождение строительства или оформления отдельно стоящей хозпостройки "
            "при существующем зарегистрированном доме.\n\n"
            "Объект: Баня, гараж, сарай, летняя кухня или другая отдельно стоящая хозпостройка.\n"
            "Город: {{city}}\n"
            "Стоимость: от {{price_from}} тенге\n"
            "Срок: ориентировочно {{estimated_duration}}\n\n"
            "В работу входит:\n"
            "1. Проверка существующего зарегистрированного дома\n"
            "2. Проверка документов на земельный участок\n"
            "3. Проверка расположения будущей или существующей хозпостройки\n"
            "4. Подготовка задания на проектирование\n"
            "5. Эскизный проект хозпостройки\n"
            "6. Получение АПЗ\n"
            "7. Сопровождение после СМР\n"
            "8. Исполнительная съёмка, если требуется\n"
            "9. Технический паспорт\n"
            "10. Акт ввода\n"
            "11. Регистрация в НАО\n\n"
            "Важно:\n"
            "Если хозпостройка пристроена к дому, это не отдельная хозпостройка, "
            "а реконструкция/пристройка дома. Тогда используется другая услуга.\n\n"
            "Не входит:\n"
            "- строительно-монтажные работы\n"
            "- вывоз мусора\n"
            "- госпошлины\n"
            "- оплата технического паспорта\n"
            "- нотариальные согласия\n"
            "- штрафы\n"
            "- дополнительные согласования\n\n"
            "Для начала работы нужно:\n"
            "1. Документы на земельный участок\n"
            "2. Документы на существующий дом\n"
            "3. Технический паспорт, если есть\n"
            "4. Фото/видео места хозпостройки\n"
            "5. Адрес и кадастровый номер\n"
            "6. Удостоверение личности собственника\n\n"
            "Следующий шаг:\n"
            "После просмотра документов и фото/видео определяем, "
            "это отдельная хозпостройка или реконструкция/пристройка дома."
        ),
        status=  "active",
        notes=   "Алматы: SVC-IZH-003. Астана: SVC-IZH-AST-003. Переменные: {{city}}, {{price_from}}, {{estimated_duration}}.",
    ),
    dict(
        doc_id=       "DOC-IZH-KP-004",
        service_ids=  "SVC-IZH-004; SVC-IZH-AST-004",
        title=        "Коммерческое предложение — снос дома / хозпостройки",
        document_type="commercial_offer",
        description=  (
            "Коммерческое предложение\n\n"
            "Услуга:\n"
            "Сопровождение процедуры сноса дома или хозпостройки.\n\n"
            "Объект: Жилой дом, баня, гараж, сарай или другая хозпостройка.\n"
            "Город: {{city}}\n"
            "Стоимость: от 150 000 тенге\n"
            "Срок: ориентировочно 1–2 месяца\n\n"
            "В работу входит:\n"
            "1. Проверка документов на объект\n"
            "2. Проверка документов на земельный участок\n"
            "3. Проверка / получение технического паспорта\n"
            "4. Техническое обследование объекта\n"
            "5. Заключение о возможности сноса\n"
            "6. Получение решения архитектуры на снос\n"
            "7. Подготовка акта сноса\n"
            "8. Регистрация сноса / изменений в госорганах\n\n"
            "Не входит:\n"
            "- физический демонтаж объекта\n"
            "- вывоз строительного мусора\n"
            "- спецтехника\n"
            "- госпошлины\n"
            "- оплата технического паспорта\n"
            "- штрафы\n"
            "- дополнительные согласования\n\n"
            "Важно:\n"
            "Физический снос выполняет клиент или подрядчик. "
            "Наша услуга — документальное сопровождение процедуры сноса и регистрация изменений.\n\n"
            "Для начала работы нужно:\n"
            "1. Документы на объект\n"
            "2. Документы на земельный участок\n"
            "3. Технический паспорт, если есть\n"
            "4. Фото/видео объекта\n"
            "5. Адрес и кадастровый номер\n"
            "6. Удостоверение личности собственника\n\n"
            "Следующий шаг:\n"
            "После проверки документов определяем порядок оформления сноса "
            "и список недостающих документов."
        ),
        status=  "active",
        notes=   "Алматы: SVC-IZH-004. Астана: SVC-IZH-AST-004. Фиксированная цена от 150 000 тг.",
    ),
]


# ═══════════════════════════════════════════════════════════════
# Idempotency helpers
# ═══════════════════════════════════════════════════════════════

def _is_quota_error(e: Exception) -> bool:
    return "429" in str(e) or "Quota exceeded" in str(e)


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


def _doc_exists(doc_id: str) -> bool:
    try:
        from business_core.knowledge_manager import find_document_template_by_id
        return find_document_template_by_id(doc_id) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_doc_exists({doc_id}): quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_doc_exists({doc_id}) error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Dry-run preview
# ═══════════════════════════════════════════════════════════════

def dry_run() -> dict:
    plan = []
    skip = []

    if _sop_exists():
        skip.append(f"[SKIP] SOP {SOP_ID} уже существует")
    else:
        plan.append(f"[CREATE] SOP {SOP_ID}: {SOP_DATA['title']}")

    for doc in DOCS:
        did = doc["doc_id"]
        if _doc_exists(did):
            skip.append(f"[SKIP] {did} уже существует")
        else:
            plan.append(f"[CREATE] {did}: {doc['title']}")

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

    # ── Doc Templates — КП ────────────────────────────────────
    for doc in DOCS:
        did = doc["doc_id"]
        if _doc_exists(did):
            skipped.append(did)
            if verbose: print(f"  [SKIP] {did}")
            continue
        try:
            from business_core.knowledge_manager import create_document_template_record
            from business_core.sheets import get_business_sheet
            result = create_document_template_record(
                title=         doc["title"],
                biz_id=        BIZ_ID,
                service_id=    doc["service_ids"],
                document_type= doc["document_type"],
                description=   doc["description"],
                status=        doc["status"],
                notes=         doc["notes"],
            )
            if result["ok"]:
                sheet = get_business_sheet("document_template_registry")
                _rename_id_in_sheet(sheet, result["doc_template_id"], did)
                created.append(did)
                if verbose: print(f"  [OK] {did}")
            else:
                errors.append(f"{did}: {result['error']}")
                if verbose: print(f"  [ERR] {did}: {result['error']}")
        except Exception as e:
            errors.append(f"{did} exception: {e}")
            if verbose: print(f"  [ERR] {did} exception: {e}")

    return {"created": created, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seed: КП по ИЖС (коммерческие предложения)")
    print(f"SOP: {SOP_ID} | Шаблонов КП: {len(DOCS)}")
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
