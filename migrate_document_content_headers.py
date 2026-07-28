"""
Идемпотентная миграция заголовков листа DOCUMENT_CONTENT (Phase 16B.1).

Контекст: production DOCUMENT_CONTENT физически содержит только первые
20 колонок (Phase 16A shape). business_core/sheets.py's
BUSINESS_HEADERS["document_content"] уже аддитивно расширен на 3 новые
колонки в конце (Duplicate Status / Duplicate Of Document ID /
Duplicate Checked At — Phase 16B.1), но код никогда не переписывает
заголовки существующего листа сам по себе (ensure_headers() в
business_core/sheets.py явно отказывается действовать при
расхождении — логирует предупреждение и не трогает лист). Это —
контролируемый, одноразовый admin-скрипт для закрытия именно этого
разрыва, а не общая Telegram-команда.

Значительно проще прецедента migrate_roadmap_stages_headers.py: там
требовалось распознавать/переставлять уже существующие, но неверно
подписанные колонки по данным. Здесь такой проблемы нет — все текущие
20 колонок DOCUMENT_CONTENT уже правильно подписаны с Phase 16A; нужно
только ДОПИСАТЬ 3 новые колонки строго в конец, если их ещё нет.

Использование:
    python migrate_document_content_headers.py              # dry-run (по умолчанию)
    python migrate_document_content_headers.py --dry-run     # то же самое явно
    python migrate_document_content_headers.py --live        # применить (требует ввода YES)

Гарантии:
- Работает ТОЛЬКО с листом DOCUMENT_CONTENT — ни один другой Business
  Core лист не читается и не пишется.
- НИКОГДА не трогает строки данных (row >= 2) — только строку
  заголовков (row 1), и только ячейки СПРАВА от уже существующих
  заголовков.
- НИКОГДА не переименовывает и не переставляет уже существующие
  заголовки. Если существующие заголовки НЕ являются точным префиксом
  канонического списка (т.е. что-то в первых 20 колонках уже
  расходится с ожиданием) — миграция отказывается действовать и требует
  ручной проверки, а не угадывает.
- Идемпотентна: повторный запуск на уже смигрированном листе не меняет
  ничего (has_changes=False, ноль write-запросов).
- Dry-run (по умолчанию) не выполняет ни одной записи — только читает
  текущие заголовки и печатает план.
- Live-запуск сверяет строки данных (row >= 2) до и после миграции на
  побайтовую идентичность.
"""

from __future__ import annotations

import sys

SHEET_KEY = "document_content"


def _canonical_headers() -> list[str]:
    from business_core.sheets import BUSINESS_HEADERS
    return list(BUSINESS_HEADERS[SHEET_KEY])


def analyze_document_content_headers(existing_headers: list[str]) -> dict:
    """
    Read-only анализ фактического состояния листа DOCUMENT_CONTENT.
    Ничего не пишет в Sheets.

    Returns:
        {
            "existing_headers": list[str],
            "canonical_headers": list[str],
            "already_present": list[str],   # canonical headers already on the sheet
            "to_append": list[str],          # canonical headers missing, in canonical order
            "prefix_ok": bool,                # existing_headers is an exact, unmodified
                                               # prefix of canonical_headers — the ONLY
                                               # shape this script is willing to migrate
            "conflicts": list[tuple],         # (col, existing, expected) if prefix_ok is False
            "after_preview": list[str] | None,
            "has_changes": bool,
        }
    """
    canonical = _canonical_headers()
    existing = list(existing_headers)

    conflicts = []
    for i, h in enumerate(existing):
        expected = canonical[i] if i < len(canonical) else None
        if expected is None or h != expected:
            conflicts.append((i + 1, h, expected))

    prefix_ok = not conflicts
    already_present = [h for h in canonical if h in existing]
    to_append = [h for h in canonical if h not in existing]

    return {
        "existing_headers": existing,
        "canonical_headers": canonical,
        "already_present": already_present,
        "to_append": to_append,
        "prefix_ok": prefix_ok,
        "conflicts": conflicts,
        "after_preview": (existing + to_append) if prefix_ok else None,
        "has_changes": bool(to_append) and prefix_ok,
    }


def apply_migration_plan(sheet, plan: dict) -> list[tuple[str, str]]:
    """
    Применить план на реальный Worksheet. Пишет ТОЛЬКО ячейки строки 1,
    строго справа от уже существующих заголовков — никогда не трогает
    row >= 2.

    Raises:
        ValueError: если plan["prefix_ok"] is False — этот скрипт
            никогда не пытается угадать/переставить существующие
            заголовки, только дописывает отсутствующие в конец.

    Returns:
        [(header_name, "ADDED" | "ALREADY_PRESENT"), ...] — по одному
        элементу на каждый канонический заголовок, в каноническом
        порядке.
    """
    if not plan["prefix_ok"]:
        raise ValueError(
            "existing DOCUMENT_CONTENT headers are not a clean prefix of the "
            "canonical schema — refusing to migrate automatically. "
            f"Conflicts: {plan['conflicts']}"
        )

    results: list[tuple[str, str]] = []
    next_col = len(plan["existing_headers"]) + 1
    for h in plan["to_append"]:
        sheet.update_cell(1, next_col, h)
        results.append((h, "ADDED"))
        next_col += 1

    for h in plan["already_present"]:
        results.append((h, "ALREADY_PRESENT"))

    # Re-order results into canonical order for a stable, predictable report.
    by_name = dict(results)
    return [(h, by_name[h]) for h in plan["canonical_headers"]]


def _print_plan(plan: dict) -> None:
    print("=== ДО миграции (фактические заголовки DOCUMENT_CONTENT) ===")
    for i, h in enumerate(plan["existing_headers"], start=1):
        print(f"{i}: {h!r}")

    print()
    print("=== План миграции ===")
    print("Уже присутствуют:      ", plan["already_present"])
    print("Добавить справа:       ", plan["to_append"])
    print("Существующие корректны (чистый префикс канонической схемы):", plan["prefix_ok"])
    if plan["conflicts"]:
        print("⚠️  КОНФЛИКТЫ (расхождение с ожидаемой схемой, миграция откажет):")
        for col, existing, expected in plan["conflicts"]:
            print(f"   col{col}: найдено {existing!r}, ожидалось {expected!r}")

    print()
    if plan["after_preview"] is not None:
        print("=== ПОСЛЕ миграции (предпросмотр) ===")
        for i, h in enumerate(plan["after_preview"], start=1):
            print(f"{i}: {h!r}")
    else:
        print("=== ПОСЛЕ миграции: недоступно (конфликт схемы, см. выше) ===")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Применить изменения (по умолчанию — только dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Явно указать dry-run (это и так поведение по умолчанию)")
    args = parser.parse_args()

    from business_core.sheets import get_business_sheet

    sheet = get_business_sheet(SHEET_KEY)
    existing_headers = sheet.row_values(1)

    plan = analyze_document_content_headers(existing_headers)
    _print_plan(plan)

    if not plan["prefix_ok"]:
        print("\n❌ Миграция отменена — обнаружен конфликт схемы. Требуется ручная проверка.")
        return 1

    if not args.live:
        print("\n[DRY-RUN] Изменения НЕ применены. Запустите с --live для применения.")
        return 0

    if not plan["has_changes"]:
        print("\nВсе заголовки уже присутствуют — изменений не требуется.")
        return 0

    data_before = sheet.get_all_values()[1:]

    print(f"\n⚠️  Это добавит {len(plan['to_append'])} колонок(и) СПРАВА в строку заголовков "
          f"(row 1) листа DOCUMENT_CONTENT в проде: {plan['to_append']}")
    print(f"Строк данных сейчас: {len(data_before)}. Они изменены НЕ будут.")
    confirm = input("Введите YES для применения: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return 0

    results = apply_migration_plan(sheet, plan)

    print("\nВыполнено:")
    for name, outcome in results:
        print(f" - {name}: {outcome}")

    # Verification: re-read headers, confirm exact match with canonical.
    after_headers = sheet.row_values(1)
    headers_match = after_headers == plan["canonical_headers"]
    print()
    print("=== Проверка после записи ===")
    print(f"Заголовки совпадают с канонической схемой: {headers_match}")
    if not headers_match:
        print("‼️  ВНИМАНИЕ: заголовки после записи НЕ совпадают с ожиданием! Проверьте лист вручную.")
        return 1

    data_after = sheet.get_all_values()[1:]
    rows_match = len(data_before) == len(data_after) and all(
        a == b for a, b in zip(data_before, data_after)
    )
    print(f"Строк данных до:    {len(data_before)}")
    print(f"Строк данных после: {len(data_after)}")
    print(f"Данные не изменились (row >= 2): {rows_match}")
    if not rows_match:
        print("‼️  ВНИМАНИЕ: данные изменились! Немедленно проверьте лист вручную.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
