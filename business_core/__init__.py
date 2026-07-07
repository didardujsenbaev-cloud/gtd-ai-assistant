"""
Business Core — модуль бизнес-операционки для GTD OS.

Принцип: GTD остаётся центром. Business Core — отдельный модуль рядом.
Все задачи и проекты в итоге попадают обратно в GTD.

Не импортирует из: telegram_bot, sheets, calendar_sync, inbox_processor, project_planner.
Подключается к GTD только через явные интеграционные функции в business_builder.py.
"""

__version__ = "1.0.0"
__author__ = "GTD OS — Business Core"

from business_core.models import (
    BusinessArea,
    Service,
    Person,
    Channel,
    Integration,
    RelationshipTouch,
)

__all__ = [
    "BusinessArea",
    "Service",
    "Person",
    "Channel",
    "Integration",
    "RelationshipTouch",
]
