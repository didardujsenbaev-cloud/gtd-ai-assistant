"""
Seed: WhatsApp-шаблоны сообщений по ИЖС.

SOP:      SOP-IZH-WHATSAPP-001 — Как общаться с клиентом по ИЖС в WhatsApp
Templates: MSG-IZH-WA-001…007  — хранятся как FAQ records (category=whatsapp_template)
           без изменения архитектуры.

Охватывает все 8 ИЖС-услуг (Алматы + Астана).
SendPulse / WABA API не используется.

Использование:
    python3 business_core/seeds/seed_izhs_whatsapp_templates.py --dry-run
    python3 business_core/seeds/seed_izhs_whatsapp_templates.py
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

SOP_ID  = "SOP-IZH-WHATSAPP-001"
BIZ_ID  = "BIZ-001"

IZH_SERVICE_IDS = (
    "SVC-IZH-001; SVC-IZH-002; SVC-IZH-003; SVC-IZH-004; "
    "SVC-IZH-AST-001; SVC-IZH-AST-002; SVC-IZH-AST-003; SVC-IZH-AST-004"
)

MSG_IDS = [
    "MSG-IZH-WA-001",
    "MSG-IZH-WA-002",
    "MSG-IZH-WA-003",
    "MSG-IZH-WA-004",
    "MSG-IZH-WA-005",
    "MSG-IZH-WA-006",
    "MSG-IZH-WA-007",
]

# ─── SOP ─────────────────────────────────────────────────────

SOP_DATA = dict(
    title=    "Как общаться с клиентом по ИЖС в WhatsApp",
    biz_id=   BIZ_ID,
    service_id=       IZH_SERVICE_IDS,
    template_id=      "",
    template_stage_id="",
    purpose=  (
        "Дать оператору или ассистенту готовые безопасные формулировки для общения "
        "с клиентом по ИЖС: первичный ответ, запрос документов, запрос фото/видео, "
        "объяснение диагностики, напоминание, передача менеджеру и аккуратная работа "
        "с рисками."
    ),
    steps=(
        "1. Общий стиль: писать вежливо и понятно; не перегружать юридическими терминами; "
        "не обещать 100% результат; не гарантировать АПЗ, легализацию, акт ввода или сроки "
        "госорганов; сначала собирать данные и фото/видео; после получения данных передавать "
        "на классификацию через SOP-IZH-INTAKE-001 и SOP-IZH-ROUTER-001. "

        "2. Запрещенные формулировки: 'точно узаконим'; '100% получится'; "
        "'АПЗ точно выйдет'; 'проблем не будет'; 'гарантируем срок'; "
        "'можно без документов'; 'сделаем задним числом'. "

        "3. Разрешенные формулировки: "
        "'сначала нужно посмотреть документы и фактическое состояние объекта'; "
        "'после первичной проверки скажем возможный путь'; "
        "'по госорганам и АПЗ есть риски'; "
        "'предварительно можно оценить после фото/видео и документов'; "
        "'точная стоимость зависит от ситуации по объекту'. "

        "4. Когда использовать шаблоны: "
        "MSG-IZH-WA-001 — клиент впервые написал; "
        "MSG-IZH-WA-002 — нужно запросить фото/видео и документы; "
        "MSG-IZH-WA-003 — клиент отправил материалы; "
        "MSG-IZH-WA-004 — предложить диагностику/этап 1; "
        "MSG-IZH-WA-005 — клиент не отвечает (напоминание); "
        "MSG-IZH-WA-006 — передача менеджеру; "
        "MSG-IZH-WA-007 — аккуратно объяснить риски."
    ),
    expected_result=(
        "Оператор может использовать готовые WhatsApp-шаблоны для первичного общения "
        "с клиентом по ИЖС без риска дать неверное обещание."
    ),
    owner_role= "operator",
    status=     "active",
    notes=(
        "Кросс-сервисный WA SOP. Услуги: " + IZH_SERVICE_IDS + ". "
        "Шаблоны хранятся как FAQ records (MSG-IZH-WA-001…007). "
        "SendPulse/WABA API не подключается — шаблоны используются вручную."
    ),
)

# ─── 7 Message Templates → хранятся как FAQ records ──────────

MESSAGES = [
    dict(
        msg_id=   "MSG-IZH-WA-001",
        question= (
            "Когда использовать: клиент впервые написал — "
            "'хочу узаконить дом', 'хочу оформить пристройку', "
            "'хочу построить дом', 'нужно оформить баню/гараж/снос'."
        ),
        answer=   (
            "Здравствуйте! Чтобы понять, каким путём можно оформить ваш объект, "
            "нужно сначала посмотреть вводные данные.\n\n"
            "Напишите, пожалуйста:\n"
            "1. В каком городе объект — Алматы или Астана?\n"
            "2. Участок голый или на участке уже есть дом?\n"
            "3. Что хотите сделать: построить, узаконить, пристроить, "
            "оформить хозпостройку или снести?\n"
            "4. Работы уже выполнены или только планируете?\n"
            "5. Есть ли документы на землю и техпаспорт?\n"
            "6. Можете отправить фото/видео объекта?\n\n"
            "После просмотра скажем предварительный путь, риски, стоимость и сроки."
        ),
        notes=    (
            "Не обещать результат. Использовать как первый ответ. "
            "WABA Draft: Здравствуйте! Чтобы понять, каким путём можно оформить ваш объект, "
            "отправьте: город, адрес/кадастровый номер, фото/видео объекта, документы на землю, "
            "документы на дом и техпаспорт, если есть. "
            "Также напишите, работы уже выполнены или только планируются."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-002",
        question= (
            "Когда использовать: клиент рассказал ситуацию, "
            "но не отправил документы/фото."
        ),
        answer=   (
            "Для первичной проверки отправьте, пожалуйста:\n\n"
            "1. Фото/видео объекта или участка\n"
            "2. Документ на земельный участок\n"
            "3. Документы на дом/объект, если есть\n"
            "4. Технический паспорт, если есть\n"
            "5. Адрес объекта или кадастровый номер\n\n"
            "Лучше всего отправить короткое видео обхода участка: "
            "дом, пристройка/хозпостройка, границы участка и общий вид.\n\n"
            "После этого мы сможем понять, к какой услуге относится объект "
            "и каким путём лучше идти."
        ),
        notes=    (
            "Использовать после первичного контакта. "
            "WABA Draft: Для первичной проверки отправьте: фото/видео объекта, "
            "документы на землю, документы на дом, технический паспорт, "
            "адрес или кадастровый номер. "
            "После просмотра скажем предварительный путь оформления."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-003",
        question= "Когда использовать: клиент отправил документы/фото/видео.",
        answer=   (
            "Спасибо, материалы получили. "
            "Сейчас посмотрим документы и фактическое состояние объекта.\n\n"
            "После первичной проверки скажем:\n"
            "1. К какой услуге относится объект\n"
            "2. Каким путём можно идти\n"
            "3. Какие есть риски\n"
            "4. Какие документы ещё нужны\n"
            "5. Предварительную стоимость и сроки\n\n"
            "Если по объекту будут спорные моменты, "
            "передадим на дополнительную проверку менеджеру."
        ),
        notes=    (
            "Не давать ответ сразу, если документы ещё не проанализированы. "
            "WABA Draft: Спасибо, материалы получили. Проведём первичную проверку "
            "документов и фактического состояния объекта, затем сообщим возможный путь "
            "оформления, риски, стоимость и сроки."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-004",
        question= (
            "Когда использовать: нужно предложить первичную диагностику "
            "или этап проверки возможности оформления."
        ),
        answer=   (
            "По вашему объекту сначала лучше провести первичную проверку "
            "возможности оформления.\n\n"
            "На этом этапе мы проверяем:\n"
            "1. Документы на землю и объект\n"
            "2. Фактическое состояние по фото/видео\n"
            "3. Какой путь подходит: реконструкция, новое строительство, "
            "хозпостройка или снос\n"
            "4. Нужны ли дополнительные проверки\n"
            "5. Какие есть риски по АПЗ, техпаспорту и регистрации\n\n"
            "После диагностики будет понятно, есть ли смысл запускать полный процесс "
            "и каким путём идти.\n\n"
            "Стоимость первичной диагностики зависит от города и сложности объекта. "
            "Если потребуется отдельная топосъёмка, официальные запросы или "
            "дополнительные подрядчики, это обсуждается отдельно."
        ),
        notes=    (
            "Использовать, когда нельзя сразу продавать полный пакет. "
            "WABA Draft: По вашему объекту сначала рекомендуем провести первичную проверку "
            "возможности оформления. После проверки документов и фото/видео будет понятно, "
            "каким путём идти, какие есть риски, стоимость и сроки."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-005",
        question= (
            "Когда использовать: клиент не отвечает после запроса документов/фото."
        ),
        answer=   (
            "Здравствуйте! Напоминаю по вашему объекту.\n\n"
            "Чтобы мы могли предварительно сказать путь оформления, "
            "отправьте, пожалуйста:\n"
            "1. Город объекта\n"
            "2. Адрес или кадастровый номер\n"
            "3. Фото/видео объекта\n"
            "4. Документы на землю\n"
            "5. Техпаспорт и документы на дом, если есть\n\n"
            "Без этих данных мы не сможем корректно оценить ситуацию и риски."
        ),
        notes=    (
            "Использовать мягко, без давления. "
            "WABA Draft: Здравствуйте! Напоминаем, что для первичной проверки нужны "
            "город, адрес/кадастровый номер, фото/видео объекта, документы на землю "
            "и техпаспорт, если есть."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-006",
        question= (
            "Когда использовать: объект сложный или оператор не должен сам отвечать "
            "(отказ, спор с соседями, нет документов, водоохранная зона, штраф, "
            "предписание, другой город)."
        ),
        answer=   (
            "По вашему объекту есть моменты, которые лучше дополнительно проверить менеджеру.\n\n"
            "Я передам материалы специалисту. Он посмотрит документы, фото/видео и подскажет:\n"
            "1. Возможный путь оформления\n"
            "2. Риски\n"
            "3. Что нужно подготовить\n"
            "4. Стоимость и сроки\n\n"
            "Как только будет предварительный ответ, мы вам напишем."
        ),
        notes=    (
            "Использовать при сложных случаях. "
            "WABA Draft: По вашему объекту нужна дополнительная проверка менеджера. "
            "Передадим материалы специалисту, после просмотра сообщим возможный путь "
            "оформления, риски, стоимость и сроки."
        ),
    ),
    dict(
        msg_id=   "MSG-IZH-WA-007",
        question= (
            "Когда использовать: клиент просит гарантию или "
            "спрашивает 'точно получится?'."
        ),
        answer=   (
            "По таким объектам заранее гарантировать результат нельзя, "
            "потому что решение зависит от документов, фактического состояния объекта "
            "и рассмотрения госорганов.\n\n"
            "Мы можем:\n"
            "1. Проверить вашу ситуацию\n"
            "2. Подобрать правильный путь оформления\n"
            "3. Подготовить документы\n"
            "4. Сопроводить процесс\n"
            "5. Заранее предупредить о рисках\n\n"
            "Но АПЗ, согласования и регистрацию всегда нужно проходить официально, "
            "поэтому сначала делаем проверку и только потом фиксируем дальнейшие шаги."
        ),
        notes=    (
            "Использовать, если клиент просит гарантию, быстрый срок или 'точно сделаете?'. "
            "WABA Draft: Заранее гарантировать результат нельзя, так как решение зависит "
            "от документов, фактического состояния объекта и госорганов. Мы можем проверить "
            "ситуацию, подобрать путь оформления, подготовить документы и сопровождать процесс."
        ),
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


def _msg_exists(msg_id: str) -> bool:
    try:
        from business_core.knowledge_manager import find_faq_by_id
        return find_faq_by_id(msg_id) is not None
    except Exception as e:
        if _is_quota_error(e):
            log.warning(f"_msg_exists({msg_id}): quota — assuming EXISTS. {e}")
            return True
        log.warning(f"_msg_exists({msg_id}) error: {e}")
        return False


def _existing_msg_ids() -> list[str]:
    return [m["msg_id"] for m in MESSAGES if _msg_exists(m["msg_id"])]


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

    for msg in MESSAGES:
        mid = msg["msg_id"]
        if _msg_exists(mid):
            skip.append(f"[SKIP] {mid} уже существует")
        else:
            plan.append(f"[CREATE] {mid}: {msg['question'][:60]}…")

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

    # ── Message Templates → FAQ records ───────────────────────
    for msg in MESSAGES:
        mid = msg["msg_id"]
        if _msg_exists(mid):
            skipped.append(mid)
            if verbose: print(f"  [SKIP] {mid}")
            continue
        try:
            from business_core.knowledge_manager import create_faq_record
            from business_core.sheets import get_business_sheet
            result = create_faq_record(
                question=   msg["question"],
                answer=     msg["answer"],
                biz_id=     BIZ_ID,
                service_id= IZH_SERVICE_IDS,
                category=   "whatsapp_template",
                status=     "active",
                notes=      msg["notes"],
            )
            if result["ok"]:
                sheet = get_business_sheet("faq_registry")
                _rename_id_in_sheet(sheet, result["faq_id"], mid)
                created.append(mid)
                if verbose: print(f"  [OK] {mid}")
            else:
                errors.append(f"{mid}: {result['error']}")
                if verbose: print(f"  [ERR] {mid}: {result['error']}")
        except Exception as e:
            errors.append(f"{mid} exception: {e}")
            if verbose: print(f"  [ERR] {mid} exception: {e}")

    return {"created": created, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seed: WhatsApp-шаблоны по ИЖС")
    print(f"SOP: {SOP_ID} | Templates: {len(MESSAGES)} шт.")
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
