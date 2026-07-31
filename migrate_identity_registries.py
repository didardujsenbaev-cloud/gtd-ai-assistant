"""
Explicit sheet creation/verification for the four Phase 17B Identity &
Access Control registries — EMPLOYEE_REGISTRY, TELEGRAM_IDENTITY_REGISTRY,
ACCESS_ROLE_ASSIGNMENTS, ACCESS_SCOPE_ASSIGNMENTS — plus an optional,
separately-confirmed OWNER bootstrap step.

This is NOT a column-append migration (unlike
migrate_document_registry_archive_fields.py) — these are brand-new,
empty sheets. business_core.sheets.get_business_sheet() already
creates a missing worksheet with full canonical headers on first
access, so this script's job is purely to make that creation explicit,
reviewable, and independently verified per-registry BEFORE any Phase
17C+ code path would otherwise trigger it implicitly on first use.

Never touches any existing sheet — zero risk to DOCUMENT_REGISTRY (27),
DOCUMENT_CONTENT (35), DOCUMENT_FIELD_REVIEWS (12), or any other
existing registry. Never touches GTD sheets (a separate spreadsheet
entirely).

Owner bootstrap (business_builder.bootstrap_owner_from_env()) is
NEVER run implicitly — it requires its own explicit --bootstrap-owner
flag AND its own separate exact "YES" confirmation, on top of the
sheet-creation --live YES gate. Reads BC_OWNER_TELEGRAM_USER_ID from
the environment; this script never accepts a Telegram User ID as a
CLI argument.

Usage:
    python migrate_identity_registries.py
        # dry-run: verify what would be created, zero writes

    python migrate_identity_registries.py --live YES
        # create/verify the four sheets only, zero owner-bootstrap writes

    python migrate_identity_registries.py --live YES --bootstrap-owner YES
        # create/verify the four sheets, then also run the explicit
        # owner bootstrap (still its own dry-run preview first — see
        # below; --bootstrap-owner YES only unlocks the *live* bootstrap
        # write, it does not skip the preview)
"""

from __future__ import annotations

import sys

REGISTRY_KEYS = (
    "employee_registry",
    "telegram_identity_registry",
    "access_role_assignments",
    "access_scope_assignments",
)

STATUS_DRY_RUN = "DRY_RUN"
STATUS_ALREADY_PRESENT = "ALREADY_PRESENT"
STATUS_CREATED = "CREATED"
STATUS_HEADER_MISMATCH = "HEADER_MISMATCH"
STATUS_VERIFICATION_FAILED = "VERIFICATION_FAILED"


def _canonical_headers(sheet_key: str) -> list[str]:
    from business_core.sheets import BUSINESS_HEADERS
    return list(BUSINESS_HEADERS[sheet_key])


def check_registry(sheet_key: str) -> dict:
    """
    Read-only. Determines whether the sheet already exists (and with
    what headers) WITHOUT creating anything — get_business_sheet()
    itself creates on WorksheetNotFound, so this function deliberately
    checks existence first via the underlying Spreadsheet object
    rather than calling get_business_sheet() directly in dry-run mode.
    """
    from business_core.sheets import BUSINESS_SHEET_NAMES, get_business_spreadsheet
    import gspread

    sheet_name = BUSINESS_SHEET_NAMES[sheet_key]
    canonical = _canonical_headers(sheet_key)

    ss = get_business_spreadsheet()
    try:
        sheet = ss.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return {
            "sheet_key": sheet_key, "sheet_name": sheet_name, "exists": False,
            "existing_headers": [], "canonical_headers": canonical,
            "headers_match": False, "required_col_count": len(canonical),
        }

    existing_headers = sheet.row_values(1)
    return {
        "sheet_key": sheet_key, "sheet_name": sheet_name, "exists": True,
        "existing_headers": existing_headers, "canonical_headers": canonical,
        "headers_match": existing_headers == canonical, "required_col_count": len(canonical),
    }


def create_registry_if_missing(sheet_key: str, plan: dict) -> dict:
    """
    Idempotent. If the sheet already exists with exact canonical
    headers -> ALREADY_PRESENT, zero writes. If it doesn't exist ->
    get_business_sheet() creates it with full canonical headers (the
    existing, already-proven creation path — see sheets.py), then this
    function re-verifies the result. If it exists but headers don't
    match canonical -> HEADER_MISMATCH, zero writes, refuses to touch
    an unexpected existing sheet automatically.
    """
    if plan["exists"] and plan["headers_match"]:
        return {"sheet_key": sheet_key, "status": STATUS_ALREADY_PRESENT, "headers_after": plan["existing_headers"]}

    if plan["exists"] and not plan["headers_match"]:
        return {"sheet_key": sheet_key, "status": STATUS_HEADER_MISMATCH, "headers_after": plan["existing_headers"]}

    from business_core.sheets import get_business_sheet

    sheet = get_business_sheet(sheet_key)  # creates with full canonical headers if missing
    headers_after = sheet.row_values(1)

    if headers_after != plan["canonical_headers"]:
        return {"sheet_key": sheet_key, "status": STATUS_VERIFICATION_FAILED, "headers_after": headers_after}

    return {"sheet_key": sheet_key, "status": STATUS_CREATED, "headers_after": headers_after}


def _print_registry_plan(plan: dict) -> None:
    print(f"=== {plan['sheet_key']} ({plan['sheet_name']}) ===")
    print(f"Существует: {plan['exists']}")
    if plan["exists"]:
        print(f"Заголовки совпадают с канонической схемой: {plan['headers_match']}")
        if not plan["headers_match"]:
            print(f"  Найдено:  {plan['existing_headers']}")
            print(f"  Ожидалось: {plan['canonical_headers']}")
    else:
        print(f"Будет создан с {plan['required_col_count']} колонками:")
        for i, h in enumerate(plan["canonical_headers"], start=1):
            print(f"  {i}: {h!r}")
    print()


def run_registry_creation(live: bool) -> dict:
    """Returns {"all_ok": bool, "results": [per-registry dict, ...]}."""
    plans = {key: check_registry(key) for key in REGISTRY_KEYS}

    for key in REGISTRY_KEYS:
        _print_registry_plan(plans[key])

    if not live:
        return {"all_ok": all(not p["exists"] or p["headers_match"] for p in plans.values()),
                "results": [{"sheet_key": k, "status": STATUS_DRY_RUN} for k in REGISTRY_KEYS]}

    results = []
    for key in REGISTRY_KEYS:
        result = create_registry_if_missing(key, plans[key])
        results.append(result)
        print(f"{key}: {result['status']}")

    all_ok = all(r["status"] in (STATUS_ALREADY_PRESENT, STATUS_CREATED) for r in results)
    return {"all_ok": all_ok, "results": results}


def run_owner_bootstrap(live: bool) -> dict:
    """
    Always previews first (dry_run=True), regardless of the --live
    flag — the live write only happens if this script's OWN separate
    --bootstrap-owner YES confirmation was given, checked by the
    caller (main()) before this function is invoked with live=True.
    """
    from business_core.business_builder import bootstrap_owner_from_env

    preview = bootstrap_owner_from_env(dry_run=True)
    print("=== Owner bootstrap: предпросмотр ===")
    print(f"Код: {preview['code']}")
    print(f"OK: {preview['ok']}")
    print()

    if not live:
        return preview

    if not preview["ok"] and preview["code"] != "OWNER_BOOTSTRAP_PREVIEW":
        print("❌ Owner bootstrap отменён — предпросмотр обнаружил проблему, live-запуск не выполняется.")
        return preview

    result = bootstrap_owner_from_env(dry_run=False)
    print("=== Owner bootstrap: результат ===")
    print(f"Код: {result['code']}")
    print(f"OK: {result['ok']}")
    print(f"changed: {result['changed']}")
    print(f"retry_safe: {result['retry_safe']}")
    print(f"completed_steps: {result['completed_steps']}")
    print(f"created_ids: {result['created_ids']}")
    if result["verification_errors"]:
        print(f"verification_errors: {result['verification_errors']}")
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", default="", help="Pass YES to create/verify the four sheets (default: dry-run)")
    parser.add_argument("--bootstrap-owner", default="", help="Pass YES to also run the explicit owner bootstrap (requires --live YES)")
    args = parser.parse_args()

    live = args.live == "YES"
    bootstrap_owner = args.bootstrap_owner == "YES"

    if bootstrap_owner and not live:
        print("❌ --bootstrap-owner YES требует --live YES (сначала должны существовать все четыре листа).")
        return 1

    print("=" * 60)
    print("Шаг 1/2: создание/проверка четырёх Identity & Access Control листов")
    print("=" * 60)
    registry_outcome = run_registry_creation(live)

    if not registry_outcome["all_ok"]:
        print("\n❌ Не все листы в ожидаемом состоянии — bootstrap owner (если запрошен) НЕ выполняется.")
        return 1

    if not live:
        print("\n[DRY-RUN] Изменения НЕ применены. Запустите с --live YES для создания листов.")
        return 0

    if not bootstrap_owner:
        print("\nЛисты созданы/проверены. Owner bootstrap не запрошен (--bootstrap-owner YES не передан).")
        return 0

    print()
    print("=" * 60)
    print("Шаг 2/2: явный owner bootstrap (BC_OWNER_TELEGRAM_USER_ID)")
    print("=" * 60)
    confirm = input("Введите YES для выполнения owner bootstrap: ").strip()
    if confirm != "YES":
        print("Отменено.")
        return 0

    bootstrap_result = run_owner_bootstrap(live=True)
    if not bootstrap_result["ok"]:
        print("\n❌ Owner bootstrap не завершён успешно — см. код выше.")
        return 1

    print("\n✅ Owner bootstrap завершён.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
