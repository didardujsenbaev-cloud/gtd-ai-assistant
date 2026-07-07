"""
AI-обработка Inbox по методологии GTD.
Запуск: python3 inbox_processor.py
"""

import os
import anthropic
from datetime import date
from dotenv import load_dotenv
from sheets import get_sheet, read_inbox
from project_planner import save_project

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Ты GTD-ассистент. Обработай элемент из Inbox по методологии GTD Дэвида Аллена.

ПРАВИЛО 2 МИНУТ: если действие займёт менее 2 минут — отметь РЕЗУЛЬТАТ как "2min" (сделать немедленно, не добавлять в систему).

REFERENCE: если текст начинается с "Ref:", "Контакт:", "Сохранить:", "Справка:" — это ВСЕГДА Reference.
Также Reference: номера телефонов с именем, адреса, реквизиты, пароли, ссылки для сохранения.

Для каждого элемента определи:
1. РЕЗУЛЬТАТ — одно из:
   - 2min (займёт < 2 минут — сделай сразу)
   - Action (одно следующее действие > 2 минут, выполняю сам)
   - Waiting (делегировано другому человеку или ожидаю ответа/результата от кого-то: "попросить Асель", "ждать от Сарсена", "напомнить Бауыржану")
   - Project (требует нескольких шагов для достижения результата)
   - Someday (когда-нибудь/может быть, не срочно)
   - SomedayDate (хочу сделать в конкретный день/период в будущем, но не сейчас: "в августе", "после отпуска", "в следующем квартале")
   - Reference (справочная информация, контакты, адреса — действий не требует)
   - Trash (не нужно, можно удалить)
   - H3 (цель на 1-2 года: "хочу открыть офис", "план на год", "цель квартала")
   - H4 (видение на 3-5 лет: "хочу стать лидером рынка", "идеальный сценарий бизнеса", "как выглядит успех через 5 лет")
   - H5 (миссия/принципы: "моя миссия", "мои ценности", "зачем я это делаю", "мои принципы")
2. СЛЕДУЮЩЕЕ ДЕЙСТВИЕ — конкретный физический шаг (если Action, Project или 2min)
3. КОНТЕКСТ — где выполняется: @Phone, @Computer, @Email, @WhatsApp, @Office, @Almaty, @Astana, @Shymkent, @Finance, @Legal, @Government, @Contractors, @Team
4. ОБЛАСТЬ — одна из: Business, Finance, Investments, Family, Health, Learning, Coaching, Real Estate, Visas, Legalization, Marketing, Sales, Operations, IT, Automation, Knowledge Base
5. ПРИОРИТЕТ — Высокий, Средний, Низкий
6. ВРЕМЯ — сколько минут займёт следующее действие (реально, в минутах)
7. СРОК — дата дедлайна в формате YYYY-MM-DD, если упомянут срок/дедлайн/дата ("до пятницы", "до 10-го", "к среде", "до конца недели" и т.п.). Текущая дата: 2026-07-07. Используй 2026 год. Если срок не указан — оставь пустым.
7a. КОМУ — только если РЕЗУЛЬТАТ = Waiting. Имя человека или организации которой делегировано/от кого ждёшь.
8. ИТОГ ПРОЕКТА — только если РЕЗУЛЬТАТ = Project. Одно предложение: как выглядит ситуация, когда проект успешно завершён? Начни с глагола совершенного вида: "Получен...", "Подписан...", "Запущен...", "Найден..." и т.п.
9. ПОЧЕМУ — только если РЕЗУЛЬТАТ = Project. Зачем это важно? Какова основная причина/намерение? (1 предложение — модель естественного планирования GTD, шаг 1)
10. ПОДЗАДАЧИ — только если РЕЗУЛЬТАТ = Project. 2-3 ключевых подэтапа проекта через точку с запятой. Например: "Собрать документы; Подать в орган X; Получить акт"
9. ЭНЕРГИЯ — уровень физической/ментальной энергии для выполнения действия: Высокая (требует концентрации, творчества, сложного мышления), Средняя (стандартная работа), Низкая (рутина, механические действия, звонки по готовому скрипту).

Отвечай кратко и чётко. Формат:
РЕЗУЛЬТАТ: ...
ДЕЙСТВИЕ: ...
КОНТЕКСТ: ...
ОБЛАСТЬ: ...
ПРИОРИТЕТ: ...
ВРЕМЯ: ... мин
СРОК: YYYY-MM-DD или пусто
КОМУ: имя человека (только для Waiting, иначе пусто)
ИТОГ ПРОЕКТА: ... (только для Project, иначе пусто)
ПОЧЕМУ: ... (только для Project, иначе пусто)
ПОДЗАДАЧИ: шаг1; шаг2; шаг3 (только для Project, иначе пусто)
ЭНЕРГИЯ: Высокая / Средняя / Низкая
ПРОЕКТ: название существующего проекта если действие явно относится к нему, иначе пусто
ПОЯСНЕНИЕ: одно предложение почему так"""


def process_item(content: str, active_projects: list[str] | None = None) -> dict:
    """Отправить элемент Inbox в Claude и получить обработку."""
    today_str = date.today().isoformat()
    system = SYSTEM_PROMPT.replace(
        "Текущая дата: 2026-07-07. Используй 2026 год.",
        f"Текущая дата: {today_str}. Используй этот год и месяц при расчёте дат."
    )

    projects_hint = ""
    if active_projects:
        projects_list = "\n".join(f"  - {p}" for p in active_projects[:20])
        projects_hint = f"\n\nАктивные проекты пользователя (для поля ПРОЕКТ):\n{projects_list}"

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=system,
        messages=[
            {"role": "user", "content": f"Обработай этот элемент Inbox:{projects_hint}\n\n{content}"}
        ]
    )

    response = message.content[0].text
    return parse_response(response)


def parse_response(text: str) -> dict:
    """Распарсить ответ Claude в словарь."""
    result = {
        "результат": "",
        "действие": "",
        "контекст": "",
        "область": "",
        "приоритет": "",
        "время": "",
        "срок": "",
        "кому": "",
        "проект": "",
        "итог_проекта": "",
        "почему": "",
        "подзадачи": "",
        "энергия": "",
        "пояснение": "",
        "raw": text
    }

    import re
    for line in text.strip().split("\n"):
        if line.startswith("РЕЗУЛЬТАТ:"):
            result["результат"] = line.replace("РЕЗУЛЬТАТ:", "").strip()
        elif line.startswith("ДЕЙСТВИЕ:"):
            result["действие"] = line.replace("ДЕЙСТВИЕ:", "").strip()
        elif line.startswith("КОНТЕКСТ:"):
            result["контекст"] = line.replace("КОНТЕКСТ:", "").strip()
        elif line.startswith("ОБЛАСТЬ:"):
            result["область"] = line.replace("ОБЛАСТЬ:", "").strip()
        elif line.startswith("ПРИОРИТЕТ:"):
            result["приоритет"] = line.replace("ПРИОРИТЕТ:", "").strip()
        elif line.startswith("ВРЕМЯ:"):
            result["время"] = line.replace("ВРЕМЯ:", "").strip().replace(" мин", "")
        elif line.startswith("СРОК:"):
            val = line.replace("СРОК:", "").strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                result["срок"] = val
        elif line.startswith("КОМУ:"):
            result["кому"] = line.replace("КОМУ:", "").strip()
        elif line.startswith("ПРОЕКТ:"):
            result["проект"] = line.replace("ПРОЕКТ:", "").strip()
        elif line.startswith("ИТОГ ПРОЕКТА:"):
            result["итог_проекта"] = line.replace("ИТОГ ПРОЕКТА:", "").strip()
        elif line.startswith("ПОЧЕМУ:"):
            result["почему"] = line.replace("ПОЧЕМУ:", "").strip()
        elif line.startswith("ПОДЗАДАЧИ:"):
            result["подзадачи"] = line.replace("ПОДЗАДАЧИ:", "").strip()
        elif line.startswith("ЭНЕРГИЯ:"):
            val = line.replace("ЭНЕРГИЯ:", "").strip()
            if val in ("Высокая", "Средняя", "Низкая"):
                result["энергия"] = val
        elif line.startswith("ПОЯСНЕНИЕ:"):
            result["пояснение"] = line.replace("ПОЯСНЕНИЕ:", "").strip()

    return result


def process_inbox():
    """Прочитать Inbox, обработать новые элементы через AI."""
    print("📥 Читаем Inbox...\n")
    rows = read_inbox()

    new_items = [r for r in rows if r.get("Статус") == "Новый" and r.get("Содержимое")]

    if not new_items:
        print("✅ Нет новых элементов в Inbox.")
        return

    print(f"Найдено новых элементов: {len(new_items)}\n")
    print("─" * 60)

    sheet_actions = get_sheet("next_actions")
    sheet_inbox = get_sheet("inbox")
    all_inbox = sheet_inbox.get_all_values()

    # Загрузить активные проекты для передачи в AI
    try:
        from sheets import read_projects
        active_proj_names = [
            p.get("Название проекта", "") for p in read_projects()
            if p.get("Статус") == "Активен" and p.get("Название проекта")
        ]
    except Exception:
        active_proj_names = []

    for item in new_items:
        content = item.get("Содержимое", "")
        print(f"\n🔍 Элемент: {content}")
        print("   Обрабатываю...")

        result = process_item(content, active_projects=active_proj_names)

        print(f"   → Результат:  {result['результат']}")
        print(f"   → Действие:   {result['действие']}")
        print(f"   → Контекст:   {result['контекст']}")
        print(f"   → Область:    {result['область']}")
        print(f"   → Приоритет:  {result['приоритет']}")
        print(f"   → Время:      {result['время']} мин")
        print(f"   → Пояснение:  {result['пояснение']}")

        # Правило 2 минут
        if result["результат"] == "2min":
            print("   ⚡ ПРАВИЛО 2 МИНУТ — сделай прямо сейчас!")
            print(f"   → {result['действие']}")

        # Action — добавить в NEXT ACTIONS
        elif result["результат"] == "Action":
            today = date.today().isoformat()
            proj_link = result.get("проект", "")
            action_row = [
                "", result["действие"], proj_link, result["область"],
                result["контекст"], "Next", result["приоритет"],
                result["энергия"], result["время"], result["срок"], "", "", "",
                f"Из Inbox: {content}", today, ""
            ]
            sheet_actions.append_row(action_row, value_input_option="USER_ENTERED")
            deadline_str = f" (срок: {result['срок']})" if result["срок"] else ""
            proj_str = f" [проект: {proj_link}]" if proj_link else ""
            print(f"   ✅ Добавлено в NEXT ACTIONS{deadline_str}{proj_str}")

        # Waiting — делегировано, ждём от кого-то
        elif result["результат"] == "Waiting":
            sheet_actions = get_sheet("next_actions")
            today = date.today().isoformat()
            whom = result.get("кому", "")
            action_text = result["действие"] or content[:200]
            action_row = [
                "", action_text, "", result["область"],
                result["контекст"], "Waiting", result["приоритет"],
                result.get("энергия", ""), result["время"], result["срок"], whom, "", "",
                f"Из Inbox: {content}", today, ""
            ]
            sheet_actions.append_row(action_row, value_input_option="USER_ENTERED")
            whom_str = f" (от {whom})" if whom else ""
            print(f"   ⏳ Добавлено в WAITING FOR{whom_str}")

        # Project — добавить в PROJECTS + первое действие в NEXT ACTIONS
        elif result["результат"] == "Project":
            desired_outcome = result["итог_проекта"] or result["пояснение"][:200]
            save_project(
                content[:100], desired_outcome, result["область"], result["приоритет"],
                result["действие"], result["контекст"],
                why=result.get("почему", ""),
                subtasks=result.get("подзадачи", ""),
                energy=result.get("энергия", ""),
                time_min=result["время"],
                deadline=result.get("срок", ""),
                notes_extra=f"Из Inbox: {content[:80]}",
            )
            print("   ✅ Добавлено в PROJECTS + первое действие в NEXT ACTIONS")

        elif result["результат"] in ("Someday", "SomedayDate"):
            sheet_someday = get_sheet("someday")
            today = date.today().isoformat()
            remind_date = result.get("срок", "") if result["результат"] == "SomedayDate" else ""
            # Структура: ID | Идея/Проект | Описание | Область | Пересмотреть | Статус | ID проекта | Добавлен
            someday_row = [
                "", content[:200], result["пояснение"][:300], result["область"],
                remind_date, "Ожидает", "", today
            ]
            all_rows = sheet_someday.get_all_values()
            next_row = len(all_rows) + 1
            sheet_someday.update(values=[someday_row], range_name=f"A{next_row}:H{next_row}")
            date_str = f" (напомнить: {remind_date})" if remind_date else ""
            print(f"   💭 Добавлено в SOMEDAY{date_str}")
        elif result["результат"] == "Reference":
            sheet_ref = get_sheet("reference")
            today = date.today().isoformat()
            ref_row = ["", today, content[:300], "", result["область"], "Inbox", "", result["пояснение"][:200]]
            all_rows = sheet_ref.get_all_values()
            next_row = len(all_rows) + 1
            sheet_ref.update(values=[ref_row], range_name=f"A{next_row}:H{next_row}")
            print("   📚 Добавлено в REFERENCE")

        elif result["результат"] in ("H3", "H4", "H5"):
            level = result["результат"]
            sheet_horizons = get_sheet("horizons")
            today = date.today().isoformat()
            all_rows = sheet_horizons.get_all_values()
            # Миграция: добавить Область если нет
            if all_rows and len(all_rows[0]) < 7:
                sheet_horizons.update_cell(1, 6, "Область")
                sheet_horizons.update_cell(1, 7, "Заметки")
            new_id = f"{level}-{len(all_rows):03d}"
            area = result.get("область", "")
            horizon_row = [new_id, level, content[:300], today, "Активен", area, result["пояснение"][:200]]
            sheet_horizons.append_row(horizon_row, value_input_option="USER_ENTERED")
            label = {"H3": "🎯 Цель", "H4": "🔭 Видение", "H5": "⭐ Миссия"}[level]
            area_tag = f" [{area}]" if area else ""
            print(f"   {label} Добавлено в HORIZONS ({level}){area_tag}")

        elif result["результат"] == "Trash":
            print("   🗑 Можно удалить")

        # Обновить статус в Inbox на "Обработан"
        for i, row in enumerate(all_inbox):
            if row and len(row) > 2 and row[2] == content:
                sheet_inbox.update_cell(i + 1, 5, "Обработан")
                sheet_inbox.update_cell(i + 1, 6, result["результат"])
                break

        print("─" * 60)

    print(f"\n✅ Готово! Обработано элементов: {len(new_items)}")


if __name__ == "__main__":
    process_inbox()
