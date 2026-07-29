"""
Идемпотентная миграция заголовков листа DOCUMENT_CONTENT — Phase 16B.3
(Human Confirmation of Structured Document Fields).

Контекст: после Phase 16B.2, production DOCUMENT_CONTENT физически
содержит 31 колонку (headers == grid, col_count=31). Phase 16B.3
аддитивно расширяет BUSINESS_HEADERS["document_content"] на 4 новые
колонки в конце: Structured Review Status, Confirmed Fields JSON,
Structured Review Version, Structured Review Updated At (колонки
32-35) — материализованный current-state кэш; source of truth — новый
отдельный append-only лист DOCUMENT_FIELD_REVIEWS (создаётся
автоматически при первой записи через business_core.sheets
.get_business_sheet() — та же функция уже умеет создавать
отсутствующий лист с заголовками, отдельная миграция для него не
нужна).

Grid: текущий production col_count=31 — меньше требуемых 35, поэтому
эта миграция ОБЯЗАТЕЛЬНО требует resize 31 → 35 (тот же класс
проблемы, что и в Phase 16B.1/16B.2).

ВАЖНО — порядок деплоя (тот же принцип, что и в Phase 16B.2):
business_core/document_confirmation.py пишет 4 новые колонки в ОДНОМ
update_business_row() вызове при confirm/reject/clear. Если новый код
задеплоен, а эта миграция ещё не выполнена (--live), КАЖДАЯ попытка
подтверждения поля будет падать с ValueError ("update_business_row:
колонки не найдены") → структурная mutation вернёт WRITE_FAILED. Это
не роняет основной AI-анализ (document_intelligence.py эти 4 колонки
не пишет и не читает вовсе), но /confirmdocfield/reviewdoc не будут
работать корректно до миграции. Обязательный порядок:
    1. Запустить эту миграцию (--live, до 35 колонок) на production.
    2. Только ПОСЛЕ успешной миграции — деплоить новый код
       document_confirmation.py/document_query.py/telegram_handlers.py.

Использование:
    python migrate_document_content_review_fields.py              # dry-run (по умолчанию)
    python migrate_document_content_review_fields.py --dry-run     # то же самое явно
    python migrate_document_content_review_fields.py --live        # применить (требует ввода YES)

Гарантии — идентичны предыдущим migrate_document_content_*.py
скриптам (ни один из них не изменён и не переиспользуется этим
скриптом напрямую — намеренное дублирование small, self-contained
admin-скрипта, как и раньше):
- Работает ТОЛЬКО с листом DOCUMENT_CONTENT.
- НИКОГДА не трогает строки данных (row >= 2) — только row 1 и grid.
- НИКОГДА не переименовывает/переставляет существующие заголовки; если
  существующие заголовки НЕ являются точным префиксом канонической
  схемы — миграция отказывается действовать.
- НИКОГДА не уменьшает grid.
- Идемпотентна: повторный запуск на уже смигрированном листе не меняет
  ничего (has_changes=False, ноль write/resize-запросов).
- Dry-run (по умолчанию) не выполняет ни одной записи и ни одного resize.
- Live-запуск сверяет строки данных (row >= 2) до и после миграции
  нормализованным сравнением (только preserved_width колонок,
  appended_columns_clean отдельно).
- resize()/update_cell() — write-операции, НИКОГДА не оборачиваются в
  read_with_retry и никогда не повторяются автоматически при ошибке.
"""

from __future__ import annotations

import sys

SHEET_KEY = "document_content"

STATUS_DRY_RUN = "DRY_RUN"
STATUS_ADDED = "ADDED"
STATUS_ALREADY_PRESENT = "ALREADY_PRESENT"
STATUS_GRID_RESIZE_FAILED = "GRID_RESIZE_FAILED"
STATUS_HEADER_WRITE_FAILED = "HEADER_WRITE_FAILED"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"


def _canonical_headers() -> list[str]:
    from business_core.sheets import BUSINESS_HEADERS
    return list(BUSINESS_HEADERS[SHEET_KEY])


def analyze_document_content_headers(existing_headers: list[str], current_col_count: int | None = None) -> dict:
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
    required_col_count = len(canonical)
    grid_resize_required = current_col_count is not None and current_col_count < required_col_count

    return {
        "existing_headers": existing,
        "canonical_headers": canonical,
        "already_present": already_present,
        "to_append": to_append,
        "prefix_ok": prefix_ok,
        "conflicts": conflicts,
        "after_preview": (existing + to_append) if prefix_ok else None,
        "has_changes": bool(to_append) and prefix_ok,
        "current_col_count": current_col_count,
        "required_col_count": required_col_count,
        "grid_resize_required": grid_resize_required,
    }


def resize_grid_if_needed(sheet, plan: dict) -> dict:
    col_count_before = plan["current_col_count"]

    if not plan["grid_resize_required"]:
        return {
            "attempted": False, "succeeded": True, "error": None,
            "col_count_before": col_count_before, "col_count_after": col_count_before,
        }

    try:
        sheet.resize(rows=sheet.row_count, cols=plan["required_col_count"])
    except Exception as exc:
        return {
            "attempted": True, "succeeded": False, "error": str(exc),
            "col_count_before": col_count_before, "col_count_after": col_count_before,
        }

    col_count_after = sheet.col_count
    succeeded = col_count_after >= plan["required_col_count"]
    return {
        "attempted": True, "succeeded": succeeded,
        "error": None if succeeded else (
            f"col_count after resize ({col_count_after}) still below required "
            f"({plan['required_col_count']})"
        ),
        "col_count_before": col_count_before, "col_count_after": col_count_after,
    }


def _compare_data_preservation(data_rows_before: list, data_rows_after: list, preserved_width: int) -> dict:
    def _normalize(row):
        padded = list(row) + [""] * max(0, preserved_width - len(row))
        return padded[:preserved_width]

    rows_before_count = len(data_rows_before)
    rows_after_count = len(data_rows_after)

    first_mismatch_row = None
    data_preserved = True
    for i in range(max(rows_before_count, rows_after_count)):
        if i >= rows_before_count or i >= rows_after_count:
            data_preserved = False
            first_mismatch_row = i + 1
            break
        if _normalize(data_rows_before[i]) != _normalize(data_rows_after[i]):
            data_preserved = False
            first_mismatch_row = i + 1
            break

    appended_columns_clean = True
    for row in data_rows_after:
        if any(v != "" for v in list(row)[preserved_width:]):
            appended_columns_clean = False
            break

    return {
        "data_preserved": data_preserved,
        "appended_columns_clean": appended_columns_clean,
        "preserved_column_count": preserved_width,
        "rows_before_count": rows_before_count,
        "rows_after_count": rows_after_count,
        "first_mismatch_row": first_mismatch_row,
    }


def apply_migration_plan(sheet, plan: dict, data_rows_before: list | None = None) -> dict:
    if not plan["prefix_ok"]:
        raise ValueError(
            "existing DOCUMENT_CONTENT headers are not a clean prefix of the "
            "canonical schema — refusing to migrate automatically. "
            f"Conflicts: {plan['conflicts']}"
        )

    result: dict = {
        "status": "",
        "grid_before": plan["current_col_count"],
        "grid_after": plan["current_col_count"],
        "grid_resize_required": plan["grid_resize_required"],
        "grid_resized": False,
        "headers_before": list(plan["existing_headers"]),
        "headers_after": list(plan["existing_headers"]),
        "added_headers": [],
        "already_present_headers": list(plan["already_present"]),
        "data_preserved": None,
        "appended_columns_clean": None,
        "preserved_column_count": None,
        "rows_before_count": None,
        "rows_after_count": None,
        "first_mismatch_row": None,
        "error": None,
    }
    preserved_width = len(plan["existing_headers"])

    if not plan["has_changes"]:
        result["status"] = STATUS_ALREADY_PRESENT
        return result

    resize_outcome = resize_grid_if_needed(sheet, plan)
    result["grid_resized"] = resize_outcome["attempted"] and resize_outcome["succeeded"]
    result["grid_after"] = resize_outcome["col_count_after"]

    if plan["grid_resize_required"] and not resize_outcome["succeeded"]:
        result["status"] = STATUS_GRID_RESIZE_FAILED
        result["error"] = resize_outcome["error"]
        return result

    next_col = len(plan["existing_headers"]) + 1
    added: list[str] = []
    try:
        for h in plan["to_append"]:
            sheet.update_cell(1, next_col, h)
            added.append(h)
            next_col += 1
    except Exception as exc:
        result["added_headers"] = added
        result["status"] = STATUS_HEADER_WRITE_FAILED
        result["error"] = str(exc)
        try:
            result["headers_after"] = sheet.row_values(1)
        except Exception:
            pass
        if data_rows_before is not None:
            try:
                data_after = sheet.get_all_values()[1:]
                result.update(_compare_data_preservation(data_rows_before, data_after, preserved_width))
            except Exception:
                pass
        return result

    result["added_headers"] = added

    after_headers = sheet.row_values(1)
    result["headers_after"] = after_headers

    if data_rows_before is not None:
        data_after = sheet.get_all_values()[1:]
        result.update(_compare_data_preservation(data_rows_before, data_after, preserved_width))

    if after_headers != plan["canonical_headers"]:
        result["status"] = STATUS_VERIFICATION_FAILED
        return result

    result["status"] = STATUS_ADDED
    return result


def _print_plan(plan: dict) -> None:
    print("=== ДО миграции (фактические заголовки DOCUMENT_CONTENT) ===")
    for i, h in enumerate(plan["existing_headers"], start=1):
        print(f"{i}: {h!r}")

    print()
    print("=== Grid ===")
    print(f"Текущий col_count:   {plan['current_col_count']}")
    print(f"Требуемый col_count: {plan['required_col_count']}")
    if plan["grid_resize_required"]:
        print(f"Grid resize required: {plan['current_col_count']} → {plan['required_col_count']}")
        print(f"Add grid columns: {plan['required_col_count'] - plan['current_col_count']}")
    else:
        print("Grid resize required: нет")

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
    current_col_count = sheet.col_count

    plan = analyze_document_content_headers(existing_headers, current_col_count=current_col_count)
    _print_plan(plan)

    if not plan["prefix_ok"]:
        print("\n❌ Миграция отменена — обнаружен конфликт схемы. Требуется ручная проверка.")
        return 1

    if not args.live:
        print("\n[DRY-RUN] Изменения (заголовки и grid) НЕ применены. Запустите с --live для применения.")
        return 0

    if not plan["has_changes"]:
        print("\nВсе заголовки уже присутствуют — изменений не требуется.")
        return 0

    data_before = sheet.get_all_values()[1:]

    print(f"\n⚠️  Это выполнит в проде на листе DOCUMENT_CONTENT:")
    if plan["grid_resize_required"]:
        print(f"   - расширение grid: {plan['current_col_count']} → {plan['required_col_count']} колонок "
              f"(rows сохраняются: {sheet.row_count})")
    print(f"   - добавление {len(plan['to_append'])} колонок(и) СПРАВА в строку заголовков (row 1): "
          f"{plan['to_append']}")
    print(f"Строк данных сейчас: {len(data_before)}. Они изменены НЕ будут.")
    print("\n‼️  ВАЖНО: деплой нового кода document_confirmation.py, который пишет "
          "эти 4 поля при confirm/reject/clear, должен произойти ТОЛЬКО ПОСЛЕ "
          "успешного завершения этой миграции — см. module docstring.")
    confirm = input("Введите YES для применения: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return 0

    result = apply_migration_plan(sheet, plan, data_rows_before=data_before)

    print()
    print("=== Результат миграции ===")
    print(f"Status: {result['status']}")
    print(f"Grid: {result['grid_before']} → {result['grid_after']} (resized: {result['grid_resized']})")
    print(f"Headers до:    {result['headers_before']}")
    print(f"Headers после: {result['headers_after']}")
    print(f"Добавлено: {result['added_headers']}")
    print(f"Уже было:  {result['already_present_headers']}")
    print(f"Данные не изменились (первые {result['preserved_column_count']} колонок): {result['data_preserved']}")
    print(f"Новые колонки справа пустые: {result['appended_columns_clean']}")
    print(f"Строк данных: до={result['rows_before_count']}, после={result['rows_after_count']}")
    if result["first_mismatch_row"] is not None:
        print(f"Первое несовпадение в строке данных №{result['first_mismatch_row']}")
    if result["error"]:
        print(f"Ошибка: {result['error']}")

    if result["status"] == STATUS_ADDED:
        return 0

    print("\n‼️  Миграция НЕ завершена полностью — см. status выше. Проверьте лист вручную.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
