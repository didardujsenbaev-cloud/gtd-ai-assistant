# NEXT TASKS

## Open

- Phase 10.2A: Legacy cleanup (roadmap_manager.py мёртвая in-memory

  модель Roadmap/RoadmapStage, ROADMAP_STATUSES, STATUS_ICONS,

  get_next_gtd_action…format_roadmap_digest, /newroadmap мёртвый

  импорт create_roadmap).

  Статус: **postponed until after v1.0**. Разрешены только безопасные

  deprecated-пометки в докстрингах/комментариях (без удаления кода,

  без изменения поведения) — не блокирует 10.2B–10.5.

- Phase 10.2B: Header-safe refactoring

  Перевести оставшиеся позиционные writer'ы на row_from_header_map:

  create_stages_from_template_record (приоритет — основной путь

  /startroadmap), create_roadmap_stages_from_template,

  create_roadmap_template, add_roadmap_template_stage,

  create_object_record, /newroadmap (мигрировать на общий путь или

  deprecate). См. DECISIONS.md (ADR-012) и CURRENT_STATUS.md.

- Phase 10.2C: Sheets read optimization

  Устранить двойное полное чтение ROADMAP_STAGES за один вызов

  /updatestage (recalculate_roadmap_progress и maybe_complete_roadmap

  сейчас читают этапы отдельно друг от друга). Без изменения

  контрактов calculate_progress/should_complete_roadmap.

- Phase 10.3: Test infrastructure

  Вынести общий fake-sheet helper в единые fixtures (сейчас

  продублирован в 11+ тестовых файлах). Добавить end-to-end тест

  полной цепочки startroadmap → stages → updatestage → progress →

  completed на едином mock-состоянии.

- Phase 10.5: Business Core v1.0 release

  Формальная фиксация Stable API Roadmap Engine как контракта v1.0.

  Решение по консолидации Roadmap CRUD (сейчас разделён между

  business_builder.py и roadmap_manager.py — см. ARCHITECTURE.md).

---

## Completed

- BUG-001: Persist Template ID в ROADMAPS

  template_id, выбранный в /startroadmap, теперь сохраняется в листе

  ROADMAPS и корректно читается в /milestones. Исправлены

  create_roadmap_for_object и find_roadmap_by_id (запись/чтение по

  фактическим именам заголовков, а не по позиции). Добавлена

  безопасная идемпотентная миграция заголовков ROADMAPS

  (migrate_roadmaps_headers.py). Миграция выполнена в проде, данные

  не затронуты. Проверено на roadmap RM-027 — коммерческие этапы

  в /milestones отображаются корректно. См. DECISIONS.md (ADR-008)

  и CURRENT_STATUS.md.

- Phase 9A: ROADMAP_STAGES schema/header migration

  Безопасная идемпотентная миграция заголовков ROADMAP_STAGES

  (migrate_roadmap_stages_headers.py) — колонки 13–17 (SOP IDs,

  Checklist IDs, Materials IDs, Document Template IDs, FAQ IDs)

  подписаны по факту данных. Выполнено в проде, данные не затронуты.

- Phase 9B: канонические статусы этапов и /updatestage

  STAGE_STATUS_CANONICAL (pending/in_progress/blocked/done/skipped),

  find_stage_by_id(), update_stage_status_in_sheet(), команда

  /updatestage. См. DECISIONS.md (ADR-009).

- Phase 9C: расчёт Progress %

  calculate_progress(), recalculate_roadmap_progress(). См.

  DECISIONS.md (ADR-010).

- Phase 9D: /recalcprogress

  Команда ручного пересчёта Progress % без побочных изменений.

- Phase 9E.1: автоматический пересчёт после изменения этапа

  /updatestage автоматически вызывает recalculate_roadmap_progress

  после успешного изменения статуса этапа.

- Phase 9E.2: автоматическое завершение Roadmap

  should_complete_roadmap(), maybe_complete_roadmap().

  /updatestage автоматически переводит Roadmap active → completed

  при выполнении всех условий. См. DECISIONS.md (ADR-011).

- Phase 10.1: Core Architecture Audit (read-only)

  Полный аудит структуры модулей, legacy/dead code, header-safety,

  Sheets-производительности, Stable API, Telegram-команд, тестовой

  архитектуры и документации Business Core после Phase 9. Результат —

  план стабилизации Phase 10.2A–10.5 (этот файл) и ADR-012

  (Header-safe Sheets Writes).
