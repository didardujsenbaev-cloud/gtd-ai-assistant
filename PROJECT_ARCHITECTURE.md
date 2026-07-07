# GTD AI Assistant — Архитектура проекта

> Дата анализа: 07.07.2026  
> Версия: production (4392 строк основного модуля)

---

## 1. Как запускается Telegram Bot

```bash
source venv/bin/activate
python3 telegram_bot.py
```

Точка входа — функция `main()` в конце `telegram_bot.py`:
- Создаёт `Application` через `python-telegram-bot`
- Регистрирует все `CommandHandler` и `MessageHandler`
- Запускает `job_queue` для автоматических задач:
  - `morning_digest` — каждый день в **05:00** (Asia/Almaty)
  - `evening_reminder` — каждый день в **21:00**
  - `scheduled_weekly_review` — каждое воскресенье в **19:00**
  - `scheduled_qh3_review` — 1-й день квартала в **10:00**
  - `scheduled_h2_review` — 1-е число месяца в **10:30**
- Запускает polling: `app.run_polling()`

---

## 2. Основная логика GTD

Вся GTD-логика сосредоточена в **`telegram_bot.py`** (4392 строки).

### Ключевые блоки:

| Блок | Строки | Описание |
|------|--------|----------|
| Состояния ConversationHandler | 27–43 | WR, NP, QH3, MS состояния |
| Утренний/вечерний дайджест | ~1682–2305 | `morning_digest`, `evening_reminder` |
| Natural Planning (NP) | ~1105–1400 | 6-шаговый конструктор проектов |
| Weekly Review | ~3418–3700 | 7-шаговый обзор |
| Quarterly H3 Review | ~2930–3080 | Ежеквартальный обзор целей |
| Mind Sweep | ~3180–3244 | Очистка сознания |
| Горизонты H0–H5 | ~2075–2530 | Пирамида фокуса |
| Дубликаты | ~233–255 | `_find_similar()` — Jaccard |
| /now интерактив | ~357–482 | 3-шаговый выбор задачи |

---

## 3. Интеграция с Google Sheets

**Файл:** `sheets.py`

### Архитектура:
```
sheets.py
├── _get_creds()          → credentials из .env (JSON-файл)
├── get_client()          → gspread авторизация
├── get_spreadsheet()     → личный GTD Spreadsheet (SPREADSHEET_ID)
├── get_biz_spreadsheet() → бизнес-таблица (BIZ_SPREADSHEET_ID)
├── get_sheet(name)       → лист по короткому имени
├── upload_pdf_to_drive() → PDF → Google Drive (GDRIVE_FOLDER_ID)
└── read_*()              → чтение конкретных листов
```

### Листы GTD Master System:
| Ключ | Название листа | Назначение |
|------|---------------|------------|
| `inbox` | INBOX | Входящие до обработки |
| `projects` | PROJECTS | Активные/завершённые проекты |
| `next_actions` | NEXT ACTIONS | Следующие действия |
| `waiting` | WAITING FOR | Делегированные задачи |
| `someday` | SOMEDAY | Когда-нибудь/может быть |
| `areas` | AREAS | 16 зон ответственности (H2) |
| `review` | WEEKLY REVIEW | История еженедельных обзоров |
| `reference` | REFERENCE | Справочные материалы |
| `horizons` | HORIZONS | H3/H4/H5 цели, видение, миссия |
| `quarterly` | QUARTERLY REVIEW | Квартальные обзоры |
| `archive` | ARCHIVE | Завершённые проекты |

### Бизнес-таблица (Узаконение):
| Лист | Описание |
|------|----------|
| `Действущие обекты` | Список объектов недвижимости |
| `UZ-XXXX` | Отдельный лист на каждый объект со шагами |

---

## 4. Интеграция с Google Calendar

**Файл:** `calendar_sync.py`

```
calendar_sync.py
├── _gtd_calendar_id()      → CALENDAR_ID (только запись)
├── _read_calendar_ids()    → все календари для чтения
├── upsert_deadline_event() → создать/обновить дедлайн в GTD-кал.
├── sync_gtd_deadlines()    → синхронизировать все Next Actions
├── list_upcoming_events()  → события на N дней вперёд
├── list_past_events()      → события за N дней назад
├── list_calendars_status() → статус всех календарей
└── format_calendar_summary() → текст для /calendar
```

### Конфигурация (.env):
- `CALENDAR_ID` — GTD-календарь (чтение + запись)
- `READ_CALENDAR_IDS` — дополнительные через запятую (только чтение)

---

## 5. Обработка Inbox

**Файл:** `inbox_processor.py`

### Поток обработки:
```
Текст/Голос/Фото/PDF
        ↓
    Inbox Sheet
        ↓
  process_item(text, active_projects)
        ↓ Claude claude-sonnet-4-5
        ↓
  parse_response() → dict
        ↓
Маршрутизация по результату:
  2min      → уведомление "сделай сейчас"
  Action    → NEXT ACTIONS (с проверкой дубликатов)
  Waiting   → NEXT ACTIONS (статус Waiting, поле Кому)
  Project   → Natural Planning → PROJECTS + NEXT ACTIONS
  Someday   → SOMEDAY
  SomedayDate → SOMEDAY (с датой в колонке Пересмотреть)
  Reference → REFERENCE
  H3/H4/H5  → HORIZONS (с полем Область)
  Trash     → уведомление "можно удалить"
```

### AI-промпт включает:
- 11 категорий результата
- Список активных проектов (для привязки Action → Проект)
- Динамическую текущую дату
- Поля: действие, контекст, область, приоритет, время, срок, кому, проект, энергия

---

## 6. Создание проектов и задач

**Файл:** `project_planner.py`

```python
save_project(name, outcome, area, priority, next_action, context_tag, ...)
```

Создаёт **одновременно**:
1. Строку в PROJECTS (16 колонок) через `build_project_row()`
2. Строку в NEXT ACTIONS (16 колонок) через `build_action_row()`

### Natural Planning (в `telegram_bot.py`):
6-шаговый ConversationHandler:
1. `NP_NAME` — название проекта
2. `NP_WHY` — зачем (миссия шага)
3. `NP_OUTCOME` — желаемый результат
4. `NP_BRAINSTORM` — мозговой штурм
5. `NP_ORGANIZE` — организация
6. `NP_ACTION` — первое следующее действие

---

## 7. Все Google Sheets

### Личный GTD (SPREADSHEET_ID):
```
GTD Master System
├── INBOX
├── PROJECTS
├── NEXT ACTIONS
├── WAITING FOR
├── SOMEDAY
├── AREAS
├── WEEKLY REVIEW
├── REFERENCE
├── HORIZONS
├── QUARTERLY REVIEW
└── ARCHIVE
```

### Бизнес Узаконение (BIZ_SPREADSHEET_ID):
```
GTD Biz · Узаконение
├── Действущие обекты
├── UZ-2026-01  (отдельный объект)
├── UZ-2026-02
└── ...
```

### Google Drive:
- Папка `GDRIVE_FOLDER_ID` — хранение PDF-файлов

---

## 8. Все команды Telegram

### Capture & Process
| Команда | Функция |
|---------|---------|
| (любой текст) | `handle_message()` → AI → Inbox |
| (голос) | `handle_voice()` → Whisper → Inbox |
| (фото) | `handle_photo()` → Claude Vision → Inbox |
| (PDF) | `handle_document()` → Claude → Drive + Inbox |
| `/inbox` | `show_inbox()` — просмотр Inbox |

### Tasks & Actions
| Команда | Функция |
|---------|---------|
| `/now` | `now_command()` — интерактивный выбор |
| `/tasks` | `show_tasks()` — фильтр по контексту/энергии/времени |
| `/done` | `done_task()` — отметить выполненным |
| `/repeat` | `set_recurring()` — повторяющаяся задача |
| `/waiting` | `show_waiting()` — список ожидания |
| `/received` | `close_waiting()` — получено |

### Projects
| Команда | Функция |
|---------|---------|
| `/projects` | `show_projects()` — список + застрявшие |
| `/project` | `project_command()` — Natural Planning |
| `/close` | `close_project()` — завершить → архив |
| `/archive` | `show_archive()` — история проектов |
| `/ref` | `add_reference()` — материалы к проекту |

### Someday & Ideas
| Команда | Функция |
|---------|---------|
| `/someday` | `activate_someday()` — список |
| `/activate` | `activate_someday()` — активировать идею |

### Horizons
| Команда | Функция |
|---------|---------|
| `/horizons` | `show_horizons()` — пирамида H0–H5 |
| `/vision` | `show_vision_mission()` — H4+H5 по областям |
| `/h3` | `add_horizon()` — добавить цель |
| `/h4` | `add_vision_guided()` — добавить видение |
| `/h5` | `add_vision_guided()` — добавить миссию |

### Reviews
| Команда | Функция |
|---------|---------|
| `/review` | `wr_start()` — Weekly Review (7 шагов) |
| `/qreview` | `qh3_start()` — Quarterly H3 Review |
| `/h2review` | `h2_review()` — обзор зон ответственности |
| `/mindsweep` | `mindsweep_start()` — очистка сознания |
| `/agendas` | `show_agendas()` — повестки встреч |
| `/agenda` | `add_agenda()` — добавить повестку |

### Analytics & System
| Команда | Функция |
|---------|---------|
| `/stats` | `show_stats()` — полная аналитика |
| `/digest` | `digest_now()` — дайджест прямо сейчас |
| `/calendar` | `show_calendar()` — события + дедлайны |
| `/cal_sync` | `cal_sync_command()` — синхронизация |
| `/calendar_setup` | `calendar_setup_command()` — статус |
| `/help` | `show_help()` — справка по сценариям |
| `/start` | `start()` — приветствие |

### Business (Узаконение)
| Команда | Функция |
|---------|---------|
| `/biz` | `show_biz()` — список объектов |
| `/biz_sync` | `biz_sync_to_gtd()` — синхронизация |

### Dev/Admin
| Команда | Функция |
|---------|---------|
| `/cleartest` | `cleartest_command()` — очистка тестовых данных |
| `/myid` | `myid()` — получить Telegram chat_id |

---

## 9. Критические файлы

| Файл | Критичность | Почему нельзя трогать без осторожности |
|------|-------------|----------------------------------------|
| `telegram_bot.py` | 🔴 Максимальная | 4392 строки, вся логика. Любое изменение требует `python3 -m py_compile` после |
| `sheets.py` | 🔴 Максимальная | Структура листов. Изменение `SHEET_NAMES` ломает существующие данные в Google Sheets |
| `inbox_processor.py` | 🟡 Высокая | AI-промпт. Изменение формата ломает парсинг |
| `calendar_sync.py` | 🟡 Высокая | Google Calendar API. Ошибка = потеря дедлайнов |
| `project_planner.py` | 🟡 Высокая | Структура строк проектов/задач (16 колонок) |
| `.env` | 🔴 Максимальная | API ключи, ID таблиц. Никогда не коммитить в git |
| `*.json` (credentials) | 🔴 Максимальная | Service account ключ Google. Хранить локально |

### Правила безопасного изменения:
1. После каждого изменения: `python3 -m py_compile telegram_bot.py`
2. Новые листы добавлять только в `SHEET_NAMES` dict в `sheets.py`
3. Новые колонки в листах не ломают существующий код (gspread читает по именам)
4. Изменение AI-промпта требует обновления `parse_response()` в `inbox_processor.py`

---

## 10. Безопасный план добавления модуля `business-automation`

### Принцип: **новый файл, без изменений в существующих**

```
gtd-ai-assistant/
├── telegram_bot.py          ← НЕ ТРОГАТЬ основную логику
├── sheets.py                ← добавить только новые ключи в SHEET_NAMES
├── inbox_processor.py       ← не трогать
├── calendar_sync.py         ← не трогать
├── project_planner.py       ← не трогать
│
├── business_automation.py   ← НОВЫЙ ФАЙЛ (вся новая логика)
├── business_sheets.py       ← НОВЫЙ ФАЙЛ (схема бизнес-листов)
└── business_bot.py          ← НОВЫЙ ФАЙЛ (отдельный Telegram Bot)
```

### Шаг 1 — Новый файл `business_automation.py`
```python
# Импортирует из sheets.py через get_sheet() — безопасно
from sheets import get_sheet, get_client
# НЕ импортирует из telegram_bot.py — избегаем циклических зависимостей
```

### Шаг 2 — Добавить листы в `sheets.py` (минимально)
```python
SHEET_NAMES = {
    # ... существующие ...
    "biz_tasks":     "BIZ TASKS",      # задачи по бизнесам
    "biz_employees": "BIZ EMPLOYEES",  # сотрудники
    "biz_reports":   "BIZ REPORTS",    # отчёты
}
```

### Шаг 3 — Отдельный Telegram Bot (`business_bot.py`)
```python
# Запускается независимо от GTD бота
# python3 business_bot.py
# Свой BOT_TOKEN в .env: BIZ_BOT_TOKEN=...
```

### Шаг 4 — Минимальная интеграция с GTD ботом
Добавить в конец `telegram_bot.py` **только регистрацию хендлеров**:
```python
# В main() — в самом конце, после всех существующих хендлеров
from business_automation import register_biz_handlers
register_biz_handlers(app)  # добавляет /biz_team, /delegate, etc.
```

### Архитектура интеграции:
```
GTD Bot (личный)          Business Bot (командный)
     ↓                            ↓
 sheets.py ←──────────────── business_automation.py
     ↓                            ↓
Google Sheets             Telegram Group Chats
  (общая БД)               (уведомления команде)
```

### Что НЕ делать:
- ❌ Не добавлять бизнес-логику в `telegram_bot.py` (он уже 4392 строки)
- ❌ Не менять структуру существующих листов
- ❌ Не создавать циклические импорты
- ❌ Не хранить секреты нигде кроме `.env`

---

## Зависимости (ключевые библиотеки)

```
python-telegram-bot  — Telegram Bot API
gspread              — Google Sheets API
anthropic            — Claude AI (claude-sonnet-4-5)
openai-whisper       — голосовая транскрипция
google-api-python-client — Calendar + Drive API
pytz                 — временные зоны (Asia/Almaty)
python-dotenv        — конфигурация из .env
```

---

## Переменные окружения (.env)

| Переменная | Назначение |
|-----------|-----------|
| `GOOGLE_CREDENTIALS_FILE` | Путь к JSON service account |
| `SPREADSHEET_ID` | ID личного GTD Google Sheets |
| `BIZ_SPREADSHEET_ID` | ID бизнес-таблицы (Узаконение) |
| `ANTHROPIC_API_KEY` | Claude API ключ |
| `TELEGRAM_BOT_TOKEN` | Токен GTD бота |
| `TELEGRAM_CHAT_ID` | Chat ID владельца (для дайджестов) |
| `GDRIVE_FOLDER_ID` | Папка для PDF в Google Drive |
| `GDRIVE_IS_SHARED_DRIVE` | true/false |
| `BIZ_OWNER_NAME` | Имя владельца для отчётов |
| `CALENDAR_ID` | GTD Google Calendar (запись) |
| `READ_CALENDAR_IDS` | Доп. календари через запятую (чтение) |
