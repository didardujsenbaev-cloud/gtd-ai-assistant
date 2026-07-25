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