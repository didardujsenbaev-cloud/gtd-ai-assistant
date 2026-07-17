"""
Идемпотентная миграция заголовков листа ROADMAPS.

Контекст: колонки Object ID / Parent Roadmap ID / Case Type / Template ID
годами писались create_roadmap_for_object позиционно, без реальных
заголовков в строке 1 листа. Это привело к тому, что на проде колонка,
подписанная 'Template ID', на самом деле содержит данные Object ID
(см. RM-027). Эта миграция читает ФАКТИЧЕСКИЕ данные в колонках, чтобы
понять, что где реально лежит, и только затем правит заголовки.

Использование:
    python migrate_roadmaps_headers.py              # dry-run (по умолчанию)
    python migrate_roadmaps_headers.py --dry-run     # то же самое явно
    python migrate_roadmaps_headers.py --live        # применить (требует ввода YES)

Гарантии:
- НИКОГДА не трогает строки данных (row >= 2) — только строку заголовков (row 1).
- НИКОГДА не удаляет и не перезаписывает уже правильно подписанные колонки.
- Отсутствующие заголовки добавляются в конец, только если для них не
  найдена существующая колонка с подходящими данными.
- Идемпотентна: повторный запуск на уже смигрированном листе не меняет ничего.
"""

from __future__ import annotations

import re
import sys

CANONICAL_TAIL = ["Object ID", "Parent Roadmap ID", "Case Type", "Template ID"]

_OBJ_RE       = re.compile(r"^OBJ-\d+$")
_RMT_RE       = re.compile(r"^RMT-")
_RM_RE        = re.compile(r"^RM-\d+$")
_CASE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # напр. general, legalization_reconstruction_house


def classify_column_data(values: list[str]) -> str | None:
    """
    По непустым значениям колонки угадать, какому каноническому полю
    она соответствует. None — если данных нет или они не совпадают ни
    с одним известным паттерном (безопасный отказ, а не угадывание).
    """
    non_empty = [v.strip() for v in values if v and v.strip()]
    if not non_empty:
        return None
    if all(_RMT_RE.match(v) for v in non_empty):
        return "Template ID"
    if all(_OBJ_RE.match(v) for v in non_empty):
        return "Object ID"
    if all(_RM_RE.match(v) for v in non_empty):
        return "Parent Roadmap ID"
    if all(_CASE_TYPE_RE.match(v) for v in non_empty):
        return "Case Type"
    return None


def analyze_roadmaps_headers(all_values: list[list[str]]) -> dict:
    """
    Read-only анализ фактического состояния листа ROADMAPS.

    ВАЖНО: колонкой-кандидатом на роль одного из CANONICAL_TAIL полей
    считается ТОЛЬКО колонка, у которой заголовок сейчас пуст, либо уже
    равен одному из имён CANONICAL_TAIL (т.е. потенциально мисклассифицирован
    прошлой миграцией, как 'Template ID' над данными Object ID в RM-027).
    Колонки с любым другим существующим именем (Business ID, Client ID,
    Status, ...) никогда не рассматриваются и не переименовываются —
    иначе наивная классификация по паттерну данных может случайно
    перезаписать не относящуюся к делу колонку.

    Args:
        all_values: sheet.get_all_values() — строка 0 это заголовки,
                    остальные — данные.

    Returns:
        План миграции (см. ключи ниже). Ничего не пишет в Sheets.
    """
    headers   = list(all_values[0]) if all_values else []
    data_rows = all_values[1:] if len(all_values) > 1 else []

    max_col = len(headers)
    for row in data_rows:
        max_col = max(max_col, len(row))

    col_samples: dict[int, list[str]] = {c: [] for c in range(1, max_col + 1)}
    for row in data_rows:
        for c in range(1, max_col + 1):
            v = row[c - 1] if c - 1 < len(row) else ""
            if v and v.strip():
                col_samples[c].append(v.strip())

    def header_at(c: int) -> str:
        return headers[c - 1] if c - 1 < len(headers) else ""

    territory_cols = [
        c for c in range(1, max_col + 1)
        if header_at(c) == "" or header_at(c) in CANONICAL_TAIL
    ]

    plan: dict = {
        "before_headers":       list(headers),
        "already_correct":      [],
        "rename":                [],  # (col, old_name, new_name)
        "label_empty":           [],  # (col, new_name)
        "inferred_by_position":  [],  # (col, name) — не подтверждено данными
        "append":                [],  # name — колонки для этого поля не найдено, добавляем в конец
    }

    resolved_cols: dict[str, int] = {}

    # 1. Колонка уже названа именем цели — доверяем имени, ЕСЛИ данные в
    #    ней не противоречат (нет данных вовсе, или данные тоже
    #    классифицируются как это же поле). Так уже полностью мигрированный
    #    лист (или лист вовсе без данных) не переклассифицируется заново.
    #    Если данные явно указывают на ДРУГОЕ поле (случай RM-027: колонка
    #    подписана 'Template ID', а в ней лежат значения вида OBJ-...) —
    #    имени не доверяем, колонку заберёт её настоящий владелец на шаге 2.
    for target in CANONICAL_TAIL:
        if target in headers:
            col = headers.index(target) + 1
            data_here = classify_column_data(col_samples.get(col, []))
            if data_here in (None, target):
                resolved_cols[target] = col

    # 2. Поля с узнаваемым паттерном данных (Object ID / Template ID /
    #    Case Type), которые ещё не резолвлены по имени — ищем среди
    #    "своей территории" колонок (пустой заголовок либо один из
    #    CANONICAL_TAIL, но не занятый другим полем).
    for target in ("Object ID", "Template ID", "Case Type"):
        if target in resolved_cols:
            continue
        for c in territory_cols:
            if c in resolved_cols.values():
                continue
            if classify_column_data(col_samples.get(c, [])) == target:
                resolved_cols[target] = c
                break

    # 3. Parent Roadmap ID: в данных всегда пусто (фича не использовалась),
    #    по данным не определяется, если ещё не резолвлена по имени на
    #    шаге 1 — позиционный вывод: единственная пустая неподписанная
    #    колонка строго между Object ID и Case Type.
    if "Parent Roadmap ID" not in resolved_cols:
        obj_col  = resolved_cols.get("Object ID")
        case_col = resolved_cols.get("Case Type")
        if obj_col and case_col and case_col - obj_col >= 2:
            between = [
                c for c in range(obj_col + 1, case_col)
                if header_at(c) == "" and not col_samples.get(c)
            ]
            if len(between) == 1:
                resolved_cols["Parent Roadmap ID"] = between[0]
                plan["inferred_by_position"].append((between[0], "Parent Roadmap ID"))

    # 3. Собрать действия по каждому найденному/ненайденному полю.
    for target in CANONICAL_TAIL:
        col = resolved_cols.get(target)
        if col is None:
            plan["append"].append(target)
            continue
        h = header_at(col)
        if h == target:
            plan["already_correct"].append(target)
        elif h == "":
            plan["label_empty"].append((col, target))
        else:
            plan["rename"].append((col, h, target))

    plan["after_headers_preview"] = _simulate_after(headers, plan, max_col)
    return plan


def _simulate_after(headers: list[str], plan: dict, max_col: int) -> list[str]:
    result = list(headers) + [""] * max(0, max_col - len(headers))
    for col, _old, new in plan["rename"]:
        result[col - 1] = new
    for col, new in plan["label_empty"]:
        result[col - 1] = new

    used_max = len(result)
    for new in plan["append"]:
        used_max += 1
        if used_max > len(result):
            result.append(new)
        else:
            result[used_max - 1] = new
    return result


def apply_migration_plan(sheet, plan: dict) -> list[str]:
    """
    Применить план на реальный Worksheet.

    Меняет ТОЛЬКО ячейки первой строки (заголовки). Никогда не трогает
    строки данных (row >= 2).

    Returns:
        Список текстовых описаний выполненных действий (для лога).
    """
    actions: list[str] = []

    for col, old, new in plan.get("rename", []):
        sheet.update_cell(1, col, new)
        actions.append(f"rename col{col}: {old!r} -> {new!r}")

    for col, new in plan.get("label_empty", []):
        sheet.update_cell(1, col, new)
        actions.append(f"label col{col}: '' -> {new!r}")

    used_max = len(plan["before_headers"])
    for col, _old, _new in plan.get("rename", []):
        used_max = max(used_max, col)
    for col, _new in plan.get("label_empty", []):
        used_max = max(used_max, col)

    next_col = used_max + 1
    for new in plan.get("append", []):
        sheet.update_cell(1, next_col, new)
        actions.append(f"append col{next_col}: '' -> {new!r}")
        next_col += 1

    return actions


def _print_plan(plan: dict) -> None:
    print("=== ДО миграции (фактические заголовки ROADMAPS) ===")
    for i, h in enumerate(plan["before_headers"], start=1):
        print(f"{i}: {h!r}")

    print()
    print("=== План миграции ===")
    print("Уже корректно:                 ", plan["already_correct"])
    print("Переименовать (col, old, new): ", plan["rename"])
    print("Подписать пустую колонку:      ", plan["label_empty"])
    print("Позиционный вывод (без данных):", plan["inferred_by_position"])
    print("Добавить новой колонкой в конец:", plan["append"])

    print()
    print("=== ПОСЛЕ миграции (предпросмотр) ===")
    for i, h in enumerate(plan["after_headers_preview"], start=1):
        print(f"{i}: {h!r}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Применить изменения (по умолчанию — только dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Явно указать dry-run (это и так поведение по умолчанию)")
    args = parser.parse_args()

    from business_core.sheets import get_business_sheet
    sheet = get_business_sheet("roadmaps")
    all_values = sheet.get_all_values()

    plan = analyze_roadmaps_headers(all_values)
    _print_plan(plan)

    has_changes = bool(plan["rename"] or plan["label_empty"] or plan["append"])

    if not args.live:
        print("\n[DRY-RUN] Изменения НЕ применены. Запустите с --live для применения.")
        return

    if not has_changes:
        print("\nВсе заголовки уже корректны — изменений не требуется.")
        return

    print("\n⚠️  Это изменит ТОЛЬКО строку заголовков (row 1) листа ROADMAPS в проде.")
    print("Строки данных (сами roadmap-записи) изменены НЕ будут.")
    confirm = input("Введите YES для применения: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return

    actions = apply_migration_plan(sheet, plan)
    print("\nВыполнено:")
    for a in actions:
        print(" -", a)


if __name__ == "__main__":
    sys.exit(main() or 0)
