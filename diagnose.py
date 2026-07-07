import warnings
warnings.filterwarnings("ignore")

from sheets import get_sheet

def show_sheet(name, short_name):
    print(f"\n{'='*60}")
    print(f"  {short_name}")
    print(f"{'='*60}")
    s = get_sheet(name)
    rows = s.get_all_values()
    if not rows:
        print("  ПУСТО")
        return
    headers = rows[0]
    print(f"  Колонки: {headers}")
    print(f"  Строк данных: {len(rows)-1}")
    print()
    for i, row in enumerate(rows[1:], 2):
        # Пропустить полностью пустые
        if not any(cell.strip() for cell in row):
            print(f"  Строка {i}: [ПУСТАЯ]")
            continue
        print(f"  Строка {i}:")
        for j, (h, v) in enumerate(zip(headers, row)):
            if v.strip():
                print(f"    {h}: {v[:80]}")
        print()

show_sheet("inbox", "📥 INBOX")
show_sheet("projects", "🗂 PROJECTS")
show_sheet("next_actions", "⚡ NEXT ACTIONS")
