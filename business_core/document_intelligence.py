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
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Phase 16B.1 (2026-07-28): Sheets quota mitigation contract, reused as-is
# from business_core.sheets (no second retry helper). A 429/5xx/network
# failure during analysis must never be reported as a generic AI/analysis
# "failed" (indistinguishable from "the model returned garbage") — these
# two fixed, machine-readable prefixes let document_query/telegram_handlers
# recognize a transient-infra failure from the stored Analysis Error text
# without adding a new Content Status enum value (CONTENT_STATUS_VALUES is
# unchanged — "failed" is still the terminal state used, just with a
# recognizable error-text prefix).
QUOTA_ERROR_PREFIX = "SHEETS_QUOTA_EXCEEDED: "
TRANSIENT_ERROR_PREFIX = "TRANSIENT_SHEETS_READ_ERROR: "

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


DUPLICATE_STATUS_VALUES = ("", "EXACT_DUPLICATE", "NEW_DOCUMENT")


@dataclass(frozen=True)
class ExactDuplicateResult:
    """
    Phase 16B.1: result of find_exact_duplicate(). `status` is always one
    of "EXACT_DUPLICATE" | "NEW_DOCUMENT" — never a third "unknown" value
    (a pre-16B.1 DOCUMENT_CONTENT row simply has an empty "Duplicate
    Status" cell until re-analyzed, which is a schema-level absence, not
    a value this dataclass itself ever produces).
    """
    status: str
    duplicate_of_document_id: str = ""
    duplicate_document_status: str = ""
    duplicate_document_name: str = ""
    content_hash: str = ""
    checked_at: str = ""
    warnings: tuple = ()


def find_exact_duplicate(document_id: str, business_id: str, content_hash: str) -> ExactDuplicateResult:
    """
    Deterministic exact-duplicate detection — same non-empty Content
    Hash, same Business ID, a different Document ID that exists in
    DOCUMENT_REGISTRY. Every Document Status participates (rejected/
    archived/superseded included): this detects PHYSICAL file identity,
    not business validity — the candidate's Status is only ever surfaced
    for display, never used to exclude it from matching.

    Canonical-selection algorithm (structurally cycle-free): among the
    WHOLE matching set (this document included), the canonical one is
    whichever has the earliest "Created At", tie-broken by the
    lexicographically smallest Document ID. A candidate with a missing/
    malformed (empty) Created At is NEVER preferred over one with a real
    value — an empty string would otherwise sort first lexicographically
    and let corrupted data falsely claim "oldest"/canonical status; the
    fallback to Document ID applies only once Created At is tied
    (including the case where every candidate's Created At is empty),
    making the choice deterministic and independent of Google Sheets row
    order in every case. If this document itself is the canonical one,
    the result is NEW_DOCUMENT — even if newer duplicates of it already
    exist elsewhere — a document can never be reported as "a duplicate
    of" one created after it, no matter how many times it is re-analyzed
    (this is a pure function of the whole set on every call, so it can
    never disagree with itself and form a cycle like DOC-1 duplicate_of
    DOC-2 / DOC-2 duplicate_of DOC-1).

    Never used to skip/reuse another document's AI analysis, never
    changes Document Family/Version/Template ID/Status/relations — purely
    informational.

    Read-only: at most one full DOCUMENT_CONTENT read and one full
    DOCUMENT_REGISTRY read (via read_business_sheet(), already quota-safe
    — see business_core.sheets.read_with_retry()) — never a per-candidate
    find_row_by_id()/find_document_by_id() lookup.
    """
    now = _now_utc_str()

    if not content_hash:
        return ExactDuplicateResult(
            status="NEW_DOCUMENT", content_hash=content_hash, checked_at=now,
            warnings=("Пустой Content Hash — проверка дублей пропущена.",),
        )

    from business_core.sheets import read_business_sheet

    content_rows = read_business_sheet("document_content")
    same_hash_ids = {
        r.get("Document ID", "") for r in content_rows
        if (r.get("Content Hash", "") or "") == content_hash
    }
    same_hash_ids.add(document_id)  # always include self in the candidate set, even on a first-ever analysis

    if len(same_hash_ids) <= 1:
        return ExactDuplicateResult(status="NEW_DOCUMENT", content_hash=content_hash, checked_at=now)

    registry_rows = read_business_sheet("document_registry")
    registry_by_id = {r.get("Document ID", ""): r for r in registry_rows}

    warnings: list[str] = []
    candidates: list[tuple] = []
    for doc_id in same_hash_ids:
        row = registry_by_id.get(doc_id)
        if row is None:
            if doc_id != document_id:
                warnings.append(f"{doc_id}: не найден в DOCUMENT_REGISTRY — исключён из сравнения")
            continue
        if row.get("Business ID", "") != business_id:
            continue  # different Business — never a duplicate candidate
        candidates.append((row.get("Created At", ""), doc_id, row))

    if len(candidates) <= 1 or document_id not in {c[1] for c in candidates}:
        return ExactDuplicateResult(
            status="NEW_DOCUMENT", content_hash=content_hash, checked_at=now, warnings=tuple(warnings),
        )

    # Sort key: candidates with a real (non-empty) Created At always sort
    # before any candidate with a missing/malformed one — an empty string
    # would otherwise sort FIRST lexicographically and let a document
    # with corrupted/missing Created At data falsely claim "oldest"
    # (canonical) status ahead of a genuinely older document. Only when
    # Created At is missing/tied does the ordering fall back to Document
    # ID — deterministic, independent of Google Sheets row order.
    candidates.sort(key=lambda c: (0 if c[0] else 1, c[0], c[1]))
    _, canonical_id, canonical_row = candidates[0]

    if canonical_id == document_id:
        return ExactDuplicateResult(
            status="NEW_DOCUMENT", content_hash=content_hash, checked_at=now, warnings=tuple(warnings),
        )

    return ExactDuplicateResult(
        status="EXACT_DUPLICATE",
        duplicate_of_document_id=canonical_id,
        duplicate_document_status=canonical_row.get("Status", ""),
        duplicate_document_name=canonical_row.get("Document Name", ""),
        content_hash=content_hash,
        checked_at=now,
        warnings=tuple(warnings),
    )


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


def _finalize(document_id: str, status: str, error: str, now: str, row_num: int | None = None) -> None:
    """
    Last-resort terminal-status writer — guarantees a row is never left
    stuck at "processing" no matter where in analyze_document() things
    went wrong.

    `row_num` (Phase 16B.1, optional): if the caller already knows the
    row number (e.g. from the claim step's own update/append), it is
    reused instead of a second find_row_by_id() lookup. Default None
    preserves the exact prior behavior (always a fresh lookup).

    Phase 16B.1: this function's own find_row_by_id() call is wrapped so
    a 429/5xx/network failure here (finalizing an already-broken
    analysis) is logged and swallowed rather than propagating out of a
    function whose entire purpose is "the last-resort safety net" — if
    THIS also raised, analyze_document()'s own outer except could not
    guarantee a terminal status any more than before, but it must never
    itself become a second, unhandled crash.
    """
    from business_core.sheets import find_row_by_id, update_business_row, SheetsReadError

    if row_num is None:
        try:
            found = find_row_by_id("document_content", document_id)
        except SheetsReadError as exc:
            log.error(f"_finalize({document_id}): could not re-read row to finalize: {exc}")
            return
        if not found:
            log.error(f"_finalize({document_id}): row disappeared mid-analysis, cannot finalize")
            return
        row_num, _ = found

    try:
        update_business_row("document_content", row_num, {
            "Content Status": status,
            "Analysis Error": bounded_error(error),
            "Updated At": now,
        })
    except SheetsReadError as exc:
        # update_business_row() itself reads headers before writing —
        # same rationale as above, never let the safety net raise.
        log.error(f"_finalize({document_id}): could not write terminal status: {exc}")


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
        row_from_header_map, update_business_row, read_with_retry,
        SheetsQuotaExceededError, TransientSheetsReadError,
    )

    # Phase 16B.1: a 429/5xx/network failure on this very first read must
    # never be reported as a generic analysis "failed" — nothing has been
    # claimed/written yet at this point, so it's fully safe to just return
    # a distinguishable action and let the caller retry (background job:
    # logged and dropped; /analyzedoc: its own caller sees this exception
    # — see below).
    try:
        existing_found = find_row_by_id("document_content", document_id)
    except SheetsQuotaExceededError as exc:
        log.warning(f"analyze_document({document_id}): quota exceeded before claim: {exc}")
        return {"ok": False, "action": "quota_exceeded", "document_id": document_id, "error": str(exc)}
    except TransientSheetsReadError as exc:
        log.warning(f"analyze_document({document_id}): transient read error before claim: {exc}")
        return {"ok": False, "action": "transient_read_error", "document_id": document_id, "error": str(exc)}

    existing_row = existing_found[1] if existing_found else None
    action = decide_action(existing_row, force=force)

    if action != "proceed":
        return {"ok": True, "action": action, "document_id": document_id, "error": None}

    now = _now_utc_str()

    # Claim step — synchronous, no `await`/network-yield in between the
    # decision above and this write, so a second near-simultaneous trigger
    # (in this single-process event loop) always observes this claim (or
    # a later terminal state) rather than racing past it.
    #
    # `claimed_row_num` (Phase 16B.1): known immediately on a re-analysis
    # (the row already existed) — reused by every _finalize() call below
    # instead of a fresh find_row_by_id() lookup. On a first-ever analysis
    # (append branch) the new row's number isn't known without a fresh
    # read, so it stays None there (unavoidable — append_business_row()
    # doesn't return the new row index).
    claimed_row_num: int | None = None
    if existing_row is None:
        headers = read_with_retry(get_business_sheet("document_content").row_values, 1)
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
        claimed_row_num, _ = existing_found
        update_business_row("document_content", claimed_row_num, {
            "Content Status": "processing",
            "Analysis Started At": now,
            "Updated At": now,
        })

    try:
        doc_found = find_row_by_id("document_registry", document_id)
        if not doc_found:
            _finalize(document_id, "failed", "Document Registry row not found", _now_utc_str(),
                      row_num=claimed_row_num)
            return {"ok": False, "action": "failed", "document_id": document_id,
                    "error": "Document Registry row not found"}

        _, doc_row = doc_found
        mime_type = doc_row.get("Mime Type", "")
        business_id = doc_row.get("Business ID", "")

        if not is_supported_mime_type(mime_type):
            error = f"Unsupported MIME type: {mime_type or '(empty)'}"
            _finalize(document_id, "unsupported", error, _now_utc_str(), row_num=claimed_row_num)
            return {"ok": True, "action": "unsupported", "document_id": document_id, "error": error}

        try:
            from integrations.google_drive_adapter import get_drive_service
            service = get_drive_service()
            file_bytes = _download_drive_file_bytes(service, drive_file_id)
        except Exception as exc:
            error = f"Drive download error: {exc}"
            log.error(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        content_hash = compute_content_hash(file_bytes)

        # Phase 16B.1: exact-duplicate detection, right after the hash is
        # known and before the (expensive) AI call — per the approved
        # order. Best-effort only: a failure here is logged and treated
        # as "no duplicate info available this run", it NEVER fails the
        # whole analysis (duplicate detection is informational, not a
        # precondition for AI analysis to proceed — an exact duplicate is
        # never used to skip or reuse another document's AI result in
        # this phase).
        duplicate_result = None
        try:
            duplicate_result = find_exact_duplicate(document_id, business_id, content_hash)
        except Exception as exc:
            log.warning(f"analyze_document({document_id}): duplicate check failed (non-fatal): {exc}")

        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            error = "ANTHROPIC_API_KEY не задан — анализ пропущен"
            log.warning(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
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
            _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        parsed = parse_and_validate_ai_result(raw_text)
        if parsed is None:
            error = "AI вернул невалидный/неразбираемый JSON"
            log.error(f"analyze_document({document_id}): {error}")
            _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
            return {"ok": False, "action": "failed", "document_id": document_id, "error": error}

        suggested_template_id, confidence = match_template_suggestion(parsed["document_type"])

        completed_at = _now_utc_str()
        if claimed_row_num is not None:
            row_num = claimed_row_num
        else:
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

        # Phase 16B.1: duplicate fields are written as a SEPARATE,
        # best-effort follow-up call — never merged into the update above.
        # update_business_row() raises ValueError if ANY key it's given
        # isn't an actual header on the real Sheet; the 3 new duplicate
        # columns must be added to the live DOCUMENT_CONTENT sheet before
        # this code can write them (this schema change is additive-only in
        # code — see business_core/sheets.py — but the physical Sheet
        # header row itself is not auto-migrated). Keeping this in its own
        # try/except means a not-yet-migrated production Sheet degrades to
        # "duplicate fields simply not written yet", never to "the entire
        # completed analysis silently reverts to failed".
        if duplicate_result is not None:
            try:
                update_business_row("document_content", row_num, {
                    "Duplicate Status": duplicate_result.status,
                    "Duplicate Of Document ID": duplicate_result.duplicate_of_document_id,
                    "Duplicate Checked At": duplicate_result.checked_at,
                })
            except Exception as exc:
                log.warning(
                    f"analyze_document({document_id}): could not write duplicate fields "
                    f"(non-fatal, analysis itself already completed): {exc}"
                )

        return {"ok": True, "action": "completed", "document_id": document_id, "error": None}

    except (SheetsQuotaExceededError, TransientSheetsReadError) as exc:
        # Phase 16B.1: a 429/5xx/network failure anywhere in the analysis
        # read-path (Registry mime lookup, template-match full-table read,
        # or the pre-final-write row lookup) is never the same thing as
        # "the AI/document itself is broken" — finalize with the SAME
        # terminal "failed" Content Status (CONTENT_STATUS_VALUES is
        # unchanged, no new enum value), but with a recognizable, fixed
        # error-text prefix so document_query/telegram_handlers can render
        # a safe, distinct, retry-encouraging message instead of a generic
        # analysis-failure one (see QUOTA_ERROR_PREFIX/TRANSIENT_ERROR_PREFIX).
        is_quota = isinstance(exc, SheetsQuotaExceededError)
        prefix = QUOTA_ERROR_PREFIX if is_quota else TRANSIENT_ERROR_PREFIX
        action = "quota_exceeded" if is_quota else "transient_read_error"
        error = f"{prefix}{exc}"
        log.warning(f"analyze_document({document_id}): {error}")
        _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
        return {"ok": False, "action": action, "document_id": document_id, "error": error}

    except Exception as exc:
        # Absolute last-resort safety net: never leave a row stuck at
        # "processing" on a totally unexpected error.
        error = f"Unexpected error: {exc}"
        log.error(f"analyze_document({document_id}): {error}")
        _finalize(document_id, "failed", error, _now_utc_str(), row_num=claimed_row_num)
        return {"ok": False, "action": "failed", "document_id": document_id, "error": error}
