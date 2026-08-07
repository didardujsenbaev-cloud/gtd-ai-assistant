"""
Task Manager — Business Task + Task Assignment persistence (Phase 36C,
ADR-019).

Sole transactional owner of TASK_REGISTRY and TASK_ASSIGNMENTS. Mirrors
the Organization Layer's read/write pattern (organization_manager.py)
exactly — targeted sheet.find() + read_row_by_headers(), never a
positional-index assumption (see RM-027 precedent).

This module is deliberately low-level only: no Business/Client/Object/
Service/Roadmap/Stage cross-entity validation, no Organization
eligibility, no Roadmap/Stage lifecycle policy, no idempotency policy,
no Russian user-facing text. All of that lives solely in
business_builder.py's Task orchestration functions (create_business_task/
update_task_admin_fields/transition_task_status/assign_task/
unassign_task) — this module is the primitive those functions call
after their own validation passes, exactly like organization_manager.
assign_person_to_role() is to business_builder.
assign_person_to_role_canonical() (ADR-018 §15).

Dependencies: only business_core.sheets. Never business_builder or
telegram_handlers. GTD Core is never imported.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Canonical enums (ADR-019 §14/§17)
# ─────────────────────────────────────────────────────────────

TASK_STATUS = ("new", "ready", "in_progress", "waiting", "blocked", "done", "cancelled", "skipped")
TASK_ASSIGNMENT_STATUS = ("active", "ended")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_date(value: str) -> bool:
    return bool(_DATE_RE.match(value or ""))


# ─────────────────────────────────────────────────────────────
# Task: internal read helper
# ─────────────────────────────────────────────────────────────

_TASK_FIELDS = [
    "Task ID", "Business ID", "Title", "Description", "Status",
    "Priority", "Due Date", "Source", "Idempotency Key",
    "Client ID", "Object ID", "Service ID", "Roadmap ID", "Stage ID",
    "Responsible Role ID", "Assignee Person ID",
    "Created At", "Updated At", "Started At", "Completed At", "Cancelled At",
    "Created By", "GTD Action ID",
]


def _find_task_row(task_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not task_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("task_registry")
        cell = sheet.find(task_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        v = read_row_by_headers(headers, row, _TASK_FIELDS)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_task_row({task_id}) error: {exc}")
        return None


def _task_row_to_dict(row_num: int, v: dict) -> dict:
    return {
        "row_num":              row_num,
        "task_id":              v["Task ID"],
        "business_id":          v["Business ID"],
        "title":                v["Title"],
        "description":          v["Description"],
        "status":               v["Status"],
        "priority":             v["Priority"],
        "due_date":             v["Due Date"],
        "source":               v["Source"],
        "idempotency_key":      v["Idempotency Key"],
        "client_id":            v["Client ID"],
        "object_id":            v["Object ID"],
        "service_id":           v["Service ID"],
        "roadmap_id":           v["Roadmap ID"],
        "stage_id":             v["Stage ID"],
        "responsible_role_id":  v["Responsible Role ID"],
        "assignee_person_id":   v["Assignee Person ID"],
        "created_at":           v["Created At"],
        "updated_at":           v["Updated At"],
        "started_at":           v["Started At"],
        "completed_at":         v["Completed At"],
        "cancelled_at":         v["Cancelled At"],
        "created_by":           v["Created By"],
        "gtd_action_id":        v["GTD Action ID"],
    }


def list_tasks(
    business_id: str = "",
    status: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    role_id: str = "",
    person_id: str = "",
    *,
    raise_on_error: bool = False,
) -> list[dict]:
    """
    Read-only. Все Task, опционально отфильтрованные по любой комбинации
    Business ID/Status/Roadmap ID/Stage ID/Responsible Role ID/Assignee
    Person ID (cache-поле, не история). Exact-match filters only — нет
    fuzzy/partial matching. Пустые фильтры не исключают ни одну строку.

    Phase 36D (ADR-019 §6): единственный read API, который /bctasks
    вызывает — сам не содержит cross-entity policy, только фильтрацию
    уже персистентных значений.

    raise_on_error (keyword-only, default False): when False, an
    internal storage exception is logged and this function returns
    [] — the original, unchanged behavior every existing caller
    already relies on. When True, the exception propagates unchanged
    instead of being converted to [] — no retry, no partial result,
    no logging here (a caller that opts into raise_on_error is
    expected to log its own fixed-literal message and must not have
    this function's dynamic exception text land in a log first).
    Filtering, scan order, and result shape are identical in both
    modes — only error propagation differs.
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("task_registry")
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
            if business_id and _g(row, "Business ID") != business_id:
                continue
            if status and _g(row, "Status") != status:
                continue
            if roadmap_id and _g(row, "Roadmap ID") != roadmap_id:
                continue
            if stage_id and _g(row, "Stage ID") != stage_id:
                continue
            if role_id and _g(row, "Responsible Role ID") != role_id:
                continue
            if person_id and _g(row, "Assignee Person ID") != person_id:
                continue
            results.append(_task_row_to_dict(0, {f: _g(row, f) for f in _TASK_FIELDS}))
        return results
    except Exception as exc:
        if raise_on_error:
            raise
        log.warning(f"list_tasks() error: {exc}")
        return []


def get_current_task_assignment(task_id: str) -> Optional[dict]:
    """
    Read-only. Единственная current active Task Assignment для Task,
    если ровно одна существует — None если ноль или больше одной
    (caller'у нужно отдельно проверить len(list_task_assignments_for_task(...))
    для интеграционного конфликта, эта функция намеренно не выбирает
    произвольную первую строку при множественном конфликте).
    """
    active = list_task_assignments_for_task(task_id, status="active")
    if len(active) != 1:
        return None
    return active[0]


def find_task_by_id(task_id: str) -> Optional[dict]:
    """Найти Task по ID. Read-only."""
    found = _find_task_row(task_id)
    if not found:
        return None
    row_num, v = found
    return _task_row_to_dict(row_num, v)


def find_tasks_by_idempotency_key(business_id: str, idempotency_key: str) -> dict:
    """
    Read-only. Returns a typed result contract that distinguishes
    "checked, zero matches" from "could not check" (Phase 18A.9-A1) —
    a storage read failure must never be silently treated as zero
    matches, since that previously let create_business_task() proceed
    to create a Task while the idempotency state was genuinely unknown
    (Phase 18A.9-A0 audit, §3/§12).

    idempotency_key is normalized (stripped) once here before both the
    comparison and the empty-input short-circuit below; each stored
    cell value is already stripped by the existing `_g` accessor. Case
    is preserved, not folded.

    Returns:
        {"ok": bool, "code": str, "matches": list[dict], "error": None}

        ok=True  — read succeeded (matches may be an empty list).
        ok=False, code="IDEMPOTENCY_CHECK_UNAVAILABLE", matches=[]
            — the read itself failed; the caller must not treat this
              as zero matches.

    Never called by Telegram/other callers directly — exclusively
    business_builder.create_business_task()'s zero/one/multiple
    idempotency policy (ADR-019 §10/§23).
    """
    normalized_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not business_id or not normalized_key:
        return {"ok": True, "code": "", "matches": [], "error": None}
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("task_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": True, "code": "", "matches": [], "error": None}

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _g(row, h):
            i = idx.get(h)
            return row[i].strip() if (i is not None and i < len(row)) else ""

        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            if _g(row, "Business ID") != business_id:
                continue
            if _g(row, "Idempotency Key") != normalized_key:
                continue
            results.append(_task_row_to_dict(0, {f: _g(row, f) for f in _TASK_FIELDS}))
        return {"ok": True, "code": "", "matches": results, "error": None}
    except Exception:
        log.warning("find_tasks_by_idempotency_key: read failure")
        return {"ok": False, "code": "IDEMPOTENCY_CHECK_UNAVAILABLE", "matches": [], "error": None}


def _verify_created_task_row(task_id: str, business_id: str, idempotency_key: str) -> dict:
    """
    Phase 18A.9-A1. Read-only post-append verification for
    create_task() — never called before an append attempt, never used
    for any policy decision other than confirming what is actually
    persisted.

    Returns every task_registry row whose Task ID equals `task_id`,
    UNIONED with (when `idempotency_key` is non-blank) every row whose
    (Business ID, Idempotency Key) equals the intended compound key.
    The union covers both "did my specific row land" and "did a
    concurrent writer produce a duplicate under the same idempotency
    key" in a single read.

    Returns:
        {"ok": bool, "matches": list[dict]}

        ok=False means the verification read itself failed — the
        caller must treat this as an unknown outcome, never as zero
        matches.
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("task_registry")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return {"ok": True, "matches": []}

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _g(row, h):
            i = idx.get(h)
            return row[i].strip() if (i is not None and i < len(row)) else ""

        results = []
        for row in all_values[1:]:
            if not row or not row[0].strip():
                continue
            row_task_id = _g(row, "Task ID")
            row_business_id = _g(row, "Business ID")
            row_key = _g(row, "Idempotency Key")
            matches_task_id = row_task_id == task_id
            matches_compound = bool(idempotency_key) and row_business_id == business_id and row_key == idempotency_key
            if matches_task_id or matches_compound:
                results.append(_task_row_to_dict(0, {f: _g(row, f) for f in _TASK_FIELDS}))
        return {"ok": True, "matches": results}
    except Exception:
        log.warning("create_task: post-append verification read failure")
        return {"ok": False, "matches": []}


def create_task(
    business_id: str,
    title: str,
    *,
    description: str = "",
    status: str = "new",
    priority: str = "",
    due_date: str = "",
    source: str = "",
    idempotency_key: str = "",
    client_id: str = "",
    object_id: str = "",
    service_id: str = "",
    roadmap_id: str = "",
    stage_id: str = "",
    responsible_role_id: str = "",
    assignee_person_id: str = "",
    created_by: str = "",
    gtd_action_id: str = "",
) -> dict:
    """
    Создать Business Task в TASK_REGISTRY. Низкоуровневая запись — не
    проверяет Business/Client/Object/Service/Roadmap/Stage существование
    или согласованность, не проверяет lifecycle eligibility, не
    проверяет идемпотентность (that policy is exclusively
    business_builder.create_business_task(), ADR-019 §7). Calling this
    function directly deliberately bypasses that policy — it is the
    primitive the orchestrator calls only after its own validation.

    Phase 18A.9-A1: Task ID allocation and the registry append use
    Task-registry-only primitives (generate_next_task_id() /
    append_task_registry_row()) that fail closed instead of the
    generic generate_next_id()/append_business_row() fallback-prone /
    row-overwrite-prone behavior used by other registries (Phase
    18A.9-A0 audit, §5/§6). After the append attempt — whether or not
    it raised — a fresh read (_verify_created_task_row) confirms what
    is actually persisted before this function claims success,
    distinguishing:
      - unknown outcome (TASK_WRITE_OUTCOME_UNKNOWN): verification
        read failed, OR verification found zero matching rows after
        any append attempt (whether the append reported success or
        raised — an append exception does not prove non-persistence);
      - confirmed success, exactly one row (TASK_CREATED);
      - confirmed duplicate, more than one row (TASK_DUPLICATE_DETECTED).
    This function never retries a write and never claims distributed
    atomicity — verification only proves what this one process can
    observe in this one read. Phase 18A.9-A1-F1: there is no
    post-append path that returns TASK_STORAGE_ERROR.

    Returns:
        {"ok": bool, "task_id": str, "code": str, "error": str | None}
        (TASK_DUPLICATE_DETECTED additionally carries
        "conflicting_task_ids": tuple)
    """
    if not business_id:
        return {"ok": False, "task_id": "", "code": "", "error": "business_id обязателен"}
    if not title:
        return {"ok": False, "task_id": "", "code": "", "error": "title обязателен"}
    if status not in TASK_STATUS:
        return {
            "ok": False, "task_id": "", "code": "INVALID_TASK_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TASK_STATUS)}",
        }

    normalized_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""

    from business_core.sheets import generate_next_task_id, append_task_registry_row, row_from_header_map, get_business_sheet

    task_id = generate_next_task_id()
    if not task_id:
        log.error("create_task: Task ID allocation failure")
        return {"ok": False, "task_id": "", "code": "TASK_ID_ALLOCATION_ERROR", "error": None}

    try:
        sheet = get_business_sheet("task_registry")
        headers = sheet.row_values(1)
    except Exception:
        log.error("create_task: header read failure")
        return {"ok": False, "task_id": "", "code": "TASK_ID_ALLOCATION_ERROR", "error": None}

    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d")
    values = {
        "Task ID": task_id, "Business ID": business_id, "Title": title,
        "Description": description, "Status": status, "Priority": priority,
        "Due Date": due_date, "Source": source, "Idempotency Key": normalized_key,
        "Client ID": client_id, "Object ID": object_id, "Service ID": service_id,
        "Roadmap ID": roadmap_id, "Stage ID": stage_id,
        "Responsible Role ID": responsible_role_id, "Assignee Person ID": assignee_person_id,
        "Created At": ts, "Updated At": ts, "Started At": "", "Completed At": "", "Cancelled At": "",
        "Created By": created_by, "GTD Action ID": gtd_action_id,
    }
    row = row_from_header_map(headers, values)

    append_raised = False
    try:
        append_task_registry_row(row)
    except Exception:
        append_raised = True
        log.error("create_task: append attempt raised")

    verification = _verify_created_task_row(task_id, business_id, normalized_key)
    if not verification["ok"]:
        log.warning("create_task: outcome unknown, verification read failed")
        return {"ok": False, "task_id": task_id, "code": "TASK_WRITE_OUTCOME_UNKNOWN", "error": None}

    matches = verification["matches"]
    if len(matches) == 0:
        # Phase 18A.9-A1-F1: zero matching rows after any append attempt
        # is always ambiguous — an append exception does not prove the
        # server rejected the write. Never classify as TASK_STORAGE_ERROR
        # / retry-safe confirmed failure.
        if append_raised:
            log.warning("create_task: outcome unknown after append exception, no row found")
        else:
            log.warning("create_task: outcome unknown, append reported success but no row found")
        return {"ok": False, "task_id": task_id, "code": "TASK_WRITE_OUTCOME_UNKNOWN", "error": None}

    if len(matches) > 1:
        conflicting_ids = tuple(t.get("task_id", "") for t in matches)
        log.warning("create_task: duplicate rows detected after append")
        return {
            "ok": False, "task_id": task_id, "code": "TASK_DUPLICATE_DETECTED", "error": None,
            "conflicting_task_ids": conflicting_ids,
        }

    log.info(f"create_task: {task_id} / {title}")
    return {"ok": True, "task_id": task_id, "code": "TASK_CREATED", "error": None}


_TASK_ADMIN_EDITABLE_FIELDS = (
    "Title", "Description", "Priority", "Due Date", "Created By", "GTD Action ID",
)

# Phase 36C (ADR-019 §11/§24): Task ID/Business ID/Created At are
# immutable identity; relation fields require an explicit relink API
# (not implemented in foundation); assignment cache and Status are
# never writable through the generic admin-field path.
_TASK_IDENTITY_FIELDS = ("Task ID", "Business ID", "Created At")
_TASK_RELATION_FIELDS = ("Client ID", "Object ID", "Service ID", "Roadmap ID", "Stage ID")
_TASK_ASSIGNMENT_CACHE_FIELDS = ("Responsible Role ID", "Assignee Person ID")


def update_task_admin_fields(task_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько admin-полей Task. Точечная запись
    только переданных колонок. Не проверяет cross-entity eligibility —
    это уже сделал business_builder.update_task_admin_fields() перед
    вызовом этой функции.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "code": str, "error": str | None}
    """
    if not task_id:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": "task_id не указан"}

    identity_conflict = [k for k in updates if k in _TASK_IDENTITY_FIELDS]
    if identity_conflict:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "TASK_IMMUTABLE_FIELD_CONFLICT",
            "error": f"Поля {', '.join(identity_conflict)} являются неизменяемой идентичностью Task",
        }

    relation_conflict = [k for k in updates if k in _TASK_RELATION_FIELDS]
    if relation_conflict:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION",
            "error": f"Поля {', '.join(relation_conflict)} требуют отдельного явного relink-действия (не реализовано)",
        }

    cache_conflict = [k for k in updates if k in _TASK_ASSIGNMENT_CACHE_FIELDS]
    if cache_conflict:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "INVALID_TASK_ADMIN_FIELD",
            "error": f"Поля {', '.join(cache_conflict)} доступны только через assignment orchestration",
        }

    if "Status" in updates:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "INVALID_TASK_ADMIN_FIELD",
            "error": "Status изменяется только через transition orchestration",
        }

    unknown = [k for k in updates if k not in _TASK_ADMIN_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (), "code": "INVALID_TASK_ADMIN_FIELD",
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    found = _find_task_row(task_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "code": "TASK_NOT_FOUND", "error": f"Task '{task_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime

        sheet = get_business_sheet("task_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        field_key_map = {f: f for f in _TASK_ADMIN_EDITABLE_FIELDS}

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

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, datetime.now().strftime("%Y-%m-%d"))

        log.info(f"update_task_admin_fields: {task_id} fields={updated_fields}")
        return {
            "ok": True, "changed": changed, "updated_fields": tuple(updated_fields),
            "code": "TASK_ADMIN_FIELDS_UPDATED" if changed else "TASK_ADMIN_FIELDS_UNCHANGED",
            "error": None,
        }
    except Exception as exc:
        log.error(f"update_task_admin_fields({task_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "code": "", "error": str(exc)}


def update_task_status(task_id: str, status: str, timestamp_field: str = "") -> dict:
    """
    Низкоуровневая запись Status (+ опциональная timestamp-колонка —
    Started At/Completed At/Cancelled At). Не проверяет transition
    matrix или Roadmap/Stage eligibility — это уже сделал
    business_builder.transition_task_status().

    timestamp_field, если указан и ещё пуст на строке, записывается
    вместе со Status в этом же вызове (Started At/Completed At/
    Cancelled At никогда не перезаписываются повторно — ADR-019 §16).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not task_id:
        return {"ok": False, "changed": False, "code": "TASK_NOT_FOUND", "error": "task_id не указан"}
    if status not in TASK_STATUS:
        return {
            "ok": False, "changed": False, "code": "INVALID_TASK_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TASK_STATUS)}",
        }

    found = _find_task_row(task_id)
    if not found:
        return {"ok": False, "changed": False, "code": "TASK_NOT_FOUND", "error": f"Task '{task_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime

        sheet = get_business_sheet("task_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        changed = False
        if current.get("Status", "") != status:
            sheet.update_cell(row_num, idx["Status"] + 1, status)
            changed = True

        if timestamp_field and timestamp_field in idx and not current.get(timestamp_field, ""):
            sheet.update_cell(row_num, idx[timestamp_field] + 1, datetime.now().strftime("%Y-%m-%d"))

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, datetime.now().strftime("%Y-%m-%d"))

        log.info(f"update_task_status: {task_id} -> {status}")
        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_task_status({task_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


def update_task_assignment_cache(task_id: str, responsible_role_id: str, assignee_person_id: str) -> dict:
    """
    Низкоуровневая запись cache-полей Responsible Role ID / Assignee
    Person ID на Task-строке. Единственный легитимный writer — canonical
    assignment orchestration (business_builder.assign_task()/
    unassign_task()) — ADR-019 §8/§22. Generic admin update не может
    достичь этого пути (см. update_task_admin_fields()'s explicit
    rejection выше).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not task_id:
        return {"ok": False, "changed": False, "code": "TASK_NOT_FOUND", "error": "task_id не указан"}

    found = _find_task_row(task_id)
    if not found:
        return {"ok": False, "changed": False, "code": "TASK_NOT_FOUND", "error": f"Task '{task_id}' не найден"}
    row_num, current = found

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime

        sheet = get_business_sheet("task_registry")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        changed = False
        if current.get("Responsible Role ID", "") != responsible_role_id:
            sheet.update_cell(row_num, idx["Responsible Role ID"] + 1, responsible_role_id)
            changed = True
        if current.get("Assignee Person ID", "") != assignee_person_id:
            sheet.update_cell(row_num, idx["Assignee Person ID"] + 1, assignee_person_id)
            changed = True

        if changed and "Updated At" in idx:
            sheet.update_cell(row_num, idx["Updated At"] + 1, datetime.now().strftime("%Y-%m-%d"))

        return {"ok": True, "changed": changed, "code": "", "error": None}
    except Exception as exc:
        log.error(f"update_task_assignment_cache({task_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Task Assignment: internal read helper
# ─────────────────────────────────────────────────────────────

_TASK_ASSIGNMENT_FIELDS = [
    "Task Assignment ID", "Task ID", "Responsible Role ID",
    "Assignee Person ID", "Status", "Start Date", "End Date",
    "Assignment Type", "Created At", "Updated At",
]


def _list_task_assignments_raw() -> list[dict]:
    """Internal: read every TASK_ASSIGNMENTS row, unfiltered."""
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("task_assignments")
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
            results.append({
                "task_assignment_id":  _g(row, "Task Assignment ID"),
                "task_id":              _g(row, "Task ID"),
                "responsible_role_id":  _g(row, "Responsible Role ID"),
                "assignee_person_id":   _g(row, "Assignee Person ID"),
                "status":               _g(row, "Status"),
                "start_date":           _g(row, "Start Date"),
                "end_date":             _g(row, "End Date"),
                "assignment_type":      _g(row, "Assignment Type"),
                "created_at":           _g(row, "Created At"),
                "updated_at":           _g(row, "Updated At"),
            })
        return results
    except Exception as exc:
        log.warning(f"_list_task_assignments_raw() error: {exc}")
        return []


def list_task_assignments_for_task(task_id: str, status: str = "") -> list[dict]:
    """Read-only. Все Task Assignment для одного Task, опционально по Status."""
    if not task_id:
        return []
    return [
        a for a in _list_task_assignments_raw()
        if a["task_id"] == task_id and (not status or a["status"] == status)
    ]


def find_task_assignment_by_id(task_assignment_id: str) -> Optional[dict]:
    """Read-only. Одна Task Assignment по ID, или None."""
    if not task_assignment_id:
        return None
    for a in _list_task_assignments_raw():
        if a["task_assignment_id"] == task_assignment_id:
            return a
    return None


def create_task_assignment(
    task_id: str,
    responsible_role_id: str,
    assignee_person_id: str,
    start_date: str,
    assignment_type: str = "primary",
    status: str = "active",
) -> dict:
    """
    Создать Task Assignment в TASK_ASSIGNMENTS. Низкоуровневая запись —
    не проверяет Role/Person eligibility, не проверяет duplicate active
    policy. Вся эта политика — исключительно business_builder.
    assign_task() (ADR-019 §17-20).

    Returns:
        {"ok": bool, "task_assignment_id": str, "code": str, "error": str | None}
    """
    if not task_id:
        return {"ok": False, "task_assignment_id": "", "code": "", "error": "task_id обязателен"}
    if not start_date:
        return {"ok": False, "task_assignment_id": "", "code": "", "error": "start_date обязателен"}
    if not _is_valid_date(start_date):
        return {"ok": False, "task_assignment_id": "", "code": "", "error": f"Недопустимый формат start_date '{start_date}'"}
    if status not in TASK_ASSIGNMENT_STATUS:
        return {
            "ok": False, "task_assignment_id": "", "code": "INVALID_TASK_ASSIGNMENT_STATUS",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(TASK_ASSIGNMENT_STATUS)}",
        }

    try:
        from business_core.sheets import generate_next_id, append_business_row
        from datetime import datetime

        task_assignment_id = generate_next_id("task_assignments")
        ts = datetime.now().strftime("%Y-%m-%d")
        row = [
            task_assignment_id, task_id, responsible_role_id, assignee_person_id,
            status, start_date, "", assignment_type, ts, ts,
        ]
        append_business_row("task_assignments", row)
        log.info(f"create_task_assignment: {task_assignment_id} / task={task_id}")
        return {"ok": True, "task_assignment_id": task_assignment_id, "code": "TASK_ASSIGNMENT_CREATED", "error": None}
    except Exception as exc:
        log.error(f"create_task_assignment error: {exc}")
        return {"ok": False, "task_assignment_id": "", "code": "", "error": str(exc)}


def end_task_assignment(task_assignment_id: str, end_date: Optional[str] = None) -> dict:
    """
    Завершить Task Assignment (Status=ended, End Date заполняется).
    Идемпотентна: повторный вызов на уже ended Assignment возвращает
    ok=True, changed=False. Никогда не удаляет строку — soft-terminal
    only (ADR-019 §16).

    Returns:
        {"ok": bool, "changed": bool, "code": str, "error": str | None}
    """
    if not task_assignment_id:
        return {"ok": False, "changed": False, "code": "", "error": "task_assignment_id не указан"}

    existing = find_task_assignment_by_id(task_assignment_id)
    if not existing:
        return {"ok": False, "changed": False, "code": "", "error": f"Task Assignment '{task_assignment_id}' не найдена"}

    if existing["status"] == "ended":
        return {"ok": True, "changed": False, "code": "", "error": None}

    if end_date and not _is_valid_date(end_date):
        return {"ok": False, "changed": False, "code": "", "error": f"Недопустимый формат end_date '{end_date}'"}

    if not end_date:
        from datetime import datetime
        end_date = datetime.now().strftime("%Y-%m-%d")

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map
        from datetime import datetime

        sheet = get_business_sheet("task_assignments")
        cell = sheet.find(task_assignment_id, in_column=1)
        if not cell:
            return {"ok": False, "changed": False, "code": "", "error": f"Task Assignment '{task_assignment_id}' не найдена в листе"}

        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        sheet.update_cell(cell.row, idx["Status"] + 1, "ended")
        sheet.update_cell(cell.row, idx["End Date"] + 1, end_date)
        if "Updated At" in idx:
            sheet.update_cell(cell.row, idx["Updated At"] + 1, datetime.now().strftime("%Y-%m-%d"))

        log.info(f"end_task_assignment: {task_assignment_id}")
        return {"ok": True, "changed": True, "code": "", "error": None}
    except Exception as exc:
        log.error(f"end_task_assignment({task_assignment_id}) error: {exc}")
        return {"ok": False, "changed": False, "code": "", "error": str(exc)}
