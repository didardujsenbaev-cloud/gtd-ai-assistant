"""
Seed: Первичный приём клиента по ИЖС.

SOP:       SOP-IZH-INTAKE-001 — Как принять клиента по ИЖС
Checklist: CHK-IZH-INTAKE-001 — Первичная анкета клиента ИЖС

Охватывает все 8 ИЖС-услуг (Алматы + Астана).
Связь с несколькими service_id — через поле service_id с разделителем «; »
(без изменения архитектуры).

Использование:
    python3 business_core/seeds/seed_izhs_intake_sop.py --dry-run
    python3 business_core/seeds/seed_izhs_intake_sop.py
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

SOP_ID       = "SOP-IZH-INTAKE-001"
CHECKLIST_ID = "CHK-IZH-INTAKE-001"
BIZ_ID       = "BIZ-001"

IZH_SERVICE_IDS = (
    "SVC-IZH-001; SVC-IZH-002; SVC-IZH-003; SVC-IZH-004; "
    "SVC-IZH-AST-001; SVC-IZH-AST-002; SVC-IZH-AST-003; SVC-IZH-AST-004"
)

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=    "Как принять клиента по ИЖС",
    biz_id=   BIZ_ID,
    service_id=       IZH_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    purpose=  (
        "Дать менеджеру, оператору или ассистенту понятный порядок первичного "
        "общения с клиентом по ИЖС: собрать вводные данные, документы, фото/видео, "
        "понять город и тип ситуации, затем выбрать service_id и template_id "
        "через SOP-IZH-ROUTER-001."
    ),
    steps=(
        "1. Приветствие: поздороваться, коротко объяснить что нужно понять ситуацию по объекту, "
        "сказать что после первичной проверки можно назвать путь, ориентировочную стоимость и сроки. "

        "2. Обязательные вопросы клиенту: "
        "(1) В каком городе объект? Алматы / Астана / другой город. "
        "(2) Что у вас за объект? частный дом / земельный участок / баня / гараж / сарай / "
        "летняя кухня / другая хозпостройка / объект на снос. "
        "(3) Участок голый или дом уже есть? голый участок / дом уже есть / есть дом и хозпостройки / не знаю. "
        "(4) Что вы хотите сделать? построить новый дом / узаконить уже построенный дом / "
        "сделать пристройку / узаконить пристройку / сделать надстройку / узаконить надстройку / "
        "построить хозпостройку / узаконить хозпостройку / снести объект / получить консультацию. "
        "(5) Работы уже выполнены или только планируются? уже построено / частично построено / "
        "только планируем / хотим снести. "
        "(6) Если хозпостройка: отдельно стоит / пристроена к дому / только планируется / уже построена. "
        "(7) Документы: удостоверение личности / документ на землю / документы на дом / "
        "технический паспорт / кадастровый номер / адрес объекта. "
        "(8) Фото/видео: фото участка / фото дома снаружи / фото пристройки/надстройки / "
        "фото хозпостройки / видео обхода / фото документов. "
        "(9) Спорные моменты: соседи против / объект близко к границе / рядом арык/речка/канал / "
        "нет техпаспорта / нет документов на землю / дом не зарегистрирован / уже был отказ / "
        "штраф или предписание / нужно срочно. "

        "3. Обязательно запросить: город; адрес объекта; кадастровый номер если есть; "
        "фото/видео объекта; документы на землю; документы на дом/объект если есть; "
        "техпаспорт если есть; кратко что хочет сделать. "

        "4. После сбора данных: не обещать результат; не говорить точный путь без проверки; "
        "передать данные менеджеру или применить SOP-IZH-ROUTER-001; "
        "выбрать service_id и template_id; если есть сомнение — статус 'нужна проверка менеджера'. "

        "5. Правильные формулировки: "
        "'Сначала нужно посмотреть документы и фактическое состояние объекта.' "
        "'После первичной проверки скажем, каким путем лучше идти.' "
        "'По АПЗ и госорганам есть риски, поэтому сначала делаем анализ.' "
        "'Точную стоимость и сроки можно зафиксировать после просмотра документов и фото/видео.' "
        "Не использовать: 'точно узаконим' / '100% получится' / 'АПЗ точно выйдет' / "
        "'проблем не будет' / 'сроки гарантируем'. "

        "6. Сразу передавать менеджеру если: уже был отказ; спор с соседями; "
        "объект рядом с арыком/речкой/каналом; дом не зарегистрирован; нет документов на землю; "
        "объект построен давно без документов; клиент хочет срочно; "
        "клиент не понимает что хочет оформить; объект в другом городе; "
        "предписание/штраф/суд; большой или нестандартный объект. "

        "7. Связь с классификатором: после intake применить SOP-IZH-ROUTER-001 — "
        "определить город; определить тип ситуации; выбрать service_id; выбрать template_id. "

        "8. Примеры первичного ответа: "
        "A: 'Здравствуйте. Чтобы понять, каким путем можно оформить объект, отправьте: "
        "город, адрес, фото/видео объекта, документы на землю, документы на дом и техпаспорт если есть. "
        "Также напишите, работы уже выполнены или только планируете.' "
        "B: 'Если это пристройка к дому — это обычно идет как реконструкция. "
        "Если хозпостройка стоит отдельно — это отдельная услуга. "
        "Сначала посмотрим фото/видео и документы, потом скажем точный путь.' "
        "C: 'По таким объектам сначала делаем первичный анализ. "
        "АПЗ и решения госорганов заранее гарантировать нельзя, "
        "поэтому важно сначала проверить документы, землю и фактическое состояние.'"
    ),
    expected_result=(
        "Оператор собрал минимально достаточную информацию для первичной классификации "
        "клиента ИЖС и определил service_id/template_id или передал на проверку менеджеру."
    ),
    owner_role= "operator",
    status=     "active",
    notes=(
        "Intake SOP для всех ИЖС-услуг: " + IZH_SERVICE_IDS + ". "
        "После intake использовать SOP-IZH-ROUTER-001 для выбора service_id и template_id."
    ),
)

# ─── Checklist ────────────────────────────────────────────────

CHECKLIST_DATA = dict(
    title=    "Первичная анкета клиента ИЖС",
    biz_id=   BIZ_ID,
    service_id=       IZH_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    items=(
        "Город объекта уточнен; "
        "Адрес объекта получен; "
        "Кадастровый номер получен если есть; "
        "Понятно, голый участок или дом уже есть; "
        "Понятно, что клиент хочет сделать; "
        "Понятно, работы уже выполнены или только планируются; "
        "Понятно, объект — дом или хозпостройка; "
        "Если хозпостройка — понятно, отдельно стоит или пристроена к дому; "
        "Уточнено, нужен ли снос; "
        "Фото объекта запрошены; "
        "Видео объекта запрошено если нужно; "
        "Документы на землю запрошены; "
        "Документы на дом/объект запрошены; "
        "Технический паспорт запрошен если есть; "
        "Уточнено наличие соседских споров; "
        "Уточнено, рядом ли арык/речка/канал; "
        "Уточнено, были ли отказы/предписания/штрафы; "
        "Клиенту не обещан 100% результат; "
        "Данные переданы на классификацию через SOP-IZH-ROUTER-001; "
        "Выбран service_id или поставлен статус 'нужна проверка менеджера'; "
        "Выбран template_id или поставлен статус 'нужна проверка менеджера'"
    ),
    completion_criteria=(
        "Оператор собрал минимально достаточную информацию для первичной классификации "
        "клиента ИЖС и передачи в работу менеджеру или запуска подходящего "
        "service_id/template_id."
    ),
    status=  "active",
    notes=   "Используется вместе с SOP-IZH-INTAKE-001 и SOP-IZH-ROUTER-001.",
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
    print("Seed: Первичный приём клиента по ИЖС")
    print("SOP: SOP-IZH-INTAKE-001 | CHK: CHK-IZH-INTAKE-001")
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
