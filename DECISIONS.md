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
   ID); Role (Role ID, Department ID — перемещение Role между
   Department не реализуется); Role Function (Function ID — см. Phase
   35G §2 ниже: Role ID у Role Function является редактируемым
   reference-полем, НЕ идентичностью); Assignment (Assignment ID,
   Person ID, Role ID); Stage Role Relation (Relation ID, Stage ID,
   Entity Type, Entity ID). Ни один update-API не может переписать эти
   поля (кроме документированного исключения Role Function.Role ID).
   Схема не меняется в этом ADR.

   [Phase 35G, закрытие находки Phase 35F: пункт "Department (…,
   Created)" в исходной формулировке ссылался на несуществующее поле —
   DEPARTMENT_REGISTRY никогда не имел колонки Created/timestamp;
   формулировка выше исправлена, это не поведенческое изменение.]

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

Дополнение (Phase 35G — закрытие находки Phase 35F):

Phase 35F (Organization Domain Closeout Audit) нашёл два расхождения
между §2 этого ADR и фактической реализацией:

1. Department.Business ID оставался редактируемым через
   update_department() (был в _DEPARTMENT_EDITABLE_FIELDS), хотя §2
   декларировал его неизменяемым. Ни один caller/тест никогда не
   полагался на успешное изменение Business ID — Phase 35F
   подтвердила это прямым поиском. Решение: закрыто в Phase 35G —
   "Business ID" убран из _DEPARTMENT_EDITABLE_FIELDS; попытка
   изменить Department ID или Business ID через update_department()
   теперь блокируется кодом DEPARTMENT_IMMUTABLE_FIELD_CONFLICT ДО
   любой записи. Нулевое поведенческое влияние на существующих
   caller'ов (подтверждено тестами).

2. Role Function.Role ID оставался редактируемым через
   update_role_function(), и существующий тест
   (test_reassign_function_to_different_role,
   test_business_organization_function_assignment.py) явно проверяет
   успешное переназначение — это не случайный пробел, а
   спроектированная, задокументированная в коде (комментарий "Phase
   20A revised §6") возможность "перенести эту функцию с одной Role на
   другую". Phase 35G выбирает Вариант B (одобренное исключение), а не
   Вариант A (запрет), по следующим причинам:
     - Role Function — это документация ответственности
       (function_category/function_name/description), НЕ historical
       record: в отличие от Person Role Assignment и Stage Role
       Relation, ROLE_FUNCTIONS не хранит историю по дизайну (нет
       append-only-паттерна, нет Start/End Date) — это текущее
       состояние документации, не журнал событий.
     - Ни один caller, тест или production-ряд не зависит от Role ID
       Role Function как identity-инварианта; Function ID остаётся
       единственной идентичностью и НЕ меняется этим решением.
     - Role Functions никогда не участвуют в eligibility/assignment/
       resolution логике (подтверждено Phase 35F §8) — перемещение
       Function между Role не может нарушить Person↔Role assignment
       или Stage→Role resolution целостность, потому что ни один из
       этих путей никогда их не читает.
   Итоговое решение: Role Function.Role ID официально
   ЗАДОКУМЕНТИРОВАННОЕ ИСКЛЮЧЕНИЕ — редактируемое
   ownership/reference-поле, НЕ идентичность. Function ID остаётся
   единственной неизменяемой идентичностью Role Function. Существующий
   позитивный тест переноса сохранён без изменений.

Статус (Phase 35G): оба расхождения закрыты. §2 выше исправлен, чтобы
не противоречить фактической реализации. Organization Domain
identity-политика теперь внутренне согласована.


## ADR-019 — Task Domain Architecture Decision (Phase 36B)

Контекст:

Phase 35A и Phase 36A (Task Domain Architecture Audit / Audit Refresh,
read-only) подтвердили, что канонической Business Task-сущности не
существует: нет task_manager.py, нет TASK_REGISTRY, нет Task ID, нет
API назначения/статуса Task. Personal GTD (`/tasks`, Next Actions,
Waiting, Someday) остаётся однопользовательской системой без Business
Task ID и без Person/Role assignee — не может служить канонической
Business Task-сущностью. До Phase 35H единственной блокирующей
зависимостью было отсутствие закрытого Organization Domain: без
канонической Person↔Role eligibility Task Domain унаследовал бы те же
пробелы (archived Person, неактивная Role), которые ADR-018 закрыл для
Organization. Organization Domain теперь формально закрыт (Phase 35H)
и предоставляет: canonical `business_builder.
assign_person_to_role_canonical()`; archived Person блокируется;
paused/archived Role блокируется для нового назначения; только active
Role может получить новую Stage-ответственность; Business-scoped Role
требует Person Business membership; global Role — нет; duplicate
active Assignment блокируется; ended Assignment неизменяем; Stage→Role
relation канонична и исторична; Stage Responsible свободный текст
остаётся исключительно информационным. Это решение — Task Domain's
собственный ADR, применяющий тот же архитектурный принцип
Audit→ADR→Foundation→Closeout, который ADR-013…ADR-018 уже применили к
Service/Object/Client/Roadmap/Stage/Organization.

Решения:

1. Канонические владельцы persistence и orchestration.

   task_manager.py — единственный transactional-владелец TASK_REGISTRY
   и TASK_ASSIGNMENTS. business_builder.py — единственный
   cross-domain orchestration-владелец: Task creation, Task status
   transition, Task relation validation, Task assignment/reassignment,
   Task lifecycle eligibility, idempotency, structured result
   assembly. Направление зависимостей: telegram_handlers →
   business_builder → task_manager → sheets. business_builder может
   вызывать read-only validation API из person_manager,
   organization_manager, roadmap_manager, service_manager,
   object_manager и существующих канонических person-related helpers.
   task_manager НЕ импортирует business_builder/telegram_handlers.
   Закрытые домены (Object/Client/Service/Roadmap/Stage/Organization)
   НЕ импортируют task_manager — зависимость только в одну сторону, от
   Task к ним, никогда наоборот.

2. Каноническая сущность Business Task.

   Новая каноническая сущность: Business Task. Реестр: task_registry.
   Идентичность: Task ID, префикс `TSK-` (проверено — не
   пересекается ни с одним существующим префиксом в _ID_PREFIXES).
   Task ID глобально уникален.

3. Неизменяемые поля Task.

   Task ID, Business ID, Created At — неизменяемы через обычный
   update-путь. Entity-reference поля (Client ID, Object ID, Service
   ID, Roadmap ID, Stage ID) редактируемы только через явную
   canonical relink-операцию, отдельную от обычного admin-update; в
   Phase 36C relink-команда НЕ реализуется — foundation допускает
   установку этих полей только при создании. Обычное admin-обновление
   не может переписать Business ID. Обычное status-обновление не
   может переписать relation-поля. Никакого silent переноса Task
   между Business не существует. Прямые правки листа через caller не
   допускаются.

4. Каноническая сущность Task Assignment.

   Отдельная каноническая сущность: Task Assignment. Реестр:
   task_assignments. Идентичность: Task Assignment ID, префикс
   `TAS-` (проверено — не пересекается ни с одним существующим
   префиксом). Поля: Task Assignment ID, Task ID, Responsible Role ID,
   Assignee Person ID, Status, Start Date, End Date, Assignment Type,
   Created At, Updated At. Изменения назначения сохраняют историю:
   reassign создаёт новую Assignment-строку и завершает (`Status =
   ended`) предыдущую текущую строку. Hard delete не вводится. Ровно
   одна текущая active Assignment-строка на Task. Unassigned Task
   разрешён через отсутствие активной Assignment-строки (не через
   специальное значение).

5. Task versus personal GTD.

   Business Task и personal GTD Next Action — раз и навсегда отдельные
   реестры. `/tasks` остаётся GTD-владением и НЕ изменяется этим или
   любым Task Domain ADR. Employee Task никогда не создаёт personal
   GTD-строку автоматически. Общей идентичности нет. Two-way sync в
   foundation не вводится. Опциональная одно-сторонняя связь: Business
   Task может хранить опциональное поле GTD Action ID — используется
   только для Didar-owned Task; GTD остаётся source-of-truth для
   personal-строки; Task остаётся source-of-truth для business
   execution state. GTD Action ID включён в foundation-схему как
   опциональное, по умолчанию пустое поле, без синхронизирующего
   поведения.

6. Task versus Stage.

   Task и Stage — раздельные сущности. Task может опционально
   ссылаться максимум на один Stage; один Stage может иметь много
   Task. Task completion НЕ авто-завершает Stage. Stage completion НЕ
   авто-закрывает Task. Автоматическая генерация Task из Stage не
   вводится. Автоматического lifecycle-каскада нет. Task↔Stage
   automation остаётся отложенным явно вне foundation.

7. Иерархия связей Task с бизнес-сущностями.

   Ровно один обязательный Business ID. Опциональные единичные
   ссылки: Client ID, Object ID, Service ID, Roadmap ID, Stage ID.
   Cross-validation: каждая указанная сущность должна существовать;
   каждая указанная сущность должна принадлежать тому же Business там,
   где Business-принадлежность применима; если указаны и Stage ID, и
   Roadmap ID — они должны соответствовать друг другу (Stage ID
   принадлежит указанному Roadmap ID), иначе
   TASK_ENTITY_RELATION_MISMATCH; если указаны Roadmap и Object/Service
   — они должны быть взаимно согласованы (тот же принцип, что
   `create_roadmap_for_object()` уже проверяет для Roadmap creation);
   many-to-many Task-связей в foundation нет; Task может существовать
   только с Business ID и Title (все остальные ссылки опциональны).

8. Схема task_registry (foundation).

   Обязательные поля: Task ID, Business ID, Title, Status, Source,
   Idempotency Key, Created At, Updated At. Опциональные
   foundation-поля: Description, Priority, Due Date, Client ID, Object
   ID, Service ID, Roadmap ID, Stage ID, Responsible Role ID, Assignee
   Person ID, Completed At, Cancelled At, Created By, GTD Action ID.
   Отложено (не foundation): Reminder At, Follow-up Date, External ID,
   recurring-метаданные, dependency graph поля, SLA/escalation поля.
   Responsible Role ID и Assignee Person ID остаются на Task-строке
   как cache-поля текущего назначения (для быстрого чтения без join с
   task_assignments), в дополнение к task_assignments как
   единственному источнику истины по истории. Cache-поля пишутся
   только канонической assignment-orchestration функцией — прямая
   запись caller'ом запрещена. Рассогласование cache с
   task_assignments должно быть детектируемо (через architecture
   guard / будущий reporting), но не исправляется автоматически в
   foundation.

9. Модель назначения Person и Role.

   Task может быть unassigned. Task может иметь только Responsible
   Role (без Person) — валидная конфигурация "пре-стаффинг/вакантно".
   Task может иметь Assignee Person без явной Role только если Person
   eligible как активный, не архивированный, с корректным Business
   membership — это не вводит вторую систему eligibility, а повторно
   использует то же Organization-правило. Task может иметь оба поля
   одновременно. Канонические роли: Responsible Role — durable
   организационная ответственность (тот же принцип, что Stage
   Responsibility уже использует); Assignee Person — текущий
   исполнитель. Если указаны и Role, и Person — Person должен быть
   eligible для этой Role и её Business (через существующую
   Organization-проверку, не изобретённую заново). Active-но-vacant
   Role — валидная конфигурация ответственности; Task может оставаться
   открытым, пока Role вакантна.

10. Person eligibility для Task.

    Person должен существовать (иначе PERSON_NOT_FOUND). Person не
    должен быть архивирован для НОВОГО назначения/переназначения
    (иначе PERSON_ARCHIVED) — как и в Organization Domain, эта
    проверка применяется только к моменту записи нового назначения,
    не ретроактивно. Business-scoped Task требует Person Business
    membership (иначе PERSON_NOT_LINKED_TO_BUSINESS /
    PERSON_TASK_BUSINESS_MISMATCH — та же пара кодов и то же различие,
    что ADR-018 §11 уже установил для PERSON_NOT_LINKED_TO_BUSINESS /
    PERSON_ROLE_BUSINESS_MISMATCH). Архивирование Person после
    назначения НЕ вызывает автоматическое удаление/отмену исторических
    Task/Assignment-строк — существующее назначение становится
    конфигурационным вопросом для reporting/resolution, не ошибкой,
    требующей немедленного исправления. Employee-реестр не вводится.

11. Role eligibility для Task.

    Для НОВОГО Task-назначения: active Role — разрешена. planned
    Role — разрешена ТОЛЬКО как Responsible Role для будущих/
    пре-стаффинг Task (Task остаётся в статусе `new`/`ready`, никогда
    `in_progress`, пока Role не станет active) — planned Role НЕ
    разрешена как активно исполняющий Assignee-резолюшн. paused Role —
    заблокирована для нового назначения (ROLE_PAUSED). archived Role —
    заблокирована для нового назначения (ROLE_ARCHIVED). Родительский
    Department должен существовать (DEPARTMENT_NOT_FOUND) и не быть
    архивирован (DEPARTMENT_ARCHIVED) — те же коды и та же проверка,
    что ADR-018 §16 уже установило для Stage→Role eligibility.
    ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION используется когда Role
    указана как активно исполняющая, но не active (в отличие от
    planned-как-Responsible-only случая выше).

12. Инвариант текущей Assignment-строки.

    Ноль активных Task Assignment-строк → Task unassigned. Ровно одна
    активная строка → каноническое текущее назначение. Больше одной
    активной строки → integrity error
    (MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR, со всеми
    конфликтующими ID, без произвольного первого выбора — тот же
    принцип "no arbitrary first-pick", что ADR-016 §9 и ADR-018 §12
    уже установили). Reassignment завершает текущую строку и создаёт
    новую. Повторный идентичный assignment-запрос идемпотентен и
    переиспользует текущую строку (TASK_ASSIGNMENT_REUSED).

13. Словарь статусов Task Assignment.

    Task Assignment Status: active, ended — минимальный словарь,
    "paused" НЕ вводится на уровне Assignment. Task execution
    waiting/blocked принадлежит словарю статусов Task (§14), не
    Assignment — конфликтовать они не могут, потому что описывают
    разные вещи (Assignment = "кто отвечает", Task status = "что
    происходит с работой"). Reassignment/end сохраняют историю
    (ended-строка никогда не удаляется и не переиспользуется).

14. Словарь статусов Task.

    Отдельный, не переиспользующий GTD или Stage словарь: new, ready,
    in_progress, waiting, blocked, done, cancelled, skipped. new —
    зафиксирован, но не готов к работе; ready — готов к исполнению;
    in_progress — выполняется; waiting — ожидает внешнего ответа/
    события; blocked — не может продолжаться по внутренней причине;
    done — завершён; cancelled — более не требуется; skipped —
    намеренно пропущен в процессном контексте (по аналогии со Stage
    `skipped`).

15. Матрица переходов Task.

    new → {new, ready, cancelled, skipped}. ready → {ready,
    in_progress, waiting, blocked, done, cancelled, skipped}.
    in_progress → {in_progress, ready, waiting, blocked, done,
    cancelled, skipped}. waiting → {waiting, ready, in_progress,
    blocked, done, cancelled, skipped}. blocked → {blocked, ready,
    in_progress, waiting, cancelled, skipped}. done → {done only}.
    cancelled → {cancelled only}. skipped → {skipped only}. Выход из
    done/cancelled/skipped через обычный update требует будущего
    явного reopen/restore-действия (TASK_REOPEN_REQUIRES_EXPLICIT_ACTION
    — не реализуется в foundation, только код блокировки, тот же
    принцип, что ROLE_RESTORE_REQUIRES_EXPLICIT_ACTION и
    STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION). Неизменившийся статус —
    успех/no-op (TASK_STATUS_UNCHANGED). Неизвестный целевой статус
    блокируется (INVALID_TASK_STATUS). Недопустимый переход —
    INVALID_TASK_TRANSITION.

16. Политика временных меток Task.

    Started At: устанавливается при первом переходе в in_progress;
    никогда не перезаписывается повторно; никогда не сбрасывается
    молча. Completed At: устанавливается при done; никогда не
    устанавливается при skipped; никогда не сбрасывается молча.
    Cancelled At: устанавливается при cancelled; никогда не
    сбрасывается молча. Отдельное поле Skipped At НЕ вводится в
    foundation — вместо этого используется Updated At вместе с
    финальным статусом; отдельная метка может быть добавлена позже,
    если появится конкретная потребность. Restore/reopen не
    реализуется в foundation.

17. Семантика Waiting.

    Waiting утверждён как статус Task (не как assignment-атрибут).
    Waiting означает, что требуется внешний ответ/событие; Task
    остаётся business-owned; Waiting НЕ подразумевает делегирование.
    Follow-up Date отделён от Due Date. В foundation сохраняется
    только сам статус Waiting; поле "Waiting For" (Person ID или
    свободный текст) и Follow-up Date откладываются — более богатые
    Waiting-метаданные добавляются позже отдельным решением.

18. Семантика делегирования.

    Delegation утверждён как assignment-метаданные/событие, НЕ как
    статус Task. Task может одновременно быть: ready и delegated;
    in_progress и delegated; waiting и delegated; blocked и delegated.
    Отдельного статуса `delegated` не вводится — это сохраняет
    словарь статусов Task ортогональным словарю Assignment, как и §13
    уже устанавливает.

19. Due Date, Reminder, Follow-up, Calendar.

    Due Date входит в foundation-схему. Reminder At зарезервирован как
    поле, но без автоматизации в foundation. Follow-up Date отложен.
    Calendar Event — отдельная, не связанная в foundation система.
    Recurring-автоматизация отложена. Поведение отмены напоминаний
    откладывается до будущей Automation Domain. Calendar-интеграция НЕ
    входит в Phase 36C.

20. Roadmap/Stage lifecycle eligibility для Task.

    Новое создание Task, связанного с active Roadmap — разрешено.
    С on_hold Roadmap — создание/подготовка admin-полей Task
    разрешена; переход в in_progress блокируется
    (ROADMAP_ON_HOLD); переходы в ready/waiting/blocked и
    admin-изменения разрешены (тот же принцип, что ADR-017 §12 уже
    установило для Stage: on_hold блокирует только исполнительный
    переход, не административное редактирование). С completed
    Roadmap — новое создание связанного Task блокируется
    (ROADMAP_COMPLETED). С cancelled Roadmap — новое создание
    связанного Task блокируется (ROADMAP_CANCELLED). С terminal Stage
    (done/skipped) — новое создание связанного Task блокируется
    (STAGE_TERMINAL). Существующие Task: никакого автоматического
    cancel/complete-каскада; никакой автоматической мутации Stage;
    никакой автоматической мутации Roadmap; несоответствия помечаются
    read-only отчётностью позже (TASK_LIFECYCLE_INCONSISTENCY), не
    исправляются автоматически.

21. Источники создания Task (foundation).

    Разрешены: канонический API; точная Telegram-команда. Отложены:
    AI Inbox; автоматическая генерация из Stage; Service/Roadmap
    templates; Checklist/Document generation; Gmail; Calendar;
    SendPulse; Binotel; recurring automation; внешние интеграции.

22. Namespace команд.

    Не конфликтует с GTD `/tasks`: /newbctask, /bctasks, /bctask,
    /updatetask, /assigntask, /reassigntask. Проверено — ни одно имя
    не пересекается ни с одним зарегистрированным CommandHandler.
    `/tasks` НЕ изменяется.

23. Идемпотентность создания.

    Первичный ключ: явный Idempotency Key. Будущий внешний ключ:
    Source + External ID. Title-based dedup НЕ является каноническим
    (тот же принцип "no arbitrary first-pick", применённый здесь к
    созданию). Ноль совпадений → create (TASK_CREATED). Ровно одно
    совпадение → reuse (TASK_REUSED). Больше одного совпадения →
    integrity error (MULTIPLE_TASK_IDEMPOTENCY_MATCHES), все
    конфликтующие ID возвращаются, без произвольного выбора. Пустой
    Idempotency Key: поле опционально на уровне схемы; канонический
    API для Telegram-пути ВСЕГДА генерирует детерминированный
    request-scoped ключ; прямые внутренние вызовы могут опустить его
    только при явном осознанном принятии неидемпотентного создания.

24. Политика admin-update Task.

    Редактируемые простые поля через обычный admin-update: Title,
    Description, Priority, Due Date, Created By. Entity relation поля
    (Client ID, Object ID, Service ID, Roadmap ID, Stage ID, GTD Action
    ID) редактируемы ТОЛЬКО через отдельный явный canonical relink API
    (не через обычный admin-update) — попытка обычного обновления
    relation-поля блокируется
    (TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION). Business ID
    никогда не редактируется (TASK_IMMUTABLE_FIELD_CONFLICT). Cache-
    поля назначения (Responsible Role ID, Assignee Person ID) никогда
    не редактируются через admin-update — только через каноническую
    assignment-orchestration. Status редактируется только через
    transition API, никогда через admin-update.

25. Структурированный result-контракт Task.

    Стабильные поля: ok, code, error, task_id, business_id,
    previous_status, requested_status, final_status, changed,
    assignment_changed, task_created, task_reused, assignment_id,
    previous_assignment_id, warnings, conflicting_task_ids,
    conflicting_assignment_ids, retry_safe. Коды по семействам:
    Entity — TASK_NOT_FOUND, BUSINESS_NOT_FOUND, PERSON_NOT_FOUND,
    PERSON_ARCHIVED, ROLE_NOT_FOUND, ROLE_PAUSED, ROLE_ARCHIVED,
    DEPARTMENT_NOT_FOUND, DEPARTMENT_ARCHIVED, ROADMAP_NOT_FOUND,
    STAGE_NOT_FOUND, TASK_ENTITY_RELATION_MISMATCH. Creation —
    TASK_CREATED, TASK_REUSED, MULTIPLE_TASK_IDEMPOTENCY_MATCHES.
    Status — INVALID_TASK_STATUS, INVALID_TASK_TRANSITION,
    TASK_REOPEN_REQUIRES_EXPLICIT_ACTION, TASK_STATUS_UPDATED,
    TASK_STATUS_UNCHANGED. Assignment — TASK_ASSIGNMENT_CREATED,
    TASK_ASSIGNMENT_REUSED, TASK_REASSIGNED, TASK_UNASSIGNED,
    MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR. Lifecycle —
    ROADMAP_ON_HOLD, ROADMAP_COMPLETED, ROADMAP_CANCELLED,
    STAGE_TERMINAL, TASK_LIFECYCLE_INCONSISTENCY. Mutation —
    TASK_IMMUTABLE_FIELD_CONFLICT,
    TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION. Ни один код не
    пересекается по имени с существующими Object/Client/Service/
    Roadmap/Stage/Organization кодами (проверено).

26. Privacy и logging.

    Разрешено логировать: code, Task ID, Business ID, Roadmap ID,
    Stage ID, Person ID, Role ID, Assignment ID, значения статусов,
    changed/reused-флаги. Запрещено: Title там, где не необходимо,
    Description, Notes, телефонные номера, документы, полное
    Telegram-сообщение, credentials/токены, чувствительные личные
    детали. Русскоязычный пользовательский текст остаётся
    исключительно в telegram_handlers.py, никогда в task_manager.py
    или business_builder.py — тот же принцип, что уже применяется во
    всех закрытых доменах.

27. Test isolation.

    Все Task-тесты регистрируются в hard socket-block немедленно при
    создании файла, ДО написания какой-либо логики. Mock-completeness
    guard обязателен. Никакого Google/Drive/Telegram/Railway/HTTP/
    socket доступа ни в одном Task-тесте. Architecture guards для
    ownership, для GTD-разделения и для запрета изменения `/tasks`.
    Ни один тест не создаёт production-строки. Production snapshot
    до/после каждой фазы. PRS-003 precedent остаётся обязывающим —
    каждый новый Task-тестовый файл регистрируется в момент создания,
    не постфактум.

28. Production migration.

    PRODUCTION_SCHEMA_MIGRATION_REQUIRED = YES — создаются два новых
    листа, task_registry и task_assignments.
    PRODUCTION_DATA_REWRITE_REQUIRED = NO — существующих Business
    Task-данных не существует (greenfield), никакой GTD-миграции,
    никакого rewrite Stage/Organization данных. Foundation
    провижионирует только пустые реестры с заголовками, без строк
    данных.

29. Область работ Phase 36C.

    Авторизовано реализовать вместе: схема task_registry; схема
    task_assignments; task_manager persistence; business_builder
    orchestration; creation/idempotency; Task transitions; Task
    Assignment current-row/history поведение; entity validation; hard
    socket-block; architecture guards; тесты. НЕ авторизовано в Phase
    36C: Telegram UX сверх минимального test-plumbing (полноценный
    caller UX — предмет Phase 36D); deployment; AI routing; reminders/
    calendar; automatic Task↔Stage updates; Task generation из
    templates/documents/checklists; внешние интеграции; Permission
    Domain.

Причина:

Тот же архитектурный принцип, применённый ADR-013…ADR-018 к границам
Business/Client/Object/Service/Roadmap-создания, Stage-transition и
Organization Person↔Role assignment, здесь впервые применяется к
совершенно новой сущности — Business Task — потому что она нигде не
существовала раньше и требует полного набора решений, а не только
закрытия пробела. Phase 35A/36A показали: (1) канонической Task-
сущности не существует; (2) personal GTD структурно непригоден как её
замена (нет Business ID, нет Person/Role assignee, single-user); (3)
единственная блокирующая зависимость — закрытый Organization Domain —
теперь удовлетворена. Решение здесь сознательно переиспользует уже
проверенные паттерны вместо изобретения новых: canonical assignment
orchestration (как ADR-018 §15), no-arbitrary-first-pick duplicate
policy (как ADR-016 §9 / ADR-018 §12), non-cascading lifecycle
(как ADR-017 §2 / ADR-018 §16), terminal-state-requires-explicit-
reopen (как ADR-017 §6 / ADR-018 §6), и permanently-informational
free-text boundary (как Stage Responsible в ADR-018 §19) — Task Domain
не вводит ни одного нового архитектурного принципа, только применяет
уже утверждённые к новой сущности.

Статус:

Утверждено для реализации (Phase 36C). Ничего не реализовано в рамках
этого ADR — только архитектурное решение. task_registry и
task_assignments не созданы. Ни один production-caller не мигрирован,
ни один код не изменён, схема Google Sheets не менялась. GTD Core
(`/tasks`, inbox_processor.py, telegram_bot.py, project_planner.py,
calendar_sync.py) не затронут.


## ADR-020 — Document Domain Architecture Decision (Phase 37C)

Контекст:

Phase 37B (Document Domain Architecture Audit, read-only) нашла домен
существенно более зрелым, чем предполагалось при выборе (Phase 37A):
уже существует частичный persistence-модуль
(`document_registry_manager.py` — генерация ID, разрешение и
кросс-валидация связей, выбор Drive-папки, устаревший
stage-scoped алгоритм missing-document), полностью изолированная и
приватность-дисциплинированная AI-подсистема
(`document_intelligence.py` — никогда не пишет `document_registry`,
всегда bounded-логирование), отдельный более полный evaluator
требований (`document_requirements_query.py`), и 376 уже проходящих
тестов (в 4 файлах, ни один не зарегистрирован в hard socket-block —
самая критичная находка аудита). Реальный архитектурный пробел уже,
чем предполагалось изначально при выборе домена: сама
запись `append_business_row("document_registry", ...)` выполняется
напрямую внутри `telegram_handlers.py` (`registerdoc_confirm()` и
`uploaddoc_confirm()`), никакого business_builder-orchestration нет,
никакого структурированного result-контракта нет, и существуют два
конкурирующих алгоритма missing-document
(`compute_stage_document_status()` устаревший рядом с более полным
`evaluate_scope()`). Оба существующих production-ряда (DREG-001,
DREG-002) корректны и не требуют миграции. Это решение — тот же
архитектурный принцип, применённый ADR-013…ADR-019 к
Service/Object/Client/Roadmap/Stage/Organization/Task — здесь впервые
применяется к домену, где значительная часть логики уже написана
качественно и нуждается в формализации владения, а не в редизайне.

Решения:

1. Канонические границы сущностей.

   Operational Document — канонический Document Domain entity.
   Реестр: document_registry. Идентичность: Document ID, префикс
   `DREG-`. Operational Document — источник истины для business
   ownership, business-entity связей, document lifecycle, Drive file
   references, version family, version number, upload-метаданных и
   (в будущем) текущих review-полей.

   Document Template остаётся отдельной supporting reference
   подсистемой: document_template_registry, владелец —
   knowledge_manager.py без изменений. Document Template НЕ является
   идентичностью Operational Document; Document Domain может читать
   его для классификации и требований, но не берёт на себя владение
   его persistence.

   Document Requirement НЕ вводится как хранимая сущность в
   foundation — требования остаются детерминированным derived view
   поверх связей Document Template↔Stage/knowledge relations; никакого
   реестра document_requirements в Phase 37D.

   Document Content / AI Analysis остаётся derived intelligence
   данными; владелец — document_intelligence.py без изменений; НЕ
   является идентичностью Operational Document; анализ опционален;
   сбой анализа не может испортить Document lifecycle; AI не может
   approve/reject/review/archive или иным образом менять operational
   truth — AI-классификация производит только suggestions.

   Drive File — внешняя ссылка на файл, не идентичность Document;
   Drive-интеграция владеет фактическим хранением файла; Document
   Domain владеет каноническими reference-полями; Drive URL —
   метаданные, не идентичность; Drive-операции orchestrated, никогда
   не рассматриваются как отдельное владение сущностью.

2. Владение persistence.

   Новый модуль business_core/document_manager.py становится
   единственным persistence-владельцем document_registry: exact-ID
   чтения, list/filter чтения, генерация Document ID, генерация
   Document Family ID, низкоуровневое создание Document,
   низкоуровневая запись разрешённых полей, низкоуровневая запись
   статуса, version/family lookups, Drive File ID duplicate lookup,
   будущий exact idempotency lookup, current-row verification.
   Существующий document_registry_manager.py: его
   persistence-примыкающие helpers (генерация ID, resolve_and_
   validate_links, compute_stage_document_status) мигрируют в
   document_manager.py там, где это уместно; чисто relation/folder-
   resolution helpers (resolve_target_drive_folder) сохраняются
   отдельно только если их размещение остаётся чистым. После Phase
   37D должен существовать РОВНО один канонический
   persistence-владелец Operational Document — не два конкурирующих
   Document-менеджера. Реализация — предмет Phase 37D, не этого ADR.

3. Владение cross-domain orchestration.

   business_builder.py — единственный владелец Document orchestration:
   регистрация метаданных, orchestration Telegram-file upload,
   валидация связей, последовательность Drive/Sheet failure,
   creation retry/idempotency, lifecycle transitions, admin-обновления
   метаданных, создание версии, entry point для requirement
   evaluation, сборка structured result. Направление зависимостей:
   telegram_handlers → business_builder → document_manager → sheets;
   для upload: business_builder → Drive adapter → document_manager.
   business_builder может вызывать read-only API из person_manager,
   object_manager, service_manager, roadmap_manager, task_manager
   (если Task-связь одобрена в будущем), knowledge_manager,
   document_requirements_query, document_intelligence, Drive adapter.
   document_manager НЕ импортирует business_builder/telegram_handlers;
   document_intelligence НЕ пишет document_registry; knowledge_manager
   НЕ пишет operational Documents; Telegram НЕ пишет document_registry
   напрямую; закрытые домены НЕ импортируют document_manager; обратных
   циклов зависимостей нет.

4. Идентичность и неизменяемые поля.

   Каноническая идентичность: Document ID, префикс DREG-, глобально
   уникален. Неизменяемые поля: Document ID, Business ID, Created At,
   Document Family ID (после создания), Version (после создания).
   Drive File ID — не идентичность. Document Template ID — не
   идентичность. Никакого переноса Document между Business.
   Обычный update не может изменить identity/version поля. После
   Foundation — ни одной второй реализации генерации ID; генерация ID
   caller-стороной запрещена; ID генерируется только после валидации
   и проверки reuse. Коды: DOCUMENT_IMMUTABLE_FIELD_CONFLICT,
   DOCUMENT_VERSION_FIELD_IMMUTABLE, DOCUMENT_FAMILY_FIELD_IMMUTABLE.

5. Решение по схеме.

   Существующая схема document_registry сохраняется без изменений в
   Phase 37D: Document ID, Document Family ID, Version, Business ID,
   Client ID, Object ID, Roadmap ID, Stage ID, Document Template ID,
   Document Name, Status, Drive File ID, Drive File URL, File Name,
   Mime Type, Uploaded At, Uploaded By, Reviewed At, Reviewed By,
   Rejection Reason, Notes, Created At, Updated At. Task ID НЕ
   добавляется в Phase 37D — Task-связи сегодня не существует,
   добавление расширило бы объём миграции и связей; Task↔Document
   связь может быть спроектирована позже через явный relation-механизм
   или изменение схемы. Не добавляются: idempotency key, checksum,
   file size, review-history поля, retention-поля, AI-derived поля,
   automation-поля. Phase 37D закрывает владение на текущей схеме.

6. Модель регистрации и загрузки.

   Одна каноническая creation orchestration с двумя режимами входа.
   Mode A (register existing Drive file): валидирует метаданные и
   связи, читает authoritative Drive-метаданные, создаёт один
   Operational Document, не загружает новый файл. Mode B (upload
   Telegram file): валидирует метаданные и связи где возможно заранее,
   загружает в Drive, читает authoritative Drive-метаданные,
   персистирует один Operational Document, компенсирует при сбое
   persistence. Оба режима используют один и тот же канонический
   Document creation result contract. Upload — не отдельная сущность;
   регистрация и upload не имеют раздельных identity-правил; оба
   создают одну версию Operational Document. Telegram не строит
   финальные строки напрямую.

7. Безопасность Drive/Sheet сбоев.

   Ратифицируется и формализуется уже существующий безопасный паттерн
   (Phase 15B): валидация Business и связей → выбор целевой папки →
   установка request guard → загрузка в Drive → чтение authoritative
   Drive-метаданных → персистирование строки Document → верификация
   персистированной строки → структурированный успех. Если Drive
   upload не удался — ни одна строка Document не создаётся. Если
   persistence Document не удалась после успешного Drive upload —
   попытка Drive-компенсации (trash); DRIVE_UPLOAD_COMPENSATED при
   успехе; DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING при
   неудаче компенсации; успех никогда не заявляется ложно.
   Существующие Drive-файлы, зарегистрированные через Mode A, никогда
   не удаляются автоматически. Текущее compensation-поведение не
   ослабляется.

8. Идемпотентность создания.

   Событийная/request-scoped идемпотентность без нового поля схемы.
   Telegram upload: Telegram update ID + Telegram file unique ID,
   одна и та же in-memory/request операция переиспользуется или
   блокируется, без дублирующей загрузки при retry в поддерживаемом
   окне операции. Register-existing-file: проверяется Business ID +
   Drive File ID — ноль совпадений → создать; ровно один совпадающий
   Operational Document → переиспользовать; больше одного → блок со
   всеми конфликтующими Document ID, без первого выбора.
   Telegram-upload после создания в Drive: Drive File ID должен быть
   уникален среди активных/не-archived Document; один существующий
   совпадающий может быть переиспользован только при совместимых
   связях; несколько совпадений блокируют. Dedup по filename запрещён;
   dedup по Document Name запрещён; dedup по MIME запрещён; content
   hash не является foundation Document-creation ключом; будущие
   автоматизированные интеграции должны добавить явный Source/External
   ID или Idempotency Key через отдельное будущее решение о схеме.
   Коды: DOCUMENT_REGISTERED, DOCUMENT_UPLOADED, DOCUMENT_REUSED,
   MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES,
   DOCUMENT_RELATION_CONFLICT_ON_REUSE, DRIVE_UPLOAD_FAILED,
   DRIVE_UPLOAD_COMPENSATED, DOCUMENT_PERSISTENCE_FAILED,
   DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING.

9. Модель версионирования.

   Существующая модель сохраняется: одна строка document_registry —
   одна неизменяемая версия Document; Document Family ID группирует
   логические версии; Version неизменяем; новая версия создаёт новую
   строку Document; старые версии сохраняются; никакой замены
   file-reference на старой строке; никакого hard delete; никакого
   отдельного реестра document_versions. Новый независимый Document:
   новый Document ID, новый Document Family ID, Version=1. Новая
   версия: новый Document ID, существующий Document Family ID,
   Version=max+1. Явная команда /newdocversion, supersedes-поле,
   автоматическое создание версии и сравнение версий откладываются.
   Phase 37D может реализовать низкоуровневую/каноническую поддержку
   новой версии только если она ограничена, полностью протестирована
   и требуется текущей миграцией кода — иначе схема сохраняется, а
   user-facing операция откладывается.

10. Словарь операционных статусов Document.

    Точные операционные статусы: uploaded, under_review, approved,
    rejected, superseded, archived. НЕ вводятся: registered как
    отдельный статус (оба текущих режима создания дают Document с
    authoritative Drive-ссылкой — разделения "зарегистрирован без
    файла" не существует и не вводится); processing/analyzed как
    операционные статусы; expired как хранимый статус в foundation;
    deleted. Content/AI-статусы остаются отдельными: pending,
    processing, completed, failed, unsupported.

11. Матрица переходов.

    uploaded → {uploaded, under_review, archived, superseded}.
    under_review → {under_review, approved, rejected, uploaded,
    archived, superseded}. approved → {approved, archived,
    superseded}. rejected → {rejected, under_review, uploaded,
    archived, superseded}. superseded → {superseded только через
    обычное обновление}. archived → {archived только через обычное
    обновление}. Неизменившийся статус — успех/no-op. Неизвестный
    статус блокируется. Недопустимый переход блокируется. Выход из
    superseded/archived требует будущего явного restore-действия; в
    Phase 37D restore API не реализуется. Hard delete не вводится.
    AI не может инициировать lifecycle-переход. Никакого
    автоматического перехода Roadmap/Stage/Task. Коды:
    INVALID_DOCUMENT_STATUS, INVALID_DOCUMENT_TRANSITION,
    DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION,
    DOCUMENT_STATUS_UPDATED, DOCUMENT_STATUS_UNCHANGED.

12. Политика временных меток.

    Uploaded At: устанавливается при первичном создании/загрузке,
    неизменяем после создания. Reviewed At: устанавливается только
    через явное review-решение, не пишется обычным обновлением
    статуса, если review workflow не вызван явно. Reviewed By:
    явный Person ID только через review workflow. Rejection Reason:
    обязателен для решения rejected; очищается только будущим явным
    review-действием, не обычным обновлением. Updated At — только при
    фактической мутации. Created At — неизменяем. Approved At в
    текущей схеме не существует; не добавляется в Phase 37D.

13. Модель review/approval — архитектура одобрена, реализация
    отложена.

    Review — отдельная операция Document Domain; Reviewer — Person ID;
    Role eligibility через Organization может потребоваться в будущем;
    rejected требует Rejection Reason; AI не может выполнять review;
    история review в конечном счёте должна быть append-only. Phase
    37D НЕ добавляет реестр document_reviews, НЕ реализует полный
    approve/reject Telegram UX; Reviewed At/Reviewed By/Rejection
    Reason сохраняются как reserved операционные поля; lifecycle
    foundation может структурно поддерживать статусы, но user-facing
    review-команды остаются отложенными, если Phase 37E явно не
    расширена после доказательств из Foundation. Document Review
    history entity одобрена концептуально, отложена до отдельной
    будущей фазы, не требуется для закрытия owner ship persistence.

14. Политика связей.

    Business ID обязателен. Опциональные единичные ссылки: Client ID,
    Object ID, Roadmap ID, Stage ID, Document Template ID. Service ID
    отсутствует в document_registry и не добавляется в Phase 37D — может
    выводиться через Roadmap/template-контекст при необходимости. Task
    ID отсутствует и отложен. Каждая указанная ссылка должна
    существовать; ссылки должны принадлежать тому же Business там, где
    применимо; Stage подразумевает Roadmap; Roadmap подразумевает
    Object/Client там, где канонические данные их предоставляют;
    указанные ID должны быть взаимно согласованы; более специфичная
    связь может вывести отсутствующую более широкую связь; противоречие
    блокирует; никакого автоматического исправления; никаких
    many-to-many связей в foundation; обычное admin-обновление не может
    релинковать сущности; будущий relink должен быть явным. Коды:
    DOCUMENT_ENTITY_RELATION_MISMATCH,
    DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION.

15. Семантика требуемых документов.

    Document Requirement остаётся derived read model; реестра
    требований нет; канонический источник требований — связи Document
    Template↔Stage/knowledge relation; канонический ключ
    удовлетворения — точный Document Template ID; угадывание по
    filename/title/type запрещено; никакого fuzzy matching; никакого
    первого выбора. Требование удовлетворяется только Document, чей
    операционный статус — один из uploaded/under_review/approved.
    Rejected не удовлетворяет. Archived не удовлетворяет. Superseded
    не удовлетворяет, если существует более новая активная версия;
    иначе остаётся только историческим. Если существует несколько
    активных подходящих Document — сообщаются все совпадающие ID;
    требование может быть помечено удовлетворённым; дополнительно
    выдаётся duplicate/configuration warning; произвольный выбор
    одного никогда не выполняется.

16. Канонический алгоритм missing-document.

    document_requirements_query.evaluate_scope() утверждается
    единственным каноническим evaluator требований/missing-document;
    владеет read-only оценкой для Stage/Roadmap/Object и любого
    поддерживаемого текущего scope.
    organization_manager.compute_stage_document_status() (в
    document_registry_manager.py) признаётся legacy; Phase 37D должна
    либо удалить его, если это безопасно, либо превратить в тонкий
    адаптер поверх evaluate_scope(); /docs4stage, /missingdocs и
    /docsrequired должны в конечном счёте использовать один и тот же
    канонический алгоритм; никаких записей; детерминированная
    структура результата; никакого fuzzy matching; никакого
    произвольного первого выбора.

17. Политика валидации загрузки.

    Foundation допускает хранение файлов, которые AI не может
    анализировать — Document не отклоняется только потому, что AI не
    может его проанализировать; чётко различаются "разрешено для
    хранения" и "поддерживается для AI-анализа" (существующий RTF —
    legacy пример именно такого случая). Одобрены: явный максимальный
    размер (меньшее из настроенного системного лимита и
    предоставленного Telegram размера); лимит длины filename;
    санитизация filename для безопасного отображения/хранения; пустое
    имя файла отклоняется; управляющие символы/path separators
    отклоняются; опасные исполняемые/бинарные типы блокируются;
    никакого логирования сырого содержимого файла; обработка
    password-protected/encrypted документов откладывается, если
    детектирование ещё не доступно. Phase 37D должна сначала
    инвентаризировать текущие принимаемые MIME-типы, прежде чем
    устанавливать лимиты, которые могли бы сломать текущее поведение.
    Коды: UNSUPPORTED_DOCUMENT_STORAGE_TYPE,
    DOCUMENT_ANALYSIS_UNSUPPORTED, DOCUMENT_TOO_LARGE,
    INVALID_DOCUMENT_FILENAME, DOCUMENT_FILE_METADATA_INVALID.

18. Граница AI-анализа.

    Существующая архитектура ратифицируется без переписывания.
    document_intelligence.py остаётся владельцем document_content;
    Document может существовать без анализа; анализ опционален и имеет
    собственный lifecycle; анализ не мутирует операционный статус
    Document; AI-suggestions никогда не approve/reject Document; анализ
    требует валидный Document ID; анализ должен быть
    идемпотентным/retry-aware; force re-analysis может перезаписать
    текущую derived-строку в foundation; никакого append-only
    analysis-history реестра в Phase 37D; сырой полный извлечённый
    текст не хранится неограниченно; bounded preview/summary/error
    поведение остаётся обязательным. document_intelligence.py не
    переписывается, кроме минимального boundary-адаптера или
    result-code wrapper при необходимости.

19. Политика persistence Document Content.

    Одна текущая derived-строка на Document ID. Foundation-поведение:
    создать или обновить единственную текущую строку анализа; никаких
    дублирующих активных content-строк; content hash может подавлять
    ненужный повторный анализ; overwrite-in-place принимается для
    derived-данных; append-only analysis history откладывается;
    Document Content не становится операционной audit-историей;
    политика retention/удаления откладывается.

20. Политика admin-обновления.

    Обычные редактируемые поля: Document Name, Notes. Поля, редактируемые
    только через выделенные операции: Status (через transition API),
    review-поля (через review API), Drive references (через
    create/new-version/repair операцию), relation-поля (через будущий
    relink API). Неизменяемые/блокируемые для обычного обновления:
    Document ID, Business ID, Created At, Document Family ID, Version,
    Uploaded At, Uploaded By, Drive File ID, Drive File URL, File Name,
    Mime Type, relation-поля, Status, review-поля. Коды:
    DOCUMENT_ADMIN_FIELDS_UPDATED, DOCUMENT_ADMIN_FIELDS_UNCHANGED,
    INVALID_DOCUMENT_ADMIN_FIELD, DOCUMENT_IMMUTABLE_FIELD_CONFLICT,
    DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION.

21. Структурированный result-контракт.

    Стабильные поля: ok, code, error, document_id, document_family_id,
    version, business_id, drive_file_id, drive_file_url,
    document_template_id, client_id, object_id, roadmap_id, stage_id,
    previous_status, requested_status, final_status, created, reused,
    changed, uploaded, compensation_attempted, compensation_succeeded,
    analysis_status, warnings, conflicting_document_ids, retry_safe.
    Коды по семействам: Entity/relation — DOCUMENT_NOT_FOUND,
    BUSINESS_NOT_FOUND, CLIENT_NOT_FOUND, OBJECT_NOT_FOUND,
    ROADMAP_NOT_FOUND, STAGE_NOT_FOUND, DOCUMENT_TEMPLATE_NOT_FOUND,
    DOCUMENT_ENTITY_RELATION_MISMATCH. Creation/upload —
    DOCUMENT_REGISTERED, DOCUMENT_UPLOADED, DOCUMENT_REUSED,
    MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES,
    DOCUMENT_RELATION_CONFLICT_ON_REUSE, DRIVE_UPLOAD_FAILED,
    DRIVE_UPLOAD_COMPENSATED, DOCUMENT_PERSISTENCE_FAILED,
    DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING,
    DOCUMENT_POST_WRITE_VERIFICATION_FAILED,
    UNSUPPORTED_DOCUMENT_STORAGE_TYPE, DOCUMENT_TOO_LARGE,
    INVALID_DOCUMENT_FILENAME, DOCUMENT_FILE_METADATA_INVALID. Admin —
    DOCUMENT_ADMIN_FIELDS_UPDATED, DOCUMENT_ADMIN_FIELDS_UNCHANGED,
    INVALID_DOCUMENT_ADMIN_FIELD, DOCUMENT_IMMUTABLE_FIELD_CONFLICT,
    DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION. Status —
    INVALID_DOCUMENT_STATUS, INVALID_DOCUMENT_TRANSITION,
    DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION, DOCUMENT_STATUS_UPDATED,
    DOCUMENT_STATUS_UNCHANGED. Analysis — DOCUMENT_ANALYSIS_NOT_FOUND,
    DOCUMENT_ANALYSIS_STARTED, DOCUMENT_ANALYSIS_REUSED,
    DOCUMENT_ANALYSIS_COMPLETED, DOCUMENT_ANALYSIS_FAILED,
    DOCUMENT_ANALYSIS_UNSUPPORTED, DOCUMENT_CONTENT_NOT_FOUND.
    Requirements — DOCUMENT_REQUIREMENTS_EVALUATED,
    DOCUMENT_REQUIREMENT_SATISFIED, DOCUMENT_REQUIREMENT_MISSING,
    MULTIPLE_DOCUMENT_REQUIREMENT_MATCHES. Ни один код не пересекается
    по имени с существующими Object/Client/Service/Roadmap/Stage/
    Organization/Task кодами.

22. Privacy и logging.

    Разрешено логировать: code, Document ID, Document Family ID,
    Business ID, relation ID, Drive File ID там, где это безопасно,
    status, MIME type, file size, changed/reused-флаги, статус
    компенсации, количество/ID конфликтов. Запрещено: сырое тело
    документа, извлечённый текст, AI summary там, где он
    чувствителен, Document Name там, где не необходимо, filename там,
    где он может раскрыть личные данные, номер паспорта, ИИН, телефон,
    адрес, полное Telegram-сообщение, credentials, токены, сырой Drive
    URL с access-параметрами, сырой текст исключения в
    пользовательских сообщениях. Сырое исключение НЕ разрешено
    показывать пользователю ни при каких обстоятельствах — только
    безопасный generic fallback; bounded AI-логи остаются обязательными;
    guard-тесты на чувствительные значения обязательны.

23. Namespace команд.

    Сохраняются все 8 существующих команд: /registerdoc, /doc,
    /docs4stage, /uploaddoc, /analyzedoc, /docanalysis, /missingdocs,
    /docsrequired — коллизий нет. /updatedoc для admin-полей и статуса
    одобряется к добавлению в Phase 37E только если Foundation
    поддерживает это без проблем. НЕ одобряются сейчас:
    review/approve/reject команды, relink, new version, list by Task,
    delete, restore, AI fuzzy mutation.

24. Требование миграции caller'ов.

    Все 8 существующих команд должны в конечном счёте мигрировать на
    канонические границы. Write-команды (/registerdoc, /uploaddoc)
    должны вызывать business_builder orchestration — никаких прямых
    записей document_registry, никакой caller-side генерации ID,
    никакой caller-side relation policy. Read-команды: /doc использует
    document_manager read API; /docs4stage, /missingdocs, /docsrequired
    используют канонический requirement evaluation;
    /analyzedoc использует orchestration/result adapter без передачи
    AI контроля над Document lifecycle; /docanalysis остаётся
    read-only. Telegram владеет только парсингом, confirmation state,
    безопасным UX и безопасным логированием.

25. Test isolation.

    Блокирующее предусловие Phase 37D: до запуска любого Document-теста
    в Phase 37D — регистрация всех существующих 4 Document test-файлов
    в hard socket-block; регистрация каждого нового Document test-файла
    до написания/запуска его логики; проверка отсутствия
    Sheets/Drive/Telegram/Railway/HTTP/socket доступа; mock-completeness
    guard; architecture guards; privacy/logging guards; no-direct-write-
    from-Telegram guard; PRS-003 precedent сохраняется обязывающим.
    Phase 37D должна немедленно остановиться, если существующие
    Document-тесты не проходят под hard socket-block.

26. Production migration.

    PRODUCTION_SCHEMA_MIGRATION_REQUIRED = NO.
    PRODUCTION_DOCUMENT_ROW_REWRITE_REQUIRED = NO. Существующие два
    ряда (DREG-001, DREG-002) остаются без изменений, остаются
    валидными, остаются Version 1 в своих существующих family, сохраняют
    пустые Roadmap/Stage/Template ссылки, не получают угаданных
    backfill-значений, не перезагружаются повторно, не переанализируются
    исключительно ради миграции. Foundation-миграция состоит только из
    миграции caller'ов/владения.

27. Отклонённые альтернативы.

    Явно отклонены: Telegram как persistence-владелец; document_
    intelligence как владелец operational Document; knowledge_manager
    владение operational Documents; Drive File ID как идентичность
    Document; dedup по filename/title; fuzzy requirement matching;
    generic первый выбор совпадения; одно статусное поле, смешивающее
    analysis/review/upload; AI approval/rejection; hard delete;
    перезапись старых Document version-строк; создание нового реестра
    версий, когда Family ID + Version уже существуют; создание реестра
    Document Requirement в Foundation; переписывание существующих
    production-рядов; добавление Task ID во время очистки владения;
    превращение полной review-истории в блокирующее требование
    Foundation.

Причина:

Тот же архитектурный принцип, применённый ADR-013…ADR-019 к границам
Business/Client/Object/Service/Roadmap-создания, Stage-transition,
Organization Person↔Role assignment и Task Domain, здесь применяется к
Document Domain — с существенной особенностью: значительная часть
логики (валидация связей, Drive-компенсация, AI-изоляция,
идемпотентность через op_state, bounded-логирование) уже написана
качественно и production-проверена на двух реальных рядах. Решение
здесь сознательно НЕ переписывает то, что уже работает правильно
(document_intelligence.py, resolve_and_validate_links(), Drive
failure-safety), а формализует владение (единственный persistence-
владелец вместо записи из Telegram), устраняет дублирование (два
конкурирующих missing-document алгоритма → один канонический), и
добавляет структурированный result-контракт — тот же паттерн, что
ADR-016/017/018/019 уже применили к аналогичным пробелам в других
доменах.

Статус:

Утверждено для реализации (Phase 37D). Ничего не реализовано в рамках
этого ADR — только архитектурное решение. document_manager.py не
создан. Ни один production-caller не мигрирован, ни один код не
изменён, схема Google Sheets не менялась, существующие два ряда
DOCUMENT_REGISTRY и DOCUMENT_CONTENT не изменены. GTD Core не
затронут.

## ADR-021 — Checklist Domain Architecture Decision (Phase 38B)

Контекст:

Phase 37A выбрала Checklist Domain второй по приоритету после Document
Domain (теперь формально закрыт). Phase 38A (read-only архитектурный
аудит) нашла домен на стадии, структурно аналогичной Document Domain
до ADR-020: существует зрелый, production-проверенный
reference/template-слой (`checklist_registry`, 14 production-рядов,
владелец `knowledge_manager.py`, часть общего Knowledge Core наряду с
SOP/Document Template/FAQ), но НЕ существует никакого operational
instance-слоя — ни одной строки кода, создающей Checklist instance при
старте Roadmap, отслеживающей completion отдельных пунктов, вычисляющей
progress, блокирующей Stage completion или генерирующей Task. Все 14
production-рядов — самодостаточные Templates: `Items`/`Required
Items`/`Optional Items` хранятся как один текстовый blob (through
`;`-разделитель), `Template Stage ID` пуст на всех 14 рядах (реальная
привязка к Template Stage идёт в обратную сторону — через
`roadmap_template_stages."Checklist IDs"`), `Status` = `active`
одинаково у всех, ни один ряд не ссылается ни на один реальный
Roadmap/Stage/Task/Document. При старте Roadmap (`/startroadmap`)
список Checklist ID копируется как текст из `roadmap_template_stages` в
`roadmap_stages` — чистое конфигурационное копирование, без создания
какой-либо исполняемой сущности. Phase 38A.1 закрыла найденный
PRS-003-класса test-isolation пробел (13 файлов зарегистрированы в
hard socket-block) — это блокирующее предусловие Foundation уже
выполнено. Это решение применяет тот же архитектурный принцип, что
ADR-013…ADR-020: формализовать существующий reference-слой без
переписывания того, что уже работает, и спроектировать (но не
реализовать) недостающий operational-слой с той же дисциплиной
(единственный persistence-владелец, единственный orchestration-
владелец, детерминированная идентичность, структурированный
result-контракт, явные lifecycle-границы, никаких скрытых cross-domain
мутаций).

Решения:

1. Канонические границы сущностей.

   Checklist Template — переиспользуемое reference-определение.
   Реестр: `checklist_registry` (без изменений). Идентичность:
   Checklist ID (существующие значения, включая ручные semantic-slug'и
   вроде `CHK-IZH-ALM-LEGALIZATION-DOCS-001`, сохраняются без
   изменений — переименование/миграция не требуется). Владелец
   persistence: `knowledge_manager.py`, без изменений. Каждый
   существующий ряд представляет ОДИН целый Checklist Template, а не
   один пункт. Существующие поля `Items`/`Required Items`/`Optional
   Items` остаются reference/template-текстом; `checklist_registry` НЕ
   становится operational execution-реестром.

   Checklist Template Item — переиспользуемое определение одного
   пункта шаблона. В Foundation НЕ вводится отдельный нормализованный
   реестр Template Item; существующий текст пунктов остаётся внутри
   `checklist_registry`; нормализация в отдельные Template Item-
   идентичности откладывается. Foundation парсит/снимает snapshot
   существующего текста пунктов детерминированно (см. решение 11), без
   переписывания текущих 14 Template-рядов.

   Checklist Instance — канонический operational parent entity.
   Одно исполнение одного Checklist Template. Привязан к одному
   Business; опционально — к одному Roadmap и одному Stage; может
   нести производный Object/Service-контекст. Владеет operational
   lifecycle и агрегированной progress-сводкой. Никогда не заменяет и
   не изменяет Template.

   Checklist Instance Item — канонический исполняемый пункт.
   Принадлежит ровно одному Checklist Instance. Хранит snapshot
   исполняемого текста шаблона (заголовок/описание/порядок/required-
   флаг), независимый item-статус, метаданные завершения. НЕ становится
   Task автоматически; НЕ дублирует Document Requirement matching;
   может позже получить bounded опциональные ссылки на Task/Document/
   SOP (физически включены в Foundation-схему, но без автоматической
   генерации/синхронизации — см. решение 8).

   Completion Event / История — в Foundation НЕ вводится отдельный
   append-only реестр событий завершения; текущий статус и метаданные
   завершения хранятся непосредственно на Instance Item; append-only
   аудит-история — явно отложена.

   Evidence — НЕ каноническая сущность файлового хранения. Будущее
   evidence может ссылаться на Document ID; никакого raw-встраивания
   файлов; никакой Checklist-владеемой Drive-загрузки; Document Domain
   остаётся единственным владельцем Document persistence/lifecycle.

2. Владение существующим Template-слоем.

   `knowledge_manager.py` остаётся единственным persistence-владельцем
   `checklist_registry`, создания/чтения Checklist Template,
   Template-уровня метаданных — без изменений. Существующий
   `/newchecklist` остаётся Template-командой; `/linkknowledge`
   остаётся привязкой knowledge к Template Stage; `/stageknowledge`
   остаётся read-only отображением. Все три — НЕ operational Checklist
   команды. Persistence `checklist_registry` НЕ переносится в
   `checklist_manager.py`.

3. Operational persistence ownership.

   Одобряется будущий модуль `business_core/checklist_manager.py` —
   единственный persistence-владелец operational Checklist-реестров.
   Он владеет: точным чтением Checklist Instance/Instance Item по ID;
   list/filter-чтением; генерацией Instance ID; генерацией Instance
   Item ID; низкоуровневым созданием instance; низкоуровневым созданием
   item; низкоуровневой записью статуса; низкоуровневой записью
   completion-метаданных; проверкой текущего ряда после записи;
   idempotency-поиском. Он НЕ владеет: производной кросс-domain
   relation-логикой; политикой парсинга Template; генерацией Task;
   сопоставлением Document; мутацией Stage; Telegram UX.

4. Operational orchestration ownership.

   Одобряется `business_builder.py` как единственный cross-domain
   orchestration-владелец Checklist. Он владеет: relation-валидацией;
   поиском Template; детерминированным парсингом пунктов Template;
   созданием snapshot Template; instantiation-идемпотентностью;
   созданием Instance + Items; политикой reuse/conflict; оркестрацией
   вычисления progress; оркестрацией item-status transition;
   оркестрацией Checklist-status transition; сборкой структурированного
   result; compensation-поведением, если создание parent прошло, а
   создание items — нет.

   Направление зависимостей:
   `telegram_handlers → business_builder → checklist_manager → sheets`.

   Read-only зависимости разрешены на: `knowledge_manager`,
   `roadmap_manager`, `service_manager`, `object_manager`,
   `task_manager`, `document_manager`, `organization_manager`.
   Обратные зависимости запрещены.

5. Новые operational-реестры (ровно два).

   A. `checklist_instances`: Checklist Instance ID, Business ID,
      Checklist Template ID, Checklist Title Snapshot, Service ID,
      Object ID, Roadmap ID, Stage ID, Status, Total Items, Required
      Items, Completed Items, Required Remaining, Created At, Created
      By, Started At, Completed At, Cancelled At, Updated At, Notes.

   B. `checklist_instance_items`: Checklist Instance Item ID, Checklist
      Instance ID, Checklist Template ID, Source Item Key, Item Order,
      Item Title Snapshot, Item Description Snapshot, Required,
      Status, Blocked Reason, Skip Reason, Task ID, Document ID, SOP
      ID, Completed At, Completed By, Created At, Updated At, Notes.

   Task ID/Document ID/SOP ID на Instance Item физически включаются в
   Foundation-схему как опциональные reference-колонки, но БЕЗ
   автоматической генерации/линковки/синхронизации в Foundation — они
   могут оставаться пустыми и заполняются только через явную будущую
   validated-запись. Никаких generic relation-JSON или comma-
   separated relation-полей не добавляется — только bounded одиночные
   ссылки, как во всех предыдущих доменах.

6. Identity-политика.

   Checklist Template: существующий Checklist ID (включая смешанные
   `CHK-NNN` и semantic-slug форматы) сохраняется без изменений —
   миграция не требуется.

   Checklist Instance: префикс `CLIN-NNN`. Checklist Instance Item:
   префикс `CLII-NNN`. Выбраны вместо более коротких `CLI-*`/`CII-*`,
   потому что `CLI` визуально и мнемонически слишком легко спутать с
   `CLIENT`-related сокращениями, уже используемыми в человеческом
   обсуждении домена (Client ID часто сокращают как "CLI" в заметках),
   а `CII` не несёт очевидной для человека связи с "Checklist
   Instance Item" без дополнительного контекста; `CLIN`/`CLII`
   сохраняют однозначную визуальную связь с "Checklist INstance" /
   "Checklist Instance Item" и не пересекаются ни с одним префиксом,
   уже занятым в `sheets._ID_PREFIXES` (проверено при аудите: CHK, SOP,
   DOC, FAQ, BIZ, PRS, OBJ, RM, STAGE, TSK, TAS, ROLE, DEPT, DREG,
   DFAM и т.д. — коллизий нет). Ровно одна реализация генератора на
   каждый operational ID; caller-side генерация запрещена; генерация
   сканирует существующие валидные значения безопасно; некорректные
   существующие ID игнорируются безопасно, не ломая сканирование;
   ID генерируются только после валидации и проверки reuse; никакой
   identity по title; никакого переиспользования filename/document/
   task-идентичности.

7. Политика парсинга и snapshot Template.

   Детерминированный парсер: разделитель `;` (уже используемый во всех
   14 production-рядов), опционально `\n` как альтернативный
   разделитель, если `;` отсутствует в тексте пункта. Порядок пунктов
   сохраняется по порядку появления в тексте. Пробелы обрезаются;
   пустые токены игнорируются. НЕ используется AI-парсинг; недостающие
   пункты НЕ домысливаются; Template-ряды НЕ переписываются. Каждому
   распарсенному пункту присваивается детерминированный порядковый
   `Source Item Key` (например, индекс появления в исходном тексте,
   1-based) — стабильный до тех пор, пока текст Template не изменится
   (изменение текста Template не переписывает уже существующие Instance
   Item — они уже сняли snapshot).

   Required/Optional классификация: Required Items и Optional Items
   разбираются тем же способом и сопоставляются с распарсенными Items
   ТОЛЬКО через точное текстовое совпадение (после trim) — никакого
   fuzzy-сопоставления. Безопасный default: все распарсенные Items по
   умолчанию `required=true`; точное совпадение в Optional Items
   переопределяет на `required=false`; точное совпадение в Required
   Items оставляет `required=true`; если один и тот же пункт текста
   точно совпадает и с Required Items, и с Optional Items одновременно
   — это противоречивая классификация, и инстанцирование этого
   Template блокируется кодом
   `CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT`. Пустой список
   Items блокирует инстанцирование
   (`CHECKLIST_TEMPLATE_ITEMS_EMPTY`). Обоснование default'а
   "required=true": в текущих production-данных колонки Required
   Items/Optional Items не заполнены ни у одного из 14 рядов — если бы
   default был `required=false`, Checklist мог бы быть отмечен
   завершённым, не выполнив ни одного реального пункта; `required=true`
   по умолчанию — единственный выбор, который не позволяет тихо
   потерять важную работу.

   Instance Item снимает snapshot заголовка/описания/порядка/required-
   флага на момент инстанцирования; последующие правки Template
   никогда не переписывают уже созданные (активные или исторические)
   Instance Items — они уже независимы от Template.

8. Instantiation и idempotency-политика.

   Канонический ключ инстанцирования: Business ID + Checklist Template
   ID + Roadmap ID + Stage ID (пустые Roadmap ID/Stage ID
   нормализуются как явное "не указано", участвуя в ключе как есть, а
   не заменяясь угадыванием). Business ID и Checklist Template ID —
   обязательны; Roadmap ID и Stage ID — опциональны; если указан Stage
   ID, Roadmap ID выводится/валидируется из него (Stage должен
   принадлежать этому Roadmap). Ноль совпадений → создаётся один
   Checklist Instance и все его Items. Одно совместимое совпадение →
   переиспользуется существующий Instance, код
   `CHECKLIST_INSTANCE_REUSED`, дубликат items не создаётся. Несколько
   совпадений → блокируется, код `MULTIPLE_CHECKLIST_INSTANCE_MATCHES`
   (единственный канонический код для этого случая — синонимов не
   вводится), возвращаются все конфликтующие Instance ID, никакого
   first-pick, никаких записей. Никакого dedup по title; никакого
   dedup по тексту пункта; никакого fuzzy-сопоставления Template;
   никакого автоматического duplicate-repair. Явный отдельный
   Idempotency Key НЕ вводится в Foundation — канонический relation-
   tuple достаточен; внешний idempotency-параметр откладывается.

9. Relation-политика.

   Обязательные: Business ID, Checklist Template ID. Опциональные
   одиночные ссылки на уровне Instance: Service ID, Object ID, Roadmap
   ID, Stage ID. Опциональные одиночные ссылки на уровне Item: Task
   ID, Document ID, SOP ID. Каждый указанный ID должен существовать;
   same-Business ownership обеспечивается там, где применимо; Stage
   должен принадлежать Roadmap; Roadmap может выводить Object/Service-
   контекст; противоречия блокируют (`CHECKLIST_ENTITY_RELATION_
   MISMATCH`); никакого автоматического repair; никакого перемещения
   между Business; никакой generic many-to-many связи; relink требует
   будущего явного действия (`CHECKLIST_RELATION_UPDATE_REQUIRES_
   EXPLICIT_ACTION`); Foundation не изменяет ряды закрытых доменов.
   Привязка через Template Stage помогает ВЫБРАТЬ Template, но не
   является operational-идентичностью.

10. Instance lifecycle.

    Вокабуляр: `draft`, `in_progress`, `blocked`, `completed`,
    `cancelled`, `archived`. Отдельный статус `ready` НЕ вводится —
    Instance создаётся сразу валидным и доступным к старту; отдельное
    промежуточное состояние между "создан" и "начат" не несёт сейчас
    отличимой семантики и добавило бы переход без реальной причины.

    Матрица переходов:
    `draft` → `draft`, `in_progress`, `cancelled`, `archived`.
    `in_progress` → `in_progress`, `blocked`, `completed`, `cancelled`,
    `archived`.
    `blocked` → `blocked`, `in_progress`, `cancelled`, `archived`.
    `completed` → `completed`, `archived`.
    `cancelled` → `cancelled`, `archived`.
    `archived` → только `archived`.

    Неизменный переход — успех/no-op. `completed`/`cancelled`/
    `archived` не могут обычно переоткрываться; restore требует
    будущего явного действия (`CHECKLIST_RESTORE_REQUIRES_EXPLICIT_
    ACTION`). Никакой автоматической мутации Stage/Roadmap. Никакой
    статус не выводится исключительно из timestamp'ов.

11. Item lifecycle.

    Вокабуляр: `pending`, `in_progress`, `blocked`, `done`, `skipped`,
    `not_applicable`. `done`/`skipped`/`not_applicable` — терминальные
    для обычного перехода. Матрица: `pending`/`in_progress`/`blocked`
    свободно переходят друг в друга и в любое терминальное состояние;
    терминальные состояния переходят только сами в себя обычным путём.
    Обычное переоткрытие терминального Item не разрешено; explicit
    restore/reopen — отдельное будущее действие
    (`CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION`).
    `blocked` требует `Blocked Reason`
    (`CHECKLIST_ITEM_REASON_REQUIRED` при отсутствии). `skipped` и
    `not_applicable` оба используют единое поле `Skip Reason` в
    Foundation (отдельного `Outcome Reason` не вводится — bounded-
    схема предпочтительнее двух полей с пересекающейся семантикой).
    `done` требует `Completed At` и `Completed By`
    (`CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED` при отсутствии).
    Поскольку append-only история статусов отложена, смена активного
    статуса не сохраняет отдельной истории — только текущее состояние.

12. Completion и progress policy.

    Checklist может перейти в `completed` только если: существует хотя
    бы один Instance Item; каждый required item — `done` либо
    `not_applicable` (с обязательной причиной); ни один required item
    не находится в `pending`/`in_progress`/`blocked`; `skipped` НЕ
    удовлетворяет required item; optional items могут оставаться в
    любом нетерминальном состоянии и не блокируют завершение Checklist.
    `blocked` required item предотвращает завершение
    (`CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET`).

    Item-статус — хранимый (canonical truth). Progress — производится
    каноническим вычислением поверх item-статусов на каждый запрос;
    Checklist-статус — персистентный (задаётся через transition-API,
    которая сама проверяет производную completion-готовность перед
    записью `completed`). Колонки Total Items/Required Items/Completed
    Items/Required Remaining на `checklist_instances` — верифицированный
    persisted-кэш, пересчитываемый при каждой мутации item, но
    каноническая истина остаётся в статусах Instance Items, а не в этом
    кэше. Ручной override completion в Foundation НЕ разрешён —
    переход в `completed` всегда проверяется автоматически.

    Total Items = все Instance Items. Required Items = count
    `required=true`. Completed Items = count `done` + `not_applicable`.
    Required Remaining = required items, не находящиеся в `done`/
    `not_applicable`. Blocked Required — производный warning-счётчик
    (может не персиститься отдельной колонкой). `skipped` required
    item никогда не считается completed. Никакого caller-side
    вычисления progress — только orchestration-уровень.

13. Parent/item consistency и compensation.

    Каждый Instance Item принадлежит ровно одному Checklist Instance;
    Business-контекст выводится из parent; orphan Item не создаётся;
    Item не может быть перемещён в другой Instance; удаление parent
    запрещено; hard delete в Foundation отсутствует; создание parent
    не может быть отрапортовано как успех, если не все распарсенные
    Items персистированы и верифицированы.

    Compensation-политика: валидация и парсинг выполняются полностью
    ДО любой записи; parent создаётся только после того, как полный
    payload items готов; parent и items добавляются; если запись items
    не удаётся после успешного создания parent — успех НЕ заявляется,
    возвращается явный код `CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE` с
    перечислением уже созданных ID; автоматическое удаление уже
    созданных operational-рядов ЗАПРЕЩЕНО, поскольку в репозитории нет
    безопасного канонического row-delete примитива для Business Core
    реестров; повторная попытка должна обнаруживать и переиспользовать/
    исправлять только через явную orchestration-логику, никогда не
    создавая тихий дубликат.

14. Task boundary.

    Checklist Instance Item и Task — раздельные канонические сущности.
    Task ID — только опциональная ссылка. Никакой автоматической
    генерации Task в Foundation; никакого автоматического создания
    assignment; никакой двусторонней синхронизации статуса. Завершение
    Task не завершает автоматически Checklist Item; завершение
    Checklist Item не завершает автоматически Task. Любая генерация/
    синхронизация требует отдельного будущего ADR. Checklist Domain
    может читать точное ID-состояние Task, но не может мутировать Task
    через скрытые side-эффекты.

15. Stage/Roadmap boundary.

    Checklist Instance может ссылаться на один Roadmap и один Stage;
    Stage ID может выводить Roadmap ID. Stage/Checklist lifecycle
    остаются независимыми: Checklist completion не завершает Stage;
    Stage completion не завершает Checklist; Checklist не блокирует
    Stage transitions в Foundation. Read-only предупреждения/отчётность
    могут быть добавлены позже. Автоматическое инстанцирование
    Checklist при старте Roadmap НЕ входит в Phase 38C: Foundation
    предоставляет только явный канонический instantiation API;
    интеграция с `/startroadmap` откладывается в отдельную будущую
    integration-фазу — это защищает уже закрытое Roadmap/Stage-
    поведение от скрытых побочных эффектов.

16. Document boundary.

    Checklist Domain не дублирует Document Requirement логику;
    удовлетворение Document Template остаётся во владении
    `document_requirements_query.evaluate_scope()`. Document ID может
    быть опциональной evidence/ссылкой на Instance Item; привязка
    Document НЕ отмечает Item выполненным автоматически в Foundation;
    завершение Item не меняет статус Document. Checklist может позже
    ЧИТАТЬ канонический результат Document requirement evaluation, но
    не пишет в Document ни при каких обстоятельствах; никакой Drive-
    загрузки, владеемой Checklist.

17. SOP boundary.

    SOP остаётся Knowledge reference-подсистемой; persistence остаётся
    в `knowledge_manager.py`. Checklist Instance Item может опционально
    ссылаться на один SOP ID; ссылка — чисто инструктивная. Никакого
    SOP completion; никакой мутации SOP-записей со стороны Checklist.

18. Template Stage и текущие скопированные Checklist ID.

    Текущее поведение явно подтверждается неизменным:
    `roadmap_template_stages` хранит Checklist IDs;
    `/startroadmap` копирует эту строку в `roadmap_stages` как есть.
    Это конфигурационное/reference-распространение, а не создание
    operational Checklist Instance. Текущее поведение остаётся
    неизменным в Phase 38C. Операционное инстанцирование из этих ID —
    отдельная будущая явная интеграция. Checklist Domain не должен
    трактовать скопированные Stage Checklist IDs как исполняемые
    записи.

19. Template lifecycle.

    Template lifecycle (`active`/`inactive`/`archived`) остаётся
    отдельным от operational lifecycle и во владении
    `knowledge_manager.py`. Operational Instance snapshot остаётся
    стабильным, даже если Template позже станет `inactive`/`archived`.
    `inactive`/`archived` Template не может создать новый Instance без
    будущего явного override; уже существующие Instances остаются
    валидными. Template-статус не мутирует Instance-статус. API
    переходов Template НЕ реализуется в Phase 38C.

20. Result-контракт.

    Стабильный структурированный результат для каждой operational
    Checklist-функции: ok, code, error, checklist_instance_id,
    checklist_template_id, checklist_instance_item_id, business_id,
    service_id, object_id, roadmap_id, stage_id, task_id, document_id,
    sop_id, previous_status, requested_status, final_status, created,
    reused, changed, completed, total_items, required_items,
    completed_items, required_remaining, blocked_required,
    conflicting_ids, created_item_ids, warnings, retry_safe. Никогда
    не содержит сырой exception-объект, сырую строку Sheets или сырой
    dict, показываемый пользователю в Telegram.

21. Result-код вокабуляр (единственные канонические имена, без
    синонимов):

    Template: CHECKLIST_TEMPLATE_NOT_FOUND,
    CHECKLIST_TEMPLATE_INACTIVE, CHECKLIST_TEMPLATE_ARCHIVED,
    CHECKLIST_TEMPLATE_ITEMS_EMPTY,
    CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT,
    CHECKLIST_TEMPLATE_PARSE_FAILED.

    Отношения: BUSINESS_NOT_FOUND, SERVICE_NOT_FOUND, OBJECT_NOT_FOUND,
    ROADMAP_NOT_FOUND, STAGE_NOT_FOUND, TASK_NOT_FOUND,
    DOCUMENT_NOT_FOUND, SOP_NOT_FOUND,
    CHECKLIST_ENTITY_RELATION_MISMATCH,
    CHECKLIST_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION.

    Инстанцирование: CHECKLIST_INSTANCE_CREATED,
    CHECKLIST_INSTANCE_REUSED, MULTIPLE_CHECKLIST_INSTANCE_MATCHES
    (единственный канонический код конфликта совпадений —
    MULTIPLE_CHECKLIST_IDEMPOTENCY_MATCHES не вводится как отдельный
    синоним), CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE,
    CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED.

    Чтение instance: CHECKLIST_INSTANCE_NOT_FOUND,
    CHECKLIST_INSTANCE_ITEM_NOT_FOUND.

    Статус Instance: CHECKLIST_STATUS_UPDATED,
    CHECKLIST_STATUS_UNCHANGED, INVALID_CHECKLIST_STATUS,
    INVALID_CHECKLIST_STATUS_TRANSITION,
    CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET,
    CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION.

    Статус Item: CHECKLIST_ITEM_STATUS_UPDATED,
    CHECKLIST_ITEM_STATUS_UNCHANGED, INVALID_CHECKLIST_ITEM_STATUS,
    INVALID_CHECKLIST_ITEM_STATUS_TRANSITION,
    CHECKLIST_ITEM_REASON_REQUIRED,
    CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED,
    CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION.

    Admin/update: CHECKLIST_ADMIN_FIELDS_UPDATED,
    CHECKLIST_ADMIN_FIELDS_UNCHANGED, INVALID_CHECKLIST_ADMIN_FIELD,
    CHECKLIST_IMMUTABLE_FIELD_CONFLICT,
    CHECKLIST_ITEM_IMMUTABLE_FIELD_CONFLICT.

    Persistence: CHECKLIST_PERSISTENCE_FAILED,
    CHECKLIST_ITEM_PERSISTENCE_FAILED.

22. Immutable/mutable поля.

    Checklist Instance неизменны: Checklist Instance ID, Business ID,
    Checklist Template ID, Created At. Условно неизменны после
    создания (обычный update их не трогает, relink требует будущего
    явного действия): Roadmap ID, Stage ID, Service ID, Object ID,
    Title Snapshot. Обычно изменяемы: Notes; Status — только через
    transition API.

    Checklist Instance Item неизменны: Checklist Instance Item ID,
    Checklist Instance ID, Checklist Template ID, Source Item Key,
    Item Order, Item Title Snapshot, Item Description Snapshot,
    Required, Created At. Обычно изменяемы через bounded API: Status;
    Blocked Reason; Skip Reason; Notes; Task ID/Document ID/SOP ID —
    только через будущее явное link-действие; Completed At/Completed
    By — управляются исключительно transition-логикой, не generic
    update. Никаких generic relation-обновлений.

23. Timestamp-политика.

    Instance: Created At — устанавливается один раз; Updated At —
    только при реальной мутации; Started At — устанавливается при
    первом переходе в `in_progress`, не перезаписывается повторно;
    Completed At — устанавливается при успешном переходе в `completed`,
    неизменен через generic update; Cancelled At — устанавливается при
    переходе в `cancelled`.

    Item: Created At — один раз; Updated At — только при реальной
    мутации; Completed At/Completed By — устанавливаются для `done`,
    не доступны для записи через generic update.

24. Restore/reopen policy.

    Никакого обычного переоткрытия завершённого/отменённого/
    архивированного Checklist Instance. Никакого обычного
    переоткрытия done/skipped/not_applicable Item. Restore/reopen —
    НЕ реализуется в Foundation (`CHECKLIST_RESTORE_IMPLEMENTED = NO`,
    `CHECKLIST_ITEM_REOPEN_IMPLEMENTED = NO`), но защита ОБЯЗАНА
    существовать (`CHECKLIST_RESTORE_PROTECTION_REQUIRED = YES`,
    `CHECKLIST_ITEM_REOPEN_PROTECTION_REQUIRED = YES`) через явные
    result-коды. Никакого скрытого admin-обхода.

25. Delete/archive policy.

    Hard delete отсутствует в Foundation. `archived` — терминален.
    `cancelled` — operational-терминален, но может позже архивироваться
    через ту же transition matrix. Item-ряды никогда не удаляются
    отдельно. Template-записи не удаляются operational Checklist-кодом.
    Retention-политика отложена.

26. Privacy и логирование.

    Разрешено логировать: команда/действие, result-код, Checklist
    Instance ID, Checklist Template ID, Item ID, Business/Service/
    Object/Roadmap/Stage ID, Task/Document/SOP ID (если есть), статус,
    progress-счётчики, флаги changed/reused, конфликтующие ID/их
    количество, retry-safe флаг. Запрещено логировать: Item Title
    Snapshot, Item Description Snapshot, Notes, Blocked Reason, Skip
    Reason, содержимое Document, персональные данные, полное Telegram-
    сообщение, credentials, сырые exceptions, сырые Sheets-ряды.
    Telegram обязан показывать только безопасные bounded-сообщения.

27. Command scope для будущего Caller UX (Phase 38D).

    Сохраняются без изменений: /newchecklist, /linkknowledge,
    /stageknowledge — Template/reference-команды. Одобряются к
    будущему рассмотрению (без коллизий, проверено при аудите):
    /startchecklist (только instantiation через business_builder),
    /checklists (read-only отфильтрованный список), /checklist (точный
    Checklist Instance ID), /updatecheckitem (только item-status
    transition, без admin/relink/task/document автоматизации),
    /updatechecklist (status transition ИЛИ admin-обновление Notes,
    взаимоисключающе — тот же паттерн, что /updatetask и /updatedoc).
    Команды НЕ реализуются в Phase 38B.

28. Требования к тестам Phase 38C.

    Обязательны до и во время Foundation: все Checklist-тесты
    зарегистрированы в hard socket-block (уже выполнено Phase 38A.1);
    mock-completeness guard остаётся обязывающим; никакого живого
    доступа к Sheets/Drive/Telegram/HTTP; тесты генерации ID; тесты
    парсера; тесты точной required/optional классификации; тесты
    relation-валидации; тесты идемпотентности zero/one/multiple; тесты
    отсутствия title-based dedup; тесты partial-persistence parent/
    item; тесты вычисления progress; тесты Instance lifecycle; тесты
    Item lifecycle; тесты обязательности reason; тесты защиты
    терминального reopen; guard-тесты не-мутации Task/Document/Stage;
    guard-тесты владения persistence; guard-тесты владения
    orchestration; guard-тесты отсутствия caller-side генерации ID;
    privacy/logging guards; проверки production-снимка.

29. Production migration.

    Не переписываются существующие 14 рядов `checklist_registry`;
    Checklist ID не меняются; существующие Templates не разбиваются на
    нормализованные Template Item-ряды; колонка Template Stage ID не
    backfill'ится; скопированные `roadmap_stages` Checklist IDs не
    конвертируются в operational-ряды. Новые operational-реестры
    добавляются РЯДОМ с текущими reference-данными. Production
    migration — только после отдельного явного одобрения, если
    когда-либо понадобится.

30. Явно исключено из Foundation (Phase 38C):

    нормализованный реестр Checklist Template Item; AI-парсинг
    шаблонов; автоматическое создание Checklist при старте Roadmap;
    автоматическое создание Task; двусторонняя синхронизация Task;
    автоматическое завершение Document; дублирование Document
    Requirement логики; блокировка Stage; авто-завершение Stage;
    авто-завершение Checklist из Stage; append-only история статусов;
    напоминания; WABA/SendPulse/Binotel-интеграция; permissions/RBAC;
    workflow назначений; комментарии/threading; вложения помимо
    Document-ссылок; generic many-to-many связи; hard delete;
    реализация restore/reopen; production migration/backfill.

31. Границы Phase 38C (bounded Foundation scope).

    Разрешено: создать `checklist_manager.py`; добавить схему
    `checklist_instances`; добавить схему `checklist_instance_items`;
    добавить канонические ID-генераторы; добавить точные reads/list-
    helpers; добавить детерминированный Template-парсер; добавить
    business_builder instantiation orchestration; добавить relation-
    валидацию; добавить idempotent create/reuse/conflict-поведение;
    добавить orchestration переходов item и Instance; добавить
    вычисление progress; добавить структурированный result-контракт;
    добавить architecture/test guards. Запрещено: изменять Telegram
    caller UX; деплоить; автоматически интегрировать в
    `/startroadmap`; генерировать Task; мутировать Document; мутировать
    Stage/Roadmap lifecycle; мигрировать production Template-ряды.

32. Отклонённые альтернативы.

    A. Считать текущий `checklist_registry` operational execution-
       реестром — отклонено: нет instance-идентичности, нет item-
       идентичности, нет completion-полей, нет Roadmap/Stage execution-
       связи.
    B. Хранить каждое operational-исполнение как закодированный текст
       в одном существующем ряду — отклонено: нет детерминированной
       item-идентичности, нет безопасного progress, нет истории, нет
       bounded-переходов.
    C. Сделать Checklist Item идентичным Task — отклонено: Checklist-
       семантика легче; неназначенные/non-task items валидны;
       автоматическая генерация Task отложена; Task Domain владеет
       Task lifecycle.
    D. Дублировать Document Requirement логику внутри Checklist —
       отклонено: ADR-020 уже определяет канонический evaluator;
       дублирующая истина расходилась бы со временем.
    E. Автоматически мутировать статус Stage из Checklist — отклонено:
       Stage Domain владеет Stage lifecycle; скрытый каскад запрещён.
    F. Переписать существующие 14 Templates в нормализованные Item-
       ряды до Foundation — отклонено: ненужная production migration;
       текущие ряды можно детерминированно снять как snapshot без
       переписывания.

Причина:

Тот же архитектурный принцип, применённый ADR-013…ADR-020 к границам
Business/Client/Object/Service/Roadmap/Stage/Organization/Task/Document,
здесь применяется к Checklist Domain — с той же особенностью, что и в
ADR-020: значительная часть reference-слоя (Template-создание,
Knowledge-привязка к Template Stage, копирование ID при старте
Roadmap) уже написана и production-проверена, и НЕ переписывается;
решение формализует владение Template-слоем (единственный владелец
`knowledge_manager.py`, без изменений) и проектирует недостающий
operational-слой с нуля, применяя уже проверенные паттерны из ADR-019
(idempotency zero/one/multiple, parent+child registry shape, transition
matrix с терминальными состояниями и явной restore-защитой) и ADR-020
(snapshot-not-live-reference, structured result contract, единственный
canonical evaluator вместо дублирования, compensation без claim
ложного успеха). Явно откладывается всё, что создало бы скрытые
cross-domain побочные эффекты (Task-генерация, Document-мутация,
Stage-каскад) или потребовало бы production migration прежде, чем
Foundation вообще может начаться.

Статус:

Утверждено для реализации (Phase 38C) с bounded scope, определённым в
решении 31. Ничего не реализовано в рамках этого ADR — только
архитектурное решение. `checklist_manager.py` не создан; `checklist_
instances`/`checklist_instance_items` не существуют; ни один
production-caller не мигрирован; ни один код не изменён; схема Google
Sheets не менялась; существующие 14 рядов `checklist_registry` не
изменены; `roadmap_template_stages`/`roadmap_stages`/`stage_entity_
relations` не изменены. GTD Core не затронут. Ни один закрытый домен
(Object/Client/Service/Roadmap/Stage/Organization/Task/Document) не
переоткрыт.

## ADR-022 — Payment/Milestone Domain Architecture Decision (Phase 39B)

### 0. Контекст

Phase 39A (Next Domain Selection Audit) и Phase 39A.1 (Payment Domain Scope
and Financial-Integrity Clarification) установили: единственный оставшийся
домен с реальным code footprint — Payment/Milestone. Никакого
`milestone_registry` не существует; `COMMERCIAL_MILESTONES_MAP` в
`roadmap_manager.py` — это hardcoded Python dict (одна запись, шаблон
`RMT-IZH-ALM-STANDARD-002`, 3 фиксированные milestone-суммы), не Sheets
registry. `/milestones` — read-only команда без мутаций. Ни operational, ни
Template Sheets-слоя не существует ни в каком виде — это более "чистый"
greenfield, чем был Checklist Domain перед своим Foundation (у Checklist уже
был зрелый производственный Template-слой; здесь нет и его).

Ключевая находка Phase 39A.1, формально утверждаемая здесь: expected money
(что должны) и actual money (что реально получено) — это два разных факта,
которые никогда не должны жить в одной операционной строке. Одна строка с
полями "Expected Amount"/"Paid Amount" уничтожает возможность аудита истории
платежей (перезапись при исправлении, невозможность различить два частичных
платежа, невозможность отличить "ожидаем" от "подтверждено получено").

Это ADR утверждает архитектуру Payment/Milestone Domain Foundation
(Phase 39C) — Template + Obligation + Transaction, без Allocation-реестра,
без миграции, без Telegram-команд, без деплоя.

### 1. Канонические концепции

**A. Commercial Milestone Template** — переиспользуемое определение
коммерческого графика платежей. Reference/config-слой. Привязан к Roadmap
Template и/или Service. Никогда не хранит фактическую историю платежей и
не хранит live paid-статус.

**B. Payment Obligation** — каноническая expected-money сущность. Одна
сумма к оплате, одна явная валюта, один Business, один payer/Client,
опциональные Object/Service/Roadmap/Stage/Template-ссылки, due date,
операционный receivable-lifecycle.

**C. Payment Transaction** — каноническое actual-money событие. Одна запись
о фактическом платеже, одна явная валюта, ровно один Payment Obligation (в
Foundation), дата платежа, метод, внешняя транзакционная ссылка,
опциональный evidence Document ID, immutable после подтверждения.

**D. Payment Allocation** — НЕ Foundation-сущность, отложена. Foundation
поддерживает: один Transaction → один Obligation; один Obligation → много
Transactions. Оплата нескольких Obligation одним платежом фиксируется как
отдельные Transaction-записи, каждая — на свой Obligation.

```
PAYMENT_OBLIGATION_IS_EXPECTED_MONEY_ENTITY = YES
PAYMENT_TRANSACTION_IS_ACTUAL_MONEY_ENTITY = YES
EXPECTED_AND_ACTUAL_MONEY_ARE_SEPARATE = YES
PAYMENT_ALLOCATION_REGISTRY_REQUIRED_IN_FOUNDATION = NO
```

### 2. Registry design

Три новых registry, все — будущая работа Phase 39C, ничего не создаётся
этим ADR.

**A. `commercial_milestone_templates`**

```
Commercial Milestone Template ID
Roadmap Template ID
Service ID
Title
Description
Sequence
Trigger Description
Calculation Type
Fixed Amount
Percentage
Currency
Status
Created At
Created By
Updated At
Notes
```

**B. `payment_obligations`**

```
Payment Obligation ID
Business ID
Client ID
Object ID
Service ID
Roadmap ID
Stage ID
Commercial Milestone Template ID
Caller Idempotency Key
Title Snapshot
Description Snapshot
Obligation Amount
Currency
Due Date
Status
Paid Amount
Remaining Amount
Created At
Created By
Issued At
Paid At
Cancelled At
Updated At
Notes
```

Единственное отклонение от предложенного в задании набора полей: добавлено
`Caller Idempotency Key` (см. решение 19 ниже) — без него нет безопасного
основного idempotency-ключа для Obligation, создаваемых не строго из
Template/Roadmap/Stage triple.

**C. `payment_transactions`**

```
Payment Transaction ID
Business ID
Payment Obligation ID
Client ID
Amount
Currency
Payment Date
Payment Method
External Transaction ID
Caller Idempotency Key
Evidence Document ID
Status
Reversal Reason
Confirmed At
Confirmed By
Reversed At
Reversed By
Created At
Created By
Updated At
Notes
```

Единственное отклонение от предложенного набора: поле `Reversal Of
Transaction ID` из задания — не включено. Причина: решение 16 (модель
реверса) утверждает status-based reversal НА ТОЙ ЖЕ строке (не отдельная
reversal-транзакция), поэтому поле-ссылка "reversal of" не имеет объекта
для ссылки в Foundation — второй транзакционной строки не создаётся.
Поле сознательно не резервируется как "для будущей совместимости", чтобы
не вводить в схему поле без единого производителя/потребителя в Foundation
(тот же принцип "не формализовать код без runtime-вызова", что закрыл
Phase 37F находку по Document Domain).

Требуемые решения:

```
- payment_allocations в Foundation не создаётся;
- invoice-реестр в Foundation не создаётся;
- expense/revenue/ledger-реестры не создаются;
- generic JSON relation-поля не используются;
- comma-separated relation-поля не используются;
- скрытая expected/actual гибридная строка запрещена.
```

### 3. Persistence ownership

Выбрано: **один `payment_manager.py`** — единственный persistence owner
для всех трёх registry (`commercial_milestone_templates`,
`payment_obligations`, `payment_transactions`).

Обоснование против разделения на `payment_template_manager.py` +
отдельный operational manager: в первой версии домена искусственное
разделение на два файла-владельца создаёт две параллельные, но пустые в
день 1, поверхности с почти нулевой независимой сложностью каждая (тот же
паттерн, что уже использовался — `document_manager.py`,
`checklist_manager.py`, `task_manager.py` — каждый владеет всеми своими
registry одним файлом). Разделение может быть сделано позже, если Template
persistence разрастётся достаточно, чтобы оправдать отдельный модуль —
не предвосхищается здесь.

`payment_manager.py` владеет: точечные reads, list/filter reads, ID
generation (PMT/POB/PTXN), низкоуровневое create/update/status persistence,
idempotency-lookup примитивы, verification подтверждённой Transaction-
строки после записи, персистентность derived-balance кэша.

`payment_manager.py` НЕ владеет: cross-domain relation-валидацию, деловую
policy-оркестрацию (overpayment/lifecycle/idempotency-decision), Telegram
UX, автоматическую мутацию Roadmap/Stage/Document.

### 4. Orchestration ownership

`business_builder.py` — единственный cross-domain owner Payment-
оркестрации. Владеет: Template-валидацию, amount/currency normalization,
relation-валидацию, создание Obligation, создание/подтверждение/реверс
Transaction, overpayment-предотвращение, balance-calculation,
status-synchronization, idempotency zero/one/multiple handling,
structured result assembly.

Направление зависимостей (без реверса, как во всех закрытых доменах):

```
telegram_handlers
  → business_builder
    → payment_manager
      → sheets
```

```
PAYMENT_MANAGER_IS_APPROVED_PERSISTENCE_OWNER = YES
BUSINESS_BUILDER_IS_APPROVED_PAYMENT_ORCHESTRATION_OWNER = YES
```

### 5. Identity policy

```
Commercial Milestone Template: PMT-NNN
Payment Obligation:            POB-NNN
Payment Transaction:           PTXN-NNN
```

Проверка коллизий с существующими `_ID_PREFIXES` (`CLIN`, `CLII`, `TSK`,
`DOC`, `RM`, `RMS`, `OBJ`, `SVC`, `BIZ`, `PRS`, `CHK`, `DT`, `FAQ`, `SOP`,
`DEPT`, `ROLE` и др.) — `PMT`/`POB`/`PTXN` не пересекаются ни с одним
существующим префиксом.

Правила: ровно один генератор на identity, оба живут в `payment_manager.py`
через `sheets.generate_next_id`/`generate_next_ids`; никакой caller-side
генерации; malformed ID безопасно игнорируются (как во всех прочих
доменах); ID генерируются только после полной валидации и idempotency-
проверки (никогда — до); никакой title-based или amount/date-based
identity; никакого повторного использования Roadmap/Stage/Document ID как
платёжной identity.

```
COMMERCIAL_MILESTONE_TEMPLATE_IDENTITY_APPROVED = YES
PAYMENT_OBLIGATION_IDENTITY_APPROVED = YES
PAYMENT_TRANSACTION_IDENTITY_APPROVED = YES
```

### 6. Amount policy

Python `Decimal` исключительно, никогда `float`. Персистентность —
канонической decimal-строкой (например `"150000.00"`). Фиксированный scale
= 2 дробных знака для всех валют, включая KZT (единообразие важнее
KZT-специфичного целочисленного исключения — единственный реальный пример
(`150_000`/`500_000`/`300_000`) не требует тийин, но и не противоречит
scale=2). Amount обязателен и строго > 0 (отрицательные и нулевые суммы
запрещены и для Obligation, и для Transaction). Никакой scientific
notation, никаких locale-разделителей в хранимом значении (только в
Telegram-отображении, как уже делает `/milestones`). Детерминированная
нормализация на входе. Все суммы и totals считаются исключительно через
`Decimal`. Ввод с более чем 2 дробными знаками блокируется, а не тихо
округляется.

```
INVALID_PAYMENT_AMOUNT
INVALID_PAYMENT_AMOUNT_SCALE
PAYMENT_AMOUNT_MUST_BE_POSITIVE
```

```
PAYMENT_USES_DECIMAL_NOT_FLOAT = YES
PAYMENT_AMOUNT_SCALE_IS_EXPLICIT = YES
```

### 7. Currency policy

Обязателен явный 3-буквенный uppercase ISO-style код. `KZT` поддерживается
изначально (совпадает с дефолтом `service_catalog`). Никакой пустой/
implicit валюты ни на каком уровне персистентности. Template/Obligation/
Transaction — валюта всегда явная. Transaction currency обязана совпадать
с Obligation currency — иначе блок. Никакой кросс-валютной агрегации.
Никакой FX-конвертации в Foundation.

```
INVALID_PAYMENT_CURRENCY
PAYMENT_CURRENCY_MISMATCH
MULTI_CURRENCY_AGGREGATION_NOT_ALLOWED
```

```
PAYMENT_CURRENCY_IS_EXPLICIT = YES
MULTI_CURRENCY_AGGREGATION_IS_ALLOWED = NO
```

### 8. Template calculation policy

Ровно два режима, взаимоисключающих: `fixed`, `percentage`.

`fixed`: `Fixed Amount` обязателен, `Percentage` пуст, `Currency`
обязательна.
`percentage`: `Percentage` обязателен, `Fixed Amount` пуст, `Currency`
обязательна; percentage в Foundation — исключительно reference-метаданные;
никакого автоматического расчёта суммы без явного canonical pricing basis
(см. решение 9).

Противоречие (оба поля заполнены, оба пусты, либо поле не соответствует
заявленному Calculation Type) блокируется.

```
INVALID_MILESTONE_CALCULATION_TYPE
MILESTONE_FIXED_AMOUNT_REQUIRED
MILESTONE_PERCENTAGE_REQUIRED
MILESTONE_CALCULATION_FIELDS_CONFLICT
```

### 9. Pricing-basis policy

Foundation требует явную сумму Payment Obligation при создании. `fixed`-
Template может предложить amount по умолчанию (используется как есть).
`percentage`-Template НЕ может самостоятельно породить каноническую сумму:
Contract/Commercial Offer сущности не существуют нигде в кодовой базе —
единственный canonical price source отсутствует. Никакого автоматического
расчёта из `service_catalog`'s `Цена мин`/`Цена макс` (это price-range
reference-поля закрытого Service Domain, не операционная цена). Операционная
сумма снапшотится в Payment Obligation в момент создания; последующие
изменения Template или Service-цены никогда не переписывают уже созданные
Obligation (тот же snapshot-not-live-reference паттерн, что уже используют
Document/Checklist Domains).

```
FOUNDATION_REQUIRES_EXPLICIT_OBLIGATION_AMOUNT = YES
PERCENTAGE_TEMPLATE_AUTO_CALCULATION_IS_FOUNDATION_SCOPE = NO
```

### 10. Commercial Milestone Template lifecycle

Статусы: `active`, `inactive`, `archived`.

`active` — доступен для использования в новых Obligation. `inactive`
блокирует создание новых Obligation (существующие не затрагиваются).
`archived` блокирует любое новое использование. Никакого hard delete.
Восстановление (`active` ← `inactive`/`archived`) НЕ реализуется в
Foundation, но защита от случайного "ordinary"-перехода в обратную сторону
обязательна (тот же reopen-gated паттерн, что и в Document/Checklist).

### 11. Payment Obligation lifecycle

Статусы: `draft`, `issued`, `partially_paid`, `paid`, `cancelled`,
`archived`.

```
draft:           draft, issued, cancelled, archived
issued:          issued, partially_paid, paid, cancelled, archived
partially_paid:  partially_paid, paid, archived
                 → cancelled ТОЛЬКО если Paid Amount = 0, иначе блок
paid:            paid, archived
cancelled:       cancelled, archived
archived:        archived (только)
```

`partially_paid` и `paid` — синхронизируются исключительно из Transaction-
truth (§14), никогда не устанавливаются обычным ручным переходом без
соответствующего фактического баланса. `overdue` — derived at read-time
(due date просрочена И статус не в paid/cancelled/archived), никогда не
хранится как канонический статус. Никакого ordinary reopen из терминальных
состояний. Никакого hard delete.

Отмена (`cancelled`) после любого подтверждённого платежа запрещена: если
`Paid Amount > 0`, `cancelled` блокируется — сначала требуется реверс всех
confirmed Transaction до восстановления `Paid Amount = 0`, только после
этого отмена Obligation становится доступной.

### 12. Payment Transaction lifecycle

Статусы: `pending`, `confirmed`, `reversed`, `failed`.

```
pending:    pending, confirmed, failed
confirmed:  confirmed, reversed
reversed:   reversed (только)
failed:     failed (только)
```

`pending` не влияет на баланс. `failed` не влияет на баланс. `confirmed`
влияет на баланс. `reversed` перестаёт влиять на баланс. Финансовые поля
`confirmed`-строки immutable (Amount/Currency/Payment Date/External
Transaction ID/Created At). Реверс — явное, отдельное действие, не
"обычный" переход. Никакого ordinary reopen из терминальных состояний.
Никакого hard delete. Отрицательные суммы при реверсе запрещены (реверс —
это смена статуса на существующей строке, не компенсирующая транзакция с
отрицательной суммой).

### 13. Reversal model

Выбрана простая, ограниченная модель: **status-based reversal на исходной
строке**, НЕ отдельная reversal-транзакция.

- исходная `confirmed` Transaction меняет статус на `reversed`;
- `Reversal Reason`, `Reversed At`, `Reversed By` обязательны при этом
  переходе;
- исходные финансовые поля (Amount/Currency/Payment Date/External
  Transaction ID/Created At) остаются НЕИЗМЕНЕННЫМИ — переписывается
  только статус и добавляются reversal-метаданные;
- никакая вторая (offset/negative) Transaction-строка не создаётся в
  Foundation;
- баланс (Paid Amount/Remaining Amount) пересчитывается заново после
  реверса, автоматически исключая эту строку из суммы confirmed (§14).

Отклонена альтернатива "отдельная reversal-транзакция, связанная с
исходной через `Reversal Of Transaction ID`" — она добавляет вторую
транзакционную строку и поле-ссылку без демонстрированной необходимости в
Foundation (см. решение 34.G и раздел 2 про исключённое поле).

```
TRANSACTION_REVERSAL_IS_FOUNDATION_SCOPE = YES
TRANSACTION_HARD_DELETE_IS_ALLOWED = NO
```

### 14. Partial payments и derived truth

```
Paid Amount      = сумма Amount по confirmed (и НЕ reversed) Transaction.
Remaining Amount = Obligation Amount − Paid Amount.
```

`pending` и `failed` Transaction исключены из Paid Amount. `reversed`
Transaction исключены из Paid Amount (после реверса эффект её confirmed-
состояния аннулируется). Синхронизация статуса Obligation:

```
Paid Amount = 0                       → draft/issued остаются как есть
0 < Paid Amount < Obligation Amount   → partially_paid
Paid Amount = Obligation Amount       → paid
Paid Amount > Obligation Amount       → недопустимо, блокируется ДО
                                         подтверждения транзакции (см. §15)
```

`Paid Amount`/`Remaining Amount` могут персистироваться как verified
cache на строке Obligation (для быстрого чтения), но каноническая истина —
всегда `Obligation Amount` + фактические строки Transaction. Никаких
caller-side totals — вся арифметика в `business_builder.py`/
`payment_manager.py`.

```
PARTIAL_PAYMENTS_ARE_SUPPORTED = YES
PAID_AMOUNT_IS_DERIVED_FROM_TRANSACTIONS = YES
REMAINING_AMOUNT_IS_DERIVED = YES
```

### 15. Overpayment policy

Overpayment запрещён в Foundation: подтверждение (`pending → confirmed`)
Transaction блокируется, если оно сделало бы суммарные confirmed-платежи
больше `Remaining Amount` на момент подтверждения. Никакого credit-
баланса, никакого silent over-allocation, никакого автоматического
разбиения суммы между несколькими Obligation.

```
PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED
```

```
OVERPAYMENT_IS_ALLOWED_IN_FOUNDATION = NO
```

### 16. Obligation idempotency

Канонический ключ:

**Primary**: `Business ID` + `Caller Idempotency Key` (новое поле,
добавленное в схему §2 именно для этого).

**Fallback** (только когда Obligation явно инстанцируется из Template без
явного caller-ключа): `Business ID` + `Commercial Milestone Template ID` +
`Roadmap ID` + `Stage ID` + explicit Obligation Sequence.

Обоснование: тот же Template/Roadmap/Stage triple теоретически может
повториться (например, второй цикл этапа), поэтому единственный надёжный
основной механизм — явный caller-ключ; produced-from-Template fallback
используется только при явной Template-инстанциации с последовательным
Sequence.

Amount/date/client НЕ могут быть частью дедупликационного ключа: два
подлинно различных платежа (два одинаковых по сумме планомерных частичных
платежа, либо два разных клиента, платящих одну и ту же milestone-сумму в
один день) неотличимы по этим полям — это либо молча сольёт два реальных
платежа в один, либо молча отбросит второй.

Правила: zero creates; ровно один совместимый match — reuse; несколько
matches — блок с полным списком конфликтующих ID; никакого first-pick;
никакого title-based или amount/date-based dedup.

```
PAYMENT_OBLIGATION_IDEMPOTENCY_IS_APPROVED = YES
PAYMENT_TITLE_BASED_DEDUP_IS_ALLOWED = NO
PAYMENT_AMOUNT_DATE_BASED_DEDUP_IS_ALLOWED = NO
MULTIPLE_PAYMENT_IDEMPOTENCY_MATCHES_MUST_BLOCK = YES
```

### 17. Transaction idempotency

**Primary**: `Business ID` + `External Transaction ID`, когда он передан
(банк/платёжный шлюз предоставляет свою ссылку).

**Fallback**: `Business ID` + `Caller Idempotency Key`, когда внешней
ссылки нет.

Хотя бы одно из двух — `External Transaction ID` или `Caller Idempotency
Key` — обязательно; создание Transaction без обоих блокируется
(`PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED`). Amount/date/client не
являются dedup-ключом по той же причине, что и для Obligation. Zero
creates; один совместимый match — reuse; несколько matches — блок;
конфликт идемпотентности с несовместимым payload (тот же ключ, но другой
Obligation/Amount/Currency) — отдельный блокирующий код, не reuse.

```
PAYMENT_TRANSACTION_REUSED
MULTIPLE_PAYMENT_TRANSACTION_MATCHES
PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT
PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED
```

```
PAYMENT_TRANSACTION_IDEMPOTENCY_IS_APPROVED = YES
```

### 18. Relation policy

**Commercial Milestone Template** обязателен: `Roadmap Template ID` ИЛИ
`Service ID` — минимум одна каноническая context-связь.

**Payment Obligation** обязателен: `Business ID`, `Client ID`, `Obligation
Amount`, `Currency`. Опционально: `Object ID`, `Service ID`, `Roadmap ID`,
`Stage ID`, `Commercial Milestone Template ID`. Все переданные сущности
должны существовать; одна и та же Business на всех связанных сущностях;
Stage обязан принадлежать указанному Roadmap; Roadmap может служить
источником Client/Object/Service context там, где это канонично (тот же
паттерн, что уже использует `_validate_document_relations`/
`_validate_checklist_relations`); противоречия блокируются; никакого
auto-repair; никакого движения между Business; никаких generic
many-to-many связей.

**Payment Transaction** обязателен: `Business ID`, `Payment Obligation
ID`, `Client ID`, `Amount`, `Currency`, `Payment Date`, источник
идемпотентности (§17). Obligation должен существовать; та же Business;
Client Transaction должен совпадать с Client Obligation (см. §19);
валюта должна совпадать с валютой Obligation; никакой unallocated
Transaction в Foundation; никакой multi-obligation Transaction.

```
PAYMENT_ENTITY_RELATION_MISMATCH
PAYMENT_RELATION_POLICY_IS_APPROVED = YES
```

### 19. Client/payer policy

Foundation-упрощение: `Client ID` — обязательная payer identity.
Third-party payer (кто-то платит не за себя) НЕ поддерживается в
Foundation — `Client ID` Transaction обязан совпадать с `Client ID`
Obligation, иначе блок. Снапшот имени плательщика не хранится отдельно
(достаточно `Client ID` + существующий `people_registry`). Обновления
Client (имя, статус) никогда не переписывают уже сохранённые исторические
финансовые поля. Никакой кросс-Business payer-связи.

```
THIRD_PARTY_PAYER_IS_FOUNDATION_SCOPE = NO
```

### 20. Document boundary

`Evidence Document ID` — опциональное поле на Transaction, только
ссылка. Payment Domain не владеет файловым хранилищем, не реализует
upload-логику, не мутирует статус Document, не дублирует Document
Requirement логику. При передаче `Evidence Document ID` — валидация
существования и совпадения Business (тот же принцип, что во всех
cross-domain ссылках этого ADR), но никакой мутации Document-строки.

```
PAYMENT_EVIDENCE_MAY_REFERENCE_DOCUMENT = YES
PAYMENT_CAN_MUTATE_DOCUMENT_STATUS = NO
```

### 21. Roadmap/Stage boundary

Payment может ссылаться на Roadmap и Stage (опционально, только чтение/
валидация существования). Никакого автоматического создания Obligation из
`/startroadmap` в Foundation. Никакого завершения Stage от платежа.
Никакого завершения Roadmap от платежа. Никакой блокировки Stage-переходов
неоплаченным Obligation. Никакого lifecycle-каскада в любую сторону. Любая
будущая интеграция такого рода требует отдельного ADR.

```
PAYMENT_CAN_MUTATE_STAGE = NO
PAYMENT_CAN_MUTATE_ROADMAP = NO
AUTOMATIC_ROADMAP_PAYMENT_INSTANTIATION_IS_FOUNDATION_SCOPE = NO
```

### 22. Service/Commercial Offer/Contract boundary

`service_catalog`'s `Цена мин`/`Цена макс` остаются исключительно price-
range reference-полями закрытого Service Domain — не переосмысливаются и
не трогаются. Никакого canonical agreed-price source не существует.
Commercial Offer сущность не создаётся в Foundation. Contract сущность не
создаётся в Foundation. `fixed`-Template может предложить сумму по
умолчанию; явная сумма Obligation обязательна (§9). Никакого
автоматического расчёта процента.

### 23. Expense/accounting exclusions

Явно исключены из Foundation и из объёма этого ADR: расходы (expenses),
выплаты поставщикам, исходящие платежи, полноценный бухгалтерский леджер,
признание выручки (revenue recognition), P&L, налоги, комиссии, кассовые
операции, банковская сверка (reconciliation), генерация счетов (invoice
generation), исполнение возвратов (refund execution) сверх ограниченного
внутреннего реверса (§13).

```
EXPENSE_ACCOUNTING_IS_FOUNDATION_SCOPE = NO
FULL_ACCOUNTING_LEDGER_IS_FOUNDATION_SCOPE = NO
```

### 24. Hardcoded-map compatibility

`COMMERCIAL_MILESTONES_MAP` остаётся полностью нетронутым в Phase 39C.
`/milestones` остаётся read-only и неизменным. Никакого автоматического
перехода на новый Template registry. Никакой production-миграции.
Никакого удаления map. Будущая миграция потребует отдельной явно
утверждённой фазы.

```
CURRENT_COMMERCIAL_MILESTONES_MAP_REWRITE_REQUIRED = NO
PRODUCTION_PAYMENT_MIGRATION_REQUIRED = NO
```

### 25. Структурированный result contract

Единый канонический future Payment result contract (используется всеми
будущими `business_builder.py` Payment-функциями):

```
ok, code, error,
commercial_milestone_template_id, payment_obligation_id,
payment_transaction_id,
business_id, client_id, object_id, service_id, roadmap_id, stage_id,
document_id,
amount, currency, paid_amount, remaining_amount,
previous_status, requested_status, final_status,
created, reused, changed, confirmed, reversed, completed,
conflicting_ids, warnings, retry_safe
```

Каждое поле присутствует всегда (даже если `None`/пусто/`False`). Никакого
raw exception объекта. Никакой raw row. Никакого Telegram-специфичного
текста в manager/orchestration слоях — только в будущем `telegram_
handlers.py`.

```
PAYMENT_RESULT_CONTRACT_APPROVED = YES
```

### 26. Result-code vocabulary

Утверждены как канонические (без синонимов) — реализуются в Phase 39C
только там, где есть реальный runtime-вызов, порождающий этот код (не
формализуются "про запас", тот же принцип, что закрыл находку Phase 37F):

```
Template:
  COMMERCIAL_MILESTONE_TEMPLATE_CREATED
  COMMERCIAL_MILESTONE_TEMPLATE_REUSED
  COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND
  COMMERCIAL_MILESTONE_TEMPLATE_INACTIVE
  COMMERCIAL_MILESTONE_TEMPLATE_ARCHIVED
  INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS
  INVALID_MILESTONE_CALCULATION_TYPE
  MILESTONE_FIXED_AMOUNT_REQUIRED
  MILESTONE_PERCENTAGE_REQUIRED
  MILESTONE_CALCULATION_FIELDS_CONFLICT

Amount/currency:
  INVALID_PAYMENT_AMOUNT
  INVALID_PAYMENT_AMOUNT_SCALE
  PAYMENT_AMOUNT_MUST_BE_POSITIVE
  INVALID_PAYMENT_CURRENCY
  PAYMENT_CURRENCY_MISMATCH

Obligation:
  PAYMENT_OBLIGATION_CREATED
  PAYMENT_OBLIGATION_REUSED
  PAYMENT_OBLIGATION_NOT_FOUND
  MULTIPLE_PAYMENT_OBLIGATION_MATCHES
  PAYMENT_OBLIGATION_IDEMPOTENCY_CONFLICT
  PAYMENT_OBLIGATION_RELATION_MISMATCH
  INVALID_PAYMENT_OBLIGATION_STATUS
  INVALID_PAYMENT_OBLIGATION_TRANSITION
  PAYMENT_OBLIGATION_STATUS_UPDATED
  PAYMENT_OBLIGATION_STATUS_UNCHANGED
  PAYMENT_OBLIGATION_HAS_CONFIRMED_PAYMENTS
  PAYMENT_OBLIGATION_PERSISTENCE_FAILED
  PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED

Transaction:
  PAYMENT_TRANSACTION_CREATED
  PAYMENT_TRANSACTION_REUSED
  PAYMENT_TRANSACTION_NOT_FOUND
  MULTIPLE_PAYMENT_TRANSACTION_MATCHES
  PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED
  PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT
  PAYMENT_TRANSACTION_CONFIRMED
  PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED
  PAYMENT_TRANSACTION_REVERSED
  PAYMENT_TRANSACTION_REVERSAL_UNCHANGED
  PAYMENT_TRANSACTION_FAILED
  INVALID_PAYMENT_TRANSACTION_STATUS
  INVALID_PAYMENT_TRANSACTION_TRANSITION
  PAYMENT_TRANSACTION_IMMUTABLE
  PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED
  PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED
  PAYMENT_TRANSACTION_CONFIRMATION_METADATA_REQUIRED
  PAYMENT_TRANSACTION_PERSISTENCE_FAILED
  PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED

Generic:
  BUSINESS_NOT_FOUND
  CLIENT_NOT_FOUND
  OBJECT_NOT_FOUND
  SERVICE_NOT_FOUND
  ROADMAP_NOT_FOUND
  STAGE_NOT_FOUND
  DOCUMENT_NOT_FOUND
  PAYMENT_ENTITY_RELATION_MISMATCH
  PAYMENT_PERSISTENCE_FAILED
```

### 27. Privacy и логирование

Разрешено в логах: внутренние ID, result code, статусы, валюта,
ограниченные amount-поля только когда необходимо для диагностики,
флаги created/reused/changed, ID и count конфликтов, `retry_safe`.

Запрещено в логах: полное тело Telegram-сообщения, банковские/карточные/
счётные реквизиты, содержимое чеков/квитанций, персональные
идентификаторы сверх ID, поле `Notes`, детали метода платежа при их
чувствительности, `External Transaction ID` в открытом виде, содержимое
Document, raw rows, raw exceptions, credentials/токены.

```
PAYMENT_PRIVACY_LOGGING_POLICY_APPROVED = YES
```

### 28. Тестовые требования для Phase 39C

Категории обязательных изолированных тестов: schema (точные заголовки
трёх registry, отсутствие мутации существующей схемы), IDs (генерация
PMT/POB/PTXN, malformed игнорируются, никакой caller-side генерации),
amounts (Decimal only, scale, positivity, отсутствие float/scientific
notation, точное суммирование), currencies (обязательность, uppercase,
блок при mismatch, отсутствие смешанной агрегации), Template (fixed/
percentage режимы, конфликты полей, inactive/archived, стабильность
снапшота), relations (та же Business, совпадение Client, согласованность
Roadmap/Stage, опциональная валидация evidence Document, отсутствие
мутации закрытых доменов), idempotency (zero/one/multiple, конфликт при
несовместимом reuse, отсутствие title/amount-date dedup, полный список
конфликтующих ID), obligations (дефолты создания, явная сумма, отсутствие
авто-расчёта процента, lifecycle-переходы, блокировка отмены при
платежах, отсутствие reopen/hard delete), transactions (создание, pending,
подтверждение, частичный платёж, блок overpayment, несколько частичных
платежей, реверс, immutability, отсутствие отрицательных сумм, отсутствие
hard delete), balances (только confirmed, исключение pending/failed/
reversed, точность paid/remaining, синхронизация статуса, верификация
кэша), boundaries (отсутствие мутации Roadmap/Stage/Document/Checklist,
отсутствие интеграции с `/startroadmap`, неизменность hardcoded map),
isolation (все Payment-тесты — hard socket-block, mock-completeness guard,
отсутствие live Sheets/Drive/Telegram/Railway/socket).

### 29. Production migration policy

Никакой production-миграции в Phase 39C. Никакой перезаписи map. Никакого
backfill Template-строк. Никакого создания живых строк Obligation/
Transaction. Схемы могут быть определены только в коде (`BUSINESS_
SHEET_NAMES`/`BUSINESS_HEADERS`), физические вкладки Google Sheets могут
отсутствовать до отдельного будущего утверждённого шага записи. Сверка
(reconciliation) не требуется, поскольку никаких production
payment-строк не существует.

### 30. Bounded scope Phase 39C

Phase 39C реализует ТОЛЬКО: три схемы registry (в коде); генерацию ID
PMT/POB/PTXN; `payment_manager.py`; Decimal/currency нормализацию; точные
reads/filters; Foundation создания/чтения/обновления/статуса Commercial
Milestone Template; Foundation создания/чтения/статуса Payment Obligation;
Foundation создания/чтения/подтверждения/реверса Payment Transaction;
derived balance/status синхронизацию; idempotency; immutability;
relation-валидацию; структурированные result contracts;
architecture/isolation guards; тесты.

Явно запрещено в Phase 39C: Telegram caller UX; деплой; миграция
`/milestones`; автоматическая интеграция с Roadmap; автоматическое
создание Obligation; Payment Allocation; счета (invoices); расходы
(expenses); исходящие платежи; возвраты (refunds) сверх реверса;
Contract/Commercial Offer; hard delete; restore/reopen; полный accounting;
записи в production-данные.

```
PAYMENT_FOUNDATION_SCOPE_IS_BOUNDED = YES
```

### 31. Отклонённые альтернативы

**A. Одна Milestone-строка с Expected Amount + Paid Amount.** Отклонено:
уничтожает transaction-level auditability, невозможно безопасно
исправить ошибку без перезаписи единственной записи о факте.

**B. Полноценный accounting ledger сейчас.** Отклонено: слишком широкий
объём, не подтверждённый текущими деловыми свидетельствами (единственный
реальный пример — 3 фиксированные milestone-суммы одного Roadmap
Template).

**C. Payment Allocation registry в Foundation.** Отклонено: отсутствует
продемонстрированная many-to-many потребность; Option A (1 Transaction →
1 Obligation) покрывает единственный реальный сценарий без избыточной
инфраструктуры.

**D. Автоматический расчёт процента из `service_catalog` min/max.**
Отклонено: нет канонической согласованной цены — min/max это диапазон
для reference, не операционная сумма.

**E. Автоматическое создание Obligation из `/startroadmap`.**
Отклонено: cross-domain автоматизация такого рода не утверждена этим ADR
и требует отдельного решения после того, как Payment Domain
продемонстрирует стабильность.

**F. Немедленная перезапись `COMMERCIAL_MILESTONES_MAP`.** Отклонено:
риск совместимости и миграции без демонстрированной необходимости —
`/milestones` продолжает работать от текущего map до отдельно
утверждённого шага миграции.

**G. Перезапись полей подтверждённой Transaction.** Отклонено: уничтожает
финансовую историю — тот же принцип, что и решение A, применённый к
Transaction-слою; корректировка — только через explicit reversal (§13).

### 32. Cross-ADR consistency

Проверено на отсутствие противоречий с ADR по Roadmap/Stage (ADR-016/
ADR-017), Client, Service, Document (ADR-020), Checklist (ADR-021), Task
(ADR-019), Organization (ADR-018): ни один closed-домен не мутируется
Payment Foundation (§21, §22, §20 явно запрещают мутацию Roadmap/Stage/
Service/Document); Payment ссылается на их ID только для чтения/
валидации существования, тем же паттерном, что уже используют Document и
Checklist Domains для своих cross-domain связей.

### 33. Статус

Утверждено для реализации (Phase 39C) с bounded scope, определённым в
решении 30. Ничего не реализовано в рамках этого ADR — только
архитектурное решение. `payment_manager.py` не создан; `commercial_
milestone_templates`/`payment_obligations`/`payment_transactions` не
существуют; `COMMERCIAL_MILESTONES_MAP` и `/milestones` не изменены; ни
один production-caller не мигрирован; ни один код не изменён; схема
Google Sheets не менялась; GTD Core не затронут. Ни один закрытый домен
(Object/Client/Service/Roadmap/Stage/Organization/Task/Document/
Checklist) не переоткрыт.


## ADR-023 — Commercial Offer Domain Architecture Decision (Phase 40B)

### 0. Контекст

Phase 40A (Next Domain Selection Audit) установила: ни один оставшийся
домен не имеет production-данных, но Commercial Offer — единственный
кандидат, чья необходимость уже прямо задокументирована предыдущим
закрытым доменом. ADR-022 (Payment/Milestone) явно отказался от
автоматического расчёта суммы для `percentage`-режима Commercial
Milestone Template именно потому, что в репозитории нет канонического
источника согласованной (agreed) цены — `service_catalog`'s "Цена
мин"/"Цена макс" являются диапазоном для reference, а не операционной
ценой конкретному Клиенту. Commercial Offer Domain закрывает именно
этот пробел: канонический quoted/agreed amount, привязанный к
конкретному Client/Object/Service/Roadmap, с собственным жизненным
циклом (draft/sent/accepted/...), но без Contract-уровня (подпись,
юридические условия) и без Invoice-уровня (номер счёта, налоги).

Repository evidence (Phase 40A): нет ни одной строки production-данных,
нет реестра, нет manager-модуля, нет команд — полностью чистый лист,
аналогично состоянию Payment Domain перед Phase 39C, но даже без
hardcoded-конфигурации вроде `COMMERCIAL_MILESTONES_MAP`.

Это ADR утверждает архитектуру Commercial Offer Domain Foundation
(Phase 40C) — один операционный реестр `commercial_offers`,
immutable-row-based versioning, явный closed lifecycle, без Contract,
без Invoice, без line items, без автоматического создания Payment
Obligation.

### 1. Канонический entity

**Commercial Offer** — единственная каноническая сущность Foundation.
Представляет одно конкретное коммерческое предложение, представленное
одному Client, принадлежащее одному Business. Содержит одну явную
quoted-сумму и валюту. Снапшотит предложенный объём (scope) и
коммерческие условия версии. Может ссылаться на Object/Service/
Roadmap/Document. Имеет собственный lifecycle. НЕ является Contract
(нет подписи/юридических условий), НЕ является Invoice (нет номера
счёта/налогов/due-date-статуса оплаты), НЕ является Payment Obligation
(не доказывает получение денег — Payment Obligation остаётся
единственной canonical expected-money сущностью, ADR-022).

```
COMMERCIAL_OFFER_IS_CANONICAL_QUOTED_TERMS_ENTITY = YES
COMMERCIAL_OFFER_IS_NOT_PAYMENT_OBLIGATION = YES
COMMERCIAL_OFFER_IS_NOT_CONTRACT = YES
COMMERCIAL_OFFER_IS_NOT_INVOICE = YES
COMMERCIAL_OFFER_ACCEPTANCE_DOES_NOT_MEAN_PAYMENT_RECEIVED = YES
```

### 2. Модель версионирования

Выбрана: **immutable version rows с самого начала** (не единственная
mutable draft-строка с иммутабельными снапшотами после отправки).

- каждая строка `commercial_offers` — immutable коммерческая версия;
- пересмотр предложения создаёт НОВУЮ строку, никогда не переписывает
  существующую;
- `Previous Commercial Offer ID` связывает новую версию с
  непосредственным предшественником;
- `Offer Series ID` группирует все версии одного и того же
  коммерческого предложения;
- `Version Number` — положительное целое число, монотонно
  увеличивается внутри серии;
- только одна текущая non-terminal версия может быть "активной"
  (derived, не хранится отдельным полем — см. решение 12);
- предыдущие версии никогда не перезаписываются;
- никакой line-level amendment-машинерии.

Обоснование: отправленные/принятые коммерческие условия должны
оставаться auditable — позднее изменение суммы или объёма не должно
переписывать то, что Клиент реально получил изначально. Реализация
остаётся ограниченной, поскольку версионирование — на уровне строки, а
не на уровне отдельных пунктов предложения (тот же принцип, что и
Document Domain использует для версий документа).

```
COMMERCIAL_OFFER_VERSIONING_IS_IMMUTABLE_ROW_BASED = YES
```

### 3. Дизайн реестра

Утверждён ровно один Foundation registry: **`commercial_offers`**.

```
Commercial Offer ID
Offer Series ID
Previous Commercial Offer ID
Version Number
Business ID
Client ID
Object ID
Service ID
Roadmap ID
Offer Document ID
Title Snapshot
Scope Snapshot
Quoted Amount
Currency
Valid Until
Status
Caller Idempotency Key
Created At
Created By
Updated At
Sent At
Sent By
Accepted At
Accepted By
Rejected At
Rejected By
Rejection Reason
Expired At
Cancelled At
Cancelled By
Cancellation Reason
Archived At
Notes
```

Все предложенные поля сохранены как необходимые — каждое соответствует
ровно одному lifecycle-переходу или одному identity/relation/snapshot
факту, без избыточности (то же соответствие "одно поле = один
задокументированный факт", что используют payment_obligations/
payment_transactions).

Явно НЕ добавлено:

```
- line-item JSON;
- comma-separated Service IDs;
- comma-separated Object IDs;
- generic relation JSON;
- payment status;
- paid amount;
- remaining amount;
- contract-поля;
- invoice-поля;
- signature payload;
- tax ledger-поля.
```

```
COMMERCIAL_OFFER_REGISTRY_APPROVED = YES
```

### 4. Решение по line items

```
COMMERCIAL_OFFER_LINE_ITEM_ENTITY_REQUIRED_IN_FOUNDATION = NO
```

Foundation хранит: одну quoted-сумму итого; один ограниченный Scope
Snapshot (текстовое описание объёма); опциональную единственную Service
-связь; опциональные Object/Roadmap-связи.

Обоснование: нет текущих доказательств необходимости multi-line
pricing (ни одного production-примера, ни одного запроса); line items
добавили бы identity/ordering/quantity/unit-price/discount/tax
сложность несоразмерную демонстрированной потребности. Путь будущего
расширения явно оставлен открытым: `Offer Series ID` + `Commercial
Offer ID` уже дают стабильный parent-identity, к которому в будущем
можно добавить отдельный `commercial_offer_line_items` реестр (тот же
паттерн parent+child, что checklist_instances/checklist_instance_items
и payment_obligations/payment_transactions), не переписывая уже
созданные Offer-строки.

### 5. Identity policy

```
Commercial Offer ID: OFR-NNN
Offer Series ID:     OFS-NNN
```

Проверка коллизий: среди всех существующих `_ID_PREFIXES` (BIZ, SVC,
PRS, CH, INT, RM, STAGE, MAT, OBJ, RTMPL, TSTG, SOP, CHK, DOC, FAQ,
DREG, REL, DEPT, ROLE, FUNC, PRA, TSK, TAS, CLIN, CLII, PMT, POB, PTXN)
— `OFR`/`OFS` не пересекаются ни с одним.

Ровно один генератор на identity, оба живут в `offer_manager.py` через
`sheets.generate_next_id`/`generate_next_ids`. Никакой caller-side
генерации. Malformed ID безопасно игнорируются. ID генерируются только
после полной валидации и idempotency-проверки. Никакой title-based или
amount/date-based identity. Никакого повторного использования Client/
Object/Service/Payment ID как Offer identity.

```
OFR_IDENTITY_APPROVED = YES
OFS_IDENTITY_APPROVED = YES
```

### 6. Persistence ownership

`business_core/offer_manager.py` — единственный persistence owner для
`commercial_offers`. Владеет: точечные reads, ограниченные list/filter
reads, генерацию OFR/OFS, низкоуровневое создание строки,
низкоуровневую персистентность lifecycle-переходов, ограниченное
draft-only admin-обновление, idempotency-lookup примитивы, version-
series lookup (поиск максимального Version Number в серии), проверку
текущей строки после записи, immutable-field enforcement.

НЕ владеет: cross-domain relation-валидацией, коммерческой policy-
оркестрацией (acceptance policy, revision-оркестрация), Telegram UX,
созданием Payment Obligation, созданием/мутацией Document, raw
exception rendering.

```
OFFER_MANAGER_IS_APPROVED_PERSISTENCE_OWNER = YES
```

### 7. Orchestration ownership

`business_builder.py` — единственный cross-domain owner Commercial
Offer-оркестрации. Владеет: relation-валидацию, amount/currency
normalization, создание Offer, revision Offer, lifecycle-переходы,
version/series-валидацию, idempotency zero/one/multiple handling,
неизменность принятого Offer, structured result assembly.

Направление зависимостей:

```
telegram_handlers
  → business_builder
    → offer_manager
      → sheets
```

Без обратной зависимости и без циклов.

```
BUSINESS_BUILDER_IS_APPROVED_OFFER_ORCHESTRATION_OWNER = YES
```

### 8. Amount policy

Переиспользуется Payment-дисциплина Decimal без изменений в закрытом
Payment Domain. `Decimal` исключительно, никогда `float`; каноническая
decimal-строка; scale ровно 2; сумма обязательна и строго `> 0`; более
2 дробных знаков блокирует; никакой scientific notation; никаких
locale-разделителей в хранимом значении; никакого silent rounding.

Решение по реализации: Phase 40C должен предпочесть переиспользование
существующего примитива `business_builder.normalize_payment_amount()`
как есть (без изменения его кода, интерфейса или поведения — чтение
только), если это не требует модификации файла `payment_manager.py`
или Payment-специфичных кодов результата. Если переиспользование
создаёт двусмысленность именования (например, код ошибки
`INVALID_PAYMENT_AMOUNT` появляется в Offer-контексте), Phase 40C
обязан реализовать эквивалентный Offer-локальный wrapper
(`normalize_commercial_offer_amount()`), производящий Offer-specific
коды (`INVALID_COMMERCIAL_OFFER_AMOUNT` и т.д.), не трогая Payment-код.
Payment Domain остаётся полностью нетронутым в любом случае.

```
COMMERCIAL_OFFER_USES_DECIMAL_NOT_FLOAT = YES
COMMERCIAL_OFFER_AMOUNT_SCALE_IS_EXPLICIT = YES
```

### 9. Currency policy

Явная валюта обязательна; uppercase 3-буквенный ASCII-код; никакого
implicit default на уровне персистентности; никакой FX-конвертации;
никакой кросс-валютной агрегации Offer. Пересмотренные версии обычно
сохраняют валюту исходной версии; смена валюты в revision должна быть
явной (передана заново, не унаследована молча) и никогда не
переписывает предыдущие версии.

```
COMMERCIAL_OFFER_CURRENCY_IS_EXPLICIT = YES
```

### 10. Snapshot policy

`Title Snapshot` и `Scope Snapshot` обязательны. Снапшоты — коммерческие
факты именно этой версии. После выхода из `draft` amount/currency/
title/scope/relations становятся неизменяемыми. Изменения Service/
Object/Roadmap после создания никогда не переписывают снапшоты.
Никакой live-реконструкции принятого объёма из Service catalog. Никакой
логирование полного текста snapshot (см. §решение о privacy).
Ограничение длины: `Title Snapshot` — разумный короткий заголовок (as
with Document/Checklist Title fields, без жёсткого числового лимита в
Foundation, но не блок текста); `Scope Snapshot` — свободный текст без
искусственного лимита в Foundation (аналогично `Description Snapshot`
Payment Obligation), поскольку коммерческий объём может быть
многострочным описанием условий.

```
COMMERCIAL_OFFER_TITLE_SNAPSHOT_IS_REQUIRED = YES
COMMERCIAL_OFFER_SCOPE_SNAPSHOT_IS_REQUIRED = YES
```

### 11. Relation policy

Обязательны: `Business ID`, `Client ID`. Опциональны: `Object ID`,
`Service ID`, `Roadmap ID`, `Offer Document ID`. Правила: все
переданные сущности должны существовать; все связи должны принадлежать
той же Business (там, где текущая canonical модель это поддерживает —
Roadmap может служить источником Client/Object/Service context, тем же
паттерном, что и Payment Obligation §18 ADR-022); Client должен быть
валидным Client; противоречия блокируются; никакого auto-repair;
никакого движения между Business; Offer Document — только ссылка;
никакой мутации Document/Service/Client/Object/Roadmap/Payment.

Решение: хотя бы одна коммерческая context-связь обязательна — Service
ID, Object ID или Roadmap ID (нельзя создать Offer без привязки к
конкретному коммерческому контексту, только Business+Client
недостаточно).

```
COMMERCIAL_OFFER_CONTEXT_RELATION_IS_REQUIRED = YES
```

### 12. Document boundary

`Offer Document ID` — опциональная ссылка на существующий Document
только. Commercial Offer Domain не генерирует файлы в Foundation:
никакой upload-логики, никакого template rendering, никакого PDF-
генерации, никакой мутации Document lifecycle. Same-Business
валидация обязательна при передаче. Принятый Offer остаётся валидным,
даже если связанный Document позже архивирован — коммерческие снапшоты
хранятся в самой строке Offer, не зависят от текущего состояния
Document.

```
COMMERCIAL_OFFER_DOCUMENT_IS_REFERENCE_ONLY = YES
```

### 13. Lifecycle vocabulary

```
draft
sent
accepted
rejected
expired
cancelled
archived
```

Не добавлены: `paid`, `partially_paid`, `invoiced`, `contracted`,
`signed` — все они относятся к другим доменам (Payment/Contract/
Invoice), не Commercial Offer.

```
COMMERCIAL_OFFER_STATUS_VOCABULARY_IS_APPROVED = YES
```

### 14. Lifecycle matrix

```
draft:      draft, sent, cancelled, archived
sent:       sent, accepted, rejected, expired, cancelled, archived
accepted:   accepted, archived
rejected:   rejected, archived
expired:    expired, archived
cancelled:  cancelled, archived
archived:   archived (только)
```

`accepted` — коммерчески терминален: никакого accepted → rejected/
cancelled/draft. `rejected`/`expired`/`cancelled` не могут быть
reopened обычным переходом. Никакого ordinary restore. Никакого hard
delete. Тот же статус — безопасный no-op.

```
COMMERCIAL_OFFER_TRANSITION_MATRIX_IS_APPROVED = YES
```

### 15. Expiration policy

Выбрана модель: `expired` остаётся в closed vocabulary как реальный
хранимый статус, доступный через явный `sent → expired` переход
(callable), НЕ через фоновую автоматическую мутацию. Read-слои
(будущая caller UX) могут дополнительно отображать "sent, но Valid
Until уже прошёл" как effectively-expired без перезаписи строки — это
derived-отображение, не изменение канонического Status. Никакого
background job в Foundation. `accepted`/`rejected`/`cancelled`/
`archived` никогда не auto-expire.

```
COMMERCIAL_OFFER_EXPIRATION_POLICY_IS_APPROVED = YES
```

### 16. Draft mutability и sent/accepted immutability

Draft может обновлять: `Title Snapshot`, `Scope Snapshot`, `Quoted
Amount`, `Currency`, `Valid Until`, `Object ID`, `Service ID`,
`Roadmap ID`, `Offer Document ID`, `Notes`. После `sent` коммерческие
поля становятся неизменяемыми — изменяются только lifecycle-переходы и
их метаданные. `Notes` остаётся административно изменяемым всегда
(включая после `sent`/`accepted`) — единственное исключение из
коммерческой неизменности, поскольку Notes — не коммерческий факт, а
внутренняя административная заметка (тот же принцип, что payment_
obligations допускает Notes-редактирование независимо от финансовой
неизменности Transaction).

```
SENT_COMMERCIAL_OFFER_TERMS_ARE_IMMUTABLE = YES
ACCEPTED_COMMERCIAL_OFFER_TERMS_ARE_IMMUTABLE = YES
```

### 17. Revision policy

Revision реализуется как новая строка, никогда не как обновление
sent/accepted условий. Требуется существующий source Offer; source
должен принадлежать той же Business; новая строка получает новый OFR
ID; тот же Offer Series ID; Version Number увеличивается
детерминированно (`max(existing) + 1`); `Previous Commercial Offer ID`
ссылается на непосредственного предшественника; caller обязан передать
новый idempotency key; source-строка остаётся неизменной; новая версия
по умолчанию `draft`; коммерческие поля могут наследоваться от source и
быть явно переопределены. `accepted`/`rejected`/`expired`/`cancelled`
Offer МОГУТ быть revised в новую draft-версию без reopening старой
версии — сама операция revision не является reopen исходной строки
(исходная строка остаётся в своём терминальном статусе, просто
появляется новая независимая строка-потомок).

Branching запрещён в Foundation: ровно одна следующая версия на каждую
текущую последнюю версию. Revision НЕ-последней версии блокируется
(`COMMERCIAL_OFFER_NOT_LATEST_VERSION`). Множественные совпадения с
максимальным Version Number — integrity error, блокируется
(`COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR`), без first-pick.

```
COMMERCIAL_OFFER_REVISION_CREATES_NEW_ROW = YES
COMMERCIAL_OFFER_BRANCHING_IS_ALLOWED_IN_FOUNDATION = NO
```

### 18. Latest/current-version policy

Единственный источник истины: latest version определяется как
максимальный `Version Number` внутри `Offer Series ID` — derived
чтением, никакого мутируемого поля `Is Current` в Foundation.
Множественные строки с одинаковым максимальным Version Number —
integrity error (не должно происходить при корректной работе
Foundation, но защищено явной проверкой), без first-pick.

```
LATEST_COMMERCIAL_OFFER_VERSION_IS_DERIVED = YES
```

### 19. Создание Offer

Обязательны: `Business ID`, `Client ID`, `Title Snapshot`, `Scope
Snapshot`, `Quoted Amount`, `Currency`, `Valid Until`, `Created By`,
`Caller Idempotency Key`, хотя бы одна коммерческая context-связь.

`Valid Until` обязателен (не "explicit no-expiry policy" — Foundation
не поддерживает бессрочные предложения, что соответствует нормальной
коммерческой практике и упрощает §15's expiration-модель); ISO-дата;
не может быть раньше даты создания.

Defaults: новый `Offer Series ID`; `Version Number = 1`; `Previous
Commercial Offer ID` пуст; `Status = draft`; lifecycle-таймстампы
пусты; `Created At`/`Updated At` установлены.

### 20. Idempotency policy

Primary key создания: `Business ID` + `Caller Idempotency Key`. Тот же
ключ используется и для revision (каждая revision требует свой новый
caller key — не переиспользует ключ source-версии). Caller key
обязателен (нет template-derived fallback, в отличие от Payment
Obligation — у Commercial Offer нет эквивалента Commercial Milestone
Template как источника инстанциации). Zero creates; один совместимый
match — reuse; несколько matches — блок с полным списком конфликтующих
ID; несовместимый payload с тем же ключом — блок; никакого first-pick;
никакого title-based или amount/date-based dedup; ID генерируются
только после проверки идемпотентности.

```
COMMERCIAL_OFFER_IDEMPOTENCY_IS_APPROVED = YES
COMMERCIAL_OFFER_TITLE_BASED_DEDUP_IS_ALLOWED = NO
COMMERCIAL_OFFER_AMOUNT_DATE_BASED_DEDUP_IS_ALLOWED = NO
MULTIPLE_COMMERCIAL_OFFER_MATCHES_MUST_BLOCK = YES
```

### 21. Acceptance policy

Только `sent` Offer может быть принят. `Accepted By` обязателен.
`Accepted At` устанавливается один раз. Принятый Offer — коммерчески
неизменен. Acceptance НЕ создаёт Payment Obligation, НЕ мутирует
Roadmap/Stage, НЕ создаёт Contract, НЕ создаёт Invoice, НЕ означает
получение оплаты, НЕ обновляет автоматически цену в Service.

Только последняя (latest) версия в Offer Series может быть принята —
принятие устаревшей (superseded) версии блокируется
(`COMMERCIAL_OFFER_NOT_LATEST_VERSION`).

```
ONLY_LATEST_OFFER_VERSION_MAY_BE_ACCEPTED = YES
COMMERCIAL_OFFER_ACCEPTANCE_CREATES_PAYMENT_OBLIGATION = NO
```

### 22. Rejection policy

Только `sent` Offer может быть отклонён. `Rejected By` обязателен.
`Rejection Reason` обязателен, но является чувствительным свободным
текстом — не логируется (см. §privacy). Никакого reopen. Revision
может создать новую draft-версию из отклонённой.

### 23. Cancellation policy

`draft` или `sent` могут быть отменены. `Cancelled By` обязателен.
`Cancellation Reason` обязателен. `accepted` не может быть отменён.
Cancellation не удаляет строку. Никакого reopen. Revision из
отменённой версии допускается только как новая версия.

### 24. Archive policy

Archive терминален. Никакого hard delete. Никакого ordinary restore.
Архивированные строки остаются читаемыми по точному ID. Архивированные
строки исключены из обычных активных списков по умолчанию. Никакого
автоматического каскада на связанные сущности.

### 25. Payment boundary

Принятый Commercial Offer МОЖЕТ стать будущей pricing basis (то есть
будущая интеграция Offer→Payment концептуально допустима), но:

```
COMMERCIAL_OFFER_ACCEPTANCE_CREATES_PAYMENT_OBLIGATION = NO
```

Phase 40C не создаёт Payment Obligation автоматически; никакой
интеграции с percentage-расчётом Payment Template в Phase 40C; никакой
записи в payment_manager из Offer Domain; никакой мутации Payment
lifecycle; никаких paid/remaining-полей в Commercial Offer. Будущая
интеграция Offer→Payment требует отдельного ADR или отдельно
утверждённой интеграционной фазы.

```
COMMERCIAL_OFFER_CAN_MUTATE_PAYMENT = NO
```

### 26. Service boundary

Service-связь — только для чтения. Диапазон цены Service остаётся
reference-данными. Commercial Offer не переписывает цены Service.
Offer amount — операционная quoted-сумма, независимая от диапазона
Service. Несовпадение с диапазоном цены Service НЕ блокирует создание
Offer в Foundation (никакой скрытой pricing-policy); опциональное
предупреждение может быть рассмотрено позже, но не реализуется в
Foundation.

```
COMMERCIAL_OFFER_CAN_MUTATE_SERVICE = NO
COMMERCIAL_OFFER_CAN_MUTATE_CLIENT = NO
COMMERCIAL_OFFER_CAN_MUTATE_OBJECT = NO
COMMERCIAL_OFFER_CAN_MUTATE_ROADMAP = NO
COMMERCIAL_OFFER_CAN_MUTATE_DOCUMENT = NO
```

### 27. Contract и Invoice boundaries

Никакого Contract registry. Никакого signature workflow. Никакой
legal amendment/termination модели. Никакого Invoice registry. Никакой
нумерации счетов. Никаких налоговых полей. Никакого due-payment-
статуса. Никакого revenue recognition. Принятый Offer — не Contract и
не Invoice.

```
CONTRACT_IS_FOUNDATION_SCOPE = NO
INVOICE_IS_FOUNDATION_SCOPE = NO
```

### 28. Структурированный result contract

```
ok, code, error,
commercial_offer_id, offer_series_id, previous_commercial_offer_id, version_number,
business_id, client_id, object_id, service_id, roadmap_id, document_id,
amount, currency, valid_until,
previous_status, requested_status, final_status,
created, reused, changed, revised,
sent, accepted, rejected, expired, cancelled, archived,
conflicting_ids, warnings, retry_safe
```

Каждое поле присутствует всегда. Никакого raw exception. Никакого raw
row. Никакого Telegram-специфичного текста в manager/orchestration.

```
COMMERCIAL_OFFER_RESULT_CONTRACT_APPROVED = YES
```

### 29. Result-code vocabulary

Утверждены как канонические (без синонимов), реализуются в Phase 40C
только там, где есть реальный runtime-вызов:

```
Создание/revision:
  COMMERCIAL_OFFER_CREATED
  COMMERCIAL_OFFER_REUSED
  COMMERCIAL_OFFER_REVISED
  COMMERCIAL_OFFER_NOT_FOUND
  MULTIPLE_COMMERCIAL_OFFER_MATCHES
  COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED
  COMMERCIAL_OFFER_IDEMPOTENCY_CONFLICT
  COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR
  COMMERCIAL_OFFER_NOT_LATEST_VERSION
  COMMERCIAL_OFFER_PERSISTENCE_FAILED
  COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED

Amount/currency:
  INVALID_COMMERCIAL_OFFER_AMOUNT
  INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE
  COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE
  INVALID_COMMERCIAL_OFFER_CURRENCY

Relations:
  BUSINESS_NOT_FOUND
  CLIENT_NOT_FOUND
  OBJECT_NOT_FOUND
  SERVICE_NOT_FOUND
  ROADMAP_NOT_FOUND
  DOCUMENT_NOT_FOUND
  COMMERCIAL_OFFER_RELATION_MISMATCH
  COMMERCIAL_OFFER_CONTEXT_REQUIRED

Validation:
  COMMERCIAL_OFFER_TITLE_REQUIRED
  COMMERCIAL_OFFER_SCOPE_REQUIRED
  INVALID_COMMERCIAL_OFFER_VALID_UNTIL
  COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST
  INVALID_COMMERCIAL_OFFER_VERSION

Lifecycle:
  INVALID_COMMERCIAL_OFFER_STATUS
  INVALID_COMMERCIAL_OFFER_TRANSITION
  COMMERCIAL_OFFER_STATUS_UPDATED
  COMMERCIAL_OFFER_STATUS_UNCHANGED
  COMMERCIAL_OFFER_SENT
  COMMERCIAL_OFFER_ACCEPTED
  COMMERCIAL_OFFER_REJECTED
  COMMERCIAL_OFFER_EXPIRED
  COMMERCIAL_OFFER_CANCELLED
  COMMERCIAL_OFFER_ARCHIVED
  COMMERCIAL_OFFER_ACCEPTED_IMMUTABLE
  COMMERCIAL_OFFER_REJECTION_REASON_REQUIRED
  COMMERCIAL_OFFER_CANCELLATION_REASON_REQUIRED
  COMMERCIAL_OFFER_ACTOR_REQUIRED
  COMMERCIAL_OFFER_RESTORE_REQUIRES_EXPLICIT_ACTION

Admin update:
  COMMERCIAL_OFFER_UPDATED
  COMMERCIAL_OFFER_UPDATE_UNCHANGED
  COMMERCIAL_OFFER_IMMUTABLE
```

Phase 40C не обязан реализовывать коды, для которых в Foundation нет
реального callable (тот же принцип "no comment-only vocabulary",
закрывший находку Phase 37F Document Domain).

### 30. Privacy и логирование

Разрешено в логах: внутренние ID, result code, lifecycle-статусы,
валюта, ограниченные amount-поля только при необходимости, номер
версии, флаги created/reused/revised, ID и count конфликтов,
`retry_safe`.

Запрещено в логах: полный текст `Scope Snapshot`, `Notes`, `Rejection
Reason`, `Cancellation Reason`, полное тело Telegram-сообщения,
персональные данные Client, содержимое Document, raw row, raw
exception, credentials/токены.

```
COMMERCIAL_OFFER_PRIVACY_LOGGING_POLICY_APPROVED = YES
```

### 31. Тестовые требования для Phase 40C

Обязательные изолированные категории тестов: schema (точные заголовки
`commercial_offers`, отсутствие мутации существующей схемы); IDs
(генерация OFR/OFS, malformed игнорируются, отсутствие caller-side
генерации, генерация после validation/idempotency); amounts (Decimal
only, positivity, scale, отклонение float/scientific/comma, точная
персистентность); currency (обязательность, uppercase, недопустимые
коды, отсутствие implicit default); relations (обязательность
Business/Client/context, same-Business, Roadmap-derived context,
блокировка противоречий, опциональная валидация Document, отсутствие
мутации закрытых доменов); creation (дефолты, снапшоты, валидация
expiry, идемпотентность zero/one/multiple/conflict, ошибки
persistence/verification); versioning (новая серия, revision,
Previous ID, инкремент версии, derivation latest-version, блокировка
revision не-последней версии, предотвращение branching, неизменность
source); lifecycle (все разрешённые переходы, все запрещённые
переходы, no-op, обязательность actor/reason, latest-version-only
acceptance, неизменность после acceptance, отсутствие restore,
отсутствие hard delete); admin update (draft-only коммерческие
обновления, неизменность после sent/terminal, политика Notes, no-op
таймстампы); boundaries (отсутствие мутации Payment/Service/Client/
Object/Roadmap/Document, отсутствие Contract/Invoice); isolation (все
тесты Commercial Offer — hard socket-block, mock-completeness guard,
отсутствие live Sheets/Drive/Telegram/Railway/socket).

### 32. Production migration policy

Никакой production-миграции в Phase 40C. Никаких существующих строк
для миграции. Никаких legacy Offer-данных. Схема может быть определена
только в коде. Физическая production-вкладка может отсутствовать.
Никаких живых строк Commercial Offer, созданных во время Foundation-
тестов. Никаких изменений Payment. Никакой перезаписи цен Service.

```
COMMERCIAL_OFFER_PRODUCTION_MIGRATION_REQUIRED = NO
```

### 33. Bounded scope Phase 40C

Phase 40C реализует ТОЛЬКО: одну схему registry `commercial_offers` (в
коде); ID OFR/OFS; `offer_manager.py`; нормализацию amount/currency/
date; точные reads и ограниченные фильтры; создание Commercial Offer;
revision Commercial Offer; draft admin-обновление; lifecycle-переходы;
derivation latest-version; idempotency; relation-валидацию;
immutability; структурированный result contract; architecture/
isolation guards; тесты.

Явно запрещено в Phase 40C: Telegram caller UX; деплой; Contract;
Invoice; Offer line items; PDF/document generation; автоматическое
создание Payment Obligation; интеграция percentage Payment; автоматическая
мутация Roadmap/Stage; signature flow; налоговая логика; полный pricing
engine; discounts/commissions; записи в production-данные; hard
delete; restore/reopen.

### 34. Отклонённые альтернативы

**A. Переиспользование Payment Obligation как Commercial Offer.**
Отклонено: ожидаемая дебиторская задолженность (receivable) и
коммерческое предложение (quote) — разные факты жизненного цикла;
Obligation подразумевает согласованный долг, Offer — ещё не принятое
предложение.

**B. Хранение согласованной цены прямо в Service.**
Отклонено: диапазон цены Service — общие reference-данные, не
Client-специфичные согласованные условия.

**C. Mutable единственная Offer-строка после отправки.**
Отклонено: переписывает исторические коммерческие условия, которые
Клиент реально получил.

**D. Полный Contract domain сейчас.**
Отклонено: объём signature/legal/amendment слишком широк для
следующего bounded-цикла.

**E. Invoice domain сейчас.**
Отклонено: дублирует Payment Obligation без демонстрированной внешней
необходимости.

**F. Line items в Foundation.**
Отклонено: нет текущих доказательств необходимости разбивки по
количеству/цене за единицу/налогу.

**G. Автоматическое создание Payment Obligation при acceptance.**
Отклонено: cross-domain интеграция такого рода пока не утверждена.

**H. Автоматический percentage-расчёт Payment в Phase 40C.**
Отклонено: интеграция Offer→Payment требует отдельного явного решения
в будущем.

### 35. Cross-ADR consistency

Проверено на отсутствие противоречий с решениями по Service/Client/
Object/Roadmap/Stage Domain, Document ADR-020, Payment ADR-022,
Organization ADR-018, Task ADR-019, Checklist ADR-021: ни один закрытый
домен не мутируется Commercial Offer Foundation — Offer ссылается на их
ID только для чтения/валидации существования, тем же паттерном, что уже
используют Document/Checklist/Payment Domains для своих cross-domain
связей.

### 36. Статус

Утверждено для реализации (Phase 40C) с bounded scope, определённым в
решении 33. Ничего не реализовано в рамках этого ADR — только
архитектурное решение. `offer_manager.py` не создан; `commercial_
offers` не существует; ни один production-caller не мигрирован; ни
один код не изменён; схема Google Sheets не менялась; GTD Core не
затронут. Ни один закрытый домен (Object/Client/Service/Roadmap/Stage/
Organization/Task/Document/Checklist/Payment) не переоткрыт.


## ADR-024 — Lead / Sales Funnel Domain Architecture Decision (Phase 41B)

### 0. Контекст

Phase 41A (Next Domain Selection Audit) переоценила Lead/Sales Funnel
после закрытия Payment и Commercial Offer Domains и подтвердила: это
единственный оставшийся кандидат, закрывающий реальный, ранее не
покрытый участок бизнес-жизненного цикла — pre-Client этап продаж.
Person/Client Domain (закрыт) начинает жизненный цикл сразу с готового
Client-контакта; отдельной pre-Client сущности не существует. При этом
production-данные подтверждают: все 3 существующих Person-записи уже
типизированы как "клиент"/"клиент по узаконению" — pre-client записей
нет вообще, миграция не требуется.

Ключевая архитектурная находка Phase 41A: Person уже содержит
разрозненные lead-подобные поля ("Источник", "История", "Следующее
касание", "Тип касания", "Заметка касания", "Статус отношений",
"Теплота"), плюс полностью нерабочий (orphaned) код
`relationship_capital.py` (`RelationshipTouch`/`create_touch_record()`)
— никогда не подключённый ни к одной команде и несовместимый по схеме
с самим реестром `relationship_capital`. Это ADR явно фиксирует: Lead
Domain НЕ трогает ни одно из этих полей, не мигрирует их и не
переиспользует orphaned-код — Lead представляет собой полностью новую,
чистую сущность, ссылающуюся на Person только опционально и только для
чтения (после конверсии).

Это ADR утверждает архитектуру Lead Domain Foundation (Phase 41C) —
один операционный реестр `leads`, Lead-only (без Deal), явная граница
идемпотентности vs. duplicate detection, безопасная conversion-модель
без автоматического создания Client.

### 1. Канонический entity

**Lead** — единственная каноническая сущность Foundation. Представляет
pre-Client коммерческого прospect'а. Принадлежит одному Business.
Хранит контактные снапшоты и sales-состояние. Может ссылаться на
Service, Channel, Assigned Person. Может позже связаться с уже
существующим Client. Остаётся читаемым после конверсии. НЕ является
Person subtype, НЕ является Client, НЕ является Deal, НЕ является
Commercial Offer, НЕ является Roadmap, НЕ является Payment-сущностью.

```
LEAD_IS_CANONICAL_PRE_CLIENT_ENTITY = YES
LEAD_IS_SEPARATE_FROM_PERSON = YES
LEAD_IS_SEPARATE_FROM_CLIENT = YES
LEAD_IS_NOT_DEAL = YES
LEAD_IS_NOT_COMMERCIAL_OFFER = YES
LEAD_IS_NOT_ROADMAP = YES
LEAD_IS_NOT_PAYMENT_ENTITY = YES
```

### 2. Решение Lead-only

Утверждено: один Lead entity, без отдельного Deal в Foundation.

Обоснование: post-conversion opportunity lifecycle уже полностью
представлен цепочкой Object → Roadmap → Commercial Offer → Payment (все
закрыты и работают). Deal дублировал бы уже существующую операционную
истину post-conversion. Lead закрывает исключительно pre-Client пробел.

```
LEAD_DEAL_ENTITY_REQUIRED_IN_FOUNDATION = NO
```

### 3. Дизайн реестра

Утверждён ровно один Foundation registry: **`leads`**.

```
Lead ID
Business ID
Caller Idempotency Key
Contact Name Snapshot
Phone Snapshot
WhatsApp Snapshot
Email Snapshot
Company Snapshot
Service ID
Source
Channel ID
Status
Qualification Notes
Disposition Reason
Expected Value
Currency
Next Follow-up At
Last Contacted At
Assigned Person ID
Converted Client ID
Converted At
Converted By
Created At
Created By
Updated At
Archived At
Notes
```

Отклонение от предложенного набора: поле `Loss Reason` из задания
переименовано в **`Disposition Reason`** (решение 20 ниже) — используется
и для `unqualified`, и для `lost`, чтобы не называть все unqualified
Leads "проигранными" ложно.

Явно НЕ добавлено: Deal ID, Object ID, Roadmap ID, Commercial Offer ID,
Payment Obligation ID, Task ID, Interaction history JSON,
comma-separated relation-поля, generic relation JSON, Campaign/UTM-поля,
automatic Client-creation поля, скрытые Person-type поля.

```
LEAD_REGISTRY_APPROVED = YES
```

### 4. Identity policy

```
Lead ID: LED-NNN
```

Проверка коллизий: среди всех существующих `_ID_PREFIXES` (включая
`OFR`/`OFS`/`PMT`/`POB`/`PTXN` из Payment/Offer) — `LED` не пересекается
ни с одним. Ровно один генератор, живёт в `lead_manager.py`. Никакой
caller-side генерации. Malformed ID безопасно игнорируются. ID
генерируются только после полной валидации и idempotency-проверки.
Никакой name/phone/email-based identity. Никакого повторного
использования Person/Client ID.

```
LED_IDENTITY_APPROVED = YES
```

### 5. Persistence ownership

`business_core/lead_manager.py` — единственный persistence owner для
`leads`. Владеет: точечные reads, ограниченные list/filter reads,
генерацию LED, низкоуровневое создание строки, низкоуровневую
персистентность lifecycle-переходов, низкоуровневую персистентность
admin/update-полей, idempotency-lookup примитивы, точные normalized-
contact duplicate-lookup примитивы, immutable-field enforcement,
проверку после записи.

НЕ владеет: cross-domain relation-валидацией, бизнес-решениями по
нормализации контактов сверх утверждённого canonical helper (сама
нормализация — orchestration-функция business_builder, вызываемая ДО
записи; manager лишь хранит уже нормализованное значение), lifecycle
policy, qualification policy, conversion policy, duplicate auto-merge,
Telegram UX, созданием/мутацией Client, мутацией Service/Organization,
raw exception rendering.

```
LEAD_MANAGER_IS_APPROVED_PERSISTENCE_OWNER = YES
```

### 6. Orchestration ownership

`business_builder.py` — единственный cross-domain owner Lead-
оркестрации. Владеет: валидацию обязательных полей, нормализацию
контактных снапшотов (phone/WhatsApp/email), relation-валидацию,
создание Lead, idempotency zero/one/multiple handling, политику
exact-contact duplicate warning, lifecycle-переходы, qualification/
unqualification, lost-переход, conversion к существующему Client,
обновления follow-up, обновления assignment, structured result
assembly.

Направление зависимостей:

```
telegram_handlers
  → business_builder
    → lead_manager
      → sheets
```

Без обратной зависимости.

```
BUSINESS_BUILDER_IS_APPROVED_LEAD_ORCHESTRATION_OWNER = YES
```

### 7. Contact identity policy

Обязательно: `Contact Name Snapshot`. Плюс хотя бы одно из: `Phone
Snapshot`, `WhatsApp Snapshot`, `Email Snapshot`. Опционально: `Company
Snapshot`. Имя — trimmed, ограничено по длине. Phone/WhatsApp —
канонически нормализуются. Email — консервативно нормализуется. Raw
контактные снапшоты хранятся как бизнес-данные, но никогда не
логируются. Никакого fuzzy name matching. Никакого auto-merge.

Phone и WhatsApp могут нормализоваться к одному и тому же
каноническому номеру, но остаются раздельными исходными полями;
duplicate detection может рассматривать совпадающие нормализованные
значения Phone/WhatsApp как совпадение контактного канала — но одно
поле никогда молча не схлопывается в другое.

```
LEAD_CONTACT_NAME_IS_REQUIRED = YES
LEAD_CONTACT_CHANNEL_IS_REQUIRED = YES
```

### 8. Contact normalization

**Phone/WhatsApp**: trim; удаление безопасных форматирующих символов
(пробелы, скобки, дефисы); сохранение ведущего `+` при наличии;
канонический вид — только цифры плюс опциональный ведущий `+`; явно
некорректные значения блокируются; страна НЕ выводится автоматически;
казахстанский `+7` НЕ подставляется молча; никакого substring/fuzzy
сопоставления.

**Email**: trim; понижение регистра (предпочтительно всего значения для
точного сравнения дублей); ровно один `@`; ограниченная длина; никакой
сложной проверки deliverability; никакой исходящей верификации.

**Name/Company**: trimmed, ограничены по длине, никогда не используются
для identity.

```
LEAD_PHONE_NORMALIZATION_IS_APPROVED = YES
LEAD_WHATSAPP_NORMALIZATION_IS_APPROVED = YES
LEAD_EMAIL_NORMALIZATION_IS_APPROVED = YES
```

### 9. Contact duplicate detection

Отдельный механизм, НЕ идемпотентность. Точное совпадение только по
нормализованным Phone/WhatsApp/Email; область действия — в пределах
одного Business; ноль совпадений — без предупреждения; одно или более
совпадений — возвращаются ВСЕ совпадающие Lead ID; никогда не
auto-reuse; никогда не auto-merge; никогда не first-pick; никакого
fuzzy name matching; никакого сопоставления по названию компании;
никакого кросс-Business сопоставления.

Выбрана модель: **A. warning-only** (не blocking). Обоснование: один и
тот же контакт может законно оставить несколько разных заявок для
разных услуг или периодов; детерминированная идемпотентность уже
предотвращает retry-дубли; предупреждение информирует caller, не
портя историю продаж принудительным блоком.

```
LEAD_CONTACT_DUPLICATE_WARNING_IS_APPROVED = YES
LEAD_CONTACT_DUPLICATE_AUTO_MERGE_IS_ALLOWED = NO
LEAD_FUZZY_NAME_DEDUP_IS_ALLOWED = NO
```

### 10. Idempotency policy

Primary key: `Business ID` + `Caller Idempotency Key`. Caller key
обязателен; zero creates; один совместимый match — reuse; несколько
matches — блок с полным списком конфликтующих Lead ID; несовместимый
payload с тем же ключом — блок; никакого first-pick; никакого
contact-channel-based reuse; никакого name-based reuse; никакого
amount/date/source-based dedup. ID генерируется только после проверки
идемпотентности.

Идемпотентность и duplicate detection принципиально разделены: первая
защищает от повторных запросов одного и того же caller (retry-safe
создание), вторая — информационное предупреждение о потенциально том
же человеке через другой канал/повод обращения.

```
LEAD_IDEMPOTENCY_IS_DISTINCT_FROM_DUPLICATE_DETECTION = YES
```

### 11. Source/Channel policy

`Source` — опциональный ограниченный scalar-строка; не controlled
vocabulary; не отдельный реестр в Foundation; никогда не используется
как identity; никакого Campaign/UTM-движка. `Channel ID` — опциональная
read-only связь с существующим `channel_registry`; точная проверка
существования; никакой мутации канала; никакого runtime-поведения
интеграции.

Source не обязателен — его отсутствие не блокирует создание Lead.

```
LEAD_SOURCE_REGISTRY_REQUIRED_IN_FOUNDATION = NO
LEAD_CHANNEL_IS_REFERENCE_ONLY = YES
```

### 12. Relation policy

Обязательно: `Business ID`. Опционально: `Service ID`, `Channel ID`,
`Assigned Person ID`, `Converted Client ID` (только через conversion).
Правила: Business должен существовать; Service существует при указании;
Channel существует при указании; Assigned Person существует и
принадлежит Business там, где текущие canonical данные это
поддерживают; Converted Client существует, является валидным Client и
принадлежит тому же Business. Никакой Object-связи. Никакой
Roadmap-связи. Никакой Commercial Offer-связи. Никакой Payment-связи.
Никакой Task-связи. Никакого auto-repair. Никакого движения между
Business. Никакой мутации любого связанного домена.

### 13. Expected Value policy

Включено, но ограничено и явно некономично: опциональные `Expected
Value` + `Currency`. Оба поля — либо вместе пусты, либо вместе
заполнены. `Expected Value` — некономичная оценка продаж, никогда не
становится agreed-price истиной. Decimal only, ровно 2 дробных знака,
значение `> 0`, явная 3-буквенная валюта в верхнем регистре, никакой
FX-конвертации, никакого автоматического переноса в Commercial Offer
или Payment, никакой валидации против диапазона цены Service.

```
LEAD_EXPECTED_VALUE_IS_INCLUDED = YES
LEAD_EXPECTED_VALUE_IS_CANONICAL_COMMERCIAL_AMOUNT = NO
LEAD_EXPECTED_VALUE_USES_DECIMAL = YES
```

### 14. Follow-up policy

`Next Follow-up At` — опционально. `Last Contacted At` — опционально.
`Assigned Person ID` — опционально. `Qualification Notes` — опционально.
`Notes` — опционально. Никакого автоматического создания Task. Никакого
Reminder-реестра. Никакого scheduler. Никакой Calendar-интеграции.
Никакой мутации Task. "follow-up due" — derived at read-time, никогда
не хранится отдельным полем. Таймстампы — детерминированный ISO
datetime формат, никакой timezone-неоднозначности.

`Last Contacted At` может обновляться независимо от lifecycle через
ограниченный Lead update API — обновление этого поля само по себе НЕ
меняет Status; lifecycle остаётся явным отдельным действием.

```
LEAD_FOLLOW_UP_IS_STORED_ON_LEAD = YES
LEAD_AUTOMATIC_TASK_CREATION_IS_FOUNDATION_SCOPE = NO
```

### 15. Interaction-history boundary

Никакого Interaction registry в Foundation. Никакого переиспользования
`RelationshipTouch`. Никакой записи в `relationship_capital`. Никакой
таблицы истории сообщений/звонков. Никакого счётчика попыток контакта.
Lead Foundation хранит только: `Last Contacted At`, `Next Follow-up At`,
опциональные `Qualification Notes`. Полноценный Interaction Domain
остаётся отложенным.

```
LEAD_INTERACTION_REGISTRY_IS_FOUNDATION_SCOPE = NO
```

### 16. Lifecycle vocabulary

```
new
contacted
qualified
unqualified
converted
lost
archived
```

Не добавлены: `won`, `follow_up_due`, `nurturing`, `dormant`,
`customer`, `offer_sent`, `paid` — все они либо derived (follow_up_due),
либо дублируют `converted` (won), либо принадлежат другим доменам.

```
LEAD_STATUS_VOCABULARY_IS_APPROVED = YES
```

### 17. Lifecycle matrix

```
new:          new, contacted, qualified, unqualified, lost, converted, archived
contacted:    contacted, qualified, unqualified, lost, converted, archived
qualified:    qualified, contacted, unqualified, lost, converted, archived
unqualified:  unqualified, archived
converted:    converted, archived
lost:         lost, archived
archived:     archived (только)
```

Прямой `new → converted` РАЗРЕШЁН: некоторые заявки могут иметь уже
существующего Client на момент захвата (например, повторное обращение
существующего клиента через новый канал, до того как это распознано
вручную) — conversion остаётся явной и валидируется точно так же, как
из любого другого статуса.

Правила: тот же статус — no-op; `archived` терминален; никакого
ordinary restore; никакого hard delete; никакого `converted → active`;
никакого reopen из `lost`/`unqualified`. Будущее повторное обращение
создаёт НОВУЮ запись Lead, не reopen старой.

```
LEAD_TRANSITION_MATRIX_IS_APPROVED = YES
```

### 18. Qualification policy

`qualified` — явный переход, `Qualification Notes` не обязательны.
`unqualified` — явный переход, требует причину.

Решено: поле переименовано из `Loss Reason` в **`Disposition Reason`**,
используется и для `unqualified`, и для `lost` — единое поле,
избегающее ложного называния всех unqualified Leads "проигранными".
Причина обязательна для обоих терминальных исходов, никогда не
логируется, отдельного дублирующего поля причины нет.

```
LEAD_DISPOSITION_REASON_IS_REQUIRED = YES
```

### 19. Conversion policy

Lead может перейти в `converted`. `Converted Client ID` обязателен.
`Converted By` обязателен. `Converted At` устанавливается один раз.
Целевой Client должен уже существовать, быть валидным Client и
принадлежать тому же Business. Никакого автоматического создания
Person. Никакой мутации Client. Никакого обновления Person `Тип`.
Никакого создания Object/Roadmap/Commercial Offer. Никакого создания
Payment. Converted Lead остаётся читаемым и исторически нетронутым.
Будущие обновления ограничены Notes/archive согласно admin policy.

Выбрана модель: **A. lifecycle conversion естественно идемпотентна по
текущему статусу и целевому Client, без отдельного хранимого ключа.**
Повторная попытка конвертации в тот же Client — безопасный no-op.
Попытка конвертации в ДРУГОЙ Client после того, как Lead уже
конвертирован, блокируется (`LEAD_CONVERSION_TARGET_CONFLICT`). Второе
поле идентичности не требуется.

```
LEAD_AUTOMATIC_CLIENT_CREATION_IS_FOUNDATION_SCOPE = NO
LEAD_CONVERSION_REQUIRES_EXISTING_CLIENT = YES
LEAD_CONVERSION_MUTATES_CLIENT = NO
```

### 20. Converted Lead immutability

После конвертации неизменны: Business ID, контактные снапшоты, Service
ID, Source, Channel ID, Assigned Person ID, Expected Value/Currency,
Converted Client ID, метаданные конверсии, Created At/By, Caller
Idempotency Key. Разрешено после конверсии: Notes, archive, Updated At.
Никакого generic update bypass.

```
CONVERTED_LEAD_IS_IMMUTABLE = YES
```

### 21. Lost/unqualified policy

Причина (`Disposition Reason`) обязательна; сохраняется один раз при
переходе; никакого reopen; новое обращение того же контакта создаёт
новый Lead; exact-contact duplicate warning может ссылаться на
исторический lost/unqualified Lead, но не auto-reuse его.

### 22. Archive policy

Archive терминален. Никакого hard delete. Никакого ordinary restore.
Точный-ID read по-прежнему возвращает архивированную запись.
Архивированные записи исключены из активных списков по умолчанию.
Никакого каскада. Никакой мутации связанного домена.

```
LEAD_HARD_DELETE_IS_FOUNDATION_SCOPE = NO
LEAD_RESTORE_REOPEN_IS_FOUNDATION_SCOPE = NO
```

### 23. Update policy

Изменяемые поля, пока Lead активен (`new`/`contacted`/`qualified`):
Contact Name/Phone/WhatsApp/Email/Company Snapshot, Service ID, Source,
Channel ID, Qualification Notes, Expected Value, Currency, Next
Follow-up At, Last Contacted At, Assigned Person ID, Notes. Все
переданные значения перепроверяются. Identity/Business/Caller
Idempotency Key/Status/conversion/audit-поля блокируются. После
терминального disposition (unqualified/lost/converted/archived) —
изменяемы только Notes; исправления контактных данных должны
происходить до терминального перехода; будущее обращение создаёт новый
Lead. No-op сохраняет Updated At неизменным.

### 24. Person/Client overlap boundary

Явно зафиксировано: поля Person/Client остаются нетронутыми; никакой
миграции из `people_registry`; никакого dual-write в Person; поля
Lead's Source/Follow-up/Contact применяются ТОЛЬКО к pre-conversion
sales-истории; после конверсии поля Lead остаются историческими
снапшотами; текущее отслеживание отношений с Client продолжается
исключительно в Person/Client; никакой синхронизации между Lead и
Person; никакого переиспользования персистентности `person_manager`;
никакой мутации Person `Тип`, `Источник`, `История`, `Следующее
касание` или полей отношений.

```
LEAD_PERSON_FIELDS_ARE_MUTATED = NO
LEAD_MIGRATION_FROM_PEOPLE_REGISTRY_REQUIRED = NO
```

### 25. relationship_capital boundary

Явно утверждено: orphaned-модель `RelationshipTouch` не переиспользуется;
реестр `relationship_capital` не записывается; никакого TCH ID;
никакой миграции; никакой очистки в Phase 41C. Будущий Interaction
Domain может отдельно решить судьбу этого orphaned-кода — вне рамок
этого ADR.

```
RELATIONSHIP_CAPITAL_IS_REUSED_BY_LEAD = NO
```

### 26. Структурированный result contract

```
ok, code, error,
lead_id, business_id, service_id, channel_id, assigned_person_id, converted_client_id,
previous_status, requested_status, final_status,
created, reused, changed,
contacted, qualified, unqualified, converted, lost, archived,
expected_value, currency, next_follow_up_at, last_contacted_at,
duplicate_contact_ids, conflicting_ids, warnings, retry_safe
```

`expected_value`/`currency`/`next_follow_up_at`/`last_contacted_at`
включены — вызывающей стороне нужны безопасные операционные выводы, и
это не чувствительные контактные данные. Никаких phone/email/name/
company-полей в result contract. Каждое поле присутствует всегда.
Никакого raw exception. Никакого raw row. Никакого Telegram-
специфичного текста в Foundation.

```
LEAD_RESULT_CONTRACT_APPROVED = YES
```

### 27. Result-code vocabulary

Утверждены как канонические (без синонимов), реализуются в Phase 41C
только там, где есть реальный runtime-вызов:

```
Создание/idempotency:
  LEAD_CREATED
  LEAD_REUSED
  LEAD_NOT_FOUND
  MULTIPLE_LEAD_MATCHES
  LEAD_IDEMPOTENCY_REQUIRED
  LEAD_IDEMPOTENCY_CONFLICT
  LEAD_PERSISTENCE_FAILED
  LEAD_POST_WRITE_VERIFICATION_FAILED

Validation:
  LEAD_CONTACT_NAME_REQUIRED
  LEAD_CONTACT_CHANNEL_REQUIRED
  INVALID_LEAD_PHONE
  INVALID_LEAD_WHATSAPP
  INVALID_LEAD_EMAIL
  INVALID_LEAD_EXPECTED_VALUE
  INVALID_LEAD_EXPECTED_VALUE_SCALE
  LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE
  INVALID_LEAD_CURRENCY
  INVALID_LEAD_DATETIME
  LEAD_DISPOSITION_REASON_REQUIRED

Relations:
  BUSINESS_NOT_FOUND
  SERVICE_NOT_FOUND
  CHANNEL_NOT_FOUND
  PERSON_NOT_FOUND
  CLIENT_NOT_FOUND
  LEAD_RELATION_MISMATCH

Duplicates:
  LEAD_CONTACT_DUPLICATE_WARNING

Lifecycle:
  INVALID_LEAD_STATUS
  INVALID_LEAD_TRANSITION
  LEAD_STATUS_UPDATED
  LEAD_STATUS_UNCHANGED
  LEAD_CONTACTED
  LEAD_QUALIFIED
  LEAD_UNQUALIFIED
  LEAD_CONVERTED
  LEAD_LOST
  LEAD_ARCHIVED
  LEAD_CONVERSION_CLIENT_REQUIRED
  LEAD_CONVERSION_ACTOR_REQUIRED
  LEAD_CONVERSION_TARGET_CONFLICT
  LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION

Admin update:
  LEAD_UPDATED
  LEAD_UPDATE_UNCHANGED
  LEAD_IMMUTABLE
```

Phase 41C не обязан реализовывать коды без реального runtime-callable
в bounded scope (тот же принцип, что закрыл находку Phase 37F).

### 28. Privacy и логирование

Разрешено в логах: Lead ID, Business ID, Service/Channel/Assigned
Person/Converted Client ID, result code, статус, count и ID дублей,
ожидаемая валюта/значение только при необходимости, флаги
created/reused/changed, `retry_safe`.

Запрещено в логах: Contact Name Snapshot, Phone Snapshot, WhatsApp
Snapshot, Email Snapshot, Company Snapshot, Qualification Notes,
Disposition Reason, Notes, полное тело Telegram-сообщения, raw row, raw
exception, credentials/токены.

```
LEAD_PRIVACY_LOGGING_POLICY_APPROVED = YES
```

### 29. Тестовые требования для Phase 41C

Обязательные изолированные категории: schema (точные заголовки `leads`,
отсутствие мутации существующей схемы); identity (генерация LED,
malformed игнорируются, отсутствие caller-side генерации, генерация
после validation/idempotency); contact validation (обязательность
имени, обязательность хотя бы одного канала, нормализация phone/
WhatsApp/email, отсутствие вывода кода страны, ограниченные поля);
idempotency (zero/one/multiple, совместимый reuse, несовместимый
conflict, отсутствие contact-based/fuzzy/name-based reuse, отсутствие
first-pick); duplicate warning (точное совпадение normalized phone/
WhatsApp/email, несколько совпадающих ID, только предупреждение, без
auto-merge, без кросс-Business детекции); relations (Business/Service/
Channel/Assigned Person/Converted Client, same-Business, отсутствие
мутации связанных доменов); expected value (Decimal, scale,
positivity, явная валюта, both-or-neither, некономичность, отсутствие
переноса в Offer/Payment); follow-up (детерминированный datetime,
derived due-статус, отсутствие мутации Task/Reminder/Calendar);
lifecycle (все разрешённые переходы, все запрещённые переходы, no-op,
disposition reason, валидация conversion, конфликт конверсионной цели,
отсутствие reopen, archive терминален); conversion (только существующий
Client, отсутствие создания Client, отсутствие мутации Person, повторная
конверсия в тот же Client — no-op, конверсия в другой Client после уже
состоявшейся — блок, читаемость Lead после конверсии, неизменность
после конверсии); updates (изменяемость активных полей, неизменность
терминальных, политика Notes, no-op таймстампы, блокировка identity/
audit полей); boundaries (отсутствие Deal, отсутствие Interaction
registry, отсутствие записи в relationship_capital, отсутствие мутации
Object/Roadmap/Offer/Payment/Task, отсутствие auto-create Client,
отсутствие миграции people_registry); isolation (все Lead-тесты — hard
socket-block, mock-completeness guard, отсутствие live Sheets/Drive/
Telegram/Railway/HTTP/socket).

### 30. Production migration policy

Никакой миграции. Никакого backfill из `people_registry`. Никаких
legacy Lead-строк. Существующие Client остаются без изменений. Реестр
Lead начинается пустым. Никакого создания production Lead-строк во
время тестов Phase 41C. Никакого изменения схемы Person. Никакой
очистки `relationship_capital`.

### 31. Bounded scope Phase 41C

Phase 41C реализует ТОЛЬКО: одну схему registry `leads` (в коде); LED
identity; `lead_manager.py`; нормализацию контактов; опциональную
нормализацию Expected Value/currency; детерминированную нормализацию
datetime; точные reads и ограниченные фильтры; создание Lead;
idempotency; exact-contact duplicate warning; обновления активного
Lead; lifecycle-переходы; conversion к существующему Client;
follow-up-поля; assignment-связь; immutability; структурированный
result contract; architecture/isolation guards; тесты.

Явно запрещено в Phase 41C: Telegram caller UX; деплой; Deal-сущность;
автоматическое создание Client; миграция people_registry; изменения
схемы Person; связь с Object/Roadmap/Commercial Offer; создание Offer;
создание Payment; создание Task; интеграция Reminder/Calendar;
Interaction registry; изменения relationship_capital; Campaign/UTM-
модель; внешние CRM-интеграции; hard delete; restore/reopen.

### 32. Отклонённые альтернативы

**A. Lead как Person subtype.** Отклонено: переоткрывает Client Domain
и перегружает семантику типа Person.

**B. Lead как Client с другим статусом.** Отклонено: теряет pre-Client
границу и смешивает владение жизненным циклом.

**C. Автоматическое создание Client при конверсии.** Отклонено:
переоткрывает закрытую персистентность Client и вносит риск
дублирования клиентов.

**D. Lead + Deal в Foundation.** Отклонено: Deal дублирует
post-conversion жизненный цикл Roadmap/Offer/Payment.

**E. Auto-merge по контактному каналу.** Отклонено: один и тот же
контакт может законно иметь несколько Lead.

**F. Fuzzy name dedup.** Отклонено: недетерминированно и небезопасно.

**G. Полная история Interaction в Lead Foundation.** Отклонено:
отдельный домен, больший объём.

**H. Campaign/UTM-атрибуция в Foundation.** Отклонено: нет
доказательств в репозитории.

**I. Автоматическое создание Task/Reminder.** Отклонено: переоткрыло
бы Task или ввело бы Automation-объём.

**J. Миграция из people_registry.** Отклонено: существующие строки —
это Client, поля Source неструктурированы, надёжного backfill не
существует.

### 33. Cross-ADR consistency

Проверено на отсутствие противоречий с решениями по Client, Organization
ADR-018, Task ADR-019, Document ADR-020, Checklist ADR-021, Payment
ADR-022, Commercial Offer ADR-023, Service/Object/Roadmap/Stage
closed-domain решениями. Ни один закрытый домен не мутируется Lead
Foundation — Lead ссылается на их ID только для чтения/валидации
существования, тем же паттерном, что уже используют все предыдущие
домены этого engagement.

### 34. Статус

Утверждено для реализации (Phase 41C) с bounded scope, определённым в
решении 31. Ничего не реализовано в рамках этого ADR — только
архитектурное решение. `lead_manager.py` не создан; `leads` не
существует; ни один production-caller не мигрирован; ни один код не
изменён; схема Google Sheets не менялась; GTD Core не затронут. Ни один
закрытый домен (Object/Client/Service/Roadmap/Stage/Organization/Task/
Document/Checklist/Payment/Commercial Offer) не переоткрыт.


## ADR-025 — Interaction / Communication History Domain Architecture Decision (Phase 42B)

### 0. Контекст

Phase 42A (Next Domain Selection Audit) переоценила оставшиеся домены
после закрытия Lead/Sales Funnel и рекомендовала Interaction /
Communication History с решением **GO WITH PREREQUISITE** — не
отдельная Phase 42A.1, а два явных решения, зафиксированных прямо в
этом ADR: (1) ключ реестра не должен быть `interactions` /
`interaction_registry` / `lead_interactions` — эти строки уже явно
запрещены существующими Lead architecture guard-тестами
(`test_lead_manager.py`, `test_lead_architecture_guards.py`); (2)
основной субъект связи должен быть ровно один — Lead XOR Client, без
одновременного присутствия обоих.

Аудит подтвердил: `relationship_capital.py`/`RelationshipTouch` —
полностью нерабочий (orphaned) код, чья схема (`RelationshipTouch.
to_dict()`: `id/person_id/touch_date/touch_type/channel/summary/
outcome/warmth_before/warmth_after/created_at`) структурно
несовместима с фактическими заголовками реестра `relationship_capital`
(`PRS ID/ФИО/Теплота/Дни без контакта/Тип касания/Дата касания/Общие
интересы/Чем помог мне/Чем я помог/Кого познакомить/Через кого решить/
Контент для него`). Реестр не имеет записи в `_ID_PREFIXES`. Ни одного
живого вызывающего кода нет ни в `business_builder.py`, ни в
`telegram_handlers.py`. Это ADR явно фиксирует: Interaction Domain НЕ
переиспользует и не чинит этот orphaned-код — Interaction представляет
собой полностью новую, чистую сущность.

Это ADR утверждает архитектуру Interaction Foundation (Phase 42C) —
один канонический immutable-event реестр `interaction_log`, с ровно
одним обязательным основным субъектом (Lead XOR Client), опциональными
context-связями, закрытым словарём типов, и immutable-факт моделью с
архивом как единственным допустимым переходом.

### 1. Канонический entity

**Interaction** — единственная каноническая сущность Foundation.
Immutable-событие, фиксирующее один содержательный контакт/
коммуникацию с одним бизнес-субъектом. Channel-neutral (тип канала —
отдельное поле, не часть идентичности события). Историческое —
остаётся читаемым после архивации. Принадлежит одному Business. Имеет
ровно один основной субъект (Lead или Client). Может нести
опциональные context-связи.

Interaction НЕ является: техническим Audit Event; записью доставки
сообщения (Message delivery record); Appointment; Task; Reminder;
обновлением статуса Lead; сводкой отношений Client; RelationshipTouch;
generic системным Activity Log.

```
INTERACTION_IS_CANONICAL_BUSINESS_COMMUNICATION_EVENT = YES
INTERACTION_IS_SEPARATE_FROM_AUDIT_EVENT = YES
INTERACTION_IS_SEPARATE_FROM_MESSAGE_DELIVERY = YES
INTERACTION_IS_SEPARATE_FROM_TASK = YES
INTERACTION_IS_SEPARATE_FROM_REMINDER = YES
INTERACTION_REUSES_RELATIONSHIP_TOUCH = NO
```

### 2. Legacy relationship_capital boundary

Явно зафиксировано: `RelationshipTouch` — несовместимый legacy-код;
схема `relationship_capital` не соответствует модели
`RelationshipTouch`; канонического persistence-пути не существует; ни
одна production-миграция не требуется; TCH-идентичность не
переиспользуется; `relationship_capital` не записывается; файл
`relationship_capital.py` остаётся нетронутым; в Foundation нет
compatibility-адаптера; в Phase 42C нет очистки orphaned-кода; будущая
очистка legacy-кода потребует отдельной фазы.

```
INTERACTION_REUSES_TCH_IDENTITY = NO
INTERACTION_WRITES_RELATIONSHIP_CAPITAL = NO
INTERACTION_MIGRATION_FROM_RELATIONSHIP_CAPITAL_REQUIRED = NO
```

### 3. Registry naming prerequisite — решение

Ключ реестра НЕ может быть `interactions`, `interaction_registry` или
`lead_interactions` — эти строки уже явно запрещены существующими Lead
architecture guard-тестами (`test_lead_manager.py::
test_no_interaction_registry`, `test_lead_architecture_guards.py::
test_no_deal_interaction_campaign_registry_exists`). Ослабление или
удаление этих guard-тестов ради использования запрещённого имени
недопустимо.

Утверждённый ключ реестра: **`interaction_log`**.

Человеческий смысл: канонический реестр Interaction.

```
INTERACTION_REGISTRY_KEY_APPROVED = YES
INTERACTION_REGISTRY_KEY_AVOIDS_LEAD_GUARD_COLLISION = YES
INTERACTION_REGISTRY_USES_PROHIBITED_NAME = NO
```

### 4. Точная схема реестра

Утверждён ровно один Foundation registry: **`interaction_log`**.

```
Interaction ID
Business ID
Caller Idempotency Key
Interaction Type
Direction
Channel ID
Occurred At
Summary
Outcome
Lead ID
Client ID
Commercial Offer ID
Assigned Person ID
External Reference
Status
Created At
Created By
Updated At
Archived At
Notes
```

Явно НЕ добавлены: Object ID, Service ID, Roadmap ID, Payment
Obligation ID, Task ID, Message Body, Email Body, Transcript,
Attachment Content, Provider Payload, generic relation JSON,
comma-separated subject IDs, технические audit-event поля, поля
delivery-статуса, retry count, reminder-поля.

```
INTERACTION_REGISTRY_SCHEMA_APPROVED = YES
```

### 5. Identity policy

```
Interaction ID: ACT-NNN
```

Обоснование выбора префикса: `INT` коллидирует с
`integration_registry` (уже занят в `_ID_PREFIXES`); `TCH` семантически
контаминирован orphaned-кодом `relationship_capital.py`; `ACT` —
свободен и мнемоничен ("Activity" читается естественно как "одно
событие взаимодействия").

Ровно один генератор, живёт в `interaction_manager.py`. Никакой
caller-side генерации. Malformed ID безопасно игнорируются. ID
генерируется только после полной валидации и idempotency-проверки.
Никакой Summary/time-based identity. Никакой provider-ID identity.
Никакого переиспользования Lead/Client ID.

```
ACT_IDENTITY_APPROVED = YES
INT_IDENTITY_REJECTED_DUE_TO_COLLISION = YES
TCH_IDENTITY_REJECTED_DUE_TO_LEGACY_OVERLAP = YES
```

### 6. Persistence ownership

`business_core/interaction_manager.py` — единственный persistence
owner для `interaction_log`. Владеет: точечные reads, ограниченные
list/filter reads, генерацию ACT, низкоуровневое создание строки,
персистентность архивации, персистентность Notes-only обновления,
idempotency-lookup примитивы, immutable-field enforcement, проверку
после записи.

НЕ владеет: cross-domain relation-валидацией, subject-policy
решениями, lifecycle policy, business-валидацией временных меток,
Telegram UX, мутацией Person/Lead, созданием Task/Reminder, поведением
Audit Log, relationship_capital compatibility, raw exception
rendering.

```
INTERACTION_MANAGER_IS_APPROVED_PERSISTENCE_OWNER = YES
```

### 7. Orchestration ownership

`business_builder.py` — единственный cross-domain owner Interaction-
оркестрации. Владеет: валидацию обязательных полей, валидацию
Interaction Type, валидацию Direction, валидацию Occurred At,
валидацию Summary/Outcome, XOR-валидацию основного субъекта,
relation-валидацию Lead/Client, опциональную валидацию Commercial
Offer, опциональную валидацию Channel, опциональную валидацию Assigned
Person, создание, idempotency zero/one/multiple handling, архивацию,
обновление Notes, сборку структурированного результата.

Направление зависимостей:

```
telegram_handlers
  → business_builder
    → interaction_manager
      → sheets
```

Без обратной зависимости.

```
BUSINESS_BUILDER_IS_APPROVED_INTERACTION_ORCHESTRATION_OWNER = YES
```

### 8. Primary subject policy

Обязательное решение. Утверждён ровно один основной субъект: **Lead ID
XOR Client ID**.

Правила: ровно один должен присутствовать; отсутствие обоих блокирует
(`INTERACTION_SUBJECT_REQUIRED`); присутствие обоих блокирует
(`INTERACTION_SUBJECT_CONFLICT`); Business ID должен совпадать с
Business выбранного субъекта; никакого произвольного выбора основного
субъекта; никакой автоматической конверсии Lead → Client; никакого
автоматического перепривязывания после конверсии Lead. Interactions,
записанные до конверсии, могут ссылаться на Lead; записанные после —
должны ссылаться на Client. Foundation не мутирует и не инспектирует
историю конверсии Lead сверх точной relation-валидации. Никакого
multi-subject fan-out.

```
INTERACTION_ONE_PRIMARY_SUBJECT_POLICY_IS_CLEAR = YES
INTERACTION_REQUIRES_EXACTLY_ONE_OF_LEAD_OR_CLIENT = YES
```

### 9. Optional context relations

Утверждены опциональные read-only связи: Commercial Offer ID, Channel
ID, Assigned Person ID. Правила: точная проверка существования;
same-Business проверка; никакой мутации связанного домена; Commercial
Offer остаётся опциональным контекстом (без автоматического
обновления статуса Offer); никакой автоматической мутации Lead/Client;
никакой мутации Organization; никакой мутации Channel.

Явно отложены: Object ID, Service ID, Roadmap ID, Payment Obligation
ID, Task ID — текущие данные репозитория не подтверждают
необходимость этих связей в Foundation.

```
INTERACTION_COMMERCIAL_OFFER_IS_REFERENCE_ONLY = YES
INTERACTION_CHANNEL_IS_REFERENCE_ONLY = YES
INTERACTION_ASSIGNED_PERSON_IS_REFERENCE_ONLY = YES
```

### 10. Converted Lead boundary

Interactions, записанные до конверсии Lead, могут ссылаться на Lead;
записанные после конверсии — должны ссылаться на Client. Никакого
автоматического перепривязывания. Никакой ретроактивной перезаписи.
Никакой одновременной связи Lead+Client. Никакой мутации Lead.
Никакой мутации Client. Исторические Lead-interactions остаются
привязанными к Lead. Это документационная норма и ответственность
вызывающей стороны — не автоматическая migration-логика Foundation.

### 11. Interaction Type vocabulary

Утверждено ровно:

```
call
message
email
meeting
note
other
```

WhatsApp/Telegram — значения Channel, не Interaction Type. Никаких
системно-сгенерированных audit-событий. Никакого типа "обмен
документами". Никакого типа "follow_up_due". Никакого типа
delivery-статуса.

```
INTERACTION_TYPE_VOCABULARY_IS_APPROVED = YES
```

### 12. Direction policy

Утверждены закрытые значения: `inbound`, `outbound`, `internal`.

Решение: Direction обязателен для `call`/`message`/`email`/`meeting`;
для `note` — не обязателен, но при явном указании допустимо только
`internal`; никакого неявного значения по умолчанию ни для одного
типа, включая `other` — для `other` Direction обязателен, как и для
активных коммуникационных типов, поскольку `other` явно не
идентифицирует форму контакта и требует того же уровня строгости.
Caller никогда не получает автоматически подставленное значение
Direction.

```
INTERACTION_DIRECTION_POLICY_IS_APPROVED = YES
```

### 13. Occurred At policy

Обязателен. Timezone-aware ISO-8601/RFC3339 (тот же принцип, что уже
использует `normalize_lead_datetime()` — timezone-naive значения
блокируются). Created At остаётся отдельной audit-меткой времени.
Исторические временные метки разрешены. Нереалистично будущие
временные метки блокируются: значения позже reference-времени плюс
пять минут блокируются (`INTERACTION_OCCURRED_AT_IN_FUTURE`) —
пятиминутный допуск покрывает небольшой рассинхрон часов клиента.
Никакого scheduled-Interaction. Детерминированная инъекция
reference-времени обязательна для тестов.

```
INTERACTION_OCCURRED_AT_IS_REQUIRED = YES
INTERACTION_OCCURRED_AT_REQUIRES_TIMEZONE = YES
```

### 14. Summary/content policy

Это приватность-чувствительное решение.

**Summary**: обязателен; trimmed; ограничен; пустое после trim
блокирует. Максимум: 2000 символов.

**Outcome**: опционален; trimmed; ограничен. Максимум: 1000 символов.

**Notes**: опционален; изменяем после создания; ограничен. Максимум:
5000 символов.

**External Reference**: опционален; ограничен; рассматривается как
чувствительный операционный идентификатор; не идентичность; никогда не
логируется; никакого provider-специфичного парсинга.

Не хранится: полное тело сообщения; транскрипт; сырое тело письма;
транскрипция аудио; содержимое вложений; provider payload;
credentials/токены.

```
INTERACTION_SUMMARY_IS_REQUIRED = YES
INTERACTION_FULL_MESSAGE_CONTENT_IS_FOUNDATION_SCOPE = NO
```

### 15. Idempotency policy

Primary key: `Business ID` + `Caller Idempotency Key`. Caller key
обязателен; zero creates; один совместимый match — reuse; несколько
matches — блок со всеми Interaction ID; несовместимый payload с тем же
ключом — блок; никакого first-pick; никакого Summary/time dedup;
никакого External Reference dedup в Foundation; никакого
channel-provider dedup. ACT генерируется только после проверки
идемпотентности.

```
INTERACTION_IDEMPOTENCY_IS_CANONICAL = YES
```

### 16. External Reference policy

Утверждено: опциональный scalar; некономичен; не идентичность; не
используется для автоматического dedup; никакой гарантии
уникальности; никакого provider-адаптера; никакой
Telegram/WhatsApp/email платформенной логики; никогда не логируется;
точный фильтр может быть отложен.

Обоснование: внешние provider-идентификаторы требуют отдельных
интеграционных правил и не могут быть безопасно обобщены в Foundation.

```
INTERACTION_EXTERNAL_REFERENCE_IS_IDENTITY = NO
```

### 17. Lifecycle model

Утверждена минимальная immutable-event модель.

```
active
archived
```

Создание: Status = active.

```
active:   active, archived
archived: archived только
```

Правила: тот же статус — no-op; archived терминален; никакого
restore/reopen; никакого hard delete; никаких
completed/failed/scheduled/cancelled/pending статусов; никакого
delivery-статуса; никакого appointment-статуса.

```
INTERACTION_LIFECYCLE_IS_IMMUTABLE_ARCHIVE_ONLY = YES
INTERACTION_HARD_DELETE_IS_FOUNDATION_SCOPE = NO
INTERACTION_RESTORE_REOPEN_IS_FOUNDATION_SCOPE = NO
```

### 18. Immutable facts

После создания неизменны: Interaction ID, Business ID, Caller
Idempotency Key, Interaction Type, Direction, Channel ID, Occurred At,
Summary, Outcome, Lead ID, Client ID, Commercial Offer ID, Assigned
Person ID, External Reference, Created At, Created By.

Изменяемы: Notes; Status только через архивацию; Updated At; Archived
At. Никакого generic update bypass.

```
INTERACTION_FACTS_ARE_IMMUTABLE = YES
INTERACTION_NOTES_ARE_MUTABLE = YES
```

### 19. Correction policy

Утверждено: никакого редактирования Interaction-фактов; никакой
correction-in-place; исправление создаёт новый Interaction; Notes могут
пояснять исправление; исходная запись остаётся исторической; никакого
relation relinking; никакой мутации субъекта; никакой мутации Occurred
At.

### 20. Archive policy

active → archived; Archived At устанавливается один раз; терминален;
никакого hard delete; никакого restore; точный-ID read по-прежнему
возвращает архивированную запись; активные списки исключают
архивированные по умолчанию; никакого каскада; никакой мутации
Lead/Client/Offer.

### 21. Notes policy

Notes изменяемы в статусах active и archived; Notes никогда не
логируются; обновление Notes не меняет факты или lifecycle Interaction;
Updated At меняется только при фактическом изменении; no-op сохраняет
Updated At.

### 22. Channel policy

Channel ID: опционален; точная read-only связь с `channel_registry`;
same-Business проверка; никакой мутации канала; никакого вызова
интеграции; не требуется, чтобы каждый Interaction имел Channel ID —
`meeting`/`note` могут законно не иметь Channel ID.

### 23. Assigned Person policy

Assigned Person ID: опционален; точная read-only связь с
Person/Organization; same-Business валидация там, где это допускают
canonical данные; представляет бизнес-ответственность/владение.
Created By остаётся фактическим актором создания. Никакой мутации
Organization/Person.

### 24. Person/Client overlap boundary

Явно зафиксировано: никакой мутации `people_registry`; никаких
изменений схемы Person; никакого автоматического обновления полей
"Дата последнего контакта", "Канал последнего контакта", "История",
"Следующее касание", "Тип касания", "Заметка касания", "Статус
отношений", "Теплота", "Комментарий"; никакого dual-write; никакой
миграции/backfill; будущая синхронизация требует отдельного
интеграционного ADR/фазы.

```
INTERACTION_MUTATES_PERSON_CONTACT_FIELDS = NO
```

### 25. Lead overlap boundary

Явно зафиксировано: никакой мутации Lead "Last Contacted At"; никакой
мутации Lead "Next Follow-up At"; никакого изменения статуса Lead;
никакой мутации Qualification Notes; никакого создания Task/Reminder;
никакого автоматического создания Interaction из жизненного цикла
Lead; никакого автоматического обновления Lead из создания
Interaction. Будущая синхронизация требует отдельной интеграционной
фазы.

```
INTERACTION_MUTATES_LEAD_FOLLOW_UP_FIELDS = NO
INTERACTION_MUTATES_LEAD_STATUS = NO
INTERACTION_AUTOMATIC_TASK_CREATION_IS_FOUNDATION_SCOPE = NO
```

### 26. Audit Log separation

Interaction фиксирует человеческие/бизнес-коммуникационные события.
Audit Event фиксировал бы: создание сущности, мутацию статуса, вызов
команды, технические/системные изменения.

Они остаются раздельными, потому что: разная приватность (Summary —
бизнес-чувствителен; Audit-метаданные — структурны); разные
потребители (sales/ops персонал vs. compliance/engineering); разный
объём и паттерн записи; Audit Log потребовал бы hooks во ВСЕХ уже
закрытых доменах — прямое переоткрытие каждого закрытого orchestration
пути. Никакого Audit Event registry в Foundation.

```
INTERACTION_AUDIT_EVENT_REGISTRY_IS_FOUNDATION_SCOPE = NO
```

### 27. Структурированный result contract

```
ok, code, error,
interaction_id, business_id, lead_id, client_id, commercial_offer_id,
channel_id, assigned_person_id,
interaction_type, direction, occurred_at,
previous_status, requested_status, final_status,
created, reused, changed, archived,
conflicting_ids, warnings, retry_safe
```

Каждое поле присутствует всегда. Никакого Summary. Никакого Outcome.
Никакого Notes. Никакого External Reference. Никакого raw exception.
Никакого raw row. Никакого Telegram-специфичного текста в Foundation.

```
INTERACTION_RESULT_CONTRACT_APPROVED = YES
```

### 28. Result-code vocabulary

```
Создание/idempotency:
  INTERACTION_CREATED
  INTERACTION_REUSED
  INTERACTION_NOT_FOUND
  MULTIPLE_INTERACTION_MATCHES
  INTERACTION_IDEMPOTENCY_REQUIRED
  INTERACTION_IDEMPOTENCY_CONFLICT
  INTERACTION_PERSISTENCE_FAILED
  INTERACTION_POST_WRITE_VERIFICATION_FAILED

Validation:
  INTERACTION_TYPE_REQUIRED
  INVALID_INTERACTION_TYPE
  INTERACTION_DIRECTION_REQUIRED
  INVALID_INTERACTION_DIRECTION
  INTERACTION_OCCURRED_AT_REQUIRED
  INVALID_INTERACTION_OCCURRED_AT
  INTERACTION_OCCURRED_AT_IN_FUTURE
  INTERACTION_SUMMARY_REQUIRED
  INTERACTION_SUMMARY_TOO_LONG
  INTERACTION_OUTCOME_TOO_LONG
  INTERACTION_NOTES_TOO_LONG
  INTERACTION_EXTERNAL_REFERENCE_TOO_LONG

Relations:
  BUSINESS_NOT_FOUND
  LEAD_NOT_FOUND
  CLIENT_NOT_FOUND
  COMMERCIAL_OFFER_NOT_FOUND
  CHANNEL_NOT_FOUND
  PERSON_NOT_FOUND
  INTERACTION_SUBJECT_REQUIRED
  INTERACTION_SUBJECT_CONFLICT
  INTERACTION_RELATION_MISMATCH

Lifecycle/admin:
  INVALID_INTERACTION_STATUS
  INVALID_INTERACTION_TRANSITION
  INTERACTION_STATUS_UNCHANGED
  INTERACTION_ARCHIVED
  INTERACTION_NOTES_UPDATED
  INTERACTION_NOTES_UNCHANGED
  INTERACTION_IMMUTABLE
  INTERACTION_RESTORE_REQUIRES_EXPLICIT_ACTION
```

Phase 42C не обязан реализовывать коды для возможностей вне
bounded scope.

### 29. Privacy и логирование

Разрешено в логах: Interaction ID, Business ID, Lead/Client/Offer/
Channel/Assigned Person ID, Interaction Type, Direction, статус,
result code, флаги created/reused/changed/archived, count и ID
конфликтов, retry_safe.

Запрещено в логах: Summary, Outcome, Notes, External Reference,
контактные данные, полное тело Telegram-сообщения, provider payload,
raw row, raw exception, credentials/токены.

```
INTERACTION_PRIVACY_LOGGING_POLICY_APPROVED = YES
```

### 30. Migration policy

Утверждено: никакой production-миграции; никакого backfill из
`relationship_capital`; никакого backfill из `people_registry`
"История"; никакого backfill из полей контакта Lead; существующие
исторические поля остаются нетронутыми; реестр Interaction стартует
пустым; legacy-импорт потребует отдельного ADR/фазы; никакой
деструктивной очистки.

### 31. Тестовые требования Phase 42C

Обязательные изолированные категории: schema (точный ключ реестра,
точные заголовки, отсутствие запрещённых имён, отсутствие мутации
существующей схемы); identity (генерация ACT, malformed игнорируются,
отсутствие INT/TCH генератора, отсутствие caller-side генерации,
генерация после validation/idempotency); subject (только Lead валиден,
только Client валиден, отсутствие обоих блокирует, оба блокируют,
same-Business проверки, отсутствие произвольного выбора субъекта);
relations (опциональные Offer/Channel/Assigned Person, точное
существование, same-Business, отсутствие мутации связанных доменов);
type/direction (закрытый словарь, требования Direction,
WhatsApp/Telegram остаются значениями Channel); Occurred At
(timezone-aware, исторические разрешены, naive блокируются, future
tolerance, детерминированное reference-время); content (Summary
обязателен/ограничен, Outcome ограничен, Notes ограничены, External
Reference ограничен, отсутствие полей тела сообщения); idempotency
(zero/one/multiple, совместимый reuse, несовместимый conflict,
отсутствие Summary/time dedup, отсутствие External Reference dedup,
отсутствие first-pick); lifecycle (active→archived, no-op, archived
терминален, restore заблокирован, отсутствие hard delete);
immutability (факты неизменны, Notes изменяемы, исправления требуют
нового Interaction, отсутствие relinking, отсутствие мутации Occurred
At); boundaries (отсутствие мутации Person, отсутствие мутации Client,
отсутствие мутации Lead, отсутствие мутации Offer, отсутствие
создания Task/Reminder, отсутствие Audit Event, отсутствие
использования relationship_capital, отсутствие импорта
RelationshipTouch, отсутствие TCH identity, отсутствие
миграции/backfill); isolation (каждый Interaction test file
hard-socket-blocked до написания логики, mock-completeness guard,
отсутствие live Sheets/Drive/Telegram/Railway/HTTP/socket).

### 32. Production migration policy (Phase 42C)

Подтверждено: только один новый пустой реестр; никакой миграции
legacy-строк; никакого создания production Interaction во время Phase
42C; никакой мутации Person/Lead/Client/Offer; никаких изменений
`relationship_capital`; никаких изменений Drive; никакого деплоя в
Phase 42C.

### 33. Точный bounded scope Phase 42C

Phase 42C реализует ТОЛЬКО: один канонический реестр с
ADR-утверждённым непротиворечивым ключом; точные заголовки; ACT
identity; `interaction_manager.py`; точные reads и ограниченные
фильтры; создание Interaction; idempotency; XOR-валидацию субъекта;
опциональную relation-валидацию; type/direction валидацию;
валидацию Occurred At; валидацию Summary/Outcome/External Reference;
архивацию; обновление Notes; immutability; структурированный result
contract; architecture/isolation guards; тесты.

Явно запрещено в Phase 42C: Telegram caller UX; деплой; использование
ключей реестра `interactions`/`interaction_registry`/
`lead_interactions`; переиспользование RelationshipTouch; TCH
identity; записи в relationship_capital; синхронизация полей Person;
синхронизация Lead "Last Contacted At"; мутация follow-up/статуса
Lead; автоматический Task/Reminder; хранение тела сообщения/вложений;
интеграции с провайдерами; технический Audit Log; связи
Object/Service/Roadmap/Payment/Task; hard delete; restore/reopen;
миграция/backfill.

### 34. Отклонённые альтернативы

**A. Переиспользование RelationshipTouch.** Отклонено: несовместимость
схемы и персистентности; legacy orphan.

**B. Переиспользование реестра relationship_capital.** Отклонено:
несовместимое назначение и поля.

**C. Использование TCH identity.** Отклонено: legacy семантическая
контаминация.

**D. Использование INT identity.** Отклонено: коллизия с
`integration_registry`.

**E. Использование ключа реестра `interactions`.** Отклонено:
конфликтует с закрытыми Lead architecture guards.

**F. Одновременно Lead и Client как субъекты.** Отклонено: неоднозначный
fan-out и дублирующее представление жизненного цикла.

**G. Generic Activity entity, объединяющая Interaction и Audit Log.**
Отклонено: разная приватность, потребители, объём и точки мутации.

**H. Автоматическое обновление сводных полей контакта Person.**
Отклонено: переоткрывает закрытый Client Domain и создаёт dual-write.

**I. Автоматическое обновление Lead "Last Contacted At".** Отклонено:
переоткрывает закрытую Lead-оркестрацию и вносит скрытую связанность.

**J. Автоматическое создание Task/Reminder.** Отклонено: кросс-доменная
автоматизация и scheduler вне объёма.

**K. Хранение полного сообщения/транскрипта.** Отклонено: приватность,
объём, provider-специфичная сложность.

**L. External Reference как идентичность.** Отклонено: provider-
специфично и не глобально канонично.

**M. Изменяемые Interaction-факты.** Отклонено: ослабляет историческую
целостность.

**N. Миграция/backfill из legacy-полей.** Отклонено: отсутствует
надёжный schema-совместимый источник данных.

### 35. Cross-ADR consistency

Проверено на отсутствие противоречий с решениями по Client, Lead
ADR-024, Organization ADR-018, Task ADR-019, Document ADR-020,
Checklist ADR-021, Payment ADR-022, Commercial Offer ADR-023,
Object/Service/Roadmap/Stage closed-domain решениями. Ни один закрытый
домен не мутируется Interaction Foundation — Interaction ссылается на
их ID только для чтения/валидации существования, тем же паттерном, что
уже используют все предыдущие домены этого engagement.

### 36. Статус

Утверждено для реализации (Phase 42C) с bounded scope, определённым в
решении 33. Ничего не реализовано в рамках этого ADR — только
архитектурное решение. `interaction_manager.py` не создан;
`interaction_log` не существует; ни один production-caller не
мигрирован; ни один код не изменён; схема Google Sheets не менялась;
GTD Core не затронут; `relationship_capital.py` не изменён. Ни один
закрытый домен (Object/Client/Service/Roadmap/Stage/Organization/Task/
Document/Checklist/Payment/Commercial Offer/Lead) не переоткрыт.
