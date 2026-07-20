"""
Google Drive Adapter — создание и управление структурой папок бизнеса.

Использует существующий GOOGLE_CREDENTIALS_FILE из .env (тот же service account,
что и для Google Sheets). Service account уже авторизован в вашем Drive.

Идемпотентность: все операции проверяют наличие папки перед созданием.
  create_folder()  →  ищет папку, создаёт только если не существует.

Режим dry_run=True: все операции логируются, но не выполняются реально.
  Используется в тестах и при отладке.

Поддержка Shared Drive: автоматически если GDRIVE_IS_SHARED_DRIVE=true.

Требует:
  pip install google-api-python-client google-auth

Переменные .env:
  GOOGLE_CREDENTIALS_FILE    = path/to/service_account.json
  GDRIVE_BIZ_ROOT_FOLDER_ID  = ID корневой папки Business Core (BUSINESS_CORE_DRIVE)
                               Если не задан — ensure_biz_root_folder_id() найдёт автоматически
  GDRIVE_IS_SHARED_DRIVE     = true/false  (поддержка Team Drive)
  BUSINESS_DRIVE_ENABLED     = true/false
  DRIVE_ROOT_FOLDER_ID       = устаревший алиас (для обратной совместимости)
"""

from __future__ import annotations

import os
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Стандартная структура папок бизнеса (из business_builder.py)
# ─────────────────────────────────────────────────────────────

BUSINESS_FOLDER_STRUCTURE = [
    "01 Стратегия",
    "02 Услуги",
    "03 Процессы",
    "04 Маркетинг",
    "05 Продажи",
    "06 Клиенты",
    "07 Производство",
    "08 Финансы",
    "09 Команда",
    "10 Автоматизация",
    "11 Аналитика",
    "12 Архив",
]

# Папки для хранения клиентских документов по услугам
CLIENT_FOLDER_STRUCTURE = [
    "01 Документы клиента",
    "02 Наши документы",
    "03 Переписка",
    "04 Финансы",
    "05 Архив",
]

# Папки для конкретного кейса (roadmap)
CASE_FOLDER_STRUCTURE = [
    "01 Исходные документы",
    "02 Промежуточные",
    "03 Готовые документы",
    "04 Финансы кейса",
]

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"


# ─────────────────────────────────────────────────────────────
# Авторизация
# ─────────────────────────────────────────────────────────────

def _get_credentials():
    """
    Получить Google-credentials из GOOGLE_CREDENTIALS_FILE.

    Returns:
        google.oauth2.service_account.Credentials

    Raises:
        RuntimeError: если файл не найден или некорректен
    """
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    if not creds_file:
        raise RuntimeError(
            "GOOGLE_CREDENTIALS_FILE не задан в .env. "
            "Укажи путь к JSON service account."
        )
    if not os.path.exists(creds_file):
        raise RuntimeError(
            f"Файл credentials не найден: {creds_file}"
        )

    try:
        from google.oauth2 import service_account
        scopes = [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/drive.file",
        ]
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=scopes
        )
        return creds
    except ImportError:
        raise RuntimeError(
            "Библиотека google-api-python-client не установлена. "
            "Выполни: pip install google-api-python-client google-auth"
        )


def get_drive_service():
    """
    Получить авторизованный сервис Google Drive API v3.

    Returns:
        googleapiclient.discovery.Resource

    Raises:
        RuntimeError: при проблемах с авторизацией
    """
    try:
        from googleapiclient.discovery import build
        creds = _get_credentials()
        service = build("drive", "v3", credentials=creds)
        log.debug("Google Drive service: авторизация успешна")
        return service
    except ImportError:
        raise RuntimeError(
            "Библиотека googleapiclient не установлена."
        )


def is_enabled() -> bool:
    """
    Проверить, включён ли Google Drive адаптер.

    Returns:
        True если BUSINESS_DRIVE_ENABLED=true и credentials доступны
    """
    if os.getenv("BUSINESS_DRIVE_ENABLED", "false").lower() != "true":
        return False
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    return bool(creds_file and os.path.exists(creds_file))


def check_configuration() -> dict:
    """
    Проверить конфигурацию Google Drive.

    Returns:
        {ok: bool, issues: list[str], info: dict}
    """
    issues = []
    info = {}

    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    if not creds_file:
        issues.append("GOOGLE_CREDENTIALS_FILE не задан в .env")
    elif not os.path.exists(creds_file):
        issues.append(f"Файл {creds_file} не найден")
    else:
        try:
            with open(creds_file) as f:
                data = json.load(f)
            info["service_account"] = data.get("client_email", "?")
            info["project_id"] = data.get("project_id", "?")
        except Exception as e:
            issues.append(f"Ошибка чтения credentials: {e}")

    if os.getenv("BUSINESS_DRIVE_ENABLED", "false").lower() != "true":
        issues.append("BUSINESS_DRIVE_ENABLED != true (Drive отключён)")

    root_folder = os.getenv("DRIVE_ROOT_FOLDER_ID", "")
    info["root_folder_id"] = root_folder or "(корень Drive)"

    return {
        "ok":     len(issues) == 0,
        "issues": issues,
        "info":   info,
    }


# ─────────────────────────────────────────────────────────────
# Операции с папками
# ─────────────────────────────────────────────────────────────

def _is_shared_drive() -> bool:
    """Проверить, используется ли Shared Drive (GDRIVE_IS_SHARED_DRIVE=true)."""
    return os.getenv("GDRIVE_IS_SHARED_DRIVE", "false").lower() == "true"


def find_folder(
    service,
    name: str,
    parent_id: Optional[str] = None,
) -> Optional[str]:
    """
    Найти папку по имени в указанном родителе.

    Args:
        service:   Drive API service
        name:      Имя папки
        parent_id: ID родительской папки (None = корень)

    Returns:
        ID папки если найдена, None если не существует
    """
    name_escaped = name.replace("'", "\\'")
    query = (
        f"mimeType='{DRIVE_FOLDER_MIME}' "
        f"and name='{name_escaped}' "
        f"and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    kwargs: dict = {
        "q":      query,
        "fields": "files(id, name)",
        "pageSize": 10,
    }
    if _is_shared_drive():
        kwargs["supportsAllDrives"]         = True
        kwargs["includeItemsFromAllDrives"] = True
        kwargs["corpora"]                   = "allDrives"

    result = service.files().list(**kwargs).execute()

    files = result.get("files", [])
    if files:
        return files[0]["id"]
    return None


def create_folder(
    service,
    name: str,
    parent_id: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """
    Создать папку в Google Drive.

    Идемпотентно: если папка существует — вернёт её ID.

    Args:
        service:   Drive API service
        name:      Имя папки
        parent_id: ID родительской папки (None = корень)
        dry_run:   True = только логировать, не создавать

    Returns:
        ID созданной/найденной папки
    """
    # Проверяем, существует ли уже
    existing_id = find_folder(service, name, parent_id)
    if existing_id:
        log.debug(f"Папка уже существует: '{name}' → {existing_id}")
        return existing_id

    if dry_run:
        fake_id = f"DRY_RUN_{name.replace(' ', '_')}"
        log.info(f"[dry_run] Создать папку: '{name}' (parent={parent_id}) → {fake_id}")
        return fake_id

    metadata: dict = {
        "name":     name,
        "mimeType": DRIVE_FOLDER_MIME,
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    create_kwargs: dict = {"body": metadata, "fields": "id"}
    if _is_shared_drive():
        create_kwargs["supportsAllDrives"] = True

    folder = service.files().create(**create_kwargs).execute()

    folder_id = folder["id"]
    log.info(f"Создана папка: '{name}' → {folder_id}")
    return folder_id


def get_or_create_folder(
    service,
    name: str,
    parent_id: Optional[str] = None,
    dry_run: bool = False,
) -> tuple[str, bool]:
    """
    Получить ID папки или создать новую.

    Returns:
        (folder_id, was_created)
    """
    existing_id = find_folder(service, name, parent_id)
    if existing_id:
        return existing_id, False

    new_id = create_folder(service, name, parent_id, dry_run=dry_run)
    return new_id, True


def get_folder_url(folder_id: str) -> str:
    """Вернуть URL папки Google Drive."""
    return f"https://drive.google.com/drive/folders/{folder_id}"


def get_file_url(file_id: str) -> str:
    """Вернуть URL файла Google Drive."""
    return f"https://drive.google.com/file/d/{file_id}/view"


def get_file_metadata(service, file_id: str) -> dict:
    """
    Phase 15A: read-only метаданные существующего Drive-файла для
    /registerdoc — НЕ перемещает и не изменяет файл, только читает.

    Returns:
        {"ok": True, "name": str, "mime_type": str, "trashed": bool,
         "web_view_link": str}
        или
        {"ok": False, "error": str}
    """
    try:
        meta = service.files().get(
            fileId=file_id,
            fields="id,name,mimeType,webViewLink,trashed",
        ).execute()
        return {
            "ok": True,
            "name": meta.get("name", ""),
            "mime_type": meta.get("mimeType", ""),
            "trashed": meta.get("trashed", False),
            "web_view_link": meta.get("webViewLink", ""),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Создание структуры бизнеса
# ─────────────────────────────────────────────────────────────

def create_business_structure(
    service,
    business_name: str,
    parent_folder_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Создать стандартную структуру папок для бизнеса.

    Структура:
    [business_name]/
    ├── 01 Стратегия
    ├── 02 Услуги
    ├── ...
    └── 12 Архив

    Args:
        service:          Drive API service
        business_name:    Название бизнеса (создаётся корневая папка)
        parent_folder_id: Куда поместить корневую папку
                          (если None — берётся DRIVE_ROOT_FOLDER_ID из .env)
        dry_run:          True = не создавать реально

    Returns:
        {
          "root_id":    str,
          "root_url":   str,
          "subfolders": {slug: {"id": str, "url": str}},
          "created":    bool,  # False если папка уже существовала
          "dry_run":    bool,
        }
    """
    root_parent = parent_folder_id or os.getenv("DRIVE_ROOT_FOLDER_ID", "") or None

    # Создаём корневую папку бизнеса
    root_id, root_created = get_or_create_folder(
        service, business_name, root_parent, dry_run=dry_run
    )

    subfolders: dict[str, dict] = {}
    for folder_name in BUSINESS_FOLDER_STRUCTURE:
        fid, _ = get_or_create_folder(service, folder_name, root_id, dry_run=dry_run)
        slug = folder_name.lower().replace(" ", "_")
        subfolders[slug] = {
            "name": folder_name,
            "id":   fid,
            "url":  get_folder_url(fid),
        }

    log.info(
        f"create_business_structure: '{business_name}' → {root_id} "
        f"({len(subfolders)} подпапок)"
    )

    return {
        "root_id":    root_id,
        "root_url":   get_folder_url(root_id),
        "subfolders": subfolders,
        "created":    root_created,
        "dry_run":    dry_run,
    }


def create_client_folder(
    service,
    client_name: str,
    business_root_id: str,
    service_name: str = "",
    dry_run: bool = False,
) -> dict:
    """
    Создать папку клиента внутри папки «06 Клиенты» бизнеса.

    Структура:
    [business_name]/
    └── 06 Клиенты/
        └── [client_name]/
            ├── 01 Документы клиента
            ├── 02 Наши документы
            ├── 03 Переписка
            ├── 04 Финансы
            └── 05 Архив

    Returns:
        {client_root_id, client_root_url, subfolders}
    """
    # Найти или создать «06 Клиенты»
    clients_id, _ = get_or_create_folder(
        service, "06 Клиенты", business_root_id, dry_run=dry_run
    )

    # Создать папку клиента (имя + услуга если задана)
    folder_name = (
        f"{client_name} — {service_name}" if service_name else client_name
    )
    client_root_id, created = get_or_create_folder(
        service, folder_name, clients_id, dry_run=dry_run
    )

    subfolders = {}
    for sub in CLIENT_FOLDER_STRUCTURE:
        fid, _ = get_or_create_folder(service, sub, client_root_id, dry_run=dry_run)
        slug = sub.lower().replace(" ", "_")
        subfolders[slug] = {"name": sub, "id": fid, "url": get_folder_url(fid)}

    return {
        "client_root_id":  client_root_id,
        "client_root_url": get_folder_url(client_root_id),
        "clients_folder_id": clients_id,
        "subfolders":      subfolders,
        "created":         created,
        "dry_run":         dry_run,
    }


def create_case_folder(
    service,
    case_name: str,
    client_root_id: str,
    dry_run: bool = False,
) -> dict:
    """
    Создать папку кейса внутри папки клиента.
    Используется для конкретной дорожной карты (Roadmap).

    Структура:
    [client_name]/
    └── [case_name]/
        ├── 01 Исходные документы
        ├── 02 Промежуточные
        ├── 03 Готовые документы
        └── 04 Финансы кейса

    Returns:
        {case_root_id, case_root_url, subfolders}
    """
    case_root_id, created = get_or_create_folder(
        service, case_name, client_root_id, dry_run=dry_run
    )

    subfolders = {}
    for sub in CASE_FOLDER_STRUCTURE:
        fid, _ = get_or_create_folder(service, sub, case_root_id, dry_run=dry_run)
        slug = sub.lower().replace(" ", "_")
        subfolders[slug] = {"name": sub, "id": fid, "url": get_folder_url(fid)}

    return {
        "case_root_id":  case_root_id,
        "case_root_url": get_folder_url(case_root_id),
        "subfolders":    subfolders,
        "created":       created,
        "dry_run":       dry_run,
    }


# ─────────────────────────────────────────────────────────────
# Загрузка файлов
# ─────────────────────────────────────────────────────────────

def upload_file(
    service,
    local_path: str,
    folder_id: str,
    filename: Optional[str] = None,
    mime_type: str = "application/octet-stream",
    dry_run: bool = False,
) -> dict:
    """
    Загрузить файл в папку Google Drive.

    Args:
        service:    Drive API service
        local_path: Путь к локальному файлу
        folder_id:  ID папки назначения
        filename:   Имя файла в Drive (если отличается от локального)
        mime_type:  MIME-тип файла
        dry_run:    True = не загружать реально

    Returns:
        {file_id, file_url, filename, dry_run}
    """
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Файл не найден: {local_path}")

    fname = filename or os.path.basename(local_path)

    if dry_run:
        fake_id = f"DRY_FILE_{fname.replace(' ', '_')}"
        log.info(f"[dry_run] Загрузить файл: '{fname}' → {folder_id}")
        return {
            "file_id":  fake_id,
            "file_url": get_file_url(fake_id),
            "filename": fname,
            "dry_run":  True,
        }

    try:
        from googleapiclient.http import MediaFileUpload

        metadata = {
            "name":    fname,
            "parents": [folder_id],
        }
        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
        ).execute()

        file_id = result["id"]
        log.info(f"Файл загружен: '{fname}' → {file_id}")
        return {
            "file_id":  file_id,
            "file_url": get_file_url(file_id),
            "filename": fname,
            "dry_run":  False,
        }
    except ImportError:
        raise RuntimeError("googleapiclient не установлен")


# ─────────────────────────────────────────────────────────────
# Полный флоу: создать структуру для нового клиента
# ─────────────────────────────────────────────────────────────

def setup_client_workspace(
    service,
    business_name:    str,
    business_root_id: str,
    client_name:      str,
    service_name:     str = "",
    roadmap_id:       str = "",
    dry_run:          bool = False,
) -> dict:
    """
    Создать полное рабочее пространство для нового клиента.

    Создаёт:
    [business_name]/
    └── 06 Клиенты/
        └── [client_name] — [service_name]/
            ├── 01 Документы клиента
            ├── 02 Наши документы
            ├── 03 Переписка
            ├── 04 Финансы
            └── 05 Архив/
                └── [roadmap_id] (если задан)

    Returns:
        полный dict с ID и URL всех созданных папок
    """
    client_result = create_client_folder(
        service, client_name, business_root_id, service_name, dry_run=dry_run
    )

    result = {
        "business_name":   business_name,
        "business_root_id": business_root_id,
        "client_name":     client_name,
        "service_name":    service_name,
        "client_root_id":  client_result["client_root_id"],
        "client_root_url": client_result["client_root_url"],
        "subfolders":      client_result["subfolders"],
        "case_folder":     None,
        "dry_run":         dry_run,
    }

    # Если задан roadmap_id — создать папку кейса в «05 Архив»
    if roadmap_id:
        archive_sub = client_result["subfolders"].get("05_архив", {})
        archive_id = archive_sub.get("id", client_result["client_root_id"])
        case_result = create_case_folder(
            service, roadmap_id, archive_id, dry_run=dry_run
        )
        result["case_folder"] = case_result

    log.info(
        f"setup_client_workspace: {client_name} → {client_result['client_root_url']}"
    )
    return result


# ─────────────────────────────────────────────────────────────
# Часть 1–2: Поиск корневой папки Business Core
# ─────────────────────────────────────────────────────────────

def find_business_root_folder(folder_name: str = "BUSINESS_CORE_DRIVE") -> dict:
    """
    Найти корневую папку Business Core в Google Drive по имени.

    Ищет во всех доступных дисках (включая Shared Drive).
    Папка должна быть расшарена для service account как Редактор.

    Args:
        folder_name: имя папки (default: "BUSINESS_CORE_DRIVE")

    Returns:
        {"id": str, "name": str, "webViewLink": str}

    Raises:
        RuntimeError: если папка не найдена, или найдено несколько
    """
    service = get_drive_service()
    name_escaped = folder_name.replace("'", "\\'")
    query = (
        f"mimeType='{DRIVE_FOLDER_MIME}' "
        f"and name='{name_escaped}' "
        f"and trashed=false"
    )

    kwargs: dict = {
        "q":      query,
        "fields": "files(id, name, webViewLink)",
        "pageSize": 20,
    }
    # Всегда ищем во всех дисках — папка может быть в Shared Drive
    kwargs["supportsAllDrives"]         = True
    kwargs["includeItemsFromAllDrives"] = True
    kwargs["corpora"]                   = "allDrives"

    result = service.files().list(**kwargs).execute()
    files  = result.get("files", [])

    if not files:
        raise RuntimeError(
            f"Папка '{folder_name}' не найдена в Google Drive.\n"
            f"Создай папку с именем '{folder_name}' и дай доступ service account "
            f"как Редактор:\n"
            f"  {_read_service_account_email()}"
        )

    if len(files) > 1:
        ids_list = "\n".join(f"  • {f['name']} → {f['id']}" for f in files)
        raise RuntimeError(
            f"Найдено {len(files)} папки с именем '{folder_name}':\n{ids_list}\n\n"
            f"Укажи нужный ID вручную в .env:\n"
            f"  GDRIVE_BIZ_ROOT_FOLDER_ID=<ID папки>"
        )

    folder = files[0]
    log.info(f"find_business_root_folder: найдена '{folder_name}' → {folder['id']}")
    return {
        "id":          folder["id"],
        "name":        folder["name"],
        "webViewLink": folder.get("webViewLink", get_folder_url(folder["id"])),
    }


def _read_service_account_email() -> str:
    """Прочитать email service account из credentials файла."""
    try:
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
        if creds_file and os.path.exists(creds_file):
            with open(creds_file) as f:
                return json.load(f).get("client_email", "<service_account>")
    except Exception:
        pass
    return "<service_account>"


def ensure_biz_root_folder_id(
    folder_name: str = "BUSINESS_CORE_DRIVE",
    ask_confirmation: bool = True,
) -> str:
    """
    Получить ID корневой папки Business Core.

    1. Если GDRIVE_BIZ_ROOT_FOLDER_ID задан в .env — возвращает его.
    2. Иначе ищет папку folder_name в Drive.
    3. Если нашёл — предлагает записать в .env и возвращает ID.

    Args:
        folder_name:       Имя папки для поиска (default: "BUSINESS_CORE_DRIVE")
        ask_confirmation:  Показать предупреждение перед записью в .env (default: True)

    Returns:
        folder_id: str

    Raises:
        RuntimeError: если папка не найдена
    """
    # Шаг 1: уже есть в .env?
    existing = os.getenv("GDRIVE_BIZ_ROOT_FOLDER_ID", "").strip()
    if existing:
        log.debug(f"ensure_biz_root_folder_id: из .env → {existing}")
        return existing

    # Шаг 2: ищем в Drive
    log.info(f"GDRIVE_BIZ_ROOT_FOLDER_ID не задан, ищем '{folder_name}' в Drive...")
    folder_info = find_business_root_folder(folder_name)
    folder_id   = folder_info["id"]
    folder_url  = folder_info.get("webViewLink", get_folder_url(folder_id))

    # Шаг 3: предлагаем записать в .env
    env_line = f"GDRIVE_BIZ_ROOT_FOLDER_ID={folder_id}"

    if ask_confirmation:
        print(f"\n✅ Найдена папка '{folder_name}':")
        print(f"   ID:  {folder_id}")
        print(f"   URL: {folder_url}")
        print(f"\n📝 Будет добавлено в .env:")
        print(f"   {env_line}")
        print("\nПодтвердить запись? (yes/no): ", end="", flush=True)
        answer = input().strip().lower()
        if answer not in ("yes", "y", "да"):
            print("Отменено. ID не записан в .env.")
            return folder_id

    # Записываем в .env (не меняем остальное)
    _append_to_env(env_line)
    # Обновляем текущий процесс
    os.environ["GDRIVE_BIZ_ROOT_FOLDER_ID"] = folder_id
    log.info(f"ensure_biz_root_folder_id: записано в .env → {folder_id}")
    print(f"✅ Записано в .env: {env_line}")

    return folder_id


def _append_to_env(line: str, env_path: str = ".env") -> None:
    """Добавить строку в .env файл (не перезаписывает существующие переменные)."""
    if not os.path.exists(env_path):
        log.warning(f".env файл не найден: {env_path}")
        return

    # Читаем текущее содержимое
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Проверяем, нет ли уже такой переменной
    var_name = line.split("=")[0].strip()
    if var_name in content:
        log.debug(f"_append_to_env: '{var_name}' уже есть в .env, не добавляем")
        return

    # Добавляем в конец
    separator = "\n" if not content.endswith("\n") else ""
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"{separator}{line}\n")

    log.info(f"_append_to_env: добавлено '{line}'")


# ─────────────────────────────────────────────────────────────
# Часть 3: Высокоуровневые обёртки (не требуют service объекта)
# ─────────────────────────────────────────────────────────────

def create_business_folder_structure(
    biz_id:        str,
    biz_name:      str,
    dry_run:       bool = False,
    root_folder_id: Optional[str] = None,
) -> dict:
    """
    Создать структуру папок бизнеса внутри BUSINESS_CORE_DRIVE (или явного root).

    Создаёт:
    <root>/
    └── {biz_id}_{biz_name}/
        ├── 01 Стратегия ... 12 Архив

    Args:
        biz_id:          ID бизнеса (например "BIZ-001")
        biz_name:        Название бизнеса (например "Узаконение")
        dry_run:         True = только логировать
        root_folder_id:  Явный root folder ID (Phase 6A per-biz Drive root).
                         Если None — используется GDRIVE_BIZ_ROOT_FOLDER_ID из .env.

    Returns:
        {
          "business_folder_id":  str,
          "business_folder_url": str,
          "folders":             {"01 Стратегия": {"id": str, "url": str}, ...},
          "dry_run":             bool,
        }
    """
    # Phase 6A: если root передан явно — используем его;
    # иначе старый путь через ensure_biz_root_folder_id()
    if root_folder_id:
        root_id = root_folder_id
        log.debug(f"create_business_folder_structure: using explicit root {root_id}")
    else:
        root_id = ensure_biz_root_folder_id(ask_confirmation=False)
    service   = get_drive_service()
    biz_label = f"{biz_id}_{biz_name}"

    result = create_business_structure(
        service,
        business_name=biz_label,
        parent_folder_id=root_id,
        dry_run=dry_run,
    )

    # Переформатируем в запрошенный формат
    folders = {
        info["name"]: {"id": info["id"], "url": info["url"]}
        for info in result["subfolders"].values()
    }

    return {
        "business_folder_id":  result["root_id"],
        "business_folder_url": result["root_url"],
        "folders":             folders,
        "dry_run":             dry_run,
    }


def setup_biz_client_folder(
    biz_id:        str,
    biz_name:      str,
    client_name:   str,
    roadmap_id:    Optional[str] = None,
    dry_run:       bool = False,
    root_folder_id: Optional[str] = None,
) -> dict:
    """
    Создать папку клиента внутри {biz_id}_{biz_name}/06 Клиенты/.

    Структура:
    <root>/
    └── {biz_id}_{biz_name}/
        └── 06 Клиенты/
            └── {client_name}_{roadmap_id}/   (roadmap_id опционально)
                ├── 01 Документы от клиента
                ├── 02 Документы наши
                ├── 03 Переписка
                ├── 04 Материалы
                └── 05 Архив

    Args:
        biz_id:          ID бизнеса
        biz_name:        Название бизнеса
        client_name:     ФИО клиента
        roadmap_id:      ID карты (опционально)
        dry_run:         True = только логировать
        root_folder_id:  Явный root folder ID (Phase 6A per-biz Drive root).
                         Если None — используется GDRIVE_BIZ_ROOT_FOLDER_ID из .env.

    Returns:
        {client_folder_id, client_folder_url, subfolders, dry_run}
    """
    if root_folder_id:
        root_id = root_folder_id
        log.debug(f"setup_biz_client_folder: using explicit root {root_id}")
    else:
        root_id = ensure_biz_root_folder_id(ask_confirmation=False)
    service   = get_drive_service()
    biz_label = f"{biz_id}_{biz_name}"

    # Находим или создаём папку бизнеса
    biz_folder_id, _ = get_or_create_folder(service, biz_label, root_id, dry_run=dry_run)

    # Папка клиента: {client_name}_{roadmap_id} или просто {client_name}
    folder_name = f"{client_name}_{roadmap_id}" if roadmap_id else client_name

    # Находим "06 Клиенты"
    clients_folder_id, _ = get_or_create_folder(
        service, "06 Клиенты", biz_folder_id, dry_run=dry_run
    )

    # Создаём папку клиента
    client_folder_id, _ = get_or_create_folder(
        service, folder_name, clients_folder_id, dry_run=dry_run
    )

    # Структура внутри клиента (соответствует запросу)
    client_subfolders_names = [
        "01 Документы от клиента",
        "02 Документы наши",
        "03 Переписка",
        "04 Материалы",
        "05 Архив",
    ]
    subfolders = {}
    for sub in client_subfolders_names:
        fid, _ = get_or_create_folder(service, sub, client_folder_id, dry_run=dry_run)
        subfolders[sub] = {"id": fid, "url": get_folder_url(fid)}

    client_url = get_folder_url(client_folder_id)
    log.info(f"setup_biz_client_folder: {client_name} → {client_url}")

    return {
        "client_folder_id":  client_folder_id,
        "client_folder_url": client_url,
        "subfolders":        subfolders,
        "dry_run":           dry_run,
    }


# ─────────────────────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────────────────────

def list_folder_contents(
    service,
    folder_id: str,
    include_files: bool = True,
) -> list[dict]:
    """
    Список содержимого папки.

    Returns:
        list[{id, name, mimeType, webViewLink}]
    """
    query = f"'{folder_id}' in parents and trashed=false"
    if not include_files:
        query += f" and mimeType='{DRIVE_FOLDER_MIME}'"

    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, webViewLink, size)",
        pageSize=100,
        orderBy="name",
    ).execute()

    return result.get("files", [])


def get_file_id_from_input(value: str) -> str:
    """
    Phase 15A: извлечь Drive file ID из URL или вернуть значение как есть,
    если это уже голый ID (без '/').

    Поддерживает:
    - https://drive.google.com/file/d/FILE_ID/view
    - https://drive.google.com/open?id=FILE_ID
    - голый FILE_ID
    """
    import re
    value = value.strip()
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", value)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", value)
    if m:
        return m.group(1)
    return value


def get_folder_id_from_url(url: str) -> Optional[str]:
    """
    Извлечь folder_id из URL Google Drive.

    Поддерживает форматы:
    - https://drive.google.com/drive/folders/FOLDER_ID
    - https://drive.google.com/drive/u/0/folders/FOLDER_ID
    """
    import re
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def format_structure_report(result: dict) -> str:
    """
    Отформатировать результат create_business_structure() для отображения.
    """
    mode = " [DRY RUN]" if result.get("dry_run") else ""
    lines = [
        f"📁 *Google Drive структура{mode}*",
        f"🔗 [Открыть папку]({result['root_url']})",
        "",
        f"*Подпапки ({len(result['subfolders'])}):*",
    ]
    for slug, info in result["subfolders"].items():
        lines.append(f"  📂 {info['name']}")

    return "\n".join(lines)


def format_client_report(result: dict) -> str:
    """
    Отформатировать результат setup_client_workspace() для Telegram.
    """
    mode = " [DRY RUN]" if result.get("dry_run") else ""
    action = "Создано" if result.get("subfolders") else "Уже существует"

    lines = [
        f"📁 *Рабочее пространство клиента{mode}*",
        f"👤 {result['client_name']}",
        f"🏢 {result['business_name']}",
    ]
    if result.get("service_name"):
        lines.append(f"🛠 {result['service_name']}")

    lines.extend([
        f"",
        f"🔗 [Открыть папку]({result['client_root_url']})",
        f"",
        f"*{action} папок: {len(result.get('subfolders', {}))}*",
    ])

    if result.get("case_folder"):
        cf = result["case_folder"]
        lines.append(f"📋 Кейс: [открыть]({cf['case_root_url']})")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Phase 7A: Object folder (OBJECT_REGISTRY)
# ─────────────────────────────────────────────────────────────

def _safe_folder_name(s: str, max_len: int = 60) -> str:
    """Безопасное имя папки: убрать / \\ : * ? \" < > |, обрезать."""
    import re
    safe = re.sub(r'[/\\:*?"<>|]', "_", s.strip())
    safe = re.sub(r"\s+", " ", safe)
    return safe[:max_len].strip()


def create_object_folder(
    biz_id:           str,
    biz_name:         str,
    client_id:        str,
    client_name:      str,
    obj_id:           str,
    city:             str,
    address:          str,
    object_type:      str = "",
    client_folder_id: Optional[str] = None,
    root_folder_id:   Optional[str] = None,
    dry_run:          bool = False,
) -> dict:
    """
    Создать папку объекта недвижимости в Google Drive.

    Структура:
    <root>/
    └── {biz_id}_{biz_name}/
        └── 06 Клиенты/
            └── {client_name}/
                └── {obj_id}_{city}_{address_slug}/
                    ├── 01 Документы от клиента
                    ├── 02 Документы наши
                    ├── 03 Переписка
                    ├── 04 Фото и медиа
                    └── 05 Архив

    Если client_folder_id передан — создаёт папку объекта внутри него напрямую.
    Если не передан — находит/создаёт бизнес-папку и папку клиента.

    Args:
        biz_id:           ID бизнеса
        biz_name:         Название бизнеса
        client_id:        PRS-ID клиента
        client_name:      ФИО клиента
        obj_id:           OBJ-ID объекта
        city:             Город
        address:          Адрес
        object_type:      Тип объекта (опционально)
        client_folder_id: Готовый ID папки клиента (опционально, ускоряет)
        root_folder_id:   Drive root (Phase 6C per-biz root или глобальный)
        dry_run:          True = только логировать

    Returns:
        {
            "ok":         bool,
            "folder_id":  str,
            "folder_url": str,
            "error":      str | None,
        }
    """
    try:
        service = get_drive_service()

        # Имя папки объекта: "{obj_id}_{city}_{address_slug}"
        addr_slug    = _safe_folder_name(f"{address[:40]}")
        type_suffix  = f"_{_safe_folder_name(object_type)}" if object_type else ""
        folder_name  = _safe_folder_name(f"{obj_id}_{city}_{addr_slug}{type_suffix}")

        # Получить/создать папку клиента
        if client_folder_id:
            parent_for_obj = client_folder_id
        else:
            # Нужен root
            if root_folder_id:
                root_id = root_folder_id
            else:
                root_id = ensure_biz_root_folder_id(ask_confirmation=False)

            biz_label = f"{biz_id}_{biz_name}"
            biz_folder_id, _   = get_or_create_folder(service, biz_label,     root_id,       dry_run=dry_run)
            clients_folder_id, _ = get_or_create_folder(service, "06 Клиенты", biz_folder_id, dry_run=dry_run)
            parent_for_obj, _  = get_or_create_folder(service, client_name,   clients_folder_id, dry_run=dry_run)

        # Создаём папку объекта (идемпотентно)
        obj_folder_id, _ = get_or_create_folder(service, folder_name, parent_for_obj, dry_run=dry_run)

        # Стандартные подпапки объекта
        for sub in [
            "01 Документы от клиента",
            "02 Документы наши",
            "03 Переписка",
            "04 Фото и медиа",
            "05 Архив",
        ]:
            get_or_create_folder(service, sub, obj_folder_id, dry_run=dry_run)

        obj_url = get_folder_url(obj_folder_id)
        log.info(f"create_object_folder: {obj_id} → {obj_url}")

        return {
            "ok":         True,
            "folder_id":  obj_folder_id,
            "folder_url": obj_url,
            "error":      None,
        }

    except Exception as exc:
        log.warning(f"create_object_folder({obj_id}) error: {exc}")
        return {"ok": False, "folder_id": "", "folder_url": "", "error": str(exc)}
