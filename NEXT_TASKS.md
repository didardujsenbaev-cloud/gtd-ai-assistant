# NEXT TASKS

## Open



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
