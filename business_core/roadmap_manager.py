"""
Roadmap Manager — дорожные карты по клиентам, услугам и проектам.

Не обращается к Google Sheets (это задача sheets.py).
Не обращается к Telegram.
Только чистая Python-логика над объектами Roadmap/RoadmapStage.

Связи:
  business_id  → business_registry
  service_id   → service_catalog
  client_id    → people_registry
  gtd_project_id → Google Sheets PROJECTS (через GTD Master)
"""

from __future__ import annotations

import re
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
        from business_core.sheets import append_business_row, generate_next_id
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        stage_ids: list[str] = []

        for order, name in enumerate(stage_names, start=1):
            stage_id = generate_next_id("roadmap_stages")
            row = [
                stage_id,     # Stage ID
                roadmap_id,   # Roadmap ID
                str(order),   # Order
                name,         # Name
                "pending",    # Status
                "",           # Due Date
                "",           # Completed At
                "",           # GTD Action ID
                "",           # Responsible
                "",           # Docs Required
                "",           # Docs Received
                "",           # Notes
            ]
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
    1. из notes по паттерну template_id=RMT-...
    2. из default_roadmap_template_id услуги
    3. из первого шаблона, привязанного к service_id
    Возвращает '' если не удалось определить.
    """
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
        from business_core.business_builder import find_roadmap_by_id as _find_rm
        roadmap = _find_rm(roadmap_id)
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

    # Для отображения commercial milestones не требуется читать весь
    # ROADMAP_STAGES. Диапазоны этапов уже заданы в mapping.
    # Это исключает лишний Google Sheets API request и зависания команды.
    stages: list[dict] = []
    stage_by_order: dict[int, dict] = {}

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
                results.append({
                    "stage_id":   _get(row, "Stage ID"),
                    "roadmap_id": _get(row, "Roadmap ID"),
                    "order":      _get(row, "Order"),
                    "name":       _get(row, "Name"),
                    "status":     _get(row, "Status"),
                    "due_date":   _get(row, "Due Date"),
                    "notes":      _get(row, "Notes"),
                })
        results.sort(key=lambda x: int(x["order"]) if x["order"].isdigit() else 0)
        return results
    except Exception as exc:
        log.warning(f"get_stages_for_roadmap({roadmap_id}) error: {exc}")
        return []
