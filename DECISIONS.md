# ARCHITECTURE DECISIONS

## ADR-001 — GTD Core и Business Core разделены

Решение:

GTD Core отвечает за личную систему задач.

Business Core отвечает за бизнесы, клиентов, объекты, услуги, roadmap и производство.

Причина:

Нельзя смешивать личную GTD-систему и операционную систему бизнеса.

Статус:

Принято.

---

## ADR-002 — Google Sheets является текущей базой данных

Решение:

На текущем этапе все основные реестры Business Core хранятся в Google Sheets.

Причина:

- быстрое внедрение;

- простая проверка данных;

- понятность для владельца;

- возможность ручного контроля;

- небольшая текущая нагрузка.

Ограничение:

При росте одновременной нагрузки, количества строк и требований к безопасности возможен переход на PostgreSQL.

Статус:

Принято временно.

---

## ADR-003 — Один Telegram-бот

Решение:

Использовать один Telegram-бот как интерфейс GTD и Business Core.

При этом доступ к личному и рабочему контуру должен разделяться ролями и правами.

Причина:

- проще поддерживать;

- одна точка входа;

- сотрудники смогут работать через кнопки;

- бизнесы можно разделять через biz_id.

Статус:

Принято.

---

## ADR-004 — SendPulse, Binotel и Business Core имеют разные роли

Решение:

SendPulse отвечает за продажи, переписку и CRM-воронку.

Binotel отвечает за телефонию и звонки.

Business Core отвечает за клиента, объект, услугу и производство.

Google Drive отвечает за документы.

Telegram отвечает за внутреннюю работу сотрудников.

Статус:

Принято.

---

## ADR-005 — Рабочие stages и commercial milestones разделены

Решение:

Roadmap stages отражают рабочий производственный процесс.

Commercial milestones отражают коммерческие этапы и оплаты.

Пример по ИЖС:

1. Анализ — 150 000 тг.

2. Документы до АПЗ — 500 000 тг.

3. Техпаспорт, акт ввода и регистрация — 300 000 тг.

Статус:

Принято.

---

## ADR-006 — Новые таблицы не создаются без отдельного решения

Решение:

Сначала использовать существующую архитектуру и реестры.

Новые Google Sheets, новые сущности и крупные изменения архитектуры создаются только после отдельного анализа.

Причина:

Избежать дублей, усложнения и хаотичного роста системы.

Статус:

Принято.

---

## ADR-007 — Один исполнитель меняет проект в один момент

Решение:

Claude и Cursor не должны одновременно менять код или запускать seed-файлы.

Порядок:

1. Один исполнитель изучает задачу.

2. Вносит изменения.

3. Запускает тесты.

4. Делает commit.

5. После этого проект передаётся другому исполнителю.

Причина:

Избежать конфликтов, дублей и непонятных изменений.

Статус:

Принято.

---

## ADR-008 — BUG-001: template_id не сохранялся / читался неверно

Проблема:

Команда /milestones работает и не зависает.

Но RM-022 и RM-026 определялись как:

RMT-IZH-ALM-LEGALIZATION-001

Хотя ожидался:

RMT-IZH-ALM-STANDARD-002

Диагностика подтвердила:

1. template_id, выбранный в /startroadmap, нигде не сохранялся —

   *resolve*template_id пересчитывал его заново через notes / default

   услуги / первый связанный шаблон и терял явный выбор.

2. Промежуточный фикс (добавление колонки Template ID) выявил второй,

   более глубокий баг: живой лист ROADMAPS имел только 24 реальных

   заголовка, тогда как код (create_roadmap_for_object) годами писал

   Object ID / Parent Roadmap ID / Case Type позиционно в колонки 25–27

   без соответствующих подписей. Новая колонка Template ID, добавленная

   по фактической длине заголовков, легла поверх данных Object ID

   (пример: RM-027 → template_id читался как "OBJ-001").

Решение:

- create_roadmap_for_object и find_roadmap_by_id переведены на запись

  и чтение ROADMAPS по фактическим именам заголовков (helper'ы

  get_header_index_map / row_from_header_map / read_row_by_headers

  в business_core/sheets.py), а не по жёсткой позиции.

- _resolve_template_id в первую очередь использует сохранённый

  roadmap["template_id"]; старая эвристика (notes → default услуги →

  первый связанный шаблон) оставлена как fallback для roadmap,

  созданных до фикса.

- Добавлен отдельный идемпотентный инструмент миграции заголовков

  (migrate_roadmaps_headers.py): читает фактические данные колонок,

  чтобы определить правильную подпись, работает в dry-run по умолчанию,

  для live-записи требует явного ввода YES, меняет только строку

  заголовков (row 1) и никогда — строки данных.

- Миграция выполнена в проде: заголовки 25–28 приведены к

  Object ID / Parent Roadmap ID / Case Type / Template ID.

  Все 27 существующих roadmap-строк не изменены.

- Проверено на RM-027: /milestones корректно показывает 3 коммерческих

  этапа по шаблону RMT-IZH-ALM-STANDARD-002.

Статус:

Закрыто.

---

## ADR-009 — Canonical Stage Statuses

Решение:

Единственный канонический словарь статусов РЕАЛЬНОГО этапа

(лист ROADMAP_STAGES) — ровно пять значений:

pending, in_progress, blocked, done, skipped.

Только эти значения принимаются на запись через

update_stage_status_in_sheet() и команду /updatestage.

Legacy-значения, встречающиеся в исторических данных

(not_started — из /newroadmap; waiting; "completed" как статус

этапа, а не Roadmap) в канонический словарь намеренно НЕ входят.

Существующие этапы с legacy-статусом по-прежнему читаются без

ошибок (find_stage_by_id не валидирует статус на чтение) — но

записать такое значение через /updatestage нельзя.

Отдельная константа STAGE_STATUS_CANONICAL не заменяет и не

изменяет STAGE_STATUSES — та константа принадлежит мёртвой

in-memory модели (Roadmap/RoadmapStage, Phase 2C) и Sheets не

касается; обе константы сосуществуют осознанно до отдельной

фазы очистки legacy-кода.

Причина:

Одна из трёх ранее сосуществовавших несогласованных вокабуляров

статусов (мёртвая in-memory модель, иконки в /stages, реально

писавшиеся значения) должна была стать источником истины для

всех новых Sheets-операций.

Статус:

Принято.

---

## ADR-010 — Progress Calculation

Решение:

Progress % roadmap считается по формуле:

- завершёнными считаются этапы со статусом done ИЛИ skipped

  (DONE_SET = {done, skipped});

- pending, in_progress, blocked, любые legacy/пустые/неизвестные

  статусы — не завершены;

- при отсутствии этапов у roadmap (total == 0) — Progress % = 0;

- иначе Progress % = round_half_up(done_count / total_count * 100),

  целое число (не float, не строка с "%").

round-half-up выбран сознательно вместо встроенного Python round()

(banker's rounding) — на границе .5 (например 1/8 = 12.5%) round()

даёт 12, что менее интуитивно для бизнес-контекста, чем 13.

Решение по skipped: считается завершённым, т.к. это финальное

состояние этапа (осознанно пропущен, больше не требует действий),

а не промежуточное вроде pending/blocked. Иначе roadmap с хотя бы

одним пропущенным этапом никогда не мог бы показать 100%, даже

если процесс по факту закрыт.

calculate_progress() — чистая функция без обращения к Sheets.

recalculate_roadmap_progress() — Sheets-backed, пишет ТОЛЬКО

колонку Progress % найденной строки ROADMAPS, не трогает Status

roadmap и не трогает ROADMAP_STAGES.

Причина:

До Phase 9C Progress % писался один раз при создании roadmap

("0") и никогда не пересчитывался — колонка была фактически

мёртвой на всех существующих roadmap.

Статус:

Принято.

---

## ADR-011 — Roadmap Automatic Completion

Решение:

Roadmap автоматически переводится Status: active → completed

только при одновременном выполнении всех условий:

1. у roadmap есть хотя бы один этап;

2. каждый этап имеет статус done или skipped (DONE_SET);

3. Progress % == 100;

4. текущий Status roadmap == active.

Гарантии maybe_complete_roadmap():

- completed никогда автоматически не возвращается в active,

  даже если позже какой-то этап откатили обратно в pending —

  обратное открытие Roadmap сознательно не реализовано;

- draft, paused, cancelled, on_hold и любой другой статус,

  отличный от active, не изменяются;

- повторный вызов на уже completed roadmap — идемпотентный

  результат без записи (changed=False);

- пишет ТОЛЬКО колонку Status; не трогает Progress %, не трогает

  ROADMAP_STAGES, не трогает другие roadmap, не пишет историю.

/updatestage вызывает maybe_complete_roadmap() автоматически

после каждого успешного recalculate_roadmap_progress — только

если статус этапа был валиден и этап найден.

Причина:

Ручное отслеживание момента завершения roadmap ненадёжно при

десятках параллельных объектов; автоматизация должна быть

односторонней (только к завершению) и полностью обратимой по

данным (никогда не удаляет и не переписывает историю статусов

этапов), чтобы ошибочное автозавершение всегда можно было

вручную скорректировать через прямое изменение Status в Sheets.

Статус:

Принято.

---

## ADR-012 — Header-safe Sheets Writes

Решение:

Весь НОВЫЙ код записи в Google Sheets в Business Core обязан

формировать строку данных по ИМЕНАМ фактических заголовков листа

(row_from_header_map / get_header_index_map из business_core/sheets.py),

а не по числовой позиции колонки и не по статическому списку

BUSINESS_HEADERS.

Чтение обязано использовать тот же принцип

(read_row_by_headers / get_header_index_map), а не row[N] по индексу.

Это правило применяется к новому коду безусловно. Существующие

позиционные writer'ы (create_roadmap_stages_from_template,

create_roadmap_template, add_roadmap_template_stage, /newroadmap)

остаются как технический долг до отдельной фазы Phase 10.2B —

их не трогать без предварительного read-only аудита фактических

заголовков соответствующего листа.

(Phase 30A, docs-only correction: create_object_record уже переведён

на header-mapped запись (Phase 10.2B.5, row_from_header_map) — снят

из списка тех.долга выше как устаревшее заявление, не отражающее

фактический код. create_stages_from_template_record также снят: он

переехал из roadmap_template_manager.py в business_builder.py

целиком в Phase 29CD, см. ADR-013 — прежнее упоминание относилось к

уже не существующей функции в её прежнем расположении.)

Причина:

Позиционная запись дважды приводила к реальным инцидентам в проде:

BUG-001 (RM-027: колонка Template ID легла поверх данных Object ID

из-за расхождения между кодом и фактическими заголовками ROADMAPS)

и аналогичный скрытый риск, обнаруженный и устранённый в

ROADMAP_STAGES (Phase 9A) до того, как он успел проявиться как

видимый баг. Оба случая — следствие одной и той же причины:

код предполагал, что структура листа совпадает со статическим

списком в коде, без проверки факта.

Статус:

Принято.

---

## ADR-013 — Service Domain Ownership (Phase 29B)

Контекст:

Phase 29A (Service Domain Ownership Audit, read-only) показал, что

`service_manager.py` структурно готов быть единственным владельцем

SERVICE_CATALOG (нет циклов, нет обратных зависимостей), но им не

является на практике: `/initbc` пишет SERVICE_CATALOG напрямую в

обход `service_manager` (позиционная строка на 28 колонок против

реальных 41, собственная генерация Service ID и slug); легаси

`/newroadmap` читает SERVICE_CATALOG напрямую; `create_service_record`

не защищает от дублей; Roadmap можно создать для несуществующего

или неактивного Service; существует мёртвый параллельный модуль

`business_core/service_catalog.py` с коллизией имени

`create_service_record`.

Решение:

1. Canonical owner.

   `service_manager.py` — единственный transactional owner

   SERVICE_CATALOG. Допустимые исключения: read-only reporting

   snapshot (`report_manager.collect_snapshot`), CLI-only

   maintenance/seed-скрипты (см. пункт 9), read-only миграции.

   Ни одно исключение не считается production transactional path.

2. Technical identity vs duplicate key.

   Service ID остаётся уникальным неизменяемым техническим

   идентификатором, генерируется только `service_manager`.

   Отдельно вводится business duplicate key:

   SERVICE_DUPLICATE_KEY = (Business ID, normalized Service Name).

   Service ID сам по себе НЕ является duplicate key — он не

   препятствует созданию двух одинаковых услуг под разными ID,

   что и происходит сейчас через `/newservice` и `/initbc`.

   Нормализация имени: trim, схлопывание повторных пробелов,

   Unicode-нормализация, case-insensitive сравнение. Slug, Category,

   City, Template ID в ключ не входят. Различие только в регистре

   или пробелах считается совпадением.

3. Idempotent creation.

   `create_service_record` переходит на convergent/idempotent режим:

   повторный вызов с тем же duplicate key не создаёт новую строку,

   возвращает существующий Service (`service_created=False`,

   `service_reused=True`), не переписывает существующие поля молча.

   Если переданные значения отличаются от уже сохранённых —

   возвращается mismatch warning, изменение полей — задача отдельного

   update API (см. пункт 10), не самого create.

4. `/initbc`.

   Команда сохраняется (нужна для инициализации бизнеса), но

   переводится на владельца: никаких прямых записей в

   SERVICE_CATALOG, никакой собственной генерации Service ID или

   slug, никаких позиционных строк — только вызов

   `service_manager.create_service_record` в идемпотентном режиме.

   Повторный запуск `/initbc` становится безопасным по построению.

5. Slug.

   Slug — derived field, генерируется только в `service_manager`

   (существующий `_make_slug()` остаётся базовой реализацией, т.к.

   уже используется в проде). `/initbc` теряет собственный

   алгоритм (`name.lower().replace(" ", "-")`). Slug не используется

   как duplicate key и не меняется автоматически при переименовании.

6. Service status vocabulary.

   Подтверждается: active / inactive / draft.

   draft — ещё нельзя использовать в production Roadmap; inactive —

   больше нельзя использовать для новых Roadmap; active — разрешён.

   Неизвестный статус — не нормализуется молча в active, а

   отклоняется понятной ошибкой (это меняет текущее поведение

   `normalize_service_status`, которое сейчас именно так и делает —

   изменение вносится в Phase 29C). Legacy `paused` из мёртвого

   `service_catalog.py` canonical-словарём не считается.

7. Roadmap integration.

   `business_builder.create_roadmap_for_object` обязан получить

   Service через `service_manager.find_service_by_id`, отклонить

   отсутствующий, `inactive` и `draft` Service, использовать только

   `active`. Проверка — до создания Roadmap, до Stages, до Extension

   operations, без production writes при отказе. Проверка остаётся

   в orchestration-слое (`business_builder`), а не переносится в

   `roadmap_manager.create_roadmap_record` — existence/status

   validation не относится к persistence owner.

8. Legacy `/newroadmap` service lookup.

   UX поиска услуги по названию сохраняется, но raw

   `read_business_sheet("service_catalog")` из хендлера убирается в

   пользу нового owner API `find_services_by_name(query, biz_id=None,

   active_only=True)` (или аналогичного). Ambiguity policy: 0

   совпадений — not found; 1 совпадение — выбрать; >1 совпадения —

   показать варианты, не выбирать первый молча.

9. Public read API.

   Canonical публичный набор: `find_service_by_id`,

   `find_services_by_biz`, `list_active_services`,

   `find_services_by_name`. `_load_services` остаётся private;

   `/services` переводится на публичный API вместо прямого вызова

   `_load_services`.

10. Update/lifecycle scope.

    В текущий цикл (Phase 29C) входят только необходимые owner API:

    duplicate-safe create, name lookup, template-link update при

    необходимости, status validation primitives. Полный generic

    update/lifecycle (rename, category, price, description,

    deactivate/reactivate/draft, миграция Business ID,

    archive/delete) — отложен, отдельной фазой не раздувается 29C.

    Фиксируется: HARD_DELETE_ALLOWED = NO,

    BUSINESS_ID_MUTABLE = NO, SERVICE_STATUS_UPDATE_API = DEFERRED.

11. Seed/admin writes.

    `seed_izhs_*.py::_rename_id_in_sheet` и

    `seed_izhs_commercial_milestones.py::patch_service_notes`

    классифицируются как explicit maintenance debt: CLI-only

    maintenance-скрипты не считаются production transactional

    writer'ами и не блокируют закрытие домена, но остаются

    зафиксированным долгом, а не молчаливым исключением. Новые

    seed-скрипты обязаны использовать owner API. Общего allowlist

    «все seeds разрешены» не вводится. Уборка этого долга — Phase 29D.

12. Dead `service_catalog.py`.

    Статус: DEAD LEGACY MODEL, DO NOT IMPORT IN PRODUCTION, удаление

    отложено до общей уборки мёртвых legacy-моделей (тот же

    принцип, что уже применён к мёртвой in-memory RoadmapStage —

    см. ADR-009). Будущий architecture guard должен подтверждать,

    что ни один production-модуль его не импортирует, и что

    коллизия имени `create_service_record` не используется вне

    собственных legacy-тестов этого модуля.

13. Reporting exception.

    `report_manager.collect_snapshot` — approved read-only reporting

    exception: не пишет, не используется для transactional решений,

    явно документирован. Будущий architecture guard должен отличать

    этот read-only reporting-путь от production-хендлеров.

14. Target dependency direction.

    Разрешено: telegram_handlers → service_manager/business_builder;

    business_builder → service_manager; roadmap-модули →

    service_manager.find_service_by_id. Запрещено: telegram_handlers,

    business_builder и roadmap-модули → raw SERVICE_CATALOG;

    service_manager → telegram/orchestration/Roadmap (в любую сторону).

Целевые инварианты (проверяются в Phase 29C/29D через architecture

guards, аналогично Roadmap Closeout):

```
ALL_TRANSACTIONAL_SERVICE_WRITES_OWNED_BY_SERVICE_MANAGER = YES
ALL_TRANSACTIONAL_SERVICE_READS_USE_SERVICE_MANAGER_API = YES
SERVICE_CATALOG_RUNTIME_WRITERS == {service_manager.py}
TELEGRAM_HANDLERS_WRITE_SERVICE_CATALOG_DIRECTLY = NO
TELEGRAM_HANDLERS_READ_SERVICE_CATALOG_DIRECTLY = NO
BUSINESS_BUILDER_READS_SERVICE_CATALOG_DIRECTLY = NO
ROADMAP_MODULES_READ_SERVICE_CATALOG_DIRECTLY = NO
SERVICE_MANAGER_DEPENDS_ON_ORCHESTRATION = NO
SERVICE_MANAGER_DEPENDENCY_CYCLE_EXISTS = NO
SERVICE_CREATION_USES_CANONICAL_DUPLICATE_KEY = YES
SERVICE_CREATION_IS_IDEMPOTENT = YES
ROADMAP_CREATION_REQUIRES_EXISTING_ACTIVE_SERVICE = YES
PRODUCTION_IMPORTS_DEAD_SERVICE_CATALOG_MODEL = NO
```

Implementation plan:

Phase 29C — Guards + Canonical API (ownership guards, duplicate key

normalization, `find_service_by_name`, public list API, strict status

validation, additive return shapes; без обязательной миграции

вызывающего кода).

Phase 29D — Caller Migration + Validation (`/initbc` через owner API,

`/services` без `_load_services`, легаси `/newroadmap` через owner

lookup, Roadmap требует existing active Service, устранение slug

duplication, тесты, deploy). Допускается объединение 29C+29D, если

риск умеренный и файлы тесно связаны — решение об объединении

принимается в начале 29C по факту объёма диффа.

Phase 29E — Service Closeout Audit (writers/readers, duplicate

behavior, production integrity, tests, smoke, финальное закрытие

домена — по аналогии с Roadmap Closeout).

Причина:

Тот же архитектурный принцип, что уже закрыл Roadmap Domain

(единственный transactional owner на реестр, defense-in-depth

валидация на границе orchestration, устранение прямых обходов

реестра из Telegram-хендлеров) применяется к Service Domain:

Phase 29A нашла структурно идентичный класс проблем (прямой писатель

в обход владельца, отсутствие duplicate-защиты, отсутствие

валидации существования зависимой сущности при создании Roadmap) —

решение сознательно зеркалит уже проверенный на Roadmap Domain

подход, а не изобретает новый.

Статус:

Реализовано (Phase 29CD) и закрыто (Phase 29E, Service Domain Closeout).
service_manager.py — единственный runtime transactional owner
SERVICE_CATALOG; /initbc, /services, /newroadmap мигрированы на owner
API; Roadmap creation требует существующего active Service. Полный
generic lifecycle/update API (rename/price/deactivate/archive/delete)
и удаление мёртвого business_core/service_catalog.py остаются
отдельно отложенными (см. Phase 29E closeout report) — не входят в
это ADR.

---

## ADR-014 — Object Domain Ownership (Phase 30B)

Контекст:

Phase 30A (Object Domain Ownership Audit, read-only) показала, что

Object-функции живут внутри business_builder.py вперемешку с

orchestration-логикой, отдельного object_manager.py нет,

/editobject пишет OBJECT_REGISTRY напрямую (raw update_cell, нет

owner API для этого вообще), /editobject и /objects читают реестр

напрямую в обход существующих find_object_by_id/

find_objects_by_client, create_object_record не защищает от

дублей, Roadmap можно создать для несуществующего Object, Business

existence при создании Object не проверяется, Object status model

отсутствует, Drive folder creation не полностью идемпотентно.

Решение:

1. Canonical owner.

   Создать business_core/object_manager.py — единственный

   transactional owner OBJECT_REGISTRY (чтение, создание,

   narrow updates, duplicate lookup, status validation, Drive/

   Roadmap reference persistence). business_builder.py после

   миграции — orchestration only: проверка Business/Client,

   вызов object_manager, Drive folder orchestration, Roadmap

   orchestration, partial failure aggregation. (Реализация — Phase

   30C/30D, не в этом ADR.)

2. Technical identity.

   Object ID остаётся уникальным неизменяемым техническим

   идентификатором (формат OBJ-...), генерируется только

   object_manager. Старые Object ID не мигрируются.

3. Canonical duplicate key.

   OBJECT_DUPLICATE_KEY_POLICY — двухуровневая:

   Tier 1 (кадастровый номер заполнен): (Business ID, normalized

   Cadastral Number) — сильный ключ.

   Tier 2 (кадастрового номера нет): (Business ID, Client ID,

   normalized City, normalized Address) — fallback.

   Нормализация обоих уровней: trim, Unicode-нормализация,

   casefold; для кадастрового номера дополнительно убираются

   пробелы/разделители, если это безопасно для формата; для адреса —

   схлопывание повторных пробелов, без fuzzy-исправления улиц/домов.

   Object ID, голый Address, Roadmap ID, Drive Folder ID, Object

   Type сами по себе НЕ являются duplicate key.

4. Idempotent creation.

   create_object_record переходит на convergent режим: повторный

   вызов с тем же duplicate key не создаёт новую строку, возвращает

   существующий Object (object_created=False, object_reused=True),

   поля молча не перезаписываются — различия возвращаются как

   warnings. Несколько существующих совпадений — integrity error,

   без выбора первого и без записи.

5. Required Business/Client.

   OBJECT_REQUIRES_EXISTING_BUSINESS = YES,

   OBJECT_REQUIRES_EXISTING_CLIENT = YES, проверка до записи.

   Business existence: в кодовой базе нет отдельного Business

   Manager — business_builder.py, organization_manager.py,

   person_manager.py и telegram_handlers.py (newservice_cmd) уже

   единообразно используют sheets.find_row_by_id("biz_registry",

   biz_id) как de facto canonical primitive; /newobject должен

   перейти на тот же вызов внутри business_builder (orchestration),

   а не остаться непроверенным и не изобретать новый метод. Это не

   Object-domain-специфичное нарушение — Business Domain ещё не

   закрыт отдельной фазой (см. ограничение "не начинать Client/

   Business audit"), поэтому здесь фиксируется только использование

   уже существующего повсеместного паттерна, без изменения Business

   Domain. Client existence — через person_manager.find_person_by_id

   (уже фактический owner, без изменений).

6. Object status model.

   Минимальный vocabulary на этот цикл: new, active, on_hold,

   completed, cancelled (archived отложен до lifecycle API).

   OBJECT_STATUS_DEFAULT = new. ROADMAP_ALLOWED_OBJECT_STATUSES =

   new / active / on_hold. ROADMAP_REJECTED_OBJECT_STATUSES =

   completed / cancelled. Unknown status отклоняется на write,

   никогда не считается active по умолчанию (то же разделение

   read-side/write-side строгости, что уже применено к Service

   Domain в Phase 29CD).

7. Roadmap Object validation.

   ROADMAP_CREATION_REQUIRES_EXISTING_ALLOWED_OBJECT = YES.

   business_builder.create_roadmap_for_object обязан вызвать

   object_manager.find_object_by_id, отклонить отсутствующий Object,

   отклонить запрещённый/unknown статус, и только затем продолжить

   уже существующую Service-валидацию (Phase 29CD) и convergent

   Roadmap flow — до любых Roadmap/Stage/Object-reference/Extension

   writes. Валидация остаётся в orchestration (business_builder),

   не переносится в roadmap_manager — тот же принцип, что уже

   применён к Service-валидации.

8. Object Roadmap reference.

   ROADMAPS остаётся source of truth для всех Roadmap объекта.

   Object.Roadmap ID — compatibility/reference поле (может хранить

   primary/current Roadmap), не единственный источник истины, не

   блокирует создание второй Roadmap для другой Service. Текущая

   политика "update only if empty" сохраняется на этот цикл; полная

   модель Current/Primary Roadmap ID отложена. find_roadmaps_by_object

   должен в будущем делегировать на roadmap_manager.list_roadmaps

   (object_id=...) вместо собственного raw ROADMAPS-чтения.

9. Current Service ID.

   CURRENT_SERVICE_ID_SYNC = DEFERRED — это поле не становится

   source of truth; Service для Roadmap берётся из ROADMAPS;

   автоматическая синхронизация отложена до отдельной модели

   "текущей услуги", чтобы не смешивать её с Object ownership.

10. Public Object API (минимум для object_manager.py):

    generate_object_id, normalize_object_address,

    normalize_cadastral_number, validate_object_status,

    create_object_record, find_object_by_id, find_objects_by_client,

    find_objects_by_biz, list_objects, update_object_fields

    (allowlist-based: только Address/Object Type/Notes в этом

    цикле — Object ID/Client ID/Biz ID/Drive Folder ID/Roadmap ID/

    Created At через generic update запрещены; Last Updated

    обновляется автоматически), update_object_drive_info,

    update_object_roadmap_id.

11. /editobject → object_manager.find_object_by_id →

    object_manager.update_object_fields. Handler не получает

    worksheet, не вызывает update_cell, только парсит/форматирует,

    UX сохраняется без изменений.

12. /objects → object_manager.list_objects /

    find_objects_by_biz / find_objects_by_client — без raw reads и

    ручного парсинга headers в хендлере.

13. Extension readers (document_registry_manager.py,

    document_requirements_query.py) переводятся на

    object_manager.find_object_by_id, включая existence-only lookup.

    После появления object_manager прямые Extension-чтения реестра

    больше не считаются допустимыми. report_manager.collect_snapshot

    остаётся approved read-only reporting exception;

    synthetic_cleanup.py остаётся file/function-scoped admin

    exception — оба без изменений.

14. Drive idempotency.

    Flow: найти Object → если Drive Folder ID уже установлен —

    переиспользовать ссылку, Drive create не вызывать → иначе

    создать папку и сохранить Folder ID/URL. object_manager владеет

    чтением/записью Drive-ссылки; business_builder оркестрирует сам

    вызов Drive API; folder naming остаётся в orchestration/Drive

    adapter, не в persistence owner. Partial failure остаётся видимым.

15. Partial failure policy.

    Если Object создан, а Drive упал: ok=true, partial_success=true,

    drive_created=false, ошибка/warning видимы. Повторный вызов:

    переиспользовать Object, пытаться создать Drive folder только

    если Folder ID пуст, не создавать второй Object, не создавать

    вторую папку при уже существующей ссылке.

16. Dependency direction.

    object_manager → business_core.sheets only. Запрещено:

    object_manager → business_builder/telegram_handlers/

    roadmap_manager/Drive adapter/Extension. Разрешено:

    business_builder → object_manager; telegram_handlers →

    object_manager/business_builder; roadmap orchestration →

    object_manager; Extension-менеджеры → object_manager read API.

17. Migration of existing functions (Phase 30C, не в этом ADR):

    в object_manager.py переносятся generate_object_id,

    create_object_record, find_objects_by_client, find_object_by_id,

    update_object_drive_info, update_object_roadmap_id.

    provision_object_drive остаётся в business_builder.py как

    orchestration-wrapper (вызывает object_manager + Drive adapter).

    find_roadmaps_by_object переводится на

    roadmap_manager.list_roadmaps(object_id=...), дублирующая raw-

    реализация в business_builder убирается. Если у старых public

    функций business_builder есть внешние вызывающие, допустимы

    тонкие delegating wrappers без persistence-логики внутри —

    guards должны это гарантировать.

18. FK immutability / delete policy.

    OBJECT_HARD_DELETE_ALLOWED = NO. OBJECT_BUSINESS_ID_MUTABLE = NO.

    OBJECT_CLIENT_ID_MUTABLE = NO. /editobject не получает доступ

    к этим полям. Archive/lifecycle API отложены.

Целевые инварианты (проверяются в Phase 30C/30D через architecture

guards, по аналогии с Roadmap/Service Closeout):

```
ALL_TRANSACTIONAL_OBJECT_WRITES_OWNED_BY_OBJECT_MANAGER = YES
ALL_TRANSACTIONAL_OBJECT_READS_USE_OBJECT_MANAGER_API = YES
TELEGRAM_HANDLERS_WRITE_OBJECT_REGISTRY_DIRECTLY = NO
TELEGRAM_HANDLERS_READ_OBJECT_REGISTRY_DIRECTLY = NO
BUSINESS_BUILDER_WRITES_OBJECT_REGISTRY_DIRECTLY = NO
ROADMAP_CREATION_REQUIRES_EXISTING_ALLOWED_OBJECT = YES
OBJECT_CREATION_USES_CANONICAL_DUPLICATE_POLICY = YES
OBJECT_CREATION_IS_IDEMPOTENT = YES
OBJECT_DRIVE_CREATION_IS_RETRY_SAFE = YES
EXTENSION_MODULES_READ_OBJECT_REGISTRY_DIRECTLY = NO
OBJECT_MANAGER_DEPENDENCY_CYCLE_EXISTS = NO
OBJECT_DOMAIN_HAS_REVERSE_DEPENDENCY = NO
```

Implementation plan:

Phase 30C — Object Manager Foundation (создать object_manager.py,

перенести canonical read/write primitives, normalization/status/

duplicate-safe create, update_object_fields, guards, thin

compatibility wrappers в business_builder при необходимости — без

обязательной caller migration и без deploy, если production

behavior не меняется).

Phase 30D — Caller Migration + Validation (/editobject, /objects,

Extension readers, Roadmap Object validation, Business validation в

/newobject, Drive retry-safety, тесты, deploy). Допускается

объединение 30C+30D, если diff остаётся контролируемым — предпочтение

сначала сделать foundation отдельно, так как вводится новый manager.

Phase 30E — Object Closeout Audit (ownership, readers/writers,

duplicate/idempotency, Roadmap/Drive integration, data integrity,

финальное закрытие домена).

Причина:

Тот же архитектурный принцип, что уже закрыл Roadmap Domain и

Service Domain (единственный transactional owner на реестр,

defense-in-depth валидация на границе orchestration, устранение

прямых обходов реестра из Telegram-хендлеров и Extension-модулей)

применяется к Object Domain. Phase 30A нашла структурно похожий, но

более острый класс проблем — на этот раз включая write-side

нарушение без вообще какого-либо owner API (/editobject), поэтому

решение вводит новый выделенный object_manager.py, а не просто

ужесточает существующий модуль, как это было достаточно для Service

Domain.

Статус:

Реализовано (Phase 30C/30D) и закрыто (Phase 30E, Object Domain
Closeout). object_manager.py — единственный runtime transactional
owner OBJECT_REGISTRY; /editobject, /objects, Extension-читатели
(document_registry_manager.py, document_requirements_query.py) и
Roadmap Object-валидация мигрированы на owner API; создание Object
идемпотентно по Tier 1/Tier 2 duplicate key; Drive provisioning
retry-safe. Полный generic lifecycle/archive/delete API и
синхронизация Current Service ID остаются отдельно отложенными (см.
Phase 30E closeout report) — не входят в это ADR.

## ADR-015 — Client Domain Ownership (Phase 31B)

Контекст:

Phase 31A (Client Domain Ownership Audit, read-only) показала, что
Client не является отдельной сущностью — это Person из
PEOPLE_REGISTRY с клиентским смыслом в свободном текстовом поле
"Тип"; OBJECT_REGISTRY.Client ID хранит Person ID формата PRS-....
Аудит нашёл три HIGH-проблемы: (1) в /newclient используются две
разные duplicate-identity функции (find_existing_person и
find_duplicate_person) с разными правилами совпадения и разной
обработкой archived-строк; (2) telegram_handlers.py читает
PEOPLE_REGISTRY напрямую в трёх местах (/clients, /bc dashboard,
legacy /newroadmap client lookup), в обход owner API
person_manager.py; (3) /newobject не требует существующей связи
Person↔Business и молча добавляет Business ID к Person вместо
отказа/подтверждения. Дополнительно: Client role — substring-match
по свободному тексту без единого helper'а; multiple person matches
разрешаются выбором первого совпадения без ambiguity-статуса;
multi-business Drive folder policy не определена (single-slot
Drive-ссылка на Person не может представить папку по каждому
Business); Biz IDs/Primary Biz ID разрешены в generic update_person;
Person↔Business link хранится как строка в одной ячейке, а не как
relation-запись.

Решение:

1. Client entity model.

   CLIENT_IS_SEPARATE_ENTITY = NO. CLIENT_IS_PERSON_ROLE = YES.
   CLIENT_ID_EQUALS_PERSON_ID = YES. Отдельный client_manager.py и
   отдельный CLIENT_REGISTRY не создаются. Client Domain закрывается
   как специализация Person Domain. Canonical owner —
   business_core/person_manager.py.

2. Canonical Person identity policy.

   Ввести единственную canonical identity API —
   resolve_person_identity — вместо двух конкурирующих функций.
   Иерархия: normalized phone и normalized email — сильные
   идентификаторы (PHONE_OR_EMAIL_MATCH = strong match); normalized
   full name — слабый идентификатор, сам по себе не подтверждает
   identity (NAME_ONLY_MATCH = ambiguous candidate, не automatic
   reuse). Resolver возвращает структурированный результат
   {status: not_found|single_match|ambiguous|archived_match, person,
   matches, matched_by, error} — никогда не выбирает первое
   совпадение молча. MULTIPLE_PERSON_MATCHES_ARE_REJECTED = YES
   (несколько сильных совпадений → ambiguous, а не первый результат).
   find_existing_person и find_duplicate_person мигрируют на thin
   wrappers над resolve_person_identity, без собственной identity
   logic (PERSON_IDENTITY_HAS_SINGLE_IMPLEMENTATION = YES).

3. Archived-person policy.

   ARCHIVED_PERSON_CAN_BE_REUSED_AS_CLIENT = NO.
   ARCHIVED_PERSON_CAN_OWN_NEW_OBJECT = NO. Совпадение только с
   archived-строкой по сильному идентификатору возвращает отдельный
   статус archived_match — без автосоздания дубликата и без
   автореактивации; реактивация — отдельная будущая lifecycle-фаза.

4. /newclient branch model.

   Единый flow: /newclient → resolve_person_identity → NEW /
   SAME_BIZ / OTHER_BIZ / AMBIGUOUS. AMBIGUOUS не производит никаких
   записей (ни create_person, ни Business link, ни Drive folder) и
   показывает список кандидатов или понятную ошибку вместо отказа
   через raw exception.

5. Client role policy.

   Схема "Тип" не меняется в этом цикле (CLIENT_ROLE_STORAGE =
   existing "Тип" field). Вводятся canonical helpers
   is_client_person(person) и ensure_client_role(person_id) с точной
   (не substring) проверкой распознанных значений ("клиент", "клиент
   по узаконению" и т.п.): если поле уже содержит признанную
   client-категорию — no-op; если поле пустое — установить "клиент";
   если поле содержит другую непустую категорию — предупреждение без
   молчаливой перезаписи. Полноценная multi-role модель откладывается.

6. Client listing API.

   Ввести list_clients(biz_id=None, query=None,
   include_archived=False) в person_manager.py, использующий
   is_client_person и возвращающий canonical Person dicts — без
   substring-фильтрации в Telegram-хендлерах.

7. Telegram reader migration.

   /clients, /bc dashboard и legacy /newroadmap client lookup
   мигрируют на person_manager public API.
   TELEGRAM_HANDLERS_READ_PEOPLE_REGISTRY_DIRECTLY = NO.
   TELEGRAM_HANDLERS_WRITE_PEOPLE_REGISTRY_DIRECTLY = NO. Единственное
   утверждённое исключение — inbox_bridge.py (GTD-boundary файл, не
   подлежит изменению в рамках Business Core фаз), scoped строго к
   этому файлу, не blanket allowlist.

8. Person↔Business relationship policy.

   Модель "Biz IDs как multi-value cell + Primary Biz ID как
   отдельное поле" сохраняется без relation-таблицы в этом цикле.
   PERSON_BUSINESS_LINK_OWNER = person_manager.py.
   PERSON_BUSINESS_LINK_MODE = ADD_ONLY. Biz IDs и Primary Biz ID
   исключаются из allowlist generic update_person — изменения только
   через append_person_biz_id/has_person_business_link/
   list_person_business_ids. Удаление/переназначение Business link
   откладывается.

9. /newobject cross-business и client-role policy.

   OBJECT_CREATION_REQUIRES_PERSON_LINKED_TO_OBJECT_BUSINESS = YES.
   OBJECT_CREATION_REQUIRES_CLIENT_ROLE = YES.
   OBJECT_CREATION_AUTO_LINKS_PERSON_TO_BUSINESS = NO. Если Person не
   связан с Object Business или не является Client (is_client_person
   == False) или archived — Object не создаётся, /newobject
   отклоняет запрос с объяснением, что связь нужно оформить сначала
   через /newclient. Никакой скрытой мутации Person со стороны
   /newobject.

10. Multi-business Client Drive policy.

    Текущая single-slot Drive-ссылка на Person (Drive Folder ID/
    Google Drive) не расширяется до per-Business модели в этом
    цикле — переинтерпретируется как general/primary person folder
    reference. Для OTHER_BIZ Person эта ссылка не показывается как
    папка нового Business, и новая непредставимая Business-specific
    папка не создаётся — вместо этого возвращается явный warning.
    MULTI_BUSINESS_CLIENT_DRIVE_CREATES_NO_UNTRACKED_FOLDER = YES.
    Полноценная relation-based Drive-модель откладывается до
    отдельной фазы, требующей schema migration.

11. Drive retry safety.

    CLIENT_DRIVE_CREATION_IS_RETRY_SAFE = YES:
    если Drive Folder ID/URL уже установлен — reuse без повторного
    create; иначе — create once, persist через
    person_manager.update_person_drive_info.
    CLIENT_DRIVE_REFERENCE_WRITES_OWNED_BY_PERSON_MANAGER = YES.

12. Lifecycle.

    PERSON_HARD_DELETE_ALLOWED = NO. PERSON_MERGE_SUPPORTED = NO.
    CLIENT_ROLE_REMOVAL_SUPPORTED = NO. Статус меняется только через
    archive_person; Business link — только через
    append_person_biz_id; Drive — только через
    update_person_drive_info.

13. Dependency direction.

    person_manager.py импортирует только business_core.sheets (и
    stdlib) — без обратных зависимостей на business_builder,
    telegram_handlers, object_manager, Drive adapter или Extension-
    модули. PERSON_MANAGER_DEPENDENCY_CYCLE_EXISTS = NO.
    CLIENT_DOMAIN_HAS_REVERSE_DEPENDENCY = NO.

14. Public API target.

    normalize_person_name, normalize_phone, normalize_email,
    resolve_person_identity, find_person_by_id, list_people,
    list_people_by_business, list_clients, is_client_person,
    create_person, update_person, archive_person, ensure_client_role,
    list_person_business_ids, has_person_business_link,
    append_person_biz_id, update_person_drive_info. Compatibility
    wrappers допустимы, но не должны содержать отдельную business
    logic.

15. Required guards (для будущих фаз).

    PEOPLE_REGISTRY_RUNTIME_WRITERS == {person_manager.py};
    TELEGRAM_HANDLERS_WRITE_PEOPLE_REGISTRY_DIRECTLY = NO;
    TELEGRAM_HANDLERS_READ_PEOPLE_REGISTRY_DIRECTLY = NO;
    BUSINESS_BUILDER_WRITES_PEOPLE_REGISTRY_DIRECTLY = NO;
    PERSON_IDENTITY_HAS_SINGLE_IMPLEMENTATION = YES;
    PERSON_IDENTITY_NEVER_RETURNS_ARBITRARY_FIRST_MATCH = YES;
    NAME_ONLY_MATCH_IS_NOT_AUTOMATIC_REUSE = YES;
    CLIENT_LISTING_USES_CANONICAL_HELPER = YES;
    PERSON_BUSINESS_LINK_MUTATION_IS_ADD_ONLY = YES;
    OBJECT_CREATION_REQUIRES_CLIENT_ROLE = YES;
    OBJECT_CREATION_REQUIRES_PERSON_LINKED_TO_OBJECT_BUSINESS = YES;
    ARCHIVED_PERSON_CAN_OWN_NEW_OBJECT = NO;
    MULTI_BUSINESS_CLIENT_DRIVE_CREATES_NO_UNTRACKED_FOLDER = YES;
    PERSON_MANAGER_DEPENDENCY_CYCLE_EXISTS = NO. Утверждённое
    исключение из read/write guards — inbox_bridge.py, scoped строго
    к этому файлу.

Implementation plan (не в этом ADR):

Phase 31C — Canonical Identity and Client API Foundation
(resolve_person_identity, normalize_email, is_client_person,
list_clients, ensure_client_role, Business-link query API, исключение
Biz IDs/Primary Biz ID из generic update_person, guards; без
deployment, если production paths не меняются).

Phase 31D — Caller Migration and Cross-domain Validation (/newclient
на canonical resolver; /clients, /bc, legacy /newroadmap на
person_manager API; /newobject — Client role + существующий Business
link required, без silent auto-link, отказ для archived Person;
безопасный Drive для OTHER_BIZ; тесты; deploy).

Phase 31E — Client Domain Closeout Audit (ownership, identity, role
behavior, Person↔Business, Object integration, Drive, production
integrity, финальное закрытие домена).

Deferred (явно откладывается, не блокирует Client Domain closeout при
соблюдении временных политик выше): отдельный CLIENT_REGISTRY;
relation-таблица Person↔Business; multi-role schema; per-Business
Client Drive reference model; Person merge; Client role removal;
Business-link removal; archived Person reactivation; schema migration.

Причина:

Тот же архитектурный принцип, что уже закрыл Roadmap/Service/Object
Domain (единственный transactional owner на реестр, defense-in-depth
валидация на границе orchestration, устранение прямых обходов реестра
из Telegram-хендлеров) применяется к Client Domain — но в отличие от
Object Domain, здесь не требуется новый manager, поскольку
person_manager.py уже существует и уже является единственным
transactional writer'ом; проблема — в конкурирующей identity-логике,
в оставшихся raw readers и в отсутствующей cross-domain валидации на
границе Object creation, а не в отсутствии owner API как таковой.

Статус:

Утверждено для реализации (Phase 31C/31D/31E). Ничего не
реализовано в рамках этого ADR — только архитектурное решение.

---

## ADR-016 — Roadmap Cross-Domain Validation (Phase 33B)

Контекст:

Phase 33A (Roadmap Domain Architecture Audit, read-only) подтвердила,
что owner-слой Roadmap Domain (roadmap_manager.py — единственный
transactional writer ROADMAPS/ROADMAP_STAGES, идентичность,
идемпотентная материализация Stages, отсутствие циклов) остаётся
корректно закрытым — эта область НЕ пересматривается этим ADR.
Аудит подтвердил и уточнил унаследованную из Phase 32A (Service
Domain re-audit) находку: business_builder.create_roadmap_for_object()
проверяет существование и статус Object и Service, но НЕ проверяет
Business вообще, НЕ проверяет Client (существование/статус/роль/
привязку к Business), НЕ проверяет согласованность Object↔Business,
Object↔Client, Service↔Business, и НЕ проверяет совместимость
Object Type/Client Type услуги с реальным типом Object. Сегодня это
не эксплуатируется, так как единственный вызывающий (/startroadmap)
берёт biz_id/client_id из самого Object, а не из независимого
пользовательского ввода — но сама функция create_roadmap_for_object
не имеет defense-in-depth и не защищена от будущего вызывающего кода
без этой же дисциплины.

Дополнительно, при подготовке этого ADR (read-only проверка
production-данных, без записи) обнаружено критически важное для
решения по Object Type несоответствие: SERVICE_CATALOG.Object Type
хранит машинные английские slug-значения (например
"private_house_izhs"), тогда как OBJECT_REGISTRY.Object Type
реального объекта OBJ-001 хранит свободный русский текст ("жилой
дом") — два поля живут в совершенно разных, никак не связанных
словарях. Простое точное сравнение после нормализации (NFKC/trim/
casefold) между ними НИКОГДА не совпадёт ни для одной существующей
или новой записи, введённой через текущий UX /newobject. Это прямо
меняет рекомендованную по умолчанию политику "hard rejection" — её
буквальное применение сегодня заблокировало бы Roadmap-совместимую
работу для всех 7 Service с непустым Object Type, у которых пока
физически не может быть ни одного Object с совпадающим по словарю
значением.

Аналогично для Client Type: единственное встречающеея в проде
значение — "physical_person" (все 7 записей с непустым Client Type),
что не позволяет установить, действительно ли это стабильная,
различающая категория (a не случайно единообразное значение,
введённое один раз при сидировании каталога) — недостаточно
доказательств для канонического статуса поля.

Также обнаружено: BIZ_REGISTRY.Статус — не канонический словарь
(в проде встречаются "test" (36 строк), "active" (4), "hold" (1)), и
у Business Domain до сих пор нет собственного owner-модуля или
архитектурного решения о статус-модели (тот же вывод уже
зафиксирован в Object/Client ADR как "Business Domain ещё не имеет
отдельного owner-модуля"). Изобретать канонический статус-словарь
Business здесь, попутно, при решении по Roadmap — было бы
самовольным расширением scope в недорешённый домен.

Решение:

1. Canonical validation owner.

   business_builder.create_roadmap_for_object() остаётся единственной
   orchestration-границей, ответственной за все cross-domain
   валидации, ДО вызова roadmap_manager.py. roadmap_manager.py
   остаётся ответственным ТОЛЬКО за persistence, identity,
   deduplication (Object ID, Service ID), статус/progress Roadmap и
   идемпотентную материализацию Stages — ничего из этого не
   пересматривается.

   roadmap_manager.py НЕ должен импортировать: person_manager,
   object_manager, service_manager, любой Business-owner-модуль,
   telegram_handlers, business_builder. Подтверждено: сегодня так и
   есть (Phase 33A, AST-проверка) — фиксируется как обязывающий
   инвариант, а не как желаемое состояние.

   Целевое направление зависимостей:
   ```
   telegram_handlers
     → business_builder
         → business/person/object/service/template owners
         → roadmap_manager
   ```
   Обратных импортов и циклов нет.

2. Business validation.

   Требуется: biz_id непустой; Business существует в BIZ_REGISTRY
   (find_row_by_id("biz_registry", biz_id) не None) — HARD GATE,
   безопасно определимо уже сегодня.

   Требование "Business активен/eligible для новой работы" —
   ОТКЛАДЫВАЕТСЯ. BIZ_REGISTRY.Статус не является канонической
   валидированной моделью (36 строк "test", 4 "active", 1 "hold", нет
   owner-модуля, нет ADR о статус-словаре Business Domain).
   Устанавливать здесь строгий gate на нестабильном, недорешённом
   поле означало бы либо заблокировать почти весь текущий каталог
   бизнесов ("test" ≠ "active"), либо изобрести на месте канонический
   статус-словарь для домена, у которого ещё нет собственного
   архитектурного решения. Это прямо запрещено инструкцией "Do not
   silently repair or auto-link inconsistent data" в применении к
   более широкому принципу — не изобретать канон для чужого домена.

   Требуется (новое, добавляется в Phase 33C): Object.Biz ID == biz_id
   параметр (OBJECT_BUSINESS_MISMATCH, HARD GATE); Service.Бизнес ID
   == biz_id параметр (SERVICE_BUSINESS_MISMATCH, HARD GATE). Оба уже
   тривиально проверяемы через существующие Object/Service reader'ы,
   без изобретения нового canonical поля.

   Требование "Client Person привязан к тому же Business" — см.
   пункт 3 (Client validation) — это отдельная, но связанная
   проверка, HARD GATE.

   Требование "Template принадлежит Service, связанному с тем же
   Business" — покрывается транзитивно через Service↔Business
   (пункт 5) и Template↔Service (пункт 8): отдельной прямой проверки
   Template↔Business не вводится, так как Template не хранит
   собственного Business ID — его Business-принадлежность целиком
   определяется через Service, который его использует.

3. Client validation.

   Client Person должен: существовать (CLIENT_NOT_FOUND, HARD GATE);
   не быть archived (CLIENT_ARCHIVED, HARD GATE, без автоматической
   реактивации); иметь точную нормализованную Client-роль через
   person_manager.is_client_person() (CLIENT_ROLE_REQUIRED, HARD GATE,
   без автоматического добавления роли); быть привязан к выбранному
   Business через person_manager.has_person_business_link()
   (CLIENT_NOT_LINKED_TO_BUSINESS, HARD GATE, без автоматического
   линковки); совпадать с Client, на которого ссылается сам Object
   (Object.Client ID == client_id параметр — OBJECT_CLIENT_MISMATCH,
   HARD GATE).

   Неоднозначные/legacy Client-ссылки (например Object.Client ID
   пустой или ссылается на несуществующего Person) — трактуются как
   OBJECT_NOT_ELIGIBLE/OBJECT_CLIENT_MISMATCH соответствующим кодом,
   без попытки угадать или восстановить связь.

   Ничего из этого не переоткрывает Client Domain ownership (ADR-015)
   — используются исключительно уже существующие public API
   person_manager (is_person_archived, is_client_person,
   has_person_business_link, find_person_by_id).

4. Object validation.

   Eligible-статусы для старта Roadmap остаются как в Phase 30D/33A:
   new, active, on_hold (ROADMAP_ALLOWED_OBJECT_STATUSES в
   object_manager.py, не пересматривается — completed/cancelled
   остаются НЕ eligible). on_hold ОСТАЁТСЯ eligible: временная
   приостановка объекта — не то же самое, что его недействительность;
   это уже было сознательным решением Object Domain (ADR-014/Phase
   30D), и этот ADR его не пересматривает.

   Требуется: Object существует (OBJECT_NOT_FOUND); Object не
   archived (в текущей модели Object Domain "archived" как отдельный
   статус не введён — статус, не входящий в OBJECT_STATUSES вообще,
   уже сегодня отклоняется как unknown, HARD GATE); Object.status ∈
   ROADMAP_ALLOWED_OBJECT_STATUSES (OBJECT_NOT_ELIGIBLE, уже
   реализовано); Object.Biz ID == biz_id параметр
   (OBJECT_BUSINESS_MISMATCH, новое); Object.Client ID == client_id
   параметр (OBJECT_CLIENT_MISMATCH, новое). Object ID остаётся
   неизменяемым после создания Roadmap — Roadmap creation никогда не
   пишет ничего в OBJECT_REGISTRY, кроме уже существующего отдельного
   вызова update_object_roadmap_id() (Roadmap ID back-reference,
   Phase 28C, не пересматривается и не расширяется).

5. Service validation.

   Service должен: существовать (SERVICE_NOT_FOUND, уже есть);
   иметь статус active (SERVICE_INACTIVE, уже есть); принадлежать
   тому же Business, что и Object (Service.Бизнес ID == biz_id
   параметр — SERVICE_BUSINESS_MISMATCH, новое). Service выбирается
   ИСКЛЮЧИТЕЛЬНО по точному Service ID на границе orchestration —
   arbitrary first-name-match НЕ допускается на этой границе (legacy
   /newroadmap's find_services_by_name остаётся отдельным,
   already-audited, unreachable legacy UX-путём, не используемым
   create_roadmap_for_object). Никакого автоматического создания
   Service или переназначения его Business не вводится.

6. Object Type compatibility.

   Политика: **WARNING (мягкое предупреждение), НЕ hard gate** — это
   осознанное отступление от рекомендованного по умолчанию "hard
   rejection", обоснованное конкретными production-данными,
   обнаруженными при подготовке этого ADR (см. Контекст выше):
   SERVICE_CATALOG.Object Type хранит английские machine-slug
   значения ("private_house_izhs"), а реальный OBJECT_REGISTRY.Object
   Type — свободный русский текст ("жилой дом"). Между этими двумя
   словарями сегодня нет никакого канонического alias-отображения.
   Введение hard gate до появления такого отображения немедленно
   заблокировало бы Roadmap-старт для всех Service с непустым Object
   Type против любого реального сегодняшнего Object — это было бы не
   исправлением найденного архитектурного пробела, а внесением
   нового, более серьёзного функционального регресса.

   Нормализация (для использования в WARNING-сравнении и для будущего
   alias-отображения): NFKC → trim → схлопывание пробелов → casefold.
   Точное сравнение после нормализации, без substring/fuzzy/семантического
   вывода. Явный alias-словарь МОЖЕТ быть введён в Phase 33C только
   если он уже поддерживается существующими каноническими данными
   Object Type (а не изобретается здесь) — сегодня такого
   отображения нет, поэтому alias-словарь в Phase 33C НЕ вводится
   автоматически; это отдельно фиксируется как deferred schema/
   mapping work (см. пункт 23).

   Поведение: Service.Object Type пустой → сравнение не выполняется
   (WARNING не показывается); Object.Object Type пустой → сравнение
   не выполняется; оба непустые, но нормализованные значения не
   совпадают → OBJECT_SERVICE_TYPE_MISMATCH возвращается как
   non-blocking warning (видимый пользователю, не блокирующий
   создание Roadmap). Поддержка одним Service нескольких Object Type
   сегодня не представима без новой relation-таблицы/схемы —
   явно откладывается (пункт 23), никакой encoded-list формат не
   изобретается взамен.

7. Client Type compatibility.

   Политика: **DEFERRED** — явно откладывается, канонический смысл
   SERVICE_CATALOG.Client Type не установлен. В проде встречается
   единственное значение ("physical_person") во всех 7 непустых
   строках — недостаточно данных, чтобы отличить "это стабильная
   категория с несколькими реальными значениями" от "это
   единообразное значение, введённое один раз при сидировании
   каталога и никогда не варьировавшееся". Hard gate или даже
   warning на поле без установленной канонической семантики создал
   бы ложное ощущение валидации там, где её предмет не определён.

   Явно различается: CLIENT_ROLE_VALIDATION (пункт 3 — Person
   реально является Client, через is_client_person()) и
   SERVICE_CLIENT_TYPE_COMPATIBILITY (этот пункт — соответствует ли
   Client некоторой декларируемой Service категории клиента) — это
   разные инварианты; первый утверждается этим ADR как HARD GATE,
   второй — как DEFERRED.

8. Template validation.

   Explicit (явно переданный) Template ID: существует и принадлежит
   выбранному Service — HARD REJECTION (TEMPLATE_NOT_FOUND /
   TEMPLATE_SERVICE_MISMATCH), уже реализовано на Telegram-границе
   (startroadmap_cmd), фиксируется как обязывающее поведение
   canonical orchestration API, а не только UX-слоя.

   Auto-selected Template ID (Service.Default Roadmap Template ID,
   либо первый результат find_roadmap_templates_by_service): ДОЛЖЕН
   быть повторно провалидирован на существование в
   create_roadmap_for_object() перед использованием — сегодня это
   не так (Phase 33A finding), фиксируется как обязательное
   исправление в Phase 33C. Stale/несуществующий auto-selected
   Template ID → HARD REJECTION с понятной ошибкой (TEMPLATE_NOT_FOUND),
   а не молчаливая деградация до нуля Stages.

   Service без Template вообще (Default Roadmap Template ID пуст, и
   find_roadmap_templates_by_service тоже пуст): Roadmap создаётся БЕЗ
   Stages из шаблона; встроенный fallback ROADMAP_TEMPLATES (по
   case_type) остаётся ОДОБРЕННЫМ, но LEGACY-ONLY поведением — не
   расширяется, не считается частью canonical Template-модели,
   кандидат на будущее устаревание отдельной фазой (не в scope этого
   ADR).

   Несколько Template, связанных с одним Service, без explicit/default
   выбора: НЕ выбирается первый молча — MULTIPLE_TEMPLATES_REQUIRE_SELECTION
   возвращается как структурный результат (уже частично реализовано
   как user-facing hint на Telegram-границе; фиксируется как
   обязывающее поведение canonical API, не только UX-подсказка).

   Template существует, но имеет ноль Stages: не является ошибкой —
   Roadmap создаётся с нулём Stages из этого источника, ровно как при
   пустом Template (симметрично, без спецкейса).

9. Duplicate active Roadmaps / open-Roadmap policy.

   Business key остаётся (Object ID, Service ID). Open-статусы для
   цели дедупликации: **active И on_hold** — оба считаются "открытым"
   Roadmap и блокируют создание второго для той же пары. completed и
   cancelled НЕ блокируют — можно начать новый Roadmap для той же
   пары Object+Service после того, как предыдущий завершён или
   отменён.

   Если найдено >1 открытых (active/on_hold) Roadmap для одной пары —
   это НЕ разрешается выбором первого: MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR
   возвращается как блокирующая ошибка, перечисляющая все конфликтующие
   Roadmap ID, без записи. Это ужесточение по сравнению с текущим
   поведением (сегодня — non-blocking warning с использованием
   первого) и фиксируется как обязательное изменение для Phase 33C.

10. Existing Roadmap reuse and retry.

    Если найден ровно один открытый (active/on_hold) Roadmap для
    пары — используется его Roadmap ID; immutable-поля (пункт 12) не
    перезаписываются; Template ID существующей записи не заменяется
    новым/другим запрошенным (текущая "existing wins" политика
    сохраняется без изменений); идемпотентная материализация Stages
    повторяется только для отсутствующих Order; результат явно
    сообщает, была ли запись создана/переиспользована, и сколько
    Stages создано/уже существовало.

    Все cross-domain валидации (пункты 2–8) выполняются ДО решения о
    reuse — нет исторического исключения: даже при reuse существующего
    Roadmap, Business/Client/Object/Service/Template должны заново
    пройти проверку на момент retry (защита от того, что состояние
    могло измениться между вызовами — например Client был архивирован
    после создания первого Roadmap).

11. Stage materialization.

    ROADMAP_STAGE_CREATION_IS_IDEMPOTENT = YES и
    ROADMAP_PARTIAL_FAILURE_IS_RECOVERABLE = YES сохраняются без
    изменений — этот ADR не вводит cross-registry атомарность, которую
    Google Sheets API не может гарантировать.

    Принятая транзакционная модель: (1) выполнить все cross-domain
    валидации (пункты 2–8) без единой записи; (2) создать или
    переиспользовать Roadmap; (3) идемпотентно материализовать
    отсутствующие Stages; (4) вернуть структурированный результат,
    включая частичный сбой Stage-материализации, если он произошёл;
    (5) повторный вызов сходится (converges) без дублей на любом шаге.
    Никакого отката через hard-delete Roadmap/Stage строки не
    вводится и не допускается.

12. Historical immutability.

    Неизменяемые после создания поля Roadmap: Roadmap ID, Business ID,
    Client ID, Object ID, Service ID, Template ID, Created timestamp.
    Retry не должен молчаливо менять ни одно из них. Проверено в
    Phase 33A: текущий код НЕ содержит ни одного writer'а, который бы
    перезаписывал любое из этих полей после создания — инвариант уже
    выполняется фактически, фиксируется здесь как обязывающий на
    будущее (а не как найденное нарушение, требующее исправления в
    Phase 33C).

13. Lifecycle boundary.

    Этот ADR НЕ проектирует полный lifecycle API Roadmap. Для целей
    валидации дедупликации вводятся только категории:
    Open = {active, on_hold}; Closed = {completed, cancelled}.
    Универсальные команды cancel/hold/restore остаются отложенными в
    отдельную будущую lifecycle-фазу (тот же паттерн, что уже принят
    для Service Domain). Hard delete остаётся запрещённым.

14. Error contract.

    Канонический orchestration-слой (create_roadmap_for_object)
    возвращает один из структурных кодов (без языковой локализации на
    этом уровне — Telegram-специфичный русский текст остаётся в
    telegram_handlers.py, транслирующем код в сообщение):

    ```
    BUSINESS_NOT_FOUND
    CLIENT_NOT_FOUND
    CLIENT_ARCHIVED
    CLIENT_ROLE_REQUIRED
    CLIENT_NOT_LINKED_TO_BUSINESS
    OBJECT_NOT_FOUND
    OBJECT_NOT_ELIGIBLE
    OBJECT_BUSINESS_MISMATCH
    OBJECT_CLIENT_MISMATCH
    SERVICE_NOT_FOUND
    SERVICE_INACTIVE
    SERVICE_BUSINESS_MISMATCH
    OBJECT_SERVICE_TYPE_MISMATCH        (non-blocking warning code)
    CLIENT_TYPE_VALIDATION_DEFERRED     (informational only, never blocks)
    TEMPLATE_NOT_FOUND
    TEMPLATE_SERVICE_MISMATCH
    MULTIPLE_TEMPLATES_REQUIRE_SELECTION
    MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR
    ROADMAP_REUSED
    ROADMAP_CREATED
    STAGE_MATERIALIZATION_PARTIAL_FAILURE
    ```

    BUSINESS_NOT_ELIGIBLE сознательно НЕ включён в этот цикл (пункт 2
    — Business-статус валидация отложена).

15. Compatibility wrappers.

    Ни один текущий вызывающий не требует compatibility wrapper —
    create_roadmap_for_object уже единственная orchestration-точка
    входа (Phase 28C), единственный вызывающий (startroadmap_cmd) уже
    делегирует ей полностью. Никакая вторая реализация валидации не
    вводится; никакая логика сопоставления/нормализации не
    дублируется в telegram_handlers.py — весь новый код валидации
    (Phase 33C) добавляется исключительно внутри
    create_roadmap_for_object(), используя уже существующие public
    API (object_manager, service_manager, person_manager,
    roadmap_template_manager), без создания новых модулей.

16. Test isolation requirements.

    Обязательно для Phase 33C, до начала любой реализации: hard
    socket-block для ВСЕХ Roadmap/Stage тестовых файлов (все 20+ файлов,
    перечисленных в Phase 33A, включая test_service_ownership_migration.py,
    где Phase 32A уже нашла замаскированный live-вызов); никакого
    обращения к живым Google Sheets/Drive/Telegram/Railway; никакой
    опоры на перехваченные сетевые исключения как признак "безопасности";
    все Business/Person/Object/Service/Template owner'ы замоканы именно
    на реальных call sites ПОСЛЕ изменения (не на устаревших целях);
    статическая/AST-проверка полноты моков (по образцу
    test_client_newclient_mock_completeness.py); production snapshot —
    только read-only проверка; ноль тестовых записей в production.

    Инцидент PRS-003 (Phase 31D: тест с устаревшим mock target записал
    реальную строку в PEOPLE_REGISTRY) зафиксирован как постоянный,
    обязывающий прецедент, по которому оценивается достаточность
    изоляции тестов Phase 33C — не разовый инцидент, а стандарт
    проверки для любой будущей Roadmap-фазы.

17. Production migration policy.

    Схема НЕ меняется, массовый rewrite данных НЕ требуется.
    Существующие Roadmap остаются историческими записями как есть.
    RM-002 остаётся нетронутым как исторический cancelled-артефакт с
    пустым Service ID — не переинтерпретируется, не исправляется, не
    удаляется. Изменяется только поведение БУДУЩЕГО создания/retry
    Roadmap (Phase 33C), задним числом ничего не проверяется и не
    перезаписывается.

18. Scope exclusions.

    Явно исключены из этого ADR и Phase 33C: редизайн Service
    lifecycle; Roadmap lifecycle-команды (cancel/hold/restore);
    редизайн Stage Domain; Payment Domain; Relation Domain; Document
    Domain; миграция схемы; hard delete; автоматический repair
    данных; изменения GTD.

Причина:

Тот же архитектурный принцип defense-in-depth на границе
orchestration, что уже применён к Object Domain (ADR-014, проверка
Business/Client при создании Object) и к Client Domain (ADR-015,
проверка Client role/Business link при создании Object), теперь
применяется к границе создания Roadmap — самой глубокой точке
cross-domain пересечения в системе (Business → Client → Object →
Service → Template → Roadmap → Stages). В отличие от предыдущих
доменных ADR, часть решений здесь сознательно ОТКЛОНЯЕТСЯ от
предложенного по умолчанию более строгого варианта (Object Type —
WARNING вместо HARD GATE; Business status — DEFERRED вместо
required), потому что конкретные production-данные, проверенные при
подготовке этого ADR, показали, что буквальное применение
предложенного по умолчанию сегодня создало бы новый функциональный
регресс, а не устранило существующий архитектурный пробел. Это
задокументировано как осознанное, evidence-based решение, а не как
отступление от процесса.

Статус:

Утверждено для реализации (Phase 33C). Ничего не реализовано в
рамках этого ADR — только архитектурное решение. Ни один
production-caller не мигрирован, ни один код не изменён.

## ADR-017 — Stage Domain Transition & Lifecycle Boundary (Phase 34B)

Контекст:

Phase 34A (Stage Domain Architecture Audit, read-only) подтвердила,
что persistence-слой Stage Domain (roadmap_manager.py — единственный
transactional writer ROADMAP_STAGES, идентичность Stage ID +
(Roadmap ID, Order), идемпотентная материализация из Template,
структурированные результаты записи, отсутствие циклов зависимостей)
остаётся корректным и НЕ пересматривается этим ADR. Аудит нашёл
единственную HIGH-находку: ни update_stage_status_in_sheet, ни
update_stage_fields, ни вызывающий их /updatestage НИКОГДА не
проверяют собственный статус родительского Roadmap — этап
`cancelled` или `completed` Roadmap сегодня можно менять точно так
же, как этап `active` Roadmap, и явный "reopen" уже `done`/`skipped`
этапа технически ничем не отличается от обычного перехода статуса.
Это может оставить Roadmap с Status=`completed`, чьи Stages больше
не удовлетворяют условию завершённости (should_complete_roadmap),
без какого-либо механизма обнаружения или исправления. Production
на момент подготовки ADR не содержит такого рассогласования (RM-001
active/8 pending, RM-002 cancelled/0 stages) — находка носит
структурный, а не инцидентный характер, и разрешается здесь тем же
процессом, что и предыдущие доменные ADR (013–016): решение
принимается ДО реализации, а не постфактум.

Решения:

1. Канонический владелец persistence.

   roadmap_manager.py остаётся единственным transactional-владельцем
   чтения и записи ROADMAP_STAGES: идентичность Stage, материализация
   из Template, персистентность статуса, расчёт Progress %,
   персистентность авто-завершения Roadmap. telegram_handlers.py и
   business_builder.py не обращаются к ROADMAP_STAGES напрямую —
   это уже так сегодня (Phase 34A подтвердила ноль нарушений) и
   этим ADR не меняется.

2. Канонический владелец transition-политики.

   Вариант B принят: новая orchestration-функция в business_builder.py
   (рабочее имя `transition_stage_status()`, точное имя решает Phase
   34C) становится единственной точкой, где проверяется статус
   родительского Roadmap ПЕРЕД вызовом
   roadmap_manager.update_stage_status_in_sheet(). Сам
   update_stage_status_in_sheet() остаётся низкоуровневой
   persistence-функцией без доступа к Roadmap-статусу — она не
   импортирует ничего о Roadmap eligibility и не станет второй
   реализацией transition-политики. telegram_handlers.py (/updatestage)
   вызывает ТОЛЬКО эту orchestration-функцию, не
   update_stage_status_in_sheet напрямую — зеркально тому, как
   ADR-016 уже сделало create_roadmap_for_object() единственной
   точкой cross-domain проверки для Roadmap-создания. Второй
   реализации transition-политики не создаётся нигде.

3. Идентичность Stage.

   Stage ID, Roadmap ID, Order подтверждены неизменяемыми полями.
   Канонический business key — (Roadmap ID, Order), как и было.
   Ни один существующий или будущий update-API не переписывает эти
   три поля. Stage ID остаётся глобально уникальным (generate_next_ids).

4. Created timestamp.

   Вариант B принят: колонка Created для ROADMAP_STAGES желательна,
   но откладывается до отдельной schema-миграции — она не нужна для
   реализации transition/lifecycle-исправления (Phase 34C) и не
   меняется в этом ADR. Схема ROADMAP_STAGES не меняется.

5. Канонический словарь статусов.

   ADR-009 сохраняется без изменений: pending, in_progress, blocked,
   done, skipped. Legacy read-alias not_started → pending сохраняется.
   Неизвестные значения остаются незаписываемыми (уже так сегодня).
   Новые статусы этим ADR не вводятся.

6. Transition-политика.

   Вариант C принят (минимальные ограничения) — со следующей
   явной матрицей:

     pending      → pending, in_progress, blocked, skipped
     in_progress  → in_progress, pending, blocked, done, skipped
     blocked      → blocked, pending, in_progress, skipped
     done         → done (без reopen через обычный transition)
     skipped      → skipped (без reopen через обычный transition)

   Явный reopen policy: обычный /updatestage (и его orchestration-
   функция из решения 2) НЕ может неявно перевести done/skipped
   обратно в pending/in_progress/blocked. Любая такая попытка
   отклоняется с кодом STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION. Полная
   команда/флаг явного reopen НЕ проектируется в этом ADR и НЕ
   реализуется в Phase 34C — фиксируется только инвариант "reopen
   требует отдельного явного намерения" и структурированный код
   ошибки для обычного пути. Любой другой переход между pending/
   in_progress/blocked разрешён в обе стороны без ограничений —
   это НЕ полноценная state machine, а минимальный, явно
   документированный набор запретов (запрет неявного reopen), как и
   рекомендовано.

7. Eligibility родительского Roadmap.

   active:     Stage status update разрешён без ограничений.
   on_hold:    Stage status update (execution-переход статуса)
               ЗАБЛОКИРОВАН, код ROADMAP_ON_HOLD; административные
               поля (Responsible/Notes/Priority/Blocking Reason/
               Due Date через update_stage_fields) разрешены (см.
               решение 19).
   completed:  Stage status update ЗАБЛОКИРОВАН, код
               ROADMAP_COMPLETED — включая попытку reopen (см.
               решение 8).
   cancelled:  Stage status update ЗАБЛОКИРОВАН НАВСЕГДА, код
               ROADMAP_CANCELLED — административные поля тоже
               блокируются (см. решение 19), кроме, возможно, Notes
               как отдельного audit-механизма — не проектируется в
               этом ADR.

   Никакая мутация статуса Roadmap не происходит неявно как побочный
   эффект Stage-transition проверки — только чтение текущего статуса
   Roadmap перед принятием решения.

8. Согласованность completed Roadmap.

   Вариант B принят: reopen Stage, принадлежащего Roadmap со
   статусом completed, БЛОКИРУЕТСЯ (код ROADMAP_COMPLETED) до тех
   пор, пока Roadmap явно не переведён в другое состояние отдельной
   будущей Roadmap lifecycle-командой (cancel/hold/restore — вне
   scope этого ADR и Phase 34C). Phase 34C реализует только блок,
   не создаёт lifecycle-команды. Completed Roadmap не может стать
   рассогласованным СИЛЕНТНО — теперь для этого требуется явное
   действие, которого пока не существует, то есть на практике
   рассогласование становится НЕВОЗМОЖНЫМ до появления lifecycle-
   команд в будущей фазе.

9. Авто-завершение Roadmap.

   Однонаправленное поведение active → completed сохраняется
   (ADR-011). Подтверждено:
     - on_hold Roadmap НЕ авто-завершается (maybe_complete_roadmap
       уже сегодня действует только на статусе active — сохраняется);
     - cancelled Roadmap НИКОГДА не авто-завершается (уже так);
     - completed Roadmap остаётся completed (уже так, идемпотентно);
     - zero-stage Roadmap не авто-завершается (should_complete_roadmap
       уже возвращает False при пустом списке этапов — сохраняется).
   maybe_complete_roadmap ДОЛЖНА проверять текущий статус Roadmap
   непосредственно перед записью (уже делает это сегодня — читает
   строку заново, а не использует кэшированное значение) — это
   поведение подтверждается как обязательное, не переизобретается.

10. Пересчёт Progress %.

    Формула ADR-010 сохраняется без изменений: (done + skipped) /
    total, round-half-up. Подтверждено:
      - Progress пересчитывается после каждого успешного изменения
        статуса Stage;
      - Progress НЕ меняется при edits только Notes/Responsible через
        update_stage_fields (эти edits не затрагивают Status);
      - сбой пересчёта Progress — структурированный downstream
        partial failure, не превращает успешную запись Status в
        ok=False;
      - retry безопасен (recalculate_roadmap_progress уже
        идемпотентна);
      - ROADMAPS.Progress % остаётся кэшированной read-model колонкой,
        хранилище прогресса не редизайнится.

11. Transition transaction model.

    Утверждена следующая последовательность для orchestration-функции
    из решения 2:
      1. resolve Stage (find_stage_by_id);
      2. resolve родительский Roadmap (find_roadmap_by_id);
      3. проверить Roadmap eligibility (решение 7) — ROADMAP_NOT_FOUND/
         ROADMAP_ON_HOLD/ROADMAP_COMPLETED/ROADMAP_CANCELLED блокируют
         здесь, до любой записи;
      4. проверить current→target Stage transition (решение 6) —
         INVALID_STAGE_TRANSITION/STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION
         блокируют здесь, до любой записи;
      5. персистентность Stage status (update_stage_status_in_sheet);
      6. побочные эффекты Start Date/Completed At (уже часть шага 5,
         не выносятся отдельно);
      7. пересчёт Progress Roadmap (recalculate_roadmap_progress);
      8. возможное авто-завершение Roadmap (maybe_complete_roadmap);
      9. вернуть структурированный результат (решение 12).
    Cross-sheet атомарность НЕ требуется (как и во всём Roadmap
    Domain — ADR-016 уже принял тот же принцип). Partial success
    должен быть видимым, не скрытым. Hard-delete rollback не
    существует и не вводится.

12. Структурированный контракт результата.

    Новая orchestration-функция возвращает как минимум:
    ok, code, error, stage_id, roadmap_id, previous_status,
    requested_status, final_status, changed, partial_success,
    written_fields, warnings, downstream_failures, progress_before,
    progress_after, roadmap_status_before, roadmap_status_after,
    retry_safe.

    Машиночитаемые коды (минимум): STAGE_NOT_FOUND, ROADMAP_NOT_FOUND,
    INVALID_STAGE_STATUS, INVALID_STAGE_TRANSITION,
    STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION, ROADMAP_ON_HOLD,
    ROADMAP_COMPLETED, ROADMAP_CANCELLED, STAGE_STATUS_UPDATED,
    STAGE_STATUS_UNCHANGED, STAGE_WRITE_PARTIAL_FAILURE,
    PROGRESS_RECALCULATION_FAILED, ROADMAP_AUTO_COMPLETION_FAILED.

    Русский пользовательский текст остаётся ИСКЛЮЧИТЕЛЬНО в
    telegram_handlers.py (централизованный error_code → текст маппинг,
    тот же паттерн, что Phase 33D уже применила для Roadmap-создания)
    — persistence- и orchestration-слои никогда не формируют
    пользовательский текст напрямую.

13. Поведение дат этапа.

    На основе текущего, уже проверенного тестами поведения
    update_stage_status_in_sheet:
      - Start Date выставляется один раз, при первом входе в
        in_progress; повторный вход в in_progress НЕ перезаписывает
        уже существующее значение (уже так сегодня — сохраняется);
      - Completed At выставляется при входе в done (уже так сегодня —
        сохраняется); поведение при skipped НЕ меняется относительно
        текущей реализации (сегодня Completed At выставляется только
        веткой new_status == "done" — skipped его не трогает; это
        сохраняется без изменений, не вводится новая семантика);
      - reopen (когда он появится в будущей фазе как отдельное явное
        действие) НЕ стирает исторические Start Date/Completed At
        автоматически — эти поля остаются honest историческими
        отметками первого прохождения, а не текущим состоянием;
        точный механизм "очистки при reopen", если он вообще
        понадобится, — решение будущей фазы, не этого ADR.

14. Порядок и зависимости этапов.

    Вариант A + C приняты: Order остаётся display/identity-полем,
    НЕ зависимостью. Параллельное и out-of-order выполнение этапов
    остаётся разрешённым и осознанным, не ошибкой. Prerequisite/
    dependency-граф явно откладывается в будущий Workflow/Task Domain
    (вне scope Stage Domain и этого ADR). Зависимости НЕ выводятся из
    числового Order неявно ни в этом ADR, ни в Phase 34C.

15. Конкурентность материализации.

    TOCTOU-риск в ensure_roadmap_stages, найденный в Phase 34A,
    принимается и документируется как НЕБЛОКИРУЮЩИЙ технический долг:
    последовательная retry-идемпотентность признаётся достаточной на
    сегодня; истинная конкурентная материализация НЕ является
    одобренным паттерном использования; distributed locking НЕ
    добавляется в Phase 34C без отдельного явного одобрения; guard
    от дублирования по (Roadmap ID, Order) остаётся обязательным и
    уже существует.

16. Семантика поля Responsible.

    Responsible остаётся информационным свободным текстом в Stage
    Domain и НЕ валидируется против PEOPLE_REGISTRY. Канонический
    Person/Role assignment остаётся исключительно в
    work_assignment_manager.py и STAGE_ENTITY_RELATIONS (Phase 22B/
    22D-механизм) — это разделение, найденное Phase 34A уже здоровым
    и намеренным, этим ADR не трогается. Будущий Organization/
    Assignment UX не должен перегружать это поле как Person ID.

17. Documents/checklists/materials/SOP/FAQ.

    Comma-list поля (Docs Required, SOP IDs, Checklist IDs, Materials
    IDs, Document Template IDs, FAQ IDs) остаются информационными
    снимками, скопированными из Template при материализации. Stage
    completion НЕ блокируется этими полями в Stage Domain. Document
    enforcement — будущая забота Document/Relation Domain; checklist
    execution — будущая забота Checklist/Task Domain; Materials IDs
    остаются reserved/deferred (materials_manager.py не существует).
    SOP/FAQ остаются read-only knowledge-ссылками.
    document_requirements.py НЕ подключается к transition-orchestration
    в Phase 34C — этот ADR явно НЕ одобряет hard completion gate.

18. Milestones.

    Расчёт коммерческих milestones остаётся read-only и внешним по
    отношению к Stage persistence (COMMERCIAL_MILESTONES_MAP —
    статический, вычисляется на чтение). Stage status update не
    создаёт записи об оплате. Отсутствие маппинга для template_id
    остаётся неблокирующим (уже так — подтверждено живым smoke-тестом
    /milestones roadmap_id=RM-001 в Phase 33D). Трактовка skipped/done
    в milestone-контексте остаётся только display/enrichment-
    поведением. Payment Domain не редизайнится.

19. Generic field updates (update_stage_fields).

    active:     Responsible/Notes/Priority/Blocking Reason/Due Date —
                разрешены без ограничений.
    on_hold:    Responsible/Notes/Due Date/Blocking Reason —
                разрешены; Priority разрешён как административное
                поле (не влияет на execution-статус); ИЗМЕНЕНИЕ
                Status через update_stage_fields блокируется тем же
                кодом ROADMAP_ON_HOLD, что и через orchestration-
                функцию (решение 20) — единой политики, не два пути.
    completed:  ВСЕ edits через update_stage_fields блокируются
                (включая Notes) — явное решение этого ADR, не
                оставлено на усмотрение реализации: completed Roadmap
                — исторический снимок, административные "уточнения"
                после завершения не считаются безопасными без
                отдельного audit-механизма, который не проектируется
                здесь.
    cancelled:  ВСЕ edits блокируются без исключений, включая Notes —
                cancelled Roadmap — не редактируемый исторический
                артефакт (см. RM-002).

    Generic field updates НЕ могут обходить Roadmap eligibility
    policy решения 7 — update_stage_fields должна проверять тот же
    Roadmap-статус, что и orchestration-функция, прежде чем писать
    любое из перечисленных полей.

20. Политика совместимости (compatibility wrappers).

    update_stage_status_in_sheet() остаётся низкоуровневой
    persistence-функцией (без доступа к Roadmap-статусу, без
    transition-валидации) — не становится compatibility wrapper, а
    остаётся тем, чем она является сегодня: точечная запись Status
    (+ автозаполнение дат/Notes), ничего сверх этого. Новая
    orchestration-функция (решение 2) становится КАНОНИЧЕСКИМ путём
    для transition — /updatestage обязана вызывать её, а не
    update_stage_status_in_sheet напрямую. update_stage_fields()
    остаётся канонической функцией для административных полей, но
    приобретает ту же Roadmap-eligibility-проверку (решение 19) —
    она не становится вторым местом, где transition-правила
    реализованы заново; она лишь проверяет Roadmap-статус тем же
    способом. Никакая state machine не дублируется в
    telegram_handlers.py — Phase 34C обязана добавить AST-guard,
    подтверждающий это (см. решение 22).

21. Направление зависимостей.

    Утверждено:
      telegram_handlers.py
        → orchestration-функция (business_builder.py)
            → roadmap_manager.py
                → sheets.py

    roadmap_manager.py по-прежнему не импортирует telegram_handlers,
    business_builder, person_manager, organization_manager, модули
    Document/Task-доменов — как и подтверждено Phase 34A (единственное
    документированное исключение — legacy service_manager fallback
    внутри _resolve_template_id, не расширяется этим ADR). Поскольку
    business_builder уже вызывает roadmap_manager (однонаправленно,
    ADR-016), выбор business_builder как orchestration-владельца
    (решение 2) не создаёт обратного цикла — сохраняется тот же
    порядок слоёв Business → Client → Service → Object → Roadmap →
    Stage, что и везде в проекте.

22. Test safety.

    Обязательно до начала Phase 34C:
      - test_recalcprogress.py, test_seed_izhs_commercial_milestones.py,
        test_seed_izhs_commercial_milestones_sop.py добавляются в
        hard socket-block реестр conftest.py (закрывает находку
        Phase 34A);
      - все новые Stage-transition тесты — под hard socket-block;
      - никакого обращения к живым Google/Drive/Telegram/Railway/
        HTTP/сокетам;
      - моки должны соответствовать РЕАЛЬНЫМ call site'ам после
        изменений (mock-completeness), а не устаревшим сигнатурам;
      - AST-guard, подтверждающий отсутствие второй реализации
        transition-политики в telegram_handlers.py;
      - production-снимок до и после запуска тестов идентичен;
      - ноль тестовых записей в production.
    Инцидент PRS-003 остаётся постоянным прецедентом, обосновывающим
    обязательность этой дисциплины для каждого нового Stage-теста.

23. Production migration.

    PRODUCTION_SCHEMA_MIGRATION_REQUIRED = NO
    PRODUCTION_DATA_REWRITE_REQUIRED = NO

    RM-001 и его 8 pending Stages остаются без изменений. RM-002
    остаётся нетронутым. Изменяется только поведение БУДУЩИХ
    вызовов transition/generic-field-update (Phase 34C) — задним
    числом ничего не проверяется и не переписывается.

24. Явно отложено (Deferred).

    Roadmap lifecycle-команды (cancel/hold/restore/явный reopen);
    Task-дедлайны и напоминания; employee work queues; Organization
    permissions; dependency-графы между этапами; document completion
    gates; исполняемые checklists; создание платёжных записей;
    schema-миграция для Created timestamp; concurrency-locking для
    материализации; обнаружение ручных правок в Sheets.

Причина:

Тот же архитектурный принцип, применённый ADR-013/014/015/016 к
границам Business/Client/Object/Service/Roadmap-создания, здесь
применяется к границе Stage-transition — единственной оставшейся
незакрытой границе в уже иначе корректно устроенном Stage Domain.
Phase 34A не нашла нарушений владения или циклов зависимостей;
единственная реальная проблема — отсутствие любой проверки
Roadmap-eligibility перед Stage-transition, что структурно допускает
рассогласование Roadmap.Status и фактического состояния его Stages.
Решение здесь сознательно МИНИМАЛЬНО: не вводится новая state
machine, не вводится schema-миграция, не создаются lifecycle-команды
— добавляется только одна проверка (Roadmap eligibility) и один
явный запрет (implicit reopen), оба оформленные как структурированные,
машиночитаемые коды, а не как молчаливая деградация или новая
неявная политика.

Статус:

Утверждено для реализации (Phase 34C). Ничего не реализовано в
рамках этого ADR — только архитектурное решение. Ни один
production-caller не мигрирован, ни один код не изменён, схема
ROADMAP_STAGES не менялась.

## ADR-018 — Organization Domain Ownership & Eligibility (Phase 35C)

Контекст:

Phase 35B (Organization Domain Architecture Audit, read-only) подтвердила,
что persistence-слой Organization Domain (organization_manager.py —
единственный transactional writer DEPARTMENT_REGISTRY/ROLE_REGISTRY/
ROLE_FUNCTIONS/PERSON_ROLE_ASSIGNMENTS; work_assignment_manager.py —
канонический владелец Stage→Role responsibility поверх
STAGE_ENTITY_RELATIONS) уже корректен и не пересматривается этим ADR.
В отличие от Service/Object/Client/Roadmap/Stage, у Organization Domain
никогда не было своего ADR — вся текущая логика построена до введения
дисциплины Audit→ADR→Foundation→Closeout. Аудит нашёл два конкретных,
подтверждённых кодом пробела: (1) organization_manager.
assign_person_to_role() проверяет существование Person, но не
проверяет is_person_archived() — архивированный Person сегодня может
быть назначен на любую Role; (2) та же функция не проверяет статус
Role вообще — planned/paused/archived Role одинаково принимают новое
назначение, хотя work_assignment_manager.assign_role_to_stage() уже
блокирует archived Role на уровне Stage-relation. Аудит также
зафиксировал реальное, не гипотетическое расхождение в production:
ROLE-001 имеет ноль активных Person Assignment (единственная запись
PRA-001 — ended), поэтому все 8 Stage у RM-001 канонически резолвятся
как "vacant", тогда как их свободно-текстовое поле Responsible
заполнено другими значениями — ничто это не согласовывает и не
показывает пользователю. Это решение закрывает эти пробелы минимально
— тем же принципом, каким ADR-013…ADR-017 закрыли аналогичные пробелы
для своих доменов — не редизайня уже корректную persistence и
Stage-relation логику.

Решения:

1. Канонические владельцы persistence.

   organization_manager.py остаётся единственным transactional-
   владельцем DEPARTMENT_REGISTRY, ROLE_REGISTRY, ROLE_FUNCTIONS,
   PERSON_ROLE_ASSIGNMENTS. work_assignment_manager.py остаётся
   каноническим orchestration-владельцем Stage→Role responsibility,
   используя STAGE_ENTITY_RELATIONS (через stage_entity_relations.py)
   как persistence-границу для role-type relation. telegram_handlers.py
   и business_builder.py не пишут эти реестры напрямую — уже так
   сегодня (Phase 35B подтвердила ноль нарушений), этим ADR не
   меняется. Второй реализации идентичности не вводится. Обратных
   импортов/циклов не вводится.

2. Канонические идентичности и неизменяемые поля.

   Department: Department ID. Role: Role ID. Role Function: Function
   ID. Person Role Assignment: Assignment ID. Stage Role Relation:
   Relation ID. Неизменяемые поля: Department (Department ID, Business
   ID, Created); Role (Role ID, Department ID — перемещение Role между
   Department не реализуется); Role Function (Function ID, Role ID);
   Assignment (Assignment ID, Person ID, Role ID); Stage Role Relation
   (Relation ID, Stage ID, Entity Type, Entity ID). Ни один
   update-API не может переписать эти поля. Схема не меняется в этом
   ADR.

3. Business-принадлежность Department.

   Текущий дизайн сохраняется: Business ID у Department опционален;
   пустой Business ID означает явно глобальный/общий Department;
   Business ID валидируется только если указан (против BIZ_REGISTRY);
   Business status eligibility остаётся отложенным (тот же принцип,
   что ADR-016 §2 уже применило к Roadmap — BIZ_REGISTRY не имеет
   канонической owned status-модели); никакого silent переноса
   Department между Business не существует и не вводится.

4. Жизненный цикл Department.

   Статусы active/archived сохраняются без изменений. Утверждено:
   ARCHIVED_DEPARTMENT_CAN_RECEIVE_NEW_ROLE = NO — будущая
   orchestration-функция создания Role должна проверять статус
   родительского Department и блокировать создание новой Role под
   archived Department кодом DEPARTMENT_ARCHIVED. Архивирование
   остаётся мягким (soft) и НЕ каскадным (подтверждено существующим
   regression-тестом — archive_department() не трогает
   role_registry) — это поведение подтверждается как обязательное, не
   переизобретается. Существующие Role сохраняются как есть. Hard
   delete не вводится. Автоматической реактивации не существует.

5. Жизненный цикл Role.

   Статусы planned/active/paused/archived сохраняются без изменений.
   Eligibility для НОВОГО Person Role Assignment:
     planned:  разрешено (пре-стаффинг), но Stage responsibility НЕ
               получает, пока Role не станет active;
     active:   разрешено и для Assignment, и для Stage responsibility;
     paused:   существующие Assignment и Stage relations сохраняются
               без изменений; новый Assignment и новая Stage
               responsibility — заблокированы;
     archived: то же самое, что paused, плюс read-паттерны (`resolve_
               stage_responsibility`) должны явно показывать
               archived_role как configuration-состояние, а не
               молчать.
   Никакого автоматического изменения существующих Assignment при
   смене статуса Role не происходит — только будущие записи меняют
   поведение.

6. Transition-политика Role.

   Утверждена минимальная матрица:
     planned  → planned, active, archived
     active   → active, paused, archived
     paused   → paused, active, archived
     archived → archived только через обычный update
   Выход из archived через обычный update ЗАБЛОКИРОВАН — требуется
   отдельное явное действие restore (код
   ROLE_RESTORE_REQUIRES_EXPLICIT_ACTION), которое НЕ реализуется в
   Phase 35D, только фиксируется инвариант и код ошибки — тот же
   принцип, что ADR-017 уже применило к Stage reopen.

7. Семантика Role Function.

   Подтверждено: Role Function — документация обязанностей/
   ответственности Role, НЕ исполняемая задача, НЕ экземпляр
   checklist, НЕ назначение сотруднику. Текущие поля и поведение
   сохраняются без изменений. Organization Domain не генерирует Task
   из Role Function.

8. Person eligibility.

   Для НОВОГО Person Role Assignment утверждены обязательные гейты:
   Person должен существовать (PERSON_NOT_FOUND); Person не должен
   быть archived (PERSON_ARCHIVED, проверка через уже существующую
   person_manager.is_person_archived()) — PRS-003 структурно
   заблокирован этим правилом для ЛЮБОГО будущего назначения, без
   изменения самой записи PRS-003. Никакой автоматической
   реактивации Person не происходит. Никакой мутации person_type не
   происходит. Специальный "employee" person_type НЕ требуется в этой
   фазе. Employment/contractor-семантика остаётся отложенной.

9. Role eligibility для Person assignment.

   planned:  разрешено. active: разрешено. paused: заблокировано
   (ROLE_PAUSED). archived: заблокировано (ROLE_ARCHIVED). Role
   должна существовать (ROLE_NOT_FOUND). Валидация происходит до
   любой записи Assignment.

10. Department eligibility для Role assignment.

    Родительский Department Role должен существовать
    (DEPARTMENT_NOT_FOUND); archived родительский Department блокирует
    НОВОЕ Person assignment (DEPARTMENT_ARCHIVED) — тем же принципом,
    что и решение 4. Существующий исторический Assignment не
    затрагивается.

11. Кросс-Business семантика.

    Принят Вариант A+B в комбинации, ровно как и предложено: если
    Department.Business ID пуст — Role глобальна, Person Business
    membership НЕ требуется; если Department.Business ID заполнен —
    Person должен быть привязан к этому же Business
    (PERSON_NOT_LINKED_TO_BUSINESS при отсутствии привязки,
    PERSON_ROLE_BUSINESS_MISMATCH при привязке к другому Business),
    кросс-Business назначение блокируется. Используется существующий
    person_manager.has_person_business_link() — новая система
    membership не изобретается. Business ID НЕ добавляется ни в Role,
    ни в Assignment — Business принадлежность Role по-прежнему
    выводится исключительно через Department (без изменения схемы).

12. Идентичность и duplicate-политика Assignment.

    Assignment ID остаётся глобально уникальным. Множественные
    активные Role на одного Person разрешены (multi-role, без
    изменений). Множественные активные People на одну Role разрешены
    (без изменений). Для ТОЧНОГО дубликата (тот же Person ID + тот же
    Role ID, оба active одновременно): ноль совпадающих active
    Assignment → создать (ASSIGNMENT_CREATED); ровно один совпадающий
    active Assignment → переиспользовать, idempotent no-op
    (ASSIGNMENT_REUSED); более одного совпадающего active Assignment
    (уже существующая целостностная аномалия, если возникнет) →
    блокирующая ошибка (MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR),
    без произвольного выбора первого — тот же принцип, что ADR-016 §9
    уже применило к дублирующимся открытым Roadmap.

13. Vocabulary и transition-политика статуса Assignment.

    Статусы active/paused/ended сохраняются без изменений. Неизвестные
    значения остаются незаписываемыми. Утверждена минимальная матрица:
      active → active, paused, ended
      paused → paused, active, ended
      ended  → ended только через обычный update
    Реактивация из ended НЕ переиспользует старую строку — требуется
    СОЗДАНИЕ НОВОЙ строки Assignment (нового периода трудоустройства/
    участия), а не мутация исторической. Код
    ASSIGNMENT_ENDED_IMMUTABLE фиксирует этот инвариант для будущей
    orchestration-функции.

14. История и неизменяемость Assignment.

    ended-строки Assignment — исторические записи. Person ID и Role ID
    неизменяемы. Hard delete не существует и не вводится. Start Date
    сохраняется, End Date выставляется при завершении. Старая строка
    никогда не переиспользуется для нового периода — для этого
    создаётся новый Assignment ID (см. решение 13). Никакой
    production-перезаписи не происходит в рамках этого ADR.

15. Владелец assignment-orchestration.

    Принят предпочтённый вариант: business_builder.py становится
    владельцем будущей cross-entity orchestration-функции для Person
    Role Assignment (рабочее имя `assign_person_to_role_validated()`
    или аналогичное, точное имя решает Phase 35D) — она проверяет
    Person (решение 8), Role (решение 9), Department (решение 10),
    Business membership (решение 11), duplicate-политику (решение 12)
    ДО вызова organization_manager.assign_person_to_role() (низкоуровневая
    persistence, без изменений). organization_manager.py остаётся
    persistence-only и не приобретает эту orchestration-логику — тот
    же принцип разделения, что ADR-016 и ADR-017 уже применили к
    Roadmap-созданию и Stage-transition. Telegram только парсит и
    рендерит. Второй реализации этой валидации нигде не создаётся.

16. Политика Stage→Role relation.

    Сохраняются без изменений: ровно одна активная Role-relation на
    Stage; reassign создаёт новую Relation-строку и деактивирует
    старую; история сохраняется; idempotent no-op при повторном
    назначении той же Role; hard delete не существует. Eligibility для
    НОВОЙ/переназначаемой Role: active — разрешено; planned/paused/
    archived — заблокировано (код ROLE_NOT_ACTIVE_FOR_STAGE_ASSIGNMENT
    — ужесточение по сравнению с текущим кодом, который сегодня
    блокирует только archived, но не planned/paused; это единственное
    расхождение с "не менять существующее поведение", явно
    обосновано: Stage responsibility — это АКТИВНОЕ исполнение
    процесса, а не пре-стаффинг, поэтому planned/paused Role логически
    не могут быть исполнителем прямо сейчас). Родительский Department
    Role должен существовать; archived Department блокирует НОВОЕ
    Stage-назначение (код DEPARTMENT_ARCHIVED), тем же принципом, что
    и решение 10.

17. Поведение существующих Stage relations после смены статуса Role.

    Явно принята non-cascade политика: пауза или архивирование Role
    НЕ деактивирует автоматически исторические Stage relations —
    ничего не переписывается и не удаляется. resolve_stage_
    responsibility() должен явно возвращать paused_role/archived_role/
    vacant_role как отдельные configuration-состояния (не просто
    единый generic "configuration_error", как сегодня, — уточнение
    видимости, не поведения) — точное имя полей решает Phase 35D.
    Будущее создание Task не должно трактовать эти состояния как
    валидного исполнителя. Автоматического ремонта не происходит.
    Существующие production-relations не изменяются в рамках этого
    ADR.

18. Границы Stage Responsible.

    Утверждено НАВСЕГДА (в дополнение к тому, что уже задокументировано
    для Stage Domain): ROADMAP_STAGES.Responsible остаётся
    информационным свободным текстом; НЕ является канонической
    ответственностью; НЕ используется для авторизации; НЕ определяет
    будущего Task assignee. Канонической ответственностью остаётся
    Stage→Role relation, канонический исполнитель разрешается через
    активные Person Role Assignment на эту Role. Поле сохраняется для
    исторического/шаблонного отображения, помечается как
    информационное в будущем UX, автоматически НЕ сверяется с
    канонической записью. Production не переписывается.

19. Концепция Employee.

    Employee-сущность не создаётся. Organization Domain использует
    Person Role Assignment как представление организационного участия
    Person. Трудовые договоры, зарплата, отпуска, HR-документы
    остаются вне Organization Domain. Специальный employee person_type
    не требуется в этой фазе.

20. Граница Permissions.

    Permission Domain не реализуется в Phase 35D. Organization-команды
    остаются доверенными только по операционному контексту (единый
    доверенный оператор — тот же принцип, что и весь остальной бот
    сегодня). Будущий multi-user access control — отдельный будущий
    Permission Domain. Self-service сотрудника и фильтрация "только
    моя работа" не реализуются в этом цикле. Зафиксировано как
    принятый, осознанный технический долг, а не молчаливо
    проигнорированный пробел.

21. Структурированный контракт результата (assignment orchestration).

    Новая orchestration-функция (решение 15) возвращает как минимум:
    ok, code, error, department_id, role_id, person_id, assignment_id,
    assignment_created, assignment_reused, previous_status,
    final_status, warnings, conflicting_assignment_ids, retry_safe.

    Машиночитаемые коды (минимум): PERSON_NOT_FOUND, PERSON_ARCHIVED,
    ROLE_NOT_FOUND, ROLE_PAUSED, ROLE_ARCHIVED, DEPARTMENT_NOT_FOUND,
    DEPARTMENT_ARCHIVED, PERSON_NOT_LINKED_TO_BUSINESS,
    PERSON_ROLE_BUSINESS_MISMATCH, ASSIGNMENT_CREATED,
    ASSIGNMENT_REUSED, MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR,
    ASSIGNMENT_ENDED_IMMUTABLE, ROLE_RESTORE_REQUIRES_EXPLICIT_ACTION,
    INVALID_ROLE_STATUS, INVALID_ASSIGNMENT_STATUS. Для Stage Role
    assignment дополнительно: STAGE_NOT_FOUND,
    ROLE_NOT_ACTIVE_FOR_STAGE_ASSIGNMENT, STAGE_ROLE_ASSIGNED,
    STAGE_ROLE_REUSED, STAGE_ROLE_REASSIGNED,
    MULTIPLE_ACTIVE_STAGE_ROLE_RELATIONS_INTEGRITY_ERROR. Русский
    пользовательский текст остаётся исключительно в
    telegram_handlers.py (централизованный маппинг, тот же паттерн,
    что Phase 33D/34D уже применили).

22. Коды результата создания Department/Role.

    Department: DEPARTMENT_CREATED, DEPARTMENT_DUPLICATE,
    DEPARTMENT_NOT_FOUND, DEPARTMENT_ARCHIVED, INVALID_DEPARTMENT_STATUS.
    Role: ROLE_CREATED, ROLE_DUPLICATE, ROLE_NOT_FOUND, ROLE_PAUSED,
    ROLE_ARCHIVED, INVALID_ROLE_STATUS, DEPARTMENT_NOT_FOUND,
    DEPARTMENT_ARCHIVED. Новые orchestration-пути не используют
    бизнес-логику на основе только строк текста ошибки; существующие
    строки могут временно сохраняться как compatibility-wrapper для
    уже существующих вызывающих.

23. Приватность и логирование.

    Разрешено логировать: code, Department ID, Role ID, Assignment ID,
    Relation ID, Person ID, значения статусов, флаги changed/reused.
    Запрещено логировать: номера телефонов, Notes, Purpose, Main
    Result, полное имя Person без необходимости, документы, полное
    тело Telegram-сообщения, credentials/токены — тот же стандарт, что
    уже применён к Stage Domain (ADR-017 §23).

24. Изоляция тестов.

    Обязательно до Phase 35D реализации: все 9 файлов
    (test_business_organization_commands.py,
    test_business_organization_department_role.py,
    test_business_organization_duplicate_protection.py,
    test_business_organization_function_assignment.py,
    test_business_organization_integration.py,
    test_business_organization_schema.py,
    test_business_organization_seed.py,
    test_business_work_assignment.py, test_inbox_bridge.py)
    добавляются в hard socket-block реестр conftest.py — закрывает
    находку Phase 35B. Все новые Phase 35D Organization-тесты — под
    hard socket-block. Никакого обращения к живым Google/Drive/
    Telegram/Railway/HTTP/сокетам. Моки должны соответствовать
    реальным call site после изменений. AST-guard, подтверждающий
    отсутствие второй реализации eligibility-политики. Production-
    снимок до и после тестов идентичен. Инцидент PRS-003 остаётся
    постоянным прецедентом.

25. Production migration.

    PRODUCTION_SCHEMA_MIGRATION_REQUIRED = NO
    PRODUCTION_DATA_REWRITE_REQUIRED = NO

    PRA-001 не реактивируется. Новый Person Assignment не создаётся.
    Stage Responsible не сверяется автоматически. Stage Role relations
    не деактивируются. Вакансия (ROLE-001 без активного Assignment) не
    "чинится". PRS-003 не изменяется. Изменяется только поведение
    БУДУЩИХ записей (Phase 35D), задним числом ничего не проверяется и
    не переписывается.

26. Контракт для Task Domain.

    Task Domain (будущая отдельная фаза) может полагаться ТОЛЬКО на
    следующие гарантии Organization Domain: assignee-Person должен
    существовать и не быть archived; assignee-Role должна быть active
    для реального исполнения; paused/archived Role не может получить
    новую работу; Business-scoped Role требует Person Business
    membership; глобальная Role принимает любого eligible Person;
    история назначений неизменяема; Task Domain НЕ должен использовать
    Stage Responsible свободный текст как источник истины; Task Domain
    НЕ должен изобретать вторую систему назначений. Схема и словарь
    статусов Task здесь НЕ утверждаются — это предмет отдельного Task
    ADR.

27. Явно отложено (Deferred).

    Permission Domain; employee self-service; HR/payroll; трудовые
    договоры; команда Role restore; команда Assignment restore;
    lifecycle Telegram-команды (archive/pause/end через бота);
    автоматические каскады; сверка Stage Responsible; уведомления о
    вакансии; Task Domain; multi-user visibility; audit log сверх уже
    существующей истории строк; schema timestamps там, где их сейчас
    нет (PERSON_ROLE_ASSIGNMENTS).

Причина:

Тот же архитектурный принцип, применённый ADR-013…ADR-017 к границам
Business/Client/Object/Service/Roadmap-создания и Stage-transition,
здесь применяется к границе Person↔Role assignment — единственной
содержательной незакрытой границе в уже корректно устроенном
Organization Domain. Phase 35B не нашла нарушений владения или циклов
зависимостей; реальная проблема — отсутствие проверки Person/Role/
Department eligibility перед записью Assignment, что структурно
допускает назначение archived Person или неактивной Role, и служит
слабым основанием для будущего Task Domain, который иначе унаследовал
бы эти же пробелы без явного решения. Решение здесь минимально: не
вводится новая Employee-сущность, не вводится Permission Domain, не
меняется схема — добавляется только проверка eligibility (Person/Role/
Department/Business) и явные запреты (Role restore из archived,
Assignment reactivation в той же строке), оформленные как
структурированные, машиночитаемые коды.

Статус:

Утверждено для реализации (Phase 35D). Ничего не реализовано в
рамках этого ADR — только архитектурное решение. Ни один
production-caller не мигрирован, ни один код не изменён, схема
Organization-реестров не менялась.