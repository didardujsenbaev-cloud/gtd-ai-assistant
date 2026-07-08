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
    """Показать активные дорожные карты из Google Sheets."""
    if not _is_bc_enabled():
        await _reply(update, _bc_disabled_msg())
        return

    try:
        from business_core.sheets import read_business_sheet

        rows = read_business_sheet("roadmaps")
        if not rows:
            await _reply(update,
                "🗺 *Дорожные карты*\n\n"
                "Пусто. Создай первую: /newroadmap"
            )
            return

        active = [r for r in rows if r.get("Status", "") not in ("completed", "cancelled")]
        done   = [r for r in rows if r.get("Status", "") == "completed"]

        lines = [f"🗺 *Дорожные карты* ({len(active)} активных)\n"]

        for r in active:
            rm_id    = r.get("Roadmap ID", "?")
            client   = r.get("Client Name", "?")
            city     = r.get("City", "")
            biz_id   = r.get("Business ID", "")
            progress = r.get("Progress %", "0")
            status   = r.get("Status", "active")

            try:
                pct = float(progress)
            except (ValueError, TypeError):
                pct = 0.0

            filled = int(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)

            lines.append(
                f"*{rm_id}* — {client}"
                + (f", {city}" if city else "")
                + (f" `[{biz_id}]`" if biz_id else "")
            )
            lines.append(f"  {bar} {pct:.0f}%")

            # Показать текущий этап если есть
            for i in range(1, 11):
                stage_status = r.get(f"Stage {i} Status", "")
                if stage_status in ("in_progress", "blocked", "waiting"):
                    lines.append(f"  ⬅ Этап {i}: {stage_status}")
                    break
            lines.append("")

        if done:
            lines.append(f"✅ Завершено: {len(done)}")

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
            find_existing_client,
            provision_client_drive,
            save_client_drive_to_sheets,
            normalize_biz_ids,
            _get_biz_id_by_name,
        )

        full_name = nc.get("full_name", "")
        biz_name  = nc.get("businesses", "")
        biz_name  = "" if biz_name.startswith("/skip") else biz_name

        # Phase 6A: резолвим biz_id по имени бизнеса
        biz_id_resolved = ""
        if biz_name:
            try:
                resolved = _get_biz_id_by_name(biz_name)
                # _get_biz_id_by_name возвращает имя, если ID не найден
                if resolved and resolved != biz_name:
                    biz_id_resolved = resolved
            except Exception:
                pass

        # ── Проверяем дубль ──────────────────────────────────────
        existing = find_existing_client(full_name, biz_name)
        is_new   = existing is None

        if is_new:
            # Создаём новую запись
            prs_id     = generate_next_id("people_registry", "PRS")
            parts      = full_name.split()
            short_name = parts[0] if parts else full_name
            now        = datetime.now().strftime("%Y-%m-%d")

            # Phase 6A: Biz IDs как "<BIZ-001>" или "" если не нашли
            biz_ids_val      = biz_id_resolved if biz_id_resolved else ""
            primary_biz_val  = biz_id_resolved if biz_id_resolved else ""

            row_values = [
                prs_id, full_name, short_name,
                nc.get("phone", ""), "", "", "", "",
                "", "", "",
                nc.get("person_type", "клиент"), "",
                biz_name,       # старое поле "Бизнесы" — для совместимости
                "средний", "",
                "", "", "", "", "",
                "", "", now, now, "", "",
                "", "", "", "", "active", "тёплый", "",
                # Google Drive, Drive Folder ID (добавлены в Phase 5 — пустые сейчас)
                "", "",
                # Phase 6A новые поля
                biz_ids_val,    # Biz IDs
                "",             # Company ID
                "",             # Citizenship
                "",             # Passport / ID
                primary_biz_val,  # Primary Biz ID
            ]
            append_business_row("people_registry", row_values)

            # Обновляем кеш inbox_bridge
            try:
                from business_core.inbox_bridge import invalidate_cache
                invalidate_cache()
            except Exception:
                pass
        else:
            prs_id = existing["prs_id"]

        # ── Drive ────────────────────────────────────────────────
        drive_msg = ""
        if biz_name:
            # Если уже есть ссылка — показываем её без повторного запроса к Drive
            if not is_new and existing.get("drive_url"):
                drive_msg = f"\n📁 Drive: {existing['drive_url']}"
            else:
                try:
                    drive_result = provision_client_drive(
                        prs_id=prs_id,
                        full_name=full_name,
                        biz_name=biz_name,
                    )
                    if drive_result["ok"]:
                        save_client_drive_to_sheets(
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
        header = "✅ *Клиент добавлен!*" if is_new else "ℹ️ *Клиент уже существует, использую существующую запись*"

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
    app.add_handler(CommandHandler("bc",       bc_dashboard))
    app.add_handler(CommandHandler("bcstatus", bc_status))
    app.add_handler(CommandHandler("roadmaps", show_roadmaps))
    app.add_handler(CommandHandler("clients",  show_clients))
    app.add_handler(CommandHandler("bcdrive",  bc_drive))
    app.add_handler(CommandHandler("initbc",   init_bc))

    # Callback handler для кнопок подтверждения бизнес-контекста (Фаза 5B)
    app.add_handler(CallbackQueryHandler(bc_ctx_callback, pattern=r"^bc_ctx:"))

    log.info(
        "Business Core handlers зарегистрированы: "
        "/bc /bcstatus /roadmaps /clients /newroadmap /newclient /newbiz /initbc /bcdrive "
        "+ bc_ctx callback (Фаза 5B)"
    )
