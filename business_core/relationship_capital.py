"""
Relationship Capital — управление социальным капиталом.
Активная система касаний поверх People Registry.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from business_core.models import Person, RelationshipTouch


TOUCH_RULES = {
    "hot":  {"max_days": 7,   "label": "горячий контакт"},
    "warm": {"max_days": 30,  "label": "тёплый контакт"},
    "cold": {"max_days": 90,  "label": "холодный контакт"},
}

TOUCH_TYPE_SUGGESTIONS = {
    "birthday":     ("поздравление", "Поздравить с днём рождения"),
    "overdue_hot":  ("сообщение",    "Написать — давно не общались"),
    "overdue_warm": ("звонок",       "Позвонить — поддержать контакт"),
    "follow_up":    ("сообщение",    "Follow-up по предыдущему разговору"),
    "introduce":    ("встреча",      "Познакомить с нужным человеком"),
    "info":         ("сообщение",    "Отправить полезную информацию"),
}


def _next_tch_id(existing_ids: list[str]) -> str:
    numbers = []
    for tid in existing_ids:
        match = re.match(r"TCH-(\d+)", tid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"TCH-{next_num:03d}"


def create_touch_record(
    person_id: str,
    touch_type: str,
    channel: str = "",
    summary: str = "",
    outcome: str = "",
    warmth_before: int = 5,
    warmth_after: int = 5,
    touch_date: Optional[str] = None,
    existing_ids: Optional[list[str]] = None,
) -> RelationshipTouch:
    """
    Создаёт запись о касании с человеком.

    Args:
        person_id: ID человека (PRS-XXX).
        touch_type: Тип касания из RelationshipTouch.TOUCH_TYPES.
        channel: Канал (WhatsApp / Telegram / Phone / встреча).
        summary: О чём говорили / что отправили.
        outcome: Результат / следующий шаг.
        warmth_before: Теплота до касания (1–10).
        warmth_after: Теплота после касания (1–10).
        touch_date: Дата в формате YYYY-MM-DD. По умолчанию — сегодня.
        existing_ids: Список существующих TCH-IDs.

    Returns:
        RelationshipTouch объект.
    """
    tch_id = _next_tch_id(existing_ids or [])
    actual_date = touch_date or datetime.now().strftime("%Y-%m-%d")

    return RelationshipTouch(
        id=tch_id,
        person_id=person_id,
        touch_date=actual_date,
        touch_type=touch_type,
        channel=channel,
        summary=summary,
        outcome=outcome,
        warmth_before=warmth_before,
        warmth_after=warmth_after,
    )


def suggest_next_touch(person: Person) -> dict:
    """
    Предлагает следующее касание для человека на основе его профиля.

    Логика:
    - Если скоро день рождения → поздравление
    - Если горячий контакт и давно не общались → написать
    - Если тёплый контакт и давно не общались → позвонить
    - Если есть outcome/follow-up → follow-up
    - По умолчанию → информация

    Returns:
        {
            "touch_type": str,
            "suggested_date": str (YYYY-MM-DD),
            "reason": str,
            "note": str,
            "priority": str (high/medium/low),
        }
    """
    today = date.today()
    result = {
        "touch_type": "сообщение",
        "suggested_date": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
        "reason": "плановое касание",
        "note": "",
        "priority": "low",
    }

    # Проверка дня рождения
    if person.birthday:
        try:
            month, day = map(int, person.birthday.split("-"))
            bday = date(today.year, month, day)
            if bday < today:
                bday = date(today.year + 1, month, day)
            days_to_bday = (bday - today).days
            if days_to_bday <= 7:
                touch_type, note = TOUCH_TYPE_SUGGESTIONS["birthday"]
                return {
                    "touch_type": touch_type,
                    "suggested_date": bday.strftime("%Y-%m-%d"),
                    "reason": f"день рождения через {days_to_bday} дн.",
                    "note": note,
                    "priority": "high",
                }
        except (ValueError, AttributeError):
            pass

    # Вычисление дней без контакта
    days_silent = None
    if person.last_contact_date:
        try:
            last = datetime.strptime(person.last_contact_date, "%Y-%m-%d").date()
            days_silent = (today - last).days
        except ValueError:
            pass

    rule = TOUCH_RULES.get(person.relationship_status, TOUCH_RULES["cold"])
    max_days = rule["max_days"]

    if days_silent is not None and days_silent > max_days:
        if person.relationship_status == "hot":
            touch_type, note = TOUCH_TYPE_SUGGESTIONS["overdue_hot"]
            priority = "high"
            days_ahead = 1
        elif person.relationship_status == "warm":
            touch_type, note = TOUCH_TYPE_SUGGESTIONS["overdue_warm"]
            priority = "medium"
            days_ahead = 3
        else:
            touch_type, note = TOUCH_TYPE_SUGGESTIONS["info"]
            priority = "low"
            days_ahead = 7

        return {
            "touch_type": touch_type,
            "suggested_date": (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d"),
            "reason": f"не общались {days_silent} дн. (норма: {max_days} дн.)",
            "note": note,
            "priority": priority,
        }

    # Если задан следующий шаг → возвращаем его
    if person.next_touch_date:
        return {
            "touch_type": person.next_touch_type or "сообщение",
            "suggested_date": person.next_touch_date,
            "reason": "запланированное касание",
            "note": person.next_touch_note or "",
            "priority": "medium",
        }

    return result


def get_daily_relationship_digest(people: list[Person]) -> str:
    """
    Формирует ежедневный дайджест для работы с контактами.

    Возвращает форматированный текст для Telegram.
    """
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")

    urgent = []     # сегодня / просрочено
    important = []  # hot-контакты давно без контакта
    regular = []    # запланированы

    for person in people:
        suggestion = suggest_next_touch(person)
        suggested = suggestion.get("suggested_date", "")
        priority = suggestion.get("priority", "low")

        if suggested <= today_str and priority == "high":
            urgent.append((person, suggestion))
        elif priority == "medium":
            important.append((person, suggestion))
        elif suggested == today_str:
            regular.append((person, suggestion))

    if not urgent and not important and not regular:
        return "✅ Сегодня нет срочных касаний. Хорошая работа!"

    lines = ["🤝 КАСАНИЯ НА СЕГОДНЯ\n"]

    if urgent:
        lines.append("🔴 СРОЧНО:")
        for person, sug in urgent[:5]:
            lines.append(f"  • {person.short_name or person.full_name} — {sug['reason']}")
            if sug.get("note"):
                lines.append(f"    → {sug['note']}")
        lines.append("")

    if important:
        lines.append("🟡 ВАЖНО:")
        for person, sug in important[:5]:
            lines.append(f"  • {person.short_name or person.full_name} — {sug['reason']}")
        lines.append("")

    if regular:
        lines.append("🟢 ЗАПЛАНИРОВАНО:")
        for person, sug in regular[:5]:
            lines.append(f"  • {person.short_name or person.full_name} ({sug['touch_type']})")

    return "\n".join(lines).strip()


def get_warm_contacts(people: list[Person], min_warmth: int = 7) -> list[Person]:
    """Возвращает тёплые контакты с теплотой >= min_warmth."""
    return [p for p in people if p.warmth >= min_warmth]


def get_overdue_contacts(people: list[Person], days_threshold: int = 30) -> list[Person]:
    """Возвращает контакты, с которыми давно не общались."""
    result = []
    today = date.today()
    for person in people:
        if not person.last_contact_date:
            continue
        try:
            last = datetime.strptime(person.last_contact_date, "%Y-%m-%d").date()
            if (today - last).days > days_threshold:
                result.append(person)
        except ValueError:
            continue
    return result
