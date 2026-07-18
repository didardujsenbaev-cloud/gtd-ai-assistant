"""
Report Manager — read-only reporting layer for Business Core (Phase 11B).

Foundation of the future Attention Engine.

Architectural rule: collect_snapshot() is the ONLY function allowed to
touch Google Sheets. Every other function here is pure — it takes the
snapshot (or pieces of it) and returns plain data structures, never
Markdown, never Telegram objects, never writes.

Header-safe by construction: all data comes from read_business_sheet(),
which already reads by actual column name, not by position.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from business_core.roadmap_manager import calculate_progress, STAGE_STATUS_CANONICAL

# Sheets read by collect_snapshot(), keyed the same way they are returned
# in the snapshot dict.
_SNAPSHOT_SHEETS = (
    ("biz", "biz_registry"),
    ("people", "people_registry"),
    ("objects", "object_registry"),
    ("services", "service_catalog"),
    ("roadmaps", "roadmaps"),
    ("stages", "roadmap_stages"),
)


# ═══════════════════════════════════════════════════════════════
# 1. collect_snapshot() — the only Sheets-touching function
# ═══════════════════════════════════════════════════════════════

def collect_snapshot() -> dict:
    """
    Read every sheet needed for reporting exactly once, header-safe.

    Each sheet is read independently — a failure on one sheet does not
    prevent the others from being read. Failures are collected in
    snapshot["errors"] instead of raising, so the report can still be
    built (partially) from whatever data was available.

    Returns:
        {
            "biz":      list[dict],
            "people":   list[dict],
            "objects":  list[dict],
            "services": list[dict],
            "roadmaps": list[dict],
            "stages":   list[dict],
            "errors":   dict[str, str],  # sheet_key -> error message
        }
    """
    from business_core.sheets import read_business_sheet

    snapshot: dict = {"errors": {}}
    for key, sheet_key in _SNAPSHOT_SHEETS:
        try:
            snapshot[key] = read_business_sheet(sheet_key)
        except Exception as exc:
            snapshot[key] = []
            snapshot["errors"][sheet_key] = str(exc)
    return snapshot


# ═══════════════════════════════════════════════════════════════
# Internal pure helpers (shared by build_attention / build_quality)
# ═══════════════════════════════════════════════════════════════

def _orphan_roadmap_services(roadmaps: list[dict], services: list[dict]) -> list[dict]:
    """Roadmaps whose Service ID does not exist in SERVICE_CATALOG."""
    service_ids = {s.get("ID", "") for s in services}
    result = []
    for r in roadmaps:
        svc_id = r.get("Service ID", "").strip()
        if svc_id and svc_id not in service_ids:
            result.append({
                "roadmap_id": r.get("Roadmap ID", ""),
                "service_id": svc_id,
            })
    return sorted(result, key=lambda x: x["roadmap_id"])


def _roadmaps_without_object(roadmaps: list[dict]) -> list[dict]:
    """Roadmaps with an empty Object ID."""
    result = [
        {
            "roadmap_id": r.get("Roadmap ID", ""),
            "business_id": r.get("Business ID", ""),
            "client_name": r.get("Client Name", ""),
        }
        for r in roadmaps
        if not r.get("Object ID", "").strip()
    ]
    return sorted(result, key=lambda x: x["roadmap_id"])


def _objects_without_roadmap(objects: list[dict]) -> list[dict]:
    """Objects with an empty Roadmap ID."""
    result = [
        {
            "obj_id": o.get("OBJ ID", ""),
            "biz_id": o.get("Biz ID", ""),
            "client_id": o.get("Client ID", ""),
        }
        for o in objects
        if not o.get("Roadmap ID", "").strip()
    ]
    return sorted(result, key=lambda x: x["obj_id"])


def _legacy_stage_statuses(stages: list[dict]) -> list[dict]:
    """Stages whose Status is non-empty but not in the Phase 9B canonical
    vocabulary (e.g. "not_started" left over from deprecated /newroadmap)."""
    result = [
        {
            "stage_id": s.get("Stage ID", ""),
            "roadmap_id": s.get("Roadmap ID", ""),
            "status": s.get("Status", ""),
        }
        for s in stages
        if s.get("Status", "").strip()
        and s.get("Status", "").strip() not in STAGE_STATUS_CANONICAL
    ]
    return sorted(result, key=lambda x: x["stage_id"])


def _roadmaps_without_template(roadmaps: list[dict]) -> list[dict]:
    """Roadmaps with an empty Template ID."""
    result = [
        {"roadmap_id": r.get("Roadmap ID", "")}
        for r in roadmaps
        if not r.get("Template ID", "").strip()
    ]
    return sorted(result, key=lambda x: x["roadmap_id"])


# ═══════════════════════════════════════════════════════════════
# 2. build_attention(snapshot)
# ═══════════════════════════════════════════════════════════════

def build_attention(snapshot: dict) -> dict:
    """
    Pure. Concrete items that need action right now.

    Returns:
        {
            "orphan_services":        list[dict],  # roadmap_id, service_id
            "roadmaps_without_object": list[dict],  # roadmap_id, business_id, client_name
            "objects_without_roadmap": list[dict],  # obj_id, biz_id, client_id
            "legacy_stage_statuses":   list[dict],  # stage_id, roadmap_id, status
        }
    """
    roadmaps = snapshot.get("roadmaps", [])
    services = snapshot.get("services", [])
    objects  = snapshot.get("objects", [])
    stages   = snapshot.get("stages", [])

    return {
        "orphan_services":         _orphan_roadmap_services(roadmaps, services),
        "roadmaps_without_object": _roadmaps_without_object(roadmaps),
        "objects_without_roadmap": _objects_without_roadmap(objects),
        "legacy_stage_statuses":   _legacy_stage_statuses(stages),
    }


# ═══════════════════════════════════════════════════════════════
# 3. build_statistics(snapshot)
# ═══════════════════════════════════════════════════════════════

def build_statistics(snapshot: dict) -> dict:
    """
    Pure. Simple counts and aggregates.

    Returns:
        {
            "business_count":        int,
            "active_business_count": int,
            "client_count":          int,
            "object_count":          int,
            "roadmap_count":         int,
            "active_roadmap_count":  int,
            "stage_count":           int,
        }
    """
    biz      = snapshot.get("biz", [])
    people   = snapshot.get("people", [])
    objects  = snapshot.get("objects", [])
    roadmaps = snapshot.get("roadmaps", [])
    stages   = snapshot.get("stages", [])

    clients = [p for p in people if "клиент" in p.get("Тип", "").lower()]

    return {
        "business_count":        len(biz),
        "active_business_count": sum(1 for b in biz if b.get("Статус", "") == "active"),
        "client_count":          len(clients),
        "object_count":          len(objects),
        "roadmap_count":         len(roadmaps),
        "active_roadmap_count":  sum(1 for r in roadmaps if r.get("Status", "") == "active"),
        "stage_count":           len(stages),
    }


# ═══════════════════════════════════════════════════════════════
# 4. build_quality(snapshot)
# ═══════════════════════════════════════════════════════════════

def build_quality(snapshot: dict) -> dict:
    """
    Pure. Data-quality overview (counts + item lists), independent of
    build_attention() (same underlying facts, different framing for the
    "⚠ Качество данных" section).

    Returns:
        {
            "orphan_ids":       list[dict],  # roadmap_id, service_id
            "legacy_statuses":  list[dict],  # stage_id, roadmap_id, status
            "missing_template": list[dict],  # roadmap_id
            "missing_object":   list[dict],  # roadmap_id, business_id, client_name
        }
    """
    roadmaps = snapshot.get("roadmaps", [])
    services = snapshot.get("services", [])
    stages   = snapshot.get("stages", [])

    return {
        "orphan_ids":       _orphan_roadmap_services(roadmaps, services),
        "legacy_statuses":  _legacy_stage_statuses(stages),
        "missing_template": _roadmaps_without_template(roadmaps),
        "missing_object":   _roadmaps_without_object(roadmaps),
    }


# ═══════════════════════════════════════════════════════════════
# 5. build_progress(snapshot)
# ═══════════════════════════════════════════════════════════════

def build_progress(snapshot: dict) -> dict:
    """
    Pure. Recomputes progress from ROADMAP_STAGES via the existing
    calculate_progress() — never trusts the stored ROADMAPS."Progress %"
    (which can be stale, see Phase 11A audit).

    Returns:
        {
            "average_progress":    int,             # 0..100, round-half-up
            "roadmap_progress_map": dict[str, int],  # roadmap_id -> 0..100
        }
    """
    roadmaps = snapshot.get("roadmaps", [])
    stages   = snapshot.get("stages", [])

    stages_by_roadmap: dict[str, list[dict]] = {}
    for s in stages:
        rm_id = s.get("Roadmap ID", "")
        stages_by_roadmap.setdefault(rm_id, []).append({"status": s.get("Status", "")})

    roadmap_progress_map: dict[str, int] = {}
    for r in roadmaps:
        rm_id = r.get("Roadmap ID", "")
        roadmap_progress_map[rm_id] = calculate_progress(stages_by_roadmap.get(rm_id, []))

    if roadmap_progress_map:
        avg = math.floor(sum(roadmap_progress_map.values()) / len(roadmap_progress_map) + 0.5)
    else:
        avg = 0

    return {
        "average_progress":     avg,
        "roadmap_progress_map": roadmap_progress_map,
    }


# ═══════════════════════════════════════════════════════════════
# 6. render_report(...) — the only function producing text
# ═══════════════════════════════════════════════════════════════

def render_report(
    attention: dict,
    statistics: dict,
    quality: dict,
    progress: dict,
    snapshot_errors: Optional[dict] = None,
) -> str:
    """
    Pure. Turns the four data structures above into the final Markdown
    text. The Telegram handler must not assemble text itself — this is
    the single place formatting happens.
    """
    lines: list[str] = [
        "📊 *Business Core Report*",
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
    ]

    if snapshot_errors:
        lines.append("⚠️ *Не удалось прочитать:*")
        for sheet_key, err in snapshot_errors.items():
            lines.append(f"  • `{sheet_key}`: {err}")
        lines.append("")

    # ── 1. 🔥 Требует внимания ──────────────────────────────────
    lines.append("🔥 *Требует внимания*")

    orphan = attention.get("orphan_services", [])
    if orphan:
        lines.append(f"  Orphan services: {len(orphan)}")
        for item in orphan[:10]:
            lines.append(f"    • `{item['roadmap_id']}` → `{item['service_id']}` не найден")
        if len(orphan) > 10:
            lines.append(f"    ...и ещё {len(orphan) - 10}")
    else:
        lines.append("  Orphan services: 0")

    no_obj = attention.get("roadmaps_without_object", [])
    if no_obj:
        lines.append(f"  Roadmap без объекта: {len(no_obj)}")
        for item in no_obj[:10]:
            lines.append(f"    • `{item['roadmap_id']}`")
        if len(no_obj) > 10:
            lines.append(f"    ...и ещё {len(no_obj) - 10}")
    else:
        lines.append("  Roadmap без объекта: 0")

    no_rm = attention.get("objects_without_roadmap", [])
    if no_rm:
        lines.append(f"  Объект без roadmap: {len(no_rm)}")
        for item in no_rm[:10]:
            lines.append(f"    • `{item['obj_id']}`")
        if len(no_rm) > 10:
            lines.append(f"    ...и ещё {len(no_rm) - 10}")
    else:
        lines.append("  Объект без roadmap: 0")

    # ── 2. 📊 Статистика ─────────────────────────────────────────
    lines.append("")
    lines.append("📊 *Статистика*")
    lines.append(f"  Businesses: {statistics.get('active_business_count', 0)} активных / {statistics.get('business_count', 0)} всего")
    lines.append(f"  Clients: {statistics.get('client_count', 0)}")
    lines.append(f"  Objects: {statistics.get('object_count', 0)}")
    lines.append(f"  Roadmaps: {statistics.get('active_roadmap_count', 0)} активных / {statistics.get('roadmap_count', 0)} всего")
    lines.append(f"  Stages: {statistics.get('stage_count', 0)}")

    # ── 3. ⚠ Качество данных ────────────────────────────────────
    lines.append("")
    lines.append("⚠️ *Качество данных*")
    legacy = quality.get("legacy_statuses", [])
    lines.append(f"  Legacy-статусы этапов: {len(legacy)}")
    missing_tmpl = quality.get("missing_template", [])
    lines.append(f"  Roadmap без шаблона: {len(missing_tmpl)}")
    orphan_ids = quality.get("orphan_ids", [])
    lines.append(f"  Orphan ID: {len(orphan_ids)}")

    # ── 4. 📈 Прогресс ───────────────────────────────────────────
    lines.append("")
    lines.append("📈 *Прогресс*")
    lines.append(f"  Средний прогресс: {progress.get('average_progress', 0)}%")

    return "\n".join(lines)
