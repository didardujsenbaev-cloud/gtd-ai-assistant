"""
People Registry — единый справочник людей.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from business_core.models import Person


VALID_TYPES = (
    "клиент", "подрядчик", "сотрудник", "партнер",
    "госорган", "знакомый", "инвестор",
)
VALID_STATUSES = ("cold", "warm", "hot", "paused")


def _next_prs_id(existing_ids: list[str]) -> str:
    numbers = []
    for pid in existing_ids:
        match = re.match(r"PRS-(\d+)", pid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"PRS-{next_num:03d}"


def create_person_record(
    full_name: str,
    phone: str = "",
    city: str = "",
    person_type: str = "знакомый",
    businesses: Optional[list[str]] = None,
    trust_level: int = 3,
    existing_ids: Optional[list[str]] = None,
    **kwargs,
) -> Person:
    """
    Создаёт объект Person (без обращения к Google API).

    Args:
        full_name: Полное ФИО.
        phone: Основной телефон.
        city: Город.
        person_type: клиент/подрядчик/сотрудник/партнер/госорган/знакомый/инвестор.
        businesses: Список BIZ-IDs связанных бизнесов.
        trust_level: Уровень доверия 1–5.
        existing_ids: Список существующих PRS-IDs.

    Returns:
        Person объект.
    """
    prs_id = _next_prs_id(existing_ids or [])
    short_name = kwargs.pop("short_name", full_name.split()[0] if full_name else "")

    return Person(
        id=prs_id,
        full_name=full_name,
        short_name=short_name,
        phone=phone,
        city=city,
        person_type=person_type,
        businesses=businesses or [],
        trust_level=trust_level,
        first_contact_date=datetime.now().strftime("%Y-%m-%d"),
        **kwargs,
    )


def validate_person_record(record: Person | dict) -> tuple[bool, list[str]]:
    """
    Проверяет корректность записи человека.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []

    if isinstance(record, Person):
        data = record.to_dict()
        full_data = record
    else:
        data = record
        full_data = data

    if not data.get("id"):
        errors.append("Отсутствует поле 'id'")
    elif not re.match(r"^PRS-\d{3,}$", data["id"]):
        errors.append(f"Неверный формат id: '{data['id']}'. Ожидается PRS-XXX")

    if not data.get("full_name") or not str(data["full_name"]).strip():
        errors.append("Отсутствует или пустое поле 'full_name'")

    if isinstance(full_data, Person):
        person_type = full_data.person_type
        trust_level = full_data.trust_level
        relationship_status = full_data.relationship_status
        warmth = full_data.warmth
    else:
        person_type = data.get("person_type", "")
        trust_level = data.get("trust_level", 3)
        relationship_status = data.get("relationship_status", "")
        warmth = data.get("warmth", 5)

    if person_type and person_type not in VALID_TYPES:
        errors.append(f"Неверный тип: '{person_type}'. Допустимые: {VALID_TYPES}")

    if not isinstance(trust_level, int) or trust_level < 1 or trust_level > 5:
        errors.append(f"trust_level должен быть числом от 1 до 5, получено: {trust_level}")

    if relationship_status and relationship_status not in VALID_STATUSES:
        errors.append(f"Неверный relationship_status: '{relationship_status}'")

    if not isinstance(warmth, int) or warmth < 1 or warmth > 10:
        errors.append(f"warmth должен быть числом от 1 до 10, получено: {warmth}")

    return (len(errors) == 0, errors)


def get_people_to_touch(
    people: list[Person],
    target_date: Optional[str] = None,
) -> list[Person]:
    """Возвращает людей, с которыми нужно связаться сегодня (или на указанную дату)."""
    check_date = target_date or datetime.now().strftime("%Y-%m-%d")
    return [p for p in people if p.next_touch_date == check_date]


def get_upcoming_birthdays(people: list[Person], days_ahead: int = 7) -> list[Person]:
    """Возвращает людей с днём рождения в ближайшие N дней."""
    today = date.today()
    result = []
    for person in people:
        if not person.birthday:
            continue
        try:
            month, day = map(int, person.birthday.split("-"))
            bday_this_year = date(today.year, month, day)
            if bday_this_year < today:
                bday_this_year = date(today.year + 1, month, day)
            delta = (bday_this_year - today).days
            if 0 <= delta <= days_ahead:
                result.append(person)
        except (ValueError, AttributeError):
            continue
    return result


def days_since_contact(person: Person) -> Optional[int]:
    """Возвращает количество дней с последнего контакта."""
    if not person.last_contact_date:
        return None
    try:
        last = datetime.strptime(person.last_contact_date, "%Y-%m-%d").date()
        return (date.today() - last).days
    except ValueError:
        return None


def format_person_card(person: Person) -> str:
    """Форматирует карточку человека для Telegram."""
    lines = [
        f"👤 [{person.id}] {person.full_name}",
        f"Тип: {person.person_type} · Доверие: {'⭐' * person.trust_level}",
    ]
    if person.phone:
        lines.append(f"📞 {person.phone}")
    if person.telegram:
        lines.append(f"💬 {person.telegram}")
    if person.city:
        lines.append(f"📍 {person.city}")
    if person.can_help_me_with:
        lines.append(f"\n✅ Полезен: {person.can_help_me_with}")
    if person.next_touch_date:
        lines.append(f"\n📅 Следующее касание: {person.next_touch_date} ({person.next_touch_type})")
        if person.next_touch_note:
            lines.append(f"   {person.next_touch_note}")
    days = days_since_contact(person)
    if days is not None:
        lines.append(f"⏱ Последний контакт: {days} дн. назад")
    return "\n".join(lines)
