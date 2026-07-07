import warnings
warnings.filterwarnings("ignore")

import sys
print("Шаг 1: импортируем...", flush=True)

from sheets import get_spreadsheet

print("Шаг 2: подключаемся...", flush=True)
ss = get_spreadsheet()

print("Шаг 3: получаем листы...", flush=True)
sheets = ss.worksheets()

print("Листов найдено:", len(sheets), flush=True)
for s in sheets:
    print("-", repr(s.title), flush=True)

print("Готово.", flush=True)
