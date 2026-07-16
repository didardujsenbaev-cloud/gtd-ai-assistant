# GTD AI Assistant

Единая операционная система для личного GTD и управления бизнесами.

Проект объединяет:

- GTD Core

- Business Core

- Telegram Bot

- Google Sheets

- Google Drive

- Railway

- SendPulse

- Binotel

---

## Основные контуры

### GTD Core

Личная система управления:

- Inbox

- Projects

- Next Actions

- Calendar

- Reference

- Horizons

GTD Core нельзя менять в задачах, относящихся только к Business Core.

### Business Core

Операционная система бизнеса:

Business  

→ Client  

→ Object  

→ Service  

→ Roadmap  

→ Stages

Также включает:

- Knowledge Core

- SOP

- Checklists

- Commercial Milestones

- Documents

- Contractors

- Reports

---

## Роли систем

### Business Core

Источник истины по:

- клиентам;

- объектам;

- услугам;

- производственным процессам;

- ответственным;

- статусам работы.

### Google Sheets

Текущая база данных Business Core.

### Google Drive

Хранение документов, фото, файлов и папок клиентов.

### Telegram Bot

Рабочий интерфейс владельца и сотрудников.

### SendPulse

Продажи, переписка, CRM-воронка и WABA.

### Binotel

Телефония, звонки и записи разговоров.

### Railway

Развёртывание и постоянная работа Telegram-бота.

---

## Технологии

- Python

- python-telegram-bot

- Google Sheets API

- Google Drive API

- Railway

- Git

- GitHub

- Cursor

- Claude

- ChatGPT

---

## Структура документации

Перед работой с проектом обязательно прочитать:

1. `PROJECT_CONTEXT.md`

2. `ARCHITECTURE.md`

3. `CURRENT_STATUS.md`

4. `NEXT_TASKS.md`

5. `DECISIONS.md`

6. `CLAUDE.md`

---

## Главные правила разработки

1. Не ломать GTD Core.

2. Не менять `.env`.

3. Не менять архитектуру без отдельного решения.

4. Не создавать новые таблицы без необходимости.

5. Сначала диагностика.

6. Потом минимальный фикс.

7. Затем тесты.

8. Потом commit.

9. Потом deploy.

10. После deploy проверить Telegram и Railway.

---

## Запрещённые изменения без отдельного согласования

Не менять GTD Core файлы:

- `telegram_bot.py`

- `sheets.py`

- `inbox_processor.py`

- `project_planner.py`

- `calendar_sync.py`

Исключение — только точечное подключение Business Core по уже существующей архитектуре.

---

## Локальный запуск

Перейти в папку проекта:

```bash

cd ~/Desktop/gtd-ai-assistant