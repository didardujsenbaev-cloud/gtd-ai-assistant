"""
Business Registry — реестр бизнес-направлений.
Работает локально (без Google API) на этапе Фазы 1.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from business_core.models import BusinessArea


# ─────────────────────────────────────────────────────────────
# Константы
# ─────────────────────────────────────────────────────────────

VALID_STATUSES = ("active", "test", "hold", "archived")
VALID_PRIORITIES = ("high", "medium", "low")

DEFAULT_BUSINESSES: list[dict] = [
    {
        "id": "BIZ-001",
        "name": "Узаконение недвижимости",
        "slug": "legalization",
        "status": "active",
        "description": "Узаконивание объектов недвижимости: гаражи, дома, коммерция",
        "cities": ["Алматы", "Астана", "Шымкент"],
        "owner": "Дидар",
        "priority": "high",
    },
    {
        "id": "BIZ-002",
        "name": "Визы и документы",
        "slug": "visas",
        "status": "active",
        "description": "Оформление виз, нотариальные переводы, справки",
        "cities": ["Алматы"],
        "owner": "Дидар",
        "priority": "medium",
    },
    {
        "id": "BIZ-003",
        "name": "Коучинг",
        "slug": "coaching",
        "status": "active",
        "description": "Стратегические сессии, менторинг, воркшопы",
        "cities": ["Алматы", "Онлайн"],
        "owner": "Дидар",
        "priority": "medium",
    },
    {
        "id": "BIZ-004",
        "name": "Инвестиции",
        "slug": "investments",
        "status": "hold",
        "description": "Инвестиции в недвижимость и бизнес",
        "cities": ["Алматы"],
        "owner": "Дидар",
        "priority": "low",
    },
    {
        "id": "BIZ-005",
        "name": "Автоматизация бизнеса",
        "slug": "automation",
        "status": "test",
        "description": "Telegram-боты, AI-интеграции, автоматизация процессов",
        "cities": ["Алматы", "Онлайн"],
        "owner": "Дидар",
        "priority": "medium",
    },
]


# ─────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Генерирует slug из названия: 'Узаконение' → 'uzakonenie'."""
    transliteration = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya", " ": "_",
    }
    slug = name.lower()
    result = ""
    for char in slug:
        result += transliteration.get(char, char)
    result = re.sub(r"[^a-z0-9_]", "", result)
    result = re.sub(r"_+", "_", result).strip("_")
    return result or "business"


def _next_biz_id(existing_ids: list[str]) -> str:
    """Генерирует следующий ID: ['BIZ-001', 'BIZ-002'] → 'BIZ-003'."""
    numbers = []
    for bid in existing_ids:
        match = re.match(r"BIZ-(\d+)", bid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"BIZ-{next_num:03d}"


# ─────────────────────────────────────────────────────────────
# Основные функции
# ─────────────────────────────────────────────────────────────

def create_business_record(
    name: str,
    cities: Optional[list[str]] = None,
    owner: str = "",
    priority: str = "medium",
    status: str = "test",
    description: str = "",
    existing_ids: Optional[list[str]] = None,
    **kwargs,
) -> BusinessArea:
    """
    Создаёт объект BusinessArea (без обращения к Google API).

    Args:
        name: Название бизнес-направления.
        cities: Список городов. По умолчанию ["Алматы"].
        owner: Ответственный.
        priority: high / medium / low.
        status: active / test / hold / archived.
        description: Краткое описание.
        existing_ids: Список уже существующих BIZ-IDs для генерации следующего.
        **kwargs: Дополнительные поля BusinessArea.

    Returns:
        BusinessArea объект.
    """
    if cities is None:
        cities = ["Алматы"]

    biz_id = _next_biz_id(existing_ids or [])
    slug = kwargs.pop("slug", _slugify(name))

    return BusinessArea(
        id=biz_id,
        name=name,
        slug=slug,
        status=status,
        description=description,
        cities=cities,
        owner=owner,
        priority=priority,
        **kwargs,
    )


def list_default_businesses() -> list[BusinessArea]:
    """Возвращает список стандартных бизнес-направлений."""
    result = []
    for data in DEFAULT_BUSINESSES:
        biz = BusinessArea(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            status=data["status"],
            description=data["description"],
            cities=data["cities"],
            owner=data["owner"],
            priority=data["priority"],
        )
        result.append(biz)
    return result


def validate_business_record(record: BusinessArea | dict) -> tuple[bool, list[str]]:
    """
    Проверяет корректность записи бизнеса.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if isinstance(record, BusinessArea):
        data = record.to_dict()
    else:
        data = record

    if not data.get("id"):
        errors.append("Отсутствует поле 'id'")
    elif not re.match(r"^BIZ-\d{3,}$", data["id"]):
        errors.append(f"Неверный формат id: '{data['id']}'. Ожидается BIZ-XXX")

    if not data.get("name") or not str(data["name"]).strip():
        errors.append("Отсутствует или пустое поле 'name'")

    if data.get("status") and data["status"] not in VALID_STATUSES:
        errors.append(f"Неверный статус: '{data['status']}'. Допустимые: {VALID_STATUSES}")

    if data.get("priority") and data["priority"] not in VALID_PRIORITIES:
        errors.append(f"Неверный приоритет: '{data['priority']}'. Допустимые: {VALID_PRIORITIES}")

    if not data.get("cities"):
        errors.append("Поле 'cities' пустое — укажите хотя бы один город")

    return (len(errors) == 0, errors)


def get_business_by_id(biz_id: str, businesses: list[BusinessArea]) -> Optional[BusinessArea]:
    """Находит бизнес по ID в списке."""
    for biz in businesses:
        if biz.id == biz_id:
            return biz
    return None


def filter_businesses(
    businesses: list[BusinessArea],
    status: Optional[str] = None,
    city: Optional[str] = None,
    owner: Optional[str] = None,
) -> list[BusinessArea]:
    """Фильтрует список бизнесов по статусу, городу или ответственному."""
    result = businesses
    if status:
        result = [b for b in result if b.status == status]
    if city:
        result = [b for b in result if city in b.cities]
    if owner:
        result = [b for b in result if owner.lower() in b.owner.lower()]
    return result


def format_business_list(businesses: list[BusinessArea]) -> str:
    """Форматирует список бизнесов для отображения в Telegram."""
    if not businesses:
        return "Нет бизнес-направлений."

    status_icons = {
        "active": "🟢",
        "test": "🟡",
        "hold": "⏸",
        "archived": "📦",
    }

    lines = ["🏢 БИЗНЕС-НАПРАВЛЕНИЯ\n"]
    for biz in businesses:
        icon = status_icons.get(biz.status, "⚪")
        cities_str = ", ".join(biz.cities) if biz.cities else "—"
        lines.append(f"{icon} [{biz.id}] {biz.name}")
        lines.append(f"   Города: {cities_str} · Приоритет: {biz.priority}")
        if biz.description:
            lines.append(f"   {biz.description}")
        lines.append("")

    return "\n".join(lines).strip()
