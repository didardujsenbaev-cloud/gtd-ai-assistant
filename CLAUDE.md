# CLAUDE PROJECT RULES

Перед внесением любых изменений обязательно:

1. Прочитать:

- PROJECT_[CONTEXT.md](http://CONTEXT.md)

- CURRENT_[STATUS.md](http://STATUS.md)

- [ARCHITECTURE.md](http://ARCHITECTURE.md)

- NEXT_[TASKS.md](http://TASKS.md)

2. Изучить существующую архитектуру.

3. Не менять код, пока не станет понятна причина проблемы.

---

## Главные правила

Никогда не менять GTD Core.

Business Core развивается отдельно.

Не изменять:

- inbox_[processor.py](http://processor.py)

- telegram_[bot.py](http://bot.py) (GTD часть)

- [sheets.py](http://sheets.py) (GTD)

- project_[planner.py](http://planner.py)

- calendar_[sync.py](http://sync.py)

если задача относится только к Business Core.

---

## Workflow

Диагностика

↓

План

↓

Минимальный фикс

↓

Тесты

↓

Commit

↓

Deploy

---

## Перед Commit

Обязательно:

- пройти тесты;

- проверить git diff;

- проверить git status;

- убедиться, что .env не изменился.

---

## После Deploy

Проверить Telegram.

Проверить Railway.

Проверить Google Sheets.

---

## Стиль

Минимальные изменения.

Не переписывать большие куски проекта.

Не делать рефакторинг без необходимости.

Не менять архитектуру без согласования.