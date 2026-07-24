# ENGINEERING STANDARDS — Development Constitution
## Business Operating System (Business Core)

Статус: принято, Phase 21.0. Обязателен к соблюдению во всех последующих фазах
(21A, 21B, ..., 22, 23, ...). Архитектура Phase 20A → 20A.6 и Phase 21
Implementation Plan считаются утверждёнными и здесь не пересматриваются.

Это не архитектурный документ и не implementation plan. Это правила, по
которым любая будущая фаза — независимо от того, кто её выполняет, человек
или AI-ассистент — обязана работать, чтобы система оставалась целостной через
годы разработки.

---

## 1. Project Principles

**Registry First.**
Любая новая сущность сначала получает строку в `BUSINESS_HEADERS`/
`BUSINESS_SHEET_NAMES`/`_ID_PREFIXES` (`sheets.py`), и только потом — код,
который её читает или пишет. Схема — источник истины, а не побочный продукт
кода. Причина: во всей истории этого проекта (Knowledge Core, Document
Registry, Stage-Entity Relations, теперь Organization Layer) именно этот
порядок ни разу не привёл к breaking-миграции.

**Manager First.**
Ни один Telegram-хендлер и ни один другой модуль не обращается к
`get_business_sheet()` напрямую в обход manager-модуля своего домена.
Manager — единственная точка правды для чтения/записи конкретной Registry.
Причина: это единственное место, где легко проверить «а вызывается ли эта
функция где-то ещё» и «а что произойдёт, если Sheets вернёт 429» — если
доступ к листу размазан по хендлерам, это невозможно аудировать.

**Additive Evolution.**
Новая колонка добавляется в конец списка полей. Новый лист добавляется
новым словарным ключом. Существующая колонка никогда не переименовывается
и не удаляется без отдельного, явно одобренного migration-плана. Причина:
это единственная причина, по которой у проекта за всю его историю не было
ни одной breaking-миграции (см. Phase 20A.6, раздел «What already matches
best practices»).

**Backward Compatibility.**
Любое изменение формата возвращаемого значения функции обязано сохранять
все существующие ключи словаря, даже если добавляются новые (см. Phase
19B-1: `_stage_update_result()` хранит одновременно новый контракт и старые
`error`/`old_status`/`new_status`). Перед любым рефакторингом сигнатуры —
`grep` по всем тестам на точное использование старых ключей.

**Core Protection.**
Core (Business → Client → Service → Roadmap → Stage, см. Phase 20A.5) не
меняется без отдельного, явно одобренного диагностика→план→фикс цикла.
Extension-слои (Organization, Relation, Document, Knowledge, Automation,
AI, Reporting, Integration) могут развиваться свободно, пока не требуют
изменений в Core. Это тот же принцип, что «не менять GTD Core» — только
на один уровень ниже, внутри Business Core.

**One Source of Truth.**
Одна сущность — одна Registry. Если два листа могут описывать одно и то же
(например, `Owner Role` в Knowledge Layer и будущий `Role ID` в Organization
Layer) — это документируется как «параллельные, не связанные поля» явно,
а не тихо оставляется как потенциальный источник рассинхрона.

**Explicit Relationships.**
Связь между сущностями — либо прямой Foreign Key (ID-строка, провалидированная
при записи), либо отдельная relation-таблица (`STAGE_ENTITY_RELATIONS`-стиль).
Никогда — comma-separated список ID в одной ячейке для новых полей (см. явный
запрет в Phase 20A revised, п.2 про `Business ID` на Role). Существующие
comma-list поля (`Biz IDs` в People Registry) не переделываются задним числом,
но новые поля никогда не повторяют этот паттерн.

**Read-before-Write.**
Любая write-операция, зависящая от текущего состояния строки (например,
«заполнить Start Date только если она пуста»), обязана читать актуальное
состояние непосредственно перед записью — snapshot из начала диалога
(Telegram confirmation flow) не считается актуальным на момент записи.
Это уже установленный паттерн `_stage_edit_start()`/`_stage_edit_execute()`.

**Test Driven Changes.**
Ни один PR/commit, меняющий поведение записи, не принимается без теста,
воспроизводящего сценарий отказа (частичная запись, невалидный enum,
отсутствующая колонка) — не только happy path. Это прямое следствие того,
чему научил Phase 18D (реальный production-дефект, обнаруженный именно
потому, что happy-path тесты проходили, а partial-failure — нет).

---

## 2. Layer Dependency Rules

```
Telegram (telegram_handlers.py)
   ↓
Manager (roadmap_manager.py, organization_manager.py, ...)
   ↓
Sheets (sheets.py — единственная точка доступа к Google Sheets API)
   ↓
Google API (gspread)
```

Дополнительно, между manager-модулями:

```
Extension-слои читают Core через его manager (read-only).
Core никогда не импортирует из Extension-слоёв.
GTD Core никогда не импортируется из Business Core, и наоборот
   (единственный разрешённый мост — inbox_bridge.py).
```

**Разрешённые зависимости:**
- `telegram_handlers.py` → любой `*_manager.py` (импорт внутри функции, established convention).
- `*_manager.py` → `sheets.py` (только через `get_business_sheet()`, `get_header_index_map()`, `read_row_by_headers()` — общие примитивы, не прямой gspread-вызов).
- Extension-manager (`organization_manager.py`) → Core-manager (`person_manager.py` для проверки Person ID) — **только чтение**, никогда запись.
- `stage_entity_relations.py` → `document_requirements.py` использует его как источник (не наоборот) — Relation Layer не знает о Document Layer напрямую, только Document Layer знает о Relation Layer.

**Запрещённые зависимости:**
- `telegram_handlers.py` → `sheets.py` напрямую, в обход manager.
- Core-manager (`roadmap_manager.py`) → любой Extension-manager (`organization_manager.py`, `document_intelligence.py`) — Core не должен знать о существовании Extension-слоёв.
- Любой `business_core/*.py` → `inbox_processor.py` / `telegram_bot.py` (GTD части) / `project_planner.py` / `calendar_sync.py`, кроме `inbox_bridge.py`.
- Extension-manager → запись в чужую Registry напрямую (например, `organization_manager.py` пишет строку в `PEOPLE_REGISTRY`) — если нужна запись в чужой домен, это повод для отдельного, explicitly-approved cross-domain design review, а не тихого добавления.
- Circular imports между любыми двумя `*_manager.py` — если возникает необходимость, это сигнал, что граница домена проведена неправильно.

---

## 3. Module Standards

| Тип модуля | Единственная ответственность |
|---|---|
| `sheets.py` | Схема (headers/prefixes/sheet-names) + низкоуровневые примитивы доступа к Google Sheets (auth, `get_business_sheet`, `get_header_index_map`, `read_row_by_headers`, `generate_next_id`). Не содержит доменной логики ни одного конкретного registry. |
| `*_manager.py` | CRUD + доменная логика ровно одной Registry (или тесно связанной пары, как Role+Assignment). Не знает о Telegram, не знает о других доменах кроме read-only FK-проверок. |
| `telegram_handlers.py` | Парсинг команд, вызов manager-функций, форматирование ответа. Не содержит бизнес-логики валидации сверх того, что уже возвращает manager — обёртка, не источник правды. |
| `stage_entity_relations.py` (Relation Layer) | Единственный generic-механизм связывания Stage↔Entity. Расширяется только через `ENTITY_TYPE_DISPATCH`, никогда новой колонкой в самой relation-таблице. |
| `document_intelligence.py` / AI-модули | Только enrichment. Никогда не блокирует и не откатывает основную write-транзакцию (см. существующий инвариант в докстринге модуля — обязателен для любого будущего AI-модуля). |
| `*_registry.py` (integration_registry.py, channel_registry.py) | Реестр метаданных о внешней системе. Не выполняет вызовов к этой внешней системе — это задача будущего отдельного `*_integration.py`/execution-модуля, если он появится. |
| `report_manager.py` / Reporting-модули | Read-only агрегация. Не пишет ни в одну Registry никогда, ни при каких обстоятельствах. |
| `synthetic_cleanup.py`-класс утилит | Guarded maintenance-скрипты. Никогда не импортируются runtime-кодом или Telegram-хендлерами. Allowlist-only, dry-run по умолчанию. |

Правило: если модуль начинает делать что-то из списка ответственности другого
типа — это сигнал для рефакторинга, а не для «пока так, потом поправим».

---

## 4. Function Design Standards

**Naming:**
- `create_*`, `find_*_by_id`, `list_*`, `update_*`, `delete_*`/`archive_*` — единый глагольный префикс по операции, домен — существительным сразу после (`create_role`, не `role_create`).
- Приватные помощники — `_leading_underscore`, не экспортируются.
- Булевы helper-функции — `is_*`/`has_*` (`is_role_vacant`, не `check_role_vacant`).

**Function size:**
Одна функция — одна логическая write-операция или один логический read-запрос.
Если функция начинает писать в 3+ разных листа — это повод разбить на отдельные
изолированные шаги (см. `update_stage_status_in_sheet()`'s per-field isolation,
Phase 19B-1, как образец «одна функция, много изолированных шагов записи»).

**Return contracts:**
Каждая write-функция возвращает dict с как минимум `ok: bool`. Для операций,
где возможна частичная запись, обязателен расширенный контракт:
`ok, partial_success, updated_fields, warnings, errors` (см.
`_stage_update_result()` как канонический образец). Read-функции возвращают
`None`/`[]` на «не найдено», никогда не бросают исключение на нормальный
«пусто» случай.

**Error handling:**
- Sheets-исключения ловятся внутри manager-функции, никогда не пробрасываются в Telegram-слой как raw exception.
- Если запись не удалась и причина неясна (write вызвал исключение) — обязателен controlled fresh-read для честного определения состояния, никогда не «предполагаем успех» и не «предполагаем провал» (Phase 19B-1 «fail closed, never guess»).
- Downstream-failure (например, пересчёт Progress % после успешного обновления статуса) никогда не превращает уже подтверждённый успех в ложный total failure — это отдельный, независимый сигнал (Phase 19B-1 Part D).

**Validation:**
- Enum-поля валидируются в manager-функции до похода в Sheets (invalid status отклоняется без единого вызова `sheet.find()` — см. `test_invalid_status_no_lookup_performed`).
- FK-поля (Person ID, Role ID, Department ID) валидируются явным `find_*_by_id()`-вызовом перед записью, не полагаясь на то, что Sheets сам откажет.

**Logging:**
См. раздел 8.

**Docstrings:**
Обязательны для каждой публичной функции manager-модуля. Формат: одна строка
назначения, затем при необходимости — Args/Returns, затем — «Phase XX: …» с
объяснением нетривиального решения (почему именно так, а не «что делает код» —
что делает код и так видно по имени и телу).

**Comments:**
Только там, где неочевидна причина («WHY», не «WHAT»). Пример хорошего
комментария (реальный, из `stage_entity_relations.py`): «Deliberately NOT a
generic graph: only Entity Type/Entity ID vary… — none has a current
consumer». Пример плохого — `# increment counter`.

**Примеры хорошей/плохой практики:**

Хорошо (реальный код, `_stage_update_result`):
```python
return _stage_update_result(
    ok=True, partial_success=bool(warnings), ...
    updated_fields=tuple(updated_fields), warnings=tuple(warnings),
)
```
Честный контракт, явно видно что могло пойти не так, ничего не скрыто.

Плохо (гипотетический антипаттерн, не допускать):
```python
def update_role(role_id, **fields):
    try:
        ...write everything...
        return True
    except:
        return False
```
Никакой информации о том, что именно записалось, что не записалось, и почему.

---

## 5. Testing Standards

**Test naming:** `test_<condition>_<expected_result>` — не `test_1`, не
`test_role`. Пример из уже принятого кода: `test_status_write_raises_but_
fresh_read_confirms_committed`.

**Arrange / Act / Assert style:** обязателен, даже без явных комментариев-
маркеров — построение mock-листа и входных данных (Arrange), единственный
вызов тестируемой функции (Act), серия `assertEqual`/`assertIn` (Assert).
Не смешивать несколько вызовов тестируемой функции в одном тесте без явной
причины (idempotency-тесты — законное исключение, две последовательные
записи специально сравниваются).

**Mocking rules:**
- Google Sheets всегда мокается (`MagicMock` + `sheet.find.return_value`/
  `sheet.row_values.side_effect`) — ни один unit-тест не делает живой вызов
  к Sheets API.
- Использовать реальные production-заголовки листа (`STAGES_HEADERS`-стиль
  константа в начале тестового файла), не произвольные укороченные списки —
  иначе тест не поймает рассинхрон реального листа.
- Для module-reset между тестами использовать установленный `_fresh()`-паттерн
  (удаление `business_core.*` из `sys.modules` + `importlib.import_module`).

**Regression rules:**
Любое изменение существующего response-формата (Telegram-текст, dict-ключи)
обязано сопровождаться обновлением всех тестов, зафиксировавших старый формат
— найденных через явный `grep` перед изменением, не «пока запустим и
посмотрим что упадёт».

**Coverage expectations:**
Каждая write-функция: минимум по одному тесту на (а) happy path, (б) каждое
поле изолированной записи выбрасывает исключение отдельно, (в) невалидный
enum, (г) not-found ID, (д) idempotent повтор. Это не «стремиться к X%
покрытия» — это конкретный список сценариев, обязательных для write-путей,
установленный практикой Phase 19B-1 (27 тестов на одну функцию).

**When integration tests are required:**
Когда новая функциональность связывает 2+ реестра (Role↔Person, Relation↔
Document) — обязателен отдельный integration-тест, воспроизводящий полную
цепочку чтения/записи через оба слоя, в дополнение к unit-тестам каждого
слоя по отдельности.

---

## 6. Google Sheets Standards

**Registry schema:** регистрируется исключительно в `sheets.py`'s трёх
словарях. Никогда — hardcoded имя листа или список колонок где-либо ещё
в кодовой базе.

**ID generation:** через `generate_next_id()` с уникальным префиксом в
`_ID_PREFIXES`. Перед добавлением нового префикса — обязательная проверка
на коллизию (`grep` по всему `business_core/`) — установленная практика
каждой прошлой фазы (Phase 15A явно задокументировала, почему `DREG`, а
не переиспользование занятого `DOC`).

**Header naming:** английские названия для новых полей (проектная эволюция
уже идёт от русскоязычных заголовков ранних Registry к английским — новые
таблицы не возвращаются к русскому). Разделитель слов — пробел, Title Case
(`"Role Name"`, не `"role_name"`, не `"RoleName"`).

**Enums:** валидируются в коде (Python tuple constant), не через Sheets
data-validation. Единый источник правды — Python-константа, аналогично
`STAGE_STATUS_CANONICAL`.

**Foreign Keys:** ID-строка (`ROLE-xxx`), валидированная явным
`find_*_by_id()`-вызовом в manager-функции перед записью. Никогда —
comma-separated список для новых полей (см. принцип Explicit Relationships).

**Nullable fields:** пустая строка `""`, не `None`, не отсутствие колонки.
Все read-функции обязаны быть header-safe (отдавать `""` для отсутствующей
в старой строке колонки, не бросать `IndexError`) — установленный паттерн
`read_row_by_headers()`.

**Soft delete:** через `Status=archived`/`inactive`, строка никогда физически
не удаляется штатным кодом. Физическое удаление — только через отдельный
guarded utility (`synthetic_cleanup.py`-класс), никогда не runtime-путём.

**Status fields:** каждая Registry с понятием жизненного цикла обязана иметь
явный `Status` enum-column, а не подразумевать статус через отсутствие/
наличие других полей.

**Version compatibility:** новая колонка добавляется в конец списка полей.
Существующие строки с этой позиции читаются как `""` до тех пор, пока явно
не заполнены — не требует backfill-миграции.

---

## 7. Telegram Command Standards

**Command naming:** глагол+существительное, слитно, нижний регистр
(`/newrole`, `/assignstage`, `/updatestage`) — установленный паттерн, не
нарушать ради новых команд.

**Input validation:** парсинг через общий `_parse_kv_args()`, обязательные
аргументы проверяются до вызова manager-функции; при отсутствии —
usage-сообщение с примерами вызова (established convention, каждая
существующая команда).

**Error messages:** начинаются с `❌`, содержат ID сущности и причину.
Для невалидного enum — обязательно перечисление всех допустимых значений
в самом сообщении (established, `/updatestage`).

**Success messages:** начинаются с `✅` (полный успех) или `ℹ️` (успех без
изменений / idempotent-повтор). Частичный успех — `⚠️`, с явным списком
«что не удалось» и фразой «повтор команды безопасен» (established,
Phase 19B-1).

**Read-only commands:** никогда не изменяют состояние ни при каком входе,
включая невалидный. Помечать в докстринге явно `Read-only.` (established,
`find_stage_by_id`, `/stage`).

**Write commands:** для необратимых/значимых изменений — confirmation flow
(snapshot → показать old→new → явное подтверждение → перечитать перед
записью → записать только разрешённые колонки), established
`_stage_edit_start()`/`_stage_edit_execute()`-паттерн. Для простых
одноходовых операций (`/assignstage`) confirmation flow не обязателен, если
операция идемпотентна и легко отменяема повторным вызовом.

**Confirmation flow:** общий `SE_CONFIRM`-style state, единая пара
start/execute-функций на несколько похожих команд, а не дублирование
диалоговой логики в каждой команде отдельно.

**Future multi-user compatibility:** сейчас система однопользовательская,
никакой access-control layer не строится заранее (см. Phase 21 Test Plan,
раздел Telegram — явно отложено). Но: ни одна новая команда не должна
хардкодить предположение «есть только один пользователь» в самой бизнес-
логике (только в текущем отсутствии проверки прав) — то есть manager-слой
не должен требовать переделки, когда access-control появится, только
telegram_handlers.py должен получить дополнительную проверку перед вызовом
manager-функции.

---

## 8. Logging & Diagnostics

- **INFO** — не используется избыточно; успешные write-операции не логируются
  построчно (Sheets — источник аудита сама по себе через сам факт записи).
- **WARNING** — партиальный отказ, не блокирующий (`log.warning`, established
  в `find_stage_by_id`'s except-блок при not-found-по-исключению).
- **ERROR** — write-операция не удалась полностью, или неожиданное исключение
  до похода в Sheets (`log.error`, established в
  `update_stage_status_in_sheet`'s outer except).
- **Audit logging:** сама Registry — источник аудита (Created At/Updated At/
  Uploaded By/Reviewed By-колонки), отдельный audit-log не строится, пока нет
  явного запроса на compliance-функциональность (вне текущего scope, см.
  Phase 20A.6 ISO 9001-сравнение).
- **Traceability:** каждое сообщение лога включает entity ID
  (`f"update_stage_status_in_sheet({stage_id}) ..."`), никогда generic
  «write failed» без контекста.
- **Debug strategy:** при неясном production-инциденте — read-only диагностика
  сначала (как в Phase 18D/19B-2), никогда «попробуем ещё раз и посмотрим» без
  сначала понятого механизма отказа. При quota (429) — стоп, ожидание,
  контролируемый retry, никогда не угадывать состояние.

---

## 9. Commit & Release Standards

**Commit message format:** `<type>: <краткое summary в imperative mood>`,
где `type` — `feat`/`fix`/`chore`/`refactor` (established, вся история этого
репозитория). Тело коммита — не обязательно, если summary самодостаточен.

**Branch strategy:** прямые коммиты в `main`, без feature-веток — established
практика этого проекта (однопользовательская разработка, agent-gated review
на каждом шаге заменяет PR-review). Не менять эту практику без явного запроса.

**Release checklist (перед commit):**
1. Полный diff review (`git diff`, `git status`) — подтверждение, что изменены
   только запланированные файлы.
2. Полный regression-прогон (весь suite, не только затронутые тесты).
3. Подтверждение: нет изменений в `.env`, нет изменений в GTD-файлах, нет
   изменений схемы вне явно одобренного плана.
4. Явное одобрение пользователя перед самим commit — не молчаливое
   предположение согласия.

**Deployment checklist:**
1. Pre-deploy: HEAD совпадает с одобренным commit SHA, working tree чист.
2. Deploy через established Railway CLI workflow (`railway up`), без push
   в GitHub, без изменений env-переменных.
3. Post-deploy: startup-логи без ошибок/restart-loop/растущего getUpdates
   conflict; read-only проверка production-данных (ничего непреднамеренно
   не записано).
4. Финальный отчёт по established 15–21-пунктовому формату (см. Phase 19B-2).

**Rollback checklist:** см. индивидуальный Rollback Plan каждой фазы (пример
— Phase 21, раздел 6). Общее правило: additive-изменения откатываются чистым
`git revert`/commit-откатом без реконсиляции данных; любое изменение,
затронувшее уже записанные production-данные, требует отдельного,
explicitly-approved recovery-плана перед откатом кода.

---

## 10. Documentation Standards

Каждая новая фаза, вводящая новую Registry/Layer/Manager, обязана оставить
после себя:

- **Architecture note** — если фаза меняет layer-карту (Phase 20A/20A.5-стиль
  документ), иначе — не требуется отдельно для мелких фаз.
- **Implementation note** — краткое резюме: что реализовано, какие файлы
  изменены, какие функции добавлены (естественным образом уже присутствует в
  финальном отчёте каждой фазы этого engagement — фиксировать как обязательный
  минимум, не как формальность).
- **Test summary** — какие тесты добавлены, каков итог полного прогона
  (established, каждая фаза).
- **Deployment record** — если фаза включала deploy: deployment ID до/после,
  commit SHA, startup health (established, Phase 19B-2-формат).
- **Handoff note** — если фаза оставляет что-то намеренно отложенным
  (deferred entity, open question) — фиксировать явно в финальном отчёте
  фазы (established, «Risks and Open Questions»-разделы Phase 20A/20A.5/20A.6).

Этот файл (`ENGINEERING_STANDARDS.md`) и файлы, упомянутые в `CLAUDE.md`
(`PROJECT_CONTEXT.md`, `CURRENT_STATUS.md`, `ARCHITECTURE.md`,
`NEXT_TASKS.md`), — обязательное чтение перед началом любой новой фазы,
как уже требует `CLAUDE.md`.

---

## 11. Code Review Checklist

Перед каждым commit — обязательный чек-лист:

- [ ] Затрагивает ли изменение Core (Business/Client/Service/Roadmap/Stage)? Если да — отдельное явное обоснование обязательно.
- [ ] Затрагивает ли изменение GTD-файлы? Если да — стоп, требуется отдельное разрешение вне обычного workflow.
- [ ] Является ли изменение additive (новая колонка/строка/файл), а не modify-in-place существующей схемы?
- [ ] Включены ли тесты на happy path И на partial-failure/invalid-input сценарии?
- [ ] Провалидированы ли Foreign Key поля перед записью?
- [ ] Возможен ли безопасный rollback без реконсиляции данных?
- [ ] Следует ли изменение manager-first архитектуре (нет прямого обращения к Sheets из Telegram-слоя)?
- [ ] Сохранены ли все существующие ключи возвращаемого dict (backward compatibility)?
- [ ] Пройден ли полный regression suite, не только затронутые тесты?
- [ ] Проверен ли `.env` на отсутствие изменений?
- [ ] Проверена ли схема (`sheets.py`) на отсутствие непреднамеренных изменений, если фаза не про схему?
- [ ] Есть ли явное одобрение пользователя на commit (не молчаливое предположение)?

---

## 12. Technical Debt Policy

**Допустимо:** явно задокументированный, но не исправленный сейчас технический
долг — при условии, что он зафиксирован письменно с причиной отсрочки
(established прецедент: хардкод `"Дидар"` как default responsible/owner,
зафиксирован в Phase 20A как технический долг, не исправляется до появления
второго реального сотрудника — правильный пример этой политики в действии).

**Запрещено:** тихий технический долг — код, который «временно» обходит
установленный стандарт (Manager First, Additive Evolution, Read-before-Write)
без явной фиксации этого факта в докстринге/финальном отчёте фазы.

**Когда допустим рефакторинг:** только когда у изменения есть конкретный
триггер (новый consumer, реальный баг, явный запрос пользователя) — не
«заодно почистим», не рефакторинг ради стиля. Это прямое следствие принципа
проекта «Минимальные изменения. Не переписывать большие куски проекта» из
`CLAUDE.md`, распространённое на весь Business Core, а не только на GTD Core.

---

## 13. Future Evolution Policy

**Новая Registry:** добавляется исключительно через additive-запись в трёх
словарях `sheets.py`, с обязательной проверкой на коллизию ID-префикса и
имени листа. Не требует изменения ни одной существующей Registry.

**Новый Layer:** сначала — audit-фаза (Phase 20A-стиля: что уже есть, где
возможно дублирование, минимальная версия против полной), только потом —
implementation plan (Phase 21-стиля), только потом — код. Ни один новый
слой не начинается сразу с кода.

**Новый Manager:** один manager — один домен (см. раздел 3). Новый manager
не импортирует напрямую из manager другого домена для записи — только для
read-only FK-валидации, и то в явно обоснованных случаях.

**Новая Integration:** регистрируется в `INTEGRATION_REGISTRY` как факт
(метаданные) до того, как появляется исполняющий код. Исполняющий код
(реальные вызовы к внешнему API) — отдельный, явно одобренный этап, не
подразумеваемый автоматически фактом регистрации.

**Новая AI-возможность:** обязана следовать уже установленному инварианту
`document_intelligence.py` — enrichment-only, никогда не блокирует и не
откатывает основную транзакцию, результат хранится в отдельной,
purely-additive таблице (по аналогии с `DOCUMENT_CONTENT`, никогда не
смешивается со схемой основной Registry).

Ни одно из вышеперечисленного не может быть нарушено «ради скорости» без
явного, письменно зафиксированного решения пользователя — этот документ
и есть то место, где такое решение должно быть зафиксировано, если оно
когда-либо будет принято.

---

*Этот документ — часть постоянной документации проекта, наравне с
`ARCHITECTURE.md`, `PROJECT_CONTEXT.md`, `CURRENT_STATUS.md`,
`NEXT_TASKS.md`. Изменяется только через явное решение пользователя,
не переписывается автоматически новой фазой без отдельного запроса.*
