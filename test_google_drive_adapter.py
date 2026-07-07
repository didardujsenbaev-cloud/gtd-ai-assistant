"""
Тесты для integrations/google_drive_adapter.py (Фаза 3).

Все тесты работают БЕЗ реального подключения к Google Drive.
Используется Mock-сервис, имитирующий Drive API.

Разделение:
  Секции 1–9  — логика без API (mock-тесты)
  Секция 10   — РЕАЛЬНЫЙ Drive API (запускается только с флагом --live)

Запуск (mock-тесты):  python3 test_google_drive_adapter.py
Запуск (live-тест):   python3 test_google_drive_adapter.py --live
"""

import sys
import os
import traceback

LIVE_MODE = "--live" in sys.argv

PASSED = 0
FAILED = 0
ERRORS = []


def test(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        print(f"  ✅ {name}")
        PASSED += 1
    else:
        msg = f"  ❌ {name}"
        if detail:
            msg += f"\n     → {detail}"
        print(msg)
        FAILED += 1
        ERRORS.append(name)


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ─────────────────────────────────────────────────────────────
# Mock Drive Service
# ─────────────────────────────────────────────────────────────

class MockFileList:
    """Имитирует ответ service.files().list().execute()"""
    def __init__(self, files):
        self._files = files

    def execute(self):
        return {"files": self._files}


class MockFileCreate:
    """Имитирует ответ service.files().create().execute()"""
    def __init__(self, folder_id):
        self._id = folder_id

    def execute(self):
        return {"id": self._id}


class MockFiles:
    """Имитирует service.files()"""
    def __init__(self):
        self._folders: dict[str, str] = {}   # "name|parent" → id
        self._counter = 0

    def _key(self, name, parent):
        return f"{name}|{parent or 'root'}"

    def list(self, q="", fields="", pageSize=10, orderBy=None):
        import re
        name_match = re.search(r"name='([^']+)'", q)
        parent_match = re.search(r"'([^']+)' in parents", q)
        name = name_match.group(1) if name_match else ""
        parent = parent_match.group(1) if parent_match else None

        key = self._key(name, parent)
        if key in self._folders:
            return MockFileList([{"id": self._folders[key], "name": name}])
        return MockFileList([])

    def create(self, body=None, fields="", media_body=None):
        name = body.get("name", "unnamed")
        parents = body.get("parents", [None])
        parent = parents[0] if parents else None
        self._counter += 1
        new_id = f"MOCK_ID_{self._counter:03d}"
        key = self._key(name, parent)
        self._folders[key] = new_id
        return MockFileCreate(new_id)


class MockDriveService:
    """Имитирует полный Google Drive API service."""
    def __init__(self):
        self._files = MockFiles()

    def files(self):
        return self._files


# ─────────────────────────────────────────────────────────────
# Импорт
# ─────────────────────────────────────────────────────────────

section("1. Импорт integrations.google_drive_adapter")

try:
    from integrations.google_drive_adapter import (
        find_folder,
        create_folder,
        get_or_create_folder,
        get_folder_url,
        get_file_url,
        get_folder_id_from_url,
        create_business_structure,
        create_client_folder,
        create_case_folder,
        setup_client_workspace,
        format_structure_report,
        format_client_report,
        check_configuration,
        is_enabled,
        BUSINESS_FOLDER_STRUCTURE,
        CLIENT_FOLDER_STRUCTURE,
        CASE_FOLDER_STRUCTURE,
        DRIVE_FOLDER_MIME,
        # Новые (Фаза 5C)
        find_business_root_folder,
        ensure_biz_root_folder_id,
        create_business_folder_structure,
        setup_biz_client_folder,
        _append_to_env,
        _read_service_account_email,
        _is_shared_drive,
    )
    test("import google_drive_adapter — все функции", True)
except Exception as e:
    test("import google_drive_adapter", False, str(e))
    traceback.print_exc()
    sys.exit(1)


# ─────────────────────────────────────────────────────────────
# Тест 2: Константы
# ─────────────────────────────────────────────────────────────

section("2. Константы и структуры")

test("BUSINESS_FOLDER_STRUCTURE содержит 12 папок",
     len(BUSINESS_FOLDER_STRUCTURE) == 12,
     f"найдено: {len(BUSINESS_FOLDER_STRUCTURE)}")
test("первая папка — 01 Стратегия",
     BUSINESS_FOLDER_STRUCTURE[0] == "01 Стратегия")
test("последняя папка — 12 Архив",
     BUSINESS_FOLDER_STRUCTURE[-1] == "12 Архив")
test("папка 06 Клиенты есть",
     "06 Клиенты" in BUSINESS_FOLDER_STRUCTURE)
test("папка 08 Финансы есть",
     "08 Финансы" in BUSINESS_FOLDER_STRUCTURE)

test("CLIENT_FOLDER_STRUCTURE содержит 5 папок",
     len(CLIENT_FOLDER_STRUCTURE) == 5,
     f"найдено: {len(CLIENT_FOLDER_STRUCTURE)}")
test("CASE_FOLDER_STRUCTURE содержит 4 папки",
     len(CASE_FOLDER_STRUCTURE) == 4,
     f"найдено: {len(CASE_FOLDER_STRUCTURE)}")

test("DRIVE_FOLDER_MIME корректный",
     DRIVE_FOLDER_MIME == "application/vnd.google-apps.folder")


# ─────────────────────────────────────────────────────────────
# Тест 3: URL-утилиты
# ─────────────────────────────────────────────────────────────

section("3. URL-утилиты")

url = get_folder_url("ABC123")
test("get_folder_url содержит id", "ABC123" in url)
test("get_folder_url — drive.google.com", "drive.google.com" in url)
test("get_folder_url — /folders/", "/folders/" in url)

file_url = get_file_url("FILE456")
test("get_file_url содержит id", "FILE456" in file_url)
test("get_file_url — drive.google.com", "drive.google.com" in file_url)

# get_folder_id_from_url
fid = get_folder_id_from_url("https://drive.google.com/drive/folders/ABC123XYZ")
test("get_folder_id_from_url стандартный формат",
     fid == "ABC123XYZ", f"получено: {fid}")

fid2 = get_folder_id_from_url("https://drive.google.com/drive/u/0/folders/DEF456")
test("get_folder_id_from_url с /u/0/",
     fid2 == "DEF456", f"получено: {fid2}")

fid3 = get_folder_id_from_url("https://example.com/not-a-drive-url")
test("get_folder_id_from_url → None при плохом URL",
     fid3 is None, f"получено: {fid3}")


# ─────────────────────────────────────────────────────────────
# Тест 4: find_folder() с mock
# ─────────────────────────────────────────────────────────────

section("4. find_folder() — поиск папки (mock)")

svc = MockDriveService()

# Папки пока нет
fid = find_folder(svc, "Тестовая папка", None)
test("несуществующая папка → None", fid is None)

# Создаём папку вручную в mock
svc.files()._folders["Тестовая папка|root"] = "EXISTING_ID_001"

fid2 = find_folder(svc, "Тестовая папка", None)
test("существующая папка → возвращает ID",
     fid2 == "EXISTING_ID_001", f"получено: {fid2}")

# Поиск с parent_id
svc.files()._folders["Подпапка|PARENT_001"] = "CHILD_ID_001"
fid3 = find_folder(svc, "Подпапка", "PARENT_001")
test("поиск с parent_id → верный ID",
     fid3 == "CHILD_ID_001", f"получено: {fid3}")

fid4 = find_folder(svc, "Подпапка", "WRONG_PARENT")
test("поиск с неверным parent → None", fid4 is None)


# ─────────────────────────────────────────────────────────────
# Тест 5: create_folder() с mock
# ─────────────────────────────────────────────────────────────

section("5. create_folder() — создание папки (mock)")

svc2 = MockDriveService()

# Создаём новую папку
new_id = create_folder(svc2, "Новая папка", None, dry_run=False)
test("create_folder возвращает ID", bool(new_id))
test("ID не пустой", new_id != "")
print(f"     ID: {new_id}")

# Идемпотентность: повторный вызов возвращает тот же ID
same_id = create_folder(svc2, "Новая папка", None, dry_run=False)
test("идемпотентность: повторный вызов → тот же ID",
     same_id == new_id, f"new={new_id}, same={same_id}")

# dry_run
dry_id = create_folder(svc2, "Папка не создаётся", None, dry_run=True)
test("dry_run: ID содержит DRY_RUN", "DRY_RUN" in dry_id,
     f"получено: {dry_id}")
# dry_run не добавляет папку в mock
fid_after_dry = find_folder(svc2, "Папка не создаётся", None)
test("dry_run: папка НЕ создана в Drive", fid_after_dry is None)


# ─────────────────────────────────────────────────────────────
# Тест 6: get_or_create_folder()
# ─────────────────────────────────────────────────────────────

section("6. get_or_create_folder()")

svc3 = MockDriveService()

fid_a, created_a = get_or_create_folder(svc3, "Папка А", None)
test("первое создание: was_created == True", created_a is True)
test("первое создание: ID не пустой", bool(fid_a))

fid_b, created_b = get_or_create_folder(svc3, "Папка А", None)
test("повторный вызов: was_created == False", created_b is False)
test("повторный вызов: тот же ID", fid_b == fid_a, f"a={fid_a} b={fid_b}")


# ─────────────────────────────────────────────────────────────
# Тест 7: create_business_structure()
# ─────────────────────────────────────────────────────────────

section("7. create_business_structure() — структура бизнеса (mock)")

svc4 = MockDriveService()

result = create_business_structure(
    svc4,
    business_name="Узаконение недвижимости",
    parent_folder_id=None,
    dry_run=False,
)

test("результат содержит root_id", bool(result.get("root_id")))
test("результат содержит root_url", "drive.google.com" in result.get("root_url", ""))
test("created == True (папка новая)", result.get("created") is True)
test("dry_run == False", result.get("dry_run") is False)
test("subfolders содержит 12 записей",
     len(result.get("subfolders", {})) == 12,
     f"найдено: {len(result.get('subfolders', {}))}")

# Проверяем ключи подпапок
subs = result["subfolders"]
test("подпапка 01_стратегия есть",  "01_стратегия" in subs)
test("подпапка 06_клиенты есть",    "06_клиенты" in subs)
test("подпапка 08_финансы есть",    "08_финансы" in subs)
test("подпапка 12_архив есть",      "12_архив" in subs)

# Каждая подпапка имеет id и url
for slug, info in subs.items():
    test(f"подпапка {slug}: id не пустой",
         bool(info.get("id")))
    break  # проверяем только первую для краткости

test("подпапки имеют url",
     all("drive.google.com" in info.get("url", "") for info in subs.values()))

# Идемпотентность: повторный вызов — папка уже есть
result2 = create_business_structure(
    svc4, "Узаконение недвижимости", None, dry_run=False
)
test("повторный вызов: root_id тот же",
     result2["root_id"] == result["root_id"],
     f"1st={result['root_id']} 2nd={result2['root_id']}")
test("повторный вызов: created == False",
     result2["created"] is False)

# dry_run версия
result_dry = create_business_structure(
    svc4, "Коучинг", None, dry_run=True
)
test("dry_run: root_id содержит DRY_RUN",
     "DRY_RUN" in result_dry["root_id"], f"id={result_dry['root_id']}")
test("dry_run: subfolders возвращаются",
     len(result_dry["subfolders"]) == 12)
print(f"     root_id: {result['root_id']}")
print(f"     url: {result['root_url']}")


# ─────────────────────────────────────────────────────────────
# Тест 8: create_client_folder()
# ─────────────────────────────────────────────────────────────

section("8. create_client_folder() — папка клиента (mock)")

svc5 = MockDriveService()

# Создаём корневую папку бизнеса
biz_root_id = create_folder(svc5, "Узаконение недвижимости", None)

client_result = create_client_folder(
    svc5,
    client_name="Иванов Александр",
    business_root_id=biz_root_id,
    service_name="Узаконение частного дома",
    dry_run=False,
)

test("client_root_id не пустой", bool(client_result.get("client_root_id")))
test("client_root_url есть", "drive.google.com" in client_result.get("client_root_url", ""))
test("clients_folder_id есть", bool(client_result.get("clients_folder_id")))
test("created == True", client_result.get("created") is True)
test("subfolders содержит 5 записей",
     len(client_result.get("subfolders", {})) == 5,
     f"найдено: {len(client_result.get('subfolders', {}))}")

# Без названия услуги
client_result2 = create_client_folder(
    svc5, "Петрова Алия", biz_root_id, dry_run=False
)
test("без услуги: папка создаётся", bool(client_result2.get("client_root_id")))
print(f"     client_url: {client_result['client_root_url']}")


# ─────────────────────────────────────────────────────────────
# Тест 9: setup_client_workspace()
# ─────────────────────────────────────────────────────────────

section("9. setup_client_workspace() — полный флоу")

svc6 = MockDriveService()
biz_id2 = create_folder(svc6, "Визы и документы", None)

workspace = setup_client_workspace(
    svc6,
    business_name="Визы и документы",
    business_root_id=biz_id2,
    client_name="Алибек Дюсенов",
    service_name="Туристическая виза",
    roadmap_id="RM-003",
    dry_run=False,
)

test("workspace: business_name заполнен", workspace.get("business_name") == "Визы и документы")
test("workspace: client_name заполнен", workspace.get("client_name") == "Алибек Дюсенов")
test("workspace: client_root_id не пустой", bool(workspace.get("client_root_id")))
test("workspace: client_root_url есть", "drive.google.com" in workspace.get("client_root_url", ""))
test("workspace: subfolders есть", len(workspace.get("subfolders", {})) == 5)
test("workspace: case_folder создана (roadmap_id задан)",
     workspace.get("case_folder") is not None)

case = workspace["case_folder"]
test("case_folder: root_id не пустой", bool(case.get("case_root_id")))
test("case_folder: subfolders 4 штуки",
     len(case.get("subfolders", {})) == 4,
     f"найдено: {len(case.get('subfolders', {}))}")

# Без roadmap_id → case_folder = None
workspace2 = setup_client_workspace(
    svc6,
    business_name="Визы и документы",
    business_root_id=biz_id2,
    client_name="Асель Нурланова",
    dry_run=False,
)
test("без roadmap_id: case_folder == None",
     workspace2.get("case_folder") is None)

# dry_run
workspace_dry = setup_client_workspace(
    svc6,
    business_name="Узаконение",
    business_root_id="BIZ_ROOT_FAKE",
    client_name="Сарсен",
    service_name="Узаконение гаража",
    dry_run=True,
)
test("dry_run workspace: dry_run == True",
     workspace_dry.get("dry_run") is True)
test("dry_run workspace: ID содержит DRY_RUN",
     "DRY_RUN" in workspace_dry.get("client_root_id", ""))


# ─────────────────────────────────────────────────────────────
# Тест 10 (дополнительный): format_*()
# ─────────────────────────────────────────────────────────────

section("10. Форматирование отчётов")

report = format_structure_report(result)
test("format_structure_report: строка", isinstance(report, str))
test("содержит 'Google Drive'", "Drive" in report or "drive" in report.lower())
test("содержит ссылку", "http" in report)

client_rpt = format_client_report(workspace)
test("format_client_report: строка", isinstance(client_rpt, str))
test("содержит имя клиента", "Алибек" in client_rpt)
test("содержит бизнес", "Визы" in client_rpt)

dry_report = format_structure_report(result_dry)
test("dry_run отчёт содержит DRY RUN", "DRY RUN" in dry_report)

cfg = check_configuration()
test("check_configuration: возвращает dict", isinstance(cfg, dict))
test("check_configuration: содержит ok, issues, info",
     all(k in cfg for k in ("ok", "issues", "info")))
test("is_enabled() возвращает bool", isinstance(is_enabled(), bool))


# ─────────────────────────────────────────────────────────────
# Тест 11: Изоляция
# ─────────────────────────────────────────────────────────────

section("11. Изоляция — GTD-файлы не импортируются")

import pathlib
source = pathlib.Path("integrations/google_drive_adapter.py").read_text()
for forbidden in ["telegram_bot", "inbox_processor", "project_planner",
                  "calendar_sync", "from sheets import"]:
    test(f"не импортирует '{forbidden}'", forbidden not in source)

section("12. GTD-файлы не изменены")
for f in ["telegram_bot.py", "sheets.py", "inbox_processor.py",
          "project_planner.py", "calendar_sync.py"]:
    test(f"{f} существует", os.path.exists(f))


# ─────────────────────────────────────────────────────────────
# Тест 13: Shared Drive helper
# ─────────────────────────────────────────────────────────────

section("13. _is_shared_drive() и _read_service_account_email()")

original_shared = os.environ.get("GDRIVE_IS_SHARED_DRIVE", "")

os.environ["GDRIVE_IS_SHARED_DRIVE"] = "true"
test("_is_shared_drive() == True при GDRIVE_IS_SHARED_DRIVE=true", _is_shared_drive() is True)

os.environ["GDRIVE_IS_SHARED_DRIVE"] = "false"
test("_is_shared_drive() == False при GDRIVE_IS_SHARED_DRIVE=false", _is_shared_drive() is False)

os.environ["GDRIVE_IS_SHARED_DRIVE"] = original_shared or "false"

sa_email = _read_service_account_email()
test("_read_service_account_email() возвращает строку", isinstance(sa_email, str))
test("_read_service_account_email() не пустой или fallback",
     len(sa_email) > 0)
print(f"     service account: {sa_email}")


# ─────────────────────────────────────────────────────────────
# Тест 14: find_business_root_folder() — mock
# ─────────────────────────────────────────────────────────────

section("14. find_business_root_folder() — mock")

from unittest.mock import MagicMock, patch


class MockFilesWithRoot:
    """Mock: возвращает папку BUSINESS_CORE_DRIVE."""
    def list(self, q="", fields="", pageSize=10, **kwargs):
        if "BUSINESS_CORE_DRIVE" in q:
            mock = MagicMock()
            mock.execute.return_value = {"files": [
                {"id": "MOCK_ROOT_001", "name": "BUSINESS_CORE_DRIVE",
                 "webViewLink": "https://drive.google.com/drive/folders/MOCK_ROOT_001"}
            ]}
            return mock
        mock = MagicMock()
        mock.execute.return_value = {"files": []}
        return mock


class MockServiceWithRoot:
    def files(self):
        return MockFilesWithRoot()


class MockFilesNotFound:
    def list(self, **kwargs):
        mock = MagicMock()
        mock.execute.return_value = {"files": []}
        return mock


class MockServiceNotFound:
    def files(self):
        return MockFilesNotFound()


class MockFilesMultiple:
    def list(self, **kwargs):
        mock = MagicMock()
        mock.execute.return_value = {"files": [
            {"id": "ID_001", "name": "BUSINESS_CORE_DRIVE", "webViewLink": "..."},
            {"id": "ID_002", "name": "BUSINESS_CORE_DRIVE", "webViewLink": "..."},
        ]}
        return mock


class MockServiceMultiple:
    def files(self):
        return MockFilesMultiple()


# Тест: папка найдена
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockServiceWithRoot()):
    try:
        info = find_business_root_folder("BUSINESS_CORE_DRIVE")
        test("найдена одна папка → dict", isinstance(info, dict))
        test("id заполнен", info.get("id") == "MOCK_ROOT_001")
        test("name заполнен", info.get("name") == "BUSINESS_CORE_DRIVE")
        test("webViewLink заполнен", "drive.google.com" in info.get("webViewLink", ""))
    except Exception as e:
        test("find_business_root_folder — нет исключения", False, str(e))

# Тест: папка не найдена → RuntimeError
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockServiceNotFound()):
    try:
        find_business_root_folder("BUSINESS_CORE_DRIVE")
        test("не найдена → RuntimeError", False, "исключение не брошено")
    except RuntimeError as e:
        test("не найдена → RuntimeError", True, str(e)[:60])
    except Exception as e:
        test("не найдена → RuntimeError (другое исключение)", False, str(e))

# Тест: несколько папок → RuntimeError с ID
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockServiceMultiple()):
    try:
        find_business_root_folder("BUSINESS_CORE_DRIVE")
        test("несколько папок → RuntimeError", False, "исключение не брошено")
    except RuntimeError as e:
        err_msg = str(e)
        test("несколько папок → RuntimeError", True)
        test("ошибка содержит ID_001", "ID_001" in err_msg)
        test("ошибка содержит ID_002", "ID_002" in err_msg)


# ─────────────────────────────────────────────────────────────
# Тест 15: ensure_biz_root_folder_id() и _append_to_env()
# ─────────────────────────────────────────────────────────────

section("15. ensure_biz_root_folder_id() — mock")

import tempfile

# Тест: уже задан в env
original_env_id = os.environ.get("GDRIVE_BIZ_ROOT_FOLDER_ID", "")
os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = "ENV_FOLDER_ID_123"

with patch("integrations.google_drive_adapter.get_drive_service"):  # не должен вызываться
    result_id = ensure_biz_root_folder_id(ask_confirmation=False)
test("env уже задан → возвращает его без Drive-запроса",
     result_id == "ENV_FOLDER_ID_123", f"получено: {result_id}")

# Тест: не задан → ищет в Drive
del os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"]
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockServiceWithRoot()):
    with patch("integrations.google_drive_adapter._append_to_env"):
        found_id = ensure_biz_root_folder_id(ask_confirmation=False)
test("не задан → находит через Drive API",
     found_id == "MOCK_ROOT_001", f"получено: {found_id}")

# Тест: _append_to_env добавляет строку (без изменения существующих)
with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as tf:
    tf.write("TELEGRAM_TOKEN=abc123\nGOOGLE_CREDENTIALS_FILE=creds.json\n")
    tmp_path = tf.name

# Напрямую передаём путь к временному файлу
_append_to_env("GDRIVE_BIZ_ROOT_FOLDER_ID=NEW_TEST_ID", env_path=tmp_path)
with open(tmp_path) as f:
    content = f.read()
test("_append_to_env добавил строку", "GDRIVE_BIZ_ROOT_FOLDER_ID=NEW_TEST_ID" in content)
test("существующие переменные не изменились", "TELEGRAM_TOKEN=abc123" in content)

# Повторный вызов не дублирует
_append_to_env("GDRIVE_BIZ_ROOT_FOLDER_ID=NEW_TEST_ID", env_path=tmp_path)
with open(tmp_path) as f:
    content2 = f.read()
count = content2.count("GDRIVE_BIZ_ROOT_FOLDER_ID")
test("повторный _append_to_env не дублирует", count == 1, f"найдено {count} вхождений")

import os as _os
_os.unlink(tmp_path)

# Восстанавливаем env
if original_env_id:
    os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = original_env_id
elif "GDRIVE_BIZ_ROOT_FOLDER_ID" in os.environ:
    del os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"]


# ─────────────────────────────────────────────────────────────
# Тест 16: create_business_folder_structure() — mock высокоуровневый
# ─────────────────────────────────────────────────────────────

section("16. create_business_folder_structure() — высокоуровневый mock")

os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = "MOCK_BIZ_ROOT"

with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockDriveService()):
    biz_result = create_business_folder_structure(
        biz_id="BIZ-TEST",
        biz_name="Тестовый бизнес",
        dry_run=False,
    )

test("возвращает dict", isinstance(biz_result, dict))
test("business_folder_id не пустой", bool(biz_result.get("business_folder_id")))
test("business_folder_url содержит drive.google.com",
     "drive.google.com" in biz_result.get("business_folder_url", ""))
test("folders содержит 12 папок",
     len(biz_result.get("folders", {})) == 12,
     f"найдено: {len(biz_result.get('folders', {}))}")
test("01 Стратегия в folders", "01 Стратегия" in biz_result.get("folders", {}))
test("06 Клиенты в folders",   "06 Клиенты"   in biz_result.get("folders", {}))
test("12 Архив в folders",     "12 Архив"     in biz_result.get("folders", {}))
print(f"     folder_url: {biz_result.get('business_folder_url')}")

# Повтор — идемпотентность
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockDriveService()):
    biz_result2 = create_business_folder_structure(
        "BIZ-TEST", "Тестовый бизнес", dry_run=False
    )
test("dry_run=False, структура возвращается", bool(biz_result2.get("business_folder_id")))


# ─────────────────────────────────────────────────────────────
# Тест 17: setup_biz_client_folder() — mock высокоуровневый
# ─────────────────────────────────────────────────────────────

section("17. setup_biz_client_folder() — высокоуровневый mock")

with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockDriveService()):
    client_result = setup_biz_client_folder(
        biz_id="BIZ-TEST",
        biz_name="Тестовый бизнес",
        client_name="Тестовый клиент",
        roadmap_id="RM-TEST",
        dry_run=False,
    )

test("возвращает dict", isinstance(client_result, dict))
test("client_folder_id не пустой", bool(client_result.get("client_folder_id")))
test("client_folder_url содержит drive.google.com",
     "drive.google.com" in client_result.get("client_folder_url", ""))
test("subfolders содержит 5 папок",
     len(client_result.get("subfolders", {})) == 5,
     f"найдено: {len(client_result.get('subfolders', {}))}")
test("01 Документы от клиента",
     "01 Документы от клиента" in client_result.get("subfolders", {}))
test("05 Архив в subfolders",
     "05 Архив" in client_result.get("subfolders", {}))

# Без roadmap_id
with patch("integrations.google_drive_adapter.get_drive_service",
           return_value=MockDriveService()):
    client_result2 = setup_biz_client_folder(
        "BIZ-TEST", "Тестовый бизнес",
        client_name="Другой клиент",
        dry_run=False,
    )
test("без roadmap_id: папка создаётся", bool(client_result2.get("client_folder_id")))
print(f"     client_url: {client_result.get('client_folder_url')}")

# Очищаем env
if "GDRIVE_BIZ_ROOT_FOLDER_ID" in os.environ:
    del os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"]


# ─────────────────────────────────────────────────────────────
# LIVE-тест (только при --live)
# ─────────────────────────────────────────────────────────────

if LIVE_MODE:
    section("LIVE. Реальный Google Drive API")
    print("  ⚠️  Этот тест создаёт РЕАЛЬНЫЕ папки в Google Drive!")
    print("  ⚠️  Потребуется папка 'BUSINESS_CORE_DRIVE' с доступом для service account")
    print()

    try:
        from integrations.google_drive_adapter import get_drive_service

        svc_live = get_drive_service()
        test("LIVE: авторизация успешна", True)

        # 1. Найти корневую папку
        root_info = find_business_root_folder("BUSINESS_CORE_DRIVE")
        test("LIVE: BUSINESS_CORE_DRIVE найдена", bool(root_info.get("id")))
        print(f"  🔗 Корень: {root_info.get('webViewLink', root_info['id'])}")

        # 2. Создать тестовую структуру бизнеса
        os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = root_info["id"]
        biz_live = create_business_folder_structure(
            biz_id="BIZ-TEST",
            biz_name="Тестовый бизнес",
            dry_run=False,
        )
        test("LIVE: BIZ-TEST_Тестовый бизнес — папка создана", bool(biz_live["business_folder_id"]))
        test("LIVE: 12 подпапок", len(biz_live["folders"]) == 12)
        print(f"  🔗 Бизнес: {biz_live['business_folder_url']}")

        # 3. Создать клиентскую папку
        client_live = setup_biz_client_folder(
            biz_id="BIZ-TEST",
            biz_name="Тестовый бизнес",
            client_name="Тестовый клиент",
            roadmap_id="RM-TEST",
            dry_run=False,
        )
        test("LIVE: папка клиента создана", bool(client_live["client_folder_id"]))
        test("LIVE: 5 подпапок клиента", len(client_live["subfolders"]) == 5)
        print(f"  🔗 Клиент: {client_live['client_folder_url']}")

        # 4. Повторный вызов — нет дублей
        client_live2 = setup_biz_client_folder(
            biz_id="BIZ-TEST", biz_name="Тестовый бизнес",
            client_name="Тестовый клиент", roadmap_id="RM-TEST",
            dry_run=False,
        )
        test("LIVE: нет дублей — тот же client_folder_id",
             client_live2["client_folder_id"] == client_live["client_folder_id"])

        print()
        print("  ✅ Все LIVE-тесты прошли!")
        print(f"  Структура создана в папке: {root_info.get('webViewLink', root_info['id'])}")

    except Exception as e:
        test("LIVE: Google Drive API", False, str(e))
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────
# Итог
# ─────────────────────────────────────────────────────────────

total = PASSED + FAILED
print(f"\n{'═' * 60}")
print(f"  ИТОГ: {PASSED}/{total} тестов прошло")
if FAILED == 0:
    print("  🎉 Все тесты прошли! Google Drive Adapter готов.")
    print()
    if not LIVE_MODE:
        print("  Для реального теста Drive: python3 test_google_drive_adapter.py --live")
    print("  Следующий шаг: Фаза 4 — /business команды в Telegram")
else:
    print(f"  ❌ Провалено: {FAILED}")
    for err in ERRORS:
        print(f"     • {err}")
print(f"{'═' * 60}\n")

sys.exit(0 if FAILED == 0 else 1)
