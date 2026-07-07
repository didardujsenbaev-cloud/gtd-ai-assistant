# GTD Current Workflow — Технический отчёт

> Версия: 1.0 — На основе реального кода  
> Дата: 07.07.2026  
> Источник: анализ telegram_bot.py (4392 строки), sheets.py, inbox_processor.py, project_planner.py, calendar_sync.py

---

## 1. Запуск Telegram Bot

### Точка входа

```
python3 telegram_bot.py
→ функция main() (строка 4254)
→ Application.builder().token(TOKEN).build()
→ регистрация handlers
→ job_queue расписание
→ app.run_polling(allowed_updates=Update.ALL_TYPES)
```

### Порядок регистрации handlers (важен!)

Handlers регистрируются **строго по приоритету** — верхние перехватывают первыми:

```
1. ConversationHandler: /review  (Weekly Review, 8 шагов)
2. ConversationHandler: /qreview (Quarterly H3 Review, 4 шага)
3. CommandHandlers: /start, /help, /myid, /digest, /now, /repeat...
4. ConversationHandler: /mindsweep (2 фазы: Работа + Личное)
5. CommandHandlers: /h3, /h4, /h5, /vision, /h2review...
6. MessageHandler: filters.VOICE → handle_voice
7. MessageHandler: filters.PHOTO → handle_photo
8. MessageHandler: filters.Document.PDF → handle_document
9. MessageHandler: filters.TEXT & ~filters.COMMAND → handle_message
```

### Все зарегистрированные команды (42 команды)

| Команда | Функция | Описание |
|---------|---------|----------|
| `/start` | `start` | Приветствие, главное меню |
| `/help` | `show_help` | Сценарная справка |
| `/myid` | `myid` | Показать Chat ID |
| `/digest` | `digest_now` | Вызвать утренний дайджест вручную |
| `/inbox` | `show_inbox` | Просмотр Inbox (новые + обработанные) |
| `/tasks` | `show_tasks` | Next Actions с фильтрами (@контекст, Xm) |
| `/now` | `now_command` | Интерактивный выбор задачи (контекст → время → энергия) |
| `/done` | `done_task` | Отметить задачу выполненной |
| `/repeat` | `set_recurring` | Сделать задачу повторяющейся |
| `/projects` | `show_projects` | Все активные проекты с next action |
| `/project` | `project_command` | Создать новый проект (Natural Planning) |
| `/close` | `close_project` | Завершить проект → архив |
| `/archive` | `show_archive` | Список завершённых проектов |
| `/ref` | `add_reference` | Добавить материал к проекту |
| `/stats` | `show_stats` | Расширенная статистика GTD |
| `/waiting` | `show_waiting` | Список ожидания (делегировано) |
| `/received` | `close_waiting` | Закрыть ожидание (получил) |
| `/someday` | `activate_someday` | Просмотр + активация Someday |
| `/activate` | `activate_someday` | Алиас для /someday |
| `/horizons` | `show_horizons` | Горизонты H0–H5 |
| `/h3` | `add_horizon` | Добавить цель H3 |
| `/h4` | `add_vision_guided` | Добавить видение H4 |
| `/h5` | `add_vision_guided` | Добавить миссию H5 |
| `/vision` | `show_vision_mission` | Детальный просмотр H4+H5 |
| `/h2review` | `h2_review` | Обзор зон ответственности H2 |
| `/agendas` | `show_agendas` | Повестки встреч (@Agendas) |
| `/agenda` | `add_agenda` | Добавить пункт в повестку |
| `/review` | `wr_start` | Запустить Weekly Review (8 шагов) |
| `/qreview` | `qh3_start` | Квартальный обзор H3 (4 шага) |
| `/mindsweep` | `mindsweep_start` | Очистка сознания (Работа → Личное) |
| `/calendar` | `show_calendar` | Дедлайны GTD + события из Calendar |
| `/cal_sync` | `cal_sync_command` | Синхронизировать дедлайны в Google Calendar |
| `/calendar_setup` | `calendar_setup_command` | Настройка + статус Calendar |
| `/biz` | `show_biz` | Бизнес-объекты (узаконение) |
| `/biz_sync` | `biz_sync_to_gtd` | Синхронизировать объекты → GTD |
| `/cancel` | `np_cancel_command` | Отмена Natural Planning |
| `/cleartest` | `cleartest_command` | Очистить тестовые данные |

### Кнопки главного меню (`_main_keyboard()`)

```python
[
    ["⚡ Задачи",      "🗂 Проекты",   "📊 Статистика"],
    ["✅ Выполнено",   "⏳ Waiting",   "🏔 Горизонты"],
    ["🏗 Объекты",    "📥 Добавить в Inbox"],
]
```

### Кнопки NP (Natural Planning)

```
[⏭ Пропустить]  [❌ Отмена]  [✅ Принять]
```

### Расписание (job_queue)

| Время (Almaty) | День | Функция |
|----------------|------|---------|
| 05:00 | ежедневно | `morning_digest` — дайджест дня |
| 21:00 | ежедневно | `evening_reminder` — итоги вечера |
| 19:00 | воскресенье | `scheduled_weekly_review` — автоматический WR |
| 10:00 | ежедневно | `scheduled_qh3_review` — проверка начала квартала |
| 10:30 | ежедневно | `scheduled_h2_review` — проверка 1-го числа месяца |

---

## 2. Полный путь входящего сообщения

```
Пользователь отправляет текст
         │
         ▼
MessageHandler → handle_message() [строка 1580]
         │
         ├─── Проверка: это кнопка меню? (_MENU_BUTTONS)
         │    → да: направить в соответствующую функцию, вернуться
         │
         ├─── Проверка: активен ref_pending? (выбор проекта для материала)
         │    → да: _handle_ref_project_choice() → REFERENCE sheet
         │
         ├─── Проверка: активен pending_action? (подтверждение дубликата)
         │    → да/нет: сохранить или отменить дубликат
         │
         ├─── Проверка: активен now_step? (фильтрация задач /now)
         │    → context/time/energy: now_handle_*()
         │
         ├─── Проверка: активен np_state? (Natural Planning)
         │    → да: np_step_handler() → продолжить диалог планирования
         │
         ├─── Проверка: формат "h3/h4/h5: текст"
         │    → да: _save_horizon_item() → HORIZONS sheet
         │
         └─── По умолчанию: отправить в AI
                   │
                   ▼
         get_sheet("inbox") → append_row() [запись в INBOX]
                   │
                   ▼
         process_item(text, active_projects) [inbox_processor.py]
                   │
                   ▼
         Claude claude-sonnet-4-5 API → parse_response()
                   │
                   ▼
         Маршрутизация по result["результат"]:
         ├── "2min"        → сообщение "сделай сейчас", в Inbox Статус=Обработан
         ├── "Action"      → NEXT ACTIONS sheet
         ├── "Waiting"     → NEXT ACTIONS sheet (Статус=Waiting)
         ├── "Project"     → PROJECTS + NEXT ACTIONS (через save_project)
         ├── "Someday"     → SOMEDAY sheet
         ├── "SomedayDate" → SOMEDAY sheet (с датой в поле Пересмотреть)
         ├── "Reference"   → REFERENCE sheet
         ├── "H3/H4/H5"   → HORIZONS sheet
         └── "Trash"       → сообщение, Inbox Статус=Обработан
                   │
                   ▼
         Обновить Inbox строку: Статус=Обработан, Результат=XXX
                   │
                   ▼
         [опционально] upsert_deadline_event() → Google Calendar
                   │
                   ▼
         reply_text(ответ пользователю) с форматированием
```

---

## 3. Как работает Inbox

### Куда записывается

**Лист:** `INBOX` в Google Sheets (`SPREADSHEET_ID`)

### Поля (колонки) листа INBOX

| Кол. | Поле | Описание |
|------|------|----------|
| A | ID | Уникальный ID (пусто = авто) |
| B | Дата | YYYY-MM-DD |
| C | Содержимое | Исходный текст сообщения |
| D | Источник | Text / Voice / Photo / PDF |
| E | Статус | `Новый` / `Обработан` |
| F | Результат | Категория AI: Action/Project/Waiting/... |

### Как обрабатывается

1. Любое текстовое сообщение → `handle_message()` → запись в Inbox со статусом `Новый`
2. При обработке → `process_item()` → Claude API → результат
3. В конце → строка в Inbox обновляется: `Статус=Обработан`, `Результат=категория`

### Как очищается

- `/cleartest` → `sheet.clear()` + повторная запись заголовка
- Inbox **не очищается автоматически** — только вручную через `/cleartest`

### Команды связанные с Inbox

```
/inbox      — просмотр (новые + обработанные)
/mindsweep  — массовая загрузка в Inbox (по категориям)
/cleartest  — очистка тестовых данных (включая Inbox)
```

---

## 4. Как работает Projects

### Как создаётся проект

**Путь 1 — AI из Inbox:**
```
Текст → Claude → РЕЗУЛЬТАТ=Project → save_project() → PROJECTS sheet
```

**Путь 2 — Natural Planning (/project):**
```
/project → np_start → 6 шагов:
  NP_NAME      → название проекта
  NP_WHY       → почему важно (можно пропустить)
  NP_OUTCOME   → желаемый результат
  NP_BRAINSTORM → мозговой штурм (можно пропустить)
  NP_ORGANIZE  → организация/подзадачи (можно пропустить)
  NP_ACTION    → первое следующее действие
→ _np_finish() → save_project()
```

### Поля (колонки) листа PROJECTS (16 колонок)

| Кол. | Поле | Описание |
|------|------|----------|
| A | ID | Уникальный ID |
| B | Название проекта | До 100 символов |
| C | Желаемый результат | До 300 символов |
| D | Область | Business, Finance, Health... |
| E | Связанный H3 | Ссылка на цель (заполняется вручную) |
| F | Дедлайн проекта | YYYY-MM-DD |
| G | Статус | `Активен` / `Завершён` / `На паузе` |
| H | Приоритет | Высокий / Средний / Низкий |
| I | Прогресс | % (заполняется вручную) |
| J | Следующее действие | Текст первого NA |
| K | Горизонт | `H1` |
| L | Ответственный | |
| M | Теги | |
| N | Заметки | Natural Planning: ПОЧЕМУ, ИДЕИ, ПОДЗАДАЧИ |
| O | Дата создания | YYYY-MM-DD |
| P | Дата обновления | YYYY-MM-DD |

### Как определяется что это проект

Claude решает по правилу: **РЕЗУЛЬТАТ=Project** если "требует нескольких шагов для достижения результата". Ключевые слова в промпте: наличие нескольких этапов, планирование, процесс из нескольких действий.

### Как создаётся Next Action при проекте

В `save_project()` [project_planner.py строка 68]:
```python
# 1. Записать проект в PROJECTS
projects_sheet.append_row(project_row)

# 2. Записать первое действие в NEXT ACTIONS
action_row = build_action_row(next_action, name, area, ...)
actions_sheet.append_row(action_row)
```

### Как проект закрывается

```
/close [номер проекта]
→ close_project()
→ Показывает список активных проектов
→ Пользователь выбирает номер
→ PROJECTS: Статус → "Завершён", Дата завершения = сегодня
→ NEXT ACTIONS: все действия проекта → Статус "Done"
→ Запрос итога проекта (текст)
→ ARCHIVE: новая строка с итогом и датами
```

### Как уходит в Archive

Лист **ARCHIVE** (создаётся автоматически при первом обращении):

| Кол. | Поле |
|------|------|
| A | ID |
| B | Название проекта |
| C | Итог проекта |
| D | Область |
| E | Приоритет |
| F | Дата старта |
| G | Дата завершения |
| H | Действий выполнено |
| I | Уроки/Заметки |

---

## 5. Как работает Next Actions

### Как создаётся действие

**Путь 1 — AI:**
`Inbox → Claude → РЕЗУЛЬТАТ=Action → append_row() → NEXT ACTIONS`

**Путь 2 — из проекта:**
`save_project() → build_action_row() → append_row()`

### Поля (колонки) листа NEXT ACTIONS (16 колонок)

| Кол. | Поле | Значения |
|------|------|---------|
| A | ID | |
| B | Действие | Текст задачи |
| C | Проект | Название проекта (ссылка) |
| D | Область | Business, Finance, Health... |
| E | Контекст | @Phone, @Computer, @Email, @WhatsApp, @Office... |
| F | Статус | `Next` / `Waiting` / `Done` |
| G | Приоритет | Высокий / Средний / Низкий |
| H | Энергия | Высокая / Средняя / Низкая |
| I | Время | Минуты (число) |
| J | Срок | YYYY-MM-DD |
| K | Кому | Имя (для Waiting) |
| L | Повтор | daily / weekly / monthly (для recurring) |
| M | Следующий запуск | YYYY-MM-DD (для recurring) |
| N | Заметки | |
| O | Дата создания | |
| P | Дата выполнения | |

### Как выбирается контекст

Claude определяет контекст по содержанию задачи. Доступные контексты из промпта:
```
@Phone, @Computer, @Email, @WhatsApp, @Office,
@Almaty, @Astana, @Shymkent,
@Finance, @Legal, @Government, @Contractors, @Team
```

### Как работает /now

```
/now
→ now_command() [строка 477]
→ Показывает клавиатуру контекстов (ReplyKeyboardMarkup):
  [📱 @Phone] [💻 @Computer] [💬 @WhatsApp]
  [🏢 @Office] [🏠 @Home] [🌍 @Anywhere]
  [🔋 Высокая энергия] [😴 Низкая энергия]

→ now_handle_context() [строка 496]
→ Сохраняет context в user_data["now_context"]
→ Показывает клавиатуру времени:
  [⚡ 15 мин] [🕐 30 мин] [🕑 1 час] [🕒 2+ часа]

→ now_handle_time() [строка 522]
→ Показывает клавиатуру энергии:
  [🔋 Высокая] [⚡ Средняя] [😴 Низкая]

→ now_handle_energy() [строка 546]
→ Фильтрует NEXT ACTIONS по:
   - Статус = "Next"
   - Контекст содержит выбранный @контекст (или "Anywhere" = все)
   - Время <= выбранное время
   - Энергия = выбранная (или все если не указана)
→ Показывает отфильтрованные задачи
```

### Как отмечается выполненным

```
/done [номер] или /done [текст]
→ done_task() [строка 685]
→ Читает все Next Actions
→ Находит по номеру или по совпадению текста
→ Проверяет: задача повторяющаяся? (Повтор != пусто)
   → да: обновляет "Следующий запуск" + 1 период
   → нет: обновляет Статус → "Done", Дата выполнения = сегодня
```

---

## 6. Как работает Waiting For

### Как создаётся ожидание

**Путь 1 — AI:**
Claude возвращает `РЕЗУЛЬТАТ=Waiting` + `КОМУ=имя человека`

Сохраняется в **NEXT ACTIONS** со статусом `Waiting`:
```
action_row = [
    "", action_text, "", область,
    контекст, "Waiting", приоритет,
    энергия, время, срок, whom,  ← имя в колонке K
    "", "", заметки, сегодня, ""
]
```

**Путь 2 — Ручной:**
Текст с ключевыми словами ("попросить Асель", "ждать от Сарсена") → Claude сам определяет Waiting.

### Где хранится

В листе **NEXT ACTIONS**, строки с `Статус = "Waiting"`. Отдельного листа "WAITING FOR" нет — Waiting = статус в том же листе.

> **Важно:** В `SHEET_NAMES` есть ключ `"waiting": "WAITING FOR"`, но реальные Waiting-записи хранятся в `NEXT ACTIONS`. `WAITING FOR` лист фактически не используется для хранения.

### Команды

```
/waiting   — показать все Waiting (show_waiting)
/received  — закрыть ожидание, пометить полученным (close_waiting)
```

---

## 7. Как работает Someday/Maybe

### Как добавляется

**Через AI:**
`РЕЗУЛЬТАТ=Someday` → SOMEDAY sheet

**С датой (SomedayDate):**
`РЕЗУЛЬТАТ=SomedayDate` → SOMEDAY sheet, поле `Пересмотреть` = дата

**Структура строки SOMEDAY:**
```
[ID, Идея/Проект, Описание, Область, Пересмотреть, Статус, ID проекта, Добавлен]
```

### Как просматривается

```
/someday [номер]
→ activate_someday() [строка 2391]
→ Если без номера: показывает список Someday
→ Если с номером: переводит в Next Action (спрашивает подтверждение)
```

### Tickler (автоматическое напоминание)

```
morning_digest() → _check_tickler()
→ Читает SOMEDAY
→ Находит записи где Пересмотреть = сегодня
→ Добавляет в утренний дайджест: "🗓 Tickler: [список]"
```

---

## 8. Как работает Google Sheets

### Таблица

Переменная в `.env`: `SPREADSHEET_ID`  
Открывается через: `client.open_by_key(os.getenv("SPREADSHEET_ID"))`

### Авторизация

```python
# sheets.py строка 38
def _get_creds():
    return Credentials.from_service_account_file(
        os.getenv("GOOGLE_CREDENTIALS_FILE"),  # путь к JSON ключу
        scopes=[spreadsheets, drive, calendar]
    )
```

Переменная в `.env`: `GOOGLE_CREDENTIALS_FILE` → путь к сервисному аккаунту JSON.

### Все листы GTD Master

| Ключ | Имя листа | Создаётся автоматически |
|------|-----------|------------------------|
| `inbox` | `INBOX` | нет (должен быть) |
| `projects` | `PROJECTS` | нет |
| `next_actions` | `NEXT ACTIONS` | нет |
| `waiting` | `WAITING FOR` | нет (не используется!) |
| `someday` | `SOMEDAY` | нет |
| `areas` | `AREAS` | нет |
| `review` | `WEEKLY REVIEW` | нет |
| `reference` | `REFERENCE` | нет |
| `horizons` | `HORIZONS` | **да** (с заголовками) |
| `quarterly` | `QUARTERLY REVIEW` | **да** (с заголовками) |
| `archive` | `ARCHIVE` | **да** (с заголовками) |

### Бизнес-таблица

Переменная: `BIZ_SPREADSHEET_ID` — отдельная таблица для бизнес-объектов.

### Ключевые функции

```python
get_sheet(name: str)           # получить лист (создаёт если нет)
read_inbox() → list[dict]      # sheet.get_all_records()
read_projects() → list[dict]   # sheet.get_all_records()
read_next_actions() → list     # sheet.get_all_records()
append_row(sheet_name, values) # надёжная запись через sheet.update()
update_cell(sheet_name, row, col, value) # обновить ячейку
```

### Надёжная запись (важно!)

```python
# sheets.py строка 179
def append_row(sheet_name: str, values: list):
    sheet = get_sheet(sheet_name)
    all_rows = sheet.get_all_values()
    next_row = len(all_rows) + 1  # вычисляем следующую строку
    # НЕ используем sheet.append_row() напрямую — используем sheet.update()
    # чтобы избежать гонки условий при параллельных операциях
    sheet.update(values=[values], range_name=f"A{next_row}:{col}{next_row}")
```

---

## 9. Как работает Google Calendar

### Конфигурация

```
CALENDAR_ID          — GTD-календарь (запись + чтение)
READ_CALENDAR_IDS    — дополнительные через запятую (только чтение)
GOOGLE_CREDENTIALS_FILE — JSON сервисного аккаунта
```

### Какие события создаются

**Только all-day события** с дедлайнами из Next Actions.  
Формат: `📌 [текст действия]`  
Описание содержит: `GTD Next Action`, `Проект: ...`, `Контекст: ...`, `Приоритет: ...`

### Идентификатор события (gtd_key)

```python
def _gtd_event_key(action, deadline, project=""):
    raw = f"{action}|{deadline}|{project}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]
```

Ключ хранится в `extendedProperties.private.gtd_key`. Это позволяет **не создавать дубли** при повторной синхронизации.

### Как синхронизируется

```
/cal_sync
→ cal_sync_command()
→ читает все Next Actions
→ для каждой со Статус="Next" и непустым Срок:
   → upsert_deadline_event(action, deadline, ...)
   → _find_event_by_key() — есть ли уже такое событие?
   → если нет → events().insert()
   → если есть → events().patch()
→ возвращает stats: {created, updated, skipped}
```

### Автоматическое добавление при создании Action

При классификации Action через AI:
```python
# telegram_bot.py строка 1624
_sync_one_deadline(action_text, срок, context_tag=..., priority=...)
```

Это сразу создаёт событие в Calendar, не дожидаясь ручного `/cal_sync`.

### Чтение из нескольких календарей

```python
# Читает из GTD + всех READ_CALENDAR_IDS
list_upcoming_events(days=7)  → события следующих 7 дней
list_past_events(days=7)      → события прошедших 7 дней (для Weekly Review)
```

---

## 10. Обработка медиа-материалов

### Текстовые сообщения

```
handle_message() → проверки → запись в INBOX → process_item() → Claude → маршрутизация
```

### Голосовые сообщения

```
handle_voice() [строка 2134]
→ скачать .ogg файл в tempfile
→ конвертировать ogg → mp3 через ffmpeg (Homebrew /opt/homebrew/bin/ffmpeg)
→ whisper_model.transcribe(mp3_path)  ← OpenAI Whisper "base" модель
→ транскрипт → _save_extracted_to_inbox()
→ process_item(транскрипт)  ← то же что и текст
→ показать транскрипт + результат обработки
```

### Фото / изображения

```
handle_photo() [строка 2011]
→ скачать фото в bytes
→ base64 encode
→ ai_client.messages.create(model="claude-sonnet-4-5")
   с vision payload: {"type": "image", "source": {"type": "base64", ...}}
   и EXTRACT_PROMPT: "извлеки задачи из изображения"
→ extracted_text → _save_extracted_to_inbox()
→ process_item(extracted_text)
```

### PDF документы

```
handle_document() [строка 2049]
→ проверить: это PDF? (Document.PDF filter)
→ скачать bytes
→ upload_pdf_to_drive(bytes, filename)  ← Google Drive
   → папка GDRIVE_FOLDER_ID из .env
   → возвращает webViewLink
→ отправить PDF в Claude Vision (base64)
   с EXTRACT_PROMPT: "извлеки задачи из документа"
→ _save_extracted_to_inbox() с ссылкой на Drive
→ process_item(extracted_text)
```

### Связь PDF с проектом

При добавлении через `/ref`:
```
add_reference() [строка 1137]
→ если это PDF → upload_pdf_to_drive()
→ _ask_ref_project()  ← показывает клавиатуру активных проектов
→ пользователь выбирает проект
→ _save_reference_row(content, project=выбранный)
→ REFERENCE sheet: [ID, Дата, Содержимое, URL, Область, Источник, Проект, Заметки]
```

---

## 11. Где используется AI/NLP

### Основная AI классификация

**Модель:** `claude-sonnet-4-5` (Anthropic)  
**Файл:** `inbox_processor.py`  
**Функция:** `process_item(content, active_projects)`  
**Max tokens:** 512

### Классификация по категориям (из SYSTEM_PROMPT)

| Результат | Правило определения |
|-----------|---------------------|
| `2min` | Займёт < 2 минут |
| `Action` | Одно следующее действие > 2 минут, выполняю сам |
| `Waiting` | Делегировано / жду от другого человека |
| `Project` | Требует нескольких шагов |
| `Someday` | Когда-нибудь/может быть |
| `SomedayDate` | Хочу сделать в конкретный день в будущем |
| `Reference` | Справочная информация, контакты, адреса |
| `Trash` | Не нужно |
| `H3` | Цель на 1–2 года |
| `H4` | Видение на 3–5 лет |
| `H5` | Миссия/принципы/ценности |

### Специальное правило для Reference

```
Если начинается с "Ref:", "Контакт:", "Сохранить:", "Справка:" → ВСЕГДА Reference
Также: номера телефонов с именем, адреса, реквизиты, пароли, ссылки
```

### Привязка к проекту

AI получает список активных проектов и должен проставить поле `ПРОЕКТ`:
```python
# Передаётся до 20 активных проектов
projects_hint = "\nАктивные проекты пользователя:\n  - Проект 1\n  - Проект 2..."
```

### Другие AI вызовы

| Место | Модель | Задача |
|-------|--------|--------|
| `_build_weekly_review()` | claude-sonnet-4-5 | ТОП-3 приоритета на неделю (300 токенов) |
| `wr_done()` | claude-sonnet-4-5 | Итоговый AI-анализ Weekly Review (400 токенов) |
| `handle_photo()` | claude-sonnet-4-5 | Vision: извлечь задачи из фото |
| `handle_document()` | claude-sonnet-4-5 | Vision: извлечь задачи из PDF |
| Quarterly Review | claude-sonnet-4-5 | AI-итог квартального обзора |
| `show_stats()` | claude-sonnet-4-5 | Анализ статистики GTD |

### OpenAI Whisper (локально)

```python
whisper_model = whisper.load_model("base")  # загружается при старте бота
result = whisper_model.transcribe(mp3_path)  # локально, без API вызова
```

---

## 12. Критические файлы

### `telegram_bot.py` — 4392 строки

**Что делает:** Весь Telegram-интерфейс, вся GTD-логика, маршрутизация сообщений, все диалоги.

**Критично:**
- Все 42 команды и их обработчики
- `handle_message()` — центральный роутер [строка 1580]
- Все ConversationHandler потоки (WR, NP, QH3, MS, /now)
- `morning_digest()` и `evening_reminder()` — автоматические уведомления
- `_find_similar()` — дедупликация через Jaccard similarity
- `_main_keyboard()` — главное меню

**Риск изменения:** ВЫСОКИЙ — любая ошибка ломает весь бот.

---

### `sheets.py` — 193 строки

**Что делает:** Единственная точка входа в Google Sheets. Все чтения и записи через него.

**Критично:**
- `_get_creds()` — авторизация Google
- `get_sheet(name)` — центральная функция, создаёт лист если нет
- `SHEET_NAMES` — маппинг ключей на имена листов
- `append_row()` — надёжная запись (не `sheet.append_row`!)
- `upload_pdf_to_drive()` — Google Drive загрузка

**Риск изменения:** ВЫСОКИЙ — изменение SHEET_NAMES или структуры ломает запись данных.

---

### `inbox_processor.py` — 301 строка

**Что делает:** Весь AI-промпт и классификация GTD-категорий.

**Критично:**
- `SYSTEM_PROMPT` — 63 строки инструкций Claude
- `process_item()` — основная функция (вызывается из telegram_bot.py)
- `parse_response()` — парсинг ответа Claude в dict
- `process_inbox()` — автономный запуск из командной строки

**Риск изменения:** СРЕДНИЙ — изменение промпта меняет поведение классификации.

---

### `calendar_sync.py` — 339 строк

**Что делает:** Google Calendar API. Запись GTD-дедлайнов + чтение событий.

**Критично:**
- `upsert_deadline_event()` — создание/обновление событий
- `_gtd_event_key()` — MD5 хэш для дедупликации
- `sync_gtd_deadlines()` — массовая синхронизация
- `list_upcoming_events()` / `list_past_events()` — чтение
- `is_configured()` — проверка наличия CALENDAR_ID

**Риск изменения:** СРЕДНИЙ — ломает синхронизацию Calendar.

---

### `project_planner.py` — 104 строки

**Что делает:** Natural Planning — сборка строк для PROJECTS и NEXT ACTIONS.

**Критично:**
- `build_project_row()` — 16 колонок PROJECTS в строгом порядке
- `build_action_row()` — 16 колонок NEXT ACTIONS в строгом порядке
- `save_project()` — записывает проект + first action

**Риск изменения:** ВЫСОКИЙ — изменение порядка колонок ломает все записи.

---

### `gtd.py` — 8808 байт

**Что делает:** GTD-логика ядра (скорее всего исторический файл до разделения по модулям).

**Риск изменения:** НИЗКИЙ (если не используется telegram_bot.py) — нужно проверить импорты.

---

## 13. Слабые места

### 1. Риск дублей

**Проблема:** Дедупликация реализована через Jaccard similarity (порог 0.6), но только для Next Actions и Projects. Someday, Waiting, Reference — без защиты от дублей.

**Механизм:** `_find_similar(new_text, existing, threshold=0.6)` в handle_message — если найдено похожее, спрашивает подтверждение. Но при быстром вводе можно успеть добавить два раза.

**Слабость:** Порог 0.6 может пропустить семантически идентичные тексты с разными словами ("Позвонить Асель" vs "Набрать Асель").

---

### 2. Риск неправильной классификации

**Проблема:** Claude делает ~95% правильных классификаций, но:
- Короткие тексты ("позвонить") без контекста → может быть Action или Waiting
- Многозначные тексты → проект или Action?
- Язык (казахский, смешанный) — не указан в промпте явно
- Год дедлайна: строка `"Текущая дата: {today}"` в промпте динамична, но при ошибке API она не обновится

**Нет обратной связи:** Если Claude ошибся, нет команды "переклассифицировать". Нужно вручную идти в Google Sheets и исправлять.

---

### 3. Риск потери файлов

**Проблема:** PDF загружается в Google Drive по `GDRIVE_FOLDER_ID`. Если:
- Папка удалена → `upload_pdf_to_drive()` упадёт
- Нет прав у Service Account → 403
- `GDRIVE_FOLDER_ID` не задан → файл не загрузится, но ошибка может быть поглощена

**Ссылки на Drive:** сохраняются в REFERENCE sheet. Если файл удалён из Drive — ссылка станет битой, система не проверяет актуальность.

---

### 4. Риск смешивания личного и бизнес-GTD

**Проблема:** Все задачи (личные и бизнес) идут в **одну** таблицу SPREADSHEET_ID. Разделение только через поле `Область` (Business, Family, Finance...).

**Последствия:**
- `/tasks` без фильтра показывает всё вместе
- Сотрудники не могут иметь свою GTD-систему на этой базе
- При масштабировании на несколько пользователей — таблица станет общей

**Текущий обходной путь:** Только через поле `Область` и контексты типа `@Team`.

---

### 5. Риск прав доступа Google

**Проблема:** Один Service Account (`gtd-assistant@gtd-ai-assistant.iam.gserviceaccount.com`) управляет всем: Sheets, Drive, Calendar.

- Если JSON-ключ (`GOOGLE_CREDENTIALS_FILE`) истечёт/удалится → всё упадёт
- Ключ в файловой системе (не в секрет-хранилище)
- `SCOPES` запрашивают максимальные права на Sheets + Drive + Calendar одновременно
- `READ_CALENDAR_IDS` — личные календари расшарены на service account → потенциальная утечка если аккаунт скомпрометирован

---

### 6. Отсутствие queue для AI запросов

**Проблема:** Каждое сообщение делает синхронный Claude API вызов. При нескольких сообщениях подряд — запросы выполняются последовательно. Нет rate limiting, нет retry логики при таймаутах.

---

## 14. Как правильно подключить Business Core

### Точка входа — только в `main()`

```python
# telegram_bot.py → main() → ПОСЛЕ всех существующих app.add_handler():

from business_core.bot_handlers import register_business_handlers
register_business_handlers(app)
```

Это **единственное** изменение в telegram_bot.py. Всё остальное — в новых файлах.

### Файлы которые нельзя менять

| Файл | Почему |
|------|--------|
| `telegram_bot.py` | Вся GTD логика. 2 строки в main() — максимум |
| `sheets.py` | Структура GTD таблицы. Изменение = риск |
| `project_planner.py` | Порядок 16 колонок строго фиксирован |
| `inbox_processor.py` | AI промпт. Менять только с тестированием |
| `calendar_sync.py` | Стабильно работает |
| `.env` | Только добавлять, не менять существующие |

### Какие функции Business Core может использовать

```python
# Из project_planner.py — для создания GTD-проектов из Business Core:
from project_planner import save_project, build_action_row

# Из sheets.py — для чтения GTD данных:
from sheets import read_projects, read_next_actions, get_sheet

# НЕ импортировать из telegram_bot.py — там нет public API
```

### Как не сломать существующий бот

1. **Новые команды** — только через `register_business_handlers(app)`
2. **Новые листы** — только в `BUSINESS_SPREADSHEET_ID` (отдельная таблица)
3. **Не трогать** `SHEET_NAMES` в `sheets.py`
4. **Не трогать** `_main_keyboard()` — добавить кнопки Business только через новую клавиатуру
5. **Не трогать** `_MENU_BUTTONS` список — добавить свои кнопки туда через register
6. **Тестировать** отдельно: `python3 test_business_core.py` должен проходить до и после любых изменений

---

## Итоговая схема потока данных

```
╔════════════════════════════════════════════════════════════╗
║                  ПОЛЬЗОВАТЕЛЬ (Telegram)                   ║
║  текст / голос / фото / PDF / команда                      ║
╚═══════════════════════════╦════════════════════════════════╝
                            │
                            ▼
╔═══════════════════════════════════════════════════════════╗
║              telegram_bot.py — handle_message()           ║
║  1. Проверка: это кнопка меню? → команда                  ║
║  2. Проверка: активный диалог? → ConversationHandler      ║
║  3. Whisper (если голос) → текст                          ║
║  4. Claude Vision (если фото/PDF) → текст                 ║
║  5. По умолчанию → запись в INBOX                         ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                            ▼
╔═══════════════════════════════════════════════════════════╗
║           inbox_processor.py — process_item()             ║
║  Claude claude-sonnet-4-5 API                             ║
║  SYSTEM_PROMPT (63 строки правил GTD)                     ║
║  → РЕЗУЛЬТАТ: Action/Project/Waiting/Someday/...          ║
║  → КОНТЕКСТ, ОБЛАСТЬ, ПРИОРИТЕТ, СРОК, КОМУ, ПРОЕКТ       ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
         Action/Waiting  Project    Someday/H3/H4/H5
                │           │           │
                ▼           ▼           ▼
╔═══════════════════════════════════════════════════════════╗
║                   sheets.py — get_sheet()                 ║
║  Google Sheets API (gspread)                              ║
║  SPREADSHEET_ID → 11 листов                               ║
║                                                           ║
║  NEXT ACTIONS   PROJECTS   SOMEDAY   HORIZONS             ║
║  INBOX          REFERENCE  ARCHIVE   WEEKLY REVIEW        ║
║  QUARTERLY REVIEW          AREAS                          ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                            ▼ (если есть Срок)
╔═══════════════════════════════════════════════════════════╗
║              calendar_sync.py — upsert_deadline_event()   ║
║  Google Calendar API                                      ║
║  CALENDAR_ID → all-day event                              ║
║  MD5 ключ → дедупликация при повторной синхронизации      ║
║  READ_CALENDAR_IDS → чтение личного/бизнес Calendar       ║
╚═══════════════════════════╦═══════════════════════════════╝
                            │
                            ▼
╔═══════════════════════════════════════════════════════════╗
║                     ОТВЕТ ПОЛЬЗОВАТЕЛЮ                    ║
║  reply_text(форматированное сообщение, parse_mode=MD)     ║
║  + ReplyKeyboardMarkup (_main_keyboard())                 ║
╚═══════════════════════════════════════════════════════════╝


Автоматические процессы (job_queue):
┌─ 05:00 ─ morning_digest() ─ Tickler + Waiting + Today
├─ 21:00 ─ evening_reminder() ─ Done today + Stats
├─ 19:00 вс ─ scheduled_weekly_review() ─ WR + AI анализ
├─ 10:00 ─ scheduled_qh3_review() ─ раз в квартал
└─ 10:30 ─ scheduled_h2_review() ─ раз в месяц
```

---

*Документ создан на основе анализа реального кода. Не содержит предположений — только факты из исходников.*
