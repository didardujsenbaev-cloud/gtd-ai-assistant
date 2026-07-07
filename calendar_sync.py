"""
Google Calendar — синхронизация дедлайнов GTD + чтение из нескольких календарей.

.env переменные:
  CALENDAR_ID          — GTD-календарь (запись дедлайнов + чтение)
  READ_CALENDAR_IDS    — дополнительные календари для чтения через запятую
                         Пример: personal@gmail.com,biz1@group.calendar.google.com

Каждый доп. календарь должен быть расшарен на service account (права: Просмотр).
"""

import hashlib
import logging
import os
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build
from sheets import _get_creds

SERVICE_ACCOUNT_EMAIL = "gtd-assistant@gtd-ai-assistant.iam.gserviceaccount.com"
TIMEZONE = "Asia/Almaty"


# ─── Конфигурация ─────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(os.getenv("CALENDAR_ID", "").strip())


def _gtd_calendar_id() -> str:
    """Основной GTD-календарь (запись дедлайнов)."""
    return os.getenv("CALENDAR_ID", "").strip()


def _read_calendar_ids() -> list[str]:
    """Все календари для чтения: GTD + дополнительные."""
    ids = [_gtd_calendar_id()] if _gtd_calendar_id() else []
    extra = os.getenv("READ_CALENDAR_IDS", "").strip()
    if extra:
        for cal_id in extra.split(","):
            cal_id = cal_id.strip()
            if cal_id and cal_id not in ids:
                ids.append(cal_id)
    return ids


def setup_instructions() -> str:
    read_ids = _read_calendar_ids()
    extra_count = len(read_ids) - 1 if read_ids else 0
    extra_note = f"\n_Дополнительных календарей для чтения: {extra_count}_" if extra_count else ""
    return (
        "📅 *Google Calendar не настроен*\n\n"
        "1. Создай календарь «GTD» в Google Calendar\n"
        f"2. Поделись с: `{SERVICE_ACCOUNT_EMAIL}` (права: *Изменение*)\n"
        "3. Скопируй ID → добавь в `.env`:\n"
        "   `CALENDAR_ID=твой_id@group.calendar.google.com`\n\n"
        "Для доп. календарей (личный, бизнес) — *Просмотр*:\n"
        "   `READ_CALENDAR_IDS=personal@gmail.com,biz@group.calendar.google.com`\n\n"
        "4. Перезапусти бота и напиши `/cal_sync`"
        + extra_note
    )


def get_calendar_service():
    return build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)


# ─── Запись дедлайнов в GTD-календарь ─────────────────────────────────────────

def _gtd_event_key(action: str, deadline: str, project: str = "") -> str:
    raw = f"{action}|{deadline}|{project}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _find_event_by_key(service, key: str) -> dict | None:
    events = service.events().list(
        calendarId=_gtd_calendar_id(),
        privateExtendedProperty=f"gtd_key={key}",
        singleEvents=True,
        maxResults=5,
    ).execute()
    items = events.get("items", [])
    return items[0] if items else None


def upsert_deadline_event(
    action: str,
    deadline: str,
    *,
    project: str = "",
    context: str = "",
    priority: str = "",
) -> str:
    """Создать или обновить all-day событие в GTD-календаре."""
    if not is_configured():
        return "skipped"
    try:
        dl = date.fromisoformat(deadline)
    except ValueError:
        return "skipped"

    service = get_calendar_service()
    key = _gtd_event_key(action, deadline, project)
    existing = _find_event_by_key(service, key)

    desc_parts = ["GTD Next Action"]
    if project:
        desc_parts.append(f"Проект: {project}")
    if context:
        desc_parts.append(f"Контекст: {context}")
    if priority:
        desc_parts.append(f"Приоритет: {priority}")

    body = {
        "summary": f"📌 {action[:80]}",
        "description": "\n".join(desc_parts),
        "start": {"date": dl.isoformat()},
        "end": {"date": (dl + timedelta(days=1)).isoformat()},
        "extendedProperties": {"private": {"gtd_key": key, "gtd_sync": "1"}},
    }

    if existing:
        service.events().patch(
            calendarId=_gtd_calendar_id(),
            eventId=existing["id"],
            body=body,
        ).execute()
        return "updated"

    service.events().insert(calendarId=_gtd_calendar_id(), body=body).execute()
    return "created"


def sync_gtd_deadlines(actions: list[dict]) -> dict:
    """Синхронизировать все Next Actions с дедлайнами в GTD-календарь."""
    if not is_configured():
        return {"error": "not_configured"}

    stats = {"created": 0, "updated": 0, "skipped": 0}
    for a in actions:
        if a.get("Статус") != "Next":
            continue
        deadline = a.get("Срок", "").strip()
        if not deadline:
            continue
        result = upsert_deadline_event(
            a.get("Действие", ""),
            deadline,
            project=a.get("Проект", ""),
            context=a.get("Контекст", ""),
            priority=a.get("Приоритет", ""),
        )
        stats[result] = stats.get(result, 0) + 1
    return stats


# ─── Чтение событий из всех календарей ────────────────────────────────────────

def _fetch_events_from_calendar(
    service,
    cal_id: str,
    time_min: str,
    time_max: str,
    max_results: int = 20,
) -> list[dict]:
    """Загрузить события из одного календаря. Возвращает [] при ошибке доступа."""
    try:
        result = service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        ).execute()
        events = []
        for item in result.get("items", []):
            start = item.get("start", {})
            start_date = start.get("date") or start.get("dateTime", "")[:10]
            events.append({
                "summary": item.get("summary", "—"),
                "date": start_date,
                "description": item.get("description", ""),
                "calendar_id": cal_id,
                "is_gtd": item.get("extendedProperties", {}).get("private", {}).get("gtd_sync") == "1",
            })
        return events
    except Exception as e:
        logging.warning(f"Calendar read error [{cal_id}]: {e}")
        return []


def _calendar_label(cal_id: str) -> str:
    """Короткая метка календаря для отображения."""
    if cal_id == _gtd_calendar_id():
        return "GTD"
    if "@gmail.com" in cal_id:
        return "Личный"
    if "@group.calendar.google.com" in cal_id:
        # Берём первую часть до @
        return cal_id.split("@")[0][:12]
    return cal_id[:15]


def list_upcoming_events(days: int = 7) -> list[dict]:
    """События из ВСЕХ настроенных календарей на ближайшие N дней."""
    if not is_configured():
        return []

    service = get_calendar_service()
    now = datetime.now().astimezone()
    time_max = (now + timedelta(days=days)).isoformat()

    all_events = []
    for cal_id in _read_calendar_ids():
        events = _fetch_events_from_calendar(
            service, cal_id, now.isoformat(), time_max, max_results=15
        )
        all_events.extend(events)

    all_events.sort(key=lambda e: e["date"])
    return all_events


def list_past_events(days: int = 7) -> list[dict]:
    """События из ВСЕХ настроенных календарей за прошедшие N дней."""
    if not is_configured():
        return []

    service = get_calendar_service()
    now = datetime.now().astimezone()
    time_min = (now - timedelta(days=days)).isoformat()

    all_events = []
    for cal_id in _read_calendar_ids():
        events = _fetch_events_from_calendar(
            service, cal_id, time_min, now.isoformat(), max_results=20
        )
        all_events.extend(events)

    all_events.sort(key=lambda e: e["date"])
    return all_events


def list_calendars_status() -> list[dict]:
    """Статус всех настроенных календарей (для /calendar_setup)."""
    if not is_configured():
        return []

    service = get_calendar_service()
    result = []
    for cal_id in _read_calendar_ids():
        role = "writer" if cal_id == _gtd_calendar_id() else "reader"
        try:
            cal = service.calendars().get(calendarId=cal_id).execute()
            result.append({
                "id": cal_id,
                "name": cal.get("summary", cal_id),
                "role": role,
                "ok": True,
            })
        except Exception as e:
            result.append({
                "id": cal_id,
                "name": _calendar_label(cal_id),
                "role": role,
                "ok": False,
                "error": str(e)[:60],
            })
    return result


# ─── Форматирование для /calendar ─────────────────────────────────────────────

def format_calendar_summary(actions: list[dict], days: int = 7) -> str:
    """Текст для /calendar: GTD-дедлайны + события всех календарей."""
    today = date.today()
    end = today + timedelta(days=days)

    deadlines = []
    for a in actions:
        if a.get("Статус") != "Next":
            continue
        dl = a.get("Срок", "").strip()
        if not dl:
            continue
        try:
            dl_date = date.fromisoformat(dl)
        except ValueError:
            continue
        if today <= dl_date <= end:
            deadlines.append((dl_date, a))

    deadlines.sort(key=lambda x: x[0])
    cal_ids = _read_calendar_ids()
    cal_count = len(cal_ids)
    text = (
        f"📅 *КАЛЕНДАРЬ — {days} дней*\n"
        f"_{today.strftime('%d.%m')} – {end.strftime('%d.%m.%Y')}_"
        + (f" · {cal_count} кал." if cal_count > 1 else "")
        + "\n\n"
    )

    if deadlines:
        text += f"⚡ *Дедлайны GTD ({len(deadlines)}):*\n"
        for dl_date, a in deadlines[:10]:
            diff = (dl_date - today).days
            marker = "⚠️" if diff == 0 else "⏰" if diff == 1 else "·"
            proj = a.get("Проект", "")
            proj_str = f" _{proj}_" if proj else ""
            text += f"{marker} *{dl_date.strftime('%d.%m')}* — {a.get('Действие', '—')}{proj_str}\n"
        text += "\n"
    else:
        text += "✅ Нет дедлайнов на ближайшие 7 дней\n\n"

    if is_configured():
        try:
            events = list_upcoming_events(days)
            non_gtd = [e for e in events if not e["is_gtd"]]
            if non_gtd:
                text += f"🗓 *Встречи и события ({len(non_gtd)}):*\n"
                for e in non_gtd[:10]:
                    d = e["date"]
                    try:
                        d_fmt = date.fromisoformat(d).strftime("%d.%m")
                    except ValueError:
                        d_fmt = d[:10]
                    label = _calendar_label(e["calendar_id"])
                    label_str = f" _[{label}]_" if label != "GTD" else ""
                    text += f"· *{d_fmt}* — {e['summary'][:50]}{label_str}\n"
                text += "\n"
        except Exception as e:
            logging.error(f"Calendar list error: {e}")
            text += "⚠️ Не удалось загрузить события\n\n"
    else:
        text += "_Google Calendar: не настроен (`/cal_sync` для инструкции)_\n"

    return text
