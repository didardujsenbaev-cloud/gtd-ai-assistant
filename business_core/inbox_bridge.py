"""
Inbox Bridge — соединяет GTD Inbox-поток с Business Router.

Вызывается из telegram_bot.py handle_message() ПОСЛЕ process_item().
Никогда не бросает исключений — работает тихо.
Не меняет GTD-результат, только добавляет бизнес-контекст в ответ.

Кеш: данные из Google Sheets загружаются раз в 5 минут.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Простой кеш (TTL 5 минут — не грузить Sheets на каждом сообщении)
# ─────────────────────────────────────────────────────────────

_CACHE_TTL = 300   # секунд

_cache: dict = {
    "businesses": [],
    "people":     [],
    "roadmaps":   [],
    "loaded_at":  0.0,
}


def _is_stale() -> bool:
    return (time.time() - _cache["loaded_at"]) > _CACHE_TTL


def _refresh_cache() -> None:
    """Загрузить свежие данные из Business Core Google Sheets."""
    try:
        from business_core.sheets import read_business_sheet

        biz_rows = read_business_sheet("biz_registry")
        _cache["businesses"] = [
            {
                "id":     r.get("ID", ""),
                "name":   r.get("Название", ""),
                "slug":   r.get("Slug", ""),
                "status": r.get("Статус", ""),
                "cities": r.get("Города", ""),
            }
            for r in biz_rows
            if r.get("Статус", "") in ("active", "test")
        ]

        ppl_rows = read_business_sheet("people_registry")
        _cache["people"] = [
            {
                "id":         r.get("ID", ""),
                "full_name":  r.get("ФИО", ""),
                "short_name": r.get("Имя", ""),
                "person_type": r.get("Тип", ""),
            }
            for r in ppl_rows
        ]

        rm_rows = read_business_sheet("roadmaps")
        _cache["roadmaps"] = [
            {
                "roadmap_id":  r.get("Roadmap ID", ""),
                "business_id": r.get("Business ID", ""),
                "client_id":   r.get("Client ID", ""),
                "client_name": r.get("Client Name", ""),
                "service_id":  r.get("Service ID", ""),
                "city":        r.get("City", ""),
                "status":      r.get("Status", ""),
            }
            for r in rm_rows
            if r.get("Status", "") == "active"
        ]

        _cache["loaded_at"] = time.time()
        log.debug(
            f"inbox_bridge cache: {len(_cache['businesses'])} biz, "
            f"{len(_cache['people'])} people, {len(_cache['roadmaps'])} roadmaps"
        )
    except Exception as e:
        log.debug(f"inbox_bridge cache refresh failed: {e}")


def _get_cached() -> tuple[list, list, list]:
    if _is_stale():
        _refresh_cache()
    return _cache["businesses"], _cache["people"], _cache["roadmaps"]


# ─────────────────────────────────────────────────────────────
# Поиск активной дорожной карты по клиенту
# ─────────────────────────────────────────────────────────────

def _find_active_roadmap(client_name: str, business_id: str, roadmaps: list) -> Optional[dict]:
    """Найти активную дорожную карту для клиента и бизнеса."""
    if not client_name:
        return None
    name_lower = client_name.lower()
    for rm in roadmaps:
        rm_client = rm.get("client_name", "").lower()
        if not rm_client:
            continue
        # Матч по части имени (фамилия)
        parts = name_lower.split()
        if any(p in rm_client for p in parts if len(p) > 3):
            if not business_id or rm.get("business_id", "") == business_id:
                return rm
    return None


# ─────────────────────────────────────────────────────────────
# Главная функция
# ─────────────────────────────────────────────────────────────

def route_inbox(original_text: str, gtd_result: dict) -> str:
    """
    Определить бизнес-контекст для входящего GTD-результата.

    Args:
        original_text: исходный текст пользователя
        gtd_result:    результат process_item()

    Returns:
        Строка с бизнес-контекстом для добавления к ответу боту.
        Пустая строка если Business Core не активен или контекст не найден.

    Никогда не бросает исключений.
    """
    try:
        # Проверяем что BC включён
        if os.getenv("BUSINESS_CORE_ENABLED", "false").lower() != "true":
            return ""

        # Роутим только Action / Project / Waiting — остальные не имеют смысла
        from business_core.business_router import route_business_context
        if gtd_result.get("результат") not in ("Action", "Project", "Waiting"):
            return ""

        # Загружаем данные из кеша
        businesses, people, roadmaps = _get_cached()
        if not businesses:
            return ""

        # Запускаем роутер (без AI для скорости)
        routing = route_business_context(
            original_text=original_text,
            gtd_result=gtd_result,
            businesses=businesses,
            services=[],
            people=people,
            use_ai=False,
        )

        # Нет ни бизнеса, ни клиента — молчим
        if not routing["business_name"] and not routing["client_name"]:
            return ""

        # Ищем активную дорожную карту
        active_rm = _find_active_roadmap(
            routing["client_name"],
            routing["business_id"],
            roadmaps,
        )

        # Формируем компактную строку
        parts = []

        if routing["business_name"]:
            conf_icon = "🏢" if routing["confidence"] >= 0.8 else "🏢❓"
            parts.append(f"{conf_icon} {routing['business_name']}")

        if routing["city"]:
            parts.append(f"📍 {routing['city']}")

        if routing["client_name"]:
            client_str = routing["client_name"]
            if not routing["client_id"]:
                client_str += " _(не в базе)_"
            parts.append(f"👤 {client_str}")

        if routing["roadmap_stage_name"]:
            parts.append(f"📋 Этап: {routing['roadmap_stage_name']}")

        if active_rm:
            rm_id = active_rm.get("roadmap_id", "")
            parts.append(f"🗺 Карта: `{rm_id}`")

        if not parts:
            return ""

        note = "\n".join(parts)

        # Если нужно подтверждение — добавляем маркер
        if routing["needs_confirmation"] and routing["confidence"] < 0.85:
            note += "\n_Контекст определён автоматически_"

        return "\n\n─────\n" + note

    except Exception as e:
        log.debug(f"route_inbox error (silent): {e}")
        return ""


def invalidate_cache() -> None:
    """Сбросить кеш (например после /newclient или /newroadmap)."""
    _cache["loaded_at"] = 0.0
