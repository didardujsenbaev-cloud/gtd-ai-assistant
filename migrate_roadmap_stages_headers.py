"""
Идемпотентная миграция заголовков листа ROADMAP_STAGES.

Контекст (Phase 9A, подготовка к Stage Management): create_stages_from_template_record
пишет 5 полей знаниевых привязок (SOP IDs, Checklist IDs, Materials IDs,
Document Template IDs, FAQ IDs) в колонки 13-17 позиционно, но живой лист
исторически имел подписанными только колонки 1-12. В отличие от бага
ROADMAPS (RM-027), здесь заголовки не переопределены неверным именем —
они просто ПУСТЫЕ. Тем не менее подпись выполняется только после проверки
фактических данных (ID-префиксы SOP-/CHK-/MAT-/DOC-/FAQ-), а не вслепую.

Использование:
    python migrate_roadmap_stages_headers.py              # dry-run (по умолчанию)
    python migrate_roadmap_stages_headers.py --dry-run     # то же самое явно
    python migrate_roadmap_stages_headers.py --live        # применить (требует ввода YES)

Гарантии:
- НИКОГДА не трогает строки данных (row >= 2) — только строку заголовков (row 1).
- НИКОГДА не удаляет и не переименовывает уже подписанные колонки без
  явного расхождения с данными (в этом листе такого расхождения нет).
- Недостающие заголовки подписываются только после подтверждения их
  фактической позиции по данным (ID-префиксы) либо, если данных нет,
  по единственно возможной позиции в фиксированном порядке записи кода.
- Идемпотентна: повторный запуск на уже смигрированном листе не меняет ничего.
- Перед live-записью и сразу после неё сверяет строки данных
  (row >= 2) на побайтовую идентичность — если хоть одна строка
  изменилась, это будет явно показано.
"""

from __future__ import annotations

import re
import sys

SHEET_KEY = "roadmap_stages"

CANONICAL_TAIL = [
    "SOP IDs", "Checklist IDs", "Materials IDs",
    "Document Template IDs", "FAQ IDs",
]

# Соответствие канонического поля и ID-префикса реестра, который в него
# копируется (_ID_PREFIXES в business_core/sheets.py).
_TAIL_PREFIX = {
    "SOP IDs":                "SOP",
    "Checklist IDs":           "CHK",
    "Materials IDs":            "MAT",
    "Document Template IDs":    "DOC",
    "FAQ IDs":                   "FAQ",
}


def _tokens_match_prefix(value: str, prefix: str) -> bool:
    """Поле может быть списком через запятую (','.join(...)) — каждый токен
    должен соответствовать префиксу реестра."""
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    if not tokens:
        return False
    return all(re.match(rf"^{prefix}-\S+$", t) for t in tokens)


def classify_column_data(values: list[str]) -> str | None:
    """
    По непустым значениям колонки угадать, какому каноническому полю
    (SOP IDs / Checklist IDs / Materials IDs / Document Template IDs / FAQ IDs)
    она соответствует. None — если данных нет или они не совпадают
    однозначно ни с одним префиксом (безопасный отказ, а не угадывание).
    """
    non_empty = [v.strip() for v in values if v and v.strip()]
    if not non_empty:
        return None

    matches = [
        name for name, prefix in _TAIL_PREFIX.items()
        if all(_tokens_match_prefix(v, prefix) for v in non_empty)
    ]
    return matches[0] if len(matches) == 1 else None


def analyze_roadmap_stages_headers(all_values: list[list[str]], col_count: int | None = None) -> dict:
    """
    Read-only анализ фактического состояния листа ROADMAP_STAGES.

    ВАЖНО: колонкой-кандидатом на роль одного из CANONICAL_TAIL полей
    считается ТОЛЬКО колонка, у которой заголовок сейчас пуст, либо уже
    равен одному из имён CANONICAL_TAIL. Колонки с любым другим
    существующим именем (Stage ID, Status, Notes, ...) никогда не
    рассматриваются и не переименовываются.

    Args:
        all_values: sheet.get_all_values() — строка 0 это заголовки,
                    остальные — данные.
        col_count:  реальное количество колонок в листе (sheet.col_count),
                    если больше, чем видно в all_values — колонки за
                    пределами использованного диапазона тоже считаются
                    существующими пустыми кандидатами (не "добавить
                    новую колонку", а "подписать уже существующую").

    Returns:
        План миграции. Ничего не пишет в Sheets.
    """
    headers   = list(all_values[0]) if all_values else []
    data_rows = all_values[1:] if len(all_values) > 1 else []

    max_col = len(headers)
    for row in data_rows:
        max_col = max(max_col, len(row))
    if col_count is not None:
        max_col = max(max_col, col_count)

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
        "before_headers":      list(headers),
        "max_col":              max_col,
        "already_correct":     [],
        "rename":                [],  # (col, old_name, new_name)
        "label_empty":           [],  # (col, new_name)
        "inferred_by_position":  [],  # (col, name) — не подтверждено данными
        "append":                [],  # name — колонки для этого поля вовсе не найдено
    }

    resolved_cols: dict[str, int] = {}

    # 1. Колонка уже названа именем цели — доверяем имени, если данные
    #    не противоречат (нет данных вовсе, или данные тоже
    #    классифицируются как это же поле).
    for target in CANONICAL_TAIL:
        if target in headers:
            col = headers.index(target) + 1
            data_here = classify_column_data(col_samples.get(col, []))
            if data_here in (None, target):
                resolved_cols[target] = col

    # 2. Поля с узнаваемым паттерном данных (ID-префикс реестра), ещё не
    #    резолвленные по имени — ищем среди "своей территории".
    for target in CANONICAL_TAIL:
        if target in resolved_cols:
            continue
        for c in territory_cols:
            if c in resolved_cols.values():
                continue
            if classify_column_data(col_samples.get(c, [])) == target:
                resolved_cols[target] = c
                break

    # 3. Поля без данных вообще (Materials IDs пока не используется,
    #    FAQ IDs ни разу не заполнялось) — позиционный вывод строго по
    #    ФИКСИРОВАННОМУ порядку CANONICAL_TAIL, единственному порядку
    #    записи в create_stages_from_template_record. Разрешаем только
    #    когда кандидат однозначен (ровно одна пустая неподписанная
    #    колонка на нужном месте между уже резолвленными соседями, либо
    #    в конце после всех резолвленных).
    for idx, target in enumerate(CANONICAL_TAIL):
        if target in resolved_cols:
            continue

        prev_targets = CANONICAL_TAIL[:idx]
        next_targets = CANONICAL_TAIL[idx + 1:]
        prev_col = next((resolved_cols[t] for t in reversed(prev_targets) if t in resolved_cols), None)
        next_col = next((resolved_cols[t] for t in next_targets if t in resolved_cols), None)

        lo = prev_col + 1 if prev_col else 1
        hi = (next_col - 1) if next_col else max_col

        candidates = [
            c for c in range(lo, hi + 1)
            if header_at(c) == "" and not col_samples.get(c) and c not in resolved_cols.values()
        ]
        if len(candidates) == 1:
            resolved_cols[target] = candidates[0]
            plan["inferred_by_position"].append((candidates[0], target))

    # 4. Собрать действия.
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


def strip_trailing_empty(row: list[str]) -> list[str]:
    """
    Убрать ТОЛЬКО хвостовые пустые значения из строки.

    Нужно потому, что после подписи ранее пустого заголовка used-range
    листа расширяется, и gspread.get_all_values() дополняет КАЖДУЮ строку
    данных пустыми строками '' до новой ширины — это не изменение данных,
    а особенность выравнивания прямоугольной матрицы. Пустые значения
    ВНУТРИ строки (например, неиспользуемое поле 'Due Date' посреди
    строки) — это реальные данные, и они не трогаются: убираются только
    ячейки с конца, до первого непустого значения.

    Не пишет ничего в Google Sheets — чистая функция для сравнения.
    """
    r = list(row)
    while r and r[-1] == "":
        r.pop()
    return r


def compare_data_rows(before: list[list[str]], after: list[list[str]]) -> dict:
    """
    Сравнить строки данных (row >= 2) до и после миграции заголовков.

    Returns:
        {
            "raw_equal":        bool — сырое сравнение списков (чувствительно
                                 к хвостовому padding после роста used-range),
            "normalized_equal": bool — сравнение после strip_trailing_empty,
            "real_diff_count":  int  — количество строк с реальным различием
                                 содержимого (плюс разница в количестве строк),
        }
    """
    raw_equal = before == after

    norm_before = [strip_trailing_empty(r) for r in before]
    norm_after  = [strip_trailing_empty(r) for r in after]

    real_diff_count = sum(
        1 for a, b in zip(norm_before, norm_after) if a != b
    )
    real_diff_count += abs(len(norm_before) - len(norm_after))

    return {
        "raw_equal":        raw_equal,
        "normalized_equal": norm_before == norm_after,
        "real_diff_count":  real_diff_count,
    }


def _print_plan(plan: dict) -> None:
    print("=== ДО миграции (фактические заголовки ROADMAP_STAGES) ===")
    for i, h in enumerate(plan["before_headers"], start=1):
        print(f"{i}: {h!r}")

    print()
    print("=== План миграции ===")
    print("Уже корректно:                  ", plan["already_correct"])
    print("Переименовать (col, old, new):  ", plan["rename"])
    print("Подписать пустую колонку:       ", plan["label_empty"])
    print("Позиционный вывод (без данных): ", plan["inferred_by_position"])
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
    sheet = get_business_sheet(SHEET_KEY)
    all_values = sheet.get_all_values()
    col_count = getattr(sheet, "col_count", None)

    plan = analyze_roadmap_stages_headers(all_values, col_count=col_count)
    _print_plan(plan)

    has_changes = bool(plan["rename"] or plan["label_empty"] or plan["append"])

    if not args.live:
        print("\n[DRY-RUN] Изменения НЕ применены. Запустите с --live для применения.")
        return

    if not has_changes:
        print("\nВсе заголовки уже корректны — изменений не требуется.")
        return

    data_before = sheet.get_all_values()[1:]

    print("\n⚠️  Это изменит ТОЛЬКО строку заголовков (row 1) листа ROADMAP_STAGES в проде.")
    print(f"Строк данных сейчас: {len(data_before)}. Они изменены НЕ будут.")
    confirm = input("Введите YES для применения: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return

    actions = apply_migration_plan(sheet, plan)
    print("\nВыполнено:")
    for a in actions:
        print(" -", a)

    data_after = sheet.get_all_values()[1:]
    comparison = compare_data_rows(data_before, data_after)
    print()
    print("=== Проверка целостности данных (row >= 2) ===")
    print(f"Строк данных до:   {len(data_before)}")
    print(f"Строк данных после: {len(data_after)}")
    print(f"raw_equal (сырое сравнение, чувствительно к padding used-range): {comparison['raw_equal']}")
    print(f"normalized_equal (без хвостовых пустых значений):               {comparison['normalized_equal']}")
    print(f"Количество строк с реальными различиями:                        {comparison['real_diff_count']}")
    if not comparison["normalized_equal"]:
        print("‼️  ВНИМАНИЕ: данные изменились! Немедленно проверьте лист вручную.")
    elif not comparison["raw_equal"]:
        print("ℹ️  raw_equal=False объясняется исключительно ростом used-range "
              "после подписи заголовков (хвостовой padding), реальных различий нет.")


if __name__ == "__main__":
    sys.exit(main() or 0)
