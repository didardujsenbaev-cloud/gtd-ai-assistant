"""
Material Manager — привязка файлов, документов, фото и ссылок
к бизнесу, клиенту, дорожной карте и этапу.

Логика интеграции с существующим GTD:
  - В GTD файлы попадают через handle_document() / handle_photo() → REFERENCE sheet
  - Material Manager добавляет бизнес-контекст к уже сохранённому GTD-Reference
  - Поле gtd_reference_row — номер строки в GTD REFERENCE (для обратной связи)
  - Поле drive_url — ссылка на Google Drive (если файл уже загружен через upload_pdf_to_drive)

Не обращается к Google Sheets, Telegram, Google Drive API напрямую.
Только чистая Python-логика. Интеграция — через business_core/sheets.py.

Статусы материала:
  received  — получен, не проверен
  checked   — проверен сотрудником
  approved  — принят (документ подходит)
  rejected  — не подходит (запросить заново)
  archived  — в архиве (кейс закрыт)
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Константы
# ─────────────────────────────────────────────────────────────

MATERIAL_STATUSES = ("received", "checked", "approved", "rejected", "archived")

MATERIAL_SOURCES = (
    "Telegram",
    "Google Drive",
    "WhatsApp",
    "Email",
    "Manual",
    "Scanner",
    "Other",
)

FILE_TYPES = (
    "pdf",
    "photo",
    "document",     # .docx / .doc / .txt
    "spreadsheet",  # .xlsx / .xls
    "contract",     # договор (определяется по имени)
    "passport",     # удостоверение / паспорт
    "certificate",  # свидетельство / справка
    "techpassport", # техпаспорт
    "act",          # акт
    "archive",      # .zip / .rar
    "other",
)

STATUS_ICONS = {
    "received":  "📥",
    "checked":   "👁",
    "approved":  "✅",
    "rejected":  "❌",
    "archived":  "🗄",
}

FILE_ICONS = {
    "pdf":         "📄",
    "photo":       "🖼",
    "document":    "📝",
    "spreadsheet": "📊",
    "contract":    "📋",
    "passport":    "🪪",
    "certificate": "📜",
    "techpassport":"🏠",
    "act":         "📃",
    "archive":     "📦",
    "other":       "📎",
}

# Ключевые слова для авто-классификации типа документа (в именах файлов)
_TYPE_KEYWORDS: list[tuple[list[str], str]] = [
    (["техпаспорт", "техпасп", "tech_pass", "techpass"], "techpassport"),
    (["договор", "dogovor", "contract"],              "contract"),
    (["паспорт", "удостоверение", "passport", "id_"], "passport"),
    (["свидетельство", "справка", "certificate"],     "certificate"),
    (["акт", "act_", "_act"],                         "act"),
]

_MIME_TO_TYPE: dict[str, str] = {
    "application/pdf":                                "pdf",
    "image/jpeg":                                     "photo",
    "image/png":                                      "photo",
    "image/heic":                                     "photo",
    "image/webp":                                     "photo",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/msword":                             "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":       "spreadsheet",
    "application/vnd.ms-excel":                       "spreadsheet",
    "text/plain":                                     "document",
    "application/zip":                                "archive",
    "application/x-rar-compressed":                  "archive",
}

_EXT_TO_TYPE: dict[str, str] = {
    ".pdf":  "pdf",
    ".jpg":  "photo", ".jpeg": "photo", ".png": "photo",
    ".heic": "photo", ".webp": "photo",
    ".docx": "document", ".doc": "document", ".txt": "document",
    ".xlsx": "spreadsheet", ".xls": "spreadsheet",
    ".zip":  "archive", ".rar": "archive",
}


# ─────────────────────────────────────────────────────────────
# Dataclass
# ─────────────────────────────────────────────────────────────

@dataclass
class Material:
    material_id:       str
    source:            str              # Telegram / Google Drive / WhatsApp ...
    received_at:       str              # ISO datetime
    file_type:         str = "other"
    filename:          str = ""
    file_size_kb:      int = 0
    drive_url:         str = ""

    # GTD-связи (заполняются из существующей GTD-системы)
    gtd_reference_row: int = 0          # строка в REFERENCE sheet
    gtd_project_id:    str = ""         # ID GTD-проекта

    # Business Core-связи
    business_id:       str = ""
    service_id:        str = ""
    city:              str = ""
    client_id:         str = ""
    roadmap_id:        str = ""
    stage_id:          str = ""

    # Статус
    status:            str = "received"
    checked_by:        str = ""
    approved_at:       str = ""
    notes:             str = ""
    tags:              list[str] = field(default_factory=list)

    def is_linked(self) -> bool:
        """Привязан ли материал к бизнес-контексту."""
        return bool(self.business_id or self.roadmap_id or self.client_id)

    def is_pending(self) -> bool:
        """Ожидает проверки."""
        return self.status == "received"

    def to_dict(self) -> dict:
        return {
            "material_id":        self.material_id,
            "source":             self.source,
            "received_at":        self.received_at,
            "gtd_reference_row":  str(self.gtd_reference_row),
            "gtd_project_id":     self.gtd_project_id,
            "business_id":        self.business_id,
            "service_id":         self.service_id,
            "city":               self.city,
            "client_id":          self.client_id,
            "roadmap_id":         self.roadmap_id,
            "stage_id":           self.stage_id,
            "file_type":          self.file_type,
            "drive_url":          self.drive_url,
            "filename":           self.filename,
            "file_size_kb":       str(self.file_size_kb),
            "status":             self.status,
            "checked_by":         self.checked_by,
            "approved_at":        self.approved_at,
            "notes":              self.notes,
        }


# ─────────────────────────────────────────────────────────────
# ID-генератор
# ─────────────────────────────────────────────────────────────

_mat_counter = 0


def _next_mat_id() -> str:
    global _mat_counter
    _mat_counter += 1
    return f"MAT-{_mat_counter:04d}"


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ─────────────────────────────────────────────────────────────
# Классификация типа файла
# ─────────────────────────────────────────────────────────────

def classify_file_type(
    filename: str = "",
    mime_type: str = "",
) -> str:
    """
    Определить тип файла по имени и/или MIME-типу.

    Порядок приоритетов:
      1. Ключевые слова в имени файла (наиболее специфично)
      2. MIME-тип
      3. Расширение файла
      4. "other"
    """
    name_lower = filename.lower()

    # 1. Ключевые слова
    for keywords, ftype in _TYPE_KEYWORDS:
        if any(kw in name_lower for kw in keywords):
            return ftype

    # 2. MIME-тип
    if mime_type and mime_type in _MIME_TO_TYPE:
        return _MIME_TO_TYPE[mime_type]

    # 3. Расширение
    _, ext = os.path.splitext(name_lower)
    if ext in _EXT_TO_TYPE:
        return _EXT_TO_TYPE[ext]

    return "other"


# ─────────────────────────────────────────────────────────────
# Создание и обновление записей
# ─────────────────────────────────────────────────────────────

def create_material_record(
    source:            str,
    filename:          str = "",
    mime_type:         str = "",
    file_size_kb:      int = 0,
    drive_url:         str = "",
    gtd_reference_row: int = 0,
    gtd_project_id:    str = "",
    business_id:       str = "",
    service_id:        str = "",
    city:              str = "",
    client_id:         str = "",
    roadmap_id:        str = "",
    stage_id:          str = "",
    notes:             str = "",
    material_id:       Optional[str] = None,
    received_at:       Optional[str] = None,
) -> Material:
    """
    Создать запись материала.

    Args:
        source:            Telegram / Google Drive / WhatsApp / Email / Manual
        filename:          Имя файла (для определения типа)
        mime_type:         MIME-тип (для определения типа)
        file_size_kb:      Размер в KB
        drive_url:         Ссылка на Google Drive (если уже загружен)
        gtd_reference_row: Строка в GTD REFERENCE sheet (связь с существующей системой)
        gtd_project_id:    ID GTD-проекта
        business_id:       BIZ-001 и т.д.
        service_id:        SVC-001 и т.д.
        city:              Город
        client_id:         PRS-001 и т.д.
        roadmap_id:        RM-001 и т.д.
        stage_id:          STAGE-001-03 и т.д.
        notes:             Заметки
        material_id:       Принудительно задать ID (для тестов)
        received_at:       Время получения (для тестов)

    Returns:
        Material
    """
    if source not in MATERIAL_SOURCES:
        log.warning(f"Неизвестный источник '{source}', используется 'Other'")
        source = "Other"

    mat_id = material_id or _next_mat_id()
    file_type = classify_file_type(filename, mime_type)

    return Material(
        material_id=mat_id,
        source=source,
        received_at=received_at or _now_iso(),
        file_type=file_type,
        filename=filename,
        file_size_kb=file_size_kb,
        drive_url=drive_url,
        gtd_reference_row=gtd_reference_row,
        gtd_project_id=gtd_project_id,
        business_id=business_id,
        service_id=service_id,
        city=city,
        client_id=client_id,
        roadmap_id=roadmap_id,
        stage_id=stage_id,
        notes=notes,
    )


def link_material_to_context(
    material: Material,
    business_id:    str = "",
    service_id:     str = "",
    city:           str = "",
    client_id:      str = "",
    roadmap_id:     str = "",
    stage_id:       str = "",
    gtd_project_id: str = "",
) -> Material:
    """
    Привязать существующий материал к бизнес-контексту.
    Используется когда контекст определяется позже (Business Router).

    Не перезаписывает уже заполненные поля, если новые пустые.
    """
    if business_id:
        material.business_id = business_id
    if service_id:
        material.service_id = service_id
    if city:
        material.city = city
    if client_id:
        material.client_id = client_id
    if roadmap_id:
        material.roadmap_id = roadmap_id
    if stage_id:
        material.stage_id = stage_id
    if gtd_project_id:
        material.gtd_project_id = gtd_project_id

    log.debug(
        f"link_material_to_context: {material.material_id} → "
        f"biz={material.business_id} rm={material.roadmap_id} stage={material.stage_id}"
    )
    return material


def update_material_status(
    material: Material,
    new_status: str,
    checked_by: str = "",
    notes: str = "",
) -> Material:
    """
    Обновить статус материала.

    Raises:
        ValueError: если статус некорректен
    """
    if new_status not in MATERIAL_STATUSES:
        raise ValueError(
            f"Некорректный статус '{new_status}'. "
            f"Допустимые: {MATERIAL_STATUSES}"
        )

    material.status = new_status
    if checked_by:
        material.checked_by = checked_by
    if notes:
        material.notes = notes
    if new_status == "approved":
        material.approved_at = _now_iso()

    return material


def add_tag(material: Material, tag: str) -> Material:
    """Добавить тег к материалу (без дублей)."""
    tag = tag.strip().lower()
    if tag and tag not in material.tags:
        material.tags.append(tag)
    return material


# ─────────────────────────────────────────────────────────────
# Фильтры
# ─────────────────────────────────────────────────────────────

def get_materials_by_roadmap(
    roadmap_id: str,
    materials: list[Material],
) -> list[Material]:
    return [m for m in materials if m.roadmap_id == roadmap_id]


def get_materials_by_stage(
    roadmap_id: str,
    stage_id: str,
    materials: list[Material],
) -> list[Material]:
    return [
        m for m in materials
        if m.roadmap_id == roadmap_id and m.stage_id == stage_id
    ]


def get_materials_by_client(
    client_id: str,
    materials: list[Material],
) -> list[Material]:
    return [m for m in materials if m.client_id == client_id]


def get_materials_by_business(
    business_id: str,
    materials: list[Material],
) -> list[Material]:
    return [m for m in materials if m.business_id == business_id]


def get_pending_materials(materials: list[Material]) -> list[Material]:
    """Материалы, ожидающие проверки (status == received)."""
    return [m for m in materials if m.is_pending()]


def get_unlinked_materials(materials: list[Material]) -> list[Material]:
    """Материалы без бизнес-контекста — нужна привязка."""
    return [m for m in materials if not m.is_linked()]


def get_materials_by_type(
    file_type: str,
    materials: list[Material],
) -> list[Material]:
    return [m for m in materials if m.file_type == file_type]


def get_materials_by_project(
    gtd_project_id: str,
    materials: list[Material],
) -> list[Material]:
    return [m for m in materials if m.gtd_project_id == gtd_project_id]


# ─────────────────────────────────────────────────────────────
# Проверка документов этапа (checklist)
# ─────────────────────────────────────────────────────────────

def check_stage_documents(
    stage_name: str,
    docs_required: list[str],
    materials: list[Material],
) -> dict:
    """
    Проверить, все ли требуемые документы для этапа получены.

    Args:
        stage_name:    Название этапа
        docs_required: Список требуемых документов (из шаблона)
        materials:     Материалы, привязанные к этому этапу

    Returns:
        {
            "stage_name": str,
            "required_count": int,
            "received_count": int,
            "missing": [список_незакрытых_требований],
            "ready": bool,
        }
    """
    received_names = {m.filename.lower() for m in materials if m.status != "rejected"}
    received_notes = " ".join(m.notes.lower() for m in materials)

    missing = []
    for doc in docs_required:
        doc_lower = doc.lower()
        # Проверяем по ключевым словам
        found = any(
            any(word in fname for word in doc_lower.split() if len(word) > 3)
            for fname in received_names
        )
        if not found:
            # Проверяем в заметках
            found = any(
                word in received_notes
                for word in doc_lower.split() if len(word) > 3
            )
        if not found:
            missing.append(doc)

    return {
        "stage_name":      stage_name,
        "required_count":  len(docs_required),
        "received_count":  len(docs_required) - len(missing),
        "missing":         missing,
        "ready":           len(missing) == 0,
    }


# ─────────────────────────────────────────────────────────────
# Аналитика
# ─────────────────────────────────────────────────────────────

def get_materials_summary(materials: list[Material]) -> dict:
    """Сводная статистика по материалам."""
    total     = len(materials)
    pending   = sum(1 for m in materials if m.is_pending())
    checked   = sum(1 for m in materials if m.status == "checked")
    approved  = sum(1 for m in materials if m.status == "approved")
    rejected  = sum(1 for m in materials if m.status == "rejected")
    archived  = sum(1 for m in materials if m.status == "archived")
    unlinked  = sum(1 for m in materials if not m.is_linked())

    by_type: dict[str, int] = {}
    for m in materials:
        by_type[m.file_type] = by_type.get(m.file_type, 0) + 1

    by_source: dict[str, int] = {}
    for m in materials:
        by_source[m.source] = by_source.get(m.source, 0) + 1

    total_size_kb = sum(m.file_size_kb for m in materials)

    return {
        "total":        total,
        "pending":      pending,
        "checked":      checked,
        "approved":     approved,
        "rejected":     rejected,
        "archived":     archived,
        "unlinked":     unlinked,
        "by_type":      by_type,
        "by_source":    by_source,
        "total_size_kb": total_size_kb,
    }


# ─────────────────────────────────────────────────────────────
# Форматирование
# ─────────────────────────────────────────────────────────────

def format_material_card(material: Material) -> str:
    """Карточка материала для Telegram."""
    status_icon = STATUS_ICONS.get(material.status, "❓")
    file_icon   = FILE_ICONS.get(material.file_type, "📎")

    lines = [
        f"{file_icon} *{material.filename or 'Без имени'}*",
        f"{status_icon} Статус: {material.status}",
        f"📡 Источник: {material.source}",
        f"🕐 Получен: {material.received_at[:10] if material.received_at else '—'}",
    ]

    if material.file_size_kb:
        size_str = (
            f"{material.file_size_kb / 1024:.1f} MB"
            if material.file_size_kb > 1024
            else f"{material.file_size_kb} KB"
        )
        lines.append(f"💾 Размер: {size_str}")

    if material.drive_url:
        lines.append(f"🔗 [Открыть в Drive]({material.drive_url})")

    context_parts = []
    if material.client_id:
        context_parts.append(f"👤 {material.client_id}")
    if material.business_id:
        context_parts.append(f"🏢 {material.business_id}")
    if material.roadmap_id:
        context_parts.append(f"🗺 {material.roadmap_id}")
    if material.stage_id:
        context_parts.append(f"📋 {material.stage_id}")

    if context_parts:
        lines.append("   " + " | ".join(context_parts))

    if material.notes:
        lines.append(f"📝 {material.notes}")

    return "\n".join(lines)


def format_materials_list(
    materials: list[Material],
    title: str = "Материалы",
) -> str:
    """Краткий список материалов."""
    if not materials:
        return f"📁 {title}: нет материалов."

    lines = [f"📁 *{title}* ({len(materials)}):"]
    for m in materials:
        file_icon   = FILE_ICONS.get(m.file_type, "📎")
        status_icon = STATUS_ICONS.get(m.status, "❓")
        name = m.filename or m.material_id
        lines.append(f"  {file_icon}{status_icon} {name}")

    return "\n".join(lines)


def format_stage_checklist(
    check_result: dict,
    materials: list[Material],
) -> str:
    """
    Чеклист документов для этапа дорожной карты.
    Показывает: что есть, чего не хватает.
    """
    stage_name = check_result["stage_name"]
    ready_icon = "✅" if check_result["ready"] else "⚠️"

    lines = [
        f"{ready_icon} *Документы — {stage_name}*",
        f"📊 {check_result['received_count']}/{check_result['required_count']}",
        "",
    ]

    # Полученные (approved или checked)
    good = [m for m in materials if m.status in ("approved", "checked")]
    for m in good:
        lines.append(f"  ✅ {m.filename or m.file_type}")

    # Отклонённые
    bad = [m for m in materials if m.status == "rejected"]
    for m in bad:
        lines.append(f"  ❌ {m.filename or m.file_type} _(нужно переслать)_")

    # Недостающие
    for doc in check_result["missing"]:
        lines.append(f"  ⬜ {doc} _(не получен)_")

    return "\n".join(lines)


def format_materials_digest(
    materials: list[Material],
    pending_limit: int = 5,
) -> str:
    """Дайджест материалов для утреннего обзора."""
    if not materials:
        return "📁 Материалов нет."

    summary = get_materials_summary(materials)
    pending = get_pending_materials(materials)
    unlinked = get_unlinked_materials(materials)

    lines = [
        f"📁 *Материалы — дайджест*",
        f"Всего: {summary['total']} | Ожидают: {summary['pending']} "
        f"| Одобрено: {summary['approved']}",
        "",
    ]

    if pending:
        lines.append(f"📥 *Ожидают проверки ({len(pending)}):*")
        for m in pending[:pending_limit]:
            file_icon = FILE_ICONS.get(m.file_type, "📎")
            lines.append(f"  {file_icon} {m.filename or m.material_id} [{m.source}]")
        if len(pending) > pending_limit:
            lines.append(f"  ...и ещё {len(pending) - pending_limit}")
        lines.append("")

    if unlinked:
        lines.append(
            f"🔗 *Не привязаны к контексту: {len(unlinked)}* "
            f"_(нужно указать бизнес/клиента)_"
        )

    return "\n".join(lines)
