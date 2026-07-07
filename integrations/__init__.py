"""
Integrations — адаптеры внешних сервисов для GTD OS + Business Core.

Принцип:
  Каждый адаптер изолирован. Он не знает о других адаптерах.
  Все адаптеры получают данные из Business Core и отдают результаты назад.
  Telegram-бот не вызывается из адаптеров напрямую.

Порядок внедрения (из BUSINESS_CORE_PLAN.md):
  Фаза 3:  google_drive_adapter.py   ← сейчас
  Фаза 6:  sendpulse_adapter.py
  Фаза 6:  binotel_adapter.py
  Фаза 6:  waba_adapter.py
  Фаза 6:  instagram_adapter.py
  Позже:   google_calendar_adapter.py
  Позже:   integration_router.py
"""

__version__ = "1.0.0"
