"""
Seed: SOP-классификатор ИЖС (общий).

SOP:       SOP-IZH-ROUTER-001 — Как определить услугу ИЖС
Checklist: CHK-IZH-ROUTER-001 — Чек-лист классификации клиента ИЖС

Охватывает все 8 ИЖС-услуг в Алматы и Астане.
Связь с несколькими service_id реализована через разделитель «; »
в поле service_id (без изменения архитектуры).

Использование:
    python3 business_core/seeds/seed_izhs_router_sop.py --dry-run
    python3 business_core/seeds/seed_izhs_router_sop.py
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

SOP_ID       = "SOP-IZH-ROUTER-001"
CHECKLIST_ID = "CHK-IZH-ROUTER-001"
BIZ_ID       = "BIZ-001"

# Все ИЖС-услуги, к которым относится роутер
IZH_SERVICE_IDS = (
    "SVC-IZH-001; SVC-IZH-002; SVC-IZH-003; SVC-IZH-004; "
    "SVC-IZH-AST-001; SVC-IZH-AST-002; SVC-IZH-AST-003; SVC-IZH-AST-004"
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=    "Как определить услугу ИЖС",
    biz_id=   BIZ_ID,
    service_id= IZH_SERVICE_IDS,
    template_id= "",
    template_stage_id= "",
    purpose=  (
        "Помочь менеджеру, оператору или ассистенту быстро классифицировать "
        "входящего клиента по ИЖС и выбрать правильный service_id и template_id "
        "для Алматы или Астаны."
    ),
    steps=(
        # 1. Город
        "1. Определить город клиента: Алматы / Астана / другой город "
        "(другой — без автоматического шаблона, вручную). "

        # 2. Тип объекта
        "2. Определить, что у клиента: уже есть существующий дом; голый участок; "
        "отдельная хозпостройка; объект на снос. "

        # 3. Снос
        "3. Снос дома или хозпостройки — "
        "Алматы: SVC-IZH-004 / RMT-IZH-ALM-DEMOLITION-001. "
        "Астана: SVC-IZH-AST-004 / RMT-IZH-AST-DEMOLITION-001. "

        # 4. Голый участок, новый дом
        "4. Голый участок, новый дом (включая баню/гараж/сарай на том же участке) — "
        "Алматы: SVC-IZH-002 / RMT-IZH-ALM-NEWBUILD-001. "
        "Астана: SVC-IZH-AST-002 / RMT-IZH-AST-NEWBUILD-001. "
        "Важно: баня/гараж на голом участке вместе с домом — это новое строительство, "
        "не отдельная хозпостройка. "

        # 5. Существующий дом + отдельная хозпостройка
        "5. Дом зарегистрирован + клиент хочет отдельно стоящую баню/гараж/сарай — "
        "Алматы: SVC-IZH-003 / RMT-IZH-ALM-OUTBUILDING-001. "
        "Астана: SVC-IZH-AST-003 / RMT-IZH-AST-OUTBUILDING-001. "
        "Важно: если хозпостройка пристроена к дому — это реконструкция, не SVC-IZH-003. "

        # 6. Реконструкция / пристройка / надстройка
        "6. Реконструкция / пристройка / надстройка / пристроенная хозпостройка / "
        "изменение конфигурации дома — "
        "Алматы: SVC-IZH-001. Выбор шаблона: "
        "(a) временная легализация самовольного строения — RMT-IZH-ALM-LEGALIZATION-001; "
        "(b) обычный путь, СМР ещё не выполнены — RMT-IZH-ALM-STANDARD-001; "
        "(c) обычный путь, СМР уже выполнены — RMT-IZH-ALM-STANDARD-002. "
        "Астана: SVC-IZH-AST-001 / RMT-IZH-AST-RECON-001 "
        "(один универсальный шаблон; если СМР уже выполнены — этап отмечается выполненным, "
        "фиксируется риск). "

        # 7. Клиент не знает — контрольные вопросы
        "7. Если клиент не знает — задать: В каком городе объект? "
        "Участок голый или дом уже есть? "
        "Что хотите сделать: построить, пристроить, узаконить или снести? "
        "Объект уже построен или только планируется? "
        "Это дом или хозпостройка? "
        "Хозпостройка отдельно стоит или пристроена к дому? "
        "Есть ли техпаспорт? Документы на землю? Фото/видео? "

        # 8. Правило выбора
        "8. Правило: голый участок + новый дом = новое строительство. "
        "Дом есть + меняется сам дом = реконструкция. "
        "Дом есть + отдельная баня/гараж/сарай = хозпостройка. "
        "Убрать объект из регистрации = снос. "
        "Алматы сложнее (3 шаблона по SVC-IZH-001), Астана проще (1 шаблон). "
        "Сомнение новое строительство vs реконструкция — передать менеджеру. "
        "Сомнение хозпостройка vs пристройка — смотреть физическую связь с домом. "

        # 9. Примеры
        "9. Примеры: "
        "Алматы, дом есть, пристроил комнату, уже построил → SVC-IZH-001 / RMT-IZH-ALM-STANDARD-002. "
        "Алматы, самовольное строение → SVC-IZH-001 / RMT-IZH-ALM-LEGALIZATION-001. "
        "Астана, пристройка к дому → SVC-IZH-AST-001 / RMT-IZH-AST-RECON-001. "
        "Алматы, голый участок, дом и баня → SVC-IZH-002 / RMT-IZH-ALM-NEWBUILD-001. "
        "Астана, дом есть, отдельный гараж → SVC-IZH-AST-003 / RMT-IZH-AST-OUTBUILDING-001. "
        "Алматы, снос старой бани → SVC-IZH-004 / RMT-IZH-ALM-DEMOLITION-001."
    ),
    expected_result=(
        "Менеджер или оператор определил service_id и template_id "
        "для клиента ИЖС в Алматы или Астане."
    ),
    owner_role= "manager",
    status=     "active",
    notes=(
        "Кросс-сервисный классификатор ИЖС. "
        "Применяется к услугам: " + IZH_SERVICE_IDS + ". "
        "Если город не Алматы и не Астана — вести вручную без автошаблона."
    ),
)

# ─── Checklist ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=    "Чек-лист классификации клиента ИЖС",
    biz_id=   BIZ_ID,
    service_id= IZH_SERVICE_IDS,
    template_id= "",
    template_stage_id= "",
    items=(
        "Город определен: Алматы / Астана / другой; "
        "Понятно, голый участок или есть существующий дом; "
        "Понятно, клиент хочет построить / пристроить / узаконить / снести; "
        "Понятно, СМР уже выполнены или только планируются; "
        "Понятно, объект — дом или хозпостройка; "
        "Если хозпостройка — понятно, отдельно стоит или пристроена к дому; "
        "Проверено наличие документов на землю; "
        "Проверено наличие документов на дом/объект; "
        "Проверено наличие техпаспорта если есть; "
        "Получены фото/видео объекта; "
        "Выбран service_id; "
        "Выбран template_id; "
        "Если есть сомнение — передано менеджеру"
    ),
    completion_criteria=(
        "Менеджер или оператор может корректно выбрать service_id и template_id "
        "для клиента ИЖС по Алматы или Астане."
    ),
    status=  "active",
    notes=   "Используется вместе с SOP-IZH-ROUTER-001.",
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
    print("Seed: SOP-классификатор ИЖС (Алматы + Астана)")
    print("SOP: SOP-IZH-ROUTER-001 | CHK: CHK-IZH-ROUTER-001")
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
