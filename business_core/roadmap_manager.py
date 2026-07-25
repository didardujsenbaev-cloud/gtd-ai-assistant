"""
Roadmap Manager — дорожные карты по клиентам, услугам и проектам.

Canonical Sheets-facing owner (Phase 28B/28C/28D/28G/28H) of two
реестров:
  ROADMAPS       — единственный writer: create_roadmap_record(),
                   recalculate_roadmap_progress(), maybe_complete_roadmap().
  ROADMAP_STAGES — единственный writer: ensure_roadmap_stages(),
                   update_stage_fields(), update_stage_status_in_sheet().

Не обращается к Telegram и к business_core.business_builder (Core не
знает об orchestration-слое). Не импортирует Extension-модули
(stage_entity_relations, knowledge_manager, ...).

Строки 1–~793 (Roadmap/RoadmapStage dataclasses, create_roadmap(),
update_stage_status(), advance_stage(), ...) — более старая, отдельная
in-memory модель, которая ДЕЙСТВИТЕЛЬНО не обращается к Google Sheets;
она не подключена к производственным вызовам (см. Phase 27A/27B —
сохранена намеренно, удаление не входит в текущий scope).

Связи:
  business_id  → business_registry
  service_id   → service_catalog
  client_id    → people_registry
  object_id    → object_registry
  template_id  → roadmap_template_registry (через roadmap_template_manager)
  gtd_project_id → Google Sheets PROJECTS (через GTD Master)
"""

from __future__ import annotations

import re
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Статусы этапа
# ─────────────────────────────────────────────────────────────

STAGE_STATUSES = ("not_started", "in_progress", "waiting", "blocked", "done")
ROADMAP_STATUSES = ("active", "completed", "on_hold", "cancelled")

# Phase 9B: канонический словарь статусов РЕАЛЬНОГО этапа (лист
# ROADMAP_STAGES), не путать со STAGE_STATUSES выше — та константа
# принадлежит мёртвой in-memory модели (Roadmap/RoadmapStage,
# update_stage_status/advance_stage) и Sheets не касается.
#
# Legacy-значения, встречающиеся в живых данных ROADMAP_STAGES
# ("not_started" — из /newroadmap) и на уровне ROADMAPS.Status
# ("completed"), в этот словарь намеренно НЕ входят: /updatestage
# принимает только эти пять значений на запись, хотя существующие
# этапы с legacy-статусом по-прежнему читаются без ошибок.
STAGE_STATUS_CANONICAL = ("pending", "in_progress", "blocked", "done", "skipped")

# Phase 9C: статусы, считающиеся ЗАВЕРШЁННЫМИ для расчёта Progress %.
# skipped считается завершённым осознанно — это финальное состояние
# этапа (больше не требует действий), а не промежуточное вроде pending/
# blocked. Всё остальное (pending, in_progress, blocked, legacy-значения
# not_started/waiting/completed, пустые и любые неизвестные строки) —
# не завершено. Решение подтверждено отдельно, не пересматривать здесь.
DONE_SET = frozenset({"done", "skipped"})

# Phase 28H: read-time normalization. Evidence-based, not guessed —
# repository-wide search (code, tests, fixtures, production read-only
# snapshot) found exactly one legacy value ever actually written to
# real ROADMAP_STAGES.Status data: "not_started", by the now-retired
# /newroadmap flow (Phase 28C removed that write path; existing rows
# with this value are read-compatible, never rewritten in bulk here).
# "waiting" appears only in the dead in-memory model's STAGE_STATUSES
# tuple and in defensive icon-lookup dicts (STATUS_ICONS below,
# telegram_handlers.stages_cmd's own status_icons) — no evidence it was
# ever written to a real ROADMAP_STAGES row, so no alias is added for
# it (Phase 28G/H instruction: "не угадывать автоматически").
# ROADMAP_STATUSES has no legacy predecessor — it has always been the
# complete canonical set (active/completed/on_hold/cancelled); the
# "completed" mentioned in STAGE_STATUS_CANONICAL's own comment below
# refers to the Roadmap-level status, not a Stage-level legacy value.
STAGE_STATUS_READ_ALIASES: dict[str, str] = {
    "not_started": "pending",
}
ROADMAP_STATUS_READ_ALIASES: dict[str, str] = {}


def normalize_stage_status(raw_status: str) -> str:
    """Read-time canonicalization for one Stage Status value. Unknown,
    already-canonical, or empty values pass through unchanged — this
    never raises and never hides an unrecognized value."""
    return STAGE_STATUS_READ_ALIASES.get(raw_status, raw_status)


def normalize_roadmap_status(raw_status: str) -> str:
    """Read-time canonicalization for one Roadmap Status value. No
    evidenced legacy alias exists today — kept as a real function (not
    inlined) so a future evidenced alias has one place to be added."""
    return ROADMAP_STATUS_READ_ALIASES.get(raw_status, raw_status)


STATUS_ICONS = {
    "not_started": "⬜",
    "in_progress":  "🔵",
    "waiting":      "🟡",
    "blocked":      "🔴",
    "done":         "✅",
    "active":       "🟢",
    "completed":    "🏆",
    "on_hold":      "⏸",
    "cancelled":    "❌",
}


# ─────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────

@dataclass
class RoadmapStage:
    stage_id:      str
    roadmap_id:    str
    order:         int
    name:          str
    status:        str = "not_started"
    due_date:      Optional[str] = None   # ISO-8601 "YYYY-MM-DD"
    completed_at:  Optional[str] = None
    gtd_action_id: str = ""
    responsible:   str = ""
    docs_required: list[str] = field(default_factory=list)
    docs_received: list[str] = field(default_factory=list)
    notes:         str = ""

    def is_done(self) -> bool:
        return self.status == "done"

    def is_active(self) -> bool:
        return self.status == "in_progress"

    def is_overdue(self, today: Optional[date] = None) -> bool:
        if not self.due_date or self.is_done():
            return False
        t = today or date.today()
        try:
            return date.fromisoformat(self.due_date) < t
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {
            "stage_id":      self.stage_id,
            "roadmap_id":    self.roadmap_id,
            "order":         self.order,
            "name":          self.name,
            "status":        self.status,
            "due_date":      self.due_date or "",
            "completed_at":  self.completed_at or "",
            "gtd_action_id": self.gtd_action_id,
            "responsible":   self.responsible,
            "docs_required": ", ".join(self.docs_required),
            "docs_received": ", ".join(self.docs_received),
            "notes":         self.notes,
        }


@dataclass
class Roadmap:
    roadmap_id:     str
    business_id:    str
    service_id:     str
    city:           str
    client_id:      str
    client_name:    str
    gtd_project_id: str
    responsible:    str
    status:         str = "active"
    created_at:     str = ""
    expected_at:    str = ""
    stages:         list[RoadmapStage] = field(default_factory=list)
    notes:          str = ""

    def get_progress_pct(self) -> float:
        if not self.stages:
            return 0.0
        done = sum(1 for s in self.stages if s.is_done())
        return round(done / len(self.stages) * 100, 1)

    def get_current_stage(self) -> Optional[RoadmapStage]:
        """Первый незавершённый этап."""
        for s in sorted(self.stages, key=lambda x: x.order):
            if not s.is_done():
                return s
        return None

    def get_done_stages(self) -> list[RoadmapStage]:
        return [s for s in self.stages if s.is_done()]

    def get_overdue_stages(self, today: Optional[date] = None) -> list[RoadmapStage]:
        return [s for s in self.stages if s.is_overdue(today)]

    def is_completed(self) -> bool:
        return all(s.is_done() for s in self.stages) if self.stages else False

    def to_dict(self) -> dict:
        return {
            "roadmap_id":     self.roadmap_id,
            "business_id":    self.business_id,
            "service_id":     self.service_id,
            "city":           self.city,
            "client_id":      self.client_id,
            "client_name":    self.client_name,
            "gtd_project_id": self.gtd_project_id,
            "responsible":    self.responsible,
            "status":         self.status,
            "created_at":     self.created_at,
            "expected_at":    self.expected_at,
            "progress_pct":   self.get_progress_pct(),
            "notes":          self.notes,
        }


# ─────────────────────────────────────────────────────────────
# Шаблоны этапов по услугам
# ─────────────────────────────────────────────────────────────

# Ключ: slug услуги → список (order, name, docs_required)
SERVICE_STAGE_TEMPLATES: dict[str, list[dict]] = {

    # ── Узаконение гаража / частного дома ─────────────────────
    "legalization_house": [
        {"order": 1, "name": "Диагностика кейса",
         "docs_required": ["Правоустанавливающий документ на землю", "Техпаспорт (если есть)"]},
        {"order": 2, "name": "Сбор документов от клиента",
         "docs_required": ["Удостоверение личности", "Правоустанавливающий документ", "Техпаспорт"]},
        {"order": 3, "name": "АПЗ",
         "docs_required": ["Заявление в АПЗ", "Документы на землю"]},
        {"order": 4, "name": "Проект",
         "docs_required": ["АПЗ", "Топосъемка"]},
        {"order": 5, "name": "Техобследование",
         "docs_required": ["Проект"]},
        {"order": 6, "name": "Топосъемка",
         "docs_required": ["Заявление геодезисту"]},
        {"order": 7, "name": "Техпаспорт",
         "docs_required": ["Техобследование", "Заявление в БТИ"]},
        {"order": 8, "name": "Акт ввода",
         "docs_required": ["Техпаспорт", "Проект", "АПЗ"]},
        {"order": 9, "name": "Регистрация",
         "docs_required": ["Акт ввода", "Техпаспорт"]},
        {"order": 10, "name": "Архив",
         "docs_required": ["Все оригинальные документы"]},
    ],

    "legalization_garage": [
        {"order": 1, "name": "Диагностика кейса",
         "docs_required": ["Документ на землю или гараж"]},
        {"order": 2, "name": "Сбор документов",
         "docs_required": ["Удостоверение личности", "Документы на участок"]},
        {"order": 3, "name": "Техпаспорт гаража",
         "docs_required": ["Заявление в БТИ"]},
        {"order": 4, "name": "Акт ввода",
         "docs_required": ["Техпаспорт"]},
        {"order": 5, "name": "Регистрация",
         "docs_required": ["Акт ввода", "Техпаспорт"]},
        {"order": 6, "name": "Архив",
         "docs_required": ["Оригиналы документов"]},
    ],

    "legalization_commercial": [
        {"order": 1, "name": "Диагностика кейса",
         "docs_required": ["Правоустанавливающие документы", "Техпаспорт"]},
        {"order": 2, "name": "Сбор документов",
         "docs_required": ["Свидетельство о регистрации юрлица", "Документы на объект"]},
        {"order": 3, "name": "АПЗ",
         "docs_required": ["Документы на землю"]},
        {"order": 4, "name": "Проект реконструкции",
         "docs_required": ["АПЗ", "Топосъемка"]},
        {"order": 5, "name": "Техобследование",
         "docs_required": ["Проект"]},
        {"order": 6, "name": "Топосъемка",
         "docs_required": []},
        {"order": 7, "name": "Техпаспорт",
         "docs_required": ["Техобследование"]},
        {"order": 8, "name": "Акт ввода",
         "docs_required": ["Техпаспорт", "Проект", "АПЗ"]},
        {"order": 9, "name": "Регистрация",
         "docs_required": ["Акт ввода"]},
        {"order": 10, "name": "Архив",
         "docs_required": ["Все документы"]},
    ],

    # ── Визы ──────────────────────────────────────────────────
    "visa_tourist": [
        {"order": 1, "name": "Консультация и выбор типа визы",
         "docs_required": ["Загранпаспорт", "Фото"]},
        {"order": 2, "name": "Сбор документов от клиента",
         "docs_required": ["Загранпаспорт", "Справка с работы", "Выписка из банка"]},
        {"order": 3, "name": "Запись в посольство",
         "docs_required": []},
        {"order": 4, "name": "Подача документов",
         "docs_required": ["Полный пакет документов"]},
        {"order": 5, "name": "Ожидание решения",
         "docs_required": []},
        {"order": 6, "name": "Выдача паспорта с визой",
         "docs_required": []},
    ],

    "visa_work": [
        {"order": 1, "name": "Консультация",
         "docs_required": ["Загранпаспорт", "Трудовой договор"]},
        {"order": 2, "name": "Сбор документов",
         "docs_required": ["Диплом", "Трудовой договор", "Медсправка"]},
        {"order": 3, "name": "Нотариальный перевод документов",
         "docs_required": ["Оригиналы документов"]},
        {"order": 4, "name": "Подача в посольство",
         "docs_required": ["Полный пакет"]},
        {"order": 5, "name": "Ожидание визы",
         "docs_required": []},
        {"order": 6, "name": "Получение и выдача",
         "docs_required": []},
    ],

    # ── Коучинг ───────────────────────────────────────────────
    "coaching_strategy": [
        {"order": 1, "name": "Диагностическая сессия",
         "docs_required": ["Анкета клиента"]},
        {"order": 2, "name": "Разработка плана работы",
         "docs_required": []},
        {"order": 3, "name": "Сессии (блок 1)",
         "docs_required": []},
        {"order": 4, "name": "Промежуточная оценка",
         "docs_required": []},
        {"order": 5, "name": "Сессии (блок 2)",
         "docs_required": []},
        {"order": 6, "name": "Итоговая сессия и план действий",
         "docs_required": []},
    ],

    # ── Универсальный шаблон (если услуга не найдена) ─────────
    "default": [
        {"order": 1, "name": "Старт — диагностика",       "docs_required": []},
        {"order": 2, "name": "Сбор информации",            "docs_required": []},
        {"order": 3, "name": "Работа над задачей",         "docs_required": []},
        {"order": 4, "name": "Проверка результата",        "docs_required": []},
        {"order": 5, "name": "Закрытие и сдача клиенту",   "docs_required": []},
    ],
}

# Маппинг service_id → template_slug
SERVICE_ID_TO_TEMPLATE: dict[str, str] = {
    "SVC-001": "legalization_garage",
    "SVC-002": "legalization_house",
    "SVC-003": "legalization_commercial",
    "SVC-004": "visa_tourist",
    "SVC-005": "visa_work",
    "SVC-006": "coaching_strategy",
}

# Маппинг ключевых слов → template_slug (если service_id не задан)
SERVICE_KEYWORD_TEMPLATES: list[tuple[list[str], str]] = [
    (["гараж"],            "legalization_garage"),
    (["дом", "самострой", "частный"], "legalization_house"),
    (["коммерческ"],       "legalization_commercial"),
    (["туристическ", "шенген", "туризм"], "visa_tourist"),
    (["рабочая виза", "работа за рубеж"], "visa_work"),
    (["стратегическ", "коучинг"],  "coaching_strategy"),
]


def get_stage_template(service_id: str = "", service_name: str = "") -> list[dict]:
    """
    Получить шаблон этапов для услуги.

    Args:
        service_id:   ID услуги (SVC-001 и т.д.)
        service_name: название услуги (используется если service_id не найден)

    Returns:
        list[dict] с полями order, name, docs_required
    """
    # По service_id
    if service_id and service_id in SERVICE_ID_TO_TEMPLATE:
        slug = SERVICE_ID_TO_TEMPLATE[service_id]
        return SERVICE_STAGE_TEMPLATES.get(slug, SERVICE_STAGE_TEMPLATES["default"])

    # По ключевым словам в названии
    name_lower = service_name.lower()
    for keywords, slug in SERVICE_KEYWORD_TEMPLATES:
        if any(kw in name_lower for kw in keywords):
            return SERVICE_STAGE_TEMPLATES.get(slug, SERVICE_STAGE_TEMPLATES["default"])

    return SERVICE_STAGE_TEMPLATES["default"]


# ─────────────────────────────────────────────────────────────
# ID-генераторы (в памяти, без Google Sheets)
# ─────────────────────────────────────────────────────────────

_rm_counter = 0


def _next_rm_id() -> str:
    global _rm_counter
    _rm_counter += 1
    return f"RM-{_rm_counter:03d}"


def _stage_id(roadmap_id: str, order: int) -> str:
    rm_num = re.sub(r"[^0-9]", "", roadmap_id)
    return f"STAGE-{rm_num}-{order:02d}"


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _date_plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ─────────────────────────────────────────────────────────────
# Создание дорожной карты
# ─────────────────────────────────────────────────────────────

def create_roadmap(
    business_id:    str,
    service_id:     str,
    client_id:      str,
    client_name:    str,
    city:           str,
    responsible:    str,
    service_name:   str = "",
    gtd_project_id: str = "",
    expected_days:  int = 30,
    notes:          str = "",
    roadmap_id:     Optional[str] = None,
) -> Roadmap:
    """
    Создать новую дорожную карту по шаблону услуги.

    Args:
        business_id:    ID бизнеса (BIZ-001)
        service_id:     ID услуги  (SVC-001)
        client_id:      ID клиента (PRS-001)
        client_name:    Имя клиента для отображения
        city:           Город
        responsible:    Ответственный (имя/ID)
        service_name:   Название услуги (для автоматического выбора шаблона)
        gtd_project_id: ID GTD-проекта (заполнить после создания проекта в GTD)
        expected_days:  Ожидаемый срок в днях от сегодня
        notes:          Заметки
        roadmap_id:     Принудительно задать ID (для тестов)

    Returns:
        Roadmap с заполненными этапами
    """
    rm_id = roadmap_id or _next_rm_id()
    template = get_stage_template(service_id, service_name)

    stages = [
        RoadmapStage(
            stage_id=_stage_id(rm_id, t["order"]),
            roadmap_id=rm_id,
            order=t["order"],
            name=t["name"],
            docs_required=list(t.get("docs_required", [])),
        )
        for t in template
    ]

    rm = Roadmap(
        roadmap_id=rm_id,
        business_id=business_id,
        service_id=service_id,
        city=city,
        client_id=client_id,
        client_name=client_name,
        gtd_project_id=gtd_project_id,
        responsible=responsible,
        status="active",
        created_at=_now_iso(),
        expected_at=_date_plus(expected_days),
        stages=stages,
        notes=notes,
    )

    log.debug(f"create_roadmap: {rm_id} client={client_name} stages={len(stages)}")
    return rm


# ─────────────────────────────────────────────────────────────
# Изменение статусов
# ─────────────────────────────────────────────────────────────

def update_stage_status(
    roadmap: Roadmap,
    stage_id: str,
    new_status: str,
    notes: str = "",
) -> tuple[Roadmap, RoadmapStage]:
    """
    Обновить статус этапа дорожной карты.

    Args:
        roadmap:    объект Roadmap
        stage_id:   ID этапа
        new_status: один из STAGE_STATUSES
        notes:      заметка об изменении

    Returns:
        (обновлённый roadmap, обновлённый stage)

    Raises:
        ValueError: если stage_id не найден или статус некорректен
    """
    if new_status not in STAGE_STATUSES:
        raise ValueError(
            f"Некорректный статус '{new_status}'. "
            f"Допустимые: {STAGE_STATUSES}"
        )

    target = next((s for s in roadmap.stages if s.stage_id == stage_id), None)
    if not target:
        raise ValueError(f"Этап '{stage_id}' не найден в {roadmap.roadmap_id}")

    target.status = new_status
    if notes:
        target.notes = notes
    if new_status == "done":
        target.completed_at = _now_iso()
        # Если все этапы завершены — закрыть дорожную карту
        if roadmap.is_completed():
            roadmap.status = "completed"

    log.debug(f"update_stage_status: {stage_id} → {new_status}")
    return roadmap, target


def advance_stage(
    roadmap: Roadmap,
    notes: str = "",
) -> tuple[Roadmap, Optional[RoadmapStage], Optional[RoadmapStage]]:
    """
    Завершить текущий этап и перейти к следующему.

    Returns:
        (roadmap, завершённый_этап, новый_текущий_этап или None)
    """
    current = roadmap.get_current_stage()
    if not current:
        return roadmap, None, None

    roadmap, done_stage = update_stage_status(roadmap, current.stage_id, "done", notes)
    next_stage = roadmap.get_current_stage()

    if next_stage:
        roadmap, next_stage = update_stage_status(
            roadmap, next_stage.stage_id, "in_progress"
        )

    return roadmap, done_stage, next_stage


def start_roadmap(roadmap: Roadmap) -> Roadmap:
    """Запустить первый этап дорожной карты."""
    if roadmap.stages:
        first = sorted(roadmap.stages, key=lambda s: s.order)[0]
        if first.status == "not_started":
            roadmap, _ = update_stage_status(roadmap, first.stage_id, "in_progress")
    return roadmap


def complete_roadmap(roadmap: Roadmap) -> Roadmap:
    """Принудительно завершить дорожную карту (все этапы → done)."""
    for stage in roadmap.stages:
        if not stage.is_done():
            stage.status = "done"
            stage.completed_at = _now_iso()
    roadmap.status = "completed"
    return roadmap


# ─────────────────────────────────────────────────────────────
# Подсказки — следующее GTD-действие
# ─────────────────────────────────────────────────────────────

# Имя этапа → рекомендуемое GTD-действие
STAGE_NEXT_ACTIONS: dict[str, str] = {
    "Диагностика кейса":              "Провести первичную консультацию с клиентом по кейсу",
    "Диагностика":                    "Провести первичную консультацию с клиентом",
    "Сбор документов от клиента":     "Запросить пакет документов у клиента",
    "Сбор документов":                "Запросить необходимые документы у клиента",
    "АПЗ":                            "Подать заявление в АПЗ с полным пакетом документов",
    "Проект":                         "Передать задание проектировщику",
    "Проект реконструкции":           "Передать задание проектировщику",
    "Техобследование":                "Согласовать дату выезда технического специалиста",
    "Топосъемка":                     "Согласовать дату выезда геодезиста",
    "Техпаспорт":                     "Подать заявление на техпаспорт в БТИ",
    "Техпаспорт гаража":              "Подать заявление на техпаспорт гаража в БТИ",
    "Акт ввода":                      "Подать документы на акт ввода в эксплуатацию",
    "Регистрация":                    "Подать документы на регистрацию объекта",
    "Архив":                          "Передать оригиналы документов клиенту и закрыть кейс",
    "Консультация и выбор типа визы": "Провести консультацию с клиентом по типу визы",
    "Консультация":                   "Провести диагностическую сессию с клиентом",
    "Запись в посольство":            "Записать клиента на приём в посольство",
    "Подача документов":              "Подать документы в посольство",
    "Подача в посольство":            "Подать документы в посольство",
    "Ожидание решения":               "Проверить статус рассмотрения визы",
    "Ожидание визы":                  "Уточнить сроки готовности визы",
    "Выдача паспорта с визой":        "Забрать паспорт с визой и передать клиенту",
    "Получение и выдача":             "Получить и передать документы клиенту",
    "Нотариальный перевод документов": "Сдать документы нотариусу для перевода",
    "Диагностическая сессия":         "Провести первую диагностическую сессию",
    "Разработка плана работы":        "Составить индивидуальный план коучинга",
    "Промежуточная оценка":           "Провести промежуточную сессию оценки прогресса",
    "Итоговая сессия и план действий": "Провести финальную сессию и составить план дальнейших действий",
    "Старт — диагностика":            "Провести первичный анализ задачи с клиентом",
    "Сбор информации":                "Собрать необходимую информацию по проекту",
    "Работа над задачей":             "Выполнить основную работу по проекту",
    "Проверка результата":            "Проверить результат и согласовать с клиентом",
    "Закрытие и сдача клиенту":       "Сдать результат клиенту и закрыть проект",
}


def get_next_gtd_action(roadmap: Roadmap) -> str:
    """
    Предложить следующее GTD-действие на основе текущего этапа.

    Returns:
        Строка — формулировка для Next Action в GTD
    """
    current = roadmap.get_current_stage()
    if not current:
        return f"Закрыть дорожную карту {roadmap.roadmap_id} — все этапы завершены"

    # Пробуем точный матч, потом частичный
    action = STAGE_NEXT_ACTIONS.get(current.name, "")
    if not action:
        for key, val in STAGE_NEXT_ACTIONS.items():
            if key.lower() in current.name.lower() or current.name.lower() in key.lower():
                action = val
                break

    client_part = f" ({roadmap.client_name})" if roadmap.client_name else ""
    city_part   = f", {roadmap.city}" if roadmap.city else ""

    if action:
        return f"{action}{client_part}{city_part}"
    return f"{current.name} — следующий шаг по кейсу{client_part}{city_part}"


# ─────────────────────────────────────────────────────────────
# Аналитика
# ─────────────────────────────────────────────────────────────

def get_overdue_roadmaps(
    roadmaps: list[Roadmap],
    today: Optional[date] = None,
) -> list[tuple[Roadmap, list[RoadmapStage]]]:
    """
    Найти все дорожные карты с просроченными этапами.

    Returns:
        list[ (roadmap, [просроченные_этапы]) ]
    """
    result = []
    for rm in roadmaps:
        if rm.status in ("completed", "cancelled"):
            continue
        overdue = rm.get_overdue_stages(today)
        if overdue:
            result.append((rm, overdue))
    return result


def get_blocked_roadmaps(roadmaps: list[Roadmap]) -> list[Roadmap]:
    """Дорожные карты с заблокированными этапами."""
    return [
        rm for rm in roadmaps
        if any(s.status == "blocked" for s in rm.stages)
        and rm.status == "active"
    ]


def get_active_roadmaps(roadmaps: list[Roadmap]) -> list[Roadmap]:
    return [rm for rm in roadmaps if rm.status == "active"]


def get_roadmaps_by_client(
    roadmaps: list[Roadmap],
    client_id: str,
) -> list[Roadmap]:
    return [rm for rm in roadmaps if rm.client_id == client_id]


def get_roadmaps_by_business(
    roadmaps: list[Roadmap],
    business_id: str,
) -> list[Roadmap]:
    return [rm for rm in roadmaps if rm.business_id == business_id]


def get_roadmap_stats(roadmaps: list[Roadmap]) -> dict:
    """Сводная статистика по всем дорожным картам."""
    total     = len(roadmaps)
    active    = sum(1 for r in roadmaps if r.status == "active")
    completed = sum(1 for r in roadmaps if r.status == "completed")
    on_hold   = sum(1 for r in roadmaps if r.status == "on_hold")
    cancelled = sum(1 for r in roadmaps if r.status == "cancelled")

    avg_progress = (
        sum(r.get_progress_pct() for r in roadmaps) / total if total else 0.0
    )

    return {
        "total":       total,
        "active":      active,
        "completed":   completed,
        "on_hold":     on_hold,
        "cancelled":   cancelled,
        "avg_progress": round(avg_progress, 1),
    }


# ─────────────────────────────────────────────────────────────
# Форматирование
# ─────────────────────────────────────────────────────────────

def _progress_bar(pct: float, width: int = 10) -> str:
    """Текстовый прогресс-бар: ████░░░░ 40%"""
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled) + f" {pct:.0f}%"


def format_roadmap_card(roadmap: Roadmap, compact: bool = False) -> str:
    """
    Карточка дорожной карты для Telegram.

    compact=True — короткая версия для списка.
    """
    status_icon = STATUS_ICONS.get(roadmap.status, "❓")
    pct = roadmap.get_progress_pct()
    current = roadmap.get_current_stage()

    if compact:
        cur_name = current.name if current else "Завершено"
        return (
            f"{status_icon} *{roadmap.client_name}* — {cur_name}\n"
            f"   {_progress_bar(pct, 8)} | {roadmap.city}"
        )

    lines = [
        f"{status_icon} *Дорожная карта {roadmap.roadmap_id}*",
        f"👤 Клиент:  {roadmap.client_name}",
        f"📍 Город:   {roadmap.city}",
        f"👔 Ответств: {roadmap.responsible}",
        f"📅 Создана: {roadmap.created_at[:10] if roadmap.created_at else '—'}",
        f"🏁 Срок:    {roadmap.expected_at or '—'}",
        f"",
        f"📊 Прогресс: {_progress_bar(pct)}",
        f"",
        f"*Этапы:*",
    ]

    for s in sorted(roadmap.stages, key=lambda x: x.order):
        icon = STATUS_ICONS.get(s.status, "❓")
        line = f"  {icon} {s.order}. {s.name}"
        if s.status == "in_progress" and s.due_date:
            line += f"  _(до {s.due_date})_"
        if s.is_overdue():
            line += "  ⚠️ просрочен"
        lines.append(line)

    if current:
        lines.extend([
            "",
            f"➡️ *Текущий этап:* {current.name}",
            f"📌 *Следующее действие:*",
            f"   _{get_next_gtd_action(roadmap)}_",
        ])

    if roadmap.notes:
        lines.extend(["", f"📝 {roadmap.notes}"])

    return "\n".join(lines)


def format_roadmap_list(roadmaps: list[Roadmap]) -> str:
    """Краткий список дорожных карт."""
    if not roadmaps:
        return "📋 Нет активных дорожных карт."

    lines = [f"📋 *Дорожные карты ({len(roadmaps)}):*", ""]
    for rm in roadmaps:
        lines.append(format_roadmap_card(rm, compact=True))
    return "\n".join(lines)


def format_roadmap_digest(roadmaps: list[Roadmap]) -> str:
    """
    Дайджест для утреннего обзора:
    - просроченные этапы
    - заблокированные кейсы
    - следующие действия на сегодня
    """
    active = get_active_roadmaps(roadmaps)
    if not active:
        return "📋 Активных дорожных карт нет."

    lines = [f"🗺 *Дорожные карты — дайджест* ({len(active)} активных)", ""]

    # Просроченные
    overdue_items = get_overdue_roadmaps(active)
    if overdue_items:
        lines.append("⚠️ *Просроченные этапы:*")
        for rm, stages in overdue_items:
            for s in stages:
                lines.append(f"  • {rm.client_name} → {s.name} (до {s.due_date})")
        lines.append("")

    # Заблокированные
    blocked = get_blocked_roadmaps(active)
    if blocked:
        lines.append("🔴 *Заблокированные кейсы:*")
        for rm in blocked:
            lines.append(f"  • {rm.client_name} — {rm.city}")
        lines.append("")

    # Следующие действия
    lines.append("➡️ *Следующие действия:*")
    for rm in active[:5]:
        action = get_next_gtd_action(rm)
        lines.append(f"  • {action}")

    stats = get_roadmap_stats(roadmaps)
    lines.extend([
        "",
        f"📊 Всего: {stats['total']} | Активных: {stats['active']} "
        f"| Завершено: {stats['completed']} | Ср. прогресс: {stats['avg_progress']}%",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Phase 7B: Roadmap Templates + Stages
# ═══════════════════════════════════════════════════════════════

ROADMAP_TEMPLATES: dict[str, list[str]] = {
    "legalization_reconstruction_house": [
        "Первичный анализ объекта",
        "Проверка документов клиента",
        "Топографическая съемка",
        "Техническое обследование",
        "Сейсмостойкое заключение",
        "Получение АПЗ",
        "Разработка проекта",
        "Технический паспорт",
        "Исполнительная съемка",
        "Акт ввода в эксплуатацию",
        "Регистрация в НАО",
    ],
    "legalization_new_building": [
        "Первичный анализ объекта",
        "Проверка документов клиента",
        "Получение АПЗ",
        "Разработка проекта",
        "Экспертиза проекта",
        "Уведомление ГАСК",
        "Исполнительная съемка",
        "Технический паспорт",
        "Акт ввода в эксплуатацию",
        "Регистрация в НАО",
    ],
    "legalization_non_residential_reconstruction": [
        "Первичный анализ объекта",
        "Проверка правоустанавливающих документов",
        "Протокол собрания жильцов",
        "Топографическая съемка",
        "Получение АПЗ",
        "Постановление на проектирование",
        "Разработка рабочего проекта",
        "Экспертиза проекта",
        "Уведомление ГАСК",
        "Декларация",
        "Технический паспорт",
        "Землеустроительный проект",
        "Акт ввода в эксплуатацию",
        "Регистрация",
    ],
}


def create_roadmap_stages_from_template(
    roadmap_id: str,
    case_type:  str,
) -> dict:
    """
    Создать этапы roadmap в листе ROADMAP_STAGES по шаблону.

    Returns:
        {
            "ok":           bool,
            "stages_count": int,
            "warning":      str | None,
            "stage_ids":    list[str],
        }
    """
    if not roadmap_id:
        return {
            "ok": False, "stages_count": 0,
            "warning": "roadmap_id не указан", "stage_ids": [],
        }

    stage_names = ROADMAP_TEMPLATES.get(case_type, [])
    if not stage_names:
        return {
            "ok": True, "stages_count": 0,
            "warning": f"Шаблон '{case_type}' не найден — этапы не созданы.",
            "stage_ids": [],
        }

    try:
        from business_core.sheets import (
            append_business_row,
            generate_next_id,
            get_business_sheet,
            row_from_header_map,
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        stage_ids: list[str] = []

        # Phase 10.2B.2: строка формируется по ФАКТИЧЕСКИМ заголовкам
        # листа ROADMAP_STAGES, а не по жёсткой позиции — не зависит от
        # порядка колонок и не молчит, если ожидаемая колонка отсутствует.
        # Заголовки читаются один раз на весь вызов функции.
        sheet   = get_business_sheet("roadmap_stages")
        headers = sheet.row_values(1)

        for order, name in enumerate(stage_names, start=1):
            stage_id = generate_next_id("roadmap_stages")
            values = {
                "Stage ID":   stage_id,
                "Roadmap ID": roadmap_id,
                "Order":      str(order),
                "Name":       name,
                "Status":     "pending",
                # Due Date / Completed At / GTD Action ID / Responsible /
                # Docs Required / Docs Received / Notes намеренно не
                # переданы — остаются "" (как и раньше).
            }
            row = row_from_header_map(headers, values)
            append_business_row("roadmap_stages", row)
            stage_ids.append(stage_id)

        return {
            "ok": True,
            "stages_count": len(stage_ids),
            "warning": None,
            "stage_ids": stage_ids,
        }

    except Exception as exc:
        return {
            "ok": False,
            "stages_count": 0,
            "warning": str(exc),
            "stage_ids": [],
        }


# ═══════════════════════════════════════════════════════════════
# Commercial Milestones — коммерческие этапы оплаты
# ═══════════════════════════════════════════════════════════════

COMMERCIAL_MILESTONES_MAP: dict[str, list[dict]] = {
    "RMT-IZH-ALM-STANDARD-002": [
        {
            "id":           "CM-1",
            "title":        "Анализ / проверка возможности оформления",
            "price":        150_000,
            "currency":     "KZT",
            "stage_orders": list(range(1, 5)),    # этапы 1–4
            "result":       "Понятен путь оформления, риски и возможность запуска следующего этапа.",
            "important":    "Этап 1 не гарантирует получение АПЗ.",
        },
        {
            "id":           "CM-2",
            "title":        "Документы до АПЗ / проектно-разрешительный этап",
            "price":        500_000,
            "currency":     "KZT",
            "stage_orders": list(range(5, 11)),   # этапы 5–10
            "result":       "Пакет подготовлен, подача выполнена, получен результат по АПЗ: АПЗ / замечания / отказ.",
            "important":    "АПЗ зависит от госоргана. При отказе этап считается выполненным, если подготовка и подача сделаны.",
        },
        {
            "id":           "CM-3",
            "title":        "Технический паспорт / акт ввода / регистрация",
            "price":        300_000,
            "currency":     "KZT",
            "stage_orders": list(range(11, 14)),  # этапы 11–13
            "result":       "Объект оформлен и изменения зарегистрированы.",
            "important":    "Финальный этап запускается после оплаты этапа 3.",
        },
    ],
}


def _resolve_template_id(roadmap: dict) -> str:
    """
    Определить template_id для roadmap (read-only, не пишет в Sheets):
    0. из сохранённого поля template_id (колонка Template ID в ROADMAPS)
    1. из notes по паттерну template_id=RMT-... (fallback для старых roadmap)
    2. из default_roadmap_template_id услуги (fallback для старых roadmap)
    3. из первого шаблона, привязанного к service_id (fallback для старых roadmap)
    Возвращает '' если не удалось определить.
    """
    saved = roadmap.get("template_id", "").strip()
    if saved:
        return saved

    import re
    notes = roadmap.get("notes", "")
    m = re.search(r"template_id\s*=\s*(RMT-\S+)", notes, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    service_id = roadmap.get("service_id", "").strip()
    if service_id:
        try:
            from business_core.service_manager import find_service_by_id
            svc = find_service_by_id(service_id)
            if svc:
                tid = svc.get("default_roadmap_template_id", "").strip()
                if tid:
                    return tid
        except Exception:
            pass

        try:
            from business_core.roadmap_template_manager import find_roadmap_templates_by_service
            linked = find_roadmap_templates_by_service(service_id)
            if linked:
                return linked[0].get("template_id", "")
        except Exception:
            pass

    return ""


def get_commercial_milestones_for_roadmap(roadmap_id: str) -> dict:
    """
    Read-only: получить коммерческие этапы оплаты для roadmap.

    Returns:
        {
            "ok":          bool,
            "error":       str | None,
            "roadmap":     dict | None,
            "template_id": str,
            "milestones":  list[dict],  — milestones с loaded_stages и stage_range
            "stages":      list[dict],  — сырые этапы из Sheets
            "total_price": int,
        }
    """
    if not roadmap_id:
        return {
            "ok": False, "error": "roadmap_id не указан", "roadmap": None,
            "template_id": "", "milestones": [], "stages": [], "total_price": 0,
        }

    try:
        # Phase 28E: this used to delegate to business_builder.find_roadmap_by_id
        # (a Core -> orchestration-layer dependency). find_roadmap_by_id is now
        # this module's own canonical function (Phase 28B), defined further down
        # in this same file — no import needed, and no more reverse dependency.
        roadmap = find_roadmap_by_id(roadmap_id)
    except Exception as exc:
        return {
            "ok": False, "error": str(exc), "roadmap": None,
            "template_id": "", "milestones": [], "stages": [], "total_price": 0,
        }

    if not roadmap:
        return {
            "ok": False, "error": f"Roadmap {roadmap_id} не найден",
            "roadmap": None, "template_id": "", "milestones": [], "stages": [], "total_price": 0,
        }

    template_id    = _resolve_template_id(roadmap)
    milestones_cfg = COMMERCIAL_MILESTONES_MAP.get(template_id, [])
    stages         = get_stages_for_roadmap(roadmap_id)

    stage_by_order: dict[int, dict] = {}
    for s in stages:
        try:
            stage_by_order[int(s.get("order", 0))] = s
        except (ValueError, TypeError):
            pass

    populated: list[dict] = []
    for cm in milestones_cfg:
        orders = cm["stage_orders"]
        populated.append({
            **cm,
            "loaded_stages": [stage_by_order[o] for o in orders if o in stage_by_order],
            "stage_range":   f"{orders[0]}–{orders[-1]}" if orders else "",
        })

    total = sum(cm["price"] for cm in milestones_cfg)
    return {
        "ok":          True,
        "error":       None,
        "roadmap":     roadmap,
        "template_id": template_id,
        "milestones":  populated,
        "stages":      stages,
        "total_price": total,
    }


def get_stages_for_roadmap(roadmap_id: str) -> list[dict]:
    """Получить все этапы roadmap из ROADMAP_STAGES."""
    if not roadmap_id:
        return []
    try:
        from business_core.sheets import get_business_sheet
        sheet      = get_business_sheet("roadmap_stages")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []
        headers = all_values[0]

        def _col(h):
            return headers.index(h) if h in headers else None

        def _get(row, h):
            c = _col(h)
            return row[c].strip() if c is not None and c < len(row) else ""

        rm_col  = _col("Roadmap ID")
        results = []
        for row in all_values[1:]:
            if not row or not row[0]:
                continue
            if rm_col is not None and rm_col < len(row) and row[rm_col].strip() == roadmap_id:
                raw_status = _get(row, "Status")
                results.append({
                    "stage_id":   _get(row, "Stage ID"),
                    "roadmap_id": _get(row, "Roadmap ID"),
                    "order":      _get(row, "Order"),
                    "name":       _get(row, "Name"),
                    "status":     normalize_stage_status(raw_status),
                    "raw_status": raw_status,
                    "due_date":   _get(row, "Due Date"),
                    "notes":      _get(row, "Notes"),
                })
        results.sort(key=lambda x: int(x["order"]) if x["order"].isdigit() else 0)
        return results
    except Exception as exc:
        log.warning(f"get_stages_for_roadmap({roadmap_id}) error: {exc}")
        return []


def find_stage_by_id(stage_id: str) -> Optional[dict]:
    """
    Найти один этап по Stage ID в листе ROADMAP_STAGES.

    Read-only. Читает по ФАКТИЧЕСКИМ именам заголовков (не по позиции) —
    тот же паттерн, что и find_roadmap_by_id в business_builder.py, чтобы
    не повторить баг с рассинхроном заголовков и данных (см. RM-027).

    Существующий этап с legacy-статусом (например 'not_started' из
    /newroadmap) читается как есть, без ошибки — статус не валидируется
    здесь, только при записи через update_stage_status_in_sheet.

    Returns:
        dict с полями row_num, stage_id, roadmap_id, order, name, status,
        raw_status, due_date, completed_at, responsible, notes,
        start_date, priority, blocking_reason, docs_required,
        docs_received, checklist_ids — или None, если этап не найден.
        (start_date/priority/blocking_reason/docs_required/docs_received/
        checklist_ids added additively — Closeout Remediation finding #3 —
        so telegram_handlers's read-only /stage display can be migrated
        onto this owner API without losing any field it already shows;
        no existing key removed or renamed.)
    """
    if not stage_id:
        return None

    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("roadmap_stages")
        cell = sheet.find(stage_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)

        wanted = [
            "Stage ID", "Roadmap ID", "Order", "Name", "Status",
            "Due Date", "Completed At", "Responsible", "Notes",
            "Start Date", "Priority", "Blocking Reason",
            "Docs Required", "Docs Received", "Checklist IDs",
        ]
        v = read_row_by_headers(headers, row, wanted)

        return {
            "row_num":         cell.row,
            "stage_id":        v["Stage ID"],
            "roadmap_id":      v["Roadmap ID"],
            "order":           v["Order"],
            "name":            v["Name"],
            "status":          normalize_stage_status(v["Status"]),
            "raw_status":      v["Status"],
            "due_date":        v["Due Date"],
            "completed_at":    v["Completed At"],
            "responsible":     v["Responsible"],
            "notes":           v["Notes"],
            "start_date":      v["Start Date"],
            "priority":        v["Priority"],
            "blocking_reason": v["Blocking Reason"],
            "docs_required":   v["Docs Required"],
            "docs_received":   v["Docs Received"],
            "checklist_ids":   v["Checklist IDs"],
        }

    except Exception as exc:
        log.warning(f"find_stage_by_id({stage_id}) error: {exc}")
        return None


def _stage_update_result(
    *, ok: bool, partial_success: bool, stage_id: str, roadmap_id: str,
    previous_status: str, requested_status: str, final_status: str, changed: bool,
    updated_fields: tuple = (), warnings: tuple = (), errors: tuple = (),
) -> dict:
    """
    Phase 19B-1: shared result-builder for update_stage_status_in_sheet().
    Keeps BOTH the new structured contract (ok/partial_success/previous_status/
    requested_status/final_status/updated_fields/warnings/errors) AND the
    original Phase 9B/14A keys (error/old_status/new_status) so every
    pre-existing caller/test keeps working unchanged, while new callers can
    read the richer, honest contract.
    """
    return {
        "ok": ok,
        "partial_success": partial_success,
        "stage_id": stage_id,
        "roadmap_id": roadmap_id,
        "previous_status": previous_status,
        "requested_status": requested_status,
        "final_status": final_status,
        "changed": changed,
        "updated_fields": tuple(updated_fields),
        "warnings": tuple(warnings),
        "errors": tuple(errors),
        # Backward-compatible aliases (Phase 9B/14A contract, unchanged shape):
        "error": errors[0] if errors else None,
        "old_status": previous_status,
        "new_status": requested_status,
    }


def update_stage_status_in_sheet(
    stage_id: str,
    new_status: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Обновить статус этапа в листе ROADMAP_STAGES (Phase 9B — /updatestage;
    hardened in Phase 19B-1 against partial writes).

    Пишет ТОЛЬКО колонку Status (и, если notes передан явно, колонку
    Notes) — по имени заголовка, точечно в найденную строку. Никакие
    другие колонки (Order, Name, Due Date, Responsible, Docs Required/
    Received, знаниевые поля) и никакие другие строки не трогаются.
    Не пересчитывает Progress %, не меняет статус Roadmap, не пишет
    историю.

    Phase 19B-1: каждая колонка теперь пишется и обрабатывается ИЗОЛИРОВАННО.
    Если Status успешно записан, но последующая запись (Completed At /
    Start Date / Notes) выбрасывает исключение — результат остаётся
    ok=True (запрошенный статус подтверждённо зафиксирован), но
    partial_success=True, и причина попадает в "warnings", а не молча
    теряется и не превращается в ложный "ok=False". Если сама запись
    Status выбрасывает исключение, делается контролируемое повторное
    чтение строки, чтобы честно определить final_status (мог ли статус
    всё же зафиксироваться, несмотря на исключение при отправке запроса) —
    "final_status" никогда не угадывается.

    Args:
        stage_id:   ID этапа (STAGE-...)
        new_status: один из STAGE_STATUS_CANONICAL (pending / in_progress /
                    blocked / done / skipped). Legacy-значения
                    (not_started, completed, waiting) и любые другие
                    строки отклоняются.
        notes:      если передан (не None) — записывается в колонку Notes.
                    Если не передан — колонка Notes не трогается.

    Returns:
        См. _stage_update_result() — новые поля (partial_success,
        previous_status, requested_status, final_status, updated_fields,
        warnings, errors) плюс старые (ok, error, old_status, new_status,
        changed) для обратной совместимости.
    """
    if not stage_id:
        return _stage_update_result(
            ok=False, partial_success=False, stage_id="", roadmap_id="",
            previous_status="", requested_status=new_status, final_status="", changed=False,
            errors=("stage_id не указан",),
        )

    if new_status not in STAGE_STATUS_CANONICAL:
        return _stage_update_result(
            ok=False, partial_success=False, stage_id=stage_id, roadmap_id="",
            previous_status="", requested_status=new_status, final_status="", changed=False,
            errors=(
                f"Недопустимый статус '{new_status}'. "
                f"Допустимые значения: {', '.join(STAGE_STATUS_CANONICAL)}",
            ),
        )

    stage = find_stage_by_id(stage_id)
    if not stage:
        return _stage_update_result(
            ok=False, partial_success=False, stage_id=stage_id, roadmap_id="",
            previous_status="", requested_status=new_status, final_status="", changed=False,
            errors=(f"Этап '{stage_id}' не найден",),
        )

    roadmap_id = stage["roadmap_id"]
    previous_status = stage["status"]

    updated_fields: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("roadmap_stages")
        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        if "Status" not in idx:
            return _stage_update_result(
                ok=False, partial_success=False, stage_id=stage_id, roadmap_id=roadmap_id,
                previous_status=previous_status, requested_status=new_status,
                final_status=previous_status, changed=False,
                errors=("В листе ROADMAP_STAGES отсутствует колонка 'Status'",),
            )

        row_num = stage["row_num"]

        # ── 1. Status: the one write whose success this function must
        #      determine HONESTLY, even if the write call itself raises. ──
        final_status = previous_status
        status_confirmed = False
        try:
            sheet.update_cell(row_num, idx["Status"] + 1, new_status)
            status_confirmed = True
            final_status = new_status
            updated_fields.append("Status")
        except Exception as exc:
            log.error(f"update_stage_status_in_sheet({stage_id}) Status write error: {exc}")
            # Controlled fresh read: did the write actually commit despite
            # the exception (e.g. a timeout on an otherwise-successful
            # request)? Never guess — only trust a successful re-read.
            try:
                fresh = find_stage_by_id(stage_id)
            except Exception as verify_exc:
                fresh = None
                warnings.append(f"Не удалось перепроверить статус после ошибки записи: {verify_exc}")

            if fresh is not None and fresh.get("status") == new_status:
                status_confirmed = True
                final_status = new_status
                updated_fields.append("Status")
                warnings.append(
                    f"Запись Status вызвала ошибку ({exc}), но повторное чтение "
                    f"подтвердило, что статус зафиксирован."
                )
            elif fresh is not None:
                final_status = fresh.get("status", previous_status)
                errors.append(f"Не удалось записать Status: {exc}")
            else:
                final_status = previous_status
                errors.append(f"Не удалось записать Status: {exc}")

            if not status_confirmed:
                return _stage_update_result(
                    ok=False, partial_success=False, stage_id=stage_id, roadmap_id=roadmap_id,
                    previous_status=previous_status, requested_status=new_status,
                    final_status=final_status, changed=(final_status != previous_status),
                    updated_fields=tuple(updated_fields), warnings=tuple(warnings), errors=tuple(errors),
                )

        # From here, the requested Status IS confirmed committed — every
        # remaining write is a SEPARATE, isolated, best-effort secondary
        # field. A failure here never erases the confirmed Status result.
        changed = previous_status != new_status

        # ── 2. Completed At / Start Date autofill (Phase 14A semantics
        #      unchanged: Completed At refilled every 'done' transition;
        #      Start Date filled only once, on first 'in_progress'). ──
        if new_status == "done" and "Completed At" in idx:
            try:
                sheet.update_cell(row_num, idx["Completed At"] + 1, datetime.now().strftime("%Y-%m-%d"))
                updated_fields.append("Completed At")
            except Exception as exc:
                warnings.append(f"Не удалось обновить Completed At: {exc}")

        if new_status == "in_progress" and "Start Date" in idx:
            try:
                current_row = sheet.row_values(row_num)
                start_col = idx["Start Date"]
                current_start = current_row[start_col].strip() if start_col < len(current_row) else ""
                if not current_start:
                    sheet.update_cell(row_num, start_col + 1, datetime.now().strftime("%Y-%m-%d"))
                    updated_fields.append("Start Date")
            except Exception as exc:
                warnings.append(f"Не удалось обновить Start Date: {exc}")

        # ── 3. Notes, only if explicitly supplied. ──
        if notes is not None:
            if "Notes" not in idx:
                warnings.append("В листе ROADMAP_STAGES отсутствует колонка 'Notes' — заметка не сохранена.")
            else:
                try:
                    sheet.update_cell(row_num, idx["Notes"] + 1, notes)
                    updated_fields.append("Notes")
                except Exception as exc:
                    warnings.append(f"Не удалось обновить Notes: {exc}")

        return _stage_update_result(
            ok=True, partial_success=bool(warnings), stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=new_status,
            final_status=final_status, changed=changed,
            updated_fields=tuple(updated_fields), warnings=tuple(warnings), errors=tuple(errors),
        )

    except Exception as exc:
        # Unexpected failure before we even reached the sheet/headers
        # (e.g. get_business_sheet() itself raised) — nothing was written.
        log.error(f"update_stage_status_in_sheet({stage_id}) error: {exc}")
        errors.append(str(exc))
        return _stage_update_result(
            ok=False, partial_success=False, stage_id=stage_id, roadmap_id=roadmap_id,
            previous_status=previous_status, requested_status=new_status,
            final_status=previous_status, changed=False,
            updated_fields=tuple(updated_fields), warnings=tuple(warnings), errors=tuple(errors),
        )


def calculate_progress(stages: list[dict]) -> int:
    """
    Phase 9C: чистая функция расчёта Progress % — без обращения к Sheets.

    Args:
        stages: список dict с ключом 'status' (формат, возвращаемый
                get_stages_for_roadmap).

    Returns:
        Целый процент (0..100), round-half-up:
            total == 0                       -> 0
            done_count / total_count * 100    -> round-half-up (1/8 -> 13, не 12)
        Завершённым считается статус из DONE_SET (done, skipped).
        Любой другой статус (pending, in_progress, blocked, legacy-значения,
        пустые, неизвестные строки) — не завершён.
    """
    total = len(stages)
    if total == 0:
        return 0

    done = sum(1 for s in stages if s.get("status", "") in DONE_SET)
    return math.floor(done / total * 100 + 0.5)


def recalculate_roadmap_progress(roadmap_id: str) -> dict:
    """
    Phase 9C: пересчитать и записать Progress % для roadmap.

    Читает этапы через get_stages_for_roadmap (уже читает по именам
    заголовков), считает процент через calculate_progress(), и пишет
    результат ТОЛЬКО в колонку 'Progress %' листа ROADMAPS — по имени
    заголовка, точечно в найденную строку.

    Не меняет Status roadmap, не меняет строки ROADMAP_STAGES, не пишет
    историю. Идемпотентна: повторный вызов при неизменном состоянии
    этапов даёт тот же процент и не является ошибкой.

    Returns:
        {
            "ok":            bool,
            "error":         str | None,
            "roadmap_id":    str,
            "old_progress":  str,   # как было записано в Sheets (напр. '0')
            "new_progress":  int,
            "done_count":    int,
            "total_count":   int,
            "changed":       bool,
        }
    """
    if not roadmap_id:
        return {"ok": False, "error": "roadmap_id не указан", "roadmap_id": "",
                "old_progress": "", "new_progress": 0, "done_count": 0,
                "total_count": 0, "changed": False}

    stages = get_stages_for_roadmap(roadmap_id)
    total_count = len(stages)
    done_count = sum(1 for s in stages if s.get("status", "") in DONE_SET)
    new_progress = calculate_progress(stages)

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("roadmaps")
        cell = sheet.find(roadmap_id, in_column=1)
        if not cell:
            return {"ok": False, "error": f"Roadmap '{roadmap_id}' не найден",
                    "roadmap_id": roadmap_id, "old_progress": "", "new_progress": new_progress,
                    "done_count": done_count, "total_count": total_count, "changed": False}

        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        if "Progress %" not in idx:
            return {"ok": False, "error": "В листе ROADMAPS отсутствует колонка 'Progress %'",
                    "roadmap_id": roadmap_id, "old_progress": "", "new_progress": new_progress,
                    "done_count": done_count, "total_count": total_count, "changed": False}

        row = sheet.row_values(cell.row)
        col = idx["Progress %"]
        old_progress = row[col].strip() if col < len(row) else ""

        sheet.update_cell(cell.row, col + 1, str(new_progress))

        return {
            "ok": True, "error": None,
            "roadmap_id": roadmap_id,
            "old_progress": old_progress,
            "new_progress": new_progress,
            "done_count": done_count,
            "total_count": total_count,
            "changed": old_progress != str(new_progress),
        }

    except Exception as exc:
        log.error(f"recalculate_roadmap_progress({roadmap_id}) error: {exc}")
        return {"ok": False, "error": str(exc),
                "roadmap_id": roadmap_id, "old_progress": "", "new_progress": new_progress,
                "done_count": done_count, "total_count": total_count, "changed": False}


def should_complete_roadmap(stages: list[dict], progress_pct: int) -> bool:
    """
    Phase 9E.2: чистая функция — определить, завершён ли roadmap.

    Не обращается к Sheets. Roadmap считается завершённым только если
    ОДНОВРЕМЕННО:
      - есть хотя бы один этап;
      - progress_pct == 100;
      - статус КАЖДОГО этапа входит в DONE_SET (done, skipped).

    Legacy-значения (not_started, waiting, "completed" как статус этапа),
    пустые и любые неизвестные строки — не входят в DONE_SET, поэтому
    любой такой этап автоматически даёт False.

    Args:
        stages:       список dict с ключом 'status' (формат
                      get_stages_for_roadmap).
        progress_pct: рассчитанный процент (обычно из calculate_progress).

    Returns:
        bool
    """
    if not stages:
        return False
    if progress_pct != 100:
        return False
    return all(s.get("status", "") in DONE_SET for s in stages)


def maybe_complete_roadmap(
    roadmap_id: str,
    stages: Optional[list[dict]] = None,
    progress_pct: Optional[int] = None,
) -> dict:
    """
    Phase 9E.2: автоматически перевести Roadmap active -> completed,
    если он действительно завершён (см. should_complete_roadmap).

    Если stages/progress_pct не переданы — читает и считает их сама
    (get_stages_for_roadmap + calculate_progress), чтобы не заставлять
    вызывающего дублировать логику, если он ими не располагает.

    Пишет ТОЛЬКО колонку Status в найденной строке ROADMAPS, и только
    в направлении active -> completed:
      - Status уже 'completed'      -> идемпотентный результат, без записи;
      - Status любой другой (кроме active/completed, напр. draft/paused/
        cancelled) -> НЕ меняется, без записи;
      - Status == 'active', но условия завершения не выполнены -> без записи;
      - Status == 'active' и условия выполнены -> записывает 'completed'.

    Никогда не переводит completed обратно в active. Не трогает Progress %,
    не трогает ROADMAP_STAGES, не трогает другие roadmap, не пишет историю.

    Returns:
        {
            "ok":         bool,
            "error":      str | None,
            "roadmap_id": str,
            "old_status": str,
            "new_status": str,
            "changed":    bool,
        }
    """
    if not roadmap_id:
        return {"ok": False, "error": "roadmap_id не указан", "roadmap_id": "",
                "old_status": "", "new_status": "", "changed": False}

    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("roadmaps")
        cell = sheet.find(roadmap_id, in_column=1)
        if not cell:
            return {"ok": False, "error": f"Roadmap '{roadmap_id}' не найден",
                    "roadmap_id": roadmap_id, "old_status": "", "new_status": "", "changed": False}

        headers = sheet.row_values(1)
        idx = get_header_index_map(headers)

        if "Status" not in idx:
            return {"ok": False, "error": "В листе ROADMAPS отсутствует колонка 'Status'",
                    "roadmap_id": roadmap_id, "old_status": "", "new_status": "", "changed": False}

        row = sheet.row_values(cell.row)
        current_status = row[idx["Status"]].strip() if idx["Status"] < len(row) else ""

        if current_status == "completed":
            return {"ok": True, "error": None, "roadmap_id": roadmap_id,
                    "old_status": "completed", "new_status": "completed", "changed": False}

        if current_status != "active":
            return {"ok": True, "error": None, "roadmap_id": roadmap_id,
                    "old_status": current_status, "new_status": current_status, "changed": False}

        if stages is None:
            stages = get_stages_for_roadmap(roadmap_id)
        if progress_pct is None:
            progress_pct = calculate_progress(stages)

        if not should_complete_roadmap(stages, progress_pct):
            return {"ok": True, "error": None, "roadmap_id": roadmap_id,
                    "old_status": "active", "new_status": "active", "changed": False}

        sheet.update_cell(cell.row, idx["Status"] + 1, "completed")

        return {"ok": True, "error": None, "roadmap_id": roadmap_id,
                "old_status": "active", "new_status": "completed", "changed": True}

    except Exception as exc:
        log.error(f"maybe_complete_roadmap({roadmap_id}) error: {exc}")
        return {"ok": False, "error": str(exc), "roadmap_id": roadmap_id,
                "old_status": "", "new_status": "", "changed": False}


# ═══════════════════════════════════════════════════════════════
# Phase 28B: Canonical Sheets-facing Roadmap/Roadmap Stage API.
#
# Additive only — no existing caller is rewired to these functions in
# this phase (Phase 28C+ will do that). This is deliberately a
# low-level persistence API: it does not validate that Business/
# Client/Object/Service IDs actually exist elsewhere (that FK-existence
# check stays in the orchestration layer, business_builder.py, per the
# Phase 27B architecture decision — adding it here would create a new
# cross-domain dependency this module must not have), never copies
# Stage Entity Relations or Knowledge (Extension-layer concerns, wired
# by the orchestrator in a later phase), and never imports
# business_core.telegram_handlers or business_core.business_builder.
# ═══════════════════════════════════════════════════════════════

def find_roadmap_by_id(roadmap_id: str) -> Optional[dict]:
    """
    Canonical, header-mapped single-row read of ROADMAPS by Roadmap ID.

    Mirrors the read pattern already used by find_stage_by_id() in this
    same module (targeted sheet.find() + read_row_by_headers(), never a
    positional-index assumption — see RM-027 in business_builder.py for
    why that matters). This is an independent implementation, not a
    delegation to business_builder.find_roadmap_by_id() — Phase 27B
    decided business_builder.py will eventually call INTO this module,
    not the other way around.

    Returns:
        dict с полями row_num, roadmap_id, business_id, service_id,
        client_id, client_name, status, created, object_id,
        parent_roadmap_id, case_type, template_id, progress, notes,
        city, legacy_stage_statuses (list of 10 strings — the legacy
        "Stage 1 Status".."Stage 10 Status" per-roadmap columns, kept
        for callers like /roadmaps that still display them; the source
        of truth for stage state is ROADMAP_STAGES, read via
        get_stages_for_roadmap()/find_stage_by_id(), never this list)
        — или None, если roadmap не найден.
    """
    if not roadmap_id:
        return None

    try:
        from business_core.sheets import get_business_sheet, read_row_by_headers

        sheet = get_business_sheet("roadmaps")
        cell = sheet.find(roadmap_id, in_column=1)
        if not cell:
            return None

        headers = sheet.row_values(1)
        row = sheet.row_values(cell.row)

        stage_status_headers = [f"Stage {i} Status" for i in range(1, 11)]
        wanted = [
            "Roadmap ID", "Business ID", "Service ID", "Client ID", "Client Name",
            "Status", "Created", "Object ID", "Parent Roadmap ID", "Case Type",
            "Template ID", "Progress %", "Notes", "City",
        ] + stage_status_headers
        v = read_row_by_headers(headers, row, wanted)

        return {
            "row_num":               cell.row,
            "roadmap_id":            v["Roadmap ID"],
            "business_id":           v["Business ID"],
            "service_id":            v["Service ID"],
            "client_id":             v["Client ID"],
            "client_name":           v["Client Name"],
            "status":                normalize_roadmap_status(v["Status"]),
            "raw_status":            v["Status"],
            "created":               v["Created"],
            "object_id":             v["Object ID"],
            "parent_roadmap_id":     v["Parent Roadmap ID"],
            "case_type":             v["Case Type"],
            "template_id":           v["Template ID"],
            "progress":              v["Progress %"],
            "notes":                 v["Notes"],
            "city":                  v["City"],
            "legacy_stage_statuses": [v[h] for h in stage_status_headers],
        }

    except Exception as exc:
        log.warning(f"find_roadmap_by_id({roadmap_id}) error: {exc}")
        return None


def list_roadmaps(
    business_id: Optional[str] = None,
    client_id: Optional[str] = None,
    object_id: Optional[str] = None,
    service_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    """
    Canonical, header-mapped listing of ROADMAPS, optionally filtered by
    any combination of the given fields (all AND-combined; a filter
    left as None is not applied). Deliberately no query DSL beyond
    this — every filter this module's own callers need today is a
    simple equality match on one column.

    Returns rows in the same dict shape as find_roadmap_by_id(), each
    additionally carrying "row_num".
    """
    try:
        from business_core.sheets import get_business_sheet, get_header_index_map

        sheet = get_business_sheet("roadmaps")
        all_values = sheet.get_all_values()
        if len(all_values) < 2:
            return []

        headers = all_values[0]
        idx = get_header_index_map(headers)

        def _get(row: list[str], header: str) -> str:
            col = idx.get(header)
            return row[col].strip() if col is not None and col < len(row) else ""

        results: list[dict] = []
        for row_num, row in enumerate(all_values[1:], start=2):
            if not row or not row[0].strip():
                continue

            candidate = {
                "row_num":           row_num,
                "roadmap_id":        _get(row, "Roadmap ID"),
                "business_id":       _get(row, "Business ID"),
                "service_id":        _get(row, "Service ID"),
                "client_id":         _get(row, "Client ID"),
                "client_name":       _get(row, "Client Name"),
                "status":            normalize_roadmap_status(_get(row, "Status")),
                "raw_status":        _get(row, "Status"),
                "created":           _get(row, "Created"),
                "object_id":         _get(row, "Object ID"),
                "parent_roadmap_id": _get(row, "Parent Roadmap ID"),
                "case_type":         _get(row, "Case Type"),
                "template_id":       _get(row, "Template ID"),
                "progress":          _get(row, "Progress %"),
                "notes":             _get(row, "Notes"),
                "city":              _get(row, "City"),
                "legacy_stage_statuses": [_get(row, f"Stage {i} Status") for i in range(1, 11)],
            }

            if business_id is not None and candidate["business_id"] != business_id:
                continue
            if client_id is not None and candidate["client_id"] != client_id:
                continue
            if object_id is not None and candidate["object_id"] != object_id:
                continue
            if service_id is not None and candidate["service_id"] != service_id:
                continue
            if status is not None and candidate["status"] != status:
                continue

            results.append(candidate)

        return results

    except Exception as exc:
        log.warning(f"list_roadmaps(...) error: {exc}")
        return []


def find_active_roadmap_for_object(object_id: str, service_id: str) -> Optional[dict]:
    """
    Read-only duplicate-detection primitive: is there already an ACTIVE
    Roadmap for this (Object ID, Service ID) pair?

    Duplicate key: (Object ID, Service ID) — matches the same
    "only active rows count as a duplicate" convention already used by
    business_core.stage_entity_relations.find_active_duplicate_relation()
    and business_core.organization_manager's assignment layer.

    This phase adds the read primitive only. No caller is wired to
    reject a duplicate yet — that orchestration policy is Phase 28G's
    job, applied in business_builder.py, per the Phase 27B decision.

    Returns:
        The first matching active Roadmap row (same dict shape as
        find_roadmap_by_id()), or None if no active Roadmap exists for
        this Object+Service.
    """
    if not object_id or not service_id:
        return None

    matches = list_roadmaps(object_id=object_id, service_id=service_id, status="active")
    return matches[0] if matches else None


def find_open_roadmaps_for_object(
    object_id: str,
    service_id: str,
    open_statuses: tuple[str, ...] = ("active", "on_hold"),
) -> list[dict]:
    """
    Read-only, parametrized duplicate-detection primitive (Phase 33C,
    ADR-016 Decision 9): all Roadmaps for (Object ID, Service ID) whose
    status is one of `open_statuses`.

    Deliberately a pure read primitive, not a policy decision — WHICH
    statuses count as "open" (blocking a second Roadmap for the same
    key) is an orchestration-layer choice, made by the caller
    (business_core.business_builder.create_roadmap_for_object()), not
    by this module. The default of ("active", "on_hold") matches
    ADR-016's approved default only for caller convenience; it is not
    hardcoded policy here.

    Unlike find_active_roadmap_for_object() (kept unchanged, still
    "active"-only, for any existing caller depending on that exact
    behavior), this function returns ALL matches rather than just the
    first — so the caller can detect and reject >1 open Roadmaps for
    the same key rather than silently using one.

    Returns:
        list[dict], same shape as find_roadmap_by_id(), in sheet order.
        Empty list if object_id/service_id missing or no match.
    """
    if not object_id or not service_id:
        return []

    matches = list_roadmaps(object_id=object_id, service_id=service_id)
    return [r for r in matches if r.get("status") in open_statuses]


def create_roadmap_record(
    *,
    business_id: str,
    client_id: str,
    object_id: str,
    service_id: str = "",
    template_id: str = "",
    city: str = "",
    client_name: str = "",
    case_type: str = "",
    notes: str = "",
    status: str = "active",
) -> dict:
    """
    Canonical, header-mapped creation of exactly one ROADMAPS row.

    Low-level persistence only — deliberately does NOT:
      - verify that business_id/client_id/object_id/service_id/
        template_id actually exist elsewhere (presence-only validation
        here; existence-checking is an orchestration-layer concern,
        wired in business_builder.py starting Phase 28C, per the
        Phase 27B architecture decision — adding it here would give
        this module a new cross-domain dependency it must not have);
      - check for an existing active Roadmap for this Object+Service
        (see find_active_roadmap_for_object() — enforcing that as a
        rejection policy is Phase 28G's job, in the orchestrator);
      - create any ROADMAP_STAGES rows (see ensure_roadmap_stages());
      - call anything in business_core.stage_entity_relations,
        business_core.knowledge_manager, business_core.business_builder,
        or business_core.telegram_handlers.

    Required: business_id, client_id, object_id (non-empty strings).
    `status` must be one of ROADMAP_STATUSES.

    Returns:
        {
            "ok":         bool,
            "roadmap_id": str,
            "roadmap":    dict | None,  # same shape as find_roadmap_by_id()
            "error":      str | None,
        }
    """
    if not business_id or not client_id or not object_id:
        return {
            "ok": False, "roadmap_id": "", "roadmap": None,
            "error": "Обязательные поля: business_id, client_id, object_id",
        }

    if status not in ROADMAP_STATUSES:
        return {
            "ok": False, "roadmap_id": "", "roadmap": None,
            "error": f"Status must be one of {ROADMAP_STATUSES}, got {status!r}",
        }

    try:
        from business_core.sheets import (
            append_business_row, generate_next_id, get_business_sheet, row_from_header_map,
        )

        now = datetime.now().strftime("%Y-%m-%d")
        roadmap_id = generate_next_id("roadmaps")

        if not client_name:
            client_name = f"Roadmap {object_id}" + (f" / {service_id}" if service_id else "")

        sheet = get_business_sheet("roadmaps")
        headers = sheet.row_values(1)

        values = {
            "Roadmap ID":        roadmap_id,
            "Business ID":       business_id,
            "Service ID":        service_id,
            "City":              city,
            "Client ID":         client_id,
            "Client Name":       client_name,
            "GTD Project ID":    "",
            "Responsible":       "",
            "Status":            status,
            "Created":           now,
            "Expected":          "",
            "Progress %":        "0",
            "Notes":             notes,
            "Last Updated":      now,
            "Object ID":         object_id,
            "Parent Roadmap ID": "",
            "Case Type":         case_type,
            "Template ID":       template_id,
        }

        try:
            row = row_from_header_map(headers, values)
        except ValueError as header_exc:
            log.error(f"create_roadmap_record: {header_exc}")
            return {"ok": False, "roadmap_id": "", "roadmap": None, "error": str(header_exc)}

        append_business_row("roadmaps", row)
        log.info(f"create_roadmap_record: {roadmap_id} / {object_id} / {service_id}")

        roadmap = {
            "row_num": None,
            "roadmap_id": roadmap_id,
            "business_id": business_id,
            "service_id": service_id,
            "client_id": client_id,
            "client_name": client_name,
            "status": status,
            "created": now,
            "object_id": object_id,
            "parent_roadmap_id": "",
            "case_type": case_type,
            "template_id": template_id,
            "progress": "0",
            "notes": notes,
        }
        return {"ok": True, "roadmap_id": roadmap_id, "roadmap": roadmap, "error": None}

    except Exception as exc:
        log.error(f"create_roadmap_record error: {exc}")
        return {"ok": False, "roadmap_id": "", "roadmap": None, "error": str(exc)}


def ensure_roadmap_stages(
    roadmap_id: str,
    template_stage_rows: list[dict],
) -> dict:
    """
    Idempotent, canonical creation of ROADMAP_STAGES rows for an
    existing roadmap_id, from already-read Template Stage rows (e.g.
    business_core.roadmap_template_manager.find_template_stages()'s
    return shape — this function deliberately accepts already-resolved
    rows rather than a template_id, so this module never has to import
    roadmap_template_manager to read ROADMAP_TEMPLATE_STAGES itself;
    the orchestrator reads the template stages and passes them in).

    Stage uniqueness key: (Roadmap ID, Order). A stage whose Order
    already exists among this roadmap_id's current stages is treated
    as already created and skipped — never duplicated. Only Orders
    missing from the existing set are written. Calling this function
    twice with the same arguments creates nothing the second time.

    New stages are always written with Status "pending" (validated
    against STAGE_STATUS_CANONICAL) — never the legacy "not_started"
    value that /newroadmap still seeds.

    Does not copy Stage Entity Relations or Knowledge, and does not
    call business_core.stage_entity_relations, business_core.
    knowledge_manager, business_core.business_builder, or business_core.
    telegram_handlers — those are Extension-layer/orchestration
    concerns wired by the caller in a later phase.

    If a template_stage_rows entry also carries any of "sop_ids",
    "checklist_ids", "material_ids", "document_template_ids", "faq_ids"
    (each a list[str] — the shape business_core.roadmap_template_manager.
    find_template_stages() returns since Phase 28E), those are merged
    into the new stage row's own "SOP IDs"/"Checklist IDs"/
    "Materials IDs"/"Document Template IDs"/"FAQ IDs" columns exactly
    as business_core.roadmap_template_manager.create_stages_from_template_record()
    used to do internally — this is a same-registry field copy, not an
    Extension call.

    Returns:
        {
            "ok":                   bool,
            "roadmap_id":           str,
            "created_stage_ids":    list[str],
            "created_from_orders":  list[int],  # parallel to created_stage_ids —
                                                  # the Order each created stage
                                                  # came from, so a caller can map
                                                  # a new stage_id back to its
                                                  # source template_stage_rows entry
            "existing_stage_ids":   list[str],
            "created_count":        int,
            "existing_count":       int,
            "total_count":          int,
            "error":                str | None,
        }
    """
    empty_result = {
        "ok": True, "roadmap_id": roadmap_id,
        "created_stage_ids": [], "created_from_orders": [], "existing_stage_ids": [],
        "created_count": 0, "existing_count": 0, "total_count": 0,
        "error": None,
    }

    if not roadmap_id:
        return {**empty_result, "ok": False, "error": "roadmap_id не указан"}

    if "pending" not in STAGE_STATUS_CANONICAL:
        # Defensive — STAGE_STATUS_CANONICAL is a module constant that
        # should never actually change without deliberate review, but a
        # write function should never silently write a value its own
        # canonical set doesn't recognize.
        return {**empty_result, "ok": False,
                "error": "'pending' отсутствует в STAGE_STATUS_CANONICAL"}

    existing = get_stages_for_roadmap(roadmap_id)
    existing_stage_ids = [s.get("stage_id", "") for s in existing]
    existing_orders = {
        int(s["order"]) for s in existing
        if str(s.get("order", "")).isdigit()
    }

    if not template_stage_rows:
        return {
            **empty_result,
            "existing_stage_ids": existing_stage_ids,
            "existing_count": len(existing_stage_ids),
            "total_count": len(existing_stage_ids),
        }

    to_create: list[dict] = []
    seen_orders: set[int] = set()
    for tmpl_row in template_stage_rows:
        raw_order = str(tmpl_row.get("order", "")).strip()
        if not raw_order.isdigit():
            continue
        order = int(raw_order)
        if order in existing_orders or order in seen_orders:
            continue
        seen_orders.add(order)
        to_create.append(tmpl_row)

    if not to_create:
        return {
            **empty_result,
            "existing_stage_ids": existing_stage_ids,
            "existing_count": len(existing_stage_ids),
            "total_count": len(existing_stage_ids),
        }

    try:
        from business_core.sheets import (
            batch_append_business_rows, generate_next_ids, get_business_sheet, row_from_header_map,
        )

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        sheet = get_business_sheet("roadmap_stages")
        headers = sheet.row_values(1)
        new_stage_ids = generate_next_ids("roadmap_stages", len(to_create))

        rows = []
        created_from_orders: list[int] = []
        for tmpl_row, stage_id in zip(to_create, new_stage_ids):
            order = int(str(tmpl_row.get("order", "")).strip())
            values = {
                "Stage ID":       stage_id,
                "Roadmap ID":     roadmap_id,
                "Order":          str(order),
                "Name":           tmpl_row.get("stage_name", ""),
                "Status":         "pending",
                "Docs Required":  tmpl_row.get("required_docs", ""),
                "Responsible":    tmpl_row.get("responsible", ""),
                "Notes":          tmpl_row.get("notes", ""),
                # Phase 8C knowledge bindings — same-registry field copy
                # from the template stage row, not an Extension call
                # (see this function's docstring).
                "SOP IDs":               ",".join(tmpl_row.get("sop_ids", [])),
                "Checklist IDs":         ",".join(tmpl_row.get("checklist_ids", [])),
                "Materials IDs":         ",".join(tmpl_row.get("material_ids", [])),
                "Document Template IDs": ",".join(tmpl_row.get("document_template_ids", [])),
                "FAQ IDs":               ",".join(tmpl_row.get("faq_ids", [])),
            }
            rows.append(row_from_header_map(headers, values))
            created_from_orders.append(order)

        batch_append_business_rows("roadmap_stages", rows)

        created_stage_ids = list(new_stage_ids)
        log.info(
            f"ensure_roadmap_stages: roadmap={roadmap_id} "
            f"created={len(created_stage_ids)} existing={len(existing_stage_ids)}"
        )

        return {
            "ok": True, "roadmap_id": roadmap_id,
            "created_stage_ids": created_stage_ids,
            "created_from_orders": created_from_orders,
            "existing_stage_ids": existing_stage_ids,
            "created_count": len(created_stage_ids),
            "existing_count": len(existing_stage_ids),
            "total_count": len(existing_stage_ids) + len(created_stage_ids),
            "error": None,
        }

    except Exception as exc:
        log.error(f"ensure_roadmap_stages({roadmap_id}) error: {exc}")
        return {
            "ok": False, "roadmap_id": roadmap_id,
            "created_stage_ids": [], "created_from_orders": [], "existing_stage_ids": existing_stage_ids,
            "created_count": 0, "existing_count": len(existing_stage_ids),
            "total_count": len(existing_stage_ids),
            "error": str(exc),
        }


_STAGE_FIELD_UPDATE_ALLOWED_COLUMNS = {
    "Responsible", "Due Date", "Priority", "Blocking Reason",
}


def update_stage_fields(stage_id: str, writes: dict) -> dict:
    """
    Phase 28D: canonical point-write of one or more ROADMAP_STAGES
    administrative field(s) — the shared write primitive behind
    /assignstage, /duedate, /priority, and the admin-field half of
    /blockstage, /unblockstage, replacing telegram_handlers.
    _stage_edit_execute's former direct Sheets access.

    Restricted to a fixed column allowlist (Responsible, Due Date,
    Priority, Blocking Reason) — the same Phase 14A Stage Management
    Core columns this write path has always been scoped to; any other
    key in `writes` is silently ignored, exactly matching the prior
    behavior for non-Status keys.

    Phase 34C (ADR-017 §13/§20): "Status" is no longer part of this
    function's editable set at all — it used to accept a validated
    Status value directly, but that made this the second place (besides
    update_stage_status_in_sheet) capable of changing a Stage's Status,
    with zero Roadmap-eligibility or transition-matrix awareness. A
    "Status" key in `writes` is now REJECTED outright (ok=False, before
    touching Sheets), regardless of value — Status changes must go
    through business_core.business_builder.transition_stage_status(),
    the sole canonical transition-orchestration boundary (ADR-017 §2/§6).

    Re-reads the row via find_row_by_id() immediately before writing
    (staleness guard — Read-before-Write, ENGINEERING_STANDARDS.md),
    header-mapped, never a positional column assumption.

    Returns:
        {"ok": bool, "stage_id": str, "written_fields": tuple, "error": str | None}
    """
    if not stage_id:
        return {"ok": False, "stage_id": stage_id, "written_fields": (), "error": "stage_id обязателен"}

    if "Status" in (writes or {}):
        return {
            "ok": False, "stage_id": stage_id, "written_fields": (),
            "error": (
                "Status нельзя изменить через update_stage_fields — "
                "используйте business_builder.transition_stage_status()."
            ),
        }

    try:
        from business_core.sheets import find_row_by_id, get_business_sheet

        found = find_row_by_id("roadmap_stages", stage_id)
        if not found:
            return {"ok": False, "stage_id": stage_id, "written_fields": (),
                     "error": f"Этап {stage_id} больше не найден — изменение не выполнено."}

        row_number, _live_row = found
        sheet = get_business_sheet("roadmap_stages")
        headers = sheet.row_values(1)

        def _col(name):
            return headers.index(name) + 1 if name in headers else None

        written = []
        for column_name, value in (writes or {}).items():
            if column_name not in _STAGE_FIELD_UPDATE_ALLOWED_COLUMNS:
                continue
            col = _col(column_name)
            if col:
                sheet.update_cell(row_number, col, value)
                written.append(column_name)

        return {"ok": True, "stage_id": stage_id, "written_fields": tuple(written), "error": None}

    except Exception as exc:
        log.error(f"update_stage_fields({stage_id}) error: {exc}")
        return {"ok": False, "stage_id": stage_id, "written_fields": (), "error": str(exc)}
