"""
Object Manager — canonical owner of OBJECT_REGISTRY.

Phase 30C: Object Manager Foundation (ADR-014, Phase 30B).

Архитектурный принцип:
  business_builder.py (orchestration: Business/Client validation, Drive
  orchestration, Roadmap orchestration, partial-failure aggregation)
  → object_manager.py (this module: OBJECT_REGISTRY persistence,
    normalization, status validation, duplicate-safe create, narrow
    updates, Drive/Roadmap reference persistence)
  → business_core.sheets (Google Sheets I/O)

Зависимости только от business_core.sheets и стандартной библиотеки.
Не импортирует business_builder, telegram_handlers, roadmap_manager,
service_manager, person_manager, google_drive_adapter, Extension-модули
(ADR-014, Decision 16) — так же, как service_manager.py не импортирует
Roadmap/orchestration/Telegram.

Phase 30C — foundation only: this module is the canonical API, but
production callers are NOT yet migrated onto it (see Phase 30D).
business_core.business_builder's existing public Object functions
remain thin compatibility wrappers delegating here.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Canonical status vocabulary (ADR-014, Decision 6)
# ═══════════════════════════════════════════════════════════════

OBJECT_STATUSES = (
    "new",
    "active",
    "on_hold",
    "completed",
    "cancelled",
)

OBJECT_STATUS_DEFAULT = "new"

# Statuses for which a new Roadmap may be created (ADR-014, Decision 7).
# Not enforced here — Roadmap-creation validation lives in the
# orchestration layer (business_builder), per the same principle
# already applied to Service Domain. Exposed as a constant so that
# orchestration-layer code has a single source of truth instead of
# redeclaring its own copy.
ROADMAP_ALLOWED_OBJECT_STATUSES = ("new", "active", "on_hold")
ROADMAP_REJECTED_OBJECT_STATUSES = ("completed", "cancelled")


def validate_object_status(status: Optional[str]) -> str:
    """
    Строго провалидировать статус объекта для WRITE-пути (create/update).

    status is None или "" (не передан) → documented default "new".
    status передан непустым, но не входит в OBJECT_STATUSES →
    ValueError с понятным текстом (никогда не сворачивается в "new"
    молча).

    Returns:
        нормализованное (trim + lower) каноническое значение статуса.

    Raises:
        ValueError: если status передан, но не входит в vocabulary.
    """
    if status is None:
        return OBJECT_STATUS_DEFAULT
    s = status.strip().lower()
    if not s:
        return OBJECT_STATUS_DEFAULT
    if s not in OBJECT_STATUSES:
        raise ValueError(
            f"Неизвестный статус объекта: '{status}'. "
            f"Допустимые значения: {', '.join(OBJECT_STATUSES)}"
        )
    return s


def normalize_object_status_for_read(status: str) -> str:
    """
    Терпимая read-side нормализация — для отображения легаси/мусорных
    значений без падения (тот же принцип разделения read/write
    строгости, что и service_manager.normalize_service_status()).
    Неизвестное значение возвращается как есть (не подменяется), в
    отличие от validate_object_status(), которое их отклоняет на write.
    """
    return (status or "").strip().lower()


# ═══════════════════════════════════════════════════════════════
# Normalization (ADR-014, Decision 3 / Part 3)
# ═══════════════════════════════════════════════════════════════

def _collapse_whitespace(value: str) -> str:
    v = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", v.strip())


def normalize_object_address(value: str) -> str:
    """NFKC + trim + collapse whitespace + casefold, for duplicate-key
    comparison only — does not rewrite the stored display value."""
    return _collapse_whitespace(value).casefold()


def normalize_object_city(value: str) -> str:
    """NFKC + trim + collapse whitespace + casefold, for duplicate-key
    comparison only — does not rewrite the stored display value."""
    return _collapse_whitespace(value).casefold()


def normalize_cadastral_number(value: str) -> str:
    """
    NFKC + trim + casefold + strip obvious separators/whitespace, for
    duplicate-key comparison only — does not rewrite the stored display
    value. Separators stripped: spaces, hyphens, colons, slashes — the
    common cadastral-number punctuation variants; digits/letters kept.
    """
    v = unicodedata.normalize("NFKC", value or "").strip().casefold()
    v = re.sub(r"[\s\-:/]+", "", v)
    return v


# ═══════════════════════════════════════════════════════════════
# Canonical row shape (Part 4)
# ═══════════════════════════════════════════════════════════════

_WANTED_HEADERS = [
    "OBJ ID", "Client ID", "Biz ID", "City", "Address",
    "Cadastral Number", "Area m2", "Object Type", "Object Status",
    "Current Service ID", "Roadmap ID", "Drive Folder ID",
    "Google Drive", "Notes", "Created At", "Last Updated",
]


def _row_to_canonical(row_num: int, values: dict[str, str]) -> dict:
    return {
        "row_num":            row_num,
        "object_id":          values.get("OBJ ID", ""),
        "client_id":          values.get("Client ID", ""),
        "biz_id":             values.get("Biz ID", ""),
        "city":               values.get("City", ""),
        "address":            values.get("Address", ""),
        "cadastral_number":   values.get("Cadastral Number", ""),
        "area_m2":            values.get("Area m2", ""),
        "object_type":        values.get("Object Type", ""),
        "status":             normalize_object_status_for_read(values.get("Object Status", "")),
        "current_service_id": values.get("Current Service ID", ""),
        "roadmap_id":         values.get("Roadmap ID", ""),
        "drive_folder_id":    values.get("Drive Folder ID", ""),
        "drive_url":          values.get("Google Drive", ""),
        "notes":              values.get("Notes", ""),
        "created_at":         values.get("Created At", ""),
        "last_updated":       values.get("Last Updated", ""),
    }


def _load_objects() -> tuple[list[dict], list[str]]:
    """Загрузить все строки OBJECT_REGISTRY как canonical dicts.
    Returns (rows, headers)."""
    from business_core.sheets import get_business_sheet, read_row_by_headers
    sheet = get_business_sheet("object_registry")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return [], (all_values[0] if all_values else [])
    headers = all_values[0]
    rows = []
    for i, row in enumerate(all_values[1:], start=2):
        if not row or not row[0].strip():
            continue
        values = read_row_by_headers(headers, row, _WANTED_HEADERS)
        rows.append(_row_to_canonical(i, values))
    return rows, headers


# ═══════════════════════════════════════════════════════════════
# ID generation
# ═══════════════════════════════════════════════════════════════

def generate_object_id() -> str:
    """Сгенерировать следующий OBJ ID из OBJECT_REGISTRY. Формат:
    OBJ-001, OBJ-002, ... Безопасно работает на пустом листе."""
    try:
        from business_core.sheets import generate_next_id
        return generate_next_id("object_registry")
    except Exception as exc:
        log.warning(f"generate_object_id error: {exc}")
        return "OBJ-001"


# ═══════════════════════════════════════════════════════════════
# Read APIs (Part 5)
# ═══════════════════════════════════════════════════════════════

def find_object_by_id(object_id: str) -> Optional[dict]:
    """Найти объект по OBJ ID. Returns canonical dict or None."""
    if not object_id:
        return None
    try:
        rows, _ = _load_objects()
        for r in rows:
            if r["object_id"] == object_id:
                return r
    except Exception as exc:
        log.warning(f"find_object_by_id({object_id}) error: {exc}")
    return None


def find_objects_by_client(client_id: str, biz_id: Optional[str] = None) -> list[dict]:
    """Найти объекты клиента, опционально фильтруя по бизнесу."""
    if not client_id:
        return []
    try:
        rows, _ = _load_objects()
        results = [r for r in rows if r["client_id"] == client_id]
        if biz_id:
            results = [r for r in results if r["biz_id"] == biz_id]
        return results
    except Exception as exc:
        log.warning(f"find_objects_by_client({client_id}) error: {exc}")
        return []


def find_objects_by_biz(biz_id: str) -> list[dict]:
    """Найти все объекты бизнеса по Biz ID."""
    if not biz_id:
        return []
    try:
        rows, _ = _load_objects()
        return [r for r in rows if r["biz_id"] == biz_id]
    except Exception as exc:
        log.warning(f"find_objects_by_biz({biz_id}) error: {exc}")
        return []


def list_objects(
    biz_id:    Optional[str] = None,
    client_id: Optional[str] = None,
    status:    Optional[str] = None,
) -> list[dict]:
    """Список объектов с опциональными фильтрами. Пустые/None фильтры
    не сужают выборку. status сравнивается канонически (trim+lower)."""
    try:
        rows, _ = _load_objects()
        if biz_id:
            rows = [r for r in rows if r["biz_id"] == biz_id]
        if client_id:
            rows = [r for r in rows if r["client_id"] == client_id]
        if status:
            want = status.strip().lower()
            rows = [r for r in rows if r["status"] == want]
        return rows
    except Exception as exc:
        log.warning(f"list_objects error: {exc}")
        return []


# ═══════════════════════════════════════════════════════════════
# Duplicate-key resolution (Part 6)
# ═══════════════════════════════════════════════════════════════

def find_duplicate_objects(
    biz_id:           str,
    client_id:        str,
    city:             str,
    address:          str,
    cadastral_number: str = "",
) -> list[dict]:
    """
    Найти существующие объекты, совпадающие с запросом по canonical
    duplicate key (ADR-014, Decision 3):

      Tier 1 (cadastral_number непустой после нормализации):
        (Business ID, normalized Cadastral Number)
      Tier 2 (иначе):
        (Business ID, Client ID, normalized City, normalized Address)

    Tier 1 имеет приоритет и полностью игнорирует Client/Address при
    совпадении — один и тот же физический объект с тем же кадастровым
    номером в том же бизнесе считается дублем независимо от того, кто
    указан клиентом или как записан адрес.
    """
    rows, _ = _load_objects()
    norm_cadastral = normalize_cadastral_number(cadastral_number)

    if norm_cadastral:
        return [
            r for r in rows
            if r["biz_id"] == biz_id
            and normalize_cadastral_number(r["cadastral_number"]) == norm_cadastral
        ]

    norm_city = normalize_object_city(city)
    norm_address = normalize_object_address(address)
    return [
        r for r in rows
        if r["biz_id"] == biz_id
        and r["client_id"] == client_id
        and normalize_object_city(r["city"]) == norm_city
        and normalize_object_address(r["address"]) == norm_address
    ]


# ═══════════════════════════════════════════════════════════════
# Duplicate-safe create (Part 7/8)
# ═══════════════════════════════════════════════════════════════

def _object_result(
    ok:                bool,
    object_id:         Optional[str] = None,
    error:             Optional[str] = None,
    object_created:    bool = False,
    object_reused:     bool = False,
    warnings:          Optional[list[str]] = None,
    matching_object_ids: Optional[list[str]] = None,
) -> dict:
    """Единая return-shape helper для create_object_record."""
    return {
        "ok":                  ok,
        "object_id":           object_id,
        "error":               error,
        "object_created":      object_created,
        "object_reused":       object_reused,
        "warnings":            list(warnings or []),
        "matching_object_ids": list(matching_object_ids or []),
    }


# Поля запроса create_object_record, для которых проверяется mismatch
# с уже существующей (reused) записью. (param_name, canonical row key)
_MISMATCH_CHECK_FIELDS = (
    ("client_id",         "client_id"),
    ("city",              "city"),
    ("address",           "address"),
    ("cadastral_number",  "cadastral_number"),
    ("area_m2",           "area_m2"),
    ("object_type",       "object_type"),
    ("notes",             "notes"),
)


def _diff_mismatch_fields(existing: dict, requested: dict, resolved_status: str, status_explicit: bool) -> list[str]:
    """Сравнить только явно переданные (непустые) поля запроса с уже
    сохранённой (reused) записью. Whitespace/case-only различие в
    address/city/cadastral_number не считается mismatch (сравнение
    идёт через те же normalize_* функции, что и duplicate-key)."""
    warnings: list[str] = []
    norm_funcs = {
        "city": normalize_object_city,
        "address": normalize_object_address,
        "cadastral_number": normalize_cadastral_number,
    }
    for param_name, row_key in _MISMATCH_CHECK_FIELDS:
        requested_value = str(requested.get(param_name, "") or "").strip()
        if not requested_value:
            continue
        existing_value = str(existing.get(row_key, "") or "").strip()
        norm = norm_funcs.get(param_name)
        if norm is not None:
            if norm(requested_value) == norm(existing_value):
                continue
        elif requested_value == existing_value:
            continue
        warnings.append(
            f"{param_name}: запрошено '{requested_value}', в существующей записи '{existing_value}'"
        )
    if status_explicit:
        existing_status = normalize_object_status_for_read(existing.get("status", ""))
        if resolved_status != existing_status:
            warnings.append(
                f"status: запрошено '{resolved_status}', в существующей записи '{existing_status}'"
            )
    return warnings


def create_object_record(
    client_id:          str,
    biz_id:              str,
    city:                str,
    address:             str,
    cadastral_number:    str = "",
    area_m2:             str = "",
    object_type:         str = "",
    status:              Optional[str] = None,
    current_service_id:  str = "",
    notes:               str = "",
    drive_folder_id:     str = "",
    google_drive_url:    str = "",
) -> dict:
    """
    Создать (или конвергентно переиспользовать) запись в OBJECT_REGISTRY.

    Phase 30C, ADR-014 Decision 3/4: duplicate-safe/idempotent create.
    Duplicate key — see find_duplicate_objects(). Повторный вызов с тем
    же ключом НЕ создаёт вторую строку: возвращает существующий Object
    (object_reused=True), существующие поля не перезаписываются молча —
    расхождения возвращаются как warnings.

    status: None/не передан → documented default "new". Передан, но не
    входит в OBJECT_STATUSES → ошибка в error, ничего не записывается.

    Args:
        client_id: PRS-ID клиента (обязательный)
        biz_id:    BIZ-ID бизнеса (обязательный)
        city:      город (обязательный)
        address:   адрес (обязательный)

    Returns: см. _object_result().
    """
    if not client_id or not biz_id or not (city or "").strip() or not (address or "").strip():
        return _object_result(False, error="Обязательные поля: client_id, biz_id, city, address")

    try:
        resolved_status = validate_object_status(status)
    except ValueError as exc:
        return _object_result(False, error=str(exc))

    try:
        existing_matches = find_duplicate_objects(
            biz_id=biz_id, client_id=client_id, city=city, address=address,
            cadastral_number=cadastral_number,
        )
    except Exception as exc:
        return _object_result(False, error=str(exc))

    if len(existing_matches) > 1:
        ids = [m["object_id"] for m in existing_matches]
        return _object_result(
            False,
            error=(
                f"object duplicate integrity error: найдено {len(existing_matches)} "
                f"существующих Object по duplicate key (biz_id={biz_id!r}): {ids}. "
                f"Новая запись не создана."
            ),
            matching_object_ids=ids,
        )

    if len(existing_matches) == 1:
        existing = existing_matches[0]
        requested = {
            "client_id": client_id, "city": city, "address": address,
            "cadastral_number": cadastral_number, "area_m2": area_m2,
            "object_type": object_type, "notes": notes,
        }
        warnings = _diff_mismatch_fields(existing, requested, resolved_status, status is not None)
        return _object_result(
            True, object_id=existing["object_id"],
            object_created=False, object_reused=True, warnings=warnings,
        )

    try:
        from business_core.sheets import append_business_row, get_business_sheet, row_from_header_map

        now = datetime.now().strftime("%Y-%m-%d")
        object_id = generate_object_id()

        sheet = get_business_sheet("object_registry")
        headers = sheet.row_values(1)

        required_headers = list(_WANTED_HEADERS)
        missing_headers = [h for h in required_headers if h not in headers]
        if missing_headers:
            return _object_result(
                False,
                error=(
                    f"OBJECT_REGISTRY: отсутствуют обязательные колонки {missing_headers}. "
                    f"Запись объекта остановлена, ничего не записано."
                ),
            )

        row = row_from_header_map(headers, {
            "OBJ ID":             object_id,
            "Client ID":          client_id,
            "Biz ID":             biz_id,
            "City":               city,
            "Address":            address,
            "Cadastral Number":   cadastral_number,
            "Area m2":            area_m2,
            "Object Type":        object_type,
            "Object Status":      resolved_status,
            "Current Service ID": current_service_id,
            "Roadmap ID":         "",
            "Drive Folder ID":    drive_folder_id,
            "Google Drive":       google_drive_url,
            "Notes":              notes,
            "Created At":         now,
            "Last Updated":       now,
        })
        append_business_row("object_registry", row)
        log.info(f"create_object_record: {object_id} / {client_id} / {address}")
        return _object_result(True, object_id=object_id, object_created=True, object_reused=False)

    except Exception as exc:
        log.error(f"create_object_record error: {exc}")
        return _object_result(False, error=str(exc))


# ═══════════════════════════════════════════════════════════════
# Narrow update API (Part 9)
# ═══════════════════════════════════════════════════════════════

_UPDATABLE_FIELDS = {
    "address":     "Address",
    "object_type": "Object Type",
    "notes":       "Notes",
}


def update_object_fields(object_id: str, fields: dict) -> dict:
    """
    Allowlist-based narrow update of an existing Object row.

    Разрешённые ключи fields: "address", "object_type", "notes"
    (ADR-014, Decision 10/Part 9). Любой другой ключ — вся операция
    отклоняется целиком (all-or-nothing), ничего не пишется. Object
    ID/Client ID/Biz ID/Drive reference/Roadmap reference/Created At
    никогда не изменяются этим API. "Last Updated" обновляется
    автоматически при любом успешном обновлении.

    Returns:
        {"ok": bool, "object_id": str, "updated_fields": list[str], "error": str | None}
    """
    if not object_id:
        return {"ok": False, "object_id": object_id, "updated_fields": [], "error": "object_id обязателен"}
    if not fields:
        return {"ok": False, "object_id": object_id, "updated_fields": [], "error": "fields пуст"}

    unknown = [k for k in fields if k not in _UPDATABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "object_id": object_id, "updated_fields": [],
            "error": f"Недопустимые поля для обновления: {unknown}. "
                     f"Разрешены: {sorted(_UPDATABLE_FIELDS)}",
        }

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "object_id": object_id, "updated_fields": [], "error": f"Объект {object_id} не найден"}

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        row_num = None
        for i, row in enumerate(all_values[1:], start=2):
            if row and row[0].strip() == object_id:
                row_num = i
                break

        if row_num is None:
            return {"ok": False, "object_id": object_id, "updated_fields": [], "error": f"Объект {object_id} не найден"}

        missing_cols = [
            header_name for key, header_name in _UPDATABLE_FIELDS.items()
            if key in fields and _col(header_name) is None
        ]
        if missing_cols:
            return {
                "ok": False, "object_id": object_id, "updated_fields": [],
                "error": f"OBJECT_REGISTRY: отсутствуют колонки {missing_cols}",
            }

        updated_fields = []
        for key, value in fields.items():
            header_name = _UPDATABLE_FIELDS[key]
            col = _col(header_name)
            sheet.update_cell(row_num, col + 1, value)
            updated_fields.append(key)

        last_updated_col = _col("Last Updated")
        if last_updated_col is not None:
            sheet.update_cell(row_num, last_updated_col + 1, datetime.now().strftime("%Y-%m-%d"))

        log.info(f"update_object_fields: {object_id} → {updated_fields}")
        return {"ok": True, "object_id": object_id, "updated_fields": updated_fields, "error": None}

    except Exception as exc:
        log.warning(f"update_object_fields({object_id}) error: {exc}")
        return {"ok": False, "object_id": object_id, "updated_fields": [], "error": str(exc)}


# ═══════════════════════════════════════════════════════════════
# Narrow reference APIs (Part 10)
# ═══════════════════════════════════════════════════════════════

def update_object_drive_info(
    object_id:        str,
    folder_id:        str = "",
    folder_url:       str = "",
    only_if_empty:    bool = True,
) -> dict:
    """
    Записать Drive Folder ID/URL для объекта. only_if_empty=True
    (по умолчанию, сохраняет текущее production-поведение) — не
    перезаписывает уже заполненное значение, что делает повторные
    вызовы с тем же значением идемпотентными и безопасными для retry.

    Returns:
        {"ok": bool, "object_id": str, "updated": bool, "error": str | None}
    """
    if not object_id:
        return {"ok": False, "object_id": object_id, "updated": False, "error": "object_id обязателен"}

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "object_id": object_id, "updated": False, "error": f"Объект {object_id} не найден"}

        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        drive_id_col = _col("Drive Folder ID")
        drive_url_col = _col("Google Drive")
        updated = False

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0].strip() != object_id:
                continue

            if drive_id_col is not None and folder_id:
                cur = row[drive_id_col].strip() if drive_id_col < len(row) else ""
                if not cur or not only_if_empty:
                    sheet.update_cell(i, drive_id_col + 1, folder_id)
                    updated = True

            if drive_url_col is not None and folder_url:
                cur = row[drive_url_col].strip() if drive_url_col < len(row) else ""
                if not cur or not only_if_empty:
                    sheet.update_cell(i, drive_url_col + 1, folder_url)
                    updated = True

            if updated:
                log.info(f"update_object_drive_info: {object_id} → Drive дозаполнен")
            return {"ok": True, "object_id": object_id, "updated": updated, "error": None}

        return {"ok": False, "object_id": object_id, "updated": False, "error": f"Объект {object_id} не найден"}

    except Exception as exc:
        log.warning(f"update_object_drive_info({object_id}) error: {exc}")
        return {"ok": False, "object_id": object_id, "updated": False, "error": str(exc)}


def update_object_roadmap_id(
    object_id:      str,
    roadmap_id:     str,
    only_if_empty:  bool = True,
) -> dict:
    """
    Записать Roadmap ID для объекта. only_if_empty=True (по умолчанию,
    сохраняет текущее production-поведение — Object.Roadmap ID остаётся
    a compatibility/reference field, не блокирует создание второй
    Roadmap для другой Service, см. ADR-014 Decision 8) — не
    перезаписывает уже заполненное значение.

    Returns:
        {"ok": bool, "object_id": str, "updated": bool, "error": str | None}
    """
    if not object_id or not roadmap_id:
        return {"ok": False, "object_id": object_id, "updated": False, "error": "object_id и roadmap_id обязательны"}

    try:
        from business_core.sheets import get_business_sheet
        sheet = get_business_sheet("object_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": False, "object_id": object_id, "updated": False, "error": f"Объект {object_id} не найден"}
        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        rm_col = _col("Roadmap ID")
        if rm_col is None:
            return {"ok": False, "object_id": object_id, "updated": False, "error": "колонка Roadmap ID не найдена"}

        for i, row in enumerate(all_values[1:], start=2):
            if not row or not row[0]:
                continue
            if row[0].strip() != object_id:
                continue
            current = row[rm_col].strip() if rm_col < len(row) else ""
            if not current or not only_if_empty:
                sheet.update_cell(i, rm_col + 1, roadmap_id)
                log.info(f"update_object_roadmap_id: {object_id} → {roadmap_id}")
                return {"ok": True, "object_id": object_id, "updated": True, "error": None}
            # Уже заполнен — не перезаписываем.
            return {"ok": True, "object_id": object_id, "updated": False, "error": None}

        return {"ok": False, "object_id": object_id, "updated": False, "error": f"Объект {object_id} не найден"}

    except Exception as exc:
        log.warning(f"update_object_roadmap_id({object_id}) error: {exc}")
        return {"ok": False, "object_id": object_id, "updated": False, "error": str(exc)}
