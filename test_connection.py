"""
Тест подключения к Google Sheets.
Запуск: python test_connection.py
"""

from sheets import get_spreadsheet, read_inbox, read_projects, read_next_actions


def main():
    print("Подключаемся к GTD Master System...")
    ss = get_spreadsheet()
    print(f"✅ Подключено: {ss.title}")
    print()

    print("📥 INBOX:")
    inbox = read_inbox()
    if inbox:
        for row in inbox[:3]:
            print(f"  • {row.get('Содержимое', '—')} [{row.get('Статус', '?')}]")
    else:
        print("  (пусто)")
    print()

    print("🗂 PROJECTS:")
    projects = read_projects()
    active = [p for p in projects if p.get("Статус") == "Активен"]
    print(f"  Всего: {len(projects)}, Активных: {len(active)}")
    for p in active[:3]:
        print(f"  • {p.get('Название проекта', '—')} [{p.get('Приоритет', '?')}]")
    print()

    print("⚡ NEXT ACTIONS:")
    actions = read_next_actions()
    next_up = [a for a in actions if a.get("Статус") == "Next"]
    print(f"  Всего: {len(actions)}, Next: {len(next_up)}")
    for a in next_up[:3]:
        print(f"  • {a.get('Действие', '—')} [{a.get('Контекст', '?')}]")


if __name__ == "__main__":
    main()
