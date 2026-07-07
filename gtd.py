"""
GTD AI Assistant — главное меню
Запуск: python3 gtd.py
"""

import os
from datetime import date
from dotenv import load_dotenv
from sheets import read_inbox, read_next_actions, read_projects, get_sheet, append_row

load_dotenv()


def clear():
    os.system("clear")


def header():
    print("╔══════════════════════════════════════╗")
    print("║       GTD AI ASSISTANT               ║")
    print(f"║       {date.today().strftime('%d.%m.%Y')}                        ║")
    print("╚══════════════════════════════════════╝")
    print()


def show_menu():
    clear()
    header()

    # Быстрая статистика
    try:
        inbox = read_inbox()
        new_inbox = len([r for r in inbox if r.get("Статус") == "Новый"])
        actions = read_next_actions()
        next_actions = len([a for a in actions if a.get("Статус") == "Next"])
        projects = read_projects()
        active_projects = len([p for p in projects if p.get("Статус") == "Активен"])

        print(f"  📥 Inbox:          {new_inbox} новых")
        print(f"  ⚡ Next Actions:   {next_actions} задач")
        print(f"  🗂  Проекты:        {active_projects} активных")
    except Exception:
        print("  (не удалось загрузить статистику)")

    print()
    print("─" * 40)
    print("  1. Добавить в Inbox")
    print("  2. Обработать Inbox через AI")
    print("  3. Показать задачи на сегодня")
    print("  4. Показать все активные проекты")
    print("  5. Weekly Review")
    print("  0. Выход")
    print("─" * 40)
    print()


def add_to_inbox():
    clear()
    header()
    print("📥 ДОБАВИТЬ В INBOX")
    print()
    content = input("Что нужно сделать / что пришло в голову?\n> ").strip()
    if not content:
        print("Пусто — ничего не добавлено.")
        input("\nEnter чтобы вернуться...")
        return

    source = input("\nОткуда (WhatsApp / Email / Мысль / Звонок / Telegram) [Мысль]: ").strip()
    if not source:
        source = "Мысль"

    today = date.today().isoformat()
    row = ["", today, content, source, "Новый", "", "", ""]
    sheet = get_sheet("inbox")
    sheet.append_row(row, value_input_option="USER_ENTERED")

    print(f"\n✅ Добавлено в Inbox: {content}")
    input("\nEnter чтобы вернуться...")


def process_inbox_menu():
    clear()
    header()
    print("🤖 ОБРАБОТКА INBOX ЧЕРЕЗ AI")
    print()

    from inbox_processor import process_inbox
    process_inbox()

    input("\nEnter чтобы вернуться...")


def show_today_actions():
    clear()
    header()
    print("⚡ ЗАДАЧИ НА СЕГОДНЯ")
    print()

    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]

    if not next_up:
        print("  Нет активных задач.")
    else:
        # Сортировка: Высокий приоритет первым
        priority_order = {"Высокий": 0, "Средний": 1, "Низкий": 2}
        next_up.sort(key=lambda x: priority_order.get(x.get("Приоритет", "Низкий"), 3))

        for i, a in enumerate(next_up, 1):
            p = a.get("Приоритет", "")
            icon = "🔴" if p == "Высокий" else "🟡" if p == "Средний" else "🟢"
            action = a.get("Действие", "—")
            context = a.get("Контекст", "")
            time_est = a.get("Время (мин)", "")
            time_str = f" [{time_est} мин]" if time_est else ""
            print(f"  {i}. {icon} {action}")
            print(f"       {context}{time_str}")
            print()

    input("Enter чтобы вернуться...")


def show_projects():
    clear()
    header()
    print("🗂  АКТИВНЫЕ ПРОЕКТЫ")
    print()

    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]

    if not active:
        print("  Нет активных проектов.")
    else:
        for i, p in enumerate(active, 1):
            name = p.get("Название проекта", "—")
            area = p.get("Область (Area)", "")
            priority = p.get("Приоритет", "")
            next_action = p.get("Следующее действие", "")
            icon = "🔴" if priority == "Высокий" else "🟡" if priority == "Средний" else "🟢"
            print(f"  {i}. {icon} {name}")
            if area:
                print(f"       Область: {area}")
            if next_action:
                print(f"       → {next_action}")
            print()

    input("Enter чтобы вернуться...")


def weekly_review():
    clear()
    header()
    print("📊 WEEKLY REVIEW")
    print()

    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    projects = read_projects()
    actions = read_next_actions()
    inbox = read_inbox()

    active_projects = [p for p in projects if p.get("Статус") == "Активен"]
    next_actions = [a for a in actions if a.get("Статус") == "Next"]
    waiting = [a for a in actions if a.get("Статус") == "Waiting"]
    new_inbox = [r for r in inbox if r.get("Статус") == "Новый"]

    # Формируем сводку для AI
    summary = f"""Данные GTD системы на {date.today().strftime('%d.%m.%Y')}:

INBOX: {len(new_inbox)} необработанных элементов

АКТИВНЫЕ ПРОЕКТЫ ({len(active_projects)}):
"""
    for p in active_projects:
        na = p.get("Следующее действие", "НЕТ СЛЕДУЮЩЕГО ДЕЙСТВИЯ")
        summary += f"- {p.get('Название проекта')} [{p.get('Приоритет')}] → {na}\n"

    summary += f"\nNEXT ACTIONS: {len(next_actions)} задач\n"
    summary += f"WAITING FOR: {len(waiting)} ожиданий\n"

    print("Анализирую через AI...\n")

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Ты GTD-коуч. Проведи краткий Weekly Review на основе данных:

{summary}

Дай:
1. ОБЩАЯ ОЦЕНКА — как дела в системе (2-3 предложения)
2. ВНИМАНИЕ — что требует немедленного внимания
3. ТОП-3 ПРИОРИТЕТА на эту неделю
4. РЕКОМЕНДАЦИЯ — один совет по улучшению системы

Отвечай на русском, кратко и конкретно."""
        }]
    )

    print(message.content[0].text)
    print()

    # Сохранить Review в таблицу
    save = input("Сохранить этот Review в таблицу? (да/нет): ").strip().lower()
    if save in ("да", "д", "y", "yes"):
        review_sheet = get_sheet("review")
        today = date.today().isoformat()
        projects_with_na = sum(1 for p in active_projects if p.get("Следующее действие"))
        row = [
            today, "", "Да" if not new_inbox else "Нет",
            projects_with_na, len(active_projects), "",
            len(waiting), "", "", "", "", message.content[0].text
        ]
        # Найти первую пустую строку в колонке A и записать туда
        col_a = review_sheet.col_values(1)
        next_row = len(col_a) + 1
        review_sheet.update(values=[row], range_name=f"A{next_row}:L{next_row}")
        print("✅ Сохранено в WEEKLY REVIEW")

    input("\nEnter чтобы вернуться...")


def main():
    while True:
        show_menu()
        choice = input("Выбери пункт меню: ").strip()

        if choice == "1":
            add_to_inbox()
        elif choice == "2":
            process_inbox_menu()
        elif choice == "3":
            show_today_actions()
        elif choice == "4":
            show_projects()
        elif choice == "5":
            weekly_review()
        elif choice == "0":
            print("\nПока! 👋\n")
            break
        else:
            print("Неверный выбор, попробуй снова.")


if __name__ == "__main__":
    main()
