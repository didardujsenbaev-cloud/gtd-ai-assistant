# Business Core — Архитектура расширения GTD OS

> Версия: 1.0 — Проектный документ (без кода)  
> Дата: 07.07.2026  
> Принцип: GTD — центр. Business Core — отдельный модуль рядом.

---

## Общая архитектура

```
┌─────────────────────────────────────────────────────────┐
│                    ЛИЧНЫЙ GTD (существующий)             │
│  telegram_bot.py  •  sheets.py  •  inbox_processor.py   │
│  Inbox → Проекты → Next Actions → Горизонты → Архив     │
└────────────────────┬────────────────────────────────────┘
                     │ задачи и проекты ↕
┌────────────────────▼────────────────────────────────────┐
│                   BUSINESS CORE (новый модуль)           │
│                                                          │
│  Business Registry   Service Catalog   People Registry  │
│  Channel Registry    Integration Reg.  Rel. Capital     │
│  Business Branches   Business Builder                   │
└─────────────────────────────────────────────────────────┘
                     │ данные ↕
┌────────────────────▼────────────────────────────────────┐
│               GOOGLE SHEETS (отдельная таблица)          │
│          BUSINESS_CORE_SPREADSHEET_ID                   │
└─────────────────────────────────────────────────────────┘
```

**Главный принцип потока данных:**
```
Бизнес-событие → Business Core → GTD Inbox → AI → Projects/Actions
```

---

## Модуль 1: Business Registry (Реестр бизнесов)

### Назначение
Единая точка истины о всех бизнес-направлениях. Отвечает на вопрос: "какие у меня бизнесы и в каком они состоянии?"

### Структура листа `BIZ_REGISTRY`

| Колонка | Тип | Описание |
|---------|-----|----------|
| ID | `BIZ-001` | Уникальный ID бизнеса |
| Название | текст | Полное название |
| Slug | `legalization` | Короткий код (для API/папок) |
| Статус | `active/test/hold/archived` | Текущий статус |
| Описание | текст | Чем занимается бизнес |
| Города | через запятую | Алматы, Астана, Шымкент |
| Ответственный | текст | ФИО или Telegram-ник |
| Приоритет | `1/2/3` | Приоритет для внимания |
| Дата старта | YYYY-MM-DD | Когда запущен |
| Google Drive папка | URL | Ссылка на папку |
| Google Sheet | URL | Операционная таблица |
| GTD Project ID | `PRJ-XXX` | Связь с GTD |
| SendPulse | текст | Аккаунт/организация |
| Binotel | текст | Номера/аккаунт |
| WABA | текст | Номер WhatsApp Business |
| Instagram | `@handle` | Аккаунт |
| Telegram | `@channel` | Канал/группа |
| CRM | текст | Какая CRM и ссылка |
| Комментарий | текст | Свободные заметки |
| Последнее обновление | YYYY-MM-DD | |

### Бизнес-направления (начальные данные)

| ID | Название | Slug | Статус |
|----|----------|------|--------|
| BIZ-001 | Узаконение недвижимости | legalization | active |
| BIZ-002 | Визы и документы | visas | active |
| BIZ-003 | Коучинг | coaching | active |
| BIZ-004 | Инвестиции | investments | hold |
| BIZ-005 | Автоматизация бизнеса | automation | test |

### Связь с GTD
- Каждый бизнес = одна Зона ответственности H2 в GTD
- Смена статуса бизнеса → напоминание проверить связанные проекты в GTD
- `GTD Project ID` — прямая ссылка на управляющий проект

---

## Модуль 2: Service Catalog (Каталог услуг)

### Назначение
Структурированное описание каждой услуги. Отвечает на вопрос: "что именно мы продаём и как это делается?"

### Структура листа `SERVICE_CATALOG`

| Колонка | Тип | Описание |
|---------|-----|----------|
| ID | `SVC-001` | Уникальный ID услуги |
| Бизнес ID | `BIZ-001` | Ссылка на бизнес |
| Название услуги | текст | Полное название |
| Slug | `garage-legalization` | Короткий код |
| Статус | `active/draft/paused` | |
| Город | текст | Или "все города" |
| Цена мин. | число | Минимальная цена (KZT) |
| Цена макс. | число | Максимальная цена |
| Срок выполнения | текст | "30–45 дней" |
| Описание | текст | Что входит в услугу |

**Следующий блок — этапы производства:**

| Колонка | Описание |
|---------|----------|
| Этап 1 | Название этапа |
| Этап 2 | |
| ... | до 10 этапов |
| Этап 10 | |

**Документы:**

| Колонка | Описание |
|---------|----------|
| Документы от клиента | Перечень через ; |
| Документы которые готовим мы | Перечень через ; |

**Чек-листы:**

| Колонка | Описание |
|---------|----------|
| Чек-лист производства | Шаги через ; |
| Чек-лист закрытия | Финальные шаги через ; |
| Риски | Типичные проблемы через ; |
| Ссылка на шаблоны | URL Google Drive |
| Ссылка на инструкцию | URL |
| Комментарий | |

### Связь с GTD
- Каждая услуга → шаблон проекта в GTD
- При создании сделки по услуге → автоматически создаётся проект в GTD с этапами как подзадачами
- Чек-листы → становятся Next Actions в GTD

### Пример: Услуга "Узаконивание гаража"
```
SVC-003 | BIZ-001 | Узаконивание гаража | garage-legalization | active
Цена: 180 000 – 250 000 KZT | Срок: 30–45 дней
Этапы:
  1. Выезд и обмеры объекта
  2. Подготовка технического паспорта
  3. Подача в ЦОН
  4. Получение акта ввода
  5. Регистрация в ЕГРН
Документы от клиента: Удостоверение личности; Правоустанавливающий документ; ...
Риски: Самовольное строительство; Долги по земле; Ограничения по зонированию
```

---

## Модуль 3: People Registry (Реестр людей)

### Назначение
Единый справочник всех людей в орбите бизнеса. CRM-слой на уровне личных отношений. Отвечает на вопрос: "кто эти люди и как я с ними работаю?"

### Структура листа `PEOPLE_REGISTRY`

**Базовая информация:**

| Колонка | Тип | Описание |
|---------|-----|----------|
| ID | `PRS-001` | Уникальный ID |
| ФИО | текст | Полное имя |
| Имя (короткое) | текст | Для обращений |
| Телефон | текст | Основной |
| Телефон 2 | текст | |
| WhatsApp | текст | |
| Telegram | `@handle` | |
| Email | текст | |
| Город | текст | |
| Компания | текст | |
| Должность | текст | |

**Классификация:**

| Колонка | Значения |
|---------|----------|
| Тип | `клиент / подрядчик / сотрудник / партнер / госорган / знакомый / инвестор` |
| Подтип | уточнение типа (например: "активный клиент", "потенциальный инвестор") |
| Бизнесы | через запятую (BIZ-001, BIZ-002) |
| Уровень доверия | `1-5` (1=незнакомый, 5=ключевой партнёр) |
| Источник знакомства | текст |

**Ценность отношений:**

| Колонка | Описание |
|---------|----------|
| Чем может быть полезен | текст — конкретно |
| Чем я могу быть полезен | текст — конкретно |
| Кого знает | текст — ценные связи через него |
| Специализация | через запятую |
| Теги | через запятую (ключевые слова) |

**История и следующие шаги:**

| Колонка | Описание |
|---------|----------|
| Дата первого контакта | YYYY-MM-DD |
| Дата последнего контакта | YYYY-MM-DD |
| Канал последнего контакта | WhatsApp / Telegram / Phone / встреча |
| Краткая история | последние 3-5 взаимодействий |
| Следующее касание | YYYY-MM-DD |
| Тип следующего касания | звонок / встреча / сообщение / поздравление |
| Заметка для касания | о чём говорить / что отправить |
| Статус отношений | `cold / warm / hot / paused` |

### Связь с GTD
- `Следующее касание` → Next Action в GTD (@Phone или @WhatsApp)
- `Статус = hot` → автоматически появляется в утреннем дайджесте
- Поздравления (день рождения) → Tickler в Someday

---

## Модуль 4: Channel Registry (Реестр каналов)

### Назначение
Карта всех коммуникационных каналов. Отвечает на вопрос: "через что мы общаемся с клиентами и как это устроено?"

### Структура листа `CHANNEL_REGISTRY`

| Колонка | Тип | Описание |
|---------|-----|----------|
| ID | `CH-001` | Уникальный ID канала |
| Тип канала | см. ниже | |
| Бизнес ID | `BIZ-001` | |
| Город | текст | |
| Номер / Аккаунт | текст | Конкретные данные |
| Назначение | текст | Для чего используется |
| Аудитория | текст | Кто подписан/звонит |
| Ответственный | текст | |
| Статус | `active/paused/test` | |
| Интеграция | текст | С чем связан |
| Метрики | текст | Что измеряем |
| Комментарий | текст | |

### Типы каналов и специфика

**Binotel:**
- Номер телефона
- Аккаунт Binotel
- Виртуальный номер
- Сценарий IVR
- Ответственный за звонки

**WABA (WhatsApp Business API):**
- Номер WABA
- Провайдер (SendPulse / другой)
- Шаблоны сообщений
- Автоответы
- Ссылка на настройки

**Instagram:**
- @аккаунт
- Тип контента
- Частота постинг
- Ответственный за DM

**SendPulse:**
- Организация/проект
- Тип (email/SMS/WhatsApp/чат-бот)
- Список рассылки
- Автоматизации

**Telegram:**
- Канал/группа/бот
- Количество подписчиков
- Назначение

**Gmail:**
- Email адрес
- Назначение (продажи/поддержка/документы)
- Forwarding настройки

**Google Forms:**
- Название формы
- Ссылка
- Куда идут ответы
- Для чего

**Сайт:**
- Домен
- CMS
- Хостинг
- Форма заявки

### Связь с GTD
- Упавший канал (статус → paused) → Next Action в GTD
- Настройка нового канала → Проект в GTD

---

## Модуль 5: Integration Registry (Реестр интеграций)

### Назначение
Техническая карта всех API и интеграций. Отвечает на вопрос: "что с чем связано и как это работает?"

### Структура листа `INTEGRATION_REGISTRY`

| Колонка | Тип | Описание |
|---------|-----|----------|
| ID | `INT-001` | Уникальный ID |
| Сервис | текст | SendPulse, Binotel, etc. |
| Тип | `API/Webhook/Script/Manual` | |
| Бизнес ID | через запятую | |
| Описание | текст | Что делает интеграция |
| API endpoint | URL | |
| Где хранится код | текст | файл/репозиторий/n8n/Make |
| API ключи — где | текст | `.env` имя переменной |
| Статус | `active/broken/test/planned` | |
| Последняя проверка | YYYY-MM-DD | |
| Как проверить работу | текст | Конкретный тест |
| Типичные ошибки | текст | Что ломается и почему |
| Решение ошибок | текст | Как чинить |
| Кто отвечает | текст | |
| Документация | URL | |
| Комментарий | текст | |

### Текущие интеграции (начальные данные)

| ID | Сервис A | Сервис B | Описание |
|----|----------|----------|----------|
| INT-001 | Telegram Bot | Google Sheets | GTD данные |
| INT-002 | Telegram Bot | Anthropic Claude | AI-обработка |
| INT-003 | Telegram Bot | Google Calendar | Дедлайны |
| INT-004 | Telegram Bot | Google Drive | PDF хранение |
| INT-005 | Telegram Bot | OpenAI Whisper | Голос → текст |
| INT-006 | Binotel | SendPulse | Звонки → CRM |
| INT-007 | WABA | SendPulse | WhatsApp рассылки |

### Связь с GTD
- `Статус = broken` → автоматически создаётся Next Action в GTD
- Плановые проверки интеграций → Recurring Action в GTD

---

## Модуль 6: Relationship Capital (Социальный капитал)

### Назначение
Активное управление отношениями. Не просто справочник, а система касаний. Отвечает на вопрос: "кому нужно написать, кого поздравить, кого с кем познакомить?"

### Структура листа `RELATIONSHIP_CAPITAL`

**Это не отдельный лист, а VIEW поверх People Registry с дополнительными полями:**

| Колонка | Описание |
|---------|----------|
| PRS ID | Ссылка на People Registry |
| Теплота | `1–10` (10 = самый тёплый) |
| Дни без контакта | вычисляемое поле |
| Тип следующего касания | информация / поздравление / вопрос / просьба / знакомство |
| Дата касания | YYYY-MM-DD |

**Специальные поля для социального капитала:**

| Колонка | Описание |
|---------|----------|
| День рождения | MM-DD (без года) |
| Важные события | текст (юбилей компании, переезд) |
| Общие интересы | через запятую |
| Чем помог мне | история помощи |
| Чем я помог ему | история помощи |
| Кого могу познакомить | PRS ID через запятую |
| Через кого решить вопрос | текст — конкретный вопрос + имя |
| Полезный контент для него | текст — что отправить |

### Автоматические сигналы (логика в коде)

```
Условие                           → Действие
─────────────────────────────────────────────
Дни без контакта > 30 (тёплый)   → Next Action в GTD "Написать [имя]"
Дни без контакта > 7 (горячий)   → Уведомление в дайджест
День рождения в течение 7 дней   → Tickler в Someday
Теплота < 3, давно не общались   → Предложение: "восстановить контакт?"
```

### Инструменты управления (будущие команды)

```
/people             — список людей с фильтрами
/people warm        — тёплые контакты
/people touch       — кому написать сегодня
/people birthday    — дни рождения в ближайшие 7 дней
/people [имя]       — карточка человека
/touch [ID]         — зафиксировать касание
/intro [ID1] [ID2]  — запланировать знакомство
```

---

## Модуль 7: Business Branches (Ветки бизнесов)

### Назначение
Детальная операционная карта каждого бизнес-направления. Отвечает на вопрос: "как именно устроен каждый бизнес?"

### Структура данных на каждый бизнес

Каждый бизнес хранится как отдельный набор записей. Структура одинаковая:

#### 7.1 Узаконение недвижимости (BIZ-001)
```
Города: Алматы, Астана, Шымкент
Услуги: SVC-001 (гаражи), SVC-002 (частные дома), SVC-003 (коммерция)
Сотрудники: [из People Registry, тип=сотрудник, бизнес=BIZ-001]
Каналы: Binotel (3 номера), WABA, Instagram, сайт
Текущие объекты: [из BIZ Spreadsheet]
KPI: объектов в месяц, средний чек, срок выполнения
```

#### 7.2 Визы и документы (BIZ-002)
```
Города: Алматы
Услуги: [из Service Catalog]
Каналы: WABA, Instagram, Telegram
KPI: заявок в месяц, конверсия, срок
```

#### 7.3 Коучинг (BIZ-003)
```
Формат: индивидуальный, групповой
Услуги: стратегические сессии, менторинг, воркшопы
KPI: клиентов, часов, NPS
```

#### 7.4 Инвестиции (BIZ-004)
```
Статус: hold
Направления: недвижимость, бизнес
Портфель: [из отдельной таблицы]
```

#### 7.5 Автоматизация бизнеса (BIZ-005)
```
Статус: test
Услуги: Telegram-боты, интеграции, GPT-решения
Целевые клиенты: малый и средний бизнес
```

### Структура листа `BUSINESS_BRANCHES`

| Колонка | Описание |
|---------|----------|
| BIZ ID | Ссылка на Business Registry |
| Раздел | `overview/kpi/roadmap/risks/notes` |
| Ключ | Название показателя |
| Значение | Текущее значение |
| Цель | Целевое значение |
| Период | `monthly/quarterly/annual` |
| Дата обновления | |

---

## Модуль 8: Business Builder (Конструктор бизнеса)

### Назначение
Функция создания нового бизнес-направления "под ключ". Запускает цепочку создания всей инфраструктуры.

### Проектируемая функция

```python
def create_business_area(
    name: str,           # "Доставка документов"
    cities: list[str],   # ["Алматы", "Астана"]
    owner: str,          # "Дидар"
    priority: int,       # 1, 2 или 3
    description: str = "",
    services: list[str] = [],
) -> dict:
    """
    Полный цикл создания бизнес-направления.
    
    Возвращает:
    {
        "biz_id": "BIZ-006",
        "gtd_project_id": "PRJ-XXX",
        "gtd_actions_created": 5,
        "status": "created"
    }
    """
```

### Что создаёт функция (поэтапно)

**Этап 1: Регистрация бизнеса**
```
1. Генерирует BIZ-ID (следующий по порядку)
2. Создаёт строку в BIZ_REGISTRY
3. Статус: test
```

**Этап 2: GTD-интеграция**
```
4. Создаёт Проект в GTD PROJECTS:
   "Запустить бизнес: [название]"
   Желаемый результат: "Бизнес работает, первые клиенты получены"
   
5. Создаёт 5 стартовых Next Actions в GTD:
   - "Описать услуги [название] в Service Catalog"     @Computer
   - "Определить первых 10 потенциальных клиентов"     @Computer
   - "Настроить базовые каналы коммуникации"           @Computer
   - "Создать шаблоны документов"                      @Computer
   - "Провести первые 3 переговора"                    @Phone
```

**Этап 3: Структура данных (будущее)**
```
6. [БУДУЩЕЕ] Создаёт папку в Google Drive
7. [БУДУЩЕЕ] Создаёт операционный Google Sheet
8. [БУДУЩЕЕ] Шаблоны для услуг из Service Catalog
```

**Этап 4: Уведомление**
```
9. Отправляет сводку в Telegram:
   "✅ Бизнес BIZ-006 создан
   📋 GTD проект: PRJ-XXX
   ⚡ Добавлено 5 Next Actions
   🔗 Следующий шаг: /tasks @Computer"
```

### Telegram-команда

```
/newbiz Доставка документов | Алматы, Астана | Дидар | 2
```

---

## Структура папок `business_core/`

```
gtd-ai-assistant/
│
├── business_core/                    ← новая папка
│   ├── __init__.py                   ← пустой, делает папку пакетом
│   ├── sheets.py                     ← схема листов Business Core
│   ├── registry.py                   ← Business Registry
│   ├── services.py                   ← Service Catalog
│   ├── people.py                     ← People Registry
│   ├── channels.py                   ← Channel Registry
│   ├── integrations.py               ← Integration Registry
│   ├── relationships.py              ← Relationship Capital
│   ├── branches.py                   ← Business Branches
│   ├── builder.py                    ← Business Builder
│   ├── bot_handlers.py               ← Telegram handlers для Business Core
│   └── utils.py                      ← вспомогательные функции
│
├── telegram_bot.py                   ← НЕ МЕНЯТЬ (существующий)
├── sheets.py                         ← НЕ МЕНЯТЬ (существующий)
├── inbox_processor.py                ← НЕ МЕНЯТЬ (существующий)
├── calendar_sync.py                  ← НЕ МЕНЯТЬ (существующий)
├── project_planner.py                ← НЕ МЕНЯТЬ (существующий)
│
├── PROJECT_ARCHITECTURE.md           ← уже создан
├── BUSINESS_CORE_PLAN.md             ← этот документ
└── .env                              ← добавить BUSINESS_SPREADSHEET_ID
```

---

## Список файлов Python и функции

### `business_core/__init__.py`
```python
# Пустой файл — делает папку Python-пакетом
```

### `business_core/sheets.py`
```python
BUSINESS_SHEET_NAMES = {
    "biz_registry":     "BIZ_REGISTRY",
    "service_catalog":  "SERVICE_CATALOG",
    "people_registry":  "PEOPLE_REGISTRY",
    "channel_registry": "CHANNEL_REGISTRY",
    "integration_reg":  "INTEGRATION_REGISTRY",
    "rel_capital":      "RELATIONSHIP_CAPITAL",
    "biz_branches":     "BUSINESS_BRANCHES",
}

def get_biz_core_spreadsheet()        # открыть BUSINESS_SPREADSHEET_ID
def get_biz_core_sheet(name: str)     # получить лист по ключу
def init_business_core_sheets()       # создать все листы с заголовками (первый запуск)
def generate_id(prefix: str) -> str  # BIZ-001, PRS-001, SVC-001...
```

### `business_core/registry.py`
```python
def create_business(name, cities, owner, priority, ...) -> str   # → BIZ-ID
def get_business(biz_id: str) -> dict
def get_all_businesses(status=None) -> list[dict]
def update_business_status(biz_id, status)
def link_gtd_project(biz_id, project_id)
def get_business_summary(biz_id) -> str          # текст для Telegram
def list_businesses_text() -> str                # форматированный список
```

### `business_core/services.py`
```python
def create_service(biz_id, name, cities, price_min, price_max, ...) -> str  # → SVC-ID
def get_service(svc_id: str) -> dict
def get_services_by_business(biz_id: str) -> list[dict]
def get_service_checklist(svc_id: str) -> list[str]       # этапы как список
def get_service_documents(svc_id: str) -> dict            # от клиента / от нас
def service_to_gtd_project(svc_id, client_name) -> dict  # создаёт проект в GTD
def format_service_card(svc_id: str) -> str              # текст для Telegram
```

### `business_core/people.py`
```python
def create_person(name, phone, city, person_type, ...) -> str    # → PRS-ID
def get_person(prs_id: str) -> dict
def find_person(query: str) -> list[dict]                        # поиск по имени/телефону
def get_people_by_type(person_type: str) -> list[dict]
def get_people_by_business(biz_id: str) -> list[dict]
def update_last_contact(prs_id, date=None, channel=None)
def set_next_touch(prs_id, date, touch_type, note="")
def get_people_to_touch_today() -> list[dict]           # следующее касание = сегодня
def get_birthday_alerts(days_ahead=7) -> list[dict]     # дни рождения
def create_touch_action_in_gtd(prs_id) -> str           # → GTD Next Action ID
def format_person_card(prs_id: str) -> str              # текст для Telegram
```

### `business_core/channels.py`
```python
def create_channel(channel_type, biz_id, account, purpose, ...) -> str  # → CH-ID
def get_channel(ch_id: str) -> dict
def get_channels_by_business(biz_id: str) -> list[dict]
def get_channels_by_type(channel_type: str) -> list[dict]
def update_channel_status(ch_id, status)
def get_broken_channels() -> list[dict]                 # статус broken
def format_channel_summary(biz_id: str) -> str         # текст для Telegram
```

### `business_core/integrations.py`
```python
def create_integration(service_a, service_b, description, ...) -> str   # → INT-ID
def get_integration(int_id: str) -> dict
def get_broken_integrations() -> list[dict]             # статус broken
def update_integration_status(int_id, status, last_check=None)
def get_integration_by_service(service_name: str) -> list[dict]
def format_integration_status() -> str                  # текст для Telegram
def create_fix_action_in_gtd(int_id) -> str            # → GTD Next Action
```

### `business_core/relationships.py`
```python
def get_warm_contacts(min_warmth=7) -> list[dict]
def get_overdue_contacts(days=30) -> list[dict]         # давно не общались
def get_upcoming_birthdays(days=7) -> list[dict]
def get_people_to_introduce() -> list[dict]             # кого с кем познакомить
def calculate_relationship_health() -> dict             # аналитика по сети
def get_daily_relationship_digest() -> str             # что делать сегодня
def record_interaction(prs_id, channel, notes="")      # зафиксировать контакт
def create_birthday_tickler(prs_id) -> str             # → GTD Someday с датой
```

### `business_core/branches.py`
```python
def get_branch_overview(biz_id: str) -> dict
def update_branch_kpi(biz_id, kpi_key, value, period)
def get_branch_roadmap(biz_id: str) -> list[dict]
def get_all_branches_summary() -> str                  # текст для Telegram
def get_branch_risks(biz_id: str) -> list[str]
def update_branch_notes(biz_id, notes)
```

### `business_core/builder.py`
```python
def create_business_area(name, cities, owner, priority, ...) -> dict
def _register_business(name, cities, owner, priority) -> str        # → BIZ-ID
def _create_gtd_project(biz_id, name) -> str                       # → PRJ-ID
def _create_starter_actions(biz_id, project_id) -> list[str]       # → list[action IDs]
def _generate_business_structure(biz_id) -> dict                   # шаблон структуры
def get_business_creation_status(biz_id) -> dict
```

### `business_core/bot_handlers.py`
```python
# Telegram handlers — подключаются к существующему telegram_bot.py
# через register_business_handlers(app) в main()

def register_business_handlers(app)           # регистрация всех хендлеров

# Business Registry
async def cmd_businesses(update, context)     # /biz_list
async def cmd_business_detail(update, context) # /biz BIZ-001
async def cmd_new_business(update, context)   # /newbiz

# Service Catalog
async def cmd_services(update, context)       # /services [BIZ-001]
async def cmd_service_detail(update, context) # /service SVC-001

# People
async def cmd_people(update, context)         # /people [фильтр]
async def cmd_person(update, context)         # /person PRS-001
async def cmd_touch(update, context)          # /touch PRS-001
async def cmd_people_today(update, context)   # /touch_today

# Channels & Integrations
async def cmd_channels(update, context)       # /channels [BIZ-001]
async def cmd_integrations(update, context)   # /integrations

# Relationship Capital
async def cmd_warm(update, context)           # /warm — тёплые контакты
async def cmd_birthdays(update, context)      # /birthdays

# Builder
async def cmd_new_business_wizard(update, context)  # /newbiz
```

### `business_core/utils.py`
```python
def format_table_row(data: dict, fields: list) -> str    # → строка для Telegram
def parse_command_args(text: str) -> dict                # /cmd arg1|arg2|arg3
def generate_next_id(sheet, prefix: str) -> str          # BIZ-001, BIZ-002...
def safe_get(data: dict, *keys, default="") -> str       # безопасное получение
def date_diff_days(date_str: str) -> int                 # дней с даты
def truncate(text: str, max_len: int) -> str
def cities_list(cities_str: str) -> list[str]            # "Алматы, Астана" → list
```

---

## Google Sheets — структура данных

### Новая таблица `BUSINESS_CORE` (отдельный Spreadsheet)

```
Добавить в .env:
BUSINESS_SPREADSHEET_ID=<новый_id>
```

#### Лист: BIZ_REGISTRY
```
Заголовки (строка 1):
ID | Название | Slug | Статус | Описание | Города | Ответственный | 
Приоритет | Дата старта | Google Drive | Google Sheet | GTD Project ID |
SendPulse | Binotel | WABA | Instagram | Telegram | CRM | Комментарий |
Последнее обновление
```

#### Лист: SERVICE_CATALOG
```
ID | Бизнес ID | Название | Slug | Статус | Город | Цена мин | Цена макс |
Срок | Описание | Этап 1-10 | Документы от клиента | Документы наши |
Чек-лист производства | Чек-лист закрытия | Риски | Шаблоны | Инструкция | Комментарий
```

#### Лист: PEOPLE_REGISTRY
```
ID | ФИО | Имя | Телефон | Телефон 2 | WhatsApp | Telegram | Email | Город |
Компания | Должность | Тип | Подтип | Бизнесы | Уровень доверия | Источник |
Чем полезен | Чем я полезен | Кого знает | Специализация | Теги |
День рождения | Важные события | Дата первого контакта | Дата последнего контакта |
Канал последнего контакта | История | Следующее касание | Тип касания |
Заметка касания | Статус отношений | Теплота | Комментарий
```

#### Лист: CHANNEL_REGISTRY
```
ID | Тип | Бизнес ID | Город | Номер/Аккаунт | Назначение | Аудитория |
Ответственный | Статус | Интеграция | Метрики | Комментарий
```

#### Лист: INTEGRATION_REGISTRY
```
ID | Сервис A | Сервис B | Тип | Бизнесы | Описание | API endpoint |
Где код | Ключи (.env) | Статус | Последняя проверка | Как проверить |
Типичные ошибки | Решение | Ответственный | Документация | Комментарий
```

#### Лист: RELATIONSHIP_CAPITAL
```
PRS ID | ФИО | Теплота | Дни без контакта | Тип касания | Дата касания |
Общие интересы | Чем помог мне | Чем я помог | Кого познакомить |
Через кого решить | Контент для него
```

#### Лист: BUSINESS_BRANCHES
```
BIZ ID | Раздел | Ключ | Значение | Цель | Период | Дата обновления
```

---

## Безопасное подключение к GTD

### Принцип: только импорт, никогда не наоборот

```
business_core/ ──импортирует──→ project_planner.py (создание проектов/задач)
business_core/ ──импортирует──→ sheets.py (get_sheet для GTD листов)
business_core/ ──импортирует──→ inbox_processor.py (process_item для AI)

telegram_bot.py ──импортирует──→ business_core/bot_handlers.py
                                  (только register_business_handlers)
```

### Единственное изменение в `telegram_bot.py`

В конец функции `main()` добавить **2 строки**:

```python
# В main(), после всех существующих app.add_handler():
from business_core.bot_handlers import register_business_handlers
register_business_handlers(app)
```

**Всё остальное — только в новых файлах.**

### Безопасная точка интеграции в GTD

Business Core создаёт задачи/проекты через существующие функции:

```python
# В business_core/builder.py — используем готовый project_planner
from project_planner import save_project, build_action_row
from sheets import get_sheet

def _create_gtd_project(biz_id, name):
    save_project(
        name=f"Запустить бизнес: {name}",
        outcome="Бизнес работает, первые клиенты получены",
        area="Business",
        priority="Высокий",
        next_action="Описать услуги в Service Catalog",
        context_tag="@Computer",
    )
```

---

## Файлы которые нельзя менять на первом этапе

| Файл | Почему нельзя менять |
|------|---------------------|
| `telegram_bot.py` | 4392 строки, вся логика GTD. Единственное допустимое изменение — 2 строки в `main()` |
| `sheets.py` | Структура GTD таблицы. Изменение = риск потери данных |
| `inbox_processor.py` | AI-промпт. Менять только если тестируешь |
| `calendar_sync.py` | Стабильно работает. Не трогать |
| `project_planner.py` | Критичная структура строк (16 колонок) |
| `.env` | Только добавлять новые переменные, не менять существующие |
| `credentials.json` | Service account ключ |

---

## Пошаговый план внедрения

### Фаза 0: Подготовка (1 день)
```
□ Создать новый Google Sheets для Business Core
□ Записать BUSINESS_SPREADSHEET_ID в .env
□ Создать папку business_core/ в проекте
□ Создать __init__.py (пустой)
□ python3 -m py_compile telegram_bot.py  ← убедиться что всё работает
```

### Фаза 1: Sheets и Registry (2–3 дня)
```
□ Написать business_core/sheets.py
□ Написать init_business_core_sheets()
□ Запустить: python3 -c "from business_core.sheets import init_business_core_sheets; init_business_core_sheets()"
□ Убедиться что листы создались в Google Sheets
□ Написать business_core/registry.py
□ Заполнить BIZ_REGISTRY вручную (5 бизнесов)
□ Протестировать get_all_businesses()
```

### Фаза 2: People Registry (2–3 дня)
```
□ Написать business_core/people.py
□ Добавить первых 20 ключевых людей вручную
□ Протестировать find_person(), get_people_to_touch_today()
□ Написать business_core/bot_handlers.py (только /people команды)
□ Добавить 2 строки в telegram_bot.py main()
□ python3 -m py_compile telegram_bot.py
□ Перезапустить бота и протестировать /people
```

### Фаза 3: Service Catalog (2–3 дня)
```
□ Написать business_core/services.py
□ Заполнить SERVICE_CATALOG для топ-3 услуг
□ Добавить /services команды в bot_handlers.py
□ Протестировать service_to_gtd_project()
```

### Фаза 4: Channels & Integrations (1–2 дня)
```
□ Написать business_core/channels.py
□ Написать business_core/integrations.py
□ Заполнить данные по текущим каналам и интеграциям
□ Добавить команды /channels, /integrations
```

### Фаза 5: Relationship Capital (1–2 дня)
```
□ Написать business_core/relationships.py
□ Добавить поля теплоты и касаний к существующим записям
□ Подключить к утреннему дайджесту (get_daily_relationship_digest)
□ Добавить /warm, /birthdays команды
```

### Фаза 6: Business Builder (2–3 дня)
```
□ Написать business_core/builder.py
□ Реализовать create_business_area()
□ Добавить /newbiz команду
□ Полное тестирование: /newbiz → проект в GTD → Next Actions
```

### Фаза 7: Автоматизации (по готовности)
```
□ Ежедневный relationship digest в morning_digest
□ Напоминания о broken integrations
□ Автосоздание GTD-задач при смене статусов
□ n8n/Make webhooks (Binotel → GTD, SendPulse → GTD)
```

---

## Итоговая схема всей системы

```
                    ВЛАДЕЛЕЦ
                       │
                  Telegram Bot
                  ┌────┴────┐
                  │         │
             GTD Core   Business Core
                  │         │
         ┌────────┼─────────┼────────┐
         │        │         │        │
      INBOX   PROJECTS   PEOPLE   SERVICES
      TASKS   HORIZONS   CHANNELS REGISTRY
      WAITING ARCHIVE    CAPITAL  BRANCHES
         │        │         │        │
         └────────┴─────────┴────────┘
                       │
              Google Sheets (2 таблицы)
              GTD Master + Business Core
                       │
              ┌─────────────────┐
              │  Внешние сервисы │
              │ Binotel SendPulse│
              │ WABA   Calendar  │
              └─────────────────┘
```

---

*Документ готов к реализации. Начинать с Фазы 0.*
