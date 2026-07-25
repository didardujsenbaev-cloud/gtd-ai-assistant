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