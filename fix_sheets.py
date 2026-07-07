import warnings
warnings.filterwarnings("ignore")
from sheets import get_sheet

# Удалить строку 2 (формула #ERROR) во всех листах
for name in ["inbox", "projects", "next_actions"]:
    s = get_sheet(name)
    rows = s.get_all_values()
    if len(rows) >= 2:
        row2 = rows[1]
        if "#ERROR!" in row2 or not any(cell.strip() for cell in row2):
            s.delete_rows(2)
            print(f"{name}: удалена строка 2 (#ERROR)")

# Удалить сдвинутые строки из Inbox (где дата попала в Содержимое)
s = get_sheet("inbox")
rows = s.get_all_values()
to_delete = []
for i, row in enumerate(rows[1:], 2):
    if len(row) >= 3:
        content = row[2].strip()
        # Если в содержимом дата вида 2026-07-XX — строка сдвинута
        if content.startswith("2026-") and len(content) == 10:
            to_delete.append(i)

for i in reversed(to_delete):
    s.delete_rows(i)
    print(f"inbox: удалена сдвинутая строка {i}")

print("\nГотово. Запусти check_all.py для проверки.")
