"""
Google Drive Adapter — создание и управление структурой папок бизнеса.

Использует существующий GOOGLE_CREDENTIALS_FILE из .env (тот же service account,
что и для Google Sheets). Service account уже авторизован в вашем Drive.

Идемпотентность: все операции проверяют наличие папки перед созданием.
  create_folder()  →  ищет папку, создаёт только если не существует.

Режим dry_run=True: все операции логируются, но не выполняются реально.
  Используется в тестах и при отладке.

Требует:
  pip install google-api-python-client google-auth

Переменные .env:
  GOOGLE_CREDENTIALS_FILE = path/to/service_account.json
  DRIVE_ROOT_FOLDER_ID    = ID корневой папки (опционально)
                            Если не задан — папки создаются в корне Drive
  BUSINESS_DRIVE_ENABLED  = true/false
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

    result = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=10,
    ).execute()

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

    folder = service.files().create(
        body=metadata,
        fields="id",
    ).execute()

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
