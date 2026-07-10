"""
Patch seed: Коммерческая модель услуги SVC-IZH-001.

Обновляет поле Notes (и Комментарий / Описание) в SERVICE_CATALOG для SVC-IZH-001.
Новые таблицы не создаёт. GTD Core не трогает.

Использование:
    python3 business_core/seeds/seed_izhs_commercial_milestones.py --dry-run
    python3 business_core/seeds/seed_izhs_commercial_milestones.py
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

SERVICE_ID = "SVC-IZH-001"

# Маркер — если он уже есть в Notes, повторно не пишем (идемпотентность)
_MARKER = "КОММЕРЧЕСКАЯ МОДЕЛЬ v1"

COMMERCIAL_NOTES = f"""=== {_MARKER} ===

Коммерческая модель из 3 этапов.

── Этап 1 — Проверка возможности оформления объекта: 150 000 тг ──
Входит:
  • Топосъёмка
  • Проверка границ по топосъёмке
  • Проверка фактического расположения строений
  • ПДП / регламент / ситуационная схема (одним блоком)
  • Проверка красных линий и ограничений
  • Проверка целевого назначения земли
  • Проверка водоохранной зоны (если рядом арык/речка/канал)
  • Официальные запросы при необходимости
  • Предварительное заключение
Результат: понятно, есть ли смысл идти дальше в АПЗ/легализацию/реконструкцию.
Важно: этап 1 не гарантирует получение АПЗ. Показывает предварительные риски и возможность запуска.

── Этап 2 — Проектно-разрешительный этап / АПЗ: 500 000 тг ──
Входит:
  • Первичный замер
  • Техническое обследование
  • Сейсмостойкое заключение (если требуется)
  • Технический проект
  • Формирование пакета на АПЗ
  • Подача на АПЗ
  • Сопровождение рассмотрения
  • Получение результата: АПЗ / замечания / отказ
Важно: АПЗ — рискованный этап. Компания не гарантирует выдачу АПЗ, решение принимает госорган.
При отказе этап считается выполненным; дальнейшая стратегия согласуется отдельно.

── Этап 3 — Ввод в эксплуатацию / техпаспорт / регистрация: 300 000 тг ──
Входит:
  • Сопровождение после АПЗ
  • Технический паспорт
  • Подготовка акта ввода
  • Согласование акта ввода в архитектуре
  • Регистрация акта ввода в НАО
По практике: архитектура — обычно 1 рабочий день, регистрация НАО — около 5 рабочих дней.

── Базовая цена ──
  Этап 1 — 150 000 тг
  Этап 2 — 500 000 тг
  Этап 3 — 300 000 тг
  Итого   — 950 000 тг
Для сложных объектов цена определяется индивидуально.

Сложные случаи (цена выше):
  большая площадь пристройки/надстройки; водоохранная зона; спорные границы;
  ПДП/регламент с ограничениями; красные линии; отказ/замечания госоргана;
  повторные подачи; нестандартный участок.

Не входит (если отдельно не прописано в договоре):
  госпошлины; оплата технического паспорта; нотариальные согласия; штрафы;
  строительно-монтажные работы; повторные подачи после существенных изменений;
  дополнительные согласования."""

# Колонки SERVICE_CATALOG которые обновляем
# (обновляем Notes/Комментарий — старая колонка и новую Notes, если есть)
_TARGET_COLUMNS = ["Комментарий", "Notes"]


# ═══════════════════════════════════════════════════════════════
# Idempotency helpers
# ═══════════════════════════════════════════════════════════════

def _service_exists() -> bool:
    try:
        from business_core.service_manager import find_service_by_id
        return find_service_by_id(SERVICE_ID) is not None
    except Exception as e:
        log.warning(f"_service_exists error: {e}")
        return False


def _already_patched() -> bool:
    """Проверяем, содержит ли Notes уже наш маркер."""
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("service_catalog")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return False
        headers = all_values[0]

        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if row[0].strip() != SERVICE_ID:
                continue
            for col in _TARGET_COLUMNS:
                if col in headers:
                    idx = headers.index(col)
                    val = row[idx].strip() if idx < len(row) else ""
                    if _MARKER in val:
                        return True
        return False
    except Exception as e:
        log.warning(f"_already_patched error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# Core patch function
# ═══════════════════════════════════════════════════════════════

def patch_service_notes(dry_run: bool = False) -> dict:
    """
    Обновить Notes/Комментарий в SERVICE_CATALOG для SVC-IZH-001.

    Args:
        dry_run: если True — ничего не пишет, только сообщает что будет сделано.

    Returns:
        {"ok": bool, "action": str, "error": str | None}
    """
    if not _service_exists():
        return {
            "ok": False,
            "action": "skip",
            "error": f"Service {SERVICE_ID} не найден. Сначала запусти seed 1.",
        }

    if _already_patched():
        return {
            "ok": True,
            "action": "skip",
            "error": None,
        }

    if dry_run:
        return {
            "ok": True,
            "action": "would_update",
            "error": None,
        }

    try:
        from business_core.sheets import get_business_sheet, _invalidate_sheet_cache
        sheet      = get_business_sheet("service_catalog")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "action": "skip", "error": "SERVICE_CATALOG пуст"}
        headers = all_values[0]

        updated = False
        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0].strip():
                continue
            if row[0].strip() != SERVICE_ID:
                continue

            for col in _TARGET_COLUMNS:
                if col not in headers:
                    continue
                idx     = headers.index(col)
                current = row[idx].strip() if idx < len(row) else ""
                if _MARKER in current:
                    continue   # уже есть
                new_val = (current + "\n\n" + COMMERCIAL_NOTES).strip()
                sheet.update_cell(i, idx + 1, new_val)
                updated = True
                log.info(f"patch_service_notes: обновлено {col} для {SERVICE_ID}")

            # Сбрасываем кэш, чтобы следующие читатели видели свежие данные
            _invalidate_sheet_cache("service_catalog")

            return {
                "ok": True,
                "action": "updated" if updated else "skip",
                "error": None,
            }

        return {"ok": False, "action": "skip",
                "error": f"{SERVICE_ID} не найден в таблице"}

    except Exception as e:
        log.error(f"patch_service_notes error: {e}")
        return {"ok": False, "action": "error", "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# Dry-run preview
# ═══════════════════════════════════════════════════════════════

def dry_run() -> dict:
    """Показать план без записи в Sheets."""
    plan = []
    skip = []

    if not _service_exists():
        skip.append(f"[WARN] Service {SERVICE_ID} не найден — нужен seed 1")
    elif _already_patched():
        skip.append(f"[SKIP] {SERVICE_ID} уже содержит коммерческую модель ({_MARKER})")
    else:
        plan.append(
            f"[UPDATE] Notes/Комментарий для {SERVICE_ID}: "
            f"добавить коммерческую модель из 3 этапов (950 000 тг)"
        )

    return {"plan": plan, "skip": skip}


# ═══════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    is_dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Patch: Коммерческая модель SVC-IZH-001 (3 этапа, 950 000 тг)")
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
            print("  Ничего делать не нужно.")
        return

    # Live mode
    result = dry_run()
    print()
    for line in result["skip"]:
        print(f"  {line}")

    if not result["plan"]:
        print("  Ничего делать не нужно.")
        return

    print("\nБудет обновлено:")
    for line in result["plan"]:
        print(f"  {line}")

    print()
    confirm = input("Type YES to continue: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return

    print("\nОбновление в Google Sheets...\n")
    outcome = patch_service_notes(dry_run=False)

    if outcome["ok"] and outcome["action"] == "updated":
        print(f"  [OK] Notes для {SERVICE_ID} обновлены")
    elif outcome["action"] == "skip":
        print(f"  [SKIP] Уже актуально")
    else:
        print(f"  [ERR] {outcome['error']}")

    print("=" * 60)


if __name__ == "__main__":
    main()
