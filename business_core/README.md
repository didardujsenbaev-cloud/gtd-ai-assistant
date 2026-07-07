# Business Core

Модуль бизнес-операционки для **GTD OS**.

## Принцип

```
GTD — центр управления.
Business Core — отдельный модуль рядом.
Все задачи и проекты попадают обратно в GTD.
```

## Структура

```
business_core/
├── __init__.py              — точка входа, экспорт моделей
├── models.py                — dataclass-модели (BusinessArea, Service, Person, ...)
├── business_registry.py     — реестр бизнес-направлений
├── service_catalog.py       — каталог услуг
├── people_registry.py       — справочник людей
├── channel_registry.py      — каналы коммуникации
├── integration_registry.py  — технические интеграции
├── relationship_capital.py  — социальный капитал
└── business_builder.py      — конструктор нового бизнеса
```

## Модели

| Модель | ID-формат | Описание |
|--------|-----------|----------|
| `BusinessArea` | BIZ-001 | Бизнес-направление |
| `Service` | SVC-001 | Услуга |
| `Person` | PRS-001 | Человек |
| `Channel` | CH-001 | Канал коммуникации |
| `Integration` | INT-001 | Техническая интеграция |
| `RelationshipTouch` | TCH-001 | Касание с человеком |

## Быстрый старт

```python
from business_core.business_builder import create_business_area

result = create_business_area(
    name="Узаконение недвижимости",
    cities=["Алматы", "Астана"],
    owner="Дидар",
    priority="high",
)

print(result["summary"])
print(f"Папки: {result['folder_structure']}")
print(f"Проектов: {len(result['starter_projects'])}")
```

## Стандартная структура папок

Каждое новое бизнес-направление получает 12 папок:

```
01 Стратегия
02 Услуги
03 Процессы
04 Маркетинг
05 Продажи
06 Клиенты
07 Производство
08 Финансы
09 Команда
10 Автоматизация
11 Аналитика
12 Архив
```

## Стартовые проекты

При создании нового направления автоматически генерируется 7 проектов:

1. Описать услуги направления
2. Собрать текущих клиентов
3. Описать процесс продаж
4. Описать процесс производства
5. Настроить автоматизацию направления
6. Создать базу знаний направления
7. Настроить финансовый учёт направления

Каждый проект имеет первое Next Action.

## Фазы внедрения

- ✅ **Фаза 1** — локальные модели и структуры (без Google API)
- ⬜ **Фаза 2** — запись в Google Sheets (BUSINESS_CORE_SPREADSHEET_ID)
- ⬜ **Фаза 3** — Telegram-команды (/biz, /people, /services)
- ⬜ **Фаза 4** — Relationship Capital в утреннем дайджесте
- ⬜ **Фаза 5** — Автоматизации (Binotel, SendPulse, WABA)

## Файлы которые НЕ изменялись

- `telegram_bot.py` — не тронут
- `sheets.py` — не тронут
- `inbox_processor.py` — не тронут
- `calendar_sync.py` — не тронут
- `project_planner.py` — не тронут
