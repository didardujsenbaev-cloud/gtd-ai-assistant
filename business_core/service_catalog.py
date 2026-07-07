"""
Service Catalog — каталог услуг бизнес-направлений.
"""

from __future__ import annotations

import re
from typing import Optional

from business_core.models import Service


VALID_STATUSES = ("active", "draft", "paused")


def _next_svc_id(existing_ids: list[str]) -> str:
    numbers = []
    for sid in existing_ids:
        match = re.match(r"SVC-(\d+)", sid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"SVC-{next_num:03d}"


def create_service_record(
    business_id: str,
    name: str,
    city: str = "",
    price_min: float = 0.0,
    price_max: float = 0.0,
    duration_days: str = "",
    description: str = "",
    stages: Optional[list[str]] = None,
    docs_from_client: Optional[list[str]] = None,
    docs_we_prepare: Optional[list[str]] = None,
    checklist_production: Optional[list[str]] = None,
    checklist_closing: Optional[list[str]] = None,
    risks: Optional[list[str]] = None,
    status: str = "draft",
    existing_ids: Optional[list[str]] = None,
    **kwargs,
) -> Service:
    """
    Создаёт объект Service (без обращения к Google API).

    Args:
        business_id: ID бизнес-направления (BIZ-XXX).
        name: Название услуги.
        city: Город или "все города".
        price_min/price_max: Диапазон цен в KZT.
        duration_days: Срок выполнения (строка, например "30–45 дней").
        stages: Этапы производства (список строк).
        docs_from_client: Документы, которые предоставляет клиент.
        docs_we_prepare: Документы, которые готовим мы.
        checklist_production: Чек-лист производства.
        checklist_closing: Чек-лист закрытия.
        risks: Типичные риски.
        status: draft / active / paused.
        existing_ids: Список существующих SVC-IDs.

    Returns:
        Service объект.
    """
    svc_id = _next_svc_id(existing_ids or [])

    return Service(
        id=svc_id,
        business_id=business_id,
        name=name,
        city=city,
        price_min=price_min,
        price_max=price_max,
        duration_days=duration_days,
        description=description,
        stages=stages or [],
        docs_from_client=docs_from_client or [],
        docs_we_prepare=docs_we_prepare or [],
        checklist_production=checklist_production or [],
        checklist_closing=checklist_closing or [],
        risks=risks or [],
        status=status,
        **kwargs,
    )


def validate_service_record(record: Service | dict) -> tuple[bool, list[str]]:
    """
    Проверяет корректность записи услуги.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if isinstance(record, Service):
        data = record.to_dict()
    else:
        data = record

    if not data.get("id"):
        errors.append("Отсутствует поле 'id'")
    elif not re.match(r"^SVC-\d{3,}$", data["id"]):
        errors.append(f"Неверный формат id: '{data['id']}'. Ожидается SVC-XXX")

    if not data.get("business_id"):
        errors.append("Отсутствует поле 'business_id'")
    elif not re.match(r"^BIZ-\d{3,}$", data["business_id"]):
        errors.append(f"Неверный формат business_id: '{data['business_id']}'")

    if not data.get("name") or not str(data["name"]).strip():
        errors.append("Отсутствует или пустое поле 'name'")

    if data.get("status") and data["status"] not in VALID_STATUSES:
        errors.append(f"Неверный статус: '{data['status']}'. Допустимые: {VALID_STATUSES}")

    price_min = data.get("price_min", 0)
    price_max = data.get("price_max", 0)
    if price_min < 0 or price_max < 0:
        errors.append("Цены не могут быть отрицательными")
    if price_max > 0 and price_min > price_max:
        errors.append(f"price_min ({price_min}) больше price_max ({price_max})")

    return (len(errors) == 0, errors)


def get_service_summary(service: Service) -> str:
    """Форматирует карточку услуги для Telegram."""
    price_str = ""
    if service.price_min and service.price_max:
        price_str = f"{service.price_min:,.0f}–{service.price_max:,.0f} {service.currency}"
    elif service.price_min:
        price_str = f"от {service.price_min:,.0f} {service.currency}"

    lines = [
        f"📋 [{service.id}] {service.name}",
        f"Бизнес: {service.business_id} · Статус: {service.status}",
    ]
    if service.city:
        lines.append(f"Город: {service.city}")
    if price_str:
        lines.append(f"Цена: {price_str}")
    if service.duration_days:
        lines.append(f"Срок: {service.duration_days}")
    if service.description:
        lines.append(f"\n{service.description}")
    if service.stages:
        lines.append(f"\nЭтапы ({len(service.stages)}):")
        for i, stage in enumerate(service.stages, 1):
            lines.append(f"  {i}. {stage}")
    if service.risks:
        lines.append(f"\n⚠️ Риски: {'; '.join(service.risks)}")

    return "\n".join(lines)
