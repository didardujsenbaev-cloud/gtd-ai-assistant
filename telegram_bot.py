"""
GTD Telegram Bot
Запуск: python3 telegram_bot.py
"""

import os
import io
import re
import base64
import logging
import tempfile
import subprocess

# Добавить Homebrew в PATH для ffmpeg
os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")
from datetime import date, time, datetime, timedelta
from dotenv import load_dotenv
import anthropic
import whisper
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# Weekly Review conversation states (7 шагов: inbox, прошедший календарь, проекты, задачи, waiting, someday, горизонты+done)
WR_INBOX, WR_PAST_CAL, WR_PROJECTS, WR_NEXT_ACTIONS, WR_WAITING, WR_SOMEDAY, WR_HORIZONS, WR_DONE = range(8)

# Natural Planning states
NP_NAME, NP_WHY, NP_OUTCOME, NP_BRAINSTORM, NP_ORGANIZE, NP_ACTION = range(6)
_NP_SKIP = "⏭ Пропустить"
_NP_CANCEL = "❌ Отмена"
_NP_ACCEPT = "✅ Принять"

# Quarterly H3 Review states
QH3_GOALS, QH3_PROJECTS, QH3_SOMEDAY, QH3_PRIORITIES, QH3_DONE = range(5)
_QH3_NEXT = "➡️ Далее"
_QH3_STOP = "⛔ Закончить обзор"

# Mind Sweep states
MS_WORK, MS_PERSONAL, MS_DONE = range(3)
_MS_NEXT = "➡️ Далее"
_MS_STOP = "✅ Готово"
import pytz
from sheets import (get_sheet, read_next_actions, read_projects, read_inbox,
                    upload_pdf_to_drive, read_biz_objects, read_biz_steps,
                    read_biz_object_names)
from inbox_processor import process_item
from project_planner import save_project, format_planning_notes
from calendar_sync import (
    is_configured as cal_configured,
    setup_instructions as cal_setup,
    sync_gtd_deadlines,
    format_calendar_summary,
    upsert_deadline_event,
    list_past_events,
    list_calendars_status,
    SERVICE_ACCOUNT_EMAIL as CAL_SERVICE_ACCOUNT,
)

load_dotenv()

logging.basicConfig(level=logging.WARNING)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TIMEZONE = pytz.timezone("Asia/Almaty")

# Загружаем Whisper один раз при старте (base = быстрая модель)
print("   Загружаю Whisper модель...", flush=True)
whisper_model = whisper.load_model("base")
print("   Whisper готов!", flush=True)
ai_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

EXTRACT_PROMPT = """Ты GTD-ассистент. Посмотри на это изображение/документ и извлеки из него задачи, действия или важную информацию для системы GTD.

Если есть чёткие задачи — перечисли их.
Если это документ — выдели ключевые действия которые нужно предпринять.
Если это визитка — сформулируй задачу "связаться с [имя]".
Если задач нет — скажи об этом прямо.

Отвечай на русском."""


# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    await update.message.reply_text(f"Твой Chat ID: `{chat_id}`", parse_mode="Markdown")


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызвать утренний дайджест вручную."""
    context.job_queue
    await morning_digest(context)
    if not TELEGRAM_CHAT_ID:
        await update.message.reply_text("❌ TELEGRAM_CHAT_ID не задан в .env")


async def show_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/inbox — показать текущий Inbox."""
    try:
        inbox = read_inbox()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    new_items = [r for r in inbox if r.get("Статус") == "Новый" and r.get("Содержимое")]
    processed = [r for r in inbox if r.get("Статус") != "Новый" and r.get("Содержимое")]

    if not new_items and not processed:
        await update.message.reply_text(
            "📥 *Inbox пуст*\n\nДобавляй идеи и задачи — просто напиши текст.",
            parse_mode="Markdown"
        )
        return

    text = f"📥 *INBOX*\n\n"
    if new_items:
        text += f"⚡ *Необработанных: {len(new_items)}*\n"
        for i, r in enumerate(new_items[:10], 1):
            content = str(r.get("Содержимое", "—"))[:60]
            source = r.get("Источник", "")
            src_tag = f" _{source}_" if source else ""
            text += f"{i}. {content}{src_tag}\n"
        if len(new_items) > 10:
            text += f"_...и ещё {len(new_items) - 10}_\n"
        text += "\n_Обработать: напиши *обработать*_\n\n"
    else:
        text += "✅ Все элементы обработаны\n\n"

    text += f"_Всего в Inbox: {len(inbox)} · Обработано: {len(processed)}_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def _build_weekly_review() -> tuple[str, dict]:
    """Собрать данные для Weekly Review. Возвращает (текст, данные для сохранения)."""
    actions = read_next_actions()
    inbox = read_inbox()
    projects = read_projects()

    today_date = date.today()
    new_inbox = len([r for r in inbox if r.get("Статус") == "Новый"])
    next_actions = [a for a in actions if a.get("Статус") == "Next"]
    waiting = [a for a in actions if a.get("Статус") == "Waiting"]
    active_projects = [p for p in projects if p.get("Статус") == "Активен"]
    projects_no_na = [p for p in active_projects if not p.get("Следующее действие")]

    # Просроченные задачи
    overdue = []
    for a in next_actions:
        dl = a.get("Срок", "")
        if dl:
            try:
                if date.fromisoformat(dl) < today_date:
                    overdue.append(a)
            except ValueError:
                pass

    text = f"📊 *ЕЖЕНЕДЕЛЬНЫЙ ОБЗОР*\n_{today_date.strftime('%d.%m.%Y')}_\n\n"

    # Шаг 1 — Inbox
    inbox_icon = "✅" if new_inbox == 0 else "⚠️"
    text += f"{inbox_icon} *1. INBOX*\n"
    text += f"Необработанных: {new_inbox}\n"
    if new_inbox > 0:
        text += "→ Напиши *обработать* чтобы разобрать\n"
    text += "\n"

    # Шаг 2 — Проекты
    text += f"🗂 *2. ПРОЕКТЫ* ({len(active_projects)} активных)\n"
    if projects_no_na:
        text += f"⚠️ Без следующего действия: {len(projects_no_na)}\n"
        for p in projects_no_na[:3]:
            text += f"  • {p.get('Название проекта', '—')}\n"
    else:
        text += "✅ У всех проектов есть следующее действие\n"
    text += "\n"

    # Шаг 3 — Next Actions
    text += f"⚡ *3. NEXT ACTIONS* ({len(next_actions)} задач)\n"
    high = len([a for a in next_actions if a.get("Приоритет") == "Высокий"])
    text += f"Высокий приоритет: {high}\n"
    if overdue:
        text += f"🚨 Просрочено: {len(overdue)}\n"
    text += "\n"

    # Шаг 4 — Waiting For
    text += f"⏳ *4. WAITING FOR* ({len(waiting)} ожиданий)\n"
    if waiting:
        text += "Проверь — нужен ли follow-up?\n"
    text += "\n"

    # Шаг 5 — AI анализ
    text += "🤖 *5. AI АНАЛИЗ*\n"

    summary = f"Проекты: {len(active_projects)}, Next Actions: {len(next_actions)}, Waiting: {len(waiting)}, Inbox: {new_inbox}, Просрочено: {len(overdue)}"
    projects_list = "\n".join([f"- {p.get('Название проекта')} [{p.get('Приоритет')}]" for p in active_projects[:5]])

    msg = ai_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content":
            f"GTD Weekly Review. {summary}. Проекты: {projects_list}. "
            f"Дай ТОП-3 приоритета на неделю. Кратко, по-русски, 3 пункта."}]
    )
    ai_text = msg.content[0].text
    text += ai_text + "\n"

    save_data = {
        "date": today_date.isoformat(),
        "inbox_clear": new_inbox == 0,
        "projects_with_na": sum(1 for p in active_projects if p.get("Следующее действие")),
        "active_projects": len(active_projects),
        "waiting": len(waiting),
        "next_actions": len(next_actions),
        "overdue": len(overdue),
        "ai_text": ai_text,
    }
    return text, save_data


def _save_weekly_review(save_data: dict):
    """Сохранить Weekly Review в Google Sheets."""
    try:
        review_sheet = get_sheet("review")
        col_a = review_sheet.col_values(1)
        next_row = len(col_a) + 1
        row = [
            save_data["date"], "", "Да" if save_data["inbox_clear"] else "Нет",
            save_data["projects_with_na"], save_data["active_projects"], "",
            save_data["waiting"], "", "", "", "",
            save_data["ai_text"]
        ]
        review_sheet.update(values=[row], range_name=f"A{next_row}:L{next_row}")
    except Exception as e:
        logging.error(f"Ошибка сохранения Weekly Review: {e}")


async def weekly_review_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Еженедельный обзор — ручной вызов через /review."""
    await update.message.reply_text("⏳ Генерирую Weekly Review...")
    try:
        text, save_data = await _build_weekly_review()
        _save_weekly_review(save_data)
        text += "\n✅ _Сохранено в Google Sheets_"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def scheduled_weekly_review(context):
    """Автоматический Weekly Review каждое воскресенье в 19:00."""
    if not TELEGRAM_CHAT_ID:
        return
    try:
        text, save_data = await _build_weekly_review()
        _save_weekly_review(save_data)
        text = "🗓 *Автоматический Weekly Review*\n\n" + text
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка автоматического Weekly Review: {e}")


def _find_similar(new_text: str, existing: list[str], threshold: float = 0.6) -> list[str]:
    """Найти похожие строки по простому сравнению слов (без внешних библиотек)."""
    new_words = set(new_text.lower().split())
    if len(new_words) < 2:
        return []
    similar = []
    for item in existing:
        item_words = set(item.lower().split())
        if not item_words:
            continue
        intersection = new_words & item_words
        union = new_words | item_words
        jaccard = len(intersection) / len(union) if union else 0
        # Также проверяем вхождение (один текст содержит другой)
        contains = (new_text.lower() in item.lower()) or (item.lower() in new_text.lower())
        if jaccard >= threshold or contains:
            similar.append(item)
    return similar[:3]


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — справка по сценариям использования."""
    text = (
        "📖 *GTD ASSISTANT — СПРАВКА*\n\n"

        "*💡 У меня есть идея / задача:*\n"
        "  Просто напиши текст → AI сам определит куда\n"
        "  Голосовое сообщение → транскрибируется и в Inbox\n"
        "  Фото / PDF → извлечёт задачи автоматически\n\n"

        "*⚡ Что делать прямо сейчас:*\n"
        "  /now — выбор по контексту/времени/энергии\n"
        "  /tasks @Phone — задачи по контексту\n"
        "  /tasks 30m — задачи до 30 минут\n"
        "  /done — отметить выполненным\n\n"

        "*🗂 Проекты:*\n"
        "  /projects — все активные + застрявшие\n"
        "  /project — создать новый\n"
        "  /close — завершить проект → архив\n"
        "  /archive — история завершённых\n"
        "  /ref — материалы к проекту\n\n"

        "*⏳ Делегировано / Ожидаю:*\n"
        "  /waiting — список ожидания\n"
        "  /received — получено, закрыть\n\n"

        "*💭 Когда-нибудь / Идеи:*\n"
        "  /someday — список Someday/Maybe\n"
        "  /activate — перевести в активные\n\n"
        "*📥 Inbox:*\n"
        "  /inbox — просмотр необработанных\n"
        "  напиши *обработать* — AI разберёт все\n\n"

        "*🔄 Обзоры (Reviews):*\n"
        "  /review — еженедельный обзор (7 шагов)\n"
        "  /qreview — квартальный обзор H3\n"
        "  /h2review — обзор зон ответственности\n"
        "  /mindsweep — очистка сознания\n\n"

        "*🏔 Горизонты и цели:*\n"
        "  /horizons — пирамида H0-H5\n"
        "  /vision — видение H4 и миссия H5\n"
        "  /h3 — добавить цель на год\n"
        "  /h4 — добавить видение\n"
        "  /h5 — добавить миссию/принципы\n\n"

        "*📅 Календарь:*\n"
        "  /calendar — ближайшие события\n"
        "  /cal\\_sync — синхронизировать дедлайны\n\n"

        "*📊 Аналитика:*\n"
        "  /stats — статистика системы\n"
        "  /digest — утренний дайджест сейчас\n\n"

        "*🔁 Повторяющиеся задачи:*\n"
        "  /repeat 2 weekly — задача №2 каждую неделю\n"
        "  /repeat 2 daily / monthly\n\n"
        "*📦 Архив:*\n"
        "  /close — завершить проект\n"
        "  /archive — история закрытых проектов\n"
        "  /archive 2026 — фильтр по году\n\n"

        "*👥 Встречи и повестки:*\n"
        "  /agendas — список повесток\n"
        "  /agenda Имя: вопрос — добавить\n\n"

        "_Напиши что угодно — бот сам разберётся!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 GTD Assistant запущен!\n\n"
        "Просто напиши что угодно — я добавлю в Inbox и обработаю через AI.\n"
        "Проекты создаются через *Natural Planning* (5 шагов GTD).\n\n"
        "Или используй кнопки меню.",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(),
    )


async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Фильтры: по контексту (@Phone) или по энергии (@Высокая / @Низкая / @Средняя)
    filter_context = None
    filter_energy = None

    ENERGY_MAP = {
        "@высокая": "Высокая", "@high": "Высокая",
        "@средняя": "Средняя", "@medium": "Средняя",
        "@низкая": "Низкая",  "@low": "Низкая",
    }
    filter_time = None  # фильтр по времени в минутах

    if context.args:
        arg = context.args[0]
        # Фильтр по времени: 15m, 30m, 60m, 15мин
        time_match = re.match(r"^(\d+)\s*(?:m|мин|м)$", arg, re.IGNORECASE)
        if time_match:
            filter_time = int(time_match.group(1))
        elif arg.startswith("@") or not arg[0].isdigit():
            arg = arg if arg.startswith("@") else f"@{arg}"
            if arg.lower() in ENERGY_MAP:
                filter_energy = ENERGY_MAP[arg.lower()]
            else:
                filter_context = arg

    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]

    if filter_context:
        next_up = [a for a in next_up if filter_context.lower() in a.get("Контекст", "").lower()]
    if filter_energy:
        next_up = [a for a in next_up if a.get("Энергия", "") == filter_energy]
    if filter_time:
        def _parse_time(t):
            try: return int(str(t).strip())
            except: return 999
        next_up = [a for a in next_up if _parse_time(a.get("Время (мин)", 999)) <= filter_time]

    if not next_up:
        if filter_time:
            msg = f"✅ Нет задач до {filter_time} мин."
        elif filter_energy:
            msg = f"✅ Нет задач с энергией «{filter_energy}»."
        elif filter_context:
            msg = f"✅ Нет задач для контекста {filter_context}."
        else:
            msg = "✅ Нет активных задач."
        await update.message.reply_text(msg)
        return

    priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
    next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))

    if filter_time:
        title = f"⏱ *ЗАДАЧИ до {filter_time} мин*"
    elif filter_energy:
        energy_icon = {"Высокая": "🔋", "Средняя": "⚡", "Низкая": "😴"}[filter_energy]
        title = f"{energy_icon} *ЗАДАЧИ — энергия «{filter_energy}»*"
    elif filter_context:
        title = f"⚡ *ЗАДАЧИ {filter_context}*"
    else:
        title = "⚡ *ВСЕ ЗАДАЧИ*"

    text = f"{title}\n\n"
    today_date = date.today()

    for i, a in enumerate(next_up[:10], 1):
        p = a.get("Приоритет", "")
        icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
        action = a.get("Действие", "—")
        context_tag = a.get("Контекст", "")
        time_est = a.get("Время (мин)", "")
        area = a.get("Область (Area)", "")
        energy = a.get("Энергия", "")
        deadline = a.get("Срок", "")
        time_str = f"_{time_est} мин_" if time_est else ""
        energy_str = f" 🔋" if energy == "Высокая" else f" 😴" if energy == "Низкая" else ""

        deadline_str = ""
        if deadline:
            try:
                dl = date.fromisoformat(deadline)
                diff = (dl - today_date).days
                if diff < 0:
                    deadline_str = f" 🚨 _просрочено {abs(diff)}д_"
                elif diff == 0:
                    deadline_str = " ⚠️ _сегодня!_"
                elif diff == 1:
                    deadline_str = " ⏰ _завтра_"
                else:
                    deadline_str = f" 📅 _{dl.strftime('%d.%m')}_"
            except ValueError:
                pass

        text += f"{i}. {icon}{energy_str} {action}{deadline_str}\n"
        text += f"   {context_tag} · {area} · {time_str}\n\n"

    if not filter_context and not filter_energy and not filter_time:
        text += "_Контекст: /tasks @Phone · @Computer · @WhatsApp_\n"
        text += "_Энергия: /tasks @Высокая · @Низкая_\n"
        text += "_Время: /tasks 15m · /tasks 30m · /tasks 60m_"

    await update.message.reply_text(text, parse_mode="Markdown")


async def now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/now — интерактивный GTD-выбор: где ты, сколько времени, какая энергия."""
    keyboard = ReplyKeyboardMarkup(
        [
            ["📱 @Phone", "💻 @Computer", "📧 @Email"],
            ["🏢 @Office", "🏠 @Home", "🌍 @Anywhere"],
            ["💬 @WhatsApp", "📞 @Calls", "🚶 @Errands"],
        ],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "⚡ *Что делаем прямо сейчас?*\n\n_Выбери где ты находишься:_",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    context.user_data["now_step"] = "context"


async def now_handle_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2 /now — выбрать сколько времени есть."""
    text = update.message.text.strip()
    ctx_map = {
        "📱 @Phone": "@Phone", "💻 @Computer": "@Computer", "📧 @Email": "@Email",
        "🏢 @Office": "@Office", "🏠 @Home": "@Home", "🌍 @Anywhere": "@Anywhere",
        "💬 @WhatsApp": "@WhatsApp", "📞 @Calls": "@Phone", "🚶 @Errands": "@Errands",
    }
    chosen_context = ctx_map.get(text, text if text.startswith("@") else None)
    if not chosen_context:
        return False
    context.user_data["now_context"] = chosen_context
    context.user_data["now_step"] = "time"

    keyboard = ReplyKeyboardMarkup(
        [["⚡ 15 мин", "🕐 30 мин", "🕑 1 час", "🕒 2+ часа"]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.message.reply_text(
        f"*{chosen_context}* — сколько времени есть?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return True


async def now_handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3 /now — выбрать уровень энергии."""
    text = update.message.text.strip()
    time_map = {"⚡ 15 мин": 15, "🕐 30 мин": 30, "🕑 1 час": 60, "🕒 2+ часа": 999}
    chosen_time = time_map.get(text)
    if chosen_time is None:
        try:
            chosen_time = int(text.replace("мин", "").replace("m", "").strip())
        except ValueError:
            return False
    context.user_data["now_time"] = chosen_time
    context.user_data["now_step"] = "energy"

    keyboard = ReplyKeyboardMarkup(
        [["🔋 Высокая", "⚡ Средняя", "😴 Низкая"]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.message.reply_text(
        "Какой уровень энергии?",
        reply_markup=keyboard,
    )
    return True


async def now_handle_energy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финал /now — показать отфильтрованные задачи."""
    text = update.message.text.strip()
    energy_map = {"🔋 Высокая": "Высокая", "⚡ Средняя": "Средняя", "😴 Низкая": "Низкая"}
    chosen_energy = energy_map.get(text)
    if not chosen_energy:
        return False

    ctx = context.user_data.get("now_context", "")
    max_time = context.user_data.get("now_time", 999)
    context.user_data.pop("now_step", None)
    context.user_data.pop("now_context", None)
    context.user_data.pop("now_time", None)

    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]

    if ctx and ctx != "@Anywhere":
        next_up = [a for a in next_up if ctx.lower() in a.get("Контекст", "").lower()]
    if max_time < 999:
        def _t(a):
            try: return int(str(a.get("Время (мин)", 999)).strip())
            except: return 999
        next_up = [a for a in next_up if _t(a) <= max_time]
    if chosen_energy == "Низкая":
        next_up = [a for a in next_up if a.get("Энергия", "") in ("Низкая", "Средняя", "")]
    elif chosen_energy == "Средняя":
        next_up = [a for a in next_up if a.get("Энергия", "") in ("Средняя", "Низкая", "")]

    priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
    next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))

    time_label = f"{max_time} мин" if max_time < 999 else "2+ часа"
    energy_icon = {"Высокая": "🔋", "Средняя": "⚡", "Низкая": "😴"}[chosen_energy]

    if not next_up:
        await update.message.reply_text(
            f"✅ Нет задач для: {ctx} · {time_label} · {chosen_energy}\n\n"
            f"Попробуй `/tasks` без фильтров или добавь новые задачи.",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(),
        )
        return True

    today_date = date.today()
    result = f"⚡ *ЧТО ДЕЛАТЬ СЕЙЧАС*\n{ctx} · {time_label} · {energy_icon}\n\n"
    for i, a in enumerate(next_up[:7], 1):
        p = a.get("Приоритет", "")
        p_icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
        action = a.get("Действие", "—")
        t = a.get("Время (мин)", "")
        dl = a.get("Срок", "")
        deadline_str = ""
        if dl:
            try:
                diff = (date.fromisoformat(dl) - today_date).days
                if diff < 0: deadline_str = f" 🚨"
                elif diff == 0: deadline_str = f" ⚠️сегодня"
                elif diff == 1: deadline_str = f" ⏰завтра"
            except ValueError:
                pass
        result += f"{i}. {p_icon} {action}{deadline_str}\n   _{t} мин_\n\n"

    result += f"_Выполнил? /done <номер>_"
    await update.message.reply_text(result, parse_mode="Markdown", reply_markup=_main_keyboard())
    return True


async def set_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/repeat <номер> <daily|weekly|monthly> — сделать задачу повторяющейся."""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "📅 *Повторяющаяся задача*\n\n"
            "Формат: `/repeat <номер> <периодичность>`\n\n"
            "Периодичность:\n"
            "  `daily` — каждый день\n"
            "  `weekly` — каждую неделю\n"
            "  `monthly` — каждый месяц\n\n"
            "Сначала посмотри список: `/done`",
            parse_mode="Markdown"
        )
        return
    try:
        idx = int(context.args[0]) - 1
        period = context.args[1].lower()
    except ValueError:
        await update.message.reply_text("⚠️ Укажи номер и период: `/repeat 2 weekly`", parse_mode="Markdown")
        return

    valid_periods = {"daily": "daily", "ежедневно": "daily", "weekly": "weekly",
                     "еженедельно": "weekly", "monthly": "monthly", "ежемесячно": "monthly"}
    if period not in valid_periods:
        await update.message.reply_text("⚠️ Период: `daily`, `weekly` или `monthly`", parse_mode="Markdown")
        return

    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]
    priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
    next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))

    if idx < 0 or idx >= len(next_up):
        await update.message.reply_text(f"⚠️ Номер от 1 до {len(next_up)}.")
        return

    task = next_up[idx]
    action_name = task.get("Действие", "—")
    period_normalized = valid_periods[period]
    period_labels = {"daily": "ежедневно", "weekly": "еженедельно", "monthly": "ежемесячно"}

    try:
        sheet = get_sheet("next_actions")
        all_rows = sheet.get_all_values()
        headers = all_rows[0] if all_rows else []
        action_col = headers.index("Действие") + 1 if "Действие" in headers else 2
        status_col = headers.index("Статус") + 1 if "Статус" in headers else 6

        # Найти или создать колонку Повтор
        if "Повтор" in headers:
            repeat_col = headers.index("Повтор") + 1
        else:
            repeat_col = len(headers) + 1
            sheet.update_cell(1, repeat_col, "Повтор")

        for i, row in enumerate(all_rows[1:], 2):
            if len(row) >= action_col and row[action_col - 1] == action_name:
                if len(row) >= status_col and row[status_col - 1] == "Next":
                    sheet.update_cell(i, repeat_col, period_normalized)
                    await update.message.reply_text(
                        f"🔄 *Повтор установлен*\n\n_{action_name}_\n\n"
                        f"Периодичность: *{period_labels[period_normalized]}*\n"
                        f"После `/done` автоматически создастся следующая.",
                        parse_mode="Markdown"
                    )
                    return
        await update.message.reply_text("❌ Задача не найдена.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пометить задачу выполненной. /done <номер> или /done (покажет список)."""
    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]

    priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
    next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))

    # Если номер не передан — показать список
    if not context.args:
        if not next_up:
            await update.message.reply_text("✅ Нет активных задач.")
            return
        text = "✅ *ОТМЕТИТЬ ВЫПОЛНЕННОЙ*\n\nВведи `/done <номер>`:\n\n"
        for i, a in enumerate(next_up[:15], 1):
            p = a.get("Приоритет", "")
            icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
            text += f"{i}. {icon} {a.get('Действие', '—')}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    # Получить номер задачи
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("⚠️ Укажи номер задачи: `/done 3`", parse_mode="Markdown")
        return

    if idx < 0 or idx >= len(next_up):
        await update.message.reply_text(f"⚠️ Номер должен быть от 1 до {len(next_up)}.")
        return

    task = next_up[idx]
    action_name = task.get("Действие", "—")

    # Найти строку в таблице и обновить статус
    try:
        sheet = get_sheet("next_actions")
        all_rows = sheet.get_all_values()
        headers = all_rows[0] if all_rows else []

        action_col = headers.index("Действие") + 1 if "Действие" in headers else 2
        status_col = headers.index("Статус") + 1 if "Статус" in headers else 6

        found = False
        for i, row in enumerate(all_rows[1:], 2):
            if len(row) >= action_col and row[action_col - 1] == action_name:
                if len(row) >= status_col and row[status_col - 1] == "Next":
                    sheet.update_cell(i, status_col, "Done")
                    found = True
                    break

        if found:
            today_str = date.today().isoformat()
            try:
                done_col = headers.index("Дата выполнения") + 1
                sheet.update_cell(i, done_col, today_str)
            except (ValueError, UnboundLocalError):
                pass

            # Повторяющиеся задачи — создать следующую
            recurring_text = ""
            try:
                repeat_col = headers.index("Повтор") + 1
                repeat_val = row[repeat_col - 1] if len(row) >= repeat_col else ""
                if repeat_val:
                    from datetime import timedelta
                    delta_map = {
                        "daily": timedelta(days=1), "ежедневно": timedelta(days=1),
                        "weekly": timedelta(weeks=1), "еженедельно": timedelta(weeks=1),
                        "monthly": timedelta(days=30), "ежемесячно": timedelta(days=30),
                    }
                    delta = delta_map.get(repeat_val.lower().strip())
                    if delta:
                        next_date = (date.today() + delta).isoformat()
                        new_row = list(row)
                        new_row[status_col - 1] = "Next"
                        try:
                            deadline_col = headers.index("Срок") + 1
                            new_row[deadline_col - 1] = next_date
                        except ValueError:
                            pass
                        try:
                            done_col2 = headers.index("Дата выполнения") + 1
                            new_row[done_col2 - 1] = ""
                        except ValueError:
                            pass
                        sheet.append_row(new_row, value_input_option="USER_ENTERED")
                        recurring_text = f"\n🔄 Повтор создан на {next_date}"
            except (ValueError, IndexError):
                pass

            await update.message.reply_text(
                f"✅ *Выполнено!*\n\n_{action_name}_{recurring_text}\n\n💪 Отличная работа!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Задача не найдена в таблице.")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def close_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/close <номер> [заметка] — завершить проект и отправить в архив."""
    # Сбросить любые активные процессы
    context.user_data.pop("np_state", None)
    context.user_data.pop("now_step", None)
    context.user_data.pop("wr", None)
    projects = read_projects()
    active = [p for p in projects if p.get("Статус", "") not in ("Завершён", "Отменён", "Done")]

    if not context.args:
        if not active:
            await update.message.reply_text("✅ Нет активных проектов.")
            return
        text = "🏁 *ЗАВЕРШИТЬ ПРОЕКТ*\n\nВведи `/close <номер>` или `/close <номер> заметка`:\n\n"
        for i, p in enumerate(active[:15], 1):
            pr = p.get("Приоритет", "")
            icon = "🔴" if pr == "Высокий" else "🟡" if pr == "Средний" else "🟢"
            text += f"{i}. {icon} {p.get('Название проекта', p.get('Проект', '—'))}\n"
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_main_keyboard())
        return

    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("⚠️ Укажи номер: `/close 2`", parse_mode="Markdown")
        return

    if idx < 0 or idx >= len(active):
        await update.message.reply_text(f"⚠️ Номер от 1 до {len(active)}.")
        return

    project = active[idx]
    proj_name = project.get("Название проекта") or project.get("Проект") or "—"
    notes = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    today_str = date.today().isoformat()

    try:
        proj_sheet = get_sheet("projects")
        all_rows = proj_sheet.get_all_values()
        headers = all_rows[0] if all_rows else []

        name_col = next((i for i, h in enumerate(headers) if "Название" in h or "Проект" in h), 1)
        status_col = next((i for i, h in enumerate(headers) if "Статус" in h), 5)

        # Найти строку проекта и обновить статус
        proj_row_num = None
        proj_row = None
        for i, row in enumerate(all_rows[1:], 2):
            if len(row) > name_col and row[name_col] == proj_name:
                if len(row) <= status_col or row[status_col] not in ("Завершён", "Отменён", "Done"):
                    proj_sheet.update_cell(i, status_col + 1, "Завершён")
                    # Дата завершения
                    date_col = next((j for j, h in enumerate(headers) if "Дата" in h and "завер" in h.lower()), None)
                    if date_col is not None:
                        proj_sheet.update_cell(i, date_col + 1, today_str)
                    proj_row_num = i
                    proj_row = row
                    break

        # Закрыть связанные Next Actions
        actions_sheet = get_sheet("next_actions")
        act_rows = actions_sheet.get_all_values()
        act_headers = act_rows[0] if act_rows else []
        act_status_col = next((j for j, h in enumerate(act_headers) if "Статус" in h), 5)
        act_proj_col = next((j for j, h in enumerate(act_headers) if "Проект" in h), None)

        closed_actions = 0
        if act_proj_col is not None:
            for i, row in enumerate(act_rows[1:], 2):
                if len(row) > act_proj_col and proj_name.lower() in row[act_proj_col].lower():
                    if len(row) > act_status_col and row[act_status_col] == "Next":
                        actions_sheet.update_cell(i, act_status_col + 1, "Done")
                        closed_actions += 1

        # Подсчитать материалы в Reference связанные с проектом
        ref_count = 0
        ref_names = []
        try:
            ref_rows = _read_reference()
            for r in ref_rows:
                proj_field = r.get("Проект", "") or ""
                if proj_name.lower() in proj_field.lower():
                    ref_count += 1
                    content_preview = str(r.get("Материал", r.get("Содержание", ""))).strip()[:40]
                    if content_preview:
                        ref_names.append(content_preview)
        except Exception:
            pass

        # Сохранить в ARCHIVE
        archive_sheet = get_sheet("archive")
        arch_rows = archive_sheet.get_all_values()
        arch_id = f"ARC-{len(arch_rows):03d}"
        desired_outcome = project.get("Желаемый итог", project.get("Итог", ""))
        area = project.get("Область (Area)", project.get("Область", ""))
        priority = project.get("Приоритет", "")
        start_date = project.get("Дата создания", project.get("Дата", ""))
        archive_sheet.append_row(
            [arch_id, proj_name, desired_outcome, area, priority,
             start_date, today_str, str(closed_actions), notes],
            value_input_option="USER_ENTERED"
        )

        actions_str = f"\n✅ Закрыто действий: {closed_actions}" if closed_actions else ""
        notes_str = f"\n📝 Заметка: _{notes}_" if notes else ""

        ref_str = ""
        if ref_count > 0:
            ref_preview = ", ".join(ref_names[:3])
            if len(ref_names) > 3:
                ref_preview += f" и ещё {ref_count - 3}"
            ref_str = f"\n📚 Материалов в архиве: {ref_count} — _{ref_preview}_\nПросмотр: `/ref {proj_name}`"

        await update.message.reply_text(
            f"🏆 *Проект завершён!*\n\n"
            f"_{proj_name}_\n"
            f"{actions_str}"
            f"{ref_str}"
            f"{notes_str}\n\n"
            f"Сохранено в архив. Просмотр: /archive",
            parse_mode="Markdown",
            reply_markup=_main_keyboard()
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def show_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/archive [год] [область] — просмотр завершённых проектов."""
    try:
        sheet = get_sheet("archive")
        rows = sheet.get_all_records()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    if not rows:
        await update.message.reply_text(
            "📦 Архив пуст.\n\nЗавершай проекты через `/close <номер>`.",
            parse_mode="Markdown"
        )
        return

    # Фильтры из аргументов
    filter_year = None
    filter_area = None
    if context.args:
        for arg in context.args:
            if arg.isdigit() and len(arg) == 4:
                filter_year = arg
            else:
                filter_area = arg

    filtered = rows
    if filter_year:
        filtered = [r for r in filtered if str(r.get("Дата завершения", "")).startswith(filter_year)]
    if filter_area:
        filtered = [r for r in filtered if filter_area.lower() in r.get("Область", "").lower()]

    if not filtered:
        await update.message.reply_text(f"📦 Нет проектов по фильтру.")
        return

    # Группировка по году
    from collections import defaultdict
    by_year: dict = defaultdict(list)
    for r in filtered:
        d = str(r.get("Дата завершения", ""))
        year = d[:4] if d else "—"
        by_year[year].append(r)

    # Подгружаем Reference для подсчёта материалов
    try:
        all_refs = _read_reference()
    except Exception:
        all_refs = []

    def _ref_count_for(proj_name: str) -> int:
        return sum(1 for r in all_refs if proj_name.lower() in str(r.get("Проект", "")).lower())

    text = "📦 *АРХИВ ПРОЕКТОВ*\n\n"
    for year in sorted(by_year.keys(), reverse=True):
        items = by_year[year]
        text += f"*{year}* — {len(items)} проектов\n"
        for r in items[:10]:
            name = r.get("Название проекта", "—")
            area = r.get("Область", "")
            d = str(r.get("Дата завершения", ""))
            date_str = d[5:10].replace("-", ".") if len(d) >= 10 else ""
            area_tag = f" · _{area}_" if area else ""
            rc = _ref_count_for(name)
            ref_tag = f" 📚{rc}" if rc > 0 else ""
            actions_done = r.get("Действий выполнено", "")
            actions_tag = f" · ✅{actions_done}" if actions_done and str(actions_done) != "0" else ""
            text += f"  🏆 {name}{area_tag}{actions_tag}{ref_tag} · {date_str}\n"
        if len(items) > 10:
            text += f"  _...и ещё {len(items) - 10}_\n"
        text += "\n"

    total = len(rows)
    text += f"_Всего в архиве: {total} проектов_\n"
    text += "_📚N = материалы проекта · ✅N = выполненных действий_\n"
    if not filter_year:
        text += "_Фильтр: /archive 2026 · /archive Business_\n"
    text += "_Материалы проекта: /ref название проекта_"

    await update.message.reply_text(text, parse_mode="Markdown")


def _read_reference() -> list[dict]:
    """Вернуть все строки листа REFERENCE."""
    try:
        sheet = get_sheet("reference")
        return sheet.get_all_records()
    except Exception:
        return []


def _save_reference_row(content: str, project: str = "", area: str = "",
                        source: str = "Telegram", url: str = "", notes: str = "") -> None:
    """Сохранить строку в лист REFERENCE."""
    today = date.today().isoformat()
    ref_sheet = get_sheet("reference")
    all_rows = ref_sheet.get_all_values()
    next_row = len(all_rows) + 1
    row = ["", today, content[:400], project[:100], area[:50], source, url[:300], notes[:200]]
    ref_sheet.update(values=[row], range_name=f"A{next_row}:H{next_row}")


async def show_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ref [проект] — показать вспомогательные материалы."""
    filter_project = " ".join(context.args).strip().lower() if context.args else ""
    items = _read_reference()

    if filter_project:
        items = [r for r in items if filter_project in str(r.get("Проект", "")).lower()
                 or filter_project in str(r.get("Содержимое", "")).lower()]
        title = f"📚 *МАТЕРИАЛЫ: {filter_project.upper()}*"
    else:
        title = "📚 *СПРАВОЧНЫЕ МАТЕРИАЛЫ*"

    items = [r for r in items if str(r.get("Содержимое", "")).strip()
             and not str(r.get("Содержимое", "")).startswith("#")]

    if not items:
        msg = f"{title}\n\nМатериалов нет.\n\n"
        if filter_project:
            msg += f"_Добавь: `ref: {filter_project}: текст или ссылка`_"
        else:
            msg += "_Добавь: `ref: Проект: текст или ссылка`_"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    # Группируем по проектам
    by_project: dict[str, list] = {}
    for r in items:
        proj = (r.get("Проект") or "Без проекта").strip() or "Без проекта"
        by_project.setdefault(proj, []).append(r)

    text = f"{title} ({len(items)})\n\n"
    for proj, rows in sorted(by_project.items()):
        text += f"📁 *{proj}* ({len(rows)})\n"
        for r in rows[:5]:
            content = str(r.get("Содержимое", "—"))[:70]
            url = str(r.get("Ссылка", "")).strip()
            d = str(r.get("Дата", ""))[:10]
            url_str = f" 🔗" if url else ""
            text += f"  · _{content}_{url_str} _{d}_\n"
        if len(rows) > 5:
            text += f"  _...ещё {len(rows) - 5}_\n"
        text += "\n"

    text += "_Добавить: `ref: Проект: заметка`_\n_Фильтр: `/ref название проекта`_"
    await update.message.reply_text(text, parse_mode="Markdown")


def _ref_project_keyboard(projects: list[str]) -> ReplyKeyboardMarkup:
    """Клавиатура выбора проекта для материала."""
    rows = []
    for i, name in enumerate(projects[:10], 1):
        rows.append([KeyboardButton(f"{i}. {name[:50]}")])
    rows.append([KeyboardButton("📂 Без проекта"), KeyboardButton("❌ Отмена")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


async def _ask_ref_project(update: Update, context: ContextTypes.DEFAULT_TYPE, content: str):
    """Показать список проектов для выбора к материалу."""
    projects = read_projects()
    active_names = [p.get("Название проекта", "") for p in projects
                    if p.get("Статус") == "Активен" and p.get("Название проекта", "").strip()]

    if not active_names:
        _save_reference_row(content, source="Telegram")
        await update.message.reply_text(
            f"📚 *Материал сохранён* (без проекта)\n\n_{content[:150]}_",
            parse_mode="Markdown",
            reply_markup=_main_keyboard(),
        )
        return

    context.user_data["ref_pending"] = {"content": content, "projects": active_names}
    await update.message.reply_text(
        f"📚 *К какому проекту добавить?*\n\n_{content[:120]}_\n\nВыбери проект:",
        parse_mode="Markdown",
        reply_markup=_ref_project_keyboard(active_names),
    )


async def _handle_ref_project_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обработать выбор проекта для материала. Возвращает True если обработано."""
    pending = context.user_data.get("ref_pending")
    if not pending:
        return False

    text = update.message.text
    content = pending["content"]
    projects = pending["projects"]

    if text == "❌ Отмена":
        context.user_data.pop("ref_pending", None)
        await update.message.reply_text("❌ Отменено.", reply_markup=_main_keyboard())
        return True

    project = ""
    if text == "📂 Без проекта":
        project = ""
    else:
        # Попытка выбрать по номеру "1. Название"
        m = re.match(r"^(\d+)\.\s*(.+)$", text)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(projects):
                project = projects[idx]
        if not project:
            project = text.strip()

    context.user_data.pop("ref_pending", None)
    _save_reference_row(content, project=project, source="Telegram")
    proj_str = f"Проект: *{project}*\n" if project else "_Без проекта_\n"
    await update.message.reply_text(
        f"📚 *Материал сохранён*\n\n{proj_str}_{content[:150]}_\n\n"
        + (f"Просмотр: `/ref {project}`" if project else "Просмотр: `/ref`"),
        parse_mode="Markdown",
        reply_markup=_main_keyboard(),
    )
    return True


async def add_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ref [Проект: заметка] — добавить материал или просмотреть список."""
    raw = " ".join(context.args).strip() if context.args else ""

    if ":" in raw:
        # Формат: /ref Проект: текст — сохраняем сразу
        project, _, content = raw.partition(":")
        project = project.strip()
        content = content.strip()
        if project and content:
            _save_reference_row(content, project=project, source="Telegram/Command")
            await update.message.reply_text(
                f"📚 *Материал добавлен*\n\n"
                f"Проект: *{project}*\n"
                f"_{content[:150]}_\n\n"
                f"Просмотр: `/ref {project}`",
                parse_mode="Markdown",
            )
            return
    elif raw:
        # /ref текст без двоеточия — спрашиваем проект
        await _ask_ref_project(update, context, raw)
        return

    # Без аргументов — показать список
    await show_reference(update, context)


def _get_projects_with_actions(active_projects: list, all_actions: list) -> dict[str, list]:
    """Вернуть словарь {название_проекта: [действия]} для активных проектов."""
    result: dict[str, list] = {}
    for p in active_projects:
        name = p.get("Название проекта", "")
        if not name:
            continue
        linked = [
            a for a in all_actions
            if a.get("Статус") == "Next"
            and name.lower() in str(a.get("Проект", "")).lower()
        ]
        result[name] = linked
    return result


async def show_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]

    if not active:
        await update.message.reply_text(
            "🗂 Нет активных проектов.\n\n"
            "Создай проект: /project или кнопка *📋 Новый проект*",
            parse_mode="Markdown"
        )
        return

    all_actions = read_next_actions()
    proj_actions = _get_projects_with_actions(active, all_actions)

    ref_items = _read_reference()
    ref_by_project: dict[str, int] = {}
    for r in ref_items:
        proj = str(r.get("Проект", "")).strip()
        if proj:
            ref_by_project[proj] = ref_by_project.get(proj, 0) + 1

    # Застрявшие — без Next Actions в реальном листе
    stuck = [p for p in active if not proj_actions.get(p.get("Название проекта", ""))]

    text = "🗂 *АКТИВНЫЕ ПРОЕКТЫ*\n\n"

    if stuck:
        text += f"⚠️ *ЗАСТРЯВШИЕ ({len(stuck)}) — нет следующего действия:*\n"
        for p in stuck[:5]:
            name = p.get("Название проекта", "—")
            text += f"  🔸 {name}\n"
        text += "_Добавь действие: напиши задачу и укажи проект_\n\n"

    for i, p in enumerate(active[:10], 1):
        name = p.get("Название проекта", "—")
        priority = p.get("Приоритет", "")
        outcome = p.get("Желаемый результат", p.get("Желаемый итог", ""))
        notes = p.get("Заметки", "")
        why = ""
        if notes and "ПОЧЕМУ:" in notes:
            why = notes.split("ПОЧЕМУ:")[1].split("\n")[0].strip()
        icon = "🔴" if priority == "Высокий" else "🟡" if priority == "Средний" else "🟢"
        ref_count = ref_by_project.get(name, 0)
        ref_str = f" 📚{ref_count}" if ref_count else ""
        linked_actions = proj_actions.get(name, [])
        stuck_flag = " ⚠️" if not linked_actions else ""

        text += f"{i}. {icon} *{name}*{ref_str}{stuck_flag}\n"
        if why:
            text += f"   💡 _{why[:80]}_\n"
        if outcome:
            text += f"   🎯 _{outcome[:80]}_\n"
        if linked_actions:
            top_action = linked_actions[0].get("Действие", "")
            text += f"   → {top_action[:70]}\n"
            if len(linked_actions) > 1:
                text += f"   _+{len(linked_actions)-1} ещё_\n"
        text += "\n"

    text += "_Новый проект: /project · Закрыть: /close · Материалы: /ref_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_date = date.today()
    week_ago = (today_date - timedelta(days=7)).isoformat()

    inbox = read_inbox()
    actions = read_next_actions()
    projects = read_projects()

    new_inbox = len([r for r in inbox if r.get("Статус") == "Новый"])
    next_actions_list = [a for a in actions if a.get("Статус") == "Next"]
    waiting_list = [a for a in actions if a.get("Статус") == "Waiting"]
    done_week = [a for a in actions if a.get("Статус") == "Done"
                 and str(a.get("Дата выполнения", "")) >= week_ago]
    active_projects = [p for p in projects if p.get("Статус") == "Активен"]

    # Просроченные
    overdue = []
    for a in next_actions_list:
        dl = a.get("Срок", "")
        if dl:
            try:
                if date.fromisoformat(str(dl)) < today_date:
                    overdue.append(a)
            except ValueError:
                pass

    # Застрявшие проекты
    proj_actions_map = _get_projects_with_actions(active_projects, actions)
    stuck_projects = [p for p in active_projects if not proj_actions_map.get(p.get("Название проекта", ""))]

    # Топ контексты
    from collections import Counter
    ctx_counter = Counter(
        a.get("Контекст", "").strip()
        for a in next_actions_list
        if a.get("Контекст", "").strip()
    )

    # Архив
    try:
        arch_rows = get_sheet("archive").get_all_records()
        arch_week = [r for r in arch_rows if str(r.get("Дата завершения", "")) >= week_ago]
        arch_total = len(arch_rows)
    except Exception:
        arch_week = []
        arch_total = 0

    text = (
        f"📊 *СТАТИСТИКА GTD*\n"
        f"_{today_date.strftime('%d.%m.%Y')}_\n\n"
    )

    # Здоровье системы
    health_issues = []
    if new_inbox > 0: health_issues.append(f"📥 Inbox не обработан ({new_inbox})")
    if overdue: health_issues.append(f"🚨 Просрочено ({len(overdue)})")
    if stuck_projects: health_issues.append(f"⚠️ Застрявших проектов ({len(stuck_projects)})")

    if health_issues:
        text += "⚠️ *Требует внимания:*\n"
        for h in health_issues:
            text += f"  {h}\n"
        text += "\n"
    else:
        text += "✅ *Система в порядке*\n\n"

    text += (
        f"📥 Inbox новых:       {new_inbox}\n"
        f"⚡ Next Actions:      {len(next_actions_list)}\n"
        f"⏳ Waiting For:       {len(waiting_list)}\n"
        f"🗂 Активных проектов: {len(active_projects)}\n"
        f"⚠️ Застрявших:        {len(stuck_projects)}\n\n"
    )

    text += f"*За последние 7 дней:*\n"
    text += f"  ✅ Выполнено задач: {len(done_week)}\n"
    text += f"  🏆 Закрыто проектов: {len(arch_week)}\n\n"

    if arch_total > 0:
        text += f"📦 Всего в архиве: {arch_total} проектов\n\n"

    if ctx_counter:
        text += "*Топ контексты:*\n"
        for ctx, cnt in ctx_counter.most_common(5):
            text += f"  {ctx}: {cnt}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ─── NATURAL PLANNING ─────────────────────────────────────────────────────────

def _np_keyboard(show_accept: bool = False):
    rows = []
    if show_accept:
        rows.append([KeyboardButton(_NP_ACCEPT), KeyboardButton(_NP_SKIP)])
    else:
        rows.append([KeyboardButton(_NP_SKIP)])
    rows.append([KeyboardButton(_NP_CANCEL)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _clear_np(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("np", None)
    context.user_data.pop("np_state", None)


def _np_value(text: str, current: str = "") -> str:
    """Вернуть значение шага: принять AI, пропустить или ввод пользователя."""
    if text == _NP_ACCEPT:
        return current
    if text == _NP_SKIP:
        return ""
    return text.strip()


async def project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск Natural Planning: /project"""
    _clear_np(context)
    context.user_data["np"] = {
        "area": "", "priority": "Средний", "context": "@Anywhere",
        "energy": "", "time": "", "deadline": "",
    }
    context.user_data["np_state"] = NP_NAME
    await update.message.reply_text(
        "🗂 *NATURAL PLANNING — новый проект*\n\n"
        "Модель GTD из 5 шагов:\n"
        "1️⃣ Зачем → 2️⃣ Итог → 3️⃣ Идеи → 4️⃣ Этапы → 5️⃣ Действие\n\n"
        "📝 *Шаг 1/5 — Название*\n"
        "Как назвать этот проект?",
        parse_mode="Markdown",
        reply_markup=_np_keyboard(),
    )


async def np_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена Natural Planning: /cancel"""
    if context.user_data.get("np_state") is not None:
        _clear_np(context)
        await update.message.reply_text("❌ Создание проекта отменено.", reply_markup=_main_keyboard())
    else:
        await update.message.reply_text("Нечего отменять. Для Weekly Review: /review → ⛔ Закончить обзор")


async def np_start_from_ai(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           name: str, ai_result: dict):
    """Запустить Natural Planning с предзаполнением от AI."""
    _clear_np(context)
    context.user_data["np"] = {
        "name": name[:100],
        "why": ai_result.get("почему", ""),
        "outcome": ai_result.get("итог_проекта", ""),
        "subtasks": ai_result.get("подзадачи", ""),
        "action": ai_result.get("действие", ""),
        "context": ai_result.get("контекст", "@Anywhere"),
        "area": ai_result.get("область", ""),
        "priority": ai_result.get("приоритет", "Средний"),
        "energy": ai_result.get("энергия", ""),
        "time": ai_result.get("время", ""),
        "deadline": ai_result.get("срок", ""),
        "brainstorm": "",
        "source": name,
    }
    context.user_data["np_state"] = NP_WHY
    why_hint = ""
    show_accept = False
    if ai_result.get("почему"):
        why_hint = f"\n\n🤖 AI предлагает:\n_{ai_result['почему']}_"
        show_accept = True
    await update.message.reply_text(
        f"🗂 *NATURAL PLANNING*\n\n"
        f"📌 Проект: _{name[:100]}_\n\n"
        f"1️⃣ *Зачем этот проект?* (цель, намерение){why_hint}",
        parse_mode="Markdown",
        reply_markup=_np_keyboard(show_accept=show_accept),
    )


async def _np_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранить проект и завершить Natural Planning."""
    np = context.user_data.get("np", {})
    name = np.get("name", "Без названия")
    outcome = np.get("outcome") or np.get("why") or name
    action = np.get("action") or f"Определить первый шаг по проекту: {name}"

    try:
        save_project(
            name, outcome, np.get("area", ""), np.get("priority", "Средний"),
            action, np.get("context", "@Anywhere"),
            why=np.get("why", ""),
            brainstorm=np.get("brainstorm", ""),
            subtasks=np.get("subtasks", ""),
            energy=np.get("energy", ""),
            time_min=np.get("time", ""),
            deadline=np.get("deadline", ""),
            notes_extra=f"Из Telegram: {np.get('source', name)[:80]}",
        )
        _sync_one_deadline(
            action, np.get("deadline", ""), project=name,
            context_tag=np.get("context", ""), priority=np.get("priority", ""),
        )
    except Exception as e:
        _clear_np(context)
        await update.message.reply_text(f"❌ Ошибка сохранения: {e}", reply_markup=_main_keyboard())
        return

    _clear_np(context)
    notes_preview = format_planning_notes(np.get("why", ""), np.get("brainstorm", ""), np.get("subtasks", ""))
    msg = (
        f"✅ *Проект создан!*\n\n"
        f"🗂 *{name}*\n"
    )
    if np.get("why"):
        msg += f"💡 _{np['why']}_\n"
    if np.get("outcome"):
        msg += f"🎯 _{np['outcome']}_\n"
    if np.get("subtasks"):
        msg += f"📋 Этапы: _{np['subtasks']}_\n"
    msg += (
        f"\n⚡ *Первое действие:*\n"
        f"_{action}_ ({np.get('context', '@Anywhere')})\n"
    )
    if notes_preview:
        msg += f"\n📝 Сохранено в Google Sheets"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_main_keyboard())


async def np_step_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка шагов Natural Planning."""
    text = update.message.text
    np = context.user_data.setdefault("np", {})
    state = context.user_data.get("np_state")

    if text == _NP_CANCEL or text.lower() in ("/cancel", "отмена"):
        _clear_np(context)
        await update.message.reply_text("❌ Создание проекта отменено.", reply_markup=_main_keyboard())
        return

    if state == NP_NAME:
        if text in (_NP_SKIP, _NP_ACCEPT):
            await update.message.reply_text("⚠️ Название обязательно. Напиши название проекта.")
            return
        np["name"] = text[:100]
        np["source"] = text
        context.user_data["np_state"] = NP_WHY
        await update.message.reply_text(
            f"📌 Проект: _{np['name']}_\n\n"
            f"1️⃣ *Зачем этот проект?* (цель, намерение)\n"
            f"_Например: чтобы расширить бизнес в ЕС_",
            parse_mode="Markdown",
            reply_markup=_np_keyboard(),
        )
        return

    if state == NP_WHY:
        np["why"] = _np_value(text, np.get("why", ""))
        context.user_data["np_state"] = NP_OUTCOME
        outcome_hint = ""
        show_accept = False
        if np.get("outcome"):
            outcome_hint = f"\n\n🤖 AI предлагает:\n_{np['outcome']}_"
            show_accept = True
        await update.message.reply_text(
            f"2️⃣ *Желаемый результат*\n"
            f"Как выглядит ситуация, когда проект завершён успешно?{outcome_hint}",
            parse_mode="Markdown",
            reply_markup=_np_keyboard(show_accept=show_accept),
        )
        return

    if state == NP_OUTCOME:
        np["outcome"] = _np_value(text, np.get("outcome", ""))
        context.user_data["np_state"] = NP_BRAINSTORM
        await update.message.reply_text(
            "3️⃣ *Мозговой штурм*\n"
            "Напиши все идеи, мысли, соображения — без фильтра.\n"
            "Можно списком. Это шаг 3 Natural Planning.",
            parse_mode="Markdown",
            reply_markup=_np_keyboard(),
        )
        return

    if state == NP_BRAINSTORM:
        np["brainstorm"] = _np_value(text, "")
        context.user_data["np_state"] = NP_ORGANIZE
        subtasks_hint = ""
        show_accept = False
        if np.get("subtasks"):
            subtasks_hint = f"\n\n🤖 AI предлагает этапы:\n_{np['subtasks']}_"
            show_accept = True
        await update.message.reply_text(
            f"4️⃣ *Ключевые этапы*\n"
            f"Какие основные шаги/подэтапы? (через ; или списком){subtasks_hint}",
            parse_mode="Markdown",
            reply_markup=_np_keyboard(show_accept=show_accept),
        )
        return

    if state == NP_ORGANIZE:
        np["subtasks"] = _np_value(text, np.get("subtasks", ""))
        context.user_data["np_state"] = NP_ACTION
        action_hint = ""
        show_accept = False
        if np.get("action"):
            action_hint = f"\n\n🤖 AI предлагает:\n_{np['action']}_ ({np.get('context', '')})"
            show_accept = True
        await update.message.reply_text(
            f"5️⃣ *Первое физическое действие*\n"
            f"Что сделать прямо сейчас, чтобы проект двинулся?{action_hint}",
            parse_mode="Markdown",
            reply_markup=_np_keyboard(show_accept=show_accept),
        )
        return

    if state == NP_ACTION:
        np["action"] = _np_value(text, np.get("action", ""))
        if not np.get("area"):
            context.user_data["np_state"] = NP_ACTION + 1  # временный шаг — область
            await update.message.reply_text(
                "📂 *Область* (Business / Finance / Health / Learning / ...)\n"
                "Или нажми ⏭ Пропустить",
                parse_mode="Markdown",
                reply_markup=_np_keyboard(),
            )
            return
        await _np_finish(update, context)
        return

    # Доп. шаг: область (если не была задана AI)
    if state == NP_ACTION + 1:
        if text != _NP_SKIP:
            np["area"] = text.strip()
        await _np_finish(update, context)
        return


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    _MENU_BUTTONS = {
        "⚡ Задачи", "🗂 Проекты", "📊 Статистика", "✅ Выполнено",
        "⏳ Waiting", "🏔 Горизонты", "🏗 Объекты", "📥 Добавить в Inbox",
        "📋 Новый проект", "🔋 Высокая энергия", "😴 Низкая энергия",
        "📱 @Phone", "💻 @Computer", "💬 @WhatsApp",
        "👥 Повестки", "🏢 @Office", "🏠 @Home", "🌍 @Anywhere",
        # Кнопки процессов — не обрабатывать как Inbox
        "Отмена", "❌ Отмена", "Пропустить", "➡️ Пропустить", "Далее", "→ Далее",
        "✅ Готово", "⏭ Пропустить", "⚡ 15 мин", "🕐 30 мин", "🕑 1 час", "🕒 2+ часа",
        "🔋 Высокая", "⚡ Средняя", "😴 Низкая",
        "📧 @Email", "📞 @Calls", "🚶 @Errands",
        "➡️ Следующий шаг", "⛔ Закончить обзор", "🚀 Начать",
        "Да", "Нет", "✅ Да", "❌ Нет",
    }
    _is_menu_btn = text in _MENU_BUTTONS
    if _is_menu_btn:
        if context.user_data.get("np_state") is not None:
            _clear_np(context)
        context.user_data.pop("now_step", None)
        context.user_data.pop("now_context", None)
        context.user_data.pop("now_time", None)
        context.user_data.pop("pending_action", None)

    # Ожидание выбора проекта для материала
    if context.user_data.get("ref_pending"):
        if text in _MENU_BUTTONS:
            # Пользователь нажал кнопку меню — отменяем выбор
            context.user_data.pop("ref_pending", None)
        else:
            handled = await _handle_ref_project_choice(update, context)
            if handled:
                return

    # Ожидание ответа на предупреждение о дубликате
    if context.user_data.get("pending_action"):
        answer = text.strip().lower()
        if answer in ("да", "yes", "добавить", "➕ добавить"):
            pending = context.user_data.pop("pending_action")
            try:
                sheet = get_sheet("next_actions")
                sheet.append_row(pending["row"], value_input_option="USER_ENTERED")
                _sync_one_deadline(
                    pending["action_text"], pending.get("срок", ""),
                    context_tag=pending.get("контекст", ""),
                    priority=pending.get("приоритет", ""),
                )
                await update.message.reply_text(
                    f"✅ *Добавлено в Next Actions*\n\n_{pending['action_text']}_",
                    parse_mode="Markdown"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")
            return
        elif answer in ("нет", "no", "дубликат", "это дубликат"):
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("✅ Понял, дубликат — не добавляю.")
            return

    # /now — пошаговый выбор контекста/времени/энергии
    now_step = context.user_data.get("now_step")
    if now_step == "context":
        handled = await now_handle_context(update, context)
        if handled:
            return
    elif now_step == "time":
        handled = await now_handle_time(update, context)
        if handled:
            return
    elif now_step == "energy":
        handled = await now_handle_energy(update, context)
        if handled:
            return

    # Natural Planning в процессе
    if context.user_data.get("np_state") is not None:
        await np_step_handler(update, context)
        return

    # Кнопки меню
    if text == "⚡ Задачи":
        await show_tasks(update, context)
        return
    elif text == "🗂 Проекты":
        await show_projects(update, context)
        return
    elif text == "📋 Новый проект":
        await project_command(update, context)
        return
    elif text == "📊 Статистика":
        await show_stats(update, context)
        return
    elif text == "✅ Выполнено":
        context.args = []
        await done_task(update, context)
        return
    elif text == "⏳ Waiting":
        await show_waiting(update, context)
        return
    elif text == "🏔 Горизонты":
        await show_horizons(update, context)
        return
    elif text == "🏗 Объекты":
        context.args = []
        await show_biz(update, context)
        return
    elif re.match(r"^h[345]\s*[:：\s]\s*.+", text, re.IGNORECASE):
        # Формат без команды: "h3: открыть офис" или "h3 открыть офис"
        m = re.match(r"^(h[345])\s*[:：\s]\s*(.+)", text, re.IGNORECASE)
        if m:
            await _save_horizon_item(update, m.group(1), m.group(2).strip())
        return
    elif re.match(r"^активировать(\s+\d+)?$", text, re.IGNORECASE):
        m = re.match(r"^активировать\s+(\d+)$", text, re.IGNORECASE)
        context.args = [m.group(1)] if m else []
        await activate_someday(update, context)
        return
    elif re.match(r"^получил(\s+\d+)?$", text, re.IGNORECASE):
        m = re.match(r"^получил\s+(\d+)$", text, re.IGNORECASE)
        context.args = [m.group(1)] if m else []
        await close_waiting(update, context)
        return
    elif re.match(r"^жду\s+от\s+.+:.+$", text, re.IGNORECASE):
        await add_waiting(update, context)
        return
    elif re.match(r"^(повестка|agenda)\s*[:：]\s*.+:.+$", text, re.IGNORECASE):
        m = re.match(r"^(?:повестка|agenda)\s*[:：]\s*(.+:.+)$", text, re.IGNORECASE)
        if m:
            context.args = m.group(1).split()
            await add_agenda(update, context)
        return
    elif re.match(r"^ref\s*[:：]\s*.+$", text, re.IGNORECASE):
        m_two = re.match(r"^ref\s*[:：]\s*(.+?)\s*[:：]\s*(.+)$", text, re.IGNORECASE)
        if m_two:
            # ref: Проект: текст — сохраняем сразу
            project = m_two.group(1).strip()
            content = m_two.group(2).strip()
            _save_reference_row(content, project=project, source="Telegram")
            await update.message.reply_text(
                f"📚 *Материал сохранён*\n\n"
                f"Проект: *{project}*\n"
                f"_{content[:150]}_\n\n"
                f"Просмотр: `/ref {project}`",
                parse_mode="Markdown",
            )
        else:
            # ref: текст — спрашиваем проект
            m_one = re.match(r"^ref\s*[:：]\s*(.+)$", text, re.IGNORECASE)
            if m_one:
                await _ask_ref_project(update, context, m_one.group(1).strip())
        return
    elif text == "📥 Добавить в Inbox":
        await update.message.reply_text("Напиши что добавить в Inbox:")
        return
    elif text == "📱 @Phone":
        context.args = ["@Phone"]
        await show_tasks(update, context)
        return
    elif text == "💻 @Computer":
        context.args = ["@Computer"]
        await show_tasks(update, context)
        return
    elif text == "💬 @WhatsApp":
        context.args = ["@WhatsApp"]
        await show_tasks(update, context)
        return
    elif text == "👥 Повестки":
        await show_agendas(update, context)
        return
    elif text == "🏢 @Office":
        context.args = ["@Office"]
        await show_tasks(update, context)
        return
    elif text == "🏠 @Home":
        context.args = ["@Home"]
        await show_tasks(update, context)
        return
    elif text == "🌍 @Anywhere":
        context.args = ["@Anywhere"]
        await show_tasks(update, context)
        return
    elif text == "🔋 Высокая энергия":
        context.args = ["@Высокая"]
        await show_tasks(update, context)
        return
    elif text == "😴 Низкая энергия":
        context.args = ["@Низкая"]
        await show_tasks(update, context)
        return
    elif text.startswith("@"):
        context.args = [text]
        await show_tasks(update, context)
        return
    elif text.lower() in ("обработать", "обработай", "процесс", "process"):
        await update.message.reply_text("⏳ Обрабатываю Inbox через AI...")
        from inbox_processor import process_inbox
        process_inbox()
        await update.message.reply_text("✅ Inbox обработан! Задачи добавлены в Next Actions.")
        return
    elif text.lower() in ("очистить тест", "очистить", "clear test", "сброс"):
        await update.message.reply_text(
            "⚠️ *Очистка тестовых данных*\n\n"
            "Эта команда очищает только Inbox и Next Actions.\n\n"
            "Для полной очистки всех листов используй:\n"
            "`/cleartest`",
            parse_mode="Markdown"
        )
        return
    elif text.lower() in ("отмена", "удалить", "удали последнее", "undo"):
        try:
            inbox_sheet = get_sheet("inbox")
            all_rows = inbox_sheet.get_all_values()
            if len(all_rows) <= 1:
                await update.message.reply_text("Inbox пуст — нечего удалять.")
                return
            last_row_num = len(all_rows)
            last_content = all_rows[-1][2] if len(all_rows[-1]) > 2 else "?"
            inbox_sheet.delete_rows(last_row_num)
            await update.message.reply_text(f"🗑 Удалена последняя строка из Inbox:\n_{last_content}_", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # Кнопки интерфейса — молча игнорировать, не отправлять в AI
    if _is_menu_btn:
        return

    # Любой другой текст — добавить в Inbox и обработать через AI
    await update.message.reply_text("⏳ Принял, обрабатываю через AI...")

    try:
        # Добавить в Inbox
        today = date.today().isoformat()
        inbox_sheet = get_sheet("inbox")
        inbox_sheet.append_row(
            ["", today, text, "Telegram", "Новый", "", "", ""],
            value_input_option="USER_ENTERED"
        )

        # Загружаем активные проекты для AI
        try:
            _active_proj_names = [
                p.get("Название проекта", "") for p in read_projects()
                if p.get("Статус") == "Активен" and p.get("Название проекта")
            ]
        except Exception:
            _active_proj_names = []

        # Обработать через AI
        result = process_item(text, active_projects=_active_proj_names)

        # ── Business Core routing (Фаза 5) ──────────────────
        _bc_note = ""
        try:
            from business_core.inbox_bridge import route_inbox
            _bc_note = route_inbox(text, result)
        except Exception:
            pass
        # ────────────────────────────────────────────────────

        # Правило 2 минут или добавить в Next Actions
        if result["результат"] == "2min":
            reply = (
                f"⚡ *ПРАВИЛО 2 МИНУТ*\n\n"
                f"Это займёт меньше 2 минут — сделай *прямо сейчас*!\n\n"
                f"👉 {result['действие']}\n\n"
                f"_{result['пояснение']}_"
            )
        elif result["результат"] == "Action":
            actions_sheet = get_sheet("next_actions")
            proj_link = result.get("проект", "")

            # Проверка дубликатов
            existing_actions = [
                a.get("Действие", "") for a in read_next_actions()
                if a.get("Статус") == "Next" and a.get("Действие")
            ]
            action_text = result["действие"]
            duplicates = _find_similar(action_text, existing_actions)
            if duplicates:
                context.user_data["pending_action"] = {
                    "row": ["", action_text, proj_link, result["область"],
                            result["контекст"], "Next", result["приоритет"],
                            result.get("энергия", ""), result["время"],
                            result.get("срок", ""), "", "", "",
                            f"Из Telegram: {text}", today, ""],
                    "action_text": action_text,
                    "срок": result.get("срок", ""),
                    "контекст": result["контекст"],
                    "приоритет": result["приоритет"],
                }
                dups_str = "\n".join(f"  • _{d}_" for d in duplicates)
                reply = (
                    f"⚠️ *Похожая задача уже есть:*\n\n{dups_str}\n\n"
                    f"Новая: _{action_text}_\n\n"
                    f"Добавить всё равно или это дубликат?\n"
                    f"Напиши *да* — добавить · *нет* — это дубликат"
                )
                await update.message.reply_text(reply, parse_mode="Markdown")
                # Обновить статус Inbox
                all_inbox = inbox_sheet.get_all_values()
                for i, row in enumerate(all_inbox):
                    if row and len(row) > 2 and row[2] == text and row[4] == "Новый":
                        inbox_sheet.update_cell(i + 1, 5, "Проверка дубл.")
                        break
                return
            
            action_row = [
                "", action_text, proj_link, result["область"],
                result["контекст"], "Next", result["приоритет"],
                result.get("энергия", ""), result["время"], result.get("срок", ""), "", "", "",
                f"Из Telegram: {text}", today, ""
            ]
            actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")
            _sync_one_deadline(
                result["действие"], result.get("срок", ""),
                context_tag=result["контекст"], priority=result["приоритет"],
            )
            deadline_line = f"*Срок:* {result['срок']}\n" if result.get("срок") else ""
            proj_line = f"*Проект:* {proj_link}\n" if proj_link else ""
            reply = (
                f"✅ *Обработано → Next Actions*\n\n"
                f"📌 _{text}_\n\n"
                f"*Действие:* {result['действие']}\n"
                f"*Контекст:* {result['контекст']}\n"
                f"*Область:* {result['область']}\n"
                f"{proj_line}"
                f"*Приоритет:* {result['приоритет']}\n"
                f"*Время:* {result['время']} мин\n"
                f"{deadline_line}\n"
                f"_{result['пояснение']}_"
                f"{_bc_note}"
            )
        elif result["результат"] == "Project":
            # Проверка дубликатов проектов
            existing_proj_names = [
                p.get("Название проекта", "") for p in read_projects()
                if p.get("Статус") == "Активен" and p.get("Название проекта")
            ]
            proj_dups = _find_similar(text, existing_proj_names, threshold=0.5)
            if proj_dups:
                dups_str = "\n".join(f"  • _{d}_" for d in proj_dups)
                await update.message.reply_text(
                    f"⚠️ *Похожий проект уже существует:*\n\n{dups_str}\n\n"
                    f"Это новый проект или тот же?\n"
                    f"Если новый — напиши `/project {text[:60]}`\n"
                    f"Если тот же — можешь добавить задачу к существующему.",
                    parse_mode="Markdown"
                )
            else:
                # Natural Planning вместо автосоздания
                await np_start_from_ai(update, context, text, result)
                # Обновить статус в Inbox
                all_inbox = inbox_sheet.get_all_values()
                for i, row in enumerate(all_inbox):
                    if row and len(row) > 2 and row[2] == text and row[4] == "Новый":
                        inbox_sheet.update_cell(i + 1, 5, "Обработан")
                        inbox_sheet.update_cell(i + 1, 6, "Project→NP")
                        break
            return
        elif result["результат"] == "Waiting":
            actions_sheet = get_sheet("next_actions")
            whom = result.get("кому", "")
            action_text = result["действие"] or text[:200]
            proj_link_w = result.get("проект", "")
            action_row = [
                "", action_text, proj_link_w, result["область"],
                result["контекст"], "Waiting", result["приоритет"],
                result.get("энергия", ""), result["время"], result.get("срок", ""), whom, "", "",
                f"Из Telegram: {text}", today, ""
            ]
            actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")
            whom_line = f"\n👤 Ждём от: *{whom}*" if whom else ""
            deadline_line = f"\nСрок: {result['срок']}" if result.get("срок") else ""
            reply = (
                f"⏳ *Делегировано → Waiting For*\n\n"
                f"_{text}_\n"
                f"{whom_line}"
                f"{deadline_line}\n\n"
                f"✅ Сохранено в список ожидания\n\n"
                f"_{result['пояснение']}_"
                f"{_bc_note}"
            )
        elif result["результат"] in ("Someday", "SomedayDate"):
            someday_sheet = get_sheet("someday")
            remind_date = result.get("срок", "") if result["результат"] == "SomedayDate" else ""
            # Структура: ID | Идея/Проект | Описание | Область | Пересмотреть | Статус | ID проекта | Добавлен
            someday_row = [
                "", text[:200], result["пояснение"][:300], result["область"],
                remind_date, "Ожидает", "", today
            ]
            all_rows = someday_sheet.get_all_values()
            next_row = len(all_rows) + 1
            someday_sheet.update(values=[someday_row], range_name=f"A{next_row}:H{next_row}")
            date_line = f"\n📅 Напомнить: {remind_date}" if remind_date else ""
            reply = f"💭 *Someday/Maybe*\n\n_{text}_{date_line}\n\n✅ Сохранено в SOMEDAY\n\n_{result['пояснение']}_"
        elif result["результат"] == "Reference":
            ref_project = result.get("проект", "") or result.get("project", "")
            _save_reference_row(
                text, project=ref_project,
                area=result.get("область", ""),
                source="Telegram/Inbox",
                notes=result.get("пояснение", "")[:200],
            )
            proj_str = f"\nПроект: *{ref_project}*" if ref_project else "\n_Проект не определён — добавь вручную: `ref: Проект: текст`_"
            reply = f"📚 *Справочная информация*\n\n_{text}_\n{proj_str}\n\n✅ Сохранено в REFERENCE\n\n_{result['пояснение']}_"
        elif result["результат"] in ("H3", "H4", "H5"):
            level = result["результат"]
            area = result.get("область", "")
            await _save_horizon_item(update, level, text, area=area)
            labels = {"H3": "🎯 Цель (1-2 года)", "H4": "🔭 Видение (3-5 лет)", "H5": "⭐ Миссия и принципы"}
            area_tag = f"\nОбласть: _{area}_" if area else ""
            view_cmd = "/vision" if level in ("H4", "H5") else "/horizons"
            reply = (
                f"{labels[level]}\n\n"
                f"_{text}_\n"
                f"{area_tag}\n"
                f"✅ Сохранено в Горизонты\n\n"
                f"_{result['пояснение']}_\n\n"
                f"Просмотр: {view_cmd}"
            )
        elif result["результат"] == "Trash":
            reply = f"🗑 *Можно удалить*\n\n_{text}_\n\n_{result['пояснение']}_"
        else:
            reply = f"✅ Обработано: {result['результат']}\n\n{result['пояснение']}"

        # Обновить статус в Inbox
        all_inbox = inbox_sheet.get_all_values()
        for i, row in enumerate(all_inbox):
            if row and len(row) > 2 and row[2] == text and row[4] == "Новый":
                inbox_sheet.update_cell(i + 1, 5, "Обработан")
                inbox_sheet.update_cell(i + 1, 6, result["результат"])
                break

        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🖼 Анализирую фото через AI...")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        image_data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

        message = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"type": "text", "text": EXTRACT_PROMPT}
                ]
            }]
        )

        extracted = message.content[0].text
        await update.message.reply_text(f"📋 *Извлечено из фото:*\n\n{extracted}", parse_mode="Markdown")

        await _save_extracted_to_inbox(update, extracted, "Фото")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка обработки фото: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if doc.mime_type != "application/pdf":
        await update.message.reply_text("⚠️ Поддерживаются только PDF файлы.")
        return

    await update.message.reply_text("📄 Читаю PDF через AI...")

    try:
        file = await context.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        pdf_data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

        message = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        }
                    },
                    {"type": "text", "text": EXTRACT_PROMPT}
                ]
            }]
        )

        extracted = message.content[0].text
        await update.message.reply_text(f"📋 *Извлечено из PDF:*\n\n{extracted}", parse_mode="Markdown")

        # Сохранить PDF в Google Drive
        await update.message.reply_text("☁️ Сохраняю PDF в Google Drive...")
        pdf_bytes = buf.getvalue()
        drive_link = upload_pdf_to_drive(pdf_bytes, doc.file_name)
        if drive_link:
            await update.message.reply_text(f"✅ PDF сохранён в Google Drive:\n{drive_link}")

        await _save_extracted_to_inbox(update, extracted, f"PDF: {doc.file_name}")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка обработки PDF: {e}")


async def _save_extracted_to_inbox(update: Update, extracted: str, source_label: str):
    """Разбить извлечённый текст на задачи и сохранить каждую в Inbox."""
    today = date.today().isoformat()
    inbox_sheet = get_sheet("inbox")

    # Разбиваем по строкам, ищем пункты списка
    lines = extracted.split("\n")
    tasks = []
    for line in lines:
        line = line.strip()
        # Убираем маркеры списков (-, •, *, 1., 2. и т.д.)
        if line and len(line) > 3:
            clean = line.lstrip("-•*0123456789.) ").strip()
            if clean and len(clean) > 3:
                tasks.append(clean)

    if not tasks:
        tasks = [extracted.strip()]

    count = 0
    for task in tasks:
        if len(task) > 5:
            inbox_sheet.append_row(
                ["", today, task, f"Telegram ({source_label})", "Новый", "", "", ""],
                value_input_option="USER_ENTERED"
            )
            count += 1

    await update.message.reply_text(
        f"✅ Добавлено в Inbox: {count} задач\n\n"
        f"Напиши боту *'обработать'* чтобы AI разобрал их по GTD.",
        parse_mode="Markdown"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Распознаю голосовое...")

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_memory(io.BytesIO())
            await file.download_to_drive(tmp.name)
            tmp_path = tmp.name

        result = whisper_model.transcribe(tmp_path, language="ru")
        text = result["text"].strip()
        os.unlink(tmp_path)

        if not text:
            await update.message.reply_text("❌ Не удалось распознать речь.")
            return

        await update.message.reply_text(f"📝 Распознано: _{text}_", parse_mode="Markdown")
        await update.message.reply_text("⏳ Обрабатываю через AI...")

        # Добавить в Inbox и обработать
        today = date.today().isoformat()
        inbox_sheet = get_sheet("inbox")
        inbox_sheet.append_row(
            ["", today, text, "Голосовое", "Новый", "", "", ""],
            value_input_option="USER_ENTERED"
        )

        result_ai = process_item(text)

        if result_ai["результат"] == "Project":
            all_inbox = inbox_sheet.get_all_values()
            for i, row in enumerate(all_inbox):
                if row and len(row) > 2 and row[2] == text and row[4] == "Новый":
                    inbox_sheet.update_cell(i + 1, 5, "Обработан")
                    inbox_sheet.update_cell(i + 1, 6, "Project→NP")
                    break
            await np_start_from_ai(update, context, text, result_ai)
            return

        if result_ai["результат"] == "Action":
            actions_sheet = get_sheet("next_actions")
            action_row = [
                "", result_ai["действие"], "", result_ai["область"],
                result_ai["контекст"], "Next", result_ai["приоритет"],
                result_ai.get("энергия", ""), result_ai["время"], result_ai.get("срок", ""), "", "", "",
                f"Голосовое: {text}", today, ""
            ]
            actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")

        reply = (
            f"✅ *Обработано*\n\n"
            f"🎤 _{text}_\n\n"
            f"*Результат:* {result_ai['результат']}\n"
            f"*Действие:* {result_ai['действие']}\n"
            f"*Контекст:* {result_ai['контекст']}\n"
            f"*Приоритет:* {result_ai['приоритет']}\n"
            f"*Время:* {result_ai['время']} мин"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def _check_tickler(context) -> str:
    """Проверить SomedayDate — вернуть текст если есть напоминания на сегодня."""
    today_str = date.today().isoformat()
    try:
        sheet = get_sheet("someday")
        rows = sheet.get_all_records()
        due_today = [r for r in rows if r.get("Пересмотреть", "") == today_str and r.get("Статус", "") != "Активирован"]
        if not due_today:
            return ""
        text = "🗂 *НАПОМИНАНИЯ НА СЕГОДНЯ (Tickler):*\n"
        for r in due_today[:5]:
            name = r.get("Идея / Проект") or r.get("Идея/Проект") or r.get("Идея") or "—"
            text += f"  • {name}\n"
        text += "_Активировать: /activate_\n\n"
        return text
    except Exception:
        return ""


async def morning_digest(context):
    """Утренний дайджест — топ задач на день."""
    if not TELEGRAM_CHAT_ID:
        return

    try:
        actions = read_next_actions()
        inbox = read_inbox()

        next_up = [a for a in actions if a.get("Статус") == "Next"]
        new_inbox = len([r for r in inbox if r.get("Статус") == "Новый"])

        priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
        next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))
        top5 = next_up[:5]

        today_date = date.today()
        text = f"☀️ *Доброе утро! {today_date.strftime('%d.%m.%Y')}*\n\n"

        if new_inbox > 0:
            text += f"📥 В Inbox {new_inbox} необработанных — напиши *обработать*\n\n"

        # Просроченные задачи
        overdue = []
        for a in next_up:
            dl = a.get("Срок", "")
            if dl:
                try:
                    if date.fromisoformat(dl) < today_date:
                        overdue.append(a)
                except ValueError:
                    pass

        if overdue:
            text += f"🚨 *ПРОСРОЧЕНО ({len(overdue)}):*\n"
            for a in overdue[:3]:
                dl = date.fromisoformat(a["Срок"])
                days = (today_date - dl).days
                text += f"  • {a.get('Действие', '—')} _{days}д назад_\n"
            text += "\n"

        if top5:
            text += "⚡ *Топ задач на сегодня:*\n\n"
            for i, a in enumerate(top5, 1):
                p = a.get("Приоритет", "")
                icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
                action = a.get("Действие", "—")
                context_tag = a.get("Контекст", "")
                dl = a.get("Срок", "")
                deadline_str = ""
                if dl:
                    try:
                        diff = (date.fromisoformat(dl) - today_date).days
                        if diff == 0:
                            deadline_str = " ⚠️ _сегодня!_"
                        elif diff == 1:
                            deadline_str = " ⏰ _завтра_"
                    except ValueError:
                        pass
                text += f"{i}. {icon} {action}{deadline_str}\n   {context_tag}\n\n"
        else:
            text += "✅ Нет активных задач — добавь новые в Inbox!\n"

        if cal_configured():
            try:
                cal_text = format_calendar_summary(next_up, days=3)
                if "Дедлайны" in cal_text or "Google Calendar" in cal_text:
                    lines = cal_text.split("\n\n", 1)
                    if len(lines) > 1:
                        text += f"\n{lines[1][:400]}"
            except Exception:
                pass

        tickler_text = await _check_tickler(context)
        if tickler_text:
            text += f"\n{tickler_text}"

        text += "_Хорошего дня!_ 💪"

        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка утреннего дайджеста: {e}")


async def show_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список Waiting For: кто, что, сколько дней ждём."""
    actions = read_next_actions()
    waiting = [a for a in actions if a.get("Статус") == "Waiting"]

    if not waiting:
        await update.message.reply_text(
            "⏳ Список ожидания пуст.\n\n"
            "Добавь: _жду от Иван: решение по договору_",
            parse_mode="Markdown"
        )
        return

    today_date = date.today()
    text = f"⏳ *WAITING FOR* ({len(waiting)})\n\n"

    for i, a in enumerate(waiting, 1):
        action = a.get("Действие", "—")
        from_who = a.get("Ждём от", "")
        since = a.get("Ждём с", "")
        days_str = ""
        urgent = ""
        if since:
            try:
                since_date = date.fromisoformat(since)
                days = (today_date - since_date).days
                days_str = f" · {days}д"
                if days >= 7:
                    urgent = " 🚨"
                elif days >= 3:
                    urgent = " ⚠️"
            except ValueError:
                pass

        from_str = f"от *{from_who}*" if from_who else ""
        text += f"{i}. {from_str}{urgent}\n   {action}{days_str}\n\n"

    text += "_Добавить: жду от [имя]: [что]_\n"
    text += "_Закрыть: получил [номер]_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить задачу в Waiting For через текст 'жду от Иван: решение по договору'."""
    text = update.message.text.strip()

    # Парсим формат "жду от [кто]: [что]"
    import re
    match = re.match(r"^жду\s+от\s+(.+?):\s*(.+)$", text, re.IGNORECASE)
    if not match:
        await update.message.reply_text(
            "⚠️ Формат: _жду от [имя]: [что ждём]_\n\nПример: жду от Алмаз: подписанный договор",
            parse_mode="Markdown"
        )
        return

    from_who = match.group(1).strip()
    what = match.group(2).strip()
    today = date.today().isoformat()

    try:
        sheet = get_sheet("next_actions")
        # Колонки: ID, Действие, Проект, Область, Контекст, Статус, Приоритет,
        #          Энергия, Время, Срок, Кому делегировано, Ждём от, Ждём с, Заметки, Создано, Выполнено
        row = [
            "", what, "", "", "@Waiting", "Waiting", "Средний",
            "", "", "", "", from_who, today, "", today, ""
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")

        await update.message.reply_text(
            f"⏳ *Добавлено в Waiting For*\n\n"
            f"Ждём от: *{from_who}*\n"
            f"Что: _{what}_\n"
            f"С: {today}\n\n"
            f"Напомню если не получишь через 3+ дня.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def activate_someday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активировать идею из Someday: /activate N или 'активировать N'."""
    try:
        someday_sheet = get_sheet("someday")
        all_records = someday_sheet.get_all_records()
        active = [
            (i + 2, r) for i, r in enumerate(all_records)
            if r.get("Статус") not in ("Активирован", "Удалён")
            and str(r.get("Идея / Проект", "")).strip()
            and not str(r.get("Идея / Проект", "")).startswith("#")
        ]
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка чтения Someday: {e}")
        return

    if not active:
        await update.message.reply_text("💭 Someday пуст или все идеи уже активированы.")
        return

    # Без номера — показать список
    args = context.args if context.args else []
    if not args:
        text = "💡 *АКТИВИРОВАТЬ ИДЕЮ*\n\nНапиши _активировать [номер]_:\n\n"
        for i, (_, r) in enumerate(active, 1):
            idea = r.get("Идея / Проект", "—")[:55]
            area = r.get("Область (Area)", "")
            area_str = f" · {area}" if area else ""
            text += f"{i}. _{idea}_{area_str}\n"
        text += "\n_Или напиши: активировать 2_"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    try:
        idx = int(args[0]) - 1
    except ValueError:
        await update.message.reply_text("⚠️ Укажи номер: _активировать 1_", parse_mode="Markdown")
        return

    if idx < 0 or idx >= len(active):
        await update.message.reply_text(f"⚠️ Номер от 1 до {len(active)}.")
        return

    row_num, item = active[idx]
    idea = item.get("Идея / Проект", "—")
    description = item.get("Описание", "")
    area = item.get("Область (Area)", "")

    await update.message.reply_text(f"⏳ Активирую «{idea}» через AI...")

    today = date.today().isoformat()
    content = f"{idea}. {description}".strip(". ")

    try:
        # AI определяет: это проект или одна задача?
        ai_msg = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content":
                f"GTD активация Someday. Идея: '{content}'. Область: {area}. "
                f"Определи: это проект (несколько шагов) или одно действие? "
                f"Ответь:\nТИП: Project или Action\n"
                f"ИТОГ: желаемый результат (если Project, глагол совершенного вида)\n"
                f"ДЕЙСТВИЕ: первое конкретное следующее действие\n"
                f"КОНТЕКСТ: @Phone/@Computer/@Office/@Home/@Anywhere\n"
                f"ПРИОРИТЕТ: Высокий/Средний/Низкий\n"
                f"ЭНЕРГИЯ: Высокая/Средняя/Низкая"}]
        )
        ai_text = ai_msg.content[0].text
        lines = {l.split(":")[0].strip(): ":".join(l.split(":")[1:]).strip()
                 for l in ai_text.strip().split("\n") if ":" in l}

        item_type = lines.get("ТИП", "Project")
        outcome = lines.get("ИТОГ", idea)
        action = lines.get("ДЕЙСТВИЕ", f"Начать работу над: {idea}")
        context_tag = lines.get("КОНТЕКСТ", "@Anywhere")
        priority = lines.get("ПРИОРИТЕТ", "Средний")
        energy = lines.get("ЭНЕРГИЯ", "")

        someday_sheet = get_sheet("someday")
        all_values = someday_sheet.get_all_values()
        headers = all_values[0] if all_values else []
        status_col = headers.index("Статус") + 1 if "Статус" in headers else 6

        if "Project" in item_type:
            _clear_np(context)
            context.user_data["np"] = {
                "name": idea[:100],
                "why": "",
                "outcome": outcome,
                "subtasks": "",
                "action": action,
                "context": context_tag,
                "area": area,
                "priority": priority,
                "energy": energy,
                "brainstorm": "",
                "source": f"Someday: {idea}",
            }
            context.user_data["np_state"] = NP_WHY
            someday_sheet.update_cell(row_num, status_col, "Активирован")
            await update.message.reply_text(
                f"🚀 *Активировано из Someday*\n\n"
                f"💭 _{idea}_\n\n"
                f"Запускаю Natural Planning...\n\n"
                f"1️⃣ *Зачем этот проект?* (цель, намерение)",
                parse_mode="Markdown",
                reply_markup=_np_keyboard(),
            )
            return

        # Action — без Natural Planning
        actions_sheet = get_sheet("next_actions")
        action_row = [
            "", action, "", area,
            context_tag, "Next", priority,
            energy, "", "", "", "", "",
            f"Из Someday: {idea}", today, ""
        ]
        actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")

        try:
            someday_sheet.update_cell(row_num, status_col, "Активирован")
        except Exception:
            pass

        reply = (
            f"🚀 *Задача создана!*\n\n"
            f"💭 Идея: _{idea}_\n"
            f"\n⚡ Первое действие:\n"
            f"_{action}_ ({context_tag})\n\n"
            f"✅ Статус в Someday обновлён → Активирован"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка AI: {e}")


async def close_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрыть Waiting-задачу: /received <номер> или 'получил <номер>'."""
    actions = read_next_actions()
    waiting = [a for a in actions if a.get("Статус") == "Waiting"]

    if not waiting:
        await update.message.reply_text("⏳ Список ожидания пуст.")
        return

    # Если номер не передан — показать список
    args = context.args if context.args else []
    if not args:
        text = "✅ *ПОЛУЧИЛ — какой пункт закрыть?*\n\nНапиши _получил [номер]_:\n\n"
        today_date = date.today()
        for i, a in enumerate(waiting, 1):
            from_who = a.get("Ждём от", "?")
            action = a.get("Действие", "—")
            since = a.get("Ждём с", "")
            days = 0
            if since:
                try:
                    days = (today_date - date.fromisoformat(since)).days
                except ValueError:
                    pass
            text += f"{i}. от *{from_who}* ({days}д): _{action}_\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    try:
        idx = int(args[0]) - 1
    except ValueError:
        await update.message.reply_text("⚠️ Укажи номер: _получил 1_", parse_mode="Markdown")
        return

    if idx < 0 or idx >= len(waiting):
        await update.message.reply_text(f"⚠️ Номер от 1 до {len(waiting)}.")
        return

    task = waiting[idx]
    action_name = task.get("Действие", "—")
    from_who = task.get("Ждём от", "?")

    try:
        sheet = get_sheet("next_actions")
        all_rows = sheet.get_all_values()
        headers = all_rows[0] if all_rows else []
        action_col = headers.index("Действие") + 1 if "Действие" in headers else 2
        status_col = headers.index("Статус") + 1 if "Статус" in headers else 6
        done_col = headers.index("Выполнено") + 1 if "Выполнено" in headers else None

        for i, row in enumerate(all_rows[1:], 2):
            if len(row) >= action_col and row[action_col - 1] == action_name:
                if len(row) >= status_col and row[status_col - 1] == "Waiting":
                    sheet.update_cell(i, status_col, "Done")
                    if done_col:
                        sheet.update_cell(i, done_col, date.today().isoformat())
                    break

        await update.message.reply_text(
            f"✅ *Получено от {from_who}!*\n\n_{action_name}_\n\n"
            f"Задача закрыта. Нужно ли создать следующее действие?\n"
            f"Просто напиши боту что делать дальше.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def evening_reminder(context):
    """Вечернее напоминание — задачи на завтра и просроченные."""
    if not TELEGRAM_CHAT_ID:
        return

    try:
        actions = read_next_actions()
        next_up = [a for a in actions if a.get("Статус") == "Next"]
        today_date = date.today()
        tomorrow = today_date + timedelta(days=1)

        due_tomorrow = []
        overdue = []
        for a in next_up:
            dl = a.get("Срок", "")
            if not dl:
                continue
            try:
                dl_date = date.fromisoformat(dl)
                if dl_date == tomorrow:
                    due_tomorrow.append(a)
                elif dl_date < today_date:
                    overdue.append(a)
            except ValueError:
                pass

        # Waiting For — ждём > 3 дней (из всех задач, не только Next)
        followup_needed = []
        for a in actions:
            if a.get("Статус") != "Waiting":
                continue
            since = a.get("Ждём с", "")
            if since:
                try:
                    days = (today_date - date.fromisoformat(since)).days
                    if days >= 3:
                        followup_needed.append((a, days))
                except ValueError:
                    pass

        if not due_tomorrow and not overdue and not followup_needed:
            return  # Нечего напоминать — не беспокоим

        text = f"🌆 *Вечерний обзор — {today_date.strftime('%d.%m.%Y')}*\n\n"

        if overdue:
            text += f"🚨 *Просрочено ({len(overdue)}):*\n"
            for a in overdue[:3]:
                dl_date = date.fromisoformat(a["Срок"])
                days = (today_date - dl_date).days
                text += f"  • {a.get('Действие', '—')} _{days}д_\n"
            text += "\n"

        if due_tomorrow:
            text += f"⏰ *Срок завтра ({len(due_tomorrow)}):*\n"
            for a in due_tomorrow:
                p = a.get("Приоритет", "")
                icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
                text += f"  {icon} {a.get('Действие', '—')}\n"
            text += "\n"

        if followup_needed:
            text += f"⏳ *Follow-up нужен ({len(followup_needed)}):*\n"
            for a, days in followup_needed[:5]:
                from_who = a.get("Ждём от", "?")
                action = a.get("Действие", "—")
                icon = "🚨" if days >= 7 else "⚠️"
                text += f"  {icon} от *{from_who}* ({days}д): _{action}_\n"
            text += "\n"

        # По воскресеньям — добавляем итог недели из архива
        if today_date.weekday() == 6:  # 6 = воскресенье
            try:
                arch_sheet = get_sheet("archive")
                arch_rows = arch_sheet.get_all_records()
                week_ago = (today_date - timedelta(days=7)).isoformat()
                done_this_week = [
                    r for r in arch_rows
                    if str(r.get("Дата завершения", "")) >= week_ago
                ]
                if done_this_week:
                    text += f"\n🏆 *Завершено за неделю ({len(done_this_week)}):*\n"
                    for r in done_this_week[:5]:
                        text += f"  ✅ {r.get('Название проекта', '—')}\n"
                    text += "\n"
            except Exception:
                pass

        text += "_Запланируй время на эти задачи!_"

        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Ошибка вечернего напоминания: {e}")


# ─── БИЗНЕС: УЗАКОНЕНИЕ ───────────────────────────────────────────────────────

BIZ_OWNER = os.getenv("BIZ_OWNER_NAME", "Дидар")


async def show_biz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/biz — список объектов или /biz UZ-2026-02 — шаги по объекту."""
    # Если передан ID объекта — показываем шаги
    if context.args:
        obj_id = context.args[0].upper()
        await _show_biz_steps(update, obj_id)
        return

    try:
        objects = read_biz_objects()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    if not objects:
        await update.message.reply_text("🏗 Нет активных объектов.")
        return

    text = f"🏗 *ДЕЙСТВУЮЩИЕ ОБЪЕКТЫ* ({len(objects)})\n\n"
    for obj in objects:
        num = obj.get("№", "")
        arch = obj.get("Архивный номер", "")
        client_name = obj.get("ФИО клиента ", obj.get("ФИО клиента", "—")).strip()
        address = obj.get("адрес", "")[:40]
        obj_type = obj.get("тип обекта", "")
        service = obj.get("тип услуги", "")

        text += f"*{arch}* — {client_name}\n"
        text += f"  📍 {address}\n"
        if obj_type or service:
            text += f"  🏠 {obj_type} · {service}\n"
        text += "\n"

    text += "_Детали: /biz UZ-2026-02_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def _show_biz_steps(update: Update, obj_id: str):
    """Показать шаги по конкретному объекту."""
    try:
        address, steps = read_biz_steps(obj_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Объект {obj_id} не найден: {e}")
        return

    if not steps:
        await update.message.reply_text(f"📋 Объект {obj_id}: шаги не заполнены.")
        return

    text = f"📋 *{obj_id}*\n_{address[:60]}_\n\n"
    my_steps = []

    for step in steps:
        num = step.get("№", "")
        name = step.get("Наименование работ ", step.get("Наименование работ", "—")).strip()
        executor = step.get("Исполнитель ", step.get("Исполнитель", "")).strip()
        gov = step.get("Гос орган", "").strip()

        is_mine = BIZ_OWNER.lower() in executor.lower()
        icon = "👤" if is_mine else "👥"
        exec_str = f"*{executor}*" if is_mine else executor

        text += f"{icon} {num}. {name}\n"
        if executor:
            text += f"   Исполнитель: {exec_str}"
        if gov:
            text += f" · {gov}"
        text += "\n"

        if is_mine:
            my_steps.append(name)

    if my_steps:
        text += f"\n👤 *Твои шаги ({len(my_steps)}):*\n"
        for s in my_steps:
            text += f"  • _{s}_\n"
        text += f"\n_Синхронизировать в GTD: /biz\\_sync {obj_id}_"

    await update.message.reply_text(text, parse_mode="Markdown")


async def biz_sync_to_gtd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/biz_sync UZ-2026-02 — добавить мои шаги как GTD задачи."""
    if not context.args:
        # Показать все объекты для выбора
        names = read_biz_object_names()
        text = "🔄 *СИНХРОНИЗАЦИЯ С GTD*\n\nВыбери объект:\n\n"
        for n in names:
            text += f"  `/biz_sync {n}`\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    obj_id = context.args[0].upper()
    try:
        address, steps = read_biz_steps(obj_id)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return

    my_steps = [
        s for s in steps
        if BIZ_OWNER.lower() in s.get("Исполнитель ", s.get("Исполнитель", "")).lower()
    ]

    if not my_steps:
        await update.message.reply_text(f"✅ В {obj_id} нет шагов на тебе.")
        return

    today = date.today().isoformat()
    actions_sheet = get_sheet("next_actions")
    added = 0

    for step in my_steps:
        name = step.get("Наименование работ ", step.get("Наименование работ", "—")).strip()
        gov = step.get("Гос орган", "").strip()
        where = step.get("Куда сдавать ", step.get("Куда сдавать", "")).strip()

        # Определяем контекст
        if "звон" in name.lower() or "позвон" in name.lower():
            ctx = "@Phone"
        elif "egov" in where.lower() or "сайт" in where.lower() or "онлайн" in where.lower():
            ctx = "@Computer"
        else:
            ctx = "@Office"

        action_row = [
            "", name, "", "Real Estate",
            ctx, "Next", "Высокий",
            "Средняя", "", "", "", "", "",
            f"Бизнес: {obj_id} · {gov}", today, ""
        ]
        actions_sheet.append_row(action_row, value_input_option="USER_ENTERED")
        added += 1

    await update.message.reply_text(
        f"✅ *Синхронизировано: {obj_id}*\n\n"
        f"Добавлено в GTD Next Actions: *{added} задач*\n\n"
        + "\n".join(f"  • _{s.get('Наименование работ ', s.get('Наименование работ', '—')).strip()}_"
                    for s in my_steps),
        parse_mode="Markdown"
    )


# ─── ГОРИЗОНТЫ H3-H5 ──────────────────────────────────────────────────────────

HORIZON_INFO = {
    "H3": ("🎯", "Цели (1-2 года)", "Что конкретно хочешь достичь в ближайшие 1-2 года?"),
    "H4": ("🔭", "Видение (3-5 лет)", "Как выглядит успех через 3-5 лет? Идеальный сценарий?"),
    "H5": ("⭐", "Миссия и принципы", "Зачем всё это? Каковы твои основные принципы и предназначение?"),
}


def _read_horizons() -> list[dict]:
    try:
        sheet = get_sheet("horizons")
        return sheet.get_all_records()
    except Exception:
        return []


async def show_horizons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать полную пирамиду горизонтов H0-H5."""
    horizon_items = _read_horizons()
    active_h = [h for h in horizon_items if h.get("Статус") != "Архив" and h.get("Описание", "").strip()]

    # H0 — Действия сейчас
    try:
        actions = read_next_actions()
        next_count = len([a for a in actions if a.get("Статус") == "Next"])
        waiting_count = len([a for a in actions if a.get("Статус") == "Waiting"])
        h0_str = f"{next_count} задач в Next Actions · {waiting_count} в Waiting"
    except Exception:
        h0_str = "недоступно"

    # H1 — Проекты
    try:
        projects = read_projects()
        active_projects = [p for p in projects if p.get("Статус") == "Активен"]
        h1_str = f"{len(active_projects)} активных проектов"
    except Exception:
        h1_str = "недоступно"

    # H2 — Зоны ответственности из AREAS
    try:
        areas_sheet = get_sheet("areas")
        areas_rows = areas_sheet.get_all_records()
        areas = [a for a in areas_rows if a.get("Название", "").strip()
                 and not str(a.get("Название", "")).startswith("#")]
    except Exception:
        areas = []

    text = "🏔 *ГОРИЗОНТЫ ПЛАНИРОВАНИЯ*\n_(от основания к вершине)_\n\n"

    # H0
    text += f"📅 *H0 — Календарь/Действия*\n  {h0_str}\n\n"

    # H1
    text += f"📋 *H1 — Проекты*\n  {h1_str}\n"
    for p in active_projects[:3]:
        text += f"  • _{p.get('Название проекта', '—')[:50]}_\n"
    if len(active_projects) > 3:
        text += f"  _...и ещё {len(active_projects) - 3}_\n"
    text += "\n"

    # H2
    text += f"🏢 *H2 — Зоны ответственности* ({len(areas)})\n"
    for a in areas[:6]:
        name = a.get("Название", "—")
        desc = a.get("Описание", "")
        text += f"  • *{name}*" + (f" — _{desc[:40]}_" if desc else "") + "\n"
    if len(areas) > 6:
        text += f"  _...и ещё {len(areas) - 6}_\n"
    text += "\n"

    # H3-H5
    for level, (icon, title, _) in HORIZON_INFO.items():
        level_items = [h for h in active_h if str(h.get("Горизонт", "")).strip() == level]
        text += f"{icon} *{level} — {title}*\n"
        if level_items:
            for h in level_items:
                text += f"  • _{h.get('Описание', '—')}_\n"
        else:
            text += "  _не заполнено_\n"
        text += "\n"

    text += (
        "➕ *Добавить H3-H5* (напиши):\n"
        "`h3: открыть офис в Алматы`\n"
        "`h4: стать лидером рынка в ЦА`\n"
        "`h5: создавать системы, которые работают без меня`\n\n"
        "🔭 *Видение и Миссия подробно:* /vision\n"
        "📆 *Ежеквартальный обзор H3:* /qreview\n"
        "🏢 *Обзор зон H2:* /h2review\n"
        "🧠 *Очистка сознания:* /mindsweep"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def _save_horizon_item(update: Update, level: str, description: str, area: str = ""):
    """Сохранить элемент горизонта в таблицу и ответить пользователю."""
    level = level.upper()
    if level not in HORIZON_INFO:
        await update.message.reply_text("⚠️ Уровень должен быть H3, H4 или H5")
        return
    icon, title, _ = HORIZON_INFO[level]
    today = date.today().isoformat()
    try:
        sheet = get_sheet("horizons")
        all_rows = sheet.get_all_values()
        # Миграция: добавить заголовок Область если его нет
        if all_rows and len(all_rows[0]) < 7:
            sheet.update_cell(1, 6, "Область")
            sheet.update_cell(1, 7, "Заметки")
        new_id = f"{level}-{len(all_rows):03d}"
        sheet.append_row([new_id, level, description, today, "Активен", area, ""],
                         value_input_option="USER_ENTERED")
        area_tag = f" · _{area}_" if area else ""
        await update.message.reply_text(
            f"{icon} *Добавлено в {level} — {title}*{area_tag}\n\n_{description}_",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def add_horizon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить элемент горизонта. /h3, /h4, /h5 [текст]."""
    cmd = update.message.text.split()[0].lstrip("/").upper()
    level = cmd  # H3, H4, H5

    if level not in HORIZON_INFO:
        await update.message.reply_text("⚠️ Используй /h3, /h4 или /h5")
        return

    if not context.args:
        icon, title, prompt = HORIZON_INFO[level]
        await update.message.reply_text(
            f"{icon} *{level} — {title}*\n\n{prompt}\n\n"
            f"Пример: `/{level.lower()} твой текст здесь`\n"
            f"Или: `{level.lower()}: твой текст`",
            parse_mode="Markdown"
        )
        return

    await _save_horizon_item(update, level, " ".join(context.args))


# ─── H4 ВИДЕНИЕ И H5 МИССИЯ — РАСШИРЕННЫЕ ВОПРОСЫ ────────────────────────────

H4_QUESTIONS = [
    "Как будет выглядеть идеальный результат через 3-5 лет?",
    "Как ты хочешь, чтобы выглядела твоя компания/карьера/жизнь?",
    "Что ты хочешь создать? Что будет достижением?",
    "Какую роль ты хочешь играть — в бизнесе, семье, сообществе?",
]

H5_QUESTIONS = [
    "Зачем ты делаешь то, что делаешь? В чём высший смысл?",
    "Какие принципы и ценности определяют твои решения?",
    "Что для тебя важнее всего в жизни?",
    "Как ты хочешь, чтобы тебя помнили?",
]


def _group_horizons_by_area(items: list[dict]) -> dict:
    """Группировать элементы горизонта по области жизни."""
    grouped: dict[str, list] = {}
    for h in items:
        area = h.get("Область", "").strip() or "Общее"
        grouped.setdefault(area, []).append(h)
    return grouped


async def show_vision_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать и редактировать H4/H5 с вопросами из GTD, сгруппировано по областям."""
    horizon_items = _read_horizons()
    h4_items = [h for h in horizon_items if h.get("Горизонт") == "H4" and h.get("Статус") != "Архив" and h.get("Описание", "").strip()]
    h5_items = [h for h in horizon_items if h.get("Горизонт") == "H5" and h.get("Статус") != "Архив" and h.get("Описание", "").strip()]

    text = "🔭 *H4 — ВИДЕНИЕ (3-5 лет)*\n"
    text += "_Долгосрочные результаты, идеальные сценарии_\n\n"
    if h4_items:
        grouped = _group_horizons_by_area(h4_items)
        for area, items in grouped.items():
            if len(grouped) > 1:
                text += f"*{area}:*\n"
            for h in items:
                text += f"  • _{h.get('Описание', '—')}_\n"
            if len(grouped) > 1:
                text += "\n"
    else:
        text += "  _не заполнено_\n"
    text += "\n*Вопросы для рефлексии:*\n"
    for q in H4_QUESTIONS[:2]:
        text += f"  · {q}\n"
    text += "\n➕ Добавить: `h4: твоё видение`\n\n"

    text += "─" * 30 + "\n\n"

    text += "⭐ *H5 — МИССИЯ И ПРИНЦИПЫ*\n"
    text += "_Высшее намерение, ценности, предназначение_\n\n"
    if h5_items:
        for h in h5_items:
            text += f"  • _{h.get('Описание', '—')}_\n"
    else:
        text += "  _не заполнено_\n"
    text += "\n*Вопросы для рефлексии:*\n"
    for q in H5_QUESTIONS[:2]:
        text += f"  · {q}\n"
    text += "\n➕ Добавить: `h5: твоя миссия`\n\n"
    text += "─" * 30 + "\n\n"
    text += (
        "_По GTD: H5 определяет H4, H4 определяет H3-цели,\n"
        "цели порождают H1-проекты, проекты — H0-действия._\n\n"
        "📆 Обзор H3/квартал: /qreview"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_vision_guided(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/h4 без аргументов — показывает вопросы-помощники."""
    cmd = update.message.text.split()[0].lstrip("/").upper()
    if context.args:
        await _save_horizon_item(update, cmd, " ".join(context.args))
        return
    if cmd == "H4":
        text = (
            "🔭 *H4 — ВИДЕНИЕ (3-5 лет)*\n\n"
            "Ответь на один из вопросов или напиши своё:\n\n"
        )
        for i, q in enumerate(H4_QUESTIONS, 1):
            text += f"{i}. _{q}_\n"
        text += "\n*Формат:* `h4: как выглядит успех через 5 лет`"
    else:
        text = (
            "⭐ *H5 — МИССИЯ И ПРИНЦИПЫ*\n\n"
            "Ответь на один из вопросов или напиши своё:\n\n"
        )
        for i, q in enumerate(H5_QUESTIONS, 1):
            text += f"{i}. _{q}_\n"
        text += "\n*Формат:* `h5: зачем я это делаю`"
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── @AGENDAS — ПОВЕСТКИ ВСТРЕЧ ────────────────────────────────────────────────

async def show_agendas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все повестки встреч, сгруппированные по людям."""
    actions = read_next_actions()
    agenda_items = [
        a for a in actions
        if a.get("Контекст", "").strip().lower() in ("@agendas", "@agenda", "@повестка")
        and a.get("Статус") not in ("Done", "Выполнено")
    ]

    if not agenda_items:
        await update.message.reply_text(
            "👥 *ПОВЕСТКИ ВСТРЕЧ*\n\nСписок пуст.\n\n"
            "Добавь: `повестка: Человек: что обсудить`\n"
            "Или: /agenda Человек: вопрос",
            parse_mode="Markdown",
        )
        return

    by_person: dict[str, list] = {}
    for a in agenda_items:
        person = (a.get("Проект") or "Без имени").strip()
        by_person.setdefault(person, []).append(a)

    text = "👥 *ПОВЕСТКИ ВСТРЕЧ*\n\n"
    for person, items in sorted(by_person.items()):
        text += f"*{person}* ({len(items)}):\n"
        for a in items:
            action = a.get("Действие", "—")
            text += f"  · _{action[:70]}_\n"
        text += "\n"

    text += "_Добавить: `повестка: Имя: вопрос`_"
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_agenda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить вопрос к повестке встречи. /agenda Имя: вопрос"""
    raw = " ".join(context.args) if context.args else ""
    if not raw:
        await update.message.reply_text(
            "👥 *Повестка встречи*\n\n"
            "Формат: `/agenda Имя: что обсудить`\n\n"
            "Пример:\n`/agenda Алия: бюджет Q3`\n`/agenda Марат: статус проекта`",
            parse_mode="Markdown",
        )
        return

    if ":" in raw:
        person, _, topic = raw.partition(":")
        person = person.strip()
        topic = topic.strip()
    else:
        person = "Без имени"
        topic = raw.strip()

    if not topic:
        await update.message.reply_text("⚠️ Укажи что обсудить: `/agenda Имя: вопрос`", parse_mode="Markdown")
        return

    today = date.today().isoformat()
    actions_sheet = get_sheet("next_actions")
    row = [
        "", topic[:200], person[:100], "",
        "@Agendas", "Next", "Средний",
        "", "", "", "", "", "",
        f"Повестка встречи с {person}", today, "",
    ]
    try:
        actions_sheet.append_row(row, value_input_option="USER_ENTERED")
        await update.message.reply_text(
            f"👥 *Добавлено в повестку*\n\n"
            f"Человек: *{person}*\n"
            f"Вопрос: _{topic}_\n\n"
            f"Просмотр: /agendas",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


# ─── H2 ОБЗОР ЗОН ОТВЕТСТВЕННОСТИ ─────────────────────────────────────────────

async def h2_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обзор зон ответственности H2: все ли зоны покрыты проектами?"""
    try:
        areas_sheet = get_sheet("areas")
        areas_rows = areas_sheet.get_all_records()
        areas = [a for a in areas_rows if a.get("Название", "").strip() and not str(a.get("Название", "")).startswith("#")]
    except Exception:
        areas = []

    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]

    area_project_map: dict[str, int] = {}
    for p in active:
        area = (p.get("Область") or p.get("Область (Area)") or "").strip()
        if area:
            area_project_map[area] = area_project_map.get(area, 0) + 1

    text = "🏢 *ОБЗОР H2 — ЗОНЫ ОТВЕТСТВЕННОСТИ*\n\n"
    text += "_H2 — важные сферы, которые надо поддерживать на должном уровне._\n"
    text += "_Обзор: каждые 2-3 месяца._\n\n"

    no_projects = []
    for a in areas:
        name = a.get("Название", "—")
        desc = a.get("Описание", "")
        count = area_project_map.get(name, 0)
        icon = "✅" if count > 0 else "⚠️"
        text += f"{icon} *{name}*"
        if desc:
            text += f" — _{desc[:40]}_"
        text += f"\n   Проектов: {count}\n"
        if count == 0:
            no_projects.append(name)

    if not areas:
        text += "_(зоны не заданы — добавь в таблицу AREAS)_\n"

    text += "\n"
    if no_projects:
        text += f"⚠️ *Зоны без проектов ({len(no_projects)}):*\n"
        for n in no_projects:
            text += f"  • {n}\n"
        text += "\n_Создай проект или Next Action для каждой пустой зоны._\n"
    else:
        text += "✅ Все зоны покрыты проектами.\n"

    text += (
        "\n❓ *Вопросы для рефлексии:*\n"
        "• Все роли выполняются на должном уровне?\n"
        "• Нет ли зон, которые давно не получали внимания?\n"
        "• Нужно ли добавить новую зону?\n\n"
        "📌 Редактировать зоны: таблица Google Sheets → лист AREAS"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def scheduled_h2_review(context):
    """Ежемесячное напоминание об обзоре H2 — 1-е число каждого месяца."""
    if not TELEGRAM_CHAT_ID:
        return
    today = date.today()
    if today.day != 1:
        return
    try:
        areas_sheet = get_sheet("areas")
        areas_rows = areas_sheet.get_all_records()
        areas_count = len([a for a in areas_rows if a.get("Название", "").strip() and not str(a.get("Название", "")).startswith("#")])
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                f"🏢 *Время обзора H2 — Зоны ответственности!*\n\n"
                f"Сегодня 1-е число — хорошее время проверить все {areas_count} зон.\n\n"
                f"Запусти: /h2review"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Scheduled H2 error: {e}")


# ─── MIND SWEEP — ОЧИСТКА СОЗНАНИЯ ────────────────────────────────────────────

def _parse_ms_items(text: str) -> list[str]:
    """Разбить текст Mind Sweep на элементы: по Enter, запятой, точке с запятой."""
    import re as _re
    # Сначала делим по Enter
    lines = text.split("\n")
    items = []
    for line in lines:
        # Внутри строки делим по запятой или точке с запятой (если нет Enter)
        parts = _re.split(r"[,;،،]", line)
        for part in parts:
            part = part.strip().lstrip("•-·0123456789.) ").strip()
            if part and len(part) > 2:
                items.append(part)
    return items


_MS_WORK_CATEGORIES = [
    "📋 Проекты начатые, но не завершённые",
    "🚀 Проекты, которые нужно начать",
    "🤝 Обязательства/обещания другим",
    "📞 Звонки, письма, коммуникация",
    "💰 Финансы, бюджет, платежи",
    "👥 Персонал, команда, делегирование",
    "📈 Маркетинг, продажи, клиенты",
    "⚙️ Системы, ИТ, автоматизация",
    "📅 Предстоящие встречи, мероприятия",
    "⏳ Лист ожидания — что жду от других",
    "📚 Обучение, развитие, что хочу изучить",
]

_MS_PERSONAL_CATEGORIES = [
    "👨‍👩‍👧 Семья, близкие, обязательства",
    "🏠 Дом, ремонт, хозяйство",
    "💊 Здоровье, врачи, спорт",
    "💳 Личные финансы, налоги, страховка",
    "🚗 Транспорт, машина, поездки",
    "📖 Личное развитие, книги, курсы",
    "🎯 Личные цели и мечты (Someday)",
    "🛒 Покупки, дела в городе",
    "🌐 Сообщество, социальные обязательства",
]


def _ms_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(_MS_NEXT), KeyboardButton(_MS_STOP)]],
        resize_keyboard=True,
    )


async def mindsweep_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск Mind Sweep: /mindsweep"""
    context.user_data["ms"] = {"items": [], "phase": "work"}
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("🧹 Начать"), KeyboardButton(_MS_STOP)]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "🧠 *ОЧИСТКА СОЗНАНИЯ (Mind Sweep)*\n\n"
        "Выброси всё из головы в Inbox.\n"
        "Для каждой категории напиши всё, что приходит в голову.\n\n"
        "Фаза 1: Профессиональное\n"
        "Фаза 2: Личное\n\n"
        "_Цель: ничего не держать в голове._\n\n"
        "Начнём?",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return MS_WORK


async def ms_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фаза 1: профессиональные категории."""
    text = update.message.text
    if text == _MS_STOP:
        return await ms_finish(update, context)

    ms = context.user_data.setdefault("ms", {"items": [], "phase": "work"})

    if text not in ("🧹 Начать", _MS_NEXT):
        ms["items"].extend(_parse_ms_items(text))

    msg = "📋 *ФАЗА 1 / 2 — ПРОФЕССИОНАЛЬНОЕ*\n\n"
    msg += "Для каждой категории ниже напиши всё что есть:\n\n"
    for cat in _MS_WORK_CATEGORIES:
        msg += f"  {cat}\n"
    msg += (
        "\n💡 Напиши всё подряд — одно сообщение или несколько.\n"
        "Когда закончишь профессиональное — нажми *➡️ Далее*."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_ms_keyboard())
    return MS_PERSONAL


async def ms_personal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фаза 2: личные категории."""
    text = update.message.text
    if text == _MS_STOP:
        return await ms_finish(update, context)

    ms = context.user_data.get("ms", {"items": []})

    if text != _MS_NEXT:
        ms["items"].extend(_parse_ms_items(text))

    msg = "🏠 *ФАЗА 2 / 2 — ЛИЧНОЕ*\n\n"
    msg += "Теперь личное:\n\n"
    for cat in _MS_PERSONAL_CATEGORIES:
        msg += f"  {cat}\n"
    msg += (
        "\n💡 Напиши всё что приходит в голову.\n"
        "Когда закончишь — нажми *✅ Готово*."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_ms_keyboard())
    return MS_DONE


async def ms_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финал: сохранить все собранные элементы в Inbox."""
    text = update.message.text
    ms = context.user_data.get("ms", {"items": []})

    if text not in (_MS_STOP, _MS_NEXT, "✅ Готово"):
        ms["items"].extend(_parse_ms_items(text))

    items = [i for i in ms.get("items", []) if i.strip()]

    if items:
        today = date.today().isoformat()
        inbox_sheet = get_sheet("inbox")
        for item in items:
            inbox_sheet.append_row(
                ["", today, item[:300], "Mind Sweep", "Новый", "", "", ""],
                value_input_option="USER_ENTERED",
            )

    context.user_data.pop("ms", None)
    await update.message.reply_text(
        f"✅ *Mind Sweep завершён!*\n\n"
        f"Добавлено в Inbox: *{len(items)}* элементов\n\n"
        f"Теперь напиши *обработать* — AI разберёт всё по GTD-системе.\n\n"
        f"_Голова свободна!_ 🧠",
        parse_mode="Markdown",
        reply_markup=_main_keyboard(),
    )
    return ConversationHandler.END


async def ms_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ms", None)
    await update.message.reply_text("⛔ Mind Sweep прерван.", reply_markup=_main_keyboard())
    return ConversationHandler.END


# ─── GOOGLE CALENDAR ───────────────────────────────────────────────────────────

async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать дедлайны GTD и события Google Calendar."""
    try:
        actions = read_next_actions()
        text = format_calendar_summary(actions, days=7)
        if not cal_configured():
            text += f"\n\n{cal_setup()}"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def calendar_setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статус всех подключённых календарей. /calendar_setup"""
    if not cal_configured():
        await update.message.reply_text(cal_setup(), parse_mode="Markdown")
        return

    await update.message.reply_text("⏳ Проверяю доступ к календарям...")
    try:
        calendars = list_calendars_status()
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    text = "📅 *НАСТРОЙКА GOOGLE CALENDAR*\n\n"
    ok_count = sum(1 for c in calendars if c["ok"])
    text += f"Подключено: {ok_count}/{len(calendars)}\n\n"

    for c in calendars:
        icon = "✅" if c["ok"] else "❌"
        role_icon = "✏️" if c["role"] == "writer" else "👁"
        text += f"{icon} {role_icon} *{c['name']}*\n"
        text += f"   `{c['id']}`\n"
        if not c["ok"]:
            text += f"   ⚠️ _{c.get('error', 'нет доступа')}_\n"
        text += "\n"

    text += (
        "─────────────────\n"
        f"✏️ = запись (GTD-дедлайны)\n"
        f"👁 = только чтение (встречи)\n\n"
        f"*Service account:*\n`{CAL_SERVICE_ACCOUNT}`\n\n"
        "Чтобы добавить календарь — поделись с service account\n"
        "и добавь ID в `.env` → `READ_CALENDAR_IDS`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cal_sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Синхронизировать дедлайны GTD → Google Calendar."""
    if not cal_configured():
        await update.message.reply_text(cal_setup(), parse_mode="Markdown")
        return
    await update.message.reply_text("⏳ Синхронизирую дедлайны с Google Calendar...")
    try:
        actions = read_next_actions()
        stats = sync_gtd_deadlines(actions)
        if stats.get("error"):
            await update.message.reply_text(cal_setup(), parse_mode="Markdown")
            return
        await update.message.reply_text(
            f"✅ *Синхронизация завершена*\n\n"
            f"Создано: {stats.get('created', 0)}\n"
            f"Обновлено: {stats.get('updated', 0)}\n"
            f"Пропущено: {stats.get('skipped', 0)}\n\n"
            f"_Дедлайны из Next Actions → all-day события в Google Calendar_",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка синхронизации: {e}\n\n"
            f"Проверь CALENDAR_ID и доступ service account к календарю.",
        )


def _sync_one_deadline(action: str, deadline: str, project: str = "",
                       context_tag: str = "", priority: str = ""):
    """Тихая синхронизация одного дедлайна (если календарь настроен)."""
    if not cal_configured() or not deadline:
        return
    try:
        upsert_deadline_event(
            action, deadline, project=project,
            context=context_tag, priority=priority,
        )
    except Exception as e:
        logging.error(f"Calendar sync error: {e}")


# ─── ЕЖЕКВАРТАЛЬНЫЙ ОБЗОР H3 ──────────────────────────────────────────────────

def _current_quarter() -> str:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return f"Q{q} {today.year}"


def _qh3_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(_QH3_NEXT), KeyboardButton(_QH3_STOP)]],
        resize_keyboard=True,
    )


async def qh3_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск ежеквартального обзора H3: /qreview"""
    context.user_data["qh3"] = {
        "quarter": _current_quarter(),
        "notes": [],
    }
    horizon_items = _read_horizons()
    h3_items = [
        h for h in horizon_items
        if h.get("Горизонт") == "H3" and h.get("Статус") != "Архив"
        and h.get("Описание", "").strip()
    ]

    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 Начать"), KeyboardButton(_QH3_STOP)]],
        resize_keyboard=True,
    )
    msg = (
        f"🎯 *ЕЖЕКВАРТАЛЬНЫЙ ОБЗОР H3*\n"
        f"_{_current_quarter()}_\n\n"
        "4 шага рефлексии по целям 1-2 года:\n"
        "1️⃣ Цели H3 — прогресс за квартал\n"
        "2️⃣ Проекты — движут ли к H3?\n"
        "3️⃣ Someday — что активировать?\n"
        "4️⃣ Приоритеты — топ-3 на квартал\n\n"
        "Займёт ~15 минут. Начнём?"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    return QH3_GOALS


async def qh3_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: цели H3."""
    if update.message.text == _QH3_STOP:
        return await qh3_cancel(update, context)

    if update.message.text not in ("🚀 Начать", _QH3_NEXT):
        context.user_data["qh3"]["notes"].append(f"H3: {update.message.text}")

    horizon_items = _read_horizons()
    h3_items = [
        h for h in horizon_items
        if h.get("Горизонт") == "H3" and h.get("Статус") != "Архив"
        and h.get("Описание", "").strip()
    ]
    context.user_data["qh3"]["h3_count"] = len(h3_items)

    msg = f"🎯 *ШАГ 1 / 4 — ЦЕЛИ H3*\n\n"
    if h3_items:
        msg += f"Активных целей: *{len(h3_items)}*\n\n"
        for h in h3_items:
            msg += f"  • _{h.get('Описание', '—')}_\n"
        msg += "\n"
    else:
        msg += "⚠️ H3 не заполнен!\n"
        msg += "Добавь: `h3: твоя цель на 1-2 года`\n\n"

    msg += (
        "❓ *Вопросы:*\n"
        "• Какой прогресс по каждой цели за квартал?\n"
        "• Что изменилось в приоритетах?\n"
        "• Нужны ли новые цели H3?\n\n"
        "Напиши заметки или нажми *➡️ Далее*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_qh3_keyboard())
    return QH3_PROJECTS


async def qh3_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: проекты vs H3."""
    if update.message.text == _QH3_STOP:
        return await qh3_cancel(update, context)

    if update.message.text != _QH3_NEXT:
        context.user_data["qh3"]["notes"].append(f"Проекты: {update.message.text}")

    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]
    context.user_data["qh3"]["projects_count"] = len(active)

    msg = f"🗂 *ШАГ 2 / 4 — ПРОЕКТЫ И H3*\n\nАктивных проектов: *{len(active)}*\n\n"
    for p in active[:8]:
        name = p.get("Название проекта", "—")
        outcome = p.get("Желаемый результат", "")
        msg += f"  • *{name}*"
        if outcome:
            msg += f" → _{outcome[:50]}_"
        msg += "\n"
    if len(active) > 8:
        msg += f"  _...и ещё {len(active) - 8}_\n"
    msg += (
        "\n❓ *Вопросы:*\n"
        "• Какие проекты двигают к H3?\n"
        "• Что завершить / заморозить / начать?\n"
        "• Есть ли проекты без связи с целями?\n\n"
        "Напиши заметки или *➡️ Далее*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_qh3_keyboard())
    return QH3_SOMEDAY


async def qh3_someday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Someday vs H3."""
    if update.message.text == _QH3_STOP:
        return await qh3_cancel(update, context)

    if update.message.text != _QH3_NEXT:
        context.user_data["qh3"]["notes"].append(f"Someday: {update.message.text}")

    try:
        someday_sheet = get_sheet("someday")
        someday_items = someday_sheet.get_all_records()
        active_someday = [
            s for s in someday_items
            if s.get("Статус") not in ("Архив", "Выполнено", "Активирован")
        ]
    except Exception:
        active_someday = []

    context.user_data["qh3"]["someday_count"] = len(active_someday)

    msg = f"💭 *ШАГ 3 / 4 — SOMEDAY / H3*\n\n"
    if active_someday:
        msg += f"Отложенных идей: *{len(active_someday)}*\n\n"
        for s in active_someday[:6]:
            item = (s.get("Идея / Проект") or s.get("Название") or "").strip()
            if item:
                msg += f"  • _{item[:55]}_\n"
        msg += "\n"
    else:
        msg += "Список Someday пуст.\n\n"

    msg += (
        "❓ *Вопросы:*\n"
        "• Какие идеи пора активировать в этом квартале?\n"
        "• Что потеряло смысл — удалить?\n\n"
        "Напиши заметки или *➡️ Далее*"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_qh3_keyboard())
    return QH3_PRIORITIES


async def qh3_priorities(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: топ-3 приоритета на квартал."""
    if update.message.text == _QH3_STOP:
        return await qh3_cancel(update, context)

    if update.message.text == _QH3_NEXT and not context.user_data["qh3"].get("priorities"):
        await update.message.reply_text(
            "📝 Напиши *топ-3 приоритета* на этот квартал (списком или текстом):",
            parse_mode="Markdown",
            reply_markup=_qh3_keyboard(),
        )
        return QH3_PRIORITIES

    if update.message.text != _QH3_NEXT:
        context.user_data["qh3"]["priorities"] = update.message.text

    await update.message.reply_text("⏳ Генерирую AI-итог квартала...")
    return await qh3_finish(update, context)


async def qh3_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финал: AI-итог и сохранение."""
    qh3 = context.user_data.get("qh3", {})
    horizon_items = _read_horizons()
    h3_items = [h for h in horizon_items if h.get("Горизонт") == "H3" and h.get("Статус") != "Архив"]
    h3_text = "\n".join(f"- {h.get('Описание', '')}" for h in h3_items) or "не заполнено"

    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]
    proj_text = "\n".join(f"- {p.get('Название проекта', '')}" for p in active[:10])

    notes_text = "\n".join(qh3.get("notes", []))
    priorities = qh3.get("priorities", "не указаны")

    try:
        ai_msg = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            messages=[{"role": "user", "content":
                f"GTD ежеквартальный обзор H3 ({qh3.get('quarter', '')}).\n\n"
                f"ЦЕЛИ H3:\n{h3_text}\n\n"
                f"АКТИВНЫЕ ПРОЕКТЫ ({len(active)}):\n{proj_text}\n\n"
                f"ЗАМЕТКИ ПОЛЬЗОВАТЕЛЯ:\n{notes_text or 'нет'}\n\n"
                f"ПРИОРИТЕТЫ НА КВАРТАЛ:\n{priorities}\n\n"
                "Дай краткий итог (на русском):\n"
                "1. ПРОГРЕСС — оценка движения к H3 (2-3 предложения)\n"
                "2. ВЫРОВНЯТЬ — что не соответствует целям\n"
                "3. ТОП-3 ФОКУСА — конкретные рекомендации на квартал\n"
                "4. РЕШЕНИЕ — один стратегический совет"}],
        )
        ai_summary = ai_msg.content[0].text
    except Exception as e:
        ai_summary = f"(AI недоступен: {e})"

    try:
        review_sheet = get_sheet("quarterly")
        col_a = review_sheet.col_values(1)
        next_row = len(col_a) + 1
        row = [
            date.today().isoformat(),
            qh3.get("quarter", ""),
            h3_text[:500],
            proj_text[:500],
            priorities[:300],
            notes_text[:500],
            ai_summary[:2000],
        ]
        review_sheet.update(values=[row], range_name=f"A{next_row}:G{next_row}")
    except Exception as e:
        logging.error(f"Quarterly review save error: {e}")

    summary = (
        f"🏁 *ЕЖЕКВАРТАЛЬНЫЙ ОБЗОР H3 ЗАВЕРШЁН*\n"
        f"_{qh3.get('quarter', '')} · {date.today().strftime('%d.%m.%Y')}_\n\n"
        f"🎯 H3 целей: {qh3.get('h3_count', 0)}\n"
        f"🗂 Проектов: {qh3.get('projects_count', 0)}\n"
        f"💭 Someday: {qh3.get('someday_count', 0)}\n\n"
        f"🤖 *Итог квартала:*\n{ai_summary}\n\n"
        f"✅ _Сохранено в Google Sheets → QUARTERLY REVIEW_"
    )

    context.user_data.pop("qh3", None)
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=_main_keyboard())
    return ConversationHandler.END


async def qh3_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("qh3", None)
    await update.message.reply_text(
        "⛔ Ежеквартальный обзор прерван.",
        reply_markup=_main_keyboard(),
    )
    return ConversationHandler.END


async def scheduled_qh3_review(context):
    """Автоматический запуск в 1-й день квартала (янв, апр, июл, окт)."""
    if not TELEGRAM_CHAT_ID:
        return
    today = date.today()
    if today.month not in (1, 4, 7, 10) or today.day != 1:
        return
    try:
        horizon_items = _read_horizons()
        h3_count = len([
            h for h in horizon_items
            if h.get("Горизонт") == "H3" and h.get("Статус") != "Архив"
        ])
        projects = read_projects()
        active = len([p for p in projects if p.get("Статус") == "Активен"])

        text = (
            f"📆 *Начало {_current_quarter()}!*\n\n"
            f"Время для ежеквартального обзора H3.\n\n"
            f"🎯 H3 целей: {h3_count}\n"
            f"🗂 Активных проектов: {active}\n\n"
            f"Запусти: /qreview"
        )
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Scheduled QH3 error: {e}")


# ─── WEEKLY REVIEW ИНТЕРАКТИВНЫЙ ЧЕКЛИСТ ─────────────────────────────────────

_WR_NEXT = "➡️ Следующий шаг"
_WR_STOP = "⛔ Закончить обзор"


def _wr_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(_WR_NEXT), KeyboardButton(_WR_STOP)]],
        resize_keyboard=True
    )


def _main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📥 Добавить в Inbox"), KeyboardButton("⚡ Задачи")],
        [KeyboardButton("✅ Выполнено"), KeyboardButton("🗂 Проекты")],
        [KeyboardButton("📋 Новый проект"), KeyboardButton("⏳ Waiting")],
        [KeyboardButton("🏔 Горизонты"), KeyboardButton("👥 Повестки")],
        [KeyboardButton("🏗 Объекты"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("🔋 Высокая энергия"), KeyboardButton("😴 Низкая энергия")],
        [KeyboardButton("📱 @Phone"), KeyboardButton("💻 @Computer"), KeyboardButton("💬 @WhatsApp")],
        [KeyboardButton("🏢 @Office"), KeyboardButton("🏠 @Home"), KeyboardButton("🌍 @Anywhere")],
    ], resize_keyboard=True)


async def wr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск интерактивного Weekly Review."""
    context.user_data["wr"] = {"started": date.today().isoformat()}
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 Начать"), KeyboardButton(_WR_STOP)]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "📋 *WEEKLY REVIEW — 7 шагов GTD*\n\n"
        "1️⃣ Inbox → 0\n"
        "2️⃣ Прошедший календарь — что пропустил?\n"
        "3️⃣ Проекты — все имеют Next Action?\n"
        "4️⃣ Next Actions — просроченные и приоритеты\n"
        "5️⃣ Waiting For — нужен ли follow-up?\n"
        "6️⃣ Someday/Maybe — что активировать?\n"
        "7️⃣ Горизонты — цели, видение, миссия\n\n"
        "Займёт ~10 минут. Начнём?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WR_INBOX


async def wr_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Inbox."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    inbox = read_inbox()
    new_inbox = [r for r in inbox if r.get("Статус") == "Новый"]
    count = len(new_inbox)
    context.user_data["wr"]["inbox_count"] = count

    icon = "✅" if count == 0 else "⚠️"
    msg = f"{icon} *ШАГ 1 / 6 — INBOX*\n\n"
    if count == 0:
        msg += "Inbox пуст — отлично! 🎉\n"
    else:
        msg += f"Необработанных: *{count}*\n\n"
        for item in new_inbox[:5]:
            content = item.get("Содержимое", "") or item.get("Содержание", "") or "—"
            content = str(content).strip()
            if content.startswith("#") or not content:
                continue
            msg += f"  • _{content[:60]}_\n"
        msg += "\n💡 После обзора напиши *обработать* — AI разберёт всё\n"

    msg += "\n_Цель: Inbox = 0. Каждый элемент — выброшен или обработан._"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_PAST_CAL


async def wr_past_cal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: Прошедший календарь — показывает реальные события + просроченные дедлайны."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    note = update.message.text if update.message.text not in (_WR_NEXT, "🚀 Начать") else ""
    if note:
        context.user_data["wr"]["past_cal_note"] = note

    today_date = date.today()
    week_ago = today_date - timedelta(days=7)

    msg = (
        f"📅 *ШАГ 2 / 7 — ПРОШЕДШИЙ КАЛЕНДАРЬ*\n"
        f"_{week_ago.strftime('%d.%m')} – {today_date.strftime('%d.%m.%Y')}_\n\n"
    )

    # Просроченные дедлайны из Next Actions
    try:
        actions = read_next_actions()
        overdue = []
        for a in actions:
            if a.get("Статус") != "Next":
                continue
            dl = a.get("Срок", "").strip()
            if not dl:
                continue
            try:
                dl_date = date.fromisoformat(dl)
                if dl_date < today_date:
                    overdue.append((dl_date, a))
            except ValueError:
                pass
        overdue.sort(key=lambda x: x[0])
        if overdue:
            msg += f"🚨 *Просроченные дедлайны ({len(overdue)}):*\n"
            for dl_date, a in overdue[:7]:
                days_ago = (today_date - dl_date).days
                msg += f"  · {dl_date.strftime('%d.%m')} ({days_ago}д) — _{a.get('Действие', '—')[:50]}_\n"
            msg += "\n"
    except Exception:
        pass

    # События прошлой недели из Google Calendar
    if cal_configured():
        try:
            past = list_past_events(days=7)
            non_gtd = [e for e in past if not e["is_gtd"]]
            if non_gtd:
                msg += f"🗓 *События прошлой недели ({len(non_gtd)}):*\n"
                for e in non_gtd[:10]:
                    try:
                        d_fmt = date.fromisoformat(e["date"]).strftime("%d.%m (%a)")
                    except ValueError:
                        d_fmt = e["date"]
                    msg += f"  · *{d_fmt}* — {e['summary'][:55]}\n"
                msg += "\n"
            else:
                msg += "🗓 _Событий в Google Calendar за прошлую неделю нет._\n\n"
        except Exception as e:
            logging.error(f"wr_past_cal calendar error: {e}")
            msg += "⚠️ _Не удалось загрузить события Google Calendar._\n\n"
    else:
        msg += "_Google Calendar не настроен — проверяй вручную (/calendar)._\n\n"

    msg += (
        "❓ *Проверь по каждому событию:*\n"
        "• Вышли ли дела из встреч — занесены ли они в систему?\n"
        "• Обещания и договорённости — добавлены ли в Waiting?\n"
        "• Появились новые проекты или идеи — в Inbox?\n\n"
        "_Напиши инсайты или нажми ➡️ Далее._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_PROJECTS


async def wr_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Проекты."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]
    all_actions = read_next_actions()
    proj_actions_map = _get_projects_with_actions(active, all_actions)

    # Проекты без реальных Next Actions в листе
    no_na = [p for p in active if not proj_actions_map.get(p.get("Название проекта", ""))]
    no_outcome = [p for p in active if not p.get("Желаемый результат") and not p.get("Желаемый итог")]
    context.user_data["wr"]["projects_count"] = len(active)
    context.user_data["wr"]["projects_no_na"] = len(no_na)

    msg = f"🗂 *ШАГ 3 / 7 — ПРОЕКТЫ*\n\nАктивных: *{len(active)}*\n\n"

    if no_na:
        msg += f"⚠️ *ЗАСТРЯВШИЕ — нет Next Action ({len(no_na)}):*\n"
        for p in no_na[:5]:
            msg += f"  🔸 {p.get('Название проекта', '—')}\n"
        msg += "_Добавь следующее действие для каждого!_\n\n"
    else:
        msg += "✅ У всех проектов есть Next Action\n\n"

    if no_outcome:
        msg += f"🎯 *Нет желаемого результата ({len(no_outcome)}):*\n"
        for p in no_outcome[:3]:
            msg += f"  • {p.get('Название проекта', '—')}\n"
        msg += "\n"

    msg += "_По GTD: каждый проект = желаемый результат + следующее действие._"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_NEXT_ACTIONS


async def wr_next_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Next Actions."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]
    today_date = date.today()
    overdue, high_prio = [], []

    for a in next_up:
        if a.get("Приоритет") == "Высокий":
            high_prio.append(a)
        dl = a.get("Срок", "")
        if dl:
            try:
                if date.fromisoformat(dl) < today_date:
                    overdue.append(a)
            except ValueError:
                pass

    context.user_data["wr"]["next_count"] = len(next_up)
    context.user_data["wr"]["overdue_count"] = len(overdue)

    msg = (
        f"⚡ *ШАГ 4 / 7 — NEXT ACTIONS*\n\n"
        f"Всего задач: *{len(next_up)}*\n"
        f"Высокий приоритет: *{len(high_prio)}*\n\n"
    )

    if overdue:
        msg += f"🚨 *Просрочено ({len(overdue)}):*\n"
        for a in overdue[:5]:
            days = (today_date - date.fromisoformat(a["Срок"])).days
            msg += f"  • {a.get('Действие', '—')} _{days}д_\n"
        msg += "\n"

    if high_prio:
        msg += f"🔴 *Высокий приоритет:*\n"
        for a in high_prio[:5]:
            msg += f"  • {a.get('Действие', '—')}\n"
        msg += "\n"

    msg += "_Что можно удалить, делегировать или перенести в Someday?_"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_WAITING


async def wr_waiting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: Waiting For."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    actions = read_next_actions()
    waiting = [a for a in actions if a.get("Статус") == "Waiting"]
    today_date = date.today()
    context.user_data["wr"]["waiting_count"] = len(waiting)

    msg = f"⏳ *ШАГ 5 / 7 — WAITING FOR*\n\n"

    if not waiting:
        msg += "Список ожидания пуст.\n"
    else:
        msg += f"Ждём ответа: *{len(waiting)}*\n\n"
        stale_count = 0
        for a in waiting:
            from_who = a.get("Ждём от", "?")
            action = a.get("Действие", "—")
            since = a.get("Ждём с", "")
            days = 0
            if since:
                try:
                    days = (today_date - date.fromisoformat(since)).days
                except ValueError:
                    pass
            icon = "🚨" if days >= 7 else "⚠️" if days >= 3 else "·"
            if days >= 3:
                stale_count += 1
            msg += f"{icon} от *{from_who}* ({days}д): _{action}_\n"

        if stale_count:
            msg += f"\n💡 {stale_count} пунктов 3+ дней — стоит написать/позвонить\n"

    msg += "\n_Всё ли ещё актуально? Кого нужно поторопить?_"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_SOMEDAY


async def wr_someday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 5: Someday/Maybe."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    try:
        someday_sheet = get_sheet("someday")
        someday_items = someday_sheet.get_all_records()
        active_someday = [s for s in someday_items if s.get("Статус") not in ("Архив", "Выполнено")]
    except Exception:
        active_someday = []

    context.user_data["wr"]["someday_count"] = len(active_someday)

    msg = f"💭 *ШАГ 6 / 7 — SOMEDAY / MAYBE*\n\n"

    if not active_someday:
        msg += "Список пуст.\n"
    else:
        msg += f"Отложенных идей: *{len(active_someday)}*\n\n"
        for s in active_someday[:7]:
            item = (s.get("Идея / Проект") or s.get("Название") or "").strip()
            if not item or item == "—" or item.startswith("#"):
                continue
            msg += f"  • _{item[:55]}_\n"
        if len(active_someday) > 7:
            msg += f"  _...и ещё {len(active_someday) - 7}_\n"

    msg += "\n_Что-то пора активировать? Что потеряло смысл — удали._"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_HORIZONS


async def wr_horizons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 6: Горизонты — рефлексия."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    # Показываем текущие горизонты для контекста
    items = _read_horizons()
    active = [h for h in items if h.get("Статус") != "Архив" and h.get("Описание", "").strip()]

    msg = "🏔 *ШАГ 7 / 7 — ГОРИЗОНТЫ И ЦЕЛИ*\n\n"

    # H2 зоны ответственности
    try:
        areas_sheet = get_sheet("areas")
        areas_rows = areas_sheet.get_all_records()
        areas = [a.get("Название", "") for a in areas_rows
                 if a.get("Название", "").strip() and not str(a.get("Название", "")).startswith("#")]
        if areas:
            msg += f"🏢 *H2 — Зоны ответственности:*\n"
            msg += "  " + " · ".join(f"_{a}_" for a in areas[:6]) + "\n\n"
    except Exception:
        pass

    for level, (icon, title, _) in HORIZON_INFO.items():
        level_items = [h for h in active if str(h.get("Горизонт", "")).strip() == level]
        msg += f"{icon} *{level} — {title}:*\n"
        if level_items:
            for h in level_items[:2]:
                msg += f"  • _{h.get('Описание', '—')}_\n"
        else:
            msg += f"  _не заполнено_ — добавь: `{level.lower()}: текст`\n"
        msg += "\n"

    msg += (
        "❓ *Вопросы для рефлексии:*\n"
        "• H2: Все роли выполняются на должном уровне?\n"
        "• H3: Движешься ли к целям этой недели?\n"
        "• H4: Соответствуют ли проекты твоему Видению?\n"
        "• H5: Дела соответствуют твоей Миссии и ценностям?\n\n"
        "_Добавить видение: `h4: текст` · миссию: `h5: текст`_\n\n"
        "Напиши инсайты для AI-итога или нажми *➡️ Следующий шаг*."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=_wr_keyboard())
    return WR_DONE


async def wr_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финал: AI-итог + сохранение."""
    if update.message.text == _WR_STOP:
        return await wr_cancel(update, context)

    horizons_note = update.message.text if update.message.text != _WR_NEXT else ""
    wr = context.user_data.get("wr", {})

    await update.message.reply_text("⏳ Генерирую итог через AI...")

    inbox_count = wr.get("inbox_count", 0)
    projects_count = wr.get("projects_count", 0)
    no_na = wr.get("projects_no_na", 0)
    next_count = wr.get("next_count", 0)
    overdue_count = wr.get("overdue_count", 0)
    waiting_count = wr.get("waiting_count", 0)
    someday_count = wr.get("someday_count", 0)

    try:
        prompt = (
            f"GTD Weekly Review. Итоги: "
            f"Inbox необработанных: {inbox_count}, "
            f"Активных проектов: {projects_count} (без next action: {no_na}), "
            f"Next Actions: {next_count} (просрочено: {overdue_count}), "
            f"Waiting: {waiting_count}, Someday: {someday_count}. "
            f"Заметки: {horizons_note or 'нет'}. "
            f"Дай краткий итог и ТОП-3 фокуса на следующую неделю. "
            f"По-русски, вдохновляюще, 4-5 предложений."
        )
        ai_msg = ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        ai_summary = ai_msg.content[0].text
    except Exception as e:
        ai_summary = f"(AI недоступен: {e})"

    save_data = {
        "date": wr.get("started", date.today().isoformat()),
        "inbox_clear": inbox_count == 0,
        "projects_with_na": projects_count - no_na,
        "active_projects": projects_count,
        "waiting": waiting_count,
        "next_actions": next_count,
        "overdue": overdue_count,
        "ai_text": ai_summary,
    }
    _save_weekly_review(save_data)

    inbox_str = "✅" if inbox_count == 0 else f"⚠️ {inbox_count} необраб."
    na_str = "✅ все" if no_na == 0 else f"⚠️ {no_na} без NA"
    overdue_str = f" 🚨 {overdue_count} просроч." if overdue_count else ""

    summary = (
        f"🏁 *WEEKLY REVIEW ЗАВЕРШЁН*\n"
        f"_{date.today().strftime('%d.%m.%Y')}_\n\n"
        f"📥 Inbox: {inbox_str}\n"
        f"🗂 Проекты: {projects_count} ({na_str})\n"
        f"⚡ Next Actions: {next_count}{overdue_str}\n"
        f"⏳ Waiting: {waiting_count}\n"
        f"💭 Someday: {someday_count}\n\n"
        f"🤖 *Итог недели:*\n{ai_summary}\n\n"
        f"✅ _Сохранено в Google Sheets_"
    )

    context.user_data.pop("wr", None)
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=_main_keyboard())
    return ConversationHandler.END


async def cleartest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cleartest — очистить все тестовые данные (все листы кроме AREAS и HORIZONS)."""
    TO_CLEAR = ["inbox", "next_actions", "projects", "someday", "reference", "review", "quarterly"]

    await update.message.reply_text("🗑 Очищаю все тестовые данные...")

    results = []
    for sheet_key in TO_CLEAR:
        try:
            sheet = get_sheet(sheet_key)
            rows = sheet.get_all_values()
            count = len(rows) - 1  # без заголовка
            if count > 0:
                header = rows[0] if rows else []
                sheet.clear()
                if header:
                    sheet.append_row(header, value_input_option="USER_ENTERED")
                results.append(f"✅ {sheet_key.upper()}: удалено {count} строк")
            else:
                results.append(f"⬜ {sheet_key.upper()}: уже пуст")
        except Exception as e:
            results.append(f"❌ {sheet_key.upper()}: ошибка — {str(e)[:40]}")

    # WAITING FOR — в таблице Next Actions со статусом Waiting, уже очищено выше
    # HORIZONS и AREAS — не трогаем (реальные данные)

    summary = "🗑 Очистка завершена\n\n" + "\n".join(results)
    summary += "\n\nHORIZONS и AREAS — не тронуты (реальные данные)"
    await update.message.reply_text(summary, reply_markup=_main_keyboard())


async def wr_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена Weekly Review."""
    context.user_data.pop("wr", None)
    await update.message.reply_text(
        "⛔ Weekly Review прерван.",
        reply_markup=_main_keyboard()
    )
    return ConversationHandler.END


# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────

def main():
    print("🤖 GTD Telegram Bot запущен...")
    print(f"   Бот: @GTD_DIDA_BOT")
    print("   Нажми Ctrl+C чтобы остановить\n")

    app = Application.builder().token(TOKEN).build()

    # Weekly Review — ConversationHandler (должен быть ПЕРВЫМ)
    wr_handler = ConversationHandler(
        entry_points=[
            CommandHandler("review", wr_start),
        ],
        states={
            WR_INBOX:        [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_inbox)],
            WR_PAST_CAL:     [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_past_cal)],
            WR_PROJECTS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_projects)],
            WR_NEXT_ACTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_next_actions)],
            WR_WAITING:      [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_waiting)],
            WR_SOMEDAY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_someday)],
            WR_HORIZONS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_horizons)],
            WR_DONE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, wr_done)],
        },
        fallbacks=[
            CommandHandler("cancel", wr_cancel),
            MessageHandler(filters.Regex(f"^{re.escape(_WR_STOP)}$"), wr_cancel),
        ],
        allow_reentry=True,
    )
    app.add_handler(wr_handler)

    # Ежеквартальный обзор H3
    qh3_handler = ConversationHandler(
        entry_points=[CommandHandler("qreview", qh3_start)],
        states={
            QH3_GOALS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, qh3_goals)],
            QH3_PROJECTS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, qh3_projects)],
            QH3_SOMEDAY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, qh3_someday)],
            QH3_PRIORITIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, qh3_priorities)],
        },
        fallbacks=[
            CommandHandler("cancel", qh3_cancel),
            MessageHandler(filters.Regex(f"^{re.escape(_QH3_STOP)}$"), qh3_cancel),
        ],
        allow_reentry=True,
    )
    app.add_handler(qh3_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", show_help))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("digest", digest_now))
    app.add_handler(CommandHandler("now", now_command))
    app.add_handler(CommandHandler("repeat", set_recurring))
    app.add_handler(CommandHandler("tasks", show_tasks))
    app.add_handler(CommandHandler("projects", show_projects))
    app.add_handler(CommandHandler("project", project_command))
    app.add_handler(CommandHandler("cancel", np_cancel_command))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("waiting", show_waiting))
    app.add_handler(CommandHandler("received", close_waiting))
    app.add_handler(CommandHandler("activate", activate_someday))
    app.add_handler(CommandHandler("someday", activate_someday))
    app.add_handler(CommandHandler("inbox", show_inbox))
    app.add_handler(CommandHandler("horizons", show_horizons))
    app.add_handler(CommandHandler("calendar", show_calendar))
    app.add_handler(CommandHandler("cal_sync", cal_sync_command))
    app.add_handler(CommandHandler("calendar_setup", calendar_setup_command))
    app.add_handler(CommandHandler("biz", show_biz))
    app.add_handler(CommandHandler("biz_sync", biz_sync_to_gtd))
    # Mind Sweep
    ms_handler = ConversationHandler(
        entry_points=[CommandHandler("mindsweep", mindsweep_start)],
        states={
            MS_WORK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ms_work)],
            MS_PERSONAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ms_personal)],
            MS_DONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ms_finish)],
        },
        fallbacks=[
            CommandHandler("cancel", ms_cancel),
            MessageHandler(filters.Regex(f"^{re.escape(_MS_STOP)}$"), ms_finish),
        ],
        allow_reentry=True,
    )
    app.add_handler(ms_handler)

    app.add_handler(CommandHandler("h3", add_horizon))
    app.add_handler(CommandHandler("h4", add_vision_guided))
    app.add_handler(CommandHandler("h5", add_vision_guided))
    app.add_handler(CommandHandler("vision", show_vision_mission))
    app.add_handler(CommandHandler("h2review", h2_review))
    app.add_handler(CommandHandler("agendas", show_agendas))
    app.add_handler(CommandHandler("agenda", add_agenda))
    app.add_handler(CommandHandler("ref", add_reference))
    app.add_handler(CommandHandler("close", close_project))
    app.add_handler(CommandHandler("archive", show_archive))
    app.add_handler(CommandHandler("cleartest", cleartest_command))

    # ── Business Core handlers (Фаза 4) ─────────────────────
    try:
        from business_core.telegram_handlers import register_business_handlers
        register_business_handlers(app)
    except Exception as _bc_err:
        print(f"   ⚠️  Business Core handlers не загружены: {_bc_err}")
    # ────────────────────────────────────────────────────────

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Утренний дайджест в 9:00 по Алматы
    job_queue = app.job_queue
    job_queue.run_daily(
        morning_digest,
        time=time(hour=5, minute=0, tzinfo=TIMEZONE)
    )

    # Вечернее напоминание в 21:00 по Алматы
    job_queue.run_daily(
        evening_reminder,
        time=time(hour=21, minute=0, tzinfo=TIMEZONE)
    )

    # Автоматический Weekly Review каждое воскресенье в 19:00 по Алматы
    job_queue.run_daily(
        scheduled_weekly_review,
        time=time(hour=19, minute=0, tzinfo=TIMEZONE),
        days=(6,)  # 6 = воскресенье
    )

    # Напоминание об ежеквартальном обзоре H3 — 1-й день квартала в 10:00
    job_queue.run_daily(
        scheduled_qh3_review,
        time=time(hour=10, minute=0, tzinfo=TIMEZONE),
    )

    # Напоминание об обзоре H2 — 1-е число каждого месяца в 10:30
    job_queue.run_daily(
        scheduled_h2_review,
        time=time(hour=10, minute=30, tzinfo=TIMEZONE),
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
