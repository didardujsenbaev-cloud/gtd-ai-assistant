"""
Seed: Коммерческие этапы оплаты по ИЖС.

SOP:       SOP-IZH-COMMERCIAL-MILESTONES-001 — Как делить ИЖС на 3 коммерческих этапа
Checklist: CHK-IZH-COMMERCIAL-MILESTONES-001 — Чек-лист коммерческих этапов оплаты

Охватывает все 8 ИЖС-услуг (Алматы + Астана).
Существующие roadmap templates и stages НЕ меняются.

Использование:
    python3 business_core/seeds/seed_izhs_commercial_milestones_sop.py --dry-run
    python3 business_core/seeds/seed_izhs_commercial_milestones_sop.py
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

SOP_ID       = "SOP-IZH-COMMERCIAL-MILESTONES-001"
CHECKLIST_ID = "CHK-IZH-COMMERCIAL-MILESTONES-001"
BIZ_ID       = "BIZ-001"

IZH_SERVICE_IDS = (
    "SVC-IZH-001; SVC-IZH-002; SVC-IZH-003; SVC-IZH-004; "
    "SVC-IZH-AST-001; SVC-IZH-AST-002; SVC-IZH-AST-003; SVC-IZH-AST-004"
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=    "Как делить ИЖС на 3 коммерческих этапа оплаты",
    biz_id=   BIZ_ID,
    service_id=       IZH_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    purpose=  (
        "Помочь менеджеру понимать, какие рабочие этапы roadmap относятся к каждому "
        "коммерческому этапу оплаты по ИЖС, когда выставлять оплату клиенту "
        "и что считается завершением каждого коммерческого этапа."
    ),
    steps=(
        "1. ЭТАП 1 — Анализ / проверка возможности оформления. Стоимость: 150 000 тг. "
        "Цель: понять, можно ли запускать объект дальше, какие есть ограничения и какой путь подходит. "
        "Roadmap stages этапа 1: первичный анализ объекта; проверка земли, ограничений и необходимости "
        "согласий; топографическая съемка; согласование топосъемки; проверка ПДП/регламента/ситуационной "
        "схемы, если требуется; проверка водоохранной зоны, если рядом арык/река/канал; "
        "предварительное заключение по возможности оформления. "
        "Результат этапа 1: понятен путь оформления; понятны риски; понятно, есть ли смысл идти дальше; "
        "клиент получает предварительное заключение. "
        "Важно: Этап 1 не гарантирует получение АПЗ. Это этап проверки возможности. "

        "2. ЭТАП 2 — Документы до АПЗ / проектно-разрешительный этап. Стоимость: 500 000 тг. "
        "Цель: подготовить документы и пройти проектно-разрешительную часть до результата по АПЗ. "
        "Roadmap stages этапа 2: договор с клиентом; согласие соседей/дольщиков, если нужно; "
        "первичный замер БТИ/специалиста; техническое обследование, если требуется; "
        "сейсмостойкое заключение, если требуется для Алматы; технический/эскизный проект; "
        "формирование пакета на АПЗ; подача на АПЗ; сопровождение рассмотрения; "
        "получение результата: АПЗ/замечания/отказ. "
        "Результат этапа 2: пакет на АПЗ подготовлен; подача выполнена; "
        "получен результат госоргана: АПЗ, замечания или отказ. "
        "При отказе или замечаниях дальнейшая стратегия согласуется отдельно. "
        "Важно: АПЗ зависит от госоргана. Компания не гарантирует выдачу АПЗ. "
        "При отказе этап считается выполненным, если подготовка и подача произведены. "

        "3. ЭТАП 3 — Технический паспорт / акт ввода / регистрация. Стоимость: 300 000 тг. "
        "Цель: закрыть объект после АПЗ и зарегистрировать изменения. "
        "Roadmap stages этапа 3: технический паспорт; подготовка акта ввода; "
        "согласование акта ввода в архитектуре; регистрация акта ввода в НАО; "
        "финальная проверка регистрации. "
        "Результат этапа 3: технический паспорт готов; акт ввода подготовлен и согласован; "
        "акт ввода зарегистрирован в НАО; объект официально оформлен. "

        "4. ИТОГО базовая модель: Этап 1 — 150 000 тг; Этап 2 — 500 000 тг; "
        "Этап 3 — 300 000 тг; Итого: 950 000 тг. "

        "5. ОБЩИЕ ПРАВИЛА: "
        "Это коммерческие этапы, а не отдельные услуги. "
        "Roadmap stages остаются рабочими этапами — коммерческий этап объединяет несколько stages. "
        "Оплата следующего этапа запускается до начала работ по нему. "
        "Если объект сложный, цена индивидуальная. "
        "Госпошлины, БТИ, нотариальные согласия, штрафы, СМР, подрядчики и повторные подачи "
        "не входят, если отдельно не указано в договоре. "
        "Если госорган выдал отказ/замечания, оплаченный этап не считается невыполненным, "
        "если компания сделала подготовку и подачу. "
        "Если клиент меняет исходные данные или нужны повторные подачи — это согласуется отдельно. "

        "6. ПРИМЕР для RMT-IZH-ALM-STANDARD-002 (законченные СМР): "
        "Этап 1 — 150 000 тг: 1. Первичный анализ объекта и фактически выполненных СМР; "
        "2. Проверка земли, ограничений и необходимости согласий; "
        "3. Топографическая съемка; 4. Согласование топосъемки. "
        "Этап 2 — 500 000 тг: 5. Договор с клиентом; "
        "6. Согласие соседей/дольщиков, если нужно; 7. Первичный замер БТИ/специалиста; "
        "8. Техническое обследование/сейсмостойкое заключение; "
        "9. Технический проект по фактически выполненным СМР; 10. Получение АПЗ. "
        "Этап 3 — 300 000 тг: 11. Технический паспорт; "
        "12. Подготовка и согласование акта ввода; 13. Регистрация акта ввода в НАО."
    ),
    expected_result=(
        "Менеджер понимает, как разбить roadmap по ИЖС на 3 коммерческих этапа оплаты "
        "и может объяснить это клиенту."
    ),
    owner_role= "manager",
    status=     "active",
    notes=(
        "Кросс-сервисный SOP для коммерческой модели ИЖС. "
        "Услуги: " + IZH_SERVICE_IDS + ". "
        "Roadmap stages и templates НЕ изменяются — только коммерческая разбивка."
    ),
)

# ─── Checklist ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=    "Чек-лист коммерческих этапов оплаты ИЖС",
    biz_id=   BIZ_ID,
    service_id=       IZH_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    items=(
        "Определена услуга ИЖС; "
        "Определен город: Алматы / Астана; "
        "Определен roadmap template; "
        "Клиенту объяснено, что roadmap stages и коммерческие этапы — разные вещи; "
        "Клиенту объяснен Этап 1 — анализ / проверка возможности; "
        "Клиенту объяснена стоимость Этапа 1; "
        "Клиенту объяснен результат Этапа 1; "
        "Клиенту объяснено, что Этап 1 не гарантирует АПЗ; "
        "Клиенту объяснен Этап 2 — документы до АПЗ; "
        "Клиенту объяснена стоимость Этапа 2; "
        "Клиенту объяснен риск АПЗ; "
        "Клиенту объяснено, что отказ/замечания госоргана не делают этап невыполненным; "
        "Клиенту объяснен Этап 3 — техпаспорт / акт ввода / регистрация; "
        "Клиенту объяснена стоимость Этапа 3; "
        "Клиенту объяснено, что не входит в стоимость; "
        "Клиенту объяснены доп. расходы: БТИ, нотариус, госпошлины, штрафы, СМР, подрядчики; "
        "Порядок оплаты зафиксирован в КП/договоре; "
        "Следующий коммерческий этап не запускается без оплаты; "
        "Все риски зафиксированы в notes или договоре; "
        "Если объект нестандартный, цена вынесена на индивидуальное согласование"
    ),
    completion_criteria=(
        "Менеджер понимает, как разбить roadmap по ИЖС на 3 коммерческих этапа оплаты "
        "и может объяснить это клиенту."
    ),
    status=  "active",
    notes=   "Используется вместе с SOP-IZH-COMMERCIAL-MILESTONES-001.",
)


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

    if _checklist_exists():
        skip.append(f"[SKIP] Checklist {CHECKLIST_ID} уже существует")
    else:
        plan.append(f"[CREATE] Checklist {CHECKLIST_ID}: {CHECKLIST_DATA['title']}")

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

    return {"created": created, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seed: Коммерческие этапы оплаты ИЖС")
    print(f"SOP: {SOP_ID}")
    print(f"CHK: {CHECKLIST_ID}")
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
