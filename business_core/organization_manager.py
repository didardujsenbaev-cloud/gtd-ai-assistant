"""
Organization Manager — Department и Role (Phase 21B).

Организационная структура компании: Department (подразделение) и Role
(внутренняя должность). Реализует архитектуру Phase 20A -> 20A.6
(см. ARCHITECTURE.md, раздел "Organization Layer") в редакции критических
замечаний: Role не привязана к Business ID (глобальна для всей группы),
внешние подрядчики НЕ являются Role — они остаются в PEOPLE_REGISTRY
(External Party Layer).

Phase 21C добавит Role Function и Person Role Assignment в этот же модуль.
Phase 21F добавит Telegram-команды отдельным слоем поверх функций отсюда.

Только чтение/запись DEPARTMENT_REGISTRY и ROLE_REGISTRY. Единственная
внешняя FK-проверка — Business ID на Department (сверяется с BIZ_REGISTRY)
и Department ID на Role (сверяется с DEPARTMENT_REGISTRY, тем же модулем).
Head Role ID на Department намеренно НЕ валидируется при записи — вакантный
Department (без назначенного головы роли) — легитимное состояние, ссылка
может указывать на ещё не созданную Role (см. ARCHITECTURE.md).

Зависимости: только business_core.sheets (+ read-only чтение biz_registry
через find_row_by_id). GTD Core не импортируется — см.
ENGINEERING_STANDARDS.md, Layer Dependency Rules.
"""

from __future__ import annotations

import logging
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
