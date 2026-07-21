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

        # Клиенты
        try:
            ppl_rows = read_business_sheet("people_registry")
            clients = [r for r in ppl_rows if "клиент" in r.get("Тип", "").lower()]
            lines.append(f"\n👥 *Клиенты:* {len(clients)} / {len(ppl_rows)} людей")
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

        from business_core.sheets import read_business_sheet

        rows = read_business_sheet("roadmaps")
        if not rows:
            await _reply(update,
                "🗺 *Дорожные карты*\n\n"
                "Пусто. Создай первую: /newroadmap"
            )
            return

        # Применить фильтры
        if filter_obj_id:
            rows = [r for r in rows if r.get("Object ID", "") == filter_obj_id]
        if filter_biz_id:
            rows = [r for r in rows if r.get("Business ID", "") == filter_biz_id]
        if filter_client_id:
            rows = [r for r in rows if r.get("Client ID", "") == filter_client_id]

        active = [r for r in rows if r.get("Status", "") not in ("completed", "cancelled")]
        done   = [r for r in rows if r.get("Status", "") == "completed"]

        filter_info = ""
        if filter_obj_id:
            filter_info = f" | obj: {filter_obj_id}"
        elif filter_biz_id:
            filter_info = f" | biz: {filter_biz_id}"
        elif filter_client_id:
            filter_info = f" | client: {filter_client_id}"

        lines = [f"🗺 *Дорожные карты* ({len(active)} активных{filter_info})\n"]

        for r in active:
            rm_id    = r.get("Roadmap ID", "?")
            client   = r.get("Client Name", "?")
            city     = r.get("City", "")
            biz_id   = r.get("Business ID", "")
            obj_id   = r.get("Object ID", "")
            svc_id   = r.get("Service ID", "")
            case_t   = r.get("Case Type", "")
            progress = r.get("Progress %", "0")

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
            for i in range(1, 11):
                stage_status = r.get(f"Stage {i} Status", "")
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

    query = " ".join(context.args).strip().lower() if context.args else ""

    try:
        from business_core.sheets import read_business_sheet

        rows = read_business_sheet("people_registry")
        if not rows:
            await _reply(update,
                "👥 *Клиенты*\n\nПусто. Добавь первого: /newclient"
            )
            return

        clients = [r for r in rows if "клиент" in r.get("Тип", "").lower()]

        # Фильтр по запросу
        if query:
            clients = [
                r for r in clients
                if query in r.get("ФИО", "").lower()
                or query in r.get("Имя", "").lower()
                or query in r.get("Телефон", "").lower()
            ]

        if not clients:
            msg = f"👥 Клиент *{query}* не найден." if query else "👥 Клиентов нет."
            await _reply(update, msg + "\n\nДобавь: /newclient")
            return

        total_clients = len([r for r in rows if "клиент" in r.get("Тип", "").lower()])
        header = f"👥 *Клиенты*"
        if query:
            header += f" — поиск: _{query}_"
        header += f" ({len(clients)}"
        if not query:
            header += f" / {len(rows)} людей"
        header += ")"

        lines = [header, ""]
        for r in clients[:15]:
            prs_id = r.get("ID", "?")
            name   = r.get("ФИО", r.get("Имя", "?"))
            phone  = r.get("Телефон", "")
            city   = r.get("Город", "")
            bizs   = r.get("Бизнесы", "")

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
    text = update.message.text.strip()
    context.user_data["nr"]["client_name"] = text

    # Ищем client_id в People Registry
    try:
        from business_core.sheets import read_business_sheet
        from business_core.business_router import _find_client_in_text
        rows = read_business_sheet("people_registry")
        people = [
            {"id": r.get("ID", ""), "full_name": r.get("ФИО", ""), "short_name": r.get("Имя", "")}
            for r in rows
        ]
        cid, cname, _ = _find_client_in_text(text, people)
        if cid:
            context.user_data["nr"]["client_id"] = cid
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

    # Находим service_id
    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("service_catalog")
        biz_id = context.user_data["nr"].get("business_id", "")
        for r in rows:
            if text.lower() in r.get("Название", "").lower():
                if not biz_id or r.get("Бизнес ID", "") == biz_id:
                    context.user_data["nr"]["service_id"] = r.get("ID", "")
                    break
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

    try:
        from business_core.sheets import (
            read_business_sheet, append_business_row, generate_next_id
        )
        from business_core.roadmap_manager import (
            create_roadmap, get_stage_template
        )
        from datetime import date, timedelta

        # Генерируем ID
        rm_id = generate_next_id("roadmaps", "RM")
        template = get_stage_template(
            nr.get("service_id", ""),
            nr.get("service_name", ""),
        )
        expected = (date.today() + timedelta(days=nr.get("expected_days", 60))).isoformat()

        # Формируем строку для ROADMAPS
        stage_statuses = ["not_started"] * 10
        row_values = [
            rm_id,
            nr.get("business_id", ""),
            nr.get("service_id", ""),
            nr.get("city", ""),
            nr.get("client_id", ""),
            nr.get("client_name", ""),
            "",          # GTD Project ID — заполнить позже
            "Дидар",     # Responsible
            "active",
            datetime.now().strftime("%Y-%m-%d"),
            expected,
            "0",         # Progress %
        ] + stage_statuses[:10] + [""]  # Notes

        append_business_row("roadmaps", row_values)

        # Строки этапов
        for i, tmpl in enumerate(template, start=1):
            stage_id = f"STAGE-{rm_id.replace('RM-', '')}-{i:02d}"
            stage_row = [
                stage_id, rm_id, str(i), tmpl["name"],
                "not_started", "", "", "", "Дидар",
                ", ".join(tmpl.get("docs_required", [])), "", "",
            ]
            append_business_row("roadmap_stages", stage_row)

        # Обновляем кеш inbox_bridge
        try:
            from business_core.inbox_bridge import invalidate_cache
            invalidate_cache()
        except Exception:
            pass

        await update.message.reply_text(
            f"✅ *Дорожная карта создана!*\n\n"
            f"🆔 ID: `{rm_id}`\n"
            f"👤 Клиент: {nr.get('client_name', '?')}\n"
            f"🛠 Услуга: {nr.get('service_name', '?')}\n"
            f"📋 Этапов: {len(template)}\n\n"
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
        from business_core.sheets import (
            append_business_row,
            generate_next_id,
            get_business_sheet,
            row_from_header_map,
        )
        from business_core.business_builder import (
            find_existing_person,
            add_biz_id_to_person,
            update_person_drive_info,
            provision_client_drive,
            save_client_drive_to_sheets,
            normalize_biz_ids,
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

        # ── Phase 6B: расширенная дедупликация ───────────────────
        existing = find_existing_person(
            name=full_name,
            phone=phone,
            biz_id=biz_id_resolved or None,
        )

        STATUS_NEW           = "new"
        STATUS_SAME_BIZ      = "same_biz"
        STATUS_OTHER_BIZ     = "other_biz"

        if existing is None:
            client_status = STATUS_NEW
            prs_id = None
        elif existing.get("same_biz", True):
            client_status = STATUS_SAME_BIZ
            prs_id = existing["prs_id"]
        else:
            client_status = STATUS_OTHER_BIZ
            prs_id = existing["prs_id"]

        # ── Создание новой записи ─────────────────────────────────
        if client_status == STATUS_NEW:
            prs_id     = generate_next_id("people_registry", "PRS")
            parts      = full_name.split()
            short_name = parts[0] if parts else full_name
            now        = datetime.now().strftime("%Y-%m-%d")

            biz_ids_val     = biz_id_resolved if biz_id_resolved else ""
            primary_biz_val = biz_id_resolved if biz_id_resolved else ""

            # Phase 10.2B.4: строка формируется по ФАКТИЧЕСКИМ заголовкам
            # листа PEOPLE_REGISTRY, а не по жёсткой позиции — не зависит
            # от порядка колонок и не смещает значения в чужие колонки
            # (см. Phase 10.2B.3: подтверждённое смещение "active"/"тёплый").
            sheet   = get_business_sheet("people_registry")
            headers = sheet.row_values(1)

            required_headers = [
                "ID", "ФИО", "Телефон",
                "Статус отношений", "Теплота", "Комментарий",
                "Biz IDs", "Primary Biz ID",
                "Дата первого контакта", "Дата последнего контакта",
            ]
            missing_headers = [h for h in required_headers if h not in headers]
            if missing_headers:
                raise ValueError(
                    f"PEOPLE_REGISTRY: отсутствуют обязательные колонки {missing_headers}. "
                    f"Запись клиента остановлена, ничего не записано."
                )

            row_values = row_from_header_map(headers, {
                "ID":     prs_id,
                "ФИО":    full_name,
                "Имя":    short_name,
                "Телефон": phone,
                "Тип":    nc.get("person_type", "клиент"),
                "Бизнесы": biz_name,
                "Уровень доверия": "средний",
                "Дата первого контакта":    now,
                "Дата последнего контакта": now,
                "Статус отношений": "active",
                "Теплота":           "тёплый",
                "Biz IDs":           biz_ids_val,
                "Primary Biz ID":    primary_biz_val,
            })
            append_business_row("people_registry", row_values)

            try:
                from business_core.inbox_bridge import invalidate_cache
                invalidate_cache()
            except Exception:
                pass

        # ── Добавление biz_id к существующему контакту ───────────
        elif client_status == STATUS_OTHER_BIZ and biz_id_resolved:
            try:
                add_biz_id_to_person(prs_id, biz_id_resolved)
            except Exception as exc:
                log.warning(f"newclient add_biz_id error: {exc}")

        # ── Drive ─────────────────────────────────────────────────
        drive_msg = ""
        if biz_name:
            # Уже есть Drive-ссылка — показываем её
            if existing and existing.get("drive_url"):
                drive_msg = f"\n📁 Drive: {existing['drive_url']}"
            else:
                # Создаём/получаем Drive-папку
                try:
                    drive_result = provision_client_drive(
                        prs_id=prs_id,
                        full_name=full_name,
                        biz_name=biz_name,
                    )
                    if drive_result["ok"]:
                        # Сохраняем в таблицу (идемпотентно — только если пусто)
                        if client_status == STATUS_NEW:
                            save_client_drive_to_sheets(
                                prs_id, drive_result["folder_id"], drive_result["folder_url"]
                            )
                        else:
                            update_person_drive_info(
                                prs_id, drive_result["folder_id"], drive_result["folder_url"]
                            )
                        drive_msg = f"\n📁 Drive: {drive_result['folder_url']}"
                    else:
                        err = drive_result.get("error", "")
                        if err and "не задан" not in err:
                            drive_msg = f"\n⚠️ Папка Drive не создана: {err}"
                except Exception as drive_exc:
                    log.warning(f"newclient Drive error: {drive_exc}")

        # ── Ответ ─────────────────────────────────────────────────
        # Phase 11J: запись уже сохранена в Sheets к этому моменту —
        # ошибка форматирования ответа не должна выглядеть как ошибка
        # сохранения. parse_mode=None (без Markdown) — full_name и
        # drive_msg содержат динамические пользовательские данные и URL,
        # которые могут содержать "_"/"*"/"[" и ломать Markdown-парсер
        # (см. Phase 10.2D/11E: сломанный Drive URL с "_" вызывал
        # "Can't parse entities").
        if client_status == STATUS_NEW:
            header = "✅ Клиент добавлен!"
        elif client_status == STATUS_SAME_BIZ:
            header = "ℹ️ Клиент уже существует, использую существующую запись"
        else:
            header = "ℹ️ Контакт уже был в другом бизнесе, добавил связь с текущим бизнесом"

        try:
            await update.message.reply_text(
                f"{header}\n\n"
                f"🆔 ID: {prs_id}\n"
                f"👤 {full_name}"
                f"{drive_msg}\n\n"
                f"/clients — посмотреть всех клиентов",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as notify_exc:
            # Persistence (append_business_row / add_biz_id_to_person)
            # уже отработала успешно — сообщаем об успехе, а не о
            # несуществующей ошибке сохранения.
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("people_registry", client_id)
    if not found:
        await update.message.reply_text(f"❌ Клиент {client_id} не найден.")
        return ConversationHandler.END

    row_number, row = found
    context.user_data["ec"] = {
        "client_id": client_id,
        "row_number": row_number,
        "current": row,
    }
    context.user_data.pop("ec_confirmed_snapshot", None)

    lines = [
        "✏️ Редактирование клиента",
        "",
        f"ID: {client_id}",
        f"ФИО: {row.get('ФИО', '')}",
        f"Телефон: {row.get('Телефон', '')}",
        f"Бизнес: {row.get('Бизнесы', '')} (Biz IDs: {row.get('Biz IDs', '')})",
        f"Комментарий: {row.get('Комментарий', '')}",
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
        from business_core.sheets import find_row_by_id, get_business_sheet

        client_id = snap["client_id"]
        field_key = snap["field"]

        # Перечитываем строку прямо перед записью — защита от staleness
        # между показом карточки и подтверждением.
        found = find_row_by_id("people_registry", client_id)
        if not found:
            await update.message.reply_text(
                f"❌ Клиент {client_id} больше не найден — изменение не выполнено.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            row_number, _live_row = found
            sheet = get_business_sheet("people_registry")
            headers = sheet.row_values(1)

            def _col(name):
                return headers.index(name) + 1 if name in headers else None

            if field_key == "full_name":
                fio_col   = _col("ФИО")
                short_col = _col("Имя")
                if fio_col:
                    sheet.update_cell(row_number, fio_col, snap["new_value"])
                if short_col:
                    parts = snap["new_value"].split()
                    sheet.update_cell(row_number, short_col, parts[0] if parts else snap["new_value"])
            elif field_key == "phone":
                col = _col("Телефон")
                if col:
                    sheet.update_cell(row_number, col, snap["new_value"])
            elif field_key == "business":
                biz_ids_col     = _col("Biz IDs")
                primary_col     = _col("Primary Biz ID")
                biz_display_col = _col("Бизнесы")
                if biz_ids_col:
                    sheet.update_cell(row_number, biz_ids_col, snap["new_biz_id"])
                if primary_col:
                    sheet.update_cell(row_number, primary_col, snap["new_biz_id"])
                if biz_display_col:
                    sheet.update_cell(row_number, biz_display_col, snap["new_biz_name"])
            elif field_key == "notes":
                col = _col("Комментарий")
                if col:
                    sheet.update_cell(row_number, col, snap["new_value"])

            field_labels = {v: k for k, v in EDITCLIENT_FIELDS.items()}
            await update.message.reply_text(
                f"✅ Клиент {client_id} обновлён\n\n"
                f"Поле: {field_labels[field_key]}\n"
                f"Было: {snap['old_value_display'] or '—'}\n"
                f"Стало: {snap['new_value_display'] or '—'}",
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("object_registry", obj_id)
    if not found:
        await update.message.reply_text(f"❌ Объект {obj_id} не найден.")
        return ConversationHandler.END

    row_number, row = found
    context.user_data["eo"] = {
        "obj_id": obj_id,
        "row_number": row_number,
        "current": row,
    }
    context.user_data.pop("eo_confirmed_snapshot", None)

    lines = [
        "✏️ Редактирование объекта",
        "",
        f"OBJ ID: {obj_id}",
        f"Адрес: {row.get('Address', '')}",
        f"Тип объекта: {row.get('Object Type', '')}",
        f"Комментарий: {row.get('Notes', '')}",
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
        "address": current.get("Address", ""),
        "object_type": current.get("Object Type", ""),
        "notes": current.get("Notes", ""),
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
        from business_core.sheets import find_row_by_id, get_business_sheet
        from datetime import datetime as _dt

        obj_id = snap["obj_id"]
        field_key = snap["field"]

        found = find_row_by_id("object_registry", obj_id)
        if not found:
            await update.message.reply_text(
                f"❌ Объект {obj_id} больше не найден — изменение не выполнено.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            row_number, _live_row = found
            sheet = get_business_sheet("object_registry")
            headers = sheet.row_values(1)

            def _col(name):
                return headers.index(name) + 1 if name in headers else None

            field_to_column = {
                "address": "Address",
                "object_type": "Object Type",
                "notes": "Notes",
            }
            col = _col(field_to_column[field_key])
            if col:
                sheet.update_cell(row_number, col, snap["new_value"])

            last_updated_col = _col("Last Updated")
            if last_updated_col:
                sheet.update_cell(row_number, last_updated_col, _dt.now().strftime("%Y-%m-%d"))

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

        existing_svc = read_business_sheet("service_catalog")
        existing_svc_names = {r.get("Название", "").lower() for r in existing_svc}
        added_svc = 0

        for (name, biz_id, city, price_min, price_max, days) in default_services:
            if name.lower() in existing_svc_names:
                continue
            svc_id = generate_next_id("service_catalog", "SVC")
            row = [
                svc_id, biz_id, name,
                name.lower().replace(" ", "-"),
                "active", city, price_min, price_max, days,
                "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
            ]
            append_business_row("service_catalog", row)
            existing_svc_names.add(name.lower())
            added_svc += 1

        lines = [
            "✅ *Business Core инициализирован!*",
            "",
            f"🏢 Бизнесов добавлено: {added_biz} (пропущено: {skipped_biz})",
            f"🛠 Услуг добавлено: {added_svc}",
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
            add_biz_id_to_person,
            find_existing_person,
        )

        # Проверяем что клиент существует и связан с бизнесом
        try:
            from business_core.sheets import get_business_sheet
            prs_sheet  = get_business_sheet("people_registry")
            all_vals   = prs_sheet.get_all_values()
            client_row = None
            if len(all_vals) > 1:
                headers = all_vals[0]
                biz_ids_col = headers.index("Biz IDs") if "Biz IDs" in headers else None
                prim_col    = headers.index("Primary Biz ID") if "Primary Biz ID" in headers else None
                for row in all_vals[1:]:
                    if row and row[0] == client_id:
                        client_row = row
                        break
        except Exception:
            client_row = None

        if client_row is None:
            await _reply(update, f"❌ Клиент `{client_id}` не найден в PEOPLE_REGISTRY")
            return

        # Добавляем biz_id к клиенту если нужно
        try:
            biz_ids_in_row = []
            if biz_ids_col is not None and biz_ids_col < len(client_row):
                from business_core.business_builder import normalize_biz_ids
                biz_ids_in_row = normalize_biz_ids(client_row[biz_ids_col])
            if biz_id not in biz_ids_in_row:
                add_biz_id_to_person(client_id, biz_id)
        except Exception:
            pass

        # Создаём объект в OBJECT_REGISTRY
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

        # Drive (безопасно, не ломает создание объекта)
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
            if drive_res["ok"]:
                drive_msg = f"\n📁 [Drive папка]({drive_res['folder_url']})"
            elif drive_res.get("error") and "не задан" not in drive_res["error"] and "not configured" not in drive_res["error"]:
                drive_msg = f"\n⚠️ Drive папка не создана: {drive_res['error'][:60]}"
        except Exception as e:
            log.warning(f"newobject Drive error: {e}")

        # Ответ
        type_line = f"\nТип: {object_type}" if object_type else ""
        cadr_line = f"\nКадастр: {cadastral}" if cadastral else ""
        area_line = f"\nПлощадь: {area} м²" if area else ""

        await update.message.reply_text(
            f"✅ *Объект создан*\n\n"
            f"🆔 OBJ ID: `{obj_id}`\n"
            f"👤 Клиент: `{client_id}`\n"
            f"🏢 Бизнес: `{biz_id}`\n"
            f"📍 Город: {city}\n"
            f"🏠 Адрес: {address}"
            f"{type_line}{cadr_line}{area_line}\n"
            f"📊 Статус: new"
            f"{drive_msg}\n\n"
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
        from business_core.business_builder import find_objects_by_client
        from business_core.sheets import get_business_sheet

        # Получаем объекты
        if client_id:
            objects = find_objects_by_client(client_id, biz_id=biz_id or None)
        elif biz_id:
            # Все объекты по бизнесу — читаем лист напрямую
            sheet     = get_business_sheet("object_registry")
            all_vals  = sheet.get_all_values()
            objects   = []
            if len(all_vals) > 1:
                headers = all_vals[0]
                def _col(h):
                    return headers.index(h) if h in headers else None
                def _get(row, h):
                    c = _col(h)
                    return row[c].strip() if c is not None and c < len(row) else ""
                for row in all_vals[1:]:
                    if not row or not row[0]:
                        continue
                    if _get(row, "Biz ID") != biz_id:
                        continue
                    objects.append({
                        "obj_id":        _get(row, "OBJ ID"),
                        "client_id":     _get(row, "Client ID"),
                        "biz_id":        _get(row, "Biz ID"),
                        "city":          _get(row, "City"),
                        "address":       _get(row, "Address"),
                        "object_type":   _get(row, "Object Type"),
                        "object_status": _get(row, "Object Status"),
                        "roadmap_id":    _get(row, "Roadmap ID"),
                        "google_drive":  _get(row, "Google Drive"),
                    })
        else:
            # Все объекты
            sheet    = get_business_sheet("object_registry")
            all_vals = sheet.get_all_values()
            objects  = []
            if len(all_vals) > 1:
                headers = all_vals[0]
                def _col(h):
                    return headers.index(h) if h in headers else None
                def _get(row, h):
                    c = _col(h)
                    return row[c].strip() if c is not None and c < len(row) else ""
                for row in all_vals[1:]:
                    if not row or not row[0]:
                        continue
                    objects.append({
                        "obj_id":        _get(row, "OBJ ID"),
                        "client_id":     _get(row, "Client ID"),
                        "biz_id":        _get(row, "Biz ID"),
                        "city":          _get(row, "City"),
                        "address":       _get(row, "Address"),
                        "object_type":   _get(row, "Object Type"),
                        "object_status": _get(row, "Object Status"),
                        "roadmap_id":    _get(row, "Roadmap ID"),
                        "google_drive":  _get(row, "Google Drive"),
                    })

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
            drive = f" · [📁]({obj['google_drive']})" if obj.get("google_drive") else ""
            lines.append(
                f"• `{obj['obj_id']}` | {obj.get('city','')} | {obj.get('address','')[:30]}"
                f"\n  [{obj.get('object_type','—')}] {obj.get('object_status','—')}"
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

    try:
        from business_core.business_builder import (
            find_object_by_id,
            create_roadmap_for_object,
            update_object_roadmap_id,
        )
        from business_core.roadmap_manager import (
            create_roadmap_stages_from_template,
            ROADMAP_TEMPLATES,
        )
        from business_core.roadmap_template_manager import (
            create_stages_from_template_record,
            find_roadmap_templates_by_service,
        )
        from business_core.service_manager import find_service_by_id

        obj = find_object_by_id(obj_id)
        if not obj:
            await _reply(update, f"❌ Объект `{obj_id}` не найден. Проверь /objects")
            return

        biz_id    = obj.get("biz_id", "")
        client_id = obj.get("client_id", "")

        # ── Определить шаблон ─────────────────────────────────
        # Приоритет 1: явно переданный template_id (с валидацией)
        # Приоритет 2: Default Roadmap Template ID услуги
        # Приоритет 3: первый шаблон, связанный с сервисом
        # Fallback:    старая логика через case_type
        from business_core.roadmap_template_manager import find_roadmap_template_by_id

        explicit_template_id = args.get("template_id", "").strip()
        template_id_to_use   = ""
        template_source      = ""

        if explicit_template_id:
            # ── Валидация явно переданного template_id ─────────
            tmpl_rec = find_roadmap_template_by_id(explicit_template_id)
            if not tmpl_rec:
                await _reply(update,
                    f"❌ Шаблон `{explicit_template_id}` не найден в ROADMAP\\_TEMPLATE\\_REGISTRY.\n\n"
                    f"Проверь список шаблонов для услуги:\n"
                    f"`/rtemplates service_id={service_id}`"
                )
                return

            tmpl_svc = tmpl_rec.get("service_id", "").strip()
            if service_id and tmpl_svc and tmpl_svc != service_id:
                await _reply(update,
                    f"❌ Шаблон `{explicit_template_id}` принадлежит услуге `{tmpl_svc}`, "
                    f"а не `{service_id}`.\n\n"
                    f"Укажи шаблон из правильной услуги:\n"
                    f"`/rtemplates service_id={service_id}`"
                )
                return

            template_id_to_use = explicit_template_id
            template_source    = "явно указан"

        else:
            # ── Автовыбор шаблона ──────────────────────────────
            svc = find_service_by_id(service_id) if service_id else None
            if svc:
                tmpl_from_svc = svc.get("default_roadmap_template_id", "").strip()
                if tmpl_from_svc:
                    template_id_to_use = tmpl_from_svc
                    template_source    = f"default для {service_id}"

            if not template_id_to_use and service_id:
                linked = find_roadmap_templates_by_service(service_id)
                if linked:
                    template_id_to_use = linked[0].get("template_id", "")
                    template_source    = f"автовыбор для {service_id}"

                    # ── Подсказка: несколько шаблонов доступно ─
                    if len(linked) > 1:
                        hint_lines = [
                            f"ℹ️ Для услуги `{service_id}` найдено несколько шаблонов "
                            f"(используется первый):\n"
                        ]
                        for t in linked:
                            tid   = t.get("template_id", "")
                            tname = t.get("template_name", tid)
                            marker = " ← *выбран*" if tid == template_id_to_use else ""
                            hint_lines.append(f"• `{tid}` — {tname}{marker}")
                        hint_lines.append(
                            f"\nЧтобы выбрать конкретный шаблон:\n"
                            f"`/startroadmap obj_id={obj_id} service_id={service_id} "
                            f"template_id=RMT-...`"
                        )
                        await _reply(update, "\n".join(hint_lines))

        # ── Создать roadmap ────────────────────────────────────
        rm_result = create_roadmap_for_object(
            obj_id=obj_id,
            biz_id=biz_id,
            client_id=client_id,
            service_id=service_id,
            case_type=case_type,
            title=title,
            notes=notes,
            template_id=template_id_to_use,
        )
        if not rm_result["ok"]:
            await _reply(update, f"❌ Не удалось создать roadmap: {rm_result['error']}")
            return

        roadmap_id = rm_result["roadmap_id"]

        # ── Создать этапы ──────────────────────────────────────
        stages_result   = None
        used_template   = False

        if template_id_to_use:
            stages_result = create_stages_from_template_record(roadmap_id, template_id_to_use)
            used_template = True

        # Fallback: встроенные шаблоны через case_type
        if not stages_result or not stages_result.get("ok") or stages_result.get("stages_count", 0) == 0:
            stages_result_fb = create_roadmap_stages_from_template(roadmap_id, case_type)
            if stages_result_fb.get("stages_count", 0) > 0:
                stages_result = stages_result_fb
                used_template = False

        if not stages_result:
            stages_result = {"ok": True, "stages_count": 0, "warning": "Шаблон не найден", "stage_ids": []}

        update_object_roadmap_id(obj_id, roadmap_id)

        # ── Ответ ──────────────────────────────────────────────
        lines = [
            "✅ *Roadmap создан*\n",
            f"Roadmap ID: `{roadmap_id}`",
            f"Object ID:  `{obj_id}`",
            f"Service ID: `{service_id or '—'}`",
        ]
        if template_id_to_use and used_template:
            lines.append(f"Шаблон: `{template_id_to_use}`"
                         + (f" _{template_source}_" if template_source else ""))
        elif case_type and case_type != "general":
            lines.append(f"Case Type: `{case_type}`")

        if stages_result.get("warning") and not stages_result.get("stages_count"):
            lines.append(f"\n⚠️ {stages_result['warning']}")
        else:
            count = stages_result.get("stages_count", 0)
            lines.append(f"Этапов создано: {count}")
            # Показать первые 5 названий
            if not used_template:
                stage_names = ROADMAP_TEMPLATES.get(case_type, [])
                if stage_names:
                    lines.append("\n*Следующие шаги:*")
                    for i, name in enumerate(stage_names[:5], start=1):
                        lines.append(f"{i}. {name}")
                    if len(stage_names) > 5:
                        lines.append(f"   ... (+{len(stage_names) - 5} этапов)")

        lines.append(f"\nПросмотр этапов: `/stages roadmap_id={roadmap_id}`")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"startroadmap_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


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
        from business_core.roadmap_manager import get_stages_for_roadmap
        from business_core.business_builder import find_roadmap_by_id

        rm = find_roadmap_by_id(roadmap_id)
        stages = get_stages_for_roadmap(roadmap_id)

        if not stages and not rm:
            await _reply(update, f"❌ Roadmap `{roadmap_id}` не найден.")
            return

        header = f"📋 *Этапы {roadmap_id}*"
        if rm:
            header += f" — {rm.get('title', '')}"
            if rm.get("case_type"):
                header += f" (`{rm['case_type']}`)"

        lines = [header, ""]

        if not stages:
            lines.append("Этапы ещё не созданы.")
        else:
            status_icons = {
                "pending":     "⬜",
                "in_progress": "🔄",
                "completed":   "✅",
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

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"stages_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /updatestage — обновить статус этапа (Phase 9B)
# ─────────────────────────────────────────────────────────────

async def updatestage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обновить статус этапа дорожной карты.

    Форматы:
      /updatestage stage_id=STAGE-xxx status=done
      /updatestage stage_id=STAGE-xxx status=blocked notes="Ожидаем документы клиента"

    status принимает только: pending, in_progress, blocked, done, skipped.
    notes с пробелами нужно указывать в кавычках (как и в остальных командах).

    Меняет только колонки Status (и Notes, если notes передан) в найденной
    строке ROADMAP_STAGES. После успешного изменения статуса автоматически
    пересчитывает Progress % roadmap (Phase 9E.1) и, если roadmap реально
    завершён (все этапы done/skipped, Progress % == 100, Status == active),
    переводит его в completed (Phase 9E.2) — вызывается только если статус
    этапа валиден и этап найден. Не пишет историю, не делает массовых
    обновлений, не открывает completed обратно в active.
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

    if not stage_id or not status:
        from business_core.roadmap_manager import STAGE_STATUS_CANONICAL
        await _reply(update,
            "❌ Укажи stage\\_id и status.\n\n"
            f"Допустимые статусы: `{', '.join(STAGE_STATUS_CANONICAL)}`\n\n"
            "Примеры:\n"
            "`/updatestage stage_id=STAGE-001-01 status=done`\n"
            "`/updatestage stage_id=STAGE-001-01 status=blocked "
            "notes=\"Ожидаем документы клиента\"`"
        )
        return

    try:
        from business_core.roadmap_manager import (
            update_stage_status_in_sheet,
            recalculate_roadmap_progress,
            maybe_complete_roadmap,
        )

        result = update_stage_status_in_sheet(stage_id, status, notes=notes)

        if not result["ok"]:
            await _reply(update, f"❌ {result['error']}")
            return

        if result["changed"]:
            lines = [
                f"✅ Этап `{stage_id}`: {result['old_status']} → {result['new_status']}",
            ]
        else:
            lines = [
                f"ℹ️ Этап `{stage_id}` уже имел статус `{result['new_status']}` "
                "(изменений нет, повтор безопасен).",
            ]

        # Phase 9E.1: пересчёт Progress % только после валидного и
        # существующего этапа (result["ok"] уже гарантирует это выше).
        roadmap_id = result.get("roadmap_id", "")
        if roadmap_id:
            progress = recalculate_roadmap_progress(roadmap_id)
            if progress["ok"]:
                if progress["changed"]:
                    lines.append(
                        f"Progress Roadmap `{roadmap_id}`: "
                        f"{progress['old_progress']}% → {progress['new_progress']}%"
                    )
                else:
                    lines.append(
                        f"Progress Roadmap `{roadmap_id}` уже {progress['new_progress']}%"
                    )

                # Phase 9E.2: автозавершение roadmap — только если Progress %
                # реально пересчитан. progress_pct передаётся напрямую, чтобы
                # не пересчитывать его повторно; список этапов
                # maybe_complete_roadmap при необходимости читает сам.
                completion = maybe_complete_roadmap(
                    roadmap_id, progress_pct=progress["new_progress"],
                )
                if completion["ok"]:
                    if completion["changed"]:
                        lines.append(
                            f"✅ Roadmap `{roadmap_id}` завершён: "
                            f"{completion['old_status']} → {completion['new_status']}"
                        )
                    elif completion["old_status"] == "completed":
                        lines.append(
                            f"ℹ️ Roadmap `{roadmap_id}` уже имеет статус `completed`"
                        )

        if notes is not None:
            lines.append(f"Notes обновлены: {notes}")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"updatestage_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


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


def _stage_row_display(row: dict) -> str:
    lines = [
        f"📌 Этап {row.get('Stage ID', '')}",
        "",
        f"Roadmap: {row.get('Roadmap ID', '')}",
        f"Order: {row.get('Order', '')}",
        f"Название: {row.get('Name', '')}",
        f"Статус: {row.get('Status', '')}",
        f"Ответственный: {row.get('Responsible', '') or '—'}",
        f"Start Date: {row.get('Start Date', '') or '—'}",
        f"Due Date: {row.get('Due Date', '') or '—'}",
        f"Completed At: {row.get('Completed At', '') or '—'}",
        # Пустой Priority отображается как 'normal' по умолчанию — это
        # только отображение, ничего не пишется в Sheets, пока
        # пользователь явно не вызовет /priority.
        f"Приоритет: {row.get('Priority', '') or 'normal'}",
        f"Blocking Reason: {row.get('Blocking Reason', '') or '—'}",
        f"Required Docs: {row.get('Docs Required', '') or '—'}",
        f"Checklist IDs: {row.get('Checklist IDs', '') or '—'}",
        f"Notes: {row.get('Notes', '') or '—'}",
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
        from business_core.sheets import find_row_by_id
        found = find_row_by_id("roadmap_stages", stage_id)
        if not found:
            await _reply(update, f"❌ Этап {stage_id} не найден.")
            return
        _, row = found
        await _reply(update, _stage_row_display(row))
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
        from business_core.sheets import find_row_by_id, get_business_sheet

        stage_id = snap["stage_id"]
        # Перечитываем строку прямо перед записью — защита от staleness
        # между показом карточки и подтверждением. find_row_by_id
        # гарантирует ровно одно совпадение по Stage ID (первая строка).
        found = find_row_by_id("roadmap_stages", stage_id)
        if not found:
            await update.message.reply_text(
                f"❌ Этап {stage_id} больше не найден — изменение не выполнено.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            row_number, _live_row = found
            sheet = get_business_sheet("roadmap_stages")
            headers = sheet.row_values(1)

            def _col(name):
                return headers.index(name) + 1 if name in headers else None

            # Защита от случайного расширения области записи: только
            # разрешённые Phase 14A колонки могут быть записаны отсюда.
            allowed_columns = {
                "Responsible", "Due Date", "Priority",
                "Blocking Reason", "Status",
            }
            for column_name, value in snap["writes"].items():
                if column_name not in allowed_columns:
                    continue
                col = _col(column_name)
                if col:
                    sheet.update_cell(row_number, col, value)

            await update.message.reply_text(
                f"✅ Этап {stage_id} обновлён\n\n"
                f"Поле: {snap['field_label']}\n"
                f"Было: {snap['old_value_display'] or '—'}\n"
                f"Стало: {snap['new_value_display'] or '—'}",
                reply_markup=ReplyKeyboardRemove(),
            )

    except Exception as e:
        log.error(f"stage_edit_confirm({snapshot_key}) error: {e}")
        await update.message.reply_text(f"❌ Ошибка сохранения: {e}", reply_markup=ReplyKeyboardRemove())

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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END
    _, row = found

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Ответственный",
        writes={"Responsible": responsible},
        old_value_display=row.get("Responsible", ""),
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END
    _, row = found

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Due Date",
        writes={"Due Date": date_val},
        old_value_display=row.get("Due Date", ""),
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END
    _, row = found

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Приоритет",
        writes={"Priority": level},
        old_value_display=row.get("Priority", "") or "normal",
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END
    _, row = found

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Блокировка (Status → blocked)",
        writes={"Blocking Reason": reason, "Status": "blocked"},
        old_value_display=row.get("Blocking Reason", ""),
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

    from business_core.sheets import find_row_by_id
    found = find_row_by_id("roadmap_stages", stage_id)
    if not found:
        await update.message.reply_text(f"❌ Этап {stage_id} не найден.")
        return ConversationHandler.END
    _, row = found

    writes = {"Blocking Reason": ""}
    # Возвращаем в pending только если этап действительно был blocked —
    # не трогаем Status, если он уже done/skipped/in_progress по другой причине.
    if row.get("Status", "") == "blocked":
        writes["Status"] = "pending"

    return await _stage_edit_start(
        update, context, stage_id=stage_id, field_label="Разблокировка",
        writes=writes,
        old_value_display=row.get("Blocking Reason", "") or "—",
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
        await update.message.reply_text(f"❌ Ошибка: {e}")
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
        from business_core.sheets import (
            append_business_row, find_row_by_id,
            get_business_sheet, row_from_header_map,
        )
        from business_core.document_registry_manager import compute_next_document_and_family_ids

        # Phase 15A safety refinement: ONE read of the sheet, both IDs
        # (DREG + DFAM) computed from that single snapshot, immediately
        # before the one append — no separate reads per prefix that
        # could observe different sheet states between them.
        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
        headers = all_values[0] if all_values else []
        document_id, family_id = compute_next_document_and_family_ids(all_values)

        now = _now_utc_str()
        row = row_from_header_map(headers, {
            "Document ID": document_id,
            "Document Family ID": family_id,
            "Version": "1",
            "Business ID": snap["business_id"],
            "Client ID": snap["client_id"],
            "Object ID": snap["object_id"],
            "Roadmap ID": snap["roadmap_id"],
            "Stage ID": snap["stage_id"],
            "Document Template ID": snap["document_template_id"],
            "Document Name": snap["document_name"],
            "Status": "uploaded",
            "Drive File ID": snap["drive_file_id"],
            "Drive File URL": snap.get("web_view_link", ""),
            "File Name": snap["file_name"],
            "Mime Type": snap["mime_type"],
            "Uploaded At": now,
            "Uploaded By": _telegram_username(update),
            "Notes": snap["notes"],
            "Created At": now,
            "Updated At": now,
        })
        # Единственная запись — либо строка полностью появляется, либо
        # (при исключении) не появляется вовсе; нет промежуточного
        # состояния с частично записанной строкой.
        append_business_row("document_registry", row)

        found = find_row_by_id("document_registry", document_id)
        if not found:
            await update.message.reply_text(
                "⚠️ Строка записана, но не удалось перечитать её для подтверждения.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            _, saved_row = found
            await update.message.reply_text(
                f"✅ Документ зарегистрирован\n\n"
                f"Document ID: {saved_row.get('Document ID')}\n"
                f"Document Family ID: {saved_row.get('Document Family ID')}\n"
                f"Название: {saved_row.get('Document Name')}\n"
                f"Статус: {saved_row.get('Status')}\n"
                f"Файл: {saved_row.get('File Name')}",
                reply_markup=ReplyKeyboardRemove(),
            )

    except Exception as e:
        log.error(f"registerdoc_confirm error: {e}")
        await update.message.reply_text(f"❌ Ошибка сохранения: {e}", reply_markup=ReplyKeyboardRemove())

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
        from business_core.sheets import find_row_by_id
        found = find_row_by_id("document_registry", document_id)
        if not found:
            await _reply(update, f"❌ Документ {document_id} не найден.")
            return
        _, row = found
        lines = [
            f"📄 Документ {row.get('Document ID', '')}",
            "",
            f"Family: {row.get('Document Family ID', '')} (v{row.get('Version', '')})",
            f"Название: {row.get('Document Name', '')}",
            f"Статус: {row.get('Status', '')}",
            f"Business: {row.get('Business ID', '') or '—'}",
            f"Client: {row.get('Client ID', '') or '—'}",
            f"Object: {row.get('Object ID', '') or '—'}",
            f"Roadmap: {row.get('Roadmap ID', '') or '—'}",
            f"Stage: {row.get('Stage ID', '') or '—'}",
            f"Document Template: {row.get('Document Template ID', '') or '—'}",
            f"Файл: {row.get('File Name', '')} ({row.get('Mime Type', '')})",
            f"Drive: {row.get('Drive File URL', '')}",
            f"Загружен: {row.get('Uploaded At', '')} ({row.get('Uploaded By', '')})",
            f"Notes: {row.get('Notes', '') or '—'}",
        ]
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"doc_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


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
        await _reply(update, f"❌ Ошибка: {e}")


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

    context.user_data["ud"] = {
        "tg_file_id": doc.file_id,
        "tg_file_unique_id": doc.file_unique_id,
        "tg_file_name": doc.file_name or "document",
        "tg_mime_type": doc.mime_type or "application/octet-stream",
        "tg_file_size": doc.file_size,
        "uploaded_by": _telegram_username(update),
    }

    await update.message.reply_text(
        "✅ Файл получен: " + (doc.file_name or "(без имени)") + "\n\n"
        "Теперь одной строкой укажи данные документа:\n\n"
        'business=BIZ-001 name="Технический паспорт"\n\n'
        "Опционально: client=, object=, roadmap=, stage=, template=, notes=\n\n"
        "/cancel — отменить."
    )
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
        await update.message.reply_text(f"❌ Ошибка: {e}")
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
                f"❌ Не удалось скачать файл из Telegram: {e}",
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

        try:
            upload_result = upload_file(
                service, tmp_path, snap["folder_id"],
                filename=snap["tg_file_name"], mime_type=snap["tg_mime_type"],
            )
        except Exception as e:
            log.error(f"uploaddoc_confirm: Drive upload error: {e}")
            await update.message.reply_text(
                f"❌ Ошибка загрузки в Google Drive: {e}",
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
            if cleanup.get("ok"):
                await update.message.reply_text(
                    "❌ Не удалось получить полные метаданные файла из Google Drive после загрузки — "
                    "регистрация не выполнена.\n"
                    "Загруженный файл в Google Drive перемещён в корзину (компенсация выполнена).",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                parts = [
                    "❌ Не удалось получить полные метаданные файла из Google Drive после загрузки — "
                    "регистрация не выполнена.",
                    f"⚠️ Очистка Drive-файла НЕ удалась: {cleanup.get('error')}",
                    f"Orphan Drive File ID: {drive_file_id}",
                ]
                if meta.get("web_view_link"):
                    parts.append(f"Drive URL: {meta['web_view_link']}")
                parts.append("Требуется ручная очистка.")
                await update.message.reply_text("\n".join(parts), reply_markup=ReplyKeyboardRemove())
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        real_name = meta["name"]
        real_mime = meta["mime_type"]
        web_view_link = meta["web_view_link"]

        from business_core.sheets import (
            append_business_row, find_row_by_id,
            get_business_sheet, row_from_header_map,
        )
        from business_core.document_registry_manager import compute_next_document_and_family_ids

        sheet = get_business_sheet("document_registry")
        all_values = sheet.get_all_values()
        headers = all_values[0] if all_values else []
        document_id, family_id = compute_next_document_and_family_ids(all_values)

        now = _now_utc_str()
        row = row_from_header_map(headers, {
            "Document ID": document_id,
            "Document Family ID": family_id,
            "Version": "1",
            "Business ID": snap["business_id"],
            "Client ID": snap["client_id"],
            "Object ID": snap["object_id"],
            "Roadmap ID": snap["roadmap_id"],
            "Stage ID": snap["stage_id"],
            "Document Template ID": snap["document_template_id"],
            "Document Name": snap["document_name"],
            "Status": "uploaded",
            "Drive File ID": drive_file_id,
            "Drive File URL": web_view_link,
            "File Name": real_name,
            "Mime Type": real_mime,
            "Uploaded At": now,
            "Uploaded By": snap["uploaded_by"],
            "Notes": snap["notes"],
            "Created At": now,
            "Updated At": now,
        })

        try:
            append_business_row("document_registry", row)
        except Exception as e:
            log.error(f"uploaddoc_confirm: DOCUMENT_REGISTRY write failed: {e}")
            cleanup = trash_file(service, drive_file_id)
            if cleanup.get("ok"):
                await update.message.reply_text(
                    f"❌ Не удалось сохранить запись в DOCUMENT_REGISTRY: {e}\n"
                    "Загруженный файл в Google Drive перемещён в корзину (компенсация выполнена) — "
                    "запись не создана.",
                    reply_markup=ReplyKeyboardRemove(),
                )
            else:
                await update.message.reply_text(
                    f"❌ Не удалось сохранить запись в DOCUMENT_REGISTRY: {e}\n"
                    f"⚠️ Очистка Drive-файла НЕ удалась: {cleanup.get('error')}\n"
                    f"Orphan Drive File ID: {drive_file_id}\n"
                    f"Drive URL: {web_view_link or '(нет ссылки)'}\n"
                    "Требуется ручная очистка.",
                    reply_markup=ReplyKeyboardRemove(),
                )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        # Post-write verification: re-read and compare against the
        # immutable snapshot + authoritative Drive metadata. A missing
        # row or any mismatch NEVER triggers a second write/upload — the
        # row may already exist, so we also never trash the Drive file
        # here (only a registry-write EXCEPTION, handled above, does
        # that). We report a distinct manual-verification result and
        # end the operation as terminal (no return to "pending").
        expected = {
            "Document ID": document_id, "Document Family ID": family_id, "Version": "1",
            "Business ID": snap["business_id"], "Client ID": snap["client_id"],
            "Object ID": snap["object_id"], "Roadmap ID": snap["roadmap_id"],
            "Stage ID": snap["stage_id"], "Document Template ID": snap["document_template_id"],
            "Document Name": snap["document_name"], "Status": "uploaded",
            "Drive File ID": drive_file_id, "Drive File URL": web_view_link,
            "File Name": real_name, "Mime Type": real_mime,
        }
        found = find_row_by_id("document_registry", document_id)
        if not found:
            log.error(
                f"uploaddoc_confirm: post-write re-read did not find {document_id} "
                f"(expected={expected})"
            )
            snap["op_state"] = "verification_failed"
            await update.message.reply_text(
                "⚠️ Document registered, but post-write verification failed.\n"
                "Manual verification is required.\n"
                f"Document ID: {document_id}\n"
                f"Drive File ID: {drive_file_id}",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        _, saved_row = found
        mismatches = {k: {"expected": v, "actual": saved_row.get(k)}
                      for k, v in expected.items() if saved_row.get(k) != v}
        if mismatches:
            log.error(
                f"uploaddoc_confirm: post-write verification mismatch for {document_id}: {mismatches}"
            )
            snap["op_state"] = "verification_failed"
            await update.message.reply_text(
                "⚠️ Document registered, but post-write verification failed.\n"
                "Manual verification is required.\n"
                f"Document ID: {document_id}\n"
                f"Drive File ID: {drive_file_id}",
                reply_markup=ReplyKeyboardRemove(),
            )
            context.user_data.pop("ud_confirmed_snapshot", None)
            return ConversationHandler.END

        await update.message.reply_text(
            f"✅ Документ загружен и зарегистрирован\n\n"
            f"Document ID: {saved_row.get('Document ID')}\n"
            f"Document Family ID: {saved_row.get('Document Family ID')}\n"
            f"Version: {saved_row.get('Version')}\n"
            f"Название: {saved_row.get('Document Name')}\n"
            f"Файл: {saved_row.get('File Name')}\n"
            f"Drive URL: {saved_row.get('Drive File URL')}\n"
            f"Business ID: {saved_row.get('Business ID') or '—'}\n"
            f"Client ID: {saved_row.get('Client ID') or '—'}\n"
            f"Object ID: {saved_row.get('Object ID') or '—'}\n"
            f"Roadmap ID: {saved_row.get('Roadmap ID') or '—'}\n"
            f"Stage ID: {saved_row.get('Stage ID') or '—'}\n"
            f"Document Template ID: {saved_row.get('Document Template ID') or '—'}\n"
            f"Статус: {saved_row.get('Status')}",
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
        await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=ReplyKeyboardRemove())
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
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw = " ".join(context.args or [])
    kv = _parse_kv_args(raw)
    document_id = kv.get("document_id") or kv.get("_pos0", "")
    force = kv.get("force", "").strip().lower() == "true"

    if not document_id:
        await _reply(update, "❌ Укажи document_id.\n\nПример: /analyzedoc document_id=DREG-001 [force=true]")
        return

    try:
        from business_core.sheets import find_row_by_id
        from business_core.document_intelligence import get_content_status, decide_action

        doc_found = find_row_by_id("document_registry", document_id)
        if not doc_found:
            await _reply(update, f"❌ Документ {document_id} не найден в DOCUMENT_REGISTRY.")
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
                "Используй force=true для повторного анализа.",
            )
            return
        if action == "skip_processing":
            await _reply(update, f"⏳ Документ {document_id} уже анализируется — подожди результата.")
            return
        if action in ("skip_failed", "skip_unsupported"):
            status_ru = "не поддерживается" if action == "skip_unsupported" else "завершился ошибкой"
            await _reply(
                update,
                f"⚠️ Предыдущий анализ {document_id} {status_ru}.\n"
                f"Ошибка: {existing.get('Analysis Error') or '—'}\n\n"
                "Для повторной попытки укажи force=true.",
            )
            return

        # action == "proceed"
        enqueued = _enqueue_document_analysis(context, document_id, drive_file_id, force=force)
        if enqueued:
            await _reply(update, f"🧠 Анализ документа {document_id} поставлен в очередь.")
        else:
            await _reply(
                update,
                f"⚠️ Не удалось поставить анализ {document_id} в очередь "
                "(job_queue недоступен). Документ остаётся зарегистрированным без изменений.",
            )

    except Exception as e:
        log.error(f"analyzedoc_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


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
        from business_core.service_manager import _load_services, normalize_service_status

        rows, _ = _load_services()

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
            title="Как проверить документы" purpose="..." steps="1. ...; 2. ..." result="..."
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
            'steps="1. Удостоверение; 2. Правоустанавливающий"`'
        )
        return
    try:
        from business_core.knowledge_manager import create_sop_record
        result = create_sop_record(
            title=             title,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            purpose=           args.get("purpose",            ""),
            steps=             args.get("steps",              ""),
            expected_result=   args.get("result",             ""),
            owner_role=        args.get("owner_role",         ""),
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
        await _reply(update, "\n".join(lines))
    except Exception as e:
        log.error(f"newsop_cmd error: {e}")
        await _reply(update, f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────────────────────
# /newchecklist — создать чек-лист (Phase 8C)
# ─────────────────────────────────────────────────────────────

async def newchecklist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /newchecklist biz_id=BIZ-001 template_stage_id=TSTG-001 title="Чек-лист документов"
                  items="Удостоверение; Правоустанавливающий; Техпаспорт"
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
            '`/newchecklist biz_id=BIZ-001 template_stage_id=TSTG-001 '
            'title="Документы клиента" items="Удостоверение; Техпаспорт"`'
        )
        return
    try:
        from business_core.knowledge_manager import create_checklist_record
        result = create_checklist_record(
            title=             title,
            biz_id=            args.get("biz_id",            ""),
            service_id=        args.get("service_id",         ""),
            template_id=       args.get("template_id",        ""),
            template_stage_id= args.get("template_stage_id",  ""),
            items=             args.get("items",              ""),
            required_items=    args.get("required",           ""),
            optional_items=    args.get("optional",           ""),
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
        await _reply(update, f"❌ Ошибка: {e}")


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
        await _reply(update, f"❌ Ошибка: {e}")


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
        await _reply(update, f"❌ Ошибка: {e}")


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
            f"Object:   `{rm.get('obj_id',     '—')}`",
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
    # Phase 8D
    app.add_handler(CommandHandler("milestones",       milestones_cmd))
    # Phase 11B
    app.add_handler(CommandHandler("report",           report_cmd))
    # Phase 12A
    app.add_handler(CommandHandler("version",          version_cmd))

    # Callback handler для кнопок подтверждения бизнес-контекста (Фаза 5B)
    app.add_handler(CallbackQueryHandler(bc_ctx_callback, pattern=r"^bc_ctx:"))

    log.info(
        "Business Core handlers зарегистрированы: "
        "/bc /bcstatus /roadmaps /clients /newroadmap /newclient /newbiz /initbc /bcdrive "
        "/newobject /objects /startroadmap /stages /updatestage /recalcprogress "
        "/newservice /services /service "
        "/milestones /report "
        "+ bc_ctx callback (Фаза 5B)"
    )
