import warnings
warnings.filterwarnings("ignore")

from sheets import read_inbox, read_projects, read_next_actions

print("=== INBOX ===")
inbox = read_inbox()
print(f"Строк: {len(inbox)}")
for r in inbox:
    print(f"  [{r.get('Статус','?')}] {str(r.get('Содержимое','-'))[:70]}")

print()
print("=== PROJECTS ===")
projects = read_projects()
print(f"Строк: {len(projects)}")
for p in projects:
    print(f"  [{p.get('Статус','?')}] {str(p.get('Название проекта','-'))[:70]}")
    na = p.get('Следующее действие','')
    if na:
        print(f"    → {na[:60]}")

print()
print("=== NEXT ACTIONS ===")
actions = read_next_actions()
print(f"Строк: {len(actions)}")
for a in actions:
    print(f"  [{a.get('Статус','?')}] [{a.get('Приоритет','?')}] {str(a.get('Действие','-'))[:70]}")
    print(f"    {a.get('Контекст','')} | {a.get('Область','')} | {a.get('Время (мин)','')} мин")
