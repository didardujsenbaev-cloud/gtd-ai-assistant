"""
Business Core — Telegram handlers.

Все Business Core-команды живут здесь, отдельно от telegram_bot.py.
Подключается через одну строку в main():
    from business_core.telegram_handlers import register_business_handlers
    register_business_handlers(app)

Если business_core не настроен (BUSINESS_CORE_ENABLED=false) —
каждая команда вернёт понятную инструкцию по настройке.

Команды:
  /bc               — дашборд Business Core (статус + счётчики)
  /roadmaps         — список активных дорожных карт
  /newroadmap       — создать новую дорожную карту (диалог)
  /clients          — поиск клиента по имени
  /newclient        — добавить клиента в People Registry
  /newbiz           — добавить новый бизнес (диалог)
  /initbc           — заполнить таблицу начальными данными (бизнесы + услуги)
  /bcdrive          — создать Drive-структуру для бизнеса
  /bcstatus         — проверить конфигурацию Business Core
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# ConversationHandler states
# ─────────────────────────────────────────────────────────────

NR_BUSINESS, NR_CLIENT, NR_SERVICE, NR_CITY, NR_DAYS, NR_CONFIRM = range(6)
NC_NAME, NC_PHONE, NC_TYPE, NC_BIZ, NC_CONFIRM = range(10, 15)
NB_NAME, NB_CITIES, NB_PRIORITY, NB_CONFIRM = range(20, 24)
# Phase 13A
EC_FIELD, EC_VALUE, EC_CONFIRM = range(30, 33)
EO_FIELD, EO_VALUE, EO_CONFIRM = range(40, 43)
# Phase 15A
RD_CONFIRM = 60
# Phase 15B
UD_FILE, UD_DETAILS, UD_CONFIRM = range(70, 73)


# ─────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────

def _is_bc_enabled() -> bool:
    return os.getenv("BUSINESS_CORE_ENABLED", "false").lower() == "true"


def _bc_disabled_msg() -> str:
    return (
        "⚠️ *Business Core не активирован*\n\n"
        "Для включения добавь в `.env`:\n"
        "`BUSINESS_CORE_ENABLED=true`\n"
        "`BUSINESS_SPREADSHEET_ID=<id таблицы>`\n\n"
        "После этого перезапусти бота."
    )


def _safe_send(text: str, max_len: int = 4000) -> list[str]:
    """Разбить длинный текст на части для Telegram (лимит 4096)."""
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        parts.append(text[:max_len])
        text = text[max_len:]
    return parts


def _mask_phone_for_display(phone: str) -> str:
    """Phase 31D: mask all but the last 4 digits of a phone number for
    ambiguity-candidate display — avoids showing full personal data in
    an error message (Phase 31A's privacy constraint)."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return "—"
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


async def _reply(update: Update, text: str, parse_mode: str = "Markdown") -> None:
    """Отправить ответ, разбивая при необходимости."""
    for part in _safe_send(text):
        try:
            await update.message.reply_text(part, parse_mode=parse_mode)
        except Exception:
            await update.message.reply_text(part, parse_mode=None)


# ─────────────────────────────────────────────────────────────
# /bcstatus — проверка конфигурации
# ─────────────────────────────────────────────────────────────

async def bc_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверить конфигурацию Business Core."""
    lines = ["🔍 *Business Core — статус конфигурации*\n"]

    # .env переменные
    bc_enabled = os.getenv("BUSINESS_CORE_ENABLED", "false")
    bs_id      = os.getenv("BUSINESS_SPREADSHEET_ID", "")
    creds      = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    drive_en   = os.getenv("BUSINESS_DRIVE_ENABLED", "false")
    drive_root = os.getenv("DRIVE_ROOT_FOLDER_ID", "")

    lines.append(
        f"{'✅' if bc_enabled == 'true' else '❌'} "
        f"BUSINESS_CORE_ENABLED = `{bc_enabled}`"
    )
    lines.append(
        f"{'✅' if bs_id else '❌'} "
        f"BUSINESS_SPREADSHEET_ID = `{'задан' if bs_id else 'не задан'}`"
    )
    lines.append(
        f"{'✅' if creds and os.path.exists(creds) else '❌'} "
        f"GOOGLE_CREDENTIALS_FILE = `{'OK' if creds and os.path.exists(creds) else 'не найден'}`"
    )
    lines.append(
        f"{'✅' if drive_en == 'true' else '⬜'} "
        f"BUSINESS_DRIVE_ENABLED = `{drive_en}`"
    )
    if drive_root:
        lines.append(f"✅ DRIVE_ROOT_FOLDER_ID = задан")

    # Проверка Google Sheets
    if bc_enabled == "true" and bs_id:
        lines.append("")
        try:
            from business_core.sheets import check_configuration
            cfg = check_configuration()
            if cfg["ok"]:
                sa = cfg.get("service_account", "?")
                lines.append(f"✅ Google Sheets: OK")
                lines.append(f"   SA: `{sa}`")
                url = cfg.get("url", "")
                if url:
                    lines.append(f"   [Открыть таблицу]({url})")
            else:
                lines.append("❌ Google Sheets: проблемы")
                for issue in cfg["issues"]:
                    lines.append(f"   • {issue}")
        except Exception as e:
            lines.append(f"❌ Ошибка проверки Sheets: {e}")

    await _reply(update, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# /bc — дашборд Business Core
# ─────────────────────────────────────────────────────────────

async def bc_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Главный дашборд Business Core."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    lines = [
        "🏢 *Business Core — Дашборд*",
        f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
    ]

    try:
        from business_core.sheets import (
            read_business_sheet, is_enabled, get_spreadsheet_url
        )

        if not is_enabled():
            await _reply(update, _bc_disabled_msg())
            return

        # Бизнесы
        try:
            biz_rows = read_business_sheet("biz_registry")
            active_biz = [r for r in biz_rows if r.get("Статус", "") == "active"]
            lines.append(f"🏢 *Бизнесы:* {len(active_biz)} активных / {len(biz_rows)} всего")
            for b in active_biz[:5]:
                name = b.get("Название", "?")
                cities = b.get("Города", "")
                lines.append(f"  • {name}" + (f" ({cities})" if cities else ""))
        except Exception:
            lines.append("🏢 Бизнесы: нет данных")

        # Дорожные карты
        try:
            rm_rows = read_business_sheet("roadmaps")
            active_rm = [r for r in rm_rows if r.get("Status", "") == "active"]
            lines.append(f"\n🗺 *Дорожные карты:* {len(active_rm)} активных / {len(rm_rows)} всего")
            for r in active_rm[:3]:
                client = r.get("Client Name", "?")
                progress = r.get("Progress %", "0")
                city = r.get("City", "")
                lines.append(f"  • {client} {city} — {progress}%")
            if len(active_rm) > 3:
                lines.append(f"  ...и ещё {len(active_rm) - 3}")
        except Exception:
            lines.append("\n🗺 Дорожные карты: нет данных")

        # Клиенты (Phase 31D, ADR-015 Decision 6: canonical owner API,
        # replacing the raw read_business_sheet("people_registry") +
        # substring "клиент" in Тип filter)
        try:
            from business_core.person_manager import list_clients, list_people
            client_count = len(list_clients())
            people_count = len(list_people())
            lines.append(f"\n👥 *Клиенты:* {client_count} / {people_count} людей")
        except Exception:
            lines.append("\n👥 Клиенты: нет данных")

        # Материалы
        try:
            mat_rows = read_business_sheet("materials")
            pending_mat = [r for r in mat_rows if r.get("Status", "") == "received"]
            lines.append(f"\n📁 *Материалы:* {len(pending_mat)} ожидают проверки / {len(mat_rows)} всего")
        except Exception:
            pass

        try:
            url = get_spreadsheet_url()
            if url:
                lines.append(f"\n[📊 Открыть Business Core таблицу]({url})")
        except Exception:
            pass

    except Exception as e:
        lines.append(f"\n❌ Ошибка загрузки данных: {e}")

    lines.extend([
        "",
        "📋 *Команды:*",
        "/roadmaps — дорожные карты",
        "/clients — клиенты",
        "/newroadmap — новая дорожная карта",
        "/newclient — добавить клиента",
        "/bcstatus — проверить настройки",
    ])

    await _reply(update, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# /roadmaps — список дорожных карт
# ─────────────────────────────────────────────────────────────

async def show_roadmaps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать дорожные карты с поддержкой фильтров.

    Форматы:
      /roadmaps
      /roadmaps obj_id=OBJ-001
      /roadmaps biz_id=BIZ-001
      /roadmaps client_id=PRS-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        raw = " ".join(context.args or [])
        args = _parse_kv_args(raw)

        filter_obj_id    = args.get("obj_id")    or args.get("_pos0", "")
        filter_biz_id    = args.get("biz_id",    "")
        filter_client_id = args.get("client_id", "")

        from business_core.roadmap_manager import list_roadmaps

        rows = list_roadmaps()
        if not rows:
            await _reply(update,
                "🗺 *Дорожные карты*\n\n"
                "Пусто. Создай первую: /newroadmap"
            )
            return

        # Применить фильтры
        if filter_obj_id:
            rows = [r for r in rows if r.get("object_id", "") == filter_obj_id]
        if filter_biz_id:
            rows = [r for r in rows if r.get("business_id", "") == filter_biz_id]
        if filter_client_id:
            rows = [r for r in rows if r.get("client_id", "") == filter_client_id]

        active = [r for r in rows if r.get("status", "") not in ("completed", "cancelled")]
        done   = [r for r in rows if r.get("status", "") == "completed"]

        filter_info = ""
        if filter_obj_id:
            filter_info = f" | obj: {filter_obj_id}"
        elif filter_biz_id:
            filter_info = f" | biz: {filter_biz_id}"
        elif filter_client_id:
            filter_info = f" | client: {filter_client_id}"

        lines = [f"🗺 *Дорожные карты* ({len(active)} активных{filter_info})\n"]

        for r in active:
            rm_id    = r.get("roadmap_id", "?")
            client   = r.get("client_name", "?")
            city     = r.get("city", "")
            biz_id   = r.get("business_id", "")
            obj_id   = r.get("object_id", "")
            svc_id   = r.get("service_id", "")
            case_t   = r.get("case_type", "")
            progress = r.get("progress", "0")

            try:
                pct = float(progress)
            except (ValueError, TypeError):
                pct = 0.0

            filled = int(pct / 10)
            bar    = "█" * filled + "░" * (10 - filled)

            lines.append(
                f"*{rm_id}* — {client}"
                + (f", {city}" if city else "")
                + (f" `[{biz_id}]`" if biz_id else "")
            )
            if obj_id or svc_id or case_t:
                meta = []
                if obj_id:
                    meta.append(f"OBJ: {obj_id}")
                if svc_id:
                    meta.append(f"SVC: {svc_id}")
                if case_t:
                    meta.append(f"type: {case_t}")
                lines.append("  " + " | ".join(meta))
            lines.append(f"  {bar} {pct:.0f}%")

            # Показать текущий этап если есть (legacy Stage X columns)
            for i, stage_status in enumerate(r.get("legacy_stage_statuses", []), start=1):
                if stage_status in ("in_progress", "blocked", "waiting"):
                    lines.append(f"  ⬅ Этап {i}: {stage_status}")
                    break
            lines.append(f"  `/stages roadmap_id={rm_id}`")
            lines.append("")

        if done:
            lines.append(f"✅ Завершено: {len(done)}")

        if not active and not done:
            lines.append("Ничего не найдено по заданному фильтру.")

    except Exception as e:
        log.error(f"show_roadmaps error: {e}")
        await _reply(update, f"❌ Ошибка загрузки дорожных карт: {e}")
        return

    await _reply(update, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# /clients — список клиентов
# ─────────────────────────────────────────────────────────────

async def show_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать клиентов или найти по имени."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    query = " ".join(context.args).strip() if context.args else ""

    try:
        from business_core.person_manager import list_clients, list_people

        # Phase 31D (ADR-015 Decision 6): canonical owner API, replacing
        # the raw read_business_sheet("people_registry") + substring
        # "клиент" in Тип filter. Archived excluded by default (matches
        # the previous behavior — old code never excluded archived rows
        # explicitly, but no archived Person existed in the "клиент"
        # subset in practice; list_clients()'s default is now the
        # explicit, intentional policy going forward).
        all_clients = list_clients()
        if not all_clients:
            total_people = len(list_people())
            if total_people == 0:
                await _reply(update, "👥 *Клиенты*\n\nПусто. Добавь первого: /newclient")
                return

        clients = list_clients(query=query or None)

        if not clients:
            msg = f"👥 Клиент *{query}* не найден." if query else "👥 Клиентов нет."
            await _reply(update, msg + "\n\nДобавь: /newclient")
            return

        header = f"👥 *Клиенты*"
        if query:
            header += f" — поиск: _{query}_"
        header += f" ({len(clients)}"
        if not query:
            header += f" / {len(list_people())} людей"
        header += ")"

        lines = [header, ""]
        for p in clients[:15]:
            name  = p.get("full_name") or p.get("short_name") or "?"
            phone = p.get("phone", "")
            city  = p.get("city", "")
            # Phase 31D: canonical Person shape exposes biz_ids (technical
            # IDs), not the legacy free-text "Бизнесы" display-name column
            # — that column isn't part of the canonical read shape at all
            # (Phase 31A/31C). Showing Biz IDs is the closest canonical
            # equivalent without a raw registry read.
            bizs  = ",".join(p.get("biz_ids") or [])

            line = f"*{name}*"
            if phone:
                line += f" | {phone}"
            if city:
                line += f" | {city}"
            if bizs:
                line += f" | _{bizs}_"
            lines.append(line)

        if len(clients) > 15:
            lines.append(f"\n...и ещё {len(clients) - 15}. Уточни поиск: `/clients имя`")

    except Exception as e:
        log.error(f"show_clients error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")
        return

    await _reply(update, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# /newroadmap — создание дорожной карты (диалог)
# ─────────────────────────────────────────────────────────────

async def newroadmap_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Phase 10.2E: /newroadmap deprecated — вместо legacy-диалога сразу
    отправляет redirect на /startroadmap и завершает разговор. Не
    обращается к Google Sheets, не создаёт conversation state.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    context.user_data.pop("nr", None)

    await update.message.reply_text(
        "🗺 Команда /newroadmap больше не используется.\n\n"
        "Создание дорожной карты теперь выполняется через /startroadmap.\n\n"
        "Сначала создайте или выберите объект:\n"
        "- /newobject\n"
        "- /objects\n\n"
        "Затем используйте:\n"
        "`/startroadmap obj_id=OBJ-... service_id=SVC-... case_type=...`",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def newroadmap_business(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data["nr"]["business_name"] = text

    # Находим business_id
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("biz_registry")
        for r in rows:
            if text.lower() in r.get("Название", "").lower():
                context.user_data["nr"]["business_id"] = r.get("ID", "")
                break
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Бизнес: *{text}*\n\n"
        "Введи имя клиента (ФИО или имя):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NR_CLIENT


async def newroadmap_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    NOTE (Phase 31D): this ConversationHandler state is unreachable in
    production — the /newroadmap entry point (newroadmap_start) always
    redirects to /startroadmap and returns ConversationHandler.END
    before NR_CLIENT can ever be reached (see newroadmap_start's own
    docstring, Phase 10.2E). Migrated anyway per Phase 31D Part 6, since
    it is still wired into the ConversationHandler and the phase names
    it explicitly.
    """
    text = update.message.text.strip()
    context.user_data["nr"]["client_name"] = text

    # Phase 31D (ADR-015 Decision 6): owner API instead of raw
    # read_business_sheet("people_registry") + business_router's
    # substring/first-match fuzzy entity extractor. 0 matches → not
    # found (client_id left unset, same as before); exactly 1 match →
    # selected; >1 matches → ambiguity, never silently picks the first
    # (a real behavior tightening vs. the old fuzzy matcher — safe here
    # since this code path never actually runs in production).
    try:
        from business_core.person_manager import list_clients
        matches = list_clients(query=text)
        if len(matches) == 1:
            context.user_data["nr"]["client_id"] = matches[0]["person_id"]
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Клиент: *{text}*\n\n"
        "Укажи услугу (например: Узаконение частного дома):",
        parse_mode="Markdown",
    )
    return NR_SERVICE


async def newroadmap_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["nr"]["service_name"] = text

    # Находим service_id (Phase 29CD, Part 6: owner API вместо raw
    # read_business_sheet("service_catalog")). Ambiguity policy:
    # 0 совпадений — не найдено (service_id не выставляется, как и
    # раньше); 1 совпадение — выбрать; >1 совпадений — не выбирать
    # первое молча (раньше выбирался первый по порядку в листе).
    try:
        from business_core.service_manager import find_services_by_name
        biz_id = context.user_data["nr"].get("business_id", "")
        matches = find_services_by_name(text, biz_id=biz_id or None, active_only=True)
        if len(matches) == 1:
            context.user_data["nr"]["service_id"] = matches[0].get("service_id", "")
    except Exception:
        pass

    # Предложить известные города
    keyboard = [["Алматы", "Астана"], ["Шымкент", "Онлайн"], ["❌ Отмена"]]
    await update.message.reply_text(
        f"✅ Услуга: *{text}*\n\n"
        "Укажи город:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return NR_CITY


async def newroadmap_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data["nr"]["city"] = text

    await update.message.reply_text(
        f"✅ Город: *{text}*\n\n"
        "Ожидаемый срок (в днях, например: 60)?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["30", "60", "90"], ["❌ Отмена"]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return NR_DAYS


async def newroadmap_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    try:
        days = int(text)
    except ValueError:
        days = 60

    context.user_data["nr"]["expected_days"] = days
    nr = context.user_data["nr"]

    # Показать сводку и запросить подтверждение
    lines = [
        "📋 *Проверь дорожную карту:*",
        "",
        f"🏢 Бизнес:  {nr.get('business_name', '?')}",
        f"👤 Клиент:  {nr.get('client_name', '?')}",
        f"🛠 Услуга:  {nr.get('service_name', '?')}",
        f"📍 Город:   {nr.get('city', '?')}",
        f"📅 Срок:    {days} дней",
    ]

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Создать"], ["❌ Отмена"]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return NR_CONFIRM


async def newroadmap_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text or text == "❌":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop("nr", None)
        return ConversationHandler.END

    nr = context.user_data.get("nr", {})

    # Phase 28C/28D: this legacy state is unreachable in production —
    # the /newroadmap entry point (newroadmap_start) always replies with
    # a redirect to /startroadmap and returns ConversationHandler.END
    # immediately (Phase 10.2E), so this conversation state is never
    # actually entered by a real user. It is kept, per the "no command
    # removal in this phase" constraint, but no longer writes ROADMAPS/
    # ROADMAP_STAGES directly — it now calls the same canonical
    # orchestration entry point /startroadmap uses. This legacy flow has
    # no Object ID concept (it is client/service-centric, not
    # object-centric), so create_roadmap_for_object correctly rejects it
    # with a clear error — an honest reflection of this path's real,
    # already-dead status rather than an invented Object ID.
    try:
        from business_core.business_builder import create_roadmap_for_object

        result = create_roadmap_for_object(
            obj_id="",
            biz_id=nr.get("business_id", ""),
            client_id=nr.get("client_id", ""),
            service_id=nr.get("service_id", ""),
            title=nr.get("client_name", ""),
            notes="",
        )

        if not result["ok"]:
            await update.message.reply_text(
                f"❌ Ошибка сохранения: {result['error']}\n\nПопробуй /startroadmap",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text(
                f"✅ *Дорожная карта создана!*\n\n"
                f"🆔 ID: `{result['roadmap_id']}`\n"
                f"👤 Клиент: {nr.get('client_name', '?')}\n"
                f"🛠 Услуга: {nr.get('service_name', '?')}\n"
                f"📋 Этапов: {result.get('stages_count', 0)}\n\n"
                f"Первый шаг: /roadmaps",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )

    except Exception as e:
        log.error(f"newroadmap_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка сохранения: {e}\n\nПопробуй ещё раз: /newroadmap",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop("nr", None)
    return ConversationHandler.END


async def newroadmap_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nr", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# /newclient — добавление клиента (диалог)
# ─────────────────────────────────────────────────────────────

async def newclient_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    # Phase 11J: свежий вход в /newclient (в т.ч. через allow_reentry)
    # обязан сбросить и draft, и предыдущий confirmed snapshot — иначе
    # повторный вход мог бы оставить старый snapshot от прошлой,
    # незавершённой попытки.
    context.user_data["nc"] = {}
    context.user_data.pop("nc_confirmed_snapshot", None)
    await update.message.reply_text(
        "👤 *Новый клиент*\n\nВведи ФИО клиента:",
        parse_mode="Markdown",
    )
    return NC_NAME


async def newclient_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["nc"]["full_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 Телефон (или /skip чтобы пропустить):"
    )
    return NC_PHONE


async def newclient_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    context.user_data["nc"]["phone"] = "" if text.startswith("/skip") else text
    keyboard = [
        ["клиент", "партнер"],
        ["сотрудник", "подрядчик"],
        ["❌ Отмена"],
    ]
    await update.message.reply_text(
        "🏷 Тип контакта:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return NC_TYPE


async def newclient_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data["nc"]["person_type"] = text

    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("biz_registry")
        active = [r.get("Название", "") for r in rows if r.get("Статус", "") == "active"]
    except Exception:
        active = ["Узаконение", "Визы", "Коучинг"]

    keyboard = [[b] for b in active[:6]] + [["❌ Отмена"]]
    await update.message.reply_text(
        "🏢 К какому бизнесу относится (или /skip):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return NC_BIZ


async def newclient_biz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    nc = context.user_data["nc"]

    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if text.startswith("/skip"):
        nc["businesses"] = ""
        nc["biz_id_resolved"] = ""
    else:
        # Phase 13A: единый resolver бизнеса (BIZ-ID / точное название /
        # другой регистр / лишние пробелы -> один канонический BIZ-ID).
        # Если не резолвится — не сохраняем пустой Biz ID молча:
        # показываем ошибку и список активных бизнесов, остаёмся в этом
        # же состоянии, чтобы пользователь ввёл бизнес заново.
        from business_core.business_builder import resolve_business

        resolved = resolve_business(text)
        if not resolved["ok"]:
            active = resolved.get("active_businesses", [])
            lines = ["❌ Бизнес не распознан: «{}»".format(text)]
            if resolved.get("reason") == "ambiguous":
                lines[0] = "❌ Название неоднозначно, совпало несколько бизнесов: «{}»".format(text)
            lines.append("")
            lines.append("Доступные активные бизнесы:")
            for b in active:
                lines.append(f"  {b['id']} — {b['name']}")
            lines.append("")
            lines.append("Введи бизнес заново (ID или точное название), или /skip:")
            await update.message.reply_text("\n".join(lines))
            return NC_BIZ

        nc["businesses"] = resolved["biz_name"]
        nc["biz_id_resolved"] = resolved["biz_id"]

    lines = [
        "📋 *Проверь данные клиента:*",
        "",
        f"👤 ФИО:    {nc.get('full_name', '?')}",
        f"📱 Телефон: {nc.get('phone', '—')}",
        f"🏷 Тип:    {nc.get('person_type', '?')}",
        f"🏢 Бизнес: {nc.get('businesses', '—')}",
    ]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Сохранить"], ["❌ Отмена"]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )

    # Phase 11J: неизменяемый snapshot того, что показано в карточке
    # подтверждения. newclient_confirm() обязан сохранять ТОЛЬКО этот
    # snapshot, а не перечитывать context.user_data["nc"] заново — иначе
    # любое последующее изменение draft (повторный вход в состояние,
    # запоздавшее/дублирующееся обновление и т.п.) может привести к
    # сохранению данных, которые пользователь не подтверждал.
    context.user_data["nc_confirmed_snapshot"] = dict(nc)

    return NC_CONFIRM


async def newclient_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop("nc", None)
        context.user_data.pop("nc_confirmed_snapshot", None)
        return ConversationHandler.END

    # Phase 11J: сохраняем ТОЛЬКО неизменяемый snapshot, показанный в
    # карточке подтверждения (newclient_biz()) — никогда не перечитываем
    # context.user_data["nc"] здесь, т.к. draft мог измениться между
    # показом карточки и обработкой ответа пользователя.
    nc = context.user_data.get("nc_confirmed_snapshot")
    if nc is None:
        await update.message.reply_text(
            "❌ Не найдены подтверждённые данные клиента. Начни заново: /newclient",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("nc", None)
        context.user_data.pop("nc_confirmed_snapshot", None)
        return ConversationHandler.END

    try:
        from business_core.business_builder import provision_client_drive_safe
        from business_core.person_manager import (
            resolve_person_identity,
            create_person,
            update_person,
            ensure_client_role,
            append_person_biz_id,
            has_person_business_link,
            is_client_person,
        )

        full_name = nc.get("full_name", "")
        phone     = nc.get("phone", "")
        biz_name  = nc.get("businesses", "")
        biz_name  = "" if biz_name.startswith("/skip") else biz_name

        # Phase 13A: бизнес уже резолвлен единым resolve_business() в
        # newclient_biz() ДО показа карточки подтверждения — snapshot
        # содержит готовый biz_id_resolved, здесь его нужно только читать,
        # не резолвить заново (иначе снова возможен разрыв между тем, что
        # подтвердил пользователь, и тем, что сохраняется).
        biz_id_resolved = nc.get("biz_id_resolved", "")
        requested_type = nc.get("person_type", "клиент")

        # Phase 31D (ADR-015 Decision 2/4): canonical identity resolver,
        # called directly — NOT the find_existing_person/find_duplicate_
        # person compatibility wrappers. Archived rows are excluded by
        # default (a strong-only archived match surfaces as its own
        # status below, never silently reused/reactivated); a name-only
        # match — even a single one — is always "ambiguous", stricter
        # than the pre-31D behavior (see Phase 31D final report, Part 8).
        identity = resolve_person_identity(
            name=full_name or None, phone=phone or None, email=None,
        )
        status = identity["status"]

        # ── AMBIGUOUS: zero writes ────────────────────────────────
        if status == "ambiguous":
            lines = [
                "⚠️ Найдено несколько похожих контактов — не могу однозначно "
                "определить, это новый человек или уже существующий.",
                "",
            ]
            for p in identity["matches"][:5]:
                lines.append(
                    f"• {p.get('person_id', '?')} — {p.get('full_name', '?')} "
                    f"({_mask_phone_for_display(p.get('phone', ''))})"
                )
            lines.append("")
            lines.append("Уточни номер телефона или email и повтори /newclient.")
            await update.message.reply_text(
                "\n".join(lines), reply_markup=ReplyKeyboardRemove(), parse_mode=None,
            )
            context.user_data.pop("nc", None)
            context.user_data.pop("nc_confirmed_snapshot", None)
            return ConversationHandler.END

        # ── ARCHIVED_MATCH: zero writes, no reactivation ──────────
        if status == "archived_match":
            await update.message.reply_text(
                "⚠️ Найден архивный контакт с такими же данными. "
                "Автоматическое восстановление не выполняется — "
                "обратитесь к администратору для реактивации записи.",
                reply_markup=ReplyKeyboardRemove(), parse_mode=None,
            )
            context.user_data.pop("nc", None)
            context.user_data.pop("nc_confirmed_snapshot", None)
            return ConversationHandler.END

        STATUS_NEW       = "new"
        STATUS_SAME_BIZ  = "same_biz"
        STATUS_OTHER_BIZ = "other_biz"

        profile_fields_warning = False
        requesting_client_role = is_client_person({"person_type": requested_type})

        if status == "not_found":
            client_status = STATUS_NEW

            # Core identity write — the ONLY step whose failure reproduces
            # today's "❌ Ошибка сохранения" path (raising here lets the
            # existing outer `except Exception as e` handle it exactly as
            # before — no new error-handling shape introduced). create_person()
            # runs its own duplicate check (find_duplicate_person, now itself
            # a resolve_person_identity wrapper) immediately before writing —
            # if a race narrows what resolve_person_identity saw a moment ago,
            # this returns a structured {"ok": False, "error": ...}, handled
            # the same as any other create_person failure, not a raw exception.
            create_result = create_person(
                full_name=full_name,
                phone=phone,
                person_type=requested_type,
                business_id=biz_id_resolved,
                status="active",
            )
            if not create_result["ok"]:
                raise ValueError(create_result["error"])

            prs_id = create_result["person_id"]

            # Profile-field write — Бизнесы (legacy display name),
            # Уровень доверия, Теплота are /newclient-specific defaults,
            # deliberately NOT part of create_person()'s universal API
            # (Person Manager stays domain-neutral). A failure here is a
            # PARTIAL success: the Person itself is already confirmed
            # created, so this must never be reported as a save failure,
            # must never block Drive provisioning, and must never block
            # cache invalidation.
            update_result = update_person(prs_id, {
                "Бизнесы": biz_name,
                "Уровень доверия": "средний",
                "Теплота": "тёплый",
            })
            if not update_result["ok"]:
                profile_fields_warning = True
                log.warning(
                    f"newclient_confirm: update_person partial failure "
                    f"person_id={prs_id} operation=update_person "
                    f"error={update_result['error']} "
                    f"attempted_fields=['Бизнесы', 'Уровень доверия', 'Теплота']"
                )

            # Phase 31D (ADR-015 Decision 5/12): NOT calling
            # ensure_client_role() here deliberately — the freshly
            # created row's "Тип" is already exactly requested_type
            # (create_person() just wrote it), so ensure_client_role()
            # could only ever be a no-op confirmation for a NEW Person,
            # at the cost of one extra PEOPLE_REGISTRY read. It is still
            # used below for the existing-person (single_match) branch,
            # where the Person's current "Тип" is NOT already known to
            # match this request.

            try:
                from business_core.inbox_bridge import invalidate_cache
                invalidate_cache()
            except Exception:
                pass

        else:  # status == "single_match" — an existing Person
            person = identity["person"]
            prs_id = person["person_id"]

            # Phase 31D (ADR-015 Decision 5/12): client-role enforcement
            # only applies when THIS /newclient invocation is actually
            # requesting the Client role (person_type == "клиент"/
            # recognized subtype) — /newclient also serves партнер/
            # сотрудник/подрядчик contacts, which are legitimate non-Client
            # Person types this gate must not block.
            if requesting_client_role:
                role_result = ensure_client_role(prs_id)
                if role_result.get("manual_decision_required"):
                    await update.message.reply_text(
                        f"ℹ️ {role_result.get('warning') or 'Требуется ручное решение по типу контакта.'}\n\n"
                        f"Связь с бизнесом и Drive-папка не изменены.",
                        reply_markup=ReplyKeyboardRemove(), parse_mode=None,
                    )
                    context.user_data.pop("nc", None)
                    context.user_data.pop("nc_confirmed_snapshot", None)
                    return ConversationHandler.END

            same_biz = (not biz_id_resolved) or has_person_business_link(person, biz_id_resolved)
            if same_biz:
                client_status = STATUS_SAME_BIZ
            else:
                client_status = STATUS_OTHER_BIZ
                try:
                    append_person_biz_id(prs_id, biz_id_resolved)
                except Exception as exc:
                    log.warning(f"newclient add_biz_id error: {exc}")

        # ── Drive (Phase 31D, ADR-015 Decisions 14/15) ─────────────
        drive_msg = ""
        if biz_name:
            try:
                drive_result = provision_client_drive_safe(
                    person_id=prs_id, full_name=full_name, biz_name=biz_name,
                )
                if drive_result["ok"] and drive_result["folder_url"]:
                    drive_msg = f"\n📁 Drive: {drive_result['folder_url']}"
                    if drive_result["drive_reused"] and client_status == STATUS_OTHER_BIZ:
                        drive_msg += (
                            "\n⚠️ Для клиента уже существует общая папка. "
                            "Отдельная папка для нового бизнеса не создана."
                        )
                    if drive_result["partial_failure"]:
                        drive_msg += f"\n⚠️ {drive_result.get('warning', '')}"
                elif not drive_result["ok"]:
                    err = drive_result.get("error", "") or ""
                    if err and "не задан" not in err:
                        drive_msg = f"\n⚠️ Папка Drive не создана: {err}"
            except Exception as drive_exc:
                log.warning(f"newclient Drive error: {drive_exc}")

        # ── Ответ ─────────────────────────────────────────────────
        # Phase 11J: запись уже сохранена в Sheets к этому моменту —
        # ошибка форматирования ответа не должна выглядеть как ошибка
        # сохранения. parse_mode=None (без Markdown) — full_name и
        # drive_msg содержат динамические пользовательские данные и URL,
        # которые могут содержать "_"/"*"/"[" и ломать Markdown-парсер.
        if client_status == STATUS_NEW:
            header = "✅ Клиент добавлен!"
        elif client_status == STATUS_SAME_BIZ:
            header = "ℹ️ Клиент уже существует, использую существующую запись"
        else:
            header = "ℹ️ Контакт уже был в другом бизнесе, добавил связь с текущим бизнесом"

        warning_line = (
            "\n⚠️ Некоторые дополнительные поля профиля (бизнес/теплота) "
            "могли сохраниться не полностью — проверьте карточку клиента."
            if profile_fields_warning else ""
        )

        try:
            await update.message.reply_text(
                f"{header}\n\n"
                f"🆔 ID: {prs_id}\n"
                f"👤 {full_name}"
                f"{drive_msg}"
                f"{warning_line}\n\n"
                f"/clients — посмотреть всех клиентов",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode=None,
            )
        except Exception as notify_exc:
            # Persistence уже отработала успешно — сообщаем об успехе, а
            # не о несуществующей ошибке сохранения.
            log.warning(f"newclient_confirm notify error: {notify_exc}")
            await update.message.reply_text(
                f"✅ Клиент сохранён (ID: {prs_id}), но не удалось отобразить полную карточку.",
                reply_markup=ReplyKeyboardRemove(),
            )

    except Exception as e:
        log.error(f"newclient_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка сохранения: {e}",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop("nc", None)
    context.user_data.pop("nc_confirmed_snapshot", None)
    return ConversationHandler.END


async def newclient_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nc", None)
    context.user_data.pop("nc_confirmed_snapshot", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# /editclient — безопасное редактирование PEOPLE_REGISTRY (Phase 13A)
# ─────────────────────────────────────────────────────────────
#
# Root cause этой фазы: не было способа исправить опечатку клиента без
# прямой правки Google Sheets. Архитектура повторяет immutable-snapshot
# паттерн /newclient (Phase 11J): поле выбирается -> вводится новое
# значение -> строится карточка "было/станет" -> снимается snapshot ->
# ТОЛЬКО после явного подтверждения выполняется ОДНА точечная запись
# в уже найденную (перечитанную заново) строку. ID/Drive Folder ID/
# Created At никогда не трогаются.

EDITCLIENT_FIELDS = {
    "Имя (ФИО)": "full_name",
    "Телефон": "phone",
    "Бизнес": "business",
    "Комментарий": "notes",
}


async def editclient_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /editclient client_id=PRS-001

    Загружает клиента, показывает текущие значения и предлагает выбрать
    ОДНО поле для изменения. Ничего не пишет в Sheets на этом шаге.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    client_id = kv.get("client_id") or kv.get("_pos0", "")

    if not client_id:
        await update.message.reply_text(
            "❌ Укажи client_id.\n\nПример:\n/editclient client_id=PRS-001"
        )
        return ConversationHandler.END

    from business_core.person_manager import find_person_by_id
    person = find_person_by_id(client_id)
    if not person:
        await update.message.reply_text(f"❌ Клиент {client_id} не найден.")
        return ConversationHandler.END

    # "Бизнесы" (free-text business display name) is not part of
    # find_person_by_id()'s canonical field set — derived here from
    # Primary Biz ID via the existing business_builder.get_business_config()
    # (a BIZ_REGISTRY read, not PEOPLE_REGISTRY) rather than adding a new
    # Person Manager API.
    biz_name = ""
    if person["primary_biz_id"]:
        from business_core.business_builder import get_business_config
        biz_name = get_business_config(person["primary_biz_id"]).get("name", "")

    biz_ids_display = ",".join(person["biz_ids"])
    current = {
        "ФИО": person["full_name"],
        "Телефон": person["phone"],
        "Бизнесы": biz_name,
        "Biz IDs": biz_ids_display,
        "Комментарий": person["notes"],
    }

    row_number = person["row_num"]
    context.user_data["ec"] = {
        "client_id": client_id,
        "row_number": row_number,
        "current": current,
    }
    context.user_data.pop("ec_confirmed_snapshot", None)

    lines = [
        "✏️ Редактирование клиента",
        "",
        f"ID: {client_id}",
        f"ФИО: {current['ФИО']}",
        f"Телефон: {current['Телефон']}",
        f"Бизнес: {current['Бизнесы']} (Biz IDs: {current['Biz IDs']})",
        f"Комментарий: {current['Комментарий']}",
        "",
        "Выбери поле для изменения:",
    ]
    keyboard = [[k] for k in EDITCLIENT_FIELDS] + [["❌ Отмена"]]
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return EC_FIELD


def _editclient_current_display(current: dict, field_key: str) -> str:
    return {
        "full_name": current.get("ФИО", ""),
        "phone": current.get("Телефон", ""),
        "business": current.get("Бизнесы", ""),
        "notes": current.get("Комментарий", ""),
    }[field_key]


async def editclient_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        context.user_data.pop("ec", None)
        context.user_data.pop("ec_confirmed_snapshot", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    field_key = EDITCLIENT_FIELDS.get(text)
    if not field_key:
        await update.message.reply_text("❌ Выбери поле из списка ниже.")
        return EC_FIELD

    context.user_data["ec"]["field"] = field_key
    current_display = _editclient_current_display(context.user_data["ec"]["current"], field_key)

    await update.message.reply_text(
        f"Текущее значение: {current_display or '—'}\n\nВведи новое значение:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return EC_VALUE


async def editclient_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ec = context.user_data["ec"]
    field_key = ec["field"]
    current = ec["current"]

    if not text:
        await update.message.reply_text("❌ Значение не может быть пустым. Введи новое значение:")
        return EC_VALUE

    old_value = _editclient_current_display(current, field_key)

    if field_key == "business":
        from business_core.business_builder import resolve_business
        resolved = resolve_business(text)
        if not resolved["ok"]:
            active = resolved.get("active_businesses", [])
            lines = [f"❌ Бизнес не распознан: «{text}»"]
            if resolved.get("reason") == "ambiguous":
                lines[0] = f"❌ Название неоднозначно, совпало несколько бизнесов: «{text}»"
            lines.append("")
            lines.append("Доступные активные бизнесы:")
            for b in active:
                lines.append(f"  {b['id']} — {b['name']}")
            lines.append("")
            lines.append("Введи бизнес заново (ID или точное название):")
            await update.message.reply_text("\n".join(lines))
            return EC_VALUE
        ec["new_biz_id"] = resolved["biz_id"]
        ec["new_biz_name"] = resolved["biz_name"]
        new_value_display = resolved["biz_name"]
    else:
        new_value_display = text

    ec["new_value"] = text
    ec["old_value_display"] = old_value
    ec["new_value_display"] = new_value_display

    field_labels = {v: k for k, v in EDITCLIENT_FIELDS.items()}
    await update.message.reply_text(
        f"📋 Подтверди изменение:\n\n"
        f"Поле: {field_labels[field_key]}\n"
        f"Было: {old_value or '—'}\n"
        f"Станет: {new_value_display or '—'}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Сохранить"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )

    # Phase 13A: immutable snapshot того, что показано в карточке
    # подтверждения — editclient_confirm() сохраняет только его.
    context.user_data["ec_confirmed_snapshot"] = dict(ec)
    return EC_CONFIRM


async def editclient_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        context.user_data.pop("ec", None)
        context.user_data.pop("ec_confirmed_snapshot", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    snap = context.user_data.get("ec_confirmed_snapshot")
    if snap is None:
        await update.message.reply_text(
            "❌ Не найдены подтверждённые данные для сохранения. Начни заново: /editclient",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("ec", None)
        context.user_data.pop("ec_confirmed_snapshot", None)
        return ConversationHandler.END

    try:
        from business_core.person_manager import find_person_by_id, update_person
        from business_core.inbox_bridge import invalidate_cache

        client_id = snap["client_id"]
        field_key = snap["field"]

        # Phase 23D-3A: structural (not error-string-based) staleness
        # guard — re-checks existence right before writing, exactly as
        # the prior find_row_by_id() re-read did, just via Person
        # Manager's own read API instead of a raw Sheets call.
        if find_person_by_id(client_id) is None:
            await update.message.reply_text(
                f"❌ Клиент {client_id} больше не найден — изменение не выполнено.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            if field_key == "full_name":
                parts = snap["new_value"].split()
                updates = {
                    "ФИО": snap["new_value"],
                    "Имя": parts[0] if parts else snap["new_value"],
                }
            elif field_key == "phone":
                updates = {"Телефон": snap["new_value"]}
            elif field_key == "business":
                updates = {
                    "Бизнесы": snap["new_biz_name"],
                    "Biz IDs": snap["new_biz_id"],
                    "Primary Biz ID": snap["new_biz_id"],
                }
            elif field_key == "notes":
                updates = {"Комментарий": snap["new_value"]}

            result = update_person(client_id, updates)
            # A write attempt was just made — update_person() cannot
            # prove how many cells landed if it failed partway through
            # (see its own docstring / Phase 23D-2 technical debt note),
            # so the cache is invalidated unconditionally here rather
            # than only on result["ok"] — never inferred from parsing
            # result["error"].
            invalidate_cache()

            if result["ok"]:
                field_labels = {v: k for k, v in EDITCLIENT_FIELDS.items()}
                await update.message.reply_text(
                    f"✅ Клиент {client_id} обновлён\n\n"
                    f"Поле: {field_labels[field_key]}\n"
                    f"Было: {snap['old_value_display'] or '—'}\n"
                    f"Стало: {snap['new_value_display'] or '—'}",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                log.warning(
                    f"editclient_confirm: update_person failure "
                    f"person_id={client_id} field={field_key} error={result['error']}"
                )
                await update.message.reply_text(
                    f"❌ Ошибка сохранения: {result['error']}",
                    reply_markup=ReplyKeyboardRemove(),
                )

    except Exception as e:
        log.error(f"editclient_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка сохранения: {e}",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop("ec", None)
    context.user_data.pop("ec_confirmed_snapshot", None)
    return ConversationHandler.END


async def editclient_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("ec", None)
    context.user_data.pop("ec_confirmed_snapshot", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# /editobject — безопасное редактирование OBJECT_REGISTRY (Phase 13A)
# ─────────────────────────────────────────────────────────────
#
# Object ID / Client ID / Drive Folder ID / Created At / Roadmap ID
# никогда не изменяются этой командой. Client ID сознательно НЕ входит
# в первую версию — архитектура связей объект/Drive/roadmap не даёт
# безопасно сменить владельца объекта одной точечной правкой ячейки.

EDITOBJECT_FIELDS = {
    "Адрес": "address",
    "Тип объекта": "object_type",
    "Комментарий": "notes",
}


async def editobject_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/editobject object_id=OBJ-001"""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    obj_id = kv.get("object_id") or kv.get("obj_id") or kv.get("_pos0", "")

    if not obj_id:
        await update.message.reply_text(
            "❌ Укажи object_id.\n\nПример:\n/editobject object_id=OBJ-001"
        )
        return ConversationHandler.END

    from business_core.object_manager import find_object_by_id
    obj = find_object_by_id(obj_id)
    if not obj:
        await update.message.reply_text(f"❌ Объект {obj_id} не найден.")
        return ConversationHandler.END

    context.user_data["eo"] = {
        "obj_id": obj_id,
        "current": obj,
    }
    context.user_data.pop("eo_confirmed_snapshot", None)

    lines = [
        "✏️ Редактирование объекта",
        "",
        f"OBJ ID: {obj_id}",
        f"Адрес: {obj.get('address', '')}",
        f"Тип объекта: {obj.get('object_type', '')}",
        f"Комментарий: {obj.get('notes', '')}",
        "",
        "Выбери поле для изменения:",
    ]
    keyboard = [[k] for k in EDITOBJECT_FIELDS] + [["❌ Отмена"]]
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return EO_FIELD


def _editobject_current_display(current: dict, field_key: str) -> str:
    return {
        "address": current.get("address", ""),
        "object_type": current.get("object_type", ""),
        "notes": current.get("notes", ""),
    }[field_key]


async def editobject_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        context.user_data.pop("eo", None)
        context.user_data.pop("eo_confirmed_snapshot", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    field_key = EDITOBJECT_FIELDS.get(text)
    if not field_key:
        await update.message.reply_text("❌ Выбери поле из списка ниже.")
        return EO_FIELD

    context.user_data["eo"]["field"] = field_key
    current_display = _editobject_current_display(context.user_data["eo"]["current"], field_key)

    extra = ""
    if field_key == "address":
        extra = "\n\n⚠️ Имя Drive-папки при этом НЕ переименовывается."

    await update.message.reply_text(
        f"Текущее значение: {current_display or '—'}{extra}\n\nВведи новое значение:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return EO_VALUE


async def editobject_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    eo = context.user_data["eo"]
    field_key = eo["field"]

    if not text:
        await update.message.reply_text("❌ Значение не может быть пустым. Введи новое значение:")
        return EO_VALUE

    old_value = _editobject_current_display(eo["current"], field_key)
    eo["new_value"] = text
    eo["old_value_display"] = old_value
    eo["new_value_display"] = text

    field_labels = {v: k for k, v in EDITOBJECT_FIELDS.items()}
    extra = "\n⚠️ Имя Drive-папки останется прежним." if field_key == "address" else ""
    await update.message.reply_text(
        f"📋 Подтверди изменение:\n\n"
        f"Поле: {field_labels[field_key]}\n"
        f"Было: {old_value or '—'}\n"
        f"Станет: {text or '—'}"
        f"{extra}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Сохранить"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )

    context.user_data["eo_confirmed_snapshot"] = dict(eo)
    return EO_CONFIRM


async def editobject_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        context.user_data.pop("eo", None)
        context.user_data.pop("eo_confirmed_snapshot", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    snap = context.user_data.get("eo_confirmed_snapshot")
    if snap is None:
        await update.message.reply_text(
            "❌ Не найдены подтверждённые данные для сохранения. Начни заново: /editobject",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("eo", None)
        context.user_data.pop("eo_confirmed_snapshot", None)
        return ConversationHandler.END

    try:
        from business_core.object_manager import find_object_by_id, update_object_fields

        obj_id = snap["obj_id"]
        field_key = snap["field"]

        obj = find_object_by_id(obj_id)
        if not obj:
            await update.message.reply_text(
                f"❌ Объект {obj_id} больше не найден — изменение не выполнено.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            result = update_object_fields(obj_id, {field_key: snap["new_value"]})
            if not result["ok"]:
                await update.message.reply_text(
                    f"❌ Ошибка сохранения: {result['error']}",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                field_labels = {v: k for k, v in EDITOBJECT_FIELDS.items()}
                extra = "\n⚠️ Имя Drive-папки осталось прежним." if field_key == "address" else ""
                await update.message.reply_text(
                    f"✅ Объект {obj_id} обновлён\n\n"
                    f"Поле: {field_labels[field_key]}\n"
                    f"Было: {snap['old_value_display'] or '—'}\n"
                    f"Стало: {snap['new_value_display'] or '—'}"
                    f"{extra}",
                    reply_markup=ReplyKeyboardRemove(),
                )

    except Exception as e:
        log.error(f"editobject_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка сохранения: {e}",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop("eo", None)
    context.user_data.pop("eo_confirmed_snapshot", None)
    return ConversationHandler.END


async def editobject_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("eo", None)
    context.user_data.pop("eo_confirmed_snapshot", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# /initbc — заполнить таблицу начальными данными
# ─────────────────────────────────────────────────────────────

async def init_bc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Заполнить BUSINESS_CORE таблицу начальными данными:
    бизнесы из business_registry.list_default_businesses()
    и услуги из service_catalog.
    Пропускает уже существующие записи (проверяет по Slug).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    await update.message.reply_text("⏳ Инициализирую Business Core...", parse_mode="Markdown")

    try:
        from business_core.sheets import (
            read_business_sheet, append_business_row, generate_next_id
        )
        from business_core.business_registry import list_default_businesses
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d")
        added_biz = 0
        skipped_biz = 0

        # Загружаем существующие записи
        existing_rows = read_business_sheet("biz_registry")
        existing_slugs = {r.get("Slug", "").lower() for r in existing_rows}

        # priority: "high"→1, "medium"→2, "low"→3
        _prio_map = {"high": "1", "medium": "2", "low": "3"}

        businesses = list_default_businesses()
        for biz in businesses:
            slug = biz.slug.lower()
            if slug in existing_slugs:
                skipped_biz += 1
                continue

            biz_id = generate_next_id("biz_registry", "BIZ")
            row = [
                biz_id,
                biz.name,
                biz.slug,
                biz.status,
                biz.description or "",
                ", ".join(biz.cities),
                biz.owner or "Дидар",
                _prio_map.get(str(biz.priority), "2"),
                now,
                "", "", "", "", "", "", "", "", "", "",  # Drive, Sheet, GTD, интеграции, комментарий
                now,  # Последнее обновление
            ]
            append_business_row("biz_registry", row)
            existing_slugs.add(slug)
            added_biz += 1

        # Дефолтные услуги
        default_services = [
            ("Узаконение гаража",                 "BIZ-001", "Алматы", "150000", "250000", "30"),
            ("Узаконение частного дома",           "BIZ-001", "Алматы", "200000", "400000", "60"),
            ("Узаконение коммерческой недвижимости","BIZ-001", "Алматы", "300000", "600000", "90"),
            ("Туристическая виза",                 "BIZ-002", "Алматы", "15000",  "30000",  "14"),
            ("Рабочая виза",                       "BIZ-002", "Алматы", "30000",  "60000",  "30"),
            ("Стратегическая сессия",              "BIZ-003", "Онлайн", "50000",  "150000", "7"),
        ]

        # Phase 29CD: /initbc больше не пишет service_catalog напрямую
        # (append_business_row + собственная генерация ID/slug) — оба
        # шага теперь принадлежат владельцу, business_core.service_manager
        # .create_service_record(), которая идемпотентна по duplicate key
        # (Business ID, normalized Service Name) — повторный /initbc
        # безопасен и переиспользует уже созданные услуги вместо
        # собственной name-based проверки, которая раньше это делала.
        from business_core.service_manager import create_service_record
        added_svc = 0
        reused_svc = 0
        svc_errors: list[str] = []

        for (name, biz_id, city, price_min, price_max, days) in default_services:
            svc_result = create_service_record(
                biz_id=biz_id,
                service_name=name,
                city=city,
                price_from=price_min,
                price_to=price_max,
                estimated_duration=days,
            )
            if not svc_result["ok"]:
                svc_errors.append(f"{name}: {svc_result['error']}")
                continue
            if svc_result["service_created"]:
                added_svc += 1
            elif svc_result["service_reused"]:
                reused_svc += 1

        lines = [
            "✅ *Business Core инициализирован!*",
            "",
            f"🏢 Бизнесов добавлено: {added_biz} (пропущено: {skipped_biz})",
            f"🛠 Услуг добавлено: {added_svc}",
        ]
        if svc_errors:
            lines.append(f"⚠️ Ошибки услуг: {len(svc_errors)}")
        lines += [
            "",
            "Теперь попробуй:",
            "/bc — дашборд",
            "/newroadmap — создать дорожную карту",
            "/newclient — добавить клиента",
        ]
        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"init_bc error: {e}")
        await _reply(update, f"❌ Ошибка инициализации: {e}")


# ─────────────────────────────────────────────────────────────
# /newbiz — добавление бизнеса (диалог)
# ─────────────────────────────────────────────────────────────

async def newbiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    context.user_data["nb"] = {}
    await update.message.reply_text(
        "🏢 *Новый бизнес*\n\nВведи название направления:",
        parse_mode="Markdown",
    )
    return NB_NAME


async def newbiz_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["nb"]["name"] = update.message.text.strip()
    keyboard = [["Алматы, Астана", "Алматы, Шымкент"],
                ["Алматы", "Астана"], ["Онлайн"], ["❌ Отмена"]]
    await update.message.reply_text(
        "📍 Города (выбери или напиши через запятую):",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return NB_CITIES


async def newbiz_cities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    context.user_data["nb"]["cities"] = text
    keyboard = [["1 — Высокий", "2 — Средний", "3 — Низкий"], ["❌ Отмена"]]
    await update.message.reply_text(
        "⭐ Приоритет:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return NB_PRIORITY


async def newbiz_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    priority = "1" if "1" in text else "3" if "3" in text else "2"
    context.user_data["nb"]["priority"] = priority
    nb = context.user_data["nb"]

    await update.message.reply_text(
        f"📋 *Проверь:*\n\n"
        f"🏢 Название: {nb['name']}\n"
        f"📍 Города: {nb['cities']}\n"
        f"⭐ Приоритет: {priority}",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Создать"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )
    return NB_CONFIRM


async def newbiz_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if "Отмена" in text:
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop("nb", None)
        return ConversationHandler.END

    nb = context.user_data.get("nb", {})

    try:
        from business_core.sheets import append_business_row, generate_next_id
        from business_core.business_registry import _slugify
        from datetime import datetime

        biz_id = generate_next_id("biz_registry", "BIZ")
        slug = _slugify(nb.get("name", ""))
        now = datetime.now().strftime("%Y-%m-%d")

        row = [
            biz_id,
            nb.get("name", ""),
            slug,
            "active",
            "",                      # описание
            nb.get("cities", ""),
            "Дидар",                 # ответственный
            nb.get("priority", "2"),
            now,
            "", "", "", "", "", "", "", "", "", "", now,
        ]
        append_business_row("biz_registry", row)

        # ── Drive интеграция (безопасная, не ломает GTD) ─────────
        drive_note = ""
        try:
            from business_core.business_builder import (
                provision_biz_drive, save_drive_info_to_sheets,
            )
            drive_res = provision_biz_drive(biz_id, nb.get("name", ""))
            if drive_res["ok"]:
                save_drive_info_to_sheets(
                    biz_id,
                    drive_res["folder_id"],
                    drive_res["folder_url"],
                )
                drive_note = f"\n📁 [Drive папка]({drive_res['folder_url']})"
            elif drive_res.get("error"):
                short_err = str(drive_res["error"])[:80]
                drive_note = f"\n⚠️ Бизнес создан, но папка Drive не создана: {short_err}"
        except Exception as _drive_exc:
            log.warning(f"newbiz Drive integration error: {_drive_exc}")
        # ─────────────────────────────────────────────────────────

        await update.message.reply_text(
            f"✅ *Бизнес создан!*\n\n"
            f"🆔 `{biz_id}`\n"
            f"🏢 {nb['name']}\n"
            f"📍 {nb['cities']}"
            f"{drive_note}\n\n"
            f"/bc — дашборд\n"
            f"/newroadmap — первая дорожная карта",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        log.error(f"newbiz_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка: {e}", reply_markup=ReplyKeyboardRemove()
        )

    context.user_data.pop("nb", None)
    return ConversationHandler.END


async def newbiz_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nb", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# /bcdrive — создать Drive-структуру для бизнеса
# ─────────────────────────────────────────────────────────────

async def bc_drive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Создать папки в Google Drive для бизнеса."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    drive_enabled = os.getenv("BUSINESS_DRIVE_ENABLED", "false").lower()
    if drive_enabled != "true":
        await _reply(update,
            "⚠️ *Google Drive не настроен*\n\n"
            "Добавь в `.env`:\n"
            "`BUSINESS_DRIVE_ENABLED=true`\n"
            "`DRIVE_ROOT_FOLDER_ID=<ID корневой папки>`\n\n"
            "Затем дай service account доступ к папке Drive."
        )
        return

    args = context.args
    if not args:
        await _reply(update,
            "Укажи название бизнеса:\n"
            "`/bcdrive Узаконение недвижимости`"
        )
        return

    biz_name = " ".join(args)
    await update.message.reply_text(
        f"⏳ Создаю структуру для *{biz_name}*...",
        parse_mode="Markdown",
    )

    try:
        from integrations.google_drive_adapter import (
            get_drive_service, create_business_structure, format_structure_report
        )

        service = get_drive_service()
        result = create_business_structure(service, biz_name)
        report = format_structure_report(result)

        # Сохранить Drive URL в BIZ_REGISTRY
        try:
            from business_core.sheets import read_business_sheet, update_business_cell
            biz_rows = read_business_sheet("biz_registry")
            for i, r in enumerate(biz_rows, start=2):
                if biz_name.lower() in r.get("Название", "").lower():
                    headers = ["ID", "Название", "Slug", "Статус", "Описание",
                               "Города", "Ответственный", "Приоритет", "Дата старта",
                               "Google Drive"]
                    drive_col = len(headers)
                    update_business_cell("biz_registry", i, drive_col, result["root_url"])
                    break
        except Exception:
            pass

        await _reply(update, report)

    except Exception as e:
        log.error(f"bc_drive error: {e}")
        await _reply(update, f"❌ Ошибка создания Drive-структуры: {e}")


# ─────────────────────────────────────────────────────────────
# Фаза 5B: подтверждение бизнес-контекста
# ─────────────────────────────────────────────────────────────

async def send_bc_confirmation(update: Update, confirm_data: dict) -> None:
    """
    Отправить отдельное сообщение с кнопками подтверждения бизнес-контекста.
    Вызывается из telegram_bot.py когда 0.5 <= confidence < 0.9.

    Никогда не бросает исключений — ошибки логируются тихо.
    """
    try:
        lines = ["🤔 *Я правильно понял бизнес-контекст?*\n"]

        if confirm_data.get("business_name"):
            lines.append(f"🏢 {confirm_data['business_name']}")
        if confirm_data.get("city"):
            lines.append(f"📍 {confirm_data['city']}")
        if confirm_data.get("client_name"):
            client_str = confirm_data["client_name"]
            if not confirm_data.get("client_id"):
                client_str += " _(не в базе)_"
            lines.append(f"👤 {client_str}")
        if confirm_data.get("roadmap_id"):
            lines.append(f"🗺 Карта: `{confirm_data['roadmap_id']}`")

        conf_pct = int(confirm_data.get("confidence", 0) * 100)
        lines.append(f"\n_Уверенность: {conf_pct}%_")

        text = "\n".join(lines)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да", callback_data="bc_ctx:yes"),
                InlineKeyboardButton("✏️ Изменить", callback_data="bc_ctx:edit"),
                InlineKeyboardButton("Только GTD", callback_data="bc_ctx:gtd"),
            ]
        ])

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

    except Exception as e:
        log.debug(f"send_bc_confirmation error (silent): {e}")


async def bc_ctx_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик всех трёх кнопок подтверждения бизнес-контекста.
    callback_data: "bc_ctx:yes" | "bc_ctx:edit" | "bc_ctx:gtd"
    """
    query = update.callback_query
    await query.answer()  # убирает индикатор загрузки

    action = query.data.split(":")[1] if ":" in query.data else ""

    if action == "yes":
        await query.edit_message_text(
            query.message.text + "\n\n✅ *Бизнес-контекст подтверждён*",
            parse_mode="Markdown",
        )

    elif action == "gtd":
        await query.edit_message_text(
            "Ок, оставил только в GTD",
            parse_mode="Markdown",
        )

    elif action == "edit":
        await query.edit_message_text(
            "Пока изменение вручную: уточни бизнес / клиента / карту одним сообщением",
            parse_mode="Markdown",
        )

    else:
        await query.answer("Неизвестное действие")


# ─────────────────────────────────────────────────────────────
# Регистрация всех handlers
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Phase 7A: /newobject и /objects
# ─────────────────────────────────────────────────────────────

def _parse_kv_args(text: str) -> dict:
    """
    Разобрать строку аргументов вида:
      biz_id=BIZ-001 client_id=PRS-001 city=Алматы address="ул. Абая 10"

    Поддерживает значения в кавычках (одинарных или двойных).
    Токены без '=' записываются как _pos0, _pos1, ... (позиционные аргументы).
    """
    import re
    result: dict[str, str] = {}
    # Паттерн: ключ=значение или "quoted value" или одиночное слово
    token_pattern = r'(\w+)=(?:"([^"]*?)"|\'([^\']*?)\'|(\S+))|"([^"]*?)"|\'([^\']*?)\'|(\S+)'
    pos_idx = 0
    for m in re.finditer(token_pattern, text):
        if m.group(1):
            # key=value
            key = m.group(1)
            val = m.group(2) or m.group(3) or m.group(4) or ""
            result[key] = val.strip()
        else:
            # позиционный: "quoted" или слово
            val = m.group(5) or m.group(6) or m.group(7) or ""
            result[f"_pos{pos_idx}"] = val.strip()
            pos_idx += 1
    return result


async def newobject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newobject biz_id=BIZ-001 client_id=PRS-001 city=Алматы address="ул. Абая 10"
               type="частный дом" cadastral="12:34:56" area=120 notes="..."

    Минимальный формат:
    /newobject BIZ-001 PRS-001 Алматы ул. Абая 10
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    if not raw.strip():
        await _reply(update, (
            "❌ Использование:\n"
            "`/newobject biz_id=BIZ-001 client_id=PRS-001 city=Алматы address=\"ул. Абая 10\"`\n\n"
            "Необязательные: `type`, `cadastral`, `area`, `notes`"
        ))
        return

    # Парсинг аргументов
    kv = _parse_kv_args(raw)

    biz_id    = kv.get("biz_id", "")
    client_id = kv.get("client_id", "")
    city      = kv.get("city", "")
    address   = kv.get("address", "")

    # Минимальный формат: позиционные аргументы (biz city addr без ключей)
    if not biz_id or not client_id:
        parts = raw.split()
        if len(parts) >= 4:
            biz_id    = biz_id    or parts[0]
            client_id = client_id or parts[1]
            city      = city      or parts[2]
            address   = address   or " ".join(parts[3:])

    if not biz_id or not client_id or not city or not address:
        await _reply(update, (
            "❌ Необходимы: `biz_id`, `client_id`, `city`, `address`\n\n"
            "Пример:\n"
            "`/newobject biz_id=BIZ-001 client_id=PRS-001 city=Алматы address=\"ул. Абая 10\"`"
        ))
        return

    object_type  = kv.get("type", "")
    cadastral    = kv.get("cadastral", "")
    area         = kv.get("area", "")
    notes        = kv.get("notes", "")

    await update.message.reply_text("⏳ Создаю объект...", parse_mode="Markdown")

    try:
        from business_core.business_builder import (
            create_object_record,
            provision_object_drive,
        )

        # Проверяем что бизнес существует (Phase 30D, Part 5 — тот же
        # canonical primitive, что уже используется во всех остальных
        # местах Business Core для проверки biz_id: business_builder.py,
        # organization_manager.py, person_manager.py, newservice_cmd).
        # Business Domain ещё не имеет отдельного owner-модуля.
        from business_core.sheets import find_row_by_id
        biz_row = find_row_by_id("biz_registry", biz_id)
        if biz_row is None:
            await _reply(update, f"❌ Бизнес `{biz_id}` не найден в BIZ_REGISTRY")
            return

        # Phase 31D (ADR-015 Decisions 11/12): Client-role and existing
        # Business-link validation, replacing the old silent
        # add_biz_id_to_person() auto-link. /newobject must never
        # mutate a Person's Business links itself — that is /newclient's
        # job. Each rejection below returns before create_object_record()
        # or provision_object_drive() is ever called: zero Object/Drive
        # writes on any invalid Client condition.
        from business_core.person_manager import (
            find_person_by_id, is_person_archived, is_client_person, has_person_business_link,
        )
        person = find_person_by_id(client_id)

        if person is None:
            await _reply(update, f"❌ Клиент `{client_id}` не найден в PEOPLE_REGISTRY")
            return

        if is_person_archived(person):
            await _reply(update, "❌ Клиент находится в архиве")
            return

        if not is_client_person(person):
            await _reply(update, "❌ Сначала оформите человека как клиента через /newclient")
            return

        if not has_person_business_link(person, biz_id):
            await _reply(
                update,
                "❌ Клиент не привязан к этому бизнесу. "
                "Сначала добавьте его через /newclient.",
            )
            return

        # Создаём (или конвергентно переиспользуем) объект в OBJECT_REGISTRY
        res = create_object_record(
            client_id=client_id,
            biz_id=biz_id,
            city=city,
            address=address,
            cadastral_number=cadastral,
            area_m2=area,
            object_type=object_type,
            object_status="new",
            notes=notes,
        )

        if not res["ok"]:
            await _reply(update, f"❌ Ошибка создания объекта: {res['error']}")
            return

        obj_id = res["obj_id"]
        was_reused = res.get("object_reused", False)
        warnings = res.get("warnings") or []

        # Drive (безопасно, не ломает создание/переиспользование объекта;
        # provision_object_drive само по себе retry-safe — не создаёт
        # вторую папку, если Drive Folder ID уже установлен, Phase 30D Part 6)
        drive_msg = ""
        try:
            drive_res = provision_object_drive(
                biz_id=biz_id,
                client_id=client_id,
                obj_id=obj_id,
                city=city,
                address=address,
                object_type=object_type,
            )
            if drive_res["ok"] and drive_res.get("folder_url"):
                if drive_res.get("drive_reused"):
                    drive_msg = f"\n📁 [Drive папка]({drive_res['folder_url']}) (уже существовала)"
                else:
                    drive_msg = f"\n📁 [Drive папка]({drive_res['folder_url']})"
            elif drive_res.get("error") and "не задан" not in drive_res["error"] and "not configured" not in drive_res["error"]:
                drive_msg = f"\n⚠️ Drive папка не создана: {drive_res['error'][:60]}"
        except Exception as e:
            log.warning(f"newobject Drive error: {e}")

        # Ответ
        type_line = f"\nТип: {object_type}" if object_type else ""
        cadr_line = f"\nКадастр: {cadastral}" if cadastral else ""
        area_line = f"\nПлощадь: {area} м²" if area else ""
        warnings_msg = ""
        if was_reused and warnings:
            warnings_lines = "\n".join(f"  • {w}" for w in warnings)
            warnings_msg = f"\n\n⚠️ Отличия от уже сохранённых данных (не перезаписаны):\n{warnings_lines}"

        title = "✅ *Объект уже существовал*" if was_reused else "✅ *Объект создан*"

        await update.message.reply_text(
            f"{title}\n\n"
            f"🆔 OBJ ID: `{obj_id}`\n"
            f"👤 Клиент: `{client_id}`\n"
            f"🏢 Бизнес: `{biz_id}`\n"
            f"📍 Город: {city}\n"
            f"🏠 Адрес: {address}"
            f"{type_line}{cadr_line}{area_line}\n"
            f"📊 Статус: new"
            f"{drive_msg}"
            f"{warnings_msg}\n\n"
            f"/objects client\\_id={client_id} — объекты клиента",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )

    except Exception as e:
        log.error(f"newobject_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


async def objects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /objects
    /objects BIZ-001
    /objects client_id=PRS-001
    /objects biz_id=BIZ-001 client_id=PRS-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    kv  = _parse_kv_args(raw)

    biz_id    = kv.get("biz_id", "")
    client_id = kv.get("client_id", "")

    # Позиционный: /objects BIZ-001
    if not biz_id and raw.strip():
        first = raw.strip().split()[0]
        if first.startswith("BIZ-"):
            biz_id = first
        elif first.startswith("PRS-"):
            client_id = first

    try:
        from business_core.object_manager import (
            find_objects_by_client,
            find_objects_by_biz,
            list_objects,
        )

        # Получаем объекты — все чтения через object_manager (owner API),
        # без raw registry reads (Phase 30D, Part 2).
        if client_id:
            objects = find_objects_by_client(client_id, biz_id=biz_id or None)
        elif biz_id:
            objects = find_objects_by_biz(biz_id)
        else:
            objects = list_objects()

        if not objects:
            filter_desc = ""
            if biz_id:    filter_desc += f" по бизнесу `{biz_id}`"
            if client_id: filter_desc += f" по клиенту `{client_id}`"
            await _reply(update, f"📭 Объекты не найдены{filter_desc}.\n\n`/newobject biz_id=... client_id=... city=... address=...`")
            return

        MAX_SHOW = 20
        lines = [f"🏠 *Объекты* ({len(objects)} шт.):\n"]
        for obj in objects[:MAX_SHOW]:
            rm    = f" · 🗺 `{obj['roadmap_id']}`" if obj.get("roadmap_id") else ""
            drive = f" · [📁]({obj['drive_url']})" if obj.get("drive_url") else ""
            lines.append(
                f"• `{obj['object_id']}` | {obj.get('city','')} | {obj.get('address','')[:30]}"
                f"\n  [{obj.get('object_type','—')}] {obj.get('status','—')}"
                f" · 👤`{obj.get('client_id','')}`{rm}{drive}"
            )
        if len(objects) > MAX_SHOW:
            lines.append(f"\n_...показано {MAX_SHOW} из {len(objects)}_")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    except Exception as e:
        log.error(f"objects_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /startroadmap — создать Roadmap для объекта (Phase 7B)
# ─────────────────────────────────────────────────────────────

# Phase 33D (ADR-016 §14 caller-facing UX): a single, centralized
# mapping from business_builder.create_roadmap_for_object()'s stable,
# machine-readable error_code to Russian user-facing text. This module
# performs presentation ONLY — it never re-derives *why* a code fired
# (that decision was already made, once, inside create_roadmap_for_object
# per ADR-016). Codes needing structured extra data (candidate lists,
# conflicting IDs) are rendered by _roadmap_failure_message() below
# instead of this flat table.
_ROADMAP_ERROR_MESSAGES: dict[str, str] = {
    "BUSINESS_NOT_FOUND": "Бизнес не найден.",
    "CLIENT_NOT_FOUND": "Клиент не найден.",
    "CLIENT_ARCHIVED": "Клиент архивирован — Roadmap не создан.",
    "CLIENT_ROLE_REQUIRED": "У клиента нет роли «клиент».",
    "CLIENT_NOT_LINKED_TO_BUSINESS": "Клиент не привязан к этому бизнесу.",
    "OBJECT_NOT_FOUND": "Объект не найден.",
    "OBJECT_NOT_ELIGIBLE": "Статус объекта не позволяет создать Roadmap.",
    "OBJECT_BUSINESS_MISMATCH": "Объект принадлежит другому бизнесу.",
    "OBJECT_CLIENT_MISMATCH": "Объект привязан к другому клиенту.",
    "SERVICE_NOT_FOUND": "Услуга не найдена.",
    "SERVICE_INACTIVE": "Услуга не активна.",
    "SERVICE_BUSINESS_MISMATCH": "Услуга принадлежит другому бизнесу.",
    "TEMPLATE_NOT_FOUND": "Указанный или связанный шаблон не найден либо недоступен.",
    "TEMPLATE_SERVICE_MISMATCH": "Шаблон принадлежит другой услуге.",
    # Actual stable code emitted by create_roadmap_for_object (ADR-016
    # §12/§13) — the Phase 33D spec's "ROADMAP_IMMUTABLE_IDENTITY_CONFLICT"
    # name does not exist in the Phase 33C implementation; this maps the
    # real code instead of inventing a parallel alias.
    "ROADMAP_IMMUTABLE_FIELD_CONFLICT": (
        "Найден существующий Roadmap с другими Business/Client — "
        "новый Roadmap не создан, существующий не изменён."
    ),
}


def _roadmap_failure_message(rm_result: dict, obj_id: str, service_id: str) -> str:
    """
    Render rm_result (ok=False) into a single Russian Telegram message.
    Presentation only — every branch here reacts to a structured field
    already computed by create_roadmap_for_object(); none of them
    re-validate anything.
    """
    error_code = rm_result.get("error_code", "")

    if error_code == "MULTIPLE_TEMPLATES_REQUIRE_SELECTION":
        candidates = rm_result.get("candidate_template_ids", [])
        lines = ["❌ Найдено несколько подходящих шаблонов — нужен явный выбор.\n"]
        for tid in candidates:
            lines.append(f"• `{tid}`")
        lines.append(
            f"\nПовтори команду с явным шаблоном:\n"
            f"`/startroadmap obj_id={obj_id} service_id={service_id} "
            f"template_id=RMT-...`"
        )
        return "\n".join(lines)

    if error_code == "MULTIPLE_OPEN_ROADMAPS_INTEGRITY_ERROR":
        conflicting = rm_result.get("conflicting_roadmap_ids", [])
        return (
            f"❌ Найдено {len(conflicting)} открытых Roadmap для этого объекта и услуги — "
            f"новый Roadmap не создан.\n\n"
            f"Конфликтующие Roadmap: {', '.join(f'`{r}`' for r in conflicting)}\n\n"
            f"Это конфликт данных, требующий проверки вручную — ни один из них "
            f"не выбран и не изменён автоматически."
        )

    if error_code in _ROADMAP_ERROR_MESSAGES:
        # The centralized table above is the authoritative statement of
        # what each code MEANS; create_roadmap_for_object's own "error"
        # text is already safe, specific, human-readable Russian
        # (includes the concrete IDs involved) — preferred when present
        # so the user sees exactly which Business/Client/Object/Service/
        # Template ID triggered the code, falling back to the generic
        # category text only if "error" is somehow empty.
        return f"❌ {rm_result.get('error') or _ROADMAP_ERROR_MESSAGES[error_code]}"

    if error_code:
        # Unknown/unmapped code: safe generic fallback — never expose
        # the raw structured result or a stack trace to Telegram, but
        # log it (structured, non-secret) so it can be triaged.
        log.warning(
            "startroadmap_cmd: unmapped error_code=%r for obj_id=%s service_id=%s",
            error_code, obj_id, service_id,
        )
        return "❌ Не удалось создать Roadmap из-за ошибки проверки данных. Попробуй ещё раз позже."

    # No error_code at all (identifier-level rejections from steps A,
    # which predate the structured contract) — the human-readable
    # "error" string is already safe, static text written by
    # create_roadmap_for_object itself, never raw exception content.
    return f"❌ Не удалось создать Roadmap: {rm_result.get('error') or 'неизвестная ошибка'}"


def _roadmap_success_lines(rm_result: dict, obj_id: str, service_id: str, case_type: str) -> list[str]:
    """
    Render rm_result (ok=True) into the list of message lines shown for
    a successful call — which may still carry non-blocking warnings or
    a partial-failure notice. Presentation only.
    """
    from business_core.roadmap_manager import ROADMAP_TEMPLATES

    roadmap_id      = rm_result["roadmap_id"]
    used_template   = rm_result.get("used_template", False)
    roadmap_created = rm_result.get("roadmap_created", True)
    roadmap_reused  = rm_result.get("roadmap_reused", False)
    stages_created  = rm_result.get("stages_count", 0)
    stages_reused   = rm_result.get("stages_reused", False)
    existing_stage_count = rm_result.get("existing_stage_count", 0)
    effective_template_id = rm_result.get("selected_template_id") or rm_result.get("template_id", "")

    if roadmap_created:
        lines = ["✅ *Roadmap создан*\n", f"Roadmap ID: `{roadmap_id}`"]
    else:
        # ROADMAP_REUSED — never phrased as "создан" for a reused Roadmap.
        lines = [
            "ℹ️ *Найден существующий Roadmap — используется он*\n",
            f"Roadmap ID: `{roadmap_id}`",
            "Новый Roadmap не создан — переиспользован существующий.",
        ]

    lines += [
        f"Object ID:  `{obj_id}`",
        f"Service ID: `{service_id or '—'}`",
    ]
    if effective_template_id and used_template:
        lines.append(f"Шаблон: `{effective_template_id}`")
    elif case_type and case_type != "general":
        lines.append(f"Case Type: `{case_type}`")

    # template_warning is also present in "warnings" (API completeness
    # for other callers) — shown once, via its own dedicated line below,
    # so it is excluded from the generic warnings list here.
    template_warning = rm_result.get("template_warning")
    other_warnings = [w for w in rm_result.get("warnings", ()) if w != template_warning]

    # Phase 28G/33D: distinguish new-Roadmap / reused-with-additions /
    # already-fully-converged stage outcomes — never say "создан" for a
    # reused Roadmap's stages either.
    if roadmap_created:
        lines.append(f"Этапов создано: {stages_created}")
    elif stages_created:
        lines.append(f"Добавлено отсутствующих этапов: {stages_created}")
    elif stages_reused or existing_stage_count:
        lines.append("Новых этапов не создано — все уже существовали.")
    else:
        lines.append("Новых этапов не создано.")

    # Показать первые 5 названий built-in шаблона — только для НОВОГО
    # Roadmap, использующего case_type-fallback (у переиспользуемого
    # Roadmap этапы уже существуют, показывать нечего).
    if roadmap_created and not used_template:
        stage_names = ROADMAP_TEMPLATES.get(case_type, [])
        if stage_names:
            lines.append("\n*Следующие шаги:*")
            for i, name in enumerate(stage_names[:5], start=1):
                lines.append(f"{i}. {name}")
            if len(stage_names) > 5:
                lines.append(f"   ... (+{len(stage_names) - 5} этапов)")

    if template_warning:
        lines.append(f"\n⚠️ {template_warning}")

    for w in other_warnings:
        lines.append(f"\n⚠️ {w}")

    # Phase 33C (ADR-016 §6): Object Type compatibility is a non-blocking
    # warning only — shown, never rejected. Client Type validation
    # remains explicitly deferred (ADR-016 §7) and never produces a
    # user-facing message here.
    type_warning = rm_result.get("type_compatibility_warning")
    if type_warning and type_warning.get("status") == "mismatch":
        lines.append(
            "\n⚠️ Дорожная карта создана, но тип объекта и тип услуги отличаются. "
            "Проверьте правильность выбранной услуги.\n"
            f"Тип объекта: `{type_warning.get('object_type') or '—'}`\n"
            f"Тип объекта услуги: `{type_warning.get('service_object_type') or '—'}`"
        )
    elif type_warning and type_warning.get("status") == "unavailable":
        lines.append("\n⚠️ Не удалось проверить совместимость типа объекта с услугой.")

    # Phase 33C: a Stage-materialization failure is now a structural
    # field (error_code + partial_failure), not just a warning string —
    # the Roadmap itself is retained, safe to retry.
    if rm_result.get("error_code") == "STAGE_MATERIALIZATION_PARTIAL_FAILURE":
        lines.append(
            f"\n⚠️ Roadmap `{roadmap_id}` создан, но не все этапы удалось создать. "
            f"Повторить команду безопасно — новый Roadmap создан не будет."
        )

    # Extension (relation-copy) failures never roll back an already-
    # committed Roadmap/Stages.
    if rm_result.get("relation_copy_errors"):
        lines.append(
            f"\n⚠️ Часть связей документов не скопирована для "
            f"{len(rm_result['relation_copy_errors'])} этап(ов). "
            f"Этапы созданы корректно; связи можно досоздать позже."
        )

    lines.append(f"\nПросмотр этапов: `/stages roadmap_id={roadmap_id}`")
    return lines


async def startroadmap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Создать roadmap для объекта по услуге и типу кейса.

    Форматы:
      /startroadmap obj_id=OBJ-001 service_id=SVC-001 case_type=legalization_reconstruction_house
      /startroadmap OBJ-001 SVC-001 legalization_reconstruction_house
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        raw = (update.message.text or "").split(None, 1)[1] if context.args else " ".join(context.args or [])
    except (IndexError, TypeError):
        raw = ""

    args = _parse_kv_args(raw)

    obj_id     = args.get("obj_id")     or args.get("_pos0", "")
    service_id = args.get("service_id") or args.get("_pos1", "")
    case_type  = args.get("case_type")  or args.get("_pos2", "general")
    title      = args.get("title", "")
    notes      = args.get("notes", "")

    if not obj_id:
        await _reply(update,
            "❌ Укажи obj\\_id объекта.\n\n"
            "Пример:\n`/startroadmap obj_id=OBJ-001 service_id=SVC-001 "
            "case_type=legalization_reconstruction_house`"
        )
        return

    if not service_id.strip():
        # Phase Closeout Remediation (finding #1): service_id is part of
        # the (Object ID, Service ID) duplicate key — silently defaulting
        # to "" here let a blank Service ID reach create_roadmap_for_object,
        # which then skipped the active-Roadmap reuse lookup entirely and
        # created a second, distinct Roadmap for an Object that already
        # had one (the RM-002 incident). Required now, same as obj_id.
        await _reply(update,
            "❌ Не указан service\\_id.\n\n"
            "Пример:\n`/startroadmap obj_id=OBJ-001 service_id=SVC-001 "
            "case_type=legalization_reconstruction_house`"
        )
        return

    try:
        from business_core.business_builder import find_object_by_id, create_roadmap_for_object

        obj = find_object_by_id(obj_id)
        if not obj:
            await _reply(update, f"❌ Объект `{obj_id}` не найден. Проверь /objects")
            return

        biz_id    = obj.get("biz_id", "")
        client_id = obj.get("client_id", "")

        explicit_template_id = args.get("template_id", "").strip()

        # ── Создать roadmap + этапы ─────────────────────────────
        # Phase 33C (ADR-016): create_roadmap_for_object() is the sole
        # cross-domain validation boundary (Business/Client/Object/
        # Service/Object Type/Template/duplicate Roadmap). This handler
        # (Phase 33D) does not re-implement or duplicate any of that —
        # it only collects arguments, calls this one function, and
        # translates its structured result into a Telegram message via
        # _roadmap_failure_message()/_roadmap_success_lines() above.
        rm_result = create_roadmap_for_object(
            obj_id=obj_id,
            biz_id=biz_id,
            client_id=client_id,
            service_id=service_id,
            case_type=case_type,
            title=title,
            notes=notes,
            template_id=explicit_template_id,
        )

        log.info(
            "startroadmap_cmd result: ok=%s error_code=%s roadmap_id=%s "
            "roadmap_created=%s roadmap_reused=%s partial_failure=%s "
            "conflicting_roadmap_ids=%s candidate_template_ids=%s "
            "type_warning_status=%s",
            rm_result.get("ok"), rm_result.get("error_code") or "",
            rm_result.get("roadmap_id") or "", rm_result.get("roadmap_created"),
            rm_result.get("roadmap_reused"), rm_result.get("partial_failure"),
            rm_result.get("conflicting_roadmap_ids") or [],
            rm_result.get("candidate_template_ids") or [],
            (rm_result.get("type_compatibility_warning") or {}).get("status"),
        )

        if not rm_result["ok"]:
            await _reply(update, _roadmap_failure_message(rm_result, obj_id, service_id))
            return

        roadmap_id = rm_result["roadmap_id"]
        lines = _roadmap_success_lines(rm_result, obj_id, service_id, case_type)

        # Object -> Roadmap reference update (Phase 30D/ADR-014 Decision 8:
        # "update only if empty" — a compatibility field, never blocks
        # anything above). Phase 33D surfaces a genuine write failure
        # (not the harmless "already set" no-op) as a visible, non-fatal
        # partial-failure notice — the Roadmap above is never hidden or
        # rolled back because of it.
        from business_core.business_builder import update_object_roadmap_id
        obj_ref_result = update_object_roadmap_id(obj_id, roadmap_id)
        if isinstance(obj_ref_result, dict) and obj_ref_result.get("ok") is False:
            log.warning(
                "startroadmap_cmd: object reference update failed for obj_id=%s roadmap_id=%s",
                obj_id, roadmap_id,
            )
            lines.append(
                f"\n⚠️ Roadmap `{roadmap_id}` создан, но не удалось обновить ссылку "
                f"на него в объекте `{obj_id}`. Повторить команду безопасно."
            )

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"startroadmap_cmd error: {e}")
        await _reply(update, "❌ Не удалось обработать команду из-за внутренней ошибки. Попробуй ещё раз позже.")


# ─────────────────────────────────────────────────────────────
# /stages — показать этапы roadmap (Phase 7B)
# ─────────────────────────────────────────────────────────────

async def stages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать этапы roadmap.

    Форматы:
      /stages roadmap_id=RM-001
      /stages RM-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        raw = (update.message.text or "").split(None, 1)[1] if context.args else " ".join(context.args or [])
    except (IndexError, TypeError):
        raw = ""

    args       = _parse_kv_args(raw)
    roadmap_id = args.get("roadmap_id") or args.get("_pos0", "")

    if not roadmap_id:
        await _reply(update,
            "❌ Укажи roadmap\\_id.\n\nПример: `/stages roadmap_id=RM-001`"
        )
        return

    try:
        from business_core.roadmap_manager import get_stages_for_roadmap, find_roadmap_by_id

        rm = find_roadmap_by_id(roadmap_id)
        stages = get_stages_for_roadmap(roadmap_id)

        if not stages and not rm:
            await _reply(update, f"❌ Roadmap `{roadmap_id}` не найден.")
            return

        header = f"📋 *Этапы {roadmap_id}*"
        if rm:
            header += f" — {rm.get('client_name', '')}"
            if rm.get("case_type"):
                header += f" (`{rm['case_type']}`)"

        lines = [header, ""]

        if not stages:
            lines.append("Этапы ещё не созданы.")
        else:
            status_icons = {
                "pending":     "⬜",
                "in_progress": "🔄",
                "done":        "✅",
                "blocked":     "🔴",
                "waiting":     "⏳",
                "skipped":     "⏭",
            }
            for s in stages:
                icon = status_icons.get(s["status"], "⬜")
                line = f"{icon} *{s['order']}.* {s['name']}"
                if s.get("due_date"):
                    line += f" _(до {s['due_date']})_"
                lines.append(line)
                lines.append(f"   ID: {s.get('stage_id', '') or '—'}")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"stages_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /updatestage — обновить статус этапа (Phase 9B)
# ─────────────────────────────────────────────────────────────

# Phase 34D (ADR-017 §12 caller-facing UX): human-readable Russian
# names for the canonical Stage statuses (ADR-009) — presentation only,
# machine IDs/status codes are always shown alongside, never hidden.
_STAGE_STATUS_RU: dict[str, str] = {
    "pending": "Ожидает",
    "in_progress": "В работе",
    "blocked": "Заблокирован",
    "done": "Выполнен",
    "skipped": "Пропущен",
}


def _stage_status_ru(status: str) -> str:
    """Russian display name for a canonical Stage status, falling back
    to the raw value for anything unrecognized (never hides an unknown
    status behind a placeholder)."""
    ru = _STAGE_STATUS_RU.get(status)
    return f"{ru} (`{status}`)" if ru else (status or "—")


# Phase 34C/34D (ADR-017 §12): centralized error_code -> Russian message
# mapping for business_builder.transition_stage_status()'s structured
# result. Presentation only — every branch here reacts to a field the
# orchestration function already computed; none of them re-validate
# anything, mirroring the Phase 33D Roadmap-creation UX pattern. Static
# entries are used verbatim; codes needing structured detail (current/
# requested status, conflicting Roadmap state) are rendered by
# _stage_transition_failure_message()'s per-code branches below instead.
_STAGE_TRANSITION_ERROR_MESSAGES: dict[str, str] = {
    "STAGE_NOT_FOUND": "Этап не найден.",
    "ROADMAP_NOT_FOUND": "Roadmap для этапа не найден.",
}


def _render_output_gate_missing_lines(instance_ids, template_ids, titles, statuses) -> list[str]:
    """Phase B: shared per-item renderer for the Required Output
    Completion Gate — used by both the output-only and the combined
    (Document+Checklist+Output) blocking messages so the two never
    duplicate this formatting. An empty Instance ID (the
    "instance_missing" case — an active blocking relation whose instance
    was never created via /syncoutputs) is shown as
    "[instance отсутствует]" instead of a blank."""
    lines = []
    for instance_id, template_id, title, status in zip(instance_ids, template_ids, titles, statuses):
        instance_label = instance_id if instance_id else "[instance отсутствует]"
        lines.append(f"- {instance_label} / {template_id} — {title or '—'} — {status}")
    return lines


def _stage_transition_failure_message(result: dict, stage_id: str, status: str) -> str:
    """
    Render a failed transition_stage_status() result (ok=False) into a
    single Russian Telegram message. Never exposes a raw stack trace or
    Python object — an unmapped code gets a safe generic fallback and a
    logged warning for triage.
    """
    code = result.get("code", "")
    roadmap_id = result.get("roadmap_id") or "—"
    previous_status = result.get("previous_status") or ""
    requested_status = result.get("requested_status") or status

    if code == "STAGE_NOT_FOUND":
        return "\n".join([
            "❌ Этап не найден",
            f"Этап: `{stage_id}`",
        ])

    if code == "ROADMAP_NOT_FOUND":
        return "\n".join([
            "❌ Не удалось найти Roadmap для этого этапа",
            f"Этап: `{stage_id}`",
            "Это указывает на проблему в данных — требуется проверка, а не автоматическое исправление.",
        ])

    if code == "INVALID_STAGE_STATUS":
        from business_core.roadmap_manager import STAGE_STATUS_CANONICAL
        return "\n".join([
            "❌ Недопустимый статус",
            f"Запрошено: `{requested_status}`",
            f"Допустимые значения: `{', '.join(STAGE_STATUS_CANONICAL)}`",
            "(значение `not_started` при чтении распознаётся как `pending`, "
            "но как цель команды не принимается)",
        ])

    if code == "INVALID_STAGE_TRANSITION":
        return "\n".join([
            "❌ Такой переход статуса не разрешён",
            f"Этап: `{stage_id}`",
            f"Текущий статус: {_stage_status_ru(previous_status)}",
            f"Запрошенный статус: {_stage_status_ru(requested_status)}",
        ])

    if code == "STAGE_REOPEN_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Этап уже завершён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Текущий статус: {_stage_status_ru(previous_status)}",
            f"Запрошенный статус: {_stage_status_ru(requested_status)}",
            "",
            "Этап со статусом «Выполнен» или «Пропущен» нельзя вернуть в работу "
            "обычной командой изменения статуса. Для этого потребуется отдельное "
            "действие повторного открытия, которое пока не реализовано. "
            "Повтор этой же команды не изменит результат.",
        ])

    if code == "ROADMAP_ON_HOLD":
        return "\n".join([
            "⏸️ Roadmap временно приостановлен (on_hold)",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "Изменение статуса этапа сейчас не разрешено. "
            "Административные поля (ответственный, срок, приоритет, причина блокировки) "
            "по-прежнему можно редактировать.",
        ])

    if code == "ROADMAP_COMPLETED":
        return "\n".join([
            "✅ Roadmap уже завершён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "Изменение статуса и административных полей этапа заблокировано. "
            "Возврат к работе потребует отдельного будущего действия по жизненному "
            "циклу Roadmap — не выполняется автоматически.",
        ])

    if code == "ROADMAP_CANCELLED":
        return "\n".join([
            "🚫 Roadmap отменён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "Изменения этапа заблокированы. Небезопасный повтор не предлагается — "
            "исторические данные не изменяются.",
        ])

    if code == "STAGE_WRITE_PARTIAL_FAILURE":
        return "\n".join([
            "❌ Не удалось обновить этап",
            f"Этап: `{stage_id}`",
            f"Текущий подтверждённый статус: {_stage_status_ru(result.get('final_status') or previous_status)}",
            f"Причина: {result.get('error') or 'не удалось подтверждённо записать статус'}",
        ])

    if code == "STAGE_DOCUMENT_GATE_BLOCKED":
        missing = result.get("missing_blocking_doc_ids", ())
        return "\n".join([
            "🔒 Завершение заблокировано — не хватает обязательных документов",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Missing Blocking Document Template IDs: {', '.join(missing) if missing else '—'}",
            "",
            "Чтобы всё же завершить этап, используй явный override:",
            f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`",
        ])

    if code == "STAGE_DOCUMENT_REQUIREMENTS_CONFIGURATION_ERROR":
        return "\n".join([
            "⚠️ Завершение заблокировано — повреждена настройка требований к документам",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Детали: {result.get('configuration_error_details') or result.get('error') or '—'}",
            "Требуется проверка администратора настроек этапа.",
            "",
            "Чтобы всё же завершить этап, используй явный override:",
            f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`",
        ])

    if code == "STAGE_CHECKLIST_GATE_BLOCKED":
        instance_ids = result.get("missing_checklist_instance_ids", ())
        item_ids = result.get("missing_checklist_item_ids", ())
        titles = result.get("missing_checklist_item_titles", ())
        return "\n".join([
            "🔒 Завершение заблокировано — не хватает обязательных пунктов чек-листа",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Checklist Instance IDs: {', '.join(instance_ids) if instance_ids else '—'}",
            f"Missing Checklist Item IDs: {', '.join(item_ids) if item_ids else '—'}",
            f"Невыполненные пункты: {', '.join(titles) if titles else '—'}",
            "",
            "Чтобы всё же завершить этап, используй явный override:",
            f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`",
        ])

    if code == "STAGE_OUTPUT_GATE_BLOCKED":
        instance_ids = result.get("missing_blocking_output_instance_ids", ())
        template_ids = result.get("missing_blocking_output_template_ids", ())
        titles = result.get("missing_blocking_output_titles", ())
        statuses = result.get("missing_blocking_output_statuses", ())
        lines = [
            "🔒 Завершение заблокировано — не приняты обязательные результаты",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "",
            "── Required Outputs ──",
            "Не приняты результаты:",
        ]
        lines.extend(_render_output_gate_missing_lines(instance_ids, template_ids, titles, statuses))
        lines.append("")
        lines.append("Чтобы всё же завершить этап, используй явный override:")
        lines.append(f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`")
        return "\n".join(lines)

    if code == "STAGE_COMPLETION_GATE_BLOCKED":
        missing_docs = result.get("missing_blocking_doc_ids", ())
        instance_ids = result.get("missing_checklist_instance_ids", ())
        item_ids = result.get("missing_checklist_item_ids", ())
        titles = result.get("missing_checklist_item_titles", ())
        output_instance_ids = result.get("missing_blocking_output_instance_ids", ())
        output_template_ids = result.get("missing_blocking_output_template_ids", ())
        output_titles = result.get("missing_blocking_output_titles", ())
        output_statuses = result.get("missing_blocking_output_statuses", ())
        lines = [
            "🔒 Завершение заблокировано сразу по нескольким причинам",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
        ]
        if missing_docs:
            lines.append(f"Missing Blocking Document Template IDs: {', '.join(missing_docs)}")
        if result.get("configuration_error_details"):
            lines.append(f"Ошибка настройки требований к документам: {result.get('configuration_error_details')}")
        if instance_ids:
            lines.append(f"Checklist Instance IDs: {', '.join(instance_ids)}")
        if item_ids:
            lines.append(f"Missing Checklist Item IDs: {', '.join(item_ids)}")
        if titles:
            lines.append(f"Невыполненные пункты чек-листа: {', '.join(titles)}")
        if output_template_ids:
            lines.append("")
            lines.append("── Required Outputs ──")
            lines.append("Не приняты результаты:")
            lines.extend(_render_output_gate_missing_lines(
                output_instance_ids, output_template_ids, output_titles, output_statuses,
            ))
        lines.append("")
        lines.append("Чтобы всё же завершить этап, используй явный override:")
        lines.append(f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`")
        return "\n".join(lines)

    if code in ("STAGE_DOCUMENT_GATE_OVERRIDE_REASON_REQUIRED", "STAGE_COMPLETION_GATE_OVERRIDE_REASON_REQUIRED"):
        return "\n".join([
            "❌ force=yes требует явную причину",
            f"Этап: `{stage_id}`",
            f"`/updatestage stage_id={stage_id} status=done force=yes reason=\"...\"`",
        ])

    known_message = _STAGE_TRANSITION_ERROR_MESSAGES.get(code)
    if known_message:
        return "\n".join([
            "❌ Не удалось обновить этап",
            f"Этап: `{stage_id}`",
            f"Причина: {result.get('error') or known_message}",
        ])

    if code:
        log.warning(
            "updatestage_cmd: unmapped code=%r for stage_id=%s requested_status=%s",
            code, stage_id, status,
        )
        return "❌ Не удалось обновить этап из-за ошибки проверки данных. Попробуй ещё раз позже."
    return f"❌ Не удалось обновить этап: {result.get('error') or 'неизвестная ошибка'}"


def _stage_transition_success_lines(result: dict, stage_id: str, notes: Optional[str]) -> list[str]:
    """
    Render a successful transition_stage_status() result (ok=True) into
    the list of message lines — which may still carry a downstream
    partial-failure notice (progress recalculation or Roadmap
    auto-completion). Presentation only.
    """
    code = result.get("code", "")
    changed = result.get("changed")
    previous_status = result.get("previous_status")
    final_status = result.get("final_status")
    roadmap_id = result.get("roadmap_id") or "—"
    downstream_failures = list(result.get("downstream_failures", ()))
    partial_success = bool(result.get("partial_success"))
    retry_safe = result.get("retry_safe", True)

    if partial_success:
        # ADR-017 §12: the Stage Status write itself already succeeded —
        # this is never presented as a total failure, only as a clearly
        # scoped downstream shortfall.
        lines = [
            "⚠️ Статус этапа сохранён, но не всё обновилось полностью",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Статус сохранён: {_stage_status_ru(previous_status)} → {_stage_status_ru(final_status)}" if changed
            else f"Статус подтверждён: {_stage_status_ru(final_status)} (без изменений)",
        ]
        if code == "PROGRESS_RECALCULATION_FAILED":
            lines.append("Прогресс Roadmap мог не пересчитаться и временно устареть.")
        elif code == "ROADMAP_AUTO_COMPLETION_FAILED":
            lines.append("Статус и прогресс, вероятно, уже сохранены — не удалось проверить завершение Roadmap.")
        if downstream_failures:
            lines.append("Не удалось обновить:")
            for item in downstream_failures:
                lines.append(f"- {item}")
        if retry_safe:
            lines.append("Повтор команды безопасен.")
    elif changed:
        lines = [
            "✅ Статус этапа обновлён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Было: {_stage_status_ru(previous_status)}",
            f"Стало: {_stage_status_ru(final_status)}",
        ]
    else:
        lines = [
            "ℹ️ Этап уже имеет запрошенный статус",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            f"Текущий статус: {_stage_status_ru(final_status)} (изменений нет, повтор безопасен).",
        ]

    if changed and roadmap_id and roadmap_id != "—":
        progress_before = result.get("progress_before")
        progress_after = result.get("progress_after")
        if progress_after is not None:
            if progress_before is not None and progress_before != progress_after:
                lines.append(f"Прогресс: {progress_before}% → {progress_after}%")
            else:
                lines.append(f"Прогресс: {progress_after}%")

        roadmap_status_before = result.get("roadmap_status_before")
        roadmap_status_after = result.get("roadmap_status_after")
        # ADR-017 §11/Phase 34D §11: only ever shown when the structured
        # result confirms an ACTUAL active->completed transition — never
        # inferred merely from progress reaching 100.
        if roadmap_status_before == "active" and roadmap_status_after == "completed":
            lines.append(f"🎉 Все этапы завершены. Roadmap `{roadmap_id}` переведена в статус «Завершена».")

    if not partial_success:
        for w in result.get("warnings", ()):
            lines.append(f"⚠️ {w}")

    if result.get("override_applied"):
        lines.append(
            f"🔓 Применён override completion gate (force=yes). "
            f"Override ID: `{result.get('override_id') or '—'}`, тип: `{result.get('override_type') or '—'}`."
        )
        titles = result.get("missing_checklist_item_titles", ())
        if titles:
            lines.append(f"Обойдённые пункты чек-листа: {', '.join(titles)}")
        output_titles = result.get("missing_blocking_output_titles", ())
        if output_titles:
            lines.append(f"Обойдённые Required Output: {', '.join(output_titles)}")

    if notes is not None:
        lines.append(f"Notes обновлены: {notes}")

    return lines


async def updatestage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обновить статус этапа дорожной карты.

    Форматы:
      /updatestage stage_id=STAGE-xxx status=done
      /updatestage stage_id=STAGE-xxx status=blocked notes="Ожидаем документы клиента"
      /updatestage stage_id=STAGE-xxx status=done force=yes reason="..."

    status принимает только: pending, in_progress, blocked, done, skipped.
    notes с пробелами нужно указывать в кавычках (как и в остальных командах).

    Меняет только колонки Status (и Notes, если notes передан) в найденной
    строке ROADMAP_STAGES. После успешного изменения статуса автоматически
    пересчитывает Progress % roadmap (Phase 9E.1) и, если roadmap реально
    завершён (все этапы done/skipped, Progress % == 100, Status == active),
    переводит его в completed (Phase 9E.2) — вызывается только если статус
    этапа валиден и этап найден. Не пишет историю, не делает массовых
    обновлений, не открывает completed обратно в active.

    Phase 43 (Document Completion Gate): переход in_progress→done
    проверяет закрытость обязательных (blocking) требований к документам
    этапа. Явный override — только через параметры команды (`force=yes`
    и обязательный непустой `reason="..."`), никогда через свободный
    текст-«подтверждение» (это ушло бы в GTD Inbox, а не в эту команду).
    `force` без `status=done` не имеет эффекта на другие переходы.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        raw = (update.message.text or "").split(None, 1)[1] if context.args else " ".join(context.args or [])
    except (IndexError, TypeError):
        raw = ""

    args = _parse_kv_args(raw)

    stage_id = args.get("stage_id") or args.get("_pos0", "")
    status   = args.get("status")   or args.get("_pos1", "")
    notes    = args.get("notes")
    force    = args.get("force", "").strip().lower() == "yes"
    reason   = args.get("reason")

    if not stage_id or not status:
        from business_core.roadmap_manager import STAGE_STATUS_CANONICAL
        await _reply(update,
            "❌ Укажи stage\\_id и status.\n\n"
            f"Допустимые статусы: `{', '.join(STAGE_STATUS_CANONICAL)}`\n\n"
            "Примеры:\n"
            "`/updatestage stage_id=STAGE-001-01 status=done`\n"
            "`/updatestage stage_id=STAGE-001-01 status=blocked "
            "notes=\"Ожидаем документы клиента\"`\n"
            "`/updatestage stage_id=STAGE-001-01 status=done force=yes reason=\"...\"`"
        )
        return

    try:
        from business_core.business_builder import transition_stage_status

        # Phase 34C (ADR-017): transition_stage_status() is the sole
        # canonical orchestration boundary — it resolves the Stage, the
        # parent Roadmap, checks Roadmap eligibility (active/on_hold/
        # completed/cancelled), validates the current→target transition
        # (including the done/skipped explicit-reopen block), enforces
        # the Phase 43 document completion gate for in_progress→done,
        # persists Status, recalculates Progress %, and maybe auto-
        # completes the Roadmap. This handler only parses input and
        # renders the structured result — it no longer calls
        # update_stage_status_in_sheet, recalculate_roadmap_progress, or
        # maybe_complete_roadmap itself.
        result = transition_stage_status(
            stage_id, status, notes=notes,
            force=force, reason=reason, actor=_telegram_username(update),
        )

        log.info(
            "updatestage_cmd result: ok=%s code=%s stage_id=%s roadmap_id=%s "
            "previous_status=%s requested_status=%s final_status=%s changed=%s "
            "partial_success=%s retry_safe=%s roadmap_status_before=%s "
            "roadmap_status_after=%s downstream_failure_count=%s",
            result.get("ok"), result.get("code"), stage_id, result.get("roadmap_id") or "",
            result.get("previous_status"), result.get("requested_status"),
            result.get("final_status"), result.get("changed"),
            result.get("partial_success"), result.get("retry_safe"),
            result.get("roadmap_status_before"), result.get("roadmap_status_after"),
            len(result.get("downstream_failures") or ()),
        )

        if not result["ok"]:
            await _reply(update, _stage_transition_failure_message(result, stage_id, status))
            return

        await _reply(update, "\n".join(_stage_transition_success_lines(result, stage_id, notes)))

    except Exception as e:
        log.error(f"updatestage_cmd error: {e}")
        await _reply(update, "❌ Не удалось обработать команду из-за внутренней ошибки. Попробуй ещё раз позже.")


# ─────────────────────────────────────────────────────────────
# Stage Management Core (Phase 14A)
# ─────────────────────────────────────────────────────────────
#
# Scope decision: только базовое управление этапом — Start Date,
# Priority, Blocking Reason (новые колонки) плюс Responsible/Due Date/
# Completed At/Notes/Checklist IDs (уже существуют, только читаются).
# Checklist Status и Docs Status сознательно НЕ добавлены в этой фазе —
# документы и чек-листы остаются вне scope Phase 14A.
#
# Architecture: как и /editclient/editobject (Phase 13A) — immutable
# confirmation snapshot, перечитывание строки перед записью, точечная
# запись только разрешённых колонок, повторное чтение после записи,
# old->new в ответе, очистка state на любом терминальном исходе.
# Все пять write-команд (assignstage/duedate/priority/blockstage/
# unblockstage) — отдельные ConversationHandler'ы с общей реализацией
# в _stage_edit_start()/_stage_edit_execute(), разные snapshot-ключи.

SE_CONFIRM = 50  # общее состояние подтверждения для всех stage-edit хендлеров

STAGE_PRIORITY_VALUES = ("low", "normal", "high", "urgent")


def _stage_row_display(stage: dict) -> str:
    """stage: canonical dict from roadmap_manager.find_stage_by_id()
    (Closeout Remediation finding #3 — no longer a raw sheet-header-keyed
    row from find_row_by_id)."""
    lines = [
        f"📌 Этап {stage.get('stage_id', '')}",
        "",
        f"Roadmap: {stage.get('roadmap_id', '')}",
        f"Order: {stage.get('order', '')}",
        f"Название: {stage.get('name', '')}",
        f"Статус: {stage.get('status', '')}",
        f"Ответственный: {stage.get('responsible', '') or '—'}",
        f"Start Date: {stage.get('start_date', '') or '—'}",
        f"Due Date: {stage.get('due_date', '') or '—'}",
        f"Completed At: {stage.get('completed_at', '') or '—'}",
        # Пустой Priority отображается как 'normal' по умолчанию — это
        # только отображение, ничего не пишется в Sheets, пока
        # пользователь явно не вызовет /priority.
        f"Приоритет: {stage.get('priority', '') or 'normal'}",
        f"Blocking Reason: {stage.get('blocking_reason', '') or '—'}",
        f"Required Docs: {stage.get('docs_required', '') or '—'}",
        f"Checklist IDs: {stage.get('checklist_ids', '') or '—'}",
        f"Notes: {stage.get('notes', '') or '—'}",
    ]
    return "\n".join(lines)


async def stage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stage stage_id=STAGE-001

    Read-only карточка этапа со всеми полями, включая новые (Phase 14A):
    Priority, Start Date, Blocking Reason. Required Docs/Checklist IDs —
    только отображение уже существующих полей, без новой логики
    управления документами/чек-листами. Ничего не пишет.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")

    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: /stage stage_id=STAGE-001")
        return

    try:
        from business_core.roadmap_manager import find_stage_by_id
        stage = find_stage_by_id(stage_id)
        if not stage:
            await _reply(update, f"❌ Этап {stage_id} не найден.")
            return
        await _reply(update, _stage_row_display(stage))
    except Exception as e:
        log.error(f"stage_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


async def _stage_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *,
    stage_id: str, field_label: str, writes: dict,
    old_value_display: str, new_value_display: str,
    snapshot_key: str,
) -> int:
    """Общий шаг 'построить и показать карточку old->new, снять snapshot'."""
    context.user_data[snapshot_key] = {
        "stage_id": stage_id,
        "field_label": field_label,
        "writes": writes,
        "old_value_display": old_value_display,
        "new_value_display": new_value_display,
    }
    await update.message.reply_text(
        f"📋 Подтверди изменение этапа {stage_id}:\n\n"
        f"Поле: {field_label}\n"
        f"Было: {old_value_display or '—'}\n"
        f"Станет: {new_value_display or '—'}",
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Подтвердить"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )
    return SE_CONFIRM


# Phase 34D (ADR-017 §13/§19): centralized error_code -> Russian message
# mapping for business_builder.update_stage_admin_fields()'s structured
# result (Responsible/Notes/Due Date/Priority/Blocking Reason edits via
# /assignstage, /duedate, /priority). Presentation only.
def _stage_admin_failure_message(result: dict, stage_id: str) -> str:
    code = result.get("code", "")
    roadmap_id = result.get("roadmap_id") or "—"

    if code == "STAGE_NOT_FOUND":
        return f"❌ Этап `{stage_id}` не найден."

    if code == "ROADMAP_NOT_FOUND":
        return (
            f"❌ Не удалось найти Roadmap для этапа `{stage_id}`. "
            f"Это указывает на проблему в данных — требуется проверка."
        )

    if code == "ROADMAP_COMPLETED":
        return "\n".join([
            "✅ Roadmap уже завершён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "Изменение полей этапа заблокировано — Roadmap является завершённым историческим снимком.",
        ])

    if code == "ROADMAP_CANCELLED":
        return "\n".join([
            "🚫 Roadmap отменён",
            f"Этап: `{stage_id}`",
            f"Roadmap: `{roadmap_id}`",
            "Изменение полей этапа заблокировано.",
        ])

    if code == "STAGE_WRITE_PARTIAL_FAILURE":
        return f"❌ Не удалось сохранить изменения этапа `{stage_id}`: {result.get('error') or 'ошибка записи'}"

    if code:
        log.warning("stage_admin_edit: unmapped code=%r for stage_id=%s", code, stage_id)
        return "❌ Не удалось обновить этап из-за ошибки проверки данных. Попробуй ещё раз позже."
    return f"❌ {result.get('error') or 'неизвестная ошибка'}"


async def _stage_edit_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, snapshot_key: str) -> int:
    """
    Общий шаг подтверждения: перечитать строку, точечно записать только
    колонки из snapshot['writes'], перечитать после, ответить old->new.
    Очищает snapshot_key на любом терминальном исходе.
    """
    text = update.message.text.strip()

    if "Отмена" in text:
        context.user_data.pop(snapshot_key, None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    snap = context.user_data.get(snapshot_key)
    if snap is None:
        await update.message.reply_text(
            "❌ Не найдены подтверждённые данные для сохранения. Начни заново.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop(snapshot_key, None)
        return ConversationHandler.END

    try:
        from business_core.business_builder import transition_stage_status, update_stage_admin_fields

        stage_id = snap["stage_id"]
        writes = dict(snap["writes"])

        # Phase 34C (ADR-017): a "Status" key (only /blockstage and
        # /unblockstage's writes ever carry one) must go through the
        # canonical transition-orchestration boundary, never
        # roadmap_manager.update_stage_fields directly — otherwise this
        # shared confirm step would be a second place capable of
        # changing Stage Status with zero Roadmap-eligibility check.
        # Every other admin-only field (Responsible/Due Date/Priority/
        # Blocking Reason alone) goes through update_stage_admin_fields,
        # which enforces the looser admin-field eligibility instead.
        target_status = writes.pop("Status", None)
        if target_status is not None:
            result = transition_stage_status(stage_id, target_status, admin_fields=writes or None)
        else:
            result = update_stage_admin_fields(stage_id, writes)

        log.info(
            "stage_admin_edit result: ok=%s code=%s stage_id=%s roadmap_id=%s "
            "requested_status=%s final_status=%s changed=%s partial_success=%s "
            "retry_safe=%s",
            result.get("ok"), result.get("code"), stage_id, result.get("roadmap_id") or "",
            result.get("requested_status"), result.get("final_status"),
            result.get("changed"), result.get("partial_success"), result.get("retry_safe"),
        )

        if not result["ok"]:
            # blockstage/unblockstage (target_status is not None) share
            # transition_stage_status()'s own centralized failure
            # renderer — never a second, ad-hoc message for the same codes.
            message = (
                _stage_transition_failure_message(result, stage_id, target_status)
                if target_status is not None
                else _stage_admin_failure_message(result, stage_id)
            )
            await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text(
                f"✅ Этап {stage_id} обновлён\n\n"
                f"Поле: {snap['field_label']}\n"
                f"Было: {snap['old_value_display'] or '—'}\n"
                f"Стало: {snap['new_value_display'] or '—'}",
                reply_markup=ReplyKeyboardRemove(),
            )

    except Exception as e:
        log.error(f"stage_edit_confirm({snapshot_key}) error: {e}")
        await update.message.reply_text(
            "❌ Не удалось сохранить изменения из-за внутренней ошибки. Попробуй ещё раз позже.",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop(snapshot_key, None)
    return ConversationHandler.END


async def _stage_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, snapshot_key: str) -> int:
    context.user_data.pop(snapshot_key, None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── /assignstage ────────────────────────────────────────────────

async def assignstage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /assignstage stage_id=STAGE-001 responsible=Иван
    /assignstage stage_id=STAGE-001 responsible=""      — снять назначение
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")
    has_responsible_arg = "responsible" in kv or "_pos1" in kv
    responsible = (kv.get("responsible") if "responsible" in kv else kv.get("_pos1", "")).strip()

    if not stage_id or not has_responsible_arg:
        await update.message.reply_text(
            "❌ Использование:\n"
            "/assignstage stage_id=STAGE-001 responsible=Иван\n\n"
            'Чтобы снять назначение: /assignstage stage_id=STAGE-001 responsible=""'
        )
        return ConversationHandler.END

    from business_core.roadmap_manager import find_stage_by_id
    stage = find_stage_by_id(stage_id)
    if not stage:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Ответственный",
        writes={"Responsible": responsible},
        old_value_display=stage.get("responsible", ""),
        new_value_display=responsible or "не назначен",
        snapshot_key="se_assign",
    )


async def assignstage_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_execute(update, context, "se_assign")


async def assignstage_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_cancel(update, context, "se_assign")


# ── /duedate ─────────────────────────────────────────────────────

async def duedate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /duedate stage_id=STAGE-001 date=2026-08-01
    /duedate stage_id=STAGE-001 date=""            — очистить срок
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")
    has_date_arg = "date" in kv or "_pos1" in kv
    date_val = (kv.get("date") if "date" in kv else kv.get("_pos1", "")).strip()

    if not stage_id or not has_date_arg:
        await update.message.reply_text(
            "❌ Использование:\n"
            "/duedate stage_id=STAGE-001 date=2026-08-01\n\n"
            'Чтобы очистить срок: /duedate stage_id=STAGE-001 date=""'
        )
        return ConversationHandler.END

    import re
    if date_val and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
        await update.message.reply_text("❌ Дата должна быть в формате ГГГГ-ММ-ДД, например 2026-08-01.")
        return ConversationHandler.END

    from business_core.roadmap_manager import find_stage_by_id
    stage = find_stage_by_id(stage_id)
    if not stage:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Due Date",
        writes={"Due Date": date_val},
        old_value_display=stage.get("due_date", ""),
        new_value_display=date_val or "снят",
        snapshot_key="se_duedate",
    )


async def duedate_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_execute(update, context, "se_duedate")


async def duedate_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_cancel(update, context, "se_duedate")


# ── /priority ────────────────────────────────────────────────────

async def priority_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/priority stage_id=STAGE-001 level=high"""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")
    level = (kv.get("level") or kv.get("_pos1", "")).strip().lower()

    if not stage_id or not level:
        await update.message.reply_text(
            "❌ Использование:\n/priority stage_id=STAGE-001 level=high\n\n"
            f"Допустимые значения: {', '.join(STAGE_PRIORITY_VALUES)}"
        )
        return ConversationHandler.END

    if level not in STAGE_PRIORITY_VALUES:
        await update.message.reply_text(
            f"❌ Недопустимый приоритет '{level}'. "
            f"Допустимые значения: {', '.join(STAGE_PRIORITY_VALUES)}"
        )
        return ConversationHandler.END

    from business_core.roadmap_manager import find_stage_by_id
    stage = find_stage_by_id(stage_id)
    if not stage:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Приоритет",
        writes={"Priority": level},
        old_value_display=stage.get("priority", "") or "normal",
        new_value_display=level,
        snapshot_key="se_priority",
    )


async def priority_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_execute(update, context, "se_priority")


async def priority_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_cancel(update, context, "se_priority")


# ── /blockstage / /unblockstage ──────────────────────────────────

async def blockstage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/blockstage stage_id=STAGE-001 reason="Ожидаем документы от клиента" """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")
    reason = (kv.get("reason") or kv.get("_pos1", "")).strip()

    if not stage_id or not reason:
        await update.message.reply_text(
            '❌ Использование:\n/blockstage stage_id=STAGE-001 reason="Причина блокировки"\n\n'
            "Причина обязательна и не может быть пустой."
        )
        return ConversationHandler.END

    from business_core.roadmap_manager import find_stage_by_id
    stage = find_stage_by_id(stage_id)
    if not stage:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END

    writes = {"Blocking Reason": reason, "Status": "blocked"}
    # Запоминаем текущий статус ДО блокировки, чтобы /unblockstage мог
    # вернуть именно его (pending или in_progress), а не всегда pending.
    # Если этап уже blocked (повторный вызов /blockstage — no-op перехода),
    # не перезаписываем уже сохранённый исходный статус.
    if stage.get("status") != "blocked":
        writes["Status Before Block"] = stage.get("status", "")

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Блокировка (Status → blocked)",
        writes=writes,
        old_value_display=stage.get("blocking_reason", ""),
        new_value_display=reason,
        snapshot_key="se_block",
    )


async def blockstage_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_execute(update, context, "se_block")


async def blockstage_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_cancel(update, context, "se_block")


async def unblockstage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/unblockstage stage_id=STAGE-001"""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")

    if not stage_id:
        await update.message.reply_text("❌ Использование:\n/unblockstage stage_id=STAGE-001")
        return ConversationHandler.END

    from business_core.roadmap_manager import find_stage_by_id, STAGE_STATUS_CANONICAL
    stage = find_stage_by_id(stage_id)
    if not stage:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END

    writes = {"Blocking Reason": ""}
    # Возвращаем в статус, который был ДО блокировки (pending или
    # in_progress) — не трогаем Status, если этап уже done/skipped/
    # in_progress по другой причине (т.е. не сейчас blocked).
    if stage.get("raw_status", "") == "blocked":
        restored_status = stage.get("status_before_block", "")
        if restored_status not in STAGE_STATUS_CANONICAL:
            # Старые строки без сохранённого статуса (до этого фикса) —
            # прежнее поведение "всегда pending" как безопасный fallback.
            restored_status = "pending"
        writes["Status"] = restored_status
        writes["Status Before Block"] = ""

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Разблокировка",
        writes=writes,
        old_value_display=stage.get("blocking_reason", "") or "—",
        new_value_display="снято",
        snapshot_key="se_unblock",
    )


async def unblockstage_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_execute(update, context, "se_unblock")


async def unblockstage_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _stage_edit_cancel(update, context, "se_unblock")


# ─────────────────────────────────────────────────────────────
# Document Registry Foundation (Phase 15A)
# ─────────────────────────────────────────────────────────────
#
# Scope: register ONE already-existing Drive file against optional
# Client/Object/Roadmap/Stage/Document Template links. No upload-from-
# Telegram, no review workflow (/approvedoc, /rejectdoc), no versioning
# UX, no bulk operations, no automatic Drive file moves — see
# DOCUMENT_REGISTRY_ARCHITECTURE.md and the Phase 15A review gate for
# what is deliberately deferred to 15B.
#
# Architecture: same immutable-snapshot pattern as /editclient,
# /editobject and the Stage Management commands — single command line
# with all fields, referential validation happens BEFORE any card is
# shown (a validation failure never reaches confirmation), snapshot
# taken once, confirm re-validates nothing further and writes exactly
# one row, re-reads after, replies with the new Document ID.

DOCUMENT_REGISTRY_REQUIRED_ARGS = ("business", "name", "drive")


# ─────────────────────────────────────────────────────────────
# Phase 37E (ADR-020 §22-26): Document Domain — centralized caller UX.
#
# Every Document command below renders orchestration results (business_
# builder.register_document/upload_and_register_document/
# update_document_admin_fields/transition_document_status) through the
# helpers in this section — never inline per-command Russian text for
# a result code, and never a raw exception/result dict to the user.
# Mirrors the Phase 35E Organization / Phase 36D Task UX pattern
# exactly.
# ─────────────────────────────────────────────────────────────

_DOCUMENT_STATUS_RU: dict[str, str] = {
    "uploaded": "Загружен", "under_review": "На проверке", "approved": "Утверждён",
    "rejected": "Отклонён", "superseded": "Заменён", "archived": "В архиве",
}

_DOCUMENT_ANALYSIS_STATUS_RU: dict[str, str] = {
    "pending": "Ожидает анализа", "processing": "Анализируется",
    "completed": "Проанализирован", "unsupported": "Формат не поддерживается",
    "failed": "Ошибка анализа",
}


def _document_status_ru(status: str) -> str:
    """Russian label + raw machine status, always both — never only
    the translation, so debugging never loses the exact stored value."""
    return f"{_DOCUMENT_STATUS_RU.get(status, status)} ({status})"


def _document_analysis_status_ru(status: str) -> str:
    return f"{_DOCUMENT_ANALYSIS_STATUS_RU.get(status, status)} ({status})"


def _document_creation_message(result: dict, *, document_name: str = "", file_name: str = "", drive_file_url: str = "") -> str:
    """
    Render any business_builder.register_document()/
    upload_and_register_document() result into a single Russian
    Telegram message. Shared by /registerdoc's and /uploaddoc's
    confirm steps — the distinct outcomes (created/reused/uploaded/
    every validation, duplicate, and persistence error) are already
    carried in `code` by the orchestrator, never re-derived here.
    Never exposes the raw result dict or a traceback.
    """
    code = result.get("code", "")

    if result.get("ok") and code in ("DOCUMENT_REGISTERED", "DOCUMENT_UPLOADED"):
        verb = "загружен и зарегистрирован" if result.get("uploaded") else "зарегистрирован"
        lines = [
            f"✅ Документ {verb}",
            "",
            f"Document ID: {result.get('document_id', '')}",
            f"Document Family ID: {result.get('document_family_id', '')}",
        ]
        if result.get("version"):
            lines.append(f"Version: {result['version']}")
        if document_name:
            lines.append(f"Название: {document_name}")
        if file_name:
            lines.append(f"Файл: {file_name}")
        if drive_file_url:
            lines.append(f"Drive URL: {drive_file_url}")
        for key, label in (
            ("business_id", "Business ID"), ("client_id", "Client ID"),
            ("object_id", "Object ID"), ("roadmap_id", "Roadmap ID"),
            ("stage_id", "Stage ID"), ("document_template_id", "Document Template ID"),
        ):
            if result.get(key):
                lines.append(f"{label}: {result[key]}")
        lines.append(f"Статус: {_document_status_ru(result.get('final_status', ''))}")
        return "\n".join(lines)

    if code == "DOCUMENT_REUSED":
        return "\n".join([
            "♻️ Документ с этим Drive-файлом уже зарегистрирован — использована существующая запись",
            f"Document ID: {result.get('document_id', '')}",
            f"Document Family ID: {result.get('document_family_id', '')}",
            f"Статус: {_document_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "DOCUMENT_ENTITY_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "MULTIPLE_DOCUMENT_DRIVE_FILE_MATCHES":
        ids = ", ".join(result.get("conflicting_document_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Document с одним Drive File ID: {ids}",
            "Новый Document не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "DOCUMENT_RELATION_CONFLICT_ON_REUSE":
        return (
            "❌ Документ с этим Drive File ID уже существует с другими связями.\n"
            f"Document ID: {result.get('document_id', '')}"
        )

    if code == "DOCUMENT_POST_WRITE_VERIFICATION_FAILED":
        lines = [
            "⚠️ Документ записан, но пост-проверка записи не прошла.",
            "Требуется ручная проверка.",
        ]
        if result.get("document_id"):
            lines.append(f"Document ID: {result['document_id']}")
        if result.get("drive_file_id"):
            lines.append(f"Drive File ID: {result['drive_file_id']}")
        return "\n".join(lines)

    if code == "DOCUMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось сохранить документ."

    if code == "DRIVE_UPLOAD_FAILED":
        return "❌ Не удалось загрузить файл в Google Drive."

    if code == "DOCUMENT_FILE_METADATA_INVALID":
        lines = [
            "❌ Не удалось получить полные метаданные файла из Google Drive после загрузки — регистрация не выполнена.",
        ]
        if result.get("compensation_attempted"):
            if result.get("compensation_succeeded"):
                lines.append("Загруженный файл в Google Drive перемещён в корзину (компенсация выполнена).")
            else:
                lines.append("⚠️ Очистка Drive-файла НЕ удалась — требуется ручная очистка.")
                if result.get("drive_file_id"):
                    lines.append(f"Orphan Drive File ID: {result['drive_file_id']}")
        return "\n".join(lines)

    if code == "DRIVE_UPLOAD_COMPENSATED":
        return (
            "❌ Не удалось сохранить запись документа.\n"
            "Загруженный файл в Google Drive перемещён в корзину (компенсация выполнена) — запись не создана."
        )

    if code == "DOCUMENT_PERSISTENCE_FAILED_WITH_ORPHANED_FILE_WARNING":
        lines = [
            "❌ Не удалось сохранить запись документа.",
            "⚠️ Очистка Drive-файла НЕ удалась — требуется ручная очистка.",
        ]
        if result.get("drive_file_id"):
            lines.append(f"Orphan Drive File ID: {result['drive_file_id']}")
        return "\n".join(lines)

    if code == "INVALID_DOCUMENT_FILENAME":
        return f"❌ Недопустимое имя файла: {result.get('error') or ''}"

    if code == "DOCUMENT_TOO_LARGE":
        return f"❌ Недопустимый размер файла: {result.get('error') or ''}"

    if code == "UNSUPPORTED_DOCUMENT_STORAGE_TYPE":
        return "❌ Этот тип файла не поддерживается для хранения."

    if code == "DOCUMENT_ANALYSIS_UNSUPPORTED":
        return "⚠️ Файл принят, но автоматический анализ для этого формата не поддерживается."

    if code == "DOCUMENT_UPLOAD_VALIDATED":
        return "✅ Файл прошёл проверку."

    log.warning(f"_document_creation_message: unmapped code={code!r} business_id={result.get('business_id', '')}")
    return "❌ Не удалось сохранить документ."


def _document_admin_message(result: dict, document_id: str) -> str:
    """Render any business_builder.update_document_admin_fields() result."""
    code = result.get("code", "")

    if code == "DOCUMENT_ADMIN_FIELDS_UPDATED":
        return f"✅ Document {document_id} обновлён."

    if code == "DOCUMENT_ADMIN_FIELDS_UNCHANGED":
        return f"ℹ️ Document {document_id} — изменений нет (значения совпадают)."

    if code == "DOCUMENT_NOT_FOUND":
        return f"❌ Document {document_id} не найден."

    if code == "DOCUMENT_IMMUTABLE_FIELD_CONFLICT":
        return f"❌ Указанные поля являются неизменяемой идентичностью Document: {result.get('error') or ''}"

    if code == "DOCUMENT_VERSION_FIELD_IMMUTABLE":
        return "❌ Version неизменяем после создания."

    if code == "DOCUMENT_FAMILY_FIELD_IMMUTABLE":
        return "❌ Document Family ID неизменяем после создания."

    if code == "DOCUMENT_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION":
        return "❌ Изменение связей (Client/Object/Roadmap/Stage/Template ID) через /updatedoc не поддерживается."

    if code == "INVALID_DOCUMENT_ADMIN_FIELD":
        return f"❌ Недопустимое поле для /updatedoc: {result.get('error') or ''}"

    log.warning(f"_document_admin_message: unmapped code={code!r} document_id={document_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _document_transition_message(result: dict, document_id: str) -> str:
    """Render any business_builder.transition_document_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    if code == "DOCUMENT_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус Document изменён",
            f"Document ID: {document_id}",
            f"Был: {_document_status_ru(previous_status)}",
            f"Стал: {_document_status_ru(result.get('final_status', ''))}",
        ])

    if code == "DOCUMENT_STATUS_UNCHANGED":
        return f"ℹ️ Document {document_id} уже имеет статус {_document_status_ru(previous_status)} — изменений нет."

    if code == "DOCUMENT_NOT_FOUND":
        return f"❌ Document {document_id} не найден."

    if code == "INVALID_DOCUMENT_STATUS":
        from business_core.document_manager import DOCUMENT_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: {', '.join(DOCUMENT_STATUS)}"

    if code == "INVALID_DOCUMENT_TRANSITION":
        return f"❌ Переход {_document_status_ru(previous_status)} → {_document_status_ru(requested_status)} не разрешён."

    if code == "DOCUMENT_RESTORE_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Document имеет терминальный статус",
            f"Document ID: {document_id}",
            f"Текущий статус: {_document_status_ru(previous_status)}",
            "Такой Document нельзя вернуть в обычный оборот обычной командой изменения статуса. "
            "Отдельное явное действие restore пока не реализовано.",
        ])

    log.warning(f"_document_transition_message: unmapped code={code!r} document_id={document_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _document_relink_message(result: dict, document_id: str) -> str:
    """Render any business_builder.relink_document() result (both the
    dry_run preview and the applied outcome share this mapping, except
    for the dedicated DOCUMENT_RELINK_PREVIEW case handled by
    _document_relink_preview_message() before falling back here)."""
    code = result.get("code", "")

    if code == "DOCUMENT_RELATION_UPDATED":
        return "\n".join([
            "✅ Связи Document обновлены",
            f"Document ID: {document_id}",
            f"Roadmap ID: {result.get('roadmap_id', '') or '—'}",
            f"Stage ID: {result.get('stage_id', '') or '—'}",
            f"Document Template ID: {result.get('document_template_id', '') or '—'}",
            "Drive File ID, Drive URL, Document ID, Business/Client/Object ID, "
            "Family ID и Version не изменились.",
        ])

    if code == "DOCUMENT_RELATION_UNCHANGED":
        return f"ℹ️ Document {document_id} — новые значения совпадают с текущими, изменений нет."

    if code == "DOCUMENT_NOT_FOUND":
        return f"❌ Document {document_id} не найден."

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ {result.get('error') or 'Business не найден.'}"

    if code == "DOCUMENT_ENTITY_RELATION_MISMATCH":
        return f"❌ {result.get('error') or 'Указанные связи несовместимы.'}"

    log.warning(f"_document_relink_message: unmapped code={code!r} document_id={document_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _document_relink_preview_message(
    result: dict, document_id: str, old_roadmap_id: str, old_stage_id: str, old_document_template_id: str = "",
) -> str:
    """Render the dry_run preview step of /updatedoc's relink mode —
    shows old->new Roadmap/Stage/Document Template ID and explicitly
    confirms Drive File ID/URL/Document ID/Business/Client/Object ID/
    Family ID/Version will not change. Any validation failure
    (incompatible/missing Stage, unknown Document Template, etc.) falls
    through to the same mapping the applied outcome uses, so a bad
    request never silently looks like a valid preview."""
    if result.get("code") == "DOCUMENT_RELINK_PREVIEW":
        return "\n".join([
            "📋 Подтверди перепривязку Document:",
            "",
            f"Document ID: {document_id}",
            f"Roadmap ID — было: {old_roadmap_id or '—'} → станет: {result.get('roadmap_id', '') or '—'}",
            f"Stage ID — было: {old_stage_id or '—'} → станет: {result.get('stage_id', '') or '—'}",
            f"Document Template ID — было: {old_document_template_id or '—'} → станет: "
            f"{result.get('document_template_id', '') or '—'}",
            "",
            "Drive File ID, Drive URL, Document ID, Business/Client/Object ID, "
            "Family ID и Version не изменятся.",
            "",
            "Чтобы применить, повтори команду с confirm=yes.",
        ])
    return _document_relink_message(result, document_id)


async def registerdoc_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    /registerdoc business=BIZ-001 name="Технический паспорт" drive=<file_id_or_url>
                  [client=PRS-001] [object=OBJ-001] [roadmap=RM-001] [stage=STAGE-001]
                  [template=DOC-001] [notes="..."]
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)

    business_id = kv.get("business", "").strip()
    name = kv.get("name", "").strip()
    drive_input = kv.get("drive", "").strip()
    client_id = kv.get("client", "").strip()
    object_id = kv.get("object", "").strip()
    roadmap_id = kv.get("roadmap", "").strip()
    stage_id = kv.get("stage", "").strip()
    template_id = kv.get("template", "").strip()
    notes = kv.get("notes", "").strip()

    missing = [a for a in DOCUMENT_REGISTRY_REQUIRED_ARGS if not kv.get(a, "").strip()]
    if missing:
        await update.message.reply_text(
            "❌ Использование:\n"
            '/registerdoc business=BIZ-001 name="Технический паспорт" drive=<file_id_или_URL>\n\n'
            "Опционально: client=, object=, roadmap=, stage=, template=, notes=\n\n"
            f"Отсутствуют обязательные поля: {', '.join(missing)}"
        )
        return ConversationHandler.END

    try:
        from business_core.document_registry_manager import resolve_and_validate_links

        validation = resolve_and_validate_links(
            business_id=business_id, client_id=client_id, object_id=object_id,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=template_id,
        )
        if not validation["ok"]:
            await update.message.reply_text(f"❌ {validation['error']}")
            return ConversationHandler.END

        from integrations.google_drive_adapter import (
            get_drive_service, get_file_id_from_input, get_file_metadata,
        )

        file_id = get_file_id_from_input(drive_input)
        service = get_drive_service()
        meta = get_file_metadata(service, file_id)
        if not meta["ok"]:
            await update.message.reply_text(
                f"❌ Не удалось прочитать Drive-файл {file_id}: {meta['error']}"
            )
            return ConversationHandler.END
        if meta.get("trashed"):
            await update.message.reply_text(f"❌ Файл {file_id} находится в Trash — регистрация невозможна.")
            return ConversationHandler.END

    except Exception as e:
        log.error(f"registerdoc_start error: {e}")
        await update.message.reply_text("❌ Не удалось начать регистрацию документа.")
        return ConversationHandler.END

    resolved = validation["resolved"]
    snapshot = {
        "business_id": resolved["business_id"],
        "client_id": resolved["client_id"],
        "object_id": resolved["object_id"],
        "roadmap_id": resolved["roadmap_id"],
        "stage_id": resolved["stage_id"],
        "document_template_id": resolved["document_template_id"],
        "document_name": name,
        "drive_file_id": file_id,
        "file_name": meta["name"],
        "mime_type": meta["mime_type"],
        # Phase 15A safety refinement: store the Drive API's own
        # webViewLink verbatim — never construct a URL manually. Empty
        # if Drive didn't return one; that alone never blocks registration.
        "web_view_link": meta.get("web_view_link", ""),
        "notes": notes,
    }
    context.user_data["regdoc_confirmed_snapshot"] = snapshot

    # Phase 15A safety refinement: show the FINAL NORMALIZED links (all
    # six, "—" when empty) — not just what the user typed — so the
    # confirmation is over exactly what will be written, including any
    # auto-derived values (e.g. stage= alone deriving roadmap/object/client).
    lines = [
        "📋 Подтверди регистрацию документа:",
        "",
        f"Название: {name}",
        f"Business ID: {resolved['business_id'] or '—'}",
        f"Client ID: {resolved['client_id'] or '—'}",
        f"Object ID: {resolved['object_id'] or '—'}",
        f"Roadmap ID: {resolved['roadmap_id'] or '—'}",
        f"Stage ID: {resolved['stage_id'] or '—'}",
        f"Document Template ID: {resolved['document_template_id'] or '—'}",
        f"Файл: {meta['name']} ({meta['mime_type']})",
    ]
    if notes:
        lines.append(f"Notes: {notes}")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Подтвердить"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )
    return RD_CONFIRM


async def registerdoc_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        context.user_data.pop("regdoc_confirmed_snapshot", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    snap = context.user_data.get("regdoc_confirmed_snapshot")
    if snap is None:
        # Либо ничего не было начато, либо это повторное нажатие
        # "✅ Подтвердить" после того, как первое уже создало строку и
        # очистило snapshot — не создаём вторую строку молча.
        await update.message.reply_text(
            "❌ Нет подтверждённых данных для регистрации (возможно, уже зарегистрировано). "
            "Начни заново: /registerdoc",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    try:
        # Phase 37D (ADR-020 §10/§19): register_document() is now the
        # sole canonical creation path — this handler no longer
        # generates IDs or appends the final row itself.
        from business_core.business_builder import register_document

        result = register_document(
            snap["business_id"], snap["document_name"], snap["drive_file_id"],
            file_name=snap["file_name"], mime_type=snap["mime_type"],
            drive_file_url=snap.get("web_view_link", ""),
            client_id=snap["client_id"], object_id=snap["object_id"],
            roadmap_id=snap["roadmap_id"], stage_id=snap["stage_id"],
            document_template_id=snap["document_template_id"],
            uploaded_by=_telegram_username(update), notes=snap["notes"],
        )

        if not result["ok"]:
            log.error(f"registerdoc_confirm: code={result['code']} error={result['error']}")
        await update.message.reply_text(
            _document_creation_message(result, document_name=snap["document_name"], file_name=snap["file_name"]),
            reply_markup=ReplyKeyboardRemove(),
        )

    except Exception as e:
        log.error(f"registerdoc_confirm error: {e}")
        await update.message.reply_text("❌ Ошибка сохранения документа.", reply_markup=ReplyKeyboardRemove())

    context.user_data.pop("regdoc_confirmed_snapshot", None)
    return ConversationHandler.END


async def registerdoc_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("regdoc_confirmed_snapshot", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def _now_utc_str() -> str:
    """Phase 15A: единый UTC timestamp текущей операции — вызывается
    ОДИН раз в registerdoc_confirm() и переиспользуется для Uploaded At/
    Created At/Updated At, а не пересчитывается отдельно для каждого поля."""
    from datetime import timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _telegram_username(update: Update) -> str:
    user = getattr(update, "effective_user", None)
    if user is None:
        return ""
    return getattr(user, "username", "") or str(getattr(user, "id", ""))


async def doc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/doc document_id=DREG-001 — read-only полная карточка документа."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    document_id = kv.get("document_id") or kv.get("_pos0", "")

    if not document_id:
        await _reply(update, "❌ Укажи document_id.\n\nПример: /doc document_id=DREG-001")
        return

    try:
        # Phase 37E (ADR-020 §7/§19): exact-ID lookup only, through the
        # sole document_registry read owner — never a raw Sheets read,
        # never fuzzy matching.
        from business_core.document_manager import find_document_by_id
        doc = find_document_by_id(document_id)
        if doc is None:
            await _reply(update, f"❌ Документ {document_id} не найден.")
            return
        lines = [
            f"📄 Документ {doc.get('document_id', '')}",
            "",
            f"Family: {doc.get('document_family_id', '')} (v{doc.get('version', '')})",
            f"Название: {doc.get('document_name', '')}",
            f"Статус: {_document_status_ru(doc.get('status', ''))}",
            f"Business: {doc.get('business_id', '') or '—'}",
            f"Client: {doc.get('client_id', '') or '—'}",
            f"Object: {doc.get('object_id', '') or '—'}",
            f"Roadmap: {doc.get('roadmap_id', '') or '—'}",
            f"Stage: {doc.get('stage_id', '') or '—'}",
            f"Document Template: {doc.get('document_template_id', '') or '—'}",
            f"Файл: {doc.get('file_name', '')} ({doc.get('mime_type', '')})",
            f"Drive: {'есть' if doc.get('drive_file_id') else '—'}",
            f"Загружен: {doc.get('uploaded_at', '')} ({doc.get('uploaded_by', '')})",
        ]
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"doc_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить документ.")


async def docs4stage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /docs4stage stage_id=STAGE-001 — read-only: требования из шаблона
    (Document Template IDs), зарегистрированные документы, вычисляемые
    missing requirements. Без keyword-угадывания — если у этапа нет ни
    одного Document Template ID, явно показывает "не сопоставлено".
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    stage_id = kv.get("stage_id") or kv.get("_pos0", "")

    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: /docs4stage stage_id=STAGE-001")
        return

    try:
        from business_core.document_registry_manager import (
            compute_stage_document_status, get_documents_for_stage,
        )

        status = compute_stage_document_status(stage_id)
        documents = get_documents_for_stage(stage_id)

        lines = [f"📄 Документы этапа {stage_id}", ""]

        if not status["matchable"]:
            lines.append("⚠️ Требования не сопоставлены — у этапа нет Document Template ID.")
            lines.append("(намеренно не угадываем по ключевым словам)")
        else:
            lines.append(f"Требуется шаблонов: {len(status['template_ids_required'])}")
            lines.append(f"Закрыто: {len(status['matched'])}")
            if status["missing"]:
                lines.append(f"Отсутствует: {', '.join(status['missing'])}")
            else:
                lines.append("Отсутствующих требований нет.")

        lines.append("")
        lines.append(f"Зарегистрировано документов: {len(documents)}")
        for d in documents:
            lines.append(f"  {d.get('Document ID')} — {d.get('Document Name')} ({d.get('Status')})")

        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"docs4stage_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить требования этапа.")


async def updatedoc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatedoc document_id=DREG-001 name="..." notes="..."
    /updatedoc document_id=DREG-001 status=under_review
    /updatedoc document_id=DREG-001 stage_id=STAGE-014
    /updatedoc document_id=DREG-001 roadmap_id=RM-... stage_id=STAGE-... confirm=yes
    /updatedoc document_id=DREG-001 document_template_id=DOC-012 confirm=yes

    Phase 37E (ADR-020 §14/§15/§20): status and admin fields are never
    mixed in one call — mirrors /updatetask's Phase 36D foundation UX
    exactly, so admin-field policy and transition policy never share a
    single ambiguous write. No review fields, no Drive-field repair, no
    restore.

    Relink mode (roadmap_id/stage_id/document_template_id only —
    narrow, audit-approved scope): the first call (no confirm=yes) only
    validates and shows a before/after preview via business_builder.
    relink_document(..., dry_run=True) — nothing is written. Repeating
    the exact same call with confirm=yes re-validates (staleness guard)
    and applies it. Business ID/Client ID/Object ID can never be
    changed this way — passing any of them is an explicit, visible
    rejection, never a silent no-op. Document Template ID is a pure
    classification field (no Drive-path implication like Object ID
    has), so — unlike those three — it IS relinkable.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    document_id = args.get("document_id", "")

    if not document_id:
        await _reply(
            update,
            "❌ Укажи document_id.\n\nПример:\n"
            '`/updatedoc document_id=DREG-001 name="..." notes="..."`\n'
            "`/updatedoc document_id=DREG-001 status=under_review`\n"
            "`/updatedoc document_id=DREG-001 stage_id=STAGE-014`",
        )
        return

    forbidden_relink_keys = ("business_id", "client_id", "object_id")
    forbidden_present = [k for k in forbidden_relink_keys if k in args]
    if forbidden_present:
        forbidden_list = ", ".join(f"`{k}`" for k in forbidden_present)
        await _reply(
            update,
            f"❌ Изменение полей {forbidden_list} через /updatedoc не поддерживается.\n"
            "Через relink можно менять только `roadmap_id`, `stage_id` и `document_template_id`.",
        )
        return

    admin_keys = {"name", "notes"}
    relink_keys = {"roadmap_id", "stage_id", "document_template_id"}
    has_status = "status" in args
    has_admin = any(k in args for k in admin_keys)
    has_relink = any(k in args for k in relink_keys)

    modes_selected = sum((has_status, has_admin, has_relink))
    if modes_selected > 1:
        await _reply(
            update,
            "❌ Нельзя одновременно менять статус, admin-поля и связи "
            "(`roadmap_id`/`stage_id`/`document_template_id`).\n"
            "Отправь отдельные команды:\n"
            "`/updatedoc document_id=... status=...`\n"
            '`/updatedoc document_id=... name="..." notes="..."`\n'
            "`/updatedoc document_id=... stage_id=...`",
        )
        return

    if modes_selected == 0:
        await _reply(
            update,
            "❌ Укажи либо status=..., либо admin-поля (name/notes), либо "
            "`roadmap_id`/`stage_id`/`document_template_id` для перепривязки.",
        )
        return

    try:
        if has_status:
            from business_core.business_builder import transition_document_status
            result = transition_document_status(document_id, args["status"])
            await _reply(update, _document_transition_message(result, document_id))
            return

        if has_relink:
            from business_core.document_manager import find_document_by_id
            from business_core.business_builder import relink_document

            document = find_document_by_id(document_id)
            if document is None:
                await _reply(update, f"❌ Document {document_id} не найден.")
                return

            new_roadmap_id = args.get("roadmap_id")
            new_stage_id = args.get("stage_id")
            new_document_template_id = args.get("document_template_id")
            confirmed = args.get("confirm", "").strip().lower() == "yes"

            result = relink_document(
                document_id, roadmap_id=new_roadmap_id, stage_id=new_stage_id,
                document_template_id=new_document_template_id, dry_run=not confirmed,
            )
            if confirmed:
                await _reply(update, _document_relink_message(result, document_id))
            else:
                await _reply(
                    update,
                    _document_relink_preview_message(
                        result, document_id, document.get("roadmap_id", ""), document.get("stage_id", ""),
                        document.get("document_template_id", ""),
                    ),
                )
            return

        from business_core.business_builder import update_document_admin_fields

        field_key_map = {"name": "Document Name", "notes": "Notes"}
        updates = {field_key_map[k]: v for k, v in args.items() if k in admin_keys}
        result = update_document_admin_fields(document_id, updates)
        await _reply(update, _document_admin_message(result, document_id))
    except Exception as e:
        log.error(f"updatedoc_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить документ.")


_STAGE_KNOWLEDGE_SOURCE_RU = {
    "relations": "STAGE_ENTITY_RELATIONS (активные relations на Template Stage)",
    "legacy": "legacy-поле ROADMAP_TEMPLATE_STAGES.\"Document Template IDs\" (то же, что пишет /linkknowledge)",
    "": "—",
}


def _stage_knowledge_sync_message(result: dict) -> str:
    """Render any business_builder.sync_stage_document_requirements()
    result (both the dry_run preview and the applied outcome share this
    mapping, except for the dedicated preview case handled by
    _stage_knowledge_sync_preview_message() before falling back here)."""
    code = result.get("code", "")
    stage_id = result.get("stage_id", "")
    template_stage_id = result.get("template_stage_id", "")

    if code == "STAGE_KNOWLEDGE_SYNCED":
        created = result.get("created", ())
        already_present = result.get("already_present", ())
        source = result.get("source", "")
        lines = [
            "✅ Синхронизация выполнена",
            f"Stage ID: {stage_id}",
            f"Template Stage ID: {template_stage_id}",
            f"Источник: {_STAGE_KNOWLEDGE_SOURCE_RU.get(source, source)}",
        ]
        if created:
            lines.append(f"Добавлено: {', '.join(created)}")
        else:
            lines.append("Добавлено: ничего (уже было синхронизировано).")
        if already_present:
            lines.append(f"Уже было: {', '.join(already_present)}")
        lines.append(
            "Статус, ответственный, сроки, приоритет и прогресс этапа не изменились. "
            "ROADMAP_STAGES не изменялся."
        )
        return "\n".join(lines)

    if code == "STAGE_NOT_FOUND":
        return f"❌ Stage {stage_id} не найден."

    if code == "ROADMAP_NOT_FOUND":
        return f"❌ {result.get('error') or 'Roadmap не найден.'}"

    if code == "ROADMAP_HAS_NO_TEMPLATE":
        return f"❌ {result.get('error') or 'У Roadmap не определён Template ID.'}"

    if code == "TEMPLATE_STAGE_NOT_FOUND":
        return f"❌ {result.get('error') or 'Template Stage не найден.'}"

    if code == "NO_DOCUMENT_TEMPLATE_RELATIONS":
        return (
            f"❌ {result.get('error') or 'У Template Stage нет document_template relations, ни legacy-значений.'}"
        )

    if code == "UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE":
        return f"❌ {result.get('error') or 'Template Stage содержит relations вне поддерживаемого типа.'}"

    if code == "INVALID_LEGACY_DOCUMENT_TEMPLATE_ID":
        return f"❌ {result.get('error') or 'В legacy-поле Template Stage есть несуществующий Document Template ID.'}"

    if code == "STAGE_KNOWLEDGE_SYNC_FAILED":
        return f"❌ {result.get('error') or 'Не удалось синхронизировать.'}"

    log.warning(f"_stage_knowledge_sync_message: unmapped code={code!r} stage_id={stage_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _stage_knowledge_sync_preview_message(result: dict) -> str:
    """Render the dry_run preview step of /syncstageknowledge — shows
    Stage ID, Template Stage ID, WHICH SOURCE was used (active
    STAGE_ENTITY_RELATIONS vs. the legacy ROADMAP_TEMPLATE_STAGES.
    "Document Template IDs" column /linkknowledge writes), which
    Document Template IDs would be added vs. are already present, and
    explicitly confirms Status/Responsible/Due Date/Priority/Progress
    will not change. Any resolution/validation failure falls through to
    the same mapping the applied outcome uses, so a bad request never
    silently looks like a valid preview."""
    if result.get("code") == "STAGE_KNOWLEDGE_SYNC_PREVIEW":
        to_add = result.get("to_add", ())
        already_present = result.get("already_present", ())
        source = result.get("source", "")
        lines = [
            "📋 Подтверди синхронизацию document-template knowledge:",
            "",
            f"Stage ID: {result.get('stage_id', '')}",
            f"Template Stage ID: {result.get('template_stage_id', '')}",
            f"Источник: {_STAGE_KNOWLEDGE_SOURCE_RU.get(source, source)}",
            "",
        ]
        if to_add:
            lines.append(f"Будет добавлено: {', '.join(to_add)}")
        else:
            lines.append("Будет добавлено: ничего — уже полностью синхронизировано.")
        if already_present:
            lines.append(f"Уже привязано: {', '.join(already_present)}")
        lines.append("")
        lines.append(
            "Статус, ответственный, сроки, приоритет и прогресс этапа не изменятся. "
            "ROADMAP_STAGES меняться не будет."
        )
        lines.append("")
        lines.append("Чтобы применить, повтори команду с confirm=yes.")
        return "\n".join(lines)
    return _stage_knowledge_sync_message(result)


_STAGE_SOP_SOURCE_RU = {
    "relations": "STAGE_ENTITY_RELATIONS (активные sop relations на Template Stage)",
    "legacy": "legacy-поле ROADMAP_TEMPLATE_STAGES.\"SOP IDs\" (то же, что пишет /linkknowledge)",
    "": "—",
}


def _stage_sop_sync_message(result: dict) -> str:
    """SOP counterpart of _stage_knowledge_sync_message() — same shape,
    applied to business_builder.sync_stage_sop_knowledge()'s result.
    Shared resolution-failure codes (STAGE_NOT_FOUND/ROADMAP_NOT_FOUND/
    ROADMAP_HAS_NO_TEMPLATE/TEMPLATE_STAGE_NOT_FOUND/
    UNSUPPORTED_RELATION_TYPE_ON_TEMPLATE_STAGE) are identical messages
    to the document version since resolve_template_stage_for_stage() is
    the same shared read for both — delegated to that renderer to avoid
    duplicating the same five branches twice."""
    code = result.get("code", "")
    stage_id = result.get("stage_id", "")
    template_stage_id = result.get("template_stage_id", "")

    if code == "STAGE_SOP_SYNCED":
        created = result.get("created", ())
        already_present = result.get("already_present", ())
        source = result.get("source", "")
        lines = [
            "✅ Синхронизация SOP выполнена",
            f"Stage ID: {stage_id}",
            f"Template Stage ID: {template_stage_id}",
            f"Источник: {_STAGE_SOP_SOURCE_RU.get(source, source)}",
        ]
        if created:
            lines.append(f"Добавлено: {', '.join(created)}")
        else:
            lines.append("Добавлено: ничего (уже было синхронизировано).")
        if already_present:
            lines.append(f"Уже было: {', '.join(already_present)}")
        lines.append(
            "Статус, ответственный, сроки, приоритет и прогресс этапа не изменились. "
            "ROADMAP_STAGES не изменялся. SOP не участвует в Stage Completion Gate."
        )
        return "\n".join(lines)

    if code == "NO_SOP_KNOWLEDGE":
        return f"❌ {result.get('error') or 'У Template Stage нет sop relations, ни legacy-значений.'}"

    if code == "INVALID_LEGACY_SOP_ID":
        return f"❌ {result.get('error') or 'В legacy-поле Template Stage есть несуществующий SOP ID.'}"

    if code == "STAGE_SOP_SYNC_FAILED":
        return f"❌ {result.get('error') or 'Не удалось синхронизировать SOP.'}"

    # Shared resolution-failure codes — same rendering as the document sync.
    return _stage_knowledge_sync_message(result)


def _stage_sop_sync_preview_message(result: dict) -> str:
    """SOP counterpart of _stage_knowledge_sync_preview_message()."""
    if result.get("code") == "STAGE_SOP_SYNC_PREVIEW":
        to_add = result.get("to_add", ())
        already_present = result.get("already_present", ())
        source = result.get("source", "")
        lines = [
            "📋 Подтверди синхронизацию SOP:",
            "",
            f"Stage ID: {result.get('stage_id', '')}",
            f"Template Stage ID: {result.get('template_stage_id', '')}",
            f"Источник: {_STAGE_SOP_SOURCE_RU.get(source, source)}",
            "",
        ]
        if to_add:
            lines.append(f"Будет добавлено: {', '.join(to_add)}")
        else:
            lines.append("Будет добавлено: ничего — уже полностью синхронизировано.")
        if already_present:
            lines.append(f"Уже привязано: {', '.join(already_present)}")
        lines.append("")
        lines.append(
            "Статус, ответственный, сроки, приоритет и прогресс этапа не изменятся. "
            "ROADMAP_STAGES меняться не будет. SOP не участвует в Stage Completion Gate."
        )
        lines.append("")
        lines.append("Чтобы применить, повтори команду с confirm=yes.")
        return "\n".join(lines)
    return _stage_sop_sync_message(result)


async def syncstageknowledge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /syncstageknowledge stage_id=STAGE-014
    /syncstageknowledge stage_id=STAGE-014 confirm=yes

    Retroactively syncs BOTH document_template requirements AND SOP
    knowledge from the Template Stage a Stage was created from, into
    that already-existing Stage — for the case where /linkknowledge
    added a document_template or sop relation to the Template Stage
    AFTER the real Stage had already been instantiated, so the one-time
    creation-time copy never saw it.

    Calls business_builder.sync_stage_document_requirements() and
    business_builder.sync_stage_sop_knowledge() independently (two
    small functions, each scoped to one Entity Type — neither grows
    into a multi-entity-type monolith, the same principle already
    applied to the two Stage Completion Gate evaluators) and combines
    both into one reply. SOP has no Required/Blocking semantics and is
    never part of any Stage Completion Gate — syncing it here is purely
    about making /sop stage_id=... able to discover it.

    Checklist/Materials/FAQ IDs and the legacy ROADMAP_STAGES columns
    are never touched by either function. Same preview/confirm shape as
    /updatedoc's relink mode: the first call (no confirm=yes) only
    resolves and previews via dry_run=True for both — nothing is
    written. Repeating the exact same call with confirm=yes re-validates
    (staleness guard) and applies both.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id") or args.get("_pos0", "")

    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: `/syncstageknowledge stage_id=STAGE-014`")
        return

    confirmed = args.get("confirm", "").strip().lower() == "yes"

    try:
        from business_core.business_builder import sync_stage_document_requirements, sync_stage_sop_knowledge

        doc_result = sync_stage_document_requirements(stage_id, dry_run=not confirmed)
        sop_result = sync_stage_sop_knowledge(stage_id, dry_run=not confirmed)

        if confirmed:
            doc_text = _stage_knowledge_sync_message(doc_result)
            sop_text = _stage_sop_sync_message(sop_result)
        else:
            doc_text = _stage_knowledge_sync_preview_message(doc_result)
            sop_text = _stage_sop_sync_preview_message(sop_result)

        combined = (
            f"📚 Синхронизация knowledge этапа {stage_id}\n\n"
            f"── Документы ──\n{doc_text}\n\n"
            f"── SOP ──\n{sop_text}"
        )
        await _reply(update, combined)
    except Exception as e:
        log.error(f"syncstageknowledge_cmd error: {e}")
        await _reply(update, "❌ Не удалось синхронизировать knowledge этапа.")


# ─────────────────────────────────────────────────────────────
# Telegram Document Upload Foundation (Phase 15B)
# ─────────────────────────────────────────────────────────────
#
# Scope: upload exactly ONE Telegram document to an existing Drive
# folder and register exactly one DOCUMENT_REGISTRY row (Version=1,
# Status=uploaded). No /approvedoc, /rejectdoc, /docversions, OCR,
# bulk upload, keyword-based document-type guessing, or new Drive
# folder architecture — see the Phase 15B review gate for the full
# exclusion list.
#
# Flow (three states, same immutable-snapshot architecture as
# /registerdoc, /editclient, /editobject):
#   UD_FILE    — waiting for the Telegram document itself. Any other
#                media type (photo/voice/video/audio/text/album) is
#                rejected with a clear message, conversation stays in
#                UD_FILE so the user can retry without restarting.
#   UD_DETAILS — waiting for one command-style line with business=,
#                name= (required) and optional client=/object=/
#                roadmap=/stage=/template=/notes=, reusing the exact
#                same _parse_kv_args()/resolve_and_validate_links()
#                pattern as /registerdoc. Once links resolve, the
#                target Drive folder is picked (Object -> Client ->
#                Business, most-specific-first; Stage folder is never
#                attempted — ROADMAP_STAGES has no Drive Folder ID
#                column). If no folder is found, the operation stops
#                here — nothing is downloaded, nothing is uploaded.
#                A confirmation snapshot is taken at this point.
#   UD_CONFIRM — on "✅ Подтвердить": re-validates the resolved links
#                (staleness guard), downloads the Telegram file body
#                for the FIRST time, uploads it to the resolved folder,
#                reads back authoritative Drive metadata, generates
#                DREG/DFAM ids from one sheet read, writes exactly one
#                row. If the registry write fails after a successful
#                Drive upload, the uploaded file is trashed as
#                compensation (never left behind silently, never
#                retried automatically, never a partially-written row).
#
# Idempotency: the snapshot carries an "op_state" (pending -> processing)
# set synchronously (no `await` in between check and set) at the very
# top of uploaddoc_confirm(), before any Telegram/Drive/Sheets I/O. A
# duplicate tap on "✅ Подтвердить" arriving while the first tap's I/O
# is still in flight sees op_state == "processing" and gets a safe
# no-op reply — it never re-downloads, re-uploads, or re-registers.

UPLOADDOC_REQUIRED_ARGS = ("business", "name")


async def uploaddoc_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/uploaddoc — начать загрузку одного документа."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    context.user_data.pop("ud", None)
    context.user_data.pop("ud_confirmed_snapshot", None)

    await update.message.reply_text(
        "📎 Отправь один документ (Telegram document — файл, не фото и не голосовое).\n\n"
        "/cancel — отменить."
    )
    return UD_FILE


async def uploaddoc_receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    doc = message.document if message else None

    if doc is None:
        await update.message.reply_text(
            "⚠️ Поддерживается только один Telegram document (файл).\n"
            "Фото, голосовые, видео, аудио и текст без файла не подходят.\n\n"
            "Отправь документ или /cancel."
        )
        return UD_FILE

    if getattr(message, "media_group_id", None):
        await update.message.reply_text(
            "⚠️ Групповая отправка (альбом) не поддерживается — пришли один документ отдельным сообщением.\n\n"
            "Отправь документ или /cancel."
        )
        return UD_FILE

    tg_file_name = doc.file_name or "document"
    tg_mime_type = doc.mime_type or "application/octet-stream"

    # Phase 37F.1 (ADR-020 §12): canonical pre-Drive-upload validation —
    # runs before any Drive call, using only Telegram-supplied metadata
    # already available at this point. An invalid/oversized/dangerous
    # file is rejected here and never reaches Drive.
    from business_core.business_builder import validate_document_upload_request
    validation = validate_document_upload_request(tg_file_name, tg_mime_type, doc.file_size)
    if not validation["ok"]:
        await update.message.reply_text(
            _document_creation_message(validation) + "\n\nОтправь другой документ или /cancel.",
        )
        return UD_FILE

    context.user_data["ud"] = {
        "tg_file_id": doc.file_id,
        "tg_file_unique_id": doc.file_unique_id,
        "tg_file_name": tg_file_name,
        "tg_mime_type": tg_mime_type,
        "tg_file_size": doc.file_size,
        "uploaded_by": _telegram_username(update),
    }

    lines = ["✅ Файл получен: " + (doc.file_name or "(без имени)")]
    if validation["code"] == "DOCUMENT_ANALYSIS_UNSUPPORTED":
        lines.append(_document_creation_message(validation))
    lines.extend([
        "",
        "Теперь одной строкой укажи данные документа:",
        "",
        'business=BIZ-001 name="Технический паспорт"',
        "",
        "Опционально: client=, object=, roadmap=, stage=, template=, notes=",
        "",
        "/cancel — отменить.",
    ])
    await update.message.reply_text("\n".join(lines))
    return UD_DETAILS


async def uploaddoc_receive_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = context.user_data.get("ud")
    if draft is None:
        await update.message.reply_text(
            "❌ Файл не найден в текущей сессии. Начни заново: /uploaddoc",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("ud_confirmed_snapshot", None)
        return ConversationHandler.END

    raw = update.message.text or ""
    kv = _parse_kv_args(raw)

    business_id = kv.get("business", "").strip()
    name = kv.get("name", "").strip()
    client_id = kv.get("client", "").strip()
    object_id = kv.get("object", "").strip()
    roadmap_id = kv.get("roadmap", "").strip()
    stage_id = kv.get("stage", "").strip()
    template_id = kv.get("template", "").strip()
    notes = kv.get("notes", "").strip()

    missing = [a for a in UPLOADDOC_REQUIRED_ARGS if not kv.get(a, "").strip()]
    if missing:
        await update.message.reply_text(
            "❌ Использование:\n"
            'business=BIZ-001 name="Технический паспорт"\n\n'
            "Опционально: client=, object=, roadmap=, stage=, template=, notes=\n\n"
            f"Отсутствуют обязательные поля: {', '.join(missing)}"
        )
        return UD_DETAILS

    try:
        from business_core.document_registry_manager import (
            resolve_and_validate_links, resolve_target_drive_folder,
        )

        validation = resolve_and_validate_links(
            business_id=business_id, client_id=client_id, object_id=object_id,
            roadmap_id=roadmap_id, stage_id=stage_id, document_template_id=template_id,
        )
        if not validation["ok"]:
            await update.message.reply_text(f"❌ {validation['error']}")
            context.user_data.pop("ud", None)
            return ConversationHandler.END

        resolved = validation["resolved"]

        folder = resolve_target_drive_folder(
            business_id=resolved["business_id"],
            client_id=resolved["client_id"],
            object_id=resolved["object_id"],
            stage_id=resolved["stage_id"],
        )
        if not folder["ok"]:
            await update.message.reply_text(f"❌ {folder['error']}")
            context.user_data.pop("ud", None)
            return ConversationHandler.END

        # Best-effort friendly folder name for the confirmation card —
        # never blocks registration if this read-only lookup fails.
        folder_name = ""
        try:
            from integrations.google_drive_adapter import get_drive_service, get_file_metadata
            service = get_drive_service()
            meta = get_file_metadata(service, folder["folder_id"])
            if meta.get("ok"):
                folder_name = meta.get("name", "")
        except Exception:
            pass

    except Exception as e:
        log.error(f"uploaddoc_receive_details error: {e}")
        await update.message.reply_text("❌ Не удалось подготовить загрузку документа.")
        context.user_data.pop("ud", None)
        return ConversationHandler.END

    snapshot = {
        **draft,
        "business_id": resolved["business_id"],
        "client_id": resolved["client_id"],
        "object_id": resolved["object_id"],
        "roadmap_id": resolved["roadmap_id"],
        "stage_id": resolved["stage_id"],
        "document_template_id": resolved["document_template_id"],
        "document_name": name,
        "notes": notes,
        "folder_id": folder["folder_id"],
        "folder_level": folder["level"],
        "folder_source_id": folder["source_id"],
        "folder_name": folder_name,
        "op_state": "pending",
    }
    context.user_data["ud_confirmed_snapshot"] = snapshot
    context.user_data.pop("ud", None)

    size_line = f"{snapshot['tg_file_size']} B" if snapshot.get("tg_file_size") else "—"
    folder_label = f"{folder['level']} {folder['source_id']}" if folder["level"] else "—"
    if folder_name:
        folder_label += f" — {folder_name}"

    lines = [
        "📋 Подтверди загрузку документа:",
        "",
        f"Document Name: {name}",
        f"Telegram File Name: {snapshot['tg_file_name']}",
        f"Mime Type: {snapshot['tg_mime_type']}",
        f"File Size: {size_line}",
        f"Business ID: {resolved['business_id'] or '—'}",
        f"Client ID: {resolved['client_id'] or '—'}",
        f"Object ID: {resolved['object_id'] or '—'}",
        f"Roadmap ID: {resolved['roadmap_id'] or '—'}",
        f"Stage ID: {resolved['stage_id'] or '—'}",
        f"Document Template ID: {resolved['document_template_id'] or '—'}",
        f"Target Drive Folder: {folder_label} ({folder['folder_id']})",
        f"Uploaded By: {snapshot['uploaded_by'] or '—'}",
    ]
    if notes:
        lines.append(f"Notes: {notes}")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(
            [["✅ Подтвердить"], ["❌ Отмена"]],
            resize_keyboard=True, one_time_keyboard=True,
        ),
    )
    return UD_CONFIRM


async def uploaddoc_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        context.user_data.pop("ud_confirmed_snapshot", None)
        context.user_data.pop("ud", None)
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    snap = context.user_data.get("ud_confirmed_snapshot")
    if snap is None:
        await update.message.reply_text(
            "❌ Нет подтверждённых данных для загрузки (возможно, уже загружено или отменено). "
            "Начни заново: /uploaddoc",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    op_state = snap.get("op_state")
    if op_state == "processing":
        await update.message.reply_text(
            "⏳ Загрузка уже выполняется, подожди результата.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return UD_CONFIRM
    if op_state == "completed":
        context.user_data.pop("ud_confirmed_snapshot", None)
        await update.message.reply_text(
            "✅ Этот документ уже был загружен.", reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END
    if op_state == "verification_failed":
        context.user_data.pop("ud_confirmed_snapshot", None)
        await update.message.reply_text(
            "⚠️ Регистрация уже выполнена, но post-write verification не прошла ранее. "
            "Повторная загрузка не выполняется — требуется ручная проверка.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    # Atomic guard: set BEFORE any `await` so a duplicate tap arriving
    # while this invocation is mid-flight sees "processing", not "pending".
    snap["op_state"] = "processing"

    tmp_path = None
    try:
        from business_core.document_registry_manager import resolve_and_validate_links

        # Staleness guard: re-check the resolved links still hold right
        # before doing any Telegram/Drive/Sheets I/O.
        revalidation = resolve_and_validate_links(
            business_id=snap["business_id"], client_id=snap["client_id"],
            object_id=snap["object_id"], roadmap_id=snap["roadmap_id"],
            stage_id=snap["stage_id"], document_template_id=snap["document_template_id"],
        )
        if not revalidation["ok"]:
            await update.message.reply_text(
                f"❌ Связи изменились и больше не подтверждаются: {revalidation['error']}\n"
                "Начни заново: /uploaddoc",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        try:
            tg_file = await context.bot.get_file(snap["tg_file_id"])
            buf = io.BytesIO()
            await tg_file.download_to_memory(buf)
            file_bytes = buf.getvalue()
        except Exception as e:
            log.error(f"uploaddoc_confirm: Telegram download error: {e}")
            await update.message.reply_text(
                "❌ Не удалось скачать файл из Telegram.",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        from integrations.google_drive_adapter import (
            get_drive_service, upload_file, get_file_metadata, trash_file,
        )

        service = get_drive_service()

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        from business_core.business_builder import (
            document_drive_upload_failed_result, document_file_metadata_invalid_result,
        )

        try:
            upload_result = upload_file(
                service, tmp_path, snap["folder_id"],
                filename=snap["tg_file_name"], mime_type=snap["tg_mime_type"],
            )
        except Exception as e:
            log.error(f"uploaddoc_confirm: Drive upload error: {e}")
            await update.message.reply_text(
                _document_creation_message(document_drive_upload_failed_result(snap["business_id"])),
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        drive_file_id = upload_result["file_id"]

        # Read back authoritative Drive metadata — never construct the
        # URL manually, never substitute Telegram-side name/mime for a
        # successful registration. If this read fails OR returns
        # incomplete data (missing name/mime_type/webViewLink), the
        # upload is compensated (trashed) and NO registry row is written
        # — Telegram metadata is only ever shown in error messages, never
        # used to complete a registration.
        meta = get_file_metadata(service, drive_file_id)
        metadata_complete = bool(
            meta.get("ok") and meta.get("name") and meta.get("mime_type") and meta.get("web_view_link")
        )
        if not metadata_complete:
            log.error(
                f"uploaddoc_confirm: Drive metadata read failed or incomplete for "
                f"{drive_file_id}: {meta}"
            )
            cleanup = trash_file(service, drive_file_id)
            invalid_result = document_file_metadata_invalid_result(
                business_id=snap["business_id"], drive_file_id=drive_file_id,
                compensation_attempted=True, compensation_succeeded=bool(cleanup.get("ok")),
            )
            await update.message.reply_text(
                _document_creation_message(invalid_result), reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        real_name = meta["name"]
        real_mime = meta["mime_type"]
        web_view_link = meta["web_view_link"]

        # Phase 37D (ADR-020 §11/§19): upload_and_register_document()
        # is now the sole canonical persistence-and-verification path
        # for this mode — this handler only performs the Drive upload/
        # download (both require `await`) and the compensation trash
        # call (also `await`), driven by the structured result's code.
        from business_core.business_builder import upload_and_register_document

        result = upload_and_register_document(
            snap["business_id"], snap["document_name"], drive_file_id,
            real_name, real_mime, web_view_link,
            client_id=snap["client_id"], object_id=snap["object_id"],
            roadmap_id=snap["roadmap_id"], stage_id=snap["stage_id"],
            document_template_id=snap["document_template_id"],
            uploaded_by=snap["uploaded_by"], notes=snap["notes"],
        )

        if result["code"] == "DOCUMENT_PERSISTENCE_FAILED":
            log.error(f"uploaddoc_confirm: DOCUMENT_REGISTRY write failed: {result['error']}")
            cleanup = trash_file(service, drive_file_id)
            from business_core.business_builder import finalize_persistence_failure_compensation
            final_result = finalize_persistence_failure_compensation(
                {**result, "drive_file_id": drive_file_id}, compensation_succeeded=bool(cleanup.get("ok")),
            )
            await update.message.reply_text(
                _document_creation_message(final_result), reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        if result["code"] == "DOCUMENT_POST_WRITE_VERIFICATION_FAILED":
            log.error(
                f"uploaddoc_confirm: post-write verification failed "
                f"document_id={result.get('document_id', '')} drive_file_id={drive_file_id}"
            )
            snap["op_state"] = "verification_failed"
            await update.message.reply_text(
                _document_creation_message(result), reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        if not result["ok"]:
            log.error(f"uploaddoc_confirm: code={result['code']} error={result['error']}")
            await update.message.reply_text(
                _document_creation_message(result), reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        document_id = result["document_id"]
        await update.message.reply_text(
            _document_creation_message(
                result, document_name=snap["document_name"],
                file_name=real_name, drive_file_url=web_view_link,
            ),
            reply_markup=ReplyKeyboardRemove(),
        )

        # Phase 16A: enqueue enrichment analysis ONLY after the upload has
        # fully succeeded (uploaded, authoritative metadata, registry
        # write, post-write verification, success reply already sent).
        # This is a background job — its failure can never roll back the
        # upload above, which has already completed by this point.
        _enqueue_document_analysis(context, document_id, drive_file_id)

    except Exception as e:
        log.error(f"uploaddoc_confirm error: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке документа.", reply_markup=ReplyKeyboardRemove())
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    context.user_data.pop("ud_confirmed_snapshot", None)
    context.user_data.pop("ud", None)
    return ConversationHandler.END


async def uploaddoc_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("ud", None)
    context.user_data.pop("ud_confirmed_snapshot", None)
    await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# Document Intelligence Foundation (Phase 16A)
# ─────────────────────────────────────────────────────────────
#
# Analysis is enrichment ONLY, run asynchronously via the existing
# Telegram job_queue (already installed/used elsewhere — no new
# dependency), and ONLY ever enqueued after /uploaddoc's own transaction
# (upload -> Drive metadata -> DOCUMENT_REGISTRY write -> post-write
# verification -> success reply) has fully completed. An analysis
# failure can never roll back that already-completed upload — see
# business_core/document_intelligence.py's module docstring for the
# full design rationale.

def _enqueue_document_analysis(
    context: ContextTypes.DEFAULT_TYPE, document_id: str, drive_file_id: str,
    force: bool = False,
) -> bool:
    """Best-effort enqueue — never raises, never blocks the caller."""
    job_queue = getattr(context, "job_queue", None)
    if job_queue is None:
        log.warning(
            f"_enqueue_document_analysis({document_id}): job_queue недоступен — "
            "анализ не запланирован (загрузка документа уже успешно завершена)."
        )
        return False
    try:
        job_queue.run_once(
            _analyze_document_job,
            when=0,
            data={"document_id": document_id, "drive_file_id": drive_file_id, "force": force},
            name=f"analyze_document_{document_id}",
        )
        return True
    except Exception as e:
        log.error(f"_enqueue_document_analysis({document_id}): не удалось поставить задачу: {e}")
        return False


async def _analyze_document_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    payload = context.job.data or {}
    document_id = payload.get("document_id", "")
    drive_file_id = payload.get("drive_file_id", "")
    force = bool(payload.get("force", False))
    try:
        from business_core.document_intelligence import analyze_document
        result = analyze_document(document_id=document_id, drive_file_id=drive_file_id, force=force)
        log.info(f"_analyze_document_job({document_id}): {result}")
    except Exception as e:
        # Defensive — analyze_document() already catches everything
        # internally and always leaves a terminal Content Status, but a
        # job callback must never let an exception escape regardless.
        log.error(f"_analyze_document_job({document_id}): unexpected error: {e}")


async def analyzedoc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /analyzedoc document_id=DREG-001 [force=true]

    Read-triggering only — no confirmation flow needed (idempotent,
    non-destructive). Enqueues at most one new background analysis
    attempt; never writes DOCUMENT_CONTENT directly from this handler
    (analyze_document() itself is the single source of truth for the
    idempotency claim, so this command can never create a duplicate row
    even if called twice in quick succession).
    """
    # Phase 16A fix (post-deploy smoke test): every reply here uses
    # parse_mode=None. _reply()'s default "Markdown" silently swallows
    # underscores when their count happens to be even (Telegram parses
    # them as paired italic delimiters rather than raising an error), so
    # "document_id" was rendered as "documentid" — the same class of bug
    # already fixed for /uploaddoc's and /registerdoc's messages.
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    document_id = kv.get("document_id") or kv.get("_pos0", "")
    force = kv.get("force", "").strip().lower() == "true"

    if not document_id:
        await _reply(
            update,
            "❌ Укажи document_id.\n\nПример: /analyzedoc document_id=DREG-001 [force=true]",
            parse_mode=None,
        )
        return

    try:
        from business_core.sheets import find_row_by_id
        from business_core.document_intelligence import get_content_status, decide_action

        doc_found = find_row_by_id("document_registry", document_id)
        if not doc_found:
            await _reply(update, f"❌ Документ {document_id} не найден в DOCUMENT_REGISTRY.", parse_mode=None)
            return
        _, doc_row = doc_found
        drive_file_id = doc_row.get("Drive File ID", "")

        existing = get_content_status(document_id)
        action = decide_action(existing, force=force)

        if action == "skip_completed":
            await _reply(
                update,
                f"✅ Уже проанализировано.\n\n"
                f"Document ID: {document_id}\n"
                f"Detected Document Type: {existing.get('Detected Document Type') or '—'}\n"
                f"Summary: {existing.get('AI Summary') or '—'}\n"
                f"Suggested Document Template ID: {existing.get('Suggested Document Template ID') or '—'}\n\n"
                f"Полная карточка: /docanalysis document_id={document_id}\n"
                "Используй force=true для повторного анализа.",
                parse_mode=None,
            )
            return
        if action == "skip_processing":
            await _reply(
                update, f"⏳ Документ {document_id} уже анализируется — подожди результата.",
                parse_mode=None,
            )
            return
        if action in ("skip_failed", "skip_unsupported"):
            status_ru = "не поддерживается" if action == "skip_unsupported" else "завершился ошибкой"
            await _reply(
                update,
                f"⚠️ Предыдущий анализ {document_id} {status_ru}.\n"
                f"Ошибка: {existing.get('Analysis Error') or '—'}\n\n"
                "Для повторной попытки укажи force=true.",
                parse_mode=None,
            )
            return

        # action == "proceed"
        enqueued = _enqueue_document_analysis(context, document_id, drive_file_id, force=force)
        if enqueued:
            await _reply(update, f"🧠 Анализ документа {document_id} поставлен в очередь.", parse_mode=None)
        else:
            await _reply(
                update,
                f"⚠️ Не удалось поставить анализ {document_id} в очередь "
                "(job_queue недоступен). Документ остаётся зарегистрированным без изменений.",
                parse_mode=None,
            )

    except Exception as e:
        log.error(f"analyzedoc_cmd error: {e}")
        await _reply(update, "❌ Не удалось запустить анализ документа.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Document Analysis Read Interface (Phase 16C)
# ─────────────────────────────────────────────────────────────
#
# /docanalysis is strictly read-only: it never calls Anthropic, never
# downloads from Drive, never writes to DOCUMENT_CONTENT or
# DOCUMENT_REGISTRY, and never triggers analysis. All lookup logic
# (Sheets reads, column names, JSON parsing) lives in
# business_core/document_query.py — this handler only calls
# get_document_analysis() and renders the returned
# DocumentAnalysisResult. It never reads a Sheets column name directly.

_DOCANALYSIS_MESSAGE_MAX_CHARS = 4000


def _render_value(value, depth: int = 0) -> str:
    """Scalars pass through as str(); arrays are comma-joined; a single
    level of nested dict is flattened inline ('key: v; key2: v2') —
    deeper nesting falls back to a compact JSON string rather than
    recursing further ("shallow nested objects" only, per spec)."""
    if isinstance(value, dict):
        if depth >= 1:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts = [f"{str(k).replace('_', ' ')}: {_render_value(v, depth + 1)}" for k, v in value.items()]
        return "; ".join(parts) if parts else "{}"
    if isinstance(value, list):
        return ", ".join(_render_value(v, depth + 1) for v in value) if value else "[]"
    return str(value)


def _render_fields_dict(fields: dict) -> str:
    """
    Pure rendering: turns an ALREADY-PARSED dict (JSON parsing itself
    happens in document_query.py, not here) into a readable multi-line
    block ("field name: value" per line, underscores replaced with
    spaces in KEYS only — values shown verbatim, no invented
    translations/renames). "" if there's nothing to show.
    """
    if not fields:
        return ""
    lines = [f"{str(key).replace('_', ' ')}: {_render_value(value)}" for key, value in fields.items()]
    return "\n".join(lines)


def _split_message_by_lines(text: str, max_len: int = _DOCANALYSIS_MESSAGE_MAX_CHARS) -> list[str]:
    """Line-aware splitter: never cuts a line in half, so it can never
    cut a Unicode character or a "field: value" line's content midway —
    unlike a naive text[:max_len] slice. Splits between lines only.

    A single line that is itself longer than max_len (e.g. an unusually
    long matched-document-ID list) cannot be preserved whole without
    risking an outgoing message exceeding Telegram's size limit, so as a
    last-resort fallback such a line is deterministically chunked into
    max_len-sized pieces — a plain character-level slice, which is always
    safe here since Python str indexing operates on whole Unicode code
    points, never splitting one in half. Normal-sized lines are never
    touched by this fallback and remain intact."""
    lines = text.split("\n")
    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush():
        nonlocal current, current_len
        if current:
            parts.append("\n".join(current))
            current = []
            current_len = 0

    for line in lines:
        if len(line) > max_len:
            _flush()
            for i in range(0, len(line), max_len):
                parts.append(line[i:i + max_len])
            continue
        line_len = len(line) + 1  # +1 for the joining newline
        if current and current_len + line_len > max_len:
            _flush()
        current.append(line)
        current_len += line_len
    _flush()
    return parts or [""]


def _render_document_analysis(result) -> str:
    """
    Pure rendering of a business_core.document_query.DocumentAnalysisResult
    — this function (and docanalysis_cmd below) never references a
    Google Sheets column name, only the result object's own attributes.
    """
    if result.status == "not_found":
        return f"❌ Документ {result.document_id} не найден в DOCUMENT_REGISTRY."

    if result.status == "no_content":
        return (
            f"ℹ️ Анализ для документа {result.document_id} ещё не запускался.\n\n"
            f"Для запуска:\n/analyzedoc document_id={result.document_id}"
        )

    if result.status == "pending":
        return "⏳ Анализ документа ожидает запуска."

    if result.status == "processing":
        return "⏳ Документ сейчас анализируется."

    if result.status == "failed":
        lines = [
            "❌ Анализ завершился с ошибкой",
            "",
            f"Document ID: {result.document_id}",
            f"Название документа: {result.document_name or '—'}",
            f"Ошибка: {result.error or '—'}",
            f"Updated At: {result.updated_at or '—'}",
            "",
            f"/analyzedoc document_id={result.document_id} force=true",
        ]
        return "\n".join(lines)

    if result.status == "unsupported":
        # Deliberately no force=true suggestion here — an unsupported
        # format is not something a retry can fix.
        lines = [
            "⚠️ Формат документа пока не поддерживается",
            "",
            f"Document ID: {result.document_id}",
            f"File Name: {result.file_name or '—'}",
            f"MIME Type: {result.mime_type or '—'}",
            f"Reason: {result.error or '—'}",
        ]
        return "\n".join(lines)

    if result.status != "completed":
        return f"ℹ️ Статус анализа: {result.status or 'неизвестен'}."

    keywords_line = ", ".join(result.keywords)
    card_lines = [
        "📄 Результат анализа документа",
        "",
        f"Document ID: {result.document_id}",
        f"Document Name: {result.document_name or '—'}",
        f"File Name: {result.file_name or '—'}",
        f"Detected Document Type: {result.detected_document_type or '—'}",
        f"AI Summary: {result.summary or '—'}",
        f"Language: {result.language or '—'}",
        f"Page Count: {result.page_count or '—'}",
        f"Suggested Document Template ID: {result.suggested_template_id or '—'}",
        f"Template Match Confidence: {result.template_match_confidence or '—'}",
    ]
    if keywords_line:
        card_lines.append(f"Keywords: {keywords_line}")
    card_lines.append(f"Analysis Completed At: {result.completed_at or '—'}")

    if not result.fields_valid:
        card_lines.append("")
        card_lines.append("Извлечённые поля:")
        card_lines.append("⚠️ Структурированные поля сохранены в некорректном формате.")
    else:
        fields_block = _render_fields_dict(result.fields)
        if fields_block:
            card_lines.append("")
            card_lines.append("Извлечённые поля:")
            card_lines.append(fields_block)

    return "\n".join(card_lines)


async def docanalysis_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /docanalysis document_id=DREG-001

    Read-only view of cached DOCUMENT_CONTENT analysis: lookup (via
    business_core.document_query.get_document_analysis()) then render
    — nothing else. Never calls Anthropic, never downloads from Drive,
    never writes to any sheet, never triggers or re-triggers analysis.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    document_id = kv.get("document_id") or kv.get("_pos0", "")

    if not document_id:
        await _reply(
            update,
            "❌ Укажи document_id.\n\nПример: /docanalysis document_id=DREG-001",
            parse_mode=None,
        )
        return

    try:
        from business_core.document_query import get_document_analysis

        result = get_document_analysis(document_id)
        text = _render_document_analysis(result)
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)

    except Exception as e:
        log.error(f"docanalysis_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить результат анализа.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Telegram Document Requirements Interface (Phase 17B)
# ─────────────────────────────────────────────────────────────
#
# /missingdocs and /docsrequired are strictly read-only: validate input
# → validate scope existence → call business_core.document_requirements'
# public API (via the business_core.document_requirements_query bridge)
# → render. Neither handler reads DOCUMENT_REGISTRY or any other Sheets
# row directly — only business_core.document_requirements_query's
# scope_exists()/evaluate_scope() and the returned result objects'
# attributes. No AI calls, no Drive calls, no Sheets writes, no mutation
# of the requirements engine's own rules (business_core/
# document_requirements.py is untouched by this phase).

_SCOPE_ARG_NAMES = ("stage_id", "roadmap_id", "object_id")
_SCOPE_LABEL_RU = {"stage": "Этап", "roadmap": "Дорожная карта", "object": "Объект"}
_SCOPE_ID_LABEL = {"stage": "Stage ID", "roadmap": "Roadmap ID", "object": "Object ID"}

_STATUS_LABELS_RU = {
    "present": "присутствует",
    "missing": "отсутствует",
    "partial": "частично",
    "optional_missing": "необязательный отсутствует",
    "not_applicable": "не применяется",
}


def _parse_scope_args(raw: str) -> tuple:
    """
    Returns (scope_type, scope_id, error_message). Exactly one of
    stage_id=/roadmap_id=/object_id= must be given, non-blank; anything
    else (none given, more than one given, unknown argument name, blank
    value, stray positional token) is rejected with a clear message —
    never silently guessed.
    """
    kv = _parse_kv_args(raw)

    unknown = [k for k in kv if k not in _SCOPE_ARG_NAMES and not k.startswith("_pos")]
    positional = [k for k in kv if k.startswith("_pos")]
    if unknown or positional:
        bad = unknown + [kv[k] for k in positional]
        return None, None, (
            f"❌ Неизвестный аргумент: {', '.join(str(b) for b in bad)}.\n\n"
            "Укажи ровно один из: stage_id=, roadmap_id=, object_id="
        )

    blank_keys = [k for k in _SCOPE_ARG_NAMES if k in kv and not kv.get(k, "").strip()]
    if blank_keys:
        return None, None, f"❌ Пустое значение параметра: {', '.join(blank_keys)}."

    present = [(k, kv[k].strip()) for k in _SCOPE_ARG_NAMES if k in kv and kv.get(k, "").strip()]
    if len(present) == 0:
        return None, None, "❌ Укажи ровно один параметр: stage_id=, roadmap_id= или object_id=."
    if len(present) > 1:
        names = ", ".join(k for k, _ in present)
        return None, None, f"❌ Укажи только ОДИН параметр области (получено: {names})."

    key, value = present[0]
    scope_type = key[: -len("_id")]  # "stage_id" -> "stage", etc.
    return scope_type, value, None


_NOT_FOUND_RU = {
    "stage": "Этап {id} не найден.",
    "roadmap": "Дорожная карта {id} не найдена.",
    "object": "Объект {id} не найден.",
}

_ZERO_CONFIGURED_RU = {
    "stage": "ℹ️ Для этого этапа ещё не настроены структурированные требования к документам.",
    "roadmap": "ℹ️ В этапах этой дорожной карты ещё не настроены структурированные требования к документам.",
    "object": "ℹ️ В дорожных картах этого объекта ещё не настроены структурированные требования к документам.",
}


def _requirement_display_name(requirement) -> str:
    """
    Unknown/dangling template IDs must remain visible, never hidden.
    business_core.document_requirements already falls back to using the
    template ID itself as the name when no catalog entry exists (it
    never leaves name empty) — this is the only reliable signal
    available from the existing result model without modifying the
    Phase 17A engine, so a name that equals the template ID itself is
    rendered as an explicit "unknown template" label instead of a bare
    ID that could be mistaken for a real title.
    """
    if requirement.name == requirement.document_template_id:
        return f"[неизвестный шаблон: {requirement.document_template_id}]"
    return requirement.name


def _scope_header_lines(result) -> list:
    label = _SCOPE_ID_LABEL.get(result.scope_type, "Scope ID")
    return [f"{label}: {result.scope_id}"]


def _configuration_error_warning_lines(summary) -> list:
    """
    Phase 18C-4A: rendered only when summary.has_configuration_errors
    is True (never for any summary produced before this phase, since
    the field defaults to False) — never a stack trace, only the
    existing human-readable validation-error strings already produced
    by business_core.stage_entity_relations.
    """
    if not getattr(summary, "has_configuration_errors", False):
        return []
    lines = [
        "⚠️ Ошибка настройки требований к документам.",
        "Некоторые связи этапа повреждены или дублируются.",
        "Требуется проверка администратора.",
        "",
    ]
    for stage_id, relation_id, reason in summary.configuration_errors:
        lines.append(f"- Stage ID: {stage_id or '—'}, Relation ID: {relation_id or '—'}")
        lines.append(f"  Причина: {reason}")
    return lines


async def missingdocs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/missingdocs stage_id=... | roadmap_id=... | object_id=... — read-only."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    scope_type, scope_id, error = _parse_scope_args(raw)
    if error:
        await _reply(update, error, parse_mode=None)
        return

    try:
        from business_core.document_requirements_query import evaluate_scope

        result = evaluate_scope(scope_type, scope_id)

        if not result.exists:
            await _reply(update, "❌ " + _NOT_FOUND_RU[scope_type].format(id=scope_id), parse_mode=None)
            return

        summary = result.summary
        if not summary.items and not summary.has_configuration_errors:
            await _reply(update, _ZERO_CONFIGURED_RU[scope_type], parse_mode=None)
            return

        unsatisfied = [
            item for item in summary.items
            if item.status in (
                "missing",
                "partial",
                "optional_missing",
            )
        ]

        lines = []
        if not unsatisfied and not summary.has_configuration_errors:
            lines.append("✅ Все обязательные документы собраны.")
            lines.append("")
            lines.extend(_scope_header_lines(result))
            lines.append(f"Required total: {summary.total_required}")
            lines.append(f"Satisfied: {summary.satisfied_required}")
            lines.append(f"Completion percentage: {summary.completion_percentage}")
        else:
            if unsatisfied:
                lines.append("❌ Не хватает обязательных документов")
            else:
                lines.append("❌ Настройка требований содержит ошибки")
            lines.append("")
            lines.extend(_scope_header_lines(result))
            lines.append(f"Required total: {summary.total_required}")
            lines.append(f"Satisfied: {summary.satisfied_required}")
            lines.append(f"Missing: {summary.missing_required}")
            lines.append(f"Blocking missing: {summary.blocking_missing}")
            lines.append(f"Completion percentage: {summary.completion_percentage}")
            lines.append("")
            for item in unsatisfied:
                req = item.requirement
                lines.append(f"- Document Template ID: {req.document_template_id}")
                lines.append(f"  Name: {_requirement_display_name(req)}")
                lines.append(f"  Stage ID: {req.stage_id or '—'}")
                lines.append(f"  Matched count / Minimum count: {item.matched_count}/{req.minimum_count}")
                lines.append(f"  Status: {_STATUS_LABELS_RU.get(item.status, item.status)}")
                lines.append(f"  Blocking: {'yes' if item.is_blocking else 'no'}")

        if summary.has_configuration_errors:
            lines.append("")
            lines.extend(_configuration_error_warning_lines(summary))

        text = "\n".join(lines)
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)

    except Exception as e:
        log.error(f"missingdocs_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить недостающие документы.", parse_mode=None)


async def docsrequired_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/docsrequired stage_id=... | roadmap_id=... | object_id=... — read-only."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    scope_type, scope_id, error = _parse_scope_args(raw)
    if error:
        await _reply(update, error, parse_mode=None)
        return

    try:
        from business_core.document_requirements_query import evaluate_scope

        result = evaluate_scope(scope_type, scope_id)

        if not result.exists:
            await _reply(update, "❌ " + _NOT_FOUND_RU[scope_type].format(id=scope_id), parse_mode=None)
            return

        summary = result.summary
        if not summary.items and not summary.has_configuration_errors:
            await _reply(update, _ZERO_CONFIGURED_RU[scope_type], parse_mode=None)
            return

        lines = ["📋 Требования к документам", ""]
        lines.extend(_scope_header_lines(result))
        lines.append(f"Required total: {summary.total_required}")
        lines.append(f"Satisfied: {summary.satisfied_required}")
        lines.append(f"Missing: {summary.missing_required}")
        lines.append(f"Blocking missing: {summary.blocking_missing}")
        lines.append(f"Optional missing: {summary.optional_missing}")
        lines.append(f"Completion percentage: {summary.completion_percentage}")
        lines.append(f"Complete: {'yes' if summary.is_complete else 'no'}")
        lines.append("")

        for item in summary.items:
            req = item.requirement
            matched_ids = ", ".join(item.matched_document_ids) if item.matched_document_ids else "—"
            lines.append(f"- Document Template ID: {req.document_template_id}")
            lines.append(f"  Name: {_requirement_display_name(req)}")
            lines.append(f"  Stage ID: {req.stage_id or '—'}")
            lines.append(f"  Status: {_STATUS_LABELS_RU.get(item.status, item.status)}")
            lines.append(f"  Matched Document IDs: {matched_ids}")
            lines.append(f"  Matched count / Minimum count: {item.matched_count}/{req.minimum_count}")
            lines.append(f"  Required: {'yes' if req.required else 'no'}")
            lines.append(f"  Blocking: {'yes' if req.blocking else 'no'}")

        if summary.has_configuration_errors:
            lines.append("")
            lines.extend(_configuration_error_warning_lines(summary))

        text = "\n".join(lines)
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)

    except Exception as e:
        log.error(f"docsrequired_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить требования к документам.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# /recalcprogress — ручной пересчёт Progress % (Phase 9D)
# ─────────────────────────────────────────────────────────────

async def recalcprogress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Пересчитать Progress % дорожной карты по фактическим статусам этапов.

    Формат:
      /recalcprogress roadmap_id=RM-xxx

    Вызывает существующую recalculate_roadmap_progress() — пишет ТОЛЬКО
    колонку Progress % в ROADMAPS. Не меняет Status roadmap, не меняет
    ROADMAP_STAGES, не пишет историю. Пересчёт вручную, не связан с
    /updatestage.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        raw = (update.message.text or "").split(None, 1)[1] if context.args else " ".join(context.args or [])
    except (IndexError, TypeError):
        raw = ""

    args = _parse_kv_args(raw)
    roadmap_id = args.get("roadmap_id") or args.get("_pos0", "")

    if not roadmap_id:
        await _reply(update,
            "❌ Укажи roadmap\\_id.\n\n"
            "Пример:\n`/recalcprogress roadmap_id=RM-027`"
        )
        return

    try:
        from business_core.roadmap_manager import recalculate_roadmap_progress

        result = recalculate_roadmap_progress(roadmap_id)

        if not result["ok"]:
            await _reply(update, f"❌ {result['error']}")
            return

        if result["changed"]:
            lines = [
                f"✅ Roadmap `{roadmap_id}`: Progress "
                f"{result['old_progress']}% → {result['new_progress']}%",
            ]
        else:
            lines = [
                f"ℹ️ Roadmap `{roadmap_id}`: Progress уже {result['new_progress']}% "
                "(изменений нет)",
            ]
        lines.append(
            f"Завершено этапов: {result['done_count']} из {result['total_count']}"
        )

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"recalcprogress_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newservice — создать услугу (Phase 8A)
# ─────────────────────────────────────────────────────────────

async def newservice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Создать новую услугу в SERVICE_CATALOG.

    Формат (строго key=value, позиционный ввод не поддерживается):
      /newservice biz_id=BIZ-001 name="Узаконение реконструкции" category="узаконение" ...
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    known_keys = {
        "biz_id", "name", "service_name", "category", "city", "object_type",
        "client_type", "description", "what_included", "what_not_included",
        "price_from", "price_to", "currency", "duration", "documents",
        "template", "risks", "contractors", "materials", "status", "notes",
    }
    usage_hint = (
        "Пример:\n"
        "`/newservice biz_id=BIZ-001 name=\"Узаконение реконструкции\" "
        "city=Алматы price_from=1500000 duration=\"3-4 месяца\"`"
    )

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    # Phase 10.2D: positional fallback (_pos0/_pos1) удалён — любой
    # свободный текст или ввод без key=value отклоняется, вместо того
    # чтобы тихо интерпретироваться как biz_id/name (см. инцидент SVC-001,
    # где случайное сообщение создало реальную запись в SERVICE_CATALOG).
    positional_tokens = [k for k in args if k.startswith("_pos")]
    if not args or positional_tokens:
        await _reply(update,
            "❌ Используй формат key=value (без key=value ввод не принимается).\n\n"
            + usage_hint
        )
        return

    unknown_keys = sorted(k for k in args if k not in known_keys)
    if unknown_keys:
        await _reply(update,
            f"❌ Неизвестные параметры: {', '.join(unknown_keys)}\n\n"
            + usage_hint
        )
        return

    biz_id       = (args.get("biz_id") or "").strip()
    service_name = (args.get("name") or args.get("service_name") or "").strip()

    if not biz_id or not service_name:
        await _reply(update,
            "❌ Укажи biz\\_id и name.\n\n"
            + usage_hint
        )
        return

    # Проверяем, что biz_id реально существует в BIZ_REGISTRY —
    # раньше любая непустая строка принималась без проверки.
    try:
        from business_core.sheets import find_row_by_id
        biz_row = find_row_by_id("biz_registry", biz_id)
    except Exception as exc:
        log.warning(f"newservice_cmd: не удалось проверить biz_id '{biz_id}': {exc}")
        biz_row = None

    if biz_row is None:
        await _reply(update, f"❌ Бизнес `{biz_id}` не найден в BIZ_REGISTRY")
        return

    try:
        from business_core.service_manager import create_service_record

        result = create_service_record(
            biz_id=biz_id,
            service_name=service_name,
            service_category=args.get("category",          ""),
            city=            args.get("city",              ""),
            object_type=     args.get("object_type",       ""),
            client_type=     args.get("client_type",       ""),
            description=     args.get("description",       ""),
            what_included=   args.get("what_included",     ""),
            what_not_included=args.get("what_not_included",""),
            price_from=      args.get("price_from",        ""),
            price_to=        args.get("price_to",          ""),
            currency=        args.get("currency",          "KZT"),
            estimated_duration=args.get("duration",        ""),
            required_documents=args.get("documents",       ""),
            default_roadmap_template_id=args.get("template", ""),
            risks=           args.get("risks",             ""),
            contractors_needed=args.get("contractors",     ""),
            materials_ids=   args.get("materials",         ""),
            status=          args.get("status",            "active"),
            notes=           args.get("notes",             ""),
        )

        if not result["ok"]:
            await _reply(update, f"❌ Не удалось создать услугу: {result['error']}")
            return

        svc_id = result["service_id"]
        price_str = ""
        pf = args.get("price_from", "")
        if pf:
            try:
                price_str = f"\nЦена от: {int(pf):,} {args.get('currency', 'KZT')}".replace(",", " ")
            except ValueError:
                price_str = f"\nЦена от: {pf} {args.get('currency', 'KZT')}"

        lines = [
            "✅ *Услуга создана*\n",
            f"Service ID: `{svc_id}`",
            f"Бизнес: `{biz_id}`",
            f"Название: {service_name}",
        ]
        if args.get("category"):
            lines.append(f"Категория: {args['category']}")
        if args.get("city"):
            lines.append(f"Город: {args['city']}")
        if args.get("object_type"):
            lines.append(f"Тип объекта: {args['object_type']}")
        if price_str:
            lines.append(price_str.strip())
        if args.get("duration"):
            lines.append(f"Срок: {args['duration']}")
        lines.append(f"Статус: `active`")
        lines.append(f"\nПодробнее: `/service {svc_id}`")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"newservice_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /services — список услуг (Phase 8A)
# ─────────────────────────────────────────────────────────────

async def services_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать список услуг с фильтрами.

    Форматы:
      /services
      /services biz_id=BIZ-001
      /services object_type="частный дом"
      /services city=Алматы
      /services status=active
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    filter_biz_id      = args.get("biz_id",      "")
    filter_object_type = args.get("object_type",  "")
    filter_city        = args.get("city",         "")
    filter_status      = args.get("status",       "")

    try:
        from business_core.service_manager import list_services, normalize_service_status

        # Phase 29CD, Part 5: public list_services() вместо приватного
        # helper-загрузчика service_manager'а — статус здесь намеренно
        # не фильтруется по умолчанию (список всех статусов), чтобы
        # сохранить прежний UX /services; filter_status ниже фильтрует
        # явно, если задан.
        rows = list_services()

        if filter_biz_id:
            rows = [r for r in rows if r.get("biz_id") == filter_biz_id]
        if filter_object_type:
            rows = [r for r in rows
                    if r.get("object_type", "").lower() == filter_object_type.lower()]
        if filter_city:
            rows = [r for r in rows
                    if r.get("city", "").lower() == filter_city.lower()]
        if filter_status:
            rows = [r for r in rows
                    if normalize_service_status(r.get("status", "")) == filter_status.lower()]

        if not rows:
            await _reply(update,
                "📋 *Каталог услуг*\n\nПусто. Создай первую: /newservice"
            )
            return

        rows = rows[:20]

        filter_info = " | ".join(filter(None, [
            f"biz: {filter_biz_id}" if filter_biz_id else "",
            f"obj: {filter_object_type}" if filter_object_type else "",
            f"city: {filter_city}" if filter_city else "",
            f"status: {filter_status}" if filter_status else "",
        ]))

        lines = [f"📋 *Каталог услуг* ({len(rows)} шт.)"
                 + (f" | {filter_info}" if filter_info else "") + "\n"]

        for r in rows:
            svc_id = r.get("service_id", "?")
            name   = r.get("service_name", r.get("notes", "?"))
            biz    = r.get("biz_id", "")
            city   = r.get("city", "")
            otype  = r.get("object_type", "")
            pf     = r.get("price_from", "")
            dur    = r.get("duration", "")
            status = r.get("status", "active")

            status_icon = {"active": "✅", "inactive": "⏸", "draft": "📝"}.get(status, "✅")

            line = f"{status_icon} *{svc_id}* — {name}"
            meta = []
            if biz:
                meta.append(f"`{biz}`")
            if city:
                meta.append(city)
            if otype:
                meta.append(otype)
            if pf:
                meta.append(f"от {pf}")
            if dur:
                meta.append(dur)
            if meta:
                line += "\n  " + " | ".join(meta)
            lines.append(line)
            lines.append("")

    except Exception as e:
        log.error(f"services_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")
        return

    await _reply(update, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# /service — карточка услуги (Phase 8A)
# ─────────────────────────────────────────────────────────────

async def service_detail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать подробную карточку услуги.

    Форматы:
      /service SVC-001
      /service service_id=SVC-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    service_id = args.get("service_id") or args.get("_pos0", "")

    if not service_id:
        await _reply(update,
            "❌ Укажи service\\_id.\n\nПример: `/service SVC-001`"
        )
        return

    try:
        from business_core.service_manager import find_service_by_id

        svc = find_service_by_id(service_id)
        if not svc:
            await _reply(update,
                f"❌ Услуга `{service_id}` не найдена. Список: /services"
            )
            return

        def _f(key: str, label: str) -> str:
            val = svc.get(key, "").strip()
            return f"{label}: {val}" if val else ""

        status_icon = {
            "active": "✅", "inactive": "⏸", "draft": "📝",
        }.get(svc.get("status", "active"), "✅")

        lines = [
            f"📋 *Услуга {service_id}* {status_icon}\n",
            f"Бизнес: `{svc.get('biz_id', '—')}`",
            f"Название: *{svc.get('service_name', svc.get('notes', '—'))}*",
        ]
        for key, label in [
            ("service_category",   "Категория"),
            ("city",               "Город"),
            ("object_type",        "Тип объекта"),
            ("client_type",        "Тип клиента"),
            ("description",        "Описание"),
            ("what_included",      "Включено"),
            ("what_not_included",  "Не включено"),
        ]:
            v = _f(key, label)
            if v:
                lines.append(v)

        # Цена
        pf = svc.get("price_from", "").strip()
        pt = svc.get("price_to",   "").strip()
        cur= svc.get("currency",   "KZT").strip() or "KZT"
        if pf or pt:
            price = f"Цена: от {pf}" if pf else "Цена:"
            if pt:
                price += f" до {pt}"
            price += f" {cur}"
            lines.append(price)

        for key, label in [
            ("duration",                      "Срок"),
            ("required_documents",            "Документы"),
            ("default_roadmap_template_id",   "Шаблон roadmap"),
            ("risks",                         "Риски"),
            ("contractors_needed",            "Подрядчики"),
            ("notes",                         "Заметки"),
        ]:
            v = _f(key, label)
            if v:
                lines.append(v)

        if svc.get("created_at"):
            lines.append(f"\nСоздана: {svc['created_at']}")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"service_detail_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newrtemplate — создать шаблон roadmap (Phase 8B)
# ─────────────────────────────────────────────────────────────

async def newrtemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Создать шаблон дорожной карты в ROADMAP_TEMPLATE_REGISTRY.

    Форматы:
      /newrtemplate name="Узаконение частного дома" biz_id=BIZ-001 service_id=SVC-001
      /newrtemplate name="Глобальный шаблон" case_type=legalization_reconstruction_house
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    template_name = (args.get("name") or args.get("template_name")
                     or args.get("_pos0", ""))

    if not template_name:
        await _reply(update,
            "❌ Укажи name шаблона.\n\n"
            "Пример:\n"
            '`/newrtemplate name="Узаконение реконструкции" biz_id=BIZ-001 service_id=SVC-001`'
        )
        return

    try:
        from business_core.roadmap_template_manager import create_roadmap_template

        result = create_roadmap_template(
            template_name=template_name,
            biz_id=       args.get("biz_id",       ""),
            service_id=   args.get("service_id",    ""),
            case_type=    args.get("case_type",     ""),
            object_type=  args.get("object_type",   ""),
            description=  args.get("description",   ""),
            status=       args.get("status",        "active"),
            notes=        args.get("notes",         ""),
        )

        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return

        tmpl_id = result["template_id"]
        lines = [
            "✅ *Шаблон создан*\n",
            f"Template ID: `{tmpl_id}`",
            f"Название: {template_name}",
        ]
        if args.get("biz_id"):
            lines.append(f"Бизнес: `{args['biz_id']}`")
        if args.get("service_id"):
            lines.append(f"Услуга: `{args['service_id']}`")
        if args.get("case_type"):
            lines.append(f"Case Type: `{args['case_type']}`")
        if args.get("object_type"):
            lines.append(f"Тип объекта: {args['object_type']}")

        lines.append(f"\nДобавь этапы: `/addrtemplatestage template_id={tmpl_id} stage_name=\"...\"`")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"newrtemplate_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /rtemplates — список шаблонов (Phase 8B)
# ─────────────────────────────────────────────────────────────

async def rtemplates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать шаблоны дорожных карт.

    Форматы:
      /rtemplates
      /rtemplates biz_id=BIZ-001
      /rtemplates service_id=SVC-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    filter_biz     = args.get("biz_id",     "")
    filter_service = args.get("service_id", "")

    try:
        from business_core.roadmap_template_manager import (
            list_roadmap_templates, find_roadmap_templates_by_service,
        )

        if filter_service:
            templates = find_roadmap_templates_by_service(filter_service)
        else:
            templates = list_roadmap_templates(biz_id=filter_biz, status="")

        if not templates:
            await _reply(update,
                "📋 *Шаблоны roadmap*\n\nПусто. Создай первый: /newrtemplate"
            )
            return

        lines = [f"📋 *Шаблоны roadmap* ({len(templates)} шт.)\n"]
        for t in templates[:20]:
            tid    = t.get("template_id", "?")
            name   = t.get("template_name", "?")
            svc    = t.get("service_id", "")
            biz    = t.get("biz_id", "")
            stages = t.get("stages_count", "0")
            status = t.get("status", "active")
            icon   = {"active": "✅", "inactive": "⏸", "draft": "📝"}.get(status, "✅")
            line   = f"{icon} `{tid}` — {name}"
            meta   = []
            if biz:
                meta.append(f"biz: {biz}")
            if svc:
                meta.append(f"svc: {svc}")
            meta.append(f"{stages} эт.")
            line += "\n  " + " | ".join(meta)
            lines.append(line)
            lines.append("")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"rtemplates_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /addrtemplatestage — добавить этап в шаблон (Phase 8B)
# ─────────────────────────────────────────────────────────────

async def addrtemplatestage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Добавить этап в шаблон дорожной карты.

    Форматы:
      /addrtemplatestage template_id=RTMPL-001 stage_name="Первичный анализ"
      /addrtemplatestage template_id=RTMPL-001 stage_name="..." order=3 docs="паспорт" days=7
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    template_id = args.get("template_id") or args.get("_pos0", "")
    stage_name  = (args.get("stage_name") or args.get("name")
                   or args.get("_pos1", ""))

    if not template_id or not stage_name:
        await _reply(update,
            "❌ Укажи template\\_id и stage\\_name.\n\n"
            "Пример:\n"
            '`/addrtemplatestage template_id=RTMPL-001 stage_name="Первичный анализ объекта"`'
        )
        return

    try:
        from business_core.roadmap_template_manager import add_roadmap_template_stage

        result = add_roadmap_template_stage(
            template_id=   template_id,
            stage_name=    stage_name,
            order=         int(args.get("order", "0")) if args.get("order", "").isdigit() else 0,
            description=   args.get("description", ""),
            required_docs= args.get("docs",        ""),
            responsible=   args.get("responsible", ""),
            estimated_days=args.get("days",        ""),
            notes=         args.get("notes",       ""),
        )

        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return

        await _reply(update,
            f"✅ Этап добавлен\n\n"
            f"Stage ID: `{result['stage_id']}`\n"
            f"Template: `{template_id}`\n"
            f"Порядок: #{result['order']}\n"
            f"Название: {stage_name}\n\n"
            f"Все этапы: `/rtemplatestages template_id={template_id}`"
        )

    except Exception as e:
        log.error(f"addrtemplatestage_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /rtemplatestages — этапы шаблона (Phase 8B)
# ─────────────────────────────────────────────────────────────

async def rtemplatestages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показать этапы шаблона дорожной карты.

    Форматы:
      /rtemplatestages template_id=RTMPL-001
      /rtemplatestages RTMPL-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    template_id = args.get("template_id") or args.get("_pos0", "")

    if not template_id:
        await _reply(update,
            "❌ Укажи template\\_id.\n\nПример: `/rtemplatestages template_id=RTMPL-001`"
        )
        return

    try:
        from business_core.roadmap_template_manager import (
            find_template_stages, find_roadmap_template_by_id,
        )

        tmpl   = find_roadmap_template_by_id(template_id)
        stages = find_template_stages(template_id)

        if not tmpl and not stages:
            await _reply(update, f"❌ Шаблон `{template_id}` не найден.")
            return

        header = f"📋 *Этапы шаблона {template_id}*"
        if tmpl:
            header += f" — {tmpl.get('template_name', '')}"

        lines = [header, ""]
        if not stages:
            lines.append("Этапов пока нет.")
            lines.append(f"\nДобавить: `/addrtemplatestage template_id={template_id} stage_name=\"...\"`")
        else:
            for s in stages:
                line = f"*{s['order']}.* {s['stage_name']}"
                if s.get("estimated_days"):
                    line += f" _{s['estimated_days']} дн._"
                if s.get("required_docs"):
                    line += f"\n  📄 {s['required_docs']}"
                lines.append(line)

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"rtemplatestages_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newsop — создать SOP (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def newsop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newsop biz_id=BIZ-001 service_id=SVC-001 template_stage_id=TSTG-001
            title="Как проверить документы" purpose="..." steps="1. ...; 2. ..."
            expected_result="..."

    Полный список поддерживаемых параметров (все опциональны, кроме
    title): biz_id, service_id, template_id, template_stage_id, title,
    purpose, steps, expected_result, owner_role, drive_file_id,
    google_drive, version, status, notes — один в один с колонками
    sop_registry.

    expected_result= — основной, документированный параметр для
    ожидаемого результата (совпадает по смыслу с колонкой sop_registry.
    "Expected Result"). result= — короткий алиас, поддерживается для
    обратной совместимости. Если передано И длинное, И короткое имя —
    побеждает expected_result= (тот же приоритет, что уже принят для
    /newchecklist's required_items=/optional_items= vs required=/optional=).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    title = args.get("title") or args.get("_pos0", "")
    if not title:
        await _reply(update,
            "❌ Укажи title.\n\nПример:\n"
            '`/newsop biz_id=BIZ-001 template_stage_id=TSTG-001 title="Проверка документов" '
            'steps="1. Удостоверение; 2. Правоустанавливающий" expected_result="Документы проверены"`'
        )
        return
    try:
        from business_core.knowledge_manager import create_sop_record

        # expected_result= — документированное основное имя; result= —
        # короткий алиас для обратной совместимости. Явно переданное
        # длинное имя всегда побеждает короткое.
        expected_result = args.get("expected_result") or args.get("result", "")

        result = create_sop_record(
            title=             title,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            purpose=           args.get("purpose",            ""),
            steps=             args.get("steps",              ""),
            expected_result=   expected_result,
            owner_role=        args.get("owner_role",         ""),
            drive_file_id=     args.get("drive_file_id",      ""),
            google_drive=      args.get("google_drive",       ""),
            version=           args.get("version",            "1.0"),
            status=            args.get("status",             "active"),
            notes=             args.get("notes",              ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return
        sop_id = result["sop_id"]
        lines = ["✅ *SOP создан*\n", f"SOP ID: `{sop_id}`", f"Название: {title}"]
        if args.get("template_stage_id"):
            lines.append(f"Stage: `{args['template_stage_id']}`")
        lines.append(f"\nПривязать к этапу: `/linkknowledge template_stage_id=... sop_ids={sop_id}`")
        lines.append(f"Посмотреть полностью: `/sop sop_id={sop_id}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newsop_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newchecklist — создать чек-лист (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def newchecklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newchecklist biz_id=BIZ-001 title="Чек-лист документов"
                  items="Удостоверение; Правоустанавливающий; Техпаспорт"
                  required_items="Удостоверение; Правоустанавливающий" optional_items="Техпаспорт"

    template_stage_id=TSTG-001 — опционально, привязка к этапу шаблона.

    required_items=/optional_items= — основной, документированный синтаксис
    для классификации пунктов (совпадает с названиями колонок
    checklist_registry."Required Items"/"Optional Items"). Пункт,
    отсутствующий в обоих списках, по умолчанию становится required
    (safest default — см. business_builder.parse_checklist_template_items()).

    required=/optional= — короткие алиасы, поддерживаются для обратной
    совместимости, но не документируются как основной вариант. Если
    передано И длинное, И короткое имя одновременно — побеждает длинное
    (required_items=/optional_items=).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    title = args.get("title") or args.get("_pos0", "")
    if not title:
        await _reply(update,
            "❌ Укажи title.\n\nПример:\n"
            '`/newchecklist biz_id=BIZ-001 title="Документы клиента" '
            'items="Удостоверение; Техпаспорт" required_items="Удостоверение" optional_items="Техпаспорт"`'
        )
        return
    try:
        from business_core.knowledge_manager import create_checklist_record

        # required_items=/optional_items= — документированное основное имя;
        # required=/optional= — короткий алиас для обратной совместимости.
        # Явно переданное длинное имя всегда побеждает короткое.
        required_items = args.get("required_items") or args.get("required", "")
        optional_items = args.get("optional_items") or args.get("optional", "")

        result = create_checklist_record(
            title=             title,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            items=             args.get("items",              ""),
            required_items=    required_items,
            optional_items=    optional_items,
            completion_criteria=args.get("criteria",          ""),
            owner_role=        args.get("owner_role",         ""),
            notes=             args.get("notes",              ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return
        chk_id = result["checklist_id"]
        lines  = ["✅ *Чек-лист создан*\n", f"Checklist ID: `{chk_id}`", f"Название: {title}"]
        if args.get("template_stage_id"):
            lines.append(f"Stage: `{args['template_stage_id']}`")
        if args.get("items"):
            items = [x.strip() for x in args["items"].split(";") if x.strip()]
            lines.append(f"Пунктов: {len(items)}")
        lines.append(f"\nПривязать: `/linkknowledge template_stage_id=... checklist_ids={chk_id}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newchecklist_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать чек-лист.")


# ─────────────────────────────────────────────────────────────
# /newdoctemplate — создать шаблон документа (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def newdoctemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newdoctemplate biz_id=BIZ-001 template_stage_id=TSTG-001
                    title="Запрос документов" type=message_template description="..."
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    title = args.get("title") or args.get("_pos0", "")
    if not title:
        await _reply(update,
            "❌ Укажи title.\n\nПример:\n"
            '`/newdoctemplate biz_id=BIZ-001 template_stage_id=TSTG-001 '
            'title="Запрос документов" type=message_template`'
        )
        return
    try:
        from business_core.knowledge_manager import create_document_template_record
        result = create_document_template_record(
            title=             title,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            document_type=     args.get("type",               ""),
            description=       args.get("description",        ""),
            notes=             args.get("notes",              ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return
        doc_id = result["doc_template_id"]
        lines  = ["✅ *Шаблон документа создан*\n",
                  f"Document Template ID: `{doc_id}`", f"Название: {title}"]
        if args.get("type"):
            lines.append(f"Тип: {args['type']}")
        if args.get("template_stage_id"):
            lines.append(f"Stage: `{args['template_stage_id']}`")
        lines.append(f"\nПривязать: `/linkknowledge template_stage_id=... document_template_ids={doc_id}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newdoctemplate_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newfaq — создать FAQ (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def newfaq_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newfaq biz_id=BIZ-001 template_stage_id=TSTG-001
            question="Можно ли начать без техпаспорта?"
            answer="Можно провести первичный анализ, но для запуска нужен."
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    question = args.get("question") or args.get("q", "") or args.get("_pos0", "")
    answer   = args.get("answer")   or args.get("a", "") or args.get("_pos1", "")
    if not question:
        await _reply(update,
            "❌ Укажи question.\n\nПример:\n"
            '`/newfaq biz_id=BIZ-001 template_stage_id=TSTG-001 '
            'question="Можно без техпаспорта?" answer="Нет, нужен."`'
        )
        return
    try:
        from business_core.knowledge_manager import create_faq_record
        result = create_faq_record(
            question=          question,
            answer=            answer,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            category=          args.get("category",           ""),
            notes=             args.get("notes",              ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return
        faq_id = result["faq_id"]
        lines  = ["✅ *FAQ создан*\n", f"FAQ ID: `{faq_id}`",
                  f"Вопрос: {question[:80]}"]
        if answer:
            lines.append(f"Ответ: {answer[:80]}")
        if args.get("template_stage_id"):
            lines.append(f"Stage: `{args['template_stage_id']}`")
        lines.append(f"\nПривязать: `/linkknowledge template_stage_id=... faq_ids={faq_id}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newfaq_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /linkknowledge — привязать knowledge к этапу шаблона (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def linkknowledge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /linkknowledge template_stage_id=TSTG-001 sop_ids=SOP-001
                   checklist_ids=CHK-001 document_template_ids=DOC-001 faq_ids=FAQ-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    template_stage_id = args.get("template_stage_id") or args.get("_pos0", "")
    if not template_stage_id:
        await _reply(update,
            "❌ Укажи template\\_stage\\_id.\n\nПример:\n"
            "`/linkknowledge template_stage_id=TSTG-001 sop_ids=SOP-001 checklist_ids=CHK-001`"
        )
        return

    def _split(val: str) -> list[str]:
        return [x.strip() for x in val.replace(";", ",").split(",") if x.strip()]

    sop_ids    = _split(args.get("sop_ids",               ""))
    chk_ids    = _split(args.get("checklist_ids",          ""))
    mat_ids    = _split(args.get("material_ids",           "") or args.get("materials", ""))
    doc_ids    = _split(args.get("document_template_ids",  ""))
    faq_ids    = _split(args.get("faq_ids",                ""))

    try:
        from business_core.knowledge_manager import link_knowledge_to_template_stage
        result = link_knowledge_to_template_stage(
            template_stage_id=     template_stage_id,
            sop_ids=               sop_ids   or None,
            checklist_ids=         chk_ids   or None,
            material_ids=          mat_ids   or None,
            document_template_ids= doc_ids   or None,
            faq_ids=               faq_ids   or None,
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return
        summary = []
        if sop_ids:    summary.append(f"SOP: {', '.join(sop_ids)}")
        if chk_ids:    summary.append(f"CHK: {', '.join(chk_ids)}")
        if mat_ids:    summary.append(f"MAT: {', '.join(mat_ids)}")
        if doc_ids:    summary.append(f"DOC: {', '.join(doc_ids)}")
        if faq_ids:    summary.append(f"FAQ: {', '.join(faq_ids)}")
        await _reply(update,
            f"✅ *Knowledge привязан*\n\n"
            f"Stage: `{template_stage_id}`\n"
            + ("\n".join(summary) if summary else "Ничего не изменено")
            + f"\n\nПросмотр: `/stageknowledge template_stage_id={template_stage_id}`"
        )
    except Exception as e:
        log.error(f"linkknowledge_cmd error: {e}")
        await _reply(update, "❌ Не удалось привязать knowledge.")


# ─────────────────────────────────────────────────────────────
# /stageknowledge — knowledge по этапу (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def stageknowledge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stageknowledge template_stage_id=TSTG-001
    /stageknowledge stage_id=STAGE-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    template_stage_id = args.get("template_stage_id") or ""
    real_stage_id     = args.get("stage_id",           "") or args.get("_pos0", "")

    if not template_stage_id and not real_stage_id:
        await _reply(update,
            "❌ Укажи template\\_stage\\_id или stage\\_id.\n\n"
            "Примеры:\n"
            "`/stageknowledge template_stage_id=TSTG-001`\n"
            "`/stageknowledge stage_id=STAGE-001`"
        )
        return

    try:
        from business_core.knowledge_manager import (
            find_knowledge_by_template_stage, get_knowledge_for_stage,
            find_sop_by_id, find_checklist_by_id,
            find_document_template_by_id, find_faq_by_id,
        )

        if template_stage_id:
            knowledge = find_knowledge_by_template_stage(template_stage_id)
            header    = f"📚 *Knowledge для шаблона {template_stage_id}*"
        else:
            knowledge = get_knowledge_for_stage(real_stage_id, is_template=False)
            header    = f"📚 *Knowledge для этапа {real_stage_id}*"

        lines = [header, ""]
        any_found = False

        for sop_id in knowledge.get("sop_ids", []):
            sop = find_sop_by_id(sop_id)
            if sop:
                lines.append(f"📋 *SOP* `{sop_id}`: {sop.get('Title', sop_id)}")
                if sop.get("Steps"):
                    lines.append(f"   Шаги: {sop['Steps'][:100]}")
                any_found = True

        for chk_id in knowledge.get("checklist_ids", []):
            chk = find_checklist_by_id(chk_id)
            if chk:
                lines.append(f"☑️ *Чек-лист* `{chk_id}`: {chk.get('Title', chk_id)}")
                if chk.get("Items"):
                    items = [x.strip() for x in chk["Items"].split(";") if x.strip()]
                    for item in items[:5]:
                        lines.append(f"   • {item}")
                any_found = True

        for doc_id in knowledge.get("document_template_ids", []):
            doc = find_document_template_by_id(doc_id)
            if doc:
                lines.append(f"📄 *Шаблон* `{doc_id}`: {doc.get('Title', doc_id)}")
                any_found = True

        for faq_id in knowledge.get("faq_ids", []):
            faq = find_faq_by_id(faq_id)
            if faq:
                lines.append(f"❓ *FAQ* `{faq_id}`: {faq.get('Question', faq_id)[:80]}")
                if faq.get("Answer"):
                    lines.append(f"   💬 {faq['Answer'][:100]}")
                any_found = True

        if knowledge.get("material_ids"):
            lines.append(f"📦 *Materials*: {', '.join(knowledge['material_ids'])}")
            any_found = True

        if not any_found:
            lines.append("Нет привязанных материалов.")
            stage_ref = template_stage_id or real_stage_id
            lines.append(f"\nДобавить: `/linkknowledge template_stage_id={stage_ref} sop_ids=...`")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"stageknowledge_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить knowledge.")


# ─────────────────────────────────────────────────────────────
# Phase 45: SOP Foundation UX — /sop full-text read-only viewer.
# /stageknowledge already shows SOPs, but truncates Steps to 100
# characters and mixes SOP in with Checklist/Document/FAQ/Materials in
# one combined view. /sop is a dedicated, full-text, SOP-only viewer —
# never truncates, splits safely across multiple messages if needed,
# and always sends with parse_mode=None (never the legacy Markdown
# default) since SOP free text (Purpose/Steps/Expected Result, written
# by non-technical staff) can contain underscores/asterisks that would
# otherwise be silently mangled by Telegram's legacy Markdown parser —
# the same escaping-risk class already found and fixed elsewhere in
# this codebase (see /updatestage's override_type fix).
# ─────────────────────────────────────────────────────────────

def _render_sop_full(sop: dict) -> list[str]:
    """Full, untruncated field-by-field rendering of one sop_registry
    row — the counterpart to /stageknowledge's truncated inline preview."""
    lines = [
        f"📋 SOP: {sop.get('SOP ID', '')}",
        f"Title: {sop.get('Title', '') or '—'}",
    ]
    if sop.get("Purpose"):
        lines.append(f"Purpose: {sop['Purpose']}")
    if sop.get("Steps"):
        lines.append(f"Steps: {sop['Steps']}")
    if sop.get("Expected Result"):
        lines.append(f"Expected Result: {sop['Expected Result']}")
    if sop.get("Owner Role"):
        lines.append(f"Owner Role: {sop['Owner Role']}")
    lines.append(f"Version: {sop.get('Version', '') or '—'}")
    lines.append(f"Status: {sop.get('Status', '') or '—'}")
    if sop.get("Notes"):
        lines.append(f"Notes: {sop['Notes']}")
    drive_url = sop.get("Google Drive", "")
    drive_id = sop.get("Drive File ID", "")
    if drive_url or drive_id:
        lines.append(f"Drive: {drive_url or drive_id}")
    return lines


async def sop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sop sop_id=SOP-001 — read-only, полная запись без обрезки.
    /sop stage_id=STAGE-001 — все SOP, привязанные к живому этапу
    (сначала активные STAGE_ENTITY_RELATIONS Entity Type="sop", если их
    нет — fallback на legacy ROADMAP_STAGES."SOP IDs"), каждый полностью,
    без обрезки.

    Read-only — ничего не пишет и не синхронизирует (для этого есть
    /syncstageknowledge). Всегда отправляется с parse_mode=None —
    свободный текст SOP (Purpose/Steps/Expected Result) может содержать
    символы, которые легаси Markdown-парсер Telegram интерпретирует как
    разметку.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    sop_id = args.get("sop_id") or ""
    stage_id = args.get("stage_id") or (args.get("_pos0", "") if not sop_id else "")

    if not sop_id and not stage_id:
        await _reply(
            update,
            "❌ Укажи sop_id или stage_id.\n\nПримеры:\n"
            "/sop sop_id=SOP-001\n"
            "/sop stage_id=STAGE-001",
            parse_mode=None,
        )
        return

    try:
        from business_core.knowledge_manager import find_sop_by_id, get_knowledge_for_stage

        if sop_id:
            sop = find_sop_by_id(sop_id)
            if sop is None:
                await _reply(update, f"❌ SOP {sop_id} не найден.", parse_mode=None)
                return
            lines = _render_sop_full(sop)
        else:
            from business_core.stage_entity_relations import get_relations_for_stage

            relations = get_relations_for_stage(stage_id, entity_type="sop")
            if relations:
                sop_ids = [r.get("Entity ID", "") for r in relations if r.get("Entity ID", "")]
            else:
                knowledge = get_knowledge_for_stage(stage_id, is_template=False)
                sop_ids = knowledge.get("sop_ids", [])

            if not sop_ids:
                await _reply(
                    update,
                    f"У этапа {stage_id} нет привязанных SOP.\n\n"
                    f"Привязать через шаблон: `/linkknowledge template_stage_id=... sop_ids=...`, "
                    f"затем `/syncstageknowledge stage_id={stage_id}`.",
                    parse_mode=None,
                )
                return

            lines = [f"📚 SOP для этапа {stage_id} ({len(sop_ids)}):", ""]
            for i, one_sop_id in enumerate(sop_ids):
                sop = find_sop_by_id(one_sop_id)
                if sop is None:
                    lines.append(f"⚠️ SOP {one_sop_id} привязан, но не найден в sop_registry.")
                else:
                    lines.extend(_render_sop_full(sop))
                if i < len(sop_ids) - 1:
                    lines.append("")
                    lines.append("──────────")
                    lines.append("")

        text = "\n".join(lines)
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)

    except Exception as e:
        log.error(f"sop_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить SOP.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Phase A: Stage Output Foundation — Required Output.
#
# Template layer (STAGE_OUTPUT_TEMPLATES, business_core.stage_output_manager)
# + Instance layer (STAGE_OUTPUT_INSTANCES) — mirrors the Checklist Template/
# Instance split. /newoutput creates a Template; /linkoutput links it to a
# Template Stage via STAGE_ENTITY_RELATIONS Entity Type="required_output";
# /syncoutputs retroactively creates Output Instances for an already-live
# Stage. Required Output does NOT replace Document/Checklist/SOP/Milestone
# and does NOT participate in any Stage Completion Gate in this phase — see
# business_builder.sync_stage_output_requirements()'s docstring.
# ─────────────────────────────────────────────────────────────

async def newoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newoutput biz_id=BIZ-001 service_id=SVC-001 template_id=RMT-... template_stage_id=TSTG-029
               title="Подписанный договор с клиентом" description="..."
               output_type=document verification_method="Проверить наличие подписанного обеими сторонами договора"
               related_document_template_id=DOC-001 related_checklist_id=CHK-001
               required=true blocking=true status=active notes="..."

    biz_id/title/output_type обязательны. output_type ∈ document/approval/
    decision/communication/system_record/payment/physical_result/
    external_status/other. required=/blocking= сохраняются как
    Default Required/Default Blocking шаблона (используются /linkoutput'ом
    как fallback, если сам /linkoutput их не указал явно).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    biz_id = args.get("biz_id", "")
    title = args.get("title") or args.get("_pos0", "")
    output_type = args.get("output_type", "")

    if not biz_id or not title or not output_type:
        await _reply(update,
            "❌ Укажи biz_id, title и output_type.\n\nПример:\n"
            '`/newoutput biz_id=BIZ-001 template_stage_id=TSTG-029 '
            'title="Подписанный договор с клиентом" output_type=document '
            'verification_method="Проверить наличие подписанного обеими сторонами договора" '
            'required=true blocking=true`'
        )
        return

    try:
        from business_core.stage_output_manager import create_output_template

        result = create_output_template(
            biz_id=biz_id, title=title, output_type=output_type,
            service_id=args.get("service_id", ""),
            template_id=args.get("template_id", ""),
            template_stage_id=args.get("template_stage_id", ""),
            description=args.get("description", ""),
            verification_method=args.get("verification_method", ""),
            related_document_template_id=args.get("related_document_template_id", ""),
            related_checklist_id=args.get("related_checklist_id", ""),
            default_required=args.get("required", "true"),
            default_blocking=args.get("blocking", "true"),
            status=args.get("status", "active"),
            notes=args.get("notes", ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return

        output_template_id = result["output_template_id"]
        lines = [
            "✅ *Output Template создан*\n",
            f"Output Template ID: `{output_template_id}`",
            f"Название: {title}",
            f"Тип: {output_type}",
        ]
        template_stage_id = args.get("template_stage_id", "")
        if template_stage_id:
            lines.append(f"Template Stage: `{template_stage_id}`")
            lines.append(
                f"\nПривязать: `/linkoutput template_stage_id={template_stage_id} "
                f"output_ids={output_template_id}`"
            )
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Output Template.")


async def linkoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /linkoutput template_stage_id=TSTG-029 output_ids=SOUT-001,SOUT-002 [required=true] [blocking=true]

    Связывает Output Template(ы) с Template Stage через
    STAGE_ENTITY_RELATIONS (Entity Type="required_output") — relation
    остаётся на уровне Template Stage, никогда не копируется на живой
    Stage (для этого есть /syncoutputs). Отдельная команда, НЕ расширение
    /linkknowledge — required_output не имеет legacy comma-list колонки,
    поэтому не вписывается в архитектуру /linkknowledge, которая пишет
    именно в такие колонки.

    Если required=/blocking= не переданы — для каждого output_id
    подставляется его собственный Default Required/Default Blocking из
    Output Template (у разных outputs могут быть разные дефолты). Если
    переданы явно — применяются одинаково ко ВСЕМ перечисленным outputs.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    template_stage_id = args.get("template_stage_id") or args.get("_pos0", "")
    if not template_stage_id:
        await _reply(update,
            "❌ Укажи template_stage_id.\n\nПример:\n"
            "`/linkoutput template_stage_id=TSTG-029 output_ids=SOUT-001`"
        )
        return

    output_ids = [x.strip() for x in (args.get("output_ids", "") or "").replace(";", ",").split(",") if x.strip()]
    if not output_ids:
        await _reply(update,
            "❌ Укажи output_ids.\n\nПример:\n"
            "`/linkoutput template_stage_id=TSTG-029 output_ids=SOUT-001,SOUT-002`"
        )
        return

    explicit_required = args.get("required")
    explicit_blocking = args.get("blocking")

    try:
        from business_core.stage_output_manager import find_output_template_by_id
        from business_core.stage_entity_relations import create_required_output_relation_for_template_stage

        not_found = []
        # Каждый output_id может разрешиться в свою собственную (required,
        # blocking) пару, если флаги не переданы явно — группируем по
        # итоговой паре, т.к. примитив записи relation принимает ровно одну
        # конкретную пару за вызов.
        by_pair: dict[tuple[str, str], list[str]] = {}
        for output_template_id in output_ids:
            template = find_output_template_by_id(output_template_id)
            if template is None:
                not_found.append(output_template_id)
                continue
            resolved_required = (
                explicit_required if explicit_required is not None
                else template.get("Default Required", "true")
            )
            resolved_blocking = (
                explicit_blocking if explicit_blocking is not None
                else template.get("Default Blocking", "true")
            )
            by_pair.setdefault((resolved_required, resolved_blocking), []).append(output_template_id)

        if not_found:
            await _reply(update, f"❌ Не найдены Output Template: {', '.join(not_found)}")
            return

        created_ids: list[str] = []
        error_texts: list[str] = []
        for (required, blocking), ids in by_pair.items():
            result = create_required_output_relation_for_template_stage(
                template_stage_id, ids, required, blocking,
            )
            if not result.ok:
                error_texts.append("; ".join(str(errs) for _, errs in result.errors))
            else:
                created_ids.extend(rec.get("Entity ID", "") for rec in result.created)

        if error_texts:
            await _reply(update, f"❌ Ошибка: {'; '.join(error_texts)}")
            return

        lines = ["✅ *Output привязан к Template Stage*\n", f"Template Stage: `{template_stage_id}`"]
        if created_ids:
            lines.append(f"Добавлено: {', '.join(created_ids)}")
        else:
            lines.append("Добавлено: ничего (уже было привязано).")
        lines.append("\nСинхронизировать в live Stage: `/syncoutputs stage_id=... confirm=yes`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"linkoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось привязать Output.")


_STAGE_OUTPUT_SYNC_NOTE = (
    "Статус, ответственный, сроки, приоритет и прогресс этапа не изменятся. "
    "ROADMAP_STAGES меняться не будет. Required Output не участвует в Stage "
    "Completion Gate (Phase A)."
)


def _stage_output_sync_message(result: dict) -> str:
    """Render any business_builder.sync_stage_output_requirements()
    result — SOP/Document sync message counterpart, applied to
    STAGE_OUTPUT_INSTANCES creation instead of a relation copy."""
    code = result.get("code", "")
    stage_id = result.get("stage_id", "")
    template_stage_id = result.get("template_stage_id", "")

    if code == "STAGE_OUTPUT_SYNCED":
        created = result.get("created", ())
        already_present = result.get("already_present", ())
        skipped = result.get("skipped_inactive_templates", ())
        lines = [
            "✅ Синхронизация Required Output выполнена",
            f"Stage ID: {stage_id}",
            f"Template Stage ID: {template_stage_id}",
        ]
        if created:
            lines.append(f"Добавлено: {', '.join(created)}")
        else:
            lines.append("Добавлено: ничего (уже было синхронизировано).")
        if already_present:
            lines.append(f"Уже было: {', '.join(already_present)}")
        if skipped:
            lines.append(f"Пропущено (неактивный Output Template): {', '.join(skipped)}")
        lines.append(_STAGE_OUTPUT_SYNC_NOTE)
        return "\n".join(lines)

    if code == "NO_REQUIRED_OUTPUT_RELATIONS":
        return f"❌ {result.get('error') or 'У Template Stage нет активных required_output relations.'}"

    if code == "STAGE_OUTPUT_SYNC_FAILED":
        return f"❌ {result.get('error') or 'Не удалось синхронизировать Required Output.'}"

    # Shared resolution-failure codes (STAGE_NOT_FOUND/ROADMAP_NOT_FOUND/
    # ROADMAP_HAS_NO_TEMPLATE/TEMPLATE_STAGE_NOT_FOUND) — resolve_template_
    # stage_for_stage() is the same shared read used by document/SOP sync,
    # so their rendering already covers these generically.
    return _stage_knowledge_sync_message(result)


def _stage_output_sync_preview_message(result: dict) -> str:
    """Preview counterpart of _stage_output_sync_message()."""
    if result.get("code") == "STAGE_OUTPUT_SYNC_PREVIEW":
        to_add = result.get("to_add", ())
        already_present = result.get("already_present", ())
        skipped = result.get("skipped_inactive_templates", ())
        lines = [
            "📋 Подтверди синхронизацию Required Output:",
            "",
            f"Stage ID: {result.get('stage_id', '')}",
            f"Template Stage ID: {result.get('template_stage_id', '')}",
            "",
        ]
        if to_add:
            lines.append(f"Будет добавлено: {', '.join(to_add)}")
        else:
            lines.append("Будет добавлено: ничего — уже полностью синхронизировано.")
        if already_present:
            lines.append(f"Уже привязано: {', '.join(already_present)}")
        if skipped:
            lines.append(f"Пропущено (неактивный Output Template): {', '.join(skipped)}")
        lines.append("")
        lines.append(_STAGE_OUTPUT_SYNC_NOTE)
        lines.append("")
        lines.append("Чтобы применить, повтори команду с confirm=yes.")
        return "\n".join(lines)
    return _stage_output_sync_message(result)


async def syncoutputs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /syncoutputs stage_id=STAGE-013
    /syncoutputs stage_id=STAGE-013 confirm=yes

    Retroactively creates Output Instances (STAGE_OUTPUT_INSTANCES) for an
    already-live Stage from its Template Stage's active required_output
    relations — separate command, NOT folded into /syncstageknowledge
    (which combines document_template+sop only), so the already-tested
    combined command stays untouched.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id") or args.get("_pos0", "")
    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: `/syncoutputs stage_id=STAGE-013`")
        return

    confirmed = args.get("confirm", "").strip().lower() == "yes"

    try:
        from business_core.business_builder import sync_stage_output_requirements

        result = sync_stage_output_requirements(stage_id, confirm=confirmed)
        text = (
            _stage_output_sync_message(result) if confirmed
            else _stage_output_sync_preview_message(result)
        )
        await _reply(update, text)
    except Exception as e:
        log.error(f"syncoutputs_cmd error: {e}")
        await _reply(update, "❌ Не удалось синхронизировать Required Output.")


_OUTPUT_STATUS_ICON = {
    "pending": "⏳", "produced": "🔧", "submitted": "📤", "accepted": "✅",
    "rejected": "❌", "waived": "🚫", "not_applicable": "➖",
}


def _render_output_instance_summary(instance: dict) -> str:
    icon = _OUTPUT_STATUS_ICON.get(instance.get("Status", ""), "•")
    has_evidence = "есть" if (instance.get("Evidence Value", "") or "").strip() else "нет"
    return (
        f"{icon} {instance.get('Output Instance ID', '')} — {instance.get('Title Snapshot', '')}\n"
        f"   Тип: {instance.get('Output Type Snapshot', '')} | "
        f"Required: {instance.get('Required', '')} | Blocking: {instance.get('Blocking', '')} | "
        f"Статус: {instance.get('Status', '')} | Evidence: {has_evidence}"
    )


def _render_output_instance_full(instance: dict) -> list[str]:
    """Full, untruncated field-by-field rendering of one
    STAGE_OUTPUT_INSTANCES row — including every snapshot and every
    submitted/accepted/rejected/waived audit field."""
    lines = [
        f"📦 Output Instance: {instance.get('Output Instance ID', '')}",
        f"Output Template ID: {instance.get('Output Template ID', '')}",
        f"Title: {instance.get('Title Snapshot', '') or '—'}",
    ]
    if instance.get("Description Snapshot"):
        lines.append(f"Description: {instance['Description Snapshot']}")
    lines.append(f"Output Type: {instance.get('Output Type Snapshot', '') or '—'}")
    if instance.get("Verification Method Snapshot"):
        lines.append(f"Verification Method: {instance['Verification Method Snapshot']}")
    if instance.get("Related Document Template ID"):
        lines.append(f"Related Document Template ID: {instance['Related Document Template ID']}")
    if instance.get("Related Checklist ID"):
        lines.append(f"Related Checklist ID: {instance['Related Checklist ID']}")
    lines.append(f"Required: {instance.get('Required', '')} | Blocking: {instance.get('Blocking', '')}")
    lines.append(f"Roadmap ID: {instance.get('Roadmap ID', '') or '—'} | Stage ID: {instance.get('Stage ID', '') or '—'}")
    lines.append(f"Статус: {instance.get('Status', '')}")
    if instance.get("Evidence Type") or instance.get("Evidence Value"):
        lines.append(f"Evidence: {instance.get('Evidence Type', '')} = {instance.get('Evidence Value', '')}")
    if instance.get("Submitted By") or instance.get("Submitted At"):
        lines.append(f"Submitted By: {instance.get('Submitted By', '') or '—'} / At: {instance.get('Submitted At', '') or '—'}")
    if instance.get("Accepted By") or instance.get("Accepted At"):
        lines.append(f"Accepted By: {instance.get('Accepted By', '') or '—'} / At: {instance.get('Accepted At', '') or '—'}")
    if instance.get("Rejected By") or instance.get("Rejected At"):
        lines.append(f"Rejected By: {instance.get('Rejected By', '') or '—'} / At: {instance.get('Rejected At', '') or '—'}")
        if instance.get("Rejection Reason"):
            lines.append(f"Rejection Reason: {instance['Rejection Reason']}")
    if instance.get("Waived By") or instance.get("Waived At"):
        lines.append(f"Waived By: {instance.get('Waived By', '') or '—'} / At: {instance.get('Waived At', '') or '—'}")
        if instance.get("Waiver Reason"):
            lines.append(f"Waiver Reason: {instance['Waiver Reason']}")
    if instance.get("Notes"):
        lines.append(f"Notes: {instance['Notes']}")
    return lines


async def outputs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /outputs stage_id=STAGE-013 — read-only список Output Instances этапа:
    ID, title, type, required, blocking, status, наличие evidence.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id") or args.get("_pos0", "")
    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: /outputs stage_id=STAGE-013", parse_mode=None)
        return

    try:
        from business_core.stage_output_manager import list_output_instances_for_stage

        instances = list_output_instances_for_stage(stage_id)
        if not instances:
            await _reply(
                update,
                f"У этапа {stage_id} нет Output Instances.\n\n"
                f"Синхронизировать: /syncoutputs stage_id={stage_id} confirm=yes",
                parse_mode=None,
            )
            return

        lines = [f"📦 Outputs этапа {stage_id} ({len(instances)}):", ""]
        for instance in instances:
            lines.append(_render_output_instance_summary(instance))

        text = "\n".join(lines)
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)
    except Exception as e:
        log.error(f"outputs_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Outputs.", parse_mode=None)


async def output_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /output output_instance_id=SOUTI-001 — read-only полная карточка:
    snapshots, stage/roadmap, статус, evidence, submitted/accepted/
    rejected/waived audit-поля. Без обрезки, безопасное разбиение длинных
    сообщений, всегда parse_mode=None.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    if not output_instance_id:
        await _reply(update, "❌ Укажи output_instance_id.\n\nПример: /output output_instance_id=SOUTI-001", parse_mode=None)
        return

    try:
        from business_core.stage_output_manager import find_output_instance_by_id

        instance = find_output_instance_by_id(output_instance_id)
        if instance is None:
            await _reply(update, f"❌ Output Instance {output_instance_id} не найден.", parse_mode=None)
            return

        text = "\n".join(_render_output_instance_full(instance))
        for part in _split_message_by_lines(text):
            await update.message.reply_text(part, parse_mode=None)
    except Exception as e:
        log.error(f"output_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Output.", parse_mode=None)


def _output_lifecycle_message(result: dict, success_text: str) -> str:
    """Shared result-code -> Russian message mapping for /updateoutput,
    /submitoutput, /acceptoutput, /rejectoutput, /waiveoutput."""
    if result.get("ok"):
        return f"✅ {success_text}"
    code = result.get("code", "")
    error = result.get("error", "") or ""
    if code == "OUTPUT_INSTANCE_NOT_FOUND":
        return f"❌ {error or 'Output Instance не найден.'}"
    if code == "INVALID_STATUS_TRANSITION":
        return f"❌ Недопустимый переход статуса: {error}"
    if code in ("EVIDENCE_TYPE_REQUIRED", "EVIDENCE_VALUE_REQUIRED",
                "REJECTION_REASON_REQUIRED", "WAIVER_REASON_REQUIRED"):
        return f"❌ {error}"
    return f"❌ {error or 'Не удалось выполнить операцию.'}"


async def updateoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updateoutput output_instance_id=SOUTI-001 status=produced
    /updateoutput output_instance_id=SOUTI-001 status=not_applicable

    Прямая установка статуса разрешена ТОЛЬКО для produced и
    not_applicable (даёт доступность переходов pending→produced,
    rejected→produced, pending→not_applicable). submitted/accepted/
    rejected/waived требуют своих специализированных команд
    (/submitoutput, /acceptoutput, /rejectoutput, /waiveoutput) — они
    несут обязательный evidence/reason, которых /updateoutput не
    собирает.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    status = args.get("status", "")

    if not output_instance_id or not status:
        await _reply(update,
            "❌ Укажи output_instance_id и status.\n\nПример:\n"
            "`/updateoutput output_instance_id=SOUTI-001 status=produced`"
        )
        return

    if status not in ("produced", "not_applicable"):
        await _reply(update,
            "❌ /updateoutput разрешает только status=produced или status=not_applicable.\n\n"
            "Для submitted/accepted/rejected/waived используй "
            "/submitoutput, /acceptoutput, /rejectoutput, /waiveoutput."
        )
        return

    try:
        from business_core.stage_output_manager import update_output_instance_status

        result = update_output_instance_status(output_instance_id, status)
        await _reply(
            update,
            _output_lifecycle_message(result, f"Статус Output Instance {output_instance_id} обновлён: {status}"),
        )
    except Exception as e:
        log.error(f"updateoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Output.")


async def submitoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /submitoutput output_instance_id=SOUTI-001 evidence_type=drive_url evidence_value="https://..."

    evidence_type и evidence_value обязательны и непусты. Сохраняет их,
    ставит статус submitted, записывает Submitted By (Telegram User ID)
    / Submitted At.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    evidence_type = args.get("evidence_type", "")
    evidence_value = args.get("evidence_value", "")

    if not output_instance_id:
        await _reply(update,
            "❌ Укажи output_instance_id.\n\nПример:\n"
            '`/submitoutput output_instance_id=SOUTI-001 evidence_type=drive_url '
            'evidence_value="https://drive.google.com/..."`'
        )
        return

    try:
        from business_core.stage_output_manager import submit_output_evidence

        submitted_by = str(update.effective_user.id) if update.effective_user else ""
        result = submit_output_evidence(output_instance_id, evidence_type, evidence_value, submitted_by)
        await _reply(
            update,
            _output_lifecycle_message(
                result, f"Evidence сохранено, статус Output Instance {output_instance_id}: submitted",
            ),
        )
    except Exception as e:
        log.error(f"submitoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось сохранить evidence.")


async def acceptoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /acceptoutput output_instance_id=SOUTI-001

    Разрешён из produced или submitted. Ставит accepted, записывает
    Accepted By (Telegram User ID) / Accepted At.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    if not output_instance_id:
        await _reply(update, "❌ Укажи output_instance_id.\n\nПример:\n`/acceptoutput output_instance_id=SOUTI-001`")
        return

    try:
        from business_core.stage_output_manager import accept_output_instance

        accepted_by = str(update.effective_user.id) if update.effective_user else ""
        result = accept_output_instance(output_instance_id, accepted_by)
        await _reply(
            update,
            _output_lifecycle_message(result, f"Output Instance {output_instance_id} принят (accepted)"),
        )
    except Exception as e:
        log.error(f"acceptoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось принять Output.")


async def rejectoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /rejectoutput output_instance_id=SOUTI-001 reason="..."

    reason обязателен. Разрешён только из submitted. Ставит rejected,
    записывает Rejected By (Telegram User ID) / Rejected At / Rejection Reason.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    reason = args.get("reason", "")

    if not output_instance_id:
        await _reply(update,
            "❌ Укажи output_instance_id.\n\nПример:\n"
            '`/rejectoutput output_instance_id=SOUTI-001 reason="Договор не подписан второй стороной"`'
        )
        return

    try:
        from business_core.stage_output_manager import reject_output_instance

        rejected_by = str(update.effective_user.id) if update.effective_user else ""
        result = reject_output_instance(output_instance_id, rejected_by, reason)
        await _reply(
            update,
            _output_lifecycle_message(result, f"Output Instance {output_instance_id} отклонён (rejected)"),
        )
    except Exception as e:
        log.error(f"rejectoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось отклонить Output.")


async def waiveoutput_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /waiveoutput output_instance_id=SOUTI-001 reason="..."

    reason обязателен. Разрешён из pending/produced/submitted/rejected.
    Ставит waived, записывает Waived By (Telegram User ID) / Waived At / Waiver Reason.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    output_instance_id = args.get("output_instance_id") or args.get("_pos0", "")
    reason = args.get("reason", "")

    if not output_instance_id:
        await _reply(update,
            "❌ Укажи output_instance_id.\n\nПример:\n"
            '`/waiveoutput output_instance_id=SOUTI-001 reason="Требование снято клиентом"`'
        )
        return

    try:
        from business_core.stage_output_manager import waive_output_instance

        waived_by = str(update.effective_user.id) if update.effective_user else ""
        result = waive_output_instance(output_instance_id, waived_by, reason)
        await _reply(
            update,
            _output_lifecycle_message(result, f"Output Instance {output_instance_id} списан (waived)"),
        )
    except Exception as e:
        log.error(f"waiveoutput_cmd error: {e}")
        await _reply(update, "❌ Не удалось списать Output.")


# ─────────────────────────────────────────────────────────────
# Phase 38D (ADR-021 §9-§20): Checklist Domain — operational caller UX.
# /newchecklist /linkknowledge /stageknowledge (above) remain Template/
# reference commands, unchanged in meaning — knowledge_manager.py
# stays the Checklist Template persistence owner. The five commands
# below are thin wrappers over business_builder's Checklist
# orchestration functions (instantiate_checklist/
# transition_checklist_status/transition_checklist_item_status/
# update_checklist_admin_fields) and checklist_manager's read-only APIs
# (find_checklist_instance_by_id/list_checklist_instances/
# list_checklist_instance_items) — no business logic beyond what those
# functions already return. Centralized result-code -> Russian message
# mapping below mirrors the Phase 36D Task / Phase 37E Document UX
# pattern exactly.
# ─────────────────────────────────────────────────────────────

_CHECKLIST_INSTANCE_STATUS_RU: dict[str, str] = {
    "draft": "Черновик", "in_progress": "В работе", "blocked": "Заблокирован",
    "completed": "Завершён", "cancelled": "Отменён", "archived": "В архиве",
}

_CHECKLIST_ITEM_STATUS_RU: dict[str, str] = {
    "pending": "Ожидает", "in_progress": "В работе", "blocked": "Заблокирован",
    "done": "Выполнено", "skipped": "Пропущено", "not_applicable": "Не применимо",
}


def _checklist_status_ru(status: str) -> str:
    """Russian label + raw machine status, always both — never only
    the translation, so debugging never loses the exact stored value."""
    return f"{_CHECKLIST_INSTANCE_STATUS_RU.get(status, status)} ({status})"


def _checklist_item_status_ru(status: str) -> str:
    return f"{_CHECKLIST_ITEM_STATUS_RU.get(status, status)} ({status})"


def _checklist_instantiation_message(result: dict) -> str:
    """Render any business_builder.instantiate_checklist() result into
    a single Russian Telegram message. Never exposes the raw result
    dict or a traceback."""
    code = result.get("code", "")

    if code == "CHECKLIST_INSTANCE_CREATED":
        lines = [
            "✅ Checklist Instance создан",
            f"Checklist Instance ID: {result.get('checklist_instance_id', '')}",
            f"Checklist Template ID: {result.get('checklist_template_id', '')}",
            f"Статус: {_checklist_status_ru(result.get('final_status', ''))}",
            f"Пунктов: {result.get('total_items', 0)} (обязательных: {result.get('required_items', 0)})",
        ]
        for key, label in (
            ("business_id", "Business ID"), ("service_id", "Service ID"), ("object_id", "Object ID"),
            ("roadmap_id", "Roadmap ID"), ("stage_id", "Stage ID"),
        ):
            if result.get(key):
                lines.append(f"{label}: {result[key]}")
        return "\n".join(lines)

    if code == "CHECKLIST_INSTANCE_REUSED":
        return "\n".join([
            "♻️ Checklist Instance с этим ключом уже существует — использована существующая запись",
            f"Checklist Instance ID: {result.get('checklist_instance_id', '')}",
            f"Статус: {_checklist_status_ru(result.get('final_status', ''))}",
        ])

    if code == "CHECKLIST_TEMPLATE_NOT_FOUND":
        return f"❌ Checklist Template не найден: {result.get('error') or ''}"

    if code == "CHECKLIST_TEMPLATE_INACTIVE":
        return "❌ Checklist Template неактивен."

    if code == "CHECKLIST_TEMPLATE_ARCHIVED":
        return "❌ Checklist Template архивирован."

    if code == "INVALID_CHECKLIST_TEMPLATE_STATUS":
        return "❌ Недопустимый статус Checklist Template."

    if code == "CHECKLIST_TEMPLATE_ITEMS_EMPTY":
        return "❌ У Checklist Template нет пунктов."

    if code == "CHECKLIST_TEMPLATE_ITEM_CLASSIFICATION_CONFLICT":
        return f"❌ Конфликт классификации пунктов Template: {result.get('error') or ''}"

    if code == "CHECKLIST_TEMPLATE_PARSE_FAILED":
        return "❌ Не удалось разобрать пункты Checklist Template."

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "SERVICE_NOT_FOUND":
        return "❌ Указанный Service не найден."

    if code == "OBJECT_NOT_FOUND":
        return "❌ Указанный Object не найден."

    if code == "ROADMAP_NOT_FOUND":
        return "❌ Указанный Roadmap не найден."

    if code == "STAGE_NOT_FOUND":
        return "❌ Указанный Stage не найден."

    if code == "CHECKLIST_ENTITY_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "MULTIPLE_CHECKLIST_INSTANCE_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Checklist Instance с одним ключом: {ids}",
            "Новый Instance не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "CHECKLIST_INSTANCE_PARTIAL_PERSISTENCE":
        return "\n".join([
            "⚠️ Checklist Instance создан частично — часть пунктов не сохранена.",
            f"Checklist Instance ID: {result.get('checklist_instance_id', '')}",
            "Требуется ручная проверка.",
        ])

    if code == "CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Checklist Instance записан, но пост-проверка записи не прошла.",
            "Требуется ручная проверка.",
        ])

    if code == "CHECKLIST_PERSISTENCE_FAILED":
        return "❌ Не удалось создать Checklist Instance."

    log.warning(f"_checklist_instantiation_message: unmapped code={code!r} business_id={result.get('business_id', '')}")
    return "❌ Не удалось создать Checklist Instance."


def _checklist_item_transition_message(result: dict, item_id: str) -> str:
    """Render any business_builder.transition_checklist_item_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    if code == "CHECKLIST_ITEM_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус пункта Checklist изменён",
            f"Item ID: {item_id}",
            f"Был: {_checklist_item_status_ru(previous_status)}",
            f"Стал: {_checklist_item_status_ru(result.get('final_status', ''))}",
        ])

    if code == "CHECKLIST_ITEM_STATUS_UNCHANGED":
        return f"ℹ️ Пункт {item_id} уже имеет статус {_checklist_item_status_ru(previous_status)} — изменений нет."

    if code == "CHECKLIST_INSTANCE_ITEM_NOT_FOUND":
        return f"❌ Пункт {item_id} не найден."

    if code == "INVALID_CHECKLIST_ITEM_STATUS":
        from business_core.checklist_manager import CHECKLIST_ITEM_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: {', '.join(CHECKLIST_ITEM_STATUS)}"

    if code == "INVALID_CHECKLIST_ITEM_STATUS_TRANSITION":
        return f"❌ Переход {_checklist_item_status_ru(previous_status)} → {_checklist_item_status_ru(requested_status)} не разрешён."

    if code == "CHECKLIST_ITEM_REASON_REQUIRED":
        return f"❌ {result.get('error') or 'Для этого статуса требуется указать причину.'}"

    if code == "CHECKLIST_ITEM_COMPLETION_METADATA_REQUIRED":
        return f"❌ {result.get('error') or 'Для статуса done требуется completed_by.'}"

    if code == "CHECKLIST_ITEM_TERMINAL_REOPEN_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Пункт Checklist уже завершён",
            f"Item ID: {item_id}",
            f"Текущий статус: {_checklist_item_status_ru(previous_status)}",
            "Такой пункт нельзя вернуть в работу обычной командой изменения статуса. "
            "Отдельное явное действие reopen пока не реализовано.",
        ])

    if code == "CHECKLIST_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить статус пункта Checklist."

    if code == "CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED":
        return "⚠️ Статус пункта записан, но пост-проверка записи не прошла."

    log.warning(f"_checklist_item_transition_message: unmapped code={code!r} item_id={item_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _checklist_instance_transition_message(result: dict, instance_id: str) -> str:
    """Render any business_builder.transition_checklist_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    if code == "CHECKLIST_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус Checklist Instance изменён",
            f"Checklist Instance ID: {instance_id}",
            f"Был: {_checklist_status_ru(previous_status)}",
            f"Стал: {_checklist_status_ru(result.get('final_status', ''))}",
        ])

    if code == "CHECKLIST_STATUS_UNCHANGED":
        return f"ℹ️ Checklist Instance {instance_id} уже имеет статус {_checklist_status_ru(previous_status)} — изменений нет."

    if code == "CHECKLIST_INSTANCE_NOT_FOUND":
        return f"❌ Checklist Instance {instance_id} не найден."

    if code == "INVALID_CHECKLIST_STATUS":
        from business_core.checklist_manager import CHECKLIST_INSTANCE_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: {', '.join(CHECKLIST_INSTANCE_STATUS)}"

    if code == "INVALID_CHECKLIST_STATUS_TRANSITION":
        return f"❌ Переход {_checklist_status_ru(previous_status)} → {_checklist_status_ru(requested_status)} не разрешён."

    if code == "CHECKLIST_COMPLETION_REQUIREMENTS_NOT_MET":
        remaining = result.get("required_remaining", 0)
        return f"❌ Не все обязательные пункты Checklist завершены (осталось: {remaining})."

    if code == "CHECKLIST_RESTORE_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Checklist Instance уже завершён",
            f"Checklist Instance ID: {instance_id}",
            f"Текущий статус: {_checklist_status_ru(previous_status)}",
            "Такой Checklist нельзя вернуть в обычный оборот обычной командой изменения статуса. "
            "Отдельное явное действие restore пока не реализовано.",
        ])

    if code == "CHECKLIST_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить статус Checklist Instance."

    if code == "CHECKLIST_INSTANCE_POST_WRITE_VERIFICATION_FAILED":
        return "⚠️ Статус записан, но пост-проверка записи не прошла."

    log.warning(f"_checklist_instance_transition_message: unmapped code={code!r} instance_id={instance_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _checklist_admin_message(result: dict, instance_id: str) -> str:
    """Render any business_builder.update_checklist_admin_fields() result."""
    code = result.get("code", "")

    if code == "CHECKLIST_ADMIN_FIELDS_UPDATED":
        return f"✅ Checklist Instance {instance_id} обновлён."

    if code == "CHECKLIST_ADMIN_FIELDS_UNCHANGED":
        return f"ℹ️ Checklist Instance {instance_id} — изменений нет (значения совпадают)."

    if code == "CHECKLIST_INSTANCE_NOT_FOUND":
        return f"❌ Checklist Instance {instance_id} не найден."

    if code == "INVALID_CHECKLIST_ADMIN_FIELD":
        return f"❌ Недопустимое поле для /updatechecklist: {result.get('error') or ''}"

    if code == "CHECKLIST_IMMUTABLE_FIELD_CONFLICT":
        return f"❌ Указанные поля являются неизменяемой идентичностью Checklist Instance: {result.get('error') or ''}"

    if code == "CHECKLIST_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION":
        return "❌ Изменение связей через /updatechecklist не поддерживается."

    if code == "CHECKLIST_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить Checklist Instance."

    log.warning(f"_checklist_admin_message: unmapped code={code!r} instance_id={instance_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


async def startchecklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /startchecklist business_id=BIZ-001 checklist_template_id=CHK-001
                     [roadmap_id=RM-001] [stage_id=STAGE-001]
                     [service_id=SVC-001] [object_id=OBJ-001]
                     [created_by=...] [notes=...]

    Explicit instantiation of one operational Checklist Instance from
    one Checklist Template. Idempotent — repeated calls with the same
    Business+Template+Roadmap+Stage reuse the existing Instance rather
    than creating a duplicate (ADR-021 §10), so no confirmation flow
    is needed, mirroring /newbctask's own idempotency-key design.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    checklist_template_id = args.get("checklist_template_id", "")

    if not business_id or not checklist_template_id:
        await _reply(
            update,
            "❌ Укажи business_id и checklist_template_id.\n\nПример:\n"
            "`/startchecklist business_id=BIZ-001 checklist_template_id=CHK-001`", parse_mode=None)
        return

    try:
        from business_core.business_builder import instantiate_checklist

        result = instantiate_checklist(
            business_id, checklist_template_id,
            service_id=args.get("service_id", ""), object_id=args.get("object_id", ""),
            roadmap_id=args.get("roadmap_id", ""), stage_id=args.get("stage_id", ""),
            created_by=args.get("created_by", "") or _telegram_username(update),
            notes=args.get("notes", ""),
        )
        await _reply(update, _checklist_instantiation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"startchecklist_cmd error: {e}")
        await _reply(update, "❌ Не удалось запустить Checklist.", parse_mode=None)


_CHECKLISTS_LIST_MAX_SHOWN = 20


# ─────────────────────────────────────────────────────────────
# Phase 1: Checklist Relation Foundation — Template Stage -> Checklist
# Template linkage (STAGE_ENTITY_RELATIONS Entity Type="checklist") and
# provisioning. Does NOT change /startchecklist, /updatecheckitem,
# /updatechecklist, or the Checklist Completion Gate — see
# business_builder.provision_checklists_for_stage()'s docstring for the
# Blocking=false design decision.
# ─────────────────────────────────────────────────────────────

async def linkchecklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /linkchecklist template_stage_id=TSTG-001 checklist_ids=CHK-001,CHK-002 [required=true] [blocking=true]

    Связывает Checklist Template(ы) с Template Stage через
    STAGE_ENTITY_RELATIONS (Entity Type="checklist") — relation остаётся
    на уровне Template Stage, никогда не копируется на живой Stage (для
    этого есть /syncchecklists). Отдельная команда, НЕ расширение
    /linkknowledge — та остаётся legacy-командой, пишущей только в
    comma-list колонки ROADMAP_TEMPLATE_STAGES.

    Если required=/blocking= не переданы — применяется true/true к
    каждому checklist_id (у checklist_registry нет per-template Default
    Required/Blocking колонок, в отличие от Output Template). Если
    переданы явно — применяются одинаково ко ВСЕМ перечисленным ID.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    template_stage_id = args.get("template_stage_id") or args.get("_pos0", "")
    if not template_stage_id:
        await _reply(update,
            "❌ Укажи template_stage_id.\n\nПример:\n"
            "`/linkchecklist template_stage_id=TSTG-001 checklist_ids=CHK-001`"
        )
        return

    checklist_ids = [x.strip() for x in (args.get("checklist_ids", "") or "").replace(";", ",").split(",") if x.strip()]
    if not checklist_ids:
        await _reply(update,
            "❌ Укажи checklist_ids.\n\nПример:\n"
            "`/linkchecklist template_stage_id=TSTG-001 checklist_ids=CHK-001,CHK-002`"
        )
        return

    required = (args.get("required", "").strip().lower() != "false") if "required" in args else True
    blocking = (args.get("blocking", "").strip().lower() != "false") if "blocking" in args else True

    try:
        from business_core.stage_entity_relations import create_checklist_relation_for_template_stage

        created_ids: list[str] = []
        error_texts: list[str] = []
        for checklist_id in checklist_ids:
            result = create_checklist_relation_for_template_stage(
                template_stage_id, checklist_id, required=required, blocking=blocking,
            )
            if not result.ok:
                error_texts.append("; ".join(str(errs) for _, errs in result.errors))
            elif result.created:
                created_ids.append(checklist_id)

        if error_texts:
            await _reply(update, f"❌ Ошибка: {'; '.join(error_texts)}")
            return

        lines = ["✅ *Checklist привязан к Template Stage*\n", f"Template Stage: `{template_stage_id}`"]
        if created_ids:
            lines.append(f"Добавлено: {', '.join(created_ids)}")
        else:
            lines.append("Добавлено: ничего (уже было привязано).")
        lines.append("\nСинхронизировать в live Stage: `/syncchecklists stage_id=... confirm=yes`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"linkchecklist_cmd error: {e}")
        await _reply(update, "❌ Не удалось привязать Checklist.")


_CHECKLIST_PROVISION_NOTE = (
    "Статус, ответственный, сроки, приоритет и прогресс этапа не изменятся. "
    "ROADMAP_STAGES меняться не будет. Checklist Completion Gate не изменён."
)


def _checklist_provision_message(result: dict) -> str:
    code = result.get("code", "")
    stage_id = result.get("stage_id", "")
    template_stage_id = result.get("template_stage_id", "")

    if code in ("CHECKLIST_PROVISIONED", "CHECKLIST_PROVISION_PARTIAL"):
        created = result.get("created", ())
        already_existing = result.get("already_existing", ())
        skipped = result.get("skipped_inactive", ())
        errors = result.get("errors", ())
        lines = [
            "✅ Синхронизация Checklist выполнена" if code == "CHECKLIST_PROVISIONED"
            else "⚠️ Синхронизация Checklist выполнена частично",
            f"Stage ID: {stage_id}",
            f"Template Stage ID: {template_stage_id}",
        ]
        if created:
            lines.append(f"Добавлено: {', '.join(created)}")
        else:
            lines.append("Добавлено: ничего (уже было синхронизировано).")
        if already_existing:
            lines.append(f"Уже было: {', '.join(already_existing)}")
        if skipped:
            lines.append(f"Пропущено (неактивный Checklist Template): {', '.join(skipped)}")
        if errors:
            lines.append("Ошибки: " + "; ".join(f"{cid}: {err}" for cid, err in errors))
        lines.append(_CHECKLIST_PROVISION_NOTE)
        return "\n".join(lines)

    if code == "NO_CHECKLIST_TEMPLATES":
        return f"❌ {result.get('error') or 'У Template Stage нет активных checklist relations, ни legacy-значений.'}"

    if code == "CHECKLIST_PROVISION_FAILED":
        return f"❌ {result.get('error') or 'Не удалось синхронизировать Checklist.'}"

    return _stage_knowledge_sync_message(result)


def _checklist_provision_preview_message(result: dict) -> str:
    if result.get("code") == "CHECKLIST_PROVISION_PREVIEW":
        to_create = result.get("to_create", ())
        already_existing = result.get("already_existing", ())
        skipped = result.get("skipped_inactive", ())
        lines = [
            "📋 Подтверди синхронизацию Checklist:",
            "",
            f"Stage ID: {result.get('stage_id', '')}",
            f"Template Stage ID: {result.get('template_stage_id', '')}",
            "",
        ]
        if to_create:
            lines.append(f"Будет добавлено: {', '.join(to_create)}")
        else:
            lines.append("Будет добавлено: ничего — уже полностью синхронизировано.")
        if already_existing:
            lines.append(f"Уже привязано: {', '.join(already_existing)}")
        if skipped:
            lines.append(f"Пропущено (неактивный Checklist Template): {', '.join(skipped)}")
        lines.append("")
        lines.append(_CHECKLIST_PROVISION_NOTE)
        lines.append("")
        lines.append("Чтобы применить, повтори команду с confirm=yes.")
        return "\n".join(lines)
    return _checklist_provision_message(result)


async def syncchecklists_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /syncchecklists stage_id=STAGE-013
    /syncchecklists stage_id=STAGE-013 confirm=yes

    Тонкая обёртка над business_builder.provision_checklists_for_stage()
    — создаёт недостающие Checklist Instances для живого Stage из
    активных checklist relations (или legacy fallback) Template Stage.
    Не вызывается автоматически ни из /updatestage, ни откуда-либо ещё
    в этой фазе.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return
    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id") or args.get("_pos0", "")
    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: `/syncchecklists stage_id=STAGE-013`")
        return

    confirmed = args.get("confirm", "").strip().lower() == "yes"

    try:
        from business_core.business_builder import provision_checklists_for_stage

        result = provision_checklists_for_stage(stage_id, confirm=confirmed)
        text = (
            _checklist_provision_message(result) if confirmed
            else _checklist_provision_preview_message(result)
        )
        await _reply(update, text)
    except Exception as e:
        log.error(f"syncchecklists_cmd error: {e}")
        await _reply(update, "❌ Не удалось синхронизировать Checklist.")


async def checklists_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /checklists [business_id=BIZ-001] [checklist_template_id=CHK-001]
                [service_id=...] [object_id=...] [roadmap_id=...]
                [stage_id=...] [status=in_progress]

    Read-only, bounded, filtered list of Checklist Instances.

    /checklists template_stage_id=TSTG-001 — отдельный, Template-level
    режим (Phase 1): показывает Checklist Template ID/название/relation
    Required/Blocking/Status/источник (relations или legacy), не
    инстансы.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    template_stage_id = args.get("template_stage_id", "")
    if template_stage_id:
        try:
            from business_core.business_builder import resolve_checklist_templates_for_template_stage
            from business_core.knowledge_manager import find_checklist_by_id
            from business_core.stage_entity_relations import get_relations_for_template_stage

            resolution = resolve_checklist_templates_for_template_stage(template_stage_id)
            if not resolution["ok"]:
                await _reply(update, f"❌ {resolution['error']}", parse_mode=None)
                return

            checklist_ids = resolution["checklist_template_ids"]
            skipped = resolution["skipped_inactive_templates"]
            source = resolution["source"]
            if not checklist_ids and not skipped:
                await _reply(
                    update,
                    f"У Template Stage {template_stage_id} нет привязанных Checklist Template.",
                    parse_mode=None,
                )
                return

            relations_by_id = {}
            if source == "relations":
                relations_by_id = {
                    r.get("Entity ID", ""): r
                    for r in get_relations_for_template_stage(template_stage_id, entity_type="checklist")
                }

            source_label = {"relations": "STAGE_ENTITY_RELATIONS", "legacy": "legacy Checklist IDs", "": "—"}.get(source, source)
            lines = [f"📋 Checklist Templates для Template Stage {template_stage_id} (источник: {source_label}):", ""]
            for checklist_id in checklist_ids:
                template = find_checklist_by_id(checklist_id) or {}
                rel = relations_by_id.get(checklist_id)
                line = f"- {checklist_id} — {template.get('Title', '') or '—'}"
                if rel:
                    line += f" | Required: {rel.get('Required', '')} | Blocking: {rel.get('Blocking', '')} | Status: {rel.get('Status', '')}"
                lines.append(line)
            for checklist_id in skipped:
                lines.append(f"- {checklist_id} — ⚠️ пропущен (неактивный Checklist Template)")

            await _reply(update, "\n".join(lines), parse_mode=None)
        except Exception as e:
            log.error(f"checklists_cmd (template_stage_id) error: {e}")
            await _reply(update, "❌ Не удалось получить Checklist Templates.", parse_mode=None)
        return

    try:
        from business_core.checklist_manager import list_checklist_instances

        instances = list_checklist_instances(business_id=args.get("business_id", ""), status=args.get("status", ""))
        for key, field in (
            ("checklist_template_id", "Checklist Template ID"), ("service_id", "Service ID"),
            ("object_id", "Object ID"), ("roadmap_id", "Roadmap ID"), ("stage_id", "Stage ID"),
        ):
            if args.get(key):
                instances = [i for i in instances if i.get(field, "") == args[key]]

        if not instances:
            await _reply(update, "ℹ️ Checklist Instances не найдены.", parse_mode=None)
            return

        lines = [f"📋 Checklist Instances ({len(instances)})", ""]
        for inst in instances[:_CHECKLISTS_LIST_MAX_SHOWN]:
            lines.append(
                f"{inst.get('Checklist Instance ID', '')} [{inst.get('Checklist Template ID', '')}] — "
                f"{inst.get('Checklist Title Snapshot', '')} "
                f"[{_checklist_status_ru(inst.get('Status', ''))}] "
                f"{inst.get('Completed Items', '0')}/{inst.get('Total Items', '0')} "
                f"(обязательных осталось: {inst.get('Required Remaining', '0')})"
            )
        if len(instances) > _CHECKLISTS_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_CHECKLISTS_LIST_MAX_SHOWN} из {len(instances)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"checklists_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Checklist.", parse_mode=None)


async def checklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /checklist checklist_instance_id=CLIN-001

    Read-only, exact-ID detail: parent status/progress + bounded item
    list. Never shows Notes, Blocked Reason, Skip Reason, or raw rows.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    instance_id = args.get("checklist_instance_id") or args.get("_pos0", "")

    if not instance_id:
        await _reply(update, "❌ Укажи checklist_instance_id.\n\nПример: /checklist checklist_instance_id=CLIN-001", parse_mode=None)
        return

    try:
        from business_core.checklist_manager import find_checklist_instance_by_id, list_checklist_instance_items

        instance = find_checklist_instance_by_id(instance_id)
        if instance is None:
            await _reply(update, f"❌ Checklist Instance {instance_id} не найден.", parse_mode=None)
            return

        items = list_checklist_instance_items(instance_id=instance_id)

        lines = [
            f"📋 Checklist Instance {instance.get('Checklist Instance ID', '')}",
            "",
            f"Template: {instance.get('Checklist Template ID', '')}",
            f"Название: {instance.get('Checklist Title Snapshot', '')}",
            f"Статус: {_checklist_status_ru(instance.get('Status', ''))}",
            f"Business: {instance.get('Business ID', '') or '—'}",
            f"Service: {instance.get('Service ID', '') or '—'}",
            f"Object: {instance.get('Object ID', '') or '—'}",
            f"Roadmap: {instance.get('Roadmap ID', '') or '—'}",
            f"Stage: {instance.get('Stage ID', '') or '—'}",
            f"Прогресс: {instance.get('Completed Items', '0')}/{instance.get('Total Items', '0')} "
            f"(обязательных осталось: {instance.get('Required Remaining', '0')})",
            "",
            f"Пунктов: {len(items)}",
        ]
        for item in sorted(items, key=lambda i: int(i.get("Item Order") or 0)):
            required_label = "обязательный" if item.get("Required", "") == "true" else "опциональный"
            done_marker = "✅" if item.get("Status", "") in ("done", "not_applicable") else "▫️"
            lines.append(
                f"{done_marker} {item.get('Checklist Instance Item ID', '')} "
                f"[{item.get('Item Order', '')}] {item.get('Item Title Snapshot', '')} "
                f"({required_label}, {_checklist_item_status_ru(item.get('Status', ''))})"
            )

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"checklist_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Checklist Instance.", parse_mode=None)


async def updatecheckitem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatecheckitem checklist_instance_item_id=CLII-001 status=done
                      [completed_by=...] [blocked_reason=...] [skip_reason=...]

    Item-status transition only — no admin/relink/task/document
    automation.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    item_id = args.get("checklist_instance_item_id", "")
    status = args.get("status", "")

    if not item_id or not status:
        await _reply(
            update,
            "❌ Укажи checklist_instance_item_id и status.\n\nПример:\n"
            "`/updatecheckitem checklist_instance_item_id=CLII-001 status=done completed_by=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import transition_checklist_item_status

        result = transition_checklist_item_status(
            item_id, status,
            blocked_reason=args.get("blocked_reason", ""),
            skip_reason=args.get("skip_reason", ""),
            completed_by=args.get("completed_by", "") or _telegram_username(update),
        )
        await _reply(update, _checklist_item_transition_message(result, item_id), parse_mode=None)
    except Exception as e:
        log.error(f"updatecheckitem_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить пункт Checklist.", parse_mode=None)


async def updatechecklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatechecklist checklist_instance_id=CLIN-001 status=in_progress
    /updatechecklist checklist_instance_id=CLIN-001 notes=...

    Status and Notes are never mixed in one call — mirrors /updatetask's
    and /updatedoc's foundation UX exactly, so transition policy and
    admin policy never share a single ambiguous write.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    instance_id = args.get("checklist_instance_id", "")

    if not instance_id:
        await _reply(
            update,
            "❌ Укажи checklist_instance_id.\n\nПример:\n"
            "`/updatechecklist checklist_instance_id=CLIN-001 status=in_progress`\n"
            "`/updatechecklist checklist_instance_id=CLIN-001 notes=...`", parse_mode=None)
        return

    has_status = "status" in args
    has_notes = "notes" in args

    if has_status and has_notes:
        await _reply(
            update,
            "❌ Нельзя одновременно менять статус и Notes.\n"
            "Отправь две отдельные команды:\n"
            "`/updatechecklist checklist_instance_id=... status=...`\n"
            "`/updatechecklist checklist_instance_id=... notes=...`", parse_mode=None)
        return

    if not has_status and not has_notes:
        await _reply(update, "❌ Укажи либо status=..., либо notes=....", parse_mode=None)
        return

    try:
        if has_status:
            from business_core.business_builder import transition_checklist_status
            result = transition_checklist_status(instance_id, args["status"])
            await _reply(update, _checklist_instance_transition_message(result, instance_id), parse_mode=None)
            return

        from business_core.business_builder import update_checklist_admin_fields
        result = update_checklist_admin_fields(instance_id, {"Notes": args["notes"]})
        await _reply(update, _checklist_admin_message(result, instance_id), parse_mode=None)
    except Exception as e:
        log.error(f"updatechecklist_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Checklist Instance.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Phase 39D (ADR-022): Payment/Milestone Domain caller (Telegram) UX.
#
# Every command below is a thin resolve-args -> call-canonical-
# orchestration -> render-message wrapper — no business logic beyond
# what business_builder/payment_manager already returns. Centralized
# result-code -> Russian message mapping below mirrors the Phase 36D
# Task / Phase 37E Document / Phase 38D Checklist UX pattern exactly.
# `/milestones` (defined above, Phase 9-era) is untouched by this
# section — it remains its own separate, read-only, Roadmap-owned
# command with no relation to payment_manager.py.
# ─────────────────────────────────────────────────────────────

_PAYMENT_TEMPLATE_STATUS_RU: dict[str, str] = {
    "active": "Активен", "inactive": "Неактивен", "archived": "В архиве",
}

_PAYMENT_OBLIGATION_STATUS_RU: dict[str, str] = {
    "draft": "Черновик", "issued": "Выставлен", "partially_paid": "Частично оплачен",
    "paid": "Оплачен", "cancelled": "Отменён", "archived": "В архиве",
}

_PAYMENT_TRANSACTION_STATUS_RU: dict[str, str] = {
    "pending": "Ожидает подтверждения", "confirmed": "Подтверждён",
    "reversed": "Реверснут", "failed": "Не прошёл",
}

_PAYMENT_CALCULATION_TYPE_RU: dict[str, str] = {
    "fixed": "Фиксированная сумма", "percentage": "Процент",
}


def _payment_template_status_ru(status: str) -> str:
    return f"{_PAYMENT_TEMPLATE_STATUS_RU.get(status, status)} ({status})"


def _payment_obligation_status_ru(status: str) -> str:
    return f"{_PAYMENT_OBLIGATION_STATUS_RU.get(status, status)} ({status})"


def _payment_transaction_status_ru(status: str) -> str:
    return f"{_PAYMENT_TRANSACTION_STATUS_RU.get(status, status)} ({status})"


def _payment_calculation_type_ru(calc_type: str) -> str:
    return _PAYMENT_CALCULATION_TYPE_RU.get(calc_type, calc_type)


def _format_payment_amount(amount: str, currency: str) -> str:
    """Caller-only display formatting. Never recomputes or rounds —
    renders exactly the canonical Decimal string Foundation already
    produced, alongside its currency (ADR-022 §20/Phase 39C §12)."""
    amount = amount or "—"
    currency = currency or ""
    return f"{amount} {currency}".strip()


def _payment_template_creation_message(result: dict) -> str:
    """Render any business_builder.create_commercial_milestone_template() result."""
    code = result.get("code", "")

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_CREATED":
        lines = [
            "✅ Commercial Milestone Template создан",
            f"PMT ID: {result.get('commercial_milestone_template_id', '')}",
            f"Статус: {_payment_template_status_ru(result.get('final_status', ''))}",
        ]
        if result.get("amount"):
            lines.append(f"Сумма: {_format_payment_amount(result.get('amount', ''), result.get('currency', ''))}")
        return "\n".join(lines)

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_REUSED":
        return "\n".join([
            "♻️ Commercial Milestone Template с этим ключом уже существует — использована существующая запись",
            f"PMT ID: {result.get('commercial_milestone_template_id', '')}",
            f"Статус: {_payment_template_status_ru(result.get('final_status', ''))}",
        ])

    if code == "MULTIPLE_COMMERCIAL_MILESTONE_TEMPLATE_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Commercial Milestone Template с одним ключом: {ids}",
            "Новый Template не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "INVALID_MILESTONE_CALCULATION_TYPE":
        return f"❌ {result.get('error') or 'Недопустимый calculation_type. Допустимые значения: fixed, percentage.'}"

    if code == "MILESTONE_FIXED_AMOUNT_REQUIRED":
        return "❌ Для calculation_type=fixed требуется fixed_amount."

    if code == "MILESTONE_PERCENTAGE_REQUIRED":
        return "❌ Для calculation_type=percentage требуется percentage (0, 100]."

    if code == "MILESTONE_CALCULATION_FIELDS_CONFLICT":
        return f"❌ {result.get('error') or 'fixed_amount и percentage не могут быть заполнены одновременно.'}"

    if code in ("INVALID_PAYMENT_AMOUNT", "INVALID_PAYMENT_AMOUNT_SCALE", "PAYMENT_AMOUNT_MUST_BE_POSITIVE"):
        return f"❌ {result.get('error') or 'Недопустимая сумма.'}"

    if code == "INVALID_PAYMENT_CURRENCY":
        return f"❌ {result.get('error') or 'Недопустимая валюта — требуется 3-буквенный код (например KZT).'}"

    if code == "ROADMAP_NOT_FOUND":
        return "❌ Указанный Roadmap Template не найден."

    if code == "SERVICE_NOT_FOUND":
        return "❌ Указанный Service не найден."

    if code == "PAYMENT_ENTITY_RELATION_MISMATCH":
        return f"❌ {result.get('error') or 'Требуется хотя бы одно: roadmap_template_id или service_id.'}"

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Commercial Milestone Template записан, но пост-проверка записи не прошла.",
            "Требуется ручная проверка.",
        ])

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось создать Commercial Milestone Template."

    if not code and result.get("error"):
        return f"❌ {result['error']}"

    log.warning(f"_payment_template_creation_message: unmapped code={code!r}")
    return "❌ Не удалось создать Commercial Milestone Template."


def _payment_template_status_message(result: dict, template_id: str) -> str:
    """Render any business_builder.transition_commercial_milestone_template_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус Commercial Milestone Template изменён",
            f"PMT ID: {template_id}",
            f"Был: {_payment_template_status_ru(previous_status)}",
            f"Стал: {_payment_template_status_ru(result.get('final_status', ''))}",
        ])

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_STATUS_UNCHANGED":
        return f"ℹ️ Template {template_id} уже имеет статус {_payment_template_status_ru(previous_status)} — изменений нет."

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND":
        return f"❌ Commercial Milestone Template {template_id} не найден."

    if code == "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS":
        from business_core.payment_manager import TEMPLATE_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: {', '.join(TEMPLATE_STATUS)}"

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_RESTORE_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Commercial Milestone Template уже деактивирован/архивирован",
            f"PMT ID: {template_id}",
            f"Текущий статус: {_payment_template_status_ru(previous_status)}",
            "Вернуть его в active обычной командой изменения статуса нельзя. "
            "Отдельное явное действие restore пока не реализовано.",
        ])

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить статус Commercial Milestone Template."

    log.warning(f"_payment_template_status_message: unmapped code={code!r} template_id={template_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_template_admin_message(result: dict, template_id: str) -> str:
    """Render any business_builder.update_commercial_milestone_template_admin_fields() result."""
    code = result.get("code", "")

    if result.get("ok"):
        if result.get("changed"):
            return f"✅ Commercial Milestone Template {template_id} обновлён."
        return f"ℹ️ Commercial Milestone Template {template_id} — изменений нет (значения совпадают)."

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND":
        return f"❌ Commercial Milestone Template {template_id} не найден."

    if code == "PAYMENT_TRANSACTION_IMMUTABLE":
        return f"❌ Указанные поля являются неизменяемой идентичностью Commercial Milestone Template: {result.get('error') or ''}"

    if code == "INVALID_COMMERCIAL_MILESTONE_TEMPLATE_STATUS":
        return f"❌ {result.get('error') or 'Недопустимое поле для /updatepaymenttemplate.'}"

    log.warning(f"_payment_template_admin_message: unmapped code={code!r} template_id={template_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_obligation_creation_message(result: dict) -> str:
    """Render any business_builder.create_payment_obligation() result."""
    code = result.get("code", "")

    if code == "PAYMENT_OBLIGATION_CREATED":
        lines = [
            "✅ Payment Obligation создан",
            f"POB ID: {result.get('payment_obligation_id', '')}",
            f"Сумма: {_format_payment_amount(result.get('amount', ''), result.get('currency', ''))}",
            f"Статус: {_payment_obligation_status_ru(result.get('final_status', ''))}",
        ]
        for key, label in (
            ("object_id", "Object ID"), ("service_id", "Service ID"),
            ("roadmap_id", "Roadmap ID"), ("stage_id", "Stage ID"),
            ("commercial_milestone_template_id", "Template ID"),
        ):
            if result.get(key):
                lines.append(f"{label}: {result[key]}")
        return "\n".join(lines)

    if code == "PAYMENT_OBLIGATION_REUSED":
        return "\n".join([
            "♻️ Payment Obligation с этим ключом уже существует — использована существующая запись",
            f"POB ID: {result.get('payment_obligation_id', '')}",
            f"Сумма: {_format_payment_amount(result.get('amount', ''), result.get('currency', ''))}",
            f"Оплачено: {_format_payment_amount(result.get('paid_amount', ''), result.get('currency', ''))}",
            f"Статус: {_payment_obligation_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "CLIENT_NOT_FOUND":
        return f"❌ Client не найден: {result.get('error') or ''}"

    if code == "OBJECT_NOT_FOUND":
        return "❌ Указанный Object не найден."

    if code == "SERVICE_NOT_FOUND":
        return "❌ Указанный Service не найден."

    if code == "ROADMAP_NOT_FOUND":
        return "❌ Указанный Roadmap не найден."

    if code == "STAGE_NOT_FOUND":
        return "❌ Указанный Stage не найден."

    if code == "COMMERCIAL_MILESTONE_TEMPLATE_NOT_FOUND":
        return "❌ Указанный Commercial Milestone Template не найден."

    if code in ("PAYMENT_OBLIGATION_RELATION_MISMATCH", "PAYMENT_ENTITY_RELATION_MISMATCH"):
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "PAYMENT_OBLIGATION_IDEMPOTENCY_CONFLICT":
        return f"❌ {result.get('error') or 'Требуется caller_idempotency_key либо полный Template+Roadmap+Stage+Sequence fallback.'}"

    if code == "MULTIPLE_PAYMENT_OBLIGATION_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Payment Obligation с одним ключом: {ids}",
            "Новый Obligation не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code in ("INVALID_PAYMENT_AMOUNT", "INVALID_PAYMENT_AMOUNT_SCALE", "PAYMENT_AMOUNT_MUST_BE_POSITIVE"):
        return f"❌ {result.get('error') or 'Недопустимая сумма.'}"

    if code == "INVALID_PAYMENT_CURRENCY":
        return f"❌ {result.get('error') or 'Недопустимая валюта.'}"

    if code == "PAYMENT_OBLIGATION_PERSISTENCE_FAILED":
        return "❌ Не удалось создать Payment Obligation."

    if code == "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Payment Obligation записан, но пост-проверка записи не прошла.",
            "Требуется ручная проверка.",
        ])

    log.warning(f"_payment_obligation_creation_message: unmapped code={code!r}")
    return "❌ Не удалось создать Payment Obligation."


def _payment_obligation_status_message(result: dict, obligation_id: str) -> str:
    """Render any business_builder.transition_payment_obligation_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")

    if code == "PAYMENT_OBLIGATION_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус Payment Obligation изменён",
            f"POB ID: {obligation_id}",
            f"Был: {_payment_obligation_status_ru(previous_status)}",
            f"Стал: {_payment_obligation_status_ru(result.get('final_status', ''))}",
        ])

    if code == "PAYMENT_OBLIGATION_STATUS_UNCHANGED":
        return f"ℹ️ Payment Obligation {obligation_id} уже имеет статус {_payment_obligation_status_ru(previous_status)} — изменений нет."

    if code == "PAYMENT_OBLIGATION_NOT_FOUND":
        return f"❌ Payment Obligation {obligation_id} не найден."

    if code == "INVALID_PAYMENT_OBLIGATION_STATUS":
        from business_core.payment_manager import OBLIGATION_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: {', '.join(OBLIGATION_STATUS)}"

    if code == "INVALID_PAYMENT_OBLIGATION_TRANSITION":
        return f"❌ {result.get('error') or 'Такой переход статуса не разрешён.'}"

    if code == "PAYMENT_OBLIGATION_HAS_CONFIRMED_PAYMENTS":
        return "\n".join([
            "🔒 Payment Obligation имеет подтверждённые платежи",
            f"POB ID: {obligation_id}",
            f"Оплачено: {_format_payment_amount(result.get('paid_amount', ''), '')}",
            "Отмена заблокирована — сначала реверсните подтверждённые платежи.",
        ])

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить статус Payment Obligation."

    log.warning(f"_payment_obligation_status_message: unmapped code={code!r} obligation_id={obligation_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_obligation_admin_message(result: dict, obligation_id: str) -> str:
    """Render any business_builder.update_payment_obligation_admin_fields() result."""
    code = result.get("code", "")

    if result.get("ok"):
        if result.get("changed"):
            return f"✅ Payment Obligation {obligation_id} обновлён."
        return f"ℹ️ Payment Obligation {obligation_id} — изменений нет (значения совпадают)."

    if code == "PAYMENT_OBLIGATION_NOT_FOUND":
        return f"❌ Payment Obligation {obligation_id} не найден."

    if code == "PAYMENT_OBLIGATION_RELATION_MISMATCH":
        return f"❌ Указанные поля являются неизменяемой идентичностью Payment Obligation: {result.get('error') or ''}"

    if code == "INVALID_PAYMENT_OBLIGATION_STATUS":
        return f"❌ {result.get('error') or 'Недопустимое поле для /updateobligation.'}"

    log.warning(f"_payment_obligation_admin_message: unmapped code={code!r} obligation_id={obligation_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_transaction_creation_message(result: dict) -> str:
    """Render any business_builder.create_payment_transaction() result.
    Never echoes External Transaction ID/Caller Idempotency Key back —
    only a safe acknowledgement (ADR-022 §27/Phase 39C §12)."""
    code = result.get("code", "")

    if code == "PAYMENT_TRANSACTION_CREATED":
        return "\n".join([
            "✅ Payment записан (pending)",
            f"PTXN ID: {result.get('payment_transaction_id', '')}",
            f"Obligation: {result.get('payment_obligation_id', '')}",
            f"Сумма: {_format_payment_amount(result.get('amount', ''), result.get('currency', ''))}",
            f"Статус: {_payment_transaction_status_ru(result.get('final_status', ''))}",
            "Требуется подтверждение через /confirmpayment.",
        ])

    if code == "PAYMENT_TRANSACTION_REUSED":
        return "\n".join([
            "♻️ Payment с этим ключом уже существует — использована существующая запись",
            f"PTXN ID: {result.get('payment_transaction_id', '')}",
            f"Статус: {_payment_transaction_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "PAYMENT_OBLIGATION_NOT_FOUND":
        return "❌ Указанный Payment Obligation не найден."

    if code == "CLIENT_NOT_FOUND":
        return f"❌ Client не найден: {result.get('error') or ''}"

    if code == "DOCUMENT_NOT_FOUND":
        return "❌ Указанный evidence Document не найден."

    if code == "PAYMENT_ENTITY_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "PAYMENT_CURRENCY_MISMATCH":
        return f"❌ {result.get('error') or 'Валюта Payment не совпадает с валютой Obligation.'}"

    if code == "PAYMENT_TRANSACTION_IDEMPOTENCY_REQUIRED":
        return "❌ Требуется external_transaction_id или caller_idempotency_key."

    if code == "PAYMENT_TRANSACTION_IDEMPOTENCY_CONFLICT":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return f"⚠️ Ключ идемпотентности уже используется другим Payment ({ids}) с иными параметрами."

    if code == "MULTIPLE_PAYMENT_TRANSACTION_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Payment с одним ключом: {ids}",
            "Новый Payment не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code in ("INVALID_PAYMENT_AMOUNT", "INVALID_PAYMENT_AMOUNT_SCALE", "PAYMENT_AMOUNT_MUST_BE_POSITIVE"):
        return f"❌ {result.get('error') or 'Недопустимая сумма.'}"

    if code == "INVALID_PAYMENT_CURRENCY":
        return f"❌ {result.get('error') or 'Недопустимая валюта.'}"

    if code == "PAYMENT_TRANSACTION_PERSISTENCE_FAILED":
        return "❌ Не удалось записать Payment."

    if code == "PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Payment записан, но пост-проверка записи не прошла.",
            "Требуется ручная проверка.",
        ])

    if not code and result.get("error"):
        return f"❌ {result['error']}"

    log.warning(f"_payment_transaction_creation_message: unmapped code={code!r}")
    return "❌ Не удалось записать Payment."


def _payment_transaction_confirmation_message(result: dict, transaction_id: str) -> str:
    """Render any business_builder.confirm_payment_transaction() result."""
    code = result.get("code", "")

    if code == "PAYMENT_TRANSACTION_CONFIRMED":
        return "\n".join([
            "✅ Payment подтверждён",
            f"PTXN ID: {transaction_id}",
            f"Оплачено (Obligation): {_format_payment_amount(result.get('paid_amount', ''), result.get('currency', ''))}",
            f"Остаток (Obligation): {_format_payment_amount(result.get('remaining_amount', ''), result.get('currency', ''))}",
        ])

    if code == "PAYMENT_TRANSACTION_CONFIRMATION_UNCHANGED":
        return f"ℹ️ Payment {transaction_id} уже подтверждён — изменений нет."

    if code == "PAYMENT_TRANSACTION_NOT_FOUND":
        return f"❌ Payment {transaction_id} не найден."

    if code == "INVALID_PAYMENT_TRANSACTION_TRANSITION":
        return f"❌ {result.get('error') or 'Подтверждение возможно только из статуса pending.'}"

    if code == "PAYMENT_TRANSACTION_CONFIRMATION_METADATA_REQUIRED":
        return "❌ Укажи confirmed_by."

    if code == "PAYMENT_TRANSACTION_OVERPAYMENT_BLOCKED":
        return "\n".join([
            "🔒 Подтверждение заблокировано — переплата",
            f"PTXN ID: {transaction_id}",
            f"Сумма Payment: {_format_payment_amount(result.get('amount', ''), '')}",
            f"Остаток Obligation: {_format_payment_amount(result.get('remaining_amount', ''), '')}",
        ])

    if code == "PAYMENT_OBLIGATION_NOT_FOUND":
        return "❌ Связанный Payment Obligation не найден."

    if code == "INVALID_PAYMENT_AMOUNT":
        return "❌ Не удалось разобрать сумму Payment."

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось подтвердить Payment."

    if code == "PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Payment помечен confirmed, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    if code == "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Payment подтверждён, но синхронизация баланса Obligation не удалась.",
            "Требуется ручная проверка.",
        ])

    log.warning(f"_payment_transaction_confirmation_message: unmapped code={code!r} transaction_id={transaction_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_transaction_reversal_message(result: dict, transaction_id: str) -> str:
    """Render any business_builder.reverse_payment_transaction() result.
    Never echoes reversal_reason back verbatim (ADR-022 §22/Phase 39C §22)."""
    code = result.get("code", "")

    if code == "PAYMENT_TRANSACTION_REVERSED":
        return "\n".join([
            "✅ Payment реверснут",
            f"PTXN ID: {transaction_id}",
            f"Оплачено (Obligation): {_format_payment_amount(result.get('paid_amount', ''), result.get('currency', ''))}",
            f"Остаток (Obligation): {_format_payment_amount(result.get('remaining_amount', ''), result.get('currency', ''))}",
        ])

    if code == "PAYMENT_TRANSACTION_REVERSAL_UNCHANGED":
        return f"ℹ️ Payment {transaction_id} уже реверснут — изменений нет."

    if code == "PAYMENT_TRANSACTION_NOT_FOUND":
        return f"❌ Payment {transaction_id} не найден."

    if code == "INVALID_PAYMENT_TRANSACTION_TRANSITION":
        return f"❌ {result.get('error') or 'Реверс возможен только из статуса confirmed.'}"

    if code == "PAYMENT_TRANSACTION_REVERSAL_REASON_REQUIRED":
        return "❌ Укажи reversal_reason и reversed_by."

    if code == "PAYMENT_TRANSACTION_IMMUTABLE":
        return "⚠️ Финансовые поля Payment изменились при реверсе — недопустимо. Требуется ручная проверка."

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось реверснуть Payment."

    if code == "PAYMENT_TRANSACTION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Payment помечен reversed, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    if code == "PAYMENT_OBLIGATION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join([
            "⚠️ Payment реверснут, но синхронизация баланса Obligation не удалась.",
            "Требуется ручная проверка.",
        ])

    log.warning(f"_payment_transaction_reversal_message: unmapped code={code!r} transaction_id={transaction_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _payment_transaction_failure_message(result: dict, transaction_id: str) -> str:
    """Render any business_builder.fail_payment_transaction() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")

    if code == "PAYMENT_TRANSACTION_FAILED":
        if previous_status == "failed":
            return f"ℹ️ Payment {transaction_id} уже помечен failed — изменений нет."
        return f"✅ Payment {transaction_id} помечен failed."

    if code == "PAYMENT_TRANSACTION_NOT_FOUND":
        return f"❌ Payment {transaction_id} не найден."

    if code == "INVALID_PAYMENT_TRANSACTION_TRANSITION":
        return f"❌ {result.get('error') or 'Переход в failed возможен только из статуса pending.'}"

    if code == "PAYMENT_PERSISTENCE_FAILED":
        return "❌ Не удалось обновить статус Payment."

    log.warning(f"_payment_transaction_failure_message: unmapped code={code!r} transaction_id={transaction_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


async def newpaymenttemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newpaymenttemplate title=... calculation_type=fixed fixed_amount=500000
                        currency=KZT [roadmap_template_id=RMT-...] [service_id=SVC-...]
                        [sequence=1] [description=...] [trigger_description=...]
                        [percentage=...] [created_by=...] [notes=...]

    Creates one Commercial Milestone Template. Idempotent — repeated
    calls with the same Roadmap Template/Service/Sequence/Title reuse
    the existing Template rather than creating a duplicate (ADR-022 §10).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    title = args.get("title", "")
    calculation_type = args.get("calculation_type", "")
    currency = args.get("currency", "")

    if not title or not calculation_type or not currency:
        await _reply(
            update,
            "❌ Укажи title, calculation_type и currency.\n\nПример:\n"
            "`/newpaymenttemplate title=... calculation_type=fixed fixed_amount=500000 "
            "currency=KZT roadmap_template_id=RMT-...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_commercial_milestone_template

        result = create_commercial_milestone_template(
            title, calculation_type,
            roadmap_template_id=args.get("roadmap_template_id", ""), service_id=args.get("service_id", ""),
            description=args.get("description", ""), sequence=args.get("sequence", "1"),
            trigger_description=args.get("trigger_description", ""),
            fixed_amount=args.get("fixed_amount", ""), percentage=args.get("percentage", ""),
            currency=currency, created_by=args.get("created_by", "") or _telegram_username(update),
            notes=args.get("notes", ""),
        )
        await _reply(update, _payment_template_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"newpaymenttemplate_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Commercial Milestone Template.", parse_mode=None)


_PAYMENT_LIST_MAX_SHOWN = 20


async def paymenttemplates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /paymenttemplates [roadmap_template_id=...] [service_id=...]
                       [calculation_type=fixed] [currency=KZT] [status=active]

    Read-only, bounded, filtered list of Commercial Milestone Templates.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    try:
        from business_core.payment_manager import list_commercial_milestone_templates

        templates = list_commercial_milestone_templates(
            roadmap_template_id=args.get("roadmap_template_id", ""), service_id=args.get("service_id", ""),
            status=args.get("status", ""),
        )
        for key, field in (("calculation_type", "Calculation Type"), ("currency", "Currency")):
            if args.get(key):
                templates = [t for t in templates if t.get(field, "") == args[key]]

        if not templates:
            await _reply(update, "ℹ️ Commercial Milestone Templates не найдены.", parse_mode=None)
            return

        lines = [f"💰 Commercial Milestone Templates ({len(templates)})", ""]
        for t in templates[:_PAYMENT_LIST_MAX_SHOWN]:
            amount_display = t.get("Fixed Amount") or (f"{t.get('Percentage', '')}%" if t.get("Percentage") else "—")
            lines.append(
                f"{t.get('Commercial Milestone Template ID', '')} — {t.get('Title', '')} "
                f"[{_payment_template_status_ru(t.get('Status', ''))}] "
                f"{_payment_calculation_type_ru(t.get('Calculation Type', ''))}: {amount_display} {t.get('Currency', '')}"
            )
        if len(templates) > _PAYMENT_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_PAYMENT_LIST_MAX_SHOWN} из {len(templates)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"paymenttemplates_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Commercial Milestone Templates.", parse_mode=None)


async def paymenttemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /paymenttemplate commercial_milestone_template_id=PMT-001

    Read-only, exact-ID detail. Hides Notes by default.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    template_id = args.get("commercial_milestone_template_id") or args.get("_pos0", "")

    if not template_id:
        await _reply(update, "❌ Укажи commercial_milestone_template_id.\n\nПример: /paymenttemplate commercial_milestone_template_id=PMT-001", parse_mode=None)
        return

    try:
        from business_core.payment_manager import find_commercial_milestone_template_by_id

        template = find_commercial_milestone_template_by_id(template_id)
        if template is None:
            await _reply(update, f"❌ Commercial Milestone Template {template_id} не найден.", parse_mode=None)
            return

        amount_display = template.get("Fixed Amount") or (f"{template.get('Percentage', '')}%" if template.get("Percentage") else "—")
        lines = [
            f"💰 Commercial Milestone Template {template.get('Commercial Milestone Template ID', '')}",
            "",
            f"Название: {template.get('Title', '')}",
            f"Sequence: {template.get('Sequence', '')}",
            f"Тип расчёта: {_payment_calculation_type_ru(template.get('Calculation Type', ''))}",
            f"Сумма/процент: {amount_display}",
            f"Валюта: {template.get('Currency', '')}",
            f"Статус: {_payment_template_status_ru(template.get('Status', ''))}",
            f"Roadmap Template: {template.get('Roadmap Template ID', '') or '—'}",
            f"Service: {template.get('Service ID', '') or '—'}",
        ]
        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"paymenttemplate_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Commercial Milestone Template.", parse_mode=None)


async def updatepaymenttemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatepaymenttemplate commercial_milestone_template_id=PMT-001 status=inactive
    /updatepaymenttemplate commercial_milestone_template_id=PMT-001 description=...

    Status and descriptive-admin fields are never mixed in one call —
    mirrors /updatechecklist's foundation UX exactly.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    template_id = args.get("commercial_milestone_template_id", "")

    if not template_id:
        await _reply(
            update,
            "❌ Укажи commercial_milestone_template_id.\n\nПример:\n"
            "`/updatepaymenttemplate commercial_milestone_template_id=PMT-001 status=inactive`\n"
            "`/updatepaymenttemplate commercial_milestone_template_id=PMT-001 description=...`", parse_mode=None)
        return

    has_status = "status" in args
    admin_fields = {}
    for key, header in (("description", "Description"), ("trigger_description", "Trigger Description"), ("notes", "Notes")):
        if key in args:
            admin_fields[header] = args[key]

    if has_status and admin_fields:
        await _reply(
            update,
            "❌ Нельзя одновременно менять статус и описательные поля.\n"
            "Отправь две отдельные команды:\n"
            "`/updatepaymenttemplate commercial_milestone_template_id=... status=...`\n"
            "`/updatepaymenttemplate commercial_milestone_template_id=... description=...`", parse_mode=None)
        return

    if not has_status and not admin_fields:
        await _reply(update, "❌ Укажи либо status=..., либо description=.../trigger_description=.../notes=....", parse_mode=None)
        return

    try:
        if has_status:
            from business_core.business_builder import transition_commercial_milestone_template_status
            result = transition_commercial_milestone_template_status(template_id, args["status"])
            await _reply(update, _payment_template_status_message(result, template_id), parse_mode=None)
            return

        from business_core.business_builder import update_commercial_milestone_template_admin_fields
        result = update_commercial_milestone_template_admin_fields(template_id, admin_fields)
        await _reply(update, _payment_template_admin_message(result, template_id), parse_mode=None)
    except Exception as e:
        log.error(f"updatepaymenttemplate_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Commercial Milestone Template.", parse_mode=None)


async def newobligation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newobligation business_id=BIZ-001 client_id=PRS-001 amount=500000 currency=KZT
                    caller_idempotency_key=...
                    [object_id=...] [service_id=...] [roadmap_id=...] [stage_id=...]
                    [commercial_milestone_template_id=PMT-...] [title=...] [description=...]
                    [due_date=YYYY-MM-DD] [created_by=...] [notes=...]

    Creates one Payment Obligation. Idempotent via caller_idempotency_key
    (ADR-022 §16) — repeated calls with the same key reuse the existing
    Obligation rather than creating a duplicate.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    client_id = args.get("client_id", "")
    amount = args.get("amount", "")
    currency = args.get("currency", "")

    if not business_id or not client_id or not amount or not currency:
        await _reply(
            update,
            "❌ Укажи business_id, client_id, amount и currency.\n\nПример:\n"
            "`/newobligation business_id=BIZ-001 client_id=PRS-001 amount=500000 currency=KZT "
            "caller_idempotency_key=...`", parse_mode=None)
        return

    if not args.get("caller_idempotency_key") and not (
        args.get("commercial_milestone_template_id") and args.get("roadmap_id")
        and args.get("stage_id") and args.get("obligation_sequence")
    ):
        await _reply(
            update,
            "❌ Укажи caller_idempotency_key, либо полностью commercial_milestone_template_id+"
            "roadmap_id+stage_id+obligation_sequence.", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_payment_obligation

        result = create_payment_obligation(
            business_id, client_id, amount, currency,
            object_id=args.get("object_id", ""), service_id=args.get("service_id", ""),
            roadmap_id=args.get("roadmap_id", ""), stage_id=args.get("stage_id", ""),
            commercial_milestone_template_id=args.get("commercial_milestone_template_id", ""),
            caller_idempotency_key=args.get("caller_idempotency_key", ""),
            title=args.get("title", ""), description=args.get("description", ""),
            due_date=args.get("due_date", ""),
            created_by=args.get("created_by", "") or _telegram_username(update),
            notes=args.get("notes", ""), obligation_sequence=args.get("obligation_sequence", ""),
        )
        await _reply(update, _payment_obligation_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"newobligation_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Payment Obligation.", parse_mode=None)


async def obligations_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /obligations [business_id=...] [client_id=...] [object_id=...] [service_id=...]
                 [roadmap_id=...] [stage_id=...] [commercial_milestone_template_id=...]
                 [status=...] [currency=...]

    Read-only, bounded, filtered list of Payment Obligations. Never
    shows Notes.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    try:
        from business_core.payment_manager import list_payment_obligations

        obligations = list_payment_obligations(business_id=args.get("business_id", ""), status=args.get("status", ""))
        for key, field in (
            ("client_id", "Client ID"), ("object_id", "Object ID"), ("service_id", "Service ID"),
            ("roadmap_id", "Roadmap ID"), ("stage_id", "Stage ID"),
            ("commercial_milestone_template_id", "Commercial Milestone Template ID"),
            ("currency", "Currency"),
        ):
            if args.get(key):
                obligations = [o for o in obligations if o.get(field, "") == args[key]]

        if not obligations:
            await _reply(update, "ℹ️ Payment Obligations не найдены.", parse_mode=None)
            return

        lines = [f"💰 Payment Obligations ({len(obligations)})", ""]
        for o in obligations[:_PAYMENT_LIST_MAX_SHOWN]:
            lines.append(
                f"{o.get('Payment Obligation ID', '')} — {o.get('Title Snapshot', '') or '—'} "
                f"[{_payment_obligation_status_ru(o.get('Status', ''))}] "
                f"{_format_payment_amount(o.get('Paid Amount', ''), o.get('Currency', ''))}/"
                f"{_format_payment_amount(o.get('Obligation Amount', ''), '')} "
                f"Client: {o.get('Client ID', '')}"
            )
        if len(obligations) > _PAYMENT_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_PAYMENT_LIST_MAX_SHOWN} из {len(obligations)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"obligations_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Payment Obligations.", parse_mode=None)


_OBLIGATION_TRANSACTIONS_MAX_SHOWN = 20


async def obligation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /obligation payment_obligation_id=POB-001

    Read-only, exact-ID detail + bounded Transaction summary. Hides
    Notes, Payment Method, External Transaction ID, and Evidence
    Document content.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    obligation_id = args.get("payment_obligation_id") or args.get("_pos0", "")

    if not obligation_id:
        await _reply(update, "❌ Укажи payment_obligation_id.\n\nПример: /obligation payment_obligation_id=POB-001", parse_mode=None)
        return

    try:
        from business_core.payment_manager import find_payment_obligation_by_id, list_payment_transactions

        obligation = find_payment_obligation_by_id(obligation_id)
        if obligation is None:
            await _reply(update, f"❌ Payment Obligation {obligation_id} не найден.", parse_mode=None)
            return

        transactions = list_payment_transactions(payment_obligation_id=obligation_id)
        currency = obligation.get("Currency", "")

        lines = [
            f"💰 Payment Obligation {obligation.get('Payment Obligation ID', '')}",
            "",
            f"Название: {obligation.get('Title Snapshot', '') or '—'}",
            f"Client: {obligation.get('Client ID', '')}",
            f"Сумма: {_format_payment_amount(obligation.get('Obligation Amount', ''), currency)}",
            f"Оплачено: {_format_payment_amount(obligation.get('Paid Amount', ''), currency)}",
            f"Остаток: {_format_payment_amount(obligation.get('Remaining Amount', ''), currency)}",
            f"Статус: {_payment_obligation_status_ru(obligation.get('Status', ''))}",
            f"Due Date: {obligation.get('Due Date', '') or '—'}",
            f"Roadmap: {obligation.get('Roadmap ID', '') or '—'}",
            f"Stage: {obligation.get('Stage ID', '') or '—'}",
            f"Template: {obligation.get('Commercial Milestone Template ID', '') or '—'}",
            "",
            f"Payments: {len(transactions)}",
        ]
        for t in transactions[:_OBLIGATION_TRANSACTIONS_MAX_SHOWN]:
            lines.append(
                f"  {t.get('Payment Transaction ID', '')} "
                f"[{_payment_transaction_status_ru(t.get('Status', ''))}] "
                f"{_format_payment_amount(t.get('Amount', ''), t.get('Currency', ''))} "
                f"({t.get('Payment Date', '')})"
            )
        if len(transactions) > _OBLIGATION_TRANSACTIONS_MAX_SHOWN:
            lines.append(f"  … показаны первые {_OBLIGATION_TRANSACTIONS_MAX_SHOWN} из {len(transactions)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"obligation_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Payment Obligation.", parse_mode=None)


async def updateobligation_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updateobligation payment_obligation_id=POB-001 status=issued
    /updateobligation payment_obligation_id=POB-001 notes=...

    Status and Notes are never mixed in one call.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    obligation_id = args.get("payment_obligation_id", "")

    if not obligation_id:
        await _reply(
            update,
            "❌ Укажи payment_obligation_id.\n\nПример:\n"
            "`/updateobligation payment_obligation_id=POB-001 status=issued`\n"
            "`/updateobligation payment_obligation_id=POB-001 notes=...`", parse_mode=None)
        return

    has_status = "status" in args
    has_notes = "notes" in args

    if has_status and has_notes:
        await _reply(
            update,
            "❌ Нельзя одновременно менять статус и Notes.\n"
            "Отправь две отдельные команды:\n"
            "`/updateobligation payment_obligation_id=... status=...`\n"
            "`/updateobligation payment_obligation_id=... notes=...`", parse_mode=None)
        return

    if not has_status and not has_notes:
        await _reply(update, "❌ Укажи либо status=..., либо notes=....", parse_mode=None)
        return

    try:
        if has_status:
            from business_core.business_builder import transition_payment_obligation_status
            result = transition_payment_obligation_status(obligation_id, args["status"])
            await _reply(update, _payment_obligation_status_message(result, obligation_id), parse_mode=None)
            return

        from business_core.business_builder import update_payment_obligation_admin_fields
        result = update_payment_obligation_admin_fields(obligation_id, {"Notes": args["notes"]})
        await _reply(update, _payment_obligation_admin_message(result, obligation_id), parse_mode=None)
    except Exception as e:
        log.error(f"updateobligation_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Payment Obligation.", parse_mode=None)


async def recordpayment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /recordpayment business_id=BIZ-001 payment_obligation_id=POB-001 client_id=PRS-001
                    amount=250000 currency=KZT payment_date=YYYY-MM-DD
                    [external_transaction_id=...] [caller_idempotency_key=...]
                    [payment_method=...] [evidence_document_id=DREG-...]
                    [created_by=...] [notes=...]

    Records one pending Payment Transaction. Never auto-confirms — use
    /confirmpayment separately (ADR-022 §15/§20).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    obligation_id = args.get("payment_obligation_id", "")
    client_id = args.get("client_id", "")
    amount = args.get("amount", "")
    currency = args.get("currency", "")
    payment_date = args.get("payment_date", "")

    if not business_id or not obligation_id or not client_id or not amount or not currency or not payment_date:
        await _reply(
            update,
            "❌ Укажи business_id, payment_obligation_id, client_id, amount, currency и payment_date.\n\n"
            "Пример:\n`/recordpayment business_id=BIZ-001 payment_obligation_id=POB-001 client_id=PRS-001 "
            "amount=250000 currency=KZT payment_date=2026-01-15 external_transaction_id=...`", parse_mode=None)
        return

    if not args.get("external_transaction_id") and not args.get("caller_idempotency_key"):
        await _reply(update, "❌ Укажи external_transaction_id или caller_idempotency_key.", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_payment_transaction

        result = create_payment_transaction(
            business_id, obligation_id, client_id, amount, currency, payment_date,
            payment_method=args.get("payment_method", ""),
            external_transaction_id=args.get("external_transaction_id", ""),
            caller_idempotency_key=args.get("caller_idempotency_key", ""),
            evidence_document_id=args.get("evidence_document_id", ""),
            created_by=args.get("created_by", "") or _telegram_username(update),
            notes=args.get("notes", ""),
        )
        await _reply(update, _payment_transaction_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"recordpayment_cmd error: {e}")
        await _reply(update, "❌ Не удалось записать Payment.", parse_mode=None)


async def payments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /payments [business_id=...] [payment_obligation_id=...] [client_id=...]
              [status=...] [currency=...] [evidence_document_id=...]

    Read-only, bounded, filtered list of Payment Transactions. Never
    shows Notes, Payment Method, External Transaction ID, or Caller
    Idempotency Key.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    try:
        from business_core.payment_manager import list_payment_transactions

        transactions = list_payment_transactions(
            payment_obligation_id=args.get("payment_obligation_id", ""), status=args.get("status", ""),
        )
        for key, field in (
            ("business_id", "Business ID"), ("client_id", "Client ID"),
            ("currency", "Currency"), ("evidence_document_id", "Evidence Document ID"),
        ):
            if args.get(key):
                transactions = [t for t in transactions if t.get(field, "") == args[key]]

        if not transactions:
            await _reply(update, "ℹ️ Payments не найдены.", parse_mode=None)
            return

        lines = [f"💰 Payments ({len(transactions)})", ""]
        for t in transactions[:_PAYMENT_LIST_MAX_SHOWN]:
            lines.append(
                f"{t.get('Payment Transaction ID', '')} — Obligation: {t.get('Payment Obligation ID', '')} "
                f"[{_payment_transaction_status_ru(t.get('Status', ''))}] "
                f"{_format_payment_amount(t.get('Amount', ''), t.get('Currency', ''))} "
                f"({t.get('Payment Date', '')})"
            )
        if len(transactions) > _PAYMENT_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_PAYMENT_LIST_MAX_SHOWN} из {len(transactions)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"payments_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Payments.", parse_mode=None)


async def payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /payment payment_transaction_id=PTXN-001

    Read-only, exact-ID detail. Hides External Transaction ID, Caller
    Idempotency Key, Notes, Payment Method, and Reversal Reason.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    transaction_id = args.get("payment_transaction_id") or args.get("_pos0", "")

    if not transaction_id:
        await _reply(update, "❌ Укажи payment_transaction_id.\n\nПример: /payment payment_transaction_id=PTXN-001", parse_mode=None)
        return

    try:
        from business_core.payment_manager import find_payment_transaction_by_id

        txn = find_payment_transaction_by_id(transaction_id)
        if txn is None:
            await _reply(update, f"❌ Payment {transaction_id} не найден.", parse_mode=None)
            return

        lines = [
            f"💰 Payment {txn.get('Payment Transaction ID', '')}",
            "",
            f"Obligation: {txn.get('Payment Obligation ID', '')}",
            f"Client: {txn.get('Client ID', '')}",
            f"Сумма: {_format_payment_amount(txn.get('Amount', ''), txn.get('Currency', ''))}",
            f"Дата платежа: {txn.get('Payment Date', '')}",
            f"Статус: {_payment_transaction_status_ru(txn.get('Status', ''))}",
        ]
        if txn.get("Evidence Document ID"):
            lines.append(f"Evidence Document: {txn['Evidence Document ID']}")
        if txn.get("Confirmed At"):
            lines.append(f"Подтверждён: {txn['Confirmed At']}")
        if txn.get("Reversed At"):
            lines.append(f"Реверснут: {txn['Reversed At']}")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"payment_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Payment.", parse_mode=None)


async def confirmpayment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /confirmpayment payment_transaction_id=PTXN-001 confirmed_by=...

    Confirms one pending Payment Transaction. Synchronizes the parent
    Obligation's balance/status automatically (ADR-022 §20).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    transaction_id = args.get("payment_transaction_id", "")
    confirmed_by = args.get("confirmed_by", "") or _telegram_username(update)

    if not transaction_id or not confirmed_by:
        await _reply(
            update,
            "❌ Укажи payment_transaction_id и confirmed_by.\n\nПример:\n"
            "`/confirmpayment payment_transaction_id=PTXN-001 confirmed_by=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import confirm_payment_transaction

        result = confirm_payment_transaction(transaction_id, confirmed_by)
        await _reply(update, _payment_transaction_confirmation_message(result, transaction_id), parse_mode=None)
    except Exception as e:
        log.error(f"confirmpayment_cmd error: {e}")
        await _reply(update, "❌ Не удалось подтвердить Payment.", parse_mode=None)


async def reversepayment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reversepayment payment_transaction_id=PTXN-001 reversal_reason=... reversed_by=...

    Reverses one confirmed Payment Transaction — status-based, on the
    original row (ADR-022 §13/§19). Never logs reversal_reason verbatim.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    transaction_id = args.get("payment_transaction_id", "")
    reversal_reason = args.get("reversal_reason", "")
    reversed_by = args.get("reversed_by", "") or _telegram_username(update)

    if not transaction_id or not reversal_reason or not reversed_by:
        await _reply(
            update,
            "❌ Укажи payment_transaction_id, reversal_reason и reversed_by.\n\nПример:\n"
            "`/reversepayment payment_transaction_id=PTXN-001 reversal_reason=... reversed_by=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import reverse_payment_transaction

        result = reverse_payment_transaction(transaction_id, reversal_reason, reversed_by)
        await _reply(update, _payment_transaction_reversal_message(result, transaction_id), parse_mode=None)
    except Exception as e:
        log.error(f"reversepayment_cmd error: {e}")
        await _reply(update, "❌ Не удалось реверснуть Payment.", parse_mode=None)


async def failpayment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /failpayment payment_transaction_id=PTXN-001

    Marks one pending Payment Transaction as failed — never affects
    Obligation balance.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    transaction_id = args.get("payment_transaction_id") or args.get("_pos0", "")

    if not transaction_id:
        await _reply(update, "❌ Укажи payment_transaction_id.\n\nПример: /failpayment payment_transaction_id=PTXN-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import fail_payment_transaction

        result = fail_payment_transaction(transaction_id)
        await _reply(update, _payment_transaction_failure_message(result, transaction_id), parse_mode=None)
    except Exception as e:
        log.error(f"failpayment_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Payment.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Phase 40D (ADR-023): Commercial Offer Domain caller (Telegram) UX.
#
# Every command below is a thin resolve-args -> call-canonical-
# orchestration -> render-message wrapper — no business logic beyond
# what business_builder/offer_manager already returns. Centralized
# result-code -> Russian message mapping below mirrors the Phase 39D
# Payment / Phase 38D Checklist UX pattern exactly.
# ─────────────────────────────────────────────────────────────

_OFFER_STATUS_RU: dict[str, str] = {
    "draft": "Черновик", "sent": "Отправлен", "accepted": "Принят",
    "rejected": "Отклонён", "expired": "Истёк", "cancelled": "Отменён", "archived": "В архиве",
}


def _offer_status_ru(status: str) -> str:
    return f"{_OFFER_STATUS_RU.get(status, status)} ({status})"


def _format_offer_amount(amount: str, currency: str) -> str:
    """Caller-only display formatting. Never recomputes — renders
    exactly the canonical Decimal string Foundation already produced,
    alongside its currency."""
    amount = amount or "—"
    currency = currency or ""
    return f"{amount} {currency}".strip()


def _offer_creation_message(result: dict) -> str:
    """Render any business_builder.create_commercial_offer() result."""
    code = result.get("code", "")

    if code == "COMMERCIAL_OFFER_CREATED":
        lines = [
            "✅ Commercial Offer создан",
            f"OFR ID: {result.get('commercial_offer_id', '')}",
            f"Series ID: {result.get('offer_series_id', '')}",
            f"Версия: {result.get('version_number', '')}",
            f"Сумма: {_format_offer_amount(result.get('amount', ''), result.get('currency', ''))}",
            f"Действителен до: {result.get('valid_until', '')}",
            f"Статус: {_offer_status_ru(result.get('final_status', ''))}",
        ]
        return "\n".join(lines)

    if code == "COMMERCIAL_OFFER_REUSED":
        return "\n".join([
            "♻️ Commercial Offer с этим ключом уже существует — использована существующая запись",
            f"OFR ID: {result.get('commercial_offer_id', '')}",
            f"Статус: {_offer_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "CLIENT_NOT_FOUND":
        return f"❌ Client не найден: {result.get('error') or ''}"

    if code == "OBJECT_NOT_FOUND":
        return "❌ Указанный Object не найден."

    if code == "SERVICE_NOT_FOUND":
        return "❌ Указанный Service не найден."

    if code == "ROADMAP_NOT_FOUND":
        return "❌ Указанный Roadmap не найден."

    if code == "DOCUMENT_NOT_FOUND":
        return "❌ Указанный Document не найден."

    if code == "COMMERCIAL_OFFER_CONTEXT_REQUIRED":
        return "❌ Требуется хотя бы одно: object_id, service_id или roadmap_id."

    if code == "COMMERCIAL_OFFER_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "COMMERCIAL_OFFER_TITLE_REQUIRED":
        return "❌ Укажи title (не более 300 символов)."

    if code == "COMMERCIAL_OFFER_SCOPE_REQUIRED":
        return "❌ Укажи scope (не более 10000 символов)."

    if code in ("INVALID_COMMERCIAL_OFFER_AMOUNT", "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE", "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE"):
        return f"❌ {result.get('error') or 'Недопустимая сумма.'}"

    if code == "INVALID_COMMERCIAL_OFFER_CURRENCY":
        return f"❌ {result.get('error') or 'Недопустимая валюта.'}"

    if code == "INVALID_COMMERCIAL_OFFER_VALID_UNTIL":
        return f"❌ {result.get('error') or 'Недопустимая дата valid_until.'}"

    if code == "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST":
        return f"❌ {result.get('error') or 'valid_until не может быть в прошлом.'}"

    if code == "COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED":
        return "❌ Укажи caller_idempotency_key."

    if code == "MULTIPLE_COMMERCIAL_OFFER_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Commercial Offer с одним ключом: {ids}",
            "Новый Offer не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "COMMERCIAL_OFFER_PERSISTENCE_FAILED":
        return "❌ Не удалось создать Commercial Offer."

    if code == "COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Commercial Offer записан, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    if not code and result.get("error"):
        return f"❌ {result['error']}"

    log.warning(f"_offer_creation_message: unmapped code={code!r}")
    return "❌ Не удалось создать Commercial Offer."


def _offer_revision_message(result: dict) -> str:
    """Render any business_builder.revise_commercial_offer() result."""
    code = result.get("code", "")

    if code == "COMMERCIAL_OFFER_REVISED":
        return "\n".join([
            "✅ Создана новая версия Commercial Offer",
            f"Новый OFR ID: {result.get('commercial_offer_id', '')}",
            f"Series ID: {result.get('offer_series_id', '')}",
            f"Версия: {result.get('version_number', '')}",
            f"Предыдущая версия: {result.get('previous_commercial_offer_id', '')}",
            f"Статус: {_offer_status_ru(result.get('final_status', ''))}",
        ])

    if code == "COMMERCIAL_OFFER_REUSED":
        return "\n".join([
            "♻️ Revision с этим ключом уже существует — использована существующая запись",
            f"OFR ID: {result.get('commercial_offer_id', '')}",
        ])

    if code == "COMMERCIAL_OFFER_NOT_FOUND":
        return "❌ Указанный source_commercial_offer_id не найден."

    if code == "COMMERCIAL_OFFER_NOT_LATEST_VERSION":
        return "\n".join([
            "🔒 Указанная версия не является последней в серии",
            "Revision возможен только от последней версии.",
        ])

    if code == "COMMERCIAL_OFFER_SERIES_INTEGRITY_ERROR":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности серии",
            f"Уже существует ревизия(и): {ids}",
        ])

    if code == "COMMERCIAL_OFFER_IDEMPOTENCY_REQUIRED":
        return "❌ Укажи caller_idempotency_key."

    if code == "MULTIPLE_COMMERCIAL_OFFER_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return f"⚠️ Найдено несколько Commercial Offer с одним ключом: {ids}"

    if code in (
        "INVALID_COMMERCIAL_OFFER_AMOUNT", "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE", "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE",
        "INVALID_COMMERCIAL_OFFER_CURRENCY", "INVALID_COMMERCIAL_OFFER_VALID_UNTIL", "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST",
        "COMMERCIAL_OFFER_TITLE_REQUIRED", "COMMERCIAL_OFFER_SCOPE_REQUIRED",
        "BUSINESS_NOT_FOUND", "CLIENT_NOT_FOUND", "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND", "ROADMAP_NOT_FOUND",
        "DOCUMENT_NOT_FOUND", "COMMERCIAL_OFFER_CONTEXT_REQUIRED", "COMMERCIAL_OFFER_RELATION_MISMATCH",
    ):
        return f"❌ {result.get('error') or 'Проверьте параметры revision.'}"

    if code == "COMMERCIAL_OFFER_PERSISTENCE_FAILED":
        return "❌ Не удалось создать новую версию Commercial Offer."

    if code == "COMMERCIAL_OFFER_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Revision записана, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    log.warning(f"_offer_revision_message: unmapped code={code!r}")
    return "❌ Не удалось создать revision Commercial Offer."


def _offer_update_message(result: dict, offer_id: str) -> str:
    """Render any business_builder.update_commercial_offer_draft()/
    update_commercial_offer_admin_fields() result."""
    code = result.get("code", "")

    if code == "COMMERCIAL_OFFER_UPDATED":
        return f"✅ Commercial Offer {offer_id} обновлён."

    if code == "COMMERCIAL_OFFER_UPDATE_UNCHANGED":
        return f"ℹ️ Commercial Offer {offer_id} — изменений нет (значения совпадают)."

    if code == "COMMERCIAL_OFFER_NOT_FOUND":
        return f"❌ Commercial Offer {offer_id} не найден."

    if code == "COMMERCIAL_OFFER_IMMUTABLE":
        return f"❌ {result.get('error') or 'Изменение недоступно — поле неизменяемо или Offer не в статусе draft.'}"

    if code in (
        "INVALID_COMMERCIAL_OFFER_AMOUNT", "INVALID_COMMERCIAL_OFFER_AMOUNT_SCALE", "COMMERCIAL_OFFER_AMOUNT_MUST_BE_POSITIVE",
        "INVALID_COMMERCIAL_OFFER_CURRENCY", "INVALID_COMMERCIAL_OFFER_VALID_UNTIL", "COMMERCIAL_OFFER_VALID_UNTIL_IN_PAST",
        "COMMERCIAL_OFFER_TITLE_REQUIRED", "COMMERCIAL_OFFER_SCOPE_REQUIRED",
        "OBJECT_NOT_FOUND", "SERVICE_NOT_FOUND", "ROADMAP_NOT_FOUND", "DOCUMENT_NOT_FOUND", "COMMERCIAL_OFFER_RELATION_MISMATCH",
    ):
        return f"❌ {result.get('error') or 'Проверьте параметры обновления.'}"

    log.warning(f"_offer_update_message: unmapped code={code!r} offer_id={offer_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _offer_lifecycle_message(result: dict, offer_id: str, action_label: str) -> str:
    """
    Shared renderer for send/accept/reject/expire/cancel/archive
    results — all share the same underlying _transition_commercial_
    offer() code family plus one action-specific success code.
    `action_label` is the past-tense Russian verb for the success line
    (e.g. "отправлен", "принят") — acceptance intentionally never
    implies payment received, invoice issued, or contract signed
    (ADR-023 §21/Phase 40D §9): only "коммерческие условия приняты".
    """
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    success_codes = {
        "COMMERCIAL_OFFER_SENT": "✅ Commercial Offer отправлен",
        "COMMERCIAL_OFFER_ACCEPTED": "✅ Коммерческие условия приняты",
        "COMMERCIAL_OFFER_REJECTED": "✅ Commercial Offer отклонён",
        "COMMERCIAL_OFFER_EXPIRED": "✅ Commercial Offer помечен как истёкший",
        "COMMERCIAL_OFFER_CANCELLED": "✅ Commercial Offer отменён",
        "COMMERCIAL_OFFER_ARCHIVED": "✅ Commercial Offer архивирован",
    }
    if code in success_codes:
        return "\n".join([
            success_codes[code],
            f"OFR ID: {offer_id}",
            f"Был: {_offer_status_ru(previous_status)}",
            f"Стал: {_offer_status_ru(result.get('final_status', ''))}",
        ])

    if code == "COMMERCIAL_OFFER_STATUS_UNCHANGED":
        return f"ℹ️ Commercial Offer {offer_id} уже имеет статус {_offer_status_ru(previous_status)} — изменений нет."

    if code == "COMMERCIAL_OFFER_NOT_FOUND":
        return f"❌ Commercial Offer {offer_id} не найден."

    if code == "INVALID_COMMERCIAL_OFFER_TRANSITION":
        return f"❌ Переход '{previous_status}' → '{requested_status}' не разрешён."

    if code == "COMMERCIAL_OFFER_NOT_LATEST_VERSION":
        return "\n".join([
            "🔒 Commercial Offer не является последней версией серии",
            f"OFR ID: {offer_id}",
            f"Действие {action_label} возможно только для последней версии.",
        ])

    if code == "COMMERCIAL_OFFER_ACTOR_REQUIRED":
        return f"❌ {result.get('error') or 'Укажи ответственного (actor).'}"

    if code == "COMMERCIAL_OFFER_REJECTION_REASON_REQUIRED":
        return "❌ Укажи rejection_reason."

    if code == "COMMERCIAL_OFFER_CANCELLATION_REASON_REQUIRED":
        return "❌ Укажи cancellation_reason."

    if code == "COMMERCIAL_OFFER_PERSISTENCE_FAILED":
        return f"❌ Не удалось изменить статус Commercial Offer {offer_id}."

    log.warning(f"_offer_lifecycle_message: unmapped code={code!r} offer_id={offer_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


async def newoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newoffer business_id=BIZ-001 client_id=PRS-001 title=... scope=...
              quoted_amount=500000 currency=KZT valid_until=YYYY-MM-DD
              caller_idempotency_key=...
              [object_id=...] [service_id=...] [roadmap_id=...]
              [offer_document_id=...] [created_by=...] [notes=...]

    Creates one version-1 Commercial Offer. Idempotent via
    caller_idempotency_key (ADR-023 §22) — repeated calls with the same
    key reuse the existing Offer rather than creating a duplicate.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    client_id = args.get("client_id", "")
    title = args.get("title", "")
    scope = args.get("scope", "")
    quoted_amount = args.get("quoted_amount", "")
    currency = args.get("currency", "")
    valid_until = args.get("valid_until", "")
    caller_idempotency_key = args.get("caller_idempotency_key", "")

    if not business_id or not client_id or not title or not scope or not quoted_amount or not currency or not valid_until:
        await _reply(
            update,
            "❌ Укажи business_id, client_id, title, scope, quoted_amount, currency и valid_until.\n\nПример:\n"
            "`/newoffer business_id=BIZ-001 client_id=PRS-001 title=... scope=... quoted_amount=500000 "
            "currency=KZT valid_until=2026-12-31 caller_idempotency_key=... service_id=SVC-001`", parse_mode=None)
        return

    if not caller_idempotency_key:
        await _reply(update, "❌ Укажи caller_idempotency_key.", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_commercial_offer

        result = create_commercial_offer(
            business_id, client_id, title, scope, quoted_amount, currency, valid_until,
            object_id=args.get("object_id", ""), service_id=args.get("service_id", ""),
            roadmap_id=args.get("roadmap_id", ""), offer_document_id=args.get("offer_document_id", ""),
            caller_idempotency_key=caller_idempotency_key,
            created_by=args.get("created_by", "") or _telegram_username(update),
            notes=args.get("notes", ""),
        )
        await _reply(update, _offer_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"newoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Commercial Offer.", parse_mode=None)


_OFFERS_LIST_MAX_SHOWN = 20


async def offers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /offers [business_id=...] [client_id=...] [object_id=...] [service_id=...]
            [roadmap_id=...] [offer_series_id=...] [status=...] [currency=...]
            [document_id=...]

    Read-only, bounded, filtered list of Commercial Offers. Archived
    Offers are excluded by default unless status=archived is explicit.
    Never shows Scope Snapshot, Notes, Rejection Reason, or Cancellation
    Reason.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    status_filter = args.get("status", "")

    try:
        from business_core.offer_manager import list_commercial_offers

        offers = list_commercial_offers(
            business_id=args.get("business_id", ""), client_id=args.get("client_id", ""),
            object_id=args.get("object_id", ""), service_id=args.get("service_id", ""),
            roadmap_id=args.get("roadmap_id", ""), offer_series_id=args.get("offer_series_id", ""),
            status=status_filter, currency=args.get("currency", ""), document_id=args.get("document_id", ""),
        )
        if not status_filter:
            offers = [o for o in offers if o.get("Status", "") != "archived"]

        if not offers:
            await _reply(update, "ℹ️ Commercial Offers не найдены.", parse_mode=None)
            return

        lines = [f"📄 Commercial Offers ({len(offers)})", ""]
        for o in offers[:_OFFERS_LIST_MAX_SHOWN]:
            lines.append(
                f"{o.get('Commercial Offer ID', '')} (v{o.get('Version Number', '')}) — {o.get('Title Snapshot', '')} "
                f"[{_offer_status_ru(o.get('Status', ''))}] "
                f"{_format_offer_amount(o.get('Quoted Amount', ''), o.get('Currency', ''))} "
                f"Client: {o.get('Client ID', '')}"
            )
        if len(offers) > _OFFERS_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_OFFERS_LIST_MAX_SHOWN} из {len(offers)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"offers_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Commercial Offers.", parse_mode=None)


_OFFER_SCOPE_DISPLAY_MAX_LENGTH = 500
_OFFER_SERIES_HISTORY_MAX_SHOWN = 10


async def offer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /offer commercial_offer_id=OFR-001

    Read-only, exact-ID detail + bounded version-history summary. Hides
    Notes, Caller Idempotency Key, Rejection Reason, Cancellation
    Reason. Scope Snapshot is bounded to a safe display length.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id") or args.get("_pos0", "")

    if not offer_id:
        await _reply(update, "❌ Укажи commercial_offer_id.\n\nПример: /offer commercial_offer_id=OFR-001", parse_mode=None)
        return

    try:
        from business_core.offer_manager import find_commercial_offer_by_id, list_commercial_offers_by_series
        from business_core.business_builder import is_commercial_offer_effectively_expired

        offer = find_commercial_offer_by_id(offer_id)
        if offer is None:
            await _reply(update, f"❌ Commercial Offer {offer_id} не найден.", parse_mode=None)
            return

        scope = offer.get("Scope Snapshot", "")
        scope_display = scope if len(scope) <= _OFFER_SCOPE_DISPLAY_MAX_LENGTH else scope[:_OFFER_SCOPE_DISPLAY_MAX_LENGTH] + "…"

        lines = [
            f"📄 Commercial Offer {offer.get('Commercial Offer ID', '')}",
            "",
            f"Series: {offer.get('Offer Series ID', '')} (версия {offer.get('Version Number', '')})",
            f"Предыдущая версия: {offer.get('Previous Commercial Offer ID', '') or '—'}",
            f"Business: {offer.get('Business ID', '')}",
            f"Client: {offer.get('Client ID', '')}",
        ]
        for key, label in (("Object ID", "Object"), ("Service ID", "Service"), ("Roadmap ID", "Roadmap"), ("Offer Document ID", "Document")):
            if offer.get(key):
                lines.append(f"{label}: {offer[key]}")
        lines.extend([
            f"Название: {offer.get('Title Snapshot', '')}",
            f"Объём: {scope_display}",
            f"Сумма: {_format_offer_amount(offer.get('Quoted Amount', ''), offer.get('Currency', ''))}",
            f"Действителен до: {offer.get('Valid Until', '')}",
            f"Статус: {_offer_status_ru(offer.get('Status', ''))}",
        ])
        if is_commercial_offer_effectively_expired(offer):
            lines.append("⚠️ Внимание: срок действия истёк (Valid Until в прошлом), но статус ещё не переведён в 'expired'.")
        for key, label in (("Sent At", "Отправлен"), ("Accepted At", "Принят"), ("Rejected At", "Отклонён"), ("Cancelled At", "Отменён"), ("Archived At", "Архивирован")):
            if offer.get(key):
                lines.append(f"{label}: {offer[key]}")

        series = list_commercial_offers_by_series(offer.get("Offer Series ID", ""))
        series_sorted = sorted(series, key=lambda o: int(o.get("Version Number") or 0))
        lines.append("")
        lines.append(f"История версий: {len(series_sorted)}")
        for v in series_sorted[:_OFFER_SERIES_HISTORY_MAX_SHOWN]:
            lines.append(f"  v{v.get('Version Number', '')} — {v.get('Commercial Offer ID', '')} [{_offer_status_ru(v.get('Status', ''))}]")
        if len(series_sorted) > _OFFER_SERIES_HISTORY_MAX_SHOWN:
            lines.append(f"  … показаны первые {_OFFER_SERIES_HISTORY_MAX_SHOWN} из {len(series_sorted)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"offer_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Commercial Offer.", parse_mode=None)


async def reviseoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reviseoffer source_commercial_offer_id=OFR-001 caller_idempotency_key=...
                 [title=...] [scope=...] [quoted_amount=...] [currency=...]
                 [valid_until=...] [object_id=...] [service_id=...]
                 [roadmap_id=...] [offer_document_id=...] [created_by=...] [notes=...]

    Creates a new immutable draft version in the same Offer Series.
    Unspecified commercial fields default from the source version.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    source_id = args.get("source_commercial_offer_id", "")
    caller_idempotency_key = args.get("caller_idempotency_key", "")

    if not source_id or not caller_idempotency_key:
        await _reply(
            update,
            "❌ Укажи source_commercial_offer_id и caller_idempotency_key.\n\nПример:\n"
            "`/reviseoffer source_commercial_offer_id=OFR-001 caller_idempotency_key=... quoted_amount=550000`", parse_mode=None)
        return

    try:
        from business_core.business_builder import revise_commercial_offer

        result = revise_commercial_offer(
            source_id, caller_idempotency_key, args.get("created_by", "") or _telegram_username(update),
            title_snapshot=args.get("title", ""), scope_snapshot=args.get("scope", ""),
            quoted_amount=args.get("quoted_amount"), currency=args.get("currency", ""),
            valid_until=args.get("valid_until", ""),
            object_id=args.get("object_id", ""), service_id=args.get("service_id", ""),
            roadmap_id=args.get("roadmap_id", ""), offer_document_id=args.get("offer_document_id", ""),
            notes=args.get("notes", ""),
        )
        await _reply(update, _offer_revision_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"reviseoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать revision Commercial Offer.", parse_mode=None)


async def updateoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updateoffer commercial_offer_id=OFR-001 quoted_amount=... (draft only)
    /updateoffer commercial_offer_id=OFR-001 notes=... (any status)

    Draft-commercial-field mode and Notes-only mode are mutually
    exclusive — mirrors /updatepaymenttemplate's foundation UX exactly.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id", "")

    if not offer_id:
        await _reply(
            update,
            "❌ Укажи commercial_offer_id.\n\nПример:\n"
            "`/updateoffer commercial_offer_id=OFR-001 quoted_amount=550000`\n"
            "`/updateoffer commercial_offer_id=OFR-001 notes=...`", parse_mode=None)
        return

    draft_field_map = {
        "title": "Title Snapshot", "scope": "Scope Snapshot", "quoted_amount": "Quoted Amount",
        "currency": "Currency", "valid_until": "Valid Until",
        "object_id": "Object ID", "service_id": "Service ID", "roadmap_id": "Roadmap ID",
        "offer_document_id": "Offer Document ID",
    }
    draft_updates = {header: args[key] for key, header in draft_field_map.items() if key in args}
    has_notes = "notes" in args

    if draft_updates and has_notes:
        await _reply(
            update,
            "❌ Нельзя одновременно менять коммерческие поля и Notes.\n"
            "Отправь две отдельные команды:\n"
            "`/updateoffer commercial_offer_id=... quoted_amount=...`\n"
            "`/updateoffer commercial_offer_id=... notes=...`", parse_mode=None)
        return

    if not draft_updates and not has_notes:
        await _reply(update, "❌ Укажи хотя бы одно поле для обновления (например quoted_amount=... или notes=...).", parse_mode=None)
        return

    try:
        if draft_updates:
            from business_core.business_builder import update_commercial_offer_draft
            result = update_commercial_offer_draft(offer_id, draft_updates)
            await _reply(update, _offer_update_message(result, offer_id), parse_mode=None)
            return

        from business_core.business_builder import update_commercial_offer_admin_fields
        result = update_commercial_offer_admin_fields(offer_id, {"Notes": args["notes"]})
        await _reply(update, _offer_update_message(result, offer_id), parse_mode=None)
    except Exception as e:
        log.error(f"updateoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Commercial Offer.", parse_mode=None)


async def sendoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /sendoffer commercial_offer_id=OFR-001 sent_by=...

    draft → sent. Only the latest version in its series may be sent.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id", "")
    sent_by = args.get("sent_by", "") or _telegram_username(update)

    if not offer_id or not sent_by:
        await _reply(update, "❌ Укажи commercial_offer_id и sent_by.\n\nПример:\n`/sendoffer commercial_offer_id=OFR-001 sent_by=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import send_commercial_offer

        result = send_commercial_offer(offer_id, sent_by)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "отправка"), parse_mode=None)
    except Exception as e:
        log.error(f"sendoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось отправить Commercial Offer.", parse_mode=None)


async def acceptoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /acceptoffer commercial_offer_id=OFR-001 accepted_by=...

    sent → accepted. Means only that the commercial terms were
    accepted — never that payment was received, an invoice was issued,
    or a contract was signed (ADR-023 §21). Never creates a Payment
    Obligation.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id", "")
    accepted_by = args.get("accepted_by", "") or _telegram_username(update)

    if not offer_id or not accepted_by:
        await _reply(update, "❌ Укажи commercial_offer_id и accepted_by.\n\nПример:\n`/acceptoffer commercial_offer_id=OFR-001 accepted_by=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import accept_commercial_offer

        result = accept_commercial_offer(offer_id, accepted_by)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "принятие"), parse_mode=None)
    except Exception as e:
        log.error(f"acceptoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось принять Commercial Offer.", parse_mode=None)


async def rejectoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /rejectoffer commercial_offer_id=OFR-001 rejected_by=... rejection_reason=...

    sent → rejected. rejection_reason is never logged.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id", "")
    rejected_by = args.get("rejected_by", "") or _telegram_username(update)
    rejection_reason = args.get("rejection_reason", "")

    if not offer_id or not rejected_by or not rejection_reason:
        await _reply(
            update,
            "❌ Укажи commercial_offer_id, rejected_by и rejection_reason.\n\nПример:\n"
            "`/rejectoffer commercial_offer_id=OFR-001 rejected_by=... rejection_reason=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import reject_commercial_offer

        result = reject_commercial_offer(offer_id, rejected_by, rejection_reason)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "отклонение"), parse_mode=None)
    except Exception as e:
        log.error(f"rejectoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось отклонить Commercial Offer.", parse_mode=None)


async def expireoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /expireoffer commercial_offer_id=OFR-001

    Explicit sent → expired. Never a background/scheduled mutation.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id") or args.get("_pos0", "")

    if not offer_id:
        await _reply(update, "❌ Укажи commercial_offer_id.\n\nПример: /expireoffer commercial_offer_id=OFR-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import expire_commercial_offer

        result = expire_commercial_offer(offer_id)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "истечение срока"), parse_mode=None)
    except Exception as e:
        log.error(f"expireoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Commercial Offer.", parse_mode=None)


async def canceloffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /canceloffer commercial_offer_id=OFR-001 cancelled_by=... cancellation_reason=...

    draft/sent → cancelled. accepted cannot be cancelled.
    cancellation_reason is never logged.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id", "")
    cancelled_by = args.get("cancelled_by", "") or _telegram_username(update)
    cancellation_reason = args.get("cancellation_reason", "")

    if not offer_id or not cancelled_by or not cancellation_reason:
        await _reply(
            update,
            "❌ Укажи commercial_offer_id, cancelled_by и cancellation_reason.\n\nПример:\n"
            "`/canceloffer commercial_offer_id=OFR-001 cancelled_by=... cancellation_reason=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import cancel_commercial_offer

        result = cancel_commercial_offer(offer_id, cancelled_by, cancellation_reason)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "отмена"), parse_mode=None)
    except Exception as e:
        log.error(f"canceloffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось отменить Commercial Offer.", parse_mode=None)


async def archiveoffer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /archiveoffer commercial_offer_id=OFR-001

    Any allowed status → archived. Terminal — no restore.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    offer_id = args.get("commercial_offer_id") or args.get("_pos0", "")

    if not offer_id:
        await _reply(update, "❌ Укажи commercial_offer_id.\n\nПример: /archiveoffer commercial_offer_id=OFR-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import archive_commercial_offer

        result = archive_commercial_offer(offer_id)
        await _reply(update, _offer_lifecycle_message(result, offer_id, "архивирование"), parse_mode=None)
    except Exception as e:
        log.error(f"archiveoffer_cmd error: {e}")
        await _reply(update, "❌ Не удалось архивировать Commercial Offer.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Phase 41D (ADR-024): Lead / Sales Funnel Domain caller (Telegram) UX.
#
# Every command below is a thin resolve-args -> call-canonical-
# orchestration -> render-message wrapper — no business logic beyond
# what business_builder/lead_manager already returns. Centralized
# result-code -> Russian message mapping below mirrors the Phase 40D
# Commercial Offer UX pattern exactly. Contact values (Phone/WhatsApp/
# Email/Contact Name) are never shown in raw form in any reply — only
# through the masking helpers below — and are never logged.
# ─────────────────────────────────────────────────────────────

_LEAD_STATUS_RU: dict[str, str] = {
    "new": "Новый", "contacted": "На связи", "qualified": "Квалифицирован",
    "unqualified": "Не подходит", "converted": "Конвертирован", "lost": "Потерян", "archived": "В архиве",
}


def _lead_status_ru(status: str) -> str:
    return f"{_LEAD_STATUS_RU.get(status, status)} ({status})"


def _mask_lead_phone_like(value: str) -> str:
    """Caller-only masking — preserves at most the final 4 digits,
    never leaks the full number. Used for both Phone and WhatsApp."""
    if not value:
        return ""
    has_plus = value.startswith("+")
    digits = value[1:] if has_plus else value
    if len(digits) <= 4:
        masked = "*" * len(digits)
    else:
        masked = "*" * (len(digits) - 4) + digits[-4:]
    return f"{'+' if has_plus else ''}{masked}"


def _mask_lead_email(value: str) -> str:
    """Caller-only masking — shows only the first local-part character
    plus the domain, never the complete address."""
    if not value or "@" not in value:
        return ""
    local, _, domain = value.partition("@")
    if len(local) <= 1:
        masked_local = local
    else:
        masked_local = local[0] + "*" * (len(local) - 1)
    return f"{masked_local}@{domain}"


def _mask_lead_contact_summary(lead: dict) -> str:
    """Combined masked contact-channel summary for list/detail views —
    never the raw Phone/WhatsApp/Email Snapshot values."""
    parts = []
    phone = lead.get("Phone Snapshot", "")
    whatsapp = lead.get("WhatsApp Snapshot", "")
    email = lead.get("Email Snapshot", "")
    if phone:
        parts.append(f"Тел: {_mask_lead_phone_like(phone)}")
    if whatsapp:
        parts.append(f"WhatsApp: {_mask_lead_phone_like(whatsapp)}")
    if email:
        parts.append(f"Email: {_mask_lead_email(email)}")
    return ", ".join(parts) if parts else "—"


def _mask_lead_contact_name(name: str) -> str:
    """Bounded contact-name display for the exact-ID detail view only
    (/lead) — first name plus a single last-name initial. List views
    (/leads) never show any part of Contact Name Snapshot at all."""
    if not name:
        return "—"
    parts = name.strip().split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0]}."


def _format_lead_expected_value(expected_value: str, currency: str) -> str:
    """Caller-only display formatting. Always labeled as a non-binding
    estimate — never called agreed price, Offer amount, or payable
    amount. Never recomputes; renders exactly the canonical Decimal
    string Foundation already produced."""
    if not expected_value:
        return "—"
    return f"~{expected_value} {currency} (оценка, не является согласованной суммой)".strip()


def _format_lead_follow_up_lines(lead: dict) -> list[str]:
    """Display-only follow-up rendering — never writes, never mutates
    Status. Distinguishes the stored timestamps from the derived
    due-warning (is_lead_follow_up_due())."""
    from business_core.business_builder import is_lead_follow_up_due

    lines = []
    next_follow_up = lead.get("Next Follow-up At", "")
    last_contacted = lead.get("Last Contacted At", "")
    if next_follow_up:
        lines.append(f"Следующее касание: {next_follow_up}")
    if last_contacted:
        lines.append(f"Последний контакт: {last_contacted}")
    if is_lead_follow_up_due(lead):
        lines.append("⏰ Follow-up просрочен")
    return lines


def _lead_duplicate_warning_lines(result: dict) -> list[str]:
    """Duplicate-contact warning — never blocks, never reveals matching
    contact values, never auto-merges, never picks one arbitrarily.
    Discloses every bounded matching Lead ID."""
    duplicate_ids = result.get("duplicate_contact_ids", ())
    if not duplicate_ids:
        return []
    ids = ", ".join(duplicate_ids)
    return ["", f"⚠️ Похожий контакт уже встречается в Lead: {ids}", "Это только предупреждение — новая запись не объединена с ними."]


def _lead_creation_message(result: dict) -> str:
    """Render any business_builder.create_lead() result."""
    code = result.get("code", "")

    if code == "LEAD_CREATED":
        lines = [
            "✅ Lead создан",
            f"Lead ID: {result.get('lead_id', '')}",
            f"Статус: {_lead_status_ru(result.get('final_status', ''))}",
        ]
        if result.get("service_id"):
            lines.append(f"Service: {result['service_id']}")
        if result.get("expected_value"):
            lines.append(f"Ожидаемая сумма: {_format_lead_expected_value(result.get('expected_value', ''), result.get('currency', ''))}")
        lines.extend(_lead_duplicate_warning_lines(result))
        return "\n".join(lines)

    if code == "LEAD_REUSED":
        return "\n".join([
            "♻️ Lead с этим ключом уже существует — использована существующая запись",
            f"Lead ID: {result.get('lead_id', '')}",
            f"Статус: {_lead_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code == "SERVICE_NOT_FOUND":
        return "❌ Указанный Service не найден."

    if code == "CHANNEL_NOT_FOUND":
        return "❌ Указанный Channel не найден."

    if code == "PERSON_NOT_FOUND":
        return "❌ Указанный Assigned Person не найден или архивирован."

    if code == "LEAD_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "LEAD_CONTACT_NAME_REQUIRED":
        return "❌ Укажи contact_name (не более 300 символов)."

    if code == "LEAD_CONTACT_CHANNEL_REQUIRED":
        return "❌ Укажи хотя бы один контактный канал: phone, whatsapp или email."

    if code in ("INVALID_LEAD_PHONE", "INVALID_LEAD_WHATSAPP", "INVALID_LEAD_EMAIL"):
        return f"❌ {result.get('error') or 'Недопустимый контактный канал.'}"

    if code in ("INVALID_LEAD_EXPECTED_VALUE", "INVALID_LEAD_EXPECTED_VALUE_SCALE", "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE"):
        return f"❌ {result.get('error') or 'Недопустимое значение expected_value.'}"

    if code == "INVALID_LEAD_CURRENCY":
        return f"❌ {result.get('error') or 'Недопустимая валюта.'}"

    if code == "INVALID_LEAD_DATETIME":
        return f"❌ {result.get('error') or 'Недопустимая дата/время.'}"

    if code == "LEAD_IDEMPOTENCY_REQUIRED":
        return "❌ Укажи caller_idempotency_key."

    if code == "MULTIPLE_LEAD_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Lead с одним ключом: {ids}",
            "Новый Lead не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "LEAD_PERSISTENCE_FAILED":
        return f"❌ {result.get('error') or 'Не удалось создать Lead.'}"

    if code == "LEAD_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Lead записан, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    if not code and result.get("error"):
        return f"❌ {result['error']}"

    log.warning(f"_lead_creation_message: unmapped code={code!r}")
    return "❌ Не удалось создать Lead."


def _lead_update_message(result: dict, lead_id: str) -> str:
    """Render any business_builder.update_lead()/update_lead_admin_fields() result."""
    code = result.get("code", "")

    if code == "LEAD_UPDATED":
        lines = [f"✅ Lead {lead_id} обновлён."]
        lines.extend(_lead_duplicate_warning_lines(result))
        return "\n".join(lines)

    if code == "LEAD_UPDATE_UNCHANGED":
        return f"ℹ️ Lead {lead_id} — изменений нет (значения совпадают)."

    if code == "LEAD_NOT_FOUND":
        return f"❌ Lead {lead_id} не найден."

    if code == "LEAD_IMMUTABLE":
        return f"❌ {result.get('error') or 'Изменение недоступно — поле неизменяемо или Lead не в активном статусе.'}"

    if code == "LEAD_CONTACT_CHANNEL_REQUIRED":
        return "❌ Укажи хотя бы один контактный канал: phone, whatsapp или email."

    if code in (
        "LEAD_CONTACT_NAME_REQUIRED", "INVALID_LEAD_PHONE", "INVALID_LEAD_WHATSAPP", "INVALID_LEAD_EMAIL",
        "INVALID_LEAD_EXPECTED_VALUE", "INVALID_LEAD_EXPECTED_VALUE_SCALE", "LEAD_EXPECTED_VALUE_MUST_BE_POSITIVE",
        "INVALID_LEAD_CURRENCY", "INVALID_LEAD_DATETIME",
        "SERVICE_NOT_FOUND", "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND", "LEAD_RELATION_MISMATCH",
    ):
        return f"❌ {result.get('error') or 'Проверьте параметры обновления.'}"

    log.warning(f"_lead_update_message: unmapped code={code!r} lead_id={lead_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _lead_lifecycle_message(result: dict, lead_id: str, action_label: str) -> str:
    """
    Shared renderer for contact/qualify/unqualify/lose/archive results —
    all share the same underlying _transition_lead() code family plus
    one action-specific success code.
    """
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")

    success_codes = {
        "LEAD_CONTACTED": "✅ Lead помечен как 'на связи'",
        "LEAD_QUALIFIED": "✅ Lead квалифицирован",
        "LEAD_UNQUALIFIED": "✅ Lead помечен как не подходящий",
        "LEAD_LOST": "✅ Lead помечен как потерянный",
        "LEAD_ARCHIVED": "✅ Lead архивирован",
    }
    if code in success_codes:
        return "\n".join([
            success_codes[code],
            f"Lead ID: {lead_id}",
            f"Был: {_lead_status_ru(previous_status)}",
            f"Стал: {_lead_status_ru(result.get('final_status', ''))}",
        ])

    if code == "LEAD_STATUS_UNCHANGED":
        return f"ℹ️ Lead {lead_id} уже имеет статус {_lead_status_ru(previous_status)} — изменений нет."

    if code == "LEAD_NOT_FOUND":
        return f"❌ Lead {lead_id} не найден."

    if code == "INVALID_LEAD_TRANSITION":
        return f"❌ Переход '{previous_status}' → '{result.get('requested_status', '')}' не разрешён."

    if code == "LEAD_RESTORE_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            f"🔒 Lead {lead_id} находится в терминальном статусе {_lead_status_ru(previous_status)}",
            f"Действие {action_label} не может вернуть его в активную работу.",
        ])

    if code == "LEAD_DISPOSITION_REASON_REQUIRED":
        return "❌ Укажи disposition_reason."

    if code == "INVALID_LEAD_DATETIME":
        return f"❌ {result.get('error') or 'Недопустимая дата/время.'}"

    if code == "LEAD_PERSISTENCE_FAILED":
        return f"❌ Не удалось изменить статус Lead {lead_id}."

    log.warning(f"_lead_lifecycle_message: unmapped code={code!r} lead_id={lead_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _lead_conversion_message(result: dict, lead_id: str) -> str:
    """
    Render any business_builder.convert_lead() result. The success
    message intentionally means only that the Lead is now linked to an
    existing Client and its status is 'converted' — never that a
    Person/Client/Object/Commercial Offer/Payment was created, and
    never a "deal won" implication.
    """
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")

    if code == "LEAD_CONVERTED":
        return "\n".join([
            "✅ Lead связан с существующим Client и переведён в статус 'converted'",
            f"Lead ID: {lead_id}",
            f"Client ID: {result.get('converted_client_id', '')}",
            f"Был: {_lead_status_ru(previous_status)}",
        ])

    if code == "LEAD_STATUS_UNCHANGED":
        return "\n".join([
            f"ℹ️ Lead {lead_id} уже конвертирован в этот же Client — изменений нет.",
            f"Client ID: {result.get('converted_client_id', '')}",
        ])

    if code == "LEAD_CONVERSION_TARGET_CONFLICT":
        return "\n".join([
            f"🔒 Lead {lead_id} уже конвертирован в другой Client",
            f"Текущий Client ID: {result.get('converted_client_id', '')}",
            "Повторная конверсия в другой Client не разрешена.",
        ])

    if code == "LEAD_NOT_FOUND":
        return f"❌ Lead {lead_id} не найден."

    if code == "LEAD_CONVERSION_CLIENT_REQUIRED":
        return "❌ Укажи converted_client_id."

    if code == "LEAD_CONVERSION_ACTOR_REQUIRED":
        return "❌ Укажи converted_by."

    if code == "CLIENT_NOT_FOUND":
        return f"❌ Client не найден: {result.get('error') or ''}"

    if code == "LEAD_RELATION_MISMATCH":
        return f"❌ {result.get('error') or 'Client принадлежит другому Business.'}"

    if code == "INVALID_LEAD_TRANSITION":
        return f"❌ Переход '{previous_status}' → 'converted' не разрешён."

    if code == "LEAD_PERSISTENCE_FAILED":
        return f"❌ Не удалось конвертировать Lead {lead_id}."

    log.warning(f"_lead_conversion_message: unmapped code={code!r} lead_id={lead_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


async def newlead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newlead business_id=BIZ-001 contact_name=... caller_idempotency_key=...
             [phone=...] [whatsapp=...] [email=...] [company=...]
             [service_id=...] [source=...] [channel_id=...]
             [qualification_notes=...] [expected_value=...] [currency=...]
             [next_follow_up_at=...] [last_contacted_at=...]
             [assigned_person_id=...] [created_by=...] [notes=...]

    Creates one Lead. Idempotent via caller_idempotency_key (ADR-024
    §10) — repeated calls with the same key reuse the existing Lead
    rather than creating a duplicate. A duplicate-contact match is only
    ever a warning — it never blocks creation and never auto-merges.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    contact_name = args.get("contact_name", "")
    caller_idempotency_key = args.get("caller_idempotency_key", "")

    if not business_id or not contact_name or not caller_idempotency_key:
        await _reply(
            update,
            "❌ Укажи business_id, contact_name и caller_idempotency_key.\n\nПример:\n"
            "`/newlead business_id=BIZ-001 contact_name=\"Иван Иванов\" phone=+77001234567 "
            "caller_idempotency_key=... service_id=SVC-001`", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_lead

        result = create_lead(
            business_id, contact_name,
            created_by=args.get("created_by", "") or _telegram_username(update),
            caller_idempotency_key=caller_idempotency_key,
            phone_snapshot=args.get("phone", ""), whatsapp_snapshot=args.get("whatsapp", ""),
            email_snapshot=args.get("email", ""), company_snapshot=args.get("company", ""),
            service_id=args.get("service_id", ""), source=args.get("source", ""), channel_id=args.get("channel_id", ""),
            qualification_notes=args.get("qualification_notes", ""),
            expected_value=args.get("expected_value", ""), currency=args.get("currency", ""),
            next_follow_up_at=args.get("next_follow_up_at", ""), last_contacted_at=args.get("last_contacted_at", ""),
            assigned_person_id=args.get("assigned_person_id", ""), notes=args.get("notes", ""),
        )
        await _reply(update, _lead_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"newlead_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Lead.", parse_mode=None)


_LEADS_LIST_MAX_SHOWN = 20


async def leads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /leads [business_id=...] [service_id=...] [channel_id=...]
           [assigned_person_id=...] [converted_client_id=...] [status=...]
           [source=...] [currency=...]

    Read-only, bounded, filtered list of Leads. Archived Leads are
    excluded by default unless status=archived is explicit. Never shows
    Contact Name Snapshot, raw Phone/WhatsApp/Email Snapshot, Company
    Snapshot, Qualification Notes, Disposition Reason, Notes, or Caller
    Idempotency Key — only a masked contact-channel summary.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    status_filter = args.get("status", "")

    try:
        from business_core.lead_manager import list_leads

        leads = list_leads(
            business_id=args.get("business_id", ""), service_id=args.get("service_id", ""),
            channel_id=args.get("channel_id", ""), assigned_person_id=args.get("assigned_person_id", ""),
            converted_client_id=args.get("converted_client_id", ""), status=status_filter,
            source=args.get("source", ""), currency=args.get("currency", ""),
            include_archived=(status_filter == "archived"),
        )

        if not leads:
            await _reply(update, "ℹ️ Leads не найдены.", parse_mode=None)
            return

        lines = [f"📋 Leads ({len(leads)})", ""]
        for lead in leads[:_LEADS_LIST_MAX_SHOWN]:
            entry = f"{lead.get('Lead ID', '')} [{_lead_status_ru(lead.get('Status', ''))}] — {_mask_lead_contact_summary(lead)}"
            if lead.get("Service ID"):
                entry += f" | Service: {lead['Service ID']}"
            if lead.get("Assigned Person ID"):
                entry += f" | Ответственный: {lead['Assigned Person ID']}"
            if lead.get("Expected Value"):
                entry += f" | {_format_lead_expected_value(lead.get('Expected Value', ''), lead.get('Currency', ''))}"
            lines.append(entry)
        if len(leads) > _LEADS_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_LEADS_LIST_MAX_SHOWN} из {len(leads)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"leads_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Leads.", parse_mode=None)


async def lead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /lead lead_id=LED-001

    Read-only, exact-ID detail. Hides raw Phone/WhatsApp/Email
    Snapshot, Company Snapshot, Qualification Notes, Disposition
    Reason, Notes, and Caller Idempotency Key. Contact name shown only
    in bounded form (first name + last-name initial).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id") or args.get("_pos0", "")

    if not lead_id:
        await _reply(update, "❌ Укажи lead_id.\n\nПример: /lead lead_id=LED-001", parse_mode=None)
        return

    try:
        from business_core.lead_manager import find_lead_by_id

        lead = find_lead_by_id(lead_id)
        if lead is None:
            await _reply(update, f"❌ Lead {lead_id} не найден.", parse_mode=None)
            return

        lines = [
            f"📋 Lead {lead.get('Lead ID', '')}",
            "",
            f"Business: {lead.get('Business ID', '')}",
            f"Контакт: {_mask_lead_contact_name(lead.get('Contact Name Snapshot', ''))} ({_mask_lead_contact_summary(lead)})",
            f"Статус: {_lead_status_ru(lead.get('Status', ''))}",
        ]
        for key, label in (("Service ID", "Service"), ("Source", "Источник"), ("Channel ID", "Channel"), ("Assigned Person ID", "Ответственный")):
            if lead.get(key):
                lines.append(f"{label}: {lead[key]}")
        if lead.get("Expected Value"):
            lines.append(f"Ожидаемая сумма: {_format_lead_expected_value(lead.get('Expected Value', ''), lead.get('Currency', ''))}")
        lines.extend(_format_lead_follow_up_lines(lead))
        if lead.get("Converted Client ID"):
            lines.append(f"Конвертирован в Client: {lead['Converted Client ID']}")
            if lead.get("Converted At"):
                lines.append(f"Конвертирован: {lead['Converted At']}")
        lines.append(f"Создан: {lead.get('Created At', '')}")
        if lead.get("Updated At"):
            lines.append(f"Обновлён: {lead['Updated At']}")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"lead_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Lead.", parse_mode=None)


async def updatelead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatelead lead_id=LED-001 phone=... (active status only)
    /updatelead lead_id=LED-001 notes=... (any status)

    Active-field mode and Notes-only mode are mutually exclusive —
    mirrors /updateoffer's Foundation UX exactly.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id", "")

    if not lead_id:
        await _reply(
            update,
            "❌ Укажи lead_id.\n\nПример:\n"
            "`/updatelead lead_id=LED-001 phone=+77001234567`\n"
            "`/updatelead lead_id=LED-001 notes=...`", parse_mode=None)
        return

    active_field_map = {
        "contact_name": "Contact Name Snapshot", "phone": "Phone Snapshot", "whatsapp": "WhatsApp Snapshot",
        "email": "Email Snapshot", "company": "Company Snapshot", "service_id": "Service ID",
        "source": "Source", "channel_id": "Channel ID", "qualification_notes": "Qualification Notes",
        "expected_value": "Expected Value", "currency": "Currency",
        "next_follow_up_at": "Next Follow-up At", "last_contacted_at": "Last Contacted At",
        "assigned_person_id": "Assigned Person ID",
    }
    active_updates = {header: args[key] for key, header in active_field_map.items() if key in args}
    has_notes = "notes" in args

    if active_updates and has_notes:
        await _reply(
            update,
            "❌ Нельзя одновременно менять контактные/коммерческие поля и Notes.\n"
            "Отправь две отдельные команды:\n"
            "`/updatelead lead_id=... phone=...`\n"
            "`/updatelead lead_id=... notes=...`", parse_mode=None)
        return

    if not active_updates and not has_notes:
        await _reply(update, "❌ Укажи хотя бы одно поле для обновления (например phone=... или notes=...).", parse_mode=None)
        return

    try:
        if active_updates:
            from business_core.business_builder import update_lead
            result = update_lead(lead_id, active_updates)
            await _reply(update, _lead_update_message(result, lead_id), parse_mode=None)
            return

        from business_core.business_builder import update_lead_admin_fields
        result = update_lead_admin_fields(lead_id, {"Notes": args["notes"]})
        await _reply(update, _lead_update_message(result, lead_id), parse_mode=None)
    except Exception as e:
        log.error(f"updatelead_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Lead.", parse_mode=None)


async def contactlead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /contactlead lead_id=LED-001 [last_contacted_at=...]

    Explicit allowed → contacted. last_contacted_at is optional — if
    omitted, Last Contacted At is left unchanged (no automatic
    "now" is ever invented by the caller).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id") or args.get("_pos0", "")

    if not lead_id:
        await _reply(update, "❌ Укажи lead_id.\n\nПример: /contactlead lead_id=LED-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import contact_lead

        result = contact_lead(lead_id, last_contacted_at=args.get("last_contacted_at", ""))
        await _reply(update, _lead_lifecycle_message(result, lead_id, "отметка контакта"), parse_mode=None)
    except Exception as e:
        log.error(f"contactlead_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Lead.", parse_mode=None)


async def qualifylead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /qualifylead lead_id=LED-001 [qualification_notes=...]

    Explicit allowed → qualified. Never creates a Commercial Offer,
    never auto-converts, never mutates Service.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id") or args.get("_pos0", "")

    if not lead_id:
        await _reply(update, "❌ Укажи lead_id.\n\nПример: /qualifylead lead_id=LED-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import qualify_lead

        result = qualify_lead(lead_id, qualification_notes=args.get("qualification_notes", ""))
        await _reply(update, _lead_lifecycle_message(result, lead_id, "квалификация"), parse_mode=None)
    except Exception as e:
        log.error(f"qualifylead_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Lead.", parse_mode=None)


async def unqualifylead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /unqualifylead lead_id=LED-001 disposition_reason=...

    Explicit allowed → unqualified. disposition_reason is required and
    is never logged.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id", "")
    disposition_reason = args.get("disposition_reason", "")

    if not lead_id or not disposition_reason:
        await _reply(
            update,
            "❌ Укажи lead_id и disposition_reason.\n\nПример:\n"
            "`/unqualifylead lead_id=LED-001 disposition_reason=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import unqualify_lead

        result = unqualify_lead(lead_id, disposition_reason=disposition_reason)
        await _reply(update, _lead_lifecycle_message(result, lead_id, "отметка 'не подходит'"), parse_mode=None)
    except Exception as e:
        log.error(f"unqualifylead_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Lead.", parse_mode=None)


async def loselead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /loselead lead_id=LED-001 disposition_reason=...

    Explicit allowed → lost. disposition_reason is required and is
    never logged.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id", "")
    disposition_reason = args.get("disposition_reason", "")

    if not lead_id or not disposition_reason:
        await _reply(
            update,
            "❌ Укажи lead_id и disposition_reason.\n\nПример:\n"
            "`/loselead lead_id=LED-001 disposition_reason=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import lose_lead

        result = lose_lead(lead_id, disposition_reason=disposition_reason)
        await _reply(update, _lead_lifecycle_message(result, lead_id, "отметка 'потерян'"), parse_mode=None)
    except Exception as e:
        log.error(f"loselead_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить статус Lead.", parse_mode=None)


async def convertlead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /convertlead lead_id=LED-001 converted_client_id=PRS-001 [converted_by=...]

    Links the Lead to an existing Client and moves it to 'converted'.
    Never creates a Person/Client, never mutates one — the Client must
    already exist.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id", "")
    converted_client_id = args.get("converted_client_id", "")
    converted_by = args.get("converted_by", "") or _telegram_username(update)

    if not lead_id or not converted_client_id:
        await _reply(
            update,
            "❌ Укажи lead_id и converted_client_id.\n\nПример:\n"
            "`/convertlead lead_id=LED-001 converted_client_id=PRS-001`", parse_mode=None)
        return

    try:
        from business_core.business_builder import convert_lead

        result = convert_lead(lead_id, converted_client_id, converted_by)
        await _reply(update, _lead_conversion_message(result, lead_id), parse_mode=None)
    except Exception as e:
        log.error(f"convertlead_cmd error: {e}")
        await _reply(update, "❌ Не удалось конвертировать Lead.", parse_mode=None)


async def archivelead_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /archivelead lead_id=LED-001

    Any allowed status → archived. Terminal — no restore, no hard
    delete.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    lead_id = args.get("lead_id") or args.get("_pos0", "")

    if not lead_id:
        await _reply(update, "❌ Укажи lead_id.\n\nПример: /archivelead lead_id=LED-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import archive_lead

        result = archive_lead(lead_id)
        await _reply(update, _lead_lifecycle_message(result, lead_id, "архивирование"), parse_mode=None)
    except Exception as e:
        log.error(f"archivelead_cmd error: {e}")
        await _reply(update, "❌ Не удалось архивировать Lead.", parse_mode=None)


# ─────────────────────────────────────────────────────────────
# Phase 42D (ADR-025): Interaction / Communication History Domain
# caller (Telegram) UX.
#
# Every command below is a thin resolve-args -> call-canonical-
# orchestration -> render-message wrapper — no business logic beyond
# what business_builder/interaction_manager already returns.
# Centralized result-code -> Russian message mapping below mirrors the
# Phase 41D Lead UX pattern exactly. Summary/Outcome are only ever
# rendered in bounded/truncated form; Notes and External Reference are
# never shown or logged in any command.
# ─────────────────────────────────────────────────────────────

_INTERACTION_STATUS_RU: dict[str, str] = {
    "active": "Активно", "archived": "В архиве",
}

_INTERACTION_TYPE_RU: dict[str, str] = {
    "call": "Звонок", "message": "Сообщение", "email": "Email",
    "meeting": "Встреча", "note": "Заметка", "other": "Другое",
}

_INTERACTION_DIRECTION_RU: dict[str, str] = {
    "inbound": "Входящее", "outbound": "Исходящее", "internal": "Внутреннее",
}

_INTERACTION_SUMMARY_LIST_PREVIEW_LENGTH = 80
_INTERACTION_SUMMARY_DETAIL_MAX_LENGTH = 500
_INTERACTION_OUTCOME_DETAIL_MAX_LENGTH = 300


def _interaction_status_ru(status: str) -> str:
    return f"{_INTERACTION_STATUS_RU.get(status, status)} ({status})"


def _interaction_type_ru(interaction_type: str) -> str:
    return _INTERACTION_TYPE_RU.get(interaction_type, interaction_type or "—")


def _interaction_direction_ru(direction: str) -> str:
    if not direction:
        return "не указано"
    return _INTERACTION_DIRECTION_RU.get(direction, direction)


def _interaction_subject_summary(interaction: dict) -> str:
    """Centralized subject renderer — exactly one of Lead ID/Client ID
    is expected. Malformed historical data (both or neither present)
    is disclosed as an integrity warning, never silently repaired or
    arbitrarily chosen. Never exposes Client personal data — only the
    internal ID."""
    lead_id = interaction.get("Lead ID", "")
    client_id = interaction.get("Client ID", "")
    if lead_id and client_id:
        return f"⚠️ Некорректные данные: указаны и Lead ({lead_id}), и Client ({client_id})"
    if lead_id:
        return f"Lead: {lead_id}"
    if client_id:
        return f"Client: {client_id}"
    return "⚠️ Некорректные данные: не указан ни Lead, ни Client"


def _truncate_interaction_text(text: str, max_length: int) -> str:
    """Caller-only bounded rendering — discloses truncation, never
    shows unbounded content merely because it exists in the row."""
    text = text or ""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "…"


def _interaction_creation_message(result: dict) -> str:
    """Render any business_builder.create_interaction() result."""
    code = result.get("code", "")

    if code == "INTERACTION_CREATED":
        lines = [
            "✅ Interaction создан",
            f"Interaction ID: {result.get('interaction_id', '')}",
            f"Тип: {_interaction_type_ru(result.get('interaction_type', ''))}",
        ]
        if result.get("direction"):
            lines.append(f"Направление: {_interaction_direction_ru(result.get('direction', ''))}")
        lines.append(f"Дата: {result.get('occurred_at', '')}")
        if result.get("lead_id"):
            lines.append(f"Lead: {result['lead_id']}")
        if result.get("client_id"):
            lines.append(f"Client: {result['client_id']}")
        return "\n".join(lines)

    if code == "INTERACTION_REUSED":
        return "\n".join([
            "♻️ Interaction с этим ключом уже существует — использована существующая запись",
            f"Interaction ID: {result.get('interaction_id', '')}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business не найден: {result.get('error') or ''}"

    if code in ("LEAD_NOT_FOUND", "CLIENT_NOT_FOUND", "COMMERCIAL_OFFER_NOT_FOUND", "CHANNEL_NOT_FOUND", "PERSON_NOT_FOUND"):
        return f"❌ {result.get('error') or 'Указанная связанная запись не найдена.'}"

    if code == "INTERACTION_SUBJECT_REQUIRED":
        return "❌ Укажи ровно один субъект: lead_id либо client_id."

    if code == "INTERACTION_SUBJECT_CONFLICT":
        return "❌ Нельзя одновременно указать lead_id и client_id."

    if code == "INTERACTION_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "INTERACTION_TYPE_REQUIRED":
        return "❌ Укажи interaction_type."

    if code == "INVALID_INTERACTION_TYPE":
        return f"❌ {result.get('error') or 'Недопустимый interaction_type.'}"

    if code == "INTERACTION_DIRECTION_REQUIRED":
        return "❌ Укажи direction для этого interaction_type."

    if code == "INVALID_INTERACTION_DIRECTION":
        return f"❌ {result.get('error') or 'Недопустимый direction.'}"

    if code == "INTERACTION_OCCURRED_AT_REQUIRED":
        return "❌ Укажи occurred_at."

    if code in ("INVALID_INTERACTION_OCCURRED_AT", "INTERACTION_OCCURRED_AT_IN_FUTURE"):
        return f"❌ {result.get('error') or 'Недопустимая дата occurred_at.'}"

    if code == "INTERACTION_SUMMARY_REQUIRED":
        return "❌ Укажи summary."

    if code in ("INTERACTION_SUMMARY_TOO_LONG", "INTERACTION_OUTCOME_TOO_LONG", "INTERACTION_NOTES_TOO_LONG", "INTERACTION_EXTERNAL_REFERENCE_TOO_LONG"):
        return f"❌ {result.get('error') or 'Превышена допустимая длина поля.'}"

    if code == "INTERACTION_IDEMPOTENCY_REQUIRED":
        return "❌ Укажи caller_idempotency_key."

    if code == "MULTIPLE_INTERACTION_MATCHES":
        ids = ", ".join(result.get("conflicting_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Interaction с одним ключом: {ids}",
            "Новый Interaction не создан — автоматический выбор одного из них не выполняется.",
        ])

    if code == "INTERACTION_PERSISTENCE_FAILED":
        return f"❌ {result.get('error') or 'Не удалось создать Interaction.'}"

    if code == "INTERACTION_POST_WRITE_VERIFICATION_FAILED":
        return "\n".join(["⚠️ Interaction записан, но пост-проверка записи не прошла.", "Требуется ручная проверка."])

    if not code and result.get("error"):
        return f"❌ {result['error']}"

    log.warning(f"_interaction_creation_message: unmapped code={code!r}")
    return "❌ Не удалось создать Interaction."


def _interaction_archive_message(result: dict, interaction_id: str) -> str:
    """Render any business_builder.archive_interaction() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")

    if code == "INTERACTION_ARCHIVED":
        return "\n".join([
            "✅ Interaction архивирован",
            f"Interaction ID: {interaction_id}",
            f"Был: {_interaction_status_ru(previous_status)}",
        ])

    if code == "INTERACTION_STATUS_UNCHANGED":
        return f"ℹ️ Interaction {interaction_id} уже архивирован — изменений нет."

    if code == "INTERACTION_NOT_FOUND":
        return f"❌ Interaction {interaction_id} не найден."

    if code == "INVALID_INTERACTION_TRANSITION":
        return f"❌ Переход '{previous_status}' → 'archived' не разрешён."

    if code == "INTERACTION_PERSISTENCE_FAILED":
        return f"❌ Не удалось архивировать Interaction {interaction_id}."

    log.warning(f"_interaction_archive_message: unmapped code={code!r} interaction_id={interaction_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _interaction_notes_message(result: dict, interaction_id: str) -> str:
    """Render any business_builder.update_interaction_notes() result.
    Notes content is never echoed back, regardless of outcome."""
    code = result.get("code", "")

    if code == "INTERACTION_NOTES_UPDATED":
        return f"✅ Notes для Interaction {interaction_id} обновлены."

    if code == "INTERACTION_NOTES_UNCHANGED":
        return f"ℹ️ Interaction {interaction_id} — изменений нет (значения совпадают)."

    if code == "INTERACTION_NOT_FOUND":
        return f"❌ Interaction {interaction_id} не найден."

    if code == "INTERACTION_IMMUTABLE":
        return f"❌ {result.get('error') or 'Изменение недоступно — только Notes могут быть изменены.'}"

    if code == "INTERACTION_NOTES_TOO_LONG":
        return f"❌ {result.get('error') or 'Notes превышают допустимую длину.'}"

    log.warning(f"_interaction_notes_message: unmapped code={code!r} interaction_id={interaction_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


async def newinteraction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newinteraction business_id=BIZ-001 interaction_type=call
                     occurred_at=2026-08-01T10:00:00+05:00 summary=...
                     caller_idempotency_key=...
                     (lead_id=LED-001 | client_id=PRS-001)
                     [direction=outbound] [channel_id=CH-001]
                     [commercial_offer_id=OFR-001] [assigned_person_id=PRS-002]
                     [outcome=...] [external_reference=...]
                     [created_by=...] [notes=...]

    Creates one immutable Interaction event. Idempotent via
    caller_idempotency_key (ADR-025 §17) — repeated calls with the same
    key reuse the existing Interaction rather than creating a
    duplicate. Exactly one of lead_id/client_id is required.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    interaction_type = args.get("interaction_type", "")
    occurred_at = args.get("occurred_at", "")
    summary = args.get("summary", "")
    caller_idempotency_key = args.get("caller_idempotency_key", "")

    if not business_id or not interaction_type or not occurred_at or not summary or not caller_idempotency_key:
        await _reply(
            update,
            "❌ Укажи business_id, interaction_type, occurred_at, summary и caller_idempotency_key.\n\nПример:\n"
            "`/newinteraction business_id=BIZ-001 interaction_type=call direction=outbound "
            "occurred_at=2026-08-01T10:00:00+05:00 summary=\"Обсудили цену\" lead_id=LED-001 "
            "caller_idempotency_key=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import create_interaction

        result = create_interaction(
            business_id, interaction_type, occurred_at, summary,
            created_by=args.get("created_by", "") or _telegram_username(update),
            caller_idempotency_key=caller_idempotency_key,
            direction=args.get("direction", ""), channel_id=args.get("channel_id", ""),
            outcome=args.get("outcome", ""), lead_id=args.get("lead_id", ""), client_id=args.get("client_id", ""),
            commercial_offer_id=args.get("commercial_offer_id", ""), assigned_person_id=args.get("assigned_person_id", ""),
            external_reference=args.get("external_reference", ""), notes=args.get("notes", ""),
        )
        await _reply(update, _interaction_creation_message(result), parse_mode=None)
    except Exception as e:
        log.error(f"newinteraction_cmd error: {e}")
        await _reply(update, "❌ Не удалось создать Interaction.", parse_mode=None)


_INTERACTIONS_LIST_MAX_SHOWN = 20


async def interactions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /interactions [business_id=...] [lead_id=...] [client_id=...]
                  [commercial_offer_id=...] [channel_id=...] [assigned_person_id=...]
                  [interaction_type=...] [direction=...] [status=...]

    Read-only, bounded, filtered list of Interactions. Archived
    Interactions are excluded by default unless status=archived is
    explicit. Never shows full Summary/Outcome, Notes, External
    Reference, or Caller Idempotency Key.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    status_filter = args.get("status", "")

    try:
        from business_core.interaction_manager import list_interactions

        interactions = list_interactions(
            business_id=args.get("business_id", ""), lead_id=args.get("lead_id", ""),
            client_id=args.get("client_id", ""), commercial_offer_id=args.get("commercial_offer_id", ""),
            channel_id=args.get("channel_id", ""), assigned_person_id=args.get("assigned_person_id", ""),
            interaction_type=args.get("interaction_type", ""), direction=args.get("direction", ""),
            status=status_filter, include_archived=(status_filter == "archived"),
        )

        if not interactions:
            await _reply(update, "ℹ️ Interactions не найдены.", parse_mode=None)
            return

        lines = [f"📞 Interactions ({len(interactions)})", ""]
        for i in interactions[:_INTERACTIONS_LIST_MAX_SHOWN]:
            preview = _truncate_interaction_text(i.get("Summary", ""), _INTERACTION_SUMMARY_LIST_PREVIEW_LENGTH)
            entry = (
                f"{i.get('Interaction ID', '')} [{_interaction_status_ru(i.get('Status', ''))}] "
                f"{_interaction_type_ru(i.get('Interaction Type', ''))} — {_interaction_subject_summary(i)} — {preview}"
            )
            lines.append(entry)
        if len(interactions) > _INTERACTIONS_LIST_MAX_SHOWN:
            lines.append(f"\n… показаны первые {_INTERACTIONS_LIST_MAX_SHOWN} из {len(interactions)}.")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"interactions_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить список Interactions.", parse_mode=None)


async def interaction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /interaction interaction_id=ACT-001

    Read-only, exact-ID detail. Hides Notes, External Reference, and
    Caller Idempotency Key. Summary/Outcome are shown only in bounded
    form.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    interaction_id = args.get("interaction_id") or args.get("_pos0", "")

    if not interaction_id:
        await _reply(update, "❌ Укажи interaction_id.\n\nПример: /interaction interaction_id=ACT-001", parse_mode=None)
        return

    try:
        from business_core.interaction_manager import find_interaction_by_id

        interaction = find_interaction_by_id(interaction_id)
        if interaction is None:
            await _reply(update, f"❌ Interaction {interaction_id} не найден.", parse_mode=None)
            return

        lines = [
            f"📞 Interaction {interaction.get('Interaction ID', '')}",
            "",
            f"Business: {interaction.get('Business ID', '')}",
            _interaction_subject_summary(interaction),
            f"Тип: {_interaction_type_ru(interaction.get('Interaction Type', ''))}",
        ]
        if interaction.get("Direction"):
            lines.append(f"Направление: {_interaction_direction_ru(interaction.get('Direction', ''))}")
        for key, label in (("Commercial Offer ID", "Offer"), ("Channel ID", "Channel"), ("Assigned Person ID", "Ответственный")):
            if interaction.get(key):
                lines.append(f"{label}: {interaction[key]}")
        lines.append(f"Дата: {interaction.get('Occurred At', '')}")
        lines.append(f"Summary: {_truncate_interaction_text(interaction.get('Summary', ''), _INTERACTION_SUMMARY_DETAIL_MAX_LENGTH)}")
        if interaction.get("Outcome"):
            lines.append(f"Outcome: {_truncate_interaction_text(interaction.get('Outcome', ''), _INTERACTION_OUTCOME_DETAIL_MAX_LENGTH)}")
        lines.append(f"Статус: {_interaction_status_ru(interaction.get('Status', ''))}")
        lines.append(f"Создан: {interaction.get('Created At', '')}")
        if interaction.get("Updated At"):
            lines.append(f"Обновлён: {interaction['Updated At']}")
        if interaction.get("Archived At"):
            lines.append(f"Архивирован: {interaction['Archived At']}")

        await _reply(update, "\n".join(lines), parse_mode=None)
    except Exception as e:
        log.error(f"interaction_cmd error: {e}")
        await _reply(update, "❌ Не удалось получить Interaction.", parse_mode=None)


async def archiveinteraction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /archiveinteraction interaction_id=ACT-001

    active → archived. Terminal — no restore, no hard delete.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    interaction_id = args.get("interaction_id") or args.get("_pos0", "")

    if not interaction_id:
        await _reply(update, "❌ Укажи interaction_id.\n\nПример: /archiveinteraction interaction_id=ACT-001", parse_mode=None)
        return

    try:
        from business_core.business_builder import archive_interaction

        result = archive_interaction(interaction_id)
        await _reply(update, _interaction_archive_message(result, interaction_id), parse_mode=None)
    except Exception as e:
        log.error(f"archiveinteraction_cmd error: {e}")
        await _reply(update, "❌ Не удалось архивировать Interaction.", parse_mode=None)


async def updateinteractionnotes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updateinteractionnotes interaction_id=ACT-001 notes=...

    Notes-only admin update, allowed in both active and archived
    states. No Interaction fact may be changed through this command.
    Notes content is never echoed back in the reply.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg(), parse_mode=None)
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    interaction_id = args.get("interaction_id", "")
    notes = args.get("notes", "")

    if not interaction_id or not notes:
        await _reply(
            update,
            "❌ Укажи interaction_id и notes.\n\nПример:\n"
            "`/updateinteractionnotes interaction_id=ACT-001 notes=...`", parse_mode=None)
        return

    try:
        from business_core.business_builder import update_interaction_notes

        result = update_interaction_notes(interaction_id, notes)
        await _reply(update, _interaction_notes_message(result, interaction_id), parse_mode=None)
    except Exception as e:
        log.error(f"updateinteractionnotes_cmd error: {e}")
        await _reply(update, "❌ Не удалось обновить Notes для Interaction.", parse_mode=None)


async def milestones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /milestones roadmap_id=RM-022

    Read-only: показать коммерческие этапы оплаты по roadmap.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        parts = (update.message.text or "").split(None, 1)
        raw = parts[1] if len(parts) > 1 else " ".join(context.args or [])
    except (IndexError, TypeError, AttributeError):
        raw = ""

    args       = _parse_kv_args(raw)
    roadmap_id = (args.get("roadmap_id") or args.get("_pos0", "")).strip()

    if not roadmap_id:
        await _reply(update,
            "ℹ️ *Использование:* `/milestones roadmap_id=RM-022`\n\n"
            "Команда показывает коммерческие этапы оплаты по roadmap.\n\n"
            "Пример:\n`/milestones roadmap_id=RM-022`"
        )
        return

    await _reply(update, f"⏳ Загружаю коммерческие этапы для `{roadmap_id}`...")

    try:
        import asyncio
        from business_core.roadmap_manager import get_commercial_milestones_for_roadmap

        data = await asyncio.to_thread(
            get_commercial_milestones_for_roadmap,
            roadmap_id,
        )

        if not data["ok"]:
            await _reply(update, f"❌ {data['error']}")
            return

        rm          = data["roadmap"]
        template_id = data["template_id"]

        if not data["milestones"]:
            if template_id:
                msg = (
                    f"ℹ️ Для roadmap `{roadmap_id}` коммерческие этапы не настроены.\n\n"
                    f"Шаблон `{template_id}` пока не имеет маппинга коммерческих этапов.\n"
                    f"Проверьте `SOP-IZH-COMMERCIAL-MILESTONES-001` или добавьте mapping."
                )
            else:
                msg = (
                    f"ℹ️ Для roadmap `{roadmap_id}` коммерческие этапы не настроены.\n\n"
                    "Не удалось определить template\\_id для roadmap.\n"
                    "Для этого шаблона коммерческие этапы ещё не настроены. "
                    "Проверьте `SOP-IZH-COMMERCIAL-MILESTONES-001` или добавьте mapping."
                )
            await _reply(update, msg)
            return

        lines = [
            f"💰 *Коммерческие этапы: {roadmap_id}*",
            f"Object:   `{rm.get('object_id',  '—')}`",
            f"Service:  `{rm.get('service_id', '—')}`",
            f"Template: `{template_id}`",
            "",
        ]

        for i, ms in enumerate(data["milestones"], 1):
            price_fmt = f"{ms['price']:,}".replace(",", " ")
            lines.append(f"*{i}) {ms['title']} — {price_fmt} тг*")
            lines.append(f"Рабочие этапы: {ms['stage_range']}")
            lines.append(f"Результат: {ms['result']}")
            if ms.get("important"):
                lines.append(f"⚠️ Важно: _{ms['important']}_")
            lines.append("")

        total_fmt = f"{data['total_price']:,}".replace(",", " ")
        lines.append(f"💵 *Итого: {total_fmt} тг*")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"milestones_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /report — Business Core read-only report (Phase 11B)
# ─────────────────────────────────────────────────────────────

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Read-only отчёт Business Core: attention / statistics / quality / progress.

    Вся бизнес-логика — в business_core.report_manager; этот handler
    только собирает snapshot, прогоняет его через pure build_*() функции
    и отправляет результат render_report().
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        from business_core.report_manager import (
            collect_snapshot,
            build_attention,
            build_statistics,
            build_quality,
            build_progress,
            render_report,
        )

        snapshot   = collect_snapshot()
        attention  = build_attention(snapshot)
        statistics = build_statistics(snapshot)
        quality    = build_quality(snapshot)
        progress   = build_progress(snapshot)

        text = render_report(
            attention, statistics, quality, progress,
            snapshot_errors=snapshot.get("errors"),
        )

        await _reply(update, text)

    except Exception as e:
        log.error(f"report_cmd error: {e}")
        await _reply(update, f"❌ Ошибка построения отчёта: {e}")


async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Read-only build/deploy provenance (Phase 12A).

    Не обращается к Google Sheets/Drive — только читает bundled VERSION
    файл и Railway environment variables. Существует, чтобы можно было
    подтвердить "production действительно на этом коммите" без SSH
    (см. Phase 11H/11I: `railway redeploy` может незаметно оставить
    старый build запущенным).
    """
    try:
        from business_core.version_info import get_version_info

        info = get_version_info()
        lines = [
            "🏷 Build info",
            "",
            f"Commit: {info['commit_sha']}",
            f"Source: {info['source']}",
            f"Build time: {info['build_timestamp']}",
            f"Environment: {info['environment']}",
            f"Deployment ID: {info['deployment_id']}",
        ]
        if info["warning"]:
            lines.append(f"⚠️ Warning: {info['warning']}")
        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"version_cmd error: {e}")
        await _reply(update, f"❌ Ошибка получения версии: {e}")


# ─────────────────────────────────────────────────────────────
# Phase 35E (ADR-018 §17-§20): centralized Organization result-code ->
# Russian message mapping. Presentation only — every branch reacts to a
# field business_builder.assign_person_to_role_canonical() /
# work_assignment_manager.assign_role_to_stage() / reassign_stage_role()
# already computed; nothing here re-derives eligibility, re-checks
# archived/paused status, or picks among duplicates. Mirrors the
# Phase 34C/34D Stage-transition UX pattern
# (_stage_transition_failure_message()) applied to the Organization
# Domain's Person<->Role assignment and Stage->Role codes. An unmapped
# code gets a safe generic fallback (code + IDs only, never a raw
# exception or the result dict) plus a logged warning for triage.
# ─────────────────────────────────────────────────────────────

def _organization_assignment_message(result: dict, person_id: str, role_id: str) -> str:
    """
    Render any business_builder.assign_person_to_role_canonical() result
    (ok=True or ok=False) into a single Russian Telegram message. Never
    exposes the raw result dict or a traceback.
    """
    code = result.get("code", "")

    if code == "ASSIGNMENT_CREATED":
        return "\n".join([
            "✅ Назначение создано",
            f"Person ID: `{person_id}`",
            f"Role ID: `{role_id}`",
            f"Assignment ID: `{result.get('assignment_id', '')}`",
        ])

    if code == "ASSIGNMENT_REUSED":
        return "\n".join([
            "ℹ️ Уже назначен — активное назначение уже существует",
            f"Person ID: `{person_id}`",
            f"Role ID: `{role_id}`",
            f"Assignment ID: `{result.get('assignment_id', '')}` (новая запись не создана)",
        ])

    if code == "PERSON_NOT_FOUND":
        return f"❌ Person `{person_id}` не найден."

    if code == "PERSON_ARCHIVED":
        return "\n".join([
            "❌ Person архивирован",
            f"Person ID: `{person_id}`",
            "Архивированный Person не может получить назначение на Role.",
        ])

    if code == "ROLE_NOT_FOUND":
        return f"❌ Role `{role_id}` не найдена."

    if code == "ROLE_PAUSED":
        return "\n".join([
            "❌ Role приостановлена (paused)",
            f"Role ID: `{role_id}`",
            "Приостановленная Role не может получить новое назначение Person.",
        ])

    if code == "ROLE_ARCHIVED":
        return "\n".join([
            "❌ Role архивирована",
            f"Role ID: `{role_id}`",
            "Архивированная Role не может получить новое назначение Person.",
        ])

    if code == "DEPARTMENT_NOT_FOUND":
        return "\n".join([
            "❌ Department этой Role не найден",
            f"Role ID: `{role_id}`",
        ])

    if code == "DEPARTMENT_ARCHIVED":
        return "\n".join([
            "❌ Department этой Role архивирован",
            f"Department ID: `{result.get('department_id', '')}`",
            "Родительский Department архивирован — назначение не разрешено.",
        ])

    if code == "PERSON_NOT_LINKED_TO_BUSINESS":
        return "\n".join([
            "❌ Person не привязан к бизнесу этой Role",
            f"Person ID: `{person_id}`",
            f"Role ID: `{role_id}`",
        ])

    if code == "PERSON_ROLE_BUSINESS_MISMATCH":
        return "\n".join([
            "❌ Person привязан к другому бизнесу",
            f"Person ID: `{person_id}`",
            "Person не привязан к бизнесу этой Role.",
        ])

    if code == "MULTIPLE_ACTIVE_ASSIGNMENTS_INTEGRITY_ERROR":
        ids = ", ".join(f"`{a}`" for a in result.get("conflicting_assignment_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Person ID: `{person_id}`",
            f"Role ID: `{role_id}`",
            f"Найдено несколько активных Assignment одновременно: {ids}",
            "Новое назначение не создано — требуется ручная проверка данных, "
            "автоматический выбор одного из них не выполняется.",
        ])

    if code == "ASSIGNMENT_ENDED_IMMUTABLE":
        return "❌ Это назначение уже завершено (ended) — изменить его статус нельзя."

    if code == "INVALID_ROLE_STATUS":
        return f"❌ Role `{role_id}` имеет недопустимый статус."

    if code == "INVALID_ASSIGNMENT_STATUS":
        return "❌ Недопустимый статус назначения."

    log.warning(f"_organization_assignment_message: unmapped code={code!r} person_id={person_id} role_id={role_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _stage_role_message(result: dict, stage_id: str, role_id: str) -> str:
    """
    Render any work_assignment_manager.assign_role_to_stage() /
    reassign_stage_role() result into a single Russian Telegram message.
    Never exposes the raw result dict or a traceback.
    """
    code = result.get("code", "")

    if code == "STAGE_ROLE_ASSIGNED":
        return "\n".join([
            "✅ Role назначена на этап",
            f"Stage ID: `{stage_id}`",
            f"Role ID: `{role_id}`",
            f"Relation ID: `{result.get('relation_id') or result.get('new_relation_id', '')}`",
        ])

    if code == "STAGE_ROLE_REUSED":
        return "\n".join([
            f"ℹ️ Этап `{stage_id}` уже назначен на роль `{role_id}`",
            "Изменений нет, повтор безопасен.",
        ])

    if code == "STAGE_ROLE_REASSIGNED":
        return "\n".join([
            "✅ Role этапа изменена",
            f"Stage ID: `{stage_id}`",
            f"Была: `{result.get('old_relation_id') or '—'}`",
            f"Стала: `{result.get('new_relation_id', '')}` (role `{role_id}`)",
        ])

    if code == "STAGE_NOT_FOUND":
        return f"❌ Этап `{stage_id}` не найден."

    if code == "ROLE_NOT_FOUND":
        return f"❌ Role `{role_id}` не найдена."

    if code == "ROLE_NOT_ACTIVE_FOR_STAGE_ASSIGNMENT":
        return "\n".join([
            "❌ Role не активна",
            f"Role ID: `{role_id}`",
            "Только Role со статусом active может получить ответственность за этап.",
        ])

    if code == "DEPARTMENT_NOT_FOUND":
        return "\n".join([
            "❌ Department этой Role не найден",
            f"Role ID: `{role_id}`",
        ])

    if code == "DEPARTMENT_ARCHIVED":
        return "\n".join([
            "❌ Department этой Role архивирован",
            f"Role ID: `{role_id}`",
        ])

    if code == "MULTIPLE_ACTIVE_STAGE_ROLE_RELATIONS_INTEGRITY_ERROR":
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Stage ID: `{stage_id}`",
            "У этапа уже есть активная Role-relation — используй /reassignstagerole. "
            "Автоматический выбор одной из relations не выполняется.",
        ])

    log.warning(f"_stage_role_message: unmapped code={code!r} stage_id={stage_id} role_id={role_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


# ─────────────────────────────────────────────────────────────
# Phase 21F: Organization Layer — /newdept /newrole /roles /roledetails
# /assignrole. Additive only — no existing command touched.
#
# Thin wrappers over business_core.organization_manager: parse args,
# call the manager, format the reply. No business logic beyond what the
# manager already returns (ENGINEERING_STANDARDS.md, Module Standards —
# telegram_handlers.py is not a source of truth for validation).
# ─────────────────────────────────────────────────────────────

async def newdept_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newdept name="Operations" [business_id=BIZ-001] [parent_department_id=DEPT-001]
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    name = args.get("name") or args.get("_pos0", "")

    if not name:
        await _reply(update,
            "❌ Укажи name.\n\nПример:\n"
            '`/newdept name="Operations" parent_department_id=DEPT-001`'
        )
        return

    try:
        from business_core.organization_manager import create_department

        result = create_department(
            name,
            business_id=args.get("business_id", ""),
            parent_department_id=args.get("parent_department_id", ""),
            notes=args.get("notes", ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return

        lines = ["✅ Department создан", f"Department ID: `{result['department_id']}`", f"Название: {name}"]
        if args.get("parent_department_id"):
            lines.append(f"Parent: `{args['parent_department_id']}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newdept_cmd error: {e}")
        await _reply(update, "❌ Ошибка при создании Department.")


async def newrole_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newrole name="Coordinator" department_id=DEPT-002 [reports_to_role_id=ROLE-001]
             [status=planned] [purpose="..."] [main_result="..."]

    status по умолчанию "planned" — новая роль обычно вакантна до найма
    (см. ARCHITECTURE.md / Organization Layer).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    name = args.get("name") or args.get("_pos0", "")
    department_id = args.get("department_id", "")

    if not name or not department_id:
        from business_core.organization_manager import ROLE_STATUS
        await _reply(update,
            "❌ Укажи name и department_id.\n\n"
            f"Допустимые статусы: `{', '.join(ROLE_STATUS)}`\n\n"
            "Пример:\n"
            '`/newrole name="Coordinator" department_id=DEPT-002 '
            'reports_to_role_id=ROLE-001 status=planned`'
        )
        return

    try:
        from business_core.organization_manager import create_role

        result = create_role(
            name,
            department_id=department_id,
            reports_to_role_id=args.get("reports_to_role_id", ""),
            status=args.get("status", "planned"),
            purpose=args.get("purpose", ""),
            main_result=args.get("main_result", ""),
            notes=args.get("notes", ""),
        )
        if not result["ok"]:
            await _reply(update, f"❌ Ошибка: {result['error']}")
            return

        lines = ["✅ Role создана", f"Role ID: `{result['role_id']}`", f"Название: {name}",
                  f"Department: `{department_id}`"]
        if args.get("reports_to_role_id"):
            lines.append(f"Reports To: `{args['reports_to_role_id']}`")
        lines.append(f"\nНазначить человека: `/assignrole person_id=PRS-001 role_id={result['role_id']}`")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newrole_cmd error: {e}")
        await _reply(update, "❌ Ошибка при создании Role.")


async def roles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /roles [department_id=DEPT-002] [status=planned]

    Read-only. Показывает вакантность (по is_role_vacant()) рядом с
    каждой ролью.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    try:
        from business_core.organization_manager import list_roles, is_role_vacant

        roles = list_roles(department_id=args.get("department_id", ""), status=args.get("status", ""))

        if not roles:
            await _reply(update, "📋 *Роли*\n\nПусто. Создай первую: /newrole")
            return

        lines = [f"📋 *Роли* ({len(roles)} шт.)\n"]
        for r in roles[:30]:
            vacancy_icon = "🟡 вакантна" if is_role_vacant(r["role_id"]) else "🟢 занята"
            lines.append(f"`{r['role_id']}` {r['role_name']} — {r['status']} ({vacancy_icon})")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"roles_cmd error: {e}")
        await _reply(update, "❌ Ошибка при получении списка Roles.")


async def roledetails_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /roledetails role_id=ROLE-001

    Read-only карточка роли: поля Role + вакантность + активные
    назначения (person_id, start_date).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    role_id = args.get("role_id") or args.get("_pos0", "")

    if not role_id:
        await _reply(update, "❌ Укажи role_id.\n\nПример: /roledetails role_id=ROLE-001")
        return

    try:
        from business_core.organization_manager import find_role_by_id, is_role_vacant, get_active_roles_for_person

        role = find_role_by_id(role_id)
        if not role:
            await _reply(update, f"❌ Role {role_id} не найдена.")
            return

        from business_core.organization_manager import list_assignments_for_role
        active_assignments = list_assignments_for_role(role_id, status="active")

        lines = [
            f"📌 Role {role['role_id']}",
            "",
            f"Название: {role['role_name']}",
            f"Department: {role['department_id']}",
            f"Reports To: {role['reports_to_role_id'] or '—'}",
            f"Статус: {role['status']}",
            f"Purpose: {role['purpose'] or '—'}",
            f"Main Result: {role['main_result'] or '—'}",
        ]
        if is_role_vacant(role_id):
            lines.append("Вакантность: 🟡 вакантна")
        else:
            lines.append("Вакантность: 🟢 занята")
            for a in active_assignments:
                lines.append(f"  — {a['person_id']} (с {a['start_date']}, {a['assignment_type']})")

        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"roledetails_cmd error: {e}")
        await _reply(update, "❌ Ошибка при получении карточки Role.")


async def assignrole_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /assignrole person_id=PRS-001 role_id=ROLE-001 [start_date=2026-01-01]
                [assignment_type=primary]

    start_date по умолчанию — сегодня, если не передан. Множественные
    одновременные активные назначения для одного человека разрешены
    (multi-role, см. ARCHITECTURE.md §4) — эта команда не проверяет и не
    запрещает такое дублирование.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    person_id = args.get("person_id", "")
    role_id = args.get("role_id", "")

    if not person_id or not role_id:
        await _reply(update,
            "❌ Укажи person_id и role_id.\n\nПример:\n"
            "`/assignrole person_id=PRS-001 role_id=ROLE-001`"
        )
        return

    try:
        # Phase 35D (ADR-018 §17): this command only parses IDs and
        # renders a minimal compatibility message. All Person/Role/
        # Department/Business-membership eligibility and duplicate-
        # Assignment policy lives solely in business_builder.
        # assign_person_to_role_canonical() — never called directly
        # here again.
        from business_core.business_builder import assign_person_to_role_canonical

        start_date = args.get("start_date", "") or datetime.now().strftime("%Y-%m-%d")
        result = assign_person_to_role_canonical(
            person_id, role_id, start_date,
            assignment_type=args.get("assignment_type", "primary"),
        )
        await _reply(update, _organization_assignment_message(result, person_id, role_id))
    except Exception as e:
        log.error(f"assignrole_cmd error: {e}")
        await _reply(update, "❌ Ошибка при назначении Person на Role.")


# ─────────────────────────────────────────────────────────────
# Phase 22D: Work Execution Layer — /assignstagerole /reassignstagerole
# /stageresponsibility. Additive only — no existing command touched.
#
# Thin wrappers over business_core.work_assignment_manager: parse args,
# call the manager, format the reply. No business logic beyond what the
# manager already returns, no direct Sheets access from these handlers
# (ENGINEERING_STANDARDS.md, Module Standards / Manager First).
# ─────────────────────────────────────────────────────────────

async def assignstagerole_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /assignstagerole stage_id=STAGE-001 role_id=ROLE-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id", "")
    role_id = args.get("role_id", "")

    if not stage_id or not role_id:
        await _reply(update,
            "❌ Укажи stage_id и role_id.\n\nПример:\n"
            "`/assignstagerole stage_id=STAGE-001 role_id=ROLE-001`"
        )
        return

    try:
        from business_core.work_assignment_manager import assign_role_to_stage

        result = assign_role_to_stage(stage_id, role_id)
        await _reply(update, _stage_role_message(result, stage_id, role_id))
    except Exception as e:
        log.error(f"assignstagerole_cmd error: {e}")
        await _reply(update, "❌ Ошибка при назначении Role на этап.")


async def reassignstagerole_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reassignstagerole stage_id=STAGE-001 role_id=ROLE-002

    Различает четыре исхода:
      - changed=True, ok=True  -> ✅ смена прошла успешно
      - changed=False, ok=True -> ℹ️ этап уже назначен на эту роль (idempotent no-op)
      - changed=True, ok=False -> ⚠️ старая relation уже деактивирована,
        но новая не создалась — partial failure, требует повторной попытки
      - changed=False, ok=False -> ❌ валидационная/manager-ошибка, ничего не изменено
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id", "")
    role_id = args.get("role_id", "")

    if not stage_id or not role_id:
        await _reply(update,
            "❌ Укажи stage_id и role_id.\n\nПример:\n"
            "`/reassignstagerole stage_id=STAGE-001 role_id=ROLE-002`"
        )
        return

    try:
        from business_core.work_assignment_manager import reassign_stage_role

        result = reassign_stage_role(stage_id, role_id)

        # The one outcome _stage_role_message() doesn't cover: the old
        # relation was already deactivated but the new one failed to
        # create (changed=True, ok=False) — a genuine partial-failure
        # state specific to reassign's two-step write, distinct from
        # any single result code.
        if not result["ok"] and result["changed"]:
            log.warning(
                f"reassignstagerole_cmd partial failure: stage_id={stage_id} role_id={role_id} "
                f"old_relation_id={result['old_relation_id']} error={result.get('error')}"
            )
            await _reply(update, "\n".join([
                "⚠️ Смена роли выполнена частично",
                f"Stage ID: `{stage_id}`",
                f"Старая relation деактивирована: `{result['old_relation_id']}`",
                "Не удалось создать новую — повтор команды безопасен.",
            ]))
            return

        await _reply(update, _stage_role_message(result, stage_id, role_id))
    except Exception as e:
        log.error(f"reassignstagerole_cmd error: {e}")
        await _reply(update, "❌ Ошибка при смене Role этапа.")


async def stageresponsibility_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stageresponsibility stage_id=STAGE-001

    Read-only. Показывает все четыре структурных статуса resolve_
    stage_responsibility(): assigned / vacant / unconfigured /
    configuration_error. Никогда не показывает traceback/внутренние
    детали исключений — только уже безопасные, человекочитаемые строки
    из result['errors'].
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    stage_id = args.get("stage_id") or args.get("_pos0", "")

    if not stage_id:
        await _reply(update, "❌ Укажи stage_id.\n\nПример: /stageresponsibility stage_id=STAGE-001")
        return

    try:
        from business_core.work_assignment_manager import resolve_stage_responsibility

        result = resolve_stage_responsibility(stage_id)
        status = result["status"]

        if status == "assigned":
            role_name = "—"
            try:
                from business_core.organization_manager import find_role_by_id
                role = find_role_by_id(result["role_id"])
                if role:
                    role_name = role.get("role_name") or "—"
            except Exception:
                pass

            person_name = "—"
            assignment_type = ""
            try:
                from business_core.person_manager import find_person_by_id
                person = find_person_by_id(result["person_id"])
                if person:
                    person_name = person.get("full_name") or person.get("short_name") or "—"
            except Exception:
                pass
            try:
                from business_core.organization_manager import list_assignments_for_role
                active = list_assignments_for_role(result["role_id"], status="active")
                match = next((a for a in active if a.get("person_id") == result["person_id"]), None)
                if match:
                    assignment_type = match.get("assignment_type", "")
            except Exception:
                pass

            lines = [
                "✅ Stage Responsibility: assigned",
                f"Stage ID: `{stage_id}`",
                f"Role ID: `{result['role_id']}`",
                f"Role Name: {role_name}",
                f"Person ID: `{result['person_id']}`",
                f"Person Name: {person_name}",
            ]
            if assignment_type:
                lines.append(f"Assignment Type: {assignment_type}")
            await _reply(update, "\n".join(lines))
            return

        if status == "vacant":
            role_name = "—"
            try:
                from business_core.organization_manager import find_role_by_id
                role = find_role_by_id(result["role_id"])
                if role:
                    role_name = role.get("role_name") or "—"
            except Exception:
                pass

            await _reply(update, "\n".join([
                "🟡 Stage Responsibility: vacant",
                f"Stage ID: `{stage_id}`",
                f"Role ID: `{result['role_id']}`",
                f"Role Name: {role_name}",
                "У роли нет активного Person Assignment.",
            ]))
            return

        if status == "unconfigured":
            await _reply(update, "\n".join([
                "ℹ️ Stage Responsibility: unconfigured",
                f"Stage ID: `{stage_id}`",
                "Для этого этапа не настроена ответственная роль.",
            ]))
            return

        # configuration_error
        lines = [
            "❌ Stage Responsibility: configuration_error",
            f"Stage ID: `{stage_id}`",
        ]
        if result.get("role_id"):
            lines.append(f"Role ID: `{result['role_id']}`")
        if result.get("relation_id"):
            lines.append(f"Relation ID: `{result['relation_id']}`")
        for err in result.get("errors", ()):
            lines.append(f"— {err}")
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"stageresponsibility_cmd error: {e}")
        await _reply(update, "❌ Ошибка при получении статуса ответственности за этап.")


# ─────────────────────────────────────────────────────────────
# Phase 36D (ADR-019 §4/§14-16): Task Domain — /newbctask /bctasks
# /bctask /updatetask /assigntask /reassigntask /unassigntask.
# Additive only — GTD's own /tasks (telegram_bot.py) is never touched.
#
# Thin wrappers over business_core.business_builder's Task orchestration
# functions (create_business_task/update_task_admin_fields/
# transition_task_status/assign_task/unassign_task) and
# business_core.task_manager's read-only APIs (find_task_by_id/
# list_tasks/task_assignment_cache_is_consistent) — no business logic
# beyond what those functions already return (ENGINEERING_STANDARDS.md,
# Module Standards). Centralized result-code -> Russian message mapping
# below mirrors the Phase 35E Organization UX pattern exactly.
# ─────────────────────────────────────────────────────────────

_TASK_STATUS_RU: dict[str, str] = {
    "new": "Новая", "ready": "Готова к работе", "in_progress": "В работе",
    "waiting": "Ожидает", "blocked": "Заблокирована", "done": "Выполнена",
    "cancelled": "Отменена", "skipped": "Пропущена",
}

_TASK_ASSIGNMENT_STATUS_RU: dict[str, str] = {
    "active": "Активно", "ended": "Завершено",
}


def _task_status_ru(status: str) -> str:
    """Russian label + raw machine status, always both — never only
    the translation, so debugging never loses the exact stored value."""
    return f"{_TASK_STATUS_RU.get(status, status)} ({status})"


def _task_creation_message(result: dict) -> str:
    """
    Render any business_builder.create_business_task() result into a
    single Russian Telegram message. Never exposes the raw result dict
    or a traceback.
    """
    code = result.get("code", "")

    if code == "TASK_CREATED":
        return "\n".join([
            "✅ Task создан",
            f"Task ID: `{result.get('task_id', '')}`",
            f"Business ID: `{result.get('business_id', '')}`",
            f"Статус: {_task_status_ru(result.get('final_status', 'new'))}",
        ])

    if code == "TASK_REUSED":
        return "\n".join([
            "ℹ️ Task уже существует — переиспользован по Idempotency Key",
            f"Task ID: `{result.get('task_id', '')}`",
            f"Статус: {_task_status_ru(result.get('final_status', ''))}",
        ])

    if code == "BUSINESS_NOT_FOUND":
        return f"❌ Business `{result.get('business_id', '')}` не найден."

    if code == "TASK_ENTITY_RELATION_MISMATCH":
        return f"❌ Несогласованные ссылки на сущности: {result.get('error') or 'см. логи'}"

    if code == "ROADMAP_NOT_FOUND":
        return "❌ Указанный Roadmap не найден."

    if code == "STAGE_NOT_FOUND":
        return "❌ Указанный Stage не найден."

    if code == "ROADMAP_COMPLETED":
        return "❌ Roadmap уже завершён — новый связанный Task не может быть создан."

    if code == "ROADMAP_CANCELLED":
        return "❌ Roadmap отменён — новый связанный Task не может быть создан."

    if code == "STAGE_TERMINAL":
        return "❌ Stage имеет терминальный статус (done/skipped) — новый связанный Task не может быть создан."

    if code == "MULTIPLE_TASK_IDEMPOTENCY_MATCHES":
        ids = ", ".join(f"`{t}`" for t in result.get("conflicting_task_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Найдено несколько Task с одним Idempotency Key: {ids}",
            "Новый Task не создан — автоматический выбор одного из них не выполняется.",
        ])

    log.warning(f"_task_creation_message: unmapped code={code!r} business_id={result.get('business_id', '')}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _task_admin_message(result: dict, task_id: str) -> str:
    """Render any business_builder.update_task_admin_fields() result."""
    code = result.get("code", "")

    if code == "TASK_ADMIN_FIELDS_UPDATED":
        return f"✅ Task `{task_id}` обновлён."

    if code == "TASK_ADMIN_FIELDS_UNCHANGED":
        return f"ℹ️ Task `{task_id}` — изменений нет (значения совпадают)."

    if code == "TASK_NOT_FOUND":
        return f"❌ Task `{task_id}` не найден."

    if code == "TASK_IMMUTABLE_FIELD_CONFLICT":
        return f"❌ Указанные поля являются неизменяемой идентичностью Task: {result.get('error') or ''}"

    if code == "TASK_RELATION_UPDATE_REQUIRES_EXPLICIT_ACTION":
        return "❌ Изменение связей (Client/Object/Service/Roadmap/Stage ID) через /updatetask не поддерживается."

    if code == "INVALID_TASK_ADMIN_FIELD":
        return f"❌ Недопустимое поле для /updatetask: {result.get('error') or ''}"

    log.warning(f"_task_admin_message: unmapped code={code!r} task_id={task_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _task_transition_message(result: dict, task_id: str) -> str:
    """Render any business_builder.transition_task_status() result."""
    code = result.get("code", "")
    previous_status = result.get("previous_status", "")
    requested_status = result.get("requested_status", "")

    if code == "TASK_STATUS_UPDATED":
        return "\n".join([
            "✅ Статус Task изменён",
            f"Task ID: `{task_id}`",
            f"Был: {_task_status_ru(previous_status)}",
            f"Стал: {_task_status_ru(result.get('final_status', ''))}",
        ])

    if code == "TASK_STATUS_UNCHANGED":
        return f"ℹ️ Task `{task_id}` уже имеет статус {_task_status_ru(previous_status)} — изменений нет."

    if code == "TASK_NOT_FOUND":
        return f"❌ Task `{task_id}` не найден."

    if code == "INVALID_TASK_STATUS":
        from business_core.task_manager import TASK_STATUS
        return f"❌ Недопустимый статус. Допустимые значения: `{', '.join(TASK_STATUS)}`"

    if code == "INVALID_TASK_TRANSITION":
        return (
            f"❌ Переход {_task_status_ru(previous_status)} → {_task_status_ru(requested_status)} не разрешён."
        )

    if code == "TASK_REOPEN_REQUIRES_EXPLICIT_ACTION":
        return "\n".join([
            "🔒 Task уже завершён",
            f"Task ID: `{task_id}`",
            f"Текущий статус: {_task_status_ru(previous_status)}",
            "Такой Task нельзя вернуть в работу обычной командой изменения статуса. "
            "Отдельное явное действие reopen пока не реализовано.",
        ])

    if code == "ROADMAP_ON_HOLD":
        return "⏸️ Roadmap этого Task приостановлен (on_hold) — переход в «В работе» сейчас не разрешён."

    if code == "ROADMAP_COMPLETED":
        return "✅ Roadmap этого Task уже завершён — изменение статуса заблокировано."

    if code == "ROADMAP_CANCELLED":
        return "❌ Roadmap этого Task отменён — изменение статуса заблокировано."

    log.warning(f"_task_transition_message: unmapped code={code!r} task_id={task_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _task_assignment_message(result: dict, task_id: str) -> str:
    """
    Render any business_builder.assign_task()/unassign_task() result.
    Shared by /assigntask, /reassigntask, and /unassigntask — the
    distinct outcomes (created/reused/reassigned/unassigned) are
    already carried in `code` by the orchestrator, never re-derived
    here.
    """
    code = result.get("code", "")

    if code == "TASK_ASSIGNMENT_CREATED":
        return "\n".join([
            "✅ Task назначен",
            f"Task ID: `{task_id}`",
            f"Assignment ID: `{result.get('assignment_id', '')}`",
        ])

    if code == "TASK_ASSIGNMENT_REUSED":
        return "\n".join([
            "ℹ️ Уже назначен — активное назначение уже существует",
            f"Task ID: `{task_id}`",
            f"Assignment ID: `{result.get('assignment_id', '')}`",
        ])

    if code == "TASK_REASSIGNED":
        return "\n".join([
            "✅ Task переназначен",
            f"Task ID: `{task_id}`",
            f"Было: `{result.get('previous_assignment_id') or '—'}`",
            f"Стало: `{result.get('assignment_id', '')}`",
        ])

    if code == "TASK_UNASSIGNED":
        return f"✅ Task `{task_id}` снят с назначения."

    if code == "TASK_NOT_FOUND":
        return f"❌ Task `{task_id}` не найден."

    if code == "ROLE_NOT_FOUND":
        return "❌ Указанная Role не найдена."

    if code == "ROLE_PAUSED":
        return "❌ Role приостановлена (paused) — назначение не разрешено."

    if code == "ROLE_ARCHIVED":
        return "❌ Role архивирована — назначение не разрешено."

    if code == "ROLE_NOT_ACTIVE_FOR_TASK_EXECUTION":
        return "❌ Role ещё planned — Person не может быть назначен как активный исполнитель, пока Role не станет active."

    if code == "DEPARTMENT_NOT_FOUND":
        return "❌ Department этой Role не найден."

    if code == "DEPARTMENT_ARCHIVED":
        return "❌ Department этой Role архивирован — назначение не разрешено."

    if code == "PERSON_NOT_FOUND":
        return "❌ Указанный Person не найден."

    if code == "PERSON_ARCHIVED":
        return "❌ Person архивирован — назначение не разрешено."

    if code == "PERSON_NOT_LINKED_TO_BUSINESS":
        return "❌ Person не привязан к бизнесу этого Task."

    if code == "PERSON_TASK_BUSINESS_MISMATCH":
        return "❌ Person привязан к другому бизнесу, не к бизнесу этого Task."

    if code == "MULTIPLE_ACTIVE_TASK_ASSIGNMENTS_INTEGRITY_ERROR":
        ids = ", ".join(f"`{a}`" for a in result.get("conflicting_assignment_ids", ())) or "—"
        return "\n".join([
            "⚠️ Обнаружен конфликт целостности данных",
            f"Task ID: `{task_id}`",
            f"Найдено несколько активных Task Assignment одновременно: {ids}",
            "Изменений не выполнено — автоматический выбор одного из них не выполняется.",
        ])

    log.warning(f"_task_assignment_message: unmapped code={code!r} task_id={task_id}")
    return f"❌ Ошибка ({code or 'unknown'}): {result.get('error') or 'см. логи'}"


def _task_detail_lines(task: dict) -> list[str]:
    """
    Read-only rendering of one Task's full detail for /bctask,
    including the assignment-cache consistency state. Never repairs an
    inconsistency, never silently picks among multiple active
    Assignments — only displays what the read-only helpers report.
    """
    from business_core.task_manager import get_current_task_assignment
    from business_core import business_builder as bb

    consistency = bb.task_assignment_cache_is_consistent(task["task_id"])

    lines = [
        f"📌 Task {task['task_id']}",
        "",
        f"Business ID: `{task['business_id']}`",
        f"Title: {task['title']}",
        f"Статус: {_task_status_ru(task['status'])}",
    ]
    if task.get("priority"):
        lines.append(f"Priority: {task['priority']}")
    if task.get("due_date"):
        lines.append(f"Due Date: {task['due_date']}")
    for label, key in (
        ("Client ID", "client_id"), ("Object ID", "object_id"), ("Service ID", "service_id"),
        ("Roadmap ID", "roadmap_id"), ("Stage ID", "stage_id"),
    ):
        if task.get(key):
            lines.append(f"{label}: `{task[key]}`")

    lines.append(f"Responsible Role ID: `{task.get('responsible_role_id') or '—'}`")
    lines.append(f"Assignee Person ID: `{task.get('assignee_person_id') or '—'}`")

    current = get_current_task_assignment(task["task_id"])
    if current:
        lines.append(f"Active Assignment ID: `{current['task_assignment_id']}`")

    if not consistency.get("ok"):
        lines.append("⚠️ Не удалось проверить согласованность назначения.")
    elif consistency.get("consistent"):
        lines.append("✅ Assignment cache согласован")
    else:
        lines.append("⚠️ Assignment cache РАССОГЛАСОВАН с историей — требуется проверка (не исправляется автоматически)")

    for label, key in (
        ("Created At", "created_at"), ("Updated At", "updated_at"),
        ("Started At", "started_at"), ("Completed At", "completed_at"), ("Cancelled At", "cancelled_at"),
    ):
        if task.get(key):
            lines.append(f"{label}: {task[key]}")

    if task.get("source"):
        lines.append(f"Source: {task['source']}")
    if task.get("created_by"):
        lines.append(f"Created By: {task['created_by']}")
    if task.get("gtd_action_id"):
        lines.append(f"GTD Action ID: `{task['gtd_action_id']}`")

    return lines


async def newbctask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newbctask business_id=BIZ-001 title="..." [status=new]
               [source=telegram] [idempotency_key=...]
               [client_id=...] [object_id=...] [service_id=...]
               [roadmap_id=...] [stage_id=...] [priority=...] [due_date=...]

    Idempotency Key defaults to a deterministic, request-scoped value
    derived from the Telegram update ID when omitted — never a blank
    key on this path (ADR-019 §10/§23).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    business_id = args.get("business_id", "")
    title = args.get("title", "")

    if not business_id or not title:
        await _reply(update,
            "❌ Укажи business_id и title.\n\nПример:\n"
            '`/newbctask business_id=BIZ-001 title="Подготовить документы"`'
        )
        return

    try:
        from business_core.business_builder import create_business_task

        idempotency_key = args.get("idempotency_key", "") or f"tg-{update.update_id}"
        result = create_business_task(
            business_id, title,
            description=args.get("description", ""),
            priority=args.get("priority", ""),
            due_date=args.get("due_date", ""),
            source=args.get("source", "telegram"),
            idempotency_key=idempotency_key,
            client_id=args.get("client_id", ""),
            object_id=args.get("object_id", ""),
            service_id=args.get("service_id", ""),
            roadmap_id=args.get("roadmap_id", ""),
            stage_id=args.get("stage_id", ""),
            created_by=str(update.effective_user.id) if update.effective_user else "",
        )
        await _reply(update, _task_creation_message(result))
    except Exception as e:
        log.error(f"newbctask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при создании Task.")


async def bctasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bctasks [business_id=BIZ-001] [status=ready] [roadmap_id=RM-001]
             [stage_id=STAGE-001] [role_id=ROLE-001] [person_id=PRS-001]

    Read-only. Exact filters only — no fuzzy matching. Never reads
    personal GTD Next Actions.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    try:
        from business_core.task_manager import list_tasks

        tasks = list_tasks(
            business_id=args.get("business_id", ""), status=args.get("status", ""),
            roadmap_id=args.get("roadmap_id", ""), stage_id=args.get("stage_id", ""),
            role_id=args.get("role_id", ""), person_id=args.get("person_id", ""),
        )

        if not tasks:
            await _reply(update, "📋 *Business Tasks*\n\nПусто. Создай первый: /newbctask")
            return

        lines = [f"📋 *Business Tasks* ({len(tasks)} шт.)\n"]
        for t in tasks[:30]:
            line = f"`{t['task_id']}` {t['title']} — {_task_status_ru(t['status'])}"
            if t.get("due_date"):
                line += f" (до {t['due_date']})"
            lines.append(line)
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"bctasks_cmd error: {e}")
        await _reply(update, "❌ Ошибка при получении списка Task.")


async def bctask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bctask task_id=TSK-001

    Read-only exact-ID Task detail, including assignment-cache
    consistency state.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    task_id = args.get("task_id") or args.get("_pos0", "")

    if not task_id:
        await _reply(update, "❌ Укажи task_id.\n\nПример: /bctask task_id=TSK-001")
        return

    try:
        from business_core.task_manager import find_task_by_id

        task = find_task_by_id(task_id)
        if not task:
            await _reply(update, f"❌ Task {task_id} не найден.")
            return

        await _reply(update, "\n".join(_task_detail_lines(task)))
    except Exception as e:
        log.error(f"bctask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при получении карточки Task.")


async def updatetask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /updatetask task_id=TSK-001 priority=high due_date=2026-08-01
    /updatetask task_id=TSK-001 status=in_progress

    Status and admin fields are never mixed in one call — Phase 36D
    foundation UX rejects a combined update and asks for two separate
    commands, so admin-field policy and transition policy never share
    a single ambiguous write (ADR-019 §12).
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    task_id = args.get("task_id", "")

    if not task_id:
        await _reply(update, "❌ Укажи task_id.\n\nПример:\n"
            "`/updatetask task_id=TSK-001 priority=high`\n"
            "`/updatetask task_id=TSK-001 status=in_progress`"
        )
        return

    admin_keys = {"title", "description", "priority", "due_date", "created_by", "gtd_action_id"}
    has_status = "status" in args
    has_admin = any(k in args for k in admin_keys)

    if has_status and has_admin:
        await _reply(update,
            "❌ Нельзя одновременно менять статус и admin-поля.\n"
            "Отправь две отдельные команды:\n"
            "`/updatetask task_id=... status=...`\n"
            "`/updatetask task_id=... priority=... due_date=...`"
        )
        return

    if not has_status and not has_admin:
        await _reply(update, "❌ Укажи либо status=..., либо admin-поля (priority/due_date/title/description/created_by/gtd_action_id).")
        return

    try:
        if has_status:
            from business_core.business_builder import transition_task_status
            result = transition_task_status(task_id, args["status"])
            await _reply(update, _task_transition_message(result, task_id))
            return

        from business_core.business_builder import update_task_admin_fields

        field_key_map = {
            "title": "Title", "description": "Description", "priority": "Priority",
            "due_date": "Due Date", "created_by": "Created By", "gtd_action_id": "GTD Action ID",
        }
        updates = {field_key_map[k]: v for k, v in args.items() if k in admin_keys}
        result = update_task_admin_fields(task_id, updates)
        await _reply(update, _task_admin_message(result, task_id))
    except Exception as e:
        log.error(f"updatetask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при обновлении Task.")


async def assigntask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /assigntask task_id=TSK-001 [role_id=ROLE-001] [person_id=PRS-001]
                [assignment_type=primary]
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    task_id = args.get("task_id", "")
    role_id = args.get("role_id", "")
    person_id = args.get("person_id", "")

    if not task_id or (not role_id and not person_id):
        await _reply(update,
            "❌ Укажи task_id и хотя бы одно из role_id/person_id.\n\nПример:\n"
            "`/assigntask task_id=TSK-001 role_id=ROLE-001 person_id=PRS-001`"
        )
        return

    try:
        from business_core.business_builder import assign_task

        result = assign_task(
            task_id, responsible_role_id=role_id, assignee_person_id=person_id,
            assignment_type=args.get("assignment_type", "primary"),
        )
        await _reply(update, _task_assignment_message(result, task_id))
    except Exception as e:
        log.error(f"assigntask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при назначении Task.")


async def reassigntask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /reassigntask task_id=TSK-001 [role_id=ROLE-002] [person_id=PRS-002]
                  [assignment_type=primary]

    Uses the same canonical assign_task() orchestration as /assigntask —
    it already distinguishes created/reused/reassigned via `code`
    (ADR-019 §20), so this command is a thin syntactic alias with no
    separate policy of its own.
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    task_id = args.get("task_id", "")
    role_id = args.get("role_id", "")
    person_id = args.get("person_id", "")

    if not task_id or (not role_id and not person_id):
        await _reply(update,
            "❌ Укажи task_id и хотя бы одно из role_id/person_id.\n\nПример:\n"
            "`/reassigntask task_id=TSK-001 role_id=ROLE-002`"
        )
        return

    try:
        from business_core.business_builder import assign_task

        result = assign_task(
            task_id, responsible_role_id=role_id, assignee_person_id=person_id,
            assignment_type=args.get("assignment_type", "primary"),
        )
        await _reply(update, _task_assignment_message(result, task_id))
    except Exception as e:
        log.error(f"reassigntask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при переназначении Task.")


async def unassigntask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /unassigntask task_id=TSK-001
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    args = _parse_kv_args(raw)
    task_id = args.get("task_id") or args.get("_pos0", "")

    if not task_id:
        await _reply(update, "❌ Укажи task_id.\n\nПример: /unassigntask task_id=TSK-001")
        return

    try:
        from business_core.business_builder import unassign_task

        result = unassign_task(task_id)
        await _reply(update, _task_assignment_message(result, task_id))
    except Exception as e:
        log.error(f"unassigntask_cmd error: {e}")
        await _reply(update, "❌ Ошибка при снятии назначения Task.")


def register_business_handlers(app: Application) -> None:
    """
    Зарегистрировать все Business Core handlers в приложении.

    Вызывается из telegram_bot.py main() одной строкой:
        register_business_handlers(app)
    """

    # ConversationHandler — создание дорожной карты
    newroadmap_handler = ConversationHandler(
        entry_points=[CommandHandler("newroadmap", newroadmap_start)],
        states={
            NR_BUSINESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_business)],
            NR_CLIENT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_client)],
            NR_SERVICE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_service)],
            NR_CITY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_city)],
            NR_DAYS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_days)],
            NR_CONFIRM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, newroadmap_confirm)],
        },
        fallbacks=[CommandHandler("cancel", newroadmap_cancel)],
        allow_reentry=True,
    )

    # ConversationHandler — добавление клиента
    newclient_handler = ConversationHandler(
        entry_points=[CommandHandler("newclient", newclient_start)],
        states={
            NC_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, newclient_name)],
            NC_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, newclient_phone)],
            NC_TYPE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, newclient_type)],
            NC_BIZ:     [MessageHandler(filters.TEXT & ~filters.COMMAND, newclient_biz)],
            NC_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, newclient_confirm)],
        },
        fallbacks=[CommandHandler("cancel", newclient_cancel)],
        allow_reentry=True,
    )

    # ConversationHandler — создание бизнеса
    newbiz_handler = ConversationHandler(
        entry_points=[CommandHandler("newbiz", newbiz_start)],
        states={
            NB_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, newbiz_name)],
            NB_CITIES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, newbiz_cities)],
            NB_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, newbiz_priority)],
            NB_CONFIRM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, newbiz_confirm)],
        },
        fallbacks=[CommandHandler("cancel", newbiz_cancel)],
        allow_reentry=True,
    )

    # ConversationHandler — редактирование клиента (Phase 13A)
    editclient_handler = ConversationHandler(
        entry_points=[CommandHandler("editclient", editclient_start)],
        states={
            EC_FIELD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, editclient_field)],
            EC_VALUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, editclient_value)],
            EC_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, editclient_confirm)],
        },
        fallbacks=[CommandHandler("cancel", editclient_cancel)],
        allow_reentry=True,
    )

    # ConversationHandler — редактирование объекта (Phase 13A)
    editobject_handler = ConversationHandler(
        entry_points=[CommandHandler("editobject", editobject_start)],
        states={
            EO_FIELD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, editobject_field)],
            EO_VALUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, editobject_value)],
            EO_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, editobject_confirm)],
        },
        fallbacks=[CommandHandler("cancel", editobject_cancel)],
        allow_reentry=True,
    )

    # Регистрируем ConversationHandlers первыми
    app.add_handler(newroadmap_handler)
    app.add_handler(newclient_handler)
    app.add_handler(newbiz_handler)
    app.add_handler(editclient_handler)
    app.add_handler(editobject_handler)

    # Phase 14A: Stage Management Core — пять точечных редакторов этапа,
    # каждый со своим entry point, все делят один общий SE_CONFIRM helper.
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("assignstage", assignstage_start)],
        states={SE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, assignstage_confirm)]},
        fallbacks=[CommandHandler("cancel", assignstage_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("duedate", duedate_start)],
        states={SE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, duedate_confirm)]},
        fallbacks=[CommandHandler("cancel", duedate_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("priority", priority_start)],
        states={SE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, priority_confirm)]},
        fallbacks=[CommandHandler("cancel", priority_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("blockstage", blockstage_start)],
        states={SE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, blockstage_confirm)]},
        fallbacks=[CommandHandler("cancel", blockstage_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("unblockstage", unblockstage_start)],
        states={SE_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, unblockstage_confirm)]},
        fallbacks=[CommandHandler("cancel", unblockstage_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(CommandHandler("stage", stage_cmd))

    # Phase 15A: Document Registry Foundation
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("registerdoc", registerdoc_start)],
        states={RD_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, registerdoc_confirm)]},
        fallbacks=[CommandHandler("cancel", registerdoc_cancel)],
        allow_reentry=True,
    ))
    app.add_handler(CommandHandler("doc", doc_cmd))
    app.add_handler(CommandHandler("docs4stage", docs4stage_cmd))
    app.add_handler(CommandHandler("updatedoc", updatedoc_cmd))
    app.add_handler(CommandHandler("syncstageknowledge", syncstageknowledge_cmd))

    # Phase 15B: Telegram Document Upload Foundation
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("uploaddoc", uploaddoc_start)],
        states={
            UD_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, uploaddoc_receive_file)],
            UD_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, uploaddoc_receive_details)],
            UD_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, uploaddoc_confirm)],
        },
        fallbacks=[CommandHandler("cancel", uploaddoc_cancel)],
        allow_reentry=True,
    ))

    # Phase 16A: Document Intelligence Foundation
    app.add_handler(CommandHandler("analyzedoc", analyzedoc_cmd))
    app.add_handler(CommandHandler("docanalysis", docanalysis_cmd))

    # Phase 17B: Telegram Document Requirements Interface
    app.add_handler(CommandHandler("missingdocs", missingdocs_cmd))
    app.add_handler(CommandHandler("docsrequired", docsrequired_cmd))

    # Простые команды
    app.add_handler(CommandHandler("bc",        bc_dashboard))
    app.add_handler(CommandHandler("bcstatus",  bc_status))
    app.add_handler(CommandHandler("roadmaps",  show_roadmaps))
    app.add_handler(CommandHandler("clients",   show_clients))
    app.add_handler(CommandHandler("bcdrive",   bc_drive))
    app.add_handler(CommandHandler("initbc",    init_bc))
    # Phase 7A
    app.add_handler(CommandHandler("newobject",    newobject_cmd))
    app.add_handler(CommandHandler("objects",      objects_cmd))
    # Phase 7B
    app.add_handler(CommandHandler("startroadmap", startroadmap_cmd))
    app.add_handler(CommandHandler("stages",       stages_cmd))
    # Phase 9B
    app.add_handler(CommandHandler("updatestage",  updatestage_cmd))
    # Phase 9D
    app.add_handler(CommandHandler("recalcprogress", recalcprogress_cmd))
    # Phase 8A
    app.add_handler(CommandHandler("newservice",       newservice_cmd))
    app.add_handler(CommandHandler("services",         services_cmd))
    app.add_handler(CommandHandler("service",          service_detail_cmd))
    # Phase 8B
    app.add_handler(CommandHandler("newrtemplate",     newrtemplate_cmd))
    app.add_handler(CommandHandler("rtemplates",       rtemplates_cmd))
    app.add_handler(CommandHandler("addrtemplatestage",addrtemplatestage_cmd))
    app.add_handler(CommandHandler("rtemplatestages",  rtemplatestages_cmd))
    # Phase 8C
    app.add_handler(CommandHandler("newsop",           newsop_cmd))
    app.add_handler(CommandHandler("newchecklist",     newchecklist_cmd))
    app.add_handler(CommandHandler("newdoctemplate",   newdoctemplate_cmd))
    app.add_handler(CommandHandler("newfaq",           newfaq_cmd))
    app.add_handler(CommandHandler("linkknowledge",    linkknowledge_cmd))
    app.add_handler(CommandHandler("stageknowledge",   stageknowledge_cmd))
    app.add_handler(CommandHandler("sop",              sop_cmd))
    # Phase A: Stage Output Foundation — Required Output.
    app.add_handler(CommandHandler("newoutput",        newoutput_cmd))
    app.add_handler(CommandHandler("linkoutput",       linkoutput_cmd))
    app.add_handler(CommandHandler("syncoutputs",      syncoutputs_cmd))
    app.add_handler(CommandHandler("outputs",          outputs_cmd))
    app.add_handler(CommandHandler("output",           output_cmd))
    app.add_handler(CommandHandler("updateoutput",     updateoutput_cmd))
    app.add_handler(CommandHandler("submitoutput",     submitoutput_cmd))
    app.add_handler(CommandHandler("acceptoutput",     acceptoutput_cmd))
    app.add_handler(CommandHandler("rejectoutput",     rejectoutput_cmd))
    app.add_handler(CommandHandler("waiveoutput",      waiveoutput_cmd))
    # Phase 38D (ADR-021): Checklist Domain — operational commands.
    # Phase 1: Checklist Relation Foundation.
    app.add_handler(CommandHandler("linkchecklist",    linkchecklist_cmd))
    app.add_handler(CommandHandler("syncchecklists",   syncchecklists_cmd))
    app.add_handler(CommandHandler("startchecklist",   startchecklist_cmd))
    app.add_handler(CommandHandler("checklists",       checklists_cmd))
    app.add_handler(CommandHandler("checklist",        checklist_cmd))
    app.add_handler(CommandHandler("updatecheckitem",  updatecheckitem_cmd))
    app.add_handler(CommandHandler("updatechecklist",  updatechecklist_cmd))
    # Phase 39D (ADR-022): Payment/Milestone Domain — operational commands.
    app.add_handler(CommandHandler("newpaymenttemplate",     newpaymenttemplate_cmd))
    app.add_handler(CommandHandler("paymenttemplates",       paymenttemplates_cmd))
    app.add_handler(CommandHandler("paymenttemplate",        paymenttemplate_cmd))
    app.add_handler(CommandHandler("updatepaymenttemplate",  updatepaymenttemplate_cmd))
    app.add_handler(CommandHandler("newobligation",          newobligation_cmd))
    app.add_handler(CommandHandler("obligations",            obligations_cmd))
    app.add_handler(CommandHandler("obligation",             obligation_cmd))
    app.add_handler(CommandHandler("updateobligation",       updateobligation_cmd))
    app.add_handler(CommandHandler("recordpayment",          recordpayment_cmd))
    app.add_handler(CommandHandler("payments",               payments_cmd))
    app.add_handler(CommandHandler("payment",                payment_cmd))
    app.add_handler(CommandHandler("confirmpayment",         confirmpayment_cmd))
    app.add_handler(CommandHandler("reversepayment",         reversepayment_cmd))
    app.add_handler(CommandHandler("failpayment",            failpayment_cmd))
    # Phase 40D (ADR-023): Commercial Offer Domain — operational commands.
    app.add_handler(CommandHandler("newoffer",         newoffer_cmd))
    app.add_handler(CommandHandler("offers",           offers_cmd))
    app.add_handler(CommandHandler("offer",            offer_cmd))
    app.add_handler(CommandHandler("reviseoffer",      reviseoffer_cmd))
    app.add_handler(CommandHandler("updateoffer",      updateoffer_cmd))
    app.add_handler(CommandHandler("sendoffer",        sendoffer_cmd))
    app.add_handler(CommandHandler("acceptoffer",      acceptoffer_cmd))
    app.add_handler(CommandHandler("rejectoffer",      rejectoffer_cmd))
    app.add_handler(CommandHandler("expireoffer",      expireoffer_cmd))
    app.add_handler(CommandHandler("canceloffer",      canceloffer_cmd))
    app.add_handler(CommandHandler("archiveoffer",     archiveoffer_cmd))
    # Phase 41D (ADR-024): Lead / Sales Funnel Domain — operational commands.
    app.add_handler(CommandHandler("newlead",          newlead_cmd))
    app.add_handler(CommandHandler("leads",            leads_cmd))
    app.add_handler(CommandHandler("lead",             lead_cmd))
    app.add_handler(CommandHandler("updatelead",       updatelead_cmd))
    app.add_handler(CommandHandler("contactlead",      contactlead_cmd))
    app.add_handler(CommandHandler("qualifylead",      qualifylead_cmd))
    app.add_handler(CommandHandler("unqualifylead",    unqualifylead_cmd))
    app.add_handler(CommandHandler("loselead",         loselead_cmd))
    app.add_handler(CommandHandler("convertlead",      convertlead_cmd))
    app.add_handler(CommandHandler("archivelead",      archivelead_cmd))
    # Phase 42D (ADR-025): Interaction / Communication History Domain — operational commands.
    app.add_handler(CommandHandler("newinteraction",        newinteraction_cmd))
    app.add_handler(CommandHandler("interactions",           interactions_cmd))
    app.add_handler(CommandHandler("interaction",            interaction_cmd))
    app.add_handler(CommandHandler("archiveinteraction",     archiveinteraction_cmd))
    app.add_handler(CommandHandler("updateinteractionnotes", updateinteractionnotes_cmd))
    # Phase 8D
    app.add_handler(CommandHandler("milestones",       milestones_cmd))
    # Phase 11B
    app.add_handler(CommandHandler("report",           report_cmd))
    # Phase 12A
    app.add_handler(CommandHandler("version",          version_cmd))
    # Phase 21F: Organization Layer
    app.add_handler(CommandHandler("newdept",          newdept_cmd))
    app.add_handler(CommandHandler("newrole",          newrole_cmd))
    app.add_handler(CommandHandler("roles",            roles_cmd))
    app.add_handler(CommandHandler("roledetails",      roledetails_cmd))
    app.add_handler(CommandHandler("assignrole",       assignrole_cmd))
    # Phase 22D: Work Execution Layer
    app.add_handler(CommandHandler("assignstagerole",   assignstagerole_cmd))
    app.add_handler(CommandHandler("reassignstagerole", reassignstagerole_cmd))
    app.add_handler(CommandHandler("stageresponsibility", stageresponsibility_cmd))
    # Phase 36D: Task Domain (ADR-019) — deliberately NOT "/tasks", which
    # remains GTD-owned (telegram_bot.py's show_tasks()).
    app.add_handler(CommandHandler("newbctask",      newbctask_cmd))
    app.add_handler(CommandHandler("bctasks",        bctasks_cmd))
    app.add_handler(CommandHandler("bctask",         bctask_cmd))
    app.add_handler(CommandHandler("updatetask",     updatetask_cmd))
    app.add_handler(CommandHandler("assigntask",     assigntask_cmd))
    app.add_handler(CommandHandler("reassigntask",   reassigntask_cmd))
    app.add_handler(CommandHandler("unassigntask",   unassigntask_cmd))

    # Callback handler для кнопок подтверждения бизнес-контекста (Фаза 5B)
    app.add_handler(CallbackQueryHandler(bc_ctx_callback, pattern=r"^bc_ctx:"))

    log.info(
        "Business Core handlers зарегистрированы: "
        "/bc /bcstatus /roadmaps /clients /newroadmap /newclient /newbiz /initbc /bcdrive "
        "/newobject /objects /startroadmap /stages /updatestage /recalcprogress "
        "/newservice /services /service "
        "/milestones /report "
        "/newdept /newrole /roles /roledetails /assignrole "
        "/assignstagerole /reassignstagerole /stageresponsibility "
        "/newbctask /bctasks /bctask /updatetask /assigntask /reassigntask /unassigntask "
        "+ bc_ctx callback (Фаза 5B)"
    )
