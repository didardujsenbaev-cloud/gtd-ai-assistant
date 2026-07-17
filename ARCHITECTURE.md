# BUSINESS CORE ARCHITECTURE

## Общая архитектура

GTD Core

│

├── Inbox

├── Projects

├── Calendar

├── Reference

└── Next Actions

Business Core

│

├── Business

│

├── Client

│

├── Object

│

├── Service

│

├── Roadmap

│

├── Stages

│

├── Documents

│

├── Contractors

│

└── Reports

---

## Иерархия

Business

↓

Client

↓

Object

↓

Service

↓

Roadmap

↓

Stage

---

## Источник данных

Google Sheets

↓

Business Core

↓

Telegram Bot

↓

Пользователь

---

## Документы

Google Drive

Business

↓

Client

↓

Object

↓

Service

↓

Documents

---

## Каналы

Binotel

↓

SendPulse

↓

Business Core

↓

Telegram

---

## Главный принцип

Business Core является единственным источником истины.

Никакая другая система не хранит бизнес-логику.

SendPulse отвечает только за продажи.

Binotel отвечает только за телефонию.

Google Drive отвечает только за документы.

Telegram является интерфейсом сотрудников.

Google Sheets является текущей базой данных.

---

## Roadmap Engine (Phase 9)

Фактическая модель, реализованная и проверенная в Phase 9A–9E.2:

Business → Client → Object → Service → Roadmap → Stages

Roadmap хранится в листе ROADMAPS, Stages — в отдельном листе

ROADMAP_STAGES (один roadmap → много этапов, связь по Roadmap ID).

Создание Roadmap:

```
/startroadmap
  → create_roadmap_for_object()   (business_core/business_builder.py)
       пишет 1 строку в ROADMAPS

  → create_stages_from_template_record() /
    create_roadmap_stages_from_template()   (business_core/roadmap_manager.py,
                                              business_core/roadmap_template_manager.py)
       пишут N строк в ROADMAP_STAGES
```

Обновление этапа и каскад пересчёта:

```
/updatestage stage_id=... status=... [notes=...]
  → update_stage_status_in_sheet()   пишет Status (+Notes) этапа
  → recalculate_roadmap_progress()   пишет Progress % roadmap
  → maybe_complete_roadmap()         пишет Status roadmap (active → completed),
                                      только если условия завершения выполнены
```

Каждый шаг пишет только свою колонку и только свою строку — шаги не

перезаписывают результаты друг друга и безопасны при повторном вызове.

---

## Stage lifecycle

Канонический словарь статусов реального этапа (ADR-009):

pending → in_progress → blocked → done

                                 → skipped

pending, in_progress, blocked — этап не завершён.

done, skipped — этап завершён (входят в DONE_SET).

Legacy-значения (not_started, waiting, "completed" как статус этапа)

читаются без ошибок на существующих данных, но не принимаются на

запись через /updatestage.

---

## Progress and Completion

Progress % roadmap = round_half_up(done_count / total_count × 100),

где done_count — количество этапов со статусом из DONE_SET

(done, skipped). Пустой roadmap (0 этапов) → 0%. Формула и решение

по skipped зафиксированы в ADR-010.

Roadmap автоматически переходит active → completed, когда

одновременно: есть хотя бы один этап, все этапы в DONE_SET,

Progress % = 100, текущий Status = active. completed никогда не

откатывается обратно в active автоматически; draft/paused/cancelled/

on_hold не изменяются автозавершением. Полные правила — ADR-011.

---

## Header-safe Sheets pattern

Архитектурный принцип (ADR-012, обязателен для нового кода):

строки Google Sheets читаются и пишутся по ИМЕНАМ фактических

заголовков листа (get_header_index_map / row_from_header_map /

read_row_by_headers из business_core/sheets.py), а не по числовой

позиции колонки и не по статическому списку BUSINESS_HEADERS.

Причина закреплена в ADR-012: позиционная запись при расхождении

кода и фактических заголовков листа дважды приводила к реальным

инцидентам (BUG-001 / RM-027, и аналогичный риск в ROADMAP_STAGES,

устранённый миграцией Phase 9A до появления видимого бага).

Весь Roadmap Engine (Phase 9B–9E.2) реализован header-safe.

Несколько более старых writer'ов (создание этапов из шаблона,

создание объектов, /newroadmap) остаются позиционными как известный

технический долг — см. NEXT_TASKS.md (Phase 10.2B).

---

## Известный технический долг: разделение Roadmap CRUD

Создание и чтение самого Roadmap (create_roadmap_for_object,

find_roadmap_by_id, find_roadmaps_by_object, update_object_roadmap_id)

физически находится в business_core/business_builder.py.

Всё, что касается этапов, прогресса и завершения Roadmap

(get_stages_for_roadmap, find_stage_by_id, update_stage_status_in_sheet,

calculate_progress, recalculate_roadmap_progress,

should_complete_roadmap, maybe_complete_roadmap), находится в

business_core/roadmap_manager.py.

Это осознанный, а не случайный технический долг: разделение возникло

исторически (Object/Roadmap CRUD — Phase 6–7, Stage/Progress Engine —

Phase 9) и не создаёт функциональных проблем сейчас. Решение о

консолидации (если оно будет принято) откладывается до Phase 10.5

(Business Core v1.0 release) и не должно приниматься попутно в рамках

более мелких фаз.