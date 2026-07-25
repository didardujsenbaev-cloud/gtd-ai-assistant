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


# ─────────────────────────────────────────────────────────────
# Normalization helpers (relocated from business_builder.py, hardened
# to guard blank/None inputs — a minor, safe improvement made during
# the move, matching every other manager's normalization helper).
# ─────────────────────────────────────────────────────────────

def normalize_person_name(name: str) -> str:
    """Trim + collapse internal whitespace + lowercase. Same recipe
    used throughout this codebase for name-based duplicate detection."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def normalize_phone(phone: str) -> str:
    """Strip everything except digits — comparable regardless of
    formatting ("+7 (777) 123-45-67" and "8 777 123 45 67" normalize
    to the same digit string)."""
    return re.sub(r"\D", "", (phone or "").strip())


def _normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


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
    Read-only. Faithful port of business_builder.py's original
    find_existing_person() — kept as a SEPARATE function from
    find_person()/find_duplicate_person() (the new Phase 23D-1 public
    API) because its callers (business_core.telegram_handlers.
    newclient_confirm(), via business_builder.py's delegator) depend on
    its EXACT existing return shape and semantics, which differ from
    the new API in two ways this phase must not change:

      1. It does NOT exclude archived rows (find_duplicate_person()
         does — they answer different questions: "does this contact
         already exist at all" vs. "should a NEW create be blocked").
      2. It returns "same_biz": False (rather than excluding the row)
         when a business_id is given but doesn't match — used by
         newclient_confirm() to distinguish "this is the same client,
         different business" from "brand new contact", a distinction
         find_duplicate_person() has no need for.

    Search priority: normalized phone (+ WhatsApp) is a strong
    identifier; normalized full name is a weaker one. If biz_id is not
    given, matches on name/phone alone (a "weak search").

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

    norm_name = normalize_person_name(name) if name else ""
    norm_phone = normalize_phone(phone) if phone else ""

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("people_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return None

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h, fallback=""):
            c = _col(h)
            return (row[c].strip() if c is not None and c < len(row) else "") or fallback

        name_col = _col("ФИО") if _col("ФИО") is not None else 1
        phone_col = _col("Телефон")
        wa_col = _col("WhatsApp")
        biz_ids_col = _col("Biz IDs")

        def _person_biz_ids(row) -> list[str]:
            if biz_ids_col is not None and biz_ids_col < len(row) and row[biz_ids_col].strip():
                return _normalize_biz_ids(row[biz_ids_col])
            return []

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue

            row_name = normalize_person_name(row[name_col] if name_col < len(row) else "")
            row_phone = normalize_phone(row[phone_col] if phone_col is not None and phone_col < len(row) else "")
            row_wa = normalize_phone(row[wa_col] if wa_col is not None and wa_col < len(row) else "")

            phone_match = bool(
                norm_phone and (
                    (row_phone and row_phone == norm_phone) or
                    (row_wa and row_wa == norm_phone)
                )
            )
            name_match = bool(norm_name and row_name == norm_name)

            if not phone_match and not name_match:
                continue

            person_biz_ids = _person_biz_ids(row)

            if biz_id:
                old_biz = _get(row, "Бизнесы")
                biz_match = (
                    biz_id in person_biz_ids or
                    (not person_biz_ids and old_biz)
                )
                same_biz = biz_id in person_biz_ids
            else:
                biz_match = True
                same_biz = True

            if not biz_match and not phone_match and not name_match:
                continue

            return {
                "row_num": i,
                "prs_id": row[0],
                "full_name": row[name_col] if name_col < len(row) else "",
                "biz_ids": person_biz_ids,
                "primary_biz_id": _get(row, "Primary Biz ID"),
                "drive_url": _get(row, "Google Drive"),
                "drive_folder_id": _get(row, "Drive Folder ID"),
                "phone_raw": row[phone_col] if phone_col is not None and phone_col < len(row) else "",
                "same_biz": same_biz,
            }

    except Exception as exc:
        log.warning(f"find_existing_person error: {exc}")

    return None


def find_duplicate_person(
    full_name: str = "", phone: str = "", email: str = "", business_id: str = "",
) -> Optional[dict]:
    """
    Read-only. The pre-create duplicate check (Phase 23D-1 §5):
    identity is based on the real person — normalized phone, normalized
    full name, and email (when available) — NEVER Person Type (an
    attribute of the relationship, not the person's identity; see
    ARCHITECTURE.md / Person Layer). Business ID narrows the match when
    supplied (checked against the multi-valued Biz IDs column, not an
    exact single-value match, since one Person can belong to several
    businesses).

    Archived People NEVER block a new create — only "active" rows are
    considered, matching the same soft-delete-excluded-from-duplicate-
    check convention already established for Department/Role
    (Phase 23C).
    """
    if not full_name and not phone and not email:
        return None

    norm_name = normalize_person_name(full_name) if full_name else ""
    norm_phone = normalize_phone(phone) if phone else ""
    norm_email = _normalize_email(email) if email else ""

    for person in _list_people_raw():
        if person["status"] != "active":
            continue
        if business_id and business_id not in person["biz_ids"]:
            continue

        phone_match = bool(norm_phone and normalize_phone(person["phone"]) == norm_phone)
        name_match = bool(norm_name and normalize_person_name(person["full_name"]) == norm_name)
        email_match = bool(norm_email and _normalize_email(person["email"]) == norm_email)

        if phone_match or name_match or email_match:
            return person

    return None


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
    "Статус отношений", "Теплота", "Комментарий", "Бизнесы", "Biz IDs",
    "Company ID", "Citizenship", "Passport / ID", "Primary Biz ID",
    "Дата последнего контакта",
)


def update_person(person_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Person. Точечная запись только
    переданных колонок — по имени заголовка, только в найденную строку.
    "ID" и "Дата первого контакта" не редактируемы через эту функцию
    (ID — ключ записи; первый контакт устанавливается один раз при
    создании).

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

    if "Статус отношений" in updates and updates["Статус отношений"] not in PERSON_STATUS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": (
                f"Недопустимый статус '{updates['Статус отношений']}'. "
                f"Допустимые значения: {', '.join(PERSON_STATUS)}"
            ),
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

    result = update_person(person_id, {"Статус отношений": "archived"})
    return {"ok": result["ok"], "changed": result["changed"], "error": result["error"]}


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
