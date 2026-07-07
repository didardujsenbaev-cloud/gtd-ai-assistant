# Business Core — Архитектура расширения GTD OS

> Версия: 2.0 — Обновлено с учётом реальной архитектуры GTD  
> Дата: 07.07.2026  
> Источник: GTD_CURRENT_WORKFLOW.md (анализ реального кода)  
> Принцип: GTD — методологический центр. Business Core — контекстный слой поверх GTD.

---

## Разграничение ответственности

```
┌──────────────────────────────────────────────────────────────┐
│              GTD MASTER SYSTEM (существующий, не меняем)      │
│                                                               │
│  Inbox  •  Projects  •  Next Actions  •  Waiting             │
│  Someday  •  Reference  •  Horizons H1–H5  •  Archive        │
│  Weekly Review  •  Calendar  •  Google Drive                  │
│                                                               │
│  telegram_bot.py (4392 строки) — НЕ ТРОГАТЬ                  │
│  sheets.py • inbox_processor.py • project_planner.py          │
│  calendar_sync.py — НЕ ТРОГАТЬ                               │
└─────────────────────┬────────────────────────────────────────┘
                      │ Projects/Actions ↕
┌─────────────────────▼────────────────────────────────────────┐
│                  BUSINESS CORE (строим)                       │
│                                                               │
│  РЕЕСТРЫ:                                                     │
│  Business Registry  •  Service Catalog  •  People Registry   │
│  Channel Registry  •  Integration Registry  •  Rel. Capital  │
│                                                               │
│  ЛОГИКА:                                                      │
│  Business Router  ←  получает GTD-результат process_item()   │
│  Roadmap Manager  ←  дорожные карты по клиенту/услуге        │
│  Material Manager ←  файлы привязанные к этапу               │
│  Business Builder ←  конструктор нового бизнеса              │
└─────────────────────┬────────────────────────────────────────┘
                      │ данные ↕
┌─────────────────────▼────────────────────────────────────────┐
│              BUSINESS_CORE Google Sheets                      │
│         (отдельный BUSINESS_SPREADSHEET_ID)                  │
│  BIZ_REGISTRY • SERVICE_CATALOG • PEOPLE_REGISTRY            │
│  CHANNEL_REGISTRY • INTEGRATION_REGISTRY                     │
│  ROADMAPS • MATERIALS • RELATIONSHIP_CAPITAL                 │
└─────────────────────┬────────────────────────────────────────┘
                      │ API ↕ (Фаза 6)
┌─────────────────────▼────────────────────────────────────────┐
│              ИНТЕГРАЦИИ (integrations/)                       │
│  SendPulse • Binotel • WABA • Instagram                      │
│  Google Drive • Google Calendar • Google Accounts            │
└──────────────────────────────────────────────────────────────┘
```

**Главный принцип потока данных:**
```
Telegram → handle_message() → process_item() [GTD-классификация]
→ Business Router [бизнес-контекст]
→ GTD Master System [задачи/проекты]
→ BUSINESS_CORE [реестры/дорожные карты]
→ Google Drive / Calendar / Интеграции
```

**Что GTD делает сам:** Inbox, классификация задач, создание Projects/Actions/Waiting, Горизонты, Review, Calendar sync.  
**Что добавляет Business Core:** Бизнес, услуга, клиент, город, этап дорожной карты, материалы, каналы.

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

---

## Модуль 9: Business Router

### Назначение

Определяет **бизнес-контекст** входящего сообщения — после того как GTD уже классифицировал его через `process_item()`. Business Router не заменяет GTD-классификацию, а **дополняет** её бизнес-измерением.

**Ключевой принцип:** GTD отвечает на "что делать?", Business Router отвечает на "в рамках какого бизнеса/клиента/этапа?"

### Файл

```
business_core/business_router.py
```

### Входные данные

```python
{
    "original_text": "По узаконению частного дома Иванова в Алматы надо проверить техпаспорт",
    "gtd_result": "Action",           # результат process_item()
    "action": "Проверить техпаспорт Иванова",
    "context": "@Computer",
    "deadline": "2026-07-10",
    "area": "Legalization",            # уже есть из GTD
    "project": "Узаконение дома Иванова",
}
```

### Выходные данные

```python
{
    "business_id": "BIZ-001",
    "business_name": "Узаконение недвижимости",
    "service_id": "SVC-003",
    "service_name": "Узаконение частного дома",
    "city": "Алматы",
    "client_id": "PRS-042",
    "client_name": "Иванов",
    "process": "Производство",
    "roadmap_id": "RM-017",
    "roadmap_stage_id": "STAGE-07",
    "roadmap_stage_name": "Техпаспорт",
    "confidence": 0.86,
    "needs_confirmation": True,      # если confidence < 0.9 → спросить
    "routing_method": "keyword_match",  # keyword_match / ai / manual
}
```

### Логика роутинга (3 уровня)

**Уровень 1 — Ключевые слова (быстро, без AI):**
```
"узаконение", "легализация", "БТИ", "акт ввода" → BIZ-001
"виза", "паспорт", "нотариус" → BIZ-002
"коучинг", "сессия", "ментор" → BIZ-003
```

**Уровень 2 — Люди и клиенты:**
```
Имя в тексте → поиск в People Registry по имени
→ если найден → привязать client_id
→ если не найден → needs_confirmation = True
```

**Уровень 3 — AI (если confidence < 0.7):**
```
Краткий Claude-запрос с контекстом активных бизнесов и услуг
→ определить business_id + service_id + city
→ max_tokens: 256 (дешёвый запрос)
```

### Функции

```python
def route_business_context(
    original_text: str,
    gtd_result: dict,
    businesses: list[dict],
    services: list[dict],
    people: list[dict],
) -> dict
    """Основная функция роутинга."""

def _route_by_keywords(text: str, businesses: list) -> tuple[str, float]
    """Быстрый матч по ключевым словам. Возвращает (biz_id, confidence)."""

def _find_client_in_text(text: str, people: list) -> tuple[str, float]
    """Найти имя клиента в тексте. Возвращает (person_id, confidence)."""

def _find_city_in_text(text: str) -> str
    """Определить город: Алматы / Астана / Шымкент / ""."""

def _route_by_ai(text: str, businesses: list, services: list) -> dict
    """AI-роутинг для неоднозначных случаев."""

def _find_active_roadmap(client_id: str, service_id: str) -> str
    """Найти активную дорожную карту клиента по услуге."""

def format_routing_confirmation(routing: dict) -> str
    """Текст для подтверждения пользователем (если needs_confirmation)."""
```

### Когда Business Router вызывается

Business Router вызывается **только** если:
1. `gtd_result["результат"]` в (`"Action"`, `"Project"`, `"Waiting"`)
2. `gtd_result["область"]` ∈ бизнес-областям (`Business`, `Legalization`, `Visas`, `Coaching`, ...)
3. Business Core активирован в `.env`: `BUSINESS_CORE_ENABLED=true`

При `результат=Someday`, `H3/H4/H5`, `Reference`, `Trash` — Business Router **не вызывается**.

### Связь с GTD

Business Router **не создаёт** GTD-записи. Он только **обогащает** данные, которые потом GTD запишет в NEXT ACTIONS с дополнительными полями:
```
Проект: [gtd_project_id]        ← уже есть в GTD
Заметки: [business_id, client_id, roadmap_stage_id]  ← добавляет Business Router
```

---

## Модуль 10: Roadmap Manager

### Назначение

Создаёт и ведёт **дорожные карты** по конкретным сделкам/клиентам. Каждая дорожная карта = один кейс (клиент + услуга + город).

**Связь с GTD:** Каждая дорожная карта → один GTD-проект (`gtd_project_id`). Этапы дорожной карты → GTD Next Actions того же проекта.

### Файл

```
business_core/roadmap_manager.py
```

### Структура дорожной карты

```python
{
    "roadmap_id": "RM-017",
    "business_id": "BIZ-001",
    "service_id": "SVC-003",
    "city": "Алматы",
    "client_id": "PRS-042",
    "client_name": "Иванов А.А.",
    "gtd_project_id": "PRJ-023",     # ссылка на GTD PROJECTS
    "responsible": "Дидар",
    "status": "in_progress",
    "created_at": "2026-07-01",
    "expected_completion": "2026-08-15",
    "stages": [
        {
            "stage_id": "STAGE-01",
            "order": 1,
            "name": "Диагностика кейса",
            "status": "done",
            "completed_at": "2026-07-02",
            "gtd_action_id": "ACT-045",
            "notes": "Дом 1990 года, самострой",
        },
        {
            "stage_id": "STAGE-07",
            "order": 7,
            "name": "Техпаспорт",
            "status": "in_progress",
            "due_date": "2026-07-10",
            "gtd_action_id": "ACT-089",
            "responsible": "Кайрат",
            "documents_required": ["заявление", "копия удостоверения"],
            "documents_received": ["заявление"],
            "notes": "",
        },
        # ... до 10 этапов
    ],
    "documents": [],   # список Material IDs
    "total_stages": 10,
    "completed_stages": 6,
    "progress_pct": 60,
}
```

### Стандартные этапы по услугам

**Узаконение частного дома (SVC-003):**
```
1. Диагностика кейса
2. Сбор документов
3. АПЗ (Архитектурно-планировочное задание)
4. Проект
5. Техобследование
6. Топосъемка
7. Техпаспорт
8. Акт ввода
9. Регистрация в ЕГРН
10. Закрытие и архив
```

**Узаконение гаража (SVC-001):**
```
1. Диагностика
2. Документы от клиента
3. Технический паспорт
4. Подача в ЦОН
5. Получение акта ввода
6. Регистрация
7. Архив
```

### Статусы этапов

| Статус | Описание |
|--------|----------|
| `not_started` | Этап ещё не начат |
| `in_progress` | В работе |
| `waiting` | Ждём от клиента или третьей стороны |
| `blocked` | Заблокировано (проблема) |
| `done` | Завершён |

### Лист `ROADMAPS` в Google Sheets

```
Заголовки:
Roadmap ID | Business ID | Service ID | City | Client ID | Client Name |
GTD Project ID | Responsible | Status | Created | Expected | Progress % |
Stage 1 Status | Stage 2 Status | ... | Stage 10 Status |
Notes | Last Updated
```

### Лист `ROADMAP_STAGES` в Google Sheets

```
Stage ID | Roadmap ID | Order | Name | Status | Due Date | Completed At |
GTD Action ID | Responsible | Docs Required | Docs Received | Notes
```

### Функции

```python
def create_roadmap(
    business_id, service_id, city, client_id,
    gtd_project_id, responsible="",
) -> str   # → RM-ID

def get_roadmap(roadmap_id: str) -> dict
def get_active_roadmaps(business_id=None, client_id=None) -> list[dict]

def advance_stage(roadmap_id: str, stage_id: str, notes="") -> dict
    """Перевести этап в in_progress → done, создать GTD Action для следующего."""

def block_stage(roadmap_id, stage_id, reason: str) -> None
    """Заблокировать этап. Создать Waiting в GTD с reason."""

def get_roadmap_summary(roadmap_id: str) -> str
    """Текст для Telegram: прогресс по клиенту."""

def create_roadmap_from_gtd_project(project_id: str, service_id: str) -> str
    """Создать дорожную карту из существующего GTD-проекта."""

def get_overdue_stages(days=0) -> list[dict]
    """Этапы с просроченным дедлайном."""

def calculate_progress(roadmap_id: str) -> int
    """Процент выполнения: done_stages / total_stages * 100."""
```

### Автоматические GTD-действия из Roadmap

При `advance_stage()`:
```
1. Текущий этап → статус "done", дата выполнения
2. Следующий этап → статус "in_progress"
3. В GTD: создать Next Action с именем следующего этапа
   → project = gtd_project_id
   → context = @Computer или @Government (по шаблону этапа)
   → deadline = due_date этапа
```

---

## Модуль 11: Material Manager

### Назначение

Привязывает файлы, фото, PDF, ссылки и заметки к **конкретному бизнес-контексту**: бизнес + клиент + услуга + этап дорожной карты.

**Важно:** GTD уже умеет принимать документы через `handle_document()`, `handle_photo()`, `upload_pdf_to_drive()` и хранит в листе `REFERENCE`. Material Manager **не дублирует** эту логику — он добавляет к существующей ссылке в REFERENCE дополнительную бизнес-привязку.

### Файл

```
business_core/material_manager.py
```

### Структура материала

```python
{
    "material_id": "MAT-001",

    # Откуда пришёл
    "source": "Telegram",           # Telegram/PDF/Photo/WhatsApp/Email/Drive
    "received_at": "2026-07-07",
    "received_by": "Дидар",

    # Ссылки на GTD
    "gtd_reference_row": 42,        # строка в GTD REFERENCE sheet
    "gtd_project_id": "PRJ-023",    # если материал привязан к проекту

    # Ссылки на Business Core
    "business_id": "BIZ-001",
    "service_id": "SVC-003",
    "city": "Алматы",
    "client_id": "PRS-042",
    "roadmap_id": "RM-017",
    "stage_id": "STAGE-07",         # к какому этапу относится

    # Файл
    "file_type": "PDF",             # PDF/Photo/Text/Link/Voice
    "drive_url": "https://drive.google.com/...",
    "filename": "tehpasport_ivanov.pdf",
    "file_size_kb": 342,

    # Статус
    "status": "received",           # received/checked/approved/archived
    "checked_by": "",
    "approved_at": "",
    "notes": "Техпаспорт от 2019 года",
}
```

### Статусы материала

| Статус | Описание |
|--------|----------|
| `received` | Получен, ещё не проверен |
| `checked` | Проверен, всё ок |
| `approved` | Утверждён, принят в работу |
| `rejected` | Не принят, нужна замена |
| `archived` | В архиве завершённого проекта |

### Лист `MATERIALS` в Google Sheets

```
Material ID | Source | Received At | GTD Reference Row | GTD Project ID |
Business ID | Service ID | City | Client ID | Roadmap ID | Stage ID |
File Type | Drive URL | Filename | File Size KB |
Status | Checked By | Approved At | Notes
```

### Функции

```python
def register_material(
    gtd_reference_row: int,
    drive_url: str,
    source: str,
    routing: dict,             # результат Business Router
    file_type: str = "PDF",
    filename: str = "",
    notes: str = "",
) -> str   # → MAT-ID

def get_materials_by_stage(roadmap_id, stage_id) -> list[dict]
def get_materials_by_client(client_id) -> list[dict]
def get_materials_by_roadmap(roadmap_id) -> list[dict]
def update_material_status(mat_id, status, checked_by="") -> None
def get_missing_documents(roadmap_id, stage_id) -> list[str]
    """Вернуть список документов из шаблона услуги которых ещё нет."""

def format_materials_summary(roadmap_id: str) -> str
    """Текст для Telegram: документы по кейсу."""

def archive_roadmap_materials(roadmap_id: str) -> int
    """При закрытии проекта — перевести все материалы в archived."""
```

### Интеграция с существующим GTD

При получении PDF/фото в Telegram (уже работает):
```python
# telegram_bot.py — handle_document() / handle_photo()
drive_url = upload_pdf_to_drive(bytes, filename)     # уже есть
_save_extracted_to_inbox(update, extracted, "PDF")   # уже есть
# → попадает в GTD REFERENCE sheet

# НОВОЕ (Фаза 2D):
if BUSINESS_CORE_ENABLED:
    routing = route_business_context(...)             # Business Router
    if routing["confidence"] > 0.7:
        register_material(
            gtd_reference_row=ref_row_num,
            drive_url=drive_url,
            source="Telegram",
            routing=routing,
            file_type="PDF",
        )
```

---

## Модуль 12: Integration Architecture

### Структура папки `integrations/`

```
integrations/
├── __init__.py
├── base_adapter.py              ← базовый класс адаптера
├── integration_router.py        ← роутер: определяет куда направить данные
├── sendpulse_adapter.py         ← SendPulse (рассылки, CRM, чат-боты)
├── binotel_adapter.py           ← Binotel (телефония, запись звонков)
├── waba_adapter.py              ← WhatsApp Business API
├── instagram_adapter.py         ← Instagram DM и комментарии
├── google_drive_adapter.py      ← Google Drive (структура папок бизнеса)
├── google_calendar_adapter.py   ← Google Calendar (дедлайны и события)
└── google_accounts_adapter.py   ← разные Google-аккаунты для разных бизнесов
```

---

### 12.1 SendPulse Adapter

**Что принимает SendPulse от нас:**
- Новые контакты → добавить в адресную книгу (имя, телефон, email, теги)
- Триггерные события → запустить автоматизацию (новый клиент, смена этапа)
- Сегменты → обновить теги (бизнес, город, услуга, статус)

**Что отдаёт SendPulse нам:**
- Новые заявки с форм → `webhook → GTD Inbox`
- Статусы рассылок → статистика открытий
- Ответы клиентов на письма → `→ GTD INBOX → process_item()`
- Чат-бот события → действие клиента в воронке

**Ключи `.env`:**
```
SENDPULSE_CLIENT_ID=...
SENDPULSE_CLIENT_SECRET=...
SENDPULSE_ADDRESS_BOOK_ID_BIZ001=...   # отдельная книга на каждый бизнес
SENDPULSE_ADDRESS_BOOK_ID_BIZ002=...
```

**Привязка к бизнесу:**
- У каждого бизнеса своя адресная книга (`SENDPULSE_ADDRESS_BOOK_ID_BIZxxx`)
- Теги = `biz_id` + `city` + `service_id` (например: `BIZ-001 Алматы SVC-003`)
- При создании нового клиента → автоматически добавить в нужную книгу

**Риски:**
- Дубли контактов: один человек может быть в нескольких книгах → дедупликация по телефону через People Registry
- Rate limiting API SendPulse: 10 запросов/секунду

---

### 12.2 Binotel Adapter

**Что принимает Binotel от нас:**
- Список сотрудников → для маршрутизации звонков
- Теги звонка → добавить после разговора

**Что отдаёт Binotel нам:**
- CDR (Call Detail Record) через webhook: номер звонящего, длительность, запись
- Пропущенные звонки → `webhook → GTD Inbox` → Action "Перезвонить [номер]"
- Входящий звонок → поиск номера в People Registry → показать карточку

**Ключи `.env`:**
```
BINOTEL_API_KEY_BIZ001=...    # ключ для каждого бизнеса/города
BINOTEL_API_KEY_BIZ002=...
BINOTEL_WEBHOOK_SECRET=...    # для верификации вебхуков
```

**Привязка к бизнесу и городу:**
- Каждый виртуальный номер Binotel → строка в `CHANNEL_REGISTRY` (CH-ID + BIZ-ID + город)
- При входящем звонке: номер → поиск в CHANNEL_REGISTRY → определить бизнес и город
- CDR запись → Material Manager (ссылка на запись звонка)

**Риски:**
- Определение звонящего: если номер не в People Registry → создать нового PRS
- Записи звонков хранятся на серверах Binotel (не в Drive) → ссылка, не файл

---

### 12.3 WABA Adapter

**Что принимает WABA от нас:**
- Шаблонные сообщения (HSM): уведомления о статусе этапа, напоминания
- Ответы на входящие

**Что отдаёт WABA нам:**
- Входящие сообщения от клиентов → `webhook → GTD Inbox → process_item()`
- Статусы доставки → логирование
- Медиа (фото, документы) → Material Manager

**Ключи `.env`:**
```
WABA_ACCESS_TOKEN=...
WABA_PHONE_NUMBER_ID_BIZ001=...   # отдельный номер на каждый бизнес
WABA_PHONE_NUMBER_ID_BIZ002=...
WABA_VERIFY_TOKEN=...
```

**Привязка к бизнесу:**
- Каждый WABA-номер → строка в CHANNEL_REGISTRY с `channel_type=WABA`
- Входящее сообщение: определить по номеру → BIZ-ID → маршрутизировать

**Дедупликация клиентов:**
- При входящем: поиск по номеру в People Registry
- Если не найден → создать новый PRS с `person_type=клиент`, `source=WABA`
- Если найден → обновить `last_contact_date` и `last_contact_channel`

**Риски:**
- Шаблоны WABA требуют одобрения Meta (2–5 дней)
- Лимит: 1000 уникальных разговоров/день на бесплатном тарифе
- Провайдер (SendPulse как WABA-провайдер): API идёт через SendPulse

---

### 12.4 Instagram Adapter

**Что принимает Instagram от нас:**
- (нет прямой отправки без Instagram API)

**Что отдаёт Instagram нам:**
- DM входящие → `webhook → GTD Inbox`
- Комментарии под постами → GTD Inbox (фильтровать спам)
- Лиды из Stories/Reels → GTD Inbox

**Ключи `.env`:**
```
INSTAGRAM_ACCESS_TOKEN_BIZ001=...
INSTAGRAM_PAGE_ID_BIZ001=...
```

**Риски:**
- Instagram Graph API требует прав `instagram_manage_messages`
- Токены истекают → нужен refresh механизм
- Комментарии часто спам → нужна фильтрация перед отправкой в Inbox

**Статус:** Низкий приоритет. Реализовать только после стабилизации WABA + Binotel.

---

### 12.5 Google Drive Adapter

**Задача:** Создавать и поддерживать структуру папок в Google Drive по шаблону бизнеса.

**Структура папок для бизнеса:**
```
GTD_DOCUMENTS/                    ← уже существует (GDRIVE_FOLDER_ID)
│
├── BIZ-001_Узаконение/
│   ├── 01 Стратегия/
│   ├── 02 Услуги/
│   ├── 06 Клиенты/
│   │   ├── Иванов_RM-017/       ← папка под каждый кейс
│   │   │   ├── Документы/
│   │   │   ├── Переписка/
│   │   │   └── Архив/
│   │   └── Петров_RM-018/
│   └── ...
└── BIZ-002_Визы/
    └── ...
```

**Ключи `.env`:**
```
GDRIVE_FOLDER_ID=...              # уже есть — корневая папка
GOOGLE_CREDENTIALS_FILE=...       # уже есть — тот же service account
```

**Важно:** Google Drive API уже подключён через `sheets.py → _get_creds()`. Новый адаптер использует те же credentials.

**Риски:**
- Создание папок при первом запуске `create_business_area()` — нужен `GDRIVE_ENABLED=true`
- Если папка бизнеса удалена → `business_registry.google_drive_folder` станет битой ссылкой

---

### 12.6 Google Accounts Adapter

**Задача:** Управление разными Google-аккаунтами для разных бизнесов.

**Проблема:** Сейчас один service account управляет всем. При масштабировании на несколько бизнесов каждый может иметь свой Google Workspace.

**Архитектура:**
```python
# .env
GOOGLE_CREDENTIALS_FILE=gtd-ai-assistant-38676c1d863d.json  # основной (GTD)
GOOGLE_CREDENTIALS_BIZ001=biz001-credentials.json           # бизнес 1
GOOGLE_CREDENTIALS_BIZ002=biz002-credentials.json           # бизнес 2
```

```python
# google_accounts_adapter.py
def get_credentials(biz_id: str = None):
    """Вернуть credentials для конкретного бизнеса или основные GTD."""
    if biz_id and os.getenv(f"GOOGLE_CREDENTIALS_{biz_id.replace('-','')}"):
        return Credentials.from_service_account_file(...)
    return _get_creds()  # fallback на основной GTD account
```

**Риски безопасности:**
- Несколько JSON-ключей в файловой системе → все должны быть в `.gitignore` (уже есть `*.json`)
- Лучшее решение: Secret Manager (Google Secret Manager или HashiCorp Vault) — на Фазе 6

---

### 12.7 Integration Router

**Задача:** Единая точка входа для всех входящих webhook-событий.

```python
# integrations/integration_router.py

async def route_webhook(source: str, payload: dict) -> dict:
    """
    Принять webhook от любого сервиса и направить в GTD Inbox.
    
    Поддерживаемые источники:
    - binotel_missed_call  → Action "Перезвонить [номер]"
    - waba_incoming         → Inbox → process_item()
    - sendpulse_lead        → Inbox → process_item()
    - instagram_dm          → Inbox → process_item()
    """
```

### Порядок реализации интеграций

**Делать первыми (высокий ROI, низкий риск):**
1. `google_drive_adapter.py` — структура папок, без внешних API
2. `binotel_adapter.py` — пропущенные звонки → GTD (прямой практический эффект)
3. `waba_adapter.py` — входящие WhatsApp → GTD Inbox

**Делать после стабилизации Business Core:**
4. `sendpulse_adapter.py` — рассылки и CRM-контакты
5. `google_calendar_adapter.py` — отдельный Calendar для каждого бизнеса
6. `google_accounts_adapter.py` — мультиаккаунт

**Не трогать до Фазы 6:**
7. `instagram_adapter.py` — сложный API, нестабильный, низкий приоритет

---

## Обновлённая структура папок `business_core/`

```
gtd-ai-assistant/
│
├── business_core/                    ← уже создан (Фаза 1 ✅)
│   ├── __init__.py                   ← пустой, делает папку пакетом
│   ├── sheets.py                     ← схема листов Business Core
│   ├── registry.py                   ← Business Registry
│   ├── service_catalog.py            ✅ создан
│   ├── people_registry.py            ✅ создан
│   ├── channel_registry.py           ✅ создан
│   ├── integration_registry.py       ✅ создан
│   ├── relationship_capital.py       ✅ создан
│   ├── business_builder.py           ✅ создан
│   ├── README.md                     ✅ создан
│   │
│   ├── sheets.py                     ← Фаза 2A
│   ├── business_router.py            ← Фаза 2B
│   ├── roadmap_manager.py            ← Фаза 2C
│   ├── material_manager.py           ← Фаза 2D
│   ├── bot_handlers.py               ← Фаза 4
│   └── utils.py                      ← по мере необходимости
│
├── integrations/                     ← Фаза 6
│   ├── __init__.py
│   ├── base_adapter.py
│   ├── integration_router.py
│   ├── sendpulse_adapter.py
│   ├── binotel_adapter.py
│   ├── waba_adapter.py
│   ├── instagram_adapter.py
│   ├── google_drive_adapter.py
│   ├── google_calendar_adapter.py
│   └── google_accounts_adapter.py
│
├── telegram_bot.py                   ← НЕ МЕНЯТЬ
├── sheets.py                         ← НЕ МЕНЯТЬ
├── inbox_processor.py                ← НЕ МЕНЯТЬ
├── calendar_sync.py                  ← НЕ МЕНЯТЬ
├── project_planner.py                ← НЕ МЕНЯТЬ
│
├── PROJECT_ARCHITECTURE.md           ← создан
├── GTD_CURRENT_WORKFLOW.md           ← создан
├── BUSINESS_CORE_PLAN.md             ← этот документ
└── .env                              ← добавить новые переменные
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

## Обновлённые переменные `.env`

```bash
# ── СУЩЕСТВУЮЩИЕ (не менять) ──────────────────────────────
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...           # для Whisper (локально, не нужен если нет)
GOOGLE_CREDENTIALS_FILE=gtd-ai-assistant-38676c1d863d.json
SPREADSHEET_ID=...           # GTD Master таблица
BIZ_SPREADSHEET_ID=...       # Бизнес-объекты (узаконение)
CALENDAR_ID=...              # GTD-календарь
READ_CALENDAR_IDS=...        # Доп. календари
GDRIVE_FOLDER_ID=...         # GTD документы в Drive
GDRIVE_IS_SHARED_DRIVE=false

# ── ДОБАВИТЬ (Фаза 2A) ────────────────────────────────────
BUSINESS_SPREADSHEET_ID=...  # Business Core таблица (новая)
BUSINESS_CORE_ENABLED=false  # Включить после тестирования

# ── ДОБАВИТЬ (Фаза 3) ─────────────────────────────────────
GDRIVE_BIZ_ROOT_FOLDER_ID=...  # Корень папок бизнесов

# ── ДОБАВИТЬ (Фаза 6) ─────────────────────────────────────
BINOTEL_API_KEY_BIZ001=...
BINOTEL_WEBHOOK_SECRET=...
SENDPULSE_CLIENT_ID=...
SENDPULSE_CLIENT_SECRET=...
WABA_ACCESS_TOKEN=...
WABA_PHONE_NUMBER_ID_BIZ001=...
WABA_VERIFY_TOKEN=...
```

---

## Файлы которые нельзя менять

| Файл | Причина | Допустимое изменение |
|------|---------|---------------------|
| `telegram_bot.py` | 4392 строки GTD-логики | **Только 2 строки в `main()`:** `register_business_handlers(app)` |
| `sheets.py` | Структура GTD таблицы (11 листов) | Нельзя трогать |
| `inbox_processor.py` | SYSTEM_PROMPT Claude — 63 строки правил | Менять только с тестом |
| `project_planner.py` | 16 колонок PROJECTS + NEXT ACTIONS в строгом порядке | Нельзя трогать |
| `calendar_sync.py` | MD5 ключи событий, синхронизация | Нельзя трогать |
| `.env` | Ключи и ID | Только добавлять новые, не менять существующие |
| `gtd-ai-assistant-38676c1d863d.json` | Service account credentials | Нельзя трогать |

---

## Пошаговый план внедрения (обновлён)

### ✅ Фаза 0: Подготовка — ВЫПОЛНЕНО
```
✅ git init + .gitignore (venv, *.json, .env не в git)
✅ Первый коммит: 30 файлов, 10 763 строки
✅ test_business_core.py: 181/181 тестов
```

### ✅ Фаза 1: Локальные модели — ВЫПОЛНЕНО
```
✅ business_core/__init__.py
✅ business_core/models.py            — 6 dataclass-моделей
✅ business_core/business_registry.py — реестр, валидация, 5 дефолтных бизнесов
✅ business_core/service_catalog.py   — услуги, этапы, чек-листы
✅ business_core/people_registry.py   — люди, касания, дни рождения
✅ business_core/channel_registry.py  — каналы коммуникации
✅ business_core/integration_registry.py — интеграции
✅ business_core/relationship_capital.py — социальный капитал
✅ business_core/business_builder.py  — 12 папок + 7 проектов + next actions
✅ business_core/README.md
```

---

### Фаза 2A: BUSINESS_CORE Google Sheets (2–3 дня)

**Цель:** Подключить Business Core к реальной Google Sheets таблице.  
**Изолирован от GTD:** только новый `BUSINESS_SPREADSHEET_ID`.

```
□ Создать новый Google Sheets (отдельный от GTD Master)
□ Добавить BUSINESS_SPREADSHEET_ID в .env
□ Создать business_core/sheets.py:
  - get_biz_core_spreadsheet()
  - get_biz_core_sheet(name)
  - init_all_sheets()    ← создать все 8 листов с заголовками
  - append_biz_row()
  - update_biz_cell()
□ Запустить: python3 -c "from business_core.sheets import init_all_sheets; init_all_sheets()"
□ Убедиться в Google Sheets: 8 листов созданы с заголовками
□ Написать заполнение: BIZ_REGISTRY → 5 дефолтных бизнесов
□ Тест: прочитать BIZ_REGISTRY обратно в Python
□ python3 -m py_compile telegram_bot.py  ← GTD бот не сломан
□ Коммит: "feat: business_core sheets layer"
```

**Новые листы в BUSINESS_SPREADSHEET_ID:**
```
BIZ_REGISTRY • SERVICE_CATALOG • PEOPLE_REGISTRY
CHANNEL_REGISTRY • INTEGRATION_REGISTRY
ROADMAPS • ROADMAP_STAGES • MATERIALS • RELATIONSHIP_CAPITAL
```

---

### Фаза 2B: Business Router — без Telegram (2–3 дня)

**Цель:** Роутер умеет определять бизнес-контекст по тексту GTD-результата.  
**Не затрагивает Telegram:** только Python-логика и тесты.

```
□ Написать business_core/business_router.py
□ Реализовать _route_by_keywords() — матч по ключевым словам
□ Реализовать _find_client_in_text() — поиск имени в тексте
□ Реализовать _find_city_in_text()
□ Реализовать route_business_context() — главная функция
□ Написать тесты в test_business_router.py:
  - "По узаконению дома Иванова" → business=BIZ-001, client=Иванов
  - "Виза для Алматы" → business=BIZ-002, city=Алматы
  - "коучинг сессия" → business=BIZ-003
  - Неоднозначный текст → needs_confirmation=True
□ python3 test_business_router.py
□ Коммит: "feat: business router keyword matching"
```

---

### Фаза 2C: Roadmap Manager — без Telegram (2–3 дня)

**Цель:** Дорожные карты по кейсам.  
**Данные:** хранятся в BUSINESS_SPREADSHEET_ID (листы ROADMAPS + ROADMAP_STAGES).

```
□ Написать business_core/roadmap_manager.py
□ Шаблоны этапов для SVC-001 (гараж) и SVC-003 (дом)
□ create_roadmap() → записать в ROADMAPS
□ advance_stage() → обновить статус + создать GTD Next Action
□ get_roadmap_summary() → текст для Telegram
□ get_overdue_stages()
□ Написать тесты: create → advance → check progress
□ Тест advance_stage(): должен создавать GTD Action через project_planner.py
□ python3 test_roadmap_manager.py
□ Коммит: "feat: roadmap manager"
```

---

### Фаза 2D: Material Manager — без Telegram (1–2 дня)

**Цель:** Привязка файлов к этапам дорожной карты.  
**Опирается на:** GTD REFERENCE sheet (уже работает), Google Drive (уже работает).

```
□ Написать business_core/material_manager.py
□ register_material() → записать в MATERIALS sheet
□ get_materials_by_stage()
□ get_missing_documents()
□ update_material_status()
□ Тест: зарегистрировать материал → найти по этапу → получить список недостающих
□ python3 test_material_manager.py
□ Коммит: "feat: material manager"
```

---

### Фаза 3: Google Drive структура бизнеса (1–2 дня)

**Цель:** Автоматически создавать папки при `create_business_area()`.  
**Требует:** `GDRIVE_BIZ_ROOT_FOLDER_ID` в .env, `GDRIVE_ENABLED=true`.

```
□ Написать integrations/google_drive_adapter.py
□ create_business_folders(biz_id, biz_name) → 12 стандартных папок
□ create_client_folder(biz_id, client_id, client_name)
□ Обновить business_builder.py: вызывать create_business_folders() если GDRIVE_ENABLED
□ Тест: создать структуру для BIZ-TEST, проверить в Drive, удалить
□ Обновить BIZ_REGISTRY: записать drive_folder_url
□ Коммит: "feat: google drive folder structure"
```

---

### Фаза 4: Telegram /business (2–3 дня)

**Цель:** Первые команды Business Core в Telegram-боте.  
**Изменение в telegram_bot.py:** **только 2 строки** в `main()`.

```
□ Написать business_core/bot_handlers.py
□ register_business_handlers(app) — главная функция
□ Реализовать команды:
  /biz_list   — список всех бизнесов
  /people     — справочник людей с фильтрами
  /person X   — карточка человека
  /touch X    — зафиксировать касание
  /roadmap X  — статус дорожной карты
  /client X   — кейс клиента (RM + материалы)
□ Добавить в telegram_bot.py main():
  from business_core.bot_handlers import register_business_handlers
  register_business_handlers(app)
□ python3 -m py_compile telegram_bot.py
□ Перезапустить бота, протестировать /biz_list
□ Коммит: "feat: business core telegram handlers"
```

---

### Фаза 5: Подключение к Inbox-потоку (осторожно, 2–3 дня)

**Цель:** Business Router вызывается после `process_item()`.  
**Это единственный этап с риском — тщательно тестировать.**

```
□ Добавить в .env: BUSINESS_CORE_ENABLED=false  (сначала выключен)
□ В telegram_bot.py handle_message() добавить (после GTD-записи):
  if os.getenv("BUSINESS_CORE_ENABLED") == "true":
      routing = route_business_context(text, result, ...)
      if routing["confidence"] > 0.9:
          # автоматически обогатить запись
      elif routing["needs_confirmation"]:
          # спросить пользователя

□ Протестировать с BUSINESS_CORE_ENABLED=false — GTD работает как раньше
□ Включить BUSINESS_CORE_ENABLED=true
□ Тест с реальными сообщениями:
  "Позвонить Иванову по техпаспорту" → routing=BIZ-001, client=Иванов
□ Проверить: GTD Next Actions создаются корректно
□ Проверить: бизнес-контекст записывается в Notes/заметки
□ Коммит: "feat: business router in inbox flow"
```

---

### Фаза 6: SendPulse / Binotel / WABA / Instagram (по очереди)

**Порядок внедрения интеграций:**

```
6.1 Binotel (пропущенные звонки → GTD):
    □ integrations/binotel_adapter.py
    □ Webhook: пропущенный звонок → GTD Inbox "Перезвонить [номер]"
    □ CDR: запись звонка → Material Manager
    □ Тест: эмулировать webhook, проверить появление в Inbox

6.2 WABA (WhatsApp входящие → GTD):
    □ integrations/waba_adapter.py
    □ Webhook: входящее → GTD Inbox → process_item()
    □ Медиа из WhatsApp → Material Manager
    □ Дедупликация клиентов по номеру телефона

6.3 SendPulse (лиды и рассылки):
    □ integrations/sendpulse_adapter.py
    □ Новая заявка → GTD Inbox
    □ Синхронизация People Registry → адресная книга

6.4 Google Accounts (мультиаккаунт):
    □ integrations/google_accounts_adapter.py
    □ Разные credentials для разных бизнесов

6.5 Instagram (низкий приоритет, после стабилизации):
    □ integrations/instagram_adapter.py
    □ Только если Instagram является основным каналом
```

---

## Итоговая схема системы (v2.0)

```
╔═══════════════════════════════════════════════════════════╗
║                  ПОЛЬЗОВАТЕЛЬ (Telegram)                   ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                            ▼
╔═══════════════════════════════════════════════════════════╗
║         telegram_bot.py — handle_message()                ║
║  Whisper (голос) • Claude Vision (фото/PDF)               ║
║  → INBOX sheet (GTD)                                      ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                            ▼
╔═══════════════════════════════════════════════════════════╗
║       inbox_processor.py — process_item()                 ║
║  Claude claude-sonnet-4-5 (GTD-классификация)             ║
║  → Action / Project / Waiting / Someday / H3/H4/H5        ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                  ┌─────────▼─────────┐
                  │                   │
                  ▼                   ▼
╔═════════════════════╗   ╔══════════════════════════════╗
║  GTD MASTER SYSTEM  ║   ║  BUSINESS ROUTER (Фаза 5)    ║
║  (существующий)     ║   ║  business_core/              ║
║                     ║   ║  business_router.py          ║
║  NEXT ACTIONS       ║   ║                              ║
║  PROJECTS           ║   ║  → business_id               ║
║  WAITING            ║   ║  → service_id                ║
║  SOMEDAY            ║   ║  → client_id                 ║
║  HORIZONS           ║   ║  → roadmap_id                ║
║  ARCHIVE            ║   ║  → stage_id                  ║
║  REFERENCE          ║   ║  → confidence                ║
╚═════════════════════╝   ╚══════════════════════════════╝
          │                            │
          │            ┌───────────────┘
          │            ▼
          │   ╔═════════════════════════════════════╗
          │   ║      BUSINESS CORE Sheets           ║
          │   ║  (BUSINESS_SPREADSHEET_ID)          ║
          │   ║                                     ║
          │   ║  BIZ_REGISTRY  SERVICE_CATALOG      ║
          │   ║  PEOPLE_REGISTRY  CHANNEL_REGISTRY  ║
          │   ║  ROADMAPS  ROADMAP_STAGES            ║
          │   ║  MATERIALS                           ║
          │   ╚══════════╦══════════════════════════╝
          │              │
          │    ┌──────────┼──────────┐
          │    ▼          ▼          ▼
          │  Roadmap   Material  Rel.Capital
          │  Manager   Manager   (Фаза 2C,D)
          │    │          │
          └────┘          ▼
                     Google Drive
                     (Фаза 3)
                          │
                          ▼
                     ┌──────────┐
                     │ Calendar │  ← уже работает
                     └──────────┘
                          │
                          ▼ (Фаза 6)
              SendPulse / Binotel / WABA / Instagram
```

---

*Версия 2.0 — обновлено на основе GTD_CURRENT_WORKFLOW.md*  
*Следующий шаг: Фаза 2A — создать BUSINESS_SPREADSHEET_ID и business_core/sheets.py*
