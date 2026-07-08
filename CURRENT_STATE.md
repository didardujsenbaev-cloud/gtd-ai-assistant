# GTD AI Assistant — Current State

_Last updated: 2026-07-08_

---

## GTD Core

- **Статус: стабилен, не трогать без необходимости**
- Файлы: `telegram_bot.py`, `sheets.py`, `inbox_processor.py`, `project_planner.py`, `calendar_sync.py`
- Команды работают: `/start`, `/now`, `/tasks`, `/projects`, `/done`, `/waiting`, `/someday`, `/calendar`, `/cal_sync`, `/stats`, `/review`, `/inbox`, `/project`, `/close`, `/archive`, `/ref`, `/help`
- Деплой: Railway (`worker: python3 start.py`)
- Голосовые сообщения: `faster-whisper` (без torch, без openai-whisper)

---

## Business Core

- **Статус: подключен, работает параллельно с GTD**
- Выключатель: `BUSINESS_CORE_ENABLED=true/false` в `.env`
- Файлы: `business_core/` — `sheets.py`, `business_builder.py`, `telegram_handlers.py`, `inbox_bridge.py`, `models.py`, `business_router.py`, `roadmap_manager.py`, `material_manager.py`
- Команды: `/newbiz`, `/newclient`, `/newroadmap`, `/bc`, `/clients`, `/initbc`
- Business Core не влияет на GTD-поток при любой ошибке (try/except)

---

## Google Drive Adapter

- **Статус: работает, live-тест пройден**
- Файл: `integrations/google_drive_adapter.py`
- `/newbiz` → создаёт папку бизнеса в Drive
- `/newclient` → создаёт папку клиента внутри `{biz_id}_{biz_name}/06 Клиенты/`
- Идемпотентно: повторный вызов возвращает существующую папку, не создаёт дубли
- Поддерживает Shared Drives

---

## Выполненные фазы

| Фаза | Описание | Коммит |
|------|----------|--------|
| Phase 1 | Локальные модели Business Core | — |
| Phase 2A | Google Sheets для Business Core | — |
| Phase 2B | Business Router (AI-роутинг) | — |
| Phase 2C | Roadmap Manager | — |
| Phase 2D | Material Manager | — |
| Phase 3 | Google Drive Adapter | — |
| Phase 5 | Подключение к GTD Inbox-потоку | — |
| Phase 5B | Подтверждение бизнес-контекста (inline кнопки) | — |
| Phase 6A | Multi-Business Config Schema | `08d23dd` |
| Phase 6B | Защита от дублей клиентов через Biz IDs | `e2350ee` |
| Phase 6C | Drive Root per Business | `d266b53` |

---

## Phase 6A — Multi-Business Config Schema

- `BIZ_REGISTRY`: добавлены `Drive Root ID`, `Drive Credentials`, `Google Account Email`, `Cities JSON`, `Default City`, `Business Model Type`
- `PEOPLE_REGISTRY`: добавлены `Biz IDs`, `Company ID`, `Citizenship`, `Passport / ID`, `Primary Biz ID`; старое поле `"Бизнесы"` сохранено
- `OBJECT_REGISTRY`: новый лист (для объектов недвижимости в Узаконении)
- `ROADMAPS`: добавлены `Object ID`, `Parent Roadmap ID`, `Case Type`
- Helper-функции: `get_business_config`, `get_business_drive_root_id`, `get_business_model_type`, `get_person_biz_ids`, `normalize_biz_ids`

## Phase 6B — Client Dedup via Biz IDs

- `normalize_person_name(name)` — trim + spaces + lower
- `normalize_phone(phone)` — только цифры
- `find_existing_person(name, phone, biz_id)` — поиск с флагом `same_biz`
- `add_biz_id_to_person(person_id, biz_id)` — без дублей, Primary Biz ID не перезаписывает
- `update_person_drive_info(...)` — дозаполняет только если пусто
- `/newclient`: три сценария — NEW / SAME_BIZ / OTHER_BIZ

## Phase 6C — Drive Root per Business

- `resolve_drive_root_for_business(biz_id)` — возвращает `{root_id, source, ok, error}`
- Приоритет: `BIZ_REGISTRY.Drive Root ID` → `GDRIVE_BIZ_ROOT_FOLDER_ID` (.env) → `ok=False`
- Разные бизнесы могут использовать разные Google Drive root-папки
- Старый global fallback через `.env` сохранён

---

## Тесты (mock, без live API)

| Файл | Тестов |
|------|--------|
| `test_business_core.py` | 211 |
| `test_inbox_bridge.py` | 25 |
| `test_phase6a_schema.py` | 42 |
| `test_business_client_dedup.py` | 38 |
| `test_business_drive_root_per_biz.py` | 22 |
| `test_business_builder_drive.py` | 15 |
| `test_business_builder_client_drive.py` | 38 |
| `test_google_drive_adapter.py` | 114 (mock) |

---

## Правила работы с проектом

- **`.env` не коммитить** (в `.gitignore`)
- **GTD-файлы не трогать без необходимости**: `telegram_bot.py`, `sheets.py`, `inbox_processor.py`, `project_planner.py`, `calendar_sync.py`
- Business Core не должен импортировать GTD-модули (проверяется тестами)
- Live Drive API не запускать без явного подтверждения

---

## Следующие шаги (не реализованы)

- Phase 7: OBJECT_REGISTRY — команды `/newobject`, `/objects`
- Phase 7B: Roadmap → Object связка (для Узаконения)
- Phase 8: SendPulse / WABA / Instagram / Binotel per-biz (конфигурация уже в схеме)
- Phase 9: Полный мульти-бизнес дашборд `/bc`

---

## Переменные окружения (`.env`)

```
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
GOOGLE_CREDENTIALS_FILE=...
SPREADSHEET_ID=...               # GTD Google Sheet
BUSINESS_SPREADSHEET_ID=...      # Business Core Google Sheet
BUSINESS_CORE_ENABLED=true
GDRIVE_BIZ_ROOT_FOLDER_ID=...    # глобальный Drive root (fallback)
BUSINESS_DRIVE_ENABLED=true
GOOGLE_CREDENTIALS_JSON=...      # для Railway (base64 или JSON-строка)
```
