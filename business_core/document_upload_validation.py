"""
Document Upload Validation — Phase 37F.1 (ADR-020 §12).

Small, stateless, read-only validation helper. Called ONLY by
business_core.business_builder — never imported directly by
telegram_handlers.py, so upload-safety policy stays orchestration-
owned, not Telegram-owned, exactly like every other Document policy
decision in this domain.

No Sheets access, no Drive access, no network access, no persistence.
Pure functions over already-available metadata (filename, mime_type,
size) — the same metadata Telegram already has before performing any
Drive upload, so validation can run before that upload, never after.

Storage acceptance and AI-analysis support are deliberately two
separate axes (ADR-020 §12): a document may be accepted for storage
even when business_core.document_intelligence cannot analyze it (the
existing production RTF Document is exactly this case) — AI support
is never a precondition for storage.
"""

from __future__ import annotations

MAX_DOCUMENT_FILENAME_LENGTH = 255

# Telegram Bot API's own ceiling for a bot downloading a file via
# getFile — used here as the one explicit, deterministic maximum
# rather than inventing an unrelated arbitrary number.
MAX_DOCUMENT_FILE_SIZE_BYTES = 20 * 1024 * 1024

# Storage-level block list: executable/script/archive-of-executables
# types that must never be accepted into DOCUMENT_REGISTRY regardless
# of AI-analysis support. This is deliberately narrow and explicit —
# an allow-by-default, block-by-exception policy — so ordinary
# business document formats (docx, xlsx, rtf, images, pdf, plain
# text, ...) are never accidentally rejected.
_DANGEROUS_STORAGE_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".vbs", ".vbe",
    ".js", ".jse", ".jar", ".sh", ".ps1", ".psm1", ".app", ".dll",
    ".apk", ".dmg", ".bin", ".msix", ".gadget", ".wsf",
})

_DANGEROUS_STORAGE_MIME_TYPES = frozenset({
    "application/x-msdownload", "application/x-executable",
    "application/x-sh", "application/x-bat",
    "application/vnd.microsoft.portable-executable",
    "application/java-archive", "application/x-msi",
    "application/x-dosexec", "application/x-elf",
})


def _file_extension(file_name: str) -> str:
    name = file_name.strip()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def validate_filename(file_name: str) -> dict:
    """
    Returns {"ok": bool, "code": str, "error": str | None}.

    Deterministic checks only — never guesses, never repairs. Filename
    is validated for storage safety only; it is never used as dedup
    identity (that remains Drive File ID's exclusive role, ADR-020 §10).
    """
    name = (file_name or "").strip()

    if not name:
        return {"ok": False, "code": "INVALID_DOCUMENT_FILENAME", "error": "Имя файла не указано"}

    if len(name) > MAX_DOCUMENT_FILENAME_LENGTH:
        return {
            "ok": False, "code": "INVALID_DOCUMENT_FILENAME",
            "error": f"Имя файла длиннее {MAX_DOCUMENT_FILENAME_LENGTH} символов",
        }

    if any(ord(ch) < 32 for ch in name):
        return {"ok": False, "code": "INVALID_DOCUMENT_FILENAME", "error": "Имя файла содержит управляющие символы"}

    if "/" in name or "\\" in name:
        return {"ok": False, "code": "INVALID_DOCUMENT_FILENAME", "error": "Имя файла содержит разделители пути"}

    if ".." in name:
        return {"ok": False, "code": "INVALID_DOCUMENT_FILENAME", "error": "Имя файла содержит недопустимую последовательность '..'"}

    return {"ok": True, "code": "", "error": None}


def validate_size(file_size: int | None) -> dict:
    """
    Returns {"ok": bool, "code": str, "error": str | None}.

    file_size=None (metadata unavailable) is treated as "cannot
    validate size here" — ok=True, since this check runs on Telegram-
    supplied size before any Drive interaction, and absent metadata
    must never itself become a rejection reason for this specific
    check (it may still be caught later by the post-upload metadata
    completeness check, DOCUMENT_FILE_METADATA_INVALID).
    """
    if file_size is None:
        return {"ok": True, "code": "", "error": None}

    if file_size <= 0:
        return {"ok": False, "code": "DOCUMENT_TOO_LARGE", "error": "Некорректный размер файла (0 или отрицательный)"}

    if file_size > MAX_DOCUMENT_FILE_SIZE_BYTES:
        return {
            "ok": False, "code": "DOCUMENT_TOO_LARGE",
            "error": f"Файл превышает максимальный размер {MAX_DOCUMENT_FILE_SIZE_BYTES} байт",
        }

    return {"ok": True, "code": "", "error": None}


def classify_storage_type(file_name: str, mime_type: str) -> dict:
    """
    Returns {"ok": bool, "code": str, "error": str | None, "analysis_supported": bool}.

    ok=False only for storage-level danger (executable/script/archive-
    of-executables). Everything else is ok=True — analysis_supported
    reflects business_core.document_intelligence.is_supported_mime_type()
    (reused, not duplicated) purely as informational metadata; it never
    blocks storage.
    """
    from business_core.document_intelligence import is_supported_mime_type

    normalized_mime = (mime_type or "").strip().lower()
    ext = _file_extension(file_name or "")

    if normalized_mime in _DANGEROUS_STORAGE_MIME_TYPES or ext in _DANGEROUS_STORAGE_EXTENSIONS:
        return {
            "ok": False, "code": "UNSUPPORTED_DOCUMENT_STORAGE_TYPE",
            "error": f"Тип файла не поддерживается для хранения (mime={normalized_mime or '—'}, ext={ext or '—'})",
            "analysis_supported": False,
        }

    return {"ok": True, "code": "", "error": None, "analysis_supported": is_supported_mime_type(normalized_mime)}


def validate_upload_request(file_name: str, mime_type: str, file_size: int | None = None) -> dict:
    """
    Single entry point — combines filename, size, and storage-type
    checks in that order, all before any Drive call. Returns:

        {"ok": bool, "code": str, "error": str | None, "analysis_supported": bool}

    ok=True with code="DOCUMENT_ANALYSIS_UNSUPPORTED" means: storage is
    allowed, but business_core.document_intelligence cannot analyze
    this MIME type — never a rejection, purely informational (ADR-020
    §12: AI support is never a prerequisite for storage).
    ok=True with code="" (mapped to DOCUMENT_UPLOAD_VALIDATED by the
    caller) means: fully supported for both storage and analysis.
    """
    filename_result = validate_filename(file_name)
    if not filename_result["ok"]:
        return {**filename_result, "analysis_supported": False}

    size_result = validate_size(file_size)
    if not size_result["ok"]:
        return {**size_result, "analysis_supported": False}

    storage_result = classify_storage_type(file_name, mime_type)
    if not storage_result["ok"]:
        return storage_result

    if not storage_result["analysis_supported"]:
        return {
            "ok": True, "code": "DOCUMENT_ANALYSIS_UNSUPPORTED", "error": None,
            "analysis_supported": False,
        }

    return {"ok": True, "code": "", "error": None, "analysis_supported": True}
