"""
Идемпотентная миграция заголовков листа DOCUMENT_CONTENT (Phase 16B.1).

Контекст: production DOCUMENT_CONTENT физически содержит только первые
20 колонок (Phase 16A shape), И его grid (физическая сетка листа) выделен
ровно под 20 колонок (`worksheet.col_count == 20`). business_core/
sheets.py's BUSINESS_HEADERS["document_content"] уже аддитивно расширен
на 3 новые колонки в конце (Duplicate Status / Duplicate Of Document ID /
Duplicate Checked At — Phase 16B.1), но код никогда не переписывает
заголовки существующего листа сам по себе (ensure_headers() в
business_core/sheets.py явно отказывается действовать при
расхождении). Это — контролируемый, одноразовый admin-скрипт для
закрытия именно этого разрыва, а не общая Telegram-команда.

Первая живая попытка миграции (без grid-resize) упала с:
    gspread.exceptions.APIError: [400]: Range (DOCUMENT_CONTENT!U1)
    exceeds grid limits. Max rows: 999, max columns: 20
— `update_cell()` не расширяет grid сам; сетку нужно явно расширить
(`worksheet.resize(...)`) ДО записи заголовков за пределы текущего
`col_count`. Эта версия скрипта делает это безопасно, отдельным,
явно проверяемым шагом.

Использование:
    python migrate_document_content_headers.py              # dry-run (по умолчанию)
    python migrate_document_content_headers.py --dry-run     # то же самое явно
    python migrate_document_content_headers.py --live        # применить (требует ввода YES)

Гарантии:
- Работает ТОЛЬКО с листом DOCUMENT_CONTENT — ни один другой Business
  Core лист не читается и не пишется.
- НИКОГДА не трогает строки данных (row >= 2) — только строку
  заголовков (row 1) и grid-размер, и только справа/сверх уже
  существующих заголовков/колонок.
- НИКОГДА не переименовывает и не переставляет уже существующие
  заголовки. Если существующие заголовки НЕ являются точным префиксом
  канонического списка — миграция отказывается действовать и требует
  ручной проверки, а не угадывает.
- НИКОГДА не уменьшает grid (`worksheet.resize(cols=...)` вызывается
  только когда col_count МЕНЬШЕ требуемого; если col_count уже больше
  или равен требуемому — resize не вызывается вовсе).
- Идемпотентна: повторный запуск на уже смигрированном листе не меняет
  ничего (has_changes=False, ноль write-запросов, ноль resize-вызовов).
- Dry-run (по умолчанию) не выполняет ни одной записи и ни одного
  resize — только читает текущие заголовки/grid и печатает план.
- Live-запуск сверяет строки данных (row >= 2) до и после миграции на
  побайтовую идентичность.
- resize()/update_cell() — write-операции, НИКОГДА не оборачиваются в
  read_with_retry и никогда не повторяются автоматически при ошибке
  (см. Sheets quota mitigation write-policy: no retry around writes).
"""

from __future__ import annotations

import sys

SHEET_KEY = "document_content"

# Structured result statuses (Phase 16B.1 grid-resize hardening).
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
    """
    Read-only анализ фактического состояния листа DOCUMENT_CONTENT —
    и заголовков, и grid-размера. Ничего не пишет в Sheets.

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
            "current_col_count": int | None,  # worksheet.col_count, if known
            "required_col_count": int,        # len(canonical_headers)
            "grid_resize_required": bool,     # current_col_count is known AND < required
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
    """
    Grow the worksheet's grid to plan["required_col_count"] columns, ONLY
    if plan["grid_resize_required"] is True. NEVER shrinks — if
    col_count is already >= required, this is a pure no-op (no API call
    at all, not even a read).

    Uses worksheet.resize(rows=sheet.row_count, cols=required_col_count)
    — rows explicitly preserved (never implicitly reset), per the
    approved preference over add_cols().

    A single attempt, no retry (this is a write operation — see the
    module docstring's write-policy note).

    Returns:
        {
            "attempted": bool,
            "succeeded": bool,
            "error": str | None,
            "col_count_before": int | None,
            "col_count_after": int | None,
        }
    """
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
    """
    Compare only the column range that existed BEFORE this migration —
    columns 1..preserved_width (preserved_width = len(headers_before)).
    Newly appended columns to the right (the ones this migration itself
    just added) must NEVER affect this comparison: a resize/append pass
    legitimately widens every existing data row with empty trailing
    cells, and that is not data loss.

    Each row is padded with "" up to preserved_width (a short row is not
    itself corruption — a genuinely empty trailing cell is still data
    and must compare equal, not be treated as "missing"), then truncated
    to preserved_width, before comparing. Rows are compared strictly by
    position — never sorted — so a reordering of existing rows is
    detected as a mismatch.

    Returns:
        {
            "data_preserved": bool,
            "appended_columns_clean": bool,  # True iff every row's
                newly-appended columns (index >= preserved_width) are
                all empty in data_rows_after
            "preserved_column_count": int,
            "rows_before_count": int,
            "rows_after_count": int,
            "first_mismatch_row": int | None,  # 1-indexed position
                within the data rows (NOT the sheet row number) of the
                first mismatch — never the row content itself.
        }
    """
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
    """
    Full controlled live migration — steps 8-13 of the approved order:
      8.  resize grid, если требуется (never shrinks, never retried);
      9.  verify col_count >= required after resize;
      10. write missing headers (only after 8-9 succeed);
      11. re-read headers;
      12. verify exact canonical header match;
      13. verify existing data rows unchanged (if data_rows_before given).

    Raises:
        ValueError: если plan["prefix_ok"] is False — never guesses/
            reorders existing headers, refuses outright.

    Returns a structured result:
        {
            "status": one of ADDED/ALREADY_PRESENT/GRID_RESIZE_FAILED/
                      HEADER_WRITE_FAILED/VERIFICATION_FAILED,
            "grid_before": int | None,
            "grid_after": int | None,
            "grid_resize_required": bool,
            "grid_resized": bool,          # True only if resize was
                                            # attempted AND succeeded
            "headers_before": list[str],
            "headers_after": list[str],
            "added_headers": list[str],
            "already_present_headers": list[str],
            "data_preserved": bool | None, # None if data_rows_before not given
            "appended_columns_clean": bool | None,
            "preserved_column_count": int | None,
            "rows_before_count": int | None,
            "rows_after_count": int | None,
            "first_mismatch_row": int | None,
            "error": str | None,
        }

    Guarantees on failure:
      - GRID_RESIZE_FAILED: headers are NEVER written (grid still at
        col_count_before, or whatever partial state resize() itself left
        it in — never assumed corrupted, just not migrated).
      - HEADER_WRITE_FAILED: grid may already be resized (never rolled
        back automatically) — data rows are NOT considered damaged,
        only some headers may be missing; headers_after reflects the
        actual current state via a fresh re-read.
      - VERIFICATION_FAILED: the write calls all returned without
        raising, but the final re-read doesn't exactly match the
        canonical header list — surfaced distinctly rather than
        silently reported as ADDED.
    """
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

    # Step 8-9: resize grid if required, verify it actually grew enough.
    resize_outcome = resize_grid_if_needed(sheet, plan)
    result["grid_resized"] = resize_outcome["attempted"] and resize_outcome["succeeded"]
    result["grid_after"] = resize_outcome["col_count_after"]

    if plan["grid_resize_required"] and not resize_outcome["succeeded"]:
        result["status"] = STATUS_GRID_RESIZE_FAILED
        result["error"] = resize_outcome["error"]
        return result  # headers deliberately never written

    # Step 10: write missing headers, strictly to the right of existing ones.
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
            pass  # best-effort only — status already reflects the failure
        if data_rows_before is not None:
            try:
                data_after = sheet.get_all_values()[1:]
                result.update(_compare_data_preservation(data_rows_before, data_after, preserved_width))
            except Exception:
                pass  # best-effort only — status already reflects the failure
        return result

    result["added_headers"] = added

    # Step 11-12: re-read headers, verify exact canonical match.
    after_headers = sheet.row_values(1)
    result["headers_after"] = after_headers

    # Step 13: verify existing data rows unchanged, if requested. Only
    # the column range that existed BEFORE this migration is compared —
    # newly appended columns legitimately widen every row and must
    # never be mistaken for data loss.
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
