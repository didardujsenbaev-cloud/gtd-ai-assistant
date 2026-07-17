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

## Правило

Перед изменением кода:

1. Анализ.

2. План.

3. Изменения.

4. Тесты.

5. Commit.

6. Deploy.