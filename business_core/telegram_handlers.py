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

import logging
import os
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
    """Старт диалога создания дорожной карты."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return ConversationHandler.END

    try:
        from business_core.sheets import read_business_sheet
        rows = read_business_sheet("biz_registry")
        active_biz = [r for r in rows if r.get("Статус", "") in ("active", "test")]
    except Exception:
        active_biz = []

    context.user_data["nr"] = {}

    if active_biz:
        biz_names = [r.get("Название", "?") for r in active_biz[:8]]
        keyboard = [[name] for name in biz_names] + [["❌ Отмена"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "🗺 *Новая дорожная карта*\n\n"
            "Выбери бизнес или напиши название:",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(
            "🗺 *Новая дорожная карта*\n\n"
            "Введи название или ID бизнеса (например: Узаконение):",
            parse_mode="Markdown",
        )
    return NR_BUSINESS


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

    context.user_data["nc"] = {}
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

    nc["businesses"] = "" if text.startswith("/skip") else text

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
    return NC_CONFIRM


async def newclient_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if "Отмена" in text:
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop("nc", None)
        return ConversationHandler.END

    nc = context.user_data.get("nc", {})

    try:
        from business_core.sheets import append_business_row, generate_next_id
        from business_core.business_builder import (
            find_existing_person,
            add_biz_id_to_person,
            update_person_drive_info,
            provision_client_drive,
            save_client_drive_to_sheets,
            normalize_biz_ids,
            _get_biz_id_by_name,
        )

        full_name = nc.get("full_name", "")
        phone     = nc.get("phone", "")
        biz_name  = nc.get("businesses", "")
        biz_name  = "" if biz_name.startswith("/skip") else biz_name

        # Phase 6A/6B: резолвим biz_id по имени бизнеса
        biz_id_resolved = ""
        if biz_name:
            try:
                resolved = _get_biz_id_by_name(biz_name)
                if resolved and resolved != biz_name:
                    biz_id_resolved = resolved
            except Exception:
                pass

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

            row_values = [
                prs_id, full_name, short_name,
                phone, "", "", "", "",
                "", "", "",
                nc.get("person_type", "клиент"), "",
                biz_name,           # "Бизнесы" — для совместимости
                "средний", "",
                "", "", "", "", "",
                "", "", now, now, "", "",
                "", "", "", "", "active", "тёплый", "",
                "", "",             # Google Drive, Drive Folder ID (Phase 5)
                biz_ids_val,        # Biz IDs
                "",                 # Company ID
                "",                 # Citizenship
                "",                 # Passport / ID
                primary_biz_val,    # Primary Biz ID
            ]
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
        if client_status == STATUS_NEW:
            header = "✅ *Клиент добавлен!*"
        elif client_status == STATUS_SAME_BIZ:
            header = "ℹ️ *Клиент уже существует, использую существующую запись*"
        else:
            header = "ℹ️ *Контакт уже был в другом бизнесе, добавил связь с текущим бизнесом*"

        await update.message.reply_text(
            f"{header}\n\n"
            f"🆔 ID: `{prs_id}`\n"
            f"👤 {full_name}"
            f"{drive_msg}\n\n"
            f"/clients — посмотреть всех клиентов",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )

    except Exception as e:
        log.error(f"newclient_confirm error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка сохранения: {e}",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.pop("nc", None)
    return ConversationHandler.END


async def newclient_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nc", None)
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
    пересчитывает Progress % roadmap (Phase 9E.1) — вызывается только если
    статус этапа валиден и этап найден. Не меняет статус Roadmap, не
    реализует автозавершение Roadmap, не пишет историю.
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

        if notes is not None:
            lines.append(f"Notes обновлены: {notes}")

        await _reply(update, "\n".join(lines))

    except Exception as e:
        log.error(f"updatestage_cmd error: {e}")
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

    Форматы:
      /newservice biz_id=BIZ-001 name="Узаконение реконструкции" category="узаконение" ...
      /newservice BIZ-001 "Узаконение реконструкции частного дома"
    """
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    raw  = " ".join(context.args or [])
    args = _parse_kv_args(raw)

    biz_id       = args.get("biz_id")       or args.get("_pos0", "")
    service_name = (args.get("name") or args.get("service_name")
                    or args.get("_pos1", ""))

    if not biz_id or not service_name:
        await _reply(update,
            "❌ Укажи biz\\_id и name.\n\n"
            "Пример:\n"
            "`/newservice biz_id=BIZ-001 name=\"Узаконение реконструкции\" "
            "city=Алматы price_from=1500000 duration=\"3-4 месяца\"`"
        )
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

    # Регистрируем ConversationHandlers первыми
    app.add_handler(newroadmap_handler)
    app.add_handler(newclient_handler)
    app.add_handler(newbiz_handler)

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

    # Callback handler для кнопок подтверждения бизнес-контекста (Фаза 5B)
    app.add_handler(CallbackQueryHandler(bc_ctx_callback, pattern=r"^bc_ctx:"))

    log.info(
        "Business Core handlers зарегистрированы: "
        "/bc /bcstatus /roadmaps /clients /newroadmap /newclient /newbiz /initbc /bcdrive "
        "/newobject /objects /startroadmap /stages /updatestage /recalcprogress "
        "/newservice /services /service "
        "/milestones "
        "+ bc_ctx callback (Фаза 5B)"
    )
