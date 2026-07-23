"""
Organization Manager — Department, Role, Role Function, Person Role
Assignment (Phase 21B + 21C).

Организационная структура компании. Реализует архитектуру Phase 20A ->
20A.6 (см. ARCHITECTURE.md, раздел "Organization Layer") в редакции
критических замечаний: Role не привязана к Business ID (глобальна для
всей группы), внешние подрядчики НЕ являются Role — они остаются в
PEOPLE_REGISTRY (External Party Layer). Role Function — отдельная
сущность (не свёрнута в Role.Notes, см. Phase 20A revised §6). Person
Role Assignment — отдельная сущность с полной историей (soft delete
only, см. ENGINEERING_STANDARDS.md).

Phase 21F добавит Telegram-команды отдельным слоем поверх функций отсюда.

Единственные внешние FK-проверки (read-only, никогда запись — см.
ENGINEERING_STANDARDS.md, Layer Dependency Rules): Business ID на
Department сверяется с BIZ_REGISTRY; Person ID на Assignment сверяется
с PEOPLE_REGISTRY. Head Role ID на Department намеренно НЕ валидируется
при записи — вакантный Department легитимен, ссылка может указывать на
ещё не созданную Role (см. ARCHITECTURE.md).

Зависимости: только business_core.sheets. GTD Core не импортируется.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Canonical enums (см. ENGINEERING_STANDARDS.md, Google Sheets Standards)
# ─────────────────────────────────────────────────────────────

DEPARTMENT_STATUS = ("active", "archived")

# ROLE_TYPE намеренно содержит только "internal" в v1 — внешние подрядчики
# не становятся Role-строками (см. ARCHITECTURE.md / External Party Layer).
# Значение зарезервировано на будущее без необходимости менять enum позже.
ROLE_TYPE = ("internal",)

EMPLOYMENT_MODEL = ("full_time", "part_time")

ROLE_STATUS = ("planned", "active", "paused", "archived")


# ─────────────────────────────────────────────────────────────
# Department: internal read helper
# ─────────────────────────────────────────────────────────────

def _find_department_row(department_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not department_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("department_registry")
        cell = sheet.find(department_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        wanted = [
            "Department ID", "Business ID", "Department Name",
            "Parent Department ID", "Head Role ID", "Status", "Notes",
        ]
        v = read_row_by_headers(headers, row, wanted)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_department_row({department_id}) error: {exc}")
        return None


def find_department_by_id(department_id: str) -> Optional[dict]:
    """
    Найти Department по ID. Read-only.

    Returns:
        dict с полями row_num, department_id, business_id, department_name,
        parent_department_id, head_role_id, status, notes — или None.
    """
    found = _find_department_row(department_id)
    if not found:
        return None
    row_num, v = found
    return {
        "row_num":              row_num,
        "department_id":        v["Department ID"],
        "business_id":          v["Business ID"],
        "department_name":      v["Department Name"],
        "parent_department_id": v["Parent Department ID"],
        "head_role_id":         v["Head Role ID"],
        "status":               v["Status"],
        "notes":                v["Notes"],
    }


def list_departments(business_id: str = "", status: str = "") -> list[dict]:
    """
    Список Department, опционально отфильтрованный по Business ID и/или
    Status. Read-only. Пустые фильтры — вернуть все строки.
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("department_registry")
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
            dept_business_id = _g(row, "Business ID")
            dept_status = _g(row, "Status")
            if business_id and dept_business_id != business_id:
                continue
            if status and dept_status != status:
                continue
            results.append({
                "department_id":        _g(row, "Department ID"),
                "business_id":          dept_business_id,
                "department_name":      _g(row, "Department Name"),
                "parent_department_id": _g(row, "Parent Department ID"),
                "head_role_id":         _g(row, "Head Role ID"),
                "status":               dept_status,
                "notes":                _g(row, "Notes"),
            })
        return results
    except Exception as exc:
        log.warning(f"list_departments() error: {exc}")
        return []


# ─────────────────────────────────────────────────────────────
# Department: write operations
# ─────────────────────────────────────────────────────────────

def create_department(
    department_name: str,
    business_id: str = "",
    parent_department_id: str = "",
    head_role_id: str = "",
    status: str = "active",
    notes: str = "",
) -> dict:
    """
    Создать Department в DEPARTMENT_REGISTRY.

    Business ID — опционален (Department может быть глобальным, см.
    ARCHITECTURE.md §5); если указан — валидируется против BIZ_REGISTRY.
    Parent Department ID — опционален; если указан — валидируется против
    DEPARTMENT_REGISTRY (self-FK). Head Role ID НЕ валидируется — вакантный
    Department без назначенной головы роли легитимен по дизайну.

    Returns:
        {"ok": bool, "department_id": str, "error": str | None}
    """
    if not department_name:
        return {"ok": False, "department_id": "", "error": "department_name обязателен"}

    if status not in DEPARTMENT_STATUS:
        return {
            "ok": False, "department_id": "",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(DEPARTMENT_STATUS)}",
        }

    if business_id:
        try:
            from business_core.sheets import find_row_by_id
            if not find_row_by_id("biz_registry", business_id):
                return {"ok": False, "department_id": "", "error": f"Business '{business_id}' не найден"}
        except Exception as exc:
            log.error(f"create_department business_id validation error: {exc}")
            return {"ok": False, "department_id": "", "error": str(exc)}

    if parent_department_id:
        if not find_department_by_id(parent_department_id):
            return {
                "ok": False, "department_id": "",
                "error": f"Parent Department '{parent_department_id}' не найден",
            }

    try:
        from business_core.sheets import generate_next_id, append_business_row

        department_id = generate_next_id("department_registry")
        row = [
            department_id, business_id, department_name,
            parent_department_id, head_role_id, status, notes,
        ]
        append_business_row("department_registry", row)
        log.info(f"create_department: {department_id} / {department_name}")
        return {"ok": True, "department_id": department_id, "error": None}
    except Exception as exc:
        log.error(f"create_department error: {exc}")
        return {"ok": False, "department_id": "", "error": str(exc)}


_DEPARTMENT_EDITABLE_FIELDS = (
    "Business ID", "Department Name", "Parent Department ID",
    "Head Role ID", "Status", "Notes",
)


def update_department(department_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Department. Точечная запись только
    переданных колонок — по имени заголовка, только в найденную строку.

    Args:
        department_id: DEPT-xxx
        updates: {header_name: new_value}, только поля из
                 _DEPARTMENT_EDITABLE_FIELDS. "Department ID" не может быть
                 изменён (это ключ записи, не редактируемое поле).

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not department_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "department_id не указан"}

    unknown = [k for k in updates if k not in _DEPARTMENT_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    if "Status" in updates and updates["Status"] not in DEPARTMENT_STATUS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый статус '{updates['Status']}'. Допустимые значения: {', '.join(DEPARTMENT_STATUS)}",
        }

    if "Business ID" in updates and updates["Business ID"]:
        try:
            from business_core.sheets import find_row_by_id
            if not find_row_by_id("biz_registry", updates["Business ID"]):
                return {
                    "ok": False, "changed": False, "updated_fields": (),
                    "error": f"Business '{updates['Business ID']}' не найден",
                }
        except Exception as exc:
            log.error(f"update_department business_id validation error: {exc}")
            return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}

    if "Parent Department ID" in updates and updates["Parent Department ID"]:
        if updates["Parent Department ID"] == department_id:
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": "Department не может быть родителем самого себя",
            }
        if not find_department_by_id(updates["Parent Department ID"]):
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": f"Parent Department '{updates['Parent Department ID']}' не найден",
            }

    found = _find_department_row(department_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Department '{department_id}' не найден"}
    row_num, current = found

    field_key_map = {
        "Business ID": "Business ID", "Department Name": "Department Name",
        "Parent Department ID": "Parent Department ID", "Head Role ID": "Head Role ID",
        "Status": "Status", "Notes": "Notes",
    }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("department_registry")
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

        log.info(f"update_department: {department_id} fields={updated_fields}")
        return {"ok": True, "changed": changed, "updated_fields": tuple(updated_fields), "error": None}
    except Exception as exc:
        log.error(f"update_department({department_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


def archive_department(department_id: str) -> dict:
    """
    Soft-delete Department через Status=archived. Идемпотентна: повторный
    вызов на уже archived Department возвращает ok=True, changed=False.

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    existing = find_department_by_id(department_id)
    if not existing:
        return {"ok": False, "changed": False, "error": f"Department '{department_id}' не найден"}

    if existing["status"] == "archived":
        return {"ok": True, "changed": False, "error": None}

    result = update_department(department_id, {"Status": "archived"})
    return {"ok": result["ok"], "changed": result["changed"], "error": result["error"]}


# ─────────────────────────────────────────────────────────────
# Role: internal read helper
# ─────────────────────────────────────────────────────────────

def _find_role_row(role_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not role_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("role_registry")
        cell = sheet.find(role_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        wanted = [
            "Role ID", "Department ID", "Role Name", "Reports To Role ID",
            "Role Type", "Employment Model", "Status",
            "Purpose", "Main Result", "Notes",
        ]
        v = read_row_by_headers(headers, row, wanted)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_role_row({role_id}) error: {exc}")
        return None


def find_role_by_id(role_id: str) -> Optional[dict]:
    """
    Найти Role по ID. Read-only.

    Returns:
        dict с полями row_num, role_id, department_id, role_name,
        reports_to_role_id, role_type, employment_model, status, purpose,
        main_result, notes — или None.
    """
    found = _find_role_row(role_id)
    if not found:
        return None
    row_num, v = found
    return {
        "row_num":             row_num,
        "role_id":             v["Role ID"],
        "department_id":       v["Department ID"],
        "role_name":           v["Role Name"],
        "reports_to_role_id":  v["Reports To Role ID"],
        "role_type":           v["Role Type"],
        "employment_model":    v["Employment Model"],
        "status":              v["Status"],
        "purpose":             v["Purpose"],
        "main_result":         v["Main Result"],
        "notes":               v["Notes"],
    }


def list_roles(department_id: str = "", status: str = "") -> list[dict]:
    """
    Список Role, опционально отфильтрованный по Department ID и/или
    Status. Read-only. Пустые фильтры — вернуть все строки.
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("role_registry")
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
            role_department_id = _g(row, "Department ID")
            role_status = _g(row, "Status")
            if department_id and role_department_id != department_id:
                continue
            if status and role_status != status:
                continue
            results.append({
                "role_id":            _g(row, "Role ID"),
                "department_id":      role_department_id,
                "role_name":          _g(row, "Role Name"),
                "reports_to_role_id": _g(row, "Reports To Role ID"),
                "role_type":          _g(row, "Role Type"),
                "employment_model":   _g(row, "Employment Model"),
                "status":             role_status,
                "purpose":            _g(row, "Purpose"),
                "main_result":        _g(row, "Main Result"),
                "notes":              _g(row, "Notes"),
            })
        return results
    except Exception as exc:
        log.warning(f"list_roles() error: {exc}")
        return []


# ─────────────────────────────────────────────────────────────
# Role: write operations
# ─────────────────────────────────────────────────────────────

def create_role(
    role_name: str,
    department_id: str,
    reports_to_role_id: str = "",
    role_type: str = "internal",
    employment_model: str = "full_time",
    status: str = "planned",
    purpose: str = "",
    main_result: str = "",
    notes: str = "",
) -> dict:
    """
    Создать Role в ROLE_REGISTRY. Внутренняя должность — НЕ для внешних
    подрядчиков (см. ARCHITECTURE.md / External Party Layer: контракторы
    остаются PEOPLE_REGISTRY-строками, никогда Role).

    Role глобальна для группы бизнесов — Business ID не хранится на самой
    Role (см. Phase 20A revised §4). department_id обязателен и
    валидируется против DEPARTMENT_REGISTRY. reports_to_role_id, если
    указан, валидируется против ROLE_REGISTRY.

    Returns:
        {"ok": bool, "role_id": str, "error": str | None}
    """
    if not role_name:
        return {"ok": False, "role_id": "", "error": "role_name обязателен"}
    if not department_id:
        return {"ok": False, "role_id": "", "error": "department_id обязателен"}

    if role_type not in ROLE_TYPE:
        return {
            "ok": False, "role_id": "",
            "error": f"Недопустимый Role Type '{role_type}'. Допустимые значения: {', '.join(ROLE_TYPE)}",
        }
    if employment_model not in EMPLOYMENT_MODEL:
        return {
            "ok": False, "role_id": "",
            "error": f"Недопустимый Employment Model '{employment_model}'. Допустимые значения: {', '.join(EMPLOYMENT_MODEL)}",
        }
    if status not in ROLE_STATUS:
        return {
            "ok": False, "role_id": "",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(ROLE_STATUS)}",
        }

    if not find_department_by_id(department_id):
        return {"ok": False, "role_id": "", "error": f"Department '{department_id}' не найден"}

    if reports_to_role_id and not find_role_by_id(reports_to_role_id):
        return {"ok": False, "role_id": "", "error": f"Reports To Role '{reports_to_role_id}' не найден"}

    try:
        from business_core.sheets import generate_next_id, append_business_row

        role_id = generate_next_id("role_registry")
        row = [
            role_id, department_id, role_name, reports_to_role_id,
            role_type, employment_model, status, purpose, main_result, notes,
        ]
        append_business_row("role_registry", row)
        log.info(f"create_role: {role_id} / {role_name}")
        return {"ok": True, "role_id": role_id, "error": None}
    except Exception as exc:
        log.error(f"create_role error: {exc}")
        return {"ok": False, "role_id": "", "error": str(exc)}


_ROLE_EDITABLE_FIELDS = (
    "Department ID", "Role Name", "Reports To Role ID", "Role Type",
    "Employment Model", "Status", "Purpose", "Main Result", "Notes",
)


def update_role(role_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Role. Точечная запись только
    переданных колонок — по имени заголовка, только в найденную строку.

    Args:
        role_id: ROLE-xxx
        updates: {header_name: new_value}, только поля из
                 _ROLE_EDITABLE_FIELDS. "Role ID" не может быть изменён.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not role_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "role_id не указан"}

    unknown = [k for k in updates if k not in _ROLE_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    if "Role Type" in updates and updates["Role Type"] not in ROLE_TYPE:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый Role Type '{updates['Role Type']}'. Допустимые значения: {', '.join(ROLE_TYPE)}",
        }
    if "Employment Model" in updates and updates["Employment Model"] not in EMPLOYMENT_MODEL:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый Employment Model '{updates['Employment Model']}'. Допустимые значения: {', '.join(EMPLOYMENT_MODEL)}",
        }
    if "Status" in updates and updates["Status"] not in ROLE_STATUS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый статус '{updates['Status']}'. Допустимые значения: {', '.join(ROLE_STATUS)}",
        }

    if "Department ID" in updates:
        if not updates["Department ID"] or not find_department_by_id(updates["Department ID"]):
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": f"Department '{updates.get('Department ID', '')}' не найден",
            }

    if "Reports To Role ID" in updates and updates["Reports To Role ID"]:
        if updates["Reports To Role ID"] == role_id:
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": "Role не может подчиняться самой себе",
            }
        if not find_role_by_id(updates["Reports To Role ID"]):
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": f"Reports To Role '{updates['Reports To Role ID']}' не найден",
            }

    found = _find_role_row(role_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Role '{role_id}' не найден"}
    row_num, current = found

    field_key_map = {
        "Department ID": "Department ID", "Role Name": "Role Name",
        "Reports To Role ID": "Reports To Role ID", "Role Type": "Role Type",
        "Employment Model": "Employment Model", "Status": "Status",
        "Purpose": "Purpose", "Main Result": "Main Result", "Notes": "Notes",
    }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("role_registry")
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

        log.info(f"update_role: {role_id} fields={updated_fields}")
        return {"ok": True, "changed": changed, "updated_fields": tuple(updated_fields), "error": None}
    except Exception as exc:
        log.error(f"update_role({role_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


def archive_role(role_id: str) -> dict:
    """
    Soft-delete Role через Status=archived. Идемпотентна: повторный вызов
    на уже archived Role возвращает ok=True, changed=False. Не удаляет
    Person Role Assignments (Phase 21C) — это отдельная сущность с
    собственным жизненным циклом (см. ARCHITECTURE.md / Organization Layer).

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    existing = find_role_by_id(role_id)
    if not existing:
        return {"ok": False, "changed": False, "error": f"Role '{role_id}' не найден"}

    if existing["status"] == "archived":
        return {"ok": True, "changed": False, "error": None}

    result = update_role(role_id, {"Status": "archived"})
    return {"ok": result["ok"], "changed": result["changed"], "error": result["error"]}


# ═══════════════════════════════════════════════════════════════
# Phase 21C: Role Function CRUD
# ═══════════════════════════════════════════════════════════════
#
# One row per named, individually-trackable function belonging to a Role
# (see ARCHITECTURE.md / Organization Layer, Phase 20A revised §6 — a
# real, current need given the Coordinator role's 11 named functions,
# not folded into Role.Notes). Frequency/Criticality/Can Delegate are
# accepted but not required — deferred fields per the approved schema,
# blank is valid.

ROLE_FUNCTION_STATUS = ("active", "inactive")

FUNCTION_FREQUENCY = ("continuous", "daily", "weekly", "monthly", "ad_hoc")

CRITICALITY = ("low", "medium", "high")

VALID_BOOL_STRINGS = ("true", "false")


def _find_role_function_row(function_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not function_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("role_functions")
        cell = sheet.find(function_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        wanted = [
            "Function ID", "Role ID", "Function Category", "Function Name",
            "Description", "Frequency", "Criticality", "Can Delegate",
            "Status", "Sort Order",
        ]
        v = read_row_by_headers(headers, row, wanted)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_role_function_row({function_id}) error: {exc}")
        return None


def find_role_function_by_id(function_id: str) -> Optional[dict]:
    """
    Найти Role Function по ID. Read-only.

    Returns:
        dict с полями row_num, function_id, role_id, function_category,
        function_name, description, frequency, criticality, can_delegate,
        status, sort_order — или None.
    """
    found = _find_role_function_row(function_id)
    if not found:
        return None
    row_num, v = found
    return {
        "row_num":           row_num,
        "function_id":       v["Function ID"],
        "role_id":           v["Role ID"],
        "function_category": v["Function Category"],
        "function_name":     v["Function Name"],
        "description":       v["Description"],
        "frequency":         v["Frequency"],
        "criticality":       v["Criticality"],
        "can_delegate":      v["Can Delegate"],
        "status":            v["Status"],
        "sort_order":        v["Sort Order"],
    }


def list_role_functions(role_id: str = "", status: str = "") -> list[dict]:
    """
    Список Role Function, опционально отфильтрованный по Role ID и/или
    Status. Read-only. Отсортирован по Sort Order (числовой, нечисловые/
    пустые значения — в конец, как в get_stages_for_roadmap()).
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("role_functions")
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
            func_role_id = _g(row, "Role ID")
            func_status = _g(row, "Status")
            if role_id and func_role_id != role_id:
                continue
            if status and func_status != status:
                continue
            results.append({
                "function_id":       _g(row, "Function ID"),
                "role_id":           func_role_id,
                "function_category": _g(row, "Function Category"),
                "function_name":     _g(row, "Function Name"),
                "description":       _g(row, "Description"),
                "frequency":         _g(row, "Frequency"),
                "criticality":       _g(row, "Criticality"),
                "can_delegate":      _g(row, "Can Delegate"),
                "status":            func_status,
                "sort_order":        _g(row, "Sort Order"),
            })
        results.sort(key=lambda x: int(x["sort_order"]) if x["sort_order"].isdigit() else 0)
        return results
    except Exception as exc:
        log.warning(f"list_role_functions() error: {exc}")
        return []


def create_role_function(
    function_name: str,
    role_id: str,
    function_category: str = "",
    description: str = "",
    frequency: str = "",
    criticality: str = "",
    can_delegate: str = "false",
    status: str = "active",
    sort_order: str = "0",
) -> dict:
    """
    Создать Role Function в ROLE_FUNCTIONS. role_id обязателен и
    валидируется против ROLE_REGISTRY. Frequency/Criticality — опциональны
    (см. Phase 20A revised §6, deferred fields), но если указаны —
    валидируются против соответствующего enum.

    Returns:
        {"ok": bool, "function_id": str, "error": str | None}
    """
    if not function_name:
        return {"ok": False, "function_id": "", "error": "function_name обязателен"}
    if not role_id:
        return {"ok": False, "function_id": "", "error": "role_id обязателен"}

    if status not in ROLE_FUNCTION_STATUS:
        return {
            "ok": False, "function_id": "",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(ROLE_FUNCTION_STATUS)}",
        }
    if frequency and frequency not in FUNCTION_FREQUENCY:
        return {
            "ok": False, "function_id": "",
            "error": f"Недопустимая Frequency '{frequency}'. Допустимые значения: {', '.join(FUNCTION_FREQUENCY)}",
        }
    if criticality and criticality not in CRITICALITY:
        return {
            "ok": False, "function_id": "",
            "error": f"Недопустимая Criticality '{criticality}'. Допустимые значения: {', '.join(CRITICALITY)}",
        }
    if can_delegate not in VALID_BOOL_STRINGS:
        return {
            "ok": False, "function_id": "",
            "error": f"Недопустимое значение Can Delegate '{can_delegate}'. Допустимые значения: {', '.join(VALID_BOOL_STRINGS)}",
        }

    if not find_role_by_id(role_id):
        return {"ok": False, "function_id": "", "error": f"Role '{role_id}' не найден"}

    try:
        from business_core.sheets import generate_next_id, append_business_row

        function_id = generate_next_id("role_functions")
        row = [
            function_id, role_id, function_category, function_name,
            description, frequency, criticality, can_delegate,
            status, sort_order,
        ]
        append_business_row("role_functions", row)
        log.info(f"create_role_function: {function_id} / {function_name} (role={role_id})")
        return {"ok": True, "function_id": function_id, "error": None}
    except Exception as exc:
        log.error(f"create_role_function error: {exc}")
        return {"ok": False, "function_id": "", "error": str(exc)}


_ROLE_FUNCTION_EDITABLE_FIELDS = (
    "Role ID", "Function Category", "Function Name", "Description",
    "Frequency", "Criticality", "Can Delegate", "Status", "Sort Order",
)


def update_role_function(function_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Role Function. Точечная запись
    только переданных колонок. "Role ID" МОЖЕТ быть переназначен —
    это единственная операция, которой распределяется ответственность
    между ролями (например, перенести функцию с Coordinator на новую
    Inbound Manager, см. Phase 20A revised §6) — простое обновление
    одного поля, не пересоздание строки.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not function_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "function_id не указан"}

    unknown = [k for k in updates if k not in _ROLE_FUNCTION_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    if "Status" in updates and updates["Status"] not in ROLE_FUNCTION_STATUS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый статус '{updates['Status']}'. Допустимые значения: {', '.join(ROLE_FUNCTION_STATUS)}",
        }
    if "Frequency" in updates and updates["Frequency"] and updates["Frequency"] not in FUNCTION_FREQUENCY:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимая Frequency '{updates['Frequency']}'. Допустимые значения: {', '.join(FUNCTION_FREQUENCY)}",
        }
    if "Criticality" in updates and updates["Criticality"] and updates["Criticality"] not in CRITICALITY:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимая Criticality '{updates['Criticality']}'. Допустимые значения: {', '.join(CRITICALITY)}",
        }
    if "Can Delegate" in updates and updates["Can Delegate"] not in VALID_BOOL_STRINGS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимое значение Can Delegate '{updates['Can Delegate']}'. Допустимые значения: {', '.join(VALID_BOOL_STRINGS)}",
        }
    if "Role ID" in updates:
        if not updates["Role ID"] or not find_role_by_id(updates["Role ID"]):
            return {
                "ok": False, "changed": False, "updated_fields": (),
                "error": f"Role '{updates.get('Role ID', '')}' не найден",
            }

    found = _find_role_function_row(function_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Function '{function_id}' не найден"}
    row_num, current = found

    field_key_map = {
        "Role ID": "Role ID", "Function Category": "Function Category",
        "Function Name": "Function Name", "Description": "Description",
        "Frequency": "Frequency", "Criticality": "Criticality",
        "Can Delegate": "Can Delegate", "Status": "Status", "Sort Order": "Sort Order",
    }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("role_functions")
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

        log.info(f"update_role_function: {function_id} fields={updated_fields}")
        return {"ok": True, "changed": changed, "updated_fields": tuple(updated_fields), "error": None}
    except Exception as exc:
        log.error(f"update_role_function({function_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}


def archive_role_function(function_id: str) -> dict:
    """
    Soft-delete Role Function через Status=inactive. Идемпотентна:
    повторный вызов на уже inactive Function возвращает ok=True,
    changed=False.

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    existing = find_role_function_by_id(function_id)
    if not existing:
        return {"ok": False, "changed": False, "error": f"Function '{function_id}' не найден"}

    if existing["status"] == "inactive":
        return {"ok": True, "changed": False, "error": None}

    result = update_role_function(function_id, {"Status": "inactive"})
    return {"ok": result["ok"], "changed": result["changed"], "error": result["error"]}


# ═══════════════════════════════════════════════════════════════
# Phase 21C: Person Role Assignment CRUD
# ═══════════════════════════════════════════════════════════════
#
# Who currently/previously held which Role. Multiple simultaneous active
# Assignments for one Person are legitimate (multi-role — see
# ARCHITECTURE.md §4 invariant). Ending an Assignment (End Date +
# Status=ended) never deletes the row — full history stays queryable
# (Phase 21 Test Plan: "history"). A Role's vacancy is a pure read-time
# computation (zero active Assignments), never a stored flag on Role.

ASSIGNMENT_STATUS = ("active", "ended", "paused")

ASSIGNMENT_TYPE = ("primary", "backup", "temporary")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_date(value: str) -> bool:
    return bool(_DATE_RE.match(value or ""))


def _find_assignment_row(assignment_id: str) -> Optional[tuple[int, dict]]:
    """Read-only. Возвращает (row_num, row_dict) или None."""
    if not assignment_id:
        return None
    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("person_role_assignments")
        cell = sheet.find(assignment_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)
        wanted = [
            "Assignment ID", "Person ID", "Role ID",
            "Start Date", "End Date", "Assignment Type", "Status", "Notes",
        ]
        v = read_row_by_headers(headers, row, wanted)
        return (cell.row, v)
    except Exception as exc:
        log.warning(f"_find_assignment_row({assignment_id}) error: {exc}")
        return None


def find_assignment_by_id(assignment_id: str) -> Optional[dict]:
    """
    Найти Person Role Assignment по ID. Read-only.

    Returns:
        dict с полями row_num, assignment_id, person_id, role_id,
        start_date, end_date, assignment_type, status, notes — или None.
    """
    found = _find_assignment_row(assignment_id)
    if not found:
        return None
    row_num, v = found
    return {
        "row_num":         row_num,
        "assignment_id":   v["Assignment ID"],
        "person_id":       v["Person ID"],
        "role_id":         v["Role ID"],
        "start_date":      v["Start Date"],
        "end_date":        v["End Date"],
        "assignment_type": v["Assignment Type"],
        "status":          v["Status"],
        "notes":           v["Notes"],
    }


def _list_assignments_raw() -> list[dict]:
    """Internal: read every PERSON_ROLE_ASSIGNMENTS row, unfiltered."""
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("person_role_assignments")
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
                "assignment_id":   _g(row, "Assignment ID"),
                "person_id":       _g(row, "Person ID"),
                "role_id":         _g(row, "Role ID"),
                "start_date":      _g(row, "Start Date"),
                "end_date":        _g(row, "End Date"),
                "assignment_type": _g(row, "Assignment Type"),
                "status":          _g(row, "Status"),
                "notes":           _g(row, "Notes"),
            })
        return results
    except Exception as exc:
        log.warning(f"_list_assignments_raw() error: {exc}")
        return []


def list_assignments_for_person(person_id: str, status: str = "") -> list[dict]:
    """Read-only. Все Assignment для одного Person, опционально по Status."""
    if not person_id:
        return []
    return [
        a for a in _list_assignments_raw()
        if a["person_id"] == person_id and (not status or a["status"] == status)
    ]


def list_assignments_for_role(role_id: str, status: str = "") -> list[dict]:
    """Read-only. Все Assignment для одной Role, опционально по Status."""
    if not role_id:
        return []
    return [
        a for a in _list_assignments_raw()
        if a["role_id"] == role_id and (not status or a["status"] == status)
    ]


def get_assignment_history(role_id: str) -> list[dict]:
    """
    Read-only. Полная история Assignment для Role — ВСЕ статусы (active,
    ended, paused), отсортированные по Start Date по возрастанию. Ни одна
    запись никогда не удаляется физически (soft delete only — см.
    ENGINEERING_STANDARDS.md, Google Sheets Standards).
    """
    if not role_id:
        return []
    history = [a for a in _list_assignments_raw() if a["role_id"] == role_id]
    history.sort(key=lambda a: a["start_date"] or "")
    return history


def is_role_vacant(role_id: str) -> bool:
    """
    Read-only. True если у Role нет ни одного Assignment со Status=active.
    Вакансия — чисто вычисляемое состояние, никогда не хранится отдельным
    полем на Role (см. ARCHITECTURE.md / Organization Layer).
    """
    return len(list_assignments_for_role(role_id, status="active")) == 0


def get_active_roles_for_person(person_id: str) -> list[dict]:
    """
    Read-only. Все активные (Status=active) Assignment для Person —
    поддерживает multi-role: один Person может одновременно занимать
    несколько Role (см. ARCHITECTURE.md §4 инвариант).
    """
    return list_assignments_for_person(person_id, status="active")


def assign_person_to_role(
    person_id: str,
    role_id: str,
    start_date: str,
    assignment_type: str = "primary",
    status: str = "active",
    notes: str = "",
) -> dict:
    """
    Создать Person Role Assignment в PERSON_ROLE_ASSIGNMENTS. person_id
    валидируется против PEOPLE_REGISTRY (read-only cross-domain FK check —
    см. ENGINEERING_STANDARDS.md, Layer Dependency Rules: только чтение,
    никогда запись в чужой Registry). role_id валидируется против
    ROLE_REGISTRY. Множественные одновременные active Assignment для
    одного Person разрешены (multi-role) — эта функция НЕ проверяет и не
    запрещает такое дублирование.

    Returns:
        {"ok": bool, "assignment_id": str, "error": str | None}
    """
    if not person_id:
        return {"ok": False, "assignment_id": "", "error": "person_id обязателен"}
    if not role_id:
        return {"ok": False, "assignment_id": "", "error": "role_id обязателен"}
    if not start_date:
        return {"ok": False, "assignment_id": "", "error": "start_date обязателен"}

    if not _is_valid_date(start_date):
        return {"ok": False, "assignment_id": "", "error": f"Недопустимый формат start_date '{start_date}'. Ожидается YYYY-MM-DD"}
    if assignment_type not in ASSIGNMENT_TYPE:
        return {
            "ok": False, "assignment_id": "",
            "error": f"Недопустимый Assignment Type '{assignment_type}'. Допустимые значения: {', '.join(ASSIGNMENT_TYPE)}",
        }
    if status not in ASSIGNMENT_STATUS:
        return {
            "ok": False, "assignment_id": "",
            "error": f"Недопустимый статус '{status}'. Допустимые значения: {', '.join(ASSIGNMENT_STATUS)}",
        }

    try:
        from business_core.sheets import find_row_by_id
        if not find_row_by_id("people_registry", person_id):
            return {"ok": False, "assignment_id": "", "error": f"Person '{person_id}' не найден"}
    except Exception as exc:
        log.error(f"assign_person_to_role person_id validation error: {exc}")
        return {"ok": False, "assignment_id": "", "error": str(exc)}

    if not find_role_by_id(role_id):
        return {"ok": False, "assignment_id": "", "error": f"Role '{role_id}' не найден"}

    try:
        from business_core.sheets import generate_next_id, append_business_row

        assignment_id = generate_next_id("person_role_assignments")
        row = [
            assignment_id, person_id, role_id,
            start_date, "", assignment_type, status, notes,
        ]
        append_business_row("person_role_assignments", row)
        log.info(f"assign_person_to_role: {assignment_id} / {person_id} -> {role_id}")
        return {"ok": True, "assignment_id": assignment_id, "error": None}
    except Exception as exc:
        log.error(f"assign_person_to_role error: {exc}")
        return {"ok": False, "assignment_id": "", "error": str(exc)}


def end_assignment(assignment_id: str, end_date: Optional[str] = None) -> dict:
    """
    Завершить Assignment: записывает End Date (сегодняшняя дата, если
    end_date не передан) и Status=ended. Идемпотентна: повторный вызов на
    уже ended Assignment возвращает ok=True, changed=False. Role строка
    НЕ трогается — вакансия вычисляется отдельно (is_role_vacant()).

    Returns:
        {"ok": bool, "changed": bool, "error": str | None}
    """
    existing = find_assignment_by_id(assignment_id)
    if not existing:
        return {"ok": False, "changed": False, "error": f"Assignment '{assignment_id}' не найден"}

    if existing["status"] == "ended":
        return {"ok": True, "changed": False, "error": None}

    if end_date and not _is_valid_date(end_date):
        return {"ok": False, "changed": False, "error": f"Недопустимый формат end_date '{end_date}'. Ожидается YYYY-MM-DD"}

    if not end_date:
        from datetime import datetime
        end_date = datetime.now().strftime("%Y-%m-%d")

    result = update_assignment(assignment_id, {"End Date": end_date, "Status": "ended"})
    return {"ok": result["ok"], "changed": result["changed"], "error": result["error"]}


_ASSIGNMENT_EDITABLE_FIELDS = (
    "Start Date", "End Date", "Assignment Type", "Status", "Notes",
)


def update_assignment(assignment_id: str, updates: dict) -> dict:
    """
    Обновить одно или несколько полей Assignment. Точечная запись только
    переданных колонок. Person ID/Role ID НЕ редактируемы после создания —
    "перевод" человека на другую роль моделируется как end_assignment()
    старой + assign_person_to_role() новой (сохраняет полную историю,
    см. get_assignment_history()), а не как in-place перезапись FK.

    Returns:
        {"ok": bool, "changed": bool, "updated_fields": tuple, "error": str | None}
    """
    if not assignment_id:
        return {"ok": False, "changed": False, "updated_fields": (), "error": "assignment_id не указан"}

    unknown = [k for k in updates if k not in _ASSIGNMENT_EDITABLE_FIELDS]
    if unknown:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимые поля для обновления: {', '.join(unknown)}",
        }

    if "Start Date" in updates and not _is_valid_date(updates["Start Date"]):
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый формат Start Date '{updates['Start Date']}'. Ожидается YYYY-MM-DD",
        }
    if "End Date" in updates and updates["End Date"] and not _is_valid_date(updates["End Date"]):
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый формат End Date '{updates['End Date']}'. Ожидается YYYY-MM-DD",
        }
    if "Assignment Type" in updates and updates["Assignment Type"] not in ASSIGNMENT_TYPE:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый Assignment Type '{updates['Assignment Type']}'. Допустимые значения: {', '.join(ASSIGNMENT_TYPE)}",
        }
    if "Status" in updates and updates["Status"] not in ASSIGNMENT_STATUS:
        return {
            "ok": False, "changed": False, "updated_fields": (),
            "error": f"Недопустимый статус '{updates['Status']}'. Допустимые значения: {', '.join(ASSIGNMENT_STATUS)}",
        }

    found = _find_assignment_row(assignment_id)
    if not found:
        return {"ok": False, "changed": False, "updated_fields": (), "error": f"Assignment '{assignment_id}' не найден"}
    row_num, current = found

    field_key_map = {
        "Start Date": "Start Date", "End Date": "End Date",
        "Assignment Type": "Assignment Type", "Status": "Status", "Notes": "Notes",
    }

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("person_role_assignments")
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

        log.info(f"update_assignment: {assignment_id} fields={updated_fields}")
        return {"ok": True, "changed": changed, "updated_fields": tuple(updated_fields), "error": None}
    except Exception as exc:
        log.error(f"update_assignment({assignment_id}) error: {exc}")
        return {"ok": False, "changed": False, "updated_fields": (), "error": str(exc)}
