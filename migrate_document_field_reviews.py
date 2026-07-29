"""
Контролируемое одноразовое создание листа DOCUMENT_FIELD_REVIEWS —
Phase 16B.3 (Human Confirmation of Structured Document Fields).

Контекст: DOCUMENT_FIELD_REVIEWS — append-only source-of-truth audit
trail для человеческих confirm/reject/clear решений по structured
document fields (см. business_core/document_confirmation.py). Этот
лист НЕ существует в production до выполнения этой миграции.

business_core.sheets.get_business_sheet() умеет автоматически создать
отсутствующий лист с канонической схемой заголовков — технически
первый же вызов из document_confirmation.py мог бы неявно его
создать. Это ЗАПРЕЩЕНО намеренно: Telegram-команда (/confirmdocfield и
т.п.) никогда не должна становиться механизмом миграции схемы —
business_core.document_confirmation._reviews_sheet_ready() явно
проверяет существование листа ЧЕРЕЗ business_sheet_exists()
(НЕ вызывающую auto-create) и отказывает в мутации (fail closed,
REVIEWS_SHEET_NOT_READY), если этот скрипт ещё не был запущен.

Использование:
    python migrate_document_field_reviews.py              # dry-run (по умолчанию)
    python migrate_document_field_reviews.py --dry-run     # то же самое явно
    python migrate_document_field_reviews.py --live         # применить (требует ввода YES)

Гарантии:
- Работает ТОЛЬКО с листом DOCUMENT_FIELD_REVIEWS.
- НИКОГДА не создаёт лист с произвольными заголовками — только с точной
  канонической схемой BUSINESS_HEADERS["document_field_reviews"].
- Если лист уже существует: НИКОГДА не переставляет/перезаписывает его
  заголовки — только сверяет их с канонической схемой. Расхождение —
  жёсткий отказ (fail closed), требующий ручной проверки, а не
  автоматическое исправление.
- НИКОГДА не трогает уже существующие строки данных (append-only лог).
- Идемпотентна: повторный запуск на уже созданном/корректном листе не
  меняет ничего (status=ALREADY_PRESENT).
- Dry-run (по умолчанию) не создаёт лист и не выполняет ни одной записи.
"""

from __future__ import annotations

import sys

SHEET_KEY = "document_field_reviews"

STATUS_DRY_RUN = "DRY_RUN"
STATUS_CREATED = "CREATED"
STATUS_ALREADY_PRESENT = "ALREADY_PRESENT"
STATUS_SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
STATUS_CREATION_FAILED = "CREATION_FAILED"


def _canonical_headers() -> list[str]:
    from business_core.sheets import BUSINESS_HEADERS
    return list(BUSINESS_HEADERS[SHEET_KEY])


def analyze_sheet_state() -> dict:
    """
    Read-only. Never triggers auto-creation (uses business_sheet_exists(),
    not get_business_sheet()).

    Returns:
        {
            "exists": bool,
            "headers": list[str] | None,   # None if the sheet doesn't exist
            "canonical_headers": list[str],
            "headers_match": bool | None,  # None if the sheet doesn't exist
        }
    """
    from business_core.sheets import business_sheet_exists, get_business_sheet, read_with_retry

    canonical = _canonical_headers()
    exists = business_sheet_exists(SHEET_KEY)
    if not exists:
        return {"exists": False, "headers": None, "canonical_headers": canonical, "headers_match": None}

    headers = read_with_retry(get_business_sheet(SHEET_KEY).row_values, 1)
    return {
        "exists": True,
        "headers": headers,
        "canonical_headers": canonical,
        "headers_match": headers == canonical,
    }


def apply_creation(state: dict) -> dict:
    """
    Live action. Only ever called after analyze_sheet_state() confirms
    either "doesn't exist" (safe to create) — never called when the
    sheet exists with mismatched headers (caller must fail closed
    before reaching here).

    Returns:
        {"status": str, "headers": list[str] | None, "error": str | None}
    """
    if state["exists"]:
        if state["headers_match"]:
            return {"status": STATUS_ALREADY_PRESENT, "headers": state["headers"], "error": None}
        return {"status": STATUS_SCHEMA_MISMATCH, "headers": state["headers"], "error": (
            "Существующие заголовки DOCUMENT_FIELD_REVIEWS не совпадают с "
            "канонической схемой — требуется ручная проверка."
        )}

    try:
        from business_core.sheets import get_business_sheet, read_with_retry
        # get_business_sheet() auto-creates with the canonical headers
        # from BUSINESS_HEADERS[SHEET_KEY] when the sheet is missing —
        # this IS the intended, controlled use of that mechanism (this
        # script's whole purpose), never invoked implicitly elsewhere.
        sheet = get_business_sheet(SHEET_KEY)
        headers = read_with_retry(sheet.row_values, 1)
    except Exception as exc:
        return {"status": STATUS_CREATION_FAILED, "headers": None, "error": str(exc)}

    if headers != state["canonical_headers"]:
        return {"status": STATUS_CREATION_FAILED, "headers": headers, "error": (
            "Лист создан, но заголовки после создания не совпадают с "
            "канонической схемой — требуется ручная проверка."
        )}

    return {"status": STATUS_CREATED, "headers": headers, "error": None}


def _print_state(state: dict) -> None:
    print("=== DOCUMENT_FIELD_REVIEWS ===")
    print(f"Существует: {state['exists']}")
    if state["exists"]:
        print(f"Текущие заголовки: {state['headers']}")
        print(f"Совпадают с канонической схемой: {state['headers_match']}")
    print()
    print("=== Каноническая схема ===")
    for i, h in enumerate(state["canonical_headers"], start=1):
        print(f"{i}: {h!r}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Создать лист, если отсутствует (по умолчанию — только dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Явно указать dry-run (это и так поведение по умолчанию)")
    args = parser.parse_args()

    state = analyze_sheet_state()
    _print_state(state)

    if state["exists"] and not state["headers_match"]:
        print("\n❌ Заголовки существующего листа не совпадают с канонической схемой. "
              "Миграция отказывается действовать — требуется ручная проверка.")
        return 1

    if not args.live:
        if state["exists"]:
            print("\n[DRY-RUN] Лист уже существует с корректными заголовками — изменений не требуется.")
        else:
            print("\n[DRY-RUN] Лист будет создан со следующими заголовками (см. выше). "
                  "Запустите с --live для применения.")
        return 0

    if state["exists"]:
        print("\nЛист уже существует с корректными заголовками — изменений не требуется.")
        return 0

    print(f"\n⚠️  Это создаст в проде новый лист DOCUMENT_FIELD_REVIEWS с "
          f"{len(state['canonical_headers'])} заголовками (см. выше). Строки данных не создаются.")
    confirm = input("Введите YES для применения: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return 0

    result = apply_creation(state)
    print()
    print("=== Результат ===")
    print(f"Status: {result['status']}")
    print(f"Заголовки: {result['headers']}")
    if result["error"]:
        print(f"Ошибка: {result['error']}")

    if result["status"] in (STATUS_CREATED, STATUS_ALREADY_PRESENT):
        return 0

    print("\n‼️  Создание листа НЕ завершено корректно — см. status выше.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
