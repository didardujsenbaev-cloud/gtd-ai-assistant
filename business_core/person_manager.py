"""
Person Manager — Phase 23D-1: Person Layer Foundation.

Owns PEOPLE_REGISTRY exclusively, following the same manager conventions
as business_core/organization_manager.py, roadmap_manager.py, and
service_manager.py: one domain per module, depends only on
business_core.sheets, honest {ok, ...} write contracts, soft-delete via
Status, duplicate detection before ID generation and before any write.

This module started as a foundation-only phase (see ARCHITECTURE.md /
Phase 23D audit) but has since been completed by later phases:
- /newclient (business_core.telegram_handlers.newclient_confirm()) was
  refactored in Phase 23D-2 — it now calls create_person()/update_person()
  directly for its NEW-Person path, and append_person_biz_id()/
  update_person_drive_info() (via business_builder.py's thin delegators)
  for the SAME_BIZ/OTHER_BIZ paths. It no longer writes PEOPLE_REGISTRY
  directly.
- Person-specific logic previously living in business_core.business_builder
  (normalize_person_name, normalize_phone, find_existing_person,
  get_person_biz_ids) has been RELOCATED here. business_builder.py keeps
  the same function names as thin delegators, for full backward
  compatibility with its own existing callers.
- Phase 31A (Client Domain Ownership Audit) found that this docstring's
  original "not yet refactored" claim was stale relative to the actual
  code and corrected it here; that same audit also found telegram_handlers.py
  still reads PEOPLE_REGISTRY raw (read_business_sheet) in three places
  (show_clients, the /bc dashboard client count, and the legacy
  /newroadmap client-lookup step) — a read-ownership gap this docstring
  update does not resolve, tracked for a future remediation phase.
- Phase 31B (ADR-015, Client Domain Architecture Decision) approved
  Client as a Person role (never a separate entity) and specified a
  canonical identity resolver, Client-role helpers, and stricter
  generic-update boundaries.
- Phase 31C (Canonical Person Identity and Client API Foundation)
  implements that decision: resolve_person_identity() is now the single
  identity-matching implementation (phone/email = strong identifiers,
  full name = weak/ambiguous-only, archived rows never silently reused);
  find_existing_person()/find_duplicate_person() are thin compatibility
  wrappers over it with no matching logic of their own; is_client_person()/
  ensure_client_role()/list_clients() are the new canonical Client-role
  API (still backed by the free-text "Тип" column — no schema change);
  list_person_business_ids()/has_person_business_link() are read-only
  Business-link helpers; update_person()'s editable-fields allowlist no
  longer accepts "Biz IDs", "Primary Biz ID", or "Статус отношений" —
  those are mutated only via append_person_biz_id()/archive_person().
  Production callers (telegram_handlers.py's /newclient, /clients, /bc,
  legacy /newroadmap, and business_builder.py's /newobject validation)
  are NOT migrated onto this foundation yet — that is Phase 31D.

No Google Sheets schema change. "Статус отношений" (the existing column)
is reused as the Person status field — no new column introduced.

Two small helpers (_normalize_biz_ids, _get_biz_id_by_name) are
deliberately DUPLICATED from business_builder.py rather than imported —
both are trivial, pure, sheets-only functions, and importing them would
create a reverse dependency from this manager onto another domain's
module, violating the Layer Dependency Rule that a manager depends only
on business_core.sheets (same precedent as organization_manager.py's
_normalize_org_name(), Phase 23C).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Canonical status model (see ENGINEERING_STANDARDS.md, Google Sheets
# Standards). Two values only — matching DEPARTMENT_STATUS, not
# ROLE_STATUS's four-value set: a Person either currently matters to
# the business (active) or has been retired from active tracking
# (archived). There is no "planned Person" concept, and a third
# "inactive" state would be redundant with "archived" here — unlike
# Assignment's "paused", which describes a temporary pause in a
# specific role, not the Person's own existence (see Phase 23D
# architecture report, Step 3).
# ─────────────────────────────────────────────────────────────

PERSON_STATUS = ("active", "archived")


def is_person_archived(person: Optional[dict]) -> bool:
    """Read-only. True iff person["status"] == "archived". Phase 31C
    (ADR-015 Decision 5/13): the single place archived-ness is decided
    from a canonical Person dict, used by resolve_person_identity(),
    ensure_client_role(), and list_clients()."""
    return bool(person) and person.get("status") == "archived"


# ─────────────────────────────────────────────────────────────
# Normalization helpers (relocated from business_builder.py, hardened
# to guard blank/None inputs — a minor, safe improvement made during
# the move, matching every other manager's normalization helper).
# ─────────────────────────────────────────────────────────────

def normalize_person_name(name: str) -> str:
    """Unicode NFKC + trim + collapse internal whitespace + casefold.
    No fuzzy matching, no token reordering, no substring matching — a
    name either normalizes to the same string or it doesn't (Phase 31C,
    ADR-015 Decision 3). NFKC/casefold added in Phase 31C; the previous
    trim+collapse+lower() recipe is unchanged in effect for existing
    Cyrillic/ASCII production data (casefold() == lower() for those
    alphabets), so this is additive robustness, not a behavior change
    for current rows."""
    normalized = unicodedata.normalize("NFKC", (name or "").strip())
    return re.sub(r"\s+", " ", normalized).casefold()


def normalize_phone(phone: str) -> str:
    """Strip everything except digits — comparable regardless of
    formatting ("+7 (777) 123-45-67" and "8 777 123 45 67" normalize
    to the same digit string).

    Deliberately does NOT canonicalize Kazakhstan's "8XXXXXXXXXX" vs
    "+7XXXXXXXXXX" leading-digit convention (ADR-015 Decision 3 asks
    for this, but test_business_person_manager.py's
    test_normalize_phone locks in the current digit-strip-only
    contract: normalize_phone("8 707 123 45 67") == "87071234567", not
    "77071234567"). Changing this public function would silently
    change find_duplicate_person()/create_person()'s existing
    production duplicate-matching behavior, which Phase 31C is
    forbidden from doing. The KZ 8/+7 equivalence is instead applied
    only inside resolve_person_identity()'s strong-match comparison,
    via _kz_phone_identity_key() below — additive, and scoped to the
    new resolver only. See Phase 31C final report, Part 8, for the
    explicit compatibility-vs-spec tradeoff this records."""
    return re.sub(r"\D", "", (phone or "").strip())


def _kz_phone_identity_key(phone_digits: str) -> str:
    """Kazakhstan-specific canonicalization used ONLY for
    resolve_person_identity()'s strong phone-match comparison (never
    by normalize_phone() itself — see its docstring). An 11-digit
    number starting with the domestic trunk prefix "8" is treated as
    identical to the same number in "+7" international form for
    identity purposes; every other digit string (other countries,
    short/invalid numbers) passes through unchanged."""
    if len(phone_digits) == 11 and phone_digits[0] == "8":
        return "7" + phone_digits[1:]
    return phone_digits


def normalize_email(email: str) -> str:
    """Unicode NFKC + trim + casefold. No mailbox canonicalization
    (dot-stripping, plus-addressing, etc.) — deliberately simple."""
    return unicodedata.normalize("NFKC", (email or "").strip()).casefold()


def _normalize_email(email: str) -> str:
    """Backward-compatible private alias for normalize_email() (Phase
    31C made the email normalizer public per ADR-015 Decision 3)."""
    return normalize_email(email)


def _normalize_biz_ids(value: str) -> list[str]:
    """Parse the "Biz IDs" comma/semicolon-list column into a list.
    Duplicated from business_builder.py's normalize_biz_ids() — trivial,
    pure, no dependency beyond string parsing."""
    if not value or not value.strip():
        return []
    return [x.strip() for x in value.replace(";", ",").split(",") if x.strip()]


def _get_biz_id_by_name(biz_name: str) -> str:
    """Resolve a Business ID from its display name in BIZ_REGISTRY, or
    return biz_name unchanged if not found. Duplicated from
    business_builder.py's _get_biz_id_by_name() — reads only
    business_core.sheets, no cross-manager dependency."""
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("biz_registry")
        for row in rows:
            if row.get("Название", "").strip() == (biz_name or "").strip():
                return row.get("ID", biz_name)
    except Exception as exc:
        log.debug(f"_get_biz_id_by_name: не удалось прочитать BIZ_REGISTRY: {exc}")
    return biz_name


def get_person_biz_ids(person_id: str) -> list[str]:
    """
    Read-only. Список Business ID для человека из PEOPLE_REGISTRY.

    Relocated from business_builder.py. Behavior preserved for current
    production data: reads "Biz IDs" if populated, else falls back to
    resolving the legacy "Бизнесы" name column. (Verified against live
    production data during the Phase 23D audit: PRS-001 already has
    "Biz IDs" populated, so the legacy fallback is dead in practice
    today — kept only for any older row that might still rely on it.)
    """
    if not person_id:
        return []
    try:
        from business_core.sheets import get_business_sheet

        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        biz_ids_col = _col("Biz IDs")
        biz_col = _col("Бизнесы")

        for row in all_values[1:]:
            if not row or row[0] != person_id:
                continue
            if biz_ids_col is not None and biz_ids_col < len(row) and row[biz_ids_col].strip():
                return _normalize_biz_ids(row[biz_ids_col])
            if biz_col is not None and biz_col < len(row) and row[biz_col].strip():
                biz_name = row[biz_col].strip()
                biz_id = _get_biz_id_by_name(biz_name)
                return [biz_id] if biz_id != biz_name else []
        return []
    except Exception as exc:
        log.warning(f"get_person_biz_ids({person_id}) error: {exc}")
        return []


# ─────────────────────────────────────────────────────────────
# Read: point lookup by ID
# ─────────────────────────────────────────────────────────────

_WANTED_PERSON_FIELDS = [
    "ID", "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp", "Telegram",
    "Email", "Город", "Компания", "Должность", "Тип", "Подтип",
    "Уровень доверия", "Статус отношений", "Теплота", "Комментарий",
    "Biz IDs", "Company ID", "Citizenship", "Passport / ID",
    "Primary Biz ID", "Google Drive", "Drive Folder ID",
    "Дата первого контакта", "Дата последнего контакта",
]


def _person_row_to_dict(row_num: int, v: dict) -> dict:
    return {
        "row_num":            row_num,
        "person_id":          v["ID"],
        "full_name":          v["ФИО"],
        "short_name":         v["Имя"],
        "phone":              v["Телефон"],
        "phone2":             v["Телефон 2"],
        "whatsapp":           v["WhatsApp"],
        "telegram":           v["Telegram"],
        "email":              v["Email"],
        "city":               v["Город"],
        "company":            v["Компания"],
        "position":           v["Должность"],
        "person_type":        v["Тип"],
        "subtype":            v["Подтип"],
        "trust_level":        v["Уровень доверия"],
        "status":             v["Статус отношений"],
        "warmth":             v["Теплота"],
        "notes":              v["Комментарий"],
        "biz_ids":            _normalize_biz_ids(v["Biz IDs"]),
        "company_id":         v["Company ID"],
        "citizenship":        v["Citizenship"],
        "passport_id":        v["Passport / ID"],
        "primary_biz_id":     v["Primary Biz ID"],
        "google_drive":       v["Google Drive"],
        "drive_folder_id":    v["Drive Folder ID"],
        "first_contact_date": v["Дата первого контакта"],
        "last_contact_date":  v["Дата последнего контакта"],
    }


def _find_person_row(person_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not person_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("people_registry")
        cell = sheet.find(person_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        v = read_row_by_headers(headers, row, _WANTED_PERSON_FIELDS)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_person_row({person_id}) error: {exc}")
        return None


def find_person_by_id(person_id: str) -> Optional[dict]:
    """
    Найти Person по ID. Read-only.

    Returns:
        dict с полями row_num, person_id, full_name, short_name, phone,
        phone2, whatsapp, telegram, email, city, company, position,
        person_type, subtype, trust_level, status, warmth, notes,
        biz_ids (list), company_id, citizenship, passport_id,
        primary_biz_id, google_drive, drive_folder_id,
        first_contact_date, last_contact_date — или None.
    """
    found = _find_person_row(person_id)
    if not found:
        return None
    row_num, v = found
    return _person_row_to_dict(row_num, v)


# ─────────────────────────────────────────────────────────────
# Read: full-scan search / list
# ─────────────────────────────────────────────────────────────

def _list_people_raw() -> list[dict]:
    """Internal: read every PEOPLE_REGISTRY row, unfiltered, in the
    same dict shape as find_person_by_id() (minus row_num, which the
    scan path doesn't need to expose)."""
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _g(row, h):
            i = idx.get(h)
            return row[i].strip() if (i is not None and i < len(row)) else ""

        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            v = {h: _g(row, h) for h in _WANTED_PERSON_FIELDS}
            person = _person_row_to_dict(0, v)
            del person["row_num"]
            results.append(person)
        return results
    except Exception as exc:
        log.warning(f"_list_people_raw() error: {exc}")
        return []


def _scan_people_with_row_num() -> list[dict]:
    """Internal: same scan as _list_people_raw(), but keeps row_num —
    needed by resolve_person_identity() so its compatibility wrappers
    (find_existing_person/find_duplicate_person) can reconstruct their
    legacy row_num-bearing return shape without a second sheet read.
    Deliberately a separate, small duplication of the scan loop rather
    than changing _list_people_raw()'s existing (row_num-stripped)
    return shape, which list_people()/list_clients()/callers already
    depend on."""
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _g(row, h):
            i = idx.get(h)
            return row[i].strip() if (i is not None and i < len(row)) else ""

        results = []
        for row_num, row in enumerate(all_values[1:], start=2):
            if not row or not row[0].strip():
                continue
            v = {h: _g(row, h) for h in _WANTED_PERSON_FIELDS}
            results.append(_person_row_to_dict(row_num, v))
        return results
    except Exception as exc:
        log.warning(f"_scan_people_with_row_num() error: {exc}")
        return []


def resolve_person_identity(
    *,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    include_archived: bool = False,
) -> dict:
    """
    Canonical Person identity resolver (Phase 31C, ADR-015 Decisions 2/4/5).
    THE single implementation of "is this the same Person" — every other
    identity-matching function in this module (find_existing_person,
    find_duplicate_person) is a thin wrapper over this.

    Strong identifiers: normalized phone (also matches the WhatsApp
    column — a WhatsApp number is still a phone identifier for the same
    person) and normalized email. A single strong match is enough to
    resolve identity. Weak identifier: normalized full name — a name
    match is NEVER treated as automatic reuse, even when it is the only
    signal and there is exactly one candidate (status is always
    "ambiguous" in that case).

    Kazakhstan phone canonicalization ("8XXXXXXXXXX" == "+7XXXXXXXXXX")
    is applied here (via _kz_phone_identity_key), not in the public
    normalize_phone() — see that function's docstring for why.

    Returns:
        {
            "status": "not_found" | "single_match" | "ambiguous" | "archived_match",
            "person": dict | None,
            "matches": list[dict],
            "matched_by": list[str],   # subset of ["phone", "email", "name"], fixed order
            "error": str | None,
        }

    Never picks an arbitrary first match: multiple strong matches, or
    any active+archived strong-match collision, is reported as
    "ambiguous" with all candidates in "matches" rather than resolved
    silently. A strong match found ONLY among archived rows (with
    include_archived=False) is reported as "archived_match" and is
    never auto-reused or auto-reactivated by this function.
    """
    norm_name = normalize_person_name(name) if name else ""
    norm_phone = normalize_phone(phone) if phone else ""
    norm_email = normalize_email(email) if email else ""

    empty_result = {"status": "not_found", "person": None, "matches": [], "matched_by": [], "error": None}
    if not norm_name and not norm_phone and not norm_email:
        return empty_result

    phone_key = _kz_phone_identity_key(norm_phone) if norm_phone else ""

    try:
        people = _scan_people_with_row_num()
    except Exception as exc:
        log.warning(f"resolve_person_identity scan error: {exc}")
        return {**empty_result, "error": str(exc)}

    strong_active, strong_archived, weak_active, weak_archived = [], [], [], []

    for person in people:
        archived = is_person_archived(person)

        p_phone_key = _kz_phone_identity_key(normalize_phone(person.get("phone", "")))
        p_wa_key = _kz_phone_identity_key(normalize_phone(person.get("whatsapp", "")))
        p_email = normalize_email(person.get("email", ""))
        p_name = normalize_person_name(person.get("full_name", ""))

        phone_strong = bool(phone_key and (p_phone_key == phone_key or p_wa_key == phone_key))
        email_strong = bool(norm_email and p_email == norm_email)
        name_weak = bool(norm_name and p_name == norm_name)

        if not phone_strong and not email_strong and not name_weak:
            continue

        by = []
        if phone_strong:
            by.append("phone")
        if email_strong:
            by.append("email")
        if name_weak:
            by.append("name")

        entry = {"person": person, "matched_by": by}
        if phone_strong or email_strong:
            (strong_archived if archived else strong_active).append(entry)
        else:
            (weak_archived if archived else weak_active).append(entry)

    def _finalize(status: str, entries: list[dict], person: Optional[dict]) -> dict:
        matched_by_union = []
        for key in ("phone", "email", "name"):
            if any(key in e["matched_by"] for e in entries):
                matched_by_union.append(key)
        return {
            "status": status,
            "person": person,
            "matches": [e["person"] for e in entries],
            "matched_by": matched_by_union,
            "error": None,
        }

    if include_archived:
        combined_strong = strong_active + strong_archived
        combined_weak = weak_active + weak_archived
        if combined_strong:
            if len(combined_strong) == 1:
                return _finalize("single_match", combined_strong, combined_strong[0]["person"])
            return _finalize("ambiguous", combined_strong, None)
        if combined_weak:
            return _finalize("ambiguous", combined_weak, None)
        return dict(empty_result)

    # Default: archived rows never silently resolve identity on their own.
    if strong_active and strong_archived:
        return _finalize("ambiguous", strong_active + strong_archived, None)
    if strong_active:
        if len(strong_active) == 1:
            return _finalize("single_match", strong_active, strong_active[0]["person"])
        return _finalize("ambiguous", strong_active, None)
    if strong_archived:
        person = strong_archived[0]["person"] if len(strong_archived) == 1 else None
        return _finalize("archived_match", strong_archived, person)
    if weak_active:
        return _finalize("ambiguous", weak_active, None)
    return dict(empty_result)


def list_people(business_id: str = "", person_type: str = "", status: str = "") -> list[dict]:
    """
    Список People, опционально отфильтрованный по Business ID
    (проверяется через Biz IDs — многозначное поле), Person Type и/или
    Status. Read-only. Пустые фильтры — вернуть все строки.
    """
    results = []
    for person in _list_people_raw():
        if business_id and business_id not in person["biz_ids"]:
            continue
        if person_type and person["person_type"] != person_type:
            continue
        if status and person["status"] != status:
            continue
        results.append(person)
    return results


def list_people_by_business(business_id: str) -> list[dict]:
    """Read-only. Thin wrapper over list_people(business_id=...)."""
    if not business_id:
        return []
    return list_people(business_id=business_id)


def list_people_by_type(person_type: str) -> list[dict]:
    """Read-only. Thin wrapper over list_people(person_type=...)."""
    if not person_type:
        return []
    return list_people(person_type=person_type)


def find_person(name: str = "", phone: str = "", email: str = "", business_id: str = "") -> Optional[dict]:
    """
    Read-only, general-purpose weak search (ANY status, including
    archived — unlike find_duplicate_person(), which deliberately
    excludes archived rows because it exists specifically to decide
    "should a create be blocked"). Matches on normalized phone OR
    normalized name OR normalized email; if business_id is given, the
    match must also have that Business ID among its Biz IDs.

    Returns the first match (in sheet order), or None.
    """
    if not name and not phone and not email:
        return None

    norm_name = normalize_person_name(name) if name else ""
    norm_phone = normalize_phone(phone) if phone else ""
    norm_email = _normalize_email(email) if email else ""

    for person in _list_people_raw():
        if business_id and business_id not in person["biz_ids"]:
            continue

        phone_match = bool(norm_phone and normalize_phone(person["phone"]) == norm_phone)
        name_match = bool(norm_name and normalize_person_name(person["full_name"]) == norm_name)
        email_match = bool(norm_email and _normalize_email(person["email"]) == norm_email)

        if phone_match or name_match or email_match:
            return person

    return None


def find_existing_person(
    name: Optional[str] = None,
    phone: Optional[str] = None,
    biz_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Read-only. Phase 31C: COMPATIBILITY WRAPPER over
    resolve_person_identity() — contains no matching logic of its own.
    Kept as a SEPARATE function from find_person()/find_duplicate_person()
    because its callers (business_core.telegram_handlers.
    newclient_confirm(), via business_builder.py's delegator) depend on
    its EXACT legacy return shape and two semantics resolve_person_identity()
    does not itself express:

      1. It does NOT exclude archived rows — achieved here by calling
         resolve_person_identity(include_archived=True), so archived
         and active candidates are resolved together exactly like the
         legacy scan did.
      2. It returns "same_biz": False (rather than excluding the row)
         when biz_id is given but doesn't match the resolved Person's
         Biz IDs — a business-relationship concern layered on top of
         identity resolution, not an identity decision itself (the
         legacy code's own biz_id check never actually excluded a
         phone/name match either — same_biz only affects this field).

    When resolve_person_identity() reports "ambiguous" (e.g. a
    name-only match, or multiple strong matches), this wrapper
    preserves the legacy "first match in sheet order wins" behavior by
    taking matches[0] — a presentation-layer translation of the
    canonical result, not a new identity decision. Callers relying on
    this exact legacy shape are migrated in Phase 31D.

    Returns:
        {
            "row_num":         int,
            "prs_id":          str,
            "full_name":       str,
            "biz_ids":         list[str],
            "primary_biz_id":  str,
            "drive_url":       str,
            "drive_folder_id": str,
            "phone_raw":       str,
            "same_biz":        bool,
        }
        или None.
    """
    if not name and not phone:
        return None

    result = resolve_person_identity(name=name, phone=phone, email=None, include_archived=True)
    if result["error"] is not None:
        log.warning(f"find_existing_person error: {result['error']}")
        return None

    if result["status"] in ("single_match",):
        person = result["person"]
    elif result["status"] == "ambiguous":
        person = result["matches"][0] if result["matches"] else None
    else:  # not_found (archived_match cannot occur with include_archived=True)
        person = None

    if person is None:
        return None

    biz_ids = person["biz_ids"]
    same_biz = (biz_id in biz_ids) if biz_id else True

    return {
        "row_num": person["row_num"],
        "prs_id": person["person_id"],
        "full_name": person["full_name"],
        "biz_ids": biz_ids,
        "primary_biz_id": person["primary_biz_id"],
        "drive_url": person["google_drive"],
        "drive_folder_id": person["drive_folder_id"],
        "phone_raw": person["phone"],
        "same_biz": same_biz,
    }


def find_duplicate_person(
    full_name: str = "", phone: str = "", email: str = "", business_id: str = "",
) -> Optional[dict]:
    """
    Read-only. Phase 31C: COMPATIBILITY WRAPPER over
    resolve_person_identity() — contains no matching logic of its own.
    The pre-create duplicate check (originally Phase 23D-1 §5): identity
    is based on the real person — normalized phone, normalized full
    name, and email — NEVER Person Type (an attribute of the
    relationship, not the person's identity). business_id narrows the
    match when supplied (checked against the multi-valued Biz IDs
    column — a business-relationship filter, layered on top of identity
    resolution here, same as resolve_person_identity()'s signature
    intentionally omits biz filtering).

    Archived People NEVER block a new create: resolve_person_identity()
    is called with include_archived=False (the default), so a
    strong-only match against an archived row surfaces as
    "archived_match" — deliberately treated as "no active duplicate"
    below (never as a candidate), preserving the legacy guarantee
    exactly.

    Ambiguous results (multiple strong matches, or a name-only match)
    resolve to the first candidate in sheet order, preserving this
    function's legacy "return the first match" contract — a
    presentation-layer choice, not a new identity decision.
    """
    if not full_name and not phone and not email:
        return None

    result = resolve_person_identity(name=full_name, phone=phone, email=email, include_archived=False)

    if result["status"] == "single_match":
        candidates = [result["person"]]
    elif result["status"] == "ambiguous":
        candidates = list(result["matches"])
    else:  # not_found, archived_match — archived never blocks a new create
        candidates = []

    if business_id:
        candidates = [p for p in candidates if business_id in p["biz_ids"]]

    return candidates[0] if candidates else None


# ─────────────────────────────────────────────────────────────
# Write: create / update / archive
# ─────────────────────────────────────────────────────────────

def create_person(
    full_name: str,
    phone: str = "",
    email: str = "",
    person_type: str = "",
    business_id: str = "",
    status: str = "active",
    notes: str = "",
) -> dict:
    """
    Создать Person в PEOPLE_REGISTRY.

    full_name обязателен. business_id, если указан, валидируется против
    BIZ_REGISTRY (read-only, как у create_department()). Duplicate
    detection (find_duplicate_person) выполняется ДО генерации ID и ДО
    любой записи — см. find_duplicate_person() для точного правила
    идентичности.

    Не предполагает "клиентских" значений по умолчанию (в отличие от
    /newclient) — Теплота/Уровень доверия оставляются пустыми, если не
    переданы явно, поскольку Person Manager обслуживает и внутренних
    сотрудников, для которых клиентские понятия "теплота отношений" не
    имеют смысла.

    Returns:
        {"ok": bool, "person_id": str, "error": str | None}
    """
    if not full_name:
        return {"ok": False, "person_id": "", "error": "full_name обязателен"}

    if status not in PERSON_STATUS:
        return {
            "ok": False, "person_id": "",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(PERSON_STATUS)}",
        }

    if business_id:
        try:
            from business_core.sheets import find_row_by_id
            if not find_row_by_id("biz_registry", business_id):
                return {"ok": False, "person_id": "", "error": f"Business '{business_id}' не найден"}
        except Exception as exc:
            log.error(f"create_person business_id validation error: {exc}")
            return {"ok": False, "person_id": "", "error": str(exc)}

    try:
        duplicate = find_duplicate_person(
            full_name=full_name, phone=phone, email=email, business_id=business_id,
        )
    except Exception as exc:
        log.error(f"create_person duplicate check error: {exc}")
        return {"ok": False, "person_id": "", "error": str(exc)}

    if duplicate is not None:
        return {
            "ok": False, "person_id": "",
            "error": (
                f"Активный Person с такими данными уже существует: "
                f"{duplicate['person_id']} ({duplicate['full_name']})"
            ),
        }

    try:
        from business_core.sheets import (
            generate_next_id, get_business_sheet, append_business_row, row_from_header_map,
        )
        from datetime import datetime

        person_id = generate_next_id("people_registry")
        now = datetime.now().strftime("%Y-%m-%d")
        short_name = full_name.split()[0] if full_name.split() else full_name

        sheet = get_business_sheet("people_registry")
        headers = sheet.row_values(1)

        row = row_from_header_map(headers, {
            "ID": person_id,
            "ФИО": full_name,
            "Имя": short_name,
            "Телефон": phone,
            "Email": email,
            "Тип": person_type,
            "Статус отношений": status,
            "Комментарий": notes,
            "Biz IDs": business_id,
            "Primary Biz ID": business_id,
            "Дата первого контакта": now,
            "Дата последнего контакта": now,
        })
        append_business_row("people_registry", row)
        log.info(f"create_person: {person_id} / {full_name}")
        return {"ok": True, "person_id": person_id, "error": None}
    except Exception as exc:
        log.error(f"create_person error: {exc}")
        return {"ok": False, "person_id": "", "error": str(exc)}


_PERSON_EDITABLE_FIELDS = (
    "ФИО", "Имя", "Телефон", "Телефон 2", "WhatsApp", "Telegram", "Email",
    "Город", "Компания", "Должность", "Тип", "Подтип", "Уровень доверия",
    "Теплота", "Комментарий", "Бизнесы",
    "Company ID", "Citizenship", "Passport / ID",
    "Дата последнего контакта",
)
# Phase 31C (ADR-015 Decision 9): "Biz IDs", "Primary Biz ID", and
# "Статус отношений" were REMOVED from this allowlist. Business-link
# mutation is add-only and goes through append_person_biz_id() only;
# status changes go through archive_person() only (which now writes
# the status cell directly via _archive_write_status(), bypassing this
# allowlist entirely, since it is no longer editable here). "Бизнесы"
# (the legacy free-text business-name column, distinct from the
# structured "Biz IDs"/"Primary Biz ID" link) is NOT restricted — it is
# still written by newclient_confirm() today (test_business_newclient_
# headersafe.py's test_12) and Phase 31B's ADR only targeted the
# structured link fields.


def update_person(person_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Person. Точечная запись только
    переданных колонок — по имени заголовка, только в найденную строку.
    "ID" и "Дата первого контакта" не редактируемы через эту функцию
    (ID — ключ записи; первый контакт устанавливается один раз при
    создании). "Biz IDs"/"Primary Biz ID" (use append_person_biz_id())
    and "Статус отношений" (use archive_person()) are likewise not
    editable here as of Phase 31C — see _PERSON_EDITABLE_FIELDS.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not person_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "person_id не указан"}

    unknown = [k for k in updates if k not in _PERSON_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_person_row(person_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Person '{person_id}' не найден"}
    row_num, current = found

    field_key_map = {h: h for h in _PERSON_EDITABLE_FIELDS}

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("people_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        updated_fields = []
        changed = False
        for header, new_value in updates.items():
            if header not in idx:
                continue
            old_value = current.get(field_key_map[header], "")
            if str(old_value) == str(new_value):
                continue
            sheet.update_cell(row_num, idx[header] + 1, new_value)
            updated_fields.append(header)
            changed = True

        log.info(f"update_person: {person_id} fields={updated_fields}")
        return {"ok": True, "changed": changed, "updated_fields": tuple(updated_fields), "error": None}
    except Exception as exc:
        log.error(f"update_person({person_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


def _archive_write_status(person_id: str, status: str) -> dict:
    """Internal: direct single-cell "Статус отношений" write, used only
    by archive_person(). Phase 31C removed "Статус отношений" from
    _PERSON_EDITABLE_FIELDS (status changes must go through
    archive_person(), not generic update_person()) — this helper is
    the dedicated, narrow write path that replaces the old
    update_person()-mediated call, mirroring the same pattern already
    used by append_person_biz_id()/update_person_drive_info() for
    their own dedicated fields.

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    found = _find_person_row(person_id)
    if not found:
        return {"ok": False, "changed": False, "error": f"Person '{person_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("people_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)
        col = idx.get("Статус отношений")
        if col is None:
            return {"ok": False, "changed": False, "error": "Колонка 'Статус отношений' не найдена"}

        if current.get("status") == status:
            return {"ok": True, "changed": False, "error": None}

        sheet.update_cell(row_num, col + 1, status)
        return {"ok": True, "changed": True, "error": None}
    except Exception as exc:
        log.error(f"_archive_write_status({person_id}) error: {exc}")
        return {"ok": False, "changed": False, "error": str(exc)}


def archive_person(person_id: str) -> dict:
    """
    Soft-delete Person через "Статус отношений"=archived. Идемпотентна:
    повторный вызов на уже archived Person возвращает ok=True,
    changed=False. Не удаляет Person Role Assignments — отдельная
    сущность с собственным жизненным циклом (Organization Layer,
    неизменна этой фазой).

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    existing = find_person_by_id(person_id)
    if not existing:
        return {"ok": False, "changed": False, "error": f"Person '{person_id}' не найден"}

    if existing["status"] == "archived":
        return {"ok": True, "changed": False, "error": None}

    return _archive_write_status(person_id, "archived")


def append_person_biz_id(person_id: str, biz_id: str) -> dict:
    """
    Добавить biz_id в колонку "Biz IDs" — append-без-дублей, а не
    overwrite. Primary Biz ID заполняется только если он пуст (никогда
    не перезаписывается). Phase 23D-3B1: relocated from
    business_core.business_builder.add_biz_id_to_person(), which
    becomes a thin delegator in Phase 23D-3B2.

    This is deliberately NOT expressed through update_person() —
    read-modify-write append+dedup semantics belong here, not in a
    flat field-setter.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}

    "changed": False (with "ok": True) means the biz_id was already
    present — a legitimate no-op, not an error. Duplicate detection is
    a case-sensitive exact string match against the parsed Biz IDs list.

    Not atomic: up to two sequential update_cell() calls (Biz IDs, then
    conditionally Primary Biz ID). If the second call raises after the
    first already succeeded, the except branch below still returns
    "ok": False / "changed": False / "updated_fields": () — it cannot
    prove how many cells actually landed. Same disclosed limitation as
    update_person() (Phase 23D-2 technical debt) — not solved here.
    """
    if not person_id or not biz_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "person_id и biz_id обязательны"}

    try:
        from business_core.sheets import get_business_sheet

        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "changed": False, "updated_fields": (), "error": f"Person '{person_id}' не найден"}

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        biz_ids_col = _col("Biz IDs")
        prim_col    = _col("Primary Biz ID")

        for i, row in enumerate(all_values[1:], start=2):
            if not row or row[0] != person_id:
                continue

            current_ids = _normalize_biz_ids(
                row[biz_ids_col] if biz_ids_col is not None and biz_ids_col < len(row) else ""
            )

            if biz_id in current_ids:
                log.debug(f"append_person_biz_id: {biz_id} уже есть у {person_id}")
                return {"ok": True, "changed": False, "updated_fields": (), "error": None}

            current_ids.append(biz_id)
            new_biz_ids_str = ",".join(current_ids)
            updated_fields = []

            if biz_ids_col is not None:
                sheet.update_cell(i, biz_ids_col + 1, new_biz_ids_str)
                updated_fields.append("Biz IDs")
                log.info(f"append_person_biz_id: {person_id} → Biz IDs = {new_biz_ids_str}")

            if prim_col is not None:
                current_prim = row[prim_col].strip() if prim_col < len(row) else ""
                if not current_prim:
                    sheet.update_cell(i, prim_col + 1, biz_id)
                    updated_fields.append("Primary Biz ID")
                    log.info(f"append_person_biz_id: {person_id} → Primary Biz ID = {biz_id}")

            return {"ok": True, "changed": True, "updated_fields": tuple(updated_fields), "error": None}

        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Person '{person_id}' не найден"}

    except Exception as exc:
        log.warning(f"append_person_biz_id({person_id}, {biz_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


def update_person_drive_info(person_id: str, folder_id: str = "", folder_url: str = "") -> dict:
    """
    Дозаполнить Drive-информацию Person'а — обновляет "Google Drive"
    (URL) и "Drive Folder ID" НЕЗАВИСИМО друг от друга, только если
    текущее значение поля пусто; никогда не перезаписывает уже
    заполненное значение. Phase 23D-3B1: relocated from
    business_core.business_builder.update_person_drive_info(), which
    becomes a thin delegator in Phase 23D-3B2.

    Deliberately self-contained rather than routed through
    update_person() — per Phase 23D-3B architectural decision, Drive
    fields are NOT added to _PERSON_EDITABLE_FIELDS; this function owns
    its own specialized fill-if-empty read-modify-write, exactly as the
    relocated logic did before.

    Known, documented asymmetry preserved as-is (not fixed in this
    phase): a falsy `folder_id` short-circuits the whole call before
    `folder_url` is even considered, so a call with only `folder_url`
    set and `folder_id=""` returns without attempting to fill the URL
    alone. This mirrors the pre-existing business_builder behavior
    exactly — treated as technical debt, not addressed here.

    Not atomic: up to two independent update_cell() calls (Google
    Drive, Drive Folder ID). If the second call raises after the first
    already succeeded, the except branch below still returns
    "ok": False / "changed": False / "updated_fields": () — it cannot
    prove how many cells actually landed. Same disclosed limitation as
    update_person() (Phase 23D-2 technical debt) — not solved here.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not person_id or not folder_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "person_id и folder_id обязательны"}

    try:
        from business_core.sheets import get_business_sheet

        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "changed": False, "updated_fields": (), "error": f"Person '{person_id}' не найден"}

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        drive_col    = _col("Google Drive")
        drive_id_col = _col("Drive Folder ID")

        for i, row in enumerate(all_values[1:], start=2):
            if not row or row[0] != person_id:
                continue

            updated_fields = []

            if drive_col is not None:
                current = row[drive_col].strip() if drive_col < len(row) else ""
                if not current and folder_url:
                    sheet.update_cell(i, drive_col + 1, folder_url)
                    updated_fields.append("Google Drive")

            if drive_id_col is not None:
                current = row[drive_id_col].strip() if drive_id_col < len(row) else ""
                if not current and folder_id:
                    sheet.update_cell(i, drive_id_col + 1, folder_id)
                    updated_fields.append("Drive Folder ID")

            if updated_fields:
                log.info(f"update_person_drive_info: {person_id} → Drive дозаполнен ({', '.join(updated_fields)})")

            return {"ok": True, "changed": bool(updated_fields), "updated_fields": tuple(updated_fields), "error": None}

        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Person '{person_id}' не найден"}

    except Exception as exc:
        log.warning(f"update_person_drive_info({person_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Client role — Phase 31C (ADR-015 Decision 5). Client is NOT a
# separate entity: it is a Person whose free-text "Тип" column holds a
# recognized value. No schema change, no multi-role list — exact
# normalized matching only, never substring.
# ─────────────────────────────────────────────────────────────

_RECOGNIZED_CLIENT_TYPES = frozenset({
    "клиент",
    "клиент по узаконению",
})


def is_client_person(person: Optional[dict]) -> bool:
    """
    Read-only. True iff person["person_type"], normalized (trim +
    casefold — same recipe as normalize_person_name's casefold step,
    but no NFKC/whitespace-collapse needed for these short recognized
    values), exactly matches one of _RECOGNIZED_CLIENT_TYPES. Never a
    substring check — "неклиент" and "потенциальный клиент" are both
    False, since neither equals a recognized value.
    """
    if not person:
        return False
    normalized = (person.get("person_type") or "").strip().casefold()
    return normalized in _RECOGNIZED_CLIENT_TYPES


def ensure_client_role(person_id: str) -> dict:
    """
    Idempotently ensure a Person is recognized as a Client, WITHOUT
    ever silently overwriting an existing, different, non-empty "Тип"
    category (Phase 31C, ADR-015 Decision 5/12). Never touches an
    archived Person (Decision 5: "archived Person не менять").

    Policy:
      - Person not found            → ok=False, error set.
      - Person is archived          → ok=False, error set (no write).
      - "Тип" already recognized    → no-op, already_client=True.
      - "Тип" empty                 → set to "клиент".
      - "Тип" non-empty, different  → NOT overwritten; ok=True (no
        error — this is not a failure, just a decision this function
        deliberately defers), manual_decision_required=True, warning set.

    Returns:
        {
            "ok": bool, "person_id": str, "changed": bool,
            "already_client": bool, "manual_decision_required": bool,
            "warning": str | None, "error": str | None,
        }
    """
    base = {
        "ok": False, "person_id": person_id, "changed": False,
        "already_client": False, "manual_decision_required": False,
        "warning": None, "error": None,
    }

    person = find_person_by_id(person_id)
    if not person:
        return {**base, "error": f"Person '{person_id}' не найден"}

    if is_person_archived(person):
        return {**base, "error": f"Person '{person_id}' archived — client role не может быть установлена"}

    if is_client_person(person):
        return {**base, "ok": True, "already_client": True}

    current_type = (person.get("person_type") or "").strip()
    if not current_type:
        result = update_person(person_id, {"Тип": "клиент"})
        return {
            **base,
            "ok": result["ok"],
            "changed": result["changed"],
            "error": result["error"],
        }

    return {
        **base,
        "ok": True,
        "manual_decision_required": True,
        "warning": (
            f"Тип='{current_type}' уже задан для {person_id} — client role "
            f"не установлена автоматически, требуется явное решение"
        ),
    }


def list_clients(
    *,
    biz_id: Optional[str] = None,
    query: Optional[str] = None,
    include_archived: bool = False,
) -> list[dict]:
    """
    Read-only. Canonical Client listing (Phase 31C, ADR-015 Decision 6)
    — replaces the substring "клиент" in Тип checks duplicated across
    telegram_handlers.py (not migrated onto this yet; that is Phase
    31D). Filters via is_client_person() (exact recognized values, not
    substring). archived excluded by default. query matches (case-
    insensitively) against person_id, full_name, phone, or email.
    Deterministic ordering: by person_id.
    """
    results = []
    for person in _list_people_raw():
        if not is_client_person(person):
            continue
        if not include_archived and is_person_archived(person):
            continue
        if biz_id and biz_id not in person["biz_ids"]:
            continue
        if query:
            q = query.strip().casefold()
            haystack = " ".join([
                person.get("person_id") or "",
                person.get("full_name") or "",
                person.get("phone") or "",
                person.get("email") or "",
            ]).casefold()
            if q not in haystack:
                continue
        results.append(person)

    results.sort(key=lambda p: p.get("person_id") or "")
    return results


# ─────────────────────────────────────────────────────────────
# Person↔Business query APIs — Phase 31C (ADR-015 Decision 10). Read-
# only; append_person_biz_id() remains the ONLY mutation path
# (PERSON_BUSINESS_LINK_MUTATION_IS_ADD_ONLY).
# ─────────────────────────────────────────────────────────────

def list_person_business_ids(person_or_id) -> list[str]:
    """
    Read-only. Canonical, deduplicated, stable-ordered list of Business
    IDs a Person belongs to — "Biz IDs" (parsed) plus "Primary Biz ID"
    if it isn't already present in that list (a Person's primary
    Business is always considered one of their linked Businesses, even
    on an older row where "Biz IDs" wasn't populated with it). Accepts
    either a canonical Person dict (as returned by find_person_by_id())
    or a person_id string.
    """
    person = person_or_id if isinstance(person_or_id, dict) else find_person_by_id(person_or_id)
    if not person:
        return []

    ids = list(person.get("biz_ids") or [])
    primary = (person.get("primary_biz_id") or "").strip()
    if primary and primary not in ids:
        ids.append(primary)

    seen = set()
    ordered = []
    for biz_id in ids:
        if biz_id and biz_id not in seen:
            seen.add(biz_id)
            ordered.append(biz_id)
    return ordered


def has_person_business_link(person_or_id, biz_id: str) -> bool:
    """Read-only. True iff biz_id is among the Person's linked
    Business IDs (see list_person_business_ids())."""
    if not biz_id:
        return False
    return biz_id in list_person_business_ids(person_or_id)
