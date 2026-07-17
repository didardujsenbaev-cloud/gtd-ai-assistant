# CURRENT STATUS

## Статус проекта

Business Core работает.

Telegram Bot работает.

Railway работает.

Google Sheets подключены.

Google Drive подключен.

Business Registry работает.

People Registry работает.

Objects работают.

Services работают.

Roadmaps работают.

Stages работают.

---

## Реализовано

- Business Core

- Telegram команды

- Автоматическое создание клиентов

- Автоматическое создание объектов

- Автоматическое создание услуг

- Автоматическое создание Roadmap

- Commercial Milestones

- Google Drive Folder

- Google Sheets Registry

---

## BUG-001 — закрыт

Проблема:

Roadmap, созданный с явным template_id (например RMT-IZH-ALM-STANDARD-002),

позже в /milestones определялся как другой шаблон

(RMT-IZH-ALM-LEGALIZATION-001), либо (после промежуточного фикса)

как OBJ-001 — значение колонки Object ID.

Причина:

1. template_id не сохранялся в листе ROADMAPS — /milestones пересчитывал

   его заново через эвристику и получал шаблон по умолчанию для услуги.

2. После добавления колонки Template ID запись в ROADMAPS велась

   позиционно, без учёта фактических заголовков живого листа —

   из-за исторического расхождения между кодом и реальными заголовками

   новая колонка легла на данные Object ID.

Исправлено:

- create_roadmap_for_object и find_roadmap_by_id читают и пишут

  ROADMAPS по фактическим именам заголовков, а не по позиции.

- /milestones исправлен: _resolve_template_id приоритетно использует

  сохранённый template_id.

- Добавлена безопасная идемпотентная миграция заголовков ROADMAPS

  (migrate_roadmaps_headers.py, dry-run по умолчанию, требует YES

  для live-запуска, меняет только строку заголовков).

- Миграция заголовков ROADMAPS выполнена в проде (--live, подтверждено YES).

  Заголовки 25–28 приведены к: Object ID, Parent Roadmap ID, Case Type,

  Template ID. Ни одна строка данных не изменена (27/27 строк идентичны).

- Проверено на roadmap RM-027: template_id читается как

  RMT-IZH-ALM-STANDARD-002, /milestones (get_commercial_milestones_for_roadmap)

  возвращает 3 коммерческих этапа (950 000 тг) корректно.

Статус:

Закрыто.

---

## Phase 9A–9E.2 — Stage Management и Roadmap Engine

Завершена серия фаз, построившая полноценный Sheets-backed движок

этапов и прогресса Roadmap поверх фундамента, заложенного при

исправлении BUG-001.

### Phase 9A — ROADMAP_STAGES schema/header migration

Живой лист ROADMAP_STAGES имел только 12 подписанных заголовков,

хотя код (create_stages_from_template_record) годами писал 5

дополнительных знаниевых полей (SOP IDs, Checklist IDs, Materials IDs,

Document Template IDs, FAQ IDs) в колонки 13–17 без подписей.

Добавлена safe idempotent миграция (migrate_roadmap_stages_headers.py,

тот же паттерн dry-run/YES, что и для ROADMAPS) и выполнена в проде.

Данные не затронуты.

### Phase 9B — канонические статусы этапов и /updatestage

Введён единственный канонический словарь статусов реального этапа:

pending, in_progress, blocked, done, skipped.

Добавлены find_stage_by_id() и update_stage_status_in_sheet()

(header-safe, пишут только Status и, при явной передаче, Notes).

Добавлена команда /updatestage stage_id=... status=... [notes=...].

Legacy-значения (not_started, waiting, completed как статус этапа)

не принимаются на запись, но существующие этапы с такими статусами

читаются без ошибок.

### Phase 9C — расчёт Progress %

Добавлены calculate_progress() (чистая функция) и

recalculate_roadmap_progress() (Sheets-backed, пишет только Progress %).

Формула и решения по skipped/округлению зафиксированы в DECISIONS.md

(ADR: Progress Calculation).

### Phase 9D — /recalcprogress

Добавлена команда ручного пересчёта Progress % без изменения других

полей: /recalcprogress roadmap_id=RM-xxx.

### Phase 9E.1 — автоматический пересчёт после изменения этапа

/updatestage теперь автоматически вызывает recalculate_roadmap_progress

после успешного изменения статуса этапа. Ответ показывает старый и

новый Progress %.

### Phase 9E.2 — автоматическое завершение Roadmap

Добавлены should_complete_roadmap() (чистая функция) и

maybe_complete_roadmap() (Sheets-backed, пишет только Status,

только active → completed). /updatestage автоматически переводит

Roadmap в completed, когда прогресс достигает 100% при всех этапах

в done/skipped. Правила зафиксированы в DECISIONS.md

(ADR: Roadmap Automatic Completion).

### Текущая рабочая цепочка

```
/startroadmap
  → создание Roadmap (create_roadmap_for_object)
  → создание Stages (create_stages_from_template_record /
                      create_roadmap_stages_from_template)

/updatestage stage_id=... status=...
  → update_stage_status_in_sheet   (Status/Notes этапа)
  → recalculate_roadmap_progress   (Progress % roadmap)
  → maybe_complete_roadmap         (active → completed, если готово)
```

Каждый шаг header-safe (пишет по имени колонки, не по позиции),

идемпотентен и не трогает поля за пределами своей ответственности.

### Текущий статус

Phase 9 завершена.

Phase 10.1 (Core Architecture Audit, read-only) завершён — см.

DECISIONS.md и NEXT_TASKS.md.

Следующая техническая фаза — Phase 10.2B (Header-safe refactoring

оставшихся позиционных записей в create_stages_from_template_record,

create_roadmap_template, add_roadmap_template_stage,

create_object_record и /newroadmap).

---

## Правило

Перед изменением кода:

1. Анализ.

2. План.

3. Изменения.

4. Тесты.

5. Commit.

6. Deploy.