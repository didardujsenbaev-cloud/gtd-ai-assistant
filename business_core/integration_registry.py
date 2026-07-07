"""
Integration Registry — технический реестр интеграций.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from business_core.models import Integration


VALID_STATUSES = ("active", "broken", "test", "planned", "paused")

# Начальные интеграции проекта (уже существующие в GTD-боте)
DEFAULT_INTEGRATIONS: list[dict] = [
    {
        "id": "INT-001",
        "service_a": "Telegram Bot",
        "service_b": "Google Sheets",
        "description": "GTD данные: Inbox, Projects, Next Actions, Horizons",
        "env_keys": ["GOOGLE_SHEET_ID", "GOOGLE_CREDENTIALS"],
        "status": "active",
        "code_location": "sheets.py",
    },
    {
        "id": "INT-002",
        "service_a": "Telegram Bot",
        "service_b": "Anthropic Claude",
        "description": "AI-обработка входящих сообщений, классификация GTD",
        "env_keys": ["ANTHROPIC_API_KEY"],
        "status": "active",
        "code_location": "inbox_processor.py",
    },
    {
        "id": "INT-003",
        "service_a": "Telegram Bot",
        "service_b": "Google Calendar",
        "description": "Синхронизация GTD-дедлайнов в Google Calendar",
        "env_keys": ["CALENDAR_ID", "READ_CALENDAR_IDS"],
        "status": "active",
        "code_location": "calendar_sync.py",
    },
    {
        "id": "INT-004",
        "service_a": "Telegram Bot",
        "service_b": "Google Drive",
        "description": "Загрузка PDF-документов и справочных материалов",
        "env_keys": ["GOOGLE_CREDENTIALS"],
        "status": "active",
        "code_location": "telegram_bot.py",
    },
    {
        "id": "INT-005",
        "service_a": "Telegram Bot",
        "service_b": "OpenAI Whisper",
        "description": "Транскрипция голосовых сообщений",
        "env_keys": ["OPENAI_API_KEY"],
        "status": "active",
        "code_location": "telegram_bot.py",
    },
]


def _next_int_id(existing_ids: list[str]) -> str:
    numbers = []
    for iid in existing_ids:
        match = re.match(r"INT-(\d+)", iid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"INT-{next_num:03d}"


def create_integration_record(
    service_a: str,
    service_b: str,
    description: str = "",
    integration_type: str = "API",
    env_keys: Optional[list[str]] = None,
    code_location: str = "",
    status: str = "planned",
    owner: str = "",
    existing_ids: Optional[list[str]] = None,
    **kwargs,
) -> Integration:
    """
    Создаёт объект Integration (без обращения к Google API).

    Args:
        service_a: Первый сервис (источник).
        service_b: Второй сервис (назначение).
        description: Описание что делает интеграция.
        integration_type: API / Webhook / Script / Manual / n8n / Make.
        env_keys: Имена переменных из .env файла.
        code_location: Файл или путь где находится код.
        status: active / broken / test / planned / paused.
        owner: Ответственный.
        existing_ids: Список существующих INT-IDs.

    Returns:
        Integration объект.
    """
    int_id = _next_int_id(existing_ids or [])

    return Integration(
        id=int_id,
        service_a=service_a,
        service_b=service_b,
        description=description,
        integration_type=integration_type,
        env_keys=env_keys or [],
        code_location=code_location,
        status=status,
        owner=owner,
        **kwargs,
    )


def validate_integration_record(record: Integration | dict) -> tuple[bool, list[str]]:
    """
    Проверяет корректность записи интеграции.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if isinstance(record, Integration):
        data = record.to_dict()
        int_type = record.integration_type
        status = record.status
    else:
        data = record
        int_type = data.get("integration_type", "")
        status = data.get("status", "")

    if not data.get("id"):
        errors.append("Отсутствует поле 'id'")
    elif not re.match(r"^INT-\d{3,}$", data["id"]):
        errors.append(f"Неверный формат id: '{data['id']}'. Ожидается INT-XXX")

    if not data.get("service_a"):
        errors.append("Отсутствует поле 'service_a'")

    if not data.get("service_b"):
        errors.append("Отсутствует поле 'service_b'")

    if int_type and int_type not in Integration.TYPES:
        errors.append(f"Неверный тип: '{int_type}'. Допустимые: {Integration.TYPES}")

    if status and status not in VALID_STATUSES:
        errors.append(f"Неверный статус: '{status}'. Допустимые: {VALID_STATUSES}")

    return (len(errors) == 0, errors)


def list_default_integrations() -> list[Integration]:
    """Возвращает список встроенных интеграций GTD-бота."""
    result = []
    for data in DEFAULT_INTEGRATIONS:
        obj = Integration(
            id=data["id"],
            service_a=data["service_a"],
            service_b=data["service_b"],
            description=data["description"],
            env_keys=data.get("env_keys", []),
            status=data["status"],
            code_location=data.get("code_location", ""),
        )
        result.append(obj)
    return result


def get_broken_integrations(integrations: list[Integration]) -> list[Integration]:
    """Возвращает интеграции со статусом 'broken'."""
    return [i for i in integrations if i.status == "broken"]


def format_integration_status(integrations: list[Integration]) -> str:
    """Форматирует статус интеграций для Telegram."""
    if not integrations:
        return "Интеграции не найдены."

    status_icons = {
        "active": "✅",
        "broken": "❌",
        "test": "🧪",
        "planned": "📋",
        "paused": "⏸",
    }

    lines = ["🔌 ИНТЕГРАЦИИ\n"]
    for intg in integrations:
        icon = status_icons.get(intg.status, "⚪")
        lines.append(f"{icon} [{intg.id}] {intg.service_a} ↔ {intg.service_b}")
        if intg.description:
            lines.append(f"   {intg.description}")
        lines.append("")
    return "\n".join(lines).strip()
