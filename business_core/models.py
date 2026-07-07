"""
Dataclass-модели для Business Core.
Не зависят от внешних API — только структуры данных.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────
# BusinessArea — бизнес-направление
# ─────────────────────────────────────────────────────────────

@dataclass
class BusinessArea:
    """Единица бизнес-направления в реестре."""

    id: str                                     # BIZ-001
    name: str                                   # "Узаконение недвижимости"
    slug: str                                   # "legalization"
    status: str = "test"                        # active / test / hold / archived
    description: str = ""
    cities: list[str] = field(default_factory=list)       # ["Алматы", "Астана"]
    owner: str = ""
    priority: str = "medium"                    # high / medium / low

    # Интеграции (заполняются позже)
    google_drive_folder: str = ""
    google_sheet_id: str = ""
    gtd_project_id: str = ""
    sendpulse_account: str = ""
    binotel_account: str = ""
    waba_number: str = ""
    instagram_handle: str = ""
    telegram_channel: str = ""
    crm_link: str = ""
    comment: str = ""

    # Структура папок (генерируется при создании)
    folder_structure: list[str] = field(default_factory=list)

    # Стартовые проекты (генерируются при создании)
    starter_projects: list[dict] = field(default_factory=list)

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "description": self.description,
            "cities": self.cities,
            "owner": self.owner,
            "priority": self.priority,
            "google_drive_folder": self.google_drive_folder,
            "google_sheet_id": self.google_sheet_id,
            "gtd_project_id": self.gtd_project_id,
            "sendpulse_account": self.sendpulse_account,
            "binotel_account": self.binotel_account,
            "waba_number": self.waba_number,
            "instagram_handle": self.instagram_handle,
            "telegram_channel": self.telegram_channel,
            "crm_link": self.crm_link,
            "comment": self.comment,
            "folder_structure": self.folder_structure,
            "starter_projects": self.starter_projects,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ─────────────────────────────────────────────────────────────
# Service — услуга в каталоге
# ─────────────────────────────────────────────────────────────

@dataclass
class Service:
    """Услуга в каталоге бизнес-направления."""

    id: str                                     # SVC-001
    business_id: str                            # BIZ-001
    name: str
    slug: str = ""
    status: str = "draft"                       # active / draft / paused
    city: str = ""
    price_min: float = 0.0
    price_max: float = 0.0
    currency: str = "KZT"
    duration_days: str = ""                     # "30–45 дней"
    description: str = ""

    stages: list[str] = field(default_factory=list)       # этапы производства
    docs_from_client: list[str] = field(default_factory=list)
    docs_we_prepare: list[str] = field(default_factory=list)
    checklist_production: list[str] = field(default_factory=list)
    checklist_closing: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    templates_url: str = ""
    instruction_url: str = ""
    comment: str = ""

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "business_id": self.business_id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "city": self.city,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "currency": self.currency,
            "duration_days": self.duration_days,
            "description": self.description,
            "stages": self.stages,
            "docs_from_client": self.docs_from_client,
            "docs_we_prepare": self.docs_we_prepare,
            "checklist_production": self.checklist_production,
            "checklist_closing": self.checklist_closing,
            "risks": self.risks,
            "templates_url": self.templates_url,
            "instruction_url": self.instruction_url,
            "comment": self.comment,
            "created_at": self.created_at,
        }


# ─────────────────────────────────────────────────────────────
# Person — человек в реестре
# ─────────────────────────────────────────────────────────────

@dataclass
class Person:
    """Запись в People Registry."""

    id: str                                     # PRS-001
    full_name: str
    short_name: str = ""
    phone: str = ""
    phone2: str = ""
    whatsapp: str = ""
    telegram: str = ""
    email: str = ""
    city: str = ""
    company: str = ""
    position: str = ""

    person_type: str = "знакомый"               # клиент/подрядчик/сотрудник/партнер/госорган/знакомый/инвестор
    person_subtype: str = ""
    businesses: list[str] = field(default_factory=list)   # ["BIZ-001", "BIZ-002"]
    trust_level: int = 3                        # 1–5
    source: str = ""

    can_help_me_with: str = ""
    i_can_help_with: str = ""
    knows_people: str = ""
    specialization: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    birthday: str = ""                          # MM-DD
    important_events: str = ""
    first_contact_date: Optional[str] = None
    last_contact_date: Optional[str] = None
    last_contact_channel: str = ""              # WhatsApp / Telegram / Phone / встреча
    history_notes: str = ""

    next_touch_date: Optional[str] = None
    next_touch_type: str = ""                   # звонок/встреча/сообщение/поздравление
    next_touch_note: str = ""
    relationship_status: str = "cold"           # cold / warm / hot / paused
    warmth: int = 5                             # 1–10

    comment: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "full_name": self.full_name,
            "short_name": self.short_name,
            "phone": self.phone,
            "telegram": self.telegram,
            "city": self.city,
            "person_type": self.person_type,
            "businesses": self.businesses,
            "trust_level": self.trust_level,
            "can_help_me_with": self.can_help_me_with,
            "i_can_help_with": self.i_can_help_with,
            "last_contact_date": self.last_contact_date,
            "next_touch_date": self.next_touch_date,
            "relationship_status": self.relationship_status,
            "warmth": self.warmth,
            "created_at": self.created_at,
        }


# ─────────────────────────────────────────────────────────────
# Channel — канал коммуникации
# ─────────────────────────────────────────────────────────────

@dataclass
class Channel:
    """Канал коммуникации в реестре каналов."""

    TYPES = (
        "Binotel", "WABA", "Instagram", "SendPulse",
        "Telegram", "Gmail", "Google Forms", "Сайт", "Рекомендации", "Другое",
    )

    id: str                                     # CH-001
    channel_type: str                           # из TYPES
    business_id: str                            # BIZ-001
    city: str = ""
    account: str = ""                           # номер / @handle / email
    purpose: str = ""
    audience: str = ""
    owner: str = ""
    status: str = "active"                      # active / paused / test
    integration: str = ""
    metrics: str = ""
    comment: str = ""

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_type": self.channel_type,
            "business_id": self.business_id,
            "city": self.city,
            "account": self.account,
            "purpose": self.purpose,
            "owner": self.owner,
            "status": self.status,
            "integration": self.integration,
            "comment": self.comment,
            "created_at": self.created_at,
        }


# ─────────────────────────────────────────────────────────────
# Integration — техническая интеграция
# ─────────────────────────────────────────────────────────────

@dataclass
class Integration:
    """Запись в реестре интеграций."""

    TYPES = ("API", "Webhook", "Script", "Manual", "n8n", "Make")
    STATUSES = ("active", "broken", "test", "planned", "paused")

    id: str                                     # INT-001
    service_a: str                              # "Telegram Bot"
    service_b: str                              # "Google Sheets"
    integration_type: str = "API"               # из TYPES
    businesses: list[str] = field(default_factory=list)
    description: str = ""
    api_endpoint: str = ""
    code_location: str = ""
    env_keys: list[str] = field(default_factory=list)     # имена переменных в .env
    status: str = "planned"                     # из STATUSES
    last_checked: Optional[str] = None
    how_to_verify: str = ""
    common_errors: str = ""
    error_solutions: str = ""
    owner: str = ""
    docs_url: str = ""
    comment: str = ""

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_a": self.service_a,
            "service_b": self.service_b,
            "integration_type": self.integration_type,
            "businesses": self.businesses,
            "description": self.description,
            "status": self.status,
            "env_keys": self.env_keys,
            "owner": self.owner,
            "created_at": self.created_at,
        }


# ─────────────────────────────────────────────────────────────
# RelationshipTouch — касание / взаимодействие
# ─────────────────────────────────────────────────────────────

@dataclass
class RelationshipTouch:
    """Одно взаимодействие с человеком (касание)."""

    TOUCH_TYPES = (
        "звонок", "встреча", "сообщение", "поздравление",
        "знакомство", "информация", "просьба", "помощь",
    )

    id: str                                     # TCH-001
    person_id: str                              # PRS-001
    touch_date: str                             # YYYY-MM-DD
    touch_type: str = "сообщение"               # из TOUCH_TYPES
    channel: str = ""                           # WhatsApp / Telegram / Phone
    summary: str = ""                           # о чём говорили / что отправили
    outcome: str = ""                           # результат / следующий шаг
    warmth_before: int = 5                      # теплота до касания (1–10)
    warmth_after: int = 5                       # теплота после

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "person_id": self.person_id,
            "touch_date": self.touch_date,
            "touch_type": self.touch_type,
            "channel": self.channel,
            "summary": self.summary,
            "outcome": self.outcome,
            "warmth_before": self.warmth_before,
            "warmth_after": self.warmth_after,
            "created_at": self.created_at,
        }
