"""
Phase 16A: Document Intelligence Foundation.

Scope: enrich an already-registered DOCUMENT_REGISTRY row with AI-derived
metadata (detected document type, summary, bounded text preview, keywords,
extracted structured fields, a suggested — never authoritative — Document
Template ID). Analysis runs asynchronously (Telegram job_queue) AFTER
/uploaddoc's transaction (upload -> Drive metadata -> DOCUMENT_REGISTRY
write -> post-write verification -> success reply) has already fully
completed. Analysis is enrichment only:

    An analysis error must NEVER:
      - roll back the upload;
      - delete the Drive file;
      - remove the DOCUMENT_REGISTRY row;
      - change the upload result from success to failure.

Storage: a separate, purely additive DOCUMENT_CONTENT sheet (see
business_core/sheets.py BUSINESS_HEADERS["document_content"]).
DOCUMENT_REGISTRY's schema is never touched. Extracted text is
intentionally NOT stored unbounded (Google Sheets has a 50k-char/cell
limit) — only a bounded Text Preview. A future DOCUMENT_CHUNKS sheet can
hold full text later without any change to this module's schema or to
DOCUMENT_REGISTRY.

Isolation: this module never imports telegram_bot.py and never reuses
GTD Core's global `ai_client` — it builds its own local anthropic.Anthropic
client, exactly the pattern already established in
business_core/business_router.py's AI-routing call.

Idempotency: exactly one DOCUMENT_CONTENT row per Document ID. The real
safety mechanism is inside analyze_document() itself — a synchronous
check-then-claim sequence (read current status, decide, write
"processing") with no `await`/network-yielding point in between within
the same call. Since this whole codebase runs Sheets/Drive/Anthropic
calls synchronously inside a single-process asyncio event loop (same as
every other Business Core write path), two near-simultaneous triggers
(e.g. auto-enqueue-after-upload + a manual /analyzedoc) can only ever
interleave at an `await` boundary in the OUTER async job callback, never
inside this synchronous function body — so the second trigger's call to
analyze_document() always observes whatever terminal/processing state the
first call already left behind, and never creates a second row.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

CONTENT_STATUS_VALUES = ("pending", "processing", "completed", "failed", "unsupported")

# Phase 16A v1 scope — zero new dependencies. Only formats Claude's Messages
# API understands natively (PDF via a "document" content block, these four
# image types via an "image" content block, plain text via a "text" block).
# RTF is deliberately NOT included — it is not decodable as plain UTF-8 text
# (it contains RTF control codes) even though a naive glance might mistake
# it for one; DOCX is deliberately NOT included either (would require the
# new `python-docx` dependency, out of scope for v1).
SUPPORTED_MIME_TYPES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "text/plain",
})

PROMPT_VERSION = "v1"
DEFAULT_MODEL = "claude-sonnet-4-5"

# Deterministic size safeguards — enforced in code, never left to the
# model "following instructions" in the prompt. Google Sheets has a
# 50,000-char/cell hard limit; these bounds keep every field far below
# that with a wide safety margin, and are applied BEFORE any write.
TEXT_PREVIEW_MAX_CHARS = 500
AI_SUMMARY_MAX_CHARS = 500
ANALYSIS_ERROR_MAX_CHARS = 500
DETECTED_TYPE_MAX_CHARS = 100
LANGUAGE_MAX_CHARS = 20
MAX_KEYWORDS_COUNT = 20
MAX_KEYWORD_CHARS = 80
MAX_EXTRACTED_FIELDS_COUNT = 30
MAX_EXTRACTED_FIELD_KEY_CHARS = 80
MAX_EXTRACTED_FIELD_VALUE_CHARS = 300
# Absolute defense-in-depth ceiling on the SERIALIZED JSON string itself
# (after the per-item bounds above already keep it far smaller in
# practice) — if ever exceeded, the stored value is replaced with a
# deterministic, still-valid-JSON truncation marker rather than emitting
# a partially-cut, unparseable JSON string.
MAX_JSON_FIELD_CHARS = 4000

# Deterministic, non-fuzzy template-match confidence for an exact
# (trim + casefold) match against document_template_registry's Title or
# Document Type field. No match at all -> "" / 0.0, never guessed.
TEMPLATE_MATCH_CONFIDENCE = 0.9


def is_supported_mime_type(mime_type: str) -> bool:
    return (mime_type or "").strip().lower() in SUPPORTED_MIME_TYPES


def compute_content_hash(file_bytes: bytes) -> str:
    """SHA-256 of the analyzed file's bytes — stored alongside Prompt
    Version so future code can detect stale analysis (different file
    content or a newer prompt) without silently reprocessing it."""
    return hashlib.sha256(file_bytes).hexdigest()


def _bounded_str(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def bounded_text_preview(text: str) -> str:
    return _bounded_str(text, TEXT_PREVIEW_MAX_CHARS)


def bounded_summary(text: str) -> str:
    return _bounded_str(text, AI_SUMMARY_MAX_CHARS)


def bounded_error(text: str) -> str:
    return _bounded_str(text, ANALYSIS_ERROR_MAX_CHARS)


def bounded_keywords(keywords: list) -> list:
    """Caps both the NUMBER of keywords and each keyword's length —
    applied to the data before JSON serialization, so the resulting JSON
    is always valid (never a truncated/cut-off JSON string)."""
    return [_bounded_str(k, MAX_KEYWORD_CHARS) for k in (keywords or [])[:MAX_KEYWORDS_COUNT]]


def bounded_extracted_fields(fields: dict) -> dict:
    """Caps both the NUMBER of fields and each key/value's length —
    same rationale as bounded_keywords(): bound the data, not the
    serialized string, so the result is always valid JSON."""
    bounded = {}
    for i, (key, value) in enumerate((fields or {}).items()):
        if i >= MAX_EXTRACTED_FIELDS_COUNT:
            break
        bounded_key = _bounded_str(str(key), MAX_EXTRACTED_FIELD_KEY_CHARS)
        bounded_value = _bounded_str(str(value), MAX_EXTRACTED_FIELD_VALUE_CHARS)
        bounded[bounded_key] = bounded_value
    return bounded


def bounded_json(obj) -> str:
    """Deterministic JSON serialization (sort_keys, ensure_ascii=False)
    with an absolute defense-in-depth length ceiling: if the serialized
    string somehow still exceeds MAX_JSON_FIELD_CHARS despite the
    per-item bounds already applied to its contents, the stored value is
    replaced with a small, deterministic, still-valid-JSON marker —
    never a partially-cut/unparseable string."""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    if len(text) <= MAX_JSON_FIELD_CHARS:
        return text
    return json.dumps({"_truncated": True}, sort_keys=True, ensure_ascii=False)


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_content_status(document_id: str) -> dict | None:
    """Read-only: current DOCUMENT_CONTENT row for document_id, or None."""
    from business_core.sheets import find_row_by_id

    found = find_row_by_id("document_content", document_id)
    return found[1] if found else None


def decide_action(existing_row: dict | None, force: bool = False) -> str:
    """
    Pure decision function (no I/O) — one of:
        "proceed", "skip_completed", "skip_processing",
        "skip_failed", "skip_unsupported"

    "processing" is NEVER interrupted by force=True — force only applies
    to completed/failed/unsupported, per the approved architecture.
    """
    if existing_row is None:
        return "proceed"

    status = (existing_row.get("Content Status") or "").strip()
    if status == "processing":
        return "skip_processing"
    if status == "completed":
        return "proceed" if force else "skip_completed"
    if status in ("failed", "unsupported"):
        return "proceed" if force else f"skip_{status}"
    # "pending" or any unrecognized/empty status — proceed defensively
    # rather than getting permanently stuck.
    return "proceed"


def build_analysis_prompt() -> str:
    return (
        "Ты анализируешь один бизнес-документ (скан, PDF, фото или "
        "текстовый файл) для внутренней системы учёта документов. "
        "Верни СТРОГО валидный JSON и ничего кроме него — без markdown "
        "code fences, без пояснений до или после — в точности в этом "
        "формате:\n\n"
        "{\n"
        '  "document_type": "краткая метка типа документа на английском, '
        'snake_case, например: passport, technical_passport, contract, '
        'invoice, cadastral_extract, unknown",\n'
        '  "summary": "краткое резюме содержимого документа, 1-3 '
        'предложения",\n'
        '  "language": "код языка документа, например ru, kk, en",\n'
        '  "page_count": число_страниц_или_null,\n'
        '  "keywords": ["ключевые", "слова", "документа"],\n'
        '  "extracted_fields": {"имя_поля": "значение"},\n'
        '  "text_preview": "короткая выдержка из документа, не более 500 '
        'символов"\n'
        "}\n\n"
        "Если не уверен в значении поля — используй пустую строку, пустой "
        "массив/объект или null. Никогда не выдумывай факты, которых нет "
        "в документе."
    )


def parse_and_validate_ai_result(raw_text: str) -> dict | None:
    """
    Never trust unvalidated model output. Returns a fully-typed dict with
    safe defaults for any field that doesn't match the expected shape, or
    None if the response isn't parseable JSON at all (or isn't a JSON
    object) — callers must treat None as an analysis failure.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    document_type = data.get("document_type")
    summary = data.get("summary")
    language = data.get("language")
    page_count = data.get("page_count")
    keywords = data.get("keywords")
    extracted_fields = data.get("extracted_fields")
    text_preview = data.get("text_preview")

    if not isinstance(document_type, str):
        document_type = ""
    if not isinstance(summary, str):
        summary = ""
    if not isinstance(language, str):
        language = ""
    if page_count is not None and not isinstance(page_count, int):
        page_count = None
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        keywords = []
    if not isinstance(extracted_fields, dict):
        extracted_fields = {}
    if not isinstance(text_preview, str):
        text_preview = ""

    return {
        "document_type": document_type.strip(),
        "summary": summary.strip(),
        "language": language.strip(),
        "page_count": page_count,
        "keywords": keywords,
        "extracted_fields": extracted_fields,
        "text_preview": text_preview,
    }


def match_template_suggestion(document_type: str) -> tuple[str, float]:
    """
    Deterministic, non-fuzzy: normalized (trim + casefold) exact match of
    the AI-detected document_type against document_template_registry's
    Title or Document Type field. No confident match -> ("", 0.0).

    This is a SUGGESTION ONLY. The Document Template ID the user supplied
    at registration time (if any) is authoritative and is never read,
    compared, or overwritten by this function or by analyze_document().
    """
    from business_core.sheets import read_business_sheet

    normalized = (document_type or "").strip().casefold()
    if not normalized:
        return "", 0.0

    for tmpl in read_business_sheet("document_template_registry"):
        title = (tmpl.get("Title", "") or "").strip().casefold()
        doc_type_field = (tmpl.get("Document Type", "") or "").strip().casefold()
        if normalized == title or normalized == doc_type_field:
            return tmpl.get("Document Template ID", ""), TEMPLATE_MATCH_CONFIDENCE

    return "", 0.0


def _build_content_block(mime_type: str, file_bytes: bytes) -> dict:
    mt = (mime_type or "").strip().lower()
    if mt == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(file_bytes).decode("ascii"),
            },
        }
    if mt in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mt,
                "data": base64.standard_b64encode(file_bytes).decode("ascii"),
            },
        }
    if mt == "text/plain":
        return {"type": "text", "text": file_bytes.decode("utf-8", errors="replace")}
    raise ValueError(f"Unsupported mime_type for content block: {mime_type}")


def _download_drive_file_bytes(service, drive_file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    from integrations.google_drive_adapter import _is_shared_drive

    kwargs: dict = {"fileId": drive_file_id}
    if _is_shared_drive():
        kwargs["supportsAllDrives"] = True

    request = service.files().get_media(**kwargs)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _finalize(document_id: str, status: str, error: str, now: str) -> None:
    """Last-resort terminal-status writer — guarantees a row is never left
    stuck at "processing" no matter where in analyze_document() things
    went wrong."""
    from business_core.sheets import find_row_by_id, update_business_row

    found = find_row_by_id("document_content", document_id)
    if not found:
        log.error(f"_finalize({document_id}): row disappeared mid-analysis, cannot finalize")
        return
    row_num, _ = found
    update_business_row("document_content", row_num, {
        "Content Status": status,
        "Analysis Error": bounded_error(error),
        "Updated At": now,
    })


def analyze_document(document_id: str, drive_file_id: str, force: bool = False) -> dict:
    """
    Synchronous, idempotent. Intended to be called from inside a Telegram
    job_queue callback (or directly, e.g. from tests) — never awaited
    itself, matching every other Sheets/Drive/Anthropic call already made
    synchronously elsewhere in this codebase.

    Returns:
        {"ok": bool, "action": str, "document_id": str, "error": str | None}
    """
    from business_core.sheets import (
        append_business_row, find_row_by_id, get_business_sheet,
        row_from_header_map, update_business_row,
    )

    existing_found = find_row_by_id("document_content", document_id)
    existing_row = existing_found[1] if existing_found else None
    action = decide_action(existing_row, force=force)

    if action != "proceed":
        return {"ok": True, "action": action, "document_id": document_id, "error": None}

    now = _now_utc_str()

    # Claim step — synchronous, no `await`/network-yield in between the
    # decision above and this write, so a second near-simultaneous trigger
    # (in this single-process event loop) always observes this claim (or
    # a later terminal state) rather than racing past it.
    if existing_row is None:
        headers = get_business_sheet("document_content").row_values(1)
        row = row_from_header_map(headers, {
            "Document ID": document_id,
            "Drive File ID": drive_file_id,
            "Content Status": "processing",
            "Prompt Version": PROMPT_VERSION,
            "Analysis Started At": now,
            "Created At": now,
            "Updated At": now,
        })
        append_business_row("document_content", row)
    else:
        row_num, _ = existing_found
        update_business_row("document_content", row_num, {
            "Content Status": "processing",
            "Analysis Started At": now,
            "Updated At": now,
        })

    try:
        doc_found = find_row_by_id("document_registry", document_id)
        if not doc_found:
            _finalize(document_id, "failed", "Document Registry row not found", _now_utc_str())
            return {"ok": False, "action": "failed", "document_id": document_id,
                    "error": "Document Registry row not found"}

        _, doc_row = doc_found
        mime_type = doc_row.get("Mime Type", "")

        if not is_supported_mime_type(mime_type):
            error = f"Unsupported MIME type: {mime_type or '(empty)'}"
            _finalize(document_id, "unsupported", error, _now_utc_str())
            return {"ok": True, "action": "unsupported", "document_id": document_id, "error": error}

        try:
            from integrations.google_drive_adapter import get_drive_service
            service = get_drive_service()
            file_bytes = _download_drive_file_bytes(service, drive_file_id)
        except Exception as exc:
            error = f"Drive download error: {exc}"
            log.error(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str())
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        content_hash = compute_content_hash(file_bytes)

        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            error = "ANTHROPIC_API_KEY не задан — анализ пропущен"
            log.warning(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str())
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        model = os.getenv("DOCUMENT_INTELLIGENCE_MODEL", "").strip() or DEFAULT_MODEL

        try:
            import anthropic

            block = _build_content_block(mime_type, file_bytes)
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [block, {"type": "text", "text": build_analysis_prompt()}],
                }],
            )
            raw_text = msg.content[0].text
        except Exception as exc:
            error = f"AI call error: {exc}"
            log.error(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str())
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        parsed = parse_and_validate_ai_result(raw_text)
        if parsed is None:
            error = "AI вернул невалидный/неразбираемый JSON"
            log.error(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str())
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        suggested_template_id, confidence = match_template_suggestion(parsed["document_type"])

        completed_at = _now_utc_str()
        row_num, _ = find_row_by_id("document_content", document_id)
        update_business_row("document_content", row_num, {
            "Content Status": "completed",
            "Detected Document Type": _bounded_str(parsed["document_type"], DETECTED_TYPE_MAX_CHARS),
            "Suggested Document Template ID": suggested_template_id,
            "Template Match Confidence": f"{confidence:.2f}",
            "AI Summary": bounded_summary(parsed["summary"]),
            "Extracted Fields JSON": bounded_json(bounded_extracted_fields(parsed["extracted_fields"])),
            "Text Preview": bounded_text_preview(parsed["text_preview"]),
            "Language": _bounded_str(parsed["language"], LANGUAGE_MAX_CHARS),
            "Page Count": "" if parsed["page_count"] is None else str(parsed["page_count"]),
            "Keywords JSON": bounded_json(bounded_keywords(parsed["keywords"])),
            "Model": model,
            "Content Hash": content_hash,
            "Analysis Completed At": completed_at,
            "Analysis Error": "",
            "Updated At": completed_at,
        })
        return {"ok": True, "action": "completed", "document_id": document_id, "error": None}

    except Exception as exc:
        # Absolute last-resort safety net: never leave a row stuck at
        # "processing" on a totally unexpected error.
        error = f"Unexpected error: {exc}"
        log.error(f"analyze_document({document_id}): {error}")
        _finalize(document_id, "failed", error, _now_utc_str())
        return {"ok": False, "action": "failed", "document_id": document_id, "error": error}
