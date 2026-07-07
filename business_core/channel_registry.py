"""
Channel Registry — реестр каналов коммуникации.
"""

from __future__ import annotations

import re
from typing import Optional

from business_core.models import Channel


VALID_STATUSES = ("active", "paused", "test")


def _next_ch_id(existing_ids: list[str]) -> str:
    numbers = []
    for cid in existing_ids:
        match = re.match(r"CH-(\d+)", cid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"CH-{next_num:03d}"


def create_channel_record(
    channel_type: str,
    business_id: str,
    account: str = "",
    purpose: str = "",
    city: str = "",
    owner: str = "",
    status: str = "active",
    integration: str = "",
    existing_ids: Optional[list[str]] = None,
    **kwargs,
) -> Channel:
    """
    Создаёт объект Channel (без обращения к Google API).

    Args:
        channel_type: Binotel / WABA / Instagram / SendPulse / Telegram / Gmail / ...
        business_id: ID бизнес-направления (BIZ-XXX).
        account: Номер телефона, @handle, email и т.д.
        purpose: Для чего используется канал.
        city: Город.
        owner: Ответственный.
        status: active / paused / test.
        integration: С чем интегрирован.
        existing_ids: Список существующих CH-IDs.

    Returns:
        Channel объект.
    """
    ch_id = _next_ch_id(existing_ids or [])

    return Channel(
        id=ch_id,
        channel_type=channel_type,
        business_id=business_id,
        account=account,
        purpose=purpose,
        city=city,
        owner=owner,
        status=status,
        integration=integration,
        **kwargs,
    )


def validate_channel_record(record: Channel | dict) -> tuple[bool, list[str]]:
    """
    Проверяет корректность записи канала.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if isinstance(record, Channel):
        data = record.to_dict()
        channel_type = record.channel_type
    else:
        data = record
        channel_type = data.get("channel_type", "")

    if not data.get("id"):
        errors.append("Отсутствует поле 'id'")
    elif not re.match(r"^CH-\d{3,}$", data["id"]):
        errors.append(f"Неверный формат id: '{data['id']}'. Ожидается CH-XXX")

    if not data.get("business_id"):
        errors.append("Отсутствует поле 'business_id'")

    if not channel_type:
        errors.append("Отсутствует поле 'channel_type'")
    elif channel_type not in Channel.TYPES:
        errors.append(f"Неверный тип канала: '{channel_type}'. Допустимые: {Channel.TYPES}")

    if data.get("status") and data["status"] not in VALID_STATUSES:
        errors.append(f"Неверный статус: '{data['status']}'. Допустимые: {VALID_STATUSES}")

    return (len(errors) == 0, errors)


def get_broken_channels(channels: list[Channel]) -> list[Channel]:
    """Возвращает каналы со статусом 'paused'."""
    return [c for c in channels if c.status == "paused"]


def get_channels_by_business(channels: list[Channel], biz_id: str) -> list[Channel]:
    """Фильтрует каналы по бизнесу."""
    return [c for c in channels if c.business_id == biz_id]


def format_channel_list(channels: list[Channel]) -> str:
    """Форматирует список каналов для Telegram."""
    if not channels:
        return "Каналы не найдены."

    status_icons = {"active": "✅", "paused": "❌", "test": "🧪"}
    lines = ["📡 КАНАЛЫ КОММУНИКАЦИИ\n"]
    for ch in channels:
        icon = status_icons.get(ch.status, "⚪")
        lines.append(f"{icon} [{ch.id}] {ch.channel_type} — {ch.account or '—'}")
        if ch.purpose:
            lines.append(f"   {ch.purpose}")
        lines.append("")
    return "\n".join(lines).strip()
